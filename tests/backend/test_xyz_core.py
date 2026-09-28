# -*- coding: utf-8 -*-
import os
import shutil
import tempfile
import unittest

import _paths
from _servers import TileServer
import tilemath
import xyz_core

BBOX = [-56.10, -15.62, -56.09, -15.61]   # 5 x 4 tiles no zoom 17
ZOOM = 17


def _no_sleep(_s):
    pass


class XyzUnitTest(unittest.TestCase):
    def test_provider_urls(self):
        g = xyz_core.get_provider('google')
        self.assertEqual(xyz_core.tile_url(g, 1, 2, 3), 'https://mt3.google.com/vt/lyrs=s&x=1&y=2&z=3')
        e = xyz_core.get_provider('esri')
        self.assertTrue(xyz_core.tile_url(e, 1, 2, 3).endswith('/tile/3/2/1'))
        b = xyz_core.get_provider('bing')
        self.assertIn('a213.jpeg', xyz_core.tile_url(b, 3, 5, 3))
        c = xyz_core.get_provider('http://srv/{z}/{x}/{y}.png')
        self.assertEqual(c['key'], 'custom')
        with self.assertRaises(ValueError):
            xyz_core.get_provider('inexistente')

    def test_max_tiles_guard(self):
        with self.assertRaises(ValueError) as ctx:
            xyz_core.download_mosaic([-57, -16, -55, -14], 18, 'esri', max_tiles=100)
        self.assertIn('tiles', str(ctx.exception))


class XyzDownloadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='arcmagery_xyz_')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _check_placement(self, path, engine):
        """Cada tile tem cor (x, y) unica: o pixel de cada posicao deve vir do tile certo."""
        from PIL import Image
        win = tilemath.crop_window(BBOX, ZOOM)
        if engine == 'gdal':
            from osgeo import gdal
            ds = gdal.Open(path)
            gt = ds.GetGeoTransform()
            self.assertAlmostEqual(gt[0], win['left'], places=4)
            self.assertAlmostEqual(gt[3], win['top'], places=4)
            self.assertAlmostEqual(gt[1], win['res'], places=8)
            self.assertEqual(ds.GetSpatialRef().GetAuthorityCode(None), '3857')
            self.assertEqual((ds.RasterXSize, ds.RasterYSize), (win['width'], win['height']))
            arr = ds.ReadAsArray()
            px = lambda c, r: tuple(int(v) for v in arr[:, r, c])
        else:
            im = Image.open(path)
            self.assertEqual(im.size, (win['width'], win['height']))
            self.assertTrue(os.path.exists(os.path.splitext(path)[0] + '.tfw'))
            px = lambda c, r: im.getpixel((c, r))
        for (c, r) in [(0, 0), (win['width'] - 1, win['height'] - 1), (win['width'] // 2, win['height'] // 3)]:
            gx = win['px0'] + c
            gy = win['py0'] + r
            tx, ty = win['x0'] + gx // 256, win['y0'] + gy // 256
            self.assertEqual(px(c, r)[:2], (tx % 256, ty % 256), "pixel (%d,%d)" % (c, r))

    def _run(self, engine, **kw):
        with TileServer(**kw.pop('server', {})) as srv:
            out = os.path.join(self.tmp, 'm_%s.tif' % engine)
            res = xyz_core.download_mosaic(BBOX, ZOOM, srv.template, out, compression='LZW',
                                           engine=engine, workers=4, **kw)
            return srv, out, res

    @unittest.skipUnless(_paths.HAS_GDAL, "GDAL indisponivel")
    def test_gdal_engine_georef_and_placement(self):
        srv, out, res = self._run('gdal')
        self.assertEqual(res['tiles'], 20)
        self.assertEqual(res['missing_tiles'], 0)
        self._check_placement(out, 'gdal')
        self.assertFalse(os.path.exists(os.path.splitext(out)[0] + '_tiles'), "cache deveria ser removido")

    def test_pil_engine_georef_and_placement(self):
        srv, out, res = self._run('pil')
        self._check_placement(out, 'pil')
        if _paths.HAS_GDAL:  # tags GeoTIFF gravadas pelo Pillow sao lidas pelo GDAL
            from osgeo import gdal
            self.assertEqual(gdal.Open(out).GetSpatialRef().GetAuthorityCode(None), '3857')

    def test_missing_tiles_are_reported(self):
        win = tilemath.crop_window(BBOX, ZOOM)
        srv, out, res = self._run('pil', server={'missing': [(win['x0'], win['y0'])]})
        self.assertEqual(res['missing_tiles'], 1)

    def test_retry_on_503(self):
        orig = xyz_core.time.sleep
        xyz_core.time.sleep = _no_sleep
        try:
            win = tilemath.crop_window(BBOX, ZOOM)
            key = (win['x0'] + 1, win['y0'])
            srv, out, res = self._run('pil', server={'flaky': {key: 2}})
            self.assertEqual(srv.hits[key], 3)
            self.assertEqual(res['missing_tiles'], 0)
        finally:
            xyz_core.time.sleep = orig

    def test_failure_keeps_cache_for_resume(self):
        orig = xyz_core.time.sleep
        xyz_core.time.sleep = _no_sleep
        try:
            win = tilemath.crop_window(BBOX, ZOOM)
            bad = (win['x0'], win['y0'] + 1)
            out = os.path.join(self.tmp, 'resume.tif')
            with TileServer(garbage=[bad]) as srv:
                with self.assertRaises(xyz_core.TileDownloadError):
                    xyz_core.download_mosaic(BBOX, ZOOM, srv.template, out, engine='pil', retries=2)
                self.assertFalse(os.path.exists(out))
                cache = os.path.splitext(out)[0] + '_tiles'
                self.assertEqual(len(os.listdir(cache)), 19)   # os demais ficaram em cache
            with TileServer() as srv2:  # servidor "consertado": so o tile que faltava e baixado
                res = xyz_core.download_mosaic(BBOX, ZOOM, srv2.template, out, engine='pil')
                self.assertEqual(sum(srv2.hits.values()), 1)
                self.assertEqual(res['tiles'], 20)
        finally:
            xyz_core.time.sleep = orig

    @unittest.skipUnless(_paths.HAS_GDAL, "GDAL indisponivel")
    def test_reproject_to_sirgas(self):
        srv, out, res = self._run('gdal', target_crs='EPSG:4674')
        from osgeo import gdal
        ds = gdal.Open(out)
        self.assertEqual(ds.GetSpatialRef().GetAuthorityCode(None), '4674')
        gt = ds.GetGeoTransform()
        self.assertAlmostEqual(gt[0], BBOX[0], delta=0.0002)
        self.assertAlmostEqual(gt[3], BBOX[3], delta=0.0002)


@unittest.skipUnless(_paths.LIVE, "defina ARCMAGERY_LIVE=1 para testes com internet")
class XyzLiveTest(unittest.TestCase):
    def test_esri_and_google_live(self):
        tmp = tempfile.mkdtemp(prefix='arcmagery_live_')
        try:
            for prov in ('esri', 'google'):
                res = xyz_core.download_mosaic(BBOX, ZOOM, prov, os.path.join(tmp, prov + '.tif'))
                self.assertEqual(res['missing_tiles'], 0, prov)
                self.assertGreater(os.path.getsize(res['file']), 10000)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
