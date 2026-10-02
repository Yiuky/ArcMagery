# -*- coding: utf-8 -*-
"""
Regras das fontes do QMagery (core/sources.py) x backend: roda no CI, sem QGIS.

  * contrato: todo parâmetro que o QMagery envia é lido pelo comando do backend (os bugs da 1ª versão
    eram exatamente parâmetros ignorados: SPOT sem a chave e sem o filtro de satélite);
  * linhas da tabela a partir de respostas reais do backend (gravadas da rede em 2026-10-02).
"""
import inspect
import os
import re
import sys
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import _paths  # noqa: E402,F401
import run_gee  # noqa: E402
from qmagery.core import sources  # noqa: E402

BBOX = [-56.10, -15.61, -56.08, -15.59]
GEOJSON = os.path.join(_THIS_DIR, 'aoi_nao_lido.geojson')   # só o nome importa aqui

SAMPLE_ROWS = {
    'gee': {'id': 'COPERNICUS/S2_SR_HARMONIZED/20240828T135701_20240828T135924_T21LWC', 'date': '2024-08-28 14:06',
            'c_name': '20240828T135701_20240828T135924_T21LWC'},
    'inpe': {'id': 'CBERS_4A_WPM_20240717_217_132_L4', 'date': '2024-07-17', 'collection': 'CB4A-WPM-L4-DN-1',
             'thumbnail': 'https://x/t.png'},
    'spot': {'id': '010-011_S2_693-381-0_2008-05-08-13-58-21_HRV-2_X_DT_GU', 'date': '2008-05-08',
             'thumbnail': 'https://x/q.jpg', 'platform': 'SPOT2'},
    'gehist': {'id': 'GoogleEarth_20250222_z18', 'date': '2025-02-22', 'zoom': 18},
    'wayback': {'id': 'EsriWayback_20250910_r10842_z17', 'date': '2025-09-10', 'zoom': 17, 'release_num': 10842,
                'release_date': '2026-05-28'},
}


def backend_reads(fn):
    """Chaves do dicionário de parâmetros lidas pela função do backend."""
    src = inspect.getsource(fn)
    keys = set(re.findall(r"p(?:\.get\(|\[)'(\w+)'", src))
    if '_resolve_bbox(p)' in src:
        keys |= {'bbox', 'geojson_file'}
    if '_min_coverage(p)' in src:
        keys.add('min_coverage')
    return keys


class ContratoBackend(unittest.TestCase):

    def assert_accepted(self, cmd, params):
        if cmd in run_gee.SOURCE_COMMANDS:
            unread = set(params) - backend_reads(run_gee.SOURCE_COMMANDS[cmd]) - {'command'}
            self.assertEqual(unread, set(), msg='%s ignora %s' % (cmd, sorted(unread)))
        else:
            try:
                args = run_gee.build_parser().parse_args(run_gee.params_to_cli(cmd, params))
            except SystemExit:
                self.fail('argparse recusou %s %r' % (cmd, params))
            self.assertEqual(args.command, cmd)

    def test_busca_de_todas_as_fontes_e_sensores(self):
        for source in sources.SOURCES:
            for _label, sensor in sources.sensors_for(source):
                for area in ({'bbox': BBOX}, {'geojson_file': GEOJSON}):
                    cmd, params, timeout = sources.search_request(source, sensor, '2024-01-01', '2024-12-31',
                                                                  project='meu-projeto', workers=16, **area)
                    self.assert_accepted(cmd, params)
                    self.assertGreater(timeout, 0)

    def test_download_e_miniatura(self):
        for source in sources.SOURCES:
            sensor = sources.sensors_for(source)[0][1]
            for comp, _label in sources.compositions_for(source, sensor):
                row = SAMPLE_ROWS[source]
                cmd, params, _t = sources.download_request(
                    source, sensor, row, comp, r'C:\saida\x.tif', bbox=BBOX, project='p', api_key='k', workers=8,
                    scale=10, custom_bands='B8,B4,B3' if comp == 'CUSTOM_BANDS' else None)
                self.assert_accepted(cmd, params)
                cmd, params, _t = sources.thumb_request(source, sensor, row, comp, r'C:\t.png', bbox=BBOX, project='p')
                self.assert_accepted(cmd, params)

    def test_comandos_das_janelas_auxiliares(self):
        area = sources.area_params(BBOX)
        for cmd, params in (('xyz_estimate', dict(area, zoom=18)),
                            ('xyz_download', dict(area, provider='google', zoom=18, out='x.tif', crs='EPSG:4674',
                                                  workers=16)),
                            ('selfcheck', {'api_key': 'k'}), ('spot_check_key', {'api_key': 'k'}),
                            ('pylibs_install', {}), ('check', {'project': 'p'})):
            self.assert_accepted(cmd, params)

    def test_spot_envia_chave_satelites_e_tipo(self):
        cmd, p, _t = sources.search_request('spot', 'SPOT:5-PAN', '2002-01-01', '2015-12-31', bbox=BBOX)
        self.assertEqual((cmd, p['satellites'], p['kind']), ('spot_search', '5', 'pan'))
        cmd, p, _t = sources.search_request('spot', 'SPOT:MS', '1986-01-01', '2015-12-31', bbox=BBOX)
        self.assertEqual((p['satellites'], p['kind']), (None, 'ms'))
        cmd, p, _t = sources.download_request('spot', 'SPOT:5-MS', SAMPLE_ROWS['spot'], 'rgb', 'x.tif', bbox=BBOX,
                                              api_key='CHAVE')
        self.assertEqual((p['api_key'], p['mode']), ('CHAVE', 'false'))   # SPOT não tem cor natural

    def test_zoom_dos_sensores_de_tiles(self):
        _c, p, _t = sources.search_request('gehist', 'GEH:ALL', None, None, bbox=BBOX)
        self.assertEqual(p['zooms'], 'all')
        _c, p, _t = sources.search_request('wayback', 'EWB:19', None, None, bbox=BBOX)
        self.assertEqual(p['zoom'], 19)
        _c, p, _t = sources.download_request('gehist', 'GEH:ALL', dict(SAMPLE_ROWS['gehist'], zoom=20), 'rgb', 'x.tif',
                                             bbox=BBOX)
        self.assertEqual(p['zoom'], 20)   # no modo "todos os zooms" o zoom vem da linha

    def test_composicoes_do_landsat_nao_usam_as_do_sentinel(self):
        codes = [c for c, _l in sources.compositions_for('gee', 'L5')]
        self.assertIn('321', codes)
        self.assertNotIn('843', codes)
        self.assertNotIn('MB_10', codes)

    def test_aoi_tem_prioridade_sobre_a_extensao(self):
        self.assertEqual(sources.area_params(BBOX, 'a.geojson'), {'geojson_file': 'a.geojson'})
        self.assertEqual(sources.area_params(BBOX)['bbox'].count(','), 3)


class LinhasDaTabela(unittest.TestCase):

    def test_gee_nuvem_zero_aparece(self):
        res = {'images': [{'id': 'COPERNICUS/S2_SR_HARMONIZED/X_T21LWC', 'name': 'X_T21LWC', 'date': '2024-08-18 14:06',
                           'cloud_pct': 0.0, 'mgrs': '21LWC'},
                          {'id': 'LANDSAT/LT05/C02/T1_L2/LT05_226071_20090907', 'name': 'LT05_226071_20090907',
                           'date': '2009-09-07 13:35', 'cloud_pct': None, 'path': 226, 'row': 71}]}
        rows = sources.rows_from_result('gee', 'S2', res)
        self.assertEqual(rows[0]['c_cloud'], '0,0%')
        self.assertEqual(rows[1]['c_cloud'], 'n/d')
        self.assertEqual(rows[1]['c_detail'], '226/71')

    def test_inpe_spot_gehist_wayback(self):
        inpe = sources.rows_from_result('inpe', 'INPE:CB4A-WPM-L4-DN-1', {'items': [
            {'id': 'CBERS_4A_WPM_20240717_217_132_L4', 'date': '2024-07-17', 'cloud_cover': 25.0, 'coverage_pct': 40.0,
             'path_row': '217/132', 'collection': 'CB4A-WPM-L4-DN-1', 'thumbnail': 'https://x/t.png'}]})[0]
        self.assertEqual((inpe['c_cloud'], inpe['c_detail']), ('25%', '217/132 · 40% da área'))
        spot = sources.rows_from_result('spot', 'SPOT:MS', {'items': [
            {'id': 'S', 'date': '2008-05-08', 'cloud_cover': 1.0, 'coverage_pct': 100.0, 'platform': 'SPOT2',
             'res_m': 20.0, 'mode_label': 'XS 3 bandas', 'thumbnail': 'https://x/q.jpg'}]})[0]
        self.assertEqual(spot['c_detail'], 'SPOT2 · 20 m · XS 3 bandas · 100% da área')
        dates = {'dates': [{'date': '2025-09-29', 'zoom': 18, 'coverage_pct': 100.0, 'provider': 'Provedor 398'},
                           {'date': '2019-01-01', 'zoom': 18, 'coverage_pct': 37.0, 'estimated': True}]}
        rows = sources.rows_from_result('gehist', 'GEH:18', dates, '2020-01-01', '2026-12-31')
        self.assertEqual([r['id'] for r in rows], ['GoogleEarth_20250929_z18'])   # filtrada pelo período
        vers = {'versions': [{'capture_date': '2025-09-10', 'release_date': '2026-05-28', 'release_num': 10842,
                              'sensor_name': 'GeoEye-1 (GE01)', 'provider': 'Vantor', 'resolution_m': 0.46}]}
        w = sources.rows_from_result('wayback', 'EWB:17', vers)[0]
        self.assertEqual((w['id'], w['c_cloud'], w['release_num']),
                         ('EsriWayback_20250910_r10842_z17', 'versão 28/05/2026', 10842))

    def test_nomes_de_arquivo_e_camada(self):
        row = sources.gee_row({'id': 'COPERNICUS/S2_SR_HARMONIZED/20240828T135701_20240828T135924_T21LWC',
                               'name': '20240828T135701_20240828T135924_T21LWC', 'date': '2024-08-28 14:06'})
        self.assertEqual(sources.output_stem('gee', 'S2', row, 'NDVI'), 'S2_20240828T135701_20240828T135924_T21LWC_NDVI')
        self.assertEqual(sources.layer_name('gee', 'S2', row, '432'), 'S2 2024-08-28 T21LWC (432)')
        self.assertEqual(sources.safe_name(u'a b/c:d'), 'a_b_c_d')


class Simbologia(unittest.TestCase):

    def test_multibanda_exibida_em_cor_natural(self):
        self.assertEqual(sources.gee_style('S2', 'MB_10'), ('rgb', [2, 1, 0]))     # B4, B3, B2
        self.assertEqual(sources.gee_style('L5', 'MB_6'), ('rgb', [2, 1, 0]))      # SR_B3, SR_B2, SR_B1
        self.assertEqual(sources.gee_style('S2', '432'), ('rgb', [0, 1, 2]))
        self.assertEqual(sources.gee_style('S2', 'NDVI'), ('index', None))
        self.assertEqual(sources.gee_style('S2', 'CUSTOM_MATH', '(B8-B4)/(B8+B4)'), ('index', None))

    def test_formula_x_intervalo_de_bandas(self):
        self.assertTrue(sources.is_math_expr('B8-B4'))
        self.assertFalse(sources.is_math_expr('B3-B5, B7'))
        self.assertTrue(sources.is_math_expr('(B8-B4)/(B8+B4)'))
        self.assertFalse(sources.is_math_expr('SR_B5,SR_B4,SR_B3'))

    def test_limite_de_tamanho_do_gee(self):
        self.assertIsNone(sources.gee_size_check('S2', '432', BBOX))
        self.assertIn('3,5 GB', sources.gee_size_check('S2', 'MB_12', [-60, -20, -50, -10], scale=2))


if __name__ == '__main__':
    unittest.main()
