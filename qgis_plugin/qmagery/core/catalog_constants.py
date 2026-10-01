# -*- coding: utf-8 -*-
"""
Constantes, metadados de catálogo e definições de sensores idênticos ao ArcMagery.
Compartilhado pela interface do QMagery para garantir 100% de paridade visual e de comportamento.
"""

# Limite de escala operacional
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

# Coleções do STAC INPE (idênticas ao arcmagery_inpe.py)
INPE_PREFIX = 'INPE:'
INPE_COLLECTIONS = [
    ("CBERS-4A WPM · 8 m multiespectral + 2 m PAN", 'CB4A-WPM-L4-DN-1', 8, "29/12/2019 até o Presente (Ativo)",
     "BAND1 azul, BAND2 verde, BAND3 vermelho, BAND4 NIR (8 m) · BAND0 pancromática (2 m)"),
    ("CBERS-4A WPM · 2 m fusionada RGB (PCA)", 'CB4A-WPM-PCA-FUSED-1', 2, "02/03/2023 até o Presente (Ativo)",
     "RGB fusionado (pancromática + multiespectral)"),
    ("CBERS-4A MUX · 16 m", 'CB4A-MUX-L4-DN-1', 16, "27/12/2019 até o Presente (Ativo)",
     "BAND5 azul, BAND6 verde, BAND7 vermelho, BAND8 NIR"),
    ("CBERS-4A MUX · 16 m reflectância de superfície", 'CB4A-MUX-L4-SR-1', 16, "01/01/2026 até o Presente (Ativo)",
     "BAND5 azul, BAND6 verde, BAND7 vermelho, BAND8 NIR"),
    ("CBERS-4A WFI · 55 m reflectância de superfície", 'CB4A-WFI-L4-SR-1', 55, "01/01/2020 até o Presente (Ativo)",
     "BAND13 azul, BAND14 verde, BAND15 vermelho, BAND16 NIR"),
    ("CBERS-4 MUX · 20 m reflectância de superfície", 'CB4-MUX-L4-SR-1', 20, "01/01/2016 até o Presente (Ativo)",
     "BAND5 azul, BAND6 verde, BAND7 vermelho, BAND8 NIR"),
    ("CBERS-4 MUX · 20 m", 'CB4-MUX-L4-DN-1', 20, "09/12/2014 até o Presente (Ativo)",
     "BAND5 azul, BAND6 verde, BAND7 vermelho, BAND8 NIR"),
    ("CBERS-4 WFI · 64 m reflectância de superfície", 'CB4-WFI-L4-SR-1', 64, "01/01/2016 até o Presente (Ativo)",
     "BAND13 azul, BAND14 verde, BAND15 vermelho, BAND16 NIR"),
    ("CBERS-4 PAN · 10 m (verde, vermelho, NIR)", 'CB4-PAN10M-L4-DN-1', 10, "09/12/2014 até o Presente (Ativo)",
     "BAND2 verde, BAND3 vermelho, BAND4 NIR"),
    ("CBERS-4 PAN · 5 m pancromática", 'CB4-PAN5M-L4-DN-1', 5, "09/12/2014 até o Presente (Ativo)",
     "BAND1 pancromática"),
    ("Amazônia-1 WFI · 64 m reflectância de superfície", 'AMZ1-WFI-L4-SR-1', 64, "01/01/2024 até o Presente (Ativo)",
     "BAND1 azul, BAND2 verde, BAND3 vermelho, BAND4 NIR"),
    ("Amazônia-1 WFI · 64 m", 'AMZ1-WFI-L4-DN-1', 64, "17/03/2021 até o Presente (Ativo)",
     "BAND1 azul, BAND2 verde, BAND3 vermelho, BAND4 NIR"),
    ("CBERS-4A WFI · 55 m", 'CB4A-WFI-L4-DN-1', 55, "04/07/2020 até o Presente (Ativo)",
     "BAND13 azul, BAND14 verde, BAND15 vermelho, BAND16 NIR"),
    ("CBERS-4 WFI · 64 m", 'CB4-WFI-L4-DN-1', 64, "09/12/2014 até o Presente (Ativo)",
     "BAND13 azul, BAND14 verde, BAND15 vermelho, BAND16 NIR"),
]

INPE_SENSOR_DISPLAY = [(label, INPE_PREFIX + cid) for (label, cid, _r, _p, _b) in INPE_COLLECTIONS]

INPE_SENSOR_METADATA = dict(
    (INPE_PREFIX + cid, {
        'name': label,
        'agency': 'INPE (STAC)',
        'collection': cid,
        'period_display': period,
        'res': f'{res}m',
        'available_bands': bands,
        'default_pixel_size': str(res),
    }) for (label, cid, res, period, bands) in INPE_COLLECTIONS
)

# SPOT 1-5 (idêntico ao arcmagery_spot.py)
SPOT_PREFIX = 'SPOT:'
SPOT_GROUPS = [
    ("SPOT 1 a 5 · multiespectral (todas as cenas, 10-20 m)", 'MS', "10 a 20 m", "23/02/1986 a 29/03/2015 (Encerrado)", "XS3 NIR, XS2 vermelho, XS1 verde (+ SWIR no SPOT 4/5)"),
    ("SPOT 1 a 5 · pancromática (todas as cenas, 2,5-10 m)", 'PAN', "2,5 a 10 m", "23/02/1986 a 29/03/2015 (Encerrado)", "PAN (tons de cinza)"),
    ("SPOT 5 · 10 m multiespectral (HRG, 2002-2015)", '5-MS', "10 m", "19/06/2002 a 29/03/2015 (Encerrado)", "XS3 NIR, XS2 vermelho, XS1 verde, SWIR (20 m reamostrado)"),
    ("SPOT 5 · 5 m / 2,5 m pancromática (HRG, 2002-2015)", '5-PAN', "2,5 a 5 m", "19/06/2002 a 29/03/2015 (Encerrado)", "PAN (HM 5 m, THR 2,5 m)"),
    ("SPOT 4 · 20 m multiespectral (HRVIR, 1998-2013)", '4-MS', "20 m", "27/03/1998 a 19/06/2013 (Encerrado)", "XS3 NIR, XS2 vermelho, XS1 verde, SWIR"),
    ("SPOT 4 · 10 m pancromática (HRVIR, 1998-2013)", '4-PAN', "10 m", "27/03/1998 a 19/06/2013 (Encerrado)", "PAN (banda M, vermelho)"),
    ("SPOT 1, 2 e 3 · 20 m multiespectral (HRV, 1986-2009)", '123-MS', "20 m", "23/02/1986 a 25/07/2009 (Encerrado)", "XS3 NIR, XS2 vermelho, XS1 verde"),
    ("SPOT 1, 2 e 3 · 10 m pancromática (HRV, 1986-2009)", '123-PAN', "10 m", "23/02/1986 a 25/07/2009 (Encerrado)", "PAN (tons de cinza)"),
]

SPOT_SENSOR_DISPLAY = [(label, SPOT_PREFIX + code) for (label, code, _r, _p, _b) in SPOT_GROUPS]

SPOT_SENSOR_METADATA = dict(
    (SPOT_PREFIX + code, {
        'name': label,
        'agency': 'CNES (SPOT World Heritage)',
        'collection': f'GEODES SWH {code}',
        'period_display': period,
        'res': res,
        'available_bands': bands,
        'default_pixel_size': 'nativa',
    }) for (label, code, res, period, bands) in SPOT_GROUPS
)

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
    ("Esri Wayback · só o zoom 17 (~1,15 m/pixel)", WAYBACK_PREFIX + '17'),
    ("Esri Wayback · só o zoom 18 (~0,57 m/pixel)", WAYBACK_PREFIX + '18'),
    ("Esri Wayback · só o zoom 19 (~0,29 m/pixel)", WAYBACK_PREFIX + '19'),
    ("Esri Wayback · só o zoom 16 (~2,30 m/pixel)", WAYBACK_PREFIX + '16'),
    ("Esri Wayback · só o zoom 15 (~4,60 m/pixel)", WAYBACK_PREFIX + '15'),
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

# Fontes XYZ Mosaicos (para a janela auxiliar Google Earth / XYZ...)
XYZ_PROVIDERS = [
    ("Google Earth / Satélite", "google", 21, True),
    ("Google Híbrido (satélite + rótulos)", "google-hybrid", 21, True),
    ("Esri World Imagery", "esri", 19, False),
    ("Esri World Imagery (Clarity)", "esri-clarity", 19, False),
    ("Bing Aerial", "bing", 19, True),
]

# Composições GEE padrão
GEE_COMPOSITIONS = {
    'S2': [
        ('432', 'COR NATURAL - 432'),
        ('843', 'FALSA COR (VEGETAÇÃO) - 843'),
        ('1284', 'AGRICULTURA - 12.8.4'),
        ('1184', 'ANÁLISE DA VEGETAÇÃO - 11.8.4'),
        ('128a4', 'INFRAVERMELHO ONDA CURTA - 12.8a.4'),
        ('8114', 'PENETRAÇÃO ATMOSFÉRICA - 8.11.4'),
        ('MB_10', 'MULTIBANDA - 10 BANDAS PRINCIPAIS (B2 a B12)'),
        ('MB_12', 'MULTIBANDA - 12 BANDAS COMPLETAS (B1 a B12)'),
        ('NDVI', 'ÍNDICE - NDVI (Vegetação: B8-B4)'),
        ('NDWI', 'ÍNDICE - NDWI (Água: B3-B8)'),
        ('NDMI', 'ÍNDICE - NDMI (Umidade: B8-B11)'),
        ('NBR', 'ÍNDICE - NBR (Queimadas: B8-B12)'),
        ('EVI', 'ÍNDICE - EVI (Vegetação Realçada)'),
        ('SAVI', 'ÍNDICE - SAVI (Ajustado ao Solo)'),
        ('CUSTOM_BANDS', 'BANDAS PERSONALIZADAS (Digite na caixa abaixo)'),
        ('CUSTOM_MATH', 'ÍNDICE - FÓRMULA MATEMÁTICA (ex: (B8-B4)/(B8+B4))'),
    ],
    'L8': [
        ('432', 'COR NATURAL - 432'),
        ('543', 'COR INFRAVERMELHA (VEGETAÇÃO) - 543'),
        ('652', 'AGRICULTURA - 652'),
        ('765', 'PENETRAÇÃO ATMOSFÉRICA - 765'),
        ('754', 'INFRAVERMELHO ONDA CURTA - 754'),
        ('654', 'ANÁLISE DA VEGETAÇÃO - 654'),
        ('MB_8', 'MULTIBANDA - 8 BANDAS (SR_B1 a SR_B7 + ST_B10 Térmica)'),
        ('MB_7', 'MULTIBANDA - 7 BANDAS ÓPTICAS (SR_B1 a SR_B7)'),
        ('10', 'TÉRMICA - BANDA 10 (Temperatura de Superfície em °C)'),
        ('NDVI', 'ÍNDICE - NDVI (Vegetação: NIR-RED)'),
        ('NDWI', 'ÍNDICE - NDWI (Água: GREEN-NIR)'),
        ('NDMI', 'ÍNDICE - NDMI (Umidade: NIR-SWIR1)'),
        ('NBR', 'ÍNDICE - NBR (Queimadas: NIR-SWIR2)'),
        ('EVI', 'ÍNDICE - EVI (Vegetação Realçada)'),
        ('SAVI', 'ÍNDICE - SAVI (Ajustado ao Solo)'),
        ('CUSTOM_BANDS', 'BANDAS PERSONALIZADAS (Digite na caixa abaixo)'),
        ('CUSTOM_MATH', 'ÍNDICE - FÓRMULA MATEMÁTICA'),
    ]
}
