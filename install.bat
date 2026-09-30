@echo off
chcp 65001 >nul
setlocal
title Instalador - ArcMagery v2.0.0
cls
echo ======================================================================
echo              ARCMAGERY - INSTALADOR AUTOMATIZADO (v2.0.0)
echo   Google Earth Engine, Google Earth e CBERS/INPE no ArcGIS Desktop 10.8
echo ======================================================================
echo.

set "SCRIPT_DIR=%~dp0"
set "PYTHON27=C:\Python27\ArcGIS10.8\python.exe"
set "REGADDIN=C:\Program Files (x86)\Common Files\ArcGIS\bin\ESRIRegAddIn.exe"
set "ADDIN_UUID={ceae58c4-c44e-4edd-b8f4-1ba7d13b6b7d}"
set "USER_ADDIN_DIR=%USERPROFILE%\Documents\ArcGIS\AddIns\Desktop10.8\%ADDIN_UUID%"
set "CACHE_DIR=%LOCALAPPDATA%\ESRI\Desktop10.8\AssemblyCache\%ADDIN_UUID%"
set "VENV_DIR=%LOCALAPPDATA%\ArcMagery\venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "FAILED="

:: Nunca herdar o Python 2.7 do ArcGIS no Python 3 (e vice-versa)
set "PYTHONHOME="
set "PYTHONPATH="

:: 1. ArcGIS Desktop 10.8 / Python 2.7
echo [1/5] Verificando instalacao do ArcGIS Desktop 10.8...
if not exist "%PYTHON27%" (
    echo [ALERTA] Python 2.7 do ArcGIS nao encontrado em "%PYTHON27%".
    echo          Certifique-se de que o ArcGIS Desktop 10.8 esteja instalado nesta maquina.
) else (
    echo [OK] ArcGIS Desktop 10.8 e Python 2.7 detectados.
    "%PYTHON27%" -c "import comtypes" 2>nul
    if errorlevel 1 (
        echo [OK] comtypes ausente no Python 2.7: sera usada a copia embutida no add-in ^(Installendor^).
    ) else (
        echo [OK] Modulo comtypes disponivel no Python 2.7.
    )
)

:: 2. Python 3 do backend. NAO precisa de pip nem de venv: o Python do QGIS ja traz GDAL, numpy e
::    Pillow, e o earthengine-api e baixado com os certificados do Windows (funciona com o proxy de
::    inspecao SSL) para %LOCALAPPDATA%\ArcMagery\pylibs (backend\pylibs.py). Um venv antigo e mantido.
echo.
echo [2/5] Preparando o Python 3 do backend...
set "BASE_PY="
:: 2a. Preferencia: Python do QGIS/OSGeo4W (ja traz GDAL, numpy e Pillow - necessarios ao CBERS e SPOT)
for /d %%D in ("C:\Program Files\QGIS 3*" "C:\OSGeo4W" "C:\OSGeo4W64") do (
    for /d %%P in ("%%~D\apps\Python3*") do (
        if exist "%%~P\python.exe" set "BASE_PY=%%~P\python.exe"
    )
)
:: 2b. Alternativa: Python 3 oficial (CBERS e SPOT exigirao GDAL; Google Earth funciona com Pillow)
if not defined BASE_PY for %%P in ("%LOCALAPPDATA%\Programs\Python\Python312\python.exe" "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" "C:\Python312\python.exe" "C:\Python311\python.exe" "C:\Python310\python.exe") do (
    if not defined BASE_PY if exist "%%~P" set "BASE_PY=%%~P"
)
set "PY3=%BASE_PY%"
:: venv antigo so e usado se ainda abrir (um venv quebrado e tirado de uso pelo diagnostico)
if exist "%VENV_PY%" "%VENV_PY%" -c "import sys" >nul 2>nul && set "PY3=%VENV_PY%"
if not defined PY3 (
    echo [ERRO] Nenhum Python 3 encontrado ^(QGIS 3.x^).
    echo        Instale o QGIS 3.x ^(recomendado: 3.34 LTR ou mais novo^) e execute este instalador novamente.
    set "FAILED=1"
    goto :step3
)
echo [INFO] Python 3: %PY3%
set "BACKEND=%SCRIPT_DIR%arcgis_addin\Install\backend"
set "PYTHONIOENCODING=utf-8"
echo.
echo [DIAGNOSTICO] Verificando o ambiente e corrigindo o que for possivel ^(~20 s^)...
echo ----------------------------------------------------------------------
"%PY3%" "%BACKEND%\run_gee.py" doctor --text "--install-path=%SCRIPT_DIR%"
if errorlevel 1 (
    echo ----------------------------------------------------------------------
    echo [ATENCAO] O diagnostico encontrou problemas ^(veja "o que fazer" acima^).
    echo           O relatorio completo esta em %LOCALAPPDATA%\ArcMagery\diagnostico.txt
    set "FAILED=1"
) else (
    echo ----------------------------------------------------------------------
)
:step3
:: 3. Empacotar o Add-in (backend autocontido em arcgis_addin\Install\backend)
echo.
echo [3/5] Empacotando Add-in autocontido (.esriaddin)...
if exist "%PYTHON27%" (
    pushd "%SCRIPT_DIR%arcgis_addin"
    "%PYTHON27%" makeaddin.py
    if errorlevel 1 set "FAILED=1"
    popd
)
if not exist "%SCRIPT_DIR%arcgis_addin\GEE_Image_Selector.esriaddin" (
    echo [ERRO] Pacote GEE_Image_Selector.esriaddin nao foi gerado.
    set "FAILED=1"
    goto :summary
)

:: 4. Instalar o Add-In no diretorio oficial do ArcGIS Desktop 10.8
echo.
echo [4/5] Instalando Add-In no ArcGIS Desktop...
if not exist "%USER_ADDIN_DIR%" mkdir "%USER_ADDIN_DIR%"
copy /Y "%SCRIPT_DIR%arcgis_addin\GEE_Image_Selector.esriaddin" "%USER_ADDIN_DIR%\" >nul
if errorlevel 1 set "FAILED=1"

:: Atualizar o AssemblyCache (inclusive a subpasta backend) para evitar codigo antigo em cache
if exist "%CACHE_DIR%" (
    del /S /Q /F "%CACHE_DIR%\*.pyc" >nul 2>nul
    xcopy /S /E /Y /I /Q "%SCRIPT_DIR%arcgis_addin\Install\*" "%CACHE_DIR%\" >nul
    if errorlevel 1 set "FAILED=1"
    copy /Y "%SCRIPT_DIR%arcgis_addin\config.xml" "%CACHE_DIR%\" >nul
)

if exist "%REGADDIN%" "%REGADDIN%" /s "%SCRIPT_DIR%arcgis_addin\GEE_Image_Selector.esriaddin"

:: 5. Caixa de ferramentas ArcToolbox
echo.
echo [5/5] Registrando Caixa de Ferramentas ArcToolbox (.pyt)...
set "USER_TOOLBOX_DIR=%USERPROFILE%\Documents\ArcGIS"
if not exist "%USER_TOOLBOX_DIR%" mkdir "%USER_TOOLBOX_DIR%"
copy /Y "%SCRIPT_DIR%pyt\GEE_Tools.pyt" "%USER_TOOLBOX_DIR%\" >nul

:summary
echo.
echo ======================================================================
if defined FAILED (
    echo      INSTALACAO CONCLUIDA COM ERROS - revise as mensagens acima.
    echo ======================================================================
    pause
    exit /b 1
)
echo              INSTALACAO CONCLUIDA COM SUCESSO!
echo ======================================================================
echo.
echo PASSOS PARA USAR NO ARCMAP:
echo   1. Abra o ArcMap 10.8.
echo   2. Menu Customize ^> Toolbars: marque "ArcMagery".
echo   3. Clique no botao "ArcMagery" da barra de ferramentas.
echo   4. Google Earth Engine: clique em "Configurar Projeto GEE" e informe seu Project ID.
echo   5. Google Earth e CBERS/INPE: botao "Google Earth / CBERS" no topo da janela.
echo.
echo Para autenticar o GEE agora, execute: autenticar_gee.bat
echo.
pause
exit /b 0
