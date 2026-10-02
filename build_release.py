# -*- coding: utf-8 -*-
"""
Gera os artefatos de uma GitHub Release (Python 2.7 ou 3.x):

    dist/ArcMagery-<versao>.zip   -> arquivos versionados (git ls-files), mesmo layout do
                                     "Download ZIP" do GitHub (pasta raiz ArcMagery-<versao>/)
    dist/QMagery-<versao>.zip     -> plugin do QGIS pronto para "Instalar a partir do ZIP": pasta raiz
                                     qmagery/, com o backend embutido em qmagery/backend/ e a LICENSE
    dist/SHA256SUMS.txt           -> hash SHA-256 dos dois pacotes (formato do `sha256sum`)

Publicacao (o atualizador embutido do ArcMagery so aceita Releases com SHA256SUMS.txt):
    python build_release.py
    gh release create v<versao> dist/ArcMagery-<versao>.zip dist/SHA256SUMS.txt --notes-file ...
    gh release upload v<versao> dist/QMagery-<versao>.zip
O pacote do ArcMagery deve ser o PRIMEIRO .zip da Release: os atualizadores ate a 2.4.3-nightly.20261001
usam o primeiro .zip que encontram.

A versao vem de arcgis_addin/config.xml (<Version>); a tag deve ser v<versao>. O metadata.txt do QMagery
deve ter a versao correspondente (tools/qgis_repo.qgis_version: "-nightly." vira "-beta.").
Os dois ZIPs sao reprodutiveis: o mesmo commit gera os mesmos bytes.
"""
from __future__ import print_function

import hashlib
import io
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
NS = {'e': 'http://schemas.esri.com/Desktop/AddIns'}
QMAGERY_SRC = 'qgis_plugin/qmagery/'
BACKEND_SRC = 'arcgis_addin/Install/backend/'


def read_version():
    tree = ET.parse(os.path.join(ROOT, 'arcgis_addin', 'config.xml'))
    node = tree.getroot().find('e:Version', NS)
    if node is None or not (node.text or '').strip():
        raise SystemExit("config.xml sem <Version>")
    return node.text.strip()


def qgis_version(version):
    return version.replace('-nightly.', '-beta.')


def read_qmagery_version():
    with io.open(os.path.join(ROOT, 'qgis_plugin', 'qmagery', 'metadata.txt'), encoding='utf-8') as f:
        for line in f:
            if line.startswith('version='):
                return line.split('=', 1)[1].strip()
    return None


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


def _write_zip(zip_path, members, stamp):
    """members: [(nome no zip, caminho relativo no repositorio)], gravados em ordem alfabetica."""
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for arcname, rel in sorted(members):
            full = os.path.join(ROOT, rel)
            if os.path.isfile(full):
                info = zipfile.ZipInfo(arcname, date_time=stamp)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                with open(full, 'rb') as src:
                    z.writestr(info, src.read())


def qmagery_members(files):
    """Plugin + backend embutido + LICENSE. Fora: caches, testes e o metadata de outro plugin."""
    out = []
    for rel in files:
        if '__pycache__' in rel or rel.endswith(('.pyc', '.pyo')):
            continue
        if rel.startswith(QMAGERY_SRC):
            if rel.startswith(QMAGERY_SRC + 'backend/'):
                continue   # copia local de desenvolvimento: o backend vem sempre do repositorio
            out.append(('qmagery/' + rel[len(QMAGERY_SRC):], rel))
        elif rel.startswith(BACKEND_SRC):
            out.append(('qmagery/backend/' + rel[len(BACKEND_SRC):], rel))
    if 'LICENSE' in files:
        out.append(('qmagery/LICENSE', 'LICENSE'))
    return out


def build(dist_dir=None):
    version = read_version()
    qv = read_qmagery_version()
    if qv != qgis_version(version):
        raise SystemExit('qgis_plugin/qmagery/metadata.txt tem version=%s; esperado %s (config.xml = %s)'
                         % (qv, qgis_version(version), version))
    warn_if_dirty()
    dist_dir = dist_dir or os.path.join(ROOT, 'dist')
    if not os.path.isdir(dist_dir):
        os.makedirs(dist_dir)
    files = [f for f in tracked_files() if not f.startswith('dist/')]
    stamp = commit_time()

    arc_name = 'ArcMagery-%s.zip' % version
    arc_path = os.path.join(dist_dir, arc_name)
    prefix = 'ArcMagery-%s/' % version
    _write_zip(arc_path, [(prefix + rel, rel) for rel in files], stamp)

    qm_name = 'QMagery-%s.zip' % version
    qm_path = os.path.join(dist_dir, qm_name)
    qm_members = qmagery_members(files)
    _write_zip(qm_path, qm_members, stamp)

    digests = [(sha256_of(arc_path), arc_name), (sha256_of(qm_path), qm_name)]
    # binario + "\n": formato aceito pelo `sha256sum -c` em qualquer sistema (sem CRLF do Windows)
    with open(os.path.join(dist_dir, 'SHA256SUMS.txt'), 'wb') as f:
        for digest, name in digests:
            f.write(('%s  %s\n' % (digest, name)).encode('ascii'))
    print('Pacote : %s (%d arquivos)' % (arc_path, len(files)))
    print('Pacote : %s (%d arquivos)' % (qm_path, len(qm_members)))
    for digest, name in digests:
        print('SHA-256: %s  %s' % (digest, name))
    return arc_path, digests[0][0]


if __name__ == '__main__':
    build(sys.argv[1] if len(sys.argv) > 1 else None)
