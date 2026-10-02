# -*- coding: utf-8 -*-
"""
Interface do QMagery com o PyQGIS (pulado no CI): botões, fila, substituir, AOI, cancelamento e encerramento.

O backend é simulado: BackendRunner.run grava (comando, parâmetros) e responde pelo sinal, como o real.
Os parâmetros em si são conferidos contra o backend em test_fontes.py; aqui vale o fluxo da janela.
"""
import os
import subprocess
import sys
import tempfile
import time
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import _paths  # noqa: E402

if _paths.HAS_PYQGIS:
    from qgis.core import (QgsCoordinateReferenceSystem, QgsFeature, QgsGeometry, QgsProject, QgsRasterLayer,  # noqa
                           QgsRectangle, QgsVectorLayer)
    from qgis.PyQt.QtCore import QDate, QObject, pyqtSignal
    from qgis.PyQt.QtWidgets import QDialog, QMessageBox

    class _Canvas(QObject):
        scaleChanged = pyqtSignal(float)

        def __init__(self):
            super().__init__()
            self._scale = 20000.0
            self.zoomed = None

        def extent(self):
            return QgsRectangle(-56.10, -15.61, -56.08, -15.59)

        def scale(self):
            return self._scale

        def zoomScale(self, s):
            self.zoomed = s
            self._scale = s

        def mapSettings(self):
            class S:
                def destinationCrs(self):
                    return QgsCoordinateReferenceSystem("EPSG:4326")
            return S()

    class _Iface:
        def __init__(self):
            self.canvas = _Canvas()

        def mainWindow(self):
            return None

        def mapCanvas(self):
            return self.canvas


GEE_RESULT = {'success': True, 'images': [
    {'id': 'COPERNICUS/S2_SR_HARMONIZED/A_T21LWC', 'name': 'A_T21LWC', 'date': '2024-08-28 14:06', 'cloud_pct': 0.1,
     'mgrs': '21LWC'},
    {'id': 'COPERNICUS/S2_SR_HARMONIZED/B_T21LWC', 'name': 'B_T21LWC', 'date': '2024-08-23 14:06', 'cloud_pct': 0.0,
     'mgrs': '21LWC'},
    {'id': 'COPERNICUS/S2_SR_HARMONIZED/C_T21LWC', 'name': 'C_T21LWC', 'date': '2024-08-18 14:06', 'cloud_pct': 2.0,
     'mgrs': '21LWC'}]}
SPOT_RESULT = {'success': True, 'items': [
    {'id': 'SPOTSCENE', 'date': '2008-05-08', 'cloud_cover': 1.0, 'coverage_pct': 100.0, 'platform': 'SPOT2',
     'res_m': 20.0, 'mode_label': 'XS', 'thumbnail': 'https://x/q.jpg'}]}


def _tiny_tif(path, bands=3):
    from osgeo import gdal, osr
    ds = gdal.GetDriverByName('GTiff').Create(path, 4, 4, bands, gdal.GDT_UInt16)
    ds.SetGeoTransform([-56.1, 0.005, 0, -15.59, 0, -0.005])
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    ds.SetProjection(srs.ExportToWkt())
    for b in range(1, bands + 1):
        ds.GetRasterBand(b).Fill(100 * b)
        ds.GetRasterBand(b).WriteRaster(0, 0, 1, 1, b'\x10\x00')
    ds = None
    return path


@unittest.skipUnless(_paths.HAS_PYQGIS and _paths.HAS_GDAL, "requer o PyQGIS (python-qgis-ltr.bat)")
class JanelaPrincipal(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = _paths.ensure_qgis_app()
        cls.tmp = tempfile.mkdtemp(prefix='qmagery_gui_')
        from qmagery.core import config
        cls._orig_settings = config.load_settings
        config.load_settings = lambda: dict(cls._orig_settings(), output_dir=cls.tmp, tos_accepted=True)
        cls._orig_key = config.load_geodes_key
        cls.messages = []
        cls._orig_mb = {}
        for name in ('information', 'warning', 'critical'):
            cls._orig_mb[name] = getattr(QMessageBox, name)
            setattr(QMessageBox, name, staticmethod(
                lambda *a, _n=name, **k: cls.messages.append((_n, a[2] if len(a) > 2 else '')) or QMessageBox.Ok))
        cls._orig_mb['question'] = QMessageBox.question
        cls.answer = QMessageBox.Yes
        QMessageBox.question = staticmethod(lambda *a, **k: cls.answer)

    @classmethod
    def tearDownClass(cls):
        from qmagery.core import config
        config.load_settings = cls._orig_settings
        config.load_geodes_key = cls._orig_key
        for name, fn in cls._orig_mb.items():
            setattr(QMessageBox, name, fn)
        QgsProject.instance().removeAllMapLayers()

    def setUp(self):
        from qmagery.core import backend_runner
        from qmagery.gui.main_dialog import MainDialog
        self.calls = []
        self.responses = {}
        test = self

        def fake_run(runner, command, params, timeout=None):
            test.calls.append((command, dict(params)))
            res = test.responses.get(command, {'success': True})
            res = res(params) if callable(res) else res
            if isinstance(res, str):
                runner.error.emit(res)
            else:
                runner.finished.emit(res)

        self._orig_run = backend_runner.BackendRunner.run
        backend_runner.BackendRunner.run = fake_run
        self.messages.clear()
        type(self).answer = QMessageBox.Yes
        QgsProject.instance().removeAllMapLayers()
        self.iface = _Iface()
        self.dlg = MainDialog(self.iface, auto_check=False)

    def tearDown(self):
        from qmagery.core import backend_runner
        self.dlg.shutdown()
        self.dlg.deleteLater()
        backend_runner.BackendRunner.run = self._orig_run

    def select(self, source, sensor=None, comp=None):
        self.dlg._source_buttons[source].setChecked(True)
        if sensor:
            self.dlg._cbo_sensor.setCurrentIndex(self.dlg._cbo_sensor.findData(sensor))
        if comp:
            self.dlg._cbo_comp.setCurrentIndex(self.dlg._cbo_comp.findData(comp))


    def download_writes_tif(self, bands=3):
        def respond(params):
            return {'success': True, 'file': _tiny_tif(params['out'], bands), 'rgb_bands': [0, 1, 2]}
        return respond

    # ------------------------------------------------------------------ fontes e sensores
    def test_fontes_sensores_e_composicoes(self):
        for code in ('gee', 'inpe', 'spot', 'gehist', 'wayback'):
            self.select(code)
            self.assertGreater(self.dlg._cbo_sensor.count(), 0)
            self.assertEqual(self.dlg._cbo_comp.isHidden(), code in ('gehist', 'wayback'))
        self.select('gee', 'L5')
        codes = [self.dlg._cbo_comp.itemData(i) for i in range(self.dlg._cbo_comp.count())]
        self.assertIn('321', codes)
        self.assertNotIn('MB_10', codes)
        self.select('spot', 'SPOT:5-PAN')
        self.assertEqual([self.dlg._cbo_comp.itemData(i) for i in range(self.dlg._cbo_comp.count())], ['pan'])
        self.assertEqual(self.dlg._date_start.date(), QDate(1986, 1, 1))

    def test_bandas_personalizadas_so_quando_a_composicao_pede(self):
        self.select('gee', 'S2', '432')
        self.assertTrue(self.dlg._txt_custom.isHidden())
        self.select('gee', 'S2', 'CUSTOM_MATH')
        self.assertFalse(self.dlg._txt_custom.isHidden())

    def test_atalhos_de_data(self):
        self.dlg._quick_date_buttons[30].click()
        self.assertEqual(self.dlg._date_start.date().daysTo(self.dlg._date_end.date()), 30)

    # ------------------------------------------------------------------ busca
    def test_busca_preenche_a_tabela(self):
        self.select('gee', 'S2', '432')
        self.responses['search'] = GEE_RESULT
        self.dlg._on_search_clicked()
        cmd, params = self.calls[-1]
        self.assertEqual((cmd, params['sensor']), ('search', 'S2'))
        self.assertEqual(self.dlg._table.rowCount(), 3)
        self.assertEqual(self.dlg._table.item(1, 1).text(), '0,0%')
        self.assertIsNone(self.dlg._busy)

    def test_escala_acima_do_limite_pergunta_e_ajusta(self):
        self.iface.canvas._scale = 2000000.0
        self.select('inpe')
        type(self).answer = QMessageBox.No
        self.dlg._on_search_clicked()
        self.assertEqual(self.calls, [])                    # recusou: nada foi buscado
        type(self).answer = QMessageBox.Yes
        self.responses['stac_search'] = {'success': True, 'items': []}
        self.dlg._on_search_clicked()
        self.assertIsNotNone(self.iface.canvas.zoomed)
        self.assertEqual(self.calls[-1][0], 'stac_search')

    def test_area_por_camada_vetorial(self):
        vl = QgsVectorLayer("Polygon?crs=EPSG:31981", "aoi", "memory")
        f = QgsFeature()
        f.setGeometry(QgsGeometry.fromWkt("POLYGON((600000 8270000,601000 8270000,601000 8271000,600000 8271000,"
                                          "600000 8270000))"))
        vl.dataProvider().addFeatures([f])
        QgsProject.instance().addMapLayer(vl)
        self.dlg._refresh_vector_layers()
        self.dlg._rb_lyr.setChecked(True)
        self.dlg._cbo_layers.setCurrentIndex(self.dlg._cbo_layers.findData(vl.id()))
        self.select('wayback', 'EWB:17')
        self.responses['esri_versions'] = {'success': True, 'versions': []}
        self.dlg._on_search_clicked()
        params = self.calls[-1][1]
        self.assertIn('geojson_file', params)
        self.assertNotIn('bbox', params)
        import json
        with open(params['geojson_file'], encoding='utf-8') as fh:
            gj = json.load(fh)
        x = gj['features'][0]['geometry']['coordinates'][0][0][0]
        self.assertTrue(-57.5 < x < -56.0, msg='a AOI deve ir em graus (EPSG:4326): %s' % x)

    # ------------------------------------------------------------------ carregamento
    def test_fila_de_varias_cenas_carrega_todas(self):
        self.select('gee', 'S2', 'MB_10')
        self.responses['search'] = GEE_RESULT
        self.dlg._on_search_clicked()
        self.responses['download'] = self.download_writes_tif(bands=10)
        self.dlg._start_queue([0, 1, 2])
        downloads = [p for c, p in self.calls if c == 'download']
        self.assertEqual(len(downloads), 3)
        self.assertEqual(len({p['out'] for p in downloads}), 3)
        self.assertTrue(all(p['out'].startswith(self.tmp) for p in downloads))
        layers = [l for l in QgsProject.instance().mapLayers().values() if isinstance(l, QgsRasterLayer)]
        self.assertEqual(len(layers), 3)
        r = layers[0].renderer()
        self.assertEqual((r.type(), r.redBand(), r.greenBand(), r.blueBand()), ('multibandcolor', 3, 2, 1))
        self.assertIn(u'Carregada', self.dlg._table.item(2, 4).text())
        self.assertIsNone(self.dlg._busy)

    def test_erro_numa_cena_nao_para_a_fila(self):
        self.select('gee', 'S2', '432')
        self.responses['search'] = GEE_RESULT
        self.dlg._on_search_clicked()
        state = {'n': 0}

        def respond(params):
            state['n'] += 1
            return {'success': False, 'message': 'falhou'} if state['n'] == 1 else \
                {'success': True, 'file': _tiny_tif(params['out'])}
        self.responses['download'] = respond
        self.dlg._start_queue([0, 1])
        self.assertEqual(self.dlg._table.item(0, 4).text(), 'Erro')
        self.assertIn(u'Carregada', self.dlg._table.item(1, 4).text())
        self.assertEqual(self.messages[-1][0], 'critical')

    def test_substituir_ocupa_o_lugar_da_camada(self):
        old = QgsRasterLayer(_tiny_tif(os.path.join(self.tmp, 'antiga.tif')), 'antiga', 'gdal')
        QgsProject.instance().addMapLayer(old)
        old_id = old.id()
        self.dlg._refresh_toc_rasters()
        self.dlg._cbo_toc.setCurrentIndex(self.dlg._cbo_toc.findData(old_id))
        self.select('gee', 'S2', '432')
        self.responses['search'] = GEE_RESULT
        self.dlg._on_search_clicked()
        self.dlg._table.selectRow(0)
        self.responses['download'] = self.download_writes_tif()
        self.dlg._on_replace_clicked()
        self.assertIsNone(QgsProject.instance().mapLayer(old_id))
        names = [n.name() for n in QgsProject.instance().layerTreeRoot().findLayers()]
        self.assertEqual(len(names), 1)
        self.assertTrue(names[0].startswith('S2 '))

    def test_spot_sem_chave_pede_a_chave_e_nao_baixa(self):
        from qmagery.core import config
        config.load_geodes_key = lambda: None
        import qmagery.gui.main_dialog as md
        orig = md.GeodesKeyDialog
        md.GeodesKeyDialog = lambda parent: type('D', (), {'exec_': lambda self: 0})()
        try:
            self.select('spot', 'SPOT:123-MS')
            self.responses['spot_search'] = SPOT_RESULT
            self.dlg._on_search_clicked()
            self.dlg._start_queue([0])
        finally:
            md.GeodesKeyDialog = orig
            config.load_geodes_key = self._orig_key
        self.assertNotIn('spot_download', [c for c, _p in self.calls])

    def test_spot_envia_a_chave(self):
        from qmagery.core import config
        config.load_geodes_key = lambda: 'CHAVE-TESTE'
        try:
            self.select('spot', 'SPOT:5-MS', 'false')
            self.responses['spot_search'] = SPOT_RESULT
            self.dlg._on_search_clicked()
            self.assertEqual((self.calls[-1][1]['satellites'], self.calls[-1][1]['kind']), ('5', 'ms'))
            self.responses['spot_download'] = self.download_writes_tif()
            self.dlg._start_queue([0])
        finally:
            config.load_geodes_key = self._orig_key
        params = [p for c, p in self.calls if c == 'spot_download'][0]
        self.assertEqual((params['api_key'], params['mode']), ('CHAVE-TESTE', 'false'))

    def test_cancelamento_restaura_a_janela(self):
        from qmagery.core.backend_runner import CANCELLED_MESSAGE
        self.select('gee', 'S2', '432')
        self.responses['search'] = GEE_RESULT
        self.dlg._on_search_clicked()
        self.responses['download'] = CANCELLED_MESSAGE
        self.dlg._start_queue([0, 1])
        self.assertIsNone(self.dlg._busy)
        self.assertEqual(self.dlg._table.item(1, 4).text(), 'Cancelada')
        self.assertTrue(self.dlg._btn_search.isEnabled())
        self.assertEqual([m for m in self.messages if m[0] == 'critical'], [])

    def test_miniatura(self):
        self.select('inpe')
        self.responses['stac_search'] = {'success': True, 'items': [
            {'id': 'CBERS_X', 'date': '2024-01-01', 'collection': 'CB4A-WPM-L4-DN-1', 'thumbnail': 'https://x/t.png'}]}
        self.dlg._on_search_clicked()
        self.dlg._table.selectRow(0)
        png = os.path.join(self.tmp, 't.png')
        from qgis.PyQt.QtGui import QImage
        QImage(8, 8, QImage.Format_RGB32).save(png)
        self.responses['stac_thumb'] = {'success': True, 'file': png}
        shown = []
        orig = QDialog.exec_
        QDialog.exec_ = lambda d: shown.append(d.windowTitle()) or 0
        try:
            self.dlg._on_thumb_clicked()
        finally:
            QDialog.exec_ = orig
        self.assertEqual(self.calls[-1][0], 'stac_thumb')
        self.assertEqual(self.calls[-1][1]['href'], 'https://x/t.png')
        self.assertTrue(shown)

    # ------------------------------------------------------------------ diálogos
    def test_dialogos_abrem(self):
        from qmagery.gui.splash_dialog import SplashDialog
        from qmagery.gui.support_dialogs import (AboutDialog, ExtraSourcesDialog, GeeProjectDialog, GeodesKeyDialog,
                                                  SettingsDialog)
        for d in (AboutDialog(self.dlg), SettingsDialog(self.dlg), GeodesKeyDialog(self.dlg),
                  GeeProjectDialog(self.dlg, 'p'), ExtraSourcesDialog(self.iface, self.dlg, self.dlg._resolve_area),
                  SplashDialog(self.dlg, auto_run=False)):
            d.done(0)

    def test_xyz_ao_vivo_e_bing_so_download(self):
        from qmagery.gui.support_dialogs import ExtraSourcesDialog
        x = ExtraSourcesDialog(self.iface, self.dlg, self.dlg._resolve_area)
        x._cbo_provider.setCurrentIndex(x._cbo_provider.findText('Bing Aerial'))
        self.assertFalse(x._btn_live.isEnabled())
        x._cbo_provider.setCurrentIndex(0)
        x._on_live()
        layer = [l for l in QgsProject.instance().mapLayers().values()][-1]
        self.assertEqual(layer.providerType(), 'wms')
        self.assertIn('%7Bz%7D', layer.source())
        self.assertTrue(layer.isValid())
        x.done(0)



@unittest.skipUnless(_paths.HAS_PYQGIS, "requer o PyQGIS")
class ExecutorDoBackend(unittest.TestCase):
    """BackendRunner real (sem simulação): cancelamento e novo comando dentro do slot de término."""

    @classmethod
    def setUpClass(cls):
        cls.app = _paths.ensure_qgis_app()

    def wait(self, cond, timeout=60):
        t0 = time.time()
        while not cond() and time.time() - t0 < timeout:
            self.app.processEvents()
            time.sleep(0.02)

    def test_comando_seguinte_dentro_do_slot(self):
        from qmagery.core.backend_runner import BackendRunner
        r = BackendRunner()
        results = []

        def on_done(res):
            results.append(res)
            if len(results) == 1:
                r.run('sources_info', {})      # fila: começa no slot de término do anterior
        r.finished.connect(on_done)
        r.error.connect(lambda m: results.append(m))
        r.run('sources_info', {})
        self.wait(lambda: len(results) >= 2)
        self.assertEqual([x.get('success') for x in results], [True, True])
        r.shutdown()

    def test_cancelar_encerra_o_processo(self):
        from qmagery.core.backend_runner import CANCELLED_MESSAGE, _BackendWorker, get_python_executable, \
            subprocess_kwargs
        w = _BackendWorker('x', {})
        w._proc = subprocess.Popen([get_python_executable(), '-c', 'import time; time.sleep(30)'],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, **subprocess_kwargs())
        t0 = time.time()
        w.cancel()
        w._proc.wait(timeout=10)
        self.assertLess(time.time() - t0, 10)
        self.assertTrue(CANCELLED_MESSAGE)


if __name__ == '__main__':
    unittest.main()
