# -*- coding: utf-8 -*-
from __future__ import print_function

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import _paths
import gee_bridge


class RgbOverrideTest(unittest.TestCase):
    def test_valid_and_invalid(self):
        self.assertEqual(gee_bridge._rgb_override([2, 1, 0]), (2, 1, 0))
        self.assertEqual(gee_bridge._rgb_override(['0', '1', '2']), (0, 1, 2))
        self.assertIsNone(gee_bridge._rgb_override(None))
        self.assertIsNone(gee_bridge._rgb_override([0, 1]))
        self.assertIsNone(gee_bridge._rgb_override([0, -1, 2]))
        self.assertIsNone(gee_bridge._rgb_override(['a', 'b', 'c']))


class ErrTextTest(unittest.TestCase):
    """Bug: "'ascii' codec can't encode character u'\xf3' in position 1" ao carregar QUALQUER camada
    numa maquina sem comtypes: a mensagem u"Módulo 'comtypes' ausente..." passava por str(e)."""

    def test_unicode_utf8_and_cp1252_messages(self):
        self.assertEqual(gee_bridge.err_text(Exception(u'Módulo ausente')), u'Módulo ausente')
        self.assertEqual(gee_bridge.err_text(Exception(u'Módulo'.encode('utf-8'))), u'Módulo')
        self.assertEqual(gee_bridge.err_text(Exception(u'Módulo'.encode('cp1252'))), u'Módulo')
        self.assertEqual(gee_bridge.err_text(ValueError('ascii')), u'ascii')

    def test_prepare_symbology_survives_accented_error(self):
        import arcmagery_symbology as sym
        orig = sym.apply_to_layer_file

        def boom(*a, **k):
            raise sym.SymbologyError(u"Módulo 'comtypes' ausente no Python do ArcGIS")
        sym.apply_to_layer_file = boom
        try:
            warn = gee_bridge._prepare_layer_symbology('x.lyr', {}, None)
        finally:
            sym.apply_to_layer_file = orig
        self.assertEqual(warn, u"Módulo 'comtypes' ausente no Python do ArcGIS")

    def test_vendored_comtypes_is_on_path(self):
        import os, sys
        import arcmagery_vendor
        self.assertTrue(os.path.isfile(os.path.join(arcmagery_vendor.VENDOR_DIR, 'comtypes', 'client', '__init__.py')))
        self.assertIn(arcmagery_vendor.VENDOR_DIR, sys.path)
        self.assertTrue(os.path.isfile(os.path.join(arcmagery_vendor.VENDOR_DIR, 'comtypes', 'LICENSE.txt')))


class AtomicJsonTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='arcmagery_ipc_')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_roundtrip_and_no_leftovers(self):
        path = os.path.join(self.tmp, 'cmd.json')
        for i in range(5):  # sobrescrita repetida (MoveFileEx REPLACE_EXISTING)
            self.assertTrue(gee_bridge.safe_write_json(path, {'id': i, 'txt': u'ção'}))
        self.assertEqual(gee_bridge.safe_read_json(path), {'id': 4, 'txt': u'ção'})
        self.assertEqual(os.listdir(self.tmp), ['cmd.json'])


class IpcSessionTest(unittest.TestCase):
    def _names(self, env_value):
        env = dict(os.environ)
        env.pop('ARCMAGERY_SESSION', None)
        if env_value is not None:
            env['ARCMAGERY_SESSION'] = env_value
        code = ("import sys, json; sys.path.insert(0, %r); import gee_bridge as b; "
                "sys.stdout.write(json.dumps([b.IPC_SESSION, b.CMD_FILE, b.REPLY_FILE, b.CONTEXT_FILE, b.HEARTBEAT_FILE]))"
                % _paths.INSTALL)
        out = subprocess.check_output([sys.executable, '-c', code], env=env)
        return json.loads(out.decode('utf-8').strip().splitlines()[-1])

    def test_session_from_env_isolates_files(self):
        sid, cmd, reply, ctx, hb = self._names('4242')
        self.assertEqual(sid, '4242')
        for p in (cmd, reply, ctx, hb):
            self.assertIn('arcmagery_4242_', os.path.basename(p))

    def test_invalid_env_falls_back_to_pid(self):
        sid = self._names('../evil')[0]
        self.assertTrue(sid.isdigit())
        self.assertNotEqual(sid, '../evil')


class PythonDiscoveryTest(unittest.TestCase):
    def test_candidates_exist_and_skip_store_alias(self):
        for c in gee_bridge.python3_candidates():
            self.assertTrue(os.path.exists(c), c)
            self.assertNotIn('WindowsApps', c)

    @unittest.skipUnless(_paths.qgis_python(), "QGIS 3.x nao encontrado")
    def test_python_has_modules(self):
        py = _paths.qgis_python()
        gee_bridge._MODULE_CHECK_CACHE.clear()
        self.assertTrue(gee_bridge.python_has_modules(py, ['json']))
        self.assertFalse(gee_bridge.python_has_modules(py, ['modulo_que_nao_existe_arcmagery']))
        self.assertFalse(gee_bridge.python_has_modules(sys.executable, ['json']),
                         "o Python 2.7 nao pode ser aceito como backend Python 3")
        self.assertIn((py, ('json',)), gee_bridge._MODULE_CHECK_CACHE)

    @unittest.skipUnless(_paths.qgis_python(), "QGIS 3.x nao encontrado")
    def test_find_python3_gdal(self):
        gee_bridge._FOUND_PYTHON3_GDAL = None
        py = gee_bridge.find_python3_gdal()
        self.assertTrue(gee_bridge.python_has_modules(py, ['osgeo.gdal', 'numpy']), py)


class BackendCommandTest(unittest.TestCase):
    """Chamada real Py2 -> Py3 pelo protocolo --params-file (inclui caminho com acento)."""

    @unittest.skipUnless(_paths.qgis_python(), "QGIS 3.x nao encontrado")
    def test_xyz_estimate_roundtrip_with_accented_geojson(self):
        tmp = tempfile.mkdtemp(prefix=u'arcmagery_joão_'.encode(sys.getfilesystemencoding()))
        try:
            gj = os.path.join(tmp.decode(sys.getfilesystemencoding()), u'área_ção.geojson')
            with open(gj, 'w') as f:
                json.dump({'type': 'Polygon', 'coordinates': [[[-56.10, -15.62], [-56.09, -15.62],
                                                                [-56.09, -15.61], [-56.10, -15.62]]]}, f)
            res = gee_bridge.run_backend_cmd('xyz_estimate', {'zoom': 17, 'geojson_file': gj},
                                             python_exe=_paths.qgis_python())
            self.assertTrue(res.get('success'), res)
            self.assertEqual(res['tiles'], 20)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @unittest.skipUnless(_paths.qgis_python(), "QGIS 3.x nao encontrado")
    def test_backend_error_is_reported(self):
        res = gee_bridge.run_backend_cmd('stac_download', {'collection': 'X', 'item_id': 'Y'},
                                         python_exe=_paths.qgis_python())
        self.assertFalse(res.get('success'))
        self.assertIn('Filtro espacial', res.get('message', ''))


if __name__ == '__main__':
    unittest.main()
