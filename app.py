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

if not 'autheticated' in st.session_state: 
    st.session_state.autheticated = False 

with open('config.json', 'r') as file: 
    config = json.load(file) 

@st.cache_data
def fetch_data(url): 
    return requests.get(url = url).json() 

if not st.session_state.autheticated: 
    
    with st.sidebar:         
        pwd = st.sidebar.text_input('password', type = 'password') 
        st.session_state.autheticated = hashlib.sha256(pwd.encode()).hexdigest() in config['keys']

if st.session_state.autheticated:
    sales_data = pd.DataFrame(fetch_data(os.getenv("BASE_URL") + "/sales/details"))

    # Transform sales_data
    sales_data['creditnote_date'] = pd.to_datetime(sales_data['creditnote_date'])
    sales_data['issued_at'] = pd.to_datetime(sales_data['issued_at'])

    sales_data['real_unitprice'] = sales_data.groupby('invoice_number').apply(
        lambda group: group['item_unitprice'] - (
            group['extra_discount'].iloc[0] * (group['item_unitprice']) / group['subtotal'].iloc[0]
        )
    ).reset_index(level=0, drop=True)

    sales_data['item_sales'] = sales_data['real_unitprice'] * sales_data['item_quantity']

    # Summarize where creditnote_date is null
    summarized_data = (
        sales_data[sales_data['creditnote_date'].isnull()]
        .groupby(['issued_at', 'invoice_number', 'seller_name', 'payee_name', 'payee_nit', 'item_name'], as_index=False)
        .agg({'total': 'mean', 'due': 'mean', 'item_sales' : 'mean'})
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
        .agg({'total': 'mean', 'due': 'mean', 'item_sales' : 'mean'})
    )

    # Combine both datasets
    sales_data = pd.concat([summarized_data, creditnote_data], ignore_index=True)

    st.title('Vista General')

    ### SIDEBAR 
    with st.sidebar:
        min_date = sales_data['issued_at'].min()
        max_date = pd.Timestamp.today()
        start_date, end_date = st.date_input(
            "Select a date range",
            value=(pd.Timestamp(max_date.year, 1, 1), max_date),  # Default to Year-To-Date (YTD)
            min_value=min_date,
            max_value=max_date
        )

        # Filter sales_data by the selected date range
        filtered_sales_data = sales_data[
            (sales_data['issued_at'] >= pd.Timestamp(start_date)) & 
            (sales_data['issued_at'] <= pd.Timestamp(end_date))
        ]
    ### MAIN PANEL 

    ### HEADER 
    col1, col2, col3 = st.columns(3)

    # Overall total in the selected period
    overall_total = filtered_sales_data['item_sales'].sum()
    col1.metric("Overall Total", f"Q{overall_total:,.2f}")

    # Due amount in the selected period
    due_amount = filtered_sales_data['due'].sum()
    col2.metric("Due Amount", f"Q{due_amount:,.2f}")

    # Monthly growth trend as a percentage of the first value
    monthly_totals = (
        filtered_sales_data
        .groupby(filtered_sales_data['issued_at'].dt.to_period('M'))
        .agg({'item_sales': 'sum'})
        .reset_index()
    )
    monthly_totals['month'] = monthly_totals['issued_at'].dt.to_timestamp()
    monthly_totals['month_number'] = (monthly_totals['month'] - monthly_totals['month'].min()).dt.days

    # Fit linear regression
    X = monthly_totals[['month_number']]
    y = monthly_totals['item_sales']
    model = LinearRegression().fit(X, y)

    # Extract slope (growth trend)
    growth_trend = model.coef_[0]

    # Calculate growth trend as a percentage of the first value
    first_value = monthly_totals['item_sales'].iloc[0]
    growth_trend_percentage = (growth_trend / first_value) * 100 if first_value != 0 else 0
    col3.metric("Monthly Growth Trend", f"{'+' if growth_trend_percentage > 0 else ''}{growth_trend_percentage:,.1f}%/monthly")

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
    monthly_sales['month_text'] = monthly_sales['month'].dt.strftime('%B %Y')

    # Calculate Month-over-Month (MoM) growth
    monthly_sales['mom_growth'] = monthly_sales['monthly_total'].pct_change() * 100
    monthly_sales['mom_growth'] = monthly_sales['mom_growth'].fillna(0)

    # Create a bar chart with Altair
    bar_chart = alt.Chart(monthly_sales).mark_bar().encode(
        x=alt.X('month:T', title='Month', scale=alt.Scale(nice='month')),  # Ensure bars cover the whole month
        y=alt.Y('monthly_total:Q', title='Monthly Sales'),
        tooltip=[
            alt.Tooltip('month_text:N', title='Month'),
            alt.Tooltip('monthly_total:Q', title='Monthly Sales', format=',.2f'),
            alt.Tooltip('mom_growth:Q', title='MoM Growth (%)', format='.2f')
        ]
    ).properties(
        title="Monthly Sales with MoM Growth",
        width=800,
        height=400
    )

    st.altair_chart(bar_chart, use_container_width=True)

    ### TOP PERFORMERS

    # Create two columns
    left_col, right_col = st.columns(2)

    # Left column: Ranking of sellers by total amount and percentage of total
    with left_col:
        st.subheader("Ranking of Sellers")
        seller_ranking = (
            filtered_sales_data
            .assign(seller_name=lambda df: df['seller_name'].str.upper())  # Transform seller_name to upper case
            .groupby('seller_name', as_index=False)
            .agg({'total': 'sum'})
            .sort_values('total', ascending=False)
        )
        seller_ranking['percentage'] = ((seller_ranking['total'] / seller_ranking['total'].sum()) * 100).round(1).astype(str) + '%'
        seller_ranking['total'] = seller_ranking['total'].apply(lambda x: f"Q{x:,.2f}")
        st.dataframe(
            seller_ranking.rename(columns={'total': 'Total Amount', 'percentage': 'Percentage (%)'}),
            use_container_width=True,
            hide_index=True
        )

    # Right column: Top 10 items sold in the period
    with right_col:
        st.subheader("Top 10 Items Sold")
        top_items = (
            filtered_sales_data
            .groupby('item_name', as_index=False)
            .agg({'total': 'sum'})
            .sort_values('total', ascending=False)
            .head(10)
        )
        top_items['percentage'] = ((top_items['total'] / top_items['total'].sum()) * 100).round(1).astype(str) + '%'
        top_items['total'] = top_items['total'].apply(lambda x: f"Q{x:,.2f}")
        st.dataframe(
            top_items.rename(columns={'total': 'Total Amount', 'percentage': 'Percentage (%)'}),
            use_container_width=True,
            hide_index=True
        )

    ### ALERTS

    st.subheader("Highest Due Amounts with Oldest Issued Dates")
    highest_due = (
        filtered_sales_data
        .sort_values(['due', 'issued_at'], ascending=[False, True])
        .head(10)
        .loc[:, ['issued_at', 'invoice_number', 'seller_name', 'payee_name', 'due']]
    )
    highest_due['issued_at'] = highest_due['issued_at'].dt.strftime('%Y-%m-%d')
    highest_due['due'] = highest_due['due'].apply(lambda x: f"Q{x:,.2f}")
    st.dataframe(highest_due.rename(columns={
        'issued_at': 'Issued Date',
        'invoice_number': 'Invoice Number',
        'seller_name': 'Seller Name',
        'payee_name': 'Payee Name',
        'due': 'Due Amount'
    })
        , use_container_width=True
        , hide_index=True
    )
