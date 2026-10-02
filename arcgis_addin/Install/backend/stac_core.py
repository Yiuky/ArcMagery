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
import re
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qgis_env  # noqa: E402,F401  (DLLs do GDAL do QGIS antes do import do osgeo)

try:
    from osgeo import gdal, osr
    gdal.UseExceptions()
    HAS_GDAL = True
except Exception:  # pragma: no cover
    gdal = osr = None
    HAS_GDAL = False

STAC_URL = os.environ.get('ARCMAGERY_STAC_URL', 'https://data.inpe.br/bdc/stac/v1').rstrip('/')
USER_AGENT = 'ArcMagery/2.0 (+https://github.com/Yiuky/ArcMagery)'

# Bandas por camera (especificacao INPE). Ordem: azul, verde, vermelho, NIR.
_MUX = ['BAND5', 'BAND6', 'BAND7', 'BAND8']
_WFI = ['BAND13', 'BAND14', 'BAND15', 'BAND16']
_WPM = ['BAND1', 'BAND2', 'BAND3', 'BAND4']
_AMZ = ['BAND1', 'BAND2', 'BAND3', 'BAND4']

COLLECTIONS = {
    'CB4A-WPM-L4-DN-1': {'label': u'CBERS-4A WPM - 8 m multiespectral + 2 m pancromática (L4)',
                         'ms': _WPM, 'pan': 'BAND0', 'res': 8.0, 'pan_res': 2.0},
    'CB4A-WPM-PCA-FUSED-1': {'label': u'CBERS-4A WPM - 2 m fusionada RGB (PCA)',
                             'fused': 'tci', 'res': 2.0},   # um COG com as 3 bandas
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

    # --- Nivel 4 DN do WFI (a versao SR ja existia)
    'CB4A-WFI-L4-DN-1': {'label': u'CBERS-4A WFI - 55 m (L4 DN)', 'ms': _WFI, 'res': 55.0},
    'CB4-WFI-L4-DN-1': {'label': u'CBERS-4 WFI - 64 m (L4 DN)', 'ms': _WFI, 'res': 64.0},

    # --- Cubos de dados do Brazil Data Cube: composicoes temporais sem nuvem + NDVI/EVI prontos
    'CBERS4-WFI-16D-2': {'label': u'Cubo 16 dias - CBERS-4 WFI 64 m (sem nuvens, NDVI/EVI)', 'ms': _WFI, 'res': 64.0,
                         'extra': 'indices'},
    'CBERS-WFI-8D-1': {'label': u'Cubo 8 dias - CBERS-4/4A WFI 64 m (sem nuvens, NDVI/EVI)', 'ms': _WFI, 'res': 64.0,
                       'extra': 'indices'},
    'CBERS4-MUX-2M-1': {'label': u'Cubo 2 meses - CBERS-4 MUX 20 m (sem nuvens, NDVI/EVI)', 'ms': _MUX, 'res': 20.0,
                        'extra': 'indices'},

    # --- Nivel 2 (correcao sistematica, SEM ortorretificacao: geometria menos precisa que o L4)
    'CB4A-WPM-L2-DN-1': {'label': u'CBERS-4A WPM - 8 m + 2 m PAN (Nível 2, sem ortorretificação)',
                         'ms': _WPM, 'pan': 'BAND0', 'res': 8.0, 'pan_res': 2.0},
    'CB4A-MUX-L2-DN-1': {'label': u'CBERS-4A MUX - 16 m (Nível 2, sem ortorretificação)', 'ms': _MUX, 'res': 16.5},
    'CB4A-WFI-L2-DN-1': {'label': u'CBERS-4A WFI - 55 m (Nível 2, sem ortorretificação)', 'ms': _WFI, 'res': 55.0},
    'CB4-MUX-L2-DN-1': {'label': u'CBERS-4 MUX - 20 m (Nível 2, sem ortorretificação)', 'ms': _MUX, 'res': 20.0},
    'CB4-WFI-L2-DN-1': {'label': u'CBERS-4 WFI - 64 m (Nível 2, sem ortorretificação)', 'ms': _WFI, 'res': 64.0},
    'CB4-PAN10M-L2-DN-1': {'label': u'CBERS-4 PAN - 10 m (Nível 2, sem ortorretificação)',
                           'ms3': ['BAND2', 'BAND3', 'BAND4'], 'res': 10.0},
    'CB4-PAN5M-L2-DN-1': {'label': u'CBERS-4 PAN - 5 m pancromática (Nível 2, sem ortorretificação)',
                          'pan': 'BAND1', 'res': 5.0, 'pan_res': 5.0},
    'AMZ1-WFI-L2-DN-1': {'label': u'Amazônia-1 WFI - 64 m (Nível 2, sem ortorretificação)', 'ms': _AMZ, 'res': 64.0},

    # --- Historico CBERS-2 (2003-2009) e CBERS-2B (2007-2010). A CCD separa as bandas em dois
    #     grupos: CCD1XS = B2 verde, B3 vermelho, B4 NIR; CCD2XS = B1 azul, B3; CCD2PAN = B5 pan.
    'CB2-CCD-L2-DN-1': {'label': u'CBERS-2 CCD - 20 m (2003-2009, Nível 2)', 'res': 20.0, 'modes': 'ccd'},
    'CB2B-CCD-L2-DN-1': {'label': u'CBERS-2B CCD - 20 m (2007-2010, Nível 2)', 'res': 20.0, 'modes': 'ccd'},
    'CB2B-HRC-L2-DN-1': {'label': u'CBERS-2B HRC - 2,5 m pancromática (2007-2010, Nível 2)',
                         'pan': 'BAND1', 'res': 2.5, 'pan_res': 2.5},
    'CB2-WFI-L2-DN-1': {'label': u'CBERS-2 WFI - 260 m (2003-2005, vermelho + NIR)', 'res': 260.0, 'modes': 'wfi2'},
    'CB2B-WFI-L2-DN-1': {'label': u'CBERS-2B WFI - 260 m (2007-2010, vermelho + NIR)', 'res': 260.0, 'modes': 'wfi2'},

    # --- Mosaicos trimestrais (produto visual RGB)
    'mosaic-cbers4-brazil-3m-1': {'label': u'Mosaico Brasil - CBERS-4 WFI (abr-jun/2020, RGB)', 'res': 64.0,
                                  'modes': 'visual'},
    'mosaic-cbers4a-paraiba-3m-1': {'label': u'Mosaico Paraíba - CBERS-4A WFI (jul-set/2020, RGB)', 'res': 55.0,
                                    'modes': 'visual'},
}

# Planos de bandas especiais: modo -> (assets na ordem do arquivo, indices RGB 0-based ou None)
_SPECIAL_PLANS = {
    'ccd': [
        ('rgb', (['CCD1XS_BAND3', 'CCD1XS_BAND2', 'CCD2XS_BAND1'], [0, 1, 2])),
        ('false', (['CCD1XS_BAND4', 'CCD1XS_BAND3', 'CCD1XS_BAND2'], [0, 1, 2])),
        ('multi', (['CCD2XS_BAND1', 'CCD1XS_BAND2', 'CCD1XS_BAND3', 'CCD1XS_BAND4'], [2, 1, 0])),
        ('pan', (['CCD2PAN_BAND5'], None)),
    ],
    'wfi2': [('multi', (['BAND1', 'BAND2'], None))],       # vermelho + NIR (sem banda verde/azul)
    'visual': [('visual', (['VISUAL'], [0, 1, 2]))],
}
# Nomes alternativos de assets (o STAC do INPE publica a fusionada como 'tci'; 'rgb' era o nome antigo)
ASSET_ALIASES = {'TCI': ('RGB', 'VISUAL'), 'VISUAL': ('TCI',)}


def resolve_asset(assets, name):
    """Asset pelo nome, sem diferenciar maiusculas e aceitando os nomes alternativos."""
    by_upper = dict((k.upper(), v) for k, v in assets.items())
    for cand in (name.upper(),) + ASSET_ALIASES.get(name.upper(), ()):
        if cand in by_upper:
            return by_upper[cand]
    return None


_EXTRA_PLANS = {
    'indices': [('ndvi', (['NDVI'], None)), ('evi', (['EVI'], None))],   # Int16, escala 0,0001
}

MODES = {
    'rgb': u'Cor natural (R-G-B)',
    'false': u'Falsa cor (NIR-R-G)',
    'multi': u'Multibanda (todas as bandas)',
    'pan': u'Pancromática',
    'fused': u'Fusionada RGB',
    'ndvi': u'NDVI (índice de vegetação, escala 0,0001)',
    'evi': u'EVI (índice de vegetação, escala 0,0001)',
    'visual': u'RGB visual (mosaico)',
}

DEFAULT_MAX_PIXELS = 20000 * 20000


class StacError(RuntimeError):
    pass


def _log(msg):
    sys.stderr.write("[ArcGEE] " + msg + "\n")
    sys.stderr.flush()


def _plans(c):
    """Lista ordenada (modo, (assets, rgb)) de uma colecao."""
    if c.get('modes'):
        plans = list(_SPECIAL_PLANS[c['modes']])
    else:
        plans = []
        if c.get('ms'):
            b, g, r, n = c['ms']
            plans += [('rgb', ([r, g, b], [0, 1, 2])), ('false', ([n, r, g], [0, 1, 2])),
                      ('multi', ([b, g, r, n], [2, 1, 0]))]   # multi: ordem espectral, exibida R-G-B
        if c.get('ms3'):  # CBERS-4 PAN10M: verde, vermelho, NIR (sem azul)
            g, r, n = c['ms3']
            plans += [('false', ([n, r, g], [0, 1, 2])), ('multi', ([g, r, n], [2, 1, 0]))]
        if c.get('pan'):
            plans.append(('pan', ([c['pan']], None)))
        if c.get('fused'):
            plans.append(('fused', ([c['fused']], [0, 1, 2])))
    if c.get('extra'):
        plans += _EXTRA_PLANS[c['extra']]
    return plans


def available_modes(collection_id):
    return [m for m, _p in _plans(COLLECTIONS.get(collection_id, {}))]


def band_plan(collection_id, mode):
    """Retorna (lista_de_assets_na_ordem_do_arquivo, indices_rgb_0based) para o modo."""
    c = COLLECTIONS.get(collection_id)
    if not c:
        raise StacError(u"Coleção não suportada: %s" % collection_id)
    plans = dict(_plans(c))
    if mode not in plans:
        raise StacError(u"Modo '%s' indisponível para %s (disponíveis: %s)"
                        % (mode, collection_id, ', '.join(available_modes(collection_id))))
    assets, rgb = plans[mode]
    return list(assets), (list(rgb) if rgb else None)


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


def footprint_is_envelope(geometry):
    """True quando o 'footprint' e so o retangulo envolvente alinhado aos eixos (ex.: CBERS-2/2B):
    a cobertura calculada sobre ele e apenas um LIMITE SUPERIOR, pois a cena real e inclinada."""
    try:
        if geometry.get('type') != 'Polygon' or len(geometry['coordinates']) != 1:
            return False
        ring = [tuple(p[:2]) for p in geometry['coordinates'][0]]
        if ring[0] == ring[-1]:
            ring = ring[:-1]
        if len(ring) != 4:
            return False
        xs, ys = set(round(p[0], 6) for p in ring), set(round(p[1], 6) for p in ring)
        return len(xs) == 2 and len(ys) == 2
    except (KeyError, TypeError, AttributeError, IndexError):
        return False


MEASURE_MAX_ITEMS = 100     # teto de cenas medidas por busca (cada medida ~1 s, 8 em paralelo)
MEASURE_SAMPLE = 64         # a janela da area e lida reduzida a no maximo 64 x 64 px


def needs_measured_coverage(item):
    """O 'footprint' publicado pelo INPE nem sempre descreve a imagem (medido em 2026-10-02 em Cuiaba):
      - retangulo envolvente (Amazonia-1 WFI L2, parte do CBERS-2): cobria a area, imagem 0%;
      - poligono do CBERS-2 CCD/WFI Nivel 2 (sem ortorretificacao): 100% pelo poligono, imagem 0%;
      - bordas de cena (poligono parcial) tambem divergem.
    Medir na imagem tudo que nao for Nivel 4+ com o poligono cobrindo a area inteira."""
    cov = item.get('coverage_pct')
    return bool(item.get('coverage_is_estimate') or '-L2-' in (item.get('collection') or '')
                or (cov is not None and cov < 99.5))


def measured_coverage_pct(feature, bbox):
    """Cobertura REAL da area na imagem: le a janela da area (reduzida) da 1a banda da cena e conta os
    pixels com imagem. Para cenas cujo 'footprint' e so o retangulo envolvente (ex.: Amazonia-1 WFI
    Nivel 2): o retangulo da passagem (~10 graus) cobria a area, mas a faixa imageada, inclinada, nao,
    e o recorte saia 100% NoData. Retorna None se nao der para medir (sem GDAL, rede)."""
    if not HAS_GDAL:
        return None
    try:
        import numpy as np
        coll = feature.get('collection')
        modes = available_modes(coll)
        if not modes:
            return None
        first = band_plan(coll, modes[0])[0][0]
        asset = resolve_asset(feature.get('assets', {}), first)
        if not asset or not asset.get('href'):
            return None
        configure_gdal_http()
        ds = gdal.Open(_vsi(asset['href']))
        if ds is None:
            return None
        try:
            try:
                x, y, w, h = bbox_to_srcwin(ds, bbox)
            except StacError:
                return 0.0
            band = ds.GetRasterBand(1)
            arr = band.ReadAsArray(x, y, w, h, buf_xsize=min(w, MEASURE_SAMPLE), buf_ysize=min(h, MEASURE_SAMPLE))
            nd = band.GetNoDataValue()
            valid = (arr != nd) if nd is not None else (arr != 0)
            return round(100.0 * float(np.mean(valid)), 1)
        finally:
            band = ds = None
            # As conexoes /vsicurl/ ficam presas a THREAD que as abriu: sem fecha-las aqui, o
            # hard_exit do run_gee (que limpa so a thread principal) espera a E/S de rede e o
            # processo nao encerra (mesmo sintoma do recorte CBERS, ver run_gee.hard_exit).
            try:
                gdal.VSICurlClearCache()
            except Exception:
                pass
    except Exception:
        return None


def measure_envelope_coverage(items, bbox, workers=8):
    """Troca a cobertura estimada (retangulo envolvente) pela medida na imagem, em paralelo. Itens sem
    medida (falha de rede) continuam com a estimativa e coverage_is_estimate=True."""
    todo = [it for it in items if it.get('_feature') is not None][:MEASURE_MAX_ITEMS]
    if todo and HAS_GDAL:
        _log(u"INPE: medindo na imagem a cobertura real de %d cena(s)..." % len(todo))
        configure_gdal_http()   # opcoes globais do GDAL: uma vez, antes das threads
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(workers, len(todo))) as pool:
            measured = list(pool.map(lambda it: measured_coverage_pct(it['_feature'], bbox), todo))
        for it, pct in zip(todo, measured):
            if pct is not None:
                it['coverage_pct'] = pct
                it['coverage_is_estimate'] = False
                it['coverage_measured'] = True
    for it in items:
        it.pop('_feature', None)
    return items


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
        'coverage_is_estimate': footprint_is_envelope(f.get('geometry') or {}),
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
        try:
            page = _http_json(url, body)
        except StacError as e:
            # O servidor do INPE responde HTTP 500 ao filtro 'intersects' em algumas colecoes
            # (ex.: mosaicos). Repetir com 'bbox': a cobertura real e calculada aqui de qualquer forma.
            if pages == 0 and body and 'intersects' in body and re.search(r'HTTP( Error)? 500', str(e)):
                body = dict(body)
                body.pop('intersects')
                body['bbox'] = bbox
                if body.get('datetime') == '../..':
                    body.pop('datetime')
                page = _http_json(url, body)
            else:
                raise
        pages += 1
        for f in page.get('features', []):
            item = _summarize_item(f, bbox)
            if max_cloud is not None and item['cloud_cover'] is not None and item['cloud_cover'] > float(max_cloud):
                continue
            if needs_measured_coverage(item):
                item['_feature'] = f   # medida abaixo, na imagem
            elif min_coverage is not None and item['coverage_pct'] is not None and item['coverage_pct'] < float(min_coverage):
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
    measure_envelope_coverage(results, bbox)
    if min_coverage is not None:
        results = [it for it in results if it['coverage_pct'] is None or it['coverage_pct'] >= float(min_coverage)]
    results = dedupe_same_scene(results)
    results.sort(key=lambda it: it.get('datetime') or '', reverse=True)
    return results[:max_items]


def dedupe_same_scene(items):
    """O INPE publica cenas do CBERS-2/2B duas vezes ('CBERS_2_CCD_...' e 'CBERS2_CCD_...') apontando
    para os MESMOS arquivos. Mantem uma linha por cena (mesmo identificador normalizado): o poligono
    real (cobertura exata) de uma e o horario real de aquisicao da outra (a segunda marca 00:00)."""
    by_key, out = {}, []
    for it in items:
        key = re.sub(r'^CBERS_2(B?)_', r'CBERS2\1_', it.get('id') or '')
        prev = by_key.get(key)
        if prev is None:
            by_key[key] = it
            out.append(it)
            continue
        keep, other = (prev, it) if not prev.get('coverage_is_estimate') or it.get('coverage_is_estimate') else (it, prev)
        if (keep.get('datetime') or '').endswith('T00:00:00.000000Z') and other.get('datetime'):
            keep['datetime'] = other['datetime']
        keep.setdefault('duplicate_ids', []).append(other['id'])
        if keep is not prev:
            out[out.index(prev)] = keep
            by_key[key] = keep
    return out


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
from sysenv import windows_ca_bundle  # noqa: E402  (PEM do repositorio do Windows; compartilhado com o GEE)


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


def transform_bounds(ct, minx, miny, maxx, maxy, densify=21):
    """ct.TransformBounds (GDAL >= 3.4) com alternativa para GDAL antigo: densifica as 4 bordas
    (densify pontos intermediarios em cada) com TransformPoints e pega o min/max."""
    if hasattr(ct, 'TransformBounds'):
        return tuple(ct.TransformBounds(minx, miny, maxx, maxy, densify))
    n = int(densify) + 1   # segmentos por borda
    pts = []
    for i in range(n + 1):
        t = i / float(n)
        x = minx + (maxx - minx) * t
        y = miny + (maxy - miny) * t
        pts.extend([(x, miny), (x, maxy), (minx, y), (maxx, y)])
    res = ct.TransformPoints(pts)
    xs = [p[0] for p in res if p[0] is not None and math.isfinite(p[0])]
    ys = [p[1] for p in res if p[1] is not None and math.isfinite(p[1])]
    if not xs or not ys:
        raise StacError(u"Não foi possível transformar a área de interesse para a projeção da cena.")
    return min(xs), min(ys), max(xs), max(ys)


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
    minx, miny, maxx, maxy = transform_bounds(ct, min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1), 21)
    px0 = int(math.floor((minx - gt[0]) / gt[1]))
    px1 = int(math.ceil((maxx - gt[0]) / gt[1]))
    py0 = int(math.floor((maxy - gt[3]) / gt[5]))
    py1 = int(math.ceil((miny - gt[3]) / gt[5]))
    px0, py0 = max(0, px0), max(0, py0)
    px1, py1 = min(ds.RasterXSize, px1), min(ds.RasterYSize, py1)
    if px1 <= px0 or py1 <= py0:
        raise StacError(u"A cena não cobre a área de interesse.")
    return px0, py0, px1 - px0, py1 - py0


def source_nodata(ds):
    """NoData declarado na 1a banda da origem (ex.: -9999 nos cubos do BDC); 0 se nao houver."""
    try:
        nd = ds.GetRasterBand(1).GetNoDataValue()
    except Exception:
        nd = None
    return 0 if nd is None else nd


def _remove_quiet(path):
    for p in (path, path + '.aux.xml'):
        try:
            if os.path.exists(p):
                os.remove(p)
        except OSError:
            pass


def _has_valid_pixels(band):
    try:
        mn, mx = band.ComputeRasterMinMax(False)
        return mx is not None
    except RuntimeError:
        return False  # GDAL: "no valid pixels found"


def valid_pixel_pct(band, max_side=1024):
    """Percentual de pixels com imagem (!= NoData/0) no recorte, estimado numa leitura reduzida."""
    import numpy as np
    w, h = band.XSize, band.YSize
    f = max(1.0, max(w, h) / float(max_side))
    bw, bh = max(1, int(w / f)), max(1, int(h / f))
    arr = band.ReadAsArray(0, 0, w, h, buf_xsize=bw, buf_ysize=bh)
    nd = band.GetNoDataValue()
    valid = (arr != nd) if nd is not None else (arr != 0)
    return round(100.0 * float(valid.mean()), 1)


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
    # 'visual' x 'VISUAL', 'tci' x 'rgb': casar sem diferenciar maiusculas e com nomes alternativos
    assets = dict((a, resolve_asset(assets, a)) for a in assets_order)
    missing = [a for a in assets_order if not assets[a]]
    assets = dict((a, v) for a, v in assets.items() if v)
    if missing:
        raise StacError(u"Cena %s sem as bandas %s." % (item_id, ', '.join(missing)))
    sources = [_vsi(assets[a]['href']) for a in assets_order]

    if not out_tif:
        out_tif = os.path.join(tempfile.gettempdir(), '%s_%s.tif' % (item_id, mode))
    out_tif = os.path.abspath(out_tif)
    os.makedirs(os.path.dirname(out_tif), exist_ok=True)

    _log(u"CBERS %s: abrindo %d banda(s) remotas..." % (item_id, len(sources)))
    vrt_path = '/vsimem/arcmagery_%s_%d.vrt' % (item_id, int(time.time() * 1000))
    # Um asset so (fusionada 'tci', mosaico 'visual') ja traz as 3 bandas: separate=True pegaria so a 1a
    vrt = gdal.BuildVRT(vrt_path, sources, separate=len(sources) > 1)
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
        out = None
        try:
            gdal.Translate(tmp, vrt, srcWin=[xoff, yoff, xsize, ysize], noData=source_nodata(vrt),
                           creationOptions=['TILED=YES', 'COMPRESS=DEFLATE', 'PREDICTOR=2', 'BIGTIFF=IF_SAFER'],
                           callback=_cb)
            out = gdal.Open(tmp, gdal.GA_Update)
            if len(assets_order) == out.RasterCount:
                for i, a in enumerate(assets_order):
                    out.GetRasterBand(i + 1).SetDescription(a)
            else:   # asset unico multibanda
                for i in range(out.RasterCount):
                    out.GetRasterBand(i + 1).SetDescription(u"%s_%s" % (assets_order[0], u"RGB"[i] if i < 3 else i + 1))
            if not _has_valid_pixels(out.GetRasterBand(1)):
                raise StacError(u"A área de interesse cai fora da parte imageada da cena %s (recorte 100%% NoData). "
                                u"Escolha uma cena com maior cobertura." % item_id)
            valid_pct = valid_pixel_pct(out.GetRasterBand(1))
            gt, w, h = out.GetGeoTransform(), out.RasterXSize, out.RasterYSize
            epsg = osr.SpatialReference(wkt=out.GetProjection()).GetAuthorityCode(None)
            out = None
        except BaseException:
            out = None   # fecha o handle antes de apagar o parcial (Windows bloqueia arquivo aberto)
            _remove_quiet(tmp)
            raise
        if os.path.exists(out_tif):
            os.remove(out_tif)
        for ext in ('.ovr', '.aux.xml'):   # piramides/estatisticas de um recorte anterior com o mesmo nome
            if os.path.exists(out_tif + ext):
                os.remove(out_tif + ext)
        os.replace(tmp, out_tif)
    finally:
        vrt = None
        try:
            gdal.Unlink(vrt_path)
        except RuntimeError:
            pass  # VRT em memoria nunca materializado: nada a remover (nao mascarar o erro real)
    return {'file': out_tif, 'item_id': item_id, 'collection': collection_id, 'mode': mode,
            'bands': assets_order, 'rgb_bands': rgb, 'width': w, 'height': h,
            'pixel_size': abs(gt[1]), 'epsg': epsg, 'valid_pct': valid_pct}
