# -*- coding: utf-8 -*-
"""
================================================================================
ArcMagery - Módulo de Atualização Robusto e Transacional (gee_updater)
================================================================================
Engenharia de Confiabilidade e Automação para Atualizações via Git/GitHub e ZIP.

Princípios Arquiteturais:
1. Robustez e Atomicidade:
   - Execução em estágios com barreira de transação.
   - Nenhuma modificação é feita antes da validação completa (pre-flight checks).
   - O processo de aplicação é desacoplado do interpretador Python em execução
     (evitando travamento de arquivos do Windows / WinError 32).
2. Validações Prévias (Pre-flight checks):
   - Para Git/GitHub: conectividade de rede, permissões, branch/tag remota,
     detecção de working tree suja (dirty working tree) e divergência (merge conflicts).
   - Para .zip: integridade CRC-32 (testzip), hash SHA-256 opcional, verificação
     de espaço em disco (com margem de segurança de 3x + buffer de 50MB),
     permissão real de escrita e validação contra Zip Slip / Path Traversal.
3. Backup e Rollback Automático:
   - Snapshot completo do .esriaddin atual e do AssemblyCache antes da aplicação.
   - Se qualquer etapa do script de aplicação falhar ou o smoke test pós-cópia
     não passar, o script reverte automaticamente para o estado anterior íntegro.
4. Tratamento de Exceções e Feedback Estruturado:
   - Exceções tipadas com mensagens claras em português e ações recomendadas.
   - Detalhes técnicos, tracebacks e comandos executados salvos em arquivo de log.

Compatibilidade: Python 2.7 (ArcGIS 10.8) e Python 3.x (QGIS / Standalone).
================================================================================
"""

import os
import sys
import time
import shutil
import tempfile
import zipfile
import hashlib
import socket
import subprocess
import traceback
import xml.etree.ElementTree as ET

# ==============================================================================
# CONSTANTES DE IDENTIFICAÇÃO E CAMINHOS DO SISTEMA
# ==============================================================================

ADDIN_UUID = "{ceae58c4-c44e-4edd-b8f4-1ba7d13b6b7d}"
ADDIN_UUID_UPPER = "{CEAE58C4-C44E-4EDD-B8F4-1BA7D13B6B7D}"

GITHUB_REPO_URL = "https://github.com/Yiuky/ArcMagery"
GITHUB_ZIP_URL = "https://github.com/Yiuky/ArcMagery/archive/refs/heads/main.zip"
# Canal oficial: GitHub Releases com arquivo de hashes publicado junto do pacote.
GITHUB_API_LATEST_RELEASE = "https://api.github.com/repos/Yiuky/ArcMagery/releases/latest"
# Lista de Releases (inclui pre-releases/nightly; /latest so devolve a ultima ESTAVEL)
GITHUB_API_RELEASES = "https://api.github.com/repos/Yiuky/ArcMagery/releases?per_page=40"
# Reserva sem a API (que aceita 60 consultas/h por IP SEM login, somando toda a rede da empresa): o feed
# Atom das Releases (estaveis e nightlies) e o SHA256SUMS.txt de cada uma, que lista o pacote
GITHUB_RELEASES_FEED = "https://github.com/Yiuky/ArcMagery/releases.atom"
GITHUB_RELEASE_DOWNLOAD = "https://github.com/Yiuky/ArcMagery/releases/download"
# Canais de atualizacao: estavel (Releases normais) e experimental (pre-releases "-nightly.AAAAMMDD")
CHANNEL_STABLE, CHANNEL_NIGHTLY = "stable", "nightly"
CHANNEL_LABELS = {CHANNEL_STABLE: u"Estável", CHANNEL_NIGHTLY: u"Experimental (nightly)"}
RELEASE_CHECKSUM_ASSET = "SHA256SUMS.txt"
def _installed_version(default="2.4"):
    """Versao do config.xml instalado (AssemblyCache: ao lado deste arquivo; repositorio: pasta acima)."""
    import re
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (os.path.join(here, "config.xml"), os.path.join(here, "..", "config.xml")):
        try:
            with open(p, "rb") as f:
                m = re.search(br"<Version>\s*([0-9A-Za-z.+-]+)\s*</Version>", f.read())
            if m:
                return str(m.group(1).decode("ascii"))
        except Exception:
            pass
    return default


UPDATER_USER_AGENT = "ArcMagery-Updater/%s" % _installed_version()
GITHUB_HOST = "github.com"
GITHUB_PORT = 443

# Componentes nucleares obrigatórios no pacote
ESSENTIAL_COMPONENTS = ["config.xml", "gee_gui.py", "gee_bridge.py", "gee_core.py"]

# Dispositivos reservados do Windows proibidos em nomes de arquivos (Zip Slip / DoS)
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"
}

# ==============================================================================
# HIERARQUIA DE EXCEÇÕES ESTRUTURADAS
# ==============================================================================

class UpdaterError(Exception):
    """
    Exceção base para o subsistema de atualização.
    Contém campos específicos para geração de interface amigável ao usuário.
    """
    def __init__(self, message, title=None, user_message=None, remediation=None, technical_details=None):
        if sys.version_info[0] < 3 and isinstance(message, unicode):
            encoded_msg = message.encode("utf-8")
        else:
            encoded_msg = str(message)
        super(UpdaterError, self).__init__(encoded_msg)
        self.message = message
        self.title = title or u"Erro de Atualização"
        self.user_message = user_message or message
        self.remediation = remediation or []
        self.technical_details = technical_details or ""

    def __str__(self):
        if sys.version_info[0] < 3:
            if isinstance(self.user_message, unicode):
                return self.user_message.encode("utf-8", "replace")
        return str(self.user_message)

    def __unicode__(self):
        if sys.version_info[0] < 3:
            if isinstance(self.user_message, unicode):
                return self.user_message
            return unicode(str(self.user_message), "utf-8", "replace")
        return str(self.user_message)


class PreflightCheckError(UpdaterError):
    """Erro emitido durante as validações prévias antes de modificar qualquer arquivo."""
    pass

class NetworkError(PreflightCheckError):
    """Falha de conexão com a internet, DNS ou servidores do GitHub."""
    pass

class GitRepositoryError(PreflightCheckError):
    """Falha relacionada ao repositório Git local (dirty tree, stashes, merge conflicts)."""
    pass

class SecurityValidationError(PreflightCheckError):
    """Violação de segurança detectada no pacote (Zip Slip / Path Traversal)."""
    pass

class CorruptPackageError(PreflightCheckError):
    """Arquivo ZIP com dados corrompidos ou falha de soma de verificação CRC/SHA-256."""
    pass

class DiskSpaceError(PreflightCheckError):
    """Espaço livre em disco insuficiente para extração, backup ou instalação."""
    pass

class PermissionCheckError(PreflightCheckError):
    """Permissão negada para leitura, escrita ou exclusão nos diretórios necessários."""
    pass

class MissingComponentsError(PreflightCheckError):
    """Pacote de atualização não contém a estrutura esperada do plugin."""
    pass

class ConfirmationRequired(UpdaterError):
    """A operacao exige confirmacao explicita do usuario (ex.: pacote sem verificacao de
    integridade ou downgrade). A GUI pergunta e repete a chamada com `flag`=True."""
    def __init__(self, message, flag, **kwargs):
        super(ConfirmationRequired, self).__init__(message, **kwargs)
        self.flag = flag


class RollbackTriggeredError(UpdaterError):
    """Falha ocorrida durante a aplicação, acionando restauração automática do backup."""
    pass

# ==============================================================================
# CAMINHOS SEMPRE EM UNICODE (Python 2: os.environ e tempfile devolvem bytes no codepage
# ANSI; misturar esses bytes com texto unicode quebrava com perfis acentuados, ex. C:\Users\joão)
# ==============================================================================

def _fs_text(path):
    """Caminho como texto unicode. Bytes sao decodificados com a codificacao do sistema de arquivos."""
    if path is None:
        return u""
    if sys.version_info[0] < 3 and isinstance(path, bytes):
        enc = sys.getfilesystemencoding() or "mbcs"
        try:
            return path.decode(enc)
        except Exception:
            return path.decode(enc, "replace")
    return path


def _err(e):
    """Texto unicode de uma excecao: no Python 2 unicode(e) quebra com mensagens localizadas do
    Windows em bytes (WindowsError em pt-BR) e str(e) quebra com mensagens unicode acentuadas."""
    if sys.version_info[0] >= 3:
        return str(e)
    try:
        return unicode(e)
    except UnicodeError:
        pass
    parts = []
    for a in (getattr(e, "args", None) or (e,)):
        if isinstance(a, bytes):
            for enc in ("utf-8", "mbcs", "cp1252"):
                try:
                    parts.append(a.decode(enc))
                    break
                except (UnicodeError, LookupError):
                    continue
            else:
                parts.append(a.decode("ascii", "replace"))
        else:
            try:
                parts.append(unicode(a))
            except UnicodeError:
                parts.append(unicode(repr(a)))
    return u" ".join(parts) or unicode(repr(e))


def _env_path(name, default=u""):
    return _fs_text(os.environ.get(name, "")) or default


def _temp_dir():
    return _fs_text(tempfile.gettempdir())


def _documents_dir():
    """Pasta Documentos REAL do usuario (com o OneDrive / Known Folder Move ela sai do perfil e o
    ArcMap usa a redirecionada). SHGetFolderPathW(CSIDL_PERSONAL); se falhar, %USERPROFILE%\\Documents."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(1024)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:
            return buf.value
    except Exception:
        pass
    return os.path.join(_env_path("USERPROFILE"), u"Documents")


# ==============================================================================
# SISTEMA DE LOGGING ESTRUTURADO
# ==============================================================================

def get_app_data_dir():
    """Retorna o diretório base para dados do aplicativo CGMA ArcGEE (%LOCALAPPDATA%\\CGMA_ArcGEE)."""
    user_prof = _env_path("USERPROFILE")
    local_appdata = _env_path("LOCALAPPDATA") or os.path.join(user_prof, u"AppData", u"Local")
    base_dir = os.path.join(local_appdata, u"CGMA_ArcGEE")
    if not os.path.exists(base_dir):
        try:
            os.makedirs(base_dir)
        except Exception:
            pass
    return base_dir

def get_updater_log_path():
    """Retorna o caminho completo para o arquivo de log das atualizações."""
    base_dir = get_app_data_dir()
    logs_dir = os.path.join(base_dir, "logs")
    if not os.path.exists(logs_dir):
        try:
            os.makedirs(logs_dir)
        except Exception:
            logs_dir = _temp_dir()
    return os.path.join(logs_dir, u"arcgee_updater.log")

def get_backups_dir():
    """Retorna o diretório raiz onde os snapshots de backup são armazenados."""
    base_dir = get_app_data_dir()
    backups_dir = os.path.join(base_dir, "backups")
    if not os.path.exists(backups_dir):
        try:
            os.makedirs(backups_dir)
        except Exception:
            backups_dir = os.path.join(_temp_dir(), u"arcgee_backups")
            if not os.path.exists(backups_dir):
                try:
                    os.makedirs(backups_dir)
                except Exception:
                    pass
    return backups_dir

def log_message(level, message, exc=None):
    """
    Registra uma mensagem no arquivo de log do atualizador de forma atômica e segura.
    Compatível com Python 2.7 e Python 3.x.
    """
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    log_path = get_updater_log_path()
    try:
        # Normalização de texto para UTF-8
        if sys.version_info[0] < 3:
            if isinstance(message, unicode):
                msg_str = message.encode("utf-8", "replace")
            else:
                msg_str = str(message)
        else:
            msg_str = str(message)

        line = "[%s] [%s] %s\n" % (timestamp, level.upper(), msg_str)
        if exc is not None:
            tb = traceback.format_exc()
            line += "Traceback:\n%s\n" % tb

        with open(log_path, "a") as f:
            f.write(line)
    except Exception:
        pass

def log_info(msg):
    log_message("INFO", msg)

def log_warning(msg):
    log_message("WARNING", msg)

def log_error(msg, exc=None):
    log_message("ERROR", msg, exc=exc)

# ==============================================================================
# UTILITÁRIOS DE BAIXO NÍVEL (COMPATIBILIDADE DUAL PYTHON 2.7 / 3.X)
# ==============================================================================

def get_free_disk_space_bytes(folder_path):
    """
    Calcula o espaço livre em bytes na unidade correspondente ao caminho informado.
    Utiliza Win32 GetDiskFreeSpaceExW (compatível com Python 2.7 e 3.x).
    """
    abs_path = os.path.abspath(folder_path)
    if not os.path.isdir(abs_path):
        abs_path = os.path.dirname(abs_path) or abs_path

    # Tentativa 1: API Win32 GetDiskFreeSpaceExW
    try:
        import ctypes
        free_bytes = ctypes.c_ulonglong(0)
        total_bytes = ctypes.c_ulonglong(0)
        free_user_bytes = ctypes.c_ulonglong(0)

        # Garante wchar_p no Python 2 e Python 3
        if sys.version_info[0] < 3:
            wchar_path = _fs_text(abs_path)
        else:
            wchar_path = str(abs_path)

        ret = ctypes.windll.kernel32.GetDiskFreeSpaceExW(
            ctypes.c_wchar_p(wchar_path),
            ctypes.byref(free_user_bytes),
            ctypes.byref(total_bytes),
            ctypes.byref(free_bytes)
        )
        if ret:
            return free_user_bytes.value
    except Exception as e:
        log_warning(u"Falha em GetDiskFreeSpaceExW: %s" % _err(e))

    # Tentativa 2: shutil.disk_usage (Python 3)
    try:
        if hasattr(shutil, "disk_usage"):
            return shutil.disk_usage(abs_path).free
    except Exception:
        pass

    # Se não puder determinar, retorna um valor padrão conservador (500MB)
    return 524288000

def test_write_permission(directory_path):
    """
    Testa de forma empírica a permissão de criação, escrita e remoção de arquivo.
    Evita falsos positivos comuns do os.access(W_OK) no Windows.
    """
    if not os.path.exists(directory_path):
        try:
            os.makedirs(directory_path)
        except Exception as e:
            return False, u"Nao foi possivel criar o diretorio: %s" % _err(e)

    canary = os.path.join(
        directory_path,
        ".arcgee_perm_check_%d_%d.tmp" % (os.getpid(), int(time.time() * 1000) % 100000)
    )
    try:
        with open(canary, "w") as f:
            f.write("write_permission_check")
        if os.path.exists(canary):
            os.remove(canary)
        return True, None
    except Exception as e:
        return False, _err(e)

def calculate_file_sha256(filepath):
    """Calcula o hash SHA-256 do arquivo em blocos de 64KB."""
    sha = hashlib.sha256()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            sha.update(chunk)
    return sha.hexdigest()

def parse_version(text):
    """'v1.10' / '1.10.0' / '2.4.1-nightly.20260930' -> (1, 10, 0) / ... / (2, 4, 1): so o nucleo
    numerico. Retorna None se nao for uma versao numerica. Para ORDENAR use version_key()."""
    try:
        core = str(text).strip().lstrip("vV").split("+")[0].split("-")[0]
        parts = core.split(".")
        nums = [int(p) for p in parts if p != ""]
        while len(nums) < 3:
            nums.append(0)
        return tuple(nums[:3])
    except Exception:
        return None


def is_prerelease(text):
    """'2.4.1-nightly.20260930' -> True (versao experimental); '2.4.0' -> False."""
    return "-" in str(text or "").strip().lstrip("vV").split("+")[0]


def version_key(text):
    """Chave de ordenacao semver: 2.4.0 < 2.4.1-nightly.20260930 < 2.4.1-nightly.20261001 < 2.4.1.
    Retorna None se a versao nao for reconhecida."""
    core = parse_version(text)
    if core is None:
        return None
    s = str(text).strip().lstrip("vV").split("+")[0]
    if "-" not in s:
        return core + (1, ())
    ident = []
    for part in s.split("-", 1)[1].replace("-", ".").split("."):
        ident.append((1, int(part), u"") if part.isdigit() else (0, 0, part))
    return core + (0, tuple(ident))


def default_channel(current_version):
    """Quem ja esta numa versao experimental continua no canal experimental."""
    return CHANNEL_NIGHTLY if is_prerelease(current_version) else CHANNEL_STABLE


def _http_get(url, timeout=30, accept=None):
    """GET simples compativel com Python 2.7 (urllib2) e 3 (urllib.request). Retorna bytes."""
    headers = {"User-Agent": UPDATER_USER_AGENT}
    if accept:
        headers["Accept"] = accept
    if sys.version_info[0] < 3:
        import urllib2
        resp = urllib2.urlopen(urllib2.Request(url, headers=headers), timeout=timeout)
    else:
        import urllib.request
        resp = urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout)
    try:
        return resp.read()
    finally:
        resp.close()


def parse_sha256sums(text):
    """Le o formato do `sha256sum`: '<hash>  <arquivo>' por linha. Retorna {arquivo: hash}."""
    out = {}
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) == 2 and len(parts[0]) == 64:
            out[parts[1].strip().lstrip("*")] = parts[0].lower()
    return out


def _net_text(e):
    """Texto de um erro de rede sem o repr do Py2 ("error(10061, 'conex\\xe3o...')"): a mensagem do socket
    (URLError.reason) decodificada na pagina de codigo do Windows, com o numero do erro."""
    inner = getattr(e, "reason", None)
    if inner is not None and not isinstance(inner, (str, type(u""))):
        e = inner
    args = getattr(e, "args", ())
    if len(args) >= 2 and isinstance(args[0], int):
        msg = args[1]
        if isinstance(msg, bytes):
            msg = msg.decode("mbcs" if os.name == "nt" else "utf-8", "replace")
        return u"%s (erro %d)" % (msg, args[0])
    return _err(e)


def failure_reason(e):
    """Motivo da falha de consulta ao GitHub em portugues, para a mensagem ao usuario."""
    code = getattr(e, "code", None)
    headers = getattr(e, "headers", None) or getattr(e, "hdrs", None)
    remaining = None
    try:
        remaining = headers.get("X-RateLimit-Remaining") if headers is not None else None
    except Exception:
        pass
    if code in (403, 429) and (remaining == "0" or code == 429):
        return (u"o GitHub recusou a consulta (HTTP %d): a rede atingiu o limite de consultas por hora da API do "
                u"GitHub, que soma todos os computadores que saem pelo mesmo endereço" % code)
    text = _net_text(e)
    low = text.lower()
    if "certificate" in low or "ssl" in low:
        return u"falha de certificado SSL (inspeção do proxy da rede): %s" % text
    if code:
        return u"o GitHub respondeu HTTP %d" % code
    return text


def _release_query_error(what, e, feed_error=None):
    reason = failure_reason(e)
    err = NetworkError(
        u"Falha ao consultar %s do GitHub: %s%s" % (what, _err(e), (u" | feed: %s" % _err(feed_error)) if feed_error else u""),
        title=u"Falha ao Consultar Releases",
        user_message=u"Não foi possível consultar as versões publicadas no GitHub.\n\nMotivo: %s." % reason,
        remediation=[u"Tente de novo em alguns minutos (o limite do GitHub zera a cada hora).",
                     u"Verifique a conexão/proxy.",
                     u"Ou baixe o ArcMagery-<versão>.zip em %s/releases e use a atualização via arquivo ZIP."
                     % GITHUB_REPO_URL],
        technical_details=traceback.format_exc())
    err.reason = reason
    return err


def fetch_release_from_feed(channel=CHANNEL_STABLE, feed_url=GITHUB_RELEASES_FEED, download_base=GITHUB_RELEASE_DOWNLOAD):
    """Reserva da API: a Release mais nova do canal pelo feed Atom e pelo SHA256SUMS.txt dela (nenhum dos
    dois conta no limite da API). Mesmo dict de _release_info, ou None se nao houver Release com hashes."""
    import re
    try:
        from urllib import unquote
    except ImportError:
        from urllib.parse import unquote
    text = _http_get(feed_url, timeout=20).decode("utf-8", "replace")
    tags = []
    for t in re.findall(r'/releases/tag/([^"<>\s]+)', text):
        t = unquote(t)
        if t not in tags and version_key(t) is not None and (channel == CHANNEL_NIGHTLY or not is_prerelease(t)):
            tags.append(t)
    tags.sort(key=version_key, reverse=True)
    for tag in tags[:5]:
        sums_url = "%s/%s/%s" % (download_base, tag, RELEASE_CHECKSUM_ASSET)
        try:
            names = sorted(n for n in parse_sha256sums(_http_get(sums_url, timeout=20)) if n.lower().endswith(".zip"))
        except Exception as e_sums:
            log_warning(u"Feed de Releases: %s sem %s (%s)." % (tag, RELEASE_CHECKSUM_ASSET, _err(e_sums)))
            continue
        zips = [n for n in names if n.lower().startswith("arcmagery-")] or names
        if zips:
            return {"version": tag.lstrip("vV"), "tag": tag, "prerelease": is_prerelease(tag), "zip_name": zips[0],
                    "zip_url": "%s/%s/%s" % (download_base, tag, zips[0]), "sums_url": sums_url}
    return None


def _api_or_feed(what, api_call, channel, feed_url, download_base):
    """A API primeiro; se ela falhar (limite por hora, proxy), o feed. Erro so se os dois falharem."""
    try:
        return api_call()
    except Exception as e_api:
        if getattr(e_api, "code", None) == 404:
            return None
        log_warning(u"API do GitHub falhou ao consultar %s (%s); tentando o feed de Releases." % (what, failure_reason(e_api)))
        try:
            return fetch_release_from_feed(channel, feed_url, download_base)
        except Exception as e_feed:
            raise _release_query_error(what, e_api, e_feed)


def fetch_latest_release(api_url=GITHUB_API_LATEST_RELEASE, feed_url=GITHUB_RELEASES_FEED,
                         download_base=GITHUB_RELEASE_DOWNLOAD):
    """Consulta a ultima Release publicada. Retorna None se o repositorio ainda nao tem Releases.
    Retorna dict: version, tag, zip_name, zip_url, sums_url."""
    import json

    def api():
        return _release_info(json.loads(_http_get(api_url, timeout=20, accept="application/vnd.github+json").decode("utf-8")))
    return _api_or_feed(u"a última Release", api, CHANNEL_STABLE, feed_url, download_base)


def _release_info(data):
    assets = data.get("assets") or []
    zips = [a for a in assets if a.get("name", "").lower().endswith(".zip")]
    # Desde a 2.4.3 a Release traz tambem o QMagery-<versao>.zip (plugin do QGIS): o pacote do
    # ArcMagery e escolhido pelo nome; o primeiro .zip so vale para Releases antigas sem esse padrao.
    named = [a for a in zips if a.get("name", "").lower().startswith("arcmagery-")]
    zips = named or zips
    sums = [a for a in assets if a.get("name") == RELEASE_CHECKSUM_ASSET]
    tag = data.get("tag_name") or ""
    return {
        "version": tag.lstrip("vV"),
        "tag": tag,
        "prerelease": bool(data.get("prerelease")) or is_prerelease(tag),
        "zip_name": zips[0]["name"] if zips else None,
        "zip_url": zips[0].get("browser_download_url") if zips else None,
        "sums_url": sums[0].get("browser_download_url") if sums else None,
    }


def fetch_newest_release(api_url=GITHUB_API_RELEASES, feed_url=GITHUB_RELEASES_FEED,
                         download_base=GITHUB_RELEASE_DOWNLOAD):
    """Canal experimental: a Release mais nova da lista (estavel OU nightly), so as publicadas com
    pacote e SHA256SUMS. Retorna None se nao houver."""
    import json

    def api():
        return _newest_of(json.loads(_http_get(api_url, timeout=20, accept="application/vnd.github+json").decode("utf-8")))
    return _api_or_feed(u"as Releases", api, CHANNEL_NIGHTLY, feed_url, download_base)


def _newest_of(data):
    best = None
    for item in data or []:
        if item.get("draft"):
            continue
        info = _release_info(item)
        if not (info["zip_url"] and info["sums_url"]) or version_key(info["version"]) is None:
            continue
        if best is None or version_key(info["version"]) > version_key(best["version"]):
            best = info
    return best


def fetch_release_for_channel(channel=CHANNEL_STABLE):
    return fetch_newest_release() if channel == CHANNEL_NIGHTLY else fetch_latest_release()


AVAIL_NEW, AVAIL_CURRENT, AVAIL_OLDER, AVAIL_NONE, AVAIL_ERROR = "new", "current", "older", "none", "error"


def describe_available(current_version, channel=CHANNEL_STABLE, fetch=None):
    """(estado, texto) da versao publicada no canal comparada a instalada, para a janela de atualizacao.
    Nunca levanta: uma falha vira AVAIL_ERROR com o motivo."""
    label = CHANNEL_LABELS.get(channel, u"")
    try:
        rel = (fetch or fetch_release_for_channel)(channel)
    except Exception as e:
        reason = getattr(e, "reason", None)      # NetworkError: motivo pronto; URLError: o erro do socket
        if not isinstance(reason, type(u"")):
            reason = failure_reason(e)
        return AVAIL_ERROR, u"Não foi possível consultar a versão disponível: %s." % reason
    if not rel or not rel.get("version"):
        return AVAIL_NONE, u"Nenhuma versão publicada no canal %s." % label
    new_k, cur_k = version_key(rel["version"]), version_key(current_version)
    if new_k and cur_k and new_k > cur_k:
        return AVAIL_NEW, u"Disponível no canal %s: v%s (instalada: v%s). Clique em Iniciar Atualização Online." % (
            label, rel["version"], current_version)
    if new_k and cur_k and new_k == cur_k:
        return AVAIL_CURRENT, u"Você já está na versão mais recente do canal %s: v%s." % (label, current_version)
    return AVAIL_OLDER, u"Última versão do canal %s: v%s (instalada: v%s, mais nova)." % (label, rel["version"], current_version)


def check_for_update(current_version, channel=CHANNEL_STABLE):
    """(ha_atualizacao, release) para o aviso de inicializacao. Silencioso: nunca levanta."""
    try:
        rel = fetch_release_for_channel(channel)
    except Exception:
        return False, None
    if not rel:
        return False, None
    new_k, cur_k = version_key(rel["version"]), version_key(current_version)
    return bool(new_k and cur_k and new_k > cur_k), rel


def verify_file_sha256(path, expected_hex):
    actual = calculate_file_sha256(path)
    if not actual or actual.lower() != (expected_hex or "").lower():
        raise SecurityValidationError(
            u"Hash SHA-256 divergente para %s (esperado %s, obtido %s)." % (os.path.basename(path), expected_hex, actual),
            title=u"Pacote Não Confiável",
            user_message=u"O pacote baixado não corresponde ao hash publicado na Release. A atualização foi bloqueada.",
            remediation=[u"Tente novamente mais tarde.", u"Se persistir, avise o responsável pelo plugin."])
    return actual


def check_network_connectivity(host=GITHUB_HOST, port=GITHUB_PORT, timeout=5.0):
    """
    Testa conectividade TCP básica com o servidor de destino dentro de um timeout estrito.
    """
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return True, None
    except socket.gaierror as e:
        return False, u"Falha na resolução de DNS para %s: %s" % (host, _err(e))
    except socket.timeout:
        return False, u"Tempo limite excedido (%ds) conectando a %s:%d" % (timeout, host, port)
    except Exception as e:
        return False, u"Erro de conexão com %s:%d: %s" % (host, port, _err(e))

def find_system_directories():
    """
    Localiza os diretórios oficiais do Add-In no ArcGIS Desktop 10.8 e o repositório local de dev.
    """
    # Documentos pode estar redirecionado (OneDrive / GPO): o ArcMap usa a pasta real
    addin_dir = os.path.join(
        _documents_dir(),
        u"ArcGIS\\AddIns\\Desktop10.8\\%s" % ADDIN_UUID
    )
    local_appdata = _env_path("LOCALAPPDATA") or os.path.join(_env_path("USERPROFILE"), u"AppData", u"Local")
    cache_dir = os.path.join(
        local_appdata,
        u"ESRI\\Desktop10.8\\AssemblyCache\\%s" % ADDIN_UUID_UPPER
    )

    curr_dir = _fs_text(os.path.dirname(os.path.abspath(__file__)))
    candidates = [
        os.path.abspath(os.path.join(curr_dir, u"..", u"..")),
        _env_path("GEE_PLUGIN_DEV_REPO")
    ]
    dev_repo = None
    for c in candidates:
        if os.path.exists(os.path.join(c, "arcgis_addin", "makeaddin.py")):
            dev_repo = c
            break

    return {
        "addin_dir": addin_dir,
        "cache_dir": cache_dir,
        "dev_repo": dev_repo
    }

# ==============================================================================
# VALIDAÇÕES PRÉVIAS (PRE-FLIGHT CHECKS)
# ==============================================================================

def validate_zip_archive(zip_path, target_dirs=None):
    """
    Executa verificação exaustiva de pré-instalação no arquivo .zip:
    1. Existência e tamanho mínimo.
    2. Integridade física dos blocos compactados (CRC-32 via testzip).
    3. Proteção contra Path Traversal / Zip Slip e nomes reservados do Windows.
    4. Cálculo de espaço em disco necessário (3x descompactado + 50MB) e verificação do volume.
    5. Teste empírico de permissões de escrita nos destinos.
    6. Existência dos componentes essenciais do plugin (config.xml, gee_gui.py, etc.).

    Retorna um dicionário com metadados do pacote validado.
    """
    log_info(u"Iniciando pré-validação do pacote ZIP: %s" % zip_path)

    # 1. Existência e tamanho
    if not os.path.exists(zip_path) or not os.path.isfile(zip_path):
        raise PreflightCheckError(
            u"O arquivo especificado não foi encontrado.",
            title=u"Arquivo Não Encontrado",
            user_message=u"O caminho do arquivo de atualização fornecido não existe ou é inválido.",
            remediation=[
                u"Verifique se o arquivo não foi movido ou excluído.",
                u"Selecione novamente o arquivo .zip ou .esriaddin."
            ]
        )

    file_size = os.path.getsize(zip_path)
    if file_size < 100:  # Menor que 100 bytes (um arquivo zip vazio tem aprox 22 bytes)
        raise CorruptPackageError(
            u"Arquivo de atualização truncado ou anormalmente pequeno (%d bytes)." % file_size,
            title=u"Arquivo Incompleto",
            user_message=u"O arquivo ZIP selecionado possui tamanho inferior ao esperado (%d bytes) e parece estar incompleto ou vazio." % file_size,
            remediation=[
                u"Baixe novamente o arquivo do repositório oficial.",
                u"Certifique-se de que o download tenha sido 100% concluído."
            ]
        )


    # 2. Teste de integridade CRC-32
    try:
        z = zipfile.ZipFile(zip_path, "r")
    except zipfile.BadZipfile as e:
        log_error(u"Arquivo não é um ZIP válido: %s" % _err(e))
        raise CorruptPackageError(
            u"O arquivo não possui cabeçalho ZIP válido.",
            title=u"Pacote Corrompido",
            user_message=u"O arquivo fornecido não é um arquivo ZIP válido ou seus cabeçalhos foram corrompidos.",
            remediation=[
                u"Faça o download novamente do pacote oficial.",
                u"Não renomeie extensões de arquivos arbitrariamente."
            ],
            technical_details=_err(e)
        )

    try:
        bad_entry = z.testzip()
        if bad_entry:
            log_error(u"Falha no teste de integridade CRC-32 no arquivo: %s" % bad_entry)
            raise CorruptPackageError(
                u"Falha de integridade CRC-32 no membro compactado: %s" % bad_entry,
                title=u"Arquivo ZIP Danificado (CRC)",
                user_message=u"O arquivo ZIP falhou na verificação de integridade interna (membro corrompido: %s)." % bad_entry,
                remediation=[
                    u"O pacote está danificado. Efetue um novo download.",
                    u"Verifique a estabilidade da sua conexão com a internet."
                ]
            )

        # 3. Proteção contra Path Traversal / Zip Slip e caracteres perigosos
        total_uncompressed_bytes = 0
        found_files = set()
        config_xml_entry = None

        for info in z.infolist():
            total_uncompressed_bytes += info.file_size
            filename = info.filename

            # Rejeitar caminhos absolutos (iniciados com / ou \ ou com letra de unidade C:)
            if filename.startswith("/") or filename.startswith("\\"):
                raise SecurityValidationError(
                    u"Violação de segurança: caminho absoluto detectado no ZIP (%s)." % filename,
                    title=u"Risco de Segurança Detectado (Zip Slip)",
                    user_message=u"O arquivo ZIP foi rejeitado porque contém caminhos absolutos que violam a segurança do sistema.",
                    remediation=[u"Utilize apenas arquivos oficiais do ArcMagery."]
                )
            if len(filename) >= 2 and filename[1] == ":":
                raise SecurityValidationError(
                    u"Violação de segurança: unidade absoluta detectada no ZIP (%s)." % filename,
                    title=u"Risco de Segurança Detectado (Zip Slip)",
                    user_message=u"O arquivo ZIP foi rejeitado por conter letras de unidade absolutas.",
                    remediation=[u"Utilize apenas arquivos oficiais do repositório."]
                )

            # Normalização e verificação de escape '..'
            normalized_parts = os.path.normpath(filename).replace("\\", "/").split("/")
            if ".." in normalized_parts:
                raise SecurityValidationError(
                    u"Tentativa de Path Traversal ('..') detectada no arquivo: %s" % filename,
                    title=u"Risco de Segurança Detectado (Zip Slip)",
                    user_message=u"O arquivo ZIP contém referências a diretórios superiores ('..') e foi bloqueado por segurança.",
                    remediation=[u"Utilize apenas distribuições oficiais publicadas pelos desenvolvedores."]
                )

            # Rejeição de dispositivos reservados do Windows
            for part in normalized_parts:
                root_part = part.split(".")[0].upper()
                if root_part in WINDOWS_RESERVED_NAMES:
                    raise SecurityValidationError(
                        u"Nome de dispositivo reservado detectado no ZIP: %s" % part,
                        title=u"Nome de Arquivo Proibido",
                        user_message=u"O arquivo ZIP contém nomes reservados do sistema Windows (%s) e foi rejeitado." % part,
                        remediation=[u"Utilize o arquivo oficial do repositório."]
                    )

            base_name = os.path.basename(filename)
            if base_name:
                found_files.add(base_name)
            if base_name.lower() == "config.xml":
                config_xml_entry = filename

        # 4. Verificação de componentes essenciais
        missing = [c for c in ESSENTIAL_COMPONENTS if c not in found_files]
        if missing:
            raise MissingComponentsError(
                u"Componentes essenciais ausentes no ZIP: %s" % ", ".join(missing),
                title=u"Estrutura do Plugin Incompleta",
                user_message=u"O arquivo ZIP não contém os componentes essenciais do plugin: %s." % ", ".join(missing),
                remediation=[
                    u"Verifique se você selecionou o arquivo correto do ArcMagery.",
                    u"Se você baixou o código-fonte compactado, certifique-se de baixar o ZIP completo do repositório."
                ]
            )

        # Extrair e analisar versão proposta no config.xml
        proposed_version = "Desconhecida"
        if config_xml_entry:
            try:
                xml_data = z.read(config_xml_entry)
                root_elem = ET.fromstring(xml_data)
                # O config.xml usa namespace padrao (xmlns=".../AddIns"): find(".//Version")
                # nunca casava e a versao ficava "Desconhecida" (anulando o bloqueio de downgrade)
                ver_node = next((el for el in root_elem.iter()
                                 if el.tag == "Version" or el.tag.endswith("}Version")), None)
                if ver_node is not None and ver_node.text:
                    proposed_version = ver_node.text.strip()
            except Exception as e_xml:
                log_warning(u"Não foi possível extrair a versão do config.xml: %s" % _err(e_xml))

    finally:
        z.close()

    # 5. Cálculo e validação de espaço livre em disco
    # Fórmula: 3x o tamanho descompactado (staging + backup + instalação) + 50 MB de margem
    required_space = (total_uncompressed_bytes * 3) + (50 * 1024 * 1024)
    temp_dir = _temp_dir()
    free_temp = get_free_disk_space_bytes(temp_dir)
    log_info(u"Espaço livre em TEMP (%s): %.2f MB | Necessário: %.2f MB" % (
        temp_dir, free_temp / (1024.0 * 1024.0), required_space / (1024.0 * 1024.0)
    ))

    if free_temp < required_space:
        raise DiskSpaceError(
            u"Espaço em disco insuficiente em TEMP (%d < %d bytes)." % (free_temp, required_space),
            title=u"Disco Quase Cheio",
            user_message=(
                u"Espaço livre insuficiente na unidade temporária.\n"
                u"Disponível: %.1f MB | Necessário com margem de segurança: %.1f MB."
            ) % (free_temp / (1024.0 * 1024.0), required_space / (1024.0 * 1024.0)),
            remediation=[
                u"Libere espaço na unidade do sistema (C:) limpando a pasta temporária.",
                u"Esvazie a lixeira do Windows e execute a Limpeza de Disco."
            ]
        )

    # 6. Teste de permissão de escrita nos diretórios de destino
    if target_dirs is None:
        target_dirs = find_system_directories()

    for key, path in target_dirs.items():
        if path and key in ("addin_dir", "cache_dir"):
            parent_p = os.path.dirname(path)
            ok, err = test_write_permission(parent_p)
            if not ok:
                raise PermissionCheckError(
                    u"Permissão negada ao testar escrita em: %s (%s)" % (parent_p, err),
                    title=u"Permissão Negada",
                    user_message=u"O ArcGIS ou o Windows não concedeu permissão de escrita para atualizar a pasta:\n%s" % parent_p,
                    remediation=[
                        u"Execute o ArcMap ou o instalador com privilégios adequados.",
                        u"Verifique se o seu usuário possui controle total sobre a pasta Documentos/AppData."
                    ],
                    technical_details=err
                )

    log_info(u"Validação prévia do ZIP concluída com sucesso! Versão do pacote: %s" % proposed_version)
    return {
        "status": "valid",
        "zip_path": zip_path,
        "file_size": file_size,
        "uncompressed_bytes": total_uncompressed_bytes,
        "proposed_version": proposed_version,
        "required_space": required_space
    }

def validate_git_repository(repo_path, remote_branch="main"):
    """
    Executa verificações prévias completas em um repositório Git local:
    1. Presença do executável git no PATH do Windows.
    2. Conectividade de rede com o repositório remoto.
    3. Status da working tree: rejeita repositórios com alterações locais não salvas (dirty working tree).
    4. Verificação de stashes ou commits locais não sincronizados que possam causar conflito de merge.
    5. Verificação de possibilidade de avanço rápido (fast-forward).
    """
    log_info(u"Iniciando pré-validação Git no repositório: %s" % _fs_text(repo_path))
    repo_path = _cmdline_path(repo_path)   # Py2: cwd do Popen precisa ser bytes ANSI

    # 1. Verificar executável git
    try:
        proc = subprocess.Popen(
            ["git", "--version"],
            cwd=repo_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        out, _ = proc.communicate()
        if proc.returncode != 0:
            raise Exception("git returncode != 0")
        git_ver = out.decode("utf-8", "replace").strip()
        log_info(u"Git detectado: %s" % git_ver)
    except Exception as e_git:
        raise GitRepositoryError(
            u"Executável 'git' não encontrado no sistema: %s" % _err(e_git),
            title=u"Git Não Encontrado",
            user_message=u"O comando 'git' não está instalado ou não foi adicionado ao PATH do Windows.",
            remediation=[
                u"Instale o Git for Windows (https://git-scm.com).",
                u"Ou utilize o 'Método 2: Atualizar via Arquivo ZIP' para atualizar offline."
            ]
        )

    # 2. Conectividade com o remote
    net_ok, net_err = check_network_connectivity(GITHUB_HOST, GITHUB_PORT, timeout=5.0)
    if not net_ok:
        raise NetworkError(
            u"Sem conectividade com o GitHub: %s" % net_err,
            title=u"Sem Conexão com a Internet",
            user_message=u"Não foi possível conectar ao servidor do GitHub para verificar atualizações.",
            remediation=[
                u"Verifique sua conexão com a internet ou Wi-Fi.",
                u"Se você estiver em rede corporativa, verifique configurações de Proxy ou VPN."
            ],
            technical_details=net_err
        )

    # 3. Status da working tree (Dirty working tree check)
    proc_status = subprocess.Popen(
        ["git", "status", "--porcelain"],
        cwd=repo_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    out_status, err_status = proc_status.communicate()
    out_status = out_status.decode("utf-8", "replace").strip()

    if out_status:
        # Filtrar alterações críticas (modificações em arquivos rastreados)
        dirty_lines = [line for line in out_status.splitlines() if not line.startswith("??")]
        if dirty_lines:
            log_warning(u"Repositório local contém arquivos modificados: %s" % dirty_lines)
            raise GitRepositoryError(
                u"Working tree do Git está suja (modificações locais não salvas).",
                title=u"Modificações Locais Não Salvas",
                user_message=(
                    u"O repositório local contém alterações de código que ainda não foram salvas.\n\n"
                    u"Para proteger seu trabalho contra perda de dados ou conflitos de merge, "
                    u"a atualização automática foi interrompida."
                ),
                remediation=[
                    u"Faça 'git commit' de suas alterações antes de atualizar.",
                    u"Ou execute 'git stash' no terminal para arquivar temporariamente as mudanças.",
                    u"Ou execute 'git restore .' se quiser descartar modificações locais."
                ],
                technical_details="\n".join(dirty_lines)
            )

    # 4. Fetch e verificação de divergência (Fast-forward check)
    log_info(u"Executando git fetch para verificar branch '%s'..." % remote_branch)
    proc_fetch = subprocess.Popen(
        ["git", "fetch", "origin", remote_branch, "--quiet"],
        cwd=repo_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    _, err_fetch = proc_fetch.communicate()
    if proc_fetch.returncode != 0:
        err_msg = err_fetch.decode("utf-8", "replace").strip()
        log_error(u"git fetch falhou: %s" % err_msg)
        raise NetworkError(
            u"Falha ao sincronizar referências com 'git fetch origin %s': %s" % (remote_branch, err_msg),
            title=u"Falha ao Acessar Repositório Remoto",
            user_message=u"O Git não conseguiu buscar as alterações mais recentes do repositório oficial.",
            remediation=[
                u"Verifique sua conexão de rede.",
                u"Verifique se o repositório remoto no GitHub está acessível."
            ],
            technical_details=err_msg
        )

    # Verificar se o branch local está adiantado em relação ao remote (conflitos em potencial)
    proc_ahead = subprocess.Popen(
        ["git", "rev-list", "--count", "origin/%s..HEAD" % remote_branch],
        cwd=repo_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    out_ahead, _ = proc_ahead.communicate()
    ahead_count = int(out_ahead.decode("utf-8", "replace").strip() or "0")

    if ahead_count > 0:
        log_warning(u"Repositório local possui %d commit(s) à frente do remote." % ahead_count)
        raise GitRepositoryError(
            u"O branch local possui commits próprios não enviados ao remote (%d commits à frente)." % ahead_count,
            title=u"Repositório Local Divergiu do Oficial",
            user_message=(
                u"Seu repositório local possui %d commit(s) que não existem no GitHub oficial.\n"
                u"A atualização automática requer avanço rápido (fast-forward) para garantir consistência."
            ) % ahead_count,
            remediation=[
                u"Envie seus commits para um branch próprio (git push origin seu-branch).",
                u"Ou faça um rebase manual das suas alterações sobre origin/main."
            ]
        )

    # Obter hash do commit atual para possibilitar rollback
    proc_head = subprocess.Popen(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    out_head, _ = proc_head.communicate()
    current_head = out_head.decode("utf-8", "replace").strip()

    log_info(u"Validação Git aprovada! Commit HEAD atual: %s" % current_head)
    return {
        "status": "valid",
        "current_head": current_head,
        "remote_branch": remote_branch,
        "repo_path": repo_path
    }

# ==============================================================================
# DOWNLOAD RESILIENTE DO GITHUB
# ==============================================================================

def download_github_archive(target_path, progress_callback=None, url=None):
    """
    Realiza o download em streaming de um pacote .zip do GitHub (Release ou branch)
    com validação de tamanho, timeout configurado e relatório de progresso.
    """
    url = url or GITHUB_ZIP_URL
    log_info(u"Iniciando download do pacote GitHub a partir de: %s" % url)

    # 1. Diagnóstico de rede (apenas registro: em redes com proxy explícito a conexão TCP
    #    direta falha mesmo quando o download via urllib, que respeita o proxy, funciona)
    net_ok, net_err = check_network_connectivity(GITHUB_HOST, GITHUB_PORT, timeout=5.0)
    if not net_ok:
        log_warning(u"Conexão TCP direta com %s indisponível (%s); tentando mesmo assim (proxy?)." % (GITHUB_HOST, net_err))

    # 2. Download em arquivo temporário com sufixo .part
    part_path = target_path + ".part"
    if os.path.exists(part_path):
        try:
            os.remove(part_path)
        except Exception:
            pass

    try:
        # Suporte dual Python 2.7 / Python 3
        if sys.version_info[0] < 3:
            import urllib2
            req = urllib2.Request(
                url,
                headers={"User-Agent": UPDATER_USER_AGENT}
            )
            response = urllib2.urlopen(req, timeout=20)
        else:
            import urllib.request
            req = urllib.request.Request(
                url,
                headers={"User-Agent": UPDATER_USER_AGENT}
            )
            response = urllib.request.urlopen(req, timeout=20)

        meta = response.info()
        content_length = meta.get("Content-Length") if hasattr(meta, "get") else meta.getheader("Content-Length")
        total_size = int(content_length) if content_length else None

        downloaded = 0
        chunk_size = 65536  # 64 KB

        with open(part_path, "wb") as f_out:
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                f_out.write(chunk)
                downloaded += len(chunk)
                if progress_callback:
                    try:
                        progress_callback(downloaded, total_size)
                    except Exception:
                        pass

        response.close()

        if total_size and downloaded != total_size:
            raise CorruptPackageError(
                u"Download incompleto: %d de %d bytes." % (downloaded, total_size),
                title=u"Download Incompleto",
                user_message=u"A transferência do pacote foi interrompida antes do fim.",
                remediation=[u"Tente baixar novamente a atualização."]
            )

        # Validação pós-download: tamanho e assinatura ZIP
        if downloaded < 10240:
            raise CorruptPackageError(
                u"Tamanho de download insuficiente (%d bytes)." % downloaded,
                title=u"Download Incompleto",
                user_message=u"O arquivo baixado do GitHub parece truncado ou incompleto.",
                remediation=[u"Tente baixar novamente a atualização."]
            )

        # Substituição atômica do arquivo temporário
        if os.path.exists(target_path):
            try:
                os.remove(target_path)
            except Exception:
                pass
        os.rename(part_path, target_path)

        log_info(u"Download concluído com sucesso: %s (%d bytes)" % (target_path, downloaded))
        return target_path

    except Exception as e:
        if os.path.exists(part_path):
            try:
                os.remove(part_path)
            except Exception:
                pass
        log_error(u"Erro durante o download do GitHub: %s" % _err(e))
        if isinstance(e, UpdaterError):
            raise
        raise NetworkError(
            u"Falha durante transferência de dados do GitHub: %s" % _err(e),
            title=u"Erro ao Baixar Atualização",
            user_message=u"Ocorreu um erro ao baixar os arquivos de atualização do GitHub.\nA transferência foi interrompida.",
            remediation=[
                u"Verifique a estabilidade da sua internet.",
                u"Tente novamente em alguns instantes."
            ],
            technical_details=traceback.format_exc()
        )

# ==============================================================================
# MOTOR DE BACKUP E SNAPSHOT DE SEGURANÇA
# ==============================================================================

SNAPSHOT_REQUIRED_FILES = (u"GEE_Image_Selector.esriaddin",
                           os.path.join(u"AssemblyCache", u"gee_gui.py"),
                           os.path.join(u"AssemblyCache", u"config.xml"))


def snapshot_missing_files(snapshot_dir):
    """Arquivos obrigatorios para restaurar um snapshot que faltam nele (lista vazia = completo)."""
    return [f for f in SNAPSHOT_REQUIRED_FILES if not os.path.isfile(os.path.join(snapshot_dir, f))]


def discard_snapshot(backup_meta):
    """Apaga o snapshot criado por um fluxo que falhou ANTES de despachar o executor: senao ele
    (copia da versao ATUAL) viraria o alvo do botao 'Voltar para a Versao Anterior'."""
    d = (backup_meta or {}).get("snapshot_dir")
    if d and os.path.isdir(d):
        try:
            shutil.rmtree(d)
            log_info(u"Snapshot descartado (fluxo interrompido antes da aplicação): %s" % d)
        except Exception as e_rm:
            log_warning(u"Não foi possível descartar o snapshot %s: %s" % (d, _err(e_rm)))


def create_snapshot_backup(current_version="2.4.3-nightly.20261006", backups_root=None, custom_sys_dirs=None):
    """
    Cria um backup completo e atômico do estado operacional atual do plugin.
    Copia o .esriaddin instalado e todo o AssemblyCache para uma pasta versionada:
    %LOCALAPPDATA%\\CGMA_ArcGEE\\backups\\backup_<timestamp>

    Salva um arquivo manifest.json para auditoria e controle de integridade.
    Retorna o dicionário com metadados do snapshot.
    """
    sys_dirs = custom_sys_dirs if custom_sys_dirs else find_system_directories()
    addin_dir = _fs_text(sys_dirs.get("addin_dir", ""))
    cache_dir = _fs_text(sys_dirs.get("cache_dir", ""))

    timestamp_str = time.strftime("%Y%m%d_%H%M%S")
    if backups_root is None:
        backups_root = get_backups_dir()
    backups_root = _fs_text(backups_root)
    snapshot_dir = os.path.join(backups_root, u"backup_%s_%s" % (current_version.replace(".", "_"), timestamp_str))

    log_info(u"Criando snapshot de backup em: %s" % snapshot_dir)
    if not os.path.exists(snapshot_dir):
        try:
            os.makedirs(snapshot_dir)
        except Exception as e:
            raise PermissionCheckError(
                u"Falha ao criar pasta de backup: %s" % _err(e),
                title=u"Erro de Backup",
                user_message=u"Não foi possível criar o diretório de segurança para backup antes da atualização.",
                technical_details=_err(e)
            )

    backup_manifest = {
        "timestamp": timestamp_str,
        "version": current_version,
        "snapshot_dir": snapshot_dir,
        "files": {}
    }

    # 1. Backup do arquivo .esriaddin
    problems = []
    live_addin = os.path.join(addin_dir, u"GEE_Image_Selector.esriaddin")
    if os.path.exists(live_addin):
        dest_addin = os.path.join(snapshot_dir, u"GEE_Image_Selector.esriaddin")
        try:
            shutil.copy2(live_addin, dest_addin)
            backup_manifest["files"]["esriaddin"] = {
                "source": live_addin,
                "backup": dest_addin,
                "sha256": calculate_file_sha256(dest_addin)
            }
        except Exception as e_cp:
            log_warning(u"Aviso: não foi possível copiar .esriaddin para o backup: %s" % _err(e_cp))
            problems.append(u"cópia do .esriaddin falhou (%s)" % _err(e_cp))
    else:
        problems.append(u".esriaddin instalado não encontrado em %s" % addin_dir)

    # 2. Backup do AssemblyCache
    if os.path.exists(cache_dir):
        dest_cache = os.path.join(snapshot_dir, u"AssemblyCache")
        try:
            shutil.copytree(cache_dir, dest_cache)
            backup_manifest["files"]["cache_dir"] = {
                "source": cache_dir,
                "backup": dest_cache
            }
        except Exception as e_cache:
            log_warning(u"Aviso: cópia do AssemblyCache para backup parcial: %s" % _err(e_cache))
            problems.append(u"cópia do AssemblyCache falhou (%s)" % _err(e_cache))
    else:
        problems.append(u"AssemblyCache não encontrado em %s" % cache_dir)

    # Sem snapshot COMPLETO nao ha como reverter: aborta antes de modificar qualquer arquivo
    missing = snapshot_missing_files(snapshot_dir)
    if missing or problems:
        details = u"; ".join(problems + [u"ausente no snapshot: %s" % m for m in missing])
        log_error(u"Snapshot de backup incompleto (%s): %s" % (snapshot_dir, details))
        try:
            shutil.rmtree(snapshot_dir)
        except Exception:
            pass
        raise PreflightCheckError(
            u"Snapshot de backup incompleto: %s" % details,
            title=u"Backup Incompleto",
            user_message=u"Não foi possível salvar uma cópia completa da versão instalada, então a "
                         u"atualização foi cancelada antes de alterar qualquer arquivo.",
            remediation=[u"Tente novamente em instantes (veja o log de atualização).",
                         u"Se o plugin não estiver instalado nesta conta, instale-o pelo install.bat."],
            technical_details=details)

    # 3. Gravar manifest.json
    try:
        manifest_file = os.path.join(snapshot_dir, "backup_manifest.json")
        import json
        with open(manifest_file, "w") as f_man:
            json.dump(backup_manifest, f_man, indent=2)
    except Exception as e_man:
        log_warning(u"Não foi possível salvar manifest.json: %s" % _err(e_man))

    # 4. Política de retenção: manter no máximo os últimos 5 backups
    try:
        all_backups = []
        for name in os.listdir(backups_root):
            p = os.path.join(backups_root, name)
            if os.path.isdir(p) and name.startswith("backup_"):
                all_backups.append((os.path.getmtime(p), p))
        all_backups.sort(key=lambda x: x[0], reverse=True)
        # Remover os excedentes (além de 5)
        for _, old_p in all_backups[5:]:
            try:
                shutil.rmtree(old_p)
                log_info(u"Removido backup antigo da política de retenção: %s" % old_p)
            except Exception:
                pass
    except Exception as e_ret:
        log_warning(u"Erro na retenção de backups: %s" % _err(e_ret))

    log_info(u"Snapshot de segurança gerado com sucesso.")
    return backup_manifest

# ==============================================================================
# MOTOR DE STAGING E MONTAGEM DO PACOTE (.ESRIADDIN)
# ==============================================================================

def prepare_staging_environment(zip_path):
    """
    Extrai o arquivo ZIP validado em uma pasta de staging isolada,
    organiza as pastas e compila um pacote .esriaddin pronto para implantação.
    Garante que arquivos corrompidos ou maliciosos nunca toquem o diretório do ArcMap.
    """
    log_info(u"Preparando ambiente de staging isolado...")
    staging_base = _temp_dir()
    ts = int(time.time() * 1000) % 1000000
    staging_dir = os.path.join(staging_base, u"arcgee_stage_%d" % ts)

    if os.path.exists(staging_dir):
        try:
            shutil.rmtree(staging_dir)
        except Exception:
            pass
    try:
        os.makedirs(staging_dir)
    except Exception as e:
        raise PermissionCheckError(
            u"Não foi possível criar a pasta de staging: %s" % _err(e),
            title=u"Erro de Sistema",
            user_message=u"Falha ao criar diretório temporário isolado para a atualização.",
            technical_details=_err(e)
        )

    # 1. Extração segura com sanitização de caminhos (Prevenção Zip Slip)
    with zipfile.ZipFile(zip_path, "r") as z:
        for member in z.infolist():
            filename = member.filename.replace("\\", "/")
            if sys.version_info[0] < 3 and isinstance(filename, bytes):
                filename = filename.decode("cp437", "replace")   # staging_dir e unicode
            # Pular diretórios explícitos vazios
            if filename.endswith("/"):
                continue

            # Sanitização estrita
            norm_name = os.path.normpath(filename).replace("\\", "/")
            parts = [p for p in norm_name.split("/") if p and p != "." and p != ".."]
            target_path = os.path.join(staging_dir, *parts)

            # Barreira de segurança: garantir que o caminho final resida estritamente dentro do staging
            real_target = os.path.abspath(target_path)
            real_staging = os.path.abspath(staging_dir)
            if not real_target.startswith(real_staging):
                raise SecurityValidationError(
                    u"Tentativa de escape de diretório na extração: %s" % filename,
                    title=u"Erro Crítico de Segurança",
                    user_message=u"O arquivo ZIP tentou gravar dados fora da pasta de staging."
                )

            target_dir = os.path.dirname(real_target)
            if not os.path.exists(target_dir):
                os.makedirs(target_dir)

            with z.open(member) as src_f, open(real_target, "wb") as dst_f:
                shutil.copyfileobj(src_f, dst_f)

    # 2. Localização dos componentes vitais
    config_file = None
    install_dir = None
    backend_dir = None
    images_dir = None

    for root, dirs, files in os.walk(staging_dir):
        if "config.xml" in files and not config_file:
            config_file = os.path.join(root, "config.xml")
        if "gee_gui.py" in files and not install_dir:
            install_dir = root
        if "gee_core.py" in files and not backend_dir:
            backend_dir = root
        if "icon.png" in files and not images_dir and os.path.basename(root).lower() == "images":
            images_dir = root

    if not config_file or not install_dir:
        raise MissingComponentsError(
            u"config.xml ou pasta Install não puderam ser localizados no pacote extraído.",
            title=u"Estrutura Incorreta",
            user_message=u"A estrutura do pacote de atualização é incompatível com o padrão ESRI Add-In.",
            remediation=[u"Utilize a versão oficial fornecida pelo repositório."]
        )

    # 3. Sincronização obrigatória da subpasta backend dentro de Install
    inst_backend = os.path.join(install_dir, "backend")
    if not os.path.exists(inst_backend):
        try:
            os.makedirs(inst_backend)
        except Exception:
            pass

    if backend_dir and os.path.abspath(backend_dir) != os.path.abspath(inst_backend):
        for f in os.listdir(backend_dir):
            if f.endswith(".py") or f.endswith(".json"):
                shutil.copy2(os.path.join(backend_dir, f), os.path.join(inst_backend, f))

    # 4. Construção do novo pacote .esriaddin pronto para implantação
    staged_addin = os.path.join(staging_dir, "GEE_Image_Selector.esriaddin")
    with zipfile.ZipFile(staged_addin, "w", zipfile.ZIP_DEFLATED) as z_out:
        z_out.write(config_file, "config.xml")
        # Adicionar arquivos da pasta Install
        for root, dirs, files in os.walk(install_dir):
            for f in files:
                if f.endswith(".pyc") or f.endswith(".pyo"):
                    continue
                full_p = os.path.join(root, f)
                rel_p = "Install/" + os.path.relpath(full_p, install_dir).replace("\\", "/")
                z_out.write(full_p, rel_p)
        # Adicionar pasta Images se existir
        if images_dir and os.path.exists(images_dir):
            for root, dirs, files in os.walk(images_dir):
                for f in files:
                    full_p = os.path.join(root, f)
                    rel_p = "Images/" + os.path.relpath(full_p, images_dir).replace("\\", "/")
                    z_out.write(full_p, rel_p)

    # 5. Verificação pós-construção do pacote gerado
    with zipfile.ZipFile(staged_addin, "r") as z_check:
        if z_check.testzip():
            raise CorruptPackageError(u"O pacote .esriaddin compilado falhou na verificação de integridade.")

    # 6. Plugin do QGIS (QMagery) do mesmo pacote: so para sincronizar o repositorio de desenvolvimento
    qgis_plugin_dir = u""
    for root, dirs, files in os.walk(staging_dir):
        if os.path.basename(root) == "qmagery" and "metadata.txt" in files and "plugin.py" in files:
            qgis_plugin_dir = os.path.dirname(root)
            break

    log_info(u"Ambiente de staging pronto e verificado: %s" % staged_addin)
    return {
        "staging_dir": staging_dir,
        "config_file": config_file,
        "install_dir": install_dir,
        "inst_backend": inst_backend,
        "staged_addin": staged_addin,
        "qgis_plugin_dir": qgis_plugin_dir,
    }

# ==============================================================================
# SCRIPT DESACOPLADO E TRANSAÇÃO COM ROLLBACK AUTOMÁTICO
# ==============================================================================

def _bat_text(text):
    """Texto no tipo do template do .bat: unicode (o arquivo e gravado no codepage ANSI por _bat_bytes)."""
    if sys.version_info[0] < 3 and isinstance(text, bytes):
        return text.decode("utf-8", "replace")
    return text


def _bat_bytes(text):
    """Conteudo final do .bat. O executor roda DESANEXADO (sem console): o cmd le o arquivo no codepage
    ANSI e 'chcp 65001' nao tem efeito, entao o arquivo e gravado em ANSI (mbcs) com CRLF."""
    text = _bat_text(text).replace(u"\r\n", u"\n").replace(u"\n", u"\r\n")
    try:
        return text.encode("mbcs", "replace")
    except LookupError:   # fora do Windows (testes)
        return text.encode("cp1252", "replace")


def _ansi_roundtrip(text):
    """True se o texto sobrevive ao codepage ANSI (o que o cmd do executor consegue ler)."""
    try:
        return text.encode("mbcs", "replace").decode("mbcs") == text
    except LookupError:
        try:
            return text.encode("cp1252", "replace").decode("cp1252") == text
        except Exception:
            return False
    except Exception:
        return False


def _short_path(path):
    """Nome 8.3 (GetShortPathNameW). Se o caminho ainda nao existe, encurta o maior ancestral existente
    e acrescenta o resto. Devolve o proprio caminho quando nao for possivel."""
    try:
        import ctypes
        head, tail = path, []
        while head and not os.path.exists(head):
            new_head, t = os.path.split(head)
            if not t or new_head == head:
                break
            tail.insert(0, t)
            head = new_head
        if not head or not os.path.exists(head):
            return path
        buf = ctypes.create_unicode_buffer(1024)
        n = ctypes.windll.kernel32.GetShortPathNameW(head, buf, 1024)
        if not n or n > 1024 or not buf.value:
            return path
        return os.path.join(buf.value, *tail) if tail else buf.value
    except Exception:
        return path


def bat_path_text(path):
    """Caminho seguro para o .bat: o proprio caminho (unicode) se cabe no codepage ANSI; senao o nome
    8.3. '%' vira '%%' (senao o cmd o expandiria como variavel)."""
    path = _fs_text(path or u"")
    if path and not _ansi_roundtrip(path):
        short = _short_path(path)
        if _ansi_roundtrip(short):
            path = short
        else:
            log_warning(u"Caminho fora do codepage ANSI e sem nome 8.3; o executor pode não encontrá-lo: %s" % path)
    return path.replace(u"%", u"%%")


def _cmdline_path(path):
    """Caminho para a linha de comando do Popen: no Python 2 o subprocess usa CreateProcessA, entao
    o caminho vai em bytes ANSI (bat_path_text garante que cabe no codepage)."""
    path = _fs_text(path)
    if sys.version_info[0] < 3:
        if not _ansi_roundtrip(path):
            path = _short_path(path)
        try:
            return path.encode("mbcs", "replace")
        except LookupError:
            return path.encode("cp1252", "replace")
    return path


BAT_UNSAFE_PATH_CHARS = u"&^%!()"


def _bat_safe_dir(path):
    """O proprio diretorio (ou o nome 8.3) se o cmd consegue EXECUTAR um .bat dentro dele; senao None.
    O cmd reabre o .bat pelo caminho a cada linha e se perde com '&' (perfil 'P&D'), '^', '%', '!' ou
    parenteses no caminho do proprio arquivo, mesmo entre aspas; e precisa do caminho no codepage ANSI."""
    p = _fs_text(path or u"")
    if p and not _ansi_roundtrip(p):
        p = _short_path(p)
    if not p or not _ansi_roundtrip(p) or any(c in p for c in BAT_UNSAFE_PATH_CHARS):
        return None
    return p


def runner_dir():
    """Pasta onde o .bat do executor e gravado: a TEMP do usuario; se o caminho dela quebra o cmd,
    %SystemRoot%\\Temp (os usuarios criam arquivos, mas nao listam os dos outros) e, por fim,
    %ProgramData%\\ArcMagery\\tmp."""
    candidates = (_temp_dir(),
                  os.path.join(_env_path("SystemRoot", u"C:\\Windows"), u"Temp"),
                  os.path.join(_env_path("ProgramData", u"C:\\ProgramData"), u"ArcMagery", u"tmp"))
    for cand in candidates:
        safe = _bat_safe_dir(cand)
        if safe and test_write_permission(safe)[0]:
            return safe
    return _temp_dir()


def cmd_run_bat_line(bat_path):
    """Linha de comando que executa o .bat. 'cmd /s /c ""caminho""': sem /s, um '&' ou '(' no caminho
    (ex.: perfil 'P&D') faz o cmd descartar as aspas e quebrar o caminho em dois comandos."""
    path = _cmdline_path(bat_path)
    if sys.version_info[0] < 3:
        return b'cmd.exe /d /s /c ""' + path + b'""'
    return u'cmd.exe /d /s /c ""%s""' % path


def ps_message_expr(text):
    """Expressao PowerShell 100% ASCII para o texto (MessageBox do executor): trechos entre aspas
    simples + [char]N para quebras de linha e acentos. Nao depende do codepage em que o cmd le o .bat
    e aceita tanto '\\n' quanto o antigo '`n' como quebra de linha."""
    text = _bat_text(text or u"").replace(u"`n", u"\n").replace(u"\r\n", u"\n")
    parts, chunk = [], []
    for ch in text:
        code = ord(ch)
        if ch == u'"':
            continue   # a mensagem fica dentro de -Command "..." do cmd
        if 32 <= code < 127:
            chunk.append(u"''" if ch == u"'" else (u"%%" if ch == u"%" else ch))
            continue
        if chunk:
            parts.append(u"'%s'" % u"".join(chunk))
            chunk = []
        if ch == u"\n":
            parts.append(u"[char]10")
        elif code >= 32:
            parts.append(u"[char]0x%04X" % code)
    if chunk:
        parts.append(u"'%s'" % u"".join(chunk))
    return u"(%s)" % (u" + ".join(parts) if parts else u"''")


def _gui_process_to_stop():
    """(pid, imagem) do processo da propria interface, que o executor espera fechar (e finaliza se
    preciso). So o pythonw.exe da GUI: nunca outros pythonw (scripts de outros usuarios, QGIS...)."""
    exe = os.path.basename(sys.executable or "").lower()
    if exe == "pythonw.exe":
        return str(os.getpid()), exe
    return u"", u"pythonw.exe"


_BAT_TEMPLATE = r"""@echo off
title Atualizador ArcMagery

set "LOG_FILE={log_file}"
set "ADDIN_DIR={addin_dir}"
set "CACHE_DIR={cache_dir}"
set "BACKUP_DIR={snapshot_dir}"
set "STAGING_DIR={staging_dir}"
set "STAGED_ADDIN={staged_addin}"
set "INSTALL_DIR={install_dir}"
set "CONFIG_FILE={config_file}"
set "INST_BACKEND={inst_backend}"
set "DEV_REPO={dev_repo}"
set "QGIS_PLUGIN={qgis_plugin}"
set "GUI_PID={gui_pid}"
set "GUI_NAME={gui_name}"

echo ====================================================================== >> "%LOG_FILE%"
echo [%DATE% %TIME%] [TRANSACAO DE ATUALIZACAO INICIADA] >> "%LOG_FILE%"
echo ====================================================================== >> "%LOG_FILE%"

:: 1. Aguardar o encerramento da interface (somente o processo da propria GUI, nunca outros pythonw)
echo [%DATE% %TIME%] Aguardando o encerramento da interface (PID %GUI_PID%)... >> "%LOG_FILE%"
ping 127.0.0.1 -n 3 >nul
if not defined GUI_PID goto :GUI_CLOSED
:: Sem console (executor desanexado) tasklist nao imprime nada e o pipe tasklist/find trava: a espera e
:: o encerramento usam o PowerShell, filtrando pelo PID E pelo nome do executavel da GUI.
powershell -NoProfile -Command "$p = Get-Process -Id %GUI_PID% -ErrorAction SilentlyContinue; if ($p -and ($p.ProcessName -eq '%GUI_NAME%') -and -not $p.WaitForExit(15000)) {{ Stop-Process -Id %GUI_PID% -Force; 'KILLED' }}" >> "%LOG_FILE%" 2>&1
ping 127.0.0.1 -n 2 >nul
:GUI_CLOSED

:: 2. Validacao previa de integridade do backup (nada foi modificado ate aqui)
if not exist "%BACKUP_DIR%\GEE_Image_Selector.esriaddin" (
    echo [%DATE% %TIME%] [ERRO CRITICO] Backup sem GEE_Image_Selector.esriaddin: "%BACKUP_DIR%" >> "%LOG_FILE%"
    goto :ABORT_NO_BACKUP
)
if not exist "%BACKUP_DIR%\AssemblyCache\gee_gui.py" (
    echo [%DATE% %TIME%] [ERRO CRITICO] Backup sem AssemblyCache\gee_gui.py: "%BACKUP_DIR%" >> "%LOG_FILE%"
    goto :ABORT_NO_BACKUP
)
if not exist "%BACKUP_DIR%\AssemblyCache\config.xml" (
    echo [%DATE% %TIME%] [ERRO CRITICO] Backup sem AssemblyCache\config.xml: "%BACKUP_DIR%" >> "%LOG_FILE%"
    goto :ABORT_NO_BACKUP
)

echo [%DATE% %TIME%] Backup de seguranca confirmado em: "%BACKUP_DIR%" >> "%LOG_FILE%"

:: 3. ETAPA 1 DA TRANSACAO: Atualizar arquivo .esriaddin
if not exist "%ADDIN_DIR%" mkdir "%ADDIN_DIR%" >> "%LOG_FILE%" 2>&1
echo [%DATE% %TIME%] Copiando pacote .esriaddin para "%ADDIN_DIR%"... >> "%LOG_FILE%"
copy /Y "%STAGED_ADDIN%" "%ADDIN_DIR%\GEE_Image_Selector.esriaddin" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    echo [%DATE% %TIME%] [FALHA] Erro ao copiar .esriaddin. Codigo de saida: %errorlevel% >> "%LOG_FILE%"
    goto :ROLLBACK
)

:: 4. ETAPA 2 DA TRANSACAO: Atualizar arquivos do AssemblyCache
if not exist "%CACHE_DIR%" mkdir "%CACHE_DIR%" >> "%LOG_FILE%" 2>&1
echo [%DATE% %TIME%] Copiando novos componentes para AssemblyCache... >> "%LOG_FILE%"
xcopy /s /e /y /i "%INSTALL_DIR%\*" "%CACHE_DIR%\" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    echo [%DATE% %TIME%] [FALHA] Erro ao copiar componentes para AssemblyCache. Codigo: %errorlevel% >> "%LOG_FILE%"
    goto :ROLLBACK
)

copy /Y "%CONFIG_FILE%" "%CACHE_DIR%\config.xml" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    echo [%DATE% %TIME%] [FALHA] Erro ao copiar config.xml para AssemblyCache. Codigo: %errorlevel% >> "%LOG_FILE%"
    goto :ROLLBACK
)

:: 5. ETAPA 3 DA TRANSACAO: Limpar bytecode antigo e recompilar
echo [%DATE% %TIME%] Limpando bytecode compilado antigo (.pyc)... >> "%LOG_FILE%"
del /Q /F "%CACHE_DIR%\*.pyc" 2>nul
del /Q /F "%CACHE_DIR%\backend\*.pyc" 2>nul

if exist "C:\Python27\ArcGIS10.8\python.exe" (
    echo [%DATE% %TIME%] Recompilando bytecode com Python 2.7 do ArcGIS... >> "%LOG_FILE%"
    "C:\Python27\ArcGIS10.8\python.exe" -m compileall "%CACHE_DIR%" >> "%LOG_FILE%" 2>&1
    if errorlevel 1 (
        echo [%DATE% %TIME%] [AVISO] compileall retornou codigo diferente de zero. Prosseguindo para o smoke test... >> "%LOG_FILE%"
    )
)

:: 6. ETAPA 4 DA TRANSACAO: Smoke Test de integridade pos-copia
echo [%DATE% %TIME%] Executando Smoke Test nos componentes essenciais... >> "%LOG_FILE%"
if not exist "%CACHE_DIR%\gee_gui.py" (
    echo [%DATE% %TIME%] [FALHA NO SMOKE TEST] gee_gui.py ausente no AssemblyCache! >> "%LOG_FILE%"
    goto :ROLLBACK
)
if not exist "%CACHE_DIR%\config.xml" (
    echo [%DATE% %TIME%] [FALHA NO SMOKE TEST] config.xml ausente no AssemblyCache! >> "%LOG_FILE%"
    goto :ROLLBACK
)
if not exist "%ADDIN_DIR%\GEE_Image_Selector.esriaddin" (
    echo [%DATE% %TIME%] [FALHA NO SMOKE TEST] .esriaddin ausente na pasta oficial! >> "%LOG_FILE%"
    goto :ROLLBACK
)

:: 7. Sincronizacao do repositorio local de desenvolvimento (opcional se existir)
if defined DEV_REPO if exist "%DEV_REPO%\arcgis_addin" (
    echo [%DATE% %TIME%] Sincronizando repositorio de desenvolvimento em "%DEV_REPO%"... >> "%LOG_FILE%"
    xcopy /s /e /y /i "%INSTALL_DIR%\*" "%DEV_REPO%\arcgis_addin\Install\" >> "%LOG_FILE%" 2>&1
    copy /Y "%STAGED_ADDIN%" "%DEV_REPO%\arcgis_addin\GEE_Image_Selector.esriaddin" >> "%LOG_FILE%" 2>&1
    if exist "%DEV_REPO%\backend" (
        xcopy /s /e /y /i "%INST_BACKEND%\*" "%DEV_REPO%\backend\" >> "%LOG_FILE%" 2>&1
    )
    if defined QGIS_PLUGIN if exist "%DEV_REPO%\qgis_plugin" (
        xcopy /s /e /y /i "%QGIS_PLUGIN%\*" "%DEV_REPO%\qgis_plugin\" >> "%LOG_FILE%" 2>&1
    )
)

:: 8. SUCESSO TOTAL DA TRANSACAO
echo [%DATE% %TIME%] [SUCESSO] Atualizacao concluida com exito e validada! >> "%LOG_FILE%"
rd /s /q "%STAGING_DIR%" 2>nul

powershell -NoProfile -Command "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; [System.Windows.Forms.MessageBox]::Show({success_text}, {success_title}, [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Information)"
(goto) 2>nul & del "%~f0"
exit /b 0

:: ============================================================================
:: ROTINA DE ROLLBACK AUTOMATICO (REVERSAO SEGURA EM CASO DE FALHA)
:: ============================================================================
:ROLLBACK
echo ====================================================================== >> "%LOG_FILE%"
echo [%DATE% %TIME%] [FALHA DETECTADA - INICIANDO ROLLBACK AUTOMATICO] >> "%LOG_FILE%"
echo ====================================================================== >> "%LOG_FILE%"

set "ROLLBACK_ERR=0"

:: Restaurar .esriaddin (obrigatorio no backup)
if exist "%BACKUP_DIR%\GEE_Image_Selector.esriaddin" (
    echo [%DATE% %TIME%] Restaurando .esriaddin do backup... >> "%LOG_FILE%"
    copy /Y "%BACKUP_DIR%\GEE_Image_Selector.esriaddin" "%ADDIN_DIR%\GEE_Image_Selector.esriaddin" >> "%LOG_FILE%" 2>&1
    if errorlevel 1 (
        echo [%DATE% %TIME%] [ERRO] Falha ao restaurar .esriaddin! >> "%LOG_FILE%"
        set "ROLLBACK_ERR=1"
    )
) else (
    echo [%DATE% %TIME%] [ERRO] Backup sem GEE_Image_Selector.esriaddin: nada a restaurar! >> "%LOG_FILE%"
    set "ROLLBACK_ERR=1"
)

:: Restaurar AssemblyCache (obrigatorio no backup: gee_gui.py e config.xml)
if not exist "%BACKUP_DIR%\AssemblyCache\gee_gui.py" (
    echo [%DATE% %TIME%] [ERRO] Backup sem AssemblyCache\gee_gui.py! >> "%LOG_FILE%"
    set "ROLLBACK_ERR=1"
)
if not exist "%BACKUP_DIR%\AssemblyCache\config.xml" (
    echo [%DATE% %TIME%] [ERRO] Backup sem AssemblyCache\config.xml! >> "%LOG_FILE%"
    set "ROLLBACK_ERR=1"
)
if exist "%BACKUP_DIR%\AssemblyCache" (
    echo [%DATE% %TIME%] Restaurando AssemblyCache do backup... >> "%LOG_FILE%"
    xcopy /s /e /y /i "%BACKUP_DIR%\AssemblyCache\*" "%CACHE_DIR%\" >> "%LOG_FILE%" 2>&1
    if errorlevel 1 (
        echo [%DATE% %TIME%] [ERRO] Falha ao restaurar AssemblyCache! >> "%LOG_FILE%"
        set "ROLLBACK_ERR=1"
    )
) else (
    echo [%DATE% %TIME%] [ERRO] Backup sem a pasta AssemblyCache: nada a restaurar! >> "%LOG_FILE%"
    set "ROLLBACK_ERR=1"
)

:: Recompilar versao restaurada
del /Q /F "%CACHE_DIR%\*.pyc" 2>nul
del /Q /F "%CACHE_DIR%\backend\*.pyc" 2>nul
if exist "C:\Python27\ArcGIS10.8\python.exe" (
    "C:\Python27\ArcGIS10.8\python.exe" -m compileall "%CACHE_DIR%" >> "%LOG_FILE%" 2>&1
)
if not exist "%CACHE_DIR%\gee_gui.py" set "ROLLBACK_ERR=1"
if not exist "%CACHE_DIR%\config.xml" set "ROLLBACK_ERR=1"

rd /s /q "%STAGING_DIR%" 2>nul

if "%ROLLBACK_ERR%"=="0" (
    echo [%DATE% %TIME%] [ROLLBACK CONCLUIDO] Estado anterior restaurado com seguranca. >> "%LOG_FILE%"
    powershell -NoProfile -Command "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; [System.Windows.Forms.MessageBox]::Show({rollback_ok_text}, {rollback_ok_title}, [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Warning)"
) else (
    echo [%DATE% %TIME%] [ROLLBACK COM ERROS] Ocorreram falhas ao restaurar os arquivos de backup. >> "%LOG_FILE%"
    powershell -NoProfile -Command "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; [System.Windows.Forms.MessageBox]::Show({rollback_err_text}, {rollback_err_title}, [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error)"
)
(goto) 2>nul & del "%~f0"
exit /b 1

:ABORT_NO_BACKUP
echo [%DATE% %TIME%] [ERRO FATAL] Cancelando operacao pois o backup nao pode ser verificado. >> "%LOG_FILE%"
rd /s /q "%STAGING_DIR%" 2>nul
powershell -NoProfile -Command "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; [System.Windows.Forms.MessageBox]::Show({abort_text}, {abort_title}, [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error)"
(goto) 2>nul & del "%~f0"
exit /b 1
"""


def build_runner_script(staging_info, backup_info, sys_dirs, log_file, sync_dev_repo=True, success_text=None,
                        gui_process=None):
    """Texto (unicode) do .bat do executor. Funcao pura: os testes geram o script sem executa-lo."""
    success_text = success_text or (u"ArcMagery atualizado com sucesso!\n\nTodos os arquivos foram validados, "
                                    u"instalados e recompilados.\nReabra o ArcMap para carregar a nova versão.")
    # No rollback a versao ANTIGA nunca e copiada para o repositorio de desenvolvimento
    dev_repo = (sys_dirs.get("dev_repo") or u"") if sync_dev_repo else u""
    gui_pid, gui_exe = gui_process if gui_process is not None else _gui_process_to_stop()
    template = _BAT_TEMPLATE if sys.version_info[0] >= 3 else _BAT_TEMPLATE.decode("ascii")
    return template.format(
        log_file=bat_path_text(log_file),
        addin_dir=bat_path_text(sys_dirs.get("addin_dir")),
        cache_dir=bat_path_text(sys_dirs.get("cache_dir")),
        snapshot_dir=bat_path_text(backup_info["snapshot_dir"]),
        staging_dir=bat_path_text(staging_info["staging_dir"]),
        staged_addin=bat_path_text(staging_info["staged_addin"]),
        install_dir=bat_path_text(staging_info["install_dir"]),
        config_file=bat_path_text(staging_info["config_file"]),
        inst_backend=bat_path_text(staging_info["inst_backend"]),
        dev_repo=bat_path_text(dev_repo),
        qgis_plugin=bat_path_text(staging_info.get("qgis_plugin_dir") or u"") if dev_repo else u"",
        gui_pid=_bat_text(gui_pid),
        gui_name=os.path.splitext(_bat_text(gui_exe))[0],   # Get-Process: nome sem '.exe'
        success_text=ps_message_expr(success_text),
        success_title=ps_message_expr(u"Atualização Concluída"),
        rollback_ok_text=ps_message_expr(
            u"A atualização encontrou um erro durante a instalação e foi CANCELADA.\n\n"
            u"O sistema executou o ROLLBACK AUTOMÁTICO e restaurou a versão anterior com sucesso.\n"
            u"Nenhuma funcionalidade foi perdida.\n\nConsulte o log de atualização para mais detalhes."),
        rollback_ok_title=ps_message_expr(u"Atualização Cancelada - Rollback Executado"),
        rollback_err_text=ps_message_expr(
            u"Aviso crítico: a atualização falhou e o rollback automático encontrou erros ao restaurar arquivos.\n\n"
            u"Verifique o arquivo de log para detalhes e certifique-se de que o ArcMap esteja fechado."),
        rollback_err_title=ps_message_expr(u"Aviso de Rollback"),
        abort_text=ps_message_expr(
            u"Erro crítico de atualização: o backup de segurança não foi encontrado ou está incompleto.\n"
            u"A operação foi cancelada e nenhum arquivo foi modificado."),
        abort_title=ps_message_expr(u"Erro de Atualização"),
    )


def generate_and_launch_detached_runner(staging_info, backup_info, sync_dev_repo=True, success_text=None):
    """
    Gera e despacha o script de instalação desacoplado com transação e ROLLBACK AUTOMÁTICO.
    O script roda independente de processos Python (evitando travas de arquivos) e:
    1. Aguarda o fechamento do processo da GUI (só o PID dela, conferindo o nome do executável;
       finaliza-o se não fechar em ~15 s). Nunca 'taskkill /im pythonw.exe' (U-02).
    2. Valida o snapshot (esriaddin + AssemblyCache) antes de iniciar qualquer alteração.
    3. Executa a cópia atômica com verificação de ERRORLEVEL a cada passo.
    4. Limpa pyc antigos e recompila novos módulos com python.exe.
    5. Efetua SMOKE TEST: confere se gee_gui.py e config.xml estão íntegros no destino.
    6. Em caso de falha em QUALQUER etapa: salta para :ROLLBACK, restaura todo o snapshot
       anterior, recompila e exibe mensagem de alerta informando a reversão segura.
    7. Em caso de sucesso total: limpa o staging e exibe notificação de sucesso.
    O .bat é gravado no codepage ANSI (o cmd desanexado não tem console: chcp não funciona) e os
    caminhos fora do ANSI usam o nome 8.3.
    """
    sys_dirs = find_system_directories()
    log_file = get_updater_log_path()

    ts = int(time.time() * 1000) % 1000000
    bat_path = os.path.join(runner_dir(), u"apply_arcgee_update_%d_%d.bat" % (os.getpid(), ts))

    log_info(u"Gerando script desacoplado de transação: %s" % bat_path)
    bat_content = build_runner_script(staging_info, backup_info, sys_dirs, log_file,
                                      sync_dev_repo=sync_dev_repo, success_text=success_text)

    with open(bat_path, "wb") as f_bat:
        f_bat.write(_bat_bytes(bat_content))

    log_info(u"Script em lote criado. Despachando processo desanexado...")

    # Flags para processo totalmente desanexado no Windows
    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    creation_flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

    subprocess.Popen(
        cmd_run_bat_line(bat_path),
        creationflags=creation_flags,
        close_fds=True
    )

    log_info(u"Processo de atualização desanexado iniciado com sucesso. Encerrando processo Python da interface.")
    return True

# ==============================================================================
# FLUXO ORQUESTRADO COMPLETO (ORCHESTRATOR)
# ==============================================================================

def execute_zip_update_flow(zip_path, current_version="2.4.3-nightly.20261006", progress_callback=None,
                            expected_sha256=None, allow_downgrade=False):
    """
    Fluxo de atualização passo a passo via arquivo ZIP:
    Fase 1: Pre-flight checks (integridade, segurança Zip Slip, espaço em disco, permissões).
    Fase 2: Criação de snapshot de backup da versão atual.
    Fase 3: Preparação e compilação do pacote em staging isolado.
    Fase 4: Geração e disparo do executor desacoplado com rollback automático.
    """
    log_info(u"=== INICIANDO FLUXO DE ATUALIZAÇÃO VIA ZIP ===")
    if progress_callback:
        progress_callback(u"1/4 Validando integridade e segurança do pacote...")

    # Fase 1: Pre-flight checks
    if expected_sha256:
        verify_file_sha256(zip_path, expected_sha256)
        log_info(u"Hash SHA-256 do pacote conferido com a Release.")
    target_dirs = find_system_directories()
    zip_meta = validate_zip_archive(zip_path, target_dirs=target_dirs)

    new_v = version_key(zip_meta.get("proposed_version"))
    cur_v = version_key(current_version)
    if new_v and cur_v and new_v < cur_v and not allow_downgrade:
        raise ConfirmationRequired(
            u"Pacote v%s é anterior à versão instalada v%s." % (zip_meta.get("proposed_version"), current_version),
            flag="allow_downgrade",
            title=u"Confirmar Downgrade",
            user_message=u"O pacote selecionado (v%s) é MAIS ANTIGO que a versão instalada (v%s).\n\n"
                         u"Deseja realmente voltar para a versão anterior?" % (zip_meta.get("proposed_version"), current_version))

    if progress_callback:
        progress_callback(u"2/4 Criando snapshot de backup da versão atual...")

    # Fase 2: Snapshot de segurança
    backup_meta = create_snapshot_backup(current_version=current_version)

    try:
        if progress_callback:
            progress_callback(u"3/4 Preparando e compilando nova versão...")

        # Fase 3: Staging isolado
        staging_info = prepare_staging_environment(zip_path)

        if progress_callback:
            progress_callback(u"4/4 Finalizando e aplicando alterações...")

        # Fase 4: Despacho desacoplado
        generate_and_launch_detached_runner(staging_info, backup_meta)
    except Exception:
        discard_snapshot(backup_meta)   # nada foi aplicado: o snapshot da versao atual nao vira "anterior"
        raise
    return True

def execute_git_update_flow(repo_path, remote_branch="main", current_version="2.4.3-nightly.20261006", progress_callback=None):
    """
    Fluxo de atualização passo a passo via repositório Git local:
    Fase 1: Pre-flight checks Git (conectividade, working tree limpa, divergência).
    Fase 2: Snapshot de segurança da instalação do ArcMap.
    Fase 3: Git pull / fast-forward merge com verificação de erro.
    Fase 4: Recompilação do .esriaddin e implantação desacoplada.
    """
    log_info(u"=== INICIANDO FLUXO DE ATUALIZAÇÃO VIA REPOSITÓRIO GIT ===")
    if progress_callback:
        progress_callback(u"1/4 Validando status do repositório Git...")

    # Fase 1: Pre-flight checks Git
    git_meta = validate_git_repository(repo_path, remote_branch=remote_branch)

    if progress_callback:
        progress_callback(u"2/4 Criando snapshot de backup de segurança...")

    # Fase 2: Snapshot de segurança
    backup_meta = create_snapshot_backup(current_version=current_version)
    try:
        return _git_update_after_snapshot(repo_path, remote_branch, git_meta, backup_meta, progress_callback)
    except Exception:
        discard_snapshot(backup_meta)
        raise


def _git_update_after_snapshot(repo_path, remote_branch, git_meta, backup_meta, progress_callback):
    repo_path = _cmdline_path(repo_path)
    if progress_callback:
        progress_callback(u"3/4 Baixando atualizações do GitHub via Git...")

    # Fase 3: Git pull fast-forward
    proc_pull = subprocess.Popen(
        ["git", "pull", "--ff-only", "origin", remote_branch],
        cwd=repo_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    out_pull, err_pull = proc_pull.communicate()
    if proc_pull.returncode != 0:
        err_msg = err_pull.decode("utf-8", "replace").strip()
        log_error(u"git pull falhou: %s" % err_msg)
        # Rollback via git reset se necessário
        try:
            subprocess.call(["git", "reset", "--hard", git_meta["current_head"]], cwd=repo_path)
        except Exception:
            pass
        raise GitRepositoryError(
            u"Falha ao executar 'git pull --ff-only': %s" % err_msg,
            title=u"Erro ao Sincronizar Git",
            user_message=u"Ocorreu um erro ao sincronizar o repositório local com a versão mais recente do GitHub.",
            technical_details=err_msg
        )

    # Fase 4: Reempacotar addin a partir do repositório atualizado
    if progress_callback:
        progress_callback(u"4/4 Recompilando e implantando Add-In...")

    addin_folder = os.path.join(repo_path, "arcgis_addin")
    makeaddin_script = os.path.join(addin_folder, "makeaddin.py")

    py27 = r"C:\Python27\ArcGIS10.8\python.exe"
    py_cmd = py27 if os.path.exists(py27) else sys.executable

    proc_make = subprocess.Popen(
        [py_cmd, makeaddin_script],
        cwd=addin_folder,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    proc_make.communicate()

    # Reutilizar o motor desacoplado com o zip gerado
    generated_addin = os.path.join(addin_folder, "GEE_Image_Selector.esriaddin")
    if not os.path.exists(generated_addin):
        raise UpdaterError(u"O script makeaddin.py não gerou o arquivo .esriaddin esperado.")

    staging_info = prepare_staging_environment(generated_addin)
    generate_and_launch_detached_runner(staging_info, backup_meta)
    return True

def execute_online_github_update_flow(current_version="2.4.3-nightly.20261006", progress_callback=None,
                                      allow_unverified_main=False, allow_downgrade=False,
                                      channel=CHANNEL_STABLE):
    """
    Fluxo de atualização inteligente online:
    1. Se o sistema estiver rodando de um clone Git com .git:
       Verifica o repositório local e aplica a atualização via Git (mantendo histórico).
    2. Se for uma instalação comum do ArcMap (AssemblyCache):
       Testa conectividade, baixa o arquivo ZIP oficial do GitHub com barra de progresso,
       e aciona o fluxo atômico de extração com backup e rollback.
    """
    log_info(u"=== INICIANDO FLUXO DE ATUALIZAÇÃO ONLINE INTELIGENTE ===")
    sys_dirs = find_system_directories()
    dev_repo = sys_dirs.get("dev_repo")

    # Verifica se dev_repo tem .git (so no canal estavel: o experimental usa sempre a Release nightly)
    if dev_repo and os.path.exists(os.path.join(dev_repo, ".git")) and channel == CHANNEL_STABLE:
        log_info(u"Repositório Git ativo detectado em %s. Usando canal Git." % dev_repo)
        try:
            return execute_git_update_flow(
                dev_repo,
                remote_branch="main",
                current_version=current_version,
                progress_callback=progress_callback
            )
        except PreflightCheckError as e_pf:
            # Se for um erro específico de Git (ex: dirty working tree), propagar para o usuário
            raise e_pf
        except Exception as e_git_fallback:
            log_warning(u"Atualização Git não pôde ser concluída (%s). Alternando para canal ZIP online." % _err(e_git_fallback))

    # Canal ZIP Online: Release publicada + SHA256SUMS (verificado) ou, com confirmação
    # explícita do usuário, o branch main sem verificação de integridade.
    if progress_callback:
        progress_callback(u"1/4 Consultando a última versão %s publicada..." % CHANNEL_LABELS.get(channel, u"").lower())
    release = fetch_release_for_channel(channel)
    zip_url, expected_sha = None, None
    if release and release.get("zip_url") and release.get("sums_url"):
        new_v, cur_v = version_key(release["version"]), version_key(current_version)
        if (new_v and cur_v and new_v < cur_v and not allow_downgrade and channel == CHANNEL_STABLE
                and is_prerelease(current_version)):
            raise ConfirmationRequired(
                u"Canal estável: v%s instalada é experimental; estável publicada v%s." % (current_version, release["version"]),
                flag="allow_downgrade",
                title=u"Voltar para a Versão Estável",
                user_message=u"Você está usando a versão EXPERIMENTAL v%s.\n\nA última versão ESTÁVEL publicada é a "
                             u"v%s. Deseja instalá-la no lugar da experimental?\n\n(A versão atual é salva antes e "
                             u"pode ser restaurada pelo botão de rollback.)" % (current_version, release["version"]))
        if new_v and cur_v and new_v <= cur_v and not allow_downgrade:
            raise UpdaterError(
                u"Versão publicada v%s não é mais nova que a instalada v%s." % (release["version"], current_version),
                title=u"Plugin Atualizado",
                user_message=u"Você já está na versão mais recente publicada (v%s)." % current_version)
        sums = parse_sha256sums(_http_get(release["sums_url"], timeout=20))
        expected_sha = sums.get(release["zip_name"])
        if not expected_sha:
            raise SecurityValidationError(
                u"%s não lista o pacote %s." % (RELEASE_CHECKSUM_ASSET, release["zip_name"]),
                title=u"Release Sem Hash",
                user_message=u"A Release publicada não contém o hash do pacote. A atualização foi bloqueada.")
        zip_url = release["zip_url"]
        log_info(u"Release %s encontrada; pacote %s (SHA-256 %s)." % (release["tag"], release["zip_name"], expected_sha))
    elif allow_unverified_main:
        log_warning(u"Nenhuma Release verificável publicada: usando branch main SEM verificação (confirmado pelo usuário).")
        zip_url = GITHUB_ZIP_URL
    else:
        raise ConfirmationRequired(
            u"Nenhuma Release com %s publicada." % RELEASE_CHECKSUM_ASSET,
            flag="allow_unverified_main",
            title=u"Atualização Sem Verificação",
            user_message=u"Não há uma Release publicada com hash de verificação (SHA256SUMS).\n\n"
                         u"Posso baixar a versão de desenvolvimento do branch 'main', mas a integridade "
                         u"do pacote NÃO poderá ser verificada e ele pode conter alterações ainda não testadas.\n\n"
                         u"Deseja continuar mesmo assim?")

    if progress_callback:
        progress_callback(u"1/4 Baixando pacote do GitHub...")

    tmp_zip = os.path.join(_temp_dir(), u"arcgee_github_update_%d.zip" % int(time.time()))

    def dl_progress(down, total):
        if total and progress_callback:
            pct = int((float(down) / float(total)) * 100)
            progress_callback(u"1/4 Baixando atualização do GitHub (%d%%)..." % pct)
        elif progress_callback:
            mb = down / (1024.0 * 1024.0)
            progress_callback(u"1/4 Baixando atualização do GitHub (%.1f MB)..." % mb)

    download_github_archive(tmp_zip, progress_callback=dl_progress, url=zip_url)
    return execute_zip_update_flow(tmp_zip, current_version=current_version, progress_callback=progress_callback,
                                   expected_sha256=expected_sha, allow_downgrade=allow_downgrade)


# ==============================================================================
# ROLLBACK PARA A VERSAO ANTERIOR (a partir dos snapshots de backup)
# ==============================================================================

def list_version_backups(backups_root=None):
    """Snapshots validos (com AssemblyCache/gee_gui.py e config.xml), do mais recente ao mais antigo."""
    import json
    root = backups_root or get_backups_dir()
    out = []
    try:
        names = os.listdir(root)
    except Exception:
        return out
    for name in names:
        d = os.path.join(root, name)
        cache = os.path.join(d, "AssemblyCache")
        if not (name.startswith("backup_") and os.path.isdir(d)):
            continue
        if not (os.path.exists(os.path.join(cache, "gee_gui.py")) and os.path.exists(os.path.join(cache, "config.xml"))):
            continue
        meta = {}
        try:
            with open(os.path.join(d, "backup_manifest.json"), "r") as f:
                meta = json.load(f)
        except Exception:
            pass
        version = meta.get("version") or _config_version(os.path.join(cache, "config.xml")) or u"?"
        out.append({
            "dir": d, "cache_dir": cache, "version": version,
            "timestamp": meta.get("timestamp") or u"",
            "mtime": os.path.getmtime(d),
            "addin": os.path.join(d, "GEE_Image_Selector.esriaddin") if os.path.exists(
                os.path.join(d, "GEE_Image_Selector.esriaddin")) else None,
        })
    out.sort(key=lambda b: b["mtime"], reverse=True)
    return out


def _config_version(config_xml):
    try:
        root = ET.parse(config_xml).getroot()
        for el in root.iter():
            if el.tag.endswith("Version") and (el.text or "").strip():
                return el.text.strip()
    except Exception:
        pass
    return None


def describe_backup(b):
    """'v2.3.3 de 29/09/2026 14:05' para a interface."""
    ts = b.get("timestamp") or ""
    when = u""
    if len(ts) >= 15:
        when = u" de %s/%s/%s %s:%s" % (ts[6:8], ts[4:6], ts[0:4], ts[9:11], ts[11:13])
    return u"v%s%s" % (b.get("version"), when)


def find_previous_version_backup(backups_root=None, current_version=None):
    """Versao anterior = o snapshot mais recente (tirado antes da ultima atualizacao ou rollback) de
    uma versao DIFERENTE da instalada: um snapshot da propria versao atual (reinstalacao da mesma versao
    ou fluxo que falhou depois do snapshot) nao 'volta' para nada."""
    cur_k = version_key(current_version) if current_version else None
    for b in list_version_backups(backups_root):
        if cur_k is not None and version_key(b.get("version")) == cur_k:
            continue
        if current_version and cur_k is None and b.get("version") == current_version:
            continue
        return b
    return None


def execute_rollback_to_previous_flow(current_version="2.4.3-nightly.20261006", progress_callback=None, backup=None):
    """Reinstala o snapshot da versao anterior pelo mesmo executor desacoplado da atualizacao:
    snapshot da versao ATUAL primeiro (se a restauracao falhar, o executor volta a ela), copia do
    backup escolhido para um staging descartavel e nada e copiado para o repositorio de desenvolvimento."""
    log_info(u"=== INICIANDO ROLLBACK PARA A VERSÃO ANTERIOR ===")
    target = backup or find_previous_version_backup(current_version=current_version)
    if not target:
        raise UpdaterError(
            u"Nenhum snapshot de versão anterior encontrado em %s." % get_backups_dir(),
            title=u"Rollback Indisponível",
            user_message=u"Não há uma versão anterior salva neste computador.\n\n"
                         u"Os backups são criados automaticamente a cada atualização pelo assistente.",
            remediation=[u"Instale uma versão anterior pelo Método 2 (arquivo ZIP da Release)."])
    if not target.get("addin"):
        raise CorruptPackageError(
            u"Snapshot sem GEE_Image_Selector.esriaddin: %s" % target["dir"],
            title=u"Backup Incompleto",
            user_message=u"O backup da versão anterior está incompleto e não pode ser restaurado.")
    label = describe_backup(target)
    log_info(u"Rollback: v%s -> %s (%s)" % (current_version, label, target["dir"]))

    if progress_callback:
        progress_callback(u"1/3 Salvando a versão atual (para poder desfazer)...")
    backup_meta = create_snapshot_backup(current_version=current_version)

    try:
        if progress_callback:
            progress_callback(u"2/3 Preparando %s..." % label)
        staging_dir = tempfile.mkdtemp(prefix="arcgee_rollback_", dir=_temp_dir())
        install_dir = os.path.join(staging_dir, u"Install")
        shutil.copytree(target["cache_dir"], install_dir)
        staged_addin = os.path.join(staging_dir, u"GEE_Image_Selector.esriaddin")
        shutil.copy2(target["addin"], staged_addin)
        for root, _dirs, files in os.walk(install_dir):
            for f in files:
                if f.endswith((".pyc", ".pyo")):
                    try:
                        os.remove(os.path.join(root, f))
                    except Exception:
                        pass
        staging_info = {
            "staging_dir": staging_dir,
            "config_file": os.path.join(install_dir, u"config.xml"),
            "install_dir": install_dir,
            "inst_backend": os.path.join(install_dir, u"backend"),
            "staged_addin": staged_addin,
        }

        if progress_callback:
            progress_callback(u"3/3 Aplicando %s..." % label)
        generate_and_launch_detached_runner(
            staging_info, backup_meta, sync_dev_repo=False,
            success_text=u"ArcMagery voltou para a versão anterior (%s).\n\nReabra o ArcMap para carregar essa versão. "
                         u"Para desfazer, use de novo o botão de rollback." % label)
    except Exception:
        discard_snapshot(backup_meta)
        raise
    return target
