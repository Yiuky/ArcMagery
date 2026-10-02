# -*- coding: utf-8 -*-
"""
Janela principal do QMagery (mesmo arranjo da janela do ArcMagery).

  Topo ........ versão, conexão com o Earth Engine, escala do mapa e configurações
  Fontes ...... Google Earth Engine | CBERS / Amazônia-1 | SPOT 1-5 | Google Earth histórico | Esri Wayback
  Esquerda .... 1. sensor, composição, período e área de interesse -> Buscar
  Direita ..... 2. tabela de cenas (seleção múltipla) e 3. carregamento (grupo, substituir, miniatura)
  Rodapé ...... progresso e Interromper

As regras de cada fonte (parâmetros do backend e linhas da tabela) ficam em core/sources.py.
"""
import json
import os
import tempfile
from datetime import date, timedelta

from qgis.PyQt.QtCore import QDate, QTimer, Qt, QUrl
from qgis.PyQt.QtGui import QColor, QDesktopServices, QPixmap
from qgis.PyQt.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDateEdit, QDialog, QFrame, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QRadioButton,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..core import config, sources
from ..core import catalog_constants as cat
from ..core.backend_runner import CANCELLED_MESSAGE, BackendRunner
from ..core.qgis_layer import add_raster_layer, apply_style, raster_layers
from .support_dialogs import AboutDialog, ExtraSourcesDialog, GeeProjectDialog, GeodesKeyDialog, SettingsDialog

ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'resources', 'icons')

STATUS_COLORS = {'ok': '#1e8449', 'err': '#c0392b', 'run': '#1f618d', 'wait': '#7d6608'}

TABLE_HEADERS = {
    'gee': ("Data / hora", "Nuvens", "Tile / órbita-ponto", "Cena"),
    'inpe': ("Data", "Nuvens", "Órbita/ponto · cobertura", "Cena"),
    'spot': ("Data", "Nuvens", "Satélite · resolução · cobertura", "Cena"),
    'gehist': ("Data", "Cobertura", "Provedor · zoom", "Identificador"),
    'wayback': ("Captura", "Versão Wayback", "Satélite · resolução · zoom", "Identificador"),
}

SEARCH_LABELS = {
    'gee': "Buscar imagens no GEE",
    'inpe': "Buscar cenas no INPE",
    'spot': "Buscar cenas SPOT (GEODES)",
    'gehist': "Listar datas do Google Earth",
    'wayback': "Listar versões do Esri Wayback",
}

BTN = ("QPushButton { background-color: #fdfefe; border: 1px solid #b2babb; border-radius: 2px; padding: 3px 8px; }"
       " QPushButton:hover { background-color: #ebedef; }")


def _icon_pixmap(name):
    for ext in ('.png', '.gif'):
        p = os.path.join(ICON_DIR, name + ext)
        if os.path.isfile(p):
            return QPixmap(p)
    return QPixmap()


class MainDialog(QDialog):

    def __init__(self, iface, parent=None, auto_check=True):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle(u"QMagery — imagens de satélite no QGIS | %s" % config.version_label())
        self.resize(1100, 700)
        self.setMinimumSize(940, 600)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint | Qt.WindowMinimizeButtonHint)

        self._runner = BackendRunner(self)
        self._runner.progress.connect(self._on_progress)
        self._check_runner = BackendRunner(self)
        self._check_runner.finished.connect(self._on_check_finished)
        self._check_runner.error.connect(self._on_check_error)

        self._rows = []
        self._source = 'gee'
        self._gee_project = config.load_gee_project()
        self._queue = []
        self._task = None
        self._load_errors = []
        self._loaded = 0
        self._busy = None            # 'search' | 'load' | 'thumb' | None
        self._aoi_file = None
        self._auth_proc = None
        self._auth_timer = None

        self._setup_ui()
        self._on_source_toggled('gee', True)
        self._refresh_vector_layers()
        self._refresh_toc_rasters()
        self._update_map_scale()
        self._connect_canvas()
        if auto_check:
            self.check_gee_connection()

    # ===================================================================== montagem
    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)
        self._build_top_bar(root)
        self._build_source_bar(root)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 5)
        root.addWidget(splitter, stretch=1)
        self._build_bottom_bar(root)

    def _build_top_bar(self, parent):
        bar = QFrame()
        bar.setObjectName('topbar')
        bar.setStyleSheet("#topbar { background-color: #fcf3cf; border: 1px solid #d5dbdb; border-radius: 3px; }")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(6)
        ico = QLabel()
        pm = _icon_pixmap('icon24')
        if not pm.isNull():
            ico.setPixmap(pm.scaled(20, 20, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        lay.addWidget(ico)
        badge = QLabel(u" %s " % config.version_label())
        badge.setStyleSheet("background-color: #1b4f72; color: white; font-weight: bold; border-radius: 2px; padding: 2px 4px;")
        lay.addWidget(badge)
        self._lbl_status_icon = QLabel("[*]")
        lay.addWidget(self._lbl_status_icon)
        self._lbl_status = QLabel(u"Earth Engine: não verificado")
        lay.addWidget(self._lbl_status)
        self._set_status('wait', u"Earth Engine: não verificado")
        self._lbl_scale = QLabel(u"| Escala: -")
        self._lbl_scale.setStyleSheet("color: #1b4f72;")
        lay.addWidget(self._lbl_scale)
        lay.addStretch()
        for attr, text, slot in (('_btn_proj', u"Projeto GEE...", self._on_configure_project),
                                 ('_btn_check', u"Verificar conexão", self.check_gee_connection),
                                 ('_btn_fit', u"Ajustar 1:500.000", self._on_fit_scale),
                                 ('_btn_settings', u"⚙ Configurações", self._on_settings),
                                 ('_btn_about', u"ℹ Sobre", lambda: AboutDialog(self).exec_())):
            b = QPushButton(text)
            b.setStyleSheet(BTN)
            b.clicked.connect(slot)
            setattr(self, attr, b)
            lay.addWidget(b)
        parent.addWidget(bar)

    def _build_source_bar(self, parent):
        bar = QFrame()
        bar.setObjectName('srcbar')
        bar.setStyleSheet("#srcbar { background-color: #eaf2f8; border: 1px solid #d4e6f1; border-radius: 3px; }")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(10, 5, 10, 5)
        lay.setSpacing(6)
        title = QLabel(u"Fonte de imagens:")
        title.setStyleSheet("font-weight: bold; color: #1b4f72;")
        lay.addWidget(title)
        self._source_group = QButtonGroup(self)
        self._source_buttons = {}
        style = ("QRadioButton { background-color: #fdfefe; border: 1px solid #b0c4de; padding: 5px 12px;"
                 " border-radius: 4px; color: #2c3e50; } QRadioButton::indicator { width: 0px; height: 0px; }"
                 " QRadioButton:hover { background-color: #ebf5fb; border-color: #3498db; }"
                 " QRadioButton:checked { background-color: #2980b9; border: 1px solid #1f618d; font-weight: bold;"
                 " color: white; }")
        for code in sources.SOURCES:
            rb = QRadioButton(sources.SOURCE_LABELS[code])
            rb.setStyleSheet(style)
            rb.setChecked(code == 'gee')
            rb.toggled.connect(lambda checked, c=code: self._on_source_toggled(c, checked))
            self._source_group.addButton(rb)
            self._source_buttons[code] = rb
            lay.addWidget(rb)
        lay.addStretch()
        self._btn_xyz = QPushButton(u"Google Earth / XYZ...")
        self._btn_xyz.setStyleSheet("QPushButton { background-color: #fdfefe; border: 1px solid #3498db; color: #1b4f72;"
                                    " font-weight: bold; padding: 4px 12px; border-radius: 3px; }")
        self._btn_xyz.clicked.connect(self._on_xyz)
        lay.addWidget(self._btn_xyz)
        parent.addWidget(bar)

    def _build_left_panel(self):
        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        gb = QGroupBox(u" 1. Parâmetros ")
        gb.setStyleSheet("QGroupBox { font-weight: bold; }")
        form = QVBoxLayout(gb)
        form.setContentsMargins(8, 12, 8, 8)
        form.setSpacing(5)

        form.addWidget(QLabel(u"Satélite / sensor:"))
        self._cbo_sensor = QComboBox()
        self._cbo_sensor.currentIndexChanged.connect(self._on_sensor_changed)
        form.addWidget(self._cbo_sensor)

        info = QFrame()
        info.setObjectName('info')
        info.setStyleSheet("#info { background-color: #eaf2f8; border: 1px solid #aed6f1; border-radius: 3px; }")
        il = QVBoxLayout(info)
        il.setContentsMargins(6, 4, 6, 4)
        il.setSpacing(2)
        self._lbl_period = QLabel()
        self._lbl_period.setStyleSheet("font-weight: bold; color: #1a5276;")
        self._lbl_detail = QLabel()
        self._lbl_bands = QLabel()
        self._lbl_bands.setStyleSheet("color: #117864;")
        self._lbl_notes = QLabel()
        self._lbl_notes.setStyleSheet("color: #78281f; font-style: italic;")
        for w in (self._lbl_period, self._lbl_detail, self._lbl_bands, self._lbl_notes):
            w.setWordWrap(True)
            il.addWidget(w)
        form.addWidget(info)

        self._lbl_comp = QLabel(u"Composição / produto:")
        form.addWidget(self._lbl_comp)
        self._cbo_comp = QComboBox()
        self._cbo_comp.currentIndexChanged.connect(self._on_composition_changed)
        form.addWidget(self._cbo_comp)

        self._lbl_custom = QLabel(u"Bandas personalizadas (ex.: B8,B4,B3):")
        form.addWidget(self._lbl_custom)
        self._txt_custom = QLineEdit()
        form.addWidget(self._txt_custom)

        self._row_pixel = QWidget()
        rp = QHBoxLayout(self._row_pixel)
        rp.setContentsMargins(0, 0, 0, 0)
        rp.addWidget(QLabel(u"Tamanho do pixel (m):"))
        self._cbo_pixel = QComboBox()
        self._cbo_pixel.setEditable(True)
        self._cbo_pixel.addItems(["10", "15", "20", "30", "60", "100"])
        rp.addWidget(self._cbo_pixel)
        rp.addStretch()
        form.addWidget(self._row_pixel)

        rd = QHBoxLayout()
        rd.addWidget(QLabel(u"De:"))
        self._date_start = QDateEdit()
        rd.addWidget(self._date_start)
        rd.addWidget(QLabel(u"até:"))
        self._date_end = QDateEdit()
        rd.addWidget(self._date_end)
        for w in (self._date_start, self._date_end):
            w.setCalendarPopup(True)
            w.setDisplayFormat("dd/MM/yyyy")
            w.setMinimumDate(QDate(1972, 1, 1))
        form.addLayout(rd)

        rs = QHBoxLayout()
        self._quick_date_buttons = {}
        for d in (30, 60, 90, 180, 365):
            b = QPushButton(u"%dd" % d if d < 365 else u"1 ano")
            b.setMaximumWidth(60)
            b.clicked.connect(lambda _=False, days=d: self._set_quick_dates(days))
            self._quick_date_buttons[d] = b
            rs.addWidget(b)
        rs.addStretch()
        form.addLayout(rs)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        form.addWidget(line)
        lbl_aoi = QLabel(u"Área de interesse:")
        lbl_aoi.setStyleSheet("font-weight: bold;")
        form.addWidget(lbl_aoi)
        self._rb_ext = QRadioButton(u"Extensão da tela do QGIS (até 1:500.000)")
        self._rb_ext.setChecked(True)
        form.addWidget(self._rb_ext)
        rl = QHBoxLayout()
        self._rb_lyr = QRadioButton(u"Camada vetorial:")
        rl.addWidget(self._rb_lyr)
        self._cbo_layers = QComboBox()
        self._cbo_layers.activated.connect(lambda _i: self._rb_lyr.setChecked(True))
        rl.addWidget(self._cbo_layers, stretch=1)
        b = QPushButton(u"↻")
        b.setMaximumWidth(28)
        b.setToolTip(u"Atualizar a lista de camadas")
        b.clicked.connect(self._refresh_vector_layers)
        rl.addWidget(b)
        form.addLayout(rl)
        self._chk_selected = QCheckBox(u"Só as feições selecionadas (se houver)")
        self._chk_selected.setChecked(True)
        form.addWidget(self._chk_selected)

        self._btn_search = QPushButton(SEARCH_LABELS['gee'])
        self._btn_search.setStyleSheet("QPushButton { background-color: #1b4f72; color: white; font-weight: bold;"
                                       " padding: 7px; border-radius: 3px; } QPushButton:hover { background-color: #2874a6; }"
                                       " QPushButton:disabled { background-color: #aab7b8; }")
        self._btn_search.clicked.connect(self._on_search_clicked)
        form.addWidget(self._btn_search)
        form.addStretch()
        outer.addWidget(gb)
        return container

    def _build_right_panel(self):
        container = QWidget()
        lay = QVBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self._gb_table = QGroupBox(u" 2. Cenas disponíveis — selecione uma ou várias (Ctrl / Shift) ")
        self._gb_table.setStyleSheet("QGroupBox { font-weight: bold; }")
        tl = QVBoxLayout(self._gb_table)
        tl.setContentsMargins(6, 12, 6, 6)
        self._table = QTableWidget(0, 5)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        self._table.itemSelectionChanged.connect(self._on_table_selection_changed)
        self._table.doubleClicked.connect(lambda _i: self._on_thumb_clicked())
        tl.addWidget(self._table)
        lay.addWidget(self._gb_table, stretch=1)

        gb = QGroupBox(u" 3. Carregar no QGIS ")
        gb.setStyleSheet("QGroupBox { font-weight: bold; }")
        ll = QVBoxLayout(gb)
        ll.setContentsMargins(8, 10, 8, 8)
        ll.setSpacing(5)
        self._lbl_sel_title = QLabel(u"Nenhuma cena selecionada")
        self._lbl_sel_title.setStyleSheet("font-weight: bold; color: #2c3e50;")
        ll.addWidget(self._lbl_sel_title)
        self._lbl_sel_info = QLabel(u"Selecione uma ou mais cenas na tabela (duplo clique: miniatura).")
        self._lbl_sel_info.setStyleSheet("color: #566573;")
        self._lbl_sel_info.setWordWrap(True)
        ll.addWidget(self._lbl_sel_info)

        rg = QHBoxLayout()
        self._chk_group = QCheckBox(u"Agrupar no painel de camadas:")
        self._chk_group.setChecked(True)
        rg.addWidget(self._chk_group)
        self._txt_group = QLineEdit()
        rg.addWidget(self._txt_group, stretch=1)
        ll.addLayout(rg)

        rr = QHBoxLayout()
        rr.addWidget(QLabel(u"Camada a substituir:"))
        self._cbo_toc = QComboBox()
        rr.addWidget(self._cbo_toc, stretch=1)
        self._btn_ref_toc = QPushButton(u"↻")
        self._btn_ref_toc.setMaximumWidth(28)
        self._btn_ref_toc.setToolTip(u"Atualizar a lista de camadas raster")
        self._btn_ref_toc.clicked.connect(self._refresh_toc_rasters)
        rr.addWidget(self._btn_ref_toc)
        ll.addLayout(rr)

        ro = QHBoxLayout()
        self._lbl_out = QLabel()
        self._lbl_out.setStyleSheet("color: #566573;")
        ro.addWidget(self._lbl_out, stretch=1)
        b = QPushButton(u"Abrir pasta")
        b.clicked.connect(self._open_output_dir)
        ro.addWidget(b)
        ll.addLayout(ro)
        self._update_output_label()

        ra = QHBoxLayout()
        ra.addStretch()
        self._btn_thumb = QPushButton(u"🖼 Miniatura")
        self._btn_replace = QPushButton(u"🔁 Substituir camada")
        self._btn_replace.setToolTip(u"Carrega UMA cena no lugar da camada escolhida acima (mesmo grupo e posição)")
        self._btn_load = QPushButton(u"⬇ Carregar no QGIS")
        self._btn_load.setStyleSheet("QPushButton { background-color: #1e8449; color: white; font-weight: bold;"
                                     " padding: 6px 18px; border-radius: 4px; } QPushButton:hover { background-color: #27ae60; }"
                                     " QPushButton:disabled { background-color: #d5dbdb; color: #7f8c8d; }")
        for btn, slot in ((self._btn_thumb, self._on_thumb_clicked), (self._btn_replace, self._on_replace_clicked),
                          (self._btn_load, self._on_load_clicked)):
            btn.setEnabled(False)
            btn.clicked.connect(slot)
            ra.addWidget(btn)
        ll.addLayout(ra)
        lay.addWidget(gb)
        return container

    def _build_bottom_bar(self, parent):
        bar = QFrame()
        bar.setObjectName('bottombar')
        bar.setStyleSheet("#bottombar { background-color: #eaeded; border-top: 1px solid #bdc3c7; }")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(10, 4, 10, 4)
        self._lbl_progress = QLabel(u"Pronto.")
        lay.addWidget(self._lbl_progress, stretch=1)
        self._btn_cancel = QPushButton(u"■ Interromper")
        self._btn_cancel.setStyleSheet("QPushButton { color: #c0392b; font-weight: bold; padding: 3px 10px; }")
        self._btn_cancel.setEnabled(False)
        self._btn_cancel.clicked.connect(self._on_cancel_clicked)
        lay.addWidget(self._btn_cancel)
        self._pbar = QProgressBar()
        self._pbar.setRange(0, 100)
        self._pbar.setValue(0)
        self._pbar.setFixedWidth(200)
        self._pbar.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._pbar)
        parent.addWidget(bar)

    # ===================================================================== estado
    def _set_status(self, kind, text):
        color = STATUS_COLORS.get(kind, '#2c3e50')
        icon = {'ok': '[OK]', 'err': '[!]', 'run': '[*]', 'wait': '[*]'}.get(kind, '[*]')
        self._lbl_status_icon.setText(icon)
        for w in (self._lbl_status_icon, self._lbl_status):
            w.setStyleSheet("color: %s; font-weight: bold;" % color)
        self._lbl_status.setText(text)

    def _set_busy(self, what):
        self._busy = what
        busy = what is not None
        self._btn_search.setEnabled(not busy)
        self._btn_cancel.setEnabled(busy)
        for b in self._source_buttons.values():
            b.setEnabled(not busy)
        self._cbo_sensor.setEnabled(not busy)
        if not busy:
            self._pbar.setRange(0, 100)
        self._update_action_buttons()

    def _selected_rows(self):
        return sorted({i.row() for i in self._table.selectedIndexes()})

    def _update_action_buttons(self):
        count = len(self._selected_rows())
        idle = self._busy is None
        self._btn_load.setEnabled(idle and count > 0)
        self._btn_thumb.setEnabled(idle and count == 1)
        self._btn_replace.setEnabled(idle and count == 1 and self._cbo_toc.currentData() is not None)

    def _update_output_label(self):
        self._lbl_out.setText(u"Arquivos em: %s" % config.output_dir())

    def _open_output_dir(self):
        d = config.output_dir()
        os.makedirs(d, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(d))

    # ===================================================================== fontes e sensores
    def _on_source_toggled(self, code, checked):
        if not checked:
            return
        self._source = code
        self._btn_search.setText(SEARCH_LABELS[code])
        heads = TABLE_HEADERS[code]
        self._table.setHorizontalHeaderLabels(list(heads) + [u"Status"])
        self._cbo_sensor.blockSignals(True)
        self._cbo_sensor.clear()
        for label, value in sources.sensors_for(code):
            self._cbo_sensor.addItem(label, value)
        self._cbo_sensor.blockSignals(False)
        dates = sources.default_dates(code)
        if dates:
            self._date_start.setDate(QDate.fromString(dates[0], 'yyyy-MM-dd'))
            self._date_end.setDate(QDate.fromString(dates[1], 'yyyy-MM-dd'))
        elif code in ('gehist', 'wayback'):
            self._date_start.setDate(QDate(1985, 1, 1))
            self._date_end.setDate(QDate.currentDate())
        else:
            self._set_quick_dates(45 if code == 'gee' else 90)
        is_gee = code == 'gee'
        self._row_pixel.setVisible(is_gee)
        tiles = code in ('gehist', 'wayback')
        self._lbl_comp.setVisible(not tiles)
        self._cbo_comp.setVisible(not tiles)
        self._on_sensor_changed()

    def _on_sensor_changed(self, *_):
        sensor = self._cbo_sensor.currentData()
        if not sensor:
            return
        meta = sources.sensor_metadata(self._source, sensor)
        self._lbl_period.setText(u"📅 Período: %s" % meta.get('period_display', '-'))
        self._lbl_detail.setText(u"📡 %s: %s (%s)" % (meta.get('agency', 'GEE'), meta.get('collection', ''),
                                                      meta.get('res', '')))
        self._lbl_bands.setText(u"🌈 Bandas: %s" % meta.get('available_bands', '-'))
        notes = meta.get('notes', '')
        self._lbl_notes.setText(u"ℹ️ %s" % notes if notes else u"")
        self._lbl_notes.setVisible(bool(notes))
        if self._source == 'gee':
            self._cbo_pixel.setEditText(u"%g" % cat.GEE_NATIVE_RES.get(sensor, 30.0))
        self._cbo_comp.blockSignals(True)
        self._cbo_comp.clear()
        for code, label in sources.compositions_for(self._source, sensor):
            self._cbo_comp.addItem(u"%s - %s" % (code, label), code)
        self._cbo_comp.blockSignals(False)
        self._on_composition_changed()
        self._clear_results_table()

    def _on_composition_changed(self, *_):
        comp = self._cbo_comp.currentData() or 'rgb'
        sensor = self._cbo_sensor.currentData() or ''
        info = sources.gee_composition(sensor, comp) if self._source == 'gee' else None
        custom = bool(info and info[3] in ('bands', 'math'))
        self._lbl_custom.setVisible(custom)
        self._txt_custom.setVisible(custom)
        if custom:
            if info[3] == 'math':
                self._lbl_custom.setText(u"Fórmula do índice (ex.: (B8-B4)/(B8+B4)):")
            else:
                self._lbl_custom.setText(u"Bandas personalizadas, separadas por vírgula (ex.: B8,B4,B3):")
        short = sensor.split(':')[-1] if sensor else self._source
        self._txt_group.setText(u"%s_%s_%s" % (self._source.upper(), short, date.today().strftime('%Y%m%d')))

    def _set_quick_dates(self, days):
        end = date.today()
        start = end - timedelta(days=days)
        self._date_start.setDate(QDate(start.year, start.month, start.day))
        self._date_end.setDate(QDate(end.year, end.month, end.day))

    def _clear_results_table(self):
        self._table.setRowCount(0)
        self._rows = []
        self._on_table_selection_changed()

    # ===================================================================== mapa e camadas
    def _connect_canvas(self):
        try:
            self.iface.mapCanvas().scaleChanged.connect(self._update_map_scale)
            self._canvas_connected = True
        except Exception:
            self._canvas_connected = False

    def _update_map_scale(self, *_):
        try:
            scale = float(self.iface.mapCanvas().scale())
        except Exception:
            return
        text = u"{:,.0f}".format(scale).replace(u",", u".")
        ok = scale <= cat.MAX_ALLOWED_SCALE
        self._lbl_scale.setText(u"| Escala 1:%s%s" % (text, u"" if ok else u" (aproxime até 1:500.000)"))
        self._lbl_scale.setStyleSheet("color: %s; font-weight: bold;" % ('#145a32' if ok else '#c0392b'))

    def _on_fit_scale(self):
        try:
            self.iface.mapCanvas().zoomScale(cat.MAX_ALLOWED_SCALE * 0.98)
            self._update_map_scale()
        except Exception as e:
            QMessageBox.warning(self, u"Escala", u"Não foi possível ajustar a escala: %s" % e)

    def _refresh_vector_layers(self):
        from qgis.core import QgsProject, QgsVectorLayer, QgsWkbTypes
        current = self._cbo_layers.currentData()
        self._cbo_layers.clear()
        for node in QgsProject.instance().layerTreeRoot().findLayers():
            lyr = node.layer()
            if isinstance(lyr, QgsVectorLayer) and lyr.geometryType() == QgsWkbTypes.PolygonGeometry:
                self._cbo_layers.addItem(lyr.name(), lyr.id())
        if self._cbo_layers.count() == 0:
            self._cbo_layers.addItem(u"(nenhuma camada de polígonos no projeto)", None)
        idx = self._cbo_layers.findData(current)
        if idx >= 0:
            self._cbo_layers.setCurrentIndex(idx)

    def _refresh_toc_rasters(self):
        current = self._cbo_toc.currentData()
        self._cbo_toc.clear()
        self._cbo_toc.addItem(u"(nenhuma: carregar como camada nova)", None)
        for lid, name in raster_layers():
            self._cbo_toc.addItem(name, lid)
        idx = self._cbo_toc.findData(current)
        if idx >= 0:
            self._cbo_toc.setCurrentIndex(idx)
        self._update_action_buttons()

    def _canvas_bbox(self):
        from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject
        canvas = self.iface.mapCanvas()
        ext = canvas.extent()
        src = canvas.mapSettings().destinationCrs()
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        if src != wgs84:
            ext = QgsCoordinateTransform(src, wgs84, QgsProject.instance()).transformBoundingBox(ext)
        return [ext.xMinimum(), ext.yMinimum(), ext.xMaximum(), ext.yMaximum()]

    def _export_aoi(self, layer_id):
        """Feições (selecionadas, se houver e a opção estiver marcada) -> GeoJSON EPSG:4326 + bbox."""
        from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject
        layer = QgsProject.instance().mapLayer(layer_id)
        if layer is None:
            raise ValueError(u"A camada vetorial escolhida não está mais no projeto.")
        feats = list(layer.selectedFeatures()) if (self._chk_selected.isChecked() and layer.selectedFeatureCount()) \
            else list(layer.getFeatures())
        tr = QgsCoordinateTransform(layer.crs(), QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance())
        out, xs, ys = [], [], []
        for f in feats:
            g = f.geometry()
            if g is None or g.isEmpty():
                continue
            g.transform(tr)
            bb = g.boundingBox()
            xs += [bb.xMinimum(), bb.xMaximum()]
            ys += [bb.yMinimum(), bb.yMaximum()]
            out.append({'type': 'Feature', 'properties': {}, 'geometry': json.loads(g.asJson(8))})
        if not out:
            raise ValueError(u"A camada '%s' não tem feições com geometria." % layer.name())
        self._remove_aoi_file()
        fd, path = tempfile.mkstemp(prefix='qmagery_aoi_', suffix='.geojson')
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump({'type': 'FeatureCollection', 'features': out}, fh)
        self._aoi_file = path
        return [min(xs), min(ys), max(xs), max(ys)], path

    def _remove_aoi_file(self):
        if self._aoi_file:
            try:
                os.remove(self._aoi_file)
            except OSError:
                pass
            self._aoi_file = None

    def _resolve_area(self):
        """(bbox WGS84, geojson ou None); None se o usuário desistir. Aplica o limite de escala."""
        if self._rb_lyr.isChecked():
            lid = self._cbo_layers.currentData()
            if not lid:
                QMessageBox.warning(self, u"Área de interesse", u"Escolha uma camada de polígonos ou use a extensão da tela.")
                return None
            try:
                return self._export_aoi(lid)
            except Exception as e:
                QMessageBox.critical(self, u"Área de interesse", u"Não foi possível usar a camada: %s" % e)
                return None
        try:
            scale = float(self.iface.mapCanvas().scale())
        except Exception:
            scale = None
        if scale and scale > cat.MAX_ALLOWED_SCALE:
            ask = QMessageBox.question(
                self, u"Limite de escala (1:500.000)",
                u"A escala do mapa é 1:{:,.0f}, maior que o limite de 1:500.000.\n\nAjustar o zoom para 1:500.000 e "
                u"continuar?".format(scale).replace(u",", u"."), QMessageBox.Yes | QMessageBox.No)
            if ask != QMessageBox.Yes:
                return None
            self._on_fit_scale()
        return self._canvas_bbox(), None

    # ===================================================================== busca
    def _period(self):
        start = self._date_start.date().toString('yyyy-MM-dd')
        end = self._date_end.date().toString('yyyy-MM-dd')
        return (start, end) if start <= end else (end, start)

    def _on_search_clicked(self):
        if self._busy:
            return
        area = self._resolve_area()
        if area is None:
            return
        bbox, geojson = area
        start, end = self._period()
        sensor = self._cbo_sensor.currentData()
        try:
            cmd, params, timeout = sources.search_request(
                self._source, sensor, start, end, bbox=bbox, geojson_file=geojson, project=self._gee_project or None,
                workers=config.tile_threads())
        except ValueError as e:
            QMessageBox.warning(self, u"Busca", str(e))
            return
        self._clear_results_table()
        self._search_ctx = (self._source, sensor, start, end)
        self._lbl_progress.setText(u"Buscando (%s)..." % sources.SOURCE_LABELS[self._source])
        self._pbar.setRange(0, 0)
        self._set_busy('search')
        self._connect_runner(self._on_search_finished, self._on_search_error)
        self._runner.run(cmd, params, timeout)

    def _connect_runner(self, on_finished, on_error):
        for sig in (self._runner.finished, self._runner.error):
            try:
                sig.disconnect()
            except TypeError:
                pass
        self._runner.finished.connect(on_finished)
        self._runner.error.connect(on_error)

    def _on_search_finished(self, res):
        self._set_busy(None)
        self._pbar.setValue(0)
        if not res.get('success'):
            msg = res.get('message') or u"Erro desconhecido."
            self._lbl_progress.setText(u"Falha na busca.")
            QMessageBox.critical(self, u"Busca", msg)
            return
        source, sensor, start, end = self._search_ctx
        self._rows = sources.rows_from_result(source, sensor, res, start, end)
        self._table.setRowCount(0)
        for row in self._rows:
            r = self._table.rowCount()
            self._table.insertRow(r)
            for col, key in enumerate(('c_date', 'c_cloud', 'c_detail', 'c_name')):
                self._table.setItem(r, col, QTableWidgetItem(u"%s" % (row.get(key) if row.get(key) is not None else u'-')))
            self._table.setItem(r, 4, QTableWidgetItem(u"Disponível"))
        n = len(self._rows)
        if n:
            self._lbl_progress.setText(u"%d cena(s) encontrada(s)." % n)
        else:
            self._lbl_progress.setText(u"Nenhuma cena encontrada na área e no período.")
            QMessageBox.information(self, u"Busca", u"Nenhuma cena encontrada na área e no período escolhidos.")
        self._on_table_selection_changed()

    def _on_search_error(self, msg):
        self._set_busy(None)
        self._pbar.setValue(0)
        if msg == CANCELLED_MESSAGE:
            self._lbl_progress.setText(u"Busca interrompida.")
            return
        self._lbl_progress.setText(u"Falha na busca.")
        QMessageBox.critical(self, u"Busca", msg)

    # ===================================================================== seleção
    def _on_table_selection_changed(self):
        rows = self._selected_rows()
        if not rows:
            self._lbl_sel_title.setText(u"Nenhuma cena selecionada")
            self._lbl_sel_info.setText(u"Selecione uma ou mais cenas na tabela (duplo clique: miniatura).")
        elif len(rows) == 1:
            row = self._rows[rows[0]]
            self._lbl_sel_title.setText(u"Cena: %s" % row.get('c_name'))
            self._lbl_sel_info.setText(u"Data: %s · %s · %s" % (row.get('c_date'), row.get('c_cloud'), row.get('c_detail')))
        else:
            self._lbl_sel_title.setText(u"%d cenas selecionadas" % len(rows))
            self._lbl_sel_info.setText(u"Cada cena vira uma camada, baixadas uma depois da outra.")
        self._update_action_buttons()

    def _set_row_status(self, index, text, color=None, bold=False):
        if index is None or index >= self._table.rowCount():
            return
        item = self._table.item(index, 4)
        if item is None:
            item = QTableWidgetItem()
            self._table.setItem(index, 4, item)
        item.setText(text)
        item.setForeground(QColor(color or '#2c3e50'))
        f = item.font()
        f.setBold(bold)
        item.setFont(f)

    # ===================================================================== carregamento
    def _download_options(self):
        """Parâmetros comuns da fila; None se faltar algo (com mensagem ao usuário)."""
        sensor = self._cbo_sensor.currentData()
        comp = self._cbo_comp.currentData() or 'rgb'
        opts = {'source': self._source, 'sensor': sensor, 'comp': comp, 'custom_bands': None, 'scale': None,
                'api_key': None}
        if self._source == 'gee':
            info = sources.gee_composition(sensor, comp)
            if info and info[3] in ('bands', 'math'):
                text = self._txt_custom.text().strip()
                if not text:
                    QMessageBox.warning(self, u"Composição", u"Digite as bandas ou a fórmula da composição escolhida.")
                    return None
                opts['custom_bands'] = text
            px = self._cbo_pixel.currentText().strip().replace(',', '.')
            try:
                opts['scale'] = float(px) if px else None
            except ValueError:
                QMessageBox.warning(self, u"Tamanho do pixel", u"Tamanho do pixel inválido: %s" % px)
                return None
        if self._source == 'spot':
            opts['api_key'] = config.load_geodes_key()
            if not opts['api_key']:
                ask = QMessageBox.question(
                    self, u"Chave do GEODES necessária",
                    u"A busca de cenas SPOT é livre, mas o DOWNLOAD exige a chave de API gratuita do GEODES (CNES).\n\n"
                    u"Configurar a chave agora?", QMessageBox.Yes | QMessageBox.No)
                if ask == QMessageBox.Yes:
                    GeodesKeyDialog(self).exec_()
                opts['api_key'] = config.load_geodes_key()
                if not opts['api_key']:
                    return None
        return opts

    def _on_load_clicked(self):
        self._start_queue(self._selected_rows(), replace_id=None)

    def _on_replace_clicked(self):
        rows = self._selected_rows()
        target = self._cbo_toc.currentData()
        if len(rows) != 1 or not target:
            return
        self._start_queue(rows, replace_id=target)

    def _start_queue(self, indexes, replace_id=None):
        if self._busy or not indexes:
            return
        opts = self._download_options()
        if opts is None:
            return
        area = self._resolve_area()
        if area is None:
            return
        bbox, geojson = area
        if self._source == 'gee':
            msg = sources.gee_size_check(opts['sensor'], opts['comp'], bbox, opts['scale'], opts['custom_bands'])
            if msg:
                QMessageBox.critical(self, u"Área muito extensa", msg)
                return
        opts.update(bbox=bbox, geojson=geojson, replace_id=replace_id,
                    group=(self._txt_group.text().strip() or None) if self._chk_group.isChecked() else None)
        self._queue = [(i, self._rows[i], opts) for i in indexes]
        self._queue_total = len(self._queue)
        self._load_errors = []
        self._loaded = 0
        for i in indexes:
            self._set_row_status(i, u"Na fila", STATUS_COLORS['wait'])
        self._set_busy('load')
        self._next_task()

    def _out_path(self, task_opts, row):
        folder = os.path.join(config.output_dir(), task_opts['source'])
        os.makedirs(folder, exist_ok=True)
        stem = sources.output_stem(task_opts['source'], task_opts['sensor'], row, task_opts['comp'])
        path = os.path.join(folder, stem + '.tif')
        n = 2
        while os.path.exists(path):
            path = os.path.join(folder, u"%s_%d.tif" % (stem, n))
            n += 1
        return path

    def _next_task(self):
        if not self._queue:
            self._finish_queue()
            return
        index, row, opts = self._queue.pop(0)
        self._task = (index, row, opts)
        done = self._queue_total - len(self._queue)
        try:
            out = self._out_path(opts, row)
            cmd, params, timeout = sources.download_request(
                opts['source'], opts['sensor'], row, opts['comp'], out, bbox=opts['bbox'], geojson_file=opts['geojson'],
                project=self._gee_project or None, custom_bands=opts['custom_bands'], scale=opts['scale'],
                api_key=opts['api_key'], workers=config.tile_threads())
        except Exception as e:
            self._on_load_error(u"%s" % e)
            return
        self._set_row_status(index, u"Baixando...", STATUS_COLORS['run'], True)
        self._task_prefix = u"Cena %d de %d" % (done, self._queue_total) if self._queue_total > 1 else u"Baixando"
        self._lbl_progress.setText(u"%s: %s..." % (self._task_prefix, row.get('c_name')))
        self._pbar.setRange(0, 100)
        self._pbar.setValue(0)
        self._connect_runner(self._on_load_finished, self._on_load_error)
        self._runner.run(cmd, params, timeout)

    def _on_load_finished(self, res):
        index, row, opts = self._task
        if not res.get('success'):
            self._on_load_error(res.get('message') or u"Falha no download.")
            return
        path = res.get('file')
        if not path or not os.path.isfile(path):
            self._on_load_error(u"O backend não gerou o GeoTIFF (%s)." % path)
            return
        name = sources.layer_name(opts['source'], opts['sensor'], row, opts['comp'])
        try:
            layer = add_raster_layer(path, name, group_name=opts['group'], replace_layer_id=opts['replace_id'])
        except Exception as e:
            self._on_load_error(u"GeoTIFF salvo em %s, mas o QGIS não conseguiu abri-lo: %s" % (path, e))
            return
        if opts['source'] == 'gee':
            kind, bands = sources.gee_style(opts['sensor'], opts['comp'], opts['custom_bands'])
        elif res.get('rgb_bands'):
            kind, bands = 'rgb', res['rgb_bands']
        else:
            kind, bands = (None, None)
        apply_style(layer, kind, bands)
        opts['replace_id'] = None   # só a primeira cena substitui
        self._loaded += 1
        notes = []
        if res.get('valid_pct') is not None and float(res['valid_pct']) < 95:
            notes.append(u"cobre %.0f%% da área" % float(res['valid_pct']))
        align = res.get('alignment') or {}
        if opts['source'] == 'spot':
            notes.append(u"alinhada à Esri (desvio corrigido: %.0f m)" % (align.get('shift_m') or 0)
                         if align.get('applied') else u"SEM alinhamento: posição com erro de até ~500 m")
        self._set_row_status(index, u"✓ Carregada" + (u" (%s)" % u"; ".join(notes) if notes else u""),
                             STATUS_COLORS['ok'], True)
        self._refresh_toc_rasters()
        self._next_task()

    def _on_load_error(self, msg):
        index, row, _opts = self._task if self._task else (None, {}, None)
        if msg == CANCELLED_MESSAGE:
            self._set_row_status(index, u"Interrompida", STATUS_COLORS['err'])
            for i, _r, _o in self._queue:
                self._set_row_status(i, u"Cancelada", STATUS_COLORS['err'])
            self._queue = []
            self._task = None
            self._set_busy(None)
            self._pbar.setValue(0)
            self._lbl_progress.setText(CANCELLED_MESSAGE)
            return
        self._set_row_status(index, u"Erro", STATUS_COLORS['err'], True)
        self._load_errors.append(u"• %s: %s" % (row.get('c_name', u'?'), msg))
        self._next_task()

    def _finish_queue(self):
        self._task = None
        self._set_busy(None)
        self._pbar.setValue(100 if self._loaded else 0)
        if self._load_errors:
            self._lbl_progress.setText(u"%d carregada(s), %d com erro." % (self._loaded, len(self._load_errors)))
            QMessageBox.critical(self, u"Carregamento", u"Algumas cenas não foram carregadas:\n\n" +
                                 u"\n\n".join(self._load_errors[:8]))
        else:
            self._lbl_progress.setText(u"%d cena(s) carregada(s) no QGIS." % self._loaded)

    # ===================================================================== miniatura
    def _on_thumb_clicked(self):
        rows = self._selected_rows()
        if self._busy or len(rows) != 1:
            return
        row = self._rows[rows[0]]
        bbox, geojson = None, None
        if self._source in ('gee', 'gehist', 'wayback'):
            area = self._resolve_area()
            if area is None:
                return
            bbox, geojson = area
        out_png = os.path.join(tempfile.gettempdir(), u"qmagery_thumb_%s.png" % sources.safe_name(row['id'], 60))
        try:
            cmd, params, timeout = sources.thumb_request(self._source, self._cbo_sensor.currentData(), row,
                                                         self._cbo_comp.currentData(), out_png, bbox=bbox,
                                                         geojson_file=geojson, project=self._gee_project or None)
        except ValueError as e:
            QMessageBox.information(self, u"Miniatura", str(e))
            return
        self._thumb_title = row.get('c_name')
        self._lbl_progress.setText(u"Gerando a miniatura...")
        self._pbar.setRange(0, 0)
        self._set_busy('thumb')
        self._connect_runner(self._show_thumb, self._on_thumb_error)
        self._runner.run(cmd, params, timeout)

    def _show_thumb(self, res):
        self._set_busy(None)
        self._lbl_progress.setText(u"Pronto.")
        path = res.get('file')
        if not res.get('success') or not path or not os.path.isfile(path):
            QMessageBox.warning(self, u"Miniatura", res.get('message') or u"Não foi possível gerar a miniatura.")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(u"Miniatura — %s" % self._thumb_title)
        lay = QVBoxLayout(dlg)
        lbl = QLabel()
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setPixmap(QPixmap(path).scaled(560, 560, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        lay.addWidget(lbl)
        btn = QPushButton(u"Fechar")
        btn.clicked.connect(dlg.accept)
        lay.addWidget(btn, alignment=Qt.AlignRight)
        dlg.exec_()

    def _on_thumb_error(self, msg):
        self._set_busy(None)
        self._lbl_progress.setText(u"Pronto." if msg == CANCELLED_MESSAGE else u"Falha na miniatura.")
        if msg != CANCELLED_MESSAGE:
            QMessageBox.warning(self, u"Miniatura", msg)

    # ===================================================================== progresso e cancelamento
    def _on_progress(self, line):
        import re
        text = line.replace('[ArcGEE]', '').strip()
        m = re.search(r'PROGRESS\s+(\d+)\s*/\s*(\d+)', line)
        if m and int(m.group(2)) > 0:
            pct = int(100 * int(m.group(1)) / int(m.group(2)))
            if self._pbar.maximum() == 0:
                self._pbar.setRange(0, 100)
            self._pbar.setValue(pct)
            return
        if not text or text.startswith(('Traceback', 'File "')):
            return
        prefix = getattr(self, '_task_prefix', None) if self._busy == 'load' else None
        self._lbl_progress.setText((u"%s: %s" % (prefix, text) if prefix else text)[:160])

    def _on_cancel_clicked(self):
        if self._busy:
            self._lbl_progress.setText(u"Interrompendo...")
            self._runner.cancel()

    # ===================================================================== Earth Engine
    def check_gee_connection(self):
        if self._check_runner.is_running():
            return
        self._set_status('run', u"Verificando a conexão com o Earth Engine...")
        params = {'project': self._gee_project} if self._gee_project else {}
        self._check_runner.run('check', params)

    def _on_check_finished(self, res):
        if res.get('success'):
            proj = u" · projeto %s" % self._gee_project if self._gee_project else u""
            self._set_status('ok', u"Conectado ao Earth Engine%s" % proj)
        elif res.get('ee_missing'):
            self._set_status('err', u"Earth Engine: componentes não instalados (Configurações)")
        else:
            msg = (res.get('message') or u"").lower()
            if 'authenticate' in msg or 'credential' in msg or 'token' in msg:
                self._set_status('err', u"Earth Engine: autentique-se (Projeto GEE...)")
            elif 'project' in msg:
                self._set_status('err', u"Earth Engine: informe o projeto (Projeto GEE...)")
            else:
                self._set_status('err', u"Earth Engine indisponível (as outras fontes funcionam)")
            self._lbl_status.setToolTip(res.get('message') or u"")

    def _on_check_error(self, msg):
        self._set_status('err', u"Earth Engine: falha na verificação")
        self._lbl_status.setToolTip(msg)

    def _on_configure_project(self):
        dlg = GeeProjectDialog(self, self._gee_project)
        accepted = dlg.exec_()
        self._gee_project = config.load_gee_project()
        if dlg.auth_process is not None:
            self._watch_auth(dlg.auth_process)
        elif accepted:
            self.check_gee_connection()

    def _watch_auth(self, proc):
        """Autenticação numa janela de console: quando ela fecha, verifica a conexão de novo."""
        self._auth_proc = proc
        self._set_status('run', u"Autenticação aberta no console: conclua no navegador...")
        if self._auth_timer is None:
            self._auth_timer = QTimer(self)
            self._auth_timer.timeout.connect(self._poll_auth)
        self._auth_timer.start(1500)

    def _poll_auth(self):
        if self._auth_proc is not None and self._auth_proc.poll() is None:
            return
        self._auth_timer.stop()
        self._auth_proc = None
        self._gee_project = config.load_gee_project()
        self.check_gee_connection()

    # ===================================================================== diálogos
    def _on_settings(self):
        dlg = SettingsDialog(self)
        dlg.exec_()
        previous = self._gee_project
        self._gee_project = config.load_gee_project()
        self._update_output_label()
        if dlg.auth_process is not None:
            self._watch_auth(dlg.auth_process)
        elif self._gee_project != previous:
            self.check_gee_connection()

    def _on_xyz(self):
        ExtraSourcesDialog(self.iface, self, area_provider=self._resolve_area).exec_()
        self._refresh_toc_rasters()

    # ===================================================================== encerramento
    def shutdown(self):
        for runner in (self._runner, self._check_runner):
            runner.shutdown()
        if self._auth_timer is not None:
            self._auth_timer.stop()
        if getattr(self, '_canvas_connected', False):
            try:
                self.iface.mapCanvas().scaleChanged.disconnect(self._update_map_scale)
            except Exception:
                pass
            self._canvas_connected = False
        self._remove_aoi_file()

    def _confirm_close(self):
        if self._busy != 'load' or getattr(self, '_closing', False):
            return True
        ask = QMessageBox.question(self, u"Download em andamento",
                                   u"Há um download em andamento. Interromper e fechar?",
                                   QMessageBox.Yes | QMessageBox.No)
        if ask == QMessageBox.Yes:
            self._closing = True
            return True
        return False

    def closeEvent(self, event):
        if not self._confirm_close():
            event.ignore()
            return
        self.shutdown()
        super().closeEvent(event)

    def reject(self):
        # Esc e o "X" chegam aqui (o closeEvent do QDialog chama reject): mesma confirmação
        if not self._confirm_close():
            return
        self.shutdown()
        super().reject()
