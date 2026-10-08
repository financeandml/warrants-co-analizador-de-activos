"""RECOPILACION DE DATOS para el informe en PDF.

Llama a todos los motores de la aplicacion y devuelve un unico diccionario con
todo lo necesario para maquetar el documento. La maquetacion vive en
motor_informe.py y no consulta nada por su cuenta: asi el papel dice
exactamente lo mismo que la pantalla, que es el requisito esencial de un
documento que se imprime y se archiva.

Cada consulta va protegida de forma individual. Si una fuente no responde, ese
apartado lo hace constar en el papel y el resto del informe se genera igual; el
fallo queda ademas anotado en la relacion de incidencias que cierra el
documento. Un informe al que le falta un apartado sin avisar es peor que uno
que declara lo que no ha podido obtener.
"""

import numpy as np
import pandas as pd

import motor_analisis as ma


def _sin_zona(indice):
    """Indice de fechas comparable: sin zona horaria y a medianoche.

    Los dos caminos de descarga de la aplicacion no devuelven el mismo formato.
    `yf.Ticker.history` entrega el indice con la zona del mercado y `yf.download`
    lo entrega sin zona, de modo que cualquier operacion que empareje ambas
    series por fecha -reindex, join, intersection- devuelve vacio en silencio.
    """
    idx = pd.DatetimeIndex(indice)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    return idx.normalize()


def _alinear(serie, indice_destino):
    """Reindexa una serie sobre otro calendario igualando antes el formato."""
    copia = serie.copy()
    copia.index = _sin_zona(copia.index)
    destino = _sin_zona(indice_destino)
    reindexada = copia.reindex(destino)
    reindexada.index = indice_destino
    return reindexada


class Recolector:
    """Ejecuta consultas dejando constancia de las que fallan."""

    def __init__(self):
        self.incidencias = []

    def __call__(self, funcion, *args, **kwargs):
        try:
            return funcion(*args, **kwargs)
        except Exception as e:
            self.incidencias.append(
                f"{getattr(funcion, '__name__', 'consulta')}: "
                f"{type(e).__name__}: {str(e)[:120]}")
            return None


# =============================================================================
#  APARTADO 09 · SELECCION DE VALORES APLICADA AL ACTIVO
# =============================================================================

def datos_seleccion(pedir, ticker, hist, umbral, ventana):
    """Aplica al activo estudiado el aparato completo del cribado del indice."""
    import motor_cribado as crib
    import motor_origen as ori
    import motor_regimen as reg
    import motor_validacion as val

    universo = pedir(crib.universo_sp500)
    if universo is None:
        return None
    descarga = pedir(crib.descargar_universo, list(universo["Ticker"]))
    if not descarga or descarga[0] is None or descarga[0].empty:
        return None
    cierres, ausentes = descarga

    fuera = ticker not in cierres.columns
    if fuera:
        # El activo no pertenece al indice. Se incorpora su serie para poder
        # calcular sus episodios, conservando el universo como referencia
        # externa de mercado y de sector.
        #
        # Las dos series NO comparten formato de fecha: yf.Ticker.history
        # devuelve el indice con zona horaria de Nueva York y yf.download lo
        # devuelve sin zona. Reindexar una sobre otra sin igualarlas antes
        # casaba CERO fechas y el apartado desaparecia del informe sin que se
        # registrase error alguno: el PDF de Ichor salia con el apartado nueve
        # diciendo que el activo no pertenece al indice, cuando el problema era
        # de formato de fecha.
        serie = _alinear(hist["Close"], cierres.index)
        validas = int(serie.dropna().shape[0])
        if validas < crib.MIN_SESIONES:
            pedir.incidencias.append(
                f"seleccion de valores: la serie de {ticker} solo casa en "
                f"{validas} sesiones con el calendario del indice, por debajo "
                f"del mínimo de {crib.MIN_SESIONES}")
            return None
        cierres = cierres.copy()
        cierres[ticker] = serie

    precios = cierres[ticker].dropna()
    retornos = np.log(precios / precios.shift(1)).dropna()
    sigma = float(retornos.std()) if len(retornos) > 2 else 0.0
    if not sigma or not np.isfinite(sigma):
        return None

    fechas, episodios = crib.episodios_historicos(
        retornos, precios, sigma, umbral, ventana)
    resumen = crib.resumir_episodios(episodios)
    referencia = pedir(crib.referencia_mercado, cierres, ventana) or {}
    ref_media = referencia.get("media")

    salida = {
        "umbral": umbral, "ventana": ventana, "sigma": sigma,
        "casos": resumen["casos"], "media": resumen["media"],
        "mediana": resumen["mediana"], "positivos": resumen["positivos"],
        "peor": resumen["peor"], "mejor": resumen["mejor"],
        "episodios": episodios, "fechas": fechas,
        "referencia": ref_media,
        "ventaja": (resumen["media"] - ref_media
                    if ref_media is not None and np.isfinite(resumen["media"])
                    else np.nan),
        "fuera_del_indice": fuera,
        "ausentes": len(ausentes or []),
        "en_relacion": False,
    }

    # --- Contraste multiple sobre la relacion de la sesion analizada
    cribado = pedir(crib.cribar, cierres, umbral, ventana, 1, universo, ausentes)
    contraste = {"p": None, "q": None, "resiste": None}
    if cribado:
        cribado = crib.anadir_ventaja(cribado, referencia or None)
        cribado = val.contraste_multiple(cribado, referencia or None)
        c = cribado.get("contraste") or {}
        tabla = cribado.get("tabla")
        fila = None
        if tabla is not None and not tabla.empty and "Ticker" in tabla:
            coincide = tabla[tabla["Ticker"] == ticker]
            fila = coincide if len(coincide) else None
        salida["en_relacion"] = fila is not None
        contraste.update({
            "contrastes": c.get("contrastes"),
            "supervivientes": c.get("supervivientes"),
            "esperados_por_azar": c.get("esperados_por_azar"),
        })
        if fila is not None:
            contraste["p"] = (float(fila["p"].iloc[0])
                              if pd.notna(fila["p"].iloc[0]) else None)
            contraste["q"] = (float(fila["q"].iloc[0])
                              if pd.notna(fila["q"].iloc[0]) else None)
            contraste["resiste"] = bool(fila["Supera el contraste"].iloc[0])
    # Si el activo no ha caido en la ultima sesion no figura en la relacion,
    # pero su historial se contrasta igualmente contra la referencia.
    if contraste["p"] is None and ref_media is not None:
        contraste["p"] = val._p_valor(episodios, ref_media)
    salida["contraste"] = contraste

    # --- Validacion dentro y fuera de periodo
    limites = val._tramos(cierres.index, ventana)
    if limites:
        r_dentro = retornos[(retornos.index >= limites["inicio_dentro"]) &
                            (retornos.index <= limites["fin_dentro"])]
        s_dentro = float(r_dentro.std()) if len(r_dentro) > 30 else sigma
        _, dentro = crib.episodios_historicos(
            retornos, precios, s_dentro, umbral, ventana,
            desde=limites["inicio_dentro"], hasta=limites["fin_dentro"])
        _, despues = crib.episodios_historicos(
            retornos, precios, s_dentro, umbral, ventana,
            desde=limites["inicio_fuera"], hasta=limites["fin_fuera"])
        comparable = (len(dentro) >= val.MIN_EPISODIOS_TRAMO
                      and len(despues) >= val.MIN_EPISODIOS_TRAMO)
        salida["validacion"] = {
            "comparable": comparable,
            "n_dentro": int(len(dentro)), "n_fuera": int(len(despues)),
            "media_dentro": float(dentro.mean()) if len(dentro) else np.nan,
            "media_fuera": float(despues.mean()) if len(despues) else np.nan,
            "deterioro": (float(despues.mean() - dentro.mean())
                          if comparable else np.nan),
            "inicio_dentro": limites["inicio_dentro"].date(),
            "fin_dentro": limites["fin_dentro"].date(),
            "inicio_fuera": limites["inicio_fuera"].date(),
            "fin_fuera": limites["fin_fuera"].date(),
            "purga": limites["purga"],
        }
    salida["cruzada"] = pedir(val.validacion_cruzada_purgada, cierres,
                              [ticker], umbral, ventana)
    salida["deriva"] = pedir(crib.deriva_composicion, universo)

    # --- Regimen del valor y de su sector
    sectores = {}
    if "Sector" in universo.columns:
        sectores = dict(zip(universo["Ticker"], universo["Sector"]))
    fecha_ep = fechas[-1] if len(fechas) else None
    r = pedir(reg.regimen_de, ticker, cierres, universo,
              sectores.get(ticker), fecha_ep)
    if r:
        cond = pedir(reg.rebote_por_regimen, ticker, cierres, umbral, ventana, r)
        salida["regimen"] = {
            "estado": r.get("estado"), "percentil": r.get("percentil"),
            "estado_sector": r.get("estado_sector"),
            "percentil_sector": r.get("percentil_sector"),
            "desglose": cond["tabla"] if cond else None,
        }

    # --- Descomposicion factorial de la estrategia
    # Es analisis de universo, no del valor concreto, pero forma parte del
    # apartado en pantalla y responde a la pregunta que un comite plantearia
    # antes que ninguna otra: si lo que produce la estrategia es rendimiento
    # propio o primas conocidas con otro nombre.
    import motor_factores as fac
    serie_est = pedir(fac.serie_estrategia, cierres, umbral, ventana)
    factores = pedir(fac.descargar_factores)
    if serie_est and factores is not None:
        d = pedir(fac.regresion_factorial, serie_est, factores)
        if d:
            salida["factorial"] = {
                "alfa_anual": d["alfa_anual"], "t_alfa": d["t_alfa"],
                "exceso_anual": d["exceso_anual"],
                "explicado_anual": d["explicado_anual"],
                "r2_ajustado": d["r2_ajustado"], "cargas": d["cargas"],
                "observaciones": d["observaciones"], "retardos": d["retardos"],
                "desde": d["desde"].date(), "hasta": d["hasta"].date(),
                "entradas": serie_est["entradas"],
                "lectura": fac.resumen_legible(d),
                "significativo": d["significativo"],
            }

    # --- Origen de la caida y desenlace por categoria
    muestra = ori.muestra_para_cobertura(universo, [ticker], 40)
    fechas_res = pedir(ori.fechas_resultados, muestra) or {}
    if fechas_res:
        clas = pedir(ori.clasificar_universo, cierres, universo, umbral,
                     fechas_res)
        des = ori.desenlace_por_categoria(clas) if clas else None
        noticias = pedir(crib.noticias_de, [ticker], 5)
        registros = (noticias.to_dict("records")
                     if isinstance(noticias, pd.DataFrame) and not noticias.empty
                     else [])
        actual = None
        if fecha_ep is not None:
            actual = pedir(ori.origen_actual, ticker, fecha_ep, cierres,
                           universo, registros, fechas_res.get(ticker))
        salida["origen"] = {
            "categoria": (actual or {}).get("categoria"),
            "descripcion": (actual or {}).get("descripcion"),
            "retorno_indice": (actual or {}).get("retorno_indice"),
            "retorno_sector": (actual or {}).get("retorno_sector"),
            "motivo_prensa": (actual or {}).get("motivo_prensa"),
            "titulares": (actual or {}).get("titulares"),
            "desenlace": des["tabla"] if des else None,
            "horizontes": des["horizontes"] if des else list(ori.HORIZONTES),
            "valores_examinados": des["valores_examinados"] if des else 0,
        }
    return salida


# =============================================================================
#  APARTADO 10 · OPCIONES Y MICROESTRUCTURA
# =============================================================================

def datos_mercado(pedir, ticker):
    import motor_mercado as mrk
    cadena = pedir(mrk.cadena_opciones, ticker)
    salida = {"cadena": cadena}
    if cadena:
        salida["movimiento"] = pedir(mrk.movimiento_implicito, cadena)
        salida["estructura"] = pedir(mrk.estructura_temporal, cadena)
        salida["sonrisa"] = pedir(mrk.sonrisa_volatilidad, cadena)
        salida["sesgo"] = pedir(mrk.sesgo, cadena)
        salida["concentracion"] = pedir(mrk.concentracion_interes, cadena)
    intra = pedir(mrk.intradia, ticker)
    salida["intradia"] = intra
    if intra is not None and not intra.empty:
        salida["calidad"] = pedir(mrk.calidad_del_dia, intra)
        salida["sesiones"] = pedir(mrk.resumen_sesiones, intra)
        salida["perfil"] = pedir(mrk.perfil_volumen_precio, intra)
    return salida


# =============================================================================
#  APARTADOS 12 y 13 · FUNDAMENTALES Y SEGMENTOS
# =============================================================================

def datos_fundamentales(pedir, ticker):
    import motor_fundamentales as mf
    cik = pedir(mf.mapa_ticker_cik)
    # Distinguir "la SEC no responde" de "el emisor no presenta cuentas ahi".
    # Son cosas muy distintas y confundirlas acusa de no cotizar en Estados
    # Unidos a companias que llevan decadas presentando cuentas.
    if not cik and mf.ULTIMO_FALLO_SEC:
        pedir.incidencias.append(f"SEC EDGAR: {mf.ULTIMO_FALLO_SEC}")
        return {"no_disponible": True,
                "motivo": f"No ha sido posible consultar SEC EDGAR. "
                          f"{mf.ULTIMO_FALLO_SEC} El emisor puede presentar "
                          f"cuentas con normalidad: se trata de un problema de "
                          f"acceso a la fuente, no de cobertura."}
    if not cik or ticker.upper() not in cik:
        return {"no_disponible": True,
                "motivo": "No se ha localizado al emisor en el registro de SEC "
                          "EDGAR. La cobertura de este apartado se limita a "
                          "sociedades que presentan cuentas ante el regulador "
                          "estadounidense."}
    codigo = cik[ticker.upper()]
    hechos = pedir(mf.companyfacts, codigo)
    estados = pedir(mf.estados_financieros, ticker)
    if not estados:
        return {"no_disponible": True,
                "motivo": "El proveedor no ha devuelto estados financieros "
                          "utilizables para este emisor."}

    clase = pedir(mf.clasificar_negocio, ticker) or {}
    es_fin = bool(clase.get("es_financiera"))

    # La reconciliacion entrega el numero de acciones y su procedencia, que son
    # justo lo que necesitan Altman y los multiplos. Se calcula antes que ellos.
    rec = pedir(mf.reconciliar, ticker, estados, hechos) or {}
    acciones = rec.get("acciones")
    precio = pedir(_ultimo_precio, ticker)
    capitalizacion = (float(precio) * float(acciones)
                      if precio and acciones and np.isfinite(precio)
                      and np.isfinite(acciones) else None)

    salida = {
        "es_financiera": es_fin,
        "clasificacion": clase,
        "precio": precio,
        "acciones": acciones,
        "capitalizacion": capitalizacion,
        "resultados": estados.get("resultados"),
        "balance": estados.get("balance"),
        "flujo": estados.get("flujo"),
        "resultados_trim": estados.get("resultados_trim"),
        "piotroski": pedir(mf.piotroski_f, estados),
        "altman": (pedir(mf.altman_z, estados, capitalizacion,
                         es_financiera=es_fin) if capitalizacion else None),
        "beneish": pedir(mf.beneish_m, estados, es_financiera=es_fin),
        "calidad": pedir(mf.calidad_beneficio, estados, es_financiera=es_fin),
        "ratios": pedir(mf.retornos_capital, estados, es_financiera=es_fin),
        "solvencia": pedir(mf.solvencia, estados),
        "circulante": pedir(mf.capital_circulante, estados),
        "apalancamiento": pedir(mf.evolucion_apalancamiento, estados),
        "crecimiento": pedir(mf.crecimiento_margenes, estados),
        "multiplos": (pedir(mf.multiplos, ticker, estados, precio, acciones)
                      if precio and acciones else None),
        "reconciliacion": rec,
        "cobertura": pedir(mf.tabla_cobertura),
        # Bloques graficos del apartado, que en pantalla son once figuras
        "composicion_balance": pedir(mf.composicion_balance, estados),
        "cascada": pedir(mf.cascada_resultados, estados),
        "puente_caja": pedir(mf.puente_flujo_caja, estados),
        "beneficio_caja": pedir(mf.beneficio_frente_a_caja, estados),
        "consenso": pedir(mf.consenso, ticker),
        "insiders": pedir(mf.insiders, ticker),
        "asignacion": (pedir(mf.asignacion_capital, estados, precio)
                       if precio else None),
    }
    # Descuento de flujos inverso: que crecimiento habria que suponer para
    # justificar la capitalizacion actual. Necesita el flujo libre y la deuda
    # neta, que los devuelve el bloque de solvencia.
    sol = salida.get("solvencia")
    if capitalizacion and isinstance(sol, dict) and sol.get("fcf"):
        salida["dcf"] = pedir(mf.dcf_inverso, capitalizacion, sol["fcf"],
                              deuda_neta=sol.get("deuda_neta") or 0.0)
    return salida


def _ultimo_precio(ticker):
    """Ultimo cierre disponible, para capitalizacion y multiplos."""
    serie = ma.descargar_historico(ticker, "1mo")
    if serie is None or serie.empty:
        return None
    return float(serie["Close"].dropna().iloc[-1])


def datos_segmentos(pedir, ticker):
    import motor_fundamentales as mf
    import motor_segmentos as ms
    cik = pedir(mf.mapa_ticker_cik)
    if not cik or ticker.upper() not in cik:
        return {"no_disponible": True,
                "motivo": "Emisor no localizado en el registro de SEC EDGAR."}
    analisis = pedir(ms.analizar_segmentos, cik[ticker.upper()])
    if not analisis:
        return {"no_disponible": True,
                "motivo": "No se ha localizado un desglose por segmentos "
                          "utilizable en el último expediente presentado."}
    return {
        "negocio": pedir(ms.desglose, analisis, "negocio"),
        "producto": pedir(ms.desglose, analisis, "producto"),
        "geografia": pedir(ms.tabla_geografica, analisis),
        "margenes": pedir(ms.margenes_por_segmento, analisis),
        "evolucion": pedir(ms.evolucion_bloques, analisis, "negocio"),
        "aviso": analisis.get("aviso") if isinstance(analisis, dict) else None,
    }


# =============================================================================
#  APARTADO 11 · COMPARATIVA
# =============================================================================

def datos_comparativa(pedir, ticker, referencia, divisa):
    if not referencia or referencia == ticker:
        return None
    info_b = pedir(ma.info_ticker, referencia)
    if info_b is None:
        return None
    par = pedir(ma.descargar_par, ticker, referencia, ma.FECHA_INICIO_PERF)
    # La guarda comprueba los NOMBRES de las columnas, no cuantas hay. Contar
    # no basta: cuando el proveedor limita las peticiones -y durante la
    # generacion del informe se le piden las 503 del indice, la cadena de
    # opciones y el intradia- devuelve el marco sin la columna del activo, y
    # el `par[ticker]` de la linea siguiente reventaba con KeyError. Ademas se
    # evaluaba fuera del recolector, de modo que el fallo escapaba al control
    # de incidencias y tumbaba el informe entero por un apartado.
    if par is None or par.empty:
        return None
    faltan = [c for c in (ticker, referencia) if c not in par.columns]
    if faltan:
        pedir.incidencias.append(
            f"comparativa: el proveedor no ha devuelto la serie de "
            f"{', '.join(faltan)}; el apartado no puede calcularse")
        return None
    for t in (ticker, referencia):
        diag = ma.diagnostico_cierres(par[t])
        if diag:
            pedir.incidencias.append("comparativa: " + ma.texto_cierres_no_positivos(diag, t))
    a = pedir(ma.analizar_performance_profesional, par[ticker])
    b = pedir(ma.analizar_performance_profesional, par[referencia])
    if not a or not b:
        return None

    ra = par[ticker].pct_change().dropna()
    rb = par[referencia].pct_change().dropna()
    comun = ra.index.intersection(rb.index)
    correl = beta = np.nan
    if len(comun) > 30:
        x, y = rb.loc[comun].to_numpy(), ra.loc[comun].to_numpy()
        correl = float(np.corrcoef(x, y)[0, 1])
        varianza = float(np.var(x))
        beta = float(np.cov(y, x)[0, 1] / varianza) if varianza else np.nan

    aviso = None
    moneda_b = info_b[1] if len(info_b) > 1 else None
    if moneda_b and divisa and moneda_b != divisa:
        aviso = (f"{ticker} cotiza en {divisa} y {referencia} en {moneda_b}. Las "
                 f"series no se convierten a una divisa común: la diferencia de "
                 f"rentabilidad entre ambas recoge también la variación del tipo "
                 f"de cambio del periodo, y los ratios se calculan con una única "
                 f"tasa sin riesgo.")
    return {"stats_a": a, "stats_b": b, "correlacion": correl, "beta": beta,
            "sesiones": int(len(comun)), "desde": par.index[0].date(),
            "aviso_divisa": aviso}


# =============================================================================
#  RECOPILACION COMPLETA
# =============================================================================

def recopilar(ticker, periodo="5y", confianza=99.0, umbral_sigmas=2.0,
              ventana_rebote=15, referencia="SPY", n_sim=10000,
              intervalo="1d", periodo_grafico="1y",
              incluir_seleccion=True, incluir_fundamentales=True):
    """Reune todo lo que el informe necesita. Devuelve un diccionario."""
    import motor_grafico as gr

    pedir = Recolector()

    info = ma.info_ticker(ticker)
    if info is None:
        raise ValueError(f"El proveedor no devuelve datos para {ticker}.")
    nombre, divisa = info

    hist = ma.descargar_historico(ticker, periodo)
    if hist is None or hist.empty:
        raise ValueError(f"Sin histórico de precios para {ticker}.")
    # El mismo aviso que la cabecera de la pantalla, con el mismo texto.
    cierres_no_positivos = hist.attrs.get("cierres_no_positivos")
    if cierres_no_positivos:
        pedir.incidencias.append(ma.texto_cierres_no_positivos(cierres_no_positivos, ticker))

    retornos = hist["Return"].dropna()
    riesgo_bruto = pedir(ma.calcular_metricas_riesgo, retornos, confianza / 100)
    riesgo = None
    if riesgo_bruto is not None and len(riesgo_bruto) == 3:
        riesgo = {"var_hist": float(riesgo_bruto[0]),
                  "var_param": float(riesgo_bruto[1]),
                  "cvar": float(riesgo_bruto[2])}

    suf = pedir(ma.suficiencia, len(retornos), confianza)
    alternativas = None
    if suf and not suf.get("todo_suficiente"):
        alternativas = pedir(ma.listados_alternativos, ticker, nombre)

    S0 = float(hist["Close"].dropna().iloc[-1])
    # sigma_anualizada espera la serie de PRECIOS y calcula ella los retornos.
    # Pasarle los log-retornos ya calculados devuelve NaN en silencio, y ese
    # NaN se propaga a las diez mil trayectorias sin que nada proteste hasta
    # que el histograma final revienta.
    sigma = pedir(ma.sigma_anualizada, hist["Close"])
    sim = (pedir(ma.monte_carlo, S0, sigma, n_sim=n_sim)
           if sigma and np.isfinite(sigma) else None)

    velas = pedir(gr.velas, ticker, intervalo, periodo_grafico, True)
    earnings = pedir(ma.analizar_earnings, ticker, hist)

    datos = {
        "ticker": ticker, "nombre": nombre, "divisa": divisa,
        "periodo": periodo, "confianza": confianza, "n_sim": n_sim,
        "umbral_sigmas": umbral_sigmas, "ventana_rebote": ventana_rebote,
        "referencia": referencia, "intervalo": intervalo,
        "periodo_grafico": periodo_grafico,
        "hist": hist, "S0": S0, "sigma": sigma,
        "situacion": pedir(ma.situacion_actual, hist, confianza),
        "riesgo": riesgo, "suficiencia": suf, "alternativas": alternativas,
        "rendimiento": pedir(ma.analizar_performance_profesional, hist["Close"]),
        "simulacion": sim,
        "velas": velas,
        "resumen_velas": pedir(gr.resumen, velas) if velas is not None else None,
        "earnings": earnings,
        "caminos": pedir(ma.caminos_evento, earnings, hist) if earnings else None,
        "reversion": pedir(ma.reversion_tras_extremos, hist, umbral_sigmas),
        "tecnicos": pedir(ma.indicadores_tecnicos, hist),
        "volumen": pedir(ma.analisis_volumen, hist),
        "mercado": datos_mercado(pedir, ticker),
        "comparativa": datos_comparativa(pedir, ticker, referencia, divisa),
    }
    datos["seleccion"] = (datos_seleccion(pedir, ticker, hist, umbral_sigmas,
                                          ventana_rebote)
                          if incluir_seleccion else None)
    datos["fundamentales"] = (datos_fundamentales(pedir, ticker)
                              if incluir_fundamentales else None)
    datos["segmentos"] = (datos_segmentos(pedir, ticker)
                          if incluir_fundamentales else None)
    datos["incidencias"] = list(dict.fromkeys(pedir.incidencias))
    return datos
