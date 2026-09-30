# -*- coding: utf-8 -*-
"""Google Earth historico na janela principal: modulo arcmagery_gehist e fluxo completo
(fonte -> listar datas -> tabela -> fila -> load_layer) na GEEPluginWindow real, com a ponte simulada."""
from __future__ import print_function

import time
import unittest

import _paths
import arcmagery_gehist as gehist
import gee_bridge
import gee_gui

CTX = {'bbox': [-56.10, -15.64, -56.02, -15.58], 'scale': 50000, 'vector_layers': [u'AOI_Cuiabá'],
       'raster_layers': [], 'groups_with_rasters': [], 'time': 1}

DATES = [
    {'date': '2025-02-23', 'coverage_pct': 100.0, 'provider': u'Maxar Technologies'},
    {'date': '2022-06-28', 'coverage_pct': 57.1, 'provider': u'Maxar Technologies'},
    {'date': '2004-05-21', 'coverage_pct': 100.0, 'provider': u'Provedor 48'},
]


class GehistModuleTest(unittest.TestCase):
    def test_catalog(self):
        codes = [c for _l, c in gehist.GEHIST_SENSOR_DISPLAY]
        self.assertEqual(codes[0], gehist.ALL)                       # todos os zooms e o padrao
        self.assertIsNone(gehist.zoom_of(gehist.ALL))
        self.assertEqual(sorted(gehist.zoom_of(c) for c in codes[1:]), [15, 16, 17, 18, 19, 20])
        self.assertTrue(all(gehist.is_gehist(c) for c in codes))
        self.assertFalse(gehist.is_gehist('INPE:CB4-MUX-L4-SR-1') or gehist.is_gehist('S2'))
        self.assertIn(u'0,60 m', dict((c, l) for l, c in gehist.GEHIST_SENSOR_DISPLAY)['GEH:18'])
        self.assertIn(u'EPSG:4326', gehist.GEHIST_SENSOR_METADATA['GEH:18']['available_bands'])

    def test_limit_matches_backend(self):
        # o backend e Python 3 (ex.: 'nonlocal'): ler a constante sem interpretar o arquivo no Py2
        import io, os, re
        src = os.path.join(os.path.dirname(os.path.abspath(gehist.__file__)), 'backend', 'gehist_core.py')
        text = io.open(src, encoding='utf-8').read()
        value = int(re.search(r'^MAX_TILES = (\d+)', text, re.M).group(1))
        zooms = re.search(r'^ALL_ZOOMS = \(([^)]*)\)', text, re.M).group(1)
        self.assertEqual([int(z) for z in zooms.split(',') if z.strip()], gehist.ALL_ZOOMS)
        self.assertEqual(value, gehist.MAX_TILES)
        self.assertEqual(value, 100000)

    def test_rows_and_period(self):
        row = gehist.date_to_row(DATES[1], 18)
        self.assertEqual(row['id'], u'GoogleEarth_20220628_z18')
        self.assertEqual((row['cloud_display'], row['mgrs'], row['source']), (u'57% da área', u'Maxar Technologies', 'GEHIST'))
        self.assertEqual(gehist.date_to_row(DATES[0], 18)['cloud_display'], u'100% da área')
        self.assertEqual(gehist._date_of_row_id(row['id']), u'2022-06-28')
        self.assertTrue(gehist.in_period('2022-06-28', '2020-01-01', '2022-12-31'))
        self.assertFalse(gehist.in_period('2004-05-21', '2020-01-01', None))

    def test_limit_and_estimate(self):
        self.assertIsNone(gehist.check_limit(CTX['bbox'], 18))
        self.assertIn(u'limite 100000', gehist.check_limit([-57, -17, -55, -15], 18))
        self.assertIn(u'2596 tiles no zoom 18', gehist.estimate_text(CTX['bbox'], 18))

    def test_backend_calls(self):
        calls = []

        def fake(cmd, params, on_progress=None, python_exe=None):
            calls.append((cmd, params))
            if on_progress:
                on_progress('[ArcGEE] PROGRESS 50/100 tiles')
            if cmd == 'gehist_dates':
                return {'success': True, 'dates': DATES}
            return {'success': True, 'file': u'C:\\tmp\\h.tif', 'coverage_pct': 57.1}

        saved = gee_bridge.run_backend_cmd, gee_bridge.find_python3_gdal
        gee_bridge.run_backend_cmd, gee_bridge.find_python3_gdal = fake, lambda: 'py3.exe'
        try:
            prog = []
            res = gehist.search('GEH:18', '2020-01-01', '2026-12-31', bbox=CTX['bbox'],
                                on_progress=lambda m, p: prog.append((m, p)))
            self.assertEqual([r['date'] for r in res['images']], ['2025-02-23', '2022-06-28'])
            self.assertEqual(res['total_dates'], 3)
            self.assertEqual(prog[0][1], 50.0)
            dl = gehist.download(u'GoogleEarth_20220628_z18', 'GEH:18', u'C:\\tmp\\h.tif', bbox=CTX['bbox'])
            self.assertEqual(calls[-1][0], 'gehist_download')
            self.assertEqual((calls[-1][1]['date'], calls[-1][1]['zoom']), (u'2022-06-28', 18))
            gehist.download(u'GoogleEarth_20220628_z20', gehist.ALL, u'C:\tmp\h.tif', bbox=CTX['bbox'])
            self.assertEqual(calls[-1][1]['zoom'], 20)                  # zoom da linha
            self.assertEqual((dl['rgb_bands'], dl['valid_pct']), ([0, 1, 2], 57.1))
            self.assertFalse(gehist.download(u'lixo', 'GEH:18', u'x.tif')['success'])
            gehist.thumbnail(gehist.date_to_row(DATES[0], 18), CTX['bbox'], u'C:\\tmp\\t.png')
            self.assertEqual((calls[-1][0], calls[-1][1]['date']), ('gehist_thumb', '2025-02-23'))
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


class MainWindowGehistFlowTest(unittest.TestCase):
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

    def _switch(self, code='GEH:18'):
        self.win.var_source.set('gehist')
        self.win.on_source_changed()
        self.win.cbo_sensor.current([c for _l, c in gehist.GEHIST_SENSOR_DISPLAY].index(code))
        self.win.on_sensor_changed()

    def test_source_switch_adapts_the_window(self):
        w = self.win
        w.var_source.set('gehist')
        w.on_source_changed()
        self.assertEqual(w.get_selected_sensor_code(), gehist.ALL)          # padrao: todos os zooms
        self.assertTrue(w.txt_group_name.get().startswith('GEH_zooms_'))
        self.assertIn('zoom', w.tree['displaycolumns'])
        self._switch()
        self.assertEqual(w.get_selected_sensor_code(), 'GEH:18')
        self.assertTrue(w.var_comp.get().startswith(u'rgb - '))
        self.assertIn(u'Google Earth', w.btn_search.cget('text'))
        self.assertEqual(w.tree.heading('cloud', 'text'), u'Cobertura')
        self.assertEqual(w.tree.heading('tile', 'text'), u'Provedor / Satélite')
        self.assertEqual(str(w.txt_custom_bands.cget('state')), 'disabled')
        self.assertEqual(w.txt_start_date.get(), u'01/01/1985')
        self.assertTrue(w.txt_group_name.get().startswith('GEH_z18_'))
        self.assertIn(u'Google Earth', w.lbl_sensor_detail.cget('text'))
        w.var_source.set('gee')
        w.on_source_changed()
        self.assertEqual(w.get_selected_sensor_code(), 'S2')
        self.assertEqual(w.tree.heading('cloud', 'text'), u'Nuvens (%)')
        self.assertNotIn('zoom', w.tree['displaycolumns'])
        self.assertEqual(str(w.txt_custom_bands.cget('state')), 'normal')

    def test_search_lists_dates_without_gee_auth(self):
        def fake_backend(cmd, params, on_progress=None, python_exe=None):
            self.calls.append((cmd, params, python_exe))
            return {'success': True, 'dates': DATES}

        self.lp.set(gee_bridge, 'run_backend_cmd', fake_backend)
        self._switch()
        self.win.is_authenticated = False
        self.win.var_spatial_type.set('extent')
        self.win.on_search_clicked()
        self.assertTrue(self._pump(lambda: len(self.win.tree.get_children()) == 3), "tabela nao foi preenchida")
        cmd, params, py = self.calls[0]
        self.assertEqual((cmd, params['zoom'], py), ('gehist_dates', 18, 'py3-gdal.exe'))
        rows = [self.win.tree.item(i, 'values') for i in self.win.tree.get_children()]
        self.assertEqual(rows[1][:4], (u'2022-06-28', u'57% da área', u'Maxar Technologies', u'GoogleEarth_20220628_z18'))
        self.win.tree.selection_set(self.win.tree.get_children()[1])
        self.win.on_image_selected()
        info = self.win.lbl_selected_info.cget('text')
        self.assertIn(u'Cobertura: 57% da área', info)
        self.assertIn(u'tiles no zoom 18', info)
        self.assertEqual(str(self.win.btn_thumb.cget('state')), 'normal')

    def test_all_zooms_search_puts_zoom_in_a_column(self):
        rows = [dict(DATES[0], zoom=20, estimated=True, coverage_pct=26.7), dict(DATES[0], zoom=18),
                dict(DATES[1], zoom=15)]

        def fake_backend(cmd, params, on_progress=None, python_exe=None):
            self.calls.append((cmd, params))
            return {'success': True, 'dates': rows}

        self.lp.set(gee_bridge, 'run_backend_cmd', fake_backend)
        self._switch(gehist.ALL)
        self.win.var_spatial_type.set('extent')
        self.win.on_search_clicked()
        self.assertTrue(self._pump(lambda: len(self.win.tree.get_children()) == 3), "tabela nao foi preenchida")
        self.assertEqual(self.calls[0][1]['zooms'], 'all')
        self.assertTrue(4 <= self.calls[0][1]['workers'] <= 64)
        vals = [self.win.tree.item(i, 'values') for i in self.win.tree.get_children()]
        self.assertEqual(vals[0][5], u'20 (~0,15 m)')                     # coluna Zoom
        self.assertEqual(vals[0][1], u'~27% da área')                      # estimada
        self.assertEqual(vals[1][3], u'GoogleEarth_20250223_z18')
        self.assertEqual(self.win.var_pixel_size.get(), u'por zoom')

    def test_search_refuses_area_over_the_limit(self):
        self.lp.set(gee_bridge, 'run_backend_cmd', lambda *a, **k: self.fail("nao deveria consultar o backend"))
        self._switch()
        self.win.arcmap_context = dict(CTX, bbox=[-57, -17, -55, -15])
        self.lp.set(self.win, 'sync_arcmap_context', lambda: None)
        self.win.var_spatial_type.set('extent')
        self.win.on_search_clicked()
        self.assertTrue(self.boxes and u'limite 100000' in self.boxes[-1][1])
        self.win.arcmap_context = dict(CTX)

    def test_download_task_loads_rgb_and_warns_partial_coverage(self):
        def fake_backend(cmd, params, on_progress=None, python_exe=None):
            self.calls.append((cmd, params))
            if on_progress:
                on_progress('[ArcGEE] PROGRESS 10/20 tiles')
            return {'success': True, 'file': u'C:\\tmp\\h.tif', 'coverage_pct': 42.0}

        self.lp.set(gee_bridge, 'run_backend_cmd', fake_backend)
        self._switch()
        task = {'image_ids': [u'GoogleEarth_20220628_z18'], 'bbox': CTX['bbox'], 'replace_map': {},
                'auto_zoom': True, 'sensor': 'GEH:18', 'comp': 'rgb', 'custom_bands': None,
                'load_mode': 'rgb', 'pixel_size': None, 'group_name': u'GEH_teste', 'geojson_file': None}
        self.win._execute_single_download_task(task)
        cmd, params = self.calls[0]
        self.assertEqual((cmd, params['date'], params['zoom']), ('gehist_download', u'2022-06-28', 18))
        load = [a for a in self.ipc if a.get('action') == 'load_layer'][0]
        self.assertEqual((load['rgb_bands'], load['group'], load['name']),
                         ([0, 1, 2], u'GEH_teste', u'GoogleEarth_20220628_z18_rgb'))
        self.assertTrue(self._pump(lambda: any(u'42.0%' in b[1] for b in self.boxes)), "sem aviso de cobertura")

    def test_enqueue_refuses_area_over_the_limit(self):
        self._switch(gehist.ALL)                          # o zoom vem da linha escolhida
        self.win._enqueue_download_task([u'GoogleEarth_20220628_z18'], bbox=[-57, -17, -55, -15])
        self.assertTrue(self.boxes and u'limite 100000' in self.boxes[-1][1])
        self.assertNotIn(u'GoogleEarth_20220628_z18', self.win.queued_ids)


if __name__ == '__main__':
    unittest.main()
