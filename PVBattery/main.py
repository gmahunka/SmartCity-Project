import pulp
import json
from datetime import datetime
from datetime import timedelta
from pathlib import Path

try:
    from .data_fetcher import get_eur_huf_rates, get_real_entsoe_prices, get_solar_forecast
    from .visualizer import plot_results, plot_results_base64
except ImportError:
    from data_fetcher import get_eur_huf_rates, get_real_entsoe_prices, get_solar_forecast
    from visualizer import plot_results, plot_results_base64


def get_last_soc_from_previous_day(start_date_str):
    """Fetch the last SOC from the previous day's data file."""
    try:
        import sqlite3
        prev_date = datetime.strptime(start_date_str, '%Y-%m-%d') - timedelta(days=1)
        prev_date_str = prev_date.strftime('%Y-%m-%d')
        data_dir = Path(__file__).parent.parent / "data"
        db_path = data_dir / "energy_data.db"
        if db_path.exists():
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT soc FROM hourly_data WHERE date = ? AND hour = 23", (prev_date_str,))
                row = cursor.fetchone()
                if row and row[0] is not None:
                    print(f"Using initial SOC {row[0]} from {prev_date_str} (last SOC of the day)")
                    return float(row[0])
    except Exception as e:
        print(f"Warning: Could not fetch previous SOC: {e}")
    return None


def run_battery_monitoring(start_date_str=None, end_date_str=None):
    if start_date_str is None:
        start_date_str = datetime.now().strftime('%Y-%m-%d')

    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
    except ValueError:
        start_date = datetime.now().date()
        start_date_str = start_date.strftime('%Y-%m-%d')

    if end_date_str is None:
        end_date = start_date + timedelta(days=1)
        end_date_str = end_date.strftime('%Y-%m-%d')
    else:
        try:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            end_date = start_date + timedelta(days=1)
            end_date_str = end_date.strftime('%Y-%m-%d')

    if end_date <= start_date:
        end_date = start_date + timedelta(days=1)
        end_date_str = end_date.strftime('%Y-%m-%d')

    RHD_DIJ = 25

    T = range(24)
    prices = get_real_entsoe_prices(start_date_str, end_date_str)
    prices_buy = [p + RHD_DIJ for p in prices]
    prices_sell = [p * 0.9 for p in prices_buy]
    eur_huf_rate = 410.0

    try:
        rates_series = get_eur_huf_rates()
        if not rates_series.empty:
            if start_date_str in rates_series.index:
                eur_huf_rate = float(rates_series[start_date_str])
            else:
                eur_huf_rate = float(rates_series.iloc[-1])
    except Exception:
        pass

    pv_gen = get_solar_forecast(start_date_str)
    load = [ 0.5, 0.4, 0.4, 0.4, 0.5, 1.2, 2.5, 3.0, 2.8, 2.5, 2.2, 
            2.0, 2.2, 2.1, 2.0, 2.2, 2.8, 3.5, 4.0, 3.5, 2.0, 1.2, 0.8, 0.6 ]

    
    model = pulp.LpProblem("Energy_Optimization", pulp.LpMinimize)

    p_chg = pulp.LpVariable.dicts("P_chg", T, lowBound=0, upBound=5)
    p_dis = pulp.LpVariable.dicts("P_dis", T, lowBound=0, upBound=5)
    p_grid_buy = pulp.LpVariable.dicts("P_buy", T, lowBound=0)
    p_grid_sell = pulp.LpVariable.dicts("P_sell", T, lowBound=0)
    soc = pulp.LpVariable.dicts("SOC", T, lowBound=2, upBound=10)

    eff = 0.95
    initial_soc = get_last_soc_from_previous_day(start_date_str)
    if initial_soc is None:
        initial_soc = 5
        print("No previous SOC found, defaulting to 5")

    c_deg = 1

    future_value_estimate = (sum(prices_buy) / len(prices_buy))

    model += pulp.lpSum([
        p_grid_buy[t] * prices_buy[t] -
        p_grid_sell[t] * prices_sell[t] +
        (p_chg[t] + p_dis[t]) * c_deg
        for t in T] - (soc[23] * future_value_estimate))

    for t in T:
        model += (pv_gen[t] + p_dis[t] + p_grid_buy[t] == load[t] + p_chg[t] + p_grid_sell[t])
        if t == 0:
            model += soc[t] == initial_soc + (p_chg[t] * eff) - (p_dis[t] / eff)
        else:
            model += soc[t] == soc[t - 1] + (p_chg[t] * eff) - (p_dis[t] / eff)

    model.solve(pulp.PULP_CBC_CMD(msg=0))

    soc_list = [float(soc[t].varValue or 0.0) for t in T]
    battery_list = [float((p_chg[t].varValue or 0.0) - (p_dis[t].varValue or 0.0)) for t in T]
    grid_list = [float((p_grid_buy[t].varValue or 0.0) - (p_grid_sell[t].varValue or 0.0)) for t in T]

    total_cost_with_smart_system = float((pulp.value(model.objective) + (pulp.value(soc[23]) * future_value_estimate)) or 0.0)
    cost_without_battery = 0.0
    for t in T:
        net_flow = load[t] - pv_gen[t]
        if net_flow > 0:
            cost_without_battery += net_flow * (prices[t] + RHD_DIJ)
        else:
            cost_without_battery += net_flow * (prices[t] * 0.9)

    saving = cost_without_battery - total_cost_with_smart_system
    pure_grid_cost = sum(load[t] * (prices_buy[t]) for t in T)
    total_saving_vs_grid = pure_grid_cost - total_cost_with_smart_system


    plot_b64 = plot_results_base64(T, prices_buy, pv_gen, load, soc_list, battery_list, grid_list)
    hourly = [
        {
            'hour': t,
            'price_huf_kwh': round(prices_buy[t], 3),
            'pv_kw': round(pv_gen[t], 3),
            'load_kw': round(load[t], 3),
            'battery_kw': round(battery_list[t], 3),
            'soc_kwh': round(soc_list[t], 3),
            'grid_kw': round(grid_list[t], 3),
        }
        for t in T
    ]

    return {
        'status': pulp.LpStatus[model.status],
        'start_date': start_date_str,
        'end_date': end_date_str,
        'plot_image_base64': plot_b64,
        'stats': {
            'smart_cost_huf': float(round(total_cost_with_smart_system, 2)),
            'no_battery_cost_huf': float(round(cost_without_battery, 2)),
            'pure_grid_cost_huf': float(round(pure_grid_cost, 2)),
            'total_saving_vs_grid_huf': float(round(total_saving_vs_grid, 2)),
            'saving_huf': float(round(saving, 2)),
            'eur_huf_rate': float(round(eur_huf_rate, 2)),
            'avg_price_huf_kwh': float(round(sum(prices_buy) / len(prices_buy), 2)),
            'total_load_kwh': float(round(sum(load), 2)),
            'total_pv_kwh': float(round(sum(pv_gen), 2)),
        },
        'hourly': hourly,
    }


if __name__ == '__main__':
    result = run_battery_monitoring()

    T = range(24)
    prices = [item['price_huf_kwh'] for item in result['hourly']]
    pv = [item['pv_kw'] for item in result['hourly']]
    load = [item['load_kw'] for item in result['hourly']]
    soc_values = [item['soc_kwh'] for item in result['hourly']]
    battery = [item['battery_kw'] for item in result['hourly']]
    grid = [item['grid_kw'] for item in result['hourly']]
    plot_results(T, prices, pv, load, soc_values, battery, grid)