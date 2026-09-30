# -*- coding: utf-8 -*-
"""
ArcMagery - Esri World Imagery Wayback na janela principal (Python 2.7).

Mesma interface do arcmagery_gehist (a janela trata as duas fontes de tiles do mesmo jeito):
cada zoom e um "sensor" 'EWB:<zoom>' (ou 'EWB:ALL' para todos) e cada VERSAO do Wayback com
imagem diferente na area e uma linha da tabela, com a data de CAPTURA da cena (metadados publicos
da Esri), o satelite e a resolucao. O download usa o xyz_download (Web Mercator EPSG:3857, grade
nativa dos tiles) e grava a data de captura nas tags do GeoTIFF.
"""
from __future__ import division

import re

import arcmagery_tilesource as ts
import gee_bridge
from backend import tilemath

PREFIX = 'EWB:'
ALL = PREFIX + 'ALL'
ZOOMS = [15, 16, 17, 18, 19]          # deve bater com backend/run_gee.WAYBACK_ZOOMS
MAX_TILES = 100000                    # deve bater com backend/xyz_core.DEFAULT_MAX_TILES
TILES_PER_SECOND = 100.0


def _res_label(zoom, lat=-15.0):
    res = tilemath.ground_resolution(lat, zoom)
    return (u"%.2f m" % res).replace(u'.', u',')


WAYBACK_SENSOR_DISPLAY = [(u"Esri Wayback · TODOS os zooms (15 a 19) · uma linha por versão e zoom", ALL)] + [
    (u"Esri Wayback · só o zoom %d (~%s/pixel)" % (z, _res_label(z)), PREFIX + str(z)) for z in ZOOMS]

_META_COMMON = {
    'agency': u'Esri World Imagery Wayback (Maxar, Airbus, ...)',
    'period_display': u"versões publicadas desde 2014 (captura conforme a área)",
    'end_year': None, 'native_res': None,
    'available_bands': u"RGB (cor natural, 3 bandas) · Web Mercator EPSG:3857",
    'notes': u"Cada linha é uma versão do Wayback com imagem diferente no centro da área.",
}
WAYBACK_SENSOR_METADATA = dict(
    (PREFIX + str(z), dict(_META_COMMON, name=u"Esri Wayback z%d" % z, collection=u"Wayback z%d" % z,
                            res=u'~%s' % _res_label(z))) for z in ZOOMS)
WAYBACK_SENSOR_METADATA[ALL] = dict(_META_COMMON, name=u"Esri Wayback (todos os zooms)",
                                    collection=u"Wayback z15-z19", res=u'~0,3 a ~4,6 m')

PRODUCTS = [('rgb', u'Cor natural (RGB) - versão escolhida do Wayback')]


def is_wayback(sensor_code):
    return bool(sensor_code) and str(sensor_code).startswith(PREFIX)


def zoom_of(sensor_code):
    if not is_wayback(sensor_code) or sensor_code == ALL:
        return None
    return int(str(sensor_code)[len(PREFIX):])


zoom_of_row_id = ts.zoom_of_row_id


def release_of_row_id(img_id):
    m = re.search(r'EsriWayback_\d{8}_r(\d+)_z\d+$', img_id or '')
    return int(m.group(1)) if m else None


def composition_items(sensor_code):
    return [u"%s - %s" % (m, label) for m, label in PRODUCTS]


def _date_br(iso):
    s = (iso or u'')[:10]
    return u"%s/%s/%s" % (s[8:10], s[5:7], s[0:4]) if len(s) == 10 else u"n/d"


def version_to_row(v, zoom=None):
    zoom = int(v.get('zoom') or zoom)
    capture = v.get('capture_date') or v.get('release_date')
    res = v.get('resolution_m')
    sensor = v.get('sensor_name') or v.get('sensor') or u''
    return {
        'id': u"EsriWayback_%s_r%d_z%d" % ((capture or u'').replace(u'-', u''), int(v['release_num']), zoom),
        'name': u"EsriWayback_%s_r%d_z%d" % ((capture or u'').replace(u'-', u''), int(v['release_num']), zoom),
        'date': capture,
        'cloud_pct': None,
        'cloud_display': u"versão %s" % _date_br(v.get('release_date')),
        'zoom_display': u"%d (~%s)" % (zoom, _res_label(zoom)),
        'mgrs': (u"%s %s%s" % (sensor, v.get('provider') or u'',
                               (u" · %.2f m" % float(res)).replace(u'.', u',') if res not in (None, '') else u'')).strip(),
        'provider': v.get('provider'),
        'release_num': int(v['release_num']),
        'release_date': v.get('release_date'),
        'capture_known': bool(v.get('capture_date')),
        'zoom': zoom,
        'source': 'WAYBACK',
    }


in_period = ts.in_period
_area_params = ts.area_params
_progress_cb = ts.progress_callback


def estimate(bbox, zoom):
    return tilemath.estimate(bbox, zoom)


def estimate_text(bbox, zoom):
    return ts.estimate_text(estimate(bbox, zoom), zoom, TILES_PER_SECOND)


def check_limit(bbox, zoom):
    return ts.limit_message(estimate(bbox, zoom), zoom, MAX_TILES)


def search(sensor_code, start_date, end_date, bbox=None, geojson_file=None, on_progress=None):
    zoom = zoom_of(sensor_code)
    params = {'zoom': zoom} if zoom else {'zooms': 'all'}
    params.update(_area_params(bbox, geojson_file))
    if on_progress:
        on_progress(u"Consultando as versões do Esri Wayback (cerca de 20 s)...", None)
    resp = gee_bridge.run_backend_cmd('esri_versions', params, python_exe=gee_bridge.find_python3_gdal())
    if not resp.get('success'):
        return resp
    versions = resp.get('versions', [])
    rows = [version_to_row(v, zoom) for v in versions]
    rows = [r for r in rows if in_period(r['date'], start_date, end_date)]
    return {'success': True, 'images': rows, 'total_dates': len(versions)}


def download(img_id, sensor_code, out_tif, bbox=None, geojson_file=None, on_progress=None):
    release = release_of_row_id(img_id)
    if not release:
        return {'success': False, 'message': u"Identificador de versão inválido: %s" % img_id}
    zoom = zoom_of_row_id(img_id) or zoom_of(sensor_code)
    params = {'zoom': zoom, 'provider': 'esri', 'wayback_release': release, 'out': out_tif,
              'compression': 'JPEG', 'crs': None, 'footprints': False, 'workers': gee_bridge.tile_threads()}
    params.update(_area_params(bbox, geojson_file))
    resp = gee_bridge.run_backend_cmd('xyz_download', params,
                                      on_progress=_progress_cb(on_progress, u"Baixando Esri Wayback:"),
                                      python_exe=gee_bridge.find_python3_gdal())
    if resp.get('success'):
        resp['rgb_bands'] = [0, 1, 2]
    return resp


def thumbnail(row, bbox, out_png, geojson_file=None):
    params = {'zoom': row.get('zoom'), 'wayback_release': row.get('release_num'), 'out': out_png}
    params.update(_area_params(bbox, geojson_file))
    return gee_bridge.run_backend_cmd('wayback_thumb', params, python_exe=gee_bridge.find_python3_gdal())
