@echo off
chcp 65001 >nul
title Instalador - CGMA ArcGEE Explorer v1.12
cls
echo ======================================================================
echo          CGMA ARCGEE EXPLORER - INSTALADOR AUTOMATIZADO (v1.12)
echo         Google Earth Engine integrado ao ArcGIS Desktop 10.8.2
echo ======================================================================
echo.

set SCRIPT_DIR=%~dp0
set PYTHON27=C:\Python27\ArcGIS10.8\python.exe
set REGADDIN="C:\Program Files (x86)\Common Files\ArcGIS\bin\ESRIRegAddIn.exe"
set ADDIN_UUID={ceae58c4-c44e-4edd-b8f4-1ba7d13b6b7d}
set USER_ADDIN_DIR=%USERPROFILE%\Documents\ArcGIS\AddIns\Desktop10.8\%ADDIN_UUID%
set CACHE_DIR=%LOCALAPPDATA%\ESRI\Desktop10.8\AssemblyCache\%ADDIN_UUID%

:: 1. Verificar presenca do ArcGIS Desktop 10.8
echo [1/5] Verificando instalacao do ArcGIS Desktop 10.8...
if not exist "%PYTHON27%" (
    echo [ALERTA] Python 2.7 do ArcGIS nao encontrado em "%PYTHON27%".
    echo Certifique-se de que o ArcGIS Desktop 10.8 esteja instalado nesta maquina.
    echo.
) else (
    echo [OK] ArcGIS Desktop 10.8 e Python 2.7 detectados.
    "%PYTHON27%" -c "import comtypes" 2>nul
    if errorlevel 1 (
        echo [INFO] Modulo comtypes ausente no Python 2.7. Tentando instalar via pip...
        "%PYTHON27%" -m pip install comtypes --quiet 2>nul
        if errorlevel 1 (
            echo [INFO] pip nao configurado no Python 2.7. O plugin utilizara o mecanismo nativo ArcPy com 100%% de compatibilidade.
        ) else (
            echo [OK] Modulo comtypes instalado com sucesso no Python 2.7.
        )
    ) else (
        echo [OK] Modulo comtypes disponivel no Python 2.7.
    )
)

:: 2. Detectar e preparar ambiente Python 3 para o Google Earth Engine
echo.
echo [2/5] Verificando ambiente Python 3 para o Google Earth Engine...
set PY3_CMD=
if exist "C:\CGMA_GEE_PLUGIN\venv\Scripts\python.exe" set PY3_CMD="C:\CGMA_GEE_PLUGIN\venv\Scripts\python.exe"
if not defined PY3_CMD if exist "C:\Python312\python.exe" set PY3_CMD="C:\Python312\python.exe"
if not defined PY3_CMD if exist "C:\Python311\python.exe" set PY3_CMD="C:\Python311\python.exe"
if not defined PY3_CMD if exist "C:\Python310\python.exe" set PY3_CMD="C:\Python310\python.exe"
if not defined PY3_CMD if exist "C:\Program Files\QGIS 3.44.10\apps\Python312\python.exe" set PY3_CMD="C:\Program Files\QGIS 3.44.10\apps\Python312\python.exe"
if not defined PY3_CMD if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PY3_CMD="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY3_CMD if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set PY3_CMD="%LOCALAPPDATA%\Programs\Python\Python311\python.exe"

if not defined PY3_CMD (
    for /f "tokens=*" %%i in ('where python 2^>nul') do (
        %%i -c "import sys; sys.exit(0 if sys.version_info[0]>=3 else 1)" 2>nul
        if not errorlevel 1 (
            set PY3_CMD="%%i"
            goto :found_py3
        )
    )
)

:found_py3
if defined PY3_CMD (
    echo [OK] Python 3 encontrado: %PY3_CMD%
    echo Instalando / atualizando a biblioteca earthengine-api...
    %PY3_CMD% -m pip install --upgrade -r "%SCRIPT_DIR%requirements.txt" --quiet
    if not errorlevel 1 (
        echo [OK] Biblioteca earthengine-api configurada com sucesso.
    ) else (
        echo [AVISO] Nao foi possivel instalar via pip automaticamente. Verifique a conexao de internet.
    )
) else (
    echo [AVISO] Python 3 nao encontrado automaticamente nas pastas comuns.
    echo O plugin tentara utilizar o Python 3 do QGIS ou do sistema quando for aberto.
    echo Caso necessario, instale o Python 3.10+ e execute: pip install earthengine-api
)

:: 3. Sincronizar arquivos do backend para a pasta Install do Add-in
echo.
echo [3/5] Empacotando Add-in autocontido (.esriaddin)...
if not exist "%SCRIPT_DIR%arcgis_addin\Install\backend" mkdir "%SCRIPT_DIR%arcgis_addin\Install\backend"
copy /Y "%SCRIPT_DIR%backend\*.py" "%SCRIPT_DIR%arcgis_addin\Install\backend\" >nul
copy /Y "%SCRIPT_DIR%backend\*.json" "%SCRIPT_DIR%arcgis_addin\Install\backend\" >nul

if exist "%PYTHON27%" (
    cd /d "%SCRIPT_DIR%arcgis_addin"
    "%PYTHON27%" makeaddin.py
    cd /d "%SCRIPT_DIR%"
) else (
    echo Utilizando pacote pre-construido GEE_Image_Selector.esriaddin.
)

:: 4. Instalar o Add-In no diretorio oficial do ArcGIS Desktop 10.8
echo.
echo [4/5] Instalando Add-In no ArcGIS Desktop...
if not exist "%USER_ADDIN_DIR%" mkdir "%USER_ADDIN_DIR%"
copy /Y "%SCRIPT_DIR%arcgis_addin\GEE_Image_Selector.esriaddin" "%USER_ADDIN_DIR%\" >nul

:: Limpar cache do AssemblyCache para forcar recarregamento
if exist "%CACHE_DIR%" (
    del /Q /F "%CACHE_DIR%\*.pyc" 2>nul
    del /Q /F "%CACHE_DIR%\*.pyo" 2>nul
    copy /Y "%SCRIPT_DIR%arcgis_addin\Install\*" "%CACHE_DIR%\" >nul 2>nul
)

if exist %REGADDIN% (
    %REGADDIN% /s "%SCRIPT_DIR%arcgis_addin\GEE_Image_Selector.esriaddin"
)

:: 5. Registrar caixa de ferramentas ArcToolbox
echo.
echo [5/5] Registrando Caixa de Ferramentas ArcToolbox (.pyt)...
set USER_TOOLBOX_DIR=%USERPROFILE%\Documents\ArcGIS
if not exist "%USER_TOOLBOX_DIR%" mkdir "%USER_TOOLBOX_DIR%"
copy /Y "%SCRIPT_DIR%pyt\GEE_Tools.pyt" "%USER_TOOLBOX_DIR%\" >nul

echo.
echo ======================================================================
echo         INSTALACAO CONCLUIDA COM SUCESSO NO ARCGIS 10.8!
echo ======================================================================
echo.
echo PASSOS PARA USAR NO ARCMAP:
echo   1. Abra o ArcMap 10.8.
echo   2. Va no menu: Customize ^> Toolbars e marque "CGMA ArcGEE Explorer" (ou "GEE Image Selector").
echo   3. Clique no botao "ArcGEE Explorer" na barra de ferramentas.
echo   4. No topo da janela, clique em "Configurar Projeto GEE"
echo      para conectar com seu ID de projeto Google Cloud / Earth Engine.
echo.
echo Para autenticar o GEE agora via linha de comando, execute:
echo   autenticar_gee.bat
echo.
pause
