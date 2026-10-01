@echo off
chcp 65001 >nul
setlocal
title Desinstalador - ArcMagery
cls
echo ==============================================================================
echo                        DESINSTALADOR DO ARCMAGERY
echo ==============================================================================
echo.
echo Remove o Add-In do ArcGIS Desktop 10.8 e o cache do ArcMap. No fim, voce pode
echo escolher remover tambem os dados do plugin (componentes, cache SPOT, backups,
echo configuracoes e a chave do GEODES).
echo.

tasklist /FI "IMAGENAME eq ArcMap.exe" 2>nul | find /I "ArcMap.exe" >nul
if not errorlevel 1 (
    echo [ERRO] O ArcMap esta aberto. Feche o ArcMap e execute novamente.
    pause
    exit /b 1
)

set /p CONFIRM="Deseja realmente desinstalar o ArcMagery? (S/N): "
if /i not "%CONFIRM%"=="S" (
    echo [INFO] Desinstalacao cancelada.
    pause
    exit /b 0
)

set "FAILED="
set "DOCS="
for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "[Console]::OutputEncoding=[Text.Encoding]::UTF8; [Environment]::GetFolderPath('MyDocuments')" 2^>nul`) do set "DOCS=%%D"
if not defined DOCS set "DOCS=%USERPROFILE%\Documents"
set "ADDIN_DIR=%DOCS%\ArcGIS\AddIns\Desktop10.8\{ceae58c4-c44e-4edd-b8f4-1ba7d13b6b7d}"
set "CACHE_DIR=%LOCALAPPDATA%\ESRI\Desktop10.8\AssemblyCache\{CEAE58C4-C44E-4EDD-B8F4-1BA7D13B6B7D}"

echo.
echo [1/3] Encerrando a interface do ArcMagery (somente ela)...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'pythonw.exe' -and $_.CommandLine -like '*gee_gui.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" 2>nul

echo [2/3] Removendo o Add-In (.esriaddin)...
if exist "%ADDIN_DIR%" (
    rd /s /q "%ADDIN_DIR%"
    if exist "%ADDIN_DIR%" (echo    [ERRO] Nao foi possivel remover "%ADDIN_DIR%". & set "FAILED=1") else (echo    - Removido.)
) else (
    echo    - Nao instalado.
)

echo [3/3] Limpando o cache do ArcMap e arquivos temporarios...
if exist "%CACHE_DIR%" (
    rd /s /q "%CACHE_DIR%"
    if exist "%CACHE_DIR%" (echo    [ERRO] Nao foi possivel remover "%CACHE_DIR%". & set "FAILED=1") else (echo    - Cache removido.)
)
:: caixa de ferramentas .pyt de versoes antigas
if exist "%DOCS%\ArcGIS\GEE_Tools.pyt" del /q "%DOCS%\ArcGIS\GEE_Tools.pyt"
del /q "%TEMP%\arcmagery_*_cmd.json" "%TEMP%\arcmagery_*_reply.json" "%TEMP%\arcmagery_*_context.json" "%TEMP%\arcmagery_*_gui_heartbeat.tmp" 2>nul
del /q "%TEMP%\gee_arcgis_*.json" "%TEMP%\arcgis_gee_*.json" "%TEMP%\arcmagery_ca_bundle.pem" 2>nul
for /d %%T in ("%TEMP%\arcmagery_spot_*" "%TEMP%\arcgee_tiles_*") do rd /s /q "%%~T" 2>nul
echo    - Concluido.

echo.
echo Dados que continuam no computador:
echo   %LOCALAPPDATA%\ArcMagery        componentes do Earth Engine, cache SPOT, diagnostico
echo   %LOCALAPPDATA%\CGMA_ArcGEE      backups e logs do atualizador (nome legado da pasta)
echo   %APPDATA%\ArcGEE                configuracoes, projeto GEE e chave do GEODES
echo   %USERPROFILE%\.config\earthengine   login do Google Earth Engine (usado tambem por outras ferramentas)
echo.
set /p RMDATA="Remover tambem as tres primeiras pastas? (S/N): "
if /i "%RMDATA%"=="S" (
    for %%F in ("%LOCALAPPDATA%\ArcMagery" "%LOCALAPPDATA%\CGMA_ArcGEE" "%APPDATA%\ArcGEE") do (
        if exist "%%~F" rd /s /q "%%~F"
        if exist "%%~F" (echo    [ERRO] Nao foi possivel remover "%%~F". & set "FAILED=1") else (echo    - Removido: %%~F)
    )
    echo    O login do Earth Engine foi mantido; para revoga-lo, apague a pasta .config\earthengine acima.
)

echo.
echo ==============================================================================
if defined FAILED (
    echo   DESINSTALACAO INCOMPLETA - revise as mensagens acima.
    echo ==============================================================================
    pause
    exit /b 1
)
echo              ARCMAGERY DESINSTALADO COM SUCESSO
echo ==============================================================================
echo Para reinstalar no futuro, execute o install.bat.
echo.
pause
exit /b 0
