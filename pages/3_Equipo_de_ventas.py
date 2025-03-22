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
    st.session_state.authenticated = False

@st.cache_data
def fetch_data(url): 
    return requests.get(url = url).json() 


if not st.session_state.authenticated: 
    
    with st.sidebar:         
        pwd = st.sidebar.text_input('password', type = 'password') 
        st.session_state.authenticated = hashlib.sha256(pwd.encode()).hexdigest() in config['keys']

if st.session_state.authenticated:

    st.title('Equipo de ventas')
    sales_data = pd.DataFrame(fetch_data(os.getenv("BASE_URL") + "/sales/details"))

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


    sales_data['seller_name'] = sales_data['seller_name'].str.upper()
    seller_names = sales_data['seller_name'].unique()
    default_sellers = ['ISABEL DE LEONARDO', 'BRETZY MARTINEZ', 'DELIA RODRIGUEZ']
    selected_sellers = st.multiselect(
        'Listado de Vendedores', 
        seller_names, 
        default=[seller for seller in default_sellers if seller in seller_names]
    )
    filtered_data = sales_data[sales_data['seller_name'].isin(selected_sellers)]
    
    current_year = pd.Timestamp.now().year
    filtered_data['issued_at'] = pd.to_datetime(filtered_data['issued_at'])
    current_date = pd.Timestamp.now()
    start_of_year = pd.Timestamp(year=current_year, month=1, day=1)

    # Filter data for the current year up to today
    current_year_data = filtered_data[
        (filtered_data['issued_at'] >= start_of_year) & 
        (filtered_data['issued_at'] <= current_date)
    ]

    # Filter data for the same period last year
    previous_year_start = start_of_year - pd.DateOffset(years=1)
    previous_year_end = current_date - pd.DateOffset(years=1)
    previous_year_data = filtered_data[
        (filtered_data['issued_at'] >= previous_year_start) & 
        (filtered_data['issued_at'] <= previous_year_end)
    ]

    # Calculate YTD sales and YoY growth
    ytd_sales = current_year_data.groupby('seller_name')['item_sales'].sum().reindex(selected_sellers, fill_value=0)
    previous_ytd_sales = previous_year_data.groupby('seller_name')['item_sales'].sum().reindex(selected_sellers, fill_value=0)

    yoy_growth = ((ytd_sales - previous_ytd_sales) / previous_ytd_sales.replace(0, np.nan)) * 100
    yoy_growth = yoy_growth.fillna(0)  # Handle division by zero or NaN cases

    ytd_sales_df = pd.DataFrame({
        'Seller Name': ytd_sales.index, 
        'YTD Sales': ytd_sales.values, 
        'YoY Growth': yoy_growth.values
    }).sort_values('Seller Name').reset_index()

    # Display metrics for each seller
    columns = st.columns(len(selected_sellers))
    for col, (index, row) in zip(columns, ytd_sales_df.iterrows()):
        
        with col.container(border=True):

            st.header(row['Seller Name'])
            st.metric(
            label="Ventas YTD", 
            value=f"Q{row['YTD Sales']:,.2f}", 
            delta=f"{row['YoY Growth']:.2f}% - YoY"
            )

            # Calculate sales for the last 30 days
            last_30_days_start = current_date - pd.Timedelta(days=30)
            last_30_days_data = filtered_data[
            (filtered_data['issued_at'] >= last_30_days_start) & 
            (filtered_data['issued_at'] <= current_date) &
            (filtered_data['seller_name'] == row['Seller Name'])
            ]
            last_30_days_sales = last_30_days_data.groupby('seller_name')['item_sales'].sum().reindex(selected_sellers, fill_value=0)

            # Display last 30 days sales metric
            st.metric(
            label="Ventas últimos 30 días", 
            value=f"Q{last_30_days_sales[row['Seller Name']]:,.2f}"
            )
            st.markdown("</div>", unsafe_allow_html=True)

            # Create a bar plot for the last 30 days of sales
            last_30_days_sales_df = last_30_days_data.groupby('issued_at')['item_sales'].sum().reset_index()
            last_30_days_sales_df['issued_at'] = last_30_days_sales_df['issued_at'].dt.date  # Convert to date for better readability

            # Fill missing dates with 0 sales
            all_dates = pd.date_range(start=last_30_days_start, end=current_date).date
            last_30_days_sales_df = last_30_days_sales_df.set_index('issued_at').reindex(all_dates, fill_value=0).reset_index()
            last_30_days_sales_df.columns = ['issued_at', 'item_sales']

            fig = px.bar(
            last_30_days_sales_df, 
            x='issued_at', 
            y='item_sales', 
            title=f"Ventas últimos 30 días - {row['Seller Name'].split(' ')[0]}",
            labels={'issued_at': 'Fecha', 'item_sales': 'Ventas'},
            text_auto=True
            )
            fig.update_layout(xaxis_title="Fecha", yaxis_title="Ventas", title_x=0.0)

            st.plotly_chart(fig, use_container_width=True)

            # Filter data for the current month for the specific seller
            start_of_month = pd.Timestamp(year=current_date.year, month=current_date.month, day=1)
            current_month_data = filtered_data[
            (filtered_data['issued_at'] >= start_of_month) & 
            (filtered_data['issued_at'] <= current_date) &
            (filtered_data['seller_name'] == row['Seller Name'])
            ]

            # Accumulate sales for the current month for the specific seller
            current_month_sales_df = (
            current_month_data.groupby('issued_at')['item_sales']
            .sum()
            .cumsum()
            .reset_index()
            )
            current_month_sales_df['issued_at'] = current_month_sales_df['issued_at'].dt.date  # Convert to date for readability
            # Calculate total sales for the current month
            total_current_month_sales = current_month_data['item_sales'].sum()

            # Filter data for the previous month for the specific seller
            start_of_previous_month = start_of_month - pd.DateOffset(months=1)
            end_of_previous_month = start_of_month - pd.Timedelta(days=1)
            previous_month_data = filtered_data[
            (filtered_data['issued_at'] >= start_of_previous_month) & 
            (filtered_data['issued_at'] <= end_of_previous_month) &
            (filtered_data['seller_name'] == row['Seller Name'])
            ]

            # Calculate total sales for the previous month
            total_previous_month_sales = previous_month_data['item_sales'].sum()

            # Calculate MoM growth
            mom_growth = ((total_current_month_sales - total_previous_month_sales) / 
                  (total_previous_month_sales if total_previous_month_sales != 0 else np.nan)) * 100
            mom_growth = 0 if np.isnan(mom_growth) else mom_growth  # Handle division by zero or NaN cases

            # Display total sales for the current month with MoM growth
            st.metric(
            label="Ventas del mes actual", 
            value=f"Q{total_current_month_sales:,.2f}", 
            delta=f"{mom_growth:.2f}% - MoM"
            )
            # Create an accumulated line plot for the current month for the specific seller
            fig_accumulated = px.line(
            current_month_sales_df,
            x='issued_at',
            y='item_sales',
            title=f"Ventas acumuladas del mes - {row['Seller Name'].split(' ')[0]}",
            labels={'issued_at': 'Fecha', 'item_sales': 'Ventas acumuladas'},
            )
            fig_accumulated.add_hline(y=50000, line_dash="dot", line_color="gray", opacity=0.5, annotation_text="50k")
            fig_accumulated.add_hline(y=100000, line_dash="dot", line_color="gray", opacity=0.5, annotation_text="100k")
            fig_accumulated.add_hline(y=150000, line_dash="dot", line_color="gray", opacity=0.5, annotation_text="150k")
            fig_accumulated.add_hline(y=200000, line_dash="dot", line_color="gray", opacity=0.5, annotation_text="200k")
            fig_accumulated.update_layout(xaxis_title="Fecha", yaxis_title="Ventas acumuladas", title_x=0.0)

            st.plotly_chart(fig_accumulated, use_container_width=True)