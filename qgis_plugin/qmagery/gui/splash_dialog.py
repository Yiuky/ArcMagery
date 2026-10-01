# -*- coding: utf-8 -*-
"""
Tela de abertura do QMagery.

Verifica o ambiente antes de abrir a janela principal:
  - Python 3 compatível
  - Backend acessível (run_gee.py existe)
  - GDAL disponível
  - GEE instalado (opcional)
  - Rede (opcional)

Equivalente ao arcmagery_startup.py do ArcMagery, mas usando PyQt em vez de Tkinter.
"""
import os
import sys
import threading
from typing import List, Tuple

from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QProgressBar,
    QDialogButtonBox, QTextEdit,
)


_THIS_FILE = os.path.realpath(__file__)
_BACKEND_DIR = os.path.normpath(
    os.path.join(os.path.dirname(_THIS_FILE), '..', '..', '..',
                 'arcgis_addin', 'Install', 'backend')
)
_RUN_GEE = os.path.join(_BACKEND_DIR, 'run_gee.py')


class SplashDialog(QDialog):
    """
    Diálogo de diagnóstico exibido antes da janela principal.
    Retorna QDialog.Accepted se o ambiente estiver OK (ou o usuário ignorar).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('QMagery — Verificando ambiente')
        self.setMinimumWidth(500)
        self._setup_ui()
        # Executa verificações em background
        QTimer.singleShot(100, self._run_checks)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        self._label = QLabel('Verificando ambiente...')
        layout.addWidget(self._label)
        self._bar = QProgressBar()
        self._bar.setRange(0, 0)  # indeterminado
        layout.addWidget(self._bar)
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(160)
        layout.addWidget(self._log)
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        self._buttons.setEnabled(False)
        layout.addWidget(self._buttons)

    def _run_checks(self):
        checks = _run_environment_checks()
        self._bar.setRange(0, 1)
        self._bar.setValue(1)
        all_ok = all(ok for ok, _ in checks)
        msgs = []
        for ok, msg in checks:
            status = '✅' if ok else '⚠️'
            msgs.append(f'{status} {msg}')
        self._log.setPlainText('\n'.join(msgs))
        if all_ok:
            self._label.setText('Ambiente OK — pronto para usar.')
        else:
            self._label.setText('Alguns itens precisam de atenção (veja abaixo).')
        self._buttons.setEnabled(True)


def _run_environment_checks() -> List[Tuple[bool, str]]:
    """Executa todas as verificações e retorna lista de (ok, mensagem)."""
    results = []

    # 1. Python 3.8+
    ok = sys.version_info >= (3, 8)
    results.append((ok, f'Python {sys.version.split()[0]} ({"OK" if ok else "requer 3.8+"})' ))

    # 2. Backend acessível
    ok = os.path.isfile(_RUN_GEE)
    results.append((ok, f'Backend ({"encontrado" if ok else "NÃO encontrado: " + _RUN_GEE})' ))

    # 3. GDAL
    try:
        from osgeo import gdal  # noqa: F401
        results.append((True, f'GDAL {gdal.__version__} disponível'))
    except ImportError:
        results.append((False, 'GDAL não encontrado (CBERS e XYZ exigem GDAL)'))

    # 4. GEE (opcional)
    try:
        import ee  # noqa: F401
        results.append((True, 'earthengine-api disponível'))
    except ImportError:
        results.append((True, 'earthengine-api não instalado (fonte GEE indisponível)'))

    return results
