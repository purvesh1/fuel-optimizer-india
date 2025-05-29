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
CSV_CITIES_FILE_PATH = 'india-diesel-22may25.csv' # Input CSV
OUTPUT_MAP_FILE = 'india_routes_and_cities_map_v3.html'
OUTPUT_DIR_ROUTES_GEOJSON = 'routes_geojson_output'
OUTPUT_CSV_CITIES_GEOJSON = 'csv_geocoded_cities_v3.geojson' # Existing GeoJSON output for CSV cities
OUTPUT_CSV_WITH_DISTANCES = 'cities_with_distances_from_reference.csv' # New CSV output

os.makedirs(OUTPUT_DIR_ROUTES_GEOJSON, exist_ok=True)

# 3. CSV Column Names
CSV_CITY_COLUMN = 'City'
CSV_PRICE_COLUMN = 'Price'

# 4. Pre-defined City Coordinates (lat, lon)
cities_coords_provided = {
    'Baghola, Haryana': (29.143027, 76.342784),
    'Bangalore, Karnataka': (12.96557, 77.60625),
    'Chittorgarh, Rajasthan': (24.878835, 74.645359),
    'Haridwar, Uttarakhand': (29.926373, 78.132662),
    'Hosur, Tamil Nadu': (12.7335, 77.826319),
    'Raigarh, Chhattisgarh': (21.9, 83.4),
    'Toranagallu, Karnataka': (15.19556, 76.67782)
}

# 5. Routes Configuration
routes_to_process_config = {
    "Toranagallu - Baghola": {"cities": ["Toranagallu, Karnataka", "Baghola, Haryana"]},
    "Baghola - Chittorgarh": {"cities": ["Baghola, Haryana", "Chittorgarh, Rajasthan"]},
    "Chittorgarh - Hosur": {"cities": ["Chittorgarh, Rajasthan", "Hosur, Tamil Nadu"]},
    "Haridwar - Bangalore": {"cities": ["Haridwar, Uttarakhand", "Bangalore, Karnataka"]},
    "Raigarh - Toranagallu": {"cities": ["Raigarh, Chhattisgarh", "Toranagallu, Karnataka"]}
}

# 6. Reference City for Distance Calculation (from which distances to CSV cities will be calculated)
# You can change this to any city name that can be geocoded or is in cities_coords_provided.
DISTANCE_REFERENCE_CITY_NAME = "Toranagallu, Karnataka"
# --- End of Configuration ---

# --- Helper Function for Geocoding (with cache) ---
geocode_cache = {}
def geocode_location(location_name, ors_client, is_city_from_csv=False):
    if location_name in geocode_cache:
        return geocode_cache[location_name]
    print(f"  Geocoding via API: {location_name} ...") # Indicate API call
    try:
        search_text = location_name
        if is_city_from_csv and "," not in location_name: # Add ", India" for potentially ambiguous city names from CSV
            search_text = f"{location_name}, India"
        
        geocode_params = {'text': search_text, 'size': 1}
        try:
            # Attempt to restrict search to India
            geocode_result = ors_client.pelias_search(**geocode_params, boundary_country=['IND'])
        except TypeError: # Fallback if boundary_country is not supported by the client version
            print(f"    (Note: 'boundary_country' not supported by this openrouteservice-py version for {location_name}. Geocoding globally if 'India' not in text.)")
            geocode_result = ors_client.pelias_search(**geocode_params)
        time.sleep(1.6) # API rate limiting

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
        print(f"    API ERROR geocoding {location_name}: {e.args[0] if e.args else 'Unknown API Error'}")
        geocode_cache[location_name] = None
        return None
    except Exception as e:
        print(f"    OTHER ERROR geocoding {location_name}: {e}")
        geocode_cache[location_name] = None
        return None

# --- Get Coordinates for the Reference Start City ---
print(f"\n--- Preparing Reference City for Distance Calculation: {DISTANCE_REFERENCE_CITY_NAME} ---")
reference_city_coords_latlon = cities_coords_provided.get(DISTANCE_REFERENCE_CITY_NAME)
if reference_city_coords_latlon:
    print(f"  Using provided coordinates for reference city {DISTANCE_REFERENCE_CITY_NAME}: {reference_city_coords_latlon}")
else:
    print(f"  Provided coordinates not found for {DISTANCE_REFERENCE_CITY_NAME}. Attempting API geocoding...")
    reference_city_coords_latlon = geocode_location(DISTANCE_REFERENCE_CITY_NAME, client)

reference_city_ors_coords = None
if reference_city_coords_latlon:
    reference_city_ors_coords = [reference_city_coords_latlon[1], reference_city_coords_latlon[0]] # [lon, lat] for ORS
    print(f"  Reference city {DISTANCE_REFERENCE_CITY_NAME} coordinates for ORS: {reference_city_ors_coords}")
else:
    print(f"  FATAL: Could not determine coordinates for the reference city '{DISTANCE_REFERENCE_CITY_NAME}'. Distance calculations will be skipped.")


# --- Initialize Folium Map ---
map_center = [20.5937, 78.9629] # India center
india_map = folium.Map(location=map_center, zoom_start=5, tiles="CartoDB positron")

# --- 1. Load and Plot District Boundaries ---
print(f"\n--- Loading District Boundaries from: {DISTRICTS_FILE_PATH} ---")
try:
    with open(DISTRICTS_FILE_PATH, 'r', encoding='utf-8') as f:
        district_json_data = json.load(f)
    object_key = None # For TopoJSON
    if district_json_data.get('type', '').lower() == 'topology' and district_json_data.get('objects'):
        object_key = list(district_json_data['objects'].keys())[0] # Get the first object key
    
    if object_key: # If TopoJSON
        folium.TopoJson(district_json_data, object_path=f'objects.{object_key}', name='District Boundaries',
                        style_function=lambda x: {'color': '#888888', 'weight': 0.5, 'fillOpacity': 0.05}).add_to(india_map)
        print("  District boundaries (TopoJSON) added to map.")
    elif district_json_data.get('type', '').lower() == 'featurecollection': # If GeoJSON
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

    if start_coords_latlon and end_coords_latlon:
        ors_request_coords = [[start_coords_latlon[1], start_coords_latlon[0]], [end_coords_latlon[1], end_coords_latlon[0]]]
        try:
            print(f"  Fetching driving directions for {route_name}...")
            route_directions_geojson = client.directions(
                coordinates=ors_request_coords, profile='driving-car', format='geojson', instructions=False
            )
            time.sleep(1.6) # API rate limiting

            if route_directions_geojson and route_directions_geojson.get('features'):
                clean_route_name = re.sub(r'[^\w_.)( -]', '', route_name).replace(' ', '_') # Sanitize filename
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
            print(f"  ERROR (API) fetching route for {route_name}: {e.args[0] if e.args else 'Unknown API Error'}")
        except Exception as e:
            print(f"  ERROR (Other) fetching route for {route_name}: {e}")
    else:
        print(f"  Skipping route '{route_name}' due to geocoding failure of endpoints.")
route_group.add_to(india_map)

# --- 3. Process, Plot, Save Cities from CSV, and Calculate Distances ---
print(f"\n--- Processing Cities from CSV: {CSV_CITIES_FILE_PATH} (Distances from {DISTANCE_REFERENCE_CITY_NAME}) ---")
city_markers_group = folium.FeatureGroup(name="Diesel Price Cities")
geocoded_cities_for_geojson = [] # For the GeoJSON output
data_for_output_csv = [] # For the new CSV output with distances

try:
    cities_df = pd.read_csv(CSV_CITIES_FILE_PATH)
    if CSV_CITY_COLUMN not in cities_df.columns or CSV_PRICE_COLUMN not in cities_df.columns:
        print(f"  ERROR: CSV must contain '{CSV_CITY_COLUMN}' and '{CSV_PRICE_COLUMN}' columns.")
    else:
        # Process unique cities to avoid redundant geocoding and API calls for the same city name
        unique_cities_in_csv = cities_df[[CSV_CITY_COLUMN, CSV_PRICE_COLUMN]].drop_duplicates(subset=[CSV_CITY_COLUMN])
        print(f"  Found {len(unique_cities_in_csv)} unique city entries to process from CSV.")
        
        plotted_cities_count = 0
        for index, row_data in unique_cities_in_csv.iterrows():
            city_name_csv = str(row_data[CSV_CITY_COLUMN])
            price_csv = row_data[CSV_PRICE_COLUMN]
            
            # Get coordinates for the current CSV city
            current_city_coords_latlon = cities_coords_provided.get(city_name_csv)
            if not current_city_coords_latlon:
                 current_city_coords_latlon = geocode_location(city_name_csv, client, is_city_from_csv=True)
            else:
                print(f"  Using provided coordinates for CSV city {city_name_csv}: {current_city_coords_latlon}")

            distance_km_from_ref = None # Initialize distance

            if current_city_coords_latlon and reference_city_ors_coords:
                current_city_ors_coords = [current_city_coords_latlon[1], current_city_coords_latlon[0]] # [lon, lat]

                # Calculate distance from reference city if it's not the same city
                if reference_city_ors_coords == current_city_ors_coords:
                    distance_m = 0.0
                    print(f"    {city_name_csv} is the reference city. Distance is 0 km.")
                else:
                    print(f"    Calculating distance from {DISTANCE_REFERENCE_CITY_NAME} to {city_name_csv}...")
                    try:
                        route_to_station = client.directions(
                            coordinates=[reference_city_ors_coords, current_city_ors_coords],
                            profile='driving-car',
                            format='geojson',
                            instructions=False # We only need the distance
                        )
                        time.sleep(1.6) # API rate limiting

                        if route_to_station and route_to_station.get('features'):
                            # Safely access distance
                            segment = route_to_station['features'][0]['properties']['segments'][0]
                            if 'distance' in segment:
                                distance_m = segment['distance']
                            else:
                                print(f"      WARNING: 'distance' not found in segment for route to {city_name_csv}. Setting distance to N/A.")
                                distance_m = None
                        else:
                            print(f"      WARNING: No route features found between reference and {city_name_csv}. Setting distance to N/A.")
                            distance_m = None
                        
                        if distance_m is not None:
                            distance_km_from_ref = round(distance_m / 1000.0, 2)
                            print(f"      Distance to {city_name_csv}: {distance_km_from_ref} km")

                    except openrouteservice.exceptions.ApiError as e:
                        print(f"      ORS API ERROR calculating distance to {city_name_csv}: {e.args[0] if e.args else 'Unknown API Error'}")
                    except (IndexError, KeyError) as e_parse: # If path for distance_m is invalid or key missing
                        print(f"      ERROR parsing route data for distance to {city_name_csv}: {e_parse}")
                    except Exception as e_other:
                        print(f"      OTHER ERROR calculating distance to {city_name_csv}: {e_other}")
            elif not reference_city_ors_coords:
                 print(f"    Skipping distance calculation for {city_name_csv} as reference city coordinates are unavailable.")
            # No else needed for !current_city_coords_latlon, as distance_km_from_ref remains None

            # Plotting (only if coordinates are available for the CSV city)
            if current_city_coords_latlon:
                tooltip_text = f"City: {city_name_csv}<br>Diesel Price: {price_csv}"
                if distance_km_from_ref is not None:
                    tooltip_text += f"<br>Dist. from {DISTANCE_REFERENCE_CITY_NAME.split(',')[0]}: {distance_km_from_ref} km"
                
                folium.CircleMarker(
                    location=current_city_coords_latlon, radius=5, color='red', fill=True, fill_color='red', fill_opacity=0.7,
                    tooltip=tooltip_text
                ).add_to(city_markers_group)
                plotted_cities_count += 1
                
                # Prepare data for GeoJSON output
                geojson_properties = {
                    "city_name_csv": city_name_csv, 
                    "price_csv": price_csv,
                    "latitude": current_city_coords_latlon[0], 
                    "longitude": current_city_coords_latlon[1],
                    "distance_from_reference_km": distance_km_from_ref
                }
                geocoded_cities_for_geojson.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [current_city_coords_latlon[1], current_city_coords_latlon[0]]}, # [lon, lat]
                    "properties": geojson_properties
                })

            # Prepare data for the new CSV output (always add a row, even if some data is missing)
            data_for_output_csv.append({
                CSV_CITY_COLUMN: city_name_csv,
                CSV_PRICE_COLUMN: price_csv,
                'Latitude': current_city_coords_latlon[0] if current_city_coords_latlon else None,
                'Longitude': current_city_coords_latlon[1] if current_city_coords_latlon else None,
                f'Distance_from_{DISTANCE_REFERENCE_CITY_NAME.split(",")[0].replace(" ","_")}_km': distance_km_from_ref
            })
            
            if (index + 1) % 5 == 0: # Log progress less frequently for distance calls
                 print(f"    Processed {index + 1}/{len(unique_cities_in_csv)} unique cities from CSV...")
        
        print(f"  Successfully plotted {plotted_cities_count} cities from CSV.")

        # Save the GeoJSON with city data (now includes distance)
        if geocoded_cities_for_geojson:
            cities_geojson_output_fc = {"type": "FeatureCollection", "features": geocoded_cities_for_geojson}
            with open(OUTPUT_CSV_CITIES_GEOJSON, 'w', encoding='utf-8') as f_cities_geojson:
                json.dump(cities_geojson_output_fc, f_cities_geojson, indent=2)
            print(f"  Geocoded city locations (with distances) from CSV saved to: {OUTPUT_CSV_CITIES_GEOJSON}")
        else:
            print("  No cities from CSV were successfully geocoded/found to save to GeoJSON.")

        # Save the new CSV file with distances
        if data_for_output_csv:
            output_df = pd.DataFrame(data_for_output_csv)
            try:
                output_df.to_csv(OUTPUT_CSV_WITH_DISTANCES, index=False, encoding='utf-8')
                print(f"  CSV with city details and distances saved to: {OUTPUT_CSV_WITH_DISTANCES}")
            except Exception as e_csv:
                print(f"  ERROR saving CSV with distances ({OUTPUT_CSV_WITH_DISTANCES}): {e_csv}")
        else:
            print("  No data processed for the output CSV with distances.")


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
