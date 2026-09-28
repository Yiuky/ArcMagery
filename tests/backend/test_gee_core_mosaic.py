# -*- coding: utf-8 -*-
"""Regressoes dos bugs de mosaico da v1.11/1.12.

1. mask_clouds_and_shadows chamava getInfo() dentro de ImageCollection.map() -> o GEE rejeita
   ("A mapped function's arguments cannot be used in client-side operations"), o except
   engolia o erro e a mediana saia SEM mascara de nuvem.
2. img.toInt16() sobre Landsat C02 L2 (uint16) truncava SR > 32767 e ST_B10 (~45000 DN).
"""
import unittest

import _paths

try:
    import gee_core
    HAS_EE = True
except Exception:  # earthengine-api ausente neste Python
    HAS_EE = False


class FakeImage(object):
    """Imitacao minima de ee.Image que registra as operacoes e PROIBE chamadas client-side."""

    def __init__(self, log, name='img'):
        self.log, self.name = log, name

    def _op(self, op, *args):
        self.log.append((op,) + args)
        return FakeImage(self.log, '%s.%s' % (self.name, op))

    def select(self, b):
        return self._op('select', b)

    def neq(self, v):
        return self._op('neq', v)

    def eq(self, v):
        return self._op('eq', v)

    def And(self, o):
        return self._op('And')

    def bitwiseAnd(self, v):
        return self._op('bitwiseAnd', v)

    def updateMask(self, m):
        return self._op('updateMask')

    def toUint16(self):
        return self._op('toUint16')

    def toUint8(self):
        return self._op('toUint8')

    def toInt16(self):
        return self._op('toInt16')

    def bandNames(self):
        return self._op('bandNames')

    def getInfo(self):
        raise AssertionError("getInfo() dentro de map() nao e permitido pelo Earth Engine")


@unittest.skipUnless(HAS_EE, "earthengine-api indisponivel neste Python")
class MaskAndCastTest(unittest.TestCase):
    def setUp(self):
        self.log = []
        self._orig_constant = gee_core.ee.Image.constant
        gee_core.ee.Image.constant = staticmethod(lambda v: FakeImage(self.log, 'const'))

    def tearDown(self):
        gee_core.ee.Image.constant = self._orig_constant

    def test_s2_uses_scl_without_client_calls(self):
        gee_core.mask_clouds_and_shadows(FakeImage(self.log), 'S2')
        self.assertIn(('select', 'SCL'), self.log)
        self.assertEqual(sorted(v for (op, *a) in self.log if op == 'neq' for v in a), [3, 8, 9, 10])
        self.assertIn(('updateMask',), self.log)

    def test_landsat_oli_masks_cirrus(self):
        gee_core.mask_clouds_and_shadows(FakeImage(self.log), 'L8')
        self.assertIn(('select', 'QA_PIXEL'), self.log)
        bits = [a[0] for (op, *a) in self.log if op == 'bitwiseAnd']
        self.assertEqual(bits, [(1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4)])

    def test_landsat_tm_etm_without_cirrus_bit(self):
        for s in ('L7', 'L5', 'L4'):
            del self.log[:]
            gee_core.mask_clouds_and_shadows(FakeImage(self.log), s)
            bits = [a[0] for (op, *a) in self.log if op == 'bitwiseAnd']
            self.assertEqual(bits, [(1 << 0) | (1 << 1) | (1 << 3) | (1 << 4)], s)

    def test_mss_unmasked(self):
        img = FakeImage(self.log)
        self.assertIs(gee_core.mask_clouds_and_shadows(img, 'L1'), img)

    def test_cast_is_unsigned(self):
        gee_core.cast_mosaic_to_native_type(FakeImage(self.log), 'L8')
        gee_core.cast_mosaic_to_native_type(FakeImage(self.log), 'S2')
        gee_core.cast_mosaic_to_native_type(FakeImage(self.log), 'L2')
        ops = [e[0] for e in self.log]
        self.assertEqual(ops, ['toUint16', 'toUint16', 'toUint8'])
        self.assertNotIn('toInt16', ops)

    def test_no_toint16_left_in_download_path(self):
        import inspect
        src = inspect.getsource(gee_core.download_geotiff)
        self.assertNotIn('toInt16()', src)
        self.assertIn('cast_mosaic_to_native_type', src)


@unittest.skipUnless(HAS_EE and _paths.LIVE and _paths.GEE_PROJECT,
                     "defina ARCMAGERY_LIVE=1 e ARCMAGERY_GEE_PROJECT=<id> para o teste no Earth Engine")
class GeeLiveTest(unittest.TestCase):
    def test_masked_median_keeps_thermal_range(self):
        ee = gee_core.ee
        ee.Initialize(project=_paths.GEE_PROJECT)
        pt = ee.Geometry.Point(-56.1, -15.6)
        coll = (ee.ImageCollection('LANDSAT/LC08/C02/T1_L2').filterBounds(pt)
                .filterDate('2024-06-01', '2024-09-30').limit(4))
        masked = coll.map(lambda im: gee_core.mask_clouds_and_shadows(im, 'L8'))
        img = gee_core.cast_mosaic_to_native_type(masked.median(), 'L8')
        types = img.select(['SR_B4', 'ST_B10']).bandTypes().getInfo()
        self.assertEqual(types['ST_B10']['max'], 65535)
        mx = img.select('ST_B10').reduceRegion(ee.Reducer.max(), pt.buffer(5000), 30).getInfo()['ST_B10']
        self.assertGreater(mx, 32767, "ST_B10 truncado em int16")


if __name__ == '__main__':
    unittest.main()
