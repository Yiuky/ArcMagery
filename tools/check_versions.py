# -*- coding: utf-8 -*-
"""
Confere que a versão é a mesma em todos os lugares (CI "Testes" e workflow de Release):

  arcgis_addin/config.xml        <Version>                 (fonte da verdade; a tag é v<versão>)
  arcgis_addin/Install/gee_gui.py  CURRENT_VERSION
  arcgis_addin/Install/gee_updater.py  current_version="..." (padrões das funções)
  qgis_plugin/qmagery/metadata.txt  version= (nightly vira "-beta.": ver tools/qgis_repo.py) e experimental
  CITATION.cff                   version: (só nas versões estáveis; na nightly fica a última estável)
  README.md                      selos "Estável" e "Nightly", lidos das Releases pelo shields.io (README_BADGES):
                                 não têm versão escrita, só precisam existir

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

# Selos do README: a versão vem das Releases do GitHub (estável = releases/latest; nightly = a mais nova
# pela ordem semver, incluindo pre-releases, que é o que o canal experimental do atualizador instala).
README_BADGES = (
    'https://img.shields.io/github/v/release/Yiuky/ArcMagery?label=Est%C3%A1vel',
    'https://img.shields.io/github/v/release/Yiuky/ArcMagery?include_prereleases&sort=semver&label=Nightly',
)


def read(rel):
    with io.open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


def collect():
    ns = {'e': 'http://schemas.esri.com/Desktop/AddIns'}
    v = ET.parse(os.path.join(ROOT, 'arcgis_addin', 'config.xml')).getroot().find('e:Version', ns).text.strip()
    gui = re.search(r'^CURRENT_VERSION = "([^"]+)"', read('arcgis_addin/Install/gee_gui.py'), re.M).group(1)
    upd = set(re.findall(r'current_version="([^"]+)"', read('arcgis_addin/Install/gee_updater.py')))
    readme = read('README.md')
    missing = [b for b in README_BADGES if b not in readme]
    meta = qgis_repo.read_metadata()
    cff = re.search(r'^version:\s*(\S+)', read('CITATION.cff'), re.M)
    return v, gui, upd, missing, meta, cff.group(1) if cff else None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag')
    ap.add_argument('--release', action='store_true')
    a = ap.parse_args(argv)
    v, gui, upd, missing, meta, cff = collect()
    print('config.xml %s | gee_gui %s | gee_updater %s | QMagery %s (experimental=%s) | CITATION %s'
          % (v, gui, sorted(upd), meta.get('version'), meta.get('experimental'), cff))
    errors = []
    if gui != v or upd != {v}:
        errors.append('versões divergentes entre config.xml, gee_gui.py e gee_updater.py')
    for b in missing:
        errors.append('README sem o selo %s' % b)
    if re.search(u'badge/Versão-v', read('README.md')):
        errors.append('README com selo de versão fixo (use os selos dinâmicos de README_BADGES)')
    if not qgis_repo.is_experimental(v) and cff != v:
        errors.append('CITATION.cff: version: %s, esperado %s (versão estável)' % (cff, v))
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
