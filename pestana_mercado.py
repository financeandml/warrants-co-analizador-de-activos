"""Pestana de OPCIONES Y MICROESTRUCTURA.

M32 · que movimiento descuenta el mercado antes del evento.
M34 · si el movimiento observado tiene informacion detras o es ruido de liquidez.

Todo el calculo vive en motor_mercado.py; aqui solo hay interfaz.
"""

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

import motor_mercado as mrk

C0 = "#1f77b4"
C1 = "#ff7f0e"
VERDE = "#2CA02C"
ROJO = "#D62728"
GRIS = "#7F7F7F"
NAVY = "#000080"
REJILLA = {"grid": True, "gridColor": "#DDDDDD", "gridOpacity": 0.9}


def _eje(campo, titulo, formato=None, eje="y", **kw):
    ejes = dict(REJILLA)
    if formato:
        ejes["format"] = formato
    cls = alt.Y if eje == "y" else alt.X
    return cls(campo, title=titulo, axis=alt.Axis(**ejes), **kw)


@st.cache_data(ttl="10m", show_spinner=False)
def _cadena(simbolo):
    return mrk.cadena_opciones(simbolo)


@st.cache_data(ttl="10m", show_spinner=False)
def _intradia(simbolo):
    return mrk.intradia(simbolo)


def render(ticker, nombre, moneda, sigma_diaria=None, mov_ultimo=None):
    st.subheader("Opciones y microestructura")
    st.caption(
        "Qué movimiento descontaba el mercado antes del evento, y si el "
        "movimiento observado se produjo con negociación real o es un artefacto "
        "de liquidez.")

    # =================================================================
    #  M32 · MOVIMIENTO IMPLICITO
    # =================================================================
    with st.spinner("Descargando cadena de opciones…"):
        cadena = _cadena(ticker)

    if cadena is None:
        st.info(
            f"**{nombre}** no tiene opciones cotizadas en Yahoo Finance, o no hay "
            f"cadena disponible. Es lo habitual en ETFs pequeños, valores poco "
            f"líquidos y emisores no estadounidenses.", icon=":material/info:")
    else:
        st.markdown("**M32 · Movimiento implícito frente a real**")
        implicito = mrk.movimiento_implicito(cadena)

        if implicito is None:
            st.info("La cadena no tiene un straddle en el dinero utilizable.",
                    icon=":material/info:")
        else:
            with st.container(horizontal=True):
                st.metric("Movimiento implícito",
                          f"±{implicito['movimiento_implicito']:.2%}",
                          f"hasta {implicito['vencimiento']} ({implicito['dias']} días)",
                          delta_color="off", border=True)
                st.metric("Volatilidad implícita", f"{implicito['iv_atm']:.1%}",
                          f"strike {implicito['strike_atm']:,.2f}",
                          delta_color="off", border=True)
                st.metric("Precio del straddle", f"{implicito['straddle']:,.2f}",
                          f"call {implicito['precio_call']:,.2f} + "
                          f"put {implicito['precio_put']:,.2f}",
                          delta_color="off", border=True)
                if mov_ultimo is not None and np.isfinite(mov_ultimo) \
                        and implicito["movimiento_implicito"]:
                    veces = abs(mov_ultimo) / implicito["movimiento_implicito"]
                    st.metric("Último movimiento", f"{veces:.1f}×",
                              "veces lo descontado", delta_color="off", border=True)

            if not implicito["liquidez_ok"]:
                st.warning(
                    f"El straddle en el dinero tiene poco interés abierto "
                    f"({implicito['interes_call']} calls y {implicito['interes_put']} "
                    f"puts). Con esa liquidez el precio de la opción es poco fiable "
                    f"y el movimiento implícito que se deriva de él, también.",
                    icon=":material/warning:")

            st.caption(
                f"El movimiento implícito sale del straddle en el dinero: lo que "
                f"cuesta cubrirse de un movimiento en cualquier dirección, dividido "
                f"entre el precio. Con {implicito['movimiento_implicito']:.2%}, el "
                f"mercado está poniendo precio a una variación de esa magnitud hasta "
                f"el {implicito['vencimiento']}.")

            st.error(
                "**Limitación de la fuente.** Yahoo solo publica la cadena de "
                "opciones **de hoy**, sin histórico. Por eso el movimiento "
                "implícito se puede comparar con lo que ocurra a partir de ahora, "
                "pero **no se puede reconstruir el de un evento pasado**. Para "
                "poder decir «se movió 2,3 veces lo previsto» en unos resultados "
                "concretos hay que haber capturado la cadena antes de que "
                "ocurrieran.", icon=":material/warning:")

        # --- Estructura temporal ---
        et = mrk.estructura_temporal(cadena)
        if et is not None and len(et) > 1:
            with st.container(border=True):
                st.markdown("**Estructura temporal de la volatilidad**")
                base = alt.Chart(et)
                l1 = base.mark_line(point=True, color=C0, strokeWidth=2).encode(
                    _eje("Días:Q", "Días hasta vencimiento", eje="x"),
                    _eje("Movimiento implícito:Q", "Movimiento implícito", ".0%"),
                    tooltip=["Vencimiento", "Días",
                             alt.Tooltip("Movimiento implícito:Q", format=".2%"),
                             alt.Tooltip("Volatilidad implícita:Q", format=".1%")],
                ).properties(height=250)
                st.altair_chart(l1)
                l2 = base.mark_line(point=True, color=C1, strokeWidth=2).encode(
                    _eje("Días:Q", "Días hasta vencimiento", eje="x"),
                    _eje("Volatilidad implícita:Q", "Volatilidad implícita", ".0%"),
                    tooltip=["Vencimiento",
                             alt.Tooltip("Volatilidad implícita:Q", format=".1%")],
                ).properties(height=220)
                st.altair_chart(l2)
                st.caption(
                    "El movimiento implícito crece con el plazo por pura "
                    "acumulación de tiempo. Lo informativo es la **volatilidad**: "
                    "si el vencimiento más cercano cotiza muy por encima del resto, "
                    "el mercado está anticipando un evento inminente.")
                st.dataframe(et, hide_index=True, column_config={
                    "Días": st.column_config.NumberColumn(format="%d"),
                    "Movimiento implícito": st.column_config.NumberColumn(format="percent"),
                    "Volatilidad implícita": st.column_config.NumberColumn(format="percent"),
                    "Interés abierto": st.column_config.NumberColumn(format="%,d"),
                })

        # --- Sonrisa y sesgo ---
        sonrisa = mrk.sonrisa_volatilidad(cadena)
        sesgo = mrk.sesgo(cadena)
        if sonrisa is not None and not sonrisa.empty:
            with st.container(border=True):
                st.markdown("**Volatilidad por strike**")
                ch = alt.Chart(sonrisa).mark_line(point=True, strokeWidth=2).encode(
                    _eje("moneyness:Q", "Distancia al precio actual", "+.0%", eje="x"),
                    _eje("impliedVolatility:Q", "Volatilidad implícita", ".0%"),
                    color=alt.Color("tipo:N", title=None, scale=alt.Scale(
                        domain=["put", "call"], range=[ROJO, VERDE])),
                    tooltip=[alt.Tooltip("strike:Q", format=",.2f"),
                             alt.Tooltip("moneyness:Q", format="+.1%"),
                             alt.Tooltip("impliedVolatility:Q", format=".1%"),
                             alt.Tooltip("openInterest:Q", format=",d")],
                ).properties(height=300)
                centro = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(
                    color=GRIS, strokeDash=[5, 4]).encode(x="x:Q")
                st.altair_chart(ch + centro)
                if sesgo:
                    if sesgo["sesgo"] > 0.02:
                        lectura = ("Las puts cotizan por encima de las calls: el "
                                   "mercado paga más por cubrirse de una caída que "
                                   "de una subida.")
                    elif sesgo["sesgo"] < -0.02:
                        lectura = ("Las calls cotizan por encima de las puts, algo "
                                   "menos habitual: suele aparecer cuando se "
                                   "anticipa un movimiento al alza.")
                    else:
                        lectura = "La curva está prácticamente simétrica."
                    st.caption(
                        f"Al 10% fuera del dinero: put {sesgo['iv_put_10']:.1%} "
                        f"frente a call {sesgo['iv_call_10']:.1%}, un sesgo de "
                        f"**{sesgo['sesgo']:+.1%}**. {lectura}")

        # --- Interes abierto por strike ---
        oi = mrk.concentracion_interes(cadena)
        if oi is not None and not oi.empty:
            with st.container(border=True):
                st.markdown("**Interés abierto por strike**")
                ch = alt.Chart(oi).mark_bar().encode(
                    _eje("strike:Q", f"Strike ({moneda})", eje="x"),
                    _eje("openInterest:Q", "Contratos abiertos"),
                    color=alt.Color("tipo:N", title=None, scale=alt.Scale(
                        domain=["put", "call"], range=[ROJO, VERDE])),
                    tooltip=[alt.Tooltip("strike:Q", format=",.2f"), "tipo",
                             alt.Tooltip("openInterest:Q", format=",d")],
                ).properties(height=280)
                spot = alt.Chart(pd.DataFrame({"x": [cadena["spot"]]})).mark_rule(
                    color=NAVY, strokeWidth=2).encode(x="x:Q")
                st.altair_chart(ch + spot)
                st.caption(
                    "La línea azul marino es el precio actual. Los strikes con "
                    "mucho interés abierto concentran cobertura de los creadores "
                    "de mercado y pueden actuar como referencia cerca del "
                    "vencimiento.")

    # =================================================================
    #  M34 · CALIDAD DEL MOVIMIENTO
    # =================================================================
    st.divider()
    st.markdown("**M34 · Calidad del movimiento**")
    st.caption(
        "Un movimiento de precio solo significa algo si hubo negociación "
        "detrás. Los minutos sin volumen producen saltos que no reflejan ningún "
        "cruce y quedan excluidos de todo el análisis.")

    with st.spinner("Descargando intradía de 1 minuto…"):
        datos = _intradia(ticker)

    if datos is None or datos.empty:
        st.info(
            f"No hay intradía disponible para **{ticker}**. Yahoo solo publica "
            f"granularidad de un minuto de los últimos 8 días naturales, y no "
            f"para todos los valores.", icon=":material/info:")
        return

    fechas = sorted(datos["Fecha"].unique(), reverse=True)
    fecha = st.selectbox("Sesión a examinar", fechas, index=0,
                         format_func=lambda f: str(f), key="sesion_micro")

    q = mrk.calidad_del_dia(datos, fecha)
    if q is None:
        st.info("Sin datos para esa sesión.", icon=":material/info:")
        return

    with st.container(horizontal=True):
        st.metric("Variación de la sesión", f"{q['variacion_total']:+.2%}",
                  "primer a último cruce", delta_color="off", border=True)
        st.metric("Solo horario regular", f"{q['variacion_regular']:+.2%}",
                  "09:30 a 16:00", delta_color="off", border=True)
        st.metric("Volumen fuera de horario", f"{q['peso_fuera_horario']:.1%}",
                  f"representatividad {q['representatividad']}",
                  delta_color="off", border=True)
        st.metric("Minutos con negociación", f"{q['minutos_con_negociacion']}",
                  "de 960 posibles", delta_color="off", border=True)

    if q["representatividad"] == "baja":
        st.error(
            f"**Movimiento poco representativo.** El "
            f"{q['peso_fuera_horario']:.0%} del volumen se negoció fuera del "
            f"horario regular. Un precio formado en preapertura o postcierre, con "
            f"el libro fino, puede moverse mucho con muy poco dinero y no refleja "
            f"el juicio del conjunto del mercado.", icon=":material/warning:")
    elif q["representatividad"] == "media":
        st.warning(
            f"El {q['peso_fuera_horario']:.0%} del volumen se negoció fuera del "
            f"horario regular. Conviene mirar a qué hora se formó el movimiento "
            f"antes de darlo por bueno.", icon=":material/warning:")

    if q["pico"]:
        p = q["pico"]
        st.caption(
            f":material/schedule: Minuto de mayor movimiento: **{p['hora']}** "
            f"({p['sesion']}), {p['retorno']:+.2%} con {p['volumen']:,.0f} títulos "
            f"negociados.")

    col_a, col_b = st.columns([3, 2])
    with col_a:
        with st.container(border=True):
            st.markdown("*Precio y volumen minuto a minuto*")
            dia = q["detalle"].reset_index()
            dia.columns = ["Momento"] + list(q["detalle"].columns)
            precio = alt.Chart(dia).mark_line(color=C0, strokeWidth=1.4).encode(
                _eje("Momento:T", "Hora", eje="x"),
                _eje("Close:Q", f"Precio ({moneda})", scale=alt.Scale(zero=False)),
                tooltip=[alt.Tooltip("Momento:T", format="%H:%M"),
                         alt.Tooltip("Close:Q", format=",.2f"),
                         alt.Tooltip("Volume:Q", format=",.0f"), "Sesion"],
            ).properties(height=260)
            st.altair_chart(precio.interactive())
            vol = alt.Chart(dia[dia["Volume"] > 0]).mark_bar().encode(
                _eje("Momento:T", "Hora", eje="x"),
                _eje("Volume:Q", "Volumen"),
                color=alt.Color("Sesion:N", title=None, scale=alt.Scale(
                    domain=["Preapertura", "Sesión regular", "Postcierre"],
                    range=[C1, C0, ROJO])),
                tooltip=[alt.Tooltip("Momento:T", format="%H:%M"),
                         alt.Tooltip("Volume:Q", format=",.0f"), "Sesion"],
            ).properties(height=200)
            st.altair_chart(vol)

    with col_b:
        with st.container(border=True):
            st.markdown("*Reparto por franja horaria*")
            ps = q["por_sesion"]
            ch = alt.Chart(ps).mark_bar().encode(
                alt.Y("Sesion:N", sort="-x", title=None),
                _eje("Volumen:Q", "Volumen", eje="x"),
                color=alt.Color("Sesion:N", legend=None, scale=alt.Scale(
                    domain=["Preapertura", "Sesión regular", "Postcierre"],
                    range=[C1, C0, ROJO])),
                tooltip=["Sesion", alt.Tooltip("Volumen:Q", format=",.0f"),
                         alt.Tooltip("Peso:Q", format=".1%"),
                         alt.Tooltip("Minutos:Q", format="d")],
            ).properties(height=180)
            st.altair_chart(ch)
            st.dataframe(ps, hide_index=True, column_config={
                "Volumen": st.column_config.NumberColumn(format="%,d"),
                "Peso": st.column_config.NumberColumn(format="percent"),
                "Minutos": st.column_config.NumberColumn(format="%d"),
            })

        perfil = mrk.perfil_volumen_precio(datos, fecha)
        if perfil is not None and not perfil.empty:
            with st.container(border=True):
                st.markdown("*Volumen por nivel de precio*")
                ch = alt.Chart(perfil).mark_bar(color=C0).encode(
                    alt.Y("Precio:Q", title=f"Precio ({moneda})",
                          scale=alt.Scale(zero=False), sort="descending"),
                    _eje("Volumen:Q", "Volumen negociado", eje="x"),
                    tooltip=[alt.Tooltip("Precio:Q", format=",.2f"),
                             alt.Tooltip("Volumen:Q", format=",.0f")],
                ).properties(height=280)
                st.altair_chart(ch)
                st.caption("Dónde se ha cruzado papel de verdad durante la sesión.")

    # --- Comparativa de sesiones ---
    resumen = mrk.resumen_sesiones(datos)
    if resumen is not None and not resumen.empty:
        with st.container(border=True):
            st.markdown("**Volumen por sesión en los últimos días**")
            ch = alt.Chart(resumen).mark_bar().encode(
                alt.X("Fecha:O", title=None),
                _eje("Volumen:Q", "Volumen", ),
                color=alt.Color("Sesion:N", title=None, scale=alt.Scale(
                    domain=["Preapertura", "Sesión regular", "Postcierre"],
                    range=[C1, C0, ROJO])),
                tooltip=["Fecha", "Sesion",
                         alt.Tooltip("Volumen:Q", format=",.0f"),
                         alt.Tooltip("Variacion:Q", title="Variación", format="+.2%")],
            ).properties(height=280)
            st.altair_chart(ch)
            st.caption(
                "Yahoo solo publica granularidad de un minuto de los **últimos 8 "
                "días naturales**. Es un límite de la fuente: para analizar la "
                "microestructura de un evento más antiguo habría que haber "
                "capturado los datos en su momento.")
