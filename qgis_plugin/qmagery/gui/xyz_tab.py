# -*- coding: utf-8 -*-
"""
Aba Google Earth / Mosaicos XYZ (Esri, Bing, Google) da janela principal do QMagery.
Permite estimar e baixar mosaicos georreferenciados de alta resolução direto no QGIS.
"""
import os
import tempfile
from typing import Optional

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QComboBox, QPushButton, QCheckBox,
    QGroupBox, QSpinBox, QProgressBar, QMessageBox
)

from ..core.backend_runner import BackendRunner
from ..core.qgis_layer import add_raster_layer, add_xyz_tile_layer


XYZ_PROVIDERS = [
    ("Google Earth / Satélite", "google", 21, True),
    ("Google Híbrido (satélite + rótulos)", "google-hybrid", 21, True),
    ("Esri World Imagery", "esri", 19, False),
    ("Esri World Imagery (Clarity)", "esri-clarity", 19, False),
    ("Bing Aerial", "bing", 19, True),
]

TOS_WARNING = (
    "Atenção: O download em massa de tiles do Google e Bing fora das APIs oficiais "
    "pode infringir os Termos de Serviço dos provedores.\n\n"
    "Deseja continuar com o download do mosaico?"
)


class XyzTab(QWidget):
    """Aba Google / XYZ / Esri / Bing."""

    def __init__(self, iface, status_bar, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.status_bar = status_bar
        self._runner: Optional[BackendRunner] = None
        self._estimate = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        form_box = QGroupBox("Configurações do Mosaico XYZ")
        form = QFormLayout(form_box)

        self._provider_cb = QComboBox()
        for label, code, max_z, tos in XYZ_PROVIDERS:
            self._provider_cb.addItem(label, (code, max_z, tos))
        self._provider_cb.currentIndexChanged.connect(self._on_provider_changed)
        form.addRow("Provedor:", self._provider_cb)

        self._zoom_spin = QSpinBox()
        self._zoom_spin.setRange(1, 21)
        self._zoom_spin.setValue(17)
        self._zoom_spin.valueChanged.connect(self._clear_estimate)
        form.addRow("Nível de Zoom:", self._zoom_spin)

        self._use_canvas_cb = QCheckBox("Usar extensão atual do mapa")
        self._use_canvas_cb.setChecked(True)
        form.addRow("", self._use_canvas_cb)

        layout.addWidget(form_box)

        # Painel de Estimativa
        self._est_box = QGroupBox("Estimativa da Área")
        est_layout = QVBoxLayout(self._est_box)
        self._est_label = QLabel("Clique em 'Calcular Estimativa' para verificar a quantidade de tiles.")
        self._est_label.setWordWrap(True)
        est_layout.addWidget(self._est_label)
        layout.addWidget(self._est_box)

        # Botões
        btn_layout = QHBoxLayout()
        self._est_btn = QPushButton("📏 Calcular Estimativa")
        self._est_btn.clicked.connect(self._on_estimate)
        btn_layout.addWidget(self._est_btn)

        self._download_btn = QPushButton("⬇️ Baixar Mosaico GeoTIFF")
        self._download_btn.clicked.connect(self._on_download)
        btn_layout.addWidget(self._download_btn)

        self._quick_add_btn = QPushButton("⚡ Adicionar como Camada de Tiles (XYZ)")
        self._quick_add_btn.setToolTip("Adiciona a camada XYZ em tempo real no QGIS sem baixar arquivos GeoTIFF")
        self._quick_add_btn.clicked.connect(self._on_quick_add)
        btn_layout.addWidget(self._quick_add_btn)

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

        layout.addStretch()

    def _on_provider_changed(self):
        data = self._provider_cb.currentData()
        if data:
            code, max_z, tos = data
            self._zoom_spin.setMaximum(max_z)
        self._clear_estimate()

    def _clear_estimate(self):
        self._estimate = None
        self._est_label.setText("Clique em 'Calcular Estimativa' para verificar a quantidade de tiles.")

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

    def _on_estimate(self):
        bbox = self._current_bbox()
        zoom = self._zoom_spin.value()
        params = {
            "zoom": zoom,
            "bbox": ",".join(str(v) for v in bbox)
        }
        self._runner = BackendRunner(self)
        self._runner.finished.connect(self._on_estimate_result)
        self._runner.error.connect(self._on_error)
        self._set_running(True)
        self._runner.run("xyz_estimate", params)

    def _on_estimate_result(self, result: dict):
        self._set_running(False)
        if not result.get("success"):
            self.status_bar.showMessage(f"Erro na estimativa: {result.get('message')}", 5000)
            return

        self._estimate = result
        tiles = result.get("tiles", 0)
        cols = result.get("cols", 0)
        rows = result.get("rows", 0)
        res_m = result.get("ground_res_m", 0)
        mb = result.get("download_mb", 0)
        self._est_label.setText(
            f"<b>Grade:</b> {cols} × {rows} ({tiles} tiles)<br>"
            f"<b>Resolução no terreno aprox.:</b> ~{res_m:.2f} m/pixel<br>"
            f"<b>Volume estimado de download:</b> ~{mb:.1f} MB"
        )
        self.status_bar.showMessage(f"Estimativa concluída: {tiles} tiles.", 4000)

    def _on_download(self):
        data = self._provider_cb.currentData()
        code, max_z, tos = data

        if tos:
            reply = QMessageBox.question(
                self, "Termos de Uso", TOS_WARNING,
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

        bbox = self._current_bbox()
        zoom = self._zoom_spin.value()
        out_path = os.path.join(tempfile.gettempdir(), f"mosaico_{code}_z{zoom}.tif")

        params = {
            "provider": code,
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
        """Adiciona conexão nativa XYZ Tiles do QGIS sem download GeoTIFF."""
        data = self._provider_cb.currentData()
        code, max_z, _ = data
        name = self._provider_cb.currentText()

        urls = {
            "google": "https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
            "google-hybrid": "https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
            "esri": "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            "esri-clarity": "https://clarity.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            "bing": "https://ecn.t3.tiles.virtualearth.net/tiles/a{q}.jpeg?g=1"
        }
        url = urls.get(code)
        if url and code != "bing":
            try:
                add_xyz_tile_layer(url, f"QMagery XYZ — {name}", max_zoom=max_z, group_name="QMagery")
                self.status_bar.showMessage(f"Camada XYZ adicionada ao mapa: {name}", 4000)
            except Exception as e:
                self.status_bar.showMessage(f"Erro ao adicionar camada: {e}", 5000)
        else:
            self.status_bar.showMessage("Use o botão de download para esta fonte.", 4000)

    def _on_cancel(self):
        if self._runner:
            self._runner.cancel()
        self._set_running(False)
        self.status_bar.showMessage("Operação cancelada.", 3000)

    def _on_progress(self, line: str):
        self.status_bar.showMessage(line.replace("[ArcGEE]", "").strip())

    def _on_download_result(self, result: dict):
        self._set_running(False)
        if not result.get("success"):
            self.status_bar.showMessage(f"Erro: {result.get('message')}", 6000)
            return

        tif_path = result.get("file")
        if tif_path and os.path.isfile(tif_path):
            try:
                prov_name = self._provider_cb.currentText()
                add_raster_layer(tif_path, f"QMagery — {prov_name}", group_name="QMagery")
                self.status_bar.showMessage(f"Mosaico carregado com sucesso: {tif_path}", 5000)
            except Exception as exc:
                self.status_bar.showMessage(f"Erro ao carregar no QGIS: {exc}", 5000)

    def _on_error(self, msg: str):
        self._set_running(False)
        self.status_bar.showMessage(f"Erro: {msg}", 8000)

    def _set_running(self, running: bool):
        self._est_btn.setEnabled(not running)
        self._download_btn.setEnabled(not running)
        self._quick_add_btn.setEnabled(not running)
        self._cancel_btn.setEnabled(running)
        self._progress.setVisible(running)
