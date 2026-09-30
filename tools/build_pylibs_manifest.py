# -*- coding: utf-8 -*-
"""Gera arcgis_addin/Install/backend/pylibs_manifest.json (ferramenta do mantenedor, precisa de pip).

Resolve earthengine-api e dependencias com `pip download`, e para cada pacote escolhe no PyPI as rodas
que funcionam sem compilador: pura (py3-none-any) > ABI estavel (abi3, win_amd64) > uma por versao do
CPython (cp310..cp314, win_amd64). Grava URL, tamanho e SHA-256 de cada arquivo.

Uso:  <python3 com pip> tools/build_pylibs_manifest.py [earthengine-api==X.Y.Z]
"""
import json
import os
import re
import ssl
import subprocess
import sys
import tempfile
import urllib.request

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
OUT = os.path.join(REPO, 'arcgis_addin', 'Install', 'backend', 'pylibs_manifest.json')
CPYTHONS = ['cp310', 'cp311', 'cp312', 'cp313', 'cp314']
# Sem uso pelo ArcMagery e so com rodas compiladas: a importacao do 'ee' funciona sem eles
OPTIONAL = {'google-crc32c'}
# Ja vem no Python do QGIS / nao precisam ir junto
SKIP = set()


def _ctx():
    ctx = ssl.create_default_context()
    if hasattr(ssl, 'enum_certificates'):
        for store in ('ROOT', 'CA'):
            for cert, enc, trust in ssl.enum_certificates(store):
                if enc == 'x509_asn':
                    try:
                        ctx.load_verify_locations(cadata=cert)
                    except Exception:
                        pass
    return ctx


def norm(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def resolve(req):
    tmp = tempfile.mkdtemp()
    subprocess.check_call([sys.executable, '-m', 'pip', 'download', req, '-d', tmp, '-q',
                           '--disable-pip-version-check'])
    pins = {}
    for f in os.listdir(tmp):
        m = re.match(r'^([A-Za-z0-9_.]+?)-(\d[^-]*)-', f) or re.match(r'^(.+)-(\d[^-]*)\.tar\.gz$', f)
        if m:
            pins[norm(m.group(1))] = m.group(2)
    return pins


def pick(name, version):
    data = json.load(urllib.request.urlopen('https://pypi.org/pypi/%s/%s/json' % (name, version), context=_ctx()))
    wheels = [u for u in data['urls'] if u['packagetype'] == 'bdist_wheel']

    def entry(u, python):
        return {'filename': u['filename'], 'url': u['url'], 'sha256': u['digests']['sha256'],
                'size': u['size'], 'python': python}

    pure = [u for u in wheels if u['filename'].endswith('-none-any.whl')]
    if pure:
        return [entry(pure[0], 'any')]
    abi3 = [u for u in wheels if '-abi3-win_amd64' in u['filename']]
    if abi3:
        def low(u):
            return int(re.search(r'-cp(\d)(\d+)-abi3', u['filename']).group(2))
        u = sorted(abi3, key=low)[0]
        return [entry(u, 'abi3:3.%d' % low(u))]
    out = []
    for cp in CPYTHONS:
        match = [u for u in wheels if '-%s-%s-win_amd64' % (cp, cp) in u['filename']]
        if match:
            out.append(entry(match[0], cp))
    return out


def main():
    req = sys.argv[1] if len(sys.argv) > 1 else 'earthengine-api'
    pins = resolve(req)
    packages = []
    for name, version in sorted(pins.items()):
        if name in SKIP:
            continue
        files = pick(name, version)
        if not files and name not in OPTIONAL:
            sys.exit('Sem roda utilizavel para %s %s' % (name, version))
        if name in OPTIONAL:
            continue
        packages.append({'name': name, 'version': version, 'files': files})
        print('%-28s %-10s %s' % (name, version, ', '.join(f['python'] for f in files)))
    manifest = {'earthengine_api': pins.get('earthengine-api'), 'requirement': req, 'packages': packages}
    with open(OUT, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(manifest, f, indent=1, ensure_ascii=False)
        f.write('\n')
    print('Gravado:', OUT)


if __name__ == '__main__':
    main()
