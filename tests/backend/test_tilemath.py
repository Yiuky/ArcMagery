# -*- coding: utf-8 -*-
import math
import unittest

import _paths  # noqa: F401
import tilemath


class TileMathTest(unittest.TestCase):
    def test_origin_tiles(self):
        self.assertEqual(tilemath.lonlat_to_tile(-180, 85.0, 1), (0, 0))
        self.assertEqual(tilemath.lonlat_to_tile(179.999, -85.0, 1), (1, 1))
        self.assertEqual(tilemath.lonlat_to_tile(0.0001, 0.0001, 1), (1, 0))

    def test_known_tile_cuiaba(self):
        # Referencia conferida com a biblioteca independente mercantile 1.2.1
        self.assertEqual(tilemath.lonlat_to_tile(-56.1, -15.6, 17), (45110, 71287))

    def test_tile_bounds_roundtrip(self):
        left, bottom, right, top = tilemath.tile_bounds_mercator(0, 0, 0)
        self.assertAlmostEqual(left, -tilemath.ORIGIN_SHIFT)
        self.assertAlmostEqual(top, tilemath.ORIGIN_SHIFT)
        self.assertAlmostEqual(right - left, 2 * tilemath.ORIGIN_SHIFT)

    def test_mercator_projection(self):
        x, y = tilemath.lonlat_to_mercator(-56.1, -15.6)
        self.assertAlmostEqual(x, -6245023.4335, places=3)   # mercantile.xy
        self.assertAlmostEqual(y, -1758446.4531, places=3)

    def test_clamp_and_degenerate(self):
        self.assertEqual(tilemath.clamp_bbox([10, 5, -10, -5]), [-10.0, -5.0, 10.0, 5.0])
        self.assertLess(tilemath.clamp_bbox([-10, -89, 10, 89])[3], 85.06)
        with self.assertRaises(ValueError):
            tilemath.clamp_bbox([1, 1, 1, 2])

    def test_edge_exactly_on_tile_border_not_included(self):
        l, b, r, t = tilemath.tile_bounds_mercator(10, 10, 5)
        n = 2 ** 5
        lon_right = (11 / float(n)) * 360.0 - 180.0  # borda direita exata do tile x=10
        x0, x1, _, _ = tilemath.tile_range([lon_right - 1.0, 0, lon_right, 1], 5)
        self.assertEqual(x1, 10)

    def test_quadkey(self):
        self.assertEqual(tilemath.quadkey(3, 5, 3), '213')   # exemplo da documentacao Bing
        self.assertEqual(tilemath.quadkey(0, 0, 1), '0')

    def test_crop_window_contains_bbox(self):
        bbox = [-56.10, -15.62, -56.09, -15.61]
        w = tilemath.crop_window(bbox, 17)
        res = w['res']
        bx0, by0 = tilemath.lonlat_to_mercator(bbox[0], bbox[1])
        bx1, by1 = tilemath.lonlat_to_mercator(bbox[2], bbox[3])
        self.assertLessEqual(w['left'], bx0)
        self.assertGreaterEqual(w['left'] + w['width'] * res, bx1)
        self.assertGreaterEqual(w['top'], by1)
        self.assertLessEqual(w['top'] - w['height'] * res, by0)
        # recorte no maximo 1 pixel maior que o bbox em cada borda
        self.assertLess(w['width'] * res - (bx1 - bx0), 2 * res + 1e-6)

    def test_estimate(self):
        est = tilemath.estimate([-56.10, -15.62, -56.09, -15.61], 17)
        self.assertEqual(est['tiles'], est['cols'] * est['rows'])
        expected = math.cos(math.radians(-15.615)) * tilemath.mercator_resolution(17)
        self.assertAlmostEqual(est['ground_res_m'], expected, places=6)
        self.assertAlmostEqual(est['ground_res_m'], 1.15, places=2)


if __name__ == '__main__':
    unittest.main()
