"""Motor de SEGMENTOS de negocio y geografia.

Extrae de los informes de la SEC el desglose de ingresos, margenes y activos por
linea de negocio y por area geografica, que es informacion que ningun proveedor
gratuito publica de forma estructurada.

De donde salen los datos
------------------------
La API `companyfacts` solo devuelve cifras CONSOLIDADAS: los segmentos van
dimensionados en XBRL y no aparecen ahi. La via que si funciona es el propio
expediente: cada 10-K y 10-Q publica un `FilingSummary.xml` con la lista de
informes renderizados (ficheros R*.htm), y entre ellos estan las tablas de
segmentos y de geografia tal y como la empresa las declaro.

Cada informe trae ademas, al pie, los elementos XBRL que lo componen. De ahi se
lee el EJE utilizado, que es lo que permite distinguir sin ambiguedad:

    srt:StatementGeographicalAxis          -> desglose geografico
    us-gaap:StatementBusinessSegmentsAxis  -> desglose por linea de negocio

y, cuando el miembro es del tipo `country_US`, obtener el codigo ISO del pais
sin depender de como este escrito el nombre en la tabla.

Comprobacion obligatoria
------------------------
Siguiendo el criterio de M9, las partes se suman y se cotejan contra el total
consolidado del propio informe. Si no cuadran, se marca la discrepancia en vez
de presentar un desglose incompleto como si fuera completo.
"""

import io
import json
import os
import re
import urllib.request

import numpy as np
import pandas as pd

# El correo de contacto se toma del entorno, con el mismo valor por defecto que
# motor_fundamentales. La SEC responde 403 a toda peticion que no se identifique
# con una direccion real, de modo que un marcador de posicion deja el modulo
# entero sin datos.
CONTACTO_POR_DEFECTO = "financeandml@gmail.com"
CONTACTO_SEC = os.environ.get("SEC_CONTACTO", "").strip() or CONTACTO_POR_DEFECTO
CABECERA_SEC = {"User-Agent": f"Analizador de Activos - {CONTACTO_SEC}"}
TIEMPO_ESPERA = 30

EJE_GEOGRAFIA = "StatementGeographicalAxis"
EJE_NEGOCIO = "StatementBusinessSegmentsAxis"
EJE_PRODUCTO = "ProductOrServiceAxis"

# Filas de relleno que XBRL intercala y que no son ni etiqueta ni dato
RUIDO = ("[line items]", "[abstract]", "[member]", "[domain]", "[axis]",
         "[table]", "[roll forward]")

# Miembros del eje de consolidacion. NO son segmentos: son totales, ajustes o
# partidas no asignadas. Si se dejan pasar aparecen como una linea de negocio
# mas y duplican los ingresos al sumar las partes.
NO_SON_BLOQUES = {
    "operating segments", "operating segment", "reportable segments",
    "corporate non-segment", "corporate, non-segment", "corporate",
    "segment reconciling items", "reconciling items", "intersegment elimination",
    "intersegment eliminations", "eliminations", "consolidation, eliminations",
    "material reconciling items", "all other segments", "unallocated",
    "corporate and other", "consolidated entity excluding eliminations",
}


def _es_bloque_valido(nombre):
    return str(nombre).strip().lower() not in NO_SON_BLOQUES


def _pedir(url, texto=False):
    try:
        p = urllib.request.Request(url, headers=CABECERA_SEC)
        with urllib.request.urlopen(p, timeout=TIEMPO_ESPERA) as r:
            bruto = r.read()
        return bruto.decode("utf-8", "replace") if texto else json.loads(bruto)
    except Exception:
        return None


# =============================================================================
#  LOCALIZAR LOS INFORMES DE SEGMENTOS DEL ULTIMO EXPEDIENTE
# =============================================================================

def ultimo_expediente(cik, formularios=("10-K", "20-F", "40-F")):
    """Accession number y fecha del ultimo informe anual disponible."""
    datos = _pedir(f"https://data.sec.gov/submissions/CIK{cik}.json")
    if not datos:
        return None
    rec = datos.get("filings", {}).get("recent", {})
    formas = rec.get("form", [])
    for i, f in enumerate(formas):
        if f in formularios:
            return {
                "accession": rec["accessionNumber"][i].replace("-", ""),
                "accession_guion": rec["accessionNumber"][i],
                "fecha": rec["filingDate"][i],
                "formulario": f,
                "periodo": rec.get("reportDate", [None] * len(formas))[i],
            }
    return None


def informes_del_expediente(cik, accession):
    """Lista de informes renderizados (R*.htm) del expediente, con su nombre."""
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession}"
    resumen = _pedir(f"{base}/FilingSummary.xml", texto=True)
    if not resumen:
        return base, []
    salida = []
    for bloque in re.findall(r"<Report[^>]*>(.*?)</Report>", resumen, re.S):
        nombre = re.search(r"<ShortName>(.*?)</ShortName>", bloque, re.S)
        fichero = re.search(r"<HtmlFileName>(.*?)</HtmlFileName>", bloque, re.S)
        if nombre and fichero:
            salida.append({"fichero": fichero.group(1).strip(),
                           "nombre": nombre.group(1).strip()})
    return base, salida


def _candidatos(informes):
    """Informes cuyo nombre sugiere desglose. Se filtra despues por el eje real."""
    claves = ("segment", "geograph", "disaggregat", "by region", "by market",
              "by product", "major customer", "revenue by")
    excluir = ("policy", "policies", "tables)", "narrative", "additional information")
    salida = []
    for inf in informes:
        n = inf["nombre"].lower()
        if any(k in n for k in claves) and not any(x in n for x in excluir):
            salida.append(inf)
    return salida


# =============================================================================
#  PARSEO DE UN INFORME
# =============================================================================

def _escala(titulo):
    """Multiplicador declarado en la cabecera: 'in Thousands', 'in Millions'..."""
    t = (titulo or "").lower()
    if "in billions" in t:
        return 1e9, "miles de millones"
    if "in millions" in t:
        return 1e6, "millones"
    if "in thousands" in t:
        return 1e3, "miles"
    return 1.0, "unidades"


def _numero(valor, factor):
    """Convierte '$ (220,960)' o '151790' en un float con su signo y escala."""
    if valor is None or (isinstance(valor, float) and np.isnan(valor)):
        return np.nan
    s = str(valor).strip()
    if s in ("", "nan", "None", "—", "-"):
        return np.nan
    negativo = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace("$", "").replace(",", "").replace("%", "").strip()
    if not re.fullmatch(r"-?\d*\.?\d+", s):
        return np.nan
    v = float(s) * factor
    return -v if negativo else v


def _es_ruido(etiqueta):
    e = str(etiqueta).strip().lower()
    return (not e) or e == "nan" or any(r in e for r in RUIDO)


def parsear_informe(html):
    """Convierte un informe R*.htm en una tabla larga de desglose.

    Devuelve (DataFrame, metadatos) o None. El DataFrame tiene una fila por
    combinacion de bloque (segmento o pais), metrica y periodo.
    """
    try:
        tablas = pd.read_html(io.StringIO(html))
    except Exception:
        return None
    if not tablas:
        return None

    datos = tablas[0]
    if datos.shape[1] < 2:
        return None

    # La cabecera lleva el titulo, la divisa y la escala
    titulo = " ".join(str(c) for c in datos.columns[:1])
    factor, escala_txt = _escala(titulo)
    moneda = "USD" if "usd" in titulo.lower() else None

    periodos = [str(c) for c in datos.columns[1:]]
    # El primer nivel de la cabecera repite el titulo; el util es el segundo
    if isinstance(datos.columns, pd.MultiIndex):
        periodos = [str(c[-1]) for c in datos.columns[1:]]

    # Ejes XBRL declarados al pie del informe
    ejes, miembros = set(), []
    for t in tablas[1:]:
        if t.shape[1] >= 2 and str(t.iloc[0, 0]).lower().startswith("name"):
            nombre = str(t.iloc[0, 1])
            if "Axis=" in nombre:
                eje, miembro = nombre.split("Axis=", 1)
                ejes.add(eje.split("_")[-1] + "Axis")
                miembros.append(miembro.strip())

    # Antes de recorrer nada hay que identificar la fila de relleno que XBRL
    # intercala tras CADA etiqueta. Normalmente se llama "... [Line Items]" y el
    # filtro de ruido la caza, pero no siempre: en Nvidia se llama "Revenues and
    # Long-Lived Assets", sin corchetes. Si no se detecta, esa fila sobrescribe
    # la etiqueta del pais que acaba de leerse y los ingresos se atribuyen al
    # bloque equivocado.
    # Criterio: un miembro real de una dimension aparece UNA vez como etiqueta;
    # la fila de relleno se repite. Todo lo que aparezca dos o mas veces es
    # relleno.
    conteo = {}
    for _, fila in datos.iterrows():
        etiqueta = str(fila.iloc[0]).strip()
        valores = [_numero(v, factor) for v in fila.iloc[1:]]
        if all(np.isnan(v) for v in valores) and not _es_ruido(etiqueta):
            conteo[etiqueta] = conteo.get(etiqueta, 0) + 1
    relleno = {e for e, c in conteo.items() if c >= 2}

    filas, bloque_actual = [], "Consolidado"
    for _, fila in datos.iterrows():
        etiqueta = str(fila.iloc[0]).strip()
        valores = [_numero(v, factor) for v in fila.iloc[1:]]
        if _es_ruido(etiqueta) or etiqueta in relleno:
            continue
        if all(np.isnan(v) for v in valores):
            # Fila sin cifras: introduce un bloque nuevo. Las etiquetas
            # compuestas del tipo "Japon | Operating segments" se quedan con la
            # primera parte, que es la dimension que interesa.
            bloque_actual = etiqueta.split("|")[0].strip()
            continue
        for periodo, v in zip(periodos, valores):
            if not np.isnan(v):
                filas.append({"Bloque": bloque_actual, "Metrica": etiqueta,
                              "Periodo": periodo, "Valor": v})

    if not filas:
        return None

    tipo = None
    if any(EJE_GEOGRAFIA in e for e in ejes):
        tipo = "geografia"
    elif any(EJE_NEGOCIO in e for e in ejes):
        tipo = "negocio"
    elif any(EJE_PRODUCTO in e for e in ejes):
        tipo = "producto"

    return pd.DataFrame(filas), {
        "tipo": tipo, "ejes": sorted(ejes), "miembros": miembros,
        "escala": escala_txt, "factor": factor, "moneda": moneda,
        "titulo": titulo, "periodos": periodos,
    }


# =============================================================================
#  MAPEO DE NOMBRES A PAISES
# =============================================================================

# Codigos ISO-3 de los nombres que aparecen habitualmente en los informes de la
# SEC. Se resuelve por NOMBRE y no por orden de aparicion de los miembros XBRL,
# porque el orden no esta garantizado y una desalineacion pondria los ingresos
# de un pais en otro.
PAISES = {
    "united states": "USA", "united states of america": "USA", "u.s.": "USA",
    "u.s": "USA", "us": "USA", "usa": "USA", "america": "USA",
    "china": "CHN", "greater china": "CHN", "prc": "CHN",
    "mainland china": "CHN", "china (including hong kong)": "CHN",
    "japan": "JPN", "germany": "DEU", "united kingdom": "GBR", "u.k.": "GBR",
    "france": "FRA", "italy": "ITA", "spain": "ESP", "netherlands": "NLD",
    "ireland": "IRL", "switzerland": "CHE", "sweden": "SWE", "norway": "NOR",
    "denmark": "DNK", "finland": "FIN", "belgium": "BEL", "austria": "AUT",
    "poland": "POL", "portugal": "PRT", "greece": "GRC", "russia": "RUS",
    "canada": "CAN", "mexico": "MEX", "brazil": "BRA", "argentina": "ARG",
    "chile": "CHL", "colombia": "COL", "peru": "PER",
    "india": "IND", "south korea": "KOR", "korea": "KOR",
    "republic of korea": "KOR", "taiwan": "TWN", "singapore": "SGP",
    "malaysia": "MYS", "thailand": "THA", "indonesia": "IDN",
    "philippines": "PHL", "vietnam": "VNM", "hong kong": "HKG",
    "australia": "AUS", "new zealand": "NZL",
    "israel": "ISR", "turkey": "TUR", "saudi arabia": "SAU",
    "united arab emirates": "ARE", "south africa": "ZAF", "egypt": "EGY",
    "nigeria": "NGA", "kenya": "KEN", "morocco": "MAR",
}

# Codigos ISO-2 de los miembros XBRL `country_XX` -> ISO-3, por si el nombre de
# la tabla no es reconocible pero el eje si lo es.
ISO2_A_ISO3 = {
    "US": "USA", "CN": "CHN", "JP": "JPN", "DE": "DEU", "GB": "GBR",
    "FR": "FRA", "IT": "ITA", "ES": "ESP", "NL": "NLD", "IE": "IRL",
    "CH": "CHE", "SE": "SWE", "CA": "CAN", "MX": "MEX", "BR": "BRA",
    "IN": "IND", "KR": "KOR", "TW": "TWN", "SG": "SGP", "MY": "MYS",
    "TH": "THA", "ID": "IDN", "PH": "PHL", "VN": "VNM", "HK": "HKG",
    "AU": "AUS", "NZ": "NZL", "IL": "ISR", "TR": "TUR", "SA": "SAU",
    "AE": "ARE", "ZA": "ZAF", "NO": "NOR", "DK": "DNK", "FI": "FIN",
    "BE": "BEL", "AT": "AUT", "PL": "POL", "PT": "PRT", "RU": "RUS",
}

# Etiquetas que son agregados regionales y NO un pais: no van al mapa.
REGIONES = ("europe", "asia", "pacific", "americas", "latin", "emea", "apac",
            "middle east", "africa", "international", "other", "rest of",
            "north america", "south america", "central", "worldwide",
            "all other", "eliminations", "corporate", "unallocated", "total",
            "consolidado", "consolidated", "foreign", "domestic")


def es_geografico(etiqueta):
    """True si la etiqueta designa un pais o un area geografica.

    Hace falta porque un mismo informe puede mezclar DIMENSIONES DISTINTAS en la
    misma tabla: Gilead publica en el mismo cuadro el desglose por region
    (U.S., Europe, Rest of World) y por medicamento (Biktarvy, Descovy...).
    Sumarlo todo como si fueran partes de un mismo desglose triplicaba los
    ingresos. Solo se conservan los bloques de naturaleza geografica.
    """
    e = str(etiqueta).strip().lower()
    if not e or e in ("consolidado", "total", "consolidated"):
        return False
    if codigo_pais(etiqueta):
        return True
    palabras_geo = ("europe", "asia", "pacific", "america", "americas", "latin",
                    "emea", "apac", "middle east", "africa", "international",
                    "rest of world", "rest of the world", "rest of", "other countries",
                    "other geographic", "foreign", "domestic", "nordic", "iberia",
                    "greater china", "north america", "south america", "oceania",
                    "worldwide", "abroad", "outside")
    return any(p in e for p in palabras_geo)


def codigo_pais(etiqueta):
    """ISO-3 del pais, o None si la etiqueta es una region o un agregado."""
    e = str(etiqueta).strip().lower().rstrip(".").strip()
    e = re.sub(r"\s*\(.*?\)\s*$", "", e).strip()
    if not e:
        return None
    if e in PAISES:
        return PAISES[e]
    # "United States" dentro de "United States and Canada" no se resuelve: si la
    # etiqueta menciona una region, se trata como agregado.
    if any(r in e for r in REGIONES):
        return None
    for nombre, iso in PAISES.items():
        if e == nombre or e.startswith(nombre + " "):
            return iso
    return None


# =============================================================================
#  ORQUESTACION
# =============================================================================

def _metrica_principal(tabla):
    """Metrica de ingresos del informe: la que mas bloques cubre."""
    if tabla is None or tabla.empty:
        return None
    preferidas = ("net sales", "revenue", "revenues", "net revenue",
                  "total net sales", "sales", "total revenue",
                  "revenues from external customers", "net sales and revenue")
    conteo = tabla.groupby("Metrica")["Bloque"].nunique().sort_values(ascending=False)
    for m in conteo.index:
        if any(p == m.strip().lower() or p in m.strip().lower() for p in preferidas):
            return m
    return conteo.index[0] if len(conteo) else None


def analizar_segmentos(cik, maximo_informes=8):
    """Desglose por geografia y por linea de negocio del ultimo informe anual."""
    if not cik:
        return None
    exp = ultimo_expediente(cik)
    if not exp:
        return None
    base, informes = informes_del_expediente(cik, exp["accession"])
    if not informes:
        return None

    resultado = {"expediente": exp, "base": base,
                 "geografia": None, "negocio": None, "producto": None,
                 "informes_usados": [], "informes_revisados": 0}

    for inf in _candidatos(informes)[:maximo_informes]:
        html = _pedir(f"{base}/{inf['fichero']}", texto=True)
        resultado["informes_revisados"] += 1
        if not html:
            continue
        parseado = parsear_informe(html)
        if not parseado:
            continue
        tabla, meta = parseado
        tipo = meta["tipo"]
        if tipo not in ("geografia", "negocio", "producto"):
            continue
        # Nos quedamos con el informe mas rico de cada tipo
        anterior = resultado.get(tipo)
        if anterior is None or tabla["Bloque"].nunique() > anterior[0]["Bloque"].nunique():
            resultado[tipo] = (tabla, meta)
            resultado["informes_usados"].append(
                {"tipo": tipo, "nombre": inf["nombre"], "fichero": inf["fichero"],
                 "bloques": int(tabla["Bloque"].nunique()),
                 "url": f"{base}/{inf['fichero']}"})

    if not any(resultado[k] for k in ("geografia", "negocio", "producto")):
        return None
    return resultado


def desglose(paquete, tipo, ingresos_reales=None):
    """Desglose de un tipo, con el total de referencia ya arbitrado.

    `ingresos_reales` son los ingresos del ultimo ejercicio segun la cuenta de
    resultados. Sirven de arbitro cuando el "total" que aparece dentro del
    informe de segmentos NO es el total de la empresa: ocurre a menudo, porque
    esas tablas incluyen subtotales intermedios. En Stryker el total detectado
    dentro del informe eran 7.171 M cuando la compania factura unos 25.000 M, de
    modo que la suma de las partes era correcta y la referencia estaba mal.
    """
    if not paquete or not paquete.get(tipo):
        return None
    tabla, meta = paquete[tipo]
    metrica = _metrica_principal(tabla)
    if not metrica:
        return None

    sub = tabla[tabla["Metrica"] == metrica]
    pivote = sub.pivot_table(index="Bloque", columns="Periodo", values="Valor",
                             aggfunc="first")
    pivote = pivote.loc[:, ~pivote.columns.duplicated()]
    # Orden cronologico: los periodos vienen del mas reciente al mas antiguo.
    # Hay que quitar repetidos ANTES de reordenar, o se vuelven a introducir
    # columnas duplicadas y cualquier suma posterior devuelve una Series en vez
    # de un escalar.
    orden_periodos = list(dict.fromkeys(meta["periodos"]))
    if all(p in pivote.columns for p in orden_periodos):
        pivote = pivote[orden_periodos]

    consolidado = None
    for nombre in ("Consolidado", "Total", "Consolidated"):
        if nombre in pivote.index:
            c = pivote.loc[nombre]
            # Con indice repetido .loc devuelve un DataFrame: se toma la primera
            consolidado = c.iloc[0] if isinstance(c, pd.DataFrame) else c
            break

    # Fuera el consolidado y fuera los miembros del eje de consolidacion, que
    # no son partes sino totales o ajustes: si se dejan, la suma duplica.
    a_quitar = [i for i in pivote.index
                if str(i).strip().lower() in ("consolidado", "total", "consolidated")
                or not _es_bloque_valido(i)]
    partes = pivote.drop(index=a_quitar, errors="ignore")

    # QUE BLOQUES FORMAN EL DESGLOSE. Dos problemas reales lo complican:
    #
    #  - Un mismo cuadro puede mezclar dimensiones distintas. Gilead publica en
    #    la misma tabla las regiones y los medicamentos; sumarlo todo triplicaba
    #    los ingresos.
    #  - Otras empresas publican dos niveles solapados: Arista declara "Americas"
    #    y ademas "United States", que ya esta dentro. Sumar ambos cuenta dos
    #    veces lo mismo.
    #
    # Elegir por lista de palabras es fragil (a Ichor le tumbaba el bloque
    # "Other", que ahi si es geografico). El criterio objetivo es el unico
    # fiable: se prueban varios cortes y se conserva el que MEJOR CUADRA contra
    # el total que declara la propia empresa.
    seleccion = "todos los bloques"
    origen_referencia = "total del informe"
    ref = np.nan
    if len(pivote.columns):
        if consolidado is not None:
            ref = consolidado.get(pivote.columns[0], np.nan)
            if isinstance(ref, pd.Series):
                ref = float(ref.iloc[0]) if len(ref) else np.nan
        # Los ingresos de la cuenta de resultados solo se usan como referencia
        # cuando el informe NO trae total propio. Se probo usarlos tambien para
        # corregir totales sospechosos y salio peor: el periodo y la escala del
        # informe de segmentos no siempre coinciden con los del ejercicio
        # contable, y el desajuste rompia desgloses que cuadraban al centimo
        # (Microsoft pasaba de +0,0000% a +26%). El total interno del informe es
        # mejor referencia porque procede de la misma tabla, el mismo periodo y
        # la misma escala.
        if not np.isfinite(ref) and ingresos_reales \
                and np.isfinite(ingresos_reales) and ingresos_reales > 0:
            ref = float(ingresos_reales)
            origen_referencia = "ingresos de la cuenta de resultados"
    if len(partes) > 1 and len(pivote.columns) and np.isfinite(ref) and ref:
        if True:
            def error(sub):
                if sub is None or len(sub) < 1:
                    return np.inf
                return abs(float(sub[pivote.columns[0]].sum(skipna=True)) / ref - 1)

            residual = ("other", "others", "all other", "rest", "remaining")

            def sel(cond):
                idx = [i for i in partes.index if cond(i)]
                return partes.loc[idx] if len(idx) >= 2 else None

            candidatos = [
                ("todos los bloques", partes),
                ("solo geograficos", sel(es_geografico)),
                ("geograficos y residuales",
                 sel(lambda i: es_geografico(i)
                     or str(i).strip().lower() in residual)),
                ("solo paises", sel(codigo_pais)),
                ("paises y residuales",
                 sel(lambda i: codigo_pais(i)
                     or str(i).strip().lower() in residual)),
                ("solo regiones", sel(lambda i: not codigo_pais(i))),
            ]
            mejor_nombre, mejor_sub, mejor_err = "todos los bloques", partes, error(partes)
            for nombre_c, cand in candidatos[1:]:
                e = error(cand)
                if e < mejor_err - 1e-9:
                    mejor_nombre, mejor_sub, mejor_err = nombre_c, cand, e
            partes, seleccion = mejor_sub, mejor_nombre

    cuadre = []
    if consolidado is not None or (np.isfinite(ref) and ref):
        for periodo in pivote.columns:
            suma = float(partes[periodo].sum(skipna=True))
            if origen_referencia == "ingresos de la cuenta de resultados"                     and periodo == pivote.columns[0]:
                total = ref
            elif consolidado is None:
                continue
            else:
                total = consolidado.get(periodo, np.nan)
            # Si el indice tiene entradas repetidas, .get devuelve una Series:
            # hay que quedarse con un escalar antes de comparar nada.
            if isinstance(total, pd.Series):
                total = float(total.iloc[0]) if len(total) else np.nan
            total = float(total) if total is not None else np.nan
            if np.isfinite(total) and total:
                cuadre.append({"Periodo": periodo, "Suma de las partes": suma,
                               "Total declarado": total,
                               "Desvio": suma / total - 1})

    return {"metrica": metrica, "tabla": pivote, "partes": partes,
            "consolidado": consolidado, "cuadre": pd.DataFrame(cuadre),
            "seleccion": seleccion, "referencia": ref,
            "origen_referencia": origen_referencia, "meta": meta}


def tabla_geografica(paquete, ingresos_reales=None):
    """Desglose geografico con codigo ISO y marca de si es pais o region."""
    d = desglose(paquete, "geografia", ingresos_reales=ingresos_reales)
    if d is None:
        return None
    partes = d["partes"]
    if partes.empty:
        return None
    periodo = partes.columns[0]          # el mas reciente
    filas = []
    for bloque in partes.index:
        valor = partes.loc[bloque, periodo]
        if not np.isfinite(valor):
            continue
        iso = codigo_pais(bloque)
        filas.append({
            "Area": str(bloque),
            "ISO3": iso,
            "Es pais": iso is not None,
            "Importe": float(valor),
        })
    if not filas:
        return None
    df = pd.DataFrame(filas)
    total = df["Importe"].sum()
    df["Peso"] = df["Importe"] / total if total else np.nan
    return {"tabla": df.sort_values("Importe", ascending=False),
            "periodo": periodo, "detalle": d}


def evolucion_bloques(paquete, tipo, ingresos_reales=None):
    """Serie por bloque y periodo, en formato largo para graficos."""
    d = desglose(paquete, tipo, ingresos_reales=ingresos_reales)
    if d is None:
        return None
    partes = d["partes"]
    if partes.empty:
        return None
    largo = partes.reset_index().melt(id_vars="Bloque", var_name="Periodo",
                                      value_name="Importe").dropna()
    # Crecimiento respecto al periodo anterior (las columnas van de mas reciente
    # a mas antigua, asi que se invierte para calcularlo)
    orden = list(partes.columns)[::-1]
    crec = []
    for bloque in partes.index:
        for i in range(1, len(orden)):
            a, b = partes.loc[bloque, orden[i - 1]], partes.loc[bloque, orden[i]]
            if np.isfinite(a) and np.isfinite(b) and a:
                crec.append({"Bloque": bloque, "Periodo": orden[i],
                             "Crecimiento": b / a - 1})
    return {"largo": largo, "crecimiento": pd.DataFrame(crec),
            "pivote": partes, "detalle": d}


def margenes_por_segmento(paquete):
    """Margen operativo de cada linea de negocio, si el informe lo declara."""
    if not paquete or not paquete.get("negocio"):
        return None
    tabla, meta = paquete["negocio"]
    metricas = {m.strip().lower(): m for m in tabla["Metrica"].unique()}

    def buscar(*claves):
        for c in claves:
            for k, original in metricas.items():
                if k == c:
                    return original
        for c in claves:
            for k, original in metricas.items():
                if c in k:
                    return original
        return None

    m_ing = buscar("net sales", "revenue", "revenues", "total revenue", "sales")
    m_op = buscar("operating income", "operating income (loss)", "segment operating income",
                  "income from operations")
    if not m_ing or not m_op:
        return None

    periodo = meta["periodos"][0] if meta["periodos"] else None
    filas = []
    for bloque in tabla["Bloque"].unique():
        if str(bloque).strip().lower() in ("consolidado", "total", "consolidated"):
            continue
        if not _es_bloque_valido(bloque):
            continue
        sub = tabla[(tabla["Bloque"] == bloque) & (tabla["Periodo"] == periodo)]
        ing = sub[sub["Metrica"] == m_ing]["Valor"]
        op = sub[sub["Metrica"] == m_op]["Valor"]
        if len(ing) and len(op):
            i, o = float(ing.iloc[0]), float(op.iloc[0])
            if i:
                filas.append({"Segmento": str(bloque), "Ingresos": i,
                              "Resultado operativo": o, "Margen operativo": o / i})
    if not filas:
        return None
    return {"tabla": pd.DataFrame(filas).sort_values("Ingresos", ascending=False),
            "periodo": periodo, "metrica_ingresos": m_ing, "metrica_resultado": m_op}
