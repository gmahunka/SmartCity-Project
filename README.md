# SmartCity Project

**Project Overview**
- **Description:**: SmartCity is a small energy optimisation and monitoring toolkit that simulates and evaluates PV + battery operation for a single-site residential or small commercial setup. It computes day-ahead charging/discharging schedules that minimise cost given market prices, PV forecasts and a local load profile.
- **Components:**: a Flask API server (`main.py`), a daily fetcher/runner (`fetcher.py`), and the `PVBattery` package which contains data fetching, optimization (`PuLP`) and visualization logic.

**Key Features**
- **Day-ahead optimization:**: formulates and solves an hourly battery dispatch optimization with `PuLP`.
- **Price & exchange rate fetching:**: fetches day-ahead electricity prices from ENTSO-E and EUR→HUF rates from Frankfurter.
- **PV forecasting:**: uses `pvlib` together with Open-Meteo weather forecasts to estimate PV generation.
- **Visualization:**: generates plots (Matplotlib) and returns base64-encoded images for the frontend or API consumers.
- **Local caching & persistence:**: stores daily statistics and hourly data in a local SQLite DB under `data/energy_data.db` and uses `data/load_profiles.csv` for consumption profiles.

**Main HTTP Endpoints**
- `GET /api/battery-monitor` — compute or return cached battery monitoring result for a date (query params: `start`, `end`, `force_refresh`, `allow_live`).
- `GET /api/available-dates` — list dates for which cached results exist.
- `GET /api/savings-series` — return historical daily savings series (optional `start` and `end` query params).

**Used APIs & Libraries**
- **Python libraries (requirements.txt):**: `flask`, `flask-Cors`, `requests`, `python-dotenv`, `pandas`, `pulp` (PuLP), `matplotlib`, `pvlib`, `entsoe-py`.
- **ENTSO-E (via entsoe-py):**: day-ahead electricity prices (requires `ENTSOE_API_KEY` environment variable).
- **Frankfurter (api.frankfurter.dev):**: EUR → HUF exchange rate lookup used to convert prices.
- **Open-Meteo:**: hourly weather forecast used as input for PV generation modelling.
- **pvlib:**: PV system modelchain for AC power forecasts from weather inputs.
- **SQLite (stdlib `sqlite3`):**: local persistence for daily and hourly results.

**Environment / Configuration**
- Set `ENTSOE_API_KEY` in your environment (used by `entsoe-py`) — required for live ENTSO-E calls.
- Optionally use a Python virtual environment and install dependencies from `requirements.txt`.

**Quick start**
1. Create and activate a virtualenv.  
2. Install deps: `pip install -r requirements.txt`.  
3. Export `ENTSOE_API_KEY` in your shell.  
4. Run the API server: `python main.py` and open `http://localhost:5000/`.

**Notes & Caveats**
- If ENTSO-E or exchange-rate calls fail the code falls back to simple defaults.  
- PV forecasts rely on Open-Meteo responses and `pvlib` model assumptions for the configured site (Budapest coordinates by default).

If you want, I can also add a short example `curl` command for each endpoint or flesh out a usage / deployment section.
