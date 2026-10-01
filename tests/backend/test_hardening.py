# -*- coding: utf-8 -*-
"""Regressoes da revisao de robustez (v2.4.x), sem internet: certificados do Windows para o 'ee',
limpeza de temporarios e parciais, JSON como ultima linha do run_gee e retentativas HTTP."""
import contextlib
import email.message
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

import _paths  # noqa: F401
import esri_core
import run_gee
import sysenv
import xyz_core

try:
    import gee_core
    HAS_EE = True
except Exception:  # earthengine-api ausente neste Python
    HAS_EE = False


@contextlib.contextmanager
def patched(obj, name, value):
    orig = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, orig)


def http_error(code, headers=None):
    hdrs = email.message.Message()
    for k, v in (headers or {}).items():
        hdrs[k] = v
    return urllib.error.HTTPError('https://x.example/y', code, 'erro %d' % code, hdrs, io.BytesIO(b''))


# ------------------------------------------------------------------------- 1. certificados (ee)
class CaBundleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='arcmagery_ca_')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_sets_all_three_variables(self):
        env = {}
        path = sysenv.configure_requests_ca(env, bundle_fn=lambda: r'C:\x\ca.pem')
        self.assertEqual(path, r'C:\x\ca.pem')
        self.assertEqual(env, dict((k, r'C:\x\ca.pem') for k in sysenv.CA_ENV_VARS))

    def test_respects_user_configuration(self):
        for key in ('REQUESTS_CA_BUNDLE', 'SSL_CERT_FILE'):
            env = {key: r'C:\ti\corp.pem'}
            self.assertIsNone(sysenv.configure_requests_ca(env, bundle_fn=lambda: self.fail('nao gerar')))
            self.assertEqual(env, {key: r'C:\ti\corp.pem'})

    def test_never_raises(self):
        def boom():
            raise OSError("sem permissao no %TEMP%")
        env = {}
        self.assertIsNone(sysenv.configure_requests_ca(env, bundle_fn=boom))
        self.assertIsNone(sysenv.configure_requests_ca(env, bundle_fn=lambda: None))
        self.assertEqual(env, {})

    def test_combined_bundle_is_superset_of_certifi(self):
        path = os.path.join(self.tmp, 'ca.pem')
        out = sysenv.combined_ca_bundle(path, windows_pems=['-----WIN-----\n'], certifi_pem='-----CERTIFI-----')
        self.assertEqual(out, path)
        with open(path) as f:
            self.assertEqual(f.read(), '-----CERTIFI-----\n-----WIN-----\n')
        # sem nada do Windows a acrescentar: manter o padrao das bibliotecas
        self.assertIsNone(sysenv.combined_ca_bundle(os.path.join(self.tmp, 'b.pem'), windows_pems=[],
                                                    certifi_pem='x'))

    @unittest.skipUnless(sys.platform == 'win32', "somente Windows")
    def test_real_combined_bundle_loads_in_openssl(self):
        import ssl
        path = sysenv.combined_ca_bundle(os.path.join(self.tmp, 'real.pem'), certifi_pem='')
        self.assertTrue(path and os.path.exists(path))
        ssl.create_default_context(cafile=path)   # um certificado invalido derrubaria o PEM inteiro

    @unittest.skipUnless(HAS_EE, "earthengine-api indisponivel neste Python")
    def test_gee_core_configures_before_importing_ee(self):
        import inspect
        src = inspect.getsource(gee_core)
        self.assertLess(src.index('configure_requests_ca()'), src.index('\nimport ee'))


# ---------------------------------------------------------------- 3. varredura de temporarios
class SweepTest(unittest.TestCase):
    def test_only_old_dirs_with_known_prefixes(self):
        base = tempfile.mkdtemp(prefix='arcmagery_sweep_')
        try:
            now = time.time()
            old = now - 2 * 86400
            names = {'arcmagery_spot_old': old, 'arcgee_tiles_old': old, 'arcmagery_spot_new': now,
                     'outra_pasta_old': old}
            for n, t in names.items():
                d = os.path.join(base, n)
                os.makedirs(d)
                with open(os.path.join(d, 'IMAGERY.TIF'), 'wb') as f:
                    f.write(b'x' * 10)
                os.utime(d, (t, t))
            with open(os.path.join(base, 'arcgee_tiles_arquivo'), 'w') as f:   # arquivo, nao pasta
                f.write('x')
            removed = sysenv.sweep_stale_temp_dirs(base=base, now=now)
            self.assertEqual(sorted(os.path.basename(p) for p in removed), ['arcgee_tiles_old', 'arcmagery_spot_old'])
            self.assertEqual(sorted(os.listdir(base)), ['arcgee_tiles_arquivo', 'arcmagery_spot_new', 'outra_pasta_old'])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_never_raises(self):
        self.assertEqual(sysenv.sweep_stale_temp_dirs(base=r'Z:\nao\existe\mesmo'), [])


# --------------------------------------------------------------------- 4/5. GEE: parciais e tiles
class _FakeResp(object):
    def __init__(self, data, fail_after=None):
        self.buf, self.fail_after, self.sent = io.BytesIO(data), fail_after, 0

    def read(self, n=-1):
        if self.fail_after is not None and self.sent >= self.fail_after:
            raise ConnectionResetError("conexao caiu no meio")
        chunk = self.buf.read(n if n and n > 0 else -1)
        self.sent += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@unittest.skipUnless(HAS_EE, "earthengine-api indisponivel neste Python")
class GeeDownloadFilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='arcmagery_geedl_')
        self.out = os.path.join(self.tmp, 'S2_RGB.tif')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_success_writes_final_without_part(self):
        with patched(gee_core.urllib.request, 'urlopen', lambda req, timeout=None: _FakeResp(b'II*\x00' * 1000)):
            self.assertTrue(gee_core.download_url_with_timeout('https://x/y', self.out, max_retries=1))
        self.assertEqual(os.path.getsize(self.out), 4000)
        self.assertFalse(os.path.exists(self.out + '.part'))

    def test_failure_leaves_neither_final_nor_part(self):
        calls = []

        def opener(req, timeout=None):
            calls.append(1)
            return _FakeResp(b'II*\x00' * 100000, fail_after=65536)

        with patched(gee_core.urllib.request, 'urlopen', opener), patched(gee_core.time, 'sleep', lambda s: None):
            with self.assertRaises(ConnectionResetError):
                gee_core.download_url_with_timeout('https://x/y', self.out, max_retries=2)
        self.assertEqual(len(calls), 2)
        self.assertEqual(os.listdir(self.tmp), [])

    def test_tiles_dir_removed_when_a_tile_fails(self):
        """Regressao: a pasta arcgee_tiles_* so era apagada no sucesso (centenas de MB no %TEMP%)."""
        class Img(object):
            def select(self, bands):
                return self

            def getDownloadURL(self, params):
                raise RuntimeError("Earth Engine: erro simulado")

        class Geometry(object):
            @staticmethod
            def BBox(*a):
                return ('bbox',) + tuple(a)

        class FakeEE(object):
            Image = staticmethod(lambda _id: Img())
            ImageCollection = None

        FakeEE.Geometry = Geometry
        made = []
        orig_mkdtemp = gee_core.tempfile.mkdtemp

        def mkdtemp(*a, **k):
            d = orig_mkdtemp(*a, **k)
            made.append(d)
            return d

        with patched(gee_core, 'ee', FakeEE), patched(gee_core.tempfile, 'mkdtemp', mkdtemp), \
                patched(gee_core.time, 'sleep', lambda s: None):
            with self.assertRaises(RuntimeError):
                gee_core.download_geotiff(['COPERNICUS/S2_SR_HARMONIZED/20240101T000000_X'], 'S2', 'XX',
                                          load_mode='multiband', bbox=[-56.4, -15.9, -55.9, -15.4],
                                          out_tif_path=self.out)
        tiles = [d for d in made if os.path.basename(d).startswith('arcgee_tiles_')]
        self.assertEqual(len(tiles), 1, made)
        self.assertFalse(os.path.exists(tiles[0]))
        self.assertFalse(os.path.exists(self.out))


# ---------------------------------------------------------------------------- 7/8. run_gee
class RunGeeTest(unittest.TestCase):
    def test_explicit_zero_min_coverage_is_kept(self):
        self.assertEqual(run_gee._min_coverage({'min_coverage': 0}), 0.0)
        self.assertEqual(run_gee._min_coverage({'min_coverage': '0'}), 0.0)
        self.assertEqual(run_gee._min_coverage({'min_coverage': ''}), 0.5)
        self.assertEqual(run_gee._min_coverage({}), 0.5)
        import spot_core
        seen = {}

        def fake_search(*a, **k):
            seen.update(k)
            return []

        with patched(spot_core, 'search', fake_search):
            run_gee.src_spot_search({'bbox': '-56.2,-15.7,-56.0,-15.5', 'min_coverage': 0})
        self.assertEqual(seen['min_coverage'], 0.0)

    def test_any_import_error_in_gee_core_chain_is_ee_missing(self):
        saved_mod = run_gee._LazyGeeCore._mod
        saved_sys = sys.modules.get('gee_core', None)
        had = 'gee_core' in sys.modules
        run_gee._LazyGeeCore._mod = None
        sys.modules['gee_core'] = None   # ImportError que NAO cita 'ee' (como google.auth/cryptography)
        try:
            with self.assertRaises(run_gee.EarthEngineMissing) as ctx:
                run_gee.gee_core.COMPOSITIONS
            self.assertIn('gee_core', str(ctx.exception))          # detalhe original preservado
            self.assertIn('earthengine-api', str(ctx.exception))
        finally:
            run_gee._LazyGeeCore._mod = saved_mod
            if had:
                sys.modules['gee_core'] = saved_sys
            else:
                sys.modules.pop('gee_core', None)

    def test_unexpected_exception_still_ends_with_json(self):
        def boom(parser, args):
            print("saida parcial do comando")
            raise ValueError("erro inesperado simulado")

        out, err = io.StringIO(), io.StringIO()
        with patched(run_gee, '_dispatch', boom), patched(sys, 'argv', ['run_gee.py', 'compositions', '--sensor', 'S2']):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                with self.assertRaises(SystemExit) as ctx:
                    run_gee.main()
        self.assertNotEqual(ctx.exception.code, 0)
        last = out.getvalue().strip().splitlines()[-1]
        data = json.loads(last)
        self.assertFalse(data['success'])
        self.assertIn('erro inesperado simulado', data['message'])
        self.assertIn('Traceback', err.getvalue())

    def test_ee_missing_contract_unchanged(self):
        def missing(parser, args):
            raise run_gee.EarthEngineMissing("sem ee")

        out = io.StringIO()
        with patched(run_gee, '_dispatch', missing), patched(sys, 'argv', ['run_gee.py', 'compositions', '--sensor', 'S2']):
            with contextlib.redirect_stdout(out):
                run_gee.main()
        self.assertEqual(json.loads(out.getvalue().strip().splitlines()[-1]),
                         {'success': False, 'message': 'sem ee', 'ee_missing': True})


# -------------------------------------------------------------------------------- 10. retentativas
class RetryTest(unittest.TestCase):
    def test_xyz_no_sleep_after_last_attempt_with_retry_after(self):
        sleeps, calls = [], []

        def opener(req, timeout=None, context=None):
            calls.append(1)
            raise http_error(429, {'Retry-After': '7'})

        with patched(xyz_core.urllib.request, 'urlopen', opener):
            with self.assertRaises(xyz_core.TileDownloadError):
                xyz_core.fetch_tile('https://x/1/2/3.png', retries=3, _sleep=sleeps.append)
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [7, 7])     # antes: 3 esperas (a ultima inutil)

    def test_esri_permanent_4xx_is_not_retried(self):
        sleeps, calls = [], []

        def opener(req, timeout=None, context=None):
            calls.append(1)
            raise http_error(404)

        with patched(esri_core.urllib.request, 'urlopen', opener):
            with self.assertRaises(esri_core.EsriError) as ctx:
                esri_core._get_json('https://x/y', retries=3, _sleep=sleeps.append)
        self.assertEqual((len(calls), sleeps), (1, []))
        self.assertIn('404', str(ctx.exception))

    def test_esri_transient_errors_retry_without_final_sleep(self):
        for code in (429, 408, 503):
            sleeps, calls = [], []

            def opener(req, timeout=None, context=None):
                calls.append(1)
                raise http_error(code)

            with patched(esri_core.urllib.request, 'urlopen', opener):
                with self.assertRaises(esri_core.EsriError):
                    esri_core._get_json('https://x/y', retries=3, _sleep=sleeps.append)
            self.assertEqual(len(calls), 3, code)
            self.assertEqual(sleeps, [1.0, 2.0], code)


if __name__ == '__main__':
    unittest.main()
