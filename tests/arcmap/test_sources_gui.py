# -*- coding: utf-8 -*-
"""Janela Google Earth / Mosaicos XYZ (Python 2.7 + Tk 8.5): funcoes puras e fumaca da interface."""
from __future__ import print_function

import os
import shutil
import tempfile
import threading
import unittest

import _paths
import arcmagery_sources_gui as sg
import gee_bridge


class PureHelpersTest(unittest.TestCase):
    def test_parse_progress(self):
        self.assertEqual(sg.parse_progress('[ArcGEE] PROGRESS 12/40 tiles'), (12, 40))
        self.assertEqual(sg.parse_progress(u'[ArcGEE] PROGRESS 55/100'), (55, 100))
        self.assertIsNone(sg.parse_progress('[ArcGEE] XYZ esri z17'))
        self.assertIsNone(sg.parse_progress('PROGRESS 1/0'))

    def test_bbox_from_geojson(self):
        fc = {'type': 'FeatureCollection', 'features': [
            {'type': 'Feature', 'geometry': {'type': 'Polygon', 'coordinates': [[[-56, -16], [-55, -16], [-55, -15], [-56, -16]]]}},
            {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [-57, -14]}}]}
        self.assertEqual(sg.bbox_from_geojson_data(fc), [-57.0, -16.0, -55.0, -14.0])
        with self.assertRaises(ValueError):
            sg.bbox_from_geojson_data({'type': 'FeatureCollection', 'features': []})

    def test_filenames(self):
        self.assertEqual(sg.safe_filename(u'CBERS 4A/WPM:ção'), u'CBERS_4A_WPM_o')
        tmp = tempfile.mkdtemp()
        try:
            p1 = sg.unique_path(tmp, u'a')
            open(p1, 'w').close()
            p2 = sg.unique_path(tmp, u'a')
            self.assertNotEqual(p1, p2)
            self.assertTrue(p2.endswith(u'.tif'))
        finally:
            shutil.rmtree(tmp)

    def test_default_output_dir_is_unicode(self):
        self.assertIsInstance(sg.default_output_dir(), unicode)  # noqa: F821


class FakeParent(object):
    def __init__(self, root):
        self.root = root
        self.settings = {}
        self.arcmap_context = {'bbox': [-56.10, -15.62, -56.09, -15.61], 'vector_layers': [u'AOI_Cuiabá']}
        self.ipc_lock = threading.Lock()
        self.posted = []

    def post_to_gui(self, fn):
        self.posted.append(fn)

    def pump(self):
        while self.posted:
            self.posted.pop(0)()


class DialogSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = sg.tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.parent = FakeParent(self.root)
        self.dlg = sg.ExtraSourcesDialog(self.parent)
        self.dlg.top.withdraw()
        self.saved = {}

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(gee_bridge, k, v)
        self.dlg.top.destroy()

    def _patch_bridge(self, name, fn):
        self.saved.setdefault(name, getattr(gee_bridge, name))
        setattr(gee_bridge, name, fn)

    def test_estimate_and_tos_label(self):
        self.dlg.cbo_provider.current(0)          # Google
        self.dlg.var_zoom.set('17')
        self.dlg._update_estimate()
        self.assertIn(u'20 tiles', self.dlg.lbl_estimate.cget('text'))
        self.assertIn(u'Termos', self.dlg.lbl_tos.cget('text'))
        self.dlg.cbo_provider.current(2)          # Esri
        self.dlg._update_estimate()
        self.assertEqual(self.dlg.lbl_tos.cget('text'), u'')
        self.dlg.var_zoom.set('21')               # Esri vai ate 19
        self.dlg._update_estimate()
        self.assertIn(u'até 19', self.dlg.lbl_estimate.cget('text'))

    def test_xyz_worker_calls_backend_and_loads_rgb(self):
        calls = {}

        def fake_backend(cmd, params, on_progress=None, python_exe=None):
            calls['cmd'], calls['params'] = cmd, params
            on_progress('[ArcGEE] PROGRESS 10/20 tiles')
            return {'success': True, 'file': u'C:\\tmp\\x.tif', 'width': 10, 'height': 10,
                    'ground_res_m': 1.15, 'tiles': 20, 'seconds': 1.0, 'attribution': u'Esri'}

        def fake_send(action, timeout=120):
            calls.setdefault('ipc', []).append(action)
            if action['action'] == 'refresh_context':
                return {'success': True, 'context': {'bbox': [-56.10, -15.62, -56.09, -15.61]}}
            return {'success': True}

        self._patch_bridge('run_backend_cmd', fake_backend)
        self._patch_bridge('send_arcmap_command', fake_send)
        self._patch_bridge('find_python3_gdal', lambda: 'py3.exe')
        tmp = tempfile.mkdtemp()
        try:
            self.dlg._xyz_worker({'area': {'type': 'extent', 'layer': None, 'buffer': 0.0}, 'provider': 'esri',
                                  'label': u'Esri World Imagery', 'zoom': 17, 'compression': 'JPEG', 'crs': None,
                                  'out_dir': tmp})
        finally:
            shutil.rmtree(tmp)
        self.parent.pump()
        self.assertEqual(calls['cmd'], 'xyz_download')
        self.assertEqual(calls['params']['provider'], 'esri')
        load = [a for a in calls['ipc'] if a['action'] == 'load_layer'][0]
        self.assertEqual(load['rgb_bands'], [0, 1, 2])
        self.assertEqual(load['group'], sg.XYZ_GROUP)
        self.assertIn(u'Concluído', self.dlg.lbl_xyz_status.cget('text'))
        self.assertEqual(str(self.dlg.btn_xyz.cget('state')), 'normal')

    def test_dialog_is_xyz_only(self):
        self.assertFalse(hasattr(self.dlg, "tree"))
        self.assertIn(u"Google Earth", self.dlg.top.title())


if __name__ == '__main__':
    unittest.main()
