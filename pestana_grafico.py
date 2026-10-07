"""Pestana de GRAFICO DE COTIZACION.

Grafico de velas interactivo con volumen, medias moviles y sesiones de
preapertura y postcierre diferenciadas. Admite refresco automatico para seguir
la sesion en curso minuto a minuto.

El calculo vive en motor_grafico.py; aqui solo hay representacion.
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import motor_grafico as gr

ALCISTA = "#2CA02C"
BAJISTA = "#D62728"
FONDO_EXTENDIDO = "rgba(31, 119, 180, 0.07)"
COLOR_MEDIAS = {20: "#1f77b4", 50: "#ff7f0e", 200: "#9467bd"}


@st.cache_data(ttl="45s", show_spinner=False)
def _velas(simbolo, intervalo, periodo, prepost):
    return gr.velas(simbolo, intervalo, periodo, prepost)


def _construir(datos, simbolo, moneda, intervalo, prepost, medias_activas,
               mostrar_volumen, sombrear):
    """Figura de velas con volumen debajo, ejes compartidos."""
    if mostrar_volumen:
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                            vertical_spacing=0.03, row_heights=[0.76, 0.24])
    else:
        fig = make_subplots(rows=1, cols=1)

    fig.add_trace(go.Candlestick(
        x=datos.index, open=datos["Open"], high=datos["High"],
        low=datos["Low"], close=datos["Close"], name=simbolo,
        increasing=dict(line=dict(color=ALCISTA, width=1), fillcolor=ALCISTA),
        decreasing=dict(line=dict(color=BAJISTA, width=1), fillcolor=BAJISTA),
        hoverinfo="x+y"), row=1, col=1)

    for ventana, serie in gr.medias_moviles(datos).items():
        if ventana not in medias_activas:
            continue
        fig.add_trace(go.Scatter(
            x=datos.index, y=serie, mode="lines", name=f"Media {ventana}",
            line=dict(width=1.4, color=COLOR_MEDIAS.get(ventana, "#7F7F7F")),
            hovertemplate=f"Media {ventana}: %{{y:,.2f}}<extra></extra>"),
            row=1, col=1)

    if mostrar_volumen:
        colores = np.where(datos["Close"] >= datos["Open"], ALCISTA, BAJISTA)
        fig.add_trace(go.Bar(
            x=datos.index, y=datos["Volume"], name="Volumen",
            marker=dict(color=colores, line=dict(width=0)), opacity=0.55,
            hovertemplate="Volumen: %{y:,.0f}<extra></extra>"), row=2, col=1)
        fig.update_yaxes(title_text="Volumen", row=2, col=1,
                         showgrid=True, gridcolor="#EEEEEE")

    # Sombreado de las franjas fuera del horario regular
    if sombrear and prepost:
        for inicio, fin in gr.franjas_extendidas(datos):
            fig.add_vrect(x0=inicio, x1=fin, fillcolor=FONDO_EXTENDIDO,
                          layer="below", line_width=0)

    cortes = gr.cortes_temporales(datos, intervalo, prepost)
    if cortes:
        fig.update_xaxes(rangebreaks=cortes)

    fig.update_layout(
        height=680 if mostrar_volumen else 560,
        margin=dict(l=0, r=0, t=10, b=0),
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
        dragmode="pan",
        legend=dict(orientation="h", yanchor="bottom", y=1.01, x=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="white",
        font=dict(size=12))
    fig.update_xaxes(showgrid=True, gridcolor="#EEEEEE", showspikes=True,
                     spikemode="across", spikethickness=1, spikecolor="#999999",
                     spikedash="dot")
    fig.update_yaxes(title_text=f"Precio ({moneda})", row=1, col=1,
                     showgrid=True, gridcolor="#EEEEEE", showspikes=True,
                     spikethickness=1, spikecolor="#999999", spikedash="dot")
    return fig


def render(ticker, nombre, moneda):
    st.subheader(f"Cotización de {nombre}")
    st.caption(
        "Representación de velas con volumen, medias móviles y diferenciación "
        "de las sesiones de preapertura y postcierre. Desplácese con el ratón "
        "para recorrer la serie y utilice la rueda para ampliar.")

    col_a, col_b, col_c, col_d = st.columns([1.1, 1.1, 1.4, 1.2])
    with col_a:
        intervalo = st.selectbox(
            "Granularidad", list(gr.INTERVALOS.keys()), index=0,
            format_func=lambda k: gr.INTERVALOS[k][0], key="graf_intervalo")
    with col_b:
        periodos = gr.PERIODOS[intervalo]
        periodo = st.selectbox("Periodo", periodos,
                               index=min(2, len(periodos) - 1), key="graf_periodo")
    with col_c:
        medias_activas = st.multiselect(
            "Medias móviles", list(gr.MEDIAS), default=[20, 50],
            format_func=lambda v: f"{v} periodos", key="graf_medias")
    with col_d:
        es_intradia = gr.INTERVALOS[intervalo][2]
        prepost = st.toggle("Pre y postmercado", value=True, key="graf_prepost",
                            disabled=not es_intradia,
                            help="Solo disponible en granularidad intradía; la "
                                 "vela diaria ya consolida la jornada completa.")

    col_e, col_f, col_g = st.columns([1, 1, 2])
    with col_e:
        mostrar_volumen = st.toggle("Volumen", value=True, key="graf_volumen")
    with col_f:
        sombrear = st.toggle("Sombrear franjas extendidas", value=True,
                             key="graf_sombra", disabled=not es_intradia)
    with col_g:
        auto = st.toggle("Actualización automática", value=False, key="graf_auto",
                         help="Recarga la cotización cada minuto mientras la "
                              "pestaña permanezca abierta.")

    if auto:
        _panel_actualizado(ticker, nombre, moneda, intervalo, periodo, prepost,
                           medias_activas, mostrar_volumen, sombrear)
    else:
        _panel(ticker, nombre, moneda, intervalo, periodo, prepost,
               medias_activas, mostrar_volumen, sombrear)


@st.fragment(run_every="60s")
def _panel_actualizado(*args):
    _panel(*args)


def _panel(ticker, nombre, moneda, intervalo, periodo, prepost, medias_activas,
           mostrar_volumen, sombrear):
    with st.spinner("Obteniendo cotizaciones…"):
        try:
            datos = _velas(ticker, intervalo, periodo, prepost)
        except gr.FalloDeFuente as e:
            st.error(
                f"Yahoo Finance no responde en este momento y no se han podido "
                f"obtener las cotizaciones de **{ticker}**. **No es un problema "
                f"de la granularidad ni del periodo elegidos**: cambiar los "
                f"controles no lo resolverá. Vuelva a intentarlo en unos "
                f"segundos.", icon=":material/cloud_off:")
            st.caption(f"Detalle técnico: {e}")
            return

    if datos is None or datos.empty:
        st.info(
            f"El proveedor no dispone de cotizaciones para **{ticker}** con "
            f"granularidad de {gr.INTERVALOS[intervalo][0].lower()} y periodo "
            f"{periodo}. Pruebe con una granularidad mayor o un periodo más "
            f"amplio.", icon=":material/info:")
        return

    res = gr.resumen(datos)
    if res:
        with st.container(horizontal=True):
            st.metric("Último", f"{res['ultimo']:,.2f} {moneda}",
                      f"{res['variacion_jornada']:+.2%}" if np.isfinite(
                          res["variacion_jornada"]) else None,
                      border=True)
            st.metric("Máximo de la jornada", f"{res['maximo']:,.2f}",
                      border=True)
            st.metric("Mínimo de la jornada", f"{res['minimo']:,.2f}",
                      border=True)
            st.metric("Volumen de la jornada", f"{res['volumen']:,.0f}",
                      border=True)
            if res["sesion_actual"]:
                st.metric("Franja", res["sesion_actual"],
                          res["momento"].strftime("%H:%M"),
                          delta_color="off", border=True)

    fig = _construir(datos, ticker, moneda, intervalo, prepost, medias_activas,
                     mostrar_volumen, sombrear)
    st.plotly_chart(fig, width="stretch",
                    config={"scrollZoom": True, "displaylogo": False,
                            "modeBarButtonsToRemove": ["lasso2d", "select2d"]})

    st.caption(
        f"{res['velas']:,} velas · {res['sesiones']} sesiones · desde "
        f"{res['desde'].strftime('%d/%m/%Y %H:%M')} hasta "
        f"{res['momento'].strftime('%d/%m/%Y %H:%M')}. "
        f"Las franjas sombreadas corresponden a preapertura y postcierre. "
        f"Los tramos sin negociación (noches y fines de semana) se comprimen "
        f"para evitar huecos vacíos en la serie.")

    if gr.INTERVALOS[intervalo][2]:
        tope = gr.INTERVALOS[intervalo][1]
        st.caption(
            f":material/info: La granularidad de "
            f"{gr.INTERVALOS[intervalo][0].lower()} dispone de un historial "
            f"máximo de {tope} en la fuente. Para series más largas seleccione "
            f"una granularidad mayor.")
