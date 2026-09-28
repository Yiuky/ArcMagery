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
:: 1. venv do ArcMagery (criado pelo install.bat)
if exist "%LOCALAPPDATA%\ArcMagery\venv\Scripts\python.exe" set "PY3_CMD=%LOCALAPPDATA%\ArcMagery\venv\Scripts\python.exe"
:: 2. venvs de versoes anteriores
if not defined PY3_CMD if exist "%LOCALAPPDATA%\ArcGEE\venv\Scripts\python.exe" set "PY3_CMD=%LOCALAPPDATA%\ArcGEE\venv\Scripts\python.exe"
if not defined PY3_CMD if exist "C:\CGMA_GEE_PLUGIN\venv\Scripts\python.exe" set "PY3_CMD=C:\CGMA_GEE_PLUGIN\venv\Scripts\python.exe"

if not defined PY3_CMD (
    echo [ERRO] Ambiente Python do ArcMagery nao encontrado.
    echo        Execute primeiro o install.bat.
    pause
    exit /b 1
)

"%PY3_CMD%" -c "import ee" 2>nul
if errorlevel 1 (
    echo [ERRO] earthengine-api ausente em "%PY3_CMD%". Execute o install.bat novamente.
    pause
    exit /b 1
)

echo Python 3 detectado: %PY3_CMD%
echo.
echo Iniciando autenticacao do Google Earth Engine...
"%PY3_CMD%" -c "import ee; ee.Authenticate()"
if errorlevel 1 (
    echo.
    echo [AVISO] Tentando autenticacao via CLI earthengine...
    "%PY3_CMD%" -m ee.cli.eecli authenticate
)

echo.
echo ======================================================================
echo          VERIFICANDO CONEXAO COM O GOOGLE EARTH ENGINE...
echo ======================================================================
"%PY3_CMD%" -c "import ee; ee.Initialize(); print('SUCESSO: Conectado ao GEE!')" 2>nul
if errorlevel 1 (
    echo.
    echo [OBSERVAÇÃO] Se for solicitado um ID de Projeto Google Cloud,
    echo voce podera defini-lo diretamente na interface do ArcMap
    echo clicando no botao 'Configurar Projeto GEE' no topo da janela.
) else (
    echo.
    echo [OK] Autenticacao e Inicializacao concluidas com sucesso!
)
echo.
pause
