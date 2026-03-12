import os
import requests
import pandas as pd
from entsoe import EntsoePandasClient
from dotenv import load_dotenv

load_dotenv()
API_TOKEN = os.environ.get("ENTSOE_API_KEY")

def get_real_entsoe_prices():
    client = EntsoePandasClient(api_key=API_TOKEN)

    # A mai nap lekérése
    start = pd.Timestamp.now(tz='Europe/Budapest').normalize()
    end = start + pd.Timedelta(days=1)

    try:
        # Adatlekérés
        prices_series = client.query_day_ahead_prices('HU', start=start, end=end)
        
        # Átváltás: Az ENTSO-E EUR/MWh-ban adja meg. 
        # Nekünk Ft/kWh kell: (EUR * 400 Ft) / 1000 = Ft/kWh
        prices_in_huf = [round((price * 400) / 1000, 2) for price in prices_series.values]
        
        # Biztosítsuk, hogy pontosan 24 értékünk van
        return prices_in_huf[:24]

    except Exception as e:
        print(f"Hiba az API híváskor: {e}")
        # Ha hiba van, adjunk vissza egy alapértelmezett listát, hogy ne omoljon össze a program
        return [30] * 24

def get_solar_forecast():
    # Paraméterek (ezeket írd át a sajátodra!)
    lat = 47.49   # Szélességi fok (Budapest)
    lon = 19.04   # Hosszúsági fok (Budapest)
    dec = 35      # Dőlésszög (fokban)
    az = 0        # Tájolás (0=Dél, -90=Kelet, 90=Nyugat)
    kwp = 5       # A napelemes rendszer csúcsteljesítménye (kWp)

    url = f"https://api.forecast.solar/estimate/{lat}/{lon}/{dec}/{az}/{kwp}"
    
    try:
        response = requests.get(url)
        data = response.json()
        
        # A Forecast.Solar óránkénti Watt adatokat ad vissza egy szótárban
        # Ebből nekünk kW kell a mai napra
        watt_hours = data['result']['watts']
        
        # Keressük ki a mai nap dátumát
        today = pd.Timestamp.now().strftime('%Y-%m-%d')
        
        solar_list = []
        for hour in range(24):
            # Az API "YYYY-MM-DD HH:00:00" formátumban adja az időpontokat
            time_key = f"{today} {hour:02d}:00:00"
            # Ha nincs adat az adott órára (pl. éjjel), legyen 0
            watt = watt_hours.get(time_key, 0)
            solar_list.append(round(watt / 1000, 2)) # Watt -> kW
            
        return solar_list

    except Exception as e:
        print(f"Hiba a napelem becslésnél: {e}")
        return [0] * 24 # Hiba esetén nulla termelés