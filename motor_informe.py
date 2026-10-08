"""INFORME INSTITUCIONAL DE RENTA VARIABLE. Documento A4 imprimible.

Vuelca a papel todo lo que la aplicacion muestra en pantalla para el activo
estudiado: los catorce apartados, con sus cifras, sus tablas y sus graficos, en
el mismo orden en que aparecen en la web.

PRINCIPIO DE CONSTRUCCION
-------------------------
El informe NO recalcula nada por su cuenta. Llama exactamente a los mismos
motores que alimentan la pantalla y se limita a maquetar lo que devuelven.
Cualquier otra cosa produciria un documento que dice algo distinto de lo que el
usuario acaba de ver, que es el peor fallo posible en un papel que se imprime,
se archiva y se entrega a un tercero.

El sistema visual vive en informe_base.py y la recopilacion de datos en
informe_datos.py. Aqui solo hay composicion de apartados.
"""

import io
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (BaseDocTemplate, Frame, NextPageTemplate,
                                PageBreak, PageTemplate, Paragraph, Spacer,
                                Table, TableStyle)

import informe_base as ib
import motor_analisis as ma
import partidas_contables as pc


# =============================================================================
#  PLANTILLA DE PAGINA
# =============================================================================

class _Documento(BaseDocTemplate):
    """Portada a sangre y paginas interiores con cabecera y pie corridos."""

    def __init__(self, destino, ticker, nombre, divisa, fecha_datos, **kw):
        super().__init__(
            destino, pagesize=ib.PAGINA,
            leftMargin=ib.MARGEN, rightMargin=ib.MARGEN,
            topMargin=ib.MARGEN_SUP, bottomMargin=ib.MARGEN_INF,
            title=f"{ib.ENTIDAD} · Informe de análisis · {ticker}",
            author=ib.ENTIDAD_LARGA,
            subject=f"Informe de {nombre}", **kw)
        self.ticker = ticker
        self.nombre = nombre
        self.divisa = divisa
        self.fecha_datos = fecha_datos
        # Fecha de generacion, no de los datos: cada descarga lleva la suya.
        self.fecha_informe = ib.fecha_larga(datetime.now())

        marco = Frame(self.leftMargin, self.bottomMargin, self.width,
                      self.height, id="cuerpo", leftPadding=0, rightPadding=0,
                      topPadding=0, bottomPadding=0)
        # La portada usa los mismos margenes que el resto. Antes ocupaba la
        # hoja entera para que la banda azul sangrase a borde, pero una
        # impresora domestica no imprime hasta el filo y el resultado era un
        # rectangulo cortado con un reborde blanco irregular.
        marco_portada = Frame(self.leftMargin, ib.MARGEN, self.width,
                              ib.PAGINA[1] - 2 * ib.MARGEN,
                              id="portada", leftPadding=0, rightPadding=0,
                              topPadding=0, bottomPadding=0)
        self.addPageTemplates([
            PageTemplate(id="portada", frames=[marco_portada]),
            PageTemplate(id="interior", frames=[marco], onPage=self._adornos),
        ])

    def _adornos(self, c, doc):
        """Cabecera y pie corridos, identicos a los de la primera pagina.

        La cabecera reproduce el membrete de portada -distintivo, casa,
        division y fecha- para que el documento se lea como una sola pieza. La
        fecha es la del dia en que se genera el informe, de modo que una
        descarga posterior lleva la suya.
        """
        izq, der = self.leftMargin, self.leftMargin + self.width
        y = ib.PAGINA[1] - ib.MARGEN_SUP + 7.5 * mm
        c.saveState()

        # distintivo
        c.setFont(ib.FUENTE_N, 8)
        c.setFillColor(ib.CORPORATIVO)
        c.drawString(izq, y, "▶")

        # casa y division
        c.setFont(ib.SERIF_N, 9.6)
        c.setFillColor(ib.TINTA_CORPORATIVA)
        c.drawString(izq + 5.2 * mm, y, ib.ENTIDAD)
        ancho = c.stringWidth(ib.ENTIDAD, ib.SERIF_N, 9.6)
        c.setFont(ib.FUENTE_N, 6.2)
        c.setFillColor(ib.TINTA_MEDIA)
        c.drawString(izq + 5.2 * mm + ancho + 4, y, "EQUITY & CREDIT RESEARCH")

        # valor analizado y fecha del informe
        c.setFont(ib.FUENTE, 6.6)
        c.setFillColor(ib.TINTA_TENUE)
        c.drawRightString(der, y, f"{self.ticker} · {self.fecha_informe}")

        c.setStrokeColor(ib.TINTA_CORPORATIVA)
        c.setLineWidth(1.0)
        c.line(izq, y - 2.6 * mm, der, y - 2.6 * mm)

        # pie
        yp = self.bottomMargin - 7 * mm
        c.setStrokeColor(ib.FILETE)
        c.setLineWidth(0.35)
        c.line(izq, yp + 4.2 * mm, der, yp + 4.2 * mm)
        c.setFont(ib.FUENTE, 6.2)
        c.setFillColor(ib.TINTA_TENUE)
        # El pie se reparte en tres tramos que no pueden solaparse: la casa a la
        # izquierda, la advertencia centrada y el numero de pagina a la derecha.
        c.drawString(izq, yp, f"{ib.ENTIDAD_LARGA} · datos a {self.fecha_datos}")
        c.drawCentredString(izq + self.width * 0.72, yp,
                            "No constituye recomendación de inversión")
        c.setFont(ib.MONO, 6.4)
        c.setFillColor(ib.TINTA_MEDIA)
        c.drawRightString(der, yp, f"{doc.page - 1:02d}")
        c.restoreState()


# =============================================================================
#  PORTADA
# =============================================================================

def _portada(d):
    """Primera pagina: hoja de datos a tres columnas.

    Vive en informe_portada.py porque su composicion no se parece a la de
    ningun otro apartado: es una rejilla densa de paneles, al modo de la
    primera pagina de una nota de mercados.
    """
    import informe_portada
    return informe_portada.construir(d, __import__("motor_informe"))


# =============================================================================
#  01 · RESUMEN
# =============================================================================

def _g_resumen(hist, divisa, alto=2.3):
    fig, ax = ib.lienzo(7.0, alto)
    ax.plot(hist.index, hist["Close"], color=ib.MPL_CORP, linewidth=0.95)
    ax.fill_between(hist.index, hist["Close"].min(), hist["Close"],
                    color=ib.MPL_CORP, alpha=0.06)
    ax.set_ylabel(f"Precio ({divisa})")
    ax.set_title("Evolución del cierre ajustado")
    fig.tight_layout(pad=0.3)
    return fig


def _g_caidas(hist, rendimiento):
    """Curva de caidas desde maximos y su distribucion acumulada."""
    serie = (rendimiento or {}).get("Series_Drawdown")
    if serie is None or len(serie) == 0:
        return None
    fig, (a1, a2) = ib.lienzo(7.0, 2.6, columnas=2,
                              gridspec_kw={"width_ratios": [2.2, 1]})
    a1.fill_between(serie.index, serie, 0, color=ib.MPL_ROJO, alpha=0.28)
    a1.plot(serie.index, serie, color=ib.MPL_ROJO, linewidth=0.7)
    a1.axhline(0, color=ib.MPL_GRIS, linewidth=0.6)
    peor = float(serie.min())
    a1.axhline(peor, color=ib.MPL_CORP, linestyle="--", linewidth=0.8,
               label=f"Máxima caída {peor:.1%}")
    a1.set_ylabel("Caída desde máximos")
    a1.set_title("Historial de caídas")
    ib.leyenda(a1)
    orden = np.sort(serie.to_numpy(dtype=float))
    a2.plot(orden, np.arange(1, len(orden) + 1) / len(orden),
            color=ib.MPL_CORP, linewidth=1.1)
    a2.axvline(0, color=ib.MPL_GRIS, linewidth=0.6)
    a2.set_xlabel("Caída")
    a2.set_ylabel("Proporción de sesiones")
    a2.set_title("Distribución acumulada")
    fig.tight_layout(pad=0.3)
    return fig


def _resumen(d):
    hist, divisa = d["hist"], d["divisa"]
    s = d.get("situacion") or {}
    r = d.get("rendimiento") or {}
    g = d.get("riesgo") or {}
    p = [ib.apartado(1, "Perfil del valor y métricas de riesgo",
                     "Datos de mercado, rendimiento ajustado por riesgo e "
                     "indicadores técnicos del periodo analizado.",
                     seccion="Datos del valor")]

    p.append(ib.figura(
        _g_caidas(hist, r),
        pie="Distancia del precio a su máximo histórico previo, sesión a "
            "sesión. El área sombreada mide cuánto tiempo pasa el valor por "
            "debajo de su máximo y con qué profundidad."))
    p.append(ib.espacio(4))

    izq = [ib.h3(f"Rendimiento del periodo · {len(hist):,} sesiones"
                 .replace(",", " ")),
           ib.ficha([
               ("Retorno anualizado", ib.pct(r.get("Retorno Anualizado"))),
               ("Volatilidad anual", ib.pct(r.get("Volatilidad Anual"), 2, False)),
               ("Ratio de Sharpe", ib.num(r.get("Sharpe Ratio"), 3)),
               ("Ratio de Sortino", ib.num(r.get("Sortino Ratio"), 3)),
               ("Máxima caída", ib.pct(r.get("Max Drawdown"))),
               ("Ratio de Calmar", ib.num(r.get("Ratio de Calmar"), 3)),
           ], columnas=1, ancho=ib.COLUMNA)]
    der = [ib.h3(f"Riesgo diario al {d['confianza']:.1f} %"),
           ib.ficha([
               ("VaR histórico", ib.pct(g.get("var_hist"))),
               ("VaR paramétrico", ib.pct(g.get("var_param"))),
               ("CVaR histórico", ib.pct(g.get("cvar"))),
               ("Exceso del CVaR sobre el VaR",
                ib.pct((g.get("cvar") - g.get("var_hist"))
                       if g else None)),
               ("Sigma diaria", ib.pct(s.get("sigma_dia"), 2, False)),
               ("Volatilidad anualizada", ib.pct(s.get("vol_anual"), 1, False)),
           ], columnas=1, ancho=ib.COLUMNA)]
    p.append(ib.dos_columnas(izq, der))

    tec = d.get("tecnicos") or {}
    if tec:
        p.append(ib.h2("Indicadores técnicos"))
        p.append(ib.ficha([
            ("Índice de fuerza relativa (14)", ib.num(tec.get("rsi"), 1)),
            ("Posición en las bandas", ib.num(tec.get("posicion_bb"), 2)),
            ("Distancia a la media de 20", ib.pct(tec.get("dist_sma20"))),
            ("Distancia a la media de 50", ib.pct(tec.get("dist_sma50"))),
            ("Distancia a la media de 200", ib.pct(tec.get("dist_sma200"))),
            ("Racha bajista", _sesiones(tec.get("racha_bajista"))),
        ], columnas=2))

    alt = d.get("alternativas")
    if alt:
        p.append(ib.h2("Listados alternativos del mismo emisor"))
        p.append(ib.nota(
            "El histórico disponible para este símbolo es corto. Estos otros "
            "listados del mismo emisor disponen de series más largas y "
            "permitirían un análisis con mayor respaldo estadístico."))
        p.append(ib.tabla(
            [[a.get("simbolo", ""), a.get("nombre", ""), a.get("mercado", ""),
              ib.num(a.get("sesiones"), 0)] for a in alt[:6]],
            ["Símbolo", "Denominación", "Mercado", "Sesiones"],
            anchos=[1, 3.4, 1.4, 1], alineacion=["L", "L", "L", "N"]))
    return p


# =============================================================================
#  02 · GRAFICO DE COTIZACION
# =============================================================================

def _g_velas(velas, tk, divisa):
    if velas is None or velas.empty:
        return None
    fig, (a1, a2) = ib.lienzo(7.0, 3.15, filas=2, sharex=True,
                              gridspec_kw={"height_ratios": [3.2, 1]})
    d = velas
    x = np.arange(len(d))
    sube = d["Close"].values >= d["Open"].values
    col = np.where(sube, ib.MPL_VERDE, ib.MPL_ROJO)
    a1.vlines(x, d["Low"].values, d["High"].values, color=col, linewidth=0.5)
    a1.bar(x, np.abs(d["Close"].values - d["Open"].values), 0.66,
           bottom=np.minimum(d["Open"].values, d["Close"].values),
           color=col, linewidth=0)
    for v, c in ((20, ib.MPL_CORP), (50, ib.MPL_AMBAR), (200, ib.MPL_MORADO)):
        if len(d) >= v:
            a1.plot(x, d["Close"].rolling(v).mean().values, color=c,
                    linewidth=0.85, label=f"Media {v}")
    if a1.get_legend_handles_labels()[0]:
        ib.leyenda(a1, loc="best")
    a1.set_ylabel(f"Precio ({divisa})")
    a1.set_title(f"{tk} · cotización, volumen y medias móviles")
    a2.bar(x, d["Volume"].values, 0.66, color=col, alpha=0.55, linewidth=0)
    a2.set_ylabel("Volumen")
    ib.eje_compacto(a2)
    paso = max(len(d) // 10, 1)
    pos = list(range(0, len(d), paso))
    a2.set_xticks(pos)
    a2.set_xticklabels([d.index[i].strftime("%d/%m/%y") for i in pos], fontsize=6.2)
    fig.tight_layout(pad=0.3)
    return fig


def _grafico(d):
    velas, divisa = d.get("velas"), d["divisa"]
    res = d.get("resumen_velas") or {}
    p = [ib.apartado(2, "Comportamiento del precio",
                     "Velas con volumen y medias móviles de 20, 50 y 200 "
                     "periodos, con las sesiones de preapertura y postcierre "
                     "diferenciadas.", seccion="Precio")]
    if velas is None or velas.empty:
        p.append(ib.nota("El proveedor no ha devuelto cotizaciones para esta "
                         "combinación de granularidad y periodo."))
        return p

    p.append(ib.destacados([
        ("Último", ib.moneda(res.get("ultimo"), divisa)),
        ("Jornada", ib.pct(res.get("variacion_jornada"))),
        ("Máximo", ib.num(res.get("maximo"))),
        ("Mínimo", ib.num(res.get("minimo"))),
        ("Volumen", ib.compacto(res.get("volumen"), 1)),
    ]))
    p.append(ib.espacio(4))
    p.append(ib.figura(_g_velas(velas, d["ticker"], divisa)))

    reparto = (velas["Sesion"].value_counts().to_dict()
               if "Sesion" in velas else {})
    p.append(ib.espacio(3))
    p.append(ib.ficha([
        ("Granularidad", str(d.get("intervalo_etiqueta", d["intervalo"]))),
        ("Periodo representado", str(d["periodo_grafico"])),
        ("Velas dibujadas", ib.num(len(velas), 0)),
        ("Sesiones distintas", ib.num(pd.Series(velas["Fecha"]).nunique(), 0)),
        ("Desde", res["desde"].strftime("%d/%m/%Y %H:%M") if res.get("desde") else "—"),
        ("Hasta", res["momento"].strftime("%d/%m/%Y %H:%M") if res.get("momento") else "—"),
    ], columnas=2, color_signo=False))
    if reparto:
        p.append(ib.espacio(3))
        p.append(ib.tabla(
            [[k, ib.num(v, 0), ib.pct(v / len(velas), 1, False)]
             for k, v in reparto.items()],
            ["Franja horaria", "Velas", "Peso"], anchos=[3, 1, 1]))
    return p


# =============================================================================
#  03 · PRECIO Y RETORNOS
# =============================================================================

def _g_precio(hist, tk, divisa):
    fig, (a1, a2) = ib.lienzo(7.0, 3.2, filas=2,
                              gridspec_kw={"height_ratios": [1.3, 1]})
    a1.plot(hist.index, hist["Close"], color=ib.MPL_CORP, linewidth=0.9)
    a1.set_ylabel(f"Precio ({divisa})")
    a1.set_title(f"{tk} · cierre ajustado")
    r = hist["Return"].dropna()
    a2.hist(r, bins=70, color=ib.MPL_CORP, alpha=0.72, edgecolor="white",
            linewidth=0.25)
    a2.axvline(float(r.mean()), color=ib.MPL_ROJO, linestyle="--", linewidth=0.9,
               label=f"Media {r.mean():+.3%}")
    a2.set_xlabel("Retorno diario")
    a2.set_ylabel("Frecuencia")
    a2.set_title("Distribución de los retornos diarios")
    ib.leyenda(a2)
    fig.tight_layout(pad=0.3)
    return fig


def _g_vol_acum(hist):
    fig, (a1, a2) = ib.lienzo(7.0, 2.95, filas=2)
    v = hist["Volatility"].dropna()
    a1.plot(v.index, v, color=ib.MPL_MORADO, linewidth=0.85)
    a1.axhline(float(v.mean()), color=ib.MPL_GRIS, linestyle="--", linewidth=0.7,
               label=f"Media {v.mean():.1%}")
    a1.set_ylabel("Volatilidad anualizada")
    a1.set_title("Volatilidad móvil de 21 sesiones")
    ib.leyenda(a1)
    acum = (1 + hist["Return"].fillna(0)).cumprod() - 1
    a2.plot(acum.index, acum, color=ib.MPL_CORP, linewidth=0.9)
    a2.axhline(0, color=ib.MPL_GRIS, linewidth=0.6)
    a2.fill_between(acum.index, 0, acum, where=acum >= 0, color=ib.MPL_VERDE,
                    alpha=0.10)
    a2.fill_between(acum.index, 0, acum, where=acum < 0, color=ib.MPL_ROJO,
                    alpha=0.10)
    a2.set_ylabel("Retorno acumulado")
    a2.set_title("Retorno acumulado del periodo")
    fig.tight_layout(pad=0.3)
    return fig


def _precio(d):
    hist, divisa, tk = d["hist"], d["divisa"], d["ticker"]
    r = hist["Return"].dropna()
    lr = hist["LogReturn"].dropna()
    from scipy import stats as sps
    p = [ib.apartado(3, "Distribución de retornos y volatilidad",
                     "Momentos de la distribución de retornos diarios, "
                     "percentiles, volatilidad realizada y retorno acumulado.",
                     seccion="Retornos")]

    p.append(ib.destacados([
        ("Retorno medio", ib.pct(r.mean(), 3)),
        ("Desviación típica", ib.pct(r.std(), 3, False)),
        ("Asimetría", ib.num(sps.skew(r), 3)),
        ("Curtosis", ib.num(sps.kurtosis(r), 3)),
        ("Sesiones", ib.num(len(r), 0)),
    ]))
    p.append(ib.espacio(4))
    p.append(ib.figura(_g_precio(hist, tk, divisa)))
    p.append(ib.espacio(4))

    izq = [ib.h3("Estadísticos de la serie"),
           ib.ficha([
               ("Precio inicial", ib.moneda(hist["Close"].iloc[0], divisa)),
               ("Precio final", ib.moneda(hist["Close"].iloc[-1], divisa)),
               ("Retorno acumulado",
                ib.pct(hist["Close"].iloc[-1] / hist["Close"].iloc[0] - 1)),
               ("Máximo del periodo", ib.moneda(hist["Close"].max(), divisa)),
               ("Mínimo del periodo", ib.moneda(hist["Close"].min(), divisa)),
               ("Mejor sesión", ib.pct(r.max())),
               ("Peor sesión", ib.pct(r.min())),
           ], columnas=1, ancho=ib.COLUMNA)]
    der = [ib.h3("Retornos logarítmicos"),
           ib.ficha([
               ("Media", ib.pct(lr.mean(), 4)),
               ("Volatilidad diaria", ib.pct(lr.std(), 3, False)),
               ("Volatilidad anualizada",
                ib.pct(lr.std() * np.sqrt(252), 2, False)),
               ("Sesiones al alza",
                f"{int((r > 0).sum())} de {len(r)}"),
               ("Proporción al alza", ib.pct((r > 0).mean(), 1, False)),
               ("Sesiones a la baja",
                f"{int((r < 0).sum())} de {len(r)}"),
               ("Proporción a la baja", ib.pct((r < 0).mean(), 1, False)),
           ], columnas=1, ancho=ib.COLUMNA)]
    p.append(ib.dos_columnas(izq, der))

    p.append(ib.h2("Percentiles de la distribución"))
    perc = [1, 5, 10, 25, 50, 75, 90, 95, 99]
    p.append(ib.tabla(
        [[ib.pct(np.percentile(r, q), 2) for q in perc]],
        [f"P{q}" for q in perc], alineacion=["N"] * len(perc), tamano=7.0))

    p.append(ib.no_partir(60))
    p.append(ib.figura(_g_vol_acum(hist)))
    return p


# =============================================================================
#  04 · MONTE CARLO
# =============================================================================

def _g_mc(sim, S0, divisa):
    precios = np.asarray(sim["precios"])
    finales = np.asarray(sim["finales"], dtype=float)
    finales = finales[np.isfinite(finales)]
    if finales.size == 0 or not np.isfinite(precios).any():
        return None
    fig, (a1, a2) = ib.lienzo(7.0, 3.1, columnas=2,
                              gridspec_kw={"width_ratios": [1.75, 1]})
    paso = max(precios.shape[1] // 160, 1)
    for j in range(0, precios.shape[1], paso):
        a1.plot(precios[:, j], color=ib.MPL_CORP, alpha=0.05, linewidth=0.35)
    a1.plot(sim["mediana_camino"], color=ib.MPL_CORP, linewidth=1.5,
            label="Mediana")
    a1.plot(sim["mejor_camino"], color=ib.MPL_VERDE, linewidth=1.0,
            linestyle="--", label="Mejor escenario")
    a1.plot(sim["peor_camino"], color=ib.MPL_ROJO, linewidth=1.0,
            linestyle="--", label="Peor escenario")
    a1.axhline(S0, color=ib.MPL_GRIS, linewidth=0.7, linestyle=":")
    a1.set_xlabel("Sesiones")
    a1.set_ylabel(f"Precio ({divisa})")
    a1.set_title("Trayectorias simuladas a un año")
    ib.leyenda(a1)
    a2.hist(finales, bins=50, color=ib.MPL_CORP, alpha=0.72, edgecolor="white",
            linewidth=0.25, orientation="horizontal")
    a2.axhline(float(np.median(finales)), color=ib.MPL_CORP, linewidth=1.2)
    a2.axhline(S0, color=ib.MPL_GRIS, linewidth=0.7, linestyle=":")
    a2.set_xlabel("Frecuencia")
    a2.set_title("Precio final")
    fig.tight_layout(pad=0.3)
    return fig


def _g_convergencia(sim, S0):
    conv = np.asarray(sim.get("convergencia", []), dtype=float)
    if conv.size < 10:
        return None
    fig, ax = ib.lienzo(7.0, 1.9)
    ax.plot(np.arange(1, len(conv) + 1), conv, color=ib.MPL_CORP, linewidth=0.8)
    ax.axhline(float(sim.get("teorico", np.nan)), color=ib.MPL_ROJO,
               linestyle="--", linewidth=0.8, label="Valor teórico")
    ax.set_xlabel("Simulaciones acumuladas")
    ax.set_ylabel("Precio medio")
    ax.set_title("Convergencia de la media simulada")
    ib.leyenda(ax)
    fig.tight_layout(pad=0.3)
    return fig


def _montecarlo(d):
    sim, S0, divisa = d.get("simulacion"), d["S0"], d["divisa"]
    p = [ib.apartado(4, "Proyección estocástica del precio",
                     "Simulación de Monte Carlo a doce meses bajo movimiento "
                     "browniano geométrico, con mediana y escenarios extremos.",
                     seccion="Proyección")]
    if not sim:
        p.append(ib.nota("No hay observaciones suficientes para simular."))
        return p

    finales = np.asarray(sim["finales"], dtype=float)
    p.append(ib.destacados([
        ("Partida", ib.moneda(S0, divisa, 2)),
        ("Mediana", ib.moneda(sim.get("mediana_final"), divisa, 2)),
        ("Mejor", ib.moneda(sim.get("mejor_final"), divisa, 2)),
        ("Peor", ib.moneda(sim.get("peor_final"), divisa, 2)),
        ("Prob. de subida", ib.pct(float((finales > S0).mean()), 1, False)),
    ]))
    p.append(ib.espacio(4))
    p.append(ib.figura(_g_mc(sim, S0, divisa)))
    p.append(ib.espacio(4))

    lim = ma.intervalo_confianza(sim["promedio"], sim["error_estandar"])
    izq = [ib.h3("Parámetros de la simulación"),
           ib.ficha([
               ("Simulaciones", ib.num(d["n_sim"], 0)),
               ("Horizonte", "252 sesiones"),
               ("Volatilidad empleada", ib.pct(d.get("sigma"), 2, False)),
               ("Media de las simulaciones", ib.moneda(sim.get("promedio"), divisa)),
               ("Valor teórico", ib.moneda(sim.get("teorico"), divisa)),
               ("Error estándar", ib.moneda(sim.get("error_estandar"), divisa)),
           ], columnas=1, ancho=ib.COLUMNA, color_signo=False)]
    der = [ib.h3("Intervalo de confianza y dispersión"),
           ib.ficha([
               ("Límite inferior del intervalo", ib.moneda(lim[0], divisa)),
               ("Límite superior del intervalo", ib.moneda(lim[1], divisa)),
               ("Retorno mediano",
                ib.pct(float(sim["mediana_final"]) / S0 - 1)),
               ("Retorno del mejor escenario",
                ib.pct(float(sim["mejor_final"]) / S0 - 1)),
               ("Retorno del peor escenario",
                ib.pct(float(sim["peor_final"]) / S0 - 1)),
               ("Recorrido entre extremos",
                ib.moneda(sim["mejor_final"] - sim["peor_final"], divisa)),
           ], columnas=1, ancho=ib.COLUMNA)]
    p.append(ib.dos_columnas(izq, der))

    p.append(ib.h2("Percentiles del precio proyectado"))
    perc = sorted(sim["percentiles"].keys())
    p.append(ib.tabla(
        [[ib.num(sim["percentiles"][q], 2) for q in perc],
         [ib.pct(sim["percentiles"][q] / S0 - 1, 1) for q in perc]],
        [f"P{q}" for q in perc], alineacion=["N"] * len(perc), tamano=7.0))
    p.append(ib.nota(
        "La primera línea recoge el precio y la segunda el retorno implícito "
        "respecto al cierre de partida."))

    fig = _g_convergencia(sim, S0)
    if fig:
        p.append(ib.no_partir(45))
        p.append(ib.figura(fig, pie=
            "La media simulada se estabiliza a medida que se acumulan "
            "trayectorias; su distancia al valor teórico mide el error de "
            "muestreo que queda."))
    p.append(ib.nota(
        "El modelo supone volatilidad constante y retornos independientes entre "
        "sesiones. Ninguno de los dos supuestos se cumple exactamente en el "
        "mercado, de modo que la dispersión debe leerse como una referencia de "
        "magnitud y no como una previsión."))
    return p


# =============================================================================
#  05 · RIESGO
# =============================================================================

def _g_riesgo(retornos, g, confianza):
    fig, (a1, a2) = ib.lienzo(7.0, 2.9, filas=2,
                              gridspec_kw={"height_ratios": [1.35, 1]})
    a1.hist(retornos, bins=80, color=ib.MPL_CORP, alpha=0.70, edgecolor="white",
            linewidth=0.22)
    for clave, color, eti in (("var_hist", ib.MPL_ROJO, "VaR histórico"),
                              ("var_param", ib.MPL_AMBAR, "VaR paramétrico"),
                              ("cvar", "#6E1610", "CVaR")):
        v = g.get(clave)
        if v is not None and np.isfinite(v):
            a1.axvline(v, color=color, linestyle="--", linewidth=1.0,
                       label=f"{eti} {v:+.2%}")
    a1.set_ylabel("Frecuencia")
    a1.set_title(f"Distribución de retornos y umbrales de pérdida al "
                 f"{confianza:.1f} %")
    ib.leyenda(a1)
    cola = retornos[retornos <= g.get("var_hist", -np.inf)]
    if len(cola):
        a2.hist(cola, bins=max(min(len(cola) // 2, 30), 6), color=ib.MPL_ROJO,
                alpha=0.72, edgecolor="white", linewidth=0.25)
        a2.axvline(float(cola.mean()), color="#6E1610", linewidth=1.1,
                   label=f"Media de la cola {cola.mean():+.2%}")
        ib.leyenda(a2)
    a2.set_xlabel("Retorno diario")
    a2.set_ylabel("Frecuencia")
    a2.set_title(f"Cola izquierda: las {len(cola)} peores sesiones")
    fig.tight_layout(pad=0.3)
    return fig


def _riesgo(d, capital):
    hist, divisa, confianza = d["hist"], d["divisa"], d["confianza"]
    g = d.get("riesgo")
    suf = d.get("suficiencia")
    p = [ib.apartado(5, "Valor en riesgo y pérdida esperada en cola",
                     "Pérdida diaria en el umbral de confianza y más allá de "
                     "él, por los métodos histórico y paramétrico.",
                     seccion="Riesgo")]
    if not g:
        p.append(ib.nota("No hay observaciones suficientes."))
        return p

    p.append(ib.destacados([
        ("VaR histórico", ib.pct(g["var_hist"])),
        ("VaR paramétrico", ib.pct(g["var_param"])),
        ("CVaR histórico", ib.pct(g["cvar"])),
        ("Exceso del CVaR", ib.pct(g["cvar"] - g["var_hist"])),
    ]))
    p.append(ib.espacio(5))

    p.append(ib.h2("Impacto sobre la posición"))
    pv = abs(capital * g["var_hist"]) if np.isfinite(g["var_hist"]) else np.nan
    pc = abs(capital * g["cvar"]) if np.isfinite(g["cvar"]) else np.nan
    p.append(ib.parrafo(
        f"Con una inversión de {capital:,.0f} {divisa}, en un día malo —el "
        f"umbral del VaR al {confianza:.1f} % de confianza— la pérdida sería de "
        f"{pv:,.2f} {divisa}. En un día catastrófico, más allá de ese umbral, "
        f"la pérdida media sería de {pc:,.2f} {divisa}."
        .replace(",", " ")))
    p.append(ib.ficha([
        ("Capital considerado", ib.moneda(capital, divisa, 0)),
        ("Pérdida en un día malo", ib.moneda(pv, divisa)),
        ("Pérdida media en la cola", ib.moneda(pc, divisa)),
        ("Nivel de confianza", f"{confianza:.1f} %"),
        ("Pérdida paramétrica",
         ib.moneda(abs(capital * g["var_param"]), divisa)),
        ("Diferencia entre métodos",
         ib.moneda(abs(capital * (g["var_hist"] - g["var_param"])), divisa)),
    ], columnas=2, color_signo=False))

    p.append(ib.espacio(4))
    # La misma serie que dio el VaR: si no, las lineas caen sobre otra distribucion.
    p.append(ib.figura(_g_riesgo(hist["LogReturn"].dropna(), g, confianza)))

    if suf:
        p.append(ib.no_partir(50))
        p.append(ib.h2("Suficiencia muestral"))
        filas = [[v.get("descripcion", k).capitalize(), ib.num(v.get("minimo"), 0),
                  ib.num(suf.get("n"), 0),
                  "Suficiente" if v.get("suficiente") else "INSUFICIENTE"]
                 for k, v in (suf.get("detalle") or {}).items()]
        p.append(ib.tabla(filas,
                          ["Cálculo", "Mínimo exigido", "Disponibles", "Resultado"],
                          anchos=[3, 1.1, 1.1, 1.2],
                          alineacion=["L", "N", "N", "C"]))
        if not suf.get("todo_suficiente"):
            p.append(ib.nota(
                "Los cálculos marcados como insuficientes no se publican en la "
                "aplicación: con esa cantidad de observaciones la cifra "
                "carecería de respaldo estadístico."))
    p.append(ib.nota(
        "El VaR histórico se obtiene del percentil correspondiente de la "
        "distribución observada; el paramétrico supone normalidad, supuesto que "
        "los retornos bursátiles incumplen en las colas. La discrepancia entre "
        "ambos es en sí misma una medida del grosor de esas colas."))
    return p


# =============================================================================
#  06 · RESULTADOS TRIMESTRALES
# =============================================================================

def _g_earnings(ev, sigma_normal):
    if not ev:
        return None
    fig, (a1, a2) = ib.lienzo(7.0, 2.7, columnas=2)
    val = [(e["sorpresa"], e["mov"]) for e in ev
           if e.get("sorpresa") is not None
           and np.isfinite(e.get("sorpresa", np.nan))
           and abs(e["sorpresa"]) <= ma.LIMITE_SORPRESA
           and np.isfinite(e.get("mov", np.nan))]
    if val:
        xs = np.array([v[0] for v in val]); ys = np.array([v[1] for v in val])
        a1.scatter(xs, ys, s=20, color=ib.MPL_CORP, alpha=0.75,
                   edgecolor="white", linewidth=0.4)
        if len(val) >= 3:
            c = np.polyfit(xs, ys, 1)
            rx = np.linspace(xs.min(), xs.max(), 40)
            a1.plot(rx, np.polyval(c, rx), color=ib.MPL_ROJO, linewidth=1.0)
        a1.axhline(0, color=ib.MPL_GRIS, linewidth=0.6)
        a1.axvline(0, color=ib.MPL_GRIS, linewidth=0.6)
    a1.set_xlabel("Sorpresa en beneficio por acción (%)")
    a1.set_ylabel("Movimiento del precio")
    a1.set_title("Sorpresa frente a reacción")

    movs = [e["mov"] for e in ev if np.isfinite(e.get("mov", np.nan))][::-1]
    if movs:
        a2.bar(range(len(movs)), movs,
               color=[ib.MPL_VERDE if v >= 0 else ib.MPL_ROJO for v in movs],
               linewidth=0)
        a2.axhline(0, color="#41474E", linewidth=0.7)
        if sigma_normal and np.isfinite(sigma_normal):
            for s in (1, -1):
                a2.axhline(s * 2 * sigma_normal, color=ib.MPL_GRIS,
                           linestyle="--", linewidth=0.7)
    a2.set_xlabel("Publicaciones, de la más antigua a la más reciente")
    a2.set_ylabel("Movimiento")
    a2.set_title("Reacción en cada publicación")
    fig.tight_layout(pad=0.3)
    return fig


def _g_caminos(cam):
    if not cam or cam.get("caminos") is None or not len(cam["caminos"]):
        return None
    fig, ax = ib.lienzo(7.0, 2.4)
    eje = cam["eje"]
    for fila in cam["caminos"]:
        ax.plot(eje, fila, linewidth=0.5, alpha=0.35, color=ib.MPL_GRIS)
    ax.plot(eje, cam["medio"], color=ib.MPL_CORP, linewidth=1.7,
            label="Trayectoria media")
    ax.axvline(0, color=ib.MPL_ROJO, linestyle="--", linewidth=0.9,
               label="Publicación")
    ax.axhline(0, color=ib.MPL_GRIS, linewidth=0.6)
    ax.set_xlabel("Sesiones respecto a la publicación")
    ax.set_ylabel("Retorno acumulado")
    ax.set_title("Comportamiento del precio alrededor de la publicación")
    ib.leyenda(ax)
    fig.tight_layout(pad=0.3)
    return fig


def _earnings(d):
    datos, cam = d.get("earnings"), d.get("caminos")
    p = [ib.apartado(6, "Reacción a la publicación de resultados",
                     "Sorpresa en beneficio por acción, reacción del precio en "
                     "la sesión de publicación y deriva posterior.",
                     seccion="Resultados")]
    if not datos or not datos.get("eventos"):
        p.append(ib.nota("El proveedor no publica histórico de resultados para "
                         "este activo."))
        return p

    ev = datos["eventos"]
    movs = np.array([e["mov"] for e in ev if np.isfinite(e.get("mov", np.nan))])
    p.append(ib.destacados([
        ("Publicaciones", ib.num(len(ev), 0)),
        ("Movimiento medio", ib.pct(datos.get("mov_medio_earnings"), 2, False)),
        ("Sesión normal", ib.pct(datos.get("mov_medio_normal"), 2, False)),
        ("Extremos", ib.num(datos.get("n_extremos"), 0)),
        ("Tasa de reversión", ib.pct(datos.get("tasa_reversion"), 0, False)),
    ]))
    p.append(ib.espacio(4))
    p.append(ib.figura(_g_earnings(ev, datos.get("sigma_normal"))))
    p.append(ib.espacio(4))

    izq = [ib.h3("Magnitud de la reacción"),
           ib.ficha([
               ("Sigma de sesiones normales",
                ib.pct(datos.get("sigma_normal"), 2, False)),
               ("Movimiento medio en resultados",
                ib.pct(datos.get("mov_medio_earnings"), 2, False)),
               ("Cociente entre ambos", _cociente(
                datos.get("mov_medio_earnings"),
                datos.get("mov_medio_normal"))),
               ("Mayor subida", ib.pct(float(movs.max())) if len(movs) else "—"),
               ("Mayor caída", ib.pct(float(movs.min())) if len(movs) else "—"),
           ], columnas=1, ancho=ib.COLUMNA)]
    der = [ib.h3("Deriva posterior a la publicación"),
           ib.ficha([
               ("Movimientos extremos", ib.num(datos.get("n_extremos"), 0)),
               ("Con ventana completa", ib.num(datos.get("n_con_ventana"), 0)),
               ("Revierten después", ib.num(datos.get("n_revierten"), 0)),
               ("Tasa de reversión",
                ib.pct(datos.get("tasa_reversion"), 0, False)),
               ("Publicaciones al alza",
                ib.pct(float((movs > 0).mean()), 0, False) if len(movs) else "—"),
           ], columnas=1, ancho=ib.COLUMNA)]
    p.append(ib.dos_columnas(izq, der))

    p.append(ib.h2("Histórico de publicaciones"))
    tabla_ev = ma.tabla_earnings(datos)
    if tabla_ev is not None and not tabla_ev.empty:
        p.append(ib.tabla_df(
            tabla_ev,
            formatos={"Publicacion": str, "Momento": str, "Reaccion": str,
                      "Sorpresa EPS": lambda v: ib.num(v, 3),
                      "Movimiento": lambda v: ib.pct(v),
                      "Sigmas": lambda v: ib.num(v, 2),
                      "Percentil": lambda v: ib.num(v, 1),
                      "+5d": lambda v: ib.pct(v), "+10d": lambda v: ib.pct(v),
                      "+20d": lambda v: ib.pct(v), "Clasificacion": str},
            encabezados=["Publicación", "Momento", "Reacción", "Sorpresa BPA",
                         "Movimiento", "σ", "Pct.", "+5d", "+10d", "+20d",
                         "Clasificación"],
            anchos=[1.0, 0.85, 0.95, 0.85, 0.95, 0.55, 0.6, 0.75, 0.75, 0.75, 1.9],
            tamano=6.5,
            alineacion=["L", "L", "L", "N", "N", "N", "N", "N", "N", "N", "L"]))
    p.append(ib.nota(
        f"Se excluyen del ajuste las sorpresas superiores al "
        f"{ma.LIMITE_SORPRESA:.0f} % en valor absoluto: cuando la estimación de "
        f"consenso se aproxima a cero, el porcentaje se dispara y deja de ser "
        f"informativo. Las líneas discontinuas del gráfico marcan dos "
        f"desviaciones típicas de una sesión normal."))
    if datos.get("proximos"):
        p.append(ib.nota("Próxima publicación prevista: "
                         + ", ".join(str(f)[:10] for f in datos["proximos"][:3])
                         + "."))

    fig = _g_caminos(cam)
    if fig:
        p.append(ib.no_partir(55))
        p.append(ib.figura(fig))
        p.append(ib.ficha([
            ("Salto medio en la publicación", ib.pct(cam.get("salto"))),
            ("Retorno al final de la ventana", ib.pct(cam.get("final"))),
            ("Publicaciones representadas", ib.num(len(cam["caminos"]), 0)),
            ("Deriva posterior al salto", _resta(cam.get("final"),
                                                  cam.get("salto"))),
        ], columnas=2))
    return p


# =============================================================================
#  07 · MOVIMIENTOS EXTREMOS
# =============================================================================

def _g_reversion(rev, umbral):
    t = rev.get("tabla")
    if t is None or t.empty:
        return None
    fig, ax = ib.lienzo(7.0, 2.5)
    x = np.arange(len(t)); a = 0.26
    ax.bar(x - a, t["Tras caida"], a, label=f"Tras caída de {umbral:.1f}σ",
           color=ib.MPL_ROJO, linewidth=0)
    ax.bar(x, t["Tras subida"], a, label=f"Tras subida de {umbral:.1f}σ",
           color=ib.MPL_VERDE, linewidth=0)
    ax.bar(x + a, t["Dia cualquiera"], a, label="Sesión cualquiera (tasa base)",
           color=ib.MPL_GRIS, linewidth=0)
    ax.axhline(0, color="#41474E", linewidth=0.7)
    ax.set_xticks(x); ax.set_xticklabels(t["Ventana"])
    ax.set_xlabel("Sesiones después del episodio")
    ax.set_ylabel("Retorno acumulado medio")
    ax.set_title("Comportamiento posterior frente a la tasa base")
    ib.leyenda(ax)
    fig.tight_layout(pad=0.3)
    return fig


def _g_diferencia(rev):
    t = rev.get("tabla")
    if t is None or t.empty:
        return None
    fig, ax = ib.lienzo(7.0, 1.9)
    x = np.arange(len(t))
    dif = t["Diferencia"].to_numpy(dtype=float)
    ax.bar(x, dif, 0.5,
           color=[ib.MPL_VERDE if v >= 0 else ib.MPL_ROJO for v in dif],
           linewidth=0)
    ax.axhline(0, color="#41474E", linewidth=0.7)
    ax.set_xticks(x); ax.set_xticklabels(t["Ventana"])
    ax.set_xlabel("Sesiones después de la caída")
    ax.set_ylabel("Diferencia con la tasa base")
    ax.set_title("Lo que aporta la caída sobre una sesión cualquiera")
    fig.tight_layout(pad=0.3)
    return fig


def _g_tecnicos(tec, divisa):
    df = (tec or {}).get("tabla")
    if df is None or df.empty:
        return None
    fig, (a1, a2) = ib.lienzo(7.0, 2.95, filas=2, sharex=True,
                              gridspec_kw={"height_ratios": [1.75, 1]})
    a1.plot(df.index, df["Close"], color=ib.MPL_CORP, linewidth=0.85,
            label="Cierre")
    if "BandaSuperior" in df:
        a1.plot(df.index, df["BandaSuperior"], color=ib.MPL_GRIS, linewidth=0.6,
                linestyle="--", label="Banda superior")
        a1.plot(df.index, df["BandaInferior"], color=ib.MPL_GRIS, linewidth=0.6,
                linestyle="--", label="Banda inferior")
        a1.fill_between(df.index, df["BandaInferior"], df["BandaSuperior"],
                        color=ib.MPL_GRIS, alpha=0.09)
    if "SMA" in df:
        a1.plot(df.index, df["SMA"], color=ib.MPL_AMBAR, linewidth=0.7,
                label="Media de 20")
    a1.set_ylabel(f"Precio ({divisa})")
    a1.set_title("Bandas de Bollinger")
    ib.leyenda(a1, ncol=2)
    if "RSI" in df:
        a2.plot(df.index, df["RSI"], color=ib.MPL_MORADO, linewidth=0.8)
        a2.axhline(70, color=ib.MPL_ROJO, linestyle="--", linewidth=0.6)
        a2.axhline(30, color=ib.MPL_VERDE, linestyle="--", linewidth=0.6)
        a2.axhline(50, color=ib.MPL_GRIS, linestyle=":", linewidth=0.5)
        a2.fill_between(df.index, 70, df["RSI"], where=df["RSI"] >= 70,
                        color=ib.MPL_ROJO, alpha=0.15)
        a2.fill_between(df.index, df["RSI"], 30, where=df["RSI"] <= 30,
                        color=ib.MPL_VERDE, alpha=0.15)
        a2.set_ylim(0, 100)
    a2.set_ylabel("RSI (14)")
    a2.set_title("Índice de fuerza relativa")
    fig.tight_layout(pad=0.3)
    return fig


def _extremos(d):
    rev, tec = d.get("reversion"), d.get("tecnicos")
    umbral, divisa = d["umbral_sigmas"], d["divisa"]
    p = [ib.apartado(7, "Reversión tras movimientos extremos",
                     "Retorno acumulado en las sesiones posteriores a cada "
                     "movimiento que excedió el umbral de desviaciones típicas, "
                     "contrastado con la tasa base.", seccion="Reversión")]
    if not rev:
        p.append(ib.nota("Se requieren al menos cien retornos para este análisis."))
        return p

    t = rev["tabla"]
    p.append(ib.destacados([
        ("Umbral", f"{umbral:.1f} σ"),
        ("Caídas", ib.num(rev.get("n_caidas"), 0)),
        ("Subidas", ib.num(rev.get("n_subidas"), 0)),
        ("Última sesión", ib.num(rev.get("z_hoy"), 2, " σ")),
        ("Dif. media con la base", ib.pct(rev.get("diferencia_media"))),
    ]))
    p.append(ib.espacio(4))
    p.append(ib.figura(_g_reversion(rev, umbral)))
    p.append(ib.espacio(3))

    p.append(ib.h2("Retorno acumulado posterior por ventana"))
    filas = [[str(f["Ventana"]), ib.pct(f["Tras caida"]), ib.num(f["n_caidas"], 0),
              ib.pct(f["% positivos caida"], 0, False), ib.pct(f["Tras subida"]),
              ib.num(f["n_subidas"], 0), ib.pct(f["Dia cualquiera"]),
              ib.pct(f["% positivos base"], 0, False), ib.pct(f["Diferencia"])]
             for _, f in t.iterrows()]
    p.append(ib.tabla(
        filas,
        ["Ventana", "Tras caída", "n", "% alza", "Tras subida", "n",
         "Sesión cualquiera", "% alza", "Diferencia"],
        anchos=[0.85, 1.05, 0.5, 0.75, 1.05, 0.5, 1.25, 0.75, 1.0],
        tamano=6.9,
        alineacion=["L", "N", "N", "N", "N", "N", "N", "N", "N"]))
    p.append(ib.nota(
        "La columna «Sesión cualquiera» es la tasa base: el retorno acumulado "
        "medio partiendo de una jornada al azar del mismo periodo. La última "
        "columna, la diferencia entre ambas, es la única con contenido "
        "informativo: un retorno posterior del +1 % no describe reacción alguna "
        "si el activo rinde +0,95 % desde cualquier punto de partida."))

    fig = _g_diferencia(rev)
    if fig:
        p.append(ib.espacio(3))
        p.append(ib.figura(fig))

    p.append(ib.no_partir(50))
    p.append(ib.h2("Indicadores técnicos en el episodio"))
    if tec:
        p.append(ib.ficha([
            ("Índice de fuerza relativa (14)", ib.num(tec.get("rsi"), 1)),
            ("Posición en las bandas", ib.num(tec.get("posicion_bb"), 2)),
            ("Distancia a la media de 20", ib.pct(tec.get("dist_sma20"))),
            ("Distancia a la media de 50", ib.pct(tec.get("dist_sma50"))),
            ("Distancia a la media de 200", ib.pct(tec.get("dist_sma200"))),
            ("Racha bajista", _sesiones(tec.get("racha_bajista"))),
        ], columnas=2))
        df = tec.get("tabla")
        if df is not None and not df.empty:
            u = df.iloc[-1]
            p.append(ib.espacio(2))
            p.append(ib.ficha([
                ("Banda superior", ib.moneda(u.get("BandaSuperior"), divisa)),
                ("Media móvil de 20", ib.moneda(u.get("SMA"), divisa)),
                ("Banda inferior", ib.moneda(u.get("BandaInferior"), divisa)),
                ("Media móvil de 50", ib.moneda(u.get("SMA50"), divisa)),
                ("Media móvil de 200", ib.moneda(u.get("SMA200"), divisa)),
                ("Cierre", ib.moneda(u.get("Close"), divisa)),
            ], columnas=2, color_signo=False))
        p.append(ib.espacio(3))
        p.append(ib.figura(_g_tecnicos(tec, divisa)))
        p.append(ib.nota(
            "Ambos indicadores se ofrecen como descripción del estado técnico "
            "en el momento del episodio, no como señal."))
    return p


# =============================================================================
#  08 · VOLUMEN
# =============================================================================

def _g_volumen(vol):
    df = vol.get("datos")
    if df is None or df.empty:
        return None
    fig, (a1, a2) = ib.lienzo(7.0, 3.0, filas=2)
    a1.bar(df.index, df["Volume"], color=ib.MPL_CORP, alpha=0.5, linewidth=0)
    a1.plot(df.index, df["Volume"].rolling(20, min_periods=5).mean(),
            color=ib.MPL_ROJO, linewidth=0.9, label="Media móvil de 20 sesiones")
    a1.set_ylabel("Volumen")
    ib.eje_compacto(a1)
    a1.set_title("Volumen negociado")
    ib.leyenda(a1)
    val = df.dropna(subset=["AbsRetorno", "VolRelativo"])
    if not val.empty:
        a2.scatter(val["VolRelativo"], val["AbsRetorno"], s=8,
                   c=[ib.MPL_VERDE if v >= 0 else ib.MPL_ROJO
                      for v in val["LogReturn"]], alpha=0.55, edgecolor="none")
        if len(val) >= 3:
            c = np.polyfit(val["VolRelativo"], val["AbsRetorno"], 1)
            xs = np.linspace(val["VolRelativo"].min(), val["VolRelativo"].max(), 40)
            a2.plot(xs, np.polyval(c, xs), color=ib.MPL_CORP, linewidth=1.1)
    a2.set_xlabel("Volumen relativo a su media")
    a2.set_ylabel("Retorno absoluto")
    a2.set_title("Volumen frente a magnitud del movimiento")
    fig.tight_layout(pad=0.3)
    return fig


def _volumen(d):
    vol = d.get("volumen")
    p = [ib.apartado(8, "Actividad de negociación",
                     "Relación entre el volumen contratado y la magnitud de los "
                     "retornos diarios.", seccion="Volumen")]
    if not vol:
        p.append(ib.nota("El proveedor no publica volumen para este activo."))
        return p

    p.append(ib.destacados([
        ("Volumen medio", ib.compacto(vol.get("vol_medio"), 1)),
        ("Última sesión", ib.compacto(vol.get("volumen_hoy"), 1)),
        ("Relativo", ib.num(vol.get("vol_relativo_hoy"), 2, " ×")),
        ("Correlación", ib.num(vol.get("correlacion"), 3)),
        ("Extremas", ib.num(vol.get("n_extremos"), 0)),
    ]))
    p.append(ib.espacio(4))
    p.append(ib.figura(_g_volumen(vol)))
    p.append(ib.espacio(4))

    p.append(ib.ficha([
        ("Volumen relativo en subidas", ib.num(vol.get("vol_rel_subidas"), 2, " ×")),
        ("Volumen relativo en bajadas", ib.num(vol.get("vol_rel_bajadas"), 2, " ×")),
        ("Volumen relativo en extremos",
         ib.num(vol.get("vol_rel_extremos"), 2, " ×")),
        ("Sesiones extremas", ib.num(vol.get("n_extremos"), 0)),
        ("Correlación volumen-movimiento", ib.num(vol.get("correlacion"), 3)),
        ("Volumen medio del periodo", ib.compacto(vol.get("vol_medio"), 2)),
    ], columnas=2, color_signo=False))

    df = vol.get("datos")
    if df is not None and not df.empty and "VolRelativo" in df:
        p.append(ib.h2("Retorno condicionado al tramo de volumen"))
        base = df.dropna(subset=["VolRelativo", "LogReturn"])
        tramos = pd.cut(base["VolRelativo"], bins=[0, 0.5, 0.8, 1.2, 2.0, np.inf],
                        labels=["Muy bajo", "Bajo", "Normal", "Alto", "Muy alto"])
        filas = []
        for eti, grupo in base.groupby(tramos, observed=True):
            if not len(grupo):
                continue
            r = grupo["LogReturn"]
            filas.append([str(eti), ib.num(len(grupo), 0), ib.pct(r.mean(), 3),
                          ib.pct(r.abs().mean(), 3, False),
                          ib.pct((r > 0).mean(), 0, False),
                          ib.pct(r.std(), 3, False)])
        p.append(ib.tabla(filas,
                          ["Tramo de volumen", "Sesiones", "Retorno medio",
                           "Movimiento medio", "% al alza", "Desviación"],
                          anchos=[1.5, 1, 1.2, 1.3, 1, 1.1]))
    p.append(ib.nota(
        "Una correlación positiva entre volumen y magnitud del movimiento "
        "indica que las sesiones de mayor actividad son también las de mayor "
        "recorrido, en cualquiera de las dos direcciones. No informa del signo."))
    return p


# =============================================================================
#  09 · SELECCION DE VALORES
# =============================================================================

def _g_seleccion(ep, ventana, referencia):
    ep = np.asarray(ep, dtype=float)
    ep = ep[np.isfinite(ep)]
    if ep.size == 0:
        return None
    fig, (a1, a2) = ib.lienzo(7.0, 2.5, columnas=2,
                              gridspec_kw={"width_ratios": [1.35, 1]})
    a1.hist(ep, bins=max(min(len(ep) // 2, 26), 6), color=ib.MPL_CORP,
            alpha=0.72, edgecolor="white", linewidth=0.3)
    a1.axvline(float(ep.mean()), color=ib.MPL_CORP, linewidth=1.4,
               label=f"Media {ep.mean():+.2%}")
    if referencia is not None and np.isfinite(referencia):
        a1.axvline(referencia, color=ib.MPL_ROJO, linestyle="--", linewidth=1.0,
                   label=f"Índice {referencia:+.2%}")
    a1.axvline(0, color=ib.MPL_GRIS, linewidth=0.6)
    a1.set_xlabel(f"Retorno a {ventana} sesiones tras la caída")
    a1.set_ylabel("Episodios")
    a1.set_title("Distribución del rebote histórico")
    ib.leyenda(a1)
    orden = np.sort(ep)
    a2.plot(orden, np.arange(1, len(orden) + 1) / len(orden),
            color=ib.MPL_CORP, linewidth=1.1)
    a2.axvline(0, color=ib.MPL_GRIS, linewidth=0.6)
    a2.set_xlabel("Retorno posterior")
    a2.set_ylabel("Probabilidad acumulada")
    a2.set_title("Función de distribución")
    fig.tight_layout(pad=0.3)
    return fig


def _g_desenlace(tab, horizontes):
    if tab is None or tab.empty:
        return None
    fig, (a1, a2) = ib.lienzo(7.0, 2.6, columnas=2)
    for i, (_, f) in enumerate(tab.iterrows()):
        ys = [f.get(f"+{h}d", np.nan) for h in horizontes]
        if not np.isfinite(ys).any():
            continue
        a1.plot(horizontes, ys, marker="o", markersize=3, linewidth=1.1,
                color=ib.MPL_SERIE[i % len(ib.MPL_SERIE)],
                label=str(f["Categoría"]))
        ps = [f.get(f"pos{h}", np.nan) for h in horizontes]
        a2.plot(horizontes, ps, marker="o", markersize=3, linewidth=1.1,
                color=ib.MPL_SERIE[i % len(ib.MPL_SERIE)])
    a1.axhline(0, color=ib.MPL_GRIS, linestyle="--", linewidth=0.6)
    a1.set_xticks(list(horizontes))
    a1.set_xlabel("Sesiones después de la caída")
    a1.set_ylabel("Retorno medio acumulado")
    a1.set_title("Desenlace por origen de la caída")
    ib.leyenda(a1, fontsize=5.6)
    a2.axhline(0.5, color=ib.MPL_GRIS, linestyle="--", linewidth=0.6)
    a2.set_xticks(list(horizontes))
    a2.set_xlabel("Sesiones después de la caída")
    a2.set_ylabel("Frecuencia al alza")
    a2.set_title("Proporción de episodios al alza")
    fig.tight_layout(pad=0.3)
    return fig


def _g_factorial(cargas):
    if cargas is None or cargas.empty:
        return None
    fig, ax = ib.lienzo(7.0, max(1.7, 0.30 * len(cargas) + 0.9))
    orden = cargas.sort_values("Carga")
    ax.barh(orden["Factor"], orden["Carga"],
            color=[ib.MPL_CORP if v >= 0 else ib.MPL_ROJO for v in orden["Carga"]],
            linewidth=0)
    ax.axvline(0, color="#41474E", linewidth=0.7)
    ax.set_xlabel("Carga factorial")
    ax.set_title("Exposición de la estrategia a los factores conocidos")
    fig.tight_layout(pad=0.3)
    return fig


def _seleccion(d):
    sel = d.get("seleccion")
    p = [ib.apartado(9, "Contraste estadístico: S&P 500",
                     "El aparato del cribado del S&P 500 aplicado a este "
                     "activo: episodios comparables, contraste múltiple, "
                     "validación fuera de periodo, descomposición factorial, "
                     "régimen y origen de la caída.",
                     seccion="Contraste")]
    if not sel:
        p.append(ib.nota(
            "No ha sido posible obtener el universo del S&P 500, o el activo no "
            "dispone de historia suficiente sobre el calendario del índice, de "
            "modo que este apartado no puede calcularse."))
        return p

    if sel.get("fuera_del_indice"):
        p.append(ib.nota(
            "El activo no forma parte del S&P 500. Los episodios y el rebote "
            "histórico se calculan sobre su propia serie; la referencia del "
            "índice y la clasificación sectorial se toman del universo del "
            "S&P 500 como término de comparación externo."))

    p.append(ib.destacados([
        ("Umbral", f"{sel['umbral']:.1f} σ"),
        ("Episodios", ib.num(sel.get("casos"), 0)),
        ("Rebote medio", ib.pct(sel.get("media"))),
        ("Al alza", ib.pct(sel.get("positivos"), 0, False)),
        ("Ventaja", ib.pct(sel.get("ventaja"))),
    ]))
    p.append(ib.espacio(4))

    izq = [ib.h3("Episodios comparables"),
           ib.ficha([
               ("Sigma diaria del valor", ib.pct(sel.get("sigma"), 2, False)),
               ("Horizonte de evaluación", f"{sel['ventana']} sesiones"),
               ("Episodios localizados", ib.num(sel.get("casos"), 0)),
               ("Rebote medio", ib.pct(sel.get("media"))),
               ("Mediana", ib.pct(sel.get("mediana"))),
               ("Peor episodio", ib.pct(sel.get("peor"))),
               ("Mejor episodio", ib.pct(sel.get("mejor"))),
           ], columnas=1, ancho=ib.COLUMNA)]
    der = [ib.h3("Contraste con la referencia del índice"),
           ib.ficha([
               ("Referencia del índice", ib.pct(sel.get("referencia"))),
               ("Ventaja sobre el índice", ib.pct(sel.get("ventaja"))),
               ("Episodios al alza", ib.pct(sel.get("positivos"), 0, False)),
               ("Figura hoy en la relación",
                "Sí" if sel.get("en_relacion") else "No"),
               ("Valores no obtenidos del índice",
                ib.num(sel.get("ausentes"), 0)),
           ], columnas=1, ancho=ib.COLUMNA)]
    p.append(ib.dos_columnas(izq, der))
    p.append(ib.espacio(3))

    fig = _g_seleccion(sel.get("episodios"), sel["ventana"], sel.get("referencia"))
    if fig:
        p.append(ib.figura(fig))

    # --- contraste multiple
    p.append(ib.no_partir(48))
    p.append(ib.h2("Contraste múltiple"))
    p.append(ib.parrafo(
        "Al examinar quinientas tres sociedades y conservar las que mejor se "
        "comportaron, la selección se realiza sobre los mismos datos con los "
        "que después se mide. El procedimiento de Benjamini-Hochberg controla "
        "la proporción de falsos hallazgos entre los declarados."))
    c = sel.get("contraste") or {}
    p.append(ib.ficha([
        ("Valor p del activo", ib.num(c.get("p"), 4)),
        ("Valor q corregido", ib.num(c.get("q"), 4)),
        ("Supera la corrección",
         "Sí" if c.get("resiste") else ("No" if c.get("q") is not None
                                        else "No aplicable")),
        ("Contrastes simultáneos", ib.num(c.get("contrastes"), 0)),
        ("Supervivientes", ib.num(c.get("supervivientes"), 0)),
        ("Esperados por azar", ib.num(c.get("esperados_por_azar"), 1)),
    ], columnas=2, color_signo=False))
    if c.get("q") is None:
        p.append(ib.nota(
            "El activo no figura en la relación de la sesión analizada —no ha "
            "caído hoy por encima del umbral—, de modo que no entra en la "
            "corrección conjunta. Se ofrece su valor p sin corregir, que no "
            "debe leerse de forma aislada."))

    # --- validacion fuera de periodo
    p.append(ib.no_partir(52))
    p.append(ib.h2("Validación dentro y fuera de periodo"))
    v = sel.get("validacion") or {}
    if v.get("comparable"):
        p.append(ib.parrafo(
            "Los episodios del primer tramo construyen la estadística y los del "
            "segundo la ponen a prueba sin haber intervenido en su cálculo. Se "
            "descartan los episodios cuyo horizonte cruzaría la frontera, por "
            "purga, y un margen equivalente después, por embargo."))
        p.append(ib.ficha([
            ("Tramo de construcción",
             f"{v['inicio_dentro']} a {v['fin_dentro']}"),
            ("Episodios en construcción", ib.num(v.get("n_dentro"), 0)),
            ("Media en construcción", ib.pct(v.get("media_dentro"))),
            ("Tramo de validación",
             f"{v['inicio_fuera']} a {v['fin_fuera']}"),
            ("Episodios en validación", ib.num(v.get("n_fuera"), 0)),
            ("Media en validación", ib.pct(v.get("media_fuera"))),
            ("Purga y embargo", f"{v['purga']} sesiones a cada lado"),
            ("Deterioro", ib.pct(v.get("deterioro"))),
        ], columnas=2))
    else:
        p.append(ib.nota(
            "No hay episodios suficientes en ambos tramos para comparar dentro "
            "y fuera de periodo. Se exigen al menos tres en cada uno."))

    cr = sel.get("cruzada")
    if cr:
        p.append(ib.h3("Estabilidad por pliegues purgados"))
        p.append(ib.tabla_df(
            cr["tabla"],
            formatos={"Pliegue": lambda v: str(int(v)), "Desde": str, "Hasta": str,
                      "Episodios": lambda v: ib.num(v, 0),
                      "Media": lambda v: ib.pct(v),
                      "% en positivo": lambda v: ib.pct(v, 0, False)},
            encabezados=["Pliegue", "Desde", "Hasta", "Episodios", "Media",
                         "% al alza"],
            anchos=[0.7, 1.1, 1.1, 0.9, 1, 1],
            alineacion=["C", "L", "L", "N", "N", "N"]))
        p.append(ib.nota(
            f"Media de los pliegues {cr['media']:+.2%} con dispersión de "
            f"{cr['dispersion']:.2%}. Pliegues con media positiva: "
            f"{cr['positivos']} de {cr['pliegues']}. Una dispersión del orden "
            f"de la media indica que el resultado depende en buena medida del "
            f"periodo examinado."))

    # --- descomposicion factorial
    f = sel.get("factorial")
    if f:
        p.append(ib.no_partir(60))
        p.append(ib.h2("Descomposición factorial de la estrategia"))
        p.append(ib.parrafo(
            "Comprar valores que acaban de desplomarse es, mecánicamente, "
            "cargarse de reversión a corto plazo, de beta elevada y a menudo de "
            "valor. Aquí se reconstruye la cartera histórica que aplica esta "
            "estrategia sobre el índice y se descuenta de ella todo lo que "
            "explican los factores conocidos."))
        p.append(ib.destacados([
            ("Exceso bruto", ib.pct(f["exceso_anual"])),
            ("Explicado", ib.pct(f["explicado_anual"])),
            ("Residuo", ib.pct(f["alfa_anual"])),
            ("Estadístico t", ib.num(f["t_alfa"], 2)),
            ("R² ajustado", ib.pct(f["r2_ajustado"], 1, False)),
        ]))
        p.append(ib.espacio(3))
        p.append(ib.parrafo(f["lectura"]))
        cargas = f.get("cargas")
        if cargas is not None and not cargas.empty:
            p.append(ib.tabla(
                [[str(r["Factor"]), ib.num(r["Carga"], 3), ib.num(r["t"], 2),
                  "Sí" if r["Significativa"] else "No", str(r["Descripción"])]
                 for _, r in cargas.iterrows()],
                ["Factor", "Carga", "t", "|t| ≥ 2", "Qué recoge"],
                anchos=[1.15, 0.65, 0.55, 0.6, 3.6], tamano=6.6,
                alineacion=["L", "N", "N", "C", "L"]))
            p.append(ib.espacio(2))
            p.append(ib.figura(_g_factorial(cargas)))
        p.append(ib.nota(
            f"Factores diarios de la biblioteca de Kenneth French. Periodo "
            f"{f['desde']} a {f['hasta']}, {f['observaciones']:,} sesiones y "
            f"{f['entradas']:,} entradas históricas. Errores estándar de "
            f"Newey-West con {f['retardos']} retardos: al mantener cada "
            f"posición varias sesiones los retornos se solapan, y los errores "
            f"ordinarios inflarían el estadístico t hasta declarar "
            f"significativo un alfa inexistente.".replace(",", " ")))

    # --- regimen
    p.append(ib.no_partir(50))
    p.append(ib.h2("Régimen del valor y de su sector"))
    r = sel.get("regimen") or {}
    if r:
        p.append(ib.parrafo(
            "El régimen se mide con la volatilidad realizada de 21 sesiones "
            "situada en el percentil de la propia historia del valor y "
            "desplazada una sesión, de modo que refleja el estado ANTES de la "
            "caída. Se determina en dos niveles propios del valor —el suyo y el "
            "de su sector—, nunca con un indicador general de mercado: una "
            "utility y una compañía de semiconductores no comparten volatilidad "
            "típica, y clasificarlas con la misma vara produce composiciones "
            "erróneas."))
        p.append(ib.ficha([
            ("Régimen del valor", r.get("estado") or "—"),
            ("Percentil propio", ib.pct(r.get("percentil"), 0, False)),
            ("Régimen del sector", r.get("estado_sector") or "—"),
            ("Percentil sectorial", ib.pct(r.get("percentil_sector"), 0, False)),
        ], columnas=2, color_signo=False))
        des = r.get("desglose")
        if des is not None and not des.empty:
            p.append(ib.espacio(2))
            p.append(ib.tabla_df(
                des[["Régimen", "Episodios", "Media", "% en positivo", "Peor"]],
                formatos={"Régimen": str,
                          "Episodios": lambda v: ib.num(v, 0),
                          "Media": lambda v: ib.pct(v),
                          "% en positivo": lambda v: ib.pct(v, 0, False),
                          "Peor": lambda v: ib.pct(v)},
                encabezados=["Régimen previo", "Episodios", "Rebote medio",
                             "% al alza", "Peor episodio"],
                anchos=[1.5, 1, 1.2, 1, 1.2]))
    else:
        p.append(ib.nota("No hay historia suficiente para situar el régimen."))

    # --- origen
    o = sel.get("origen") or {}
    p.append(ib.no_partir(60))
    p.append(ib.h2("Origen de la caída y desenlace por categoría"))
    p.append(ib.parrafo(
        "Una caída por resultados no es el mismo suceso que una caída por "
        "arrastre del índice, aunque el número sea idéntico. Promediarlas "
        "juntas mezcla poblaciones con desenlaces distintos, de modo que cada "
        "episodio se clasifica por su origen y se mide el desenlace de cada "
        "categoría por separado."))
    if o.get("categoria"):
        p.append(ib.ficha([
            ("Origen clasificado", o.get("categoria")),
            ("Índice esa sesión", ib.pct(o.get("retorno_indice"))),
            ("Sector esa sesión", ib.pct(o.get("retorno_sector"))),
            ("Motivo en prensa", o.get("motivo_prensa") or "—"),
        ], columnas=2))
        if o.get("descripcion"):
            p.append(ib.espacio(2))
            p.append(ib.nota(o["descripcion"]))

    des = o.get("desenlace")
    horizontes = o.get("horizontes", [1, 3, 5, 10, 15])
    if des is not None and not des.empty:
        p.append(ib.espacio(3))
        p.append(ib.h3("Retorno posterior por horizonte"))
        filas = [[str(f["Categoría"]), ib.num(f["Episodios"], 0),
                  ib.pct(f["Caída media"])] +
                 [ib.pct(f.get(f"+{h}d")) for h in horizontes]
                 for _, f in des.iterrows()]
        p.append(ib.tabla(
            filas, ["Origen", "Episodios", "Caída media"] +
            [f"+{h}d" for h in horizontes],
            anchos=[1.85, 0.85, 1] + [0.8] * len(horizontes), tamano=6.8))
        p.append(ib.espacio(2))
        p.append(ib.h3("Frecuencia de episodios al alza"))
        filas = [[str(f["Categoría"])] +
                 [ib.pct(f.get(f"pos{h}"), 0, False) for h in horizontes]
                 for _, f in des.iterrows()]
        p.append(ib.tabla(filas, ["Origen"] + [f"+{h}d" for h in horizontes],
                          anchos=[2.2] + [1] * len(horizontes), tamano=6.8))
        p.append(ib.espacio(3))
        p.append(ib.figura(_g_desenlace(des, horizontes)))
        p.append(ib.nota(
            f"Estadística calculada sobre {o.get('valores_examinados', 0)} "
            f"sociedades con cobertura de fechas de resultados, para que las "
            f"cuatro categorías procedan de la misma población. Si se "
            f"incluyesen los valores sin esas fechas, sus caídas por resultados "
            f"se repartirían sin etiquetar entre las otras tres categorías y "
            f"contaminarían justo la comparación que se pretende hacer. Las "
            f"referencias de índice y de sector sí se calculan sobre el "
            f"universo completo."))

    der = sel.get("deriva")
    if der and der.get("recientes"):
        p.append(ib.no_partir(38))
        p.append(ib.h2("Deriva de la composición del índice"))
        p.append(ib.parrafo(
            f"El historial se calcula sobre las {der['total']} sociedades que "
            f"integran el índice en la fecha actual, que no coinciden con las "
            f"que lo integraban al inicio del periodo. {der['recientes']} de "
            f"ellas ({ib.pct(der['cuota'], 1, False)}) se incorporaron durante "
            f"los últimos {der['anios']} años, y las excluidas en ese intervalo "
            f"no figuran en el cálculo. Ambas circunstancias desplazan el "
            f"retorno histórico posterior en la misma dirección, al alza: la "
            f"exclusión del índice suele seguir a un deterioro pronunciado y la "
            f"incorporación a una revalorización sostenida. La composición "
            f"histórica exacta no está disponible en fuentes gratuitas, de modo "
            f"que el sesgo se documenta pero no se corrige. La comparación "
            f"frente a la referencia del índice resiste mejor que el nivel "
            f"absoluto, porque ambas magnitudes comparten el mismo sesgo."))

    if o.get("titulares"):
        p.append(ib.no_partir(40))
        p.append(ib.h3("Cobertura informativa reciente"))
        p.append(ib.tabla(
            [[str(t.get("Titular", ""))[:170], t.get("Motivo", "—"),
              str(t.get("Fuente", ""))[:22]] for t in o["titulares"][:8]],
            ["Titular", "Asunto", "Fuente"], anchos=[3.9, 1.1, 1],
            tamano=6.7, alineacion=["L", "L", "L"]))
        p.append(ib.nota(
            "Los titulares corroboran la caída actual. No permiten clasificar "
            "el pasado, porque el proveedor solo publica noticias recientes."))
    return p


# =============================================================================
#  10 · OPCIONES Y MICROESTRUCTURA
# =============================================================================

def _g_sonrisa(son):
    if son is None or not isinstance(son, pd.DataFrame) or son.empty:
        return None
    fig, ax = ib.lienzo(7.0, 2.2)
    if "tipo" in son.columns:
        for tipo, color in (("call", ib.MPL_VERDE), ("put", ib.MPL_ROJO)):
            sub = son[son["tipo"] == tipo]
            if not sub.empty:
                ax.plot(sub["moneyness"], sub["impliedVolatility"], "o-",
                        color=color, markersize=2.6, linewidth=0.9, label=tipo)
    else:
        ax.plot(son["moneyness"], son["impliedVolatility"], "o-",
                color=ib.MPL_CORP, markersize=2.6, linewidth=0.9)
    ax.axvline(0, color=ib.MPL_GRIS, linestyle=":", linewidth=0.7)
    ax.set_xlabel("Distancia al precio (moneyness)")
    ax.set_ylabel("Volatilidad implícita")
    ax.set_title("Sonrisa de volatilidad")
    if ax.get_legend_handles_labels()[0]:
        ib.leyenda(ax)
    fig.tight_layout(pad=0.3)
    return fig


def _g_estructura(et):
    if et is None or et.empty:
        return None
    fig, ax = ib.lienzo(7.0, 2.0)
    ax.plot(et["Días"], et["Movimiento implícito"], "o-", color=ib.MPL_CORP,
            markersize=3, linewidth=1.0, label="Movimiento implícito")
    eje2 = ax.twinx()
    eje2.plot(et["Días"], et["Volatilidad implícita"], "s--", color=ib.MPL_AMBAR,
              markersize=2.6, linewidth=0.9, label="Volatilidad implícita")
    eje2.tick_params(labelsize=6.4, colors="#41474E")
    eje2.set_ylabel("Volatilidad implícita", fontsize=6.8, color="#41474E")
    eje2.grid(False)
    ax.set_xlabel("Sesiones hasta el vencimiento")
    ax.set_ylabel("Movimiento implícito")
    ax.set_title("Estructura temporal")
    fig.tight_layout(pad=0.3)
    return fig


def _g_intradia(intra, divisa):
    if intra is None or intra.empty:
        return None
    fig, (a1, a2) = ib.lienzo(7.0, 2.7, filas=2, sharex=True,
                              gridspec_kw={"height_ratios": [1.7, 1]})
    a1.plot(range(len(intra)), intra["Close"], color=ib.MPL_CORP, linewidth=0.7)
    a1.set_ylabel(f"Precio ({divisa})")
    a1.set_title("Cotización intradía de un minuto")
    if "Volume" in intra:
        a2.bar(range(len(intra)), intra["Volume"], color=ib.MPL_GRIS, alpha=0.6,
               linewidth=0)
    a2.set_ylabel("Volumen")
    ib.eje_compacto(a2)
    a2.set_xlabel("Minutos de negociación")
    fig.tight_layout(pad=0.3)
    return fig


def _g_perfil(perfil):
    if perfil is None or not isinstance(perfil, pd.DataFrame) or perfil.empty:
        return None
    cols = list(perfil.columns)
    if len(cols) < 2:
        return None
    fig, ax = ib.lienzo(7.0, 2.4)
    ax.barh(perfil[cols[0]].astype(str), perfil[cols[1]], color=ib.MPL_CORP,
            alpha=0.8, linewidth=0)
    ax.set_xlabel(str(cols[1]))
    ax.set_title("Perfil de volumen por nivel de precio")
    fig.tight_layout(pad=0.3)
    return fig


def _opciones(d):
    m, divisa = d.get("mercado") or {}, d["divisa"]
    p = [ib.apartado(10, "Volatilidad implícita y microestructura",
                     "Movimiento descontado por el mercado a partir del "
                     "straddle en el dinero, asimetría de la volatilidad "
                     "implícita y calidad del flujo intradía.",
                     seccion="Derivados")]
    mov = m.get("movimiento")
    if mov:
        p.append(ib.destacados([
            ("Mov. implícito", ib.pct(mov.get("movimiento_implicito"), 2, False)),
            ("Vol. implícita", ib.pct(mov.get("iv_atm"), 1, False)),
            ("Vencimiento", str(mov.get("vencimiento", "—"))),
            ("Sesiones", ib.num(mov.get("dias"), 0)),
        ]))
        p.append(ib.espacio(4))
        p.append(ib.ficha([
            ("Strike en el dinero", ib.moneda(mov.get("strike_atm"), divisa)),
            ("Precio del straddle", ib.moneda(mov.get("straddle"), divisa)),
            ("Precio de la call", ib.moneda(mov.get("precio_call"), divisa)),
            ("Precio de la put", ib.moneda(mov.get("precio_put"), divisa)),
            ("Interés abierto en calls", ib.num(mov.get("interes_call"), 0)),
            ("Interés abierto en puts", ib.num(mov.get("interes_put"), 0)),
        ], columnas=2, color_signo=False))
        if not mov.get("liquidez_ok"):
            p.append(ib.nota(
                "El interés abierto del strike en el dinero es reducido. Con esa "
                "liquidez, el precio del straddle puede no reflejar el consenso "
                "del mercado."))
    elif not m.get("cadena"):
        # El aviso se ata a la CADENA, no al straddle. Antes bastaba con que
        # fallase el movimiento implicito -por falta de liquidez en el strike
        # en el dinero- para que el apartado dijese que no hay cadena y a
        # renglon seguido publicase su estructura temporal y su interes
        # abierto, contradiciendose en la misma pagina.
        p.append(ib.nota("El proveedor no publica cadena de opciones para este "
                         "activo."))
    else:
        p.append(ib.nota(
            "No ha sido posible calcular el movimiento implícito: el strike en "
            "el dinero carece de precios utilizables. La cadena sí está "
            "disponible y su estructura figura a continuación."))

    et = m.get("estructura")
    if et is not None and not et.empty:
        p.append(ib.h2("Estructura temporal por vencimiento"))
        p.append(ib.tabla_df(
            et, formatos={"Vencimiento": str, "Días": lambda v: ib.num(v, 0),
                          "Movimiento implícito": lambda v: ib.pct(v, 2, False),
                          "Volatilidad implícita": lambda v: ib.pct(v, 1, False),
                          "Interés abierto": lambda v: ib.num(v, 0)},
            anchos=[1.2, 0.8, 1.4, 1.4, 1.2]))
        fig = _g_estructura(et)
        if fig:
            p.append(ib.espacio(2))
            p.append(ib.figura(fig))

    fig = _g_sonrisa(m.get("sonrisa"))
    if fig:
        p.append(ib.no_partir(45))
        p.append(ib.h2("Asimetría de la volatilidad implícita"))
        p.append(ib.figura(fig))
    sg = m.get("sesgo")
    if sg:
        p.append(ib.ficha([
            ("Volatilidad de puts", ib.pct(sg.get("iv_put"), 1, False)),
            ("Volatilidad de calls", ib.pct(sg.get("iv_call"), 1, False)),
            ("Asimetría", ib.pct(sg.get("sesgo"), 2)),
            ("Lectura", str(sg.get("lectura", "—"))),
        ], columnas=2))

    conc = m.get("concentracion")
    if conc is not None and isinstance(conc, pd.DataFrame) and not conc.empty:
        p.append(ib.no_partir(46))
        p.append(ib.h2("Concentración del interés abierto"))
        p.append(ib.parrafo(
            "Contratos vivos por precio de ejercicio. Los strikes donde se "
            "acumula el interés abierto marcan los niveles en los que hay "
            "posición tomada, y la asimetría entre opciones de compra y de "
            "venta indica hacia qué lado está inclinada."))
        fig = _g_interes(conc, (mov or {}).get("spot"))
        if fig:
            p.append(ib.figura(fig))
        p.append(ib.espacio(2))
        p.append(ib.tabla(_filas_interes(conc),
                          ["Precio de ejercicio", "Compras", "Ventas", "Total"],
                          anchos=[1.6, 1, 1, 1], tamano=6.7))

    cal = m.get("calidad")
    if cal:
        p.append(ib.no_partir(40))
        p.append(ib.h2("Calidad del flujo de la sesión"))
        p.append(ib.ficha([(str(k).replace("_", " ").capitalize(),
                            ib.pct(v) if isinstance(v, float) and abs(v) < 10
                            else (ib.num(v, 0) if isinstance(v, (int, float))
                                  else str(v)))
                           for k, v in cal.items()
                           if not isinstance(v, (dict, list, pd.DataFrame))][:10],
                          columnas=2))

    ses = m.get("sesiones")
    if ses is not None and isinstance(ses, pd.DataFrame) and not ses.empty:
        p.append(ib.h2("Distribución del flujo por franja"))
        # Volumenes en notacion abreviada y variaciones en porcentaje: en crudo
        # se leian como "35207175" y "-0.002", que en papel no dicen nada.
        formatos, renombrar = {}, {}
        for c in ses.columns:
            nombre = str(c).lower()
            if "volumen" in nombre:
                formatos[c] = lambda v: ib.compacto(v, 1)
            elif "variacion" in nombre or "variación" in nombre:
                formatos[c] = lambda v: ib.pct(v, 2)
            elif "operaciones" in nombre or "velas" in nombre:
                formatos[c] = lambda v: ib.num(v, 0)
                renombrar[c] = "Minutos con dato"
            elif any(x in nombre for x in ("primero", "ultimo", "último",
                                           "maximo", "minimo")):
                formatos[c] = lambda v: ib.num(v, 2)
            else:
                formatos[c] = str
        cabeceras = [renombrar.get(c, str(c)) for c in ses.columns]
        p.append(ib.tabla_df(ses, formatos=formatos, tamano=6.6, maximo=15,
                             encabezados=cabeceras))
        p.append(ib.nota(
            "La columna de minutos recoge las velas de un minuto con dato, no "
            "el número de operaciones cruzadas. Un volumen de cero en "
            "preapertura o postcierre significa que el proveedor NO publica el "
            "volumen de las sesiones extendidas a esa granularidad, no que no "
            "se haya negociado: los precios de esas velas sí son reales y "
            "varían entre sí."))

    fig = _g_intradia(m.get("intradia"), divisa)
    if fig:
        p.append(ib.no_partir(50))
        p.append(ib.h2("Serie intradía"))
        p.append(ib.figura(fig))
    fig = _g_perfil(m.get("perfil"))
    if fig:
        p.append(ib.espacio(2))
        p.append(ib.figura(fig))
    return p


# =============================================================================
#  11 · COMPARATIVA
# =============================================================================

def _g_comparativa(a, b, tk, ref):
    fig, (a1, a2) = ib.lienzo(7.0, 3.05, filas=2)
    a1.plot(a["Equity_Curve"].index, a["Equity_Curve"], color=ib.MPL_CORP,
            linewidth=1.0, label=tk)
    a1.plot(b["Equity_Curve"].index, b["Equity_Curve"], color=ib.MPL_AMBAR,
            linewidth=1.0, label=ref)
    a1.axhline(1.0, color=ib.MPL_GRIS, linewidth=0.6, linestyle=":")
    a1.set_ylabel("Valor de la cartera (base 1)")
    a1.set_title("Evolución del capital")
    ib.leyenda(a1)
    a2.fill_between(a["Series_Drawdown"].index, a["Series_Drawdown"], 0,
                    color=ib.MPL_CORP, alpha=0.32, label=tk)
    a2.fill_between(b["Series_Drawdown"].index, b["Series_Drawdown"], 0,
                    color=ib.MPL_AMBAR, alpha=0.32, label=ref)
    a2.set_ylabel("Caída desde máximos")
    a2.set_title("Historial de caídas")
    ib.leyenda(a2)
    fig.tight_layout(pad=0.3)
    return fig


def _comparativa(d):
    c, tk, ref = d.get("comparativa"), d["ticker"], d["referencia"]
    p = [ib.apartado(11, "Análisis relativo frente a la referencia",
                     f"Rendimiento ajustado por riesgo de {tk} contra {ref} "
                     f"sobre el periodo común a ambas series.",
                     seccion="Relativo")]
    if not c:
        p.append(ib.nota(
            f"No ha sido posible alinear las series de {tk} y {ref}."))
        return p
    if c.get("aviso_divisa"):
        p.append(ib.nota(c["aviso_divisa"]))

    a, b = c["stats_a"], c["stats_b"]
    p.append(ib.destacados([
        ("Correlación", ib.num(c.get("correlacion"), 3)),
        ("Beta", ib.num(c.get("beta"), 3)),
        ("Sesiones comunes", ib.num(c.get("sesiones"), 0)),
        ("Desde", str(c.get("desde", "—"))),
    ]))
    p.append(ib.espacio(3))
    # La ventana de este apartado NO es la del resto del informe: aqui solo
    # cuentan las sesiones comunes a los dos valores, que suelen ser bastantes
    # mas o bastantes menos. Sin decirlo, el lector compara el retorno
    # anualizado de esta tabla con el del apartado 01 y concluye que hay un
    # error de calculo.
    p.append(ib.parrafo(
        f"Las magnitudes de este apartado se calculan sobre el **periodo común "
        f"a {tk} y {ref}**: {ib.num(c.get('sesiones'), 0)} sesiones desde "
        f"{c.get('desde', '—')}. No coinciden con las del apartado 01, que "
        f"emplea el histórico solicitado del valor "
        f"({ib.num(len(d['hist']), 0)} sesiones). Son ventanas distintas, de "
        f"modo que la discrepancia entre ambas tablas es esperable y no indica "
        f"error de cálculo."))
    p.append(ib.espacio(3))

    filas = [
        ["Retorno anualizado", ib.pct(a["Retorno Anualizado"]),
         ib.pct(b["Retorno Anualizado"]),
         ib.pct(a["Retorno Anualizado"] - b["Retorno Anualizado"])],
        ["Volatilidad anual", ib.pct(a["Volatilidad Anual"], 2, False),
         ib.pct(b["Volatilidad Anual"], 2, False),
         ib.pct(a["Volatilidad Anual"] - b["Volatilidad Anual"])],
        ["Ratio de Sharpe", ib.num(a["Sharpe Ratio"], 3),
         ib.num(b["Sharpe Ratio"], 3),
         ib.num(a["Sharpe Ratio"] - b["Sharpe Ratio"], 3)],
        ["Ratio de Sortino", ib.num(a["Sortino Ratio"], 3),
         ib.num(b["Sortino Ratio"], 3),
         ib.num(a["Sortino Ratio"] - b["Sortino Ratio"], 3)],
        ["Máxima caída", ib.pct(a["Max Drawdown"]), ib.pct(b["Max Drawdown"]),
         ib.pct(a["Max Drawdown"] - b["Max Drawdown"])],
        ["Ratio de Calmar", ib.num(a["Ratio de Calmar"], 3),
         ib.num(b["Ratio de Calmar"], 3),
         ib.num(a["Ratio de Calmar"] - b["Ratio de Calmar"], 3)],
    ]
    sesiones = ib.num(c.get("sesiones"), 0)
    p.append(ib.tabla(filas,
                      [f"Métrica · periodo común ({sesiones} sesiones)",
                       tk, ref, "Diferencia"],
                      anchos=[2.6, 1.1, 1.1, 1.1]))
    p.append(ib.espacio(3))
    p.append(ib.figura(_g_comparativa(a, b, tk, ref)))
    p.append(ib.nota(
        "La curva de capital parte de base 1 en la primera sesión común a "
        "ambas series, de modo que la comparación no depende del precio "
        "nominal de cada activo."))
    return p


# =============================================================================
#  12 · FUNDAMENTALES
# =============================================================================

def _sesiones(v):
    """Numero de sesiones concordando singular y plural."""
    try:
        k = int(float(v))
    except (TypeError, ValueError):
        return "—"
    return f"{k} sesión" if k == 1 else f"{k} sesiones"


def _con_formato(bloque):
    """Aplica la plantilla de formato que declara el motor y retira la columna.

    Varias tablas de fundamentales -multiplos y solvencia- traen una columna
    `formato` con la plantilla de cada fila: veces, porcentaje o importe.
    Volcarlas sin aplicarla imprimia la plantilla literal, «{:,.0f}», junto a
    la cifra en bruto.
    """
    df = _tabla_de(bloque)
    if df is None or "formato" not in df.columns:
        return df
    etiqueta = df.columns[0]
    filas = _filas_multiplos(df)
    return pd.DataFrame(filas, columns=[str(etiqueta), "Valor"])


def _filas_multiplos(tabla):
    """Convierte una tabla con columna `formato` en filas ya compuestas."""
    filas = []
    for _, f in tabla.iterrows():
        valor = f.get("Valor")
        plantilla = str(f.get("formato") or "")
        try:
            numero = float(valor)
        except (TypeError, ValueError):
            numero = np.nan
        if not np.isfinite(numero):
            texto = "—"
        elif "%" in plantilla:
            texto = ib.pct(numero, 2, False)
        elif plantilla.endswith("x"):
            decimales = 2 if ".2f" in plantilla else 1
            texto = f"{numero:,.{decimales}f} ×".replace(",", " ")
        else:
            texto = ib.compacto(numero, 2)
        etiqueta = f.get("Multiplo", f.get("Metrica", ""))
        filas.append([str(etiqueta), texto])
    return filas


def _filas_interes(conc):
    """Interes abierto por strike, con compras y ventas en columnas."""
    piv = conc.pivot_table(index="strike", columns="tipo",
                           values="openInterest", aggfunc="sum").fillna(0)
    piv["total"] = piv.sum(axis=1)
    piv = piv.sort_values("total", ascending=False).head(12).sort_index()
    filas = []
    for strike, f in piv.iterrows():
        filas.append([ib.num(strike, 2),
                      ib.num(f.get("call", 0), 0),
                      ib.num(f.get("put", 0), 0),
                      ib.num(f.get("total", 0), 0)])
    return filas


def _g_interes(conc, spot=None):
    """Interes abierto por precio de ejercicio, compras frente a ventas."""
    if conc is None or conc.empty:
        return None
    piv = conc.pivot_table(index="strike", columns="tipo",
                           values="openInterest", aggfunc="sum").fillna(0)
    if piv.empty:
        return None
    piv = piv.sort_index()
    fig, ax = ib.lienzo(7.0, 2.3)
    x = np.arange(len(piv.index))
    ancho = 0.42
    if "call" in piv:
        ax.bar(x - ancho / 2, piv["call"], ancho, label="Opciones de compra",
               color=ib.MPL_CORP, linewidth=0)
    if "put" in piv:
        ax.bar(x + ancho / 2, piv["put"], ancho, label="Opciones de venta",
               color=ib.MPL_AMBAR, linewidth=0)
    if spot is not None and np.isfinite(spot):
        cerca = int(np.argmin(np.abs(np.asarray(piv.index, dtype=float) - spot)))
        ax.axvline(cerca, color=ib.MPL_ROJO, linestyle="--", linewidth=0.9,
                   label=f"Precio actual {spot:,.2f}".replace(",", " "))
    paso = max(len(piv.index) // 14, 1)
    ax.set_xticks(x[::paso])
    ax.set_xticklabels([f"{v:,.0f}".replace(",", " ")
                        for v in piv.index[::paso]], fontsize=6.0)
    ax.set_xlabel("Precio de ejercicio")
    ax.set_ylabel("Contratos vivos")
    ib.eje_compacto(ax)
    ax.set_title("Interés abierto por precio de ejercicio")
    ib.leyenda(ax)
    fig.tight_layout(pad=0.3)
    return fig


def _cociente(a, b):
    """Division defensiva: `x or 0` deja pasar los NaN en lugar de anularlos."""
    try:
        na, nb = float(a), float(b)
    except (TypeError, ValueError):
        return "—"
    if not (np.isfinite(na) and np.isfinite(nb)) or nb == 0:
        return "—"
    return ib.num(na / nb, 2, " ×")


def _resta(a, b):
    """Diferencia de dos magnitudes, con raya si falta alguna."""
    try:
        na, nb = float(a), float(b)
    except (TypeError, ValueError):
        return "—"
    if not (np.isfinite(na) and np.isfinite(nb)):
        return "—"
    return ib.pct(na - nb)


def _tabla_de(bloque, clave="tabla"):
    if bloque is None:
        return None
    if isinstance(bloque, pd.DataFrame):
        return bloque if not bloque.empty else None
    if isinstance(bloque, dict):
        df = bloque.get(clave)
        if isinstance(df, pd.DataFrame) and not df.empty:
            return df
    return None


def _g_barras_agrupadas(df, x, serie, valor, titulo, eje_y=""):
    """Barras agrupadas a partir de una tabla larga (x, serie, valor)."""
    if df is None or df.empty or not {x, serie, valor}.issubset(df.columns):
        return None
    piv = df.pivot_table(index=x, columns=serie, values=valor, aggfunc="sum")
    if piv.empty:
        return None
    fig, ax = ib.lienzo(7.0, 2.4)
    n = len(piv.columns)
    xs = np.arange(len(piv.index))
    ancho = 0.8 / max(n, 1)
    for i, col in enumerate(piv.columns):
        ax.bar(xs + i * ancho - 0.4 + ancho / 2, piv[col].values, ancho,
               label=str(col), color=ib.MPL_SERIE[i % len(ib.MPL_SERIE)],
               linewidth=0)
    ax.set_xticks(xs)
    ax.set_xticklabels([str(v) for v in piv.index], fontsize=6.2)
    ax.axhline(0, color="#41474E", linewidth=0.6)
    ax.set_ylabel(eje_y)
    ib.eje_compacto(ax)
    ax.set_title(titulo)
    ib.leyenda(ax, ncol=min(n, 4), fontsize=5.8)
    fig.tight_layout(pad=0.3)
    return fig


def _g_cascada(cascada, titulo):
    """Cascada de resultados: etiquetas e importes en tupla."""
    if not cascada or not isinstance(cascada, tuple) or len(cascada) < 2:
        return None
    etiquetas, importes = cascada[0], cascada[1]
    try:
        etiquetas = list(etiquetas); importes = [float(v) for v in importes]
    except Exception:
        return None
    if not etiquetas or len(etiquetas) != len(importes):
        return None
    fig, ax = ib.lienzo(7.0, 2.4)
    colores = [ib.MPL_CORP if v >= 0 else ib.MPL_ROJO for v in importes]
    ax.bar(range(len(importes)), importes, 0.6, color=colores, linewidth=0)
    ax.axhline(0, color="#41474E", linewidth=0.7)
    ax.set_xticks(range(len(etiquetas)))
    ax.set_xticklabels([str(e)[:18] for e in etiquetas], rotation=35,
                       ha="right", fontsize=6.0)
    ib.eje_compacto(ax)
    ax.set_title(titulo)
    fig.tight_layout(pad=0.3)
    return fig


def _fundamentales(d):
    f, divisa = d.get("fundamentales"), d["divisa"]
    p = [ib.apartado(12, "Estados financieros e indicadores fundamentales",
                     "Cuentas presentadas ante la SEC, con los indicadores de "
                     "calidad del beneficio, solvencia y retorno sobre el "
                     "capital.", seccion="Fundamentales")]
    if not f or f.get("no_disponible"):
        p.append(ib.nota((f or {}).get(
            "motivo", "No se han localizado registros en SEC EDGAR para este "
                      "emisor.")))
        return p

    if f.get("es_financiera"):
        p.append(ib.nota(
            "Entidad financiera o vehículo inmobiliario. Varios indicadores "
            "—rotación de existencias, periodo medio de cobro, retorno sobre el "
            "capital invertido— carecen de sentido en este tipo de balance y se "
            "suprimen deliberadamente en lugar de mostrarse mal calculados."))

    marcadores = []
    piot = f.get("piotroski")
    if piot:
        marcadores.append(("Piotroski F-Score",
                           f"{ib.num(piot.get('puntuacion'), 0)}/"
                           f"{ib.num(piot.get('maximo'), 0)}"))
    alt = f.get("altman")
    if alt:
        marcadores.append(("Altman Z-Score", ib.num(alt.get("z"), 2),
                           str(alt.get("zona", ""))[:22]))
    ben = f.get("beneish")
    if ben:
        marcadores.append(("Beneish M-Score", ib.num(ben.get("m"), 2)))
    rat = f.get("ratios")
    if isinstance(rat, dict) and rat.get("roic_actual") is not None:
        marcadores.append(("ROIC", ib.pct(rat.get("roic_actual"), 1, False)))
    if f.get("capitalizacion"):
        marcadores.append(("Capitalización", ib.compacto(f["capitalizacion"], 1)))
    if marcadores:
        p.append(ib.destacados(marcadores))
        p.append(ib.espacio(4))

    if f.get("precio") or f.get("acciones"):
        p.append(ib.ficha([
            ("Último cierre", ib.moneda(f.get("precio"), divisa)),
            ("Acciones en circulación", ib.compacto(f.get("acciones"), 2)),
            ("Capitalización", ib.moneda(f.get("capitalizacion"), divisa, 0)),
            ("Clasificación de negocio",
             str((f.get("clasificacion") or {}).get("sector", "—"))[:34]),
        ], columnas=2, color_signo=False))

    # --- estados financieros
    for clave, titulo in (("resultados", "Cuenta de resultados"),
                          ("balance", "Balance"),
                          ("flujo", "Estado de flujos de efectivo")):
        df = f.get(clave)
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            continue
        p.append(ib.no_partir(55))
        p.append(ib.h2(titulo))
        # El proveedor entrega las partidas en ingles y sin criterio de orden.
        # Aqui se traducen y se colocan segun la cascada contable.
        vista = pc.preparar(df, clave)
        vista.columns = [c.strftime("%Y") if hasattr(c, "strftime") else str(c)
                         for c in vista.columns]
        vista.insert(0, "Partida", [str(i) for i in vista.index])
        cols = list(vista.columns)[:7]
        p.append(ib.tabla_df(
            vista[cols],
            formatos={c: (str if c == "Partida" else ib.compacto) for c in cols},
            anchos=[2.8] + [1] * (len(cols) - 1), tamano=6.4, maximo=34,
            alineacion=["L"] + ["N"] * (len(cols) - 1)))
        p.append(ib.nota(f"Importes en {divisa}, según los registros "
                         f"presentados ante la SEC."))

    # --- graficos de los estados
    for clave, titulo, args in (
            ("composicion_balance", "Composición del balance",
             ("Ejercicio", "Partida", "Importe")),
            ("beneficio_caja", "Beneficio frente a caja generada",
             ("Ejercicio", "Magnitud", "Importe"))):
        df = f.get(clave)
        fig = _g_barras_agrupadas(df, *args, titulo=titulo, eje_y=divisa) \
            if isinstance(df, pd.DataFrame) else None
        if fig:
            p.append(ib.no_partir(45))
            p.append(ib.figura(fig))
    for clave, titulo in (("cascada", "Cascada de la cuenta de resultados"),
                          ("puente_caja", "Puente hasta el flujo de caja libre")):
        fig = _g_cascada(f.get(clave), titulo)
        if fig:
            p.append(ib.no_partir(45))
            p.append(ib.figura(fig))

    # --- bloques con tabla dentro
    mu = f.get("multiplos")
    if isinstance(mu, dict) and isinstance(mu.get("tabla"), pd.DataFrame):
        p.append(ib.no_partir(42))
        p.append(ib.h2("Múltiplos de valoración"))
        p.append(ib.tabla(_filas_multiplos(mu["tabla"]),
                          ["Múltiplo", "Valor"], anchos=[3, 1.4],
                          tamano=6.7, alineacion=["L", "N"]))
        negativos = pd.to_numeric(mu["tabla"].get("Valor"), errors="coerce")
        if negativos is not None and (negativos < 0).any():
            p.append(ib.nota(
                "Los múltiplos negativos corresponden a magnitudes negativas en "
                "el denominador —beneficio, EBITDA o flujo libre— y carecen de "
                "lectura comparativa; se muestran para dejar constancia del "
                "signo."))

    for clave, titulo in (("piotroski", "Detalle del Piotroski F-Score"),
                          ("beneish", "Componentes del Beneish M-Score"),
                          ("calidad", "Calidad del beneficio"),
                          ("ratios", "Retorno sobre el capital invertido"),
                          ("solvencia", "Solvencia y autonomía financiera"),
                          ("crecimiento", "Crecimiento y márgenes"),
                          ("asignacion", "Asignación de capital"),
                          ("consenso", "Consenso de analistas")):
        bloque = f.get(clave)
        df = _con_etiquetas(_con_formato(bloque))
        if df is None or df.empty:
            continue
        p.append(ib.no_partir(42))
        p.append(ib.h2(titulo))
        p.append(ib.tabla_df(df, tamano=6.7, maximo=28))
        if isinstance(bloque, dict):
            if clave == "ratios" and bloque.get("nota_incremental"):
                p.append(ib.nota(str(bloque["nota_incremental"])))
            if clave == "calidad" and bloque.get("alertas"):
                p.append(ib.nota("Alertas: " + "; ".join(
                    str(a) for a in bloque["alertas"][:6])))
            if clave == "solvencia" and bloque.get("autonomia_trimestres"):
                p.append(ib.nota(
                    f"Autonomía estimada: "
                    f"{ib.num(bloque['autonomia_trimestres'], 1)} trimestres "
                    f"con la caja y el flujo libre actuales."))

    # --- tablas ya en DataFrame
    for clave, titulo in (("circulante", "Capital circulante"),
                          ("apalancamiento", "Evolución del apalancamiento"),
                          ("insiders", "Operaciones de iniciados")):
        df = _con_etiquetas(_tabla_de(f.get(clave)))
        if df is None or df.empty:
            continue
        p.append(ib.no_partir(40))
        p.append(ib.h2(titulo))
        p.append(ib.tabla_df(df, tamano=6.7, maximo=26))

    # --- reconciliacion
    rec = f.get("reconciliacion")
    comp = _tabla_de(rec, "comprobaciones")
    if comp is not None:
        p.append(ib.no_partir(45))
        p.append(ib.h2("Conciliación con la fuente primaria"))
        p.append(ib.tabla_df(comp, tamano=6.7, maximo=22))
        if isinstance(rec, dict):
            detalle = []
            if rec.get("acciones") is not None:
                detalle.append(
                    f"Acciones en circulación {ib.compacto(rec['acciones'])} "
                    f"según {rec.get('fuente_acciones', 'la fuente')}"
                    + (f", {rec['acciones_formulario']} de "
                       f"{rec['acciones_fecha']}"
                       if rec.get("acciones_formulario") else ""))
            if rec.get("incidencias"):
                detalle.append("Incidencias: " + "; ".join(
                    str(i) for i in rec["incidencias"][:4]))
            if detalle:
                p.append(ib.nota(" · ".join(detalle) + "."))
        p.append(ib.nota(
            "Se contrastan las cifras del proveedor de mercado contra los "
            "registros presentados ante la SEC. Las discrepancias se muestran "
            "en lugar de ocultarse."))

    asig = f.get("asignacion")
    if isinstance(asig, dict) and asig.get("dilucion_acumulada") is not None:
        p.append(ib.ficha([
            ("Dilución acumulada", ib.pct(asig.get("dilucion_acumulada"))),
            ("Recompras del periodo", ib.compacto(asig.get("total_recompras"), 1)),
        ], columnas=2))

    dcf = f.get("dcf")
    dcf_tabla = _tabla_de(dcf)
    if dcf_tabla is not None:
        p.append(ib.no_partir(42))
        p.append(ib.h2("Descuento de flujos inverso"))
        p.append(ib.parrafo(
            "Qué tasa de crecimiento del flujo de caja libre habría que suponer "
            "para justificar la capitalización actual. No es una valoración: es "
            "la lectura inversa de la que ya hace el mercado."))
        p.append(ib.tabla_df(dcf_tabla, tamano=6.8, maximo=18))
    elif isinstance(dcf, dict) and dcf.get("crecimiento_implicito") is not None:
        p.append(ib.h2("Descuento de flujos inverso"))
        p.append(ib.ficha([
            ("Crecimiento anual implícito",
             ib.pct(dcf.get("crecimiento_implicito"), 1, False)),
            ("Coste de capital supuesto", ib.pct(dcf.get("wacc"), 1, False)),
        ], columnas=2))

    cob = f.get("cobertura")
    if isinstance(cob, pd.DataFrame) and not cob.empty:
        p.append(ib.no_partir(45))
        p.append(ib.h2("Cobertura de los módulos de análisis"))
        p.append(ib.tabla_df(cob, tamano=6.3, maximo=60,
                             anchos=[0.55, 2.1, 0.9, 3.4],
                             alineacion=["C", "L", "C", "L"]))
    return p


# =============================================================================
#  13 · SEGMENTOS
# =============================================================================

def _con_etiquetas(df):
    """Asciende el indice a primera columna cuando ahi viven los nombres.

    Los motores devuelven unas tablas con la etiqueta en una columna y otras
    con la etiqueta en el indice. El desglose por linea de negocio es de las
    segundas: sus nombres de segmento estaban en el indice y la primera columna
    era ya un importe. Al no contemplarlo, la tabla del informe salia sin los
    nombres -pura columna de cifras sin saber a que corresponden- y el grafico
    intentaba rotular el eje con importes, lo que ademas reventaba.
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return df
    if isinstance(df.index, pd.RangeIndex):
        return df
    if pd.api.types.is_numeric_dtype(df.index):
        return df.reset_index(drop=True)
    vista = df.copy()
    nombre = df.index.name or "Concepto"
    vista.insert(0, str(nombre), [str(i) for i in df.index])
    return vista.reset_index(drop=True)


# Mismo criterio que la pantalla: por encima de este desvio entre la suma de
# las partes y el total declarado, el desglose NO se representa. La aplicacion
# ya lo aplicaba y el informe no, de modo que el papel publicaba repartos que
# la pantalla se negaba a dibujar -hasta un 100 % de desvio- y ademas calculaba
# los pesos sobre la suma de las partes, con lo que sumaban 100 % aunque solo
# cubriesen la mitad de la cifra de negocio.
LIMITE_FIABLE = 0.25


def _cuadre_peor(paquete):
    """Mayor desvio entre la suma de las partes y el total declarado."""
    if not isinstance(paquete, dict):
        return None
    cuadre = paquete.get("cuadre")
    if not isinstance(cuadre, pd.DataFrame) or cuadre.empty:
        return None
    peor = pd.to_numeric(cuadre.get("Desvio"), errors="coerce").abs().max()
    return float(peor) if peor is not None and np.isfinite(peor) else None


def _aviso_cuadre(p, peor, sustantivo="las partes"):
    """Advertencia graduada segun lo lejos que quede el desglose de su total."""
    if peor is None:
        return True
    if peor < 1e-6:
        p.append(ib.nota(
            f"La suma de {sustantivo} coincide exactamente con el total "
            f"consolidado declarado en el expediente, en todos los periodos."))
        return True
    if peor < 0.01:
        p.append(ib.nota(
            f"La suma de {sustantivo} cuadra con el total declarado dentro de "
            f"un {peor:.3%}."))
        return True
    if peor < LIMITE_FIABLE:
        p.append(ib.nota(
            f"La suma de {sustantivo} se desvía hasta un {peor:.2%} del total "
            f"declarado. Suele deberse a partidas residuales que la sociedad no "
            f"asigna a ningún bloque. Los pesos relativos son orientativos y no "
            f"cuadran al céntimo."))
        return True
    p.append(ib.nota(
        f"DESGLOSE NO REPRESENTABLE. La suma de {sustantivo} se desvía un "
        f"{peor:.1%} del total declarado, muy por encima de lo tolerable: el "
        f"desglose mezcla dimensiones o niveles que no ha sido posible separar "
        f"de forma automática. No se publican ni los pesos ni el gráfico, "
        f"porque darían una apariencia de precisión que el dato no tiene. Los "
        f"importes en bruto se conservan para poder contrastarlos con el "
        f"expediente original."))
    return False


def _g_segmento(tabla, titulo, moneda="USD"):
    """Barras horizontales del ultimo periodo disponible del desglose."""
    if tabla is None or not isinstance(tabla, pd.DataFrame) or tabla.empty:
        return None
    columna = tabla.columns[0]
    serie = pd.to_numeric(tabla[columna], errors="coerce").dropna()
    serie = serie[serie != 0]
    if len(serie) < 2:
        return None
    serie = serie.sort_values()
    fig, ax = ib.lienzo(7.0, max(1.6, 0.30 * len(serie) + 0.85))
    ax.barh([str(i)[:34] for i in serie.index], serie.values,
            color=[ib.MPL_CORP if v >= 0 else ib.MPL_ROJO for v in serie.values],
            linewidth=0)
    ax.axvline(0, color="#41474E", linewidth=0.6)
    ax.set_xlabel(f"Importe ({moneda}) · {columna}")
    ib.eje_compacto(ax, "x")
    ax.set_title(titulo)
    fig.tight_layout(pad=0.3)
    return fig


def _tabla_partes(tabla, moneda="USD", maximo=7, con_derivados=True):
    """Convierte el desglose por bloque en filas ya formateadas.

    Las columnas son periodos y el indice, los bloques.

    Con `con_derivados` se anaden el peso sobre el total del ultimo periodo y la
    variacion interanual. Se omiten cuando el desglose no cuadra con su total
    declarado: un peso calculado sobre una suma que no es la real es una cifra
    falsa, por mucho que los porcentajes sumen 100 entre ellos.
    """
    if tabla is None or not isinstance(tabla, pd.DataFrame) or tabla.empty:
        return None, None
    columnas = list(tabla.columns)[:maximo]
    ultimo = columnas[0]
    total = pd.to_numeric(tabla[ultimo], errors="coerce").abs().sum()
    filas = []
    for bloque in tabla.index:
        fila = [str(bloque)[:38]]
        for c in columnas:
            fila.append(ib.compacto(tabla.loc[bloque, c], 2))
        if con_derivados:
            valor = pd.to_numeric(pd.Series([tabla.loc[bloque, ultimo]]),
                                  errors="coerce").iloc[0]
            fila.append(ib.pct(abs(valor) / total, 1, False)
                        if total and np.isfinite(valor) else "—")
            if len(columnas) > 1:
                previo = pd.to_numeric(
                    pd.Series([tabla.loc[bloque, columnas[1]]]),
                    errors="coerce").iloc[0]
                fila.append(ib.pct(valor / previo - 1)
                            if previo and np.isfinite(previo)
                            and np.isfinite(valor) and previo != 0 else "—")
        filas.append(fila)
    cabecera = ["Bloque"] + [str(c) for c in columnas]
    if con_derivados:
        cabecera.append("Peso")
        if len(columnas) > 1:
            cabecera.append("Variación")
    return filas, cabecera


def _bloque_desglose(p, paquete, titulo, moneda):
    """Compone un desglose completo: metrica, tabla, cuadre y grafico."""
    if not isinstance(paquete, dict):
        return False
    partes = paquete.get("partes")
    if not isinstance(partes, pd.DataFrame) or partes.empty:
        return False

    peor = _cuadre_peor(paquete)
    fiable = peor is None or peor < LIMITE_FIABLE

    p.append(ib.no_partir(52))
    p.append(ib.h2(titulo))
    metrica = paquete.get("metrica")
    seleccion = paquete.get("seleccion")
    if metrica:
        p.append(ib.nota(
            f"Magnitud desglosada: {metrica}. Bloques incluidos: "
            f"{seleccion or 'todos'}. Referencia de cuadre: "
            f"{paquete.get('origen_referencia', 'no declarada')}."))

    # Sin cuadre fiable no se publican ni el peso ni la variacion: serian
    # porcentajes calculados sobre una base que no es la real.
    filas, cabecera = _tabla_partes(partes, moneda, con_derivados=fiable)
    if filas:
        ancho = [2.2] + [1] * (len(cabecera) - 1)
        p.append(ib.tabla(filas, cabecera, anchos=ancho, tamano=6.6,
                          alineacion=["L"] + ["N"] * (len(cabecera) - 1)))

    cuadre = paquete.get("cuadre")
    if isinstance(cuadre, pd.DataFrame) and not cuadre.empty:
        p.append(ib.espacio(2))
        p.append(ib.h3("Cuadre con el total declarado"))
        p.append(ib.tabla(
            [[str(f["Periodo"]), ib.compacto(f["Suma de las partes"], 2),
              ib.compacto(f["Total declarado"], 2), ib.pct(f["Desvio"], 3)]
             for _, f in cuadre.iterrows()],
            ["Periodo", "Suma de las partes", "Total declarado", "Desvío"],
            anchos=[1.4, 1.3, 1.3, 1], tamano=6.6))
    _aviso_cuadre(p, peor, "los bloques")

    if fiable:
        fig = _g_segmento(partes, titulo, moneda)
        if fig:
            p.append(ib.espacio(2))
            p.append(ib.figura(fig))
    return True


def _segmentos(d):
    s = d.get("segmentos")
    moneda = d.get("divisa", "USD")
    p = [ib.apartado(13, "Desglose por segmento y geografía",
                     "Descomposición de la cifra de negocio por línea de "
                     "actividad y por área geográfica, según el desglose "
                     "presentado ante la SEC.", seccion="Segmentos")]
    if not s or s.get("no_disponible"):
        return None

    hubo = False
    for clave, titulo in (("negocio", "Por línea de negocio"),
                          ("producto", "Por producto o servicio")):
        if _bloque_desglose(p, s.get(clave), titulo, moneda):
            hubo = True

    # --- geografia
    geo = s.get("geografia")
    tabla_geo = _tabla_de(geo)
    if tabla_geo is not None:
        hubo = True
        p.append(ib.no_partir(50))
        p.append(ib.h2("Por área geográfica"))
        if isinstance(geo, dict) and geo.get("periodo"):
            detalle = geo.get("detalle") or {}
            p.append(ib.nota(
                f"Periodo: {geo['periodo']}. Magnitud desglosada: "
                f"{detalle.get('metrica', 'no declarada')}."))
        # La COBERTURA se mide contra el total que declara la propia sociedad,
        # no contra la suma de las areas listadas. El motor calcula el peso
        # sobre esa suma, de modo que siempre da 100 % aunque las areas cubran
        # la mitad de la cifra de negocio: en la muestra auditada habia casos
        # con un 60 % de cobertura y pesos que sumaban 100 %.
        importes = pd.to_numeric(tabla_geo["Importe"], errors="coerce")
        suma = float(importes.sum())
        declarado = _total_declarado(geo)
        cobertura = suma / declarado if declarado else None
        fiable_geo = cobertura is None or abs(cobertura - 1) < LIMITE_FIABLE

        filas = []
        for _, f in tabla_geo.iterrows():
            fila = [str(f.get("Area", ""))[:34], str(f.get("ISO3") or "—"),
                    "País" if f.get("Es pais") else "Agregado",
                    ib.compacto(f.get("Importe"), 2)]
            if fiable_geo:
                # El peso se recalcula sobre el TOTAL DECLARADO cuando se
                # conoce, no sobre la suma de lo listado.
                base = declarado or suma
                valor = pd.to_numeric(pd.Series([f.get("Importe")]),
                                      errors="coerce").iloc[0]
                fila.append(ib.pct(valor / base, 1, False)
                            if base and np.isfinite(valor) else "—")
            filas.append(fila)
        cabecera = ["Área", "ISO", "Naturaleza", "Importe"]
        anchos = [2.4, 0.7, 1, 1.3]
        alin = ["L", "C", "L", "N"]
        if fiable_geo:
            cabecera.append("Peso"); anchos.append(0.9); alin.append("N")
        p.append(ib.tabla(filas, cabecera, anchos=anchos, tamano=6.6,
                          alineacion=alin))

        if cobertura is not None:
            p.append(ib.tabla(
                [[ib.compacto(suma, 2), ib.compacto(declarado, 2),
                  ib.pct(cobertura, 1, False), ib.pct(cobertura - 1, 1)]],
                ["Suma de las áreas", "Total declarado", "Cobertura",
                 "Desvío"], anchos=[1.3, 1.3, 1, 1], tamano=6.6))
        _aviso_cuadre(p, None if cobertura is None else abs(cobertura - 1),
                      "las áreas")
        if cobertura is not None and fiable_geo and abs(cobertura - 1) >= 0.01:
            p.append(ib.nota(
                f"Los pesos se calculan sobre el total declarado por la "
                f"sociedad, no sobre la suma de las áreas relacionadas, de modo "
                f"que suman {ib.pct(cobertura, 1, False)} y no el 100 %: la "
                f"diferencia corresponde a la parte que el emisor no asigna a "
                f"ninguna región."))
        p.append(ib.nota(
            "Las etiquetas que el emisor publica como agregados regionales no "
            "se reparten entre países: se conservan tal cual figuran en el "
            "expediente."))

        if fiable_geo:
            fig = _g_geografia(tabla_geo, moneda)
            if fig:
                p.append(ib.espacio(2))
                p.append(ib.figura(fig))

    # --- margenes
    mar = _tabla_de(s.get("margenes"))
    if mar is not None:
        hubo = True
        p.append(ib.no_partir(42))
        p.append(ib.h2("Márgenes por segmento"))
        filas = [[str(f.get("Segmento", ""))[:34],
                  ib.compacto(f.get("Ingresos"), 2),
                  ib.compacto(f.get("Resultado operativo"), 2),
                  ib.pct(f.get("Margen operativo"), 1, False)]
                 for _, f in mar.iterrows()]
        p.append(ib.tabla(filas,
                          ["Segmento", "Ingresos", "Resultado operativo",
                           "Margen operativo"],
                          anchos=[2.2, 1.2, 1.4, 1.2], tamano=6.6))

    # --- evolucion
    evo = s.get("evolucion")
    crec = evo.get("crecimiento") if isinstance(evo, dict) else None
    if isinstance(crec, pd.DataFrame) and not crec.empty:
        hubo = True
        p.append(ib.no_partir(40))
        p.append(ib.h2("Crecimiento por bloque"))
        p.append(ib.tabla(
            [[str(f["Bloque"])[:34], str(f["Periodo"]),
              ib.pct(f["Crecimiento"], 1)] for _, f in crec.iterrows()],
            ["Bloque", "Periodo", "Variación interanual"],
            anchos=[2.4, 1.4, 1.4], tamano=6.6,
            alineacion=["L", "L", "N"]))

    if not hubo:
        # Un apartado sin contenido resta mas de lo que suma: se omite entero y
        # su ausencia queda anotada en la relacion de incidencias del cierre.
        return None
    if s.get("aviso"):
        p.append(ib.nota(str(s["aviso"])))
    return p


def _total_declarado(geo):
    """Total consolidado que la sociedad declara en el propio expediente."""
    if not isinstance(geo, dict):
        return None
    det = (geo.get("detalle") or {}).get("tabla")
    if not isinstance(det, pd.DataFrame) or det.empty:
        return None
    for etiqueta in det.index:
        if "consolidad" in str(etiqueta).lower():
            valor = pd.to_numeric(pd.Series([det.loc[etiqueta].iloc[0]]),
                                  errors="coerce").iloc[0]
            return float(valor) if np.isfinite(valor) else None
    return None


def _g_geografia(tabla, moneda):
    """Barras del reparto geografico, de mayor a menor peso."""
    if tabla is None or tabla.empty or "Importe" not in tabla:
        return None
    datos = tabla.copy()
    datos["Importe"] = pd.to_numeric(datos["Importe"], errors="coerce")
    datos = datos.dropna(subset=["Importe"]).sort_values("Importe")
    if len(datos) < 2:
        return None
    fig, ax = ib.lienzo(7.0, max(1.5, 0.30 * len(datos) + 0.8))
    ax.barh([str(a)[:30] for a in datos["Area"]], datos["Importe"],
            color=ib.MPL_CORP, alpha=0.88, linewidth=0)
    ax.set_xlabel(f"Importe ({moneda})")
    ib.eje_compacto(ax, "x")
    ax.set_title("Reparto por área geográfica")
    fig.tight_layout(pad=0.3)
    return fig


# =============================================================================
#  14 · NOTAS Y FUENTES
# =============================================================================

FUENTES = [
    ["Yahoo Finance", "Cotizaciones diarias e intradía, volumen, cadena de "
                      "opciones, resultados trimestrales y titulares", "Público"],
    ["SEC EDGAR", "Estados financieros presentados y desglose por segmentos de "
                  "negocio y geografía", "Público"],
    ["Kenneth French Data Library", "Factores de riesgo diarios empleados en la "
                                    "descomposición factorial", "Público"],
    ["Fuentes públicas de índices", "Composición del S&P 500 y clasificación "
                                    "sectorial GICS", "Público"],
]

CRITERIOS = [
    ("Toda cifra contra su tasa base",
     "Ningún retorno se presenta aislado. La comparación con lo que ocurre sin "
     "condicionamiento previo precede siempre a la lectura: un rebote del +1 % "
     "no describe nada si el activo rinde +0,95 % desde cualquier punto."),
    ("El tamaño de muestra siempre visible",
     "El número de episodios sobre el que descansa cada media acompaña a la "
     "media, con umbrales mínimos por debajo de los cuales no se publica "
     "resultado alguno."),
    ("Anualización sobre 252 sesiones",
     "Ninguna magnitud se anualiza con 365 días naturales. Se emplean las 252 "
     "sesiones bursátiles del año en todo el documento."),
    ("Las limitaciones se declaran",
     "Los sesgos metodológicos conocidos, las carencias de la fuente de datos y "
     "las muestras insuficientes se comunican de forma expresa, no se omiten."),
    ("Descriptivo, nunca prescriptivo",
     "El documento recoge el comportamiento registrado en el pasado. No formula "
     "previsiones ni recomendaciones de compra o de venta, y el lenguaje se "
     "mantiene neutral de forma deliberada."),
]


def _cierre(d):
    p = [ib.apartado(14, "Metodología, fuentes y advertencias",
                     seccion="Metodología")]
    p.append(ib.h2("Criterios metodológicos"))
    p.append(ib.tabla([[t, x] for t, x in CRITERIOS], ["Criterio", "Alcance"],
                      anchos=[1.5, 3.5], tamano=7.0,
                      alineacion=["L", "L"]))
    p.append(ib.h2("Fuentes de datos"))
    p.append(ib.tabla(FUENTES, ["Fuente", "Contenido", "Acceso"],
                      anchos=[1.5, 3.4, 0.8], tamano=7.0,
                      alineacion=["L", "L", "C"]))

    inc = d.get("incidencias") or []
    if inc:
        p.append(ib.h2("Incidencias durante la generación"))
        p.append(ib.parrafo(
            "Las consultas siguientes no han devuelto datos, o los han devuelto "
            "con una limitación que afecta a las cifras. Los apartados a los "
            "que les faltan datos lo indican en su lugar correspondiente. Se relacionan "
            "aquí para que quede constancia de qué falta y por qué, en lugar de "
            "que el documento aparente estar completo."))
        p.append(ib.tabla([[t] for t in inc], ["Consulta"], anchos=[1],
                          tamano=6.8, alineacion=["L"]))

    p.append(ib.espacio(10))
    p.append(ib.nota(
        "AVISO LEGAL. Este documento se ha generado mediante una herramienta de "
        "análisis cuantitativo descriptivo. Todas las magnitudes se calculan "
        "sobre datos históricos procedentes de fuentes públicas y describen el "
        "comportamiento pasado del activo analizado. No constituyen previsión, "
        "asesoramiento financiero ni recomendación de inversión de ningún tipo. "
        "El comportamiento pasado no garantiza resultados futuros. El "
        "destinatario es responsable de las decisiones que adopte."))
    return p


# =============================================================================
#  PUNTO DE ENTRADA
# =============================================================================

def generar(ticker, periodo="5y", confianza=99.0, capital=100000,
            umbral_sigmas=2.0, ventana_rebote=15, referencia="SPY",
            n_sim=10000, intervalo="1d", periodo_grafico="1y",
            incluir_seleccion=True, incluir_fundamentales=True, datos=None):
    """Construye el informe completo y lo devuelve como bytes de un PDF A4."""
    import informe_datos
    import motor_grafico as gr

    if datos is None:
        datos = informe_datos.recopilar(
            ticker, periodo=periodo, confianza=confianza,
            umbral_sigmas=umbral_sigmas, ventana_rebote=ventana_rebote,
            referencia=referencia, n_sim=n_sim, intervalo=intervalo,
            periodo_grafico=periodo_grafico,
            incluir_seleccion=incluir_seleccion,
            incluir_fundamentales=incluir_fundamentales)

    datos["intervalo_etiqueta"] = gr.INTERVALOS.get(
        datos["intervalo"], (datos["intervalo"],))[0]
    fecha_datos = datos["hist"].index[-1].strftime("%d/%m/%Y")

    destino = io.BytesIO()
    doc = _Documento(destino, datos["ticker"], datos["nombre"],
                     datos["divisa"], fecha_datos)

    piezas = _portada(datos)
    piezas.append(NextPageTemplate("interior"))
    piezas.append(PageBreak())

    apartados = [
        _resumen(datos), _grafico(datos), _precio(datos), _montecarlo(datos),
        _riesgo(datos, capital), _earnings(datos), _extremos(datos),
        _volumen(datos), _seleccion(datos), _opciones(datos),
        _comparativa(datos), _fundamentales(datos), _segmentos(datos),
        _cierre(datos),
    ]
    from reportlab.platypus import CondPageBreak
    # Un apartado puede devolver None cuando no tiene nada que contar: se
    # omite entero en lugar de imprimir una pagina en blanco. Su ausencia
    # queda anotada en la relacion de incidencias del cierre.
    for i, bloque in enumerate([x for x in apartados if x]):
        if i:
            # Un apartado no abre hoja nueva por sistema: eso dejaba la mitad
            # inferior de casi todas las paginas en blanco y el documento
            # parecia sin terminar. Solo salta si no caben el encabezado y un
            # primer bloque de contenido con holgura.
            piezas.append(CondPageBreak(75 * mm))
            piezas.append(Spacer(1, 7))
        piezas.extend(bloque)

    doc.build(piezas)
    return destino.getvalue()
