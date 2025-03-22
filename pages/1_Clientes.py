import streamlit  as st
import hashlib 
import json 
import requests
import pandas as pd
import os 
import numpy as np
import plotly.express as px

st.set_page_config(layout="wide")

with open('config.json', 'r') as file: 
    config = json.load(file) 

if not 'authenticated' in st.session_state: 
    st.session_state.authenticated = False

@st.cache_data
def fetch_data(url): 
    return requests.get(url = url).json() 


if not st.session_state.authenticated: 
    
    with st.sidebar:         
        pwd = st.sidebar.text_input('password', type = 'password') 
        st.session_state.authenticated = hashlib.sha256(pwd.encode()).hexdigest() in config['keys']

if st.session_state.authenticated:

    st.title('Clientes')
    sales_data = pd.DataFrame(fetch_data(os.getenv("BASE_URL") + "/sales/details"))

    summary = sales_data.groupby(['payee_nit', 'payee_name']).agg(
        total_sales=('item_sales', 'sum'),
        distinct_days_with_sales=('issued_at', 'nunique'),
        days_since_last_purchase=('issued_at', lambda x: (pd.Timestamp.now() - pd.to_datetime(x).max()).days)
    ).reset_index()

    six_months_ago = 180  # Approximate days in 6 months
    one_year_ago = 365  # Approximate days in 1 year
    avg_distinct_days = summary['distinct_days_with_sales'].mean()

    conditions = [
        (summary['days_since_last_purchase'] <= six_months_ago) & (summary['distinct_days_with_sales'] < avg_distinct_days),
        (summary['days_since_last_purchase'] <= six_months_ago) & (summary['distinct_days_with_sales'] >= avg_distinct_days),
        (summary['days_since_last_purchase'] <= one_year_ago) & (summary['distinct_days_with_sales'] < avg_distinct_days),
        (summary['days_since_last_purchase'] <= one_year_ago) & (summary['distinct_days_with_sales'] >= avg_distinct_days),
        (summary['days_since_last_purchase'] > one_year_ago) & (summary['distinct_days_with_sales'] < avg_distinct_days),
        (summary['days_since_last_purchase'] > one_year_ago) & (summary['distinct_days_with_sales'] >= avg_distinct_days)
    ]

    choices = ['Nuevo', 'Leal', 'Curioso', 'Latente', '1 Timer', 'Olvidado']

    summary['category'] = np.select(conditions, choices, default='unknown')
    color_map = {
        'Nuevo': 'limegreen',
        'Leal': 'green',
        'Curioso': 'dodgerblue',
        'Latente': 'blue',
        '1 Timer': 'orangered',
        'Olvidado': 'red',
        'unknown': 'gray'
    }

    fig = px.scatter(
        summary,
        x='days_since_last_purchase',
        y='distinct_days_with_sales',
        size='total_sales',
        color='category',
        color_discrete_map=color_map,
        title='Segmentación de clientes',
        labels={
            'days_since_last_purchase': 'Días desde última compra',
            'distinct_days_with_sales': 'Ventas distintas',
            'total_sales': 'Ventas Totales',
            'category': 'Categoría'
        },
        hover_data={
            'payee_name': True,
            'payee_nit': True,
            'days_since_last_purchase': True,
            'distinct_days_with_sales': True,
            'category': True,
        },
        height=800  # Increase the plot height
    )

    # Increase font size for the plot
    fig.update_layout(
        font=dict(size=16)  # Set font size to 16
    )

    # Add vertical and horizontal dashed lines for cuts
    fig.add_vline(x=180, line_dash="dash", line_color="gray", annotation_text="6 meses", annotation_position="top left")
    fig.add_vline(x=365, line_dash="dash", line_color="gray", annotation_text="1 año", annotation_position="top left")
    fig.add_hline(y=avg_distinct_days, line_dash="dash", line_color="gray", annotation_text="Avg Compras", annotation_position="top right")


    # Display overall sales by category in cards, ordered by total sales
    st.subheader("Ventas por Categoría")
    category_sales = summary.groupby('category').agg(
        total_sales=('total_sales', 'sum'),
        client_count=('payee_nit', 'count')
    ).reset_index()

    # Sort by total sales in descending order
    category_sales = category_sales.sort_values(by='total_sales', ascending=False).reset_index(drop=True)

    cols = st.columns(len(category_sales))
    for i, row in category_sales.iterrows():
        with cols[i]:
            st.metric(label=f"{row['category']} ({row['client_count']} clientes)", value=f"Q{row['total_sales']:,.2f}")

    st.plotly_chart(fig, use_container_width=True)

    # Add explanations for each group as captions
    group_explanations = {
        'Nuevo': 'Clientes nuevos con pocas compras recientes.',
        'Leal': 'Clientes frecuentes con compras consistentes.',
        'Curioso': 'Clientes que han explorado pero no compran regularmente.',
        'Latente': 'Clientes que han comprado antes pero están inactivos.',
        '1 Timer': 'Clientes que solo han comprado una vez.',
        'Olvidado': 'Clientes que no han comprado en mucho tiempo.',
        'unknown': 'Clientes sin categoría definida.'
    }

    for category, explanation in group_explanations.items():
        st.markdown(f"**{category}:** {explanation}")

    # Add three columns with filters
    st.subheader("Filters")
    col1, col2, col3 = st.columns(3)
    with col1:
        payee_nit_filter = st.text_input("Filtrar por NIT del Cliente")

    with col2:
        payee_name_filter = st.text_input("Filtrar por Nombre del Cliente")

    with col3:
        category_filter = st.multiselect("Filtrar por Categoría", options=summary['category'].unique().tolist(), default=[])

    # Apply filters to the detailed table
    filtered_table = summary.copy()
    if payee_nit_filter:
        filtered_table = filtered_table[filtered_table['payee_nit'].astype(str).str.contains(payee_nit_filter, case=False)]

    if payee_name_filter:
        filtered_table = filtered_table[filtered_table['payee_name'].str.contains(payee_name_filter, case=False)]

    if category_filter:
        filtered_table = filtered_table[filtered_table['category'].isin(category_filter)]

    # Display a detailed table for each payee with their category and stats
    st.subheader("Información Detallada de Clientes")
    detailed_table = filtered_table[['payee_nit', 'payee_name', 'category', 'total_sales', 'distinct_days_with_sales', 'days_since_last_purchase']]
    detailed_table.columns = ['NIT del Cliente', 'Nombre del Cliente', 'Categoría', 'Ventas Totales', 'Días con Ventas Distintas', 'Días desde Última Compra']

    # Format 'Ventas Totales' column as Q{,.2f}
    detailed_table['Ventas Totales'] = detailed_table['Ventas Totales'].round(2)

    st.dataframe(detailed_table.style.format({"Ventas Totales": "Q{:,.2f}"}), use_container_width=True, hide_index=True)