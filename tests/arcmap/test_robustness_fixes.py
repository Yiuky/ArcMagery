# -*- coding: utf-8 -*-
"""Correcoes de robustez do lado ArcMap/GUI: perfis acentuados (C:\\Users\\joão), .bat do executor
(ANSI, '&', '%', PID da propria GUI), rollback e snapshots, IPC com mensagens do arcpy em bytes,
prazos do backend, configuracoes mescladas e gravadas atomicamente, ganchos do Add-In e ordem dos
Pythons do QGIS. Nada toca o AssemblyCache real, os backups reais ou a internet."""
from __future__ import print_function

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

import _paths  # noqa: F401
import gee_bridge
import gee_updater as up

ACCENT = u"jo\xe3o"


def _mkdtemp_u(prefix):
    return gee_bridge.fs_text(tempfile.mkdtemp(prefix=prefix))


def _write(path, data=b'x'):
    d = os.path.dirname(path)
    if not os.path.isdir(d):
        os.makedirs(d)
    with open(path, 'wb') as f:
        f.write(data)


def _pid_alive(pid):
    import ctypes
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, pid)
    if not h:
        return False
    code = ctypes.c_ulong()
    k32.GetExitCodeProcess(h, ctypes.byref(code))
    k32.CloseHandle(h)
    return code.value == 259


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


class _Env(object):
    """Variaveis de ambiente temporarias (no Python 2 os.environ guarda bytes ANSI, como o Windows)."""

    def __init__(self, **values):
        self.values = values
        self.old = {}

    def __enter__(self):
        for k, v in self.values.items():
            self.old[k] = os.environ.get(k)
            os.environ[k] = v.encode('mbcs') if isinstance(v, type(u'')) else v
        return self

    def __exit__(self, *a):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _fake_install(root):
    """AssemblyCache + .esriaddin falsos (com acento e '&' no caminho)."""
    addin = os.path.join(root, u"Documents P&D", u"AddIns")
    cache = os.path.join(root, u"AppData", u"AssemblyCache")
    _write(os.path.join(addin, u"GEE_Image_Selector.esriaddin"), b'PK')
    for f in (u"gee_gui.py", u"config.xml", os.path.join(u"backend", u"run_gee.py")):
        _write(os.path.join(cache, f), b'# x')
    return {'addin_dir': addin, 'cache_dir': cache, 'dev_repo': None}


# ----------------------------------------------------------------------------------- item 1
class AccentedProfileUpdaterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = _mkdtemp_u('arcmagery_acc_')
        self.profile = os.path.join(self.tmp, ACCENT)
        os.makedirs(self.profile)
        self.p = _Patch()

    def tearDown(self):
        self.p.restore()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_app_dirs_are_unicode_with_accented_profile(self):
        with _Env(LOCALAPPDATA=os.path.join(self.profile, u"AppData", u"Local"), USERPROFILE=self.profile):
            self.assertIsInstance(up.get_backups_dir(), type(u''))
            self.assertIn(ACCENT, up.get_backups_dir())
            self.assertIn(ACCENT, up.get_updater_log_path())
            dirs = up.find_system_directories()
            self.assertIn(ACCENT, dirs['cache_dir'])
            up.log_info(u"linha com acento: %s" % up.get_backups_dir())   # nao pode levantar

    def test_snapshot_and_runner_with_accented_profile(self):
        sys_dirs = _fake_install(self.profile)
        launched = []
        self.p.set(up.subprocess, 'Popen', lambda args, **kw: launched.append(args))
        self.p.set(up, 'find_system_directories', lambda: sys_dirs)
        with _Env(LOCALAPPDATA=os.path.join(self.profile, u"AppData", u"Local"), USERPROFILE=self.profile):
            snap = up.create_snapshot_backup(current_version="2.4.1", custom_sys_dirs=sys_dirs)
            self.assertIn(ACCENT, snap['snapshot_dir'])
            self.assertEqual(up.snapshot_missing_files(snap['snapshot_dir']), [])
            staging = os.path.join(self.profile, u"stage")
            up.generate_and_launch_detached_runner(
                {'staging_dir': staging, 'config_file': os.path.join(staging, u'config.xml'),
                 'install_dir': staging, 'inst_backend': os.path.join(staging, u'backend'),
                 'staged_addin': os.path.join(staging, u'a.esriaddin')}, snap)
        self.assertIsInstance(launched[0], bytes)              # CreateProcessA: bytes ANSI
        self.assertTrue(launched[0].startswith(b'cmd.exe /d /s /c ""'))
        bat_arg = launched[0].split(b'""')[1]
        with open(bat_arg, 'rb') as f:
            text = f.read().decode('mbcs')
        os.remove(bat_arg)
        self.assertIn(u'set "BACKUP_DIR=%s"' % snap['snapshot_dir'], text)
        self.assertNotIn(u'chcp', text)

    def test_gui_temp_paths_are_unicode(self):
        self.assertIsInstance(gee_bridge.temp_dir(), type(u''))
        self.assertIsInstance(gee_bridge.CONTEXT_FILE, type(u''))
        os.path.join(gee_bridge.temp_dir(), u"cena_%s.tif" % ACCENT)


# ----------------------------------------------------------------------------- itens 5 e 6
class SnapshotAndRollbackSelectionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = _mkdtemp_u('arcmagery_snap_')
        self.root = os.path.join(self.tmp, u'backups')
        os.makedirs(self.root)
        self.p = _Patch()

    def tearDown(self):
        self.p.restore()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _snapshot(self, name, version, mtime):
        d = os.path.join(self.root, name)
        for f in (u'gee_gui.py', u'config.xml'):
            _write(os.path.join(d, u'AssemblyCache', f), b'#')
        _write(os.path.join(d, u'GEE_Image_Selector.esriaddin'), b'PK')
        with open(os.path.join(d, u'backup_manifest.json'), 'w') as fh:
            json.dump({'version': version, 'timestamp': '20260930_120000'}, fh)
        os.utime(d, (mtime, mtime))
        return d

    def test_previous_skips_snapshot_of_current_version(self):
        older = self._snapshot(u'backup_2_4_0_a', '2.4.0', 1000)
        self._snapshot(u'backup_2_4_1_b', '2.4.1', 2000)      # snapshot da propria versao instalada
        b = up.find_previous_version_backup(self.root, current_version='2.4.1')
        self.assertEqual(b['dir'], older)
        self.assertEqual(up.find_previous_version_backup(self.root)['version'], '2.4.1')   # sem filtro
        self.assertEqual(up.find_previous_version_backup(self.root, current_version='2.4.0')['version'], '2.4.1')

    def test_only_current_version_snapshots_means_no_rollback(self):
        self._snapshot(u'backup_2_4_1_b', '2.4.1', 2000)
        self.assertIsNone(up.find_previous_version_backup(self.root, current_version='v2.4.1'))

    def test_incomplete_snapshot_aborts_and_is_removed(self):
        sys_dirs = _fake_install(os.path.join(self.tmp, u'inst'))
        os.remove(os.path.join(sys_dirs['addin_dir'], u'GEE_Image_Selector.esriaddin'))
        with self.assertRaises(up.PreflightCheckError):
            up.create_snapshot_backup(current_version='2.4.1', backups_root=self.root, custom_sys_dirs=sys_dirs)
        self.assertEqual(os.listdir(self.root), [])

    def test_missing_assembly_cache_aborts(self):
        sys_dirs = _fake_install(os.path.join(self.tmp, u'inst'))
        shutil.rmtree(sys_dirs['cache_dir'])
        with self.assertRaises(up.PreflightCheckError):
            up.create_snapshot_backup(current_version='2.4.1', backups_root=self.root, custom_sys_dirs=sys_dirs)

    def test_zip_flow_discards_snapshot_when_staging_fails(self):
        snap_dir = os.path.join(self.root, u'backup_2_4_1_x')
        os.makedirs(snap_dir)
        zip_path = os.path.join(self.tmp, u'p.zip')
        _write(zip_path, b'x' * 2048)
        self.p.set(up, 'find_system_directories', lambda: {})
        self.p.set(up, 'validate_zip_archive', lambda p, target_dirs=None: {'proposed_version': '2.4.2'})
        self.p.set(up, 'create_snapshot_backup', lambda **k: {'snapshot_dir': snap_dir})

        def boom(p):
            raise up.MissingComponentsError(u"estrutura")
        self.p.set(up, 'prepare_staging_environment', boom)
        with self.assertRaises(up.MissingComponentsError):
            up.execute_zip_update_flow(zip_path, current_version='2.4.1')
        self.assertFalse(os.path.exists(snap_dir))


# ------------------------------------------------------------------------------- item 8
class RunnerScriptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = _mkdtemp_u('arcmagery_bat_')
        self.dir = os.path.join(self.tmp, u"P&D %s 50%%" % ACCENT)
        os.makedirs(self.dir)
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            try:
                p.kill()
            except Exception:
                pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _script(self, gui_process=(u'', u'pythonw.exe')):
        d = self.dir
        return up.build_runner_script(
            {'staging_dir': d, 'config_file': os.path.join(d, u'config.xml'), 'install_dir': d,
             'inst_backend': d, 'staged_addin': os.path.join(d, u'a.esriaddin')},
            {'snapshot_dir': d}, {'addin_dir': d, 'cache_dir': d, 'dev_repo': None},
            os.path.join(self.tmp, u'log.txt'), gui_process=gui_process,
            success_text=u"Versão nova & 'pronta'\n100% ok")

    def test_text_quotes_paths_and_targets_only_gui_pid(self):
        text = self._script(gui_process=(u'4242', u'pythonw.exe'))
        self.assertIn(u'set "ADDIN_DIR=%s"' % self.dir.replace(u'%', u'%%'), text)
        self.assertIn(u'set "GUI_PID=4242"', text)
        self.assertIn(u'set "GUI_NAME=pythonw"', text)
        self.assertIn(u'Stop-Process -Id %GUI_PID% -Force', text)
        self.assertIn(u"$p.ProcessName -eq '%GUI_NAME%'", text)
        self.assertNotIn(u'/im pythonw.exe', text)
        self.assertNotIn(u'| find', text)              # pipe trava no cmd desanexado
        self.assertNotIn(u'chcp', text)
        self.assertNotIn(u'`n', text)
        for line in text.splitlines():
            if line.startswith(u'powershell'):
                line.encode('ascii')           # mensagens 100% ASCII ([char]N para acentos/quebras)
        self.assertIn(u'ROLLBACK_ERR=1', text)
        self.assertIn(u'AssemblyCache\\gee_gui.py', text)

    def test_runner_dir_avoids_paths_that_break_cmd(self):
        """O cmd nao executa um .bat cujo PROPRIO caminho tem '&' (perfil 'P&D'): usa outra pasta."""
        p = _Patch()
        p.set(up, '_temp_dir', lambda: self.dir)
        try:
            d = up.runner_dir()
        finally:
            p.restore()
        self.assertNotIn(u'&', d)
        self.assertIsNone(up._bat_safe_dir(self.dir))
        self.assertEqual(up._bat_safe_dir(u"C:\\Temp"), u"C:\\Temp")

    def test_ps_message_expr(self):
        expr = up.ps_message_expr(u"Atualização\n'ok' 50%")
        expr.encode('ascii')
        self.assertIn(u"[char]10", expr)
        self.assertIn(u"''ok''", expr)
        self.assertIn(u"50%%", expr)
        self.assertEqual(up.ps_message_expr(u"a`nb"), up.ps_message_expr(u"a\nb"))

    def test_detached_cmd_reads_ansi_paths_and_spares_other_pythonw(self):
        """Executa (desanexado, como o atualizador) o cabecalho real do .bat + a espera pelo PID."""
        pyw = os.path.join(sys.prefix, 'pythonw.exe')
        if not os.path.exists(pyw):
            self.skipTest('pythonw.exe ausente')
        gui = subprocess.Popen([pyw, '-c', 'import time; time.sleep(2)'])
        other = subprocess.Popen([pyw, '-c', 'import time; time.sleep(60)'])
        self.procs += [gui, other]
        _write(os.path.join(self.dir, u'marca.txt'))
        text = self._script(gui_process=(str(gui.pid), u'pythonw.exe'))
        head = text.split(u':: 2. ')[0]                 # set + espera/kill do PID da GUI
        out = os.path.join(self.dir, u'out.txt')
        ps_out = os.path.join(self.dir, u'ps.txt')
        expected = u"Versão & 'aspas'\nfim 100%"
        script = head + (
            u'set "OUT=%s"\nset "PS_OUT=%s"\n'
            u'if exist "%%ADDIN_DIR%%\\marca.txt" (echo ADDIN_OK>> "%%OUT%%") else (echo ADDIN_NAO>> "%%OUT%%")\n'
            u'powershell -NoProfile -Command "[IO.File]::WriteAllText($env:PS_OUT, %s)"\n'
            u'echo FIM>> "%%OUT%%"\n') % (up.bat_path_text(out), up.bat_path_text(ps_out),
                                          up.ps_message_expr(expected))
        bat = os.path.join(up.runner_dir(), u'arcmagery_teste_%d.bat' % os.getpid())
        with open(bat, 'wb') as f:
            f.write(up._bat_bytes(script))
        self.addCleanup(lambda: os.path.exists(bat) and os.remove(bat))
        # desanexado e com a mesma linha de comando usada pelo atualizador
        subprocess.Popen(up.cmd_run_bat_line(bat), creationflags=0x8 | 0x200, close_fds=True)
        deadline = time.time() + 60
        while time.time() < deadline:
            if os.path.exists(out) and u'FIM' in open(out).read().decode('mbcs'):
                break
            time.sleep(0.3)
        content = open(out).read().decode('mbcs') if os.path.exists(out) else u''
        self.assertIn(u'ADDIN_OK', content)
        with open(ps_out, 'rb') as f:
            self.assertEqual(f.read().decode('utf-8-sig').replace(u'\r\n', u'\n'), expected)
        self.assertTrue(_pid_alive(other.pid), u"o .bat nao pode matar outros pythonw (U-02)")


# --------------------------------------------------------------------------- itens 7 e 12
class UpdaterMiscTest(unittest.TestCase):
    def test_documents_dir_is_real_folder(self):
        d = up._documents_dir()
        self.assertIsInstance(d, type(u''))
        self.assertTrue(os.path.isdir(d))
        self.assertTrue(up.find_system_directories()['addin_dir'].startswith(d))

    def test_user_agent_is_current(self):
        self.assertNotEqual(up.UPDATER_USER_AGENT, "ArcMagery-Updater/2.3")
        self.assertTrue(up.UPDATER_USER_AGENT.startswith("ArcMagery-Updater/2."))

    def test_err_text_of_localized_bytes(self):
        e = WindowsError(2, 'O sistema n\xe3o pode encontrar o arquivo')
        self.assertIn(u'n\xe3o', up._err(e))
        self.assertIn(u'n\xe3o', gee_bridge.err_text(e))

    def test_gui_imports_subprocess(self):
        import gee_gui
        self.assertTrue(hasattr(gee_gui, 'subprocess'))


# ---------------------------------------------------------------------- itens 2, 14 e 15
SLOW_WITH_PROGRESS = r'''
import json, sys, time
for i in range(8):
    sys.stderr.write("[ArcGEE] passo %d\n" % i)
    sys.stderr.flush()
    time.sleep(0.4)
sys.stdout.write(json.dumps({"success": True}) + "\n")
'''

SILENT = r'''
import time
time.sleep(30)
'''


class BackendCommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='arcmagery_bk_')
        self.p = _Patch()

    def tearDown(self):
        self.p.restore()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _script(self, body):
        path = os.path.join(self.tmp, 'fake_backend.py')
        with open(path, 'w') as f:
            f.write(body)
        self.p.set(gee_bridge, 'get_backend_script', lambda: path)

    def test_timeouts_table(self):
        self.assertEqual(gee_bridge.backend_timeout('spot_download'), 3600)
        self.assertEqual(gee_bridge.backend_timeout('pylibs_install'), 900)
        self.assertGreaterEqual(gee_bridge.backend_timeout('spot_search'), 120)
        self.assertGreaterEqual(gee_bridge.backend_timeout('spot_thumb'), 60)
        self.assertEqual(gee_bridge.backend_timeout('xyz_download'), 4 * 3600)
        self.assertEqual(gee_bridge.backend_timeout('nao_existe'), 120)

    def test_progress_resets_inactivity_timeout(self):
        self._script(SLOW_WITH_PROGRESS)
        self.p.set(gee_bridge, 'BACKEND_TIMEOUTS', dict(gee_bridge.BACKEND_TIMEOUTS, teste_lento=2))
        res = gee_bridge.run_backend_cmd('teste_lento', {}, python_exe=sys.executable)
        self.assertTrue(res.get('success'), res)            # 3,2 s no total, nunca 2 s sem progresso

    def test_silent_backend_times_out(self):
        self._script(SILENT)
        self.p.set(gee_bridge, 'BACKEND_TIMEOUTS', dict(gee_bridge.BACKEND_TIMEOUTS, teste_mudo=1))
        t0 = time.time()
        res = gee_bridge.run_backend_cmd('teste_mudo', {}, python_exe=sys.executable)
        self.assertFalse(res.get('success'))
        self.assertIn(u'Tempo limite', res['message'])
        self.assertLess(time.time() - t0, 15)

    def test_missing_python_returns_error_instead_of_raising(self):
        res = gee_bridge.run_backend_cmd('check', {}, python_exe="C:\\nao\\existe\\python.exe")
        self.assertFalse(res['success'])
        self.assertIsInstance(res['message'], type(u''))

    def test_cmdline_safe_path(self):
        self.assertEqual(gee_bridge.cmdline_safe_path(u"C:\\x\\a.json"), b"C:\\x\\a.json")
        d = os.path.join(gee_bridge.fs_text(self.tmp), ACCENT)
        os.makedirs(d)
        f = os.path.join(d, u"p.json")
        _write(f, b'{}')
        safe = gee_bridge.cmdline_safe_path(f)
        self.assertIsInstance(safe, bytes)
        self.assertTrue(os.path.exists(safe))               # 8.3 ASCII ou bytes ANSI: o mesmo arquivo
        self.assertIsNone(gee_bridge.cmdline_safe_path(u"C:\\nao_existe_\u4e2d\\p.json"))

    def test_params_file_with_accented_temp_reaches_backend(self):
        """O backend (aqui o Python do ArcGIS) recebe o --params-file e consegue abri-lo."""
        echo = os.path.join(self.tmp, 'echo_backend.py')
        with open(echo, 'w') as fh:
            fh.write("import sys, json, io\n"
                     "p = [a for a in sys.argv if a.startswith('--params-file=')][0].split('=', 1)[1]\n"
                     "d = json.load(io.open(p, encoding='utf-8'))\n"
                     "sys.stdout.write(json.dumps({'success': True, 'cmd': d['command'], 'v': d['v']}) + '\\n')\n")
        self.p.set(gee_bridge, 'get_backend_script', lambda: echo)
        acc = os.path.join(gee_bridge.fs_text(self.tmp), ACCENT)
        os.makedirs(acc)
        old = tempfile.tempdir
        tempfile.tempdir = acc.encode('mbcs')                # como TEMP de um perfil acentuado (bytes)
        try:
            res = gee_bridge.run_backend_cmd('eco', {'v': ACCENT}, python_exe=sys.executable)
        finally:
            tempfile.tempdir = old
        self.assertEqual((res.get('success'), res.get('cmd'), res.get('v')), (True, 'eco', ACCENT), res)

    def test_ascii_params_fallback_dir(self):
        src = os.path.join(self.tmp, 'p.json')
        _write(src, b'{}')
        with _Env(ProgramData=gee_bridge.fs_text(self.tmp)):
            moved = gee_bridge._ascii_params_path(src)
        self.assertTrue(moved and os.path.exists(moved))
        moved.encode('ascii')
        self.assertFalse(os.path.exists(src))


# ------------------------------------------------------------------------------ item 17
class QgisPythonOrderTest(unittest.TestCase):
    def test_newest_qgis_first(self):
        import glob
        fake = {
            r"C:\Program Files\QGIS *\apps\Python3*\python.exe": [
                r"C:\Program Files\QGIS 3.28\apps\Python39\python.exe",
                r"C:\Program Files\QGIS 3.40.5\apps\Python312\python.exe",
                r"C:\Program Files\QGIS 3.44.10\apps\Python312\python.exe",
                r"C:\Program Files\QGIS 3.44.10\apps\Python39\python.exe",
                r"C:\Program Files\QGIS 3.4\apps\Python37\python.exe"],
            r"C:\Program Files (x86)\QGIS *\apps\Python3*\python.exe": [
                r"C:\Program Files (x86)\QGIS 3.42.1\apps\Python312\python.exe"],
            r"C:\OSGeo4W*\apps\Python3*\python.exe": [
                r"C:\OSGeo4W\apps\Python39\python.exe", r"C:\OSGeo4W\apps\Python312\python.exe"],
        }
        p = _Patch()
        p.set(glob, 'glob', lambda pat: list(fake.get(pat, [])))
        p.set(gee_bridge.os.path, 'exists', lambda c: bool(c) and ('QGIS' in c or 'OSGeo4W' in c))
        try:
            with _Env(GEE_PYTHON3=u""):
                got = gee_bridge.python3_candidates()
        finally:
            p.restore()
        got = [os.path.normcase(g) for g in got]
        want = [os.path.normcase(x) for x in (
            r"C:\Program Files\QGIS 3.44.10\apps\Python312\python.exe",
            r"C:\Program Files\QGIS 3.44.10\apps\Python39\python.exe",
            r"C:\Program Files (x86)\QGIS 3.42.1\apps\Python312\python.exe",
            r"C:\Program Files\QGIS 3.40.5\apps\Python312\python.exe",
            r"C:\Program Files\QGIS 3.28\apps\Python39\python.exe",
            r"C:\Program Files\QGIS 3.4\apps\Python37\python.exe",
            r"C:\OSGeo4W\apps\Python312\python.exe",
            r"C:\OSGeo4W\apps\Python39\python.exe")]
        self.assertEqual([g for g in got if 'qgis' in g or 'osgeo4w' in g], want)
        self.assertFalse([g for g in got if 'cgma_gee_plugin' in g])


# ------------------------------------------------------------------------- itens 4 e 13
class IpcTest(unittest.TestCase):
    def setUp(self):
        self.tmp = gee_bridge.fs_text(tempfile.mkdtemp(prefix='arcmagery_ipc_'))
        self.p = _Patch()
        self.p.set(gee_bridge, 'CMD_FILE', os.path.join(self.tmp, u'cmd.json'))
        self.p.set(gee_bridge, 'REPLY_FILE', os.path.join(self.tmp, u'reply.json'))
        self.p.set(gee_bridge, 'HEARTBEAT_FILE', os.path.join(self.tmp, u'hb.tmp'))

    def tearDown(self):
        self.p.restore()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_safe_write_json_does_not_retry_serialization_errors(self):
        t0 = time.time()
        self.assertFalse(gee_bridge.safe_write_json(os.path.join(self.tmp, u'a.json'), {'x': object()}))
        self.assertFalse(gee_bridge.safe_write_json(os.path.join(self.tmp, u'b.json'), {'x': 'n\xe3o'}))
        self.assertLess(time.time() - t0, 0.3)
        self.assertTrue(gee_bridge.safe_write_json(os.path.join(self.tmp, u'c.json'), {'x': ACCENT}))

    def test_arcpy_bytes_error_still_produces_reply(self):
        def boom(scale):
            raise Exception('Erro ao definir a escala: n\xe3o foi poss\xedvel')
        self.p.set(gee_bridge, 'set_arcmap_scale', boom)
        self.p.set(gee_bridge, 'export_arcmap_context', lambda: None)   # sem ArcMap aberto
        gee_bridge.safe_write_json(gee_bridge.CMD_FILE, {'id': 'c1', 'action': 'set_scale', 'scale': 1})
        self.assertTrue(gee_bridge.process_pending_arcmap_commands())
        rep = gee_bridge.safe_read_json(gee_bridge.REPLY_FILE)
        self.assertEqual((rep['reply_to'], rep['success']), ('c1', False))
        self.assertIn(u'n\xe3o', rep['message'])

    def test_busy_lock_gives_up_within_own_timeout(self):
        gee_bridge._ipc_cmd_lock.acquire()
        try:
            t0 = time.time()
            rep = gee_bridge.send_arcmap_command({'action': 'export_aoi'}, timeout=0.4)
            self.assertLess(time.time() - t0, 2.0)
        finally:
            gee_bridge._ipc_cmd_lock.release()
        self.assertTrue(rep.get('busy'))
        self.assertIn(u'ocupado', rep['message'])

    def test_unwritable_command_fails_immediately(self):
        self.p.set(gee_bridge, 'safe_write_json', lambda *a, **k: False)
        t0 = time.time()
        rep = gee_bridge.send_arcmap_command({'action': 'set_scale', 'scale': 1}, timeout=30)
        self.assertFalse(rep['success'])
        self.assertLess(time.time() - t0, 1.0)

    def test_hooks_export_context_only_with_gui_alive(self):
        import gee_selector_addin
        calls = []
        self.p.set(gee_bridge, 'start_arcmap_ipc_timer', lambda *a: True)
        self.p.set(gee_bridge, 'export_arcmap_context', lambda: calls.append(1))
        ext = gee_selector_addin.GEEExtension()
        del calls[:]
        ext.activeViewChanged()
        ext.contentsChanged()
        self.assertEqual(calls, [])                       # GUI fechada: nada exportado
        _write(gee_bridge.HEARTBEAT_FILE, b'1')
        ext.activeViewChanged()
        ext.contentsChanged()
        self.assertEqual(len(calls), 2)                   # GUI aberta: comportamento de antes
        old = time.time() - 60
        os.utime(gee_bridge.HEARTBEAT_FILE, (old, old))
        btn = gee_selector_addin.OpenGEESelectorButton.__new__(gee_selector_addin.OpenGEESelectorButton)
        btn._style_applied, btn._last_ctx_time = True, 0
        btn.onUpdate()
        self.assertEqual(len(calls), 2)


# ------------------------------------------------------------------------------ item 9
class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='arcmagery_set_')
        self.p = _Patch()
        self.p.set(gee_bridge, 'SETTINGS_FILE', os.path.join(self.tmp, 'settings.json'))

    def tearDown(self):
        self.p.restore()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_update_merges_onto_disk_and_is_atomic(self):
        self.assertTrue(gee_bridge.save_plugin_settings({'a': 1, 'b': 1}))
        gee_bridge.update_plugin_settings({'b': 2, 'c': ACCENT})
        data = json.load(open(gee_bridge.SETTINGS_FILE))
        self.assertEqual((data['a'], data['b'], data['c']), (1, 2, ACCENT))
        self.assertEqual([f for f in os.listdir(self.tmp) if f.endswith('.tmp')], [])

    def test_sources_window_does_not_overwrite_with_stale_dict(self):
        import arcmagery_sources_gui as sg
        gee_bridge.save_plugin_settings({'update_channel': 'nightly', 'arcmagery_xyz_zoom': 15})
        dlg = sg.ExtraSourcesDialog.__new__(sg.ExtraSourcesDialog)
        dlg.settings = {'update_channel': 'stable'}          # copia velha guardada na abertura
        dlg._save_settings({'arcmagery_xyz_zoom': 19, 'arcmagery_xyz_crs': 'EPSG:4674'})
        data = gee_bridge.load_plugin_settings()
        self.assertEqual(data['update_channel'], 'nightly')
        self.assertEqual((data['arcmagery_xyz_zoom'], data['arcmagery_xyz_crs']), (19, 'EPSG:4674'))

    def test_parent_settings_updated_in_place(self):
        import gee_gui

        class P(object):
            pass
        parent = P()
        parent.settings = {'x': 1}
        shared = parent.settings
        gee_gui._refresh_parent_settings(parent, {'x': 2, 'y': 3})
        self.assertIs(parent.settings, shared)
        self.assertEqual(shared, {'x': 2, 'y': 3})


# --------------------------------------------------------------------------- itens 3 e 11
class GuiThreadsAndCloseTest(unittest.TestCase):
    def test_workers_are_daemon(self):
        import gee_gui
        t = gee_gui.start_daemon(lambda: None)
        self.assertTrue(t.daemon)

    def test_updater_worker_posts_to_gui_queue(self):
        import gee_gui
        posted = []
        done = threading.Event()

        class Parent(object):
            def post_to_gui(self, fn):
                posted.append(fn)
                done.set()
        dlg = gee_gui.GEEUpdaterDialog.__new__(gee_gui.GEEUpdaterDialog)
        dlg.parent = Parent()

        def flow():
            raise RuntimeError(u"falhou")
        dlg._run_update_worker(flow, u"ok", u"ok", u"falha")
        self.assertTrue(done.wait(5))
        self.assertEqual(len(posted), 1)                  # o erro volta pela fila, nunca top.after

    def test_on_close_stops_backends_and_exits(self):
        import gee_gui
        calls = {}

        class Root(object):
            def destroy(self):
                calls['destroy'] = True

        class Win(object):
            pass
        w = Win()
        w.root = Root()
        p = _Patch()
        p.set(gee_bridge, 'shutdown_backends', lambda groups, timeout=6.0: calls.setdefault('groups', list(groups)))
        p.set(gee_bridge, 'HEARTBEAT_FILE', os.path.join(tempfile.gettempdir(), 'arcmagery_hb_teste.tmp'))
        p.set(gee_gui.os, '_exit', lambda code: calls.setdefault('exit', code))
        try:
            gee_gui.GEEPluginWindow.__dict__['on_close'](w)
        finally:
            p.restore()
        self.assertTrue(calls.get('destroy'))
        self.assertEqual(calls['groups'], ['main', 'xyz'])
        self.assertEqual(calls['exit'], 0)
        self.assertFalse(w._alive)

    def test_shutdown_backends_kills_processes(self):
        proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        state = {'cancelled': False, 'group': 'xyz'}
        with gee_bridge._ACTIVE_LOCK:
            gee_bridge._ACTIVE_BACKENDS[proc] = state
        try:
            self.assertEqual(gee_bridge.shutdown_backends(['main', 'xyz'], timeout=8), 1)
        finally:
            with gee_bridge._ACTIVE_LOCK:
                gee_bridge._ACTIVE_BACKENDS.pop(proc, None)
        self.assertTrue(state['cancelled'])
        time.sleep(0.3)
        self.assertIsNotNone(proc.poll())


if __name__ == '__main__':
    unittest.main()
