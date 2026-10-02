# -*- coding: utf-8 -*-
"""
QMagery — integração com o QGIS: botão na barra de ferramentas e item no menu Raster.

Nada do backend é importado aqui (import tardio: não atrasa a abertura do QGIS). No unload (desativar,
atualizar ou reinstalar o plugin pelo Gerenciador de Complementos) as operações em andamento são
interrompidas e as threads esperadas antes de a janela ser destruída.
"""
import os

from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QDesktopServices, QIcon
from qgis.PyQt.QtWidgets import QAction

MENU = u"&QMagery"
MANUAL_URL = 'https://github.com/Yiuky/ArcMagery/blob/main/docs/QMAGERY.md'


class QMageryPlugin:

    def __init__(self, iface):
        self.iface = iface
        self._actions = []
        self._dialog = None
        self._checked_this_session = False

    def initGui(self):  # noqa: N802
        icon_path = os.path.join(os.path.dirname(__file__), 'resources', 'icons', 'icon32.png')
        icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()
        main = QAction(icon, u"QMagery — imagens de satélite", self.iface.mainWindow())
        main.setToolTip(u"Abrir o QMagery (GEE, CBERS, SPOT, Google Earth histórico, Esri Wayback)")
        main.triggered.connect(self.open_dialog)
        self.iface.addToolBarIcon(main)
        self.iface.addPluginToRasterMenu(MENU, main)
        check = QAction(u"Verificar o ambiente...", self.iface.mainWindow())
        check.triggered.connect(lambda: self._run_startup_check(force=True))
        self.iface.addPluginToRasterMenu(MENU, check)
        manual = QAction(u"Manual do QMagery", self.iface.mainWindow())
        manual.triggered.connect(lambda: QDesktopServices.openUrl(QUrl(MANUAL_URL)))
        self.iface.addPluginToRasterMenu(MENU, manual)
        self._actions = [main, check, manual]

    def unload(self):
        if self._dialog is not None:
            try:
                self._dialog.shutdown()
                self._dialog.done(0)
                self._dialog.deleteLater()
            except Exception:
                pass
            self._dialog = None
        for action in self._actions:
            self.iface.removePluginRasterMenu(MENU, action)
            self.iface.removeToolBarIcon(action)
        self._actions = []

    def _run_startup_check(self, force=False):
        from .core import config
        if not force and (self._checked_this_session or not config.load_settings().get('show_startup_check', True)):
            return True
        from .gui.splash_dialog import SplashDialog
        ok = bool(SplashDialog(parent=self.iface.mainWindow()).exec_())
        if ok:
            self._checked_this_session = True
        return ok

    def open_dialog(self):
        if self._dialog is None:
            if not self._run_startup_check():
                return
            from .gui.main_dialog import MainDialog
            self._dialog = MainDialog(iface=self.iface, parent=self.iface.mainWindow())
            self._dialog.finished.connect(self._on_dialog_closed)
        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()

    _open_dialog = open_dialog   # nome antigo

    def _on_dialog_closed(self, *_):
        dlg, self._dialog = self._dialog, None
        if dlg is not None:
            dlg.deleteLater()
