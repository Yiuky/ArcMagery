@echo off
chcp 65001 >nul
setlocal
title Atualizador - ArcMagery
cls
echo ==============================================================================
echo                         ATUALIZADOR DO ARCMAGERY
echo ==============================================================================
echo.

cd /d "%~dp0"

if not exist ".git" goto :no_git
where git >nul 2>nul
if errorlevel 1 goto :no_git

:: Pasta clonada com git: atualiza apenas por avanco rapido (nunca cria merge nem
:: sobrescreve alteracoes locais) e reinstala.
echo Esta pasta e um clone git: sera atualizada para o branch "main", a versao de
echo desenvolvimento, que pode estar a frente da ultima versao estavel publicada.
echo Para receber so versoes estaveis, use o Assistente de Atualizacao do plugin.
echo.
set /p GO="Continuar? (S/N): "
if /i not "%GO%"=="S" exit /b 0
echo.
echo [1/2] Atualizando pelo git (somente avanco rapido)...
:: HEAD: considera tambem alteracoes ja adicionadas ao indice (staged)
git diff --quiet HEAD
if errorlevel 1 (
    echo [ERRO] Ha alteracoes locais nao salvas nesta pasta. Salve ^(commit^) ou descarte-as e tente novamente.
    pause
    exit /b 1
)
git pull --ff-only origin main
if errorlevel 1 (
    echo [ERRO] Nao foi possivel atualizar por avanco rapido ^(branch divergente ou sem conexao^).
    pause
    exit /b 1
)
echo.
echo [2/2] Reinstalando o Add-In...
call "%~dp0install.bat"
exit /b %errorlevel%

:no_git
:: Pasta baixada como ZIP: a atualizacao segura e feita pela Release verificada
:: (SHA-256), pelo assistente do plugin ou baixando o pacote novo.
echo Esta pasta nao e um clone git. Para atualizar com verificacao de integridade:
echo.
echo   1. No ArcMap: ArcMagery ^> Configuracoes ^> Assistente de Atualizacao ^> Metodo 1
echo      ^(baixa a ultima Release do canal escolhido e confere o SHA-256 antes de instalar^); ou
echo   2. Baixe a ultima Release, extraia em uma pasta nova e execute o install.bat.
echo.
set /p OPEN="Abrir a pagina de Releases no navegador? (S/N): "
if /i "%OPEN%"=="S" start "" "https://github.com/Yiuky/arcgis-google-earth-engine-explorer/releases/latest"
exit /b 0
