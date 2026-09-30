# -*- coding: utf-8 -*-
"""Paralelismo com memoria limitada, piramides GDAL e consultas em varios zooms."""
import os
import shutil
import tempfile
import threading
import time
import unittest

import _paths
import parallel
import xyz_core


class ImapBoundedTest(unittest.TestCase):
    def test_results_and_bounded_in_flight(self):
        lock, state = threading.Lock(), {'now': 0, 'peak': 0}

        def job(x):
            with lock:
                state['now'] += 1
                state['peak'] = max(state['peak'], state['now'])
            time.sleep(0.002)
            with lock:
                state['now'] -= 1
            return x * 2

        started = []

        def items():
            for i in range(400):
                started.append(i)
                yield i

        out = []
        for i, r in enumerate(parallel.imap_bounded(job, items(), workers=4, pending_per_worker=2)):
            out.append(r)
            if i == 10:
                # o gerador nao foi consumido inteiro de uma vez: no maximo 8 em andamento + 11 lidos
                self.assertLessEqual(len(started), 8 + 11)
        self.assertEqual(sorted(out), [2 * i for i in range(400)])
        self.assertLessEqual(state['peak'], 4)

    def test_error_propagates_and_stops(self):
        def job(x):
            if x == 5:
                raise ValueError("falhou")
            return x

        with self.assertRaises(ValueError):
            list(parallel.imap_bounded(job, range(1000), workers=2))

    def test_worker_limits(self):
        self.assertEqual(parallel.clamp_workers(None), parallel.default_workers())
        self.assertEqual(parallel.clamp_workers(1000), parallel.MAX_WORKERS)
        self.assertEqual(parallel.clamp_workers(2), parallel.MIN_WORKERS)
        self.assertTrue(1 <= parallel.default_cores() <= 16)


class OverviewsTest(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(xyz_core.overview_levels(400, 300), [])
        self.assertEqual(xyz_core.overview_levels(47920, 29369), [2, 4, 8, 16, 32, 64, 128])

    @unittest.skipUnless(_paths.HAS_GDAL, "requer GDAL")
    def test_build_overviews_external_ovr(self):
        from osgeo import gdal
        import numpy as np
        tmp = tempfile.mkdtemp(prefix='arcmagery_ovr_')
        try:
            path = os.path.join(tmp, 'r.tif')
            ds = gdal.GetDriverByName('GTiff').Create(path, 3000, 2000, 3, gdal.GDT_Byte, options=['TILED=YES'])
            for b in range(3):
                ds.GetRasterBand(b + 1).WriteArray(np.full((2000, 3000), 40 * (b + 1), dtype=np.uint8))
            ds = None
            ovr = xyz_core.build_overviews(path, progress_log=False)
            self.assertTrue(os.path.exists(ovr))
            ds = gdal.Open(path)
            self.assertEqual(ds.GetRasterBand(1).GetOverviewCount(), len(xyz_core.overview_levels(3000, 2000)))
            self.assertEqual(int(ds.GetRasterBand(2).GetOverview(0).ReadAsArray().mean()), 80)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class MultiZoomTest(unittest.TestCase):
    def test_gehist_multi_zoom_and_sampling(self):
        import gehist_core as gh
        import test_gehist_core as tg
        srv = tg.FakeKeyhole()
        client = gh.KeyholeClient(cache_dir='', fetch=srv.fetch)
        rows = gh.list_dates_multi(tg.BBOX, [tg.LEVEL], client=client)
        self.assertEqual([(r['date'], r['zoom'], r['estimated']) for r in rows],
                         [('2022-06-28', 6, False), ('2019-05-10', 6, False)])
        saved = gh.FULL_SCAN_TILES, gh.SAMPLE_TILES
        gh.FULL_SCAN_TILES, gh.SAMPLE_TILES = 2, 2       # forca a amostragem
        try:
            rows = gh.list_dates_multi(tg.BBOX, [tg.LEVEL], client=client)
            self.assertTrue(all(r['estimated'] for r in rows))
            self.assertLess(rows[0]['total_tiles'], 6)
        finally:
            gh.FULL_SCAN_TILES, gh.SAMPLE_TILES = saved

    def test_esri_versions_all_zooms(self):
        import esri_core
        import run_gee
        seen = []

        def fake(bbox, zoom):
            seen.append(zoom)
            return [{'release_num': 100 + zoom, 'release_date': '2024-01-01', 'capture_date': '2023-0%d-01' % (zoom - 14)}]

        saved = esri_core.local_versions_cached
        esri_core.local_versions_cached = fake
        try:
            res = run_gee.src_esri_versions({'bbox': '-56.1,-15.6,-56.0,-15.5', 'zooms': 'all'})
        finally:
            esri_core.local_versions_cached = saved
        self.assertEqual(sorted(seen), list(run_gee.WAYBACK_ZOOMS))
        self.assertEqual([v['zoom'] for v in res['versions']], [19, 18, 17, 16, 15])   # captura mais recente primeiro


if __name__ == '__main__':
    unittest.main()
