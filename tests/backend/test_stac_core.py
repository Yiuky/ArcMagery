# -*- coding: utf-8 -*-
import os
import shutil
import sys
import tempfile
import unittest

import _paths
from _servers import RangeFileServer, StacServer
import stac_core

AOI = [-56.11, -15.62, -56.08, -15.59]


def _square(x0, y0, x1, y1):
    return {'type': 'Polygon', 'coordinates': [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


class StacPureTest(unittest.TestCase):
    def test_band_plans(self):
        self.assertEqual(stac_core.band_plan('CB4A-WPM-L4-DN-1', 'rgb'), (['BAND3', 'BAND2', 'BAND1'], [0, 1, 2]))
        self.assertEqual(stac_core.band_plan('CB4A-WPM-L4-DN-1', 'false'), (['BAND4', 'BAND3', 'BAND2'], [0, 1, 2]))
        self.assertEqual(stac_core.band_plan('CB4A-WPM-L4-DN-1', 'multi'),
                         (['BAND1', 'BAND2', 'BAND3', 'BAND4'], [2, 1, 0]))
        self.assertEqual(stac_core.band_plan('CB4A-WPM-L4-DN-1', 'pan'), (['BAND0'], None))
        self.assertEqual(stac_core.band_plan('CB4-WFI-L4-SR-1', 'rgb'), (['BAND15', 'BAND14', 'BAND13'], [0, 1, 2]))
        self.assertEqual(stac_core.band_plan('CB4-MUX-L4-SR-1', 'rgb'), (['BAND7', 'BAND6', 'BAND5'], [0, 1, 2]))
        self.assertEqual(stac_core.band_plan('AMZ1-WFI-L4-SR-1', 'rgb'), (['BAND3', 'BAND2', 'BAND1'], [0, 1, 2]))
        self.assertEqual(stac_core.band_plan('CB4-PAN10M-L4-DN-1', 'false'), (['BAND4', 'BAND3', 'BAND2'], [0, 1, 2]))
        self.assertEqual(stac_core.band_plan('CB4A-WPM-PCA-FUSED-1', 'fused'), (['rgb'], [0, 1, 2]))
        with self.assertRaises(stac_core.StacError):
            stac_core.band_plan('CB4-PAN5M-L4-DN-1', 'rgb')
        with self.assertRaises(stac_core.StacError):
            stac_core.band_plan('NAO-EXISTE', 'rgb')

    def test_new_cbers_plans(self):
        # CBERS-2/2B CCD: bandas com prefixo por camera
        self.assertEqual(stac_core.band_plan('CB2-CCD-L2-DN-1', 'rgb'),
                         (['CCD1XS_BAND3', 'CCD1XS_BAND2', 'CCD2XS_BAND1'], [0, 1, 2]))
        self.assertEqual(stac_core.band_plan('CB2B-CCD-L2-DN-1', 'pan'), (['CCD2PAN_BAND5'], None))
        self.assertEqual(stac_core.band_plan('CB2B-HRC-L2-DN-1', 'pan'), (['BAND1'], None))
        self.assertEqual(stac_core.available_modes('CB2-WFI-L2-DN-1'), ['multi'])
        self.assertEqual(stac_core.band_plan('CB2-WFI-L2-DN-1', 'multi'), (['BAND1', 'BAND2'], None))
        # cubos: indices prontos
        self.assertEqual(stac_core.band_plan('CBERS4-WFI-16D-2', 'ndvi'), (['NDVI'], None))
        self.assertEqual(stac_core.band_plan('CBERS4-MUX-2M-1', 'evi'), (['EVI'], None))
        self.assertEqual(stac_core.band_plan('CBERS4-MUX-2M-1', 'rgb'), (['BAND7', 'BAND6', 'BAND5'], [0, 1, 2]))
        self.assertEqual(stac_core.available_modes('mosaic-cbers4-brazil-3m-1'), ['visual'])
        self.assertEqual(stac_core.band_plan('mosaic-cbers4-brazil-3m-1', 'visual'), (['VISUAL'], [0, 1, 2]))
        self.assertEqual(len(stac_core.COLLECTIONS), 32)
        with self.assertRaises(stac_core.StacError):
            stac_core.band_plan('CB4A-WPM-L4-DN-1', 'ndvi')

    def test_envelope_footprint_is_flagged(self):
        self.assertTrue(stac_core.footprint_is_envelope(_square(-56.5, -16.0, -55.5, -15.0)))
        tilted = {'type': 'Polygon', 'coordinates': [[[0, 0], [1, 0.2], [0.8, 1.2], [-0.2, 1], [0, 0]]]}
        self.assertFalse(stac_core.footprint_is_envelope(tilted))
        self.assertFalse(stac_core.footprint_is_envelope({}))
        self.assertFalse(stac_core.footprint_is_envelope({'type': 'MultiPolygon', 'coordinates': []}))

    def test_every_collection_has_a_mode(self):
        for cid in stac_core.COLLECTIONS:
            modes = stac_core.available_modes(cid)
            self.assertTrue(modes, cid)
            for m in modes:
                stac_core.band_plan(cid, m)

    def test_dates(self):
        self.assertEqual(stac_core._to_iso('31/12/2025', end=True), '2025-12-31T23:59:59Z')
        self.assertEqual(stac_core._to_iso('2025-01-02'), '2025-01-02T00:00:00Z')
        self.assertEqual(stac_core._to_iso(None), '..')
        with self.assertRaises(stac_core.StacError):
            stac_core._to_iso('31/02/2025')

    def test_coverage(self):
        box = [0.0, 0.0, 1.0, 1.0]
        self.assertEqual(stac_core.aoi_coverage_pct(_square(-1, -1, 2, 2), box), 100.0)
        self.assertEqual(stac_core.aoi_coverage_pct(_square(0.5, -1, 2, 2), box), 50.0)
        self.assertEqual(stac_core.aoi_coverage_pct(_square(5, 5, 6, 6), box), 0.0)
        tri = {'type': 'Polygon', 'coordinates': [[[0, 0], [1, 0], [0, 1], [0, 0]]]}
        self.assertEqual(stac_core.aoi_coverage_pct(tri, box), 50.0)
        holed = {'type': 'Polygon', 'coordinates': [[[-1, -1], [2, -1], [2, 2], [-1, 2], [-1, -1]],
                                                     [[0, 0], [0.5, 0], [0.5, 1], [0, 1], [0, 0]]]}
        self.assertEqual(stac_core.aoi_coverage_pct(holed, box), 50.0)
        multi = {'type': 'MultiPolygon', 'coordinates': [_square(0, 0, 0.25, 1)['coordinates'],
                                                         _square(0.75, 0, 1, 1)['coordinates']]}
        self.assertEqual(stac_core.aoi_coverage_pct(multi, box), 50.0)
        self.assertIsNone(stac_core.aoi_coverage_pct(None, box))

    @unittest.skipUnless(sys.platform == 'win32', "somente Windows")
    def test_windows_ca_bundle(self):
        path = stac_core.windows_ca_bundle(os.path.join(tempfile.gettempdir(), 'arcmagery_test_ca.pem'))
        self.assertTrue(path and os.path.exists(path))
        with open(path) as f:
            self.assertIn('BEGIN CERTIFICATE', f.read(4096))


def _feature(fid, coll, date, geom, cloud=None, assets=None):
    props = {'datetime': date + 'T13:00:00Z'}
    if cloud is not None:
        props['eo:cloud_cover'] = cloud
    return {'type': 'Feature', 'id': fid, 'collection': coll, 'geometry': geom, 'bbox': None,
            'properties': props, 'assets': assets or {'thumbnail': {'href': 'http://x/t.png'}}}


class StacSearchTest(unittest.TestCase):
    def setUp(self):
        self._orig = stac_core.STAC_URL
        cover = _square(-56.5, -16.0, -55.5, -15.0)
        feats = [
            _feature('A', 'CB4-MUX-L4-SR-1', '2025-01-10', cover, cloud=5.0),
            _feature('B', 'CB4-MUX-L4-SR-1', '2025-03-10', cover, cloud=80.0),
            _feature('C', 'CB4-MUX-L4-SR-1', '2025-02-10', _square(-60, -20, -59, -19), cloud=0.0),  # nao cobre
            _feature('D', 'CB4-MUX-L4-SR-1', '2025-04-10', _square(-56.095, -16, -55, -15), cloud=1.0),  # ~50%
            _feature('E', 'CB4-MUX-L4-SR-1', '2025-05-10', cover),                                        # sem nuvem
            _feature('Z', 'OUTRA', '2025-05-10', cover),
        ]
        self.srv = StacServer(feats).__enter__()
        stac_core.STAC_URL = self.srv.base

    def tearDown(self):
        stac_core.STAC_URL = self._orig
        self.srv.__exit__(None, None, None)

    def test_pagination_sort_and_filters(self):
        items = stac_core.search(['CB4-MUX-L4-SR-1'], AOI, '01/01/2025', '31/12/2025', page_size=2)
        ids = [i['id'] for i in items]
        self.assertEqual(ids, ['E', 'D', 'B', 'A'])                  # C descartada (cobertura 0)
        self.assertEqual(len(self.srv.requests), 3)                   # 3 paginas (merge do body)
        self.assertIn('intersects', self.srv.requests[0])
        self.assertEqual(self.srv.requests[0]['datetime'], '2025-01-01T00:00:00Z/2025-12-31T23:59:59Z')
        d = [i for i in items if i['id'] == 'D'][0]
        self.assertAlmostEqual(d['coverage_pct'], 50.0, delta=1.0)
        self.assertIsNone([i for i in items if i['id'] == 'E'][0]['cloud_cover'])

    def test_max_cloud_keeps_unknown_cloud(self):
        ids = [i['id'] for i in stac_core.search('CB4-MUX-L4-SR-1', AOI, max_cloud=10)]
        self.assertEqual(sorted(ids), ['A', 'D', 'E'])

    def test_min_coverage(self):
        ids = [i['id'] for i in stac_core.search('CB4-MUX-L4-SR-1', AOI, min_coverage=90)]
        self.assertNotIn('D', ids)

    def test_coverage_estimate_flag(self):
        items = stac_core.search(['CB4-MUX-L4-SR-1'], AOI)
        self.assertTrue(all('coverage_is_estimate' in i for i in items))
        self.assertTrue([i for i in items if i['id'] == 'A'][0]['coverage_is_estimate'])   # retangulo

    def test_http_500_on_intersects_falls_back_to_bbox(self):
        self.srv.fail_intersects = True
        items = stac_core.search(['CB4-MUX-L4-SR-1'], AOI)
        self.assertEqual(sorted(i['id'] for i in items), ['A', 'B', 'D', 'E'])
        self.assertIn('intersects', self.srv.requests[0])
        self.assertNotIn('intersects', self.srv.requests[-1])   # apos as retentativas
        self.assertEqual(self.srv.requests[-1]['bbox'], AOI)
        self.assertNotIn('datetime', self.srv.requests[-1])      # '../..' descartado

    def test_requires_bbox(self):
        with self.assertRaises(stac_core.StacError):
            stac_core.search('CB4-MUX-L4-SR-1', None)


@unittest.skipUnless(_paths.HAS_GDAL, "GDAL indisponivel")
class StacDownloadTest(unittest.TestCase):
    """Cena sintetica em UTM 21S (EPSG:32721), pixel 8 m, servida localmente."""

    @classmethod
    def setUpClass(cls):
        from osgeo import gdal, osr
        import numpy as np
        cls.tmp = tempfile.mkdtemp(prefix='arcmagery_stac_')
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(32721)
        cls.gt = (590000.0, 8.0, 0.0, 8285000.0, 0.0, -8.0)
        drv = gdal.GetDriverByName('GTiff')
        cls.hrefs = {}
        for i, name in enumerate(['BAND1', 'BAND2', 'BAND3', 'BAND4', 'BAND0']):
            path = os.path.join(cls.tmp, name + '.tif')
            ds = drv.Create(path, 2000, 2000, 1, gdal.GDT_Int16, options=['TILED=YES'])
            ds.SetGeoTransform(cls.gt)
            ds.SetProjection(srs.ExportToWkt())
            arr = np.full((2000, 2000), (i + 1) * 100, dtype=np.int16)
            ds.GetRasterBand(1).WriteArray(arr)
            ds = None
            cls.hrefs[name] = path
        # Cena "vazia" (0 = NoData) para testar a protecao contra recorte 100% NoData
        empty = os.path.join(cls.tmp, 'EMPTY.tif')
        ds = drv.Create(empty, 2000, 2000, 1, gdal.GDT_Int16)
        ds.SetGeoTransform(cls.gt)
        ds.SetProjection(srs.ExportToWkt())
        ds.GetRasterBand(1).Fill(0)
        ds = None
        cls.empty = empty

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _item(self, hrefs):
        return {'id': 'SINT', 'collection': 'CB4A-WPM-L4-DN-1',
                'assets': dict((k, {'href': v}) for k, v in hrefs.items())}

    def _assert_native_grid(self, path, pixel):
        from osgeo import gdal
        ds = gdal.Open(path)
        gt = ds.GetGeoTransform()
        self.assertEqual(gt[1], pixel)
        self.assertAlmostEqual(((gt[0] - self.gt[0]) / pixel) % 1, 0.0)   # alinhado a grade de origem
        self.assertAlmostEqual(((self.gt[3] - gt[3]) / pixel) % 1, 0.0)
        return ds

    def test_rgb_local_files(self):
        out = os.path.join(self.tmp, 'rgb.tif')
        res = stac_core.download('CB4A-WPM-L4-DN-1', 'SINT', AOI, out, mode='rgb', item=self._item(self.hrefs))
        ds = self._assert_native_grid(out, 8.0)
        self.assertEqual(ds.RasterCount, 3)
        self.assertEqual([ds.GetRasterBand(i + 1).GetDescription() for i in range(3)], ['BAND3', 'BAND2', 'BAND1'])
        self.assertEqual(int(ds.GetRasterBand(1).ReadAsArray(0, 0, 1, 1)[0, 0]), 300)   # BAND3 = vermelho
        self.assertEqual(res['rgb_bands'], [0, 1, 2])
        self.assertEqual(res['epsg'], '32721')
        self.assertEqual(res['valid_pct'], 100.0)
        # ~3,2 km x 3,3 km a 8 m
        self.assertTrue(380 <= res['width'] <= 420 and 390 <= res['height'] <= 440, (res['width'], res['height']))

    def test_multiband_over_http_range(self):
        with RangeFileServer(self.tmp) as srv:
            hrefs = dict((k, srv.base + '/' + os.path.basename(v)) for k, v in self.hrefs.items())
            out = os.path.join(self.tmp, 'multi.tif')
            res = stac_core.download('CB4A-WPM-L4-DN-1', 'SINT', AOI, out, mode='multi', item=self._item(hrefs))
        ds = self._assert_native_grid(out, 8.0)
        self.assertEqual(ds.RasterCount, 4)
        self.assertEqual(res['rgb_bands'], [2, 1, 0])

    def test_missing_band_asset(self):
        hrefs = dict(self.hrefs)
        del hrefs['BAND0']
        with self.assertRaises(stac_core.StacError):
            stac_core.download('CB4A-WPM-L4-DN-1', 'SINT', AOI, os.path.join(self.tmp, 'p.tif'),
                               mode='pan', item=self._item(hrefs))

    def test_aoi_outside_raster(self):
        with self.assertRaises(stac_core.StacError) as ctx:
            stac_core.download('CB4A-WPM-L4-DN-1', 'SINT', [-50, -10, -49.9, -9.9], os.path.join(self.tmp, 'x.tif'),
                               mode='rgb', item=self._item(self.hrefs))
        self.assertIn(u'não cobre', ctx.exception.args[0])

    def test_all_nodata_clip_is_rejected(self):
        hrefs = {'BAND0': self.empty}
        out = os.path.join(self.tmp, 'vazio.tif')
        with self.assertRaises(stac_core.StacError) as ctx:
            stac_core.download('CB4A-WPM-L4-DN-1', 'SINT', AOI, out, mode='pan', item=self._item(hrefs))
        self.assertIn('NoData', ctx.exception.args[0])
        self.assertFalse(os.path.exists(out))
        self.assertFalse(os.path.exists(out + '.part.tif'))

    def test_pixel_limit(self):
        with self.assertRaises(stac_core.StacError):
            stac_core.download('CB4A-WPM-L4-DN-1', 'SINT', AOI, os.path.join(self.tmp, 'l.tif'), mode='rgb',
                               item=self._item(self.hrefs), max_pixels=1000)


@unittest.skipUnless(_paths.LIVE and _paths.HAS_GDAL, "defina ARCMAGERY_LIVE=1 (requer GDAL e internet)")
class StacLiveTest(unittest.TestCase):
    def test_inpe_search_and_clip(self):
        items = stac_core.search(['CB4A-WPM-L4-DN-1'], AOI, '01/06/2025', '31/12/2025', max_items=5)
        self.assertTrue(items, "nenhuma cena WPM retornada pelo INPE")
        self.assertTrue(all(i['coverage_pct'] >= 0.5 for i in items))
        tmp = tempfile.mkdtemp(prefix='arcmagery_inpe_')
        try:
            res = stac_core.download(items[0]['collection'], items[0]['id'], AOI, os.path.join(tmp, 'wpm.tif'))
            self.assertEqual(res['pixel_size'], 8.0)
            self.assertGreater(res['width'], 300)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
