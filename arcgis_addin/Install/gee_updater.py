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

GITHUB_REPO_URL = "https://github.com/Yiuky/arcgis-google-earth-engine-explorer"
GITHUB_ZIP_URL = "https://github.com/Yiuky/arcgis-google-earth-engine-explorer/archive/refs/heads/main.zip"
# Canal oficial: GitHub Releases com arquivo de hashes publicado junto do pacote.
GITHUB_API_LATEST_RELEASE = "https://api.github.com/repos/Yiuky/arcgis-google-earth-engine-explorer/releases/latest"
# Lista de Releases (inclui pre-releases/nightly; /latest so devolve a ultima ESTAVEL)
GITHUB_API_RELEASES = "https://api.github.com/repos/Yiuky/arcgis-google-earth-engine-explorer/releases?per_page=40"
# Canais de atualizacao: estavel (Releases normais) e experimental (pre-releases "-nightly.AAAAMMDD")
CHANNEL_STABLE, CHANNEL_NIGHTLY = "stable", "nightly"
CHANNEL_LABELS = {CHANNEL_STABLE: u"Estável", CHANNEL_NIGHTLY: u"Experimental (nightly)"}
RELEASE_CHECKSUM_ASSET = "SHA256SUMS.txt"
UPDATER_USER_AGENT = "ArcMagery-Updater/2.3"
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
# SISTEMA DE LOGGING ESTRUTURADO
# ==============================================================================

def get_app_data_dir():
    """Retorna o diretório base para dados do aplicativo CGMA ArcGEE (%LOCALAPPDATA%\\CGMA_ArcGEE)."""
    user_prof = os.environ.get("USERPROFILE", "")
    local_appdata = os.environ.get("LOCALAPPDATA", "") or os.path.join(user_prof, "AppData", "Local")
    base_dir = os.path.join(local_appdata, "CGMA_ArcGEE")
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
            logs_dir = tempfile.gettempdir()
    return os.path.join(logs_dir, "arcgee_updater.log")

def get_backups_dir():
    """Retorna o diretório raiz onde os snapshots de backup são armazenados."""
    base_dir = get_app_data_dir()
    backups_dir = os.path.join(base_dir, "backups")
    if not os.path.exists(backups_dir):
        try:
            os.makedirs(backups_dir)
        except Exception:
            backups_dir = os.path.join(tempfile.gettempdir(), "arcgee_backups")
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
            if isinstance(abs_path, str):
                wchar_path = abs_path.decode("utf-8", "replace")
            else:
                wchar_path = abs_path
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
        log_warning("Falha em GetDiskFreeSpaceExW: %s" % e)

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
            return False, "Nao foi possivel criar o diretorio: %s" % str(e)

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
        return False, str(e)

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


def fetch_latest_release(api_url=GITHUB_API_LATEST_RELEASE):
    """Consulta a ultima Release publicada. Retorna None se o repositorio ainda nao tem Releases.
    Retorna dict: version, tag, zip_name, zip_url, sums_url."""
    import json
    try:
        data = json.loads(_http_get(api_url, timeout=20, accept="application/vnd.github+json").decode("utf-8"))
    except Exception as e:
        code = getattr(e, "code", None)
        if code == 404:
            return None
        raise NetworkError(
            u"Falha ao consultar a última Release do GitHub: %s" % e,
            title=u"Falha ao Consultar Releases",
            user_message=u"Não foi possível consultar a versão publicada no GitHub.",
            remediation=[u"Verifique a conexão/proxy.", u"Tente a atualização via arquivo ZIP."],
            technical_details=traceback.format_exc())
    return _release_info(data)


def _release_info(data):
    assets = data.get("assets") or []
    zips = [a for a in assets if a.get("name", "").lower().endswith(".zip")]
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


def fetch_newest_release(api_url=GITHUB_API_RELEASES):
    """Canal experimental: a Release mais nova da lista (estavel OU nightly), so as publicadas com
    pacote e SHA256SUMS. Retorna None se nao houver."""
    import json
    try:
        data = json.loads(_http_get(api_url, timeout=20, accept="application/vnd.github+json").decode("utf-8"))
    except Exception as e:
        if getattr(e, "code", None) == 404:
            return None
        raise NetworkError(
            u"Falha ao consultar as Releases do GitHub: %s" % e,
            title=u"Falha ao Consultar Releases",
            user_message=u"Não foi possível consultar as versões publicadas no GitHub.",
            remediation=[u"Verifique a conexão/proxy.", u"Tente a atualização via arquivo ZIP."],
            technical_details=traceback.format_exc())
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
        return False, u"Falha na resolução de DNS para %s: %s" % (host, e)
    except socket.timeout:
        return False, u"Tempo limite excedido (%ds) conectando a %s:%d" % (timeout, host, port)
    except Exception as e:
        return False, u"Erro de conexão com %s:%d: %s" % (host, port, e)

def find_system_directories():
    """
    Localiza os diretórios oficiais do Add-In no ArcGIS Desktop 10.8 e o repositório local de dev.
    """
    user_prof = os.environ.get("USERPROFILE", "")
    addin_dir = os.path.join(
        user_prof,
        r"Documents\ArcGIS\AddIns\Desktop10.8\%s" % ADDIN_UUID
    )
    cache_dir = os.path.join(
        user_prof,
        r"AppData\Local\ESRI\Desktop10.8\AssemblyCache\%s" % ADDIN_UUID_UPPER
    )

    curr_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.abspath(os.path.join(curr_dir, "..", "..")),
        os.environ.get("GEE_PLUGIN_DEV_REPO", "")
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
        log_error(u"Arquivo não é um ZIP válido: %s" % e)
        raise CorruptPackageError(
            u"O arquivo não possui cabeçalho ZIP válido.",
            title=u"Pacote Corrompido",
            user_message=u"O arquivo fornecido não é um arquivo ZIP válido ou seus cabeçalhos foram corrompidos.",
            remediation=[
                u"Faça o download novamente do pacote oficial.",
                u"Não renomeie extensões de arquivos arbitrariamente."
            ],
            technical_details=str(e)
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
                log_warning(u"Não foi possível extrair a versão do config.xml: %s" % e_xml)

    finally:
        z.close()

    # 5. Cálculo e validação de espaço livre em disco
    # Fórmula: 3x o tamanho descompactado (staging + backup + instalação) + 50 MB de margem
    required_space = (total_uncompressed_bytes * 3) + (50 * 1024 * 1024)
    temp_dir = tempfile.gettempdir()
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
    log_info(u"Iniciando pré-validação Git no repositório: %s" % repo_path)

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
            u"Executável 'git' não encontrado no sistema: %s" % e_git,
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
        log_error(u"Erro durante o download do GitHub: %s" % e)
        if isinstance(e, UpdaterError):
            raise
        raise NetworkError(
            u"Falha durante transferência de dados do GitHub: %s" % e,
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

def create_snapshot_backup(current_version="2.4.1", backups_root=None, custom_sys_dirs=None):
    """
    Cria um backup completo e atômico do estado operacional atual do plugin.
    Copia o .esriaddin instalado e todo o AssemblyCache para uma pasta versionada:
    %LOCALAPPDATA%\\CGMA_ArcGEE\\backups\\backup_<timestamp>

    Salva um arquivo manifest.json para auditoria e controle de integridade.
    Retorna o dicionário com metadados do snapshot.
    """
    sys_dirs = custom_sys_dirs if custom_sys_dirs else find_system_directories()
    addin_dir = sys_dirs.get("addin_dir", "")
    cache_dir = sys_dirs.get("cache_dir", "")

    timestamp_str = time.strftime("%Y%m%d_%H%M%S")
    if backups_root is None:
        backups_root = get_backups_dir()
    snapshot_dir = os.path.join(backups_root, "backup_%s_%s" % (current_version.replace(".", "_"), timestamp_str))

    log_info(u"Criando snapshot de backup em: %s" % snapshot_dir)
    if not os.path.exists(snapshot_dir):
        try:
            os.makedirs(snapshot_dir)
        except Exception as e:
            raise PermissionCheckError(
                u"Falha ao criar pasta de backup: %s" % e,
                title=u"Erro de Backup",
                user_message=u"Não foi possível criar o diretório de segurança para backup antes da atualização.",
                technical_details=str(e)
            )

    backup_manifest = {
        "timestamp": timestamp_str,
        "version": current_version,
        "snapshot_dir": snapshot_dir,
        "files": {}
    }

    # 1. Backup do arquivo .esriaddin
    live_addin = os.path.join(addin_dir, "GEE_Image_Selector.esriaddin")
    if os.path.exists(live_addin):
        dest_addin = os.path.join(snapshot_dir, "GEE_Image_Selector.esriaddin")
        try:
            shutil.copy2(live_addin, dest_addin)
            backup_manifest["files"]["esriaddin"] = {
                "source": live_addin,
                "backup": dest_addin,
                "sha256": calculate_file_sha256(dest_addin)
            }
        except Exception as e_cp:
            log_warning(u"Aviso: não foi possível copiar .esriaddin para o backup: %s" % e_cp)

    # 2. Backup do AssemblyCache
    if os.path.exists(cache_dir):
        dest_cache = os.path.join(snapshot_dir, "AssemblyCache")
        try:
            shutil.copytree(cache_dir, dest_cache)
            backup_manifest["files"]["cache_dir"] = {
                "source": cache_dir,
                "backup": dest_cache
            }
        except Exception as e_cache:
            log_warning(u"Aviso: cópia do AssemblyCache para backup parcial: %s" % e_cache)

    # 3. Gravar manifest.json
    try:
        manifest_file = os.path.join(snapshot_dir, "backup_manifest.json")
        import json
        with open(manifest_file, "w") as f_man:
            json.dump(backup_manifest, f_man, indent=2)
    except Exception as e_man:
        log_warning(u"Não foi possível salvar manifest.json: %s" % e_man)

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
        log_warning(u"Erro na retenção de backups: %s" % e_ret)

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
    staging_base = tempfile.gettempdir()
    ts = int(time.time() * 1000) % 1000000
    staging_dir = os.path.join(staging_base, "arcgee_stage_%d" % ts)

    if os.path.exists(staging_dir):
        try:
            shutil.rmtree(staging_dir)
        except Exception:
            pass
    try:
        os.makedirs(staging_dir)
    except Exception as e:
        raise PermissionCheckError(
            u"Não foi possível criar a pasta de staging: %s" % e,
            title=u"Erro de Sistema",
            user_message=u"Falha ao criar diretório temporário isolado para a atualização.",
            technical_details=str(e)
        )

    # 1. Extração segura com sanitização de caminhos (Prevenção Zip Slip)
    with zipfile.ZipFile(zip_path, "r") as z:
        for member in z.infolist():
            filename = member.filename.replace("\\", "/")
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

    log_info(u"Ambiente de staging pronto e verificado: %s" % staged_addin)
    return {
        "staging_dir": staging_dir,
        "config_file": config_file,
        "install_dir": install_dir,
        "inst_backend": inst_backend,
        "staged_addin": staged_addin
    }

# ==============================================================================
# SCRIPT DESACOPLADO E TRANSAÇÃO COM ROLLBACK AUTOMÁTICO
# ==============================================================================

def _bat_text(text):
    """Texto no mesmo tipo do template do .bat (bytes UTF-8 no Python 2; o .bat usa chcp 65001)."""
    if sys.version_info[0] < 3 and not isinstance(text, bytes):
        return text.encode("utf-8")
    return text


def generate_and_launch_detached_runner(staging_info, backup_info, sync_dev_repo=True, success_text=None):
    """
    Gera e despacha o script de instalação desacoplado com transação e ROLLBACK AUTOMÁTICO.
    O script roda independente de processos Python (evitando travas de arquivos) e:
    1. Aguarda o fechamento do processo GUI e taskkill do pythonw se necessário.
    2. Valida o diretório de backup antes de iniciar qualquer alteração.
    3. Executa a cópia atômica com verificação de ERRORLEVEL a cada passo.
    4. Limpa pyc antigos e recompila novos módulos com python.exe.
    5. Efetua SMOKE TEST: confere se gee_gui.py e config.xml estão íntegros no destino.
    6. Em caso de falha em QUALQUER etapa: salta para :ROLLBACK, restaura todo o snapshot
       anterior, recompila e exibe mensagem de alerta informando a reversão segura.
    7. Em caso de sucesso total: limpa o staging e exibe notificação de sucesso.
    """
    sys_dirs = find_system_directories()
    addin_dir = sys_dirs["addin_dir"]
    cache_dir = sys_dirs["cache_dir"]
    # No rollback a versao ANTIGA nunca e copiada para o repositorio de desenvolvimento
    dev_repo = (sys_dirs["dev_repo"] or "") if sync_dev_repo else ""
    success_text = success_text or (u"ArcMagery atualizado com sucesso!`n`nTodos os arquivos foram validados, "
                                    u"instalados e recompilados.`nReabra o ArcMap para carregar a nova versão.")

    staging_dir = staging_info["staging_dir"]
    config_file = staging_info["config_file"]
    install_dir = staging_info["install_dir"]
    inst_backend = staging_info["inst_backend"]
    staged_addin = staging_info["staged_addin"]

    snapshot_dir = backup_info["snapshot_dir"]
    log_file = get_updater_log_path()

    ts = int(time.time() * 1000) % 1000000
    bat_path = os.path.join(tempfile.gettempdir(), "apply_arcgee_update_%d.bat" % ts)

    log_info(u"Gerando script desacoplado de transação: %s" % bat_path)

    # Template do script em lote altamente resiliente com rollback automático
    bat_content = r"""@echo off
chcp 65001 >nul
title Atualizador ArcMagery

set LOG_FILE={log_file}
set ADDIN_DIR={addin_dir}
set CACHE_DIR={cache_dir}
set BACKUP_DIR={snapshot_dir}
set STAGING_DIR={staging_dir}
set STAGED_ADDIN={staged_addin}
set INSTALL_DIR={install_dir}
set CONFIG_FILE={config_file}
set INST_BACKEND={inst_backend}
set DEV_REPO={dev_repo}

echo ====================================================================== >> "%LOG_FILE%"
echo [%DATE% %TIME%] [TRANSAÇÃO DE ATUALIZAÇÃO INICIADA] >> "%LOG_FILE%"
echo ====================================================================== >> "%LOG_FILE%"

:: 1. Aguardar liberação dos processos Python e ArcMap
echo [%DATE% %TIME%] Aguardando encerramento dos processos Python... >> "%LOG_FILE%"
ping 127.0.0.1 -n 3 >nul
taskkill /f /im pythonw.exe 2>nul
ping 127.0.0.1 -n 2 >nul

:: 2. Validação prévia de integridade do backup
if not exist "%BACKUP_DIR%" (
    echo [%DATE% %TIME%] [ERRO CRÍTICO] Diretório de backup não encontrado: "%BACKUP_DIR%" >> "%LOG_FILE%"
    goto :ABORT_NO_BACKUP
)

echo [%DATE% %TIME%] Backup de segurança confirmado em: "%BACKUP_DIR%" >> "%LOG_FILE%"

:: 3. ETAPA 1 DA TRANSAÇÃO: Atualizar arquivo .esriaddin
if not exist "%ADDIN_DIR%" mkdir "%ADDIN_DIR%" >> "%LOG_FILE%" 2>&1
echo [%DATE% %TIME%] Copiando pacote .esriaddin para "%ADDIN_DIR%"... >> "%LOG_FILE%"
copy /Y "%STAGED_ADDIN%" "%ADDIN_DIR%\GEE_Image_Selector.esriaddin" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    echo [%DATE% %TIME%] [FALHA] Erro ao copiar .esriaddin. Código de saída: %errorlevel% >> "%LOG_FILE%"
    goto :ROLLBACK
)

:: 4. ETAPA 2 DA TRANSAÇÃO: Atualizar arquivos do AssemblyCache
if not exist "%CACHE_DIR%" mkdir "%CACHE_DIR%" >> "%LOG_FILE%" 2>&1
echo [%DATE% %TIME%] Copiando novos componentes para AssemblyCache... >> "%LOG_FILE%"
xcopy /s /e /y /i "%INSTALL_DIR%\*" "%CACHE_DIR%\" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    echo [%DATE% %TIME%] [FALHA] Erro ao copiar componentes para AssemblyCache. Código: %errorlevel% >> "%LOG_FILE%"
    goto :ROLLBACK
)

copy /Y "%CONFIG_FILE%" "%CACHE_DIR%\config.xml" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    echo [%DATE% %TIME%] [FALHA] Erro ao copiar config.xml para AssemblyCache. Código: %errorlevel% >> "%LOG_FILE%"
    goto :ROLLBACK
)

:: 5. ETAPA 3 DA TRANSAÇÃO: Limpar bytecode antigo e recompilar
echo [%DATE% %TIME%] Limpando bytecode compilado antigo (.pyc)... >> "%LOG_FILE%"
del /Q /F "%CACHE_DIR%\*.pyc" 2>nul
del /Q /F "%CACHE_DIR%\backend\*.pyc" 2>nul

if exist "C:\Python27\ArcGIS10.8\python.exe" (
    echo [%DATE% %TIME%] Recompilando bytecode com Python 2.7 do ArcGIS... >> "%LOG_FILE%"
    "C:\Python27\ArcGIS10.8\python.exe" -m compileall "%CACHE_DIR%" >> "%LOG_FILE%" 2>&1
    if errorlevel 1 (
        echo [%DATE% %TIME%] [AVISO] Compilação compileall retornou código diferente de zero. Prosseguindo para smoke test... >> "%LOG_FILE%"
    )
)

:: 6. ETAPA 4 DA TRANSAÇÃO: Smoke Test de integridade pós-cópia
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

:: 7. Sincronização do repositório local de desenvolvimento (opcional se existir)
if defined DEV_REPO if exist "%DEV_REPO%\arcgis_addin" (
    echo [%DATE% %TIME%] Sincronizando repositório de desenvolvimento em "%DEV_REPO%"... >> "%LOG_FILE%"
    xcopy /s /e /y /i "%INSTALL_DIR%\*" "%DEV_REPO%\arcgis_addin\Install\" >> "%LOG_FILE%" 2>&1
    copy /Y "%STAGED_ADDIN%" "%DEV_REPO%\arcgis_addin\GEE_Image_Selector.esriaddin" >> "%LOG_FILE%" 2>&1
    if exist "%DEV_REPO%\backend" (
        xcopy /s /e /y /i "%INST_BACKEND%\*" "%DEV_REPO%\backend\" >> "%LOG_FILE%" 2>&1
    )
)

:: 8. SUCESSO TOTAL DA TRANSAÇÃO
echo [%DATE% %TIME%] [SUCESSO] Atualização concluída com êxito e validada! >> "%LOG_FILE%"
rd /s /q "%STAGING_DIR%" 2>nul

powershell -NoProfile -Command "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; [System.Windows.Forms.MessageBox]::Show('{success_text}', 'Atualização Concluída', [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Information)"
(goto) 2>nul & del "%~f0"
exit /b 0

:: ============================================================================
:: ROTINA DE ROLLBACK AUTOMÁTICO (REVERSÃO SEGURA EM CASO DE FALHA)
:: ============================================================================
:ROLLBACK
echo ====================================================================== >> "%LOG_FILE%"
echo [%DATE% %TIME%] [FALHA DETECTADA - INICIANDO ROLLBACK AUTOMÁTICO] >> "%LOG_FILE%"
echo ====================================================================== >> "%LOG_FILE%"

set "ROLLBACK_ERR=0"

:: Restaurar .esriaddin
if exist "%BACKUP_DIR%\GEE_Image_Selector.esriaddin" (
    echo [%DATE% %TIME%] Restaurando .esriaddin do backup... >> "%LOG_FILE%"
    copy /Y "%BACKUP_DIR%\GEE_Image_Selector.esriaddin" "%ADDIN_DIR%\GEE_Image_Selector.esriaddin" >> "%LOG_FILE%" 2>&1
    if errorlevel 1 (
        echo [%DATE% %TIME%] [ERRO] Falha ao restaurar .esriaddin! >> "%LOG_FILE%"
        set "ROLLBACK_ERR=1"
    )
)

:: Restaurar AssemblyCache
if exist "%BACKUP_DIR%\AssemblyCache" (
    echo [%DATE% %TIME%] Restaurando AssemblyCache do backup... >> "%LOG_FILE%"
    xcopy /s /e /y /i "%BACKUP_DIR%\AssemblyCache\*" "%CACHE_DIR%\" >> "%LOG_FILE%" 2>&1
    if errorlevel 1 (
        echo [%DATE% %TIME%] [ERRO] Falha ao restaurar AssemblyCache! >> "%LOG_FILE%"
        set "ROLLBACK_ERR=1"
    )
)

:: Recompilar versão restaurada
del /Q /F "%CACHE_DIR%\*.pyc" 2>nul
del /Q /F "%CACHE_DIR%\backend\*.pyc" 2>nul
if exist "C:\Python27\ArcGIS10.8\python.exe" (
    "C:\Python27\ArcGIS10.8\python.exe" -m compileall "%CACHE_DIR%" >> "%LOG_FILE%" 2>&1
)

rd /s /q "%STAGING_DIR%" 2>nul

if "%ROLLBACK_ERR%"=="0" (
    echo [%DATE% %TIME%] [ROLLBACK CONCLUÍDO] Estado anterior restaurado com segurança. >> "%LOG_FILE%"
    powershell -NoProfile -Command "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; [System.Windows.Forms.MessageBox]::Show('A atualização encontrou um erro durante a instalação e foi CANCELADA.`n`nO sistema executou o ROLLBACK AUTOMÁTICO e restaurou a versão anterior com sucesso.`nNenhuma funcionalidade foi perdida.`n`nConsulte o log de atualização para mais detalhes.', 'Atualização Cancelada - Rollback Executado', [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Warning)"
) else (
    echo [%DATE% %TIME%] [ROLLBACK COM ERROS] Ocorreram falhas ao restaurar os arquivos de backup. >> "%LOG_FILE%"
    powershell -NoProfile -Command "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; [System.Windows.Forms.MessageBox]::Show('Aviso crítico: A atualização falhou e o rollback automático encontrou erros ao restaurar arquivos.`n`nVerifique o arquivo de log para detalhes e certifique-se de que o ArcMap esteja fechado.', 'Aviso de Rollback', [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error)"
)
(goto) 2>nul & del "%~f0"
exit /b 1

:ABORT_NO_BACKUP
echo [%DATE% %TIME%] [ERRO FATAL] Cancelando operação pois o backup não pôde ser verificado. >> "%LOG_FILE%"
powershell -NoProfile -Command "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; [System.Windows.Forms.MessageBox]::Show('Erro crítico de atualização: diretório de backup não encontrado.`nA operação foi cancelada e nenhum arquivo foi modificado.', 'Erro de Atualização', [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error)"
(goto) 2>nul & del "%~f0"
exit /b 1
""".format(
        log_file=log_file,
        addin_dir=addin_dir,
        cache_dir=cache_dir,
        snapshot_dir=snapshot_dir,
        staging_dir=staging_dir,
        staged_addin=staged_addin,
        install_dir=install_dir,
        config_file=config_file,
        inst_backend=inst_backend,
        dev_repo=dev_repo,
        success_text=_bat_text(success_text.replace("'", ""))
    )

    with open(bat_path, "w") as f_bat:
        f_bat.write(bat_content)

    log_info(u"Script em lote criado. Despachando processo desanexado...")

    # Flags para processo totalmente desanexado no Windows
    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    creation_flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

    subprocess.Popen(
        ["cmd.exe", "/c", bat_path],
        creationflags=creation_flags,
        close_fds=True
    )

    log_info(u"Processo de atualização desanexado iniciado com sucesso. Encerrando processo Python da interface.")
    return True

# ==============================================================================
# FLUXO ORQUESTRADO COMPLETO (ORCHESTRATOR)
# ==============================================================================

def execute_zip_update_flow(zip_path, current_version="2.4.1", progress_callback=None,
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

    if progress_callback:
        progress_callback(u"3/4 Preparando e compilando nova versão...")

    # Fase 3: Staging isolado
    staging_info = prepare_staging_environment(zip_path)

    if progress_callback:
        progress_callback(u"4/4 Finalizando e aplicando alterações...")

    # Fase 4: Despacho desacoplado
    generate_and_launch_detached_runner(staging_info, backup_meta)
    return True

def execute_git_update_flow(repo_path, remote_branch="main", current_version="2.4.1", progress_callback=None):
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

def execute_online_github_update_flow(current_version="2.4.1", progress_callback=None,
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
            log_warning(u"Atualização Git não pôde ser concluída (%s). Alternando para canal ZIP online." % e_git_fallback)

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

    tmp_zip = os.path.join(tempfile.gettempdir(), "arcgee_github_update_%d.zip" % int(time.time()))

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


def find_previous_version_backup(backups_root=None):
    """Versao anterior = o snapshot mais recente (tirado antes da ultima atualizacao ou rollback)."""
    backups = list_version_backups(backups_root)
    return backups[0] if backups else None


def execute_rollback_to_previous_flow(current_version="2.4.1", progress_callback=None, backup=None):
    """Reinstala o snapshot da versao anterior pelo mesmo executor desacoplado da atualizacao:
    snapshot da versao ATUAL primeiro (se a restauracao falhar, o executor volta a ela), copia do
    backup escolhido para um staging descartavel e nada e copiado para o repositorio de desenvolvimento."""
    log_info(u"=== INICIANDO ROLLBACK PARA A VERSÃO ANTERIOR ===")
    target = backup or find_previous_version_backup()
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

    if progress_callback:
        progress_callback(u"2/3 Preparando %s..." % label)
    staging_dir = tempfile.mkdtemp(prefix="arcgee_rollback_")
    install_dir = os.path.join(staging_dir, "Install")
    shutil.copytree(target["cache_dir"], install_dir)
    staged_addin = os.path.join(staging_dir, "GEE_Image_Selector.esriaddin")
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
        "config_file": os.path.join(install_dir, "config.xml"),
        "install_dir": install_dir,
        "inst_backend": os.path.join(install_dir, "backend"),
        "staged_addin": staged_addin,
    }

    if progress_callback:
        progress_callback(u"3/3 Aplicando %s..." % label)
    generate_and_launch_detached_runner(
        staging_info, backup_meta, sync_dev_repo=False,
        success_text=u"ArcMagery voltou para a versão anterior (%s).`n`nReabra o ArcMap para carregar essa versão. "
                     u"Para desfazer, use de novo o botão de rollback." % label)
    return target
