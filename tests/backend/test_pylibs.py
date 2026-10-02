# -*- coding: utf-8 -*-
"""earthengine-api sem pip (backend/pylibs.py): escolha das rodas por versao do Python, download com
SHA-256, extracao atomica, poda e ativacao; o manifesto real cobre o CPython 3.10 a 3.14; e o
run_gee devolve uma mensagem clara (sem traceback) quando o 'ee' falta."""
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

import _paths  # noqa: F401
import pylibs


def wheel_bytes(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


class FakeResp(object):
    def __init__(self, data):
        self.buf = io.BytesIO(data)

    def read(self, n=-1):
        return self.buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def manifest_for(wheels):
    pk = []
    for name, (python, data) in wheels.items():
        pk.append({'name': name, 'version': '1.0', 'files': [
            {'filename': '%s-1.0-x.whl' % name, 'url': 'https://pypi.example/%s.whl' % name,
             'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data), 'python': python}]})
    return {'earthengine_api': '9.9.9', 'packages': pk}


class _TempLocal(object):
    def __enter__(self):
        self.old = os.environ.get('LOCALAPPDATA')
        self.dir = tempfile.mkdtemp()
        os.environ['LOCALAPPDATA'] = self.dir
        return self

    def __exit__(self, *a):
        if self.old is None:
            os.environ.pop('LOCALAPPDATA', None)
        else:
            os.environ['LOCALAPPDATA'] = self.old
        shutil.rmtree(self.dir, ignore_errors=True)


class SelectTest(unittest.TestCase):
    M = {'packages': [
        {'name': 'puro', 'version': '1', 'files': [{'filename': 'a', 'python': 'any'}]},
        {'name': 'crypto', 'version': '1', 'files': [{'filename': 'b', 'python': 'abi3:3.9'}]},
        {'name': 'cffi', 'version': '1', 'files': [{'filename': 'c310', 'python': 'cp310'},
                                                   {'filename': 'c312', 'python': 'cp312'}]},
        {'name': 'opcional', 'version': '1', 'optional': True, 'files': [{'filename': 'o', 'python': 'cp399'}]},
    ]}

    def test_picks_one_compatible_wheel_per_package(self):
        got = dict((f['package'], f['filename']) for f in pylibs.select_files(self.M, (3, 12)))
        self.assertEqual(got, {'puro': 'a', 'crypto': 'b', 'cffi': 'c312'})

    def test_incompatible_python_is_reported(self):
        with self.assertRaises(pylibs.PylibsError) as ctx:
            pylibs.select_files(self.M, (3, 11))
        self.assertIn('cffi', str(ctx.exception))
        with self.assertRaises(pylibs.PylibsError):
            pylibs.select_files(self.M, (3, 8))       # abi3:3.9 nao serve

    def test_real_manifest_covers_supported_pythons(self):
        # Cada versao contra o SEU manifesto (3.8/3.9 tem um proprio): independe do Python que roda o teste
        for minor in (8, 9, 10, 11, 12, 13, 14):
            m = pylibs.load_manifest(version_info=(3, minor))
            self.assertTrue(m['earthengine_api'])
            names = set(p['name'] for p in m['packages'])
            for required in ('earthengine-api', 'google-auth', 'cryptography', 'cffi', 'protobuf'):
                self.assertIn(required, names, (minor, required))
            files = pylibs.select_files(m, (3, minor))
            self.assertEqual(len(files), len(m['packages']))
            for f in files:
                self.assertTrue(f['url'].startswith('https://files.pythonhosted.org/'), f['url'])
                self.assertEqual(len(f['sha256']), 64)


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.wheels = {
            'ee': ('any', wheel_bytes({'ee/__init__.py': "__version__ = '9.9.9'\n"})),
            'googleapiclient': ('any', wheel_bytes({
                'googleapiclient/__init__.py': '',
                'googleapiclient/discovery_cache/__init__.py': '',
                'googleapiclient/discovery_cache/documents/drive.v3.json': '{}' * 1000})),
            'cffi': ('cp%d%d' % sys.version_info[:2], wheel_bytes({'_cffi_backend_fake.py': ''})),
        }
        self.manifest = manifest_for(self.wheels)
        self.calls = []

    def opener(self, req):
        name = req.full_url.rsplit('/', 1)[-1][:-4]
        self.calls.append(name)
        return FakeResp(self.wheels[name][1])

    def test_install_extracts_prunes_and_activates(self):
        with _TempLocal():
            res = pylibs.install(self.manifest, opener=self.opener)
            d = pylibs.target_dir()
            self.assertTrue(res['installed'] and res['current'] and not res['skipped'])
            self.assertTrue(os.path.exists(os.path.join(d, 'ee', '__init__.py')))
            self.assertFalse(os.path.exists(os.path.join(d, 'googleapiclient', 'discovery_cache', 'documents')))
            self.assertTrue(os.path.exists(os.path.join(d, 'googleapiclient', 'discovery_cache', '__init__.py')))
            self.assertEqual(sorted(self.calls), ['cffi', 'ee', 'googleapiclient'])
            # idempotente: nada e baixado de novo
            self.calls = []
            self.assertTrue(pylibs.install(self.manifest, opener=self.opener)['skipped'])
            self.assertEqual(self.calls, [])
            # ativacao forcada poe a pasta no inicio do sys.path
            saved = list(sys.path)
            try:
                self.assertEqual(pylibs.activate(force=True), d)
                self.assertEqual(sys.path[0], d)
            finally:
                sys.path[:] = saved

    def test_bad_hash_keeps_nothing(self):
        self.manifest['packages'][0]['files'][0]['sha256'] = '0' * 64
        saved_sleep = pylibs.time.sleep
        pylibs.time.sleep = lambda s: None
        try:
            with _TempLocal():
                with self.assertRaises(pylibs.PylibsError):
                    pylibs.install(self.manifest, opener=self.opener)
                self.assertFalse(os.path.isdir(pylibs.target_dir()))
                self.assertEqual([n for n in os.listdir(pylibs.base_dir()) if n.startswith('arcmagery_pylibs_')], [])
        finally:
            pylibs.time.sleep = saved_sleep

    def test_activate_does_not_shadow_existing_ee(self):
        with _TempLocal():
            os.makedirs(pylibs.target_dir())
            import importlib.util
            if importlib.util.find_spec('ee') is None:
                self.skipTest("este Python nao tem 'ee' proprio")
            saved = list(sys.path)
            try:
                self.assertIsNone(pylibs.activate())
                self.assertNotIn(pylibs.target_dir(), sys.path)
            finally:
                sys.path[:] = saved


class RunGeeMissingEeTest(unittest.TestCase):
    def test_check_without_ee_prints_friendly_json(self):
        import contextlib
        import run_gee

        class Missing(object):
            def __getattr__(self, name):
                raise run_gee.EarthEngineMissing(run_gee.EE_MISSING_MESSAGE % 'python.exe')

        saved_core, saved_argv = run_gee.gee_core, sys.argv
        out = io.StringIO()
        try:
            run_gee.gee_core = Missing()
            sys.argv = ['run_gee.py', 'check']
            with contextlib.redirect_stdout(out):
                run_gee.main()
        finally:
            run_gee.gee_core, sys.argv = saved_core, saved_argv
        resp = json.loads(out.getvalue().strip().splitlines()[-1])
        self.assertFalse(resp['success'])
        self.assertTrue(resp['ee_missing'])
        self.assertIn(u'Instalar componentes do Earth Engine', resp['message'])
        self.assertNotIn('Traceback', resp['message'])

    def test_commands_registered(self):
        import run_gee
        for name in ('pylibs_install', 'pylibs_status', 'selfcheck'):
            self.assertIn(name, run_gee.SOURCE_COMMANDS)


class QgisDllOrderTest(unittest.TestCase):
    """B-09: no QGIS 3.26 (Python 3.9) o _ssl usa o libssl de <QGIS>\\bin; os scripts que o Python do
    QGIS executa direto precisam importar o qgis_env antes do ssl/urllib.request (e do pylibs, que
    importa o ssl), senao: "DLL load failed while importing _ssl"."""
    NEED_DLLS = ('ssl', 'urllib.request', 'pylibs')

    def _first_lines(self, name):
        import ast
        with io.open(os.path.join(_paths.BACKEND, name), encoding='utf-8') as f:
            tree = ast.parse(f.read())
        first = {}
        for node in tree.body:  # so o nivel do modulo: e o que roda no import
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                mods = [node.module or '']
            else:
                continue
            for m in mods:
                first.setdefault(m, node.lineno)
        return first

    def test_qgis_env_comes_before_ssl(self):
        for name in ('pylibs.py', 'ee_auth.py', 'doctor.py', 'run_gee.py'):
            first = self._first_lines(name)
            self.assertIn('qgis_env', first, name)
            for mod in self.NEED_DLLS:
                if mod in first:
                    self.assertLess(first['qgis_env'], first[mod], '%s: %s antes do qgis_env' % (name, mod))
