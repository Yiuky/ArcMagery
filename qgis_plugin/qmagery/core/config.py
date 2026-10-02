# -*- coding: utf-8 -*-
"""
Versão, caminhos e configurações do QMagery (sem dependência do Qt: testável fora do QGIS).

As configurações do usuário ficam FORA da pasta do plugin, porque o Gerenciador de Complementos do
QGIS apaga e recria essa pasta a cada atualização. São os mesmos arquivos do ArcMagery, então o ID do
projeto do Google Cloud e a chave do GEODES valem para os dois plugins:

    %APPDATA%\\ArcGEE\\gee_config.json        {"project": "..."}
    %APPDATA%\\ArcGEE\\geodes_config.json     {"api_key": "..."}
    %APPDATA%\\ArcGEE\\qmagery_settings.json  preferências só do QMagery (pasta de saída, threads...)
"""
import configparser
import io
import json
import os
import tempfile

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
METADATA_FILE = os.path.join(PLUGIN_DIR, 'metadata.txt')

GEODES_KEY_ENV = 'GEODES_API_KEY'
TILE_THREADS_MIN, TILE_THREADS_MAX = 4, 64

DEFAULT_SETTINGS = {
    'output_dir': '',          # vazio = Documentos\QMagery
    'tile_threads': 0,         # 0 = automático (como o ArcMagery: 4 x núcleos, entre 8 e 48)
    'show_startup_check': True,
    'tos_accepted': False,     # aviso de termos de uso do Google/Bing aceito
}


# --------------------------------------------------------------------------- versão
def read_metadata(path=METADATA_FILE):
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    try:
        with io.open(path, 'r', encoding='utf-8') as f:
            parser.read_file(f)
        return dict(parser['general'])
    except Exception:
        return {}


def plugin_version():
    return read_metadata().get('version', '0.0.0')


def is_experimental(version=None):
    version = version or plugin_version()
    meta = read_metadata()
    return '-' in version or str(meta.get('experimental', 'False')).lower() == 'true'


def version_label(version=None):
    version = version or plugin_version()
    return u"v%s%s" % (version, u" (experimental)" if is_experimental(version) else u"")


# --------------------------------------------------------------------------- backend
def backend_candidates(plugin_dir=PLUGIN_DIR):
    """Pacote QMagery-x.zip: qmagery/backend. Repositório (desenvolvimento): arcgis_addin/Install/backend."""
    out = []
    env = os.environ.get('QMAGERY_BACKEND_DIR')
    if env:
        out.append(env)
    out.append(os.path.join(plugin_dir, 'backend'))
    out.append(os.path.normpath(os.path.join(plugin_dir, '..', '..', 'arcgis_addin', 'Install', 'backend')))
    return out


def backend_dir(plugin_dir=PLUGIN_DIR):
    candidates = backend_candidates(plugin_dir)
    for d in candidates:
        if os.path.isfile(os.path.join(d, 'run_gee.py')):
            return os.path.normpath(d)
    return os.path.normpath(candidates[0])


def run_gee_path(plugin_dir=PLUGIN_DIR):
    return os.path.join(backend_dir(plugin_dir), 'run_gee.py')


# --------------------------------------------------------------------------- arquivos do usuário
def user_config_dir():
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    d = os.path.join(base, 'ArcGEE')
    if not os.path.isdir(d):
        try:
            os.makedirs(d)
        except OSError:
            pass
    return d


def _read_json(path):
    try:
        with io.open(path, 'r', encoding='utf-8-sig') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_json(path, data):
    """Gravação atômica (temporário + rename): o ArcMagery pode estar lendo o mesmo arquivo."""
    folder = os.path.dirname(path)
    if not os.path.isdir(folder):
        os.makedirs(folder)
    fd, tmp = tempfile.mkstemp(prefix='.qmagery_', suffix='.json', dir=folder)
    try:
        with io.open(fd, 'w', encoding='utf-8') as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2))
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return True


def gee_config_file():
    return os.path.join(user_config_dir(), 'gee_config.json')


def load_gee_project():
    return (_read_json(gee_config_file()).get('project') or u'').strip()


def save_gee_project(project):
    data = _read_json(gee_config_file())
    data['project'] = (project or u'').strip()
    return _write_json(gee_config_file(), data)


def geodes_config_file():
    return os.path.join(user_config_dir(), 'geodes_config.json')


def load_geodes_key():
    """Chave salva (compartilhada com o ArcMagery); na falta dela, a variável GEODES_API_KEY."""
    key = (_read_json(geodes_config_file()).get('api_key') or u'').strip()
    return key or (os.environ.get(GEODES_KEY_ENV) or u'').strip() or None


def save_geodes_key(key):
    data = _read_json(geodes_config_file())
    data['api_key'] = (key or u'').strip()
    return _write_json(geodes_config_file(), data)


def mask_key(key):
    key = key or u''
    return (key[:4] + u'…' + key[-4:]) if len(key) > 10 else (u'•' * len(key))


def settings_file():
    return os.path.join(user_config_dir(), 'qmagery_settings.json')


def load_settings():
    out = dict(DEFAULT_SETTINGS)
    out.update(_read_json(settings_file()))
    return out


def save_settings(changes):
    data = load_settings()
    data.update(changes)
    return _write_json(settings_file(), data)


def default_output_dir():
    docs = None
    if os.name == 'nt':
        try:
            import ctypes
            from ctypes import wintypes
            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0:   # CSIDL_PERSONAL
                docs = buf.value
        except Exception:
            docs = None
    docs = docs or os.path.join(os.path.expanduser('~'), 'Documents')
    return os.path.join(docs, 'QMagery')


def output_dir(settings=None):
    settings = settings if settings is not None else load_settings()
    return (settings.get('output_dir') or u'').strip() or default_output_dir()


def system_cores():
    try:
        return os.cpu_count() or 4
    except Exception:
        return 4


def clamp_tile_threads(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = 0
    if value <= 0:
        return max(8, min(48, 4 * system_cores()))
    return max(TILE_THREADS_MIN, min(TILE_THREADS_MAX, value))


def tile_threads(settings=None):
    settings = settings if settings is not None else load_settings()
    return clamp_tile_threads(settings.get('tile_threads'))
