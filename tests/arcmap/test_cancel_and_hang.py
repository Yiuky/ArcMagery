# -*- coding: utf-8 -*-
"""Backend que entrega o resultado mas nao encerra (bug do CBERS-2: 5-15 min presos) e botao
Interromper: com processos reais (o Python do ArcGIS faz o papel do backend)."""
from __future__ import print_function

import os
import shutil
import sys
import tempfile
import threading
import time
import unittest

import _paths
import gee_bridge
import gee_gui

HANGS_AFTER_RESULT = r'''
import json, sys, time
sys.stdout.write(json.dumps({"success": True, "file": "x.tif"}) + "\n")
sys.stdout.flush()
time.sleep(60)      # como o GDAL/curl preso na saida
'''

NEVER_ANSWERS = r'''
import time
time.sleep(60)
'''


def _pid_alive(pid):
    import ctypes
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    code = ctypes.c_ulong()
    k32.GetExitCodeProcess(h, ctypes.byref(code))
    k32.CloseHandle(h)
    return code.value == 259                       # STILL_ACTIVE


class BackendHangTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='arcmagery_hang_')
        self.saved = gee_bridge.get_backend_script

    def tearDown(self):
        gee_bridge.get_backend_script = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _script(self, body):
        path = os.path.join(self.tmp, 'fake_backend.py')
        with open(path, 'w') as f:
            f.write(body)
        gee_bridge.get_backend_script = lambda: path

    def test_result_is_returned_even_if_process_never_exits(self):
        self._script(HANGS_AFTER_RESULT)
        t0 = time.time()
        res = gee_bridge.run_backend_cmd('stac_download', {}, python_exe=sys.executable)
        elapsed = time.time() - t0
        self.assertEqual(res.get('file'), 'x.tif')
        self.assertLess(elapsed, gee_bridge.RESULT_GRACE_SECONDS + 10)    # antes: ate 30 min
        self.assertEqual(gee_bridge.active_backend_count(), 0)

    def test_cancel_kills_running_backend(self):
        self._script(NEVER_ANSWERS)
        box = {}

        def run():
            box['res'] = gee_bridge.run_backend_cmd('stac_download', {}, python_exe=sys.executable)

        t = threading.Thread(target=run)
        t.start()
        deadline = time.time() + 10
        while gee_bridge.active_backend_count() == 0 and time.time() < deadline:
            time.sleep(0.05)
        pid = list(gee_bridge._ACTIVE_BACKENDS)[0].pid
        self.assertEqual(gee_bridge.cancel_backend_commands(), 1)
        t.join(20)
        self.assertFalse(t.is_alive())
        self.assertTrue(box['res'].get('cancelled'))
        self.assertEqual(box['res']['message'], gee_bridge.CANCELLED_MESSAGE)
        time.sleep(0.5)
        self.assertFalse(_pid_alive(pid))


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


class CancelButtonTest(unittest.TestCase):
    CTX = {'bbox': [-56.1, -15.6, -56.0, -15.5], 'scale': 50000, 'vector_layers': [], 'raster_layers': [],
           'groups_with_rasters': [], 'time': 1}

    @classmethod
    def setUpClass(cls):
        cls.p = _Patch()
        cls.p.set(gee_bridge, 'read_arcmap_context', lambda: dict(cls.CTX))
        cls.p.set(gee_bridge, 'load_plugin_settings', lambda: {})
        cls.p.set(gee_bridge, 'save_plugin_settings', lambda s: True)
        cls.win = gee_gui.GEEPluginWindow()
        cls.win.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.win._alive = False
        cls.win.root.destroy()
        cls.p.restore()

    def test_cancel_empties_queue_and_kills_backends(self):
        lp = _Patch()
        killed = []
        lp.set(gee_bridge, 'cancel_backend_commands', lambda: killed.append(1) or 2)
        lp.set(gee_gui.messagebox, 'askyesno', lambda *a, **k: True)
        w = self.win
        try:
            w.download_queue.put({'image_ids': ['A', 'B']})
            w.queued_ids.update(['A', 'B'])
            w.on_cancel_clicked()
            w._process_queue()
            self.assertTrue(w.download_queue.empty())
            self.assertFalse(w.queued_ids)
            self.assertTrue(killed)
            self.assertTrue(w._cancel_requested)
            self.assertIn(u'Interrompido', w.lbl_progress.cget('text'))
        finally:
            lp.restore()

    def test_button_state_follows_activity(self):
        w = self.win
        w.is_downloading = False
        w._search_running = False
        w.update_action_buttons_state()
        self.assertEqual(str(w.btn_cancel.cget('state')), 'disabled')
        w._search_running = True
        w.update_action_buttons_state()
        self.assertEqual(str(w.btn_cancel.cget('state')), 'normal')
        w._search_running = False
        w.update_action_buttons_state()


if __name__ == '__main__':
    unittest.main()
