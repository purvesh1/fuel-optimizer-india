import streamlit as st
import pandas as pd
import pulp
import folium
from streamlit_folium import st_folium
import altair as alt
from geopy.distance import geodesic

# Load Data
@st.cache_data
def load_data():
    df = pd.read_excel('routes_districts_prices_filled_mean.xlsx')
    return df

routes_df = load_data()

# Initialize Session State
if 'optimization_run' not in st.session_state:
    st.session_state.optimization_run = False
if 'stops_made' not in st.session_state:
    st.session_state.stops_made = []
if 'purchase_amounts' not in st.session_state:
    st.session_state.purchase_amounts = []
if 'fuel_chart_data' not in st.session_state:
    st.session_state.fuel_chart_data = pd.DataFrame()
if 'coords' not in st.session_state:
    st.session_state.coords = []

# Streamlit UI
st.title("🚚 Fuel Optimization Tool")

# User inputs
route_selected = st.selectbox("Choose Route", routes_df['Route Name'].unique())
mileage = st.number_input("Mileage (km/l)", value=5.0)
tank_capacity = st.number_input("Fuel Tank Capacity (liters)", value=400.0)
start_fuel = st.number_input("Starting Fuel (liters)", value=200.0)
end_fuel = st.number_input("Ending Fuel (liters)", value=50.0)
buffer_fuel = st.number_input("Buffer Fuel (liters)", value=30.0)

run_button = st.button("🚀 Run Optimization")

if run_button:
    route_data = routes_df[routes_df['Route Name'] == route_selected].reset_index()
    coords = list(zip(route_data['District Latitude (Centroid)'], route_data['District Longitude (Centroid)']))

    distances = [geodesic(coords[i], coords[i+1]).km for i in range(len(coords)-1)]
    fuel_needed_segments = [d / mileage for d in distances]

    # Optimization Model
    prob = pulp.LpProblem("FuelOptimization", pulp.LpMinimize)

    purchase = pulp.LpVariable.dicts("purchase", route_data.index, lowBound=0)
    stop = pulp.LpVariable.dicts("stop", route_data.index, cat='Binary')

    prob += pulp.lpSum([purchase[i] * route_data.loc[i, 'Price'] for i in route_data.index])

    current_fuel = start_fuel
    fuel_levels = [current_fuel]

    for idx in route_data.index[:-1]:
        next_segment = fuel_needed_segments[idx]
        prob += current_fuel + purchase[idx] - next_segment >= buffer_fuel
        prob += purchase[idx] <= tank_capacity * stop[idx]
        current_fuel = current_fuel + purchase[idx] - next_segment
        fuel_levels.append(current_fuel)

    prob.solve()

    stops_made = []
    purchase_amounts = []
    for i in route_data.index:
        if pulp.value(stop[i]) == 1:
            stops_made.append(route_data.loc[i, 'Intersected District'])
            purchase_amounts.append(pulp.value(purchase[i]))
        else:
            purchase_amounts.append(0)

    distances_cum = [0] + list(pd.Series(distances).cumsum())

    fuel_chart_data = pd.DataFrame({
        'Distance (km)': distances_cum,
        'Fuel Level (liters)': fuel_levels
    })

    st.session_state.optimization_run = True
    st.session_state.stops_made = stops_made
    st.session_state.purchase_amounts = purchase_amounts
    st.session_state.fuel_chart_data = fuel_chart_data
    st.session_state.coords = coords

if st.session_state.optimization_run:
    st.subheader("✅ Recommended Fuel Stops")
    st.write(st.session_state.stops_made)

    # Map Visualization
    st.subheader("🗺️ Route Map with Recommended Stops")
    m = folium.Map(location=st.session_state.coords[0], zoom_start=6)

    for idx, coord in enumerate(st.session_state.coords):
        popup = f"{routes_df.loc[idx, 'Intersected District']}<br>Fuel Purchased: {st.session_state.purchase_amounts[idx]:.2f} liters"
        if st.session_state.purchase_amounts[idx] > 0:
            folium.Marker(coord, popup=popup, icon=folium.Icon(color='red', icon='gas-pump', prefix='fa')).add_to(m)
        else:
            folium.CircleMarker(coord, radius=4, color='blue', fill=True, fill_opacity=0.5, popup=popup).add_to(m)

    st_folium(m, width=700, height=500)

    # Fuel Level Chart
    st.subheader("📊 Fuel Level Along the Route")

    line_chart = alt.Chart(st.session_state.fuel_chart_data).mark_line(point=True).encode(
        x='Distance (km)',
        y='Fuel Level (liters)'
    ).properties(
        width=700,
        height=400
    ).interactive()

    #st.altair_chart(line_chart)

else:
    st.info("Please adjust parameters and click 'Run Optimization' to see results.")
