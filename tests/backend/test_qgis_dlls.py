# -*- coding: utf-8 -*-
"""B-09: backend num Python com o layout do QGIS 3.26 (Python 3.9).

Nesse QGIS o _ssl do Python carrega o libssl de <QGIS>\\bin, e nao da pasta DLLs do proprio Python:
sem o qgis_env, "import ssl" falha com "DLL load failed while importing _ssl" (relatado na
autenticacao do GEE). O teste copia o Python atual para <tmp>\\apps\\PythonXY, move o libssl e o
libcrypto para <tmp>\\bin e importa cada modulo do backend num processo novo: o import nao pode falhar
por DLL e o urllib precisa continuar com HTTPS (ele desliga o HTTPS em silencio se o _ssl falhar).
Rodado com o Python 3.9 reproduz exatamente o QGIS 3.26; com o 3.12 do CI, o mesmo mecanismo.
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import _paths

# Modulos que podem faltar no Python copiado (sem site-packages): nao sao o que o teste verifica
OPTIONAL = {'ee', 'osgeo', 'numpy', 'PIL'}
CHILD = r"""
import json, sys
sys.path.insert(0, %(backend)r)
err = None
try:
    %(stmt)s
except ImportError as e:
    err = [e.name, str(e)]
u = sys.modules.get('urllib.request')  # so conta se o proprio modulo carregou o urllib
print(json.dumps({'err': err, 'https': None if u is None else hasattr(u, 'HTTPSHandler')}))
"""


def build_fake_qgis(root):
    """<root>\\apps\\PythonXY = copia do Python atual; libssl/libcrypto em <root>\\bin. Devolve o python.exe
    ou None se este Python nao trouxer o libssl na pasta DLLs."""
    src = sys.base_prefix
    ssl_dlls = glob.glob(os.path.join(src, 'DLLs', 'libssl*.dll')) + glob.glob(os.path.join(src, 'DLLs', 'libcrypto*.dll'))
    if not ssl_dlls or not os.path.isfile(os.path.join(src, 'python.exe')):
        return None
    app = os.path.join(root, 'apps', 'Python%d%d' % sys.version_info[:2])
    os.makedirs(app)
    os.makedirs(os.path.join(root, 'bin'))
    for name in os.listdir(src):
        p = os.path.join(src, name)
        if os.path.isfile(p) and name.lower().endswith(('.exe', '.dll')):
            shutil.copy2(p, app)
    shutil.copytree(os.path.join(src, 'DLLs'), os.path.join(app, 'DLLs'))
    shutil.copytree(os.path.join(src, 'Lib'), os.path.join(app, 'Lib'), ignore=shutil.ignore_patterns(
        'site-packages', 'test', 'tests', '__pycache__', 'idlelib', 'tkinter', 'turtledemo', 'ensurepip', 'lib2to3'))
    for dll in ssl_dlls:
        shutil.move(os.path.join(app, 'DLLs', os.path.basename(dll)), os.path.join(root, 'bin'))
    return os.path.join(app, 'python.exe')


@unittest.skipUnless(os.name == 'nt', 'layout do QGIS no Windows')
class QgisBinSslTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='arcmagery_qgis326_')
        cls.py = build_fake_qgis(cls.tmp)
        env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP')}
        env['PATH'] = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32')
        env['OSGEO4W_ROOT'] = cls.tmp  # como na maquina do relato: o sitecustomize do QGIS nao registra o bin
        cls.env = env

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_child(self, stmt):
        code = CHILD % {'backend': _paths.BACKEND, 'stmt': stmt}
        p = subprocess.run([self.py, '-s', '-c', code], capture_output=True, text=True, env=self.env,
                           cwd=self.tmp, timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr[-2000:])
        return json.loads(p.stdout.strip().splitlines()[-1])

    def setUp(self):
        if not self.py:
            self.skipTest('este Python nao traz o libssl em DLLs (nao da para montar o layout)')

    def test_layout_reproduces_the_report(self):
        out = self.run_child('import ssl')
        self.assertIsNotNone(out['err'], 'o layout montado nao reproduz o QGIS 3.26')
        self.assertIn('_ssl', out['err'][1])

    def test_every_backend_module_imports_first_with_https(self):
        mods = sorted(os.path.splitext(f)[0] for f in os.listdir(_paths.BACKEND)
                      if f.endswith('.py') and f != '__init__.py')
        self.assertIn('ee_auth', mods)
        for mod in mods:
            with self.subTest(mod=mod):
                out = self.run_child('import %s' % mod)
                if out['err']:
                    self.assertIn(out['err'][0], OPTIONAL, out['err'][1])
                self.assertIsNot(out['https'], False, '%s desligou o HTTPS do urllib' % mod)

    def test_gee_core_scripts_for_another_qgis_python(self):
        import qgis_env  # noqa: F401
        try:
            import gee_core
        except ImportError:
            self.skipTest('gee_core exige o earthengine-api')
        out = self.run_child(gee_core._QGIS_DLLS_CODE.replace('\n', '; ') + 'import ssl')
        self.assertIsNone(out['err'])
