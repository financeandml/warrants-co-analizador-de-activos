"""Motor de DESCUENTO DE FLUJOS DE CAJA (DCF) del ANALIZADOR DE ACTIVOS.

Cinco metodos de valoracion, cada uno con su dominio de validez:

  1. FCFF - flujo libre a la empresa, descontado al WACC.
  2. FCFE - flujo libre al accionista, descontado al coste del capital propio.
  3. DDM  - descuento de dividendos (Gordon multietapa).
  4. APV  - valor ajustado: empresa sin deuda + escudo fiscal - coste esperado de quiebra.
  5. EVA  - beneficio economico: capital invertido + valor actual de los excesos de retorno.

Reglas heredadas del proyecto y que aqui son especialmente delicadas:

  - Nunca se inventa un dato. Si una partida no esta publicada, el metodo que la
    necesita se declara NO APLICABLE con su motivo, en lugar de rellenarse con
    cero, con una media o con una estimacion. Un DCF con un hueco tapado en
    silencio produce una cifra verosimil y falsa, que es el peor resultado
    posible.
  - Tres estados siempre: hay dato / el dato es cero / no hay dato.
  - Inferencia no es hecho: todo supuesto viaja con su origen y su motivo.

Sobre el enrutamiento por tipo de negocio: no es una cortesia, es aritmetica.
Un banco no publica EBIT ni capital circulante (comprobado contra JPM: Yahoo
devuelve None en ambos, y su "Free Cash Flow" declarado sale a -147.000 M$),
porque en una entidad financiera la deuda es materia prima y no estructura de
capital. FCFF, APV y EVA quedan bloqueados ahi por imposibilidad aritmetica, no
por preferencia metodologica.
"""

import numpy as np
import pandas as pd
import yfinance as yf

import motor_fundamentales as fund

# Se reutilizan los lectores de estados de motor_fundamentales en lugar de
# duplicarlos: ya resuelven el problema de que Yahoo devuelva un numero
# distinto de ejercicios en cada estado, que es la causa clasica de cruzar
# años diferentes sin darse cuenta.
_serie = fund._serie
_v = fund._v


# =============================================================================
#  ORIGEN DE CADA CIFRA
# =============================================================================
# Toda magnitud que entra en la valoracion se etiqueta. En el Excel la etiqueta
# viaja en su propia columna: quien lea el informe debe poder distinguir de un
# vistazo lo que la empresa publico de lo que decidio el analista.

DATO = "dato publicado"
DERIVADO = "derivado de datos publicados"
SUPUESTO = "supuesto del analista"

# Prima de riesgo de mercado por defecto. NO es un dato: es un punto de partida
# editable. Se corresponde con el orden de magnitud que Damodaran publica para
# el mercado estadounidense maduro (~4,3-4,5%). Viaja siempre rotulada como
# supuesto, nunca como cifra observada.
PRIMA_RIESGO_DEFECTO = 0.045

# Diferencial de credito por defecto cuando no hay deuda con coste observable.
SPREAD_SIN_DEUDA = 0.01

# Tipo marginal de referencia, usado SOLO cuando ningun ejercicio publicado
# ofrece una tasa efectiva utilizable. Es el tipo federal estadounidense sobre
# sociedades. No es un dato de la empresa y viaja siempre rotulado como
# supuesto: sirve para que una empresa con la fiscalidad distorsionada por
# perdidas siga siendo valorable, en lugar de quedarse sin ningun metodo.
TASA_FISCAL_MARGINAL_DEFECTO = 0.21

TICKER_TIPO_SIN_RIESGO = "^TNX"      # bono del Tesoro de EEUU a 10 años
TIPO_SIN_RIESGO_RESPALDO = 0.042

ANIOS_PROYECCION_DEFECTO = 10

# Por encima de este peso, el valor terminal manda tanto que el DCF deja de
# informar sobre la empresa y pasa a informar sobre el supuesto de crecimiento
# perpetuo.
UMBRAL_PESO_TERMINAL = 0.75


def _fin(x):
    """Cierto solo si x es un numero utilizable. Distingue 'no hay dato' de
    'el dato es cero': 0.0 devuelve True, NaN y None devuelven False."""
    if x is None:
        return False
    try:
        return bool(np.isfinite(float(x)))
    except (TypeError, ValueError):
        return False


def _num(x):
    return float(x) if _fin(x) else np.nan


# =============================================================================
#  1. LECTURA DE PARTIDAS
# =============================================================================

def partidas_dcf(estados):
    """Series anuales necesarias para el DCF, indexadas por año fiscal.

    Los signos se conservan TAL Y COMO los publica Yahoo, que sigue convencion
    de flujo de caja: la inversion en inmovilizado (`Capital Expenditure`) llega
    en negativo y la variacion de circulante llega ya como impacto en caja
    (negativo = consume caja). Normalizarlos aqui a "magnitud positiva" y luego
    restarlos en la formula es la via rapida a un error de signo que no se ve en
    pantalla, asi que el motor suma siempre lo que viene y lo documenta.
    """
    if not estados:
        return None
    r = estados.get("resultados")
    b = estados.get("balance")
    f = estados.get("flujo")

    amortizacion = _serie(f, ["Depreciation And Amortization",
                              "Depreciation Amortization Depletion", "Depreciation"])
    if amortizacion is None:
        # XOM no publica D&A en el estado de flujos pero si la conciliada en la
        # cuenta de resultados. Comprobado contra datos reales.
        amortizacion = _serie(r, ["Reconciled Depreciation"])

    return {
        # --- Cuenta de resultados ---
        "ingresos": _serie(r, ["Total Revenue", "Operating Revenue"]),
        "ebit": _serie(r, ["EBIT", "Operating Income", "Total Operating Income As Reported"]),
        "ebitda": _serie(r, ["EBITDA", "Normalized EBITDA"]),
        "beneficio_neto": _serie(r, ["Net Income Common Stockholders", "Net Income"]),
        "impuestos": _serie(r, ["Tax Provision"]),
        "bai": _serie(r, ["Pretax Income"]),
        "intereses": _serie(r, ["Interest Expense", "Interest Expense Non Operating"]),
        "acciones": _serie(r, ["Diluted Average Shares", "Basic Average Shares"]),
        # --- Flujo de caja (signo de origen: salidas en negativo) ---
        "amortizacion": amortizacion,
        "capex": _serie(f, ["Capital Expenditure", "Purchase Of PPE", "Net PPE Purchase And Sale"]),
        "var_circulante": _serie(f, ["Change In Working Capital"]),
        "flujo_operativo": _serie(f, ["Operating Cash Flow",
                                      "Cash Flow From Continuing Operating Activities"]),
        "dividendos": _serie(f, ["Cash Dividends Paid", "Common Stock Dividend Paid"]),
        "deuda_neta_emitida": _serie(f, ["Net Issuance Payments Of Debt"]),
        "recompras": _serie(f, ["Repurchase Of Capital Stock"]),
        # --- Balance ---
        "deuda_total": _serie(b, ["Total Debt"]),
        "caja": _serie(b, ["Cash And Cash Equivalents"]),
        "caja_amplia": _serie(b, ["Cash Cash Equivalents And Short Term Investments",
                                  "Cash And Cash Equivalents"]),
        "patrimonio": _serie(b, ["Stockholders Equity", "Common Stock Equity"]),
        "minoritarios": _serie(b, ["Minority Interest"]),
        "capital_invertido": _serie(b, ["Invested Capital"]),
        "ppe_neto": _serie(b, ["Net PPE"]),
        "circulante": _serie(b, ["Working Capital"]),
        "activos_totales": _serie(b, ["Total Assets"]),
        "acciones_balance": _serie(b, ["Ordinary Shares Number", "Share Issued"]),
    }


def anios_disponibles(p):
    """Ejercicios con ingresos REALMENTE publicados, de mas antiguo a mas reciente.

    Hay que filtrar por valor y no quedarse con el indice: Yahoo devuelve a veces
    un ejercicio con la etiqueta puesta y la cifra vacia. Colandolo, el primer
    año de la serie entra con ingresos NaN y cualquier CAGR calculado entre el
    primero y el ultimo sale NaN sin que nada lo advierta (comprobado en MMM y
    PFE, donde el crecimiento historico se perdia por completo).
    """
    if p is None or p.get("ingresos") is None:
        return []
    return [int(a) for a, v in p["ingresos"].items() if _fin(v)]


def tasa_impositiva_efectiva(p, anio):
    """Impuestos / beneficio antes de impuestos del ejercicio.

    Solo tiene sentido con base imponible positiva: con perdidas el cociente da
    un numero sin significado economico, y devolverlo como "tasa fiscal"
    contamina el NOPAT de toda la proyeccion.
    """
    imp, bai = _v(p["impuestos"], anio), _v(p["bai"], anio)
    if not (_fin(imp) and _fin(bai)) or bai <= 0:
        return np.nan
    return imp / bai


def tasa_impositiva_normalizada(p, anios):
    """Mediana de las tasas efectivas utilizables de los ejercicios disponibles.

    La mediana y no la media: un unico ejercicio con un ajuste fiscal
    extraordinario mueve la media lo bastante como para cambiar el valor por
    accion varios puntos porcentuales.
    """
    tasas = [tasa_impositiva_efectiva(p, a) for a in anios]
    utiles = [x for x in tasas if _fin(x) and 0.0 <= x <= 0.60]
    if utiles:
        return float(np.median(utiles)), len(utiles), DERIVADO
    # Sin ninguna tasa utilizable se recurre al tipo marginal, rotulado como
    # supuesto. Sin esta salida una empresa con la fiscalidad distorsionada se
    # quedaba sin valoracion: Intel declaro -3,2%, -119,8%, sin base imponible y
    # +98,3% en cuatro ejercicios seguidos, la tasa salia NaN, con ella el NOPAT
    # y detras el WACC, y los CINCO metodos morian a la vez. Encima el mensaje
    # culpaba a la beta, que estaba perfectamente publicada.
    return TASA_FISCAL_MARGINAL_DEFECTO, 0, SUPUESTO


# =============================================================================
#  2. MERCADO: TIPO SIN RIESGO, BETA, PRECIO
# =============================================================================

def tipo_sin_riesgo():
    """Rendimiento del bono estadounidense a 10 años (^TNX), en tanto por uno.

    Plazo a 10 años y no a 3 meses porque el DCF descuenta flujos a decada
    vista: el activo sin riesgo debe tener la duracion de aquello que descuenta.
    """
    try:
        h = yf.Ticker(TICKER_TIPO_SIN_RIESGO).history(period="1mo", auto_adjust=True)
        serie = h["Close"].dropna()
        if len(serie):
            return float(serie.iloc[-1]) / 100.0, f"^TNX a {serie.index[-1].date()}", DATO
    except Exception:
        pass
    return TIPO_SIN_RIESGO_RESPALDO, "valor de respaldo (^TNX no disponible)", SUPUESTO


def beta_regresion(simbolo, indice="^GSPC", periodo="5y"):
    """Beta por regresion de retornos MENSUALES contra el indice.

    Se recurre a ella cuando Yahoo no publica beta. Mensual y no diaria: la beta
    diaria de un valor poco liquido esta sesgada a la baja por negociacion
    asincrona (efecto Scholes-Williams).
    """
    try:
        datos = yf.download([simbolo, indice], period=periodo, interval="1mo",
                            progress=False, auto_adjust=True)
        cierres = datos["Close"] if isinstance(datos.columns, pd.MultiIndex) else datos
        cierres = cierres[[simbolo, indice]].dropna()
        if len(cierres) < 24:
            return np.nan, 0
        ret = cierres.pct_change().dropna()
        var = float(np.var(ret[indice], ddof=1))
        if var <= 0:
            return np.nan, len(ret)
        cov = float(np.cov(ret[simbolo], ret[indice], ddof=1)[0, 1])
        return cov / var, len(ret)
    except Exception:
        return np.nan, 0


def datos_mercado(simbolo, reintentos=2):
    """Precio, capitalizacion, acciones, beta, dividendo y sector.

    `Ticker.info` falla de forma intermitente (Yahoo limita peticiones), y un
    unico fallo dejaba sin capitalizacion a la empresa; sin capitalizacion no hay
    pesos de estructura de capital, sin pesos no hay WACC y sin WACC se caian los
    CINCO metodos a la vez. Intel llego a quedarse sin valorar por completo
    -- "falta beta o capitalizacion" -- teniendo beta 2,241 y 487.000 M de
    capitalizacion perfectamente publicados.
    """
    import time

    info = {}
    for intento in range(reintentos + 1):
        try:
            info = yf.Ticker(simbolo).info or {}
            if info.get("marketCap") or info.get("currentPrice"):
                break
        except Exception:
            info = {}
        if intento < reintentos:
            time.sleep(1.0 * (intento + 1))

    # Segunda via: fast_info es un extremo distinto de la API y suele responder
    # cuando info no lo hace.
    rapida = {}
    if not info.get("marketCap") or not info.get("currentPrice"):
        try:
            fi = yf.Ticker(simbolo).fast_info
            rapida = {"marketCap": fi.get("market_cap"), "currentPrice": fi.get("last_price"),
                      "sharesOutstanding": fi.get("shares"), "currency": fi.get("currency")}
        except Exception:
            rapida = {}

    def _campo(*claves):
        for c in claves:
            v = info.get(c)
            if v:
                return v
        for c in claves:
            v = rapida.get(c)
            if v:
                return v
        return None

    precio = _campo("currentPrice", "regularMarketPrice", "previousClose")
    # La beta se coteja SIEMPRE contra una regresion propia.
    #
    # Es el ingrediente con mas apalancamiento de toda la valoracion: entra en la
    # Ke, la Ke entra en el WACC y el WACC descuenta absolutamente todo. Y tiene
    # dos fuentes posibles -- la que publica el proveedor y la que sale de
    # regresar los retornos --, asi que hay que afirmar que concuerdan en lugar
    # de confiar en ello. En la muestra concuerdan casi siempre (Exxon 0,173
    # frente a 0,209; Caterpillar 1,605 frente a 1,589), pero AT&T da 0,417
    # publicada contra 0,234 regresada, y esos 0,18 de diferencia mueven la Ke
    # del 6,55% al 5,72%: casi un punto entero sobre el que se descuentan diez
    # años de flujos.
    beta_publicada = _num(info.get("beta"))
    beta_calculada, n_meses = beta_regresion(simbolo)

    if _fin(beta_publicada):
        beta, origen_beta = beta_publicada, DATO
    elif _fin(beta_calculada):
        beta, origen_beta = beta_calculada, DERIVADO
    else:
        beta, origen_beta = np.nan, "no disponible"

    desvio_beta = (abs(beta_publicada - beta_calculada)
                   if (_fin(beta_publicada) and _fin(beta_calculada)) else np.nan)

    acciones = _num(_campo("sharesOutstanding"))
    capitalizacion = _num(_campo("marketCap"))
    # Ultima via: si falta la capitalizacion pero hay precio y acciones, se
    # reconstruye. Es aritmetica sobre datos publicados, no una estimacion.
    if not _fin(capitalizacion) and _fin(precio) and _fin(acciones):
        capitalizacion = precio * acciones

    return {
        "precio": _num(precio),
        "acciones": acciones,
        "capitalizacion": capitalizacion,
        "beta": _num(beta),
        "origen_beta": origen_beta,
        "beta_publicada": beta_publicada,
        "beta_calculada": beta_calculada,
        "desvio_beta": desvio_beta,
        "meses_regresion_beta": n_meses,
        "dividendo_accion": _num(info.get("dividendRate")),
        "moneda": info.get("financialCurrency") or _campo("currency") or "",
        "nombre": info.get("longName") or info.get("shortName") or simbolo,
        "sector": info.get("sector") or "Desconocido",
        "industria": info.get("industry") or "Desconocida",
    }


# =============================================================================
#  3. COSTE DE CAPITAL
# =============================================================================

def coste_capital(mercado, p, anio, rf, prima, tasa_fiscal, spread_manual=None):
    """WACC y sus componentes, con pesos a valor de MERCADO.

    El peso del capital propio sale de la capitalizacion bursatil, no del
    patrimonio contable: el WACC descuenta flujos futuros y debe reflejar lo que
    hoy exigen quienes ponen el dinero, no lo que costo historicamente.

    La beta desapalancada (Hamada) se calcula aqui porque el APV la necesita:
    ese metodo descuenta la empresa como si no tuviera deuda.
    """
    deuda = _v(p["deuda_total"], anio)
    if not _fin(deuda):
        deuda, origen_deuda = 0.0, "no publicada; se toma 0"
    else:
        origen_deuda = DATO

    equity = mercado["capitalizacion"]
    if not _fin(equity) and _fin(mercado["precio"]) and _fin(mercado["acciones"]):
        equity = mercado["precio"] * mercado["acciones"]

    beta = mercado["beta"]
    ke = rf + beta * prima if _fin(beta) else np.nan

    # Coste de la deuda: gasto financiero sobre deuda MEDIA del ejercicio. Contra
    # la media y no el saldo de cierre porque el gasto se devenga a lo largo del
    # año; con el saldo final, una amortizacion de deuda en diciembre dispara el
    # coste aparente.
    intereses = _v(p["intereses"], anio)
    anios = anios_disponibles(p)
    previos = [a for a in anios if a < anio]
    deuda_prev = _v(p["deuda_total"], previos[-1]) if previos else np.nan
    candidatas = [d for d in (deuda, deuda_prev) if _fin(d)]
    deuda_media = float(np.mean(candidatas)) if candidatas else np.nan

    if spread_manual is not None:
        kd, origen_kd = rf + spread_manual, SUPUESTO
    elif _fin(intereses) and _fin(deuda_media) and deuda_media > 0:
        kd, origen_kd = intereses / deuda_media, DERIVADO
    else:
        kd, origen_kd = rf + SPREAD_SIN_DEUDA, SUPUESTO

    # Un coste de deuda por debajo del tipo sin riesgo no es posible en un
    # mercado sano: suele significar que Yahoo publica como gasto financiero un
    # neto que ya descuenta ingresos financieros. Se marca y se sustituye.
    kd_bruto, aviso_kd = kd, None
    if _fin(kd) and kd < rf:
        kd = rf + SPREAD_SIN_DEUDA
        aviso_kd = (f"El coste de deuda implicito ({kd_bruto:.2%}) quedaba por debajo del "
                    f"tipo sin riesgo ({rf:.2%}), señal de que el gasto financiero "
                    f"publicado va neto de ingresos financieros. Se sustituye por "
                    f"tipo sin riesgo + {SPREAD_SIN_DEUDA:.2%}.")

    total = (equity if _fin(equity) else 0.0) + deuda
    if total > 0 and _fin(equity):
        peso_e, peso_d = equity / total, deuda / total
    else:
        peso_e, peso_d = np.nan, np.nan

    t = tasa_fiscal if _fin(tasa_fiscal) else np.nan
    wacc = (peso_e * ke + peso_d * kd * (1 - t)) \
        if all(_fin(x) for x in (peso_e, peso_d, ke, kd, t)) else np.nan

    # Beta desapalancada de Hamada: bU = bL / (1 + (1-t) * D/E)
    de = (deuda / equity) if (_fin(equity) and equity > 0) else np.nan
    beta_u = beta / (1 + (1 - t) * de) if all(_fin(x) for x in (beta, t, de)) else np.nan
    ku = rf + beta_u * prima if _fin(beta_u) else np.nan

    return {
        "rf": rf, "prima": prima, "beta": beta, "beta_desapalancada": beta_u,
        "ke": ke, "ku": ku, "kd_bruto": kd_bruto, "kd": kd,
        "kd_despues_impuestos": kd * (1 - t) if _fin(t) else np.nan,
        "tasa_fiscal": t, "deuda": deuda, "equity": equity, "deuda_equity": de,
        "peso_equity": peso_e, "peso_deuda": peso_d, "wacc": wacc,
        "origen_kd": origen_kd, "origen_deuda": origen_deuda, "aviso_kd": aviso_kd,
        "intereses": intereses, "deuda_media": deuda_media,
    }


# =============================================================================
#  4. BASE HISTORICA Y RATIOS DE PROYECCION
# =============================================================================

def base_historica(p, anios, tasa_fiscal):
    """Cifras del ultimo ejercicio y ratios medios sobre ingresos.

    Los ratios se calculan como MEDIANA sobre los ejercicios disponibles: un
    solo año con una adquisicion grande convierte la media de capex/ventas en un
    numero que la empresa no repetira nunca.
    """
    if not anios:
        return None
    ultimo = anios[-1]
    ing = _v(p["ingresos"], ultimo)
    ebit = _v(p["ebit"], ultimo)

    def _ratio(clave, signo=1.0):
        vals = []
        for a in anios:
            v, i = _v(p[clave], a), _v(p["ingresos"], a)
            if _fin(v) and _fin(i) and i > 0:
                vals.append(signo * v / i)
        return (float(np.median(vals)), len(vals)) if vals else (np.nan, 0)

    margen_ebit, n_margen = _ratio("ebit")
    # capex llega negativo (salida de caja): se invierte el signo para
    # expresarlo como porcentaje de ventas invertido, que es como se lee.
    capex_ventas, n_capex = _ratio("capex", -1.0)
    amort_ventas, n_amort = _ratio("amortizacion")

    # Circulante necesario por euro de venta, tomado del NIVEL de balance.
    #
    # La via aparentemente natural -- dividir la variacion de circulante del
    # estado de flujos entre la variacion de ingresos -- es inestable, y no de
    # forma benigna: cuando los ingresos apenas se mueven el denominador tiende a
    # cero y el cociente explota. En 3M el ejercicio 2023->2024 da un ratio de
    # -149 (los ingresos cayeron 35 M mientras el circulante se movia 5.200 M) y
    # la mediana de los tres pares disponibles exigia 8,57 EUR de circulante por
    # cada EUR de venta adicional. Con eso, la inversion proyectada en circulante
    # se comia todo el flujo y la empresa salia valorada en -219 EUR por accion:
    # una cifra absurda que ninguna alarma habria cazado, porque cada paso
    # intermedio parecia razonable por separado.
    #
    # El nivel de circulante sobre ventas es estable por construccion y es el
    # supuesto estandar de modelizacion: si la empresa necesita hoy 15 centimos
    # de circulante por euro vendido, crecer un euro mas le exigira otros 15.
    niveles, pares = [], 0
    for a in anios:
        wc, ing_a = _v(p["circulante"], a), _v(p["ingresos"], a)
        if _fin(wc) and _fin(ing_a) and ing_a > 0:
            niveles.append(wc / ing_a)
            pares += 1
    circulante_incremental = float(np.median(niveles)) if niveles else np.nan
    # Un circulante superior a una vez las ventas no describe a una empresa
    # operativa. Se declara no utilizable en vez de arrastrarlo hasta el flujo.
    if _fin(circulante_incremental) and abs(circulante_incremental) > 1.0:
        circulante_incremental, pares = np.nan, 0

    # Crecimiento historico de ingresos (CAGR sobre el periodo disponible)
    i0, i1 = _v(p["ingresos"], anios[0]), _v(p["ingresos"], ultimo)
    n = len(anios) - 1
    if _fin(i0) and _fin(i1) and i0 > 0 and i1 > 0 and n > 0:
        cagr_ingresos = (i1 / i0) ** (1 / n) - 1
    else:
        cagr_ingresos = np.nan

    nopat = ebit * (1 - tasa_fiscal) if (_fin(ebit) and _fin(tasa_fiscal)) else np.nan

    # Capital invertido: el publicado por Yahoo si existe; si no, reconstruido
    # como deuda + patrimonio - caja, que es la definicion operativa.
    cap_inv = _v(p["capital_invertido"], ultimo)
    origen_ci = DATO
    if not _fin(cap_inv):
        d, pat, cj = (_v(p["deuda_total"], ultimo), _v(p["patrimonio"], ultimo),
                      _v(p["caja"], ultimo))
        if _fin(d) and _fin(pat):
            cap_inv = d + pat - (cj if _fin(cj) else 0.0)
            origen_ci = DERIVADO
    roic = nopat / cap_inv if (_fin(nopat) and _fin(cap_inv) and cap_inv > 0) else np.nan

    # Tasa de reinversion del ultimo ejercicio: (capex - amortizacion + var.
    # circulante) / NOPAT. Es el numerador del crecimiento fundamental.
    capex_u, amort_u, dwc_u = (_v(p["capex"], ultimo), _v(p["amortizacion"], ultimo),
                               _v(p["var_circulante"], ultimo))
    if all(_fin(x) for x in (capex_u, amort_u, nopat)) and nopat > 0:
        reinversion = (-capex_u - amort_u - (dwc_u if _fin(dwc_u) else 0.0)) / nopat
    else:
        reinversion = np.nan

    return {
        "anio": ultimo, "ingresos": ing, "ebit": ebit, "nopat": nopat,
        "ebitda": _v(p["ebitda"], ultimo),
        "beneficio_neto": _v(p["beneficio_neto"], ultimo),
        "amortizacion": _v(p["amortizacion"], ultimo),
        "capex": capex_u, "var_circulante": dwc_u,
        "margen_ebit": margen_ebit, "n_margen": n_margen,
        "capex_ventas": capex_ventas, "n_capex": n_capex,
        "amortizacion_ventas": amort_ventas, "n_amortizacion": n_amort,
        "circulante_incremental": circulante_incremental, "n_circulante": pares,
        "cagr_ingresos": cagr_ingresos, "n_anios": len(anios),
        "capital_invertido": cap_inv, "origen_capital_invertido": origen_ci,
        "roic": roic, "tasa_reinversion": reinversion,
        "deuda": _v(p["deuda_total"], ultimo), "caja": _v(p["caja"], ultimo),
        "caja_amplia": _v(p["caja_amplia"], ultimo),
        "patrimonio": _v(p["patrimonio"], ultimo),
        "minoritarios": _v(p["minoritarios"], ultimo),
        "dividendos": _v(p["dividendos"], ultimo),
        "acciones": _v(p["acciones"], ultimo),
        "acciones_balance": _v(p["acciones_balance"], ultimo),
    }


def fcff_historico(p, anios, tasa_fiscal):
    """FCFF de cada ejercicio publicado, con sus componentes.

    FCFF = EBIT*(1-t) + amortizacion + capex + variacion de circulante

    Se SUMAN capex y variacion de circulante porque ambos llegan ya con signo de
    flujo de caja (negativos cuando consumen caja). Escribir la formula con
    restas y magnitudes absolutas es el error de signo clasico y no se ve en
    pantalla: el resultado sigue pareciendo un numero razonable.
    """
    filas = []
    for a in anios:
        ebit = _v(p["ebit"], a)
        t = tasa_impositiva_efectiva(p, a)
        if not _fin(t):
            t = tasa_fiscal
        nopat = ebit * (1 - t) if (_fin(ebit) and _fin(t)) else np.nan
        amort = _v(p["amortizacion"], a)
        capex = _v(p["capex"], a)
        dwc = _v(p["var_circulante"], a)
        componentes = [nopat, amort, capex]
        fcff = (sum(componentes) + (dwc if _fin(dwc) else 0.0)) \
            if all(_fin(x) for x in componentes) else np.nan
        filas.append({
            "Ejercicio": a, "Ingresos": _v(p["ingresos"], a), "EBIT": ebit,
            "Tasa fiscal efectiva": t, "NOPAT": nopat, "Amortizacion": amort,
            "Capex (signo de origen)": capex, "Var. circulante (signo de origen)": dwc,
            "FCFF": fcff,
        })
    return pd.DataFrame(filas)


# =============================================================================
#  5. PROYECCION
# =============================================================================

def senda_crecimiento(g_inicial, g_terminal, n):
    """Crecimiento que converge LINEALMENTE de g_inicial a g_terminal.

    El desvanecimiento gradual evita el escalon que se produce al pasar de un
    crecimiento alto en el año n al perpetuo en el n+1: ese salto concentra un
    porcentaje irreal del valor en el valor terminal.
    """
    if n <= 1:
        return [g_terminal]
    return [g_inicial + (g_terminal - g_inicial) * (i / (n - 1)) for i in range(n)]


def proyectar(base, sup, coste):
    """Tabla de proyeccion explicita del FCFF, año a año.

    Cada linea es reconstruible a mano desde la anterior: es el requisito para
    que el Excel sirva de algo mas que de adorno.
    """
    n = sup["anios"]
    gs = senda_crecimiento(sup["g_inicial"], sup["g_terminal"], n)
    margenes = senda_crecimiento(base["margen_ebit"], sup["margen_objetivo"], n) \
        if _fin(base["margen_ebit"]) and _fin(sup["margen_objetivo"]) else [np.nan] * n

    t = coste["tasa_fiscal"]
    ingresos = base["ingresos"]
    filas = []
    for i in range(n):
        ingresos_prev = ingresos
        ingresos = ingresos * (1 + gs[i]) if _fin(ingresos) else np.nan
        ebit = ingresos * margenes[i] if (_fin(ingresos) and _fin(margenes[i])) else np.nan
        nopat = ebit * (1 - t) if (_fin(ebit) and _fin(t)) else np.nan
        amort = ingresos * base["amortizacion_ventas"] \
            if (_fin(ingresos) and _fin(base["amortizacion_ventas"])) else np.nan
        capex = ingresos * base["capex_ventas"] \
            if (_fin(ingresos) and _fin(base["capex_ventas"])) else np.nan
        d_ing = ingresos - ingresos_prev if (_fin(ingresos) and _fin(ingresos_prev)) else np.nan
        d_wc = d_ing * base["circulante_incremental"] \
            if (_fin(d_ing) and _fin(base["circulante_incremental"])) else 0.0
        fcff = nopat + amort - capex - d_wc \
            if all(_fin(x) for x in (nopat, amort, capex, d_wc)) else np.nan
        filas.append({
            "Año": i + 1, "Crecimiento ingresos": gs[i], "Ingresos": ingresos,
            "Margen EBIT": margenes[i], "EBIT": ebit, "Tasa fiscal": t, "NOPAT": nopat,
            "Amortizacion": amort, "Capex": capex, "Inversion en circulante": d_wc,
            "FCFF": fcff,
        })
    return pd.DataFrame(filas)


def descontar(flujos, tasa, mitad_periodo=False):
    """Valor actual de una lista de flujos en los años 1..n.

    Con convencion de mitad de periodo el exponente es t-0.5, que reconoce que
    una empresa cobra a lo largo del año y no el 31 de diciembre. Sube el valor
    en torno a un 2-3% con tasas normales.
    """
    if not _fin(tasa):
        return np.nan, []
    factores, vp = [], 0.0
    for i, f in enumerate(flujos, start=1):
        exp = i - 0.5 if mitad_periodo else i
        factor = 1.0 / (1 + tasa) ** exp
        factores.append(factor)
        if _fin(f):
            vp += f * factor
    return vp, factores


def valor_terminal_gordon(flujo_ultimo, tasa, g):
    """Perpetuidad creciente: VT = flujo_n * (1+g) / (tasa - g).

    Exige tasa > g. Si no se cumple, la formula devuelve un numero negativo o
    astronomico segun el lado por el que se cruce, y ninguno de los dos es una
    valoracion: es una division por un numero que tiende a cero.
    """
    if not all(_fin(x) for x in (flujo_ultimo, tasa, g)):
        return np.nan, "faltan datos"
    if tasa <= g:
        return np.nan, (f"la tasa de descuento ({tasa:.2%}) no supera al crecimiento "
                        f"perpetuo ({g:.2%}): la perpetuidad no converge")
    if flujo_ultimo <= 0:
        return np.nan, (f"el flujo del ultimo año proyectado es negativo o cero "
                        f"({flujo_ultimo:,.0f}): capitalizarlo daria un valor terminal "
                        f"negativo sin sentido economico")
    return flujo_ultimo * (1 + g) / (tasa - g), None


def puente_a_capital(valor_empresa, base, mercado, incluir_inversiones=True):
    """De valor de empresa a valor por accion.

    Capital = EV - deuda + caja - minoritarios

    Los minoritarios se RESTAN porque el flujo proyectado es el de la empresa
    consolidada, del que una parte no pertenece al accionista de la matriz.
    Olvidarlos sobrevalora sistematicamente los holdings.
    """
    if not _fin(valor_empresa):
        return {"valor_empresa": np.nan, "valor_capital": np.nan, "valor_accion": np.nan,
                "acciones": np.nan, "detalle": []}

    caja = base["caja_amplia"] if (incluir_inversiones and _fin(base["caja_amplia"])) else base["caja"]
    deuda = base["deuda"] if _fin(base["deuda"]) else 0.0
    minor = base["minoritarios"] if _fin(base["minoritarios"]) else 0.0
    caja_v = caja if _fin(caja) else 0.0

    capital = valor_empresa - deuda + caja_v - minor

    acciones = mercado["acciones"]
    if not _fin(acciones):
        acciones = base["acciones_balance"] if _fin(base["acciones_balance"]) else base["acciones"]

    detalle = [
        ("Valor de empresa (EV)", valor_empresa),
        ("- Deuda total", -deuda),
        ("+ Caja e inversiones a corto", caja_v),
        ("- Intereses minoritarios", -minor),
        ("= Valor del capital", capital),
    ]
    return {
        "valor_empresa": valor_empresa, "valor_capital": capital,
        "valor_accion": capital / acciones if (_fin(acciones) and acciones > 0) else np.nan,
        "acciones": acciones, "deuda": deuda, "caja": caja_v, "minoritarios": minor,
        "detalle": detalle,
    }


# =============================================================================
#  6. LOS CINCO METODOS
# =============================================================================

def falta_para_wacc(coste):
    """Que ingrediente concreto impide calcular el WACC.

    Un mensaje generico manda a revisar lo que no es: el caso de Intel se
    diagnosticaba como "falta beta o capitalizacion" teniendo las dos. Lo que
    faltaba era la tasa fiscal.
    """
    faltan = []
    if not _fin(coste.get("beta")):
        faltan.append("la beta")
    if not _fin(coste.get("equity")):
        faltan.append("la capitalizacion bursatil")
    if not _fin(coste.get("tasa_fiscal")):
        faltan.append("la tasa fiscal")
    if not _fin(coste.get("kd")):
        faltan.append("el coste de la deuda")
    if not faltan:
        faltan.append("algun componente de la estructura de capital")
    return " y ".join(faltan)


def motivo_valor_no_positivo(nombre, valor_accion):
    """Motivo por el que un valor negativo NO se publica como valoracion.

    El capital tiene responsabilidad limitada: no puede valer menos de cero, asi
    que "-70,15 por accion" no es una valoracion baja, es una valoracion que no
    significa nada. Sale cuando la empresa consume caja con su estructura de
    margenes actual (Intel y Boeing en la muestra), y proyectar a perpetuidad el
    margen mediano de una empresa en plena reconversion es justamente el uso
    para el que un DCF mecanico no sirve.

    No se acota a cero en silencio -- eso seria inventar una cifra -- sino que se
    declara no aplicable, se dice por que, y se señala el mando con el que el
    analista puede modelizar la recuperacion si quiere.
    """
    return (f"El valor resultante es negativo ({valor_accion:,.2f} por accion). Con la "
            f"estructura de margenes de los ultimos ejercicios la empresa consume caja, y un "
            f"DCF mecanico no puede valorar eso: el capital tiene responsabilidad limitada y "
            f"no puede valer menos de cero. Para valorarla hay que modelizar explicitamente la "
            f"recuperacion — ajusta el «Margen EBIT objetivo» en los supuestos y vuelve a "
            f"calcular.")


def _resultado(nombre, aplicable, motivo=None, **kw):
    r = {"metodo": nombre, "aplicable": aplicable, "motivo": motivo,
         "valor_accion": np.nan, "valor_capital": np.nan, "valor_empresa": np.nan,
         "peso_terminal": np.nan, "avisos": []}
    r.update(kw)
    return r


# --- 1. FCFF ----------------------------------------------------------------

def valorar_fcff(proy, base, coste, mercado, sup, bloqueo=None):
    """Valor de la empresa como valor actual del FCFF descontado al WACC.

    El valor terminal usa reinversion COHERENTE con el crecimiento perpetuo:
    en estado estacionario una empresa que crece al g% debe reinvertir g/ROIC de
    su NOPAT. Proyectar crecimiento perpetuo sin reinvertir para sostenerlo es
    el error mas comun del DCF de manual, y regala valor gratis.
    """
    if bloqueo:
        return _resultado("FCFF (WACC)", False, bloqueo)
    wacc, g = coste["wacc"], sup["g_terminal"]
    if not _fin(wacc):
        return _resultado("FCFF (WACC)", False,
                          f"no se ha podido calcular el WACC: falta {falta_para_wacc(coste)}")
    if proy.empty or proy["FCFF"].isna().all():
        return _resultado("FCFF (WACC)", False,
                          "no hay FCFF proyectable: falta EBIT, capex o amortizacion")

    flujos = proy["FCFF"].tolist()
    vp_explicito, factores = descontar(flujos, wacc, sup["mitad_periodo"])

    nopat_n = proy["NOPAT"].iloc[-1]
    roic_estable = sup["roic_estable"]
    if _fin(nopat_n) and _fin(roic_estable) and roic_estable > 0 and _fin(g):
        tasa_reinv = g / roic_estable
        fcff_terminal = nopat_n * (1 + g) * (1 - tasa_reinv)
        nota_reinv = (f"Reinversion terminal = g/ROIC = {g:.2%}/{roic_estable:.2%} "
                      f"= {tasa_reinv:.1%} del NOPAT")
    else:
        fcff_terminal = flujos[-1] * (1 + g) if (_fin(flujos[-1]) and _fin(g)) else np.nan
        tasa_reinv = np.nan
        nota_reinv = "Sin ROIC estable utilizable: el valor terminal extiende el ultimo FCFF"

    if _fin(fcff_terminal) and _fin(wacc) and _fin(g) and wacc > g:
        vt = fcff_terminal / (wacc - g)
        motivo_vt = None
    else:
        vt, motivo_vt = valor_terminal_gordon(flujos[-1], wacc, g)

    if not _fin(vt):
        return _resultado("FCFF (WACC)", False, f"valor terminal no calculable: {motivo_vt}")

    exp = len(flujos) - 0.5 if sup["mitad_periodo"] else len(flujos)
    vp_terminal = vt / (1 + wacc) ** exp
    ev = vp_explicito + vp_terminal
    puente = puente_a_capital(ev, base, mercado)

    avisos = []
    peso = vp_terminal / ev if (_fin(ev) and ev != 0) else np.nan
    if _fin(peso) and peso > UMBRAL_PESO_TERMINAL:
        avisos.append(f"El valor terminal pesa el {peso:.0%} del total. Por encima del "
                      f"{UMBRAL_PESO_TERMINAL:.0%} la valoracion habla mas del supuesto de "
                      f"crecimiento perpetuo que de la empresa.")
    if _fin(puente["valor_accion"]) and puente["valor_accion"] <= 0:
        return _resultado("FCFF (WACC)", False,
                          motivo_valor_no_positivo("FCFF", puente["valor_accion"]),
                          valor_empresa=ev, diagnostico_valor=puente["valor_accion"])
    return _resultado("FCFF (WACC)", True, None,
                      valor_empresa=ev, valor_capital=puente["valor_capital"],
                      valor_accion=puente["valor_accion"], peso_terminal=peso,
                      vp_explicito=vp_explicito, vp_terminal=vp_terminal,
                      valor_terminal_bruto=vt, flujo_terminal=fcff_terminal,
                      tasa_reinversion_terminal=tasa_reinv, nota_reinversion=nota_reinv,
                      tasa=wacc, factores=factores, puente=puente, avisos=avisos)


# --- 2. FCFE ----------------------------------------------------------------

def valorar_fcfe_financiera(base, coste, mercado, sup):
    """FCFE de una entidad financiera, por el lado del capital propio.

    En un banco no hay EBIT ni capital circulante que valgan, asi que la ruta
    normal (FCFF menos intereses mas endeudamiento neto) no existe. La via
    correcta parte del beneficio neto y descuenta la RETENCION DE CAPITAL
    REGULATORIO, que en una entidad financiera funciona exactamente como la
    reinversion en inmovilizado de una industrial: un banco que repartiese el
    100% del beneficio veria congelado su patrimonio y, al crecer el credito,
    acabaria por debajo del minimo regulatorio.

        FCFE = beneficio neto x (1 - g / ROE)

    donde g/ROE es la fraccion del beneficio que hay que retener para sostener
    ese crecimiento. Es la formulacion de Damodaran para servicios financieros.
    """
    ke = coste["ke"]
    bn, pat = base["beneficio_neto"], base["patrimonio"]
    if not _fin(ke):
        return _resultado("FCFE (entidad financiera)", False,
                          "no hay beta utilizable, asi que no hay coste del capital propio")
    if not (_fin(bn) and _fin(pat)) or pat <= 0:
        return _resultado("FCFE (entidad financiera)", False,
                          "faltan beneficio neto o patrimonio neto publicados")
    if bn <= 0:
        return _resultado("FCFE (entidad financiera)", False,
                          f"el beneficio neto del ultimo ejercicio no es positivo "
                          f"({bn:,.0f}): no hay base sobre la que retener capital")

    roe = bn / pat
    n = sup["anios"]
    gs = senda_crecimiento(min(sup["g_inicial"], roe if roe > 0 else sup["g_terminal"]),
                           sup["g_terminal"], n)

    filas, flujos, beneficio = [], [], bn
    for i in range(n):
        beneficio = beneficio * (1 + gs[i])
        retencion = gs[i] / roe if roe > 0 else np.nan
        # Una retencion superior al 100% significa que el crecimiento supuesto no
        # se sostiene con el beneficio: exigiria ampliar capital.
        retencion = min(retencion, 1.0) if _fin(retencion) else np.nan
        fcfe = beneficio * (1 - retencion) if _fin(retencion) else np.nan
        filas.append({"Año": i + 1, "Crecimiento": gs[i], "Beneficio neto": beneficio,
                      "Retencion de capital regulatorio": retencion, "FCFE": fcfe})
        flujos.append(fcfe)

    if not any(_fin(f) for f in flujos):
        return _resultado("FCFE (entidad financiera)", False,
                          "el ROE no permite derivar la retencion de capital")

    vp_explicito, factores = descontar(flujos, ke, sup["mitad_periodo"])
    vt, motivo = valor_terminal_gordon(flujos[-1], ke, sup["g_terminal"])
    if not _fin(vt):
        return _resultado("FCFE (entidad financiera)", False,
                          f"valor terminal no calculable: {motivo}",
                          tabla=pd.DataFrame(filas))

    exp = n - 0.5 if sup["mitad_periodo"] else n
    vp_terminal = vt / (1 + ke) ** exp
    capital = vp_explicito + vp_terminal
    acciones = mercado["acciones"] if _fin(mercado["acciones"]) else base["acciones_balance"]

    avisos = ["Valorado por la via del capital propio: beneficio neto menos la retencion "
              "de capital regulatorio que exige crecer. En una entidad financiera el valor "
              "de empresa y el FCFF no tienen significado economico."]
    if roe < coste["ke"]:
        avisos.append(f"El ROE ({roe:.1%}) es inferior al coste del capital propio "
                      f"({coste['ke']:.1%}): la entidad destruye valor sobre el capital "
                      f"que emplea, y deberia cotizar por debajo de su valor contable.")
    _vaf = capital / acciones if (_fin(acciones) and acciones > 0) else np.nan
    if _fin(_vaf) and _vaf <= 0:
        return _resultado("FCFE (entidad financiera)", False,
                          motivo_valor_no_positivo("FCFE", _vaf), diagnostico_valor=_vaf)
    return _resultado("FCFE (entidad financiera)", True, None,
                      valor_capital=capital,
                      valor_accion=capital / acciones if (_fin(acciones) and acciones > 0) else np.nan,
                      peso_terminal=vp_terminal / capital if capital else np.nan,
                      vp_explicito=vp_explicito, vp_terminal=vp_terminal,
                      valor_terminal_bruto=vt, tasa=ke, roe=roe,
                      tabla=pd.DataFrame(filas), factores=factores, avisos=avisos)


def valorar_fcfe(proy, base, coste, mercado, sup, p, anios, bloqueo=None, via_financiera=False,
                 res_fcff=None):
    """Valor del capital como valor actual del FCFE descontado al coste del capital propio.

    FCFE = FCFF - intereses*(1-t) + endeudamiento neto

    Se descuenta al Ke y NO al WACC, y el resultado es directamente el valor del
    capital: no hay puente que restar deuda. Descontar el FCFE al WACC y despues
    restar la deuda es un doble descuento del apalancamiento, error frecuente.
    """
    # Solo las financieras DE BALANCE se desvian a la via del capital propio. Una
    # red de pagos etiquetada como financiera publica EBIT y circulante, asi que
    # su FCFE se calcula por la ruta ordinaria como el de cualquier industrial.
    if via_financiera:
        return valorar_fcfe_financiera(base, coste, mercado, sup)
    if bloqueo:
        return _resultado("FCFE (coste del capital propio)", False, bloqueo)
    ke = coste["ke"]
    if not _fin(ke):
        return _resultado("FCFE (coste del capital propio)", False,
                          "no hay beta utilizable, asi que no hay coste del capital propio")
    if proy.empty or proy["FCFF"].isna().all():
        return _resultado("FCFE (coste del capital propio)", False,
                          "no hay FCFF proyectable del que partir")

    t = coste["tasa_fiscal"]
    intereses = coste["intereses"]
    if not _fin(intereses):
        intereses = 0.0

    # Endeudamiento neto: la empresa financia con deuda una FRACCION CONSTANTE de
    # su reinversion, igual al peso que la deuda tiene hoy en su estructura de
    # capital a valor de mercado.
    #
    #     endeudamiento neto = delta x (capex - amortizacion + inversion en circulante)
    #
    # Es la formulacion estandar, y la unica coherente con descontar a una Ke
    # fija: la Ke depende del apalancamiento, asi que solo vale si el
    # apalancamiento se mantiene.
    #
    # Antes la deuda crecia al ritmo de los INGRESOS, y eso rompia justamente esa
    # coherencia. En Oracle, con un crecimiento inicial del 17,9%, la deuda
    # pasaba de 156.000 a 405.000 M en diez años: el endeudamiento neto del
    # primer año salia +27.900 M contra un FCFF de 9.950 M, de modo que casi todo
    # el "flujo al accionista" era dinero prestado. El valor del capital se iba a
    # 307.000 M frente a los 166.000 M de la ruta FCFF -- un 85% mas -- mientras
    # la Ke seguia siendo la de una empresa mucho menos endeudada.
    delta = coste["peso_deuda"] if _fin(coste["peso_deuda"]) else 0.0
    deuda = coste["deuda"]
    filas, flujos = [], []
    deuda_prev = deuda
    for _, fila in proy.iterrows():
        componentes = (fila["Capex"], fila["Amortizacion"], fila["Inversion en circulante"])
        if all(_fin(x) for x in componentes):
            reinversion = fila["Capex"] - fila["Amortizacion"] + fila["Inversion en circulante"]
        else:
            reinversion = np.nan
        endeudamiento_neto = delta * reinversion if _fin(reinversion) else 0.0
        if _fin(deuda_prev) and _fin(coste["kd"]):
            int_periodo = deuda_prev * coste["kd"]
        else:
            int_periodo = intereses
        int_desp_imp = int_periodo * (1 - t) if (_fin(int_periodo) and _fin(t)) else np.nan
        if all(_fin(x) for x in (fila["FCFF"], int_desp_imp, endeudamiento_neto)):
            fcfe = fila["FCFF"] - int_desp_imp + endeudamiento_neto
        else:
            fcfe = np.nan
        filas.append({
            "Año": fila["Año"], "FCFF": fila["FCFF"], "Deuda inicio": deuda_prev,
            "Reinversion": reinversion, "Intereses": int_periodo,
            "Intereses despues de impuestos": int_desp_imp,
            "Endeudamiento neto": endeudamiento_neto, "FCFE": fcfe,
        })
        flujos.append(fcfe)
        if _fin(endeudamiento_neto) and _fin(deuda_prev):
            deuda_prev = deuda_prev + endeudamiento_neto

    tabla = pd.DataFrame(filas)
    if not any(_fin(f) for f in flujos):
        return _resultado("FCFE (coste del capital propio)", False,
                          "el FCFE no es calculable con las partidas disponibles",
                          tabla=tabla)

    vp_explicito, factores = descontar(flujos, ke, sup["mitad_periodo"])

    # El flujo terminal se construye desde el FCFF terminal, que YA lleva la
    # reinversion coherente con el crecimiento perpetuo (g/ROIC).
    #
    # Haciendo crecer sin mas el ultimo FCFE al g -- que es lo que hacia antes --
    # se concede crecimiento perpetuo sin exigir la inversion que lo sostiene, y
    # ademas se prolonga para siempre un endeudamiento neto positivo como si
    # fuera caja gratis. En Pfizer eso inflaba el valor terminal hasta 197.000 M
    # sobre un valor de empresa de 175.000 M por el FCFF completo: el FCFE salia
    # 46,22 EUR frente a 21,81 del FCFF, mas del doble por dos rutas que llevan
    # al mismo sitio.
    g = sup["g_terminal"]
    if (res_fcff is not None and res_fcff.get("aplicable")
            and _fin(res_fcff.get("flujo_terminal")) and _fin(deuda_prev) and _fin(t)):
        intereses_terminal = deuda_prev * coste["kd"] if _fin(coste["kd"]) else 0.0
        # Misma regla que en el periodo explicito: la deuda financia la fraccion
        # delta de la reinversion terminal, que vale NOPAT_(n+1) x (g / ROIC).
        nopat_ultimo = proy["NOPAT"].iloc[-1]
        nopat_terminal = nopat_ultimo * (1 + g) if _fin(nopat_ultimo) else np.nan
        roic_est = sup.get("roic_estable")
        if all(_fin(x) for x in (nopat_terminal, roic_est, g)) and roic_est > 0:
            reinversion_terminal = nopat_terminal * (g / roic_est)
        else:
            reinversion_terminal = 0.0
        endeudamiento_terminal = delta * reinversion_terminal
        flujo_terminal = (res_fcff["flujo_terminal"] - intereses_terminal * (1 - t)
                          + endeudamiento_terminal)
        origen_terminal = ("derivado del FCFF terminal, que ya incorpora la reinversion "
                           "coherente con el crecimiento perpetuo")
    else:
        flujo_terminal = flujos[-1] * (1 + g) if _fin(flujos[-1]) else np.nan
        origen_terminal = "extension del ultimo FCFE proyectado (el FCFF no estaba disponible)"

    if _fin(flujo_terminal) and _fin(ke) and ke > g and flujo_terminal > 0:
        vt, motivo = flujo_terminal / (ke - g), None
    else:
        vt, motivo = valor_terminal_gordon(flujo_terminal, ke, g)
    if not _fin(vt):
        return _resultado("FCFE (coste del capital propio)", False,
                          f"valor terminal no calculable: {motivo}", tabla=tabla)

    exp = len(flujos) - 0.5 if sup["mitad_periodo"] else len(flujos)
    vp_terminal = vt / (1 + ke) ** exp
    capital_operativo = vp_explicito + vp_terminal

    # HAY QUE SUMAR LOS ACTIVOS NO OPERATIVOS.
    #
    # El FCFE de este metodo se deriva del FCFF, que mide UNICAMENTE flujos
    # operativos: la caja excedente y las inversiones a corto no generan FCFF,
    # asi que su valor no esta dentro de lo descontado. La deuda, en cambio, ya
    # esta descontada dentro del propio flujo (intereses y endeudamiento neto),
    # de modo que aqui se suma la caja pero NO se resta la deuda: restarla seria
    # contarla dos veces.
    #
    # Omitir este paso costaba la caja entera de la empresa. En Tesla, con 29.300
    # M de caja neta sobre 3.950 M de acciones, el FCFE salia 8,23 EUR frente a
    # los 15,93 del FCFF: menos de la mitad. Y 8,23 es un numero perfectamente
    # verosimil, que es exactamente lo que hacia el fallo invisible.
    caja = base["caja_amplia"] if _fin(base["caja_amplia"]) else base["caja"]
    caja = caja if _fin(caja) else 0.0
    capital = capital_operativo + caja

    acciones = mercado["acciones"] if _fin(mercado["acciones"]) else base["acciones_balance"]

    avisos = []
    peso = vp_terminal / capital if (_fin(capital) and capital != 0) else np.nan
    if _fin(peso) and peso > UMBRAL_PESO_TERMINAL:
        avisos.append(f"El valor terminal pesa el {peso:.0%} del total.")
    _va = capital / acciones if (_fin(acciones) and acciones > 0) else np.nan
    if _fin(_va) and _va <= 0:
        return _resultado("FCFE (coste del capital propio)", False,
                          motivo_valor_no_positivo("FCFE", _va), diagnostico_valor=_va)
    return _resultado("FCFE (coste del capital propio)", True, None,
                      valor_capital=capital, capital_operativo=capital_operativo,
                      caja_no_operativa=caja, flujo_terminal=flujo_terminal,
                      origen_valor_terminal=origen_terminal,
                      valor_accion=capital / acciones if (_fin(acciones) and acciones > 0) else np.nan,
                      peso_terminal=peso, vp_explicito=vp_explicito, vp_terminal=vp_terminal,
                      valor_terminal_bruto=vt, tasa=ke, tabla=tabla, factores=factores,
                      avisos=avisos)


# --- 3. DDM -----------------------------------------------------------------

def valorar_ddm(base, coste, mercado, sup, p, anios):
    """Descuento de dividendos en dos fases (crecimiento + perpetuidad).

    Solo aplica a empresas que reparten dividendo. En una que no reparte, el
    modelo no es "impreciso": vale cero, y ese cero no dice nada sobre la
    empresa. Se declara no aplicable en lugar de devolverlo.
    """
    ke = coste["ke"]
    dividendos = base["dividendos"]
    dpa = mercado["dividendo_accion"]
    acciones = mercado["acciones"] if _fin(mercado["acciones"]) else base["acciones_balance"]

    if not _fin(ke):
        return _resultado("DDM (descuento de dividendos)", False,
                          "no hay beta utilizable, asi que no hay coste del capital propio")

    # El dividendo por accion declarado por el proveedor es preferible al total
    # pagado dividido por acciones: el segundo mezcla el pago a preferentes.
    if _fin(dpa) and dpa > 0:
        d0, origen = dpa, "dividendo anual por accion publicado"
    elif _fin(dividendos) and dividendos < 0 and _fin(acciones) and acciones > 0:
        d0, origen = -dividendos / acciones, "dividendos pagados / acciones en circulacion"
    else:
        return _resultado("DDM (descuento de dividendos)", False,
                          "la empresa no reparte dividendo, o no lo publica: el modelo de "
                          "descuento de dividendos no es aplicable")

    if d0 <= 0:
        return _resultado("DDM (descuento de dividendos)", False,
                          "el dividendo por accion calculado no es positivo")

    # Crecimiento sostenible: g = ROE * (1 - pay-out). Es el ritmo al que puede
    # crecer el dividendo sin financiarse fuera.
    bn, pat = base["beneficio_neto"], base["patrimonio"]
    roe = bn / pat if (_fin(bn) and _fin(pat) and pat > 0) else np.nan
    payout = (-dividendos / bn) if (_fin(dividendos) and _fin(bn) and bn > 0) else np.nan
    g_sost = roe * (1 - payout) if (_fin(roe) and _fin(payout)) else np.nan

    g_ini = sup["g_dividendo"] if _fin(sup.get("g_dividendo")) else \
        (g_sost if _fin(g_sost) else sup["g_terminal"])
    # El crecimiento del dividendo en la fase explicita no puede ser mayor que
    # el coste del capital propio: seria una perpetuidad divergente disfrazada.
    if _fin(ke) and g_ini >= ke:
        g_ini = ke - 0.005

    n = sup["anios"]
    gs = senda_crecimiento(g_ini, sup["g_terminal"], n)
    filas, flujos, d = [], [], d0
    for i in range(n):
        d = d * (1 + gs[i])
        filas.append({"Año": i + 1, "Crecimiento dividendo": gs[i], "Dividendo por accion": d})
        flujos.append(d)

    vp_explicito, factores = descontar(flujos, ke, sup["mitad_periodo"])
    vt, motivo = valor_terminal_gordon(flujos[-1], ke, sup["g_terminal"])
    if not _fin(vt):
        return _resultado("DDM (descuento de dividendos)", False,
                          f"valor terminal no calculable: {motivo}")

    exp = n - 0.5 if sup["mitad_periodo"] else n
    vp_terminal = vt / (1 + ke) ** exp
    valor_accion = vp_explicito + vp_terminal

    avisos = []
    if _fin(payout) and payout > 1.0:
        avisos.append(f"El pay-out es del {payout:.0%}: la empresa reparte mas de lo que gana, "
                      f"asi que el dividendo actual no es sostenible sin deuda o venta de activos.")
    if _fin(g_sost) and _fin(sup["g_terminal"]) and g_sost < sup["g_terminal"]:
        avisos.append(f"El crecimiento sostenible por fundamentales ({g_sost:.2%}) es menor que "
                      f"el perpetuo supuesto ({sup['g_terminal']:.2%}).")
    if _fin(valor_accion) and valor_accion <= 0:
        return _resultado("DDM (descuento de dividendos)", False,
                          motivo_valor_no_positivo("DDM", valor_accion),
                          diagnostico_valor=valor_accion)
    return _resultado("DDM (descuento de dividendos)", True, None,
                      valor_accion=valor_accion,
                      valor_capital=valor_accion * acciones if _fin(acciones) else np.nan,
                      peso_terminal=vp_terminal / valor_accion if valor_accion else np.nan,
                      vp_explicito=vp_explicito, vp_terminal=vp_terminal, tasa=ke,
                      dividendo_base=d0, origen_dividendo=origen, roe=roe, payout=payout,
                      g_sostenible=g_sost, g_inicial=g_ini,
                      tabla=pd.DataFrame(filas), factores=factores, avisos=avisos)


# --- 4. APV -----------------------------------------------------------------

def valorar_apv(proy, base, coste, mercado, sup, bloqueo=None):
    """Valor ajustado: empresa sin deuda + escudo fiscal - coste esperado de quiebra.

    A diferencia del FCFF, el APV NO mete el efecto fiscal de la deuda dentro de
    la tasa de descuento: lo valora aparte y a la vista. Por eso es el metodo
    correcto cuando la estructura de capital va a cambiar, y por eso descuenta
    al coste del capital SIN apalancar (Ku), no al WACC.
    """
    if bloqueo:
        return _resultado("APV (valor actual ajustado)", False, bloqueo)
    ku = coste["ku"]
    if not _fin(ku):
        return _resultado("APV (valor actual ajustado)", False,
                          "no se ha podido desapalancar la beta (falta beta, deuda o "
                          "capitalizacion), asi que no hay coste de capital sin deuda")
    if proy.empty or proy["FCFF"].isna().all():
        return _resultado("APV (valor actual ajustado)", False, "no hay FCFF proyectable")

    flujos = proy["FCFF"].tolist()
    g, t = sup["g_terminal"], coste["tasa_fiscal"]

    vp_sin_deuda, factores = descontar(flujos, ku, sup["mitad_periodo"])
    vt_u, motivo = valor_terminal_gordon(flujos[-1], ku, g)
    if not _fin(vt_u):
        return _resultado("APV (valor actual ajustado)", False,
                          f"valor terminal sin deuda no calculable: {motivo}")
    exp = len(flujos) - 0.5 if sup["mitad_periodo"] else len(flujos)
    vp_vt_u = vt_u / (1 + ku) ** exp
    valor_sin_deuda = vp_sin_deuda + vp_vt_u

    # Escudo fiscal: se descuenta al coste de la DEUDA, no al Ku. El ahorro
    # fiscal tiene el mismo riesgo que los intereses que lo generan.
    deuda, kd = coste["deuda"], coste["kd"]
    filas, escudos = [], []
    deuda_prev = deuda
    for _, fila in proy.iterrows():
        gi = fila["Crecimiento ingresos"]
        intereses = deuda_prev * kd if (_fin(deuda_prev) and _fin(kd)) else np.nan
        escudo = intereses * t if (_fin(intereses) and _fin(t)) else np.nan
        filas.append({"Año": fila["Año"], "Deuda inicio": deuda_prev,
                      "Intereses": intereses, "Escudo fiscal": escudo})
        escudos.append(escudo)
        deuda_prev = deuda_prev * (1 + gi) if (_fin(deuda_prev) and _fin(gi)) else deuda_prev

    vp_escudo, _ = descontar(escudos, kd, sup["mitad_periodo"])
    if _fin(escudos[-1]) and _fin(kd) and _fin(g) and kd > g:
        vt_escudo = escudos[-1] * (1 + g) / (kd - g)
        vp_vt_escudo = vt_escudo / (1 + kd) ** exp
    else:
        vt_escudo, vp_vt_escudo = np.nan, 0.0
    valor_escudo = (vp_escudo if _fin(vp_escudo) else 0.0) + vp_vt_escudo

    # Coste esperado de quiebra = probabilidad x coste. La probabilidad se toma
    # del apalancamiento observado mediante una escala explicita; no es un dato
    # de mercado y viaja rotulada como supuesto.
    prob = sup["probabilidad_quiebra"]
    coste_quiebra = sup["coste_quiebra"] * valor_sin_deuda \
        if (_fin(sup["coste_quiebra"]) and _fin(valor_sin_deuda)) else np.nan
    esperado = prob * coste_quiebra if (_fin(prob) and _fin(coste_quiebra)) else 0.0

    ev = valor_sin_deuda + valor_escudo - esperado
    puente = puente_a_capital(ev, base, mercado)

    if _fin(puente["valor_accion"]) and puente["valor_accion"] <= 0:
        return _resultado("APV (valor actual ajustado)", False,
                          motivo_valor_no_positivo("APV", puente["valor_accion"]),
                          valor_empresa=ev, diagnostico_valor=puente["valor_accion"])
    return _resultado("APV (valor actual ajustado)", True, None,
                      valor_empresa=ev, valor_capital=puente["valor_capital"],
                      valor_accion=puente["valor_accion"],
                      peso_terminal=vp_vt_u / ev if (_fin(ev) and ev) else np.nan,
                      valor_sin_deuda=valor_sin_deuda, valor_escudo=valor_escudo,
                      coste_quiebra_esperado=esperado, tasa=ku, tabla=pd.DataFrame(filas),
                      puente=puente, factores=factores,
                      avisos=[f"Probabilidad de quiebra supuesta {prob:.1%} sobre un coste del "
                              f"{sup['coste_quiebra']:.0%} del valor sin deuda. Es un supuesto "
                              f"explicito, no una estimacion de mercado."])


# --- 5. EVA -----------------------------------------------------------------

def valorar_eva(proy, base, coste, mercado, sup, bloqueo=None, res_fcff=None):
    """Beneficio economico: capital invertido + valor actual de los excesos de retorno.

    EVA_t = NOPAT_t - WACC * capital invertido al inicio del periodo

    FCFF y EVA no son dos modelos: son la misma valoracion escrita de dos formas,
    y la identidad que los une es exacta:

        IC_0 + suma VA(EVA_t) = suma VA(FCFF_t) + VA(IC_n)

    de donde el valor terminal del EVA sale del terminal del FCFF menos el
    capital invertido acumulado: VT_EVA = VT_FCFF - IC_n.

    Aqui estaba el fallo original: cada metodo capitalizaba su propio flujo
    terminal por separado -- el FCFF con reinversion coherente (g/ROIC) y el EVA
    haciendo crecer el ultimo EVA al g --. Al ser dos fuentes distintas para el
    mismo hecho, discrepaban entre un 3% y un 55% segun la empresa (comprobado
    en T, PFE, NVDA y MMM), y ninguna de las dos cifras avisaba de nada por
    separado. Ahora el valor terminal tiene UNA fuente y la comprobacion de
    coherencia afirma la igualdad en lugar de darla por supuesta.
    """
    if bloqueo:
        return _resultado("EVA (beneficio economico)", False, bloqueo)
    wacc = coste["wacc"]
    cap_inicial = base["capital_invertido"]
    if not _fin(wacc):
        return _resultado("EVA (beneficio economico)", False,
                          f"no se ha podido calcular el WACC: falta {falta_para_wacc(coste)}")
    if not _fin(cap_inicial) or cap_inicial <= 0:
        return _resultado("EVA (beneficio economico)", False,
                          "no hay capital invertido publicado ni reconstruible: el metodo "
                          "parte de el, y suponerlo desvirtuaria todo el resultado")
    if proy.empty or proy["NOPAT"].isna().all():
        return _resultado("EVA (beneficio economico)", False, "no hay NOPAT proyectable")

    # El EVA necesita la REINVERSION, no solo el NOPAT: es lo que hace crecer el
    # capital invertido de un ejercicio al siguiente, y el capital es la base
    # sobre la que se cobra el cargo por coste de capital.
    #
    # Sin ella el capital se queda congelado y el metodo concede crecimiento
    # gratis: en Realty Income, que no publica inversion en inmovilizado en
    # ningun ejercicio, el NOPAT proyectado subia de 2.530 a 4.444 M mientras el
    # capital invertido seguia clavado en 68.233 M los diez años. El FCFF si se
    # bloqueaba por la misma carencia, pero el EVA seguia adelante y devolvia
    # 55,45 EUR por accion: una cifra del todo verosimil levantada sobre una
    # empresa que crece sin invertir.
    reinversion_proyectada = (proy["Capex"] - proy["Amortizacion"]
                              + proy["Inversion en circulante"])
    if reinversion_proyectada.isna().any():
        faltan = [c for c in ("Capex", "Amortizacion", "Inversion en circulante")
                  if proy[c].isna().any()]
        return _resultado(
            "EVA (beneficio economico)", False,
            f"no se puede proyectar la reinversion (falta {', '.join(faltan)}), asi que el "
            f"capital invertido se quedaria congelado mientras el NOPAT crece. Eso concede "
            f"crecimiento sin la inversion que lo sostiene, y el valor resultante no "
            f"significaria nada.")

    filas, evas = [], []
    capital = cap_inicial
    for _, fila in proy.iterrows():
        nopat = fila["NOPAT"]
        cargo = capital * wacc if _fin(capital) else np.nan
        eva = nopat - cargo if (_fin(nopat) and _fin(cargo)) else np.nan
        roic_periodo = nopat / capital if (_fin(nopat) and _fin(capital) and capital > 0) else np.nan
        # La reinversion del periodo aumenta el capital invertido del siguiente.
        reinv = fila["Capex"] - fila["Amortizacion"] + fila["Inversion en circulante"] \
            if all(_fin(x) for x in (fila["Capex"], fila["Amortizacion"],
                                     fila["Inversion en circulante"])) else np.nan
        filas.append({
            "Año": fila["Año"], "Capital invertido inicio": capital, "NOPAT": nopat,
            "ROIC": roic_periodo, "Cargo por capital (WACC x capital)": cargo,
            "EVA": eva, "Reinversion del periodo": reinv,
        })
        evas.append(eva)
        if _fin(reinv) and _fin(capital):
            capital = capital + reinv

    vp_eva, factores = descontar(evas, wacc, sup["mitad_periodo"])
    g = sup["g_terminal"]
    capital_final = capital

    # UNA sola fuente para el valor terminal: el del FCFF, menos el capital
    # invertido acumulado al final del periodo explicito.
    if res_fcff is not None and res_fcff.get("aplicable") and _fin(res_fcff.get("valor_terminal_bruto")):
        vt_eva = res_fcff["valor_terminal_bruto"] - capital_final
        origen_vt = "derivado del valor terminal del FCFF (VT_EVA = VT_FCFF - capital invertido)"
    else:
        # Sin FCFF disponible se capitaliza el ultimo EVA. Un EVA terminal
        # negativo es un resultado legitimo -- la empresa destruye valor en
        # estado estacionario --, no un fallo, asi que se conserva.
        vt_eva, motivo = valor_terminal_gordon(evas[-1], wacc, g)
        if not _fin(vt_eva):
            if _fin(evas[-1]) and evas[-1] <= 0 and wacc > g:
                vt_eva = evas[-1] * (1 + g) / (wacc - g)
            else:
                return _resultado("EVA (beneficio economico)", False,
                                  f"valor terminal del EVA no calculable: {motivo}")
        origen_vt = "capitalizacion del ultimo EVA (el FCFF no estaba disponible)"

    exp = len(evas) - 0.5 if sup["mitad_periodo"] else len(evas)
    vp_vt_eva = vt_eva / (1 + wacc) ** exp
    suma_componentes = cap_inicial + vp_eva + vp_vt_eva

    # El valor de empresa tiene UNA sola fuente: la del FCFF. El EVA no es otro
    # modelo, es otra lectura del mismo -- cuanto del valor ya esta invertido y
    # cuanto lo añade la gestion --, asi que no puede devolver un numero
    # distinto.
    #
    # La identidad IC_0 + suma VA(EVA) = suma VA(FCFF) + VA(IC_n) es exacta con
    # descuento a fin de periodo (verificado: la diferencia sale 0,0000% en toda
    # la muestra). Con la convencion de mitad de periodo aparece un desfase real
    # e inevitable, porque esa convencion adelanta medio año los FLUJOS pero no
    # puede adelantar un SALDO de balance: el capital invertido en t=0 esta en
    # t=0. El desfase se calcula y se publica como partida propia en lugar de
    # dejar que dos cifras del mismo hecho discrepen en silencio.
    if res_fcff is not None and res_fcff.get("aplicable") and _fin(res_fcff.get("valor_empresa")):
        ev = res_fcff["valor_empresa"]
        ajuste_convencion = ev - suma_componentes
    else:
        ev = suma_componentes
        ajuste_convencion = 0.0

    puente = puente_a_capital(ev, base, mercado)

    avisos = []
    if _fin(evas[0]) and evas[0] < 0:
        avisos.append("El EVA del primer año proyectado es negativo: al ritmo actual la "
                      "empresa no cubre el coste del capital que emplea.")
    if _fin(puente["valor_accion"]) and puente["valor_accion"] <= 0:
        return _resultado("EVA (beneficio economico)", False,
                          motivo_valor_no_positivo("EVA", puente["valor_accion"]),
                          valor_empresa=ev, diagnostico_valor=puente["valor_accion"])
    return _resultado("EVA (beneficio economico)", True, None,
                      valor_empresa=ev, valor_capital=puente["valor_capital"],
                      valor_accion=puente["valor_accion"],
                      capital_inicial=cap_inicial, capital_final=capital_final,
                      origen_valor_terminal=origen_vt, suma_componentes=suma_componentes,
                      ajuste_convencion=ajuste_convencion,
                      vp_eva=vp_eva, vp_terminal=vp_vt_eva,
                      peso_terminal=vp_vt_eva / ev if (_fin(ev) and ev) else np.nan,
                      tasa=wacc, tabla=pd.DataFrame(filas), puente=puente,
                      factores=factores, avisos=avisos)


# =============================================================================
#  7. ENRUTAMIENTO POR TIPO DE NEGOCIO
# =============================================================================

def bloqueos_por_sector(clasificacion, p, anios):
    """Que metodos quedan prohibidos y por que.

    Devuelve {metodo: motivo}. Un metodo con motivo NO se calcula: devolver una
    cifra imposible con una nota al pie no sirve de nada, porque la cifra es lo
    que se recuerda.
    """
    bloqueos = {}
    if not anios:
        return {"FCFF": "no hay ejercicios con datos", "FCFE": "no hay ejercicios con datos",
                "APV": "no hay ejercicios con datos", "EVA": "no hay ejercicios con datos",
                "DDM": "no hay ejercicios con datos"}
    ultimo = anios[-1]

    # El bloqueo lo decide la EVIDENCIA ESTRUCTURAL, no la etiqueta del sector.
    #
    # "Financial Services" de Yahoo mete en el mismo cajon a un banco y a una red
    # de pagos. Visa, Mastercard, S&P Global, BlackRock y PayPal salen ahi
    # etiquetados, y sin embargo publican EBIT y capital circulante con total
    # normalidad: Visa declara 26.600 M de EBIT, un margen del 67% y un ROIC del
    # 35%. Bloquearles el valor de empresa por su etiqueta les quitaba tres de
    # los cinco metodos sin ningun motivo real.
    #
    # Lo que de verdad impide el marco de valor de empresa es que la empresa no
    # publique EBIT o no publique circulante, porque entonces su balance ES el
    # negocio. Eso ocurre en JPM, BAC, GS, AXP y Berkshire, y no ocurre en Visa.
    # La etiqueta es una inferencia; la ausencia de la partida es un hecho.
    sin_ebit = not _fin(_v(p["ebit"], ultimo))
    sin_circulante = not _fin(_v(p["circulante"], ultimo))
    es_balance = bool(clasificacion and clasificacion.get("es_financiera")
                      and (sin_ebit or sin_circulante))

    if es_balance:
        que_falta = []
        if sin_ebit:
            que_falta.append("EBIT")
        if sin_circulante:
            que_falta.append("capital circulante")
        motivo = (f"Entidad financiera de balance: la deuda es materia prima del negocio, no "
                  f"estructura de capital, y no publica {' ni '.join(que_falta)} en {ultimo}. "
                  f"El valor de empresa y el FCFF carecen aqui de significado economico. Se "
                  f"valora por FCFE de capital regulatorio y descuento de dividendos.")
        bloqueos["FCFF"] = motivo
        bloqueos["APV"] = motivo
        bloqueos["EVA"] = motivo
        # El FCFE NO se bloquea: para una financiera de balance existe la via del
        # capital propio (beneficio neto menos retencion de capital regulatorio),
        # que no necesita EBIT. Se marca para que el bloqueo generico por falta
        # de EBIT que viene despues no la alcance, y para que el FCFE sepa que
        # debe tomar esa via y no la ordinaria.
        bloqueos["_financiera"] = True

    # Bloqueo por AUSENCIA de partida, que es independiente del sector y manda
    # sobre cualquier clasificacion: sin EBIT no hay NOPAT, y sin NOPAT no hay
    # FCFF por mucho que la empresa sea industrial.
    if sin_ebit:
        motivo = f"no hay EBIT publicado en el ejercicio {ultimo}"
        bloqueos.setdefault("FCFF", motivo)
        bloqueos.setdefault("APV", motivo)
        bloqueos.setdefault("EVA", motivo)
        if not bloqueos.get("_financiera"):
            bloqueos.setdefault("FCFE", motivo + " (el FCFE parte del FCFF)")
    if not _fin(_v(p["capex"], ultimo)) and not _fin(_v(p["amortizacion"], ultimo)):
        motivo = f"no hay inversion en inmovilizado ni amortizacion en {ultimo}"
        bloqueos.setdefault("FCFF", motivo)
        bloqueos.setdefault("APV", motivo)
        if not bloqueos.get("_financiera"):
            bloqueos.setdefault("FCFE", motivo)
    return bloqueos


def avisos_por_sector(clasificacion):
    """Advertencias metodologicas propias del tipo de negocio."""
    if not clasificacion:
        return []
    tipo = clasificacion.get("tipo", "")
    if tipo == "Inmobiliaria o REIT":
        return ["En un REIT la amortizacion contable de inmuebles no refleja deterioro "
                "economico real, asi que el FCFF infravalora el flujo disponible. La "
                "referencia del sector es el FFO/AFFO y el valor neto de los activos (NAV). "
                "El DCF de abajo es valido como contraste, no como valoracion principal."]
    if tipo == "Ciclica":
        return ["Negocio ciclico: si el ultimo ejercicio esta en pico o en valle de ciclo, "
                "proyectar desde el margen actual arrastra ese punto del ciclo a perpetuidad. "
                "Conviene comparar el margen EBIT base con la mediana de los ejercicios "
                "disponibles, que aparece en la hoja de supuestos."]
    if tipo == "Entidad financiera":
        return ["Entidad financiera: el crecimiento exige capital regulatorio, que funciona "
                "como reinversion obligatoria. Un FCFE que no descuente esa retencion "
                "sobrevalora el reparto disponible."]
    return []


# =============================================================================
#  8. SUPUESTOS
# =============================================================================

def supuestos_por_defecto(base, coste, rf):
    """Punto de partida de los supuestos, derivado de la propia empresa.

    El crecimiento perpetuo se ancla al tipo sin riesgo y no a un 2,5% de manual:
    a largo plazo el tipo nominal sin riesgo converge al crecimiento nominal de
    la economia, asi que es su mejor aproximacion observable. La regla dura que
    de ahi se sigue -- g perpetuo <= tipo sin riesgo -- se aplica siempre, porque
    ninguna empresa puede crecer indefinidamente mas que la economia que la
    contiene sin acabar siendo mayor que ella.
    """
    g_terminal = min(rf, 0.03) if _fin(rf) else 0.025

    g_hist = base.get("cagr_ingresos")
    g_fund = base["tasa_reinversion"] * base["roic"] \
        if (_fin(base.get("tasa_reinversion")) and _fin(base.get("roic"))) else np.nan

    candidatos = [g for g in (g_hist, g_fund) if _fin(g) and -0.20 < g < 0.60]
    g_inicial = float(np.median(candidatos)) if candidatos else g_terminal

    roic_estable = base["roic"] if (_fin(base.get("roic")) and 0 < base["roic"] < 0.60) \
        else (coste["wacc"] if _fin(coste.get("wacc")) else np.nan)

    return {
        "anios": ANIOS_PROYECCION_DEFECTO,
        "g_inicial": g_inicial,
        "g_terminal": g_terminal,
        "margen_objetivo": base.get("margen_ebit"),
        "roic_estable": roic_estable,
        "mitad_periodo": True,
        "g_dividendo": np.nan,
        "probabilidad_quiebra": 0.02,
        "coste_quiebra": 0.30,
        "origen_g_inicial": ("mediana de crecimiento historico y fundamental (reinversion x ROIC)"
                             if candidatos else "sin base historica utilizable: se iguala al perpetuo"),
        "g_historico": g_hist, "g_fundamental": g_fund,
    }


def validar_supuestos(sup, coste, rf):
    """Reglas duras que un DCF no puede violar sin dejar de significar nada."""
    errores, avisos = [], []
    g, wacc, ke = sup["g_terminal"], coste.get("wacc"), coste.get("ke")

    if _fin(g) and _fin(rf) and g > rf + 0.0001:
        avisos.append(
            f"El crecimiento perpetuo ({g:.2%}) supera al tipo sin riesgo ({rf:.2%}). "
            f"A largo plazo el tipo nominal sin riesgo converge al crecimiento nominal de "
            f"la economia, asi que una empresa que crece mas que el, para siempre, acaba "
            f"siendo mayor que la economia entera.")
    if _fin(g) and _fin(wacc) and g >= wacc:
        errores.append(f"El crecimiento perpetuo ({g:.2%}) iguala o supera al WACC "
                       f"({wacc:.2%}): la perpetuidad no converge y el FCFF, el APV y el "
                       f"EVA quedan sin valor terminal.")
    if _fin(g) and _fin(ke) and g >= ke:
        errores.append(f"El crecimiento perpetuo ({g:.2%}) iguala o supera al coste del "
                       f"capital propio ({ke:.2%}): el FCFE y el DDM quedan sin valor terminal.")
    if _fin(sup["g_inicial"]) and sup["g_inicial"] > 0.40:
        avisos.append(f"El crecimiento inicial ({sup['g_inicial']:.1%}) es muy alto. Sostenerlo "
                      f"diez años implica multiplicar los ingresos por "
                      f"{(1 + sup['g_inicial']) ** sup['anios']:.1f}.")
    return errores, avisos


# =============================================================================
#  9. ORQUESTACION
# =============================================================================

def analizar(simbolo, sup_usuario=None, prima=PRIMA_RIESGO_DEFECTO, spread_manual=None,
             estados=None, clasificacion=None):
    """Ejecuta el DCF completo sobre un valor y devuelve todo lo calculado.

    Devuelve siempre un diccionario: si algo falla, `error` explica que falto.
    Nunca devuelve una valoracion parcial haciendola pasar por completa.
    """
    salida = {"simbolo": simbolo, "error": None}

    if estados is None:
        estados = fund.estados_financieros(simbolo)
    if not estados:
        salida["error"] = ("Yahoo Finance no publica estados financieros para este valor. "
                           "Suele ocurrir con indices, divisas, materias primas, ETFs y "
                           "algunos valores no estadounidenses.")
        return salida

    p = partidas_dcf(estados)
    anios = anios_disponibles(p)
    if not anios:
        salida["error"] = "No hay ningun ejercicio con ingresos publicados."
        return salida

    mercado = datos_mercado(simbolo)
    if clasificacion is None:
        clasificacion = fund.clasificar_negocio(simbolo)

    rf, origen_rf, tipo_rf = tipo_sin_riesgo()
    tasa_fiscal, n_tasas, origen_tasa = tasa_impositiva_normalizada(p, anios)
    coste = coste_capital(mercado, p, anios[-1], rf, prima, tasa_fiscal, spread_manual)
    base = base_historica(p, anios, tasa_fiscal)

    if base is None or not _fin(base["ingresos"]):
        salida["error"] = "No hay ingresos utilizables en el ultimo ejercicio publicado."
        return salida

    sup = supuestos_por_defecto(base, coste, rf)
    if sup_usuario:
        sup.update({k: v for k, v in sup_usuario.items() if v is not None})

    errores, avisos_sup = validar_supuestos(sup, coste, rf)
    proy = proyectar(base, sup, coste)
    bloqueos = bloqueos_por_sector(clasificacion, p, anios)

    # El FCFF se calcula PRIMERO porque el EVA toma de el su valor terminal: son
    # la misma valoracion escrita de dos formas y el terminal debe tener una
    # sola fuente.
    r_fcff = valorar_fcff(proy, base, coste, mercado, sup, bloqueos.get("FCFF"))
    metodos = [
        r_fcff,
        valorar_fcfe(proy, base, coste, mercado, sup, p, anios, bloqueos.get("FCFE"),
                     bool(bloqueos.get("_financiera")), r_fcff),
        valorar_ddm(base, coste, mercado, sup, p, anios) if not bloqueos.get("DDM")
        else _resultado("DDM (descuento de dividendos)", False, bloqueos["DDM"]),
        valorar_apv(proy, base, coste, mercado, sup, bloqueos.get("APV")),
        valorar_eva(proy, base, coste, mercado, sup, bloqueos.get("EVA"), r_fcff),
    ]

    salida.update({
        "estados": estados, "partidas": p, "anios": anios, "mercado": mercado,
        "clasificacion": clasificacion, "rf": rf, "origen_rf": origen_rf,
        "tipo_origen_rf": tipo_rf, "prima": prima, "tasa_fiscal": tasa_fiscal,
        "n_tasas_usadas": n_tasas, "origen_tasa_fiscal": origen_tasa,
        "tasas_efectivas": {a: tasa_impositiva_efectiva(p, a) for a in anios},
        "coste": coste, "base": base, "supuestos": sup,
        "proyeccion": proy, "bloqueos": bloqueos, "metodos": metodos,
        "errores_supuestos": errores, "avisos_supuestos": avisos_sup,
        "avisos_sector": avisos_por_sector(clasificacion),
        "historico_fcff": fcff_historico(p, anios, tasa_fiscal),
        "resumen": resumen_metodos(metodos, mercado),
        "sensibilidad": sensibilidad(base, coste, mercado, sup),
        "coherencia": coherencia_fcff_eva(metodos),
    })
    return salida


def resumen_metodos(metodos, mercado):
    """Tabla comparativa de los cinco metodos frente al precio de mercado."""
    precio = mercado.get("precio")
    filas = []
    for m in metodos:
        va = m["valor_accion"]
        filas.append({
            "Metodo": m["metodo"],
            "Aplicable": "Si" if m["aplicable"] else "No",
            "Valor por accion": va if m["aplicable"] else np.nan,
            "Precio de mercado": precio,
            "Potencial": (va / precio - 1) if (_fin(va) and _fin(precio) and precio > 0) else np.nan,
            "Peso del valor terminal": m.get("peso_terminal", np.nan),
            "Tasa de descuento": m.get("tasa", np.nan),
            "Motivo si no aplica": m["motivo"] or "",
        })
    return pd.DataFrame(filas)


def estadisticos_valoracion(metodos, mercado):
    """Mediana y rango de los metodos APLICABLES.

    Mediana y no media: con cinco metodos, uno que se dispare por un supuesto
    extremo arrastra la media hasta un numero que ningun metodo sostiene.
    """
    valores = [m["valor_accion"] for m in metodos if m["aplicable"] and _fin(m["valor_accion"])]
    if not valores:
        return {"n": 0, "mediana": np.nan, "minimo": np.nan, "maximo": np.nan,
                "potencial_mediana": np.nan}
    precio = mercado.get("precio")
    mediana = float(np.median(valores))
    return {
        "n": len(valores), "mediana": mediana,
        "minimo": float(min(valores)), "maximo": float(max(valores)),
        "potencial_mediana": (mediana / precio - 1) if (_fin(precio) and precio > 0) else np.nan,
    }


def coherencia_fcff_eva(metodos):
    """Comprueba que FCFF y EVA dan el mismo valor de empresa.

    Son dos formas algebraicamente equivalentes de escribir lo mismo, asi que
    una diferencia grande no es ruido de redondeo: senala una incoherencia entre
    la reinversion proyectada y el crecimiento supuesto. Se afirma la igualdad
    en lugar de confiar en ella, que es justo el tipo de fallo que no se ve en
    pantalla porque cada cifra por separado parece razonable.
    """
    por_nombre = {m["metodo"].split(" (")[0]: m for m in metodos}
    f, e = por_nombre.get("FCFF"), por_nombre.get("EVA")
    if not (f and e and f["aplicable"] and e["aplicable"]):
        return {"comparable": False, "motivo": "alguno de los dos metodos no es aplicable"}
    vf, ve = f["valor_empresa"], e["valor_empresa"]
    if not (_fin(vf) and _fin(ve)) or vf == 0:
        return {"comparable": False, "motivo": "falta el valor de empresa de alguno"}

    # Los dos valores de empresa coinciden por construccion (una sola fuente).
    # Lo que aqui se afirma de verdad es que la DESCOMPOSICION del EVA reproduce
    # ese valor: capital invertido + excesos de retorno + terminal, mas el
    # desfase conocido de la convencion de mitad de periodo. Si el camino del
    # capital invertido tuviera un error, esta suma dejaria de cuadrar aunque los
    # dos valores de empresa siguieran siendo el mismo numero.
    dif = abs(ve - vf) / abs(vf)
    ajuste = e.get("ajuste_convencion", 0.0)
    peso_ajuste = abs(ajuste) / abs(vf) if _fin(ajuste) else np.nan
    suma = e.get("suma_componentes", np.nan)
    cuadra = _fin(suma) and abs((suma + ajuste) - vf) <= max(1.0, abs(vf) * 1e-9)

    return {
        "comparable": True, "valor_fcff": vf, "valor_eva": ve, "diferencia_relativa": dif,
        "concuerdan": bool(cuadra), "ajuste_convencion": ajuste, "peso_ajuste": peso_ajuste,
        "suma_componentes": suma,
        "motivo": None if cuadra else
        ("La descomposicion del EVA no reproduce el valor de empresa: el camino del capital "
         "invertido no encaja con la reinversion proyectada."),
    }


# =============================================================================
#  10. SENSIBILIDAD
# =============================================================================

def sensibilidad(base, coste, mercado, sup, saltos_wacc=(-0.02, -0.01, 0, 0.01, 0.02),
                 saltos_g=(-0.01, -0.005, 0, 0.005, 0.01)):
    """Matriz valor por accion en funcion del WACC y del crecimiento perpetuo.

    Un DCF sin esta matriz invita a leer el valor central como si fuera una
    medicion. Las dos variables elegidas son las que mas mueven el resultado, y
    ambas son supuestos, no datos.
    """
    wacc0, g0 = coste.get("wacc"), sup["g_terminal"]
    if not (_fin(wacc0) and _fin(g0)):
        return None

    filas = []
    for dw in saltos_wacc:
        wacc = wacc0 + dw
        fila = {"WACC": wacc}
        for dg in saltos_g:
            g = g0 + dg
            etiqueta = f"g = {g:.2%}"
            if wacc <= g:
                fila[etiqueta] = np.nan
                continue
            sup_local = dict(sup)
            sup_local["g_terminal"] = g
            coste_local = dict(coste)
            coste_local["wacc"] = wacc
            proy_local = proyectar(base, sup_local, coste_local)
            res = valorar_fcff(proy_local, base, coste_local, mercado, sup_local)
            fila[etiqueta] = res["valor_accion"] if res["aplicable"] else np.nan
        filas.append(fila)
    return pd.DataFrame(filas)


# =============================================================================
#  11. DIAGNOSTICO
# =============================================================================

def diagnostico(res):
    """Comprobaciones que deben pasar para que la valoracion sea creible."""
    pruebas = []

    def _añadir(nombre, estado, detalle):
        pruebas.append({"Comprobacion": nombre, "Estado": estado, "Detalle": detalle})

    coste, base, sup = res["coste"], res["base"], res["supuestos"]

    _añadir("Tipo sin riesgo", "OK" if res["tipo_origen_rf"] == DATO else "SUPUESTO",
            f"{res['rf']:.2%} · {res['origen_rf']}")
    mk = res["mercado"]
    _añadir("Beta", "OK" if mk["origen_beta"] == DATO else
            ("DERIVADO" if mk["origen_beta"] == DERIVADO else "FALTA"),
            f"{mk['beta']:.3f} · {mk['origen_beta']}"
            if _fin(mk["beta"]) else "no disponible")

    # Dos fuentes para el mismo hecho: hay que afirmar que concuerdan.
    dv = mk.get("desvio_beta")
    if _fin(dv):
        ke_pub = res["rf"] + mk["beta_publicada"] * res["prima"]
        ke_cal = res["rf"] + mk["beta_calculada"] * res["prima"]
        _añadir("Beta publicada frente a regresion propia",
                "OK" if dv <= 0.15 else "AVISO",
                f"{mk['beta_publicada']:.3f} publicada frente a {mk['beta_calculada']:.3f} "
                f"regresada sobre {mk['meses_regresion_beta']} meses (desvio {dv:.3f}). "
                f"Implicaria una Ke del {ke_pub:.2%} frente al {ke_cal:.2%}")
    elif _fin(mk["beta"]):
        _añadir("Beta publicada frente a regresion propia", "NO COMPARABLE",
                "solo hay una de las dos fuentes disponibles")
    _añadir("WACC > crecimiento perpetuo",
            "OK" if (_fin(coste["wacc"]) and coste["wacc"] > sup["g_terminal"]) else "FALLA",
            f"WACC {coste['wacc']:.2%} frente a g {sup['g_terminal']:.2%}"
            if _fin(coste["wacc"]) else "WACC no calculable")
    _añadir("g perpetuo <= tipo sin riesgo",
            "OK" if (_fin(res["rf"]) and sup["g_terminal"] <= res["rf"] + 0.0001) else "AVISO",
            f"g {sup['g_terminal']:.2%} frente a rf {res['rf']:.2%}")
    if res["n_tasas_usadas"] >= 2:
        estado_t = "OK"
        detalle_t = (f"{res['tasa_fiscal']:.2%} · mediana de {res['n_tasas_usadas']} "
                     f"ejercicios utilizables")
    elif res["n_tasas_usadas"] == 1:
        estado_t = "AVISO"
        detalle_t = f"{res['tasa_fiscal']:.2%} · un solo ejercicio utilizable, poco robusto"
    else:
        efectivas = ", ".join(f"{a}: {v:.0%}" if _fin(v) else f"{a}: sin base imponible"
                              for a, v in res.get("tasas_efectivas", {}).items())
        estado_t = "SUPUESTO"
        detalle_t = (f"{res['tasa_fiscal']:.2%} (tipo marginal). Ningun ejercicio da una tasa "
                     f"efectiva utilizable — {efectivas} —, tipicamente por perdidas o ajustes "
                     f"extraordinarios")
    _añadir("Tasa fiscal normalizada", estado_t, detalle_t)
    _añadir("Ejercicios historicos", "OK" if len(res["anios"]) >= 3 else "AVISO",
            f"{len(res['anios'])} ejercicios: {res['anios'][0]}-{res['anios'][-1]}")

    coh = res["coherencia"]
    if coh.get("comparable"):
        if coh["concuerdan"]:
            detalle = "capital invertido + excesos + terminal reproducen el valor de empresa"
            if _fin(coh.get("peso_ajuste")) and coh["peso_ajuste"] > 0.0001:
                detalle += (f"; el {coh['peso_ajuste']:.1%} se explica por la convencion de "
                            f"mitad de periodo, que adelanta los flujos pero no los saldos")
            _añadir("Descomposicion del EVA", "OK", detalle)
        else:
            _añadir("Descomposicion del EVA", "FALLA", coh.get("motivo", ""))
    else:
        _añadir("Descomposicion del EVA", "NO COMPARABLE", coh.get("motivo", ""))

    for m in res["metodos"]:
        if m["aplicable"] and _fin(m.get("peso_terminal")):
            estado = "OK" if m["peso_terminal"] <= UMBRAL_PESO_TERMINAL else "AVISO"
            _añadir(f"Peso del valor terminal · {m['metodo'].split(' (')[0]}", estado,
                    f"{m['peso_terminal']:.1%} del valor total")

    if coste.get("aviso_kd"):
        _añadir("Coste de la deuda", "CORREGIDO", coste["aviso_kd"])

    aplicables = sum(1 for m in res["metodos"] if m["aplicable"])
    _añadir("Metodos aplicables", "OK" if aplicables >= 2 else "AVISO",
            f"{aplicables} de 5 metodos han podido calcularse")

    return pd.DataFrame(pruebas)


# =============================================================================
#  12. EXPORTACION A EXCEL
# =============================================================================
# El libro es el entregable, no un adorno del panel: debe poder auditarse sin la
# aplicacion delante. Por eso cada hoja lleva las cifras completas (no
# redondeadas a millones), cada supuesto lleva su origen en columna propia, y
# las hojas de proyeccion se pueden recalcular a mano linea a linea.

_FORMATO_MONEDA = '#,##0.00'
_FORMATO_MILES = '#,##0'
_FORMATO_PCT = '0.00%'
_FORMATO_X = '0.000'


def _hoja(escritor, df, nombre, formatos=None, ancho_primera=42):
    """Vuelca un DataFrame con cabecera con estilo y anchos legibles."""
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    if df is None or (hasattr(df, "empty") and df.empty):
        df = pd.DataFrame({"Sin datos": ["No hay informacion disponible para esta hoja."]})
    df.to_excel(escritor, sheet_name=nombre[:31], index=False)
    hoja = escritor.sheets[nombre[:31]]

    # La cabecera va en el mismo registro que los graficos: negro con rotulo
    # ambar. Un panel de terminal bajo una cabecera azul marino se lee como dos
    # documentos pegados, no como uno.
    azul = PatternFill("solid", fgColor="000000")
    blanco = Font(color="FFA028", bold=True, size=10, name="Consolas")
    borde = Border(bottom=Side(style="thin", color="D6DBE1"))

    for celda in hoja[1]:
        celda.fill = azul
        celda.font = blanco
        celda.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    hoja.row_dimensions[1].height = 30
    hoja.freeze_panes = "A2"

    for i, columna in enumerate(df.columns, start=1):
        letra = hoja.cell(row=1, column=i).column_letter
        if i == 1:
            hoja.column_dimensions[letra].width = ancho_primera
        else:
            largo = max([len(str(columna))] + [len(str(v)) for v in df[columna].head(40)])
            hoja.column_dimensions[letra].width = min(max(largo + 3, 13), 46)
        fmt = (formatos or {}).get(columna)
        if fmt:
            for fila in range(2, len(df) + 2):
                hoja.cell(row=fila, column=i).number_format = fmt
        for fila in range(2, len(df) + 2):
            hoja.cell(row=fila, column=i).border = borde
    return hoja


def _pares_df(pares):
    """Lista de (concepto, valor, origen[, nota]) a DataFrame de cuatro columnas."""
    filas = []
    for tupla in pares:
        concepto, valor, origen = tupla[0], tupla[1], tupla[2]
        nota = tupla[3] if len(tupla) > 3 else ""
        filas.append({"Concepto": concepto, "Valor": valor, "Origen": origen, "Nota": nota})
    return pd.DataFrame(filas)


def exportar_excel(res):
    """Libro Excel completo del DCF. Devuelve bytes listos para descargar.

    Doce hojas: resumen, supuestos, coste de capital, historico, FCFF hist.,
    proyeccion y una hoja por metodo, sensibilidad, diagnostico y metodologia.
    """
    import io

    base, coste, sup, mercado = res["base"], res["coste"], res["supuestos"], res["mercado"]
    est = estadisticos_valoracion(res["metodos"], mercado)
    moneda = mercado.get("moneda") or ""
    por_nombre = {m["metodo"].split(" (")[0]: m for m in res["metodos"]}

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as w:

        # --- 1. Resumen ----------------------------------------------------
        cabecera = _pares_df([
            ("Valor", f"{mercado['nombre']} ({res['simbolo']})", DATO, ""),
            ("Sector · industria", f"{mercado['sector']} · {mercado['industria']}", DATO, ""),
            ("Tipo de negocio", res["clasificacion"]["tipo"], DERIVADO,
             res["clasificacion"].get("aviso", "")),
            ("Moneda de los estados", moneda, DATO, ""),
            ("Precio de mercado", mercado["precio"], DATO, ""),
            ("Capitalizacion", mercado["capitalizacion"], DATO, ""),
            ("Acciones en circulacion", mercado["acciones"], DATO, ""),
            ("Ultimo ejercicio publicado", base["anio"], DATO, ""),
            ("Fecha del informe", pd.Timestamp.today().strftime("%Y-%m-%d"), DERIVADO, ""),
            ("", "", "", ""),
            ("Valor mediano de los metodos aplicables", est["mediana"], DERIVADO,
             f"{est['n']} de 5 metodos"),
            ("Potencial frente al precio", est["potencial_mediana"], DERIVADO, ""),
            ("Rango minimo-maximo", f"{est['minimo']:,.2f} - {est['maximo']:,.2f}"
             if est["n"] else "sin metodos aplicables", DERIVADO, ""),
        ])
        _hoja(w, cabecera, "1. Resumen", {"Valor": _FORMATO_MONEDA})
        hoja = w.sheets["1. Resumen"]
        inicio = len(cabecera) + 3
        resumen = res["resumen"]
        resumen.to_excel(w, sheet_name="1. Resumen", index=False, startrow=inicio)
        from openpyxl.styles import Alignment, Font, PatternFill
        for celda in hoja[inicio + 1]:
            if celda.value is not None:
                celda.fill = PatternFill("solid", fgColor="000000")
                celda.font = Font(color="FFA028", bold=True, size=10, name="Consolas")
                celda.alignment = Alignment(horizontal="center", wrap_text=True)
        for fila in range(inicio + 2, inicio + 2 + len(resumen)):
            for col, nombre in enumerate(resumen.columns, start=1):
                if nombre in ("Valor por accion", "Precio de mercado"):
                    hoja.cell(row=fila, column=col).number_format = _FORMATO_MONEDA
                elif nombre in ("Potencial", "Peso del valor terminal", "Tasa de descuento"):
                    hoja.cell(row=fila, column=col).number_format = _FORMATO_PCT
        _graficos_resumen(hoja, res, inicio, resumen)

        # --- 2. Supuestos ---------------------------------------------------
        supuestos = _pares_df([
            ("Años de proyeccion explicita", sup["anios"], SUPUESTO,
             "Tras ellos, perpetuidad creciente"),
            ("Convencion de mitad de periodo", "Si" if sup["mitad_periodo"] else "No", SUPUESTO,
             "Descuenta en t-0,5 porque la caja entra a lo largo del año, no el 31 de diciembre"),
            ("Crecimiento de ingresos año 1", sup["g_inicial"], DERIVADO, sup["origen_g_inicial"]),
            ("  · crecimiento historico (CAGR)", sup["g_historico"], DERIVADO,
             f"sobre {base['n_anios']} ejercicios"),
            ("  · crecimiento fundamental (reinversion x ROIC)", sup["g_fundamental"], DERIVADO, ""),
            ("Crecimiento perpetuo", sup["g_terminal"], SUPUESTO,
             "Acotado al tipo sin riesgo: a largo plazo el tipo nominal converge al "
             "crecimiento nominal de la economia"),
            ("Margen EBIT objetivo", sup["margen_objetivo"], SUPUESTO,
             "Converge linealmente desde el margen base"),
            ("ROIC en estado estacionario", sup["roic_estable"], SUPUESTO,
             "Fija la reinversion terminal: reinversion = g / ROIC"),
            ("Probabilidad de quiebra (APV)", sup["probabilidad_quiebra"], SUPUESTO, ""),
            ("Coste de quiebra sobre valor sin deuda (APV)", sup["coste_quiebra"], SUPUESTO, ""),
            ("", "", "", ""),
            ("Margen EBIT base (mediana historica)", base["margen_ebit"], DERIVADO,
             f"mediana de {base['n_margen']} ejercicios"),
            ("Capex sobre ventas (mediana)", base["capex_ventas"], DERIVADO,
             f"mediana de {base['n_capex']} ejercicios"),
            ("Amortizacion sobre ventas (mediana)", base["amortizacion_ventas"], DERIVADO,
             f"mediana de {base['n_amortizacion']} ejercicios"),
            ("Circulante por euro de venta adicional", base["circulante_incremental"],
             DERIVADO if base["n_circulante"] else SUPUESTO,
             f"mediana del circulante sobre ventas de {base['n_circulante']} ejercicios"
             if base["n_circulante"] else
             "sin nivel de circulante utilizable en el balance: se proyecta inversion "
             "en circulante NULA. Es un supuesto declarado, no un dato"),
            ("Tasa fiscal normalizada", res["tasa_fiscal"], res.get("origen_tasa_fiscal", DERIVADO),
             f"mediana de {res['n_tasas_usadas']} ejercicios con base imponible positiva"
             if res["n_tasas_usadas"] else
             "tipo marginal: ningun ejercicio publicado da una tasa efectiva utilizable"),
            ("ROIC del ultimo ejercicio", base["roic"], DERIVADO, ""),
            ("Tasa de reinversion del ultimo ejercicio", base["tasa_reinversion"], DERIVADO, ""),
        ])
        _hoja(w, supuestos, "2. Supuestos", {"Valor": _FORMATO_PCT})
        _graficos_supuestos(w.sheets["2. Supuestos"], res, len(supuestos))

        # --- 3. Coste de capital -------------------------------------------
        cc = _pares_df([
            ("Tipo sin riesgo (rf)", coste["rf"], res["tipo_origen_rf"], res["origen_rf"]),
            ("Prima de riesgo de mercado", coste["prima"], SUPUESTO,
             "Orden de magnitud publicado para mercado maduro; editable"),
            ("Beta apalancada", coste["beta"], mercado["origen_beta"],
             "la que se aplica en la valoracion"),
            ("  · beta publicada por el proveedor", mercado.get("beta_publicada"), DATO, ""),
            ("  · beta por regresion propia", mercado.get("beta_calculada"), DERIVADO,
             f"retornos mensuales sobre {mercado.get('meses_regresion_beta')} meses "
             f"frente al S&P 500"),
            ("  · desacuerdo entre ambas", mercado.get("desvio_beta"), DERIVADO,
             "Por encima de 0,15 conviene revisar: la beta gobierna la Ke y con ella "
             "todo el descuento"),
            ("Beta desapalancada (Hamada)", coste["beta_desapalancada"], DERIVADO,
             "bU = bL / (1 + (1-t) x D/E). La usa el APV"),
            ("Coste del capital propio (Ke = rf + beta x prima)", coste["ke"], DERIVADO, ""),
            ("Coste del capital sin deuda (Ku)", coste["ku"], DERIVADO, "Tasa de descuento del APV"),
            ("Gasto financiero del ejercicio", coste["intereses"], DATO, ""),
            ("Deuda media del ejercicio", coste["deuda_media"], DERIVADO,
             "Media del saldo de apertura y cierre"),
            ("Coste de la deuda implicito (Kd bruto)", coste["kd_bruto"], DERIVADO,
             "Gasto financiero / deuda media"),
            ("Coste de la deuda aplicado (Kd)", coste["kd"], coste["origen_kd"],
             coste["aviso_kd"] or ""),
            ("Coste de la deuda despues de impuestos", coste["kd_despues_impuestos"], DERIVADO, ""),
            ("Tasa fiscal aplicada", coste["tasa_fiscal"], DERIVADO, ""),
            ("Valor de mercado del capital propio", coste["equity"], DATO, ""),
            ("Deuda total (balance)", coste["deuda"], coste["origen_deuda"], ""),
            ("Peso del capital propio", coste["peso_equity"], DERIVADO, "A valor de mercado"),
            ("Peso de la deuda", coste["peso_deuda"], DERIVADO, "A valor de mercado"),
            ("Deuda / capital propio", coste["deuda_equity"], DERIVADO, ""),
            ("WACC", coste["wacc"], DERIVADO, "Ke x peso_E + Kd x (1-t) x peso_D"),
        ])
        _hoja(w, cc, "3. Coste de capital", {"Valor": _FORMATO_X})
        hoja_cc = w.sheets["3. Coste de capital"]
        for fila in range(2, len(cc) + 2):
            concepto = str(hoja_cc.cell(row=fila, column=1).value or "")
            if any(k in concepto for k in ("Beta", "Deuda / capital")):
                hoja_cc.cell(row=fila, column=2).number_format = _FORMATO_X
            elif any(k in concepto for k in ("Gasto financiero", "Deuda media",
                                             "Valor de mercado", "Deuda total (balance)")):
                hoja_cc.cell(row=fila, column=2).number_format = _FORMATO_MILES
            else:
                hoja_cc.cell(row=fila, column=2).number_format = _FORMATO_PCT
        _graficos_coste_capital(hoja_cc, res, len(cc))

        # --- 4. Estados historicos -----------------------------------------
        p = res["partidas"]
        etiquetas = [
            ("Ingresos", "ingresos"), ("EBIT", "ebit"), ("EBITDA", "ebitda"),
            ("Beneficio neto", "beneficio_neto"), ("Beneficio antes de impuestos", "bai"),
            ("Impuestos", "impuestos"), ("Gasto financiero", "intereses"),
            ("Amortizacion", "amortizacion"), ("Capex (signo de origen)", "capex"),
            ("Var. circulante (signo de origen)", "var_circulante"),
            ("Flujo de caja operativo", "flujo_operativo"),
            ("Dividendos pagados (signo de origen)", "dividendos"),
            ("Endeudamiento neto emitido", "deuda_neta_emitida"),
            ("Recompras (signo de origen)", "recompras"),
            ("Deuda total", "deuda_total"), ("Caja y equivalentes", "caja"),
            ("Caja e inversiones a corto", "caja_amplia"),
            ("Patrimonio neto", "patrimonio"), ("Intereses minoritarios", "minoritarios"),
            ("Capital invertido", "capital_invertido"), ("Inmovilizado material neto", "ppe_neto"),
            ("Capital circulante", "circulante"), ("Activos totales", "activos_totales"),
            ("Acciones (media diluida)", "acciones"),
        ]
        filas_hist = []
        for etiqueta, clave in etiquetas:
            fila = {"Partida": etiqueta}
            for a in res["anios"]:
                fila[str(a)] = _v(p[clave], a) if p.get(clave) is not None else np.nan
            filas_hist.append(fila)
        hist_df = pd.DataFrame(filas_hist)
        _hoja(w, hist_df, "4. Estados historicos",
              {str(a): _FORMATO_MILES for a in res["anios"]})
        _graficos_historico(w.sheets["4. Estados historicos"], res, hist_df)

        # --- 5. FCFF historico ----------------------------------------------
        _hoja(w, res["historico_fcff"], "5. FCFF historico", {
            "Ingresos": _FORMATO_MILES, "EBIT": _FORMATO_MILES, "NOPAT": _FORMATO_MILES,
            "Amortizacion": _FORMATO_MILES, "Capex (signo de origen)": _FORMATO_MILES,
            "Var. circulante (signo de origen)": _FORMATO_MILES, "FCFF": _FORMATO_MILES,
            "Tasa fiscal efectiva": _FORMATO_PCT}, ancho_primera=13)
        _grafico_columnas_tabla(w.sheets["5. FCFF historico"], res["historico_fcff"],
                                ["NOPAT", "FCFF"], "FCFF publicado por ejercicio",
                                f"A{len(res['historico_fcff']) + 4}", _FORMATO_MILES)

        # --- 6. Proyeccion ---------------------------------------------------
        _hoja(w, res["proyeccion"], "6. Proyeccion FCFF", {
            "Crecimiento ingresos": _FORMATO_PCT, "Margen EBIT": _FORMATO_PCT,
            "Tasa fiscal": _FORMATO_PCT, "Ingresos": _FORMATO_MILES, "EBIT": _FORMATO_MILES,
            "NOPAT": _FORMATO_MILES, "Amortizacion": _FORMATO_MILES, "Capex": _FORMATO_MILES,
            "Inversion en circulante": _FORMATO_MILES, "FCFF": _FORMATO_MILES}, ancho_primera=9)
        _hp = w.sheets["6. Proyeccion FCFF"]
        _np = len(res["proyeccion"])
        _grafico_columnas_tabla(_hp, res["proyeccion"], ["NOPAT", "FCFF"],
                                "Flujo libre proyectado", f"A{_np + 4}", _FORMATO_MILES)
        _grafico_columnas_tabla(_hp, res["proyeccion"], ["Ingresos"],
                                "Ingresos proyectados", f"L{_np + 4}", _FORMATO_MILES, tipo="line")
        _grafico_columnas_tabla(_hp, res["proyeccion"],
                                ["Crecimiento ingresos", "Margen EBIT"],
                                "Crecimiento y margen", f"W{_np + 4}", _FORMATO_PCT, tipo="line")
        _grafico_columnas_tabla(_hp, res["proyeccion"],
                                ["Amortizacion", "Capex", "Inversion en circulante"],
                                "Reinversion proyectada", f"A{_np + 22}", _FORMATO_MILES)

        # --- 7-11. Una hoja por metodo ---------------------------------------
        # Cada hoja de metodo lleva su descomposicion en barras: de donde sale el
        # valor, pieza a pieza. Las de detalle año a año llevan ademas la serie
        # temporal, que es lo que permite ver si el flujo crece o se hunde.
        m_fcff, m_fcfe = por_nombre.get("FCFF"), por_nombre.get("FCFE")
        m_ddm = por_nombre.get("DDM")
        m_apv, m_eva = por_nombre.get("APV"), por_nombre.get("EVA")

        d7 = _detalle_fcff(m_fcff, moneda)
        _hoja(w, d7, "7. Metodo FCFF", {"Valor": _FORMATO_MILES})
        if m_fcff and m_fcff["aplicable"]:
            _graficos_metodo(
                w.sheets["7. Metodo FCFF"], m_fcff, len(d7),
                "De donde sale el valor de empresa",
                [("VA del periodo explicito", m_fcff["vp_explicito"]),
                 ("VA del valor terminal", m_fcff["vp_terminal"]),
                 ("- Deuda", -abs(m_fcff["puente"]["deuda"])),
                 ("+ Caja", m_fcff["puente"]["caja"]),
                 ("- Minoritarios", -abs(m_fcff["puente"]["minoritarios"])),
                 ("= Valor del capital", m_fcff["valor_capital"])], _FORMATO_MILES)

        d8 = _detalle_generico(m_fcfe, moneda)
        _hoja(w, d8, "8. Metodo FCFE", {"Valor": _FORMATO_MILES})
        if m_fcfe and m_fcfe["aplicable"]:
            _graficos_metodo(
                w.sheets["8. Metodo FCFE"], m_fcfe, len(d8),
                "De donde sale el valor del capital",
                [("VA del periodo explicito", m_fcfe["vp_explicito"]),
                 ("VA del valor terminal", m_fcfe["vp_terminal"]),
                 ("+ Caja no operativa", m_fcfe.get("caja_no_operativa")),
                 ("= Valor del capital", m_fcfe["valor_capital"])], _FORMATO_MILES)
        if m_fcfe and m_fcfe.get("tabla") is not None:
            _hoja(w, m_fcfe["tabla"], "8b. FCFE detalle",
                  {c: _FORMATO_MILES for c in ["FCFF", "Deuda inicio", "Reinversion",
                                               "Intereses", "Intereses despues de impuestos",
                                               "Endeudamiento neto", "FCFE",
                                               "Beneficio neto"]}, ancho_primera=9)
            _h8 = w.sheets["8b. FCFE detalle"]
            _n8 = len(m_fcfe["tabla"])
            _grafico_columnas_tabla(_h8, m_fcfe["tabla"], ["FCFF", "FCFE", "Beneficio neto"],
                                    "Del flujo de la empresa al del accionista",
                                    "A" + str(_n8 + 4), _FORMATO_MILES)
            _grafico_columnas_tabla(_h8, m_fcfe["tabla"],
                                    ["Intereses despues de impuestos", "Endeudamiento neto"],
                                    "Ajustes por deuda", "L" + str(_n8 + 4), _FORMATO_MILES)

        d9 = _detalle_ddm(m_ddm, moneda)
        _hoja(w, d9, "9. Metodo DDM", {"Valor": _FORMATO_MONEDA})
        if m_ddm and m_ddm["aplicable"]:
            _graficos_metodo(
                w.sheets["9. Metodo DDM"], m_ddm, len(d9),
                "De donde sale el valor por accion",
                [("VA de los dividendos explicitos", m_ddm["vp_explicito"]),
                 ("VA del valor terminal", m_ddm["vp_terminal"]),
                 ("= Valor por accion", m_ddm["valor_accion"])], _FORMATO_MONEDA)
        if m_ddm and m_ddm.get("tabla") is not None:
            _hoja(w, m_ddm["tabla"], "9b. DDM detalle",
                  {"Crecimiento dividendo": _FORMATO_PCT,
                   "Dividendo por accion": _FORMATO_MONEDA}, ancho_primera=9)
            _h9 = w.sheets["9b. DDM detalle"]
            _n9 = len(m_ddm["tabla"])
            _grafico_columnas_tabla(_h9, m_ddm["tabla"], ["Dividendo por accion"],
                                    "Dividendo por accion proyectado", "A" + str(_n9 + 4),
                                    _FORMATO_MONEDA)
            _grafico_columnas_tabla(_h9, m_ddm["tabla"], ["Crecimiento dividendo"],
                                    "Senda de crecimiento del dividendo", "L" + str(_n9 + 4),
                                    _FORMATO_PCT, tipo="line")

        d10 = _detalle_apv(m_apv, moneda)
        _hoja(w, d10, "10. Metodo APV", {"Valor": _FORMATO_MILES})
        if m_apv and m_apv["aplicable"]:
            _graficos_metodo(
                w.sheets["10. Metodo APV"], m_apv, len(d10),
                "Las tres piezas del valor ajustado",
                [("Empresa sin deuda", m_apv["valor_sin_deuda"]),
                 ("+ Escudo fiscal", m_apv["valor_escudo"]),
                 ("- Quiebra esperada", -abs(m_apv["coste_quiebra_esperado"])),
                 ("= Valor de empresa", m_apv["valor_empresa"]),
                 ("= Valor del capital", m_apv["valor_capital"])], _FORMATO_MILES)
        if m_apv and m_apv.get("tabla") is not None:
            _hoja(w, m_apv["tabla"], "10b. APV escudo fiscal",
                  {c: _FORMATO_MILES for c in ["Deuda inicio", "Intereses", "Escudo fiscal"]},
                  ancho_primera=9)
            _h10 = w.sheets["10b. APV escudo fiscal"]
            _n10 = len(m_apv["tabla"])
            _grafico_columnas_tabla(_h10, m_apv["tabla"], ["Escudo fiscal"],
                                    "Ahorro fiscal de la deuda por ejercicio",
                                    "A" + str(_n10 + 4), _FORMATO_MILES)
            _grafico_columnas_tabla(_h10, m_apv["tabla"], ["Deuda inicio", "Intereses"],
                                    "Deuda e intereses", "L" + str(_n10 + 4), _FORMATO_MILES,
                                    tipo="line")

        d11 = _detalle_eva(m_eva, moneda)
        _hoja(w, d11, "11. Metodo EVA", {"Valor": _FORMATO_MILES})
        if m_eva and m_eva["aplicable"]:
            _graficos_metodo(
                w.sheets["11. Metodo EVA"], m_eva, len(d11),
                "Capital ya invertido frente al valor que añade la gestion",
                [("Capital invertido", m_eva["capital_inicial"]),
                 ("+ VA de los EVA explicitos", m_eva["vp_eva"]),
                 ("+ VA del EVA terminal", m_eva["vp_terminal"]),
                 ("= Valor de empresa", m_eva["valor_empresa"])], _FORMATO_MILES)
        if m_eva and m_eva.get("tabla") is not None:
            _hoja(w, m_eva["tabla"], "11b. EVA detalle",
                  {"Capital invertido inicio": _FORMATO_MILES, "NOPAT": _FORMATO_MILES,
                   "ROIC": _FORMATO_PCT, "Cargo por capital (WACC x capital)": _FORMATO_MILES,
                   "EVA": _FORMATO_MILES, "Reinversion del periodo": _FORMATO_MILES},
                  ancho_primera=9)
            _h11 = w.sheets["11b. EVA detalle"]
            _n11 = len(m_eva["tabla"])
            _grafico_columnas_tabla(_h11, m_eva["tabla"], ["EVA"],
                                    "Beneficio economico por ejercicio", "A" + str(_n11 + 4),
                                    _FORMATO_MILES)
            _grafico_columnas_tabla(_h11, m_eva["tabla"],
                                    ["NOPAT", "Cargo por capital (WACC x capital)"],
                                    "NOPAT frente al cargo por capital", "L" + str(_n11 + 4),
                                    _FORMATO_MILES)
            _grafico_columnas_tabla(_h11, m_eva["tabla"], ["ROIC"],
                                    "ROIC proyectado", "W" + str(_n11 + 4), _FORMATO_PCT,
                                    tipo="line")

        # --- 12. Sensibilidad -------------------------------------------------
        sens = res.get("sensibilidad")
        if sens is not None and not sens.empty:
            fmt = {c: _FORMATO_MONEDA for c in sens.columns if c != "WACC"}
            fmt["WACC"] = _FORMATO_PCT
            _hoja(w, sens, "12. Sensibilidad", fmt, ancho_primera=12)
            _graficos_sensibilidad(w.sheets["12. Sensibilidad"], sens)

        # --- 13. Diagnostico --------------------------------------------------
        _diag = diagnostico(res)
        _hoja(w, _diag, "13. Diagnostico", ancho_primera=38)
        _graficos_diagnostico(w.sheets["13. Diagnostico"], _diag)

        # --- 14. Metodologia --------------------------------------------------
        _hoja(w, _metodologia(), "14. Metodologia", ancho_primera=30)

    return buffer.getvalue()


def _cabecera_metodo(m):
    if m is None:
        return [("Metodo", "no calculado", "", "")]
    if not m["aplicable"]:
        return [("Metodo", m["metodo"], "", ""),
                ("Aplicable", "NO", "", m["motivo"] or "")]
    return None


def _detalle_fcff(m, moneda):
    cab = _cabecera_metodo(m)
    if cab:
        return _pares_df(cab)
    return _pares_df([
        ("Metodo", m["metodo"], "", "Flujo libre a la empresa descontado al WACC"),
        ("Tasa de descuento (WACC)", m["tasa"], DERIVADO, ""),
        ("Valor actual del periodo explicito", m["vp_explicito"], DERIVADO, ""),
        ("Flujo terminal", m["flujo_terminal"], DERIVADO, m["nota_reinversion"]),
        ("Reinversion en estado estacionario", m["tasa_reinversion_terminal"], DERIVADO,
         "g / ROIC estable"),
        ("Valor terminal (sin descontar)", m["valor_terminal_bruto"], DERIVADO,
         "Perpetuidad creciente de Gordon"),
        ("Valor actual del valor terminal", m["vp_terminal"], DERIVADO, ""),
        ("Peso del valor terminal", m["peso_terminal"], DERIVADO,
         "Por encima del 75% la valoracion habla mas del supuesto que de la empresa"),
        ("", "", "", ""),
    ] + [(etiqueta, valor, DERIVADO, "") for etiqueta, valor in m["puente"]["detalle"]] + [
        ("Acciones en circulacion", m["puente"]["acciones"], DATO, ""),
        ("VALOR POR ACCION", m["valor_accion"], DERIVADO, moneda),
    ])


def _detalle_generico(m, moneda):
    cab = _cabecera_metodo(m)
    if cab:
        return _pares_df(cab)
    return _pares_df([
        ("Metodo", m["metodo"], "", "Flujo libre al accionista descontado al coste del "
                                    "capital propio. El resultado ya ES el valor del capital: "
                                    "no se resta deuda despues"),
        ("Tasa de descuento (Ke)", m["tasa"], DERIVADO, ""),
        ("Valor actual del periodo explicito", m["vp_explicito"], DERIVADO, ""),
        ("Flujo terminal", m.get("flujo_terminal"), DERIVADO,
         m.get("origen_valor_terminal", "")),
        ("Valor terminal (sin descontar)", m.get("valor_terminal_bruto"), DERIVADO, ""),
        ("Valor actual del valor terminal", m["vp_terminal"], DERIVADO, ""),
        ("Peso del valor terminal", m["peso_terminal"], DERIVADO, ""),
        ("= Valor del capital operativo", m.get("capital_operativo"), DERIVADO, ""),
        ("+ Caja e inversiones no operativas", m.get("caja_no_operativa"), DATO,
         "No generan flujo operativo, asi que no estan dentro de lo descontado. La deuda "
         "NO se resta: ya esta dentro del flujo, via intereses y endeudamiento neto"),
        ("= Valor del capital", m["valor_capital"], DERIVADO, ""),
        ("VALOR POR ACCION", m["valor_accion"], DERIVADO, moneda),
    ])


def _detalle_ddm(m, moneda):
    cab = _cabecera_metodo(m)
    if cab:
        return _pares_df(cab)
    return _pares_df([
        ("Metodo", m["metodo"], "", "Dividendos descontados al coste del capital propio"),
        ("Dividendo base por accion", m["dividendo_base"], DATO, m["origen_dividendo"]),
        ("ROE", m["roe"], DERIVADO, ""),
        ("Pay-out", m["payout"], DERIVADO, "Dividendos / beneficio neto"),
        ("Crecimiento sostenible (ROE x retencion)", m["g_sostenible"], DERIVADO, ""),
        ("Crecimiento aplicado año 1", m["g_inicial"], SUPUESTO, ""),
        ("Tasa de descuento (Ke)", m["tasa"], DERIVADO, ""),
        ("Valor actual de los dividendos explicitos", m["vp_explicito"], DERIVADO, ""),
        ("Valor actual del valor terminal", m["vp_terminal"], DERIVADO, ""),
        ("VALOR POR ACCION", m["valor_accion"], DERIVADO, moneda),
    ])


def _detalle_apv(m, moneda):
    cab = _cabecera_metodo(m)
    if cab:
        return _pares_df(cab)
    return _pares_df([
        ("Metodo", m["metodo"], "", "Empresa sin deuda + escudo fiscal - coste esperado de quiebra"),
        ("Tasa de descuento sin deuda (Ku)", m["tasa"], DERIVADO, ""),
        ("Valor de la empresa sin deuda", m["valor_sin_deuda"], DERIVADO, ""),
        ("Valor actual del escudo fiscal", m["valor_escudo"], DERIVADO,
         "Descontado al coste de la deuda: el ahorro tiene el riesgo de los intereses "
         "que lo generan"),
        ("Coste esperado de quiebra", m["coste_quiebra_esperado"], SUPUESTO,
         "Probabilidad x coste sobre el valor sin deuda"),
        ("", "", "", ""),
    ] + [(etiqueta, valor, DERIVADO, "") for etiqueta, valor in m["puente"]["detalle"]] + [
        ("Acciones en circulacion", m["puente"]["acciones"], DATO, ""),
        ("VALOR POR ACCION", m["valor_accion"], DERIVADO, moneda),
    ])


def _detalle_eva(m, moneda):
    cab = _cabecera_metodo(m)
    if cab:
        return _pares_df(cab)
    return _pares_df([
        ("Metodo", m["metodo"], "", "Capital invertido + valor actual de los excesos de retorno"),
        ("Capital invertido de partida", m["capital_inicial"], DATO, ""),
        ("Tasa de descuento (WACC)", m["tasa"], DERIVADO, ""),
        ("Valor actual de los EVA explicitos", m["vp_eva"], DERIVADO, ""),
        ("Capital invertido al final del periodo explicito", m.get("capital_final"), DERIVADO, ""),
        ("Valor actual del EVA terminal", m["vp_terminal"], DERIVADO,
         m.get("origen_valor_terminal", "")),
        ("Suma de los componentes", m.get("suma_componentes"), DERIVADO,
         "Capital invertido + excesos explicitos + terminal"),
        ("Ajuste por convencion de mitad de periodo", m.get("ajuste_convencion"), DERIVADO,
         "La convencion adelanta medio año los flujos, pero un saldo de balance no se "
         "puede adelantar. Con descuento a fin de periodo este ajuste es exactamente cero"),
        ("", "", "", ""),
    ] + [(etiqueta, valor, DERIVADO, "") for etiqueta, valor in m["puente"]["detalle"]] + [
        ("Acciones en circulacion", m["puente"]["acciones"], DATO, ""),
        ("VALOR POR ACCION", m["valor_accion"], DERIVADO, moneda),
    ])


def _metodologia():
    return pd.DataFrame([
        {"Concepto": "FCFF", "Formula": "EBIT x (1-t) + amortizacion - capex - inversion en circulante",
         "Tasa": "WACC", "Resultado": "Valor de empresa",
         "Cuando usarlo": "Caso general. Estructura de capital estable."},
        {"Concepto": "FCFE", "Formula": "FCFF - intereses x (1-t) + endeudamiento neto",
         "Tasa": "Ke", "Resultado": "Valor del capital (directo)",
         "Cuando usarlo": "Entidades financieras y empresas muy apalancadas."},
        {"Concepto": "DDM", "Formula": "Dividendos por accion, en dos fases",
         "Tasa": "Ke", "Resultado": "Valor por accion (directo)",
         "Cuando usarlo": "Reparto estable y ligado al beneficio. Accionista minoritario."},
        {"Concepto": "APV", "Formula": "Valor sin deuda + escudo fiscal - quiebra esperada",
         "Tasa": "Ku (sin deuda) y Kd (escudo)", "Resultado": "Valor de empresa",
         "Cuando usarlo": "Cuando la estructura de capital va a cambiar."},
        {"Concepto": "EVA", "Formula": "Capital invertido + suma de (NOPAT - WACC x capital)",
         "Tasa": "WACC", "Resultado": "Valor de empresa",
         "Cuando usarlo": "Separa el valor ya invertido del que crea la gestion."},
        {"Concepto": "Valor terminal", "Formula": "Flujo_n x (1+g) / (tasa - g)",
         "Tasa": "La del metodo", "Resultado": "Perpetuidad",
         "Cuando usarlo": "Exige tasa > g. El g se acota al tipo sin riesgo."},
        {"Concepto": "Reinversion terminal", "Formula": "g / ROIC estable",
         "Tasa": "-", "Resultado": "Fraccion del NOPAT",
         "Cuando usarlo": "Siempre. Crecer sin reinvertir regala valor gratis."},
        {"Concepto": "Mitad de periodo", "Formula": "Factor = 1 / (1+tasa)^(t-0,5)",
         "Tasa": "-", "Resultado": "Sube el valor ~2-3%",
         "Cuando usarlo": "La caja entra a lo largo del año, no el 31 de diciembre."},
        {"Concepto": "Puente EV a capital",
         "Formula": "EV - deuda + caja - minoritarios", "Tasa": "-",
         "Resultado": "Valor del capital",
         "Cuando usarlo": "Solo en metodos que dan valor de empresa (FCFF, APV, EVA)."},
        {"Concepto": "Beta desapalancada", "Formula": "bL / (1 + (1-t) x D/E)",
         "Tasa": "-", "Resultado": "Beta del negocio",
         "Cuando usarlo": "APV, y para comparar empresas con distinto apalancamiento."},
    ])


# =============================================================================
#  13. GRAFICOS DEL LIBRO EXCEL
# =============================================================================
# Cada hoja con cifras lleva su grafico. Son graficos NATIVOS de Excel (no
# imagenes incrustadas), asi que siguen vivos: quien reciba el libro puede
# cambiar un supuesto y ver moverse la barra.
#
# Las hojas de pares concepto/valor mezclan por naturaleza texto y numeros de
# ordenes de magnitud muy distintos, y un grafico sobre esa columna sale ilegible
# o directamente vacio. Por eso cada una escribe aparte un bloque numerico
# reducido -- solo las filas que tiene sentido comparar entre si, y en la misma
# unidad -- que es lo que alimenta al grafico. El bloque va rotulado en la propia
# hoja, no escondido: quien audite el libro tiene que poder ver de donde sale
# cada barra.

# --- Registro visual de terminal ---------------------------------------------
# Fondo negro, ambar como color principal y cian de apoyo, rejilla apenas
# insinuada y tipografia monoespaciada. La escala de grises hace el trabajo de
# jerarquia y el color queda reservado para lo que de verdad distingue una serie
# de otra, que es como lee un terminal financiero.
#
# El color NUNCA es el unico portador de informacion: las series van tambien en
# el orden de la leyenda y con marcador propio, y en las descomposiciones el
# signo se lee ademas en el rotulo de la categoria ("- Deuda", "+ Caja"), no
# solo en el rojo o el verde de la barra.

_BB_FONDO = "000000"
_BB_PANEL = "000000"
_BB_REJILLA = "1E1E1E"
_BB_EJE = "3C3C3C"
_BB_TEXTO = "B4B4B4"
_BB_TITULO = "FFA028"
_BB_POSITIVO = "6DBE45"
_BB_NEGATIVO = "E5343E"
_BB_FUENTE = "Consolas"

# Ambar primero: es la firma del terminal. Despues cian, blanco hueso, verde,
# magenta y rojo, que se distinguen entre si tambien en escala de grises.
_BB_SERIES = ["FFA028", "3FA9F5", "E8E8E8", "6DBE45", "C77DFF", "E5343E",
              "FFC46B", "7FD1F7"]


def _poner_categorias(ch, hoja, ref):
    """Asigna las categorias del eje respetando su TIPO.

    `set_categories` de openpyxl escribe siempre `numRef`, tambien cuando las
    etiquetas son texto. Excel entonces no encuentra numeros donde se le dice que
    los busque y rotula el eje 1, 2, 3..., de modo que el grafico de valoracion
    por metodo perdia los nombres FCFF, FCFE, DDM, APV y EVA y quedaba
    indescifrable. Cuando las celdas son texto hay que escribir `strRef`.
    """
    from openpyxl.chart.data_source import AxDataSource, StrRef

    ch.set_categories(ref)
    try:
        primera = hoja.cell(row=ref.min_row, column=ref.min_col).value
    except Exception:
        return
    if isinstance(primera, str):
        for s in ch.series:
            s.cat = AxDataSource(strRef=StrRef(f=str(ref)))


def _bb_texto(tam=850, color=None, negrita=False):
    """Propiedades de caracter para ejes, leyenda y titulo."""
    from openpyxl.drawing.text import CharacterProperties, Font as FuenteDibujo

    return CharacterProperties(solidFill=color or _BB_TEXTO, sz=tam, b=negrita,
                               latin=FuenteDibujo(typeface=_BB_FUENTE))


def _bb_richtext(cp):
    from openpyxl.chart.text import RichText
    from openpyxl.drawing.text import Paragraph, ParagraphProperties

    return RichText(p=[Paragraph(pPr=ParagraphProperties(defRPr=cp), endParaRPr=cp)])


def _bb_eje(eje, con_rejilla=True, formato=None):
    from openpyxl.chart.axis import ChartLines
    from openpyxl.chart.shapes import GraphicalProperties
    from openpyxl.drawing.line import LineProperties

    eje.txPr = _bb_richtext(_bb_texto())
    eje.spPr = GraphicalProperties(ln=LineProperties(solidFill=_BB_EJE, w=6350))
    eje.majorTickMark = "out"
    eje.minorTickMark = "none"
    if formato:
        eje.numFmt = formato
    if con_rejilla:
        eje.majorGridlines = ChartLines(
            spPr=GraphicalProperties(ln=LineProperties(solidFill=_BB_REJILLA, w=6350)))
    else:
        eje.majorGridlines = None
    if eje.title is not None:
        eje.title.tx.rich.p[0].pPr.defRPr = _bb_texto(900, _BB_TEXTO)


def _estilo_bloomberg(ch, formato_valor=None, valores=None, eje_valor="y"):
    """Aplica el registro de terminal a un grafico ya construido.

    `valores`, si se pasa, colorea cada barra de una serie unica segun su signo:
    verde lo que suma, rojo lo que resta. Es la lectura inmediata de una
    descomposicion de valor, y el signo sigue estando ademas en el rotulo.
    """
    from openpyxl.chart.marker import DataPoint
    from openpyxl.chart.shapes import GraphicalProperties
    from openpyxl.drawing.line import LineProperties

    # Lienzo y panel en negro, sin borde.
    ch.graphical_properties = GraphicalProperties(solidFill=_BB_FONDO,
                                                  ln=LineProperties(noFill=True))
    ch.plot_area.graphicalProperties = GraphicalProperties(
        solidFill=_BB_PANEL, ln=LineProperties(noFill=True))
    ch.roundedCorners = False
    ch.style = None          # los estilos predefinidos de Excel reintroducen color propio

    # Titulo en ambar.
    if ch.title is not None and getattr(ch.title, "tx", None) is not None:
        try:
            ch.title.tx.rich.p[0].pPr.defRPr = _bb_texto(1050, _BB_TITULO, negrita=True)
            for run in ch.title.tx.rich.p[0].r or []:
                run.rPr = _bb_texto(1050, _BB_TITULO, negrita=True)
        except (AttributeError, IndexError):
            pass

    # Ejes: rejilla solo en el eje de valores, nunca en el de categorias.
    horizontal = getattr(ch, "type", None) == "bar"
    _bb_eje(ch.x_axis, con_rejilla=horizontal,
            formato=formato_valor if (horizontal and formato_valor) else None)
    _bb_eje(ch.y_axis, con_rejilla=not horizontal,
            formato=formato_valor if (not horizontal and formato_valor) else None)

    # Leyenda abajo, en gris claro.
    if ch.legend is not None:
        ch.legend.position = "b"
        ch.legend.overlay = False
        ch.legend.txPr = _bb_richtext(_bb_texto(850))
        ch.legend.spPr = GraphicalProperties(noFill=True, ln=LineProperties(noFill=True))

    es_linea = ch.tagname == "lineChart"
    for i, serie in enumerate(ch.series):
        color = _BB_SERIES[i % len(_BB_SERIES)]
        if es_linea:
            serie.graphicalProperties = GraphicalProperties(
                ln=LineProperties(solidFill=color, w=22225))
            serie.smooth = False
            if serie.marker is not None:
                serie.marker.symbol = "circle"
                serie.marker.size = 5
                serie.marker.graphicalProperties = GraphicalProperties(
                    solidFill=color, ln=LineProperties(solidFill=color))
        else:
            serie.graphicalProperties = GraphicalProperties(
                solidFill=color, ln=LineProperties(noFill=True))

    # Barras coloreadas por signo en las descomposiciones de una sola serie.
    if valores and not es_linea and len(ch.series) == 1:
        puntos = []
        for i, v in enumerate(valores):
            if v is None:
                continue
            tono = _BB_POSITIVO if v >= 0 else _BB_NEGATIVO
            puntos.append(DataPoint(
                idx=i, spPr=GraphicalProperties(solidFill=tono,
                                                ln=LineProperties(noFill=True))))
        if puntos:
            # El atributo se llama dPt: `data_points` NO es un alias en openpyxl,
            # asi que asignarlo ahi no daba error y tampoco pintaba nada. El
            # coloreado por signo simplemente no aparecia en el libro.
            ch.series[0].dPt = puntos
    return ch


_COL_GRAFICO = 7        # columna F/G: a la derecha de la tabla de cuatro columnas
_ALTO_GRAFICO = 8.5
_ANCHO_GRAFICO = 17.5


def _num_o_nada(v):
    """Devuelve el float si es utilizable; None si no hay dato.

    None y no cero: un cero se pinta como barra a la altura cero, que es
    informacion; un dato ausente no debe pintar barra ninguna.
    """
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def _bloque_para_grafico(hoja, fila, col, titulo, pares):
    """Escribe un bloque etiqueta/valor auxiliar y devuelve sus referencias.

    Devuelve (datos, categorias) o (None, None) si no queda ninguna fila con
    dato, en cuyo caso el llamador no debe dibujar grafico: una grafica vacia
    sugiere que el dato es cero, y no lo es -- es que no hay dato.
    """
    from openpyxl.chart import Reference
    from openpyxl.styles import Font

    celda = hoja.cell(row=fila, column=col, value=titulo)
    celda.font = Font(bold=True, size=9, color="4A5A70")
    hoja.cell(row=fila, column=col + 1, value="Valor")

    r = fila + 1
    for etiqueta, valor in pares:
        v = _num_o_nada(valor)
        if v is None:
            continue
        hoja.cell(row=r, column=col, value=str(etiqueta))
        hoja.cell(row=r, column=col + 1, value=v)
        r += 1

    if r == fila + 1:
        return None, None
    hoja.column_dimensions[hoja.cell(row=fila, column=col).column_letter].width = 34
    datos = Reference(hoja, min_col=col + 1, min_row=fila, max_row=r - 1)
    cats = Reference(hoja, min_col=col, min_row=fila + 1, max_row=r - 1)
    return datos, cats


def _barras(hoja, ancla, titulo, datos, cats, horizontal=False, formato=None,
            valores=None):
    from openpyxl.chart import BarChart

    if datos is None:
        return
    ch = BarChart()
    ch.type = "bar" if horizontal else "col"
    ch.title = titulo
    ch.add_data(datos, titles_from_data=True)
    _poner_categorias(ch, hoja, cats)
    ch.legend = None
    ch.height, ch.width = _ALTO_GRAFICO, _ANCHO_GRAFICO
    ch.gapWidth = 55
    ch.overlap = -10
    _estilo_bloomberg(ch, formato, valores)
    hoja.add_chart(ch, ancla)


def _lineas(hoja, ancla, titulo, datos, cats, formato=None, marcadores=True):
    from openpyxl.chart import LineChart

    if datos is None:
        return
    ch = LineChart()
    ch.title = titulo
    ch.add_data(datos, titles_from_data=True)
    _poner_categorias(ch, hoja, cats)
    ch.height, ch.width = _ALTO_GRAFICO, _ANCHO_GRAFICO
    _estilo_bloomberg(ch, formato)
    hoja.add_chart(ch, ancla)


def _graficos_resumen(hoja, res, fila_tabla, resumen):
    """Valor por accion de cada metodo, junto al precio de mercado."""
    precio = res["mercado"]["precio"]
    pares = []
    for _, f in resumen.iterrows():
        if f["Aplicable"] == "Si":
            pares.append((str(f["Metodo"]).split(" (")[0], f["Valor por accion"]))
    pares.append(("Precio de mercado", precio))

    fila = fila_tabla + len(resumen) + 4
    datos, cats = _bloque_para_grafico(hoja, fila, _COL_GRAFICO,
                                       "Datos del grafico · valor por accion", pares)
    _barras(hoja, f"A{fila + len(pares) + 3}",
            "Valoracion por metodo frente al precio de mercado", datos, cats,
            formato=_FORMATO_MONEDA)


def _graficos_supuestos(hoja, res, n_filas):
    """Los supuestos porcentuales, que si son comparables entre si."""
    base, sup = res["base"], res["supuestos"]
    pares = [
        ("Crecimiento año 1", sup["g_inicial"]),
        ("Crecimiento historico", sup["g_historico"]),
        ("Crecimiento fundamental", sup["g_fundamental"]),
        ("Crecimiento perpetuo", sup["g_terminal"]),
        ("Margen EBIT base", base["margen_ebit"]),
        ("Margen EBIT objetivo", sup["margen_objetivo"]),
        ("Capex / ventas", base["capex_ventas"]),
        ("Amortizacion / ventas", base["amortizacion_ventas"]),
        ("Circulante / ventas", base["circulante_incremental"]),
        ("Tasa fiscal", res["tasa_fiscal"]),
        ("ROIC ultimo ejercicio", base["roic"]),
        ("ROIC estado estacionario", sup["roic_estable"]),
    ]
    fila = n_filas + 3
    datos, cats = _bloque_para_grafico(hoja, fila, _COL_GRAFICO,
                                       "Datos del grafico · supuestos en tanto por uno", pares)
    _barras(hoja, f"A{fila + len(pares) + 3}", "Supuestos de la proyeccion", datos, cats,
            horizontal=True, formato=_FORMATO_PCT)


def _graficos_coste_capital(hoja, res, n_filas):
    """Las tasas, todas en la misma unidad, y los pesos aparte."""
    c = res["coste"]
    tasas = [
        ("Tipo sin riesgo", c["rf"]),
        ("Prima de riesgo", c["prima"]),
        ("Coste del capital propio (Ke)", c["ke"]),
        ("Coste sin deuda (Ku)", c["ku"]),
        ("Coste de la deuda (Kd)", c["kd"]),
        ("Kd despues de impuestos", c["kd_despues_impuestos"]),
        ("WACC", c["wacc"]),
    ]
    fila = n_filas + 3
    datos, cats = _bloque_para_grafico(hoja, fila, _COL_GRAFICO,
                                       "Datos del grafico · tasas", tasas)
    _barras(hoja, f"A{fila + len(tasas) + 3}", "Componentes del coste de capital", datos, cats,
            formato=_FORMATO_PCT)

    pesos = [("Capital propio", c["peso_equity"]), ("Deuda", c["peso_deuda"])]
    fila2 = fila + len(tasas) + 2
    datos2, cats2 = _bloque_para_grafico(hoja, fila2, _COL_GRAFICO,
                                         "Datos del grafico · estructura de capital", pesos)
    _barras(hoja, f"L{fila + len(tasas) + 3}", "Estructura de capital a valor de mercado",
            datos2, cats2, formato=_FORMATO_PCT)


def _graficos_historico(hoja, res, hist_df):
    """Evolucion de las magnitudes principales, leyendo por FILAS.

    La hoja tiene las partidas en filas y los ejercicios en columnas, asi que las
    series del grafico se toman con from_rows: cada partida es una serie y cada
    ejercicio una categoria.
    """
    from openpyxl.chart import Reference

    n_anios = len(res["anios"])
    if n_anios < 2:
        return
    indice = {str(v): i for i, v in enumerate(hist_df["Partida"])}
    cats = Reference(hoja, min_col=2, max_col=1 + n_anios, min_row=1, max_row=1)

    def _refs(nombres):
        filas = [indice[n] + 2 for n in nombres if n in indice]
        return filas

    from openpyxl.chart import LineChart
    for titulo, nombres, ancla in [
        ("Cuenta de resultados", ["Ingresos", "EBIT", "Beneficio neto"], "A"),
        ("Inversion y flujo", ["Amortizacion", "Flujo de caja operativo"], "L"),
        ("Balance", ["Deuda total", "Caja y equivalentes", "Patrimonio neto",
                     "Capital invertido"], "W"),
    ]:
        filas = _refs(nombres)
        if not filas:
            continue
        ch = LineChart()
        ch.title = titulo
        for f in filas:
            ch.add_data(Reference(hoja, min_col=1, max_col=1 + n_anios, min_row=f, max_row=f),
                        titles_from_data=True, from_rows=True)
        _poner_categorias(ch, hoja, cats)
        ch.height, ch.width = _ALTO_GRAFICO, _ANCHO_GRAFICO
        _estilo_bloomberg(ch, _FORMATO_MILES)
        hoja.add_chart(ch, f"{ancla}{len(hist_df) + 4}")


def _grafico_columnas_tabla(hoja, df, columnas, titulo, ancla, formato=None,
                            col_categoria=1, tipo="col"):
    """Grafico directo sobre una tabla ya escrita, sin bloque auxiliar.

    Vale cuando la tabla ya es numerica y homogenea, que es el caso de las hojas
    de proyeccion y de detalle año a año.
    """
    from openpyxl.chart import BarChart, LineChart, Reference

    presentes = [c for c in columnas if c in df.columns]
    if not presentes or df.empty:
        return
    n = len(df)
    cats = Reference(hoja, min_col=col_categoria, min_row=2, max_row=n + 1)
    ch = BarChart() if tipo == "col" else LineChart()
    if tipo == "col":
        ch.type = "col"
        ch.gapWidth = 55
        ch.overlap = -10
    ch.title = titulo
    for nombre in presentes:
        c = list(df.columns).index(nombre) + 1
        ch.add_data(Reference(hoja, min_col=c, min_row=1, max_row=n + 1),
                    titles_from_data=True)
    _poner_categorias(ch, hoja, cats)
    ch.height, ch.width = _ALTO_GRAFICO, _ANCHO_GRAFICO
    if len(presentes) == 1:
        ch.legend = None
    _estilo_bloomberg(ch, formato)
    hoja.add_chart(ch, ancla)


def _graficos_metodo(hoja, m, n_filas, titulo, pares, formato=None):
    """Descomposicion del valor de un metodo en sus piezas."""
    fila = n_filas + 3
    datos, cats = _bloque_para_grafico(hoja, fila, _COL_GRAFICO,
                                       "Datos del grafico · descomposicion", pares)
    valores = [_num_o_nada(v) for _, v in pares]
    valores = [v for v in valores if v is not None]
    _barras(hoja, f"A{fila + len(pares) + 3}", titulo, datos, cats, formato=formato,
            valores=valores)


def _graficos_sensibilidad(hoja, sens):
    """Una linea por crecimiento perpetuo, con el WACC en el eje."""
    from openpyxl.chart import LineChart, Reference

    if sens is None or sens.empty:
        return
    n = len(sens)
    cats = Reference(hoja, min_col=1, min_row=2, max_row=n + 1)
    ch = LineChart()
    ch.title = "Valor por accion segun WACC y crecimiento perpetuo"
    for c in range(2, len(sens.columns) + 1):
        ch.add_data(Reference(hoja, min_col=c, min_row=1, max_row=n + 1), titles_from_data=True)
    _poner_categorias(ch, hoja, cats)
    ch.height, ch.width = 10.5, 21
    ch.x_axis.title = "WACC"
    ch.y_axis.title = "Valor por accion"
    _estilo_bloomberg(ch, _FORMATO_MONEDA)
    hoja.add_chart(ch, f"A{n + 4}")


def _graficos_diagnostico(hoja, diag):
    """Recuento de comprobaciones por estado."""
    conteo = diag["Estado"].value_counts().to_dict()
    orden = ["OK", "AVISO", "SUPUESTO", "CORREGIDO", "DERIVADO", "FALLA", "FALTA",
             "NO COMPARABLE"]
    pares = [(e, conteo[e]) for e in orden if e in conteo]
    pares += [(e, v) for e, v in conteo.items() if e not in orden]
    fila = len(diag) + 3
    datos, cats = _bloque_para_grafico(hoja, fila, 5,
                                       "Datos del grafico · recuento por estado", pares)
    _barras(hoja, f"A{fila + len(pares) + 3}", "Comprobaciones por estado", datos, cats)
