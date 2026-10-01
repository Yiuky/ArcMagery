# -*- coding: utf-8 -*-
"""
Ponte de Comunicacao entre ArcMap 10.8 (Python 2.7) e Backend GEE (Python 3)
"""

import os
import sys
import json
import time
import tempfile
import subprocess
import threading
import uuid

try:
    import arcpy
except ImportError:
    arcpy = None

try:
    unicode
except NameError:
    unicode = str

try:
    import arcmagery_vendor  # noqa: F401  (comtypes embutido como plano B do pip)
except ImportError:
    pass


def err_text(e):
    """Texto unicode de uma excecao. No Python 2, err_text(e) quebra com mensagens acentuadas
    (UnicodeEncodeError) e unicode(e) quebra com bytes UTF-8/cp1252 (mensagens do arcpy em pt-BR)."""
    try:
        return unicode(e)
    except UnicodeError:
        pass
    parts = []
    for a in (getattr(e, 'args', None) or (e,)):
        if isinstance(a, bytes):
            for enc in ('utf-8', 'cp1252'):
                try:
                    parts.append(a.decode(enc))
                    break
                except UnicodeError:
                    continue
            else:
                parts.append(a.decode('ascii', 'replace'))
        else:
            try:
                parts.append(unicode(a))
            except UnicodeError:
                parts.append(unicode(repr(a)))
    return u" ".join(parts) or unicode(repr(e))

class SafeStream(object):
    def __init__(self, log_path=None):
        self.log_path = log_path
    def write(self, s):
        if not self.log_path:
            return
        try:
            if os.path.exists(self.log_path) and os.path.getsize(self.log_path) > 3 * 1024 * 1024:
                try:
                    bak = self.log_path + ".bak"
                    if os.path.exists(bak): os.remove(bak)
                    os.rename(self.log_path, bak)
                except Exception:
                    pass
            with open(self.log_path, "a") as f:
                if isinstance(s, unicode):
                    s = s.encode("utf-8", "replace")
                f.write(s)
        except Exception:
            pass
    def flush(self):
        pass

def _stream_is_usable(stream):
    """Sob pythonw.exe (Python 2.7) sys.stdout EXISTE e write("") funciona, mas o descritor e
    invalido (fileno() == -2): o primeiro flush de ~4 KB levanta IOError(9, 'Bad file
    descriptor'). Streams sem fileno() (ex.: janela Python do ArcMap) sao consideradas validas."""
    if stream is None or not hasattr(stream, 'write'):
        return False
    try:
        return stream.fileno() >= 0
    except Exception:
        return True

# Redirecionar sys.stdout e sys.stderr para evitar IOError silencioso em pythonw
if not _stream_is_usable(sys.stdout):
    sys.stdout = SafeStream(os.path.join(tempfile.gettempdir(), "arcgee_bridge_stdout.log"))
if not _stream_is_usable(sys.stderr):
    sys.stderr = SafeStream(os.path.join(tempfile.gettempdir(), "arcgee_bridge_stderr.log"))

def get_user_gee_config_file():
    appdata = os.environ.get('APPDATA') or os.path.expanduser('~')
    arcgee_dir = os.path.join(appdata, 'ArcGEE')
    if not os.path.exists(arcgee_dir):
        try:
            os.makedirs(arcgee_dir)
        except Exception:
            pass
    return os.path.join(arcgee_dir, 'gee_config.json')

def load_user_gee_project():
    cfg_file = get_user_gee_config_file()
    if os.path.exists(cfg_file):
        try:
            with open(cfg_file, 'r') as f:
                return json.load(f).get('project', '')
        except Exception:
            pass
    return ""

def save_user_gee_project(project):
    cfg_file = get_user_gee_config_file()
    try:
        with open(cfg_file, 'w') as f:
            json.dump({"project": str(project).strip()}, f, indent=2)
        return True
    except Exception:
        return False

def get_esricarto_olb_path():
    """Descobre o caminho de esriCarto.olb dinamicamente a partir da instalacao do ArcGIS"""
    if arcpy:
        try:
            inst = arcpy.GetInstallInfo()
            idir = inst.get('InstallDir')
            if idir:
                p = os.path.join(idir, "com", "esriCarto.olb")
                if os.path.exists(p):
                    return p
        except Exception:
            pass
    import glob
    globs_to_check = [
        r"C:\Program Files (x86)\ArcGIS\Desktop*\com\esriCarto.olb",
        r"C:\Program Files\ArcGIS\Desktop*\com\esriCarto.olb",
        r"D:\Program Files (x86)\ArcGIS\Desktop*\com\esriCarto.olb",
        r"D:\ArcGIS\Desktop*\com\esriCarto.olb",
        r"E:\ArcGIS\Desktop*\com\esriCarto.olb",
    ]
    for pat in globs_to_check:
        matches = glob.glob(pat)
        if matches and os.path.exists(matches[0]):
            return matches[0]

    defaults = [
        r"C:\Program Files (x86)\ArcGIS\Desktop10.8\com\esriCarto.olb",
        r"C:\Program Files\ArcGIS\Desktop10.8\com\esriCarto.olb",
        r"C:\Program Files (x86)\ArcGIS\Desktop10.9\com\esriCarto.olb",
        r"C:\Program Files (x86)\ArcGIS\Desktop10.7\com\esriCarto.olb",
        r"C:\Program Files (x86)\ArcGIS\Desktop10.6\com\esriCarto.olb",
    ]
    for d in defaults:
        if os.path.exists(d):
            return d
    return r"C:\Program Files (x86)\ArcGIS\Desktop10.8\com\esriCarto.olb"

def find_python3():
    # 1. Variavel de ambiente explicita
    env_py = os.environ.get('GEE_PYTHON3')
    if env_py and os.path.exists(env_py):
        return env_py

    # 2. Configuracao salva do plugin
    try:
        settings = load_plugin_settings()
        custom_py3 = settings.get('python3_path')
        if custom_py3 and os.path.exists(custom_py3):
            return custom_py3
    except Exception:
        pass

    global _FOUND_PYTHON3
    if _FOUND_PYTHON3 and os.path.exists(_FOUND_PYTHON3):
        return _FOUND_PYTHON3

    existing = python3_candidates()
    # Preferir o primeiro interpretador que realmente possui o earthengine-api
    # (ex.: o Python do QGIS existe mas normalmente nao tem 'ee').
    for c in existing:
        if python_has_modules(c, ['ee']):
            _FOUND_PYTHON3 = c
            return c
    if existing:
        return existing[0]
    return "python.exe"

def find_python3_gdal():
    """Python 3 com GDAL (osgeo) + numpy para as fontes CBERS/INPE e Google Earth/XYZ.
    Ordem: venv do ArcMagery (criado sobre o Python do QGIS), Python do QGIS/OSGeo4W, demais.
    Se nenhum tiver GDAL, devolve o Python do GEE (o XYZ ainda funciona com Pillow + numpy)."""
    global _FOUND_PYTHON3_GDAL
    if _FOUND_PYTHON3_GDAL and os.path.exists(_FOUND_PYTHON3_GDAL):
        return _FOUND_PYTHON3_GDAL
    for c in python3_candidates():
        if python_has_modules(c, ['osgeo.gdal', 'numpy']):
            _FOUND_PYTHON3_GDAL = c
            return c
    return find_python3()

def python3_candidates():
    """Interpretadores Python 3 existentes, em ordem de preferencia (sem o alias da MS Store)."""
    import glob
    candidates = [
        os.environ.get("GEE_PYTHON3", ""),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"ArcMagery\venv\Scripts\python.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"ArcGEE\venv\Scripts\python.exe"),
        r"C:\CGMA_GEE_PLUGIN\venv\Scripts\python.exe",
    ]
    candidates += glob.glob(r"C:\Program Files\QGIS *\apps\Python3*\python.exe")
    candidates += glob.glob(r"C:\Program Files (x86)\QGIS *\apps\Python3*\python.exe")
    candidates += glob.glob(r"C:\OSGeo4W*\apps\Python3*\python.exe")
    candidates += glob.glob(r"C:\Python3*\python.exe")
    candidates += glob.glob(os.path.expanduser(r"~\AppData\Local\Programs\Python\Python3*\python.exe"))
    existing = []
    for c in candidates:
        if c and os.path.exists(c) and "WindowsApps" not in c:
            c = os.path.abspath(c)
            if c not in existing:
                existing.append(c)
    return existing

_FOUND_PYTHON3 = None
_FOUND_PYTHON3_GDAL = None
_MODULE_CHECK_CACHE = {}

def python_has_modules(py_exe, modules, timeout=40):
    """Verifica (uma vez por processo) se um interpretador Python 3 importa os modulos dados."""
    key = (py_exe, tuple(modules))
    if key in _MODULE_CHECK_CACHE:
        return _MODULE_CHECK_CACHE[key]
    ok = False
    try:
        env = dict(os.environ)
        env.pop('PYTHONPATH', None)
        env.pop('PYTHONHOME', None)
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
        code = probe_code(modules)
        proc = subprocess.Popen([py_exe, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                startupinfo=startupinfo, env=env)
        start = time.time()
        while proc.poll() is None and time.time() - start < timeout:
            time.sleep(0.1)
        if proc.poll() is None:
            proc.kill()
        else:
            ok = (proc.returncode == 0)
    except Exception:
        ok = False
    _MODULE_CHECK_CACHE[key] = ok
    return ok

def probe_code(modules):
    """Codigo do teste de modulos: ativa antes as bibliotecas instaladas sem pip (backend/pylibs.py),
    para que o Python do QGIS sem 'ee' proprio conte como apto ao GEE."""
    backend = os.path.dirname(get_backend_script())
    return ("import sys; sys.path.insert(0, %r)\n"
            "try:\n    import pylibs; pylibs.activate()\nexcept Exception:\n    pass\n"
            "import %s; sys.exit(0 if sys.version_info[0] == 3 else 1)" % (str(backend), ", ".join(modules)))


def reset_python_cache():
    """Esquece o Python 3 escolhido e os testes de modulos (apos instalar componentes)."""
    global _FOUND_PYTHON3, _FOUND_PYTHON3_GDAL
    _FOUND_PYTHON3 = None
    _FOUND_PYTHON3_GDAL = None
    _MODULE_CHECK_CACHE.clear()


def install_ee_components(on_progress=None):
    """Instala o earthengine-api sem pip (backend 'pylibs_install') no Python 3 com GDAL."""
    resp = run_backend_cmd('pylibs_install', {}, on_progress=on_progress, python_exe=find_python3_gdal())
    reset_python_cache()
    return resp


def get_backend_script():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # 1. Subpasta backend dentro de Install (Add-In autocontido no AssemblyCache)
    p0 = os.path.join(current_dir, "backend", "run_gee.py")
    if os.path.exists(p0):
        return os.path.abspath(p0)

    # 2. Na raiz do repositorio (backend/run_gee.py)
    p1 = os.path.join(current_dir, "..", "..", "backend", "run_gee.py")
    if os.path.exists(p1):
        return os.path.abspath(p1)

    p1_alt = os.path.join(current_dir, "..", "backend", "run_gee.py")
    if os.path.exists(p1_alt):
        return os.path.abspath(p1_alt)

    # 3. Na mesma pasta
    p2 = os.path.join(current_dir, "run_gee.py")
    if os.path.exists(p2):
        return os.path.abspath(p2)

    return os.path.abspath(p0)

# Definicoes locais de composicoes de bandas para resposta instantanea (zero subprocessos ao abrir janela)
COMPOSITIONS = {
    'L8': {
        '432': {'label': 'COR NATURAL - 432', 'bands': ['SR_B4', 'SR_B3', 'SR_B2']},
        '764': {'label': 'FALSA COR - 764', 'bands': ['SR_B7', 'SR_B6', 'SR_B4']},
        '543': {'label': 'COR INFRAVERMELHA (VEGETACAO) - 543', 'bands': ['SR_B5', 'SR_B4', 'SR_B3']},
        '652': {'label': 'AGRICULTURA - 652', 'bands': ['SR_B6', 'SR_B5', 'SR_B2']},
        '765': {'label': 'PENETRACAO ATMOSFERICA - 765', 'bands': ['SR_B7', 'SR_B6', 'SR_B5']},
        '562': {'label': 'SAUDE DA VEGETACAO - 562', 'bands': ['SR_B5', 'SR_B6', 'SR_B2']},
        '564': {'label': 'SOLO/AGUA - 564', 'bands': ['SR_B5', 'SR_B6', 'SR_B4']},
        '753': {'label': 'NATURAL COM REMOCAO ATMOSFERICA - 753', 'bands': ['SR_B7', 'SR_B5', 'SR_B3']},
        '754': {'label': 'INFRAVERMELHO ONDA CURTA - 754', 'bands': ['SR_B7', 'SR_B5', 'SR_B4']},
        '654': {'label': 'ANALISE DA VEGETACAO - 654', 'bands': ['SR_B6', 'SR_B5', 'SR_B4']},
        'MB_8': {'label': 'MULTIBANDA - 8 BANDAS (SR_B1 a SR_B7 + ST_B10 Termica)', 'bands': ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6', 'SR_B7', 'ST_B10'], 'multiband': True},
        'MB_7': {'label': 'MULTIBANDA - 7 BANDAS OPTICAS (SR_B1 a SR_B7)', 'bands': ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6', 'SR_B7'], 'multiband': True},
        'MB_6': {'label': 'MULTIBANDA - 6 BANDAS PRINCIPAIS (SR_B2 a SR_B7)', 'bands': ['SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6', 'SR_B7'], 'multiband': True},
        '10':   {'label': 'TERMICA - BANDA 10 (Temperatura de Superficie em C)', 'bands': ['ST_B10'], 'is_index': True},
        'NDVI': {'label': 'INDICE - NDVI (Vegetacao: NIR-RED)', 'bands': ['SR_B5', 'SR_B4'], 'is_index': True},
        'NDWI': {'label': 'INDICE - NDWI (Agua: GREEN-NIR)', 'bands': ['SR_B3', 'SR_B5'], 'is_index': True},
        'NDMI': {'label': 'INDICE - NDMI (Umidade: NIR-SWIR1)', 'bands': ['SR_B5', 'SR_B6'], 'is_index': True},
        'NBR':  {'label': 'INDICE - NBR (Queimadas: NIR-SWIR2)', 'bands': ['SR_B5', 'SR_B7'], 'is_index': True},
        'EVI':  {'label': 'INDICE - EVI (Vegetacao Realcada)', 'bands': ['SR_B5', 'SR_B4', 'SR_B2'], 'is_index': True},
        'SAVI': {'label': 'INDICE - SAVI (Ajustado ao Solo)', 'bands': ['SR_B5', 'SR_B4'], 'is_index': True},
        'CUSTOM_BANDS': {'label': 'BANDAS PERSONALIZADAS (Digite na caixa abaixo: ex: SR_B5,SR_B4,SR_B3)', 'bands': []},
        'CUSTOM_MATH': {'label': 'INDICE - FORMULA MATEMATICA (ex: (SR_B5-SR_B4)/(SR_B5+SR_B4))', 'bands': [], 'is_index': True, 'is_custom': True}
    },
    'L7': {
        '321': {'label': 'COR NATURAL - 321', 'bands': ['SR_B3', 'SR_B2', 'SR_B1']},
        '753': {'label': 'FALSA COR - 753', 'bands': ['SR_B7', 'SR_B5', 'SR_B3']},
        '432': {'label': 'COR INFRAVERMELHA (VEGETACAO) - 432', 'bands': ['SR_B4', 'SR_B3', 'SR_B2']},
        '541': {'label': 'AGRICULTURA - 541', 'bands': ['SR_B5', 'SR_B4', 'SR_B1']},
        '754': {'label': 'PENETRACAO ATMOSFERICA - 754', 'bands': ['SR_B7', 'SR_B5', 'SR_B4']},
        '451': {'label': 'SAUDE DA VEGETACAO - 451', 'bands': ['SR_B4', 'SR_B5', 'SR_B1']},
        '453': {'label': 'SOLO/AGUA - 453', 'bands': ['SR_B4', 'SR_B5', 'SR_B3']},
        '742': {'label': 'NATURAL COM REMOCAO ATMOSFERICA - 742', 'bands': ['SR_B7', 'SR_B4', 'SR_B2']},
        '743': {'label': 'INFRAVERMELHO ONDA CURTA - 743', 'bands': ['SR_B7', 'SR_B4', 'SR_B3']},
        '543': {'label': 'ANALISE DA VEGETACAO - 543', 'bands': ['SR_B5', 'SR_B4', 'SR_B3']},
        'MB_7': {'label': 'MULTIBANDA - 7 BANDAS (SR_B1 a SR_B5, SR_B7 + ST_B6 Termica)', 'bands': ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B7', 'ST_B6'], 'multiband': True},
        'MB_6': {'label': 'MULTIBANDA - 6 BANDAS OPTICAS (SR_B1 a SR_B5, SR_B7)', 'bands': ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B7'], 'multiband': True},
        '6':    {'label': 'TERMICA - BANDA 6 (Temperatura de Superficie em C)', 'bands': ['ST_B6'], 'is_index': True},
        'NDVI': {'label': 'INDICE - NDVI (Vegetacao: NIR-RED)', 'bands': ['SR_B4', 'SR_B3'], 'is_index': True},
        'NDWI': {'label': 'INDICE - NDWI (Agua: GREEN-NIR)', 'bands': ['SR_B2', 'SR_B4'], 'is_index': True},
        'NDMI': {'label': 'INDICE - NDMI (Umidade: NIR-SWIR1)', 'bands': ['SR_B4', 'SR_B5'], 'is_index': True},
        'NBR':  {'label': 'INDICE - NBR (Queimadas: NIR-SWIR2)', 'bands': ['SR_B4', 'SR_B7'], 'is_index': True},
        'EVI':  {'label': 'INDICE - EVI (Vegetacao Realcada)', 'bands': ['SR_B4', 'SR_B3', 'SR_B1'], 'is_index': True},
        'SAVI': {'label': 'INDICE - SAVI (Ajustado ao Solo)', 'bands': ['SR_B4', 'SR_B3'], 'is_index': True},
        'CUSTOM_BANDS': {'label': 'BANDAS PERSONALIZADAS (Digite na caixa abaixo: ex: SR_B4,SR_B3,SR_B2)', 'bands': []},
        'CUSTOM_MATH': {'label': 'INDICE - FORMULA MATEMATICA (ex: (SR_B4-SR_B3)/(SR_B4+SR_B3))', 'bands': [], 'is_index': True, 'is_custom': True}
    },
    'L5': {
        '321': {'label': 'COR NATURAL - 321', 'bands': ['SR_B3', 'SR_B2', 'SR_B1']},
        '753': {'label': 'FALSA COR - 753', 'bands': ['SR_B7', 'SR_B5', 'SR_B3']},
        '432': {'label': 'COR INFRAVERMELHA (VEGETACAO) - 432', 'bands': ['SR_B4', 'SR_B3', 'SR_B2']},
        '541': {'label': 'AGRICULTURA - 541', 'bands': ['SR_B5', 'SR_B4', 'SR_B1']},
        '754': {'label': 'PENETRACAO ATMOSFERICA - 754', 'bands': ['SR_B7', 'SR_B5', 'SR_B4']},
        '451': {'label': 'SAUDE DA VEGETACAO - 451', 'bands': ['SR_B4', 'SR_B5', 'SR_B1']},
        '453': {'label': 'SOLO/AGUA - 453', 'bands': ['SR_B4', 'SR_B5', 'SR_B3']},
        '742': {'label': 'NATURAL COM REMOCAO ATMOSFERICA - 742', 'bands': ['SR_B7', 'SR_B4', 'SR_B2']},
        '743': {'label': 'INFRAVERMELHO ONDA CURTA - 743', 'bands': ['SR_B7', 'SR_B4', 'SR_B3']},
        '543': {'label': 'ANALISE DA VEGETACAO - 543', 'bands': ['SR_B5', 'SR_B4', 'SR_B3']},
        'MB_7': {'label': 'MULTIBANDA - 7 BANDAS (SR_B1 a SR_B5, SR_B7 + ST_B6 Termica)', 'bands': ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B7', 'ST_B6'], 'multiband': True},
        'MB_6': {'label': 'MULTIBANDA - 6 BANDAS OPTICAS (SR_B1 a SR_B5, SR_B7)', 'bands': ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B7'], 'multiband': True},
        '6':    {'label': 'TERMICA - BANDA 6 (Temperatura de Superficie em C)', 'bands': ['ST_B6'], 'is_index': True},
        'NDVI': {'label': 'INDICE - NDVI (Vegetacao: NIR-RED)', 'bands': ['SR_B4', 'SR_B3'], 'is_index': True},
        'NDWI': {'label': 'INDICE - NDWI (Agua: GREEN-NIR)', 'bands': ['SR_B2', 'SR_B4'], 'is_index': True},
        'NDMI': {'label': 'INDICE - NDMI (Umidade: NIR-SWIR1)', 'bands': ['SR_B4', 'SR_B5'], 'is_index': True},
        'NBR':  {'label': 'INDICE - NBR (Queimadas: NIR-SWIR2)', 'bands': ['SR_B4', 'SR_B7'], 'is_index': True},
        'EVI':  {'label': 'INDICE - EVI (Vegetacao Realcada)', 'bands': ['SR_B4', 'SR_B3', 'SR_B1'], 'is_index': True},
        'SAVI': {'label': 'INDICE - SAVI (Ajustado ao Solo)', 'bands': ['SR_B4', 'SR_B3'], 'is_index': True},
        'CUSTOM_BANDS': {'label': 'BANDAS PERSONALIZADAS (Digite na caixa abaixo: ex: SR_B4,SR_B3,SR_B2)', 'bands': []},
        'CUSTOM_MATH': {'label': 'INDICE - FORMULA MATEMATICA (ex: (SR_B4-SR_B3)/(SR_B4+SR_B3))', 'bands': [], 'is_index': True, 'is_custom': True}
    },
    'L1': {
        '754': {'label': 'FALSA COR INFRAVERMELHA (PADRAO MSS) - 754', 'bands': ['B7', 'B5', 'B4']},
        '654': {'label': 'FALSA COR VEGETACAO - 654', 'bands': ['B6', 'B5', 'B4']},
        '764': {'label': 'PENETRACAO/SOLO - 764', 'bands': ['B7', 'B6', 'B4']},
        '765': {'label': 'ANALISE DE BIOMASSA - 765', 'bands': ['B7', 'B6', 'B5']},
        'MB_4': {'label': 'MULTIBANDA - 4 BANDAS MSS (B4, B5, B6, B7)', 'bands': ['B4', 'B5', 'B6', 'B7'], 'multiband': True},
        'NDVI': {'label': 'INDICE - NDVI (Vegetacao: B7-B5)', 'bands': ['B7', 'B5'], 'is_index': True},
        'NDWI': {'label': 'INDICE - NDWI (Agua: B4-B7)', 'bands': ['B4', 'B7'], 'is_index': True},
        'CUSTOM_BANDS': {'label': 'BANDAS PERSONALIZADAS (Digite na caixa abaixo: ex: B7,B5,B4)', 'bands': []},
        'CUSTOM_MATH': {'label': 'INDICE - FORMULA MATEMATICA (ex: (B7-B5)/(B7+B5))', 'bands': [], 'is_index': True, 'is_custom': True}
    },
    'S2': {
        '432': {'label': 'COR NATURAL - 4.3.2', 'bands': ['B4', 'B3', 'B2']},
        '12114': {'label': 'FALSA COR - 12.11.4', 'bands': ['B12', 'B11', 'B4']},
        '843': {'label': 'COR INFRAVERMELHA (VEGETACAO) - 8.4.3', 'bands': ['B8', 'B4', 'B3']},
        '8a43': {'label': 'COR INFRAVERMELHA (VEGETACAO) - 8a.4.3', 'bands': ['B8A', 'B4', 'B3']},
        '1182': {'label': 'AGRICULTURA - 11.8.2', 'bands': ['B11', 'B8', 'B2']},
        '118a2': {'label': 'AGRICULTURA - 11.8a.2', 'bands': ['B11', 'B8A', 'B2']},
        '12118': {'label': 'PENETRACAO ATMOSFERICA - 12.11.8', 'bands': ['B12', 'B11', 'B8']},
        '12118a': {'label': 'PENETRACAO ATMOSFERICA - 12.11.8a', 'bands': ['B12', 'B11', 'B8A']},
        '8112': {'label': 'SAUDE DA VEGETACAO - 8.11.2', 'bands': ['B8', 'B11', 'B2']},
        '8a112': {'label': 'SAUDE DA VEGETACAO - 8a.11.2', 'bands': ['B8A', 'B11', 'B2']},
        '8114': {'label': 'SOLO/AGUA - 8.11.4', 'bands': ['B8', 'B11', 'B4']},
        '8a114': {'label': 'SOLO/AGUA - 8a.11.4', 'bands': ['B8A', 'B11', 'B4']},
        '1283': {'label': 'NATURAL COM REMOCAO ATMOSFERICA - 12.8.3', 'bands': ['B12', 'B8', 'B3']},
        '128a3': {'label': 'NATURAL COM REMOCAO ATMOSFERICA - 12.8a.3', 'bands': ['B12', 'B8A', 'B3']},
        '1284': {'label': 'INFRAVERMELHO ONDA CURTA - 12.8.4', 'bands': ['B12', 'B8', 'B4']},
        '128a4': {'label': 'INFRAVERMELHO ONDA CURTA - 12.8a.4', 'bands': ['B12', 'B8A', 'B4']},
        '1184': {'label': 'ANALISE DA VEGETACAO - 11.8.4', 'bands': ['B11', 'B8', 'B4']},
        '118a4': {'label': 'ANALISE DA VEGETACAO - 11.8a.4', 'bands': ['B11', 'B8A', 'B4']},
        '483': {'label': 'ANALISE DA VEGETACAO - 4.8.3', 'bands': ['B4', 'B8', 'B3']},
        'MB_10': {'label': 'MULTIBANDA - 10 BANDAS PRINCIPAIS (B2 a B12)', 'bands': ['B2', 'B3', 'B4', 'B5', 'B6', 'B7', 'B8', 'B8A', 'B11', 'B12'], 'multiband': True},
        'MB_6': {'label': 'MULTIBANDA - 6 BANDAS VNIR/SWIR (B2, B3, B4, B8, B11, B12)', 'bands': ['B2', 'B3', 'B4', 'B8', 'B11', 'B12'], 'multiband': True},
        'MB_12': {'label': 'MULTIBANDA - 12 BANDAS COMPLETAS (B1 a B12)', 'bands': ['B1', 'B2', 'B3', 'B4', 'B5', 'B6', 'B7', 'B8', 'B8A', 'B9', 'B11', 'B12'], 'multiband': True},
        'NDVI': {'label': 'INDICE - NDVI (Vegetacao: B8-B4)', 'bands': ['B8', 'B4'], 'is_index': True},
        'NDWI': {'label': 'INDICE - NDWI (Agua: B3-B8)', 'bands': ['B3', 'B8'], 'is_index': True},
        'NDMI': {'label': 'INDICE - NDMI (Umidade: B8-B11)', 'bands': ['B8', 'B11'], 'is_index': True},
        'NBR':  {'label': 'INDICE - NBR (Queimadas: B8-B12)', 'bands': ['B8', 'B12'], 'is_index': True},
        'EVI':  {'label': 'INDICE - EVI (Vegetacao Realcada)', 'bands': ['B8', 'B4', 'B2'], 'is_index': True},
        'SAVI': {'label': 'INDICE - SAVI (Ajustado ao Solo)', 'bands': ['B8', 'B4'], 'is_index': True},
        'CUSTOM_BANDS': {'label': 'BANDAS PERSONALIZADAS (Digite na caixa abaixo: ex: B8,B4,B3)', 'bands': []},
        'CUSTOM_MATH': {'label': 'INDICE - FORMULA MATEMATICA (ex: (B8-B4)/(B8+B4))', 'bands': [], 'is_index': True, 'is_custom': True}
    }
}
COMPOSITIONS['L4'] = COMPOSITIONS['L5']
COMPOSITIONS['L3'] = COMPOSITIONS['L1']
COMPOSITIONS['L2'] = COMPOSITIONS['L1']

MULTIBAND_DEFAULT_BANDS = {
    'S2': ['B1', 'B2', 'B3', 'B4', 'B5', 'B6', 'B7', 'B8', 'B8A', 'B9', 'B11', 'B12'],
    'L8': ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6', 'SR_B7', 'ST_B10'],
    'L7': ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B7', 'ST_B6'],
    'L5': ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B7', 'ST_B6'],
    'L4': ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B7', 'ST_B6'],
    'L3': ['B4', 'B5', 'B6', 'B7'],
    'L2': ['B4', 'B5', 'B6', 'B7'],
    'L1': ['B4', 'B5', 'B6', 'B7']
}

# Backends em execucao (para o botao Interromper) e prazo apos o resultado chegar
_ACTIVE_BACKENDS = {}
_ACTIVE_LOCK = threading.Lock()
RESULT_GRACE_SECONDS = 5.0
CANCELLED_MESSAGE = u"Interrompido pelo usuário."


def kill_process_tree(proc):
    """Encerra o processo E os filhos: o python.exe do venv e um lancador que inicia o Python real;
    proc.kill() so matava o lancador e deixava o backend orfao."""
    try:
        if os.name == 'nt':
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE
            with open(os.devnull, 'w') as devnull:
                tk_proc = subprocess.Popen(['taskkill', '/PID', str(proc.pid), '/T', '/F'], stdout=devnull,
                                           stderr=devnull, startupinfo=si)
                deadline = time.time() + 5.0   # nunca prender a interface esperando o taskkill
                while tk_proc.poll() is None and time.time() < deadline:
                    time.sleep(0.1)
        if proc.poll() is None:
            proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


MAIN_GROUP = 'main'


def cancel_backend_commands(group=MAIN_GROUP):
    """Interrompe os comandos do backend do grupo (a janela principal nao encerra os da janela
    Mosaicos XYZ). Nao bloqueia: o encerramento (taskkill, ate 5 s por processo) roda em threads;
    run_backend_cmd ja devolve 'cancelado' ao ver a marca. Retorna quantos foram interrompidos."""
    with _ACTIVE_LOCK:
        items = [(proc, st) for proc, st in _ACTIVE_BACKENDS.items() if st.get('group') == group]
    for proc, state in items:
        state['cancelled'] = True
        t = threading.Thread(target=kill_process_tree, args=(proc,))
        t.daemon = True
        t.start()
    return len(items)


def active_backend_count(group=MAIN_GROUP):
    with _ACTIVE_LOCK:
        return len([1 for st in _ACTIVE_BACKENDS.values() if st.get('group') == group])


def parse_backend_output(out):
    """Ultima linha JSON do stdout (contrato do backend) ou None."""
    for line in reversed(out.strip().splitlines()):
        line_str = line.decode('utf-8', 'ignore') if hasattr(line, 'decode') else str(line)
        line_str = line_str.strip()
        if line_str.startswith('{') and line_str.endswith('}'):
            try:
                return json.loads(line_str)
            except Exception:
                pass
    return None


def run_backend_cmd(subcmd, args_dict, on_progress=None, python_exe=None, group=MAIN_GROUP):
    py3 = python_exe or find_python3()
    script = get_backend_script()
    if not os.path.exists(script):
        return {'success': False, 'message': u"Script backend nao encontrado: " + unicode(script)}

    # Passagem de parametros via arquivo JSON UTF-8 com caminho 8.3 puro ASCII
    # para imunidade absoluta contra erros de encoding e caminhos com acentos (ex: C:\Users\José)
    params_payload = dict(args_dict)
    params_payload['command'] = subcmd

    import io
    temp_json = tempfile.NamedTemporaryFile(suffix='.json', prefix='gee_params_', delete=False)
    temp_json_path = temp_json.name
    temp_json.close()

    try:
        with io.open(temp_json_path, 'w', encoding='utf-8') as f_json:
            json_str = json.dumps(params_payload, ensure_ascii=False)
            if not isinstance(json_str, unicode):
                json_str = unicode(json_str, 'utf-8', 'replace')
            f_json.write(json_str)

        safe_json_path = temp_json_path
        if os.name == 'nt':
            try:
                import ctypes
                buf = ctypes.create_unicode_buffer(500)
                if ctypes.windll.kernel32.GetShortPathNameW(unicode(temp_json_path), buf, 500) > 0:
                    safe_json_path = str(buf.value)
            except Exception:
                safe_json_path = temp_json_path.encode('ascii', 'ignore') if isinstance(temp_json_path, unicode) else temp_json_path

        cmd = [str(py3), str(script), str(subcmd), "--params-file=" + str(safe_json_path)]

        # Sanitizar variaveis de ambiente para isolar Python 3 do ambiente Python 2 do ArcMap
        clean_env = dict(os.environ)
        clean_env.pop('PYTHONPATH', None)
        clean_env.pop('PYTHONHOME', None)
        clean_env['PYTHONUNBUFFERED'] = '1'
        clean_env['PYTHONIOENCODING'] = 'utf-8'  # stderr/stdout do backend sempre em UTF-8

        # Configurar para nao abrir janela preta do cmd
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            startupinfo=startupinfo,
            env=clean_env
        )

        out_chunks = []
        err_chunks = []

        def _stream_out():
            try:
                for raw_line in iter(proc.stdout.readline, b''):
                    out_chunks.append(raw_line)
            except Exception:
                pass
            finally:
                try:
                    proc.stdout.close()
                except Exception:
                    pass

        def _stream_err():
            try:
                for raw_line in iter(proc.stderr.readline, b''):
                    err_chunks.append(raw_line)
                    try:
                        s = raw_line.decode('utf-8', 'ignore') if hasattr(raw_line, 'decode') else raw_line
                        if '[ArcGEE]' in s and on_progress:
                            on_progress(s.strip())
                    except Exception:
                        pass
            except Exception:
                pass
            finally:
                try:
                    proc.stderr.close()
                except Exception:
                    pass

        t_out = threading.Thread(target=_stream_out)
        t_out.daemon = True
        t_out.start()

        t_err = threading.Thread(target=_stream_err)
        t_err.daemon = True
        t_err.start()

        # Timeout adaptativo por operacao para evitar travamentos silenciosos
        if subcmd == 'download':
            timeout_seconds = 600  # 10 minutos para download e processamento de grandes rasters
        elif subcmd in ('check', 'auth', 'compositions'):
            timeout_seconds = 30   # 30 segundos para checagens basicas
        elif subcmd == 'search':
            timeout_seconds = 90   # 90 segundos para busca no catalogo GEE
        elif subcmd == 'thumb':
            timeout_seconds = 60   # 60 segundos para miniaturas
        elif subcmd == 'stac_download':
            timeout_seconds = 1800  # 30 minutos: recortes CBERS grandes
        elif subcmd in ('xyz_download', 'gehist_download'):
            timeout_seconds = 4 * 3600  # ate 100 mil tiles (~30 tiles/s em rede corporativa: ~1 h)
        elif subcmd == 'gehist_dates':
            timeout_seconds = 1800  # varredura do catalogo historico (1 consulta por tile)
        elif subcmd in ('gehist_thumb', 'wayback_thumb'):
            timeout_seconds = 120
        elif subcmd == 'esri_versions':
            timeout_seconds = 600   # varios zooms do Wayback (cada um ~15-20 s)
        elif subcmd in ('stac_search', 'stac_thumb', 'sources_info', 'xyz_estimate', 'esri_dates'):
            timeout_seconds = 120
        else:
            timeout_seconds = 120

        state = {'cancelled': False, 'group': group}
        with _ACTIVE_LOCK:
            _ACTIVE_BACKENDS[proc] = state
        start_time = time.time()
        timed_out = False
        result_seen = None
        seen_lines = 0
        try:
            while proc.poll() is None:
                time.sleep(0.1)
                if state['cancelled']:
                    break
                # Resultado ja entregue: nao esperar o encerramento do interpretador (o GDAL/curl pode
                # travar a saida por muitos minutos depois de gravar o arquivo - visto no CBERS-2).
                # So examina as linhas novas (a saida inteira nao e relida a cada 100 ms).
                n = len(out_chunks)
                if result_seen is None and n > seen_lines:
                    if any(parse_backend_output(c) is not None for c in out_chunks[seen_lines:n]):
                        result_seen = time.time()
                    seen_lines = n
                if result_seen is not None and time.time() - result_seen > RESULT_GRACE_SECONDS:
                    _log_debug(u"run_backend_cmd(%s): resultado recebido, processo nao encerrou; finalizando." % subcmd)
                    kill_process_tree(proc)
                    break
                if time.time() - start_time > timeout_seconds:
                    timed_out = True
                    kill_process_tree(proc)
                    break
        finally:
            with _ACTIVE_LOCK:
                _ACTIVE_BACKENDS.pop(proc, None)

        t_out.join(timeout=2.0)
        t_err.join(timeout=2.0)

        out = b"".join(out_chunks)
        err = b"".join(err_chunks)

        if state['cancelled']:
            return {'success': False, 'cancelled': True, 'message': CANCELLED_MESSAGE}

        if timed_out:
            return {'success': False, 'message': u"Tempo limite excedido na operacao '%s' (%d s)." % (subcmd, timeout_seconds)}

        if proc.returncode not in (0, None) and not out.strip():
            err_msg = err if isinstance(err, unicode) else unicode(str(err), errors='ignore') if hasattr(str, 'decode') else str(err)
            return {'success': False, 'message': u"Erro executando backend (codigo %d): %s" % (proc.returncode, err_msg)}

        # Filtrar saida para encontrar a linha JSON valida (procura de tras para frente)
        data = parse_backend_output(out)

        if data is None:
            raw_preview = out[:300].decode('utf-8', 'ignore') if hasattr(out, 'decode') else str(out[:300])
            err_preview = err[:300].decode('utf-8', 'ignore') if hasattr(err, 'decode') else str(err[:300])
            return {'success': False, 'message': u"Resposta invalida do backend GEE: %s (stderr: %s)" % (raw_preview, err_preview)}

        return data
    except Exception as e:
        return {'success': False, 'message': u"Excecao na execucao do backend: " + unicode(e)}
    finally:
        try:
            if os.path.exists(temp_json_path):
                os.remove(temp_json_path)
        except Exception:
            pass

def check_gee(project=None):
    if not project:
        project = load_user_gee_project()
    return run_backend_cmd("check", {"project": project})

def authenticate_gee(project=None):
    if not project:
        project = load_user_gee_project()
    return run_backend_cmd("auth", {"project": project})

def launch_auth_console(project=None):
    """Abre uma janela de console interativa com earthengine authenticate para o usuario logar no navegador"""
    # Python 3 + backend/ee_auth.py: funciona sem venv (earthengine-api instalado sem pip, pylibs)
    py3 = find_python3()
    auth_script = os.path.join(os.path.dirname(get_backend_script()), "ee_auth.py")

    # Salvar projeto na config isolada de usuario (%APPDATA%\ArcGEE) se fornecido
    if project:
        save_user_gee_project(project)

    cmd = 'start "Google Earth Engine - Autenticacao" cmd /k ""%s" "%s" %s & pause"' % (
        py3, auth_script, (project or "").replace('"', ''))
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)   # nunca herdar o Python 2.7 do ArcGIS no Python 3
    env.pop('PYTHONHOME', None)
    try:
        subprocess.Popen(cmd, shell=True, env=env)
        return True, "Janela de autenticacao aberta. Siga as instrucoes no navegador."
    except Exception as e:
        return False, err_text(e)

def get_compositions(sensor):
    comps = COMPOSITIONS.get(sensor, {})
    return {'success': True, 'compositions': comps}

def search_images(sensor, start_date, end_date, bbox=None, geojson_file=None, path=None, row=None, mgrs=None, max_images=100, project=None):
    bbox_str = ",".join(str(x) for x in bbox) if bbox else None
    return run_backend_cmd("search", {
        "sensor": sensor,
        "start_date": start_date,
        "end_date": end_date,
        "bbox": bbox_str,
        "geojson_file": geojson_file,
        "path": path,
        "row": row,
        "mgrs": mgrs,
        "max_images": max_images,
        "project": project
    })

def get_thumbnail(image_id, sensor, comp_code, out_png, bbox=None, project=None):
    bbox_str = ",".join(str(x) for x in bbox) if bbox else None
    return run_backend_cmd("thumb", {
        "image_id": image_id,
        "sensor": sensor,
        "comp": comp_code,
        "out": out_png,
        "bbox": bbox_str,
        "project": project
    })

def download_image(image_ids, sensor, comp_code, out_tif, custom_bands=None, load_mode="multiband", bbox=None, geojson_file=None, scale=None, crs="EPSG:4674", project=None, on_progress=None):
    ids_str = ",".join(image_ids) if isinstance(image_ids, (list, tuple)) else str(image_ids)
    bbox_str = ",".join(str(x) for x in bbox) if bbox else None
    return run_backend_cmd("download", {
        "ids": ids_str,
        "sensor": sensor,
        "comp": comp_code,
        "custom_bands": custom_bands,
        "load_mode": load_mode,
        "out": out_tif,
        "bbox": bbox_str,
        "geojson_file": geojson_file,
        "scale": scale,
        "crs": crs,
        "project": project
    }, on_progress=on_progress)

def get_arcmap_scale():
    """Retorna o denominador da escala do mapa atual do ArcMap (ex: 250000 para 1:250.000)"""
    if not arcpy:
        return None
    try:
        mxd = arcpy.mapping.MapDocument("CURRENT")
        df = arcpy.mapping.ListDataFrames(mxd)[0]
        return df.scale
    except Exception:
        return None

def set_arcmap_scale(new_scale):
    """Ajusta a escala do mapa no ArcMap para um valor especifico (ex: 500000 para 1:500.000)"""
    if not arcpy:
        return False, "ArcPy nao disponivel."
    try:
        mxd = arcpy.mapping.MapDocument("CURRENT")
        df = arcpy.mapping.ListDataFrames(mxd)[0]
        df.scale = float(new_scale)
        arcpy.RefreshActiveView()
        export_arcmap_context()
        return True, "Escala ajustada para 1:{:,.0f}".format(float(new_scale))
    except Exception as e:
        return False, "Erro ao ajustar escala: " + err_text(e)

def get_arcmap_extent_wgs84():
    """Retorna [minx, miny, maxx, maxy] da tela ativa do ArcMap em WGS84 (graus decimais).
    Garante que coordenadas projetadas (UTM, SIRGAS, etc.) sejam sempre convertidas corretamente para EPSG:4326.
    """
    if not arcpy:
        return None
    try:
        import math
        mxd = arcpy.mapping.MapDocument("CURRENT")
        df = arcpy.mapping.ListDataFrames(mxd)[0]
        ext = df.extent
        if not ext:
            return None

        sr_wgs84 = arcpy.SpatialReference(4326)

        # 1. Determinar o SpatialReference ativo (do extent ou do data frame)
        sr = getattr(ext, 'spatialReference', None)
        if not sr or not getattr(sr, 'name', '').strip() or getattr(sr, 'name', '') == "Unknown":
            sr = getattr(df, 'spatialReference', None)
            if sr and getattr(sr, 'name', '').strip() and getattr(sr, 'name', '') != "Unknown":
                try:
                    ext.spatialReference = sr
                except Exception:
                    pass

        # 2. Se ja for WGS84 ou coordenadas geograficas com valores compativeis (-180..180, -90..90)
        xmin, ymin, xmax, ymax = float(ext.XMin), float(ext.YMin), float(ext.XMax), float(ext.YMax)
        is_already_wgs = False
        if sr and (getattr(sr, 'factoryCode', None) == 4326 or ('wgs' in getattr(sr, 'name', '').lower() and '1984' in getattr(sr, 'name', ''))):
            is_already_wgs = True
        elif abs(xmin) <= 180.0 and abs(xmax) <= 180.0 and abs(ymin) <= 90.0 and abs(ymax) <= 90.0:
            is_already_wgs = True

        if is_already_wgs:
            return [xmin, ymin, xmax, ymax]

        # 3. Converter para WGS84 via projectAs
        if sr and getattr(sr, 'name', '') != "Unknown":
            try:
                ext_wgs = ext.projectAs(sr_wgs84)
                if ext_wgs:
                    wx1, wy1, wx2, wy2 = float(ext_wgs.XMin), float(ext_wgs.YMin), float(ext_wgs.XMax), float(ext_wgs.YMax)
                    if not any(math.isnan(v) for v in (wx1, wy1, wx2, wy2)):
                        if abs(wx1) <= 180.0 and abs(wx2) <= 180.0 and abs(wy1) <= 90.0 and abs(wy2) <= 90.0:
                            return [wx1, wy1, wx2, wy2]
            except Exception as e_proj:
                _log_debug("projectAs falhou: " + str(e_proj))

        # 4. Failsafe: se as coordenadas brutas ja estiverem em graus
        if abs(xmin) <= 180.0 and abs(xmax) <= 180.0 and abs(ymin) <= 90.0 and abs(ymax) <= 90.0:
            return [xmin, ymin, xmax, ymax]

        _log_debug("get_arcmap_extent_wgs84: coordenadas fora do intervalo WGS84: [%s, %s, %s, %s]" % (xmin, ymin, xmax, ymax))
        return None
    except Exception as e:
        _log_debug("Erro obtendo extensao ArcMap: " + err_text(e))
        return None

def get_arcmap_layers():
    """Lista camadas vetoriais disponiveis no TOC do ArcMap"""
    if not arcpy:
        return []
    try:
        mxd = arcpy.mapping.MapDocument("CURRENT")
        layers = arcpy.mapping.ListLayers(mxd)
        return [lyr.name for lyr in layers if lyr.isFeatureLayer]
    except Exception:
        return []

def get_arcmap_raster_layers():
    """Lista todas as camadas raster presentes no TOC do ArcMap para mapeamento e substituicao"""
    if not arcpy:
        return []
    try:
        mxd = arcpy.mapping.MapDocument("CURRENT")
        layers = arcpy.mapping.ListLayers(mxd)
        rasters = []
        for lyr in layers:
            if not lyr.isGroupLayer and lyr.isRasterLayer:
                rasters.append(lyr.longName)
        return rasters
    except Exception as e:
        print("Erro listando camadas raster:", e)
        return []

def get_arcmap_toc_groups():
    """Lista todos os nomes de grupos de camadas (Group Layers) presentes no TOC"""
    if not arcpy:
        return []
    groups = []
    try:
        mxd = arcpy.mapping.MapDocument("CURRENT")
        layers = arcpy.mapping.ListLayers(mxd)
        for lyr in layers:
            try:
                if getattr(lyr, 'isGroupLayer', False):
                    n = getattr(lyr, 'name', None)
                    if n and n not in groups:
                        groups.append(n)
            except Exception:
                pass
    except Exception:
        pass
    return groups

def build_toc_targets(r_layers, groups_with_rasters=None):
    """Gera a lista padronizada e robusta de alvos do TOC:
    1. [Todo o TOC] (se houver rasters)
    2. [Grupo] <nome_do_grupo> (para todos os grupos que contêm rasters)
    3. <nome_da_camada> (para cada camada raster individual)
    Extrai grupos tanto da lista informada quanto diretamente do caminho hierárquico (longName) dos rasters.
    """
    if not r_layers:
        return [u"Nenhuma camada raster no TOC"]

    extracted_groups = []
    if groups_with_rasters:
        for g in groups_with_rasters:
            if g and g not in extracted_groups:
                extracted_groups.append(g)

    # Sempre extrair grupos tambem diretamente do longName das camadas (ex: Grupo\Cena -> Grupo)
    for r in r_layers:
        r_str = unicode(r).strip()
        if u"\\" in r_str:
            parts = [p.strip() for p in r_str.split(u"\\") if p.strip()]
            for g in parts[:-1]:
                if g and g not in extracted_groups:
                    extracted_groups.append(g)

    targets = [u"[Todo o TOC]"]
    for g in extracted_groups:
        g_lbl = u"[Grupo] " + unicode(g)
        if g_lbl not in targets:
            targets.append(g_lbl)

    for r in r_layers:
        r_lbl = unicode(r).strip()
        if r_lbl and r_lbl not in targets:
            targets.append(r_lbl)

    return targets

def resolve_layer_names(target_str, raster_layers):
    """Resolve os nomes de camadas raster (strings) correspondentes a um alvo selecionado:
    - None / vazio / [Todo o TOC] / TODAS -> todas as camadas de raster_layers
    - [Grupo] Nome -> camadas cujo caminho longName inicia com Nome\\ ou contem \\Nome\\
    - Camada individual -> a camada correspondente em raster_layers
    """
    if not raster_layers:
        return []

    t_str = unicode(target_str or "").strip()
    if not t_str or t_str.startswith(u"[Todo o TOC]") or t_str in (u"TODAS", u"Todas as camadas", u"Nenhuma camada raster no TOC"):
        return list(raster_layers)

    if t_str.startswith(u"[Grupo]"):
        grp = t_str.replace(u"[Grupo]", u"").strip().lower()
        matched = []
        for r in raster_layers:
            r_low = unicode(r).strip().lower()
            if r_low.startswith(grp + u"\\") or (u"\\" + grp + u"\\") in r_low or r_low == grp:
                matched.append(r)
        if matched:
            return matched

    # Buscar por nome exato (longName ou leaf name)
    clean_target = t_str.lower()
    for r in raster_layers:
        r_low = unicode(r).strip().lower()
        if r_low == clean_target:
            return [r]
        leaf = r_low.split(u"\\")[-1]
        if leaf == clean_target:
            return [r]

    # Fallback substring
    matched = []
    for r in raster_layers:
        if clean_target in unicode(r).strip().lower():
            matched.append(r)
    if matched:
        return matched

    return [t_str]

def get_arcmap_selected_layer():
    """Identifica o nome da camada ou grupo atualmente selecionado no TOC do ArcMap via ArcObjects"""
    try:
        import comtypes.client
        esriCarto = comtypes.client.GetModule(get_esricarto_olb_path())
        import arcmagery_symbology as symbology
        mx_doc, _focus_map = symbology.live_focus_map()  # IMxDocument (tem SelectedLayer)
        if not mx_doc:
            return None, False
        sel = getattr(mx_doc, 'SelectedLayer', None)
        if not sel:
            return None, False
        name = getattr(sel, 'Name', '')
        is_grp = False
        try:
            if sel.QueryInterface(esriCarto.IGroupLayer):
                is_grp = True
        except Exception:
            pass
        return name, is_grp
    except Exception:
        return None, False

def export_layer_to_geojson(layer_name, out_geojson, buffer_meters=None):
    """Exporta o retangulo envolvente (envelope) da camada ativa para GeoJSON em WGS84 com buffer opcional em metros"""
    if not arcpy:
        return None
    try:
        import math
        mxd = arcpy.mapping.MapDocument("CURRENT")
        layers = arcpy.mapping.ListLayers(mxd, layer_name)
        if not layers:
            return None
        lyr = layers[0]
        sr_wgs84 = arcpy.SpatialReference(4326)

        if buffer_meters is None:
            settings = load_plugin_settings()
            buffer_meters = float(settings.get('aoi_buffer_meters', 1000.0))
        else:
            buffer_meters = float(buffer_meters)

        ext = lyr.getExtent()
        if not ext:
            return None

        # Verificar se o sistema da camada e projetado (unidade linear metros)
        sr = ext.spatialReference
        if sr and sr.type == 'Projected' and buffer_meters > 0:
            minx = ext.XMin - buffer_meters
            miny = ext.YMin - buffer_meters
            maxx = ext.XMax + buffer_meters
            maxy = ext.YMax + buffer_meters
            ext_buffered = arcpy.Extent(minx, miny, maxx, maxy, sr)
            ext_wgs = ext_buffered.projectAs(sr_wgs84)
            minx_wgs, miny_wgs, maxx_wgs, maxy_wgs = ext_wgs.XMin, ext_wgs.YMin, ext_wgs.XMax, ext_wgs.YMax
        else:
            ext_wgs = ext.projectAs(sr_wgs84)
            minx_wgs, miny_wgs, maxx_wgs, maxy_wgs = ext_wgs.XMin, ext_wgs.YMin, ext_wgs.XMax, ext_wgs.YMax
            if buffer_meters > 0:
                lat_c = (miny_wgs + maxy_wgs) / 2.0
                d_lat = buffer_meters / 110574.0
                cos_lat = max(0.01, math.cos(math.radians(lat_c)))
                d_lon = buffer_meters / (111320.0 * cos_lat)
                minx_wgs -= d_lon
                miny_wgs -= d_lat
                maxx_wgs += d_lon
                maxy_wgs += d_lat

        # Retangulo envolvente em GeoJSON Polygon estrito (padrao RFC 7946)
        bbox_poly = [
            [minx_wgs, miny_wgs],
            [maxx_wgs, miny_wgs],
            [maxx_wgs, maxy_wgs],
            [minx_wgs, maxy_wgs],
            [minx_wgs, miny_wgs]
        ]
        geojson_data = {
            "type": "Polygon",
            "coordinates": [bbox_poly]
        }

        with open(out_geojson, "w") as f:
            json.dump(geojson_data, f, indent=2)
        return out_geojson
    except Exception as e:
        print("Erro exportando camada para GeoJSON:", e)
        return None

def get_empty_group_lyr_path():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(current_dir, "empty_group_template.lyr"),
        os.path.join(current_dir, "Install", "empty_group_template.lyr"),
        os.path.abspath(os.path.join(current_dir, "..", "Install", "empty_group_template.lyr"))
    ]
    for c in candidates:
        if os.path.exists(c):
            return os.path.abspath(c)
    return None

def ensure_pure_group_template():
    """Garante que empty_group_template.lyr seja um GroupLayer comum (e NUNCA um BasemapLayer)"""
    tmpl_path = get_empty_group_lyr_path()
    need_create = True
    if tmpl_path and os.path.exists(tmpl_path):
        try:
            l = arcpy.mapping.Layer(tmpl_path)
            if l.isGroupLayer and not l.isBasemapLayer:
                need_create = False
        except Exception:
            pass

    if need_create:
        try:
            import comtypes.client
            esriCarto = comtypes.client.GetModule(get_esricarto_olb_path())
            gl = comtypes.client.CreateObject(esriCarto.GroupLayer, interface=esriCarto.IGroupLayer)
            out_p = tmpl_path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "empty_group_template.lyr")
            lf = comtypes.client.CreateObject(esriCarto.LayerFile, interface=esriCarto.ILayerFile)
            if os.path.exists(out_p):
                try: os.remove(out_p)
                except Exception: pass
            lf.New(out_p)
            lf.ReplaceContents(gl)
            lf.Save()
            lf.Close()
            return out_p
        except Exception as ex:
            print("Erro gerando template de grupo:", ex)
    return tmpl_path

def get_or_create_group_layer(group_name):
    """Localiza ou cria um Grupo de Camadas Comum (Group Layer normal, NUNCA Basemap Layer) no ArcMap"""
    if not arcpy or not group_name or not unicode(group_name).strip():
        return None
    try:
        mxd = arcpy.mapping.MapDocument("CURRENT")
        df = arcpy.mapping.ListDataFrames(mxd)[0]
        gname = unicode(group_name).strip()

        # 1. Procurar se ja existe um grupo com este nome
        for lyr in arcpy.mapping.ListLayers(mxd, "", df):
            if lyr.isGroupLayer and lyr.name.strip().lower() == gname.lower():
                if lyr.isBasemapLayer:
                    # Se for basemap layer (erro da versao anterior), remover do TOC para substituir por grupo comum
                    try:
                        arcpy.mapping.RemoveLayer(df, lyr)
                    except Exception:
                        pass
                    break
                else:
                    return lyr

        # 2. Criar a partir do template de grupo comum (garantido isBasemapLayer == False)
        tmpl_path = ensure_pure_group_template()
        if tmpl_path and os.path.exists(tmpl_path):
            grp_tmpl = arcpy.mapping.Layer(tmpl_path)
            grp_tmpl.name = gname
            grp_tmpl.visible = True
            arcpy.mapping.AddLayer(df, grp_tmpl, "TOP")

            for lyr in arcpy.mapping.ListLayers(mxd, "", df):
                if lyr.isGroupLayer and not lyr.isBasemapLayer and lyr.name.strip().lower() == gname.lower():
                    return lyr
        return None
    except Exception as e:
        print("Erro ao criar/obter grupo comum:", e)
        return None

BAND_NAME_TO_INDEX = {
    'S2': {
        'B1': 1, 'B2': 2, 'B3': 3, 'B4': 4, 'B5': 5, 'B6': 6, 'B7': 7, 'B8': 8, 'B8A': 9, 'B9': 10, 'B11': 11, 'B12': 12
    },
    'L8': {
        'SR_B1': 1, 'SR_B2': 2, 'SR_B3': 3, 'SR_B4': 4, 'SR_B5': 5, 'SR_B6': 6, 'SR_B7': 7, 'ST_B10': 8
    },
    'L7': {
        'SR_B1': 1, 'SR_B2': 2, 'SR_B3': 3, 'SR_B4': 4, 'SR_B5': 5, 'SR_B7': 6, 'ST_B6': 7
    },
    'L5': {
        'SR_B1': 1, 'SR_B2': 2, 'SR_B3': 3, 'SR_B4': 4, 'SR_B5': 5, 'SR_B7': 6, 'ST_B6': 7
    },
    'L4': {
        'SR_B1': 1, 'SR_B2': 2, 'SR_B3': 3, 'SR_B4': 4, 'SR_B5': 5, 'SR_B7': 6, 'ST_B6': 7
    },
    'L3': {
        'B4': 1, 'B5': 2, 'B6': 3, 'B7': 4
    },
    'L2': {
        'B4': 1, 'B5': 2, 'B6': 3, 'B7': 4
    },
    'L1': {
        'B4': 1, 'B5': 2, 'B6': 3, 'B7': 4
    }
}

def get_band_indices_for_composition(sensor, comp_code):
    """Retorna os indices [R, G, B] (1-based) para a composicao do sensor"""
    comps = COMPOSITIONS.get(sensor, {})
    comp_info = comps.get(comp_code, {})
    bands = comp_info.get('bands')
    if not bands or len(bands) < 3:
        return None
    name_map = BAND_NAME_TO_INDEX.get(sensor, {})
    indices = []
    for b in bands[:3]:
        idx = name_map.get(b)
        if idx:
            indices.append(idx)
    if len(indices) == 3:
        return indices
    return None

SETTINGS_FILE = os.path.expanduser("~/.gee_plugin_settings.json")


def system_cores():
    try:
        import multiprocessing
        return multiprocessing.cpu_count()
    except Exception:
        return 4


def default_cores():
    """Nucleos para o geoprocessamento (piramides/estatisticas), com folga de 2 para o ArcMap."""
    return max(1, min(16, system_cores() - 2))


TILE_THREADS_MIN, TILE_THREADS_MAX = 4, 64


def default_tile_threads():
    """Threads de rede do download de tiles (backend/parallel.default_workers: satura perto de 48)."""
    return max(8, min(48, 4 * system_cores()))


def clamp_tile_threads(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return default_tile_threads()
    return max(TILE_THREADS_MIN, min(TILE_THREADS_MAX, value))


def tile_threads(settings=None):
    settings = settings if settings is not None else load_plugin_settings()
    return clamp_tile_threads(settings.get('tile_threads', default_tile_threads()))


def stats_skip_factor(width, height, target_pixels=25e6):
    """Amostragem do CalculateStatistics: ~25 Mpx lidos em vez do raster inteiro (um mosaico
    de 1,4 Gpx levava mais que o prazo da interface - P-01). 1 = todos os pixels."""
    try:
        n = float(width) * float(height)
    except (TypeError, ValueError):
        return 1
    if n <= target_pixels:
        return 1
    import math
    return int(math.ceil(math.sqrt(n / target_pixels)))


def load_timeout_seconds(width=None, height=None, base=120, cap=1800):
    """Prazo de resposta do ArcMap para carregar um raster, proporcional ao tamanho."""
    try:
        mpx = float(width) * float(height) / 1e6
    except (TypeError, ValueError):
        return base
    return int(min(cap, base + 0.4 * mpx))


STALE_SIDECARS = ('.ovr', '.aux.xml')


def remove_stale_sidecars(tif_path, tolerance=2.0):
    """Remove .ovr / .aux.xml MAIS ANTIGOS que o .tif: sao de um arquivo anterior com o mesmo nome
    (os temporarios tem nome fixo) e, com BuildPyramids SKIP_EXISTING, o ArcMap exibiria as piramides
    e estatisticas da area antiga. Os gerados pelo backend depois do .tif sao mantidos."""
    removed = []
    try:
        tif_time = os.path.getmtime(tif_path)
    except OSError:
        return removed
    for ext in STALE_SIDECARS:
        side = tif_path + ext
        try:
            if os.path.exists(side) and os.path.getmtime(side) < tif_time - tolerance:
                os.remove(side)
                removed.append(side)
        except OSError:
            pass
    return removed


def _stats_and_pyramids(tif_path):
    """Estatisticas por amostragem e piramides; as piramides (.ovr) geradas pelo backend sao
    reaproveitadas (SKIP_EXISTING) em vez de recalculadas na thread do ArcMap."""
    remove_stale_sidecars(tif_path)
    skip = 1
    try:
        r = arcpy.Raster(tif_path)
        skip = stats_skip_factor(r.width, r.height)
    except Exception:
        pass
    try:
        arcpy.CalculateStatistics_management(tif_path, skip, skip, "", "OVERWRITE")
    except Exception:
        pass
    try:
        arcpy.BuildPyramids_management(tif_path, "", "", "", "", "", "SKIP_EXISTING")
    except Exception:
        try:
            arcpy.BuildPyramids_management(tif_path)
        except Exception:
            pass

def load_plugin_settings():
    """Carrega as configuracoes persistentes do plugin ou retorna os padroes"""
    defaults = {
        'stretch_type': 'Standard Deviations',
        'stretch_std_param': 2.0,
        'statistics_type': 'From Current Display Extent',
        'multicore_enabled': True,
        'multicore_cores': default_cores(),
        'tile_threads': default_tile_threads(),
        'aoi_buffer_meters': 1000.0,
        'load_layer_visible': True
    }
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r") as f:
                data = json.load(f)
                defaults.update(data)
    except Exception:
        pass
    return defaults

def save_plugin_settings(settings):
    """Salva as configuracoes do plugin no arquivo persistente"""
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=2)
        return True
    except Exception as e:
        print("Erro salvando configuracoes:", e)
        return False

def is_math_expr(text):
    """
    Verifica de forma robusta se a string de entrada representa uma expressao/formula
    matematica (ex: '(SR_B5 - SR_B4) / (SR_B5 + SR_B4)') ou uma lista de bandas
    (ex: 'SR_B3, SR_B4, SR_B5, SR_B7' ou '(SR_B3, SR_B4, SR_B5, SR_B7)' ou 'B3-B5, B7').
    """
    if not text:
        return False
    t = str(text).strip()
    if not t:
        return False

    while (t.startswith('(') and t.endswith(')')) or (t.startswith('[') and t.endswith(']')):
        t = t[1:-1].strip()

    if any(op in t for op in ['+', '*', '/', '^', '%']):
        return True

    import re
    if re.search(r'\b(sqrt|exp|log|log10|sin|cos|tan|min|max|abs)\s*\(', t, re.IGNORECASE):
        return True

    if '-' in t:
        parts = [p.strip() for p in re.split(r'[,;\s]+', t) if p.strip()]
        for p in parts:
            if '-' in p:
                sub = p.split('-')
                if len(sub) == 2 and re.match(r'^(SR_|ST_)?B\d+[A-Za-z]?$', sub[0], re.I) and re.match(r'^(SR_|ST_)?B\d+[A-Za-z]?$', sub[1], re.I):
                    continue
                else:
                    return True

    return False

def parse_bands(text, sensor=None):
    """
    Interpreta e normaliza uma lista de bandas customizadas, suportando:
    - Separadores por virgula, ponto e virgula ou espacos
    - Delimitadores externos como parenteses (B3, B4) ou colchetes [B3, B4]
    - Expansao inteligente de intervalos com hifen (ex: 'B3-B5' -> ['SR_B3', 'SR_B4', 'SR_B5'])
    - Mapeamento e normalizacao de prefixos para Landsat (SR_ / ST_) e Sentinel-2
    - Compatibilidade estrita com Landsat 5 TM (onde B6 termica e ST_B6, e nao existe SR_B6)
    """
    if not text:
        return []
    import re
    t = str(text).strip()
    while (t.startswith('(') and t.endswith(')')) or (t.startswith('[') and t.endswith(']')):
        t = t[1:-1].strip()

    raw_items = [b.strip().upper() for b in re.split(r'[,;\s]+', t) if b.strip()]
    expanded = []

    for item in raw_items:
        item = item.strip("()[]")
        if not item:
            continue

        if '-' in item:
            sub = item.split('-')
            if len(sub) == 2 and re.match(r'^(SR_|ST_)?B\d+$', sub[0]) and re.match(r'^(SR_|ST_)?B\d+$', sub[1]):
                prefix = 'SR_' if ('SR_' in sub[0] or 'SR_' in sub[1]) else ''
                m1 = re.search(r'\d+', sub[0])
                m2 = re.search(r'\d+', sub[1])
                if m1 and m2:
                    n1 = int(m1.group())
                    n2 = int(m2.group())
                    step = 1 if n1 <= n2 else -1
                    for n in range(n1, n2 + step, step):
                        expanded.append("%sB%d" % (prefix, n))
                    continue
        expanded.append(item)

    out = []
    sens = (sensor or '').upper()

    for b in expanded:
        if sens in ['L8', 'L7', 'L5', 'L4']:
            if b.startswith('B') and not b.startswith(('SR_', 'ST_')):
                if b == 'B10' and sens == 'L8':
                    out.append('ST_B10')
                elif b == 'B6' and sens in ['L7', 'L5', 'L4']:
                    out.append('ST_B6')
                else:
                    out.append('SR_' + b)
            else:
                out.append(b)
        elif sens == 'S2':
            if b.startswith('SR_'):
                out.append(b.replace('SR_', ''))
            elif b.startswith('ST_'):
                out.append(b.replace('ST_', ''))
            else:
                out.append(b)
        else:
            out.append(b)

    if sens in ['L5', 'L4', 'L7']:
        out = [('ST_B6' if x == 'SR_B6' else x) for x in out]

    return out

def resolve_rgb_band_indices(sensor, comp_code, custom_bands=None, band_count=None):
    """Retorna os indices 0-based [R, G, B] para a simbologia do raster baixado,
    preservando todas as bandas no raster e direcionando as cores iniciais."""
    raster_bands = []
    if custom_bands:
        if not is_math_expr(str(custom_bands)):
            raster_bands = parse_bands(str(custom_bands), sensor)
            if len(raster_bands) >= 3:
                return (0, 1, 2)
    
    comp_info = COMPOSITIONS.get(sensor, {}).get(comp_code, {})
    if not raster_bands:
        if band_count and band_count > 3:
            raster_bands = MULTIBAND_DEFAULT_BANDS.get(sensor, [])
        if not raster_bands and comp_info.get('bands'):
            raster_bands = comp_info['bands']

    target_comp_bands = comp_info.get('bands', [])
    if comp_info.get('multiband', False) or len(target_comp_bands) < 3:
        target_comp_bands = ['B4', 'B3', 'B2'] if sensor == 'S2' else ['SR_B4', 'SR_B3', 'SR_B2']

    if raster_bands and len(raster_bands) >= 3:
        if len(raster_bands) == 3 and not custom_bands and (not band_count or band_count == 3):
            return (0, 1, 2)
        
        indices = []
        for tb in target_comp_bands[:3]:
            if tb in raster_bands:
                indices.append(raster_bands.index(tb))
            else:
                matched = False
                for r_idx, rb in enumerate(raster_bands):
                    if rb.replace("SR_", "") == tb.replace("SR_", ""):
                        indices.append(r_idx)
                        matched = True
                        break
                if not matched:
                    indices.append(None)
        
        used = [x for x in indices if x is not None]
        avail = [i for i in range(len(raster_bands)) if i not in used]
        final_indices = []
        for x in indices:
            if x is not None:
                final_indices.append(x)
            elif avail:
                final_indices.append(avail.pop(0))
            else:
                final_indices.append(0)
        return (final_indices[0], final_indices[1], final_indices[2])
    
    bc = band_count or 3
    return (0, 1 if bc > 1 else 0, 2 if bc > 2 else 0)

def apply_stretch_and_stats(lyr_file_path, settings=None, rgb_bands=None):
    """Aplica bandas RGB + Stretch/Estatisticas a um .lyr e CONFERE relendo do disco
    (motor arcmagery_symbology). Retorna True/False; o motivo da falha vai para o log."""
    if not settings:
        settings = load_plugin_settings()
    warning = _prepare_layer_symbology(lyr_file_path, settings, rgb_bands)
    return not warning


def _legacy_apply_stretch_and_stats(lyr_file_path, settings=None, rgb_bands=None):
    # [Obsoleto] Implementacao anterior, sem verificacao. Mantida apenas como referencia.
    """Aplica configuracoes de Stretch (Standard Deviations, Percent Clip, etc) 
    e Statistics (AreaOfView / Display Extent) ao arquivo de camada .lyr via ArcObjects.
    Garante que rasters com 3 ou mais bandas utilizem IRasterRGBRenderer (RGB Composite)."""
    if not settings:
        settings = load_plugin_settings()
    try:
        import comtypes.client
        esriCarto = comtypes.client.GetModule(get_esricarto_olb_path())
        lf = comtypes.client.CreateObject(esriCarto.LayerFile, interface=esriCarto.ILayerFile)
        lf.Open(lyr_file_path)
        layer = lf.Layer
        raster_layer = layer.QueryInterface(esriCarto.IRasterLayer)
        renderer = raster_layer.Renderer

        # Se raster com 3 ou mais bandas, GARANTIR RasterRGBRenderer!
        total_b = getattr(raster_layer, 'BandCount', 1)
        if (rgb_bands and len(rgb_bands) >= 3) or total_b >= 3:
            if not rgb_bands or len(rgb_bands) < 3:
                rgb_bands = (0, 1, 2)
            rgb_rend = None
            try:
                rgb_rend = renderer.QueryInterface(esriCarto.IRasterRGBRenderer)
            except Exception:
                rgb_rend = None

            if not rgb_rend:
                try:
                    rgb_rend = comtypes.client.CreateObject(esriCarto.RasterRGBRenderer, interface=esriCarto.IRasterRGBRenderer)
                    rend_base = rgb_rend.QueryInterface(esriCarto.IRasterRenderer)
                    rend_base.Raster = raster_layer.Raster
                    rend_base.Update()
                    renderer = rend_base
                    raster_layer.Renderer = renderer
                except Exception as e_create_rgb:
                    print("Erro criando RasterRGBRenderer:", e_create_rgb)

            if rgb_rend:
                try:
                    rgb_rend.RedBandIndex = int(rgb_bands[0])
                    rgb_rend.GreenBandIndex = int(rgb_bands[1])
                    rgb_rend.BlueBandIndex = int(rgb_bands[2])
                    rend_base = rgb_rend.QueryInterface(esriCarto.IRasterRenderer)
                    rend_base.Update()
                    renderer = rend_base
                    raster_layer.Renderer = renderer
                except Exception as e_set_bands:
                    print("Erro configurando bandas RGB:", e_set_bands)

        # 1. Configurar Stretch Type
        st_map = {
            'Standard Deviations': esriCarto.esriRasterStretch_StandardDeviations,
            'Standard Deviation': esriCarto.esriRasterStretch_StandardDeviations,
            'Percent Clip': esriCarto.esriRasterStretch_PercentMinimumMaximum,
            'Minimum-Maximum': esriCarto.esriRasterStretch_MinimumMaximum,
            'Histogram Equalize': esriCarto.esriRasterStretch_HistogramEqualize,
            'None': esriCarto.esriRasterStretch_NONE,
            'Esri': esriCarto.esriRasterStretch_ESRI,
            'Sigmoid': esriCarto.esriRasterStretch_Sigmoid
        }
        st_choice = settings.get('stretch_type', 'Standard Deviations')
        st_val = st_map.get(st_choice, esriCarto.esriRasterStretch_StandardDeviations)

        try:
            stretch = renderer.QueryInterface(esriCarto.IRasterStretch)
            stretch.StretchType = st_val
            if st_val == esriCarto.esriRasterStretch_StandardDeviations:
                std_param = float(settings.get('stretch_std_param', 2.0))
                stretch.StandardDeviationsParam = std_param
        except Exception as e:
            print("Erro aplicando StretchType:", e)

        # 2. Configurar Statistics Type (AreaOfView = From Current Display Extent)
        stats_map = {
            'From Current Display Extent': esriCarto.esriRasterStretchStats_AreaOfView,
            'From Each Raster Dataset': esriCarto.esriRasterStretchStats_Dataset,
            'From Custom Settings': esriCarto.esriRasterStretchStats_GlobalStats
        }
        stats_choice = settings.get('statistics_type', 'From Current Display Extent')
        stats_val = stats_map.get(stats_choice, esriCarto.esriRasterStretchStats_AreaOfView)

        try:
            stretch2 = renderer.QueryInterface(esriCarto.IRasterStretch2)
            stretch2.StretchStatsType = stats_val
        except Exception as e:
            print("Erro aplicando StretchStatsType:", e)

        try:
            rend_base = renderer.QueryInterface(esriCarto.IRasterRenderer)
            rend_base.Update()
        except Exception:
            pass

        raster_layer.Renderer = renderer
        lf.Save()
        lf.Close()
        return True
    except Exception as ex:
        print("Erro em apply_stretch_and_stats:", ex)
        return False

def _refresh_arcmap_views(mx_doc=None):
    """Atualiza o Table of Contents (TOC) e a visualizacao do mapa (ActiveView) tanto via ArcObjects quanto ArcPy."""
    try:
        if arcpy:
            arcpy.RefreshTOC()
            arcpy.RefreshActiveView()
    except Exception:
        pass
    try:
        if mx_doc:
            if hasattr(mx_doc, 'UpdateContents'):
                mx_doc.UpdateContents()
            if hasattr(mx_doc, 'ActiveView') and hasattr(mx_doc.ActiveView, 'Refresh'):
                mx_doc.ActiveView.Refresh()
    except Exception:
        pass

def find_live_raster_layer(layer_name=None):
    """Localiza a camada raster ativa no ArcMap atraves de ArcObjects (AppRef / FocusMap).
    Retorna uma tupla: (mx_doc, focus_map, com_layer, com_raster_layer) ou (None, None, None, None)."""
    try:
        import comtypes.client
        esriCarto = comtypes.client.GetModule(get_esricarto_olb_path())
        # IApplication.Document e um IDocument (sem FocusMap): QueryInterface(IMxDocument) obrigatorio
        import arcmagery_symbology as symbology
        mx_doc, focus_map = symbology.live_focus_map()
        if not focus_map:
            return None, None, None, None

        # 1. Se layer_name foi fornecido, buscar na arvore recursiva do mapa
        if layer_name and unicode(layer_name).strip():
            clean_target = unicode(layer_name).strip().lower()
            leaf_target = clean_target.split(u"\\")[-1].strip()
            p_enum = focus_map.Layers(None, True)
            p_enum.Reset()
            lyr = p_enum.Next()
            while lyr:
                try:
                    c_name = unicode(lyr.Name).strip().lower()
                    if (c_name == clean_target or 
                        c_name == leaf_target or
                        c_name == (clean_target + u".tif") or 
                        c_name == (leaf_target + u".tif") or
                        clean_target in c_name or 
                        leaf_target in c_name or 
                        c_name in clean_target):
                        rl = lyr.QueryInterface(esriCarto.IRasterLayer)
                        return mx_doc, focus_map, lyr, rl
                except Exception:
                    pass
                lyr = p_enum.Next()
            return mx_doc, focus_map, None, None

        # 2. Se nao foi fornecido nome, tentar a camada selecionada no TOC (SelectedLayer)
        try:
            sel = getattr(mx_doc, 'SelectedLayer', None)
            if sel:
                rl = sel.QueryInterface(esriCarto.IRasterLayer)
                return mx_doc, focus_map, sel, rl
        except Exception:
            pass

        # 3. Fallback somente se layer_name nao foi informado: primeira camada raster encontrada no mapa
        p_enum = focus_map.Layers(None, True)
        p_enum.Reset()
        lyr = p_enum.Next()
        while lyr:
            try:
                rl = lyr.QueryInterface(esriCarto.IRasterLayer)
                return mx_doc, focus_map, lyr, rl
            except Exception:
                pass
            lyr = p_enum.Next()

        return mx_doc, focus_map, None, None
    except Exception as e:
        _log_debug("find_live_raster_layer falhou: " + err_text(e))
        return None, None, None, None

def resolve_target_raster_layers(mxd, df, target_name=None):
    """Localiza e retorna lista de objetos de camada raster (arcpy.mapping.Layer)
    correspondentes ao alvo selecionado:
    - [Todo o TOC] ou None ou vazio ou 'TODAS' -> Todas as camadas raster do TOC
    - [Grupo] Nome -> Todas as camadas raster pertencentes ao grupo especificado
    - Nome de Grupo -> Todas as camadas raster do grupo
    - Nome de Camada -> A camada raster individual correspondente
    Se nenhum alvo for informado, verifica se ha um grupo ou raster selecionado no ArcMap via ArcObjects.
    """
    if not arcpy:
        return []
    try:
        all_layers = arcpy.mapping.ListLayers(mxd, "", df)
        rasters = [l for l in all_layers if not l.isGroupLayer and l.isRasterLayer]
        if not rasters:
            return []

        target_str = unicode(target_name or "").strip()

        # Se target_str nao foi explicitado ou vazio, consultar se ha selecao ativa no ArcMap
        if not target_str or target_str.lower() in (u"none", u"null", u""):
            sel_name, is_grp = get_arcmap_selected_layer()
            if sel_name:
                if is_grp:
                    target_str = u"[Grupo] " + sel_name
                else:
                    target_str = sel_name

        # 1. Alvo: Todo o TOC
        if not target_str or target_str.startswith(u"[Todo o TOC]") or target_str in (u"TODAS", u"Todas as camadas", u"Nenhuma camada raster no TOC"):
            return rasters

        # 2. Alvo: Grupo com prefixo [Grupo]
        if target_str.startswith(u"[Grupo]"):
            grp = target_str.replace(u"[Grupo]", u"").strip().lower()
            matched = [l for l in rasters if l.longName.lower().startswith(grp + u"\\") or (u"\\" + grp + u"\\") in l.longName.lower() or l.name.lower() == grp]
            if matched:
                return matched

        # 3. Alvo: Nome de Grupo direto
        for l in all_layers:
            if l.isGroupLayer and (l.name.lower() == target_str.lower() or l.longName.lower() == target_str.lower()):
                grp = l.name.lower()
                matched = [r for r in rasters if r.longName.lower().startswith(grp + u"\\") or (u"\\" + grp + u"\\") in r.longName.lower()]
                if matched:
                    return matched

        # 4. Alvo: Camada raster individual (por longName ou name)
        clean_target = target_str.lower()
        for l in rasters:
            if l.longName.lower() == clean_target or l.name.lower() == clean_target:
                return [l]

        # 5. Fallback por sufixo ou substring
        for l in rasters:
            if l.longName.lower().endswith(u"\\" + clean_target) or clean_target in l.name.lower():
                return [l]

        return []
    except Exception as e_res:
        _log_debug("resolve_target_raster_layers erro: " + str(e_res))
        return []

def _apply_rgb_to_com_layer(rl, r_idx, g_idx, b_idx, settings=None):
    """Configura e aplica IRasterRGBRenderer diretamente no objeto IRasterLayer COM ao vivo."""
    import comtypes.client
    esriCarto = comtypes.client.GetModule(get_esricarto_olb_path())
    if not settings:
        settings = load_plugin_settings()

    rgb_rend = comtypes.client.CreateObject(esriCarto.RasterRGBRenderer, interface=esriCarto.IRasterRGBRenderer)
    rend_base = rgb_rend.QueryInterface(esriCarto.IRasterRenderer)
    rend_base.Raster = rl.Raster
    rend_base.Update()

    rgb_rend.RedBandIndex = int(r_idx)
    rgb_rend.GreenBandIndex = int(g_idx)
    rgb_rend.BlueBandIndex = int(b_idx)

    # 1. Configurar Stretch
    st_map = {
        'Standard Deviations': esriCarto.esriRasterStretch_StandardDeviations,
        'Standard Deviation': esriCarto.esriRasterStretch_StandardDeviations,
        'Percent Clip': esriCarto.esriRasterStretch_PercentMinimumMaximum,
        'Minimum-Maximum': esriCarto.esriRasterStretch_MinimumMaximum,
        'Histogram Equalize': esriCarto.esriRasterStretch_HistogramEqualize,
        'None': esriCarto.esriRasterStretch_NONE,
        'Esri': esriCarto.esriRasterStretch_ESRI,
        'Sigmoid': esriCarto.esriRasterStretch_Sigmoid
    }
    st_choice = settings.get('stretch_type', 'Standard Deviations')
    st_val = st_map.get(st_choice, esriCarto.esriRasterStretch_StandardDeviations)
    try:
        stretch = rend_base.QueryInterface(esriCarto.IRasterStretch)
        stretch.StretchType = st_val
        if st_val == esriCarto.esriRasterStretch_StandardDeviations:
            std_param = float(settings.get('stretch_std_param', 2.0))
            stretch.StandardDeviationsParam = std_param
    except Exception as e_st:
        _log_debug("_apply_rgb_to_com_layer stretch: " + str(e_st))

    # 2. Configurar Statistics Type
    stats_map = {
        'From Current Display Extent': esriCarto.esriRasterStretchStats_AreaOfView,
        'From Each Raster Dataset': esriCarto.esriRasterStretchStats_Dataset,
        'From Custom Settings': esriCarto.esriRasterStretchStats_GlobalStats
    }
    stats_choice = settings.get('statistics_type', 'From Current Display Extent')
    stats_val = stats_map.get(stats_choice, esriCarto.esriRasterStretchStats_AreaOfView)
    try:
        stretch2 = rend_base.QueryInterface(esriCarto.IRasterStretch2)
        stretch2.StretchStatsType = stats_val
    except Exception as e_stats:
        _log_debug("_apply_rgb_to_com_layer stats: " + str(e_stats))

    rend_base.Update()
    rl.Renderer = rend_base
    return rgb_rend

def _interrogate_and_verify_rgb(rl, exp_r=None, exp_g=None, exp_b=None):
    """Interroga a camada raster do TOC para verificar se o renderizador ativo e realmente
    RGB Composite (IRasterRGBRenderer) e se as bandas estao atribuidas a canais distintos."""
    import comtypes.client
    esriCarto = comtypes.client.GetModule(get_esricarto_olb_path())
    try:
        active_rend = rl.Renderer
        if not active_rend:
            return False, u"Nenhum renderizador ativo na camada."

        # Checar se ainda e Stretched
        try:
            stretch_rend = active_rend.QueryInterface(esriCarto.IRasterStretchColorRampRenderer)
            if stretch_rend:
                return False, u"A camada ainda esta no modo 'Stretched' (RasterStretchColorRampRenderer)."
        except Exception:
            pass

        # Checar se implementa IRasterRGBRenderer
        try:
            rgb_rend = active_rend.QueryInterface(esriCarto.IRasterRGBRenderer)
        except Exception:
            rgb_rend = None

        if not rgb_rend:
            return False, u"Renderizador ativo nao e 'RGB Composite' (IRasterRGBRenderer ausente)."

        r = rgb_rend.RedBandIndex
        g = rgb_rend.GreenBandIndex
        b = rgb_rend.BlueBandIndex

        # Validacao estrita: bandas devem ser distintas
        if r == g or r == b or g == b:
            return False, u"Bandas RGB nao sao distintas (R=%d, G=%d, B=%d)." % (r, g, b)

        if exp_r is not None and exp_g is not None and exp_b is not None:
            if (r, g, b) != (exp_r, exp_g, exp_b):
                return False, u"Bandas configuradas (R=%d, G=%d, B=%d) diferem das solicitadas (R=%d, G=%d, B=%d)." % (
                    r, g, b, exp_r, exp_g, exp_b
                )

        return True, (r, g, b)
    except Exception as e:
        return False, u"Excecao durante interrogacao da camada: " + err_text(e)

def force_single_layer_rgb(
    layer_name=None,
    rgb_bands=None,
    settings=None,
    tif_path=None,
    group_name=None,
    comp_code=None,
    sensor=None,
    custom_bands=None,
    max_retries=2
):
    """Aplica e valida a simbologia RGB Composite em uma camada raster especifica.
    Tenta primeiro via ArcObjects COM e, caso falhe ou COM nao esteja disponivel,
    aplica a Acao Corretiva Nativa do ArcPy (MakeRasterLayer -> SaveToLayerFile -> InsertLayer -> RemoveLayer).
    """
    if not settings:
        settings = load_plugin_settings()

    _log_debug("force_single_layer_rgb iniciado para layer '%s'" % str(layer_name))

    # 1. Tentar localizar camada viva no ArcMap via ArcObjects
    mx_doc, focus_map, lyr, rl = find_live_raster_layer(layer_name)
    r_idx, g_idx, b_idx = (0, 1, 2)

    if rl:
        total_bands = getattr(rl, 'BandCount', 1)
        if total_bands < 3:
            return False, u"A camada possui apenas %d banda(s); RGB Composite exige no minimo 3 bandas." % total_bands

        if not rgb_bands or len(rgb_bands) < 3:
            rgb_bands = resolve_rgb_band_indices(sensor, comp_code, custom_bands, total_bands)

        r_idx = max(0, min(int(rgb_bands[0]), total_bands - 1))
        g_idx = max(0, min(int(rgb_bands[1]), total_bands - 1))
        b_idx = max(0, min(int(rgb_bands[2]), total_bands - 1))

        if r_idx == g_idx:
            g_idx = (r_idx + 1) % total_bands
        if b_idx == r_idx or b_idx == g_idx:
            for cand in range(total_bands):
                if cand != r_idx and cand != g_idx:
                    b_idx = cand
                    break

        # Tentativa COM 1
        try:
            _apply_rgb_to_com_layer(rl, r_idx, g_idx, b_idx, settings)
        except Exception as e_app1:
            _log_debug("Tentativa COM 1 falhou: " + str(e_app1))

        ok_v1, res_v1 = _interrogate_and_verify_rgb(rl, r_idx, g_idx, b_idx)
        if ok_v1:
            _refresh_arcmap_views(mx_doc)
            msg_ok = u"Simbologia RGB Composite aplicada e validada com sucesso na camada '%s'!" % (layer_name or "")
            return True, msg_ok

        # Tentativa COM 2
        try:
            _apply_rgb_to_com_layer(rl, r_idx, g_idx, b_idx, settings)
        except Exception as e_app2:
            _log_debug("Tentativa COM 2 falhou: " + str(e_app2))

        ok_v2, res_v2 = _interrogate_and_verify_rgb(rl, r_idx, g_idx, b_idx)
        if ok_v2:
            _refresh_arcmap_views(mx_doc)
            msg_ok = u"Simbologia RGB Composite aplicada e validada apos reaplicacao na camada '%s'!" % (layer_name or "")
            return True, msg_ok

    # Se COM nao conseguiu validar ou falhou, usar ACAO CORRETIVA NATIVA DO ARCPY (100% compativel)
    _log_debug("Iniciando Acao Corretiva Nativa ArcPy para '%s'..." % str(layer_name))
    try:
        mxd_curr = arcpy.mapping.MapDocument("CURRENT")
        df_curr = arcpy.mapping.ListDataFrames(mxd_curr)[0]
        actual_name = getattr(lyr, 'Name', layer_name) if lyr else layer_name
        target_lyr_obj = None
        for l_chk in arcpy.mapping.ListLayers(mxd_curr, "", df_curr):
            if not l_chk.isGroupLayer and (l_chk.name == actual_name or (layer_name and (layer_name in l_chk.name or l_chk.name in layer_name))):
                target_lyr_obj = l_chk
                break

        if target_lyr_obj:
            if not tif_path:
                tif_path = getattr(target_lyr_obj, 'dataSource', None)

            if tif_path and os.path.exists(tif_path):
                desc_tif = arcpy.Describe(tif_path)
                t_bands = getattr(desc_tif, 'bandCount', None) or getattr(desc_tif, 'BandCount', 1)
                if t_bands < 3:
                    return False, u"Raster possui apenas %d banda(s)." % t_bands

                if not rgb_bands or len(rgb_bands) < 3:
                    rgb_bands = resolve_rgb_band_indices(sensor, comp_code, custom_bands, t_bands)
                r_idx, g_idx, b_idx = rgb_bands[:3]

                is_visible = getattr(target_lyr_obj, 'visible', True)
                readd_tmp_name = "gee_readd_" + uuid.uuid4().hex[:8]
                if arcpy.Exists(readd_tmp_name):
                    try: arcpy.Delete_management(readd_tmp_name)
                    except Exception: pass

                arcpy.MakeRasterLayer_management(tif_path, readd_tmp_name)
                cache_dir = os.path.join(tempfile.gettempdir(), 'arcgee_lyr_cache')
                if not os.path.exists(cache_dir):
                    try: os.makedirs(cache_dir)
                    except Exception: pass

                readd_lyr = os.path.join(cache_dir, "readd_" + str(int(time.time())) + ".lyr")
                if os.path.exists(readd_lyr):
                    try: os.remove(readd_lyr)
                    except Exception: pass

                arcpy.SaveToLayerFile_management(readd_tmp_name, readd_lyr)
                if arcpy.Exists(readd_tmp_name):
                    try: arcpy.Delete_management(readd_tmp_name)
                    except Exception: pass

                apply_stretch_and_stats(readd_lyr, settings, rgb_bands=(r_idx, g_idx, b_idx))

                new_obj = arcpy.mapping.Layer(readd_lyr)
                new_obj.name = target_lyr_obj.name
                new_obj.visible = is_visible

                arcpy.mapping.InsertLayer(df_curr, target_lyr_obj, new_obj, "BEFORE")
                arcpy.mapping.RemoveLayer(df_curr, target_lyr_obj)

                _refresh_arcmap_views(mx_doc)
                _log_debug("Acao Corretiva Nativa ArcPy concluida com sucesso para '%s'" % str(actual_name))
                return True, u"Simbologia RGB Composite corrigida com sucesso na camada '%s'!" % unicode(actual_name)
    except Exception as e_readd:
        _log_debug("Erro na acao corretiva nativa ArcPy: " + str(e_readd))

    _refresh_arcmap_views(mx_doc)
    return False, u"Falha ao validar RGB Composite na camada '%s'." % unicode(layer_name or "")

def force_and_validate_rgb_composite(
    layer_name=None,
    rgb_bands=None,
    settings=None,
    tif_path=None,
    group_name=None,
    comp_code=None,
    sensor=None,
    custom_bands=None,
    max_retries=2
):
    """Forca e valida que a(s) camada(s) raster no TOC do ArcMap utilizem renderizador 'RGB Composite'.
    Suporta execucao sobre:
    - Uma camada raster individual
    - Um Grupo de camadas ([Grupo] Nome)
    - Todo o TOC ([Todo o TOC])
    
    Retorna (sucesso, mensagem_formatada)."""
    if not arcpy:
        return False, "ArcPy nao disponivel."
    if not settings:
        settings = load_plugin_settings()

    _log_debug("force_and_validate_rgb_composite iniciado para alvo '%s'" % str(layer_name))

    mxd = arcpy.mapping.MapDocument("CURRENT")
    df = arcpy.mapping.ListDataFrames(mxd)[0]

    target_rasters = resolve_target_raster_layers(mxd, df, layer_name)
    if not target_rasters:
        return False, u"Nenhuma camada raster compatível encontrada no TOC para '%s'." % (layer_name or "TOC")

    # Se for exatamente 1 camada individual
    if len(target_rasters) == 1:
        lyr = target_rasters[0]
        actual_path = tif_path or getattr(lyr, 'dataSource', None)
        return force_single_layer_rgb(
            layer_name=lyr.name,
            rgb_bands=rgb_bands,
            settings=settings,
            tif_path=actual_path,
            group_name=group_name,
            comp_code=comp_code,
            sensor=sensor,
            custom_bands=custom_bands,
            max_retries=max_retries
        )

    # Multiplas camadas (Grupo ou Todo o TOC)
    success_count = 0
    errors = []
    for lyr in target_rasters:
        try:
            actual_path = getattr(lyr, 'dataSource', None)
            desc = arcpy.Describe(actual_path) if (actual_path and os.path.exists(actual_path)) else None
            band_count = getattr(desc, 'bandCount', None) or getattr(desc, 'BandCount', 1) if desc else 1
            if band_count < 3:
                continue

            r_idx, g_idx, b_idx = (0, 1, 2)
            if rgb_bands and len(rgb_bands) >= 3:
                r_idx, g_idx, b_idx = rgb_bands[:3]
            else:
                r_idx, g_idx, b_idx = resolve_rgb_band_indices(sensor, comp_code, custom_bands, band_count)

            ok, msg = force_single_layer_rgb(
                layer_name=lyr.name,
                rgb_bands=(r_idx, g_idx, b_idx),
                settings=settings,
                tif_path=actual_path,
                comp_code=comp_code,
                sensor=sensor,
                custom_bands=custom_bands,
                max_retries=max_retries
            )
            if ok:
                success_count += 1
            else:
                errors.append(unicode(lyr.name) + u": " + unicode(msg))
        except Exception as e_item:
            errors.append(unicode(lyr.name) + u": " + unicode(e_item))

    target_desc = unicode(layer_name) if layer_name else u"TOC"
    if success_count > 0:
        return True, u"Simbologia RGB Composite aplicada e validada com sucesso em %d camada(s) [%s]!" % (
            success_count, target_desc
        )
    else:
        return False, u"Falha ao validar RGB Composite. Erros: " + u"; ".join(errors[:3])

def _rgb_override(rgb_bands):
    """Aceita uma lista explicita [R, G, B] de indices 0-based enviada pela GUI (ex.: CBERS)."""
    try:
        if rgb_bands and len(rgb_bands) == 3:
            vals = tuple(int(v) for v in rgb_bands)
            if min(vals) >= 0:
                return vals
    except Exception:
        pass
    return None

SYMBOLOGY_WARNING_PREFIX = u"ATENÇÃO"

def build_date_footprints_layer(json_path, layer_name=None):
    """Esri JSON (poligonos das datas de captura) -> shapefile + .lyr estilizado (contorno sem
    preenchimento) com rotulo da data. Retorna o arcpy.mapping.Layer pronto para inserir.
    Nao depende do ArcMap aberto (testavel fora dele)."""
    import arcmagery_symbology as symbology
    base = os.path.splitext(json_path)[0]
    shp = base + '.shp'
    lyr_file = base + '.lyr'
    prev_overwrite = getattr(arcpy.env, 'overwriteOutput', False)
    arcpy.env.overwriteOutput = True
    try:
        if arcpy.Exists(shp):
            arcpy.Delete_management(shp)
        arcpy.JSONToFeatures_conversion(json_path, shp)
        tmp = "arcmagery_fp_" + uuid.uuid4().hex[:8]
        arcpy.MakeFeatureLayer_management(shp, tmp)
        if os.path.exists(lyr_file):
            os.remove(lyr_file)
        arcpy.SaveToLayerFile_management(tmp, lyr_file)
        arcpy.Delete_management(tmp)
    finally:
        arcpy.env.overwriteOutput = prev_overwrite
    symbology.style_footprints_layer_file(lyr_file)
    lyr = arcpy.mapping.Layer(lyr_file)
    lyr.name = layer_name or u"Datas de captura"
    try:
        lc = lyr.labelClasses[0]
        lc.expression = "[DATA_CAPT] & \" \" & [SATELITE]"
        lyr.showLabels = True
    except Exception as e_lbl:
        _log_debug("build_date_footprints_layer: rotulos indisponiveis (%s)" % e_lbl)
    return lyr

def load_date_footprints(json_path, layer_name=None, group_name=None):
    """Insere no TOC os poligonos com as datas de captura (acima da imagem, no mesmo grupo)."""
    if not arcpy:
        return False, "ArcPy nao disponivel."
    try:
        lyr = build_date_footprints_layer(json_path, layer_name)
        mxd = arcpy.mapping.MapDocument("CURRENT")
        df = arcpy.mapping.ListDataFrames(mxd)[0]
        target_grp = get_or_create_group_layer(group_name) if group_name and unicode(group_name).strip() else None
        if target_grp:
            arcpy.mapping.AddLayerToGroup(df, target_grp, lyr, "TOP")
        else:
            arcpy.mapping.AddLayer(df, lyr, "TOP")
        arcpy.RefreshTOC()
        arcpy.RefreshActiveView()
        return True, u"Polígonos com as datas de captura carregados."
    except Exception as e:
        _log_debug(u"load_date_footprints: %s" % err_text(e))
        return False, u"Falha ao carregar os polígonos de datas: %s" % err_text(e)

def _prepare_layer_symbology(lyr_path, settings, rgb_indices):
    """Grava bandas RGB + Stretch no .lyr e confere relendo do disco. Retorna aviso ('' se ok)."""
    try:
        import arcmagery_symbology as symbology
        symbology.apply_to_layer_file(lyr_path, settings, rgb_bands=rgb_indices)
        return u""
    except Exception as e:
        _log_debug(u"_prepare_layer_symbology: %s" % err_text(e))
        return err_text(e)

def _ensure_live_symbology(tif_path, settings, rgb_indices, layer_name, previous_warning=u"", focus_map=None):
    """Confere a camada viva (e corrige se preciso). Retorna o texto de retorno para a GUI:
    ' | Simbologia conferida (...)' ou ' | ATENÇÃO: ...' quando nao foi possivel garantir."""
    try:
        import arcmagery_symbology as symbology
        ok, msg, _states = symbology.ensure_layer_symbology(tif_path, settings, rgb_bands=rgb_indices,
                                                            layer_name=layer_name, focus_map=focus_map)
    except Exception as e:
        ok, msg = False, u"Simbologia não pôde ser verificada: %s" % err_text(e)
    _log_debug("_ensure_live_symbology(%s): %s %s" % (layer_name, ok, msg))
    if ok:
        return u" | " + msg
    detail = msg if not previous_warning else u"%s | %s" % (previous_warning, msg)
    return u" | %s: %s" % (SYMBOLOGY_WARNING_PREFIX, detail)

def load_into_toc(tif_path, layer_name=None, group_name=None, zoom=False, comp_code=None, sensor=None, custom_bands=None, rgb_bands=None):
    """Adiciona o arquivo GeoTIFF baixado diretamente no TOC do ArcMap sem duplicar,
    garantindo que camadas multibanda entrem NATIVAMENTE no modo RGB Composite como padrao."""
    if not arcpy:
        return False, "ArcPy nao disponivel."

    try:
        mxd = arcpy.mapping.MapDocument("CURRENT")
        df = arcpy.mapping.ListDataFrames(mxd)[0]

        if not layer_name:
            layer_name = os.path.splitext(os.path.basename(tif_path))[0]

        tif_basename_ext   = os.path.basename(tif_path)
        tif_basename_noext = os.path.splitext(tif_basename_ext)[0]
        suspect_names = {tif_basename_ext, tif_basename_noext, layer_name}

        # Carregar configuracoes do plugin (Stretch, Statistics, Multicore, Visibilidade)
        settings = load_plugin_settings()
        cores = settings.get('multicore_cores', 4) if settings.get('multicore_enabled', True) else 1
        layer_visible = bool(settings.get('load_layer_visible', True))

        # Ativar Multicore no ArcPy para geoprocessamento paralelo (CalculateStatistics, BuildPyramids)
        prev_parallel = getattr(arcpy.env, 'parallelProcessingFactor', None)
        try:
            arcpy.env.parallelProcessingFactor = str(cores)
        except Exception:
            pass

        # Desativar addOutputsToMap para evitar camadas espurias
        prev_add_outputs = arcpy.env.addOutputsToMap
        arcpy.env.addOutputsToMap = False
        prev_overwrite = getattr(arcpy.env, 'overwriteOutput', False)
        arcpy.env.overwriteOutput = True

        try:
            # 1. Estatisticas (amostradas) e piramides (reaproveita o .ovr do backend), em multicore
            _stats_and_pyramids(tif_path)

            # 2. Verificar numero de bandas
            desc = arcpy.Describe(tif_path)
            band_count = getattr(desc, 'bandCount', 1)

            # 3. Criar camada com MakeRasterLayer_management para garantir RGB Composite NATIVO como padrao!
            cache_dir = os.path.join(tempfile.gettempdir(), 'arcgee_lyr_cache')
            if not os.path.exists(cache_dir):
                try: os.makedirs(cache_dir)
                except Exception: pass

            import re
            safe_id = re.sub(r'[^a-zA-Z0-9_\-]', '_', layer_name)
            persistent_lyr = os.path.join(cache_dir, safe_id + ".lyr")
            if os.path.exists(persistent_lyr):
                try: os.remove(persistent_lyr)
                except Exception: pass

            temp_lyr_name = "gee_tmp_load_" + uuid.uuid4().hex[:8]
            if arcpy.Exists(temp_lyr_name):
                try: arcpy.Delete_management(temp_lyr_name)
                except Exception: pass

            arcpy.MakeRasterLayer_management(tif_path, temp_lyr_name)
            arcpy.SaveToLayerFile_management(temp_lyr_name, persistent_lyr)
            if arcpy.Exists(temp_lyr_name):
                try: arcpy.Delete_management(temp_lyr_name)
                except Exception: pass

            # 4. Configurar Stretch e bandas RGB no arquivo de camada (.lyr)
            rgb_indices = None
            if band_count >= 3:
                rgb_indices = _rgb_override(rgb_bands) or resolve_rgb_band_indices(sensor, comp_code, custom_bands, band_count)
            symbology_warning = _prepare_layer_symbology(persistent_lyr, settings, rgb_indices)

            layer_obj = arcpy.mapping.Layer(persistent_lyr)
            layer_obj.name = layer_name
            layer_obj.visible = layer_visible

            # 5. Obter ou criar grupo alvo se solicitado (sempre GroupLayer comum, nunca Basemap)
            target_grp = None
            if group_name and unicode(group_name).strip():
                target_grp = get_or_create_group_layer(group_name)

            # 6. Inserir camada: dentro do grupo (AddLayerToGroup) ou na raiz (AddLayer)
            if target_grp:
                target_grp.visible = True
                arcpy.mapping.AddLayerToGroup(df, target_grp, layer_obj, "BOTTOM")
            else:
                arcpy.mapping.AddLayer(df, layer_obj, "TOP")

            # 6.0 Conferir (e corrigir) bandas + Stretch na camada viva, localizada pelo caminho exato
            rgb_feedback_msg = _ensure_live_symbology(tif_path, settings, rgb_indices, layer_name, symbology_warning)

            # Garantir visibilidade configurada no TOC (inclusive quando inserido em grupo)
            try:
                for lyr in arcpy.mapping.ListLayers(mxd, "", df):
                    if not lyr.isGroupLayer and lyr.name == layer_name:
                        lyr.visible = layer_visible
                        break
            except Exception:
                pass

            # 6.1 Se esta camada for a versao final completa, remover previa correspondente no TOC
            if not layer_name.startswith("Previa_"):
                try:
                    prefix_cand = layer_name.rsplit('_', 1)[0]
                    prev_names = {"Previa_" + layer_name, "Previa_" + prefix_cand}
                    for l_chk in list(arcpy.mapping.ListLayers(mxd, "", df)):
                        try:
                            if not l_chk.isGroupLayer and (l_chk.name in prev_names or l_chk.name.startswith("Previa_" + prefix_cand)):
                                arcpy.mapping.RemoveLayer(df, l_chk)
                        except Exception:
                            pass
                except Exception:
                    pass

            # 7. Zoom se solicitado
            if zoom:
                try:
                    for lyr in arcpy.mapping.ListLayers(mxd, "", df):
                        if not lyr.isGroupLayer and lyr.name == layer_name:
                            df.extent = lyr.getExtent()
                            break
                except Exception:
                    pass

        finally:
            arcpy.env.addOutputsToMap = prev_add_outputs
            arcpy.env.overwriteOutput = prev_overwrite
            if prev_parallel is not None:
                try:
                    arcpy.env.parallelProcessingFactor = prev_parallel
                except Exception:
                    pass

        arcpy.RefreshTOC()
        arcpy.RefreshActiveView()

        return True, ("Camada '%s' adicionada com sucesso ao grupo '%s'!%s" % (layer_name, group_name or "TOC", rgb_feedback_msg)).strip()
    except Exception as e:
        return False, "Erro ao adicionar camada ao TOC: " + err_text(e)

def replace_in_toc(tif_path, target_long_name, new_layer_name=None, comp_code=None, sensor=None, custom_bands=None, rgb_bands=None):
    """Substitui uma camada existente no TOC pela nova imagem/mosaico baixado, mantendo a posicao exata e garantindo RGB Composite nativo"""
    if not arcpy or not target_long_name:
        return False, "Alvo nao fornecido."
    try:
        mxd = arcpy.mapping.MapDocument("CURRENT")
        df = arcpy.mapping.ListDataFrames(mxd)[0]

        target_lyr = None
        for lyr in arcpy.mapping.ListLayers(mxd, "", df):
            if lyr.longName == target_long_name or lyr.name == target_long_name:
                target_lyr = lyr
                break

        if not target_lyr:
            return False, "Camada alvo '%s' nao encontrada no TOC." % target_long_name

        settings = load_plugin_settings()
        cores = settings.get('multicore_cores', 4) if settings.get('multicore_enabled', True) else 1

        prev_parallel = getattr(arcpy.env, 'parallelProcessingFactor', None)
        try:
            arcpy.env.parallelProcessingFactor = str(cores)
        except Exception:
            pass

        prev_add_outputs = arcpy.env.addOutputsToMap
        arcpy.env.addOutputsToMap = False
        prev_overwrite = getattr(arcpy.env, 'overwriteOutput', False)
        arcpy.env.overwriteOutput = True

        try:
            # 1. Estatisticas (amostradas) e piramides (reaproveita o .ovr do backend)
            _stats_and_pyramids(tif_path)

            if not new_layer_name:
                new_layer_name = os.path.splitext(os.path.basename(tif_path))[0]

            # 2. Verificar numero de bandas
            desc = arcpy.Describe(tif_path)
            band_count = getattr(desc, 'bandCount', 1)

            # 3. Criar camada com MakeRasterLayer_management para garantir RGB Composite NATIVO
            cache_dir = os.path.join(tempfile.gettempdir(), 'arcgee_lyr_cache')
            if not os.path.exists(cache_dir):
                try: os.makedirs(cache_dir)
                except Exception: pass

            import re
            safe_id = re.sub(r'[^a-zA-Z0-9_\-]', '_', new_layer_name)
            persistent_lyr = os.path.join(cache_dir, safe_id + ".lyr")
            if os.path.exists(persistent_lyr):
                try: os.remove(persistent_lyr)
                except Exception: pass

            temp_lyr_name = "gee_tmp_rep_" + uuid.uuid4().hex[:8]
            if arcpy.Exists(temp_lyr_name):
                try: arcpy.Delete_management(temp_lyr_name)
                except Exception: pass

            arcpy.MakeRasterLayer_management(tif_path, temp_lyr_name)
            arcpy.SaveToLayerFile_management(temp_lyr_name, persistent_lyr)
            if arcpy.Exists(temp_lyr_name):
                try: arcpy.Delete_management(temp_lyr_name)
                except Exception: pass

            rgb_indices = None
            if band_count >= 3:
                rgb_indices = _rgb_override(rgb_bands) or resolve_rgb_band_indices(sensor, comp_code, custom_bands, band_count)
            symbology_warning = _prepare_layer_symbology(persistent_lyr, settings, rgb_indices)

            target_visible = getattr(target_lyr, 'visible', True)
            new_obj = arcpy.mapping.Layer(persistent_lyr)
            new_obj.name = new_layer_name
            new_obj.visible = target_visible

            arcpy.mapping.InsertLayer(df, target_lyr, new_obj, "BEFORE")
            arcpy.mapping.RemoveLayer(df, target_lyr)

            # Conferir (e corrigir) bandas + Stretch na camada nova, localizada pelo caminho exato
            rgb_feedback_msg = _ensure_live_symbology(tif_path, settings, rgb_indices, new_layer_name, symbology_warning)

            try:
                for lyr in arcpy.mapping.ListLayers(mxd, "", df):
                    if not lyr.isGroupLayer and lyr.name == new_layer_name:
                        lyr.visible = target_visible
                        break
            except Exception:
                pass

        finally:
            arcpy.env.addOutputsToMap = prev_add_outputs
            arcpy.env.overwriteOutput = prev_overwrite
            if prev_parallel is not None:
                try:
                    arcpy.env.parallelProcessingFactor = prev_parallel
                except Exception:
                    pass

        arcpy.RefreshTOC()
        arcpy.RefreshActiveView()
        return True, ("Camada '%s' substituida por '%s' com sucesso!%s" % (target_long_name, new_layer_name, rgb_feedback_msg)).strip()
    except Exception as e:
        return False, "Erro ao substituir camada no TOC: " + err_text(e)

def change_layer_composition(target_layer_name, composition_code, sensor):
    """Altera a composicao RGB de uma ou mais camadas existentes no TOC (individual, grupo ou todo o TOC)
    usando as bandas correspondentes sem descartar nenhuma banda."""
    if not arcpy:
        return False, "ArcPy nao disponivel."
    try:
        mxd = arcpy.mapping.MapDocument("CURRENT")
        df = arcpy.mapping.ListDataFrames(mxd)[0]

        target_rasters = resolve_target_raster_layers(mxd, df, target_layer_name)
        if not target_rasters:
            return False, u"Nenhuma camada raster compatível encontrada para o alvo '%s'." % (target_layer_name or "TOC")

        settings = load_plugin_settings()
        prev_add_outputs = arcpy.env.addOutputsToMap
        arcpy.env.addOutputsToMap = False

        updated_count = 0
        errors = []

        try:
            for target_lyr in target_rasters:
                try:
                    data_source = getattr(target_lyr, 'dataSource', None)
                    if not data_source or not os.path.exists(data_source):
                        continue

                    desc = arcpy.Describe(data_source)
                    band_count = getattr(desc, 'bandCount', None) or getattr(desc, 'BandCount', 1)
                    if band_count < 3:
                        continue

                    temp_lyr_name = "gee_tmp_comp_" + uuid.uuid4().hex[:8]
                    if arcpy.Exists(temp_lyr_name):
                        try: arcpy.Delete_management(temp_lyr_name)
                        except Exception: pass

                    arcpy.MakeRasterLayer_management(data_source, temp_lyr_name)
                    tmp_lyr_file = os.path.join(tempfile.gettempdir(), temp_lyr_name + ".lyr")
                    if os.path.exists(tmp_lyr_file):
                        try: os.remove(tmp_lyr_file)
                        except Exception: pass

                    arcpy.SaveToLayerFile_management(temp_lyr_name, tmp_lyr_file)
                    if arcpy.Exists(temp_lyr_name):
                        try: arcpy.Delete_management(temp_lyr_name)
                        except Exception: pass

                    rgb_indices = resolve_rgb_band_indices(sensor, composition_code, None, band_count=band_count)
                    apply_stretch_and_stats(tmp_lyr_file, settings=settings, rgb_bands=rgb_indices)

                    is_visible = getattr(target_lyr, 'visible', True)
                    orig_name = target_lyr.name

                    new_obj = arcpy.mapping.Layer(tmp_lyr_file)
                    new_obj.name = orig_name
                    new_obj.visible = is_visible

                    arcpy.mapping.InsertLayer(df, target_lyr, new_obj, "BEFORE")
                    arcpy.mapping.RemoveLayer(df, target_lyr)

                    # Forcar e validar RGB na camada recem-inserida
                    force_single_layer_rgb(
                        orig_name,
                        rgb_bands=rgb_indices,
                        settings=settings,
                        tif_path=data_source,
                        comp_code=composition_code,
                        sensor=sensor
                    )
                    updated_count += 1
                except Exception as ex_item:
                    errors.append(unicode(target_lyr.name) + u": " + unicode(ex_item))
        finally:
            arcpy.env.addOutputsToMap = prev_add_outputs

        arcpy.RefreshTOC()
        arcpy.RefreshActiveView()

        target_desc = unicode(target_layer_name) if target_layer_name else u"TOC"
        if updated_count > 0:
            return True, u"Composição '%s' aplicada com sucesso em %d camada(s) [%s]!" % (
                composition_code, updated_count, target_desc
            )
        else:
            return False, u"Falha ao alterar composição. Erros: " + u"; ".join(errors[:3])
    except Exception as e:
        return False, "Erro ao alterar composicao: " + err_text(e)

def apply_stretch_to_toc_layer(target_layer_name=None, settings=None):
    """Aplica e garante as configuracoes de Stretch (ex: Standard Deviations) e DRA (From Current Display Extent)
    em uma camada especifica, em um grupo ou em todo o TOC, forcando e validando RGB Composite para multibandas."""
    if not arcpy:
        return False, "ArcPy nao disponivel."
    if not settings:
        settings = load_plugin_settings()
    try:
        mxd = arcpy.mapping.MapDocument("CURRENT")
        df = arcpy.mapping.ListDataFrames(mxd)[0]

        rasters_to_update = resolve_target_raster_layers(mxd, df, target_layer_name)
        if not rasters_to_update:
            return False, u"Nenhuma camada raster compatível encontrada no TOC para o alvo especificado."

        # Motor verificado: reaplica o Stretch mantendo as bandas RGB atuais de cada camada
        try:
            import arcmagery_symbology as symbology
            paths = [getattr(l, 'dataSource', None) for l in rasters_to_update]
            updated, problems = symbology.restretch_layers(settings, only_paths=[p for p in paths if p])
            arcpy.RefreshTOC()
            arcpy.RefreshActiveView()
            st_name = settings.get('stretch_type', 'Standard Deviations')
            stats_type = settings.get('statistics_type', 'From Current Display Extent')
            msg = u"Stretch '%s' (estatísticas: %s) conferido em %d camada(s), bandas preservadas." % (
                st_name, stats_type, updated)
            if problems:
                return False, msg + u" Problemas: " + u" | ".join(problems[:5])
            return True, msg
        except Exception as e_sym:
            _log_debug("apply_stretch_to_toc_layer: motor de simbologia indisponivel (%s); usando legado" % e_sym)

        prev_add = arcpy.env.addOutputsToMap
        arcpy.env.addOutputsToMap = False
        updated_count = 0
        try:
            for lyr in rasters_to_update:
                try:
                    data_src = getattr(lyr, 'dataSource', None)
                    desc = arcpy.Describe(data_src) if (data_src and os.path.exists(data_src)) else None
                    b_count = getattr(desc, 'bandCount', None) or getattr(desc, 'BandCount', 1) if desc else 1
                    if b_count >= 3:
                        ok_f, msg_f = force_single_layer_rgb(
                            layer_name=lyr.name,
                            settings=settings,
                            tif_path=data_src
                        )
                        if ok_f:
                            updated_count += 1
                            continue

                    tmp_lyr = os.path.join(tempfile.gettempdir(), "gee_stretch_" + str(abs(hash(lyr.longName)))[:6] + ".lyr")
                    if os.path.exists(tmp_lyr):
                        try: os.remove(tmp_lyr)
                        except Exception: pass
                    arcpy.SaveToLayerFile_management(lyr, tmp_lyr)
                    ok = apply_stretch_and_stats(tmp_lyr, settings)
                    if ok:
                        src_lyr = arcpy.mapping.Layer(tmp_lyr)
                        arcpy.mapping.UpdateLayer(df, lyr, src_lyr, True)
                        updated_count += 1
                except Exception as ex_item:
                    print("Erro atualizando stretch da camada %s:" % lyr.name, ex_item)
        finally:
            arcpy.env.addOutputsToMap = prev_add

        arcpy.RefreshTOC()
        arcpy.RefreshActiveView()

        st_name = settings.get('stretch_type', 'Standard Deviations')
        std_n = settings.get('stretch_std_param', 2.0)
        stats_type = settings.get('statistics_type', 'From Current Display Extent')
        target_desc = unicode(target_layer_name) if target_layer_name else u"TOC"
        return True, u"Stretch garantido em %d camada(s) [%s]! [%s (n=%.1f) | DRA: %s]" % (
            updated_count, target_desc, st_name, float(std_n), stats_type
        )
    except Exception as e:
        return False, u"Erro ao garantir stretch: " + err_text(e)

# ==============================================================================
# PROTOCOLO DE COMUNICACAO INTER-PROCESSOS (IPC) ARCMAP <-> GUI EXTERNA
# Garante 100% de estabilidade: ArcMap NUNCA executa mainloop() e NUNCA trava
# ==============================================================================

def _ipc_session_id():
    """Identificador da sessao IPC = PID do processo ArcMap.
    No proprio ArcMap e os.getpid(); na GUI vem de ARCMAGERY_SESSION (definido por
    launch_gui_process). Isola varios ArcMaps/GUIs abertos ao mesmo tempo."""
    sid = os.environ.get('ARCMAGERY_SESSION', '').strip()
    return sid if sid.isdigit() else str(os.getpid())

IPC_SESSION = _ipc_session_id()
_IPC_DIR = tempfile.gettempdir()
CONTEXT_FILE = os.path.join(_IPC_DIR, "arcmagery_%s_context.json" % IPC_SESSION)
CMD_FILE = os.path.join(_IPC_DIR, "arcmagery_%s_cmd.json" % IPC_SESSION)
REPLY_FILE = os.path.join(_IPC_DIR, "arcmagery_%s_reply.json" % IPC_SESSION)
HEARTBEAT_FILE = os.path.join(_IPC_DIR, "arcmagery_%s_gui_heartbeat.tmp" % IPC_SESSION)
DEBUG_LOG_FILE = os.path.join(tempfile.gettempdir(), "arcgee_debug.log")

def _log_debug(msg):
    try:
        if os.path.exists(DEBUG_LOG_FILE) and os.path.getsize(DEBUG_LOG_FILE) > 3 * 1024 * 1024:
            try:
                bak = DEBUG_LOG_FILE + ".bak"
                if os.path.exists(bak):
                    os.remove(bak)
                os.rename(DEBUG_LOG_FILE, bak)
            except Exception:
                pass
        t_str = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(DEBUG_LOG_FILE, "a") as f:
            if isinstance(msg, unicode):
                msg = msg.encode("utf-8", "replace")
            f.write("[%s] %s\n" % (t_str, msg))
    except Exception:
        pass

def _atomic_replace(src, dst):
    """Substitui dst por src atomicamente (o leitor nunca ve um JSON pela metade)."""
    if os.name == 'nt':
        import ctypes
        MOVEFILE_REPLACE_EXISTING = 0x1
        MOVEFILE_WRITE_THROUGH = 0x8
        to_text = unicode if sys.version_info[0] == 2 else str  # noqa: F821
        if not ctypes.windll.kernel32.MoveFileExW(to_text(src), to_text(dst),
                                                  MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH):
            raise OSError("MoveFileExW falhou (%d)" % ctypes.windll.kernel32.GetLastError())
    else:
        os.rename(src, dst)

def safe_write_json(filepath, data):
    """Escreve JSON de forma atomica (arquivo temporario + rename) com novas tentativas
    em caso de conflito de acesso no Windows."""
    tmp_path = "%s.%d.tmp" % (filepath, os.getpid())
    for attempt in range(8):
        try:
            with open(tmp_path, "w") as f:
                json.dump(data, f)
            _atomic_replace(tmp_path, filepath)
            return True
        except Exception:
            time.sleep(0.05)
    try:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    except Exception:
        pass
    return False

def safe_read_json(filepath):
    """Le JSON com tentativas seguras caso o arquivo esteja sendo gravado"""
    if not os.path.exists(filepath):
        return None
    for attempt in range(8):
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except Exception:
            time.sleep(0.05)
    return None

def export_arcmap_context():
    """Exporta o contexto atual do ArcMap para arquivo JSON compartilhado"""
    if not arcpy:
        return None
    try:
        scale = get_arcmap_scale()
        bbox = get_arcmap_extent_wgs84()
        v_layers = get_arcmap_layers()
        r_layers = get_arcmap_raster_layers()
        all_groups = get_arcmap_toc_groups()

        # Determinar quais grupos contem camadas raster (via TOC e via caminho longName dos rasters)
        groups_with_rasters = []
        for g in all_groups:
            g_str = unicode(g).strip().lower()
            for r in r_layers:
                r_str = unicode(r).strip().lower()
                if r_str.startswith(g_str + u"\\") or (u"\\" + g_str + u"\\") in r_str or r_str == g_str:
                    if g not in groups_with_rasters:
                        groups_with_rasters.append(g)
                    break

        # SEMPRE extrair tambem diretamente dos nomes longos dos rasters (ex: Grupo\Cena -> Grupo)
        for r in r_layers:
            r_str = unicode(r).strip()
            if u"\\" in r_str:
                parts = [p.strip() for p in r_str.split(u"\\") if p.strip()]
                for grp in parts[:-1]:
                    if grp and grp not in groups_with_rasters:
                        groups_with_rasters.append(grp)

        # Construir lista padronizada e unificada de alvos (TOC / Grupos / Camadas)
        toc_targets = build_toc_targets(r_layers, groups_with_rasters)

        # Detectar se ha alvo selecionado ativamente no ArcMap
        sel_name, is_grp = get_arcmap_selected_layer()
        selected_target = None
        if sel_name:
            if is_grp:
                g_target = u"[Grupo] " + unicode(sel_name)
                if g_target in toc_targets:
                    selected_target = g_target
            else:
                sel_clean = unicode(sel_name).strip().lower()
                for r in r_layers:
                    r_clean = unicode(r).strip().lower()
                    if r_clean == sel_clean or r_clean.endswith(u"\\" + sel_clean) or sel_clean in r_clean:
                        selected_target = unicode(r)
                        break

        ctx = {
            'scale': scale,
            'bbox': bbox,
            'vector_layers': v_layers,
            'raster_layers': r_layers,
            'group_layers': all_groups,
            'groups_with_rasters': groups_with_rasters,
            'toc_targets': toc_targets,
            'selected_target': selected_target,
            'time': time.time()
        }
        safe_write_json(CONTEXT_FILE, ctx)
        _log_debug("export_arcmap_context: scale=%s, bbox=%s, rasters=%d, vectors=%d, targets=%d" % (
            str(scale), str(bbox), len(r_layers), len(v_layers), len(toc_targets)
        ))
        return ctx
    except Exception as e:
        _log_debug("Erro exportando contexto ArcMap: " + err_text(e))
        return None

def read_arcmap_context():
    """Lido pelo processo da GUI para obter escala, camadas e extensao atuais do ArcMap"""
    return safe_read_json(CONTEXT_FILE)

_arcmap_timer_id = None
_arcmap_timer_proc = None
_last_timer_ctx_time = 0

# Lista de cleanups diferidos: tuplas (suspect_names_set, group_name)
# Preenchida por load_into_toc; processada no proximo tick do timer
_deferred_toc_cleanup = []
_is_processing_cmd = False
_is_cleaning_toc = False

def _run_deferred_toc_cleanup():
    """Remove duplicatas de camadas na raiz do TOC agendadas pelo load_into_toc.
    Executado no proximo tick do timer, apos o ArcMap terminar de processar eventos internos.
    """
    global _deferred_toc_cleanup, _is_cleaning_toc
    if _is_cleaning_toc or not _deferred_toc_cleanup or not arcpy:
        return
    _is_cleaning_toc = True
    try:
        pending = list(_deferred_toc_cleanup)
        _deferred_toc_cleanup = []
        mxd = arcpy.mapping.MapDocument("CURRENT")
        df = arcpy.mapping.ListDataFrames(mxd)[0]
        changed = False
        for (suspect_names, group_name) in pending:
            # Verificar se grupo tem alguma das camadas alvo
            group_has_it = False
            for lyr in arcpy.mapping.ListLayers(mxd, "", df):
                try:
                    if not lyr.isGroupLayer and lyr.name in suspect_names:
                        if lyr.longName != lyr.name:  # esta dentro de algum grupo
                            group_has_it = True
                            break
                except Exception:
                    pass
            if not group_has_it:
                continue
            # Coletar camadas na raiz com nomes suspeitos
            to_remove = []
            for lyr in arcpy.mapping.ListLayers(mxd, "", df):
                try:
                    if not lyr.isGroupLayer and lyr.name in suspect_names:
                        if lyr.longName == lyr.name:  # camada na raiz (longName == name)
                            to_remove.append(lyr)
                except Exception:
                    pass
            for lyr in to_remove:
                try:
                    arcpy.mapping.RemoveLayer(df, lyr)
                    changed = True
                except Exception:
                    pass
        if changed:
            arcpy.RefreshTOC()
            arcpy.RefreshActiveView()
    except Exception:
        pass
    finally:
        _is_cleaning_toc = False

def start_arcmap_ipc_timer(interval_ms=250):
    """Inicia timer Win32 nativo na thread de UI do ArcMap para escutar comandos
    e atualizar contexto continuamente, mesmo com ArcMap em segundo plano."""
    global _arcmap_timer_id, _arcmap_timer_proc
    if _arcmap_timer_id is not None:
        return True
    try:
        import ctypes
        import ctypes.wintypes
        user32 = ctypes.windll.user32

        TIMERPROC = ctypes.WINFUNCTYPE(None, ctypes.wintypes.HWND, ctypes.c_uint, ctypes.c_ulong, ctypes.wintypes.DWORD)
        def on_timer(hwnd, msg, id_event, dw_time):
            global _last_timer_ctx_time
            try:
                process_pending_arcmap_commands()
                now = time.time()
                if now - _last_timer_ctx_time > 0.6:
                    _last_timer_ctx_time = now
                    hb_file = HEARTBEAT_FILE
                    if os.path.exists(hb_file):
                        try:
                            if (now - os.path.getmtime(hb_file)) < 6.0:
                                export_arcmap_context()
                        except Exception:
                            pass
            except Exception:
                pass
        _timer_proc_ref = TIMERPROC(on_timer)
        t_id = user32.SetTimer(0, 0, interval_ms, _timer_proc_ref)
        if t_id != 0:
            _arcmap_timer_id = t_id
            _arcmap_timer_proc = _timer_proc_ref
            _log_debug("Timer Win32 iniciado (ID %s, %d ms)" % (str(t_id), interval_ms))
            return True
    except Exception as e:
        _log_debug("Erro iniciando timer Win32: " + err_text(e))
    return False

def stop_arcmap_ipc_timer():
    """Para o timer Win32 nativo do ArcMap"""
    global _arcmap_timer_id, _arcmap_timer_proc
    try:
        if _arcmap_timer_id is not None:
            import ctypes
            user32 = ctypes.windll.user32
            user32.KillTimer(0, _arcmap_timer_id)
            _log_debug("Timer Win32 parado.")
    except Exception:
        pass
    _arcmap_timer_id = None
    _arcmap_timer_proc = None

def process_pending_arcmap_commands():
    """Executado periodicamente pelo timer nativo ou no onUpdate do Add-In (thread principal do ArcMap).
    Possui protecao estrita contra reentrancia para evitar loops de eventos COM durante RefreshTOC/RefreshActiveView.
    """
    global _is_processing_cmd
    if _is_processing_cmd:
        return False

    if not os.path.exists(CMD_FILE):
        _run_deferred_toc_cleanup()
        return False

    _is_processing_cmd = True
    try:
        cmd = safe_read_json(CMD_FILE)
        # Remover comando imediatamente para evitar execucoes duplicadas
        try:
            if os.path.exists(CMD_FILE):
                os.remove(CMD_FILE)
        except Exception:
            pass

        if not cmd:
            return False

        cmd_id = cmd.get('id', '')
        action = cmd.get('action')
        _log_debug("process_pending_arcmap_commands: executando '%s' (id=%s)" % (action, cmd_id))
        resp = {'reply_to': cmd_id, 'success': False, 'message': 'Acao desconhecida'}

        try:
            if action == 'load_layer':
                ok, msg = load_into_toc(
                    cmd['file'],
                    layer_name=cmd.get('name'),
                    group_name=cmd.get('group'),
                    zoom=cmd.get('zoom', False),
                    comp_code=cmd.get('comp'),
                    sensor=cmd.get('sensor'),
                    custom_bands=cmd.get('custom_bands'),
                    rgb_bands=cmd.get('rgb_bands')
                )
                resp = {'reply_to': cmd_id, 'success': ok, 'message': msg}
            elif action == 'load_date_footprints':
                ok, msg = load_date_footprints(cmd['file'], layer_name=cmd.get('name'), group_name=cmd.get('group'))
                resp = {'reply_to': cmd_id, 'success': ok, 'message': msg}
            elif action == 'replace_layer':
                ok, msg = replace_in_toc(
                    cmd['file'],
                    target_long_name=cmd['target_layer'],
                    new_layer_name=cmd.get('name'),
                    comp_code=cmd.get('comp'),
                    sensor=cmd.get('sensor'),
                    custom_bands=cmd.get('custom_bands'),
                    rgb_bands=cmd.get('rgb_bands')
                )
                resp = {'reply_to': cmd_id, 'success': ok, 'message': msg}
            elif action == 'change_composition':
                ok, msg = change_layer_composition(
                    cmd.get('target_layer') or cmd.get('layer_name'),
                    cmd['comp'],
                    cmd['sensor']
                )
                resp = {'reply_to': cmd_id, 'success': ok, 'message': msg}
            elif action == 'set_scale':
                ok, msg = set_arcmap_scale(cmd['scale'])
                resp = {'reply_to': cmd_id, 'success': ok, 'message': msg}
            elif action == 'export_aoi':
                tmp_geo = os.path.join(tempfile.gettempdir(), "arcgis_gee_aoi.geojson")
                buf = cmd.get('buffer_meters')
                geo_file = export_layer_to_geojson(cmd['layer_name'], tmp_geo, buffer_meters=buf)
                resp = {'reply_to': cmd_id, 'success': bool(geo_file), 'file': geo_file}
            elif action == 'refresh_context':
                ctx = export_arcmap_context()
                resp = {'reply_to': cmd_id, 'success': True, 'context': ctx}
            elif action == 'apply_stretch':
                ok, msg = apply_stretch_to_toc_layer(
                    cmd.get('target_layer') or cmd.get('layer_name'),
                    settings=cmd.get('settings')
                )
                resp = {'reply_to': cmd_id, 'success': ok, 'message': msg}
            elif action in ('force_rgb_composite', 'fix_symbology'):
                ok, msg = force_and_validate_rgb_composite(
                    layer_name=cmd.get('target_layer') or cmd.get('layer_name'),
                    rgb_bands=cmd.get('rgb_bands'),
                    settings=cmd.get('settings'),
                    sensor=cmd.get('sensor'),
                    comp_code=cmd.get('comp'),
                    custom_bands=cmd.get('custom_bands')
                )
                resp = {'reply_to': cmd_id, 'success': ok, 'message': msg}
        except Exception as ex:
            import traceback
            resp = {'reply_to': cmd_id, 'success': False, 'message': unicode(ex) + u"\n" + unicode(traceback.format_exc())}

        # Gravar resposta com safe_write_json
        safe_write_json(REPLY_FILE, resp)
        _log_debug("process_pending_arcmap_commands: concluido '%s' (sucesso=%s)" % (action, str(resp.get('success'))))

        # Atualizar contexto apos alteracoes
        try:
            export_arcmap_context()
        except Exception:
            pass

        _run_deferred_toc_cleanup()
        return True

    finally:
        _is_processing_cmd = False

_ipc_cmd_lock = threading.Lock()

def send_arcmap_command(action_dict, timeout=120):
    """Envia um comando para o ArcMap a partir do processo da GUI e aguarda a confirmacao"""
    with _ipc_cmd_lock:
        cmd_id = "cmd_" + str(int(time.time() * 1000))
        action_dict['id'] = cmd_id

        # Limpar resposta anterior se existir
        if os.path.exists(REPLY_FILE):
            try:
                os.remove(REPLY_FILE)
            except Exception:
                pass

        _log_debug("send_arcmap_command: enviando acao '%s' (id=%s)" % (action_dict.get('action'), cmd_id))
        safe_write_json(CMD_FILE, action_dict)

        # Aguardar resposta no arquivo REPLY_FILE
        t0 = time.time()
        while time.time() - t0 < timeout:
            if os.path.exists(REPLY_FILE):
                rep = safe_read_json(REPLY_FILE)
                if rep and rep.get('reply_to') == cmd_id:
                    try:
                        os.remove(REPLY_FILE)
                    except Exception:
                        pass
                    _log_debug("send_arcmap_command: resposta recebida para '%s' (sucesso=%s)" % (
                        action_dict.get('action'), str(rep.get('success'))
                    ))
                    return rep
            time.sleep(0.08)

        _log_debug("send_arcmap_command: TIMEOUT apos %ds para acao '%s'" % (timeout, action_dict.get('action')))
        try:
            if os.path.exists(CMD_FILE):
                os.remove(CMD_FILE)
        except Exception:
            pass

        return {'success': False, 'message': u'Tempo limite esgotado (%ds) aguardando resposta do ArcMap.' % timeout}

def apply_stretch(layer_name=None, settings=None):
    """Envia comando para o ArcMap aplicar/garantir o Stretch configurado na camada ou no mapa"""
    return send_arcmap_command({
        'action': 'apply_stretch',
        'layer_name': layer_name,
        'settings': settings
    })

def force_rgb_composite(layer_name=None, sensor=None, comp=None, custom_bands=None, settings=None):
    """Envia comando para o ArcMap forcar e validar a simbologia RGB Composite na camada alvo"""
    return send_arcmap_command({
        'action': 'force_rgb_composite',
        'layer_name': layer_name,
        'sensor': sensor,
        'comp': comp,
        'custom_bands': custom_bands,
        'settings': settings
    })

def launch_gui_process():
    """Inicia a interface grafica como processo independente pythonw.exe sem travar o ArcMap"""
    # pythonw.exe do proprio Python do ArcGIS (sys.prefix dentro do ArcMap); nunca o do PATH,
    # que pode ser um Python 3 incapaz de rodar a GUI (Python 2.7).
    pyw = os.path.join(sys.prefix, "pythonw.exe")
    if not os.path.exists(pyw):
        pyw = r"C:\Python27\ArcGIS10.8\pythonw.exe"
    if not os.path.exists(pyw):
        return False, "pythonw.exe do ArcGIS (Python 2.7) nao encontrado em %s" % sys.prefix

    install_dir = os.path.dirname(os.path.abspath(__file__))
    gui_script = os.path.join(install_dir, "gee_gui.py")

    # Iniciar timer IPC de background no ArcMap (a cada 500ms)
    start_arcmap_ipc_timer(500)

    # Exportar contexto antes de abrir a janela
    export_arcmap_context()

    clean_env = dict(os.environ)
    clean_env.pop('PYTHONPATH', None)
    clean_env.pop('PYTHONHOME', None)
    clean_env['ARCMAGERY_SESSION'] = str(os.getpid())  # GUI conversa apenas com ESTE ArcMap

    try:
        subprocess.Popen([pyw, gui_script], cwd=install_dir, env=clean_env)
        return True, "GUI iniciada com sucesso em processo separado."
    except Exception as e:
        return False, err_text(e)
