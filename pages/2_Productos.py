import streamlit as st 
import json 
import requests 
import hashlib 
import pandas as pd 
import os 
import numpy as np 
import plotly.express as px

st.set_page_config(layout="wide")


with open('config.json', 'r') as file: 
    config = json.load(file) 

if not 'authenticated' in st.session_state: 
    st.session_state.authenticated = True

@st.cache_data
def fetch_data(url): 
    return requests.get(url = url).json() 


if not st.session_state.authenticated: 
    
    with st.sidebar:         
        pwd = st.sidebar.text_input('password', type = 'password') 
        st.session_state.authenticated = hashlib.sha256(pwd.encode()).hexdigest() in config['keys']

if st.session_state.authenticated:

    st.title('Productos')
    st.caption('De este análisis se excluyen muestras médicas')
    sales_data = pd.DataFrame(fetch_data(os.getenv("BASE_URL") + "/sales/details"))

    # Remove sales to payee_nit 105272981
    sales_data = sales_data[sales_data['payee_nit'] != 105272981]

    # Convert issued_date to datetime and extract quarter
    sales_data['issued_at'] = pd.to_datetime(sales_data['issued_at'])
    sales_data['month'] = sales_data['issued_at'].dt.to_period('M').astype(str)

    # Create a complete index of item_category and month combinations
    all_combinations = pd.MultiIndex.from_product(
        [sales_data['item_category'].unique(), sales_data['month'].unique()],
        names=['item_category', 'month']
    )

    # Group by item_category and month, then calculate item_sales
    sales_data_grouped = sales_data.groupby(['item_category', 'month'])['item_sales'].sum()

    # Reindex to fill missing combinations with 0
    sales_data_grouped = sales_data_grouped.reindex(all_combinations, fill_value=0)

    # Sort values by month
    sales_data_grouped = sales_data_grouped.reset_index().sort_values(by=['item_category', 'month']).set_index(['item_category', 'month'])
    
    # Calculate cumulative item_sales
    sales_data_grouped = sales_data_grouped.groupby(level=0).cumsum().reset_index()
    
    # Add month-specific sales to the DataFrame for tooltips
    sales_data_grouped['month_sales'] = sales_data.groupby(['item_category', 'month'])['item_sales'].sum().reindex(all_combinations, fill_value=0).values


    # Create the line plot with dots on observations
    fig = px.line(
        sales_data_grouped,
        x='month',
        y='item_sales',
        color='item_category',
        title='Ventas acumuladas por categoría de producto por mes',
        labels={
            'item_sales': 'Ventas acumuladas',
            'month': 'Mes',
            'item_category': 'Categoría de producto',
            'month_sales': 'Ventas mensuales'
        },
        hover_data={'month_sales': True}  # Add month-specific sales to the tooltip
    )
    fig.update_traces(mode='lines+markers')  # Add dots on observations

    # Adjust the height of the plot
    fig.update_layout(height=800)  # Set the height to 800 pixels

    # Display the plot
    st.plotly_chart(fig, use_container_width=True)


    # Add filters for item_category, item_name, and price range
    filter_column1, filter_column2, filter_column3 = st.columns(3)

    with filter_column1:
        selected_categories = st.multiselect(
            "Selecciona categorías de producto",
            options=list(sales_data['item_category'].unique()),
            default=[]
        )

    with filter_column2:
        selected_items = st.multiselect(
            "Selecciona nombres de productos",
            options=list(sales_data['item_name'].unique()),
            default=[]
        )

    with filter_column3:
        min_price, max_price = st.slider(
            "Selecciona rango de precios",
            min_value=float(sales_data['item_unitprice'].min()),
            max_value=float(sales_data['item_unitprice'].max()),
            value=(float(sales_data['item_unitprice'].min()), float(sales_data['item_unitprice'].max())),
            step=250.0
        )

    # Apply filters to the sales_data DataFrame
    filtered_data = sales_data.copy()
    if selected_categories:
        filtered_data = filtered_data[filtered_data['item_category'].isin(selected_categories)]
    if selected_items:
        filtered_data = filtered_data[filtered_data['item_name'].isin(selected_items)]
    filtered_data = filtered_data[
        (filtered_data['item_unitprice'] >= min_price) & (filtered_data['item_unitprice'] <= max_price)
    ]
    
    # Create cards to display key metrics
    card_column1, card_column2, card_column3 = st.columns(3)

    with card_column1:
        st.metric(
            label="Número de productos distintos",
            value=filtered_data['item_name'].nunique()
        )

    with card_column2:
        st.metric(
            label="Precio unitario promedio",
            value=f"Q{filtered_data['item_unitprice'].astype('float').mean():,.2f}"
        )

    with card_column3:
        filtered_data['item_quantity'] = filtered_data['item_quantity'].astype(float)
        st.metric(
            label="Promedio de unidades vendidas por factura",
            value=f"{filtered_data.groupby('invoice_number')['item_quantity'].mean().mean():,.2f}"
        )

    # Create two columns
    left_column, right_column = st.columns(2)

    # Left column: Display the item summary table
    with left_column:
        # Group by item and calculate total sales, most frequent payee, and last sale date
        item_summary = filtered_data.groupby('item_name').agg(
            total_sales=('item_sales', 'sum'),
            top_payee=('payee_name', lambda x: x.value_counts().idxmax())
        ).reset_index()

        # Round total sales to 2 decimal places
        item_summary['total_sales'] = item_summary['total_sales'].round(2)

        # Add the last sale date for the top payee
        item_summary['last_sale_to_top_payee'] = item_summary.apply(
            lambda row: filtered_data[
            (filtered_data['item_name'] == row['item_name']) & 
            (filtered_data['payee_name'] == row['top_payee'])
            ]['issued_at'].max(),
            axis=1
        )

        # Rename columns for better readability
        item_summary.rename(columns={
            'item_name': 'Nombre del producto',
            'total_sales': 'Ventas totales',
            'top_payee': 'Mayor Comprador',
            'last_sale_to_top_payee': 'Última venta al mayor comprador'
        }, inplace=True)

        # Display the table in Streamlit
        st.subheader('Resumen histórico de ventas por producto')
        st.dataframe(item_summary.style.format({"Ventas totales": "Q{:,.2f}"}), hide_index=True, height=800)  # Set the height to 800 pixels

    # Right column: Display the scatter plot
    with right_column:
        # Group by item_quantity and item_unitprice, and count the number of sales
        scatter_data = filtered_data.groupby(['item_quantity', 'item_unitprice']).size().reset_index(name='sales_count')

        # Fit an exponential function to the data
        exp_fit = np.polyfit(scatter_data['item_unitprice'], np.log(scatter_data['item_quantity']), 1)
        exp_func = lambda x: np.exp(exp_fit[0] * x + exp_fit[1])
        exp_residuals = np.sum((scatter_data['item_quantity'] - exp_func(scatter_data['item_unitprice']))**2)

        # Fit a logarithmic function to the data
        log_fit = np.polyfit(np.log(scatter_data['item_unitprice']), scatter_data['item_quantity'], 1)
        log_func = lambda x: log_fit[0] * np.log(x) + log_fit[1]
        log_residuals = np.sum((scatter_data['item_quantity'] - log_func(scatter_data['item_unitprice']))**2)

        # Fit a grade 3 polynomial to the data
        poly_fit = np.polyfit(scatter_data['item_unitprice'], scatter_data['item_quantity'], 3)
        poly_func = lambda x: np.polyval(poly_fit, x)
        poly_residuals = np.sum((scatter_data['item_quantity'] - poly_func(scatter_data['item_unitprice']))**2)

        # Select the best fit based on residuals
        best_fit = min(
            [('Exponential', exp_func, exp_residuals),
             ('Logarithmic', log_func, log_residuals),
             ('Polynomial', poly_func, poly_residuals)],
            key=lambda x: x[2]
        )

        # Generate x values for the best fit line
        x_vals = np.linspace(scatter_data['item_unitprice'].min(), scatter_data['item_unitprice'].max(), 500)
        y_best_vals = best_fit[1](x_vals)

        # Create the scatter plot
        scatter_fig = px.scatter(
            scatter_data,
            x='item_unitprice',
            y='item_quantity',
            size='sales_count',
            title='Distribución de ventas por cantidad y precio unitario',
            labels={
            'item_quantity': 'Cantidad de producto',
            'item_unitprice': 'Precio unitario',
            'sales_count': 'Número de ventas'
            },
            size_max=20
        )

        # Add the best fit line to the scatter plot
        scatter_fig.add_scatter(x=x_vals, y=y_best_vals, mode='lines', name=f'Ajuste')

        # Adjust the height of the plot
        scatter_fig.update_layout(height=800)

        # Display the scatter plot
        st.plotly_chart(scatter_fig, use_container_width=True)
