# -*- coding: utf-8 -*-
"""
Matematica de tiles XYZ / Web Mercator (EPSG:3857) - Python 2.7 e 3.x, sem dependencias.

Usado pelo backend (download de mosaicos) e pela GUI no ArcMap (estimativa instantanea
de tiles, resolucao e tamanho antes de iniciar o download).
"""
from __future__ import division

import math

EARTH_RADIUS = 6378137.0
ORIGIN_SHIFT = math.pi * EARTH_RADIUS          # 20037508.342789244
MAX_LAT = 85.0511287798066                     # limite de latitude do Web Mercator
TILE_SIZE = 256


def clamp_bbox(bbox):
    """Normaliza [min_lon, min_lat, max_lon, max_lat] (ordem e limites do Web Mercator)."""
    x0, y0, x1, y1 = [float(v) for v in bbox]
    min_lon, max_lon = min(x0, x1), max(x0, x1)
    min_lat, max_lat = min(y0, y1), max(y0, y1)
    min_lon = max(-180.0, min(180.0, min_lon))
    max_lon = max(-180.0, min(180.0, max_lon))
    min_lat = max(-MAX_LAT, min(MAX_LAT, min_lat))
    max_lat = max(-MAX_LAT, min(MAX_LAT, max_lat))
    if max_lon - min_lon <= 0 or max_lat - min_lat <= 0:
        raise ValueError("BBOX degenerado (largura ou altura zero): %r" % (bbox,))
    return [min_lon, min_lat, max_lon, max_lat]


def lonlat_to_mercator(lon, lat):
    x = lon * ORIGIN_SHIFT / 180.0
    lat = max(-MAX_LAT, min(MAX_LAT, lat))
    y = math.log(math.tan((90.0 + lat) * math.pi / 360.0)) * EARTH_RADIUS
    return x, y


def lonlat_to_tile(lon, lat, zoom):
    """Tile XYZ (x, y) que contem o ponto. y cresce para o sul (esquema Google/OSM)."""
    n = 2 ** zoom
    lat = max(-MAX_LAT, min(MAX_LAT, lat))
    x = int(math.floor((lon + 180.0) / 360.0 * n))
    lat_r = math.radians(lat)
    y = int(math.floor((1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi) / 2.0 * n))
    return min(max(x, 0), n - 1), min(max(y, 0), n - 1)


def tile_bounds_mercator(x, y, zoom):
    """Extensao (left, bottom, right, top) do tile em metros EPSG:3857."""
    size = 2.0 * ORIGIN_SHIFT / (2 ** zoom)
    left = -ORIGIN_SHIFT + x * size
    top = ORIGIN_SHIFT - y * size
    return left, top - size, left + size, top


def tile_range(bbox, zoom):
    """Faixa de tiles (x_min, x_max, y_min, y_max) que cobre o BBOX WGS84."""
    min_lon, min_lat, max_lon, max_lat = clamp_bbox(bbox)
    x0, y0 = lonlat_to_tile(min_lon, max_lat, zoom)  # canto superior esquerdo
    # recuo infinitesimal: uma borda exatamente sobre o limite do tile nao inclui o vizinho
    eps = 1e-9
    x1, y1 = lonlat_to_tile(max_lon - eps, min_lat + eps, zoom)
    return x0, x1, y0, y1


def mercator_resolution(zoom, tile_size=TILE_SIZE):
    """Tamanho do pixel em metros EPSG:3857 (no equador) para o zoom."""
    return 2.0 * ORIGIN_SHIFT / (tile_size * (2 ** zoom))


def ground_resolution(lat, zoom, tile_size=TILE_SIZE):
    """Resolucao real aproximada no terreno (m/pixel) na latitude informada."""
    return math.cos(math.radians(lat)) * mercator_resolution(zoom, tile_size)


def quadkey(x, y, zoom):
    """Quadkey no esquema Bing Maps."""
    digits = []
    for i in range(zoom, 0, -1):
        digit = 0
        mask = 1 << (i - 1)
        if x & mask:
            digit += 1
        if y & mask:
            digit += 2
        digits.append(str(digit))
    return "".join(digits)


def crop_window(bbox, zoom, tile_size=TILE_SIZE):
    """Janela de pixels do BBOX dentro da grade de tiles.

    Retorna dict com a grade (x0..x1, y0..y1), a janela recortada (px0, py0, width, height)
    relativa ao canto superior esquerdo da grade, a origem georreferenciada (left, top) e a
    resolucao em metros EPSG:3857.
    """
    min_lon, min_lat, max_lon, max_lat = clamp_bbox(bbox)
    x0, x1, y0, y1 = tile_range([min_lon, min_lat, max_lon, max_lat], zoom)
    res = mercator_resolution(zoom, tile_size)
    grid_left, _, _, grid_top = tile_bounds_mercator(x0, y0, zoom)
    bx0, by0 = lonlat_to_mercator(min_lon, min_lat)
    bx1, by1 = lonlat_to_mercator(max_lon, max_lat)
    grid_w = (x1 - x0 + 1) * tile_size
    grid_h = (y1 - y0 + 1) * tile_size
    px0 = max(0, int(math.floor((bx0 - grid_left) / res)))
    py0 = max(0, int(math.floor((grid_top - by1) / res)))
    px1 = min(grid_w, int(math.ceil((bx1 - grid_left) / res)))
    py1 = min(grid_h, int(math.ceil((grid_top - by0) / res)))
    return {
        'x0': x0, 'x1': x1, 'y0': y0, 'y1': y1,
        'px0': px0, 'py0': py0, 'width': max(1, px1 - px0), 'height': max(1, py1 - py0),
        'left': grid_left + px0 * res, 'top': grid_top - py0 * res, 'res': res,
    }


# ---------------------------------------------------------------------------------------------
# Grade Keyhole (Google Earth historico): geografica EPSG:4326 (Plate Carree), NAO Web Mercator.
# No nivel L, a grade tem 2^L x 2^L tiles de 360/2^L graus (a latitude vai de -180 a 180, so
# metade e usada). As linhas crescem para o NORTE, a partir de -180 graus.
# ---------------------------------------------------------------------------------------------
METERS_PER_DEGREE = math.pi * EARTH_RADIUS / 180.0


def keyhole_tile_deg(level):
    return 360.0 / (2 ** level)


def keyhole_row_col(lat, lon, level):
    n = 2 ** level
    row = int(math.floor((lat + 180.0) / 360.0 * n))
    col = int(math.floor((lon + 180.0) / 360.0 * n))
    return min(max(row, 0), n - 1), min(max(col, 0), n - 1)


def keyhole_tile_range(bbox, level):
    """Faixa (row_min, row_max, col_min, col_max) da grade Keyhole que cobre o BBOX WGS84."""
    min_lon, min_lat, max_lon, max_lat = clamp_bbox(bbox)
    eps = 1e-9  # borda exatamente sobre o limite do tile nao inclui o vizinho
    r0, c0 = keyhole_row_col(min_lat, min_lon, level)
    r1, c1 = keyhole_row_col(max_lat - eps, max_lon - eps, level)
    return r0, r1, c0, c1


def keyhole_quadtree_path(row, col, level):
    """Caminho na quadtree do Google Earth ('0...', um digito por nivel)."""
    chars = ['0'] * (level + 1)
    for i in range(level, -1, -1):
        rb, cb = row & 1, col & 1
        row >>= 1
        col >>= 1
        chars[i] = str((rb << 1) | (rb ^ cb))
    return ''.join(chars)


def keyhole_crop_window(bbox, level, tile_size=TILE_SIZE):
    """Janela de pixels do BBOX dentro da grade Keyhole (mesma ideia do crop_window).

    A linha 0 da imagem e a linha de tiles MAIS AO NORTE (r1). Coordenadas e resolucao em graus.
    """
    min_lon, min_lat, max_lon, max_lat = clamp_bbox(bbox)
    r0, r1, c0, c1 = keyhole_tile_range([min_lon, min_lat, max_lon, max_lat], level)
    deg = keyhole_tile_deg(level)
    res = deg / tile_size
    grid_left = c0 * deg - 180.0
    grid_top = (r1 + 1) * deg - 180.0
    grid_w = (c1 - c0 + 1) * tile_size
    grid_h = (r1 - r0 + 1) * tile_size
    px0 = max(0, int(math.floor((min_lon - grid_left) / res + 1e-9)))
    py0 = max(0, int(math.floor((grid_top - max_lat) / res + 1e-9)))
    px1 = min(grid_w, int(math.ceil((max_lon - grid_left) / res - 1e-9)))
    py1 = min(grid_h, int(math.ceil((grid_top - min_lat) / res - 1e-9)))
    return {
        'r0': r0, 'r1': r1, 'c0': c0, 'c1': c1,
        'px0': px0, 'py0': py0, 'width': max(1, px1 - px0), 'height': max(1, py1 - py0),
        'left': grid_left + px0 * res, 'top': grid_top - py0 * res, 'res': res,
    }


def keyhole_estimate(bbox, level, tile_size=TILE_SIZE, kb_per_tile=25.0):
    """Estimativa para o Google Earth historico (mesmas chaves do estimate)."""
    win = keyhole_crop_window(bbox, level, tile_size)
    cols = win['c1'] - win['c0'] + 1
    rows = win['r1'] - win['r0'] + 1
    return {
        'zoom': level, 'tiles': cols * rows, 'cols': cols, 'rows': rows,
        'width': win['width'], 'height': win['height'],
        'ground_res_m': win['res'] * METERS_PER_DEGREE,   # norte-sul; leste-oeste = x cos(lat)
        'download_mb': cols * rows * kb_per_tile / 1024.0,
        'output_mb': win['width'] * win['height'] * 3 / (1024.0 * 1024.0),
    }


def estimate(bbox, zoom, tile_size=TILE_SIZE, kb_per_tile=25.0):
    """Estimativa rapida para a GUI: quantidade de tiles, dimensoes e volume."""
    min_lon, min_lat, max_lon, max_lat = clamp_bbox(bbox)
    win = crop_window([min_lon, min_lat, max_lon, max_lat], zoom, tile_size)
    cols = win['x1'] - win['x0'] + 1
    rows = win['y1'] - win['y0'] + 1
    center_lat = (min_lat + max_lat) / 2.0
    return {
        'zoom': zoom,
        'tiles': cols * rows,
        'cols': cols,
        'rows': rows,
        'width': win['width'],
        'height': win['height'],
        'ground_res_m': ground_resolution(center_lat, zoom, tile_size),
        'download_mb': cols * rows * kb_per_tile / 1024.0,
        'output_mb': win['width'] * win['height'] * 3 / (1024.0 * 1024.0),
    }
