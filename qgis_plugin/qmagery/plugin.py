# -*- coding: utf-8 -*-
"""
QMagery — Plugin principal.

Responsável por registrar o botão na toolbar do QGIS e abrir a janela principal.
Não importa nada do backend aqui (import tardio para não atrasar o carregamento do QGIS).
"""
import os

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction


class QMageryPlugin:
    """Plugin QGIS do QMagery."""

    def __init__(self, iface):
        self.iface = iface
        self._action = None
        self._dialog = None

    # ------------------------------------------------------------------
    # Ciclo de vida do plugin
    # ------------------------------------------------------------------

    def initGui(self):  # noqa: N802
        """Chamado pelo QGIS ao ativar o plugin: adiciona botão na toolbar."""
        icon_path = os.path.join(os.path.dirname(__file__), 'resources', 'icons', 'icon.png')
        icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()
        self._action = QAction(icon, 'QMagery', self.iface.mainWindow())
        self._action.setToolTip('Abrir QMagery — Imagens de Satélite')
        self._action.triggered.connect(self._open_dialog)
        self.iface.addToolBarIcon(self._action)
        self.iface.addPluginToRasterMenu('QMagery', self._action)

    def unload(self):
        """Chamado pelo QGIS ao desativar o plugin."""
        if self._action:
            self.iface.removeToolBarIcon(self._action)
            self.iface.removePluginRasterMenu('QMagery', self._action)
            self._action = None
        if self._dialog:
            self._dialog.close()
            self._dialog = None

    # ------------------------------------------------------------------
    # Ações
    # ------------------------------------------------------------------

    def _open_dialog(self):
        """Abre (ou traz para frente) a janela principal do QMagery."""
        if self._dialog is None:
            from .gui.splash_dialog import SplashDialog
            splash = SplashDialog(parent=self.iface.mainWindow())
            if not splash.exec_():
                return  # usuário cancelou na splash
            from .gui.main_dialog import MainDialog
            self._dialog = MainDialog(iface=self.iface, parent=self.iface.mainWindow())
            self._dialog.finished.connect(self._on_dialog_closed)
        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()

    def _on_dialog_closed(self):
        self._dialog = None
