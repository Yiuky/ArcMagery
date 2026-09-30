# -*- coding: utf-8 -*-
"""Gera os manifestos de backend/pylibs (ferramenta do mantenedor, precisa de pip).

Resolve earthengine-api e dependencias com `pip download`, e para cada pacote escolhe no PyPI as rodas
que funcionam sem compilador: pura (py3-none-any) > ABI estavel (abi3, win_amd64) > uma por versao do
CPython (win_amd64). Grava URL, tamanho e SHA-256 de cada arquivo.

Uso:  <python3 com pip> tools/build_pylibs_manifest.py [earthengine-api==X.Y.Z]
          -> pylibs_manifest.json (CPython 3.10 a 3.14)
      <python3 com pip> tools/build_pylibs_manifest.py --python 3.9
          -> pylibs_manifest_py39.json, resolvido para aquela versao (QGIS antigos, ex.: 3.26 = Python 3.9)
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


def resolve(req, python=None):
    tmp = tempfile.mkdtemp()
    cmd = [sys.executable, '-m', 'pip', 'download', req, '-d', tmp, '-q', '--disable-pip-version-check']
    if python:
        cmd += ['--only-binary=:all:', '--platform', 'win_amd64', '--python-version', python, '--implementation', 'cp']
    subprocess.check_call(cmd)
    pins = {}
    for f in os.listdir(tmp):
        m = re.match(r'^([A-Za-z0-9_.]+?)-(\d[^-]*)-', f) or re.match(r'^(.+)-(\d[^-]*)\.tar\.gz$', f)
        if m:
            pins[norm(m.group(1))] = m.group(2)
    return pins


def pick(name, version, cpythons):
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
    for cp in cpythons:
        match = [u for u in wheels if '-%s-%s-win_amd64' % (cp, cp) in u['filename']]
        if match:
            out.append(entry(match[0], cp))
    return out


def main():
    args = sys.argv[1:]
    python = None
    if '--python' in args:
        i = args.index('--python')
        python = args[i + 1]
        del args[i:i + 2]
    req = args[0] if args else 'earthengine-api'
    pins = resolve(req, python)
    cpythons = ['cp' + python.replace('.', '')] if python else CPYTHONS
    out = OUT if not python else OUT.replace('.json', '_py%s.json' % python.replace('.', ''))
    packages = []
    for name, version in sorted(pins.items()):
        if name in OPTIONAL:
            continue
        files = pick(name, version, cpythons)
        if not files:
            sys.exit('Sem roda utilizavel para %s %s' % (name, version))
        packages.append({'name': name, 'version': version, 'files': files})
        print('%-28s %-10s %s' % (name, version, ', '.join(f['python'] for f in files)))
    manifest = {'earthengine_api': pins.get('earthengine-api'), 'requirement': req,
                'python': python or '3.10-3.14', 'packages': packages}
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(manifest, f, indent=1, ensure_ascii=False)
        f.write('\n')
    print('Gravado:', out)


if __name__ == '__main__':
    main()
