# -*- coding: utf-8 -*-
"""
Garante que as DLLs do GDAL do QGIS/OSGeo4W sejam encontradas (Python 3 no Windows).

O sitecustomize.py do QGIS so registra <QGIS>\\bin como diretorio de DLLs quando a variavel
OSGEO4W_ROOT AINDA NAO existe - e ele mesmo a define no ambiente, que e herdado pelos processos
filhos. Assim, um Python do QGIS lancado por outro processo que ja tenha OSGEO4W_ROOT (outro
Python do QGIS, o shell do OSGeo4W ou uma variavel de sistema) falha com
"No module named '_gdal'". Aqui o <QGIS>\\bin e registrado a partir da localizacao do proprio
interpretador (sys.base_prefix = <QGIS>\\apps\\Python3xx), sem depender do ambiente.
"""
import os
import sys

_DONE = False


def qgis_bin_dir():
    base = os.path.normpath(getattr(sys, 'base_prefix', sys.prefix))
    root = os.path.dirname(os.path.dirname(base))  # <QGIS>\apps\Python3xx -> <QGIS>
    cand = os.path.join(root, 'bin')
    return cand if os.path.isdir(cand) else None


def ensure_gdal_dll_path():
    """Idempotente. Sem efeito fora do Windows ou fora de um Python do QGIS/OSGeo4W."""
    global _DONE
    if _DONE or os.name != 'nt' or not hasattr(os, 'add_dll_directory'):
        return
    _DONE = True
    bin_dir = qgis_bin_dir()
    if not bin_dir:
        return
    try:
        os.add_dll_directory(bin_dir)
    except OSError:
        return
    path = os.environ.get('PATH', '')
    if bin_dir.lower() not in [p.lower() for p in path.split(';')]:
        os.environ['PATH'] = bin_dir + ';' + path  # herdado por gdal/curl e subprocessos
    for key, rel in (('GDAL_DATA', os.path.join('apps', 'gdal', 'share', 'gdal')),
                     ('PROJ_DATA', os.path.join('share', 'proj'))):
        p = os.path.join(os.path.dirname(bin_dir), rel)
        if not os.environ.get(key) and os.path.isdir(p):
            os.environ[key] = p


ensure_gdal_dll_path()
