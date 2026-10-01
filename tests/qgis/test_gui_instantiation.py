# -*- coding: utf-8 -*-
"""
Teste unitário de instanciação da GUI do QMagery.
Se executado fora do ambiente QGIS (sem módulo 'qgis'), o teste é pulado graciosamente.
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
        if _paths.HAS_PYQGIS:
            from qgis.core import QgsApplication
            if QgsApplication.instance() is None:
                cls._qgs = QgsApplication([], False)
                cls._qgs.initQgis()

    @classmethod
    def tearDownClass(cls):
        if cls._qgs:
            cls._qgs.exitQgis()
            cls._qgs = None

    @unittest.skipUnless(_paths.HAS_PYQGIS, "Requer ambiente PyQGIS (QGIS desktop ou python-qgis)")
    def test_main_dialog_tabs_instantiation(self):
        from qgis.core import QgsRectangle, QgsCoordinateReferenceSystem

        plugin_dir = _paths.PLUGIN_ROOT
        if plugin_dir not in sys.path:
            sys.path.insert(0, plugin_dir)

        class MockCanvas:
            def extent(self):
                return QgsRectangle(-56.15, -15.65, -56.05, -15.55)
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
        dlg = MainDialog(iface=MockIface())
        self.assertEqual(dlg._tabs.count(), 6)

        expected_tabs = {
            0: ("GEE", "GeeTab"),
            1: ("CBERS / Amazônia-1", "InpeTab"),
            2: ("SPOT 1-5", "SpotTab"),
            3: ("Google Earth Hist.", "GEHistTab"),
            4: ("Esri Wayback", "WaybackTab"),
            5: ("Google / XYZ", "XyzTab"),
        }

        for idx, (expected_title, expected_cls) in expected_tabs.items():
            self.assertEqual(dlg._tabs.tabText(idx), expected_title)
            w = dlg._tabs.widget(idx)
            self.assertEqual(w.__class__.__name__, expected_cls,
                             f"Aba {expected_title} falhou ao instanciar: gerou {w.__class__.__name__}")

if __name__ == '__main__':
    unittest.main()
