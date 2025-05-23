import streamlit as st
import pandas as pd
import json
from geopy.distance import geodesic
import numpy as np

# Load data
routes_df = pd.read_excel('routes_districts_prices_filled_mean.xlsx')
with open('india-districts.json') as f:
    india_districts = json.load(f)

# Streamlit UI
st.title("Fuel Stop Optimization Tool")

# Route selection
route_options = routes_df['Route Name'].unique()
route_selected = st.selectbox("Choose Route", route_options)

# Mileage and fuel details input
mileage = st.number_input("Mileage (km/l)", value=5.0)
tank_capacity = st.number_input("Fuel Tank Capacity (liters)", value=400.0)
start_fuel = st.number_input("Starting Fuel (liters)", value=200.0)
end_fuel = st.number_input("Ending Fuel Buffer (liters)", value=50.0)

# Filter route data
route_data = routes_df[routes_df['Route Name'] == route_selected]

# Calculate total route distance
coords = list(zip(route_data['District Latitude (Centroid)'], route_data['District Longitude (Centroid)']))
total_distance = sum([geodesic(coords[i], coords[i+1]).km for i in range(len(coords)-1)])

# Total fuel required
total_fuel_required = total_distance / mileage
fuel_needed = total_fuel_required - start_fuel + end_fuel

# Logic for optimal fuel stops (simple heuristic)
fuel_left = start_fuel
fuel_stops = []
distance_traveled = 0
for i in range(len(coords)-1):
    distance_next = geodesic(coords[i], coords[i+1]).km
    fuel_needed_next = distance_next / mileage

    if fuel_left < fuel_needed_next + end_fuel:
        fuel_stops.append(route_data.iloc[i]['Intersected District'])
        fuel_left = tank_capacity
    fuel_left -= fuel_needed_next
    distance_traveled += distance_next

st.write(f"### Total Distance: {total_distance:.2f} km")
st.write(f"### Total Fuel Required: {total_fuel_required:.2f} liters")
st.write("### Recommended Fuel Stops:")
st.write(fuel_stops)

import folium
m = folium.Map(location=coords[0], zoom_start=6)

# Add route points
for coord in coords:
    folium.Marker(coord).add_to(m)

# Highlight fuel stops
for district in fuel_stops:
    stop_coord = route_data[route_data['Intersected District'] == district][['District Latitude (Centroid)', 'District Longitude (Centroid)']].values[0]
    folium.Marker(stop_coord, icon=folium.Icon(color='red')).add_to(m)

st.components.v1.html(m._repr_html_(), height=600)
