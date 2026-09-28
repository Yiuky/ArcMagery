$addinSrc = "arcgis_addin\GEE_Image_Selector.esriaddin"
$addinDest = "C:\Users\joberthgambati\Documents\ArcGIS\AddIns\Desktop10.8\{ceae58c4-c44e-4edd-b8f4-1ba7d13b6b7d}\GEE_Image_Selector.esriaddin"
$cacheDir = "C:\Users\joberthgambati\AppData\Local\ESRI\Desktop10.8\AssemblyCache\{CEAE58C4-C44E-4EDD-B8F4-1BA7D13B6B7D}"

Copy-Item $addinSrc $addinDest -Force
Copy-Item "arcgis_addin\Install\*" $cacheDir -Recurse -Force
Copy-Item "arcgis_addin\config.xml" $cacheDir -Force
Get-ChildItem -Path $cacheDir -Filter "*.pyc" -Recurse | Remove-Item -Force -ErrorAction SilentlyContinue
Stop-Process -Name pythonw -Force -ErrorAction SilentlyContinue

& "C:\Python27\ArcGIS10.8\python.exe" -c "import py_compile, os; cache=r'$cacheDir'; py_compile.compile(os.path.join(cache, 'gee_selector_addin.py')); py_compile.compile(os.path.join(cache, 'gee_bridge.py')); py_compile.compile(os.path.join(cache, 'gee_gui.py')); py_compile.compile(os.path.join(cache, 'gee_updater.py')); print('Cache pyc compiled successfully!')"


Write-Output "DEPLOY_COMPLETE"

