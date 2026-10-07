"""Pestana de CRIBADO DEL MERCADO.

Recorre las 503 empresas del S&P 500 buscando caidas superiores al umbral de
sigmas en la sesion en curso o en las ultimas sesiones, y las ordena por el
comportamiento historico del propio valor tras caidas comparables.

Al pie, los titulares recientes de los valores que han quedado en la lista.

ANALISIS COMPLEMENTARIO
-----------------------
Bajo la lista se situan cuatro bloques que NO intervienen en la seleccion. El
motor de busqueda sigue devolviendo exactamente los mismos valores en el mismo
orden; lo que aportan es el examen critico de ese resultado:

    Contraste multiple        cuantos de los listados resisten al hecho de
                              haber sido elegidos entre quinientos y pico.
    Validacion fuera de       si lo medido en la primera mitad de la historia
    periodo                   anticipa algo de lo ocurrido en la segunda.
    Descomposicion factorial  si el rendimiento es propio o son primas
                              conocidas con otro nombre.
    Origen de la caida        que provoco cada desplome y como suele terminar
                              cada tipo de desplome.
"""

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

import bloques_cribado as bloques
import motor_cribado as crib
import motor_factores as fac
import motor_origen as ori
import motor_validacion as val

C0 = "#1f77b4"
VERDE = "#2CA02C"
ROJO = "#D62728"
GRIS = "#7F7F7F"
REJILLA = {"grid": True, "gridColor": "#DDDDDD", "gridOpacity": 0.9}


@st.cache_data(ttl="6h", show_spinner=False)
def _universo():
    return crib.universo_sp500()


@st.cache_data(ttl="30m", show_spinner=False)
def _cierres(tickers):
    return crib.descargar_universo(list(tickers))


@st.cache_data(ttl="30m", show_spinner=False)
def _noticias(tickers, por_ticker):
    return crib.noticias_de(list(tickers), por_ticker=por_ticker)


@st.cache_data(ttl="12h", show_spinner=False)
def _factores():
    return fac.descargar_factores()


@st.cache_data(ttl="30m", show_spinner=False)
def _serie_estrategia(clave, umbral, ventana, _cierres_df):
    return fac.serie_estrategia(_cierres_df, umbral=umbral, ventana=ventana)


@st.cache_data(ttl="12h", show_spinner=False)
def _resultados_de(tickers):
    return ori.fechas_resultados(list(tickers))




def render(umbral_defecto=2.0):
    st.subheader("Selección de valores del universo S&P 500")
    st.caption(
        "Identificación sistemática de los valores del S&P 500 cuya variación "
        "diaria excede el umbral de desviaciones típicas fijado, en la sesión "
        "en curso o en las precedentes. La ordenación se establece a partir del "
        "comportamiento registrado por cada valor en episodios históricos "
        "comparables.")

    col_a, col_b, col_c, col_d = st.columns(4)
    with col_a:
        umbral = st.slider("Umbral de caída (σ)", 1.5, 4.0, float(umbral_defecto), 0.1,
                           key="crib_umbral",
                           help="Desviaciones típicas respecto a la volatilidad "
                                "diaria propia de cada valor.")
    with col_b:
        sesiones = st.slider("Sesiones a examinar", 1, 10, 1, key="crib_sesiones",
                             help="1 corresponde a la sesión en curso o, con el "
                                  "mercado cerrado, a la última completada.")
    with col_c:
        ventana = st.slider("Horizonte de evaluación (sesiones)", 5, 40,
                            crib.VENTANA_REBOTE, 1, key="crib_ventana",
                            help="Número de sesiones posteriores sobre el que se "
                                 "mide el comportamiento histórico.")
    with col_d:
        # La escala es de porcentaje entero. Con una escala de 0 a 0,9 y formato
        # "%.0f%%" el control mostraba "0%" en toda su longitud, porque el
        # formateo redondeaba a cero cualquier valor inferior a la unidad.
        min_pos_pct = st.slider("Frecuencia mínima de episodios al alza (%)",
                                1, 99, 50, 1, format="%d%%", key="crib_minpos")
    min_pos = min_pos_pct / 100

    solo_favorables = st.toggle(
        "Restringir a valores con antecedentes favorables", value=True,
        key="crib_filtro",
        help="Conserva los valores cuyo retorno medio posterior es positivo y "
             "cuya frecuencia de episodios al alza alcanza el mínimo fijado.")

    with st.spinner("Obteniendo cinco años de cotizaciones de las 503 sociedades…"):
        universo = _universo()
        if universo is None:
            st.error("No ha sido posible obtener la composición del índice S&P 500.",
                     icon=":material/error:")
            return
        cierres, ausentes = _cierres(tuple(universo["Ticker"]))

    if cierres is None or cierres.empty:
        st.error("No ha sido posible obtener las cotizaciones del universo de análisis.",
                 icon=":material/error:")
        return

    with st.spinner("Procesando el universo…"):
        resultado = crib.cribar(cierres, umbral=umbral, ventana=ventana,
                                sesiones_atras=sesiones, universo=universo,
                                ausentes=ausentes)
        referencia = crib.referencia_mercado(cierres, ventana=ventana)
        resultado = crib.anadir_ventaja(resultado, referencia)
        # Ambas capas se limitan a AGREGAR columnas y claves. Ni eliminan
        # candidatos ni alteran la ordenacion: la seleccion que llega al
        # usuario es exactamente la misma que antes de existir estos modulos.
        resultado = val.contraste_multiple(resultado, referencia)
        resultado = val.validacion_fuera_de_periodo(resultado, cierres)

    fechas = resultado["fechas"]
    rango = (f"{fechas[0].date()}" if len(fechas) == 1
             else f"{fechas[0].date()} a {fechas[-1].date()}")

    completo = resultado["tabla"]
    if solo_favorables:
        filtrado = crib.filtrar_por_historial(
            resultado, exigir_media_positiva=True, minimo_positivos=min_pos)
        tabla = filtrado["tabla"]
        descartadas = filtrado.get("descartadas", 0)
    else:
        tabla = completo
        descartadas = 0

    col_media = f"Media +{ventana}d"

    solicitados = resultado.get("solicitados", resultado["analizados"])
    no_obtenidos = resultado.get("ausentes", [])

    with st.container(horizontal=True):
        st.metric("Sociedades examinadas", f"{resultado['analizados']}",
                  f"de {solicitados} del índice", delta_color="off", border=True)
        st.metric(f"Caídas de más de {umbral:.1f}σ", f"{len(completo)}",
                  rango, delta_color="off", border=True)
        st.metric("Tras el criterio histórico", f"{len(tabla)}",
                  f"{descartadas} excluidas" if descartadas else "sin restricción",
                  delta_color="off", border=True)
        if referencia:
            st.metric(f"Referencia del índice a {ventana} sesiones",
                      f"{referencia['media']:+.2%}",
                      f"{referencia['positivos']:.1%} de episodios al alza",
                      delta_color="off", border=True)

    # Una descarga recortada por el proveedor no puede presentarse como un
    # universo mas pequenio: son cosas distintas y solo una invalida el cribado.
    if no_obtenidos:
        cuota = len(no_obtenidos) / solicitados
        muestra = ", ".join(no_obtenidos[:12])
        if len(no_obtenidos) > 12:
            muestra += f" y {len(no_obtenidos) - 12} más"
        if cuota > 0.05:
            st.error(
                f"**Cobertura incompleta: faltan {len(no_obtenidos)} de "
                f"{solicitados} valores ({cuota:.1%}).** Una ausencia de esta "
                f"magnitud es indicativa de limitación de peticiones por parte "
                f"del proveedor, no de valores inexistentes. El cribado que "
                f"figura a continuación **no examina el índice completo** y "
                f"puede omitir caídas relevantes. Se recomienda reintentar "
                f"pasados unos minutos. No obtenidos: {muestra}.",
                icon=":material/cloud_off:")
        else:
            st.caption(
                f":material/info: {len(no_obtenidos)} valores sin cotizaciones "
                f"disponibles ({cuota:.1%} del índice), habitualmente "
                f"incorporaciones recientes o cambios de símbolo: {muestra}.")

    if referencia:
        st.caption(
            f"La **referencia del índice** corresponde al retorno medio de un "
            f"valor cualquiera del S&P 500 a {ventana} sesiones, tomado desde "
            f"cualquier sesión de partida ({referencia['observaciones']:,} "
            f"observaciones). Constituye el término de comparación obligado: un "
            f"retorno medio posterior del +1% carece de significación si el "
            f"conjunto del índice rinde {referencia['media']:+.2%} sin "
            f"condicionamiento previo alguno.")

    if completo.empty:
        st.warning(
            f"Ninguna sociedad del S&P 500 registra una caída superior a "
            f"{umbral:.1f}σ en "
            f"{'la última sesión' if sesiones == 1 else f'las últimas {sesiones} sesiones'} "
            f"({rango}). Amplíe el número de sesiones examinadas o reduzca el "
            f"umbral exigido.",
            icon=":material/search_off:")
        return

    if tabla.empty:
        st.warning(
            f"Se han identificado {len(completo)} caídas superiores a "
            f"{umbral:.1f}σ, si bien ninguna satisface el criterio histórico "
            f"establecido. Desactive la restricción para consultar la relación "
            f"completa.",
            icon=":material/filter_alt_off:")
        return

    # ---------------------------------------------------------------
    #  Listado
    # ---------------------------------------------------------------
    columnas = ["Ticker", "Empresa", "Sector", "Fecha", "Caída", "Sigmas",
                "Cierre ese día", "Precio actual", "Casos previos", col_media,
                "% en positivo"]
    if "Ventaja sobre el mercado" in tabla.columns:
        columnas.append("Ventaja sobre el mercado")
    columnas += ["Peor caso", "Mejor caso", "Estadística suficiente"]

    st.dataframe(
        tabla[[c for c in columnas if c in tabla.columns]],
        hide_index=True,
        column_config={
            "Caída": st.column_config.NumberColumn(format="percent"),
            "Sigmas": st.column_config.NumberColumn(format="%+.2f σ"),
            "Cierre ese día": st.column_config.NumberColumn(format="%.2f"),
            "Precio actual": st.column_config.NumberColumn(format="%.2f"),
            "Casos previos": st.column_config.NumberColumn(format="%d"),
            col_media: st.column_config.NumberColumn(format="percent"),
            "% en positivo": st.column_config.NumberColumn(format="percent"),
            "Ventaja sobre el mercado": st.column_config.NumberColumn(format="percent"),
            "Peor caso": st.column_config.NumberColumn(format="percent"),
            "Mejor caso": st.column_config.NumberColumn(format="percent"),
            "Estadística suficiente": st.column_config.CheckboxColumn("Muestra suficiente"),
        })

    pocos = tabla[~tabla["Estadística suficiente"]] if "Estadística suficiente" in tabla else pd.DataFrame()
    if not pocos.empty:
        st.caption(
            f":material/warning: {len(pocos)} valor(es) presentan menos de "
            f"{crib.MIN_CASOS_HISTORICOS} episodios previos comparables. Con una "
            f"muestra de ese tamaño el retorno medio resulta altamente sensible "
            f"a un único episodio, por lo que su valor informativo es limitado.")

    # ---------------------------------------------------------------
    #  Grafico: caida de hoy frente a rebote historico
    # ---------------------------------------------------------------
    with st.container(border=True):
        st.markdown("**Variación registrada frente al comportamiento histórico posterior**")
        g = tabla.copy()
        g["Etiqueta"] = g["Ticker"]
        base = alt.Chart(g)
        puntos = base.mark_circle(size=160, opacity=0.85).encode(
            alt.X("Caída:Q", title="Variación registrada",
                  axis=alt.Axis(format="+.0%", **REJILLA)),
            alt.Y(f"{col_media}:Q", title=f"Retorno medio histórico a {ventana} sesiones",
                  axis=alt.Axis(format="+.0%", **REJILLA)),
            size=alt.Size("Casos previos:Q", title="Casos previos",
                          scale=alt.Scale(range=[50, 260])),
            color=alt.Color("% en positivo:Q", title="% en positivo",
                            scale=alt.Scale(scheme="redyellowgreen")),
            tooltip=["Ticker", "Empresa", "Sector",
                     alt.Tooltip("Caída:Q", format="+.2%"),
                     alt.Tooltip("Sigmas:Q", format="+.2f"),
                     alt.Tooltip(f"{col_media}:Q", format="+.2%"),
                     alt.Tooltip("% en positivo:Q", format=".1%"),
                     alt.Tooltip("Casos previos:Q", format="d")],
        )
        etiquetas = base.mark_text(dy=-14, fontSize=10, fontWeight="bold").encode(
            alt.X("Caída:Q"), alt.Y(f"{col_media}:Q"), text="Etiqueta:N")
        capas = [puntos, etiquetas]
        if referencia:
            linea = alt.Chart(pd.DataFrame({"y": [referencia["media"]]})).mark_rule(
                color=GRIS, strokeDash=[6, 4], strokeWidth=2).encode(y="y:Q")
            capas.insert(0, linea)
        # Alto suficiente para que las DOS leyendas (color y tamano) quepan
        # apiladas a la derecha: con 380 px la de "Casos previos" se cortaba por
        # abajo y no se veian ni el simbolo mayor ni su etiqueta.
        st.altair_chart(alt.layer(*capas).properties(height=520))
        if referencia:
            st.caption(
                f"La línea discontinua señala la referencia del índice "
                f"({referencia['media']:+.2%}). Únicamente las posiciones situadas "
                f"por encima presentan un comportamiento histórico superior al del "
                f"conjunto del mercado. El diámetro de cada punto refleja el número "
                f"de episodios previos: a menor tamaño, menor representatividad "
                f"estadística del retorno medio.")

    # ---------------------------------------------------------------
    #  Advertencia metodologica sobre la composicion del indice
    # ---------------------------------------------------------------
    deriva = crib.deriva_composicion(universo)
    if deriva and deriva["recientes"]:
        with st.expander("Nota metodológica sobre el universo de análisis"):
            st.markdown(
                f"El historial se calcula sobre las **{deriva['total']} "
                f"sociedades que integran el índice en la fecha actual**, que no "
                f"coinciden con las que lo integraban al inicio del periodo. "
                f"**{deriva['recientes']}** de ellas ({deriva['cuota']:.1%}) se "
                f"incorporaron durante los últimos {deriva['anios']} años, y las "
                f"que fueron excluidas del índice en ese intervalo no figuran en "
                f"el cálculo.\n\n"
                f"Ambas circunstancias desplazan el retorno histórico posterior "
                f"**en la misma dirección, al alza**: la exclusión del índice "
                f"suele seguir a un deterioro pronunciado —de modo que los "
                f"peores desenlaces posteriores a una caída extrema faltan de la "
                f"muestra—, mientras que la incorporación suele seguir a una "
                f"revalorización sostenida. La composición histórica exacta del "
                f"índice no está disponible en fuentes gratuitas, por lo que el "
                f"sesgo se documenta pero no se corrige.\n\n"
                f"**Consecuencia práctica.** El nivel absoluto de los retornos "
                f"medios que figuran en la tabla está sobrestimado. La "
                f"comparación de cada valor **frente a la referencia del "
                f"índice** resulta considerablemente más robusta, dado que "
                f"ambas magnitudes se calculan sobre el mismo universo y "
                f"comparten por tanto el mismo sesgo.")

    # ---------------------------------------------------------------
    #  Analisis complementario sobre la seleccion
    # ---------------------------------------------------------------
    st.divider()
    st.markdown("### Análisis complementario de la selección")
    st.caption(
        "Los cuatro bloques siguientes examinan el resultado anterior sin "
        "modificarlo. Ninguno interviene en el motor de búsqueda: la relación "
        "de valores y su orden son los mismos con o sin ellos.")

    b1, b2, b3, b4, b5 = st.tabs([
        "Contraste múltiple", "Validación fuera de periodo",
        "Descomposición factorial", "Régimen del valor y su sector",
        "Origen de la caída"])

    with b1:
        bloques.contraste(resultado, tabla, ventana)
    with b2:
        bloques.validacion(resultado, cierres, tabla, umbral, ventana)
    with b3:
        bloques.factorial(
            cierres, umbral, ventana,
            lambda u, v: _serie_estrategia(f"{u}-{v}", u, v, cierres),
            _factores)
    with b4:
        bloques.regimen(cierres, universo, tabla, umbral, ventana)
    with b5:
        bloques.origen(cierres, universo, tabla, umbral,
                       _resultados_de, _noticias)

    # ---------------------------------------------------------------
    #  Noticias de los valores listados
    # ---------------------------------------------------------------
    st.divider()
    st.markdown("**Información publicada sobre los valores identificados**")

    tickers = list(dict.fromkeys(tabla["Ticker"].tolist()))
    col_n1, col_n2 = st.columns([1, 3])
    with col_n1:
        por_ticker = st.slider("Titulares por valor", 1, 10, 4, key="crib_news_n")
    with col_n2:
        st.caption(f"Restringida a los {len(tickers)} valores relacionados: "
                   f"{', '.join(tickers[:12])}"
                   f"{'…' if len(tickers) > 12 else ''}")

    with st.spinner("Recuperando titulares…"):
        noticias = _noticias(tuple(tickers), por_ticker)

    if noticias is None or noticias.empty:
        st.info("El proveedor no dispone de titulares para estos valores en este momento.",
                icon=":material/newspaper:")
        return

    seleccion = st.multiselect("Restringir a valores concretos", tickers, default=tickers,
                               key="crib_news_filtro")
    # Deseleccionar todo debe dejar la lista vacia, no mostrarlo todo: antes
    # quitar todos los filtros producia el resultado contrario al esperado.
    if not seleccion:
        st.caption("No se ha seleccionado ningún valor.")
        return
    vista = noticias[noticias["Ticker"].isin(seleccion)]

    st.caption(f"{len(vista)} titulares, ordenados de más a menos reciente.")

    for _, n in vista.head(60).iterrows():
        fecha = n["Fecha"]
        cuando = fecha.strftime("%d/%m/%Y %H:%M") if pd.notna(fecha) else "sin fecha"
        with st.container(border=True):
            cabecera = f"**{n['Ticker']}** · {n['Medio']} · {cuando}"
            st.caption(cabecera)
            if n["Enlace"]:
                st.markdown(f"**[{n['Titular']}]({n['Enlace']})**")
            else:
                st.markdown(f"**{n['Titular']}**")
            if n["Resumen"]:
                st.write(n["Resumen"])

    st.caption(
        ":material/info: Los titulares proceden del agregador de Yahoo Finance y "
        "se reproducen sin edición ni valoración de su fiabilidad. Documentan la "
        "cobertura informativa existente sobre cada valor; no constituyen "
        "verificación de los hechos referidos.")
