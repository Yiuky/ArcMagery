# -*- coding: utf-8 -*-
"""Atualizacao segura: Release + SHA256SUMS obrigatorio; branch main e downgrade so com confirmacao.
Nenhum teste toca o AssemblyCache, backups reais ou a internet (tudo simulado)."""
from __future__ import print_function

import BaseHTTPServer
import hashlib
import json
import os
import shutil
import tempfile
import threading
import unittest

import _paths
import gee_updater as up


class PureFunctionsTest(unittest.TestCase):
    def test_parse_version(self):
        self.assertEqual(up.parse_version('v1.10'), (1, 10, 0))
        self.assertEqual(up.parse_version('2.0.0'), (2, 0, 0))
        self.assertTrue(up.parse_version('1.10') > up.parse_version('1.9'))
        self.assertIsNone(up.parse_version('Desconhecida'))

    def test_parse_sha256sums(self):
        h = 'a' * 64
        sums = up.parse_sha256sums('%s  ArcMagery-2.0.0.zip\n# comentario\n%s *outro.zip\nlixo\n' % (h, 'b' * 64))
        self.assertEqual(sums, {'ArcMagery-2.0.0.zip': h, 'outro.zip': 'b' * 64})

    def test_verify_file_sha256(self):
        fd, path = tempfile.mkstemp()
        os.write(fd, b'conteudo')
        os.close(fd)
        try:
            good = hashlib.sha256(b'conteudo').hexdigest()
            self.assertEqual(up.verify_file_sha256(path, good.upper()), good)
            with self.assertRaises(up.SecurityValidationError):
                up.verify_file_sha256(path, '0' * 64)
        finally:
            os.remove(path)


class _ReleaseHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body, code = self.server.routes.get(self.path, (b'', 404))
        self.send_response(code)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class FetchReleaseTest(unittest.TestCase):
    def setUp(self):
        self.httpd = BaseHTTPServer.HTTPServer(('127.0.0.1', 0), _ReleaseHandler)
        self.httpd.routes = {}
        self.base = 'http://127.0.0.1:%d' % self.httpd.server_address[1]
        t = threading.Thread(target=self.httpd.serve_forever)
        t.daemon = True
        t.start()
        os.environ['NO_PROXY'] = '127.0.0.1'

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def test_no_release_returns_none(self):
        self.assertIsNone(up.fetch_latest_release(self.base + '/latest'))

    def test_release_assets(self):
        self.httpd.routes['/latest'] = (json.dumps({'tag_name': 'v2.1.0', 'assets': [
            {'name': 'ArcMagery-2.1.0.zip', 'browser_download_url': 'https://x/zip'},
            {'name': 'SHA256SUMS.txt', 'browser_download_url': 'https://x/sums'}]}).encode('utf-8'), 200)
        r = up.fetch_latest_release(self.base + '/latest')
        self.assertEqual((r['version'], r['zip_name'], r['zip_url'], r['sums_url']),
                         ('2.1.0', 'ArcMagery-2.1.0.zip', 'https://x/zip', 'https://x/sums'))


class OnlineFlowTest(unittest.TestCase):
    """execute_online_github_update_flow com todas as dependencias externas simuladas."""

    def setUp(self):
        self.saved = {}
        self.calls = {}
        self.zip_bytes = b'PK-pacote-simulado' * 1000
        self._patch('find_system_directories', lambda: {'dev_repo': None})
        self._patch('download_github_archive', self._fake_download)
        self._patch('execute_zip_update_flow', self._fake_zip_flow)

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(up, k, v)

    def _patch(self, name, fn):
        self.saved.setdefault(name, getattr(up, name))
        setattr(up, name, fn)

    def _fake_download(self, target, progress_callback=None, url=None):
        self.calls['download_url'] = url
        with open(target, 'wb') as f:
            f.write(self.zip_bytes)
        return target

    def _fake_zip_flow(self, zip_path, current_version=None, progress_callback=None,
                       expected_sha256=None, allow_downgrade=False):
        self.calls['zip_flow'] = {'expected_sha256': expected_sha256, 'allow_downgrade': allow_downgrade}
        return True

    def _release(self, version, with_sums=True):
        rel = {'version': version, 'tag': 'v' + version, 'zip_name': 'ArcMagery-%s.zip' % version,
               'zip_url': 'https://x/zip', 'sums_url': 'https://x/sums' if with_sums else None}
        self._patch('fetch_latest_release', lambda *a, **k: rel)
        return rel

    def test_without_release_requires_confirmation(self):
        self._patch('fetch_latest_release', lambda *a, **k: None)
        with self.assertRaises(up.ConfirmationRequired) as ctx:
            up.execute_online_github_update_flow(current_version='2.0.0')
        self.assertEqual(ctx.exception.flag, 'allow_unverified_main')
        self.assertNotIn('download_url', self.calls, "nada pode ser baixado antes da confirmacao")

    def test_confirmed_main_channel_is_unverified(self):
        self._patch('fetch_latest_release', lambda *a, **k: None)
        up.execute_online_github_update_flow(current_version='2.0.0', allow_unverified_main=True)
        self.assertEqual(self.calls['download_url'], up.GITHUB_ZIP_URL)
        self.assertIsNone(self.calls['zip_flow']['expected_sha256'])

    def test_release_hash_is_enforced(self):
        rel = self._release('2.1.0')
        digest = hashlib.sha256(self.zip_bytes).hexdigest()
        self._patch('_http_get', lambda url, **k: ('%s  %s\n' % (digest, rel['zip_name'])).encode('utf-8'))
        up.execute_online_github_update_flow(current_version='2.0.0')
        self.assertEqual(self.calls['download_url'], rel['zip_url'])
        self.assertEqual(self.calls['zip_flow']['expected_sha256'], digest)

    def test_release_without_hash_for_package_is_blocked(self):
        self._release('2.1.0')
        self._patch('_http_get', lambda url, **k: ('%s  outro.zip\n' % ('c' * 64)).encode('utf-8'))
        with self.assertRaises(up.SecurityValidationError):
            up.execute_online_github_update_flow(current_version='2.0.0')
        self.assertNotIn('download_url', self.calls)

    def test_same_or_older_release_is_not_installed(self):
        self._release('2.0.0')
        with self.assertRaises(up.UpdaterError) as ctx:
            up.execute_online_github_update_flow(current_version='2.0.0')
        self.assertNotIsInstance(ctx.exception, up.ConfirmationRequired)
        self.assertNotIn('download_url', self.calls)


class ZipFlowTest(unittest.TestCase):
    def setUp(self):
        self.saved = {}
        self.tmp = tempfile.mkdtemp(prefix='arcmagery_upd_')
        self.zip_path = os.path.join(self.tmp, 'pacote.zip')
        with open(self.zip_path, 'wb') as f:
            f.write(b'x' * 2048)
        self.reached = []
        self._patch('find_system_directories', lambda: {})
        self._patch('validate_zip_archive', lambda p, target_dirs=None: {'proposed_version': '1.10'})
        self._patch('create_snapshot_backup', lambda **k: self.reached.append('backup') or {})
        self._patch('prepare_staging_environment', lambda p: self.reached.append('staging') or {})
        self._patch('generate_and_launch_detached_runner', lambda s, b: self.reached.append('runner'))

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(up, k, v)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _patch(self, name, fn):
        self.saved.setdefault(name, getattr(up, name))
        setattr(up, name, fn)

    def test_hash_mismatch_stops_before_anything(self):
        with self.assertRaises(up.SecurityValidationError):
            up.execute_zip_update_flow(self.zip_path, current_version='2.0.0', expected_sha256='0' * 64)
        self.assertEqual(self.reached, [])

    def test_downgrade_requires_confirmation(self):
        with self.assertRaises(up.ConfirmationRequired) as ctx:
            up.execute_zip_update_flow(self.zip_path, current_version='2.0.0')
        self.assertEqual(ctx.exception.flag, 'allow_downgrade')
        self.assertEqual(self.reached, [])
        up.execute_zip_update_flow(self.zip_path, current_version='2.0.0', allow_downgrade=True)
        self.assertEqual(self.reached, ['backup', 'staging', 'runner'])


class RealZipValidationTest(unittest.TestCase):
    """validate_zip_archive REAL (sem mock) com config.xml em namespace, como o oficial."""

    CONFIG = (u'<ESRI.Configuration xmlns="http://schemas.esri.com/Desktop/AddIns">'
              u'<Name>ArcMagery</Name><Version>%s</Version></ESRI.Configuration>')

    def _zip(self, version, extra=None):
        import zipfile
        path = os.path.join(self.tmp, 'pkg_%s.zip' % version)
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('ArcMagery-x/arcgis_addin/config.xml', (self.CONFIG % version).encode('utf-8'))
            for f in ('gee_gui.py', 'gee_bridge.py'):
                z.writestr('ArcMagery-x/arcgis_addin/Install/' + f, '# ' + 'x' * 400)
            z.writestr('ArcMagery-x/arcgis_addin/Install/backend/gee_core.py', '# ' + 'x' * 400)
            for name, data in (extra or {}).items():
                z.writestr(name, data)
        return path

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='arcmagery_realzip_')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_version_is_read_despite_xml_namespace(self):
        meta = up.validate_zip_archive(self._zip('2.0.0'), target_dirs={})
        self.assertEqual(meta['proposed_version'], '2.0.0')

    def test_zip_slip_is_rejected(self):
        bad = self._zip('2.0.0', extra={'ArcMagery-x/../../evil.py': 'x'})
        with self.assertRaises(up.UpdaterError):
            up.validate_zip_archive(bad, target_dirs={})

    def test_real_downgrade_detection(self):
        saved = up.find_system_directories
        up.find_system_directories = lambda: {}
        try:
            with self.assertRaises(up.ConfirmationRequired):
                up.execute_zip_update_flow(self._zip('1.10'), current_version='2.0.0')
        finally:
            up.find_system_directories = saved


if __name__ == '__main__':
    unittest.main()
