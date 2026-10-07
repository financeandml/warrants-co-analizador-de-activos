"""Bloque de SEGMENTOS Y GEOGRAFIA dentro de la pestana de fundamentales.

Muestra el desglose de ingresos y margenes por linea de negocio y por area
geografica, con mapa interactivo. Todo el calculo y el parseo viven en
motor_segmentos.py; aqui solo hay interfaz.
"""

import altair as alt
import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

import motor_segmentos as seg

C0 = "#1f77b4"
C1 = "#ff7f0e"
VERDE = "#2CA02C"
ROJO = "#D62728"
GRIS = "#7F7F7F"
REJILLA = {"grid": True, "gridColor": "#DDDDDD", "gridOpacity": 0.9}


def _eje_y(campo, titulo, formato=None):
    ejes = dict(REJILLA)
    if formato:
        ejes["format"] = formato
    return alt.Y(campo, title=titulo, axis=alt.Axis(**ejes))


@st.cache_data(ttl="6h", show_spinner=False)
def _segmentos(cik):
    return seg.analizar_segmentos(cik)


def _formato_importe(v, moneda="USD"):
    if not np.isfinite(v):
        return "—"
    for limite, sufijo in ((1e12, "B"), (1e9, "MM"), (1e6, "M"), (1e3, "k")):
        if abs(v) >= limite:
            return f"{v / limite:,.2f} {sufijo}"
    return f"{v:,.0f}"


def render(ticker, nombre, cik, moneda="USD"):
    st.markdown("**Segmentos de negocio y geografía**")

    if not cik:
        st.info(
            f"**{ticker}** no cotiza en Estados Unidos, así que no presenta "
            f"informes a la SEC. El desglose por segmentos y geografía se extrae "
            f"de esos informes, de modo que no está disponible para este emisor.",
            icon=":material/public_off:")
        return

    with st.spinner("Leyendo los informes de segmentos de la SEC…"):
        paquete = _segmentos(cik)

    if paquete is None:
        st.info(
            f"No se ha encontrado desglose por segmentos en el último informe anual "
            f"de **{nombre}**. Ocurre con empresas de un solo segmento operativo, "
            f"que no están obligadas a desglosar.", icon=":material/info:")
        return

    exp = paquete["expediente"]
    st.caption(
        f"Fuente: {exp['formulario']} presentado el {exp['fecha']} "
        f"· {paquete['informes_revisados']} informes del expediente revisados "
        f"· los importes son los declarados por la empresa, sin reescalar.")

    with st.expander("Informes utilizados"):
        for u in paquete["informes_usados"]:
            st.markdown(f"- **{u['tipo']}** · {u['bloques']} bloques · "
                        f"[{u['nombre']}]({u['url']})")

    # =================================================================
    #  GEOGRAFIA
    # =================================================================
    geo = seg.tabla_geografica(paquete)
    if geo is not None:
        st.divider()
        st.markdown(f"**Ingresos por área geográfica** · periodo {geo['periodo']}")

        tabla = geo["tabla"]
        paises = tabla[tabla["Es pais"]]
        regiones = tabla[~tabla["Es pais"]]

        # --- Comprobacion de cuadre antes de mostrar nada ---
        # Umbral por encima del cual el desglose NO se representa: un mapa
        # dibujado sobre cifras que no cuadran transmite una precision que el
        # dato no tiene, y es peor que no mostrar nada.
        LIMITE_FIABLE = 0.25
        cuadre = geo["detalle"]["cuadre"]
        fiable = True
        peor = np.nan
        if not cuadre.empty:
            peor = cuadre["Desvio"].abs().max()
            if peor < 1e-6:
                st.success(
                    "Las partes suman exactamente el total consolidado declarado "
                    "en el informe, en todos los periodos.",
                    icon=":material/check_circle:")
            elif peor < 0.01:
                st.info(f"Las partes cuadran con el total declarado dentro de un "
                        f"{peor:.3%}.", icon=":material/info:")
            elif peor < LIMITE_FIABLE:
                st.warning(
                    f"La suma de las áreas se desvía hasta un **{peor:.2%}** del "
                    f"total declarado. Suele deberse a partidas residuales que la "
                    f"empresa no asigna a ninguna región. Los pesos relativos "
                    f"siguen siendo orientativos, pero no cuadran al céntimo.",
                    icon=":material/warning:")
            else:
                fiable = False
                st.error(
                    f"**Desglose no representable.** La suma de las áreas se "
                    f"desvía un **{peor:.1%}** del total declarado, muy por encima "
                    f"de lo tolerable. La tabla de este informe mezcla dimensiones "
                    f"o niveles que no se han podido separar de forma automática. "
                    f"No se dibuja el mapa: hacerlo daría una apariencia de "
                    f"precisión que el dato no tiene. Los importes en bruto quedan "
                    f"abajo para que puedas contrastarlos con el informe original.",
                    icon=":material/error:")
            with st.expander("Detalle del cuadre por periodo"):
                st.dataframe(cuadre, hide_index=True, column_config={
                    "Suma de las partes": st.column_config.NumberColumn(format="%,.0f"),
                    "Total declarado": st.column_config.NumberColumn(format="%,.0f"),
                    "Desvio": st.column_config.NumberColumn("Desvío", format="percent"),
                })
                st.caption(f"Criterio de selección de bloques aplicado: "
                           f"**{geo['detalle'].get('seleccion', 'todos los bloques')}**. "
                           f"Se prueban varios cortes del desglose y se conserva el "
                           f"que mejor cuadra contra el total que declara la empresa.")

        if not fiable:
            st.dataframe(tabla[["Area", "Importe"]], hide_index=True,
                         column_config={
                             "Area": st.column_config.TextColumn("Área"),
                             "Importe": st.column_config.NumberColumn(format="%,.0f")})
            return

        # --- Mapa ---
        if not paises.empty:
            fig = px.choropleth(
                paises, locations="ISO3", locationmode="ISO-3",
                color="Importe", hover_name="Area",
                hover_data={"ISO3": False, "Importe": ":,.0f", "Peso": ":.1%"},
                color_continuous_scale="Blues",
                labels={"Importe": f"Ingresos ({moneda})"})
            fig.update_layout(
                margin=dict(l=0, r=0, t=10, b=0), height=430,
                geo=dict(showframe=False, showcoastlines=True,
                         coastlinecolor="#CCCCCC", projection_type="natural earth",
                         bgcolor="rgba(0,0,0,0)"),
                paper_bgcolor="rgba(0,0,0,0)",
                coloraxis_colorbar=dict(title=None, thickness=12))
            st.plotly_chart(fig, width="stretch")

            if not regiones.empty:
                nombres = ", ".join(f"**{r}**" for r in regiones["Area"])
                peso_reg = regiones["Peso"].sum()
                st.caption(
                    f":material/warning: {nombres} no aparecen en el mapa porque son "
                    f"agregados regionales, no países: suman el "
                    f"**{peso_reg:.1%}** de los ingresos. Aparecen en la tabla y en "
                    f"las barras de abajo.")
        else:
            st.info(
                "La empresa desglosa por regiones agregadas (Europa, Asia-Pacífico, "
                "Resto del mundo…) y no por países concretos, así que no se puede "
                "situar en el mapa. El desglose sí está disponible más abajo.",
                icon=":material/map:")

        # --- Tabla y barras ---
        col_a, col_b = st.columns([3, 2])
        with col_a:
            barras = alt.Chart(tabla).mark_bar().encode(
                alt.Y("Area:N", sort="-x", title=None),
                alt.X("Importe:Q", title=f"Ingresos ({moneda})",
                      axis=alt.Axis(format="~s", **REJILLA)),
                color=alt.Color("Es pais:N", title=None,
                                scale=alt.Scale(domain=[True, False],
                                                range=[C0, GRIS]),
                                legend=alt.Legend(
                                    labelExpr="datum.label == 'true' ? "
                                              "'País' : 'Agregado regional'")),
                tooltip=[alt.Tooltip("Area:N", title="Área"),
                         alt.Tooltip("Importe:Q", format=",.0f"),
                         alt.Tooltip("Peso:Q", format=".1%")],
            ).properties(height=max(220, 42 * len(tabla)))
            st.altair_chart(barras)
        with col_b:
            st.dataframe(
                tabla[["Area", "Importe", "Peso", "Es pais"]],
                hide_index=True,
                column_config={
                    "Area": st.column_config.TextColumn("Área"),
                    "Importe": st.column_config.NumberColumn(format="%,.0f"),
                    "Peso": st.column_config.NumberColumn(format="percent"),
                    "Es pais": st.column_config.CheckboxColumn("País"),
                })
            concentracion = tabla["Peso"].max()
            lider = tabla.iloc[0]["Area"]
            st.caption(
                f"Área de mayor peso: **{lider}**, con el **{concentracion:.1%}** "
                f"de los ingresos. La concentración geográfica es un factor de "
                f"riesgo cuando se combina con exposición regulatoria o arancelaria.")

        # --- Evolucion geografica ---
        evo = seg.evolucion_bloques(paquete, "geografia")
        if evo is not None and evo["pivote"].shape[1] > 1:
            with st.container(border=True):
                st.markdown("**Evolución por área**")
                largo = evo["largo"]
                ch = alt.Chart(largo).mark_bar().encode(
                    alt.X("Periodo:N", title=None, sort=list(evo["pivote"].columns)[::-1]),
                    alt.Y("Importe:Q", title=f"Ingresos ({moneda})", stack="zero",
                          axis=alt.Axis(format="~s", **REJILLA)),
                    color=alt.Color("Bloque:N", title=None,
                                    scale=alt.Scale(scheme="tableau10")),
                    tooltip=["Periodo", "Bloque",
                             alt.Tooltip("Importe:Q", format=",.0f")],
                ).properties(height=320)
                st.altair_chart(ch)

                crec = evo["crecimiento"]
                if not crec.empty:
                    ch2 = alt.Chart(crec).mark_bar().encode(
                        alt.X("Periodo:N", title=None,
                              sort=list(evo["pivote"].columns)[::-1]),
                        _eje_y("Crecimiento:Q", "Crecimiento interanual", formato="+.0%"),
                        xOffset="Bloque:N",
                        color=alt.Color("Bloque:N", title=None,
                                        scale=alt.Scale(scheme="tableau10")),
                        tooltip=["Periodo", "Bloque",
                                 alt.Tooltip("Crecimiento:Q", format="+.1%")],
                    ).properties(height=280)
                    st.altair_chart(ch2)
                    st.caption(
                        "Qué área tira del crecimiento y cuál lo frena. Un "
                        "crecimiento agregado plano puede esconder una región "
                        "creciendo con fuerza y otra cayendo.")

    # =================================================================
    #  LINEAS DE NEGOCIO
    # =================================================================
    marg = seg.margenes_por_segmento(paquete)
    evo_neg = seg.evolucion_bloques(paquete, "negocio")

    if marg is not None or evo_neg is not None:
        st.divider()
        st.markdown("**Líneas de negocio**")

    if marg is not None:
        t = marg["tabla"]
        col_c, col_d = st.columns(2)
        with col_c:
            with st.container(border=True):
                st.markdown(f"*Ingresos por segmento · {marg['periodo']}*")
                ch = alt.Chart(t).mark_bar(color=C0).encode(
                    alt.Y("Segmento:N", sort="-x", title=None),
                    alt.X("Ingresos:Q", title=f"Ingresos ({moneda})",
                          axis=alt.Axis(format="~s", **REJILLA)),
                    tooltip=["Segmento", alt.Tooltip("Ingresos:Q", format=",.0f"),
                             alt.Tooltip("Margen operativo:Q", format=".1%")],
                ).properties(height=max(200, 45 * len(t)))
                st.altair_chart(ch)
        with col_d:
            with st.container(border=True):
                st.markdown("*Margen operativo por segmento*")
                ch = alt.Chart(t).mark_bar().encode(
                    alt.Y("Segmento:N", sort="-x", title=None),
                    alt.X("Margen operativo:Q", title="Margen operativo",
                          axis=alt.Axis(format=".0%", **REJILLA)),
                    color=alt.Color("Margen operativo:Q",
                                    scale=alt.Scale(scheme="redyellowgreen"),
                                    legend=None),
                    tooltip=["Segmento",
                             alt.Tooltip("Margen operativo:Q", format=".1%"),
                             alt.Tooltip("Resultado operativo:Q", format=",.0f")],
                ).properties(height=max(200, 45 * len(t)))
                st.altair_chart(ch)

        st.dataframe(t, hide_index=True, column_config={
            "Ingresos": st.column_config.NumberColumn(format="%,.0f"),
            "Resultado operativo": st.column_config.NumberColumn(format="%,.0f"),
            "Margen operativo": st.column_config.NumberColumn(format="percent"),
        })

        mejor = t.loc[t["Margen operativo"].idxmax()]
        peor = t.loc[t["Margen operativo"].idxmin()]
        if len(t) > 1:
            st.caption(
                f"Mayor margen: **{mejor['Segmento']}** ({mejor['Margen operativo']:.1%}). "
                f"Menor: **{peor['Segmento']}** ({peor['Margen operativo']:.1%}). "
                f"La diferencia es de "
                f"{(mejor['Margen operativo'] - peor['Margen operativo']) * 100:.0f} "
                f"puntos porcentuales: el peso relativo de cada línea condiciona el "
                f"margen consolidado tanto como su evolución individual.")

    if evo_neg is not None and evo_neg["pivote"].shape[1] > 1:
        with st.container(border=True):
            st.markdown("**Evolución por línea de negocio**")
            ch = alt.Chart(evo_neg["largo"]).mark_bar().encode(
                alt.X("Periodo:N", title=None,
                      sort=list(evo_neg["pivote"].columns)[::-1]),
                alt.Y("Importe:Q", title=f"Ingresos ({moneda})", stack="zero",
                      axis=alt.Axis(format="~s", **REJILLA)),
                color=alt.Color("Bloque:N", title=None,
                                scale=alt.Scale(scheme="tableau10")),
                tooltip=["Periodo", "Bloque",
                         alt.Tooltip("Importe:Q", format=",.0f")],
            ).properties(height=320)
            st.altair_chart(ch)
            crec = evo_neg["crecimiento"]
            if not crec.empty:
                st.dataframe(
                    crec.pivot_table(index="Bloque", columns="Periodo",
                                     values="Crecimiento"),
                    column_config={c: st.column_config.NumberColumn(format="percent")
                                   for c in crec["Periodo"].unique()})

    # =================================================================
    #  PRODUCTOS
    # =================================================================
    evo_prod = seg.evolucion_bloques(paquete, "producto")
    if evo_prod is not None:
        st.divider()
        st.markdown("**Desglose por producto o servicio**")
        pv = evo_prod["pivote"]
        periodo = pv.columns[0]
        actual = pv[[periodo]].reset_index()
        actual.columns = ["Producto", "Importe"]
        actual = actual.dropna().sort_values("Importe", ascending=False)
        total = actual["Importe"].sum()
        actual["Peso"] = actual["Importe"] / total if total else np.nan

        col_e, col_f = st.columns([3, 2])
        with col_e:
            ch = alt.Chart(actual).mark_bar(color=C1).encode(
                alt.Y("Producto:N", sort="-x", title=None),
                alt.X("Importe:Q", title=f"Ingresos ({moneda})",
                      axis=alt.Axis(format="~s", **REJILLA)),
                tooltip=["Producto", alt.Tooltip("Importe:Q", format=",.0f"),
                         alt.Tooltip("Peso:Q", format=".1%")],
            ).properties(height=max(200, 40 * len(actual)))
            st.altair_chart(ch)
        with col_f:
            st.dataframe(actual, hide_index=True, column_config={
                "Importe": st.column_config.NumberColumn(format="%,.0f"),
                "Peso": st.column_config.NumberColumn(format="percent"),
            })
        st.caption(f"Periodo {periodo}. Es el desglose de ingresos por categoría de "
                   f"producto o servicio tal y como lo declara la empresa.")
