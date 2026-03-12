import os
from datetime import datetime

import pandas as pd
import requests
from dotenv import load_dotenv
from entsoe import EntsoePandasClient
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS

from PVBattery.main import run_battery_monitoring


load_dotenv()

app = Flask(__name__)
CORS(app)

API_KEY = os.environ.get("ENTSOE_API_KEY")
COUNTRY_CODE = "10YHU-MAVIR----U"
DEFAULT_HUF_RATE = 410.0

if not API_KEY:
    raise RuntimeError("ENTSOE_API_KEY environment variable is required")


def get_eur_huf_rates(start_date_str, end_date_str):
    try:
        start_dt = pd.to_datetime(start_date_str) - pd.Timedelta(days=7)
        start_fetch = start_dt.strftime('%Y-%m-%d')
        url = f"https://api.frankfurter.app/{start_fetch}..{end_date_str}?from=EUR&to=HUF"
        response = requests.get(url, timeout=5)

        if response.status_code == 200:
            data = response.json()
            rates = {date: values['HUF'] for date, values in data.get('rates', {}).items()}
            return pd.Series(rates)
    except Exception as exc:
        print(f"Warning: Failed to fetch exchange rates: {exc}")

    return pd.Series(dtype=float)


def get_requested_dates():
    today = datetime.now().date()
    tomorrow = today + pd.Timedelta(days=1)
    start_str = request.args.get('start', today.strftime('%Y-%m-%d'))
    end_str = request.args.get('end', tomorrow.strftime('%Y-%m-%d'))
    return start_str, end_str


@app.route('/')
def index():
    return send_file('index.html')


@app.route('/api/prices')
def get_prices():
    start_str, end_str = get_requested_dates()

    try:
        client = EntsoePandasClient(api_key=API_KEY)
        start = pd.Timestamp(start_str, tz='Europe/Budapest')
        end = pd.Timestamp(end_str, tz='Europe/Budapest') + pd.Timedelta(days=1)
        prices_series = client.query_day_ahead_prices(COUNTRY_CODE, start=start, end=end)

        if prices_series.empty:
            return jsonify({"error": "No price data available for the selected period."}), 404

        prices_df = pd.DataFrame(prices_series, columns=['EUR_MWh'])
        rates_series = get_eur_huf_rates(start_str, end_str)
        rates_series.index = pd.to_datetime(rates_series.index)
        full_dates = pd.date_range(start=start_str, end=end_str, freq='D')

        if rates_series.empty:
            rates_df = pd.DataFrame({'HUF': DEFAULT_HUF_RATE}, index=full_dates)
        else:
            rates_df = pd.DataFrame(
                index=pd.date_range(start=rates_series.index.min(), end=end_str, freq='D')
            )
            rates_df['HUF'] = rates_series
            rates_df['HUF'] = rates_df['HUF'].ffill().bfill()
            rates_df = rates_df.reindex(full_dates)
            rates_df['HUF'] = rates_df['HUF'].fillna(DEFAULT_HUF_RATE)

        prices_df['date'] = prices_df.index.tz_convert('Europe/Budapest').normalize().tz_localize(None)
        prices_df['HUF_kWh'] = (prices_df['EUR_MWh'] * prices_df['date'].map(rates_df['HUF'])) / 1000

        result = prices_df.reset_index()[['index', 'EUR_MWh', 'HUF_kWh']]
        result.columns = ['time', 'EUR_MWh', 'HUF_kWh']
        result['time'] = result['time'].dt.strftime('%Y-%m-%dT%H:%M:%S%z')

        return jsonify(result.to_dict(orient='records'))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route('/api/battery-monitor')
def get_battery_monitor():
    start_str, end_str = get_requested_dates()

    try:
        return jsonify(run_battery_monitoring(start_str, end_str))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)
