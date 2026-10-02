# -*- coding: utf-8 -*-
"""
Confere que a versão é a mesma em todos os lugares (CI "Testes" e workflow de Release):

  arcgis_addin/config.xml        <Version>                 (fonte da verdade; a tag é v<versão>)
  arcgis_addin/Install/gee_gui.py  CURRENT_VERSION
  arcgis_addin/Install/gee_updater.py  current_version="..." (padrões das funções)
  README.md                      selo "Versão-v..." (o shields.io escreve "-" como "--")
  qgis_plugin/qmagery/metadata.txt  version= (nightly vira "-beta.": ver tools/qgis_repo.py) e experimental

Uso: python tools/check_versions.py [--tag v2.4.3] [--release]
  --tag      a tag precisa ser v<versão do config.xml>
  --release  exige também a seção "## [<versão>]" no CHANGELOG.md
"""
from __future__ import print_function

import argparse
import io
import os
import re
import sys
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import qgis_repo  # noqa: E402


def read(rel):
    with io.open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


def collect():
    ns = {'e': 'http://schemas.esri.com/Desktop/AddIns'}
    v = ET.parse(os.path.join(ROOT, 'arcgis_addin', 'config.xml')).getroot().find('e:Version', ns).text.strip()
    gui = re.search(r'^CURRENT_VERSION = "([^"]+)"', read('arcgis_addin/Install/gee_gui.py'), re.M).group(1)
    upd = set(re.findall(r'current_version="([^"]+)"', read('arcgis_addin/Install/gee_updater.py')))
    badge = re.search(u'Versão-v(.+?)-[0-9A-Fa-f]{6}[.]svg', read('README.md'))
    readme = badge.group(1).replace('--', '-') if badge else None
    meta = qgis_repo.read_metadata()
    return v, gui, upd, readme, meta


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag')
    ap.add_argument('--release', action='store_true')
    a = ap.parse_args(argv)
    v, gui, upd, readme, meta = collect()
    print('config.xml %s | gee_gui %s | gee_updater %s | README %s | QMagery %s (experimental=%s)'
          % (v, gui, sorted(upd), readme, meta.get('version'), meta.get('experimental')))
    errors = []
    if gui != v or upd != {v}:
        errors.append('versões divergentes entre config.xml, gee_gui.py e gee_updater.py')
    if readme != v:
        errors.append('selo de versão do README desatualizado (%s)' % readme)
    if meta.get('version') != qgis_repo.qgis_version(v):
        errors.append('metadata.txt do QMagery: version=%s, esperado %s' % (meta.get('version'), qgis_repo.qgis_version(v)))
    if (meta.get('experimental', '').lower() == 'true') != qgis_repo.is_experimental(v):
        errors.append('metadata.txt do QMagery: experimental deve ser %s' % qgis_repo.is_experimental(v))
    if a.tag and a.tag != 'v' + v:
        errors.append('a tag %s diverge da versão do config.xml (%s)' % (a.tag, v))
    if a.release and not re.search(r'^## \[%s\]' % re.escape(v), read('CHANGELOG.md'), re.M):
        errors.append('CHANGELOG.md sem a seção "## [%s]"' % v)
    for e in errors:
        print('ERRO: ' + e)
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
