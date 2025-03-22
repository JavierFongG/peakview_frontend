import streamlit as st 
import requests
import os 
from dotenv import load_dotenv
import pandas as pd 
import json 
import hashlib
import altair as alt
from sklearn.linear_model import LinearRegression
import numpy as np

load_dotenv(override=True)

st.set_page_config(layout="wide")

if not 'authenticated' in st.session_state: 
    st.session_state.authenticated = False

with open('config.json', 'r') as file: 
    config = json.load(file) 

@st.cache_data
def fetch_data(url): 
    return requests.get(url = url).json() 

if not st.session_state.authenticated: 
    
    with st.sidebar:         
        pwd = st.sidebar.text_input('password', type = 'password') 
        st.session_state.authenticated = hashlib.sha256(pwd.encode()).hexdigest() in config['keys']

if st.session_state.authenticated:

    sales_data = pd.DataFrame(fetch_data(os.getenv("BASE_URL") + "/sales/details"))

    # Transform sales_data
    sales_data['creditnote_date'] = pd.to_datetime(sales_data['creditnote_date'])
    sales_data['issued_at'] = pd.to_datetime(sales_data['issued_at'])

    # Summarize where creditnote_date is null
    summarized_data = (
        sales_data
        .groupby(['issued_at', 'invoice_number', 'seller_name', 'payee_name', 'payee_nit', 'item_name'], as_index=False)
        .agg({'total': 'mean', 'due': 'mean', 'item_sales' : 'sum'})
    )

    # Process where creditnote_date is not null
    creditnote_data = (
        sales_data[sales_data['creditnote_date'].notnull()]
        .assign(
            issued_at=lambda df: df['creditnote_date'],
            total=lambda df: df['total'] * -1,
            item_sales = lambda df: df['item_sales'] * -1 ,
            due = 0
        )
        .groupby(['issued_at', 'invoice_number', 'seller_name', 'payee_name', 'payee_nit', 'item_name'], as_index=False)
        .agg({'total': 'mean', 'due': 'mean', 'item_sales' : 'sum'})
    )

    # Combine both datasets
    sales_data = pd.concat([summarized_data, creditnote_data], ignore_index=True)

    

    ### SIDEBAR 
    with st.sidebar:
        min_date = sales_data['issued_at'].min()
        max_date = pd.Timestamp.today()
        date_range = st.date_input(
            "Select a date range",
            value=(pd.Timestamp(max_date.year, 1, 1), max_date),  # Default to Year-To-Date (YTD)
            min_value=min_date,
            max_value=max_date
        )



    ### MAIN PANEL 

    st.title('Vista General')

    ### HEADER 
    if len(date_range) < 2: 
        st.subheader('Seleccione un período valido')
    else:
        st.text(f'Periodo: {date_range[0]} a {date_range[1]}')
        # Filter sales_data by the selected date range
        filtered_sales_data = sales_data[
            (sales_data['issued_at'] >= pd.Timestamp(date_range[0])) & 
            (sales_data['issued_at'] <= pd.Timestamp(date_range[1]))
        ]
        col1, col2, col3 = st.columns(3)

        # Overall total in the selected period
        overall_total = filtered_sales_data['item_sales'].sum()
        overall_total_muestras = filtered_sales_data[filtered_sales_data['payee_nit'] != '105272981']['item_sales'].sum()
        col1.metric(
            "Venta Total"
            , value = f"Q{overall_total:,.2f}"
            , delta = f"Sin Muestras: Q{overall_total_muestras:,.2f}"
            , delta_color = 'off'
        )

        # Due amount in the selected period
        due_amount = filtered_sales_data['due'].sum()
        col2.metric("Monto por cobrar", f"Q{due_amount:,.2f}")

        # Monthly growth trend in terms of average percentage growth
        monthly_growth = (
            filtered_sales_data
            .groupby(filtered_sales_data['issued_at'].dt.to_period('M'))
            .agg({'item_sales': 'sum'})
            .pct_change() * 100
        )
        average_growth = monthly_growth['item_sales'].mean()

        col3.metric(
            "Crecimiento MoM Promedio",
            value=f"{average_growth:.2f}%"
        )
    
        ### TIME SERIES

        # Prepare data for monthly sales
        monthly_sales = (
            filtered_sales_data
            .groupby(filtered_sales_data['issued_at'].dt.to_period('M'))
            .agg({'item_sales': 'sum'})
            .reset_index()
            .rename(columns={'issued_at': 'month', 'item_sales': 'monthly_total'})
        )
        monthly_sales['month'] = monthly_sales['month'].dt.to_timestamp()
        monthly_sales['month_text'] = monthly_sales['month'].dt.strftime('%B %Y')

        # Ensure no empty dates by creating a complete date range
        all_months = pd.date_range(
            start=monthly_sales['month'].min(), 
            end=monthly_sales['month'].max(), 
            freq='MS'
        )
        monthly_sales = monthly_sales.set_index('month').reindex(all_months).fillna(0).reset_index()
        monthly_sales = monthly_sales.rename(columns={'index': 'month'})
        monthly_sales['month_text'] = monthly_sales['month'].dt.strftime('%Y-%m')

        # Calculate Month-over-Month (MoM) growth
        monthly_sales['mom_growth'] = monthly_sales['monthly_total'].pct_change() * 100
        monthly_sales['mom_growth'] = monthly_sales['mom_growth'].fillna(0)

        # Create a bar chart with Altair
        bar_chart = alt.Chart(monthly_sales).mark_bar().encode(
            x=alt.X('month_text:N', title='Month'),  # Display dates as strings in format YYYY MMM
            y=alt.Y('monthly_total:Q', title='Monthly Sales'),
            tooltip=[
                alt.Tooltip('month_text:N', title='Mes'),
                alt.Tooltip('monthly_total:Q', title='Venta mensual', format=',.2f'),
                alt.Tooltip('mom_growth:Q', title='MoM (%)', format='.2f')
            ]
        ).properties(
            title="Ventas mensuales",
            width=800,
            height=400
        )

        st.altair_chart(bar_chart, use_container_width=True)

        ### TOP PERFORMERS

        # Create two columns
        left_col, right_col = st.columns(2)

        # Left column: Ranking of sellers by total amount and percentage of total
        with left_col:
            st.subheader("Ranking Vendedores")
            seller_ranking = (
                filtered_sales_data
                .assign(seller_name=lambda df: df['seller_name'].str.upper())  # Transform seller_name to upper case
                .groupby('seller_name', as_index=False)
                .agg({'item_sales': 'sum'})
                .sort_values('item_sales', ascending=False)
            )
            seller_ranking['percentage'] = ((seller_ranking['item_sales'] / seller_ranking['item_sales'].sum()) * 100).round(1).astype(str) + '%'
            seller_ranking['item_sales'] = seller_ranking['item_sales'].apply(lambda x: f"Q {x:,.2f}")
            st.dataframe(
                seller_ranking.rename(
                    columns={
                        'seller_name': 'Vendedor'
                        , 'item_sales': 'Monto vendido'
                        , 'percentage': 'Porcentaje de la venta (%)'
                    }),
                use_container_width=True,
                hide_index=True
            )

        # Right column: Top 10 items sold in the period
        with right_col:
            st.subheader("Top 10 Productos")
            top_items = (
                filtered_sales_data
                .groupby('item_name', as_index=False)
                .agg({'item_sales': 'sum'})
                .sort_values('item_sales', ascending=False)
                .head(10)
            )
            top_items['percentage'] = ((top_items['item_sales'] / top_items['item_sales'].sum()) * 100).round(1).astype(str) + '%'
            top_items['item_sales'] = top_items['item_sales'].apply(lambda x: f"Q{x:,.2f}")
            st.dataframe(
                top_items.rename(columns={
                    'item_name' : 'Producto'
                    , 'item_sales': 'Monto vendido'
                    , 'percentage': 'Porcentaje de la venta (%)'
                }),
                use_container_width=True,
                hide_index=True
            )

        ### ALERTS

        st.subheader("Facturas por cobrar")
        highest_due = (
            sales_data[sales_data['item_sales']>0]
            .sort_values(['due', 'issued_at'], ascending=[False, True])
            .query('due > 0')
            .loc[:, ['issued_at', 'invoice_number', 'seller_name', 'payee_name', 'due']]
        )
        highest_due['days_since_issue'] = (pd.Timestamp.today() - highest_due['issued_at']).dt.days
        highest_due['issued_at'] = highest_due['issued_at'].dt.strftime('%Y-%m-%d')

        # Add alert emoji for days since issue greater than 90
        highest_due['days_since_issue'] = highest_due['days_since_issue'].apply(
            lambda x: f"{x} 🚨" if x > 90 else str(x)
        )

        highest_due = highest_due.groupby(['issued_at', 'days_since_issue', 'invoice_number', 'seller_name', 'payee_name'])['due'].mean().reset_index()
        highest_due['due'] = highest_due['due'].apply(lambda x: f"Q{x:,.2f}")
        st.dataframe(highest_due.rename(columns={
            'issued_at': 'Fecha emisión',
            'invoice_number': 'No. Factura',
            'seller_name': 'Vendedor',
            'payee_name': 'Cliente',
            'due': 'Monto por Cobrar',
            'days_since_issue': 'Días desde emisión'
        })
            , use_container_width=True
            , hide_index=True
        )
