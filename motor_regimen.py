"""Motor de CONDICIONAMIENTO POR REGIMEN.

El rebote tras una caida no es una constante del valor: depende del estado en
que se encuentre cuando cae. La reversion funciona en mercados de rango y
fracasa en caidas con tendencia; en 2008 y en marzo de 2020 todas las senales
de comprar el desplome dispararon y siguieron perdiendo.

POR QUE NO SE USA UN REGIMEN DE MERCADO GLOBAL
----------------------------------------------
Seria lo comodo -un solo indicador tipo VIX para todo- y seria enganoso. Un
mismo estado general del mercado significa cosas opuestas segun el valor: una
utility y una companiia de semiconductores no comparten ni volatilidad tipica ni
ciclo. Clasificar a las dos con la misma vara produce composiciones erroneas:
valores etiquetados como "en tension" que estan en su normalidad, y al reves.

Aqui el regimen se determina en DOS niveles, ambos propios del valor:

  NIVEL PROPIO      volatilidad realizada de 21 sesiones del valor, situada en
                    el percentil de SU PROPIA distribucion historica.
  NIVEL SECTORIAL   la misma medida sobre una cesta equiponderada de sus
                    comparables del mismo sector GICS.

Un valor puede estar tenso mientras su sector esta en calma -problema
idiosincratico- o tenso a la vez que todo su sector -problema del sector-. Son
situaciones distintas y el desenlace historico tambien lo es, asi que se
informa de las dos por separado.

El modulo NO interviene en la seleccion de valores. Es analisis complementario.
"""

import numpy as np
import pandas as pd

import motor_cribado as crib

VENTANA_VOL = 21            # sesiones de volatilidad realizada
MIN_HISTORIA_REGIMEN = 252  # historia minima para situar el percentil
MIN_EPISODIOS_REGIMEN = 3   # episodios minimos para dar una media por regimen

# Cortes de percentil que separan los tres estados
CORTE_CALMA = 0.33
CORTE_TENSION = 0.67

ESTADOS = ("Calma", "Normalidad", "Tensión")


def _volatilidad_realizada(retornos, ventana=VENTANA_VOL):
    """Volatilidad anualizada de las ultimas `ventana` sesiones, sesion a sesion."""
    return retornos.rolling(ventana, min_periods=max(ventana // 2, 5)).std() * np.sqrt(252)


def _percentil_expandido(serie):
    """Percentil de cada valor dentro de la historia DISPONIBLE HASTA ESE DIA.

    Se usa una ventana expandida y no la distribucion completa: clasificar el
    regimen de 2022 con la volatilidad de 2025 seria emplear informacion que
    entonces no existia, y el sesgo va justo en la direccion de hacer parecer
    que el metodo acierta mas de lo que acierta.

    El resultado se DESPLAZA una sesion, de modo que a cada fecha le corresponde
    el regimen vigente ANTES de esa sesion. Sin ese desplazamiento la
    clasificacion es circular: la volatilidad de veintiuna sesiones incluye la
    propia caida que se esta analizando, asi que todo valor que acabe de
    desplomarse aparece en tension por pura construccion. En la primera prueba
    los veintiun candidatos salieron los veintiuno en tension, que es tanto como
    no clasificar. Lo que interesa es el estado en que estaba el valor CUANDO
    cayo, que ademas es lo unico que se conocia de antemano.
    """
    pct = serie.expanding(min_periods=MIN_HISTORIA_REGIMEN).rank(pct=True)
    return pct.shift(1)


def _estado(percentil):
    if not np.isfinite(percentil):
        return None
    if percentil <= CORTE_CALMA:
        return "Calma"
    if percentil >= CORTE_TENSION:
        return "Tensión"
    return "Normalidad"


def cesta_sectorial(cierres, universo, sector):
    """Retorno diario de una cesta equiponderada del sector indicado."""
    if universo is None or "Sector" not in universo.columns:
        return None
    miembros = [t for t in universo.loc[universo["Sector"] == sector, "Ticker"]
                if t in cierres.columns]
    if len(miembros) < 3:
        return None
    return cierres[miembros].pct_change().mean(axis=1, skipna=True)


def _en_fecha(serie, fecha):
    """Valor de la serie en esa fecha; si no se indica, el ultimo disponible."""
    if serie is None or len(serie) == 0:
        return np.nan
    if fecha is None:
        return serie.iloc[-1]
    # La fecha se lleva a la zona del indice antes de comparar. Sin esto, un
    # indice con zona horaria frente a una fecha sin ella lanza TypeError; es
    # el mismo desajuste que ya ha aparecido tres veces en este proyecto.
    momento = pd.Timestamp(fecha)
    indice = pd.DatetimeIndex(serie.index)
    if indice.tz is not None and momento.tzinfo is None:
        momento = momento.tz_localize(indice.tz)
    elif indice.tz is None and momento.tzinfo is not None:
        momento = momento.tz_localize(None)
    valor = serie.get(momento, np.nan)
    if not np.isfinite(valor):
        previos = serie[indice <= momento]
        valor = previos.iloc[-1] if len(previos) else np.nan
    return valor


def regimen_de(ticker, cierres, universo=None, sector=None, fecha=None):
    """Estado del valor y de su sector en la fecha del episodio.

    `fecha` es la de la caida que se analiza. El regimen que se devuelve es el
    vigente ANTES de esa sesion, que es el unico que se conocia al producirse y
    el unico comparable con el de los episodios historicos.

    Devuelve None si no hay historia suficiente para situar el percentil, en
    lugar de inventar una clasificacion con cuatro observaciones.
    """
    if cierres is None or ticker not in cierres.columns:
        return None
    precios = cierres[ticker].dropna()
    if len(precios) < MIN_HISTORIA_REGIMEN + VENTANA_VOL:
        return None

    retornos = precios.pct_change().dropna()
    vol = _volatilidad_realizada(retornos)
    pct = _percentil_expandido(vol)

    p_actual = _en_fecha(pct, fecha)
    v_actual = _en_fecha(vol.shift(1), fecha)

    salida = {
        "ticker": ticker,
        "fecha": fecha,
        "volatilidad": float(v_actual) if np.isfinite(v_actual) else np.nan,
        "percentil": float(p_actual) if np.isfinite(p_actual) else np.nan,
        "estado": _estado(p_actual),
        "serie_percentil": pct,
        "serie_volatilidad": vol,
        "sector": sector,
        "estado_sector": None,
        "percentil_sector": np.nan,
        "volatilidad_sector": np.nan,
        "serie_percentil_sector": None,
    }

    if sector and universo is not None:
        cesta = cesta_sectorial(cierres, universo, sector)
        if cesta is not None:
            cesta = cesta.dropna()
            if len(cesta) >= MIN_HISTORIA_REGIMEN + VENTANA_VOL:
                vol_s = _volatilidad_realizada(cesta)
                pct_s = _percentil_expandido(vol_s)
                ps = _en_fecha(pct_s, fecha)
                vs = _en_fecha(vol_s.shift(1), fecha)
                salida.update({
                    "volatilidad_sector": float(vs) if np.isfinite(vs) else np.nan,
                    "percentil_sector": float(ps) if np.isfinite(ps) else np.nan,
                    "estado_sector": _estado(ps),
                    "serie_percentil_sector": pct_s,
                })
    return salida


def rebote_por_regimen(ticker, cierres, umbral, ventana, regimen):
    """Que hizo el valor tras caer, separando por el regimen en que se encontraba.

    Es la pregunta util: si el rebote historico solo aparece cuando el valor
    estaba en calma y hoy esta en tension, la media global no describe la
    situacion actual.
    """
    if regimen is None or cierres is None or ticker not in cierres.columns:
        return None
    precios = cierres[ticker].dropna()
    retornos = np.log(precios / precios.shift(1)).dropna()
    sigma = float(retornos.std())
    if not sigma or not np.isfinite(sigma):
        return None

    fechas, posteriores = crib.episodios_historicos(
        retornos, precios, sigma, umbral, ventana)
    if len(fechas) == 0:
        return None

    pct = regimen["serie_percentil"]
    filas = []
    for estado in ESTADOS:
        sel = [r for f, r in zip(fechas, posteriores)
               if _estado(pct.get(f, np.nan)) == estado]
        a = np.array(sel, dtype=float)
        filas.append({
            "Régimen": estado,
            "Episodios": int(len(a)),
            "Media": float(a.mean()) if len(a) >= MIN_EPISODIOS_REGIMEN else np.nan,
            "% en positivo": (float((a > 0).mean())
                              if len(a) >= MIN_EPISODIOS_REGIMEN else np.nan),
            "Peor": float(a.min()) if len(a) else np.nan,
            "Suficiente": len(a) >= MIN_EPISODIOS_REGIMEN,
        })

    tabla = pd.DataFrame(filas)
    actual = regimen.get("estado")
    fila_actual = tabla[tabla["Régimen"] == actual] if actual else None
    return {
        "tabla": tabla,
        "estado_actual": actual,
        "media_actual": (float(fila_actual["Media"].iloc[0])
                         if fila_actual is not None and len(fila_actual)
                         and np.isfinite(fila_actual["Media"].iloc[0]) else np.nan),
        "episodios_actual": (int(fila_actual["Episodios"].iloc[0])
                             if fila_actual is not None and len(fila_actual) else 0),
        "total": int(len(fechas)),
    }


def cuadro_regimenes(tickers, cierres, universo, umbral, ventana, maximo=25,
                     fechas=None):
    """Estado de regimen de cada valor de la lista, propio y de su sector.

    `fechas` es un diccionario {ticker: fecha de su caida}. Se usa para leer el
    regimen previo a cada episodio en lugar del de la ultima sesion.
    """
    if not tickers or cierres is None:
        return None
    sectores = {}
    if universo is not None and "Sector" in universo.columns:
        sectores = dict(zip(universo["Ticker"], universo["Sector"]))
    fechas = fechas or {}

    filas = []
    # Sin duplicados: un valor que cayo en dos sesiones del intervalo figura dos
    # veces en la relacion, pero su regimen es uno solo.
    for tk in list(dict.fromkeys(tickers))[:maximo]:
        reg = regimen_de(tk, cierres, universo, sectores.get(tk), fechas.get(tk))
        if reg is None:
            continue
        cond = rebote_por_regimen(tk, cierres, umbral, ventana, reg)
        filas.append({
            "Ticker": tk,
            "Sector": sectores.get(tk, ""),
            "Régimen del valor": reg["estado"] or "—",
            "Percentil propio": reg["percentil"],
            "Volatilidad": reg["volatilidad"],
            "Régimen del sector": reg["estado_sector"] or "—",
            "Percentil sectorial": reg["percentil_sector"],
            "Media en este régimen": cond["media_actual"] if cond else np.nan,
            "Episodios en este régimen": cond["episodios_actual"] if cond else 0,
            "Episodios totales": cond["total"] if cond else 0,
        })
    if not filas:
        return None

    tabla = pd.DataFrame(filas)
    # Divergencia entre el valor y su sector: senala si el problema es propio
    tabla["Divergencia"] = np.where(
        (tabla["Régimen del valor"] == "Tensión") &
        (tabla["Régimen del sector"].isin(["Calma", "Normalidad"])),
        "Tensión propia",
        np.where((tabla["Régimen del valor"] == "Tensión") &
                 (tabla["Régimen del sector"] == "Tensión"),
                 "Tensión sectorial", "—"))
    return {"tabla": tabla, "ventana": ventana, "umbral": umbral}
