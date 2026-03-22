# SmartCity Data Fetcher — Standalone Runner

# This script is designed to be run daily by GitHub Actions.
# It fetches prices + PV data, runs battery optimization, and saves to JSON.
# Run without Flask — just: python3 fetcher.py

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

# Ensure project root is in path
import sys
sys.path.insert(0, str(Path(__file__).parent))

from PVBattery.main import run_battery_monitoring


DATA_DIR = Path(__file__).parent / "data"
ARCHIVE_DIR = DATA_DIR / "archive"


def fetch_and_save(target_date_str=None):
    if target_date_str is None:
        target_date_str = datetime.now().strftime('%Y-%m-%d')

    print(f"Fetching data for: {target_date_str}")

    try:
        result = run_battery_monitoring(
            start_date_str=target_date_str,
            end_date_str=(datetime.strptime(target_date_str, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d')
        )
    except Exception as e:
        print(f"Battery monitoring failed: {e}")
        raise

    # Save to date-labelled file
    DATA_DIR.mkdir(exist_ok=True)
    out_file = DATA_DIR / f"{target_date_str}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"Saved to {out_file}")
    return result


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    result = fetch_and_save(target)
    print(json.dumps(result["stats"], indent=2))
