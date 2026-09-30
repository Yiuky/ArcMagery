# -*- coding: utf-8 -*-
"""
ArcMagery - Integracao do CBERS / Amazonia-1 (STAC do INPE) na janela principal (Python 2.7).

A janela principal trata as colecoes do INPE como "sensores" com codigo 'INPE:<colecao>'.
Este modulo concentra o que e especifico do INPE e nao depende do Tk:
  * catalogo de colecoes (rotulo, periodo, resolucao, bandas) e produtos (composicoes);
  * conversao dos itens STAC para o formato de linha da tabela principal (images_cache);
  * chamadas ao backend (stac_search / stac_download / stac_thumb) no Python 3 com GDAL.
"""
from __future__ import division

import re

import gee_bridge

PREFIX = 'INPE:'

# (rotulo exibido, colecao STAC, resolucao nativa em m, periodo, bandas, observacao)
_COLLECTIONS = [
    (u"CBERS-4A WPM · 8 m multiespectral + 2 m PAN", 'CB4A-WPM-L4-DN-1', 8, u"29/12/2019 até o Presente (Ativo)",
     u"BAND1 azul, BAND2 verde, BAND3 vermelho, BAND4 NIR (8 m) · BAND0 pancromática (2 m)",
     u"Nível 4 (ortorretificado), números digitais."),
    (u"CBERS-4A WPM · 2 m fusionada RGB (PCA)", 'CB4A-WPM-PCA-FUSED-1', 2, u"02/03/2023 até o Presente (Ativo)",
     u"RGB fusionado (pancromática + multiespectral)", u"Produto fusionado pelo INPE."),
    (u"CBERS-4A MUX · 16 m", 'CB4A-MUX-L4-DN-1', 16, u"27/12/2019 até o Presente (Ativo)",
     u"BAND5 azul, BAND6 verde, BAND7 vermelho, BAND8 NIR", u"Nível 4, números digitais."),
    (u"CBERS-4A MUX · 16 m reflectância de superfície", 'CB4A-MUX-L4-SR-1', 16, u"01/01/2026 até o Presente (Ativo)",
     u"BAND5 azul, BAND6 verde, BAND7 vermelho, BAND8 NIR", u"Reflectância de superfície (SR)."),
    (u"CBERS-4A WFI · 55 m reflectância de superfície", 'CB4A-WFI-L4-SR-1', 55, u"01/01/2020 até o Presente (Ativo)",
     u"BAND13 azul, BAND14 verde, BAND15 vermelho, BAND16 NIR", u"Faixa larga (~684 km), revisita frequente."),
    (u"CBERS-4 MUX · 20 m reflectância de superfície", 'CB4-MUX-L4-SR-1', 20, u"01/01/2016 até o Presente (Ativo)",
     u"BAND5 azul, BAND6 verde, BAND7 vermelho, BAND8 NIR", u"Reflectância de superfície (SR)."),
    (u"CBERS-4 MUX · 20 m", 'CB4-MUX-L4-DN-1', 20, u"09/12/2014 até o Presente (Ativo)",
     u"BAND5 azul, BAND6 verde, BAND7 vermelho, BAND8 NIR", u"Nível 4, números digitais."),
    (u"CBERS-4 WFI · 64 m reflectância de superfície", 'CB4-WFI-L4-SR-1', 64, u"01/01/2016 até o Presente (Ativo)",
     u"BAND13 azul, BAND14 verde, BAND15 vermelho, BAND16 NIR", u"Faixa larga (~866 km)."),
    (u"CBERS-4 PAN · 10 m (verde, vermelho, NIR)", 'CB4-PAN10M-L4-DN-1', 10, u"09/12/2014 até o Presente (Ativo)",
     u"BAND2 verde, BAND3 vermelho, BAND4 NIR", u"Sem banda azul: use falsa cor."),
    (u"CBERS-4 PAN · 5 m pancromática", 'CB4-PAN5M-L4-DN-1', 5, u"09/12/2014 até o Presente (Ativo)",
     u"BAND1 pancromática", u"Uma banda (tons de cinza)."),
    (u"Amazônia-1 WFI · 64 m reflectância de superfície", 'AMZ1-WFI-L4-SR-1', 64, u"01/01/2024 até o Presente (Ativo)",
     u"BAND1 azul, BAND2 verde, BAND3 vermelho, BAND4 NIR", u"Primeiro satélite brasileiro de observação (2021)."),
    (u"Amazônia-1 WFI · 64 m", 'AMZ1-WFI-L4-DN-1', 64, u"17/03/2021 até o Presente (Ativo)",
     u"BAND1 azul, BAND2 verde, BAND3 vermelho, BAND4 NIR", u"Nível 4, números digitais."),
    (u"CBERS-4A WFI · 55 m", 'CB4A-WFI-L4-DN-1', 55, u"04/07/2020 até o Presente (Ativo)", u"BAND13 azul, BAND14 verde, BAND15 vermelho, BAND16 NIR", u"Nível 4, números digitais."),
    (u"CBERS-4 WFI · 64 m", 'CB4-WFI-L4-DN-1', 64, u"09/12/2014 até o Presente (Ativo)", u"BAND13 azul, BAND14 verde, BAND15 vermelho, BAND16 NIR", u"Nível 4, números digitais."),
    # Cubos de dados (Brazil Data Cube)
    (u"Cubo 16 dias · CBERS-4 WFI 64 m (sem nuvens, NDVI/EVI)", 'CBERS4-WFI-16D-2', 64, u"01/01/2016 até o Presente (Ativo)",
     u"BAND13 azul, BAND14 verde, BAND15 vermelho, BAND16 NIR · NDVI · EVI", u"Composição temporal sem nuvens (Brazil Data Cube). NDVI/EVI prontos (escala 0,0001)."),
    (u"Cubo 8 dias · CBERS-4/4A WFI 64 m (sem nuvens, NDVI/EVI)", 'CBERS-WFI-8D-1', 64, u"01/01/2020 até o Presente (Ativo)",
     u"BAND13 azul, BAND14 verde, BAND15 vermelho, BAND16 NIR · NDVI · EVI", u"Composição temporal sem nuvens (Brazil Data Cube). NDVI/EVI prontos (escala 0,0001)."),
    (u"Cubo 2 meses · CBERS-4 MUX 20 m (sem nuvens, NDVI/EVI)", 'CBERS4-MUX-2M-1', 20, u"01/01/2016 até o Presente (Ativo)",
     u"BAND5 azul, BAND6 verde, BAND7 vermelho, BAND8 NIR · NDVI · EVI", u"Composição temporal sem nuvens (Brazil Data Cube). NDVI/EVI prontos (escala 0,0001)."),
    # Nivel 2
    (u"CBERS-4A WPM · 8 m + 2 m PAN (Nível 2)", 'CB4A-WPM-L2-DN-1', 8, u"29/12/2019 até o Presente (Ativo)",
     u"BAND1 azul, BAND2 verde, BAND3 vermelho, BAND4 NIR (8 m) · BAND0 pancromática (2 m)", u"Nível 2: correção sistemática, SEM ortorretificação (geometria menos precisa que o Nível 4)."),
    (u"CBERS-4A MUX · 16 m (Nível 2)", 'CB4A-MUX-L2-DN-1', 16, u"27/12/2019 até o Presente (Ativo)", u"BAND5 azul, BAND6 verde, BAND7 vermelho, BAND8 NIR", u"Nível 2: correção sistemática, SEM ortorretificação (geometria menos precisa que o Nível 4)."),
    (u"CBERS-4A WFI · 55 m (Nível 2)", 'CB4A-WFI-L2-DN-1', 55, u"27/12/2019 até o Presente (Ativo)", u"BAND13 azul, BAND14 verde, BAND15 vermelho, BAND16 NIR", u"Nível 2: correção sistemática, SEM ortorretificação (geometria menos precisa que o Nível 4)."),
    (u"CBERS-4 MUX · 20 m (Nível 2)", 'CB4-MUX-L2-DN-1', 20, u"08/12/2014 até o Presente (Ativo)", u"BAND5 azul, BAND6 verde, BAND7 vermelho, BAND8 NIR", u"Nível 2: correção sistemática, SEM ortorretificação (geometria menos precisa que o Nível 4)."),
    (u"CBERS-4 WFI · 64 m (Nível 2)", 'CB4-WFI-L2-DN-1', 64, u"14/12/2014 até o Presente (Ativo)", u"BAND13 azul, BAND14 verde, BAND15 vermelho, BAND16 NIR", u"Nível 2: correção sistemática, SEM ortorretificação (geometria menos precisa que o Nível 4)."),
    (u"CBERS-4 PAN · 10 m (Nível 2)", 'CB4-PAN10M-L2-DN-1', 10, u"09/12/2014 até o Presente (Ativo)",
     u"BAND2 verde, BAND3 vermelho, BAND4 NIR", u"Nível 2: correção sistemática, SEM ortorretificação (geometria menos precisa que o Nível 4)."),
    (u"CBERS-4 PAN · 5 m pancromática (Nível 2)", 'CB4-PAN5M-L2-DN-1', 5, u"09/12/2014 até o Presente (Ativo)",
     u"BAND1 pancromática", u"Nível 2: correção sistemática, SEM ortorretificação (geometria menos precisa que o Nível 4)."),
    (u"Amazônia-1 WFI · 64 m (Nível 2)", 'AMZ1-WFI-L2-DN-1', 64, u"03/03/2021 até o Presente (Ativo)",
     u"BAND1 azul, BAND2 verde, BAND3 vermelho, BAND4 NIR", u"Nível 2: correção sistemática, SEM ortorretificação (geometria menos precisa que o Nível 4)."),
    # Historico CBERS-2 / 2B
    (u"Histórico · CBERS-2 CCD · 20 m (2003-2009)", 'CB2-CCD-L2-DN-1', 20, u"28/10/2003 a 07/01/2009 (Encerrado)",
     u"B1 azul, B2 verde, B3 vermelho, B4 NIR, B5 pancromática (20 m)",
     u"Nível 2 sem ortorretificação: a posição varia centenas de metros entre datas (medido: ~650 m). "
     u"Footprint retangular: a cobertura da busca é estimada; o recorte informa a real."),
    (u"Histórico · CBERS-2B CCD · 20 m (2007-2010)", 'CB2B-CCD-L2-DN-1', 20, u"25/09/2007 a 11/03/2010 (Encerrado)",
     u"B1 azul, B2 verde, B3 vermelho, B4 NIR, B5 pancromática (20 m)",
     u"Nível 2 sem ortorretificação: a posição varia centenas de metros entre datas (medido: ~650 m). "
     u"Footprint retangular: a cobertura da busca é estimada; o recorte informa a real."),
    (u"Histórico · CBERS-2B HRC · 2,5 m pancromática (2007-2010)", 'CB2B-HRC-L2-DN-1', 2.5,
     u"29/09/2007 a 11/03/2010 (Encerrado)", u"BAND1 pancromática (2,5 m)", u"Nível 2. Cenas pequenas (~27 km)."),
    (u"Histórico · CBERS-2 WFI · 260 m (2003-2005)", 'CB2-WFI-L2-DN-1', 260, u"22/10/2003 a 13/04/2005 (Encerrado)",
     u"BAND1 vermelho, BAND2 NIR", u"Nível 2. Apenas vermelho e NIR."),
    (u"Histórico · CBERS-2B WFI · 260 m (2007-2010)", 'CB2B-WFI-L2-DN-1', 260, u"29/09/2007 a 10/03/2010 (Encerrado)",
     u"BAND1 vermelho, BAND2 NIR", u"Nível 2. Apenas vermelho e NIR."),
    # Mosaicos
    (u"Mosaico Brasil · CBERS-4 WFI (abr-jun/2020, RGB)", 'mosaic-cbers4-brazil-3m-1', 64, u"01/04/2020 a 30/06/2020",
     u"RGB visual", u"Mosaico trimestral de todo o Brasil."),
    (u"Mosaico Paraíba · CBERS-4A WFI (jul-set/2020, RGB)", 'mosaic-cbers4a-paraiba-3m-1', 55, u"01/07/2020 a 30/09/2020",
     u"RGB visual", u"Mosaico trimestral do estado da Paraíba."),
]

INPE_SENSOR_DISPLAY = [(label, PREFIX + cid) for (label, cid, _r, _p, _b, _n) in _COLLECTIONS]

INPE_SENSOR_METADATA = dict(
    (PREFIX + cid, {
        'name': label,
        'agency': u'INPE',
        'collection': cid,
        'period_display': period,
        'end_year': None,
        'res': u'%d m' % res,
        'native_res': res,
        'available_bands': bands,
        'notes': notes,
    }) for (label, cid, res, period, bands, notes) in _COLLECTIONS)

PRODUCTS = [
    ('rgb', u'Cor natural (vermelho, verde, azul)'),
    ('false', u'Falsa cor (NIR, vermelho, verde) - vegetação em vermelho'),
    ('multi', u'Multibanda (todas as bandas, exibida em cor natural)'),
    ('pan', u'Pancromática (tons de cinza, maior resolução)'),
    ('fused', u'Fusionada RGB'),
    ('ndvi', u'NDVI (índice de vegetação, escala 0,0001)'),
    ('evi', u'EVI (índice de vegetação, escala 0,0001)'),
    ('visual', u'RGB visual (mosaico)'),
]
_CUBE_MODES = ['rgb', 'false', 'multi', 'ndvi', 'evi']
_COLLECTION_MODES = {   # deve bater com stac_core.available_modes (teste test_catalog_sync)
    'CB4A-WPM-L4-DN-1': ['rgb', 'false', 'multi', 'pan'],
    'CB4A-WPM-L2-DN-1': ['rgb', 'false', 'multi', 'pan'],
    'CB4A-WPM-PCA-FUSED-1': ['fused'],
    'CB4-PAN10M-L4-DN-1': ['false', 'multi'],
    'CB4-PAN10M-L2-DN-1': ['false', 'multi'],
    'CB4-PAN5M-L4-DN-1': ['pan'],
    'CB4-PAN5M-L2-DN-1': ['pan'],
    'CBERS4-WFI-16D-2': _CUBE_MODES,
    'CBERS-WFI-8D-1': _CUBE_MODES,
    'CBERS4-MUX-2M-1': _CUBE_MODES,
    'CB2-CCD-L2-DN-1': ['rgb', 'false', 'multi', 'pan'],
    'CB2B-CCD-L2-DN-1': ['rgb', 'false', 'multi', 'pan'],
    'CB2B-HRC-L2-DN-1': ['pan'],
    'CB2-WFI-L2-DN-1': ['multi'],
    'CB2B-WFI-L2-DN-1': ['multi'],
    'mosaic-cbers4-brazil-3m-1': ['visual'],
    'mosaic-cbers4a-paraiba-3m-1': ['visual'],
}


def is_inpe(sensor_code):
    return bool(sensor_code) and str(sensor_code).startswith(PREFIX)


def collection_of(sensor_code):
    return str(sensor_code)[len(PREFIX):] if is_inpe(sensor_code) else None


def modes_for(sensor_code):
    return _COLLECTION_MODES.get(collection_of(sensor_code), ['rgb', 'false', 'multi'])


def composition_items(sensor_code):
    """Itens da combobox de composicao no formato 'codigo - rotulo' (padrao da janela)."""
    labels = dict(PRODUCTS)
    return [u"%s - %s" % (m, labels[m]) for m in modes_for(sensor_code)]


def product_label(mode):
    return dict(PRODUCTS).get(mode, mode)


def native_res(sensor_code):
    return INPE_SENSOR_METADATA.get(sensor_code, {}).get('native_res')


def format_cloud(value):
    """'3.2%' / 'n/d' (colecoes DN do INPE nao informam nuvens)."""
    if value is None or value == '' or value == 'n/d':
        return u"n/d"
    try:
        return u"%.1f%%" % float(value)
    except (TypeError, ValueError):
        return u"%s%%" % value


def item_to_row(item):
    """Item do backend stac_search -> linha no formato de images_cache da janela principal."""
    cov = item.get('coverage_pct')
    path_row = item.get('path_row') or u''
    tile = path_row.strip('/') or u'-'
    if cov is not None:
        # footprint retangular (ex.: CBERS-2/2B): a cobertura e so um limite superior
        tile = u"%s · %s%.0f%% da AOI" % (tile, u"até " if item.get('coverage_is_estimate') else u"", cov)
    return {
        'id': item.get('id'),
        'name': item.get('id'),
        'date': item.get('date'),
        'cloud_pct': item.get('cloud_cover'),
        'mgrs': tile,
        'coverage_pct': cov,
        'collection': item.get('collection'),
        'thumbnail': item.get('thumbnail'),
        'source': 'INPE',
    }


def _bbox_str(bbox):
    return ','.join('%.8f' % float(v) for v in bbox) if bbox else None


def _area_params(bbox, geojson_file):
    if geojson_file:
        return {'geojson_file': geojson_file}
    if bbox:
        return {'bbox': _bbox_str(bbox)}
    return {}


def search(sensor_code, start_date, end_date, bbox=None, geojson_file=None, max_images=100, max_cloud=None):
    """Busca no STAC do INPE e devolve {'success', 'images': [linhas], 'message'}."""
    params = {'collections': collection_of(sensor_code), 'start_date': start_date, 'end_date': end_date,
              'max_items': max_images, 'max_cloud': max_cloud}
    params.update(_area_params(bbox, geojson_file))
    resp = gee_bridge.run_backend_cmd('stac_search', params, python_exe=gee_bridge.find_python3_gdal())
    if not resp.get('success'):
        return resp
    return {'success': True, 'images': [item_to_row(i) for i in resp.get('items', [])]}


def _friendly_progress(on_progress):
    if not on_progress:
        return None

    def cb(line):
        m = re.search(r'PROGRESS\s+(\d+)\s*/\s*100', line or '')
        if m:
            on_progress(u"Recortando cena do INPE na resolução nativa... %s%%" % m.group(1))
        elif line and 'CBERS' in line:
            on_progress(line.replace('[ArcGEE] ', ''))
    return cb


def download(image_id, sensor_code, mode, out_tif, bbox=None, geojson_file=None, on_progress=None):
    """Recorta a cena na grade nativa. Resposta inclui 'file' e 'rgb_bands' (para o load_layer)."""
    params = {'collection': collection_of(sensor_code), 'item_id': image_id, 'mode': mode, 'out': out_tif}
    params.update(_area_params(bbox, geojson_file))
    return gee_bridge.run_backend_cmd('stac_download', params, on_progress=_friendly_progress(on_progress),
                                      python_exe=gee_bridge.find_python3_gdal())


def thumbnail(row, out_png):
    """Miniatura (GIF para o Tk 8.5) de uma linha da tabela."""
    return gee_bridge.run_backend_cmd('stac_thumb', {'collection': row.get('collection'), 'item_id': row.get('id'),
                                                     'href': row.get('thumbnail'), 'out': out_png},
                                      python_exe=gee_bridge.find_python3_gdal())
