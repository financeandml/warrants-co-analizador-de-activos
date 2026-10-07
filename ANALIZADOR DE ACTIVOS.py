#ANALIZADOR DE ACTIVOS#

#DESCARGAR LIBRERIAS

import seaborn
import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.stats import norm



# 1. Configurar el ticker
ticker_symbol = "ICHR"
ichor = yf.Ticker(ticker_symbol)

# 2. Descargar precios históricos de los años que consideremos (en este caso 5y)
df_ichr = ichor.history(period="5y", auto_adjust=True)

# 3. Mantener solo la columna "Close" para coger el análisis con los precios de cierres del día anterior
df_ichr = df_ichr[["Close"]].copy()

# 4. Crear columna de retornos diarios
df_ichr["Return"] = df_ichr["Close"].pct_change()

# 5. Eliminar el primer valor nulo
df_ichr = df_ichr.dropna()

# Mostrar primeras filas (terminal)
print(df_ichr.head())

# 6. Cálculo de retorno medio y volatilidad
# Desviación estándar- medida de la volatilidad de los retornos diarios
mean_return = np.mean(df_ichr["Return"])
std_return = np.std(df_ichr["Return"])

print(f"Retorno Medio diario: {mean_return: .5f}")
print(f"Desviación estándar diaria: {std_return:.5f}")

# 7. Gráfico de precios con cierre ajustado

plt.figure(figsize=(12,5))
plt.plot(df_ichr["Close"])
plt.title("Precio de Cierre Ajustado de Ichor Holdings")
plt.xlabel("Fecha")
plt.ylabel("Precio (USD)")
plt.grid(True)
plt.show()


#_______________________________________________________________________

#RETORNOS DIARIOS Buscamos la variabilidad relativa, no el valor absoluto
# 1. Definir el objeto Ticker correctamente
ichr_ticker = yf.Ticker("ICHR")

# 2. Descargar datos usando el objeto Ticker (no el DataFrame)
df_ichr = ichr_ticker.history(period="5y", auto_adjust=True)

# 3. Procesar datos
df_ichr = df_ichr[["Close"]].copy()
df_ichr["Return"] = df_ichr["Close"].pct_change()
df_ichr = df_ichr.dropna()

# 4. Graficar
plt.figure(figsize=(12,5))
plt.plot(df_ichr["Return"])
plt.title("Retornos diarios de Ichor Holdings (ICHR)")
plt.xlabel("Fecha")
plt.ylabel("Retorno diario")
plt.grid(True)
plt.show()


#DISTRIBUCIÓN DE RETORNOS DIARIOS
plt.figure(figsize=(10,4))
plt.hist(df_ichr["Return"], bins=75, density=False)
plt.title("Distribución de Retornos Diarios de Ichor Holdings (ICHR)")
plt.xlabel("Retorno diario")
plt.ylabel ("Frecuencia")
plt.grid(True)
plt.show()




#________________________________________________________________________
#Meter correlación entre activos (S&P500 y Dow Jones como ejemplo)
# Copia de documento 00 drive
#_________________________________________________________________________
#Retornos logarítmicos
df_ichr["LogReturn"] = np.log(df_ichr["Close"] / df_ichr["Close"].shift(1))
df_ichr = df_ichr.dropna()
df_ichr.head()
plt.figure(figsize=(12, 8))
plt.plot(df_ichr["Close"])
plt.title("Precio de cierre ajustado Ichor")
plt.xlabel("Fecha")
plt.ylabel("Precio")
plt.grid(True)
plt.show()



plt.figure(figsize=(12, 8))
plt.plot(df_ichr["Return"], label="Simple Return")
plt.plot(df_ichr["LogReturn"], label="Log Return")
plt.title("Retornos diarios de Ichor")
plt.xlabel("Fecha")
plt.ylabel("Retorno")
plt.legend()
plt.grid(True)
plt.show()


#Volatilidad histórica anualizada en ventanas de 21 días (aproximadamente un mes)
df_ichr["Volatility"] = df_ichr["LogReturn"].rolling(window=21).std() * np.sqrt(252) #anualizada
#Multiplicamos por 252 días, asumiendo 252 días de operativa de trading anual. Es un dato "estándar"
plt.figure(figsize=(12, 8))
plt.plot(df_ichr["Volatility"])
plt.title("Volatilidad histórica anualizada 21 días")
plt.xlabel("Fecha")
plt.ylabel("Volatilidad")
plt.grid(True)
plt.show()

#_______________________________--- 
#RESUMEN ESTADÍSTICO DE RETORNOS
summary = df_ichr[["Return","LogReturn", "Volatility"]].describe()
summary


#_________________________________________________________________________________________________________________
#  MONTE CARLO SIMULACIÓN DE PRECIOS FUTUROS

# Descargar datos históricos para ICHOR (ticker 'ICHR')
ticker = 'ICHR'
data = yf.download(ticker, start='2021-01-01', end='2026-08-03') # Ajusta el rango de fechas según necesites

# Calcular S0 (precio inicial) y sigma (volatilidad) de los datos históricos
S0 = data['Close'].iloc[-1].item() # Último precio de cierre como precio inicial, convertido a escalar
log_returns = np.log(data['Close'] / data['Close'].shift(1))
daily_volatility = log_returns.std()
sigma = daily_volatility * np.sqrt(252) # Volatilidad anualizada (252 días de trading)
sigma = sigma.item() # Convertir sigma de Series a escalar

r = 0.05          # Tasa libre de riesgo (5% - puedes ajustarla)
T = 1.0           # Tiempo en años (1 año)
pasos = 252       # Pasos temporales (días bursátiles en un año)
n_sim = 10000     # Número de trayectorias (10,000 futuros)

dt = T / pasos    # Tamaño del paso temporal

# 2 GENERACIÓN DE CHOQUES ALEATORIOS (Z)
# Creamos una matriz de 252 días x 10,000 simulaciones
Z = np.random.standard_normal((pasos, n_sim))

# 3 CONSTRUCCIÓN DE TRAYECTORIAS
# Calculamos el retorno diario para cada celda
retornos_diarios = np.exp((r - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * Z)

# Creamos la matriz de precios empezando por S0
precios = np.zeros((pasos + 1, n_sim))
precios[0] = S0

# Aplicamos el producto acumulado para obtener la evolución del precio
precios[1:] = S0 * np.cumprod(retornos_diarios, axis=0)

# 4. VISUALIZACIÓN
plt.figure(figsize=(10,6))
plt.plot(precios[:, :100], color='royalblue', alpha=0.1) # Graficamos solo las primeras 100 para no saturar

plt.title(f"Simulación Monte Carlo para {ticker}: {n_sim} Trayectorias")
plt.xlabel("Días")
plt.ylabel("Precio del Activo")
plt.grid(True)
plt.show()

# 5. ANÁLISIS DE LA DISTRIBUCIÓN FINAL
plt.figure(figsize=(12,6))
plt.hist(precios[-1], bins=250, color='skyblue', edgecolor='black')
plt.title(f"Distribución de Precios al Vencimiento (T) para {ticker}")
plt.xlabel("Precio Final")
plt.ylabel("Frecuencia")
plt.show()

# 6. CÁLCULO DE MÉTRICAS CLAVE
precio_final_promedio = np.mean(precios[-1])
valor_teorico = S0 * np.exp(r * T)
error_estandar = np.std(precios[-1]) / np.sqrt(n_sim)

print(f"--- RESULTADOS DE LA SIMULACIÓN ---")
print(f"Precio promedio final (Simulado): {precio_final_promedio:.2f}")
print(f"Precio teórico (Fórmula):         {valor_teorico:.2f}")
print(f"Error Estándar de la simulación:  {error_estandar:.4f}")

# 7. VISUALIZACIÓN DE LA CONVERGENCIA
# Veamos cómo cambia el promedio a medida que añadimos simulaciones
convergencia = np.cumsum(precios[-1]) / np.arange(1, n_sim + 1)

plt.figure(figsize=(10,5))
plt.plot(convergencia)
plt.axhline(valor_teorico, color='r', linestyle='--', label='Valor Teórico')
plt.title("Análisis de Convergencia de Monte Carlo")
plt.xlabel("Número de Simulaciones")
plt.ylabel("Precio Promedio")
plt.legend()
plt.show()

#_____________________________________________________________________________________________________________
z_score_95 = 1.96 # Z-score para un intervalo de confianza del 95%
z_score_99 = 2.576 # Z-score para un intervalo de confianza del 99%

# Calcular el margen de error para 99%
margen_de_error_99 = z_score_99 * error_estandar

# Calcular el intervalo de confianza para 99%
intervalo_inferior_99 = precio_final_promedio - margen_de_error_99
intervalo_superior_99 = precio_final_promedio + margen_de_error_99

print(f"Intervalo de Confianza del 99% para el Precio Final Simulado:")
print(f"  [{intervalo_inferior_99:.2f}, {intervalo_superior_99:.2f}]")
print(f"Esto significa que, con un 99% de confianza, el precio real al vencimiento caerá dentro de este rango.")


#____________________________________________________________________________________________________________


#VAR / CVAR
# 1. Descarga de datos
ticker = "ICHR"
# Añadimos auto_adjust=True para que 'Close' sea el precio ajustado
# Añadimos multi_level_index=False para evitar el error de acceso a columnas
data = yf.download(ticker, start="2021-01-01", end="2026-08-04", auto_adjust=True, multi_level_index=False)

# Verificamos que se descargaron datos
if data.empty:
    print("Error: No se descargaron datos. Revisa tu conexión o el ticker.")
else:
    # Usamos 'Close' (que ya viene ajustado por auto_adjust=True)
    prices = data['Close']

# 2. Cálculo de Retornos Logarítmicos
# Usamos np.log y la función .shift(1)
returns = np.log(prices / prices.shift(1)).dropna()

print(f"Datos cargados correctamente: {len(returns)} días de trading para {ticker}")
print(returns.head()) # Mostramos los primeros 5 retornos


def calcular_metricas_riesgo(returns, confianza=0.95):
    """
    Calcula el VaR Histórico, Paramétrico y el CVaR en un solo paso.

    Parámetros:
    returns (Series): Retornos logarítmicos del activo.
    confianza (float): Nivel de confianza (0.95 o 0.99).
    """

    # --- 1. VaR Histórico ---
    # Simplemente buscamos el percentil (1 - confianza) en los datos reales
    var_h = np.percentile(returns, (1 - confianza) * 100)

    # --- 2. VaR Paramétrico (Normal) ---
    # Asumimos que los retornos siguen una campana de Gauss
    mu = returns.mean()
    sigma = returns.std()
    z_score = norm.ppf(1 - confianza)
    var_p = mu + (z_score * sigma)

    # --- 3. CVaR (Expected Shortfall) ---
    # Promedio de los retornos que fueron peores que el VaR Histórico
    peores_retornos = returns[returns <= var_h]
    cvar = peores_retornos.mean()

    return var_h, var_p, cvar

# Ejecución del cálculo para un nivel de confianza del 99% (Estándar institucional)
conf = 0.99
v_hist, v_para, cv = calcular_metricas_riesgo(returns, confianza=conf)

print(f"--- Reporte de Riesgo para {ticker} ---")
print(f"Confianza: {conf*100}%")
print(f"VaR Histórico:   {v_hist:.2%}")
print(f"VaR Paramétrico: {v_para:.2%}")
print(f"CVaR (Pérdida en desastre): {cv:.2%}")

#Análisis de la Gráfica 
plt.figure(figsize=(12, 6))

# Dibujamos el histograma de retornos
n, bins, patches = plt.hist(returns, bins=250, alpha=0.4, color='blue', label='Retornos Diarios')

# Sombreamos la zona de pérdida extrema (peor 1% o 5%)
for i in range(len(patches)):
    if bins[i] < v_hist:
        patches[i].set_facecolor('red')
        patches[i].set_alpha(0.6)

# Añadimos las líneas de las métricas
plt.axvline(v_hist, color='orange', linestyle='--', linewidth=2, label=f'VaR Histórico ({v_hist:.2%})')
plt.axvline(cv, color='darkred', linestyle='-', linewidth=2, label=f'CVaR ({cv:.2%})')

plt.title(f"Distribución de Retornos y Escenarios de Riesgo ({ticker})", fontsize=14)
plt.xlabel("Retorno Diario")
plt.ylabel("Frecuencia")
plt.legend()
plt.grid(alpha=0.2)
plt.show()





#______________________________________________________________________________________________________________
# Calcular retornos acumulados
cum_rets = (1 + returns).cumprod()

# Calcular Drawdowns (Caídas desde el máximo)
picos = cum_rets.cummax()
drawdowns = (cum_rets - picos) / picos

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10), sharex=True)

# Panel Superior: Crecimiento de $1000
cum_rets.plot(ax=ax1, color=["blue", "orange"])
ax1.set_title("Crecimiento de una Inversión de $1000", fontsize=14)
ax1.set_ylabel("Valor de la Inversión")
ax1.grid(alpha=0.3)

# Panel Inferior: El "Dolor" (Drawdowns)
drawdowns.plot(ax=ax2, kind='area', stacked=False, alpha=0.3, color=["blue", "orange"])
ax2.set_title("Drawdowns (Caídas desde máximos)", fontsize=14)
ax2.set_ylabel("Porcentaje de Caída")
ax2.grid(alpha=0.3)

plt.tight_layout()
plt.show()






#Sheet interactive
# Optional interactive/visual imports. Import at runtime so lint/analysis
# won't mark them unresolved when not installed in the environment.

try:
    import ipywidgets as widgets
except Exception:  # pragma: no cover - optional dependency
    widgets = None

try:
    import seaborn as sns
except Exception:  # pragma: no cover - optional dependency
    sns = None

def simulador_riesgo_interactivo(ticker, confianza, inversion):
    # 1. Descarga rápida de datos
    df_inter = yf.download(ticker, start="2021-01-01", auto_adjust=True, multi_level_index=False, progress=False)['Close']
    rets_inter = np.log(df_inter / df_inter.shift(1)).dropna()

    # 2. Cálculos de métricas
    # 'vp' not used below in this function; unpack to '_' to avoid unused-var warnings
    vh, _, cv = calcular_metricas_riesgo(rets_inter, confianza / 100)

    # 3. Impacto en Capital
    pérdida_var = inversion * vh
    pérdida_cvar = inversion * cv

    # 4. Visualización
    plt.figure(figsize=(12, 5))
    sns.histplot(rets_inter, bins=150, kde=True, color='BLACK', alpha=0.3)

    plt.axvline(vh, color='blue', lw=3, label=f'VaR {confianza}%: {vh:.2%}')
    plt.axvline(cv, color='red', lw=3, label=f'CVaR {confianza}%: {cv:.2%}')

    plt.title(f"Simulación de Riesgo: {ticker} | Capital en Riesgo: ${abs(pérdida_var):,.0f}", fontsize=15)
    plt.xlabel("Retorno Diario")
    plt.legend()
    plt.show()

    print(f"--- ANÁLISIS DE IMPACTO ---")
    print(f"Con una inversión de ${inversion:,.0f}:")
    print(f"En un día malo (VaR), podrías perder: ${abs(pérdida_var):,.2f}")
    print(f"En un día catastrófico (CVaR), la pérdida media sería: ${abs(pérdida_cvar):,.2f}")

# Creación de los controles
widgets.interact(
    simulador_riesgo_interactivo,
    ticker=['SPY', 'QQQ', 'BTC-USD', 'ETH-USD', 'TSLA', 'GOLD', 'ICHR'],
    confianza=widgets.FloatSlider(min=90, max=99.9, step=0.1, value=95, description='Confianza %'),
    inversion=widgets.IntSlider(min=100, max=100000, step=10000, value=100000, description='Inversión $')
);





#__________________________________________________________________________________________
def analizar_performance_profesional(precios, rf_anual=0.02):
    """
    Calcula métricas clave de rendimiento ajustado al riesgo.
    """
    # 1. Retornos diarios y acumulados
    rets = np.log(precios / precios.shift(1)).dropna()
    cum_rets = np.exp(rets.cumsum()) # Curva de equidad (base 1)

    # 2. Anualización de Retorno y Volatilidad
    # Usamos 252 como el número estándar de días de trading al año
    ret_anual = rets.mean() * 252
    vol_anual = rets.std() * np.sqrt(252)

    # 3. Sharpe Ratio
    sharpe = (ret_anual - rf_anual) / vol_anual

    # 4. Sortino Ratio (Volatilidad negativa)
    rets_negativos = rets[rets < 0]
    vol_downside = rets_negativos.std() * np.sqrt(252)
    sortino = (ret_anual - rf_anual) / vol_downside

    # 5. Maximum Drawdown (MDD)
    # Calculamos la caída desde el pico histórico en cada momento
    picos = cum_rets.cummax()
    drawdowns = (cum_rets - picos) / picos
    max_drawdown = drawdowns.min()

    # 6. Ratio de Calmar (Retorno / Max Drawdown)
    # Esencial para Hedge Funds: ¿Cuánto gano por cada unidad de caída máxima?
    calmar = ret_anual / abs(max_drawdown)

    return {
        "Retorno Anualizado": ret_anual,
        "Volatilidad Anual": vol_anual,
        "Sharpe Ratio": sharpe,
        "Sortino Ratio": sortino,
        "Max Drawdown": max_drawdown,
        "Ratio de Calmar": calmar,
        "Series_Drawdown": drawdowns,
        "Equity_Curve": cum_rets
    }

# --- EJECUCIÓN DEL CASO REAL ---
ticker_test = "QQQ"
datos = yf.download(ticker_test, start="2018-01-01", auto_adjust=True, multi_level_index=False)['Close']

metrics = analizar_performance_profesional(datos)

# Imprimir resultados formateados
print(f"--- DASHBOARD DE PERFORMANCE: {ticker_test} ---")
for k, v in metrics.items():
    if isinstance(v, float):
        print(f"{k}: {v:.4f}" if "Ratio" in k else f"{k}: {v:.2%}")
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10), sharex=True, gridspec_kw={'height_ratios': [2, 1]})

# Gráfico 1: Curva de Equidad
ax1.plot(metrics["Equity_Curve"], color='navy', lw=2)
ax1.set_title(f"Crecimiento de la Inversión (Base 1.0) - {ticker_test}", fontsize=14)
ax1.set_ylabel("Valor de la Cartera")
ax1.grid(alpha=0.3)

# Gráfico 2: Underwater Chart (Drawdown)
ax2.fill_between(metrics["Series_Drawdown"].index, metrics["Series_Drawdown"], 0, color='red', alpha=0.3)
ax2.plot(metrics["Series_Drawdown"], color='red', lw=1)
ax2.set_title("Drawdown Histórico", fontsize=12)
ax2.set_ylabel("% Caída")
ax2.set_ylim(-0.6, 0.05) # Ajuste para ver bien las caídas
ax2.grid(alpha=0.3)

plt.tight_layout()
plt.show()







#___________________________________________________________________________________________
def dashboard_performance_avanzado(activo_1, activo_2, rf_pct):
    # 1. Descarga y Limpieza
    tickers = [activo_1, activo_2]
    df = yf.download(tickers, start="2018-01-01", auto_adjust=True, multi_level_index=False, progress=False)['Close']
    rets = np.log(df / df.shift(1)).dropna()
    rf = rf_pct / 100

    # 2. Procesamiento de Métricas
    stats = {}
    for t in tickers:
        m = analizar_performance_profesional(df[t], rf_anual=rf)
        stats[t] = m

    # 3. Creación de Tabla Comparativa
    resumen = {t: {
        "Retorno Anual": f"{stats[t]['Retorno Anualizado']:.2%}",
        "Volatilidad": f"{stats[t]['Volatilidad Anual']:.2%}",
        "Sharpe Ratio": f"{stats[t]['Sharpe Ratio']:.2f}",
        "Max Drawdown": f"{stats[t]['Max Drawdown']:.2%}",
        "Ratio Calmar": f"{stats[t]['Ratio de Calmar']:.2f}"
    } for t in tickers}

   

    # 4. Visualización Multi-Panel
    fig = plt.figure(figsize=(16, 12))
    gs = fig.add_gridspec(3, 2)

    # A. Equity Curve (Comparativa de Crecimiento)
    ax1 = fig.add_subplot(gs[0, :])
    for t in tickers:
        ax1.plot(stats[t]['Equity_Curve'], label=f"Crecimiento {t}", lw=2)
    ax1.set_title("Evolución del Capital (Base 1.0)")
    ax1.legend()
    ax1.grid(alpha=0.2)

    # B. Underwater Chart (Drawdowns)
    ax2 = fig.add_subplot(gs[1, :])
    colors = ['blue', 'orange']
    for i, t in enumerate(tickers):
        ax2.fill_between(stats[t]['Series_Drawdown'].index, stats[t]['Series_Drawdown'], 0, alpha=0.2, color=colors[i], label=f"DD {t}")
    ax2.set_title("Análisis del 'Dolor': Historial de Drawdowns")
    ax2.legend()
    ax2.grid(alpha=0.2)

    # C. Mapa Riesgo-Retorno (Scatter)
    ax3 = fig.add_subplot(gs[2, 0])
    vols = [stats[t]['Volatilidad Anual'] for t in tickers]
    returns = [stats[t]['Retorno Anualizado'] for t in tickers]
    sns.scatterplot(x=vols, y=returns, s=200, hue=tickers, ax=ax3)
    ax3.plot([0, max(vols)*1.1], [0, max(vols)*1.1], color='gray', ls='--', alpha=0.5, label='Sharpe 1.0')
    ax3.set_title("Ubicación en el Mapa de Riesgo-Retorno")
    ax3.set_xlabel("Volatilidad")
    ax3.set_ylabel("Retorno")
    ax3.legend()

    # D. Matriz de Correlación
    ax4 = fig.add_subplot(gs[2, 1])
    sns.heatmap(rets.corr(), annot=True, cmap='coolwarm', fmt=".2f", ax=ax4, cbar=False)
    ax4.set_title("Correlación de Retornos")

    plt.tight_layout()
    plt.show()

# Lanzamiento del Dashboard
widgets.interact(
    dashboard_performance_avanzado,
    activo_1=['SPY', 'QQQ', 'DIA', 'EEM'],
    activo_2=['BTC-USD', 'ETH-USD', 'GLD', 'TLT'],
    rf_pct=widgets.FloatSlider(min=0, max=6, step=0.1, value=2.0, description='Tasa RF %')
);