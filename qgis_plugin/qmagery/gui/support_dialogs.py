# -*- coding: utf-8 -*-
"""
Diálogos de apoio do QMagery:
  - GeeProjectDialog ..... ID do projeto do Google Cloud e autenticação no Google
  - GeodesKeyDialog ...... chave de API do GEODES (SPOT), com teste e tutorial
  - SettingsDialog ....... pasta de saída, threads de tiles, tela de verificação, chaves
  - AboutDialog .......... versão, autoria e créditos
  - ExtraSourcesDialog ... Google Earth / Esri / Bing como camada XYZ ou mosaico GeoTIFF
"""
import os

from qgis.PyQt.QtCore import Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices, QPixmap
from qgis.PyQt.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QSpinBox, QVBoxLayout,
)

from ..core import config, sources
from ..core import catalog_constants as cat
from ..core.backend_runner import CANCELLED_MESSAGE, BackendRunner, open_console
from ..core.qgis_layer import add_raster_layer, add_xyz_tile_layer

ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'resources', 'icons')
REPO_URL = 'https://github.com/Yiuky/ArcMagery'

GEODES_STEPS = [
    (u"1. Crie a conta gratuita no GEODES",
     u"Acesse %s e clique em \"Log in\" > \"Register\". Confirme o cadastro pelo link enviado ao seu e-mail."
     % cat.GEODES_PORTAL),
    (u"2. Abra o seu perfil", u"Depois de entrar, clique no seu nome (canto superior direito) > \"My Profile\"."),
    (u"3. Gere a chave", u"No quadro \"Authentication\", em \"API Key\", clique em \"Generate\" (ou copie a existente)."),
    (u"4. Cole a chave aqui", u"Cole a chave abaixo, clique em \"Testar chave\" e depois em \"Salvar\"."),
]


def _pixmap(name):
    for ext in ('.png', '.gif'):
        p = os.path.join(ICON_DIR, name + ext)
        if os.path.isfile(p):
            return QPixmap(p)
    return QPixmap()


def _hline():
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setFrameShadow(QFrame.Sunken)
    return line


def start_gee_auth(parent, project):
    """Abre a autenticação do Google (ee_auth.py do backend) num console visível. Retorna o processo."""
    QMessageBox.information(
        parent, u"Autenticar no Google",
        u"Uma janela de console vai abrir e, em seguida, o navegador. Entre com a conta Google que tem acesso "
        u"ao Earth Engine e autorize. Quando o console fechar, o QMagery verifica a conexão de novo.")
    try:
        return open_console('ee_auth.py', [project or ''])
    except Exception as e:
        QMessageBox.critical(parent, u"Autenticar no Google", u"Não foi possível abrir a autenticação: %s" % e)
        return None


# ============================================================================ Projeto GEE
class GeeProjectDialog(QDialog):
    """ID do projeto do Google Cloud (compartilhado com o ArcMagery) e autenticação."""

    def __init__(self, parent=None, project=u""):
        super().__init__(parent)
        self.auth_process = None
        self.setWindowTitle(u"Google Earth Engine — projeto e autenticação")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        info = QLabel(u"O Earth Engine exige um projeto do Google Cloud com a Earth Engine API habilitada "
                      u"(gratuito para uso não comercial). O mesmo projeto vale para o ArcMagery.")
        info.setWordWrap(True)
        lay.addWidget(info)
        form = QFormLayout()
        self._txt = QLineEdit(project or config.load_gee_project())
        self._txt.setPlaceholderText(u"ex.: meu-projeto-123456")
        form.addRow(u"ID do projeto:", self._txt)
        lay.addLayout(form)
        row = QHBoxLayout()
        b_auth = QPushButton(u"Autenticar no Google...")
        b_auth.clicked.connect(self._on_auth)
        row.addWidget(b_auth)
        b_help = QPushButton(u"Como criar o projeto")
        b_help.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl('https://developers.google.com/earth-engine/guides/access')))
        row.addWidget(b_help)
        row.addStretch()
        lay.addLayout(row)
        box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Save).setText(u"Salvar e verificar")
        box.accepted.connect(self._on_save)
        box.rejected.connect(self.reject)
        lay.addWidget(box)

    def _on_save(self):
        try:
            config.save_gee_project(self._txt.text())
        except Exception as e:
            QMessageBox.critical(self, u"Projeto GEE", u"Não foi possível salvar: %s" % e)
            return
        self.accept()

    def _on_auth(self):
        try:
            config.save_gee_project(self._txt.text())
        except Exception:
            pass
        self.auth_process = start_gee_auth(self, self._txt.text().strip())
        if self.auth_process is not None:
            self.accept()


# ============================================================================ chave do GEODES
class GeodesKeyDialog(QDialog):
    """Chave de API do GEODES (CNES) para baixar cenas SPOT. Gravada em %APPDATA%\\ArcGEE (só do usuário)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(u"Chave do GEODES (SPOT)")
        self.setMinimumWidth(580)
        self._runner = BackendRunner(self)
        self._runner.finished.connect(self._on_test_done)
        self._runner.error.connect(lambda m: self._set_result(False, m))
        lay = QVBoxLayout(self)
        intro = QLabel(u"A busca de cenas SPOT é livre; o DOWNLOAD exige a chave gratuita do GEODES "
                       u"(cota de 50 cenas por hora; cenas já baixadas ficam em cache).")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        for title, text in GEODES_STEPS:
            t = QLabel(u"<b>%s</b><br>%s" % (title, text))
            t.setWordWrap(True)
            lay.addWidget(t)
        b_portal = QPushButton(u"Abrir o portal do GEODES")
        b_portal.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(cat.GEODES_PORTAL)))
        lay.addWidget(b_portal, alignment=Qt.AlignLeft)
        lay.addWidget(_hline())
        row = QHBoxLayout()
        self._txt = QLineEdit(config.load_geodes_key() or u"")
        self._txt.setEchoMode(QLineEdit.Password)
        self._txt.setPlaceholderText(u"cole aqui a chave de API")
        row.addWidget(self._txt, stretch=1)
        show = QCheckBox(u"mostrar")
        show.toggled.connect(lambda on: self._txt.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        row.addWidget(show)
        self._btn_test = QPushButton(u"Testar chave")
        self._btn_test.clicked.connect(self._on_test)
        row.addWidget(self._btn_test)
        lay.addLayout(row)
        self._lbl_result = QLabel(u"")
        self._lbl_result.setWordWrap(True)
        lay.addWidget(self._lbl_result)
        note = QLabel(u"A chave fica só neste computador (%s) e vale também para o ArcMagery. "
                      u"Não a compartilhe." % config.geodes_config_file())
        note.setWordWrap(True)
        note.setStyleSheet("color: #566573;")
        lay.addWidget(note)
        box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        box.accepted.connect(self._on_save)
        box.rejected.connect(self.reject)
        lay.addWidget(box)

    def _set_result(self, ok, text):
        self._btn_test.setEnabled(True)
        self._lbl_result.setStyleSheet("color: %s; font-weight: bold;" % ('#1e8449' if ok else '#c0392b'))
        self._lbl_result.setText(text)

    def _on_test(self):
        key = self._txt.text().strip()
        if not key:
            self._set_result(False, u"Cole a chave primeiro.")
            return
        self._btn_test.setEnabled(False)
        self._lbl_result.setStyleSheet("")
        self._lbl_result.setText(u"Testando a chave no GEODES...")
        self._runner.run('spot_check_key', {'api_key': key})

    def _on_test_done(self, res):
        if res.get('success'):
            self._set_result(True, u"Chave válida: %s de %s downloads disponíveis nesta hora."
                             % (res.get('remaining_quota'), res.get('max_quota')))
        else:
            self._set_result(False, res.get('message') or u"Chave recusada pelo GEODES.")

    def _on_save(self):
        try:
            config.save_geodes_key(self._txt.text())
        except Exception as e:
            QMessageBox.critical(self, u"Chave do GEODES", u"Não foi possível salvar: %s" % e)
            return
        self.accept()

    def done(self, r):
        self._runner.shutdown()
        super().done(r)


# ============================================================================ configurações
class SettingsDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.auth_process = None
        self.setWindowTitle(u"Configurações — QMagery")
        self.setMinimumWidth(560)
        s = config.load_settings()
        lay = QVBoxLayout(self)

        gb_out = QGroupBox(u"Arquivos baixados")
        fo = QFormLayout(gb_out)
        row = QHBoxLayout()
        self._txt_out = QLineEdit(s.get('output_dir') or u"")
        self._txt_out.setPlaceholderText(config.default_output_dir())
        row.addWidget(self._txt_out, stretch=1)
        b = QPushButton(u"Escolher...")
        b.clicked.connect(self._choose_dir)
        row.addWidget(b)
        fo.addRow(u"Pasta de saída:", row)
        hint = QLabel(u"Os GeoTIFFs ficam nessa pasta (uma subpasta por fonte) e continuam no projeto do QGIS "
                      u"depois de reiniciar. Vazio = Documentos\\QMagery.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #566573;")
        fo.addRow(hint)
        lay.addWidget(gb_out)

        gb_perf = QGroupBox(u"Desempenho")
        fp = QFormLayout(gb_perf)
        self._spn_threads = QSpinBox()
        self._spn_threads.setRange(0, config.TILE_THREADS_MAX)
        self._spn_threads.setSingleStep(4)
        self._spn_threads.setSpecialValueText(u"automático (%d)" % config.clamp_tile_threads(0))
        self._spn_threads.setValue(int(s.get('tile_threads') or 0))
        fp.addRow(u"Threads de tiles (Google Earth, Wayback, XYZ):", self._spn_threads)
        lay.addWidget(gb_perf)

        gb_acc = QGroupBox(u"Contas")
        fa = QHBoxLayout(gb_acc)
        b_gee = QPushButton(u"Projeto e autenticação do GEE...")
        b_gee.clicked.connect(self._on_gee)
        fa.addWidget(b_gee)
        b_key = QPushButton(u"Chave do GEODES (SPOT)...")
        b_key.clicked.connect(lambda: GeodesKeyDialog(self).exec_())
        fa.addWidget(b_key)
        fa.addStretch()
        lay.addWidget(gb_acc)

        self._chk_startup = QCheckBox(u"Verificar o ambiente (Python, GDAL, Earth Engine) ao abrir o QMagery")
        self._chk_startup.setChecked(bool(s.get('show_startup_check', True)))
        lay.addWidget(self._chk_startup)

        box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        box.accepted.connect(self._on_save)
        box.rejected.connect(self.reject)
        lay.addWidget(box)

    def _choose_dir(self):
        d = QFileDialog.getExistingDirectory(self, u"Pasta de saída", self._txt_out.text() or config.output_dir())
        if d:
            self._txt_out.setText(os.path.normpath(d))

    def _on_gee(self):
        dlg = GeeProjectDialog(self)
        dlg.exec_()
        if dlg.auth_process is not None:
            self.auth_process = dlg.auth_process
            self._on_save()

    def _on_save(self):
        out = self._txt_out.text().strip()
        if out:
            try:
                os.makedirs(out, exist_ok=True)
            except OSError as e:
                QMessageBox.critical(self, u"Pasta de saída", u"Não foi possível usar a pasta:\n%s" % e)
                return
        try:
            config.save_settings({'output_dir': out, 'tile_threads': int(self._spn_threads.value()),
                                  'show_startup_check': self._chk_startup.isChecked()})
        except Exception as e:
            QMessageBox.critical(self, u"Configurações", u"Não foi possível salvar: %s" % e)
            return
        self.accept()


# ============================================================================ sobre
class AboutDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(u"Sobre o QMagery")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        head = QHBoxLayout()
        logo = QLabel()
        pm = _pixmap('about_logo')
        if pm.isNull():
            pm = _pixmap('icon64')
        if not pm.isNull():
            logo.setPixmap(pm.scaled(72, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        head.addWidget(logo)
        tb = QVBoxLayout()
        title = QLabel(u"QMagery")
        title.setStyleSheet("font-size: 18pt; font-weight: bold; color: #0b5345;")
        tb.addWidget(title)
        sub = QLabel(u"Imagens de satélite no QGIS, carregadas direto no painel de camadas na resolução nativa.")
        sub.setWordWrap(True)
        sub.setStyleSheet("color: #566573; font-style: italic;")
        tb.addWidget(sub)
        head.addLayout(tb, stretch=1)
        lay.addLayout(head)
        lay.addWidget(_hline())
        text = (
            u"<b>Versão:</b> %s<br>"
            u"<b>Autor:</b> Joberth Firmino Gambati — projeto pessoal e independente, código aberto (licença MIT)<br>"
            u"<b>Código e manual:</b> <a href='%s'>github.com/Yiuky/ArcMagery</a> (o mesmo backend do ArcMagery, "
            u"plugin do ArcMap 10.8)<br>"
            u"<b>Requisitos:</b> QGIS 3.18 ou mais novo (Windows); internet. O Earth Engine exige um projeto do "
            u"Google Cloud; o download do SPOT exige a chave gratuita do GEODES.<br><br>"
            u"<b>Fontes:</b> Google Earth Engine (Sentinel-2, Landsat 1-9) · CBERS e Amazônia-1 (INPE, STAC) · "
            u"SPOT 1-5 (CNES, SPOT World Heritage) · Google Earth histórico · Esri World Imagery Wayback · "
            u"mosaicos XYZ.<br><br>"
            u"Cite a fonte das imagens. Google, Bing e Esri têm termos de uso próprios: use essas imagens para "
            u"consulta e visualização. Problemas e sugestões: "
            u"<a href='%s/issues'>abrir uma issue</a>."
            % (config.version_label(), REPO_URL, REPO_URL))
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setOpenExternalLinks(True)
        lbl.setTextInteractionFlags(Qt.TextBrowserInteraction)
        lay.addWidget(lbl)
        lay.addStretch()
        b = QPushButton(u"Fechar")
        b.clicked.connect(self.accept)
        lay.addWidget(b, alignment=Qt.AlignRight)


# ============================================================================ Google Earth / XYZ
class ExtraSourcesDialog(QDialog):
    """Mosaicos XYZ: camada "ao vivo" (sem download) ou GeoTIFF da área de interesse."""

    CRS_OPTIONS = [(u"Web Mercator (EPSG:3857) — grade nativa dos tiles", None),
                   (u"SIRGAS 2000 (EPSG:4674)", 'EPSG:4674'),
                   (u"WGS 84 (EPSG:4326)", 'EPSG:4326')]

    def __init__(self, iface, parent=None, area_provider=None):
        super().__init__(parent)
        self.iface = iface
        self._area_provider = area_provider
        self.setWindowTitle(u"Google Earth / mosaicos XYZ")
        self.setMinimumWidth(640)
        self._runner = BackendRunner(self)
        self._runner.progress.connect(self._on_progress)
        lay = QVBoxLayout(self)

        box = QGroupBox(u"Mosaico de alta resolução")
        form = QFormLayout(box)
        self._cbo_provider = QComboBox()
        for label, code, max_z, tos, url in cat.XYZ_PROVIDERS:
            self._cbo_provider.addItem(label, (code, max_z, tos, url))
        self._cbo_provider.currentIndexChanged.connect(self._on_provider)
        form.addRow(u"Fonte:", self._cbo_provider)
        self._spn_zoom = QSpinBox()
        self._spn_zoom.setRange(10, 21)
        self._spn_zoom.setValue(18)
        form.addRow(u"Zoom (detalhe):", self._spn_zoom)
        self._cbo_crs = QComboBox()
        for label, code in self.CRS_OPTIONS:
            self._cbo_crs.addItem(label, code)
        form.addRow(u"Sistema de coordenadas do GeoTIFF:", self._cbo_crs)
        lay.addWidget(box)

        self._lbl_tos = QLabel(cat.TOS_TEXT)
        self._lbl_tos.setWordWrap(True)
        self._lbl_tos.setStyleSheet("color: #78281f; background: #fdf2e9; border: 1px solid #f5cba7; padding: 4px;")
        lay.addWidget(self._lbl_tos)

        self._lbl_est = QLabel(u"Clique em \"Estimar\" para ver o número de tiles e o volume da área atual.")
        self._lbl_est.setWordWrap(True)
        lay.addWidget(self._lbl_est)

        btns = QHBoxLayout()
        self._btn_est = QPushButton(u"📏 Estimar")
        self._btn_est.clicked.connect(self._on_estimate)
        btns.addWidget(self._btn_est)
        self._btn_live = QPushButton(u"⚡ Adicionar como camada XYZ")
        self._btn_live.clicked.connect(self._on_live)
        btns.addWidget(self._btn_live)
        self._btn_dl = QPushButton(u"⬇ Baixar GeoTIFF da área")
        self._btn_dl.clicked.connect(self._on_download)
        btns.addWidget(self._btn_dl)
        btns.addStretch()
        lay.addLayout(btns)

        prow = QHBoxLayout()
        self._lbl_prog = QLabel(u"")
        prow.addWidget(self._lbl_prog, stretch=1)
        self._btn_cancel = QPushButton(u"■ Interromper")
        self._btn_cancel.setEnabled(False)
        self._btn_cancel.clicked.connect(self._runner.cancel)
        prow.addWidget(self._btn_cancel)
        self._pbar = QProgressBar()
        self._pbar.setFixedWidth(180)
        prow.addWidget(self._pbar)
        lay.addLayout(prow)

        close = QPushButton(u"Fechar")
        close.clicked.connect(self.reject)
        lay.addWidget(close, alignment=Qt.AlignRight)
        self._on_provider()

    def _provider(self):
        return self._cbo_provider.currentData()

    def _on_provider(self, *_):
        code, max_z, tos, url = self._provider()
        self._spn_zoom.setMaximum(max_z)
        self._lbl_tos.setVisible(bool(tos))
        self._btn_live.setEnabled(url is not None)
        self._btn_live.setToolTip(u"" if url else u"Esta fonte usa quadkeys: disponível só como download.")

    def _check_tos(self):
        code, _z, tos, _u = self._provider()
        if not tos or config.load_settings().get('tos_accepted'):
            return True
        ask = QMessageBox.question(self, u"Termos de uso", cat.TOS_TEXT + u"\n\nEntendi e quero continuar.",
                                   QMessageBox.Yes | QMessageBox.No)
        if ask != QMessageBox.Yes:
            return False
        try:
            config.save_settings({'tos_accepted': True})
        except Exception:
            pass
        return True

    def _area(self):
        if self._area_provider is None:
            return None
        return self._area_provider()

    def _busy(self, on):
        for b in (self._btn_est, self._btn_live, self._btn_dl, self._cbo_provider):
            b.setEnabled(not on)
        self._btn_cancel.setEnabled(on)
        if not on:
            self._on_provider()

    def _connect(self, on_finished, on_error):
        for sig in (self._runner.finished, self._runner.error):
            try:
                sig.disconnect()
            except TypeError:
                pass
        self._runner.finished.connect(on_finished)
        self._runner.error.connect(on_error)

    def _on_estimate(self):
        area = self._area()
        if area is None:
            return
        bbox, geojson = area
        p = {'zoom': self._spn_zoom.value()}
        p.update(sources.area_params(bbox, geojson))
        self._connect(self._on_estimate_done, self._on_error)
        self._busy(True)
        self._lbl_prog.setText(u"Estimando...")
        self._runner.run('xyz_estimate', p)

    def _on_estimate_done(self, res):
        self._busy(False)
        self._lbl_prog.setText(u"")
        if not res.get('success'):
            self._lbl_est.setText(res.get('message') or u"Falha na estimativa.")
            return
        self._lbl_est.setText(
            u"<b>%d tiles</b> (%d x %d) · %d x %d px · ~%s/pixel · ~%.0f MB de download" % (
                res.get('tiles', 0), res.get('cols', 0), res.get('rows', 0), res.get('width', 0), res.get('height', 0),
                sources.res_label(float(res.get('ground_res_m') or 0)), float(res.get('download_mb') or 0)))

    def _on_live(self):
        code, max_z, _tos, url = self._provider()
        if not url or not self._check_tos():
            return
        name = self._cbo_provider.currentText()
        try:
            add_xyz_tile_layer(url, u"%s (XYZ)" % name, max_zoom=max_z, group_name=u"QMagery")
        except Exception as e:
            QMessageBox.critical(self, u"Camada XYZ", u"Não foi possível adicionar a camada: %s" % e)
            return
        self._lbl_prog.setText(u"Camada \"%s\" adicionada ao grupo QMagery." % name)

    def _on_download(self):
        if not self._check_tos():
            return
        area = self._area()
        if area is None:
            return
        bbox, geojson = area
        code, _max_z, _tos, _url = self._provider()
        zoom = self._spn_zoom.value()
        folder = os.path.join(config.output_dir(), 'xyz')
        os.makedirs(folder, exist_ok=True)
        stem = u"%s_z%d" % (code, zoom)
        out = os.path.join(folder, stem + u".tif")
        n = 2
        while os.path.exists(out):
            out = os.path.join(folder, u"%s_%d.tif" % (stem, n))
            n += 1
        p = {'provider': code, 'zoom': zoom, 'out': out, 'crs': self._cbo_crs.currentData(),
             'workers': config.tile_threads()}
        p.update(sources.area_params(bbox, geojson))
        self._dl_name = u"%s z%d" % (self._cbo_provider.currentText(), zoom)
        self._connect(self._on_download_done, self._on_error)
        self._busy(True)
        self._pbar.setValue(0)
        self._lbl_prog.setText(u"Baixando os tiles...")
        self._runner.run('xyz_download', p)

    def _on_download_done(self, res):
        self._busy(False)
        if not res.get('success') or not res.get('file'):
            self._lbl_prog.setText(u"Falha no download.")
            QMessageBox.critical(self, u"Mosaico", res.get('message') or u"Falha no download.")
            return
        try:
            add_raster_layer(res['file'], self._dl_name, group_name=u"QMagery")
        except Exception as e:
            QMessageBox.critical(self, u"Mosaico", u"GeoTIFF salvo em %s, mas o QGIS não o abriu: %s" % (res['file'], e))
            return
        self._pbar.setValue(100)
        missing = res.get('missing_tiles') or 0
        self._lbl_prog.setText(u"Mosaico carregado%s." % (u" (%d tiles indisponíveis)" % missing if missing else u""))

    def _on_error(self, msg):
        self._busy(False)
        self._pbar.setValue(0)
        self._lbl_prog.setText(u"Interrompido." if msg == CANCELLED_MESSAGE else u"Falha.")
        if msg != CANCELLED_MESSAGE:
            QMessageBox.critical(self, u"Mosaico", msg)

    def _on_progress(self, line):
        import re
        m = re.search(r'PROGRESS\s+(\d+)\s*/\s*(\d+)', line)
        if m and int(m.group(2)) > 0:
            self._pbar.setValue(int(100 * int(m.group(1)) / int(m.group(2))))
        else:
            text = line.replace('[ArcGEE]', '').strip()
            if text and not text.startswith(('Traceback', 'File "')):
                self._lbl_prog.setText(text[:120])

    def done(self, r):
        self._runner.shutdown()
        super().done(r)
