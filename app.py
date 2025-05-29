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

# Initialize Session State
for key in ['optimization_run', 'stops_made', 'purchase_amounts', 'fuel_chart_data', 'coords', 'route_data', 'total_cost', 'total_fuel', 'filling_table']:
    if key not in st.session_state:
        st.session_state[key] = [] if key in ['stops_made', 'purchase_amounts', 'coords', 'filling_table'] else pd.DataFrame() if key == 'fuel_chart_data' else 0.0 if 'total' in key else False

# Streamlit UI
st.title("🚚 Fuel Optimization Tool")

# User inputs
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
    total_cost = 0.0
    total_fuel = 0.0
    filling_table = []

    current_fuel = start_fuel
    cumulative_distance = 0

    for i in route_data.index:
        purchased_fuel = pulp.value(purchase[i])
        distance_to_current = 0 if i == 0 else distances[i-1]
        cumulative_distance += distance_to_current
        arrival_fuel = current_fuel - (0 if i == 0 else fuel_needed_segments[i-1])

        if pulp.value(stop[i]) == 1:
            stops_made.append(route_data.loc[i, 'Intersected District'])
            purchase_amounts.append(purchased_fuel)
            cost_at_stop = purchased_fuel * route_data.loc[i, 'Price']
            total_cost += cost_at_stop
            total_fuel += purchased_fuel
            filling_table.append({
                'Location': route_data.loc[i, 'Intersected District'],
                'Distance (km)': f"{cumulative_distance:.2f}",
                'Arrival Fuel (L)': f"{arrival_fuel:.2f}",
                'Purchased Fuel (L)': f"{purchased_fuel:.2f}",
                'Depart Fuel (L)': f"{arrival_fuel + purchased_fuel:.2f}",
                'Fuel Cost (₹)': f"{cost_at_stop:.2f}",
                'Price (₹/L)': f"{route_data.loc[i, 'Price']:.4f}"
            })
            current_fuel = arrival_fuel + purchased_fuel
        else:
            purchase_amounts.append(0)
            current_fuel = arrival_fuel

    distances_cum = [0] + list(pd.Series(distances).cumsum())

    fuel_chart_data = pd.DataFrame({
        'Distance (km)': distances_cum,
        'Fuel Level (liters)': fuel_levels
    })

    st.session_state.update({
        'optimization_run': True,
        'stops_made': stops_made,
        'purchase_amounts': purchase_amounts,
        'fuel_chart_data': fuel_chart_data,
        'coords': coords,
        'route_data': route_data,
        'total_cost': total_cost,
        'total_fuel': total_fuel,
        'filling_table': filling_table
    })

if st.session_state.optimization_run:

    st.subheader("💰 Total Fuel Purchased and Cost")
    st.write(f"Total Fuel Purchased: {st.session_state.total_fuel:.2f} liters")
    st.write(f"Total Cost: ₹{st.session_state.total_cost:.2f}")

    st.subheader("📝 Filling Details")
    filling_df = pd.DataFrame(st.session_state.filling_table)
    st.table(filling_df)

    st.subheader("🗺️ Route Map with Recommended Stops")
    m = folium.Map(location=st.session_state.coords[0], zoom_start=6)
    for idx, coord in enumerate(st.session_state.coords):
        popup = f"{st.session_state.route_data.loc[idx, 'Intersected District']}<br>Price: ₹{st.session_state.route_data.loc[idx, 'Price']}/L"
        folium.Marker(coord, popup=popup, icon=folium.Icon(color='red' if st.session_state.purchase_amounts[idx] else 'blue')).add_to(m)
    st_folium(m, width=700, height=500)

    st.subheader("📊 Fuel Level Along the Route")
    chart = alt.Chart(st.session_state.fuel_chart_data).mark_line(point=True).encode(x='Distance (km)', y='Fuel Level (liters)').interactive()
    st.altair_chart(chart)
else:
    st.info("Adjust parameters and click 'Run Optimization'.")
