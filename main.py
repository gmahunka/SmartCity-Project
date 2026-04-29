import json
import os
from datetime import datetime
from functools import wraps

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

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

if not API_KEY:
    raise RuntimeError("ENTSOE_API_KEY environment variable is required")

def get_requested_dates():
    today = datetime.now().date()
    tomorrow = today + pd.Timedelta(days=1)
    start_str = request.args.get('start', today.strftime('%Y-%m-%d'))
    end_str = request.args.get('end', tomorrow.strftime('%Y-%m-%d'))
    return start_str, end_str


def load_stored_data(date_str):
    """Load cached battery monitoring result for a given date."""
    data_file = os.path.join(DATA_DIR, f"{date_str}.json")
    if os.path.exists(data_file):
        with open(data_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def list_available_dates():
    if not os.path.isdir(DATA_DIR):
        return []
    return sorted(
        os.path.splitext(filename)[0]
        for filename in os.listdir(DATA_DIR)
        if filename.endswith('.json')
    )


def is_live_call_allowed():
    allow_live = request.args.get('allow_live', 'false').strip().lower()
    return allow_live in {'1', 'true', 'yes', 'on'}


@app.route('/')
def index():
    return send_file('index.html')

@app.route('/api/battery-monitor')
def get_battery_monitor():
    start_str, end_str = get_requested_dates()

    force_refresh = request.args.get('force_refresh', 'false').strip().lower() in {'1', 'true', 'yes', 'on'}
    allow_live = is_live_call_allowed()

    if not force_refresh:
        stored = load_stored_data(start_str)
        if stored:
            stored["source"] = "cached"
            return jsonify(stored)
    


    if not allow_live:
        return jsonify({
            "error": "No cached data available for the selected date.",
            "source": "none"
        }), 404

    try:
        result = run_battery_monitoring(start_str, end_str)
        if force_refresh:
            result["source"] = "live_recomputed_unsaved"
        else:
            result["source"] = "live"
        return jsonify(result)
    
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route('/api/available-dates')
def get_available_dates():
    """Return list of dates that have stored data."""
    return jsonify(list_available_dates())


if __name__ == '__main__':
    app.run(debug=True, port=5000)
