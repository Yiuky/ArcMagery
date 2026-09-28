# Deploy de desenvolvimento: copia arcgis_addin\Install para o AssemblyCache do ArcMap e
# recompila os .pyc. Execute a partir da raiz do repositorio com o ArcMap FECHADO.
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$docsDir = [Environment]::GetFolderPath('MyDocuments')
$localAppData = $env:LOCALAPPDATA
$uuid = "{ceae58c4-c44e-4edd-b8f4-1ba7d13b6b7d}"
$uuidUpper = "{CEAE58C4-C44E-4EDD-B8F4-1BA7D13B6B7D}"

$addinSrc = "arcgis_addin\GEE_Image_Selector.esriaddin"
$addinDestDir = Join-Path $docsDir "ArcGIS\AddIns\Desktop10.8\$uuid"
$addinDest = Join-Path $addinDestDir "GEE_Image_Selector.esriaddin"
$cacheDir = Join-Path $localAppData "ESRI\Desktop10.8\AssemblyCache\$uuidUpper"

try {
    if (Get-Process -Name ArcMap -ErrorAction SilentlyContinue) {
        throw "Feche o ArcMap antes do deploy (arquivos do Add-In ficam bloqueados)."
    }
    foreach ($d in @($addinDestDir, $cacheDir)) {
        if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
    }

    if (Test-Path $addinSrc) { Copy-Item $addinSrc $addinDest -Force }
    Copy-Item "arcgis_addin\Install\*" $cacheDir -Recurse -Force
    Copy-Item "arcgis_addin\config.xml" $cacheDir -Force
    Get-ChildItem -Path $cacheDir -Filter "*.pyc" -Recurse | Remove-Item -Force -ErrorAction SilentlyContinue

    # Encerrar apenas a GUI do ArcMagery (nunca outros pythonw.exe do usuario)
    Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" |
        Where-Object { $_.CommandLine -like '*gee_gui.py*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

    $py27 = "C:\Python27\ArcGIS10.8\python.exe"
    if (Test-Path $py27) {
        & $py27 -c "import compileall, sys; ok = compileall.compile_dir(r'$cacheDir', quiet=1, maxlevels=0); sys.exit(0 if ok else 1)"
        if ($LASTEXITCODE -ne 0) { throw "Falha ao compilar os modulos Python 2.7 no AssemblyCache." }
    }
    Write-Output "DEPLOY_COMPLETE"
    exit 0
}
catch {
    Write-Error "DEPLOY_FAILED: $($_.Exception.Message)"
    exit 1
}
