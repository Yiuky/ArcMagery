# -*- coding: utf-8 -*-
"""
Aba Esri Wayback da janela principal do QMagery.
Permite consultar versões do Esri World Imagery desde 2014 com data de captura e satélite.
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
from ..core.qgis_layer import add_raster_layer, add_xyz_tile_layer


class WaybackTab(QWidget):
    """Aba Esri Wayback."""

    def __init__(self, iface, status_bar, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.status_bar = status_bar
        self._runner: Optional[BackendRunner] = None
        self._results = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        form_box = QGroupBox("Parâmetros do Esri Wayback")
        form = QFormLayout(form_box)

        self._zoom_spin = QSpinBox()
        self._zoom_spin.setRange(14, 19)
        self._zoom_spin.setValue(17)
        form.addRow("Nível de Zoom:", self._zoom_spin)

        self._use_canvas_cb = QCheckBox("Usar extensão atual do mapa")
        self._use_canvas_cb.setChecked(True)
        form.addRow("", self._use_canvas_cb)

        layout.addWidget(form_box)

        # Botões
        btn_layout = QHBoxLayout()
        self._search_btn = QPushButton("🔍 Consultar Versões Wayback")
        self._search_btn.clicked.connect(self._on_search)
        btn_layout.addWidget(self._search_btn)

        self._download_btn = QPushButton("⬇️ Baixar Mosaico GeoTIFF")
        self._download_btn.clicked.connect(self._on_download)
        self._download_btn.setEnabled(False)
        btn_layout.addWidget(self._download_btn)

        self._quick_btn = QPushButton("⚡ Adicionar como Camada XYZ")
        self._quick_btn.clicked.connect(self._on_quick_add)
        self._quick_btn.setEnabled(False)
        btn_layout.addWidget(self._quick_btn)

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
        self._table.setHorizontalHeaderLabels(["Data de Captura", "Versão / Lançamento", "Satélite / Fonte", "Resolução"])
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
        self._runner.run("esri_versions", params)

    def _on_download(self):
        rows = {idx.row() for idx in self._table.selectedIndexes()}
        if not rows:
            self.status_bar.showMessage("Selecione uma versão para baixar.", 3000)
            return

        row = sorted(rows)[0]
        ver = self._results[row]
        rel_num = ver.get("release_num") or ver.get("num")
        cap_date = ver.get("capture_date") or ver.get("date", "Wayback")
        zoom = self._zoom_spin.value()
        bbox = self._current_bbox()

        out_path = os.path.join(tempfile.gettempdir(), f"wayback_{rel_num}_z{zoom}.tif")
        params = {
            "wayback_release": rel_num,
            "zoom": zoom,
            "bbox": ",".join(str(v) for v in bbox),
            "out": out_path
        }

        self._runner = BackendRunner(self)
        self._runner.progress.connect(self._on_progress)
        self._runner.finished.connect(self._on_download_result)
        self._runner.error.connect(self._on_error)
        self._set_running(True)
        self._runner.run("xyz_download", params)

    def _on_quick_add(self):
        rows = {idx.row() for idx in self._table.selectedIndexes()}
        if not rows:
            return
        row = sorted(rows)[0]
        ver = self._results[row]
        url = ver.get("tile_url")
        cap_date = ver.get("capture_date") or ver.get("date", "Wayback")
        if url:
            try:
                add_xyz_tile_layer(url, f"QMagery Wayback — {cap_date}", max_zoom=self._zoom_spin.value(), group_name="QMagery")
                self.status_bar.showMessage(f"Camada XYZ Wayback adicionada: {cap_date}", 4000)
            except Exception as e:
                self.status_bar.showMessage(f"Erro: {e}", 5000)

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
            self.status_bar.showMessage(f"Erro na consulta Wayback: {result.get('message')}", 5000)
            return

        versions = result.get("versions", [])
        self._results = versions
        self._table.setRowCount(0)
        for v in versions:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(str(v.get("capture_date", v.get("date", "")))))
            self._table.setItem(row, 1, QTableWidgetItem(str(v.get("title", f"Release {v.get('num', '')}"))))
            self._table.setItem(row, 2, QTableWidgetItem(str(v.get("sensor", v.get("provider", "-")))))
            self._table.setItem(row, 3, QTableWidgetItem(str(v.get("resolution", "-"))))

        has_items = bool(versions)
        self._download_btn.setEnabled(has_items)
        self._quick_btn.setEnabled(has_items)
        self.status_bar.showMessage(f"{len(versions)} versão(ões) Wayback encontrada(s).", 5000)

    def _on_download_result(self, result: dict):
        self._set_running(False)
        if not result.get("success"):
            self.status_bar.showMessage(f"Erro no download: {result.get('message')}", 6000)
            return

        tif_path = result.get("file")
        if tif_path and os.path.isfile(tif_path):
            try:
                date_str = result.get("wayback_date", "Wayback")
                add_raster_layer(tif_path, f"QMagery Wayback — {date_str}", group_name="QMagery")
                self.status_bar.showMessage(f"GeoTIFF Wayback carregado: {tif_path}", 5000)
            except Exception as exc:
                self.status_bar.showMessage(f"Erro ao carregar no QGIS: {exc}", 5000)

    def _on_error(self, msg: str):
        self._set_running(False)
        self.status_bar.showMessage(f"Erro: {msg}", 8000)

    def _set_running(self, running: bool):
        self._search_btn.setEnabled(not running)
        self._download_btn.setEnabled(not running)
        self._quick_btn.setEnabled(not running)
        self._cancel_btn.setEnabled(running)
        self._progress.setVisible(running)
