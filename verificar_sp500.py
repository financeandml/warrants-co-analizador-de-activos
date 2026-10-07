"""Barrido del motor completo sobre una muestra aleatoria del S&P 500.

Toma una muestra estratificada por sector GICS (para que entren REITs, bancos,
utilities y no solo tecnologicas) y ejecuta TODOS los modulos sobre cada
empresa, buscando tres clases de problema:

  1. Excepciones no controladas.
  2. Modulos que devuelven None sin motivo declarado.
  3. Valores absurdos que pasarian el filtro de "no ha petado" pero que serian
     un error si llegaran a la pantalla (ROIC del 5000%, margenes fuera de
     rango, puntuaciones fuera de escala).

Ejecutar:  python verificar_sp500.py [n_por_sector]
"""

import io
import random
import sys
import traceback
import urllib.request

import numpy as np
import pandas as pd
import yfinance as yf

import motor_analisis as ma
import motor_fundamentales as mf

SEMILLA = 20260805
N_POR_SECTOR = int(sys.argv[1]) if len(sys.argv) > 1 else 4

UA = {"User-Agent": f"Mozilla/5.0 (analizador {mf.CONTACTO_SEC})"}


def universo_sp500():
    req = urllib.request.Request(
        "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", headers=UA)
    html = urllib.request.urlopen(req, timeout=40).read().decode("utf-8")
    sp = pd.read_html(io.StringIO(html))[0]
    return sp[["Symbol", "Security", "GICS Sector"]]


def muestra(sp, n):
    rng = random.Random(SEMILLA)
    filas = []
    for sector, grupo in sp.groupby("GICS Sector"):
        tickers = list(grupo["Symbol"])
        elegidos = rng.sample(tickers, min(n, len(tickers)))
        for t in elegidos:
            fila = grupo[grupo["Symbol"] == t].iloc[0]
            filas.append((t.replace(".", "-"), fila["Security"], sector))
    return filas


incidencias = []


def anotar(ticker, modulo, mensaje):
    incidencias.append({"Ticker": ticker, "Modulo": modulo, "Problema": mensaje})


def rango(ticker, modulo, nombre, valor, minimo, maximo):
    """Marca valores que no petan pero que serian un error en pantalla."""
    if valor is None or (isinstance(valor, float) and not np.isfinite(valor)):
        return
    if not (minimo <= valor <= maximo):
        anotar(ticker, modulo, f"{nombre} fuera de rango: {valor:.4g} "
                               f"(esperado entre {minimo} y {maximo})")


def probar(ticker, nombre, sector, mapa):
    resumen = {"Ticker": ticker, "Empresa": nombre[:26], "Sector": sector[:22]}
    try:
        # ---------------- Motor de precios ----------------
        info = ma.info_ticker(ticker)
        if info is None:
            anotar(ticker, "precios", "info_ticker devuelve None")
            resumen["precios"] = "FALLO"
            return resumen
        hist = ma.descargar_historico(ticker)
        if hist is None or len(hist) < 30:
            anotar(ticker, "precios", f"historico insuficiente ({0 if hist is None else len(hist)})")
            resumen["precios"] = "FALLO"
            return resumen
        rets = hist["LogReturn"].dropna()
        vh, vp, cv = ma.calcular_metricas_riesgo(rets, 0.99)
        rango(ticker, "M-riesgo", "VaR 99%", vh, -0.60, 0.0)
        rango(ticker, "M-riesgo", "CVaR", cv, -0.90, 0.0)
        met = ma.analizar_performance_profesional(hist["Close"])
        rango(ticker, "M-perf", "Volatilidad anual", met["Volatilidad Anual"], 0.0, 3.0)
        rango(ticker, "M-perf", "Max drawdown", met["Max Drawdown"], -1.0, 0.0)
        ma.analizar_earnings(ticker, hist)
        ma.indicadores_tecnicos(hist)
        ma.analisis_volumen(hist)
        ma.reversion_tras_extremos(hist, 2.0)
        serie = ma.descargar_rango(ticker, ma.FECHA_INICIO)
        if serie is not None and len(serie) > 30:
            ma.monte_carlo(float(serie.dropna().iloc[-1]),
                           ma.sigma_anualizada(serie), n_sim=500, semilla=1)
        resumen["precios"] = "OK"

        # ---------------- Motor de fundamentales ----------------
        est = mf.estados_financieros(ticker)
        if est is None:
            anotar(ticker, "M1", "sin estados financieros")
            resumen["fundamentales"] = "SIN ESTADOS"
            return resumen

        clas = mf.clasificar_negocio(ticker)
        es_fin = clas["es_financiera"]
        resumen["tipo"] = clas["tipo"][:20]

        hechos = mf.companyfacts(mapa.get(ticker.upper()))
        resumen["SEC"] = "si" if hechos else "no"

        rec = mf.reconciliar(ticker, est, hechos)
        if rec["comprobaciones"].empty:
            anotar(ticker, "M9", "sin comprobaciones de integridad")
        resumen["M9_incid"] = len(rec["incidencias"])

        cal = mf.calidad_beneficio(est, es_financiera=es_fin)
        if cal is None:
            anotar(ticker, "M11", "calidad_beneficio devuelve None")
        else:
            u = cal["tabla"].iloc[-1]
            rango(ticker, "M11", "Devengos Sloan", u["Devengos Sloan"], -1.0, 1.0)
            rango(ticker, "M11", "DSO", u["DSO"], 0.0, 730.0)
            rango(ticker, "M11", "DIO", u["DIO"], 0.0, 2000.0)
            rango(ticker, "M11", "DPO", u["DPO"], 0.0, 730.0)
            rango(ticker, "M11", "Tasa fiscal", u["Tasa fiscal efectiva"], -3.0, 3.0)

        pio = mf.piotroski_f(est)
        if pio is None:
            anotar(ticker, "M12", "Piotroski devuelve None")
        else:
            rango(ticker, "M12", "Piotroski", pio["puntuacion"], 0, 9)
            if len(pio["tabla"]) != 9:
                anotar(ticker, "M12", f"Piotroski con {len(pio['tabla'])} pruebas")

        cap = info and (yf.Ticker(ticker).info or {}).get("marketCap", np.nan)
        alt = mf.altman_z(est, cap, es_financiera=es_fin)
        if es_fin and not (alt and alt.get("bloqueado")):
            anotar(ticker, "M12", "Altman NO bloqueado en entidad financiera")
        if alt and not alt.get("bloqueado"):
            rango(ticker, "M12", "Altman Z", alt["z"], -50, 200)

        ben = mf.beneish_m(est, es_financiera=es_fin)
        if es_fin and not (ben and ben.get("bloqueado")):
            anotar(ticker, "M12", "Beneish NO bloqueado en entidad financiera")
        if ben and not ben.get("bloqueado"):
            rango(ticker, "M12", "Beneish M", ben["m"], -20, 20)

        roi = mf.retornos_capital(est, es_financiera=es_fin)
        if es_fin and not (roi and roi.get('bloqueado')):
            anotar(ticker, 'M15', 'ROIC NO bloqueado en entidad financiera')
        if roi is not None and not roi.get('bloqueado'):
            rango(ticker, "M15", "ROIC", roi["roic_actual"], -5.0, 5.0)
            v = roi["tabla"].dropna(subset=["ROIC"])
            if not v.empty:
                u = v.iloc[-1]
                if np.isfinite(u["ROIC"]) and np.isfinite(u["NOPAT"]) and u["Capital invertido"]:
                    if abs(u["ROIC"] - u["NOPAT"] / u["Capital invertido"]) > 1e-9:
                        anotar(ticker, "M15", "ROIC no cuadra con NOPAT/capital")

        sol = mf.solvencia(est)
        if sol is None:
            anotar(ticker, "M16", "solvencia devuelve None")

        mf.asignacion_capital(est, info and 100.0)
        cre = mf.crecimiento_margenes(est)
        if cre is not None:
            u = cre["tabla"].iloc[-1]
            rango(ticker, "M14", "Margen bruto", u["Margen bruto"], -5.0, 1.5)
            rango(ticker, "M14", "Margen operativo", u["Margen operativo"], -20.0, 1.5)

        acciones = rec["acciones"]
        if np.isfinite(acciones):
            precio = float(hist["Close"].iloc[-1])
            mul = mf.multiplos(ticker, est, precio, acciones)
            rango(ticker, "M20", "Capitalizacion", mul["capitalizacion"], 1e7, 1e14)
            if not (mul["capitalizacion"] > 0):
                anotar(ticker, "M20", "capitalizacion nula o negativa")
            per = mul["tabla"].loc[mul["tabla"]["Multiplo"] == "PER", "Valor"]
            if len(per) and np.isfinite(per.iloc[0]):
                rango(ticker, "M20", "PER", per.iloc[0], -2000, 3000)
            if sol and np.isfinite(sol["fcf"]) and sol["fcf"] > 0:
                d = mf.dcf_inverso(mul["capitalizacion"], sol["fcf"],
                                   deuda_neta=sol["deuda_neta"]
                                   if np.isfinite(sol["deuda_neta"]) else 0.0)
                if d and not d.get("fuera_de_rango"):
                    rango(ticker, "M19", "Crecimiento implicito",
                          d["crecimiento_implicito"], -0.60, 1.60)
                    rango(ticker, "M19", "Peso terminal", d["peso_terminal"], 0.0, 1.0)

        mf.consenso(ticker)
        mf.insiders(ticker)
        resumen["fundamentales"] = "OK"
    except Exception as e:
        anotar(ticker, "EXCEPCION", f"{type(e).__name__}: {str(e)[:150]}")
        resumen["fundamentales"] = "EXCEPCION"
        traceback.print_exc(limit=2)
    return resumen


def main():
    print(f"Muestra estratificada del S&P 500 · semilla {SEMILLA} · "
          f"{N_POR_SECTOR} empresas por sector\n")
    sp = universo_sp500()
    seleccion = muestra(sp, N_POR_SECTOR)
    print(f"Empresas a probar: {len(seleccion)}\n")

    mapa = mf.mapa_ticker_cik()
    filas = []
    for i, (tk, nombre, sector) in enumerate(seleccion, 1):
        r = probar(tk, nombre, sector, mapa)
        filas.append(r)
        estado = f"{r.get('precios','-'):>6s} / {r.get('fundamentales','-'):>12s}"
        print(f"  [{i:2d}/{len(seleccion)}] {tk:6s} {nombre[:24]:26s} "
              f"{sector[:20]:22s} {estado}")

    tabla = pd.DataFrame(filas)
    print("\n" + "=" * 78)
    print("  RESUMEN")
    print("=" * 78)
    print(f"  Empresas probadas          : {len(tabla)}")
    print(f"  Motor de precios OK        : {(tabla.get('precios') == 'OK').sum()}")
    print(f"  Motor de fundamentales OK  : {(tabla.get('fundamentales') == 'OK').sum()}")
    sin_est = (tabla.get("fundamentales") == "SIN ESTADOS").sum()
    if sin_est:
        print(f"  Sin estados financieros    : {sin_est}")
    exc = (tabla.get("fundamentales") == "EXCEPCION").sum()
    print(f"  Excepciones                : {exc}")
    if "SEC" in tabla:
        print(f"  Con datos de SEC EDGAR     : {(tabla['SEC'] == 'si').sum()} de {len(tabla)}")
    if "M9_incid" in tabla:
        con_incid = (tabla["M9_incid"].fillna(0) > 0).sum()
        print(f"  Con incidencias de M9      : {con_incid} "
              f"(discrepancia de acciones, descuadre o datos caducados)")

    print(f"\n  Incidencias detectadas     : {len(incidencias)}")
    if incidencias:
        inc = pd.DataFrame(incidencias)
        print()
        print(inc.to_string(index=False, max_colwidth=70))
        criticas = inc[inc["Modulo"] == "EXCEPCION"]
        if not criticas.empty:
            print(f"\n  EXCEPCIONES NO CONTROLADAS: {len(criticas)}")
            sys.exit(1)
    else:
        print("\n  Ninguna. Todos los modulos responden en rango en toda la muestra.")


if __name__ == "__main__":
    main()
