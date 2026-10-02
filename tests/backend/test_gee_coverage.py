# -*- coding: utf-8 -*-
"""B-11: a busca do GEE listava cenas que so tocam a area pelo contorno publicado (aproximado), sem
nenhum pixel nela - ex.: Sentinel-2 na borda da faixa imageada (20260930T140711_..._T21LVD, 66% do
tile sem dado). O download saia todo NoData/zero e o health check recusava com o JSON inteiro na tela.
Agora a busca mede a cobertura no servidor, descarta < 0,5% e mostra a cobertura parcial."""
import unittest

import _paths

try:
    import gee_core
    HAS_EE = True
except Exception:  # earthengine-api ausente neste Python
    HAS_EE = False


class FakeColl(object):
    """Colecao do GEE de mentira: encadeia os filtros e devolve as features dadas no getInfo."""

    def __init__(self, features):
        self.features = features

    def __getattr__(self, name):          # filterDate, filterBounds, filter, sort, limit, select, map...
        return lambda *a, **k: self

    def getInfo(self):
        return {'features': self.features}


def feature(name, cov, cloud=1.0):
    props = {'system:time_start': 1790000000000, 'CLOUDY_PIXEL_PERCENTAGE': cloud, 'MGRS_TILE': '21LVD'}
    if cov is not None:
        props[gee_core.AOI_COVERAGE_PROP] = cov
    return {'id': 'COPERNICUS/S2_SR_HARMONIZED/' + name, 'properties': props}


@unittest.skipUnless(HAS_EE, 'earthengine-api indisponivel neste Python')
class SearchCoverageTest(unittest.TestCase):
    def setUp(self):
        self.saved = {}
        self.feats = [feature('vazia', 0.0), feature('quase_vazia', 0.3), feature('borda', 21.04),
                      feature('cheia', 100.0), feature('sem_medida', None)]
        self._patch(gee_core, 'get_image_collection', lambda s: FakeColl(self.feats))
        self._patch(gee_core, 'with_aoi_coverage', lambda c, aoi: c)
        self._patch(gee_core.ee.Geometry, 'BBox', staticmethod(lambda *a: 'AOI'))

    def tearDown(self):
        for (obj, name), v in self.saved.items():
            setattr(obj, name, v)

    def _patch(self, obj, name, value):
        self.saved.setdefault((obj, name), getattr(obj, name))
        setattr(obj, name, value)

    def search(self):
        return gee_core.search_collection('S2', '01/01/2026', '02/10/2026', bbox=[-57.51, -14.69, -57.48, -14.67])

    def test_scenes_without_pixels_in_the_area_are_dropped(self):
        got = dict((r['name'], r['coverage_pct']) for r in self.search())
        self.assertEqual(got, {'borda': 21.0, 'cheia': 100.0, 'sem_medida': None})

    def test_measure_failure_still_lists_the_scenes(self):
        def boom(c, aoi):
            raise RuntimeError('Computation timed out')
        self._patch(gee_core, 'with_aoi_coverage', boom)
        self.feats = [feature('a', None), feature('b', None)]
        self.assertEqual([r['name'] for r in self.search()], ['a', 'b'])


@unittest.skipUnless(HAS_EE, 'earthengine-api indisponivel neste Python')
class HealthCheckMessageTest(unittest.TestCase):
    def test_empty_raster_explains_and_hides_the_json(self):
        diag = {'failures': [u'Raster vazio: todas as bandas contêm valor constante zero (0.0)'],
                'dimensions': {'width': 348, 'height': 233}, 'expected_bands': ['B11', 'B8', 'B2'],
                'geotransform': [-57.514905560337596, 8.98e-05, 0.0, -14.666254654648956, 0.0, -8.98e-05],
                'bands': [{'band': 1, 'min': 0.0}]}
        ex = gee_core.RasterHealthCheckError(u'Falha no Health Check pós-processamento: ' + diag['failures'][0], diag)
        msg = gee_core.health_check_user_message(ex)
        self.assertIn(u'não tem pixels nesta área', msg)
        self.assertIn(u'348 x 233 px', msg)
        self.assertIn(u'-57.514906, -14.666255', msg)
        self.assertIn(u'B11, B8, B2', msg)
        self.assertNotIn(u'"bands"', msg)
        self.assertIn(u'"bands"', str(ex))           # o JSON completo continua no log (stderr)

    def test_other_failures_have_no_empty_scene_hint(self):
        ex = gee_core.RasterHealthCheckError(u'Contagem de bandas divergente', {'failures': [u'Contagem de bandas divergente']})
        self.assertNotIn(u'não tem pixels', gee_core.health_check_user_message(ex))


@unittest.skipUnless(HAS_EE and _paths.LIVE and _paths.GEE_PROJECT,
                     "defina ARCMAGERY_LIVE=1 e ARCMAGERY_GEE_PROJECT=<id> para o teste no Earth Engine")
class CoverageLiveTest(unittest.TestCase):
    """Area do relato (57°29'55"W 14°40'34"S), tile 21LVD."""
    AOI = [-57.514905560, -14.687185401, -57.483644188, -14.666254655]

    def test_reported_area(self):
        gee_core.ee.Initialize(project=_paths.GEE_PROJECT)
        res = gee_core.search_collection('S2', '28/09/2026', '30/09/2026', bbox=self.AOI)
        cov = dict((r['name'], r['coverage_pct']) for r in res)
        self.assertNotIn('20260930T140711_20260930T141500_T21LVD', cov)          # 0 pixel na area
        self.assertEqual(cov.get('20260929T140111_20260929T140105_T21LVD'), 100.0)

    def test_partial_scene_is_close_to_the_exact_count(self):
        ee = gee_core.ee
        ee.Initialize(project=_paths.GEE_PROJECT)
        aoi = ee.Geometry.BBox(*self.AOI)
        iid = 'COPERNICUS/S2_SR_HARMONIZED/20260922T141101_20260922T141059_T21LVD'
        measured = ee.ImageCollection([ee.Image(iid)])
        measured = gee_core.with_aoi_coverage(measured, aoi).first().get(gee_core.AOI_COVERAGE_PROP).getInfo()
        n = ee.Image(iid).select('B2').reduceRegion(ee.Reducer.count(), aoi, 10, crs='EPSG:4326').get('B2')
        t = ee.Image.constant(1).reduceRegion(ee.Reducer.count(), aoi, 10, crs='EPSG:4326').get('constant')
        exact = 100.0 * ee.Number(n).divide(t).getInfo()
        self.assertAlmostEqual(measured, exact, delta=3.0)


if __name__ == '__main__':
    unittest.main()
