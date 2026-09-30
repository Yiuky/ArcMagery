# -*- coding: utf-8 -*-
"""Esri Wayback na janela principal (arcmagery_wayback) e ajustes de desempenho da ponte
(threads de download, nucleos, estatisticas por amostragem e prazo de carga - P-01)."""
from __future__ import print_function

import time
import unittest

import _paths
import arcmagery_wayback as wayback
import gee_bridge
import gee_gui

CTX = {'bbox': [-56.10, -15.64, -56.02, -15.58], 'scale': 50000, 'vector_layers': [u'AOI_Cuiabá'],
       'raster_layers': [], 'groups_with_rasters': [], 'time': 1}

VERSIONS = [
    {'release_num': 26334, 'release_date': '2026-08-05', 'capture_date': '2024-05-05', 'sensor': 'GE01',
     'sensor_name': 'GeoEye-1', 'provider': 'Vantor', 'resolution_m': 0.46, 'zoom': 18},
    {'release_num': 26083, 'release_date': '2022-02-02', 'capture_date': '2020-06-29', 'sensor': 'WV03',
     'sensor_name': 'WorldView-3', 'provider': 'Maxar', 'resolution_m': 0.31, 'zoom': 17},
    {'release_num': 10, 'release_date': '2014-02-20', 'capture_date': None, 'sensor': None,
     'provider': None, 'resolution_m': None, 'zoom': 16},
]


class BridgePerformanceHelpersTest(unittest.TestCase):
    def test_threads_and_cores(self):
        self.assertTrue(8 <= gee_bridge.default_tile_threads() <= 48)
        self.assertEqual(gee_bridge.clamp_tile_threads(500), 64)          # nunca acima de 64
        self.assertEqual(gee_bridge.clamp_tile_threads(1), 4)
        self.assertEqual(gee_bridge.clamp_tile_threads('x'), gee_bridge.default_tile_threads())
        self.assertEqual(gee_bridge.tile_threads({'tile_threads': 32}), 32)
        cores = gee_bridge.default_cores()
        self.assertTrue(1 <= cores <= 16 and cores <= max(1, gee_bridge.system_cores() - 2))

    def test_stats_sampling_and_load_timeout(self):
        self.assertEqual(gee_bridge.stats_skip_factor(2000, 2000), 1)      # pequeno: todos os pixels
        self.assertEqual(gee_bridge.stats_skip_factor(47920, 29369), 8)    # raster do bug: ~22 Mpx lidos
        self.assertEqual(gee_bridge.stats_skip_factor(None, 10), 1)
        self.assertEqual(gee_bridge.load_timeout_seconds(), 120)
        self.assertGreater(gee_bridge.load_timeout_seconds(47920, 29369), 600)
        self.assertEqual(gee_bridge.load_timeout_seconds(10 ** 6, 10 ** 6), 1800)


class WaybackModuleTest(unittest.TestCase):
    def test_catalog(self):
        codes = [c for _l, c in wayback.WAYBACK_SENSOR_DISPLAY]
        self.assertEqual(codes[0], wayback.ALL)
        self.assertEqual(sorted(wayback.zoom_of(c) for c in codes[1:]), [15, 16, 17, 18, 19])
        self.assertTrue(wayback.is_wayback('EWB:18') and not wayback.is_wayback('GEH:18'))
        self.assertIn(u'EPSG:3857', wayback.WAYBACK_SENSOR_METADATA['EWB:18']['available_bands'])

    def test_zooms_match_backend(self):
        import ast, io, os
        src = os.path.join(os.path.dirname(os.path.abspath(wayback.__file__)), 'backend', 'run_gee.py')
        tree = ast.parse(io.open(src, 'rb').read())
        value = [ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                 and getattr(n.targets[0], 'id', None) == 'WAYBACK_ZOOMS'][0]
        self.assertEqual(list(value), wayback.ZOOMS)

    def test_rows(self):
        row = wayback.version_to_row(VERSIONS[1])
        self.assertEqual(row['id'], u'EsriWayback_20200629_r26083_z17')
        self.assertEqual((wayback.release_of_row_id(row['id']), wayback.zoom_of_row_id(row['id'])), (26083, 17))
        self.assertEqual(row['cloud_display'], u'versão 02/02/2022')
        self.assertEqual(row['mgrs'], u'WorldView-3 Maxar · 0,31 m')
        self.assertTrue(row['zoom_display'].startswith(u'17 (~'))
        unknown = wayback.version_to_row(VERSIONS[2])                     # sem data de captura
        self.assertEqual((unknown['date'], unknown['capture_known']), ('2014-02-20', False))

    def test_backend_calls(self):
        calls = []

        def fake(cmd, params, on_progress=None, python_exe=None):
            calls.append((cmd, params))
            if cmd == 'esri_versions':
                return {'success': True, 'versions': VERSIONS}
            return {'success': True, 'file': u'C:\\tmp\\w.tif', 'width': 10, 'height': 10}

        saved = gee_bridge.run_backend_cmd, gee_bridge.find_python3_gdal
        gee_bridge.run_backend_cmd, gee_bridge.find_python3_gdal = fake, lambda: 'py3.exe'
        try:
            res = wayback.search(wayback.ALL, '2018-01-01', None, bbox=CTX['bbox'])
            self.assertEqual(calls[0][1]['zooms'], 'all')
            self.assertEqual([r['date'] for r in res['images']], ['2024-05-05', '2020-06-29'])   # periodo
            dl = wayback.download(u'EsriWayback_20200629_r26083_z17', wayback.ALL, u'C:\\tmp\\w.tif', bbox=CTX['bbox'])
            cmd, p = calls[-1]
            self.assertEqual((cmd, p['wayback_release'], p['zoom'], p['provider']), ('xyz_download', 26083, 17, 'esri'))
            self.assertTrue(4 <= p['workers'] <= 64)
            self.assertEqual(dl['rgb_bands'], [0, 1, 2])
            wayback.thumbnail(wayback.version_to_row(VERSIONS[0]), CTX['bbox'], u'C:\\tmp\\t.png')
            self.assertEqual((calls[-1][0], calls[-1][1]['wayback_release']), ('wayback_thumb', 26334))
        finally:
            gee_bridge.run_backend_cmd, gee_bridge.find_python3_gdal = saved


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


class MainWindowWaybackFlowTest(unittest.TestCase):
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
        self.calls, self.ipc, self.boxes = [], [], []
        self.lp = _Patch()
        self.lp.set(gee_bridge, 'send_arcmap_command', self._fake_ipc)
        for kind in ('showinfo', 'showwarning', 'showerror'):
            self.lp.set(gee_gui.messagebox, kind, lambda *a, **k: self.boxes.append(a))

    def tearDown(self):
        self.lp.restore()
        self.win.var_source.set('gee')
        self.win.on_source_changed()

    def _fake_ipc(self, action, timeout=120):
        self.ipc.append((action, timeout))
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

    def test_source_switch_and_search(self):
        self.lp.set(gee_bridge, 'run_backend_cmd',
                    lambda cmd, params, **k: self.calls.append((cmd, params)) or {'success': True, 'versions': VERSIONS})
        w = self.win
        w.var_source.set('wayback')
        w.on_source_changed()
        self.assertEqual(w.get_selected_sensor_code(), wayback.ALL)
        self.assertIn(u'Wayback', w.btn_search.cget('text'))
        self.assertEqual(w.tree.heading('cloud', 'text'), u'Versão Wayback')
        self.assertIn('zoom', w.tree['displaycolumns'])
        self.assertTrue(w.txt_group_name.get().startswith('EWB_zooms_'))
        self.assertIn(u'Esri Wayback', w.lbl_sensor_detail.cget('text'))
        w.is_authenticated = False
        w.var_spatial_type.set('extent')
        w.on_search_clicked()
        self.assertTrue(self._pump(lambda: len(w.tree.get_children()) == 3), "tabela nao foi preenchida")
        self.assertEqual(self.calls[0][0], 'esri_versions')
        vals = [w.tree.item(i, 'values') for i in w.tree.get_children()]
        self.assertEqual(vals[0][:4], (u'2024-05-05', u'versão 05/08/2026', u'GeoEye-1 Vantor · 0,46 m',
                                       u'EsriWayback_20240505_r26334_z18'))
        w.tree.selection_set(w.tree.get_children()[1])
        w.on_image_selected()
        self.assertIn(u'Captura: 2020-06-29 | Zoom: 17', w.lbl_selected_info.cget('text'))

    def test_download_task_uses_scaled_load_timeout(self):
        def fake_backend(cmd, params, on_progress=None, python_exe=None):
            self.calls.append((cmd, params))
            return {'success': True, 'file': u'C:\\tmp\\w.tif', 'width': 47920, 'height': 29369}

        self.lp.set(gee_bridge, 'run_backend_cmd', fake_backend)
        task = {'image_ids': [u'EsriWayback_20200629_r26083_z17'], 'bbox': CTX['bbox'], 'replace_map': {},
                'auto_zoom': False, 'sensor': wayback.ALL, 'comp': 'rgb', 'custom_bands': None,
                'load_mode': 'rgb', 'pixel_size': None, 'group_name': u'EWB_t', 'geojson_file': None}
        self.win._execute_single_download_task(task)
        self.assertEqual(self.calls[0][1]['wayback_release'], 26083)
        load, timeout = [(a, t) for a, t in self.ipc if a.get('action') == 'load_layer'][0]
        self.assertEqual(load['rgb_bands'], [0, 1, 2])
        self.assertEqual(timeout, gee_bridge.load_timeout_seconds(47920, 29369))   # nao mais 120 s fixos


if __name__ == '__main__':
    unittest.main()
