"""PORTADA del informe: hoja de datos a tres columnas.

Reproduce la disposicion de una primera pagina de nota institucional: barra de
cabecera con la marca y la fecha, y debajo tres columnas.

    IZQUIERDA   denominacion, lectura del periodo, grafico y calendario
    CENTRO      rentabilidad por ventana, riesgo y eficiencia
    DERECHA     volatilidad, nivel, fundamentales, valoracion y episodios

Todo el contenido sale de los mismos motores que alimentan la pantalla. La
lectura del periodo se redacta a partir de las cifras ya calculadas y se limita
a describirlas: no valora, no anticipa y no recomienda.

Los paneles de datos se componen con `panel()`, que imita la tabla compacta de
una hoja de mercados: titulo en negrita con filete, cabecera de columnas en el
azul de la casa y filas separadas por filetes finisimos. No hay recuadros.
"""

from datetime import datetime

import numpy as np
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, Spacer, Table, TableStyle

import informe_base as ib

# Reparto de la hoja: la columna narrativa pesa el doble que cada una de datos
CALLE = 3.2 * mm
COL_IZQ = 71 * mm
COL_MED = (ib.ANCHO_UTIL - COL_IZQ - 2 * CALLE) / 2
COL_DER = COL_MED


def _estilos():
    b = getSampleStyleSheet()["Normal"]
    e = {}

    def crear(n, **kw):
        e[n] = ParagraphStyle(n, parent=b, **kw)

    crear("marca", fontName=ib.SERIF_N, fontSize=11.5, leading=14,
          textColor=ib.TINTA_CORPORATIVA)
    crear("division", fontName=ib.FUENTE_N, fontSize=7.2, leading=10,
          textColor=ib.TINTA_MEDIA)
    crear("fecha", fontName=ib.FUENTE, fontSize=7.8, leading=10,
          textColor=ib.TINTA_MEDIA, alignment=TA_RIGHT)

    crear("titulo", fontName=ib.SERIF_N, fontSize=17.5, leading=20.5,
          textColor=ib.TINTA_CORPORATIVA, spaceAfter=1)
    crear("subtitulo", fontName=ib.MONO, fontSize=8.6, leading=11,
          textColor=ib.TINTA_TENUE, spaceAfter=4)

    crear("epigrafe", fontName=ib.FUENTE_N, fontSize=8, leading=10.5,
          textColor=ib.TINTA, spaceBefore=2, spaceAfter=2)
    crear("cuerpo", fontName=ib.FUENTE, fontSize=6.9, leading=9.3,
          textColor=ib.TINTA_MEDIA, spaceAfter=3)
    crear("grafico_tit", fontName=ib.FUENTE_N, fontSize=8, leading=10.4,
          textColor=ib.CORPORATIVO, spaceAfter=0.5)
    crear("grafico_sub", fontName=ib.FUENTE, fontSize=6.6, leading=8.8,
          textColor=ib.TINTA_TENUE, spaceAfter=2)
    crear("fuente", fontName=ib.FUENTE, fontSize=5.9, leading=7.8,
          textColor=ib.TINTA_TENUE, spaceAfter=1)

    crear("p_titulo", fontName=ib.FUENTE_N, fontSize=7.4, leading=9.6,
          textColor=ib.TINTA)
    crear("p_supra", fontName=ib.FUENTE, fontSize=5.9, leading=7.6,
          textColor=ib.TINTA_TENUE, alignment=TA_CENTER)
    crear("p_cab", fontName=ib.FUENTE_N, fontSize=5.9, leading=7.6,
          textColor=ib.CORPORATIVO, alignment=TA_RIGHT)
    crear("p_cab_izq", fontName=ib.FUENTE_N, fontSize=5.9, leading=7.6,
          textColor=ib.CORPORATIVO, alignment=TA_LEFT)
    crear("p_eti", fontName=ib.FUENTE, fontSize=6.4, leading=8.4,
          textColor=ib.TINTA_MEDIA)
    crear("p_val", fontName=ib.MONO, fontSize=6.2, leading=8.4,
          textColor=ib.TINTA, alignment=TA_RIGHT)
    crear("nota", fontName=ib.FUENTE, fontSize=5.9, leading=7.8,
          textColor=ib.TINTA_TENUE)
    crear("firma", fontName=ib.SERIF_N, fontSize=13, leading=15,
          textColor=ib.TINTA_CORPORATIVA, alignment=TA_RIGHT)
    crear("firma_sub", fontName=ib.FUENTE, fontSize=6.6, leading=9,
          textColor=ib.TINTA_MEDIA, alignment=TA_RIGHT)
    return e


E = _estilos()


# =============================================================================
#  PANEL DE DATOS
# =============================================================================

def panel(titulo, filas, cabecera=None, supra=None, anchos=None,
          ancho=COL_MED):
    """Tabla compacta de hoja de mercados.

    `filas` es una lista cuyo primer elemento es la etiqueta y el resto cifras.
    `supra` rotula un grupo de columnas, como el "% variacion" que agrupa las
    columnas de rentabilidad en una nota de mercados.
    """
    if not filas:
        return None
    ncol = max(len(f) for f in filas)
    if anchos:
        total = float(sum(anchos))
        cols = [ancho * (a / total) for a in anchos]
    else:
        primera = ancho * (0.46 if ncol > 2 else 0.62)
        resto = (ancho - primera) / max(ncol - 1, 1)
        cols = [primera] + [resto] * (ncol - 1)

    cuerpo, ordenes = [], []
    fila_actual = 0

    # --- titulo
    cuerpo.append([Paragraph(ib.esc(titulo), E["p_titulo"])] + [""] * (ncol - 1))
    ordenes += [("SPAN", (0, 0), (-1, 0)),
                ("LINEBELOW", (0, 0), (-1, 0), 0.7, ib.CORPORATIVO),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 2.2)]
    fila_actual += 1

    # --- rotulo que agrupa columnas
    if supra:
        etiqueta, desde = supra
        linea = [""] * ncol
        linea[desde] = Paragraph(ib.esc(etiqueta), E["p_supra"])
        cuerpo.append(linea)
        ordenes += [("SPAN", (desde, fila_actual), (-1, fila_actual)),
                    ("LINEBELOW", (desde, fila_actual), (-1, fila_actual),
                     0.25, ib.FILETE),
                    ("TOPPADDING", (0, fila_actual), (-1, fila_actual), 1.5),
                    ("BOTTOMPADDING", (0, fila_actual), (-1, fila_actual), 0.5)]
        fila_actual += 1

    # --- cabecera de columnas
    if cabecera:
        cuerpo.append([Paragraph(ib.esc(c), E["p_cab_izq"] if i == 0
                                 else E["p_cab"])
                       for i, c in enumerate(cabecera)])
        ordenes += [("LINEBELOW", (0, fila_actual), (-1, fila_actual), 0.4,
                     ib.CORPORATIVO),
                    ("TOPPADDING", (0, fila_actual), (-1, fila_actual), 1),
                    ("BOTTOMPADDING", (0, fila_actual), (-1, fila_actual), 1.6)]
        fila_actual += 1

    # --- datos
    for fila in filas:
        linea = [Paragraph(ib.esc(fila[0]), E["p_eti"])]
        for celda in list(fila[1:]) + [""] * (ncol - len(fila)):
            linea.append(Paragraph(ib.esc(celda), E["p_val"]))
        cuerpo.append(linea)
    ordenes += [("LINEBELOW", (0, fila_actual), (-1, -2), 0.2, ib.FILETE_FINO),
                ("LINEBELOW", (0, -1), (-1, -1), 0.4, ib.FILETE)]

    t = Table(cuerpo, colWidths=cols)
    t.setStyle(TableStyle(ordenes + [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0.6),
        ("TOPPADDING", (0, fila_actual), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, fila_actual), (-1, -1), 1.5)]))
    return t


def _columna(piezas, ancho):
    """Apila los paneles de una columna dejando aire entre ellos."""
    utiles = []
    for pieza in piezas:
        if pieza is None:
            continue
        utiles.append(pieza)
        utiles.append(Spacer(1, 4.5))
    if utiles:
        utiles.pop()
    t = Table([[u] for u in utiles], colWidths=[ancho])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    return t


# =============================================================================
#  CALCULOS PROPIOS DE LA PORTADA
# =============================================================================

VENTANAS = [("1 sesión", 1), ("1 semana", 5), ("1 mes", 21),
            ("3 meses", 63), ("6 meses", 126), ("12 meses", 252)]


def _retorno(serie, sesiones):
    if serie is None or len(serie) <= sesiones:
        return np.nan
    base = float(serie.iloc[-1 - sesiones])
    return float(serie.iloc[-1]) / base - 1 if base else np.nan


def _ytd(serie):
    """Retorno desde el primer cierre del anio en curso.

    El corte se construye con la MISMA zona horaria que el indice. Las series
    de la aplicacion llegan por dos caminos: yf.Ticker.history entrega el
    indice con la zona de Nueva York y yf.download lo entrega sin ella, de modo
    que comparar contra una fecha suelta lanza TypeError en una y funciona en
    la otra.
    """
    if serie is None or len(serie) == 0:
        return np.nan
    indice = pd.DatetimeIndex(serie.index)
    corte = pd.Timestamp(f"{indice[-1].year}-01-01")
    if indice.tz is not None:
        corte = corte.tz_localize(indice.tz)
    tramo = serie[indice >= corte]
    if len(tramo) < 2:
        return np.nan
    return float(serie.iloc[-1]) / float(tramo.iloc[0]) - 1


def rentabilidad(hist, comparativa=None):
    """Retorno del valor por ventana, con la referencia al lado si la hay."""
    c = hist["Close"]
    indice = None
    if comparativa and comparativa.get("stats_b") is not None:
        curva = comparativa["stats_b"].get("Equity_Curve")
        if curva is not None and len(curva):
            indice = curva

    filas = []
    for etiqueta, k in VENTANAS:
        r = _retorno(c, k)
        ri = _retorno(indice, k) if indice is not None else np.nan
        filas.append([etiqueta, ib.pct(r, 1), ib.pct(ri, 1)])
    filas.append(["En el año", ib.pct(_ytd(c), 1), ib.pct(_ytd(indice), 1)])
    return filas


def volatilidad(hist, mercado):
    """Volatilidad realizada por ventana y la implicita en opciones."""
    lr = hist["LogReturn"].dropna()
    filas = []
    for etiqueta, k in (("21 sesiones", 21), ("63 sesiones", 63),
                        ("252 sesiones", 252)):
        v = (float(lr.iloc[-k:].std() * np.sqrt(252))
             if len(lr) >= k else np.nan)
        filas.append([etiqueta, ib.pct(v, 1, False)])
    mov = (mercado or {}).get("movimiento") or {}
    if mov.get("liquidez_ok"):
        filas.append(["Implícita ATM", ib.pct(mov.get("iv_atm"), 1, False)])
        filas.append(["Mov. descontado",
                      ib.pct(mov.get("movimiento_implicito"), 1, False)])
    elif mov:
        filas.append(["Implícita ATM", "—"])
        filas.append(["Mov. descontado", "—"])
    return filas


def _num_de(tabla, clave, columna_clave=None, columna_valor=None):
    """Busca una fila por su etiqueta en una tabla de dos columnas."""
    if tabla is None or not isinstance(tabla, pd.DataFrame) or tabla.empty:
        return None
    cc = columna_clave or tabla.columns[0]
    cv = columna_valor or tabla.columns[1]
    coincide = tabla[tabla[cc].astype(str).str.lower()
                     .str.contains(clave.lower(), na=False)]
    if coincide.empty:
        return None
    try:
        return float(coincide[cv].iloc[0])
    except (TypeError, ValueError):
        return None


def valoracion(fundamentales):
    """Multiplos de valoracion, con el formato que declara el propio motor."""
    f = fundamentales or {}
    mu = f.get("multiplos")
    if not isinstance(mu, dict) or not isinstance(mu.get("tabla"), pd.DataFrame):
        return None
    tabla = mu["tabla"]
    quiero = ["PER", "EV / Ventas", "EV / EBITDA", "EV / FCF",
              "Precio / Valor contable"]
    filas = []
    for nombre in quiero:
        fila = tabla[tabla["Multiplo"].astype(str) == nombre]
        if fila.empty:
            continue
        valor = fila["Valor"].iloc[0]
        try:
            valor = float(valor)
        except (TypeError, ValueError):
            continue
        if not np.isfinite(valor):
            continue
        etiqueta = nombre.replace("Precio / Valor contable", "P / Valor cont.")
        filas.append([etiqueta, f"{valor:,.1f} ×".replace(",", " ")])
    if mu.get("capitalizacion"):
        filas.insert(0, ["Capitalización", ib.compacto(mu["capitalizacion"], 1)])
    if mu.get("ev"):
        filas.insert(1, ["Valor de empresa", ib.compacto(mu["ev"], 1)])
    return filas or None


def solidez(fundamentales):
    """Marcadores de calidad, solvencia y retorno del capital."""
    f = fundamentales or {}
    filas = []
    p = f.get("piotroski")
    if p:
        filas.append(["Piotroski F-Score",
                      f"{ib.num(p.get('puntuacion'), 0)} / "
                      f"{ib.num(p.get('maximo'), 0)}"])
    a = f.get("altman")
    if a:
        filas.append(["Altman Z-Score", ib.num(a.get("z"), 2)])
    b = f.get("beneish")
    if b:
        filas.append(["Beneish M-Score", ib.num(b.get("m"), 2)])
    r = f.get("ratios")
    if isinstance(r, dict):
        if r.get("roic_actual") is not None:
            filas.append(["ROIC último ejercicio",
                          ib.pct(r.get("roic_actual"), 1, False)])
        if r.get("roic_medio") is not None:
            filas.append(["ROIC medio", ib.pct(r.get("roic_medio"), 1, False)])
    s = f.get("solvencia")
    if isinstance(s, dict) and s.get("deuda_neta") is not None:
        filas.append(["Deuda neta", ib.compacto(s.get("deuda_neta"), 1)])
    return filas or None


def episodios(seleccion):
    """Sintesis del contraste sobre episodios extremos."""
    s = seleccion or {}
    if not s:
        return None
    filas = [
        ["Umbral aplicado", f"{s.get('umbral', 0):.1f} σ"],
        ["Episodios comparables", ib.num(s.get("casos"), 0)],
        ["Rebote medio", ib.pct(s.get("media"), 1)],
        ["Episodios al alza", ib.pct(s.get("positivos"), 0, False)],
        ["Referencia del índice", ib.pct(s.get("referencia"), 1)],
        ["Ventaja sobre el índice", ib.pct(s.get("ventaja"), 1)],
    ]
    c = s.get("contraste") or {}
    if c.get("q") is not None:
        filas.append(["Valor q corregido", ib.num(c.get("q"), 3)])
    return filas


def calendario(datos):
    """Proximos hitos conocidos: resultados y vencimientos de opciones."""
    filas = []
    ev = (datos.get("earnings") or {}).get("proximos") or []
    for f in list(ev)[:2]:
        try:
            fecha = pd.Timestamp(f).tz_localize(None) if pd.Timestamp(f).tzinfo \
                else pd.Timestamp(f)
            filas.append([fecha.strftime("%d/%m/%Y"), "Publicación de resultados",
                          "Trimestral"])
        except Exception:
            continue
    venc = ((datos.get("mercado") or {}).get("cadena") or {}).get("vencimientos") or []
    for v in list(venc)[:3]:
        try:
            filas.append([pd.Timestamp(v).strftime("%d/%m/%Y"),
                          "Vencimiento de opciones", "Cadena"])
        except Exception:
            continue
    return filas or None


# =============================================================================
#  LECTURA DEL PERIODO
# =============================================================================

def lectura(d):
    """Sintesis en prosa de las cifras ya calculadas. Describe, no valora."""
    s = d.get("situacion") or {}
    r = d.get("rendimiento") or {}
    g = d.get("riesgo") or {}
    rev = d.get("reversion") or {}
    hist = d["hist"]
    divisa = d["divisa"]
    frases = []

    if s.get("precio") is not None:
        frases.append(
            f"El valor cerró la última sesión en "
            f"{ib.moneda(s.get('precio'), divisa)}, con una variación de "
            f"{ib.pct(s.get('mov_dia'))} equivalente a "
            f"{ib.num(s.get('sigmas_dia'), 2)} desviaciones típicas de su "
            f"distribución diaria.")
    if s.get("pos_rango") is not None and np.isfinite(s.get("pos_rango", np.nan)):
        frases.append(
            f"Cotiza en el percentil {ib.num(s.get('pos_rango'), 0)} de su rango "
            f"de las últimas 52 semanas, a {ib.pct(s.get('desde_maximo'))} de su "
            f"máximo.")
    if r:
        frases.append(
            f"En el periodo analizado acumula un retorno anualizado de "
            f"{ib.pct(r.get('Retorno Anualizado'))} con una volatilidad de "
            f"{ib.pct(r.get('Volatilidad Anual'), 1, False)}, lo que sitúa el "
            f"ratio de Sharpe en {ib.num(r.get('Sharpe Ratio'), 2)} y la máxima "
            f"caída desde máximos en {ib.pct(r.get('Max Drawdown'))}.")
    if g:
        frases.append(
            f"La pérdida diaria en el umbral del "
            f"{d.get('confianza', 99):.1f} % de confianza asciende a "
            f"{ib.pct(g.get('var_hist'))} por el método histórico; más allá de "
            f"ese umbral la pérdida media observada es de "
            f"{ib.pct(g.get('cvar'))}.")
    if rev and rev.get("diferencia_media") is not None:
        # `x or 0` NO neutraliza un NaN: en Python NaN es verdadero, de modo
        # que el giro lo deja pasar y la comparacion posterior da False,
        # afirmando "por debajo de" cuando en realidad no hay dato.
        dif = rev.get("diferencia_media")
        dif = float(dif) if dif is not None and np.isfinite(dif) else None
        signo = "por encima de" if (dif or 0) > 0 else "por debajo de"
        frases.append(
            f"Tras los {ib.num(rev.get('n_caidas'), 0)} episodios en que el "
            f"retorno diario cayó más de {d.get('umbral_sigmas', 2):.1f} "
            f"desviaciones típicas, el retorno acumulado posterior se situó de "
            f"media {ib.pct(rev.get('diferencia_media'))} {signo} el de una "
            f"sesión cualquiera del mismo periodo.")
    frases.append(
        f"El análisis descansa en {len(hist):,} sesiones desde "
        f"{hist.index[0]:%d/%m/%Y} y describe exclusivamente comportamiento "
        f"pasado.".replace(",", " "))
    return " ".join(frases)


# =============================================================================
#  COMPOSICION
# =============================================================================

def _cabecera(d):
    """Barra superior: distintivo, marca y fecha del informe."""
    marca = Table(
        [[Paragraph("&#9654;", ParagraphStyle(
            "chev", fontName=ib.FUENTE_N, fontSize=11,
            textColor=ib.CORPORATIVO)),
          Paragraph(f"{ib.esc(ib.ENTIDAD)}", E["marca"]),
          Paragraph("EQUITY &amp; CREDIT RESEARCH", E["division"]),
          Paragraph(ib.fecha_larga(datetime.now()), E["fecha"])]],
        colWidths=[6 * mm, 42 * mm, 62 * mm, ib.ANCHO_UTIL - 110 * mm])
    marca.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING", (1, 0), (1, 0), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -1), 1.1, ib.TINTA_CORPORATIVA)]))
    return marca


def _grafico_izquierda(d, motor):
    """Grafico de la columna narrativa, al ancho de la columna."""
    hist = d["hist"]
    fig, ax = ib.lienzo(2.78, 1.5)
    ax.plot(hist.index, hist["Close"], color=ib.MPL_CORP, linewidth=0.75)
    ax.fill_between(hist.index, hist["Close"].min(), hist["Close"],
                    color=ib.MPL_CORP, alpha=0.07)
    media = hist["Close"].rolling(200, min_periods=50).mean()
    ax.plot(hist.index, media, color=ib.MPL_AMBAR, linewidth=0.7,
            label="Media de 200 sesiones")
    ax.set_ylabel(f"Precio ({d['divisa']})")
    ib.leyenda(ax, fontsize=5.2, loc="upper left")
    ax.set_title("")
    fig.tight_layout(pad=0.15)
    return ib.figura(fig, ancho_mm=COL_IZQ / mm)


def _grafico_distribucion(d):
    """Histograma compacto de los retornos diarios, al ancho de la columna."""
    r = d["hist"]["Return"].dropna()
    fig, ax = ib.lienzo(2.78, 1.15)
    ax.hist(r, bins=60, color=ib.MPL_CORP, alpha=0.75, edgecolor="white",
            linewidth=0.18)
    ax.axvline(float(r.mean()), color=ib.MPL_ROJO, linestyle="--",
               linewidth=0.8, label=f"Media {r.mean():+.2%}")
    ax.set_xlabel("Retorno diario")
    ax.set_ylabel("Sesiones")
    ib.leyenda(ax, fontsize=5.2)
    ax.set_title("")
    fig.tight_layout(pad=0.15)
    return ib.figura(fig, ancho_mm=COL_IZQ / mm)


def construir(d, motor):
    """Devuelve los elementos de la primera pagina."""
    tk, nombre, divisa = d["ticker"], d["nombre"], d["divisa"]
    s = d.get("situacion") or {}

    piezas = [_cabecera(d), Spacer(1, 7)]

    # ---------------------------------------------------------- izquierda
    largo = len(str(nombre))
    estilo_titulo = ParagraphStyle(
        "t_ajustado", parent=E["titulo"],
        fontSize=17.5 if largo <= 24 else (14.5 if largo <= 34 else 12),
        leading=(17.5 if largo <= 24 else (14.5 if largo <= 34 else 12)) * 1.18)

    izquierda = [
        Paragraph(ib.esc(nombre), estilo_titulo),
        Paragraph(f"{ib.esc(tk)} &nbsp;·&nbsp; {ib.esc(divisa)} &nbsp;·&nbsp; "
                  f"cierre de {s.get('fecha', '—')}", E["subtitulo"]),
        Paragraph("Lectura del periodo", E["epigrafe"]),
        Paragraph(ib.esc(lectura(d)), E["cuerpo"]),
        Paragraph("Evolución del precio frente a su media de largo plazo",
                  E["grafico_tit"]),
        Paragraph(f"Cierre ajustado · {len(d['hist']):,} sesiones"
                  .replace(",", " "), E["grafico_sub"]),
        _grafico_izquierda(d, motor),
        Paragraph(
            f"Cierre ajustado a {ib.fecha_larga(d['hist'].index[-1])}. "
            f"Relación de fuentes en el apartado 14.", E["fuente"]),
        Spacer(1, 3),
        Paragraph("Distribución de los retornos diarios", E["grafico_tit"]),
        Paragraph("Frecuencia por tramo, con la media señalada",
                  E["grafico_sub"]),
        _grafico_distribucion(d),
        Spacer(1, 3),
    ]
    cal = calendario(d)
    if cal:
        izquierda.append(panel("Próximos hitos", cal,
                               cabecera=["Fecha", "Hito", "Tipo"],
                               anchos=[1.05, 2.1, 0.95], ancho=COL_IZQ))
    col_izq = _columna(izquierda, COL_IZQ)

    # ------------------------------------------------------------- centro
    r = d.get("rendimiento") or {}
    g = d.get("riesgo") or {}
    ref = d.get("referencia", "índice")
    centro = [
        Paragraph("Estadísticas del valor", E["epigrafe"]),
        panel("Rentabilidad", rentabilidad(d["hist"], d.get("comparativa")),
              cabecera=["", "Valor", ref], supra=("% variación", 1),
              anchos=[1.25, 0.9, 0.9], ancho=COL_MED),
        panel("Riesgo diario", [
            [f"VaR histórico {d['confianza']:.0f} %", ib.pct(g.get("var_hist"), 2)],
            [f"VaR paramétrico {d['confianza']:.0f} %",
             ib.pct(g.get("var_param"), 2)],
            [f"CVaR {d['confianza']:.0f} %", ib.pct(g.get("cvar"), 2)],
            ["Sigma diaria", ib.pct(s.get("sigma_dia"), 2, False)],
        ], cabecera=["", "Nivel"], ancho=COL_MED),
        panel("Eficiencia", [
            ["Retorno anualizado", ib.pct(r.get("Retorno Anualizado"), 1)],
            ["Volatilidad del periodo", ib.pct(r.get("Volatilidad Anual"), 1, False)],
            ["Ratio de Sharpe", ib.num(r.get("Sharpe Ratio"), 2)],
            ["Ratio de Sortino", ib.num(r.get("Sortino Ratio"), 2)],
            ["Ratio de Calmar", ib.num(r.get("Ratio de Calmar"), 2)],
            ["Máxima caída", ib.pct(r.get("Max Drawdown"), 1)],
        ], cabecera=["", "Nivel"], ancho=COL_MED),
    ]
    ear = d.get("earnings") or {}
    if ear.get("eventos"):
        centro.append(panel("Reacción a resultados", [
            ["Publicaciones analizadas", ib.num(len(ear["eventos"]), 0)],
            ["Movimiento medio", ib.pct(ear.get("mov_medio_earnings"), 1, False)],
            ["Sesión normal", ib.pct(ear.get("mov_medio_normal"), 1, False)],
            ["Movimientos extremos", ib.num(ear.get("n_extremos"), 0)],
            ["Tasa de reversión", ib.pct(ear.get("tasa_reversion"), 0, False)],
        ], cabecera=["", "Nivel"], ancho=COL_MED))

    comp = d.get("comparativa")
    if comp:
        centro.append(panel(f"Relación con {ref}", [
            ["Correlación de retornos", ib.num(comp.get("correlacion"), 2)],
            ["Beta", ib.num(comp.get("beta"), 2)],
            ["Sesiones comunes", ib.num(comp.get("sesiones"), 0)],
        ], cabecera=["", "Nivel"], ancho=COL_MED))
    col_med = _columna(centro, COL_MED)

    # ------------------------------------------------------------ derecha
    derecha = [
        Paragraph("Riesgo, valoración y calidad", E["epigrafe"]),
        panel("Volatilidad", volatilidad(d["hist"], d.get("mercado")),
              cabecera=["", "Anualizada"], ancho=COL_DER),
        panel("Nivel y rango", [
            ["Último cierre", ib.moneda(s.get("precio"), divisa)],
            ["Máximo de 52 semanas", ib.num(s.get("max_52s"), 2)],
            ["Mínimo de 52 semanas", ib.num(s.get("min_52s"), 2)],
            ["Posición en el rango", ib.num(s.get("pos_rango"), 0, " %")],
            ["Desde máximos", ib.pct(s.get("desde_maximo"), 1)],
        ], cabecera=["", "Nivel"], ancho=COL_DER),
    ]
    val = valoracion(d.get("fundamentales"))
    if val:
        derecha.append(panel("Valoración", val, cabecera=["", "Múltiplo"],
                             ancho=COL_DER))
    sol = solidez(d.get("fundamentales"))
    if sol:
        derecha.append(panel("Calidad y solvencia", sol,
                             cabecera=["", "Nivel"], ancho=COL_DER))
    epi = episodios(d.get("seleccion"))
    if epi:
        derecha.append(panel("Episodios extremos", epi,
                             cabecera=["", "Nivel"], ancho=COL_DER))
    vol = d.get("volumen") or {}
    if vol:
        derecha.append(panel("Actividad de negociación", [
            ["Volumen medio", ib.compacto(vol.get("vol_medio"), 1)],
            ["Última sesión", ib.compacto(vol.get("volumen_hoy"), 1)],
            ["Relativo a su media",
             f"{ib.num(vol.get('vol_relativo_hoy'), 2)} ×"],
            ["En subidas", f"{ib.num(vol.get('vol_rel_subidas'), 2)} ×"],
            ["En bajadas", f"{ib.num(vol.get('vol_rel_bajadas'), 2)} ×"],
            ["Correlación con el movimiento", ib.num(vol.get("correlacion"), 2)],
        ], cabecera=["", "Nivel"], ancho=COL_DER))
    col_der = _columna(derecha, COL_DER)

    # ------------------------------------------------------------- rejilla
    rejilla = Table([[col_izq, col_med, col_der]],
                    colWidths=[COL_IZQ + CALLE / 2,
                               COL_MED + CALLE, COL_DER + CALLE / 2])
    rejilla.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), CALLE / 2),
        ("LEFTPADDING", (1, 0), (1, 0), CALLE / 2),
        ("RIGHTPADDING", (1, 0), (1, 0), CALLE / 2),
        ("LEFTPADDING", (2, 0), (2, 0), CALLE / 2),
        ("RIGHTPADDING", (2, 0), (2, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LINEAFTER", (0, 0), (0, 0), 0.35, ib.FILETE),
        ("LINEAFTER", (1, 0), (1, 0), 0.35, ib.FILETE)]))
    piezas.append(rejilla)

    # --------------------------------------------------------------- firma
    piezas.append(Spacer(1, 8))
    pie = Table(
        [[Paragraph(
            "Nota: todas las magnitudes se calculan sobre datos históricos de "
            "fuentes públicas y describen el comportamiento pasado del activo. "
            "No constituyen previsión, asesoramiento financiero ni "
            "recomendación de inversión. La rentabilidad por ventana se expresa "
            "en divisa local y sin ajustar por dividendos distintos de los ya "
            "incorporados al cierre ajustado. Aviso legal íntegro en el "
            "apartado 14.", E["nota"]),
          Table([[Paragraph(ib.esc(ib.ENTIDAD), E["firma"])],
                 [Paragraph("EQUITY &amp; CREDIT RESEARCH", E["firma_sub"])]],
                colWidths=[58 * mm], style=TableStyle([
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 0),
                    ("LINEABOVE", (0, 0), (-1, 0), 1.1, ib.TINTA_CORPORATIVA),
                    ("TOPPADDING", (0, 0), (-1, 0), 3)]))]],
        colWidths=[ib.ANCHO_UTIL - 62 * mm, 62 * mm])
    pie.setStyle(TableStyle([
        ("VALIGN", (0, 0), (0, 0), "BOTTOM"),
        ("VALIGN", (1, 0), (1, 0), "BOTTOM"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    piezas.append(pie)
    return piezas
