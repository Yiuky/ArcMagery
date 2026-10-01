# -*- coding: utf-8 -*-
"""Coloca o backend e o plugin QMagery no sys.path e define utilitarios comuns.

Espelha tests/backend/_paths.py para manter consist\u00eancia entre as duas suites de teste.
"""
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
BACKEND = os.path.join(REPO, 'arcgis_addin', 'Install', 'backend')
PLUGIN_ROOT = os.path.join(REPO, 'qgis_plugin')
PLUGIN_DIR = os.path.join(PLUGIN_ROOT, 'qmagery')

for p in (BACKEND, PLUGIN_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

# Conex\u00f5es locais n\u00e3o devem passar por proxy corporativo
os.environ['NO_PROXY'] = os.environ['no_proxy'] = '127.0.0.1,localhost'

# Flags de ambiente
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

# Verifica se o PyQGIS est\u00e1 dispon\u00edvel (testes com PyQGIS requerem QGIS instalado)
try:
    from qgis.core import QgsApplication  # noqa: F401
    HAS_PYQGIS = True
except ImportError:
    HAS_PYQGIS = False
