# -*- coding: utf-8 -*-
"""Coloca o backend e o plugin QMagery no sys.path e define utilitários comuns (espelha tests/backend/_paths.py).

Os testes de interface (test_gui.py) exigem o PyQGIS e são pulados sem ele (CI). Para rodá-los:
    "C:\\Program Files\\QGIS 3.xx\\bin\\python-qgis-ltr.bat" tests\\qgis\\run_all.py
"""
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
INSTALL = os.path.join(REPO, 'arcgis_addin', 'Install')
BACKEND = os.path.join(INSTALL, 'backend')
PLUGIN_ROOT = os.path.join(REPO, 'qgis_plugin')
PLUGIN_DIR = os.path.join(PLUGIN_ROOT, 'qmagery')

for p in (BACKEND, PLUGIN_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

# Os testes NUNCA gravam nas configurações reais do usuário (%APPDATA%\ArcGEE): o QMagery lê o APPDATA
# a cada chamada, então basta apontá-lo para uma pasta temporária antes de qualquer teste. Os testes ao
# vivo leem (só leem) o projeto do GEE e a chave do GEODES reais por REAL_APPDATA.
import atexit  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402

REAL_APPDATA = os.environ.get('QMAGERY_REAL_APPDATA') or os.environ.get('APPDATA') or os.path.expanduser('~')
if not os.environ.get('QMAGERY_REAL_APPDATA'):
    os.environ['QMAGERY_REAL_APPDATA'] = REAL_APPDATA
    _fake = tempfile.mkdtemp(prefix='qmagery_test_appdata_')
    os.environ['APPDATA'] = _fake
    atexit.register(shutil.rmtree, _fake, True)


def real_user_file(name):
    """Conteúdo (dict) de %APPDATA%\\ArcGEE\\<name> do usuário real, só leitura; {} se não existir."""
    import io
    import json
    try:
        with io.open(os.path.join(REAL_APPDATA, 'ArcGEE', name), encoding='utf-8-sig') as f:
            return json.load(f)
    except Exception:
        return {}


# Conexões locais não devem passar por proxy corporativo
os.environ['NO_PROXY'] = os.environ['no_proxy'] = '127.0.0.1,localhost'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

LIVE = os.environ.get('ARCMAGERY_LIVE') == '1'
GEE_PROJECT = os.environ.get('ARCMAGERY_GEE_PROJECT', '')

try:
    from osgeo import gdal  # noqa: F401
    HAS_GDAL = True
except Exception:
    HAS_GDAL = False

try:
    import ee  # noqa: F401
    HAS_EE = True
except Exception:
    HAS_EE = False

try:
    from qgis.core import QgsApplication  # noqa: F401
    HAS_PYQGIS = True
except ImportError:
    HAS_PYQGIS = False

_qgs_app = None


def ensure_qgis_app():
    """UMA QgsApplication por processo (duas derrubam o Python com 0xC0000409)."""
    global _qgs_app
    if HAS_PYQGIS and _qgs_app is None:
        from qgis.core import QgsApplication
        _qgs_app = QgsApplication.instance()
        if _qgs_app is None:
            _qgs_app = QgsApplication([], True)
            _qgs_app.initQgis()
    return _qgs_app
