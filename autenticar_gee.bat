@echo off
chcp 65001 >nul
setlocal
title Autenticação - Google Earth Engine (ArcMagery)
cls
echo ======================================================================
echo           AUTENTICADOR DO GOOGLE EARTH ENGINE - ARCMAGERY
echo ======================================================================
echo.
echo Este utilitário vai abrir o seu navegador para conectar sua conta Google
echo ao Google Earth Engine e gerar as credenciais locais.
echo.

set "PYTHONHOME="
set "PYTHONPATH="
set "PY3_CMD="
:: 1. venv do ArcMagery (instalacoes antigas); 2. Python do QGIS (o earthengine-api vem do pylibs)
if exist "%LOCALAPPDATA%\ArcMagery\venv\Scripts\python.exe" set "PY3_CMD=%LOCALAPPDATA%\ArcMagery\venv\Scripts\python.exe"
if not defined PY3_CMD for /d %%D in ("C:\Program Files\QGIS 3*" "C:\OSGeo4W" "C:\OSGeo4W64") do (
    for /d %%P in ("%%~D\apps\Python3*") do if exist "%%~P\python.exe" set "PY3_CMD=%%~P\python.exe"
)
if not defined PY3_CMD (
    echo [ERRO] Python 3 nao encontrado. Instale o QGIS 3.x e execute o install.bat.
    pause
    exit /b 1
)
set "AUTH=%~dp0arcgis_addin\Install\backend\ee_auth.py"
echo Python 3 detectado: %PY3_CMD%
echo.
:: ee_auth.py instala os componentes sozinho se faltarem, abre o navegador e testa a conexao
"%PY3_CMD%" "%AUTH%"
echo.
pause
exit /b 0
