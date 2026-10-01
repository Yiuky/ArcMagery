# -*- coding: utf-8 -*-
"""
Aba Google / XYZ da janela principal do QMagery.
Equivalente ao arcmagery_sources_gui.py do ArcMagery.
Estado: FASE 3 — estrutura básica.
"""
from qgis.PyQt.QtWidgets import QWidget, QVBoxLayout, QLabel


class XyzTab(QWidget):
    def __init__(self, iface, status_bar, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.status_bar = status_bar
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('<b>Google / XYZ / Esri / Bing</b> — Fase 3, em desenvolvimento.'))
        layout.addStretch()
