import os
import time
import requests
import pandas as pd
from entsoe import EntsoePandasClient
from dotenv import load_dotenv

import pvlib
from pvlib.pvsystem import PVSystem
from pvlib.location import Location
from pvlib.modelchain import ModelChain
from pvlib.temperature import TEMPERATURE_MODEL_PARAMETERS

load_dotenv()
API_TOKEN = os.environ.get("ENTSOE_API_KEY")
COUNTRY_CODE = "10YHU-MAVIR----U"
FRANKFURTER_LATEST_URL = "https://api.frankfurter.dev/v1/latest?from=EUR&to=HUF"


def _extract_frankfurter_payload(data):
    if isinstance(data, dict):
        return data

    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                return item

    return None


def get_eur_huf_rates():
    retry_delays = [0, 1, 2]
    last_error = None

    for delay in retry_delays:
        if delay:
            time.sleep(delay)

        try:
            response = requests.get(FRANKFURTER_LATEST_URL, timeout=10)
            response.raise_for_status()
            data = _extract_frankfurter_payload(response.json())

            if data is None:
                last_error = "Unexpected Frankfurter payload type"
                continue

            rates = data.get('rates') or {}
            rate = rates.get('HUF') if isinstance(rates, dict) else None
            date = data.get('date')

            if rate is not None and date:
                return pd.Series({date: rate})

            last_error = "Missing 'HUF' rate or 'date' in response"
        except Exception as exc:
            print(f"Attempt failed: {exc}")

    print(f"Warning: Failed to fetch exchange rates after retries: {last_error}")

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
        
        prices_series.index = prices_series.index.tz_convert('Europe/Budapest')

        prices_series = prices_series.resample('h').mean()

        prices_series = prices_series.iloc[:24]

        df = pd.DataFrame(prices_series, columns=['EUR_MWh'])

        rates_series = get_eur_huf_rates()
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
    # 1. Rendszer paraméterek (Budapest)
    lat = 47.50
    lon = 19.04
    tilt = 35
    # FIGYELEM: A pvlib-ben az Észak = 0, Kelet = 90, Dél = 180. 
    # A korábbi API-nál a 0 jelentette a Délt, itt át kell írni 180-ra!
    azimuth = 180 
    kwp = 5.0

    if target_date_str is None:
        target_date_str = pd.Timestamp.now(tz='Europe/Budapest').strftime('%Y-%m-%d')

    # 2. Open-Meteo API lekérés az adott napra
    # Lekérjük a hőmérsékletet, szelet, és a 3 legfontosabb sugárzási adatot (GHI, DNI, DHI)
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}&"
        f"hourly=temperature_2m,wind_speed_10m,shortwave_radiation,direct_normal_irradiance,diffuse_radiation&"
        f"timezone=Europe%2FBudapest&"
        f"start_date={target_date_str}&end_date={target_date_str}"
    )

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        # 3. Adatok DataFrame-be rendezése a pvlib számára
        times = pd.to_datetime(data['hourly']['time']).tz_localize('Europe/Budapest')
        weather_df = pd.DataFrame({
            'ghi': data['hourly']['shortwave_radiation'],          # Globális vízszintes besugárzás
            'dni': data['hourly']['direct_normal_irradiance'],     # Direkt normál besugárzás
            'dhi': data['hourly']['diffuse_radiation'],            # Diffúz besugárzás
            'temp_air': data['hourly']['temperature_2m'],
            'wind_speed': data['hourly']['wind_speed_10m']
        }, index=times)

        # 4. PVLIB Rendszer és Helyszín definíció (PVWatts modell alapján)
        site_location = Location(lat, lon, tz='Europe/Budapest')
        
        system = PVSystem(
            surface_tilt=tilt,
            surface_azimuth=azimuth,
            # pdc0: DC kapacitás Wattban, gamma_pdc: hőmérsékleti együttható (%/°C)
            module_parameters={'pdc0': kwp * 1000, 'gamma_pdc': -0.004},
            # Egyszerű inverter definíció 96%-os hatásfokkal
            inverter_parameters={'pdc0': kwp * 1000 * 1.1, 'eta_inv_nom': 0.96},
            temperature_model_parameters=TEMPERATURE_MODEL_PARAMETERS['sapm']['open_rack_glass_glass']
        )
        
        # Futtatókörnyezet (ModelChain) összeállítása
        mc = ModelChain(system, site_location, aoi_model='physical', spectral_model='no_loss')

        # 5. Szimuláció futtatása az időjárási adatokon
        mc.run_model(weather_df)

        # 6. Eredmények kinyerése (AC teljesítmény Wattból átváltva kW-ba)
        ac_power_kw = mc.results.ac / 1000.0
        
        # Éjszaka a pvlib minimális negatív értékeket (inverter fogyasztás) adhat, ezt nullázzuk
        ac_power_kw = ac_power_kw.clip(lower=0)

        # 24 órás listává alakítás
        daily_values = [round(float(val), 2) for val in ac_power_kw.values]

        # Biztonsági ellenőrzés, ha valamiért nem 24 órát adna vissza az API
        if len(daily_values) < 24:
            daily_values.extend([0.0] * (24 - len(daily_values)))

        return daily_values[:24]

    except Exception as e:
        print(f"Hiba az Open-Meteo / PVLIB számításnál: {e}")
        return [0.0] * 24