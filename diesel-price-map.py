import pandas as pd
import geopandas as gpd
import folium # For creating the interactive map
import json

# --- Configuration: USER INPUT REQUIRED (Updated based on your info) ---

# 1. Define file paths
GEOJSON_FILE_PATH = 'india-districts.json'
CSV_FILE_PATH = 'india-diesel-22may25.csv'
OUTPUT_MAP_FILE = 'india_diesel_prices_map_city_based.html'

# 2. CSV Column Names (Updated based on your input)
CSV_CITY_COLUMN = 'City'      # Your column for city/district names
CSV_PRICE_COLUMN = 'Price'    # Your column for price
# CSV_STATE_COLUMN is not available, so we will handle its absence.

# 3. GeoJSON Property Names (These should be correct based on your snippet)
GEOJSON_DISTRICT_PROPERTY = 'district'
GEOJSON_STATE_PROPERTY = 'st_nm' # We'll use this for display and to show potential ambiguities

# --- End of Configuration ---

print(f"Loading district boundaries from: {GEOJSON_FILE_PATH}")
try:
    districts_gdf = gpd.read_file(GEOJSON_FILE_PATH)
    print(f"Successfully loaded {len(districts_gdf)} district geometries.")
except Exception as e:
    print(f"Error loading GeoJSON/TopoJSON file: {e}")
    exit()

print(f"Loading diesel prices from: {CSV_FILE_PATH}")
try:
    prices_df = pd.read_csv(CSV_FILE_PATH)
    print(f"Successfully loaded diesel price data with {len(prices_df)} rows.")
    print(f"CSV Headers found: {prices_df.columns.tolist()}")
except Exception as e:
    print(f"Error loading CSV file: {e}")
    exit()

# --- Data Preparation and Merging ---
print("Preparing data for merging...")

# Standardize names in GeoDataFrame
districts_gdf['district_clean_geojson'] = districts_gdf[GEOJSON_DISTRICT_PROPERTY].astype(str).str.strip().str.lower()
# We keep state info from GeoJSON for context, even if not used directly in join key with CSV
districts_gdf['state_clean_geojson'] = districts_gdf[GEOJSON_STATE_PROPERTY].astype(str).str.strip().str.lower()

# Create a join key for the GeoDataFrame based on district name only, as CSV lacks state.
districts_gdf['join_key_geojson'] = districts_gdf['district_clean_geojson']

# Standardize names in Price DataFrame
if CSV_CITY_COLUMN not in prices_df.columns:
    print(f"ERROR: Specified city column '{CSV_CITY_COLUMN}' not found in CSV.")
    exit()
if CSV_PRICE_COLUMN not in prices_df.columns:
    print(f"ERROR: Specified price column '{CSV_PRICE_COLUMN}' not found in CSV.")
    exit()

prices_df['city_clean_csv'] = prices_df[CSV_CITY_COLUMN].astype(str).str.strip().str.lower()
prices_df['join_key_csv'] = prices_df['city_clean_csv'] # Join key from CSV is just the cleaned city name

print("WARNING: Your CSV file does not contain state information for cities/districts.")
print("Merging will be based on matching the 'City' column from your CSV with the 'district' property from the GeoJSON.")
print("This may lead to inaccuracies if city names are not unique district identifiers or if multiple states have districts/cities with the same name.")

# Convert price column to numeric
prices_df['price_numeric'] = pd.to_numeric(prices_df[CSV_PRICE_COLUMN], errors='coerce')
prices_df_cleaned = prices_df.dropna(subset=['price_numeric', 'join_key_csv']) # Remove rows where price or key is invalid
prices_df_cleaned = prices_df_cleaned.drop_duplicates(subset=['join_key_csv'], keep='last') # If multiple prices for same city, take last

# Perform the merge
print("Merging spatial data with price data...")
merged_gdf = districts_gdf.merge(
    prices_df_cleaned[['join_key_csv', 'price_numeric', CSV_CITY_COLUMN, CSV_PRICE_COLUMN]],
    left_on='join_key_geojson', # from GeoJSON districts
    right_on='join_key_csv',    # from CSV cities
    how='left'
)

# For map keying, we'll use the original district and state from GeoJSON to make properties unique if possible
merged_gdf['map_key'] = merged_gdf[GEOJSON_DISTRICT_PROPERTY] + "_GEOID_" + merged_gdf[GEOJSON_STATE_PROPERTY]


num_matched = merged_gdf['price_numeric'].notna().sum()
print(f"Number of districts in GeoJSON: {len(districts_gdf)}")
print(f"Number of GeoJSON districts with a matched diesel price: {num_matched}")

if num_matched == 0:
    print("WARNING: No districts were matched with price data. Please check:")
    print("  1. The `City` names in your CSV and ensure they correspond to district names in the GeoJSON.")
    print("  2. Spelling, capitalization, and extra spaces in your CSV `City` names.")
    # For debugging, you could print some non-matching keys:
    # unmatched_geojson_keys = districts_gdf[~districts_gdf['join_key_geojson'].isin(prices_df_cleaned['join_key_csv'])]['join_key_geojson']
    # print("Sample GeoJSON district keys that didn't find a match in CSV:", unmatched_geojson_keys.sample(min(5, len(unmatched_geojson_keys))).tolist() if not unmatched_geojson_keys.empty else "[]")
    # print("Sample CSV city keys:", prices_df_cleaned['join_key_csv'].sample(min(5, len(prices_df_cleaned))).tolist() if not prices_df_cleaned.empty else "[]")


# --- Create Interactive Map with Folium ---
print("Creating map...")
map_center = [20.5937, 78.9629]
india_map = folium.Map(location=map_center, zoom_start=5, tiles="CartoDB positron")

if merged_gdf.crs is None or merged_gdf.crs.to_string() != "EPSG:4326":
    merged_gdf = merged_gdf.to_crs("EPSG:4326")

# Use a temporary column for choropleth data fill if you want to handle NaNs specifically
merged_gdf['price_for_map'] = merged_gdf['price_numeric'] #.fillna(-1) # Folium handles NaN with nan_fill_color

if num_matched > 0:
    choropleth = folium.Choropleth(
        geo_data=merged_gdf, # GeoDataFrame with geometry
        name='Diesel Prices',
        data=merged_gdf,
        columns=['map_key', 'price_for_map'], # Key from GeoJSON features, Value to plot
        key_on='feature.properties.map_key',  # Path to the key in GeoJSON properties
        fill_color='YlOrRd',
        fill_opacity=0.7,
        line_opacity=0.3,
        legend_name='Diesel Price (INR)',
        nan_fill_color='gainsboro', # Color for districts with no data
        highlight=True
    ).add_to(india_map)

    # Tooltip: Use original GeoJSON district/state names and matched CSV city/price
    # Create a new column for display in tooltip that uses the CSV city name where available
    merged_gdf['display_name_for_tooltip'] = merged_gdf[CSV_CITY_COLUMN].fillna(merged_gdf[GEOJSON_DISTRICT_PROPERTY])
    merged_gdf['display_price_for_tooltip'] = merged_gdf[CSV_PRICE_COLUMN].astype(str).fillna('N/A')


    folium.GeoJson(
        merged_gdf,
        name="District Information",
        style_function=lambda x: {'color': 'transparent', 'fillColor': 'transparent', 'weight': 0},
        tooltip=folium.features.GeoJsonTooltip(
            fields=['display_name_for_tooltip', GEOJSON_STATE_PROPERTY, 'display_price_for_tooltip'],
            aliases=['City/District:', 'State:', 'Diesel Price (CSV):'],
            localize=True, sticky=False, labels=True,
            style="""background-color: #F0EFEF; border: 1px solid black; border-radius: 3px; box-shadow: 3px;"""
        ),
        highlight_function=lambda x: {'weight':1, 'color':'black', 'fillOpacity':0.1}
    ).add_to(india_map)
else:
    print("Skipping Choropleth layer due to no matched data. Showing base district map.")
    folium.GeoJson(
        districts_gdf,
        name="District Boundaries (No Price Data Matched)",
        tooltip=folium.features.GeoJsonTooltip(fields=[GEOJSON_DISTRICT_PROPERTY, GEOJSON_STATE_PROPERTY])
    ).add_to(india_map)

folium.LayerControl().add_to(india_map)

try:
    india_map.save(OUTPUT_MAP_FILE)
    print(f"Map successfully saved to: {OUTPUT_MAP_FILE}")
except Exception as e:
    print(f"Error saving map: {e}")