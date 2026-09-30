# -*- coding: utf-8 -*-
"""Regressoes da revisao de codigo (v2.3.3) na ponte e na janela principal (Python 2.7)."""
from __future__ import print_function

import os
import shutil
import tempfile
import threading
import time
import unittest

import _paths
import arcmagery_gehist as gehist
import arcmagery_sources_gui as sg
import gee_bridge
import gee_gui

CTX = {'bbox': [-56.10, -15.64, -56.02, -15.58], 'scale': 50000, 'vector_layers': [u'AOI'],
       'raster_layers': [], 'groups_with_rasters': [], 'time': 1}


class StaleSidecarsTest(unittest.TestCase):
    def test_only_sidecars_older_than_the_tif_are_removed(self):
        tmp = tempfile.mkdtemp(prefix='arcmagery_side_')
        try:
            tif = os.path.join(tmp, 'x.tif')
            for path in (tif, tif + '.ovr', tif + '.aux.xml'):
                open(path, 'w').close()
            now = time.time()
            os.utime(tif + '.ovr', (now - 3600, now - 3600))       # de um download anterior
            os.utime(tif, (now - 10, now - 10))
            os.utime(tif + '.aux.xml', (now, now))                  # gerado depois (backend)
            removed = gee_bridge.remove_stale_sidecars(tif)
            self.assertEqual(removed, [tif + '.ovr'])
            self.assertTrue(os.path.exists(tif + '.aux.xml'))
            self.assertEqual(gee_bridge.remove_stale_sidecars(os.path.join(tmp, 'nao_existe.tif')), [])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class _FakeProc(object):
    def __init__(self, pid):
        self.pid = pid

    def poll(self):
        return None


class CancelScopeTest(unittest.TestCase):
    def setUp(self):
        self.saved_kill = gee_bridge.kill_process_tree
        self.killed = []

        def slow_kill(proc):
            time.sleep(1.5)                     # taskkill demorado
            self.killed.append(proc.pid)

        gee_bridge.kill_process_tree = slow_kill
        self.main, self.xyz = _FakeProc(1), _FakeProc(2)
        self.st_main, self.st_xyz = {'cancelled': False, 'group': 'main'}, {'cancelled': False, 'group': 'xyz'}
        with gee_bridge._ACTIVE_LOCK:
            gee_bridge._ACTIVE_BACKENDS[self.main] = self.st_main
            gee_bridge._ACTIVE_BACKENDS[self.xyz] = self.st_xyz

    def tearDown(self):
        with gee_bridge._ACTIVE_LOCK:
            gee_bridge._ACTIVE_BACKENDS.pop(self.main, None)
            gee_bridge._ACTIVE_BACKENDS.pop(self.xyz, None)
        gee_bridge.kill_process_tree = self.saved_kill

    def test_only_main_window_backends_and_without_blocking(self):
        self.assertEqual((gee_bridge.active_backend_count(), gee_bridge.active_backend_count('xyz')), (1, 1))
        t0 = time.time()
        self.assertEqual(gee_bridge.cancel_backend_commands(), 1)
        self.assertLess(time.time() - t0, 0.5)                     # nao espera o taskkill
        self.assertTrue(self.st_main['cancelled'])
        self.assertFalse(self.st_xyz['cancelled'])                 # janela XYZ intacta
        deadline = time.time() + 5
        while not self.killed and time.time() < deadline:
            time.sleep(0.05)
        self.assertEqual(self.killed, [1])


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


class Concurrency(object):
    def __init__(self):
        self.lock, self.now, self.peak = threading.Lock(), 0, 0

    def enter(self):
        with self.lock:
            self.now += 1
            self.peak = max(self.peak, self.now)
        time.sleep(0.15)
        with self.lock:
            self.now -= 1


class MainWindowFixesTest(unittest.TestCase):
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
        self.lp = _Patch()
        self.lp.set(gee_bridge, 'send_arcmap_command', lambda a, timeout=120: {'success': True})
        for kind in ('showinfo', 'showwarning', 'showerror'):
            self.lp.set(gee_gui.messagebox, kind, lambda *a, **k: None)

    def tearDown(self):
        self.lp.restore()
        self.win.settings = {}

    def _task(self, ids, sensor):
        return {'image_ids': ids, 'bbox': CTX['bbox'], 'replace_map': {}, 'auto_zoom': False, 'sensor': sensor,
                'comp': 'rgb', 'custom_bands': None, 'load_mode': 'rgb', 'pixel_size': None, 'group_name': None,
                'geojson_file': None}

    def test_tile_source_rows_download_one_at_a_time(self):
        """Antes: 6 datas x 48 threads cada em paralelo (servidor recusava as conexoes)."""
        conc = Concurrency()

        def fake(cmd, params, on_progress=None, python_exe=None, **kw):
            conc.enter()
            return {'success': True, 'file': u'C:\\tmp\\h.tif', 'coverage_pct': 100.0}

        self.lp.set(gee_bridge, 'run_backend_cmd', fake)
        self.win.settings = {'multicore_enabled': True, 'multicore_cores': 8}
        ids = [u'GoogleEarth_2022062%d_z18' % i for i in range(4)]
        self.win._execute_single_download_task(self._task(ids, gehist.ALL))
        self.assertEqual(conc.peak, 1)

    def test_parallel_scene_downloads_capped_at_4(self):
        """Antes: multicore_cores (agora CPU - 2, ate 16) virava o numero de downloads simultaneos."""
        conc = Concurrency()

        def fake_download_image(**kw):
            conc.enter()
            return {'success': True, 'file': u'C:\\tmp\\s2.tif'}

        self.lp.set(gee_bridge, 'download_image', fake_download_image)
        self.win.settings = {'multicore_enabled': True, 'multicore_cores': 14}
        ids = ['COPERNICUS/S2_SR_HARMONIZED/X%d' % i for i in range(10)]
        self.win._execute_single_download_task(dict(self._task(ids, 'S2'), comp='432'))
        self.assertTrue(1 < conc.peak <= self.win.MAX_PARALLEL_DOWNLOADS, conc.peak)

    def test_finished_old_search_does_not_clear_running_state(self):
        w = self.win
        w._active_search_token = 10
        w._search_running = True
        w._finish_search(9)                      # busca antiga (cancelada) terminando depois
        self.assertTrue(w._search_running)
        w._finish_search(10)
        self.assertFalse(w._search_running)

    def test_thumbnail_uses_the_search_aoi(self):
        calls = []
        self.lp.set(gee_bridge, 'run_backend_cmd',
                    lambda cmd, params, **k: calls.append((cmd, params)) or {'success': False, 'message': 'x'})
        w = self.win
        w.var_source.set('gehist')
        w.on_source_changed()
        row = gehist.date_to_row({'date': '2022-06-28', 'zoom': 18, 'coverage_pct': 50.0, 'provider': 'Maxar'})
        w.images_cache = [row]
        for i in w.tree.get_children():
            w.tree.delete(i)
        w.tree.selection_set(w.tree.insert('', 'end', values=(row['date'], '', '', row['id'], '-', '')))
        w.var_spatial_type.set('layer')
        w._last_search_geojson = u'C:\\tmp\\aoi.geojson'
        try:
            w.on_thumbnail_clicked()
            deadline = time.time() + 5
            while not calls and time.time() < deadline:
                w._process_queue()
                time.sleep(0.02)
            self.assertEqual(calls[0][0], 'gehist_thumb')
            self.assertEqual(calls[0][1].get('geojson_file'), u'C:\\tmp\\aoi.geojson')
            self.assertNotIn('bbox', calls[0][1])
        finally:
            w.var_spatial_type.set('extent')
            w.var_source.set('gee')
            w.on_source_changed()


class ExtraSourcesDialogTest(unittest.TestCase):
    def test_xyz_download_uses_configured_threads_and_own_group(self):
        root = sg.tk.Tk()
        root.withdraw()
        got = {}

        class Parent(object):
            def __init__(self):
                self.root = root
                self.settings = {'tile_threads': 24}
                self.arcmap_context = {'bbox': CTX['bbox'], 'vector_layers': []}
                self.ipc_lock = threading.Lock()

            def post_to_gui(self, fn):
                pass

        saved = gee_bridge.run_backend_cmd, gee_bridge.send_arcmap_command, gee_bridge.find_python3_gdal

        def fake(cmd, params, on_progress=None, python_exe=None, group=None):
            got.update(cmd=cmd, workers=params.get('workers'), group=group)
            return {'success': True, 'file': u'C:\\tmp\\x.tif'}

        gee_bridge.run_backend_cmd = fake
        gee_bridge.send_arcmap_command = lambda a, timeout=120: {'success': True, 'context': {'bbox': CTX['bbox']}}
        gee_bridge.find_python3_gdal = lambda: 'py3.exe'
        tmp = tempfile.mkdtemp()
        try:
            dlg = sg.ExtraSourcesDialog(Parent())
            dlg.top.withdraw()
            dlg._xyz_worker({'area': {'type': 'extent', 'layer': None, 'buffer': 0.0}, 'provider': 'esri',
                             'label': u'Esri', 'zoom': 15, 'compression': 'JPEG', 'crs': None, 'out_dir': tmp})
            dlg.top.destroy()
        finally:
            gee_bridge.run_backend_cmd, gee_bridge.send_arcmap_command, gee_bridge.find_python3_gdal = saved
            shutil.rmtree(tmp, ignore_errors=True)
            root.destroy()
        self.assertEqual((got['cmd'], got['workers'], got['group']), ('xyz_download', 24, sg.XYZ_BACKEND_GROUP))


if __name__ == '__main__':
    unittest.main()
