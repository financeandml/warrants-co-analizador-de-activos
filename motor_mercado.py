"""Motor de OPCIONES y MICROESTRUCTURA.

Cubre dos bloques de la especificacion que hasta ahora estaban vacios:

  M32 · Movimiento implicito frente a real
        Cuanto descontaba el mercado ANTES del evento, para poder decir "se
        movio 2,3 veces lo previsto" en lugar de "se movio mucho".

  M34 · Calidad del movimiento
        Volumen, hora exacta y sesion de cada operacion. Es lo que distingue un
        movimiento con informacion detras de un artefacto de liquidez. El caso
        que motiva este modulo: una caida del 12,5% cuyo precio de referencia
        correspondia a una operacion registrada a las 16:04, cuatro minutos
        despues del cierre y once antes de la conferencia de resultados.

Fuentes y sus limites, medidos y no supuestos
---------------------------------------------
  - Cadena de opciones de Yahoo: completa y gratuita (volatilidad implicita,
    horquilla, interes abierto y volumen por strike, ~22 vencimientos). Lo que
    NO hay es historico: solo la foto de hoy. El movimiento implicito de un
    evento pasado no se puede reconstruir a posteriori; hay que capturarlo antes.
  - Intradia de 1 minuto: disponible con sesiones de preapertura y postcierre
    (04:00 a 20:00 hora de Nueva York), pero SOLO de los ultimos 8 dias
    naturales. Es un limite de la fuente, no del codigo.
"""

from datetime import datetime, time

import numpy as np
import pandas as pd
import yfinance as yf

# Horario del mercado estadounidense en hora de Nueva York
APERTURA = time(9, 30)
CIERRE = time(16, 0)
PREAPERTURA = time(4, 0)
POSTCIERRE = time(20, 0)

DIAS_INTRADIA = 8          # limite real de la fuente para granularidad de 1 minuto

BOLSA = "America/New_York"


def _hoy_nueva_york():
    """La fecha de HOY en el mercado, no en el reloj de quien ejecuta el programa.

    Los vencimientos que publica el proveedor son fechas del mercado
    estadounidense. Restarles la fecha local produce un desfase de un dia
    siempre que las dos zonas horarias no coincidan en ese instante, y el
    desfase NO es constante: depende de la hora a la que se mire y del pais
    desde el que se mire. A las 08:00 en Madrid son las 02:00 en Nueva York y
    todavia es el dia anterior; en un servidor situado en Estados Unidos, el
    mismo codigo devuelve la fecha correcta. El fallo aparece, por tanto, al
    cambiar de entorno o de usuario, nunca al probarlo en local.

    Sobre un vencimiento semanal a dos sesiones, un dia de error es la mitad
    del plazo.
    """
    return pd.Timestamp.now(tz=BOLSA).normalize().tz_localize(None)


# =============================================================================
#  M32 · OPCIONES Y MOVIMIENTO IMPLICITO
# =============================================================================

def _entero(valor, defecto=0):
    """Convierte a entero un campo que puede venir ausente o como NaN.

    El giro `valor or 0` NO sirve aqui y ademas falla de la peor manera. En
    Python NaN es un valor verdadero, de modo que `float("nan") or 0` devuelve
    NaN en lugar de cero y el `int()` posterior lanza ValueError. Yahoo deja el
    interes abierto sin rellenar en contratos poco negociados: con CVNA la
    pestana entera dejaba de dibujarse por una sola opcion sin ese dato.
    """
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return defecto
    if not np.isfinite(numero):
        return defecto
    return int(numero)


def _punto_medio(fila):
    """Precio de la opcion: punto medio de la horquilla, o ultimo si no hay."""
    bid, ask = fila.get("bid", np.nan), fila.get("ask", np.nan)
    if np.isfinite(bid) and np.isfinite(ask) and bid > 0 and ask > 0:
        return (bid + ask) / 2
    ultimo = fila.get("lastPrice", np.nan)
    return float(ultimo) if np.isfinite(ultimo) else np.nan


def cadena_opciones(simbolo, max_vencimientos=8):
    """Cadena de opciones por vencimiento, con volatilidad implicita y liquidez."""
    # El constructor tambien puede fallar: con un simbolo invalido yfinance
    # intenta interpretarlo como ISIN y lanza ValueError antes de llegar a
    # .options, asi que tiene que quedar DENTRO del try.
    try:
        t = yf.Ticker(simbolo)
        vencimientos = list(t.options)
    except Exception:
        return None
    if not vencimientos:
        return None

    try:
        info = t.info or {}
        spot = info.get("currentPrice") or info.get("regularMarketPrice")
    except Exception:
        spot = None
    if not spot:
        try:
            spot = float(t.history(period="5d")["Close"].dropna().iloc[-1])
        except Exception:
            return None

    hoy = _hoy_nueva_york()
    bloques = []
    for v in vencimientos[:max_vencimientos]:
        try:
            ch = t.option_chain(v)
        except Exception:
            continue
        calls, puts = ch.calls.copy(), ch.puts.copy()
        if calls.empty or puts.empty:
            continue
        calls["tipo"], puts["tipo"] = "call", "put"
        junto = pd.concat([calls, puts], ignore_index=True)
        junto["vencimiento"] = v
        dias = (pd.Timestamp(v) - hoy).days
        junto["dias"] = max(dias, 0)
        bloques.append(junto)

    if not bloques:
        return None
    tabla = pd.concat(bloques, ignore_index=True)
    tabla["moneyness"] = tabla["strike"] / spot - 1
    return {"tabla": tabla, "spot": float(spot),
            "vencimientos": vencimientos[:max_vencimientos], "todos": vencimientos}


def movimiento_implicito(cadena, vencimiento=None):
    """Movimiento que el mercado descuenta, a partir del straddle en el dinero.

    Se toma el strike mas cercano al precio y se suma call mas put: es lo que
    cuesta cubrir un movimiento en cualquier direccion hasta el vencimiento.
    Dividido entre el precio da el movimiento implicito en porcentaje.
    """
    if not cadena:
        return None
    tabla, spot = cadena["tabla"], cadena["spot"]
    venc = vencimiento or cadena["vencimientos"][0]
    sub = tabla[tabla["vencimiento"] == venc]
    if sub.empty:
        return None

    strikes = sorted(sub["strike"].unique())
    if not strikes:
        return None
    atm = min(strikes, key=lambda s: abs(s - spot))

    call = sub[(sub["strike"] == atm) & (sub["tipo"] == "call")]
    put = sub[(sub["strike"] == atm) & (sub["tipo"] == "put")]
    if call.empty or put.empty:
        return None

    precio_call = _punto_medio(call.iloc[0])
    precio_put = _punto_medio(put.iloc[0])
    if not (np.isfinite(precio_call) and np.isfinite(precio_put)):
        return None

    straddle = precio_call + precio_put
    implicito = straddle / spot
    dias = int(sub["dias"].iloc[0])

    iv_call = float(call.iloc[0].get("impliedVolatility", np.nan))
    iv_put = float(put.iloc[0].get("impliedVolatility", np.nan))
    iv_media = np.nanmean([iv_call, iv_put])

    return {
        "vencimiento": venc, "dias": dias, "strike_atm": float(atm), "spot": spot,
        "precio_call": precio_call, "precio_put": precio_put,
        "straddle": straddle, "movimiento_implicito": implicito,
        "iv_atm": iv_media,
        "liquidez_ok": bool(_entero(call.iloc[0].get("openInterest")) >= 10
                            and _entero(put.iloc[0].get("openInterest")) >= 10),
        "interes_call": _entero(call.iloc[0].get("openInterest")),
        "interes_put": _entero(put.iloc[0].get("openInterest")),
    }


def estructura_temporal(cadena):
    """Movimiento implicito y volatilidad para cada vencimiento disponible."""
    if not cadena:
        return None
    filas = []
    for v in cadena["vencimientos"]:
        m = movimiento_implicito(cadena, v)
        if m:
            filas.append({
                "Vencimiento": v, "Días": m["dias"],
                "Movimiento implícito": m["movimiento_implicito"],
                "Volatilidad implícita": m["iv_atm"],
                "Interés abierto": m["interes_call"] + m["interes_put"],
            })
    return pd.DataFrame(filas) if filas else None


def sonrisa_volatilidad(cadena, vencimiento=None, ancho=0.30):
    """Volatilidad implicita por strike: mide la asimetria del riesgo percibido.

    Si las puts fuera del dinero cotizan a volatilidad muy superior a las calls,
    el mercado esta pagando mas por cubrirse de una caida que de una subida.
    """
    if not cadena:
        return None
    venc = vencimiento or cadena["vencimientos"][0]
    sub = cadena["tabla"]
    sub = sub[(sub["vencimiento"] == venc) & (sub["moneyness"].abs() <= ancho)].copy()
    sub = sub[sub["impliedVolatility"] > 0.001]
    if sub.empty:
        return None
    sub = sub[["strike", "moneyness", "impliedVolatility", "tipo",
               "openInterest", "volume", "bid", "ask"]]
    return sub.sort_values(["tipo", "strike"])


def sesgo(cadena, vencimiento=None):
    """Diferencia de volatilidad entre la put y la call al 10% fuera del dinero."""
    s = sonrisa_volatilidad(cadena, vencimiento, ancho=0.25)
    if s is None or s.empty:
        return None

    def iv_cerca(tipo, objetivo):
        sub = s[s["tipo"] == tipo]
        if sub.empty:
            return np.nan
        fila = sub.iloc[(sub["moneyness"] - objetivo).abs().argsort()[:1]]
        return float(fila["impliedVolatility"].iloc[0]) if len(fila) else np.nan

    iv_put = iv_cerca("put", -0.10)
    iv_call = iv_cerca("call", 0.10)
    if not (np.isfinite(iv_put) and np.isfinite(iv_call)):
        return None
    return {"iv_put_10": iv_put, "iv_call_10": iv_call, "sesgo": iv_put - iv_call}


def concentracion_interes(cadena, vencimiento=None):
    """Interes abierto por strike. Los strikes muy cargados actuan como iman."""
    if not cadena:
        return None
    venc = vencimiento or cadena["vencimientos"][0]
    sub = cadena["tabla"]
    sub = sub[sub["vencimiento"] == venc]
    if sub.empty:
        return None
    agr = sub.groupby(["strike", "tipo"])["openInterest"].sum().reset_index()
    agr = agr[agr["openInterest"] > 0]
    return agr if not agr.empty else None


# =============================================================================
#  M34 · CALIDAD DEL MOVIMIENTO (MICROESTRUCTURA)
# =============================================================================

def _clasificar_sesion(momento):
    h = momento.time()
    if PREAPERTURA <= h < APERTURA:
        return "Preapertura"
    if APERTURA <= h < CIERRE:
        return "Sesión regular"
    if CIERRE <= h <= POSTCIERRE:
        return "Postcierre"
    return "Fuera de horario"


def intradia(simbolo, dias=DIAS_INTRADIA):
    """Velas de 1 minuto de los ultimos dias, incluyendo pre y postmercado."""
    try:
        d = yf.Ticker(simbolo).history(period=f"{dias}d", interval="1m",
                                       prepost=True, auto_adjust=False)
    except Exception:
        return None
    if d is None or d.empty:
        return None
    d = d[d["Volume"].notna()].copy()
    d["Sesion"] = [_clasificar_sesion(i) for i in d.index]
    d["Fecha"] = [i.date() for i in d.index]
    return d


def resumen_sesiones(datos):
    """Reparto del volumen entre preapertura, sesion regular y postcierre."""
    if datos is None or datos.empty:
        return None
    agr = datos.groupby(["Fecha", "Sesion"]).agg(
        Volumen=("Volume", "sum"), Operaciones=("Volume", "count"),
        Primero=("Open", "first"), Ultimo=("Close", "last")).reset_index()
    agr["Variacion"] = agr["Ultimo"] / agr["Primero"] - 1
    return agr


def calidad_del_dia(datos, fecha=None):
    """Anatomia de una sesion concreta: donde y cuando se movio de verdad.

    Devuelve el reparto del volumen por franja, el minuto de maxima variacion y
    una calificacion de representatividad del movimiento.
    """
    if datos is None or datos.empty:
        return None
    fecha = fecha or max(datos["Fecha"])
    dia = datos[datos["Fecha"] == fecha].copy()
    if dia.empty:
        return None

    # Solo cuentan los minutos en los que REALMENTE se ha negociado. Las velas
    # con volumen cero son cotizaciones sin cruce: producen saltos de precio
    # fantasma que, si se toman por buenos, senalan como "minuto de maximo
    # movimiento" una franja donde no cambio de manos ni una accion. Es
    # exactamente el artefacto que este modulo existe para descartar.
    negociados = dia[dia["Volume"] > 0].copy()
    negociados["Retorno"] = negociados["Close"].pct_change()
    dia["Retorno"] = np.nan
    dia.loc[negociados.index, "Retorno"] = negociados["Retorno"]
    volumen_total = float(dia["Volume"].sum())
    por_sesion = dia.groupby("Sesion").agg(
        Volumen=("Volume", "sum"), Minutos=("Volume", "count")).reset_index()
    por_sesion["Peso"] = por_sesion["Volumen"] / volumen_total if volumen_total else np.nan

    regular = dia[dia["Sesion"] == "Sesión regular"]
    fuera = dia[dia["Sesion"] != "Sesión regular"]
    peso_fuera = (float(fuera["Volume"].sum()) / volumen_total) if volumen_total else np.nan

    # Minuto de mayor movimiento, solo entre los que tuvieron negociacion real
    pico = None
    if not negociados.empty and negociados["Retorno"].notna().any():
        idx = negociados["Retorno"].abs().idxmax()
        f = negociados.loc[idx]
        pico = {"hora": idx.strftime("%H:%M"), "retorno": float(f["Retorno"]),
                "volumen": float(f["Volume"]), "sesion": f["Sesion"]}

    reg_neg = regular[regular["Volume"] > 0]
    apertura = float(reg_neg["Open"].iloc[0]) if not reg_neg.empty else np.nan
    cierre = float(reg_neg["Close"].iloc[-1]) if not reg_neg.empty else np.nan
    variacion_regular = (cierre / apertura - 1) if np.isfinite(apertura) and apertura else np.nan

    primero = float(negociados["Open"].iloc[0]) if not negociados.empty else np.nan
    ultimo = float(negociados["Close"].iloc[-1]) if not negociados.empty else np.nan
    variacion_total = (ultimo / primero - 1) if np.isfinite(primero) and primero else np.nan

    # Representatividad: un movimiento concentrado fuera de horario y con poco
    # volumen NO refleja el juicio del mercado.
    if not np.isfinite(peso_fuera):
        representatividad = "sin datos"
    elif peso_fuera > 0.50:
        representatividad = "baja"
    elif peso_fuera > 0.20:
        representatividad = "media"
    else:
        representatividad = "alta"

    return {
        "fecha": fecha, "por_sesion": por_sesion, "detalle": dia,
        "volumen_total": volumen_total, "peso_fuera_horario": peso_fuera,
        "pico": pico, "variacion_regular": variacion_regular,
        "variacion_total": variacion_total,
        "representatividad": representatividad,
        "minutos_con_negociacion": int((dia["Volume"] > 0).sum()),
    }


def perfil_volumen_precio(datos, fecha=None, tramos=24):
    """Volumen negociado por nivel de precio: donde se ha cruzado papel de verdad."""
    if datos is None or datos.empty:
        return None
    fecha = fecha or max(datos["Fecha"])
    dia = datos[datos["Fecha"] == fecha]
    if dia.empty or dia["Volume"].sum() <= 0:
        return None
    precios = dia["Close"]
    lo, hi = float(precios.min()), float(precios.max())
    if not np.isfinite(lo) or hi <= lo:
        return None
    bordes = np.linspace(lo, hi, tramos + 1)
    etiquetas = [(bordes[i] + bordes[i + 1]) / 2 for i in range(tramos)]
    cortes = pd.cut(precios, bins=bordes, labels=etiquetas, include_lowest=True)
    perfil = dia.groupby(cortes, observed=False)["Volume"].sum().reset_index()
    perfil.columns = ["Precio", "Volumen"]
    perfil["Precio"] = perfil["Precio"].astype(float)
    return perfil[perfil["Volumen"] > 0]
