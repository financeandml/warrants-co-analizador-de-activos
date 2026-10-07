"""Bloque de DESCARGA DEL INFORME EN PDF, en la pestana de resumen.

La generacion tarda alrededor de minuto y medio porque recorre las 503
sociedades del indice, consulta SEC EDGAR y descarga los factores de riesgo. Por
eso NO se genera al abrir la pestana: se genera cuando el usuario lo pide y el
resultado queda guardado en la sesion, de modo que pueda descargarlo las veces
que quiera sin volver a esperar.

El fichero queda unicamente en memoria del navegador y de la sesion. No se
escribe en disco del servidor: es la conducta que corresponde a una herramienta
que promete no guardar nada.
"""

from datetime import datetime

import streamlit as st

import motor_informe as mi

CLAVE = "informe_pdf"


def _vigente(ticker, firma):
    """El informe guardado sirve si es del mismo activo y de los mismos ajustes."""
    guardado = st.session_state.get(CLAVE)
    return bool(guardado and guardado.get("ticker") == ticker
                and guardado.get("firma") == firma)


def render(ticker, nombre, periodo, confianza, capital, umbral_sigmas,
           benchmark):
    # La fecha entra en la firma: el informe lleva impresa la del dia en que se
    # genera, de modo que el guardado de ayer deja de servir hoy y el boton
    # vuelve a ofrecer generarlo.
    firma = (periodo, round(float(confianza), 2), int(capital),
             round(float(umbral_sigmas), 2), benchmark,
             datetime.now().strftime("%Y-%m-%d"))

    with st.container(border=True):
        izquierda, derecha = st.columns([3, 1.15])

        with izquierda:
            st.markdown("**Informe completo en PDF**")
            st.caption(
                "Reproduce en un folio A4 imprimible todo lo que esta "
                "aplicación muestra para el activo: los trece apartados con sus "
                "cifras, sus tablas y sus gráficos, en el mismo orden. Recoge "
                "los ajustes actuales de la barra lateral —histórico "
                f"{periodo}, confianza {confianza:.1f} %, capital "
                f"{capital:,.0f}, umbral {umbral_sigmas:.1f}σ y comparación "
                f"contra {benchmark}—.")

        pulsado = False
        with derecha:
            if _vigente(ticker, firma):
                guardado = st.session_state[CLAVE]
                st.download_button(
                    "Descargar el PDF", data=guardado["datos"],
                    file_name=guardado["nombre_fichero"],
                    mime="application/pdf", width="stretch",
                    icon=":material/download:", key="descargar_informe")
                st.caption(
                    f"{guardado['paginas']} páginas · "
                    f"{len(guardado['datos'])/1_048_576:.1f} MB · generado a las "
                    f"{guardado['hora']}")
            else:
                pulsado = st.button(
                    "Generar informe", width="stretch", type="primary",
                    icon=":material/picture_as_pdf:", key="generar_informe")
                st.caption("Tarda alrededor de minuto y medio.")

    if not pulsado:
        return

    barra = st.progress(0.0, "Preparando la recopilación…")
    try:
        import informe_datos

        barra.progress(0.10, "Descargando cotizaciones y calculando riesgo…")
        datos = informe_datos.recopilar(
            ticker, periodo=periodo, confianza=confianza,
            umbral_sigmas=umbral_sigmas, referencia=benchmark)

        barra.progress(0.80, "Componiendo el documento…")
        pdf = mi.generar(ticker, capital=capital, datos=datos)

        barra.progress(1.0, "Informe listo.")
    except Exception as e:
        import traceback
        barra.empty()
        st.error(
            f"No ha sido posible generar el informe: {type(e).__name__}: "
            f"{str(e)[:200]}", icon=":material/error:")
        with st.expander("Detalle técnico del fallo"):
            st.code(traceback.format_exc(), language="text")
        st.caption(
            "Si el fallo menciona un símbolo o una descarga, suele deberse a "
            "que el proveedor ha limitado las peticiones. Vuelva a intentarlo "
            "en un minuto.")
        return

    barra.empty()

    paginas = 0
    try:
        from pypdf import PdfReader
        import io
        paginas = len(PdfReader(io.BytesIO(pdf)).pages)
    except Exception:
        paginas = 0

    st.session_state[CLAVE] = {
        "ticker": ticker, "firma": firma, "datos": pdf,
        "paginas": paginas, "hora": datetime.now().strftime("%H:%M"),
        "nombre_fichero": (f"Informe_{ticker}_"
                           f"{datetime.now().strftime('%Y%m%d')}.pdf"),
    }
    incidencias = datos.get("incidencias") or []
    if incidencias:
        st.warning(
            f"El informe se ha generado, pero {len(incidencias)} consulta(s) no "
            f"devolvieron datos. Los apartados afectados lo indican en el "
            f"documento y se relacionan en su última página.",
            icon=":material/warning:")
    else:
        st.success(
            f"Informe de **{nombre}** generado: {paginas} páginas en A4. "
            f"El botón de descarga está arriba a la derecha.",
            icon=":material/check_circle:")
    st.rerun()
