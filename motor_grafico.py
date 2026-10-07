"""Motor del GRAFICO DE COTIZACION.

Prepara las series de velas para el grafico interactivo: OHLC y volumen a
distintas granularidades, con las sesiones de preapertura y postcierre
identificadas, y las medias moviles habituales.

Limites de la fuente, medidos y no supuestos
--------------------------------------------
Cada granularidad tiene su propio techo de historico en Yahoo Finance:

    1 minuto     ->   8 dias naturales
    2-30 minutos ->  60 dias naturales
    1 hora       -> 730 dias naturales
    1 dia        -> sin limite practico

Todas las granularidades intradia admiten sesiones fuera de horario. La diaria
no: sus velas ya consolidan la jornada completa.
"""

from datetime import time

import numpy as np
import pandas as pd
import yfinance as yf

from motor_analisis import FalloDeFuente, _es_fallo_de_transporte

# Horario del mercado estadounidense, hora de Nueva York
APERTURA = time(9, 30)
CIERRE = time(16, 0)
PREAPERTURA = time(4, 0)
POSTCIERRE = time(20, 0)

# granularidad -> (etiqueta, periodo maximo admitido, es intradia)
INTERVALOS = {
    "1m": ("1 minuto", "8d", True),
    "2m": ("2 minutos", "60d", True),
    "5m": ("5 minutos", "60d", True),
    "15m": ("15 minutos", "60d", True),
    "30m": ("30 minutos", "60d", True),
    "60m": ("1 hora", "730d", True),
    "1d": ("1 día", "max", False),
}

# Periodos ofrecidos para cada granularidad, del mas corto al mas largo
PERIODOS = {
    "1m": ["1d", "2d", "5d", "8d"],
    "2m": ["1d", "5d", "1mo", "60d"],
    "5m": ["1d", "5d", "1mo", "60d"],
    "15m": ["5d", "1mo", "60d"],
    "30m": ["5d", "1mo", "60d"],
    "60m": ["1mo", "3mo", "6mo", "1y", "2y"],
    "1d": ["3mo", "6mo", "1y", "2y", "5y", "10y"],
}

MEDIAS = (20, 50, 200)


def _clasificar(momento):
    h = momento.time()
    if PREAPERTURA <= h < APERTURA:
        return "Preapertura"
    if APERTURA <= h < CIERRE:
        return "Sesión regular"
    if CIERRE <= h <= POSTCIERRE:
        return "Postcierre"
    return "Fuera de horario"


def velas(simbolo, intervalo="1m", periodo=None, prepost=True):
    """Serie OHLCV lista para dibujar, con la franja horaria de cada vela.

    Devuelve None cuando la fuente no publica esa combinacion de granularidad
    y periodo, que es un limite real y conocido. Si lo que falla es la conexion
    se lanza FalloDeFuente: proponerle al usuario "pruebe con una granularidad
    mayor" cuando el problema es que el proveedor no responde le hace perder el
    tiempo cambiando controles que no tienen la culpa.
    """
    if intervalo not in INTERVALOS:
        return None
    etiqueta, tope, es_intradia = INTERVALOS[intervalo]
    periodo = periodo or PERIODOS[intervalo][-1]

    try:
        d = yf.Ticker(simbolo).history(
            period=periodo, interval=intervalo,
            prepost=prepost and es_intradia, auto_adjust=False)
    except Exception as e:
        if _es_fallo_de_transporte(e):
            raise FalloDeFuente(str(e)) from e
        return None
    if d is None or d.empty:
        return None

    columnas = ["Open", "High", "Low", "Close", "Volume"]
    if not all(c in d.columns for c in columnas):
        return None
    d = d[columnas].copy()

    # NO se filtra por volumen. Yahoo no publica volumen para las sesiones
    # extendidas a granularidad de un minuto -devuelve cero en todas ellas-
    # pero los PRECIOS si son reales y activos: en una preapertura de Tesla,
    # 636 de 660 velas cotizaron a un precio distinto de la anterior, con un
    # recorrido del 6,5%. Descartar esas velas por tener volumen cero eliminaba
    # del grafico la totalidad del pre y del postmercado.
    d = d.dropna(subset=["Open", "High", "Low", "Close"])
    if d.empty:
        return None
    d["Volume"] = d["Volume"].fillna(0)

    if es_intradia and not _es_continuo(d.index):
        d["Sesion"] = [_clasificar(i) for i in d.index]
    elif es_intradia:
        # Cripto y divisas negocian sin interrupcion: hablar de preapertura o
        # de postcierre carece de sentido y sombrear esas franjas confunde.
        d["Sesion"] = "Negociación continua"
    else:
        d["Sesion"] = "Sesión regular"
    d["Fecha"] = [i.date() for i in d.index]
    return d


def _es_continuo(indice):
    """True si el activo negocia sin interrupcion (cripto, divisas).

    Se combinan dos senales porque ninguna basta por si sola:

      - Velas en fin de semana. Es la mas clara, pero desaparece si el periodo
        consultado no incluye ningun sabado ni domingo: con dos dias de datos
        de un jueves y un viernes, Bitcoin pasaba por valor bursatil y se le
        pintaban franjas de "preapertura" que no significan nada.
      - Velas fuera del horario 04:00-20:00 de Nueva York. Una accion nunca
        cotiza ahi ni con sesiones extendidas; un activo continuo, un tercio
        del tiempo. Esta senal funciona aunque se mire un solo dia.
    """
    if indice is None or len(indice) == 0:
        return False
    momentos = pd.Series(list(indice))
    finde = pd.Series([i.weekday() >= 5 for i in indice]).mean()
    fuera = pd.Series([not (PREAPERTURA <= i.time() <= POSTCIERRE)
                       for i in indice]).mean()
    return bool(finde > 0.10 or fuera > 0.10)


def cotiza_continuo(datos):
    """True si el activo negocia tambien fines de semana (cripto, divisas).

    Importa para el grafico: en un valor bursatil hay que ocultar noches y fines
    de semana o la serie aparece llena de huecos vacios, pero en un activo que
    cotiza sin interrupcion ocultarlos borraria datos reales.
    """
    if datos is None or datos.empty:
        return False
    return _es_continuo(datos.index)


def cortes_temporales(datos, intervalo, prepost=True):
    """Tramos horarios sin negociacion que el grafico debe comprimir."""
    if datos is None or datos.empty or cotiza_continuo(datos):
        return []
    cortes = [dict(bounds=["sat", "mon"])]          # fines de semana
    if INTERVALOS.get(intervalo, (None, None, False))[2]:
        if prepost:
            cortes.append(dict(bounds=[20, 4], pattern="hour"))
        else:
            cortes.append(dict(bounds=[16, 9.5], pattern="hour"))
    return cortes


def medias_moviles(datos, ventanas=MEDIAS):
    """Medias moviles simples sobre el cierre, solo las que caben en la serie."""
    if datos is None or datos.empty:
        return {}
    salida = {}
    for v in ventanas:
        if len(datos) >= v:
            salida[v] = datos["Close"].rolling(v).mean()
    return salida


def franjas_extendidas(datos):
    """Intervalos de preapertura y postcierre, para sombrearlos en el grafico."""
    if datos is None or datos.empty or "Sesion" not in datos.columns:
        return []
    if cotiza_continuo(datos):
        return []
    marcas = datos["Sesion"].isin(["Preapertura", "Postcierre"])
    if not marcas.any():
        return []

    franjas, inicio, previo = [], None, None
    for momento, fuera in zip(datos.index, marcas):
        if fuera and inicio is None:
            inicio = momento
        elif not fuera and inicio is not None:
            franjas.append((inicio, previo if previo is not None else momento))
            inicio = None
        previo = momento
    if inicio is not None:
        franjas.append((inicio, datos.index[-1]))
    return franjas


def resumen(datos):
    """Ultimo precio, variacion de la jornada y rango, para la cabecera."""
    if datos is None or datos.empty:
        return None
    ultimo = float(datos["Close"].iloc[-1])
    ultima_fecha = datos["Fecha"].iloc[-1]
    jornada = datos[datos["Fecha"] == ultima_fecha]

    apertura = float(jornada["Open"].iloc[0]) if not jornada.empty else np.nan
    variacion = (ultimo / apertura - 1) if np.isfinite(apertura) and apertura else np.nan

    regular = jornada[jornada["Sesion"] == "Sesión regular"] if "Sesion" in jornada else jornada
    cierre_regular = float(regular["Close"].iloc[-1]) if len(regular) else np.nan

    return {
        "ultimo": ultimo,
        "momento": datos.index[-1],
        "sesion_actual": datos["Sesion"].iloc[-1] if "Sesion" in datos else "",
        "variacion_jornada": variacion,
        "maximo": float(jornada["High"].max()) if not jornada.empty else np.nan,
        "minimo": float(jornada["Low"].min()) if not jornada.empty else np.nan,
        "volumen": float(jornada["Volume"].sum()) if not jornada.empty else np.nan,
        "cierre_regular": cierre_regular,
        "velas": len(datos),
        "desde": datos.index[0],
        "sesiones": int(pd.Series(datos["Fecha"]).nunique()),
    }
