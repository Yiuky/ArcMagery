# -*- coding: utf-8 -*-
"""Canais de atualizacao estavel x experimental (nightly): ordenacao de versoes com sufixo, lista de
Releases com pre-releases, escolha por canal, volta para a estavel e o selo EXPERIMENTAL da interface.
Nada toca a internet nem a instalacao real."""
from __future__ import print_function

import BaseHTTPServer
import json
import os
import threading
import unittest

import _paths  # noqa: F401
import gee_updater as up


def release(tag, prerelease=False, draft=False, assets=True):
    v = tag.lstrip('v')
    return {'tag_name': tag, 'prerelease': prerelease, 'draft': draft, 'assets': [
        {'name': 'ArcMagery-%s.zip' % v, 'browser_download_url': 'https://x/%s.zip' % v},
        {'name': 'SHA256SUMS.txt', 'browser_download_url': 'https://x/%s.sums' % v}] if assets else []}


class VersionOrderTest(unittest.TestCase):
    def test_semver_order_with_nightly_suffix(self):
        vs = ['2.4.1', '2.4.1-nightly.20261001', '2.3.3', '2.4.0', 'v2.4.1-nightly.20260930', '2.3.10']
        self.assertEqual(sorted(vs, key=up.version_key),
                         ['2.3.3', '2.3.10', '2.4.0', 'v2.4.1-nightly.20260930', '2.4.1-nightly.20261001', '2.4.1'])
        self.assertEqual(up.parse_version('2.4.1-nightly.20260930'), (2, 4, 1))
        self.assertTrue(up.is_prerelease('v2.4.1-nightly.1'))
        self.assertFalse(up.is_prerelease('2.4.0'))
        self.assertIsNone(up.version_key('Desconhecida'))

    def test_default_channel_follows_installed_version(self):
        self.assertEqual(up.default_channel('2.4.1-nightly.20260930'), up.CHANNEL_NIGHTLY)
        self.assertEqual(up.default_channel('2.4.0'), up.CHANNEL_STABLE)


class _Handler(BaseHTTPServer.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = json.dumps(self.server.releases).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class NewestReleaseTest(unittest.TestCase):
    def setUp(self):
        self.httpd = BaseHTTPServer.HTTPServer(('127.0.0.1', 0), _Handler)
        self.url = 'http://127.0.0.1:%d/releases' % self.httpd.server_address[1]
        t = threading.Thread(target=self.httpd.serve_forever)
        t.daemon = True
        t.start()
        os.environ['NO_PROXY'] = '127.0.0.1'

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def test_nightly_channel_picks_newest_published_with_hashes(self):
        self.httpd.releases = [release('v2.4.0'), release('v2.4.1-nightly.20260930', prerelease=True),
                               release('v2.4.1-nightly.20261005', prerelease=True, draft=True),      # rascunho
                               release('v2.4.1-nightly.20261004', prerelease=True, assets=False),   # sem hash
                               release('v2.3.3')]
        r = up.fetch_newest_release(self.url)
        self.assertEqual((r['version'], r['prerelease']), ('2.4.1-nightly.20260930', True))
        self.assertEqual(r['zip_name'], 'ArcMagery-2.4.1-nightly.20260930.zip')

    def test_stable_newer_than_nightly_wins_in_nightly_channel(self):
        self.httpd.releases = [release('v2.4.1-nightly.20260930', prerelease=True), release('v2.4.1')]
        self.assertEqual(up.fetch_newest_release(self.url)['version'], '2.4.1')


class ChannelFlowTest(unittest.TestCase):
    def setUp(self):
        self.saved = {}
        self.calls = {}
        self._patch('find_system_directories', lambda: {'dev_repo': None})
        self._patch('download_github_archive', self._download)
        self._patch('execute_zip_update_flow', self._zip_flow)
        self._patch('_http_get', lambda url, **k: ('%s  %s\n' % ('a' * 64, self.rel['zip_name'])).encode('utf-8'))

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(up, k, v)

    def _patch(self, name, fn):
        self.saved.setdefault(name, getattr(up, name))
        setattr(up, name, fn)

    def _download(self, target, progress_callback=None, url=None):
        self.calls['url'] = url
        open(target, 'wb').close()
        return target

    def _zip_flow(self, zip_path, current_version=None, progress_callback=None, expected_sha256=None,
                  allow_downgrade=False):
        self.calls['downgrade'] = allow_downgrade
        return True

    def _serve(self, stable, nightly):
        info = lambda v: {'version': v, 'tag': 'v' + v, 'prerelease': up.is_prerelease(v),
                          'zip_name': 'ArcMagery-%s.zip' % v, 'zip_url': 'https://x/%s.zip' % v, 'sums_url': 'https://x/s'}
        self._patch('fetch_latest_release', lambda *a, **k: info(stable))
        self._patch('fetch_newest_release', lambda *a, **k: info(nightly))

    def test_stable_channel_never_installs_nightly(self):
        self._serve('2.4.0', '2.4.1-nightly.20260930')
        self.rel = {'zip_name': 'ArcMagery-2.4.0.zip'}
        with self.assertRaises(up.UpdaterError) as ctx:
            up.execute_online_github_update_flow(current_version='2.4.0', channel=up.CHANNEL_STABLE)
        self.assertNotIsInstance(ctx.exception, up.ConfirmationRequired)
        self.assertNotIn('url', self.calls)

    def test_nightly_channel_installs_nightly(self):
        self._serve('2.4.0', '2.4.1-nightly.20260930')
        self.rel = {'zip_name': 'ArcMagery-2.4.1-nightly.20260930.zip'}
        up.execute_online_github_update_flow(current_version='2.4.0', channel=up.CHANNEL_NIGHTLY)
        self.assertEqual(self.calls['url'], 'https://x/2.4.1-nightly.20260930.zip')
        self.assertFalse(self.calls['downgrade'])

    def test_back_to_stable_from_nightly_asks_then_downgrades(self):
        self._serve('2.4.0', '2.4.1-nightly.20260930')
        self.rel = {'zip_name': 'ArcMagery-2.4.0.zip'}
        with self.assertRaises(up.ConfirmationRequired) as ctx:
            up.execute_online_github_update_flow(current_version='2.4.1-nightly.20260930', channel=up.CHANNEL_STABLE)
        self.assertEqual(ctx.exception.flag, 'allow_downgrade')
        self.assertIn(u'EXPERIMENTAL', ctx.exception.user_message)
        up.execute_online_github_update_flow(current_version='2.4.1-nightly.20260930', channel=up.CHANNEL_STABLE,
                                             allow_downgrade=True)
        self.assertEqual(self.calls['url'], 'https://x/2.4.0.zip')
        self.assertTrue(self.calls['downgrade'])

    def test_startup_check_per_channel(self):
        self._serve('2.4.0', '2.4.1-nightly.20260930')
        self.assertEqual(up.check_for_update('2.4.0', up.CHANNEL_STABLE)[0], False)
        found, rel = up.check_for_update('2.4.0', up.CHANNEL_NIGHTLY)
        self.assertTrue(found)
        self.assertEqual(rel['version'], '2.4.1-nightly.20260930')
        self._patch('fetch_newest_release', lambda *a, **k: 1 / 0)       # rede falhando: silencioso
        self.assertEqual(up.check_for_update('2.4.0', up.CHANNEL_NIGHTLY), (False, None))


class ExperimentalBadgeTest(unittest.TestCase):
    def test_badge_and_title(self):
        import gee_gui
        text, color = gee_gui.version_badge('2.4.1-nightly.20260930')
        self.assertIn(u'EXPERIMENTAL', text)
        self.assertEqual(color, '#ca6f1e')
        self.assertEqual(gee_gui.version_badge('2.4.0'), (u' v2.4.0 ', '#1b4f72'))
        self.assertEqual(gee_gui.is_experimental(), up.is_prerelease(gee_gui.CURRENT_VERSION))
        if gee_gui.is_experimental():
            self.assertIn(u'[EXPERIMENTAL]', gee_gui.APP_WINDOW_TITLE)


if __name__ == '__main__':
    unittest.main()
