# -*- coding: utf-8 -*-
"""CBERS / Amazonia-1 integrado a janela principal: modulo arcmagery_inpe e fluxo completo
(fonte -> busca -> tabela -> download -> load_layer) na GEEPluginWindow real, com a ponte simulada."""
from __future__ import print_function

import time
import unittest

import _paths
import arcmagery_inpe as inpe
import gee_bridge
import gee_gui

CTX = {'bbox': [-56.11, -15.62, -56.08, -15.59], 'scale': 50000, 'vector_layers': [u'AOI_Cuiabá'],
       'raster_layers': [], 'groups_with_rasters': [], 'time': 1}

ITEMS = [
    {'id': 'CBERS_4A_WPM_20251125_217_133_L4', 'collection': 'CB4A-WPM-L4-DN-1', 'date': '2025-11-25',
     'cloud_cover': None, 'coverage_pct': 100.0, 'path_row': '217/133', 'thumbnail': 'http://x/t.png'},
    {'id': 'CBERS_4A_WPM_20251025_217_133_L4', 'collection': 'CB4A-WPM-L4-DN-1', 'date': '2025-10-25',
     'cloud_cover': 12.34, 'coverage_pct': 62.0, 'path_row': '217/133', 'thumbnail': None},
]


class InpeModuleTest(unittest.TestCase):
    def test_catalog_is_consistent_with_backend(self):
        codes = [c for _l, c in inpe.INPE_SENSOR_DISPLAY]
        self.assertEqual(len(codes), 12)
        for code in codes:
            self.assertTrue(inpe.is_inpe(code))
            meta = inpe.INPE_SENSOR_METADATA[code]
            self.assertTrue(meta['native_res'] > 0 and meta['period_display'])
            self.assertTrue(inpe.composition_items(code))
        self.assertFalse(inpe.is_inpe('S2'))
        self.assertEqual(inpe.collection_of('INPE:CB4-MUX-L4-SR-1'), 'CB4-MUX-L4-SR-1')

    def test_products_per_collection(self):
        self.assertEqual(inpe.modes_for('INPE:CB4-PAN5M-L4-DN-1'), ['pan'])
        self.assertEqual(inpe.modes_for('INPE:CB4A-WPM-PCA-FUSED-1'), ['fused'])
        self.assertIn('pan', inpe.modes_for('INPE:CB4A-WPM-L4-DN-1'))
        self.assertTrue(inpe.composition_items('INPE:CB4-MUX-L4-SR-1')[0].startswith(u'rgb - '))

    def test_row_mapping_and_cloud_format(self):
        row = inpe.item_to_row(ITEMS[0])
        self.assertEqual(row['source'], 'INPE')
        self.assertEqual(row['mgrs'], u'217/133 · 100% da AOI')
        self.assertEqual(inpe.format_cloud(row['cloud_pct']), u'n/d')
        self.assertEqual(inpe.format_cloud(12.34), u'12.3%')
        self.assertEqual(inpe.format_cloud('45'), u'45.0%')


class _Patch(object):
    def __init__(self):
        self.saved = []

    def set(self, obj, name, value):
        self.saved.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def restore(self):
        for obj, name, value in reversed(self.saved):
            setattr(obj, name, value)
        self.saved = []


class MainWindowInpeFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = _Patch()
        cls.p.set(gee_bridge, 'read_arcmap_context', lambda: dict(CTX))
        cls.p.set(gee_bridge, 'load_plugin_settings', lambda: {})
        cls.p.set(gee_bridge, 'save_plugin_settings', lambda s: True)
        cls.p.set(gee_bridge, 'find_python3_gdal', lambda: 'py3-gdal.exe')
        cls.win = gee_gui.GEEPluginWindow()
        cls.win.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.win._alive = False
        cls.win.root.destroy()
        cls.p.restore()

    def setUp(self):
        self.calls = []
        self.ipc = []
        self.lp = _Patch()
        self.lp.set(gee_bridge, 'send_arcmap_command', self._fake_ipc)

    def tearDown(self):
        self.lp.restore()
        self.win.var_source.set('gee')
        self.win.on_source_changed()

    def _fake_ipc(self, action, timeout=120):
        self.ipc.append(action)
        if action.get('action') == 'refresh_context':
            return {'success': True, 'context': dict(CTX)}
        return {'success': True}

    def _pump(self, until, timeout=10.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.win._process_queue()
            if until():
                return True
            time.sleep(0.02)
        return False

    def _switch_to_inpe(self, index=0):
        self.win.var_source.set('inpe')
        self.win.on_source_changed()
        self.win.cbo_sensor.current(index)
        self.win.on_sensor_changed()

    def test_source_switch_adapts_the_window(self):
        self._switch_to_inpe()
        w = self.win
        self.assertEqual(tuple(w.cbo_sensor['values']), tuple(l for l, _c in inpe.INPE_SENSOR_DISPLAY))
        self.assertTrue(w.get_selected_sensor_code().startswith('INPE:'))
        self.assertTrue(w.var_comp.get().startswith(u'rgb - '))
        self.assertIn(u'INPE', w.btn_search.cget('text'))
        self.assertEqual(str(w.txt_custom_bands.cget('state')), 'disabled')
        self.assertEqual(w.var_pixel_size.get(), '8')
        self.assertTrue(w.txt_group_name.get().startswith('INPE_CB4A-WPM-L4-DN-1_rgb_'))
        self.assertIn(u'STAC INPE', w.lbl_sensor_detail.cget('text'))
        w.var_source.set('gee')
        w.on_source_changed()
        self.assertEqual(w.get_selected_sensor_code(), 'S2')
        self.assertIn(u'GEE', w.btn_search.cget('text'))
        self.assertEqual(str(w.txt_custom_bands.cget('state')), 'normal')

    def test_search_fills_main_table_without_gee_auth(self):
        def fake_backend(cmd, params, on_progress=None, python_exe=None):
            self.calls.append((cmd, params, python_exe))
            return {'success': True, 'items': ITEMS}

        self.lp.set(gee_bridge, 'run_backend_cmd', fake_backend)
        self.lp.set(gee_gui.messagebox, 'showinfo', lambda *a, **k: None)
        self._switch_to_inpe()
        self.win.is_authenticated = False            # o INPE nao depende do login no GEE
        self.win.var_spatial_type.set('extent')
        self.win.on_search_clicked()
        self.assertTrue(self._pump(lambda: len(self.win.tree.get_children()) == 2), "tabela nao foi preenchida")
        cmd, params, py = self.calls[0]
        self.assertEqual((cmd, params['collections'], py), ('stac_search', 'CB4A-WPM-L4-DN-1', 'py3-gdal.exe'))
        self.assertIn('bbox', params)
        rows = [self.win.tree.item(i, 'values') for i in self.win.tree.get_children()]
        self.assertEqual(rows[0][1], u'n/d')
        self.assertEqual(rows[1][1], u'12.3%')
        self.assertIn(u'% da AOI', rows[0][2])
        self.win.tree.selection_set(self.win.tree.get_children()[0])
        self.win.on_image_selected()
        self.assertIn(u'Órbita/Ponto', self.win.lbl_selected_info.cget('text'))
        self.assertEqual(str(self.win.btn_thumb.cget('state')), 'normal')

    def test_download_task_loads_with_backend_rgb_bands(self):
        def fake_backend(cmd, params, on_progress=None, python_exe=None):
            self.calls.append((cmd, params))
            if on_progress:
                on_progress('[ArcGEE] PROGRESS 50/100')
            return {'success': True, 'file': u'C:\\tmp\\cena.tif', 'rgb_bands': [2, 1, 0]}

        self.lp.set(gee_bridge, 'run_backend_cmd', fake_backend)
        task = {'image_ids': ['CBERS_4_MUX_20251125_166_118_L4'], 'bbox': CTX['bbox'], 'replace_map': {},
                'auto_zoom': True, 'sensor': 'INPE:CB4-MUX-L4-SR-1', 'comp': 'multi', 'custom_bands': None,
                'load_mode': 'multiband', 'pixel_size': 20.0, 'group_name': u'INPE_teste', 'geojson_file': None}
        self.win._execute_single_download_task(task)
        cmd, params = self.calls[0]
        self.assertEqual((cmd, params['collection'], params['mode']), ('stac_download', 'CB4-MUX-L4-SR-1', 'multi'))
        load = [a for a in self.ipc if a.get('action') == 'load_layer'][0]
        self.assertEqual(load['rgb_bands'], [2, 1, 0])
        self.assertEqual(load['group'], u'INPE_teste')

    def test_gee_download_path_is_unchanged(self):
        got = {}

        def fake_download_image(**kw):
            got.update(kw)
            return {'success': True, 'file': u'C:\\tmp\\s2.tif'}

        self.lp.set(gee_bridge, 'download_image', fake_download_image)
        task = {'image_ids': ['COPERNICUS/S2_SR_HARMONIZED/X'], 'bbox': CTX['bbox'], 'replace_map': {},
                'auto_zoom': False, 'sensor': 'S2', 'comp': '432', 'custom_bands': None, 'load_mode': 'rgb',
                'pixel_size': 10.0, 'group_name': None, 'geojson_file': None}
        self.win._execute_single_download_task(task)
        self.assertEqual((got['sensor'], got['comp_code'], got['scale']), ('S2', '432', 10.0))
        load = [a for a in self.ipc if a.get('action') == 'load_layer'][0]
        self.assertIsNone(load['rgb_bands'])


if __name__ == '__main__':
    unittest.main()
