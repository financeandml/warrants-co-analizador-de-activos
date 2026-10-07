"""Motor de VALIDACION ESTADISTICA del cribado.

Dos capas que se colocan SOBRE la seleccion de valores sin alterarla. Ninguna
de las dos elimina candidatos ni reordena la lista: el motor de busqueda sigue
haciendo exactamente lo que hacia. Lo que aportan es la respuesta a la pregunta
que el propio cribado no puede contestar sobre si mismo.

1. CONTRASTE MULTIPLE
   Al examinar 503 sociedades y quedarse con las que mejor se comportaron, se
   esta eligiendo sobre los mismos datos con los que se mide. Con 503 contrastes
   al 5%, unos 25 valores apareceran "significativos" por puro azar. El
   procedimiento de Benjamini-Hochberg controla la proporcion esperada de falsos
   hallazgos entre los declarados, que es la pregunta pertinente cuando se
   contrastan muchas hipotesis a la vez. Se acompana del umbral de Bonferroni,
   mucho mas exigente, como referencia conservadora.

2. VALIDACION FUERA DE PERIODO
   La estadistica de rebote se calcula hoy sobre los cinco anios completos,
   incluido el pasado reciente. Aqui se parte la muestra: los episodios del
   primer tramo construyen la estadistica y los del segundo la ponen a prueba
   sin haber participado en su calculo.

   La particion NO puede ser un corte limpio. Con un horizonte de quince
   sesiones, un episodio ocurrido diez dias antes de la frontera tiene su
   resultado dentro del tramo siguiente: la informacion se filtra de un lado a
   otro. Se aplica por eso PURGA (se descartan los episodios cuyo horizonte
   cruza la frontera) y EMBARGO (se descarta ademas un margen posterior, porque
   la volatilidad y el precio de partida siguen correlacionados un tiempo
   despues del corte).

La cifra que mas informa no es la de ningun valor concreto, sino la CORRELACION
entre lo medido dentro de periodo y lo ocurrido fuera. Si es proxima a cero, la
seleccion no tiene capacidad predictiva por muy vistosas que sean las medias.
"""

import numpy as np
import pandas as pd
from scipy import stats

import motor_cribado as crib

# Proporcion de falsos hallazgos que se admite entre los declarados
TASA_FALSOS_HALLAZGOS = 0.10

# Reparto de la muestra entre construccion y validacion
FRACCION_DENTRO = 0.60

# Episodios minimos en cada tramo para que la comparacion signifique algo
MIN_EPISODIOS_TRAMO = 3

# Pliegues de la validacion cruzada purgada
PLIEGUES = 5


# =============================================================================
#  1 · CONTRASTE MULTIPLE
# =============================================================================

def _p_valor(posteriores, referencia):
    """Probabilidad de observar este rebote si el valor no aportase nada.

    Contraste unilateral: interesa unicamente si el retorno posterior supera al
    de una sesion cualquiera del mercado, no si difiere en cualquier direccion.
    """
    a = np.asarray(posteriores, dtype=float)
    a = a[np.isfinite(a)]
    if len(a) < 3:
        return np.nan
    if np.allclose(a, a[0]):
        return np.nan
    t, p_bilateral = stats.ttest_1samp(a, referencia)
    # De bilateral a unilateral por la cola que interesa
    p = p_bilateral / 2 if t > 0 else 1 - p_bilateral / 2
    return float(min(max(p, 0.0), 1.0))


def benjamini_hochberg(p_valores, tasa=TASA_FALSOS_HALLAZGOS):
    """Control de la tasa de falsos hallazgos sobre un conjunto de contrastes.

    Devuelve (rechazos, q_valores) alineados con la entrada. Los NaN se
    conservan como NaN y no cuentan como contraste realizado.
    """
    p = np.asarray(p_valores, dtype=float)
    validos = np.isfinite(p)
    m = int(validos.sum())
    rechazos = np.zeros(len(p), dtype=bool)
    q = np.full(len(p), np.nan)
    if m == 0:
        return rechazos, q

    indices = np.where(validos)[0]
    orden = indices[np.argsort(p[indices], kind="stable")]
    ordenados = p[orden]

    # q-valores: ajuste escalonado con imposicion de monotonia de atras
    # adelante, para que un contraste no salga con q menor que otro mas
    # significativo.
    escalado = ordenados * m / np.arange(1, m + 1)
    q_ord = np.minimum.accumulate(escalado[::-1])[::-1]
    q_ord = np.minimum(q_ord, 1.0)
    q[orden] = q_ord

    # Mayor k que cumple p_(k) <= (k/m)*tasa; se rechazan todos hasta ese k
    umbrales = tasa * np.arange(1, m + 1) / m
    cumple = ordenados <= umbrales
    if cumple.any():
        k = int(np.where(cumple)[0].max())
        rechazos[orden[: k + 1]] = True
    return rechazos, q


def contraste_multiple(resultado, referencia, tasa=TASA_FALSOS_HALLAZGOS):
    """Anade a la tabla el contraste de cada valor y su correccion conjunta.

    NO filtra ni reordena: solo agrega columnas. La decision de que mirar sigue
    siendo del usuario y del criterio historico que el mismo fija.
    """
    if not resultado or resultado.get("tabla") is None or resultado["tabla"].empty:
        return resultado
    episodios = resultado.get("episodios") or {}
    if not episodios:
        return resultado

    base = float(referencia["media"]) if referencia else 0.0
    tabla = resultado["tabla"].copy()

    # UN contraste por VALOR, no por fila. Cuando se revisan varias sesiones
    # atras, un valor que cayo dos veces en el intervalo aparece dos veces en la
    # relacion, pero su historial de rebote es el mismo y la hipotesis que se
    # contrasta tambien: contarla dos veces infla el numero de contrastes -63
    # frente a 57 valores reales en una prueba- y desplaza el umbral de
    # Benjamini-Hochberg, que presupone contrastes distintos entre si.
    unicos = list(dict.fromkeys(tabla["Ticker"]))
    p_por_valor = {}
    for tk in unicos:
        datos = episodios.get(tk)
        p_por_valor[tk] = _p_valor(datos["retornos"], base) if datos else np.nan

    p_unicos = [p_por_valor[tk] for tk in unicos]
    rechazos_u, q_unicos = benjamini_hochberg(p_unicos, tasa)
    q_por_valor = dict(zip(unicos, q_unicos))
    rechazo_por_valor = dict(zip(unicos, rechazos_u))

    tabla["p"] = [p_por_valor.get(tk, np.nan) for tk in tabla["Ticker"]]
    tabla["q"] = [q_por_valor.get(tk, np.nan) for tk in tabla["Ticker"]]
    rechazos = np.array([bool(rechazo_por_valor.get(tk, False))
                         for tk in tabla["Ticker"]])
    tabla["Supera el contraste"] = rechazos

    contrastados = int(np.isfinite(np.asarray(p_unicos, dtype=float)).sum())
    supervivientes = int(rechazos_u.sum())
    resumen = {
        "tasa": tasa,
        "contrastes": contrastados,
        "supervivientes": supervivientes,
        # Con m contrastes al nivel nominal, esta es la cantidad de "hallazgos"
        # que apareceria aunque ninguno fuese real.
        "esperados_por_azar": contrastados * tasa,
        "umbral_bonferroni": tasa / contrastados if contrastados else np.nan,
        "referencia": base,
    }
    return {**resultado, "tabla": tabla, "contraste": resumen}


# =============================================================================
#  2 · VALIDACION FUERA DE PERIODO
# =============================================================================

def frontera(indice, fraccion=FRACCION_DENTRO):
    """Fecha que separa el tramo de construccion del de validacion."""
    if indice is None or len(indice) == 0:
        return None
    corte = int(len(indice) * fraccion)
    corte = min(max(corte, 1), len(indice) - 1)
    return indice[corte]


def _tramos(indice, ventana, fraccion=FRACCION_DENTRO):
    """Limites de ambos tramos con purga y embargo alrededor de la frontera.

    La purga descarta los episodios cuyo horizonte cruzaria el corte. El
    embargo anade un margen equivalente al principio del segundo tramo.
    """
    if indice is None or len(indice) <= 2 * ventana + 2:
        return None
    corte = int(len(indice) * fraccion)
    corte = min(max(corte, ventana + 1), len(indice) - ventana - 2)

    fin_dentro = indice[corte - ventana]          # purga: horizonte completo antes del corte
    inicio_fuera = indice[min(corte + ventana, len(indice) - 1)]   # embargo
    return {"inicio_dentro": indice[0], "fin_dentro": fin_dentro,
            "inicio_fuera": inicio_fuera, "fin_fuera": indice[-1],
            "frontera": indice[corte], "purga": ventana, "embargo": ventana}


def validacion_fuera_de_periodo(resultado, cierres, fraccion=FRACCION_DENTRO):
    """Reconstruye la estadistica de cada valor por tramos independientes.

    Para cada valor listado calcula el rebote medio usando SOLO los episodios
    del primer tramo, y despues el rebote realmente observado en los episodios
    del segundo, que no han intervenido en el primero.
    """
    if not resultado or resultado.get("tabla") is None or resultado["tabla"].empty:
        return resultado
    if cierres is None or cierres.empty:
        return resultado

    ventana = int(resultado["ventana"])
    umbral = float(resultado["umbral"])
    limites = _tramos(cierres.index, ventana, fraccion)
    if not limites:
        return resultado

    filas = []
    # Un valor por fila, aunque figure varias veces en la relacion: su historial
    # no depende de en cual de sus caidas recientes nos fijemos, y duplicarlo
    # ponderaria dos veces el mismo dato en la correlacion entre tramos.
    for tk in dict.fromkeys(resultado["tabla"]["Ticker"]):
        if tk not in cierres.columns:
            continue
        serie_p = cierres[tk].dropna()
        if len(serie_p) < crib.MIN_SESIONES:
            continue
        serie_r = np.log(serie_p / serie_p.shift(1)).dropna()
        sigma = float(serie_r.std())
        if not sigma or not np.isfinite(sigma):
            continue

        # La sigma se estima en cada tramo con sus propios datos: usar la de
        # toda la serie para acotar el tramo de validacion seria filtrar
        # informacion del futuro hacia el pasado.
        r_dentro = serie_r[(serie_r.index >= limites["inicio_dentro"]) &
                           (serie_r.index <= limites["fin_dentro"])]
        sigma_dentro = float(r_dentro.std()) if len(r_dentro) > 30 else sigma

        _, dentro = crib.episodios_historicos(
            serie_r, serie_p, sigma_dentro, umbral, ventana,
            desde=limites["inicio_dentro"], hasta=limites["fin_dentro"])
        _, fuera = crib.episodios_historicos(
            serie_r, serie_p, sigma_dentro, umbral, ventana,
            desde=limites["inicio_fuera"], hasta=limites["fin_fuera"])

        if len(dentro) < MIN_EPISODIOS_TRAMO or len(fuera) < MIN_EPISODIOS_TRAMO:
            filas.append({"Ticker": tk, "Episodios dentro": len(dentro),
                          "Media dentro": np.nan, "Episodios fuera": len(fuera),
                          "Media fuera": np.nan, "Deterioro": np.nan,
                          "Comparable": False})
            continue

        m_dentro, m_fuera = float(dentro.mean()), float(fuera.mean())
        filas.append({"Ticker": tk,
                      "Episodios dentro": int(len(dentro)),
                      "Media dentro": m_dentro,
                      "Episodios fuera": int(len(fuera)),
                      "Media fuera": m_fuera,
                      "Deterioro": m_fuera - m_dentro,
                      "Comparable": True})

    if not filas:
        return resultado

    tabla = pd.DataFrame(filas)
    comparables = tabla[tabla["Comparable"]]

    # La cifra decisiva: si lo medido en el primer tramo no guarda relacion con
    # lo ocurrido en el segundo, la seleccion no anticipa nada.
    correlacion, p_corr, n_corr = np.nan, np.nan, int(len(comparables))
    if n_corr >= 4:
        c, p = stats.pearsonr(comparables["Media dentro"], comparables["Media fuera"])
        correlacion, p_corr = float(c), float(p)

    resumen = {
        "limites": limites,
        "valores": n_corr,
        "correlacion": correlacion,
        "p_correlacion": p_corr,
        "media_dentro": float(comparables["Media dentro"].mean()) if n_corr else np.nan,
        "media_fuera": float(comparables["Media fuera"].mean()) if n_corr else np.nan,
        "mantienen_signo": (float((comparables["Media fuera"] > 0).mean())
                            if n_corr else np.nan),
    }
    return {**resultado, "validacion": {"tabla": tabla, **resumen}}


# =============================================================================
#  VALIDACION CRUZADA PURGADA CON EMBARGO
# =============================================================================

def validacion_cruzada_purgada(cierres, tickers, umbral, ventana,
                               pliegues=PLIEGUES):
    """Rebote medio por pliegues disjuntos, con purga y embargo entre ellos.

    Una unica particion puede caer en un tramo atipico -el segundo tramo de una
    serie de cinco anios puede ser justo un mercado alcista- y dar una lectura
    enganosa en cualquiera de los dos sentidos. Repartir la muestra en varios
    pliegues y medir en cada uno indica si el comportamiento es estable o
    depende del trozo de historia que toque mirar.

    En cada pliegue se descarta un margen de `ventana` sesiones a cada lado
    para que ningun episodio tenga su horizonte dentro del tramo evaluado.
    """
    if cierres is None or cierres.empty or not tickers:
        return None
    # Sin duplicados: un valor repetido en la relacion aportaria sus episodios
    # dos veces al recuento de cada pliegue.
    tickers = list(dict.fromkeys(tickers))
    indice = cierres.index
    n = len(indice)
    if n < pliegues * (2 * ventana + 10):
        return None

    tamano = n // pliegues
    resultados = []
    for k in range(pliegues):
        ini = k * tamano
        fin = (k + 1) * tamano - 1 if k < pliegues - 1 else n - 1
        # Purga y embargo: se recorta el pliegue por ambos extremos
        ini_p = min(ini + ventana, fin)
        fin_p = max(fin - ventana, ini_p)
        if fin_p - ini_p < ventana + 5:
            continue

        acumulados = []
        for tk in tickers:
            if tk not in cierres.columns:
                continue
            serie_p = cierres[tk].dropna()
            if len(serie_p) < crib.MIN_SESIONES:
                continue
            serie_r = np.log(serie_p / serie_p.shift(1)).dropna()
            sigma = float(serie_r.std())
            if not sigma or not np.isfinite(sigma):
                continue
            _, ep = crib.episodios_historicos(
                serie_r, serie_p, sigma, umbral, ventana,
                desde=indice[ini_p], hasta=indice[fin_p])
            acumulados.extend(ep.tolist())

        if len(acumulados) >= MIN_EPISODIOS_TRAMO:
            a = np.array(acumulados, dtype=float)
            resultados.append({
                "Pliegue": k + 1,
                "Desde": indice[ini_p].date(),
                "Hasta": indice[fin_p].date(),
                "Episodios": int(len(a)),
                "Media": float(a.mean()),
                "% en positivo": float((a > 0).mean()),
            })

    if not resultados:
        return None
    tabla = pd.DataFrame(resultados)
    medias = tabla["Media"].to_numpy(dtype=float)
    return {
        "tabla": tabla,
        "pliegues": int(len(tabla)),
        "media": float(medias.mean()),
        "dispersion": float(medias.std(ddof=1)) if len(medias) > 1 else np.nan,
        "positivos": int((medias > 0).sum()),
        "ventana": ventana,
        "umbral": umbral,
    }
