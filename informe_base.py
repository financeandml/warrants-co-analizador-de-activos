"""Sistema visual del INFORME EN PDF. Formato A4 de folio imprimible.

Aqui viven la pagina, las fuentes, la paleta y los componentes de maquetacion;
el contenido de cada apartado vive en motor_informe.py.

CRITERIO DE DISENO
------------------
Informe institucional de renta variable, del tipo que una casa de analisis
entrega a un cliente profesional. Eso impone tres reglas que conviene enunciar
porque explican casi todas las decisiones de este fichero:

  1. NADA DE RECUADROS. Los datos no se meten en cajas. Se ordenan en fichas de
     etiqueta y valor separadas por filetes finos, que es como se compone un
     informe de analisis y no un panel de control. Un recuadro por cifra
     fragmenta la pagina y la vuelve ilegible en papel.

  2. TINTA AL SERVICIO DEL DATO. Filetes de un cuarto de punto, sin fondos
     alternos, sin marcos exteriores, sin sombras. El unico color fuerte es el
     azul corporativo de los encabezados; el verde y el rojo se reservan para
     el signo de una cifra y no se usan decorativamente.

  3. DENSIDAD. Un informe profesional aprovecha la hoja. Cuerpo de 8,4 puntos,
     interlineado ajustado y dos columnas donde el contenido lo permite.

Pagina A4 vertical con margenes de 16 mm, que deja 178 mm utiles. Las fuentes
son las DejaVu que acompanan a matplotlib: las Helvetica de serie de reportlab
solo cubren Latin-1 y el informe esta lleno de caracteres que no estan ahi -la
sigma de los umbrales, el simbolo de mayor o igual, las flechas- que saldrian
como cuadrados negros en mitad de una tabla.
"""

import io
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Titulos de grafico alineados a la izquierda, como en un informe
# impreso. Se fija aqui porque el objeto Text no admite "loc".
matplotlib.rcParams["axes.titlelocation"] = "left"
matplotlib.rcParams["axes.titlepad"] = 4.0
matplotlib.rcParams["font.family"] = "DejaVu Sans"
# Los tamanos se fijan aqui y no en lienzo(): set_title y set_xlabel vuelven
# a aplicar el valor por defecto cada vez que se llaman, de modo que ajustar
# el objeto Text antes de escribir el titulo no sirve de nada.
matplotlib.rcParams["axes.titlesize"] = 7.8
matplotlib.rcParams["axes.titleweight"] = "bold"
matplotlib.rcParams["axes.titlecolor"] = "#16324F"
matplotlib.rcParams["axes.labelsize"] = 6.8
matplotlib.rcParams["axes.labelcolor"] = "#41474E"
matplotlib.rcParams["xtick.labelsize"] = 6.4
matplotlib.rcParams["ytick.labelsize"] = 6.4
matplotlib.rcParams["legend.fontsize"] = 6.2
matplotlib.rcParams["axes.formatter.useoffset"] = False
import numpy as np
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (CondPageBreak, Image, KeepTogether, LongTable,
                                PageBreak, Paragraph, Spacer, Table, TableStyle)

# --------------------------------------------------------------------- Pagina
PAGINA = A4
MARGEN = 16 * mm
MARGEN_SUP = 20 * mm
MARGEN_INF = 18 * mm
ANCHO_UTIL = PAGINA[0] - 2 * MARGEN                      # 178 mm
ALTO_UTIL = PAGINA[1] - MARGEN_SUP - MARGEN_INF          # 259 mm
COLUMNA = (ANCHO_UTIL - 6 * mm) / 2                      # dos columnas con calle

# --------------------------------------------------------------------- Paleta
# Identidad de la casa. Se toma del portal para que el papel y la web digan
# lo mismo; si el portal no esta disponible se emplean los mismos literales.
ENTIDAD = "Warrants & Co."
ENTIDAD_LARGA = "Warrants & Co. — Equity & Credit Research"
LEMA = "Análisis independiente para inversores institucionales"
CONTACTO = "research@warrantsandco.com"

# El documento se compone en tinta negra. El color queda reservado a los
# graficos, donde distingue series, y al signo de una cifra. Un titular azul
# sobre papel no aporta jerarquia: la aporta el cuerpo y el filete.
TINTA_CORPORATIVA = colors.HexColor("#0A0A0A")   # negro del cabecero
CORPORATIVO = colors.HexColor("#111111")         # negro de encabezados y filetes
CORPORATIVO_CLARO = colors.HexColor("#4A4A4A")
TINTA = colors.HexColor("#1A1D21")
TINTA_MEDIA = colors.HexColor("#41474E")
TINTA_TENUE = colors.HexColor("#6B7280")
FILETE = colors.HexColor("#C9CDD2")
FILETE_FINO = colors.HexColor("#E3E5E8")
PAPEL_SUAVE = colors.HexColor("#F5F6F7")
POSITIVO = colors.HexColor("#1E7B45")
NEGATIVO = colors.HexColor("#A62A21")

# Equivalentes para matplotlib
MPL_CORP = "#16324F"
MPL_CORP_CLARO = "#41627F"
MPL_VERDE = "#1E7B45"
MPL_ROJO = "#A62A21"
MPL_GRIS = "#8A9099"
MPL_GRIS_CLARO = "#C9CDD2"
MPL_AMBAR = "#B9770E"
MPL_MORADO = "#5B4B8A"
MPL_SERIE = ["#16324F", "#B9770E", "#1E7B45", "#A62A21", "#5B4B8A", "#41627F"]


# ------------------------------------------------------------------- Tipografia
def _registrar_fuentes():
    base = os.path.join(os.path.dirname(matplotlib.__file__),
                        "mpl-data", "fonts", "ttf")
    # Times New Roman para las cifras destacadas, tal y como se pide. Se toma
    # de las fuentes del sistema; si no estuviera, se cae a la serif de
    # matplotlib, que es la que acompana al resto del documento.
    windows = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    for alias, fichero in (("Times", "times.ttf"), ("Times-Bold", "timesbd.ttf")):
        ruta = os.path.join(windows, fichero)
        if os.path.exists(ruta):
            try:
                pdfmetrics.registerFont(TTFont(alias, ruta))
            except Exception:
                pass

    piezas = {"Inf": "DejaVuSans.ttf",
              "Inf-Bold": "DejaVuSans-Bold.ttf",
              "Inf-Italic": "DejaVuSans-Oblique.ttf",
              "InfSerif": "DejaVuSerif.ttf",
              "InfSerif-Bold": "DejaVuSerif-Bold.ttf",
              "InfMono": "DejaVuSansMono.ttf",
              "InfMono-Bold": "DejaVuSansMono-Bold.ttf"}
    try:
        for alias, fichero in piezas.items():
            ruta = os.path.join(base, fichero)
            if not os.path.exists(ruta):
                raise FileNotFoundError(ruta)
            pdfmetrics.registerFont(TTFont(alias, ruta))
        for familia, normal, negrita in (("Inf", "Inf", "Inf-Bold"),
                                         ("InfSerif", "InfSerif", "InfSerif-Bold"),
                                         ("InfMono", "InfMono", "InfMono-Bold")):
            pdfmetrics.registerFontFamily(familia, normal=normal, bold=negrita,
                                          italic="Inf-Italic",
                                          boldItalic=negrita)
        return "Inf", "Inf-Bold", "InfSerif", "InfSerif-Bold", "InfMono", "InfMono-Bold"
    except Exception:
        return ("Helvetica", "Helvetica-Bold", "Times-Roman", "Times-Bold",
                "Courier", "Courier-Bold")


(FUENTE, FUENTE_N, SERIF, SERIF_N, MONO, MONO_N) = _registrar_fuentes()

# Cifras destacadas: Times New Roman si esta disponible, serif del sistema si no
CIFRAS = "Times" if "Times" in pdfmetrics.getRegisteredFontNames() else SERIF


# ----------------------------------------------------------------------- Estilos
def _estilos():
    b = getSampleStyleSheet()["Normal"]
    e = {}

    def crear(nombre, **kw):
        e[nombre] = ParagraphStyle(nombre, parent=b, **kw)

    # Portada
    crear("cub_casa", fontName=SERIF_N, fontSize=13.5, leading=16,
          textColor=colors.white)
    crear("cub_division", fontName=FUENTE, fontSize=7, leading=10,
          textColor=colors.HexColor("#8FA3B5"), alignment=TA_RIGHT)
    crear("cub_marca", fontName=FUENTE_N, fontSize=7.4, leading=10,
          textColor=colors.HexColor("#9FB3C6"), spaceAfter=0)
    crear("cub_titulo", fontName=SERIF_N, fontSize=30, leading=34,
          textColor=colors.white, spaceAfter=2)
    crear("cub_ticker", fontName=MONO, fontSize=13, leading=17,
          textColor=colors.HexColor("#B8C4D0"))
    crear("cub_pie", fontName=FUENTE, fontSize=7.6, leading=10.6,
          textColor=TINTA_TENUE, alignment=TA_JUSTIFY)

    # Encabezados de apartado
    crear("ap_num", fontName=MONO_N, fontSize=8.4, leading=11,
          textColor=CORPORATIVO)
    # Los titulos llevan la serif de la marca. El palo seco quedaba plano al
    # lado de "Warrants & Co." y rompia la jerarquia: la casa y los apartados
    # son el mismo nivel de encabezado y deben compartir letra.
    crear("ap_titulo", fontName=SERIF_N, fontSize=12.5, leading=15.5,
          textColor=TINTA_CORPORATIVA)
    crear("ap_seccion", fontName=FUENTE_N, fontSize=6.2, leading=9,
          textColor=TINTA_MEDIA, alignment=TA_RIGHT)
    crear("ap_lema", fontName=FUENTE, fontSize=7.8, leading=10.6,
          textColor=colors.HexColor("#C4CFD9"))

    crear("h2", fontName=SERIF_N, fontSize=9, leading=11.6, textColor=TINTA,
          spaceBefore=7, spaceAfter=1.5)
    crear("h3", fontName=FUENTE_N, fontSize=6.4, leading=8.6, textColor=CORPORATIVO,
          spaceBefore=5, spaceAfter=1)

    # Texto
    crear("texto", fontName=FUENTE, fontSize=7.4, leading=10,
          textColor=TINTA_MEDIA, alignment=TA_JUSTIFY, spaceAfter=3.5)
    crear("nota", fontName=FUENTE, fontSize=6.4, leading=8.6,
          textColor=TINTA_TENUE, alignment=TA_JUSTIFY, spaceAfter=2.5)
    crear("pie_fig", fontName=FUENTE, fontSize=6.2, leading=8.2,
          textColor=TINTA_TENUE, alignment=TA_LEFT, spaceAfter=2)

    # Ficha de datos
    crear("f_eti", fontName=FUENTE, fontSize=6.8, leading=9, textColor=TINTA_MEDIA)
    crear("f_val", fontName=MONO, fontSize=6.6, leading=9, textColor=TINTA,
          alignment=TA_RIGHT)
    crear("f_val_pos", fontName=MONO, fontSize=6.6, leading=9,
          textColor=POSITIVO, alignment=TA_RIGHT)
    crear("f_val_neg", fontName=MONO, fontSize=6.6, leading=9,
          textColor=NEGATIVO, alignment=TA_RIGHT)

    # Cifras destacadas
    crear("d_val", fontName=CIFRAS, fontSize=14, leading=16.5,
          textColor=TINTA, alignment=TA_CENTER)
    crear("d_val_pos", fontName=CIFRAS, fontSize=14, leading=16.5,
          textColor=POSITIVO, alignment=TA_CENTER)
    crear("d_val_neg", fontName=CIFRAS, fontSize=14, leading=16.5,
          textColor=NEGATIVO, alignment=TA_CENTER)
    crear("d_eti", fontName=FUENTE, fontSize=6.2, leading=8.2,
          textColor=TINTA_TENUE, alignment=TA_CENTER)
    crear("d_ap", fontName=FUENTE, fontSize=6.2, leading=8,
          textColor=TINTA_TENUE, alignment=TA_CENTER)

    # Tablas
    crear("t_cab", fontName=FUENTE_N, fontSize=6.1, leading=8,
          textColor=CORPORATIVO)
    crear("t_cab_d", fontName=FUENTE_N, fontSize=6.1, leading=8,
          textColor=CORPORATIVO, alignment=TA_RIGHT)
    crear("t_cel", fontName=FUENTE, fontSize=6.5, leading=8.5,
          textColor=TINTA_MEDIA)
    crear("t_num", fontName=MONO, fontSize=6.3, leading=8.5, textColor=TINTA,
          alignment=TA_RIGHT)
    crear("t_cen", fontName=FUENTE, fontSize=6.5, leading=8.5,
          textColor=TINTA_MEDIA, alignment=TA_CENTER)
    return e


E = _estilos()


# ------------------------------------------------------------------- Formateo
def num(v, dec=2, suf=""):
    if v is None:
        return "—"
    try:
        x = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"{x:,.{dec}f}{suf}".replace(",", " ") if np.isfinite(x) else "—"


def pct(v, dec=2, signo=True):
    if v is None:
        return "—"
    try:
        x = float(v)
    except (TypeError, ValueError):
        return str(v)
    if not np.isfinite(x):
        return "—"
    return f"{x:+.{dec}%}" if signo else f"{x:.{dec}%}"


def moneda(v, div="USD", dec=2):
    if v is None:
        return "—"
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    return f"{x:,.{dec}f} {div}".replace(",", " ") if np.isfinite(x) else "—"


def compacto(v, dec=2):
    if v is None:
        return "—"
    try:
        x = float(v)
    except (TypeError, ValueError):
        return str(v)
    if not np.isfinite(x):
        return "—"
    s = "−" if x < 0 else ""
    x = abs(x)
    for corte, letra in ((1e12, " bill."), (1e9, " mm"), (1e6, " m"), (1e3, " k")):
        if x >= corte:
            return f"{s}{x/corte:,.{dec}f}{letra}".replace(",", " ")
    return f"{s}{x:,.{dec}f}".replace(",", " ")


MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre")


def fecha_larga(momento):
    """Fecha en castellano sin depender del idioma configurado en el sistema.

    `strftime("%B")` devuelve el mes en el idioma del entorno, de modo que el
    mismo codigo produce "19 de agosto" en un equipo y "19 de August" en otro.
    En un documento que se entrega a un tercero eso no es aceptable, y ademas
    es de los fallos que solo aparecen al cambiar de maquina.
    """
    if momento is None:
        return "—"
    return f"{momento.day} de {MESES[momento.month - 1]} de {momento.year}"


def esc(t):
    if t is None:
        return ""
    return (str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _signo(valor):
    """Estilo de valor segun su signo, para las fichas."""
    try:
        x = float(str(valor).replace("%", "").replace("+", "")
                  .replace("−", "-").replace(" ", "").split()[0])
    except (TypeError, ValueError, IndexError):
        return "f_val"
    if str(valor).strip().startswith(("+", "−", "-")):
        return "f_val_pos" if x > 0 and str(valor).strip()[0] == "+" else (
            "f_val_neg" if str(valor).strip()[0] in "−-" else "f_val")
    return "f_val"


# ---------------------------------------------------------------- Componentes
def apartado(numero, titulo, lema=None, seccion=None):
    """Encabezado de apartado: banda con numero, titulo y division a la derecha."""
    filas = [[Paragraph(f"{numero:02d}", E["ap_num"]),
              Paragraph(esc(titulo), E["ap_titulo"]),
              Paragraph(esc(seccion or ENTIDAD), E["ap_seccion"])]]
    t = Table(filas, colWidths=[9 * mm, ANCHO_UTIL - 49 * mm, 40 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, 0), "BOTTOM"),
        ("LEFTPADDING", (0, 0), (-1, 0), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -1), 1.0, TINTA_CORPORATIVA)]))
    piezas = [t]
    if lema:
        piezas.append(Spacer(1, 2.5))
        piezas.append(Paragraph(esc(lema), E["nota"]))
    piezas.append(Spacer(1, 3))
    return KeepTogether(piezas)


def h2(texto):
    """Epigrafe con filete inferior, al modo de un informe de analisis."""
    p = Paragraph(esc(texto), E["h2"])
    t = Table([[p]], colWidths=[ANCHO_UTIL])
    t.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 0.7, CORPORATIVO),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]))
    return t


def h3(texto):
    return Paragraph(esc(texto).upper(), E["h3"])


def parrafo(t):
    return Paragraph(esc(t), E["texto"])


def nota(t):
    return Paragraph(esc(t), E["nota"])


def pie_figura(t):
    return Paragraph(esc(t), E["pie_fig"])


def espacio(alto=3):
    return Spacer(1, alto)


def juntos(piezas):
    return KeepTogether(piezas)


def no_partir(alto_mm=42):
    """Salta de pagina si no quedan al menos `alto_mm` libres."""
    return CondPageBreak(alto_mm * mm)


def destacados(pares, ancho=None):
    """Cifras de cabecera: numeral grande, etiqueta pequena, filetes verticales.

    Sin recuadros: los separadores son filetes de un cuarto de punto entre
    columnas y un filete fino arriba y abajo del conjunto.
    """
    if not pares:
        return espacio(0)
    ancho = ancho or ANCHO_UTIL
    n = len(pares)
    valores, etiquetas = [], []
    for pieza in pares:
        eti, val = pieza[0], pieza[1]
        ap = pieza[2] if len(pieza) > 2 else None
        estilo = "d_val"
        crudo = str(val).strip()
        if crudo.startswith("+"):
            estilo = "d_val_pos"
        elif crudo.startswith(("-", "−")):
            estilo = "d_val_neg"
        valores.append(Paragraph(esc(val), E[estilo]))
        texto = esc(eti)
        if ap:
            texto += f"<br/><font size=6.2 color='#8A9099'>{esc(ap)}</font>"
        etiquetas.append(Paragraph(texto, E["d_eti"]))
    t = Table([valores, etiquetas], colWidths=[ancho / n] * n)
    ordenes = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, 0), 7),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 0),
        ("TOPPADDING", (0, 1), (-1, 1), 1),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("LINEABOVE", (0, 0), (-1, 0), 0.7, CORPORATIVO),
        ("LINEBELOW", (0, 1), (-1, 1), 0.35, FILETE),
    ]
    for c in range(1, n):
        ordenes.append(("LINEBEFORE", (c, 0), (c, -1), 0.25, FILETE_FINO))
    t.setStyle(TableStyle(ordenes))
    return t


def ficha(pares, columnas=2, ancho=None, color_signo=True):
    """Ficha de datos: etiqueta a la izquierda, valor a la derecha.

    Es el componente que sustituye a los recuadros. Cada par ocupa una linea
    con un filete finisimo debajo; los valores van en monoespaciada para que
    las cifras alineen por columna, como en cualquier informe de analisis.
    """
    if not pares:
        return espacio(0)
    ancho = ancho or ANCHO_UTIL
    por_col = (len(pares) + columnas - 1) // columnas
    bloques = [pares[i * por_col:(i + 1) * por_col] for i in range(columnas)]
    filas = []
    for i in range(por_col):
        fila = []
        for bloque in bloques:
            if i < len(bloque):
                eti, val = bloque[i][0], bloque[i][1]
                estilo = _signo(val) if color_signo else "f_val"
                fila.append(Paragraph(esc(eti), E["f_eti"]))
                fila.append(Paragraph(esc(val), E[estilo]))
            else:
                fila.extend(["", ""])
        filas.append(fila)

    calle = 5 * mm
    ancho_col = (ancho - calle * (columnas - 1)) / columnas
    cols = []
    for c in range(columnas):
        cols.extend([ancho_col * 0.60, ancho_col * 0.40])
    t = Table(filas, colWidths=cols)
    ordenes = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]
    for c in range(columnas):
        i0, i1 = c * 2, c * 2 + 1
        ordenes.append(("LINEBELOW", (i0, 0), (i1, -1), 0.25, FILETE_FINO))
        if c:
            ordenes.append(("LEFTPADDING", (i0, 0), (i0, -1), calle))
    t.setStyle(TableStyle(ordenes))
    return t


def tabla(datos, cabecera=None, anchos=None, alineacion=None, tamano=7.1,
          numericas=None, ancho=None, resaltar=None):
    """Tabla de informe: sin marco exterior, filete bajo la cabecera, hairlines.

    `alineacion` admite 'L', 'R', 'C' y 'N' (numerica: monoespaciada a la
    derecha, para que las cifras cuadren en vertical).
    """
    if not datos:
        return nota("Sin datos disponibles.")
    ancho = ancho or ANCHO_UTIL
    ncol = len(cabecera) if cabecera else len(datos[0])
    if anchos:
        total = float(sum(anchos))
        cols = [ancho * (a / total) for a in anchos]
    else:
        cols = [ancho / ncol] * ncol

    alineacion = alineacion or (["L"] + ["N"] * (ncol - 1))
    if len(alineacion) < ncol:
        alineacion = list(alineacion) + ["N"] * (ncol - len(alineacion))

    est_cel = ParagraphStyle("c", parent=E["t_cel"], fontSize=tamano,
                             leading=tamano * 1.30)
    est_num = ParagraphStyle("n", parent=E["t_num"], fontSize=tamano - 0.1,
                             leading=tamano * 1.30)
    est_cen = ParagraphStyle("x", parent=E["t_cen"], fontSize=tamano,
                             leading=tamano * 1.30)

    cuerpo = []
    if cabecera:
        cuerpo.append([
            Paragraph(esc(c), E["t_cab_d"] if alineacion[i] in "NR"
                      else E["t_cab"])
            for i, c in enumerate(cabecera)])
    for fila in datos:
        linea = []
        for i, celda in enumerate(fila):
            a = alineacion[i] if i < len(alineacion) else "L"
            estilo = est_num if a == "N" else (est_cen if a == "C" else est_cel)
            linea.append(Paragraph(esc(celda), estilo))
        cuerpo.append(linea)

    clase = LongTable if len(cuerpo) > 18 else Table
    t = clase(cuerpo, colWidths=cols, repeatRows=1 if cabecera else 0)
    t.splitByRow = 1
    ordenes = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.4),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, FILETE_FINO),
    ]
    if cabecera:
        ordenes += [
            ("LINEABOVE", (0, 0), (-1, 0), 0.7, CORPORATIVO),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, CORPORATIVO),
            ("TOPPADDING", (0, 0), (-1, 0), 3),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 3),
        ]
    ordenes.append(("LINEBELOW", (0, -1), (-1, -1), 0.5, FILETE))
    for f in (resaltar or []):
        i = f + (1 if cabecera else 0)
        if 0 <= i < len(cuerpo):
            ordenes.append(("BACKGROUND", (0, i), (-1, i), PAPEL_SUAVE))
    for c, a in enumerate(alineacion[:ncol]):
        if a == "R":
            ordenes.append(("ALIGN", (c, 0), (c, -1), "RIGHT"))
    t.setStyle(TableStyle(ordenes))
    return t


AÑO_MIN, AÑO_MAX = 1900, 2100

_PISTAS_PORCENTAJE = ("sobre ", "peso", "margen", "%", "tasa", "cuota",
                      "rentabilidad", "variación", "variacion", "crecimiento",
                      "desvío", "desvio", "positivo", "dilución", "dilucion",
                      "retorno", "rendimiento")
_PISTAS_RATIO = ("/", "ratio", "veces", "múltiplo", "multiplo", "ebitda",
                 "score", "beta", "correlación", "correlacion")
_PISTAS_AÑO = ("ejercicio", "año", "anio", "year", "periodo")
_PISTAS_CUENTA = ("episodios", "sesiones", "casos", "contratos", "minutos",
                  "operaciones", "acciones", "número", "numero", "n ")


def _formato_automatico(serie, nombre):
    """Deduce como imprimir una columna a partir de su nombre y sus valores.

    Sin esto, el formateo por defecto aplicaba tres decimales y separador de
    millares a TODO: un ejercicio salia como «2 022.000», un importe de
    veintiocho mil millones como «28 184 000 000.000» y una proporcion de 0,07
    como «0.071» en lugar de «7,1 %». Es de los fallos que no rompen nada y
    salen impresos.
    """
    texto = str(nombre).lower()
    valores = pd.to_numeric(serie, errors="coerce").dropna()

    # Ejercicios y años: enteros de cuatro cifras, sin separador ni decimales
    if any(x in texto for x in _PISTAS_AÑO) or (
            len(valores) and (valores % 1 == 0).all()
            and valores.between(AÑO_MIN, AÑO_MAX).all()):
        return lambda v: (f"{int(v)}" if v is not None
                          and np.isfinite(pd.to_numeric(v, errors="coerce"))
                          else "—")
    if any(x in texto for x in _PISTAS_PORCENTAJE):
        return lambda v: pct(v, 1, texto.startswith(("variación", "variacion",
                                                     "crecimiento", "desvío",
                                                     "desvio", "retorno")))
    if any(x in texto for x in _PISTAS_RATIO):
        return lambda v: num(v, 2)
    if any(x in texto for x in _PISTAS_CUENTA):
        # Un recuento de miles de millones de acciones se lee mucho mejor
        # abreviado; por debajo de cien mil, la cifra entera es mas precisa.
        if len(valores) and valores.abs().max() >= 1e5:
            return lambda v: compacto(v, 2)
        return lambda v: num(v, 0)
    # Importes: en cuanto la magnitud es grande, notacion abreviada
    if len(valores) and valores.abs().max() >= 1e5:
        return lambda v: compacto(v, 2)
    if len(valores) and valores.abs().max() <= 1.5:
        return lambda v: num(v, 3)
    return lambda v: num(v, 2)


def tabla_df(df, columnas=None, formatos=None, anchos=None, maximo=None,
             tamano=7.1, alineacion=None, ancho=None, encabezados=None):
    """Vuelca un DataFrame a una tabla, deduciendo el formato de cada columna."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return nota("Sin datos disponibles.")
    vista = df[columnas] if columnas else df
    if maximo:
        vista = vista.head(maximo)
    formatos = formatos or {}
    automaticos = {c: _formato_automatico(vista[c], c) for c in vista.columns}

    filas = []
    for _, fila in vista.iterrows():
        salida = []
        for col in vista.columns:
            v = fila[col]
            f = formatos.get(col)
            if callable(f):
                try:
                    salida.append(f(v))
                except Exception:
                    salida.append("—")
            elif isinstance(v, (bool, np.bool_)):
                salida.append("Sí" if v else "No")
            elif isinstance(v, (int, float, np.integer, np.floating)):
                salida.append(automaticos[col](v))
            elif v is None:
                salida.append("—")
            else:
                salida.append(str(v))
        filas.append(salida)

    if alineacion is None:
        alineacion = ["L"] + [
            "N" if pd.api.types.is_numeric_dtype(vista[c]) else "L"
            for c in list(vista.columns)[1:]]
    cab = encabezados or [str(c) for c in vista.columns]
    return tabla(filas, cab, anchos=anchos, tamano=tamano,
                 alineacion=alineacion, ancho=ancho)


def dos_columnas(izquierda, derecha, proporcion=(1, 1)):
    """Compone dos bloques en paralelo, con calle entre ellos."""
    calle = 6 * mm
    total = sum(proporcion)
    a = (ANCHO_UTIL - calle) * proporcion[0] / total
    b = (ANCHO_UTIL - calle) * proporcion[1] / total
    t = Table([[izquierda, derecha]], colWidths=[a + calle / 2, b + calle / 2])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), calle / 2),
        ("LEFTPADDING", (1, 0), (1, 0), calle / 2),
        ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    return t


# --------------------------------------------------------------------- Figuras
def figura(fig, ancho_mm=178, pie=None, cerrar=True):
    """Incrusta una figura de matplotlib, opcionalmente con su pie."""
    if fig is None:
        return nota("Gráfico no disponible.")
    for ax in fig.get_axes():
        if ax.get_title():
            ax.title.set_fontfamily("DejaVu Serif")
            ax.title.set_fontweight("bold")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=220, bbox_inches="tight",
                facecolor="white", edgecolor="none", pad_inches=0.02)
    if cerrar:
        plt.close(fig)
    buf.seek(0)
    from PIL import Image as PILImage
    with PILImage.open(buf) as im:
        w, h = im.size
    buf.seek(0)
    ancho = ancho_mm * mm
    alto = ancho * h / w
    tope = ALTO_UTIL - 30 * mm
    if alto > tope:
        alto = tope
        ancho = alto * w / h
    imagen = Image(buf, width=ancho, height=alto)
    if not pie:
        return imagen
    return juntos([imagen, Spacer(1, 1.5), pie_figura(pie)])


def lienzo(ancho=7.0, alto=2.6, filas=1, columnas=1, **kw):
    """Figura de matplotlib con el aspecto tipografico del informe."""
    fig, ejes = plt.subplots(filas, columnas, figsize=(ancho, alto), **kw)
    for ax in (ejes.flat if hasattr(ejes, "flat") else [ejes]):
        ax.grid(True, alpha=1.0, linewidth=0.45, color="#E3E5E8")
        ax.set_axisbelow(True)
        for lado in ("top", "right"):
            ax.spines[lado].set_visible(False)
        for lado in ("left", "bottom"):
            ax.spines[lado].set_color("#9AA0A6")
            ax.spines[lado].set_linewidth(0.6)
        ax.tick_params(labelsize=6.4, colors="#41474E", length=2.2, width=0.55)
        ax.xaxis.label.set(size=6.8, color="#41474E")
        ax.yaxis.label.set(size=6.8, color="#41474E")
        ax.title.set(size=7.6, color="#16324F")
        for texto in ax.get_xticklabels() + ax.get_yticklabels():
            texto.set_fontname("DejaVu Sans")
    return fig, ejes


def leyenda(ax, **kw):
    opciones = dict(fontsize=6.2, framealpha=0.92, edgecolor="#E3E5E8",
                    borderpad=0.35, handlelength=1.5, labelspacing=0.3)
    opciones.update(kw)
    lg = ax.legend(**opciones)
    if lg:
        lg.get_frame().set_linewidth(0.4)
    return lg


def eje_compacto(ax, cual="y"):
    """Rotula el eje en miles y millones en lugar de con el factor 1e6.

    El rotulo de escala que matplotlib coloca en una esquina es ilegible en un
    documento impreso y obliga al lector a multiplicar de cabeza.
    """
    from matplotlib.ticker import FuncFormatter

    def formato(v, _pos):
        a = abs(v)
        for corte, letra in ((1e12, " bill."), (1e9, " mm"), (1e6, " m"),
                             (1e3, " k")):
            if a >= corte:
                return f"{v/corte:,.0f}{letra}".replace(",", " ")
        return f"{v:,.0f}".replace(",", " ")

    destino = ax.yaxis if cual == "y" else ax.xaxis
    destino.set_major_formatter(FuncFormatter(formato))
    return ax


def salto():
    return PageBreak()
