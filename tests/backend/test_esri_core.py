# -*- coding: utf-8 -*-
"""Datas de captura e historico Wayback da Esri, com um servidor simulado (sem internet)."""
import json
import os
import re
import shutil
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import _paths
import esri_core
import tilemath

AOI = [-56.1353, -12.8199, -56.1153, -12.7999]
ZOOM = 17
DAY = 86400000


def _ms(date):
    import datetime
    d = datetime.datetime.strptime(date, '%Y-%m-%d').replace(tzinfo=datetime.timezone.utc)
    return int(d.timestamp() * 1000)


class _FakeEsri(BaseHTTPRequestHandler):
    """Wayback com 5 versoes; o tile central muda apenas nas versoes 500 (2026), 300 (2023) e
    100 (2014). Semantica do tilemap (igual ao app Wayback): consultar a versao 400 devolve
    select=[300], ou seja, o tile exibido na 400 vem da versao MAIS ANTIGA 300."""
    CAPTURE = {500: ('2024-05-05', 'GE01', 'Vantor', 0.46), 400: ('2024-05-05', 'GE01', 'Maxar', 0.46),
               300: ('2022-05-02', 'WV03', 'Maxar', 0.31), 200: ('2022-05-02', 'WV03', 'Maxar', 0.31),
               100: ('2010-10-08', 'WV02', 'DigitalGlobe', 0.5)}
    SELECT = {500: None, 400: 300, 300: None, 200: 100, 100: None}

    def log_message(self, *a):
        pass

    def _json(self, obj):
        body = json.dumps(obj).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        srv = self.server
        u = urlparse(self.path)
        srv.calls.append(u.path)
        if u.path == '/config.json':
            dates = {500: '2026-08-05', 400: '2025-06-26', 300: '2023-12-07', 200: '2023-04-05', 100: '2014-10-29'}
            return self._json(dict((str(n), {
                'itemTitle': 'World Imagery (Wayback %s)' % d,
                'itemURL': srv.base + '/tile/%d/{level}/{row}/{col}' % n,
                'metadataLayerUrl': srv.base + '/meta/%d/MapServer' % n}) for n, d in dates.items()))
        m = re.match(r'^/tilemap/(\d+)/(\d+)/(\d+)/(\d+)$', u.path)
        if m:
            num = int(m.group(1))
            out = {'data': [1], 'valid': True}
            if _FakeEsri.SELECT.get(num):
                out['select'] = [_FakeEsri.SELECT[num]]
            return self._json(out)
        m = re.match(r'^/meta/(\d+)/MapServer/(\d+)/query$', u.path)
        if m:
            num, layer = int(m.group(1)), int(m.group(2))
            q = parse_qs(u.query)
            srv.meta_layers.append(layer)
            date, sensor, prov, res = _FakeEsri.CAPTURE[num]
            feats = [{'attributes': {'SRC_DATE2': _ms(date), 'SRC_DATE': int(date.replace('-', '')), 'SRC_DESC': sensor,
                                     'NICE_DESC': prov, 'SRC_RES': res, 'SRC_ACC': 5, 'NICE_NAME': 'Vivid'},
                      'geometry': {'rings': [[[-57, -13], [-56.125, -13], [-56.125, -12], [-57, -12], [-57, -13]]]}}]
            if num == 500:  # segunda captura cobrindo a metade leste da area
                feats.append({'attributes': {'SRC_DATE2': _ms('2025-09-10'), 'SRC_DESC': 'GE01', 'NICE_DESC': 'Vantor',
                                             'SRC_RES': 0.46, 'SRC_ACC': 8},
                              'geometry': {'rings': [[[-56.125, -13], [-55, -13], [-55, -12], [-56.125, -12], [-56.125, -13]]]}})
            if q.get('returnGeometry') == ['false']:
                for f in feats:
                    f.pop('geometry')
            return self._json({'features': feats})
        self.send_error(404)


class EsriCoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), _FakeEsri)
        cls.httpd.base = 'http://127.0.0.1:%d' % cls.httpd.server_address[1]
        cls.httpd.calls, cls.httpd.meta_layers = [], []
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls._orig = (esri_core.WAYBACK_CONFIG_URL, esri_core.TILEMAP_URL)
        esri_core.WAYBACK_CONFIG_URL = cls.httpd.base + '/config.json'
        esri_core.TILEMAP_URL = cls.httpd.base + '/tilemap'
        cls.tmp = tempfile.mkdtemp(prefix='arcmagery_esri_')
        cls.releases = esri_core.load_releases(os.path.join(cls.tmp, 'cfg.json'), force=True)

    @classmethod
    def tearDownClass(cls):
        esri_core.WAYBACK_CONFIG_URL, esri_core.TILEMAP_URL = cls._orig
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        del self.httpd.calls[:]
        del self.httpd.meta_layers[:]

    def test_releases_sorted_and_template_converted(self):
        self.assertEqual([r['num'] for r in self.releases], [500, 400, 300, 200, 100])
        self.assertTrue(self.releases[0]['tile_url'].endswith('/tile/500/{z}/{y}/{x}'))

    def test_metadata_layer_matches_zoom(self):
        self.assertEqual(esri_core.metadata_layer_for_zoom(17), 6)   # 1,2 m
        self.assertEqual(esri_core.metadata_layer_for_zoom(18), 5)   # 60 cm
        self.assertEqual(esri_core.metadata_layer_for_zoom(25), 0)
        self.assertEqual(esri_core.metadata_layer_for_zoom(5), 13)

    def test_capture_dates_with_coverage(self):
        dates = esri_core.capture_dates(AOI, ZOOM, self.releases[0])
        self.assertEqual(self.httpd.meta_layers, [6])
        got = dict((d['date'], d['coverage_pct']) for d in dates)
        self.assertAlmostEqual(got['2024-05-05'], 51.5, delta=0.5)   # oeste de -56.125 (0,0103 de 0,02 grau)
        self.assertAlmostEqual(got['2025-09-10'], 48.5, delta=0.5)
        self.assertEqual(esri_core.summarize_dates(dates), u'2024-05-05 a 2025-09-10 (2 capturas)')

    def test_local_versions_follow_select_and_dedupe(self):
        versions = esri_core.local_versions(AOI, ZOOM, self.releases)
        tilemaps = [c for c in self.httpd.calls if c.startswith('/tilemap/')]
        # 500 (muda) -> 400 aponta para 300 -> 200 aponta para 100: 3 consultas para 5 versoes
        self.assertEqual([int(c.split('/')[2]) for c in tilemaps], [500, 400, 200])
        self.assertEqual([(v['release_num'], v['capture_date'], v['sensor']) for v in versions],
                         [(500, '2024-05-05', 'GE01'), (300, '2022-05-02', 'WV03'), (100, '2010-10-08', 'WV02')])

    def test_dedupe_keeps_most_recent_release_of_same_capture(self):
        v = [{'release_num': 2, 'capture_date': '2024-05-05', 'sensor': 'GE01'},
             {'release_num': 1, 'capture_date': '2024-05-05', 'sensor': 'GE01'},
             {'release_num': 0, 'capture_date': '2020-01-01', 'sensor': 'WV02'}]
        self.assertEqual([x['release_num'] for x in esri_core.dedupe_by_capture(v)], [2, 0])

    def test_versions_cache(self):
        a = esri_core.local_versions_cached(AOI, ZOOM, cache_dir=self.tmp, releases=self.releases)
        self.assertEqual([v['release_num'] for v in a], [500, 300, 100])
        n = len(self.httpd.calls)
        b = esri_core.local_versions_cached(AOI, ZOOM, cache_dir=self.tmp, releases=self.releases)
        self.assertEqual(a, b)
        self.assertEqual(len(self.httpd.calls), n, "a segunda consulta deve vir do cache")

    def test_footprints_featureset(self):
        dates = esri_core.capture_dates(AOI, ZOOM, self.releases[0], with_geometry=True)
        path = esri_core.write_footprints(dates, os.path.join(self.tmp, 'fp.json'))
        fs = json.load(open(path, encoding='utf-8'))
        self.assertEqual(fs['geometryType'], 'esriGeometryPolygon')
        self.assertEqual(sorted(f['attributes']['DATA_CAPT'] for f in fs['features']), ['05/05/2024', '10/09/2025'])
        for f in fs['features']:   # recortado a area pedida
            xs = [p[0] for r in f['geometry']['rings'] for p in r]
            self.assertTrue(min(xs) >= AOI[0] - 1e-9 and max(xs) <= AOI[2] + 1e-9)
        self.assertEqual({fl['name'] for fl in fs['fields']} >= {'DATA_CAPT', 'SATELITE', 'FORNECEDOR'}, True)


@unittest.skipUnless(_paths.LIVE, "defina ARCMAGERY_LIVE=1 para testes com internet")
class EsriLiveTest(unittest.TestCase):
    def test_real_dates_and_history(self):
        dates = esri_core.capture_dates(AOI, ZOOM)
        self.assertTrue(dates and dates[0]['date'])
        versions = esri_core.local_versions(AOI, ZOOM)
        self.assertGreaterEqual(len(versions), 3)
        caps = [v['capture_date'] for v in versions if v['capture_date']]
        self.assertEqual(caps, sorted(caps, reverse=True))


if __name__ == '__main__':
    unittest.main()
