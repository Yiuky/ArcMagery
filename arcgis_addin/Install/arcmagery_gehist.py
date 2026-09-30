# -*- coding: utf-8 -*-
"""
ArcMagery - Google Earth historico (catalogo "Time Machine") na janela principal (Python 2.7).

Mesmo modelo do CBERS (arcmagery_inpe): a janela trata cada nivel de zoom como um "sensor" com
codigo 'GEH:<zoom>' e cada DATA do historico como uma "cena" da tabela. Este modulo nao depende
do Tk:
  * catalogo de zooms (rotulo, resolucao) e o produto unico (RGB);
  * conversao das datas do backend (gehist_dates) em linhas da tabela, filtradas pelo periodo;
  * chamadas ao backend (gehist_dates / gehist_download / gehist_thumb) no Python 3.

A grade do Google Earth historico e geografica (EPSG:4326): o GeoTIFF sai nela, sem reamostragem.
"""
from __future__ import division

import re

import arcmagery_tilesource as ts
import gee_bridge
from backend import tilemath

PREFIX = 'GEH:'
ALL = PREFIX + 'ALL'          # varre todos os zooms: uma linha por (data, zoom), zoom numa coluna
DEFAULT_ZOOM = 18
ALL_ZOOMS = [15, 16, 17, 18, 19, 20]   # deve bater com backend/gehist_core.ALL_ZOOMS
MAX_TILES = 100000   # deve bater com backend/gehist_core.MAX_TILES
TILES_PER_SECOND = 140.0  # medido na rede da SEMA com 48 threads (225 tiles em 1,6 s)

_ZOOMS = [18, 19, 20, 17, 16, 15]


def _res_label(zoom):
    res = tilemath.keyhole_tile_deg(zoom) / tilemath.TILE_SIZE * tilemath.METERS_PER_DEGREE
    return (u"%.2f m" % res).replace(u'.', u',') if res < 10 else u"%.0f m" % res


GEHIST_SENSOR_DISPLAY = [(u"Google Earth histórico · TODOS os zooms (15 a 20) · uma linha por data e zoom", ALL)] + [
    (u"Google Earth histórico · só o zoom %d (~%s/pixel)" % (z, _res_label(z)), PREFIX + str(z)) for z in _ZOOMS]

GEHIST_SENSOR_METADATA = dict(
    (PREFIX + str(z), {
        'name': u"Google Earth histórico z%d" % z,
        'agency': u'Google Earth (Maxar, Airbus, ...)',
        'collection': u"Time Machine z%d" % z,
        'period_display': u"conforme a área (em geral 1985 até o presente)",
        'end_year': None,
        'res': u'~%s' % _res_label(z),
        'native_res': None,
        'available_bands': u"RGB (cor natural, 3 bandas) · grade geográfica EPSG:4326",
        'notes': u"Cada linha da tabela é uma data do histórico (como no Google Earth Pro).",
    }) for z in _ZOOMS)
GEHIST_SENSOR_METADATA[ALL] = {
    'name': u"Google Earth histórico (todos os zooms)", 'agency': u'Google Earth (Maxar, Airbus, ...)',
    'collection': u"Time Machine z15-z20", 'period_display': u"conforme a área (em geral 1985 até o presente)",
    'end_year': None, 'res': u'~0,15 a ~4,8 m', 'native_res': None,
    'available_bands': u"RGB (cor natural, 3 bandas) · grade geográfica EPSG:4326",
    'notes': u"Cada linha é uma data num zoom. Cobertura com '~' = estimada por amostragem (área grande ou z20).",
}

PRODUCTS = [('rgb', u'Cor natural (RGB) - imagem da data escolhida')]


def is_gehist(sensor_code):
    return bool(sensor_code) and str(sensor_code).startswith(PREFIX)


def zoom_of(sensor_code):
    """Zoom do sensor; None para 'todos os zooms' (o zoom vem de cada linha)."""
    if not is_gehist(sensor_code) or sensor_code == ALL:
        return None
    return int(str(sensor_code)[len(PREFIX):])


zoom_of_row_id = ts.zoom_of_row_id


def composition_items(sensor_code):
    return [u"%s - %s" % (m, label) for m, label in PRODUCTS]


def row_id(date, zoom):
    return u"GoogleEarth_%s_z%d" % ((date or u'').replace(u'-', u''), zoom)


def _date_of_row_id(img_id):
    m = re.search(r'GoogleEarth_(\d{4})(\d{2})(\d{2})_z\d+', img_id or '')
    return u"%s-%s-%s" % m.groups() if m else None


def date_to_row(d, zoom=None):
    """Data do backend -> linha no formato de images_cache da janela principal."""
    zoom = int(d.get('zoom') or zoom)
    cov = float(d.get('coverage_pct') or 0.0)
    approx = u"~" if d.get('estimated') else u""
    return {
        'id': row_id(d.get('date'), zoom),
        'name': row_id(d.get('date'), zoom),
        'date': d.get('date'),
        'cloud_pct': None,
        'cloud_display': approx + ((u"%.0f%% da área" % cov) if cov < 99.95 else u"100% da área"),
        'zoom_display': u"%d (~%s)" % (zoom, _res_label(zoom)),
        'estimated': bool(d.get('estimated')),
        'coverage_pct': cov,
        'mgrs': d.get('provider') or u'provedor n/d',
        'provider': d.get('provider'),
        'zoom': zoom,
        'source': 'GEHIST',
    }


in_period = ts.in_period
_area_params = ts.area_params


def _workers():
    return gee_bridge.tile_threads()


_progress_cb = ts.progress_callback


def estimate(bbox, zoom):
    return tilemath.keyhole_estimate(bbox, zoom)


def estimate_text(bbox, zoom):
    return ts.estimate_text(estimate(bbox, zoom), zoom, TILES_PER_SECOND)


def check_limit(bbox, zoom):
    """Mensagem de erro se a area exceder o limite de tiles; None se estiver ok."""
    return ts.limit_message(estimate(bbox, zoom), zoom, MAX_TILES)


def search(sensor_code, start_date, end_date, bbox=None, geojson_file=None, on_progress=None):
    """Lista as datas da area no periodo -> {'success', 'images': [linhas]}."""
    zoom = zoom_of(sensor_code)
    params = {'zoom': zoom, 'workers': _workers()} if zoom else {'zooms': 'all', 'workers': _workers()}
    params.update(_area_params(bbox, geojson_file))
    resp = gee_bridge.run_backend_cmd('gehist_dates', params,
                                      on_progress=_progress_cb(on_progress, u"Consultando o histórico do Google Earth:"),
                                      python_exe=gee_bridge.find_python3_gdal())
    if not resp.get('success'):
        return resp
    rows = [date_to_row(d, zoom) for d in resp.get('dates', []) if d.get('date')
            and in_period(d['date'], start_date, end_date)]
    return {'success': True, 'images': rows, 'total_dates': len(resp.get('dates', []))}


def download(img_id, sensor_code, out_tif, bbox=None, geojson_file=None, on_progress=None):
    """Baixa a data da linha. A resposta inclui 'file', 'rgb_bands' e 'valid_pct' (cobertura)."""
    date = _date_of_row_id(img_id)
    if not date:
        return {'success': False, 'message': u"Identificador de data inválido: %s" % img_id}
    params = {'zoom': zoom_of_row_id(img_id) or zoom_of(sensor_code), 'date': date, 'out': out_tif,
              'workers': _workers()}
    params.update(_area_params(bbox, geojson_file))
    resp = gee_bridge.run_backend_cmd('gehist_download', params,
                                      on_progress=_progress_cb(on_progress, u"Baixando Google Earth de %s:" % date),
                                      python_exe=gee_bridge.find_python3_gdal())
    if resp.get('success'):
        resp['rgb_bands'] = [0, 1, 2]
        resp['valid_pct'] = resp.get('coverage_pct')   # aviso de cobertura parcial da janela principal
    return resp


def thumbnail(row, bbox, out_png, geojson_file=None):
    params = {'zoom': row.get('zoom'), 'date': row.get('date'), 'out': out_png}
    params.update(_area_params(bbox, geojson_file))
    return gee_bridge.run_backend_cmd('gehist_thumb', params, python_exe=gee_bridge.find_python3_gdal())
