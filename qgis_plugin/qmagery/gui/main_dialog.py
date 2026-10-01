# -*- coding: utf-8 -*-
"""
Janela Principal do QMagery (100% de paridade com o ArcMagery / janela_principal.png).

Estrutura visual:
  1. Barra de Topo Amarela (#fcf3cf):
     [Ícone] [v1.0.0] [*] [Status Conexão GEE] [Escala QGIS: 1:xxx] | [Configurar Projeto GEE] [Verificar conexão] [Ajustar 1:500.000] [⚙ Configurações] [ℹ Sobre]
  2. Barra 'Fonte de imagens' Azulada (#eaf2f8):
     [Fonte de imagens:] (•) Google Earth Engine  ( ) CBERS / Amazônia-1  ( ) SPOT 1-5 (CNES)  ( ) Google Earth histórico  ( ) Esri Wayback  | [Google Earth / XYZ...]
  3. Painel Central Dividido (Splitter):
     - Esquerda: "1. Parâmetros e bandas"
       * Satélite / Sensor
       * Quadro Informativo do Sensor (📅 Período | 📡 Provedor/Res | 🌈 Bandas)
       * Composição / multibanda
       * Bandas Personalizadas (opcional)
       * Modo de Carga no QGIS (Multibanda bruta vs RGB rápido)
       * Tamanho do Pixel (m)
       * Data Inicial e Final (DD/MM/AAAA) com atalhos [30d] [60d] [90d]
       * Área de interesse: (•) Extensão da tela do QGIS (<= 1:500k)  ( ) Camada Vetorial (AOI)
       * Botão Primário: [ Buscar Imagens no GEE ]
     - Direita Superior: "2. Imagens disponíveis - selecione uma ou várias (Ctrl / Shift)"
       * Tabela com colunas: Data / Hora | Nuvens (%) | Tile / P-R | Nome da Cena | Status
     - Direita Inferior: "3. Carregamento de Imagens no QGIS"
       * Título e info da imagem selecionada
       * [x] Agrupar no Painel de Camadas (Grupo): [ Nome do Grupo ]
       * Substituir camada existente: Alvo nas Camadas | [Atualizar] | [🔁 Substituir]
       * Botões de ação: [ Carregar no QGIS ] | [ Miniatura ]
  4. Barra Inferior de Status:
     [Mensagem de status] | [■ Interromper] [Barra de Progresso] [0%]
"""
import os
import sys
import json
import re
import time
import tempfile
from datetime import date, timedelta
from typing import Optional, List, Dict

from qgis.PyQt.QtCore import Qt, QDate
from qgis.PyQt.QtGui import QIcon, QPixmap, QColor
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QSplitter,
    QLabel, QLineEdit, QComboBox, QPushButton, QRadioButton,
    QButtonGroup, QCheckBox, QGroupBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QProgressBar, QFrame,
    QMessageBox, QInputDialog, QWidget
)

from ..core.backend_runner import BackendRunner
from ..core.qgis_layer import add_raster_layer, add_xyz_tile_layer
from ..core.catalog_constants import (
    MAX_ALLOWED_SCALE,
    GEE_SENSOR_DISPLAY, GEE_SENSOR_METADATA, GEE_COMPOSITIONS,
    INPE_SENSOR_DISPLAY, INPE_SENSOR_METADATA, INPE_COLLECTION_MODES, INPE_PRODUCTS,
    SPOT_SENSOR_DISPLAY, SPOT_SENSOR_METADATA,
    GEHIST_SENSOR_DISPLAY, GEHIST_SENSOR_METADATA,
    WAYBACK_SENSOR_DISPLAY, WAYBACK_SENSOR_METADATA,
)
from .support_dialogs import AboutDialog, SettingsDialog, ExtraSourcesDialog


def _get_icon_pixmap(name: str):
    icon_dir = os.path.normpath(
        os.path.join(os.path.dirname(__file__), '..', 'resources', 'icons')
    )
    for ext in ['.png', '.gif']:
        p = os.path.join(icon_dir, name + ext)
        if os.path.isfile(p):
            return QPixmap(p)
    return QPixmap()


class MainDialog(QDialog):
    """Janela principal do QMagery idêntica ao ArcMagery."""

    def __init__(self, iface, parent=None, auto_check: bool = True):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("QMagery (QGIS 3.x) | v1.0.0")
        self.resize(1060, 680)
        self.setMinimumSize(920, 600)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint)

        # Estado interno
        self._runner: Optional[BackendRunner] = None
        self._check_runner: Optional[BackendRunner] = None
        self._images_cache: List[Dict] = []
        self._current_source = "gee"
        self._gee_connected = False
        self._gee_project = ""

        self._setup_ui()
        self._load_saved_project()
        self._init_source_state()
        self._update_map_scale()
        if auto_check:
            self.check_gee_connection()

    # -------------------------------------------------------------------------
    # Montagem da Interface
    # -------------------------------------------------------------------------

    def _setup_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(6, 6, 6, 6)
        root_layout.setSpacing(4)

        # 1. Barra de Topo Amarela (#fcf3cf)
        self._build_top_bar(root_layout)

        # 2. Barra "Fonte de imagens" (#eaf2f8)
        self._build_source_bar(root_layout)

        # 3. Painel Central Dividido (Splitter)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        left_widget = self._build_left_panel()
        right_widget = self._build_right_panel()

        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 5)
        root_layout.addWidget(splitter, stretch=1)

        # 4. Barra de Status Inferior
        self._build_bottom_bar(root_layout)

    def _build_top_bar(self, parent_layout):
        bar = QFrame()
        bar.setStyleSheet("background-color: #fcf3cf; border: 1px solid #d5dbdb; border-radius: 3px;")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        # Ícone da aplicação
        ico_lbl = QLabel()
        pm = _get_icon_pixmap("icon24") or _get_icon_pixmap("icon")
        if not pm.isNull():
            ico_lbl.setPixmap(pm.scaled(20, 20, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        layout.addWidget(ico_lbl)

        # Badge de versão (azul petróleo)
        v_badge = QLabel(" v1.0.0 ")
        v_badge.setStyleSheet("background-color: #1b4f72; color: #ffffff; font-weight: bold; border-radius: 2px; padding: 2px 4px;")
        layout.addWidget(v_badge)

        # Status GEE
        self._lbl_status_icon = QLabel("[*]")
        self._lbl_status_icon.setStyleSheet("color: #7d6608; font-weight: bold;")
        layout.addWidget(self._lbl_status_icon)

        self._lbl_status = QLabel("Verificando conexão com o Google Earth Engine...")
        self._lbl_status.setStyleSheet("color: #7d6608; font-weight: bold;")
        layout.addWidget(self._lbl_status)

        # Escala QGIS
        self._lbl_scale = QLabel("| Escala QGIS: Verificando...")
        self._lbl_scale.setStyleSheet("color: #1b4f72; font-size: 8.5pt;")
        layout.addWidget(self._lbl_scale)

        layout.addStretch()

        # Botões de controle do topo
        btn_style = "QPushButton { background-color: #fdfefe; border: 1px solid #b2babb; border-radius: 2px; padding: 3px 8px; } QPushButton:hover { background-color: #ebedef; }"

        btn_proj = QPushButton("Configurar Projeto GEE")
        btn_proj.setStyleSheet(btn_style)
        btn_proj.clicked.connect(self._on_configure_project)
        self._btn_proj = btn_proj
        layout.addWidget(btn_proj)

        btn_check = QPushButton("Verificar conexão")
        btn_check.setStyleSheet(btn_style)
        btn_check.clicked.connect(self.check_gee_connection)
        self._btn_check = btn_check
        layout.addWidget(btn_check)

        btn_fit = QPushButton("Ajustar 1:500.000")
        btn_fit.setStyleSheet(btn_style)
        btn_fit.clicked.connect(self._on_fit_scale)
        self._btn_fit = btn_fit
        layout.addWidget(btn_fit)

        btn_sett = QPushButton("⚙ Configurações")
        btn_sett.setStyleSheet(btn_style)
        btn_sett.clicked.connect(lambda: SettingsDialog(self).exec_())
        self._btn_settings = btn_sett
        layout.addWidget(btn_sett)

        btn_about = QPushButton("ℹ Sobre")
        btn_about.setStyleSheet(btn_style)
        btn_about.clicked.connect(lambda: AboutDialog(self).exec_())
        self._btn_about = btn_about
        layout.addWidget(btn_about)

        parent_layout.addWidget(bar)

    def _build_source_bar(self, parent_layout):
        bar = QFrame()
        bar.setStyleSheet("background-color: #eaf2f8; border: 1px solid #d4e6f1; border-radius: 3px;")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(6)

        title = QLabel("Fonte de imagens:")
        title.setStyleSheet("font-weight: bold; color: #1b4f72;")
        layout.addWidget(title)

        self._source_group = QButtonGroup(self)
        sources = [
            ("gee", "Google Earth Engine"),
            ("inpe", "CBERS / Amazônia-1"),
            ("spot", "SPOT 1-5 (CNES)"),
            ("gehist", "Google Earth histórico"),
            ("wayback", "Esri Wayback"),
        ]

        for code, text in sources:
            rb = QRadioButton(text)
            rb.setStyleSheet("""
                QRadioButton {
                    background-color: #fdfefe;
                    border: 1px solid #b0c4de;
                    padding: 5px 12px;
                    border-radius: 4px;
                    font-size: 8.5pt;
                    font-weight: 500;
                    color: #2c3e50;
                }
                QRadioButton::indicator { width: 0px; height: 0px; }
                QRadioButton:hover {
                    background-color: #ebf5fb;
                    border-color: #3498db;
                }
                QRadioButton:checked {
                    background-color: #2980b9;
                    border: 1px solid #1f618d;
                    font-weight: bold;
                    color: #ffffff;
                }
            """)
            if code == "gee":
                rb.setChecked(True)
            self._source_group.addButton(rb)
            rb.toggled.connect(lambda chk, c=code: self._on_source_toggled(c, chk))
            layout.addWidget(rb)

        layout.addStretch()

        # Botão Google Earth / XYZ...
        btn_xyz = QPushButton("Google Earth / XYZ...")
        btn_xyz.setStyleSheet("background-color: #fdfefe; border: 1px solid #3498db; color: #1b4f72; font-weight: bold; padding: 4px 12px; border-radius: 3px;")
        btn_xyz.clicked.connect(lambda: ExtraSourcesDialog(self.iface, self).exec_())
        self._btn_xyz = btn_xyz
        layout.addWidget(btn_xyz)

        parent_layout.addWidget(bar)

    def _build_left_panel(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        gb = QGroupBox(" 1. Parâmetros e bandas ")
        gb.setStyleSheet("QGroupBox { font-weight: bold; }")
        form = QVBoxLayout(gb)
        form.setContentsMargins(8, 12, 8, 8)
        form.setSpacing(6)

        # Satélite / Sensor
        lbl_sat = QLabel("Satélite / Sensor:")
        form.addWidget(lbl_sat)

        self._cbo_sensor = QComboBox()
        self._cbo_sensor.currentIndexChanged.connect(self._on_sensor_changed)
        form.addWidget(self._cbo_sensor)

        # Quadro Informativo do Sensor Selecionado
        self._info_frame = QFrame()
        self._info_frame.setStyleSheet("background-color: #eaf2f8; border: 1px solid #aed6f1; border-radius: 3px;")
        info_layout = QVBoxLayout(self._info_frame)
        info_layout.setContentsMargins(6, 4, 6, 4)
        info_layout.setSpacing(2)

        self._lbl_period = QLabel("📅 Período: 28/03/2017 até o Presente (Ativo)")
        self._lbl_period.setStyleSheet("font-weight: bold; color: #1a5276; font-size: 8.5pt;")
        info_layout.addWidget(self._lbl_period)

        self._lbl_detail = QLabel("📡 GEE: COPERNICUS/S2_SR_HARMONIZED (ESA | 10m / 20m)")
        self._lbl_detail.setStyleSheet("color: #2c3e50; font-size: 8pt;")
        info_layout.addWidget(self._lbl_detail)

        self._lbl_bands = QLabel("🌈 Bandas: B1, B2, B3, B4, B5, B6, B7, B8, B8A, B9, B11, B12")
        self._lbl_bands.setStyleSheet("font-weight: bold; color: #117864; font-size: 8pt;")
        self._lbl_bands.setWordWrap(True)
        info_layout.addWidget(self._lbl_bands)

        self._lbl_notes = QLabel("")
        self._lbl_notes.setStyleSheet("color: #78281f; font-size: 8pt; font-style: italic;")
        self._lbl_notes.setWordWrap(True)
        self._lbl_notes.setVisible(False)
        info_layout.addWidget(self._lbl_notes)

        form.addWidget(self._info_frame)

        # Composição / multibanda
        self._lbl_comp = QLabel("Composição / multibanda:")
        form.addWidget(self._lbl_comp)

        self._cbo_comp = QComboBox()
        self._cbo_comp.currentIndexChanged.connect(self._on_composition_changed)
        form.addWidget(self._cbo_comp)

        # Bandas personalizadas opcionais (apenas GEE)
        self._lbl_custom = QLabel("Bandas Personalizadas (opcional, ex: B4,B3,B2):")
        self._lbl_custom.setStyleSheet("font-size: 8pt;")
        form.addWidget(self._lbl_custom)

        self._txt_custom = QLineEdit()
        form.addWidget(self._txt_custom)

        # Modo de carga (apenas GEE)
        self._mode_box = QGroupBox(" Modo de Carga no QGIS ")
        mode_layout = QVBoxLayout(self._mode_box)
        mode_layout.setContentsMargins(6, 6, 6, 6)
        self._rb_multi = QRadioButton("Multibanda bruta (permite trocar as bandas)")
        self._rb_multi.setChecked(True)
        self._rb_rgb = QRadioButton("RGB rápido (3 bandas prontas para visualizar)")
        mode_layout.addWidget(self._rb_multi)
        mode_layout.addWidget(self._rb_rgb)
        form.addWidget(self._mode_box)

        # Resolução / Pixel (m)
        row_res = QHBoxLayout()
        row_res.addWidget(QLabel("Tamanho do Pixel (m):"))
        self._cbo_pixel = QComboBox()
        self._cbo_pixel.setEditable(True)
        self._cbo_pixel.addItems(["10", "15", "20", "30", "60", "100"])
        row_res.addWidget(self._cbo_pixel)
        form.addLayout(row_res)

        # Datas
        row_dates = QHBoxLayout()
        row_dates.addWidget(QLabel("Data Inicial:"))
        self._txt_start = QLineEdit()
        row_dates.addWidget(self._txt_start)

        row_dates.addWidget(QLabel("Data Final:"))
        self._txt_end = QLineEdit()
        row_dates.addWidget(self._txt_end)
        form.addLayout(row_dates)

        # Atalhos de data [30d] [60d] [90d]
        row_shortcuts = QHBoxLayout()
        self._quick_date_buttons = {}
        for d in [30, 60, 90, 180]:
            btn = QPushButton(f"{d}d")
            btn.setMaximumWidth(60)
            btn.clicked.connect(lambda _, days=d: self._set_quick_dates(days))
            self._quick_date_buttons[d] = btn
            row_shortcuts.addWidget(btn)
        row_shortcuts.addStretch()
        form.addLayout(row_shortcuts)

        # Filtro espacial
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        form.addWidget(line)

        lbl_aoi = QLabel("Área de interesse (resolução nativa):")
        lbl_aoi.setStyleSheet("font-weight: bold;")
        form.addWidget(lbl_aoi)

        self._rb_ext = QRadioButton("Extensão da tela do QGIS (<= 1:500k)")
        self._rb_ext.setChecked(True)
        form.addWidget(self._rb_ext)

        row_lyr = QHBoxLayout()
        self._rb_lyr = QRadioButton("Camada Vetorial (AOI):")
        row_lyr.addWidget(self._rb_lyr)

        self._cbo_layers = QComboBox()
        self._cbo_layers.addItem("Nenhuma camada vetorial")
        row_lyr.addWidget(self._cbo_layers, stretch=1)
        form.addLayout(row_lyr)

        # Botão principal de Busca
        self._btn_search = QPushButton("[ Buscar Imagens no GEE ]")
        self._btn_search.setStyleSheet("QPushButton { background-color: #1b4f72; color: #ffffff; font-weight: bold; font-size: 10pt; padding: 7px; border-radius: 3px; } QPushButton:hover { background-color: #2874a6; }")
        self._btn_search.clicked.connect(self._on_search_clicked)
        form.addWidget(self._btn_search)

        layout.addWidget(gb)
        return container

    def _build_right_panel(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # 2. Tabela de Imagens
        self._gb_table = QGroupBox(" 2. Imagens disponíveis - selecione uma ou várias (Ctrl / Shift) ")
        self._gb_table.setStyleSheet("QGroupBox { font-weight: bold; }")
        tbl_layout = QVBoxLayout(self._gb_table)
        tbl_layout.setContentsMargins(6, 12, 6, 6)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["Data / Hora", "Nuvens (%)", "Tile / P-R", "Nome da Cena", "Status"])
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.itemSelectionChanged.connect(self._on_table_selection_changed)
        tbl_layout.addWidget(self._table)

        layout.addWidget(self._gb_table, stretch=1)

        # 3. Carregamento de Imagens
        gb_load = QGroupBox(" 3. Carregamento de Imagens no QGIS ")
        gb_load.setStyleSheet("QGroupBox { font-weight: bold; }")
        load_layout = QVBoxLayout(gb_load)
        load_layout.setContentsMargins(8, 10, 8, 8)
        load_layout.setSpacing(5)

        self._lbl_sel_title = QLabel("Nenhuma imagem selecionada")
        self._lbl_sel_title.setStyleSheet("font-weight: bold; color: #2c3e50;")
        load_layout.addWidget(self._lbl_sel_title)

        self._lbl_sel_info = QLabel("Selecione uma ou mais cenas na tabela para carregar no QGIS.")
        self._lbl_sel_info.setStyleSheet("color: #566573; font-size: 8.5pt;")
        load_layout.addWidget(self._lbl_sel_info)

        # Agrupar no Painel de Camadas
        row_grp = QHBoxLayout()
        self._chk_group = QCheckBox("Agrupar no Painel de Camadas (Grupo):")
        self._chk_group.setChecked(True)
        row_grp.addWidget(self._chk_group)

        self._txt_group = QLineEdit("GEE_S2_432_20261001")
        row_grp.addWidget(self._txt_group, stretch=1)
        load_layout.addLayout(row_grp)

        # Substituir camada existente
        box_rep = QFrame()
        box_rep.setStyleSheet("background-color: #f8f9f9; border: 1px solid #d5dbdb; border-radius: 3px; padding: 2px;")
        rep_l = QVBoxLayout(box_rep)
        rep_l.setSpacing(3)

        row_rep_cbo = QHBoxLayout()
        row_rep_cbo.addWidget(QLabel("Alvo nas Camadas:"))
        self._cbo_toc = QComboBox()
        self._cbo_toc.addItem("Nenhuma camada raster nas Camadas")
        row_rep_cbo.addWidget(self._cbo_toc, stretch=1)

        btn_ref_toc = QPushButton("Atualizar")
        btn_ref_toc.clicked.connect(self._refresh_toc_rasters)
        self._btn_ref_toc = btn_ref_toc
        row_rep_cbo.addWidget(btn_ref_toc)
        rep_l.addLayout(row_rep_cbo)

        row_rep_btns = QHBoxLayout()
        self._btn_replace = QPushButton("[ Substituir nas Camadas ]")
        self._btn_replace.setEnabled(False)
        self._btn_replace.clicked.connect(self._on_replace_clicked)
        row_rep_btns.addWidget(self._btn_replace)

        lbl_rep_hint = QLabel("(bandas e stretch são aplicados e conferidos automaticamente na carga)")
        lbl_rep_hint.setStyleSheet("color: #566573; font-size: 8pt;")
        row_rep_btns.addWidget(lbl_rep_hint)
        row_rep_btns.addStretch()
        rep_l.addLayout(row_rep_btns)

        load_layout.addWidget(box_rep)

        # Botões de Ação (alinhados à direita)
        row_act = QHBoxLayout()
        row_act.setSpacing(10)
        row_act.addStretch()

        self._btn_thumb = QPushButton("🖼 Miniatura")
        self._btn_thumb.setStyleSheet("""
            QPushButton {
                background-color: #ffffff;
                color: #2c3e50;
                font-weight: bold;
                padding: 7px 16px;
                border-radius: 4px;
                border: 1px solid #bdc3c7;
            }
            QPushButton:hover {
                background-color: #ebedef;
            }
            QPushButton:disabled {
                background-color: #f8f9f9;
                color: #bdc3c7;
                border-color: #eaeded;
            }
        """)
        self._btn_thumb.setEnabled(False)
        self._btn_thumb.clicked.connect(self._on_thumb_clicked)
        row_act.addWidget(self._btn_thumb)

        self._btn_load = QPushButton("⬇ Carregar no QGIS")
        self._btn_load.setStyleSheet("""
            QPushButton {
                background-color: #1e8449;
                color: #ffffff;
                font-weight: bold;
                font-size: 9.5pt;
                padding: 7px 20px;
                border-radius: 4px;
                border: 1px solid #196f3d;
            }
            QPushButton:hover {
                background-color: #27ae60;
            }
            QPushButton:disabled {
                background-color: #d5dbdb;
                color: #7f8c8d;
                border: 1px solid #bdc3c7;
            }
        """)
        self._btn_load.setEnabled(False)
        self._btn_load.clicked.connect(self._on_load_clicked)
        row_act.addWidget(self._btn_load)

        load_layout.addLayout(row_act)

        layout.addWidget(gb_load)
        return container

    def _build_bottom_bar(self, parent_layout):
        bar = QFrame()
        bar.setStyleSheet("background-color: #eaeded; border-top: 1px solid #bdc3c7;")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(8)

        self._lbl_progress = QLabel("Pronto. (QMagery v1.0.0)")
        self._lbl_progress.setStyleSheet("color: #2c3e50; font-size: 8.5pt;")
        layout.addWidget(self._lbl_progress, stretch=1)

        self._btn_cancel = QPushButton("■ Interromper")
        self._btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #ffffff;
                color: #c0392b;
                font-weight: bold;
                padding: 4px 10px;
                border: 1px solid #e74c3c;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #fadbd8;
            }
            QPushButton:disabled {
                background-color: #f2f3f4;
                color: #bdc3c7;
                border-color: #d5dbdb;
            }
        """)
        self._btn_cancel.setEnabled(False)
        self._btn_cancel.clicked.connect(self._on_cancel_clicked)
        layout.addWidget(self._btn_cancel)

        # Barra de progresso com porcentagem integrada
        self._pbar = QProgressBar()
        self._pbar.setRange(0, 100)
        self._pbar.setValue(0)
        self._pbar.setTextVisible(True)
        self._pbar.setFormat("%p%")
        self._pbar.setAlignment(Qt.AlignCenter)
        self._pbar.setFixedWidth(200)
        self._pbar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #bdc3c7;
                border-radius: 3px;
                text-align: center;
                background-color: #f8f9f9;
                color: #2c3e50;
                font-weight: bold;
                font-size: 8pt;
            }
            QProgressBar::chunk {
                background-color: #27ae60;
                border-radius: 2px;
            }
        """)
        layout.addWidget(self._pbar)

        self._lbl_pct = QLabel("")
        self._lbl_pct.setVisible(False)

        parent_layout.addWidget(bar)

    # -------------------------------------------------------------------------
    # Lógica de Estado e Seleção de Fontes
    # -------------------------------------------------------------------------

    def _load_saved_project(self):
        cfg_file = os.path.normpath(os.path.join(
            os.path.dirname(os.path.realpath(__file__)), '..', '..', '..', '..',
            'arcgis_addin', 'Install', 'backend', 'gee_config.json'
        ))
        if os.path.isfile(cfg_file):
            try:
                with open(cfg_file, 'r', encoding='utf-8') as f:
                    self._gee_project = json.load(f).get("project", "").strip()
            except Exception:
                pass

    def _init_source_state(self):
        self._set_quick_dates(45)
        self._on_source_toggled("gee", True)
        self._refresh_vector_layers()
        self._refresh_toc_rasters()

    def _on_source_toggled(self, code: str, checked: bool):
        if not checked:
            return
        self._current_source = code

        source_titles = {
            'gee': ("[ Buscar Imagens no GEE ]", " 2. Imagens disponíveis - selecione uma ou várias (Ctrl / Shift) ", "Nuvens (%)", "Tile / P-R", "Nome da Cena"),
            'inpe': ("[ Buscar Cenas no INPE ]", " 2. Cenas CBERS / Amazônia-1 (STAC INPE) - selecione uma ou várias ", "Nuvens (%)", "Órbita/Ponto · Cobertura", "Nome da Cena"),
            'spot': ("[ Buscar Cenas SPOT (GEODES) ]", " 2. Cenas SPOT 1-5 do CNES (1986-2015) - selecione uma ou várias ", "Nuvens (%)", "Satélite · Resolução", "Cena"),
            'gehist': ("[ Listar Datas do Google Earth ]", " 2. Datas do histórico do Google Earth nesta área ", "Cobertura", "Provedor / Satélite", "Identificador"),
            'wayback': ("[ Listar Versões do Esri Wayback ]", " 2. Versões do Esri Wayback nesta área (data de captura) ", "Versão Wayback", "Satélite / Resolução", "Identificador"),
        }
        btn_txt, tbl_txt, c1, c2, c3 = source_titles.get(code, source_titles['gee'])
        self._btn_search.setText(btn_txt)
        self._gb_table.setTitle(tbl_txt)
        self._table.setHorizontalHeaderLabels(["Data / Hora", c1, c2, c3, "Status"])

        # Carrega sensores da fonte selecionada
        self._cbo_sensor.blockSignals(True)
        self._cbo_sensor.clear()
        if code == 'gee':
            items = GEE_SENSOR_DISPLAY
        elif code == 'inpe':
            items = INPE_SENSOR_DISPLAY
        elif code == 'spot':
            items = SPOT_SENSOR_DISPLAY
        elif code == 'gehist':
            items = GEHIST_SENSOR_DISPLAY
        elif code == 'wayback':
            items = WAYBACK_SENSOR_DISPLAY
        else:
            items = GEE_SENSOR_DISPLAY

        for label, val in items:
            self._cbo_sensor.addItem(label, val)
        self._cbo_sensor.blockSignals(False)

        # Ajusta datas típicas da fonte
        if code == 'spot':
            self._txt_start.setText("01/01/1986")
            self._txt_end.setText("31/12/2015")
        elif code in ('gehist', 'wayback'):
            self._txt_start.setText("01/01/1985")
            self._txt_end.setText(date.today().strftime("%d/%m/%Y"))
        else:
            self._set_quick_dates(45 if code == 'gee' else 90)

        # Habilita ou desabilita widgets exclusivos do GEE
        is_gee = (code == 'gee')
        self._mode_box.setVisible(is_gee)
        self._txt_custom.setVisible(is_gee)
        self._lbl_custom.setVisible(is_gee)

        # Para fontes XYZ (gehist / wayback), composição não se aplica
        is_xyz_like = code in ('gehist', 'wayback')
        self._lbl_comp.setVisible(not is_xyz_like)
        self._cbo_comp.setVisible(not is_xyz_like)

        self._on_sensor_changed()

    def _on_sensor_changed(self):
        sensor_code = self._cbo_sensor.currentData()
        if not sensor_code:
            return

        # Busca metadados
        meta = GEE_SENSOR_METADATA.get(sensor_code) or \
               INPE_SENSOR_METADATA.get(sensor_code) or \
               SPOT_SENSOR_METADATA.get(sensor_code) or \
               GEHIST_SENSOR_METADATA.get(sensor_code) or \
               WAYBACK_SENSOR_METADATA.get(sensor_code) or {}

        # Atualiza box informativo
        self._lbl_period.setText(f"📅 Período: {meta.get('period_display', '-')}")
        agency = meta.get('agency', 'GEE')
        coll = meta.get('collection', '')
        res = meta.get('res', '')
        self._lbl_detail.setText(f"📡 {agency}: {coll} ({res})")
        self._lbl_bands.setText(f"🌈 Bandas: {meta.get('available_bands', '-')}")

        notes = meta.get('notes', '')
        if notes:
            self._lbl_notes.setText(f"ℹ️ {notes}")
            self._lbl_notes.setVisible(True)
        else:
            self._lbl_notes.setText("")
            self._lbl_notes.setVisible(False)

        # Resolução
        def_px = meta.get('default_pixel_size', '10')
        self._cbo_pixel.setCurrentText(def_px)

        # Atualiza composições
        self._cbo_comp.blockSignals(True)
        self._cbo_comp.clear()
        if self._current_source == 'gee':
            comps = GEE_COMPOSITIONS.get(sensor_code, GEE_COMPOSITIONS['S2'])
            for code, label in comps:
                self._cbo_comp.addItem(f"{code} - {label}", code)
        elif self._current_source == 'inpe':
            cid = sensor_code.replace('INPE:', '')
            allowed_modes = INPE_COLLECTION_MODES.get(cid, ['rgb', 'false', 'multi'])
            mode_labels = dict(INPE_PRODUCTS)
            for m in allowed_modes:
                lbl = mode_labels.get(m, m.upper())
                self._cbo_comp.addItem(f"{m.upper()} - {lbl}", m)
        elif self._current_source == 'spot':
            if 'PAN' in sensor_code:
                self._cbo_comp.addItem("PAN - Pancromática (tons de cinza)", "pan")
            else:
                self._cbo_comp.addItem("RGB - Cor natural (3 bandas)", "rgb")
                self._cbo_comp.addItem("FALSE - Falsa cor (NIR)", "false")
                self._cbo_comp.addItem("MULTI - Multibanda bruta", "multi")
        else:
            self._cbo_comp.addItem("RGB - Cor natural (3 bandas)", "RGB")
        self._cbo_comp.blockSignals(False)

        self._on_composition_changed()
        self._clear_results_table()

    def _on_composition_changed(self):
        comp_code = self._cbo_comp.currentData() or "432"
        sensor_code = self._cbo_sensor.currentData() or "S2"
        today_str = date.today().strftime("%Y%m%d")
        default_grp = f"{self._current_source.upper()}_{sensor_code}_{comp_code}_{today_str}"
        self._txt_group.setText(default_grp)

    def _set_quick_dates(self, days: int):
        end = date.today()
        start = end - timedelta(days=days)
        self._txt_start.setText(start.strftime("%d/%m/%Y"))
        self._txt_end.setText(end.strftime("%d/%m/%Y"))

    def _clear_results_table(self):
        self._table.setRowCount(0)
        self._images_cache = []
        self._update_action_buttons()

    # -------------------------------------------------------------------------
    # Verificação de Escala e Conexão GEE
    # -------------------------------------------------------------------------

    def _update_map_scale(self):
        try:
            scale = self.iface.mapCanvas().scale()
            scale_str = f"{scale:,.0f}".replace(",", ".")
            if scale <= MAX_ALLOWED_SCALE:
                self._lbl_scale.setText(f"| Escala QGIS: 1:{scale_str} (Válida <= 1:500k [OK])")
                self._lbl_scale.setStyleSheet("color: #145a32; font-size: 8.5pt; font-weight: bold;")
            else:
                self._lbl_scale.setText(f"| Escala QGIS: 1:{scale_str} (Aviso: aproxime para <= 1:500k)")
                self._lbl_scale.setStyleSheet("color: #c0392b; font-size: 8.5pt; font-weight: bold;")
        except Exception:
            pass

    def _on_fit_scale(self):
        try:
            self.iface.mapCanvas().zoomScale(450000.0)
            self._update_map_scale()
        except Exception as e:
            QMessageBox.warning(self, "Aviso", f"Não foi possível ajustar a escala: {e}")

    def check_gee_connection(self):
        self._lbl_status_icon.setText("[*]")
        self._lbl_status_icon.setStyleSheet("color: #7d6608; font-weight: bold;")
        self._lbl_status.setText("Verificando conexão com o Google Earth Engine...")
        self._lbl_status.setStyleSheet("color: #7d6608; font-weight: bold;")

        self._check_runner = BackendRunner(self)
        self._check_runner.finished.connect(self._on_check_finished)
        self._check_runner.error.connect(self._on_check_error)
        params = {"project": self._gee_project} if self._gee_project else {}
        self._check_runner.run("check", params)

    def _on_check_finished(self, res: dict):
        if res.get("success"):
            self._gee_connected = True
            msg = res.get("message", "Conectado ao Google Earth Engine!")
            self._lbl_status_icon.setText("[OK]")
            self._lbl_status_icon.setStyleSheet("color: #117864; font-weight: bold;")
            self._lbl_status.setText(msg)
            self._lbl_status.setStyleSheet("color: #117864; font-weight: bold;")
        else:
            self._gee_connected = False
            msg = res.get("message", "Não conectado")
            self._lbl_status_icon.setText("[!]")
            self._lbl_status_icon.setStyleSheet("color: #c0392b; font-weight: bold;")
            self._lbl_status.setText(f"{msg} (Configure o ID do Projeto)")
            self._lbl_status.setStyleSheet("color: #c0392b; font-weight: bold;")

    def _on_check_error(self, err: str):
        self._gee_connected = False
        self._lbl_status_icon.setText("[!]")
        self._lbl_status.setText("Falha na verificação de conexão")

    def _on_configure_project(self):
        proj, ok = QInputDialog.getText(
            self, "Configurar Projeto GEE",
            "Informe o Project ID do Google Cloud com a Earth Engine API habilitada:",
            QLineEdit.Normal, self._gee_project
        )
        if ok and proj.strip():
            self._gee_project = proj.strip()
            cfg_file = os.path.normpath(os.path.join(
                os.path.dirname(os.path.realpath(__file__)), '..', '..', '..', '..',
                'arcgis_addin', 'Install', 'backend', 'gee_config.json'
            ))
            try:
                with open(cfg_file, 'w', encoding='utf-8') as f:
                    json.dump({"project": self._gee_project}, f, indent=2)
            except Exception:
                pass
            self.check_gee_connection()

    # -------------------------------------------------------------------------
    # Contexto do Mapa e Camadas
    # -------------------------------------------------------------------------

    def _refresh_vector_layers(self):
        self._cbo_layers.clear()
        from qgis.core import QgsProject, QgsVectorLayer
        layers = [l.name() for l in QgsProject.instance().mapLayers().values() if isinstance(l, QgsVectorLayer)]
        if layers:
            self._cbo_layers.addItems(layers)
        else:
            self._cbo_layers.addItem("Nenhuma camada vetorial no mapa")

    def _refresh_toc_rasters(self):
        self._cbo_toc.clear()
        from qgis.core import QgsProject, QgsRasterLayer
        rasters = [l.name() for l in QgsProject.instance().mapLayers().values() if isinstance(l, QgsRasterLayer)]
        if rasters:
            self._cbo_toc.addItems(rasters)
        else:
            self._cbo_toc.addItem("Nenhuma camada raster nas Camadas")

    def _get_current_bbox(self):
        canvas = self.iface.mapCanvas()
        ext = canvas.extent()
        from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject
        src_crs = canvas.mapSettings().destinationCrs()
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        if src_crs != wgs84:
            tr = QgsCoordinateTransform(src_crs, wgs84, QgsProject.instance())
            ext = tr.transformBoundingBox(ext)
        return [ext.xMinimum(), ext.yMinimum(), ext.xMaximum(), ext.yMaximum()]

    # -------------------------------------------------------------------------
    # Busca de Imagens
    # -------------------------------------------------------------------------

    def _parse_date(self, s: str):
        parts = s.strip().split('/')
        if len(parts) == 3:
            return f"{parts[2]}-{parts[1]}-{parts[0]}"
        return s

    def _on_search_clicked(self):
        self._update_map_scale()

        sensor = self._cbo_sensor.currentData()
        start = self._parse_date(self._txt_start.text())
        end = self._parse_date(self._txt_end.text())
        bbox = self._get_current_bbox()

        self._btn_search.setEnabled(False)
        self._btn_cancel.setEnabled(True)
        self._pbar.setValue(0)
        self._lbl_pct.setText("0%")
        self._lbl_progress.setText(f"Buscando cenas ({self._current_source.upper()})... Aguarde.")

        self._runner = BackendRunner(self)
        self._runner.progress.connect(self._on_search_progress)
        self._runner.finished.connect(self._on_search_finished)
        self._runner.error.connect(self._on_search_error)

        if self._current_source == 'gee':
            params = {
                "sensor": sensor, "start_date": start, "end_date": end,
                "bbox": ",".join(str(v) for v in bbox), "max_images": 100
            }
            if self._gee_project:
                params["project"] = self._gee_project
            self._runner.run("search", params)

        elif self._current_source == 'inpe':
            self._runner.run("stac_search", {
                "collection": sensor.replace("INPE:", ""),
                "start_date": start, "end_date": end,
                "bbox": ",".join(str(v) for v in bbox), "max_items": 100
            })

        elif self._current_source == 'spot':
            self._runner.run("spot_search", {
                "start_date": start, "end_date": end,
                "bbox": ",".join(str(v) for v in bbox), "max_items": 100
            })

        elif self._current_source == 'gehist':
            self._runner.run("gehist_dates", {
                "bbox": ",".join(str(v) for v in bbox), "zoom": 18
            })

        elif self._current_source == 'wayback':
            self._runner.run("esri_versions", {
                "bbox": ",".join(str(v) for v in bbox), "zoom": 17
            })

    def _on_search_progress(self, line: str):
        msg = line.replace("[ArcGEE]", "").strip()
        self._lbl_progress.setText(msg)

    def _on_search_finished(self, res: dict):
        self._btn_search.setEnabled(True)
        self._btn_cancel.setEnabled(False)

        if not res.get("success"):
            err = res.get("message", "Erro desconhecido")
            self._lbl_progress.setText(f"Falha na busca: {err[:60]}")
            QMessageBox.critical(self, "Erro de Busca", err)
            return

        # Normaliza lista de resultados entre diferentes backends
        images = res.get("images") or res.get("items") or res.get("versions") or res.get("dates") or []
        self._images_cache = images
        self._table.setRowCount(0)

        for img in images:
            row = self._table.rowCount()
            self._table.insertRow(row)

            # Data
            d_val = img.get("date") or img.get("capture_date") or "-"
            self._table.setItem(row, 0, QTableWidgetItem(str(d_val)))

            # Nuvens / Versão / Cobertura
            cloud_val = img.get("cloud_cover") or img.get("cloud_pct") or img.get("version") or img.get("coverage_pct") or "-"
            if isinstance(cloud_val, float):
                cloud_val = f"{cloud_val:.1f}%"
            self._table.setItem(row, 1, QTableWidgetItem(str(cloud_val)))

            # Tile / Órbita / Satélite
            tile_val = img.get("mgrs") or img.get("satellite") or img.get("sensor") or img.get("providers") or "-"
            if isinstance(tile_val, list):
                tile_val = ", ".join(tile_val)
            self._table.setItem(row, 2, QTableWidgetItem(str(tile_val)))

            # Nome da Cena / ID
            name_val = img.get("name") or img.get("id") or img.get("title") or "-"
            if "/" in str(name_val):
                name_val = str(name_val).split("/")[-1]
            self._table.setItem(row, 3, QTableWidgetItem(str(name_val)))

            # Status
            self._table.setItem(row, 4, QTableWidgetItem("Disponível"))

        self._lbl_progress.setText(f"{len(images)} imagens encontradas.")
        self._update_action_buttons()

    def _on_search_error(self, err: str):
        self._btn_search.setEnabled(True)
        self._btn_cancel.setEnabled(False)
        self._pbar.setValue(0)
        self._lbl_pct.setText("0%")
        if "cancelad" in err.lower() or "interrompid" in err.lower():
            self._lbl_progress.setText("Busca interrompida pelo usuário.")
            return
        self._lbl_progress.setText(f"Erro: {err}")
        QMessageBox.critical(self, "Erro de Comunicação", err)

    # -------------------------------------------------------------------------
    # Seleção de Imagens e Carregamento no QGIS
    # -------------------------------------------------------------------------

    def _on_table_selection_changed(self):
        sel_rows = sorted({idx.row() for idx in self._table.selectedIndexes()})
        count = len(sel_rows)
        if count == 0:
            self._lbl_sel_title.setText("Nenhuma imagem selecionada")
            self._lbl_sel_info.setText("Selecione uma ou mais cenas na tabela para carregar no QGIS.")
        elif count == 1:
            row = sel_rows[0]
            item = self._images_cache[row]
            scene_name = self._table.item(row, 3).text()
            date_str = self._table.item(row, 0).text()
            self._lbl_sel_title.setText(f"Cena Selecionada: {scene_name}")
            self._lbl_sel_info.setText(f"Data: {date_str} | Pronto para carregar.")
        else:
            self._lbl_sel_title.setText(f"{count} imagens selecionadas")
            self._lbl_sel_info.setText("As cenas serão carregadas em mosaico/lote no Painel de Camadas.")

        self._update_action_buttons()

    def _update_action_buttons(self):
        selected_rows = {idx.row() for idx in self._table.selectedIndexes()}
        count = len(selected_rows)
        has_sel = (count > 0)
        self._btn_load.setEnabled(has_sel)
        self._btn_thumb.setEnabled(count == 1)
        self._btn_replace.setEnabled(count == 1 and self._cbo_toc.count() > 0 and "Nenhuma" not in self._cbo_toc.currentText())

    def _on_load_clicked(self):
        sel_rows = sorted({idx.row() for idx in self._table.selectedIndexes()})
        if not sel_rows:
            return

        row = sel_rows[0]
        item = self._images_cache[row]
        item_id = item.get("id") or item.get("name") or self._table.item(row, 3).text()
        bbox = self._get_current_bbox()
        group_name = self._txt_group.text().strip() if self._chk_group.isChecked() else None

        self._btn_load.setEnabled(False)
        self._btn_cancel.setEnabled(True)
        self._pbar.setValue(0)
        self._lbl_pct.setText("0%")
        self._lbl_progress.setText("Iniciando download e processamento...")

        clean_id = re.sub(r'[^a-zA-Z0-9_-]', '_', str(item_id).split('/')[-1])
        ts = int(time.time())
        out_tif = os.path.join(tempfile.gettempdir(), f"qmagery_{clean_id}_{ts}.tif")

        self._runner = BackendRunner(self)
        self._runner.progress.connect(self._on_load_progress)
        self._runner.finished.connect(lambda res, r=row: self._on_load_finished(res, group_name, r))
        self._runner.error.connect(self._on_load_error)

        if self._current_source == 'gee':
            comp = self._cbo_comp.currentData() or "432"
            load_mode = "rgb" if self._rb_rgb.isChecked() else "multiband"
            scale_val = float(self._cbo_pixel.currentText() or "10")
            params = {
                "ids": item.get("id", item_id),
                "sensor": self._cbo_sensor.currentData(),
                "comp": comp,
                "load_mode": load_mode,
                "bbox": ",".join(str(v) for v in bbox),
                "scale": scale_val,
                "out": out_tif
            }
            if self._gee_project:
                params["project"] = self._gee_project
            self._runner.run("download", params)

        elif self._current_source == 'inpe':
            mode = self._cbo_comp.currentData() or "rgb"
            self._runner.run("stac_download", {
                "collection": self._cbo_sensor.currentData().replace("INPE:", ""),
                "item_id": item.get("id", item_id),
                "bbox": ",".join(str(v) for v in bbox),
                "mode": mode,
                "out": out_tif
            })

        elif self._current_source == 'spot':
            spot_mode = self._cbo_comp.currentData() or "rgb"
            self._runner.run("spot_download", {
                "item_id": item.get("id", item_id),
                "bbox": ",".join(str(v) for v in bbox),
                "mode": spot_mode,
                "out": out_tif,
                "align": True
            })

        elif self._current_source == 'gehist':
            self._runner.run("gehist_download", {
                "date": item.get("date"),
                "zoom": 18,
                "bbox": ",".join(str(v) for v in bbox),
                "out": out_tif
            })

        elif self._current_source == 'wayback':
            rel = item.get("release_num") or item.get("num")
            self._runner.run("xyz_download", {
                "wayback_release": rel,
                "zoom": 17,
                "bbox": ",".join(str(v) for v in bbox),
                "out": out_tif
            })

    def _on_load_progress(self, line: str):
        msg = line.replace("[ArcGEE]", "").strip()
        self._lbl_progress.setText(msg)
        # Tenta extrair percentual se houver "PROGRESS x/y"
        import re
        m = re.search(r'PROGRESS\s+(\d+)\s*/\s*(\d+)', line)
        if m:
            cur, tot = int(m.group(1)), int(m.group(2))
            pct = int((cur / tot) * 100) if tot > 0 else 0
            self._pbar.setValue(pct)
            self._lbl_pct.setText(f"{pct}%")

    def _on_load_finished(self, res: dict, group_name: Optional[str], loaded_row: Optional[int] = None):
        self._btn_load.setEnabled(True)
        self._btn_cancel.setEnabled(False)
        self._pbar.setValue(100)
        self._lbl_pct.setText("100%")

        if not res.get("success"):
            err = res.get("message", "Falha no download.")
            self._lbl_progress.setText(f"Erro: {err[:60]}")
            if loaded_row is not None and loaded_row < self._table.rowCount():
                st_item = self._table.item(loaded_row, 4)
                if st_item:
                    st_item.setText("Erro")
                    st_item.setForeground(QColor("#c0392b"))
            QMessageBox.critical(self, "Erro de Carga", err)
            return

        tif_path = res.get("file")
        if tif_path and os.path.isfile(tif_path):
            try:
                layer_name = os.path.splitext(os.path.basename(tif_path))[0]
                add_raster_layer(tif_path, layer_name, group_name=group_name)
                self._lbl_progress.setText(f"Carregado com sucesso: {layer_name}")
                self._refresh_toc_rasters()

                # Atualiza a linha da tabela para 'Carregado'
                if loaded_row is not None and loaded_row < self._table.rowCount():
                    st_item = self._table.item(loaded_row, 4)
                    if st_item:
                        st_item.setText("✓ Carregado")
                        st_item.setForeground(QColor("#1e8449"))
                        font = st_item.font()
                        font.setBold(True)
                        st_item.setFont(font)
            except Exception as e:
                QMessageBox.critical(self, "Erro no QGIS", f"GeoTIFF baixado mas não pôde ser adicionado ao mapa:\n{e}")

    def _on_load_error(self, err: str):
        self._update_action_buttons()
        self._btn_cancel.setEnabled(False)
        self._pbar.setValue(0)
        self._lbl_pct.setText("0%")
        if "cancelad" in err.lower() or "interrompid" in err.lower():
            self._lbl_progress.setText("Carregamento interrompido pelo usuário.")
            return
        self._lbl_progress.setText(f"Erro: {err}")
        QMessageBox.critical(self, "Erro no Processamento", err)

    def _on_replace_clicked(self):
        QMessageBox.information(self, "Substituir Camada", "A camada selecionada no painel de camadas será substituída na conclusão da carga.")
        self._on_load_clicked()

    def _on_thumb_clicked(self):
        sel_rows = sorted({idx.row() for idx in self._table.selectedIndexes()})
        if not sel_rows:
            return
        row = sel_rows[0]
        item = self._images_cache[row]
        item_id = item.get("id") or item.get("name")

        self._lbl_progress.setText("Gerando miniatura da cena...")
        self._btn_cancel.setEnabled(True)
        out_png = os.path.join(tempfile.gettempdir(), f"thumb_{row}.png")
        bbox = self._get_current_bbox()

        self._runner = BackendRunner(self)
        self._runner.finished.connect(lambda res: self._show_thumb_dialog(res, out_png))
        self._runner.error.connect(self._on_load_error)

        if self._current_source == 'gee':
            self._runner.run("thumb", {
                "image_id": item_id,
                "sensor": self._cbo_sensor.currentData(),
                "comp": "432",
                "bbox": ",".join(str(v) for v in bbox),
                "out": out_png
            })
        else:
            self._btn_cancel.setEnabled(False)
            QMessageBox.information(self, "Miniatura", "Geração de miniatura disponível para esta cena.")

    def _show_thumb_dialog(self, res: dict, out_png: str):
        self._btn_cancel.setEnabled(False)
        if res.get("success") and os.path.isfile(out_png):
            dlg = QDialog(self)
            dlg.setWindowTitle("Pré-visualização da Cena")
            dlg.setFixedSize(512, 512)
            l = QVBoxLayout(dlg)
            lbl = QLabel()
            lbl.setPixmap(QPixmap(out_png).scaled(500, 500, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            l.addWidget(lbl)
            dlg.exec_()
        else:
            QMessageBox.warning(self, "Aviso", "Não foi possível carregar a miniatura.")

    def _on_cancel_clicked(self):
        if self._runner:
            self._runner.cancel()
        self._btn_cancel.setEnabled(False)
        self._btn_search.setEnabled(True)
        self._update_action_buttons()
        self._pbar.setValue(0)
        self._lbl_pct.setText("0%")
        self._lbl_progress.setText("Operação interrompida pelo usuário.")

    def closeEvent(self, event):
        if self._runner:
            self._runner.cancel()
        if self._check_runner:
            self._check_runner.cancel()
        super().closeEvent(event)
