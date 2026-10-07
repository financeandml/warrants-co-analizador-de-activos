"""Motor de DESCOMPOSICION FACTORIAL.

Responde a una sola pregunta, que es la que plantearia un comite de riesgos:
lo que produce la estrategia, ¿es alfa o es una exposicion conocida con otro
nombre?

Comprar valores que acaban de desplomarse es, mecanicamente, cargarse de
reversion a corto plazo, de beta elevada y a menudo de value. Todas ellas son
primas documentadas desde hace decadas y accesibles por medios mucho mas
baratos. Si al descontarlas no queda nada, la estrategia no aporta nada propio;
si queda un residuo positivo y estadisticamente distinguible de cero, eso si es
suyo.

FUENTE
------
Biblioteca de datos de Kenneth French (Tuck School of Business, Dartmouth),
publica y gratuita. Se emplean los factores diarios:

    Mkt-RF   exceso de retorno del mercado
    SMB      tamano (pequenas menos grandes)
    HML      valor (caras menos baratas por valor contable)
    RMW      rentabilidad operativa
    CMA      politica de inversion
    Mom      momento a doce meses
    ST_Rev   reversion a corto plazo

El ultimo es el decisivo aqui: mide exactamente la prima de comprar lo que
acaba de caer. Omitirlo permitiria presentar como alfa lo que es la prima mas
elemental del asunto.

ERRORES ESTANDAR
----------------
Se emplean los de Newey-West. Al mantener cada posicion varias sesiones, los
retornos diarios de la cartera se solapan y estan autocorrelacionados; los
errores estandar ordinarios los subestiman y producen estadisticos t inflados,
que es la forma mas comun de anunciar un alfa que no existe. El numero de
retardos se fija en el horizonte de la estrategia.
"""

import io
import urllib.request
import zipfile

import numpy as np
import pandas as pd

BASE_FRENCH = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
CABECERA = {"User-Agent": "Mozilla/5.0 (Analizador de Activos)"}
TIEMPO_ESPERA = 60

FICHEROS = {
    "cinco": "F-F_Research_Data_5_Factors_2x3_daily_CSV.zip",
    "momento": "F-F_Momentum_Factor_daily_CSV.zip",
    "reversion": "F-F_ST_Reversal_Factor_daily_CSV.zip",
}

NOMBRES = {
    "Mkt-RF": "Mercado",
    "SMB": "Tamaño",
    "HML": "Valor",
    "RMW": "Rentabilidad",
    "CMA": "Inversión",
    "Mom": "Momento",
    "ST_Rev": "Reversión a corto",
}

EXPLICACION = {
    "Mkt-RF": "Exceso de retorno del conjunto del mercado sobre el activo sin riesgo.",
    "SMB": "Diferencia entre sociedades de pequeña y de gran capitalización.",
    "HML": "Diferencia entre sociedades baratas y caras por valor contable.",
    "RMW": "Diferencia por rentabilidad operativa entre sólidas y débiles.",
    "CMA": "Diferencia entre sociedades conservadoras y agresivas invirtiendo.",
    "Mom": "Continuidad de la tendencia de los doce meses previos.",
    "ST_Rev": "Prima de comprar lo que acaba de caer. Es la exposición natural "
              "de esta estrategia y la que primero hay que descontar.",
}

VENTANA_SIGMA = 252     # sesiones para estimar la volatilidad de cada valor


# =============================================================================
#  DESCARGA DE FACTORES
# =============================================================================

def _leer_zip(nombre):
    """Descarga y extrae el CSV diario, devolviendo su texto."""
    peticion = urllib.request.Request(BASE_FRENCH + nombre, headers=CABECERA)
    with urllib.request.urlopen(peticion, timeout=TIEMPO_ESPERA) as r:
        bruto = r.read()
    z = zipfile.ZipFile(io.BytesIO(bruto))
    return z.read(z.namelist()[0]).decode("latin-1")


def _parsear(texto):
    """Convierte el CSV de French en una tabla indexada por fecha.

    El fichero lleva varias lineas de encabezado en prosa y, en las series
    mensuales, un segundo bloque anual al final. Se conservan unicamente las
    filas cuyo primer campo es una fecha de ocho digitos.
    """
    lineas = texto.splitlines()
    cabecera, inicio = None, None
    for i, linea in enumerate(lineas):
        primero = linea.split(",")[0].strip()
        if len(primero) == 8 and primero.isdigit():
            inicio = i
            cabecera = [c.strip() for c in lineas[i - 1].split(",")]
            break
    if inicio is None:
        return None

    filas = []
    for linea in lineas[inicio:]:
        partes = [p.strip() for p in linea.split(",")]
        if not partes or len(partes[0]) != 8 or not partes[0].isdigit():
            continue
        if len(partes) != len(cabecera):
            continue
        filas.append(partes)
    if not filas:
        return None

    columnas = ["fecha"] + [c for c in cabecera[1:]]
    df = pd.DataFrame(filas, columns=columnas)
    df["fecha"] = pd.to_datetime(df["fecha"], format="%Y%m%d")
    df = df.set_index("fecha").astype(float)
    # French publica en puntos porcentuales; aqui todo se maneja en tanto por uno
    df = df / 100.0
    # -99.99 y -999 son sus codigos de dato ausente
    return df.mask(df <= -0.99)


def descargar_factores():
    """Los siete factores diarios en una sola tabla, mas el activo sin riesgo.

    Devuelve None si la fuente no responde: el modulo es complementario y su
    ausencia no debe impedir que el cribado funcione.
    """
    try:
        cinco = _parsear(_leer_zip(FICHEROS["cinco"]))
        momento = _parsear(_leer_zip(FICHEROS["momento"]))
        reversion = _parsear(_leer_zip(FICHEROS["reversion"]))
    except Exception:
        return None
    if cinco is None:
        return None

    tabla = cinco
    for extra in (momento, reversion):
        if extra is not None:
            tabla = tabla.join(extra, how="left")
    return tabla.dropna(how="all")


# =============================================================================
#  SERIE DE RETORNOS DE LA ESTRATEGIA
# =============================================================================

def serie_estrategia(cierres, umbral=2.0, ventana=15):
    """Retorno diario de una cartera que compra lo que se desploma y lo mantiene.

    Reglas, deliberadamente simples para que no haya nada que ajustar:
      - Cada sesion entran todos los valores cuyo retorno cae por debajo de
        `umbral` desviaciones tipicas de SU PROPIA volatilidad reciente.
      - Se compra al cierre de la sesion de la caida, de modo que el primer
        retorno que se cobra es el de la sesion siguiente. Sin esta cautela se
        estaria imputando a la estrategia el propio desplome.
      - Cada posicion se mantiene `ventana` sesiones y todas pesan lo mismo.

    La volatilidad se estima con una ventana movil de un anio DESPLAZADA una
    sesion: usar la desviacion de toda la serie para decidir que fue extremo en
    2022 seria emplear informacion que entonces no existia.
    """
    if cierres is None or cierres.empty:
        return None
    precios = cierres.sort_index()
    retornos = precios.pct_change()
    if len(retornos) < VENTANA_SIGMA + ventana + 20:
        return None

    sigma = retornos.rolling(VENTANA_SIGMA, min_periods=120).std().shift(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        z = retornos / sigma
    senal = (z <= -umbral) & sigma.notna()

    # Una posicion abierta en t-k (1 <= k <= ventana) sigue viva en t
    abierta = pd.DataFrame(False, index=precios.index, columns=precios.columns)
    for k in range(1, ventana + 1):
        abierta |= senal.shift(k).fillna(False).astype(bool)

    validos = retornos.notna() & abierta
    n_abiertas = validos.sum(axis=1)
    suma = retornos.where(validos).sum(axis=1, skipna=True)
    cartera = (suma / n_abiertas).where(n_abiertas > 0)

    serie = cartera.dropna()
    if len(serie) < 60:
        return None
    return {"retornos": serie, "posiciones": n_abiertas.reindex(serie.index),
            "entradas": int(senal.to_numpy().sum()),
            "umbral": umbral, "ventana": ventana,
            "sesiones_invertido": int((n_abiertas.reindex(serie.index) > 0).sum())}


# =============================================================================
#  REGRESION CON ERRORES DE NEWEY-WEST
# =============================================================================

def _newey_west(X, residuos, retardos):
    """Matriz de covarianzas robusta a heterocedasticidad y autocorrelacion.

    Nucleo de Bartlett: los retardos pesan cada vez menos hasta anularse en
    `retardos`+1, lo que garantiza que la matriz resultante sea semidefinida
    positiva.
    """
    n, k = X.shape
    XtX_inv = np.linalg.pinv(X.T @ X)
    u = X * residuos[:, None]

    S = u.T @ u
    for l in range(1, retardos + 1):
        peso = 1.0 - l / (retardos + 1.0)
        G = u[l:].T @ u[:-l]
        S += peso * (G + G.T)

    cov = XtX_inv @ S @ XtX_inv
    # Correccion de muestra finita, como en la practica habitual
    return cov * n / max(n - k, 1)


def regresion_factorial(serie, factores, retardos=None):
    """Descompone la serie de la estrategia en los factores conocidos.

    Devuelve el alfa anualizado con su estadistico t robusto y la carga sobre
    cada factor. Un alfa positivo cuyo t no llegue a 2 no sostiene la
    afirmacion de que exista rendimiento propio.
    """
    if serie is None or factores is None:
        return None
    retornos = serie["retornos"] if isinstance(serie, dict) else serie
    ventana = serie.get("ventana", 15) if isinstance(serie, dict) else 15

    columnas = [c for c in ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "Mom", "ST_Rev"]
                if c in factores.columns]
    if not columnas or "RF" not in factores.columns:
        return None

    junto = pd.concat([retornos.rename("cartera"),
                       factores[columnas + ["RF"]]], axis=1, join="inner").dropna()
    if len(junto) < 120:
        return None

    y = (junto["cartera"] - junto["RF"]).to_numpy(dtype=float)
    Xf = junto[columnas].to_numpy(dtype=float)
    X = np.column_stack([np.ones(len(Xf)), Xf])

    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    ajuste = X @ coef
    residuos = y - ajuste

    if retardos is None:
        retardos = max(int(ventana), 5)
    retardos = min(retardos, max(len(y) // 4, 1))
    cov = _newey_west(X, residuos, retardos)
    errores = np.sqrt(np.maximum(np.diag(cov), 0))

    with np.errstate(invalid="ignore", divide="ignore"):
        t = np.where(errores > 0, coef / errores, np.nan)

    sc = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - float(np.sum(residuos ** 2)) / sc if sc > 0 else np.nan
    k = X.shape[1] - 1
    r2_aj = 1 - (1 - r2) * (len(y) - 1) / max(len(y) - k - 1, 1) if np.isfinite(r2) else np.nan

    cargas = pd.DataFrame({
        "Factor": [NOMBRES.get(c, c) for c in columnas],
        "Clave": columnas,
        "Carga": coef[1:],
        "t": t[1:],
        "Significativa": np.abs(t[1:]) >= 2.0,
        "Descripción": [EXPLICACION.get(c, "") for c in columnas],
    })

    # Retorno bruto de la estrategia frente al que explican los factores
    media_diaria = float(y.mean())
    explicado = float((Xf @ coef[1:]).mean())

    return {
        "alfa_diario": float(coef[0]),
        "alfa_anual": float(coef[0]) * 252,
        "t_alfa": float(t[0]),
        "significativo": bool(abs(t[0]) >= 2.0),
        "cargas": cargas,
        "r2": r2,
        "r2_ajustado": r2_aj,
        "observaciones": int(len(y)),
        "retardos": int(retardos),
        "desde": junto.index[0],
        "hasta": junto.index[-1],
        "exceso_diario": media_diaria,
        "exceso_anual": media_diaria * 252,
        "explicado_anual": explicado * 252,
        "factores": columnas,
    }


def resumen_legible(descomposicion):
    """Traduce el resultado a una frase que se pueda leer sin ser econometrista."""
    if not descomposicion:
        return ""
    a = descomposicion["alfa_anual"]
    t = descomposicion["t_alfa"]
    if not np.isfinite(t):
        return "El contraste del alfa no ha podido calcularse."
    if abs(t) < 2:
        return (
            f"El rendimiento de la estrategia queda explicado por las primas "
            f"conocidas. El residuo anualizado es de {a:+.2%}, pero su "
            f"estadístico t es {t:.2f}: por debajo de 2 no se puede afirmar "
            f"que sea distinto de cero. En términos prácticos, no hay "
            f"rendimiento propio que no se obtenga ya por vías más baratas."
        )
    if a > 0:
        return (
            f"Descontadas las primas conocidas queda un residuo anualizado de "
            f"{a:+.2%} con estadístico t de {t:.2f}. Al superar el umbral "
            f"convencional de 2, el residuo es estadísticamente distinguible "
            f"de cero en el periodo examinado."
        )
    return (
        f"Descontadas las primas conocidas, el residuo anualizado es negativo "
        f"({a:+.2%}, t = {t:.2f}): la estrategia rinde menos de lo que "
        f"corresponderia a las exposiciones que asume."
    )
