# -*- coding: utf-8 -*-
"""
Janela principal do QMagery.

Organiza as fontes em abas (QTabWidget), uma por fonte de imagem.
Equivalente à gee_gui.py do ArcMagery (Tkinter → PyQt).
"""
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QTabWidget, QDialogButtonBox,
    QStatusBar, QWidget,
)
from qgis.PyQt.QtCore import Qt


class MainDialog(QDialog):
    """Janela principal com abas por fonte de imagem."""

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle('QMagery — Imagens de Satélite')
        self.setMinimumSize(800, 600)
        self.setWindowFlags(
            self.windowFlags() | Qt.WindowMaximizeButtonHint
        )
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Status bar (deve ser criada antes das abas, pois elas a recebem no construtor)
        self._status = QStatusBar()

        self._tabs = QTabWidget()
        layout.addWidget(self._tabs)

        # Adiciona as abas (importação tardia para não atrasar o plugin)
        self._add_tab('GEE', 'gee_tab', 'GeeTab')
        self._add_tab('CBERS / Amazônia-1', 'inpe_tab', 'InpeTab')
        self._add_tab('SPOT 1-5', 'spot_tab', 'SpotTab')
        self._add_tab('Google Earth Hist.', 'gehist_tab', 'GEHistTab')
        self._add_tab('Esri Wayback', 'wayback_tab', 'WaybackTab')
        self._add_tab('Google / XYZ', 'xyz_tab', 'XyzTab')

        layout.addWidget(self._status)

        # Botões
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _add_tab(self, label: str, module_name: str, class_name: str):
        """Adiciona uma aba carregando o módulo de forma tardia."""
        try:
            module = __import__(
                f'qmagery.gui.{module_name}',
                fromlist=[class_name]
            )
            cls = getattr(module, class_name)
            widget = cls(iface=self.iface, status_bar=self._status, parent=self)
        except Exception as exc:
            # Aba indisponível (ex: módulo ainda não implementado)
            widget = _PlaceholderTab(label, str(exc))
        self._tabs.addTab(widget, label)

    def show_status(self, msg: str):
        self._status.showMessage(msg, 5000)


class _PlaceholderTab(QWidget):
    """Widget temporário para abas ainda não implementadas."""
    def __init__(self, name: str, reason: str = '', parent=None):
        super().__init__(parent)
        from qgis.PyQt.QtWidgets import QVBoxLayout, QLabel
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f'<b>{name}</b> — em desenvolvimento.'))
        if reason:
            lbl = QLabel(f'<small>{reason}</small>')
            lbl.setWordWrap(True)
            layout.addWidget(lbl)
        layout.addStretch()
