
echo off
rem ---------------------------------------------------------------------
rem  Lanzador del ANALIZADOR DE ACTIVOS
rem  Doble clic aqui (o en el acceso directo del Escritorio) para abrirlo.
rem  Tiene que estar en la MISMA carpeta que el .py
rem ---------------------------------------------------------------------
setlocal
chcp 65001 >nul
title Analizador de Activos
cd /d "%~dp0"

set "SCRIPT=ANALIZADOR DE ACTIVOS INTERACTIVO.py"

if not exist "%SCRIPT%" goto :sin_script

rem Si ya existe el entorno que prepara "Analizador Web.bat", se usa: tiene todas
rem las librerias de requirements.txt, y el Python global puede no tenerlas.
if exist ".venv\Scripts\python.exe" goto :usar_venv

rem Buscar Python: primero el lanzador oficial "py", si no el "python" del PATH
where py >nul 2>nul
if %errorlevel%==0 goto :usar_py

where python >nul 2>nul
if %errorlevel%==0 goto :usar_python

goto :sin_python


:usar_venv
".venv\Scripts\python.exe" "%SCRIPT%"
goto :fin

:usar_py
py "%SCRIPT%"
goto :fin

:usar_python
python "%SCRIPT%"
goto :fin


:sin_script
echo.
echo   [ERROR] No encuentro el archivo:
echo           %SCRIPT%
echo.
echo   Este lanzador tiene que estar en la misma carpeta que el script .py
echo.
goto :fin

:sin_python
echo.
echo   [ERROR] No he encontrado Python en este equipo.
echo.
echo   Instalalo desde https://www.python.org/downloads/
echo   y marca la casilla "Add python.exe to PATH" durante la instalacion.
echo.
goto :fin


:fin
echo.
pause
endlocal
