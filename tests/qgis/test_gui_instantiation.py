# -*- coding: utf-8 -*-
"""
Teste unitário de instanciação da GUI do QMagery (100% de paridade com o ArcMagery).
"""
import os
import sys
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import _paths

class TestGuiInstantiation(unittest.TestCase):
    _qgs = None

    @classmethod
    def setUpClass(cls):
        _paths.ensure_qgis_app()

    @unittest.skipUnless(_paths.HAS_PYQGIS, "Requer ambiente PyQGIS (QGIS desktop ou python-qgis)")
    def test_main_dialog_instantiation(self):
        from qgis.core import QgsRectangle, QgsCoordinateReferenceSystem

        plugin_dir = _paths.PLUGIN_ROOT
        if plugin_dir not in sys.path:
            sys.path.insert(0, plugin_dir)

        class MockCanvas:
            def extent(self):
                return QgsRectangle(-56.15, -15.65, -56.05, -15.55)
            def scale(self):
                return 250000.0
            def zoomScale(self, s):
                pass
            def mapSettings(self):
                class Settings:
                    def destinationCrs(self):
                        return QgsCoordinateReferenceSystem("EPSG:4326")
                return Settings()

        class MockIface:
            def mainWindow(self):
                return None
            def mapCanvas(self):
                return MockCanvas()

        from qmagery.gui.main_dialog import MainDialog
        dlg = MainDialog(iface=MockIface(), auto_check=False)

        # Valida que todos os componentes idênticos ao ArcMagery foram criados
        self.assertIsNotNone(dlg._lbl_status)
        self.assertIsNotNone(dlg._lbl_scale)
        self.assertIsNotNone(dlg._source_group)
        self.assertIsNotNone(dlg._cbo_sensor)
        self.assertIsNotNone(dlg._cbo_comp)
        self.assertIsNotNone(dlg._table)
        self.assertIsNotNone(dlg._btn_search)
        self.assertIsNotNone(dlg._btn_load)
        self.assertIsNotNone(dlg._btn_replace)
        self.assertIsNotNone(dlg._btn_thumb)
        self.assertIsNotNone(dlg._btn_cancel)

        # Testa alternância entre fontes
        for src in ['gee', 'inpe', 'spot', 'gehist', 'wayback']:
            dlg._on_source_toggled(src, True)
            self.assertEqual(dlg._current_source, src)
            self.assertGreater(dlg._cbo_sensor.count(), 0)

        dlg.close()

if __name__ == '__main__':
    unittest.main()
