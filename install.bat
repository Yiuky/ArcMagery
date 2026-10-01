@echo off
chcp 65001 >nul
setlocal
title Instalador - ArcMagery
cls
echo ======================================================================
echo                  ARCMAGERY - INSTALADOR AUTOMATIZADO
echo   Google Earth Engine, Google Earth (atual e historico), Esri Wayback,
echo   CBERS/Amazonia-1 (INPE) e SPOT 1-5 (CNES) no ArcGIS Desktop 10.8
echo ======================================================================
echo.

set "SCRIPT_DIR=%~dp0"
set "PYTHON27=C:\Python27\ArcGIS10.8\python.exe"
set "REGADDIN=%CommonProgramFiles(x86)%\ArcGIS\bin\ESRIRegAddIn.exe"
if not exist "%REGADDIN%" set "REGADDIN=C:\Program Files (x86)\Common Files\ArcGIS\bin\ESRIRegAddIn.exe"
set "ADDIN_UUID={ceae58c4-c44e-4edd-b8f4-1ba7d13b6b7d}"
set "CACHE_DIR=%LOCALAPPDATA%\ESRI\Desktop10.8\AssemblyCache\%ADDIN_UUID%"
set "VENV_PY=%LOCALAPPDATA%\ArcMagery\venv\Scripts\python.exe"
set "FAILED="

:: Pasta Documentos real (pode estar redirecionada para o OneDrive): e nela que o ArcMap procura os Add-Ins
set "DOCS="
for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "[Console]::OutputEncoding=[Text.Encoding]::UTF8; [Environment]::GetFolderPath('MyDocuments')" 2^>nul`) do set "DOCS=%%D"
if not defined DOCS set "DOCS=%USERPROFILE%\Documents"
set "USER_ADDIN_DIR=%DOCS%\ArcGIS\AddIns\Desktop10.8\%ADDIN_UUID%"

:: Nunca herdar o Python 2.7 do ArcGIS no Python 3 (e vice-versa)
set "PYTHONHOME="
set "PYTHONPATH="

:: O ArcMap aberto prende os arquivos do Add-In e a copia sairia pela metade
tasklist /FI "IMAGENAME eq ArcMap.exe" 2>nul | find /I "ArcMap.exe" >nul
if not errorlevel 1 (
    echo [ERRO] O ArcMap esta aberto. Feche o ArcMap e execute o install.bat novamente.
    echo.
    pause
    exit /b 1
)

:: 1. ArcGIS Desktop 10.8 / Python 2.7
echo [1/4] Verificando o ArcGIS Desktop 10.8...
if not exist "%PYTHON27%" (
    echo [ERRO] Python 2.7 do ArcGIS nao encontrado em "%PYTHON27%".
    echo        O ArcMagery e um Add-In do ArcMap: instale o ArcGIS Desktop 10.8.x e execute este instalador novamente.
    set "FAILED=1"
    goto :summary
)
echo [OK] ArcGIS Desktop 10.8 e Python 2.7 detectados.
"%PYTHON27%" -c "import comtypes" 2>nul
if errorlevel 1 (
    echo [OK] comtypes ausente no Python 2.7: sera usada a copia embutida no Add-In.
) else (
    echo [OK] Modulo comtypes disponivel no Python 2.7.
)

:: 2. Python 3 do backend. NAO precisa de pip nem de venv: o Python do QGIS ja traz GDAL, numpy e
::    Pillow, e o earthengine-api e baixado com os certificados do Windows (funciona com o proxy de
::    inspecao SSL) para %LOCALAPPDATA%\ArcMagery\pylibs (backend\pylibs.py). Um venv antigo e mantido.
echo.
echo [2/4] Preparando o Python 3 do backend...
call "%SCRIPT_DIR%tools\find_python3.bat"
set "PY3=%PY3_FOUND%"
:: venv antigo so e usado se ainda abrir (um venv quebrado e tirado de uso pelo diagnostico)
if exist "%VENV_PY%" "%VENV_PY%" -c "import sys" >nul 2>nul && set "PY3=%VENV_PY%"
if not defined PY3 (
    echo [ERRO] Nenhum Python 3 encontrado.
    echo        Instale o QGIS ^(3.18 ou mais novo; recomendado: a versao LTR atual^) e execute este instalador
    echo        novamente. QGIS fora de "Program Files": setx GEE_PYTHON3 "caminho\apps\Python3XX\python.exe"
    set "FAILED=1"
    goto :step3
)
echo [INFO] Python 3: %PY3%
set "BACKEND=%SCRIPT_DIR%arcgis_addin\Install\backend"
set "PYTHONIOENCODING=utf-8"
echo.
echo [DIAGNOSTICO] Verificando o ambiente e corrigindo o que for possivel ^(~20 s^)...
echo ----------------------------------------------------------------------
:: "%~dp0." e nao "%~dp0": a barra final antes da aspa ( \" ) escaparia a aspa no argumento
"%PY3%" "%BACKEND%\run_gee.py" doctor --text "--install-path=%~dp0."
if errorlevel 1 (
    echo ----------------------------------------------------------------------
    echo [ATENCAO] O diagnostico encontrou problemas ^(veja "o que fazer" acima^).
    echo           Relatorio completo: "%LOCALAPPDATA%\ArcMagery\diagnostico.txt"
    set "FAILED=1"
) else (
    echo ----------------------------------------------------------------------
)
:step3
:: 3. Empacotar o Add-in (backend autocontido em arcgis_addin\Install\backend)
echo.
echo [3/4] Empacotando o Add-In (.esriaddin)...
pushd "%SCRIPT_DIR%arcgis_addin"
"%PYTHON27%" makeaddin.py
if errorlevel 1 set "FAILED=1"
popd
if not exist "%SCRIPT_DIR%arcgis_addin\GEE_Image_Selector.esriaddin" (
    echo [ERRO] O pacote GEE_Image_Selector.esriaddin nao foi gerado.
    set "FAILED=1"
    goto :summary
)

:: 4. Instalar o Add-In no ArcGIS Desktop 10.8
echo.
echo [4/4] Instalando o Add-In no ArcGIS Desktop...
if not exist "%USER_ADDIN_DIR%" mkdir "%USER_ADDIN_DIR%"
copy /Y "%SCRIPT_DIR%arcgis_addin\GEE_Image_Selector.esriaddin" "%USER_ADDIN_DIR%\" >nul
if errorlevel 1 (
    echo [ERRO] Nao foi possivel copiar o Add-In para "%USER_ADDIN_DIR%".
    set "FAILED=1"
)

:: Atualizar o AssemblyCache (inclusive a subpasta backend) para evitar codigo antigo em cache
if exist "%CACHE_DIR%" (
    del /S /Q /F "%CACHE_DIR%\*.pyc" >nul 2>nul
    xcopy /S /E /Y /I /Q "%SCRIPT_DIR%arcgis_addin\Install\*" "%CACHE_DIR%\" >nul
    if errorlevel 1 (
        echo [ERRO] Nao foi possivel atualizar o cache do ArcMap em "%CACHE_DIR%".
        set "FAILED=1"
    )
    copy /Y "%SCRIPT_DIR%arcgis_addin\config.xml" "%CACHE_DIR%\" >nul
)

if exist "%REGADDIN%" (
    "%REGADDIN%" /s "%SCRIPT_DIR%arcgis_addin\GEE_Image_Selector.esriaddin"
    if errorlevel 1 echo [AVISO] O registro silencioso do Add-In falhou; a copia manual acima continua valendo.
)

:: Versoes antigas instalavam uma caixa de ferramentas (.pyt) que deixou de existir
if exist "%DOCS%\ArcGIS\GEE_Tools.pyt" del /q "%DOCS%\ArcGIS\GEE_Tools.pyt" >nul 2>nul

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
echo   4. Google Earth Engine: clique em "Configurar Projeto GEE" e informe o seu Project ID.
echo   5. Outras fontes: barra "Fonte de imagens" ^(CBERS, SPOT, Google Earth historico, Esri Wayback^)
echo      e botao "Google Earth / XYZ...".
echo.
echo Para autenticar o GEE agora, execute: autenticar_gee.bat
echo.
pause
exit /b 0
