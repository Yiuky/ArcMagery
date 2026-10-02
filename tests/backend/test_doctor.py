# -*- coding: utf-8 -*-
"""Diagnostico do ambiente (backend/doctor.py) sem internet: regras de cada verificacao, correcao
automatica do venv quebrado, relatorio, manifestos por versao do Python (3.8 a 3.14) e o modo
texto do run_gee (install.bat) sem a linha JSON."""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

import _paths  # noqa: F401
import doctor
import pylibs


class _Env(object):
    def __init__(self, **values):
        self.values = values

    def __enter__(self):
        self.old = dict((k, os.environ.get(k)) for k in self.values)
        os.environ.update(self.values)
        return self

    def __exit__(self, *a):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class ChecksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='arcmagery_doctor_')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_python_is_64_bits_and_recent(self):
        c = doctor.check_python()
        self.assertEqual(c['status'], doctor.OK if sys.version_info >= (3, 10) else doctor.WARN)
        self.assertIn('64 bits', c['detail'])

    def test_python_39_of_qgis_326_works_but_warns(self):
        from unittest import mock
        with mock.patch.object(sys, 'version_info', (3, 9, 13, 'final', 0)):
            c = doctor.check_python()
        self.assertEqual(c['status'], doctor.WARN)
        self.assertIn(u'3.40 LTR', c['remediation'][0])
        with mock.patch.object(sys, 'version_info', (3, 12, 0, 'final', 0)):
            self.assertEqual(doctor.check_python()['status'], doctor.OK)

    def test_broken_venv_is_taken_out_of_use(self):
        venv = os.path.join(self.tmp, 'ArcMagery', 'venv')
        os.makedirs(os.path.join(venv, 'Scripts'))
        with io.open(os.path.join(venv, 'pyvenv.cfg'), 'w', encoding='utf-8') as f:
            f.write(u'home = C:\\QGIS 3.99 removido\\apps\\Python39\n')
        with _Env(LOCALAPPDATA=self.tmp):
            self.assertEqual(doctor.check_old_venv(fix=False)['status'], doctor.FAIL)
            c = doctor.check_old_venv(fix=True)
            self.assertEqual(c['status'], doctor.FIXED)
            self.assertFalse(os.path.exists(venv))
            self.assertTrue([n for n in os.listdir(os.path.dirname(venv)) if n.startswith('venv.quebrado_')])
            self.assertEqual(doctor.check_old_venv()['status'], doctor.OK)     # agora "nao usado"

    def test_long_install_path_warns(self):
        self.assertEqual(doctor.check_install_path('C:\\ArcMagery')['status'], doctor.OK)
        c = doctor.check_install_path('C:\\' + 'pasta\\' * 30)
        self.assertEqual(c['status'], doctor.WARN)
        self.assertIn('260', c['remediation'][0])
        self.assertIsNone(doctor.check_install_path(None))

    def test_gee_login_without_credentials_or_project(self):
        with _Env(USERPROFILE=self.tmp, HOME=self.tmp, APPDATA=self.tmp):
            c = doctor.check_gee_login(True, True)
            self.assertEqual(c['status'], doctor.WARN)
            self.assertIn('autenticar_gee.bat', c['remediation'][0])
            cred = doctor.gee_credentials_path()
            os.makedirs(os.path.dirname(cred))
            open(cred, 'w').close()
            c = doctor.check_gee_login(True, True)
            self.assertIn(u'Configurar Projeto GEE', c['remediation'][0])

    def test_ee_missing_without_network_is_explained(self):
        saved = doctor.ee_import_check
        doctor.ee_import_check = lambda: (None, ['ImportError'])
        try:
            with _Env(LOCALAPPDATA=self.tmp):
                c = doctor.check_ee(fix=True, network_ok=False)
        finally:
            doctor.ee_import_check = saved
        self.assertEqual(c['status'], doctor.FAIL)
        self.assertIn('files.pythonhosted.org', c['remediation'][0])

    def test_network_rules(self):
        saved = doctor.probe
        try:
            doctor.probe = lambda url, ctx, **k: (False, u'certificado recusado (x)') if 'geodes' in url else (True, 'HTTP 200')
            c, per = doctor.check_network()
            self.assertEqual(c['status'], doctor.WARN)
            self.assertTrue(any(u'repositório de certificados' in r for r in c['remediation']))
            self.assertTrue(per['pypi'][0])
            doctor.probe = lambda url, ctx, **k: (False, u'timed out')
            self.assertEqual(doctor.check_network()[0]['status'], doctor.FAIL)
        finally:
            doctor.probe = saved


class RunAndReportTest(unittest.TestCase):
    def test_run_writes_report_and_counts(self):
        tmp = tempfile.mkdtemp()
        stubs = {
            'check_python': lambda: doctor.check('python', u'Python', doctor.OK, u'3.12'),
            'check_libs': lambda: doctor.check('libs', u'Libs', doctor.OK),
            'check_network': lambda: (doctor.check('net', u'Rede', doctor.OK), {'pypi': (True, ''), 'google': (True, '')}),
            'check_old_venv': lambda fix=True: doctor.check('venv', u'venv', doctor.FIXED, fix=u'renomeado'),
            'check_ee': lambda fix=True, network_ok=True: doctor.check('ee', u'EE', doctor.FAIL, u'x',
                                                                     remediation=[u'faça y']),
            'check_gee_login': lambda ee_ok, net_ok, test=True: doctor.check('gee', u'GEE', doctor.WARN, u'z'),
            'check_disk': lambda: doctor.check('disk', u'Disco', doctor.OK),
        }
        saved = dict((k, getattr(doctor, k)) for k in stubs)
        try:
            for k, v in stubs.items():
                setattr(doctor, k, v)
            with _Env(LOCALAPPDATA=tmp):
                res = doctor.run(install_path='C:\\ArcMagery')
        finally:
            for k, v in saved.items():
                setattr(doctor, k, v)
        self.assertFalse(res['success'])
        self.assertEqual(res['counts'], {'ok': 5, 'warn': 1, 'fail': 1, 'fixed': 1})
        text = doctor.format_text(res)
        self.assertIn(u'[CORRIGIDO]', text)
        self.assertIn(u'o que fazer: faça y', text)
        with io.open(res['report'], encoding='utf-8') as f:
            self.assertIn(u'Resumo: 5 ok, 1 corrigido(s), 1 aviso(s), 1 problema(s)', f.read())
        shutil.rmtree(tmp, ignore_errors=True)

    def test_text_mode_prints_report_without_json(self):
        import run_gee
        saved_run, saved_argv = doctor.run, sys.argv
        saved_exit = run_gee.hard_exit
        exits = []
        out = io.StringIO()
        try:
            doctor.run = lambda **k: {'success': True, 'counts': {'ok': 1, 'warn': 0, 'fail': 0, 'fixed': 0},
                                      'report': 'r.txt', 'checks': [doctor.check('python', u'Python', doctor.OK, u'3.12')]}
            run_gee.hard_exit = exits.append
            sys.argv = ['run_gee.py', 'doctor', '--text', '--install-path=C:\\x', '--no-test-gee']
            with contextlib.redirect_stdout(out):
                run_gee.main()
        finally:
            doctor.run, sys.argv, run_gee.hard_exit = saved_run, saved_argv, saved_exit
        text = out.getvalue()
        self.assertIn(u'[OK]', text)
        self.assertNotIn('{"', text)
        self.assertEqual(exits, [0])


class ManifestPerPythonTest(unittest.TestCase):
    def test_every_supported_python_has_a_complete_set(self):
        for minor, ee_major in ((8, '1.1'), (9, '1.6'), (10, '1.7'), (12, '1.7'), (14, '1.7')):
            m = pylibs.load_manifest(version_info=(3, minor))
            self.assertTrue(m['earthengine_api'].startswith(ee_major), (minor, m['earthengine_api']))
            files = pylibs.select_files(m, (3, minor))
            self.assertEqual(len(files), len(m['packages']))
            cffi = [f for f in files if f['package'] == 'cffi'][0]
            self.assertIn('cp3%d' % minor, cffi['filename'])

    def test_python_39_hides_google_end_of_life_warnings(self):
        import warnings
        from unittest import mock
        with warnings.catch_warnings(record=True) as seen:
            warnings.simplefilter('always')
            with mock.patch.object(sys, 'version_info', (3, 9, 13, 'final', 0)), \
                    mock.patch.object(pylibs, 'target_dir', lambda *a: os.path.join(tempfile.gettempdir(), 'arcmagery_sem_pylibs')):
                pylibs.activate()  # sem pasta: so instala o filtro, nao mexe no sys.path
            warnings.warn_explicit('Python 3.9 past its end of life', FutureWarning, 'x.py', 1, module='google.auth')
            warnings.warn_explicit('outro aviso', FutureWarning, 'x.py', 1, module='numpy')
        self.assertEqual([str(w.message) for w in seen], ['outro aviso'])

    def test_python_37_is_rejected_with_guidance(self):
        with self.assertRaises(pylibs.PylibsError) as ctx:
            pylibs.select_files(pylibs.load_manifest(version_info=(3, 7)), (3, 7))
        self.assertIn(u'3.8 a 3.14', str(ctx.exception))
