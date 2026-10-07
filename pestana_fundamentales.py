"""Pestana de FUNDAMENTALES de la app web.

Implementa el subconjunto de la especificacion M1-M54 que es construible con
fuentes publicas verificables. Todo el calculo vive en motor_fundamentales.py;
aqui solo hay interfaz.

Principio rector, tomado de M9: no se confia en ninguna cifra agregada que se
pueda recalcular desde el origen, y las discrepancias se muestran en lugar de
resolverse en silencio.
"""

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

import motor_fundamentales as fund
import pestana_segmentos

C0 = "#1f77b4"
C1 = "#ff7f0e"
VERDE = "#2CA02C"
GRIS = "#7F7F7F"
REJILLA = {"grid": True, "gridColor": "#DDDDDD", "gridOpacity": 0.9}


def _eje_y(campo, titulo, formato=None):
    ejes = dict(REJILLA)
    if formato:
        ejes["format"] = formato
    return alt.Y(campo, title=titulo, axis=alt.Axis(**ejes))


# =============================================================================
#  CARGA CACHEADA
# =============================================================================

@st.cache_data(ttl="6h", show_spinner=False)
def _mapa_cik():
    return fund.mapa_ticker_cik()


@st.cache_data(ttl="6h", show_spinner=False)
def _hechos_sec(cik):
    return fund.companyfacts(cik)


@st.cache_data(ttl="1h", show_spinner=False)
def _estados(simbolo):
    return fund.estados_financieros(simbolo)


@st.cache_data(ttl="1h", show_spinner=False)
def _clasificacion(simbolo):
    return fund.clasificar_negocio(simbolo)


@st.cache_data(ttl="1h", show_spinner=False)
def _consenso(simbolo):
    return fund.consenso(simbolo)


@st.cache_data(ttl="1h", show_spinner=False)
def _insiders(simbolo):
    return fund.insiders(simbolo)


def _formatear(df, col_valor="Valor", col_formato="formato"):
    """Aplica el formato declarado fila a fila y devuelve texto legible."""
    filas = []
    for _, r in df.iterrows():
        v = r[col_valor]
        if v is None or (isinstance(v, float) and not np.isfinite(v)):
            texto = "—"
        else:
            try:
                texto = r[col_formato].format(v)
            except Exception:
                texto = str(v)
        fila = {c: r[c] for c in df.columns if c not in (col_valor, col_formato)}
        fila[col_valor] = texto
        filas.append(fila)
    return pd.DataFrame(filas)


# =============================================================================
#  RENDERIZADO DE LA PESTANA
# =============================================================================

def render(ticker, nombre, moneda, precio_actual):
    st.subheader("Análisis fundamental")
    st.caption(
        "Cifras recalculadas desde los estados financieros. Cuando la SEC publica "
        "el dato primario, se coteja contra el proveedor y se muestran ambos."
    )

    with st.spinner("Descargando estados financieros…"):
        estados = _estados(ticker)

    if estados is None:
        st.info(
            f"Yahoo Finance no publica estados financieros para **{ticker}**. "
            f"Suele ocurrir con ETFs, índices, criptomonedas y divisas, que no son "
            f"empresas y por tanto no tienen contabilidad.", icon=":material/info:")
        return

    clasificacion = _clasificacion(ticker)
    es_fin = clasificacion["es_financiera"]

    with st.spinner("Consultando SEC EDGAR…"):
        cik = _mapa_cik().get(ticker.upper())
        hechos = _hechos_sec(cik) if cik else None

    # -----------------------------------------------------------------
    #  Clasificación del negocio y métodos bloqueados
    # -----------------------------------------------------------------
    with st.container(border=True):
        st.markdown("**Clasificación del negocio**")
        with st.container(horizontal=True):
            st.metric("Sector", clasificacion["sector"], border=True)
            st.metric("Tipo", clasificacion["tipo"], border=True)
            st.metric("Motor aplicable", clasificacion["motor"], border=True)
        if clasificacion["aviso"]:
            st.caption(f":material/info: {clasificacion['aviso']}")
        if clasificacion["prohibidos"]:
            st.warning(
                "**Métodos bloqueados para este tipo de negocio:** "
                + ", ".join(clasificacion["prohibidos"])
                + ". No se calculan porque aplicarlos aquí produciría cifras sin "
                  "significado.", icon=":material/block:")

    # -----------------------------------------------------------------
    #  M9 · Reconciliación
    # -----------------------------------------------------------------
    with st.container(border=True):
        st.markdown("**M9 · Control de calidad y reconciliación de datos**")
        with st.spinner("Reconciliando contra el dato primario…"):
            rec = fund.reconciliar(ticker, estados, hechos)

        if rec["incidencias"]:
            for inc in rec["incidencias"]:
                st.error(inc, icon=":material/warning:")
        else:
            st.success("Todas las comprobaciones de integridad se superan.",
                       icon=":material/check_circle:")

        st.dataframe(rec["comprobaciones"], hide_index=True)

        if np.isfinite(rec["acciones_sec"]):
            with st.container(horizontal=True):
                st.metric("Acciones según el proveedor",
                          f"{rec['acciones_proveedor']:,.0f}"
                          if np.isfinite(rec["acciones_proveedor"]) else "—",
                          border=True)
                st.metric("Acciones declaradas a la SEC",
                          f"{rec['acciones_sec']:,.0f}",
                          f"{rec['acciones_formulario']} presentado el "
                          f"{rec['acciones_presentado'].date()}",
                          delta_color="off", border=True)
            usada = (f"la declarada a la SEC ({rec['acciones']:,.0f})"
                     if rec["fuente_acciones"] == "SEC"
                     else f"la agregada por el proveedor ({rec['acciones']:,.0f})")
            st.caption(
                f"El número de acciones contamina simultáneamente la capitalización, "
                f"el valor de empresa y todos los múltiplos. Aquí se usa **{usada}**. "
                f"Se prefiere el dato de la SEC salvo que la diferencia entre fuentes "
                f"supere el 25%, porque un desvío así suele significar que la empresa "
                f"tiene varias clases de acción y la SEC declara solo una.")
        elif cik is None:
            st.caption(":material/public_off: Este emisor no cotiza en Estados Unidos, "
                       "así que no hay XBRL de SEC EDGAR contra el que cotejar. Las "
                       "cifras proceden solo del proveedor.")

    # El motor ya arbitra que cifra usar (ver reconciliar): no se decide aqui.
    acciones_uso = rec["acciones"]

    # -----------------------------------------------------------------
    #  M1 · Estados financieros
    # -----------------------------------------------------------------
    with st.container(border=True):
        st.markdown("**M1 · Estados financieros declarados**")
        eleccion = st.segmented_control(
            "Estado", ["Cuenta de resultados", "Balance", "Flujo de caja"],
            default="Cuenta de resultados", key="estado_fund")
        periodicidad = st.segmented_control(
            "Periodicidad", ["Anual", "Trimestral"], default="Anual",
            key="periodo_fund")
        clave = {"Cuenta de resultados": "resultados", "Balance": "balance",
                 "Flujo de caja": "flujo"}.get(eleccion, "resultados")
        if periodicidad == "Trimestral":
            clave += "_trim"
        df_estado = estados.get(clave)
        if df_estado is not None and not df_estado.empty:
            mostrar = df_estado.copy()
            mostrar.columns = [str(pd.to_datetime(c).date()) for c in mostrar.columns]
            st.dataframe(mostrar)
            st.caption(f"{len(mostrar)} partidas · {len(mostrar.columns)} periodos.")
        else:
            st.caption("Sin datos para esta combinación.")

        if hechos is not None:
            serie_ing = fund.serie_concepto(
                hechos, ["RevenueFromContractWithCustomerExcludingAssessedTax",
                         "Revenues", "SalesRevenueNet"])
            if serie_ing is not None and not serie_ing.empty:
                st.markdown("**Ingresos tal y como se declararon a la SEC**")
                sec_tab = serie_ing.tail(12)[
                    ["inicio", "fin", "valor", "presentado", "formulario"]].copy()
                sec_tab["fin"] = sec_tab["fin"].dt.date.astype(str)
                sec_tab["presentado"] = sec_tab["presentado"].dt.date.astype(str)
                sec_tab.columns = ["Inicio", "Cierre", "Importe", "Presentado",
                                   "Formulario"]
                st.dataframe(sec_tab, hide_index=True, column_config={
                    "Importe": st.column_config.NumberColumn(format="%,.0f")})
                st.caption(
                    f"Historia disponible desde {serie_ing['fin'].min().date()}. La "
                    f"columna **Presentado** es lo que permite reconstruir qué se "
                    f"sabía en cada fecha: sin ella, cualquier análisis retrospectivo "
                    f"queda contaminado por información que entonces no existía.")

    # -----------------------------------------------------------------
    #  Segmentos de negocio y geografia (M13 ampliado)
    # -----------------------------------------------------------------
    with st.container(border=True):
        pestana_segmentos.render(ticker, nombre, cik, moneda)

    # -----------------------------------------------------------------
    #  Estructura del balance
    # -----------------------------------------------------------------
    comp = fund.composicion_balance(estados)
    if comp is not None:
        with st.container(border=True):
            st.markdown("**Estructura del balance**")
            st.caption(
                "Los dos lados del balance, ejercicio a ejercicio. Las barras suman "
                "siempre el total declarado: lo que no encaja en una partida "
                "identificada se agrupa en «Otros», para que nada quede fuera del "
                "gráfico sin avisar.")

            modo = st.segmented_control(
                "Escala", ["Importe", "Porcentaje"], default="Importe",
                key="escala_balance")

            apilado = "zero" if modo == "Importe" else "normalize"
            eje = (_eje_y("Importe:Q", "Importe", ) if modo == "Importe"
                   else _eje_y("Importe:Q", "Peso sobre el total", formato=".0%"))

            ch = alt.Chart(comp).mark_bar().encode(
                alt.X("Ejercicio:O", title="Ejercicio"),
                alt.Y("Importe:Q", stack=apilado,
                      title=("Importe" if modo == "Importe" else "Peso sobre el total"),
                      axis=alt.Axis(format=(",.0f" if modo == "Importe" else ".0%"),
                                    **REJILLA)),
                color=alt.Color("Partida:N", title=None,
                                sort=fund.ORDEN_BALANCE,
                                scale=alt.Scale(scheme="tableau20")),
                order=alt.Order("Partida:N"),
                column=alt.Column("Lado:N", title=None,
                                  header=alt.Header(labelFontSize=13,
                                                    labelFontWeight="bold")),
                tooltip=[alt.Tooltip("Ejercicio:O"), alt.Tooltip("Lado:N"),
                         alt.Tooltip("Partida:N"),
                         alt.Tooltip("Importe:Q", format=",.0f")],
            ).properties(width=260, height=360)
            st.altair_chart(ch)
            st.caption(
                "En porcentaje se ve la **composición** con independencia del tamaño: "
                "es la vista útil para detectar si el peso del fondo de comercio, del "
                "inventario o de la deuda está creciendo con los años.")

    # -----------------------------------------------------------------
    #  M11 · Calidad del beneficio
    # -----------------------------------------------------------------
    calidad = fund.calidad_beneficio(estados, es_financiera=es_fin)
    if calidad is not None:
        with st.container(border=True):
            st.markdown("**M11 · Calidad del beneficio**")
            st.caption(
                "Determina si el beneficio declarado se convierte en caja. Los "
                "devengos de Sloan miden qué parte del beneficio no ha llegado a "
                "tesorería.")
            for a in calidad["alertas"]:
                st.info(a, icon=":material/info:")

            # Lectura visual de los devengos: cuanto se separa el beneficio del flujo
            bvc = fund.beneficio_frente_a_caja(estados)
            if bvc is not None:
                ch = alt.Chart(bvc).mark_bar().encode(
                    alt.X("Ejercicio:O", title="Ejercicio"),
                    _eje_y("Importe:Q", "Importe"),
                    xOffset=alt.XOffset("Magnitud:N", sort=[
                        "Beneficio neto", "Flujo operativo", "Flujo de caja libre"]),
                    color=alt.Color("Magnitud:N", title=None, sort=[
                        "Beneficio neto", "Flujo operativo", "Flujo de caja libre"],
                        scale=alt.Scale(range=[C1, C0, VERDE])),
                    tooltip=["Ejercicio", "Magnitud",
                             alt.Tooltip("Importe:Q", format=",.0f")],
                ).properties(height=300)
                st.altair_chart(ch)
                st.caption(
                    "Cuanto más separado esté el beneficio (naranja) del flujo "
                    "operativo (azul), mayor peso tienen los devengos: beneficio "
                    "contabilizado que todavía no ha entrado en caja.")

            t = calidad["tabla"]
            st.dataframe(
                t[["Ejercicio", "Ingresos", "Beneficio neto", "Flujo operativo",
                   "Devengos Sloan", "Conversion OCF/BN", "Conversion FCF/BN",
                   "Tasa fiscal efectiva"]],
                hide_index=True,
                column_config={
                    "Ejercicio": st.column_config.NumberColumn(format="%d"),
                    "Ingresos": st.column_config.NumberColumn(format="%,.0f"),
                    "Beneficio neto": st.column_config.NumberColumn(format="%,.0f"),
                    "Flujo operativo": st.column_config.NumberColumn(format="%,.0f"),
                    "Devengos Sloan": st.column_config.NumberColumn(format="percent"),
                    "Conversion OCF/BN": st.column_config.NumberColumn(
                        "Flujo operativo / beneficio", format="%.2f"),
                    "Conversion FCF/BN": st.column_config.NumberColumn(
                        "Flujo libre / beneficio", format="%.2f"),
                    "Tasa fiscal efectiva": st.column_config.NumberColumn(format="percent"),
                })

            ciclo = t[["Ejercicio", "DSO", "DIO", "DPO", "Ciclo de caja"]].dropna(
                subset=["Ciclo de caja"])
            if ciclo.empty:
                st.caption(
                    ":material/block: El ciclo de conversión de efectivo no se "
                    "muestra para este negocio. En entidades financieras las "
                    "cuentas por cobrar y por pagar son saldos de clientes, y en "
                    "negocios sin aprovisionamiento (REITs, por ejemplo) el coste "
                    "de ventas no es representativo. En ambos casos los días de "
                    "cobro y de pago darían cifras de miles de días.")
            else:
                largo = ciclo.melt("Ejercicio", value_vars=["DSO", "DIO", "DPO"],
                                   var_name="Componente", value_name="Dias")
                ch = alt.Chart(largo).mark_bar().encode(
                    alt.X("Ejercicio:O", title="Ejercicio"),
                    _eje_y("Dias:Q", "Días"),
                    xOffset="Componente:N",
                    color=alt.Color("Componente:N", title=None, scale=alt.Scale(
                        domain=["DSO", "DIO", "DPO"], range=[C0, C1, GRIS])),
                    tooltip=["Ejercicio", "Componente",
                             alt.Tooltip("Dias:Q", format=".0f")],
                ).properties(height=280)
                st.altair_chart(ch)
                st.caption(
                    "DSO días de cobro, DIO días de inventario, DPO días de pago. "
                    "El ciclo de caja es DSO + DIO − DPO: cuántos días pasan desde "
                    "que se paga al proveedor hasta que se cobra del cliente.")

    # -----------------------------------------------------------------
    #  M12 · Riesgo contable
    # -----------------------------------------------------------------
    capitalizacion = (precio_actual * acciones_uso
                      if np.isfinite(acciones_uso) else np.nan)
    with st.container(border=True):
        st.markdown("**M12 · Contabilidad agresiva y riesgo contable**")
        pio = fund.piotroski_f(estados)
        alt_z = fund.altman_z(estados, capitalizacion, es_financiera=es_fin)
        ben = fund.beneish_m(estados, es_financiera=es_fin)

        with st.container(horizontal=True):
            if pio:
                st.metric("Piotroski F-Score", f"{pio['puntuacion']} / {pio['maximo']}",
                          "solidez fundamental", delta_color="off", border=True)
            if alt_z and not alt_z.get("bloqueado"):
                st.metric("Altman Z-Score", f"{alt_z['z']:.2f}", alt_z["zona"],
                          delta_color="off", border=True)
            if ben and not ben.get("bloqueado"):
                st.metric("Beneish M-Score", f"{ben['m']:.2f}",
                          "umbral de referencia −1,78", delta_color="off", border=True)

        if pio:
            st.dataframe(pio["tabla"], hide_index=True, column_config={
                "Punto": st.column_config.NumberColumn(format="%d")})

        col_a, col_b = st.columns(2)
        with col_a:
            if alt_z is None:
                st.caption("Altman Z-Score: faltan partidas para calcularlo.")
            elif alt_z.get("bloqueado"):
                st.warning(f"**Altman Z-Score bloqueado.** {alt_z['motivo']}",
                           icon=":material/block:")
            else:
                st.markdown("**Componentes del Z-Score**")
                st.dataframe(alt_z["tabla"], hide_index=True, column_config={
                    "Valor": st.column_config.NumberColumn(format="%.3f"),
                    "Peso": st.column_config.NumberColumn(format="%.2f"),
                    "Aportacion": st.column_config.NumberColumn(
                        "Aportación", format="%.3f")})
        with col_b:
            if ben is None:
                st.caption("Beneish M-Score: faltan partidas para calcularlo.")
            elif ben.get("bloqueado"):
                st.warning(f"**Beneish M-Score bloqueado.** {ben['motivo']}",
                           icon=":material/block:")
            else:
                st.markdown("**Componentes del M-Score**")
                st.dataframe(ben["tabla"], hide_index=True, column_config={
                    "Valor": st.column_config.NumberColumn(format="%.3f"),
                    "Peso": st.column_config.NumberColumn(format="%.3f"),
                    "Aportacion": st.column_config.NumberColumn(
                        "Aportación", format="%.3f")})
                st.caption(
                    f"{ben['componentes_validos']} de {ben['componentes_totales']} "
                    f"componentes con datos. El M-Score es un indicador estadístico "
                    f"de agresividad contable, no una acusación: produce falsos "
                    f"positivos con frecuencia.")

    # -----------------------------------------------------------------
    #  M15 · Retornos sobre el capital
    # -----------------------------------------------------------------
    roic = fund.retornos_capital(estados, es_financiera=es_fin)
    if roic is not None and roic.get("bloqueado"):
        with st.container(border=True):
            st.markdown("**M15 · Retornos sobre el capital**")
            st.warning(f"**ROIC bloqueado.** {roic['motivo']}", icon=":material/block:")
    elif roic is not None and not roic["tabla"]["ROIC"].isna().all():
        with st.container(border=True):
            st.markdown("**M15 · Retornos sobre el capital**")
            st.caption(
                "ROIC = NOPAT ÷ capital invertido, con NOPAT = EBIT × (1 − tasa "
                "fiscal efectiva) y capital invertido = deuda + patrimonio − caja. "
                "Se recalcula desde los estados, no se toma de ningún agregado.")
            with st.container(horizontal=True):
                st.metric("ROIC último ejercicio",
                          f"{roic['roic_actual']:.1%}"
                          if np.isfinite(roic["roic_actual"]) else "—", border=True)
                st.metric("ROIC medio del periodo",
                          f"{roic['roic_medio']:.1%}"
                          if np.isfinite(roic["roic_medio"]) else "—", border=True)
                if np.isfinite(roic["roic_incremental"]):
                    p = roic.get("periodo_incremental")
                    st.metric("ROIC incremental", f"{roic['roic_incremental']:.1%}",
                              f"{p[0]}–{p[1]}" if p else "", delta_color="off",
                              border=True)

            if roic.get("nota_incremental"):
                st.info(roic["nota_incremental"], icon=":material/info:")

            tr = roic["tabla"].dropna(subset=["ROIC"])
            if not tr.empty:
                ch = alt.Chart(tr).mark_bar(color=C0).encode(
                    alt.X("Ejercicio:O", title="Ejercicio"),
                    _eje_y("ROIC:Q", "ROIC", formato=".0%"),
                    tooltip=["Ejercicio", alt.Tooltip("ROIC:Q", format=".2%"),
                             alt.Tooltip("NOPAT:Q", format=",.0f"),
                             alt.Tooltip("Capital invertido:Q", format=",.0f")],
                ).properties(height=260)
                st.altair_chart(ch)

            st.markdown("**Descomposición DuPont**")
            st.dataframe(
                roic["tabla"][["Ejercicio", "Margen neto", "Rotacion de activos",
                               "Apalancamiento", "ROE", "Tasa fiscal usada"]],
                hide_index=True,
                column_config={
                    "Ejercicio": st.column_config.NumberColumn(format="%d"),
                    "Margen neto": st.column_config.NumberColumn(format="percent"),
                    "Rotacion de activos": st.column_config.NumberColumn(
                        "Rotación de activos", format="%.2f"),
                    "Apalancamiento": st.column_config.NumberColumn(format="%.2f"),
                    "ROE": st.column_config.NumberColumn(format="percent"),
                    "Tasa fiscal usada": st.column_config.NumberColumn(format="percent"),
                })

    # -----------------------------------------------------------------
    #  M13 / M14 · Crecimiento y márgenes
    # -----------------------------------------------------------------
    casc = fund.cascada_resultados(estados)
    if casc is not None:
        tabla_c, anio_c = casc
        with st.container(border=True):
            st.markdown(f"**De ingresos a beneficio neto · ejercicio {anio_c}**")
            st.caption(
                "Cascada de la cuenta de resultados: dónde se queda cada euro de "
                "ingresos. Las barras azules son subtotales y las rojas, gastos.")
            ch = alt.Chart(tabla_c).mark_bar().encode(
                alt.X("Concepto:N", sort=None, title=None,
                      axis=alt.Axis(labelAngle=-40)),
                alt.Y("Inicio:Q", title="Importe",
                      axis=alt.Axis(format=",.0f", **REJILLA)),
                alt.Y2("Fin:Q"),
                color=alt.Color("Tipo:N", title=None, scale=alt.Scale(
                    domain=["Subtotal", "Suma", "Resta"],
                    range=[C0, VERDE, "#D62728"])),
                tooltip=[alt.Tooltip("Concepto:N"),
                         alt.Tooltip("Importe:Q", format=",.0f"),
                         alt.Tooltip("Tipo:N")],
            ).properties(height=360)
            st.altair_chart(ch)

    circ = fund.capital_circulante(estados)
    if circ is not None and not circ.empty:
        with st.container(border=True):
            st.markdown("**Capital circulante sobre ingresos**")
            st.caption(
                "Cobros, inventario y pagos medidos como porcentaje de las ventas. "
                "Si estas partidas crecen más deprisa que los ingresos de forma "
                "sostenida, el circulante está absorbiendo caja.")
            ch = alt.Chart(circ).mark_line(point=True, strokeWidth=2).encode(
                alt.X("Ejercicio:O", title="Ejercicio"),
                _eje_y("Sobre ingresos:Q", "Sobre ingresos", formato=".0%"),
                color=alt.Color("Partida:N", title=None, scale=alt.Scale(
                    domain=["Cuentas por cobrar", "Inventario", "Proveedores"],
                    range=[C0, C1, GRIS])),
                tooltip=["Ejercicio", "Partida",
                         alt.Tooltip("Sobre ingresos:Q", format=".1%"),
                         alt.Tooltip("Importe:Q", format=",.0f")],
            ).properties(height=280)
            st.altair_chart(ch)

    crecim = fund.crecimiento_margenes(estados)
    if crecim is not None:
        with st.container(border=True):
            st.markdown("**M13 y M14 · Crecimiento y márgenes**")
            st.dataframe(crecim["tabla"], hide_index=True, column_config={
                "Ejercicio": st.column_config.NumberColumn(format="%d"),
                "Ingresos": st.column_config.NumberColumn(format="%,.0f"),
                "Crecimiento": st.column_config.NumberColumn(format="percent"),
                "Margen bruto": st.column_config.NumberColumn(format="percent"),
                "Margen operativo": st.column_config.NumberColumn(format="percent"),
                "Margen neto": st.column_config.NumberColumn(format="percent"),
            })
            marg = crecim["tabla"].melt(
                "Ejercicio",
                value_vars=["Margen bruto", "Margen operativo", "Margen neto"],
                var_name="Margen", value_name="Valor").dropna()
            if not marg.empty:
                ch = alt.Chart(marg).mark_line(point=True, strokeWidth=2).encode(
                    alt.X("Ejercicio:O", title="Ejercicio"),
                    _eje_y("Valor:Q", "Margen", formato=".0%"),
                    color=alt.Color("Margen:N", title=None, scale=alt.Scale(
                        domain=["Margen bruto", "Margen operativo", "Margen neto"],
                        range=[C0, C1, VERDE])),
                    tooltip=["Ejercicio", "Margen",
                             alt.Tooltip("Valor:Q", format=".2%")],
                ).properties(height=280)
                st.altair_chart(ch)

            inc = crecim["incremental"].dropna(subset=["Margen incremental"])
            if not inc.empty:
                st.markdown("**Margen incremental**")
                st.dataframe(inc, hide_index=True, column_config={
                    "Ejercicio": st.column_config.NumberColumn(format="%d"),
                    "Variacion de ingresos": st.column_config.NumberColumn(
                        "Variación de ingresos", format="%,.0f"),
                    "Variacion de resultado operativo": st.column_config.NumberColumn(
                        "Variación de resultado operativo", format="%,.0f"),
                    "Margen incremental": st.column_config.NumberColumn(format="percent"),
                })
                st.caption(
                    "Cuánto resultado operativo aporta cada unidad monetaria adicional "
                    "de ingresos. En negocios de margen estrecho es la palanca que más "
                    "mueve el beneficio.")

    # -----------------------------------------------------------------
    #  M16 · Solvencia
    # -----------------------------------------------------------------
    solv = fund.solvencia(estados)
    if solv is not None:
        with st.container(border=True):
            st.markdown("**M16 · Balance, solvencia y liquidez**")
            tabla_s = solv["tabla"]
            if es_fin:
                tabla_s = tabla_s[~tabla_s["Metrica"].isin(
                    ["Deuda neta", "Deuda neta / EBITDA", "Flujo operativo / deuda"])]
                st.caption(":material/block: En una entidad financiera la deuda es "
                           "materia prima del negocio, no apalancamiento: las métricas "
                           "de deuda neta quedan excluidas.")
            st.dataframe(_formatear(tabla_s), hide_index=True)

            apal = fund.evolucion_apalancamiento(estados)
            if apal is not None and not es_fin:
                largo_a = apal.melt("Ejercicio",
                                    value_vars=["Deuda total", "Caja", "Deuda neta"],
                                    var_name="Concepto", value_name="Importe").dropna()
                barras = alt.Chart(largo_a).mark_bar().encode(
                    alt.X("Ejercicio:O", title="Ejercicio"),
                    _eje_y("Importe:Q", "Importe"),
                    xOffset=alt.XOffset("Concepto:N",
                                        sort=["Deuda total", "Caja", "Deuda neta"]),
                    color=alt.Color("Concepto:N", title=None,
                                    sort=["Deuda total", "Caja", "Deuda neta"],
                                    scale=alt.Scale(range=["#D62728", VERDE, C0])),
                    tooltip=["Ejercicio", "Concepto",
                             alt.Tooltip("Importe:Q", format=",.0f")],
                ).properties(height=300)
                st.altair_chart(barras)
                ratio = apal.dropna(subset=["Deuda neta / EBITDA"])
                if not ratio.empty:
                    linea = alt.Chart(ratio).mark_line(
                        point=True, strokeWidth=2.5, color=C0).encode(
                        alt.X("Ejercicio:O", title="Ejercicio"),
                        _eje_y("Deuda neta / EBITDA:Q", "Veces EBITDA"),
                        tooltip=["Ejercicio",
                                 alt.Tooltip("Deuda neta / EBITDA:Q", format=".2f")],
                    )
                    umbral = alt.Chart(pd.DataFrame({"y": [3.0]})).mark_rule(
                        color="#D62728", strokeDash=[6, 4]).encode(y="y:Q")
                    st.altair_chart((linea + umbral).properties(height=220))
                    st.caption(
                        "La línea roja marca las 3 veces EBITDA, referencia habitual "
                        "a partir de la cual el apalancamiento empieza a condicionar "
                        "la flexibilidad financiera. No es un umbral universal: en "
                        "negocios regulados o con flujos muy estables se tolera más.")

            if np.isfinite(solv.get("autonomia_trimestres", np.nan)):
                st.info(
                    f"Con flujo de caja libre negativo y la caja actual, la autonomía "
                    f"estimada es de **{solv['autonomia_trimestres']:.1f} trimestres** "
                    f"al ritmo de consumo del último ejercicio.", icon=":material/info:")

    # -----------------------------------------------------------------
    #  M17 · Asignación de capital
    # -----------------------------------------------------------------
    asig = fund.asignacion_capital(estados, precio_actual)
    if asig is not None and not asig["tabla"].empty:
        with st.container(border=True):
            st.markdown("**M17 · Flujo de caja y asignación de capital**")

            puente = fund.puente_flujo_caja(estados)
            if puente is not None:
                tabla_p, anio_p = puente
                st.markdown(f"*Del flujo operativo al accionista · ejercicio {anio_p}*")
                ch = alt.Chart(tabla_p).mark_bar().encode(
                    alt.X("Concepto:N", sort=None, title=None,
                          axis=alt.Axis(labelAngle=-40)),
                    alt.Y("Inicio:Q", title="Importe",
                          axis=alt.Axis(format=",.0f", **REJILLA)),
                    alt.Y2("Fin:Q"),
                    color=alt.Color("Tipo:N", title=None, scale=alt.Scale(
                        domain=["Subtotal", "Suma", "Resta"],
                        range=[C0, VERDE, "#D62728"])),
                    tooltip=[alt.Tooltip("Concepto:N"),
                             alt.Tooltip("Importe:Q", format=",.0f")],
                ).properties(height=320)
                st.altair_chart(ch)
                st.caption(
                    "Cuánto genera el negocio, cuánto se reinvierte y cuánto queda "
                    "para el accionista. Si las barras rojas posteriores al flujo "
                    "libre lo superan, la retribución se está financiando con deuda "
                    "o con caja acumulada.")

            st.dataframe(asig["tabla"], hide_index=True, column_config={
                "Ejercicio": st.column_config.NumberColumn(format="%d"),
                "Flujo operativo": st.column_config.NumberColumn(format="%,.0f"),
                "Capex": st.column_config.NumberColumn(format="%,.0f"),
                "Adquisiciones": st.column_config.NumberColumn(format="%,.0f"),
                "Recompras": st.column_config.NumberColumn(format="%,.0f"),
                "Dividendos": st.column_config.NumberColumn(format="%,.0f"),
                "Retribucion en acciones": st.column_config.NumberColumn(
                    "Retribución en acciones", format="%,.0f"),
                "Acciones medias": st.column_config.NumberColumn(format="%,.0f"),
            })
            if np.isfinite(asig["dilucion_acumulada"]):
                signo = "dilución" if asig["dilucion_acumulada"] > 0 else "reducción"
                st.caption(
                    f"Variación acumulada del número medio de acciones en el periodo: "
                    f"**{asig['dilucion_acumulada']:+.2%}** ({signo}). Una empresa que "
                    f"emite más de lo que recompra está diluyendo mientras anuncia "
                    f"recompras.")
            usos = asig["tabla"].melt(
                "Ejercicio",
                value_vars=["Capex", "Recompras", "Dividendos", "Adquisiciones"],
                var_name="Destino", value_name="Importe").dropna()
            if not usos.empty and usos["Importe"].sum() > 0:
                ch = alt.Chart(usos).mark_bar().encode(
                    alt.X("Ejercicio:O", title="Ejercicio"),
                    _eje_y("Importe:Q", "Importe"),
                    color=alt.Color("Destino:N", title=None),
                    tooltip=["Ejercicio", "Destino",
                             alt.Tooltip("Importe:Q", format=",.0f")],
                ).properties(height=280)
                st.altair_chart(ch)

    # -----------------------------------------------------------------
    #  M20 · Múltiplos  +  M19 · DCF inverso
    # -----------------------------------------------------------------
    if np.isfinite(acciones_uso):
        mult = fund.multiplos(ticker, estados, precio_actual, acciones_uso)
        with st.container(border=True):
            st.markdown("**M20 · Valoración relativa**")
            tabla_m = mult["tabla"]
            if clasificacion["prohibidos"]:
                tabla_m = tabla_m[~tabla_m["Multiplo"].isin(clasificacion["prohibidos"])]
            st.dataframe(_formatear(tabla_m), hide_index=True)
            fuente = ("declarado a la SEC" if rec["fuente_acciones"] == "SEC"
                      else "agregado por el proveedor")
            st.caption(
                f"Valor de empresa construido explícitamente: capitalización + deuda "
                f"− caja + minoritarios. La capitalización usa el número de acciones "
                f"**{fuente}** ({acciones_uso:,.0f}).")
            st.caption(
                ":material/warning: Sin percentil histórico ni mediana sectorial, un "
                "múltiplo aislado dice poco: un PER de 28 puede ser alto o bajo según "
                "dónde caiga en la historia del propio valor. Esa comparación (M20 "
                "completo y M21) requiere un universo de comparables que esta "
                "herramienta no construye.")

        with st.container(border=True):
            st.markdown("**M19 · DCF inverso**")
            st.caption(
                "En lugar de preguntar cuánto vale, calcula qué crecimiento hay que "
                "creer para justificar el precio actual. Es una afirmación falsable "
                "que se puede contrastar con la historia de la propia empresa.")
            col_w, col_g = st.columns(2)
            with col_w:
                wacc = st.slider("Coste del capital (WACC)", 4.0, 15.0, 9.0, 0.5,
                                 format="%.1f%%", key="wacc_fund") / 100
            with col_g:
                g_term = st.slider("Crecimiento perpetuo", 0.0, 4.0, 2.5, 0.1,
                                   format="%.1f%%", key="gterm_fund") / 100

            fcf_base = solv["fcf"] if solv else np.nan
            if not np.isfinite(fcf_base) or fcf_base <= 0:
                st.info(
                    "El flujo de caja libre del último ejercicio no es positivo, así "
                    "que el DCF inverso no tiene solución interpretable. Es lo "
                    "habitual en empresas en pérdidas, en fuerte inversión o en la "
                    "parte baja de su ciclo.", icon=":material/info:")
            else:
                dcf = fund.dcf_inverso(
                    mult["capitalizacion"], fcf_base, wacc=wacc, g_terminal=g_term,
                    deuda_neta=(solv["deuda_neta"]
                                if solv and np.isfinite(solv["deuda_neta"]) else 0.0))
                if dcf is None:
                    st.info("No calculable con los datos disponibles.",
                            icon=":material/info:")
                elif dcf.get("fuera_de_rango"):
                    st.warning(
                        f"El crecimiento implícito queda **{dcf['fuera_de_rango']}** "
                        f"del rango explorado (−50% a +150% anual). Con estos "
                        f"supuestos el modelo no puede reconciliar el precio.",
                        icon=":material/warning:")
                else:
                    with st.container(horizontal=True):
                        st.metric("Crecimiento anual implícito",
                                  f"{dcf['crecimiento_implicito']:+.1%}",
                                  f"durante {dcf['anios']} años", delta_color="off",
                                  border=True)
                        st.metric("Peso del valor terminal",
                                  f"{dcf['peso_terminal']:.0%}", "sobre el valor total",
                                  delta_color="off", border=True)
                        st.metric("Flujo de caja libre de partida",
                                  f"{fcf_base:,.0f}", border=True)
                    st.caption(
                        f"Con un coste de capital del {wacc:.1%} y crecimiento "
                        f"perpetuo del {g_term:.1%}, el precio actual equivale a "
                        f"suponer que el flujo de caja libre crece un "
                        f"**{dcf['crecimiento_implicito']:+.1%} anual durante "
                        f"{dcf['anios']} años**. La comprobación útil es contrastar "
                        f"esa cifra con lo que la empresa ha logrado históricamente y "
                        f"con lo que ha logrado su sector.")
                    if dcf["peso_terminal"] > 0.75:
                        st.warning(
                            f"El **{dcf['peso_terminal']:.0%}** del valor procede del "
                            f"valor terminal, por encima del umbral del 75%. Cuando "
                            f"eso ocurre el modelo está diciendo poco: casi todo "
                            f"depende de un supuesto sobre un futuro lejano.",
                            icon=":material/warning:")

    # -----------------------------------------------------------------
    #  M3 · Consenso
    # -----------------------------------------------------------------
    cons = _consenso(ticker)
    if cons is not None:
        with st.container(border=True):
            st.markdown("**M3 · Estimaciones y consenso**")
            st.error(
                "**Limitación crítica documentada.** Yahoo Finance no publica ni la "
                "fecha de actualización de cada estimación ni la guía de la compañía. "
                "Sin ellas es imposible verificar si el consenso está vigente, que es "
                "justamente lo que exige M3 antes de usar la palabra «sorpresa». "
                "Interpreta estas cifras con esa reserva.", icon=":material/warning:")

            if np.isfinite(cons.get("amplitud_revision", np.nan)):
                st.metric("Amplitud de revisión a 30 días",
                          f"{cons['amplitud_revision']:.0%}",
                          "proporción de revisiones al alza", delta_color="off",
                          border=True)

            if cons.get("estimaciones") is not None:
                st.markdown("**Estimaciones de beneficio por acción**")
                st.dataframe(cons["estimaciones"], column_config={
                    "avg": st.column_config.NumberColumn("Media", format="%.3f"),
                    "low": st.column_config.NumberColumn("Mínimo", format="%.3f"),
                    "high": st.column_config.NumberColumn("Máximo", format="%.3f"),
                    "yearAgoEps": st.column_config.NumberColumn("Hace un año", format="%.3f"),
                    "numberOfAnalysts": st.column_config.NumberColumn("Analistas", format="%d"),
                    "growth": st.column_config.NumberColumn("Crecimiento", format="%.3f"),
                })
                try:
                    n_min = int(cons["estimaciones"]["numberOfAnalysts"].min())
                    if n_min < 5:
                        st.caption(
                            f":material/warning: Solo {n_min} analistas en la "
                            f"estimación con menos cobertura. Un consenso de pocos "
                            f"contribuyentes tiene poca capacidad informativa.")
                except Exception:
                    pass

            if cons.get("revisiones") is not None:
                st.markdown("**Revisiones de analistas**")
                st.dataframe(cons["revisiones"], column_config={
                    "upLast7days": st.column_config.NumberColumn("Al alza 7d", format="%d"),
                    "upLast30days": st.column_config.NumberColumn("Al alza 30d", format="%d"),
                    "downLast30days": st.column_config.NumberColumn("A la baja 30d", format="%d"),
                    "downLast7Days": st.column_config.NumberColumn("A la baja 7d", format="%d"),
                })
                st.caption(
                    "La amplitud de revisión (cuántos revisan, no cuánto) tiene "
                    "históricamente más contenido informativo que la magnitud media.")

            obj = cons.get("objetivos")
            if isinstance(obj, dict) and obj:
                st.markdown("**Objetivos de precio de analistas**")
                with st.container(horizontal=True):
                    for etiqueta, clave_o in [("Mínimo", "low"), ("Mediana", "median"),
                                              ("Media", "mean"), ("Máximo", "high")]:
                        if obj.get(clave_o) is not None:
                            st.metric(etiqueta, f"{obj[clave_o]:,.2f}", border=True)
                st.caption(
                    ":material/warning: Yahoo no publica la fecha en que se fijó cada "
                    "objetivo. Sin ella no se puede distinguir un objetivo que "
                    "anticipó el movimiento de otro que simplemente lo siguió.")

    # -----------------------------------------------------------------
    #  M5 · Insiders
    # -----------------------------------------------------------------
    ins = _insiders(ticker)
    if ins is not None and ins.get("resumen") is not None:
        with st.container(border=True):
            st.markdown("**M5 · Propiedad e insiders**")
            st.dataframe(ins["resumen"], hide_index=True)
            st.caption(
                "Yahoo agrega las operaciones de los últimos 6 meses. No distingue "
                "las compras discrecionales de las ventas programadas bajo planes "
                "10b5-1, que es la separación que da valor informativo a este dato.")
            if ins.get("institucionales") is not None:
                with st.expander("Principales accionistas institucionales"):
                    st.dataframe(ins["institucionales"], hide_index=True)

    # -----------------------------------------------------------------
    #  Cobertura de la especificación
    # -----------------------------------------------------------------
    with st.container(border=True):
        st.markdown("**Cobertura de la especificación M1–M54**")
        st.caption(
            "Qué módulos están implementados con datos reales, cuáles parcialmente y "
            "cuáles requieren fuentes de pago. Se declara de forma explícita para que "
            "ninguna ausencia se confunda con un resultado.")
        cob = fund.tabla_cobertura()
        resumen = cob["Cobertura"].value_counts()
        with st.container(horizontal=True):
            st.metric("Implementados", int(resumen.get("Si", 0)), border=True)
            st.metric("Parciales", int(resumen.get("Parcial", 0)), border=True)
            st.metric("No cubiertos", int(resumen.get("No", 0)), border=True)
        filtro = st.multiselect("Filtrar por cobertura", ["Si", "Parcial", "No"],
                                default=["Si", "Parcial", "No"], key="filtro_cobertura")
        st.dataframe(cob[cob["Cobertura"].isin(filtro)], hide_index=True)
        st.caption(
            "Los módulos M46 a M50 de la capa de decisión (veredicto de compra o "
            "venta, dimensionamiento de posición y diario de operaciones) quedan "
            "**excluidos deliberadamente**: emiten recomendaciones explícitas, lo que "
            "entra en conflicto con el requisito de neutralidad de esta herramienta.")
