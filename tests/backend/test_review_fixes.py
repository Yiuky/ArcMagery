# -*- coding: utf-8 -*-
"""Regressoes da revisao de codigo (v2.3.3): amostragem em faixas estreitas, falhas de rede por
tile no Google Earth historico, piramides antigas e encerramento do backend apos um recorte CBERS."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

import _paths
import gehist_core as gh
import tilemath
import xyz_core
import test_gehist_core as tg


class SampleTilesTest(unittest.TestCase):
    def test_narrow_corridor_is_never_empty(self):
        """Faixa de 2 x ~8000 tiles no z20: o inicio da amostra caia fora da grade (amostra vazia)."""
        for bbox in ([-56.0, -15.6001, -50.5, -15.5997],     # leste-oeste
                     [-56.0001, -20.0, -55.9997, -15.0]):    # norte-sul
            win = tilemath.keyhole_crop_window(bbox, 20)
            rows, cols = win['r1'] - win['r0'] + 1, win['c1'] - win['c0'] + 1
            sample = list(gh._sample_tiles(win, 20, gh.Z20_SAMPLE_TILES))
            self.assertTrue(sample, (rows, cols))
            self.assertLessEqual(len(sample), 2 * gh.Z20_SAMPLE_TILES)
            for r, c, _p in sample:
                self.assertTrue(win['r0'] <= r <= win['r1'] and win['c0'] <= c <= win['c1'])


class FlakyFetch(object):
    """Envolve o servidor simulado: falha sempre (ou so na 1a vez) em URLs escolhidas."""

    def __init__(self, srv, match, times=None):
        self.srv, self.match, self.times, self.calls = srv, match, times, {}

    def __call__(self, url):
        if self.match in url:
            n = self.calls.get(url, 0)
            self.calls[url] = n + 1
            if self.times is None or n < self.times:
                raise RuntimeError("falha de rede simulada")
        return self.srv.fetch(url)


class NetworkFailuresTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='arcmagery_rev_')
        self.srv = tg.FakeKeyhole()
        # um tile da grade: o do canto noroeste
        r, c = self.srv.win['r1'], self.srv.win['c0']
        self.path = tilemath.keyhole_quadtree_path(r, c, tg.LEVEL)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _client(self, fetch):
        return gh.KeyholeClient(cache_dir='', fetch=fetch)

    def test_transient_tile_failure_is_retried(self):
        fetch = FlakyFetch(self.srv, 'f1-%s-' % self.path, times=1)
        res = gh.download(tg.BBOX, tg.LEVEL, '2019-05-10', os.path.join(self.tmp, 'a.tif'), compression='LZW',
                          client=self._client(fetch), engine='pil', overviews=False)
        self.assertEqual((res['failed_tiles'], res['tiles_with_date'], res['coverage_pct']), (0, 6, 100.0))

    def test_permanent_tile_failure_keeps_the_rest(self):
        """Antes: uma falha abortava o download inteiro e apagava o arquivo parcial."""
        fetch = FlakyFetch(self.srv, 'f1-%s-' % self.path)
        out = os.path.join(self.tmp, 'b.tif')
        res = gh.download(tg.BBOX, tg.LEVEL, '2019-05-10', out, compression='LZW',
                          client=self._client(fetch), engine='pil', overviews=False)
        self.assertTrue(os.path.exists(out))
        self.assertEqual((res['failed_tiles'], res['tiles_with_date']), (1, 5))
        self.assertLess(res['coverage_pct'], 100.0)

    def test_scan_all_failed_raises_clear_error(self):
        fetch = FlakyFetch(self.srv, 'qp-0')          # nem o pacote raiz responde
        client = gh.KeyholeClient(cache_dir='', fetch=self.srv.fetch)
        client._fetch = fetch
        client._packets.clear()
        with self.assertRaises(RuntimeError) as ctx:
            gh.list_dates_multi(tg.BBOX, [tg.LEVEL], client=client)
        self.assertIn(u'Nenhum tile', str(ctx.exception))

    def test_single_tile_failure_in_scan_is_estimated(self):
        """Falha pontual (dated_layers de um tile) -> busca segue, cobertura estimada."""
        client = self._client(self.srv.fetch)
        real = client.dated_layers

        def flaky(path):
            if path == self.path:
                raise RuntimeError("falha de rede simulada")
            return real(path)

        client.dated_layers = flaky
        rows = gh.list_dates_multi(tg.BBOX, [tg.LEVEL], client=client)
        full = [r for r in rows if r['date'] == '2019-05-10'][0]
        self.assertEqual((full['total_tiles'], full['coverage_pct'], full['estimated']), (5, 100.0, True))


@unittest.skipUnless(_paths.HAS_GDAL, "requer GDAL")
class StaleSidecarsTest(unittest.TestCase):
    def test_finalize_removes_previous_pyramids_and_stats(self):
        from osgeo import gdal
        tmp = tempfile.mkdtemp(prefix='arcmagery_side_')
        try:
            out = os.path.join(tmp, 'GoogleEarth_20200101_z18_rgb.tif')
            for ext in ('.ovr', '.aux.xml'):
                with open(out + ext, 'w') as f:
                    f.write('antigo')
            part = out + '.part.tif'
            ds = gdal.GetDriverByName('GTiff').Create(part, 64, 64, 3, gdal.GDT_Byte)
            ds = None
            xyz_core._finalize_output(part, out, None)
            self.assertTrue(os.path.exists(out))
            self.assertFalse(os.path.exists(out + '.ovr'))
            self.assertFalse(os.path.exists(out + '.aux.xml'))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipUnless(_paths.LIVE and _paths.HAS_GDAL, "defina ARCMAGERY_LIVE=1 (acessa o INPE)")
class CbersBackendExitLiveTest(unittest.TestCase):
    """O recorte levava ~4 s, mas o processo ficava vivo 300-900 s (conexoes /vsicurl/ abertas)."""

    def test_stac_download_process_exits_quickly(self):
        tmp = tempfile.mkdtemp(prefix='arcmagery_exit_')
        try:
            pf = os.path.join(tmp, 'p.json')
            with open(pf, 'w', encoding='utf-8') as f:
                json.dump({'collection': 'CB2-CCD-L2-DN-1', 'item_id': 'CBERS_2_CCD_20080411_170_111_L2',
                           'mode': 'rgb', 'bbox': '-59.25,-10.40,-58.95,-10.20',
                           'out': os.path.join(tmp, 'c.tif')}, f)
            run_gee = os.path.join(_paths.BACKEND, 'run_gee.py')
            t0 = time.time()
            proc = subprocess.run([sys.executable, run_gee, 'stac_download', '--params-file=' + pf],
                                  capture_output=True, timeout=240)
            elapsed = time.time() - t0
            self.assertIn(b'"success": true', proc.stdout)
            self.assertLess(elapsed, 60, "backend demorou %.0f s para encerrar" % elapsed)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
