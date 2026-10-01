# -*- coding: utf-8 -*-
"""
Gera os artefatos de uma GitHub Release do ArcMagery (Python 2.7 ou 3.x):

    dist/ArcMagery-<versao>.zip   -> arquivos versionados (git ls-files), mesmo layout do
                                     "Download ZIP" do GitHub (pasta raiz ArcMagery-<versao>/)
    dist/SHA256SUMS.txt           -> hash SHA-256 do pacote (formato do `sha256sum`)

Publicacao (o atualizador embutido so aceita Releases com SHA256SUMS.txt):
    python build_release.py
    gh release create v<versao> dist/ArcMagery-<versao>.zip dist/SHA256SUMS.txt \
        --title "ArcMagery v<versao>" --notes-file CHANGELOG.md

A versao vem de arcgis_addin/config.xml (<Version>); a tag deve ser v<versao>.
"""
from __future__ import print_function

import hashlib
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
NS = {'e': 'http://schemas.esri.com/Desktop/AddIns'}


def read_version():
    tree = ET.parse(os.path.join(ROOT, 'arcgis_addin', 'config.xml'))
    node = tree.getroot().find('e:Version', NS)
    if node is None or not (node.text or '').strip():
        raise SystemExit("config.xml sem <Version>")
    return node.text.strip()


def tracked_files():
    out = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT)
    if not isinstance(out, str):
        out = out.decode('utf-8')
    return sorted(f for f in out.split('\0') if f)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def commit_time():
    """Data do ultimo commit (UTC), usada em todas as entradas do ZIP: o mesmo commit gera o mesmo pacote."""
    try:
        ts = int(subprocess.check_output(['git', 'log', '-1', '--format=%ct'], cwd=ROOT).strip())
    except Exception:
        ts = 315532800  # 1980-01-01, menor data aceita pelo formato ZIP
    return time.gmtime(max(ts, 315532800))[:6]


def warn_if_dirty():
    try:
        dirty = subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=ROOT).strip()
    except Exception:
        return
    if dirty:
        print('AVISO: ha alteracoes nao commitadas; o pacote usa os arquivos do disco, nao o commit.')


def build(dist_dir=None):
    version = read_version()
    warn_if_dirty()
    dist_dir = dist_dir or os.path.join(ROOT, 'dist')
    if not os.path.isdir(dist_dir):
        os.makedirs(dist_dir)
    name = 'ArcMagery-%s.zip' % version
    zip_path = os.path.join(dist_dir, name)
    prefix = 'ArcMagery-%s/' % version
    files = [f for f in tracked_files() if not f.startswith('dist/')]
    stamp = commit_time()
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for rel in files:
            full = os.path.join(ROOT, rel)
            if os.path.isfile(full):
                info = zipfile.ZipInfo(prefix + rel, date_time=stamp)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                with open(full, 'rb') as src:
                    z.writestr(info, src.read())
    digest = sha256_of(zip_path)
    # binario + "\n": formato aceito pelo `sha256sum -c` em qualquer sistema (sem CRLF do Windows)
    with open(os.path.join(dist_dir, 'SHA256SUMS.txt'), 'wb') as f:
        f.write(('%s  %s\n' % (digest, name)).encode('ascii'))
    print('Pacote : %s (%d arquivos)' % (zip_path, len(files)))
    print('SHA-256: %s' % digest)
    return zip_path, digest


if __name__ == '__main__':
    build(sys.argv[1] if len(sys.argv) > 1 else None)
