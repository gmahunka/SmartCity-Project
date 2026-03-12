import os
import requests
import pandas as pd
from flask import Flask, request, jsonify
from flask_cors import CORS
from entsoe import EntsoePandasClient
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

API_KEY = os.environ.get("ENTSOE_API_KEY")
COUNTRY_CODE = "10YHU-MAVIR----U"  # Country code for Hungary (HUPX)

if not API_KEY:
    raise RuntimeError("ENTSOE_API_KEY environment variable is required")

def get_eur_huf_rates(start_date_str, end_date_str):
    """
    Fetches the EUR to HUF exchange rates for a given date range.
    Fetches from 7 days prior to the start date to ensure we have a valid
    weekday rate to forward-fill over weekends/holidays.
    """
    try:
        # Buffer the start date by 7 days to account for weekends and long holidays
        start_dt = pd.to_datetime(start_date_str) - pd.Timedelta(days=7)
        start_fetch = start_dt.strftime('%Y-%m-%d')
        
        url = f"https://api.frankfurter.app/{start_fetch}..{end_date_str}?from=EUR&to=HUF"
        r = requests.get(url, timeout=5)
        
        if r.status_code == 200:
            data = r.json()
            rates = {date: rates['HUF'] for date, rates in data.get('rates', {}).items()}
            return pd.Series(rates)
    except Exception as e:
        print(f"Warning: Failed to fetch exchange rates: {e}")
        
    # Return an empty series if the API fails
    return pd.Series(dtype=float)

@app.route('/api/prices')
def get_prices():
    # Calculate default dates: yesterday and today
    today = datetime.now().date()
    yesterday = today - pd.Timedelta(days=1)
    
    # Get parameters from the frontend, use defaults if missing
    start_str = request.args.get('start', yesterday.strftime('%Y-%m-%d'))
    end_str = request.args.get('end', today.strftime('%Y-%m-%d'))

    try:
        client = EntsoePandasClient(api_key=API_KEY)
        
        # Convert dates to ENTSO-E required format (timezone aware)
        start = pd.Timestamp(start_str, tz='Europe/Budapest')
        # Add 1 day to the end date to include the full day up to midnight
        end = pd.Timestamp(end_str, tz='Europe/Budapest') + pd.Timedelta(days=1)

        # API call to ENTSO-E
        ts = client.query_day_ahead_prices(COUNTRY_CODE, start=start, end=end)
        
        if ts.empty:
            return jsonify({"error": "No price data available for the selected period."}), 404
            
        df = pd.DataFrame(ts, columns=['EUR_MWh'])
        
        # --- Currency Exchange Logic ---
        
        # 1. Fetch historical exchange rates
        rates_series = get_eur_huf_rates(start_str, end_str)
        rates_series.index = pd.to_datetime(rates_series.index)
        
        # 2. Create a full daily date range for the requested period
        full_dates = pd.date_range(start=start_str, end=end_str, freq='D')
        
        if rates_series.empty:
            # Fallback if the API is completely down
            rates_df = pd.DataFrame({'HUF': 410.0}, index=full_dates)
        else:
            # Create a dataframe from the earliest fetched rate up to the end date
            rates_df = pd.DataFrame(index=pd.date_range(start=rates_series.index.min(), end=end_str, freq='D'))
            rates_df['HUF'] = rates_series
            
            # Forward fill to cover weekends/holidays, then backward fill as a safety net
            rates_df['HUF'] = rates_df['HUF'].ffill().bfill()
            
            # Reindex to strictly match the requested dates and fallback to 410.0 if still NaN
            rates_df = rates_df.reindex(full_dates)
            rates_df['HUF'] = rates_df['HUF'].fillna(410.0)

        # 3. Map the correct daily exchange rate to the hourly electricity prices
        # Extract just the timezone-naive date from the ENTSO-E datetime index
        df['date'] = df.index.tz_convert('Europe/Budapest').normalize().tz_localize(None)
        
        # Map the rate based on the date and calculate HUF/kWh
        df['HUF_rate'] = df['date'].map(rates_df['HUF'])
        df['HUF_kWh'] = (df['EUR_MWh'] * df['HUF_rate']) / 1000
        
        # Clean up the dataframe for the frontend JSON response
        df = df.drop(columns=['date', 'HUF_rate'])
        result = df.reset_index()
        result.columns = ['time', 'EUR_MWh', 'HUF_kWh']
        
        return result.to_json(orient='records', date_format='iso')

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)