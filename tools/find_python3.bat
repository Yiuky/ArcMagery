@echo off
:: ==========================================================================
::  tools\find_python3.bat - encontra o Python 3 do backend (usado pelos .bat da raiz)
::    call "%~dp0tools\find_python3.bat"   ->  define PY3_FOUND (vazio se nada for encontrado)
::
::  Mesma regra do plugin (gee_bridge.python3_candidates):
::    1. variavel GEE_PYTHON3 (QGIS em pasta nao padrao: setx GEE_PYTHON3 "D:\QGIS\apps\Python312\python.exe")
::    2. QGIS / OSGeo4W, o MAIS NOVO primeiro (traz GDAL, numpy e Pillow)
::    3. Python 3 oficial (CBERS e SPOT exigirao GDAL)
:: ==========================================================================
set "PY3_FOUND="
if defined GEE_PYTHON3 if exist "%GEE_PYTHON3%" set "PY3_FOUND=%GEE_PYTHON3%"
if defined PY3_FOUND goto :eof

:: "for /d" percorre em ordem alfabetica e o ultimo encontrado vence: QGIS 3.44 depois de 3.40,
:: QGIS 4.x depois de 3.x, e o QGIS instalado em Program Files depois do OSGeo4W.
for /d %%D in ("C:\OSGeo4W" "C:\OSGeo4W64" "%ProgramFiles(x86)%\QGIS *" "%ProgramFiles%\QGIS *") do (
    for /d %%P in ("%%~D\apps\Python3*") do if exist "%%~P\python.exe" set "PY3_FOUND=%%~P\python.exe"
)
if defined PY3_FOUND goto :eof

for %%P in ("%LOCALAPPDATA%\Programs\Python\Python312\python.exe" "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" "C:\Python312\python.exe" "C:\Python311\python.exe" "C:\Python310\python.exe") do (
    if not defined PY3_FOUND if exist "%%~P" set "PY3_FOUND=%%~P"
)
goto :eof
