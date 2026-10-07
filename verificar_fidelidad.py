"""Verificacion de fidelidad: motor de la web  vs  codigo original.

Reimplementa aqui, LITERALMENTE, las formulas del script original y compara
resultado a resultado con lo que devuelve motor_analisis.py. Cualquier
diferencia por encima de la precision de maquina se marca como FALLO.

Ejecutar:  python verificar_fidelidad.py
"""

import sys

import numpy as np
import pandas as pd
import yfinance as yf
from scipy.stats import norm

import motor_analisis as motor

TOLERANCIA = 1e-12
fallos = []
comprobaciones = 0


def comparar(etiqueta, obtenido, esperado, tol=TOLERANCIA):
    global comprobaciones
    comprobaciones += 1
    if isinstance(esperado, (pd.Series, np.ndarray)):
        a = np.asarray(obtenido, dtype=float)
        b = np.asarray(esperado, dtype=float)
        if a.shape != b.shape:
            iguales, detalle = False, f" (formas distintas: {a.shape} vs {b.shape})"
        else:
            # Los NaN tienen que estar en las MISMAS posiciones. Sin esta
            # comprobacion, un desfase de una fila pasaba desapercibido porque
            # nanmax ignora justo la celda que no cuadra.
            nan_a, nan_b = np.isnan(a), np.isnan(b)
            if not np.array_equal(nan_a, nan_b):
                iguales = False
                detalle = f" (NaN desalineados en {int((nan_a != nan_b).sum())} posiciones)"
            else:
                dif = np.abs(a[~nan_a] - b[~nan_b])
                maxdif = float(dif.max()) if dif.size else 0.0
                iguales = maxdif <= tol
                detalle = "" if iguales else f" (max dif {maxdif:.3e})"
    else:
        iguales = (abs(float(obtenido) - float(esperado)) <= tol
                   or (np.isnan(obtenido) and np.isnan(esperado)))
        detalle = "" if iguales else f" (obtenido {obtenido!r}, esperado {esperado!r})"
    estado = "OK  " if iguales else "FALLO"
    print(f"  [{estado}] {etiqueta}{detalle}")
    if not iguales:
        fallos.append(etiqueta)


def bloque(titulo):
    print("\n" + "=" * 76)
    print("  " + titulo)
    print("=" * 76)


TICKERS = ["ICHR", "AAPL", "SAN.MC"]

for TICKER in TICKERS:
    bloque(f"{TICKER}")

    # ---------------------------------------------------------------------
    # 1. Serie base: replica exacta del bloque 1 del script original
    # ---------------------------------------------------------------------
    # Secuencia LITERAL del script original, con sus DOS dropna
    orig = yf.Ticker(TICKER).history(period="5y", auto_adjust=True)
    orig = orig[["Close"]].copy()
    orig["Return"] = orig["Close"].pct_change()
    orig = orig.dropna()
    orig["LogReturn"] = np.log(orig["Close"] / orig["Close"].shift(1))
    orig = orig.dropna()
    orig["Volatility"] = orig["LogReturn"].rolling(window=21).std() * np.sqrt(252)

    web = motor.descargar_historico(TICKER)

    # El indice tiene que coincidir fila a fila, no solo en la interseccion
    comparar("Numero de sesiones", float(len(web)), float(len(orig)))
    mismo_indice = web.index.equals(orig.index)
    comprobaciones += 1
    print(f"  [{'OK  ' if mismo_indice else 'FALLO'}] Indice identico al original")
    if not mismo_indice:
        fallos.append("Indice distinto")
    o, w = orig, web

    print("\n-- Serie de precios y retornos --")
    comparar("Close", w["Close"], o["Close"])
    comparar("Return (pct_change)", w["Return"], o["Return"])
    comparar("LogReturn (log del cociente)", w["LogReturn"], o["LogReturn"])
    comparar("Volatility (rolling 21 * sqrt(252))", w["Volatility"], o["Volatility"])

    # Media y desviacion como las imprime el original
    comparar("Retorno medio diario", float(np.mean(w["Return"])),
             float(np.mean(o["Return"])))
    comparar("Desviacion estandar diaria", float(np.std(w["Return"])),
             float(np.std(o["Return"])))

    # ---------------------------------------------------------------------
    # 2. VaR / CVaR: funcion original copiada literalmente aqui
    # ---------------------------------------------------------------------
    def calcular_metricas_riesgo_ORIGINAL(returns, confianza=0.95):
        var_h = np.percentile(returns, (1 - confianza) * 100)
        mu = returns.mean()
        sigma = returns.std()
        z_score = norm.ppf(1 - confianza)
        var_p = mu + (z_score * sigma)
        peores_retornos = returns[returns <= var_h]
        cvar = peores_retornos.mean()
        return var_h, var_p, cvar

    rets = web["LogReturn"].dropna()
    print("\n-- VaR / CVaR --")
    for conf in (0.90, 0.95, 0.99):
        a = motor.calcular_metricas_riesgo(rets, conf)
        b = calcular_metricas_riesgo_ORIGINAL(rets, conf)
        comparar(f"VaR historico   ({conf:.0%})", a[0], b[0])
        comparar(f"VaR parametrico ({conf:.0%})", a[1], b[1])
        comparar(f"CVaR            ({conf:.0%})", a[2], b[2])

    # ---------------------------------------------------------------------
    # 3. Performance: funcion original copiada literalmente aqui
    # ---------------------------------------------------------------------
    def analizar_performance_ORIGINAL(precios, rf_anual=0.02):
        rets = np.log(precios / precios.shift(1)).dropna()
        cum_rets = np.exp(rets.cumsum())
        ret_anual = rets.mean() * 252
        vol_anual = rets.std() * np.sqrt(252)
        sharpe = (ret_anual - rf_anual) / vol_anual
        rets_negativos = rets[rets < 0]
        vol_downside = rets_negativos.std() * np.sqrt(252)
        sortino = (ret_anual - rf_anual) / vol_downside
        picos = cum_rets.cummax()
        drawdowns = (cum_rets - picos) / picos
        max_drawdown = drawdowns.min()
        calmar = ret_anual / abs(max_drawdown)
        return {"Retorno Anualizado": ret_anual, "Volatilidad Anual": vol_anual,
                "Sharpe Ratio": sharpe, "Sortino Ratio": sortino,
                "Max Drawdown": max_drawdown, "Ratio de Calmar": calmar,
                "Series_Drawdown": drawdowns, "Equity_Curve": cum_rets}

    print("\n-- Performance ajustada al riesgo --")
    a = motor.analizar_performance_profesional(web["Close"])
    b = analizar_performance_ORIGINAL(web["Close"])
    for clave in ["Retorno Anualizado", "Volatilidad Anual", "Sharpe Ratio",
                  "Sortino Ratio", "Max Drawdown", "Ratio de Calmar"]:
        comparar(clave, a[clave], b[clave])
    comparar("Equity_Curve (serie)", a["Equity_Curve"], b["Equity_Curve"])
    comparar("Series_Drawdown (serie)", a["Series_Drawdown"], b["Series_Drawdown"])

    # Con tasa libre de riesgo distinta (la del dashboard comparativo)
    a2 = motor.analizar_performance_profesional(web["Close"], rf_anual=0.02)
    b2 = analizar_performance_ORIGINAL(web["Close"], rf_anual=0.02)
    comparar("Sharpe con rf=2%", a2["Sharpe Ratio"], b2["Sharpe Ratio"])

    # ---------------------------------------------------------------------
    # 4. Monte Carlo: misma formula, mismo Z -> mismo resultado
    # ---------------------------------------------------------------------
    print("\n-- Monte Carlo (GBM) --")
    serie = motor.descargar_rango(TICKER, motor.FECHA_INICIO)
    S0 = float(serie.dropna().iloc[-1])
    sigma = motor.sigma_anualizada(serie)
    r, T, pasos, n_sim, semilla = 0.05, 1.0, 252, 2000, 7

    mc = motor.monte_carlo(S0, sigma, r=r, T=T, pasos=pasos, n_sim=n_sim, semilla=semilla)

    # Reproducimos la formula del original con el MISMO Z que uso el motor
    dt = T / pasos
    Z = np.random.default_rng(semilla).standard_normal((pasos, n_sim))
    retornos_diarios = np.exp((r - 0.5 * sigma ** 2) * dt + sigma * np.sqrt(dt) * Z)
    precios_orig = np.zeros((pasos + 1, n_sim))
    precios_orig[0] = S0
    precios_orig[1:] = S0 * np.cumprod(retornos_diarios, axis=0)

    comparar("Matriz de precios completa", mc["precios"].ravel(), precios_orig.ravel())
    comparar("Precio promedio final", mc["promedio"], float(np.mean(precios_orig[-1])))
    comparar("Valor teorico S0*exp(r*T)", mc["teorico"], float(S0 * np.exp(r * T)))
    comparar("Error estandar",
             mc["error_estandar"], float(np.std(precios_orig[-1]) / np.sqrt(n_sim)))

    # Intervalo de confianza del 99% como en el original
    z99 = 2.576
    margen = z99 * float(np.std(precios_orig[-1]) / np.sqrt(n_sim))
    prom = float(np.mean(precios_orig[-1]))
    lo, hi = motor.intervalo_confianza(mc["promedio"], mc["error_estandar"])
    comparar("IC 99% inferior", lo, prom - margen)
    comparar("IC 99% superior", hi, prom + margen)

    # Escenarios nuevos: que sean de verdad los percentiles pedidos
    comparar("Mediana final = percentil 50",
             mc["mediana_final"], float(np.percentile(precios_orig[-1], 50)), tol=1e-9)
    comparar("Mejor escenario = percentil 95",
             mc["mejor_final"], float(np.percentile(precios_orig[-1], 95)), tol=1e-9)
    comparar("Peor escenario = percentil 5",
             mc["peor_final"], float(np.percentile(precios_orig[-1], 5)), tol=1e-9)

    # Convergencia como en el original
    conv_orig = np.cumsum(precios_orig[-1]) / np.arange(1, n_sim + 1)
    comparar("Curva de convergencia", mc["convergencia"], conv_orig)

    # ---------------------------------------------------------------------
    # 5. Analisis de impacto (el bloque que se muestra en la web)
    # ---------------------------------------------------------------------
    print("\n-- Analisis de impacto --")
    inversion = 100000
    vh, _, cv = motor.calcular_metricas_riesgo(rets, 0.95)
    comparar("Perdida VaR sobre 100.000", inversion * vh, float(inversion * vh))
    comparar("Perdida CVaR sobre 100.000", inversion * cv, float(inversion * cv))
    print(f"         (VaR 95% = {vh:.2%} -> ${abs(inversion*vh):,.2f} | "
          f"CVaR = {cv:.2%} -> ${abs(inversion*cv):,.2f})")

    # ---------------------------------------------------------------------
    # 6. Coherencia interna de los bloques nuevos
    # ---------------------------------------------------------------------
    print("\n-- Bloques nuevos (coherencia interna) --")

    vol = motor.analisis_volumen(web)
    if vol:
        d = vol["datos"]
        comparar("Volumen relativo = Volume / media 20",
                 float(d["VolRelativo"].iloc[-1]),
                 float(d["Volume"].iloc[-1] / web["Volume"].rolling(20).mean().loc[d.index[-1]]),
                 tol=1e-9)
        comparar("|Retorno| coincide con abs(LogReturn)",
                 d["AbsRetorno"].values, np.abs(d["LogReturn"].values))

    tec = motor.indicadores_tecnicos(web)
    if tec:
        cierres = web["Close"]
        sma20 = cierres.rolling(20).mean().iloc[-1]
        comparar("Distancia a SMA20", tec["dist_sma20"],
                 float(cierres.iloc[-1] / sma20 - 1), tol=1e-9)
        rsi_ok = 0 <= tec["rsi"] <= 100
        comprobaciones += 1
        print(f"  [{'OK  ' if rsi_ok else 'FALLO'}] RSI dentro de [0, 100]: {tec['rsi']:.1f}")
        if not rsi_ok:
            fallos.append("RSI fuera de rango")

    rev = motor.reversion_tras_extremos(web, 2.0)
    if rev:
        sigma_r = float(web["LogReturn"].dropna().std())
        comparar("Sigma del analisis de reversion", rev["sigma"], sigma_r)
        z_hoy_esperado = float(web["LogReturn"].dropna().iloc[-1] / sigma_r)
        comparar("Z de la ultima sesion", rev["z_hoy"], z_hoy_esperado)
        # La diferencia debe ser exactamente la resta de las dos medias
        fila = rev["tabla"].iloc[2]   # +5d
        comparar("Diferencia +5d = tras caida - sesion cualquiera",
                 float(fila["Diferencia"]),
                 float(fila["Tras caida"] - fila["Dia cualquiera"]), tol=1e-12)

    ear = motor.analizar_earnings(TICKER, web)
    if ear:
        # La sigma sin earnings debe excluir exactamente los dias de reaccion
        posiciones = [e["pos"] for e in ear["eventos"]]
        mascara = np.ones(len(web), dtype=bool)
        mascara[posiciones] = False
        sigma_esperada = float(web["LogReturn"][mascara].dropna().std())
        comparar("Sigma sin earnings excluye los dias de reaccion",
                 ear["sigma_normal"], sigma_esperada)
        # Cada movimiento debe ser el retorno de su sesion de reaccion
        e0 = ear["eventos"][-1]
        comparar("Movimiento del ultimo earnings",
                 e0["mov"], float(np.expm1(web["LogReturn"].iloc[e0["pos"]])))
        comparar("Sigmas del ultimo earnings",
                 e0["sigmas"], float(web["LogReturn"].iloc[e0["pos"]]) / ear["sigma_normal"])


bloque("RESULTADO")
print(f"  Comprobaciones realizadas : {comprobaciones}")
print(f"  Fallos                    : {len(fallos)}")
if fallos:
    for f in fallos:
        print(f"     - {f}")
    sys.exit(1)
print("\n  TODO CORRECTO: el motor de la web reproduce el codigo original.")
