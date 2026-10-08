"""Pestaña de DESCUENTO DE FLUJOS DE CAJA (DCF) de la app web.

Funciona de forma INDEPENDIENTE del generador de informes: tiene su propio
cuadro de valor, sus propios supuestos y su propia exportacion a Excel. Se
puede valorar aqui una empresa distinta de la que se este analizando en el
resto de la aplicacion sin que una cosa afecte a la otra.

Todo el calculo vive en motor_dcf.py; aqui solo hay interfaz.
"""

import numpy as np
import pandas as pd
import streamlit as st

import motor_dcf as dcf
import motor_fundamentales as fund

C0 = "#1f77b4"
VERDE = "#2CA02C"
ROJO = "#D62728"
AMBAR = "#FFA500"
GRIS = "#7F7F7F"

_ESTADO_COLOR = {"OK": VERDE, "AVISO": AMBAR, "SUPUESTO": AMBAR, "DERIVADO": C0,
                 "CORREGIDO": AMBAR, "FALLA": ROJO, "FALTA": ROJO, "NO COMPARABLE": GRIS}


# =============================================================================
#  CARGA CACHEADA
# =============================================================================

@st.cache_data(ttl="1h", show_spinner=False)
def _estados(simbolo):
    return fund.estados_financieros(simbolo)


@st.cache_data(ttl="1h", show_spinner=False)
def _clasificacion(simbolo):
    return fund.clasificar_negocio(simbolo)


@st.cache_data(ttl="30m", show_spinner=False)
def _analizar(simbolo, supuestos, prima):
    """El resultado se cachea por (valor, supuestos, prima).

    Los supuestos llegan como tupla ordenada y no como diccionario porque
    Streamlit necesita poder aplicarles un hash para usarlos como clave.
    """
    return dcf.analizar(simbolo, dict(supuestos), prima=prima)


def _fmt(x, decimales=2, sufijo=""):
    """Numero formateado, o el guion largo si no hay dato.

    El guion distingue "no hay dato" de "el dato es cero", que se imprime como
    0,00 con normalidad.
    """
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if not np.isfinite(v):
        return "—"
    return f"{v:,.{decimales}f}{sufijo}"


def _pct(x, decimales=1):
    try:
        if x is None or not np.isfinite(float(x)):
            return "—"
        return f"{float(x) * 100:.{decimales}f}%"
    except (TypeError, ValueError):
        return "—"


def _millones(x, moneda=""):
    """Cifra grande en la escala que la hace legible, sin perder el signo."""
    try:
        v = float(x)
        if not np.isfinite(v):
            return "—"
    except (TypeError, ValueError):
        return "—"
    signo = "-" if v < 0 else ""
    a = abs(v)
    if a >= 1e12:
        return f"{signo}{a / 1e12:,.2f} B{moneda}"
    if a >= 1e9:
        return f"{signo}{a / 1e9:,.2f} mil M{moneda}"
    if a >= 1e6:
        return f"{signo}{a / 1e6:,.1f} M{moneda}"
    return f"{signo}{a:,.0f}{moneda}"


def _tabla_detalle(df):
    """Prepara una tabla Concepto/Valor/Origen/Nota para pintarla.

    La columna Valor mezcla por naturaleza texto ("The Coca-Cola Company") y
    cifras de ordenes de magnitud muy distintos (un valor por accion de 96 junto
    a un valor de empresa de 400.000 millones). Con esa mezcla, Arrow no puede
    tipar la columna y st.column_config.NumberColumn no llega a aplicarse, de
    modo que las cifras salian sin formato. Se formatea aqui, en Python, donde si
    se puede decidir escala caso por caso.
    """
    salida = df.copy()

    def _mostrar(v):
        if isinstance(v, str) or v is None:
            return v if v is not None else ""
        try:
            f = float(v)
        except (TypeError, ValueError):
            return str(v)
        if not np.isfinite(f):
            return "—"
        if f != 0 and abs(f) < 1:          # tasas y pesos
            return f"{f:.2%}"
        if abs(f) >= 1e6:                  # magnitudes de balance
            return _millones(f)
        return f"{f:,.2f}"

    salida["Valor"] = salida["Valor"].map(_mostrar)
    return salida


# =============================================================================
#  RENDER
# =============================================================================

def render(ticker_defecto="AAPL"):
    st.subheader("Descuento de flujos de caja (DCF)")
    st.caption(
        "Cinco metodos de valoracion sobre los estados financieros publicados. "
        "Esta pestaña es independiente del resto de la aplicacion: puedes valorar aqui "
        "una empresa distinta de la que estes analizando arriba."
    )

    col_t, col_b = st.columns([3, 1])
    with col_t:
        simbolo = st.text_input(
            "Valor a valorar", value=st.session_state.get("dcf_ticker", ticker_defecto),
            key="dcf_ticker_input",
            help="Solo empresas: un DCF necesita cuenta de resultados, balance y estado de "
                 "flujos. Los indices, divisas, materias primas y ETFs no los tienen.",
        ).strip().upper()
    with col_b:
        st.write("")
        lanzar = st.button("Valorar", width="stretch", icon=":material/calculate:")

    if lanzar:
        st.session_state["dcf_ticker"] = simbolo
        st.session_state["dcf_lanzado"] = True

    if not st.session_state.get("dcf_lanzado"):
        st.info("Escribe un ticker y pulsa **Valorar**.", icon=":material/info:")
        _explicacion_metodos()
        return

    simbolo = st.session_state.get("dcf_ticker", simbolo)

    # --- Supuestos ---------------------------------------------------------
    with st.expander("Supuestos de la valoracion", expanded=False):
        st.caption(
            "Los valores de partida se derivan de la propia empresa. Todo lo que cambies "
            "aqui se recalcula al instante y viaja al Excel rotulado como supuesto."
        )
        c1, c2, c3 = st.columns(3)
        anios = c1.slider("Años de proyeccion explicita", 5, 15,
                          dcf.ANIOS_PROYECCION_DEFECTO, key="dcf_anios")
        prima = c2.slider("Prima de riesgo de mercado (%)", 3.0, 8.0,
                          dcf.PRIMA_RIESGO_DEFECTO * 100, step=0.1, key="dcf_prima") / 100
        mitad = c3.checkbox("Convencion de mitad de periodo", value=True, key="dcf_mitad",
                            help="Descuenta en t-0,5. Reconoce que la caja entra a lo largo "
                                 "del año y no el 31 de diciembre.")
        c4, c5, c6 = st.columns(3)
        g_ini_m = c4.number_input("Crecimiento año 1 (%) · 0 = automatico", -20.0, 60.0, 0.0,
                                  step=0.5, key="dcf_gini")
        g_term_m = c5.number_input("Crecimiento perpetuo (%) · 0 = automatico", 0.0, 6.0, 0.0,
                                   step=0.1, key="dcf_gterm")
        margen_m = c6.number_input("Margen EBIT objetivo (%) · 0 = automatico", 0.0, 80.0, 0.0,
                                   step=0.5, key="dcf_margen")

    supuestos = {"anios": anios, "mitad_periodo": mitad}
    if g_ini_m != 0.0:
        supuestos["g_inicial"] = g_ini_m / 100
    if g_term_m != 0.0:
        supuestos["g_terminal"] = g_term_m / 100
    if margen_m != 0.0:
        supuestos["margen_objetivo"] = margen_m / 100

    with st.spinner(f"Descargando estados financieros y valorando {simbolo}…"):
        try:
            res = _analizar(simbolo, tuple(sorted(supuestos.items())), prima)
        except Exception as exc:
            st.error(f"No se pudo completar la valoracion de {simbolo}: {exc}",
                     icon=":material/error:")
            return

    if res.get("error"):
        st.error(f"**{simbolo}** — {res['error']}", icon=":material/error:")
        return

    _cabecera(res)
    _avisos(res)
    _resumen_metodos(res)
    _detalle_por_metodo(res)
    _proyeccion(res)
    _sensibilidad(res)
    _diagnostico(res)
    _descarga(res)


# =============================================================================
#  BLOQUES
# =============================================================================

def _cabecera(res):
    m, c, s = res["mercado"], res["coste"], res["supuestos"]
    est = dcf.estadisticos_valoracion(res["metodos"], m)

    st.markdown(f"### {m['nombre']} · {res['simbolo']}")
    st.caption(f"{m['sector']} · {m['industria']} — clasificado como **{res['clasificacion']['tipo']}** · "
               f"moneda de los estados: {m['moneda'] or 'no publicada'} · "
               f"ultimo ejercicio: {res['base']['anio']}")

    with st.container(horizontal=True):
        st.metric("Precio de mercado", _fmt(m["precio"]), border=True)
        st.metric("Valor mediano (DCF)", _fmt(est["mediana"]), border=True,
                  help=f"Mediana de los {est['n']} metodos aplicables. Mediana y no media: "
                       f"un metodo con un supuesto extremo arrastraria la media.")
        pot = est["potencial_mediana"]
        hay_pot = isinstance(pot, float) and np.isfinite(pot)
        st.metric("Potencial", _pct(pot), border=True,
                  delta=("infravalorada" if pot > 0 else "sobrevalorada") if hay_pot else None,
                  delta_color="normal")
        st.metric("WACC", _pct(c["wacc"], 2), border=True,
                  help=f"Ke {_pct(c['ke'], 2)} · Kd despues de impuestos "
                       f"{_pct(c['kd_despues_impuestos'], 2)}")
        st.metric("Crecimiento perpetuo", _pct(s["g_terminal"], 2), border=True,
                  help=f"Acotado al tipo sin riesgo ({_pct(res['rf'], 2)}).")

    if est["n"]:
        st.caption(f"Rango entre metodos: **{_fmt(est['minimo'])} – {_fmt(est['maximo'])}**. "
                   f"Una horquilla ancha no es un fallo del modelo: significa que los metodos "
                   f"discrepan sobre esta empresa, y saberlo vale mas que un numero unico.")


def _avisos(res):
    for aviso in res.get("avisos_sector", []):
        st.warning(aviso, icon=":material/category:")
    for err in res.get("errores_supuestos", []):
        st.error(err, icon=":material/error:")
    for aviso in res.get("avisos_supuestos", []):
        st.warning(aviso, icon=":material/warning:")
    if res["coste"].get("aviso_kd"):
        st.info(res["coste"]["aviso_kd"], icon=":material/build:")

    bloqueados = [(m["metodo"], m["motivo"]) for m in res["metodos"] if not m["aplicable"]]
    if bloqueados:
        with st.expander(f"{len(bloqueados)} metodo(s) no aplicable(s) — por que"):
            for nombre, motivo in bloqueados:
                st.markdown(f"**{nombre}** — {motivo}")
            st.caption(
                "Un metodo bloqueado no devuelve cifra. Publicar un numero imposible con una "
                "nota al pie no ayuda: el numero es lo que se recuerda y la nota lo que se olvida."
            )


def _resumen_metodos(res):
    st.markdown("#### Los cinco metodos")
    tabla = res["resumen"].copy()
    precio = res["mercado"]["precio"]

    st.dataframe(
        tabla, hide_index=True, width="stretch",
        column_config={
            "Metodo": st.column_config.TextColumn(width="medium"),
            "Aplicable": st.column_config.TextColumn(width="small"),
            "Valor por accion": st.column_config.NumberColumn(format="%.2f"),
            "Precio de mercado": st.column_config.NumberColumn(format="%.2f"),
            "Potencial": st.column_config.NumberColumn(format="percent"),
            "Peso del valor terminal": st.column_config.NumberColumn(format="percent"),
            "Tasa de descuento": st.column_config.NumberColumn(format="percent"),
            "Motivo si no aplica": st.column_config.TextColumn(width="large"),
        },
    )

    aplicables = tabla[tabla["Aplicable"] == "Si"].dropna(subset=["Valor por accion"])
    if not aplicables.empty and np.isfinite(precio or np.nan):
        grafico = aplicables[["Metodo", "Valor por accion"]].copy()
        # regex=False es obligatorio: por defecto pandas trata el separador como
        # expresion regular, y " (" es un parentesis de grupo sin cerrar, asi que
        # revienta con PatternError para CUALQUIER valor. El .split() de Python
        # que se usa en el resto del modulo no tiene este problema porque nunca
        # interpreta el separador.
        grafico["Metodo"] = grafico["Metodo"].str.split(" (", regex=False).str[0]
        grafico = pd.concat([grafico, pd.DataFrame(
            [{"Metodo": "Precio de mercado", "Valor por accion": precio}])])
        st.bar_chart(grafico.set_index("Metodo"), horizontal=True, height=260,
                     color=C0, x_label="Valor por accion", y_label="")


def _detalle_por_metodo(res):
    st.markdown("#### Como sale cada cifra")
    moneda = res["mercado"]["moneda"] or ""
    por_nombre = {m["metodo"].split(" (")[0]: m for m in res["metodos"]}
    pestanas = st.tabs(["FCFF", "FCFE", "DDM", "APV", "EVA"])

    constructores = {
        "FCFF": dcf._detalle_fcff, "FCFE": dcf._detalle_generico, "DDM": dcf._detalle_ddm,
        "APV": dcf._detalle_apv, "EVA": dcf._detalle_eva,
    }
    for pestana, clave in zip(pestanas, ["FCFF", "FCFE", "DDM", "APV", "EVA"]):
        with pestana:
            m = por_nombre.get(clave)
            if m is None:
                st.info("Metodo no calculado.")
                continue
            if not m["aplicable"]:
                st.warning(f"**No aplicable.** {m['motivo']}", icon=":material/block:")
                continue
            detalle = _tabla_detalle(constructores[clave](m, moneda))
            st.dataframe(detalle, hide_index=True, width="stretch",
                         column_config={
                             "Concepto": st.column_config.TextColumn(width="medium"),
                             "Valor": st.column_config.TextColumn(width="small"),
                             "Nota": st.column_config.TextColumn(width="large")})
            for aviso in m.get("avisos", []):
                st.warning(aviso, icon=":material/warning:")
            if m.get("tabla") is not None and not m["tabla"].empty:
                with st.expander("Tabla año a año"):
                    st.dataframe(m["tabla"], hide_index=True, width="stretch")


def _proyeccion(res):
    with st.expander("Proyeccion del flujo libre, año a año"):
        st.caption("Cada linea se reconstruye desde la anterior: ingresos x margen = EBIT, "
                   "EBIT x (1 - tasa fiscal) = NOPAT, y de ahi al flujo restando inversion.")
        st.dataframe(res["proyeccion"], hide_index=True, width="stretch",
                     column_config={
                         "Crecimiento ingresos": st.column_config.NumberColumn(format="percent"),
                         "Margen EBIT": st.column_config.NumberColumn(format="percent"),
                         "Tasa fiscal": st.column_config.NumberColumn(format="percent"),
                     })
    with st.expander("Flujo libre historico realmente publicado"):
        st.caption("Sirve de contraste: si el FCFF proyectado del año 1 no se parece al de los "
                   "ejercicios reales, el punto de partida esta mal elegido.")
        st.dataframe(res["historico_fcff"], hide_index=True, width="stretch",
                     column_config={"Tasa fiscal efectiva":
                                    st.column_config.NumberColumn(format="percent")})


def _sensibilidad(res):
    sens = res.get("sensibilidad")
    if sens is None or sens.empty:
        return
    st.markdown("#### Sensibilidad al WACC y al crecimiento perpetuo")
    st.caption("Las dos variables que mas mueven el resultado, y las dos que son supuestos y no "
               "datos. Las casillas vacias son combinaciones donde el crecimiento alcanza a la "
               "tasa de descuento y la perpetuidad deja de converger.")
    mostrar = sens.copy()
    mostrar["WACC"] = mostrar["WACC"].map(lambda v: f"{v:.2%}")
    st.dataframe(mostrar.set_index("WACC").style.format("{:,.2f}", na_rep="—")
                 .background_gradient(cmap="RdYlGn", axis=None), width="stretch")


def _diagnostico(res):
    st.markdown("#### Diagnostico")
    diag = dcf.diagnostico(res)
    fallos = diag[diag["Estado"].isin(["FALLA", "FALTA"])]
    avisos = diag[diag["Estado"].isin(["AVISO", "SUPUESTO", "CORREGIDO"])]
    if fallos.empty and avisos.empty:
        st.success("Todas las comprobaciones pasan.", icon=":material/check_circle:")
    else:
        st.caption(f"{len(fallos)} fallo(s) · {len(avisos)} aviso(s) · "
                   f"{len(diag) - len(fallos) - len(avisos)} comprobacion(es) correcta(s)")
    st.dataframe(diag, hide_index=True, width="stretch",
                 column_config={"Comprobacion": st.column_config.TextColumn(width="medium"),
                                "Estado": st.column_config.TextColumn(width="small"),
                                "Detalle": st.column_config.TextColumn(width="large")})


def _hojas_del_libro(datos):
    """Cuantas hojas tiene el libro, contadas en el propio fichero.

    No puede ir escrito en el rotulo: las hojas de detalle de cada metodo y la
    de sensibilidad solo existen cuando el metodo las produce, de modo que el
    numero cambia de una empresa a otra. Ponia «catorce»; ICHR da dieciseis y
    LEN dieciocho.
    """
    import io

    import openpyxl

    libro = openpyxl.load_workbook(io.BytesIO(datos), read_only=True)
    try:
        return len(libro.sheetnames)
    finally:
        libro.close()


def _descarga(res):
    st.markdown("#### Exportar")
    st.caption(
        "El libro lleva resumen, supuestos con su origen, coste de capital, estados "
        "historicos completos, FCFF publicado, proyeccion, una hoja por metodo y otra con "
        "su detalle año a año cuando el metodo lo produce, matriz de sensibilidad cuando "
        "se puede calcular, diagnostico y metodologia. Las cifras van sin redondear, para "
        "que el Excel se pueda auditar sin la aplicacion delante."
    )
    clave = f"dcf_xlsx_{res['simbolo']}"
    if st.button("Generar Excel completo", icon=":material/table_view:", width="stretch"):
        try:
            with st.spinner("Componiendo el libro…"):
                st.session_state[clave] = dcf.exportar_excel(res)
        except Exception as exc:
            st.session_state.pop(clave, None)
            st.error(f"No se pudo generar el Excel: {exc}", icon=":material/error:")

    datos = st.session_state.get(clave)
    if datos:
        fecha = pd.Timestamp.today().strftime("%Y%m%d")
        st.download_button(
            f"Descargar DCF_{res['simbolo']}_{fecha}.xlsx "
            f"({_hojas_del_libro(datos)} hojas · {len(datos) / 1024:,.0f} KB)",
            data=datos, file_name=f"DCF_{res['simbolo']}_{fecha}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            icon=":material/download:", width="stretch")


def _explicacion_metodos():
    st.markdown("#### Los cinco metodos, y cuando sirve cada uno")
    st.dataframe(dcf._metodologia(), hide_index=True, width="stretch",
                 column_config={"Formula": st.column_config.TextColumn(width="large"),
                                "Cuando usarlo": st.column_config.TextColumn(width="large")})
