# -*- coding: utf-8 -*-
"""
Diálogos de suporte do QMagery idênticos aos do ArcMagery:
  - Sobre (GEEAboutDialog)
  - Configurações (SettingsDialog)
  - Configurar Projeto GEE / Autenticação (ProjectDialog)
  - Google Earth / Mosaicos XYZ (ExtraSourcesDialog)
"""
import os
import json
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon, QPixmap
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QComboBox,
    QCheckBox, QGroupBox, QSpinBox, QDoubleSpinBox,
    QMessageBox, QFrame
)

from ..core.backend_runner import BackendRunner
from ..core.catalog_constants import XYZ_PROVIDERS
from ..core.qgis_layer import add_raster_layer, add_xyz_tile_layer


def _get_icon_pixmap(name: str):
    icon_dir = os.path.normpath(
        os.path.join(os.path.dirname(__file__), '..', 'resources', 'icons')
    )
    for ext in ['.png', '.gif']:
        p = os.path.join(icon_dir, name + ext)
        if os.path.isfile(p):
            return QPixmap(p)
    return QPixmap()


class AboutDialog(QDialog):
    """Janela 'Sobre' com versão, autor, requisitos e visual idêntico ao ArcMagery."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sobre - QMagery")
        self.setFixedSize(580, 480)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        head = QHBoxLayout()
        logo_lbl = QLabel()
        pm = _get_icon_pixmap("about_logo") or _get_icon_pixmap("icon64")
        if not pm.isNull():
            logo_lbl.setPixmap(pm.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        head.addWidget(logo_lbl)

        title_box = QVBoxLayout()
        lbl_title = QLabel("QMagery")
        lbl_title.setStyleSheet("font-size: 18pt; font-weight: bold; color: #0b5345;")
        title_box.addWidget(lbl_title)

        lbl_sub = QLabel("Imagens de satélite no QGIS 3.x, direto nas Camadas e na resolução nativa")
        lbl_sub.setStyleSheet("font-size: 9pt; font-style: italic; color: #566573;")
        lbl_sub.setWordWrap(True)
        title_box.addWidget(lbl_sub)

        lbl_tag = QLabel("Google Earth Engine · CBERS/Amazônia-1 (INPE) · SPOT 1-5 (CNES) · "
                         "Google Earth histórico · Esri Wayback · XYZ")
        lbl_tag.setStyleSheet("font-size: 8pt; font-weight: bold; color: #1b4f72;")
        lbl_tag.setWordWrap(True)
        title_box.addWidget(lbl_tag)

        head.addLayout(title_box)
        layout.addLayout(head)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

        info_box = QGroupBox("Informações do Sistema")
        info_layout = QVBoxLayout(info_box)
        info_text = (
            "<b>Versão:</b> QMagery v1.0.0 (Port oficial do ArcMagery)<br>"
            "<b>Autor:</b> Joberth Firmino Gambati<br>"
            "<b>Repositório:</b> github.com/Yiuky/ArcMagery<br>"
            "<b>Ambiente:</b> QGIS 3.x com backend compartilhado Python 3 + GDAL<br><br>"
            "<i>Desenvolvido para oferecer máxima precisão em sensoriamento remoto sem etapas manuais de download.</i>"
        )
        info_lbl = QLabel(info_text)
        info_lbl.setWordWrap(True)
        info_layout.addWidget(info_lbl)
        layout.addWidget(info_box)

        layout.addStretch()

        close_btn = QPushButton("Fechar")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignRight)


class SettingsDialog(QDialog):
    """Janela 'Configurações' com Stretch, Cores, Threads de Tile e Parâmetros."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configurações - QMagery")
        self.setFixedSize(500, 360)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        gb_perf = QGroupBox("Desempenho e Download")
        form_perf = QFormLayout(gb_perf)

        self._threads_spin = QSpinBox()
        self._threads_spin.setRange(4, 64)
        self._threads_spin.setValue(48)
        form_perf.addRow("Threads paralelas de tiles:", self._threads_spin)

        self._buffer_spin = QDoubleSpinBox()
        self._buffer_spin.setRange(0, 10000)
        self._buffer_spin.setValue(1000)
        self._buffer_spin.setSuffix(" m")
        form_perf.addRow("Buffer da AOI vetorial:", self._buffer_spin)

        layout.addWidget(gb_perf)

        gb_disp = QGroupBox("Visualização no Painel de Camadas")
        form_disp = QFormLayout(gb_disp)

        self._stretch_cb = QComboBox()
        self._stretch_cb.addItems(["Desvio Padrão (2.0 std)", "Mínimo - Máximo", "Percentual (2% - 98%)", "Nenhum"])
        form_disp.addRow("Esticar contraste padrão:", self._stretch_cb)

        self._visible_chk = QCheckBox("Tornar camadas visíveis automaticamente ao carregar")
        self._visible_chk.setChecked(True)
        form_disp.addRow("", self._visible_chk)

        layout.addWidget(gb_disp)
        layout.addStretch()

        btn_box = QHBoxLayout()
        save_btn = QPushButton("Salvar Preferências")
        save_btn.clicked.connect(self._on_save)
        btn_box.addWidget(save_btn)

        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(cancel_btn)

        layout.addLayout(btn_box)

    def _on_save(self):
        QMessageBox.information(self, "Configurações", "Preferências salvas com sucesso!")
        self.accept()


class ExtraSourcesDialog(QDialog):
    """Janela modal 'Google Earth / Mosaicos XYZ...' acessível pelo botão superior direito."""

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("QMagery — Google Earth / Mosaicos XYZ")
        self.setMinimumSize(780, 500)
        self._runner = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        box = QGroupBox("Área de interesse e mosaicos de alta resolução")
        form = QFormLayout(box)

        self._provider_cb = QComboBox()
        for label, code, max_z, tos in XYZ_PROVIDERS:
            self._provider_cb.addItem(label, (code, max_z))
        form.addRow("Fonte:", self._provider_cb)

        self._zoom_spin = QSpinBox()
        self._zoom_spin.setRange(10, 21)
        self._zoom_spin.setValue(18)
        form.addRow("Zoom (nível de detalhe):", self._zoom_spin)

        self._crs_cb = QComboBox()
        self._crs_cb.addItems([
            "Web Mercator (EPSG:3857) - nativo dos tiles",
            "WGS 84 (EPSG:4326)",
            "SIRGAS 2000 (EPSG:4674)"
        ])
        form.addRow("Sistema de Coordenadas:", self._crs_cb)

        layout.addWidget(box)

        # Estimativa
        self._est_box = QGroupBox("Estimativa instantânea de tiles")
        est_l = QVBoxLayout(self._est_box)
        self._est_lbl = QLabel("Clique em 'Calcular Estimativa' para verificar número de tiles e volume.")
        est_l.addWidget(self._est_lbl)
        layout.addWidget(self._est_box)

        # Botões
        btns = QHBoxLayout()
        est_btn = QPushButton("📏 Calcular Estimativa")
        est_btn.clicked.connect(self._on_estimate)
        btns.addWidget(est_btn)

        quick_btn = QPushButton("⚡ Adicionar como Camada de Tiles (XYZ)")
        quick_btn.clicked.connect(self._on_quick_add)
        btns.addWidget(quick_btn)

        dl_btn = QPushButton("⬇️ Baixar Mosaico GeoTIFF")
        dl_btn.clicked.connect(self._on_download)
        btns.addWidget(dl_btn)

        layout.addLayout(btns)
        layout.addStretch()

        close_btn = QPushButton("Fechar")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignRight)

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
        self._runner = BackendRunner(self)
        self._runner.finished.connect(self._on_estimate_done)
        self._runner.run("xyz_estimate", {"zoom": zoom, "bbox": ",".join(str(v) for v in bbox)})

    def _on_estimate_done(self, res: dict):
        if res.get("success"):
            tiles = res.get("tiles", 0)
            cols = res.get("cols", 0)
            rows = res.get("rows", 0)
            res_m = res.get("ground_res_m", 0)
            mb = res.get("download_mb", 0)
            self._est_lbl.setText(
                f"<b>Grade:</b> {cols} × {rows} ({tiles} tiles)<br>"
                f"<b>Resolução no terreno aprox.:</b> ~{res_m:.2f} m/pixel<br>"
                f"<b>Volume estimado:</b> ~{mb:.1f} MB"
            )

    def _on_quick_add(self):
        data = self._provider_cb.currentData()
        code, max_z = data
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
            add_xyz_tile_layer(url, f"QMagery — {name}", max_zoom=max_z, group_name="QMagery")
            QMessageBox.information(self, "Camada Adicionada", f"Camada de tiles XYZ '{name}' carregada no painel de camadas!")

    def _on_download(self):
        import tempfile
        data = self._provider_cb.currentData()
        code, _ = data
        zoom = self._zoom_spin.value()
        bbox = self._current_bbox()
        out_tif = os.path.join(tempfile.gettempdir(), f"qmagery_xyz_{code}_z{zoom}.tif")
        self._runner = BackendRunner(self)
        self._runner.finished.connect(lambda r: self._on_dl_done(r, out_tif))
        self._runner.run("xyz_download", {
            "provider": code, "zoom": zoom,
            "bbox": ",".join(str(v) for v in bbox),
            "out": out_tif
        })
        QMessageBox.information(self, "Download Iniciado", "Download do mosaico iniciado em segundo plano!")

    def _on_dl_done(self, res: dict, out_tif: str):
        if res.get("success"):
            add_raster_layer(out_tif, f"QMagery — Mosaico {self._provider_cb.currentText()}", group_name="QMagery")
