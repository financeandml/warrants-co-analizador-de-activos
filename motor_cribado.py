"""Motor de CRIBADO del mercado estadounidense.

Busca en las 503 empresas del S&P 500 las que han sufrido una caida superior al
umbral de sigmas en la sesion en curso o en las ultimas sesiones, y las ordena
por el comportamiento historico del propio valor tras caidas comparables.

Por que el filtro NO puede mirar los proximos 15 dias
-----------------------------------------------------
La peticion natural es "quedate solo con las que suban en los proximos 15 dias".
Para una caida de HOY esos quince dias todavia no han ocurrido: filtrar por ellos
exigiria informacion futura. Es el sesgo de anticipacion, y contamina cualquier
resultado que se derive de el.

Lo que si se puede medir, y es lo que hace este modulo, es el historial DEL
PROPIO VALOR: de todas las veces que esa empresa cayo mas de N sigmas en el
pasado, en cuantas subio quince sesiones despues y cuanto de media. Eso es un
recuento sobre hechos consumados, no una prevision, y es el unico criterio que
permite ordenar la lista sin inventarse el futuro.

Coste
-----
Una pasada completa descarga cinco anios de cierres de las 503 empresas en unos
25 segundos y ocupa unos 5 MB. Se cachea en la capa de interfaz.
"""

import io
import urllib.request

import numpy as np
import pandas as pd
import yfinance as yf

CABECERA = {"User-Agent": "Mozilla/5.0 (Analizador de Activos)"}
URL_SP500 = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

VENTANA_REBOTE = 15          # sesiones posteriores que pide el analisis
MIN_SESIONES = 250           # historico minimo por valor para que cuente
MIN_CASOS_HISTORICOS = 5     # caidas previas minimas para dar la estadistica


def universo_sp500():
    """Composicion del S&P 500 con su sector, desde la fuente publica."""
    try:
        peticion = urllib.request.Request(URL_SP500, headers=CABECERA)
        html = urllib.request.urlopen(peticion, timeout=40).read().decode("utf-8")
        sp = pd.read_html(io.StringIO(html))[0]
    except Exception:
        return None
    columnas = ["Symbol", "Security", "GICS Sector"]
    alta = "Date added" if "Date added" in sp.columns else None
    sp = sp[columnas + ([alta] if alta else [])].copy()
    sp.columns = ["Ticker", "Empresa", "Sector"] + (["Alta"] if alta else [])
    # Yahoo usa guion donde la SEC usa punto (BRK.B -> BRK-B)
    sp["Ticker"] = sp["Ticker"].str.replace(".", "-", regex=False)
    if alta:
        sp["Alta"] = pd.to_datetime(sp["Alta"], errors="coerce")
    return sp


def deriva_composicion(universo, anios=5):
    """Cuanto se ha movido la composicion del indice en el periodo estudiado.

    El cribado calcula la estadistica historica sobre las 503 sociedades que
    integran el indice HOY, que no son las que lo integraban hace cinco anios.
    Eso introduce dos sesgos que actuan en la MISMA direccion:

      - Supervivencia: las expulsadas del indice no figuran en el calculo, y a
        una sociedad se la expulsa normalmente despues de hundirse. Los peores
        desenlaces posteriores a una caida extrema faltan de la muestra.
      - Inclusion: las incorporadas recientemente si figuran, con su historial
        previo completo, y a una sociedad se la incorpora despues de crecer.

    Ambos inflan el rebote medio. La composicion punto a punto del indice es un
    dato de pago, de modo que el sesgo no se puede eliminar; lo que si se puede
    es medir su tamanio y advertirlo. Devuelve None si la fuente no trae fechas.
    """
    if universo is None or "Alta" not in universo.columns:
        return None
    altas = pd.to_datetime(universo["Alta"], errors="coerce")
    if altas.notna().sum() == 0:
        return None
    # Timestamp.utcnow esta en retirada y desaparece en pandas 4.
    corte = pd.Timestamp.now("UTC").tz_localize(None) - pd.DateOffset(years=anios)
    recientes = int((altas >= corte).sum())
    total = int(len(universo))
    return {"anios": anios, "total": total, "recientes": recientes,
            "cuota": recientes / total if total else np.nan}


def descargar_universo(tickers, periodo="5y"):
    """Cierres ajustados de todo el universo en una sola llamada.

    Devuelve (cierres, ausentes). La segunda lista NO es decorativa: cuando el
    proveedor limita el numero de peticiones -y con 503 simbolos desde una IP
    compartida lo hace- yfinance no lanza ningun error, devuelve las columnas
    que no pudo traer llenas de nulos. El `dropna(axis=1)` las borraba y el
    cribado informaba de "180 sociedades examinadas" como si el universo fuese
    de 180, sin distinguir un mercado pequeno de una descarga cortada por la
    mitad. Quien lea la pantalla tiene que poder ver la diferencia.
    """
    pedidos = list(tickers)
    datos = yf.download(pedidos, period=periodo, auto_adjust=True,
                        progress=False, threads=True)
    if datos is None or datos.empty:
        return None, pedidos
    cierres = datos["Close"] if "Close" in datos else datos
    cierres = cierres.dropna(axis=1, how="all")
    ausentes = sorted(set(pedidos) - set(cierres.columns))
    return cierres, ausentes


def episodios_historicos(retornos, precios, sigma, umbral, ventana, excluir=None,
                         desde=None, hasta=None):
    """Episodios individuales: fecha de cada caida y su retorno posterior.

    Se separa del resumen estadistico porque los modulos de validacion, regimen
    y clasificacion por origen necesitan los episodios UNO A UNO, no su media.
    Calcularlos dos veces por caminos distintos acabaria dando cifras que no
    cuadran entre pantallas, que es peor que no darlas.

    `desde` y `hasta` acotan el periodo del que se toman los episodios, lo que
    permite construir muestras dentro y fuera de periodo sin duplicar codigo.
    """
    if sigma <= 0:
        return [], np.array([], dtype=float)
    corte = -umbral * sigma
    fechas_caida = retornos.index[retornos.values <= corte]
    posiciones = {f: i for i, f in enumerate(precios.index)}
    fechas, posteriores = [], []
    for fecha in fechas_caida:
        # Se excluye la caida que se esta evaluando, identificada por su FECHA.
        # Antes se descartaba la ultima de la lista por posicion, que no siempre
        # es la misma: al revisar varias sesiones atras se estaba eliminando el
        # episodio mas reciente en lugar del que se analiza.
        if excluir is not None and fecha == excluir:
            continue
        if desde is not None and fecha < desde:
            continue
        if hasta is not None and fecha > hasta:
            continue
        i = posiciones.get(fecha)
        if i is None or i + ventana >= len(precios):
            continue
        base, futuro = precios.iloc[i], precios.iloc[i + ventana]
        if np.isfinite(base) and base and np.isfinite(futuro):
            fechas.append(fecha)
            posteriores.append(futuro / base - 1)
    return fechas, np.array(posteriores, dtype=float)


def resumir_episodios(posteriores):
    """Resumen estadistico de un conjunto de episodios ya localizados."""
    a = np.asarray(posteriores, dtype=float)
    if len(a) < MIN_CASOS_HISTORICOS:
        return {"casos": int(len(a)), "suficiente": False,
                "media": np.nan, "mediana": np.nan, "positivos": np.nan,
                "peor": np.nan, "mejor": np.nan, "desviacion": np.nan}
    return {"casos": int(len(a)), "suficiente": True,
            "media": float(a.mean()), "mediana": float(np.median(a)),
            "positivos": float((a > 0).mean()),
            "peor": float(a.min()), "mejor": float(a.max()),
            "desviacion": float(a.std(ddof=1)) if len(a) > 1 else np.nan}


def _rebote_historico(retornos, precios, sigma, umbral, ventana, excluir=None):
    """Que hizo el precio las veces anteriores que cayo mas de `umbral` sigmas.

    La alineacion se hace por FECHA, no por posicion. La serie de retornos tiene
    un elemento menos que la de precios (el primer retorno no existe), asi que
    emparejarlas por indice numerico desplaza todo un dia: se tomaria como base
    el cierre ANTERIOR a la caida y la ventana de quince sesiones incluiria la
    propia caida. El efecto era sistematico y brutal: las 20 empresas del cribado
    daban media negativa, cuando lo que se estaba midiendo era el desplome mas
    lo que viniera despues.
    """
    if sigma <= 0 or len(precios) < MIN_SESIONES:
        return None
    fechas, posteriores = episodios_historicos(
        retornos, precios, sigma, umbral, ventana, excluir=excluir)
    resumen = resumir_episodios(posteriores)
    resumen["fechas"] = fechas
    resumen["retornos"] = posteriores
    return resumen


def cribar(cierres, umbral=2.0, ventana=VENTANA_REBOTE, sesiones_atras=1,
           universo=None, ausentes=None):
    """Localiza las caidas extremas recientes y les adjunta su historial.

    `sesiones_atras` = 1 significa solo la ultima sesion disponible, que durante
    el horario de mercado es la sesion en curso: Yahoo va actualizando la vela
    diaria en tiempo real.
    """
    if cierres is None or cierres.empty:
        return None

    retornos = np.log(cierres / cierres.shift(1))
    sigmas = retornos.std()
    fechas = list(cierres.index[-sesiones_atras:])

    nombres, sectores = {}, {}
    if universo is not None:
        nombres = dict(zip(universo["Ticker"], universo["Empresa"]))
        sectores = dict(zip(universo["Ticker"], universo["Sector"]))

    filas = []
    # Episodios uno a uno de cada valor listado. Los consumen los modulos
    # complementarios (validacion, regimen, origen) para no recalcular por su
    # cuenta lo que aqui ya se ha localizado.
    episodios = {}
    for fecha in fechas:
        fila_ret = retornos.loc[fecha]
        for tk in cierres.columns:
            r = fila_ret.get(tk, np.nan)
            s = sigmas.get(tk, np.nan)
            if not (np.isfinite(r) and np.isfinite(s)) or s <= 0:
                continue
            z = r / s
            if z > -umbral:
                continue
            serie_p = cierres[tk].dropna()
            serie_r = retornos[tk].dropna()
            if len(serie_p) < MIN_SESIONES:
                continue
            hist = _rebote_historico(serie_r, serie_p, s, umbral, ventana,
                                     excluir=fecha)
            if hist is None:
                continue
            # El cierre que corresponde a LA FECHA DE LA CAIDA, no el ultimo de
            # la serie: al revisar varias sesiones atras, mostrar el precio de
            # hoy para una caida de hace cuatro dias descuadraba hasta un 2%.
            cierre_del_dia = serie_p.get(fecha, np.nan)
            episodios[tk] = {"fechas": hist.get("fechas", []),
                             "retornos": hist.get("retornos", np.array([])),
                             "sigma": float(s), "fecha_actual": fecha}
            filas.append({
                "Ticker": tk,
                "Empresa": nombres.get(tk, tk),
                "Sector": sectores.get(tk, ""),
                "Fecha": fecha.date(),
                "Caída": float(np.expm1(r)),
                "Sigmas": float(z),
                "Sigma diaria": float(s),
                "Cierre ese día": float(cierre_del_dia) if np.isfinite(cierre_del_dia) else np.nan,
                "Precio actual": float(serie_p.iloc[-1]),
                "Casos previos": hist["casos"],
                "Estadística suficiente": hist["suficiente"],
                f"Media +{ventana}d": hist["media"],
                f"Mediana +{ventana}d": hist["mediana"],
                "% en positivo": hist["positivos"],
                "Peor caso": hist["peor"],
                "Mejor caso": hist["mejor"],
            })

    ausentes = list(ausentes or [])
    cobertura = {"analizados": len(cierres.columns),
                 "ausentes": ausentes,
                 "solicitados": len(cierres.columns) + len(ausentes),
                 "episodios": episodios}

    if not filas:
        return {"tabla": pd.DataFrame(), "fechas": fechas, "ventana": ventana,
                "umbral": umbral, **cobertura}

    tabla = pd.DataFrame(filas).sort_values("Sigmas")
    return {"tabla": tabla, "fechas": fechas, "ventana": ventana,
            "umbral": umbral, **cobertura}


def referencia_mercado(cierres, ventana=VENTANA_REBOTE):
    """Que hace el mercado a `ventana` sesiones desde un dia CUALQUIERA.

    Es la vara de medir imprescindible. Sin ella, un +0,9% de media tras una
    caida parece un buen dato, cuando el mercado entero rinde +0,85% partiendo
    de cualquier sesion al azar: la caida no habria aportado nada.
    """
    if cierres is None or cierres.empty:
        return None
    # Se usan TODOS los valores disponibles, no solo los que tienen el historico
    # completo. Exigir serie entera dejaba fuera 35 de las 503 (un 7%), y esas
    # son justo las incorporaciones recientes al indice: quedarse con las
    # supervivientes de cinco anios introduce sesgo sin ninguna necesidad.
    px = cierres
    if px.empty or len(px) <= ventana:
        return None
    fwd = (px.shift(-ventana) / px - 1).stack().dropna()
    if fwd.empty:
        return None
    return {"media": float(fwd.mean()), "mediana": float(fwd.median()),
            "positivos": float((fwd > 0).mean()), "observaciones": int(len(fwd)),
            "ventana": ventana}


def anadir_ventaja(resultado, referencia):
    """Diferencia entre el rebote historico del valor y el del mercado."""
    if not resultado or resultado["tabla"].empty or not referencia:
        return resultado
    t = resultado["tabla"].copy()
    col = f"Media +{resultado['ventana']}d"
    t["Ventaja sobre el mercado"] = t[col] - referencia["media"]
    t["Ventaja en aciertos"] = t["% en positivo"] - referencia["positivos"]
    return {**resultado, "tabla": t, "referencia": referencia}


def filtrar_por_historial(resultado, exigir_media_positiva=True,
                          minimo_positivos=0.50, exigir_suficiencia=True):
    """Conserva solo las que historicamente reaccionaron al alza tras caer.

    Es la traduccion honesta de "quedate con las que suben en los proximos 15
    dias": no se puede aplicar a los quince dias que aun no han pasado, pero si
    al historial de cada valor.
    """
    if not resultado or resultado["tabla"].empty:
        return resultado
    t = resultado["tabla"]
    col_media = f"Media +{resultado['ventana']}d"
    mascara = pd.Series(True, index=t.index)
    if exigir_suficiencia:
        mascara &= t["Estadística suficiente"]
    if exigir_media_positiva:
        mascara &= t[col_media] > 0
    if minimo_positivos is not None:
        mascara &= t["% en positivo"] >= minimo_positivos
    filtrada = t[mascara].sort_values(col_media, ascending=False)
    return {**resultado, "tabla": filtrada, "descartadas": int((~mascara).sum()),
            "tabla_completa": t}


# =============================================================================
#  NOTICIAS
# =============================================================================

def _campo(noticia, *rutas):
    """Lee un campo de la noticia sorteando los dos formatos que devuelve Yahoo."""
    base = noticia.get("content", noticia)
    for ruta in rutas:
        actual = base
        for paso in ruta.split("."):
            if isinstance(actual, dict):
                actual = actual.get(paso)
            else:
                actual = None
                break
        if actual:
            return actual
    return None


def noticias_de(tickers, por_ticker=5):
    """Titulares recientes de los valores indicados, ordenados por fecha."""
    filas = []
    for tk in tickers:
        try:
            crudas = yf.Ticker(tk).news or []
        except Exception:
            continue
        for n in crudas[:por_ticker]:
            titulo = _campo(n, "title")
            if not titulo:
                continue
            filas.append({
                "Ticker": tk,
                "Titular": titulo,
                "Medio": _campo(n, "provider.displayName") or "",
                "Fecha": _campo(n, "pubDate", "displayTime") or "",
                "Resumen": (_campo(n, "summary", "description") or "")[:400],
                "Enlace": _campo(n, "canonicalUrl.url", "clickThroughUrl.url") or "",
            })
    if not filas:
        return pd.DataFrame()
    tabla = pd.DataFrame(filas)
    tabla["Fecha"] = pd.to_datetime(tabla["Fecha"], errors="coerce", utc=True)
    return tabla.sort_values("Fecha", ascending=False, na_position="last")
