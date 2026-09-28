# -*- coding: utf-8 -*-
"""Coloca o backend no sys.path e define utilitarios comuns dos testes."""
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
BACKEND = os.path.join(REPO, 'arcgis_addin', 'Install', 'backend')
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

# Conexoes com 127.0.0.1 nunca devem passar por proxy corporativo (urllib e curl/GDAL)
os.environ['NO_PROXY'] = os.environ['no_proxy'] = '127.0.0.1,localhost'

LIVE = os.environ.get('ARCMAGERY_LIVE') == '1'
GEE_PROJECT = os.environ.get('ARCMAGERY_GEE_PROJECT', '')

try:
    from osgeo import gdal  # noqa: F401
    HAS_GDAL = True
except Exception:
    HAS_GDAL = False
