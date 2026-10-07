"""Traduccion y ordenacion de las PARTIDAS CONTABLES del proveedor.

El proveedor entrega los estados financieros con las etiquetas en ingles y en
un orden que no responde a ningun criterio contable: la cuenta de resultados de
un valor cualquiera puede abrir por "Tax Effect Of Unusual Items", que es de
las lineas menos relevantes que existen, y dejar la cifra de negocio a mitad de
tabla.

Este modulo hace dos cosas:

  TRADUCIR   cada etiqueta a su denominacion habitual en castellano.
  ORDENAR    las partidas segun la cascada contable, de arriba abajo:
             ingresos, coste de ventas, margen bruto, gastos de explotacion,
             resultado de explotacion, resultado financiero, impuestos y
             resultado neto. Y lo equivalente en balance y en flujos.

Lo que no figure en el diccionario se conserva TAL CUAL y se coloca al final de
su bloque. Nunca se descarta una partida por no estar traducida: es preferible
una linea en ingles a una linea que desaparece del informe sin avisar.
"""

# =============================================================================
#  TRADUCCION
# =============================================================================

TRADUCCION = {
    # --- cuenta de resultados
    "Total Revenue": "Cifra de negocio",
    "Operating Revenue": "Ingresos de explotación",
    "Cost Of Revenue": "Coste de ventas",
    "Reconciled Cost Of Revenue": "Coste de ventas conciliado",
    "Gross Profit": "Margen bruto",
    "Operating Expense": "Gastos de explotación",
    "Research And Development": "Investigación y desarrollo",
    "Selling General And Administration": "Gastos comerciales y de administración",
    "Selling And Marketing Expense": "Gastos comerciales",
    "General And Administrative Expense": "Gastos de administración",
    "Other Operating Expenses": "Otros gastos de explotación",
    "Operating Income": "Resultado de explotación",
    "Total Operating Income As Reported": "Resultado de explotación declarado",
    "EBITDA": "EBITDA",
    "Normalized EBITDA": "EBITDA normalizado",
    "EBIT": "EBIT",
    "Reconciled Depreciation": "Amortización conciliada",
    "Depreciation And Amortization In Income Statement":
        "Amortización en la cuenta de resultados",
    "Depreciation Amortization Depletion Income Statement":
        "Amortización y agotamiento",
    "Net Non Operating Interest Income Expense":
        "Resultado financiero neto",
    "Interest Income": "Ingresos financieros",
    "Interest Expense": "Gastos financieros",
    "Interest Income Non Operating": "Ingresos financieros no de explotación",
    "Interest Expense Non Operating": "Gastos financieros no de explotación",
    "Net Interest Income": "Resultado financiero",
    "Other Income Expense": "Otros ingresos y gastos",
    "Other Non Operating Income Expenses": "Otros resultados no de explotación",
    "Special Income Charges": "Ingresos y cargos extraordinarios",
    "Total Unusual Items": "Partidas extraordinarias",
    "Total Unusual Items Excluding Goodwill":
        "Partidas extraordinarias sin fondo de comercio",
    "Tax Effect Of Unusual Items": "Efecto fiscal de las partidas extraordinarias",
    "Tax Rate For Calcs": "Tipo impositivo aplicado",
    "Pretax Income": "Resultado antes de impuestos",
    "Tax Provision": "Impuesto sobre beneficios",
    "Net Income": "Resultado neto",
    "Net Income Common Stockholders": "Resultado neto atribuible",
    "Net Income From Continuing Operation Net Minority Interest":
        "Resultado de actividades continuadas",
    "Net Income From Continuing And Discontinued Operation":
        "Resultado de actividades continuadas e interrumpidas",
    "Net Income Continuous Operations": "Resultado de operaciones continuadas",
    "Net Income Including Noncontrolling Interests":
        "Resultado incluidas participaciones no dominantes",
    "Minority Interests": "Participaciones no dominantes",
    "Normalized Income": "Resultado normalizado",
    "Diluted NI Availto Com Stockholders": "Resultado diluido atribuible",
    "Basic EPS": "Beneficio por acción básico",
    "Diluted EPS": "Beneficio por acción diluido",
    "Basic Average Shares": "Acciones medias básicas",
    "Diluted Average Shares": "Acciones medias diluidas",

    # --- balance
    "Total Assets": "Activo total",
    "Current Assets": "Activo corriente",
    "Cash And Cash Equivalents": "Efectivo y equivalentes",
    "Cash Cash Equivalents And Short Term Investments":
        "Efectivo e inversiones a corto plazo",
    "Other Short Term Investments": "Otras inversiones a corto plazo",
    "Accounts Receivable": "Deudores comerciales",
    "Receivables": "Cuentas a cobrar",
    "Inventory": "Existencias",
    "Other Current Assets": "Otros activos corrientes",
    "Total Non Current Assets": "Activo no corriente",
    "Net PPE": "Inmovilizado material neto",
    "Gross PPE": "Inmovilizado material bruto",
    "Goodwill": "Fondo de comercio",
    "Goodwill And Other Intangible Assets":
        "Fondo de comercio y otros intangibles",
    "Other Intangible Assets": "Otros activos intangibles",
    "Investments And Advances": "Inversiones financieras",
    "Other Non Current Assets": "Otros activos no corrientes",
    "Total Liabilities Net Minority Interest":
        "Pasivo total sin participaciones no dominantes",
    "Current Liabilities": "Pasivo corriente",
    "Accounts Payable": "Acreedores comerciales",
    "Payables": "Cuentas a pagar",
    "Payables And Accrued Expenses": "Acreedores y gastos devengados",
    "Current Debt": "Deuda a corto plazo",
    "Current Debt And Capital Lease Obligation":
        "Deuda y arrendamientos a corto plazo",
    "Other Current Liabilities": "Otros pasivos corrientes",
    "Total Non Current Liabilities Net Minority Interest":
        "Pasivo no corriente",
    "Long Term Debt": "Deuda a largo plazo",
    "Long Term Debt And Capital Lease Obligation":
        "Deuda y arrendamientos a largo plazo",
    "Other Non Current Liabilities": "Otros pasivos no corrientes",
    "Total Debt": "Deuda total",
    "Net Debt": "Deuda neta",
    "Total Equity Gross Minority Interest":
        "Patrimonio neto con participaciones no dominantes",
    "Stockholders Equity": "Patrimonio neto",
    "Common Stock Equity": "Fondos propios",
    "Retained Earnings": "Reservas",
    "Capital Stock": "Capital social",
    "Common Stock": "Capital social ordinario",
    "Additional Paid In Capital": "Prima de emisión",
    "Treasury Stock": "Acciones propias",
    "Working Capital": "Capital circulante",
    "Invested Capital": "Capital invertido",
    "Tangible Book Value": "Valor contable tangible",
    "Total Capitalization": "Capitalización total",
    "Share Issued": "Acciones emitidas",
    "Ordinary Shares Number": "Número de acciones ordinarias",

    # --- flujos de efectivo
    "Operating Cash Flow": "Flujo de caja de explotación",
    "Cash Flow From Continuing Operating Activities":
        "Flujo de explotación de actividades continuadas",
    "Investing Cash Flow": "Flujo de caja de inversión",
    "Cash Flow From Continuing Investing Activities":
        "Flujo de inversión de actividades continuadas",
    "Financing Cash Flow": "Flujo de caja de financiación",
    "Cash Flow From Continuing Financing Activities":
        "Flujo de financiación de actividades continuadas",
    "Free Cash Flow": "Flujo de caja libre",
    "Capital Expenditure": "Inversión en inmovilizado",
    "Net PPE Purchase And Sale": "Compras y ventas de inmovilizado",
    "Purchase Of PPE": "Compra de inmovilizado",
    "Depreciation And Amortization": "Amortización",
    "Depreciation Amortization Depletion": "Amortización y agotamiento",
    "Stock Based Compensation": "Retribución en acciones",
    "Change In Working Capital": "Variación del capital circulante",
    "Changes In Cash": "Variación del efectivo",
    "Change In Cash Supplemental As Reported":
        "Variación del efectivo declarada",
    "Beginning Cash Position": "Efectivo al inicio",
    "End Cash Position": "Efectivo al cierre",
    "Repurchase Of Capital Stock": "Recompra de acciones",
    "Repayment Of Debt": "Amortización de deuda",
    "Issuance Of Debt": "Emisión de deuda",
    "Issuance Of Capital Stock": "Emisión de acciones",
    "Common Stock Dividend Paid": "Dividendos pagados",
    "Cash Dividends Paid": "Dividendos satisfechos",
    "Net Common Stock Issuance": "Emisión neta de acciones",
    "Net Issuance Payments Of Debt": "Emisión neta de deuda",
    "Deferred Tax": "Impuesto diferido",
    "Deferred Income Tax": "Impuesto sobre beneficios diferido",
    "Other Non Cash Items": "Otras partidas sin salida de caja",
}


# =============================================================================
#  ORDEN CONTABLE
# =============================================================================

ORDEN_RESULTADOS = [
    "Total Revenue", "Operating Revenue", "Cost Of Revenue",
    "Reconciled Cost Of Revenue", "Gross Profit",
    "Operating Expense", "Research And Development",
    "Selling General And Administration", "Selling And Marketing Expense",
    "General And Administrative Expense", "Other Operating Expenses",
    "Operating Income", "Total Operating Income As Reported",
    "EBITDA", "Normalized EBITDA", "EBIT",
    "Reconciled Depreciation",
    "Depreciation And Amortization In Income Statement",
    "Net Non Operating Interest Income Expense", "Net Interest Income",
    "Interest Income", "Interest Expense",
    "Interest Income Non Operating", "Interest Expense Non Operating",
    "Other Income Expense", "Other Non Operating Income Expenses",
    "Special Income Charges", "Total Unusual Items",
    "Total Unusual Items Excluding Goodwill",
    "Pretax Income", "Tax Provision", "Tax Rate For Calcs",
    "Tax Effect Of Unusual Items",
    "Net Income From Continuing Operation Net Minority Interest",
    "Net Income Continuous Operations",
    "Net Income From Continuing And Discontinued Operation",
    "Net Income Including Noncontrolling Interests", "Minority Interests",
    "Net Income", "Net Income Common Stockholders", "Normalized Income",
    "Diluted NI Availto Com Stockholders",
    "Basic EPS", "Diluted EPS", "Basic Average Shares", "Diluted Average Shares",
]

ORDEN_BALANCE = [
    "Total Assets", "Current Assets",
    "Cash Cash Equivalents And Short Term Investments",
    "Cash And Cash Equivalents", "Other Short Term Investments",
    "Accounts Receivable", "Receivables", "Inventory", "Other Current Assets",
    "Total Non Current Assets", "Net PPE", "Gross PPE", "Goodwill",
    "Goodwill And Other Intangible Assets", "Other Intangible Assets",
    "Investments And Advances", "Other Non Current Assets",
    "Total Liabilities Net Minority Interest", "Current Liabilities",
    "Accounts Payable", "Payables", "Payables And Accrued Expenses",
    "Current Debt", "Current Debt And Capital Lease Obligation",
    "Other Current Liabilities",
    "Total Non Current Liabilities Net Minority Interest",
    "Long Term Debt", "Long Term Debt And Capital Lease Obligation",
    "Other Non Current Liabilities",
    "Total Debt", "Net Debt",
    "Total Equity Gross Minority Interest", "Stockholders Equity",
    "Common Stock Equity", "Capital Stock", "Common Stock",
    "Additional Paid In Capital", "Retained Earnings", "Treasury Stock",
    "Working Capital", "Invested Capital", "Tangible Book Value",
    "Total Capitalization", "Share Issued", "Ordinary Shares Number",
]

ORDEN_FLUJO = [
    "Operating Cash Flow", "Cash Flow From Continuing Operating Activities",
    "Depreciation And Amortization", "Depreciation Amortization Depletion",
    "Stock Based Compensation", "Deferred Tax", "Deferred Income Tax",
    "Change In Working Capital", "Other Non Cash Items",
    "Investing Cash Flow", "Cash Flow From Continuing Investing Activities",
    "Capital Expenditure", "Purchase Of PPE", "Net PPE Purchase And Sale",
    "Financing Cash Flow", "Cash Flow From Continuing Financing Activities",
    "Issuance Of Debt", "Repayment Of Debt", "Net Issuance Payments Of Debt",
    "Issuance Of Capital Stock", "Repurchase Of Capital Stock",
    "Net Common Stock Issuance",
    "Common Stock Dividend Paid", "Cash Dividends Paid",
    "Free Cash Flow",
    "Changes In Cash", "Change In Cash Supplemental As Reported",
    "Beginning Cash Position", "End Cash Position",
]

ORDENES = {"resultados": ORDEN_RESULTADOS, "balance": ORDEN_BALANCE,
           "flujo": ORDEN_FLUJO}


def traducir(etiqueta):
    """Denominacion en castellano, o la original si no figura en el catalogo."""
    if etiqueta is None:
        return ""
    texto = str(etiqueta).strip()
    return TRADUCCION.get(texto, texto)


def ordenar(indice, cual):
    """Devuelve las etiquetas en orden contable.

    Las conocidas van en el orden del catalogo; las que no figuren se conservan
    detras, por orden alfabetico, para que no desaparezca ninguna linea.
    """
    orden = ORDENES.get(cual)
    if not orden:
        return list(indice)
    posicion = {nombre: i for i, nombre in enumerate(orden)}
    conocidas = [x for x in indice if str(x).strip() in posicion]
    resto = sorted(x for x in indice if str(x).strip() not in posicion)
    conocidas.sort(key=lambda x: posicion[str(x).strip()])
    return conocidas + resto


def preparar(df, cual):
    """Reordena el estado y traduce sus etiquetas, sin perder ninguna fila."""
    if df is None or getattr(df, "empty", True):
        return df
    orden = ordenar(list(df.index), cual)
    vista = df.loc[orden].copy()
    vista.index = [traducir(x) for x in vista.index]
    return vista
