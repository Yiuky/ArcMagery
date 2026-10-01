# -*- coding: utf-8 -*-
"""
Aba CBERS / Amazônia-1 (INPE STAC) da janela principal do QMagery.
Equivalente ao arcmagery_inpe.py do ArcMagery.
Estado: FASE 2 — estrutura básica.
"""
from qgis.PyQt.QtWidgets import QWidget, QVBoxLayout, QLabel


class InpeTab(QWidget):
    def __init__(self, iface, status_bar, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.status_bar = status_bar
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('<b>CBERS / Amazônia-1 (INPE STAC)</b> — Fase 2, em desenvolvimento.'))
        layout.addStretch()
