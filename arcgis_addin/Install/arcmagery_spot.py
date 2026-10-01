# -*- coding: utf-8 -*-
"""
ArcMagery - SPOT 1-5 (CNES SPOT World Heritage, 1986-2015) na janela principal (Python 2.7).

Mesmo modelo do CBERS (arcmagery_inpe): os grupos de cenas SPOT sao "sensores" com codigo
'SPOT:<grupo>' e cada cena do catalogo GEODES e uma linha da tabela. Este modulo nao depende do Tk:
  * catalogo de grupos (satelites x multiespectral/pancromatico) e composicoes;
  * chave de API do GEODES (gravada em %APPDATA%\\ArcGEE\\geodes_config.json, so para o usuario);
  * chamadas ao backend (spot_search / spot_download / spot_thumb / spot_check_key) no Python 3.

A busca e publica; o download exige a chave do GEODES (quota de 50 cenas por hora). O produto L1A
nao e ortorretificado: o backend georreferencia pelo modelo do produto e ALINHA a imagem a Esri
World Imagery (medido: 150-480 m de erro corrigidos para ~5 m).
"""
from __future__ import division

import io
import json
import os
import re

import gee_bridge

try:
    unicode
except NameError:  # importado pelo Python 3 (testes)
    unicode = str

PREFIX = 'SPOT:'
GEODES_PORTAL = u"https://geodes-portal.cnes.fr"
KEY_ENV = 'GEODES_API_KEY'

# (rotulo, grupo, satelites, tipo, resolucao nominal, periodo, bandas)
_GROUPS = [
    (u"SPOT 1 a 5 · multiespectral (todas as cenas, 10-20 m)", 'MS', None, 'ms', u"10 a 20 m",
     u"23/02/1986 a 29/03/2015 (Encerrado)", u"XS3 NIR, XS2 vermelho, XS1 verde (+ SWIR no SPOT 4/5)"),
    (u"SPOT 1 a 5 · pancromática (todas as cenas, 2,5-10 m)", 'PAN', None, 'pan', u"2,5 a 10 m",
     u"23/02/1986 a 29/03/2015 (Encerrado)", u"PAN (tons de cinza)"),
    (u"SPOT 5 · 10 m multiespectral (HRG, 2002-2015)", '5-MS', '5', 'ms', u"10 m",
     u"19/06/2002 a 29/03/2015 (Encerrado)", u"XS3 NIR, XS2 vermelho, XS1 verde, SWIR (20 m reamostrado)"),
    (u"SPOT 5 · 5 m / 2,5 m pancromática (HRG, 2002-2015)", '5-PAN', '5', 'pan', u"2,5 a 5 m",
     u"19/06/2002 a 29/03/2015 (Encerrado)", u"PAN (HM 5 m, THR 2,5 m)"),
    (u"SPOT 4 · 20 m multiespectral (HRVIR, 1998-2013)", '4-MS', '4', 'ms', u"20 m",
     u"27/03/1998 a 19/06/2013 (Encerrado)", u"XS3 NIR, XS2 vermelho, XS1 verde, SWIR"),
    (u"SPOT 4 · 10 m pancromática (HRVIR, 1998-2013)", '4-PAN', '4', 'pan', u"10 m",
     u"27/03/1998 a 19/06/2013 (Encerrado)", u"PAN (banda M, vermelho)"),
    (u"SPOT 1, 2 e 3 · 20 m multiespectral (HRV, 1986-2009)", '123-MS', '1,2,3', 'ms', u"20 m",
     u"23/02/1986 a 25/07/2009 (Encerrado)", u"XS3 NIR, XS2 vermelho, XS1 verde"),
    (u"SPOT 1, 2 e 3 · 10 m pancromática (HRV, 1986-2009)", '123-PAN', '1,2,3', 'pan', u"10 m",
     u"23/02/1986 a 25/07/2009 (Encerrado)", u"PAN (tons de cinza)"),
]
_BY_CODE = dict((PREFIX + g[1], g) for g in _GROUPS)

SPOT_SENSOR_DISPLAY = [(label, PREFIX + code) for (label, code, _s, _k, _r, _p, _b) in _GROUPS]

SPOT_SENSOR_METADATA = dict(
    (PREFIX + code, {
        'name': label,
        'agency': u'CNES (SPOT World Heritage)',
        'collection': u"GEODES SWH L1A",
        'period_display': period,
        'end_year': 2015,
        'default_dates': (u"01/01/1986", u"31/12/2015"),
        'res': res,
        'native_res': None,
        'available_bands': bands,
        'notes': u"Nível 1A alinhado automaticamente à Esri World Imagery. Download exige a chave do GEODES.",
    }) for (label, code, _s, _k, res, period, bands) in _GROUPS)

PRODUCTS = [
    ('false', u'Falsa cor (NIR, vermelho, verde) - vegetação em vermelho'),
    ('swir', u'SWIR, NIR, vermelho (só SPOT 4 e 5) - umidade e solo exposto'),
    ('multi', u'Multibanda (todas as bandas, exibida em falsa cor)'),
    ('pan', u'Pancromática (tons de cinza, maior resolução)'),
]

TUTORIAL_STEPS = [
    (u"1. Crie a conta gratuita no GEODES",
     u"Acesse %s e clique em \"Log in\" > \"Register\". Informe nome, e-mail, organização "
     u"e confirme o cadastro pelo link enviado ao seu e-mail." % GEODES_PORTAL),
    (u"2. Entre e abra o seu perfil",
     u"Depois de entrar, clique no seu nome no canto superior direito e escolha \"My Profile\"."),
    (u"3. Gere a chave de API",
     u"No quadro \"Authentication\", em \"API Key\", clique em \"Generate\" (ou copie a chave existente "
     u"com o ícone de copiar). A chave é um texto longo de letras e números."),
    (u"4. Cole a chave no ArcMagery",
     u"Em Configurações > Chave do GEODES (SPOT), cole a chave e clique em \"Testar chave\". "
     u"A cota aparece em seguida (ex.: 50 de 50 downloads por hora). Clique em \"Salvar\"."),
    (u"5. Use a fonte SPOT",
     u"Na barra \"Fonte de imagens\", escolha \"SPOT 1-5 (CNES)\", busque as cenas da área e carregue. "
     u"A busca não usa a cota; cada cena baixada conta 1 download (as já baixadas ficam em cache)."),
]
TUTORIAL_NOTES = (u"A chave fica salva só neste computador, na sua pasta de usuário "
                  u"(%APPDATA%\\ArcGEE\\geodes_config.json). Não compartilhe a chave: ela identifica a sua "
                  u"conta. Se ela vazar, gere outra no mesmo quadro (ícone de atualizar).")


def is_spot(sensor_code):
    return bool(sensor_code) and str(sensor_code).startswith(PREFIX)


def group_of(sensor_code):
    return _BY_CODE.get(sensor_code)


def modes_for(sensor_code):
    g = group_of(sensor_code)
    if g and g[3] == 'pan':
        return ['pan']
    return ['false', 'swir', 'multi']


def composition_items(sensor_code):
    labels = dict(PRODUCTS)
    return [u"%s - %s" % (m, labels[m]) for m in modes_for(sensor_code)]


def format_cloud(value):
    if value is None or value == '':
        return u"n/d"
    try:
        return u"%.0f%%" % float(value)
    except (TypeError, ValueError):
        return u"%s%%" % value


def item_to_row(item):
    """Cena do backend spot_search -> linha no formato de images_cache da janela principal."""
    cov = item.get('coverage_pct')
    res = item.get('res_m')
    detail = u"%s · %s · %s" % (item.get('platform') or u'SPOT', (u"%.0f m" % res) if res else u"?",
                                 item.get('mode_label') or u'')
    if cov is not None:
        detail += u" · %.0f%%" % cov
    return {
        'id': item.get('id'),
        'name': item.get('id'),
        'date': item.get('date'),
        'cloud_pct': item.get('cloud_cover'),
        'cloud_display': format_cloud(item.get('cloud_cover')),
        'mgrs': detail,
        'coverage_pct': cov,
        'platform': item.get('platform'),
        'mode_label': item.get('mode_label'),
        'is_pan': bool(item.get('is_pan')),
        'res_m': res,
        'incidence_deg': item.get('incidence_deg'),
        'zip_size': item.get('zip_size'),
        'thumbnail': item.get('thumbnail'),
        'source': 'SPOT',
    }


def row_info(row):
    """Texto do painel da cena selecionada."""
    inc = row.get('incidence_deg')
    size = row.get('zip_size')
    return (u"Data: %s | %s %s | Nuvens: %s | Incidência: %s | Pacote: %s\n"
            u"Nível 1A alinhado automaticamente à Esri World Imagery no download." % (
                row.get('date'), row.get('platform') or u'SPOT', row.get('mode_label') or u'',
                format_cloud(row.get('cloud_pct')),
                (u"%+.0f°" % float(inc)) if inc is not None else u"n/d",
                (u"%.0f MB" % (float(size) / 1e6)) if size else u"n/d"))


# --------------------------------------------------------------------- chave do GEODES
def key_file():
    appdata = os.environ.get('APPDATA') or os.path.expanduser('~')
    return os.path.join(appdata, 'ArcGEE', 'geodes_config.json')


def load_api_key():
    """Chave salva pelo usuario; na falta dela, a variavel de ambiente GEODES_API_KEY."""
    path = key_file()
    try:
        if os.path.exists(path):
            with io.open(path, 'r', encoding='utf-8') as f:
                key = (json.load(f).get('api_key') or u'').strip()
                if key:
                    return key
    except Exception:
        pass
    return (os.environ.get(KEY_ENV) or u'').strip() or None


def save_api_key(key):
    path = key_file()
    folder = os.path.dirname(path)
    try:
        if not os.path.isdir(folder):
            os.makedirs(folder)
        data = json.dumps({'api_key': (key or u'').strip()}, ensure_ascii=False)
        if not isinstance(data, unicode):
            data = data.decode('utf-8')
        with io.open(path, 'w', encoding='utf-8') as f:
            f.write(data)
        return True
    except Exception:
        return False


def mask_key(key):
    key = key or u''
    return (key[:4] + u'…' + key[-4:]) if len(key) > 10 else (u'•' * len(key))


def looks_like_key(key):
    return bool(re.match(r'^[A-Za-z0-9_\-]{20,200}$', (key or u'').strip()))


def check_key(key=None):
    """{'success', 'max_quota', 'remaining_quota'} ou {'success': False, 'message'}."""
    key = key or load_api_key()
    if not key:
        return {'success': False, 'message': u"Nenhuma chave do GEODES configurada."}
    return gee_bridge.run_backend_cmd('spot_check_key', {'api_key': key}, python_exe=gee_bridge.find_python3_gdal())


def quota_text(resp):
    if not resp or not resp.get('success'):
        return None
    return u"%s de %s downloads disponíveis nesta hora" % (resp.get('remaining_quota'), resp.get('max_quota'))


# ------------------------------------------------------------------------------ backend
def _area_params(bbox, geojson_file):
    if geojson_file:
        return {'geojson_file': geojson_file}
    if bbox:
        return {'bbox': ','.join('%.8f' % float(v) for v in bbox)}
    return {}


def search(sensor_code, start_date, end_date, bbox=None, geojson_file=None, max_images=500, max_cloud=None):
    g = group_of(sensor_code)
    if not g:
        return {'success': False, 'message': u"Grupo SPOT desconhecido: %s" % sensor_code}
    params = {'start_date': start_date, 'end_date': end_date, 'satellites': g[2], 'kind': g[3],
              'max_items': max_images, 'max_cloud': max_cloud}
    params.update(_area_params(bbox, geojson_file))
    resp = gee_bridge.run_backend_cmd('spot_search', params, python_exe=gee_bridge.find_python3_gdal())
    if not resp.get('success'):
        return resp
    return {'success': True, 'images': [item_to_row(i) for i in resp.get('items', [])]}


def _progress(on_progress):
    if not on_progress:
        return None

    def cb(line):
        text = (line or u'').replace('[ArcGEE] ', '')
        m = re.search(r'PROGRESS\s+(\d+)\s*/\s*100', text)
        if m:
            return
        if u'SPOT' in text or u'Esri' in text or u'pir' in text:
            on_progress(text)
    return cb


def download(img_id, sensor_code, mode, out_tif, bbox=None, geojson_file=None, on_progress=None):
    """Baixa a cena (ou usa o cache), alinha e recorta. Resposta: 'file', 'rgb_bands', 'valid_pct'."""
    key = load_api_key()
    if not key:
        return {'success': False, 'needs_key': True,
                'message': u"O download de cenas SPOT exige a chave de API gratuita do GEODES.\n\n"
                           u"Abra Configurações > Chave do GEODES (SPOT) e siga o tutorial."}
    if mode not in dict(PRODUCTS):
        mode = 'false'
    params = {'item_id': img_id, 'mode': mode, 'out': out_tif, 'api_key': key, 'align': True}
    params.update(_area_params(bbox, geojson_file))
    resp = gee_bridge.run_backend_cmd('spot_download', params, on_progress=_progress(on_progress),
                                      python_exe=gee_bridge.find_python3_gdal())
    if resp.get('success') and not resp.get('rgb_bands'):
        resp['rgb_bands'] = None
    return resp


def alignment_text(resp):
    a = (resp or {}).get('alignment') or {}
    if a.get('applied'):
        return u"alinhada à Esri (deslocamento corrigido: %.0f m; resíduo: %s m)" % (
            a.get('shift_m') or 0, (u"%.0f" % a['residual_m']) if a.get('residual_m') is not None else u"n/d")
    return u"SEM alinhamento (%s): posição com erro de até ~500 m" % (a.get('reason') or u"não medido")


def thumbnail(row, out_png):
    return gee_bridge.run_backend_cmd('spot_thumb', {'href': row.get('thumbnail'), 'out': out_png},
                                      python_exe=gee_bridge.find_python3_gdal())
