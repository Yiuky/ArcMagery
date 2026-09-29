@echo off
chcp 65001 >nul
setlocal
title Desinstalador - ArcMagery
cls
echo ==============================================================================
echo                        DESINSTALADOR DO ARCMAGERY
echo ==============================================================================
echo.
echo Remove o Add-In do ArcGIS Desktop 10.8, o cache do ArcMap e a caixa de
echo ferramentas. Suas configuracoes e o projeto GEE (%%APPDATA%%\ArcGEE) sao mantidos.
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
set "ADDIN_DIR=%USERPROFILE%\Documents\ArcGIS\AddIns\Desktop10.8\{ceae58c4-c44e-4edd-b8f4-1ba7d13b6b7d}"
set "CACHE_DIR=%LOCALAPPDATA%\ESRI\Desktop10.8\AssemblyCache\{CEAE58C4-C44E-4EDD-B8F4-1BA7D13B6B7D}"
set "PYT_FILE=%USERPROFILE%\Documents\ArcGIS\GEE_Tools.pyt"

echo.
echo [1/4] Encerrando a interface do ArcMagery (somente ela)...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'pythonw.exe' -and $_.CommandLine -like '*gee_gui.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" 2>nul

echo [2/4] Removendo o Add-In (.esriaddin)...
if exist "%ADDIN_DIR%" (
    rd /s /q "%ADDIN_DIR%"
    if exist "%ADDIN_DIR%" (echo    [ERRO] Nao foi possivel remover "%ADDIN_DIR%". & set "FAILED=1") else (echo    - Removido.)
) else (
    echo    - Nao instalado.
)

echo [3/4] Limpando o AssemblyCache do ArcMap...
if exist "%CACHE_DIR%" (
    rd /s /q "%CACHE_DIR%"
    if exist "%CACHE_DIR%" (echo    [ERRO] Nao foi possivel remover "%CACHE_DIR%". & set "FAILED=1") else (echo    - Removido.)
) else (
    echo    - Nenhum cache encontrado.
)

echo [4/4] Removendo caixa de ferramentas e arquivos temporarios...
if exist "%PYT_FILE%" del /q "%PYT_FILE%"
del /q "%TEMP%\arcmagery_*_cmd.json" "%TEMP%\arcmagery_*_reply.json" "%TEMP%\arcmagery_*_context.json" "%TEMP%\arcmagery_*_gui_heartbeat.tmp" 2>nul
del /q "%TEMP%\gee_arcgis_*.json" "%TEMP%\arcgis_gee_*.json" 2>nul
echo    - Concluido.

echo.
set /p RMVENV="Remover tambem o ambiente Python do plugin (%LOCALAPPDATA%\ArcMagery\venv)? (S/N): "
if /i "%RMVENV%"=="S" (
    if exist "%LOCALAPPDATA%\ArcMagery\venv" rd /s /q "%LOCALAPPDATA%\ArcMagery\venv"
    if exist "%LOCALAPPDATA%\ArcMagery\venv" (echo    [ERRO] Nao foi possivel remover o venv. & set "FAILED=1") else (echo    - Ambiente Python removido.)
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
