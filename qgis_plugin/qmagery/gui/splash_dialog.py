# -*- coding: utf-8 -*-
"""
Verificação do ambiente ao abrir o QMagery (equivalente à tela de abertura do ArcMagery).

Roda o diagnóstico rápido do backend (selfcheck: Python, GDAL, numpy, Earth Engine, internet e chave do
GEODES) no Python que o QMagery vai usar, e oferece a instalação dos componentes do Earth Engine (sem
pip) quando faltarem. Nada aqui bloqueia o uso: as fontes sem Earth Engine funcionam mesmo assim.
"""
from qgis.PyQt.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QTextEdit, QVBoxLayout,
)

from ..core import config
from ..core.backend_runner import CANCELLED_MESSAGE, BackendRunner, get_python_executable
from .support_dialogs import GeodesKeyDialog

OK, WARN, FAIL = u'✅', u'⚠️', u'❌'


def summarize(res, backend_found=True):
    """Resposta do selfcheck -> (linhas [(ícone, texto)], ee_missing). Sem Qt: testável."""
    lines = []
    if not backend_found:
        return [(FAIL, u"Backend não encontrado em %s. Reinstale o QMagery." % config.backend_dir())], False
    lines.append((OK, u"Python %s (%s)" % (res.get('python', '?'), get_python_executable())))
    if res.get('gdal'):
        lines.append((OK, u"GDAL %s" % res['gdal']))
    else:
        lines.append((FAIL, u"GDAL indisponível: CBERS, SPOT e os mosaicos não funcionam (%s)"
                      % (res.get('gdal_error') or u'?')))
    if res.get('numpy'):
        lines.append((OK, u"numpy %s" % res['numpy']))
    else:
        lines.append((WARN, u"numpy ausente: o SPOT não funciona"))
    ee_missing = not res.get('ee')
    if ee_missing:
        lines.append((WARN, u"Componentes do Earth Engine não instalados: instale abaixo (as outras fontes funcionam)"))
    else:
        pyl = res.get('pylibs') or {}
        extra = u"" if pyl.get('current', True) or not pyl.get('installed') else u" (há atualização: reinstale)"
        lines.append((OK, u"earthengine-api %s%s" % (res['ee'], extra)))
    names = {'inpe': u"INPE (CBERS)", 'geodes': u"GEODES (SPOT)", 'esri': u"Esri"}
    for key, label in names.items():
        r = (res.get('net') or {}).get(key) or {}
        lines.append((OK, u"Internet: %s acessível" % label) if r.get('ok')
                     else (WARN, u"Internet: %s inacessível (%s)" % (label, (r.get('error') or u'?')[:90])))
    key = res.get('geodes_key')
    if key is None:
        lines.append((WARN, u"Chave do GEODES não configurada: o download do SPOT exige a chave (gratuita)"))
    elif key.get('ok'):
        lines.append((OK, u"Chave do GEODES válida (%s de %s downloads nesta hora)"
                      % (key.get('remaining_quota'), key.get('max_quota'))))
    else:
        lines.append((WARN, u"Chave do GEODES recusada: %s" % (key.get('error') or u'?')[:120]))
    return lines, ee_missing


class SplashDialog(QDialog):

    def __init__(self, parent=None, auto_run=True):
        super().__init__(parent)
        self.setWindowTitle(u"QMagery — verificação do ambiente")
        self.setMinimumSize(620, 380)
        self._runner = BackendRunner(self)
        lay = QVBoxLayout(self)
        title = QLabel(u"<b>QMagery %s</b> — verificando o ambiente..." % config.version_label())
        title.setStyleSheet("font-size: 11pt;")
        lay.addWidget(title)
        self._label = title
        self._bar = QProgressBar()
        self._bar.setRange(0, 0)
        lay.addWidget(self._bar)
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        lay.addWidget(self._log, stretch=1)

        row = QHBoxLayout()
        self._btn_install = QPushButton(u"Instalar componentes do Earth Engine")
        self._btn_install.setVisible(False)
        self._btn_install.clicked.connect(self._on_install)
        row.addWidget(self._btn_install)
        self._btn_key = QPushButton(u"Chave do GEODES...")
        self._btn_key.clicked.connect(self._on_key)
        row.addWidget(self._btn_key)
        self._btn_retry = QPushButton(u"Verificar de novo")
        self._btn_retry.clicked.connect(self.run_checks)
        row.addWidget(self._btn_retry)
        row.addStretch()
        lay.addLayout(row)

        bottom = QHBoxLayout()
        self._chk_show = QCheckBox(u"Verificar sempre ao abrir")
        self._chk_show.setChecked(bool(config.load_settings().get('show_startup_check', True)))
        bottom.addWidget(self._chk_show)
        bottom.addStretch()
        self._btn_continue = QPushButton(u"Continuar")
        self._btn_continue.setDefault(True)
        self._btn_continue.clicked.connect(self.accept)
        bottom.addWidget(self._btn_continue)
        cancel = QPushButton(u"Cancelar")
        cancel.clicked.connect(self.reject)
        bottom.addWidget(cancel)
        lay.addLayout(bottom)
        if auto_run:
            self.run_checks()

    def _busy(self, on, text=None):
        self._bar.setRange(0, 0 if on else 1)
        self._bar.setValue(0 if on else 1)
        for b in (self._btn_install, self._btn_key, self._btn_retry):
            b.setEnabled(not on)
        if text:
            self._label.setText(text)

    def _connect(self, on_finished, on_error):
        for sig in (self._runner.finished, self._runner.error, self._runner.progress):
            try:
                sig.disconnect()
            except TypeError:
                pass
        self._runner.finished.connect(on_finished)
        self._runner.error.connect(on_error)

    def run_checks(self):
        import os
        if not os.path.isfile(config.run_gee_path()):
            self._show(summarize({}, backend_found=False))
            return
        self._busy(True, u"<b>QMagery %s</b> — verificando o ambiente..." % config.version_label())
        self._log.clear()
        self._connect(lambda res: self._show(summarize(res)), self._on_error)
        self._runner.run('selfcheck', {'api_key': config.load_geodes_key()})

    def _show(self, summary):
        lines, ee_missing = summary
        self._busy(False)
        self._log.setPlainText(u"\n".join(u"%s %s" % (icon, text) for icon, text in lines))
        if getattr(self, '_note', None):
            self._log.append(u"\n" + self._note)
            self._note = None
        bad = any(icon == FAIL for icon, _t in lines)
        warn = any(icon == WARN for icon, _t in lines)
        self._label.setText(u"<b>QMagery %s</b> — %s" % (
            config.version_label(),
            u"há itens que impedem o uso (veja abaixo)." if bad else
            u"pronto; alguns itens são opcionais (veja abaixo)." if warn else u"ambiente OK."))
        self._btn_install.setVisible(ee_missing)

    def _on_error(self, msg):
        self._busy(False, u"Não foi possível verificar o ambiente.")
        if msg != CANCELLED_MESSAGE:
            self._log.setPlainText(msg)

    def _on_install(self):
        self._busy(True, u"Instalando os componentes do Earth Engine (cerca de 20 MB, sem pip)...")
        self._connect(self._on_installed, self._on_error)
        self._runner.progress.connect(lambda line: self._log.append(line.replace('[ArcGEE]', '').strip()))
        self._runner.run('pylibs_install', {})

    def _on_installed(self, res):
        if res.get('success') and res.get('ee'):
            self._note = (u"%s earthengine-api %s instalado. Agora autentique-se em \"Projeto GEE...\" na janela "
                          u"principal." % (OK, res['ee']))
        else:
            self._note = u"%s Falha na instalação: %s" % (FAIL, res.get('message') or u'?')
        self.run_checks()

    def _on_key(self):
        GeodesKeyDialog(self).exec_()
        self.run_checks()

    def done(self, r):
        self._runner.shutdown()
        try:
            config.save_settings({'show_startup_check': self._chk_show.isChecked()})
        except Exception:
            pass
        super().done(r)
