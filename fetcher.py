"""Standalone daily fetch runner for SmartCity data collection."""

import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent))

from PVBattery.main import run_battery_monitoring


DATA_DIR = Path(__file__).parent / "data"
DB_PATH = DATA_DIR / "energy_data.db"


def save_to_database(result_dict):
    """
    Save one optimization result payload into SQLite tables.

    The function ensures schema availability (`daily_stats`, `hourly_data`),
    writes summary and hourly records with upsert semantics, and commits as a
    single transaction to avoid partial-day persistence.

    Args:
        result_dict: Dict returned by run_battery_monitoring.
    """
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    # Daily aggregates table: one row per delivery date.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_stats (
            date TEXT UNIQUE,
            smart_cost REAL,
            no_battery_cost REAL,
            savings REAL,
            pv_total REAL,
            load_total REAL,
            rate REAL
        )
    ''')
    
    # Hourly time series table: one row per (date, hour).
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS hourly_data (
            date TEXT,
            hour INTEGER,
            price REAL,
            pv REAL,
            load REAL,
            battery REAL,
            soc REAL,
            grid REAL,
            UNIQUE(date, hour)
        )
    ''')
    
    # Index speeds up per-day chart/history queries.
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_hourly_date ON hourly_data(date)
    ''')

    date_str = result_dict['start_date']
    stats = result_dict['stats']
    hourly = result_dict['hourly']

    try:
        # Upsert daily summary metrics.
        cursor.execute('''
            INSERT OR REPLACE INTO daily_stats 
            (date, smart_cost, no_battery_cost, savings, pv_total, load_total, rate)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            date_str,
            stats.get('smart_cost_huf'),
            stats.get('no_battery_cost_huf'),
            stats.get('saving_huf'),
            stats.get('total_pv_kwh'),
            stats.get('total_load_kwh'),
            stats.get('eur_huf_rate')
        ))
        
        # Prepare bulk hourly upsert for better write efficiency.
        hourly_records = []
        for h in hourly:
            hourly_records.append((
                date_str,
                h['hour'],
                h['price_huf_kwh'],
                h['pv_kw'],
                h['load_kw'],
                h['battery_kw'],
                h['soc_kwh'],
                h['grid_kw']
            ))
            
        cursor.executemany('''
            INSERT OR REPLACE INTO hourly_data 
            (date, hour, price, pv, load, battery, soc, grid)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', hourly_records)

        # Commit only after both summary and hourly inserts succeed.
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def fetch_and_save(target_date_str=None):
    """Run optimization for a target day and persist result to SQLite.

    Args:
        target_date_str: Date in YYYY-MM-DD. Defaults to tomorrow.

    Returns:
        Result dict (without plot image payload) after successful persistence.
    """
    # Daily batch job defaults to next day to precompute tomorrow's schedule.
    if target_date_str is None:
        target_date_str = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

    print(f"Fetching data for: {target_date_str}")

    try:
        result = run_battery_monitoring(
            start_date_str=target_date_str,
            end_date_str=(datetime.strptime(target_date_str, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d')
        )
    except Exception as e:
        print(f"Battery monitoring failed: {e}")
        raise

    # Drop large image blob before storing to keep DB lean.
    if 'plot_image_base64' in result:
        del result['plot_image_base64']

    save_to_database(result)
    print(f"Saved to database {DB_PATH}")
    return result


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    result = fetch_and_save(target)
    print(json.dumps(result["stats"], indent=2))
