@echo off
chcp 65001 >nul
setlocal
title Autenticacao - Google Earth Engine (ArcMagery)
cls
echo ======================================================================
echo           AUTENTICADOR DO GOOGLE EARTH ENGINE - ARCMAGERY
echo ======================================================================
echo.
echo Este utilitario abre o navegador para conectar a sua conta Google ao
echo Google Earth Engine e gravar as credenciais neste computador.
echo.

set "PYTHONHOME="
set "PYTHONPATH="
:: Mesmo Python 3 do instalador: venv antigo (se ainda abrir) ou o QGIS mais novo
call "%~dp0tools\find_python3.bat"
set "PY3_CMD=%PY3_FOUND%"
set "VENV_PY=%LOCALAPPDATA%\ArcMagery\venv\Scripts\python.exe"
if exist "%VENV_PY%" "%VENV_PY%" -c "import sys" >nul 2>nul && set "PY3_CMD=%VENV_PY%"
if not defined PY3_CMD (
    echo [ERRO] Python 3 nao encontrado. Instale o QGIS ^(3.18 ou mais novo^) e execute o install.bat.
    pause
    exit /b 1
)
set "AUTH=%~dp0arcgis_addin\Install\backend\ee_auth.py"
echo Python 3 detectado: %PY3_CMD%
echo.
:: ee_auth.py instala os componentes sozinho se faltarem, abre o navegador e testa a conexao
"%PY3_CMD%" "%AUTH%"
set "RC=%errorlevel%"
echo.
pause
exit /b %RC%
