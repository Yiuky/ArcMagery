# -*- coding: utf-8 -*-
"""
Repositório de plugins do QGIS para o QMagery: qgis_plugin/plugins.xml.

O usuário cadastra UMA vez no QGIS (Complementos > Gerenciar e instalar > Configurações > Adicionar):
    https://raw.githubusercontent.com/Yiuky/ArcMagery/main/qgis_plugin/plugins.xml
e o Gerenciador de Complementos passa a avisar e instalar as novas versões.

O arquivo tem até duas entradas: a última versão ESTÁVEL e a última EXPERIMENTAL (nightly). O QGIS só
mostra a experimental a quem marcou "Mostrar também os complementos experimentais" e, para esses,
instala a mais nova das duas.

Uso (o workflow de Release faz isso sozinho depois de publicar a Release):
    python tools/qgis_repo.py 2.4.3-nightly.20261002 [--xml qgis_plugin/plugins.xml] [--date 2026-10-02]

Regras que este módulo garante (o QGIS depende delas):
  * file_name começa por "qmagery." : o QGIS identifica o plugin pelo texto antes do 1º ponto;
  * a versão nightly vira "-beta." na versão do QGIS: para o QGIS, "2.4.3-nightly.X" seria MAIS NOVA
    que "2.4.3" (e a estável nunca seria oferecida); "2.4.3-beta.X" é mais velha, como deve ser.
"""
from __future__ import print_function

import argparse
import datetime
import io
import os
import re
import sys
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
XML_PATH = os.path.join(ROOT, 'qgis_plugin', 'plugins.xml')
METADATA = os.path.join(ROOT, 'qgis_plugin', 'qmagery', 'metadata.txt')
REPO = 'https://github.com/Yiuky/ArcMagery'
RAW = 'https://raw.githubusercontent.com/Yiuky/ArcMagery/main'

FIELDS = ('description', 'about', 'version', 'trusted', 'qgis_minimum_version', 'qgis_maximum_version',
          'homepage', 'file_name', 'icon', 'author_name', 'download_url', 'uploaded_by', 'create_date',
          'update_date', 'experimental', 'deprecated', 'tracker', 'repository', 'tags', 'downloads',
          'average_vote', 'rating_votes', 'external_dependencies', 'server', 'changelog', 'category')


def qgis_version(version):
    """Versão do projeto (tag) -> versão no metadata.txt / plugins.xml do QGIS."""
    return version.replace('-nightly.', '-beta.')


def is_experimental(version):
    return '-' in version


def zip_name(version):
    """Nome do pacote publicado na Release (mesma versão da tag)."""
    return 'QMagery-%s.zip' % version


def read_metadata(path=METADATA):
    import configparser
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    with io.open(path, 'r', encoding='utf-8') as f:
        parser.read_file(f)
    return dict(parser['general'])


def version_key(v):
    """Ordem do QGIS para as versões que publicamos: X.Y.Z-beta.AAAAMMDD < X.Y.Z."""
    m = re.match(r'^(\d+)\.(\d+)\.(\d+)(?:-[a-z]+\.(\d+))?$', v)
    if not m:
        return (0, 0, 0, 0, 0)
    a, b, c, d = m.groups()
    return (int(a), int(b), int(c), 0 if d else 1, int(d or 0))


def entry(version, meta, date):
    qv = qgis_version(version)
    exp = is_experimental(version)
    vmin = meta.get('qgisMinimumVersion', '3.18')
    return {
        'name': meta.get('name', 'QMagery'),
        'version': qv,
        'description': meta.get('description', ''),
        'about': meta.get('about', ''),
        'changelog': meta.get('changelog', ''),
        'trusted': 'False',
        'qgis_minimum_version': vmin + ('.0' if vmin.count('.') == 1 else ''),
        'qgis_maximum_version': '3.99.0',
        'homepage': meta.get('homepage', REPO),
        'file_name': 'qmagery.%s.zip' % qv,
        'icon': '%s/qgis_plugin/qmagery/%s' % (RAW, meta.get('icon', 'resources/icons/icon64.png')),
        'author_name': meta.get('author', ''),
        'download_url': '%s/releases/download/v%s/%s' % (REPO, version, zip_name(version)),
        'uploaded_by': 'Yiuky',
        'create_date': date + 'T00:00:00',
        'update_date': date + 'T00:00:00',
        'experimental': 'True' if exp else 'False',
        'deprecated': 'False',
        'tracker': meta.get('tracker', REPO + '/issues'),
        'repository': meta.get('repository', REPO),
        'tags': meta.get('tags', ''),
        'downloads': '0',
        'average_vote': '0',
        'rating_votes': '0',
        'external_dependencies': '',
        'server': 'False',
        'category': meta.get('category', 'Raster'),
    }


def read_entries(path=XML_PATH):
    if not os.path.exists(path):
        return []
    out = []
    for node in ET.parse(path).getroot().findall('pyqgis_plugin'):
        e = {'name': node.get('name'), 'version': node.get('version')}
        for f in FIELDS:
            child = node.find(f)
            e[f] = (child.text or '') if child is not None else ''
        e['version'] = node.get('version') or e.get('version')
        out.append(e)
    return out


def _cdata(text):
    return '<![CDATA[%s]]>' % (text or '').replace(']]>', ']]]]><![CDATA[>')


def render(entries):
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<!-- Repositório de plugins do QGIS para o QMagery. Gerado por tools/qgis_repo.py: não edite à mão. -->',
             '<plugins>']
    for e in entries:
        lines.append('  <pyqgis_plugin name="%s" version="%s">' % (e['name'], e['version']))
        for f in FIELDS:
            value = e.get(f, '')
            if f in ('description', 'about', 'changelog', 'tags'):
                lines.append('    <%s>%s</%s>' % (f, _cdata(value), f))
            else:
                value = (value or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                lines.append('    <%s>%s</%s>' % (f, value, f))
        lines.append('  </pyqgis_plugin>')
    lines.append('</plugins>')
    return '\n'.join(lines) + '\n'


def update(version, xml_path=XML_PATH, meta=None, date=None):
    """Grava/atualiza a entrada do canal da versão (estável ou experimental) e mantém a do outro canal.
    Uma versão mais velha que a já publicada no mesmo canal não substitui a entrada. Retorna True se mudou."""
    meta = meta or read_metadata()
    date = date or datetime.date.today().isoformat()
    if meta.get('version') != qgis_version(version):
        raise SystemExit('metadata.txt tem version=%s; esperado %s para a tag v%s'
                         % (meta.get('version'), qgis_version(version), version))
    new = entry(version, meta, date)
    channel = new['experimental']
    current = read_entries(xml_path)
    same = [e for e in current if e.get('experimental') == channel]
    other = [e for e in current if e.get('experimental') != channel]
    if same and version_key(same[0]['version']) > version_key(new['version']):
        print('plugins.xml: %s já publicada no canal; %s não substitui' % (same[0]['version'], new['version']))
        return False
    if same:
        new['create_date'] = same[0].get('create_date') or new['create_date']
    # estável primeiro; uma experimental mais velha que a estável não serve a ninguém
    stable = new if channel == 'False' else (other[0] if other else None)
    exp = new if channel == 'True' else (other[0] if other else None)
    if stable and exp and version_key(exp['version']) <= version_key(stable['version']):
        exp = None
    entries = [e for e in (stable, exp) if e]
    text = render(entries)
    old = io.open(xml_path, encoding='utf-8').read() if os.path.exists(xml_path) else None
    if text == old:
        return False
    with io.open(xml_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    print('plugins.xml: %s' % ', '.join('%s (%s)' % (e['version'], 'experimental' if e['experimental'] == 'True'
                                                      else 'estável') for e in entries))
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[1])
    ap.add_argument('version', help='versão da tag, sem o v (ex.: 2.4.3 ou 2.4.3-nightly.20261002)')
    ap.add_argument('--xml', default=XML_PATH)
    ap.add_argument('--metadata', default=METADATA)
    ap.add_argument('--date', default=None)
    a = ap.parse_args(argv)
    update(a.version, a.xml, read_metadata(a.metadata), a.date)


if __name__ == '__main__':
    sys.exit(main())
