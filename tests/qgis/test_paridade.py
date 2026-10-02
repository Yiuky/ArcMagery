# -*- coding: utf-8 -*-
"""
Paridade QMagery x ArcMagery: catálogos, parâmetros enviados ao backend e linhas da tabela.

O QMagery não importa os módulos do ArcMagery (eles dependem da ponte Python 2.7); este teste importa os
dois no Python 3 e compara. Se um catálogo mudar no ArcMagery, este teste aponta o que atualizar em
qgis_plugin/qmagery/core/catalog_constants.py ou sources.py.
"""
import ast
import io
import os
import re
import sys
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import _paths  # noqa: E402

if _paths.INSTALL not in sys.path:
    sys.path.insert(0, _paths.INSTALL)

import arcmagery_gehist as am_gehist  # noqa: E402
import arcmagery_inpe as am_inpe  # noqa: E402
import arcmagery_spot as am_spot  # noqa: E402
import arcmagery_wayback as am_wayback  # noqa: E402
import gee_bridge  # noqa: E402
from qmagery.core import catalog_constants as cat  # noqa: E402
from qmagery.core import sources  # noqa: E402

BBOX = [-56.10, -15.61, -56.08, -15.59]


class Catalogos(unittest.TestCase):

    def test_composicoes_do_gee(self):
        for sensor in ('S2', 'L8', 'L7', 'L5', 'L4', 'L3', 'L2', 'L1'):
            ours = [(c[0], c[2]) for c in cat.GEE_COMPOSITIONS[sensor]]
            theirs = [(k, list(v.get('bands') or [])) for k, v in gee_bridge.COMPOSITIONS[sensor].items()]
            self.assertEqual(ours, theirs, msg='composições do %s divergem do gee_bridge' % sensor)

    def test_sensores_do_gee(self):
        src = io.open(os.path.join(_paths.INSTALL, 'gee_gui.py'), encoding='utf-8').read()
        for _label, code in cat.GEE_SENSOR_DISPLAY:
            self.assertIn("'%s'" % code, src)

    def test_inpe(self):
        self.assertEqual([v for _l, v in cat.INPE_SENSOR_DISPLAY], [v for _l, v in am_inpe.INPE_SENSOR_DISPLAY])
        for _label, sensor in cat.INPE_SENSOR_DISPLAY:
            self.assertEqual([c for c, _l in sources.compositions_for('inpe', sensor)], am_inpe.modes_for(sensor),
                             msg=sensor)

    def test_spot(self):
        self.assertEqual([(g[1], g[2], g[3]) for g in cat.SPOT_GROUPS], [(g[1], g[2], g[3]) for g in am_spot._GROUPS])
        self.assertEqual([p[0] for p in cat.SPOT_PRODUCTS], [p[0] for p in am_spot.PRODUCTS])
        for _label, sensor in cat.SPOT_SENSOR_DISPLAY:
            self.assertEqual(cat.spot_modes_for(sensor), am_spot.modes_for(sensor))
        self.assertEqual(cat.GEODES_PORTAL, am_spot.GEODES_PORTAL)

    def test_sensores_de_tiles(self):
        self.assertEqual([v for _l, v in cat.GEHIST_SENSOR_DISPLAY], [v for _l, v in am_gehist.GEHIST_SENSOR_DISPLAY])
        self.assertEqual([v for _l, v in cat.WAYBACK_SENSOR_DISPLAY], [v for _l, v in am_wayback.WAYBACK_SENSOR_DISPLAY])

    def test_provedores_xyz_existem_no_backend(self):
        import xyz_core
        for _label, code, max_z, _tos, _url in cat.XYZ_PROVIDERS:
            self.assertIn(code, xyz_core.PROVIDERS)
            self.assertEqual(max_z, xyz_core.PROVIDERS[code]['max_zoom'], msg=code)

    def test_formula_igual_ao_backend(self):
        """sources.is_math_expr é cópia de gee_core.is_math_expr (que não dá para importar sem o 'ee')."""
        tree = ast.parse(io.open(os.path.join(_paths.BACKEND, 'gee_core.py'), encoding='utf-8').read())
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'is_math_expr')
        ns = {'re': re}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), 'gee_core', 'exec'), ns)
        for text in ('B8-B4', 'B3-B5', 'B3-B5, B7', '(B8-B4)/(B8+B4)', 'SR_B5,SR_B4,SR_B3', 'sqrt(B4)', 'B4^2',
                     '[B2, B3]', 'NDVI-B4', ''):
            self.assertEqual(sources.is_math_expr(text), ns['is_math_expr'](text), msg=text)


class ParametrosIguaisAoArcMagery(unittest.TestCase):
    """O mesmo pedido no ArcMagery e no QMagery chega igual ao backend (fora 'workers' e a formatação do bbox)."""

    IGNORE = {'workers', 'bbox'}

    def capture(self, module, fn, *args, **kwargs):
        calls = []
        original = module.gee_bridge.run_backend_cmd
        module.gee_bridge.run_backend_cmd = lambda cmd, params, **k: calls.append((cmd, dict(params))) or \
            {'success': True, 'images': [], 'items': [], 'dates': [], 'versions': []}
        try:
            getattr(module, fn)(*args, **kwargs)
        finally:
            module.gee_bridge.run_backend_cmd = original
        return calls[0]

    def same(self, theirs, ours):
        (c1, p1), (c2, p2, _t) = theirs, ours
        self.assertEqual(c1, c2)
        clean = lambda p: dict((k, v) for k, v in p.items() if k not in self.IGNORE and v is not None)
        self.assertEqual(clean(p1), clean(p2))
        self.assertEqual('bbox' in p1, 'bbox' in p2)

    def test_inpe(self):
        s = 'INPE:CB4A-WPM-L4-DN-1'
        self.same(self.capture(am_inpe, 'search', s, '2024-01-01', '2024-12-31', bbox=BBOX),
                  sources.search_request('inpe', s, '2024-01-01', '2024-12-31', bbox=BBOX))
        row = {'id': 'CBERS_X', 'collection': 'CB4A-WPM-L4-DN-1'}
        self.same(self.capture(am_inpe, 'download', 'CBERS_X', s, 'false', 'o.tif', bbox=BBOX),
                  sources.download_request('inpe', s, row, 'false', 'o.tif', bbox=BBOX))

    def test_spot(self):
        for _label, s in cat.SPOT_SENSOR_DISPLAY:
            self.same(self.capture(am_spot, 'search', s, '1986-01-01', '2015-12-31', bbox=BBOX, max_images=500),
                      sources.search_request('spot', s, '1986-01-01', '2015-12-31', bbox=BBOX))
        original = am_spot.load_api_key
        am_spot.load_api_key = lambda: 'CHAVE'
        try:
            theirs = self.capture(am_spot, 'download', 'S1', 'SPOT:5-MS', 'swir', 'o.tif', bbox=BBOX)
        finally:
            am_spot.load_api_key = original
        self.same(theirs, sources.download_request('spot', 'SPOT:5-MS', {'id': 'S1'}, 'swir', 'o.tif', bbox=BBOX,
                                                   api_key='CHAVE'))

    def test_google_earth_historico(self):
        for s in ('GEH:ALL', 'GEH:18'):
            self.same(self.capture(am_gehist, 'search', s, None, None, bbox=BBOX),
                      sources.search_request('gehist', s, None, None, bbox=BBOX))
        d = {'date': '2025-02-22', 'zoom': 19, 'coverage_pct': 100.0}
        ours = sources.gehist_row(d)
        theirs = am_gehist.date_to_row(d)
        self.assertEqual((ours['id'], ours['zoom']), (theirs['id'], theirs['zoom']))
        c1, p1 = self.capture(am_gehist, 'download', theirs['id'], 'GEH:ALL', 'o.tif', bbox=BBOX)
        c2, p2, _t = sources.download_request('gehist', 'GEH:ALL', ours, 'rgb', 'o.tif', bbox=BBOX)
        self.assertEqual((c1, p1['zoom'], p1['date']), (c2, p2['zoom'], p2['date']))

    def test_wayback(self):
        for s in ('EWB:ALL', 'EWB:17'):
            self.same(self.capture(am_wayback, 'search', s, None, None, bbox=BBOX),
                      sources.search_request('wayback', s, None, None, bbox=BBOX))
        v = {'capture_date': '2025-09-10', 'release_date': '2026-05-28', 'release_num': 10842, 'zoom': 17}
        ours, theirs = sources.wayback_row(v), am_wayback.version_to_row(v)
        self.assertEqual((ours['id'], ours['release_num']), (theirs['id'], theirs['release_num']))
        c1, p1 = self.capture(am_wayback, 'download', theirs['id'], 'EWB:ALL', 'o.tif', bbox=BBOX)
        c2, p2, _t = sources.download_request('wayback', 'EWB:ALL', ours, 'rgb', 'o.tif', bbox=BBOX)
        self.assertEqual(c1, c2)
        for k in ('zoom', 'provider', 'wayback_release', 'compression', 'footprints'):
            self.assertEqual(p1.get(k), p2.get(k), msg=k)


if __name__ == '__main__':
    unittest.main()
