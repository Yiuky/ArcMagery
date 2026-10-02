# -*- coding: utf-8 -*-
"""
Catálogo das fontes do QMagery: sensores, composições e produtos.

Espelha o ArcMagery (gee_bridge.COMPOSITIONS, arcmagery_inpe, arcmagery_spot, arcmagery_gehist e
arcmagery_wayback). tests/qgis/test_paridade.py compara este arquivo com os módulos do ArcMagery:
ao mudar um catálogo lá, atualize aqui.
"""

# Escala máxima do mapa para buscar pela extensão da tela (igual ao ArcMagery)
MAX_ALLOWED_SCALE = 500000.0

# Sensores do Google Earth Engine (iguais ao gee_gui.py do ArcMagery)
GEE_SENSOR_DISPLAY = [
    ("Sentinel-2 (MSI - Nível 2A Harmonizado)", "S2"),
    ("Landsat 8 & 9 (OLI/TIRS - Col. 2 L2)", "L8"),
    ("Landsat 7 (ETM+ - Col. 2 L2)", "L7"),
    ("Landsat 5 (TM - Col. 2 L2)", "L5"),
    ("Landsat 4 (TM - Col. 2 L2)", "L4"),
    ("Landsat 3 (MSS - Col. 2 T1/T2)", "L3"),
    ("Landsat 2 (MSS - Col. 2 T1/T2)", "L2"),
    ("Landsat 1 (MSS - Col. 2 T1/T2)", "L1")
]

GEE_SENSOR_METADATA = {
    'S2': {
        'name': 'Sentinel-2 (MSI)',
        'agency': 'ESA / Copernicus',
        'collection': 'COPERNICUS/S2_SR_HARMONIZED',
        'period_display': '28/03/2017 até o Presente (Ativo)',
        'res': '10m / 20m',
        'available_bands': "B1, B2, B3, B4, B5, B6, B7, B8, B8A, B9, B11, B12",
        'default_pixel_size': '10',
    },
    'L8': {
        'name': 'Landsat 8 & 9 (OLI / TIRS)',
        'agency': 'USGS / NASA',
        'collection': 'LANDSAT/LC08/C02/T1_L2 (+ LC09)',
        'period_display': '11/04/2013 até o Presente (L8: 2013+ | L9: 2021+)',
        'res': '30m',
        'available_bands': "SR_B1 a SR_B7, ST_B10 (aceita B1 a B7)",
        'default_pixel_size': '30',
    },
    'L7': {
        'name': 'Landsat 7 (ETM+)',
        'agency': 'USGS / NASA',
        'collection': 'LANDSAT/LE07/C02/T1_L2',
        'period_display': '15/04/1999 até o Presente (SLC-off após 31/05/2003)',
        'res': '30m',
        'available_bands': "SR_B1 a SR_B5, SR_B7, ST_B6 (aceita B1 a B7)",
        'default_pixel_size': '30',
    },
    'L5': {
        'name': 'Landsat 5 (TM)',
        'agency': 'USGS / NASA',
        'collection': 'LANDSAT/LT05/C02/T1_L2',
        'period_display': '01/03/1984 a 05/05/2012 (Encerrado)',
        'res': '30m',
        'available_bands': "SR_B1 a SR_B5, SR_B7, ST_B6 (aceita B1 a B7)",
        'default_pixel_size': '30',
    },
    'L4': {
        'name': 'Landsat 4 (TM)',
        'agency': 'USGS / NASA',
        'collection': 'LANDSAT/LT04/C02/T1_L2',
        'period_display': '16/07/1982 a 14/12/1993 (Encerrado)',
        'res': '30m',
        'available_bands': "SR_B1 a SR_B5, SR_B7, ST_B6 (aceita B1 a B7)",
        'default_pixel_size': '30',
    },
    'L3': {
        'name': 'Landsat 3 (MSS)',
        'agency': 'USGS / NASA',
        'collection': 'LANDSAT/LM03/C02/T1',
        'period_display': '05/03/1978 a 07/09/1983 (Encerrado)',
        'res': '60m',
        'available_bands': "B4, B5, B6, B7",
        'default_pixel_size': '60',
    },
    'L2': {
        'name': 'Landsat 2 (MSS)',
        'agency': 'USGS / NASA',
        'collection': 'LANDSAT/LM02/C02/T1',
        'period_display': '22/01/1975 a 26/02/1982 (Encerrado)',
        'res': '60m',
        'available_bands': "B4, B5, B6, B7",
        'default_pixel_size': '60',
    },
    'L1': {
        'name': 'Landsat 1 (MSS)',
        'agency': 'USGS / NASA',
        'collection': 'LANDSAT/LM01/C02/T1',
        'period_display': '23/07/1972 a 06/01/1978 (Encerrado)',
        'res': '60m',
        'available_bands': "B4, B5, B6, B7",
        'default_pixel_size': '60',
    }
}

# Composições por sensor (idênticas a gee_bridge.COMPOSITIONS): (código, rótulo, bandas, tipo)
# tipo: rgb (3 bandas), multi (multibanda), index (índice de 1 banda), bands (lista digitada),
#       math (fórmula digitada)
GEE_COMPOSITIONS = {
    'S2': [
        ('432', 'COR NATURAL - 4.3.2', ['B4', 'B3', 'B2'], 'rgb'),
        ('12114', 'FALSA COR - 12.11.4', ['B12', 'B11', 'B4'], 'rgb'),
        ('843', 'COR INFRAVERMELHA (VEGETAÇÃO) - 8.4.3', ['B8', 'B4', 'B3'], 'rgb'),
        ('8a43', 'COR INFRAVERMELHA (VEGETAÇÃO) - 8a.4.3', ['B8A', 'B4', 'B3'], 'rgb'),
        ('1182', 'AGRICULTURA - 11.8.2', ['B11', 'B8', 'B2'], 'rgb'),
        ('118a2', 'AGRICULTURA - 11.8a.2', ['B11', 'B8A', 'B2'], 'rgb'),
        ('12118', 'PENETRAÇÃO ATMOSFÉRICA - 12.11.8', ['B12', 'B11', 'B8'], 'rgb'),
        ('12118a', 'PENETRAÇÃO ATMOSFÉRICA - 12.11.8a', ['B12', 'B11', 'B8A'], 'rgb'),
        ('8112', 'SAÚDE DA VEGETAÇÃO - 8.11.2', ['B8', 'B11', 'B2'], 'rgb'),
        ('8a112', 'SAÚDE DA VEGETAÇÃO - 8a.11.2', ['B8A', 'B11', 'B2'], 'rgb'),
        ('8114', 'SOLO/ÁGUA - 8.11.4', ['B8', 'B11', 'B4'], 'rgb'),
        ('8a114', 'SOLO/ÁGUA - 8a.11.4', ['B8A', 'B11', 'B4'], 'rgb'),
        ('1283', 'NATURAL COM REMOÇÃO ATMOSFÉRICA - 12.8.3', ['B12', 'B8', 'B3'], 'rgb'),
        ('128a3', 'NATURAL COM REMOÇÃO ATMOSFÉRICA - 12.8a.3', ['B12', 'B8A', 'B3'], 'rgb'),
        ('1284', 'INFRAVERMELHO ONDA CURTA - 12.8.4', ['B12', 'B8', 'B4'], 'rgb'),
        ('128a4', 'INFRAVERMELHO ONDA CURTA - 12.8a.4', ['B12', 'B8A', 'B4'], 'rgb'),
        ('1184', 'ANÁLISE DA VEGETAÇÃO - 11.8.4', ['B11', 'B8', 'B4'], 'rgb'),
        ('118a4', 'ANÁLISE DA VEGETAÇÃO - 11.8a.4', ['B11', 'B8A', 'B4'], 'rgb'),
        ('483', 'ANÁLISE DA VEGETAÇÃO - 4.8.3', ['B4', 'B8', 'B3'], 'rgb'),
        ('MB_10', 'MULTIBANDA - 10 BANDAS PRINCIPAIS (B2 a B12)', ['B2', 'B3', 'B4', 'B5', 'B6', 'B7', 'B8', 'B8A', 'B11', 'B12'], 'multi'),
        ('MB_6', 'MULTIBANDA - 6 BANDAS VNIR/SWIR (B2, B3, B4, B8, B11, B12)', ['B2', 'B3', 'B4', 'B8', 'B11', 'B12'], 'multi'),
        ('MB_12', 'MULTIBANDA - 12 BANDAS COMPLETAS (B1 a B12)', ['B1', 'B2', 'B3', 'B4', 'B5', 'B6', 'B7', 'B8', 'B8A', 'B9', 'B11', 'B12'], 'multi'),
        ('NDVI', 'ÍNDICE - NDVI (Vegetação: B8-B4)', ['B8', 'B4'], 'index'),
        ('NDWI', 'ÍNDICE - NDWI (Água: B3-B8)', ['B3', 'B8'], 'index'),
        ('NDMI', 'ÍNDICE - NDMI (Umidade: B8-B11)', ['B8', 'B11'], 'index'),
        ('NBR', 'ÍNDICE - NBR (Queimadas: B8-B12)', ['B8', 'B12'], 'index'),
        ('EVI', 'ÍNDICE - EVI (Vegetação Realçada)', ['B8', 'B4', 'B2'], 'index'),
        ('SAVI', 'ÍNDICE - SAVI (Ajustado ao Solo)', ['B8', 'B4'], 'index'),
        ('CUSTOM_BANDS', 'BANDAS PERSONALIZADAS (ex.: B8,B4,B3)', [], 'bands'),
        ('CUSTOM_MATH', 'ÍNDICE - FÓRMULA MATEMÁTICA (ex: (B8-B4)/(B8+B4))', [], 'math'),
    ],
    'L8': [
        ('432', 'COR NATURAL - 432', ['SR_B4', 'SR_B3', 'SR_B2'], 'rgb'),
        ('764', 'FALSA COR - 764', ['SR_B7', 'SR_B6', 'SR_B4'], 'rgb'),
        ('543', 'COR INFRAVERMELHA (VEGETAÇÃO) - 543', ['SR_B5', 'SR_B4', 'SR_B3'], 'rgb'),
        ('652', 'AGRICULTURA - 652', ['SR_B6', 'SR_B5', 'SR_B2'], 'rgb'),
        ('765', 'PENETRAÇÃO ATMOSFÉRICA - 765', ['SR_B7', 'SR_B6', 'SR_B5'], 'rgb'),
        ('562', 'SAÚDE DA VEGETAÇÃO - 562', ['SR_B5', 'SR_B6', 'SR_B2'], 'rgb'),
        ('564', 'SOLO/ÁGUA - 564', ['SR_B5', 'SR_B6', 'SR_B4'], 'rgb'),
        ('753', 'NATURAL COM REMOÇÃO ATMOSFÉRICA - 753', ['SR_B7', 'SR_B5', 'SR_B3'], 'rgb'),
        ('754', 'INFRAVERMELHO ONDA CURTA - 754', ['SR_B7', 'SR_B5', 'SR_B4'], 'rgb'),
        ('654', 'ANÁLISE DA VEGETAÇÃO - 654', ['SR_B6', 'SR_B5', 'SR_B4'], 'rgb'),
        ('MB_8', 'MULTIBANDA - 8 BANDAS (SR_B1 a SR_B7 + ST_B10 Térmica)', ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6', 'SR_B7', 'ST_B10'], 'multi'),
        ('MB_7', 'MULTIBANDA - 7 BANDAS ÓPTICAS (SR_B1 a SR_B7)', ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6', 'SR_B7'], 'multi'),
        ('MB_6', 'MULTIBANDA - 6 BANDAS PRINCIPAIS (SR_B2 a SR_B7)', ['SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6', 'SR_B7'], 'multi'),
        ('10', 'TÉRMICA - BANDA 10 (Temperatura de Superfície em °C)', ['ST_B10'], 'index'),
        ('NDVI', 'ÍNDICE - NDVI (Vegetação: NIR-RED)', ['SR_B5', 'SR_B4'], 'index'),
        ('NDWI', 'ÍNDICE - NDWI (Água: GREEN-NIR)', ['SR_B3', 'SR_B5'], 'index'),
        ('NDMI', 'ÍNDICE - NDMI (Umidade: NIR-SWIR1)', ['SR_B5', 'SR_B6'], 'index'),
        ('NBR', 'ÍNDICE - NBR (Queimadas: NIR-SWIR2)', ['SR_B5', 'SR_B7'], 'index'),
        ('EVI', 'ÍNDICE - EVI (Vegetação Realçada)', ['SR_B5', 'SR_B4', 'SR_B2'], 'index'),
        ('SAVI', 'ÍNDICE - SAVI (Ajustado ao Solo)', ['SR_B5', 'SR_B4'], 'index'),
        ('CUSTOM_BANDS', 'BANDAS PERSONALIZADAS (ex.: SR_B5,SR_B4,SR_B3)', [], 'bands'),
        ('CUSTOM_MATH', 'ÍNDICE - FÓRMULA MATEMÁTICA (ex: (SR_B5-SR_B4)/(SR_B5+SR_B4))', [], 'math'),
    ],
    'L7': [
        ('321', 'COR NATURAL - 321', ['SR_B3', 'SR_B2', 'SR_B1'], 'rgb'),
        ('753', 'FALSA COR - 753', ['SR_B7', 'SR_B5', 'SR_B3'], 'rgb'),
        ('432', 'COR INFRAVERMELHA (VEGETAÇÃO) - 432', ['SR_B4', 'SR_B3', 'SR_B2'], 'rgb'),
        ('541', 'AGRICULTURA - 541', ['SR_B5', 'SR_B4', 'SR_B1'], 'rgb'),
        ('754', 'PENETRAÇÃO ATMOSFÉRICA - 754', ['SR_B7', 'SR_B5', 'SR_B4'], 'rgb'),
        ('451', 'SAÚDE DA VEGETAÇÃO - 451', ['SR_B4', 'SR_B5', 'SR_B1'], 'rgb'),
        ('453', 'SOLO/ÁGUA - 453', ['SR_B4', 'SR_B5', 'SR_B3'], 'rgb'),
        ('742', 'NATURAL COM REMOÇÃO ATMOSFÉRICA - 742', ['SR_B7', 'SR_B4', 'SR_B2'], 'rgb'),
        ('743', 'INFRAVERMELHO ONDA CURTA - 743', ['SR_B7', 'SR_B4', 'SR_B3'], 'rgb'),
        ('543', 'ANÁLISE DA VEGETAÇÃO - 543', ['SR_B5', 'SR_B4', 'SR_B3'], 'rgb'),
        ('MB_7', 'MULTIBANDA - 7 BANDAS (SR_B1 a SR_B5, SR_B7 + ST_B6 Térmica)', ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B7', 'ST_B6'], 'multi'),
        ('MB_6', 'MULTIBANDA - 6 BANDAS ÓPTICAS (SR_B1 a SR_B5, SR_B7)', ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B7'], 'multi'),
        ('6', 'TÉRMICA - BANDA 6 (Temperatura de Superfície em °C)', ['ST_B6'], 'index'),
        ('NDVI', 'ÍNDICE - NDVI (Vegetação: NIR-RED)', ['SR_B4', 'SR_B3'], 'index'),
        ('NDWI', 'ÍNDICE - NDWI (Água: GREEN-NIR)', ['SR_B2', 'SR_B4'], 'index'),
        ('NDMI', 'ÍNDICE - NDMI (Umidade: NIR-SWIR1)', ['SR_B4', 'SR_B5'], 'index'),
        ('NBR', 'ÍNDICE - NBR (Queimadas: NIR-SWIR2)', ['SR_B4', 'SR_B7'], 'index'),
        ('EVI', 'ÍNDICE - EVI (Vegetação Realçada)', ['SR_B4', 'SR_B3', 'SR_B1'], 'index'),
        ('SAVI', 'ÍNDICE - SAVI (Ajustado ao Solo)', ['SR_B4', 'SR_B3'], 'index'),
        ('CUSTOM_BANDS', 'BANDAS PERSONALIZADAS (ex.: SR_B4,SR_B3,SR_B2)', [], 'bands'),
        ('CUSTOM_MATH', 'ÍNDICE - FÓRMULA MATEMÁTICA (ex: (SR_B4-SR_B3)/(SR_B4+SR_B3))', [], 'math'),
    ],
    'L5': [
        ('321', 'COR NATURAL - 321', ['SR_B3', 'SR_B2', 'SR_B1'], 'rgb'),
        ('753', 'FALSA COR - 753', ['SR_B7', 'SR_B5', 'SR_B3'], 'rgb'),
        ('432', 'COR INFRAVERMELHA (VEGETAÇÃO) - 432', ['SR_B4', 'SR_B3', 'SR_B2'], 'rgb'),
        ('541', 'AGRICULTURA - 541', ['SR_B5', 'SR_B4', 'SR_B1'], 'rgb'),
        ('754', 'PENETRAÇÃO ATMOSFÉRICA - 754', ['SR_B7', 'SR_B5', 'SR_B4'], 'rgb'),
        ('451', 'SAÚDE DA VEGETAÇÃO - 451', ['SR_B4', 'SR_B5', 'SR_B1'], 'rgb'),
        ('453', 'SOLO/ÁGUA - 453', ['SR_B4', 'SR_B5', 'SR_B3'], 'rgb'),
        ('742', 'NATURAL COM REMOÇÃO ATMOSFÉRICA - 742', ['SR_B7', 'SR_B4', 'SR_B2'], 'rgb'),
        ('743', 'INFRAVERMELHO ONDA CURTA - 743', ['SR_B7', 'SR_B4', 'SR_B3'], 'rgb'),
        ('543', 'ANÁLISE DA VEGETAÇÃO - 543', ['SR_B5', 'SR_B4', 'SR_B3'], 'rgb'),
        ('MB_7', 'MULTIBANDA - 7 BANDAS (SR_B1 a SR_B5, SR_B7 + ST_B6 Térmica)', ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B7', 'ST_B6'], 'multi'),
        ('MB_6', 'MULTIBANDA - 6 BANDAS ÓPTICAS (SR_B1 a SR_B5, SR_B7)', ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B7'], 'multi'),
        ('6', 'TÉRMICA - BANDA 6 (Temperatura de Superfície em °C)', ['ST_B6'], 'index'),
        ('NDVI', 'ÍNDICE - NDVI (Vegetação: NIR-RED)', ['SR_B4', 'SR_B3'], 'index'),
        ('NDWI', 'ÍNDICE - NDWI (Água: GREEN-NIR)', ['SR_B2', 'SR_B4'], 'index'),
        ('NDMI', 'ÍNDICE - NDMI (Umidade: NIR-SWIR1)', ['SR_B4', 'SR_B5'], 'index'),
        ('NBR', 'ÍNDICE - NBR (Queimadas: NIR-SWIR2)', ['SR_B4', 'SR_B7'], 'index'),
        ('EVI', 'ÍNDICE - EVI (Vegetação Realçada)', ['SR_B4', 'SR_B3', 'SR_B1'], 'index'),
        ('SAVI', 'ÍNDICE - SAVI (Ajustado ao Solo)', ['SR_B4', 'SR_B3'], 'index'),
        ('CUSTOM_BANDS', 'BANDAS PERSONALIZADAS (ex.: SR_B4,SR_B3,SR_B2)', [], 'bands'),
        ('CUSTOM_MATH', 'ÍNDICE - FÓRMULA MATEMÁTICA (ex: (SR_B4-SR_B3)/(SR_B4+SR_B3))', [], 'math'),
    ],
    'L1': [
        ('754', 'FALSA COR INFRAVERMELHA (PADRAO MSS) - 754', ['B7', 'B5', 'B4'], 'rgb'),
        ('654', 'FALSA COR VEGETAÇÃO - 654', ['B6', 'B5', 'B4'], 'rgb'),
        ('764', 'PENETRAÇÃO/SOLO - 764', ['B7', 'B6', 'B4'], 'rgb'),
        ('765', 'ANÁLISE DE BIOMASSA - 765', ['B7', 'B6', 'B5'], 'rgb'),
        ('MB_4', 'MULTIBANDA - 4 BANDAS MSS (B4, B5, B6, B7)', ['B4', 'B5', 'B6', 'B7'], 'multi'),
        ('NDVI', 'ÍNDICE - NDVI (Vegetação: B7-B5)', ['B7', 'B5'], 'index'),
        ('NDWI', 'ÍNDICE - NDWI (Água: B4-B7)', ['B4', 'B7'], 'index'),
        ('CUSTOM_BANDS', 'BANDAS PERSONALIZADAS (ex.: B7,B5,B4)', [], 'bands'),
        ('CUSTOM_MATH', 'ÍNDICE - FÓRMULA MATEMÁTICA (ex: (B7-B5)/(B7+B5))', [], 'math'),
    ],
}
GEE_COMPOSITIONS['L4'] = GEE_COMPOSITIONS['L5']
GEE_COMPOSITIONS['L3'] = GEE_COMPOSITIONS['L1']
GEE_COMPOSITIONS['L2'] = GEE_COMPOSITIONS['L1']

# Composição "cor natural" de cada sensor: usada para exibir em RGB os downloads multibanda
GEE_NATURAL_BANDS = {
    'S2': ['B4', 'B3', 'B2'],
    'L8': ['SR_B4', 'SR_B3', 'SR_B2'],
    'L7': ['SR_B3', 'SR_B2', 'SR_B1'], 'L5': ['SR_B3', 'SR_B2', 'SR_B1'], 'L4': ['SR_B3', 'SR_B2', 'SR_B1'],
    'L3': ['B7', 'B5', 'B4'], 'L2': ['B7', 'B5', 'B4'], 'L1': ['B7', 'B5', 'B4'],   # MSS não tem azul
}

# Resolução nativa (m) usada na estimativa de tamanho do download
GEE_NATIVE_RES = {'S2': 10.0, 'L8': 30.0, 'L7': 30.0, 'L5': 30.0, 'L4': 30.0, 'L3': 60.0, 'L2': 60.0, 'L1': 60.0}

GEE_INDEX_CODES = ('NDVI', 'NDWI', 'NDMI', 'NBR', 'EVI', 'SAVI')


# Coleções do STAC INPE (idênticas ao arcmagery_inpe.py)
INPE_PREFIX = 'INPE:'
INPE_COLLECTIONS = [
    ("CBERS-4A WPM · 8 m multiespectral + 2 m PAN", 'CB4A-WPM-L4-DN-1', 8, "29/12/2019 até o Presente (Ativo)",
     "BAND1 azul, BAND2 verde, BAND3 vermelho, BAND4 NIR (8 m) · BAND0 pancromática (2 m)", "Nível 4 (ortorretificado), números digitais."),
    ("CBERS-4A WPM · 2 m fusionada RGB (PCA)", 'CB4A-WPM-PCA-FUSED-1', 2, "02/03/2023 até o Presente (Ativo)",
     "RGB fusionado (pancromática + multiespectral)", "Produto fusionado pelo INPE (alta resolução 2m)."),
    ("CBERS-4A MUX · 16 m", 'CB4A-MUX-L4-DN-1', 16, "27/12/2019 até o Presente (Ativo)",
     "BAND5 azul, BAND6 verde, BAND7 vermelho, BAND8 NIR", "Nível 4 (ortorretificado), números digitais."),
    ("CBERS-4A MUX · 16 m reflectância de superfície", 'CB4A-MUX-L4-SR-1', 16, "01/01/2026 até o Presente (Ativo)",
     "BAND5 azul, BAND6 verde, BAND7 vermelho, BAND8 NIR", "Reflectância de superfície (SR)."),
    ("CBERS-4A WFI · 55 m reflectância de superfície", 'CB4A-WFI-L4-SR-1', 55, "01/01/2020 até o Presente (Ativo)",
     "BAND13 azul, BAND14 verde, BAND15 vermelho, BAND16 NIR", "Faixa larga (~684 km), revisita frequente."),
    ("CBERS-4 MUX · 20 m reflectância de superfície", 'CB4-MUX-L4-SR-1', 20, "01/01/2016 até o Presente (Ativo)",
     "BAND5 azul, BAND6 verde, BAND7 vermelho, BAND8 NIR", "Reflectância de superfície (SR)."),
    ("CBERS-4 MUX · 20 m", 'CB4-MUX-L4-DN-1', 20, "09/12/2014 até o Presente (Ativo)",
     "BAND5 azul, BAND6 verde, BAND7 vermelho, BAND8 NIR", "Nível 4, números digitais."),
    ("CBERS-4 WFI · 64 m reflectância de superfície", 'CB4-WFI-L4-SR-1', 64, "01/01/2016 até o Presente (Ativo)",
     "BAND13 azul, BAND14 verde, BAND15 vermelho, BAND16 NIR", "Faixa larga (~866 km)."),
    ("CBERS-4 PAN · 10 m (verde, vermelho, NIR)", 'CB4-PAN10M-L4-DN-1', 10, "09/12/2014 até o Presente (Ativo)",
     "BAND2 verde, BAND3 vermelho, BAND4 NIR", "Sem banda azul: use falsa cor."),
    ("CBERS-4 PAN · 5 m pancromática", 'CB4-PAN5M-L4-DN-1', 5, "09/12/2014 até o Presente (Ativo)",
     "BAND1 pancromática", "Uma banda (tons de cinza)."),
    ("Amazônia-1 WFI · 64 m reflectância de superfície", 'AMZ1-WFI-L4-SR-1', 64, "01/01/2024 até o Presente (Ativo)",
     "BAND1 azul, BAND2 verde, BAND3 vermelho, BAND4 NIR", "Primeiro satélite brasileiro de observação (2021)."),
    ("Amazônia-1 WFI · 64 m", 'AMZ1-WFI-L4-DN-1', 64, "17/03/2021 até o Presente (Ativo)",
     "BAND1 azul, BAND2 verde, BAND3 vermelho, BAND4 NIR", "Nível 4, números digitais."),
    ("CBERS-4A WFI · 55 m", 'CB4A-WFI-L4-DN-1', 55, "04/07/2020 até o Presente (Ativo)",
     "BAND13 azul, BAND14 verde, BAND15 vermelho, BAND16 NIR", "Nível 4, números digitais."),
    ("CBERS-4 WFI · 64 m", 'CB4-WFI-L4-DN-1', 64, "09/12/2014 até o Presente (Ativo)",
     "BAND13 azul, BAND14 verde, BAND15 vermelho, BAND16 NIR", "Nível 4, números digitais."),
    ("Cubo 16 dias · CBERS-4 WFI 64 m (sem nuvens, NDVI/EVI)", 'CBERS4-WFI-16D-2', 64, "01/01/2016 até o Presente (Ativo)",
     "BAND13 azul, BAND14 verde, BAND15 vermelho, BAND16 NIR · NDVI · EVI", "Composição temporal sem nuvens (Brazil Data Cube)."),
    ("Cubo 8 dias · CBERS-4/4A WFI 64 m (sem nuvens, NDVI/EVI)", 'CBERS-WFI-8D-1', 64, "01/01/2020 até o Presente (Ativo)",
     "BAND13 azul, BAND14 verde, BAND15 vermelho, BAND16 NIR · NDVI · EVI", "Composição temporal sem nuvens (Brazil Data Cube)."),
    ("Cubo 2 meses · CBERS-4 MUX 20 m (sem nuvens, NDVI/EVI)", 'CBERS4-MUX-2M-1', 20, "01/01/2016 até o Presente (Ativo)",
     "BAND5 azul, BAND6 verde, BAND7 vermelho, BAND8 NIR · NDVI · EVI", "Composição temporal sem nuvens (Brazil Data Cube)."),
    ("CBERS-4A WPM · 8 m + 2 m PAN (Nível 2)", 'CB4A-WPM-L2-DN-1', 8, "29/12/2019 até o Presente (Ativo)",
     "BAND1 azul, BAND2 verde, BAND3 vermelho, BAND4 NIR (8 m) · BAND0 pancromática (2 m)", "Nível 2: correção sistemática, sem ortorretificação."),
    ("CBERS-4A MUX · 16 m (Nível 2)", 'CB4A-MUX-L2-DN-1', 16, "27/12/2019 até o Presente (Ativo)",
     "BAND5 azul, BAND6 verde, BAND7 vermelho, BAND8 NIR", "Nível 2: correção sistemática, sem ortorretificação."),
    ("CBERS-4A WFI · 55 m (Nível 2)", 'CB4A-WFI-L2-DN-1', 55, "27/12/2019 até o Presente (Ativo)",
     "BAND13 azul, BAND14 verde, BAND15 vermelho, BAND16 NIR", "Nível 2: correção sistemática, sem ortorretificação."),
    ("CBERS-4 MUX · 20 m (Nível 2)", 'CB4-MUX-L2-DN-1', 20, "08/12/2014 até o Presente (Ativo)",
     "BAND5 azul, BAND6 verde, BAND7 vermelho, BAND8 NIR", "Nível 2: correção sistemática, sem ortorretificação."),
    ("CBERS-4 WFI · 64 m (Nível 2)", 'CB4-WFI-L2-DN-1', 64, "14/12/2014 até o Presente (Ativo)",
     "BAND13 azul, BAND14 verde, BAND15 vermelho, BAND16 NIR", "Nível 2: correção sistemática, sem ortorretificação."),
    ("CBERS-4 PAN · 10 m (Nível 2)", 'CB4-PAN10M-L2-DN-1', 10, "09/12/2014 até o Presente (Ativo)",
     "BAND2 verde, BAND3 vermelho, BAND4 NIR", "Nível 2: correção sistemática, sem ortorretificação."),
    ("CBERS-4 PAN · 5 m pancromática (Nível 2)", 'CB4-PAN5M-L2-DN-1', 5, "09/12/2014 até o Presente (Ativo)",
     "BAND1 pancromática", "Nível 2: correção sistemática, sem ortorretificação."),
    ("Amazônia-1 WFI · 64 m (Nível 2)", 'AMZ1-WFI-L2-DN-1', 64, "03/03/2021 até o Presente (Ativo)",
     "BAND1 azul, BAND2 verde, BAND3 vermelho, BAND4 NIR", "Nível 2: correção sistemática, sem ortorretificação."),
    ("Histórico · CBERS-2 CCD · 20 m (2003-2009)", 'CB2-CCD-L2-DN-1', 20, "28/10/2003 a 07/01/2009 (Encerrado)",
     "B1 azul, B2 verde, B3 vermelho, B4 NIR, B5 pancromática (20 m)",
     "Nível 2 sem ortorretificação. Footprint retangular histórico do INPE."),
    ("Histórico · CBERS-2B CCD · 20 m (2007-2010)", 'CB2B-CCD-L2-DN-1', 20, "25/09/2007 a 11/03/2010 (Encerrado)",
     "B1 azul, B2 verde, B3 vermelho, B4 NIR, B5 pancromática (20 m)",
     "Nível 2 sem ortorretificação. Footprint retangular histórico do INPE."),
    ("Histórico · CBERS-2B HRC · 2,5 m pancromática (2007-2010)", 'CB2B-HRC-L2-DN-1', 2.5, "29/09/2007 a 11/03/2010 (Encerrado)",
     "BAND1 pancromática (2,5 m)", "Nível 2. Cenas menores de alta resolução (~27 km)."),
    ("Histórico · CBERS-2 WFI · 260 m (2003-2005)", 'CB2-WFI-L2-DN-1', 260, "22/10/2003 a 13/04/2005 (Encerrado)",
     "BAND1 vermelho, BAND2 NIR", "Nível 2. Apenas vermelho e NIR."),
    ("Histórico · CBERS-2B WFI · 260 m (2007-2010)", 'CB2B-WFI-L2-DN-1', 260, "29/09/2007 a 10/03/2010 (Encerrado)",
     "BAND1 vermelho, BAND2 NIR", "Nível 2. Apenas vermelho e NIR."),
    ("Mosaico Brasil · CBERS-4 WFI (abr-jun/2020, RGB)", 'mosaic-cbers4-brazil-3m-1', 64, "01/04/2020 a 30/06/2020",
     "RGB visual", "Mosaico trimestral de todo o Brasil."),
    ("Mosaico Paraíba · CBERS-4A WFI (jul-set/2020, RGB)", 'mosaic-cbers4a-paraiba-3m-1', 55, "01/07/2020 a 30/09/2020",
     "RGB visual", "Mosaico trimestral do estado da Paraíba."),
]

INPE_SENSOR_DISPLAY = [(label, INPE_PREFIX + cid) for (label, cid, _r, _p, _b, *rest) in INPE_COLLECTIONS]

INPE_SENSOR_METADATA = dict(
    (INPE_PREFIX + cid, {
        'name': label,
        'agency': 'INPE (STAC)',
        'collection': cid,
        'period_display': period,
        'res': f'{res}m',
        'available_bands': bands,
        'notes': notes[0] if notes else '',
        'default_pixel_size': str(int(res) if isinstance(res, (int, float)) and res == int(res) else res),
    }) for (label, cid, res, period, bands, *notes) in INPE_COLLECTIONS
)

INPE_PRODUCTS = [
    ('rgb', 'Cor natural (vermelho, verde, azul)'),
    ('false', 'Falsa cor (NIR, vermelho, verde)'),
    ('multi', 'Multibanda (todas as bandas disponíveis)'),
    ('pan', 'Pancromática (tons de cinza, maior resolução)'),
    ('fused', 'Fusionada RGB (PCA)'),
    ('ndvi', 'NDVI (índice de vegetação)'),
    ('evi', 'EVI (índice de vegetação)'),
    ('visual', 'RGB visual (mosaico)'),
]

_INPE_CUBE_MODES = ['rgb', 'false', 'multi', 'ndvi', 'evi']
INPE_COLLECTION_MODES = {
    'CB4A-WPM-L4-DN-1': ['rgb', 'false', 'multi', 'pan'],
    'CB4A-WPM-L2-DN-1': ['rgb', 'false', 'multi', 'pan'],
    'CB4A-WPM-PCA-FUSED-1': ['fused'],
    'CB4-PAN10M-L4-DN-1': ['false', 'multi'],
    'CB4-PAN10M-L2-DN-1': ['false', 'multi'],
    'CB4-PAN5M-L4-DN-1': ['pan'],
    'CB4-PAN5M-L2-DN-1': ['pan'],
    'CBERS4-WFI-16D-2': _INPE_CUBE_MODES,
    'CBERS-WFI-8D-1': _INPE_CUBE_MODES,
    'CBERS4-MUX-2M-1': _INPE_CUBE_MODES,
    'CB2-CCD-L2-DN-1': ['rgb', 'false', 'multi', 'pan'],
    'CB2B-CCD-L2-DN-1': ['rgb', 'false', 'multi', 'pan'],
    'CB2B-HRC-L2-DN-1': ['pan'],
    'CB2-WFI-L2-DN-1': ['multi'],
    'CB2B-WFI-L2-DN-1': ['multi'],
    'mosaic-cbers4-brazil-3m-1': ['visual'],
    'mosaic-cbers4a-paraiba-3m-1': ['visual'],
}


# SPOT 1-5 (idêntico ao arcmagery_spot.py): (rótulo, grupo, satélites, tipo, resolução, período, bandas)
SPOT_PREFIX = 'SPOT:'
SPOT_GROUPS = [
    ("SPOT 1 a 5 · multiespectral (todas as cenas, 10-20 m)", 'MS', None, 'ms', "10 a 20 m",
     "23/02/1986 a 29/03/2015 (Encerrado)", "XS3 NIR, XS2 vermelho, XS1 verde (+ SWIR no SPOT 4/5)"),
    ("SPOT 1 a 5 · pancromática (todas as cenas, 2,5-10 m)", 'PAN', None, 'pan', "2,5 a 10 m",
     "23/02/1986 a 29/03/2015 (Encerrado)", "PAN (tons de cinza)"),
    ("SPOT 5 · 10 m multiespectral (HRG, 2002-2015)", '5-MS', '5', 'ms', "10 m",
     "19/06/2002 a 29/03/2015 (Encerrado)", "XS3 NIR, XS2 vermelho, XS1 verde, SWIR (20 m reamostrado)"),
    ("SPOT 5 · 5 m / 2,5 m pancromática (HRG, 2002-2015)", '5-PAN', '5', 'pan', "2,5 a 5 m",
     "19/06/2002 a 29/03/2015 (Encerrado)", "PAN (HM 5 m, THR 2,5 m)"),
    ("SPOT 4 · 20 m multiespectral (HRVIR, 1998-2013)", '4-MS', '4', 'ms', "20 m",
     "27/03/1998 a 19/06/2013 (Encerrado)", "XS3 NIR, XS2 vermelho, XS1 verde, SWIR"),
    ("SPOT 4 · 10 m pancromática (HRVIR, 1998-2013)", '4-PAN', '4', 'pan', "10 m",
     "27/03/1998 a 19/06/2013 (Encerrado)", "PAN (banda M, vermelho)"),
    ("SPOT 1, 2 e 3 · 20 m multiespectral (HRV, 1986-2009)", '123-MS', '1,2,3', 'ms', "20 m",
     "23/02/1986 a 25/07/2009 (Encerrado)", "XS3 NIR, XS2 vermelho, XS1 verde"),
    ("SPOT 1, 2 e 3 · 10 m pancromática (HRV, 1986-2009)", '123-PAN', '1,2,3', 'pan', "10 m",
     "23/02/1986 a 25/07/2009 (Encerrado)", "PAN (tons de cinza)"),
]
SPOT_BY_CODE = dict((SPOT_PREFIX + g[1], g) for g in SPOT_GROUPS)

SPOT_SENSOR_DISPLAY = [(label, SPOT_PREFIX + code) for (label, code, _s, _k, _r, _p, _b) in SPOT_GROUPS]

SPOT_SENSOR_METADATA = dict(
    (SPOT_PREFIX + code, {
        'name': label,
        'agency': 'CNES (SPOT World Heritage)',
        'collection': 'GEODES SWH L1A',
        'period_display': period,
        'res': res,
        'available_bands': bands,
        'notes': 'Nível 1A alinhado automaticamente à Esri World Imagery. Download exige a chave do GEODES.',
    }) for (label, code, _s, _k, res, period, bands) in SPOT_GROUPS
)

# O SPOT não tem banda azul: não existe "cor natural"
SPOT_PRODUCTS = [
    ('false', 'Falsa cor (NIR, vermelho, verde) - vegetação em vermelho'),
    ('swir', 'SWIR, NIR, vermelho (só SPOT 4 e 5) - umidade e solo exposto'),
    ('multi', 'Multibanda (todas as bandas, exibida em falsa cor)'),
    ('pan', 'Pancromática (tons de cinza, maior resolução)'),
]


def spot_modes_for(sensor_code):
    g = SPOT_BY_CODE.get(sensor_code)
    if g and g[3] == 'pan':
        return ['pan']
    return ['false', 'swir', 'multi']

GEODES_PORTAL = 'https://geodes-portal.cnes.fr'


# Google Earth Histórico (idêntico ao arcmagery_gehist.py)
GEHIST_PREFIX = 'GEH:'
GEHIST_SENSOR_DISPLAY = [
    ("Google Earth histórico · TODOS os zooms (15 a 20)", GEHIST_PREFIX + 'ALL'),
    ("Google Earth histórico · só o zoom 18 (~0,60 m/pixel)", GEHIST_PREFIX + '18'),
    ("Google Earth histórico · só o zoom 19 (~0,30 m/pixel)", GEHIST_PREFIX + '19'),
    ("Google Earth histórico · só o zoom 20 (~0,15 m/pixel)", GEHIST_PREFIX + '20'),
    ("Google Earth histórico · só o zoom 17 (~1,20 m/pixel)", GEHIST_PREFIX + '17'),
    ("Google Earth histórico · só o zoom 16 (~2,40 m/pixel)", GEHIST_PREFIX + '16'),
    ("Google Earth histórico · só o zoom 15 (~4,80 m/pixel)", GEHIST_PREFIX + '15'),
]

GEHIST_SENSOR_METADATA = {
    GEHIST_PREFIX + 'ALL': {
        'name': 'Google Earth histórico (todos os zooms)',
        'agency': 'Google Earth (Maxar, Airbus, ...)',
        'collection': 'Time Machine z15-z20',
        'period_display': 'conforme a área (em geral 1985 até o presente)',
        'res': '~0,15 a ~4,8 m',
        'available_bands': 'RGB (cor natural, 3 bandas) · grade geográfica EPSG:4326',
        'default_pixel_size': 'por zoom',
    }
}
for z in [18, 19, 20, 17, 16, 15]:
    GEHIST_SENSOR_METADATA[GEHIST_PREFIX + str(z)] = {
        'name': f'Google Earth histórico z{z}',
        'agency': 'Google Earth (Maxar, Airbus, ...)',
        'collection': f'Time Machine z{z}',
        'period_display': 'conforme a área (em geral 1985 até o presente)',
        'res': f'zoom {z}',
        'available_bands': 'RGB (cor natural, 3 bandas) · grade geográfica EPSG:4326',
        'default_pixel_size': 'por zoom',
    }

# Esri Wayback (idêntico ao arcmagery_wayback.py)
WAYBACK_PREFIX = 'EWB:'
WAYBACK_SENSOR_DISPLAY = [
    ("Esri Wayback · TODOS os zooms (15 a 19) · uma linha por versão", WAYBACK_PREFIX + 'ALL'),
    ("Esri Wayback · só o zoom 15 (~4,60 m/pixel)", WAYBACK_PREFIX + '15'),
    ("Esri Wayback · só o zoom 16 (~2,30 m/pixel)", WAYBACK_PREFIX + '16'),
    ("Esri Wayback · só o zoom 17 (~1,15 m/pixel)", WAYBACK_PREFIX + '17'),
    ("Esri Wayback · só o zoom 18 (~0,57 m/pixel)", WAYBACK_PREFIX + '18'),
    ("Esri Wayback · só o zoom 19 (~0,29 m/pixel)", WAYBACK_PREFIX + '19'),
]

WAYBACK_SENSOR_METADATA = {
    WAYBACK_PREFIX + 'ALL': {
        'name': 'Esri Wayback (todos os zooms)',
        'agency': 'Esri World Imagery Wayback',
        'collection': 'Wayback z15-z19',
        'period_display': 'versões publicadas desde 2014 (captura conforme a área)',
        'res': '~0,3 a ~4,6 m',
        'available_bands': 'RGB (cor natural, 3 bandas) · Web Mercator EPSG:3857',
        'default_pixel_size': 'por zoom',
    }
}
for z in [17, 18, 19, 16, 15]:
    WAYBACK_SENSOR_METADATA[WAYBACK_PREFIX + str(z)] = {
        'name': f'Esri Wayback z{z}',
        'agency': 'Esri World Imagery Wayback',
        'collection': f'Wayback z{z}',
        'period_display': 'versões publicadas desde 2014',
        'res': f'zoom {z}',
        'available_bands': 'RGB (cor natural, 3 bandas) · Web Mercator EPSG:3857',
        'default_pixel_size': 'por zoom',
    }


# Mosaicos XYZ da janela "Google Earth / XYZ..." (códigos de backend/xyz_core.PROVIDERS)
# (rótulo, código, zoom máximo, exige aviso de termos de uso, URL para camada XYZ no QGIS ou None)
XYZ_PROVIDERS = [
    ("Google Earth / Satélite", "google", 21, True, "https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}"),
    ("Google Híbrido (satélite + rótulos)", "google-hybrid", 21, True, "https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}"),
    ("Esri World Imagery", "esri", 19, False,
     "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"),
    ("Esri World Imagery (Clarity)", "esri-clarity", 19, False,
     "https://clarity.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"),
    ("Bing Aerial", "bing", 19, True, None),   # quadkey: só download do mosaico
]

TOS_TEXT = ("Google e Bing não liberam o download em massa de tiles: use essas imagens só para consulta e "
            "visualização, e cite a fonte. A Esri também tem termos próprios. Para dados abertos, prefira o "
            "CBERS (INPE), o SPOT (CNES, Etalab 2.0) ou o Earth Engine.")
