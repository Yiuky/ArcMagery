# -*- coding: utf-8 -*-
"""
Script de Testes Automatizados para Validacao de Integridade de Rasters
e Prevencao de Colapso de Bandas no Plugin ArcGEE.
"""

import os
import sys
import json
import unittest
import numpy as np

import _paths  # noqa: F401  (backend no sys.path)
import gee_core
sys.path.insert(0, os.path.dirname(_paths.BACKEND))  # arcgis_addin/Install (ponte compativel com Py3)
import gee_bridge

class TestBandParsingAndMathDetection(unittest.TestCase):
    def test_landsat5_custom_bands_parsing(self):
        # 4 bandas solicitadas no Landsat 5
        raw = "SR_B3, SR_B4, SR_B5, SR_B7"
        self.assertFalse(gee_core.is_math_expr(raw))
        bands = gee_core.parse_bands(raw, "L5")
        self.assertEqual(bands, ['SR_B3', 'SR_B4', 'SR_B5', 'SR_B7'])

    def test_parentheses_and_brackets_wrapping(self):
        # Envolvidos em parenteses ou colchetes nao devem ser considerados formula matematica
        raw_paren = "(SR_B3, SR_B4, SR_B5, SR_B7)"
        self.assertFalse(gee_core.is_math_expr(raw_paren))
        self.assertEqual(gee_core.parse_bands(raw_paren, "L5"), ['SR_B3', 'SR_B4', 'SR_B5', 'SR_B7'])

        raw_bracket = "[SR_B3, SR_B4, SR_B5, SR_B7]"
        self.assertFalse(gee_core.is_math_expr(raw_bracket))
        self.assertEqual(gee_core.parse_bands(raw_bracket, "L5"), ['SR_B3', 'SR_B4', 'SR_B5', 'SR_B7'])

    def test_range_expansion(self):
        # Expansao inteligente de intervalos com hifen
        raw_range = "B3-B5, B7"
        self.assertFalse(gee_core.is_math_expr(raw_range))
        self.assertEqual(gee_core.parse_bands(raw_range, "L5"), ['SR_B3', 'SR_B4', 'SR_B5', 'SR_B7'])

        raw_sr_range = "SR_B3-SR_B5, SR_B7"
        self.assertFalse(gee_core.is_math_expr(raw_sr_range))
        self.assertEqual(gee_core.parse_bands(raw_sr_range, "L5"), ['SR_B3', 'SR_B4', 'SR_B5', 'SR_B7'])

    def test_landsat5_thermal_mapping(self):
        # Landsat 5 nao possui SR_B6; a banda 6 e termica (ST_B6)
        raw_b6 = "B1, B2, B3, B4, B5, B6, B7"
        bands = gee_core.parse_bands(raw_b6, "L5")
        self.assertEqual(bands, ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'ST_B6', 'SR_B7'])

    def test_genuine_math_formulas(self):
        # Formulas matematicas legitimas devem retornar is_math_expr == True
        self.assertTrue(gee_core.is_math_expr("(SR_B4 - SR_B3) / (SR_B4 + SR_B3)"))
        self.assertTrue(gee_core.is_math_expr("(B8 - B4) / (B8 + B4)"))
        self.assertTrue(gee_core.is_math_expr("SR_B5 - SR_B4"))
        self.assertTrue(gee_core.is_math_expr("2.5 * (NIR - RED) / (NIR + 6*RED - 7.5*BLUE + 1)"))
        self.assertTrue(gee_core.is_math_expr("sqrt(SR_B4)"))

    def test_gee_bridge_sync(self):
        # Garantir que gee_bridge possui exatamente as mesmas funcoes e comportamento
        self.assertEqual(gee_bridge.parse_bands("SR_B3, SR_B4, SR_B5, SR_B7", "L5"), ['SR_B3', 'SR_B4', 'SR_B5', 'SR_B7'])
        self.assertFalse(gee_bridge.is_math_expr("(SR_B3, SR_B4, SR_B5, SR_B7)"))
        self.assertTrue(gee_bridge.is_math_expr("(SR_B4 - SR_B3)/(SR_B4 + SR_B3)"))

class TestRasterHealthCheck(unittest.TestCase):
    def setUp(self):
        self.temp_files = []

    def tearDown(self):
        for f in self.temp_files:
            if os.path.exists(f):
                try: os.remove(f)
                except Exception: pass
            aux = f + ".aux.xml"
            if os.path.exists(aux):
                try: os.remove(aux)
                except Exception: pass

    @unittest.skipUnless(_paths.HAS_GDAL, "GDAL indisponivel (ex.: CI sem QGIS)")
    def test_valid_4band_raster_passes_healthcheck(self):
        from osgeo import gdal, osr
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)
        path = "test_valid_4b.tif"
        self.temp_files.append(path)

        drv = gdal.GetDriverByName("GTiff")
        ds = drv.Create(path, 80, 80, 4, gdal.GDT_Int16)
        ds.SetGeoTransform([-55.0, 0.00027, 0, -12.0, 0, -0.00027])
        ds.SetProjection(srs.ExportToWkt())
        for i in range(1, 5):
            arr = np.random.randint(200, 3500, size=(80, 80), dtype=np.int16)
            ds.GetRasterBand(i).WriteArray(arr)
            ds.GetRasterBand(i).SetDescription("SR_B%d" % (i+2))
        ds.FlushCache()
        ds = None

        ok, diag = gee_core.validate_geotiff_health(path, expected_bands=['SR_B3', 'SR_B4', 'SR_B5', 'SR_B7'])
        self.assertTrue(ok)
        self.assertEqual(diag['actual_band_count'], 4)
        self.assertEqual(len(diag['failures']), 0)

    @unittest.skipUnless(_paths.HAS_GDAL, "GDAL indisponivel (ex.: CI sem QGIS)")
    def test_collapsed_1band_raster_raises_healthcheck_error_and_deletes(self):
        from osgeo import gdal, osr
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)
        path = "test_collapsed_1b.tif"
        self.temp_files.append(path)

        drv = gdal.GetDriverByName("GTiff")
        ds = drv.Create(path, 80, 80, 1, gdal.GDT_Int16)
        ds.SetGeoTransform([-55.0, 0.00027, 0, -12.0, 0, -0.00027])
        ds.SetProjection(srs.ExportToWkt())
        arr = np.random.randint(200, 3500, size=(80, 80), dtype=np.int16)
        ds.GetRasterBand(1).WriteArray(arr)
        ds.FlushCache()
        ds = None

        with self.assertRaises(gee_core.RasterHealthCheckError) as ctx:
            gee_core.validate_geotiff_health(path, expected_bands=['SR_B3', 'SR_B4', 'SR_B5', 'SR_B7'])

        # Validar que o arquivo corrompido foi descartado do disco
        self.assertFalse(os.path.exists(path))
        # Validar diagnosticos estruturados
        diag = ctx.exception.diagnostics
        self.assertEqual(diag['actual_band_count'], 1)
        self.assertEqual(diag['expected_band_count'], 4)
        self.assertTrue(any('Contagem de bandas divergente' in f for f in diag['failures']))

    @unittest.skipUnless(_paths.HAS_GDAL, "GDAL indisponivel (ex.: CI sem QGIS)")
    def test_all_zero_raster_raises_healthcheck_error_and_deletes(self):
        from osgeo import gdal, osr
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)
        path = "test_empty_zero.tif"
        self.temp_files.append(path)

        drv = gdal.GetDriverByName("GTiff")
        ds = drv.Create(path, 80, 80, 4, gdal.GDT_Int16)
        ds.SetGeoTransform([-55.0, 0.00027, 0, -12.0, 0, -0.00027])
        ds.SetProjection(srs.ExportToWkt())
        for i in range(1, 5):
            ds.GetRasterBand(i).WriteArray(np.zeros((80, 80), dtype=np.int16))
        ds.FlushCache()
        ds = None

        with self.assertRaises(gee_core.RasterHealthCheckError) as ctx:
            gee_core.validate_geotiff_health(path, expected_bands=['SR_B3', 'SR_B4', 'SR_B5', 'SR_B7'])

        self.assertFalse(os.path.exists(path))
        diag = ctx.exception.diagnostics
        self.assertTrue(any('todas as bandas contêm valor constante zero' in f for f in diag['failures']))

    @unittest.skipUnless(_paths.HAS_GDAL, "GDAL indisponivel (ex.: CI sem QGIS)")
    def test_merge_geotiff_tiles_preserves_all_4_bands(self):
        from osgeo import gdal, osr
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)
        t1 = "test_merge_tile1.tif"
        t2 = "test_merge_tile2.tif"
        out_merged = "test_merge_out_4b.tif"
        self.temp_files.extend([t1, t2, out_merged])

        drv = gdal.GetDriverByName("GTiff")
        # Tile 1
        ds1 = drv.Create(t1, 40, 80, 4, gdal.GDT_Int16)
        ds1.SetGeoTransform([-55.0, 0.00027, 0, -12.0, 0, -0.00027])
        ds1.SetProjection(srs.ExportToWkt())
        for i in range(1, 5):
            ds1.GetRasterBand(i).WriteArray(np.random.randint(200, 3000, size=(80, 40), dtype=np.int16))
        ds1.FlushCache()
        ds1 = None

        # Tile 2
        ds2 = drv.Create(t2, 40, 80, 4, gdal.GDT_Int16)
        ds2.SetGeoTransform([-55.0 + 40 * 0.00027, 0.00027, 0, -12.0, 0, -0.00027])
        ds2.SetProjection(srs.ExportToWkt())
        for i in range(1, 5):
            ds2.GetRasterBand(i).WriteArray(np.random.randint(200, 3000, size=(80, 40), dtype=np.int16))
        ds2.FlushCache()
        ds2 = None

        # Mesclar tiles
        merged = gee_core.merge_geotiff_tiles([t1, t2], out_merged, expected_bands_count=4)
        self.assertEqual(merged, out_merged)
        self.assertTrue(os.path.exists(out_merged))

        # Validar via Health Check
        ok, diag = gee_core.validate_geotiff_health(out_merged, expected_bands=['SR_B3', 'SR_B4', 'SR_B5', 'SR_B7'])
        self.assertTrue(ok)
        self.assertEqual(diag['actual_band_count'], 4)
        self.assertEqual(diag['dimensions']['width'], 80)
        self.assertEqual(diag['dimensions']['height'], 80)

if __name__ == '__main__':
    unittest.main()
