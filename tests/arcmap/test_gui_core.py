# -*- coding: utf-8 -*-
"""Nucleo da GUI principal: ui_call (threads), instancia unica e pythonw sem console."""
from __future__ import print_function

import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest

import _paths
import gee_gui


class FakeWin(object):
    """Somente o necessario para exercitar GEEPluginWindow.ui_call sem abrir a janela."""

    def __init__(self):
        self.q = []

    def post_to_gui(self, fn):
        self.q.append(fn)


class UiCallTest(unittest.TestCase):
    ui_call = staticmethod(gee_gui.GEEPluginWindow.__dict__['ui_call'])  # funcao pura, sem bind ao TestCase

    def test_main_thread_runs_inline(self):
        self.assertEqual(self.ui_call(FakeWin(), lambda: 42), 42)

    def test_worker_waits_for_main_thread(self):
        win = FakeWin()
        out = {}

        def worker():
            out['thread_of_fn'] = self.ui_call(win, lambda: threading.current_thread().name, 10)

        t = threading.Thread(target=worker)
        t.start()
        deadline = time.time() + 5
        while t.is_alive() and time.time() < deadline:   # "mainloop": executa o que foi postado
            while win.q:
                win.q.pop(0)()
            time.sleep(0.01)
        t.join(1)
        self.assertEqual(out.get('thread_of_fn'), 'MainThread')

    def test_worker_gets_exception(self):
        win = FakeWin()
        out = {}

        def boom():
            raise ValueError('falhou na UI')

        def worker():
            try:
                self.ui_call(win, boom, 10)
            except ValueError as e:
                out['err'] = str(e)

        t = threading.Thread(target=worker)
        t.start()
        while t.is_alive():
            while win.q:
                win.q.pop(0)()
            time.sleep(0.01)
        self.assertEqual(out.get('err'), 'falhou na UI')


class SingleInstanceTest(unittest.TestCase):
    def test_second_instance_is_refused(self):
        self.assertTrue(gee_gui.acquire_single_instance())
        self.assertFalse(gee_gui.acquire_single_instance())


class PythonwStdoutTest(unittest.TestCase):
    """Regressao: sob pythonw.exe (sem console) o stdout tem fileno -2; um print grande dava
    IOError(9) e derrubava o worker de download. O import dos modulos deve redirecionar."""

    @unittest.skipUnless(os.path.exists(_paths.PYTHONW), "pythonw.exe nao encontrado")
    def test_large_print_under_detached_pythonw(self):
        fd, result = tempfile.mkstemp(suffix='.txt')
        os.close(fd)
        script = os.path.join(tempfile.gettempdir(), 'arcmagery_pyw_probe.py')
        with open(script, 'w') as f:
            f.write(
                "import sys\n"
                "sys.path.insert(0, %r)\n"
                "res = open(%r, 'w')\n"
                "try:\n"
                "    import gee_gui\n"
                "    for i in range(300):\n"
                "        print('x' * 100)\n"
                "    sys.stdout.flush()\n"
                "    res.write('OK')\n"
                "except Exception as e:\n"
                "    res.write('FALHA %%r' %% (e,))\n"
                "res.close()\n" % (_paths.INSTALL, result))
        DETACHED_PROCESS = 0x00000008
        p = subprocess.Popen([_paths.PYTHONW, script], close_fds=True, creationflags=DETACHED_PROCESS)
        p.wait()
        with open(result) as f:
            content = f.read()
        os.remove(result)
        os.remove(script)
        self.assertEqual(content, 'OK')


if __name__ == '__main__':
    unittest.main()
