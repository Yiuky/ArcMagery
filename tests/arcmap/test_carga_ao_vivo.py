# -*- coding: utf-8 -*-
"""Carga no ArcMap de TODAS as imagens baixadas pela suíte ao vivo (tests/qgis/test_ao_vivo.py).

Para cada GeoTIFF do manifesto, o mesmo caminho do gee_bridge.load_into_toc, fora do ArcMap:
estatísticas e pirâmides -> MakeRasterLayer/.lyr -> bandas RGB (resolve_rgb_band_indices ou as do backend)
-> simbologia gravada e relida (_prepare_layer_symbology) -> camada inserida num .mxd -> simbologia
conferida na camada viva (_ensure_live_symbology). Também confere que a extensão cai sobre a área pedida.

Uso (a 1ª linha baixa tudo com o Python do QGIS; a 2ª carrega no ArcMap com o Python 2.7 do ArcGIS):
    set ARCMAGERY_LIVE=1
    set ARCMAGERY_LIVE_KEEP=%TEMP%\\arcmagery_ao_vivo
    "C:\\Program Files\\QGIS 3.xx\\bin\\python-qgis-ltr.bat" tests\\qgis\\test_ao_vivo.py
    C:\\Python27\\ArcGIS10.8\\python.exe tests\\arcmap\\test_carga_ao_vivo.py
"""
from __future__ import print_function

import io
import json
import os
import shutil
import tempfile
import unittest

import _paths

KEEP = os.environ.get('ARCMAGERY_LIVE_KEEP')
MANIFEST = os.path.join(KEEP, 'manifesto.json') if KEEP else None

try:
    import arcpy
    import comtypes.client  # noqa: F401
    import arcmagery_symbology as sym
    import gee_bridge
    sym.carto()
    HAS_AO = True
except Exception:
    HAS_AO = False

SETTINGS = {'stretch_type': 'Standard Deviations', 'stretch_std_param': 2.5,
            'statistics_type': 'From Current Display Extent'}


@unittest.skipUnless(HAS_AO and MANIFEST and os.path.exists(MANIFEST or ''),
                     "rode antes tests/qgis/test_ao_vivo.py com ARCMAGERY_LIVE=1 e ARCMAGERY_LIVE_KEEP")
class CargaNoArcMap(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with io.open(MANIFEST, encoding='utf-8') as f:
            cls.entries = [e for e in json.load(f) if os.path.exists(e['path'])]
        cls.tmp = tempfile.mkdtemp(prefix='arcmagery_carga_')
        arcpy.env.overwriteOutput = True
        cls.results = []

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)
        ok = sum(1 for r in cls.results if r[-1] == 'ok')
        print('\n%d de %d imagens carregadas e conferidas no ArcMap' % (ok, len(cls.results)))
        for r in cls.results:
            if r[-1] != 'ok':
                print('  FALHA %s %s %s: %s' % r)

    def _layer_for(self, entry, idx):
        tif = entry['path']
        gee_bridge._stats_and_pyramids(tif)
        bands = getattr(arcpy.Describe(tif), 'bandCount', 1)
        lyr = os.path.join(self.tmp, 'camada_%03d.lyr' % idx)
        name = 'arcmagery_live_%03d' % idx
        arcpy.MakeRasterLayer_management(tif, name)
        arcpy.SaveToLayerFile_management(name, lyr)
        arcpy.Delete_management(name)
        rgb = None
        if bands >= 3:
            rgb = gee_bridge._rgb_override(entry.get('rgb_bands')) or gee_bridge.resolve_rgb_band_indices(
                entry['sensor'] if entry['source'] == 'gee' else None, entry['comp'], entry.get('custom_bands'), bands)
        warning = gee_bridge._prepare_layer_symbology(lyr, SETTINGS, rgb)
        self.assertEqual(warning, u"", msg=warning)
        return lyr, rgb, bands

    def _extent_ok(self, entry):
        ext = arcpy.Describe(entry['path']).extent
        wgs = arcpy.SpatialReference(4326)
        center = arcpy.PointGeometry(arcpy.Point((ext.XMin + ext.XMax) / 2.0, (ext.YMin + ext.YMax) / 2.0),
                                     arcpy.Describe(entry['path']).spatialReference).projectAs(wgs)
        x, y = center.firstPoint.X, center.firstPoint.Y
        b = entry['bbox']
        return b[0] - 0.05 <= x <= b[2] + 0.05 and b[1] - 0.05 <= y <= b[3] + 0.05, (x, y)

    def test_todas_as_imagens(self):
        self.assertTrue(self.entries, 'manifesto vazio')
        import glob
        templates = sorted(glob.glob(r"C:\Program Files (x86)\ArcGIS\Desktop10.8\MapTemplates\Traditional Layouts\*.mxd"))
        template = templates[0] if templates else None
        self.assertTrue(template, 'modelo .mxd do ArcGIS não encontrado')
        mxd_path = os.path.join(self.tmp, 'carga.mxd')
        shutil.copy(template, mxd_path)
        mxd = arcpy.mapping.MapDocument(mxd_path)
        df = arcpy.mapping.ListDataFrames(mxd)[0]
        prepared = []
        for i, e in enumerate(self.entries):
            label = (e['source'], e['sensor'], e['comp'])
            try:
                inside, center = self._extent_ok(e)
                self.assertTrue(inside, 'centro fora da área: %.4f, %.4f' % center)
                lyr, rgb, bands = self._layer_for(e, i)
                arcpy.mapping.AddLayer(df, arcpy.mapping.Layer(lyr), "TOP")
                prepared.append((e, rgb, label))
            except Exception as ex:
                self.results.append(label + (u'%s' % ex,))
        mxd.save()
        del mxd
        doc = comtypes.client.CreateObject(sym.carto().MapDocument, interface=sym.carto().IMapDocument)
        doc.Open(mxd_path, "")
        try:
            fmap = doc.Map(0)
            for e, rgb, label in prepared:
                msg = gee_bridge._ensure_live_symbology(e['path'], SETTINGS, rgb, os.path.basename(e['path']),
                                                        focus_map=fmap)
                self.results.append(label + ('ok' if gee_bridge.SYMBOLOGY_WARNING_PREFIX not in msg else msg,))
        finally:
            doc.Close()
        failures = [r for r in self.results if r[-1] != 'ok']
        self.assertEqual(failures, [], msg='\n'.join('%s %s %s: %s' % r for r in failures))


if __name__ == '__main__':
    unittest.main(verbosity=2)
