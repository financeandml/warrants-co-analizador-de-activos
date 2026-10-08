"""Verificacion de la APP WEB completa, sin navegador (streamlit.testing).

Ejecuta app_analizador.py como lo haria Streamlit y recorre lo que un usuario
puede hacer: las trece pestañas, los botones que disparan calculo (informe PDF,
Monte Carlo, DCF y su Excel), los calculos opcionales del cribado, el buscador
y el cambio de activo, y el aviso de cierres no positivos (CL=F) en pantalla y
en el PDF. Con --aleatorio repite el recorrido sobre activos y ajustes
elegidos al azar, en orden de pestañas aleatorio.

Cada paso afirma: cero excepciones; que la pestaña abierta NO conserva el aviso
de aplazada (prueba de que su codigo se ejecuto); y que no aparece un aviso de
fuente caida. Lo ultimo importa: sin lxml el cribado no lanzaba excepcion, solo
decia que no habia podido obtener la composicion del S&P 500.

Ejecutar:  python verificar_app.py                       (recorrido completo)
           python verificar_app.py --aleatorio 15         (15 activos al azar)
           python verificar_app.py --aleatorio 15 --semilla 7   (reproducible)
"""

import argparse
import io
import os
import random
import re
import string
import sys
import time

from streamlit.testing.v1 import AppTest

CARPETA = os.path.dirname(os.path.abspath(__file__))
# streamlit run mete la carpeta del guion en sys.path; AppTest no.
sys.path.insert(0, CARPETA)
APP = os.path.join(CARPETA, "app_analizador.py")

PLAZO = 900  # limite por ejecucion, no espera: quien termina antes, sigue
AVISO_APLAZADA = "Se calcula al abrir esta pestaña"
ROTULOS = [
    "Resumen", "Gráfico", "Precio y retornos", "Monte Carlo", "Riesgo VaR/CVaR",
    "Earnings", "Movimientos extremos", "Volumen", "Selección de valores",
    "Opciones y microestructura", "Comparativa", "Fundamentales", "DCF",
]
# Si aparecen, la funcion no ha llegado a ejecutarse aunque no haya excepcion.
AVISOS_DE_FALLO = ("No ha sido posible", "no responde", "No se pudo",
                   "no ha entregado", "Import ", "No module")

INTERNACIONALES = ["SAN.MC", "BBVA.MC", "ITX.MC", "IBE.MC", "SAP.DE", "SIE.DE",
                   "ASML.AS", "MC.PA", "AIR.PA", "NESN.SW", "7203.T", "0700.HK",
                   "SHOP.TO", "BHP.AX", "VOD.L", "HSBA.L"]
NO_EMPRESAS = ["SPY", "QQQ", "GLD", "^GSPC", "^IBEX", "EURUSD=X", "BTC-USD", "CL=F"]
COMPARATIVAS = ["SPY", "QQQ", "^GSPC", "^IBEX", "GLD", "EWP"]
NUMEROS_EN_LETRA = {
    "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8,
    "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14,
    "quince": 15, "dieciseis": 16, "dieciséis": 16, "diecisiete": 17,
    "dieciocho": 18, "diecinueve": 19, "veinte": 20,
}
# Solo si la fuente del S&P 500 no responde: el sorteo necesita algo de donde elegir.
RESERVA_SP500 = ["AAPL", "MSFT", "NVDA", "JPM", "XOM", "JNJ", "KO", "CAT", "NEE", "PLD"]

resultados = []


def bloque(titulo):
    print("\n" + "=" * 76)
    print("  " + titulo)
    print("=" * 76, flush=True)


def nuevo(ticker=None):
    at = AppTest.from_file(APP, default_timeout=PLAZO)
    if ticker:
        at.session_state["ticker"] = ticker
    return at


def correr(at, rotulo=None):
    # AppTest no recuerda la pestaña abierta entre ejecuciones (st.tabs no es un
    # widget que conozca): sin reabrirla, el control de una pestaña aplazada se
    # «prueba» sin que su codigo llegue a ejecutarse, y el paso sale verde.
    if rotulo:
        at.session_state["pestana_abierta"] = rotulo
    at.run()
    return at


def pestana(at, rotulo):
    return next((t for t in at.tabs if t.label == rotulo), None)


def paso(nombre, at, rotulo=None, extra_ok=True, detalle=""):
    exc = list(at.exception)
    errores = [str(e.value) for e in at.error]
    ok = (not exc) and extra_ok
    motivo = []
    if rotulo:
        tab = pestana(at, rotulo)
        if tab is None:
            ok = False
            motivo.append("pestaña no encontrada")
        elif any(AVISO_APLAZADA in c.value for c in tab.caption):
            ok = False
            motivo.append("SIGUE APLAZADA")
        else:
            errores = [str(e.value) for e in tab.error]
    if any(a in e for e in errores for a in AVISOS_DE_FALLO):
        ok = False
        motivo.append("aviso de fallo")
    resultados.append((nombre, ok))
    print(f"  [{'OK  ' if ok else 'FALLO'}] {nombre}"
          + (f" · {detalle}" if detalle else "")
          + (f" · {', '.join(motivo)}" if motivo else ""), flush=True)
    if not ok:
        for e in errores:
            print(f"           st.error: {e[:160]}")
        for e in exc:
            print(f"           EXCEPCION: {e.message}")
            print("           " + "\n           ".join(e.stack_trace[-6:]))
    return ok


def anotar(nombre, ok, detalle=""):
    """Para comprobaciones que no pasan por la app: motores y PDF."""
    resultados.append((nombre, ok))
    print(f"  [{'OK  ' if ok else 'FALLO'}] {nombre}" + (f" · {detalle}" if detalle else ""),
          flush=True)
    return ok


def seccion(nombre, funcion, *args):
    """Un paso que revienta no debe tapar el resultado de los demas."""
    try:
        funcion(*args)
    except Exception as exc:
        resultados.append((nombre, False))
        print(f"  [FALLO] {nombre} · la prueba revento: {exc!r}", flush=True)


def boton(at, etiqueta):
    return next(b for b in at.button if b.label == etiqueta)


# ---------------------------------------------------------------------------
#  Comprobaciones reutilizables
# ---------------------------------------------------------------------------

def comprobar_dcf(at, etiqueta):
    """Valorar, generar el Excel y afirmar que el rotulo cuenta sus hojas.

    Un hecho, una fuente: el numero de hojas que anuncia el boton de descarga
    tiene que ser el del fichero que se descarga. Ponia «catorce» fijo y el
    libro tenia dieciseis.
    """
    r = "DCF"
    correr(at, r)
    boton(at, "Valorar").click()
    correr(at, r)
    paso(f"{etiqueta} · DCF «Valorar»", at, rotulo=r,
         extra_ok=bool(at.session_state["dcf_lanzado"]))
    if not any(b.label == "Generar Excel completo" for b in at.button):
        # Sin valoracion no hay libro: lo normal en ETF, indices o divisas.
        paso(f"{etiqueta} · DCF sin valoración (no es una empresa)", at, rotulo=r)
        return
    boton(at, "Generar Excel completo").click()
    correr(at, r)
    claves = [k for k in at.session_state.filtered_state if str(k).startswith("dcf_xlsx_")]
    xlsx = at.session_state[claves[0]] if claves else None
    hojas = []
    if xlsx:
        import openpyxl
        hojas = openpyxl.load_workbook(io.BytesIO(xlsx), read_only=True).sheetnames
    tab = pestana(at, r)
    rotulo = next((d.label for d in tab.download_button), "")
    anunciadas = re.search(r"\((\d+) hojas", rotulo)
    anunciadas = int(anunciadas.group(1)) if anunciadas else None
    paso(f"{etiqueta} · DCF «Generar Excel completo»", at, rotulo=r,
         extra_ok=bool(xlsx) and xlsx[:2] == b"PK" and len(hojas) > 0,
         detalle=f"{len(hojas)} hojas, {len(xlsx or b'') / 1024:.0f} KB")
    paso(f"{etiqueta} · DCF el botón anuncia las hojas que tiene el libro", at,
         extra_ok=anunciadas == len(hojas),
         detalle=f"anuncia {anunciadas}, el libro tiene {len(hojas)}")
    # Y ningun otro texto de la pestaña puede contar otra cosa, ni en cifra ni
    # en letra: el fallo original era un «catorce» escrito a mano.
    patron = r"\b(\d+|" + "|".join(NUMEROS_EN_LETRA) + r")\s+hojas\b"
    contradicen = [m.group(0) for t in [*tab.caption, *tab.markdown]
                   for m in re.finditer(patron, t.value, re.IGNORECASE)
                   if (int(m.group(1)) if m.group(1).isdigit()
                       else NUMEROS_EN_LETRA[m.group(1).lower()]) != len(hojas)]
    paso(f"{etiqueta} · DCF ningún texto anuncia otro número de hojas", at,
         extra_ok=not contradicen,
         detalle=f"dicen {contradicen}" if contradicen else "")


def comprobar_informe(at, etiqueta):
    from pypdf import PdfReader
    r = "Resumen"
    t0 = time.time()
    correr(at, r)
    at.button(key="generar_informe").click()
    correr(at, r)
    guardado = at.session_state["informe_pdf"] if "informe_pdf" in at.session_state else {}
    pdf = (guardado or {}).get("datos")
    paginas = len(PdfReader(io.BytesIO(pdf)).pages) if pdf else 0
    paso(f"{etiqueta} · «Generar informe» (PDF)", at, rotulo=r,
         extra_ok=bool(pdf) and pdf[:4] == b"%PDF" and paginas > 0,
         detalle=f"{paginas} páginas, {len(pdf or b'') / 1_048_576:.1f} MB, "
                 f"{time.time() - t0:.0f}s")
    paso(f"{etiqueta} · el rótulo del PDF dice las páginas que tiene", at,
         extra_ok=bool(guardado) and guardado.get("paginas") == paginas,
         detalle=f"anuncia {(guardado or {}).get('paginas')}, el PDF tiene {paginas}")


AVISO_NO_POSITIVOS = "igual o inferior a cero"


def comprobar_cierres_no_positivos(simbolo="CL=F", periodo="10y"):
    """Un cierre <= 0 no tiene retorno logaritmico y el calculo lo descarta.

    CL=F cerro a -37,63 el 20/04/2020. Un hecho, una fuente: el diagnostico
    tiene que nombrar exactamente las sesiones que faltan en el historico, y la
    cabecera, la comparativa y el PDF tienen que decirlo con el mismo texto.
    """
    import re as _re

    import yfinance as yf
    from pypdf import PdfReader

    import informe_datos
    import motor_analisis as ma
    import motor_informe as mi

    hist = ma.descargar_historico(simbolo, periodo)
    diag = hist.attrs.get("cierres_no_positivos")
    bruto = yf.Ticker(simbolo).history(period=periodo, auto_adjust=True)
    # Las dos primeras filas las quitan siempre los dos dropna del original.
    faltan = sorted(set(bruto.index[2:].strftime("%d/%m/%Y"))
                    - set(hist.index.strftime("%d/%m/%Y")))
    anotar(f"{simbolo} {periodo} · el diagnóstico nombra las sesiones que faltan",
           bool(diag) and sorted(diag["descartadas"]) == faltan,
           detalle=f"faltan {faltan}, diagnóstico {diag and diag['descartadas']}")
    if not diag:
        return
    esperado = ma.texto_cierres_no_positivos(diag, simbolo)

    at = nuevo(simbolo)
    correr(at)
    at.sidebar.select_slider[0].set_value(periodo)
    correr(at)
    # Fuera de las pestañas: el aviso de la comparativa puede tener el MISMO
    # texto, y buscar en toda la pagina daba la cabecera por buena sin ella.
    en_pestanas = sum(w.value == esperado for t in at.tabs for w in t.warning)
    en_pagina = sum(w.value == esperado for w in at.warning)
    paso(f"{simbolo} {periodo} · la cabecera avisa con el texto del diagnóstico", at,
         extra_ok=en_pagina - en_pestanas >= 1,
         detalle=f"{en_pagina - en_pestanas} en cabecera, {en_pestanas} en pestañas")

    par = ma.descargar_par(simbolo, "SPY", ma.FECHA_INICIO_PERF)
    diag_par = ma.diagnostico_cierres(par[simbolo])
    tab = pestana(at, "Comparativa")
    paso(f"{simbolo} · la comparativa avisa de su propia serie", at, rotulo="Comparativa",
         extra_ok=bool(diag_par) and ma.texto_cierres_no_positivos(diag_par, simbolo)
         in [w.value for w in tab.warning])

    datos = informe_datos.recopilar(simbolo, periodo=periodo, incluir_seleccion=False,
                                    incluir_fundamentales=False)
    anotar(f"{simbolo} · el PDF lleva el aviso en sus incidencias",
           esperado in datos["incidencias"])
    pdf = mi.generar(simbolo, capital=100_000, datos=datos)
    impreso = " ".join(_re.sub(r"\s+", " ", p.extract_text() or "")
                       for p in PdfReader(io.BytesIO(pdf)).pages)
    # La entrada de la comparativa repite el texto tras «comparativa: »; sin
    # distinguirlas, el PDF pasaba aunque faltase la del historico.
    apariciones = _re.findall(r"(comparativa: )?" + _re.escape(_re.sub(r"\s+", " ", esperado)),
                              impreso)
    anotar(f"{simbolo} · el aviso del histórico sale impreso en el PDF",
           "" in apariciones,
           detalle=f"{len(apariciones)} apariciones, "
                   f"{sum(a == '' for a in apariciones)} del histórico")


# ---------------------------------------------------------------------------
#  Recorrido completo (determinista)
# ---------------------------------------------------------------------------

def recorrido_completo():
    t0 = time.time()
    at = nuevo()

    bloque("ARRANQUE Y LAS TRECE PESTAÑAS (ICHR)")
    correr(at)
    paso("Arranque con el ticker por defecto", at, extra_ok=len(at.title) > 0,
         detalle=at.title[0].value if at.title else "")
    paso("Sin cierres negativos no hay aviso de precios no positivos", at,
         extra_ok=not any(AVISO_NO_POSITIVOS in w.value for w in at.warning))
    for r in ROTULOS:
        ti = time.time()
        correr(at, r)
        paso(f"Pestaña «{r}»", at, rotulo=r, detalle=f"{time.time() - ti:.1f}s")

    bloque("CONTROLES DE CADA PESTAÑA")

    def monte_carlo():
        correr(at, "Monte Carlo")
        boton(at, "Volver a simular").click()
        correr(at, "Monte Carlo")
        paso("Monte Carlo · «Volver a simular»", at, rotulo="Monte Carlo",
             extra_ok=at.session_state["semilla"] == 1)

    def riesgo():
        correr(at, "Riesgo VaR/CVaR")
        at.number_input(key="capital_impacto").set_value(250_000)
        correr(at, "Riesgo VaR/CVaR")
        paso("Riesgo · cambiar capital del impacto", at, rotulo="Riesgo VaR/CVaR",
             extra_ok=at.number_input(key="capital_impacto").value == 250_000)

    def fundamentales():
        r = "Fundamentales"
        for estado in ["Balance", "Flujo de caja", "Cuenta de resultados"]:
            at.session_state["estado_fund"] = estado
            correr(at, r)
            paso(f"Fundamentales · estado «{estado}»", at, rotulo=r)
        at.session_state["periodo_fund"] = "Trimestral"
        correr(at, r)
        paso("Fundamentales · periodicidad trimestral", at, rotulo=r)
        at.session_state["periodo_fund"] = "Anual"
        at.session_state["estado_fund"] = "Balance"
        at.session_state["escala_balance"] = "Porcentaje"
        correr(at, r)
        paso("Fundamentales · balance en porcentaje", at, rotulo=r)

    def grafico():
        r = "Gráfico"
        correr(at, r)
        opciones = at.selectbox(key="graf_intervalo").options
        for i, opcion in enumerate(opciones):
            correr(at, r)
            at.selectbox(key="graf_intervalo").select_index(i)
            correr(at, r)
            n = len(pestana(at, r).get("plotly_chart"))
            paso(f"Gráfico · intervalo {opcion}", at, rotulo=r, extra_ok=n > 0,
                 detalle=f"{n} gráficos")
        for clave in ["graf_volumen", "graf_prepost"]:
            correr(at, r)
            at.toggle(key=clave).set_value(False)
            correr(at, r)
            paso(f"Gráfico · desactivar «{clave}»", at, rotulo=r)

    def microestructura():
        r = "Opciones y microestructura"
        correr(at, r)
        sm = at.selectbox(key="sesion_micro")
        if len(sm.options) > 1:
            sm.select_index(1)
        correr(at, r)
        paso("Microestructura · otra sesión", at, rotulo=r,
             detalle=f"{len(sm.options)} sesiones")

    def cribado():
        r = "Selección de valores"
        for clave in ["crib_fac_activo", "crib_ori_activo"]:
            ti = time.time()
            correr(at, r)
            at.toggle(key=clave).set_value(True)
            correr(at, r)
            paso(f"Cribado · activar «{clave}»", at, rotulo=r,
                 detalle=f"{time.time() - ti:.1f}s")

    def buscador():
        at.sidebar.text_input[0].input("santander")
        correr(at)
        radios = at.sidebar.radio
        n = len(radios[0].options) if radios else 0
        paso("Buscador · «santander»", at, extra_ok=n > 0, detalle=f"{n} resultados")
        if n:
            radios[0].set_value(radios[0].options[0])
            correr(at)
            paso("Buscador · elegir el primer resultado", at,
                 extra_ok=at.session_state["ticker"] != "ICHR",
                 detalle=f"ticker={at.session_state['ticker']}")

    for nombre, funcion in [("Monte Carlo", monte_carlo), ("Riesgo", riesgo),
                            ("Fundamentales", fundamentales), ("Gráfico", grafico),
                            ("Microestructura", microestructura), ("Cribado", cribado)]:
        seccion(nombre, funcion)
    seccion("DCF", comprobar_dcf, at, "ICHR")
    seccion("Informe PDF", comprobar_informe, at, "ICHR")
    seccion("Buscador", buscador)

    bloque("OTROS ACTIVOS: OTRA DIVISA Y OTRO MERCADO")

    def otro(simbolo):
        at2 = nuevo(simbolo)
        correr(at2)
        paso(f"{simbolo} · arranque", at2, extra_ok=len(at2.title) > 0,
             detalle=at2.title[0].value if at2.title else "")
        for r in ROTULOS:
            correr(at2, r)
            paso(f"{simbolo} · «{r}»", at2, rotulo=r)

    for simbolo in ["SAN.MC", "AAPL"]:
        seccion(simbolo, otro, simbolo)

    def inexistente():
        at3 = nuevo("ZZZZNOEXISTE")
        correr(at3)
        paso("Ticker inexistente · aviso controlado", at3,
             extra_ok=len(at3.error) > 0,
             detalle=str(at3.error[0].value)[:70] if at3.error else "")

    seccion("Ticker inexistente", inexistente)

    bloque("PRECIOS NO POSITIVOS: CL=F CERRÓ EN NEGATIVO EL 20/04/2020")
    seccion("Precios no positivos", comprobar_cierres_no_positivos)
    return time.time() - t0


# ---------------------------------------------------------------------------
#  Recorrido aleatorio
# ---------------------------------------------------------------------------

def sortear_activos(azar, n):
    import motor_cribado as crib
    universo = crib.universo_sp500()
    sp500 = list(universo["Ticker"]) if universo is not None else RESERVA_SP500
    if universo is None:
        print("  (la composicion del S&P 500 no ha respondido: sorteo sobre la reserva)")
    activos = []
    for _ in range(n):
        tipo = azar.choices(["sp500", "internacional", "no_empresa", "inexistente"],
                            weights=[50, 25, 15, 10])[0]
        if tipo == "sp500":
            simbolo = azar.choice(sp500)
        elif tipo == "internacional":
            simbolo = azar.choice(INTERNACIONALES)
        elif tipo == "no_empresa":
            simbolo = azar.choice(NO_EMPRESAS)
        else:
            simbolo = "ZZ" + "".join(azar.choices(string.ascii_uppercase, k=5))
        activos.append((tipo, simbolo))
    return activos


def recorrido_aleatorio(n, semilla):
    t0 = time.time()
    azar = random.Random(semilla)
    activos = sortear_activos(azar, n)
    informe_hecho = False

    for i, (tipo, simbolo) in enumerate(activos, 1):
        ajustes = {
            "periodo": azar.choice(["1y", "2y", "5y", "10y", "max"]),
            "confianza": round(azar.uniform(90.0, 99.9), 1),
            "capital": azar.randrange(100, 10_000_001),
            "comparar": azar.choice(COMPARATIVAS),
            "umbral": azar.choice([1.0, 1.5, 2.0, 2.5, 3.0]),
        }
        bloque(f"{i}/{n} · {simbolo} ({tipo}) · {ajustes}")
        etiqueta = f"{simbolo}"

        def un_activo():
            nonlocal informe_hecho
            at = nuevo(simbolo)
            correr(at)
            if tipo == "inexistente":
                paso(f"{etiqueta} · aviso controlado de ticker inexistente", at,
                     extra_ok=len(at.error) > 0 and not at.title,
                     detalle=str(at.error[0].value)[:70] if at.error else "")
                return
            if not paso(f"{etiqueta} · arranque", at, extra_ok=len(at.title) > 0,
                        detalle=at.title[0].value if at.title else ""):
                return

            barra = at.sidebar
            barra.select_slider[0].set_value(ajustes["periodo"])
            barra.slider[0].set_value(ajustes["confianza"])
            barra.number_input[0].set_value(ajustes["capital"])
            barra.text_input[2].input(ajustes["comparar"])
            barra.slider[1].set_value(ajustes["umbral"])
            correr(at)
            paso(f"{etiqueta} · ajustes de la barra lateral", at,
                 extra_ok=len(at.title) > 0)

            orden = ROTULOS[:]
            azar.shuffle(orden)
            for r in orden:
                ti = time.time()
                correr(at, r)
                paso(f"{etiqueta} · «{r}»", at, rotulo=r, detalle=f"{time.time() - ti:.1f}s")

            # Interacciones sorteadas: cada una con su probabilidad
            if azar.random() < 0.5:
                correr(at, "Monte Carlo")
                boton(at, "Volver a simular").click()
                correr(at, "Monte Carlo")
                paso(f"{etiqueta} · Monte Carlo «Volver a simular»", at, rotulo="Monte Carlo")
            if azar.random() < 0.5:
                at.session_state["estado_fund"] = azar.choice(
                    ["Cuenta de resultados", "Balance", "Flujo de caja"])
                at.session_state["periodo_fund"] = azar.choice(["Anual", "Trimestral"])
                correr(at, "Fundamentales")
                paso(f"{etiqueta} · Fundamentales {at.session_state['estado_fund']} "
                     f"{at.session_state['periodo_fund'].lower()}", at, rotulo="Fundamentales")
            if azar.random() < 0.5:
                correr(at, "Gráfico")
                sb = at.selectbox(key="graf_intervalo")
                k = azar.randrange(len(sb.options))
                sb.select_index(k)
                correr(at, "Gráfico")
                paso(f"{etiqueta} · Gráfico intervalo {sb.options[k]}", at, rotulo="Gráfico")
            if azar.random() < 0.5:
                comprobar_dcf(at, etiqueta)
            if not informe_hecho and tipo in ("sp500", "internacional"):
                informe_hecho = True
                comprobar_informe(at, etiqueta)

        seccion(etiqueta, un_activo)
    return time.time() - t0


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--aleatorio", type=int, metavar="N",
                   help="recorrer N activos y ajustes elegidos al azar")
    p.add_argument("--semilla", type=int,
                   help="semilla del sorteo, para reproducir una pasada")
    args = p.parse_args()

    if args.aleatorio:
        semilla = args.semilla if args.semilla is not None else random.SystemRandom().randrange(10**6)
        print(f"Semilla {semilla}  (repetir con: python verificar_app.py "
              f"--aleatorio {args.aleatorio} --semilla {semilla})")
        segundos = recorrido_aleatorio(args.aleatorio, semilla)
    else:
        segundos = recorrido_completo()

    fallos = [n for n, ok in resultados if not ok]
    bloque("RESULTADO")
    print(f"  Comprobaciones realizadas : {len(resultados)}")
    print(f"  Fallos                    : {len(fallos)}")
    print(f"  Duracion                  : {segundos:.0f}s")
    if fallos:
        for f in fallos:
            print(f"     - {f}")
        sys.exit(1)
    print("\n  TODO CORRECTO: la app responde sin errores en todo el recorrido.")


if __name__ == "__main__":
    main()
