# -*- coding: utf-8 -*-
"""SPOT 1-5 (backend/spot_core.py) sem internet: busca STAC simulada, download com cache/MD5/quota,
modelo de localizacao do L1A, correlacao de fase e o fluxo completo de georreferenciamento +
alinhamento contra uma referencia sintetica deslocada de um valor conhecido."""
import hashlib
import io
import json
import math
import os
import shutil
import tempfile
import unittest
import zipfile

import _paths  # noqa: F401
import spot_core as sc

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

# Modelo e vertices reais da cena 008-012_S2_693-381-0_2007-02-10-14-19-06_HRV-2_X_DT_GU (Cuiaba)
REAL_LC = [-5.6230633481e+01, -3.8446492382e-05, +2.2343213631e-04, +2.1759064899e-10, -3.5519703673e-12,
           +3.3045704066e-09]
REAL_PC = [-1.5209695185e+01, -1.7682107490e-04, -3.0175551719e-05, +1.4373330074e-11, +1.5944952646e-12,
           -3.0800493102e-10]
REAL_FRAME = [(1, 1, -56.230487740, -15.209902479), (3000, 1, -55.530606060, -15.303176063),
              (3000, 3000, -55.643969414, -15.833313049), (1, 3000, -56.345808322, -15.740168876),
              (1500, 1500, -55.945237212, -15.520847262)]


def feature(ident, ring, date='2008-05-08', platform='SPOT2', mode='X', md5='0' * 32, cloud=10.0):
    return {
        'id': 'URN:FEATURE:DATA:gdh:%s:V1' % ident, 'collection': 'SWH_SPOT123_L1',
        'geometry': {'type': 'Polygon', 'coordinates': [ring]},
        'properties': {'identifier': ident, 'start_datetime': date + 'T14:00:00Z', 'platform': platform,
                       'sar:instrument_mode': mode, 'nb_bands': 3, 'nb_cols': '3000', 'area': 3600.0,
                       'eo:cloud_cover': cloud, 'view:incidence_angle': 5.0, 'dataset': 'SWH_SPOT123_L1',
                       'datetime': '2025-04-28T14:58:43Z'},
        'assets': {ident + '.zip': {'href': 'https://geodes.example/api/download/X/files/' + md5,
                                    'title': ident + '.zip', 'type': 'application/zip', 'roles': ['data'],
                                    'description': 'File size: 1234 bytes\n\nChecksum MD5: x'},
                   ident + '.jpg': {'href': 'https://geodes.example/q.jpg', 'type': 'image/jpg',
                                    'roles': ['overview']}},
    }


BIG = [[-57, -16], [-55, -16], [-55, -15], [-57, -15], [-57, -16]]
BBOX = [-56.2, -15.7, -56.0, -15.5]


class GeometryAndModelTest(unittest.TestCase):
    def test_coverage(self):
        half = [[-56.1, -16], [-55, -16], [-55, -15], [-56.1, -15], [-56.1, -16]]
        self.assertEqual(sc.coverage_pct(BIG, BBOX), 100.0)
        self.assertAlmostEqual(sc.coverage_pct(half, BBOX), 50.0, places=1)
        self.assertEqual(sc.coverage_pct([[-50, -10], [-49, -10], [-49, -9], [-50, -10]], BBOX), 0.0)

    def test_utm_epsg_prefers_sirgas_in_brazil(self):
        self.assertEqual(sc.utm_epsg(-56.1, -15.6), 31981)     # Cuiaba: SIRGAS 2000 / UTM 21S
        self.assertEqual(sc.utm_epsg(-61.0, 2.5), 31974)       # Roraima: SIRGAS 2000 / UTM 20N
        self.assertEqual(sc.utm_epsg(2.35, 48.85), 32631)      # Paris: WGS 84 / UTM 31N

    def test_real_model_term_order(self):
        meta = {'model': (REAL_LC, REAL_PC), 'vertices': REAL_FRAME, 'ncols': 3000, 'nrows': 3000,
                'pixel_origin': 1}
        self.assertLess(sc.model_error_m(meta), 5.0)
        self.assertAlmostEqual(sc.pixel_size_m(meta), 22.6, delta=0.5)
        swapped = dict(meta, model=([REAL_LC[i] for i in (0, 2, 1, 3, 5, 4)], [REAL_PC[i] for i in (0, 2, 1, 3, 5, 4)]))
        self.assertGreater(sc.model_error_m(swapped), 10000)

    def test_gcps_use_pixel_centers_and_shift(self):
        meta = {'model': ([-56.0, 0, 0.0002, 0, 0, 0], [-15.0, -0.0002, 0, 0, 0, 0]), 'ncols': 300, 'nrows': 200,
                'pixel_origin': 1}
        px, ln, lon, lat = sc.gcps(meta, steps=2)[0]
        self.assertEqual((px, ln), (0, 0))
        self.assertAlmostEqual(lon, -56.0 + 0.0002 * 0.5)
        self.assertAlmostEqual(lat, -15.0 - 0.0002 * 0.5)
        _, _, lon2, lat2 = sc.gcps(meta, steps=2, shift=(0.001, -0.002))[0]
        self.assertAlmostEqual(lon2 - lon, 0.001)
        self.assertAlmostEqual(lat2 - lat, -0.002)

    def test_band_names_follow_file_order(self):
        self.assertEqual(sc.file_band_names({'bands': ['XS1', 'XS2', 'XS3', 'SWIR'], 'nbands': 4}),
                         ['XS3', 'XS2', 'XS1', 'SWIR'])
        self.assertEqual(sc.file_band_names({'bands': ['PAN'], 'nbands': 1}), ['PAN'])


class SearchTest(unittest.TestCase):
    def test_query_uses_dataset_filter_and_start_datetime(self):
        body = sc.build_query(BBOX, '2000-01-01', '2010-12-31', 20, ['4', '5'], 'pan')
        self.assertNotIn('collections', body)      # o GEODES devolve 0 itens com 2+ colecoes
        q = body['query']
        self.assertEqual(q['dataset']['in'], list(sc.DATASETS))
        self.assertEqual(q['start_datetime'], {'gte': '2000-01-01T00:00:00Z', 'lte': '2010-12-31T23:59:59Z'})
        self.assertEqual(q['eo:cloud_cover'], {'lte': 20.0})
        self.assertEqual(q['platform'], {'in': ['SPOT4', 'SPOT5']})
        self.assertEqual(q['sar:instrument_mode'], {'in': list(sc.PAN_MODES)})
        self.assertEqual(sc.build_query(kind='ms')['query']['sar:instrument_mode'], {'in': list(sc.MS_MODES)})

    def test_paging_and_row_fields(self):
        feats = [feature('S%04d' % i, BIG) for i in range(sc.PAGE + 3)]
        pages = []

        def http(url, body):
            pages.append(body['page'])
            n, p = body['limit'], body['page']
            got = feats[(p - 1) * n:p * n]
            return {'features': got, 'context': {'matched': len(feats), 'returned': len(got)}}

        scenes = sc.search(BBOX, http=http, max_items=10000)
        self.assertEqual(len(scenes), sc.PAGE + 3)
        self.assertEqual(pages, [1, 2])
        s = scenes[0]
        self.assertEqual((s['id'], s['date'], s['coverage_pct'], s['zip_size']), ('S0000', '2008-05-08', 100.0, 1234))
        self.assertEqual(s['res_m'], 20.0)
        self.assertFalse(s['is_pan'])
        self.assertEqual(s['thumbnail'], 'https://geodes.example/q.jpg')

    def test_min_coverage_and_get_scene(self):
        tiny = [[-56.01, -15.51], [-56.0, -15.51], [-56.0, -15.5], [-56.01, -15.5], [-56.01, -15.51]]
        feats = [feature('A', BIG), feature('B', tiny)]
        http = lambda url, body: {'features': feats, 'context': {'matched': 2}}
        self.assertEqual([s['id'] for s in sc.search(BBOX, http=http, min_coverage=0.5)], ['A'])
        bodies = []

        def http_one(url, body):
            bodies.append(body)
            return {'features': [feature('A', BIG)], 'context': {'matched': 1}}
        s = sc.get_scene('A', BBOX, http=http_one)
        self.assertEqual(bodies[0]['query']['identifier'], {'eq': 'A'})
        self.assertNotIn('bbox', bodies[0])
        self.assertEqual(s['coverage_pct'], 100.0)
        with self.assertRaises(sc.SpotError):
            sc.get_scene('X', http=lambda u, b: {'features': []})


class FakeResponse(object):
    def __init__(self, data, ctype='application/zip'):
        self.data, self.pos = data, 0
        self.headers = {'Content-Type': ctype, 'Content-Length': str(len(data))}

    def read(self, n=-1):
        n = len(self.data) - self.pos if n < 0 else n
        out = self.data[self.pos:self.pos + n]
        self.pos += len(out)
        return out

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def tiny_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('SCENE01/METADATA.DIM', '<Dimap_Document/>')
    return buf.getvalue()


class DownloadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.data = tiny_zip()
        self.scene = sc._scene(feature('CENA', BIG, md5=hashlib.md5(self.data).hexdigest()), BBOX)
        self.scene['zip_url'] = 'https://geodes.example/api/download/X/files/' + self.scene['zip_md5']

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_key_header_md5_and_cache(self):
        seen = []

        def opener(req):
            seen.append(req.get_header('X-api-key'))
            return FakeResponse(self.data)
        path = sc.download_zip(self.scene, 'CHAVE', self.tmp, opener=opener)
        with open(path, 'rb') as f:
            self.assertEqual(f.read(), self.data)
        self.assertEqual(seen, ['CHAVE'])
        # cache: sem rede e sem chave
        self.assertEqual(sc.download_zip(self.scene, None, self.tmp, opener=lambda r: self.fail('rede')), path)

    def test_quota_json_is_not_retried(self):
        calls = []

        def opener(req):
            calls.append(1)
            return FakeResponse(b'{"message":"DownloadQuotaPlugin : quota"}', 'application/json')
        with self.assertRaises(sc.SpotError) as ctx:
            sc.download_zip(self.scene, 'CHAVE', self.tmp, retries=3, opener=opener)
        self.assertIn('quota', str(ctx.exception).lower())
        self.assertEqual(len(calls), 1)

    def test_bad_md5_fails_and_cleans_part(self):
        bad = dict(self.scene, zip_md5='f' * 32)
        sc_sleep = sc.time.sleep
        sc.time.sleep = lambda s: None
        try:
            with self.assertRaises(sc.SpotError):
                sc.download_zip(bad, 'CHAVE', self.tmp, retries=2, opener=lambda r: FakeResponse(self.data))
        finally:
            sc.time.sleep = sc_sleep
        self.assertEqual([f for f in os.listdir(self.tmp) if f.endswith('.part')], [])

    def test_missing_key(self):
        with self.assertRaises(sc.SpotError):
            sc.download_zip(self.scene, None, self.tmp, opener=lambda r: self.fail('rede'))


@unittest.skipUnless(np is not None, "numpy indisponivel")
class PhaseCorrelationTest(unittest.TestCase):
    def texture(self, n=256, seed=3):
        rnd = np.random.RandomState(seed)
        a = rnd.rand(n, n)
        for _ in range(3):   # suaviza (textura parecida com imagem)
            a = (a + np.roll(a, 1, 0) + np.roll(a, 1, 1) + np.roll(a, -1, 0) + np.roll(a, -1, 1)) / 5.0
        return a * 200

    def test_sign_convention(self):
        b = self.texture()
        a = np.roll(np.roll(b, 3, axis=0), 5, axis=1)       # a(x) = b(x - (5, 3))
        dx, dy, conf = sc.phase_correlation(a, b)
        self.assertAlmostEqual(dx, 5, delta=0.2)
        self.assertAlmostEqual(dy, 3, delta=0.2)
        self.assertGreater(conf, sc.ALIGN_MIN_CONFIDENCE)

    def test_estimate_shift_returns_correction(self):
        b = self.texture(768)
        a = np.roll(np.roll(b, -4, axis=0), 6, axis=1)      # SPOT 6 px a leste e 4 px ao norte
        corr, info = sc.estimate_shift(a, b, np.ones(a.shape, bool), 10.0)
        self.assertIsNotNone(corr, info)
        d_e, d_n = corr
        self.assertAlmostEqual(d_e, -60.0, delta=3)          # corrigir: 60 m para oeste
        self.assertAlmostEqual(d_n, -40.0, delta=3)          # e 40 m para o sul
        self.assertEqual(info['agreeing'], info['windows'])

    def test_no_common_texture_is_refused(self):
        rnd = np.random.RandomState(1)
        corr, info = sc.estimate_shift(rnd.rand(512, 512) * 200, rnd.rand(512, 512) * 200,
                                       np.ones((512, 512), bool), 10.0)
        self.assertIsNone(corr)
        self.assertIn('reason', info)


def dimap_xml(lc, pc, ncols, nrows, nbands, frame):
    vert = ''.join(
        '<%s><FRAME_LON>%r</FRAME_LON><FRAME_LAT>%r</FRAME_LAT><FRAME_ROW>%d</FRAME_ROW><FRAME_COL>%d</FRAME_COL></%s>'
        % ('Scene_Center' if i == 4 else 'Vertex', lon, lat, r, c, 'Scene_Center' if i == 4 else 'Vertex')
        for i, (c, r, lon, lat) in enumerate(frame))
    return ("<?xml version='1.0'?><Dimap_Document><Dataset_Frame>%s</Dataset_Frame>"
            "<Raster_CS><PIXEL_ORIGIN>1</PIXEL_ORIGIN></Raster_CS><Geoposition><Simplified_Location_Model>"
            "<Direct_Location_Model><lc_List>%s</lc_List><pc_List>%s</pc_List></Direct_Location_Model>"
            "</Simplified_Location_Model></Geoposition><Dataset_Sources><Source_Information><Scene_Source>"
            "<IMAGING_DATE>2008-05-08</IMAGING_DATE><IMAGING_TIME>13:58:21</IMAGING_TIME><MISSION>SPOT</MISSION>"
            "<MISSION_INDEX>2</MISSION_INDEX><INSTRUMENT>HRV</INSTRUMENT><INSTRUMENT_INDEX>2</INSTRUMENT_INDEX>"
            "<INCIDENCE_ANGLE>+5.7</INCIDENCE_ANGLE></Scene_Source></Source_Information></Dataset_Sources>"
            "<Raster_Dimensions><NCOLS>%d</NCOLS><NROWS>%d</NROWS><NBANDS>%d</NBANDS></Raster_Dimensions>"
            "<Data_Processing><PROCESSING_LEVEL>1A</PROCESSING_LEVEL></Data_Processing><Image_Interpretation>"
            "<Spectral_Band_Info><BAND_DESCRIPTION>XS1</BAND_DESCRIPTION></Spectral_Band_Info>"
            "<Spectral_Band_Info><BAND_DESCRIPTION>XS2</BAND_DESCRIPTION></Spectral_Band_Info>"
            "<Spectral_Band_Info><BAND_DESCRIPTION>XS3</BAND_DESCRIPTION></Spectral_Band_Info>"
            "</Image_Interpretation></Dimap_Document>"
            % (vert, ''.join('<lc>%r</lc>' % v for v in lc), ''.join('<pc>%r</pc>' % v for v in pc),
               ncols, nrows, nbands))


@unittest.skipUnless(_paths.HAS_GDAL and np is not None, "GDAL/numpy indisponivel")
class GeoreferenceAndAlignTest(unittest.TestCase):
    """Cena sintetica 20 m cujo modelo erra 200 m (L) e -120 m (N): o alinhamento deve medir e corrigir."""
    N = 900
    PX = 20.0
    LAT0, LON0 = -15.40, -56.30
    TRUE_E, TRUE_N = 200.0, -120.0      # erro do modelo: verdade = modelo + (E, N)

    @classmethod
    def setUpClass(cls):
        from osgeo import gdal, osr
        cls.tmp = tempfile.mkdtemp()
        k = 111320.0 * math.cos(math.radians(cls.LAT0 - 0.08))
        cls.a, cls.b = cls.PX / k, cls.PX / 110574.0
        lc = [cls.LON0, 0.0, cls.a, 0.0, 0.0, 0.0]      # lon = LON0 + a * coluna
        pc = [cls.LAT0, -cls.b, 0.0, 0.0, 0.0, 0.0]     # lat = LAT0 - b * linha
        frame = [(c, r, cls.LON0 + cls.a * c, cls.LAT0 - cls.b * r)
                 for c, r in ((1, 1), (cls.N, 1), (cls.N, cls.N), (1, cls.N), (cls.N // 2, cls.N // 2))]
        rnd = np.random.RandomState(11)
        tex = rnd.rand(cls.N, cls.N)
        for _ in range(4):
            tex = (tex + np.roll(tex, 1, 0) + np.roll(tex, 1, 1) + np.roll(tex, -1, 0) + np.roll(tex, -1, 1)) / 5.0
        img = (40 + 180 * (tex - tex.min()) / (tex.max() - tex.min())).astype('uint8')
        tif = os.path.join(cls.tmp, 'IMAGERY.TIF')
        ds = gdal.GetDriverByName('GTiff').Create(tif, cls.N, cls.N, 3, gdal.GDT_Byte)
        for i in range(3):
            ds.GetRasterBand(i + 1).WriteArray(img)
        ds = None
        cls.zip = os.path.join(cls.tmp, 'cena.zip')
        with zipfile.ZipFile(cls.zip, 'w') as z:
            z.writestr('SCENE01/METADATA.DIM', dimap_xml(lc, pc, cls.N, cls.N, 3, frame))
            z.write(tif, 'SCENE01/IMAGERY.TIF')
        # Referencia "verdadeira": a mesma textura, na posicao modelo + (TRUE_E, TRUE_N), a 10 m em EPSG:4326
        dlon = cls.TRUE_E / k
        dlat = cls.TRUE_N / 110574.0
        res_lon, res_lat = cls.a / 2, cls.b / 2
        left, top = cls.LON0 + dlon, cls.LAT0 + dlat
        m = 2 * cls.N
        cols = np.arange(m) * res_lon / cls.a        # coluna DIMAP de cada pixel da referencia
        rows = np.arange(m) * res_lat / cls.b
        ci = np.clip(np.floor(cols).astype(int), 0, cls.N - 1)
        ri = np.clip(np.floor(rows).astype(int), 0, cls.N - 1)
        ref = img[ri][:, ci]
        cls.ref = os.path.join(cls.tmp, 'ref.tif')
        ds = gdal.GetDriverByName('GTiff').Create(cls.ref, m, m, 3, gdal.GDT_Byte)
        ds.SetGeoTransform([left, res_lon, 0, top, 0, -res_lat])
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)
        ds.SetProjection(srs.ExportToWkt())
        for i in range(3):
            ds.GetRasterBand(i + 1).WriteArray(ref)
        ds = None
        span_lon, span_lat = cls.a * cls.N, cls.b * cls.N
        cls.bbox = [cls.LON0 + 0.3 * span_lon, cls.LAT0 - 0.7 * span_lat, cls.LON0 + 0.7 * span_lon,
                    cls.LAT0 - 0.3 * span_lat]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_alignment_recovers_known_shift(self):
        out = os.path.join(self.tmp, 'out.tif')
        res = sc.georeference(self.zip, out, self.bbox, mode='false', align=True, reference=self.ref)
        a = res['alignment']
        self.assertTrue(a['applied'], a)
        self.assertAlmostEqual(a['shift_east_m'], self.TRUE_E, delta=12)
        self.assertAlmostEqual(a['shift_north_m'], self.TRUE_N, delta=12)
        self.assertLess(a['residual_m'], 12)
        self.assertEqual(res['epsg'], 31981)
        self.assertEqual(res['band_names'], ['XS3', 'XS2', 'XS1'])
        self.assertEqual(res['rgb_bands'], [0, 1, 2])
        self.assertGreater(res['valid_pct'], 99)
        from osgeo import gdal
        ds = gdal.Open(out)
        self.assertEqual(ds.RasterCount, 3)
        self.assertEqual(ds.GetRasterBand(1).GetDescription(), 'XS3')
        self.assertEqual(ds.GetMetadataItem('SPOT_ALIGNED_TO'), 'Esri World Imagery')
        self.assertAlmostEqual(ds.GetGeoTransform()[1], self.PX, delta=0.5)
        ds = None

    def test_without_alignment_and_multiband(self):
        out = os.path.join(self.tmp, 'out_noalign.tif')
        res = sc.georeference(self.zip, out, self.bbox, mode='false', align=False)
        self.assertFalse(res['alignment']['applied'])
        out2 = os.path.join(self.tmp, 'out_multi.tif')
        res2 = sc.georeference(self.zip, out2, self.bbox, mode='multi', align=False)
        self.assertEqual(res2['bands'], [1, 2, 3])

    def test_swir_needs_four_bands(self):
        with self.assertRaises(sc.SpotError):
            sc.georeference(self.zip, os.path.join(self.tmp, 'x.tif'), self.bbox, mode='swir', align=False)


class CliRegistrationTest(unittest.TestCase):
    def test_commands_registered(self):
        import run_gee
        for name in ('spot_search', 'spot_download', 'spot_thumb', 'spot_check_key', 'selfcheck'):
            self.assertIn(name, run_gee.SOURCE_COMMANDS)
            self.assertTrue(callable(run_gee.SOURCE_COMMANDS[name]))


@unittest.skipUnless(_paths.LIVE, "ARCMAGERY_LIVE=1 para testar o GEODES real")
class LiveGeodesTest(unittest.TestCase):
    def test_search_cuiaba(self):
        scenes = sc.search([-56.12, -15.62, -56.06, -15.57], max_cloud=5, min_coverage=100)
        self.assertGreater(len(scenes), 20)
        self.assertTrue(all(s['date'] < '2016' for s in scenes))
        self.assertTrue(all(s['coverage_pct'] == 100.0 for s in scenes))
