# -*- coding: utf-8 -*-
"""
Aba SPOT 1-5 (CNES SPOT World Heritage, 1986-2015) da janela principal do QMagery.
Busca pública de 40 anos de histórico SPOT, com alinhamento geométrico à Esri.
"""
import os
import tempfile
from typing import Optional

from qgis.PyQt.QtCore import Qt, QDate
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QComboBox, QPushButton, QDateEdit,
    QCheckBox, QGroupBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QProgressBar, QSpinBox
)

from ..core.backend_runner import BackendRunner
from ..core.qgis_layer import add_raster_layer


_SPOT_GROUPS = [
    ("SPOT 1 a 5 · multiespectral (10-20 m)", "MS", None, "ms"),
    ("SPOT 1 a 5 · pancromática (2,5-10 m)", "PAN", None, "pan"),
    ("SPOT 5 · 10 m multi (HRG, 2002-2015)", "5-MS", "5", "ms"),
    ("SPOT 5 · 2,5/5 m PAN (HRG, 2002-2015)", "5-PAN", "5", "pan"),
    ("SPOT 4 · 20 m multi (HRVIR, 1998-2013)", "4-MS", "4", "ms"),
    ("SPOT 4 · 10 m PAN (HRVIR, 1998-2013)", "4-PAN", "4", "pan"),
    ("SPOT 1, 2 e 3 · 20 m multi (1986-2009)", "123-MS", "1,2,3", "ms"),
    ("SPOT 1, 2 e 3 · 10 m PAN (1986-2009)", "123-PAN", "1,2,3", "pan"),
]


class SpotTab(QWidget):
    """Aba SPOT 1-5 (CNES / GEODES)."""

    def __init__(self, iface, status_bar, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.status_bar = status_bar
        self._runner: Optional[BackendRunner] = None
        self._results = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        form_box = QGroupBox("Parâmetros do Acervo Histórico SPOT 1–5")
        form = QFormLayout(form_box)

        self._group_cb = QComboBox()
        for label, code, sats, kind in _SPOT_GROUPS:
            self._group_cb.addItem(label, (code, sats, kind))
        form.addRow("Produto SPOT:", self._group_cb)

        self._key_edit = QLineEdit()
        self._key_edit.setEchoMode(QLineEdit.Password)
        self._key_edit.setPlaceholderText("Chave gratuita do GEODES (geodes-portal.cnes.fr)")
        form.addRow("Chave API GEODES:", self._key_edit)

        self._start_edit = QDateEdit(QDate(1986, 1, 1))
        self._start_edit.setCalendarPopup(True)
        form.addRow("Data início:", self._start_edit)

        self._end_edit = QDateEdit(QDate(2015, 12, 31))
        self._end_edit.setCalendarPopup(True)
        form.addRow("Data fim:", self._end_edit)

        self._cloud_spin = QSpinBox()
        self._cloud_spin.setRange(0, 100)
        self._cloud_spin.setValue(30)
        self._cloud_spin.setSuffix("%")
        form.addRow("Nuvens máx.:", self._cloud_spin)

        self._align_cb = QCheckBox("Alinhar automaticamente à Esri World Imagery (~2–5 m de erro)")
        self._align_cb.setChecked(True)
        form.addRow("", self._align_cb)

        self._use_canvas_cb = QCheckBox("Usar extensão atual do mapa (AOI)")
        self._use_canvas_cb.setChecked(True)
        form.addRow("", self._use_canvas_cb)

        layout.addWidget(form_box)

        # Botões
        btn_layout = QHBoxLayout()
        self._search_btn = QPushButton("🔍 Buscar cenas SPOT")
        self._search_btn.clicked.connect(self._on_search)
        btn_layout.addWidget(self._search_btn)

        self._download_btn = QPushButton("⬇️ Baixar e Alinhar no QGIS")
        self._download_btn.clicked.connect(self._on_download)
        self._download_btn.setEnabled(False)
        btn_layout.addWidget(self._download_btn)

        self._cancel_btn = QPushButton("✖ Cancelar")
        self._cancel_btn.clicked.connect(self._on_cancel)
        self._cancel_btn.setEnabled(False)
        btn_layout.addWidget(self._cancel_btn)

        layout.addLayout(btn_layout)

        # Progresso
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        # Tabela
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["ID SPOT", "Satélite", "Data", "Nuvens %", "Ângulo Incidência"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self._table)

    def _current_bbox(self):
        canvas = self.iface.mapCanvas()
        ext = canvas.extent()
        from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject
        src_crs = canvas.mapSettings().destinationCrs()
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        if src_crs != wgs84:
            tr = QgsCoordinateTransform(src_crs, wgs84, QgsProject.instance())
            ext = tr.transformBoundingBox(ext)
        return [ext.xMinimum(), ext.yMinimum(), ext.xMaximum(), ext.yMaximum()]

    def _on_search(self):
        data = self._group_cb.currentData()
        code, sats, kind = data
        start = self._start_edit.date().toString("yyyy-MM-dd")
        end = self._end_edit.date().toString("yyyy-MM-dd")
        max_cloud = self._cloud_spin.value()
        bbox = self._current_bbox() if self._use_canvas_cb.isChecked() else None

        if not bbox:
            self.status_bar.showMessage("Selecione 'Usar extensão atual do mapa' ou defina uma AOI.", 4000)
            return

        params = {
            "start_date": start,
            "end_date": end,
            "max_cloud": max_cloud,
            "bbox": ",".join(str(v) for v in bbox),
            "kind": kind,
            "max_items": 100
        }
        if sats:
            params["satellites"] = sats

        self._runner = BackendRunner(self)
        self._runner.progress.connect(self._on_progress)
        self._runner.finished.connect(self._on_search_result)
        self._runner.error.connect(self._on_error)
        self._set_running(True)
        self._runner.run("spot_search", params)

    def _on_download(self):
        rows = {idx.row() for idx in self._table.selectedIndexes()}
        if not rows:
            self.status_bar.showMessage("Selecione uma cena SPOT para baixar.", 3000)
            return

        api_key = self._key_edit.text().strip()
        if not api_key:
            self.status_bar.showMessage("Aviso: Chave de API GEODES obrigatória para download SPOT.", 5000)
            return

        row = sorted(rows)[0]
        item = self._results[row]
        item_id = item.get("id")
        bbox = self._current_bbox()
        align = self._align_cb.isChecked()

        out_path = os.path.join(tempfile.gettempdir(), f"{item_id}_aligned.tif")
        params = {
            "item_id": item_id,
            "bbox": ",".join(str(v) for v in bbox),
            "out": out_path,
            "api_key": api_key,
            "align": align
        }

        self._runner = BackendRunner(self)
        self._runner.progress.connect(self._on_progress)
        self._runner.finished.connect(self._on_download_result)
        self._runner.error.connect(self._on_error)
        self._set_running(True)
        self._runner.run("spot_download", params)

    def _on_cancel(self):
        if self._runner:
            self._runner.cancel()
        self._set_running(False)
        self.status_bar.showMessage("Operação cancelada.", 3000)

    def _on_progress(self, line: str):
        self.status_bar.showMessage(line.replace("[ArcGEE]", "").strip())

    def _on_search_result(self, result: dict):
        self._set_running(False)
        if not result.get("success"):
            self.status_bar.showMessage(f"Erro na busca SPOT: {result.get('message')}", 5000)
            return

        items = result.get("items", [])
        self._results = items
        self._table.setRowCount(0)
        for it in items:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(str(it.get("id", ""))))
            self._table.setItem(row, 1, QTableWidgetItem(str(it.get("satellite", ""))))
            self._table.setItem(row, 2, QTableWidgetItem(str(it.get("date", ""))))
            self._table.setItem(row, 3, QTableWidgetItem(str(it.get("cloud_cover", ""))))
            self._table.setItem(row, 4, QTableWidgetItem(str(it.get("incidence_angle", "-"))))

        self._download_btn.setEnabled(bool(items))
        self.status_bar.showMessage(f"{len(items)} cena(s) SPOT encontrada(s).", 5000)

    def _on_download_result(self, result: dict):
        self._set_running(False)
        if not result.get("success"):
            self.status_bar.showMessage(f"Erro no download SPOT: {result.get('message')}", 6000)
            return

        tif_path = result.get("file")
        if tif_path and os.path.isfile(tif_path):
            try:
                add_raster_layer(tif_path, f"QMagery — SPOT", group_name="QMagery")
                self.status_bar.showMessage(f"Cena SPOT alinhada e carregada: {tif_path}", 5000)
            except Exception as exc:
                self.status_bar.showMessage(f"Erro ao carregar no QGIS: {exc}", 5000)

    def _on_error(self, msg: str):
        self._set_running(False)
        self.status_bar.showMessage(f"Erro: {msg}", 8000)

    def _set_running(self, running: bool):
        self._search_btn.setEnabled(not running)
        self._download_btn.setEnabled(not running)
        self._cancel_btn.setEnabled(running)
        self._progress.setVisible(running)
