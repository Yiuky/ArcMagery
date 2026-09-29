# -*- coding: utf-8 -*-
"""Contrato CLI do backend com a ponte Python 2.7: --params-file JSON UTF-8 -> UMA linha JSON."""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

import _paths

RUN_GEE = os.path.join(_paths.BACKEND, 'run_gee.py')


def run_cli(params, timeout=120):
    fd, pf = tempfile.mkstemp(suffix='.json', prefix='gee_params_')
    os.close(fd)
    try:
        with io.open(pf, 'w', encoding='utf-8') as f:
            f.write(json.dumps(params, ensure_ascii=False))
        env = dict(os.environ, PYTHONIOENCODING='utf-8')
        env.pop('PYTHONPATH', None)
        proc = subprocess.run([sys.executable, RUN_GEE, params['command'], '--params-file=' + pf],
                              capture_output=True, timeout=timeout, env=env)
        lines = [l for l in proc.stdout.decode('utf-8').splitlines() if l.strip().startswith('{')]
        return proc.returncode, json.loads(lines[-1]), proc.stderr.decode('utf-8', 'replace')
    finally:
        os.remove(pf)


class CliTest(unittest.TestCase):
    def test_sources_info(self):
        code, data, _ = run_cli({'command': 'sources_info'})
        self.assertEqual(code, 0)
        self.assertTrue(data['success'])
        self.assertIn('google', data['providers'])
        self.assertIn('CB4A-WPM-L4-DN-1', data['collections'])

    def test_xyz_estimate_with_unicode_geojson_path(self):
        d = tempfile.mkdtemp(prefix=u'arcmagery_ção_')
        gj = os.path.join(d, u'área.geojson')
        with io.open(gj, 'w', encoding='utf-8') as f:
            json.dump({'type': 'Feature', 'geometry': {'type': 'Polygon', 'coordinates': [
                [[-56.10, -15.62], [-56.09, -15.62], [-56.09, -15.61], [-56.10, -15.61], [-56.10, -15.62]]]}}, f)
        code, data, _ = run_cli({'command': 'xyz_estimate', 'zoom': 17, 'geojson_file': gj})
        self.assertEqual(code, 0, data)
        self.assertEqual(data['tiles'], 20)

    def test_errors_are_json(self):
        code, data, _ = run_cli({'command': 'stac_download', 'collection': 'CB4A-WPM-L4-DN-1', 'item_id': 'x'})
        self.assertEqual(code, 1)
        self.assertFalse(data['success'])
        self.assertIn('Filtro espacial', data['message'])

    @unittest.skipUnless(_paths.HAS_GDAL and sys.platform == 'win32', "requer GDAL do QGIS no Windows")
    def test_gdal_loads_even_with_inherited_osgeo4w_root(self):
        """Regressao: o sitecustomize do QGIS pula o registro de <QGIS>\\bin quando OSGEO4W_ROOT
        ja existe no ambiente (herdado de outro Python do QGIS / shell OSGeo4W) -> '_gdal' nao
        carregava e CBERS/Google Earth falhavam. O backend registra o bin por conta propria."""
        fd, pf = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        with io.open(pf, 'w', encoding='utf-8') as f:
            f.write(u'{"command": "sources_info"}')
        env = dict(os.environ, OSGEO4W_ROOT=r'C:\nao\existe', PYTHONIOENCODING='utf-8')
        env.pop('PYTHONPATH', None)
        try:
            proc = subprocess.run([sys.executable, RUN_GEE, 'sources_info', '--params-file=' + pf],
                                  capture_output=True, timeout=120, env=env)
        finally:
            os.remove(pf)
        data = json.loads([l for l in proc.stdout.decode('utf-8').splitlines() if l.startswith('{')][-1])
        self.assertTrue(data['gdal'], proc.stderr.decode('utf-8', 'replace'))

    def test_source_commands_do_not_import_earthengine(self):
        code = ("import sys; sys.path.insert(0, %r); sys.modules['ee'] = None\n"
                "import run_gee\n"
                "assert 'gee_core' not in sys.modules\n"
                "print('ok')") % _paths.BACKEND
        out = subprocess.run([sys.executable, '-c', code], capture_output=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr.decode('utf-8', 'replace'))


if __name__ == '__main__':
    unittest.main()
