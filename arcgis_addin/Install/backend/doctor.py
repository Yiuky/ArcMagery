# -*- coding: utf-8 -*-
"""
ArcMagery - diagnostico do ambiente com correcao automatica (install.bat e tela de abertura).

Cada verificacao devolve {id, title, status, detail, fix, remediation}:
  status: ok | warn | fail | fixed  (fixed = havia problema e foi corrigido agora)
Correcoes automaticas (so as seguras e reversiveis):
  * instala os componentes do Earth Engine sem pip (pylibs) quando faltam ou estao desatualizados;
  * tira de uso um venv antigo quebrado (renomeia para venv.quebrado_<data>), para o ArcMagery usar o
    Python do QGIS.
O resto vira orientacao objetiva. O relatorio vai para %LOCALAPPDATA%\\ArcMagery\\diagnostico.txt.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# <QGIS>\bin antes do ssl/urllib: no QGIS 3.26 (Python 3.9) o _ssl usa o libssl de la ("DLL load failed")
import qgis_env  # noqa: E402,F401
import ssl  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402

import pylibs  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OK, WARN, FAIL, FIXED = 'ok', 'warn', 'fail', 'fixed'
SERVICES = [
    ('pypi', u"PyPI (componentes do Earth Engine)", 'https://files.pythonhosted.org/'),
    ('google', u"Google Earth Engine", 'https://earthengine.googleapis.com/$discovery/rest?version=v1'),
    ('github', u"GitHub (atualizações)", 'https://api.github.com/'),
    ('inpe', u"INPE (CBERS)", 'https://data.inpe.br/bdc/stac/v1/'),
    ('geodes', u"GEODES (SPOT)", 'https://geodes-portal.cnes.fr/api/stac'),
    ('esri', u"Esri (mosaicos e alinhamento)",
     'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer?f=json'),
]


def local_dir():
    return os.path.join(os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'), 'ArcMagery')


def check(cid, title, status, detail=u'', fix=None, remediation=None):
    return {'id': cid, 'title': title, 'status': status, 'detail': detail, 'fix': fix,
            'remediation': remediation or []}


# ------------------------------------------------------------------------------ checagens
def check_python():
    v = sys.version_info
    bits = 64 if sys.maxsize > 2 ** 32 else 32
    detail = u"Python %d.%d.%d %d bits (%s)" % (v[0], v[1], v[2], bits, sys.executable)
    if bits != 64:
        return check('python', u"Python 3 do backend", FAIL, detail,
                     remediation=[u"Instale o QGIS 3.x de 64 bits (o ArcMagery usa o Python dele)."])
    if (v[0], v[1]) < (3, 8):
        return check('python', u"Python 3 do backend", FAIL, detail,
                     remediation=[u"Python antigo demais para o Earth Engine: instale o QGIS 3.28 ou mais novo."])
    if (v[0], v[1]) < (3, 10):
        return check('python', u"Python 3 do backend", WARN, detail,
                     remediation=[u"Funciona, mas o Google não atualiza mais as bibliotecas do Earth Engine para o "
                                  u"Python %d.%d (QGIS 3.26 ou anterior): atualize o QGIS (3.40 LTR ou mais novo)."
                                  % (v[0], v[1])])
    return check('python', u"Python 3 do backend", OK, detail)


def check_libs():
    import qgis_env  # noqa: F401  (DLLs do QGIS antes do GDAL - sem isso o _ssl/GDAL do QGIS nao carregam)
    found, missing = [], []
    for mod, label in (('osgeo.gdal', 'GDAL'), ('numpy', 'numpy'), ('PIL', 'Pillow')):
        try:
            m = __import__(mod, fromlist=['x'])
            found.append(u"%s %s" % (label, getattr(m, '__version__', '')))
        except Exception as e:
            missing.append(u"%s (%s)" % (label, str(e)[:80]))
    if not missing:
        return check('libs', u"Bibliotecas de imagem", OK, u" · ".join(found))
    status = FAIL if any(m.startswith('GDAL') for m in missing) else WARN
    return check('libs', u"Bibliotecas de imagem", status, u"Ausentes: %s" % u", ".join(missing),
                 remediation=[u"CBERS e SPOT precisam do GDAL: reinstale ou atualize o QGIS 3.x.",
                              u"O Google Earth Engine e os mosaicos XYZ continuam funcionando."])


def probe(url, ctx, timeout=15, attempts=2):
    last = u''
    for _ in range(attempts):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'ArcMagery-doctor'})
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                return True, u"HTTP %d" % r.status
        except urllib.error.HTTPError as e:     # o servidor respondeu: rede e certificado estao ok
            return True, u"HTTP %d" % e.code
        except ssl.SSLError as e:
            return False, u"certificado recusado (%s)" % str(e)[:80]
        except Exception as e:
            last = str(e)[:120]
    return False, last


def check_network():
    import concurrent.futures
    import encodings.idna  # noqa: F401  (import em threads paralelas falha: "unknown encoding: idna")
    ctx = pylibs.ssl_context()
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(SERVICES)) as pool:
        res = dict((sid, pool.submit(probe, url, ctx)) for sid, _t, url in SERVICES)
        res = dict((k, f.result()) for k, f in res.items())
    down = [(t, res[s][1]) for s, t, _u in SERVICES if not res[s][0]]
    if not down:
        return check('net', u"Internet e certificados", OK, u"%d serviços acessíveis" % len(SERVICES)), res
    ssl_problem = any(u'certificado' in d for _t, d in down)
    rem = [u"Verifique a conexão; em rede corporativa, o proxy precisa liberar: %s." % u", ".join(t for t, _d in down)]
    if ssl_problem:
        rem.append(u"Certificado recusado: a CA do proxy precisa estar no repositório de certificados do Windows "
                   u"(peça à TI) - o ArcMagery usa esse repositório.")
    status = FAIL if len(down) == len(SERVICES) else WARN
    return check('net', u"Internet e certificados", status,
                 u"; ".join(u"%s: %s" % d for d in down), remediation=rem), res


def ee_import_check():
    """Importa o 'ee' num processo novo (com a pasta de componentes), como o plugin fara."""
    code = ("import sys; sys.path.insert(0, %r); import qgis_env, pylibs; pylibs.activate(); import ee; "
            "print(ee.__version__)" % HERE)
    flags = ['-I'] if sys.flags.isolated else []
    try:
        p = subprocess.run([sys.executable] + flags + ['-c', code], capture_output=True, text=True, timeout=180)
        if p.returncode == 0 and p.stdout.strip():
            return p.stdout.strip().splitlines()[-1], None
        return None, (p.stderr or p.stdout).strip().splitlines()[-1:] or [u'erro']
    except Exception as e:
        return None, [str(e)]


def check_ee(fix=True, network_ok=True):
    title = u"Componentes do Earth Engine"
    try:
        st = pylibs.status()
    except Exception as e:
        return check('ee', title, FAIL, u"Manifesto ilegível: %s" % e,
                     remediation=[u"Reinstale o ArcMagery (arquivos do backend incompletos)."])
    version, err = ee_import_check()
    if version and st['current']:
        return check('ee', title, OK, u"earthengine-api %s" % version)
    if version and not st['installed']:
        return check('ee', title, OK, u"earthengine-api %s (instalado no próprio Python)" % version)
    if not fix:
        return check('ee', title, FAIL, u"Ausentes ou desatualizados", remediation=[
            u"Clique em \"Instalar componentes do Earth Engine\" na tela de abertura ou rode o install.bat."])
    if not network_ok:
        return check('ee', title, FAIL, u"Ausentes e sem acesso ao PyPI para instalá-los", remediation=[
            u"Libere files.pythonhosted.org no proxy e rode o install.bat de novo."])
    try:
        pylibs.install()
    except Exception as e:
        return check('ee', title, FAIL, u"Falha ao instalar: %s" % e, remediation=[
            u"Verifique a internet/proxy e rode o install.bat de novo.",
            u"Veja %s" % os.path.join(local_dir(), 'diagnostico.txt')])
    version, err = ee_import_check()
    if version:
        return check('ee', title, FIXED, u"earthengine-api %s" % version,
                     fix=u"Instalados sem pip em %s" % pylibs.target_dir())
    return check('ee', title, FAIL, u"Instalados, mas o 'ee' não importa: %s" % u" ".join(err or []),
                 remediation=[u"Envie o arquivo %s ao responsável pelo plugin." % os.path.join(local_dir(), 'diagnostico.txt')])


def gee_credentials_path():
    return os.path.join(os.path.expanduser('~'), '.config', 'earthengine', 'credentials')


def gee_project():
    cfg = os.path.join(os.environ.get('APPDATA') or os.path.expanduser('~'), 'ArcGEE', 'gee_config.json')
    try:
        with io.open(cfg, 'r', encoding='utf-8') as f:
            return (json.load(f).get('project') or u'').strip()
    except Exception:
        return u''


def check_gee_login(ee_ok, network_ok, test=True):
    title = u"Login do Google Earth Engine"
    if not os.path.exists(gee_credentials_path()):
        return check('gee', title, WARN, u"Conta Google ainda não autenticada neste computador", remediation=[
            u"Rode autenticar_gee.bat (ou o botão \"Autenticar GEE\" na janela) e entre com a sua conta Google."])
    project = gee_project()
    if not project:
        return check('gee', title, WARN, u"Autenticado, mas sem ID de projeto", remediation=[
            u"Na janela do ArcMagery, clique em \"Configurar Projeto GEE\" e informe o ID do projeto Google Cloud."])
    if not (test and ee_ok and network_ok):
        return check('gee', title, OK, u"Credenciais e projeto '%s' configurados (conexão não testada)" % project)
    code = ("import sys; sys.path.insert(0, %r); import qgis_env, pylibs; pylibs.activate(); import ee; "
            "ee.Initialize(project=%r); print('OK', ee.Number(1).add(1).getInfo())" % (HERE, project))
    flags = ['-I'] if sys.flags.isolated else []
    try:
        p = subprocess.run([sys.executable] + flags + ['-c', code], capture_output=True, text=True, timeout=120)
        out = (p.stdout or '') + (p.stderr or '')
    except Exception as e:
        out = str(e)
    if 'OK 2' in out:
        return check('gee', title, OK, u"Conectado (projeto '%s')" % project)
    last = [l for l in out.strip().splitlines() if l.strip()][-1:] or [u'sem resposta']
    rem = [u"Rode autenticar_gee.bat de novo (a credencial pode ter expirado)."]
    if 'not been used' in out or 'SERVICE_DISABLED' in out or 'not registered' in out.lower():
        rem = [u"Habilite a Earth Engine API no projeto '%s' (console.cloud.google.com) ou informe outro projeto." % project]
    return check('gee', title, FAIL, u"Falha ao conectar: %s" % last[0][:200], remediation=rem)


def check_old_venv(fix=True):
    venv = os.path.join(local_dir(), 'venv')
    cfg = os.path.join(venv, 'pyvenv.cfg')
    title = u"Ambiente Python antigo (venv)"
    if not os.path.isdir(venv):
        return check('venv', title, OK, u"Não usado (o ArcMagery usa o Python do QGIS)")
    home = None
    try:
        with io.open(cfg, 'r', encoding='utf-8') as f:
            for line in f:
                if line.lower().startswith('home'):
                    home = line.split('=', 1)[1].strip()
    except Exception:
        pass
    py = os.path.join(venv, 'Scripts', 'python.exe')
    healthy = os.path.exists(py) and home and os.path.isdir(home)
    if healthy:
        return check('venv', title, OK, u"Em uso e íntegro (base: %s)" % home)
    if not fix:
        return check('venv', title, FAIL, u"Quebrado (o Python base %s não existe mais)" % (home or u'?'),
                     remediation=[u"Rode o install.bat: ele tira o venv quebrado de uso."])
    dest = venv + '.quebrado_' + time.strftime('%Y%m%d_%H%M%S')
    try:
        os.rename(venv, dest)
        return check('venv', title, FIXED, u"Estava quebrado (base %s ausente)" % (home or u'?'),
                     fix=u"Renomeado para %s; o ArcMagery passa a usar o Python do QGIS" % os.path.basename(dest))
    except Exception as e:
        return check('venv', title, FAIL, u"Quebrado e não pôde ser renomeado: %s" % e,
                     remediation=[u"Feche o ArcMap/ArcMagery e apague %s." % venv])


def check_disk():
    base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    try:
        free = shutil.disk_usage(base).free / 1e9
    except Exception:
        return check('disk', u"Espaço em disco", WARN, u"Não verificado")
    if free < 0.5:
        return check('disk', u"Espaço em disco", FAIL, u"%.1f GB livres" % free,
                     remediation=[u"Libere espaço: os downloads e componentes precisam de pelo menos 0,5 GB."])
    return check('disk', u"Espaço em disco", OK if free >= 2 else WARN, u"%.1f GB livres" % free,
                 remediation=[] if free >= 2 else [u"Pouco espaço: cenas SPOT e mosaicos grandes podem falhar."])


def check_install_path(path):
    if not path:
        return None
    n = len(os.path.abspath(path))
    if n > 120:
        return check('path', u"Pasta do instalador", WARN, u"Caminho com %d caracteres: %s" % (n, path), remediation=[
            u"Extraia o pacote numa pasta curta (ex.: C:\\ArcMagery): caminhos longos passam do limite de 260 "
            u"caracteres do Windows e arquivos do ZIP podem não ser extraídos."])
    return check('path', u"Pasta do instalador", OK, u"%d caracteres" % n)


# ------------------------------------------------------------------------------ execucao
def run(fix=True, test_gee=True, install_path=None):
    results = [check_python()]
    results.append(check_libs())
    net, per = check_network()
    results.append(net)
    pypi_ok = per.get('pypi', (False,))[0]
    results.append(check_old_venv(fix=fix))
    ee = check_ee(fix=fix, network_ok=pypi_ok)
    results.append(ee)
    results.append(check_gee_login(ee['status'] in (OK, FIXED), per.get('google', (False,))[0], test=test_gee))
    results.append(check_disk())
    p = check_install_path(install_path)
    if p:
        results.append(p)
    counts = dict((s, sum(1 for r in results if r['status'] == s)) for s in (OK, WARN, FAIL, FIXED))
    report = write_report(results, counts)
    return {'success': counts[FAIL] == 0, 'checks': results, 'counts': counts, 'report': report,
            'python': sys.executable}


ICON = {OK: u'[OK]     ', WARN: u'[AVISO]  ', FAIL: u'[PROBLEMA]', FIXED: u'[CORRIGIDO]'}


def format_text(res):
    lines = []
    for r in res['checks']:
        lines.append(u"%s %s: %s" % (ICON[r['status']], r['title'], r['detail']))
        if r.get('fix'):
            lines.append(u"            -> corrigido: %s" % r['fix'])
        for step in r.get('remediation') or []:
            if r['status'] in (WARN, FAIL):
                lines.append(u"            -> o que fazer: %s" % step)
    c = res['counts']
    lines.append(u"")
    lines.append(u"Resumo: %d ok, %d corrigido(s), %d aviso(s), %d problema(s). Relatório: %s"
                 % (c[OK], c[FIXED], c[WARN], c[FAIL], res.get('report')))
    return u"\n".join(lines)


def write_report(results, counts):
    path = os.path.join(local_dir(), 'diagnostico.txt')
    try:
        os.makedirs(local_dir(), exist_ok=True)
        body = format_text({'checks': results, 'counts': counts, 'report': path})
        with io.open(path, 'w', encoding='utf-8') as f:
            f.write(u"Diagnóstico do ArcMagery - %s\nPython: %s\n\n%s\n" % (time.strftime('%d/%m/%Y %H:%M'),
                                                                          sys.executable, body))
        return path
    except Exception:
        return None
