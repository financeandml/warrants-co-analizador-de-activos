@echo off
rem ---------------------------------------------------------------------
rem  Lanzador WEB del ANALIZADOR DE ACTIVOS
rem  Doble clic aqui: levanta el servidor local y abre el navegador solo.
rem  Para cerrarlo: vuelve a esta ventana y pulsa Ctrl+C, o cierrala.
rem ---------------------------------------------------------------------
setlocal
chcp 65001 >nul
title Analizador de Activos - servidor local
cd /d "%~dp0"

set "APP=app_analizador.py"

if not exist "%APP%" goto :sin_app
if not exist "motor_analisis.py" goto :sin_motor

rem Elegir interprete: primero el lanzador oficial "py", si no el "python" del PATH.
rem "if errorlevel" y no "%errorlevel%": dentro de un bloque ( ) el segundo se
rem expande antes de ejecutar el where, y nunca encontraria "python".
set "PY="
where py >nul 2>nul
if not errorlevel 1 set "PY=py"
if not defined PY (
    where python >nul 2>nul
    if not errorlevel 1 set "PY=python"
)
if not defined PY goto :sin_python

rem Entorno propio en .venv: la primera vez se crea y se instala requirements.txt;
rem las siguientes se reutiliza y el arranque es inmediato.
if not exist ".venv\Scripts\python.exe" (
    %PY% -c "import sys; sys.exit(sys.version_info < (3, 12))" >nul 2>nul
    if errorlevel 1 goto :python_antiguo
    echo.
    echo   Primera ejecucion: preparando el entorno en .venv ^(unos minutos^)...
    %PY% -m venv .venv
    if errorlevel 1 goto :sin_entorno
)
set "PY=.venv\Scripts\python.exe"

rem Comprobar TODAS las librerias, no solo streamlit: con una sola ausente la app
rem arranca y falla despues. lxml no se importa en el codigo, pero pandas.read_html
rem la necesita para el S&P 500 y los segmentos.
%PY% -c "import streamlit, altair, plotly, numpy, pandas, scipy, yfinance, lxml, reportlab, pypdf, matplotlib, PIL, openpyxl" >nul 2>nul
if errorlevel 1 (
    echo   Instalando las librerias de requirements.txt...
    %PY% -m pip install --disable-pip-version-check -r requirements.txt
    if errorlevel 1 goto :sin_librerias
)

rem Puerto propio de este analizador. El 8501 lo ocupa la app de QUANTUM: si
rem compartieran puerto, veriamos la otra app en el navegador.
set "PUERTO=8510"

echo.
echo   Arrancando el servidor local...
echo   Se abrira solo en el navegador: http://localhost:%PUERTO%
echo.
echo   Para PARAR el servidor: pulsa Ctrl+C en esta ventana.
echo.

%PY% -m streamlit run "%APP%" --server.port %PUERTO%
if errorlevel 1 goto :puerto_ocupado
goto :fin


:puerto_ocupado
echo.
echo   [ERROR] El servidor no pudo arrancar en el puerto %PUERTO%.
echo   Lo mas probable es que ya tengas algo escuchando ahi.
echo   Cierra la otra ventana del analizador, o cambia el numero
echo   de PUERTO en este mismo archivo .bat y en .streamlit\config.toml
echo.
goto :fin


:sin_app
echo.
echo   [ERROR] No encuentro "%APP%".
echo   Este lanzador tiene que estar en la misma carpeta que la app.
echo.
goto :fin

:sin_motor
echo.
echo   [ERROR] Falta "motor_analisis.py", que es donde estan los calculos.
echo   Tiene que estar en esta misma carpeta.
echo.
goto :fin

:sin_python
echo.
echo   [ERROR] No he encontrado Python en este equipo.
echo   Instalalo desde https://www.python.org/downloads/
echo   y marca la casilla "Add python.exe to PATH".
echo.
goto :fin

:python_antiguo
echo.
echo   [ERROR] La app necesita Python 3.12 o superior.
echo   Instala uno reciente desde https://www.python.org/downloads/
echo   y marca la casilla "Add python.exe to PATH".
echo.
goto :fin

:sin_entorno
echo.
echo   [ERROR] No se pudo crear el entorno en .venv.
echo   Borra la carpeta .venv si existe a medias y vuelve a intentarlo.
echo.
goto :fin

:sin_librerias
echo.
echo   [ERROR] No se pudieron instalar las librerias.
echo   Comprueba la conexion a internet y ejecuta en esta carpeta:
echo.
echo       .venv\Scripts\python -m pip install -r requirements.txt
echo.
goto :fin


:fin
echo.
pause
endlocal
