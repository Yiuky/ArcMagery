@echo off
setlocal
:: ==========================================================================
::  run_tests.bat - Executa as duas suites de testes do ArcMagery
::    1) tests\backend  (Python 3 do backend: venv do ArcMagery ou Python do QGIS)
::    2) tests\arcmap   (Python 2.7 do ArcGIS: ponte, GUI, atualizador)
::  Opcional: set ARCMAGERY_LIVE=1 (internet) e ARCMAGERY_GEE_PROJECT=<id> (Earth Engine)
:: ==========================================================================
cd /d "%~dp0"
set "PYTHONHOME="
set "PYTHONPATH="
set "RC=0"

set "PY3="
if exist "%LOCALAPPDATA%\ArcMagery\venv\Scripts\python.exe" set "PY3=%LOCALAPPDATA%\ArcMagery\venv\Scripts\python.exe"
if not defined PY3 for /d %%D in ("C:\Program Files\QGIS 3*") do for /d %%P in ("%%~D\apps\Python3*") do if exist "%%~P\python.exe" set "PY3=%%~P\python.exe"
set "PY2=C:\Python27\ArcGIS10.8\python.exe"

echo === Suite backend (Python 3): %PY3%
if not defined PY3 (
    echo [ERRO] Python 3 nao encontrado ^(rode install.bat^).
    set "RC=1"
) else (
    "%PY3%" tests\backend\run_all.py %*
    if errorlevel 1 set "RC=1"
)

echo.
echo === Suite ArcMap/GUI (Python 2.7): %PY2%
if not exist "%PY2%" (
    echo [ERRO] Python 2.7 do ArcGIS nao encontrado.
    set "RC=1"
) else (
    "%PY2%" tests\arcmap\run_all.py %*
    if errorlevel 1 set "RC=1"
)

echo.
if "%RC%"=="0" (echo TODOS OS TESTES PASSARAM) else (echo HA FALHAS NOS TESTES)
exit /b %RC%
