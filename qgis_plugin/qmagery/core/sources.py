# -*- coding: utf-8 -*-
"""
Regras de cada fonte de imagens: parâmetros enviados ao backend e linhas da tabela.

Sem dependência do Qt/QGIS (testável no CI). Espelha os módulos do ArcMagery (gee_bridge,
arcmagery_inpe, arcmagery_spot, arcmagery_gehist, arcmagery_wayback): tests/qgis/test_paridade.py
compara os parâmetros e as linhas com os de lá, e tests/qgis/test_contrato_backend.py confere que
cada parâmetro é lido pelo comando correspondente do backend.

Uma "requisição" é a tupla (comando, parâmetros, prazo de inatividade em segundos).
"""
import math
import re

from . import catalog_constants as cat

SOURCES = ('gee', 'inpe', 'spot', 'gehist', 'wayback')

SOURCE_LABELS = {
    'gee': 'Google Earth Engine',
    'inpe': 'CBERS / Amazônia-1',
    'spot': 'SPOT 1-5 (CNES)',
    'gehist': 'Google Earth histórico',
    'wayback': 'Esri Wayback',
}

# Prazo de INATIVIDADE (s): o relógio zera a cada linha de progresso do backend (igual ao ArcMagery)
TIMEOUTS = {
    'check': 60, 'search': 120, 'thumb': 90, 'download': 900,
    'stac_search': 120, 'stac_thumb': 120, 'stac_download': 1800,
    'spot_search': 180, 'spot_thumb': 120, 'spot_download': 3600, 'spot_check_key': 60,
    'gehist_dates': 1800, 'gehist_thumb': 120, 'gehist_download': 4 * 3600,
    'esri_versions': 600, 'wayback_thumb': 120, 'xyz_download': 4 * 3600, 'xyz_estimate': 60,
    'selfcheck': 60, 'pylibs_status': 60, 'pylibs_install': 900, 'sources_info': 60,
}
DEFAULT_TIMEOUT = 120

GEE_MAX_IMAGES = 100
INPE_MAX_ITEMS = 100
SPOT_MAX_ITEMS = 500


def timeout_for(command):
    return TIMEOUTS.get(command, DEFAULT_TIMEOUT)


# --------------------------------------------------------------------------- área
def area_params(bbox=None, geojson_file=None):
    """AOI (camada vetorial exportada) tem prioridade sobre a extensão do mapa."""
    if geojson_file:
        return {'geojson_file': geojson_file}
    if bbox:
        return {'bbox': ','.join('%.8f' % float(v) for v in bbox)}
    return {}


def area_bbox_params(bbox):
    """Comandos que só aceitam bbox (miniatura do GEE)."""
    return {'bbox': ','.join('%.8f' % float(v) for v in bbox)} if bbox else {}


# --------------------------------------------------------------------------- sensores
def sensors_for(source):
    return {
        'gee': cat.GEE_SENSOR_DISPLAY,
        'inpe': cat.INPE_SENSOR_DISPLAY,
        'spot': cat.SPOT_SENSOR_DISPLAY,
        'gehist': cat.GEHIST_SENSOR_DISPLAY,
        'wayback': cat.WAYBACK_SENSOR_DISPLAY,
    }[source]


def sensor_metadata(source, sensor):
    table = {
        'gee': cat.GEE_SENSOR_METADATA,
        'inpe': cat.INPE_SENSOR_METADATA,
        'spot': cat.SPOT_SENSOR_METADATA,
        'gehist': cat.GEHIST_SENSOR_METADATA,
        'wayback': cat.WAYBACK_SENSOR_METADATA,
    }[source]
    return table.get(sensor) or {}


def compositions_for(source, sensor):
    """[(código, rótulo)] da combobox de composição."""
    if source == 'gee':
        return [(c[0], c[1]) for c in cat.GEE_COMPOSITIONS.get(sensor, cat.GEE_COMPOSITIONS['S2'])]
    if source == 'inpe':
        cid = inpe_collection(sensor)
        labels = dict(cat.INPE_PRODUCTS)
        return [(m, labels.get(m, m.upper())) for m in cat.INPE_COLLECTION_MODES.get(cid, ['rgb', 'false', 'multi'])]
    if source == 'spot':
        labels = dict(cat.SPOT_PRODUCTS)
        return [(m, labels[m]) for m in cat.spot_modes_for(sensor)]
    return [('rgb', 'Cor natural (RGB) - imagem da data escolhida')]


def gee_composition(sensor, code):
    """(código, rótulo, bandas, tipo) da composição do GEE; None se desconhecida."""
    for c in cat.GEE_COMPOSITIONS.get(sensor, []):
        if c[0] == code:
            return c
    return None


def inpe_collection(sensor):
    return str(sensor or '')[len(cat.INPE_PREFIX):] if str(sensor or '').startswith(cat.INPE_PREFIX) else sensor


def spot_group(sensor):
    return cat.SPOT_BY_CODE.get(sensor)


def tile_zoom(sensor, prefix):
    """Zoom do sensor GEH:/EWB:; None para 'todos os zooms' (o zoom vem de cada linha)."""
    s = str(sensor or '')
    if not s.startswith(prefix) or s.endswith('ALL'):
        return None
    try:
        return int(s[len(prefix):])
    except ValueError:
        return None


def default_dates(source):
    """(início, fim) em ISO; None = usar os atalhos de dias."""
    if source == 'spot':
        return '1986-01-01', '2015-12-31'
    return None


# --------------------------------------------------------------------------- formatação
def fmt_pct(value, digits=0, empty=u'n/d'):
    if value is None or value == '':
        return empty
    try:
        return (u"%%.%df%%%%" % digits % float(value)).replace(u'.', u',')
    except (TypeError, ValueError):
        return u"%s%%" % value


def date_br(iso):
    s = (iso or u'')[:10]
    return u"%s/%s/%s" % (s[8:10], s[5:7], s[0:4]) if len(s) == 10 else (iso or u'n/d')


def in_period(date, start_date, end_date):
    """Datas ISO (AAAA-MM-DD); limites vazios não filtram; linha sem data nunca entra."""
    d = (date or u'')[:10]
    return bool(d) and (not start_date or d >= start_date) and (not end_date or d <= end_date)


def mercator_res_m(zoom, lat=-15.0):
    return math.cos(math.radians(lat)) * 2.0 * math.pi * 6378137.0 / (256 * (2 ** zoom))


def keyhole_res_m(zoom):
    return 360.0 / (2 ** zoom) / 256 * (math.pi * 6378137.0 / 180.0)


def res_label(meters):
    return (u"%.2f m" % meters).replace(u'.', u',') if meters < 10 else u"%.0f m" % meters


# --------------------------------------------------------------------------- linhas da tabela
def _row(source, rid, date, cloud, detail, name, **extra):
    row = {'source': source, 'id': rid, 'date': date, 'c_date': date or u'n/d', 'c_cloud': cloud,
           'c_detail': detail, 'c_name': name}
    row.update(extra)
    return row


def gee_row(img):
    path, wrs_row = img.get('path'), img.get('row')
    detail = img.get('mgrs') or ((u"%s/%s" % (path, wrs_row)) if path and wrs_row else u'-')
    return _row('gee', img.get('id'), img.get('date'), fmt_pct(img.get('cloud_pct'), 1), detail,
                img.get('name') or (img.get('id') or u'').split('/')[-1], cloud_pct=img.get('cloud_pct'))


def inpe_row(item):
    cov = item.get('coverage_pct')
    tile = (item.get('path_row') or u'').strip('/') or u'-'
    if cov is not None:
        # footprint retangular (ex.: CBERS-2/2B): a cobertura é só um limite superior
        tile = u"%s · %s%.0f%% da área" % (tile, u"até " if item.get('coverage_is_estimate') else u"", cov)
    return _row('inpe', item.get('id'), item.get('date'), fmt_pct(item.get('cloud_cover')), tile, item.get('id'),
                cloud_pct=item.get('cloud_cover'), coverage_pct=cov, collection=item.get('collection'),
                thumbnail=item.get('thumbnail'))


def spot_row(item):
    cov = item.get('coverage_pct')
    res = item.get('res_m')
    detail = u"%s · %s · %s" % (item.get('platform') or u'SPOT', (u"%.1f m" % res).replace(u'.0 m', u' m') if res
                                 else u"?", item.get('mode_label') or u'')
    if cov is not None:
        detail += u" · %.0f%% da área" % cov
    return _row('spot', item.get('id'), item.get('date'), fmt_pct(item.get('cloud_cover')), detail, item.get('id'),
                cloud_pct=item.get('cloud_cover'), coverage_pct=cov, platform=item.get('platform'),
                is_pan=bool(item.get('is_pan')), thumbnail=item.get('thumbnail'), zip_size=item.get('zip_size'))


def gehist_row(d, zoom=None):
    zoom = int(d.get('zoom') or zoom)
    cov = float(d.get('coverage_pct') or 0.0)
    approx = u"~" if d.get('estimated') else u""
    rid = u"GoogleEarth_%s_z%d" % ((d.get('date') or u'').replace(u'-', u''), zoom)
    cover = approx + (u"%.0f%% da área" % cov if cov < 99.95 else u"100% da área")
    detail = u"%s · zoom %d (~%s)" % (d.get('provider') or u'provedor n/d', zoom, res_label(keyhole_res_m(zoom)))
    return _row('gehist', rid, d.get('date'), cover, detail, rid, zoom=zoom, coverage_pct=cov,
                provider=d.get('provider'))


def wayback_row(v, zoom=None):
    zoom = int(v.get('zoom') or zoom)
    capture = v.get('capture_date') or v.get('release_date')
    res = v.get('resolution_m')
    sensor = v.get('sensor_name') or v.get('sensor') or u''
    rid = u"EsriWayback_%s_r%d_z%d" % ((capture or u'').replace(u'-', u''), int(v['release_num']), zoom)
    detail = (u"%s %s%s · zoom %d" % (sensor, v.get('provider') or u'',
                                      (u" · %.2f m" % float(res)).replace(u'.', u',') if res not in (None, '') else u'',
                                      zoom)).strip()
    return _row('wayback', rid, capture, u"versão %s" % date_br(v.get('release_date')), detail, rid,
                zoom=zoom, release_num=int(v['release_num']), release_date=v.get('release_date'),
                capture_known=bool(v.get('capture_date')))


def rows_from_result(source, sensor, res, start_date=None, end_date=None):
    """Resposta do comando de busca -> linhas da tabela (Google Earth e Wayback filtrados pelo período)."""
    if source == 'gee':
        return [gee_row(i) for i in res.get('images') or []]
    if source == 'inpe':
        return [inpe_row(i) for i in res.get('items') or []]
    if source == 'spot':
        return [spot_row(i) for i in res.get('items') or []]
    if source == 'gehist':
        zoom = tile_zoom(sensor, cat.GEHIST_PREFIX)
        return [gehist_row(d, zoom) for d in res.get('dates') or []
                if d.get('date') and in_period(d['date'], start_date, end_date)]
    if source == 'wayback':
        zoom = tile_zoom(sensor, cat.WAYBACK_PREFIX)
        rows = [wayback_row(v, zoom) for v in res.get('versions') or []]
        return [r for r in rows if in_period(r['date'], start_date, end_date)]
    return []


# --------------------------------------------------------------------------- requisições
def search_request(source, sensor, start_date, end_date, bbox=None, geojson_file=None, project=None,
                   workers=None):
    area = area_params(bbox, geojson_file)
    if source == 'gee':
        p = {'sensor': sensor, 'start_date': start_date, 'end_date': end_date, 'max_images': GEE_MAX_IMAGES}
        if project:
            p['project'] = project
        cmd = 'search'
    elif source == 'inpe':
        p = {'collections': inpe_collection(sensor), 'start_date': start_date, 'end_date': end_date,
             'max_items': INPE_MAX_ITEMS}
        cmd = 'stac_search'
    elif source == 'spot':
        g = spot_group(sensor)
        if not g:
            raise ValueError(u"Grupo SPOT desconhecido: %s" % sensor)
        p = {'start_date': start_date, 'end_date': end_date, 'satellites': g[2], 'kind': g[3],
             'max_items': SPOT_MAX_ITEMS}
        cmd = 'spot_search'
    elif source == 'gehist':
        zoom = tile_zoom(sensor, cat.GEHIST_PREFIX)
        p = {'zoom': zoom} if zoom else {'zooms': 'all'}
        if workers:
            p['workers'] = workers
        cmd = 'gehist_dates'
    elif source == 'wayback':
        zoom = tile_zoom(sensor, cat.WAYBACK_PREFIX)
        p = {'zoom': zoom} if zoom else {'zooms': 'all'}
        cmd = 'esri_versions'
    else:
        raise ValueError(u"Fonte desconhecida: %s" % source)
    p.update(area)
    return cmd, p, timeout_for(cmd)


def download_request(source, sensor, row, comp, out_tif, bbox=None, geojson_file=None, project=None,
                     custom_bands=None, load_mode='multiband', scale=None, api_key=None, workers=None):
    area = area_params(bbox, geojson_file)
    if source == 'gee':
        p = {'ids': row['id'], 'sensor': sensor, 'comp': comp, 'load_mode': load_mode, 'out': out_tif,
             'crs': 'EPSG:4674'}
        if custom_bands:
            p['custom_bands'] = custom_bands
        if scale:
            p['scale'] = float(scale)
        if project:
            p['project'] = project
        cmd = 'download'
    elif source == 'inpe':
        p = {'collection': row.get('collection') or inpe_collection(sensor), 'item_id': row['id'], 'mode': comp,
             'out': out_tif}
        cmd = 'stac_download'
    elif source == 'spot':
        mode = comp if comp in dict(cat.SPOT_PRODUCTS) else 'false'
        p = {'item_id': row['id'], 'mode': mode, 'out': out_tif, 'api_key': api_key, 'align': True}
        cmd = 'spot_download'
    elif source == 'gehist':
        p = {'zoom': row.get('zoom') or tile_zoom(sensor, cat.GEHIST_PREFIX) or 18, 'date': row['date'],
             'out': out_tif}
        if workers:
            p['workers'] = workers
        cmd = 'gehist_download'
    elif source == 'wayback':
        p = {'zoom': row.get('zoom') or tile_zoom(sensor, cat.WAYBACK_PREFIX) or 17, 'provider': 'esri',
             'wayback_release': row['release_num'], 'out': out_tif, 'compression': 'JPEG', 'footprints': False}
        if workers:
            p['workers'] = workers
        cmd = 'xyz_download'
    else:
        raise ValueError(u"Fonte desconhecida: %s" % source)
    p.update(area)
    return cmd, p, timeout_for(cmd)


def thumb_request(source, sensor, row, comp, out_png, bbox=None, geojson_file=None, project=None):
    if source == 'gee':
        info = gee_composition(sensor, comp)
        # índices, fórmulas e listas digitadas: a miniatura mostra a cor natural
        thumb_comp = comp if info and info[3] in ('rgb', 'multi') else cat.GEE_COMPOSITIONS.get(sensor, [('432',)])[0][0]
        p = {'image_id': row['id'], 'sensor': sensor, 'comp': thumb_comp, 'out': out_png}
        if project:
            p['project'] = project
        p.update(area_bbox_params(bbox))
        cmd = 'thumb'
    elif source == 'inpe':
        p = {'collection': row.get('collection') or inpe_collection(sensor), 'item_id': row['id'],
             'href': row.get('thumbnail'), 'out': out_png}
        cmd = 'stac_thumb'
    elif source == 'spot':
        if not row.get('thumbnail'):
            raise ValueError(u"Esta cena SPOT não tem miniatura no catálogo do GEODES.")
        p = {'href': row['thumbnail'], 'out': out_png}
        cmd = 'spot_thumb'
    elif source == 'gehist':
        p = {'zoom': row['zoom'], 'date': row['date'], 'out': out_png}
        p.update(area_params(bbox, geojson_file))
        cmd = 'gehist_thumb'
    elif source == 'wayback':
        p = {'zoom': row['zoom'], 'wayback_release': row['release_num'], 'out': out_png}
        p.update(area_params(bbox, geojson_file))
        cmd = 'wayback_thumb'
    else:
        raise ValueError(u"Fonte desconhecida: %s" % source)
    return cmd, p, timeout_for(cmd)


# --------------------------------------------------------------------------- nomes e simbologia
def safe_name(text, limit=90):
    s = re.sub(r'[^A-Za-z0-9_.-]+', '_', text or u'').strip('._')
    return (s[:limit].rstrip('._') or 'imagem')


def output_stem(source, sensor, row, comp):
    """Nome do arquivo (sem extensão): fonte, data e identificador legíveis."""
    if source == 'gee':
        return safe_name(u"%s_%s_%s" % (sensor, (row.get('c_name') or row['id']).split('/')[-1], comp))
    if source in ('inpe', 'spot'):
        return safe_name(u"%s_%s" % (row['id'], comp))
    return safe_name(row['id'])


def layer_name(source, sensor, row, comp):
    date = (row.get('date') or u'')[:10]
    if source == 'gee':
        return u"%s %s %s (%s)" % (sensor, date, (row.get('c_name') or u'').split('_')[-1] or row['id'], comp)
    if source == 'inpe':
        return u"%s (%s)" % (row['id'], comp)
    if source == 'spot':
        return u"%s %s (%s)" % (row.get('platform') or u'SPOT', date, comp)
    if source == 'gehist':
        return u"Google Earth %s z%s" % (date, row.get('zoom'))
    if source == 'wayback':
        return u"Esri Wayback %s z%s (versão %s)" % (date, row.get('zoom'), date_br(row.get('release_date')))
    return row['id']


def gee_style(sensor, comp, custom_bands=None):
    """Como exibir o GeoTIFF do GEE: ('rgb', [i, j, k] 0-based) | ('index', None) | (None, None)."""
    info = gee_composition(sensor, comp)
    custom = (custom_bands or u'').strip()
    if custom and is_math_expr(custom):
        return 'index', None
    if custom:
        bands = [b.strip().upper() for b in custom.split(',') if b.strip()]
        return ('rgb', [0, 1, 2]) if len(bands) >= 3 else (None, None)
    if not info or info[3] in ('index', 'math'):
        return 'index', None
    bands = info[2]
    if info[3] == 'rgb':
        return 'rgb', [0, 1, 2]
    natural = cat.GEE_NATURAL_BANDS.get(sensor) or []
    if natural and all(b in bands for b in natural):
        return 'rgb', [bands.index(b) for b in natural]
    return 'rgb', [0, 1, 2] if len(bands) >= 3 else None


def is_math_expr(text):
    """Fórmula x lista de bandas: cópia de backend/gee_core.is_math_expr ('B3-B5' é intervalo, 'B8-B4' é
    subtração). test_paridade.py confere que as duas dão o mesmo resultado."""
    if not text:
        return False
    t = str(text).strip()
    if not t:
        return False
    while (t.startswith('(') and t.endswith(')')) or (t.startswith('[') and t.endswith(']')):
        t = t[1:-1].strip()
    if any(op in t for op in ['+', '*', '/', '^', '%']):
        return True
    if re.search(r'\b(sqrt|exp|log|log10|sin|cos|tan|min|max|abs)\s*\(', t, re.IGNORECASE):
        return True
    if '-' in t:
        parts = [p.strip() for p in re.split(r'[,;\s]+', t) if p.strip()]
        for p in parts:
            if '-' in p:
                sub = p.split('-')
                band = r'^(SR_|ST_)?B\d+[A-Za-z]?$'
                if len(sub) == 2 and re.match(band, sub[0], re.I) and re.match(band, sub[1], re.I):
                    m1 = re.search(r'\d+', sub[0])
                    m2 = re.search(r'\d+', sub[1])
                    if m1 and m2 and int(m1.group()) < int(m2.group()):
                        continue
                    return True
                return True
    return False


def gee_size_check(sensor, comp, bbox, scale=None, custom_bands=None, n_images=1):
    """Mensagem de erro se o recorte do GEE passar de ~3,5 GB (mesma regra do ArcMagery); None se ok."""
    if not bbox:
        return None
    res = float(scale) if scale else cat.GEE_NATIVE_RES.get(sensor, 30.0)
    info = gee_composition(sensor, comp)
    custom = (custom_bands or u'').strip()
    if (custom and is_math_expr(custom)) or (not custom and (not info or info[3] in ('index', 'math'))):
        n_b, bpp = 1, 4
    else:
        n_b = len([b for b in custom.split(',') if b.strip()]) if custom else max(1, len(info[2]))
        bpp = 2 * n_b
    minx, miny, maxx, maxy = bbox
    lat = math.radians((miny + maxy) / 2.0)
    area = max(abs(maxx - minx) * 111320.0 * math.cos(lat) * abs(maxy - miny) * 110540.0, 1000.0)
    if n_images == 1:
        area = min(area, 1.5e10 if sensor == 'S2' else 3.5e10)
    est = area / (res * res) * bpp
    if est / float(32 * 1024 * 1024) > 120:
        return (u"A área (%.0f km²) exige mais de 120 partes (> 3,5 GB) na resolução de %.0f m com %d banda(s).\n\n"
                u"Aproxime o mapa (escala até 1:500.000), use uma camada vetorial menor ou aumente o tamanho do pixel."
                % (area / 1e6, res, n_b))
    return None
