# -*- coding: utf-8 -*-
"""
ArcMagery - bibliotecas Python 3 do backend SEM pip (earthengine-api e dependencias).

Por que: o pip das maquinas da SEMA falha com a inspecao SSL do proxy e, sem o earthengine-api, o
GEE quebra com "No module named 'ee'". Aqui as rodas (wheels) fixadas em pylibs_manifest.json sao
baixadas com urllib usando os certificados do Windows, conferidas por SHA-256 e extraidas em
%LOCALAPPDATA%\\ArcMagery\\pylibs\\py3XY. Qualquer Python 3.10+ de 64 bits (o do QGIS basta: ele ja
traz GDAL, numpy e Pillow) passa a importar o 'ee' - sem venv, sem pip, sem compilador.

activate() so acrescenta a pasta ao sys.path (barato: chamado no inicio do run_gee.py).
"""
import hashlib
import io
import json
import os
import shutil
import ssl
import sys
import tempfile
import time
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(HERE, 'pylibs_manifest.json')
USER_AGENT = 'ArcMagery/2.0 (+https://github.com/Yiuky/arcgis-google-earth-engine-explorer)'
# Diretorios grandes que o ArcMagery nao usa (o 'ee' busca o documento de descoberta no servidor)
PRUNE = [os.path.join('googleapiclient', 'discovery_cache', 'documents')]
MARKER = 'arcmagery_pylibs.json'


class PylibsError(RuntimeError):
    pass


def _log(msg):
    sys.stderr.write("[ArcGEE] " + msg + "\n")
    sys.stderr.flush()


def py_tag(version_info=None):
    v = version_info or sys.version_info
    return 'py%d%d' % (v[0], v[1])


def base_dir():
    return os.path.join(os.environ.get('LOCALAPPDATA') or tempfile.gettempdir(), 'ArcMagery', 'pylibs')


def target_dir(version_info=None):
    return os.path.join(base_dir(), py_tag(version_info))


def activate(force=False):
    """Poe a pasta de bibliotecas no inicio do sys.path se este Python nao tiver o 'ee' proprio
    (um venv que ja funciona nao muda). Retorna o caminho ativado ou None."""
    d = target_dir()
    if not os.path.isdir(d):
        return None
    if d in sys.path:
        return d
    if not force:
        import importlib.util
        try:
            if importlib.util.find_spec('ee') is not None:
                return None
        except Exception:
            pass
    sys.path.insert(0, d)
    return d


def load_manifest(path=MANIFEST):
    with io.open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def manifest_id(manifest):
    return hashlib.sha256(json.dumps(manifest, sort_keys=True).encode('utf-8')).hexdigest()[:16]


def _compatible(entry, version_info):
    """entry['python']: 'any' | 'abi3:3.9' (CPython >= 3.9, ABI estavel) | 'cp312'."""
    tag = entry.get('python', 'any')
    if tag == 'any':
        return 0
    if tag.startswith('abi3:'):
        major, minor = [int(x) for x in tag[5:].split('.')]
        return 1 if (version_info[0], version_info[1]) >= (major, minor) else None
    if tag == 'cp%d%d' % (version_info[0], version_info[1]):
        return 2
    return None


def select_files(manifest, version_info=None):
    """Uma roda por pacote, compativel com este Python (pura > abi3 > especifica). Erro se faltar."""
    vi = version_info or sys.version_info
    chosen, missing = [], []
    for pkg in manifest['packages']:
        best = None
        for f in pkg['files']:
            rank = _compatible(f, vi)
            if rank is not None and (best is None or rank < best[0]):
                best = (rank, f)
        if best:
            chosen.append(dict(best[1], package=pkg['name'], version=pkg['version']))
        elif not pkg.get('optional'):
            missing.append(pkg['name'])
    if missing:
        raise PylibsError(u"Sem roda compatível com o Python %d.%d para: %s. Use um Python 3.10 a 3.14 de 64 bits "
                          u"(ex.: o do QGIS 3.34+)." % (vi[0], vi[1], ', '.join(missing)))
    return chosen


def ssl_context():
    """Contexto que confia no repositorio de certificados do Windows (CA do proxy corporativo)."""
    ctx = ssl.create_default_context()
    if hasattr(ssl, 'enum_certificates'):
        for store in ('ROOT', 'CA'):
            try:
                for cert, enc, trust in ssl.enum_certificates(store):
                    if enc == 'x509_asn' and (trust is True or '1.3.6.1.5.5.7.3.1' in (trust or ())):
                        try:
                            ctx.load_verify_locations(cadata=cert)
                        except Exception:
                            pass
            except Exception:
                pass
    return ctx


def _download(url, dest, sha256, opener=None, retries=3):
    opener = opener or (lambda req: urllib.request.urlopen(req, timeout=120, context=ssl_context()))
    last = None
    for attempt in range(1, retries + 1):
        try:
            h = hashlib.sha256()
            with opener(urllib.request.Request(url, headers={'User-Agent': USER_AGENT})) as r, open(dest, 'wb') as out:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    h.update(chunk)
                    out.write(chunk)
            if h.hexdigest() != sha256:
                raise PylibsError(u"SHA-256 não confere: %s" % os.path.basename(dest))
            return dest
        except ssl.SSLError as e:
            raise PylibsError(u"Erro SSL ao baixar %s: %s" % (os.path.basename(dest), e))
        except Exception as e:
            last = e
            time.sleep(1.5 * attempt)
    raise PylibsError(u"Falha ao baixar %s: %s" % (os.path.basename(dest), last))


def status(manifest=None, version_info=None):
    """{'installed', 'current', 'dir', 'manifest_id', ...} sem importar nada."""
    manifest = manifest or load_manifest()
    d = target_dir(version_info)
    info = {'dir': d, 'installed': False, 'current': False, 'manifest_id': manifest_id(manifest),
            'earthengine_api': manifest.get('earthengine_api')}
    marker = os.path.join(d, MARKER)
    if os.path.exists(marker):
        try:
            with io.open(marker, 'r', encoding='utf-8') as f:
                m = json.load(f)
            info.update(installed=True, current=m.get('manifest_id') == info['manifest_id'],
                        installed_at=m.get('installed_at'), installed_ee=m.get('earthengine_api'))
        except Exception:
            pass
    return info


def install(manifest=None, opener=None, force=False, version_info=None):
    """Baixa, confere e extrai as rodas para target_dir(). Idempotente (pula se ja estiver atual)."""
    manifest = manifest or load_manifest()
    st = status(manifest, version_info)
    if st['current'] and not force:
        _log(u"Bibliotecas do Earth Engine já instaladas (%s)." % st['dir'])
        return dict(st, skipped=True)
    files = select_files(manifest, version_info)
    final = target_dir(version_info)
    os.makedirs(base_dir(), exist_ok=True)
    work = tempfile.mkdtemp(prefix='arcmagery_pylibs_', dir=base_dir())
    try:
        wheels = os.path.join(work, 'wheels')
        stage = os.path.join(work, 'lib')
        os.makedirs(wheels)
        os.makedirs(stage)
        total = sum(int(f.get('size') or 0) for f in files) or 1
        done = 0
        for i, f in enumerate(files, 1):
            _log(u"Baixando componentes do Earth Engine: %d/%d %s" % (i, len(files), f['filename']))
            path = _download(f['url'], os.path.join(wheels, f['filename']), f['sha256'], opener=opener)
            with zipfile.ZipFile(path) as z:
                z.extractall(stage)
            done += int(f.get('size') or 0)
            _log(u"PROGRESS %d/100" % min(99, int(100 * done / total)))
        for rel in PRUNE:
            shutil.rmtree(os.path.join(stage, rel), ignore_errors=True)
        with io.open(os.path.join(stage, MARKER), 'w', encoding='utf-8') as out:
            out.write(json.dumps({'manifest_id': manifest_id(manifest), 'earthengine_api': manifest.get('earthengine_api'),
                                  'installed_at': time.strftime('%Y-%m-%d %H:%M:%S'),
                                  'files': [f['filename'] for f in files]}, ensure_ascii=False))
        old = final + '.old'
        if os.path.isdir(old):
            shutil.rmtree(old, ignore_errors=True)
        if os.path.isdir(final):
            os.replace(final, old)
        os.replace(stage, final)
        shutil.rmtree(old, ignore_errors=True)
        _log(u"Componentes do Earth Engine instalados em %s" % final)
        return dict(status(manifest, version_info), skipped=False, files=len(files))
    finally:
        shutil.rmtree(work, ignore_errors=True)


def ee_version():
    """Versao do 'ee' importavel neste processo (com a pasta ativada) ou None."""
    activate()
    try:
        import ee
        return getattr(ee, '__version__', '?')
    except Exception:
        return None
