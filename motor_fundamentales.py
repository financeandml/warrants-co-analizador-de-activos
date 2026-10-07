"""Motor de fundamentales del ANALIZADOR DE ACTIVOS.

Implementa el subconjunto de la especificacion M1-M54 que es construible con
fuentes publicas y verificables: XBRL de SEC EDGAR (cifras tal y como se
declararon, con fecha de presentacion) y Yahoo Finance.

Principio de diseno tomado del propio documento (M9):
    el sistema nunca confia en una cifra agregada que pueda recalcular
    desde el origen.

Por eso toda metrica se recalcula desde los estados financieros y, cuando SEC
publica el dato primario, se coteja contra el proveedor y se marca la
discrepancia en lugar de elegir una fuente en silencio.

Modulos cubiertos y NO cubiertos: ver COBERTURA al final del archivo.
"""

import json
import os
import time
import urllib.error
import urllib.request
from datetime import date, datetime

import numpy as np
import pandas as pd
import yfinance as yf

# SEC exige identificarse con un correo de contacto real en cada peticion, y no
# es una formalidad: sin una direccion valida en la cabecera devuelve 403 en
# TODAS las consultas.
#
# La variable de entorno SEC_CONTACTO tiene prioridad, de modo que quien
# despliegue el programa se identifique con la suya. El valor por defecto es el
# del autor para que la instalacion local siga funcionando sin configurar nada.
#
# Un marcador de posicion NO sirve como valor por defecto: al ponerlo, la SEC
# empezo a rechazar cada peticion y el apartado de fundamentales quedo vacio
# para todas las empresas, sin un solo mensaje de error. De ahi que el fallo se
# declare ahora en voz alta unas lineas mas abajo.
CONTACTO_POR_DEFECTO = "financeandml@gmail.com"
CONTACTO_SEC = os.environ.get("SEC_CONTACTO", "").strip() or CONTACTO_POR_DEFECTO
CABECERA_SEC = {"User-Agent": f"Analizador de Activos - {CONTACTO_SEC}"}
TIEMPO_ESPERA = 25

# Ultimo fallo de acceso a la SEC, para que las pantallas puedan explicarlo en
# lugar de mostrar un apartado vacio.
ULTIMO_FALLO_SEC = None


class AccesoSecRechazado(Exception):
    """La SEC ha rechazado la peticion. No significa que la empresa no exista."""

# Umbrales de antiguedad (M3/M9: marca de obsolescencia obligatoria)
DIAS_DATO_FRESCO = 100      # un trimestre
DIAS_DATO_CADUCO = 200      # mas de dos trimestres sin actualizar

BOLSA = "America/New_York"


def _hoy_mercado():
    """Fecha de hoy en Nueva York, con independencia de donde se ejecute."""
    return pd.Timestamp.now(tz=BOLSA).normalize().tz_localize(None)


# =============================================================================
#  ACCESO A SEC EDGAR (M1 - datos primarios "as reported")
# =============================================================================

def _pedir_json(url):
    """Consulta a EDGAR. Deja constancia del motivo cuando la SEC rechaza.

    Un 403 significa que la cabecera de identificacion no le vale a la SEC, y
    afecta por igual a TODAS las consultas: confundirlo con "esta empresa no
    presenta cuentas" hace que el programa acuse de no cotizar en Estados
    Unidos a companias que llevan decadas haciendolo.
    """
    global ULTIMO_FALLO_SEC
    try:
        peticion = urllib.request.Request(url, headers=CABECERA_SEC)
        with urllib.request.urlopen(peticion, timeout=TIEMPO_ESPERA) as r:
            datos = json.loads(r.read())
        ULTIMO_FALLO_SEC = None
        return datos
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            ULTIMO_FALLO_SEC = (
                f"La SEC ha rechazado la petición (HTTP {e.code}). Exige "
                f"identificarse con un correo de contacto válido en la cabecera; "
                f"el configurado es «{CONTACTO_SEC}». Defina la variable de "
                f"entorno SEC_CONTACTO con una dirección real.")
        elif e.code == 429:
            ULTIMO_FALLO_SEC = (
                "La SEC ha limitado el número de peticiones (HTTP 429). "
                "Inténtelo de nuevo en unos segundos.")
        else:
            ULTIMO_FALLO_SEC = f"La SEC ha respondido con HTTP {e.code}."
        return None
    except Exception as e:
        ULTIMO_FALLO_SEC = f"No se ha podido consultar la SEC: {type(e).__name__}."
        return None


def mapa_ticker_cik():
    """Diccionario ticker -> CIK de todos los emisores registrados en la SEC."""
    datos = _pedir_json("https://www.sec.gov/files/company_tickers.json")
    if not datos:
        return {}
    return {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in datos.values()}


def companyfacts(cik):
    """Todos los hechos XBRL declarados por la empresa, con fecha de presentacion."""
    if not cik:
        return None
    return _pedir_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")


def serie_concepto(hechos, conceptos, taxonomia="us-gaap", unidad=None):
    """Serie historica de un concepto XBRL tal y como se declaro.

    `conceptos` puede ser una lista: se usa el primero que exista, porque las
    empresas no siempre etiquetan la misma magnitud con el mismo nombre.
    Devuelve un DataFrame con el valor, el periodo, la fecha de PRESENTACION y
    el formulario, que es lo que permite reconstruir que se sabia en cada fecha.
    """
    if not hechos:
        return None
    if isinstance(conceptos, str):
        conceptos = [conceptos]
    bloque = hechos.get("facts", {}).get(taxonomia, {})
    for concepto in conceptos:
        if concepto not in bloque:
            continue
        unidades = bloque[concepto].get("units", {})
        clave = unidad or next(iter(unidades), None)
        if not clave or clave not in unidades:
            continue
        filas = []
        for r in unidades[clave]:
            filas.append({
                "concepto": concepto,
                "inicio": r.get("start"),
                "fin": r.get("end"),
                "valor": r.get("val"),
                "presentado": r.get("filed"),
                "formulario": r.get("form"),
                "ejercicio": r.get("fy"),
                "periodo": r.get("fp"),
            })
        if filas:
            df = pd.DataFrame(filas)
            df["fin"] = pd.to_datetime(df["fin"])
            df["presentado"] = pd.to_datetime(df["presentado"])
            return df.sort_values("fin")
    return None


# =============================================================================
#  ESTADOS FINANCIEROS (M1)
# =============================================================================

def _fila(df, nombres, columna=0):
    """Lee una partida del estado financiero probando varios nombres posibles."""
    if df is None or df.empty:
        return np.nan
    if isinstance(nombres, str):
        nombres = [nombres]
    for n in nombres:
        if n in df.index:
            try:
                v = df.loc[n].iloc[columna]
            except Exception:
                continue
            if pd.notna(v):
                return float(v)
    return np.nan


def _serie(df, nombres):
    """Serie de una partida indexada por AÑO fiscal (entero), de mas antiguo a mas reciente.

    Indexar por año y no por posicion es imprescindible: yfinance devuelve un
    numero DISTINTO de ejercicios en cada estado (p. ej. 4 años de cuenta de
    resultados y 5 de balance). Emparejando por posicion se cruzan años
    diferentes, lo que producia errores de mas del 20% en los dias de cobro.
    """
    if df is None or df.empty:
        return None
    if isinstance(nombres, str):
        nombres = [nombres]
    for n in nombres:
        if n in df.index:
            s = df.loc[n].astype(float)
            s.index = [pd.to_datetime(c).year for c in s.index]
            s = s[~s.index.duplicated(keep="first")]   # cambio de ejercicio fiscal
            return s.sort_index()
    return None


def _v(serie, anio):
    """Valor de una serie en un año concreto; NaN si ese año no existe."""
    if serie is None:
        return np.nan
    try:
        v = serie.get(anio, np.nan)
        return float(v) if pd.notna(v) else np.nan
    except Exception:
        return np.nan


def _anios_comunes(*series):
    """Años presentes en TODAS las series indicadas, en orden ascendente."""
    conjuntos = [set(s.index) for s in series if s is not None and len(s)]
    if not conjuntos:
        return []
    comunes = set.intersection(*conjuntos)
    return sorted(comunes)


def _limpiar_estado(df):
    """Elimina los ejercicios que Yahoo devuelve completamente vacios.

    yfinance añade a menudo una columna de relleno sin ningun dato. Si se deja,
    contamina cualquier calculo que compare el primer ejercicio con el ultimo
    (el ROIC incremental salia NaN por este motivo).
    """
    if df is None or df.empty:
        return df
    return df.dropna(axis=1, how="all")


def estados_financieros(simbolo):
    """Cuenta de resultados, balance y flujo de caja, anuales y trimestrales."""
    t = yf.Ticker(simbolo)
    try:
        salida = {
            "resultados": _limpiar_estado(t.income_stmt),
            "balance": _limpiar_estado(t.balance_sheet),
            "flujo": _limpiar_estado(t.cashflow),
            "resultados_trim": _limpiar_estado(t.quarterly_income_stmt),
            "balance_trim": _limpiar_estado(t.quarterly_balance_sheet),
            "flujo_trim": _limpiar_estado(t.quarterly_cashflow),
        }
    except Exception:
        return None
    if salida["resultados"] is None or salida["resultados"].empty:
        return None
    return salida


# =============================================================================
#  M9 - RECONCILIACION Y CONTROL DE CALIDAD
# =============================================================================

# yf.Ticker(...).info es una peticion de red, y aqui se construia un Ticker nuevo
# en cada llamada. Como reconciliar() se ejecuta en cada repintado de la pestaña,
# eso costaba cuatro peticiones y un segundo entero de espera POR CADA CLIC del
# usuario, para volver a preguntar un dato que cambia una vez por trimestre.
#
# La memoria caduca en lugar de ser perpetua porque un recuento rancio no avisa
# de que lo es: se colaria en la capitalizacion y de ahi en todos los multiplos
# sin que nada lo delatara en pantalla.
_MEMORIA_ACCIONES = {}
VIGENCIA_ACCIONES = 3600          # segundos


def acciones_en_circulacion(simbolo):
    """Acciones en circulacion segun el proveedor, o NaN si no las publica.

    El fallo de la fuente y el dato ausente devuelven ambos NaN, pero solo el
    segundo se memoriza: memorizar un corte de red dejaria la cifra vacia
    durante una hora despues de haberse resuelto.

    El cero se trata como ausencia, no como cifra. Las empresas con doble clase
    de accion declaran a veces un total sin dimensionar igual a 0, y tomarlo por
    bueno dejaba la capitalizacion en cero arrastrando a todos los multiplos.
    """
    ahora = time.time()
    guardado = _MEMORIA_ACCIONES.get(simbolo)
    if guardado is not None and ahora - guardado[0] < VIGENCIA_ACCIONES:
        return guardado[1]
    # La conversion va DENTRO del try junto con la peticion, como estaba antes de
    # extraer esta funcion: si el proveedor devuelve algo que no es un numero, el
    # fallo debe quedarse aqui y no tumbar toda la reconciliacion.
    try:
        bruto = yf.Ticker(simbolo).info.get("sharesOutstanding")
        valor = float(bruto) if bruto else np.nan
    except Exception:
        return np.nan
    _MEMORIA_ACCIONES[simbolo] = (ahora, valor)
    return valor


def reconciliar(simbolo, estados, hechos_sec):
    """Coteja el proveedor contra el dato primario y valida la integridad contable.

    Es el modulo que el documento considera la diferencia entre un sistema
    fiable y uno peligroso. No elige una fuente en silencio: marca la
    discrepancia y muestra ambas.
    """
    incidencias = []
    comprobaciones = []

    # --- Numero de acciones: proveedor frente a ultimo balance presentado ---
    acciones_yf = acciones_en_circulacion(simbolo)

    acciones_sec, fecha_sec, form_sec, presentado_sec = np.nan, None, None, None
    serie = serie_concepto(hechos_sec, "EntityCommonStockSharesOutstanding",
                           taxonomia="dei")
    if serie is not None and not serie.empty:
        # Dos cautelas, ambas descubiertas con casos reales:
        #  - Hay que descartar los valores nulos o negativos. Las empresas con
        #    doble clase de accion (Molson Coors, por ejemplo) declaran a veces
        #    un total sin dimensionar igual a 0. Tomarlo por bueno dejaba la
        #    capitalizacion en cero y arrastraba a todos los multiplos.
        #  - Hay que ordenar por FECHA DE PRESENTACION, no por fin de periodo:
        #    lo que interesa es el recuento mas recientemente comunicado.
        validos = serie[serie["valor"] > 0]
        if not validos.empty:
            ult = validos.sort_values("presentado").iloc[-1]
            acciones_sec = float(ult["valor"])
            fecha_sec, form_sec = ult["fin"], ult["formulario"]
            presentado_sec = ult["presentado"]

    # Cual de las dos cifras usar. Regla, derivada de casos reales:
    #  - Desvio moderado (hasta el 25%): el dato de la SEC es el bueno, porque el
    #    proveedor suele arrastrar un recuento antiguo (Ichor: 34,9 M frente a
    #    37,5 M declaradas).
    #  - Desvio enorme: casi siempre significa que la SEC publica UNA SOLA CLASE
    #    de accion y el proveedor agrega todas. En Interactive Brokers la SEC da
    #    42,2 M (clase A) frente a 445,5 M totales: preferir la SEC dividiria la
    #    capitalizacion por diez. En ese caso se usa el proveedor y se avisa.
    LIMITE_CLASE_UNICA = 0.25
    acciones_elegidas, fuente_acciones = acciones_yf, "proveedor"
    if np.isfinite(acciones_yf) and np.isfinite(acciones_sec) and acciones_sec:
        desvio = acciones_yf / acciones_sec - 1
        if abs(desvio) > LIMITE_CLASE_UNICA:
            comprobaciones.append({
                "Comprobacion": "Numero de acciones: proveedor vs SEC",
                "Estado": "REVISAR",
                "Detalle": (f"Yahoo {acciones_yf:,.0f} frente a {acciones_sec:,.0f} "
                            f"en el {form_sec} ({desvio:+.0%}). Un desvio de esta "
                            f"magnitud suele indicar varias clases de accion: la "
                            f"SEC declara una y el proveedor las agrega. Se usa la "
                            f"cifra del proveedor."),
            })
            incidencias.append(
                f"El recuento de acciones difiere un {desvio:+.0%} entre fuentes. "
                f"Lo habitual es que la empresa tenga mas de una clase de accion. "
                f"Los multiplos usan la cifra agregada del proveedor; conviene "
                f"comprobarla en el ultimo balance antes de usarlos.")
        else:
            grave = abs(desvio) > 0.01
            acciones_elegidas, fuente_acciones = acciones_sec, "SEC"
            comprobaciones.append({
                "Comprobacion": "Numero de acciones: proveedor vs SEC",
                "Estado": "DISCREPANCIA" if grave else "OK",
                "Detalle": (f"Yahoo {acciones_yf:,.0f} frente a {acciones_sec:,.0f} "
                            f"declaradas en el {form_sec} presentado el "
                            f"{presentado_sec.date()} ({desvio:+.1%})"),
            })
            if grave:
                incidencias.append(
                    f"El numero de acciones del proveedor se desvia un {desvio:+.1%} "
                    f"del ultimo balance presentado. Se usa el dato de la SEC, que "
                    f"es el declarado por la empresa.")
    elif np.isfinite(acciones_sec) and acciones_sec:
        acciones_elegidas, fuente_acciones = acciones_sec, "SEC"
        comprobaciones.append({
            "Comprobacion": "Numero de acciones: proveedor vs SEC",
            "Estado": "OK",
            "Detalle": f"Solo hay dato de la SEC: {acciones_sec:,.0f}",
        })
    else:
        comprobaciones.append({
            "Comprobacion": "Numero de acciones: proveedor vs SEC",
            "Estado": "SIN DATO",
            "Detalle": "No hay dato primario de la SEC para cotejar.",
        })

    # --- Integridad del balance: Activo = Pasivo + Patrimonio ---
    # OJO con la partida de patrimonio: "Stockholders Equity" EXCLUYE a los
    # minoritarios, mientras que "Total Liabilities Net Minority Interest" ya los
    # ha descontado. Combinarlas dejaba fuera el interes minoritario y generaba
    # descuadres falsos en toda empresa que lo tenga (Linde 1,7%, GM 0,7%).
    # Con el patrimonio TOTAL el balance cuadra al 0,000%.
    bal = estados.get("balance") if estados else None
    activo = _fila(bal, ["Total Assets"])
    pasivo = _fila(bal, ["Total Liabilities Net Minority Interest", "Total Liabilities"])
    patrimonio = _fila(bal, ["Total Equity Gross Minority Interest"])
    if not np.isfinite(patrimonio):
        propio = _fila(bal, ["Stockholders Equity"])
        minoritarios = _fila(bal, ["Minority Interest"])
        patrimonio = np.nansum([propio, minoritarios]) if np.isfinite(propio) else np.nan
    if all(np.isfinite(x) for x in (activo, pasivo, patrimonio)) and activo:
        descuadre = (pasivo + patrimonio) / activo - 1
        ok = abs(descuadre) < 0.01
        comprobaciones.append({
            "Comprobacion": "Cuadre del balance (Activo = Pasivo + Patrimonio)",
            "Estado": "OK" if ok else "DESCUADRE",
            "Detalle": f"Activo {activo:,.0f} frente a pasivo mas patrimonio "
                       f"{pasivo + patrimonio:,.0f} ({descuadre:+.2%})",
        })
        if not ok:
            incidencias.append("El balance no cuadra; puede faltar la participacion "
                               "de minoritarios en los datos del proveedor.")
    else:
        comprobaciones.append({
            "Comprobacion": "Cuadre del balance",
            "Estado": "SIN DATO",
            "Detalle": "Faltan partidas para verificar el cuadre.",
        })

    # --- Antiguedad del ultimo estado publicado (marca de obsolescencia) ---
    antiguedad = np.nan
    if estados and estados.get("resultados_trim") is not None \
            and not estados["resultados_trim"].empty:
        ultimo = pd.to_datetime(estados["resultados_trim"].columns[0])
        # Fecha del mercado estadounidense, no del reloj de quien ejecuta:
        # los cierres contables que publica la SEC son fechas de alli y el
        # desfase de zona horaria desplazaria la antiguedad un dia, justo en
        # el limite entre "vigente" y "requiere atencion".
        antiguedad = (_hoy_mercado() - ultimo).days
        if antiguedad <= DIAS_DATO_FRESCO:
            estado = "OK"
        elif antiguedad <= DIAS_DATO_CADUCO:
            estado = "ATENCION"
        else:
            estado = "CADUCADO"
        comprobaciones.append({
            "Comprobacion": "Antiguedad del ultimo trimestre publicado",
            "Estado": estado,
            "Detalle": f"Cierre {ultimo.date()}, hace {antiguedad} dias",
        })
        if estado == "CADUCADO":
            incidencias.append(f"El ultimo trimestre disponible tiene {antiguedad} "
                               f"dias. Las metricas pueden no reflejar la situacion actual.")

    # --- Coherencia del flujo de caja libre ---
    flujo = estados.get("flujo") if estados else None
    ocf = _fila(flujo, ["Operating Cash Flow"])
    capex = _fila(flujo, ["Capital Expenditure"])
    fcf = _fila(flujo, ["Free Cash Flow"])
    if all(np.isfinite(x) for x in (ocf, capex, fcf)):
        recalculado = ocf + capex          # capex viene en negativo
        ok = abs(recalculado - fcf) <= max(abs(fcf) * 0.02, 1e5)
        comprobaciones.append({
            "Comprobacion": "Flujo de caja libre recalculado desde el origen",
            "Estado": "OK" if ok else "DISCREPANCIA",
            "Detalle": f"Publicado {fcf:,.0f} frente a {recalculado:,.0f} "
                       f"recalculado como flujo operativo menos capex",
        })

    return {
        "comprobaciones": pd.DataFrame(comprobaciones),
        "incidencias": incidencias,
        "acciones_proveedor": acciones_yf,
        "acciones_sec": acciones_sec,
        # Cifra que debe usarse en capitalizacion y multiplos, ya arbitrada
        "acciones": acciones_elegidas,
        "fuente_acciones": fuente_acciones,
        "acciones_fecha": fecha_sec,
        "acciones_formulario": form_sec,
        "acciones_presentado": presentado_sec,
        "antiguedad_dias": antiguedad,
        "bloqueante": bool(incidencias),
    }


# =============================================================================
#  M11 - CALIDAD DEL BENEFICIO
# =============================================================================

def calidad_beneficio(estados, es_financiera=False):
    """Determina si el beneficio declarado se convierte en caja.

    Devengos de Sloan, conversion en caja, ciclo de conversion de efectivo y
    divergencia entre ingresos y partidas de circulante.

    El ciclo de caja (DSO, DIO, DPO) SOLO se calcula cuando significa algo. Se
    suprime en dos situaciones, ambas detectadas sobre empresas reales:
      - Entidades financieras: sus "cuentas por cobrar" y "por pagar" son saldos
        de clientes, no credito comercial. En Interactive Brokers producian un
        periodo medio de cobro de 3.231 dias.
      - Negocios sin coste de ventas representativo, como los REITs: Vici
        Properties declara 26 M de coste sobre 4.006 M de ingresos, lo que
        disparaba el periodo de pago a 6.640 dias.
    """
    res, bal, flu = estados["resultados"], estados["balance"], estados["flujo"]

    ingresos = _serie(res, ["Total Revenue", "Operating Revenue"])
    neto = _serie(res, ["Net Income", "Net Income Common Stockholders"])
    ocf = _serie(flu, ["Operating Cash Flow"])
    fcf = _serie(flu, ["Free Cash Flow"])
    activos = _serie(bal, ["Total Assets"])
    cobrar = _serie(bal, ["Accounts Receivable", "Receivables"])
    inventario = _serie(bal, ["Inventory"])
    pagar = _serie(bal, ["Accounts Payable", "Payables"])
    coste = _serie(res, ["Cost Of Revenue", "Reconciled Cost Of Revenue"])
    impuesto = _serie(res, ["Tax Provision"])
    antes_imp = _serie(res, ["Pretax Income"])

    if ingresos is None or neto is None or ocf is None:
        return None

    filas = []
    for anio in ingresos.index:            # se recorre por AÑO, no por posicion
        f = {"Ejercicio": int(anio)}
        ing = _v(ingresos, anio)
        ni = _v(neto, anio)
        cf = _v(ocf, anio)
        ta = _v(activos, anio)

        f["Ingresos"] = ing
        f["Beneficio neto"] = ni
        f["Flujo operativo"] = cf
        f["Flujo caja libre"] = _v(fcf, anio)
        # Devengos de Sloan: cuanto del beneficio NO es caja
        f["Devengos Sloan"] = ((ni - cf) / ta) if all(np.isfinite([ni, cf, ta])) and ta else np.nan
        f["Conversion OCF/BN"] = (cf / ni) if np.isfinite(ni) and ni else np.nan
        f["Conversion FCF/BN"] = (f["Flujo caja libre"] / ni) if np.isfinite(ni) and ni else np.nan

        # Ciclo de conversion de efectivo, solo donde es interpretable
        ar, inv = _v(cobrar, anio), _v(inventario, anio)
        ap, cog = _v(pagar, anio), _v(coste, anio)
        # Un coste de ventas inferior al 5% de los ingresos indica que la
        # empresa no tiene aprovisionamiento en sentido convencional.
        coste_representativo = (np.isfinite(cog) and np.isfinite(ing) and ing
                                and cog / ing >= 0.05)
        if es_financiera:
            f["DSO"] = f["DIO"] = f["DPO"] = f["Ciclo de caja"] = np.nan
        else:
            f["DSO"] = (ar / ing * 365) if np.isfinite(ar) and np.isfinite(ing) and ing else np.nan
            f["DIO"] = (inv / cog * 365) if np.isfinite(inv) and coste_representativo else np.nan
            f["DPO"] = (ap / cog * 365) if np.isfinite(ap) and coste_representativo else np.nan
            f["Ciclo de caja"] = f["DSO"] + f["DIO"] - f["DPO"]

        # Tasa fiscal efectiva
        tx, pt = _v(impuesto, anio), _v(antes_imp, anio)
        f["Tasa fiscal efectiva"] = (tx / pt) if np.isfinite(tx) and np.isfinite(pt) and pt else np.nan
        filas.append(f)

    tabla = pd.DataFrame(filas)

    # Divergencia entre crecimiento de ingresos y de circulante (ultimo ejercicio)
    def _crec(serie):
        if serie is None or len(serie) < 2:
            return np.nan
        a, b = float(serie.iloc[-2]), float(serie.iloc[-1])
        return (b / a - 1) if a else np.nan

    crec_ing = _crec(ingresos)
    crec_ar = _crec(cobrar)
    crec_inv = _crec(inventario)

    ultimo = tabla.iloc[-1] if len(tabla) else None
    alertas = []
    if ultimo is not None:
        if np.isfinite(ultimo["Devengos Sloan"]) and ultimo["Devengos Sloan"] > 0.10:
            alertas.append(f"Devengos de Sloan de {ultimo['Devengos Sloan']:.1%}: una "
                           f"parte alta del beneficio no ha llegado a caja.")
        if np.isfinite(ultimo["Conversion OCF/BN"]) and ultimo["Conversion OCF/BN"] < 0.8:
            alertas.append(f"El flujo operativo cubre solo {ultimo['Conversion OCF/BN']:.0%} "
                           f"del beneficio neto.")
        if np.isfinite(ultimo["Tasa fiscal efectiva"]) and (
                ultimo["Tasa fiscal efectiva"] > 0.40 or ultimo["Tasa fiscal efectiva"] < 0):
            alertas.append(f"Tasa fiscal efectiva anomala: "
                           f"{ultimo['Tasa fiscal efectiva']:.0%}.")
    if np.isfinite(crec_ing) and np.isfinite(crec_ar) and crec_ar > crec_ing + 0.10:
        alertas.append(f"Las cuentas por cobrar crecen {crec_ar:.1%} frente al "
                       f"{crec_ing:.1%} de los ingresos.")
    if np.isfinite(crec_ing) and np.isfinite(crec_inv) and crec_inv > crec_ing + 0.15:
        alertas.append(f"El inventario crece {crec_inv:.1%} frente al {crec_ing:.1%} "
                       f"de los ingresos.")

    return {"tabla": tabla, "alertas": alertas,
            "crec_ingresos": crec_ing, "crec_cobrar": crec_ar, "crec_inventario": crec_inv}


# =============================================================================
#  M12 - RIESGO CONTABLE: PIOTROSKI, ALTMAN, BENEISH
# =============================================================================

def piotroski_f(estados):
    """F-Score de Piotroski: 9 pruebas binarias de solidez fundamental."""
    res, bal, flu = estados["resultados"], estados["balance"], estados["flujo"]
    activos = _serie(bal, ["Total Assets"])
    neto = _serie(res, ["Net Income", "Net Income Common Stockholders"])
    ocf = _serie(flu, ["Operating Cash Flow"])
    deuda_lp = _serie(bal, ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"])
    circ_act = _serie(bal, ["Current Assets", "Total Current Assets"])
    circ_pas = _serie(bal, ["Current Liabilities", "Total Current Liabilities"])
    bruto = _serie(res, ["Gross Profit"])
    ingresos = _serie(res, ["Total Revenue", "Operating Revenue"])
    acciones = _serie(res, ["Diluted Average Shares", "Basic Average Shares"])

    if activos is None or len(activos) < 2 or neto is None or ocf is None:
        return None

    # Se comparan los dos ultimos ejercicios PRESENTES EN AMBOS estados. Tomar
    # las dos ultimas posiciones de cada serie por separado cruzaria años
    # distintos cuando yfinance devuelve mas ejercicios de balance que de
    # cuenta de resultados, que es el caso habitual.
    comunes = _anios_comunes(activos, neto, ocf)
    if len(comunes) < 2:
        return None
    a_ant, a_act = comunes[-2], comunes[-1]

    def v(s, i):
        return _v(s, a_act if i == -1 else a_ant)

    roa_act = v(neto, -1) / v(activos, -1) if v(activos, -1) else np.nan
    roa_ant = v(neto, -2) / v(activos, -2) if v(activos, -2) else np.nan

    pruebas = []

    def añadir(nombre, condicion, detalle):
        punto = 1 if condicion is True else 0
        pruebas.append({"Prueba": nombre, "Punto": punto, "Detalle": detalle})

    añadir("Rentabilidad sobre activos positiva", roa_act > 0 if np.isfinite(roa_act) else None,
           f"ROA {roa_act:.2%}" if np.isfinite(roa_act) else "sin dato")
    añadir("Flujo de caja operativo positivo", v(ocf, -1) > 0 if np.isfinite(v(ocf, -1)) else None,
           f"{v(ocf,-1):,.0f}" if np.isfinite(v(ocf, -1)) else "sin dato")
    añadir("ROA mejora respecto al ejercicio anterior",
           roa_act > roa_ant if np.isfinite(roa_act) and np.isfinite(roa_ant) else None,
           f"{roa_ant:.2%} -> {roa_act:.2%}" if np.isfinite(roa_ant) else "sin dato")
    calidad = (v(ocf, -1) > v(neto, -1)) if np.isfinite(v(ocf, -1)) and np.isfinite(v(neto, -1)) else None
    añadir("Flujo operativo mayor que el beneficio neto", calidad,
           "el beneficio se convierte en caja" if calidad else "el beneficio no se convierte en caja")

    if deuda_lp is not None and len(deuda_lp) >= 2 and v(activos, -1) and v(activos, -2):
        pal_act = v(deuda_lp, -1) / v(activos, -1)
        pal_ant = v(deuda_lp, -2) / v(activos, -2)
        añadir("El apalancamiento no aumenta", pal_act <= pal_ant,
               f"{pal_ant:.1%} -> {pal_act:.1%}")
    else:
        añadir("El apalancamiento no aumenta", None, "sin dato")

    if circ_act is not None and circ_pas is not None and len(circ_act) >= 2:
        r_act = v(circ_act, -1) / v(circ_pas, -1) if v(circ_pas, -1) else np.nan
        r_ant = v(circ_act, -2) / v(circ_pas, -2) if v(circ_pas, -2) else np.nan
        añadir("La liquidez corriente mejora",
               r_act > r_ant if np.isfinite(r_act) and np.isfinite(r_ant) else None,
               f"{r_ant:.2f} -> {r_act:.2f}" if np.isfinite(r_ant) else "sin dato")
    else:
        añadir("La liquidez corriente mejora", None, "sin dato")

    if acciones is not None and len(acciones) >= 2:
        añadir("No se han emitido acciones nuevas", v(acciones, -1) <= v(acciones, -2) * 1.005,
               f"{v(acciones,-2):,.0f} -> {v(acciones,-1):,.0f}")
    else:
        añadir("No se han emitido acciones nuevas", None, "sin dato")

    if bruto is not None and ingresos is not None and len(bruto) >= 2:
        mb_act = v(bruto, -1) / v(ingresos, -1) if v(ingresos, -1) else np.nan
        mb_ant = v(bruto, -2) / v(ingresos, -2) if v(ingresos, -2) else np.nan
        añadir("El margen bruto mejora",
               mb_act > mb_ant if np.isfinite(mb_act) and np.isfinite(mb_ant) else None,
               f"{mb_ant:.1%} -> {mb_act:.1%}" if np.isfinite(mb_ant) else "sin dato")
    else:
        añadir("El margen bruto mejora", None, "sin dato")

    if ingresos is not None and len(ingresos) >= 2:
        rot_act = v(ingresos, -1) / v(activos, -1) if v(activos, -1) else np.nan
        rot_ant = v(ingresos, -2) / v(activos, -2) if v(activos, -2) else np.nan
        añadir("La rotacion de activos mejora",
               rot_act > rot_ant if np.isfinite(rot_act) and np.isfinite(rot_ant) else None,
               f"{rot_ant:.2f} -> {rot_act:.2f}" if np.isfinite(rot_ant) else "sin dato")
    else:
        añadir("La rotacion de activos mejora", None, "sin dato")

    tabla = pd.DataFrame(pruebas)
    return {"tabla": tabla, "puntuacion": int(tabla["Punto"].sum()), "maximo": len(tabla)}


def altman_z(estados, capitalizacion, es_financiera=False):
    """Z-Score de Altman.

    PROHIBICION ACTIVA: no se calcula para entidades financieras. Su balance
    hace que las variables del modelo no signifiquen lo mismo, y un Z-Score
    sobre un banco es un numero sin contenido.
    """
    if es_financiera:
        return {"bloqueado": True,
                "motivo": "El Z-Score de Altman no es aplicable a entidades "
                          "financieras: fue calibrado sobre empresas "
                          "manufactureras y sus variables no significan lo "
                          "mismo en un balance bancario."}
    res, bal = estados["resultados"], estados["balance"]
    ta = _fila(bal, ["Total Assets"])
    circ_act = _fila(bal, ["Current Assets", "Total Current Assets"])
    circ_pas = _fila(bal, ["Current Liabilities", "Total Current Liabilities"])
    reservas = _fila(bal, ["Retained Earnings"])
    ebit = _fila(res, ["EBIT", "Operating Income"])
    pasivo = _fila(bal, ["Total Liabilities Net Minority Interest", "Total Liabilities"])
    ventas = _fila(res, ["Total Revenue", "Operating Revenue"])

    if not np.isfinite(ta) or not ta:
        return None
    x1 = (circ_act - circ_pas) / ta if np.isfinite(circ_act) and np.isfinite(circ_pas) else np.nan
    x2 = reservas / ta if np.isfinite(reservas) else np.nan
    x3 = ebit / ta if np.isfinite(ebit) else np.nan
    x4 = capitalizacion / pasivo if np.isfinite(pasivo) and pasivo and np.isfinite(capitalizacion) else np.nan
    x5 = ventas / ta if np.isfinite(ventas) else np.nan

    componentes = [
        ("X1 Circulante / Activo", x1, 1.2),
        ("X2 Reservas / Activo", x2, 1.4),
        ("X3 EBIT / Activo", x3, 3.3),
        ("X4 Capitalizacion / Pasivo", x4, 0.6),
        ("X5 Ventas / Activo", x5, 1.0),
    ]
    if any(not np.isfinite(c[1]) for c in componentes):
        return None
    z = sum(v * p for _, v, p in componentes)
    if z > 2.99:
        zona = "Zona segura (Z > 2,99)"
    elif z > 1.81:
        zona = "Zona gris (1,81 < Z < 2,99)"
    else:
        zona = "Zona de alerta (Z < 1,81)"
    tabla = pd.DataFrame([{"Componente": n, "Valor": v, "Peso": p, "Aportacion": v * p}
                          for n, v, p in componentes])
    return {"z": z, "zona": zona, "tabla": tabla}


def beneish_m(estados, es_financiera=False):
    """M-Score de Beneish con sus ocho componentes visibles individualmente.

    PROHIBICION ACTIVA para entidades financieras: el modelo se apoya en
    inventario, coste de ventas y activo fijo, partidas que en un banco no
    existen o no significan lo mismo.
    """
    if es_financiera:
        return {"bloqueado": True,
                "motivo": "El M-Score de Beneish se apoya en inventario, coste "
                          "de ventas y activo fijo. En una entidad financiera "
                          "esas partidas no existen o no son comparables."}
    res, bal, flu = estados["resultados"], estados["balance"], estados["flujo"]

    # Los ocho componentes comparan el ultimo ejercicio con el anterior. Los dos
    # años tienen que ser los MISMOS para todas las partidas, o se estarian
    # mezclando ejercicios de estados con distinta profundidad historica.
    _anclas = _anios_comunes(
        _serie(res, ["Total Revenue", "Operating Revenue"]),
        _serie(bal, ["Total Assets"]),
        _serie(flu, ["Operating Cash Flow"]))
    if len(_anclas) < 2:
        return None
    _ant, _act = _anclas[-2], _anclas[-1]

    def par(df, nombres):
        s = _serie(df, nombres)
        if s is None:
            return np.nan, np.nan
        return _v(s, _ant), _v(s, _act)

    ing_a, ing_b = par(res, ["Total Revenue", "Operating Revenue"])
    ar_a, ar_b = par(bal, ["Accounts Receivable", "Receivables"])
    cog_a, cog_b = par(res, ["Cost Of Revenue", "Reconciled Cost Of Revenue"])
    ta_a, ta_b = par(bal, ["Total Assets"])
    ca_a, ca_b = par(bal, ["Current Assets", "Total Current Assets"])
    ppe_a, ppe_b = par(bal, ["Net PPE", "Net Tangible Assets"])
    dep_a, dep_b = par(flu, ["Depreciation And Amortization", "Depreciation Amortization Depletion"])
    sga_a, sga_b = par(res, ["Selling General And Administration", "Selling General And Administrative"])
    dlp_a, dlp_b = par(bal, ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"])
    cp_a, cp_b = par(bal, ["Current Liabilities", "Total Current Liabilities"])
    ni_a, ni_b = par(res, ["Net Income", "Net Income Common Stockholders"])
    ocf_a, ocf_b = par(flu, ["Operating Cash Flow"])

    def div(a, b):
        return a / b if np.isfinite(a) and np.isfinite(b) and b else np.nan

    dsri = div(div(ar_b, ing_b), div(ar_a, ing_a))
    gmi = div(div(ing_a - cog_a, ing_a), div(ing_b - cog_b, ing_b))
    aqi = div(1 - div(ca_b + ppe_b, ta_b), 1 - div(ca_a + ppe_a, ta_a))
    sgi = div(ing_b, ing_a)
    depi = div(div(dep_a, dep_a + ppe_a), div(dep_b, dep_b + ppe_b))
    sgai = div(div(sga_b, ing_b), div(sga_a, ing_a))
    lvgi = div(div(dlp_b + cp_b, ta_b), div(dlp_a + cp_a, ta_a))
    tata = div(ni_b - ocf_b, ta_b)

    componentes = [
        ("DSRI  Dias de venta en cuentas por cobrar", dsri, 0.920),
        ("GMI   Deterioro del margen bruto", gmi, 0.528),
        ("AQI   Calidad del activo", aqi, 0.404),
        ("SGI   Crecimiento de ventas", sgi, 0.892),
        ("DEPI  Ritmo de amortizacion", depi, 0.115),
        ("SGAI  Gastos generales sobre ventas", sgai, -0.172),
        ("LVGI  Apalancamiento", lvgi, -0.327),
        ("TATA  Devengos totales sobre activos", tata, 4.679),
    ]
    validos = [(n, v, p) for n, v, p in componentes if np.isfinite(v)]
    if len(validos) < 6:
        return None
    m = -4.84 + sum(v * p for _, v, p in validos)
    tabla = pd.DataFrame([{"Componente": n, "Valor": v, "Peso": p, "Aportacion": v * p}
                          for n, v, p in componentes])
    umbral = m > -1.78
    return {"m": m, "supera_umbral": umbral, "tabla": tabla,
             "componentes_validos": len(validos), "componentes_totales": len(componentes)}


# =============================================================================
#  M15 - RETORNOS SOBRE EL CAPITAL
# =============================================================================

def retornos_capital(estados, es_financiera=False):
    """ROIC, ROIC incremental, DuPont y tasa de reinversion.

    PROHIBICION ACTIVA en entidades financieras: el capital invertido se define
    como deuda mas patrimonio menos caja, y en un banco o un broker la deuda es
    materia prima del negocio y la caja es enorme, asi que el denominador queda
    reducido a un resto sin sentido economico. En Interactive Brokers el ROIC
    resultante era del 1.959%.
    """
    if es_financiera:
        return {"bloqueado": True,
                "motivo": "El ROIC no es aplicable a entidades financieras: su "
                          "capital invertido no se puede definir como deuda mas "
                          "patrimonio menos caja, porque la deuda y la caja "
                          "forman parte del negocio. La referencia adecuada es "
                          "el ROTE sobre patrimonio tangible."}
    res, bal = estados["resultados"], estados["balance"]
    ebit = _serie(res, ["EBIT", "Operating Income"])
    impuesto = _serie(res, ["Tax Provision"])
    antes = _serie(res, ["Pretax Income"])
    deuda = _serie(bal, ["Total Debt"])
    patrimonio = _serie(bal, ["Stockholders Equity"])
    caja = _serie(bal, ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"])
    activos = _serie(bal, ["Total Assets"])
    ingresos = _serie(res, ["Total Revenue", "Operating Revenue"])
    neto = _serie(res, ["Net Income", "Net Income Common Stockholders"])

    if ebit is None or patrimonio is None:
        return None

    filas = []
    for anio in ebit.index:                # se recorre por AÑO, no por posicion
        e, tx, pt = _v(ebit, anio), _v(impuesto, anio), _v(antes, anio)
        tasa = (tx / pt) if np.isfinite(tx) and np.isfinite(pt) and pt else 0.21
        tasa = min(max(tasa, 0.0), 0.60)
        nopat = e * (1 - tasa) if np.isfinite(e) else np.nan
        capital = np.nansum([_v(deuda, anio), _v(patrimonio, anio), -_v(caja, anio)])
        ing, act, pat = _v(ingresos, anio), _v(activos, anio), _v(patrimonio, anio)
        filas.append({
            "Ejercicio": int(anio),
            "NOPAT": nopat,
            "Capital invertido": capital if capital else np.nan,
            "ROIC": (nopat / capital) if np.isfinite(nopat) and capital else np.nan,
            "Margen neto": (_v(neto, anio) / ing) if np.isfinite(ing) and ing else np.nan,
            "Rotacion de activos": (ing / act) if np.isfinite(act) and act else np.nan,
            "Apalancamiento": (act / pat) if np.isfinite(pat) and pat else np.nan,
            "ROE": (_v(neto, anio) / pat) if np.isfinite(pat) and pat else np.nan,
            "Tasa fiscal usada": tasa,
        })
    tabla = pd.DataFrame(filas)

    # ROIC incremental: retorno del capital NUEVO invertido entre el primer y el
    # ultimo ejercicio CON DATOS. Es mas informativo que el ROIC medio porque
    # dice si el capital nuevo rinde mas o menos que el que ya estaba dentro.
    roic_incremental = np.nan
    periodo_incremental = None
    nota_incremental = None
    validas = tabla.dropna(subset=["NOPAT", "Capital invertido"])
    if len(validas) >= 2:
        d_nopat = validas["NOPAT"].iloc[-1] - validas["NOPAT"].iloc[0]
        d_capital = validas["Capital invertido"].iloc[-1] - validas["Capital invertido"].iloc[0]
        periodo_incremental = (int(validas["Ejercicio"].iloc[0]),
                               int(validas["Ejercicio"].iloc[-1]))

        if not np.isfinite(d_capital) or abs(d_capital) < 1:
            nota_incremental = "El capital invertido apenas ha variado en el periodo."
        elif d_capital < 0:
            # TRAMPA DE INTERPRETACION: con denominador negativo el cociente deja
            # de significar "retorno del capital nuevo", porque no ha entrado
            # capital nuevo: ha SALIDO. Un -50% aqui se leeria como pesimo cuando
            # describe lo contrario. Por eso no se publica el ratio.
            direccion = "aumentado" if d_nopat > 0 else "disminuido"
            nota_incremental = (
                f"El capital invertido se ha REDUCIDO en {abs(d_capital):,.0f} "
                f"durante el periodo (habitualmente por recompras o amortizacion "
                f"de deuda), mientras el NOPAT ha {direccion} en "
                f"{abs(d_nopat):,.0f}. Con capital nuevo negativo el cociente no "
                f"mide el retorno de la inversion nueva y no se publica para "
                f"evitar una lectura equivocada.")
        else:
            roic_incremental = d_nopat / d_capital

    return {"tabla": tabla,
            "roic_actual": validas["ROIC"].iloc[-1] if len(validas) else np.nan,
            "roic_medio": tabla["ROIC"].mean(),
            "roic_incremental": roic_incremental,
            "periodo_incremental": periodo_incremental,
            "nota_incremental": nota_incremental}


# =============================================================================
#  M16 - BALANCE, SOLVENCIA Y LIQUIDEZ
# =============================================================================

def solvencia(estados):
    res, bal, flu = estados["resultados"], estados["balance"], estados["flujo"]
    deuda = _fila(bal, ["Total Debt"])
    caja = _fila(bal, ["Cash And Cash Equivalents",
                       "Cash Cash Equivalents And Short Term Investments"])
    ebitda = _fila(res, ["EBITDA", "Normalized EBITDA"])
    ebit = _fila(res, ["EBIT", "Operating Income"])
    intereses = _fila(res, ["Interest Expense"])
    circ_act = _fila(bal, ["Current Assets", "Total Current Assets"])
    circ_pas = _fila(bal, ["Current Liabilities", "Total Current Liabilities"])
    inventario = _fila(bal, ["Inventory"])
    ocf = _fila(flu, ["Operating Cash Flow"])
    fcf = _fila(flu, ["Free Cash Flow"])
    patrimonio = _fila(bal, ["Stockholders Equity"])
    fondo = _fila(bal, ["Goodwill"])
    intangibles = _fila(bal, ["Goodwill And Other Intangible Assets"])

    deuda_neta = (deuda - caja) if np.isfinite(deuda) and np.isfinite(caja) else np.nan
    metricas = [
        ("Deuda total", deuda, "{:,.0f}"),
        ("Caja y equivalentes", caja, "{:,.0f}"),
        ("Deuda neta", deuda_neta, "{:,.0f}"),
        ("Deuda neta / EBITDA", (deuda_neta / ebitda) if np.isfinite(ebitda) and ebitda else np.nan, "{:.2f}x"),
        ("Cobertura de intereses (EBIT)",
         (ebit / abs(intereses)) if np.isfinite(intereses) and intereses else np.nan, "{:.1f}x"),
        ("Liquidez corriente", (circ_act / circ_pas) if np.isfinite(circ_pas) and circ_pas else np.nan, "{:.2f}"),
        ("Prueba acida",
         ((circ_act - inventario) / circ_pas) if np.isfinite(circ_pas) and circ_pas and np.isfinite(inventario) else np.nan,
         "{:.2f}"),
        ("Flujo de caja libre", fcf, "{:,.0f}"),
        ("Flujo operativo / deuda", (ocf / deuda) if np.isfinite(deuda) and deuda else np.nan, "{:.2f}"),
        ("Fondo de comercio / patrimonio",
         ((intangibles if np.isfinite(intangibles) else fondo) / patrimonio)
         if np.isfinite(patrimonio) and patrimonio else np.nan, "{:.1%}"),
    ]
    tabla = pd.DataFrame([{"Metrica": n, "Valor": v, "formato": f} for n, v, f in metricas])

    autonomia = np.nan
    if np.isfinite(fcf) and fcf < 0 and np.isfinite(caja):
        autonomia = caja / abs(fcf) * 4      # trimestres al ritmo actual
    return {"tabla": tabla, "deuda_neta": deuda_neta, "autonomia_trimestres": autonomia,
            "fcf": fcf, "caja": caja}


# =============================================================================
#  M17 - FLUJO DE CAJA Y ASIGNACION DE CAPITAL
# =============================================================================

def asignacion_capital(estados, precio_actual):
    res, flu = estados["resultados"], estados["flujo"]
    capex = _serie(flu, ["Capital Expenditure"])
    recompras = _serie(flu, ["Repurchase Of Capital Stock"])
    dividendos = _serie(flu, ["Cash Dividends Paid", "Common Stock Dividend Paid"])
    emision = _serie(flu, ["Issuance Of Capital Stock"])
    adquisiciones = _serie(flu, ["Net Business Purchase And Sale"])
    sbc = _serie(flu, ["Stock Based Compensation"])
    acciones = _serie(res, ["Diluted Average Shares", "Basic Average Shares"])
    ocf = _serie(flu, ["Operating Cash Flow"])

    if capex is None and recompras is None:
        return None

    filas = []
    indice = (capex if capex is not None else recompras).index
    for anio in indice:                    # se recorre por AÑO, no por posicion
        def v(s):
            x = _v(s, anio)
            return abs(x) if np.isfinite(x) else np.nan
        filas.append({
            "Ejercicio": int(anio),
            "Flujo operativo": v(ocf),
            "Capex": v(capex),
            "Adquisiciones": v(adquisiciones),
            "Recompras": v(recompras),
            "Dividendos": v(dividendos),
            "Retribucion en acciones": v(sbc),
            "Acciones medias": v(acciones),
        })
    tabla = pd.DataFrame(filas)

    # Dilucion neta: emite mas de lo que recompra?
    dilucion = np.nan
    if acciones is not None and len(acciones) >= 2:
        a, b = float(acciones.iloc[0]), float(acciones.iloc[-1])
        dilucion = (b / a - 1) if a else np.nan

    # Precio medio pagado en recompras frente a la cotizacion actual
    total_recompras = tabla["Recompras"].sum(skipna=True)
    return {"tabla": tabla, "dilucion_acumulada": dilucion,
            "total_recompras": total_recompras,
            "precio_actual": precio_actual}


# =============================================================================
#  M13 / M14 - CRECIMIENTO Y MARGENES
# =============================================================================

def _anio_de(valor):
    """Ejercicio a partir de una etiqueta que puede ser anio o fecha.

    Las series de `_serie()` estan indexadas por ANIO -entero- desde que se
    corrigio el desajuste entre estados de distinta longitud. Pasar ese entero
    por `pd.to_datetime` lo interpreta como nanosegundos desde 1970 y devuelve
    1970 para todos los ejercicios, que es lo que salia impreso en la tabla de
    crecimiento y margenes.
    """
    try:
        numero = int(valor)
        if 1900 <= numero <= 2100:
            return numero
    except (TypeError, ValueError):
        pass
    try:
        return int(pd.to_datetime(valor).year)
    except Exception:
        return None


def crecimiento_margenes(estados):
    res = estados["resultados"]
    ingresos = _serie(res, ["Total Revenue", "Operating Revenue"])
    bruto = _serie(res, ["Gross Profit"])
    operativo = _serie(res, ["Operating Income", "EBIT"])
    neto = _serie(res, ["Net Income", "Net Income Common Stockholders"])
    if ingresos is None or len(ingresos) < 2:
        return None

    filas = []
    for i, fecha in enumerate(ingresos.index):
        def v(s):
            try:
                return float(s.iloc[i]) if s is not None and i < len(s) else np.nan
            except Exception:
                return np.nan
        ing = v(ingresos)
        filas.append({
            "Ejercicio": _anio_de(fecha),
            "Ingresos": ing,
            "Crecimiento": (ing / float(ingresos.iloc[i - 1]) - 1) if i > 0 and float(ingresos.iloc[i - 1]) else np.nan,
            "Margen bruto": (v(bruto) / ing) if ing else np.nan,
            "Margen operativo": (v(operativo) / ing) if ing else np.nan,
            "Margen neto": (v(neto) / ing) if ing else np.nan,
        })
    tabla = pd.DataFrame(filas)

    # Margen incremental: cuanto resultado operativo aporta cada euro nuevo de ingresos
    incremental = []
    for i in range(1, len(ingresos)):
        d_ing = float(ingresos.iloc[i]) - float(ingresos.iloc[i - 1])
        d_op = (float(operativo.iloc[i]) - float(operativo.iloc[i - 1])
                if operativo is not None and i < len(operativo) else np.nan)
        incremental.append({
            "Ejercicio": _anio_de(ingresos.index[i]),
            "Variacion de ingresos": d_ing,
            "Variacion de resultado operativo": d_op,
            "Margen incremental": (d_op / d_ing) if d_ing else np.nan,
        })
    return {"tabla": tabla, "incremental": pd.DataFrame(incremental)}


# =============================================================================
#  M3 - CONSENSO Y REVISIONES
# =============================================================================

def consenso(simbolo):
    """Estimaciones con dispersion y amplitud de revision.

    Limitacion documentada: Yahoo no publica la fecha de actualizacion de cada
    estimacion individual ni la guia de la compania, asi que NO es posible
    verificar la vigencia del consenso como exige M3. Se advierte en la interfaz.
    """
    t = yf.Ticker(simbolo)
    salida = {}
    for clave, atributo in [("estimaciones", "earnings_estimate"),
                            ("ingresos", "revenue_estimate"),
                            ("tendencia_bpa", "eps_trend"),
                            ("revisiones", "eps_revisions"),
                            ("crecimiento", "growth_estimates")]:
        try:
            v = getattr(t, atributo)
            salida[clave] = v if v is not None and not v.empty else None
        except Exception:
            salida[clave] = None
    try:
        salida["objetivos"] = t.analyst_price_targets
    except Exception:
        salida["objetivos"] = None

    # Amplitud de revision: proporcion de analistas que revisan al alza
    amplitud = np.nan
    rev = salida.get("revisiones")
    if rev is not None and "upLast30days" in rev.columns and "downLast30days" in rev.columns:
        try:
            sube = float(rev["upLast30days"].sum())
            baja = float(rev["downLast30days"].sum())
            if sube + baja > 0:
                amplitud = sube / (sube + baja)
        except Exception:
            pass
    salida["amplitud_revision"] = amplitud
    return salida if any(v is not None for v in salida.values()) else None


# =============================================================================
#  M5 - INSIDERS
# =============================================================================

def insiders(simbolo):
    t = yf.Ticker(simbolo)
    salida = {}
    try:
        compras = t.insider_purchases
        salida["resumen"] = compras if compras is not None and not compras.empty else None
    except Exception:
        salida["resumen"] = None
    try:
        tx = t.insider_transactions
        salida["transacciones"] = tx if tx is not None and not tx.empty else None
    except Exception:
        salida["transacciones"] = None
    try:
        inst = t.institutional_holders
        salida["institucionales"] = inst if inst is not None and not inst.empty else None
    except Exception:
        salida["institucionales"] = None
    return salida if any(v is not None for v in salida.values()) else None


# =============================================================================
#  M20 - MULTIPLOS
# =============================================================================

def multiplos(simbolo, estados, precio, acciones):
    """Multiplos con el valor de empresa construido explicitamente."""
    res, bal = estados["resultados"], estados["balance"]
    capitalizacion = precio * acciones if np.isfinite(acciones) else np.nan
    deuda = _fila(bal, ["Total Debt"])
    caja = _fila(bal, ["Cash And Cash Equivalents",
                       "Cash Cash Equivalents And Short Term Investments"])
    minoritarios = _fila(bal, ["Minority Interest"])
    ev = capitalizacion
    for x, signo in ((deuda, 1), (caja, -1), (minoritarios, 1)):
        if np.isfinite(x):
            ev = ev + signo * x

    ingresos = _fila(res, ["Total Revenue", "Operating Revenue"])
    ebitda = _fila(res, ["EBITDA", "Normalized EBITDA"])
    ebit = _fila(res, ["EBIT", "Operating Income"])
    neto = _fila(res, ["Net Income", "Net Income Common Stockholders"])
    patrimonio = _fila(bal, ["Stockholders Equity"])
    fcf = _fila(estados["flujo"], ["Free Cash Flow"])

    def ratio(num, den):
        return (num / den) if np.isfinite(num) and np.isfinite(den) and den else np.nan

    filas = [
        ("Capitalizacion", capitalizacion, "{:,.0f}"),
        ("Valor de empresa (EV)", ev, "{:,.0f}"),
        ("PER", ratio(capitalizacion, neto), "{:.1f}x"),
        ("EV / Ventas", ratio(ev, ingresos), "{:.2f}x"),
        ("EV / EBITDA", ratio(ev, ebitda), "{:.1f}x"),
        ("EV / EBIT", ratio(ev, ebit), "{:.1f}x"),
        ("EV / FCF", ratio(ev, fcf), "{:.1f}x"),
        ("Precio / Valor contable", ratio(capitalizacion, patrimonio), "{:.2f}x"),
        ("Rentabilidad del FCF", ratio(fcf, capitalizacion), "{:.2%}"),
    ]
    return {"tabla": pd.DataFrame([{"Multiplo": n, "Valor": v, "formato": f}
                                   for n, v, f in filas]),
            "capitalizacion": capitalizacion, "ev": ev,
            "deuda": deuda, "caja": caja}


# =============================================================================
#  M19 - DCF INVERSO
# =============================================================================

def dcf_inverso(capitalizacion, fcf_actual, wacc=0.09, g_terminal=0.025,
                anios=10, deuda_neta=0.0):
    """Que crecimiento del flujo de caja hay que creer para justificar el precio.

    En lugar de preguntar cuanto vale, resuelve el crecimiento implicito: el
    unico numero falsable que se puede contrastar con la historia de la empresa.
    """
    if not np.isfinite(capitalizacion) or not np.isfinite(fcf_actual) or fcf_actual <= 0:
        return None
    objetivo = capitalizacion + (deuda_neta if np.isfinite(deuda_neta) else 0.0)

    def valor(g):
        vp = 0.0
        f = fcf_actual
        for t in range(1, anios + 1):
            f = f * (1 + g)
            vp += f / (1 + wacc) ** t
        terminal = f * (1 + g_terminal) / (wacc - g_terminal)
        vp += terminal / (1 + wacc) ** anios
        return vp

    lo, hi = -0.50, 1.50
    if valor(lo) > objetivo:
        return {"crecimiento_implicito": lo, "fuera_de_rango": "por debajo",
                "wacc": wacc, "g_terminal": g_terminal, "anios": anios,
                "peso_terminal": np.nan}
    if valor(hi) < objetivo:
        return {"crecimiento_implicito": hi, "fuera_de_rango": "por encima",
                "wacc": wacc, "g_terminal": g_terminal, "anios": anios,
                "peso_terminal": np.nan}

    for _ in range(200):
        medio = (lo + hi) / 2
        if valor(medio) < objetivo:
            lo = medio
        else:
            hi = medio
    g = (lo + hi) / 2

    # Peso del valor terminal: si supera el 75%, el DCF dice poco
    f = fcf_actual
    vp_explicito = 0.0
    for t in range(1, anios + 1):
        f = f * (1 + g)
        vp_explicito += f / (1 + wacc) ** t
    vp_terminal = (f * (1 + g_terminal) / (wacc - g_terminal)) / (1 + wacc) ** anios
    total = vp_explicito + vp_terminal

    return {"crecimiento_implicito": g, "fuera_de_rango": None,
            "wacc": wacc, "g_terminal": g_terminal, "anios": anios,
            "peso_terminal": (vp_terminal / total) if total else np.nan,
            "valor_calculado": total, "objetivo": objetivo}


# =============================================================================
#  CLASIFICACION DEL NEGOCIO (enrutamiento obligatorio del documento)
# =============================================================================

SECTORES_FINANCIEROS = {"Financial Services", "Financial", "Banks", "Insurance"}
SECTORES_INMOBILIARIOS = {"Real Estate"}
SECTORES_CICLICOS = {"Technology", "Basic Materials", "Industrials",
                     "Consumer Cyclical", "Energy"}


def clasificar_negocio(simbolo):
    """Determina el tipo de negocio y que metodos quedan PROHIBIDOS.

    El documento exige bloquear metodos inaplicables: EV/EBITDA en un banco o
    PER contable en un REIT invalidan todo lo que venga despues.
    """
    try:
        info = yf.Ticker(simbolo).info or {}
    except Exception:
        info = {}
    sector = info.get("sector") or "Desconocido"
    industria = info.get("industry") or "Desconocida"

    if sector in SECTORES_FINANCIEROS:
        tipo = "Entidad financiera"
        motor = "P/TBV frente a ROTE + descuento de dividendos (M23)"
        prohibidos = ["EV/EBITDA", "EV/EBIT", "EV/Ventas", "EV/FCF",
                      "Valor de empresa (EV)", "Deuda neta"]
        aviso = ("El apalancamiento es el negocio, no un riesgo accesorio. "
                 "Los multiplos de valor de empresa carecen de sentido aqui y "
                 "el sistema los bloquea.")
    elif sector in SECTORES_INMOBILIARIOS:
        tipo = "Inmobiliaria o REIT"
        motor = "NAV + multiplo de FFO (M24)"
        prohibidos = ["PER", "EV/EBITDA"]
        aviso = ("La amortizacion de inmuebles no refleja deterioro economico "
                 "real, asi que el PER contable induce a error.")
    elif sector in SECTORES_CICLICOS:
        tipo = "Ciclica"
        motor = "Beneficio normalizado de ciclo (M22)"
        prohibidos = []
        aviso = ("Negocio ciclico: el PER sobre beneficio de pico es el error "
                 "mas caro que existe. Conviene mirar el beneficio medio de ciclo, "
                 "no el del ultimo ejercicio.")
    else:
        tipo = "Industrial o consumo estable"
        motor = "DCF + multiplos + ROIC"
        prohibidos = []
        aviso = ""

    return {"sector": sector, "industria": industria, "tipo": tipo,
            "motor": motor, "prohibidos": prohibidos, "aviso": aviso,
            "es_financiera": sector in SECTORES_FINANCIEROS}


# =============================================================================
#  COBERTURA DE MODULOS (M51 - panel de estado)
# =============================================================================

COBERTURA = [
    ("M1", "Datos fundamentales primarios", "Parcial",
     "XBRL de SEC EDGAR con fecha de presentacion e historia desde 2015, mas "
     "estados de Yahoo. NO: cifras reexpresadas separadas, registros no "
     "estadounidenses, datos por segmento, notas ni reconciliacion GAAP/no-GAAP."),
    ("M2", "Mercado y microestructura", "No",
     "Requiere datos tick, cadena de opciones historica, interes corto y dark "
     "pools: solo disponibles en proveedores de pago."),
    ("M3", "Estimaciones y consenso", "Parcial",
     "Consenso con maximo, minimo y numero de analistas, y amplitud de revision "
     "a 7 y 30 dias. NO: fecha de actualizacion de cada estimacion, historial "
     "por analista ni estimaciones whisper."),
    ("M4", "Guidance corporativo", "No",
     "Yahoo no publica la guia de la compania. Es la limitacion mas importante: "
     "sin ella no se puede verificar si el consenso esta vigente."),
    ("M5", "Propiedad e insiders", "Parcial",
     "Compras y ventas netas de insiders a 6 meses e institucionales. NO: "
     "Formularios 4 individuales ni distincion de planes 10b5-1."),
    ("M6", "Datos alternativos", "No", "Requiere proveedores especializados."),
    ("M7", "Texto: filings y transcripciones", "No",
     "El texto esta en EDGAR, pero extraerlo y compararlo entre versiones es un "
     "proyecto en si mismo."),
    ("M8", "Macro y datos sectoriales", "No",
     "Requiere fuentes sectoriales especificas (book-to-bill, precios de memoria)."),
    ("M9", "Control de calidad y reconciliacion", "Si",
     "Cotejo del numero de acciones contra el ultimo balance presentado en la "
     "SEC, cuadre del balance, recalculo del flujo de caja libre y marca de "
     "antiguedad de los datos."),
    ("M10", "Normalizacion de estados", "Parcial",
     "Retribucion en acciones visible y tasa fiscal efectiva. NO: capitalizacion "
     "de I+D, arrendamientos ni ajustes pro forma."),
    ("M11", "Calidad del beneficio", "Si",
     "Devengos de Sloan, conversion en caja, ciclo de conversion de efectivo y "
     "divergencia entre ingresos y circulante."),
    ("M12", "Contabilidad agresiva", "Si",
     "Piotroski F-Score, Altman Z-Score y Beneish M-Score con sus componentes "
     "visibles uno a uno."),
    ("M13", "Descomposicion del crecimiento", "Parcial",
     "Crecimiento total y margenes. NO: organico frente a inorganico, precio "
     "frente a volumen ni desglose por segmento (requiere datos de segmento)."),
    ("M14", "Puente de margenes", "Parcial",
     "Margen incremental y evolucion de margenes. NO: cascada de mezcla, precio "
     "y coste de insumos."),
    ("M15", "Retornos sobre el capital", "Si",
     "ROIC, ROIC incremental, DuPont y rotacion de activos."),
    ("M16", "Balance, solvencia y liquidez", "Parcial",
     "Deuda neta, coberturas, liquidez y autonomia. NO: covenants ni escalera "
     "de vencimientos (estan en las notas)."),
    ("M17", "Flujo de caja y asignacion de capital", "Parcial",
     "Historial de capex, recompras, dividendos y dilucion neta. NO: separacion "
     "de capex de mantenimiento y de crecimiento."),
    ("M18", "DCF", "Parcial", "Implementado en su forma inversa (M19)."),
    ("M19", "DCF inverso", "Si",
     "Resuelve el crecimiento implicito en el precio y el peso del valor terminal."),
    ("M20", "Valoracion relativa", "Parcial",
     "Multiplos con valor de empresa construido explicitamente. NO: percentil "
     "historico del multiplo ni mediana sectorial."),
    ("M21", "Regresion de multiplos", "No", "Requiere un universo de comparables limpio."),
    ("M22", "Ciclicas", "Parcial",
     "Se detecta el negocio ciclico y se advierte. NO: beneficio normalizado de "
     "ciclo con datos de utilizacion de capacidad."),
    ("M23", "Entidades financieras", "Parcial",
     "Se BLOQUEAN los multiplos de valor de empresa en bancos y aseguradoras, "
     "como exige el documento. NO: ROTE, CET1 ni coste del riesgo."),
    ("M24", "REITs", "Parcial",
     "Se advierte de que el PER contable no aplica. NO: FFO, AFFO ni NAV."),
    ("M25", "Biotecnologia y software", "No", "Requiere datos de pipeline y de cohortes."),
    ("M26", "Rango de valor razonable", "No",
     "Depende de metodos no implementados; no se emite valoracion agregada."),
    ("M27", "Descomposicion del beat/miss", "Parcial",
     "Sorpresa contra consenso, ya presente en la pestana Earnings. NO: contra "
     "guia (M4) ni descomposicion por linea."),
    ("M28", "Analisis de guidance", "No", "Depende de M4."),
    ("M29", "Conferencia de resultados", "No", "Requiere transcripciones."),
    ("M30", "Cascada de revisiones", "Parcial",
     "Amplitud de revision a 7 y 30 dias. NO: proyeccion de revision futura."),
    ("M31", "Cuadro de mando del trimestre", "No",
     "Requiere M27 y M28 completos para ser fiable."),
    ("M32", "Movimiento implicito frente a real", "Parcial",
     "Movimiento real en sigmas y percentil historico, en la pestana Earnings. "
     "NO: movimiento implicito por opciones."),
    ("M33", "Descomposicion de la reaccion", "No", "Requiere modelo factorial."),
    ("M34", "Calidad del movimiento", "Parcial",
     "Volumen relativo del dia, en la pestana Volumen. NO: hora exacta de la "
     "operacion ni sesiones fuera de horario."),
    ("M35", "Dislocacion fundamental", "No",
     "Requiere valor razonable fiable, que depende de M4 y M26."),
    ("M36", "Flujos y mecanica de mercado", "No",
     "Requiere interes corto, gamma y datos de flujo."),
    ("M37", "Base rates empiricas", "Parcial",
     "Recuento sobre el historico del propio valor con numero de observaciones "
     "visible, en la pestana Movimientos extremos. NO: base multi-empresa con "
     "datos de punto en el tiempo ni correccion de sesgo de supervivencia."),
    ("M38-M42", "Sector y comparables", "No", "Requiere un universo de comparables."),
    ("M43-M45", "Motor de riesgos", "Parcial",
     "Riesgo financiero desde el balance y riesgo contable desde M12. NO: "
     "concentracion de clientes ni litigios (estan en el texto de los filings)."),
    ("M46-M50", "Capa de decision", "No",
     "Excluida DELIBERADAMENTE. Estos modulos emiten veredictos de compra y "
     "venta y dimensionan posiciones, lo que entra en conflicto directo con el "
     "requisito de neutralidad de esta herramienta."),
    ("M51", "Reconciliacion automatica", "Parcial",
     "Validaciones de integridad y panel de estado de datos. NO: cotejo entre "
     "varios proveedores ni pruebas de regresion historicas."),
    ("M52-M54", "Sesgos, calibracion y auditoria", "No",
     "Solo tienen sentido sobre un historial de predicciones registradas, que "
     "esta herramienta no emite."),
]


def tabla_cobertura():
    return pd.DataFrame(
        [{"Modulo": m, "Nombre": n, "Cobertura": c, "Detalle": d}
         for m, n, c, d in COBERTURA])


# =============================================================================
#  PREPARACION DE DATOS PARA EL ANALISIS VISUAL
#
#  Solo transforman a formato de grafico cifras ya leidas de los estados o ya
#  calculadas mas arriba. No introducen ninguna metrica nueva ni ningun supuesto.
# =============================================================================

def composicion_balance(estados):
    """Estructura del balance por ejercicio, en formato largo para barras apiladas.

    Cada lado (activo y pasivo mas patrimonio) incluye una partida "Otros"
    calculada por diferencia, de forma que las barras SIEMPRE suman el total
    declarado. Sin ese residuo el grafico mostraria un balance incompleto sin
    avisar de que faltan partidas.
    """
    bal = estados.get("balance")
    if bal is None or bal.empty:
        return None

    total_activo = _serie(bal, ["Total Assets"])
    if total_activo is None:
        return None
    total_pasivo = _serie(bal, ["Total Liabilities Net Minority Interest",
                                "Total Liabilities"])
    patrimonio = _serie(bal, ["Stockholders Equity"])
    minoritarios = _serie(bal, ["Minority Interest"])

    partidas_activo = [
        ("Caja e inversiones", ["Cash Cash Equivalents And Short Term Investments",
                                "Cash And Cash Equivalents"]),
        ("Cuentas por cobrar", ["Accounts Receivable", "Receivables"]),
        ("Inventario", ["Inventory"]),
        ("Inmovilizado material", ["Net PPE"]),
        ("Fondo de comercio e intangibles", ["Goodwill And Other Intangible Assets",
                                             "Goodwill"]),
    ]
    partidas_pasivo = [
        ("Deuda a corto plazo", ["Current Debt And Capital Lease Obligation",
                                 "Current Debt"]),
        ("Deuda a largo plazo", ["Long Term Debt And Capital Lease Obligation",
                                 "Long Term Debt"]),
        ("Proveedores", ["Accounts Payable", "Payables"]),
    ]

    filas = []
    for anio in total_activo.index:
        ta = _v(total_activo, anio)
        if not np.isfinite(ta) or ta <= 0:
            continue

        suma = 0.0
        for etiqueta, nombres in partidas_activo:
            v = _v(_serie(bal, nombres), anio)
            if np.isfinite(v) and v > 0:
                filas.append({"Ejercicio": int(anio), "Lado": "Activo",
                              "Partida": etiqueta, "Importe": v})
                suma += v
        resto = ta - suma
        if resto > 0:
            filas.append({"Ejercicio": int(anio), "Lado": "Activo",
                          "Partida": "Otros activos", "Importe": resto})

        suma_p = 0.0
        for etiqueta, nombres in partidas_pasivo:
            v = _v(_serie(bal, nombres), anio)
            if np.isfinite(v) and v > 0:
                filas.append({"Ejercicio": int(anio), "Lado": "Pasivo y patrimonio",
                              "Partida": etiqueta, "Importe": v})
                suma_p += v
        tp = _v(total_pasivo, anio)
        if np.isfinite(tp):
            otros_pasivos = tp - suma_p
            if otros_pasivos > 0:
                filas.append({"Ejercicio": int(anio), "Lado": "Pasivo y patrimonio",
                              "Partida": "Otros pasivos", "Importe": otros_pasivos})
                suma_p += otros_pasivos
        pn = _v(patrimonio, anio)
        if np.isfinite(pn) and pn > 0:
            filas.append({"Ejercicio": int(anio), "Lado": "Pasivo y patrimonio",
                          "Partida": "Patrimonio neto", "Importe": pn})
            suma_p += pn
        mi = _v(minoritarios, anio)
        if np.isfinite(mi) and mi > 0:
            filas.append({"Ejercicio": int(anio), "Lado": "Pasivo y patrimonio",
                          "Partida": "Minoritarios", "Importe": mi})
            suma_p += mi
        # Cuadre final del lado derecho contra el activo declarado
        hueco = ta - suma_p
        if hueco > ta * 0.001:
            filas.append({"Ejercicio": int(anio), "Lado": "Pasivo y patrimonio",
                          "Partida": "Otros pasivos", "Importe": hueco})

    if not filas:
        return None
    return pd.DataFrame(filas)


ORDEN_BALANCE = ["Caja e inversiones", "Cuentas por cobrar", "Inventario",
                 "Inmovilizado material", "Fondo de comercio e intangibles",
                 "Otros activos", "Deuda a corto plazo", "Deuda a largo plazo",
                 "Proveedores", "Otros pasivos", "Minoritarios", "Patrimonio neto"]


def _cascada(pasos):
    """Convierte una lista de (etiqueta, importe, es_total) en barras de cascada."""
    filas, acumulado = [], 0.0
    for etiqueta, importe, es_total in pasos:
        if not np.isfinite(importe):
            continue
        if es_total:
            filas.append({"Concepto": etiqueta, "Inicio": min(0.0, importe),
                          "Fin": max(0.0, importe), "Importe": importe,
                          "Tipo": "Subtotal"})
            acumulado = importe
        else:
            inicio, fin = acumulado, acumulado + importe
            filas.append({"Concepto": etiqueta, "Inicio": min(inicio, fin),
                          "Fin": max(inicio, fin), "Importe": importe,
                          "Tipo": "Suma" if importe >= 0 else "Resta"})
            acumulado = fin
    return pd.DataFrame(filas) if filas else None


def cascada_resultados(estados, anio=None):
    """De ingresos a beneficio neto, paso a paso."""
    res = estados.get("resultados")
    if res is None or res.empty:
        return None
    ingresos = _serie(res, ["Total Revenue", "Operating Revenue"])
    if ingresos is None or ingresos.empty:
        return None
    anio = int(anio) if anio is not None else int(ingresos.index[-1])

    def v(nombres, signo=1):
        return signo * _v(_serie(res, nombres), anio)

    ing = v(["Total Revenue", "Operating Revenue"])
    coste = v(["Cost Of Revenue", "Reconciled Cost Of Revenue"], -1)
    bruto = v(["Gross Profit"])
    opex = v(["Operating Expense"], -1)
    operativo = v(["Operating Income", "EBIT"])
    financiero = v(["Net Non Operating Interest Income Expense"])
    otros = v(["Other Income Expense"])
    impuesto = v(["Tax Provision"], -1)
    neto = v(["Net Income", "Net Income Common Stockholders"])

    if not np.isfinite(ing):
        return None

    pasos = [("Ingresos", ing, True)]
    if np.isfinite(coste):
        pasos.append(("Coste de ventas", coste, False))
    if np.isfinite(bruto):
        pasos.append(("Margen bruto", bruto, True))
    if np.isfinite(opex):
        pasos.append(("Gastos operativos", opex, False))
    if np.isfinite(operativo):
        pasos.append(("Resultado operativo", operativo, True))
    for etiqueta, valor in [("Resultado financiero", financiero),
                            ("Otros resultados", otros)]:
        if np.isfinite(valor) and abs(valor) > 0:
            pasos.append((etiqueta, valor, False))
    if np.isfinite(impuesto):
        pasos.append(("Impuestos", impuesto, False))
    if np.isfinite(neto):
        pasos.append(("Beneficio neto", neto, True))
    tabla = _cascada(pasos)
    return (tabla, anio) if tabla is not None else None


def puente_flujo_caja(estados, anio=None):
    """Del flujo operativo al efectivo que queda tras invertir y retribuir."""
    flu = estados.get("flujo")
    if flu is None or flu.empty:
        return None
    ocf_s = _serie(flu, ["Operating Cash Flow"])
    if ocf_s is None or ocf_s.empty:
        return None
    anio = int(anio) if anio is not None else int(ocf_s.index[-1])

    def v(nombres):
        return _v(_serie(flu, nombres), anio)

    ocf = v(["Operating Cash Flow"])
    capex = v(["Capital Expenditure"])
    fcf = v(["Free Cash Flow"])
    dividendos = v(["Cash Dividends Paid", "Common Stock Dividend Paid"])
    recompras = v(["Repurchase Of Capital Stock"])
    adquisiciones = v(["Net Business Purchase And Sale"])

    if not np.isfinite(ocf):
        return None

    def neg(x):
        return -abs(x) if np.isfinite(x) else np.nan

    pasos = [("Flujo operativo", ocf, True)]
    if np.isfinite(capex):
        pasos.append(("Inversion (capex)", neg(capex), False))
    if np.isfinite(fcf):
        pasos.append(("Flujo de caja libre", fcf, True))
    for etiqueta, valor in [("Adquisiciones", adquisiciones),
                            ("Recompras", recompras),
                            ("Dividendos", dividendos)]:
        if np.isfinite(valor) and abs(valor) > 0:
            pasos.append((etiqueta, neg(valor), False))
    tabla = _cascada(pasos)
    return (tabla, anio) if tabla is not None else None


def beneficio_frente_a_caja(estados):
    """Beneficio neto, flujo operativo y flujo libre por ejercicio.

    La distancia entre las tres barras es la lectura visual de los devengos:
    cuanto mas se separa el beneficio del flujo, menos se convierte en caja.
    """
    res, flu = estados.get("resultados"), estados.get("flujo")
    neto = _serie(res, ["Net Income", "Net Income Common Stockholders"])
    ocf = _serie(flu, ["Operating Cash Flow"])
    fcf = _serie(flu, ["Free Cash Flow"])
    if neto is None or ocf is None:
        return None
    filas = []
    for anio in neto.index:
        for etiqueta, serie in [("Beneficio neto", neto),
                                ("Flujo operativo", ocf),
                                ("Flujo de caja libre", fcf)]:
            v = _v(serie, anio)
            if np.isfinite(v):
                filas.append({"Ejercicio": int(anio), "Magnitud": etiqueta,
                              "Importe": v})
    return pd.DataFrame(filas) if filas else None


def evolucion_apalancamiento(estados):
    """Deuda neta y su relacion con el EBITDA, ejercicio a ejercicio."""
    res, bal = estados.get("resultados"), estados.get("balance")
    deuda = _serie(bal, ["Total Debt"])
    caja = _serie(bal, ["Cash Cash Equivalents And Short Term Investments",
                        "Cash And Cash Equivalents"])
    ebitda = _serie(res, ["EBITDA", "Normalized EBITDA"])
    if deuda is None:
        return None
    filas = []
    for anio in deuda.index:
        d, c, e = _v(deuda, anio), _v(caja, anio), _v(ebitda, anio)
        if not np.isfinite(d):
            continue
        dn = d - c if np.isfinite(c) else d
        filas.append({
            "Ejercicio": int(anio),
            "Deuda total": d,
            "Caja": c if np.isfinite(c) else np.nan,
            "Deuda neta": dn,
            "Deuda neta / EBITDA": (dn / e) if np.isfinite(e) and e > 0 else np.nan,
        })
    return pd.DataFrame(filas) if filas else None


def capital_circulante(estados):
    """Cuentas por cobrar, inventario y proveedores frente a los ingresos."""
    res, bal = estados.get("resultados"), estados.get("balance")
    ingresos = _serie(res, ["Total Revenue", "Operating Revenue"])
    cobrar = _serie(bal, ["Accounts Receivable", "Receivables"])
    inventario = _serie(bal, ["Inventory"])
    pagar = _serie(bal, ["Accounts Payable", "Payables"])
    if ingresos is None:
        return None
    filas = []
    for anio in ingresos.index:
        ing = _v(ingresos, anio)
        if not np.isfinite(ing) or not ing:
            continue
        for etiqueta, serie in [("Cuentas por cobrar", cobrar),
                                ("Inventario", inventario),
                                ("Proveedores", pagar)]:
            v = _v(serie, anio)
            if np.isfinite(v):
                filas.append({"Ejercicio": int(anio), "Partida": etiqueta,
                              "Importe": v, "Sobre ingresos": v / ing})
    return pd.DataFrame(filas) if filas else None
