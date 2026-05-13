import os
import sqlite3
from datetime import datetime, timedelta

import pandas as pd
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS

from PVBattery.main import run_battery_monitoring
from PVBattery.visualizer import plot_results_base64

load_dotenv()

app = Flask(__name__)
CORS(app)

API_KEY = os.environ.get("ENTSOE_API_KEY")

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
    """Load a cached battery monitoring result for a given date from SQLite."""
    db_path = os.path.join(DATA_DIR, "energy_data.db")
    if not os.path.exists(db_path):
        return None

    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM daily_stats WHERE date = ?", (date_str,))
            daily_row = cursor.fetchone()
            if not daily_row:
                return None
            
            cursor.execute("SELECT * FROM hourly_data WHERE date = ? ORDER BY hour ASC", (date_str,))
            hourly_rows = cursor.fetchall()
            
            if not hourly_rows or len(hourly_rows) != 24:
                return None
            
            hourly = []
            T = range(24)
            prices = []
            pv = []
            load = []
            soc_values = []
            battery = []
            grid = []
            
            for r in hourly_rows:
                hourly.append({
                    'hour': r['hour'],
                    'price_huf_kwh': r['price'],
                    'pv_kw': r['pv'],
                    'load_kw': r['load'],
                    'battery_kw': r['battery'],
                    'soc_kwh': r['soc'],
                    'grid_kw': r['grid'],
                })
                prices.append(r['price'])
                pv.append(r['pv'])
                load.append(r['load'])
                soc_values.append(r['soc'])
                battery.append(r['battery'])
                grid.append(r['grid'])
                
            pure_grid_cost = sum(load[t] * prices[t] for t in T)
            avg_price = sum(prices) / len(prices) if prices else 0.0
            
            stats = {
                'smart_cost_huf': daily_row['smart_cost'],
                'no_battery_cost_huf': daily_row['no_battery_cost'],
                'saving_huf': daily_row['savings'],
                'total_pv_kwh': daily_row['pv_total'],
                'total_load_kwh': daily_row['load_total'],
                'eur_huf_rate': daily_row['rate'],
                'avg_price_huf_kwh': avg_price,
                'pure_grid_cost_huf': pure_grid_cost,
                'total_saving_vs_grid_huf': pure_grid_cost - daily_row['smart_cost']
            }

            plot_b64 = plot_results_base64(T, prices, pv, load, soc_values, battery, grid)
            
            end_date_str = (datetime.strptime(date_str, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d')
            
            return {
                'status': 'Optimal',
                'start_date': date_str,
                'end_date': end_date_str,
                'plot_image_base64': plot_b64,
                'stats': stats,
                'hourly': hourly
            }
            
    except Exception as e:
        print(f"Error reading from DB: {e}")
        return None


def list_available_dates():
    """Return the dates that have stored data in SQLite."""
    db_path = os.path.join(DATA_DIR, "energy_data.db")
    if not os.path.exists(db_path):
        return []
    
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT date FROM daily_stats ORDER BY date ASC")
            rows = cursor.fetchall()
            return [row[0] for row in rows]
    except Exception as e:
        print(f"Error reading dates from DB: {e}")
        return []


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
    return jsonify(list_available_dates())


@app.route('/api/savings-series')
def get_savings_series():
    """Return savings and related daily metrics from the database.

    Optional query params:
      - start: inclusive start date (YYYY-MM-DD)
      - end: inclusive end date (YYYY-MM-DD)
    If omitted, returns the full history ordered by date ascending.
    """
    db_path = os.path.join(DATA_DIR, "energy_data.db")
    if not os.path.exists(db_path):
        return jsonify([])

    start = request.args.get('start')
    end = request.args.get('end')

    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            sql = (
                "SELECT date, savings, smart_cost, no_battery_cost, pv_total, load_total"
                " FROM daily_stats"
            )
            params = []
            if start and end:
                sql += " WHERE date >= ? AND date <= ?"
                params = [start, end]
            elif start:
                sql += " WHERE date >= ?"
                params = [start]
            elif end:
                sql += " WHERE date <= ?"
                params = [end]

            sql += " ORDER BY date ASC"

            cursor.execute(sql, params)
            rows = cursor.fetchall()

            series = []
            for r in rows:
                date_str = r['date']
                cursor.execute("SELECT price, load FROM hourly_data WHERE date = ? ORDER BY hour ASC", (date_str,))
                hourly_rows = cursor.fetchall()
                pure_grid_cost = sum(h['load'] * h['price'] for h in hourly_rows) if hourly_rows else None
                
                series.append({
                    'date': r['date'],
                    'savings': float(r['savings']) if r['savings'] is not None else None,
                    'smart_cost': float(r['smart_cost']) if r['smart_cost'] is not None else None,
                    'no_battery_cost': float(r['no_battery_cost']) if r['no_battery_cost'] is not None else None,
                    'pure_grid_cost': float(pure_grid_cost) if pure_grid_cost is not None else None,
                    'pv_total': float(r['pv_total']) if r['pv_total'] is not None else None,
                    'load_total': float(r['load_total']) if r['load_total'] is not None else None,
                })

            return jsonify(series)
    except Exception as e:
        print(f"Error reading savings series from DB: {e}")
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)
