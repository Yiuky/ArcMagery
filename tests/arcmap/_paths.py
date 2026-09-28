# -*- coding: utf-8 -*-
"""Caminhos comuns da suite Python 2.7 (lado ArcMap/GUI)."""
import glob
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
INSTALL = os.path.join(REPO, 'arcgis_addin', 'Install')
BACKEND = os.path.join(INSTALL, 'backend')
if INSTALL not in sys.path:
    sys.path.insert(0, INSTALL)

PYTHONW = os.path.join(sys.prefix, 'pythonw.exe')


def qgis_python():
    """Um Python 3 com GDAL para testes que precisam de interpretador real (ou None)."""
    for pattern in (r"C:\Program Files\QGIS *\apps\Python3*\python.exe", r"C:\OSGeo4W*\apps\Python3*\python.exe"):
        found = sorted(glob.glob(pattern))
        if found:
            return found[-1]
    return None
