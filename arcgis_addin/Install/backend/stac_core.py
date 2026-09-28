# -*- coding: utf-8 -*-
"""
Busca e download de imagens CBERS-4/4A e Amazonia-1 via STAC do INPE - Python 3 + GDAL.

Catalogo: https://data.inpe.br/bdc/stac/v1 (navegador: https://data.inpe.br/stac/browser/)
Os arquivos sao GeoTIFF publicos (sem token). O recorte e feito por leitura parcial HTTP
(/vsicurl/ do GDAL): apenas a janela de pixels da area de interesse e transferida, na grade
e resolucao NATIVAS da cena (srcWin em pixels inteiros, sem reamostragem).
"""
import datetime as _dt
import json
import math
import os
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    from osgeo import gdal, osr
    gdal.UseExceptions()
    HAS_GDAL = True
except Exception:  # pragma: no cover
    gdal = osr = None
    HAS_GDAL = False

STAC_URL = os.environ.get('ARCMAGERY_STAC_URL', 'https://data.inpe.br/bdc/stac/v1').rstrip('/')
USER_AGENT = 'ArcMagery/2.0 (+https://github.com/Yiuky/arcgis-google-earth-engine-explorer)'

# Bandas por camera (especificacao INPE). Ordem: azul, verde, vermelho, NIR.
_MUX = ['BAND5', 'BAND6', 'BAND7', 'BAND8']
_WFI = ['BAND13', 'BAND14', 'BAND15', 'BAND16']
_WPM = ['BAND1', 'BAND2', 'BAND3', 'BAND4']
_AMZ = ['BAND1', 'BAND2', 'BAND3', 'BAND4']

COLLECTIONS = {
    'CB4A-WPM-L4-DN-1': {'label': u'CBERS-4A WPM - 8 m multiespectral + 2 m pancromática (L4)',
                         'ms': _WPM, 'pan': 'BAND0', 'res': 8.0, 'pan_res': 2.0},
    'CB4A-WPM-PCA-FUSED-1': {'label': u'CBERS-4A WPM - 2 m fusionada RGB (PCA)',
                             'fused': 'rgb', 'res': 2.0},
    'CB4A-MUX-L4-DN-1': {'label': u'CBERS-4A MUX - 16 m (L4 DN)', 'ms': _MUX, 'res': 16.5},
    'CB4A-MUX-L4-SR-1': {'label': u'CBERS-4A MUX - 16 m reflectância de superfície', 'ms': _MUX, 'res': 16.5},
    'CB4A-WFI-L4-SR-1': {'label': u'CBERS-4A WFI - 55 m reflectância de superfície', 'ms': _WFI, 'res': 55.0},
    'CB4-MUX-L4-SR-1': {'label': u'CBERS-4 MUX - 20 m reflectância de superfície', 'ms': _MUX, 'res': 20.0},
    'CB4-MUX-L4-DN-1': {'label': u'CBERS-4 MUX - 20 m (L4 DN)', 'ms': _MUX, 'res': 20.0},
    'CB4-WFI-L4-SR-1': {'label': u'CBERS-4 WFI - 64 m reflectância de superfície', 'ms': _WFI, 'res': 64.0},
    'CB4-PAN10M-L4-DN-1': {'label': u'CBERS-4 PAN - 10 m (verde, vermelho, NIR)',
                           'ms3': ['BAND2', 'BAND3', 'BAND4'], 'res': 10.0},
    'CB4-PAN5M-L4-DN-1': {'label': u'CBERS-4 PAN - 5 m pancromática', 'pan': 'BAND1', 'res': 5.0, 'pan_res': 5.0},
    'AMZ1-WFI-L4-SR-1': {'label': u'Amazônia-1 WFI - 64 m reflectância de superfície', 'ms': _AMZ, 'res': 64.0},
    'AMZ1-WFI-L4-DN-1': {'label': u'Amazônia-1 WFI - 64 m (L4 DN)', 'ms': _AMZ, 'res': 64.0},
}

MODES = {
    'rgb': u'Cor natural (R-G-B)',
    'false': u'Falsa cor (NIR-R-G)',
    'multi': u'Multibanda (todas as bandas)',
    'pan': u'Pancromática',
    'fused': u'Fusionada RGB',
}

DEFAULT_MAX_PIXELS = 20000 * 20000


class StacError(RuntimeError):
    pass


def _log(msg):
    sys.stderr.write("[ArcGEE] " + msg + "\n")
    sys.stderr.flush()


def available_modes(collection_id):
    c = COLLECTIONS.get(collection_id, {})
    modes = []
    if c.get('ms'):
        modes += ['rgb', 'false', 'multi']
    if c.get('ms3'):
        modes += ['false', 'multi']
    if c.get('pan'):
        modes.append('pan')
    if c.get('fused'):
        modes.append('fused')
    return modes


def band_plan(collection_id, mode):
    """Retorna (lista_de_assets_na_ordem_do_arquivo, indices_rgb_0based) para o modo."""
    c = COLLECTIONS.get(collection_id)
    if not c:
        raise StacError(u"Coleção não suportada: %s" % collection_id)
    if mode not in available_modes(collection_id):
        raise StacError(u"Modo '%s' indisponível para %s (disponíveis: %s)"
                        % (mode, collection_id, ', '.join(available_modes(collection_id))))
    if mode == 'pan':
        return [c['pan']], None
    if mode == 'fused':
        return [c['fused']], [0, 1, 2]
    if c.get('ms3'):  # CBERS-4 PAN10M: verde, vermelho, NIR
        g, r, n = c['ms3']
        if mode == 'false':
            return [n, r, g], [0, 1, 2]
        return [g, r, n], [2, 1, 0]
    b, g, r, n = c['ms']
    if mode == 'rgb':
        return [r, g, b], [0, 1, 2]
    if mode == 'false':
        return [n, r, g], [0, 1, 2]
    return [b, g, r, n], [2, 1, 0]  # multi: ordem espectral, exibindo R-G-B


# ------------------------------------------------------------------------------------ HTTP
def _http_json(url, body=None, timeout=60, retries=3):
    data = json.dumps(body).encode('utf-8') if body is not None else None
    headers = {'User-Agent': USER_AGENT, 'Accept': 'application/geo+json, application/json'}
    if data is not None:
        headers['Content-Type'] = 'application/json'
    ctx = ssl.create_default_context()  # usa o repositorio de certificados do Windows
    last = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                return json.loads(r.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code < 500 and e.code != 429:
                detail = e.read().decode('utf-8', 'replace')[:300]
                raise StacError(u"STAC respondeu HTTP %d: %s" % (e.code, detail))
            last = e
        except ssl.SSLError as e:
            raise StacError(u"Erro SSL ao acessar o STAC do INPE: %s" % e)
        except Exception as e:
            last = e
        time.sleep(1.5 * attempt)
    raise StacError(u"Falha ao acessar %s: %s" % (url, last))


def _download_file(url, dest, timeout=60):
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r, open(dest, 'wb') as f:
        while True:
            chunk = r.read(65536)
            if not chunk:
                break
            f.write(chunk)
    return dest


# ------------------------------------------------------------------------------------ busca
def _to_iso(date_str, end=False):
    """Aceita 'AAAA-MM-DD' ou 'DD/MM/AAAA'. Retorna RFC3339 (inicio/fim do dia)."""
    if not date_str:
        return '..'
    s = str(date_str).strip()
    for fmt in ('%Y-%m-%d', '%d/%m/%Y'):
        try:
            d = _dt.datetime.strptime(s, fmt).date()
            return d.strftime('%Y-%m-%d') + ('T23:59:59Z' if end else 'T00:00:00Z')
        except ValueError:
            continue
    raise StacError(u"Data inválida: %r (use DD/MM/AAAA)" % date_str)


def _ring_area(ring):
    a = 0.0
    for i in range(len(ring)):
        x0, y0 = ring[i][0], ring[i][1]
        x1, y1 = ring[(i + 1) % len(ring)][0], ring[(i + 1) % len(ring)][1]
        a += x0 * y1 - x1 * y0
    return abs(a) / 2.0


def _clip_ring_to_bbox(ring, bbox):
    """Sutherland-Hodgman: recorta um anel (lista de [x, y]) pelo retangulo bbox."""
    xmin, ymin, xmax, ymax = bbox
    edges = [
        (lambda p: p[0] >= xmin, lambda p, q: (xmin, p[1] + (q[1] - p[1]) * (xmin - p[0]) / (q[0] - p[0]))),
        (lambda p: p[0] <= xmax, lambda p, q: (xmax, p[1] + (q[1] - p[1]) * (xmax - p[0]) / (q[0] - p[0]))),
        (lambda p: p[1] >= ymin, lambda p, q: (p[0] + (q[0] - p[0]) * (ymin - p[1]) / (q[1] - p[1]), ymin)),
        (lambda p: p[1] <= ymax, lambda p, q: (p[0] + (q[0] - p[0]) * (ymax - p[1]) / (q[1] - p[1]), ymax)),
    ]
    out = [tuple(p[:2]) for p in ring]
    for inside, cross in edges:
        if not out:
            break
        src, out = out, []
        for i in range(len(src)):
            cur, prev = src[i], src[i - 1]
            if inside(cur):
                if not inside(prev):
                    out.append(cross(prev, cur))
                out.append(cur)
            elif inside(prev):
                out.append(cross(prev, cur))
    return out


def aoi_coverage_pct(geometry, bbox):
    """Percentual do BBOX coberto pelo footprint (Polygon/MultiPolygon GeoJSON) da cena."""
    if not geometry or not bbox:
        return None
    gtype = geometry.get('type')
    polys = [geometry['coordinates']] if gtype == 'Polygon' else         (geometry['coordinates'] if gtype == 'MultiPolygon' else [])
    box_area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
    if box_area <= 0 or not polys:
        return None
    covered = 0.0
    for poly in polys:
        if not poly:
            continue
        covered += _ring_area(_clip_ring_to_bbox(poly[0], bbox) or [(0, 0)])
        for hole in poly[1:]:
            covered -= _ring_area(_clip_ring_to_bbox(hole, bbox) or [(0, 0)])
    return round(max(0.0, min(100.0, 100.0 * covered / box_area)), 1)


def _bbox_polygon(bbox):
    x0, y0, x1, y1 = bbox
    return {'type': 'Polygon', 'coordinates': [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


def _summarize_item(f, aoi_bbox=None):
    p = f.get('properties', {})
    assets = f.get('assets', {})
    cloud = p.get('eo:cloud_cover')
    thumb = assets.get('thumbnail', {}).get('href')
    return {
        'id': f.get('id'),
        'collection': f.get('collection'),
        'datetime': p.get('datetime') or p.get('start_datetime'),
        'date': (p.get('datetime') or p.get('start_datetime') or '')[:10],
        'cloud_cover': round(float(cloud), 1) if isinstance(cloud, (int, float)) else None,
        'bbox': f.get('bbox'),
        'thumbnail': thumb,
        'assets': sorted(k for k in assets if not k.endswith('_xml')),
        'satellite': p.get('platform') or p.get('satellite') or '',
        'path_row': '%s/%s' % (p.get('bdc:path', p.get('path', '')), p.get('bdc:row', p.get('row', ''))),
        'coverage_pct': aoi_coverage_pct(f.get('geometry'), aoi_bbox),
    }


def search(collections, bbox, start_date=None, end_date=None, max_cloud=None, max_items=100, page_size=50,
           min_coverage=0.5):
    """Busca cenas no STAC. bbox = [min_lon, min_lat, max_lon, max_lat] (WGS84).

    Usa 'intersects' (footprint real da cena) em vez de 'bbox' (retangulo envolvente da cena):
    com 'bbox', cenas inclinadas cujo retangulo toca a area - mas cuja imagem nao - eram
    retornadas e o recorte saia 100% NoData. O servidor do INPE avalia `intersects` pelo
    retangulo envolvente, por isso a cobertura real (coverage_pct) e calculada aqui sobre o
    footprint e cenas abaixo de min_coverage (%) sao descartadas."""
    if isinstance(collections, str):
        collections = [c.strip() for c in collections.split(',') if c.strip()]
    if not collections:
        raise StacError(u"Informe ao menos uma coleção.")
    if not bbox or len(bbox) != 4:
        raise StacError(u"Filtro espacial obrigatório (bbox WGS84).")
    x0, y0, x1, y1 = [float(v) for v in bbox]
    bbox = [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]
    body = {'collections': collections, 'intersects': _bbox_polygon(bbox), 'limit': int(page_size),
            'datetime': '%s/%s' % (_to_iso(start_date), _to_iso(end_date, end=True))}
    url = STAC_URL + '/search'
    results, pages = [], 0
    while url and len(results) < max_items and pages < 40:
        page = _http_json(url, body)
        pages += 1
        for f in page.get('features', []):
            item = _summarize_item(f, bbox)
            if max_cloud is not None and item['cloud_cover'] is not None and item['cloud_cover'] > float(max_cloud):
                continue
            if min_coverage is not None and item['coverage_pct'] is not None and item['coverage_pct'] < float(min_coverage):
                continue
            results.append(item)
        nxt = next((l for l in page.get('links', []) if l.get('rel') == 'next'), None)
        if not nxt or not page.get('features'):
            break
        url = nxt.get('href')
        if (nxt.get('method') or 'GET').upper() == 'POST':
            body = dict(body, **(nxt.get('body') or {})) if nxt.get('merge') else (nxt.get('body') or body)
        else:
            body = None
    results.sort(key=lambda it: it.get('datetime') or '', reverse=True)
    return results[:max_items]


def get_item(collection_id, item_id):
    return _http_json('%s/collections/%s/items/%s' % (STAC_URL, urllib.parse.quote(collection_id),
                                                     urllib.parse.quote(item_id)))


def thumbnail(collection_id, item_id, out_png=None, href=None):
    """Baixa a miniatura PNG e gera um GIF (Tk 8.5 do ArcGIS nao le PNG)."""
    if not href:
        href = get_item(collection_id, item_id).get('assets', {}).get('thumbnail', {}).get('href')
    if not href:
        raise StacError(u"Cena sem miniatura.")
    out_png = out_png or os.path.join(tempfile.gettempdir(), 'arcmagery_thumb_%s.png' % item_id)
    _download_file(href, out_png)
    gif = os.path.splitext(out_png)[0] + '.gif'
    try:
        from PIL import Image
        with Image.open(out_png) as im:
            im = im.convert('RGB')
            im.thumbnail((420, 420))
            im.save(gif, 'GIF')
    except Exception:
        gif = None
    return {'file': out_png, 'gif': gif, 'url': href}


# ---------------------------------------------------------------------------------- download
def windows_ca_bundle(path=None):
    """Exporta os certificados raiz/intermediarios do Windows para um PEM.

    O curl embutido no GDAL nao usa o repositorio do Windows; sem isso as leituras /vsicurl/
    falham ("HTTP response code 0") quando o Python nao e o do QGIS ou quando a rede usa
    proxy com inspecao SSL (a CA corporativa fica apenas no repositorio do Windows).
    """
    if not hasattr(ssl, 'enum_certificates'):
        return None
    path = path or os.path.join(tempfile.gettempdir(), 'arcmagery_ca_bundle.pem')
    try:
        if os.path.exists(path) and time.time() - os.path.getmtime(path) < 86400:
            return path
        pems, seen = [], set()
        for store in ('ROOT', 'CA'):
            for cert, enc, trust in ssl.enum_certificates(store):
                if enc != 'x509_asn' or cert in seen:
                    continue
                if trust is not True and '1.3.6.1.5.5.7.3.1' not in (trust or ()):
                    continue  # apenas certificados confiaveis para autenticacao de servidor
                seen.add(cert)
                pems.append(ssl.DER_cert_to_PEM_cert(cert))
        if not pems:
            return None
        tmp = path + '.%d.tmp' % os.getpid()
        with open(tmp, 'w') as f:
            f.write(''.join(pems))
        os.replace(tmp, path)
        return path
    except Exception:
        return None


def configure_gdal_http():
    if not (os.environ.get('CURL_CA_BUNDLE') or gdal.GetConfigOption('GDAL_CURL_CA_BUNDLE')):
        bundle = windows_ca_bundle()
        if bundle:
            gdal.SetConfigOption('GDAL_CURL_CA_BUNDLE', bundle)
    for k, v in {
        'GDAL_DISABLE_READDIR_ON_OPEN': 'EMPTY_DIR',
        'CPL_VSIL_CURL_ALLOWED_EXTENSIONS': '.tif,.TIF,.tiff,.TIFF',
        'GDAL_HTTP_MAX_RETRY': '5',
        'GDAL_HTTP_RETRY_DELAY': '2',
        'GDAL_HTTP_TIMEOUT': '120',
        'GDAL_HTTP_MULTIRANGE': 'YES',
        'GDAL_HTTP_MERGE_CONSECUTIVE_RANGES': 'YES',
        'VSI_CACHE': 'TRUE',
        'GDAL_HTTP_USERAGENT': USER_AGENT,
    }.items():
        if gdal.GetConfigOption(k) is None:
            gdal.SetConfigOption(k, v)


def _vsi(href):
    if href.startswith(('http://', 'https://')):
        return '/vsicurl/' + href
    return href  # caminho local (testes)


def bbox_to_srcwin(ds, bbox_wgs84):
    """Converte o BBOX WGS84 em janela de pixels inteiros (xoff, yoff, xsize, ysize) do raster.
    Levanta StacError se nao houver intersecao."""
    gt = ds.GetGeoTransform()
    if gt[2] != 0 or gt[4] != 0:
        raise StacError(u"Raster rotacionado não suportado.")
    dst = osr.SpatialReference()
    dst.ImportFromWkt(ds.GetProjection())
    src = osr.SpatialReference()
    src.ImportFromEPSG(4326)
    for s in (src, dst):
        s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    ct = osr.CoordinateTransformation(src, dst)
    x0, y0, x1, y1 = [float(v) for v in bbox_wgs84]
    minx, miny, maxx, maxy = ct.TransformBounds(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1), 21)
    px0 = int(math.floor((minx - gt[0]) / gt[1]))
    px1 = int(math.ceil((maxx - gt[0]) / gt[1]))
    py0 = int(math.floor((maxy - gt[3]) / gt[5]))
    py1 = int(math.ceil((miny - gt[3]) / gt[5]))
    px0, py0 = max(0, px0), max(0, py0)
    px1, py1 = min(ds.RasterXSize, px1), min(ds.RasterYSize, py1)
    if px1 <= px0 or py1 <= py0:
        raise StacError(u"A cena não cobre a área de interesse.")
    return px0, py0, px1 - px0, py1 - py0


def _has_valid_pixels(band):
    try:
        mn, mx = band.ComputeRasterMinMax(False)
        return mx is not None
    except RuntimeError:
        return False  # GDAL: "no valid pixels found"


def download(collection_id, item_id, bbox, out_tif=None, mode='rgb', item=None,
             max_pixels=DEFAULT_MAX_PIXELS, progress=None):
    """Recorta a cena ao BBOX (grade nativa) e grava um GeoTIFF multibanda.
    Retorna dict com caminho, bandas, indices RGB e dimensoes."""
    if not HAS_GDAL:
        raise StacError(u"O download CBERS requer GDAL (use o Python do QGIS ou o venv do ArcMagery).")
    configure_gdal_http()
    assets_order, rgb = band_plan(collection_id, mode)
    feature = item or get_item(collection_id, item_id)
    assets = feature.get('assets', {})
    missing = [a for a in assets_order if a not in assets]
    if missing:
        raise StacError(u"Cena %s sem as bandas %s." % (item_id, ', '.join(missing)))
    sources = [_vsi(assets[a]['href']) for a in assets_order]

    if not out_tif:
        out_tif = os.path.join(tempfile.gettempdir(), '%s_%s.tif' % (item_id, mode))
    out_tif = os.path.abspath(out_tif)
    os.makedirs(os.path.dirname(out_tif), exist_ok=True)

    _log(u"CBERS %s: abrindo %d banda(s) remotas..." % (item_id, len(sources)))
    vrt_path = '/vsimem/arcmagery_%s_%d.vrt' % (item_id, int(time.time() * 1000))
    vrt = gdal.BuildVRT(vrt_path, sources, separate=True)
    if vrt is None:
        raise StacError(u"Falha ao montar as bandas da cena %s." % item_id)
    try:
        xoff, yoff, xsize, ysize = bbox_to_srcwin(vrt, bbox)
        if xsize * ysize > max_pixels:
            raise StacError(u"Recorte de %d x %d px excede o limite (%d Mpx). Reduza a área."
                            % (xsize, ysize, max_pixels // 1000000))
        _log(u"CBERS %s: recortando %d x %d px (%s)..." % (item_id, xsize, ysize, mode))

        def _cb(pct, _msg, _data):
            if progress:
                progress(pct)
            _log(u"PROGRESS %d/100" % int(pct * 100))
            return 1

        tmp = out_tif + '.part.tif'
        gdal.Translate(tmp, vrt, srcWin=[xoff, yoff, xsize, ysize], noData=0,
                       creationOptions=['TILED=YES', 'COMPRESS=DEFLATE', 'PREDICTOR=2', 'BIGTIFF=IF_SAFER'],
                       callback=_cb)
        out = gdal.Open(tmp, gdal.GA_Update)
        for i, a in enumerate(assets_order):
            out.GetRasterBand(i + 1).SetDescription(a)
        if not _has_valid_pixels(out.GetRasterBand(1)):
            out = None
            os.remove(tmp)
            raise StacError(u"A área de interesse cai fora da parte imageada da cena %s (recorte 100%% NoData). "
                            u"Escolha uma cena com maior cobertura." % item_id)
        gt, w, h = out.GetGeoTransform(), out.RasterXSize, out.RasterYSize
        epsg = osr.SpatialReference(wkt=out.GetProjection()).GetAuthorityCode(None)
        out = None
        if os.path.exists(out_tif):
            os.remove(out_tif)
        os.replace(tmp, out_tif)
    finally:
        vrt = None
        try:
            gdal.Unlink(vrt_path)
        except RuntimeError:
            pass  # VRT em memoria nunca materializado: nada a remover (nao mascarar o erro real)
    return {'file': out_tif, 'item_id': item_id, 'collection': collection_id, 'mode': mode,
            'bands': assets_order, 'rgb_bands': rgb, 'width': w, 'height': h,
            'pixel_size': abs(gt[1]), 'epsg': epsg}
