#ANALIZADOR DE ACTIVOS - VERSION INTERACTIVA#
#
# Mismo analisis que "ANALIZADOR DE ACTIVOS.py", pero el ticker se introduce
# por consola al arrancar en lugar de estar escrito a mano dentro del codigo.
# TODA la parte tecnica (calculos, descargas, formulas) es identica al original:
# lo unico que se ha hecho es sustituir el literal "ICHR" por la variable TICKER.

#DESCARGAR LIBRERIAS

import logging
import os
import re
import sys
from datetime import date

import seaborn
import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.stats import norm


# =============================================================================
#  BLOQUE INTERACTIVO
#  Es lo unico nuevo del script. Pide el ticker (y 4 parametros opcionales) por
#  consola y los deja en variables globales que el resto del codigo usa en el
#  sitio exacto donde antes estaba escrito "ICHR" / "QQQ".
# =============================================================================

# --- Parametros que antes estaban "hardcodeados" y ahora viven aqui arriba ---
PERIODO_HISTORICO = "5y"          # periodo de yf.Ticker().history()
FECHA_INICIO      = "2021-01-01"  # inicio para Monte Carlo y VaR / CVaR
FECHA_INICIO_PERF = "2018-01-01"  # inicio para el analisis de performance
FECHA_FIN         = date.today().strftime("%Y-%m-%d")  

# Para que las tildes (á, é, ó...) salgan bien tambien si vuelcas la salida a
# un fichero: python "ANALIZADOR DE ACTIVOS INTERACTIVO.py" > informe.txt
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def _en_notebook():
    """True si el script corre dentro de Jupyter / Colab (para usar ipywidgets)."""
    try:
        from IPython import get_ipython
        ip = get_ipython()
        return ip is not None and "IPKernelApp" in ip.config
    except Exception:
        return False


EN_NOTEBOOK = _en_notebook()

# display() / HTML() existen en Colab pero NO en un script normal.
if EN_NOTEBOOK:
    from IPython.display import display, HTML
else:
    def HTML(texto):
        return re.sub(r"<[^>]+>", "", str(texto)).strip()

    def display(obj):
        print(obj)


def titulo(texto):
    """Separador visual en la terminal."""
    print("\n" + "=" * 78)
    print("  " + texto)
    print("=" * 78)


def leer(mensaje=""):
    """input() a prueba de balas para una herramienta que se abre con doble clic.

    - Limpia los caracteres invisibles que arrastra un copiar/pegar desde Excel
      o Word (BOM, espacio duro, ancho cero). El .strip() normal NO los quita y
      dejaria el ticker como invalido sin que se vea el motivo por pantalla.
    - Sale con elegancia si pulsas Ctrl+C o si se cierra la entrada, en vez de
      escupir un traceback en la cara.
    """
    try:
        texto = input(mensaje)
    except (EOFError, KeyboardInterrupt):
        print("\n\n  Analisis cancelado.\n")
        sys.exit(0)
    for invisible in ("﻿", "​", "‎", "‏"):
        texto = texto.replace(invisible, "")
    return texto.replace(" ", " ").strip()


def pedir_numero(mensaje, defecto, minimo, maximo, entero=False):
    """Pide un numero por consola; Enter deja el valor por defecto."""
    while True:
        entrada = leer(f"  {mensaje} [Enter = {defecto}]: ").replace(",", ".")
        if entrada == "":
            return defecto
        try:
            valor = float(entrada)
        except ValueError:
            print("     -> Eso no es un numero. Prueba otra vez.")
            continue
        if not (minimo <= valor <= maximo):
            print(f"     -> Tiene que estar entre {minimo} y {maximo}.")
            continue
        return int(valor) if entero else valor


def validar_ticker(simbolo):
    """Comprueba contra Yahoo Finance que el ticker existe y devuelve datos.

    Devuelve (nombre_largo, moneda) si es valido, o None si no lo es.
    """
    # Yahoo escupe un 404 muy feo por consola cuando el simbolo no existe.
    # Lo silenciamos SOLO durante la comprobacion para dar un mensaje limpio.
    log_yf = logging.getLogger("yfinance")
    nivel_previo = log_yf.level
    log_yf.setLevel(logging.CRITICAL)
    try:
        objeto = yf.Ticker(simbolo)
        prueba = objeto.history(period="1mo", auto_adjust=True)
    except Exception as e:
        print(f"     -> No se pudo conectar con Yahoo Finance: {e}")
        return None
    finally:
        log_yf.setLevel(nivel_previo)

    if prueba.empty:
        return None

    # El nombre y la divisa son "extras": si Yahoo no los da, no pasa nada.
    nombre, moneda = simbolo, "USD"
    try:
        info = objeto.info or {}
        nombre = info.get("longName") or info.get("shortName") or simbolo
        moneda = info.get("currency") or "USD"
    except Exception:
        pass
    return nombre, moneda


def pedir_ticker():
    """Bucle hasta que el usuario introduce un ticker que Yahoo Finance reconoce."""
    while True:
        entrada = leer("  > Ticker: ").strip().upper()
        if not entrada:
            print("     -> No has escrito nada.")
            continue
        print("     Comprobando en Yahoo Finance...")
        resultado = validar_ticker(entrada)
        if resultado is None:
            print(f"     -> '{entrada}' no devuelve datos. Revisa el simbolo "
                  f"(ej: acciones europeas llevan sufijo: SAN.MC, BMW.DE, VOD.L).")
            continue
        nombre, moneda = resultado
        print(f"     [OK] {entrada} -> {nombre}  ({moneda})")
        return entrada, nombre, moneda


# ------------------------------- ARRANQUE ------------------------------------
print("=" * 78)
print("                        A N A L I Z A D O R   D E   A C T I V O S")
print("=" * 78)
print("  Introduce el ticker que quieras analizar (Yahoo Finance).")

TICKER, NOMBRE_ACTIVO, MONEDA = pedir_ticker()

print("\n  Que quieres hacer?")
print("     1 = Analisis completo (ficha + earnings + las 6 secciones de siempre)")
print("     2 = Solo earnings: ver rapido si ha habido sobrerreaccion")
MODO_COMPLETO = pedir_numero("Opcion", 1, 1, 2, entero=True) == 1

print("\n  Parametros del analisis (pulsa Enter para dejar el valor por defecto):")

# Ticker de comparacion para el dashboard final (activo_2). Solo hace falta
# en el analisis completo, asi que en modo rapido ni se pregunta.
BENCHMARK = "SPY"
if MODO_COMPLETO:
    while True:
        _bench = input("  Ticker de comparacion [Enter = SPY]: ").strip().upper() or "SPY"
        if _bench == TICKER:
            print("     -> Tiene que ser distinto del principal.")
            continue
        if validar_ticker(_bench) is None:
            print(f"     -> '{_bench}' no devuelve datos.")
            continue
        BENCHMARK = _bench
        break

CONFIANZA = pedir_numero("Nivel de confianza VaR/CVaR en %", 99.0, 90.0, 99.9)
INVERSION = 100000
if MODO_COMPLETO:
    INVERSION = pedir_numero("Capital invertido en $", 100000, 100, 10_000_000, entero=True)

print("\n  Que hago con los graficos?")
print("     1 = Mostrarlos en pantalla (uno a uno)")
print("     2 = Guardarlos en una carpeta como PNG")
print("     3 = Ambas cosas")
_modo = pedir_numero("Opcion", 1, 1, 3, entero=True)

VER_EN_PANTALLA = _modo in (1, 3)
CARPETA_SALIDA = None
if _modo in (2, 3):
    CARPETA_SALIDA = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  f"analisis_{TICKER}")
    os.makedirs(CARPETA_SALIDA, exist_ok=True)
    print(f"     Los graficos se guardaran en: {CARPETA_SALIDA}")

# Truco para NO tener que tocar ni una sola de las lineas plt.show() del codigo
# original: se sustituye plt.show por una version que ademas guarda el PNG.
_show_original = plt.show
_contador_graficos = [0]


def _show_personalizado(*args, **kwargs):
    _contador_graficos[0] += 1
    if CARPETA_SALIDA is not None:
        ruta = os.path.join(CARPETA_SALIDA, f"{_contador_graficos[0]:02d}_{TICKER}.png")
        plt.savefig(ruta, dpi=150, bbox_inches="tight")
        print(f"     [grafico guardado] {os.path.basename(ruta)}")
    if VER_EN_PANTALLA:
        _show_original(*args, **kwargs)
    else:
        plt.close("all")


plt.show = _show_personalizado

print(f"\n  Analizando {NOMBRE_ACTIVO} ({TICKER})... cierra cada grafico para continuar.\n")


def final_del_analisis():
    """Cierre comun a los dos modos: resumen y opcion de repetir con otro ticker."""
    if EN_NOTEBOOK:
        return
    titulo(f"ANALISIS DE {TICKER} COMPLETADO")
    if CARPETA_SALIDA is not None:
        print(f"  Graficos guardados en: {CARPETA_SALIDA}")
    if input("\n  Analizar otro activo? (s/n): ").strip().lower() in ("s", "si", "sí", "y", "yes"):
        _py = sys.executable
        _script = os.path.abspath(__file__)
        try:
            os.execv(_py, [_py, _script])
        except Exception:
            import subprocess
            subprocess.run([_py, _script])
    else:
        print("\n  Hasta la proxima.\n")


# =============================================================================
#  FICHA RAPIDA + SOBRERREACCION EN EARNINGS
#
#  Bloque NUEVO. Va antes del codigo original para que ese siga sin indentar ni
#  una linea y para poder salir aqui mismo en modo rapido.
#
#  La idea: el codigo original ya calcula la distribucion de retornos, la
#  volatilidad y el VaR. Esto solo situa el movimiento del dia de resultados
#  DENTRO de esa distribucion, que es lo que permite decir si fue exagerado.
# =============================================================================

from scipy.stats import percentileofscore  # noqa: E402  (import local del bloque nuevo)

VENTANAS_DRIFT = (5, 10, 20)   # sesiones posteriores para medir si el precio revierte
UMBRAL_EXTREMO = 2.0           # sigmas a partir de las cuales el movimiento es "extremo"
UMBRAL_ELEVADO = 1.5
UMBRAL_REVERSION = 0.33        # devolver >=1/3 del movimiento cuenta como sobrerreaccion
# Cuando el EPS estimado es casi cero, la "sorpresa %" de Yahoo se dispara a
# cifras absurdas (-4600%, +700%...) que no informan de nada y aplastan la
# escala del grafico. Por encima de este limite se excluyen de la regresion.
LIMITE_SORPRESA = 200.0


def descargar_historico(simbolo):
    """Cierres diarios + retornos logaritmicos. Misma fuente que el resto del script."""
    h = yf.Ticker(simbolo).history(period="5y", auto_adjust=True)[["Close"]].copy()
    h = h.dropna()
    h["LogReturn"] = np.log(h["Close"] / h["Close"].shift(1))
    return h


def posicion_dia_reaccion(momento, fechas_sesion):
    """Indice de la sesion en la que el mercado DIGIERE los resultados.

    Es el detalle que mas se falla al analizar earnings: si la empresa publica
    despues del cierre (Yahoo suele marcar las 16:00 en NY), el movimiento no
    ocurre ese dia sino en la sesion siguiente. Si publica antes de la apertura,
    ocurre el mismo dia. Devolvemos tambien la fecha usada para poder revisarlo.
    """
    dia = momento.date()
    if momento.hour >= 15:                       # publicado con el mercado ya cerrado
        pos = int(np.searchsorted(fechas_sesion, dia, side="right"))
    else:                                        # publicado antes de abrir
        pos = int(np.searchsorted(fechas_sesion, dia, side="left"))
    if pos >= len(fechas_sesion) or pos == 0:
        return None
    return pos


def analizar_earnings(simbolo):
    """Cruza las fechas de resultados con la reaccion real del precio.

    Devuelve None si el activo no tiene earnings (ETFs, indices, cripto, divisas).
    """
    log_yf = logging.getLogger("yfinance")
    nivel = log_yf.level
    log_yf.setLevel(logging.CRITICAL)
    try:
        fechas_earnings = yf.Ticker(simbolo).get_earnings_dates(limit=40)
    except Exception:
        fechas_earnings = None
    finally:
        log_yf.setLevel(nivel)

    if fechas_earnings is None or len(fechas_earnings) == 0:
        return None

    hist = descargar_historico(simbolo)
    if len(hist) < 60:
        return None
    fechas_sesion = np.array([d.date() for d in hist.index])
    ultima_sesion = fechas_sesion[-1]

    eventos, posiciones, futuros = [], [], []
    for momento, fila in fechas_earnings.sort_index().iterrows():
        pos = posicion_dia_reaccion(momento, fechas_sesion)
        if pos is None:
            if momento.date() > ultima_sesion:
                futuros.append(momento)
            continue
        if pos in posiciones:        # dos anuncios mapeados a la misma sesion
            continue
        posiciones.append(pos)
        eventos.append({
            "momento": momento,
            "pos": pos,
            "fecha_reaccion": fechas_sesion[pos],
            "tras_cierre": momento.hour >= 15,
            "eps_est": fila.get("EPS Estimate", np.nan),
            "eps_real": fila.get("Reported EPS", np.nan),
            "sorpresa": fila.get("Surprise(%)", np.nan),
        })

    if not eventos:
        return None

    # Sigma de referencia: dias SIN resultados. Si metieramos los dias de earnings
    # dentro, la propia volatilidad del evento inflaria sigma y todo movimiento
    # pareceria menos extremo de lo que es.
    normales = np.ones(len(hist), dtype=bool)
    normales[posiciones] = False
    retornos_normales = hist["LogReturn"][normales].dropna()
    sigma_normal = float(retornos_normales.std())
    todos_retornos = hist["LogReturn"].dropna()

    cierres = hist["Close"].values
    for ev in eventos:
        pos = ev["pos"]
        lr = float(hist["LogReturn"].iloc[pos])
        ev["log_mov"] = lr
        ev["mov"] = float(np.expm1(lr))                       # en % simple, mas legible
        ev["sigmas"] = lr / sigma_normal if sigma_normal else np.nan
        ev["percentil"] = float(percentileofscore(todos_retornos, lr))

        # Deriva posterior: la prueba de fuego de la sobrerreaccion
        for n in VENTANAS_DRIFT:
            ev[f"drift_{n}"] = (float(cierres[pos + n] / cierres[pos] - 1)
                                if pos + n < len(cierres) else np.nan)

        # Deriva parcial: para el earnings mas reciente todavia no hay 5 sesiones,
        # pero si han pasado 2 o 3 ya dicen algo. Es el caso que mas interesa.
        ev["sesiones_desde"] = len(cierres) - 1 - pos
        ev["drift_parcial"] = (float(cierres[-1] / cierres[pos] - 1)
                               if ev["sesiones_desde"] > 0 else np.nan)

        # Veredicto
        d_final, ventana_usada = np.nan, None
        for n in VENTANAS_DRIFT:                              # la ventana mas larga disponible
            if not np.isnan(ev[f"drift_{n}"]):
                d_final, ventana_usada = ev[f"drift_{n}"], n
        ev["ventana_drift"] = ventana_usada
        # Fraccion del movimiento devuelta: >0 revierte, <0 continua en la misma direccion
        ev["recuperacion"] = (-d_final / ev["mov"]) if (ev["mov"] and not np.isnan(d_final)) else np.nan

        def _etiqueta(recup, prefijo="", sufijo=""):
            if recup >= UMBRAL_REVERSION:
                return f"{prefijo}SOBRERREACCION (revirtio){sufijo}"
            if recup <= -0.10:
                return f"{prefijo}continuacion / drift{sufijo}"
            return f"{prefijo}movimiento sostenido{sufijo}"

        if abs(ev["sigmas"]) < UMBRAL_ELEVADO:
            ev["veredicto"] = "movimiento normal"
        elif ventana_usada is not None:
            extra = f" [solo {ventana_usada}d]" if ventana_usada < max(VENTANAS_DRIFT) else ""
            ev["veredicto"] = _etiqueta(ev["recuperacion"], sufijo=extra)
        elif ev["sesiones_desde"] >= 1 and ev["mov"]:
            rec = -ev["drift_parcial"] / ev["mov"]
            ev["veredicto"] = _etiqueta(rec, prefijo="EN CURSO -> ",
                                        sufijo=f" ({ev['sesiones_desde']}d)")
        else:
            ev["veredicto"] = "EN CURSO (reaccion de hoy mismo)"

    movs = np.array([abs(e["mov"]) for e in eventos])
    return {
        "eventos": eventos,
        "hist": hist,
        "sigma_normal": sigma_normal,
        "mov_medio_earnings": float(movs.mean()),
        "mov_medio_normal": float(np.expm1(retornos_normales.abs().mean())),
        "proximos": futuros,
    }


def ficha_rapida(simbolo, nombre, moneda, earnings):
    """Panel de 'donde se encuentra' el activo AHORA MISMO."""
    hist = earnings["hist"] if earnings else descargar_historico(simbolo)
    cierres = hist["Close"]
    retornos = hist["LogReturn"].dropna()

    precio = float(cierres.iloc[-1])
    mov_hoy = float(np.expm1(retornos.iloc[-1]))
    sigma = earnings["sigma_normal"] if earnings else float(retornos.std())
    z_hoy = float(retornos.iloc[-1]) / sigma if sigma else np.nan
    pct_hoy = float(percentileofscore(retornos, retornos.iloc[-1]))

    ventana = cierres.iloc[-252:] if len(cierres) >= 252 else cierres
    maximo, minimo = float(ventana.max()), float(ventana.min())
    pos_rango = (precio - minimo) / (maximo - minimo) * 100 if maximo > minimo else 50.0

    vol_anual = float(retornos.std() * np.sqrt(252))
    var_hist = float(np.percentile(retornos, (1 - CONFIANZA / 100) * 100))

    titulo(f"FICHA RAPIDA - {nombre} ({simbolo})")
    print(f"  Fecha del ultimo cierre : {cierres.index[-1].date()}")
    print(f"  Precio                  : {precio:,.2f} {moneda}")
    print(f"  Variacion de la sesion  : {mov_hoy:+.2%}   "
          f"({z_hoy:+.1f} sigmas | percentil {pct_hoy:.0f} de su historico)")

    # Barra visual de posicion en el rango de 52 semanas
    casillas = 40
    marca = int(round(pos_rango / 100 * (casillas - 1)))
    barra = "".join("|" if i == marca else "-" for i in range(casillas))
    print(f"  Rango 52 semanas        : {minimo:,.2f}  {barra}  {maximo:,.2f}")
    print(f"                            esta al {pos_rango:.0f}% del rango, "
          f"a {(precio / maximo - 1):+.1%} de su maximo")
    ref = "sin earnings" if earnings else "historica"
    print(f"  Volatilidad anualizada  : {vol_anual:.1%}   (sigma diaria {ref}: {sigma:.2%})")
    etiqueta_var = f"VaR {CONFIANZA:.0f}% historico"
    print(f"  {etiqueta_var:<24}: {var_hist:.2%}"
          f"   -> la sesion de hoy {'SI' if float(retornos.iloc[-1]) <= var_hist else 'NO'} lo ha superado")

    if earnings is None:
        print("\n  Resultados: este activo no publica earnings (ETF, indice, cripto o divisa).")
        return

    print(f"  Mov. medio en earnings  : {earnings['mov_medio_earnings']:.2%}   "
          f"(vs {earnings['mov_medio_normal']:.2%} en un dia normal -> "
          f"x{earnings['mov_medio_earnings'] / earnings['mov_medio_normal']:.1f})")

    ultimo = earnings["eventos"][-1]
    print("\n  " + "-" * 74)
    print(f"  ULTIMOS RESULTADOS      : {ultimo['momento'].strftime('%Y-%m-%d %H:%M')} "
          f"({'tras el cierre' if ultimo['tras_cierre'] else 'antes de abrir'})")
    if not np.isnan(ultimo["sorpresa"]):
        print(f"     Sorpresa EPS         : {ultimo['sorpresa']:+.2f}%   "
              f"(reportado {ultimo['eps_real']} vs {ultimo['eps_est']} estimado)")
    print(f"     Reaccion del precio  : {ultimo['mov']:+.2%} el {ultimo['fecha_reaccion']} "
          f"({ultimo['sigmas']:+.1f} sigmas, percentil {ultimo['percentil']:.0f})")
    hubo_ventana = False
    for n in VENTANAS_DRIFT:
        if not np.isnan(ultimo[f"drift_{n}"]):
            print(f"     Desde entonces (+{n}d) : {ultimo[f'drift_{n}']:+.2%}")
            hubo_ventana = True
    if not hubo_ventana and ultimo["sesiones_desde"] >= 1:
        print(f"     Desde entonces ({ultimo['sesiones_desde']}d)  : {ultimo['drift_parcial']:+.2%}"
              f"   (aun no hay {min(VENTANAS_DRIFT)} sesiones completas)")
    print(f"     VEREDICTO            : {ultimo['veredicto'].upper()}")

    # Lectura en lenguaje llano del caso mas interesante: bate y aun asi cae
    if not np.isnan(ultimo["sorpresa"]) and ultimo["sorpresa"] > 0 and ultimo["mov"] < 0:
        print("     [!] Bate estimaciones y AUN ASI cae: expectativas ya descontadas,")
        print("         guidance flojo, o candidato claro a sobrerreaccion.")
    elif not np.isnan(ultimo["sorpresa"]) and ultimo["sorpresa"] < 0 and ultimo["mov"] > 0:
        print("     [!] Falla estimaciones y aun asi sube: el mercado esperaba algo peor.")

    if earnings["proximos"]:
        prox = earnings["proximos"][0]
        dias = (prox.date() - cierres.index[-1].date()).days
        print(f"\n  PROXIMOS RESULTADOS     : {prox.strftime('%Y-%m-%d')}  (dentro de {dias} dias)")


def tabla_earnings(earnings):
    """Historial completo de reacciones a resultados."""
    titulo("HISTORIAL DE REACCIONES A RESULTADOS")
    print(f"  Sigma de un dia SIN resultados: {earnings['sigma_normal']:.2%}  "
          f"(las sigmas de abajo se miden contra esto)")
    print()
    cab = (f"  {'Publicacion':<12} {'Reaccion':<12} {'Sorpresa':>9} {'Movim.':>9} "
           f"{'Sigmas':>8} {'Pctil':>6} {'+5d':>8} {'+10d':>8} {'+20d':>8}  Veredicto")
    print(cab)
    print("  " + "-" * (len(cab) + 8))
    for ev in earnings["eventos"][::-1]:
        sor = f"{ev['sorpresa']:+.1f}%" if not np.isnan(ev["sorpresa"]) else "n/d"
        d = {n: (f"{ev[f'drift_{n}']:+.1%}" if not np.isnan(ev[f"drift_{n}"]) else "-")
             for n in VENTANAS_DRIFT}
        print(f"  {ev['momento'].strftime('%Y-%m-%d'):<12} "
              f"{str(ev['fecha_reaccion']):<12} {sor:>9} {ev['mov']:>+9.2%} "
              f"{ev['sigmas']:>+8.1f} {ev['percentil']:>6.0f} "
              f"{d[5]:>8} {d[10]:>8} {d[20]:>8}  {ev['veredicto']}")

    reales = [e for e in earnings["eventos"] if not np.isnan(e.get("recuperacion", np.nan))]
    extremos = [e for e in reales if abs(e["sigmas"]) >= UMBRAL_EXTREMO]
    print()
    print(f"  Eventos analizados: {len(earnings['eventos'])}  |  "
          f"movimientos extremos (>{UMBRAL_EXTREMO:.0f} sigmas): {len(extremos)}")
    if reales:
        revierten = [e for e in reales if e["recuperacion"] >= UMBRAL_REVERSION]
        print(f"  Reacciones que revirtieron >={UMBRAL_REVERSION:.0%} del movimiento: "
              f"{len(revierten)} de {len(reales)} ({len(revierten) / len(reales):.0%})")
        print("  -> Cuanto mas alto ese porcentaje, mas tiende este valor a exagerar en earnings.")


def graficos_earnings(earnings, simbolo, nombre):
    """Tres vistas: cuanto se movio, si la sorpresa lo explica, y si revirtio."""
    eventos = earnings["eventos"]
    sigma = earnings["sigma_normal"]

    # --- 1. Movimiento de cada earnings contra las bandas de +-1 y +-2 sigmas ---
    plt.figure(figsize=(13, 6))
    etiquetas = [e["momento"].strftime("%Y-%m") for e in eventos]
    movs = [e["mov"] for e in eventos]
    colores = ["seagreen" if m >= 0 else "indianred" for m in movs]
    plt.bar(etiquetas, movs, color=colores, alpha=0.85, edgecolor="black", linewidth=0.5)
    for k, estilo in [(1, ":"), (2, "--")]:
        plt.axhline(k * sigma, color="gray", ls=estilo, lw=1.2,
                    label=f"+/-{k} sigma ({k * sigma:.1%})")
        plt.axhline(-k * sigma, color="gray", ls=estilo, lw=1.2)
    plt.axhline(0, color="black", lw=0.8)
    plt.title(f"Reaccion del precio a cada publicacion de resultados - {nombre} ({simbolo})",
              fontsize=14)
    plt.ylabel("Movimiento en la sesion de reaccion")
    plt.xticks(rotation=45, ha="right")
    plt.legend()
    plt.grid(alpha=0.2, axis="y")
    plt.tight_layout()
    plt.show()

    # --- 2. La sorpresa en EPS, explica el movimiento? ---
    con_sorpresa = [e for e in eventos if not np.isnan(e["sorpresa"])]
    usables = [e for e in con_sorpresa if abs(e["sorpresa"]) <= LIMITE_SORPRESA]
    descartados = len(con_sorpresa) - len(usables)
    if len(usables) >= 3:
        x = np.array([e["sorpresa"] for e in usables])
        y = np.array([e["mov"] for e in usables])
        plt.figure(figsize=(10, 6))
        plt.scatter(x, y, s=110, c=["seagreen" if v >= 0 else "indianred" for v in y],
                    edgecolor="black", zorder=3)
        for e in usables:
            plt.annotate(e["momento"].strftime("%y-%m"), (e["sorpresa"], e["mov"]),
                         fontsize=7, xytext=(4, 4), textcoords="offset points")
        if np.ptp(x) > 0:
            pend, corte = np.polyfit(x, y, 1)
            xs = np.linspace(x.min(), x.max(), 50)
            correl = float(np.corrcoef(x, y)[0, 1])
            plt.plot(xs, pend * xs + corte, color="navy", ls="--",
                     label=f"Tendencia (correlacion {correl:.2f})")
            plt.legend()
        plt.axhline(0, color="gray", lw=0.8)
        plt.axvline(0, color="gray", lw=0.8)
        aviso = (f"\n{descartados} evento(s) fuera: sorpresa >{LIMITE_SORPRESA:.0f}% "
                 f"por EPS estimado proximo a cero" if descartados else "")
        plt.title("Sorpresa en beneficios vs reaccion del precio\n"
                  "(abajo-derecha = bate y cae: sobrerreaccion o expectativas descontadas)"
                  + aviso, fontsize=12)
        plt.xlabel("Sorpresa EPS (%)")
        plt.ylabel("Movimiento del precio")
        plt.grid(alpha=0.2)
        plt.tight_layout()
        plt.show()
        if descartados:
            print(f"  [nota] {descartados} evento(s) excluidos del grafico de sorpresa: "
                  f"Yahoo reporta >{LIMITE_SORPRESA:.0f}% porque el EPS estimado era casi cero.")

    # --- 3. Event study: camino medio del precio alrededor de los resultados ---
    pre, post = 5, 20
    cierres = earnings["hist"]["Close"].values
    caminos = []
    for e in eventos:
        p = e["pos"]
        if p - pre - 1 < 0 or p + post >= len(cierres):
            continue
        caminos.append(cierres[p - pre: p + post + 1] / cierres[p - 1] - 1)
    if caminos:
        caminos = np.array(caminos)
        eje = np.arange(-pre, post + 1)
        plt.figure(figsize=(12, 6))
        for c in caminos:
            plt.plot(eje, c, color="steelblue", alpha=0.25, lw=1)
        plt.plot(eje, caminos.mean(axis=0), color="navy", lw=3, label="Camino medio")
        plt.axvline(0, color="red", ls="--", lw=1.5, label="Sesion de reaccion")
        plt.axhline(0, color="black", lw=0.8)
        plt.title(f"Comportamiento alrededor de los resultados - {nombre} ({simbolo})\n"
                  f"{len(caminos)} eventos, normalizados a 0 el dia previo", fontsize=13)
        plt.xlabel("Sesiones respecto al dia de reaccion")
        plt.ylabel("Rentabilidad acumulada")
        plt.legend()
        plt.grid(alpha=0.2)
        plt.tight_layout()
        plt.show()

        medio = caminos.mean(axis=0)
        salto, final = medio[pre], medio[-1]
        print(f"  De media: salta {salto:+.2%} el dia de la reaccion y termina "
              f"en {final:+.2%} {post} sesiones despues.")
        if salto != 0:
            if np.sign(final) != np.sign(salto):
                print("  -> De media el movimiento se REVIERTE por completo: patron de sobrerreaccion.")
            elif abs(final) < abs(salto):
                print(f"  -> De media devuelve {(1 - abs(final) / abs(salto)):.0%} del salto inicial.")
            else:
                print("  -> De media el movimiento CONTINUA (post-earnings drift).")


# ----------------------------- EJECUCION DEL BLOQUE ---------------------------
DATOS_EARNINGS = analizar_earnings(TICKER)
ficha_rapida(TICKER, NOMBRE_ACTIVO, MONEDA, DATOS_EARNINGS)

if DATOS_EARNINGS is not None:
    tabla_earnings(DATOS_EARNINGS)
    graficos_earnings(DATOS_EARNINGS, TICKER, NOMBRE_ACTIVO)

if not MODO_COMPLETO:
    final_del_analisis()
    sys.exit(0)

# =============================================================================
#  A PARTIR DE AQUI: CODIGO ORIGINAL INTACTO
#  (solo cambian los literales "ICHR" -> TICKER y los titulos -> f-strings)
# =============================================================================

titulo("1. PRECIOS HISTORICOS Y RETORNOS DIARIOS")

# 1. Configurar el ticker
ticker_symbol = TICKER
ichor = yf.Ticker(ticker_symbol)

# 2. Descargar precios históricos de los años que consideremos (en este caso 5y)
df_ichr = ichor.history(period=PERIODO_HISTORICO, auto_adjust=True)

# 3. Mantener solo la columna "Close" para coger el análisis con los precios de cierres del día anterior
df_ichr = df_ichr[["Close"]].copy()

# 4. Crear columna de retornos diarios
df_ichr["Return"] = df_ichr["Close"].pct_change()

# 5. Eliminar el primer valor nulo
df_ichr = df_ichr.dropna()

# Aviso si el activo es demasiado nuevo para las ventanas de 21 dias
if len(df_ichr) < 30:
    print(f"[AVISO] Solo hay {len(df_ichr)} dias de historico para {TICKER}. "
          f"Algunas metricas (volatilidad rolling 21d) pueden salir vacias.")

# Mostrar primeras filas (terminal)
print(df_ichr.head())

# 6. Cálculo de retorno medio y volatilidad
# Desviación estándar- medida de la volatilidad de los retornos diarios
mean_return = np.mean(df_ichr["Return"])
std_return = np.std(df_ichr["Return"])

print(f"Retorno Medio diario: {mean_return: .5f}")
print(f"Desviación estándar diaria: {std_return:.5f}")

# 7. Gráfico de precios con cierre ajustado

plt.figure(figsize=(12,5))
plt.plot(df_ichr["Close"])
plt.title(f"Precio de Cierre Ajustado de {NOMBRE_ACTIVO}")
plt.xlabel("Fecha")
plt.ylabel(f"Precio ({MONEDA})")
plt.grid(True)
plt.show()


#_______________________________________________________________________

#RETORNOS DIARIOS Buscamos la variabilidad relativa, no el valor absoluto
# 1. Definir el objeto Ticker correctamente
ichr_ticker = yf.Ticker(TICKER)

# 2. Descargar datos usando el objeto Ticker (no el DataFrame)
df_ichr = ichr_ticker.history(period=PERIODO_HISTORICO, auto_adjust=True)

# 3. Procesar datos
df_ichr = df_ichr[["Close"]].copy()
df_ichr["Return"] = df_ichr["Close"].pct_change()
df_ichr = df_ichr.dropna()

# 4. Graficar
plt.figure(figsize=(12,5))
plt.plot(df_ichr["Return"])
plt.title(f"Retornos diarios de {NOMBRE_ACTIVO} ({TICKER})")
plt.xlabel("Fecha")
plt.ylabel("Retorno diario")
plt.grid(True)
plt.show()


#DISTRIBUCIÓN DE RETORNOS DIARIOS
plt.figure(figsize=(10,4))
plt.hist(df_ichr["Return"], bins=75, density=False)
plt.title(f"Distribución de Retornos Diarios de {NOMBRE_ACTIVO} ({TICKER})")
plt.xlabel("Retorno diario")
plt.ylabel ("Frecuencia")
plt.grid(True)
plt.show()




#________________________________________________________________________
#Meter correlación entre activos (S&P500 y Dow Jones como ejemplo)
# Copia de documento 00 drive
#_________________________________________________________________________
#Retornos logarítmicos
df_ichr["LogReturn"] = np.log(df_ichr["Close"] / df_ichr["Close"].shift(1))
df_ichr = df_ichr.dropna()
print(df_ichr.head())
plt.figure(figsize=(12, 8))
plt.plot(df_ichr["Close"])
plt.title(f"Precio de cierre ajustado {NOMBRE_ACTIVO}")
plt.xlabel("Fecha")
plt.ylabel("Precio")
plt.grid(True)
plt.show()



plt.figure(figsize=(12, 8))
plt.plot(df_ichr["Return"], label="Simple Return")
plt.plot(df_ichr["LogReturn"], label="Log Return")
plt.title(f"Retornos diarios de {NOMBRE_ACTIVO}")
plt.xlabel("Fecha")
plt.ylabel("Retorno")
plt.legend()
plt.grid(True)
plt.show()


#Volatilidad histórica anualizada en ventanas de 21 días (aproximadamente un mes)
df_ichr["Volatility"] = df_ichr["LogReturn"].rolling(window=21).std() * np.sqrt(252) #anualizada
#Multiplicamos por 252 días, asumiendo 252 días de operativa de trading anual. Es un dato "estándar"
plt.figure(figsize=(12, 8))
plt.plot(df_ichr["Volatility"])
plt.title(f"Volatilidad histórica anualizada 21 días - {TICKER}")
plt.xlabel("Fecha")
plt.ylabel("Volatilidad")
plt.grid(True)
plt.show()

#_______________________________---
#RESUMEN ESTADÍSTICO DE RETORNOS
summary = df_ichr[["Return","LogReturn", "Volatility"]].describe()
print(summary)


#_________________________________________________________________________________________________________________
#  MONTE CARLO SIMULACIÓN DE PRECIOS FUTUROS

titulo("2. SIMULACION MONTE CARLO")

# Descargar datos históricos para el activo elegido
ticker = TICKER
data = yf.download(ticker, start=FECHA_INICIO, end=FECHA_FIN) # Ajusta el rango de fechas según necesites

# Calcular S0 (precio inicial) y sigma (volatilidad) de los datos históricos
# OJO: se añade .dropna() antes del .iloc[-1]. Yahoo a veces devuelve una ultima
# fila vacia (mercados no-US como SAN.MC, o la sesion de hoy sin cerrar). Sin el
# dropna, S0 seria NaN y TODA la simulacion saldria NaN. Con ICHR no se notaba.
S0 = data['Close'].dropna().iloc[-1].item() # Último precio de cierre como precio inicial, convertido a escalar
log_returns = np.log(data['Close'] / data['Close'].shift(1))
daily_volatility = log_returns.std()
sigma = daily_volatility * np.sqrt(252) # Volatilidad anualizada (252 días de trading)
sigma = sigma.item() # Convertir sigma de Series a escalar

r = 0.05          # Tasa libre de riesgo (5% - puedes ajustarla)
T = 1.0           # Tiempo en años (1 año)
pasos = 252       # Pasos temporales (días bursátiles en un año)
n_sim = 10000     # Número de trayectorias (10,000 futuros)

dt = T / pasos    # Tamaño del paso temporal

# 2 GENERACIÓN DE CHOQUES ALEATORIOS (Z)
# Creamos una matriz de 252 días x 10,000 simulaciones
Z = np.random.standard_normal((pasos, n_sim))

# 3 CONSTRUCCIÓN DE TRAYECTORIAS
# Calculamos el retorno diario para cada celda
retornos_diarios = np.exp((r - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * Z)

# Creamos la matriz de precios empezando por S0
precios = np.zeros((pasos + 1, n_sim))
precios[0] = S0

# Aplicamos el producto acumulado para obtener la evolución del precio
precios[1:] = S0 * np.cumprod(retornos_diarios, axis=0)

# 4. VISUALIZACIÓN
plt.figure(figsize=(10,6))
plt.plot(precios[:, :100], color='royalblue', alpha=0.1) # Graficamos solo las primeras 100 para no saturar

plt.title(f"Simulación Monte Carlo para {ticker}: {n_sim} Trayectorias")
plt.xlabel("Días")
plt.ylabel("Precio del Activo")
plt.grid(True)
plt.show()

# 5. ANÁLISIS DE LA DISTRIBUCIÓN FINAL
plt.figure(figsize=(12,6))
plt.hist(precios[-1], bins=250, color='skyblue', edgecolor='black')
plt.title(f"Distribución de Precios al Vencimiento (T) para {ticker}")
plt.xlabel("Precio Final")
plt.ylabel("Frecuencia")
plt.show()

# 6. CÁLCULO DE MÉTRICAS CLAVE
precio_final_promedio = np.mean(precios[-1])
valor_teorico = S0 * np.exp(r * T)
error_estandar = np.std(precios[-1]) / np.sqrt(n_sim)

print(f"--- RESULTADOS DE LA SIMULACIÓN ---")
print(f"Precio promedio final (Simulado): {precio_final_promedio:.2f}")
print(f"Precio teórico (Fórmula):         {valor_teorico:.2f}")
print(f"Error Estándar de la simulación:  {error_estandar:.4f}")

# 7. VISUALIZACIÓN DE LA CONVERGENCIA
# Veamos cómo cambia el promedio a medida que añadimos simulaciones
convergencia = np.cumsum(precios[-1]) / np.arange(1, n_sim + 1)

plt.figure(figsize=(10,5))
plt.plot(convergencia)
plt.axhline(valor_teorico, color='r', linestyle='--', label='Valor Teórico')
plt.title("Análisis de Convergencia de Monte Carlo")
plt.xlabel("Número de Simulaciones")
plt.ylabel("Precio Promedio")
plt.legend()
plt.show()

#_____________________________________________________________________________________________________________
z_score_95 = 1.96 # Z-score para un intervalo de confianza del 95%
z_score_99 = 2.576 # Z-score para un intervalo de confianza del 99%

# Calcular el margen de error para 99%
margen_de_error_99 = z_score_99 * error_estandar

# Calcular el intervalo de confianza para 99%
intervalo_inferior_99 = precio_final_promedio - margen_de_error_99
intervalo_superior_99 = precio_final_promedio + margen_de_error_99

print(f"Intervalo de Confianza del 99% para el Precio Final Simulado:")
print(f"  [{intervalo_inferior_99:.2f}, {intervalo_superior_99:.2f}]")
print(f"Esto significa que, con un 99% de confianza, el precio real al vencimiento caerá dentro de este rango.")


#____________________________________________________________________________________________________________


#VAR / CVAR
titulo("3. VAR / CVAR")

# 1. Descarga de datos
ticker = TICKER
# Añadimos auto_adjust=True para que 'Close' sea el precio ajustado
# Añadimos multi_level_index=False para evitar el error de acceso a columnas
data = yf.download(ticker, start=FECHA_INICIO, end=FECHA_FIN, auto_adjust=True, multi_level_index=False)

# Verificamos que se descargaron datos
if data.empty:
    print("Error: No se descargaron datos. Revisa tu conexión o el ticker.")
    sys.exit(1)
else:
    # Usamos 'Close' (que ya viene ajustado por auto_adjust=True)
    prices = data['Close']

# 2. Cálculo de Retornos Logarítmicos
# Usamos np.log y la función .shift(1)
returns = np.log(prices / prices.shift(1)).dropna()

print(f"Datos cargados correctamente: {len(returns)} días de trading para {ticker}")
print(returns.head()) # Mostramos los primeros 5 retornos


def calcular_metricas_riesgo(returns, confianza=0.95):
    """
    Calcula el VaR Histórico, Paramétrico y el CVaR en un solo paso.

    Parámetros:
    returns (Series): Retornos logarítmicos del activo.
    confianza (float): Nivel de confianza (0.95 o 0.99).
    """

    # --- 1. VaR Histórico ---
    # Simplemente buscamos el percentil (1 - confianza) en los datos reales
    var_h = np.percentile(returns, (1 - confianza) * 100)

    # --- 2. VaR Paramétrico (Normal) ---
    # Asumimos que los retornos siguen una campana de Gauss
    mu = returns.mean()
    sigma = returns.std()
    z_score = norm.ppf(1 - confianza)
    var_p = mu + (z_score * sigma)

    # --- 3. CVaR (Expected Shortfall) ---
    # Promedio de los retornos que fueron peores que el VaR Histórico
    peores_retornos = returns[returns <= var_h]
    cvar = peores_retornos.mean()

    return var_h, var_p, cvar

# Ejecución del cálculo para el nivel de confianza elegido (99% = estándar institucional)
conf = CONFIANZA / 100
v_hist, v_para, cv = calcular_metricas_riesgo(returns, confianza=conf)

print(f"--- Reporte de Riesgo para {ticker} ---")
print(f"Confianza: {conf*100}%")
print(f"VaR Histórico:   {v_hist:.2%}")
print(f"VaR Paramétrico: {v_para:.2%}")
print(f"CVaR (Pérdida en desastre): {cv:.2%}")

#Análisis de la Gráfica
plt.figure(figsize=(12, 6))

# Dibujamos el histograma de retornos
n, bins, patches = plt.hist(returns, bins=250, alpha=0.4, color='blue', label='Retornos Diarios')

# Sombreamos la zona de pérdida extrema (peor 1% o 5%)
for i in range(len(patches)):
    if bins[i] < v_hist:
        patches[i].set_facecolor('red')
        patches[i].set_alpha(0.6)

# Añadimos las líneas de las métricas
plt.axvline(v_hist, color='orange', linestyle='--', linewidth=2, label=f'VaR Histórico ({v_hist:.2%})')
plt.axvline(cv, color='darkred', linestyle='-', linewidth=2, label=f'CVaR ({cv:.2%})')

plt.title(f"Distribución de Retornos y Escenarios de Riesgo ({ticker})", fontsize=14)
plt.xlabel("Retorno Diario")
plt.ylabel("Frecuencia")
plt.legend()
plt.grid(alpha=0.2)
plt.show()





#______________________________________________________________________________________________________________
# Calcular retornos acumulados
cum_rets = (1 + returns).cumprod()

# Calcular Drawdowns (Caídas desde el máximo)
picos = cum_rets.cummax()
drawdowns = (cum_rets - picos) / picos

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10), sharex=True)

# Panel Superior: Crecimiento de $1000
cum_rets.plot(ax=ax1, color=["blue", "orange"])
ax1.set_title(f"Crecimiento de una Inversión de $1000 - {TICKER}", fontsize=14)
ax1.set_ylabel("Valor de la Inversión")
ax1.grid(alpha=0.3)

# Panel Inferior: El "Dolor" (Drawdowns)
drawdowns.plot(ax=ax2, kind='area', stacked=False, alpha=0.3, color=["blue", "orange"])
ax2.set_title("Drawdowns (Caídas desde máximos)", fontsize=14)
ax2.set_ylabel("Porcentaje de Caída")
ax2.grid(alpha=0.3)

plt.tight_layout()
plt.show()






#Sheet interactive
# Optional interactive/visual imports. Import at runtime so lint/analysis
# won't mark them unresolved when not installed in the environment.

titulo("4. SIMULADOR DE RIESGO SOBRE EL CAPITAL")

try:
    import ipywidgets as widgets
except Exception:  # pragma: no cover - optional dependency
    widgets = None

try:
    import seaborn as sns
except Exception:  # pragma: no cover - optional dependency
    sns = None

def simulador_riesgo_interactivo(ticker, confianza, inversion):
    # 1. Descarga rápida de datos
    df_inter = yf.download(ticker, start=FECHA_INICIO, auto_adjust=True, multi_level_index=False, progress=False)['Close']
    rets_inter = np.log(df_inter / df_inter.shift(1)).dropna()

    # 2. Cálculos de métricas
    # 'vp' not used below in this function; unpack to '_' to avoid unused-var warnings
    vh, _, cv = calcular_metricas_riesgo(rets_inter, confianza / 100)

    # 3. Impacto en Capital
    pérdida_var = inversion * vh
    pérdida_cvar = inversion * cv

    # 4. Visualización
    plt.figure(figsize=(12, 5))
    sns.histplot(rets_inter, bins=150, kde=True, color='BLACK', alpha=0.3)

    plt.axvline(vh, color='blue', lw=3, label=f'VaR {confianza}%: {vh:.2%}')
    plt.axvline(cv, color='red', lw=3, label=f'CVaR {confianza}%: {cv:.2%}')

    plt.title(f"Simulación de Riesgo: {ticker} | Capital en Riesgo: ${abs(pérdida_var):,.0f}", fontsize=15)
    plt.xlabel("Retorno Diario")
    plt.legend()
    plt.show()

    print(f"--- ANÁLISIS DE IMPACTO ---")
    print(f"Con una inversión de ${inversion:,.0f}:")
    print(f"En un día malo (VaR), podrías perder: ${abs(pérdida_var):,.2f}")
    print(f"En un día catastrófico (CVaR), la pérdida media sería: ${abs(pérdida_cvar):,.2f}")

# Creación de los controles.
# En Jupyter/Colab se muestran los sliders de siempre; en un script normal se
# ejecuta directamente con el ticker y los valores introducidos al arrancar.
if widgets is not None and EN_NOTEBOOK:
    widgets.interact(
        simulador_riesgo_interactivo,
        ticker=[TICKER, 'SPY', 'QQQ', 'BTC-USD', 'ETH-USD', 'TSLA', 'GOLD'],
        confianza=widgets.FloatSlider(min=90, max=99.9, step=0.1, value=CONFIANZA, description='Confianza %'),
        inversion=widgets.IntSlider(min=100, max=100000, step=10000, value=INVERSION, description='Inversión $')
    );
else:
    simulador_riesgo_interactivo(TICKER, CONFIANZA, INVERSION)




#__________________________________________________________________________________________

titulo("5. DASHBOARD DE PERFORMANCE")

def analizar_performance_profesional(precios, rf_anual=0.02):
    """
    Calcula métricas clave de rendimiento ajustado al riesgo.
    """
    # 1. Retornos diarios y acumulados
    rets = np.log(precios / precios.shift(1)).dropna()
    cum_rets = np.exp(rets.cumsum()) # Curva de equidad (base 1)

    # 2. Anualización de Retorno y Volatilidad
    # Usamos 252 como el número estándar de días de trading al año
    ret_anual = rets.mean() * 252
    vol_anual = rets.std() * np.sqrt(252)

    # 3. Sharpe Ratio
    sharpe = (ret_anual - rf_anual) / vol_anual

    # 4. Sortino Ratio (Volatilidad negativa)
    rets_negativos = rets[rets < 0]
    vol_downside = rets_negativos.std() * np.sqrt(252)
    sortino = (ret_anual - rf_anual) / vol_downside

    # 5. Maximum Drawdown (MDD)
    # Calculamos la caída desde el pico histórico en cada momento
    picos = cum_rets.cummax()
    drawdowns = (cum_rets - picos) / picos
    max_drawdown = drawdowns.min()

    # 6. Ratio de Calmar (Retorno / Max Drawdown)
    # Esencial para Hedge Funds: ¿Cuánto gano por cada unidad de caída máxima?
    calmar = ret_anual / abs(max_drawdown)

    return {
        "Retorno Anualizado": ret_anual,
        "Volatilidad Anual": vol_anual,
        "Sharpe Ratio": sharpe,
        "Sortino Ratio": sortino,
        "Max Drawdown": max_drawdown,
        "Ratio de Calmar": calmar,
        "Series_Drawdown": drawdowns,
        "Equity_Curve": cum_rets
    }

# --- EJECUCIÓN DEL CASO REAL ---
ticker_test = TICKER
datos = yf.download(ticker_test, start=FECHA_INICIO_PERF, auto_adjust=True, multi_level_index=False)['Close']

metrics = analizar_performance_profesional(datos)

# Imprimir resultados formateados
print(f"--- DASHBOARD DE PERFORMANCE: {ticker_test} ---")
for k, v in metrics.items():
    if isinstance(v, float):
        print(f"{k}: {v:.4f}" if "Ratio" in k else f"{k}: {v:.2%}")

# NOTA: en el original esta linea estaba dentro del bucle de arriba, lo que creaba
# una figura vacia por cada metrica. Sacada fuera, los calculos son identicos.
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10), sharex=True, gridspec_kw={'height_ratios': [2, 1]})

# Gráfico 1: Curva de Equidad
ax1.plot(metrics["Equity_Curve"], color='navy', lw=2)
ax1.set_title(f"Crecimiento de la Inversión (Base 1.0) - {ticker_test}", fontsize=14)
ax1.set_ylabel("Valor de la Cartera")
ax1.grid(alpha=0.3)

# Gráfico 2: Underwater Chart (Drawdown)
ax2.fill_between(metrics["Series_Drawdown"].index, metrics["Series_Drawdown"], 0, color='red', alpha=0.3)
ax2.plot(metrics["Series_Drawdown"], color='red', lw=1)
ax2.set_title("Drawdown Histórico", fontsize=12)
ax2.set_ylabel("% Caída")
# Ajuste para ver bien las caídas. Antes era fijo (-0.6): ahora se ensancha solo
# si el activo ha caido mas de un 60%, para no cortar la grafica.
ax2.set_ylim(min(-0.6, float(metrics["Series_Drawdown"].min()) * 1.1), 0.05)
ax2.grid(alpha=0.3)

plt.tight_layout()
plt.show()







#___________________________________________________________________________________________

titulo(f"6. COMPARATIVA {TICKER} vs {BENCHMARK}")

def dashboard_performance_avanzado(activo_1, activo_2, rf_pct):
    # 1. Descarga y Limpieza
    tickers = [activo_1, activo_2]
    df = yf.download(tickers, start=FECHA_INICIO_PERF, auto_adjust=True, multi_level_index=False, progress=False)['Close']
    rets = np.log(df / df.shift(1)).dropna()
    rf = rf_pct / 100

    # 2. Procesamiento de Métricas
    stats = {}
    for t in tickers:
        m = analizar_performance_profesional(df[t], rf_anual=rf)
        stats[t] = m

    # 3. Creación de Tabla Comparativa
    resumen = {t: {
        "Retorno Anual": f"{stats[t]['Retorno Anualizado']:.2%}",
        "Volatilidad": f"{stats[t]['Volatilidad Anual']:.2%}",
        "Sharpe Ratio": f"{stats[t]['Sharpe Ratio']:.2f}",
        "Max Drawdown": f"{stats[t]['Max Drawdown']:.2%}",
        "Ratio Calmar": f"{stats[t]['Ratio de Calmar']:.2f}"
    } for t in tickers}

    display(HTML(f"<h3>Análisis de Eficiencia: {activo_1} vs {activo_2}</h3>"))
    display(pd.DataFrame(resumen))

    # 4. Visualización Multi-Panel
    fig = plt.figure(figsize=(16, 12))
    gs = fig.add_gridspec(3, 2)

    # A. Equity Curve (Comparativa de Crecimiento)
    ax1 = fig.add_subplot(gs[0, :])
    for t in tickers:
        ax1.plot(stats[t]['Equity_Curve'], label=f"Crecimiento {t}", lw=2)
    ax1.set_title("Evolución del Capital (Base 1.0)")
    ax1.legend()
    ax1.grid(alpha=0.2)

    # B. Underwater Chart (Drawdowns)
    ax2 = fig.add_subplot(gs[1, :])
    colors = ['blue', 'orange']
    for i, t in enumerate(tickers):
        ax2.fill_between(stats[t]['Series_Drawdown'].index, stats[t]['Series_Drawdown'], 0, alpha=0.2, color=colors[i], label=f"DD {t}")
    ax2.set_title("Análisis del 'Dolor': Historial de Drawdowns")
    ax2.legend()
    ax2.grid(alpha=0.2)

    # C. Mapa Riesgo-Retorno (Scatter)
    ax3 = fig.add_subplot(gs[2, 0])
    vols = [stats[t]['Volatilidad Anual'] for t in tickers]
    returns = [stats[t]['Retorno Anualizado'] for t in tickers]
    sns.scatterplot(x=vols, y=returns, s=200, hue=tickers, ax=ax3)
    ax3.plot([0, max(vols)*1.1], [0, max(vols)*1.1], color='gray', ls='--', alpha=0.5, label='Sharpe 1.0')
    ax3.set_title("Ubicación en el Mapa de Riesgo-Retorno")
    ax3.set_xlabel("Volatilidad")
    ax3.set_ylabel("Retorno")
    ax3.legend()

    # D. Matriz de Correlación
    ax4 = fig.add_subplot(gs[2, 1])
    sns.heatmap(rets.corr(), annot=True, cmap='coolwarm', fmt=".2f", ax=ax4, cbar=False)
    ax4.set_title("Correlación de Retornos")

    plt.tight_layout()
    plt.show()

# Lanzamiento del Dashboard: el activo 1 es siempre el ticker introducido y el
# activo 2 el de comparacion. En Colab siguen apareciendo los desplegables.
if widgets is not None and EN_NOTEBOOK:
    widgets.interact(
        dashboard_performance_avanzado,
        activo_1=[TICKER, 'SPY', 'QQQ', 'DIA', 'EEM'],
        activo_2=[BENCHMARK, 'BTC-USD', 'ETH-USD', 'GLD', 'TLT'],
        rf_pct=widgets.FloatSlider(min=0, max=6, step=0.1, value=2.0, description='Tasa RF %')
    );
else:
    dashboard_performance_avanzado(TICKER, BENCHMARK, 2.0)


# =============================================================================
#  FIN - opcion de analizar otro activo sin tener que relanzar nada a mano
# =============================================================================
final_del_analisis()
