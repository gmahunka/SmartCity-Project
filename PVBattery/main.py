import pulp

from data_fetcher import get_real_entsoe_prices, get_solar_forecast
from visualizer import plot_results

# --- ADATOK ---
T = range(24)
prices_buy = get_real_entsoe_prices()
# Eladási ár: tegyük fel, hogy a piaci ár 90%-a
prices_sell = [p * 0.9 for p in prices_buy] 

pv_gen = pv_gen = get_solar_forecast()
# A fogyasztói profil még ideiglenes
load = [0.4, 0.3, 0.3, 0.3, 0.4, 0.8, 1.5, 2.0, 1.2, 0.8, 0.7, 0.7, 0.8, 0.7, 0.7, 0.8, 1.2, 2.5, 3.0, 2.8, 1.5, 1.0, 0.6, 0.5]

# --- MODELL ---
model = pulp.LpProblem("Energy_Optimization", pulp.LpMinimize)

# --- VÁLTOZÓK ---
p_chg = pulp.LpVariable.dicts("P_chg", T, lowBound=0, upBound=5)      # Max 5kW töltés
p_dis = pulp.LpVariable.dicts("P_dis", T, lowBound=0, upBound=5)      # Max 5kW kisütés
p_grid_buy = pulp.LpVariable.dicts("P_buy", T, lowBound=0)
p_grid_sell = pulp.LpVariable.dicts("P_sell", T, lowBound=0)
soc = pulp.LpVariable.dicts("SOC", T, lowBound=2, upBound=10)        # 2kWh min, 10kWh max

# --- PARAMÉTEREK ---
eff = 0.95 
initial_soc = 5 # Kezdjünk 5 kWh-val
c_deg = 2 # Akku kopási költség (Ft/kWh)

# --- CÉLFÜGGVÉNY (Költség minimalizálás) ---
# Költség = (Vétel * Ár) - (Eladás * Ár) + (Akku használat * Kopás)
model += pulp.lpSum([
    p_grid_buy[t] * prices_buy[t] - 
    p_grid_sell[t] * prices_sell[t] + 
    (p_chg[t] + p_dis[t]) * c_deg 
    for t in T
])

# --- KORLÁTOK ---
for t in T:
    # 1. Energia-egyensúly: Ami bejön, annak el kell mennie
    # PV + AkkuKisütés + HálózatiVétel = Fogyasztás + AkkuTöltés + HálózatiEladás
    model += (pv_gen[t] + p_dis[t] + p_grid_buy[t] == load[t] + p_chg[t] + p_grid_sell[t])
    
    # 2. SOC (Töltöttség) kiszámítása
    if t == 0:
        model += soc[t] == initial_soc + (p_chg[t] * eff) - (p_dis[t] / eff)
    else:
        model += soc[t] == soc[t-1] + (p_chg[t] * eff) - (p_dis[t] / eff)

# --- MEGOLDÁS ---
model.solve(pulp.PULP_CBC_CMD(msg=0)) # msg=0 kikapcsolja a solver naplózást

# --- EREDMÉNYEK ---
print(f"Státusz: {pulp.LpStatus[model.status]}")
print(f"{'Óra':<5} | {'Ár':<5} | {'PV':<5} | {'Load':<5} | {'Akku':<8} | {'SOC':<5} | {'Grid'}")
print("-" * 60)
for t in T:
    net_battery = p_chg[t].varValue - p_dis[t].varValue
    net_grid = p_grid_buy[t].varValue - p_grid_sell[t].varValue
    print(f"{t:<5} | {prices_buy[t]:<5} | {pv_gen[t]:<5} | {load[t]:<5} | {net_battery:>7.2f} | {soc[t].varValue:>5.2f} | {net_grid:>5.2f}")

# --- PÉNZÜGYI ÖSSZESÍTÉS ---
total_cost_with_smart_system = pulp.value(model.objective)

# Mi lett volna az akkumulátor nélkül?
# Ekkor a ház vagy a PV-t használja, vagy a hálózatot (vétel/eladás)
cost_without_battery = 0
for t in T:
    net_flow = load[t] - pv_gen[t]
    if net_flow > 0: # Venni kell a hálózatból
        cost_without_battery += net_flow * prices_buy[t]
    else: # Eladjuk a felesleget
        cost_without_battery += net_flow * prices_buy[t] * 0.9 # 0.9 az eladási szorzó

saving = cost_without_battery - total_cost_with_smart_system

print("\n" + "="*30)
print(f"Napi mérleg összesítve:")
print(f"Költség okos rendszerrel:  {total_cost_with_smart_system:>8.2f} Ft")
print(f"Költség akkumulátor nélkül: {cost_without_battery:>8.2f} Ft")
print("-" * 30)
print(f"Napi megtakarítás:         {saving:>8.2f} Ft")
print("="*30)

# --- EREDMÉNYEK ÖSSZEGYŰJTÉSE ---
# Kiolvassuk a PuLP változókból a számokat listákba
soc_list = [soc[t].varValue for t in T]
battery_list = [p_chg[t].varValue - p_dis[t].varValue for t in T]
grid_list = [p_grid_buy[t].varValue - p_grid_sell[t].varValue for t in T]

# --- VIZUALIZÁCIÓ MEGHÍVÁSA ---
plot_results(T, prices_buy, pv_gen, load, soc_list, battery_list, grid_list)