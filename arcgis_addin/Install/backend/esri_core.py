# -*- coding: utf-8 -*-
"""
Datas de captura e historico (Wayback) da Esri World Imagery - Python 3, somente stdlib.

Servicos PUBLICOS e documentados da Esri:
  * Configuracao do Wayback (todas as versoes publicadas da World Imagery desde 2014):
      https://s3-us-west-2.amazonaws.com/config.maptiles.arcgis.com/waybackconfig.json
  * Metadados de cada versao (MapServer por versao; camadas por resolucao/zoom):
      SRC_DATE2 (data de captura, epoch ms), SRC_DESC (satelite, ex. GE01/WV03),
      NICE_DESC (fornecedor, ex. Maxar/Vantor/Airbus), SRC_RES (resolucao nativa, m),
      SRC_ACC (acuracia, m).
  * tilemap do Wayback: indica se o tile MUDOU numa versao (sem "select") ou em qual versao
    esta o tile de fato ("select") -> permite listar so as versoes com imagem diferente num local
    (mesmo algoritmo do aplicativo Esri World Imagery Wayback).
"""
import datetime as _dt
import json
import os
import re
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tilemath  # noqa: E402

WAYBACK_CONFIG_URL = "https://s3-us-west-2.amazonaws.com/config.maptiles.arcgis.com/waybackconfig.json"
TILEMAP_URL = "https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tilemap"
USER_AGENT = "ArcMagery/2.3 (+https://github.com/Yiuky/arcgis-google-earth-engine-explorer)"
CACHE_SECONDS = 24 * 3600
ATTRIBUTION = u"Esri, Maxar, Vantor, Airbus e parceiros (World Imagery / Wayback)"


# Codigos de satelite dos metadados da World Imagery (SRC_DESC) -> nome legivel.
# Lista adaptada do C:\DOWNLOADER_EARTH (SENSOR_NAMES), revisada e ampliada.
SENSOR_NAMES = {
    'WV01': u'WorldView-1', 'WV02': u'WorldView-2', 'WV03': u'WorldView-3', 'WV04': u'WorldView-4',
    'GE01': u'GeoEye-1', 'QB02': u'QuickBird-2', 'IK01': u'IKONOS',
    'LG01': u'WorldView Legion 1', 'LG02': u'WorldView Legion 2', 'LG03': u'WorldView Legion 3',
    'LG04': u'WorldView Legion 4', 'LG05': u'WorldView Legion 5', 'LG06': u'WorldView Legion 6',
    'PNEO': u'Pléiades Neo', 'PHR': u'Pléiades', 'PHR1A': u'Pléiades 1A', 'PHR1B': u'Pléiades 1B',
    'SPOT': u'SPOT', 'SPOT6': u'SPOT-6', 'SPOT7': u'SPOT-7',
}


def sensor_name(code):
    """'WV03' -> 'WorldView-3 (WV03)'; codigos desconhecidos voltam como vieram."""
    if not code:
        return u''
    name = SENSOR_NAMES.get(str(code).strip().upper())
    return u"%s (%s)" % (name, code) if name else code


class EsriError(RuntimeError):
    pass


def _log(msg):
    sys.stderr.write("[ArcGEE] " + msg + "\n")
    sys.stderr.flush()


def _get_json(url, params=None, timeout=60, retries=3, _sleep=time.sleep):
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    ctx = ssl.create_default_context()  # repositorio de certificados do Windows (proxy corporativo)
    last = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                data = json.loads(r.read().decode('utf-8'))
            if isinstance(data, dict) and data.get('error'):
                raise EsriError(u"Serviço Esri respondeu: %s" % data['error'].get('message', data['error']))
            return data
        except EsriError:
            raise
        except ssl.SSLError as e:
            raise EsriError(u"Erro SSL ao acessar a Esri: %s" % e)
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500 and e.code not in (408, 429):
                # erro permanente (404, 403...): repetir nao resolve
                raise EsriError(u"Serviço Esri respondeu HTTP %d em %s" % (e.code, url.split('?')[0]))
            last = e
        except Exception as e:
            last = e
        if attempt < retries:   # esperar apenas se ainda houver outra tentativa
            _sleep(1.0 * attempt)
    raise EsriError(u"Falha ao acessar %s: %s" % (url.split('?')[0], last))


# ------------------------------------------------------------------------------ versoes
def load_releases(cache_path=None, force=False):
    """Versoes do Wayback, da mais recente para a mais antiga:
    [{'num', 'date' (AAAA-MM-DD da publicacao), 'title', 'tile_url' ({z}/{y}/{x}), 'metadata_url'}]"""
    cache_path = cache_path or os.path.join(tempfile.gettempdir(), 'arcmagery_wayback_config.json')
    raw = None
    if not force and os.path.exists(cache_path) and time.time() - os.path.getmtime(cache_path) < CACHE_SECONDS:
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                raw = json.load(f)
        except Exception:
            raw = None
    if raw is None:
        raw = _get_json(WAYBACK_CONFIG_URL)
        try:
            with open(cache_path + '.tmp', 'w', encoding='utf-8') as f:
                json.dump(raw, f)
            os.replace(cache_path + '.tmp', cache_path)
        except OSError:
            pass
    return parse_releases(raw)


def parse_releases(raw):
    out = []
    for num, v in raw.items():
        m = re.search(r'(\d{4}-\d{2}-\d{2})', v.get('itemTitle', ''))
        if not m or not v.get('itemURL'):
            continue
        out.append({
            'num': int(num),
            'date': m.group(1),
            'title': v.get('itemTitle'),
            'tile_url': v['itemURL'].replace('{level}', '{z}').replace('{row}', '{y}').replace('{col}', '{x}'),
            'metadata_url': v.get('metadataLayerUrl'),
        })
    out.sort(key=lambda r: (r['date'], r['num']), reverse=True)
    return out


def release_by_num(num, releases=None):
    releases = releases or load_releases()
    for r in releases:
        if r['num'] == int(num):
            return r
    raise EsriError(u"Versão Wayback %s não encontrada." % num)


def metadata_layer_for_zoom(zoom):
    """Camadas de metadados: 0 = 1,9 cm (zoom 23) ... 13 = 150 m (zoom 10)."""
    return max(0, min(13, 23 - int(zoom)))


def _capture_date(attrs):
    if attrs.get('SRC_DATE2') not in (None, ''):
        return _dt.datetime.fromtimestamp(int(attrs['SRC_DATE2']) / 1000.0, _dt.timezone.utc).strftime('%Y-%m-%d')
    s = str(attrs.get('SRC_DATE') or '')
    if re.match(r'^\d{8}$', s):
        return '%s-%s-%s' % (s[:4], s[4:6], s[6:])
    return None


# ------------------------------------------------------------------------- datas na area
def _polygon_area(rings):
    """Area plana (em graus^2) de um poligono Esri JSON (aneis externos positivos)."""
    total = 0.0
    for ring in rings:
        a = 0.0
        for i in range(len(ring) - 1):
            a += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
        total += a / 2.0
    return abs(total)


def _clip_rings(rings, bbox):
    import stac_core  # recorte Sutherland-Hodgman ja testado
    return [stac_core._clip_ring_to_bbox(r, bbox) for r in rings]


def capture_dates(bbox, zoom, release=None, with_geometry=False, coverage=True):
    """Datas de captura das imagens que compoem a area no zoom, para uma versao (padrao: a atual).
    Retorna lista (maior cobertura primeiro) de dicts: date, sensor, provider, resolution_m,
    accuracy_m, coverage_pct e, se with_geometry, 'rings' (WGS84).
    coverage=False dispensa a geometria (consulta rapida, ex.: data num ponto): os poligonos de
    cena cobrem centenas de km2 e transferi-los domina o tempo da consulta."""
    bbox = tilemath.clamp_bbox(bbox)
    release = release or load_releases()[0]
    meta_url = release['metadata_url']
    if not meta_url:
        raise EsriError(u"A versão %s não publica metadados." % release['date'])
    first_layer = metadata_layer_for_zoom(zoom)
    params = {
        'geometry': '%f,%f,%f,%f' % tuple(bbox), 'geometryType': 'esriGeometryEnvelope', 'inSR': 4326,
        'spatialRel': 'esriSpatialRelIntersects', 'outFields': 'SRC_DATE,SRC_DATE2,SRC_DESC,NICE_DESC,SRC_RES,SRC_ACC,NICE_NAME',
        'returnGeometry': 'true' if (coverage or with_geometry) else 'false',
        'outSR': 4326, 'geometryPrecision': 7, 'f': 'json',
    }
    # Se o zoom pedido nao tem imagem propria (ex.: z18 onde a cena vai ate z17 e e apenas
    # ampliada), a camada de metadados do zoom vem vazia: descer para a camada seguinte (menos
    # detalhada) ate achar a cena. As camadas 12-13 (TerraColor 15 m) nao tem data de captura.
    data = {'features': []}
    for layer in range(first_layer, 12):
        data = _get_json('%s/%d/query' % (meta_url, layer), params)
        if any(_capture_date(f.get('attributes', {})) for f in data.get('features', [])):
            break
    box_area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
    groups = {}
    for ft in data.get('features', []):
        a = ft.get('attributes', {})
        rings = (ft.get('geometry') or {}).get('rings') or []
        clipped = [r for r in _clip_rings(rings, bbox) if len(r) >= 3]
        if coverage or with_geometry:
            cover = _polygon_area([list(r) + [r[0]] for r in clipped]) / box_area * 100.0 if box_area else 0.0
        else:
            cover = 100.0  # sem geometria: a feicao intersecta a area (ponto)
        key = (_capture_date(a), a.get('SRC_DESC'), a.get('NICE_DESC'), a.get('SRC_RES'))
        g = groups.setdefault(key, {'date': key[0], 'sensor': key[1], 'sensor_name': sensor_name(key[1]),
                                    'provider': key[2], 'metadata_layer': layer,
                                    'resolution_m': a.get('SRC_RES'), 'accuracy_m': a.get('SRC_ACC'),
                                    'product': a.get('NICE_NAME'), 'coverage_pct': 0.0, 'rings': []})
        g['coverage_pct'] += cover
        if with_geometry:
            g['rings'].extend([[list(p) for p in r] + [list(r[0])] for r in clipped])
    result = []
    for g in groups.values():
        g['coverage_pct'] = round(min(100.0, g['coverage_pct']), 1)
        if not with_geometry:
            g.pop('rings', None)
        if g['coverage_pct'] > 0.05 or g['date']:
            result.append(g)
    result.sort(key=lambda g: (-g['coverage_pct'], g['date'] or ''))
    return result


def summarize_dates(dates):
    """Texto curto para nome de camada / status: '2024-05-05 (GE01)' ou '2022-05-02 a 2025-09-10'."""
    ds = sorted(d['date'] for d in dates if d.get('date') and d.get('coverage_pct', 0) >= 1.0)
    if not ds:
        return u"data de captura não informada"
    if ds[0] == ds[-1]:
        main = [d for d in dates if d.get('date') == ds[0]][0]
        return u"%s (%s)" % (ds[0], main.get('sensor') or main.get('provider') or u'?')
    return u"%s a %s (%d capturas)" % (ds[0], ds[-1], len(set(ds)))


# ---------------------------------------------------------------- versoes com mudanca local
def local_versions(bbox, zoom, releases=None, max_calls=80):
    """Versoes do Wayback em que a imagem MUDOU no centro da area (algoritmo do app Wayback):
    tilemap(versao) sem 'select' = tile novo nesta versao; com 'select' = o tile vem da versao
    indicada, entao pula-se direto para ela. Retorna lista (recente -> antiga) com a data de
    captura no centro: release_num, release_date, capture_date, sensor, provider, resolution_m."""
    bbox = tilemath.clamp_bbox(bbox)
    releases = releases or load_releases()
    by_num = dict((r['num'], r) for r in releases)
    lon, lat = (bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0
    x, y = tilemath.lonlat_to_tile(lon, lat, int(zoom))
    point_box = [lon - 1e-6, lat - 1e-6, lon + 1e-6, lat + 1e-6]

    def _describe(rel):
        try:
            info = capture_dates(point_box, zoom, rel, coverage=False)
        except EsriError:
            info = []
        top = info[0] if info else {}
        return {'release_num': rel['num'], 'release_date': rel['date'], 'capture_date': top.get('date'),
                'sensor': top.get('sensor'), 'sensor_name': top.get('sensor_name'), 'provider': top.get('provider'),
                'resolution_m': top.get('resolution_m'), 'tile_url': rel['tile_url']}

    # A data de captura de cada versao e consultada assim que a versao e descoberta, em paralelo
    # com a cadeia do tilemap (os servidores de metadados de versoes antigas levam ate ~10 s).
    from concurrent.futures import ThreadPoolExecutor
    found, futures, i, calls = [], [], 0, 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        while i < len(releases) and calls < max_calls:
            rel = releases[i]
            calls += 1
            tm = _get_json('%s/%d/%d/%d/%d' % (TILEMAP_URL, rel['num'], int(zoom), y, x))
            if not tm.get('data') or tm['data'][0] != 1:
                break  # nao ha tile nesta versao nem nas anteriores
            sel = (tm.get('select') or [rel['num']])[0]
            chosen = by_num.get(sel, rel)
            if not found or found[-1]['num'] != chosen['num']:
                found.append(chosen)
                futures.append(pool.submit(_describe, chosen))
            i = next((j for j in range(i + 1, len(releases)) if releases[j]['date'] < chosen['date']), len(releases))
        out = [f.result() for f in futures]
    _log(u"Wayback: %d versões com mudança local (%d consultas)" % (len(found), calls))
    return dedupe_by_capture(out)


def local_versions_cached(bbox, zoom, cache_dir=None, max_age=CACHE_SECONDS, releases=None):
    """local_versions com cache em disco por (zoom, tile central): a consulta leva ~15-20 s."""
    bbox = tilemath.clamp_bbox(bbox)
    x, y = tilemath.lonlat_to_tile((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0, int(zoom))
    cache_dir = cache_dir or tempfile.gettempdir()
    path = os.path.join(cache_dir, 'arcmagery_wayback_z%d_%d_%d.json' % (int(zoom), x, y))
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < max_age:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    versions = local_versions(bbox, zoom, releases)
    try:
        with open(path + '.tmp', 'w', encoding='utf-8') as f:
            json.dump(versions, f)
        os.replace(path + '.tmp', path)
    except OSError:
        pass
    return versions


def dedupe_by_capture(versions):
    """Mantem a versao mais recente de cada captura (a Esri as vezes republica a mesma cena)."""
    seen, out = set(), []
    for v in versions:
        key = (v.get('capture_date'), v.get('sensor'))
        if v.get('capture_date') and key in seen:
            continue
        seen.add(key)
        out.append(v)
    return out


# ----------------------------------------------------------------------- poligonos de datas
def footprints_featureset(dates):
    """FeatureSet Esri JSON (WGS84) com os poligonos de cada data, pronto para
    arcpy.JSONToFeatures_conversion no ArcMap 10.8."""
    fields = [
        {'name': 'DATA_CAPT', 'type': 'esriFieldTypeString', 'alias': u'Data de captura', 'length': 10},
        {'name': 'SATELITE', 'type': 'esriFieldTypeString', 'alias': u'Satélite', 'length': 40},
        {'name': 'FORNECEDOR', 'type': 'esriFieldTypeString', 'alias': u'Fornecedor', 'length': 60},
        {'name': 'RES_M', 'type': 'esriFieldTypeDouble', 'alias': u'Resolução (m)'},
        {'name': 'COBERT_PCT', 'type': 'esriFieldTypeDouble', 'alias': u'Cobertura da área (%)'},
    ]
    feats = []
    for d in dates:
        if not d.get('rings'):
            continue
        br = (d.get('date') or u'')
        if len(br) == 10:
            br = u'%s/%s/%s' % (br[8:10], br[5:7], br[0:4])
        feats.append({'geometry': {'rings': d['rings'], 'spatialReference': {'wkid': 4326}},
                      'attributes': {'DATA_CAPT': br or u'n/d', 'SATELITE': d.get('sensor_name') or d.get('sensor') or u'',
                                     'FORNECEDOR': d.get('provider') or u'', 'RES_M': d.get('resolution_m'),
                                     'COBERT_PCT': d.get('coverage_pct')}})
    return {'displayFieldName': 'DATA_CAPT', 'geometryType': 'esriGeometryPolygon',
            'spatialReference': {'wkid': 4326}, 'fields': fields, 'features': feats}


def write_footprints(dates, out_json):
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump(footprints_featureset(dates), f, ensure_ascii=True)  # JSONToFeatures do ArcMap 10.8
    return out_json
