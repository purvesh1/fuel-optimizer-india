import pandas as pd
# import geopandas as gpd # Not strictly needed for this script if not using districts_gdf functionality beyond plotting
import folium
from folium.features import GeoJson, TopoJson
import openrouteservice
import time
import json
import os
import re

# --- Configuration ---
# 1. API Key
try:
    with open("config.json") as f:
        ORS_API_KEY = json.load(f)["openrouteservice_api_key"]
except FileNotFoundError:
    print("Error: 'config.json' not found. Please create it with your OpenRouteService API key.")
    exit()
except KeyError:
    print("Error: 'openrouteservice_api_key' not found in 'config.json'.")
    exit()

client = openrouteservice.Client(key=ORS_API_KEY)

# 2. File Paths
DISTRICTS_FILE_PATH = 'india-districts.json'
CSV_CITIES_FILE_PATH = 'india-diesel-22may25.csv'
OUTPUT_MAP_FILE = 'india_routes_and_cities_map_v3.html'
OUTPUT_DIR_ROUTES_GEOJSON = 'routes_geojson_output'
OUTPUT_CSV_CITIES_GEOJSON = 'csv_geocoded_cities_v3.geojson'

os.makedirs(OUTPUT_DIR_ROUTES_GEOJSON, exist_ok=True)

# 3. CSV Column Names
CSV_CITY_COLUMN = 'City'
CSV_PRICE_COLUMN = 'Price'

# 4. Pre-defined City Coordinates (FROM YOUR INPUT)
cities_coords_provided = {
    'Baghola, Haryana': (29.143027, 76.342784), # Corrected to (lat, lon)
    'Bangalore, Karnataka': (12.96557, 77.60625),# Corrected to (lat, lon)
    'Chittorgarh, Rajasthan': (24.878835, 74.645359),# Corrected to (lat, lon)
    'Haridwar, Uttarakhand': (29.926373, 78.132662),# Corrected to (lat, lon)
    'Hosur, Tamil Nadu': (12.7335, 77.826319),# Corrected to (lat, lon)
    'Raigarh, Chhattisgarh': (21.9, 83.4),# Corrected to (lat, lon)
    'Toranagallu, Karnataka': (15.19556, 76.67782) # Corrected to (lat, lon)
}
# Note: I've assumed the coordinates you provided were (lon, lat) and switched them to (lat, lon)
# as commonly used for latitude, longitude order. Please verify if this assumption is correct for your source.
# If your source was already (lat, lon), then my original interpretation was fine.
# The geocode_location function returns (lat, lon).

# 5. Routes Configuration
routes_to_process_config = {
    "Toranagallu - Baghola": {"cities": ["Toranagallu, Karnataka", "Baghola, Haryana"]},
    "Baghola - Chittorgarh": {"cities": ["Baghola, Haryana", "Chittorgarh, Rajasthan"]},
    "Chittorgarh - Hosur": {"cities": ["Chittorgarh, Rajasthan", "Hosur, Tamil Nadu"]},
    "Haridwar - Bangalore": {"cities": ["Haridwar, Uttarakhand", "Bangalore, Karnataka"]},
    "Raigarh - Toranagallu": {"cities": ["Raigarh, Chhattisgarh", "Toranagallu, Karnataka"]}
}
# --- End of Configuration ---

# --- Helper Function for Geocoding (with cache) ---
geocode_cache = {}
def geocode_location(location_name, ors_client, is_city_from_csv=False):
    if location_name in geocode_cache:
        return geocode_cache[location_name]
    print(f"  Geocoding via API: {location_name} ...") # Indicate API call
    try:
        search_text = location_name
        if is_city_from_csv and "," not in location_name:
            search_text = f"{location_name}, India"
        
        geocode_params = {'text': search_text, 'size': 1}
        try:
            geocode_result = ors_client.pelias_search(**geocode_params, boundary_country=['IND'])
        except TypeError:
            print(f"    (Note: 'boundary_country' not supported by this openrouteservice-py version for {location_name}. Geocoding globally if 'India' not in text.)")
            geocode_result = ors_client.pelias_search(**geocode_params)
        time.sleep(1.6)

        if geocode_result and geocode_result.get('features'):
            coords_lon_lat = geocode_result['features'][0]['geometry']['coordinates']
            result = (coords_lon_lat[1], coords_lon_lat[0]) # (lat, lon)
            geocode_cache[location_name] = result
            print(f"    API SUCCESS: {location_name} -> {result}")
            return result
        else:
            print(f"    API WARNING: Could not geocode {location_name}.")
            geocode_cache[location_name] = None
            return None
    except openrouteservice.exceptions.ApiError as e:
        print(f"    API ERROR geocoding {location_name}: {e.status_code if hasattr(e, 'status_code') else 'N/A'} - {e}")
        geocode_cache[location_name] = None
        return None
    except Exception as e:
        print(f"    OTHER ERROR geocoding {location_name}: {e}")
        geocode_cache[location_name] = None
        return None

# --- Initialize Folium Map ---
map_center = [20.5937, 78.9629]
india_map = folium.Map(location=map_center, zoom_start=5, tiles="CartoDB positron")

# --- 1. Load and Plot District Boundaries ---
print(f"\n--- Loading District Boundaries from: {DISTRICTS_FILE_PATH} ---")
try:
    with open(DISTRICTS_FILE_PATH, 'r', encoding='utf-8') as f:
        district_json_data = json.load(f)
    object_key = None
    if district_json_data.get('type', '').lower() == 'topology' and district_json_data.get('objects'):
        object_key = list(district_json_data['objects'].keys())[0]
    if object_key:
        folium.TopoJson(district_json_data, object_path=f'objects.{object_key}', name='District Boundaries',
                        style_function=lambda x: {'color': '#888888', 'weight': 0.5, 'fillOpacity': 0.05}).add_to(india_map)
        print("  District boundaries (TopoJSON) added to map.")
    elif district_json_data.get('type', '').lower() == 'featurecollection':
         folium.GeoJson(district_json_data, name='District Boundaries',
                        style_function=lambda x: {'color': '#888888', 'weight': 0.5, 'fillOpacity': 0.05}).add_to(india_map)
         print("  District boundaries (GeoJSON) added to map.")
    else:
        print("  Could not determine TopoJSON object or not a recognized GeoJSON. Skipping district layer.")
except FileNotFoundError:
    print(f"  WARNING: Districts file '{DISTRICTS_FILE_PATH}' not found. Skipping district boundaries layer.")
except Exception as e:
    print(f"  WARNING: Could not load or plot district boundaries: {e}")

# --- 2. Process, Plot, and Save Routes ---
print("\n--- Processing, Plotting, and Saving Routes ---")
route_group = folium.FeatureGroup(name="Driving Routes")
for route_name, route_info in routes_to_process_config.items():
    print(f"Processing route: {route_name}")
    city_names = route_info['cities']
    start_city_name, end_city_name = city_names[0], city_names[-1]

    # --- MODIFICATION: Use provided coordinates first ---
    start_coords_latlon = cities_coords_provided.get(start_city_name)
    if start_coords_latlon:
        print(f"  Using provided coordinates for {start_city_name}: {start_coords_latlon}")
    else:
        print(f"  Provided coordinates not found for {start_city_name}. Attempting API geocoding...")
        start_coords_latlon = geocode_location(start_city_name, client)

    end_coords_latlon = cities_coords_provided.get(end_city_name)
    if end_coords_latlon:
        print(f"  Using provided coordinates for {end_city_name}: {end_coords_latlon}")
    else:
        print(f"  Provided coordinates not found for {end_city_name}. Attempting API geocoding...")
        end_coords_latlon = geocode_location(end_city_name, client)
    # --- End of MODIFICATION ---

    if start_coords_latlon and end_coords_latlon:
        # Ensure coords are (lat, lon) for ORS input [lon, lat]
        ors_request_coords = [[start_coords_latlon[1], start_coords_latlon[0]], [end_coords_latlon[1], end_coords_latlon[0]]]
        try:
            print(f"  Fetching driving directions for {route_name}...")
            route_directions_geojson = client.directions(
                coordinates=ors_request_coords, profile='driving-car', format='geojson', instructions=False
            )
            time.sleep(1.6)

            if route_directions_geojson and route_directions_geojson.get('features'):
                clean_route_name = re.sub(r'[^\w_.)( -]', '', route_name).replace(' ', '_')
                route_geojson_filename = os.path.join(OUTPUT_DIR_ROUTES_GEOJSON, f"Route_{clean_route_name}.geojson")
                with open(route_geojson_filename, 'w') as f_route_geojson:
                    json.dump(route_directions_geojson, f_route_geojson, indent=2)
                print(f"  Route GeoJSON saved to: {route_geojson_filename}")

                folium.GeoJson(
                    route_directions_geojson, name=f"Route: {route_name}", tooltip=route_name,
                    style_function=lambda x: {'color': 'blue', 'weight': 3, 'opacity': 0.7}
                ).add_to(route_group)
                print(f"  Route '{route_name}' plotted.")
            else:
                print(f"  WARNING: Could not get route geometry for {route_name}.")
        except openrouteservice.exceptions.ApiError as e:
            print(f"  ERROR (API) fetching route for {route_name}: {e}")
        except Exception as e:
            print(f"  ERROR (Other) fetching route for {route_name}: {e}")
    else:
        print(f"  Skipping route '{route_name}' due to geocoding failure of endpoints.")
route_group.add_to(india_map)

# --- 3. Process, Plot, and Save Cities from CSV ---
print(f"\n--- Processing, Plotting, and Saving Cities from CSV: {CSV_CITIES_FILE_PATH} ---")
city_markers_group = folium.FeatureGroup(name="Diesel Price Cities")
geocoded_cities_for_geojson = []

try:
    cities_df = pd.read_csv(CSV_CITIES_FILE_PATH)
    if CSV_CITY_COLUMN not in cities_df.columns or CSV_PRICE_COLUMN not in cities_df.columns:
        print(f"  ERROR: CSV must contain '{CSV_CITY_COLUMN}' and '{CSV_PRICE_COLUMN}' columns.")
    else:
        unique_cities_in_csv = cities_df[[CSV_CITY_COLUMN, CSV_PRICE_COLUMN]].drop_duplicates(subset=[CSV_CITY_COLUMN])
        print(f"  Found {len(unique_cities_in_csv)} unique city entries to process from CSV.")
        
        plotted_cities_count = 0
        for index, row in unique_cities_in_csv.iterrows():
            city_name = str(row[CSV_CITY_COLUMN])
            price = row[CSV_PRICE_COLUMN]
            
            # Check if this city from CSV is one of the pre-defined route endpoints
            city_coords_latlon = cities_coords_provided.get(city_name) # Try exact match first
            if not city_coords_latlon: # If not in pre-defined, try geocoding
                 city_coords_latlon = geocode_location(city_name, client, is_city_from_csv=True)
            else:
                print(f"  Using provided coordinates for CSV city {city_name}: {city_coords_latlon}")

            if city_coords_latlon:
                tooltip_text = f"City: {city_name}<br>Diesel Price: {price}"
                folium.CircleMarker(
                    location=city_coords_latlon, radius=5, color='red', fill=True, fill_color='red', fill_opacity=0.7,
                    tooltip=tooltip_text
                ).add_to(city_markers_group)
                plotted_cities_count += 1
                
                geocoded_cities_for_geojson.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [city_coords_latlon[1], city_coords_latlon[0]]}, # [lon, lat]
                    "properties": {"city_name_csv": city_name, "price_csv": price, 
                                   "latitude": city_coords_latlon[0], "longitude": city_coords_latlon[1]}
                })
            if (index + 1) % 10 == 0:
                 print(f"    Processed {index + 1}/{len(unique_cities_in_csv)} cities from CSV...")
        print(f"  Successfully plotted {plotted_cities_count} cities from CSV.")

        if geocoded_cities_for_geojson:
            cities_geojson_output_fc = {"type": "FeatureCollection", "features": geocoded_cities_for_geojson}
            with open(OUTPUT_CSV_CITIES_GEOJSON, 'w') as f_cities_geojson:
                json.dump(cities_geojson_output_fc, f_cities_geojson, indent=2)
            print(f"  Geocoded city locations from CSV saved to: {OUTPUT_CSV_CITIES_GEOJSON}")
        else:
            print("  No cities from CSV were successfully geocoded/found in provided coords to save to GeoJSON.")

except FileNotFoundError:
    print(f"  ERROR: CSV file '{CSV_CITIES_FILE_PATH}' not found.")
except Exception as e:
    print(f"  ERROR: Could not process CSV file for cities: {e}")
city_markers_group.add_to(india_map)

# --- Add Layer Control and Save Map ---
folium.LayerControl().add_to(india_map)
print(f"\n--- Saving Map to {OUTPUT_MAP_FILE} ---")
try:
    india_map.save(OUTPUT_MAP_FILE)
    print(f"Map successfully saved. You can open '{OUTPUT_MAP_FILE}' in a web browser.")
except Exception as e:
    print(f"Error saving map: {e}")

print("\n--- Processing Complete ---")