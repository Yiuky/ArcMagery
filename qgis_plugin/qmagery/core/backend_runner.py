# -*- coding: utf-8 -*-
"""
Execução do backend do ArcMagery (run_gee.py) a partir do QGIS: o equivalente ao gee_bridge.py.

Contrato com o backend (o mesmo do ArcMagery):
  - parâmetros num arquivo JSON UTF-8 (--params-file);
  - progresso no stderr, linhas com o prefixo [ArcGEE] (PROGRESS <feito>/<total> quando houver);
  - resultado: a ÚLTIMA linha do stdout que começa com '{' (JSON com 'success').

O backend roda num processo separado (e não importado no QGIS) porque encerra com os._exit() por
causa do GDAL/curl e porque um erro nele não pode derrubar o QGIS.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

try:
    from qgis.PyQt.QtCore import QObject, QThread, pyqtSignal
except ImportError:   # CI sem QGIS: as funções puras (parse_result, run_sync...) continuam testáveis
    try:
        from PyQt5.QtCore import QObject, QThread, pyqtSignal
    except ImportError:
        class QObject(object):
            def __init__(self, *args, **kwargs):
                pass

        class QThread(QObject):
            pass

        def pyqtSignal(*args, **kwargs):
            return None

from . import config

CANCELLED_MESSAGE = u"Operação interrompida pelo usuário."


def get_python_executable():
    """Python 3 do próprio QGIS. Dentro do QGIS, sys.executable é o qgis-bin.exe: passar argumentos a ele
    abriria uma camada ("Fonte de dados inválida"). O python.exe fica em sys.base_prefix
    (apps\\Python3xx) e herda do QGIS o PATH do GDAL."""
    env_py = os.environ.get('QMAGERY_PYTHON') or os.environ.get('GEE_PYTHON3')
    if env_py and os.path.isfile(env_py):
        return env_py
    exe = sys.executable or ''
    if os.path.basename(exe).lower() in ('python.exe', 'python3.exe', 'python', 'python3') and os.path.isfile(exe):
        return exe
    names = ('python.exe', 'python3.exe') if os.name == 'nt' else ('python3', 'python')
    dirs = [os.path.normpath(getattr(sys, 'base_prefix', sys.prefix)), os.path.normpath(sys.prefix)]
    if os.name != 'nt':
        dirs = [os.path.join(d, 'bin') for d in dirs]
    if exe:
        dirs.append(os.path.dirname(exe))
    for d in dirs:
        for n in names:
            c = os.path.join(d, n)
            if os.path.isfile(c):
                return c
    found = shutil.which('python3') or shutil.which('python')
    return found or exe


def subprocess_kwargs():
    """Sem janela preta de console no Windows."""
    kwargs = {}
    if sys.platform == 'win32':
        kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        kwargs['startupinfo'] = si
    return kwargs


_get_subprocess_kwargs = subprocess_kwargs   # nome antigo, usado pelos testes


def backend_env():
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUTF8'] = '1'
    # O PYTHONPATH do QGIS aponta para os módulos dele; o backend usa só a biblioteca padrão,
    # o GDAL do site-packages e as bibliotecas do Earth Engine instaladas sem pip (pylibs).
    env.pop('PYTHONPATH', None)
    return env


def write_params(params):
    fd, path = tempfile.mkstemp(suffix='.json', prefix='qmagery_params_')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(params, f, ensure_ascii=False)
    return path


def parse_result(stdout_text):
    """Última linha JSON do stdout (o contrato do backend); None se não houver."""
    for line in reversed((stdout_text or '').splitlines()):
        line = line.strip()
        if line.startswith('{'):
            try:
                return json.loads(line)
            except ValueError:
                continue
    return None


def kill_tree(proc):
    if proc is None or proc.poll() is not None:
        return
    if sys.platform == 'win32':
        try:
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(proc.pid)], capture_output=True, timeout=15,
                           **subprocess_kwargs())
        except Exception:
            pass
    try:
        proc.kill()
    except Exception:
        pass


class BackendError(RuntimeError):
    """Erro retornado pelo backend (success=false no JSON ou sem resposta)."""

    def __init__(self, message, diagnostics=None):
        super().__init__(message)
        self.diagnostics = diagnostics or {}


class _BackendWorker(QObject):
    """Executa UM comando numa QThread. Sinais: progress(linha), finished(dict), error(mensagem)."""

    progress = pyqtSignal(str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, command, params, timeout=None):
        super().__init__()
        self.command = command
        self.params = dict(params)
        self.params['command'] = command
        self.timeout = timeout
        self.done = False             # True logo antes de emitir finished/error
        self._cancelled = False
        self._timed_out = False
        self._proc = None
        self._last_activity = time.time()

    def cancel(self):
        self._cancelled = True
        kill_tree(self._proc)

    def _succeed(self, result):
        self.done = True
        self.finished.emit(result)

    def _fail(self, message):
        self.done = True
        self.error.emit(message)

    def _watchdog(self):
        """Prazo de INATIVIDADE: zera a cada linha do backend (downloads longos com progresso não expiram)."""
        while self._proc is not None and self._proc.poll() is None:
            if self.timeout and time.time() - self._last_activity > self.timeout:
                self._timed_out = True
                kill_tree(self._proc)
                return
            time.sleep(0.5)

    def run(self):
        if self._cancelled:
            self._fail(CANCELLED_MESSAGE)
            return
        params_file = None
        stderr_tail = []
        try:
            run_gee = config.run_gee_path()
            if not os.path.isfile(run_gee):
                self._fail(u"Backend não encontrado: %s\nReinstale o QMagery." % run_gee)
                return
            params_file = write_params(self.params)
            self._last_activity = time.time()
            self._proc = subprocess.Popen(
                [get_python_executable(), run_gee, self.command, '--params-file=' + params_file],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                env=backend_env(), cwd=os.path.dirname(run_gee), **subprocess_kwargs())
            if self._cancelled:
                kill_tree(self._proc)
                self._fail(CANCELLED_MESSAGE)
                return

            def read_stderr():
                try:
                    for raw in self._proc.stderr:
                        self._last_activity = time.time()
                        line = raw.decode('utf-8', 'replace').rstrip()
                        if not line:
                            continue
                        stderr_tail.append(line)
                        del stderr_tail[:-40]
                        if not self._cancelled:
                            self.progress.emit(line)
                except Exception:
                    pass

            t_err = threading.Thread(target=read_stderr, daemon=True)
            t_err.start()
            threading.Thread(target=self._watchdog, daemon=True).start()

            stdout_data = self._proc.stdout.read()
            self._proc.wait()
            t_err.join(timeout=5)

            if self._cancelled:
                self._fail(CANCELLED_MESSAGE)
                return
            if self._timed_out:
                self._fail(u"O backend ficou %d s sem responder e foi encerrado (%s). Tente de novo; se "
                           u"repetir, use uma área menor." % (self.timeout, self.command))
                return
            result = parse_result(stdout_data.decode('utf-8', 'replace'))
            if result is None:
                self._fail(u"O backend não retornou uma resposta válida (%s).\n\n%s"
                           % (self.command, u'\n'.join(stderr_tail[-15:]) or u'(sem mensagens)'))
                return
            self._succeed(result)
        except Exception as exc:
            self._fail(CANCELLED_MESSAGE if self._cancelled else u"%s: %s" % (type(exc).__name__, exc))
        finally:
            for stream in ('stdout', 'stderr'):
                try:
                    getattr(self._proc, stream).close()
                except Exception:
                    pass
            if params_file:
                try:
                    os.remove(params_file)
                except OSError:
                    pass


class BackendRunner(QObject):
    """
    Executa comandos do backend sem travar o QGIS.

        runner = BackendRunner(parent)
        runner.progress.connect(...); runner.finished.connect(...); runner.error.connect(...)
        runner.run('stac_search', {...})

    Um runner executa um comando por vez. shutdown() cancela e espera a thread terminar: chamar ao
    fechar a janela e no unload do plugin (uma QThread destruída em execução derruba o QGIS).
    """

    progress = pyqtSignal(str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None
        self._worker = None
        self._retired = []   # threads que já entregaram o resultado e estão encerrando

    @property
    def backend_dir(self):
        return config.backend_dir()

    @property
    def run_gee_path(self):
        return config.run_gee_path()

    def is_running(self):
        """True enquanto o comando atual não entregou o resultado. Um novo comando pode começar dentro do
        slot de finished/error do anterior (fila de downloads): a thread antiga termina sozinha."""
        return self._worker is not None and not self._worker.done

    def cancel(self):
        if self._worker is not None:
            self._worker.cancel()

    def shutdown(self, wait_ms=8000):
        self.cancel()
        for thread in [self._thread] + list(self._retired):
            if thread is not None and thread.isRunning():
                thread.quit()
                thread.wait(wait_ms)

    def run(self, command, params, timeout=None):
        if self.is_running():
            raise RuntimeError(u"Já existe uma operação em andamento.")
        if self._thread is not None:
            self._retired.append(self._thread)
        from .sources import timeout_for
        thread = QThread()
        worker = _BackendWorker(command, params, timeout or timeout_for(command))
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.progress)
        worker.finished.connect(self._on_finished)
        worker.error.connect(self._on_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(lambda t=thread, w=worker: self._cleanup(t, w))
        self._thread, self._worker = thread, worker
        thread.start()

    def _on_finished(self, result):
        self.finished.emit(result)

    def _on_error(self, message):
        self.error.emit(message)

    def _cleanup(self, thread, worker):
        if thread in self._retired:
            self._retired.remove(thread)
        if self._thread is thread:
            self._thread = None
            self._worker = None
        worker.deleteLater()
        thread.deleteLater()

    def run_sync(self, command, params, timeout=120):
        """Execução síncrona (testes, diagnóstico). Não chamar na thread principal do QGIS."""
        return run_sync(command, params, timeout)


def run_sync(command, params, timeout=120):
    params = dict(params)
    params['command'] = command
    params_file = write_params(params)
    try:
        proc = subprocess.run([get_python_executable(), config.run_gee_path(), command, '--params-file=' + params_file],
                              capture_output=True, timeout=timeout, env=backend_env(), stdin=subprocess.DEVNULL,
                              cwd=config.backend_dir(), **subprocess_kwargs())
        result = parse_result(proc.stdout.decode('utf-8', 'replace'))
        if result is None:
            raise BackendError(u"Backend sem resposta JSON.\n%s" % proc.stderr.decode('utf-8', 'replace')[-2000:])
        if not result.get('success'):
            raise BackendError(result.get('message', u"Erro desconhecido no backend."), result.get('diagnostics'))
        return result
    finally:
        try:
            os.remove(params_file)
        except OSError:
            pass


def open_console(script, args=()):
    """Abre um script do backend numa janela de console VISÍVEL (autenticação interativa do Google)."""
    script_path = os.path.join(config.backend_dir(), script)
    kwargs = {}
    if sys.platform == 'win32':
        kwargs['creationflags'] = getattr(subprocess, 'CREATE_NEW_CONSOLE', 0x00000010)
    return subprocess.Popen([get_python_executable(), script_path] + [a for a in args if a],
                            env=backend_env(), cwd=config.backend_dir(), **kwargs)
