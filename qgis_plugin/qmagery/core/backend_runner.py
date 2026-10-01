# -*- coding: utf-8 -*-
"""
Substituto do gee_bridge.py para o QGIS.

Chama arcgis_addin/Install/backend/run_gee.py como subprocess e entrega:
  - progresso via sinal Qt (stderr com prefixo [ArcGEE])
  - resultado via sinal Qt (última linha JSON no stdout)

Contrato com o backend (herdado do ArcMagery):
  - UMA linha JSON no stdout (a última que começa com '{').
  - Progresso no stderr com prefixo [ArcGEE] PROGRESS <n>/<total>.
  - Exit code 0 = sucesso (verificar success no JSON), != 0 = falha.

Nota: como o QGIS já é Python 3, poderíamos importar os módulos diretamente.
O subprocess é mantido por dois motivos:
  1. O backend chama os._exit() ao terminar (necessário para o GDAL/curl).
  2. Isolamento: erros no backend não derrubam o QGIS.
"""
import io
import json
import os
import subprocess
import sys
import tempfile
from typing import Dict, Any, Optional, Callable

from qgis.PyQt.QtCore import QObject, QThread, pyqtSignal


# os.path.realpath resolve junctions e symlinks do Windows.
# Sem isso, quando o plugin está instalado via junction no diretório de plugins do QGIS,
# o __file__ aponta para o alvo da junction e o caminho relativo (..'s) fica errado.
# Hierarquia: core/ → qmagery/ → qgis_plugin/ → ArcMagery/ → arcgis_addin/Install/backend/
_THIS_FILE = os.path.realpath(__file__)
_BACKEND_DIR = os.path.normpath(
    os.path.join(os.path.dirname(_THIS_FILE), '..', '..', '..',
                 'arcgis_addin', 'Install', 'backend')
)
_RUN_GEE = os.path.join(_BACKEND_DIR, 'run_gee.py')


def get_python_executable() -> str:
    """
    Retorna o executável Python 3 correto.
    No Windows dentro do QGIS Desktop, sys.executable aponta para qgis-ltr-bin.exe (ou qgis.exe).
    Se passarmos argumentos como [sys.executable, script, ...], o QGIS tenta abrir o script
    como uma camada de mapa/projeto, gerando o erro 'Fonte de dados inválida: --params-file=...'.
    Esta função localiza o python.exe ou python3.exe no ambiente do QGIS/OSGeo4W.
    """
    # 1. Se sys.executable já terminar com python.exe ou python3.exe, verifica se existe
    exe = sys.executable or ""
    exe_name = os.path.basename(exe).lower()
    if exe_name in ('python.exe', 'python3.exe', 'pythonw.exe') and os.path.isfile(exe):
        return exe

    # 2. Procura em sys.prefix / base_prefix / apps/Python3xx
    candidates = []
    base = os.path.normpath(getattr(sys, 'base_prefix', sys.prefix))
    candidates.append(os.path.join(base, 'python.exe'))
    candidates.append(os.path.join(base, 'python3.exe'))

    # Diretório bin do QGIS (ex: C:\Program Files\QGIS 3.44.10\bin\python.exe)
    root = os.path.dirname(os.path.dirname(base))
    candidates.append(os.path.join(root, 'bin', 'python.exe'))
    candidates.append(os.path.join(root, 'bin', 'python3.exe'))

    # Se exe estiver em <QGIS>\bin\qgis-ltr-bin.exe
    if os.path.dirname(exe):
        candidates.append(os.path.join(os.path.dirname(exe), 'python.exe'))
        candidates.append(os.path.join(os.path.dirname(exe), 'python3.exe'))

    # Variável de ambiente específica
    env_py = os.environ.get('PYTHON_EXECUTABLE') or os.environ.get('GEE_PYTHON3')
    if env_py:
        candidates.insert(0, env_py)

    for c in candidates:
        if c and os.path.isfile(c):
            return os.path.realpath(c)

    return sys.executable


def _get_subprocess_kwargs() -> Dict[str, Any]:
    """Retorna flags para subprocess ocultando totalmente janelas de console no Windows."""
    kwargs: Dict[str, Any] = {}
    if sys.platform == 'win32':
        kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        kwargs['startupinfo'] = si
    return kwargs


class BackendError(RuntimeError):
    """Erro retornado pelo backend (success=false no JSON ou exit != 0)."""
    def __init__(self, message: str, diagnostics: Optional[Dict] = None):
        super().__init__(message)
        self.diagnostics = diagnostics or {}


class _BackendWorker(QObject):
    """Worker executado em QThread separada."""

    # Sinais emitidos durante a execução
    progress = pyqtSignal(str)        # mensagem de progresso (linha stderr)
    finished = pyqtSignal(dict)       # resultado (dict JSON final)
    error = pyqtSignal(str)           # mensagem de erro (antes do JSON)

    def __init__(self, command: str, params: Dict[str, Any]):
        super().__init__()
        self.command = command
        self.params = params
        self._cancelled = False
        self._proc: Optional[subprocess.Popen] = None

    def cancel(self):
        """Cancela imediatamente o processo em execução."""
        self._cancelled = True
        proc = self._proc
        if proc and proc.poll() is None:
            if sys.platform == 'win32':
                try:
                    subprocess.run(
                        ['taskkill', '/F', '/T', '/PID', str(proc.pid)],
                        capture_output=True,
                        **_get_subprocess_kwargs()
                    )
                except Exception:
                    pass
            try:
                proc.kill()
            except Exception:
                pass
            try:
                proc.terminate()
            except Exception:
                pass

    def run(self):
        """Executa o backend e emite sinais de progresso/resultado."""
        if self._cancelled:
            self.error.emit('Operação cancelada.')
            return

        fd, params_file = tempfile.mkstemp(suffix='.json', prefix='qmagery_params_')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(self.params, f, ensure_ascii=False)

            env = dict(os.environ)
            env['PYTHONIOENCODING'] = 'utf-8'
            env.pop('PYTHONPATH', None)

            py_exe = get_python_executable()
            self._proc = subprocess.Popen(
                [py_exe, _RUN_GEE, self.command,
                 '--params-file=' + params_file],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                **_get_subprocess_kwargs()
            )

            if self._cancelled:
                self.cancel()
                self.error.emit('Operação cancelada.')
                return

            # Lê stderr em thread separada para não bloquear stdout
            import threading
            stderr_lines = []

            def _read_stderr():
                try:
                    if self._proc and self._proc.stderr:
                        for raw in self._proc.stderr:
                            if self._cancelled:
                                break
                            line = raw.decode('utf-8', 'replace').rstrip()
                            stderr_lines.append(line)
                            self.progress.emit(line)
                except Exception:
                    pass

            t = threading.Thread(target=_read_stderr, daemon=True)
            t.start()

            stdout_data = b''
            try:
                if self._proc and self._proc.stdout:
                    stdout_data = self._proc.stdout.read()
            except Exception:
                pass

            if self._proc:
                self._proc.wait()
            t.join(timeout=2)

            if self._cancelled:
                self.error.emit('Operação cancelada.')
                return

            # Localiza a última linha JSON no stdout
            lines = [
                l for l in stdout_data.decode('utf-8', 'replace').splitlines()
                if l.strip().startswith('{')
            ]
            if not lines:
                stderr_text = '\n'.join(stderr_lines[-20:])
                self.error.emit(
                    f'Backend não retornou JSON válido.\nStderr:\n{stderr_text}'
                )
                return

            result = json.loads(lines[-1])
            self.finished.emit(result)

        except Exception as exc:
            if not self._cancelled:
                self.error.emit(str(exc))
        finally:
            try:
                os.remove(params_file)
            except OSError:
                pass


class BackendRunner(QObject):
    """
    Interface pública para executar comandos do backend.

    Uso:
        runner = BackendRunner()
        runner.progress.connect(status_bar.showMessage)
        runner.finished.connect(on_result)
        runner.error.connect(on_error)
        runner.run('sources_info', {})
    """

    progress = pyqtSignal(str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread: Optional[QThread] = None
        self._worker: Optional[_BackendWorker] = None

    @property
    def backend_dir(self) -> str:
        """Caminho do diretório backend (para testes e diagnóstico)."""
        return _BACKEND_DIR

    @property
    def run_gee_path(self) -> str:
        """Caminho do run_gee.py (para testes e diagnóstico)."""
        return _RUN_GEE

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def cancel(self):
        """Solicita cancelamento da operação em andamento."""
        if self._worker:
            self._worker.cancel()

    def run(self, command: str, params: Dict[str, Any]):
        """
        Executa um comando do backend de forma assíncrona.

        :param command: Nome do comando (ex: 'sources_info', 'stac_search').
        :param params: Dicionário de parâmetros (serializado como JSON).
        """
        if self.is_running():
            raise RuntimeError('BackendRunner já está executando um comando.')

        params = dict(params)
        params['command'] = command

        self._thread = QThread()
        self._worker = _BackendWorker(command, params)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup)

        self._thread.start()

    def _on_finished(self, result: dict):
        self.finished.emit(result)

    def _on_error(self, msg: str):
        self.error.emit(msg)

    def _cleanup(self):
        if self._thread:
            self._thread.deleteLater()
        self._thread = None
        self._worker = None

    def run_sync(self, command: str, params: Dict[str, Any], timeout: int = 120) -> dict:
        """
        Executa um comando de forma síncrona (para testes e diagnóstico).
        Não deve ser chamado na thread principal do QGIS.
        """
        params = dict(params)
        params['command'] = command

        fd, params_file = tempfile.mkstemp(suffix='.json', prefix='qmagery_params_')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(params, f, ensure_ascii=False)

            env = dict(os.environ)
            env['PYTHONIOENCODING'] = 'utf-8'
            env.pop('PYTHONPATH', None)

            py_exe = get_python_executable()
            proc = subprocess.run(
                [py_exe, _RUN_GEE, command,
                 '--params-file=' + params_file],
                capture_output=True,
                timeout=timeout,
                env=env,
                **_get_subprocess_kwargs()
            )
            lines = [
                l for l in proc.stdout.decode('utf-8', 'replace').splitlines()
                if l.strip().startswith('{')
            ]
            if not lines:
                stderr = proc.stderr.decode('utf-8', 'replace')
                raise BackendError(f'Backend sem resposta JSON.\nStderr: {stderr}')
            result = json.loads(lines[-1])
            if not result.get('success'):
                raise BackendError(
                    result.get('message', 'Erro desconhecido no backend.'),
                    result.get('diagnostics')
                )
            return result
        finally:
            try:
                os.remove(params_file)
            except OSError:
                pass
