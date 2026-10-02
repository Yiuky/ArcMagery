# -*- coding: utf-8 -*-
"""
TODAS as fontes, com a rede, do jeito que a janela do QMagery faz (mesmos parâmetros, core/sources.py):
busca de cada sensor/coleção/zoom/provedor, download de cada produto e carregamento no QGIS.

Cada imagem baixada é conferida: GeoTIFF com pixels válidos, camada válida no QGIS com a simbologia
esperada e extensão SOBRE a área pedida (pega erro de georreferência). O backend é o mesmo do ArcMagery,
então isto cobre as duas aplicações (a carga no ArcMap em si continua no checklist V do BACKLOG).

Liga com ARCMAGERY_LIVE=1 (leva ~15-25 min). Opções:
    ARCMAGERY_LIVE_FULL=1   todas as composições do GEE (senão: 1 por tipo — RGB, multibanda, índice,
                            bandas e fórmula digitadas)
    ARCMAGERY_SPOT_QUOTA=1  baixa SPOT fora do cache (gasta a cota do GEODES); senão só cenas em cache
    ARCMAGERY_LIVE_ONLY=gee,inpe,spot,gehist,wayback,xyz   só algumas fontes
    ARCMAGERY_LIVE_KEEP=<pasta>  guarda os GeoTIFFs e o manifesto.json, que tests/arcmap/test_carga_ao_vivo.py
                            carrega no ArcMap (mesmas funções do load_into_toc)
Rode com o Python do QGIS para conferir a carga:
    set ARCMAGERY_LIVE=1 && "C:\\Program Files\\QGIS 3.xx\\bin\\python-qgis-ltr.bat" tests\\qgis\\test_ao_vivo.py
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import _paths  # noqa: E402
from qmagery.core import catalog_constants as cat  # noqa: E402
from qmagery.core import sources  # noqa: E402
from qmagery.core.backend_runner import run_sync  # noqa: E402

FULL = os.environ.get('ARCMAGERY_LIVE_FULL') == '1'
SPOT_QUOTA = os.environ.get('ARCMAGERY_SPOT_QUOTA') == '1'
ONLY = set(filter(None, os.environ.get('ARCMAGERY_LIVE_ONLY', '').split(',')))

# ~1 x 1 km em Cuiabá (MT): todas as coleções do INPE, os Landsat, o Sentinel-2 e o SPOT têm cenas aqui
BBOX = [-56.095, -15.605, -56.085, -15.595]
# o mosaico da Paraíba só cobre a Paraíba (João Pessoa)
BBOX_BY_COLLECTION = {'mosaic-cbers4a-paraiba-3m-1': [-34.885, -7.125, -34.875, -7.115]}

GEE_PERIODS = {'S2': ('2024-06-01', '2024-09-30'), 'L8': ('2023-06-01', '2023-09-30'),
               'L7': ('2002-06-01', '2002-09-30'), 'L5': ('2009-06-01', '2009-09-30'),
               'L4': ('1988-01-01', '1992-12-31'), 'L3': ('1978-01-01', '1983-12-31'),
               'L2': ('1975-01-01', '1981-12-31'), 'L1': ('1972-08-01', '1977-12-31')}
GEE_CUSTOM = {'S2': ('B8,B4,B3', '(B8-B4)/(B8+B4)'), 'L8': ('SR_B5,SR_B4,SR_B3', '(SR_B5-SR_B4)/(SR_B5+SR_B4)'),
              'L7': ('SR_B4,SR_B3,SR_B2', '(SR_B4-SR_B3)/(SR_B4+SR_B3)'),
              'L5': ('SR_B4,SR_B3,SR_B2', '(SR_B4-SR_B3)/(SR_B4+SR_B3)'),
              'L4': ('SR_B4,SR_B3,SR_B2', '(SR_B4-SR_B3)/(SR_B4+SR_B3)'),
              'L3': ('B7,B5,B4', '(B7-B5)/(B7+B5)'), 'L2': ('B7,B5,B4', '(B7-B5)/(B7+B5)'),
              'L1': ('B7,B5,B4', '(B7-B5)/(B7+B5)')}

REPORT = []
MANIFEST = []
KEEP = os.environ.get('ARCMAGERY_LIVE_KEEP')


def wanted(source):
    return not ONLY or source in ONLY


def period_of(meta_period):
    """'29/12/2019 até o Presente' / '23/02/1986 a 29/03/2015' -> (início ISO, fim ISO)."""
    import re
    dates = re.findall(r'(\d{2})/(\d{2})/(\d{4})', meta_period or '')
    iso = ['%s-%s-%s' % (y, m, d) for d, m, y in dates]
    start = iso[0] if iso else '2000-01-01'
    end = iso[1] if len(iso) > 1 else time.strftime('%Y-%m-%d')
    return start, end


@unittest.skipUnless(_paths.LIVE, 'defina ARCMAGERY_LIVE=1 (usa a internet; ~15-25 min)')
class TodasAsFontes(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.out = KEEP or tempfile.mkdtemp(prefix='qmagery_live_')
        if KEEP:
            os.makedirs(KEEP, exist_ok=True)
        cls.project = _paths.GEE_PROJECT or _paths.real_user_file('gee_config.json').get('project')
        cls.api_key = _paths.real_user_file('geodes_config.json').get('api_key') or os.environ.get('GEODES_API_KEY')
        cls.app = _paths.ensure_qgis_app() if _paths.HAS_PYQGIS else None

    @classmethod
    def tearDownClass(cls):
        if KEEP:
            with open(os.path.join(KEEP, 'manifesto.json'), 'w', encoding='utf-8') as f:
                json.dump(MANIFEST, f, ensure_ascii=False, indent=1)
        else:
            shutil.rmtree(cls.out, ignore_errors=True)
        if REPORT:
            ok = sum(1 for r in REPORT if r[3] == 'ok')
            print('\n%-8s %-34s %-14s %-6s %s' % ('fonte', 'sensor/coleção', 'produto', 'status', 'detalhe'))
            for r in REPORT:
                print('%-8s %-34s %-14s %-6s %s' % r)
            print('%d de %d casos OK' % (ok, len(REPORT)))

    # ------------------------------------------------------------------ utilidades
    def run_cmd(self, request):
        cmd, params, timeout = request
        return run_sync(cmd, params, timeout=max(timeout, 300))

    def out_tif(self, *parts):
        return os.path.join(self.out, sources.safe_name('_'.join(str(p) for p in parts), 120) + '.tif')

    def check_raster(self, path, bbox, source, sensor, comp, res=None, expect_bands=None):
        """GeoTIFF válido, com imagem, sobre a área; e, com PyQGIS, a camada carregada como na janela."""
        from osgeo import gdal, osr
        self.assertTrue(path and os.path.isfile(path), msg='GeoTIFF não gerado: %s' % path)
        ds = gdal.Open(path)
        self.assertIsNotNone(ds)
        if expect_bands:
            self.assertIn(ds.RasterCount, expect_bands, msg='bandas: %d' % ds.RasterCount)
        b = ds.GetRasterBand(1)
        mn, mx = b.ComputeRasterMinMax(False)
        self.assertIsNotNone(mx, msg='recorte sem pixels válidos')
        gt = ds.GetGeoTransform()
        srs = osr.SpatialReference(wkt=ds.GetProjection())
        srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        wgs = osr.SpatialReference()
        wgs.ImportFromEPSG(4326)
        wgs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        ct = osr.CoordinateTransformation(srs, wgs)
        cx, cy = gt[0] + gt[1] * ds.RasterXSize / 2.0, gt[3] + gt[5] * ds.RasterYSize / 2.0
        lon, lat = ct.TransformPoint(cx, cy)[:2]
        tol = 0.05   # ~5 km: o centro do recorte tem de cair na área (erro de georreferência é maior)
        self.assertTrue(bbox[0] - tol <= lon <= bbox[2] + tol and bbox[1] - tol <= lat <= bbox[3] + tol,
                        msg='centro do recorte fora da área: %.4f, %.4f' % (lon, lat))
        ds = None
        detail = '%s' % os.path.basename(path)
        rgb = (res or {}).get('rgb_bands')
        if source in ('gehist', 'wayback', 'xyz'):
            rgb = [0, 1, 2]
        MANIFEST.append({'path': path, 'source': source, 'sensor': sensor, 'comp': comp,
                         'custom_bands': (res or {}).get('_custom'), 'rgb_bands': rgb, 'bbox': bbox})
        if self.app is not None:
            from qgis.core import QgsProject
            from qmagery.core.qgis_layer import add_raster_layer, apply_style
            layer = add_raster_layer(path, os.path.basename(path), group_name='teste')
            if source == 'gee':
                kind, bands = sources.gee_style(sensor, comp, res and res.get('_custom'))
            elif res and res.get('rgb_bands'):
                kind, bands = 'rgb', res['rgb_bands']
            else:
                kind, bands = None, None
            self.assertTrue(apply_style(layer, kind, bands))
            self.assertTrue(layer.isValid())
            rtype = layer.renderer().type()
            if layer.bandCount() == 1:
                self.assertIn(rtype, ('singlebandgray', 'singlebandpseudocolor'))
            else:
                self.assertEqual(rtype, 'multibandcolor')
            detail += ' | QGIS %s' % rtype
            QgsProject.instance().removeMapLayer(layer.id())
        return detail

    def record(self, source, sensor, comp, fn):
        t = time.time()
        try:
            detail = fn()
            REPORT.append((source, sensor[:34], str(comp)[:14], 'ok', '%s (%.0fs)' % (detail or '', time.time() - t)))
        except unittest.SkipTest as e:
            REPORT.append((source, sensor[:34], str(comp)[:14], 'pulo', str(e)[:90]))
            raise
        except Exception as e:
            REPORT.append((source, sensor[:34], str(comp)[:14], 'FALHA', str(e).replace('\n', ' ')[:140]))
            raise

    def best(self, rows, key='cloud_pct', reverse=False):
        def k(r):
            v = r.get(key)
            return (v is None, v if not reverse else -(v or 0))
        return sorted(rows, key=k)[0]

    # ------------------------------------------------------------------ Google Earth Engine
    def test_gee_todos_os_sensores(self):
        if not wanted('gee'):
            self.skipTest('fora de ARCMAGERY_LIVE_ONLY')
        if not self.project:
            self.skipTest('sem projeto do GEE configurado')
        for _label, sensor in cat.GEE_SENSOR_DISPLAY:
            start, end = GEE_PERIODS[sensor]
            req = sources.search_request('gee', sensor, start, end, bbox=BBOX, project=self.project)
            with self.subTest(fonte='gee', sensor=sensor, etapa='busca'):
                res = self.run_cmd(req)
                rows = sources.rows_from_result('gee', sensor, res)
                self.assertTrue(rows, msg='%s: nenhuma cena em %s..%s' % (sensor, start, end))
            if not rows:
                continue
            row = self.best(rows)
            comps = cat.GEE_COMPOSITIONS[sensor]
            if not FULL:
                seen, pick = set(), []
                for c in comps:
                    if c[3] not in seen:
                        seen.add(c[3])
                        pick.append(c)
                comps = pick
            for code, _lbl, _bands, kind in comps:
                custom = {'bands': GEE_CUSTOM[sensor][0], 'math': GEE_CUSTOM[sensor][1]}.get(kind)
                with self.subTest(fonte='gee', sensor=sensor, comp=code):
                    def go():
                        out = self.out_tif(sensor, row['c_name'], code)
                        r = self.run_cmd(sources.download_request('gee', sensor, row, code, out, bbox=BBOX,
                                                                  project=self.project, custom_bands=custom))
                        r['_custom'] = custom
                        return self.check_raster(r.get('file'), BBOX, 'gee', sensor, code, r)
                    self.record('gee', sensor, code, go)
            with self.subTest(fonte='gee', sensor=sensor, etapa='miniatura'):
                png = os.path.join(self.out, 'thumb_gee_%s.png' % sensor)
                self.record('gee', sensor, 'miniatura', lambda: self.run_cmd(sources.thumb_request(
                    'gee', sensor, row, comps[0][0], png, bbox=BBOX, project=self.project)).get('file'))

    # ------------------------------------------------------------------ INPE
    def test_inpe_todas_as_colecoes_e_produtos(self):
        if not wanted('inpe'):
            self.skipTest('fora de ARCMAGERY_LIVE_ONLY')
        for _label, sensor in cat.INPE_SENSOR_DISPLAY:
            cid = sources.inpe_collection(sensor)
            bbox = BBOX_BY_COLLECTION.get(cid, BBOX)
            start, end = period_of(sources.sensor_metadata('inpe', sensor).get('period_display'))
            with self.subTest(fonte='inpe', colecao=cid, etapa='busca'):
                res = self.run_cmd(sources.search_request('inpe', sensor, start, end, bbox=bbox))
                rows = sources.rows_from_result('inpe', sensor, res)
                self.assertTrue(rows, msg='%s: nenhuma cena cobrindo a área em %s..%s' % (cid, start, end))
                for r in rows:
                    # depois da correção do Nível 2, nenhuma cena listada pode estar fora da faixa imageada
                    self.assertGreater(r.get('coverage_pct') or 0, 0, msg='%s listada sem cobertura' % r['id'])
            if not rows:
                REPORT.append(('inpe', cid, '-', 'FALHA', 'nenhuma cena'))
                continue
            row = self.best(rows, 'coverage_pct', reverse=True)
            for mode, _lbl in sources.compositions_for('inpe', sensor):
                with self.subTest(fonte='inpe', colecao=cid, modo=mode):
                    def go():
                        out = self.out_tif(row['id'], mode)
                        r = self.run_cmd(sources.download_request('inpe', sensor, row, mode, out, bbox=bbox))
                        nb = {'pan': (1,), 'ndvi': (1,), 'evi': (1,)}.get(mode)
                        return self.check_raster(r.get('file'), bbox, 'inpe', sensor, mode, r, nb)
                    self.record('inpe', cid, mode, go)
            with self.subTest(fonte='inpe', colecao=cid, etapa='miniatura'):
                png = os.path.join(self.out, 'thumb_%s.png' % cid)
                self.record('inpe', cid, 'miniatura', lambda: self.run_cmd(sources.thumb_request(
                    'inpe', sensor, row, 'rgb', png, bbox=bbox)).get('file'))

    # ------------------------------------------------------------------ SPOT
    def test_spot_todos_os_grupos(self):
        if not wanted('spot'):
            self.skipTest('fora de ARCMAGERY_LIVE_ONLY')
        cache = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'ArcMagery', 'spot_cache')
        cached = set(os.path.splitext(n)[0] for n in os.listdir(cache)) if os.path.isdir(cache) else set()
        downloaded = 0
        for _label, sensor in cat.SPOT_SENSOR_DISPLAY:
            g = sources.spot_group(sensor)
            with self.subTest(fonte='spot', grupo=sensor, etapa='busca'):
                res = self.run_cmd(sources.search_request('spot', sensor, '1986-01-01', '2015-12-31', bbox=BBOX))
                rows = sources.rows_from_result('spot', sensor, res)
                self.assertTrue(rows, msg='%s: nenhuma cena' % sensor)
                for r in rows:
                    sat = (r.get('platform') or '').replace('SPOT', '').strip()
                    if g[2]:
                        self.assertIn(sat, g[2].split(','), msg='%s veio no grupo %s' % (r['id'], sensor))
                    self.assertEqual(r.get('is_pan'), g[3] == 'pan', msg='%s no grupo %s' % (r['id'], sensor))
                REPORT.append(('spot', sensor, 'busca', 'ok', '%d cenas' % len(rows)))
            if not rows or not self.api_key:
                continue
            for row in rows:
                if not (SPOT_QUOTA or row['id'] in cached or any(row['id'] in c for c in cached)):
                    continue
                for mode, _lbl in sources.compositions_for('spot', sensor):
                    if mode == 'swir' and '_S5' not in row['id'] and '_S4' not in row['id']:
                        continue
                    with self.subTest(fonte='spot', grupo=sensor, modo=mode):
                        def go(row=row, mode=mode):
                            out = self.out_tif(row['id'], mode)
                            r = self.run_cmd(sources.download_request('spot', sensor, row, mode, out, bbox=BBOX,
                                                                      api_key=self.api_key))
                            self.assertTrue((r.get('alignment') or {}).get('applied'), msg='sem alinhamento')
                            return self.check_raster(r.get('file'), BBOX, 'spot', sensor, mode, r)
                        self.record('spot', sensor, mode, go)
                        downloaded += 1
                break
        if not downloaded:
            REPORT.append(('spot', '-', 'download', 'pulo', 'nenhuma cena em cache nesta área '
                           '(ARCMAGERY_SPOT_QUOTA=1 baixa usando a cota)'))

    # ------------------------------------------------------------------ Google Earth histórico
    def test_google_earth_historico_todos_os_zooms(self):
        if not wanted('gehist'):
            self.skipTest('fora de ARCMAGERY_LIVE_ONLY')
        sensor = cat.GEHIST_PREFIX + 'ALL'
        res = self.run_cmd(sources.search_request('gehist', sensor, None, None, bbox=BBOX, workers=16))
        rows = sources.rows_from_result('gehist', sensor, res)
        self.assertTrue(rows)
        for zoom in (15, 16, 17, 18, 19, 20):
            zrows = [r for r in rows if r['zoom'] == zoom]
            with self.subTest(fonte='gehist', zoom=zoom):
                self.assertTrue(zrows, msg='nenhuma data no zoom %d' % zoom)
                row = self.best(zrows, 'coverage_pct', reverse=True)

                def go(row=row):
                    r = self.run_cmd(sources.download_request('gehist', sensor, row, 'rgb', self.out_tif(row['id']),
                                                              bbox=BBOX, workers=16))
                    return self.check_raster(r.get('file'), BBOX, 'gehist', sensor, 'rgb', r, (3,))
                self.record('gehist', 'zoom %d' % zoom, row['date'], go)
        with self.subTest(fonte='gehist', etapa='miniatura'):
            png = os.path.join(self.out, 'thumb_gehist.png')
            self.record('gehist', 'zoom %d' % rows[0]['zoom'], 'miniatura', lambda: self.run_cmd(
                sources.thumb_request('gehist', sensor, rows[0], 'rgb', png, bbox=BBOX)).get('file'))

    # ------------------------------------------------------------------ Esri Wayback
    def test_wayback_todos_os_zooms(self):
        if not wanted('wayback'):
            self.skipTest('fora de ARCMAGERY_LIVE_ONLY')
        sensor = cat.WAYBACK_PREFIX + 'ALL'
        res = self.run_cmd(sources.search_request('wayback', sensor, None, None, bbox=BBOX))
        rows = sources.rows_from_result('wayback', sensor, res)
        self.assertTrue(rows)
        for zoom in (15, 16, 17, 18, 19):
            zrows = [r for r in rows if r['zoom'] == zoom]
            with self.subTest(fonte='wayback', zoom=zoom):
                self.assertTrue(zrows, msg='nenhuma versão no zoom %d' % zoom)
                row = zrows[0]

                def go(row=row):
                    r = self.run_cmd(sources.download_request('wayback', sensor, row, 'rgb', self.out_tif(row['id']),
                                                              bbox=BBOX, workers=16))
                    return self.check_raster(r.get('file'), BBOX, 'wayback', sensor, 'rgb', r, (3, 4))
                self.record('wayback', 'zoom %d' % zoom, row['date'], go)
        with self.subTest(fonte='wayback', etapa='miniatura'):
            png = os.path.join(self.out, 'thumb_wayback.png')
            self.record('wayback', 'zoom %d' % rows[0]['zoom'], 'miniatura', lambda: self.run_cmd(
                sources.thumb_request('wayback', sensor, rows[0], 'rgb', png, bbox=BBOX)).get('file'))

    # ------------------------------------------------------------------ Google Earth / XYZ
    def test_xyz_todos_os_provedores(self):
        if not wanted('xyz'):
            self.skipTest('fora de ARCMAGERY_LIVE_ONLY')
        for label, code, _max_z, _tos, url in cat.XYZ_PROVIDERS:
            with self.subTest(fonte='xyz', provedor=code):
                def go(code=code):
                    p = dict(sources.area_params(BBOX), provider=code, zoom=17, out=self.out_tif('xyz', code),
                             workers=16)
                    r = self.run_cmd(('xyz_download', p, 600))
                    return self.check_raster(r.get('file'), BBOX, 'xyz', code, 'rgb', r, (3, 4))
                self.record('xyz', code, 'mosaico z17', go)
            if url and self.app is not None:
                with self.subTest(fonte='xyz', provedor=code, etapa='camada ao vivo'):
                    from qgis.core import QgsProject
                    from qmagery.core.qgis_layer import add_xyz_tile_layer
                    layer = add_xyz_tile_layer(url, label, max_zoom=_max_z)
                    self.assertTrue(layer.isValid())
                    source = layer.source()
                    self.assertIn('%7Bz%7D', source)
                    QgsProject.instance().removeMapLayer(layer.id())
                    REPORT.append(('xyz', code, 'camada XYZ', 'ok', source[:60]))


if __name__ == '__main__':
    unittest.main(verbosity=2)
