# -*- coding: utf-8 -*-
"""Simbologia garantida (bandas RGB + Stretch) com ArcObjects REAL, fora do ArcMap.

Fluxo testado, igual ao do load_into_toc:
  GeoTIFF -> MakeRasterLayer/SaveToLayerFile -> apply_to_layer_file (grava e rele o .lyr)
  -> arcpy.mapping.AddLayer num .mxd -> leitura via COM (IMapDocument) -> ensure_layer_symbology.
Requer ArcGIS Desktop (arcpy + comtypes) e um Python 3 com GDAL para gerar os rasters de teste.
"""
from __future__ import print_function

import glob
import os
import shutil
import subprocess
import tempfile
import unittest

import _paths

try:
    import arcpy
    import comtypes.client  # noqa: F401
    import arcmagery_symbology as sym
    sym.carto()
    HAS_AO = True
except Exception:
    HAS_AO = False

TEMPLATES = sorted(glob.glob(r"C:\Program Files (x86)\ArcGIS\Desktop10.8\MapTemplates\Traditional Layouts\*.mxd") +
                   glob.glob(r"C:\Program Files (x86)\ArcGIS\Desktop10.8\MapTemplates\Standard Page Sizes\*\*.mxd"))

MAKE_RASTERS = r'''
import sys, numpy as np
from osgeo import gdal, osr
gdal.UseExceptions()
srs = osr.SpatialReference(); srs.ImportFromEPSG(32721)
for path, nb, dt, scale in ((sys.argv[1], 4, gdal.GDT_UInt16, 4000), (sys.argv[2], 1, gdal.GDT_Float32, 1),
                            (sys.argv[3], 4, gdal.GDT_UInt16, 4000)):
    ds = gdal.GetDriverByName('GTiff').Create(path, 120, 80, nb, dt)
    ds.SetGeoTransform((590000, 8, 0, 8285000, 0, -8)); ds.SetProjection(srs.ExportToWkt())
    for b in range(nb):
        ds.GetRasterBand(b + 1).WriteArray((np.random.RandomState(b).rand(80, 120) * scale).astype(np.float32))
    ds = None
'''

def gee_bridge_short_path(path):
    """Forma curta 8.3 do caminho (como o %TEMP% costuma vir), para testar a normalizacao."""
    import ctypes
    buf = ctypes.create_unicode_buffer(32768)
    n = ctypes.windll.kernel32.GetShortPathNameW(unicode(path), buf, 32768)  # noqa: F821
    return buf.value if n else path


SETTINGS = [
    {'stretch_type': 'Standard Deviations', 'stretch_std_param': 2.5, 'statistics_type': 'From Current Display Extent'},
    {'stretch_type': 'Percent Clip', 'statistics_type': 'From Each Raster Dataset'},
    {'stretch_type': 'Minimum-Maximum', 'statistics_type': 'From Current Display Extent'},
    {'stretch_type': 'Histogram Equalize', 'statistics_type': 'From Each Raster Dataset'},
]


@unittest.skipUnless(HAS_AO and _paths.qgis_python() and TEMPLATES, "requer ArcGIS (arcpy+comtypes), QGIS e modelo .mxd")
class SymbologyEngineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='arcmagery_symb_')
        cls.rgb = os.path.join(cls.tmp, 'cena_multi.tif')
        cls.ndvi = os.path.join(cls.tmp, 'cena_ndvi.tif')
        cls.rgb_b = os.path.join(cls.tmp, 'cena_multi_b.tif')       # nome parecido com o primeiro
        script = os.path.join(cls.tmp, 'mk.py')
        with open(script, 'w') as f:
            f.write(MAKE_RASTERS)
        env = dict(os.environ)
        env.pop('PYTHONHOME', None)
        env.pop('PYTHONPATH', None)
        subprocess.check_call([_paths.qgis_python(), script, cls.rgb, cls.ndvi, cls.rgb_b], env=env)
        arcpy.env.overwriteOutput = True

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _lyr(self, tif, name):
        lyr = os.path.join(self.tmp, name + '.lyr')
        tmp_name = 'arcmagery_t_' + name
        arcpy.MakeRasterLayer_management(tif, tmp_name)
        arcpy.SaveToLayerFile_management(tmp_name, lyr)
        arcpy.Delete_management(tmp_name)
        return lyr

    def _mxd_with(self, lyr_files):
        mxd_path = os.path.join(self.tmp, 'teste_%d.mxd' % len(os.listdir(self.tmp)))
        shutil.copy(TEMPLATES[0], mxd_path)
        mxd = arcpy.mapping.MapDocument(mxd_path)
        df = arcpy.mapping.ListDataFrames(mxd)[0]
        for lyr in lyr_files:
            arcpy.mapping.AddLayer(df, arcpy.mapping.Layer(lyr), "TOP")
        mxd.save()
        del mxd
        doc = comtypes.client.CreateObject(sym.carto().MapDocument, interface=sym.carto().IMapDocument)
        doc.Open(mxd_path, "")
        return doc

    def test_layer_file_roundtrip_for_every_stretch(self):
        for i, settings in enumerate(SETTINGS):
            lyr = self._lyr(self.rgb, 'rgb_%d' % i)
            state = sym.apply_to_layer_file(lyr, settings, rgb_bands=(2, 1, 0))
            exp = sym.expected_state(settings, 4, (2, 1, 0))
            self.assertEqual(sym.compare(state, exp), [], settings)
            self.assertEqual(state['bands'], (2, 1, 0))

    def test_single_band_gets_stretched_renderer(self):
        settings = SETTINGS[0]
        lyr = self._lyr(self.ndvi, 'ndvi')
        state = sym.apply_to_layer_file(lyr, settings)
        self.assertEqual(state['renderer'], 'STRETCH')
        self.assertEqual(state['std_param'], 2.5)

    def test_symbology_survives_insertion_in_map(self):
        settings = SETTINGS[0]
        lyr = self._lyr(self.rgb, 'mapa_rgb')
        sym.apply_to_layer_file(lyr, settings, rgb_bands=(3, 2, 1))
        doc = self._mxd_with([lyr])
        try:
            found = sym.find_layers_by_path(self.rgb, doc.Map(0))
            self.assertEqual(len(found), 1)
            state = sym.read_state(found[0][1])
            self.assertEqual(sym.compare(state, sym.expected_state(settings, 4, (3, 2, 1))), [])
        finally:
            doc.Close()

    def test_ensure_fixes_wrong_layer_and_ignores_similar_names(self):
        settings = SETTINGS[0]
        lyr_a = self._lyr(self.rgb, 'cena_multi')          # alvo
        lyr_b = self._lyr(self.rgb_b, 'cena_multi_b')      # vizinha de nome parecido
        sym.apply_to_layer_file(lyr_a, settings, rgb_bands=(2, 1, 0))
        wrong = {'stretch_type': 'Minimum-Maximum', 'statistics_type': 'From Each Raster Dataset'}
        sym.apply_to_layer_file(lyr_b, wrong, rgb_bands=(0, 1, 2))
        doc = self._mxd_with([lyr_a, lyr_b])
        try:
            fmap = doc.Map(0)
            # sabotar a camada alvo (como quando o ArcMap reseta o renderer)
            (_l, rl_a), = sym.find_layers_by_path(self.rgb, fmap)
            sym.configure_raster_layer(rl_a, wrong, rgb_bands=(0, 1, 2))
            ok, msg, states = sym.ensure_layer_symbology(self.rgb, settings, rgb_bands=(2, 1, 0), focus_map=fmap)
            self.assertTrue(ok, msg)
            self.assertEqual(sym.compare(states[0], sym.expected_state(settings, 4, (2, 1, 0))), [])
            # a vizinha de nome parecido NAO pode ter sido alterada
            (_l, rl_b), = sym.find_layers_by_path(self.rgb_b, fmap)
            self.assertEqual(sym.compare(sym.read_state(rl_b), sym.expected_state(wrong, 4, (0, 1, 2))), [])
        finally:
            doc.Close()

    def test_missing_layer_is_reported(self):
        lyr = self._lyr(self.ndvi, 'so_ndvi')
        doc = self._mxd_with([lyr])
        try:
            ok, msg, _ = sym.ensure_layer_symbology(self.rgb, SETTINGS[0], focus_map=doc.Map(0))
            self.assertFalse(ok)
            self.assertIn(u'não encontrada', msg)
        finally:
            doc.Close()

    def test_bridge_load_flow_in_map(self):
        """Mesmas funcoes chamadas pelo load_into_toc: _prepare_layer_symbology (.lyr) e
        _ensure_live_symbology (camada no mapa), com o caminho curto 8.3 do %TEMP%."""
        import gee_bridge
        settings = {'stretch_type': 'Standard Deviations', 'stretch_std_param': 1.5,
                    'statistics_type': 'From Current Display Extent'}
        lyr = self._lyr(self.rgb, 'fluxo_carga')
        self.assertEqual(gee_bridge._prepare_layer_symbology(lyr, settings, (2, 1, 0)), u"")
        doc = self._mxd_with([lyr])
        try:
            short_tif = gee_bridge_short_path(self.rgb)
            msg = gee_bridge._ensure_live_symbology(short_tif, settings, (2, 1, 0), 'fluxo_carga',
                                                    focus_map=doc.Map(0))
            self.assertNotIn(gee_bridge.SYMBOLOGY_WARNING_PREFIX, msg)
            self.assertIn(u'RGB (3, 2, 1)', msg)
            self.assertIn(u'n=1.5', msg)
            # arquivo que nao esta no mapa -> aviso explicito (nunca "sucesso" silencioso)
            warn = gee_bridge._ensure_live_symbology(self.ndvi, settings, None, 'x', focus_map=doc.Map(0))
            self.assertIn(gee_bridge.SYMBOLOGY_WARNING_PREFIX, warn)
        finally:
            doc.Close()

    def test_restretch_preserves_band_combination(self):
        settings_old = {'stretch_type': 'Minimum-Maximum', 'statistics_type': 'From Each Raster Dataset'}
        settings_new = {'stretch_type': 'Standard Deviations', 'stretch_std_param': 3.0,
                        'statistics_type': 'From Current Display Extent'}
        lyr = self._lyr(self.rgb, 'restretch')
        sym.apply_to_layer_file(lyr, settings_old, rgb_bands=(3, 1, 0))
        doc = self._mxd_with([lyr])
        try:
            updated, problems = sym.restretch_layers(settings_new, focus_map=doc.Map(0))
            self.assertEqual((updated, problems), (1, []))
            (_l, rl), = sym.find_layers_by_path(self.rgb, doc.Map(0))
            state = sym.read_state(rl)
            self.assertEqual(state['bands'], (3, 1, 0), "as bandas escolhidas nao podem ser redefinidas")
            self.assertEqual(sym.compare(state, sym.expected_state(settings_new, 4, (3, 1, 0))), [])
        finally:
            doc.Close()

    def test_live_arcmap_path_uses_imxdocument(self):
        """Regressao do erro 'Simbologia nao pode ser verificada: FocusMap' visto no ArcMap:
        IApplication.Document e um IDocument SEM FocusMap; e preciso QueryInterface(IMxDocument).
        Simula o AppRef do ArcMap com o mapa real de um .mxd por tras."""
        import comtypes.client as cc
        framework, arcmap_ui = sym.arcmap_modules()
        settings = SETTINGS[0]
        lyr = self._lyr(self.rgb, 'vivo')
        sym.apply_to_layer_file(lyr, {'stretch_type': 'Minimum-Maximum'}, rgb_bands=(0, 1, 2))  # "errada"
        doc = self._mxd_with([lyr])
        calls = []

        class FakeMxDocument(object):
            FocusMap = doc.Map(0)

            def UpdateContents(self):
                calls.append('UpdateContents')

            class ActiveView(object):
                @staticmethod
                def Refresh():
                    calls.append('Refresh')

        class FakeIDocument(object):          # como o IDocument real: nao tem FocusMap
            def QueryInterface(self, itf):
                calls.append(itf)
                return FakeMxDocument()

        class FakeApp(object):
            Document = FakeIDocument()

        original = cc.CreateObject

        def fake_create(what, *a, **k):
            if what is framework.AppRef:
                return FakeApp()
            return original(what, *a, **k)

        cc.CreateObject = fake_create
        try:
            ok, msg, states = sym.ensure_layer_symbology(self.rgb, settings, rgb_bands=(2, 1, 0))
        finally:
            cc.CreateObject = original
            doc.Close()
        self.assertTrue(ok, msg)
        self.assertIn(arcmap_ui.IMxDocument, calls)
        self.assertIn('UpdateContents', calls)
        self.assertIn('Refresh', calls)
        self.assertEqual(sym.compare(states[0], sym.expected_state(settings, 4, (2, 1, 0))), [])

    def test_invalid_band_request_is_rejected(self):
        with self.assertRaises(sym.SymbologyError):
            sym.expected_state(SETTINGS[0], 4, (0, 1, 7))


if __name__ == '__main__':
    unittest.main()
