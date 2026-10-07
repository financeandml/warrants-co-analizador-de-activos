# Analizador de Activos — Warrants & Co.

Aplicación web local (Streamlit) de análisis cuantitativo de un activo cotizado:
riesgo, rentabilidad, simulación, fundamentales, valoración por descuento de
flujos y cribado del S&P 500. Se ejecuta en tu equipo, en `http://localhost:8510`.

> Herramienta de análisis cuantitativo descriptivo. Todas las cifras se calculan
> sobre datos históricos y describen el comportamiento pasado del activo; no
> constituyen una previsión ni una recomendación de inversión.

## Arranque rápido (Windows)

1. Instala **Python 3.12 o superior** (verificado con 3.13 y 3.14) desde <https://www.python.org/downloads/>
   y marca la casilla *Add python.exe to PATH*.
2. Descarga el repositorio:
   ```
   git clone https://github.com/financeandml/warrants-co-analizador-de-activos.git
   ```
   o, sin git, *Code → Download ZIP* en GitHub y descomprímelo.
3. Doble clic en **`Analizador Web.bat`**.

La primera vez crea un entorno propio en `.venv` e instala las librerías de
`requirements.txt` (unos minutos). Las siguientes arranca en segundos. El
navegador se abre solo; para parar el servidor, `Ctrl+C` en la ventana negra.

## Arranque manual (cualquier sistema)

```
python -m venv .venv
.venv\Scripts\activate          # macOS / Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app_analizador.py
```

El puerto 8510 se fija en `.streamlit/config.toml`.

## Qué hace

Barra lateral: buscador de empresas por nombre, histórico (1 a 10 años o
máximo), confianza del VaR/CVaR, capital, índice de comparación y umbral de
movimiento extremo. Cabecera con precio, volatilidad, VaR, CVaR, Sharpe,
Sortino, drawdown máximo y Calmar.

| Pestaña | Contenido |
|---|---|
| Resumen | Vista general y **informe completo en PDF** (A4 imprimible) |
| Gráfico | Cotización de 1 minuto a 1 día, con pre y postmercado y volumen |
| Precio y retornos | Serie de precios y distribución de retornos |
| Monte Carlo | Simulación de trayectorias de precio |
| Riesgo VaR/CVaR | VaR histórico y paramétrico, CVaR e impacto sobre el capital |
| Earnings | Última y próxima publicación de resultados, reacción del precio a cada una y si la sorpresa explica el movimiento |
| Movimientos extremos | Reversión a la media tras caídas fuertes |
| Volumen | Volumen frente a retornos: si los movimientos grandes vienen con más volumen |
| Selección de valores | Cribado del S&P 500, descomposición factorial, régimen y origen de la caída |
| Opciones y microestructura | Cadena de opciones del día y sesiones intradía |
| Comparativa | Activo contra el índice de comparación |
| Fundamentales | Estados financieros, calidad del beneficio, riesgo contable, retornos sobre el capital, crecimiento y márgenes, solvencia, flujo de caja, valoración relativa, DCF inverso, segmentos y geografía |
| DCF | Cinco métodos de valoración (FCFF, FCFE, DDM, APV, EVA) y **exportación a Excel** |

## Fuentes de datos

Hace falta conexión a internet: los datos se descargan en cada consulta, no se
guardan en el repositorio.

- **Yahoo Finance** (librería `yfinance`): precios, opciones, resultados y estados financieros.
- **SEC EDGAR**: fundamentales y segmentos de empresas estadounidenses.
- **Wikipedia**: composición actual del S&P 500, para el cribado.
- **Kenneth French Data Library**: factores para la descomposición factorial.

La SEC exige un correo de contacto en cada petición. El código lleva uno por
defecto; para usar el tuyo, define la variable de entorno `SEC_CONTACTO` y
arranca desde esa misma ventana (en Windows: `set SEC_CONTACTO=tu@correo.com`
y después `"Analizador Web.bat"`).

## Estructura

| Fichero | Papel |
|---|---|
| `app_analizador.py` | La app web: barra lateral, cabecera y pestañas |
| `motor_*.py` | Cálculo, sin interfaz: análisis, cribado, DCF, factores, fundamentales, gráfico, informe, mercado, origen, régimen, segmentos, validación |
| `pestana_*.py`, `bloque_informe.py`, `bloques_cribado.py` | Interfaz de cada pestaña |
| `informe_*.py`, `partidas_contables.py` | Composición del informe PDF |
| `verificar_*.py`, `auditar_fundamentales.py` | Baterías de verificación del motor (ver abajo) |
| `ANALIZADOR DE ACTIVOS.py` | Script original de consola en el que se basa el motor |
| `ANALIZADOR DE ACTIVOS INTERACTIVO.py` | Versión de consola que pregunta el ticker; se abre con `Analizador de Activos.bat` |

## Verificación

Con el entorno activado:

```
python verificar_fidelidad.py         # motor de la web contra el script original
python verificar_fundamentales.py     # corrección del motor de fundamentales
python verificar_estrategia.py        # módulos de análisis complementario
python verificar_sp500.py 4           # barrido sobre N valores por sector del S&P 500
python auditar_fundamentales.py 15    # integridad de fundamentales sobre N empresas
```
