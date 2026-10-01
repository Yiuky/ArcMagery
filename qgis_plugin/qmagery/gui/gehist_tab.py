# -*- coding: utf-8 -*-
"""
Aba Google Earth Histórico (GEHistTab) da janela principal do QMagery.
Permite buscar datas históricas do Google Earth e descarregar mosaicos na grade nativa Keyhole.
"""
import os
import tempfile
from typing import Optional

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QCheckBox, QGroupBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QProgressBar, QSpinBox
)

from ..core.backend_runner import BackendRunner
from ..core.qgis_layer import add_raster_layer


class GEHistTab(QWidget):
    """Aba Google Earth Histórico."""

    def __init__(self, iface, status_bar, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.status_bar = status_bar
        self._runner: Optional[BackendRunner] = None
        self._results = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        form_box = QGroupBox("Google Earth Histórico (por data)")
        form = QFormLayout(form_box)

        self._zoom_spin = QSpinBox()
        self._zoom_spin.setRange(10, 20)
        self._zoom_spin.setValue(18)
        form.addRow("Nível de Zoom / Detalhe:", self._zoom_spin)

        self._use_canvas_cb = QCheckBox("Usar extensão atual do mapa")
        self._use_canvas_cb.setChecked(True)
        form.addRow("", self._use_canvas_cb)

        layout.addWidget(form_box)

        # Botões
        btn_layout = QHBoxLayout()
        self._search_btn = QPushButton("🔍 Consultar Datas Disponíveis")
        self._search_btn.clicked.connect(self._on_search)
        btn_layout.addWidget(self._search_btn)

        self._download_btn = QPushButton("⬇️ Baixar Imagem da Data Selecionada")
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
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Data de Captura", "Cobertura da Área %", "Provedores", "Zoom"])
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
        bbox = self._current_bbox()
        zoom = self._zoom_spin.value()
        params = {
            "bbox": ",".join(str(v) for v in bbox),
            "zoom": zoom
        }
        self._runner = BackendRunner(self)
        self._runner.progress.connect(self._on_progress)
        self._runner.finished.connect(self._on_search_result)
        self._runner.error.connect(self._on_error)
        self._set_running(True)
        self._runner.run("gehist_dates", params)

    def _on_download(self):
        rows = {idx.row() for idx in self._table.selectedIndexes()}
        if not rows:
            self.status_bar.showMessage("Selecione uma data para baixar.", 3000)
            return

        row = sorted(rows)[0]
        item = self._results[row]
        date_str = item.get("date")
        zoom = self._zoom_spin.value()
        bbox = self._current_bbox()

        out_path = os.path.join(tempfile.gettempdir(), f"gehist_{date_str}_z{zoom}.tif")
        params = {
            "date": date_str,
            "zoom": zoom,
            "bbox": ",".join(str(v) for v in bbox),
            "out": out_path
        }

        self._runner = BackendRunner(self)
        self._runner.progress.connect(self._on_progress)
        self._runner.finished.connect(self._on_download_result)
        self._runner.error.connect(self._on_error)
        self._set_running(True)
        self._runner.run("gehist_download", params)

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
            self.status_bar.showMessage(f"Erro na consulta de datas: {result.get('message')}", 5000)
            return

        dates = result.get("dates", [])
        self._results = dates
        self._table.setRowCount(0)
        for d in dates:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(str(d.get("date", ""))))
            cov = d.get("coverage_pct")
            cov_str = f"{cov:.1f}%" if cov is not None else "-"
            self._table.setItem(row, 1, QTableWidgetItem(cov_str))
            provs = ", ".join(d.get("providers", [])) if isinstance(d.get("providers"), list) else str(d.get("providers", "-"))
            self._table.setItem(row, 2, QTableWidgetItem(provs))
            self._table.setItem(row, 3, QTableWidgetItem(str(d.get("zoom", self._zoom_spin.value()))))

        self._download_btn.setEnabled(bool(dates))
        self.status_bar.showMessage(f"{len(dates)} data(s) histórica(s) encontrada(s).", 5000)

    def _on_download_result(self, result: dict):
        self._set_running(False)
        if not result.get("success"):
            self.status_bar.showMessage(f"Erro no download: {result.get('message')}", 6000)
            return

        tif_path = result.get("file")
        if tif_path and os.path.isfile(tif_path):
            try:
                date_str = result.get("capture_summary", "Histórico")
                add_raster_layer(tif_path, f"QMagery Google Earth — {date_str}", group_name="QMagery")
                self.status_bar.showMessage(f"Imagem histórica carregada: {tif_path}", 5000)
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
