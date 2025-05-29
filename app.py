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

# Vehicle mileage data
vehicle_mileage = {
    'RJ14GG9302': {'Load': 4.60, 'Empty': 5.00},
    'RJ14GH7301': {'Load': 2.10, 'Empty': 4.00}
}

# Streamlit UI
st.title("🚚 Fuel Optimization Tool")

route_selected = st.selectbox("Choose Route", routes_df['Route Name'].unique())
vehicle_selected = st.selectbox("Select Vehicle", list(vehicle_mileage.keys()))
load_status = st.radio("Vehicle Load Status", ['Load', 'Empty'])

mileage = vehicle_mileage[vehicle_selected][load_status]
st.write(f"Vehicle Mileage: {mileage} km/l")

tank_capacity = 300
start_fuel = st.number_input("Starting Fuel (liters)", value=200.0)
end_fuel = st.number_input("Ending Fuel (liters)", value=50.0)
buffer_fuel = st.number_input("Buffer Fuel (liters)", value=30.0)

run_button = st.button("🚀 Run Optimization")

if 'results' not in st.session_state:
    st.session_state['results'] = {}

if run_button:
    route_data = routes_df[routes_df['Route Name'] == route_selected].reset_index()
    coords = list(zip(route_data['District Latitude (Centroid)'], route_data['District Longitude (Centroid)']))

    distances = [geodesic(coords[i], coords[i+1]).km for i in range(len(coords)-1)]
    fuel_needed_segments = [d / mileage for d in distances]

    # Optimization Model
    prob = pulp.LpProblem("FuelOptimization", pulp.LpMinimize)

    purchase = pulp.LpVariable.dicts("purchase", route_data.index, lowBound=0)
    fuel_level = pulp.LpVariable.dicts("fuel_level", route_data.index, lowBound=buffer_fuel, upBound=tank_capacity)
    stop = pulp.LpVariable.dicts("stop", route_data.index, cat='Binary')

    prob += pulp.lpSum([purchase[i] * route_data.loc[i, 'Price'] for i in route_data.index])

    for idx in route_data.index:
        if idx == 0:
            prob += fuel_level[idx] == start_fuel
        else:
            prob += fuel_level[idx] == fuel_level[idx - 1] + purchase[idx - 1] - fuel_needed_segments[idx - 1]

        prob += purchase[idx] <= (tank_capacity - buffer_fuel) * stop[idx]
        prob += purchase[idx] + fuel_level[idx] <= tank_capacity

    prob.solve()

    filling_table = []
    total_cost, total_fuel, cumulative_distance = 0, 0, 0

    for i in route_data.index:
        purchased_fuel = pulp.value(purchase[i])
        if purchased_fuel and purchased_fuel > 0.01:
            cost_at_stop = purchased_fuel * route_data.loc[i, 'Price']
            total_cost += cost_at_stop
            total_fuel += purchased_fuel
            filling_table.append({
                'Location': route_data.loc[i, 'Intersected District'],
                'Distance (km)': f"{cumulative_distance:.2f}",
                'Arrival Fuel (L)': f"{pulp.value(fuel_level[i]):.2f}",
                'Purchased Fuel (L)': f"{purchased_fuel:.2f}",
                'Depart Fuel (L)': f"{pulp.value(fuel_level[i]) + purchased_fuel:.2f}",
                'Fuel Cost (₹)': f"{cost_at_stop:.2f}",
                'Price (₹/L)': f"{route_data.loc[i, 'Price']:.4f}"
            })
        if i < len(distances):
            cumulative_distance += distances[i]

    fuel_chart_data = pd.DataFrame({
        'Distance (km)': [sum(distances[:i]) for i in route_data.index],
        'Fuel Level (liters)': [pulp.value(fuel_level[i]) for i in route_data.index]
    }).dropna()

    st.session_state['results'] = {
        'filling_table': filling_table,
        'total_cost': total_cost,
        'total_fuel': total_fuel,
        'coords': coords,
        'route_data': route_data,
        'stop': {i: pulp.value(stop[i]) for i in route_data.index},
        'purchase': {i: pulp.value(purchase[i]) for i in route_data.index},
        'fuel_chart_data': fuel_chart_data
    }

if st.session_state['results']:
    results = st.session_state['results']

    st.subheader("✅ Recommended Fuel Stops")
    filling_df = pd.DataFrame(results['filling_table'])
    st.table(filling_df)

    st.subheader("💰 Total Fuel Purchased and Cost")
    st.write(f"Total Fuel Purchased: {results['total_fuel']:.2f} liters")
    st.write(f"Total Cost: ₹{results['total_cost']:.2f}")

    st.subheader("🗺️ Route Map with Recommended Stops")
    m = folium.Map(location=results['coords'][0], zoom_start=6)
    for idx, coord in enumerate(results['coords']):
        district = results['route_data'].loc[idx, 'Intersected District']
        price = results['route_data'].loc[idx, 'Price']
        popup = f"{district}<br>Price: ₹{price}/L"
        if results['stop'][idx] > 0 and results['purchase'][idx] > 0.01:
            folium.Marker(coord, popup=popup, icon=folium.Icon(color='green', icon='info-sign')).add_to(m)
        else:
            folium.CircleMarker(coord, radius=5, color='blue', fill=True, fill_opacity=0.7,
                                tooltip=f"{district}: ₹{price}/L").add_to(m)
    st_folium(m, width=700, height=500)

    st.subheader("📊 Fuel Level Along the Route")
    chart = alt.Chart(results['fuel_chart_data']).mark_line(point=True).encode(
        x='Distance (km)',
        y='Fuel Level (liters)'
    ).interactive()
    st.altair_chart(chart)
else:
    st.info("Adjust parameters and click 'Run Optimization'.")
