"""Bloques de ANALISIS COMPLEMENTARIO del apartado de seleccion de valores.

Cuatro examenes criticos del resultado del cribado. Ninguno interviene en la
seleccion: el motor de busqueda devuelve exactamente los mismos valores en el
mismo orden con o sin este modulo. Lo que aportan es la respuesta a preguntas
que el propio cribado no puede contestar sobre si mismo.

Vive separado de pestana_cribado.py por tamano, no por naturaleza: son la parte
de representacion de motor_validacion, motor_factores, motor_regimen y
motor_origen.
"""

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

import motor_factores as fac
import motor_origen as ori
import motor_regimen as reg
import motor_validacion as val

C0 = "#1f77b4"
VERDE = "#2CA02C"
ROJO = "#D62728"
GRIS = "#7F7F7F"
REJILLA = {"grid": True, "gridColor": "#DDDDDD", "gridOpacity": 0.9}


def pct(valor, decimales=2, signo=True):
    """Porcentaje formateado, con raya cuando no hay dato."""
    if valor is None or not np.isfinite(valor):
        return "—"
    return f"{valor:+.{decimales}%}" if signo else f"{valor:.{decimales}%}"


# =============================================================================
#  1 · CONTRASTE MULTIPLE
# =============================================================================

def contraste(resultado, tabla, ventana):
    """Cuantos de los valores listados resisten haber sido elegidos entre 503."""
    c = resultado.get("contraste")
    if not c or not c["contrastes"]:
        st.info(
            "No hay contrastes suficientes para aplicar la corrección. Se "
            "requieren al menos tres episodios previos por valor.",
            icon=":material/info:")
        return

    st.markdown(
        "Al examinar quinientas tres sociedades y conservar las que mejor se "
        "comportaron, la selección se realiza sobre los mismos datos con los "
        "que después se mide. Una parte de los valores destacados lo estarán "
        "por azar. El procedimiento de **Benjamini-Hochberg** controla la "
        "proporción de falsos hallazgos entre los declarados.")

    with st.container(horizontal=True):
        st.metric("Contrastes realizados", f"{c['contrastes']}",
                  "un valor, un contraste", delta_color="off", border=True)
        st.metric("Superan la corrección", f"{c['supervivientes']}",
                  f"tasa de falsos hallazgos {c['tasa']:.0%}",
                  delta_color="off", border=True)
        st.metric("Esperados por azar", f"{c['esperados_por_azar']:.1f}",
                  "sin efecto real alguno", delta_color="off", border=True)
        st.metric("Umbral de Bonferroni", f"{c['umbral_bonferroni']:.4f}",
                  "referencia conservadora", delta_color="off", border=True)

    if c["supervivientes"] == 0:
        st.warning(
            f"**Ningún valor de la relación supera la corrección por contraste "
            f"múltiple.** Con {c['contrastes']} contrastes simultáneos, las "
            f"diferencias observadas son compatibles con lo que produciría el "
            f"azar. Ello no invalida la relación como punto de partida, pero sí "
            f"desaconseja atribuir significación estadística a los retornos "
            f"medios de forma individual.", icon=":material/warning:")
    else:
        st.success(
            f"**{c['supervivientes']} de {c['contrastes']} valores** mantienen "
            f"un retorno posterior distinguible de la referencia del índice una "
            f"vez corregido el efecto de haber examinado el universo completo.",
            icon=":material/verified:")

    if tabla.empty or "q" not in tabla.columns:
        return

    col_media = f"Media +{ventana}d"
    columnas = [c for c in ["Ticker", "Empresa", "Casos previos", col_media,
                            "p", "q", "Supera el contraste"] if c in tabla.columns]
    st.dataframe(
        tabla[columnas], hide_index=True, width="stretch",
        column_config={
            "Empresa": st.column_config.TextColumn(width="medium"),
            "Casos previos": st.column_config.NumberColumn("Episodios", format="%d"),
            col_media: st.column_config.NumberColumn(
                f"Media +{ventana}d", format="percent",
                help="Retorno medio en episodios comparables anteriores."),
            "p": st.column_config.NumberColumn(
                "p", format="%.4f",
                help="Probabilidad de observar este resultado si el valor no "
                     "aportase nada sobre la referencia del índice."),
            "q": st.column_config.NumberColumn(
                "q", format="%.4f",
                help="Valor p corregido por el número de contrastes simultáneos."),
            "Supera el contraste": st.column_config.CheckboxColumn(
                "Resiste", help="Supera la corrección de Benjamini-Hochberg."),
        })
    st.caption(
        "La columna **p** no está corregida y no debe leerse de forma aislada: "
        "con veinte contrastes simultáneos, un valor de 0,05 deja de ser "
        "excepcional. La columna **q** sí incorpora la corrección y es la que "
        "procede consultar.")


# =============================================================================
#  2 · VALIDACION FUERA DE PERIODO
# =============================================================================

def validacion(resultado, cierres, tabla, umbral, ventana):
    """Lo medido en el primer tramo, ¿anticipa algo del segundo?"""
    v = resultado.get("validacion")
    if not v:
        st.info("No hay historia suficiente para partir la muestra en dos tramos.",
                icon=":material/info:")
        return

    L = v["limites"]
    st.markdown(
        "La estadística de la relación se calcula sobre los cinco años "
        "completos, de modo que los episodios medidos son también los que "
        "determinaron la selección. Aquí la muestra se parte: los episodios del "
        "**primer tramo** construyen la estadística y los del **segundo** la "
        "ponen a prueba sin haber intervenido en su cálculo.")
    st.caption(
        f"Construcción: {L['inicio_dentro'].date()} a {L['fin_dentro'].date()} · "
        f"Validación: {L['inicio_fuera'].date()} a {L['fin_fuera'].date()} · "
        f"Se descartan {L['purga']} sesiones a cada lado de la frontera "
        f"({L['frontera'].date()}) por purga y embargo, para que ningún episodio "
        f"tenga su horizonte a caballo entre ambos tramos.")

    correl = v["correlacion"]
    with st.container(horizontal=True):
        st.metric("Valores comparables", f"{v['valores']}",
                  "con episodios en ambos tramos", delta_color="off", border=True)
        st.metric("Media en construcción", pct(v["media_dentro"]),
                  "primer tramo", delta_color="off", border=True)
        st.metric("Media en validación", pct(v["media_fuera"]),
                  "segundo tramo, no utilizado", delta_color="off", border=True)
        st.metric("Correlación entre tramos",
                  f"{correl:+.3f}" if np.isfinite(correl) else "—",
                  (f"p = {v['p_correlacion']:.3f}"
                   if np.isfinite(v.get("p_correlacion", np.nan)) else "—"),
                  delta_color="off", border=True)

    if np.isfinite(correl):
        if correl < 0.15:
            st.warning(
                f"**La correlación entre ambos tramos es de {correl:+.3f}.** Lo "
                f"medido en el primer periodo apenas guarda relación con lo "
                f"ocurrido en el segundo: el historial de rebote no muestra "
                f"capacidad de anticipación, por vistosas que resulten las "
                f"medias de la relación.", icon=":material/warning:")
        elif correl < 0.35:
            st.info(
                f"**Correlación moderada ({correl:+.3f}).** Existe cierta "
                f"persistencia entre lo medido y lo ocurrido después, si bien "
                f"débil: conviene tratar el historial como indicio y no como "
                f"estimación fiable.", icon=":material/info:")
        else:
            st.success(
                f"**Correlación de {correl:+.3f} entre ambos tramos.** El "
                f"comportamiento medido en el periodo de construcción guarda "
                f"relación apreciable con el observado después, lo que respalda "
                f"que el historial contiene información y no solo ruido.",
                icon=":material/verified:")

    tv = v["tabla"]
    comparables = tv[tv["Comparable"]]
    if not comparables.empty:
        st.dataframe(
            comparables[["Ticker", "Episodios dentro", "Media dentro",
                         "Episodios fuera", "Media fuera", "Deterioro"]],
            hide_index=True, width="stretch",
            column_config={
                "Media dentro": st.column_config.NumberColumn(format="percent"),
                "Media fuera": st.column_config.NumberColumn(format="percent"),
                "Deterioro": st.column_config.NumberColumn(
                    format="percent",
                    help="Diferencia entre el segundo tramo y el primero. "
                         "Negativo indica que el comportamiento empeoró."),
            })

    incomparables = int((~tv["Comparable"]).sum())
    if incomparables:
        st.caption(
            f":material/info: {incomparables} valor(es) no aparecen por no "
            f"alcanzar tres episodios en alguno de los dos tramos.")

    st.markdown("**Estabilidad a lo largo de la historia**")
    st.caption(
        "Una única partición puede caer en un tramo atípico. Repartir la "
        "muestra en cinco pliegues disjuntos, con purga y embargo entre ellos, "
        "indica si el comportamiento se sostiene o depende del periodo que "
        "toque examinar.")
    with st.spinner("Recorriendo los pliegues…"):
        vc = val.validacion_cruzada_purgada(
            cierres, list(tabla["Ticker"]) if not tabla.empty else [],
            umbral, ventana)
    if not vc:
        st.caption("Sin datos suficientes para la validación cruzada.")
        return

    st.dataframe(
        vc["tabla"], hide_index=True, width="stretch",
        column_config={
            "Media": st.column_config.NumberColumn(format="percent"),
            "% en positivo": st.column_config.NumberColumn(format="percent"),
            "Episodios": st.column_config.NumberColumn(format="%d"),
        })
    disp = vc["dispersion"]
    st.caption(
        f"Media de los pliegues {vc['media']:+.2%} con dispersión de "
        f"{disp:.2%}. Pliegues con media positiva: {vc['positivos']} de "
        f"{vc['pliegues']}. Una dispersión del orden de la media indica que el "
        f"resultado depende en buena medida del periodo examinado.")


# =============================================================================
#  3 · DESCOMPOSICION FACTORIAL
# =============================================================================

def factorial(cierres, umbral, ventana, cargar_serie, cargar_factores):
    """¿Es alfa o son primas conocidas con otro nombre?"""
    st.markdown(
        "Comprar valores que acaban de desplomarse es, mecánicamente, cargarse "
        "de **reversión a corto plazo**, de beta elevada y a menudo de valor. "
        "Son primas documentadas y accesibles por vías más baratas. Aquí se "
        "construye la serie histórica de una cartera que aplica esta estrategia "
        "y se descuenta de ella todo lo que explican los factores conocidos.")
    st.caption(
        "Factores diarios de la biblioteca de Kenneth French (Tuck School of "
        "Business, Dartmouth), de acceso público y gratuito. Errores estándar de "
        "Newey-West: al mantener cada posición varias sesiones los retornos se "
        "solapan, y los errores ordinarios inflarían el estadístico t hasta "
        "declarar significativo un alfa inexistente.")

    if not st.toggle("Calcular la descomposición factorial", value=False,
                     key="crib_fac_activo",
                     help="Descarga las series de factores y reconstruye la "
                          "cartera histórica."):
        return

    with st.spinner("Reconstruyendo la cartera histórica…"):
        serie = cargar_serie(umbral, ventana)
    if not serie:
        st.info("No hay historia suficiente para reconstruir la serie.",
                icon=":material/info:")
        return

    with st.spinner("Descargando los factores…"):
        factores = cargar_factores()
    if factores is None:
        st.error(
            "La biblioteca de Kenneth French no responde en este momento. **No "
            "es un problema de los datos de mercado**: la descomposición es un "
            "complemento y el resto del apartado no se ve afectado.",
            icon=":material/cloud_off:")
        return

    d = fac.regresion_factorial(serie, factores)
    if not d:
        st.info("El periodo común entre la cartera y los factores es insuficiente.",
                icon=":material/info:")
        return

    with st.container(horizontal=True):
        st.metric("Exceso bruto anualizado", pct(d["exceso_anual"]),
                  "antes de descontar nada", delta_color="off", border=True)
        st.metric("Explicado por los factores", pct(d["explicado_anual"]),
                  "primas conocidas", delta_color="off", border=True)
        st.metric("Residuo anualizado", pct(d["alfa_anual"]),
                  f"t = {d['t_alfa']:.2f}", delta_color="off", border=True)
        st.metric("Varianza explicada", f"{d['r2_ajustado']:.1%}",
                  "R² ajustado", delta_color="off", border=True)

    texto = fac.resumen_legible(d)
    if d["significativo"] and d["alfa_anual"] > 0:
        st.success(texto, icon=":material/verified:")
    elif d["significativo"]:
        st.warning(texto, icon=":material/warning:")
    else:
        st.info(texto, icon=":material/info:")

    st.markdown("**Exposición a cada factor**")
    cargas = d["cargas"]
    st.dataframe(
        cargas[["Factor", "Carga", "t", "Significativa", "Descripción"]],
        hide_index=True, width="stretch",
        column_config={
            "Carga": st.column_config.NumberColumn(format="%.3f"),
            "t": st.column_config.NumberColumn(format="%.2f"),
            "Significativa": st.column_config.CheckboxColumn("|t| ≥ 2"),
            "Descripción": st.column_config.TextColumn(width="large"),
        })

    grafico = cargas.copy()
    grafico["Signo"] = np.where(grafico["Carga"] >= 0, "Positiva", "Negativa")
    ch = alt.Chart(grafico).mark_bar().encode(
        x=alt.X("Carga:Q", title="Carga factorial", axis=alt.Axis(**REJILLA)),
        y=alt.Y("Factor:N", title=None, sort="-x"),
        color=alt.Color("Signo:N", title=None, scale=alt.Scale(
            domain=["Positiva", "Negativa"], range=[C0, ROJO])),
        tooltip=[alt.Tooltip("Factor:N"), alt.Tooltip("Carga:Q", format=".3f"),
                 alt.Tooltip("t:Q", format=".2f")],
    ).properties(height=240)
    st.altair_chart(ch)

    st.caption(
        f"Periodo {d['desde'].date()} a {d['hasta'].date()} · "
        f"{d['observaciones']:,} sesiones · {serie['entradas']:,} entradas "
        f"históricas · {d['retardos']} retardos de Newey-West. Los factores se "
        f"publican con algunas semanas de retraso, de modo que el análisis "
        f"termina en {d['hasta'].date()} aunque los precios lleguen hasta hoy.")


# =============================================================================
#  4 · REGIMEN POR ACTIVO Y SECTOR
# =============================================================================

def regimen(cierres, universo, tabla, umbral, ventana):
    """Estado del valor y de su sector ANTES de caer, y rebote condicionado."""
    st.markdown(
        "El rebote no es una constante del valor: depende del estado en que se "
        "encontraba al caer. Aquí el régimen se determina en **dos niveles "
        "propios del valor** —su propia volatilidad y la de su sector—, nunca "
        "con un indicador general de mercado: una utility y una compañía de "
        "semiconductores no comparten volatilidad típica, y clasificarlas con "
        "la misma vara produce composiciones erróneas.")
    st.caption(
        "El régimen se mide con la volatilidad realizada de 21 sesiones situada "
        "en el percentil de la propia historia del valor, y **desplazada una "
        "sesión**: incluir la caída que se analiza haría que todo candidato "
        "apareciese en tensión por pura construcción.")

    if tabla.empty:
        st.caption("No hay valores en la relación.")
        return

    fechas = dict(zip(tabla["Ticker"], pd.to_datetime(tabla["Fecha"])))
    with st.spinner("Determinando el régimen de cada valor…"):
        cuadro = reg.cuadro_regimenes(list(tabla["Ticker"]), cierres, universo,
                                      umbral, ventana, fechas=fechas)
    if not cuadro:
        st.info("No hay historia suficiente para situar el régimen.",
                icon=":material/info:")
        return

    t = cuadro["tabla"]
    reparto = t["Régimen del valor"].value_counts().to_dict()
    with st.container(horizontal=True):
        for estado in reg.ESTADOS:
            st.metric(f"En {estado.lower()}", f"{reparto.get(estado, 0)}",
                      "antes de caer", delta_color="off", border=True)
        propias = int((t["Divergencia"] == "Tensión propia").sum())
        st.metric("Tensión propia", f"{propias}",
                  "con su sector en calma", delta_color="off", border=True)

    st.dataframe(
        t[["Ticker", "Sector", "Régimen del valor", "Percentil propio",
           "Régimen del sector", "Percentil sectorial", "Divergencia",
           "Media en este régimen", "Episodios en este régimen",
           "Episodios totales"]],
        hide_index=True, width="stretch",
        column_config={
            "Sector": st.column_config.TextColumn(width="medium"),
            "Percentil propio": st.column_config.NumberColumn(format="percent"),
            "Percentil sectorial": st.column_config.NumberColumn(format="percent"),
            "Media en este régimen": st.column_config.NumberColumn(
                format="percent",
                help="Rebote medio del valor en episodios anteriores ocurridos "
                     "estando en este mismo régimen."),
            "Episodios en este régimen": st.column_config.NumberColumn(format="%d"),
            "Episodios totales": st.column_config.NumberColumn(format="%d"),
        })
    st.caption(
        "**Tensión propia** señala los valores en tensión mientras su sector "
        "está en calma o normalidad: el problema es suyo. **Tensión sectorial** "
        "los que caen con todo su sector. La media condicionada descansa a "
        "menudo en pocos episodios; la columna contigua lo indica.")

    elegido = st.selectbox(
        "Desglose por régimen de un valor concreto", list(t["Ticker"]),
        key="crib_reg_valor")
    if not elegido:
        return
    sectores = {}
    if universo is not None and "Sector" in universo.columns:
        sectores = dict(zip(universo["Ticker"], universo["Sector"]))
    r = reg.regimen_de(elegido, cierres, universo, sectores.get(elegido),
                       fechas.get(elegido))
    cond = reg.rebote_por_regimen(elegido, cierres, umbral, ventana, r) if r else None
    if not cond:
        st.caption("Sin datos suficientes para el desglose.")
        return

    st.dataframe(
        cond["tabla"][["Régimen", "Episodios", "Media", "% en positivo", "Peor"]],
        hide_index=True, width="stretch",
        column_config={
            "Episodios": st.column_config.NumberColumn(format="%d"),
            "Media": st.column_config.NumberColumn(format="percent"),
            "% en positivo": st.column_config.NumberColumn(format="percent"),
            "Peor": st.column_config.NumberColumn(format="percent"),
        })
    if cond["estado_actual"]:
        st.caption(
            f"**{elegido}** se encontraba en régimen de "
            f"**{cond['estado_actual'].lower()}** antes de esta caída, con "
            f"{cond['episodios_actual']} episodios comparables de "
            f"{cond['total']} totales. Si la media global de la relación "
            f"descansa en episodios de otro régimen, no describe la situación "
            f"actual del valor.")


# =============================================================================
#  5 · ORIGEN DE LA CAIDA
# =============================================================================

def origen(cierres, universo, tabla, umbral, cargar_resultados, cargar_noticias):
    """Qué provocó cada caída y cómo suele terminar cada tipo de caída."""
    st.markdown(
        "Una caída por resultados no es el mismo suceso que una caída por "
        "arrastre del índice, aunque el número sea idéntico. Promediarlas "
        "juntas mezcla poblaciones con desenlaces distintos. Aquí cada episodio "
        "se clasifica por su origen y se mide el desenlace **a 1, 3, 5, 10 y 15 "
        "sesiones** de cada categoría por separado.")

    candidatos = list(tabla["Ticker"]) if not tabla.empty else []
    total = st.select_slider(
        "Valores con cobertura de resultados", options=[40, 60, 80, 120],
        value=60, key="crib_ori_muestra",
        help="Las fechas de publicación se consultan de una en una, a razón de "
             "aproximadamente un segundo por valor. Se conservan en memoria "
             "durante doce horas.")

    if not st.toggle("Clasificar los episodios por origen", value=False,
                     key="crib_ori_activo",
                     help=f"Recuperará las fechas de resultados de unos {total} "
                          f"valores; la primera ejecución tarda alrededor de "
                          f"{total} segundos."):
        return

    muestra = ori.muestra_para_cobertura(universo, candidatos, total)
    with st.spinner(f"Recuperando fechas de resultados de {len(muestra)} valores…"):
        fechas_res = cargar_resultados(tuple(muestra))
    if not fechas_res:
        st.error(
            "No ha sido posible recuperar las fechas de publicación de "
            "resultados. Sin ellas no se puede aislar la categoría más "
            "relevante y la clasificación quedaría incompleta.",
            icon=":material/cloud_off:")
        return

    with st.spinner("Clasificando los episodios de cinco años…"):
        clas = ori.clasificar_universo(cierres, universo, umbral=umbral,
                                       fechas_resultados=fechas_res)
        desenlace = ori.desenlace_por_categoria(clas) if clas else None
    if not desenlace:
        st.info("No hay episodios suficientes para la clasificación.",
                icon=":material/info:")
        return

    st.caption(
        f"{desenlace['total']:,} episodios de {desenlace['valores_examinados']} "
        f"valores con cobertura de resultados. El cálculo se **restringe a esos "
        f"valores** de forma deliberada: si se incluyesen los que carecen de "
        f"fechas de publicación, sus caídas por resultados se repartirían sin "
        f"etiquetar entre las otras tres categorías y contaminarían justo la "
        f"comparación que se pretende hacer. Las referencias de índice y de "
        f"sector sí se calculan sobre las {desenlace['valores_totales']} "
        f"sociedades del universo.")

    tab = desenlace["tabla"]
    horizontes = desenlace["horizontes"]

    st.dataframe(
        tab[["Categoría", "Episodios", "Caída media"] +
            [f"+{h}d" for h in horizontes]],
        hide_index=True, width="stretch",
        column_config={
            "Episodios": st.column_config.NumberColumn(format="%d"),
            "Caída media": st.column_config.NumberColumn(format="percent"),
            **{f"+{h}d": st.column_config.NumberColumn(
                f"+{h}d", format="percent",
                help=f"Retorno medio acumulado {h} sesiones después.")
               for h in horizontes},
        })

    largo = []
    for _, fila in tab.iterrows():
        for h in horizontes:
            if np.isfinite(fila.get(f"+{h}d", np.nan)):
                largo.append({"Categoría": fila["Categoría"], "Sesiones": h,
                              "Retorno": fila[f"+{h}d"],
                              "Positivos": fila.get(f"pos{h}", np.nan),
                              "Episodios": fila.get(f"n{h}", 0)})
    if largo:
        df = pd.DataFrame(largo)
        linea = alt.Chart(df).mark_line(point=True, strokeWidth=2).encode(
            x=alt.X("Sesiones:Q", title="Sesiones después de la caída",
                    axis=alt.Axis(values=list(horizontes), **REJILLA)),
            y=alt.Y("Retorno:Q", title="Retorno medio acumulado",
                    axis=alt.Axis(format="%", **REJILLA)),
            color=alt.Color("Categoría:N", title="Origen de la caída"),
            tooltip=[alt.Tooltip("Categoría:N"), alt.Tooltip("Sesiones:Q"),
                     alt.Tooltip("Retorno:Q", format="+.2%"),
                     alt.Tooltip("Positivos:Q", format=".0%",
                                 title="Episodios al alza"),
                     alt.Tooltip("Episodios:Q", format="d")],
        ).properties(height=360)
        cero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(
            color=GRIS, strokeDash=[4, 4]).encode(y="y:Q")
        st.altair_chart(alt.layer(linea, cero))

    st.markdown("**Frecuencia de episodios al alza por categoría**")
    frec = tab[["Categoría"]].copy()
    for h in horizontes:
        frec[f"+{h}d"] = tab[f"pos{h}"]
    st.dataframe(
        frec, hide_index=True, width="stretch",
        column_config={f"+{h}d": st.column_config.NumberColumn(
            f"+{h}d", format="percent") for h in horizontes})

    for _, fila in tab.iterrows():
        with st.expander(f"{fila['Categoría']} · {int(fila['Episodios'])} episodios"):
            st.write(ori.DESCRIPCION.get(fila["Categoría"], ""))
            piezas = []
            for h in horizontes:
                if np.isfinite(fila.get(f"+{h}d", np.nan)):
                    piezas.append(
                        f"a {h} sesiones {fila[f'+{h}d']:+.2%} "
                        f"({fila[f'pos{h}']:.0%} al alza, n={int(fila[f'n{h}'])})")
            if piezas:
                st.caption("Desenlace medio: " + " · ".join(piezas) + ".")

    st.divider()
    st.markdown("**Origen de las caídas identificadas**")
    if tabla.empty:
        st.caption("No hay valores en la relación.")
        return

    noticias = cargar_noticias(tuple(candidatos[:12]), 4)
    registros = (noticias.to_dict("records")
                 if isinstance(noticias, pd.DataFrame) and not noticias.empty else [])

    filas = []
    for _, fila in tabla.head(12).iterrows():
        tk = fila["Ticker"]
        o = ori.origen_actual(tk, fila["Fecha"], cierres, universo,
                              registros, fechas_res.get(tk))
        if not o:
            continue
        ref = tab[tab["Categoría"] == o["categoria"]]
        registro = {
            "Ticker": tk,
            "Caída": fila["Caída"],
            "Origen": o["categoria"],
            "Motivo en prensa": o["motivo_prensa"] or "—",
            "Índice ese día": o["retorno_indice"],
            "Sector ese día": o["retorno_sector"],
        }
        for h in horizontes:
            valor = np.nan
            if not ref.empty and np.isfinite(ref[f"+{h}d"].iloc[0]):
                valor = float(ref[f"+{h}d"].iloc[0])
            registro[f"Histórico +{h}d"] = valor
        filas.append(registro)

    if not filas:
        st.caption("No ha sido posible clasificar las caídas actuales.")
        return

    st.dataframe(
        pd.DataFrame(filas), hide_index=True, width="stretch",
        column_config={
            "Caída": st.column_config.NumberColumn(format="percent"),
            "Índice ese día": st.column_config.NumberColumn(format="percent"),
            "Sector ese día": st.column_config.NumberColumn(format="percent"),
            **{f"Histórico +{h}d": st.column_config.NumberColumn(
                f"Histórico +{h}d", format="percent",
                help=f"Desenlace medio a {h} sesiones de las caídas de este "
                     f"mismo origen en el periodo examinado.")
               for h in horizontes},
        })
    st.caption(
        "Las columnas de histórico recogen el desenlace medio de las caídas del "
        "**mismo origen**, no el de ese valor en particular. El motivo en prensa "
        "procede de los titulares recientes y sirve de corroboración: los "
        "titulares no permiten clasificar el pasado, porque el proveedor solo "
        "publica noticias de los últimos días.")
