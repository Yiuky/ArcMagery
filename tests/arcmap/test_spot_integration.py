# -*- coding: utf-8 -*-
"""SPOT 1-5 (CNES / GEODES) na janela principal, chave do GEODES e tela de abertura: modulos
arcmagery_spot / arcmagery_startup e o fluxo completo (fonte -> busca -> tabela -> download ->
load_layer) na GEEPluginWindow real, com a ponte e o backend simulados."""
from __future__ import print_function

import os
import shutil
import tempfile
import time
import unittest

import _paths  # noqa: F401
import arcmagery_spot as spot
import arcmagery_startup as startup
import gee_bridge
import gee_gui

CTX = {'bbox': [-56.12, -15.62, -56.06, -15.57], 'scale': 50000, 'vector_layers': [], 'raster_layers': [],
       'groups_with_rasters': [], 'time': 1}

ITEMS = [
    {'id': '005-009_S5_693-381-0_2014-10-11-13-24-06_HRG-1_J_DT_44', 'date': '2014-10-11', 'platform': 'SPOT5',
     'mode': 'J', 'mode_label': u'HI 4 bandas', 'is_pan': False, 'res_m': 10.6, 'cloud_cover': 0.0,
     'incidence_deg': 26.9, 'coverage_pct': 100.0, 'zip_size': 95000000, 'thumbnail': 'https://x/q.jpg'},
    {'id': '010-011_S2_693-381-0_2008-05-08-13-58-21_HRV-2_X_DT_GU', 'date': '2008-05-08', 'platform': 'SPOT2',
     'mode': 'X', 'mode_label': u'XS 3 bandas', 'is_pan': False, 'res_m': 20.0, 'cloud_cover': 1.0,
     'incidence_deg': 5.7, 'coverage_pct': 51.4, 'zip_size': 15000000, 'thumbnail': None},
]
KEY = 'AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcdefghij'


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


def _destroy(root):
    """Cancela os 'after' pendentes antes de destruir: senao disparam (com erro Tcl) no proximo update()."""
    try:
        for aid in root.tk.splitlist(root.tk.call('after', 'info')):
            root.after_cancel(aid)
    except Exception:
        pass
    root.destroy()


class _TempAppData(object):
    """%APPDATA% temporario: a chave de teste nunca toca a do usuario."""

    def __enter__(self):
        self.old = os.environ.get('APPDATA')
        self.old_env_key = os.environ.pop(spot.KEY_ENV, None)
        self.dir = tempfile.mkdtemp()
        os.environ['APPDATA'] = self.dir
        return self

    def __exit__(self, *a):
        if self.old is None:
            os.environ.pop('APPDATA', None)
        else:
            os.environ['APPDATA'] = self.old
        if self.old_env_key is not None:
            os.environ[spot.KEY_ENV] = self.old_env_key
        shutil.rmtree(self.dir, ignore_errors=True)


class SpotModuleTest(unittest.TestCase):
    def test_catalog(self):
        codes = [c for _l, c in spot.SPOT_SENSOR_DISPLAY]
        self.assertEqual(len(codes), len(set(codes)))
        for code in codes:
            self.assertTrue(spot.is_spot(code))
            self.assertTrue(spot.SPOT_SENSOR_METADATA[code]['period_display'])
            self.assertTrue(spot.composition_items(code))
        self.assertFalse(spot.is_spot('INPE:CB4-MUX-L4-SR-1'))
        self.assertEqual(spot.modes_for('SPOT:5-PAN'), ['pan'])
        self.assertEqual(spot.modes_for('SPOT:MS'), ['false', 'swir', 'multi'])
        self.assertTrue(spot.composition_items('SPOT:MS')[0].startswith(u'false - '))

    def test_modes_match_backend(self):
        """Composicoes da GUI (Py2) e do backend (Py3) devem bater."""
        import ast
        import io
        src = os.path.join(_paths.BACKEND, 'spot_core.py')
        tree = ast.parse(io.open(src, 'rb').read())
        backend = None
        for node in tree.body:
            if isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', None) == 'MODES':
                backend = set(ast.literal_eval(k) for k in node.value.keys)
        self.assertEqual(set(m for m, _l in spot.PRODUCTS), backend)

    def test_row_mapping(self):
        row = spot.item_to_row(ITEMS[0])
        self.assertEqual(row['source'], 'SPOT')
        self.assertEqual(row['mgrs'], u'SPOT5 · 11 m · HI 4 bandas · 100%')
        self.assertEqual(row['cloud_display'], u'0%')
        info = spot.row_info(row)
        self.assertIn(u'2014-10-11', info)
        self.assertIn(u'95 MB', info)
        self.assertIn(u'+27°', info)

    def test_key_storage_roundtrip(self):
        with _TempAppData() as tmp:
            self.assertIsNone(spot.load_api_key())
            self.assertTrue(spot.save_api_key(u'  %s  ' % KEY))
            self.assertEqual(spot.load_api_key(), KEY)
            self.assertTrue(spot.key_file().startswith(tmp.dir))
            self.assertEqual(spot.mask_key(KEY), u'AbCd…ghij')
            os.environ[spot.KEY_ENV] = 'x' * 30
            self.assertEqual(spot.load_api_key(), KEY)     # a chave salva tem prioridade
            spot.save_api_key(u'')
            self.assertEqual(spot.load_api_key(), 'x' * 30)
            os.environ.pop(spot.KEY_ENV)
        self.assertTrue(spot.looks_like_key(KEY))
        self.assertFalse(spot.looks_like_key(u'curta'))
        self.assertFalse(spot.looks_like_key(u'com espaco no meio da chave 123456'))

    def test_download_without_key_does_not_call_backend(self):
        p = _Patch()
        p.set(gee_bridge, 'run_backend_cmd', lambda *a, **k: self.fail('backend chamado sem chave'))
        try:
            with _TempAppData():
                resp = spot.download('X', 'SPOT:MS', 'false', 'C:\\tmp\\x.tif', bbox=CTX['bbox'])
        finally:
            p.restore()
        self.assertFalse(resp['success'])
        self.assertTrue(resp['needs_key'])

    def test_alignment_text(self):
        self.assertIn(u'477 m', spot.alignment_text({'alignment': {'applied': True, 'shift_m': 477.1,
                                                                   'residual_m': 2.5}}))
        self.assertIn(u'SEM alinhamento', spot.alignment_text({'alignment': {'applied': False, 'reason': u'nuvens'}}))


class StartupRulesTest(unittest.TestCase):
    OK_RESP = {'success': True, 'python': '3.12.13', 'gdal': '3.12.4', 'numpy': '2.4.4', 'ee': '1.7.46',
               'net': {'geodes': {'ok': True}, 'inpe': {'ok': True}, 'esri': {'ok': True}},
               'geodes_key': {'ok': True, 'max_quota': 50, 'remaining_quota': 47}}

    def test_all_good(self):
        out = startup.evaluate_selfcheck(self.OK_RESP, True)
        self.assertEqual(set(v[0] for v in out.values()), set([startup.OK]))
        self.assertIn(u'47 de 50', out['geodes'][1])

    def test_missing_ee_is_an_error_with_install_hint(self):
        out = startup.evaluate_selfcheck(dict(self.OK_RESP, ee=None), True)
        self.assertEqual(out['ee'][0], startup.FAIL)
        self.assertIn(u'Instalar componentes', out['ee'][1])
        self.assertEqual(startup.evaluate_selfcheck(self.OK_RESP, True)['ee'], (startup.OK, u'earthengine-api 1.7.46'))

    def test_gee_row_points_to_components_when_ee_is_missing(self):
        state, text = startup.evaluate_gee({'success': False, 'ee_missing': True, 'message': u'x' * 400})
        self.assertEqual(state, startup.WARN)
        self.assertIn(u'linha acima', text)
        self.assertLess(len(text), 80)

    def test_probe_activates_pylibs(self):
        code = gee_bridge.probe_code(['ee'])
        self.assertIn('pylibs.activate()', code)
        self.assertLess(code.index('import qgis_env'), code.index('import pylibs'))  # B-09: QGIS 3.26
        self.assertIn('import ee', code)
        compile(code, '<probe>', 'exec')

    def test_missing_key_is_only_info(self):
        out = startup.evaluate_selfcheck(dict(self.OK_RESP, geodes_key=None), False)
        self.assertEqual(out['geodes'][0], startup.INFO)
        self.assertEqual(startup.overall({'a': startup.OK, 'b': startup.INFO}), startup.OK)

    def test_rejected_key_and_partial_network(self):
        resp = dict(self.OK_RESP, geodes_key={'ok': False, 'error': u'GEODES recusou a chave de API (HTTP 401)'},
                    net={'geodes': {'ok': True}, 'inpe': {'ok': False}, 'esri': {'ok': True}})
        out = startup.evaluate_selfcheck(resp, True)
        self.assertEqual(out['geodes'][0], startup.FAIL)
        self.assertEqual(out['net'][0], startup.WARN)
        self.assertIn(u'INPE', out['net'][1])

    def test_backend_down_and_no_gdal(self):
        out = startup.evaluate_selfcheck({'success': False, 'message': u'python3 ausente'}, True)
        self.assertEqual(out['libs'][0], startup.FAIL)
        out = startup.evaluate_selfcheck(dict(self.OK_RESP, gdal=None), True)
        self.assertEqual(out['libs'][0], startup.WARN)
        all_down = dict(self.OK_RESP, net=dict((k, {'ok': False}) for k in ('geodes', 'inpe', 'esri')))
        self.assertEqual(startup.evaluate_selfcheck(all_down, True)['net'][0], startup.FAIL)

    def test_gee_arcmap_and_overall(self):
        self.assertEqual(startup.evaluate_gee({'success': True, 'message': u'ok'})[0], startup.OK)
        self.assertEqual(startup.evaluate_gee({'success': False})[0], startup.WARN)
        state, text = startup.evaluate_arcmap({'scale': 50000})
        self.assertEqual(state, startup.OK)
        self.assertIn(u'50.000', text)
        self.assertEqual(startup.evaluate_arcmap(None)[0], startup.WARN)
        self.assertEqual(startup.overall({'a': startup.OK, 'b': startup.WARN}), startup.WARN)
        self.assertEqual(startup.overall({'a': startup.FAIL, 'b': startup.WARN}), startup.FAIL)

    def test_describe_python(self):
        self.assertIn(u'venv do ArcMagery', startup.describe_python(
            r'C:\Users\x\AppData\Local\ArcMagery\venv\Scripts\python.exe'))
        self.assertEqual(startup.describe_python(r'C:\Program Files\QGIS 3.44.10\apps\Python312\python.exe'),
                         u'Python do QGIS 3.44.10')

    def test_run_checks_reports_every_item(self):
        got = {}

        def report(key, state, text, extra=None):
            got[key] = state
        threads = startup.run_checks(report, read_context=lambda: dict(CTX),
                                     check_gee=lambda: {'success': True, 'message': u'ok'},
                                     selfcheck=lambda key: self.OK_RESP,
                                     find_python=lambda: r'C:\venv\python.exe', api_key=KEY)
        for t in threads:
            t.join(10)
        self.assertEqual(sorted(got), sorted(k for k, _l in startup.CHECKS))
        self.assertEqual(set(got.values()), set([startup.OK]))


SPLASH_SCRIPT = r'''
import sys, time
sys.path.insert(0, sys.argv[1])
import Tkinter as tk
import arcmagery_startup as startup
OK_RESP = {'success': True, 'python': '3.12', 'gdal': '3.12', 'numpy': '2.4', 'ee': '1.7.46',
           'net': {'geodes': {'ok': True}, 'inpe': {'ok': True}, 'esri': {'ok': True}},
           'geodes_key': {'ok': True, 'max_quota': 50, 'remaining_quota': 47}}
root = tk.Tk(); root.withdraw(); done = []
splash = startup.StartupSplash(root, '9.9.9')
splash.start(done.append, read_context=lambda: {'scale': 50000},
             check_gee=lambda: {'success': True, 'message': u'Conectado'},
             selfcheck=lambda key: OK_RESP, find_python=lambda: r'C:\venv\python.exe', api_key='K' * 30)
deadline = time.time() + 15
while not done and time.time() < deadline:
    root.update(); time.sleep(0.02)
print('DONE=%d GEE=%s GEODES=%s' % (len(done), done and done[0].gee_resp.get('success'),
                                     done and done[0].states.get('geodes')))
'''


INSTALL_SCRIPT = r'''
import sys, time
sys.path.insert(0, sys.argv[1])
import Tkinter as tk
import arcmagery_startup as startup
MISSING = {'success': True, 'python': '3.12', 'gdal': '3.12', 'numpy': '2.4', 'ee': None,
           'net': {'geodes': {'ok': True}, 'inpe': {'ok': True}, 'esri': {'ok': True}},
           'geodes_key': {'ok': True, 'max_quota': 50, 'remaining_quota': 47}}
installed = []
def installer(on_progress=None):
    on_progress('[ArcGEE] Baixando componentes do Earth Engine: 1/26 x.whl')
    installed.append(1)
    return {'success': True, 'ee': '1.7.46', 'dir': 'C:/pylibs/py312'}
gee_ok = lambda: ({'success': True, 'message': u'Conectado'} if installed else {'success': False, 'message': u'sem ee'})
root = tk.Tk(); root.withdraw(); done = []
splash = startup.StartupSplash(root, '9.9.9')
splash.start(done.append, read_context=lambda: {'scale': 50000}, check_gee=gee_ok,
             selfcheck=lambda key: MISSING, find_python=lambda: r'C:env\python.exe', api_key='K' * 30,
             installer=installer)
deadline = time.time() + 15
while splash.states.get('ee') != 'fail' and time.time() < deadline:
    root.update(); time.sleep(0.02)
before = (splash.states.get('ee'), bool(splash.btn_ee.winfo_manager()))
splash._install_ee()
while (splash.states.get('ee') != 'ok' or splash.states.get('gee') != 'ok') and time.time() < deadline:
    root.update(); time.sleep(0.02)
print('BEFORE=%s,%s AFTER=%s,%s' % (before[0], before[1], splash.states.get('ee'), splash.states.get('gee')))
'''


DOCTOR_SCRIPT = r'''
import sys, time
sys.path.insert(0, sys.argv[1])
import Tkinter as tk
import arcmagery_startup as startup
MISSING = {'success': True, 'python': '3.9', 'gdal': '3.5', 'numpy': '1.20', 'ee': None,
           'net': {'geodes': {'ok': True}, 'inpe': {'ok': True}, 'esri': {'ok': True}}, 'geodes_key': None}
ran = []
def doctor():
    ran.append(1)
    return {'success': True, 'report': None, 'checks': [
        {'id': 'ee', 'status': 'fixed', 'detail': u'earthengine-api 1.6.15'},
        {'id': 'venv', 'status': 'fixed', 'detail': u'renomeado'}]}
root = tk.Tk(); root.withdraw(); done = []
splash = startup.StartupSplash(root, '9.9.9')
splash.start(done.append, read_context=lambda: {'scale': 4000},
             check_gee=lambda: {'success': False, 'ee_missing': True, 'message': u'ausentes ' * 40},
             selfcheck=lambda key: MISSING, find_python=lambda: r'C:\qgis\python.exe', api_key='', doctor=doctor)
deadline = time.time() + 15
while any(splash.states.get(k) not in startup.DONE for k, _ in startup.CHECKS) and time.time() < deadline:
    root.update(); time.sleep(0.02)
for _ in range(10):
    root.update(); time.sleep(0.02)
visible = bool(splash.btn_doctor.winfo_ismapped() and splash.btn_ee.winfo_ismapped() and splash.btn_go.winfo_ismapped())
fits = splash.top.winfo_height() >= splash.top.winfo_reqheight() - 2
splash._run_doctor(opener=lambda p: None)
while not getattr(splash, '_summary_locked', False) and time.time() < deadline:
    root.update(); time.sleep(0.02)
print('VISIBLE=%s FITS=%s RAN=%d EE=%s SUMMARY=%s' % (visible, fits, len(ran), splash.states.get('ee'),
      u'2 corrigido' in splash.lbl_summary.cget('text')))
'''


class SplashWindowTest(unittest.TestCase):
    """Processo proprio: o loop de eventos da splash nao dispara 'after' de janelas de outros testes."""

    def test_splash_runs_checks_and_closes(self):
        import subprocess
        env = dict(os.environ)
        env.pop('PYTHONPATH', None)
        p = subprocess.Popen([os.path.join(os.path.dirname(os.sys.executable), 'python.exe'), '-c', SPLASH_SCRIPT,
                              _paths.INSTALL], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        out, err = p.communicate()
        self.assertEqual(p.returncode, 0, err)
        self.assertIn('DONE=1 GEE=True GEODES=ok', out, u"a splash nao fechou sozinha com tudo OK: %r %r" % (out, err))

    def test_buttons_fit_and_doctor_button_fixes(self):
        import subprocess
        env = dict(os.environ)
        env.pop('PYTHONPATH', None)
        p = subprocess.Popen([os.path.join(os.path.dirname(os.sys.executable), 'python.exe'), '-c', DOCTOR_SCRIPT,
                              _paths.INSTALL], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        out, err = p.communicate()
        self.assertEqual(p.returncode, 0, err)
        self.assertIn('VISIBLE=True FITS=True RAN=1 EE=ok SUMMARY=True', out, (out, err))

    def test_install_button_installs_and_rechecks_gee(self):
        import subprocess
        env = dict(os.environ)
        env.pop('PYTHONPATH', None)
        p = subprocess.Popen([os.path.join(os.path.dirname(os.sys.executable), 'python.exe'), '-c', INSTALL_SCRIPT,
                              _paths.INSTALL], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        out, err = p.communicate()
        self.assertEqual(p.returncode, 0, err)
        self.assertIn('BEFORE=fail,True AFTER=ok,ok', out, (out, err))


class MainWindowSpotFlowTest(unittest.TestCase):
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
        _destroy(cls.win.root)
        cls.p.restore()

    def setUp(self):
        self.calls = []
        self.ipc = []
        self.lp = _Patch()
        self.lp.set(gee_bridge, 'send_arcmap_command', self._fake_ipc)
        self.lp.set(gee_gui.messagebox, 'showinfo', lambda *a, **k: None)
        self.lp.set(gee_gui.messagebox, 'showwarning', lambda *a, **k: self.calls.append(('warning', a)))

    def tearDown(self):
        self.lp.restore()
        self.win.var_source.set('gee')
        self.win.on_source_changed()

    def _fake_ipc(self, action, timeout=120):
        self.ipc.append(action)
        return {'success': True}

    def _pump(self, until, timeout=10.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.win._process_queue()
            if until():
                return True
            time.sleep(0.02)
        return False

    def _switch_to_spot(self, index=0):
        self.win.var_source.set('spot')
        self.win.on_source_changed()
        self.win.cbo_sensor.current(index)
        self.win.on_sensor_changed()

    def test_source_switch_adapts_the_window(self):
        self._switch_to_spot(2)
        w = self.win
        self.assertEqual(tuple(w.cbo_sensor['values']), tuple(l for l, _c in spot.SPOT_SENSOR_DISPLAY))
        self.assertEqual(w.get_selected_sensor_code(), 'SPOT:5-MS')
        self.assertTrue(w.var_comp.get().startswith(u'false - '))
        self.assertIn(u'SPOT', w.btn_search.cget('text'))
        self.assertEqual(str(w.txt_custom_bands.cget('state')), 'disabled')
        self.assertEqual(w.txt_start_date.get(), u'01/01/1986')
        self.assertEqual(w.txt_end_date.get(), u'31/12/2015')
        self.assertTrue(w.txt_group_name.get().startswith('SPOT_5-MS_false_'))
        self.assertIn(u'CNES GEODES', w.lbl_sensor_detail.cget('text'))
        self.assertTrue(w.btn_sources.winfo_manager())       # o botao XYZ continua na barra

    def test_search_fills_table_without_gee_auth(self):
        def fake_backend(cmd, params, on_progress=None, python_exe=None):
            self.calls.append((cmd, params, python_exe))
            return {'success': True, 'items': ITEMS}

        self.lp.set(gee_bridge, 'run_backend_cmd', fake_backend)
        self._switch_to_spot(2)
        self.win.is_authenticated = False
        self.win.var_spatial_type.set('extent')
        self.win.on_search_clicked()
        self.assertTrue(self._pump(lambda: len(self.win.tree.get_children()) == 2), u"tabela nao foi preenchida")
        cmd, params, py = self.calls[0]
        self.assertEqual((cmd, params['satellites'], params['kind'], py), ('spot_search', '5', 'ms', 'py3-gdal.exe'))
        self.assertEqual((params['start_date'], params['end_date']), ('1986-01-01', '2015-12-31'))
        rows = [self.win.tree.item(i, 'values') for i in self.win.tree.get_children()]
        self.assertEqual(rows[0][1], u'0%')
        self.assertIn(u'SPOT5', rows[0][2])
        self.win.tree.selection_set(self.win.tree.get_children()[0])
        self.win.on_image_selected()
        self.assertIn(u'Incidência', self.win.lbl_selected_info.cget('text'))

    def test_download_task_sends_key_and_loads_layer(self):
        def fake_backend(cmd, params, on_progress=None, python_exe=None):
            self.calls.append((cmd, params))
            if on_progress:
                on_progress(u'[ArcGEE] SPOT: alinhado à Esri: 477 m')
            return {'success': True, 'file': u'C:\\tmp\\spot.tif', 'rgb_bands': [0, 1, 2], 'valid_pct': 100.0,
                    'date': '2008-05-08', 'alignment': {'applied': True, 'shift_m': 477.1, 'residual_m': 2.5}}

        self.lp.set(gee_bridge, 'run_backend_cmd', fake_backend)
        with _TempAppData():
            spot.save_api_key(KEY)
            task = {'image_ids': [ITEMS[1]['id']], 'bbox': CTX['bbox'], 'replace_map': {}, 'auto_zoom': True,
                    'sensor': 'SPOT:123-MS', 'comp': 'false', 'custom_bands': None, 'load_mode': 'multiband',
                    'pixel_size': None, 'group_name': u'SPOT_teste', 'geojson_file': None}
            self.win._execute_single_download_task(task)
        cmd, params = self.calls[0]
        self.assertEqual((cmd, params['item_id'], params['mode'], params['api_key'], params['align']),
                         ('spot_download', ITEMS[1]['id'], 'false', KEY, True))
        load = [a for a in self.ipc if a.get('action') == 'load_layer'][0]
        self.assertEqual(load['rgb_bands'], [0, 1, 2])
        self.assertEqual(load['group'], u'SPOT_teste')
        self._pump(lambda: False, timeout=0.3)
        self.assertEqual([c for c in self.calls if c[0] == 'warning'], [])   # alinhada: sem aviso

    def test_unaligned_scene_warns_user(self):
        def fake_backend(cmd, params, on_progress=None, python_exe=None):
            return {'success': True, 'file': u'C:\\tmp\\spot.tif', 'rgb_bands': [0, 1, 2], 'valid_pct': 100.0,
                    'alignment': {'applied': False, 'reason': u'nuvens'}}

        self.lp.set(gee_bridge, 'run_backend_cmd', fake_backend)
        with _TempAppData():
            spot.save_api_key(KEY)
            resp = self.win._download_any('X', 'SPOT:MS', 'false', u'C:\\tmp\\x.tif', None, 'multiband',
                                          CTX['bbox'], None, None)
        self.assertTrue(resp['success'])
        self.assertTrue(self._pump(lambda: any(c[0] == 'warning' for c in self.calls), timeout=2))

    def test_enqueue_without_key_offers_setup_instead_of_downloading(self):
        asked = []
        self.lp.set(gee_gui.messagebox, 'askyesno', lambda *a, **k: asked.append(a) or False)
        self._switch_to_spot()
        with _TempAppData():
            self.win._enqueue_download_task([ITEMS[0]['id']], CTX['bbox'])
        self.assertEqual(len(asked), 1)
        self.assertIn(u'GEODES', asked[0][0])
        self.assertTrue(self.win.download_queue.empty())

    def test_settings_dialog_has_geodes_tab(self):
        self.lp.set(gee_gui.GEESettingsDialog, '__init__', gee_gui.GEESettingsDialog.__init__)
        dlg = gee_gui.GEESettingsDialog(self.win)
        try:
            self.assertTrue(hasattr(dlg, 'geodes_key'))
            tabs = [child for child in dlg.top.winfo_children() if isinstance(child, gee_gui.ttk.Notebook)][0]
            labels = [tabs.tab(t, 'text').strip() for t in tabs.tabs()]
            self.assertIn(u'Chave do GEODES (SPOT)', labels)
        finally:
            dlg.top.destroy()


if __name__ == '__main__':
    unittest.main()
