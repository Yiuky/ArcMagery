# -*- coding: utf-8 -*-
"""
Imagens historicas do Google Earth por data (catalogo "Time Machine") - Python 3, sem executavel.

Porta do motor Keyhole do C:/DOWNLOADER_EARTH (historical_engine.py), adaptada ao ArcMagery:

  * Protocolo: dbRoot.v5 (chave XOR + versao da quadtree) -> pacotes da quadtree (protobuf,
    decifrados e zlib) -> camadas de data de cada tile -> tile JPEG da data (decifrado).
  * GRADE GEOGRAFICA EPSG:4326 (Plate Carree), NAO Web Mercator: no nivel L os tiles tem
    360/2^L graus e as linhas crescem para o norte (ver tilemath.keyhole_*). O GeoTIFF sai em
    EPSG:4326 nativo (sem reamostragem) ou reprojetado via GDAL.
  * Rede: urllib + ssl.create_default_context() (repositorio do Windows, CA da inspecao SSL).
    Nunca verify=False.
  * Decifracao vetorizada (numpy): o fluxo de chave so depende da posicao do byte.
  * Escrita incremental (xyz_core.GeoTiffBuilder): o mosaico nunca fica inteiro na memoria.
  * Pacotes da quadtree ficam em cache em disco (sao imutaveis por epoca).

Tiles sem imagem na data escolhida ficam pretos (nodata), como os tiles ausentes do xyz_core.
"""
import math
import os
import random
import re
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parallel  # noqa: E402
import tilemath  # noqa: E402

BASE_URL = 'https://khmdb.google.com'
USER_AGENT = 'GoogleEarth/7.3.6.9796(Windows;Qt;k;en;google;standard)'
ATTRIBUTION = u'Imagens históricas © Google Earth e provedores (Maxar, Airbus...)'
ALL_ZOOMS = (15, 16, 17, 18, 19, 20)
# Varredura de datas: ate FULL_SCAN_TILES tiles por zoom sao consultados um a um; acima disso (ou
# no z20, que exige um pacote da quadtree por tile do z19) a cobertura e ESTIMADA por amostragem.
FULL_SCAN_TILES = 60000
SAMPLE_TILES = 4000
Z20_SAMPLE_TILES = 1500
MAX_TILES = 100000          # ~6,5 Gpx no z18: GeoTIFF gravado por partes (BigTIFF)
SUBINDEX_MAX_SZ = 4
FALLBACK_QUADTREE_VERSION = 370
MIN_VALID_DATE = 545            # 0001-01-01 codificado: camada sem data

BASE_IMAGERY_PROVIDER = 0
PROVIDER_NAMES = {
    4: u"DigitalGlobe / Maxar",
    307: u"Maxar Technologies",
    308: u"Maxar Technologies",
    318: u"Maxar Technologies",
    379: u"CNES / Airbus",
    396: u"Maxar Technologies",
    418: u"Planet Labs",
}


def _log(msg):
    sys.stderr.write("[ArcGEE] " + msg + "\n")
    sys.stderr.flush()


def default_cache_dir():
    base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    return os.path.join(base, 'ArcMagery', 'cache', 'gehist')


# ------------------------------------------------------------------------------ protobuf
def read_varint(buf, idx):
    res = shift = 0
    while True:
        b = buf[idx]
        idx += 1
        res |= (b & 0x7F) << shift
        if not b & 0x80:
            return res, idx
        shift += 7


def _skip(buf, idx, wire):
    if wire == 0:
        return read_varint(buf, idx)[1]
    if wire == 1:
        return idx + 8
    if wire == 2:
        n, idx = read_varint(buf, idx)
        return idx + n
    if wire == 5:
        return idx + 4
    raise ValueError("wire type %d" % wire)


def iter_fields(buf):
    """(campo, wire, valor) de uma mensagem protobuf simples (sem grupos)."""
    idx = 0
    while idx < len(buf):
        tag, idx = read_varint(buf, idx)
        f, w = tag >> 3, tag & 7
        if w == 0:
            v, idx = read_varint(buf, idx)
        elif w == 2:
            n, idx = read_varint(buf, idx)
            v = buf[idx:idx + n]
            idx += n
        elif w in (1, 5):
            v = None
            idx = _skip(buf, idx, w)
        else:
            return
        yield f, w, v


def decode_date(code):
    """Inteiro de 20 bits do Google Earth -> 'AAAA-MM-DD' (ano bits 9+, mes 5..8, dia 0..4)."""
    return "%04d-%02d-%02d" % (code >> 9, (code >> 5) & 0x0F, code & 0x1F)


def google_earth_date(catalog_date):
    """Data como o Google Earth Pro exibe: a do catalogo MENOS 1 DIA.

    O catalogo guarda a data a 00:00 UTC e o Google Earth Pro a mostra no fuso local (UTC-3/-4 no
    Brasil), que cai no dia anterior (conferido pelo mantenedor: catalogo 2017-07-09 = GE Pro
    8/7/2017; 2022-06-28 = 27/6/2022). A data do catalogo continua na tag ARCMAGERY_CATALOG_DATE_UTC.
    """
    import datetime
    try:
        y, m, d = [int(v) for v in catalog_date.split('-')]
        return (datetime.date(y, m, d) - datetime.timedelta(days=1)).isoformat()
    except (ValueError, AttributeError):
        return catalog_date


def encode_date(year, month, day):
    return ((year & 0x7FF) << 9) | ((month & 0x0F) << 5) | (day & 0x1F)


def parse_node(buf):
    node = {'flags': None, 'cache_node_epoch': 0, 'layers': []}
    for f, w, v in iter_fields(buf):
        if w == 0 and f == 1:
            node['flags'] = v
        elif w == 0 and f == 2:
            node['cache_node_epoch'] = v
        elif w == 2:
            node['layers'].append(v)
    return node


def parse_packet(buf):
    """Pacote da quadtree: grupos SparseQuadtreeNode {3: indice, 4: no}. Retorna {indice: no}."""
    idx, nodes = 0, {}
    while idx < len(buf):
        tag, idx = read_varint(buf, idx)
        w = tag & 7
        if w != 3:
            idx = _skip(buf, idx, w)
            continue
        node_idx = node = None
        while idx < len(buf):
            gtag, idx = read_varint(buf, idx)
            gf, gw = gtag >> 3, gtag & 7
            if gw == 4:
                break
            if gw == 0:
                v, idx = read_varint(buf, idx)
                if gf == 3:
                    node_idx = v
            elif gw == 2:
                n, idx = read_varint(buf, idx)
                if gf == 4:
                    node = parse_node(buf[idx:idx + n])
                idx += n
            elif gw == 3:   # grupo aninhado: pular inteiro
                depth = 1
                while depth and idx < len(buf):
                    ntag, idx = read_varint(buf, idx)
                    nw = ntag & 7
                    if nw == 3:
                        depth += 1
                    elif nw == 4:
                        depth -= 1
                    else:
                        idx = _skip(buf, idx, nw)
            else:
                idx = _skip(buf, idx, gw)
        if node_idx is not None and node is not None:
            nodes[node_idx] = node
    return nodes


def parse_dated_layers(node):
    """Camadas com data de um no: [{'date', 'date_int', 'epoch', 'provider_id', 'provider'}]."""
    out = []
    for layer in node.get('layers') or []:
        dates_b = None
        for f, w, v in iter_fields(layer):
            if w == 2 and f == 4:
                dates_b = v
        if not dates_b:
            continue
        for f, w, v in iter_fields(dates_b):
            if not (w == 2 and f == 1):
                continue
            vals = dict((df, dv) for df, dw, dv in iter_fields(v) if dw == 0)
            d_int = vals.get(1)
            prov = vals.get(3)
            # Provedor 0 = marcador da imagem-base atual: o catalogo historico responde 404 para
            # esses tiles (medido: 0 de 8 baixaveis, contra 719 de 719 dos demais). Nao listar.
            if d_int and d_int > MIN_VALID_DATE and prov != BASE_IMAGERY_PROVIDER:
                catalog = decode_date(d_int)
                out.append({'date': google_earth_date(catalog), 'catalog_date': catalog,
                            'date_int': d_int, 'epoch': vals.get(2),
                            'provider_id': prov,
                            'provider': PROVIDER_NAMES.get(prov, u"Provedor %s" % prov)})
    return out


def _root_subindex(path):
    sub = 0
    for ch in path[1:]:
        sub = sub * SUBINDEX_MAX_SZ + int(ch) + 1
    return sub


def quadtree_subindex(path):
    if len(path) <= SUBINDEX_MAX_SZ:
        return _root_subindex(path)
    sub = path[(len(path) - 1) // SUBINDEX_MAX_SZ * SUBINDEX_MAX_SZ:]
    return _root_subindex(sub) + int(sub[0]) * 85 + 1


# -------------------------------------------------------------------------------- cliente
class KeyholeClient(object):
    """Cliente do catalogo historico. Seguro para uso em varias threads.

    cache_dir: None = cache padrao em disco; '' ou False = sem cache em disco.
    """

    def __init__(self, cache_dir=None, timeout=20.0, retries=4, fetch=None):
        self.cache_dir = default_cache_dir() if cache_dir is None else (cache_dir or None)
        if self.cache_dir:
            os.makedirs(self.cache_dir, exist_ok=True)
        self.timeout, self.retries = timeout, retries
        self._fetch = fetch or self._http_get
        self._ctx = ssl.create_default_context()
        self._packets = {}
        self._locks = {}
        self._meta_lock = threading.Lock()
        self._ks = b''
        self._ks_lock = threading.Lock()
        self.key = None
        self.quadtree_version = None
        self._init_dbroot()

    # ---- rede
    def _http_get(self, url):
        """bytes da resposta; None para 404. Levanta RuntimeError apos esgotar as retentativas."""
        last = None
        for attempt in range(1, self.retries + 1):
            try:
                req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': '*/*'})
                with urllib.request.urlopen(req, timeout=self.timeout, context=self._ctx) as resp:
                    return resp.read()
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None
                last = e
                if e.code not in (408, 429, 500, 502, 503, 504):
                    break
            except ssl.SSLError as e:
                raise RuntimeError(u"Erro SSL ao acessar %s: %s" % (BASE_URL, e))
            except Exception as e:  # URLError, timeout
                last = e
            if attempt < self.retries:
                time.sleep(min(10.0, 0.5 * 2 ** attempt + random.random()))
        raise RuntimeError(u"Falha ao acessar o Google Earth (%s): %s" % (url.split('?')[0], last))

    # ---- decifracao (XOR com a chave do dbRoot)
    def _keystream(self, n):
        with self._ks_lock:
            if len(self._ks) < n:
                import numpy as np
                key, klen = self.key, len(self.key)
                size = max(n, 2 * len(self._ks), 1 << 16)
                idx = np.empty(size, dtype=np.int64)
                off = 16
                for j in range(size):
                    idx[j] = off
                    off += 1
                    if not off & 7:
                        off += 16
                    if off >= klen:
                        off = (off + 8) % 24
                self._ks = np.frombuffer(key, dtype=np.uint8)[idx].tobytes()
            return self._ks

    def decrypt(self, data):
        import numpy as np
        ks = self._keystream(len(data))
        return (np.frombuffer(data, dtype=np.uint8) ^ np.frombuffer(ks, dtype=np.uint8, count=len(data))).tobytes()

    def _decrypt_packet(self, data):
        return zlib.decompress(self.decrypt(data)[8:])

    def _init_dbroot(self):
        raw = self._fetch(BASE_URL + '/dbRoot.v5?db=tm&hl=en&gl=us&output=proto')
        if not raw:
            raise RuntimeError(u"O Google Earth não respondeu ao dbRoot do catálogo histórico.")
        enc = body = None
        for f, w, v in iter_fields(raw):
            if w == 2 and f == 2:
                enc = v
            elif w == 2 and f == 3:
                body = v
        if not enc or not body:
            raise RuntimeError(u"Resposta inesperada do dbRoot do Google Earth (sem chave).")
        self.key = bytes(enc)
        for f, w, v in iter_fields(self._decrypt_packet(body)):
            if w == 2 and f == 13:
                for sf, sw, sv in iter_fields(v):
                    if sw == 0 and sf == 1:
                        self.quadtree_version = sv
        self.quadtree_version = self.quadtree_version or FALLBACK_QUADTREE_VERSION

    # ---- quadtree
    def packet(self, path, epoch):
        key = (path, epoch)
        if key in self._packets:
            return self._packets[key]
        with self._meta_lock:
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:   # uma unica busca por pacote, mesmo com varias threads
            if key in self._packets:
                return self._packets[key]
            # O pacote raiz nunca vai para o disco: e uma unica requisicao e e ele que muda
            # quando o Google atualiza o catalogo. Os demais sao imutaveis por epoca.
            cache = None
            if self.cache_dir and path != '0':
                cache = os.path.join(self.cache_dir, "qp_%s_%s.bin" % (path, epoch))
            nodes = None
            if cache and os.path.exists(cache):
                try:
                    with open(cache, 'rb') as f:
                        nodes = parse_packet(f.read()) or None
                except Exception:
                    nodes = None   # cache corrompido: busca de novo
            if nodes is None:
                raw = self._fetch(BASE_URL + '/flatfile?db=tm&qp-%s-q.%s' % (path, epoch))
                if raw:
                    data = self._decrypt_packet(raw)
                    nodes = parse_packet(data)
                    if cache and nodes:
                        tmp = cache + '.%d.part' % threading.get_ident()
                        with open(tmp, 'wb') as f:
                            f.write(data)
                        os.replace(tmp, cache)
            self._packets[key] = nodes
            return nodes

    def node(self, path):
        current = self.packet('0', self.quadtree_version)
        for end in range(SUBINDEX_MAX_SZ, len(path), SUBINDEX_MAX_SZ):
            if not current:
                return None
            step = path[:end]
            nd = current.get(quadtree_subindex(step))
            if not nd or not nd['cache_node_epoch']:
                return None
            current = self.packet(step, nd['cache_node_epoch'])
        return current.get(quadtree_subindex(path)) if current else None

    def dated_layers(self, path):
        nd = self.node(path)
        return parse_dated_layers(nd) if nd else []

    def tile_jpeg(self, path, epoch, date_int):
        raw = self._fetch(BASE_URL + '/flatfile?db=tm&f1-%s-i.%s-%x' % (path, epoch, date_int))
        if not raw:
            return None
        data = self.decrypt(raw)
        return data if data[:3] == b'\xff\xd8\xff' else None


# ------------------------------------------------------------------------------ operacoes
def _check_tiles(bbox, level):
    est = tilemath.keyhole_estimate(bbox, level)
    if est['tiles'] > MAX_TILES:
        raise ValueError(u"A área exige %d tiles no zoom %d (limite %d). Reduza o zoom ou a área."
                         % (est['tiles'], level, MAX_TILES))
    return est


def _tiles(win, level):
    for r in range(win['r1'], win['r0'] - 1, -1):          # norte -> sul
        for c in range(win['c0'], win['c1'] + 1):
            yield r, c, tilemath.keyhole_quadtree_path(r, c, level)


def _sample_tiles(win, level, limit):
    """Amostra regular da grade (estimativa de cobertura) com no maximo ~limit tiles."""
    rows = win['r1'] - win['r0'] + 1
    cols = win['c1'] - win['c0'] + 1
    stride = max(1, int(math.ceil(math.sqrt(rows * cols / float(limit)))))
    # passo por eixo limitado ao tamanho do eixo: numa faixa estreita (ex.: 2 x 8000 tiles) o inicio
    # r1 - stride//2 caia fora da grade e a amostra ficava vazia
    sr, sc = min(stride, rows), min(stride, cols)
    if sr < stride:            # eixo curto: compensa no outro para manter ~limit tiles
        sc = max(1, int(math.ceil(rows * cols / float(limit) / sr)))
    elif sc < stride:
        sr = max(1, int(math.ceil(rows * cols / float(limit) / sc)))
    for r in range(win['r1'] - min(sr // 2, rows - 1), win['r0'] - 1, -sr):
        for c in range(win['c0'] + min(sc // 2, cols - 1), win['c1'] + 1, sc):
            yield r, c, tilemath.keyhole_quadtree_path(r, c, level)


def _plan(bbox, level):
    """(tiles a consultar, quantidade, estimado?) para um zoom."""
    win = tilemath.keyhole_crop_window(bbox, level)
    total = (win['r1'] - win['r0'] + 1) * (win['c1'] - win['c0'] + 1)
    limit = Z20_SAMPLE_TILES if level >= 20 else FULL_SCAN_TILES
    if total <= limit:
        return list(_tiles(win, level)), False
    sample = list(_sample_tiles(win, level, Z20_SAMPLE_TILES if level >= 20 else SAMPLE_TILES))
    return sample, True


def list_dates_multi(bbox, zooms, client=None, workers=None):
    """Datas de cada zoom: [{'date', 'zoom', 'coverage_pct', 'estimated', 'providers', ...}],
    da data mais recente para a mais antiga e, na mesma data, do maior zoom para o menor."""
    bbox = tilemath.clamp_bbox(bbox)
    plans = [(int(z),) + _plan(bbox, int(z)) for z in zooms]
    client = client or KeyholeClient()
    total = sum(len(t) for _, t, _ in plans)
    _log(u"Google Earth histórico: consultando datas nos zooms %s (%d tiles)"
         % (u', '.join(str(z) for z, _, _ in plans), total))
    jobs = [(z, p) for z, tiles, _ in plans for _, _, p in tiles]
    coverage = {}
    failed = {}
    done = 0

    def _scan(job):
        try:
            return job[0], client.dated_layers(job[1])
        except Exception:      # falha de rede num pacote: conta e segue (nao anula a busca toda)
            return job[0], None

    for z, layers in parallel.imap_bounded(_scan, jobs, parallel.clamp_workers(workers)):
        done += 1
        if layers is None:
            failed[z] = failed.get(z, 0) + 1
            continue
        for d in dict((d['date'], d) for d in layers).values():
            info = coverage.setdefault((d['date'], z), {'count': 0, 'providers': set()})
            info['count'] += 1
            info['providers'].add(d['provider'])
        if done % 100 == 0 or done == total:
            _log(u"PROGRESS %d/%d tiles" % (done, total))
    if jobs and sum(failed.values()) == len(jobs):
        raise RuntimeError(u"Nenhum tile do catálogo histórico respondeu (%d falhas de rede)." % len(jobs))
    if failed:
        _log(u"Aviso: %d tile(s) sem resposta do catálogo; a cobertura desses zooms é estimada." % sum(failed.values()))
    # tiles sem resposta saem do denominador e a cobertura do zoom passa a ser estimada
    sizes = dict((z, (len(t) - failed.get(z, 0), est or bool(failed.get(z)))) for z, t, est in plans)
    out = []
    for (date, z) in sorted(coverage, key=lambda k: (k[0], k[1]), reverse=True):
        info = coverage[(date, z)]
        n, est = sizes[z]
        n = max(1, n)
        providers = sorted(info['providers'])
        out.append({'date': date, 'zoom': z, 'coverage_tiles': info['count'], 'total_tiles': n,
                    'coverage_pct': round(100.0 * info['count'] / n, 1), 'estimated': est,
                    'providers': providers, 'provider': u', '.join(providers)})
    return out


def list_dates(bbox, zoom, client=None, workers=None):
    """Datas de um zoom (mais recente primeiro), com provedores e cobertura em tiles."""
    _check_tiles(tilemath.clamp_bbox(bbox), int(zoom))
    return list_dates_multi(bbox, [int(zoom)], client=client, workers=workers)


def summarize(dates):
    if not dates:
        return u"nenhuma data encontrada"
    return u"%s (%s)" % (dates[0]['date'], dates[0].get('provider') or u'?')


def download(bbox, zoom, date, out_tif, compression='JPEG', target_crs=None, workers=None,
             client=None, engine=None, progress=None, overviews=True):
    """Baixa so os tiles da data e grava o GeoTIFF recortado ao BBOX.

    target_crs None ou 'EPSG:4326' = grade nativa (sem reamostragem); outro valor reprojeta via GDAL.
    """
    import xyz_core
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', date or ''):
        raise ValueError(u"Data inválida: %r (use AAAA-MM-DD)." % (date,))
    bbox = tilemath.clamp_bbox(bbox)
    level = int(zoom)
    est = _check_tiles(bbox, level)
    win = tilemath.keyhole_crop_window(bbox, level)
    if target_crs and target_crs.upper() == 'EPSG:4326':
        target_crs = None
    client = client or KeyholeClient()
    total = est['tiles']
    start = time.time()
    _log(u"Google Earth histórico %s z%d: %d tiles (%dx%d)" % (date, level, total, est['cols'], est['rows']))

    tile = tilemath.TILE_SIZE
    catalog_dates = set()

    def _job(item):
        # roda nas threads: rede, decifracao e decodificacao do JPEG (a thread principal so grava)
        r, c, path = item
        try:
            match = [d for d in client.dated_layers(path) if d['date'] == date]
            if not match:
                return r, c, None, None, None
            catalog_dates.add(match[0]['catalog_date'])
            jpg = client.tile_jpeg(path, match[0]['epoch'], match[0]['date_int'])
            return r, c, (xyz_core._decode_tile_rgb(jpg, tile) if jpg else None), match[0]['provider'], None
        except Exception:  # falha de rede apos as retentativas: o tile vai para a 2a rodada
            return r, c, None, None, item

    builder = xyz_core.GeoTiffBuilder(out_tif, win['width'], win['height'], win['left'], win['top'], win['res'],
                                      4326, compression=compression, engine=engine)
    covered_px = 0
    providers = set()
    done = got = 0
    try:
        workers = parallel.clamp_workers(workers)
        _log(u"%d threads de download" % workers)
        failed = []

        def _paste(results, count_progress=True):
            nonlocal done, got, covered_px
            for r, c, arr, prov, fail in results:
                if count_progress:
                    done += 1
                if fail is not None:
                    failed.append(fail)
                elif arr is not None:
                    xoff = (c - win['c0']) * tile - win['px0']
                    yoff = (win['r1'] - r) * tile - win['py0']
                    builder.paste(arr, xoff, yoff)
                    w = min(xoff + tile, win['width']) - max(xoff, 0)
                    h = min(yoff + tile, win['height']) - max(yoff, 0)
                    covered_px += max(0, w) * max(0, h)
                    providers.add(prov)
                    got += 1
                if count_progress and progress:
                    progress(done, total)
                if count_progress and (done % 10 == 0 or done == total):
                    _log(u"PROGRESS %d/%d tiles" % (done, total))

        _paste(parallel.imap_bounded(_job, _tiles(win, level), workers))
        if failed:
            # 2a rodada com poucas threads (as falhas costumam ser limite do servidor)
            retry, failed[:] = list(failed), []
            _log(u"Repetindo %d tile(s) que falharam..." % len(retry))
            _paste(parallel.imap_bounded(_job, retry, min(4, workers)), count_progress=False)
        if failed:
            _log(u"Aviso: %d tile(s) não puderam ser baixados; ficam pretos na imagem." % len(failed))
        if not got:
            raise RuntimeError(u"Nenhum tile do Google Earth com a data %s nesta área e zoom." % date)
        if target_crs:
            _log(u"Reprojetando para %s..." % target_crs)
        final = builder.finish(target_crs)
    except BaseException:
        builder.abort()
        raise
    if overviews:
        xyz_core.build_overviews(final)
    return {
        'file': final, 'provider': 'google-historical', 'date': date, 'zoom': level,
        'tiles': total, 'tiles_with_date': got, 'width': win['width'], 'height': win['height'],
        'res_deg': win['res'], 'ground_res_m': est['ground_res_m'], 'crs': target_crs or 'EPSG:4326',
        'coverage_pct': round(100.0 * covered_px / float(win['width'] * win['height']), 1),
        'providers': sorted(providers), 'attribution': ATTRIBUTION,
        'catalog_date': u', '.join(sorted(catalog_dates)),
        'failed_tiles': len(failed),
        'seconds': round(time.time() - start, 1),
    }


def thumbnail(bbox, zoom, date, out_png, client=None, span=3):
    """Previa da data: ate span x span tiles no centro da area, no MESMO zoom da busca (o catalogo
    muda por nivel: a data pode nao existir em zooms menores). Grava PNG e GIF (Tk 8.5)."""
    from PIL import Image
    import io
    bbox = tilemath.clamp_bbox(bbox)
    level = int(zoom)
    win = tilemath.keyhole_crop_window(bbox, level)
    rc, cc = tilemath.keyhole_row_col((bbox[1] + bbox[3]) / 2.0, (bbox[0] + bbox[2]) / 2.0, level)
    half = span // 2
    rows = [r for r in range(rc + half, rc - half - 1, -1) if win['r0'] <= r <= win['r1']]
    cols = [c for c in range(cc - half, cc + half + 1) if win['c0'] <= c <= win['c1']]
    client = client or KeyholeClient()
    tile = tilemath.TILE_SIZE
    canvas = Image.new('RGB', (len(cols) * tile, len(rows) * tile), (0, 0, 0))
    got = 0
    for i, r in enumerate(rows):
        for j, c in enumerate(cols):
            path = tilemath.keyhole_quadtree_path(r, c, level)
            match = [d for d in client.dated_layers(path) if d['date'] == date]
            jpg = client.tile_jpeg(path, match[0]['epoch'], match[0]['date_int']) if match else None
            if jpg:
                with Image.open(io.BytesIO(jpg)) as im:
                    canvas.paste(im.convert('RGB'), (j * tile, i * tile))
                got += 1
    if not got:
        raise RuntimeError(u"Sem imagem de %s no centro da área para a miniatura." % date)
    os.makedirs(os.path.dirname(os.path.abspath(out_png)), exist_ok=True)
    canvas.save(out_png, 'PNG')
    gif = os.path.splitext(out_png)[0] + '.gif'
    canvas.save(gif, 'GIF')
    return {'file': out_png, 'gif': gif, 'tiles': got}


def write_tags(tif, date, providers, coverage_pct, catalog_date=None):
    """Data e provedor nas tags padrao que ArcGIS/QGIS exibem (as mesmas da fonte Esri)."""
    from osgeo import gdal
    ascii_ = lambda s: (s or u'').encode('ascii', 'replace').decode('ascii')
    ds = gdal.Open(tif, gdal.GA_Update)
    try:
        ds.SetMetadataItem('TIFFTAG_DATETIME', date.replace('-', ':') + ' 00:00:00')
        ds.SetMetadataItem('ACQUISITION_DATE', date)
        ds.SetMetadataItem('IMAGE_PROVIDER', ascii_(providers or u'Google Earth'))
        ds.SetMetadataItem('ARCMAGERY_SOURCE', 'google-historical')
        ds.SetMetadataItem('ARCMAGERY_COVERAGE_PCT', '%.1f' % coverage_pct)
        ds.SetMetadataItem('ARCMAGERY_DATE_CONVENTION', 'Google Earth Pro (catalogo UTC - 1 dia)')
        if catalog_date:
            ds.SetMetadataItem('ARCMAGERY_CATALOG_DATE_UTC', catalog_date)
    finally:
        ds = None
