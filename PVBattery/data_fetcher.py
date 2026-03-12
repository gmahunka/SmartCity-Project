import os
import requests
import pandas as pd
from entsoe import EntsoePandasClient
from dotenv import load_dotenv

load_dotenv()
API_TOKEN = os.environ.get("ENTSOE_API_KEY")
COUNTRY_CODE = "10YHU-MAVIR----U"


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


def get_real_entsoe_prices(start_date_str=None, end_date_str=None):
    client = EntsoePandasClient(api_key=API_TOKEN)

    if start_date_str is None:
        start = pd.Timestamp.now(tz='Europe/Budapest').normalize()
        start_date_str = start.strftime('%Y-%m-%d')
    else:
        start = pd.Timestamp(start_date_str, tz='Europe/Budapest')

    if end_date_str is None:
        end = start + pd.Timedelta(days=1)
        end_date_str = end.strftime('%Y-%m-%d')
    else:
        end = pd.Timestamp(end_date_str, tz='Europe/Budapest')
        if end <= start:
            end = start + pd.Timedelta(days=1)
            end_date_str = end.strftime('%Y-%m-%d')

    try:
        prices_series = client.query_day_ahead_prices(COUNTRY_CODE, start=start, end=end)
        if prices_series.empty:
            return [30] * 24

        df = pd.DataFrame(prices_series, columns=['EUR_MWh'])

        rates_series = get_eur_huf_rates(start_date_str, end_date_str)
        rates_series.index = pd.to_datetime(rates_series.index)
        full_dates = pd.date_range(start=start_date_str, end=end_date_str, freq='D')

        if rates_series.empty:
            rates_df = pd.DataFrame({'HUF': 410.0}, index=full_dates)
        else:
            rates_df = pd.DataFrame(
                index=pd.date_range(start=rates_series.index.min(), end=end_date_str, freq='D')
            )
            rates_df['HUF'] = rates_series
            rates_df['HUF'] = rates_df['HUF'].ffill().bfill()
            rates_df = rates_df.reindex(full_dates)
            rates_df['HUF'] = rates_df['HUF'].fillna(410.0)

        df['date'] = df.index.tz_convert('Europe/Budapest').normalize().tz_localize(None)
        df['HUF_rate'] = df['date'].map(rates_df['HUF'])
        df['HUF_kWh'] = (df['EUR_MWh'] * df['HUF_rate']) / 1000

        prices_in_huf = [round(price, 2) for price in df['HUF_kWh'].values]

        if len(prices_in_huf) < 24:
            prices_in_huf.extend([prices_in_huf[-1] if prices_in_huf else 30] * (24 - len(prices_in_huf)))
        return prices_in_huf[:24]

    except Exception as e:
        print(f"Hiba az API híváskor: {e}")
        return [30] * 24

def get_solar_forecast(target_date_str=None):
    lat = 47.50
    lon = 19.04
    dec = 35
    az = 0
    kwp = 5

    if target_date_str is None:
        target_date_str = pd.Timestamp.now().strftime('%Y-%m-%d')

    try:
        target_date = pd.to_datetime(target_date_str).strftime('%Y-%m-%d')
    except Exception:
        target_date = pd.Timestamp.now().strftime('%Y-%m-%d')

    url = f"https://api.forecast.solar/estimate/{lat}/{lon}/{dec}/{az}/{kwp}"

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        result = data.get('result', {}) if isinstance(data, dict) else {}
        watt_hours = result.get('watts', {}) if isinstance(result, dict) else {}
        if not isinstance(watt_hours, dict):
            raise ValueError("A Forecast.Solar válaszban a 'result.watts' nem szótár.")

        daily_values = {}
        for timestamp, watt in watt_hours.items():
            if not isinstance(timestamp, str):
                continue
            date_key = timestamp[:10]
            hour_part = timestamp[11:13]
            if len(hour_part) != 2 or not hour_part.isdigit():
                continue
            hour = int(hour_part)
            if not 0 <= hour <= 23:
                continue

            if date_key not in daily_values:
                daily_values[date_key] = [0.0] * 24

            try:
                daily_values[date_key][hour] = round(float(watt) / 1000, 2)
            except (TypeError, ValueError):
                daily_values[date_key][hour] = 0.0

        if target_date in daily_values:
            return daily_values[target_date]

        if daily_values:
            closest_date = sorted(daily_values.keys())[0]
            print(
                f"Figyelem: nincs PV előrejelzés erre a napra ({target_date}), "
                f"használt nap: {closest_date}"
            )
            return daily_values[closest_date]

        return [0.0] * 24

    except Exception as e:
        print(f"Hiba a napelem becslésnél: {e}")
        return [0.0] * 24