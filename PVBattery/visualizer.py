import matplotlib.pyplot as plt

def plot_results(T, prices, pv_gen, load, soc_values, battery_move, grid_values):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10), sharex=True)

    # 1. GRAFIKON: Ár és SOC
    color = 'tab:red'
    ax1.set_ylabel('Ár (Ft/kWh)', color=color)
    ax1.plot(T, prices, color=color, marker='o', label='Piaci ár')
    ax1.tick_params(axis='y', labelcolor=color)
    ax1.grid(True, alpha=0.3)

    ax1_2 = ax1.twinx()
    color = 'tab:blue'
    ax1_2.set_ylabel('Akku töltöttség (SOC - kWh)', color=color)
    ax1_2.fill_between(T, soc_values, color=color, alpha=0.2, label='SOC')
    ax1_2.plot(T, soc_values, color=color, linewidth=2)
    ax1_2.set_ylim(0, 11)
    ax1_2.tick_params(axis='y', labelcolor=color)
    ax1.set_title('Áramár és Akkumulátor állapota')

    # 2. GRAFIKON: Energiaáramlás
    ax2.plot(T, pv_gen, color='gold', label='PV termelés (kW)', linewidth=2, alpha=0.8)
    ax2.plot(T, load, color='black', linestyle='--', label='Fogyasztás (kW)', alpha=0.7)
    
    # Akku mozgás (zöld oszlopok)
    ax2.bar(T, battery_move, color='green', alpha=0.4, label='Akku töltés/kisütés (kW)')
    
    # ÚJ: Hálózati mérleg (kék szaggatott vagy vékonyabb vonal/oszlop)
    # Én egy átlátszó kék oszlopot vagy vonalat javaslok, hogy ne legyen túl zsúfolt:
    ax2.step(T, grid_values, where='mid', color='blue', label='Hálózati vétel/eladás (kW)', linewidth=2)
    ax2.fill_between(T, grid_values, step="mid", alpha=0.1, color='blue')

    ax2.axhline(0, color='black', linewidth=0.8)
    ax2.set_ylabel('Teljesítmény (kW)')
    ax2.set_xlabel('Óra')
    ax2.legend(loc='upper left', fontsize='small', ncol=2) # Két oszlopos legenda, hogy elférjen
    ax2.grid(True, alpha=0.3)
    ax2.set_title('Napi energia-egyensúly és Hálózati forgalom')

    plt.tight_layout()
    plt.show()