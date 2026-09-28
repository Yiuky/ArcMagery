$ErrorActionPreference = "Stop"

$docsDir = [Environment]::GetFolderPath('MyDocuments')
$localAppData = $env:LOCALAPPDATA
$uuid = "{ceae58c4-c44e-4edd-b8f4-1ba7d13b6b7d}"
$uuidUpper = "{CEAE58C4-C44E-4EDD-B8F4-1BA7D13B6B7D}"

$addinSrc = "arcgis_addin\GEE_Image_Selector.esriaddin"
$addinDestDir = Join-Path $docsDir "ArcGIS\AddIns\Desktop10.8\$uuid"
$addinDest = Join-Path $addinDestDir "GEE_Image_Selector.esriaddin"
$cacheDir = Join-Path $localAppData "ESRI\Desktop10.8\AssemblyCache\$uuidUpper"

if (-not (Test-Path $addinDestDir)) {
    New-Item -ItemType Directory -Path $addinDestDir -Force | Out-Null
}
if (-not (Test-Path $cacheDir)) {
    New-Item -ItemType Directory -Path $cacheDir -Force | Out-Null
}

if (Test-Path $addinSrc) {
    Copy-Item $addinSrc $addinDest -Force
}
Copy-Item "arcgis_addin\Install\*" $cacheDir -Recurse -Force
Copy-Item "arcgis_addin\config.xml" $cacheDir -Force
Get-ChildItem -Path $cacheDir -Filter "*.pyc" -Recurse | Remove-Item -Force -ErrorAction SilentlyContinue
Stop-Process -Name pythonw -Force -ErrorAction SilentlyContinue

if (Test-Path "C:\Python27\ArcGIS10.8\python.exe") {
    & "C:\Python27\ArcGIS10.8\python.exe" -c "import py_compile, os; cache=r'$cacheDir'; py_compile.compile(os.path.join(cache, 'gee_selector_addin.py')); py_compile.compile(os.path.join(cache, 'gee_bridge.py')); py_compile.compile(os.path.join(cache, 'gee_gui.py')); py_compile.compile(os.path.join(cache, 'gee_updater.py')); print('Cache pyc compiled successfully!')"
}

Write-Output "DEPLOY_COMPLETE"

