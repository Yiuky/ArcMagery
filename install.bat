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

:: 2. Python 3 do backend: venv PROPRIO do ArcMagery (nao altera o QGIS nem outros projetos)
echo.
echo [2/5] Preparando ambiente Python 3 isolado em "%VENV_DIR%"...
set "BASE_PY="
:: 2a. Preferencia: Python do QGIS/OSGeo4W (ja traz GDAL, numpy e Pillow - necessarios ao CBERS)
for /d %%D in ("C:\Program Files\QGIS 3*" "C:\OSGeo4W" "C:\OSGeo4W64") do (
    for /d %%P in ("%%~D\apps\Python3*") do (
        if exist "%%~P\python.exe" set "BASE_PY=%%~P\python.exe"
    )
)
:: 2b. Alternativa: Python 3 oficial (o CBERS exigira GDAL; Google Earth funciona com Pillow)
if not defined BASE_PY for %%P in ("%LOCALAPPDATA%\Programs\Python\Python312\python.exe" "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" "C:\Python312\python.exe" "C:\Python311\python.exe" "C:\Python310\python.exe") do (
    if not defined BASE_PY if exist "%%~P" set "BASE_PY=%%~P"
)

if exist "%VENV_PY%" goto :venv_ready
if not defined BASE_PY (
    echo [ERRO] Nenhum Python 3 encontrado ^(QGIS 3.x ou Python 3.10+^).
    echo        Instale o QGIS 3.x ^(recomendado^) ou o Python 3 e execute este instalador novamente.
    set "FAILED=1"
    goto :step3
)
echo [INFO] Criando venv a partir de: %BASE_PY%
"%BASE_PY%" -I -m venv --system-site-packages "%VENV_DIR%"
if errorlevel 1 (
    echo [ERRO] Falha ao criar o ambiente virtual.
    set "FAILED=1"
    goto :step3
)

:venv_ready
echo [INFO] Instalando dependencias ^(earthengine-api, Pillow, ...^)...
:: Sem --upgrade em -r: numpy/GDAL herdados do QGIS nao sao substituidos (ABI do GDAL)
"%VENV_PY%" -m pip install -r "%SCRIPT_DIR%requirements.txt" --disable-pip-version-check --quiet
if errorlevel 1 (
    echo [ERRO] Falha no pip. Verifique a conexao de internet/proxy.
    set "FAILED=1"
    goto :step3
)
"%VENV_PY%" -m pip install --upgrade earthengine-api --disable-pip-version-check --quiet
"%VENV_PY%" -c "import ee; print('[OK] earthengine-api', ee.__version__)"
if errorlevel 1 set "FAILED=1"
"%VENV_PY%" -c "from osgeo import gdal; print('[OK] GDAL', gdal.__version__, '(CBERS/INPE habilitado)')" 2>nul
if errorlevel 1 echo [AVISO] GDAL indisponivel neste Python: o download CBERS/INPE requer o QGIS 3.x instalado.

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
