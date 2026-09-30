# -*- coding: utf-8 -*-
"""
ArcMagery - tela de abertura (splash), chave do GEODES e tutorial (Python 2.7, Tk).

A splash aparece assim que o botao do ArcMap e clicado e, enquanto a janela principal e montada
escondida, verifica em paralelo:
  * Python 3 do backend, GDAL e numpy;
  * internet ate o GEODES (SPOT), o INPE (CBERS) e a Esri (mosaicos e alinhamento);
  * login do Google Earth Engine;
  * chave do GEODES (e a cota de downloads);
  * comunicacao com o ArcMap.
A janela principal abre ja com o estado de cada fonte conhecido. Falhas nao impedem a abertura:
cada uma vira um aviso com a orientacao do que fazer.

As regras (o que e erro, aviso ou OK) ficam em funcoes puras, testadas sem Tk.
"""
from __future__ import division

import os
import threading
import time
import webbrowser

import sys
if sys.version_info[0] < 3:
    import Tkinter as tk
    import ttk
    import tkMessageBox as messagebox
    import Queue as queue_mod
else:  # pragma: no cover - a GUI roda no Python 2.7 do ArcGIS
    import tkinter as tk
    from tkinter import ttk
    from tkinter import messagebox
    import queue as queue_mod

    unicode = str

import arcmagery_spot as spot
import gee_bridge

OK, INFO, WARN, FAIL, RUNNING, PENDING = 'ok', 'info', 'warn', 'fail', 'running', 'pending'
DONE = (OK, INFO, WARN, FAIL)
ICONS = {OK: u"✔", INFO: u"i", WARN: u"!", FAIL: u"✖", RUNNING: u"…", PENDING: u"·"}
COLORS = {OK: "#1e8449", INFO: "#2471a3", WARN: "#b9770e", FAIL: "#c0392b", RUNNING: "#1f618d",
          PENDING: "#7f8c8d"}

CHECKS = [
    ('python', u"Ambiente Python 3 do ArcMagery"),
    ('libs', u"Bibliotecas de imagem (GDAL e numpy)"),
    ('ee', u"Componentes do Earth Engine"),
    ('net', u"Internet: GEODES, INPE e Esri"),
    ('gee', u"Login do Google Earth Engine"),
    ('geodes', u"Chave do GEODES (SPOT 1-5)"),
    ('arcmap', u"Comunicação com o ArcMap"),
]
AUTO_CLOSE_MS = 900        # tudo OK: fecha sozinha depois deste tempo
WARN_CLOSE_S = 6           # com avisos: fecha sozinha depois desta contagem (botao Aguardar cancela)
SKIP_AFTER_S = 6           # o botao "Abrir agora" aparece depois deste tempo
CHECK_TIMEOUT_S = 60


# ------------------------------------------------------------------ regras (sem Tk)
def evaluate_selfcheck(resp, has_key):
    """Resposta do comando 'selfcheck' do backend -> {chave: (estado, texto)} para libs/net/geodes."""
    out = {}
    if not resp or not resp.get('success'):
        msg = (resp or {}).get('message') or u"o backend não respondeu"
        out['libs'] = (FAIL, u"Falha ao executar o Python 3: %s. Rode o install.bat." % msg)
        out['ee'] = (WARN, u"Não verificados (backend indisponível).")
        out['net'] = (WARN, u"Não verificada (backend indisponível).")
        out['geodes'] = (WARN, u"Não verificada (backend indisponível).")
        return out
    if resp.get('gdal') and resp.get('numpy'):
        out['libs'] = (OK, u"GDAL %s · numpy %s · Python %s" % (resp['gdal'], resp['numpy'], resp.get('python')))
    elif resp.get('numpy'):
        out['libs'] = (WARN, u"GDAL ausente: CBERS e SPOT não funcionam. Rode o install.bat.")
    else:
        out['libs'] = (FAIL, u"GDAL/numpy ausentes no Python 3. Rode o install.bat.")
    if resp.get('ee'):
        out['ee'] = (OK, u"earthengine-api %s" % resp['ee'])
    else:
        out['ee'] = (FAIL, u"Ausentes: o GEE não funciona. Clique em \"Instalar componentes do Earth Engine\" "
                           u"(sem pip, ~15 s).")
    net = resp.get('net') or {}
    names = {'geodes': u"GEODES", 'inpe': u"INPE", 'esri': u"Esri"}
    down = [names[k] for k in ('geodes', 'inpe', 'esri') if not (net.get(k) or {}).get('ok')]
    if not net:
        out['net'] = (WARN, u"Não verificada.")
    elif not down:
        out['net'] = (OK, u"GEODES, INPE e Esri acessíveis.")
    elif len(down) == 3:
        out['net'] = (FAIL, u"Sem acesso à internet (ou bloqueio do proxy). As buscas vão falhar.")
    else:
        out['net'] = (WARN, u"Sem acesso a: %s. As fontes desses serviços podem falhar." % u", ".join(down))
    key = resp.get('geodes_key')
    if not has_key:
        out['geodes'] = (INFO, u"Não configurada (opcional): só é necessária para BAIXAR cenas SPOT.")
    elif not key:
        out['geodes'] = (WARN, u"Não verificada.")
    elif key.get('ok'):
        out['geodes'] = (OK, u"Chave válida · %s de %s downloads disponíveis nesta hora."
                         % (key.get('remaining_quota'), key.get('max_quota')))
    elif u'401' in unicode(key.get('error') or u'') or u'recusou' in unicode(key.get('error') or u''):
        out['geodes'] = (FAIL, u"Chave recusada pelo GEODES. Gere outra no portal e cole em Configurações.")
    else:
        out['geodes'] = (WARN, u"Não foi possível validar agora: %s" % (key.get('error') or u'erro'))
    return out


def evaluate_gee(resp):
    if resp and resp.get('success'):
        return OK, resp.get('message') or u"Conectado."
    if resp and resp.get('ee_missing'):
        return WARN, u"Aguardando os componentes do Earth Engine (linha acima)."
    msg = (resp or {}).get('message') or u"não conectado"
    return WARN, u"%s. As demais fontes funcionam; use \"Autenticar GEE\" para o Earth Engine." % msg


def evaluate_arcmap(ctx):
    if ctx:
        return OK, u"ArcMap respondendo (escala 1:%s)." % (u"{:,}".format(int(ctx.get('scale') or 0)).replace(u',', u'.')
                                                         if ctx.get('scale') else u"n/d")
    return WARN, u"Sem resposta do ArcMap ainda. A janela funciona; a carga no TOC aguarda o ArcMap."


def describe_python(path):
    """Caminho do interpretador -> texto curto ('venv do ArcMagery', 'Python do QGIS 3.44', ...)."""
    parts = (path or u'').replace('/', '\\').split('\\')
    low = [p.lower() for p in parts]
    if 'arcmagery' in low and 'venv' in low:
        return u"venv do ArcMagery (%LOCALAPPDATA%\\ArcMagery\\venv)"
    qgis = [p for p in parts if p.lower().startswith('qgis')]
    if qgis:
        return u"Python do %s" % qgis[0]
    return path


def overall(states):
    vals = list(states.values())   # INFO nao e problema
    if any(s == FAIL for s in vals):
        return FAIL
    if any(s == WARN for s in vals):
        return WARN
    return OK


# ----------------------------------------------------------------------- execucao
def run_checks(report, read_context=None, check_gee=None, selfcheck=None, find_python=None, api_key=None):
    """Executa as verificacoes (em threads) e chama report(chave, estado, texto) a cada resultado.
    Dependencias injetaveis para os testes."""
    read_context = read_context or gee_bridge.read_arcmap_context
    check_gee = check_gee or gee_bridge.check_gee
    find_python = find_python or gee_bridge.find_python3_gdal
    api_key = spot.load_api_key() if api_key is None else api_key

    def do_selfcheck():
        report('python', RUNNING, u"Localizando o Python 3...")
        py = find_python()
        if not py or py == "python.exe":
            report('python', FAIL, u"Python 3 do ArcMagery não encontrado. Rode o install.bat.")
        else:
            report('python', OK, describe_python(py))
        for k in ('libs', 'net', 'geodes'):
            report(k, RUNNING, u"Verificando...")
        if selfcheck is not None:
            resp = selfcheck(api_key)
        else:
            resp = gee_bridge.run_backend_cmd('selfcheck', {'api_key': api_key or u'', 'timeout': 8},
                                              python_exe=py)
        for k, (state, text) in evaluate_selfcheck(resp, bool(api_key)).items():
            report(k, state, text)

    def do_gee():
        report('gee', RUNNING, u"Conectando ao Earth Engine...")
        try:
            resp = check_gee()
        except Exception as e:
            resp = {'success': False, 'message': gee_bridge.err_text(e)}
        state, text = evaluate_gee(resp)
        report('gee', state, text, resp)

    def do_arcmap():
        report('arcmap', RUNNING, u"Aguardando o ArcMap...")
        ctx = None
        for _ in range(12):
            ctx = read_context()
            if ctx:
                break
            time.sleep(0.25)
        state, text = evaluate_arcmap(ctx)
        report('arcmap', state, text)

    threads = [threading.Thread(target=_guard(fn, report, key)) for fn, key in
               ((do_selfcheck, 'libs'), (do_gee, 'gee'), (do_arcmap, 'arcmap'))]
    for t in threads:
        t.daemon = True
        t.start()
    return threads


def _guard(fn, report, key):
    def run():
        try:
            fn()
        except Exception as e:
            report(key, FAIL, u"Erro inesperado: %s" % gee_bridge.err_text(e))
    return run


# ------------------------------------------------------------------------------ splash
class StartupSplash(object):
    """Janela sem borda com as verificacoes de inicializacao."""

    def __init__(self, root, version, logo=None):
        self.root = root
        self.queue = queue_mod.Queue()
        self.states = {}
        self.gee_resp = None
        self._done_cb = None
        self._finished = False
        self._started = time.time()
        self.top = tk.Toplevel(root)
        self.top.overrideredirect(True)
        self.top.configure(bg="#1b4f72")
        # sem altura fixa: a janela cresce com o conteudo (textos longos nunca escondem os botoes)
        try:
            self.top.attributes('-topmost', True)
        except Exception:
            pass
        body = tk.Frame(self.top, bg="#fdfefe", padx=18, pady=14)
        body.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        head = tk.Frame(body, bg="#fdfefe")
        head.pack(fill=tk.X)
        if logo is not None:
            tk.Label(head, image=logo, bg="#fdfefe").pack(side=tk.LEFT, padx=(0, 10))
            self._logo = logo
        tk.Label(head, text=u"ArcMagery", font=("Segoe UI", 18, "bold"), bg="#fdfefe",
                 fg="#1b4f72").pack(side=tk.LEFT)
        tk.Label(head, text=u"  v%s" % version, font=("Segoe UI", 10), bg="#fdfefe",
                 fg="#5d6d7e").pack(side=tk.LEFT, pady=(8, 0))
        if "-" in str(version):   # versao experimental (nightly)
            tk.Label(head, text=u" EXPERIMENTAL ", font=("Segoe UI", 8, "bold"), bg="#ca6f1e",
                     fg="#ffffff").pack(side=tk.LEFT, padx=(8, 0), pady=(8, 0))
        tk.Label(body, text=u"Preparando o ambiente: verificando conexões, login e bibliotecas...",
                 font=("Segoe UI", 9), bg="#fdfefe", fg="#34495e").pack(anchor=tk.W, pady=(6, 8))
        grid = tk.Frame(body, bg="#fdfefe")
        grid.pack(fill=tk.X)
        self.rows = {}
        for i, (key, label) in enumerate(CHECKS):
            ico = tk.Label(grid, text=ICONS[PENDING], width=2, font=("Segoe UI", 11, "bold"), bg="#fdfefe",
                           fg=COLORS[PENDING])
            ico.grid(row=i, column=0, sticky=tk.NW)
            tk.Label(grid, text=label, font=("Segoe UI", 9, "bold"), bg="#fdfefe", fg="#212f3d",
                     anchor=tk.W).grid(row=i, column=1, sticky=tk.W)
            det = tk.Label(grid, text=u"", font=("Segoe UI", 8), bg="#fdfefe", fg="#566573", anchor=tk.W,
                           justify=tk.LEFT, wraplength=380)
            det.grid(row=i, column=2, sticky=tk.W, padx=(8, 0))
            self.rows[key] = (ico, det)
        grid.columnconfigure(2, weight=1)
        self.pbar = ttk.Progressbar(body, mode='determinate', maximum=len(CHECKS))
        self.pbar.pack(fill=tk.X, pady=(10, 6))
        self.lbl_summary = tk.Label(body, text=u"", font=("Segoe UI", 9, "bold"), bg="#fdfefe", fg="#1b4f72",
                                    anchor=tk.W)
        self.lbl_summary.pack(fill=tk.X)
        bar = tk.Frame(body, bg="#fdfefe")          # botoes numa linha propria, abaixo do resumo
        bar.pack(fill=tk.X, pady=(4, 0))
        self.btn_go = ttk.Button(bar, text=u"Abrir o ArcMagery", command=self.finish)
        self.btn_key = ttk.Button(bar, text=u"Configurar chave do GEODES", command=self._open_key)
        self.btn_wait = ttk.Button(bar, text=u"Aguardar", command=self._hold)
        self.btn_ee = ttk.Button(bar, text=u"Instalar componentes do Earth Engine", command=self._install_ee)
        self.btn_doctor = ttk.Button(bar, text=u"Diagnosticar e corrigir", command=self._run_doctor)
        self._check_kwargs = {}
        self._countdown = None
        self._recenter()

    def _recenter(self):
        """Centraliza pela altura real (chamado ao criar e quando o conteudo muda de tamanho)."""
        try:
            self.top.update_idletasks()
            w, h = max(680, self.top.winfo_reqwidth()), self.top.winfo_reqheight()
            sw, sh = self.top.winfo_screenwidth(), self.top.winfo_screenheight()
            self.top.geometry("+%d+%d" % (max(0, (sw - w) // 2), max(0, min((sh - h) // 3, sh - h - 40))))
            self.top.update()
        except Exception:
            pass

    # chamado de qualquer thread
    def report(self, key, state, text, extra=None):
        self.queue.put((key, state, text, extra))

    def start(self, on_done, **check_kwargs):
        self._done_cb = on_done
        self._check_kwargs = dict(check_kwargs)
        check_kwargs.pop('installer', None)        # so usados pelos botoes de instalacao e diagnostico
        check_kwargs.pop('doctor', None)
        run_checks(self.report, **check_kwargs)
        self._poll()

    def _poll(self):
        if self._finished:
            return
        try:
            while True:
                key, state, text, extra = self.queue.get_nowait()
                self._apply(key, state, text, extra)
        except queue_mod.Empty:
            pass
        final = [k for k, _ in CHECKS if self.states.get(k) in DONE]
        self.pbar['value'] = len(final)
        if len(final) == len(CHECKS):
            self._all_done()
            return
        if time.time() - self._started > SKIP_AFTER_S and not self.btn_go.winfo_ismapped():
            self.btn_go.config(text=u"Abrir agora (continuar verificando)")
            self.btn_go.pack(side=tk.RIGHT)
        if time.time() - self._started > CHECK_TIMEOUT_S:
            for k, _ in CHECKS:
                if self.states.get(k) not in DONE:
                    self._apply(k, WARN, u"Sem resposta em %d s." % CHECK_TIMEOUT_S, None)
            self._all_done()
            return
        self.top.after(120, self._poll)

    def _apply(self, key, state, text, extra):
        if key == '_summary':
            self._doctor_busy = False
            self._summary_locked = True        # o resumo do diagnostico nao e sobrescrito
            self.lbl_summary.config(text=text, fg=COLORS[WARN])
            try:
                self.btn_doctor.config(state=tk.NORMAL)
            except Exception:
                pass
            return
        self.states[key] = state
        if key == 'gee' and extra is not None:
            self.gee_resp = extra
        ico, det = self.rows[key]
        ico.config(text=ICONS[state], fg=COLORS[state])
        det.config(text=text or u"", fg=COLORS[state] if state in (INFO, WARN, FAIL) else "#566573")

    def _all_done(self):
        result = overall(dict((k, self.states.get(k)) for k, _ in CHECKS))
        self.lbl_summary.config(text={OK: u"Tudo pronto!", WARN: u"Pronto, com avisos (veja acima).",
                                      FAIL: u"Há problemas: algumas fontes não vão funcionar."}[result],
                                fg=COLORS[result])
        # ordem fixa: [Diagnosticar] ... [Chave GEODES] [Instalar componentes] [Aguardar] [Abrir]
        for btn in (self.btn_go, self.btn_wait, self.btn_ee, self.btn_key, self.btn_doctor):
            btn.pack_forget()
        self.btn_go.config(text=u"Abrir o ArcMagery")
        self.btn_go.pack(side=tk.RIGHT)
        if result == WARN:
            self.btn_wait.pack(side=tk.RIGHT, padx=(0, 6))
        if self.states.get('ee') == FAIL:
            self.btn_ee.pack(side=tk.RIGHT, padx=(0, 6))
        if self.states.get('geodes') in (INFO, WARN, FAIL):
            self.btn_key.pack(side=tk.RIGHT, padx=(0, 6))
        if result == FAIL:
            self.btn_doctor.pack(side=tk.LEFT)
        self._recenter()
        if result == OK:
            self.top.after(AUTO_CLOSE_MS, self.finish)
        elif result == WARN:
            self._countdown = WARN_CLOSE_S
            self._tick()

    def _tick(self):
        if self._finished or self._countdown is None:
            return
        if self._countdown <= 0:
            self.finish()
            return
        self.btn_go.config(text=u"Abrir o ArcMagery (%d s)" % self._countdown)
        self._countdown -= 1
        self.top.after(1000, self._tick)

    def _hold(self):
        """Cancela a abertura automatica para o usuario ler os avisos."""
        self._countdown = None
        self.btn_go.config(text=u"Abrir o ArcMagery")
        try:
            self.btn_wait.pack_forget()
        except Exception:
            pass

    def _install_ee(self, installer=None, check_gee=None):
        """Instala o earthengine-api sem pip e reverifica o login do GEE (sem fechar a splash)."""
        self._hold()
        try:
            self.btn_ee.config(state=tk.DISABLED)
        except Exception:
            pass
        installer = installer or self._check_kwargs.get('installer') or gee_bridge.install_ee_components
        check_gee = check_gee or self._check_kwargs.get('check_gee') or gee_bridge.check_gee
        self._apply('ee', RUNNING, u"Baixando e instalando (sem pip)...", None)
        self._apply('gee', PENDING, u"", None)

        def progress(line):
            text = (line or u'').replace('[ArcGEE] ', '')
            if u'Baixando componentes' in text:
                self.report('ee', RUNNING, text)

        def work():
            try:
                resp = installer(on_progress=progress)
            except Exception as e:
                resp = {'success': False, 'message': gee_bridge.err_text(e)}
            if resp.get('success') and resp.get('ee'):
                self.report('ee', OK, u"earthengine-api %s instalado em %s" % (resp['ee'], resp.get('dir')))
            else:
                self.report('ee', FAIL, u"Falha na instalação: %s" % (resp.get('message') or u'sem detalhes'))
            self.report('gee', RUNNING, u"Conectando ao Earth Engine...")
            try:
                g = check_gee()
            except Exception as e:
                g = {'success': False, 'message': gee_bridge.err_text(e)}
            state, text = evaluate_gee(g)
            self.report('gee', state, text, g)

        t = threading.Thread(target=work)
        t.daemon = True
        t.start()
        self._restart_poll()

    def _run_doctor(self, runner=None, opener=None):
        """Mesmo diagnostico do install.bat (corrige o que for seguro) e abre o relatorio."""
        self._hold()
        runner = runner or self._check_kwargs.get('doctor') or (lambda: gee_bridge.run_backend_cmd(
            'doctor', {'fix': True, 'test_gee': False}, python_exe=gee_bridge.find_python3_gdal()))
        opener = opener or _open_file
        try:
            self.btn_doctor.config(state=tk.DISABLED)
        except Exception:
            pass
        self._doctor_busy, self._summary_locked = True, False
        self.lbl_summary.config(text=u"Diagnosticando e corrigindo... (até ~1 min)", fg=COLORS[RUNNING])

        def work():
            try:
                res = runner()
            except Exception as e:
                res = {'success': False, 'message': gee_bridge.err_text(e)}
            for c in res.get('checks') or []:
                if c.get('id') == 'ee':
                    self.report('ee', OK if c['status'] in ('ok', 'fixed') else FAIL, c.get('detail'))
                elif c.get('id') == 'libs':
                    self.report('libs', {'ok': OK, 'fixed': OK, 'warn': WARN}.get(c['status'], FAIL), c.get('detail'))
            fixed = sum(1 for c in res.get('checks') or [] if c.get('status') == 'fixed')
            problems = sum(1 for c in res.get('checks') or [] if c.get('status') == 'fail')
            self.report('_summary', RUNNING, u"Diagnóstico: %d corrigido(s), %d problema(s) restante(s). "
                                             u"Relatório aberto." % (fixed, problems))
            if res.get('report'):
                opener(res['report'])

        t = threading.Thread(target=work)
        t.daemon = True
        t.start()
        self._restart_poll()

    def _restart_poll(self):
        """Volta a processar a fila de resultados depois de uma acao na splash ja concluida."""
        def pump():
            if self._finished:
                return
            try:
                while True:
                    key, state, text, extra = self.queue.get_nowait()
                    self._apply(key, state, text, extra)
            except queue_mod.Empty:
                pass
            result = overall(dict((k, self.states.get(k)) for k, _ in CHECKS))
            busy = any(self.states.get(k) in (RUNNING, PENDING) for k, _ in CHECKS) or getattr(self, '_doctor_busy', False)
            if not busy and getattr(self, '_summary_locked', False):
                self._recenter()
                return
            if not busy:
                self.lbl_summary.config(text={OK: u"Tudo pronto!", WARN: u"Pronto, com avisos (veja acima).",
                                              FAIL: u"Há problemas: algumas fontes não vão funcionar."}[result],
                                        fg=COLORS[result])
                try:
                    self.btn_ee.config(state=tk.NORMAL)
                    if self.states.get('ee') != FAIL:
                        self.btn_ee.pack_forget()
                except Exception:
                    pass
                return
            self.top.after(150, pump)
        self.top.after(150, pump)

    def _open_key(self):
        self._hold()
        GeodesKeyDialog(self.top, on_saved=self._key_saved)

    def _key_saved(self, resp):
        state = OK if resp and resp.get('success') else WARN
        self._apply('geodes', state, spot.quota_text(resp) or u"Chave salva (não validada).", None)

    def finish(self):
        if self._finished:
            return
        self._finished = True
        try:
            self.top.destroy()
        except Exception:
            pass
        if self._done_cb:
            self._done_cb(self)


def center_on(top, parent):
    """Centraliza a janela sobre a janela-mae (ou na tela, se a mae estiver escondida)."""
    try:
        top.update_idletasks()
        w, h = top.winfo_reqwidth(), top.winfo_reqheight()
        if parent is not None and parent.winfo_viewable():
            x = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
            y = parent.winfo_rooty() + (parent.winfo_height() - h) // 2
        else:
            x, y = (top.winfo_screenwidth() - w) // 2, (top.winfo_screenheight() - h) // 3
        top.geometry("+%d+%d" % (max(0, x), max(0, y)))
    except Exception:
        pass


# ----------------------------------------------------------------- chave do GEODES
class GeodesKeyFrame(object):
    """Campo da chave + Testar / Salvar / Tutorial. Usado nas Configurações e no diálogo avulso."""

    def __init__(self, master, on_saved=None):
        self.master = master
        self.on_saved = on_saved
        self.frame = ttk.Frame(master)
        ttk.Label(self.frame, text=u"Chave de API do GEODES (CNES) para baixar cenas SPOT 1-5 (1986-2015):",
                  font=("Segoe UI", 9, "bold")).pack(anchor=tk.W)
        row = ttk.Frame(self.frame)
        row.pack(fill=tk.X, pady=(4, 2))
        self.var_key = tk.StringVar(value=spot.load_api_key() or u"")
        self.var_show = tk.BooleanVar(value=False)
        self.ent = ttk.Entry(row, textvariable=self.var_key, show=u"•", width=52)
        self.ent.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Checkbutton(row, text=u"Mostrar", variable=self.var_show, command=self._toggle).pack(side=tk.LEFT, padx=4)
        btns = ttk.Frame(self.frame)
        btns.pack(fill=tk.X, pady=(4, 2))
        self.btn_test = ttk.Button(btns, text=u"Testar chave", command=self.on_test)
        self.btn_test.pack(side=tk.LEFT)
        ttk.Button(btns, text=u"Salvar chave", style="Primary.TButton", command=self.on_save).pack(side=tk.LEFT, padx=6)
        ttk.Button(btns, text=u"Como obter a chave (tutorial)", command=self.on_tutorial).pack(side=tk.LEFT)
        self.lbl = tk.Label(self.frame, text=self._initial_status(), font=("Segoe UI", 8), fg="#1b4f72",
                            justify=tk.LEFT, anchor=tk.W, wraplength=470)
        self.lbl.pack(fill=tk.X, pady=(4, 0))
        tk.Label(self.frame, text=spot.TUTORIAL_NOTES, font=("Segoe UI", 8), fg="#566573", justify=tk.LEFT,
                 anchor=tk.W, wraplength=470).pack(fill=tk.X, pady=(6, 0))

    def _initial_status(self):
        key = spot.load_api_key()
        return (u"Chave configurada (%s). Clique em Testar para ver a cota." % spot.mask_key(key)) if key else \
            u"Nenhuma chave configurada. A BUSCA de cenas SPOT funciona sem chave; o DOWNLOAD precisa dela."

    def _toggle(self):
        self.ent.config(show=u"" if self.var_show.get() else u"•")

    def _key(self):
        return (self.var_key.get() or u"").strip()

    def _set(self, text, color="#1b4f72"):
        try:
            self.lbl.config(text=text, fg=color)
        except Exception:
            pass

    def on_test(self, then=None):
        key = self._key()
        if not spot.looks_like_key(key):
            self._set(u"A chave parece incompleta: copie o texto inteiro do campo \"API Key\" do portal.", "#c0392b")
            return
        self.btn_test.config(state=tk.DISABLED)
        self._set(u"Testando a chave no GEODES...")
        box = {}

        def work():
            box['resp'] = spot.check_key(key)

        t = threading.Thread(target=work)
        t.daemon = True
        t.start()

        def wait():
            if t.is_alive():
                self.frame.after(150, wait)
                return
            resp = box.get('resp') or {}
            try:
                self.btn_test.config(state=tk.NORMAL)
            except Exception:
                return
            if resp.get('success'):
                self._set(u"✔ Chave válida · %s." % spot.quota_text(resp), "#1e8449")
            else:
                self._set(u"✖ %s" % (resp.get('message') or u"Chave não validada."), "#c0392b")
            if then:
                then(resp)
        self.frame.after(150, wait)

    def on_save(self):
        key = self._key()
        if key and not spot.looks_like_key(key):
            self._set(u"A chave parece incompleta: copie o texto inteiro do campo \"API Key\" do portal.", "#c0392b")
            return

        def store(resp):
            if not resp.get('success') and key:
                if not messagebox.askyesno(u"Chave do GEODES", u"A chave não foi validada:\n%s\n\nSalvar mesmo assim?"
                                           % (resp.get('message') or u''), parent=self.frame.winfo_toplevel()):
                    return
            if spot.save_api_key(key):
                self._set((u"✔ Chave salva. %s" % (spot.quota_text(resp) or u'')) if key else u"Chave removida.",
                          "#1e8449")
                if self.on_saved:
                    self.on_saved(resp)
            else:
                self._set(u"✖ Não foi possível gravar %s." % spot.key_file(), "#c0392b")

        if key:
            self.on_test(then=store)
        else:
            store({'success': False})

    def on_tutorial(self):
        GeodesTutorialDialog(self.frame.winfo_toplevel())


class GeodesKeyDialog(object):
    def __init__(self, parent, on_saved=None):
        self.top = tk.Toplevel(parent)
        self.top.title(u"Chave do GEODES (SPOT) - ArcMagery")
        self.top.resizable(False, False)
        try:
            self.top.transient(parent)
            self.top.attributes('-topmost', True)
        except Exception:
            pass
        box = ttk.Frame(self.top, padding=12)
        box.pack(fill=tk.BOTH, expand=True)

        def saved(resp):
            if on_saved:
                on_saved(resp)
            self.top.after(800, self.top.destroy)
        self.key = GeodesKeyFrame(box, on_saved=saved)
        self.key.frame.pack(fill=tk.BOTH, expand=True)
        ttk.Button(box, text=u"Fechar", command=self.top.destroy).pack(anchor=tk.E, pady=(10, 0))
        center_on(self.top, parent)
        self.top.grab_set()


class GeodesTutorialDialog(object):
    """Passo a passo para criar a conta e gerar a chave no portal GEODES."""

    def __init__(self, parent):
        self.top = tk.Toplevel(parent)
        self.top.title(u"Como obter a chave do GEODES - ArcMagery")
        self.top.resizable(False, False)
        try:
            self.top.transient(parent)
            self.top.attributes('-topmost', True)
        except Exception:
            pass
        box = tk.Frame(self.top, bg="#fdfefe", padx=16, pady=12)
        box.pack(fill=tk.BOTH, expand=True)
        tk.Label(box, text=u"Chave de API do GEODES em 5 passos (gratuito, ~3 minutos)",
                 font=("Segoe UI", 11, "bold"), bg="#fdfefe", fg="#1b4f72").pack(anchor=tk.W, pady=(0, 8))
        for title, text in spot.TUTORIAL_STEPS:
            tk.Label(box, text=title, font=("Segoe UI", 9, "bold"), bg="#fdfefe", fg="#212f3d",
                     anchor=tk.W).pack(anchor=tk.W, pady=(4, 0))
            tk.Label(box, text=text, font=("Segoe UI", 9), bg="#fdfefe", fg="#34495e", justify=tk.LEFT,
                     anchor=tk.W, wraplength=520).pack(anchor=tk.W, padx=(12, 0))
        tk.Label(box, text=spot.TUTORIAL_NOTES, font=("Segoe UI", 8), bg="#fdfefe", fg="#7b241c",
                 justify=tk.LEFT, anchor=tk.W, wraplength=530).pack(anchor=tk.W, pady=(10, 4))
        bar = tk.Frame(box, bg="#fdfefe")
        bar.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(bar, text=u"Abrir o portal GEODES", style="Primary.TButton",
                   command=lambda: webbrowser.open(spot.GEODES_PORTAL)).pack(side=tk.LEFT)
        ttk.Button(bar, text=u"Fechar", command=self.top.destroy).pack(side=tk.RIGHT)
        center_on(self.top, parent)


def _open_file(path):
    try:
        os.startfile(path)
    except Exception:
        try:
            import subprocess
            subprocess.Popen(["notepad.exe", path])
        except Exception:
            pass
