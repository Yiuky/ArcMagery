# -*- coding: utf-8 -*-
"""
ArcMagery - SPOT 1-5 (CNES SPOT World Heritage, 1986-2015) via API STAC do GEODES (Python 3 + GDAL).

Fluxo: busca STAC publica -> download do .zip L1A com a chave de API do GEODES (header X-API-Key,
MD5 conferido, cache local) -> georreferenciamento pelo modelo de localizacao do proprio produto
(Simplified_Location_Model do METADATA.DIM) -> ALINHAMENTO a Esri World Imagery (correlacao de
fase) -> GeoTIFF em UTM na resolucao nativa.

Fatos verificados em cenas reais (Cuiaba, 2026-09-30):
  * o GEODES devolve 0 itens se `collections` tiver mais de uma colecao: filtrar por query.dataset;
  * `datetime` do item e a data de PROCESSAMENTO; a de aquisicao e `start_datetime`;
  * modelo direto: polinomio de 2o grau com termos [1, linha, coluna, linha*coluna, linha^2, coluna^2]
    (indices DIMAP, origem 1), erro < 5 m contra os vertices do produto;
  * o IMAGERY.TIF grava XS3 (NIR), XS2 (vermelho), XS1 (verde), SWIR - ordem inversa ao XML;
  * sem alinhamento o erro contra a Esri e uma translacao quase uniforme: ~470 m (SPOT 2) e
    ~150 m (SPOT 5).
"""
import hashlib
import json
import math
import os
import shutil
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qgis_env  # noqa: E402,F401  (DLLs do GDAL do QGIS antes do import do osgeo)

try:
    from osgeo import gdal, osr
    gdal.UseExceptions()
    HAS_GDAL = True
except Exception:  # pragma: no cover
    gdal = osr = None
    HAS_GDAL = False

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

GEODES_URL = os.environ.get('ARCMAGERY_GEODES_URL', 'https://geodes-portal.cnes.fr').rstrip('/')
STAC_SEARCH = GEODES_URL + '/api/stac/search'
QUOTA_URL = GEODES_URL + '/processing/download/get'
DATASETS = ('SWH_SPOT123_L1', 'SWH_SPOT4_L1', 'SWH_SPOT5_L1')
USER_AGENT = 'ArcMagery/2.0 (+https://github.com/Yiuky/arcgis-google-earth-engine-explorer)'
ATTRIBUTION = u"SPOT images acquired by CNES's Spot World Heritage Programme (Licence Ouverte Etalab 2.0)"
PAGE = 500

# Modos de aquisicao (sar:instrument_mode) -> descricao; multiespectral x pancromatico
MS_MODES = ('X', 'I', 'J')
PAN_MODES = ('P', 'M', 'A', 'B', 'T', 'S')
MODE_LABELS = {
    ('SPOT5', 'X'): u'HX 3 bandas', ('SPOT5', 'J'): u'HI 4 bandas', ('SPOT5', 'A'): u'PAN HM-A 5 m',
    ('SPOT5', 'B'): u'PAN HM-B 5 m', ('SPOT5', 'T'): u'PAN THR 2,5 m', ('SPOT5', 'S'): u'PAN THR 2,5 m',
    ('SPOT4', 'I'): u'XI 4 bandas', ('SPOT4', 'M'): u'PAN M 10 m',
}
# Composicoes: bandas na ORDEM DO ARQUIVO (1=XS3 NIR, 2=XS2 vermelho, 3=XS1 verde, 4=SWIR)
MODES = {
    'false': u'Falsa cor (NIR, vermelho, verde) - vegetação em vermelho',
    'swir': u'SWIR, NIR, vermelho (SPOT 4 e 5) - realça umidade e solo exposto',
    'multi': u'Multibanda (todas as bandas, exibida em falsa cor)',
    'pan': u'Pancromática (tons de cinza, maior resolução)',
}
MODE_BANDS = {'false': [1, 2, 3], 'swir': [4, 1, 2], 'multi': None, 'pan': [1]}

# Alinhamento
ALIGN_MIN_SIDE_M = 8000.0      # area minima (lado) usada para medir o deslocamento
ALIGN_MAX_SIDE_M = 20000.0
ALIGN_WINDOW = 256             # janela da correlacao de fase (px)
ALIGN_MIN_CONFIDENCE = 4.0     # pico / 30o maior valor da superficie de correlacao
ALIGN_MAX_SHIFT_M = 1500.0     # deslocamentos maiores sao tratados como falha da medicao


class SpotError(RuntimeError):
    pass


def _log(msg):
    sys.stderr.write("[ArcGEE] " + msg + "\n")
    sys.stderr.flush()


def _ctx():
    return ssl.create_default_context()   # repositorio de certificados do Windows (proxy corporativo)


# ------------------------------------------------------------------------------ geometria
def _clip_ring(ring, bbox):
    """Sutherland-Hodgman: recorta o anel [(lon, lat)] pelo retangulo do BBOX."""
    edges = ((0, bbox[0], 1), (0, bbox[2], -1), (1, bbox[1], 1), (1, bbox[3], -1))
    out = list(ring)
    for axis, value, sign in edges:
        pts, out = out, []
        for i, cur in enumerate(pts):
            prev = pts[i - 1]
            cur_in, prev_in = sign * (cur[axis] - value) >= 0, sign * (prev[axis] - value) >= 0
            if cur_in != prev_in:
                t = (value - prev[axis]) / (cur[axis] - prev[axis])
                out.append((prev[0] + t * (cur[0] - prev[0]), prev[1] + t * (cur[1] - prev[1])))
            if cur_in:
                out.append(cur)
        if not out:
            return []
    return out


def _area(ring):
    return abs(sum(ring[i - 1][0] * p[1] - p[0] * ring[i - 1][1] for i, p in enumerate(ring))) / 2.0


def coverage_pct(footprint, bbox):
    """% do BBOX coberto pelo footprint (anel exterior GeoJSON)."""
    ring = [tuple(p[:2]) for p in footprint]
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring = ring[:-1]
    box = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
    clipped = _clip_ring(ring, bbox)
    return round(min(100.0, 100.0 * _area(clipped) / box), 1) if len(clipped) >= 3 and box else 0.0


def utm_epsg(lon, lat):
    """SIRGAS 2000 / UTM no Brasil (zonas 17 a 25); WGS 84 / UTM fora dele."""
    zone = int(math.floor((lon + 180.0) / 6.0)) + 1
    zone = max(1, min(60, zone))
    if -75.0 <= lon <= -28.0 and -35.0 <= lat <= 7.0 and 17 <= zone <= 25:
        return 31960 + zone if lat < 0 else 31954 + zone
    return (32700 if lat < 0 else 32600) + zone


# ---------------------------------------------------------------------------------- HTTP
def _http_json(url, body=None, headers=None, timeout=60, retries=3):
    data = json.dumps(body).encode('utf-8') if body is not None else None
    hdrs = {'User-Agent': USER_AGENT, 'Accept': 'application/json, application/geo+json'}
    if data is not None:
        hdrs['Content-Type'] = 'application/json'
    hdrs.update(headers or {})
    last = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=hdrs), timeout=timeout,
                                        context=_ctx()) as r:
                return json.loads(r.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            detail = e.read().decode('utf-8', 'replace')[:300]
            if e.code in (401, 403):
                raise SpotError(u"GEODES recusou a chave de API (HTTP %d). Confira a chave em "
                                u"Configurações > Chave do GEODES." % e.code)
            if e.code < 500 and e.code != 429:
                raise SpotError(u"GEODES respondeu HTTP %d: %s" % (e.code, detail))
            last = u"HTTP %d: %s" % (e.code, detail)
        except ssl.SSLError as e:
            raise SpotError(u"Erro SSL ao acessar o GEODES: %s" % e)
        except Exception as e:
            last = e
        time.sleep(1.5 * attempt)
    raise SpotError(u"Falha ao acessar o GEODES (%s): %s" % (url.split('?')[0], last))


def check_key(api_key):
    """Valida a chave e devolve a quota de downloads: {'max_quota', 'remaining_quota'}."""
    if not api_key:
        raise SpotError(u"Nenhuma chave de API do GEODES configurada.")
    d = _http_json(QUOTA_URL, headers={'X-API-Key': api_key}, timeout=30, retries=2)
    return {'max_quota': d.get('maxQuota'), 'remaining_quota': d.get('remainingQuota')}


# ---------------------------------------------------------------------------------- busca
def _scene(feature, bbox=None):
    p = feature.get('properties', {})
    assets = feature.get('assets', {}) or {}
    data = next((a for a in assets.values() if 'data' in (a.get('roles') or [])), None)
    quick = next((a for a in assets.values() if 'overview' in (a.get('roles') or [])), None)
    platform, mode = p.get('platform', ''), p.get('sar:instrument_mode', '')
    ncols = int(p.get('nb_cols') or 0)
    res = 1000.0 * math.sqrt(p['area']) / ncols if p.get('area') and ncols else None
    size = None
    if data:
        size = data.get('file:size')
        for line in (data.get('description') or '').splitlines():
            if line.startswith('File size:') and size is None:
                try:
                    size = int(line.split(':')[1].split()[0])
                except ValueError:
                    pass
    ring = (feature.get('geometry') or {}).get('coordinates', [[]])[0]
    if mode in PAN_MODES:
        label = MODE_LABELS.get((platform, mode), u'PAN 10 m')
    else:
        label = MODE_LABELS.get((platform, mode), u'XS 3 bandas')
    return {
        'id': p.get('identifier') or feature.get('id'),
        'stac_id': feature.get('id'),
        'date': (p.get('start_datetime') or '')[:10],
        'datetime': p.get('start_datetime'),
        'platform': platform,
        'instrument': p.get('instrument'),
        'mode': mode,
        'mode_label': label,
        'is_pan': mode in PAN_MODES,
        'bands': p.get('nb_bands'),
        'res_m': round(res, 1) if res else None,
        'cloud_cover': p.get('eo:cloud_cover'),
        'incidence_deg': p.get('view:incidence_angle'),
        'quality': p.get('image_quality'),
        'coverage_pct': coverage_pct(ring, bbox) if bbox and ring else None,
        'footprint': ring,
        'collection': p.get('dataset') or feature.get('collection'),
        'zip_url': data.get('href') if data else None,
        'zip_name': data.get('title') if data else None,
        'zip_size': size,
        'zip_md5': data['href'].rstrip('/').rsplit('/', 1)[-1] if data else None,
        'thumbnail': quick.get('href') if quick else None,
    }


def build_query(bbox=None, start_date=None, end_date=None, max_cloud=None, satellites=None, kind=None,
                identifier=None):
    query = {'dataset': {'in': list(DATASETS)}}
    if identifier:
        query['identifier'] = {'eq': identifier}
    if start_date or end_date:
        rng = {}
        if start_date:
            rng['gte'] = '%sT00:00:00Z' % start_date[:10]
        if end_date:
            rng['lte'] = '%sT23:59:59Z' % end_date[:10]
        query['start_datetime'] = rng
    if max_cloud not in (None, ''):
        query['eo:cloud_cover'] = {'lte': float(max_cloud)}
    if satellites:
        query['platform'] = {'in': ['SPOT%s' % s for s in satellites]}
    if kind == 'ms':
        query['sar:instrument_mode'] = {'in': list(MS_MODES)}
    elif kind == 'pan':
        query['sar:instrument_mode'] = {'in': list(PAN_MODES)}
    body = {'limit': PAGE, 'query': query, 'sortby': [{'field': 'start_datetime', 'direction': 'desc'}]}
    if bbox:
        body['bbox'] = [float(v) for v in bbox]
    return body


def search(bbox=None, start_date=None, end_date=None, max_cloud=None, satellites=None, kind=None,
           identifier=None, max_items=500, min_coverage=0.0, http=None):
    """Cenas SPOT que intersectam o BBOX, da mais nova para a mais antiga."""
    http = http or _http_json
    body = build_query(bbox, start_date, end_date, max_cloud, satellites, kind, identifier)
    feats, page = [], 1
    while len(feats) < max_items:
        d = http(STAC_SEARCH, dict(body, page=page))
        got = d.get('features') or []
        feats += got
        matched = (d.get('context') or {}).get('matched', d.get('numberMatched'))
        if not got or len(got) < PAGE or (matched is not None and len(feats) >= matched):
            break
        page += 1
    scenes = [_scene(f, bbox) for f in feats[:max_items]]
    if bbox and min_coverage:
        scenes = [s for s in scenes if (s['coverage_pct'] or 0) >= min_coverage]
    return scenes


def get_scene(identifier, bbox=None, http=None):
    found = search(bbox=None, identifier=identifier, max_items=5, http=http)
    if not found:
        raise SpotError(u"Cena SPOT não encontrada no GEODES: %s" % identifier)
    s = found[0]
    if bbox and s['footprint']:
        s['coverage_pct'] = coverage_pct(s['footprint'], bbox)
    return s


def thumbnail(href, out_png=None):
    """Quicklook publico (JPEG) -> PNG + GIF 420 px (o Tk 8.5 do ArcGIS nao le PNG)."""
    if not href:
        raise SpotError(u"Cena sem miniatura.")
    out_png = out_png or os.path.join(tempfile.gettempdir(), 'arcmagery_spot_thumb.png')
    req = urllib.request.Request(href, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(req, timeout=60, context=_ctx()) as r:
        raw = r.read()
    from PIL import Image
    import io
    with Image.open(io.BytesIO(raw)) as im:
        im = im.convert('RGB')
        im.thumbnail((420, 420))
        im.save(out_png, 'PNG')
        gif = os.path.splitext(out_png)[0] + '.gif'
        im.save(gif, 'GIF')
    return {'file': out_png, 'gif': gif, 'url': href}


# ------------------------------------------------------------------------------ download
def default_cache_dir():
    base = os.environ.get('LOCALAPPDATA') or tempfile.gettempdir()
    return os.path.join(base, 'ArcMagery', 'spot_cache')


def md5_ok(path, md5):
    if not zipfile.is_zipfile(path):
        return False
    if not md5 or len(md5) != 32:
        return True
    h = hashlib.md5()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest().lower() == md5.lower()


def download_zip(scene, api_key, cache_dir=None, retries=3, opener=None):
    """Baixa o .zip L1A para o cache (reaproveita se o MD5 conferir). Retorna o caminho."""
    if not scene.get('zip_url'):
        raise SpotError(u"A cena %s não tem arquivo para download." % scene.get('id'))
    cache_dir = cache_dir or default_cache_dir()
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, scene.get('zip_name') or '%s.zip' % scene['id'])
    if os.path.exists(path) and md5_ok(path, scene.get('zip_md5')):
        _log(u"SPOT: cena já baixada (cache)")
        return path
    if not api_key:
        raise SpotError(u"O download SPOT exige a chave de API do GEODES (Configurações > Chave do GEODES).")
    opener = opener or (lambda req: urllib.request.urlopen(req, timeout=120, context=_ctx()))
    tmp = path + '.part'
    last = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(scene['zip_url'], headers={'User-Agent': USER_AGENT, 'X-API-Key': api_key})
            with opener(req) as r:
                ctype = r.headers.get('Content-Type', '')
                if 'zip' not in ctype:
                    raise SpotError(u"GEODES não devolveu o arquivo (%s): %s"
                                    % (ctype, r.read(300).decode('utf-8', 'replace')))
                total = int(r.headers.get('Content-Length') or scene.get('zip_size') or 0)
                done, last_pct = 0, -1
                with open(tmp, 'wb') as fh:
                    while True:
                        chunk = r.read(1 << 20)
                        if not chunk:
                            break
                        fh.write(chunk)
                        done += len(chunk)
                        pct = int(100 * done / total) if total else 0
                        if pct != last_pct:
                            last_pct = pct
                            _log(u"SPOT: baixando %.0f/%.0f MB" % (done / 1e6, total / 1e6))
                            _log(u"PROGRESS %d/100" % min(pct, 99))
            if not md5_ok(tmp, scene.get('zip_md5')):
                raise SpotError(u"MD5 do arquivo baixado não confere com o catálogo")
            os.replace(tmp, path)
            return path
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', 'replace')[:300]
            if e.code in (401, 403) or 'quota' in body.lower():
                _remove(tmp)
                raise SpotError(u"GEODES recusou o download (HTTP %d): %s" % (e.code, body))
            last = u"HTTP %d: %s" % (e.code, body)
        except SpotError as e:
            if 'quota' in str(e).lower():
                _remove(tmp)
                raise
            last = e
        except Exception as e:
            last = e
        _log(u"SPOT: tentativa %d/%d falhou: %s" % (attempt, retries, last))
        time.sleep(2 * attempt)
    _remove(tmp)
    raise SpotError(u"Falha ao baixar a cena %s: %s" % (scene.get('id'), last))


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


# ------------------------------------------------------------------- produto L1A (DIMAP)
def read_dimap(dim_path):
    root = ET.parse(dim_path).getroot()

    def floats(xpath):
        return [float(e.text) for e in root.findall(xpath)]

    def text(xpath, default=None):
        e = root.find(xpath)
        return e.text.strip() if e is not None and e.text else default

    lc = floats('.//Simplified_Location_Model/Direct_Location_Model/lc_List/lc')
    pc = floats('.//Simplified_Location_Model/Direct_Location_Model/pc_List/pc')
    vertices = [(float(v.findtext('FRAME_COL')), float(v.findtext('FRAME_ROW')),
                 float(v.findtext('FRAME_LON')), float(v.findtext('FRAME_LAT')))
                for v in root.findall('.//Dataset_Frame/Vertex') + root.findall('.//Dataset_Frame/Scene_Center')]
    return {
        'ncols': int(text('.//Raster_Dimensions/NCOLS')),
        'nrows': int(text('.//Raster_Dimensions/NROWS')),
        'nbands': int(text('.//Raster_Dimensions/NBANDS', '1')),
        'bands': [e.text for e in root.findall('.//Spectral_Band_Info/BAND_DESCRIPTION')],
        'pixel_origin': int(text('.//Raster_CS/PIXEL_ORIGIN', '1')),
        'model': (lc, pc) if len(lc) == 6 and len(pc) == 6 else None,
        'vertices': vertices,
        'date': text('.//Scene_Source/IMAGING_DATE'),
        'time': text('.//Scene_Source/IMAGING_TIME'),
        'mission': u'%s%s' % (text('.//Scene_Source/MISSION', 'SPOT'), text('.//Scene_Source/MISSION_INDEX', '')),
        'instrument': u'%s%s' % (text('.//Scene_Source/INSTRUMENT', ''), text('.//Scene_Source/INSTRUMENT_INDEX', '')),
        'incidence_deg': float(text('.//Scene_Source/INCIDENCE_ANGLE', '0')),
        'level': text('.//Data_Processing/PROCESSING_LEVEL') or text('.//Scene_Source/SCENE_PROCESSING_LEVEL'),
    }


def file_band_names(meta):
    """Nomes na ordem do IMAGERY.TIF: XS3 (NIR), XS2, XS1, SWIR (o XML lista XS1, XS2, XS3).
    Conferido pelo PREVIEW.JPG do produto (R=1, G=2, B=3, correlacao > 0,99) e pela agua."""
    names = list(meta['bands'])
    if len(names) >= 3 and names[:3] == ['XS1', 'XS2', 'XS3']:
        names = ['XS3', 'XS2', 'XS1'] + names[3:]
    return names + ['B%d' % i for i in range(len(names) + 1, meta['nbands'] + 1)]


def locate(meta, col, row, shift=(0.0, 0.0)):
    """Pixel DIMAP (coluna, linha) -> (lon, lat); shift = (dlon, dlat) do alinhamento."""
    lc, pc = meta['model']
    t = (1.0, row, col, row * col, row * row, col * col)
    return (sum(a * b for a, b in zip(lc, t)) + shift[0], sum(a * b for a, b in zip(pc, t)) + shift[1])


def model_error_m(meta):
    worst = 0.0
    for col, row, lon, lat in meta['vertices']:
        x, y = locate(meta, col, row)
        worst = max(worst, math.hypot((x - lon) * 111320 * math.cos(math.radians(lat)), (y - lat) * 110574))
    return worst


def gcps(meta, steps=10, shift=(0.0, 0.0)):
    """(px, linha, lon, lat) em coordenadas de pixel do GDAL (canto = 0; centro do 1o pixel = 0,5)."""
    out = []
    for i in range(steps + 1):
        for j in range(steps + 1):
            px, ln = meta['ncols'] * j / float(steps), meta['nrows'] * i / float(steps)
            lon, lat = locate(meta, px - 0.5 + meta['pixel_origin'], ln - 0.5 + meta['pixel_origin'], shift)
            out.append((px, ln, lon, lat))
    return out


def pixel_size_m(meta):
    c, r = meta['ncols'] / 2.0, meta['nrows'] / 2.0
    lon0, lat0 = locate(meta, c, r)
    k = math.cos(math.radians(lat0))
    dist = []
    for dc, dr in ((1, 0), (0, 1)):
        lon, lat = locate(meta, c + dc, r + dr)
        dist.append(math.hypot((lon - lon0) * 111320 * k, (lat - lat0) * 110574))
    return sum(dist) / 2.0


def extract(zip_path, work):
    os.makedirs(work, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        dim = next((n for n in names if n.upper().endswith('METADATA.DIM')), None)
        if not dim:
            raise SpotError(u"METADATA.DIM não encontrado no pacote SPOT.")
        folder = dim[:-len('METADATA.DIM')]
        tif = next((n for n in names if n.upper() == (folder + 'IMAGERY.TIF').upper()), None)
        if not tif:
            raise SpotError(u"IMAGERY.TIF não encontrado no pacote SPOT.")
        for n in (dim, tif):
            target = os.path.join(work, os.path.basename(n).upper())
            if not os.path.exists(target) or os.path.getsize(target) != z.getinfo(n).file_size:
                with z.open(n) as src, open(target, 'wb') as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
    return os.path.join(work, 'METADATA.DIM'), os.path.join(work, 'IMAGERY.TIF')


def _gcp_vrt(tif, meta, bands, shift, path):
    gcp_list = [gdal.GCP(lon, lat, 0.0, px, ln) for px, ln, lon, lat in gcps(meta, shift=shift)]
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    return gdal.Translate(path, tif, format='VRT', bandList=bands, GCPs=gcp_list, outputSRS=srs.ExportToWkt())


def _warp(src, dst, epsg, res, bounds_wgs84, resampling='bilinear', out_format='GTiff', out_type=None,
          creation=None, callback=None):
    kw = dict(format=out_format, dstSRS='EPSG:%d' % epsg, xRes=res, yRes=res, polynomialOrder=2,
              resampleAlg=resampling, srcNodata=0, dstNodata=0, multithread=True, callback=callback)
    if bounds_wgs84:
        kw.update(outputBounds=bounds_wgs84, outputBoundsSRS='EPSG:4326')
    if out_type is not None:
        kw['outputType'] = out_type
    if creation:
        kw['creationOptions'] = creation
    return gdal.Warp(dst, src, **kw)


# --------------------------------------------------------------------------- alinhamento
def _gradient(a):
    gy, gx = np.gradient(a)
    g = np.hypot(gx, gy)
    return (g - g.mean()) / (g.std() + 1e-9)


def phase_correlation(a, b):
    """Deslocamento (dx, dy) em pixels tal que a(x) ~ b(x - d), com precisao subpixel, e a
    confianca (pico / 30o maior valor da superficie)."""
    a, b = _gradient(a.astype('float64')), _gradient(b.astype('float64'))
    win = np.outer(np.hanning(a.shape[0]), np.hanning(a.shape[1]))
    f = np.fft.fft2(a * win) * np.conj(np.fft.fft2(b * win))
    f /= np.abs(f) + 1e-12
    c = np.real(np.fft.ifft2(f))
    iy, ix = np.unravel_index(int(np.argmax(c)), c.shape)
    h, w = c.shape

    def sub(cm, c0, cp):
        den = cm - 2 * c0 + cp
        return 0.0 if abs(den) < 1e-12 else 0.5 * (cm - cp) / den

    dy = iy + sub(c[(iy - 1) % h, ix], c[iy, ix], c[(iy + 1) % h, ix])
    dx = ix + sub(c[iy, (ix - 1) % w], c[iy, ix], c[iy, (ix + 1) % w])
    if dy > h / 2:
        dy -= h
    if dx > w / 2:
        dx -= w
    flat = np.sort(c.ravel())
    conf = float(c[iy, ix] / max(flat[-30], 1e-12))
    return float(dx), float(dy), conf


def estimate_shift(spot, ref, valid, px_m, window=ALIGN_WINDOW):
    """Mede o deslocamento em janelas; devolve (dE_m, dN_m, info) da correcao a APLICAR na imagem
    SPOT (ou None se a medicao nao for confiavel)."""
    h, w = spot.shape
    win = min(window, h, w)
    if win < 64:
        return None, {'reason': u"área pequena demais para medir o deslocamento"}
    fill = float(np.median(spot[valid])) if valid.any() else 0.0
    spot = np.where(valid, spot, fill)
    ny, nx = max(1, h // win), max(1, w // win)
    oy, ox = (h - ny * win) // 2, (w - nx * win) // 2
    meas = []
    for i in range(ny):
        for j in range(nx):
            sl = (slice(oy + i * win, oy + (i + 1) * win), slice(ox + j * win, ox + (j + 1) * win))
            if valid[sl].mean() < 0.6 or ref[sl].std() < 1.0:
                continue
            dx, dy, conf = phase_correlation(spot[sl], ref[sl])
            if conf >= ALIGN_MIN_CONFIDENCE:
                meas.append((dx, dy, conf))
    if not meas:
        return None, {'reason': u"sem textura suficiente em comum com a referência (nuvens, água ou mudança)",
                      'windows': 0}
    arr = np.array([(m[0], m[1]) for m in meas])
    med = np.median(arr, axis=0)
    tol = max(2.0, 30.0 / px_m)
    agree = [m for m in meas if math.hypot(m[0] - med[0], m[1] - med[1]) <= tol]
    if len(meas) >= 2 and len(agree) < 2:
        return None, {'reason': u"medições discordantes entre janelas", 'windows': len(meas)}
    if len(meas) == 1 and meas[0][2] < 1.5 * ALIGN_MIN_CONFIDENCE:
        return None, {'reason': u"uma única janela com confiança baixa", 'windows': 1}
    dx, dy = float(np.mean([m[0] for m in agree])), float(np.mean([m[1] for m in agree]))
    spread = float(np.max([math.hypot(m[0] - dx, m[1] - dy) for m in agree])) * px_m
    # a(x) ~ b(x - d): o conteudo SPOT esta deslocado de +d; corrigir com -d (y da imagem cresce p/ sul)
    d_e, d_n = -dx * px_m, dy * px_m
    if math.hypot(d_e, d_n) > ALIGN_MAX_SHIFT_M:
        return None, {'reason': u"deslocamento medido (%.0f m) acima do plausível" % math.hypot(d_e, d_n),
                      'windows': len(meas)}
    return (d_e, d_n), {'windows': len(meas), 'agreeing': len(agree), 'spread_m': round(spread, 1),
                        'confidence': round(float(np.median([m[2] for m in agree])), 1)}


def _align_bbox(bbox, footprint, px_m=10.0):
    """BBOX usado para medir o deslocamento: o do usuario ampliado ate caber ~3x3 janelas (minimo de
    8 km), limitado a ~5x5 janelas (minimo de 20 km) e a extensao da cena."""
    grid = max(px_m, 5.0) * ALIGN_WINDOW
    side_min, side_max = max(ALIGN_MIN_SIDE_M, 3 * grid), max(ALIGN_MAX_SIDE_M, 5 * grid)
    lon_c, lat_c = (bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0
    k = 111320.0 * math.cos(math.radians(lat_c))
    w_m, h_m = (bbox[2] - bbox[0]) * k, (bbox[3] - bbox[1]) * 110574.0
    w_m, h_m = min(max(w_m, side_min), side_max), min(max(h_m, side_min), side_max)
    out = [lon_c - w_m / 2 / k, lat_c - h_m / 2 / 110574.0, lon_c + w_m / 2 / k, lat_c + h_m / 2 / 110574.0]
    if footprint:
        xs, ys = [p[0] for p in footprint], [p[1] for p in footprint]
        out = [max(out[0], min(xs)), max(out[1], min(ys)), min(out[2], max(xs)), min(out[3], max(ys))]
    return out


def _reference_zoom(pixel_m, lat):
    z = math.log(156543.03392 * math.cos(math.radians(lat)) / max(pixel_m / 1.5, 1.0), 2)
    return int(max(12, min(16, round(z))))


def _read_band(path, band=1):
    ds = gdal.Open(path)
    arr = ds.GetRasterBand(band).ReadAsArray().astype('float64')
    ds = None
    return arr


def measure_alignment(tif, meta, band, epsg, px_m, abox, work, shift=(0.0, 0.0), reference=None):
    """Deslocamento entre a banda SPOT (modelo + shift) e a referencia Esri na area abox."""
    ref_tif = reference or fetch_reference(abox, px_m, work)
    grid_res = max(px_m, 5.0)
    vrt = _gcp_vrt(tif, meta, [band], shift, os.path.join(work, 'align_src.vrt'))
    spot_path = os.path.join(work, 'align_spot.tif')
    _warp(vrt, spot_path, epsg, grid_res, abox, resampling='average', out_type=gdal.GDT_Float32)
    vrt = None
    ref_path = os.path.join(work, 'align_ref.tif')
    ds = gdal.Warp(ref_path, ref_tif, dstSRS='EPSG:%d' % epsg, xRes=grid_res, yRes=grid_res,
                   outputBounds=abox, outputBoundsSRS='EPSG:4326', resampleAlg='average',
                   outputType=gdal.GDT_Float32)
    ds = None
    spot = _read_band(spot_path)
    ref = _read_band(ref_path, 1)   # vermelho da Esri: correlaciona melhor com XS2/PAN
    h, w = min(spot.shape[0], ref.shape[0]), min(spot.shape[1], ref.shape[1])
    spot, ref = spot[:h, :w], ref[:h, :w]
    valid = (spot > 0) & (spot < 254) & (ref > 0)
    if valid.any():   # nuvens: muito mais claras que o terreno (limiar robusto: mediana + 4 MAD)
        vals = spot[valid]
        med = float(np.median(vals))
        mad = float(np.median(np.abs(vals - med))) or 1.0
        valid &= spot < med + 4 * 1.4826 * mad
    corr, info = estimate_shift(spot, ref, valid, grid_res)
    info['grid_res_m'] = grid_res
    return corr, info, ref_tif


def fetch_reference(abox, px_m, work):
    import xyz_core
    zoom = _reference_zoom(px_m, (abox[1] + abox[3]) / 2.0)
    _log(u"SPOT: baixando referência Esri (zoom %d) para o alinhamento..." % zoom)
    res = xyz_core.download_mosaic(abox, zoom, provider='esri', out_tif=os.path.join(work, 'align_esri.tif'),
                                   max_tiles=1500, overviews=False, compression='DEFLATE')
    return res['file']


# ------------------------------------------------------------------------------ produto
def georeference(zip_path, out_tif, bbox=None, mode='false', align=True, work_dir=None, footprint=None,
                 resampling='bilinear', epsg=None, reference=None):
    """Georreferencia (e alinha) a cena L1A e grava o GeoTIFF recortado ao BBOX em UTM."""
    if not HAS_GDAL or np is None:
        raise SpotError(u"O SPOT requer GDAL e numpy (venv do ArcMagery ou Python do QGIS).")
    work = work_dir or tempfile.mkdtemp(prefix='arcmagery_spot_')
    try:
        _log(u"SPOT: extraindo o pacote...")
        dim, tif = extract(zip_path, work)
        meta = read_dimap(dim)
        if not meta['model']:
            raise SpotError(u"METADATA.DIM sem Simplified_Location_Model: produto não suportado.")
        err = model_error_m(meta)
        if err > 30:
            raise SpotError(u"Modelo de localização inconsistente com os vértices do produto (%.0f m)." % err)
        names = file_band_names(meta)
        bands = MODE_BANDS.get(mode, MODE_BANDS['false'])
        if meta['nbands'] == 1:
            bands, mode = [1], 'pan'
        elif bands is None:
            bands = list(range(1, meta['nbands'] + 1))
        elif max(bands) > meta['nbands']:
            raise SpotError(u"A composição '%s' exige %d bandas; esta cena tem %d (%s)."
                            % (mode, max(bands), meta['nbands'], ', '.join(names)))
        px = pixel_size_m(meta)
        clon, clat = locate(meta, meta['ncols'] / 2.0, meta['nrows'] / 2.0)
        if bbox:
            clon, clat = (bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0
        epsg = epsg or utm_epsg(clon, clat)

        shift, align_info = (0.0, 0.0), {'applied': False}
        if align:
            abox = _align_bbox(bbox or _frame_bbox(meta), footprint or [(v[2], v[3]) for v in meta['vertices'][:4]], px)
            band = 2 if meta['nbands'] >= 3 else 1        # XS2 (vermelho) ou PAN
            try:
                corr, info, ref = measure_alignment(tif, meta, band, epsg, px, abox, work, reference=reference)
                align_info.update(info)
                if corr:
                    d_e, d_n = corr
                    shift = (d_e / (111320.0 * math.cos(math.radians(clat))), d_n / 110574.0)
                    residual, rinfo, _ = measure_alignment(tif, meta, band, epsg, px, abox, work, shift, reference=ref)
                    align_info.update(applied=True, shift_east_m=round(d_e, 1), shift_north_m=round(d_n, 1),
                                      shift_m=round(math.hypot(d_e, d_n), 1),
                                      residual_m=round(math.hypot(*residual), 1) if residual else None)
                    _log(u"SPOT: alinhado à Esri: %.0f m (L %.0f, N %.0f), resíduo %s m"
                         % (math.hypot(d_e, d_n), d_e, d_n,
                            u"%.0f" % math.hypot(*residual) if residual else u"n/d"))
                else:
                    _log(u"SPOT: alinhamento não aplicado: %s" % info.get('reason'))
            except Exception as e:
                align_info['reason'] = u"falha ao medir o deslocamento: %s" % e
                _log(u"SPOT: alinhamento não aplicado: %s" % e)

        _log(u"SPOT: georreferenciando %d banda(s) em EPSG:%d (pixel %.1f m)..." % (len(bands), epsg, px))
        vrt = _gcp_vrt(tif, meta, bands, shift, os.path.join(work, 'scene.vrt'))
        out_tif = os.path.abspath(out_tif)
        os.makedirs(os.path.dirname(out_tif), exist_ok=True)
        tmp = out_tif + '.part.tif'

        def cb(pct, _m, _d):
            _log(u"PROGRESS %d/100" % int(pct * 100))
            return 1

        _warp(vrt, tmp, epsg, round(px, 2), list(bbox) if bbox else None, resampling=resampling,
              creation=['TILED=YES', 'COMPRESS=DEFLATE', 'PREDICTOR=2', 'BIGTIFF=IF_SAFER'], callback=cb)
        vrt = None
        ds = gdal.Open(tmp, gdal.GA_Update)
        for i, b in enumerate(bands):
            ds.GetRasterBand(i + 1).SetDescription(names[b - 1])
        ds.SetMetadata({'ACQUISITION_DATE': meta['date'] or '', 'SPOT_SCENE': os.path.basename(zip_path),
                        'SPOT_PLATFORM': meta['mission'], 'SPOT_LEVEL': meta['level'] or '',
                        'SPOT_ALIGNED_TO': 'Esri World Imagery' if align_info.get('applied') else 'none'})
        band1 = ds.GetRasterBand(1)
        arr = band1.ReadAsArray(buf_xsize=min(1024, ds.RasterXSize), buf_ysize=min(1024, ds.RasterYSize))
        valid_pct = round(100.0 * float((arr != 0).mean()), 1)
        w, h = ds.RasterXSize, ds.RasterYSize
        ds = None
        if valid_pct <= 0:
            _remove(tmp)
            raise SpotError(u"A área cai fora da cena SPOT (recorte 100% NoData).")
        for ext in ('', '.ovr', '.aux.xml'):
            _remove(out_tif + ext)
        os.replace(tmp, out_tif)
        rgb = [0, 1, 2] if len(bands) >= 3 else None
        return {'file': out_tif, 'mode': mode, 'bands': bands, 'band_names': [names[b - 1] for b in bands],
                'rgb_bands': rgb, 'width': w, 'height': h, 'pixel_size': round(px, 2), 'epsg': epsg,
                'valid_pct': valid_pct, 'date': meta['date'], 'time': meta['time'], 'platform': meta['mission'],
                'instrument': meta['instrument'], 'incidence_deg': meta['incidence_deg'],
                'level': meta['level'], 'model_error_m': round(err, 2), 'alignment': align_info,
                'attribution': ATTRIBUTION}
    finally:
        if not work_dir:
            shutil.rmtree(work, ignore_errors=True)


def _frame_bbox(meta):
    xs, ys = [v[2] for v in meta['vertices']], [v[3] for v in meta['vertices']]
    return [min(xs), min(ys), max(xs), max(ys)]


def download(identifier, bbox, out_tif, api_key, mode='false', align=True, cache_dir=None, keep_zip=True,
             http=None):
    """Busca a cena, baixa o zip (ou usa o cache), georreferencia/alinha e recorta ao BBOX."""
    scene = get_scene(identifier, bbox, http=http)
    if bbox and scene.get('coverage_pct') is not None and scene['coverage_pct'] <= 0:
        raise SpotError(u"A cena %s não cobre a área escolhida." % identifier)
    _log(u"SPOT: %s %s %s (%.0f MB)" % (scene['date'], scene['platform'], scene['mode_label'],
                                        (scene.get('zip_size') or 0) / 1e6))
    zip_path = download_zip(scene, api_key, cache_dir)
    res = georeference(zip_path, out_tif, bbox, mode=mode, align=align, footprint=scene.get('footprint'))
    res.update(scene_id=scene['id'], cloud_cover=scene.get('cloud_cover'), coverage_pct=scene.get('coverage_pct'),
               zip_path=zip_path if keep_zip else None)
    if not keep_zip:
        _remove(zip_path)
    try:
        import xyz_core
        xyz_core.build_overviews(res['file'])   # piramides prontas: a carga no ArcMap nao trava
    except Exception:
        pass
    return res
