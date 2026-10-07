"""Motor de calculo del ANALIZADOR DE ACTIVOS.

Aqui SOLO hay calculo: ni prints, ni input(), ni graficos. Lo consume la app web
(app_analizador.py) para que los numeros que salen en el navegador sean
exactamente los mismos que en la consola.

Las dos funciones centrales del analisis original -calcular_metricas_riesgo y
analizar_performance_profesional- estan copiadas VERBATIM del script de consola,
sin tocar una linea. El script "ANALIZADOR DE ACTIVOS INTERACTIVO.py" conserva
su propia copia y sigue funcionando por su cuenta.
"""

import logging
import socket
import urllib.error

import numpy as np
import pandas as pd
import yfinance as yf
from scipy.stats import norm, percentileofscore

# --- Parametros: los mismos que en el script de consola ---
PERIODO_HISTORICO = "5y"
FECHA_INICIO = "2021-01-01"
FECHA_INICIO_PERF = "2018-01-01"

VENTANAS_DRIFT = (5, 10, 20)
UMBRAL_EXTREMO = 2.0
UMBRAL_ELEVADO = 1.5
UMBRAL_REVERSION = 0.33
LIMITE_SORPRESA = 200.0


def _silenciar_yfinance():
    """yfinance escupe 404 por consola con simbolos inexistentes."""
    log = logging.getLogger("yfinance")
    previo = log.level
    log.setLevel(logging.CRITICAL)
    return log, previo


class FalloDeFuente(Exception):
    """El proveedor no ha respondido. NO significa que el activo no exista.

    Distinguir las dos cosas es imprescindible. Un `except` que devuelve None
    ante cualquier problema hace que un corte de red, un tiempo de espera
    agotado o una limitacion de peticiones acaben mostrando el mismo mensaje
    que un simbolo mal escrito: "no devuelve datos, prueba con otro nombre".
    El usuario corrige entonces algo que estaba bien y concluye que la
    herramienta no encuentra su activo, cuando lo unico que ocurria es que la
    fuente estaba caida o le habia cortado el paso.

    El caso se agrava al publicar el programa: desde una direccion compartida
    por muchos usuarios las limitaciones de peticiones son constantes, y en
    local no se manifiestan jamas.
    """


def _es_fallo_de_transporte(error):
    """True si el error es de la conexion, no del simbolo consultado."""
    # HTTPError PRIMERO: hereda de URLError, de modo que comprobar URLError
    # antes se traga tambien los 404 y convierte un simbolo inexistente en una
    # supuesta caida del proveedor, que es justo el error contrario.
    if isinstance(error, urllib.error.HTTPError):
        return error.code == 429 or error.code >= 500
    if isinstance(error, (urllib.error.URLError, socket.timeout,
                          ConnectionError, TimeoutError)):
        return True
    texto = f"{type(error).__name__} {error}".lower()
    marcas = ("timed out", "timeout", "connection", "temporarily unavailable",
              "too many requests", "rate limit", "429", "curl", "ssl",
              "max retries", "unreachable", "reset by peer")
    return any(m in texto for m in marcas)


# =============================================================================
#  DESCARGA DE DATOS
# =============================================================================

def info_ticker(simbolo):
    """Valida el simbolo contra Yahoo. Devuelve (nombre, moneda) o None.

    None significa "ese simbolo no existe". Si lo que falla es la conexion se
    lanza FalloDeFuente, que es cosa muy distinta y merece otro mensaje.
    """
    log, previo = _silenciar_yfinance()
    try:
        objeto = yf.Ticker(simbolo)
        prueba = objeto.history(period="1mo", auto_adjust=True)
    except Exception as e:
        if _es_fallo_de_transporte(e):
            raise FalloDeFuente(str(e)) from e
        return None
    finally:
        log.setLevel(previo)

    if prueba.empty:
        return None

    nombre, moneda = simbolo, "USD"
    try:
        info = objeto.info or {}
        nombre = info.get("longName") or info.get("shortName") or simbolo
        moneda = info.get("currency") or "USD"
    except Exception:
        pass
    return nombre, moneda


def buscar_tickers(texto, maximo=8):
    """Busca por NOMBRE de empresa y devuelve los tickers de Yahoo Finance.

    Evita tener que conocer de memoria el simbolo exacto: escribes "santander"
    y te ofrece SAN, SAN.MC, etc.
    """
    texto = (texto or "").strip()
    if len(texto) < 2:
        return []
    log, previo = _silenciar_yfinance()
    try:
        resultados = yf.Search(texto, max_results=maximo).quotes or []
    except Exception as e:
        # Lista vacia = "no hay ninguna empresa que se llame asi". Si el
        # buscador esta caido hay que decirlo, no fingir que no existe.
        if _es_fallo_de_transporte(e):
            raise FalloDeFuente(str(e)) from e
        return []
    finally:
        log.setLevel(previo)

    salida = []
    for q in resultados:
        simbolo = q.get("symbol")
        if not simbolo:
            continue
        salida.append({
            "simbolo": simbolo,
            "nombre": (q.get("shortname") or q.get("longname") or simbolo).strip(),
            "tipo": q.get("quoteType", ""),
            "mercado": q.get("exchDisp", ""),
        })
    return salida


def descargar_historico(simbolo, periodo=PERIODO_HISTORICO):
    """Cierres diarios ajustados + retornos simples, logaritmicos y volumen.

    Reproduce EXACTAMENTE la secuencia del script original, incluidos los dos
    dropna() intermedios:

        Close -> Return -> dropna -> LogReturn -> dropna -> Volatility

    El orden importa: si se calcula LogReturn antes del primer dropna, la serie
    queda desplazada una sesion respecto al original y todo lo que dependa de
    ventanas moviles (la volatilidad de 21 dias) deja de coincidir.
    El volumen se engancha al final para que nunca influya en los dropna.
    """
    bruto = yf.Ticker(simbolo).history(period=periodo, auto_adjust=True)

    h = bruto[["Close"]].copy()
    h["Return"] = h["Close"].pct_change()
    h = h.dropna()
    h["LogReturn"] = np.log(h["Close"] / h["Close"].shift(1))
    h = h.dropna()
    h["Volatility"] = h["LogReturn"].rolling(window=21).std() * np.sqrt(252)

    if "Volume" in bruto.columns:
        h["Volume"] = bruto["Volume"].reindex(h.index)
    return h


def descargar_rango(simbolo, inicio, fin=None):
    """Serie de cierres para un rango de fechas concreto."""
    datos = yf.download(simbolo, start=inicio, end=fin, auto_adjust=True,
                        multi_level_index=False, progress=False)
    if datos.empty:
        return None
    return datos["Close"].dropna()


def descargar_par(simbolo_a, simbolo_b, inicio=FECHA_INICIO_PERF):
    """Cierres de dos activos alineados, para la comparativa."""
    datos = yf.download([simbolo_a, simbolo_b], start=inicio, auto_adjust=True,
                        progress=False)["Close"]
    return datos.dropna()


# =============================================================================
#  FUNCIONES ORIGINALES - COPIADAS VERBATIM DEL SCRIPT DE CONSOLA
# =============================================================================

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


# =============================================================================
#  MONTE CARLO (mismo modelo GBM que el script original)
# =============================================================================

def monte_carlo(S0, sigma, r=0.05, T=1.0, pasos=252, n_sim=10000, semilla=0):
    """Trayectorias de precio por movimiento browniano geometrico.

    Mismas formulas que el script original. Unica diferencia: la semilla se fija
    para que el resultado no cambie solo por tocar un control en la web.
    """
    dt = T / pasos
    generador = np.random.default_rng(semilla)
    Z = generador.standard_normal((pasos, n_sim))

    retornos_diarios = np.exp((r - 0.5 * sigma ** 2) * dt + sigma * np.sqrt(dt) * Z)
    precios = np.zeros((pasos + 1, n_sim))
    precios[0] = S0
    precios[1:] = S0 * np.cumprod(retornos_diarios, axis=0)

    finales = precios[-1]

    # Escenarios: la mediana y las dos colas "razonables". No se usan el maximo
    # y el minimo absolutos porque dependen de una sola trayectoria afortunada.
    mediana_camino = np.median(precios, axis=1)
    mejor_camino = np.percentile(precios, 95, axis=1)
    peor_camino = np.percentile(precios, 5, axis=1)

    # Convergencia del promedio segun se acumulan simulaciones (grafico original)
    convergencia = np.cumsum(finales) / np.arange(1, n_sim + 1)

    return {
        "precios": precios,
        "finales": finales,
        "promedio": float(np.mean(finales)),
        "teorico": float(S0 * np.exp(r * T)),
        "error_estandar": float(np.std(finales) / np.sqrt(n_sim)),
        "percentiles": {p: float(np.percentile(finales, p)) for p in (1, 5, 25, 50, 75, 95, 99)},
        "mediana_camino": mediana_camino,
        "mejor_camino": mejor_camino,
        "peor_camino": peor_camino,
        "convergencia": convergencia,
        "mediana_final": float(mediana_camino[-1]),
        "mejor_final": float(mejor_camino[-1]),
        "peor_final": float(peor_camino[-1]),
    }


def intervalo_confianza(promedio, error_estandar, z=2.576):
    """Intervalo de confianza del 99% del precio final simulado (z = 2.576)."""
    margen = z * error_estandar
    return promedio - margen, promedio + margen


# =============================================================================
#  VOLUMEN DE NEGOCIACION Y RETORNOS
# =============================================================================

def analisis_volumen(historico, ventana=20):
    """Relacion estadistica entre el volumen negociado y el movimiento del precio.

    Mide la correlacion entre el volumen relativo (respecto a su media movil) y
    la magnitud absoluta del retorno diario, y compara el volumen medio de las
    sesiones de movimiento extremo con el del resto. Es una descripcion de los
    datos observados, sin interpretacion.
    """
    if "Volume" not in historico.columns:
        return None
    df = historico.dropna(subset=["Volume", "LogReturn"]).copy()
    df = df[df["Volume"] > 0]
    if len(df) < ventana + 10:
        return None

    df["VolMedia"] = df["Volume"].rolling(ventana).mean()
    df["VolRelativo"] = df["Volume"] / df["VolMedia"]
    df["AbsRetorno"] = df["LogReturn"].abs()
    df = df.dropna(subset=["VolRelativo"])
    if df.empty:
        return None

    subidas = df[df["LogReturn"] > 0]
    bajadas = df[df["LogReturn"] < 0]

    correl = float(df["VolRelativo"].corr(df["AbsRetorno"]))
    ultimo = df.iloc[-1]

    # Volumen medio en los dias de movimiento extremo (>2 sigmas)
    sigma = float(df["LogReturn"].std())
    extremos = df[df["AbsRetorno"] >= 2 * sigma]

    return {
        "datos": df[["Close", "Volume", "VolRelativo", "LogReturn", "AbsRetorno"]],
        "correlacion": correl,
        "vol_relativo_hoy": float(ultimo["VolRelativo"]),
        "volumen_hoy": float(ultimo["Volume"]),
        "vol_medio": float(ultimo["VolMedia"]),
        "vol_rel_subidas": float(subidas["VolRelativo"].mean()) if len(subidas) else np.nan,
        "vol_rel_bajadas": float(bajadas["VolRelativo"].mean()) if len(bajadas) else np.nan,
        "vol_rel_extremos": float(extremos["VolRelativo"].mean()) if len(extremos) else np.nan,
        "n_extremos": len(extremos),
    }


# =============================================================================
#  INDICADORES DE SOBREVENTA / SOBRECOMPRA
# =============================================================================

def indicadores_tecnicos(historico, ventana_rsi=14, ventana_bb=20):
    """RSI de Wilder, bandas de Bollinger y distancia a medias moviles.

    Indicadores descriptivos de uso estandar. Devuelven la posicion del precio
    respecto a sus propias referencias historicas; no emiten valoracion.
    """
    cierres = historico["Close"]
    if len(cierres) < max(ventana_rsi, ventana_bb) + 5:
        return None

    # --- RSI de Wilder ---
    delta = cierres.diff()
    ganancia = delta.clip(lower=0)
    perdida = -delta.clip(upper=0)
    media_g = ganancia.ewm(alpha=1 / ventana_rsi, adjust=False).mean()
    media_p = perdida.ewm(alpha=1 / ventana_rsi, adjust=False).mean()
    rs = media_g / media_p.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    # --- Bandas de Bollinger ---
    sma = cierres.rolling(ventana_bb).mean()
    desv = cierres.rolling(ventana_bb).std()
    banda_sup = sma + 2 * desv
    banda_inf = sma - 2 * desv
    posicion_bb = (cierres - sma) / (2 * desv)   # 0 = en la media, -1 = banda inferior

    sma50 = cierres.rolling(50).mean()
    sma200 = cierres.rolling(200).mean()

    tabla = pd.DataFrame({
        "Close": cierres, "RSI": rsi, "SMA": sma,
        "BandaSuperior": banda_sup, "BandaInferior": banda_inf,
        "PosicionBB": posicion_bb, "SMA50": sma50, "SMA200": sma200,
    })

    ult = tabla.iloc[-1]
    precio = float(ult["Close"])

    def _dist(valor):
        return float(precio / valor - 1) if pd.notna(valor) and valor else np.nan

    # Rachas consecutivas de sesiones a la baja
    signos = np.sign(historico["LogReturn"].dropna().values)
    racha = 0
    for s in signos[::-1]:
        if s < 0:
            racha += 1
        else:
            break

    return {
        "tabla": tabla,
        "rsi": float(ult["RSI"]) if pd.notna(ult["RSI"]) else np.nan,
        "posicion_bb": float(ult["PosicionBB"]) if pd.notna(ult["PosicionBB"]) else np.nan,
        "dist_sma20": _dist(ult["SMA"]),
        "dist_sma50": _dist(ult["SMA50"]),
        "dist_sma200": _dist(ult["SMA200"]),
        "racha_bajista": racha,
    }


# =============================================================================
#  REVERSION A LA MEDIA TRAS MOVIMIENTOS EXTREMOS
# =============================================================================

def reversion_tras_extremos(historico, umbral_sigmas=2.0, ventanas=(1, 3, 5, 10, 20)):
    """Comportamiento historico del precio despues de movimientos extremos.

    Localiza las sesiones en las que el retorno se desvio mas de N sigmas y
    calcula el retorno acumulado medio en las sesiones siguientes. Lo presenta
    junto al retorno medio de una sesion cualquiera del mismo periodo, que actua
    como referencia.

    Es un recuento estadistico sobre datos pasados: describe lo ocurrido, no
    anticipa lo que ocurrira ni valora el resultado.
    """
    rets = historico["LogReturn"].dropna()
    if len(rets) < 100:
        return None
    sigma = float(rets.std())
    if not sigma:
        return None

    cierres = historico["Close"].reindex(rets.index).values
    z = (rets / sigma).values
    n = len(cierres)

    caidas = [i for i in range(n) if z[i] <= -umbral_sigmas]
    subidas = [i for i in range(n) if z[i] >= umbral_sigmas]

    def _posteriores(indices, ventana):
        valores = [cierres[i + ventana] / cierres[i] - 1
                   for i in indices if i + ventana < n]
        return np.array(valores)

    def _base(ventana):
        valores = [cierres[i + ventana] / cierres[i] - 1
                   for i in range(n) if i + ventana < n]
        return np.array(valores)

    filas = []
    for v in ventanas:
        tras_caida = _posteriores(caidas, v)
        tras_subida = _posteriores(subidas, v)
        general = _base(v)
        filas.append({
            "Ventana": f"+{v}d",
            "sesiones": v,
            "Tras caida": float(tras_caida.mean()) if len(tras_caida) else np.nan,
            "% positivos caida": float((tras_caida > 0).mean()) if len(tras_caida) else np.nan,
            "n_caidas": len(tras_caida),
            "Tras subida": float(tras_subida.mean()) if len(tras_subida) else np.nan,
            "n_subidas": len(tras_subida),
            "Dia cualquiera": float(general.mean()) if len(general) else np.nan,
            "% positivos base": float((general > 0).mean()) if len(general) else np.nan,
            "Diferencia": (float(tras_caida.mean() - general.mean())
                           if len(tras_caida) and len(general) else np.nan),
        })

    tabla = pd.DataFrame(filas)
    diferencias = tabla["Diferencia"].dropna()

    # Posicion de la ultima sesion respecto al umbral
    z_hoy = float(z[-1])
    return {
        "tabla": tabla,
        "sigma": sigma,
        "umbral": umbral_sigmas,
        "n_caidas": len(caidas),
        "n_subidas": len(subidas),
        "z_hoy": z_hoy,
        "umbral_superado": z_hoy <= -umbral_sigmas,
        "diferencia_media": float(diferencias.mean()) if len(diferencias) else np.nan,
        "diferencia_positiva": bool(len(diferencias) and diferencias.mean() > 0),
    }


def sigma_anualizada(serie_precios):
    """Volatilidad anualizada a partir de una serie de cierres."""
    log_returns = np.log(serie_precios / serie_precios.shift(1))
    return float(log_returns.std() * np.sqrt(252))


# =============================================================================
#  EARNINGS: DETECCION DE SOBRERREACCION
# =============================================================================

def posicion_dia_reaccion(momento, fechas_sesion):
    """Indice de la sesion en la que el mercado DIGIERE los resultados.

    Si la empresa publica despues del cierre (Yahoo marca las 16:00 en NY), el
    movimiento no ocurre ese dia sino en la sesion siguiente.
    """
    dia = momento.date()
    if momento.hour >= 15:
        pos = int(np.searchsorted(fechas_sesion, dia, side="right"))
    else:
        pos = int(np.searchsorted(fechas_sesion, dia, side="left"))
    if pos >= len(fechas_sesion) or pos == 0:
        return None
    return pos


def _clasificar(recuperacion, prefijo="", sufijo=""):
    """Etiqueta descriptiva de lo que hizo el precio despues de la reaccion.

    Solo describe la trayectoria observada: revertido, continuado o sostenido.
    """
    if recuperacion >= UMBRAL_REVERSION:
        return f"{prefijo}Movimiento revertido{sufijo}"
    if recuperacion <= -0.10:
        return f"{prefijo}Movimiento prolongado{sufijo}"
    return f"{prefijo}Movimiento sostenido{sufijo}"


def analizar_earnings(simbolo, historico=None):
    """Cruza fechas de resultados con la reaccion real del precio.

    Devuelve None si el activo no publica earnings (ETF, indice, cripto, divisa).
    """
    log, previo = _silenciar_yfinance()
    try:
        fechas_earnings = yf.Ticker(simbolo).get_earnings_dates(limit=40)
    except Exception:
        fechas_earnings = None
    finally:
        log.setLevel(previo)

    if fechas_earnings is None or len(fechas_earnings) == 0:
        return None

    hist = descargar_historico(simbolo) if historico is None else historico
    if len(hist) < 60:
        return None

    fechas_sesion = np.array([d.date() for d in hist.index])
    ultima_sesion = fechas_sesion[-1]

    eventos, posiciones, futuros = [], [], []
    for momento, fila in fechas_earnings.sort_index().iterrows():
        pos = posicion_dia_reaccion(momento, fechas_sesion)
        if pos is None:
            if momento.date() > ultima_sesion:
                futuros.append(momento)
            continue
        if pos in posiciones:
            continue
        posiciones.append(pos)
        eventos.append({
            "momento": momento,
            "pos": pos,
            "fecha_reaccion": fechas_sesion[pos],
            "tras_cierre": momento.hour >= 15,
            "eps_est": fila.get("EPS Estimate", np.nan),
            "eps_real": fila.get("Reported EPS", np.nan),
            "sorpresa": fila.get("Surprise(%)", np.nan),
        })

    if not eventos:
        return None

    # Sigma de referencia: dias SIN resultados. Incluir los dias de earnings
    # inflaria sigma y todo movimiento pareceria menos extremo de lo que es.
    normales = np.ones(len(hist), dtype=bool)
    normales[posiciones] = False
    retornos_normales = hist["LogReturn"][normales].dropna()
    sigma_normal = float(retornos_normales.std())
    todos_retornos = hist["LogReturn"].dropna()
    cierres = hist["Close"].values

    for ev in eventos:
        pos = ev["pos"]
        lr = float(hist["LogReturn"].iloc[pos])
        ev["log_mov"] = lr
        ev["mov"] = float(np.expm1(lr))
        ev["sigmas"] = lr / sigma_normal if sigma_normal else np.nan
        ev["percentil"] = float(percentileofscore(todos_retornos, lr))

        for n in VENTANAS_DRIFT:
            ev[f"drift_{n}"] = (float(cierres[pos + n] / cierres[pos] - 1)
                                if pos + n < len(cierres) else np.nan)

        ev["sesiones_desde"] = len(cierres) - 1 - pos
        ev["drift_parcial"] = (float(cierres[-1] / cierres[pos] - 1)
                               if ev["sesiones_desde"] > 0 else np.nan)

        d_final, ventana_usada = np.nan, None
        for n in VENTANAS_DRIFT:
            if not np.isnan(ev[f"drift_{n}"]):
                d_final, ventana_usada = ev[f"drift_{n}"], n
        ev["ventana_drift"] = ventana_usada
        ev["recuperacion"] = (-d_final / ev["mov"]) if (ev["mov"] and not np.isnan(d_final)) else np.nan

        if abs(ev["sigmas"]) < UMBRAL_ELEVADO:
            ev["clasificacion"] = "Dentro del rango habitual"
        elif ventana_usada is not None:
            extra = f" [solo {ventana_usada}d]" if ventana_usada < max(VENTANAS_DRIFT) else ""
            ev["clasificacion"] = _clasificar(ev["recuperacion"], sufijo=extra)
        elif ev["sesiones_desde"] >= 1 and ev["mov"]:
            rec = -ev["drift_parcial"] / ev["mov"]
            ev["clasificacion"] = _clasificar(rec, prefijo="En curso: ",
                                              sufijo=f" ({ev['sesiones_desde']}d)")
        else:
            ev["clasificacion"] = "En curso (reaccion de la ultima sesion)"

    movs = np.array([abs(e["mov"]) for e in eventos])
    con_ventana = [e for e in eventos if not np.isnan(e["recuperacion"])]
    revierten = [e for e in con_ventana if e["recuperacion"] >= UMBRAL_REVERSION]

    return {
        "eventos": eventos,
        "sigma_normal": sigma_normal,
        "mov_medio_earnings": float(movs.mean()),
        "mov_medio_normal": float(np.expm1(retornos_normales.abs().mean())),
        "proximos": futuros,
        "n_extremos": len([e for e in eventos if abs(e["sigmas"]) >= UMBRAL_EXTREMO]),
        "n_con_ventana": len(con_ventana),
        "n_revierten": len(revierten),
        "tasa_reversion": (len(revierten) / len(con_ventana)) if con_ventana else np.nan,
    }


def tabla_earnings(datos):
    """Convierte los eventos en un DataFrame listo para mostrar."""
    filas = []
    for ev in datos["eventos"][::-1]:
        filas.append({
            "Publicacion": ev["momento"].strftime("%Y-%m-%d"),
            "Momento": "Tras cierre" if ev["tras_cierre"] else "Antes de abrir",
            "Reaccion": str(ev["fecha_reaccion"]),
            "Sorpresa EPS": ev["sorpresa"] / 100 if not np.isnan(ev["sorpresa"]) else None,
            "Movimiento": ev["mov"],
            "Sigmas": ev["sigmas"],
            "Percentil": ev["percentil"],
            "+5d": ev["drift_5"] if not np.isnan(ev["drift_5"]) else None,
            "+10d": ev["drift_10"] if not np.isnan(ev["drift_10"]) else None,
            "+20d": ev["drift_20"] if not np.isnan(ev["drift_20"]) else None,
            "Clasificacion": ev["clasificacion"],
        })
    return pd.DataFrame(filas)


def caminos_evento(datos, historico, pre=5, post=20):
    """Event study: camino del precio alrededor de cada publicacion.

    Normalizado a 0 el dia anterior a la reaccion.
    """
    cierres = historico["Close"].values
    caminos, etiquetas = [], []
    for ev in datos["eventos"]:
        p = ev["pos"]
        if p - pre - 1 < 0 or p + post >= len(cierres):
            continue
        caminos.append(cierres[p - pre: p + post + 1] / cierres[p - 1] - 1)
        etiquetas.append(ev["momento"].strftime("%Y-%m"))
    if not caminos:
        return None
    matriz = np.array(caminos)
    return {
        "eje": np.arange(-pre, post + 1),
        "caminos": matriz,
        "etiquetas": etiquetas,
        "medio": matriz.mean(axis=0),
        "salto": float(matriz.mean(axis=0)[pre]),
        "final": float(matriz.mean(axis=0)[-1]),
    }


def situacion_actual(historico, confianza, sigma_ref=None):
    """Los numeros de la 'ficha rapida': donde esta el activo ahora mismo."""
    cierres = historico["Close"]
    retornos = historico["LogReturn"].dropna()

    precio = float(cierres.iloc[-1])
    ultimo_log = float(retornos.iloc[-1])
    sigma = sigma_ref if sigma_ref else float(retornos.std())

    ventana = cierres.iloc[-252:] if len(cierres) >= 252 else cierres
    maximo, minimo = float(ventana.max()), float(ventana.min())

    var_hist = float(np.percentile(retornos, (1 - confianza / 100) * 100))

    return {
        "fecha": cierres.index[-1].date(),
        "precio": precio,
        "mov_dia": float(np.expm1(ultimo_log)),
        "sigmas_dia": ultimo_log / sigma if sigma else np.nan,
        "percentil_dia": float(percentileofscore(retornos, ultimo_log)),
        "max_52s": maximo,
        "min_52s": minimo,
        "pos_rango": (precio - minimo) / (maximo - minimo) * 100 if maximo > minimo else 50.0,
        "desde_maximo": precio / maximo - 1,
        "vol_anual": float(retornos.std() * np.sqrt(252)),
        "sigma_dia": sigma,
        "var_historico": var_hist,
        "supera_var": ultimo_log <= var_hist,
    }


# =============================================================================
#  SUFICIENCIA ESTADISTICA
#
#  Guardian que se coloca DELANTE de las metricas, sin tocar ninguna de las
#  funciones de calculo originales.
#
#  Motivo: con un historico corto las formulas siguen devolviendo un numero, y
#  ese numero parece tan preciso como cualquier otro. Con 8 sesiones de Banco
#  Santander salian un Sharpe de 6,39 y una volatilidad anual del 5,7% para un
#  banco que ronda el 25-30%. No eran errores de calculo: eran cifras correctas
#  sobre una muestra que no da para calcularlas.
#
#  Los umbrales no son arbitrarios. Un VaR al 99% situa el corte en el peor 1%
#  de las observaciones: con menos de 100 datos ese percentil ni siquiera tiene
#  una observacion propia detras y degenera en el minimo de la muestra. Los
#  ratios anualizados (Sharpe, Sortino, Calmar) comparan rentabilidad con riesgo
#  a escala anual, asi que por debajo de un ano de sesiones extrapolan mas de lo
#  que miden.
# =============================================================================

MIN_OBS_VAR_99 = 100      # el percentil 1 necesita al menos una observacion propia
MIN_OBS_VAR_95 = 60
MIN_OBS_VOLATILIDAD = 60  # unos tres meses para una desviacion tipica estable
MIN_OBS_DRAWDOWN = 60
MIN_OBS_RATIOS = 252      # un ano bursatil para anualizar sin extrapolar
MIN_OBS_DISTRIBUCION = 30


def minimo_para_var(confianza):
    """Observaciones necesarias para que el percentil del VaR sea interpretable."""
    cola = 1 - (confianza / 100 if confianza > 1 else confianza)
    if cola <= 0:
        return MIN_OBS_VAR_99
    # Se exigen al menos 3 observaciones dentro de la cola
    return max(MIN_OBS_VAR_95, int(np.ceil(3 / cola)))


def suficiencia(n_observaciones, confianza=99.0):
    """Que metricas admite una muestra de este tamano, y cuales no.

    No decide nada por su cuenta: devuelve el veredicto para que la interfaz
    muestre la cifra o explique por que no la muestra.
    """
    n = int(n_observaciones)
    min_var = minimo_para_var(confianza)
    bloques = {
        "distribucion": (n >= MIN_OBS_DISTRIBUCION, MIN_OBS_DISTRIBUCION,
                         "distribucion de retornos e histogramas"),
        "volatilidad": (n >= MIN_OBS_VOLATILIDAD, MIN_OBS_VOLATILIDAD,
                        "volatilidad anualizada"),
        "var": (n >= min_var, min_var,
                f"VaR y CVaR al {confianza:.1f}%"),
        "drawdown": (n >= MIN_OBS_DRAWDOWN, MIN_OBS_DRAWDOWN,
                     "maxima caida y curva de equidad"),
        "ratios": (n >= MIN_OBS_RATIOS, MIN_OBS_RATIOS,
                   "Sharpe, Sortino y Calmar"),
        "montecarlo": (n >= MIN_OBS_VOLATILIDAD, MIN_OBS_VOLATILIDAD,
                       "simulacion de Monte Carlo"),
    }
    detalle = {k: {"suficiente": ok, "minimo": m, "descripcion": d}
               for k, (ok, m, d) in bloques.items()}
    insuficientes = [d["descripcion"] for d in detalle.values() if not d["suficiente"]]
    return {
        "n": n,
        "confianza": confianza,
        "detalle": detalle,
        "todo_suficiente": not insuficientes,
        "insuficientes": insuficientes,
        "minimo_var": min_var,
    }


def listados_alternativos(simbolo, nombre_empresa, minimo_sesiones=250):
    """Otras cotizaciones de la misma empresa con mas historico disponible.

    Cuando Yahoo trunca la serie de un mercado concreto -le paso a la cotizacion
    de Madrid de Santander y BBVA, que quedaron en 10 sesiones mientras el ADR
    de Nueva York conservaba 1.255- lo util no es solo avisar, sino senalar donde
    si estan los datos.
    """
    candidatos = buscar_tickers(nombre_empresa or simbolo, maximo=8)
    salida = []
    for c in candidatos:
        if c["simbolo"].upper() == simbolo.upper():
            continue
        try:
            h = yf.Ticker(c["simbolo"]).history(period="5y", auto_adjust=True)
            n = len(h)
        except Exception:
            continue
        if n >= minimo_sesiones:
            salida.append({"simbolo": c["simbolo"], "nombre": c["nombre"],
                           "mercado": c["mercado"], "sesiones": n})
    return sorted(salida, key=lambda x: -x["sesiones"])
