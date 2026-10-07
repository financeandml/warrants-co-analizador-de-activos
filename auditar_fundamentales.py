"""Auditoria de INTEGRIDAD de los fundamentales sobre una muestra de empresas.

No comprueba que el programa no se caiga: comprueba que las cifras que publica
son ciertas. Para cada empresa recalcula por su cuenta lo que el motor afirma y
contrasta ambos resultados, y busca ademas los tres vicios que delatan un
volcado descuidado:

    REPETICION   la misma cifra en ejercicios distintos, que casi siempre
                 significa que una columna se ha copiado sobre otra.
    INVENCION    una cifra que no se deduce de los estados de los que dice
                 proceder.
    INCOHERENCIA un porcentaje que no cuadra con sus propios importes, un
                 desglose que no suma su total, un ejercicio imposible.

Uso:  python auditar_fundamentales.py [n_empresas]
"""

import sys
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

import motor_fundamentales as mf
import motor_segmentos as ms

TOLERANCIA = 0.005          # 0,5 % de desvio admitido al recalcular
INCIDENCIAS = []


def anotar(ticker, gravedad, bloque, detalle):
    INCIDENCIAS.append({"Ticker": ticker, "Gravedad": gravedad,
                        "Bloque": bloque, "Detalle": detalle})


def _num(x):
    try:
        v = float(x)
        return v if np.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _cerca(a, b, tol=TOLERANCIA):
    a, b = _num(a), _num(b)
    if a is None or b is None:
        return None
    if b == 0:
        return abs(a) < 1e-6
    return abs(a / b - 1) <= tol


# =============================================================================
#  1 · ESTADOS: columnas repetidas y ejercicios imposibles
# =============================================================================

def revisar_estados(tk, estados):
    for clave, nombre in (("resultados", "cuenta de resultados"),
                          ("balance", "balance"), ("flujo", "flujo de caja")):
        df = estados.get(clave)
        if df is None or df.empty:
            continue

        # Ejercicios plausibles
        for c in df.columns:
            anio = None
            try:
                anio = pd.to_datetime(c).year
            except Exception:
                try:
                    anio = int(c)
                except (TypeError, ValueError):
                    pass
            if anio is not None and not (1990 <= anio <= 2100):
                anotar(tk, "ALTA", nombre, f"ejercicio imposible: {c}")

        # Columnas identicas: una copia disfrazada de ejercicio distinto
        cols = list(df.columns)
        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                a = pd.to_numeric(df[cols[i]], errors="coerce")
                b = pd.to_numeric(df[cols[j]], errors="coerce")
                comunes = a.notna() & b.notna()
                if comunes.sum() >= 5 and (a[comunes] == b[comunes]).all():
                    anotar(tk, "ALTA", nombre,
                           f"ejercicios {cols[i]} y {cols[j]} tienen valores "
                           f"identicos en las {int(comunes.sum())} partidas comunes")

        # Filas duplicadas con el mismo nombre
        repetidas = pd.Index(df.index).duplicated().sum()
        if repetidas:
            anotar(tk, "MEDIA", nombre, f"{repetidas} partidas repetidas en el indice")


# =============================================================================
#  2 · RATIOS: se recalculan desde los estados
# =============================================================================

def _serie(df, nombres):
    for n in nombres:
        if n in df.index:
            s = pd.to_numeric(df.loc[n], errors="coerce")
            if s.notna().any():
                return s
    return None


def revisar_margenes(tk, estados, crecimiento):
    tabla = crecimiento.get("tabla") if isinstance(crecimiento, dict) else crecimiento
    if not isinstance(tabla, pd.DataFrame) or tabla.empty:
        return
    res = estados.get("resultados")
    if res is None or res.empty:
        return
    ingresos = _serie(res, ["Total Revenue", "Operating Revenue"])
    bruto = _serie(res, ["Gross Profit"])
    operativo = _serie(res, ["Operating Income", "EBIT"])
    neto = _serie(res, ["Net Income", "Net Income Common Stockholders"])
    if ingresos is None:
        return

    for _, fila in tabla.iterrows():
        anio = _num(fila.get("Ejercicio"))
        if anio is None or not (1990 <= anio <= 2100):
            anotar(tk, "ALTA", "crecimiento y margenes",
                   f"ejercicio invalido: {fila.get('Ejercicio')}")
            continue
        # Localiza la columna de ese ejercicio en los estados
        etiqueta = None
        for c in ingresos.index:
            try:
                a = int(c) if 1900 <= int(c) <= 2100 else pd.to_datetime(c).year
            except (TypeError, ValueError):
                try:
                    a = pd.to_datetime(c).year
                except Exception:
                    continue
            if a == int(anio):
                etiqueta = c
                break
        if etiqueta is None:
            continue
        ing = _num(ingresos.get(etiqueta))
        if not ing:
            continue
        for columna, serie, texto in (("Margen bruto", bruto, "margen bruto"),
                                      ("Margen operativo", operativo, "margen operativo"),
                                      ("Margen neto", neto, "margen neto")):
            publicado = _num(fila.get(columna))
            if publicado is None or serie is None:
                continue
            propio = _num(serie.get(etiqueta))
            if propio is None:
                continue
            esperado = propio / ing
            if _cerca(publicado, esperado) is False:
                anotar(tk, "ALTA", "crecimiento y margenes",
                       f"{texto} {int(anio)}: publica {publicado:.4f}, "
                       f"recalculado {esperado:.4f}")


def revisar_circulante(tk, estados, circulante):
    if not isinstance(circulante, pd.DataFrame) or circulante.empty:
        return
    res = estados.get("resultados")
    if res is None:
        return
    ingresos = _serie(res, ["Total Revenue", "Operating Revenue"])
    if ingresos is None:
        return
    for _, fila in circulante.iterrows():
        anio = _num(fila.get("Ejercicio"))
        importe = _num(fila.get("Importe"))
        sobre = _num(fila.get("Sobre ingresos"))
        if None in (anio, importe, sobre):
            continue
        if not (1990 <= anio <= 2100):
            anotar(tk, "ALTA", "capital circulante",
                   f"ejercicio invalido: {fila.get('Ejercicio')}")
            continue
        etiqueta = next((c for c in ingresos.index
                         if str(c).strip() == str(int(anio))), None)
        if etiqueta is None:
            continue
        ing = _num(ingresos.get(etiqueta))
        if not ing:
            continue
        if _cerca(sobre, importe / ing, 0.02) is False:
            anotar(tk, "ALTA", "capital circulante",
                   f"{fila.get('Partida')} {int(anio)}: sobre ingresos "
                   f"{sobre:.4f}, recalculado {importe/ing:.4f}")


def revisar_apalancamiento(tk, apalancamiento):
    if not isinstance(apalancamiento, pd.DataFrame) or apalancamiento.empty:
        return
    for _, fila in apalancamiento.iterrows():
        total, caja, neta = (_num(fila.get("Deuda total")),
                             _num(fila.get("Caja")), _num(fila.get("Deuda neta")))
        if None in (total, caja, neta):
            continue
        if abs((total - caja) - neta) > max(abs(neta) * 0.01, 1000):
            anotar(tk, "ALTA", "apalancamiento",
                   f"{fila.get('Ejercicio')}: deuda neta {neta:,.0f} no es "
                   f"deuda total {total:,.0f} menos caja {caja:,.0f}")


# =============================================================================
#  3 · SEGMENTOS Y GEOGRAFIA
# =============================================================================

def revisar_geografia(tk, geo):
    tabla = geo.get("tabla") if isinstance(geo, dict) else geo
    if not isinstance(tabla, pd.DataFrame) or tabla.empty:
        return
    imp = pd.to_numeric(tabla.get("Importe"), errors="coerce")
    pes = pd.to_numeric(tabla.get("Peso"), errors="coerce")
    if imp is None or imp.dropna().empty:
        return
    total = imp.sum()
    if pes is not None and pes.notna().any():
        if abs(pes.sum() - 1) > 0.02:
            anotar(tk, "ALTA", "geografia",
                   f"los pesos suman {pes.sum():.4f} en lugar de 1")
        recalculado = imp / total if total else None
        if recalculado is not None and not np.allclose(
                recalculado.fillna(0), pes.fillna(0), atol=0.005):
            anotar(tk, "ALTA", "geografia",
                   "el peso publicado no corresponde a los importes de la tabla")
    # Areas repetidas
    if "Area" in tabla.columns:
        rep = tabla["Area"].astype(str).duplicated().sum()
        if rep:
            anotar(tk, "ALTA", "geografia", f"{rep} area(s) repetidas en la tabla")
    if (imp < 0).any() and (imp > 0).any():
        anotar(tk, "MEDIA", "geografia",
               "la tabla mezcla importes positivos y negativos")
    # Contraste con el total declarado en el propio informe de la SEC
    det = (geo.get("detalle") or {}).get("tabla") if isinstance(geo, dict) else None
    if isinstance(det, pd.DataFrame) and not det.empty:
        consolidado = None
        for etiqueta in det.index:
            if "consolidad" in str(etiqueta).lower():
                consolidado = _num(det.loc[etiqueta].iloc[0])
                break
        if consolidado and _cerca(total, consolidado, 0.02) is False:
            desvio = abs(total / consolidado - 1)
            anotar(tk, "ALTA" if desvio >= 0.25 else "MEDIA", "geografia",
                   f"las areas suman {total:,.0f} frente al total declarado "
                   f"{consolidado:,.0f} ({total/consolidado-1:+.1%})")


def revisar_desglose(tk, paquete, tipo):
    if not isinstance(paquete, dict):
        return
    partes = paquete.get("partes")
    cuadre = paquete.get("cuadre")
    if isinstance(partes, pd.DataFrame) and not partes.empty:
        if pd.Index(partes.index).duplicated().any():
            anotar(tk, "ALTA", f"segmentos ({tipo})", "bloques repetidos")
        # Columnas identicas entre ejercicios
        cols = list(partes.columns)
        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                a = pd.to_numeric(partes[cols[i]], errors="coerce")
                b = pd.to_numeric(partes[cols[j]], errors="coerce")
                com = a.notna() & b.notna()
                if com.sum() >= 3 and (a[com] == b[com]).all():
                    anotar(tk, "ALTA", f"segmentos ({tipo})",
                           f"los periodos {cols[i]} y {cols[j]} son identicos")
    if isinstance(cuadre, pd.DataFrame) and not cuadre.empty:
        peor = pd.to_numeric(cuadre.get("Desvio"), errors="coerce").abs().max()
        vacio = not isinstance(partes, pd.DataFrame) or partes.empty
        if peor is not None and np.isfinite(peor) and peor > 0.02:
            # Con las partes vacias el desvio del 100 % solo significa que el
            # motor no encontro bloques utilizables; el informe omite el bloque
            # y no publica nada, de modo que no hay dato erroneo que corregir.
            anotar(tk, "INFO" if vacio else "ALTA", f"segmentos ({tipo})",
                   f"desvio del {peor:.2%}"
                   + (" con el desglose vacio: el informe lo omite"
                      if vacio else " y el informe lo publicaba"))


# =============================================================================
#  4 · MARCADORES
# =============================================================================

def revisar_marcadores(tk, piot, altman, beneish, ratios):
    if isinstance(piot, dict):
        p, m = _num(piot.get("puntuacion")), _num(piot.get("maximo"))
        if p is not None and m is not None and not (0 <= p <= m):
            anotar(tk, "ALTA", "Piotroski", f"puntuacion {p} fuera de 0..{m}")
        tabla = piot.get("tabla")
        if isinstance(tabla, pd.DataFrame) and "Punto" in tabla.columns:
            suma = pd.to_numeric(tabla["Punto"], errors="coerce").sum()
            if p is not None and abs(suma - p) > 0.01:
                anotar(tk, "ALTA", "Piotroski",
                       f"la puntuacion {p} no es la suma de sus pruebas ({suma})")
    if isinstance(altman, dict):
        z = _num(altman.get("z"))
        if z is not None and abs(z) > 100:
            anotar(tk, "MEDIA", "Altman", f"Z-Score fuera de rango razonable: {z:.1f}")
    if isinstance(beneish, dict):
        m = _num(beneish.get("m"))
        if m is not None and abs(m) > 20:
            anotar(tk, "MEDIA", "Beneish", f"M-Score fuera de rango: {m:.1f}")
    if isinstance(ratios, dict):
        r = _num(ratios.get("roic_actual"))
        if r is not None and abs(r) > 5:
            anotar(tk, "MEDIA", "ROIC", f"ROIC de {r:.1%}, revisar denominador")


# =============================================================================
def auditar(tk):
    cik = mf.mapa_ticker_cik().get(tk.upper())
    if not cik:
        return False
    estados = mf.estados_financieros(tk)
    if not estados or estados.get("resultados") is None:
        return False

    revisar_estados(tk, estados)
    revisar_margenes(tk, estados, mf.crecimiento_margenes(estados))
    revisar_circulante(tk, estados, mf.capital_circulante(estados))
    revisar_apalancamiento(tk, mf.evolucion_apalancamiento(estados))

    clase = mf.clasificar_negocio(tk) or {}
    es_fin = bool(clase.get("es_financiera"))
    revisar_marcadores(tk, mf.piotroski_f(estados), None,
                       mf.beneish_m(estados, es_financiera=es_fin),
                       mf.retornos_capital(estados, es_financiera=es_fin))

    analisis = ms.analizar_segmentos(cik)
    if analisis:
        revisar_geografia(tk, ms.tabla_geografica(analisis))
        for tipo in ("negocio", "producto"):
            revisar_desglose(tk, ms.desglose(analisis, tipo), tipo)
    return True


def main():
    import random
    import motor_cribado as crib
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    universo = crib.universo_sp500()
    random.seed(int(sys.argv[2]) if len(sys.argv) > 2 else 20260820)
    muestra = random.sample(list(universo["Ticker"]), n)

    print("=" * 78)
    print(f"  AUDITORIA DE INTEGRIDAD DE FUNDAMENTALES · {n} empresas")
    print("=" * 78)
    revisadas = 0
    for i, tk in enumerate(muestra, 1):
        antes = len(INCIDENCIAS)
        try:
            ok = auditar(tk)
        except Exception as e:
            anotar(tk, "ALTA", "auditoria", f"{type(e).__name__}: {str(e)[:90]}")
            ok = True
        revisadas += bool(ok)
        nuevas = len(INCIDENCIAS) - antes
        print(f"  {i:2d}. {tk:6s} {'sin incidencias' if not nuevas else str(nuevas) + ' incidencia(s)'}"
              + ("" if ok else "  (sin cobertura en SEC)"))

    print("\n" + "=" * 78)
    print(f"  Empresas revisadas: {revisadas}/{n}")
    altas = [x for x in INCIDENCIAS if x["Gravedad"] == "ALTA"]
    medias = [x for x in INCIDENCIAS if x["Gravedad"] == "MEDIA"]
    print(f"  Graves: {len(altas)} · medias: {len(medias)} · "
          f"totales: {len(INCIDENCIAS)}")
    if INCIDENCIAS:
        print()
        for x in INCIDENCIAS:
            print(f"  [{x['Gravedad']:5s}] {x['Ticker']:6s} {x['Bloque']:24s} {x['Detalle']}")
    return 1 if altas else 0


if __name__ == "__main__":
    sys.exit(main())
