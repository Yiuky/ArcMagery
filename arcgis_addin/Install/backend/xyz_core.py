# -*- coding: utf-8 -*-
"""
Download de mosaicos XYZ georreferenciados (Google Earth/Satelite, Esri, Bing) - Python 3.

Fluxo: BBOX WGS84 -> grade de tiles -> download paralelo com retentativas (e cache em disco
para retomada) -> escrita incremental em GeoTIFF EPSG:3857 recortado exatamente ao BBOX.

Motores de escrita (em ordem de preferencia):
  1. GDAL (osgeo): escrita tile a tile direto no GeoTIFF (baixo uso de memoria, BigTIFF).
  2. Pillow: monta o mosaico em memoria e grava tags GeoTIFF + .tfw/.prj.

ATENCAO (Termos de Uso): o download em massa de tiles do Google/Bing fora das APIs oficiais
viola os Termos de Servico desses provedores. A Esri World Imagery exige atribuicao.
O usuario e responsavel pelo uso; a GUI exibe este aviso antes do download.
"""
import io
import os
import random
import shutil
import ssl
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qgis_env  # noqa: E402,F401  (DLLs do GDAL do QGIS antes do import do osgeo)
import tilemath  # noqa: E402

try:
    from osgeo import gdal, osr
    gdal.UseExceptions()
    HAS_GDAL = True
    GDAL_IMPORT_ERROR = None
except Exception as _e:  # pragma: no cover - depende do ambiente
    gdal = osr = None
    HAS_GDAL = False
    GDAL_IMPORT_ERROR = repr(_e)

try:
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    HAS_PIL = True
except Exception:  # pragma: no cover
    Image = None
    HAS_PIL = False

try:
    import numpy as np
    NUMPY_IMPORT_ERROR = None
except Exception as _e:  # pragma: no cover
    np = None
    NUMPY_IMPORT_ERROR = repr(_e)


PROVIDERS = {
    'google': {
        'label': u'Google Earth / Satélite',
        'url': 'https://mt{s}.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
        'subdomains': ['0', '1', '2', '3'], 'max_zoom': 21,
        'attribution': u'Imagens © Google', 'tos_warning': True,
    },
    'google-hybrid': {
        'label': u'Google Híbrido (satélite + rótulos)',
        'url': 'https://mt{s}.google.com/vt/lyrs=y&x={x}&y={y}&z={z}',
        'subdomains': ['0', '1', '2', '3'], 'max_zoom': 21,
        'attribution': u'Imagens © Google', 'tos_warning': True,
    },
    'esri': {
        'label': u'Esri World Imagery',
        'url': 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        'subdomains': [], 'max_zoom': 19,
        'attribution': u'Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community',
        'tos_warning': False,
    },
    'esri-clarity': {
        'label': u'Esri World Imagery (Clarity)',
        'url': 'https://clarity.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        'subdomains': [], 'max_zoom': 19,
        'attribution': u'Source: Esri, Maxar, Earthstar Geographics', 'tos_warning': False,
    },
    'bing': {
        'label': u'Bing Aerial',
        'url': 'https://ecn.t{s}.tiles.virtualearth.net/tiles/a{q}.jpeg?g=1',
        'subdomains': ['0', '1', '2', '3'], 'max_zoom': 19,
        'attribution': u'© Microsoft', 'tos_warning': True,
    },
}

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0 Safari/537.36 ArcMagery/2.0")

DEFAULT_MAX_TILES = 20000
RETRYABLE_HTTP = (408, 425, 429, 500, 502, 503, 504)


class TileDownloadError(RuntimeError):
    pass


def _log(msg):
    sys.stderr.write("[ArcGEE] " + msg + "\n")
    sys.stderr.flush()


def get_provider(key_or_url):
    """Provedor do catalogo ou template de URL customizado ({z}/{x}/{y}, {s}, {q})."""
    if key_or_url in PROVIDERS:
        return dict(PROVIDERS[key_or_url], key=key_or_url)
    if key_or_url and ('{z}' in key_or_url or '{q}' in key_or_url):
        return {'key': 'custom', 'label': u'URL personalizada', 'url': key_or_url,
                'subdomains': ['a', 'b', 'c'] if '{s}' in key_or_url else [],
                'max_zoom': 22, 'attribution': u'', 'tos_warning': False}
    raise ValueError(u"Provedor desconhecido: %r. Use um de %s ou um template de URL com {z}/{x}/{y}."
                     % (key_or_url, sorted(PROVIDERS)))


def tile_url(provider, x, y, z):
    subs = provider.get('subdomains') or []
    s = subs[(x + y) % len(subs)] if subs else ''
    return provider['url'].format(x=x, y=y, z=z, s=s, q=tilemath.quadkey(x, y, z))


def _ssl_context():
    # No Windows o create_default_context carrega o repositorio de certificados do sistema,
    # que inclui a CA de proxies corporativos com inspecao SSL.
    return ssl.create_default_context()


def _looks_like_image(data):
    return data[:3] == b'\xff\xd8\xff' or data[:8] == b'\x89PNG\r\n\x1a\n' or \
        data[:4] == b'RIFF' or data[:4] == b'GIF8'


def no_tiles_message(prov, zoom, reasons, sample_urls):
    """Mensagem quando NENHUM tile veio: diz o que o servidor respondeu e o que tentar."""
    msg = u"O provedor não retornou nenhum tile para esta área/zoom"
    if reasons:
        msg += u" (respostas: %s)" % u", ".join(u"%s × %d" % (k, v) for k, v in
                                                sorted(reasons.items(), key=lambda kv: -kv[1]))
    msg += u"."
    if sample_urls:
        msg += u"\nExemplo de tile pedido: %s" % sample_urls[0]
    host = urllib.parse.urlsplit(prov.get('url', '')).netloc
    if host:
        msg += (u"\nSe o mesmo endereço abre no navegador, a área não tem imagem nesta fonte; "
                u"se não abre, a rede pode estar bloqueando %s." % host)
    if prov.get('key') == 'esri-clarity':
        msg += u"\nAlternativa: use 'Esri World Imagery', que tem data de captura e histórico Wayback."
    elif zoom >= 18:
        msg += u"\nTente um zoom menor."
    return msg


def fetch_tile(url, retries=4, timeout=30.0, headers=None, _sleep=time.sleep, on_empty=None):
    """Baixa um tile. Retorna bytes da imagem, ou None se o provedor nao tem o tile (404/204).
    on_empty(motivo) informa POR QUE veio vazio ('HTTP 404', 'HTTP 204', 'resposta vazia'),
    para diagnosticar quando TODOS os tiles vem vazios (ex.: dominio bloqueado pela rede).
    Levanta TileDownloadError apos esgotar as retentativas."""
    def _empty(reason):
        if on_empty:
            on_empty(reason)
        return None

    hdrs = {'User-Agent': USER_AGENT, 'Accept': 'image/avif,image/webp,image/png,image/jpeg,image/*;q=0.8'}
    if headers:
        hdrs.update(headers)
    ctx = _ssl_context()
    last_err = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                if resp.status == 204:
                    return _empty('HTTP 204')
                data = resp.read()
            if not data:
                return _empty('resposta vazia (HTTP %s)' % resp.status)
            if not _looks_like_image(data):
                raise ValueError("resposta nao e imagem (%d bytes)" % len(data))
            return data
        except urllib.error.HTTPError as e:
            if e.code in (404, 204):
                return _empty('HTTP %d' % e.code)
            if e.code not in RETRYABLE_HTTP:
                raise TileDownloadError("HTTP %d em %s" % (e.code, url))
            last_err = e
            retry_after = e.headers.get('Retry-After') if e.headers else None
            if retry_after and str(retry_after).isdigit():
                _sleep(min(60, int(retry_after)))
                continue
        except ssl.SSLError as e:
            # certificado invalido nao se resolve com retentativa
            raise TileDownloadError("Erro SSL em %s: %s" % (url, e))
        except Exception as e:  # URLError, timeout, conteudo invalido
            last_err = e
        if attempt < retries:
            _sleep(min(20.0, 0.5 * (2 ** attempt) + random.random()))
    raise TileDownloadError("Falha apos %d tentativas: %s (%s)" % (retries, url, last_err))


# ----------------------------------------------------------------------------- decodificacao
def _decode_tile_rgb(data, tile_size):
    """Decodifica um tile em array numpy (3, tile_size, tile_size) uint8."""
    if HAS_PIL:
        with Image.open(io.BytesIO(data)) as im:
            im = im.convert('RGB')
            if im.size != (tile_size, tile_size):
                im = im.resize((tile_size, tile_size), Image.BILINEAR)
            return np.asarray(im, dtype=np.uint8).transpose(2, 0, 1)
    # Fallback GDAL (/vsimem)
    name = '/vsimem/arcmagery_tile_%d' % threading.get_ident()
    gdal.FileFromMemBuffer(name, data)
    try:
        ds = gdal.Open(name)
        if ds.RasterCount == 1 and ds.GetRasterBand(1).GetColorTable() is not None:
            ds = gdal.Translate(name + '_rgb.tif', ds, rgbExpand='rgb')
        arr = ds.ReadAsArray()
        if arr.ndim == 2:
            arr = np.stack([arr] * 3)
        arr = arr[:3].astype(np.uint8)
        if arr.shape[1:] != (tile_size, tile_size):
            raise ValueError("tile com tamanho inesperado %r" % (arr.shape,))
        return arr
    finally:
        gdal.Unlink(name)
        try:
            gdal.Unlink(name + '_rgb.tif')
        except Exception:
            pass


def detect_tile_size(data):
    if HAS_PIL:
        with Image.open(io.BytesIO(data)) as im:
            return im.size[0]
    name = '/vsimem/arcmagery_probe'
    gdal.FileFromMemBuffer(name, data)
    try:
        return gdal.Open(name).RasterXSize
    finally:
        gdal.Unlink(name)


# --------------------------------------------------------------------------------- escrita
WKT_3857_ESRI = (
    'PROJCS["WGS_1984_Web_Mercator_Auxiliary_Sphere",GEOGCS["GCS_WGS_1984",'
    'DATUM["D_WGS_1984",SPHEROID["WGS_1984",6378137.0,298.257223563]],'
    'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]],'
    'PROJECTION["Mercator_Auxiliary_Sphere"],PARAMETER["False_Easting",0.0],'
    'PARAMETER["False_Northing",0.0],PARAMETER["Central_Meridian",0.0],'
    'PARAMETER["Standard_Parallel_1",0.0],PARAMETER["Auxiliary_Sphere_Type",0.0],'
    'UNIT["Meter",1.0]]'
)


class _GdalWriter(object):
    def __init__(self, path, width, height, left, top, res, compression):
        opts = ['TILED=YES', 'BIGTIFF=IF_SAFER']
        if compression == 'JPEG':
            opts += ['COMPRESS=JPEG', 'JPEG_QUALITY=90', 'PHOTOMETRIC=YCBCR']
        elif compression in ('LZW', 'DEFLATE'):
            opts += ['COMPRESS=%s' % compression]
        self.ds = gdal.GetDriverByName('GTiff').Create(path, width, height, 3, gdal.GDT_Byte, options=opts)
        self.ds.SetGeoTransform((left, res, 0.0, top, 0.0, -res))
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(3857)
        self.ds.SetProjection(srs.ExportToWkt())
        for i, ci in enumerate((gdal.GCI_RedBand, gdal.GCI_GreenBand, gdal.GCI_BlueBand)):
            self.ds.GetRasterBand(i + 1).SetColorInterpretation(ci)
        self.width, self.height = width, height

    def paste(self, arr, xoff, yoff):
        ts_h, ts_w = arr.shape[1], arr.shape[2]
        sx0, sy0 = max(0, -xoff), max(0, -yoff)
        dx0, dy0 = max(0, xoff), max(0, yoff)
        w = min(ts_w - sx0, self.width - dx0)
        h = min(ts_h - sy0, self.height - dy0)
        if w <= 0 or h <= 0:
            return
        sub = np.ascontiguousarray(arr[:, sy0:sy0 + h, sx0:sx0 + w])
        self.ds.WriteRaster(dx0, dy0, w, h, sub.tobytes(), w, h, gdal.GDT_Byte, [1, 2, 3])

    def close(self):
        self.ds.FlushCache()
        self.ds = None

    def abort(self):
        self.ds = None


class _PilWriter(object):
    def __init__(self, path, width, height, left, top, res, compression):
        if width * height * 3 > 3.8 * 1024 ** 3:
            raise ValueError(u"Mosaico excede 4 GB sem GDAL disponível. Reduza a área/zoom ou instale o GDAL.")
        self.path, self.left, self.top, self.res = path, left, top, res
        self.compression = {'JPEG': 'jpeg', 'LZW': 'tiff_lzw', 'DEFLATE': 'tiff_deflate'}.get(compression)
        self.canvas = Image.new('RGB', (width, height), (0, 0, 0))

    def paste(self, arr, xoff, yoff):
        self.canvas.paste(Image.fromarray(np.ascontiguousarray(arr.transpose(1, 2, 0))), (xoff, yoff))

    def close(self):
        from PIL import TiffImagePlugin, TiffTags
        ifd = TiffImagePlugin.ImageFileDirectory_v2()
        ifd[33550] = (float(self.res), float(self.res), 0.0)                       # ModelPixelScale
        ifd.tagtype[33550] = TiffTags.DOUBLE
        ifd[33922] = (0.0, 0.0, 0.0, float(self.left), float(self.top), 0.0)      # ModelTiepoint
        ifd.tagtype[33922] = TiffTags.DOUBLE
        ifd[34735] = (1, 1, 0, 3, 1024, 0, 1, 1, 1025, 0, 1, 1, 3072, 0, 1, 3857)  # GeoKeyDirectory
        ifd.tagtype[34735] = TiffTags.SHORT
        kwargs = {'tiffinfo': ifd}
        if self.compression:
            kwargs['compression'] = self.compression
        if self.compression == 'jpeg':
            kwargs['quality'] = 90
        self.canvas.save(self.path, format='TIFF', **kwargs)
        self.canvas = None
        write_world_file(self.path, self.left, self.top, self.res)

    def abort(self):
        self.canvas = None


def write_world_file(tif_path, left, top, res):
    """.tfw (coordenadas do CENTRO do pixel superior esquerdo) + .prj ESRI."""
    base = os.path.splitext(tif_path)[0]
    with open(base + '.tfw', 'w') as f:
        f.write("%.10f\n0.0\n0.0\n%.10f\n%.10f\n%.10f\n" % (res, -res, left + res / 2.0, top - res / 2.0))
    with open(base + '.prj', 'w') as f:
        f.write(WKT_3857_ESRI)


# ------------------------------------------------------------------------------ orquestracao
def download_mosaic(bbox, zoom, provider='esri', out_tif=None, workers=8, retries=4, timeout=30.0,
                    max_tiles=DEFAULT_MAX_TILES, compression='JPEG', target_crs=None,
                    cache_dir=None, keep_cache=False, allow_missing=True, engine=None,
                    progress=None, headers=None):
    """Baixa e monta o mosaico. Retorna dict com caminho, dimensoes, resolucao e estatisticas.

    engine: None (automatico), 'gdal' ou 'pil' (usado nos testes).
    target_crs: None mantem EPSG:3857 nativo (sem reamostragem); ex. 'EPSG:4674' reprojeta via GDAL.
    """
    prov = get_provider(provider)
    zoom = int(zoom)
    if zoom < 0 or zoom > 23:
        raise ValueError(u"Zoom fora do intervalo 0-23: %d" % zoom)
    bbox = tilemath.clamp_bbox(bbox)
    est = tilemath.estimate(bbox, zoom)
    if est['tiles'] > max_tiles:
        raise ValueError(u"A área exige %d tiles no zoom %d (limite %d). Reduza o zoom ou a área."
                         % (est['tiles'], zoom, max_tiles))
    if engine is None:
        engine = 'gdal' if (HAS_GDAL and np is not None) else 'pil'
    if engine == 'gdal' and not (HAS_GDAL and np is not None):
        raise RuntimeError(u"GDAL/numpy indisponível neste Python.")
    if engine == 'pil' and not (HAS_PIL and np is not None):
        raise RuntimeError(u"Pillow/numpy indisponível neste Python (%s): instale 'Pillow' e 'numpy' ou use o Python do QGIS. "
                           u"[GDAL: %s | numpy: %s]" % (sys.executable, GDAL_IMPORT_ERROR, NUMPY_IMPORT_ERROR))
    if target_crs and not HAS_GDAL:
        raise RuntimeError(u"Reprojeção requer GDAL.")

    if not out_tif:
        out_tif = os.path.join(tempfile.gettempdir(), "arcmagery_%s_z%d_%d.tif" % (prov['key'], zoom, int(time.time())))
    out_tif = os.path.abspath(out_tif)
    os.makedirs(os.path.dirname(out_tif), exist_ok=True)
    cache_dir = cache_dir or (os.path.splitext(out_tif)[0] + "_tiles")
    os.makedirs(cache_dir, exist_ok=True)

    x0, x1, y0, y1 = tilemath.tile_range(bbox, zoom)
    tiles = [(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]
    total = len(tiles)
    _log(u"XYZ %s z%d: %d tiles (%dx%d) ~%.2f m/px" % (prov['key'], zoom, total, est['cols'], est['rows'], est['ground_res_m']))

    empty_reasons = {}
    empty_sample = []

    def _note_empty(reason, url):
        empty_reasons[reason] = empty_reasons.get(reason, 0) + 1
        if not empty_sample:
            empty_sample.append(url)

    def _cache_path(x, y):
        return os.path.join(cache_dir, "%d_%d_%d.img" % (zoom, x, y))

    def _job(xy):
        x, y = xy
        cp = _cache_path(x, y)
        if os.path.exists(cp):
            with open(cp, 'rb') as f:
                return xy, (f.read() or None)
        url = tile_url(prov, x, y, zoom)
        data = fetch_tile(url, retries=retries, timeout=timeout, headers=headers,
                          on_empty=lambda reason: _note_empty(reason, url))
        tmp = cp + '.part'
        with open(tmp, 'wb') as f:
            f.write(data or b'')
        os.replace(tmp, cp)
        return xy, data

    writer = None
    tile_size = None
    win = None
    missing, failures, done = 0, [], 0
    tmp_out = out_tif + '.part.tif'
    start = time.time()
    try:
        with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
            futures = [pool.submit(_job, t) for t in tiles]
            for fut in as_completed(futures):
                done += 1
                try:
                    (x, y), data = fut.result()
                except Exception as e:
                    failures.append(str(e))
                    data = None
                    x = y = None
                if data is None and x is not None:
                    missing += 1
                if data is not None:
                    if writer is None:
                        tile_size = detect_tile_size(data)
                        win = tilemath.crop_window(bbox, zoom, tile_size)
                        cls = _GdalWriter if engine == 'gdal' else _PilWriter
                        writer = cls(tmp_out, win['width'], win['height'], win['left'], win['top'], win['res'], compression)
                    writer.paste(_decode_tile_rgb(data, tile_size),
                                 (x - win['x0']) * tile_size - win['px0'], (y - win['y0']) * tile_size - win['py0'])
                if progress:
                    progress(done, total)
                if done % 10 == 0 or done == total:
                    _log(u"PROGRESS %d/%d tiles" % (done, total))

        if failures:
            raise TileDownloadError(u"%d tiles falharam (o cache foi mantido para retomar): %s"
                                    % (len(failures), failures[0]))
        if writer is None:
            shutil.rmtree(cache_dir, ignore_errors=True)   # so tiles vazios: nada a retomar
            raise TileDownloadError(no_tiles_message(prov, zoom, empty_reasons, empty_sample))
        if missing and not allow_missing:
            raise TileDownloadError(u"%d tiles inexistentes no provedor para este zoom." % missing)
        writer.close()
        writer = None

        final_path = out_tif
        if target_crs:
            _log(u"Reprojetando para %s..." % target_crs)
            gdal.Warp(out_tif, tmp_out, dstSRS=target_crs, resampleAlg='bilinear',
                      creationOptions=['TILED=YES', 'COMPRESS=LZW', 'BIGTIFF=IF_SAFER'])
            os.remove(tmp_out)
        else:
            if os.path.exists(out_tif):
                os.remove(out_tif)
            os.replace(tmp_out, out_tif)
            for ext in ('.tfw', '.prj'):
                side = os.path.splitext(tmp_out)[0] + ext
                if os.path.exists(side):
                    os.replace(side, os.path.splitext(out_tif)[0] + ext)

        if not keep_cache:
            shutil.rmtree(cache_dir, ignore_errors=True)
        return {
            'file': final_path, 'provider': prov['key'], 'zoom': zoom, 'tiles': total,
            'missing_tiles': missing, 'width': win['width'], 'height': win['height'],
            'res_mercator_m': win['res'], 'ground_res_m': est['ground_res_m'],
            'crs': target_crs or 'EPSG:3857', 'engine': engine,
            'attribution': prov.get('attribution', u''), 'seconds': round(time.time() - start, 1),
        }
    except BaseException:
        # Falha: descarta o arquivo parcial, mas MANTEM o cache de tiles para retomada
        if writer is not None:
            writer.abort()
        for side in (tmp_out, os.path.splitext(tmp_out)[0] + '.tfw', os.path.splitext(tmp_out)[0] + '.prj'):
            try:
                if os.path.exists(side):
                    os.remove(side)
            except OSError:
                pass
        raise
