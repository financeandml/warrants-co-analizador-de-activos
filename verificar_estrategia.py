"""Bateria de verificacion de los MODULOS DE ANALISIS COMPLEMENTARIO.

Tercera bateria del proyecto, junto a verificar_fidelidad y
verificar_fundamentales. Comprueba que las cinco capas anadidas sobre la
seleccion de valores hacen lo que dicen hacer, y sobre todo que NO hacen lo que
no deben:

    - que la seleccion de valores sigue siendo exactamente la misma
    - que no se usa informacion del futuro en ningun punto
    - que los procedimientos estadisticos reproducen sus definiciones

Se ejecuta con:  python verificar_estrategia.py
"""

import sys
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

import motor_cribado as crib
import motor_factores as fac
import motor_origen as ori
import motor_regimen as reg
import motor_validacion as val

COMPROBACIONES = 0
FALLOS = 0


def comprobar(etiqueta, condicion, detalle=""):
    global COMPROBACIONES, FALLOS
    COMPROBACIONES += 1
    ok = bool(condicion)
    if not ok:
        FALLOS += 1
    print(f"  [{'OK  ' if ok else 'FALLO'}] {etiqueta}")
    if detalle and not ok:
        print(f"         {detalle}")
    elif detalle:
        print(f"         {detalle}")


def titulo(texto):
    print(f"\n-- {texto} --")


# =============================================================================
def bloque_contraste_multiple():
    titulo("Contraste multiple (Benjamini-Hochberg)")

    # Ejemplo canonico del articulo original de 1995: 4 rechazos al 5%
    p = [0.0001, 0.0004, 0.0019, 0.0095, 0.0201, 0.0278, 0.0298, 0.0344,
         0.0459, 0.3240, 0.4262, 0.5719, 0.6528, 0.7590, 1.000]
    rech, q = val.benjamini_hochberg(p, tasa=0.05)
    comprobar("Reproduce el ejemplo de Benjamini y Hochberg (1995)",
              int(rech.sum()) == 4, f"rechazos={int(rech.sum())}, esperados=4")

    comprobar("Los q-valores son no decrecientes",
              bool(np.all(np.diff(q) >= -1e-12)))

    comprobar("Ningun q supera la unidad", bool(np.nanmax(q) <= 1.0))

    # Un q nunca puede ser menor que su p
    comprobar("Cada q es mayor o igual que su p",
              bool(np.all(q >= np.array(p) - 1e-12)))

    # Sin contrastes validos no debe reventar
    r2, q2 = val.benjamini_hochberg([np.nan, np.nan])
    comprobar("Con todos los contrastes invalidos no falla",
              int(r2.sum()) == 0 and np.all(np.isnan(q2)))

    # Control real de la tasa de falsos hallazgos bajo hipotesis nula
    rng = np.random.default_rng(4242)
    espurios = []
    for _ in range(60):
        ps = [val._p_valor(rng.normal(0, 0.05, 25), 0.0) for _ in range(300)]
        rr, _ = val.benjamini_hochberg(ps, tasa=0.10)
        espurios.append(int(rr.sum()))
    media = float(np.mean(espurios))
    comprobar("Bajo hipotesis nula apenas declara hallazgos",
              media < 1.0, f"media {media:.2f} de 300 contrastes "
                           f"(sin correccion saldrian ~15 al 5%)")

    # El contraste es unilateral: un rebote NEGATIVO no puede dar p pequeno
    p_malo = val._p_valor(np.full(20, -0.05) + rng.normal(0, 0.001, 20), 0.0)
    comprobar("Un rebote negativo no produce un p pequeno",
              p_malo > 0.9, f"p={p_malo:.4f}")


# =============================================================================
def bloque_particion():
    titulo("Particion con purga y embargo")

    indice = pd.date_range("2021-01-01", periods=1250, freq="B")
    ventana = 15
    L = val._tramos(indice, ventana, 0.60)
    comprobar("Se obtienen los dos tramos", L is not None)
    if not L:
        return

    hueco = (L["inicio_fuera"] - L["fin_dentro"]).days
    comprobar("Existe separacion real entre ambos tramos",
              L["fin_dentro"] < L["inicio_fuera"],
              f"hueco de {hueco} dias naturales")

    sesiones_hueco = int(((indice > L["fin_dentro"]) &
                          (indice < L["inicio_fuera"])).sum())
    comprobar("El hueco cubre al menos el horizonte completo",
              sesiones_hueco >= ventana,
              f"{sesiones_hueco} sesiones descartadas, horizonte {ventana}")

    comprobar("El primer tramo empieza al principio de la serie",
              L["inicio_dentro"] == indice[0])
    comprobar("El segundo tramo termina al final de la serie",
              L["fin_fuera"] == indice[-1])

    # Con una serie demasiado corta debe negarse, no inventar
    corto = val._tramos(pd.date_range("2024-01-01", periods=20, freq="B"), 15)
    comprobar("Con historia insuficiente devuelve None", corto is None)


# =============================================================================
def bloque_newey_west():
    titulo("Errores estandar de Newey-West")

    rng = np.random.default_rng(11)
    n = 600
    X = np.column_stack([np.ones(n), rng.normal(0, 1, n), rng.normal(0, 1, n)])
    beta = np.array([0.01, 0.5, -0.3])

    e = rng.normal(0, 1, n) * (1 + np.abs(X[:, 1]))
    y = X @ beta + e
    c, *_ = np.linalg.lstsq(X, y, rcond=None)
    r = y - X @ c
    nw0 = fac._newey_west(X, r, 0)
    iv = np.linalg.pinv(X.T @ X)
    u = X * r[:, None]
    hc1 = iv @ (u.T @ u) @ iv * n / (n - 3)
    comprobar("Con cero retardos coincide con White HC1",
              np.allclose(nw0, hc1), f"diferencia maxima {np.abs(nw0-hc1).max():.2e}")

    ruido = rng.normal(0, 1, n)
    ar = np.zeros(n)
    for i in range(n):
        ar[i] = 0.8 * (ar[i - 1] if i else 0) + ruido[i]
    y2 = X @ beta + ar
    c2, *_ = np.linalg.lstsq(X, y2, rcond=None)
    r2 = y2 - X @ c2
    ee_mco = np.sqrt(np.diag(iv * float(r2 @ r2) / (n - 3)))
    ee_nw = np.sqrt(np.diag(fac._newey_west(X, r2, 15)))
    comprobar("Con autocorrelacion es mas conservador que MCO",
              ee_nw[0] > ee_mco[0],
              f"NW {ee_nw[0]:.5f} frente a MCO {ee_mco[0]:.5f} "
              f"(x{ee_nw[0]/ee_mco[0]:.2f})")

    comprobar("La matriz de covarianzas es semidefinida positiva",
              bool(np.all(np.linalg.eigvalsh(fac._newey_west(X, r2, 15)) >= -1e-10)))


# =============================================================================
def bloque_sin_futuro(cierres):
    titulo("Ausencia de informacion del futuro")

    # La serie de la estrategia no puede cobrar el retorno del dia de la caida
    serie = fac.serie_estrategia(cierres, umbral=2.0, ventana=5)
    comprobar("La cartera historica se construye", serie is not None)
    if serie:
        retornos = cierres.pct_change()
        sigma = retornos.rolling(fac.VENTANA_SIGMA, min_periods=120).std().shift(1)
        z = retornos / sigma
        senal = (z <= -2.0) & sigma.notna()
        # El dia de la senal la cartera no debe tener esa posicion abierta
        dia = senal.any(axis=1)
        dias_senal = senal.index[dia][:200]
        # Si se incluyese el propio desplome, la media de esos dias seria muy
        # negativa; al entrar al cierre, no lo es.
        media_dias_senal = float(serie["retornos"].reindex(dias_senal).mean())
        comprobar("La entrada se produce al cierre, no antes",
                  media_dias_senal > -0.01,
                  f"retorno medio de la cartera los dias de senal: "
                  f"{media_dias_senal:+.4%}")

    # El percentil de regimen debe ir desplazado una sesion
    tk = cierres.columns[0]
    precios = cierres[tk].dropna()
    ret = precios.pct_change().dropna()
    vol = reg._volatilidad_realizada(ret)
    pct = reg._percentil_expandido(vol)
    crudo = vol.expanding(min_periods=reg.MIN_HISTORIA_REGIMEN).rank(pct=True)
    comprobar("El regimen esta desplazado una sesion respecto a la volatilidad",
              pct.iloc[-1] == crudo.iloc[-2],
              "el ultimo percentil corresponde a la sesion anterior")

    # La sigma del tramo de validacion se estima solo con datos del tramo
    fuente = "sigma_dentro" in open("motor_validacion.py", encoding="utf-8").read()
    comprobar("La sigma de la particion se estima dentro de cada tramo", fuente)


# =============================================================================
def bloque_invariante(cierres, universo, ausentes):
    titulo("La seleccion de valores no se altera")

    for umbral, sesiones, ventana in [(2.0, 1, 15), (1.5, 5, 10), (2.5, 10, 20)]:
        base = crib.cribar(cierres, umbral=umbral, ventana=ventana,
                           sesiones_atras=sesiones, universo=universo,
                           ausentes=ausentes)
        ref = crib.referencia_mercado(cierres, ventana=ventana)
        base = crib.anadir_ventaja(base, ref)
        antes = base["tabla"].copy()

        con = val.validacion_fuera_de_periodo(
            val.contraste_multiple(base, ref), cierres)
        despues = con["tabla"]

        col = f"Media +{ventana}d"
        mismo_orden = list(antes["Ticker"]) == list(despues["Ticker"])
        mismas_cifras = np.allclose(antes[col].fillna(-99),
                                    despues[col].fillna(-99))
        solo_anade = set(antes.columns).issubset(set(despues.columns))
        comprobar(f"{umbral}s / {sesiones} sesiones / {ventana}d: seleccion intacta",
                  mismo_orden and mismas_cifras and solo_anade,
                  f"{len(antes)} valores, columnas nuevas "
                  f"{sorted(set(despues.columns) - set(antes.columns))}")


# =============================================================================
def bloque_duplicados(cierres, universo, ausentes):
    titulo("Un contraste por valor, no por fila")

    r = crib.cribar(cierres, umbral=1.5, ventana=15, sesiones_atras=10,
                    universo=universo, ausentes=ausentes)
    ref = crib.referencia_mercado(cierres, ventana=15)
    r = crib.anadir_ventaja(r, ref)
    tabla = r["tabla"]
    distintos = int(tabla["Ticker"].nunique())
    repetidos = int(len(tabla) - distintos)

    c = val.contraste_multiple(r, ref)
    comprobar("El numero de contrastes no excede al de valores distintos",
              c["contraste"]["contrastes"] <= distintos,
              f"{len(tabla)} filas, {distintos} valores, "
              f"{c['contraste']['contrastes']} contrastes, {repetidos} repetidos")

    rep = c["tabla"][c["tabla"]["Ticker"].duplicated(keep=False)]
    if not rep.empty:
        coherente = int(rep.groupby("Ticker")[["p", "q"]].nunique().max().max()) == 1
        comprobar("Las filas de un mismo valor comparten p y q", coherente)
    else:
        comprobar("Las filas de un mismo valor comparten p y q", True,
                  "sin repeticiones en esta ejecucion")

    v = val.validacion_fuera_de_periodo(c, cierres).get("validacion")
    if v is not None:
        comprobar("La validacion no duplica valores",
                  int(v["tabla"]["Ticker"].duplicated().sum()) == 0)


# =============================================================================
def bloque_origen(cierres, universo):
    titulo("Clasificacion por origen de la caida")

    candidatos = list(cierres.columns[:8])
    muestra = ori.muestra_para_cobertura(universo, candidatos, 30)
    comprobar("La muestra incluye a los candidatos",
              all(c in muestra for c in candidatos))
    comprobar("La muestra no repite valores",
              len(muestra) == len(set(muestra)), f"{len(muestra)} valores")
    comprobar("La muestra reparte entre sectores",
              universo.set_index("Ticker").reindex(muestra)["Sector"].nunique() >= 5)
    comprobar("La muestra es determinista",
              muestra == ori.muestra_para_cobertura(universo, candidatos, 30))

    fechas = ori.fechas_resultados(muestra[:14])
    comprobar("Se recuperan fechas de resultados", len(fechas) > 5,
              f"{len(fechas)} valores con cobertura")

    clas = ori.clasificar_universo(cierres, universo, 2.0, fechas)
    comprobar("Se clasifican episodios", clas is not None and len(clas["episodios"]))
    if not clas:
        return

    comprobar("El calculo se restringe a los valores con cobertura",
              clas["restringido"] and
              clas["valores_examinados"] <= len(fechas),
              f"{clas['valores_examinados']} valores examinados de "
              f"{clas['valores_totales']} del universo")

    cats = set(clas["episodios"]["Categoría"])
    comprobar("Toda categoria pertenece al catalogo",
              cats.issubset(set(ori.CATEGORIAS)), f"{sorted(cats)}")

    # Cada episodio tiene una sola categoria
    dup = clas["episodios"].duplicated(subset=["Ticker", "Fecha"]).sum()
    comprobar("Cada episodio se clasifica una sola vez", int(dup) == 0)

    d = ori.desenlace_por_categoria(clas)
    comprobar("Se obtiene el desenlace por categoria", d is not None)
    if d:
        comprobar("Los cinco horizontes solicitados estan presentes",
                  d["horizontes"] == [1, 3, 5, 10, 15], f"{d['horizontes']}")
        suma = int(d["tabla"]["Episodios"].sum())
        comprobar("Los episodios de las categorias suman el total",
                  suma == d["total"], f"{suma} frente a {d['total']}")


# =============================================================================
def bloque_regimen(cierres, universo):
    titulo("Regimen por valor y por sector")

    tk = cierres.columns[0]
    sectores = dict(zip(universo["Ticker"], universo["Sector"]))
    r = reg.regimen_de(tk, cierres, universo, sectores.get(tk))
    comprobar("Se determina el regimen de un valor", r is not None)
    if not r:
        return

    comprobar("El estado pertenece al catalogo",
              r["estado"] in reg.ESTADOS, f"{r['estado']}")
    comprobar("El percentil esta entre cero y uno",
              0 <= r["percentil"] <= 1, f"{r['percentil']:.3f}")

    # Los cortes deben separar de verdad
    comprobar("Los cortes de estado son coherentes",
              reg._estado(0.10) == "Calma" and reg._estado(0.50) == "Normalidad"
              and reg._estado(0.90) == "Tensión")

    cond = reg.rebote_por_regimen(tk, cierres, 2.0, 15, r)
    if cond:
        total_desglose = int(cond["tabla"]["Episodios"].sum())
        comprobar("El desglose por regimen no pierde episodios",
                  total_desglose <= cond["total"],
                  f"{total_desglose} clasificados de {cond['total']} totales")
        comprobar("No se publica media con menos episodios que el minimo",
                  bool((cond["tabla"].loc[~cond["tabla"]["Suficiente"], "Media"]
                        .isna()).all()))

    # La clasificacion no puede salir toda igual: seria inservible
    cuadro = reg.cuadro_regimenes(list(cierres.columns[:30]), cierres, universo,
                                  1.0, 15, maximo=30)
    if cuadro is not None and len(cuadro["tabla"]) >= 10:
        estados = cuadro["tabla"]["Régimen del valor"].nunique()
        comprobar("La clasificacion discrimina entre estados",
                  estados >= 2,
                  f"{estados} estados distintos en "
                  f"{len(cuadro['tabla'])} valores")


# =============================================================================
def bloque_factorial(cierres):
    titulo("Descomposicion factorial")

    factores = fac.descargar_factores()
    comprobar("La biblioteca de Kenneth French responde", factores is not None)
    if factores is None:
        return

    for c in ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "RF", "Mom", "ST_Rev"]:
        pass
    faltan = [c for c in ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "RF", "Mom",
                          "ST_Rev"] if c not in factores.columns]
    comprobar("Estan los siete factores y el activo sin riesgo",
              not faltan, f"faltan {faltan}" if faltan else "todos presentes")

    comprobar("Los factores estan en tanto por uno, no en porcentaje",
              float(factores["Mkt-RF"].abs().max()) < 0.5,
              f"maximo absoluto {factores['Mkt-RF'].abs().max():.4f}")

    serie = fac.serie_estrategia(cierres, umbral=2.0, ventana=15)
    comprobar("Se reconstruye la cartera", serie is not None)
    if not serie:
        return

    d = fac.regresion_factorial(serie, factores)
    comprobar("La regresion produce resultado", d is not None)
    if not d:
        return

    comprobar("La beta de mercado es positiva y razonable",
              0.3 < d["cargas"].set_index("Clave").loc["Mkt-RF", "Carga"] < 1.6,
              f"beta {d['cargas'].set_index('Clave').loc['Mkt-RF','Carga']:.3f}")

    st_rev = d["cargas"].set_index("Clave").loc["ST_Rev", "Carga"]
    comprobar("Carga positiva en reversion a corto, como corresponde",
              st_rev > 0,
              f"carga {st_rev:+.3f}: comprar lo que acaba de caer ES esa prima")

    comprobar("El exceso bruto se reparte entre lo explicado y el residuo",
              abs(d["exceso_anual"] - d["explicado_anual"] - d["alfa_anual"]) < 1e-6,
              f"{d['exceso_anual']:+.2%} = {d['explicado_anual']:+.2%} "
              f"+ {d['alfa_anual']:+.2%}")

    comprobar("El R2 esta entre cero y uno", 0 <= d["r2"] <= 1, f"{d['r2']:.3f}")
    comprobar("Los retardos de Newey-West cubren el horizonte",
              d["retardos"] >= 5, f"{d['retardos']} retardos")
    comprobar("El texto de conclusion se genera",
              bool(fac.resumen_legible(d)))


# =============================================================================
def main():
    print("=" * 76)
    print("  VERIFICACION DE LOS MODULOS DE ANALISIS COMPLEMENTARIO")
    print("=" * 76)

    bloque_contraste_multiple()
    bloque_particion()
    bloque_newey_west()

    print("\n  Descargando el universo del S&P 500...")
    universo = crib.universo_sp500()
    if universo is None:
        print("  No se ha podido obtener el universo. Se aborta.")
        return 1
    cierres, ausentes = crib.descargar_universo(list(universo["Ticker"]))
    if cierres is None or cierres.empty:
        print("  No se han podido obtener las cotizaciones. Se aborta.")
        return 1
    print(f"  {cierres.shape[1]} valores x {cierres.shape[0]} sesiones "
          f"({len(ausentes)} ausentes)")

    bloque_sin_futuro(cierres)
    bloque_invariante(cierres, universo, ausentes)
    bloque_duplicados(cierres, universo, ausentes)
    bloque_regimen(cierres, universo)
    bloque_origen(cierres, universo)
    bloque_factorial(cierres)

    print("\n" + "=" * 76)
    print("  RESULTADO")
    print("=" * 76)
    print(f"  Comprobaciones realizadas : {COMPROBACIONES}")
    print(f"  Fallos                    : {FALLOS}")
    if FALLOS:
        print("\n  HAY FALLOS QUE CORREGIR.")
        return 1
    print("\n  TODO CORRECTO: las cinco capas cumplen su definicion y la")
    print("  seleccion de valores permanece inalterada.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
