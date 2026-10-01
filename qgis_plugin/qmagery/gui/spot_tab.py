# -*- coding: utf-8 -*-
"""
Aba SPOT 1-5 (CNES / GEODES) da janela principal do QMagery.
Equivalente ao arcmagery_spot.py do ArcMagery.
Estado: FASE 2 — estrutura básica.
"""
from qgis.PyQt.QtWidgets import QWidget, QVBoxLayout, QLabel


class SpotTab(QWidget):
    def __init__(self, iface, status_bar, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.status_bar = status_bar
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('<b>SPOT 1-5 (CNES / GEODES)</b> — Fase 2, em desenvolvimento.'))
        layout.addStretch()
