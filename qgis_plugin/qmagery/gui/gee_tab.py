# -*- coding: utf-8 -*-
"""
Aba Google Earth Engine (GEE) da janela principal do QMagery.

Equivalente à parte GEE da gee_gui.py do ArcMagery (Tkinter → PyQt).
Estado: FASE 1 — estrutura básica + busca + download.
"""
import json
import os
from datetime import date, timedelta
from typing import Optional

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QComboBox, QPushButton,
    QDateEdit, QCheckBox, QGroupBox, QSizePolicy,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QProgressBar,
)
from qgis.PyQt.QtCore import QDate

from ..core.backend_runner import BackendRunner
from ..core.qgis_layer import add_raster_layer


_SENSORS = [
    ('Sentinel-2 (10 m)', 'S2_SR'),
    ('Landsat 9 OLI-2 (30 m)', 'L9_OLI2'),
    ('Landsat 8 OLI (30 m)', 'L8_OLI'),
    ('Landsat 7 ETM+ (30 m)', 'L7_ETM'),
    ('Landsat 5 TM (30 m)', 'L5_TM'),
    ('Landsat 4 TM (30 m)', 'L4_TM'),
    ('Landsat 1-3 MSS (60 m)', 'L13_MSS'),
    ('MODIS Terra (250 m)', 'MODIS_TERRA'),
]


class GeeTab(QWidget):
    """Aba Google Earth Engine."""

    def __init__(self, iface, status_bar, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.status_bar = status_bar
        self._runner: Optional[BackendRunner] = None
        self._info_runner: Optional[BackendRunner] = None
        self._results = []
        self._setup_ui()

    # ------------------------------------------------------------------
    # Interface
    # ------------------------------------------------------------------

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Parâmetros de busca
        form_box = QGroupBox('Parâmetros de busca')
        form = QFormLayout(form_box)

        self._sensor_cb = QComboBox()
        for label, code in _SENSORS:
            self._sensor_cb.addItem(label, code)
        form.addRow('Sensor:', self._sensor_cb)

        self._project_edit = QLineEdit()
        self._project_edit.setPlaceholderText('my-gcp-project-id')
        form.addRow('GEE Project:', self._project_edit)

        today = QDate.currentDate()
        self._start_edit = QDateEdit(today.addDays(-30))
        self._start_edit.setCalendarPopup(True)
        form.addRow('Data início:', self._start_edit)

        self._end_edit = QDateEdit(today)
        self._end_edit.setCalendarPopup(True)
        form.addRow('Data fim:', self._end_edit)

        self._cloud_cb = QCheckBox('Usar extensão atual do mapa como AOI')
        self._cloud_cb.setChecked(True)
        form.addRow('', self._cloud_cb)

        layout.addWidget(form_box)

        # Botões de ação
        btn_layout = QHBoxLayout()
        self._search_btn = QPushButton('🔍 Buscar imagens')
        self._search_btn.clicked.connect(self._on_search)
        btn_layout.addWidget(self._search_btn)
        self._download_btn = QPushButton('⬇️ Carregar no QGIS')
        self._download_btn.clicked.connect(self._on_download)
        self._download_btn.setEnabled(False)
        btn_layout.addWidget(self._download_btn)
        self._cancel_btn = QPushButton('✖ Cancelar')
        self._cancel_btn.clicked.connect(self._on_cancel)
        self._cancel_btn.setEnabled(False)
        btn_layout.addWidget(self._cancel_btn)
        layout.addLayout(btn_layout)

        # Barra de progresso
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        # Tabela de resultados
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(['ID', 'Data', 'Nuvens %', 'Coleção'])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self._table)

    # ------------------------------------------------------------------
    # Ações
    # ------------------------------------------------------------------

    def _current_bbox(self):
        """Retorna a extensão atual do mapa como [min_lon, min_lat, max_lon, max_lat]."""
        canvas = self.iface.mapCanvas()
        ext = canvas.extent()
        # Transforma para EPSG:4326 se necessário
        from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject
        src_crs = canvas.mapSettings().destinationCrs()
        wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
        if src_crs != wgs84:
            tr = QgsCoordinateTransform(src_crs, wgs84, QgsProject.instance())
            ext = tr.transformBoundingBox(ext)
        return [ext.xMinimum(), ext.yMinimum(), ext.xMaximum(), ext.yMaximum()]

    def _load_sources_info(self):
        """Carrega metadados das fontes disponíveis no backend."""
        runner = BackendRunner(self)
        runner.finished.connect(self._on_sources_info)
        runner.error.connect(lambda e: self.status_bar.showMessage(f'Aviso: {e}', 3000))
        runner.run('sources_info', {})

    def _on_sources_info(self, result: dict):
        """Recebe metadados do backend (composições, provedores, coleções)."""
        # Armazena para uso futuro nas abas
        self._sources_info = result

    def _on_search(self):
        sensor_code = self._sensor_cb.currentData()
        project = self._project_edit.text().strip()
        start = self._start_edit.date().toString('yyyy-MM-dd')
        end = self._end_edit.date().toString('yyyy-MM-dd')
        bbox = self._current_bbox() if self._cloud_cb.isChecked() else None

        params = {
            'sensor': sensor_code,
            'project': project,
            'start_date': start,
            'end_date': end,
        }
        if bbox:
            params['bbox'] = ','.join(str(v) for v in bbox)

        self._runner = BackendRunner(self)
        self._runner.progress.connect(self._on_progress)
        self._runner.finished.connect(self._on_search_result)
        self._runner.error.connect(self._on_error)
        self._set_running(True)
        self._runner.run('search', params)

    def _on_download(self):
        rows = {idx.row() for idx in self._table.selectedIndexes()}
        if not rows:
            self.status_bar.showMessage('Selecione ao menos uma imagem.', 3000)
            return
        ids = ','.join(self._results[r]['id'] for r in sorted(rows))
        sensor_code = self._sensor_cb.currentData()
        project = self._project_edit.text().strip()
        bbox = self._current_bbox()

        import tempfile
        out = os.path.join(tempfile.gettempdir(), f'qmagery_{sensor_code}.tif')
        params = {
            'ids': ids,
            'sensor': sensor_code,
            'project': project,
            'comp': 'RGB',
            'bbox': ','.join(str(v) for v in bbox),
            'out': out,
        }
        self._runner = BackendRunner(self)
        self._runner.progress.connect(self._on_progress)
        self._runner.finished.connect(self._on_download_result)
        self._runner.error.connect(self._on_error)
        self._set_running(True)
        self._runner.run('download', params)

    def _on_cancel(self):
        if self._runner:
            self._runner.cancel()
        self._set_running(False)
        self.status_bar.showMessage('Operação cancelada.', 3000)

    # ------------------------------------------------------------------
    # Callbacks do backend
    # ------------------------------------------------------------------

    def _on_progress(self, line: str):
        self.status_bar.showMessage(line.replace('[ArcGEE]', '').strip())

    def _on_search_result(self, result: dict):
        self._set_running(False)
        if not result.get('success'):
            self.status_bar.showMessage(f'Erro: {result.get("message")}', 5000)
            return
        images = result.get('images', [])
        self._results = images
        self._table.setRowCount(0)
        for img in images:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(img.get('id', '')))
            self._table.setItem(row, 1, QTableWidgetItem(img.get('date', '')))
            self._table.setItem(row, 2, QTableWidgetItem(str(img.get('cloud_cover', ''))))
            self._table.setItem(row, 3, QTableWidgetItem(img.get('collection', '')))
        self._download_btn.setEnabled(bool(images))
        self.status_bar.showMessage(f'{len(images)} imagem(ns) encontrada(s).', 5000)

    def _on_download_result(self, result: dict):
        self._set_running(False)
        if not result.get('success'):
            self.status_bar.showMessage(f'Erro: {result.get("message")}', 5000)
            return
        tif_path = result.get('file', '')
        if os.path.isfile(tif_path):
            try:
                sensor_code = self._sensor_cb.currentData()
                add_raster_layer(tif_path, f'QMagery — {sensor_code}', group_name='QMagery')
                self.status_bar.showMessage(f'Camada adicionada: {tif_path}', 5000)
            except Exception as exc:
                self.status_bar.showMessage(f'Erro ao carregar camada: {exc}', 5000)

    def _on_error(self, msg: str):
        self._set_running(False)
        self.status_bar.showMessage(f'Erro: {msg}', 8000)

    def _set_running(self, running: bool):
        self._search_btn.setEnabled(not running)
        self._download_btn.setEnabled(not running)
        self._cancel_btn.setEnabled(running)
        self._progress.setVisible(running)
