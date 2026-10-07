"""ANALIZADOR DE ACTIVOS - version web (host local).

Ejecutar:  doble clic en "Analizador Web.bat"  ->  http://localhost:8510

Los graficos replican uno a uno los del script original (mismos titulos, mismos
colores de matplotlib, mismos bins), pero interactivos. Todo el calculo vive en
motor_analisis.py, que contiene copias verbatim de las funciones originales.
"""

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

import bloque_informe
import motor_analisis as motor
import pestana_fundamentales
import pestana_mercado
import pestana_cribado
import pestana_dcf
import pestana_grafico

st.set_page_config(
    page_title="Analizador de activos",
    page_icon=":material/monitoring:",
    layout="wide",
)

# Los graficos de Monte Carlo superan las 5.000 filas por defecto de Altair
alt.data_transformers.disable_max_rows()

# --- Colores exactos de matplotlib usados en el script original ---
C0 = "#1f77b4"        # azul por defecto (precio, retornos, convergencia)
C1 = "#ff7f0e"        # naranja por defecto (log return, segundo activo)
ROYALBLUE = "#4169E1"  # trayectorias Monte Carlo
SKYBLUE = "#87CEEB"    # histograma de precios finales
NAVY = "#000080"       # curva de equidad
ROJO = "#FF0000"       # drawdowns y cola de perdidas
NARANJA = "#FFA500"    # linea de VaR
GRANATE = "#8B0000"    # linea de CVaR
AZUL_PURO = "#0000FF"  # histograma de retornos del bloque VaR
VERDE = "#2CA02C"
GRIS = "#7F7F7F"

REJILLA = {"grid": True, "gridColor": "#DDDDDD", "gridOpacity": 0.9}


def _axis(formato=None):
    ejes = dict(REJILLA)
    if formato:
        ejes["format"] = formato
    return alt.Axis(**ejes)


def eje_x(campo, titulo, formato=None, **kw):
    return alt.X(campo, title=titulo, axis=_axis(formato), **kw)


def eje_y(campo, titulo, formato=None, **kw):
    return alt.Y(campo, title=titulo, axis=_axis(formato), **kw)


def pct(x, d=2):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    return f"{x:+.{d}%}"


# =============================================================================
#  CARGA DE DATOS (cacheada)
# =============================================================================

@st.cache_data(ttl="10m", show_spinner=False)
def buscar(texto):
    return motor.buscar_tickers(texto)


@st.cache_data(ttl="10m", show_spinner=False)
def cargar_info(simbolo):
    return motor.info_ticker(simbolo)


def _protegido(funcion, *args):
    """Reconduce los fallos de la fuente a FalloDeFuente.

    Importa por dos motivos. Uno, que la pantalla pueda dar un aviso legible en
    lugar de una traza roja: cuando Yahoo limita las peticiones -y lo hace en
    cuanto se generan varios informes seguidos- lanza YFRateLimitError, que sin
    esto sube hasta la interfaz sin control. Y dos, que st.cache_data NO guarda
    el resultado de una llamada que termina en excepcion, de modo que el corte
    no queda cacheado diez minutos.
    """
    try:
        return funcion(*args)
    except motor.FalloDeFuente:
        raise
    except Exception as e:
        if motor._es_fallo_de_transporte(e):
            raise motor.FalloDeFuente(str(e)) from e
        raise


@st.cache_data(ttl="10m", show_spinner=False)
def cargar_historico(simbolo, periodo):
    return _protegido(motor.descargar_historico, simbolo, periodo)


@st.cache_data(ttl="10m", show_spinner=False)
def cargar_earnings(simbolo, periodo):
    return _protegido(motor.analizar_earnings, simbolo,
                      cargar_historico(simbolo, periodo))


@st.cache_data(ttl="10m", show_spinner=False)
def cargar_rango(simbolo, inicio):
    return motor.descargar_rango(simbolo, inicio)


@st.cache_data(ttl="10m", show_spinner=False)
def cargar_par(a, b, inicio):
    """Cierres alineados de dos activos, con las dos series garantizadas.

    Si falta alguna de las dos se lanza FalloDeFuente en lugar de devolver el
    marco incompleto. Importa por la cache: st.cache_data NO guarda el
    resultado de una llamada que termina en excepcion, pero si guardaria un
    marco defectuoso durante diez minutos, de modo que un corte pasajero del
    proveedor seguiria dando error mucho despues de haberse resuelto.
    """
    try:
        par = motor.descargar_par(a, b, inicio)
    except motor.FalloDeFuente:
        raise
    except Exception as e:
        # Cualquier error de la descarga se reconduce al mismo cauce, de modo
        # que la pestana muestre un aviso y no una traza. Se distingue el corte
        # de red del simbolo inexistente con el clasificador del motor.
        if motor._es_fallo_de_transporte(e):
            raise motor.FalloDeFuente(str(e)) from e
        raise motor.FalloDeFuente(
            f"{type(e).__name__} al descargar {a} y {b}") from e
    if par is None or not hasattr(par, "columns") or par.empty:
        raise motor.FalloDeFuente(
            f"el proveedor no ha devuelto cotizaciones para {a} y {b}")
    faltan = [s for s in (a, b) if s not in par.columns]
    if faltan:
        raise motor.FalloDeFuente(
            f"el proveedor no ha devuelto la serie de {', '.join(faltan)}")
    return par


@st.cache_data(ttl="10m", show_spinner=False)
def simular(simbolo, s0, sigma, n_sim, semilla):
    return motor.monte_carlo(s0, sigma, n_sim=n_sim, semilla=semilla)


# =============================================================================
#  BARRA LATERAL - BUSCADOR POR NOMBRE
# =============================================================================

if "ticker" not in st.session_state:
    st.session_state.ticker = "ICHR"

with st.sidebar:
    st.header("Activo")

    consulta = st.text_input(
        "Buscar empresa o ticker",
        placeholder="Ej: apple, santander, nvidia…",
        help="Escribe el NOMBRE de la empresa y elige de la lista. "
             "No hace falta que sepas el símbolo exacto de Yahoo Finance.",
    )

    if consulta:
        resultados, fuente_caida = [], None
        with st.spinner("Buscando…"):
            try:
                resultados = buscar(consulta)
            except motor.FalloDeFuente as e:
                fuente_caida = str(e)
        if fuente_caida:
            st.error(
                "El buscador de Yahoo Finance no responde en este momento. "
                "**No significa que la empresa no exista**: vuelve a intentarlo "
                "en unos segundos o escribe el ticker directamente abajo.",
                icon=":material/cloud_off:")
        elif not resultados:
            st.caption(":material/search_off: Sin resultados. Prueba con otro nombre.")
        else:
            opciones = {
                f"{r['simbolo']} — {r['nombre']}"
                + (f" · {r['mercado']}" if r["mercado"] else ""): r["simbolo"]
                for r in resultados
            }
            elegido = st.radio("Resultados", list(opciones), index=None,
                               label_visibility="collapsed")
            if elegido and opciones[elegido] != st.session_state.ticker:
                st.session_state.ticker = opciones[elegido]
                st.rerun()

    st.caption(f"Analizando: **{st.session_state.ticker}**")

    manual = st.text_input("O escribe el ticker directamente",
                           value=st.session_state.ticker)
    if manual.strip().upper() != st.session_state.ticker:
        st.session_state.ticker = manual.strip().upper()
        st.rerun()

    st.divider()
    st.header("Parámetros")

    periodo = st.select_slider("Histórico", ["1y", "2y", "5y", "10y", "max"], value="5y")
    confianza = st.slider("Confianza VaR / CVaR", 90.0, 99.9, 99.0, 0.1, format="%.1f%%")
    inversion = st.number_input("Capital invertido", 100, 10_000_000, 100_000, 10_000,
                                help="Se usa en el análisis de impacto de VaR y CVaR.")
    benchmark = st.text_input("Comparar contra", value="SPY").strip().upper()
    umbral_sigmas = st.slider("Umbral de movimiento extremo (σ)", 1.0, 3.0, 2.0, 0.5,
                              help="Define qué cuenta como caída fuerte en el "
                                   "análisis de reversión a la media.")

    st.divider()
    st.caption("Cálculos idénticos al script de consola. Datos de Yahoo Finance, "
               "refrescados cada 10 minutos.")
    st.caption(
        "Herramienta de análisis cuantitativo descriptivo. Todas las cifras se "
        "calculan sobre datos históricos y describen el comportamiento pasado del "
        "activo; no constituyen una previsión ni una recomendación de inversión."
    )

ticker = st.session_state.ticker
if not ticker:
    st.info("Busca una empresa en la barra lateral para empezar.",
            icon=":material/search:")
    st.stop()

with st.spinner(f"Comprobando {ticker}…"):
    try:
        info = cargar_info(ticker)
    except motor.FalloDeFuente as e:
        # Un corte de la fuente NO puede presentarse como un ticker invalido:
        # el usuario se pondria a corregir un simbolo que estaba bien escrito.
        st.error(
            f"Yahoo Finance no responde en este momento, de modo que no se ha "
            f"podido comprobar **{ticker}**. **El símbolo puede ser perfectamente "
            f"correcto**; se trata de un problema temporal de la fuente de datos. "
            f"Vuelve a intentarlo en unos segundos.",
            icon=":material/cloud_off:")
        st.caption(f"Detalle técnico: {e}")
        st.stop()

if info is None:
    st.error(f"**{ticker}** no devuelve datos en Yahoo Finance. Usa el buscador "
             f"por nombre de la barra lateral.", icon=":material/error:")
    st.stop()

nombre, moneda = info

with st.spinner(f"Descargando histórico de {ticker}…"):
    try:
        hist = cargar_historico(ticker, periodo)
        earnings = cargar_earnings(ticker, periodo)
    except motor.FalloDeFuente as e:
        st.error(
            f"Yahoo Finance no ha entregado el histórico de **{ticker}**: "
            f"{str(e)[:150]}. **El símbolo puede ser correcto**; suele deberse "
            f"a que el proveedor ha limitado las peticiones, cosa habitual al "
            f"encadenar varias consultas. Espera un minuto y vuelve a "
            f"intentarlo.", icon=":material/cloud_off:")
        st.stop()

retornos = hist["LogReturn"].dropna()

# ---------------------------------------------------------------------------
#  Suficiencia estadistica de la muestra
#
#  Con un historico corto las formulas siguen devolviendo numeros de aspecto
#  normal: con 8 sesiones de Banco Santander salia un Sharpe de 6,39 y una
#  volatilidad anual del 5,7% para un banco que ronda el 25-30%. No se ocultan
#  las cifras que si tienen respaldo, pero las que no lo tienen se marcan.
# ---------------------------------------------------------------------------
suf = motor.suficiencia(len(retornos), confianza)


def fiable(bloque):
    return suf["detalle"][bloque]["suficiente"]


def marca(bloque, valor, formato="{:.2%}"):
    """Devuelve la cifra formateada, o un guion si la muestra no da para ella."""
    return formato.format(valor) if fiable(bloque) else "—"


@st.cache_data(ttl="1h", show_spinner=False)
def cargar_alternativas(simbolo, nombre_empresa):
    return motor.listados_alternativos(simbolo, nombre_empresa)


if not suf["todo_suficiente"]:
    st.error(
        f"**Histórico insuficiente: {len(retornos)} retornos disponibles.** "
        f"No se pueden calcular con respaldo estadístico "
        f"{', '.join(suf['insuficientes'])}. Las cifras afectadas aparecen como «—» "
        f"en lugar de mostrar un número que parecería preciso sin serlo.",
        icon=":material/error:")

    with st.expander("Por qué, y qué muestra haría falta"):
        st.dataframe(pd.DataFrame([
            {"Métrica": d["descripcion"], "Sesiones necesarias": d["minimo"],
             "Disponibles": suf["n"],
             "Estado": "suficiente" if d["suficiente"] else "insuficiente"}
            for d in suf["detalle"].values()]), hide_index=True)
        st.caption(
            f"Un VaR al {confianza:.1f}% sitúa el corte en el peor "
            f"{100 - confianza:.1f}% de las observaciones. Para que ese percentil "
            f"tenga al menos tres observaciones propias detrás hacen falta "
            f"{suf['minimo_var']} sesiones; con menos, degenera en el mínimo de la "
            f"muestra. Los ratios anualizados necesitan un año bursátil completo "
            f"(252 sesiones) para no extrapolar más de lo que miden.")

    with st.spinner("Buscando otras cotizaciones de la misma empresa…"):
        alternativas = cargar_alternativas(ticker, nombre)
    if alternativas:
        st.info(
            "**La misma empresa cotiza en otros mercados con histórico completo.** "
            "Yahoo Finance trunca a veces la serie de una plaza concreta mientras "
            "conserva la de otras.", icon=":material/swap_horiz:")
        for a in alternativas[:4]:
            col_i, col_j = st.columns([5, 1])
            with col_i:
                st.markdown(f"**{a['simbolo']}** — {a['nombre']} · {a['mercado']} · "
                            f"{a['sesiones']:,} sesiones")
            with col_j:
                if st.button("Usar", key=f"alt_{a['simbolo']}", width="stretch"):
                    st.session_state.ticker = a["simbolo"]
                    st.rerun()

sigma_ref = earnings["sigma_normal"] if earnings else None
situacion = motor.situacion_actual(hist, confianza, sigma_ref)
metricas = motor.analizar_performance_profesional(hist["Close"])
v_hist, v_para, cvar = motor.calcular_metricas_riesgo(retornos, confianza / 100)
tecnicos = motor.indicadores_tecnicos(hist)
volumen = motor.analisis_volumen(hist)
reversion = motor.reversion_tras_extremos(hist, umbral_sigmas)


# =============================================================================
#  CABECERA
# =============================================================================

st.title(nombre)
st.caption(f"{ticker} · {moneda} · último cierre {situacion['fecha']} · "
           f"{len(hist)} sesiones de histórico")

with st.container(horizontal=True):
    st.metric("Precio", f"{situacion['precio']:,.2f}", pct(situacion["mov_dia"]),
              border=True, chart_data=hist["Close"].iloc[-60:].tolist(),
              chart_type="line")
    st.metric("Movimiento de hoy", f"{situacion['sigmas_dia']:+.1f} σ",
              f"percentil {situacion['percentil_dia']:.0f}",
              delta_color="off", border=True)
    st.metric("Volatilidad anual", marca("volatilidad", situacion["vol_anual"], "{:.1%}"),
              f"σ diaria {situacion['sigma_dia']:.2%}" if fiable("volatilidad")
              else f"faltan {suf['detalle']['volatilidad']['minimo'] - suf['n']} sesiones",
              delta_color="off", border=True)
    st.metric(f"VaR {confianza:.1f}%", marca("var", v_hist),
              ("superado hoy" if situacion["supera_var"] else "no superado hoy")
              if fiable("var") else f"necesita {suf['minimo_var']} sesiones",
              delta_color="off", border=True)
    st.metric("CVaR", marca("var", cvar),
              "pérdida media en la cola" if fiable("var") else "muestra insuficiente",
              delta_color="off", border=True)

with st.container(horizontal=True):
    st.metric("Retorno anualizado", marca("ratios", metricas["Retorno Anualizado"]),
              border=True)
    st.metric("Sharpe", marca("ratios", metricas["Sharpe Ratio"], "{:.2f}"), border=True)
    st.metric("Sortino", marca("ratios", metricas["Sortino Ratio"], "{:.2f}"), border=True)
    st.metric("Máx. drawdown", marca("drawdown", metricas["Max Drawdown"]), border=True)
    st.metric("Ratio de Calmar", marca("ratios", metricas["Ratio de Calmar"], "{:.2f}"),
              "retorno por unidad de caída" if fiable("ratios")
              else "necesita un año bursátil", delta_color="off", border=True)

st.progress(min(max(situacion["pos_rango"] / 100, 0.0), 1.0),
            text=f"Rango 52 semanas · {situacion['min_52s']:,.2f} → "
                 f"{situacion['max_52s']:,.2f} · está al {situacion['pos_rango']:.0f}% "
                 f"({pct(situacion['desde_maximo'], 1)} desde máximos)")

# =============================================================================
#  PESTANAS
#
#  st.tabs NO es perezoso: Streamlit ejecuta el cuerpo de las TRECE pestañas en
#  cada repintado, aunque el usuario solo este viendo una. Medido con la cache ya
#  caliente, eso costaba 3,7 s por cada clic, y el 95% se iba en pestañas que
#  nadie estaba mirando.
#
#  Desde Streamlit 1.60 st.tabs admite `key`, de modo que el rotulo de la pestaña
#  abierta queda en session_state y se puede ejecutar solo esa. `on_change` a
#  "rerun" es imprescindible: sin el, al cambiar de pestaña no se repinta y la
#  recien abierta se quedaria con el aviso de aplazada para siempre.
#
#  Solo se aplazan las pestañas que delegan en un modulo propio, que son las
#  caras (Fundamentales 1,30 s, Grafico 0,83 s, Seleccion 0,54 s, Opciones
#  0,18 s). Las demas suman 0,5 s entre las nueve y no compensa tocarlas.
# =============================================================================

ROTULOS_PESTANAS = [
    "Resumen", "Gráfico", "Precio y retornos", "Monte Carlo", "Riesgo VaR/CVaR",
    "Earnings", "Movimientos extremos", "Volumen", "Selección de valores",
    "Opciones y microestructura", "Comparativa", "Fundamentales", "DCF",
]

(tab_resumen, tab_graf, tab_precio, tab_mc, tab_riesgo, tab_earn,
 tab_rev, tab_vol, tab_crib, tab_opc, tab_comp, tab_fund, tab_dcf) = st.tabs(
    ROTULOS_PESTANAS, key="pestana_abierta", on_change="rerun")


def abierta(rotulo):
    """¿Es esta la pestaña que el usuario esta viendo ahora mismo?

    Antes de la primera interaccion la clave todavia no existe; entonces manda
    el primer rotulo, que es el que Streamlit muestra abierto de salida.
    """
    return st.session_state.get("pestana_abierta", ROTULOS_PESTANAS[0]) == rotulo


def aplazada():
    """Marca de que el contenido no se ha calculado, no de que no lo haya.

    Dejar el panel en blanco confundiria «aun no calculado» con «no hay datos»,
    que son cosas distintas. Apenas se ve: al abrir la pestaña se repinta.
    """
    st.caption(":material/hourglass_empty: Se calcula al abrir esta pestaña.")


# =============================================================================
#  RESUMEN
# =============================================================================

with tab_resumen:
    bloque_informe.render(ticker, nombre, periodo, confianza, inversion,
                          umbral_sigmas, benchmark)

    col1, col2 = st.columns([2, 1])

    with col1:
        with st.container(border=True):
            st.subheader(f"Precio de Cierre Ajustado de {nombre}")
            precio_df = hist.reset_index()
            precio_df.columns = ["Fecha"] + list(hist.columns)
            linea = alt.Chart(precio_df).mark_line(color=C0, strokeWidth=1.6).encode(
                eje_x("Fecha:T", "Fecha"),
                eje_y("Close:Q", f"Precio ({moneda})", scale=alt.Scale(zero=False)),
                tooltip=[alt.Tooltip("Fecha:T", title="Fecha"),
                         alt.Tooltip("Close:Q", title="Cierre", format=",.2f")],
            ).properties(height=380)
            st.altair_chart(linea.interactive())

    with col2:
        with st.container(border=True):
            st.subheader("Situación actual")
            if tecnicos:
                st.metric("RSI (14)", f"{tecnicos['rsi']:.0f}",
                          "escala 0–100", delta_color="off", border=True)
                st.metric("Posición en Bollinger", f"{tecnicos['posicion_bb']:+.2f}",
                          "−1 = banda inferior, +1 = superior",
                          delta_color="off", border=True)
                st.metric("Distancia a media 200",
                          pct(tecnicos["dist_sma200"], 1), border=True)
                if tecnicos["racha_bajista"] >= 2:
                    st.caption(f"Sesiones consecutivas con retorno negativo: "
                               f"**{tecnicos['racha_bajista']}**.")
            else:
                st.caption("Histórico insuficiente para los indicadores técnicos.")

    if reversion and reversion["umbral_superado"]:
        st.info(
            f"La última sesión registró un retorno de {reversion['z_hoy']:+.1f}σ, "
            f"por debajo del umbral de −{umbral_sigmas:.1f}σ fijado en la barra "
            f"lateral. La pestaña *Movimientos extremos* recoge lo que hizo el "
            f"precio en las {reversion['n_caidas']} ocasiones anteriores en que "
            f"esto ocurrió.",
            icon=":material/info:",
        )

    with st.container(border=True):
        st.subheader("Resumen estadístico de retornos")
        st.dataframe(hist[["Return", "LogReturn", "Volatility"]].describe().T)
        st.caption("Mismo `describe()` que imprime el script original.")


# =============================================================================
#  PRECIO Y RETORNOS  (secciones 1-2 del script original)
# =============================================================================

with tab_precio:
    base = hist.reset_index()
    base.columns = ["Fecha"] + list(hist.columns)

    with st.container(border=True):
        st.subheader(f"Retornos diarios de {nombre} ({ticker})")
        ch = alt.Chart(base.dropna(subset=["Return"])).mark_line(
            color=C0, strokeWidth=0.9).encode(
            eje_x("Fecha:T", "Fecha"),
            eje_y("Return:Q", "Retorno diario", formato="+.0%"),
            tooltip=[alt.Tooltip("Fecha:T", title="Fecha"),
                     alt.Tooltip("Return:Q", title="Retorno", format="+.2%")],
        ).properties(height=320)
        st.altair_chart(ch.interactive())

    col_a, col_b = st.columns(2)

    with col_a:
        with st.container(border=True):
            st.subheader(f"Distribución de Retornos Diarios de {ticker}")
            h = alt.Chart(base.dropna(subset=["Return"])).mark_bar(
                color=C0).encode(
                alt.X("Return:Q", bin=alt.Bin(maxbins=75), title="Retorno diario",
                      axis=alt.Axis(format="+.0%", **REJILLA)),
                eje_y("count():Q", "Frecuencia"),
                tooltip=[alt.Tooltip("count():Q", title="Sesiones")],
            ).properties(height=330)
            st.altair_chart(h)
            st.caption("75 bins, igual que `plt.hist(..., bins=75)` del original.")

    with col_b:
        with st.container(border=True):
            st.subheader(f"Volatilidad histórica anualizada 21 días")
            vol_df = base.dropna(subset=["Volatility"])
            ch = alt.Chart(vol_df).mark_line(color=C0, strokeWidth=1.4).encode(
                eje_x("Fecha:T", "Fecha"),
                eje_y("Volatility:Q", "Volatilidad", formato=".0%"),
                tooltip=[alt.Tooltip("Fecha:T", title="Fecha"),
                         alt.Tooltip("Volatility:Q", title="Volatilidad", format=".1%")],
            ).properties(height=330)
            st.altair_chart(ch.interactive())

    with st.container(border=True):
        st.subheader(f"Retornos diarios de {nombre}: simple vs logarítmico")
        largo = base.dropna(subset=["Return", "LogReturn"]).melt(
            id_vars="Fecha", value_vars=["Return", "LogReturn"],
            var_name="Tipo", value_name="Valor")
        largo["Tipo"] = largo["Tipo"].map({"Return": "Simple Return",
                                           "LogReturn": "Log Return"})
        ch = alt.Chart(largo).mark_line(strokeWidth=0.9).encode(
            eje_x("Fecha:T", "Fecha"),
            eje_y("Valor:Q", "Retorno", formato="+.0%"),
            color=alt.Color("Tipo:N", title=None, scale=alt.Scale(
                domain=["Simple Return", "Log Return"], range=[C0, C1])),
            tooltip=[alt.Tooltip("Fecha:T", title="Fecha"),
                     alt.Tooltip("Tipo:N", title="Tipo"),
                     alt.Tooltip("Valor:Q", title="Retorno", format="+.2%")],
        ).properties(height=340)
        st.altair_chart(ch.interactive())
        st.caption("Mismos colores que matplotlib: azul el simple, naranja el logarítmico.")


# =============================================================================
#  MONTE CARLO
# =============================================================================

with tab_mc:
    col_cfg1, col_cfg2 = st.columns([3, 1])
    with col_cfg2:
        n_sim = st.select_slider("Trayectorias", [1000, 5000, 10000, 25000], value=10000)
        if st.button("Volver a simular", icon=":material/casino:", width="stretch"):
            st.session_state.semilla = st.session_state.get("semilla", 0) + 1
    semilla = st.session_state.get("semilla", 0)

    serie = cargar_rango(ticker, motor.FECHA_INICIO)
    if serie is None or len(serie) < 30:
        st.warning("No hay datos suficientes para simular.", icon=":material/warning:")
    else:
        s0 = float(serie.iloc[-1])
        sigma_mc = motor.sigma_anualizada(serie)
        mc = simular(ticker, s0, sigma_mc, n_sim, semilla)
        ic_lo, ic_hi = motor.intervalo_confianza(mc["promedio"], mc["error_estandar"])

        with col_cfg1:
            with st.container(horizontal=True):
                st.metric("Precio de partida", f"{s0:,.2f}", border=True)
                st.metric("Volatilidad usada", f"{sigma_mc:.1%}", border=True)
                st.metric("Precio promedio final", f"{mc['promedio']:,.2f}",
                          f"teórico {mc['teorico']:,.2f}", delta_color="off", border=True)
                st.metric("Error estándar", f"{mc['error_estandar']:.4f}", border=True)

        with st.container(horizontal=True):
            st.metric("Peor escenario esperado (p5)", f"{mc['peor_final']:,.2f}",
                      pct(mc["peor_final"] / s0 - 1, 1), border=True)
            st.metric("Mediana (p50)", f"{mc['mediana_final']:,.2f}",
                      pct(mc["mediana_final"] / s0 - 1, 1), border=True)
            st.metric("Mejor escenario esperado (p95)", f"{mc['mejor_final']:,.2f}",
                      pct(mc["mejor_final"] / s0 - 1, 1), border=True)

        with st.container(border=True):
            st.subheader(f"Simulación Monte Carlo para {ticker}: {n_sim:,} Trayectorias")

            precios = mc["precios"]
            n_dibujar = min(100, precios.shape[1])   # el original dibuja 100
            dias = np.arange(precios.shape[0])

            filas = []
            for j in range(n_dibujar):
                for i in dias:
                    filas.append({"dia": int(i), "precio": float(precios[i, j]),
                                  "sim": j})
            df_paths = pd.DataFrame(filas)

            spaghetti = alt.Chart(df_paths).mark_line(
                color=ROYALBLUE, opacity=0.10, strokeWidth=0.8).encode(
                eje_x("dia:Q", "Días"),
                eje_y("precio:Q", "Precio del Activo", scale=alt.Scale(zero=False)),
                detail="sim:N",
            )

            df_esc = pd.DataFrame({
                "dia": np.concatenate([dias, dias, dias]),
                "precio": np.concatenate([mc["mediana_camino"], mc["mejor_camino"],
                                          mc["peor_camino"]]),
                "Escenario": (["Mediana (p50)"] * len(dias)
                              + ["Mejor esperado (p95)"] * len(dias)
                              + ["Peor esperado (p5)"] * len(dias)),
            })
            escenarios = alt.Chart(df_esc).mark_line(strokeWidth=3).encode(
                x="dia:Q", y="precio:Q",
                color=alt.Color("Escenario:N", title=None, scale=alt.Scale(
                    domain=["Mediana (p50)", "Mejor esperado (p95)", "Peor esperado (p5)"],
                    range=[NAVY, VERDE, ROJO]),
                    legend=alt.Legend(orient="top-left")),
                strokeDash=alt.StrokeDash("Escenario:N", scale=alt.Scale(
                    domain=["Mediana (p50)", "Mejor esperado (p95)", "Peor esperado (p5)"],
                    range=[[1, 0], [6, 4], [6, 4]]), legend=None),
                tooltip=[alt.Tooltip("dia:Q", title="Sesión"),
                         alt.Tooltip("Escenario:N"),
                         alt.Tooltip("precio:Q", title="Precio", format=",.2f")],
            )

            st.altair_chart((spaghetti + escenarios).properties(height=420))
            st.caption(
                f"Se dibujan {n_dibujar} trayectorias de las {n_sim:,} simuladas, igual "
                f"que el original. **Azul marino** la mediana, **verde** el mejor "
                f"escenario esperable (percentil 95) y **rojo** el peor (percentil 5). "
                f"Se usan percentiles y no el máximo y el mínimo absolutos porque "
                f"estos dependen de una única trayectoria y no son representativos."
            )

        col_c, col_d = st.columns([3, 2])

        with col_c:
            with st.container(border=True):
                st.subheader(f"Distribución de Precios al Vencimiento (T) para {ticker}")
                dist = alt.Chart(pd.DataFrame({"precio": mc["finales"]})).mark_bar(
                    color=SKYBLUE, stroke="black", strokeWidth=0.3).encode(
                    alt.X("precio:Q", bin=alt.Bin(maxbins=250), title="Precio Final",
                          axis=alt.Axis(**REJILLA)),
                    eje_y("count():Q", "Frecuencia"),
                    tooltip=[alt.Tooltip("count():Q", title="Escenarios")],
                ).properties(height=340)
                st.altair_chart(dist)
                st.caption("250 bins y colores `skyblue` con borde negro, como el original.")

        with col_d:
            with st.container(border=True):
                st.subheader("Escenarios simulados")
                st.dataframe(
                    pd.DataFrame({
                        "Percentil": [f"{p}%" for p in mc["percentiles"]],
                        "Precio": list(mc["percentiles"].values()),
                        "Variación": [v / s0 - 1 for v in mc["percentiles"].values()],
                    }),
                    hide_index=True,
                    column_config={
                        "Precio": st.column_config.NumberColumn(format="%.2f"),
                        "Variación": st.column_config.NumberColumn(format="percent"),
                    },
                )
                st.info(f"**Intervalo de confianza del 99%** para el precio final "
                        f"simulado:\n\n**[{ic_lo:,.2f} , {ic_hi:,.2f}]**\n\n"
                        f"Con un 99% de confianza, el promedio real cae en ese rango.",
                        icon=":material/straighten:")

        with st.container(border=True):
            st.subheader("Análisis de Convergencia de Monte Carlo")
            paso = max(1, n_sim // 2000)
            idx = np.arange(0, n_sim, paso)
            conv_df = pd.DataFrame({"n": idx + 1, "promedio": mc["convergencia"][idx]})
            conv = alt.Chart(conv_df).mark_line(color=C0, strokeWidth=1.4).encode(
                eje_x("n:Q", "Número de Simulaciones"),
                eje_y("promedio:Q", "Precio Promedio", scale=alt.Scale(zero=False)),
                tooltip=[alt.Tooltip("n:Q", title="Simulaciones"),
                         alt.Tooltip("promedio:Q", title="Promedio", format=",.2f")],
            )
            teorico = alt.Chart(pd.DataFrame({"y": [mc["teorico"]]})).mark_rule(
                color=ROJO, strokeDash=[6, 4], strokeWidth=2).encode(y="y:Q")
            st.altair_chart((conv + teorico).properties(height=300))
            st.caption("La línea roja discontinua es el valor teórico S₀·e^(r·T), "
                       "igual que en el original.")


# =============================================================================
#  RIESGO VaR / CVaR  +  ANALISIS DE IMPACTO
# =============================================================================

with tab_riesgo:
    st.subheader(f"Reporte de Riesgo para {ticker}")

    with st.container(horizontal=True):
        st.metric("VaR Histórico", f"{v_hist:.2%}", border=True)
        st.metric("VaR Paramétrico", f"{v_para:.2%}", border=True)
        st.metric("CVaR", f"{cvar:.2%}", border=True)
        st.metric("Confianza", f"{confianza:.1f}%", border=True)

    # ---------------- ANALISIS DE IMPACTO (interactivo) ----------------
    with st.container(border=True):
        st.subheader("Análisis de impacto sobre tu capital")

        col_i, col_j = st.columns([1, 2])
        with col_i:
            capital = st.number_input(
                "Inversión", min_value=100, max_value=100_000_000,
                value=int(inversion), step=10_000, key="capital_impacto",
                help="Cámbialo aquí mismo: las pérdidas se recalculan al instante.")
            conf_impacto = st.slider("Confianza", 90.0, 99.9, float(confianza), 0.1,
                                     format="%.1f%%", key="conf_impacto")

        vh_i, _, cv_i = motor.calcular_metricas_riesgo(retornos, conf_impacto / 100)
        perdida_var = capital * vh_i
        perdida_cvar = capital * cv_i

        with col_j:
            with st.container(horizontal=True):
                st.metric(f"VaR {conf_impacto:.1f}% sobre el capital",
                          f"−{abs(perdida_var):,.2f} {moneda}",
                          f"{vh_i:.2%} del capital", delta_color="off", border=True)
                st.metric(f"CVaR {conf_impacto:.1f}% sobre el capital",
                          f"−{abs(perdida_cvar):,.2f} {moneda}",
                          f"{cv_i:.2%} del capital", delta_color="off", border=True)

            st.markdown(
                f"""
                ```
                --- ANÁLISIS DE IMPACTO ---
                Con una inversión de ${capital:,.0f}:
                En un día malo (VaR), podrías perder: ${abs(perdida_var):,.2f}
                En un día catastrófico (CVaR), la pérdida media sería: ${abs(perdida_cvar):,.2f}
                ```
                """
            )

    with st.container(border=True):
        st.subheader(f"Distribución de Retornos y Escenarios de Riesgo ({ticker})")

        df_r = pd.DataFrame({"retorno": retornos.values})
        df_r["zona"] = np.where(df_r["retorno"] < v_hist, "Pérdida extrema",
                                "Retornos Diarios")

        barras = alt.Chart(df_r).mark_bar(opacity=0.55).encode(
            alt.X("retorno:Q", bin=alt.Bin(maxbins=250), title="Retorno Diario",
                  axis=alt.Axis(format="+.0%", **REJILLA)),
            eje_y("count():Q", "Frecuencia"),
            color=alt.Color("zona:N", title=None, scale=alt.Scale(
                domain=["Retornos Diarios", "Pérdida extrema"],
                range=[AZUL_PURO, ROJO]),
                legend=alt.Legend(orient="top-left")),
            tooltip=[alt.Tooltip("count():Q", title="Sesiones")],
        )
        lineas = alt.Chart(pd.DataFrame({
            "valor": [v_hist, cvar],
            "Métrica": [f"VaR Histórico ({v_hist:.2%})", f"CVaR ({cvar:.2%})"],
        })).mark_rule(strokeWidth=2.5).encode(
            x="valor:Q",
            color=alt.Color("Métrica:N", title=None, scale=alt.Scale(
                domain=[f"VaR Histórico ({v_hist:.2%})", f"CVaR ({cvar:.2%})"],
                range=[NARANJA, GRANATE]),
                legend=alt.Legend(orient="top-right")),
            strokeDash=alt.StrokeDash("Métrica:N", scale=alt.Scale(
                domain=[f"VaR Histórico ({v_hist:.2%})", f"CVaR ({cvar:.2%})"],
                range=[[6, 4], [1, 0]]), legend=None),
            tooltip=[alt.Tooltip("Métrica:N"),
                     alt.Tooltip("valor:Q", title="Valor", format="+.2%")],
        )
        st.altair_chart((barras + lineas).properties(height=400))
        st.caption("Las barras rojas son las sesiones peores que el VaR: la cola que "
                   "el CVaR promedia. Mismos colores que el original (naranja "
                   "discontinuo el VaR, granate el CVaR).")

    col_k, col_l = st.columns(2)
    with col_k:
        with st.container(border=True):
            st.subheader("Crecimiento de una Inversión")
            eq = metricas["Equity_Curve"].reset_index()
            eq.columns = ["Fecha", "Valor"]
            eq["Capital"] = eq["Valor"] * capital
            ch = alt.Chart(eq).mark_line(color=NAVY, strokeWidth=1.8).encode(
                eje_x("Fecha:T", "Fecha"),
                eje_y("Capital:Q", "Valor de la Inversión", scale=alt.Scale(zero=False)),
                tooltip=[alt.Tooltip("Fecha:T", title="Fecha"),
                         alt.Tooltip("Capital:Q", title="Valor", format=",.0f")],
            ).properties(height=320)
            st.altair_chart(ch.interactive())
            st.caption(f"Base: los {capital:,.0f} {moneda} del análisis de impacto.")

    with col_l:
        with st.container(border=True):
            st.subheader("Drawdowns (Caídas desde máximos)")
            dd = metricas["Series_Drawdown"].reset_index()
            dd.columns = ["Fecha", "Drawdown"]
            ch = alt.Chart(dd).mark_area(color=ROJO, opacity=0.3,
                                         line={"color": ROJO, "strokeWidth": 1}).encode(
                eje_x("Fecha:T", "Fecha"),
                eje_y("Drawdown:Q", "Porcentaje de Caída", formato=".0%"),
                tooltip=[alt.Tooltip("Fecha:T", title="Fecha"),
                         alt.Tooltip("Drawdown:Q", title="Caída", format=".2%")],
            ).properties(height=320)
            st.altair_chart(ch.interactive())
            st.caption(f"Máxima caída histórica: **{metricas['Max Drawdown']:.2%}** · "
                       f"Ratio de Calmar: **{metricas['Ratio de Calmar']:.2f}**")


# =============================================================================
#  EARNINGS
# =============================================================================

with tab_earn:
    if earnings is None:
        st.info(f"**{nombre}** no publica resultados trimestrales: es un ETF, índice, "
                f"cripto o divisa. El resto de pestañas funciona con normalidad.",
                icon=":material/info:")
    else:
        ultimo = earnings["eventos"][-1]

        st.subheader("Última publicación de resultados")
        st.caption(f"Publicado el {ultimo['momento'].strftime('%d/%m/%Y %H:%M')} "
                   f"({'tras el cierre' if ultimo['tras_cierre'] else 'antes de abrir'})"
                   f" · el mercado reaccionó el {ultimo['fecha_reaccion']}")

        with st.container(horizontal=True):
            if not np.isnan(ultimo["sorpresa"]):
                st.metric("Sorpresa en beneficios", f"{ultimo['sorpresa']:+.2f}%",
                          f"{ultimo['eps_real']} vs {ultimo['eps_est']} est.",
                          delta_color="off", border=True)
            st.metric("Reacción del precio", pct(ultimo["mov"]), border=True)
            st.metric("Cuán extremo", f"{ultimo['sigmas']:+.1f} σ",
                      f"percentil {ultimo['percentil']:.0f}",
                      delta_color="off", border=True)
            if not np.isnan(earnings["tasa_reversion"]):
                st.metric("Tiende a revertir", f"{earnings['tasa_reversion']:.0%}",
                          f"{earnings['n_revierten']} de {earnings['n_con_ventana']}",
                          delta_color="off", border=True)

        clasificacion = ultimo["clasificacion"]
        if "revertido" in clasificacion:
            detalle = ("el precio deshizo una parte significativa del movimiento "
                       "inicial en las sesiones siguientes.")
        elif "prolongado" in clasificacion:
            detalle = ("el precio continuó en la misma dirección en las sesiones "
                       "siguientes (post-earnings drift).")
        else:
            detalle = "el precio se mantuvo cerca del nivel alcanzado tras la reacción."
        st.info(f"**{clasificacion}** — {detalle}", icon=":material/info:")

        if not np.isnan(ultimo["sorpresa"]):
            if ultimo["sorpresa"] > 0 and ultimo["mov"] < 0:
                st.info(
                    "El resultado superó la estimación de consenso y el precio cerró "
                    "a la baja. Esta combinación se asocia habitualmente a "
                    "expectativas ya incorporadas al precio o a previsiones de la "
                    "compañía por debajo de lo esperado. Yahoo Finance no publica el "
                    "*guidance*, así que esta herramienta no puede distinguir entre "
                    "ambas causas.", icon=":material/info:")
            elif ultimo["sorpresa"] < 0 and ultimo["mov"] > 0:
                st.info(
                    "El resultado quedó por debajo de la estimación de consenso y el "
                    "precio cerró al alza.", icon=":material/info:")

        if earnings["proximos"]:
            prox = earnings["proximos"][0]
            st.caption(f":material/event: Próximos resultados: "
                       f"**{prox.strftime('%d/%m/%Y')}** "
                       f"(dentro de {(prox.date() - situacion['fecha']).days} días)")

        st.divider()

        with st.container(border=True):
            st.subheader("Reacción a cada publicación")
            st.caption(f"Bandas grises: ±1σ y ±2σ de un día **sin** resultados "
                       f"(σ = {earnings['sigma_normal']:.2%}).")

            df_ev = pd.DataFrame([{
                "periodo": e["momento"].strftime("%Y-%m"),
                "movimiento": e["mov"], "sigmas": e["sigmas"],
                "clasificacion": e["clasificacion"],
                "signo": "Subida" if e["mov"] >= 0 else "Bajada",
            } for e in earnings["eventos"]])

            barras = alt.Chart(df_ev).mark_bar().encode(
                alt.X("periodo:N", title=None, sort=None, axis=alt.Axis(labelAngle=-45)),
                eje_y("movimiento:Q", "Movimiento en la sesión de reacción", formato="+.0%"),
                color=alt.Color("signo:N", scale=alt.Scale(
                    domain=["Subida", "Bajada"], range=[VERDE, ROJO]), legend=None),
                tooltip=[alt.Tooltip("periodo:N", title="Trimestre"),
                         alt.Tooltip("movimiento:Q", title="Movimiento", format="+.2%"),
                         alt.Tooltip("sigmas:Q", title="Sigmas", format="+.1f"),
                         alt.Tooltip("clasificacion:N", title="Clasificación")],
            )
            s = earnings["sigma_normal"]
            bandas = alt.Chart(pd.DataFrame({
                "y": [s, -s, 2 * s, -2 * s],
                "banda": ["±1σ", "±1σ", "±2σ", "±2σ"]})).mark_rule(
                strokeDash=[4, 4], color=GRIS).encode(
                y="y:Q", tooltip=alt.Tooltip("banda:N", title="Banda"))
            st.altair_chart((barras + bandas).properties(height=340))

        caminos = motor.caminos_evento(earnings, hist)
        if caminos is not None:
            with st.container(border=True):
                st.subheader("Comportamiento alrededor de los resultados")
                filas = [{"dia": int(d), "valor": float(caminos["caminos"][i, j]),
                          "evento": et}
                         for i, et in enumerate(caminos["etiquetas"])
                         for j, d in enumerate(caminos["eje"])]
                df_c = pd.DataFrame(filas)
                df_m = pd.DataFrame({"dia": caminos["eje"].astype(int),
                                     "valor": caminos["medio"]})

                ind = alt.Chart(df_c).mark_line(opacity=0.25, strokeWidth=1,
                                                color=C0).encode(
                    eje_x("dia:Q", "Sesiones respecto al día de reacción"),
                    eje_y("valor:Q", "Rentabilidad acumulada", formato="+.0%"),
                    detail="evento:N",
                    tooltip=[alt.Tooltip("evento:N", title="Trimestre"),
                             alt.Tooltip("valor:Q", title="Acumulado", format="+.2%")])
                med = alt.Chart(df_m).mark_line(color=NAVY, strokeWidth=4).encode(
                    x="dia:Q", y="valor:Q",
                    tooltip=alt.Tooltip("valor:Q", title="Media", format="+.2%"))
                cero = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(
                    color=ROJO, strokeDash=[5, 5]).encode(x="x:Q")
                st.altair_chart((ind + med + cero).properties(height=360))

                salto, final = caminos["salto"], caminos["final"]
                if salto and np.sign(final) != np.sign(salto):
                    lectura = "De media el movimiento **se revierte por completo**."
                elif salto and abs(final) < abs(salto):
                    lectura = f"De media devuelve **{(1 - abs(final)/abs(salto)):.0%}** del salto."
                else:
                    lectura = "De media el movimiento **continúa** (drift)."
                st.caption(f"Salta {salto:+.2%} el día de la reacción y termina en "
                           f"{final:+.2%} veinte sesiones después. {lectura}")

        con_s = [e for e in earnings["eventos"] if not np.isnan(e["sorpresa"])]
        usables = [e for e in con_s if abs(e["sorpresa"]) <= motor.LIMITE_SORPRESA]
        if len(usables) >= 3:
            with st.container(border=True):
                st.subheader("¿Explica la sorpresa el movimiento?")
                df_s = pd.DataFrame([{
                    "sorpresa": e["sorpresa"] / 100, "movimiento": e["mov"],
                    "periodo": e["momento"].strftime("%Y-%m"),
                    "signo": "Subida" if e["mov"] >= 0 else "Bajada"} for e in usables])
                correl = float(np.corrcoef(df_s["sorpresa"], df_s["movimiento"])[0, 1])
                pts = alt.Chart(df_s).mark_circle(size=180, opacity=0.85).encode(
                    eje_x("sorpresa:Q", "Sorpresa en beneficios"),
                    eje_y("movimiento:Q", "Movimiento del precio", formato="+.0%"),
                    color=alt.Color("signo:N", scale=alt.Scale(
                        domain=["Subida", "Bajada"], range=[VERDE, ROJO]), legend=None),
                    tooltip=[alt.Tooltip("periodo:N", title="Trimestre"),
                             alt.Tooltip("sorpresa:Q", title="Sorpresa", format="+.1%"),
                             alt.Tooltip("movimiento:Q", title="Movimiento", format="+.2%")])
                tend = pts.transform_regression("sorpresa", "movimiento").mark_line(
                    color=NAVY, strokeDash=[6, 4])
                st.altair_chart((pts + tend).properties(height=330))
                st.caption(f"Correlación **{correl:+.2f}** entre la sorpresa en "
                           f"beneficios y el movimiento del precio. En el cuadrante "
                           f"inferior derecho quedan las publicaciones que superaron "
                           f"la estimación y aun así cerraron a la baja.")
                if len(con_s) - len(usables):
                    st.caption(f":material/filter_alt: "
                               f"{len(con_s) - len(usables)} evento(s) excluido(s): "
                               f"sorpresa >{motor.LIMITE_SORPRESA:.0f}% por EPS "
                               f"estimado casi cero.")

        with st.container(border=True):
            st.subheader("Historial completo")
            st.dataframe(motor.tabla_earnings(earnings), hide_index=True,
                         column_config={
                             "Sorpresa EPS": st.column_config.NumberColumn(format="percent"),
                             "Movimiento": st.column_config.NumberColumn(format="percent"),
                             "Sigmas": st.column_config.NumberColumn(format="%+.1f σ"),
                             "Percentil": st.column_config.NumberColumn(format="%.0f"),
                             "+5d": st.column_config.NumberColumn(format="percent"),
                             "+10d": st.column_config.NumberColumn(format="percent"),
                             "+20d": st.column_config.NumberColumn(format="percent")})
            st.caption(f"Movimiento medio en resultados **{earnings['mov_medio_earnings']:.2%}** "
                       f"vs **{earnings['mov_medio_normal']:.2%}** en un día normal "
                       f"(×{earnings['mov_medio_earnings']/earnings['mov_medio_normal']:.1f}).")


# =============================================================================
#  REVERSION A LA MEDIA
# =============================================================================

with tab_rev:
    st.subheader("Comportamiento del precio tras movimientos extremos")
    st.caption(
        f"Localiza las sesiones en las que {ticker} registró un retorno inferior a "
        f"−{umbral_sigmas:.1f}σ y calcula el retorno acumulado medio en las "
        f"sesiones posteriores. Se muestra junto al retorno medio de una sesión "
        f"cualquiera del mismo periodo, que sirve de referencia. El umbral se "
        f"ajusta en la barra lateral."
    )

    if reversion is None:
        st.info("El histórico disponible es insuficiente para este recuento.",
                icon=":material/info:")
    else:
        with st.container(horizontal=True):
            st.metric("Retorno de la última sesión", f"{reversion['z_hoy']:+.1f} σ",
                      "por debajo del umbral" if reversion["umbral_superado"]
                      else "dentro del umbral",
                      delta_color="off", border=True)
            st.metric(f"Sesiones por debajo de −{umbral_sigmas:.1f}σ",
                      f"{reversion['n_caidas']}", "en el histórico analizado",
                      delta_color="off", border=True)
            st.metric("Diferencia media con la referencia",
                      pct(reversion["diferencia_media"]),
                      "media de las cinco ventanas",
                      delta_color="off", border=True)
            if tecnicos:
                st.metric("RSI (14)", f"{tecnicos['rsi']:.0f}",
                          "escala 0–100", delta_color="off", border=True)

        signo = ("por encima" if reversion["diferencia_positiva"] else "por debajo")
        if reversion["umbral_superado"]:
            st.info(
                f"El retorno de la última sesión ({reversion['z_hoy']:+.1f}σ) queda "
                f"por debajo del umbral fijado. En las {reversion['n_caidas']} "
                f"sesiones comparables del histórico, el retorno acumulado posterior "
                f"se situó de media {abs(reversion['diferencia_media']):.2%} {signo} "
                f"del de una sesión cualquiera. Se trata de un recuento sobre datos "
                f"pasados, sin valor predictivo.",
                icon=":material/info:")
        else:
            st.info(
                f"El retorno de la última sesión ({reversion['z_hoy']:+.1f}σ) no "
                f"alcanza el umbral de −{umbral_sigmas:.1f}σ. La tabla siguiente "
                f"recoge el histórico de las sesiones que sí lo alcanzaron.",
                icon=":material/info:")

        with st.container(border=True):
            st.subheader("Qué pasó después, sesión a sesión")
            tabla = reversion["tabla"]
            comp = tabla.melt(id_vars="Ventana",
                              value_vars=["Tras caida", "Dia cualquiera"],
                              var_name="Escenario", value_name="Retorno")
            comp["Escenario"] = comp["Escenario"].map({
                "Tras caida": f"Tras caída de {umbral_sigmas:.1f}σ",
                "Dia cualquiera": "Día cualquiera (base)"})
            ch = alt.Chart(comp).mark_bar().encode(
                alt.X("Ventana:N", title="Sesiones después", sort=None),
                eje_y("Retorno:Q", "Retorno medio acumulado", formato="+.1%"),
                xOffset="Escenario:N",
                color=alt.Color("Escenario:N", title=None, scale=alt.Scale(
                    domain=[f"Tras caída de {umbral_sigmas:.1f}σ", "Día cualquiera (base)"],
                    range=[VERDE, GRIS]), legend=alt.Legend(orient="top")),
                tooltip=[alt.Tooltip("Ventana:N"), alt.Tooltip("Escenario:N"),
                         alt.Tooltip("Retorno:Q", title="Retorno medio", format="+.2%")],
            ).properties(height=340)
            st.altair_chart(ch)

            st.dataframe(
                tabla[["Ventana", "Tras caida", "% positivos caida", "n_caidas",
                       "Dia cualquiera", "% positivos base", "Diferencia"]],
                hide_index=True,
                column_config={
                    "Tras caida": st.column_config.NumberColumn(
                        "Tras el movimiento", format="percent"),
                    "% positivos caida": st.column_config.NumberColumn(
                        "% observaciones en positivo", format="percent"),
                    "n_caidas": st.column_config.NumberColumn("Observaciones",
                                                              format="%d"),
                    "Dia cualquiera": st.column_config.NumberColumn(
                        "Sesión cualquiera", format="percent"),
                    "% positivos base": st.column_config.NumberColumn(
                        "% referencia en positivo", format="percent"),
                    "Diferencia": st.column_config.NumberColumn(
                        "Diferencia", format="percent")})
            st.caption(
                "**Diferencia** = retorno medio tras el movimiento extremo menos el "
                "de una sesión cualquiera del mismo periodo. El número de "
                "observaciones condiciona la fiabilidad del recuento: por debajo de "
                "15 casos, la media es muy sensible a valores sueltos. Estos datos "
                "describen el comportamiento pasado del activo y no constituyen "
                "una estimación de su comportamiento futuro."
            )

        if tecnicos:
            with st.container(border=True):
                st.subheader("Bandas de Bollinger y RSI")
                bb = tecnicos["tabla"].dropna(subset=["BandaInferior"]).reset_index()
                bb.columns = ["Fecha"] + list(tecnicos["tabla"].columns)
                bb = bb.tail(400)

                banda = alt.Chart(bb).mark_area(opacity=0.15, color=C0).encode(
                    eje_x("Fecha:T", "Fecha"),
                    eje_y("BandaInferior:Q", f"Precio ({moneda})",
                          scale=alt.Scale(zero=False)),
                    y2="BandaSuperior:Q")
                precio_l = alt.Chart(bb).mark_line(color=C0, strokeWidth=1.6).encode(
                    x="Fecha:T", y="Close:Q",
                    tooltip=[alt.Tooltip("Fecha:T", title="Fecha"),
                             alt.Tooltip("Close:Q", title="Cierre", format=",.2f"),
                             alt.Tooltip("RSI:Q", title="RSI", format=".0f")])
                media_l = alt.Chart(bb).mark_line(color=C1, strokeWidth=1.2,
                                                  strokeDash=[5, 4]).encode(
                    x="Fecha:T", y="SMA:Q")
                st.altair_chart((banda + precio_l + media_l).properties(height=330))

                rsi_df = bb[["Fecha", "RSI"]].dropna()
                rsi_ch = alt.Chart(rsi_df).mark_line(color=C0, strokeWidth=1.4).encode(
                    eje_x("Fecha:T", "Fecha"),
                    eje_y("RSI:Q", "RSI (14)", scale=alt.Scale(domain=[0, 100])),
                    tooltip=[alt.Tooltip("Fecha:T", title="Fecha"),
                             alt.Tooltip("RSI:Q", title="RSI", format=".0f")])
                umbrales = alt.Chart(pd.DataFrame({
                    "y": [30, 70], "nivel": ["Sobreventa (30)", "Sobrecompra (70)"]})
                ).mark_rule(strokeDash=[5, 4], color=GRIS).encode(
                    y="y:Q", tooltip=alt.Tooltip("nivel:N", title="Nivel"))
                st.altair_chart((rsi_ch + umbrales).properties(height=220))
                st.caption(
                    f"Ahora mismo: RSI **{tecnicos['rsi']:.0f}**, "
                    f"{pct(tecnicos['dist_sma20'], 1)} respecto a su media de 20 "
                    f"sesiones y {pct(tecnicos['dist_sma200'], 1)} respecto a la de 200."
                )


# =============================================================================
#  VOLUMEN
# =============================================================================

with tab_vol:
    st.subheader("Volumen de negociación frente a los retornos")
    st.caption(
        "Relación estadística entre el volumen negociado y la magnitud del "
        "movimiento diario. El volumen relativo compara cada sesión con la media "
        "de las 20 anteriores del propio activo."
    )

    if volumen is None:
        st.warning("Yahoo no devuelve volumen para este activo.",
                   icon=":material/warning:")
    else:
        with st.container(horizontal=True):
            st.metric("Volumen de hoy", f"{volumen['volumen_hoy']:,.0f}",
                      f"×{volumen['vol_relativo_hoy']:.2f} de su media 20 sesiones",
                      delta_color="off", border=True)
            st.metric("Correlación volumen ↔ |retorno|",
                      f"{volumen['correlacion']:+.2f}",
                      "correlación positiva" if volumen["correlacion"] > 0.1
                      else ("correlación negativa" if volumen["correlacion"] < -0.1
                            else "sin correlación apreciable"),
                      delta_color="off", border=True)
            st.metric("Volumen en días extremos",
                      f"×{volumen['vol_rel_extremos']:.2f}",
                      f"{volumen['n_extremos']} sesiones de más de 2σ",
                      delta_color="off", border=True)
            st.metric("Volumen: subidas vs bajadas",
                      f"×{volumen['vol_rel_subidas']:.2f} / ×{volumen['vol_rel_bajadas']:.2f}",
                      "media en sesiones al alza / a la baja",
                      delta_color="off", border=True)

        dfv = volumen["datos"].reset_index()
        dfv.columns = ["Fecha"] + list(volumen["datos"].columns)
        dfv["Signo"] = np.where(dfv["LogReturn"] >= 0, "Subida", "Bajada")

        with st.container(border=True):
            st.subheader("¿Los movimientos grandes vienen con más volumen?")
            disp = alt.Chart(dfv).mark_circle(size=45, opacity=0.5).encode(
                eje_x("VolRelativo:Q", "Volumen relativo (×media de 20 sesiones)"),
                eje_y("AbsRetorno:Q", "Movimiento absoluto del día", formato=".0%"),
                color=alt.Color("Signo:N", title=None, scale=alt.Scale(
                    domain=["Subida", "Bajada"], range=[VERDE, ROJO]),
                    legend=alt.Legend(orient="top-left")),
                tooltip=[alt.Tooltip("Fecha:T", title="Fecha"),
                         alt.Tooltip("VolRelativo:Q", title="Vol. relativo", format=".2f"),
                         alt.Tooltip("LogReturn:Q", title="Retorno", format="+.2%")],
            )
            tend = disp.transform_regression("VolRelativo", "AbsRetorno").mark_line(
                color=NAVY, strokeDash=[6, 4])
            st.altair_chart((disp + tend).properties(height=380).interactive())
            st.caption(f"Correlación **{volumen['correlacion']:+.2f}**. Cada punto es "
                       f"una sesión: a la derecha, días de volumen inusual.")

        col_m, col_n = st.columns(2)
        with col_m:
            with st.container(border=True):
                st.subheader("Volumen diario")
                ch = alt.Chart(dfv.tail(400)).mark_bar(opacity=0.75).encode(
                    eje_x("Fecha:T", "Fecha"),
                    eje_y("Volume:Q", "Volumen"),
                    color=alt.Color("Signo:N", title=None, scale=alt.Scale(
                        domain=["Subida", "Bajada"], range=[VERDE, ROJO]),
                        legend=alt.Legend(orient="top-left")),
                    tooltip=[alt.Tooltip("Fecha:T", title="Fecha"),
                             alt.Tooltip("Volume:Q", title="Volumen", format=",.0f"),
                             alt.Tooltip("LogReturn:Q", title="Retorno", format="+.2%")],
                ).properties(height=300)
                st.altair_chart(ch.interactive())

        with col_n:
            with st.container(border=True):
                st.subheader("Precio y volumen relativo")
                p = alt.Chart(dfv.tail(400)).mark_line(color=C0, strokeWidth=1.5).encode(
                    eje_x("Fecha:T", "Fecha"),
                    eje_y("Close:Q", f"Precio ({moneda})", scale=alt.Scale(zero=False)),
                    tooltip=[alt.Tooltip("Fecha:T", title="Fecha"),
                             alt.Tooltip("Close:Q", title="Cierre", format=",.2f"),
                             alt.Tooltip("VolRelativo:Q", title="Vol. rel.", format=".2f")],
                ).properties(height=300)
                st.altair_chart(p.interactive())
                st.caption("Los picos de volumen relativo señalan las sesiones con "
                           "una actividad de negociación inusual frente a su media.")


# =============================================================================
#  COMPARATIVA
# =============================================================================

with tab_comp:
    if not benchmark or benchmark == ticker:
        st.info("Elige un ticker de comparación distinto en la barra lateral.",
                icon=":material/compare_arrows:")
    else:
        try:
            info_b, caida_b = cargar_info(benchmark), False
        except motor.FalloDeFuente:
            info_b, caida_b = None, True
        if caida_b:
            st.error(
                f"Yahoo Finance no responde; no se ha podido comprobar "
                f"**{benchmark}**. El símbolo puede ser correcto: es un problema "
                f"temporal de la fuente.", icon=":material/cloud_off:")
        elif info_b is None:
            st.error(f"**{benchmark}** no devuelve datos.", icon=":material/error:")
        else:
            par, fallo_par = None, None
            with st.spinner(f"Descargando {benchmark}…"):
                try:
                    par = cargar_par(ticker, benchmark, motor.FECHA_INICIO_PERF)
                except motor.FalloDeFuente as e:
                    fallo_par = str(e)

            if fallo_par:
                st.error(
                    f"No ha sido posible alinear las series de **{ticker}** y "
                    f"**{benchmark}**: {fallo_par}. **No significa que el "
                    f"símbolo sea incorrecto**; suele deberse a que el "
                    f"proveedor ha limitado las peticiones. Vuelve a "
                    f"intentarlo en unos segundos.", icon=":material/cloud_off:")
            else:
                stats = {t: motor.analizar_performance_profesional(par[t])
                         for t in (ticker, benchmark)}

                st.subheader(f"Análisis de Eficiencia: {ticker} vs {benchmark}")

                # Cada serie viene en la divisa de su mercado y NO se convierte.
                # Sin avisar, la diferencia de rentabilidad entre ambas incorpora
                # el movimiento del tipo de cambio como si fuera comportamiento
                # del activo, y el Sharpe compara las dos con una unica tasa sin
                # riesgo que solo corresponde a una de las dos monedas.
                moneda_b = info_b[1] if len(info_b) > 1 else None
                if moneda_b and moneda and moneda_b != moneda:
                    st.warning(
                        f"**{ticker}** cotiza en **{moneda}** y **{benchmark}** en "
                        f"**{moneda_b}**. Las series no se convierten a una divisa "
                        f"común: la diferencia de rentabilidad entre ambas recoge "
                        f"también la variación del tipo de cambio {moneda}/{moneda_b} "
                        f"del periodo, y los ratios de Sharpe y Sortino se calculan "
                        f"con una única tasa sin riesgo. La volatilidad y el "
                        f"drawdown de cada valor por separado sí son comparables; "
                        f"la diferencia de retorno entre ambos, no.",
                        icon=":material/currency_exchange:")
                resumen = pd.DataFrame({
                    "Métrica": ["Retorno Anual", "Volatilidad", "Sharpe Ratio",
                                "Sortino Ratio", "Max Drawdown", "Ratio Calmar"],
                    ticker: [stats[ticker]["Retorno Anualizado"],
                             stats[ticker]["Volatilidad Anual"],
                             stats[ticker]["Sharpe Ratio"], stats[ticker]["Sortino Ratio"],
                             stats[ticker]["Max Drawdown"], stats[ticker]["Ratio de Calmar"]],
                    benchmark: [stats[benchmark]["Retorno Anualizado"],
                                stats[benchmark]["Volatilidad Anual"],
                                stats[benchmark]["Sharpe Ratio"],
                                stats[benchmark]["Sortino Ratio"],
                                stats[benchmark]["Max Drawdown"],
                                stats[benchmark]["Ratio de Calmar"]]})
                st.dataframe(resumen, hide_index=True, column_config={
                    ticker: st.column_config.NumberColumn(format="%.4f"),
                    benchmark: st.column_config.NumberColumn(format="%.4f")})

                with st.container(border=True):
                    st.subheader("Evolución del Capital (Base 1.0)")
                    eq = pd.DataFrame({t: stats[t]["Equity_Curve"]
                                       for t in (ticker, benchmark)}).reset_index()
                    eq.columns = ["Fecha", ticker, benchmark]
                    largo = eq.melt("Fecha", var_name="Activo", value_name="Valor")
                    ch = alt.Chart(largo).mark_line(strokeWidth=1.8).encode(
                        eje_x("Fecha:T", "Fecha"),
                        eje_y("Valor:Q", "Valor de la cartera", scale=alt.Scale(zero=False)),
                        color=alt.Color("Activo:N", title=None, scale=alt.Scale(
                            domain=[ticker, benchmark], range=[C0, C1])),
                        tooltip=[alt.Tooltip("Fecha:T", title="Fecha"),
                                 alt.Tooltip("Activo:N"),
                                 alt.Tooltip("Valor:Q", title="Valor", format=",.2f")],
                    ).properties(height=340)
                    st.altair_chart(ch.interactive())

                with st.container(border=True):
                    st.subheader("Historial de Drawdowns")
                    dd = pd.DataFrame({t: stats[t]["Series_Drawdown"]
                                       for t in (ticker, benchmark)}).reset_index()
                    dd.columns = ["Fecha", ticker, benchmark]
                    largo_dd = dd.melt("Fecha", var_name="Activo", value_name="Caida")
                    ch = alt.Chart(largo_dd).mark_area(opacity=0.25).encode(
                        eje_x("Fecha:T", "Fecha"),
                        eje_y("Caida:Q", "Caída desde máximos", formato=".0%"),
                        color=alt.Color("Activo:N", title=None, scale=alt.Scale(
                            domain=[ticker, benchmark], range=[C0, C1])),
                        tooltip=[alt.Tooltip("Fecha:T", title="Fecha"),
                                 alt.Tooltip("Activo:N"),
                                 alt.Tooltip("Caida:Q", title="Caída", format=".2%")],
                    ).properties(height=320)
                    st.altair_chart(ch.interactive())

                col_o, col_p = st.columns(2)
                with col_o:
                    with st.container(border=True):
                        st.subheader("Mapa de Riesgo-Retorno")
                        mapa = pd.DataFrame({
                            "Activo": [ticker, benchmark],
                            "Volatilidad": [stats[t]["Volatilidad Anual"]
                                            for t in (ticker, benchmark)],
                            "Retorno": [stats[t]["Retorno Anualizado"]
                                        for t in (ticker, benchmark)]})
                        tope = float(mapa["Volatilidad"].max()) * 1.1
                        pts = alt.Chart(mapa).mark_circle(size=320).encode(
                            eje_x("Volatilidad:Q", "Volatilidad", formato=".0%"),
                            eje_y("Retorno:Q", "Retorno", formato=".0%"),
                            color=alt.Color("Activo:N", title=None, scale=alt.Scale(
                                domain=[ticker, benchmark], range=[C0, C1])),
                            tooltip=[alt.Tooltip("Activo:N"),
                                     alt.Tooltip("Volatilidad:Q", format=".2%"),
                                     alt.Tooltip("Retorno:Q", format=".2%")])
                        diag = alt.Chart(pd.DataFrame({
                            "x": [0, tope], "y": [0, tope]})).mark_line(
                            color=GRIS, strokeDash=[5, 5], opacity=0.6).encode(
                            x="x:Q", y="y:Q")
                        st.altair_chart((diag + pts).properties(height=320))
                        st.caption("La diagonal gris es Sharpe = 1.0.")

                with col_p:
                    with st.container(border=True):
                        st.subheader("Correlación de Retornos")
                        rets_par = np.log(par / par.shift(1)).dropna()
                        corr = rets_par.corr()
                        cm = corr.reset_index().melt(
                            id_vars=corr.index.name or "index",
                            var_name="B", value_name="Correlacion")
                        cm.columns = ["A", "B", "Correlacion"]
                        heat = alt.Chart(cm).mark_rect().encode(
                            alt.X("A:N", title=None), alt.Y("B:N", title=None),
                            color=alt.Color("Correlacion:Q", scale=alt.Scale(
                                scheme="redblue", domain=[-1, 1], reverse=True),
                                legend=None),
                            tooltip=[alt.Tooltip("Correlacion:Q", format=".2f")])
                        texto = heat.mark_text(fontSize=18, fontWeight="bold").encode(
                            text=alt.Text("Correlacion:Q", format=".2f"),
                            color=alt.value("white"))
                        st.altair_chart((heat + texto).properties(height=320))
                        st.caption(f"Correlación diaria: "
                                   f"**{float(corr.iloc[0, 1]):.2f}**")


# =============================================================================
#  FUNDAMENTALES  (implementacion en pestana_fundamentales.py)
# =============================================================================

with tab_fund:
    if abierta("Fundamentales"):
        pestana_fundamentales.render(ticker, nombre, moneda, situacion["precio"])
    else:
        aplazada()


# =============================================================================
#  OPCIONES Y MICROESTRUCTURA  (implementacion en pestana_mercado.py)
# =============================================================================

with tab_opc:
    if abierta("Opciones y microestructura"):
        _mov_ultimo = situacion["mov_dia"]
        if earnings and earnings["eventos"]:
            _ult = earnings["eventos"][-1]
            if _ult["sesiones_desde"] <= 2:
                _mov_ultimo = _ult["mov"]
        pestana_mercado.render(ticker, nombre, moneda,
                               sigma_diaria=situacion["sigma_dia"],
                               mov_ultimo=_mov_ultimo)
    else:
        aplazada()


# =============================================================================
#  CRIBADO DEL MERCADO  (implementacion en pestana_cribado.py)
# =============================================================================

with tab_crib:
    if abierta("Selección de valores"):
        pestana_cribado.render(umbral_defecto=umbral_sigmas)
    else:
        aplazada()


# =============================================================================
#  GRAFICO DE COTIZACION  (implementacion en pestana_grafico.py)
# =============================================================================

with tab_graf:
    if abierta("Gráfico"):
        pestana_grafico.render(ticker, nombre, moneda)
    else:
        aplazada()


# =============================================================================
#  DCF - DESCUENTO DE FLUJOS DE CAJA  (implementacion en pestana_dcf.py)
# =============================================================================
# Independiente del generador de informes y del ticker de la cabecera: la
# pestaña tiene su propio cuadro de valor, sus propios supuestos y su propia
# exportacion, de modo que se puede valorar aqui una empresa distinta de la que
# se este analizando arriba sin que una cosa arrastre a la otra.

with tab_dcf:
    if abierta("DCF"):
        pestana_dcf.render(ticker_defecto=ticker)
    else:
        aplazada()
