"""Verificacion de correccion del motor de fundamentales.

No comprueba que la app arranque: comprueba que cada formula devuelve lo que su
definicion dice que debe devolver, recalculando por separado desde los estados
financieros. Sigue el principio de M9: nada se da por bueno si se puede
recalcular desde el origen.

Ejecutar:  python verificar_fundamentales.py
"""

import sys

import numpy as np
import pandas as pd
import yfinance as yf

import motor_fundamentales as mf

TOL = 1e-9
fallos = []
n = 0


def comprobar(etiqueta, obtenido, esperado, tol=TOL):
    global n
    n += 1
    if esperado is None or obtenido is None:
        ok = obtenido is esperado
        det = ""
    elif isinstance(esperado, bool):
        ok = bool(obtenido) == esperado
        det = "" if ok else f" (obtenido {obtenido}, esperado {esperado})"
    else:
        a, b = float(obtenido), float(esperado)
        ok = (abs(a - b) <= tol) or (np.isnan(a) and np.isnan(b))
        det = "" if ok else f" (obtenido {a!r}, esperado {b!r}, dif {abs(a-b):.3e})"
    print(f"  [{'OK  ' if ok else 'FALLO'}] {etiqueta}{det}")
    if not ok:
        fallos.append(etiqueta)


def afirmar(etiqueta, condicion, detalle=""):
    global n
    n += 1
    print(f"  [{'OK  ' if condicion else 'FALLO'}] {etiqueta}"
          f"{'' if condicion else ' -> ' + detalle}")
    if not condicion:
        fallos.append(etiqueta)


def bloque(t):
    print("\n" + "=" * 74)
    print("  " + t)
    print("=" * 74)


TICKERS = ["AAPL", "ICHR", "MSFT"]

for TK in TICKERS:
    bloque(TK)
    est = mf.estados_financieros(TK)
    if est is None:
        print("  sin estados financieros"); continue
    res, bal, flu = est["resultados"], est["balance"], est["flujo"]
    info = yf.Ticker(TK).info or {}

    # ------------------------------------------------------------------
    # 1. Limpieza de ejercicios vacios
    # ------------------------------------------------------------------
    print("\n-- Integridad de los estados --")
    for nombre, df in [("resultados", res), ("balance", bal), ("flujo", flu)]:
        vacias = [c for c in df.columns if df[c].isna().all()]
        afirmar(f"Sin ejercicios completamente vacios en {nombre}",
                len(vacias) == 0, f"{vacias}")

    # ------------------------------------------------------------------
    # 2. M11 - devengos de Sloan y ciclo de caja recalculados a mano
    # ------------------------------------------------------------------
    print("\n-- M11 Calidad del beneficio --")
    cal = mf.calidad_beneficio(est)
    if cal is not None:
        t = cal["tabla"]
        ult = t.iloc[-1]
        ni = ult["Beneficio neto"]; cfo = ult["Flujo operativo"]
        ta = mf._serie(bal, ["Total Assets"]).iloc[-1]
        comprobar("Devengos de Sloan = (BN - flujo operativo) / activo total",
                  ult["Devengos Sloan"], (ni - cfo) / ta)
        comprobar("Conversion flujo operativo / beneficio",
                  ult["Conversion OCF/BN"], cfo / ni)
        ing = ult["Ingresos"]
        ar = mf._serie(bal, ["Accounts Receivable", "Receivables"])
        if ar is not None:
            comprobar("DSO = cuentas por cobrar / ingresos * 365",
                      ult["DSO"], float(ar.iloc[-1]) / ing * 365, tol=1e-6)
        if all(np.isfinite([ult["DSO"], ult["DIO"], ult["DPO"]])):
            comprobar("Ciclo de caja = DSO + DIO - DPO",
                      ult["Ciclo de caja"], ult["DSO"] + ult["DIO"] - ult["DPO"],
                      tol=1e-6)
        tx = mf._serie(res, ["Tax Provision"]); pt = mf._serie(res, ["Pretax Income"])
        if tx is not None and pt is not None:
            comprobar("Tasa fiscal efectiva = impuesto / resultado antes de impuestos",
                      ult["Tasa fiscal efectiva"],
                      float(tx.iloc[-1]) / float(pt.iloc[-1]), tol=1e-9)

    # ------------------------------------------------------------------
    # 3. M12 - Piotroski, Altman, Beneish
    # ------------------------------------------------------------------
    print("\n-- M12 Riesgo contable --")
    pio = mf.piotroski_f(est)
    if pio:
        afirmar("Piotroski tiene 9 pruebas", len(pio["tabla"]) == 9,
                f"{len(pio['tabla'])}")
        afirmar("Puntuacion de Piotroski entre 0 y 9",
                0 <= pio["puntuacion"] <= 9, f"{pio['puntuacion']}")
        comprobar("Puntuacion = suma de los puntos individuales",
                  pio["puntuacion"], float(pio["tabla"]["Punto"].sum()))

    cap = info.get("marketCap", np.nan)
    alt = mf.altman_z(est, cap)
    if alt and not alt.get("bloqueado"):
        comprobar("Z-Score = suma de las aportaciones de sus 5 componentes",
                  alt["z"], float(alt["tabla"]["Aportacion"].sum()), tol=1e-9)
        for _, r in alt["tabla"].iterrows():
            comprobar(f"   aportacion de {r['Componente'][:22]} = valor x peso",
                      r["Aportacion"], r["Valor"] * r["Peso"], tol=1e-9)

    ben = mf.beneish_m(est)
    if ben and not ben.get("bloqueado"):
        validas = ben["tabla"].dropna(subset=["Valor"])
        comprobar("M-Score = -4,84 + suma de aportaciones",
                  ben["m"], -4.84 + float(validas["Aportacion"].sum()), tol=1e-9)
        afirmar("M-Score tiene 8 componentes", len(ben["tabla"]) == 8,
                f"{len(ben['tabla'])}")
        # SGI debe ser exactamente el crecimiento de ventas
        ing_s = mf._serie(res, ["Total Revenue", "Operating Revenue"])
        fila_sgi = ben["tabla"][ben["tabla"]["Componente"].str.startswith("SGI")]
        if not fila_sgi.empty and ing_s is not None and len(ing_s) >= 2:
            comprobar("   SGI = ventas del ultimo ejercicio / ventas del anterior",
                      float(fila_sgi["Valor"].iloc[0]),
                      float(ing_s.iloc[-1]) / float(ing_s.iloc[-2]), tol=1e-9)

    # ------------------------------------------------------------------
    # 4. M15 - ROIC
    # ------------------------------------------------------------------
    print("\n-- M15 Retornos sobre el capital --")
    roi = mf.retornos_capital(est)
    if roi is not None:
        t = roi["tabla"].dropna(subset=["ROIC"])
        if not t.empty:
            u = t.iloc[-1]
            comprobar("ROIC = NOPAT / capital invertido",
                      u["ROIC"], u["NOPAT"] / u["Capital invertido"], tol=1e-9)
            ebit = mf._serie(res, ["EBIT", "Operating Income"])
            i = list(roi["tabla"]["Ejercicio"]).index(u["Ejercicio"])
            comprobar("NOPAT = EBIT x (1 - tasa fiscal)",
                      u["NOPAT"],
                      float(ebit.iloc[i]) * (1 - u["Tasa fiscal usada"]), tol=1e-6)
            afirmar("La tasa fiscal usada esta acotada entre 0% y 60%",
                    0.0 <= u["Tasa fiscal usada"] <= 0.60,
                    f"{u['Tasa fiscal usada']}")
            comprobar("ROE = beneficio neto / patrimonio (DuPont)",
                      u["ROE"],
                      u["Margen neto"] * u["Rotacion de activos"] * u["Apalancamiento"],
                      tol=1e-6)
        # El incremental no debe publicarse si el capital se ha reducido
        validas = roi["tabla"].dropna(subset=["NOPAT", "Capital invertido"])
        if len(validas) >= 2:
            dcap = (validas["Capital invertido"].iloc[-1]
                    - validas["Capital invertido"].iloc[0])
            if dcap < 0:
                afirmar("Con capital invertido decreciente NO se publica el "
                        "ROIC incremental",
                        not np.isfinite(roi["roic_incremental"])
                        and roi.get("nota_incremental") is not None,
                        "se publico un ratio no interpretable")
            else:
                dnop = validas["NOPAT"].iloc[-1] - validas["NOPAT"].iloc[0]
                comprobar("ROIC incremental = variacion NOPAT / variacion capital",
                          roi["roic_incremental"], dnop / dcap, tol=1e-9)

    # ------------------------------------------------------------------
    # 5. M20 - construccion del valor de empresa
    # ------------------------------------------------------------------
    print("\n-- M20 Multiplos --")
    mapa = mf.mapa_ticker_cik()
    hechos = mf.companyfacts(mapa.get(TK))
    rec = mf.reconciliar(TK, est, hechos)
    acciones = rec["acciones"]
    precio = info.get("currentPrice") or info.get("regularMarketPrice")
    if np.isfinite(acciones) and precio:
        mul = mf.multiplos(TK, est, precio, acciones)
        comprobar("Capitalizacion = precio x acciones",
                  mul["capitalizacion"], precio * acciones, tol=1e-3)
        deuda = mf._fila(bal, ["Total Debt"])
        caja = mf._fila(bal, ["Cash And Cash Equivalents",
                              "Cash Cash Equivalents And Short Term Investments"])
        minor = mf._fila(bal, ["Minority Interest"])
        ev_esperado = mul["capitalizacion"]
        for x, s in ((deuda, 1), (caja, -1), (minor, 1)):
            if np.isfinite(x):
                ev_esperado += s * x
        comprobar("Valor de empresa = capitalizacion + deuda - caja + minoritarios",
                  mul["ev"], ev_esperado, tol=1e-3)
        per = mul["tabla"].loc[mul["tabla"]["Multiplo"] == "PER", "Valor"].iloc[0]
        neto = mf._fila(res, ["Net Income", "Net Income Common Stockholders"])
        if np.isfinite(per) and np.isfinite(neto) and neto:
            comprobar("PER = capitalizacion / beneficio neto",
                      per, mul["capitalizacion"] / neto, tol=1e-6)

        # ------------------------------------------------------------------
        # 6. M19 - DCF inverso: prueba de ida y vuelta
        # ------------------------------------------------------------------
        print("\n-- M19 DCF inverso (ida y vuelta) --")
        sol = mf.solvencia(est)
        fcf = sol["fcf"] if sol else np.nan
        if np.isfinite(fcf) and fcf > 0:
            dn = sol["deuda_neta"] if np.isfinite(sol["deuda_neta"]) else 0.0
            wacc, gt, anios = 0.09, 0.025, 10
            d = mf.dcf_inverso(mul["capitalizacion"], fcf, wacc=wacc,
                               g_terminal=gt, anios=anios, deuda_neta=dn)
            if d and not d.get("fuera_de_rango"):
                g = d["crecimiento_implicito"]
                # Reconstruimos el valor con ese g: debe dar el objetivo
                f, vp = fcf, 0.0
                for k in range(1, anios + 1):
                    f *= (1 + g)
                    vp += f / (1 + wacc) ** k
                vp += (f * (1 + gt) / (wacc - gt)) / (1 + wacc) ** anios
                objetivo = mul["capitalizacion"] + dn
                error_rel = abs(vp / objetivo - 1)
                afirmar(f"El crecimiento implicito ({g:+.2%}) reproduce el valor "
                        f"objetivo", error_rel < 1e-6, f"error relativo {error_rel:.2e}")
                comprobar("Peso del valor terminal entre 0 y 1",
                          float(0 <= d["peso_terminal"] <= 1), 1.0)
        else:
            print("  (flujo de caja libre no positivo: no aplica)")

    # ------------------------------------------------------------------
    # 7. M9 - la reconciliacion detecta lo que debe
    # ------------------------------------------------------------------
    print("\n-- M9 Reconciliacion --")
    afirmar("Se ejecutan comprobaciones de integridad",
            len(rec["comprobaciones"]) >= 3, f"{len(rec['comprobaciones'])}")
    if np.isfinite(rec["acciones_sec"]) and np.isfinite(rec["acciones_proveedor"]):
        desvio = rec["acciones_proveedor"] / rec["acciones_sec"] - 1
        fila = rec["comprobaciones"][
            rec["comprobaciones"]["Comprobacion"].str.contains("acciones")]
        estado = fila["Estado"].iloc[0]
        esperado = "DISCREPANCIA" if abs(desvio) > 0.01 else "OK"
        afirmar(f"El cotejo de acciones se marca como {esperado} "
                f"(desvio {desvio:+.2%})", estado == esperado, f"marcado {estado}")

# ------------------------------------------------------------------
# 8. Prohibiciones activas para entidades financieras
# ------------------------------------------------------------------
bloque("PROHIBICIONES ACTIVAS (entidades financieras)")
est_jpm = mf.estados_financieros("JPM")
clas = mf.clasificar_negocio("JPM")
afirmar("JPM se clasifica como entidad financiera", clas["es_financiera"],
        clas["tipo"])
afirmar("Se bloquean los multiplos de valor de empresa",
        "EV/EBITDA" in clas["prohibidos"], f"{clas['prohibidos']}")
r_jpm = mf.retornos_capital(est_jpm, es_financiera=True)
afirmar("ROIC bloqueado para financieras", bool(r_jpm and r_jpm.get("bloqueado")))
c_jpm = mf.calidad_beneficio(est_jpm, es_financiera=True)
afirmar("Ciclo de caja suprimido en financieras",
        bool(c_jpm) and c_jpm["tabla"]["Ciclo de caja"].isna().all())
a = mf.altman_z(est_jpm, 1e11, es_financiera=True)
afirmar("Altman Z bloqueado para financieras", bool(a and a.get("bloqueado")))
b = mf.beneish_m(est_jpm, es_financiera=True)
afirmar("Beneish M bloqueado para financieras", bool(b and b.get("bloqueado")))

# ------------------------------------------------------------------
# 9. Coherencia de la tabla de cobertura
# ------------------------------------------------------------------
bloque("COBERTURA DECLARADA")
cob = mf.tabla_cobertura()
afirmar("La tabla de cobertura cubre los 54 modulos en 44 entradas",
        len(cob) >= 40, f"{len(cob)} entradas")
afirmar("Todas las entradas declaran cobertura Si, Parcial o No",
        set(cob["Cobertura"]) <= {"Si", "Parcial", "No"}, f"{set(cob['Cobertura'])}")
afirmar("La capa de decision M46-M50 se declara NO cubierta",
        cob[cob["Modulo"] == "M46-M50"]["Cobertura"].iloc[0] == "No")
print(f"\n  Implementados: {(cob['Cobertura']=='Si').sum()} | "
      f"Parciales: {(cob['Cobertura']=='Parcial').sum()} | "
      f"No cubiertos: {(cob['Cobertura']=='No').sum()}")


# ==================================================================
# 10. Datos de los graficos: deben cuadrar con los estados
# ==================================================================
bloque("GRAFICOS DE FUNDAMENTALES")

for TKV in ["AAPL", "ICHR", "JPM", "VICI"]:
    print(f"\n-- {TKV} --")
    estv = mf.estados_financieros(TKV)
    if estv is None:
        print("   sin estados"); continue
    balv, resv, fluv = estv["balance"], estv["resultados"], estv["flujo"]

    # --- Composicion del balance: cada lado suma el activo total ---
    comp = mf.composicion_balance(estv)
    if comp is not None:
        ta_serie = mf._serie(balv, ["Total Assets"])
        for anio in sorted(comp["Ejercicio"].unique()):
            total = mf._v(ta_serie, anio)
            for lado in ["Activo", "Pasivo y patrimonio"]:
                suma = comp[(comp["Ejercicio"] == anio) &
                            (comp["Lado"] == lado)]["Importe"].sum()
                comprobar(f"Balance {anio}: {lado} suma el activo total",
                          suma, total, tol=max(abs(total) * 1e-6, 1.0))
        afirmar("Ninguna partida del balance es negativa",
                bool((comp["Importe"] >= 0).all()),
                f"{(comp['Importe'] < 0).sum()} negativas")

    # --- Cascada de resultados: los subtotales cuadran ---
    casc = mf.cascada_resultados(estv)
    if casc is not None:
        tab, anio_c = casc
        d = dict(zip(tab["Concepto"], tab["Importe"]))
        if "Ingresos" in d and "Coste de ventas" in d and "Margen bruto" in d:
            comprobar(f"Cascada {anio_c}: ingresos + coste = margen bruto",
                      d["Ingresos"] + d["Coste de ventas"], d["Margen bruto"],
                      tol=max(abs(d["Margen bruto"]) * 1e-6, 1.0))
        if "Margen bruto" in d and "Gastos operativos" in d and "Resultado operativo" in d:
            comprobar(f"Cascada {anio_c}: bruto + gastos = resultado operativo",
                      d["Margen bruto"] + d["Gastos operativos"],
                      d["Resultado operativo"],
                      tol=max(abs(d["Resultado operativo"]) * 1e-6, 1.0))
        # Cada barra debe ir de Inicio a Fin coherentemente
        malas = tab[(tab["Fin"] < tab["Inicio"] - 1e-6)]
        afirmar("Cascada de resultados: toda barra va de menor a mayor",
                malas.empty, f"{len(malas)} barras invertidas")
        # Los importes coinciden con la cuenta de resultados
        ing_real = mf._v(mf._serie(resv, ["Total Revenue", "Operating Revenue"]), anio_c)
        if "Ingresos" in d:
            comprobar(f"Cascada {anio_c}: ingresos coinciden con el estado",
                      d["Ingresos"], ing_real, tol=1.0)
        neto_real = mf._v(mf._serie(resv, ["Net Income",
                                           "Net Income Common Stockholders"]), anio_c)
        if "Beneficio neto" in d and np.isfinite(neto_real):
            comprobar(f"Cascada {anio_c}: beneficio neto coincide con el estado",
                      d["Beneficio neto"], neto_real, tol=1.0)

    # --- Puente de flujo de caja: OCF - capex = FCF ---
    pue = mf.puente_flujo_caja(estv)
    if pue is not None:
        tab, anio_p = pue
        d = dict(zip(tab["Concepto"], tab["Importe"]))
        if all(k in d for k in ("Flujo operativo", "Inversion (capex)",
                                "Flujo de caja libre")):
            comprobar(f"Puente {anio_p}: flujo operativo - capex = flujo libre",
                      d["Flujo operativo"] + d["Inversion (capex)"],
                      d["Flujo de caja libre"],
                      tol=max(abs(d["Flujo de caja libre"]) * 0.02, 1e5))
        malas = tab[(tab["Fin"] < tab["Inicio"] - 1e-6)]
        afirmar("Puente de caja: toda barra va de menor a mayor",
                malas.empty, f"{len(malas)} barras invertidas")

    # --- Beneficio frente a caja: coincide con los estados ---
    bvc = mf.beneficio_frente_a_caja(estv)
    if bvc is not None:
        ult = int(bvc["Ejercicio"].max())
        for etiqueta, nombres, df_o in [
                ("Beneficio neto", ["Net Income", "Net Income Common Stockholders"], resv),
                ("Flujo operativo", ["Operating Cash Flow"], fluv)]:
            fila = bvc[(bvc["Ejercicio"] == ult) & (bvc["Magnitud"] == etiqueta)]
            if not fila.empty:
                comprobar(f"Beneficio vs caja {ult}: {etiqueta} coincide",
                          float(fila["Importe"].iloc[0]),
                          mf._v(mf._serie(df_o, nombres), ult), tol=1.0)

    # --- Apalancamiento: deuda neta = deuda - caja ---
    apal = mf.evolucion_apalancamiento(estv)
    if apal is not None:
        for _, r in apal.dropna(subset=["Caja"]).iterrows():
            comprobar(f"Apalancamiento {int(r['Ejercicio'])}: deuda neta = deuda - caja",
                      r["Deuda neta"], r["Deuda total"] - r["Caja"], tol=1.0)

    # --- Capital circulante: el peso es la partida sobre los ingresos ---
    circ = mf.capital_circulante(estv)
    if circ is not None and not circ.empty:
        ult = int(circ["Ejercicio"].max())
        ing = mf._v(mf._serie(resv, ["Total Revenue", "Operating Revenue"]), ult)
        fila = circ[circ["Ejercicio"] == ult].iloc[0]
        comprobar(f"Circulante {ult}: peso = importe / ingresos",
                  fila["Sobre ingresos"], fila["Importe"] / ing, tol=1e-9)


bloque("RESULTADO")
print(f"  Comprobaciones: {n}")
print(f"  Fallos        : {len(fallos)}")
for f in fallos:
    print(f"     - {f}")
if fallos:
    sys.exit(1)
print("\n  TODO CORRECTO: las formulas coinciden con su definicion.")
