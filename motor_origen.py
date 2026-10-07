"""Motor de CLASIFICACION POR ORIGEN DE LA CAIDA.

Una caida de tres desviaciones tipicas por resultados no es el mismo suceso que
una caida de tres desviaciones por rotacion sectorial o por arrastre del indice,
aunque el numero sea identico. Promediarlas juntas -que es lo que hace cualquier
cribado por umbral- mezcla poblaciones con desenlaces distintos y devuelve una
media que no describe a ninguna.

CATEGORIAS
----------
  RESULTADOS      la caida cae en la ventana de publicacion de resultados.
                  Es el caso que interesa: el castigo por una cifra concreta.
  ARRASTRE        el conjunto del indice cayo con fuerza esa sesion. El valor
                  acompano; poco hay de propio en su desplome.
  SECTORIAL       el sector se desplomo sin que lo hiciera el mercado entero.
  IDIOSINCRATICA  el valor cayo solo, sin resultados de por medio y sin que ni
                  el indice ni su sector se movieran. Es la categoria que la
                  literatura de reversion senala como la mas propensa a
                  revertir, precisamente porque no responde a informacion
                  amplia.

El orden de precedencia importa y es el enumerado: los resultados mandan sobre
todo lo demas porque son una causa identificable y fechada.

QUE SE PUEDE CLASIFICAR HACIA ATRAS Y QUE NO
--------------------------------------------
El arrastre, lo sectorial y lo idiosincratico se deducen de los propios precios
y por tanto se pueden reconstruir cinco anios atras para las 503 sociedades. Los
titulares NO: el proveedor solo publica noticias recientes, de modo que emplear
noticias para clasificar el pasado es sencillamente imposible.

Los titulares se usan, pues, donde si tienen valor: como corroboracion de la
caida ACTUAL, aportando el motivo concreto que la prensa recoge. La estadistica
historica descansa en la clasificacion por precios y en las fechas de
resultados, que si son recuperables.
"""

import re

import numpy as np
import pandas as pd
import yfinance as yf

import motor_cribado as crib

HORIZONTES = (1, 3, 5, 10, 15)

# Sesiones a cada lado de la fecha de resultados que se consideran su ventana.
# Dos, porque la publicacion puede caer antes de la apertura o despues del
# cierre y el mercado reacciona en la sesion contigua.
VENTANA_RESULTADOS = 2

UMBRAL_ARRASTRE = 2.0     # sigmas del indice para considerar caida general
UMBRAL_SECTORIAL = 2.0    # sigmas del sector para considerar caida de sector

CATEGORIAS = ("Resultados", "Arrastre del índice", "Sectorial", "Idiosincrática")

DESCRIPCION = {
    "Resultados": "La caída coincide con la publicación de resultados. El "
                  "mercado reacciona a cifras concretas ya conocidas.",
    "Arrastre del índice": "El conjunto del mercado cayó con fuerza esa sesión. "
                           "El descenso del valor es en buena parte acompañamiento.",
    "Sectorial": "El sector retrocedió con fuerza sin que lo hiciera el mercado "
                 "entero. La causa es común a los comparables del valor.",
    "Idiosincrática": "El valor cayó en solitario, sin resultados de por medio y "
                      "sin movimiento apreciable del índice ni de su sector.",
}

# Terminos que permiten adivinar el motivo del titular de la caida actual
PISTAS = [
    ("Resultados", ("earnings", "results", "quarter", "q1", "q2", "q3", "q4",
                    "eps", "revenue", "beats", "misses", "guidance", "outlook",
                    "forecast", "resultados", "trimestre")),
    ("Regulatorio o judicial", ("lawsuit", "sec ", "investigation", "probe",
                                "fda", "antitrust", "regulator", "fine",
                                "settlement", "court", "ruling", "demanda")),
    ("Dirección", ("ceo", "cfo", "resign", "steps down", "appoint",
                   "management", "board", "dimite")),
    ("Operación corporativa", ("acquisition", "merger", "stake", "offering",
                               "buyback", "spin-off", "divest", "adquisición",
                               "fusión")),
    ("Analistas", ("downgrade", "upgrade", "price target", "rating",
                   "initiated", "cut to", "raised to")),
]


# =============================================================================
#  CLASIFICACION POR PRECIOS
# =============================================================================

def _series_referencia(cierres, universo):
    """Retornos del indice equiponderado y de cada sector, con sus sigmas."""
    retornos = cierres.pct_change()
    indice = retornos.mean(axis=1, skipna=True)
    sigma_indice = float(indice.std())

    sectores, sigmas_sector = {}, {}
    if universo is not None and "Sector" in universo.columns:
        for sector, grupo in universo.groupby("Sector"):
            miembros = [t for t in grupo["Ticker"] if t in cierres.columns]
            if len(miembros) < 3:
                continue
            serie = retornos[miembros].mean(axis=1, skipna=True)
            s = float(serie.std())
            if s > 0:
                sectores[sector] = serie
                sigmas_sector[sector] = s
    return indice, sigma_indice, sectores, sigmas_sector


def _clasificar(fecha, sector, indice, sigma_indice, sectores, sigmas_sector,
                fechas_resultados=None):
    """Categoria de una caida concreta segun el estado del indice y del sector."""
    if fechas_resultados is not None and len(fechas_resultados):
        dias = np.abs((np.array(fechas_resultados, dtype="datetime64[D]")
                       - np.datetime64(pd.Timestamp(fecha).date(), "D")).astype(int))
        if dias.min() <= VENTANA_RESULTADOS:
            return "Resultados"

    r_indice = indice.get(fecha, np.nan)
    if np.isfinite(r_indice) and sigma_indice > 0:
        if r_indice / sigma_indice <= -UMBRAL_ARRASTRE:
            return "Arrastre del índice"

    if sector and sector in sectores:
        r_sector = sectores[sector].get(fecha, np.nan)
        s = sigmas_sector.get(sector, 0.0)
        if np.isfinite(r_sector) and s > 0 and r_sector / s <= -UMBRAL_SECTORIAL:
            return "Sectorial"

    return "Idiosincrática"


def _futuros(precios, fecha, horizontes=HORIZONTES):
    """Retorno acumulado a cada horizonte desde el cierre de la caida."""
    posiciones = {f: i for i, f in enumerate(precios.index)}
    i = posiciones.get(fecha)
    if i is None:
        return None
    base = precios.iloc[i]
    if not (np.isfinite(base) and base):
        return None
    salida = {}
    for h in horizontes:
        if i + h < len(precios):
            futuro = precios.iloc[i + h]
            salida[h] = float(futuro / base - 1) if np.isfinite(futuro) else np.nan
        else:
            salida[h] = np.nan
    return salida


def clasificar_universo(cierres, universo, umbral=2.0, fechas_resultados=None,
                        horizontes=HORIZONTES, restringir_a_cobertura=True):
    """Clasifica las caidas extremas de cinco anios y mide su desenlace.

    `fechas_resultados` es un diccionario {ticker: [fechas]}.

    `restringir_a_cobertura` limita el calculo a los valores de los que SI se
    conocen las fechas de publicacion. No es una limitacion caprichosa: sin ella
    las caidas por resultados de los valores sin cobertura acaban repartidas
    entre las otras tres categorias, que quedan contaminadas justo con los casos
    que se pretendia aislar. En la primera prueba habia cobertura de 20 valores
    sobre 503, de modo que las 116 caidas etiquetadas como "Resultados" se
    comparaban contra otras tres categorias que contenian miles de caidas por
    resultados sin etiquetar. La comparacion entre categorias solo significa
    algo si las cuatro salen de la MISMA poblacion de valores.

    Las referencias de indice y de sector se siguen calculando sobre el universo
    ENTERO: para saber si el mercado cayo ese dia hacen falta todos los valores,
    no solo los de la submuestra.
    """
    if cierres is None or cierres.empty:
        return None

    indice, sigma_indice, sectores, sigmas_sector = _series_referencia(cierres, universo)
    mapa_sector = {}
    if universo is not None and "Sector" in universo.columns:
        mapa_sector = dict(zip(universo["Ticker"], universo["Sector"]))

    fechas_resultados = fechas_resultados or {}
    registros = []
    con_resultados = 0

    # El indice y los sectores se han calculado ya sobre el universo completo.
    # A partir de aqui se recorren solo los valores clasificables.
    if restringir_a_cobertura and fechas_resultados:
        examinados = [t for t in cierres.columns if t in fechas_resultados]
    else:
        examinados = list(cierres.columns)
    if not examinados:
        return None

    for tk in examinados:
        precios = cierres[tk].dropna()
        if len(precios) < crib.MIN_SESIONES:
            continue
        retornos = np.log(precios / precios.shift(1)).dropna()
        sigma = float(retornos.std())
        if not sigma or not np.isfinite(sigma):
            continue

        propias = fechas_resultados.get(tk)
        if propias:
            con_resultados += 1

        corte = -umbral * sigma
        caidas = retornos.index[retornos.values <= corte]
        for fecha in caidas:
            futuros = _futuros(precios, fecha, horizontes)
            if futuros is None:
                continue
            categoria = _clasificar(fecha, mapa_sector.get(tk), indice,
                                    sigma_indice, sectores, sigmas_sector, propias)
            fila = {"Ticker": tk, "Fecha": fecha, "Categoría": categoria,
                    "Caída": float(np.expm1(retornos.loc[fecha]))}
            fila.update({f"+{h}d": futuros[h] for h in horizontes})
            registros.append(fila)

    if not registros:
        return None

    tabla = pd.DataFrame(registros)
    return {"episodios": tabla, "umbral": umbral, "horizontes": list(horizontes),
            "valores_con_resultados": con_resultados,
            "valores_examinados": int(len(examinados)),
            "restringido": bool(restringir_a_cobertura and fechas_resultados),
            "valores_totales": int(len(cierres.columns))}


def desenlace_por_categoria(clasificacion, minimo=20):
    """Retorno medio y frecuencia de acierto a cada horizonte, por categoria."""
    if not clasificacion:
        return None
    tabla = clasificacion["episodios"]
    horizontes = clasificacion["horizontes"]

    filas = []
    for categoria in CATEGORIAS:
        sub = tabla[tabla["Categoría"] == categoria]
        if sub.empty:
            continue
        fila = {"Categoría": categoria, "Episodios": int(len(sub)),
                "Caída media": float(sub["Caída"].mean())}
        for h in horizontes:
            col = f"+{h}d"
            serie = sub[col].dropna()
            fila[col] = float(serie.mean()) if len(serie) >= minimo else np.nan
            fila[f"pos{h}"] = (float((serie > 0).mean())
                               if len(serie) >= minimo else np.nan)
            fila[f"n{h}"] = int(len(serie))
        filas.append(fila)

    if not filas:
        return None
    return {"tabla": pd.DataFrame(filas), "horizontes": horizontes,
            "minimo": minimo,
            "total": int(len(tabla)),
            "valores_con_resultados": clasificacion["valores_con_resultados"],
            "valores_examinados": clasificacion.get("valores_examinados"),
            "restringido": clasificacion.get("restringido", False),
            "valores_totales": clasificacion["valores_totales"]}


# =============================================================================
#  FECHAS DE RESULTADOS
# =============================================================================

def muestra_para_cobertura(universo, candidatos, total=80):
    """Valores de los que conviene recuperar las fechas de resultados.

    Primero los candidatos que se estan mostrando, que son imprescindibles.
    Despues se completa hasta `total` repartiendo por sector, de forma que la
    submuestra sobre la que se compara no quede escorada hacia un sector
    concreto: los desplomes por resultados no se comportan igual en tecnologia
    que en consumo basico, y una muestra sesgada trasladaria ese desequilibrio
    a la estadistica de todas las categorias.

    El reparto es determinista -orden alfabetico dentro de cada sector- para que
    dos ejecuciones seguidas den la misma muestra y las cifras no bailen.
    """
    elegidos = list(dict.fromkeys(candidatos or []))
    if universo is None or "Sector" not in universo.columns:
        return elegidos[:total]

    restantes = total - len(elegidos)
    if restantes <= 0:
        return elegidos[:total]

    por_sector = {}
    for sector, grupo in universo.groupby("Sector"):
        disponibles = sorted(t for t in grupo["Ticker"] if t not in elegidos)
        if disponibles:
            por_sector[sector] = disponibles

    # Reparto por turnos entre sectores hasta agotar el presupuesto
    turno = 0
    while restantes > 0 and por_sector:
        for sector in sorted(list(por_sector)):
            if restantes <= 0:
                break
            lista = por_sector[sector]
            if turno < len(lista):
                elegidos.append(lista[turno])
                restantes -= 1
            else:
                por_sector.pop(sector, None)
        turno += 1
        if turno > 200:
            break
    return elegidos


def fechas_resultados(tickers, maximo_por_valor=40):
    """Fechas de publicacion de resultados de cada valor, hasta donde llegue Yahoo.

    Se consultan de uno en uno porque la fuente no ofrece descarga conjunta. Por
    eso se limita a los valores que realmente se van a mostrar: pedirlas para
    las 503 del indice tardaria varios minutos y no aportaria nada.
    """
    salida = {}
    for tk in tickers:
        try:
            tabla = yf.Ticker(tk).get_earnings_dates(limit=maximo_por_valor)
        except Exception:
            continue
        if tabla is None or tabla.empty:
            continue
        try:
            fechas = pd.to_datetime(tabla.index)
            if getattr(fechas, "tz", None) is not None:
                fechas = fechas.tz_localize(None)
            salida[tk] = [f.date() for f in fechas]
        except Exception:
            continue
    return salida


# =============================================================================
#  ORIGEN DE LA CAIDA ACTUAL
# =============================================================================

def motivo_del_titular(titulo):
    """Deduce el asunto de un titular a partir de su texto."""
    if not titulo:
        return None
    texto = titulo.lower()
    for etiqueta, terminos in PISTAS:
        if any(t in texto for t in terminos):
            return etiqueta
    return None


def origen_actual(ticker, fecha, cierres, universo, noticias=None,
                  propias_resultados=None):
    """Clasifica la caida que se esta analizando y la corrobora con la prensa."""
    if cierres is None or ticker not in cierres.columns:
        return None
    indice, sigma_indice, sectores, sigmas_sector = _series_referencia(cierres, universo)
    mapa_sector = {}
    if universo is not None and "Sector" in universo.columns:
        mapa_sector = dict(zip(universo["Ticker"], universo["Sector"]))
    sector = mapa_sector.get(ticker)

    fecha = pd.Timestamp(fecha)
    categoria = _clasificar(fecha, sector, indice, sigma_indice, sectores,
                            sigmas_sector, propias_resultados)

    r_indice = indice.get(fecha, np.nan)
    r_sector = sectores[sector].get(fecha, np.nan) if sector in sectores else np.nan

    motivos, titulares = [], []
    for n in (noticias or []):
        if str(n.get("Ticker", "")).upper() != ticker.upper():
            continue
        titulo = n.get("Titular") or ""
        motivo = motivo_del_titular(titulo)
        if motivo:
            motivos.append(motivo)
        titulares.append({"Titular": titulo, "Motivo": motivo or "Sin clasificar",
                          "Fuente": n.get("Fuente", ""), "Fecha": n.get("Fecha")})

    predominante = None
    if motivos:
        predominante = max(set(motivos), key=motivos.count)

    return {
        "ticker": ticker,
        "fecha": fecha,
        "categoria": categoria,
        "descripcion": DESCRIPCION.get(categoria, ""),
        "retorno_indice": float(r_indice) if np.isfinite(r_indice) else np.nan,
        "retorno_sector": float(r_sector) if np.isfinite(r_sector) else np.nan,
        "sector": sector,
        "motivo_prensa": predominante,
        "titulares": titulares,
        # La prensa confirma la clasificacion por precios cuando ambas apuntan
        # a resultados; si discrepan, conviene saberlo antes que ocultarlo.
        "coincide": (predominante == "Resultados" and categoria == "Resultados"
                     if predominante else None),
    }
