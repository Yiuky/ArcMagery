# -*- coding: utf-8 -*-
"""
Aba CBERS / Amazônia-1 (INPE STAC) da janela principal do QMagery.
Permite buscar cenas de satélites brasileiros/INPE e baixar no QGIS em resolução nativa.
"""
import os
import tempfile
from typing import Optional

from qgis.PyQt.QtCore import Qt, QDate
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QComboBox, QPushButton, QDateEdit,
    QCheckBox, QGroupBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QProgressBar, QDoubleSpinBox, QSpinBox
)

from ..core.backend_runner import BackendRunner
from ..core.qgis_layer import add_raster_layer


_COLLECTIONS = [
    ("CBERS-4A WPM · 8 m multi + 2 m PAN", "CB4A-WPM-L4-DN-1"),
    ("CBERS-4A WPM · 2 m fusionada RGB (PCA)", "CB4A-WPM-PCA-FUSED-1"),
    ("CBERS-4A MUX · 16 m", "CB4A-MUX-L4-DN-1"),
    ("CBERS-4A MUX · 16 m reflectância (SR)", "CB4A-MUX-L4-SR-1"),
    ("CBERS-4A WFI · 55 m reflectância (SR)", "CB4A-WFI-L4-SR-1"),
    ("CBERS-4 MUX · 20 m reflectância (SR)", "CB4-MUX-L4-SR-1"),
    ("CBERS-4 MUX · 20 m", "CB4-MUX-L4-DN-1"),
    ("CBERS-4 WFI · 64 m reflectância (SR)", "CB4-WFI-L4-SR-1"),
    ("CBERS-4 PAN · 10 m (verde, verm, NIR)", "CB4-PAN10M-L4-DN-1"),
    ("CBERS-4 PAN · 5 m pancromática", "CB4-PAN5M-L4-DN-1"),
    ("Amazônia-1 WFI · 64 m reflectância (SR)", "AMZ1-WFI-L4-SR-1"),
    ("Amazônia-1 WFI · 64 m", "AMZ1-WFI-L4-DN-1"),
    ("CBERS-4A WFI · 55 m", "CB4A-WFI-L4-DN-1"),
    ("CBERS-4 WFI · 64 m", "CB4-WFI-L4-DN-1"),
]


class InpeTab(QWidget):
    """Aba CBERS / Amazônia-1 (INPE STAC)."""

    def __init__(self, iface, status_bar, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.status_bar = status_bar
        self._runner: Optional[BackendRunner] = None
        self._results = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Form de busca
        form_box = QGroupBox("Parâmetros de busca STAC (INPE)")
        form = QFormLayout(form_box)

        self._collection_cb = QComboBox()
        for label, code in _COLLECTIONS:
            self._collection_cb.addItem(label, code)
        form.addRow("Coleção:", self._collection_cb)

        today = QDate.currentDate()
        self._start_edit = QDateEdit(today.addDays(-60))
        self._start_edit.setCalendarPopup(True)
        form.addRow("Data início:", self._start_edit)

        self._end_edit = QDateEdit(today)
        self._end_edit.setCalendarPopup(True)
        form.addRow("Data fim:", self._end_edit)

        self._cloud_spin = QSpinBox()
        self._cloud_spin.setRange(0, 100)
        self._cloud_spin.setValue(50)
        self._cloud_spin.setSuffix("%")
        form.addRow("Nuvens máx.:", self._cloud_spin)

        self._mode_cb = QComboBox()
        self._mode_cb.addItems(["rgb", "false", "pan", "all"])
        form.addRow("Modo de download:", self._mode_cb)

        self._use_canvas_cb = QCheckBox("Usar extensão atual do mapa (AOI)")
        self._use_canvas_cb.setChecked(True)
        form.addRow("", self._use_canvas_cb)

        layout.addWidget(form_box)

        # Botões
        btn_layout = QHBoxLayout()
        self._search_btn = QPushButton("🔍 Buscar cenas")
        self._search_btn.clicked.connect(self._on_search)
        btn_layout.addWidget(self._search_btn)

        self._download_btn = QPushButton("⬇️ Baixar e Carregar no QGIS")
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
        self._table.setHorizontalHeaderLabels(["ID da Cena", "Data", "Nuvens %", "Cobertura AOI %", "Resolução"])
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
        col = self._collection_cb.currentData()
        start = self._start_edit.date().toString("yyyy-MM-dd")
        end = self._end_edit.date().toString("yyyy-MM-dd")
        max_cloud = self._cloud_spin.value()
        bbox = self._current_bbox() if self._use_canvas_cb.isChecked() else None

        if not bbox:
            self.status_bar.showMessage("Selecione 'Usar extensão atual do mapa' ou defina uma AOI.", 4000)
            return

        params = {
            "collection": col,
            "start_date": start,
            "end_date": end,
            "max_cloud": max_cloud,
            "bbox": ",".join(str(v) for v in bbox),
            "max_items": 100
        }

        self._runner = BackendRunner(self)
        self._runner.progress.connect(self._on_progress)
        self._runner.finished.connect(self._on_search_result)
        self._runner.error.connect(self._on_error)
        self._set_running(True)
        self._runner.run("stac_search", params)

    def _on_download(self):
        rows = {idx.row() for idx in self._table.selectedIndexes()}
        if not rows:
            self.status_bar.showMessage("Selecione uma cena para baixar.", 3000)
            return

        row = sorted(rows)[0]
        item = self._results[row]
        item_id = item.get("id")
        col = self._collection_cb.currentData()
        mode = self._mode_cb.currentText()
        bbox = self._current_bbox()

        out_path = os.path.join(tempfile.gettempdir(), f"{item_id}_{mode}.tif")
        params = {
            "collection": col,
            "item_id": item_id,
            "bbox": ",".join(str(v) for v in bbox),
            "out": out_path,
            "mode": mode
        }

        self._runner = BackendRunner(self)
        self._runner.progress.connect(self._on_progress)
        self._runner.finished.connect(self._on_download_result)
        self._runner.error.connect(self._on_error)
        self._set_running(True)
        self._runner.run("stac_download", params)

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
            self.status_bar.showMessage(f"Erro: {result.get('message')}", 5000)
            return

        items = result.get("items", [])
        self._results = items
        self._table.setRowCount(0)
        for it in items:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(str(it.get("id", ""))))
            self._table.setItem(row, 1, QTableWidgetItem(str(it.get("date", ""))))
            self._table.setItem(row, 2, QTableWidgetItem(str(it.get("cloud_cover", ""))))
            cov = it.get("coverage_pct")
            cov_str = f"{cov:.1f}%" if cov is not None else "-"
            self._table.setItem(row, 3, QTableWidgetItem(cov_str))
            self._table.setItem(row, 4, QTableWidgetItem(str(it.get("resolution", ""))))

        self._download_btn.setEnabled(bool(items))
        self.status_bar.showMessage(f"{len(items)} cena(s) encontrada(s) no STAC INPE.", 5000)

    def _on_download_result(self, result: dict):
        self._set_running(False)
        if not result.get("success"):
            self.status_bar.showMessage(f"Erro no download: {result.get('message')}", 6000)
            return

        tif_path = result.get("file")
        if tif_path and os.path.isfile(tif_path):
            try:
                col = self._collection_cb.currentText().split("·")[0].strip()
                add_raster_layer(tif_path, f"QMagery — {col}", group_name="QMagery")
                self.status_bar.showMessage(f"Camada adicionada: {tif_path}", 5000)
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
