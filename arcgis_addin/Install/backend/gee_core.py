# -*- coding: utf-8 -*-
"""
Motor de Processamento Google Earth Engine (Python 3)
Compatível com earthengine-api.
Baseado no script de seleção e mosaico GEE para Mato Grosso / Brasil.
"""

import os
import sys
import json
import time
import math
import shutil
import re
import subprocess
import concurrent.futures
import urllib.request
import tempfile
import ee

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gee_config.json")

COLLECTIONS = {
    'S2': 'COPERNICUS/S2_SR_HARMONIZED',
    'L8': 'LANDSAT/LC08/C02/T1_L2',
    'L7': 'LANDSAT/LE07/C02/T1_L2',
    'L5': 'LANDSAT/LT05/C02/T1_L2',
    'L4': 'LANDSAT/LT04/C02/T1_L2',
    'L3': 'LANDSAT/LM03/C02/T1',
    'L2': 'LANDSAT/LM02/C02/T1',
    'L1': 'LANDSAT/LM01/C02/T1'
}

MULTIBAND_DEFAULT_BANDS = {
    'S2': ['B1', 'B2', 'B3', 'B4', 'B5', 'B6', 'B7', 'B8', 'B8A', 'B9', 'B11', 'B12'],
    'L8': ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6', 'SR_B7', 'ST_B10'],
    'L7': ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B7', 'ST_B6'],
    'L5': ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B7', 'ST_B6'],
    'L4': ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B7', 'ST_B6'],
    'L3': ['B4', 'B5', 'B6', 'B7'],
    'L2': ['B4', 'B5', 'B6', 'B7'],
    'L1': ['B4', 'B5', 'B6', 'B7']
}

VALID_SENSOR_BANDS = {
    'S2': ['B1', 'B2', 'B3', 'B4', 'B5', 'B6', 'B7', 'B8', 'B8A', 'B9', 'B11', 'B12'],
    'L8': ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6', 'SR_B7', 'ST_B10'],
    'L7': ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B7', 'ST_B6'],
    'L5': ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B7', 'ST_B6'],
    'L4': ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B7', 'ST_B6'],
    'L3': ['B4', 'B5', 'B6', 'B7'],
    'L2': ['B4', 'B5', 'B6', 'B7'],
    'L1': ['B4', 'B5', 'B6', 'B7']
}

def get_image_collection(sensor):
    """Retorna colecao de imagens incluindo Tier 1 e Tier 2 para Landsat para garantir busca de todas as datas"""
    if sensor == 'S2':
        return ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
    elif sensor == 'L8':
        t1 = ee.ImageCollection('LANDSAT/LC08/C02/T1_L2')
        t2 = ee.ImageCollection('LANDSAT/LC08/C02/T2_L2')
        l9_t1 = ee.ImageCollection('LANDSAT/LC09/C02/T1_L2')
        l9_t2 = ee.ImageCollection('LANDSAT/LC09/C02/T2_L2')
        return t1.merge(t2).merge(l9_t1).merge(l9_t2)
    elif sensor == 'L7':
        t1 = ee.ImageCollection('LANDSAT/LE07/C02/T1_L2')
        t2 = ee.ImageCollection('LANDSAT/LE07/C02/T2_L2')
        return t1.merge(t2)
    elif sensor == 'L5':
        t1 = ee.ImageCollection('LANDSAT/LT05/C02/T1_L2')
        t2 = ee.ImageCollection('LANDSAT/LT05/C02/T2_L2')
        return t1.merge(t2)
    elif sensor == 'L4':
        t1 = ee.ImageCollection('LANDSAT/LT04/C02/T1_L2')
        t2 = ee.ImageCollection('LANDSAT/LT04/C02/T2_L2')
        return t1.merge(t2)
    elif sensor == 'L3':
        t1 = ee.ImageCollection('LANDSAT/LM03/C02/T1')
        t2 = ee.ImageCollection('LANDSAT/LM03/C02/T2')
        return t1.merge(t2)
    elif sensor == 'L2':
        t1 = ee.ImageCollection('LANDSAT/LM02/C02/T1')
        t2 = ee.ImageCollection('LANDSAT/LM02/C02/T2')
        return t1.merge(t2)
    elif sensor == 'L1':
        t1 = ee.ImageCollection('LANDSAT/LM01/C02/T1')
        t2 = ee.ImageCollection('LANDSAT/LM01/C02/T2')
        return t1.merge(t2)
    else:
        return ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')

COMPOSITIONS = {
    'L8': {
        '432': {'label': 'COR NATURAL - 432', 'bands': ['SR_B4', 'SR_B3', 'SR_B2']},
        '764': {'label': 'FALSA COR - 764', 'bands': ['SR_B7', 'SR_B6', 'SR_B4']},
        '543': {'label': 'COR INFRAVERMELHA (VEGETACAO) - 543', 'bands': ['SR_B5', 'SR_B4', 'SR_B3']},
        '652': {'label': 'AGRICULTURA - 652', 'bands': ['SR_B6', 'SR_B5', 'SR_B2']},
        '765': {'label': 'PENETRACAO ATMOSFERICA - 765', 'bands': ['SR_B7', 'SR_B6', 'SR_B5']},
        '562': {'label': 'SAUDE DA VEGETACAO - 562', 'bands': ['SR_B5', 'SR_B6', 'SR_B2']},
        '564': {'label': 'SOLO/AGUA - 564', 'bands': ['SR_B5', 'SR_B6', 'SR_B4']},
        '753': {'label': 'NATURAL COM REMOCAO ATMOSFERICA - 753', 'bands': ['SR_B7', 'SR_B5', 'SR_B3']},
        '754': {'label': 'INFRAVERMELHO ONDA CURTA - 754', 'bands': ['SR_B7', 'SR_B5', 'SR_B4']},
        '654': {'label': 'ANALISE DA VEGETACAO - 654', 'bands': ['SR_B6', 'SR_B5', 'SR_B4']},
        'MB_8': {'label': 'MULTIBANDA - 8 BANDAS (SR_B1 a SR_B7 + ST_B10 Termica)', 'bands': ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6', 'SR_B7', 'ST_B10'], 'multiband': True},
        'MB_7': {'label': 'MULTIBANDA - 7 BANDAS OPTICAS (SR_B1 a SR_B7)', 'bands': ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6', 'SR_B7'], 'multiband': True},
        'MB_6': {'label': 'MULTIBANDA - 6 BANDAS PRINCIPAIS (SR_B2 a SR_B7)', 'bands': ['SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6', 'SR_B7'], 'multiband': True},
        '10':   {'label': 'TERMICA - BANDA 10 (Temperatura de Superficie em C)', 'bands': ['ST_B10'], 'is_index': True},
        'NDVI': {'label': 'INDICE - NDVI (Vegetacao: NIR-RED)', 'bands': ['SR_B5', 'SR_B4'], 'is_index': True},
        'NDWI': {'label': 'INDICE - NDWI (Agua: GREEN-NIR)', 'bands': ['SR_B3', 'SR_B5'], 'is_index': True},
        'NDMI': {'label': 'INDICE - NDMI (Umidade: NIR-SWIR1)', 'bands': ['SR_B5', 'SR_B6'], 'is_index': True},
        'NBR':  {'label': 'INDICE - NBR (Queimadas: NIR-SWIR2)', 'bands': ['SR_B5', 'SR_B7'], 'is_index': True},
        'EVI':  {'label': 'INDICE - EVI (Vegetacao Realcada)', 'bands': ['SR_B5', 'SR_B4', 'SR_B2'], 'is_index': True},
        'SAVI': {'label': 'INDICE - SAVI (Ajustado ao Solo)', 'bands': ['SR_B5', 'SR_B4'], 'is_index': True},
        'CUSTOM_BANDS': {'label': 'BANDAS PERSONALIZADAS (Digite na caixa abaixo: ex: SR_B5,SR_B4,SR_B3)', 'bands': []},
        'CUSTOM_MATH': {'label': 'INDICE - FORMULA MATEMATICA (ex: (SR_B5-SR_B4)/(SR_B5+SR_B4))', 'bands': [], 'is_index': True, 'is_custom': True}
    },
    'L7': {
        '321': {'label': 'COR NATURAL - 321', 'bands': ['SR_B3', 'SR_B2', 'SR_B1']},
        '753': {'label': 'FALSA COR - 753', 'bands': ['SR_B7', 'SR_B5', 'SR_B3']},
        '432': {'label': 'COR INFRAVERMELHA (VEGETACAO) - 432', 'bands': ['SR_B4', 'SR_B3', 'SR_B2']},
        '541': {'label': 'AGRICULTURA - 541', 'bands': ['SR_B5', 'SR_B4', 'SR_B1']},
        '754': {'label': 'PENETRACAO ATMOSFERICA - 754', 'bands': ['SR_B7', 'SR_B5', 'SR_B4']},
        '451': {'label': 'SAUDE DA VEGETACAO - 451', 'bands': ['SR_B4', 'SR_B5', 'SR_B1']},
        '453': {'label': 'SOLO/AGUA - 453', 'bands': ['SR_B4', 'SR_B5', 'SR_B3']},
        '742': {'label': 'NATURAL COM REMOCAO ATMOSFERICA - 742', 'bands': ['SR_B7', 'SR_B4', 'SR_B2']},
        '743': {'label': 'INFRAVERMELHO ONDA CURTA - 743', 'bands': ['SR_B7', 'SR_B4', 'SR_B3']},
        '543': {'label': 'ANALISE DA VEGETACAO - 543', 'bands': ['SR_B5', 'SR_B4', 'SR_B3']},
        'MB_7': {'label': 'MULTIBANDA - 7 BANDAS (SR_B1 a SR_B5, SR_B7 + ST_B6 Termica)', 'bands': ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B7', 'ST_B6'], 'multiband': True},
        'MB_6': {'label': 'MULTIBANDA - 6 BANDAS OPTICAS (SR_B1 a SR_B5, SR_B7)', 'bands': ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B7'], 'multiband': True},
        '6':    {'label': 'TERMICA - BANDA 6 (Temperatura de Superficie em C)', 'bands': ['ST_B6'], 'is_index': True},
        'NDVI': {'label': 'INDICE - NDVI (Vegetacao: NIR-RED)', 'bands': ['SR_B4', 'SR_B3'], 'is_index': True},
        'NDWI': {'label': 'INDICE - NDWI (Agua: GREEN-NIR)', 'bands': ['SR_B2', 'SR_B4'], 'is_index': True},
        'NDMI': {'label': 'INDICE - NDMI (Umidade: NIR-SWIR1)', 'bands': ['SR_B4', 'SR_B5'], 'is_index': True},
        'NBR':  {'label': 'INDICE - NBR (Queimadas: NIR-SWIR2)', 'bands': ['SR_B4', 'SR_B7'], 'is_index': True},
        'EVI':  {'label': 'INDICE - EVI (Vegetacao Realcada)', 'bands': ['SR_B4', 'SR_B3', 'SR_B1'], 'is_index': True},
        'SAVI': {'label': 'INDICE - SAVI (Ajustado ao Solo)', 'bands': ['SR_B4', 'SR_B3'], 'is_index': True},
        'CUSTOM_BANDS': {'label': 'BANDAS PERSONALIZADAS (Digite na caixa abaixo: ex: SR_B4,SR_B3,SR_B2)', 'bands': []},
        'CUSTOM_MATH': {'label': 'INDICE - FORMULA MATEMATICA (ex: (SR_B4-SR_B3)/(SR_B4+SR_B3))', 'bands': [], 'is_index': True, 'is_custom': True}
    },
    'L5': {
        '321': {'label': 'COR NATURAL - 321', 'bands': ['SR_B3', 'SR_B2', 'SR_B1']},
        '753': {'label': 'FALSA COR - 753', 'bands': ['SR_B7', 'SR_B5', 'SR_B3']},
        '432': {'label': 'COR INFRAVERMELHA (VEGETACAO) - 432', 'bands': ['SR_B4', 'SR_B3', 'SR_B2']},
        '541': {'label': 'AGRICULTURA - 541', 'bands': ['SR_B5', 'SR_B4', 'SR_B1']},
        '754': {'label': 'PENETRACAO ATMOSFERICA - 754', 'bands': ['SR_B7', 'SR_B5', 'SR_B4']},
        '451': {'label': 'SAUDE DA VEGETACAO - 451', 'bands': ['SR_B4', 'SR_B5', 'SR_B1']},
        '453': {'label': 'SOLO/AGUA - 453', 'bands': ['SR_B4', 'SR_B5', 'SR_B3']},
        '742': {'label': 'NATURAL COM REMOCAO ATMOSFERICA - 742', 'bands': ['SR_B7', 'SR_B4', 'SR_B2']},
        '743': {'label': 'INFRAVERMELHO ONDA CURTA - 743', 'bands': ['SR_B7', 'SR_B4', 'SR_B3']},
        '543': {'label': 'ANALISE DA VEGETACAO - 543', 'bands': ['SR_B5', 'SR_B4', 'SR_B3']},
        'MB_7': {'label': 'MULTIBANDA - 7 BANDAS (SR_B1 a SR_B5, SR_B7 + ST_B6 Termica)', 'bands': ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B7', 'ST_B6'], 'multiband': True},
        'MB_6': {'label': 'MULTIBANDA - 6 BANDAS OPTICAS (SR_B1 a SR_B5, SR_B7)', 'bands': ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B7'], 'multiband': True},
        '6':    {'label': 'TERMICA - BANDA 6 (Temperatura de Superficie em C)', 'bands': ['ST_B6'], 'is_index': True},
        'NDVI': {'label': 'INDICE - NDVI (Vegetacao: NIR-RED)', 'bands': ['SR_B4', 'SR_B3'], 'is_index': True},
        'NDWI': {'label': 'INDICE - NDWI (Agua: GREEN-NIR)', 'bands': ['SR_B2', 'SR_B4'], 'is_index': True},
        'NDMI': {'label': 'INDICE - NDMI (Umidade: NIR-SWIR1)', 'bands': ['SR_B4', 'SR_B5'], 'is_index': True},
        'NBR':  {'label': 'INDICE - NBR (Queimadas: NIR-SWIR2)', 'bands': ['SR_B4', 'SR_B7'], 'is_index': True},
        'EVI':  {'label': 'INDICE - EVI (Vegetacao Realcada)', 'bands': ['SR_B4', 'SR_B3', 'SR_B1'], 'is_index': True},
        'SAVI': {'label': 'INDICE - SAVI (Ajustado ao Solo)', 'bands': ['SR_B4', 'SR_B3'], 'is_index': True},
        'CUSTOM_BANDS': {'label': 'BANDAS PERSONALIZADAS (Digite na caixa abaixo: ex: SR_B4,SR_B3,SR_B2)', 'bands': []},
        'CUSTOM_MATH': {'label': 'INDICE - FORMULA MATEMATICA (ex: (SR_B4-SR_B3)/(SR_B4+SR_B3))', 'bands': [], 'is_index': True, 'is_custom': True}
    },
    'L1': {
        '754': {'label': 'FALSA COR INFRAVERMELHA (PADRAO MSS) - 754', 'bands': ['B7', 'B5', 'B4']},
        '654': {'label': 'FALSA COR VEGETACAO - 654', 'bands': ['B6', 'B5', 'B4']},
        '764': {'label': 'PENETRACAO/SOLO - 764', 'bands': ['B7', 'B6', 'B4']},
        '765': {'label': 'ANALISE DE BIOMASSA - 765', 'bands': ['B7', 'B6', 'B5']},
        'MB_4': {'label': 'MULTIBANDA - 4 BANDAS MSS (B4, B5, B6, B7)', 'bands': ['B4', 'B5', 'B6', 'B7'], 'multiband': True},
        'NDVI': {'label': 'INDICE - NDVI (Vegetacao: B7-B5)', 'bands': ['B7', 'B5'], 'is_index': True},
        'NDWI': {'label': 'INDICE - NDWI (Agua: B4-B7)', 'bands': ['B4', 'B7'], 'is_index': True},
        'CUSTOM_BANDS': {'label': 'BANDAS PERSONALIZADAS (Digite na caixa abaixo: ex: B7,B5,B4)', 'bands': []},
        'CUSTOM_MATH': {'label': 'INDICE - FORMULA MATEMATICA (ex: (B7-B5)/(B7+B5))', 'bands': [], 'is_index': True, 'is_custom': True}
    },
    'S2': {
        '432': {'label': 'COR NATURAL - 4.3.2', 'bands': ['B4', 'B3', 'B2']},
        '12114': {'label': 'FALSA COR - 12.11.4', 'bands': ['B12', 'B11', 'B4']},
        '843': {'label': 'COR INFRAVERMELHA (VEGETACAO) - 8.4.3', 'bands': ['B8', 'B4', 'B3']},
        '8a43': {'label': 'COR INFRAVERMELHA (VEGETACAO) - 8a.4.3', 'bands': ['B8A', 'B4', 'B3']},
        '1182': {'label': 'AGRICULTURA - 11.8.2', 'bands': ['B11', 'B8', 'B2']},
        '118a2': {'label': 'AGRICULTURA - 11.8a.2', 'bands': ['B11', 'B8A', 'B2']},
        '12118': {'label': 'PENETRACAO ATMOSFERICA - 12.11.8', 'bands': ['B12', 'B11', 'B8']},
        '12118a': {'label': 'PENETRACAO ATMOSFERICA - 12.11.8a', 'bands': ['B12', 'B11', 'B8A']},
        '8112': {'label': 'SAUDE DA VEGETACAO - 8.11.2', 'bands': ['B8', 'B11', 'B2']},
        '8a112': {'label': 'SAUDE DA VEGETACAO - 8a.11.2', 'bands': ['B8A', 'B11', 'B2']},
        '8114': {'label': 'SOLO/AGUA - 8.11.4', 'bands': ['B8', 'B11', 'B4']},
        '8a114': {'label': 'SOLO/AGUA - 8a.11.4', 'bands': ['B8A', 'B11', 'B4']},
        '1283': {'label': 'NATURAL COM REMOCAO ATMOSFERICA - 12.8.3', 'bands': ['B12', 'B8', 'B3']},
        '128a3': {'label': 'NATURAL COM REMOCAO ATMOSFERICA - 12.8a.3', 'bands': ['B12', 'B8A', 'B3']},
        '1284': {'label': 'INFRAVERMELHO ONDA CURTA - 12.8.4', 'bands': ['B12', 'B8', 'B4']},
        '128a4': {'label': 'INFRAVERMELHO ONDA CURTA - 12.8a.4', 'bands': ['B12', 'B8A', 'B4']},
        '1184': {'label': 'ANALISE DA VEGETACAO - 11.8.4', 'bands': ['B11', 'B8', 'B4']},
        '118a4': {'label': 'ANALISE DA VEGETACAO - 11.8a.4', 'bands': ['B11', 'B8A', 'B4']},
        '483': {'label': 'ANALISE DA VEGETACAO - 4.8.3', 'bands': ['B4', 'B8', 'B3']},
        'MB_10': {'label': 'MULTIBANDA - 10 BANDAS PRINCIPAIS (B2 a B12)', 'bands': ['B2', 'B3', 'B4', 'B5', 'B6', 'B7', 'B8', 'B8A', 'B11', 'B12'], 'multiband': True},
        'MB_6': {'label': 'MULTIBANDA - 6 BANDAS VNIR/SWIR (B2, B3, B4, B8, B11, B12)', 'bands': ['B2', 'B3', 'B4', 'B8', 'B11', 'B12'], 'multiband': True},
        'MB_12': {'label': 'MULTIBANDA - 12 BANDAS COMPLETAS (B1 a B12)', 'bands': ['B1', 'B2', 'B3', 'B4', 'B5', 'B6', 'B7', 'B8', 'B8A', 'B9', 'B11', 'B12'], 'multiband': True},
        'NDVI': {'label': 'INDICE - NDVI (Vegetacao: B8-B4)', 'bands': ['B8', 'B4'], 'is_index': True},
        'NDWI': {'label': 'INDICE - NDWI (Agua: B3-B8)', 'bands': ['B3', 'B8'], 'is_index': True},
        'NDMI': {'label': 'INDICE - NDMI (Umidade: B8-B11)', 'bands': ['B8', 'B11'], 'is_index': True},
        'NBR':  {'label': 'INDICE - NBR (Queimadas: B8-B12)', 'bands': ['B8', 'B12'], 'is_index': True},
        'EVI':  {'label': 'INDICE - EVI (Vegetacao Realcada)', 'bands': ['B8', 'B4', 'B2'], 'is_index': True},
        'SAVI': {'label': 'INDICE - SAVI (Ajustado ao Solo)', 'bands': ['B8', 'B4'], 'is_index': True},
        'CUSTOM_BANDS': {'label': 'BANDAS PERSONALIZADAS (Digite na caixa abaixo: ex: B8,B4,B3)', 'bands': []},
        'CUSTOM_MATH': {'label': 'INDICE - FORMULA MATEMATICA (ex: (B8-B4)/(B8+B4))', 'bands': [], 'is_index': True, 'is_custom': True}
    }
}
COMPOSITIONS['L4'] = COMPOSITIONS['L5']
COMPOSITIONS['L3'] = COMPOSITIONS['L1']
COMPOSITIONS['L2'] = COMPOSITIONS['L1']

def get_user_gee_config_file():
    appdata = os.environ.get('APPDATA') or os.path.expanduser('~')
    arcgee_dir = os.path.join(appdata, 'ArcGEE')
    os.makedirs(arcgee_dir, exist_ok=True)
    return os.path.join(arcgee_dir, 'gee_config.json')

def load_config():
    # 1. Config do usuario em %APPDATA%\ArcGEE\gee_config.json (nao sobrescrito em atualizacoes)
    user_cfg = get_user_gee_config_file()
    if os.path.exists(user_cfg):
        try:
            with open(user_cfg, 'r', encoding='utf-8') as f:
                d = json.load(f)
                if d.get('project'):
                    return d
        except Exception:
            pass
    # 2. Fallback: arquivo local de exemplo/pacote
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                d = json.load(f)
                if d.get('project'):
                    return d
        except Exception:
            pass
    return {'project': ''}

def save_config(cfg):
    user_cfg = get_user_gee_config_file()
    try:
        with open(user_cfg, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2)
        return True
    except Exception as e:
        sys.stderr.write("[ArcGEE] Erro salvando config: %s\n" % str(e))
        return False

CREDENTIALS_PATH = os.path.expanduser('~/.config/earthengine/credentials')

def has_credentials():
    return os.path.exists(CREDENTIALS_PATH)

def init_gee(project=None):
    if not has_credentials():
        return False, "Nao autenticado no Google Earth Engine. Clique no botao 'Autenticar' para conectar sua conta Google."

    cfg = load_config()
    proj = project or cfg.get('project') or os.environ.get('EARTHENGINE_PROJECT') or None
    try:
        if proj:
            ee.Initialize(project=proj)
        else:
            ee.Initialize()
        return True, "Conectado ao Google Earth Engine! (Projeto: %s)" % (proj or "Padrao")
    except Exception as e:
        err_msg = str(e)
        if "API has not been used" in err_msg or "SERVICE_DISABLED" in err_msg:
            return False, "A API do Earth Engine nao esta habilitada no projeto '%s'. Habilite no Google Cloud Console ou informe outro ID de projeto." % (proj or "")
        return False, err_msg

def authenticate_gee(project=None):
    try:
        ee.Authenticate(auth_mode='localhost')
        if project:
            cfg = load_config()
            cfg['project'] = project
            save_config(cfg)
        return init_gee(project)
    except Exception as e:
        return False, str(e)

# Alias de compatibilidade
init_ee = init_gee

def apply_sensor_scaling(img, sensor):
    if sensor == 'S2':
        return img.divide(10000.0)
    elif sensor in ['L8', 'L7', 'L5', 'L4']:
        return img.multiply(0.0000275).add(-0.2)
    else:
        # MSS L1-3
        return img.divide(255.0)

INDEX_PALETTES = {
    'NDVI': {'min': -0.2, 'max': 0.85, 'palette': ['#0000ff', '#ffffff', '#e0f3f8', '#fee08b', '#d9ef8b', '#91cf60', '#1a9850', '#00441b']},
    'NDWI': {'min': -0.5, 'max': 0.5, 'palette': ['#8c510a', '#d8b365', '#f6e8c3', '#c7eae5', '#5ab4ac', '#01665e']},
    'NDMI': {'min': -0.5, 'max': 0.5, 'palette': ['#8c510a', '#d8b365', '#f6e8c3', '#c7eae5', '#5ab4ac', '#01665e']},
    'NBR':  {'min': -0.4, 'max': 0.8, 'palette': ['#000000', '#d73027', '#f46d43', '#fdae61', '#fee08b', '#d9ef8b', '#a6d96a', '#1a9850']},
    'EVI':  {'min': -0.1, 'max': 0.8, 'palette': ['#0000ff', '#ffffff', '#fee08b', '#d9ef8b', '#91cf60', '#1a9850']},
    'SAVI': {'min': -0.1, 'max': 0.8, 'palette': ['#0000ff', '#ffffff', '#fee08b', '#d9ef8b', '#91cf60', '#1a9850']},
    '10':   {'min': 10.0, 'max': 50.0, 'palette': ['#0000ff', '#00ffff', '#ffff00', '#ff0000', '#7f0000']},
    '6':    {'min': 10.0, 'max': 50.0, 'palette': ['#0000ff', '#00ffff', '#ffff00', '#ff0000', '#7f0000']},
    'CUSTOM_MATH': {'min': -1.0, 'max': 1.0, 'palette': ['#0000ff', '#ffffff', '#ff0000']}
}

class RasterHealthCheckError(Exception):
    """Exceção levantada quando um raster gerado falha na validação atômica de integridade."""
    def __init__(self, message, diagnostics=None):
        super(RasterHealthCheckError, self).__init__(message)
        self.message = message
        self.diagnostics = diagnostics or {}

    def __str__(self):
        diag_str = json.dumps(self.diagnostics, indent=2, ensure_ascii=False) if self.diagnostics else ""
        return "%s\n[Health Check Diagnósticos]:\n%s" % (self.message, diag_str)

def is_math_expr(text):
    """
    Verifica de forma robusta se a string de entrada representa uma expressao/formula
    matematica (ex: '(SR_B5 - SR_B4) / (SR_B5 + SR_B4)') ou uma lista de bandas
    (ex: 'SR_B3, SR_B4, SR_B5, SR_B7' ou '(SR_B3, SR_B4, SR_B5, SR_B7)' ou 'B3-B5, B7').
    """
    if not text:
        return False
    t = str(text).strip()
    if not t:
        return False

    # Remover parenteses ou colchetes externos se envolverem a expressao inteira
    while (t.startswith('(') and t.endswith(')')) or (t.startswith('[') and t.endswith(']')):
        t = t[1:-1].strip()

    # Operadores inequivocos de operacao matematica
    if any(op in t for op in ['+', '*', '/', '^', '%']):
        return True

    # Funcoes matematicas comuns (sqrt, exp, log, min, max, etc.)
    if re.search(r'\b(sqrt|exp|log|log10|sin|cos|tan|min|max|abs)\s*\(', t, re.IGNORECASE):
        return True

    # Tratar ocorrencias do caractere '-': verificar se e intervalo de bandas (ex: B3-B7 ou SR_B3-SR_B7)
    # ou operacao aritmetica de subtracao (ex: B8-B4 ou B5-B4)
    if '-' in t:
        parts = [p.strip() for p in re.split(r'[,;\s]+', t) if p.strip()]
        for p in parts:
            if '-' in p:
                sub = p.split('-')
                if len(sub) == 2 and re.match(r'^(SR_|ST_)?B\d+[A-Za-z]?$', sub[0], re.I) and re.match(r'^(SR_|ST_)?B\d+[A-Za-z]?$', sub[1], re.I):
                    m1 = re.search(r'\d+', sub[0])
                    m2 = re.search(r'\d+', sub[1])
                    if m1 and m2 and int(m1.group()) < int(m2.group()):
                        # Intervalo estritamente ascendente (ex: B3-B5)
                        continue
                    else:
                        # Subtracao aritmetica (ex: B8-B4)
                        return True
                else:
                    return True

    return False

def parse_bands(text, sensor=None):
    """
    Interpreta e normaliza uma lista de bandas customizadas, suportando:
    - Separadores por virgula, ponto e virgula ou espacos
    - Delimitadores externos como parenteses (B3, B4) ou colchetes [B3, B4]
    - Expansao de intervalos com hifen apenas quando estritamente ascendente (ex: 'B3-B5' -> ['SR_B3', 'SR_B4', 'SR_B5'])
    - Bloqueia expressao matematica (ex: 'B8-B4' e subtracao, nao intervalo)
    - Mapeamento e normalizacao de prefixos para Landsat (SR_ / ST_) e Sentinel-2
    - Compatibilidade estrita com Landsat 5 TM (onde B6 termica e ST_B6, e nao existe SR_B6)
    - Filtragem estrita pelas bandas reais suportadas pelo sensor
    """
    if not text:
        return []
    t = str(text).strip()
    if is_math_expr(t):
        return []

    while (t.startswith('(') and t.endswith(')')) or (t.startswith('[') and t.endswith(']')):
        t = t[1:-1].strip()

    raw_items = [b.strip().upper() for b in re.split(r'[,;\s]+', t) if b.strip()]
    expanded = []

    for item in raw_items:
        item = item.strip("()[]")
        if not item:
            continue

        if '-' in item:
            sub = item.split('-')
            if len(sub) == 2 and re.match(r'^(SR_|ST_)?B\d+$', sub[0]) and re.match(r'^(SR_|ST_)?B\d+$', sub[1]):
                prefix = 'SR_' if ('SR_' in sub[0] or 'SR_' in sub[1]) else ''
                m1 = re.search(r'\d+', sub[0])
                m2 = re.search(r'\d+', sub[1])
                if m1 and m2:
                    n1 = int(m1.group())
                    n2 = int(m2.group())
                    if n1 < n2:
                        for n in range(n1, n2 + 1):
                            expanded.append("%sB%d" % (prefix, n))
                        continue
        expanded.append(item)

    out = []
    sens = (sensor or '').upper()

    for b in expanded:
        if sens in ['L8', 'L7', 'L5', 'L4']:
            if b.startswith('B') and not b.startswith(('SR_', 'ST_')):
                if b == 'B10' and sens == 'L8':
                    out.append('ST_B10')
                elif b == 'B6' and sens in ['L7', 'L5', 'L4']:
                    out.append('ST_B6')
                else:
                    out.append('SR_' + b)
            else:
                out.append(b)
        elif sens == 'S2':
            if b.startswith('SR_'):
                out.append(b.replace('SR_', ''))
            elif b.startswith('ST_'):
                out.append(b.replace('ST_', ''))
            else:
                out.append(b)
        else:
            out.append(b)

    if sens in ['L5', 'L4', 'L7']:
        out = [('ST_B6' if x == 'SR_B6' else x) for x in out]

    # Validacao contra as bandas reais do sensor selecionado
    if sens in VALID_SENSOR_BANDS:
        valid_set = set(VALID_SENSOR_BANDS[sens])
        out = [b for b in out if b in valid_set]

    return out

def inspect_tiff_header_pure_python(tif_path):
    """Lê cabeçalho TIFF em Python puro usando struct para extrair largura, altura e contagem de bandas
    como fallback definitivo caso GDAL e rasterio não estejam instalados."""
    import struct
    try:
        with open(tif_path, 'rb') as f:
            header = f.read(8)
            if len(header) < 8:
                return None
            byte_order = header[:2]
            if byte_order == b'II':
                fmt = '<'
            elif byte_order == b'MM':
                fmt = '>'
            else:
                return None
            version = struct.unpack(fmt + 'H', header[2:4])[0]
            if version != 42:
                return None
            first_ifd_offset = struct.unpack(fmt + 'I', header[4:8])[0]
            f.seek(first_ifd_offset)
            num_entries_bytes = f.read(2)
            if len(num_entries_bytes) < 2:
                return None
            num_entries = struct.unpack(fmt + 'H', num_entries_bytes)[0]
            tags = {}
            for _ in range(num_entries):
                entry = f.read(12)
                if len(entry) < 12:
                    break
                tag, ttype, count, val_or_offset = struct.unpack(fmt + 'HHII', entry)
                if ttype == 3:  # SHORT
                    val = (val_or_offset & 0xFFFF) if fmt == '<' else (val_or_offset >> 16)
                    tags[tag] = val
                elif ttype == 4:  # LONG
                    tags[tag] = val_or_offset

            width = tags.get(256)   # ImageWidth
            height = tags.get(257)  # ImageLength
            samples = tags.get(277, 1)  # SamplesPerPixel (padrão 1 banda se omitido)
            if width and height and width > 0 and height > 0:
                bands_info = []
                for b_i in range(1, samples + 1):
                    bands_info.append({
                        'band': b_i,
                        'description': '',
                        'dtype': 'uint16',
                        'min': None, 'max': None, 'mean': None, 'std': None,
                        'is_constant': False, 'is_nan': False
                    })
                return {
                    'width': width,
                    'height': height,
                    'count': samples,
                    'geotransform': [0.0, 1.0, 0.0, 0.0, 0.0, -1.0],
                    'projection': 'TIFF',
                    'bands': bands_info
                }
    except Exception:
        pass
    return None

def validate_geotiff_health(tif_path, expected_bands=None, sensor=None, strict_stats=True):
    """
    Realiza a validação atômica de integridade (Health Check) do raster pós-geração:
    - Existência física e tamanho de arquivo mínimo (> 1024 bytes).
    - Contagem estrita de bandas (raster.count == len(expected_bands)).
    - Dimensões espaciais válidas (W > 0, H > 0).
    - Resolução espacial e geotransform válidos.
    - Projeção/CRS presente.
    - Tipos de dados íntegros.
    - Verificação de dados: detecção de all-NaN ou rasters vazios/constantes com variância zero.

    Se a validação falhar:
    - Descarta imediatamente o arquivo corrompido e seus arquivos auxiliares.
    - Registra metadados diagnósticos estruturados em JSON.
    - Levanta a exceção tipada RasterHealthCheckError com os diagnósticos completos.
    """
    if not tif_path or not os.path.exists(tif_path):
        diag = {'file': str(tif_path), 'error': 'Arquivo nao existe no disco'}
        raise RasterHealthCheckError("Arquivo GeoTIFF não foi criado ou não existe: %s" % str(tif_path), diag)

    file_size = os.path.getsize(tif_path)
    if file_size < 1024:
        diag = {'file': str(tif_path), 'file_size_bytes': file_size, 'error': 'Arquivo truncado ou menor que 1KB'}
        try: os.remove(tif_path)
        except Exception: pass
        raise RasterHealthCheckError("Arquivo GeoTIFF corrompido ou truncado (tamanho: %d bytes)" % file_size, diag)

    # 1. Tentar inspecionar com osgeo.gdal nativo
    info = None
    try:
        from osgeo import gdal
        ds = gdal.Open(tif_path, gdal.GA_ReadOnly)
        if ds is not None:
            w = ds.RasterXSize
            h = ds.RasterYSize
            count = ds.RasterCount
            gt = ds.GetGeoTransform()
            proj = ds.GetProjection()
            bands_info = []
            for i in range(1, count + 1):
                b = ds.GetRasterBand(i)
                stats = None
                try:
                    stats = b.GetStatistics(0, 1)
                except Exception:
                    pass
                b_min = float(stats[0]) if stats else None
                b_max = float(stats[1]) if stats else None
                b_mean = float(stats[2]) if stats else None
                b_std = float(stats[3]) if stats else None
                is_const = (b_min is not None and b_max is not None and b_min == b_max) or (b_std is not None and b_std == 0.0)
                is_nan = (b_mean is None) or math.isnan(b_mean)
                bands_info.append({
                    'band': i,
                    'description': b.GetDescription() or '',
                    'dtype': gdal.GetDataTypeName(b.DataType),
                    'min': b_min,
                    'max': b_max,
                    'mean': b_mean,
                    'std': b_std,
                    'is_constant': is_const,
                    'is_nan': is_nan
                })
            ds = None
            info = {
                'width': w,
                'height': h,
                'count': count,
                'geotransform': gt,
                'projection': proj,
                'bands': bands_info
            }
    except Exception as e_gdal:
        sys.stderr.write("[ArcGEE][HealthCheck] Inspecao GDAL nativo falhou: %s. Tentando QGIS...\n" % str(e_gdal))

    # 2. Fallback: Subprocesso Python QGIS com GDAL (busca dinâmica)
    if not info:
        import glob
        qgis_py_candidates = glob.glob(r"C:\Program Files\QGIS *\apps\Python3*\python.exe")
        qgis_py_candidates += glob.glob(r"C:\Program Files (x86)\QGIS *\apps\Python3*\python.exe")
        qgis_py_candidates += glob.glob(r"C:\OSGeo4W*\apps\Python3*\python.exe")
        for qpy in qgis_py_candidates:
            if os.path.exists(qpy):
                try:
                    inspect_script = (
                        "import sys, json, math\n"
                        "from osgeo import gdal\n"
                        "ds = gdal.Open(%r, gdal.GA_ReadOnly)\n"
                        "if not ds:\n"
                        "    print(json.dumps({'error': 'Falha gdal.Open'}))\n"
                        "    sys.exit(0)\n"
                        "count = ds.RasterCount\n"
                        "bands_info = []\n"
                        "for i in range(1, count + 1):\n"
                        "    b = ds.GetRasterBand(i)\n"
                        "    stats = None\n"
                        "    try:\n"
                        "        stats = b.GetStatistics(0, 1)\n"
                        "    except Exception:\n"
                        "        pass\n"
                        "    b_min = float(stats[0]) if stats else None\n"
                        "    b_max = float(stats[1]) if stats else None\n"
                        "    b_mean = float(stats[2]) if stats else None\n"
                        "    b_std = float(stats[3]) if stats else None\n"
                        "    is_const = (b_min is not None and b_max is not None and b_min == b_max) or (b_std is not None and b_std == 0.0)\n"
                        "    is_nan = (b_mean is None) or math.isnan(b_mean)\n"
                        "    bands_info.append({\n"
                        "        'band': i, 'description': b.GetDescription() or '',\n"
                        "        'dtype': gdal.GetDataTypeName(b.DataType),\n"
                        "        'min': b_min, 'max': b_max, 'mean': b_mean, 'std': b_std,\n"
                        "        'is_constant': is_const, 'is_nan': is_nan\n"
                        "    })\n"
                        "res = {\n"
                        "    'width': ds.RasterXSize, 'height': ds.RasterYSize, 'count': count,\n"
                        "    'geotransform': list(ds.GetGeoTransform()), 'projection': ds.GetProjection(),\n"
                        "    'bands': bands_info\n"
                        "}\n"
                        "print(json.dumps(res))\n"
                    ) % tif_path
                    proc = subprocess.run([qpy, "-c", inspect_script], capture_output=True, text=True, timeout=60)
                    if proc.returncode == 0 and proc.stdout.strip():
                        parsed = json.loads(proc.stdout.strip())
                        if 'error' not in parsed:
                            info = parsed
                            break
                except Exception as ex_q:
                    sys.stderr.write("[ArcGEE][HealthCheck] Fallback QGIS falhou: %s\n" % str(ex_q))

    # 3. Fallback: rasterio (se disponivel)
    if not info:
        try:
            import rasterio
            import numpy as np
            with rasterio.open(tif_path) as src:
                count = src.count
                w = src.width
                h = src.height
                crs_str = str(src.crs) if src.crs else ""
                bands_info = []
                for i in range(1, count + 1):
                    arr = src.read(i)
                    arr_f = arr.astype(float)
                    b_min = float(np.nanmin(arr_f)) if arr_f.size > 0 else None
                    b_max = float(np.nanmax(arr_f)) if arr_f.size > 0 else None
                    b_mean = float(np.nanmean(arr_f)) if arr_f.size > 0 else None
                    b_std = float(np.nanstd(arr_f)) if arr_f.size > 0 else None
                    is_const = (b_min is not None and b_max is not None and b_min == b_max) or (b_std is not None and b_std == 0.0)
                    is_nan = (b_mean is None) or math.isnan(b_mean)
                    bands_info.append({
                        'band': i,
                        'description': src.descriptions[i - 1] or '',
                        'dtype': str(src.dtypes[i - 1]),
                        'min': b_min, 'max': b_max, 'mean': b_mean, 'std': b_std,
                        'is_constant': is_const, 'is_nan': is_nan
                    })
                info = {
                    'width': w, 'height': h, 'count': count,
                    'geotransform': list(src.transform)[:6],
                    'projection': crs_str,
                    'bands': bands_info
                }
        except Exception:
            pass

    # 4. Fallback: Python puro (leitor basico de cabecalho TIFF com struct - sem GDAL e sem rasterio)
    is_pure_python_inspection = False
    if not info:
        info = inspect_tiff_header_pure_python(tif_path)
        if info:
            is_pure_python_inspection = True
            sys.stderr.write("[ArcGEE][HealthCheck] Cabecalho TIFF verificado com sucesso via leitor Python puro (GDAL/rasterio ausentes).\n")
            sys.stderr.flush()

    if not info:
        diag = {'file': str(tif_path), 'error': 'Nao foi possivel inspecionar metadados do GeoTIFF'}
        raise RasterHealthCheckError("Falha crítica ao inspecionar GeoTIFF: nenhum driver geoespacial disponível.", diag)

    failures = []
    w = info.get('width', 0)
    h = info.get('height', 0)
    count = info.get('count', 0)
    gt = info.get('geotransform', [])
    proj = info.get('projection', '')
    bands_info = info.get('bands', [])

    if w <= 0 or h <= 0:
        failures.append("Dimensões espaciais inválidas: largura=%d, altura=%d" % (w, h))

    if not is_pure_python_inspection:
        if not gt or (len(gt) >= 6 and gt[1] == 0 and gt[5] == 0):
            failures.append("Geotransform ou resolução espacial inválida: %s" % str(gt))

        if not proj or len(str(proj).strip()) == 0:
            failures.append("CRS / Sistema de Referência de Coordenadas ausente no arquivo")

    expected_count = None
    if expected_bands is not None:
        expected_count = len(expected_bands) if isinstance(expected_bands, (list, tuple)) else int(expected_bands)
        if count != expected_count:
            failures.append(
                "Contagem de bandas divergente: esperado %d bandas (%s), mas o produto gerado possui %d banda(s)"
                % (expected_count, str(expected_bands), count)
            )

    if strict_stats and bands_info:
        if all(b.get('is_nan', False) for b in bands_info):
            failures.append("Raster sem dados válidos: todas as bandas são NaN (NoData integral)")
        elif all(b.get('is_constant', False) and (b.get('mean') == 0.0 or b.get('min') == 0.0) for b in bands_info):
            failures.append("Raster vazio: todas as bandas contêm valor constante zero (0.0)")

    diagnostics = {
        'file': tif_path,
        'file_size_bytes': file_size,
        'expected_band_count': expected_count,
        'expected_bands': expected_bands,
        'actual_band_count': count,
        'dimensions': {'width': w, 'height': h},
        'geotransform': gt,
        'crs_summary': str(proj)[:120] if proj else 'Nenhum',
        'bands': bands_info,
        'failures': failures
    }

    if failures:
        try:
            if os.path.exists(tif_path): os.remove(tif_path)
            aux_xml = tif_path + ".aux.xml"
            if os.path.exists(aux_xml): os.remove(aux_xml)
            ovr = tif_path + ".ovr"
            if os.path.exists(ovr): os.remove(ovr)
        except Exception:
            pass

        diag_json = json.dumps(diagnostics, indent=2, ensure_ascii=False)
        sys.stderr.write("[ArcGEE][HealthCheck] FALHA NA VALIDAÇÃO DO RASTER:\n%s\n" % diag_json)
        sys.stderr.flush()
        raise RasterHealthCheckError(
            "Falha no Health Check pós-processamento: " + "; ".join(failures),
            diagnostics=diagnostics
        )

    return True, diagnostics

def compute_spectral_index(img, sensor, comp_code, custom_formula=None):
    """Calcula indice espectral ou formula customizada sobre a imagem (usando reflectancia normalizada)"""
    # 0. Banda Termica (Surface Temperature em Celsius)
    if comp_code in ['10', 'ST_B10']:
        return img.select('ST_B10').multiply(0.00341802).add(149.0).subtract(273.15).rename('TEMP_CELSIUS').toFloat()
    elif comp_code in ['6', 'ST_B6']:
        return img.select('ST_B6').multiply(0.00341802).add(149.0).subtract(273.15).rename('TEMP_CELSIUS').toFloat()

    scaled = apply_sensor_scaling(img, sensor)

    # 1. Formula Matematica Customizada
    has_formula = bool(custom_formula and is_math_expr(custom_formula))
    if has_formula or (comp_code == 'CUSTOM_MATH' and not custom_formula):
        formula = custom_formula or comp_code
        band_names = scaled.bandNames().getInfo()
        b_dict = {}
        for b in band_names:
            b_dict[b] = scaled.select(b)
            b_dict[b.lower()] = scaled.select(b)
            b_dict[b.upper()] = scaled.select(b)
        return scaled.expression(formula, b_dict).rename('CUSTOM_INDEX').toFloat()

    # Mapeamento padrao de bandas por sensor
    if sensor == 'S2':
        b_blue, b_green, b_red, b_nir, b_swir1, b_swir2 = 'B2', 'B3', 'B4', 'B8', 'B11', 'B12'
    elif sensor == 'L8':
        b_blue, b_green, b_red, b_nir, b_swir1, b_swir2 = 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6', 'SR_B7'
    elif sensor in ['L7', 'L5', 'L4']:
        b_blue, b_green, b_red, b_nir, b_swir1, b_swir2 = 'SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B7'
    else:
        # L1-L3 MSS
        b_blue, b_green, b_red, b_nir, b_swir1, b_swir2 = 'B4', 'B4', 'B5', 'B7', 'B7', 'B7'

    if comp_code == 'NDVI':
        return scaled.normalizedDifference([b_nir, b_red]).rename('NDVI').toFloat()
    elif comp_code == 'NDWI':
        return scaled.normalizedDifference([b_green, b_nir]).rename('NDWI').toFloat()
    elif comp_code == 'NDMI':
        return scaled.normalizedDifference([b_nir, b_swir1]).rename('NDMI').toFloat()
    elif comp_code == 'NBR':
        return scaled.normalizedDifference([b_nir, b_swir2]).rename('NBR').toFloat()
    elif comp_code == 'EVI':
        return scaled.expression(
            '2.5 * ((NIR - RED) / (NIR + 6.0 * RED - 7.5 * BLUE + 1.0))',
            {'NIR': scaled.select(b_nir), 'RED': scaled.select(b_red), 'BLUE': scaled.select(b_blue)}
        ).rename('EVI').toFloat()
    elif comp_code == 'SAVI':
        return scaled.expression(
            '1.5 * ((NIR - RED) / (NIR + RED + 0.5))',
            {'NIR': scaled.select(b_nir), 'RED': scaled.select(b_red)}
        ).rename('SAVI').toFloat()

    return scaled.normalizedDifference([b_nir, b_red]).rename(comp_code).toFloat()

def get_visualization_image(img, sensor, composition_code):
    comp_map = COMPOSITIONS.get(sensor, COMPOSITIONS['L8'])
    comp_info = comp_map.get(composition_code, {})

    # Se for indice espectral, visualiza com a rampa de cores do indice
    if comp_info.get('is_index', False) or composition_code in INDEX_PALETTES:
        idx_img = compute_spectral_index(img, sensor, composition_code)
        pal_info = INDEX_PALETTES.get(composition_code, INDEX_PALETTES['NDVI'])
        return idx_img.visualize(min=pal_info['min'], max=pal_info['max'], palette=pal_info['palette'])

    if composition_code not in comp_map:
        first_code = list(comp_map.keys())[0]
        bands = comp_map[first_code]['bands']
    else:
        bands = comp_info['bands']

    # Se for multibanda, usa bandas padrao RGB para visualizacao da miniatura
    if len(bands) > 3:
        if sensor == 'S2':
            bands = ['B4', 'B3', 'B2']
        else:
            bands = ['SR_B4', 'SR_B3', 'SR_B2']

    scaled = apply_sensor_scaling(img, sensor)
    vis_params = {
        'bands': bands,
        'min': 0.0,
        'max': 0.7,
        'gamma': 1.2
    }
    return scaled.visualize(**vis_params)

def normalize_date(d_str):
    if not d_str:
        return ""
    d_str = str(d_str).strip()
    import re
    m = re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$", d_str)
    if m:
        day, month, year = m.groups()
        return "%04d-%02d-%02d" % (int(year), int(month), int(day))
    m2 = re.match(r"^(\d{4})[/.-](\d{1,2})[/.-](\d{1,2})$", d_str)
    if m2:
        year, month, day = m2.groups()
        return "%04d-%02d-%02d" % (int(year), int(month), int(day))
    return d_str

def parse_ee_geometry(geom_dict):
    """Converte com seguranca qualquer formato GeoJSON (Polygon, MultiPolygon, Feature, FeatureCollection) para ee.Geometry"""
    if not geom_dict:
        return None
    gtype = geom_dict.get('type')
    if gtype == 'FeatureCollection':
        return ee.FeatureCollection(geom_dict).geometry()
    elif gtype == 'Feature':
        return ee.Feature(geom_dict).geometry()
    elif gtype in ['Polygon', 'MultiPolygon', 'Point', 'MultiPoint', 'LineString', 'MultiLineString', 'GeometryCollection']:
        return ee.Geometry(geom_dict)
    elif 'coordinates' in geom_dict:
        return ee.Geometry(geom_dict)
    elif 'features' in geom_dict:
        return ee.FeatureCollection(geom_dict).geometry()
    return ee.Geometry(geom_dict)

def search_collection(sensor, start_date, end_date, bbox=None, geometry=None, path=None, row=None, mgrs=None, max_images=150):
    coll = get_image_collection(sensor)

    # Filtro temporal flexível e inclusivo (suporta uma ou ambas as datas)
    s_date = normalize_date(start_date)
    e_date = normalize_date(end_date)
    import datetime
    if s_date or e_date:
        if not s_date:
            s_date = "1972-01-01"
        if not e_date:
            e_date = datetime.date.today().strftime("%Y-%m-%d")

        end_dt_str = e_date
        if len(end_dt_str) == 10:
            try:
                d = datetime.datetime.strptime(end_dt_str, "%Y-%m-%d").date() + datetime.timedelta(days=1)
                end_dt_str = d.strftime("%Y-%m-%d")
            except Exception:
                pass
        coll = coll.filterDate(s_date, end_dt_str)

    # Filtro espacial estrito: Extensao da tela (bbox) ou Camada Vetorial (geometry)
    aoi = None
    if geometry:
        aoi = parse_ee_geometry(geometry)
    elif bbox:
        # [minx, miny, maxx, maxy] com protecao de orientacao e limites WGS84
        try:
            b_minx = min(float(bbox[0]), float(bbox[2]))
            b_maxx = max(float(bbox[0]), float(bbox[2]))
            b_miny = min(float(bbox[1]), float(bbox[3]))
            b_maxy = max(float(bbox[1]), float(bbox[3]))
            b_minx = max(-180.0, min(180.0, b_minx))
            b_maxx = max(-180.0, min(180.0, b_maxx))
            b_miny = max(-90.0, min(90.0, b_miny))
            b_maxy = max(-90.0, min(90.0, b_maxy))
            if abs(b_maxx - b_minx) < 1e-6:
                b_maxx = b_minx + 0.001
            if abs(b_maxy - b_miny) < 1e-6:
                b_maxy = b_miny + 0.001
            aoi = ee.Geometry.BBox(b_minx, b_miny, b_maxx, b_maxy)
        except Exception as e_bbox:
            raise ValueError("Coordenadas de extensão inválidas: " + str(e_bbox))
    else:
        raise ValueError(u"Filtro espacial obrigatório: defina a extensão da tela do ArcMap ou selecione uma camada vetorial (AOI).")

    coll = coll.filterBounds(aoi)

    # Filtros de indexação espacial (Path/Row para Landsat, MGRS para Sentinel-2)
    sens_u = (sensor or '').upper()
    if path:
        try:
            coll = coll.filter(ee.Filter.eq('WRS_PATH', int(path)))
        except Exception:
            pass
    if row:
        try:
            coll = coll.filter(ee.Filter.eq('WRS_ROW', int(row)))
        except Exception:
            pass
    if mgrs:
        try:
            coll = coll.filter(ee.Filter.eq('MGRS_TILE', str(mgrs).strip().upper()))
        except Exception:
            pass

    # Ordenar por data (mais recentes primeiro) e limitar
    coll = coll.sort('system:time_start', False).limit(max_images)

    # Obter lista de imagens de forma direta e rapida (select([]) reduz tráfego e latência)
    try:
        data = coll.select([]).getInfo()
    except Exception:
        data = coll.getInfo()
    features = data.get('features', [])

    results = []
    import datetime
    for f in features:
        full_id = f.get('id', '')
        short_name = full_id.split('/')[-1]
        p = f.get('properties', {})

        t_ms = p.get('system:time_start', 0)
        dt_str = datetime.datetime.utcfromtimestamp(t_ms / 1000.0).strftime('%Y-%m-%d %H:%M') if t_ms else 'N/A'

        # Nuvem
        cloud_val = p.get('CLOUDY_PIXEL_PERCENTAGE')
        if cloud_val is None:
            cloud_val = p.get('CLOUD_COVER', 0.0)
        try:
            cloud = round(float(cloud_val), 1)
        except Exception:
            cloud = 0.0

        tile_val = p.get('MGRS_TILE') or ''
        path_val = p.get('WRS_PATH') or ''
        row_val = p.get('WRS_ROW') or ''

        results.append({
            'id': full_id,
            'name': short_name,
            'date': dt_str,
            'cloud_pct': cloud,
            'mgrs': tile_val,
            'path': path_val,
            'row': row_val
        })

    return results

def get_thumbnail_url(image_id, sensor, composition_code, dimensions=350, bbox=None):
    coll_id = COLLECTIONS.get(sensor, '')
    if coll_id and '/' not in image_id:
        image_id = coll_id + '/' + image_id

    img = ee.Image(image_id)
    vis_img = get_visualization_image(img, sensor, composition_code)
    
    thumb_params = {
        'dimensions': dimensions,
        'format': 'png',
        'crs': 'EPSG:3857'
    }
    if bbox:
        thumb_params['region'] = ee.Geometry.BBox(bbox[0], bbox[1], bbox[2], bbox[3])
    
    return vis_img.getThumbURL(thumb_params)

def compute_safe_scale(region_bbox, num_bands, is_multiband, requested_scale=None, sensor=None):
    """
    Retorna a resolucao nativa estrita (100% de qualidade) solicitada pelo usuario ou nativa do sensor.
    REGRA RIGOROSA: NUNCA diminuir qualidade/reamostrar silenciosamente!
    """
    req = None
    if requested_scale is not None:
        try:
            req = float(requested_scale)
        except Exception:
            req = None

    if req is None or req <= 0:
        if sensor == 'S2':
            req = 10.0
        elif sensor in ['L8', 'L7', 'L5', 'L4']:
            req = 30.0
        elif sensor in ['L1', 'L2', 'L3']:
            req = 60.0
        else:
            req = 20.0 if num_bands > 3 else 30.0

    return req

def calculate_spatial_grid(region_bbox, scale, num_bands, is_multiband, max_chunk_mb=32, bytes_per_sample=None):
    """
    Calcula a divisao da area em quadrantes quando o tamanho estimado excede
    o limite de seguranca do GEE (max_chunk_mb, padrao 32 MB para garantir margem segura contra o teto de 48 MB).
    Retorna (nx, ny, tot_bytes, grid_tiles).
    """
    import math
    if not region_bbox:
        return 1, 1, 0, []

    minx, miny, maxx, maxy = region_bbox
    lat_center = (miny + maxy) / 2.0
    lat_rad = math.radians(lat_center)
    m_per_deg_lat = 110540.0
    m_per_deg_lon = 111320.0 * math.cos(lat_rad)
    width_m = abs(maxx - minx) * m_per_deg_lon
    height_m = abs(maxy - miny) * m_per_deg_lat

    if bytes_per_sample is not None:
        bpp = int(bytes_per_sample) * num_bands
    else:
        bpp = 4 if (num_bands == 1 and not is_multiband) else ((2 * num_bands) if is_multiband else 3)
    target_max_bytes = max_chunk_mb * 1024 * 1024
    max_pixels = float(target_max_bytes) / float(bpp)

    tot_px_x = max(1, int(math.ceil(width_m / float(scale))))
    tot_px_y = max(1, int(math.ceil(height_m / float(scale))))
    tot_px = tot_px_x * tot_px_y
    tot_bytes = tot_px * bpp

    if tot_bytes <= target_max_bytes:
        return 1, 1, tot_bytes, [(minx, miny, maxx, maxy)]

    ratio = math.sqrt(float(tot_px) / float(max_pixels))
    aspect = float(tot_px_x) / float(tot_px_y) if tot_px_y > 0 else 1.0

    nx = max(1, int(math.ceil(ratio * math.sqrt(aspect))))
    ny = max(1, int(math.ceil(ratio / math.sqrt(aspect))))

    while ((tot_px_x / nx) * (tot_px_y / ny)) > max_pixels:
        if (tot_px_x / nx) >= (tot_px_y / ny):
            nx += 1
        else:
            ny += 1

    tiles = []
    dx = (maxx - minx) / float(nx)
    dy = (maxy - miny) / float(ny)
    overlap_x = (scale / m_per_deg_lon) * 1.5
    overlap_y = (scale / m_per_deg_lat) * 1.5

    for r in range(ny):
        for c in range(nx):
            t_minx = minx + c * dx
            t_maxx = minx + (c + 1) * dx
            t_miny = miny + r * dy
            t_maxy = miny + (r + 1) * dy
            # Adicionar overlap nas bordas internas para zero costuras/linhas
            if c > 0:
                t_minx -= overlap_x
            if c < nx - 1:
                t_maxx += overlap_x
            if r > 0:
                t_miny -= overlap_y
            if r < ny - 1:
                t_maxy += overlap_y
            tiles.append((t_minx, t_miny, t_maxx, t_maxy))

    return nx, ny, tot_bytes, tiles

def merge_geotiff_tiles(tile_paths, out_tif_path, expected_bands_count=None):
    """
    Mescla uma lista de GeoTIFFs em um unico arquivo GeoTIFF continuo
    preservando bandas, tipos de dados, CRS e georreferenciamento.
    Garante a integridade do empilhamento e contagem de bandas solicitadas.
    Tenta em ordem:
    1. osgeo.gdal (Python nativo no processo atual)
    2. Subprocesso Python do QGIS com GDAL
    3. Executaveis GDAL do sistema (gdalbuildvrt / gdal_translate)
    """
    import os, sys, tempfile, subprocess, shutil

    if not tile_paths:
        raise ValueError("Nenhum arquivo de quadrante para mesclar.")

    if expected_bands_count is None and os.path.exists(tile_paths[0]):
        try:
            from osgeo import gdal
            ds0 = gdal.Open(tile_paths[0], gdal.GA_ReadOnly)
            if ds0:
                expected_bands_count = ds0.RasterCount
                ds0 = None
        except Exception:
            pass

    band_list_arg = list(range(1, expected_bands_count + 1)) if (expected_bands_count and expected_bands_count > 0) else None

    if len(tile_paths) == 1:
        os.makedirs(os.path.dirname(os.path.abspath(out_tif_path)), exist_ok=True)
        shutil.copy2(tile_paths[0], out_tif_path)
        return out_tif_path

    os.makedirs(os.path.dirname(os.path.abspath(out_tif_path)), exist_ok=True)

    # 1. osgeo.gdal nativo no processo atual
    try:
        from osgeo import gdal
        vrt_opts = gdal.BuildVRTOptions(resampleAlg='near')
        vrt = gdal.BuildVRT('', tile_paths, options=vrt_opts)
        if vrt is not None:
            trans_kwargs = {
                'format': 'GTiff',
                'creationOptions': ['COMPRESS=LZW', 'TILED=YES', 'BIGTIFF=IF_SAFER']
            }
            if band_list_arg:
                trans_kwargs['bandList'] = band_list_arg
            trans_opts = gdal.TranslateOptions(**trans_kwargs)
            ds = gdal.Translate(out_tif_path, vrt, options=trans_opts)
            ds = None
            vrt = None
            if os.path.exists(out_tif_path) and os.path.getsize(out_tif_path) > 1024:
                return out_tif_path
    except Exception as e:
        sys.stderr.write("[ArcGEE] GDAL nativo: %s. Tentando alternativas...\n" % str(e))

    # 2. Subprocesso Python do QGIS (que possui GDAL nativo C++)
    qgis_py_candidates = [
        r"C:\Program Files\QGIS 3.44.10\apps\Python312\python.exe",
        r"C:\Program Files\QGIS 3.34.10\apps\Python312\python.exe",
        r"C:\Program Files\QGIS 3.28\apps\Python39\python.exe",
    ]
    for qpy in qgis_py_candidates:
        if os.path.exists(qpy):
            try:
                b_list_repr = repr(band_list_arg)
                merge_code = (
                    "import sys\n"
                    "from osgeo import gdal\n"
                    "tiles = %r\n"
                    "out_path = %r\n"
                    "band_list = %s\n"
                    "vrt = gdal.BuildVRT('', tiles)\n"
                    "kwargs = {'format': 'GTiff', 'creationOptions': ['COMPRESS=LZW', 'TILED=YES', 'BIGTIFF=IF_SAFER']}\n"
                    "if band_list:\n"
                    "    kwargs['bandList'] = band_list\n"
                    "opts = gdal.TranslateOptions(**kwargs)\n"
                    "gdal.Translate(out_path, vrt, options=opts)\n"
                    "vrt = None\n"
                ) % (tile_paths, out_tif_path, b_list_repr)

                proc = subprocess.run([qpy, "-c", merge_code], capture_output=True, text=True, timeout=300)
                if proc.returncode == 0 and os.path.exists(out_tif_path) and os.path.getsize(out_tif_path) > 1024:
                    return out_tif_path
            except Exception as e2:
                sys.stderr.write("[ArcGEE] QGIS Python subprocess: %s\n" % str(e2))

    # 3. Executaveis GDAL do sistema
    gdal_bin_dirs = [
        r"C:\Program Files\QGIS 3.44.10\bin",
        r"C:\Program Files\QGIS 3.34.10\bin",
        r"C:\OSGeo4W\bin",
        r"C:\OSGeo4W64\bin",
    ]
    for bdir in gdal_bin_dirs:
        bvrt_exe = os.path.join(bdir, "gdalbuildvrt.exe")
        trans_exe = os.path.join(bdir, "gdal_translate.exe")
        if os.path.exists(bvrt_exe) and os.path.exists(trans_exe):
            try:
                vrt_temp = tempfile.mktemp(suffix='.vrt')
                cmd_vrt = [bvrt_exe, vrt_temp] + tile_paths
                subprocess.run(cmd_vrt, check=True, capture_output=True, timeout=300)
                cmd_trans = [trans_exe, "-co", "COMPRESS=LZW", "-co", "TILED=YES", "-co", "BIGTIFF=IF_SAFER"]
                if band_list_arg:
                    for b_num in band_list_arg:
                        cmd_trans.extend(["-b", str(b_num)])
                cmd_trans.extend([vrt_temp, out_tif_path])
                subprocess.run(cmd_trans, check=True, capture_output=True, timeout=300)
                if os.path.exists(vrt_temp):
                    try: os.remove(vrt_temp)
                    except Exception: pass
                if os.path.exists(out_tif_path) and os.path.getsize(out_tif_path) > 1024:
                    return out_tif_path
            except Exception as e3:
                sys.stderr.write("[ArcGEE] GDAL CLI: %s\n" % str(e3))

    raise RuntimeError("Falha ao mesclar quadrantes: nenhum motor de mosaico GDAL disponivel.")

# Bits do QA_PIXEL (Landsat Collection 2 L2): 0=Fill (inclui gaps SLC-off), 1=Dilated Cloud,
# 2=Cirrus (apenas OLI/L8-L9), 3=Cloud, 4=Cloud Shadow
_LANDSAT_QA_MASK_BITS = (1 << 0) | (1 << 1) | (1 << 3) | (1 << 4)
_LANDSAT_OLI_QA_MASK_BITS = _LANDSAT_QA_MASK_BITS | (1 << 2)
# Classes SCL (Sentinel-2 L2A) removidas: 3=Sombra de nuvem, 8/9=Nuvem media/alta prob., 10=Cirrus
_S2_SCL_MASKED_CLASSES = (3, 8, 9, 10)


def mask_clouds_and_shadows(image, sensor=None):
    """Aplica mascaramento de nuvens, sombras e linhas de varredura (SLC-off)
    para Sentinel-2 e Landsat 4-9 antes de calculos de mosaico/mediana.

    IMPORTANTE: esta funcao e executada dentro de ImageCollection.map(), onde a
    imagem e um placeholder do servidor. Nenhuma operacao client-side (getInfo)
    pode ser usada aqui - a decisao de bandas e feita pelo sensor, que e conhecido.
    As colecoes usadas (S2_SR_HARMONIZED e Landsat C02 T1/T2_L2) sempre possuem
    SCL / QA_PIXEL. Landsat MSS (L1-L3) nao possui QA de nuvem e retorna sem mascara.
    """
    sens = (sensor or '').upper()
    if sens == 'S2':
        scl = image.select('SCL')
        mask = ee.Image.constant(1)
        for cls in _S2_SCL_MASKED_CLASSES:
            mask = mask.And(scl.neq(cls))
        return image.updateMask(mask)
    if sens in ('L8', 'L9'):
        return image.updateMask(image.select('QA_PIXEL').bitwiseAnd(_LANDSAT_OLI_QA_MASK_BITS).eq(0))
    if sens in ('L7', 'L5', 'L4'):
        return image.updateMask(image.select('QA_PIXEL').bitwiseAnd(_LANDSAT_QA_MASK_BITS).eq(0))
    return image


def cast_mosaic_to_native_type(image, sensor=None):
    """Converte o resultado de median() (sempre ponto flutuante) de volta ao tipo nativo do sensor.

    Landsat C02 L2 e Sentinel-2 L2A sao uint16 (SR ate ~43.636 DN e ST_B10 ~45.000 DN a 300 K):
    usar int16 truncaria tudo acima de 32.767. Landsat MSS (L1-L3) e uint8.
    """
    sens = (sensor or '').upper()
    if sens in ('L1', 'L2', 'L3'):
        return image.toUint8()
    return image.toUint16()


def get_safe_destination_path(target_path):
    """Verifica se o arquivo de destino esta bloqueado por outro processo (ex: ArcMap).
    Se estiver bloqueado, gera um nome alternativo com timestamp para evitar WinError 32."""
    if not target_path:
        return target_path
    if not os.path.exists(target_path):
        return target_path
    try:
        with open(target_path, 'r+b'):
            pass
        return target_path
    except (IOError, OSError):
        base, ext = os.path.splitext(target_path)
        ts = int(time.time() * 1000) % 1000000
        safe_path = "%s_%d%s" % (base, ts, ext)
        sys.stderr.write("[ArcGEE] Arquivo '%s' bloqueado pelo ArcMap. Gravando em '%s'...\n" % (os.path.basename(target_path), os.path.basename(safe_path)))
        sys.stderr.flush()
        return safe_path

def download_url_with_timeout(url, out_path, timeout=120, max_retries=3):
    """Realiza download via stream HTTP com timeout explicito de socket e tentativas contra dropouts."""
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'ArcGEE-Downloader/1.10'})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                with open(out_path, 'wb') as out_f:
                    shutil.copyfileobj(resp, out_f, length=65536)
            return True
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            time.sleep(1.5 * (attempt + 1))
    return False

def download_geotiff(image_ids, sensor, composition_code, custom_bands=None, load_mode='multiband', aoi_geometry=None, bbox=None, out_tif_path=None, scale=None, crs='EPSG:4674'):
    import math
    import re

    out_tif_path = get_safe_destination_path(out_tif_path)

    if not image_ids:
        raise ValueError("Nenhum ID de imagem fornecido.")

    cleaned_ids = []
    for img_id in image_ids:
        if '/' not in img_id:
            coll_id = COLLECTIONS.get(sensor, '')
            if coll_id:
                cleaned_ids.append(coll_id + '/' + img_id)
            else:
                cleaned_ids.append(img_id)
        else:
            cleaned_ids.append(img_id)

    # 0. Deteccao automatica do sensor real a partir do ID da imagem para evitar divergencia de satelite
    first_id = cleaned_ids[0].upper()
    if 'COPERNICUS/S2' in first_id:
        sensor = 'S2'
    elif 'LANDSAT/LC08' in first_id or 'LANDSAT/LC09' in first_id:
        sensor = 'L8'
    elif 'LANDSAT/LE07' in first_id:
        sensor = 'L7'
    elif 'LANDSAT/LT05' in first_id:
        sensor = 'L5'
    elif 'LANDSAT/LT04' in first_id:
        sensor = 'L4'
    elif 'LANDSAT/LM0' in first_id:
        sensor = 'L1'

    if len(cleaned_ids) == 1:
        img = ee.Image(cleaned_ids[0])
    else:
        coll = ee.ImageCollection(cleaned_ids)
        # Aplicar mascara de nuvens, sombras e SLC-off gaps em cada cena da colecao
        coll = coll.map(lambda im: mask_clouds_and_shadows(im, sensor))
        # median() promove para ponto flutuante: restaurar o tipo nativo (uint16/uint8) antes
        # de indices/termica, que aplicam os fatores de escala sobre o DN original.
        img = cast_mosaic_to_native_type(coll.median(), sensor)

    comp_map = COMPOSITIONS.get(sensor, COMPOSITIONS['L8'])
    comp_info = comp_map.get(composition_code, {})

    custom_text = (custom_bands or '').strip()
    is_custom_formula = bool(custom_text and is_math_expr(custom_text))
    is_custom_band_list = bool(custom_text and not is_math_expr(custom_text))

    is_thermal = (composition_code in ['10', '6', 'ST_B10', 'ST_B6'])
    is_spec_index = (composition_code in ['NDVI', 'NDWI', 'NDMI', 'NBR', 'EVI', 'SAVI'] or comp_info.get('is_index', False))

    if is_custom_formula or is_thermal or (is_spec_index and not is_custom_band_list) or (composition_code == 'CUSTOM_MATH' and not is_custom_band_list):
        is_index = True
        is_multi = False
        bands = [composition_code]
        formula = custom_text if (composition_code == 'CUSTOM_MATH' or is_custom_formula) else None
        export_img = compute_spectral_index(img, sensor, composition_code, custom_formula=formula)
    else:
        is_index = False
        if is_custom_band_list:
            bands = parse_bands(custom_text, sensor)
        elif comp_info.get('bands'):
            bands = comp_info['bands']
        elif comp_info.get('multiband', False) or load_mode == 'multiband':
            bands = MULTIBAND_DEFAULT_BANDS.get(sensor, ['B4', 'B3', 'B2'])
        else:
            bands = ['B4', 'B3', 'B2'] if sensor == 'S2' else ['SR_B4', 'SR_B3', 'SR_B2']

        if not bands:
            bands = ['B4', 'B3', 'B2'] if sensor == 'S2' else ['SR_B4', 'SR_B3', 'SR_B2']

        is_multi = (len(bands) > 1)
        export_img = img.select(bands)

    region = None
    calc_bbox = None
    if aoi_geometry:
        region = parse_ee_geometry(aoi_geometry)
        try:
            all_pts = []
            def extract_pts(c):
                if isinstance(c, (list, tuple)):
                    if len(c) >= 2 and isinstance(c[0], (int, float)):
                        all_pts.append(c)
                    else:
                        for sub in c:
                            extract_pts(sub)
            coords = aoi_geometry.get('coordinates', [])
            extract_pts(coords)
            if not all_pts and 'features' in aoi_geometry:
                for ft in aoi_geometry.get('features', []):
                    extract_pts(ft.get('geometry', {}).get('coordinates', []))
            if all_pts:
                xs = [p[0] for p in all_pts]
                ys = [p[1] for p in all_pts]
                calc_bbox = [min(xs), min(ys), max(xs), max(ys)]
        except Exception:
            pass
    elif bbox:
        region = ee.Geometry.BBox(bbox[0], bbox[1], bbox[2], bbox[3])
        calc_bbox = bbox
    else:
        raise ValueError(u"Filtro espacial obrigatório: defina a extensão da tela do mapa ou selecione uma camada vetorial (AOI).")

    safe_scale = compute_safe_scale(calc_bbox, len(bands), is_multi, requested_scale=scale, sensor=sensor)

    is_float_data = is_index or is_thermal
    bytes_per_sample = 4 if is_float_data else 2
    nx, ny, tot_bytes, grid_tiles = calculate_spatial_grid(calc_bbox, safe_scale, len(bands), is_multi, max_chunk_mb=32, bytes_per_sample=bytes_per_sample)

    if not out_tif_path:
        first_name = cleaned_ids[0].split('/')[-1]
        out_tif_path = os.path.join(tempfile.gettempdir(), "%s_%s.tif" % (first_name, composition_code))

    os.makedirs(os.path.dirname(os.path.abspath(out_tif_path)), exist_ok=True)

    # Caso 1: Apenas 1 tile (cabe no limite unitario <= 32 MB)
    if len(grid_tiles) <= 1:
        download_params = {
            'scale': safe_scale,
            'crs': crs,
            'region': region,
            'format': 'GEO_TIFF'
        }

        url = None
        try:
            url = export_img.getDownloadURL(download_params)
        except Exception as e:
            err_str = str(e)
            m = re.search(r'Total request size \((\d+) bytes\) must be less than or equal to (\d+) bytes', err_str)
            if not m:
                raise e

        if url:
            sys.stderr.write("[ArcGEE] Baixando arquivo GeoTIFF do GEE...\n")
            sys.stderr.flush()
            download_url_with_timeout(url, out_tif_path, timeout=180)
            sys.stderr.write("[ArcGEE] Validando integridade atômica do GeoTIFF (Health Check)...\n")
            sys.stderr.flush()
            validate_geotiff_health(out_tif_path, expected_bands=bands, sensor=sensor)
            sys.stderr.write("[ArcGEE] Download concluído e verificado com sucesso (%d bandas íntegras).\n" % len(bands))
            sys.stderr.flush()
            return out_tif_path

        # Se rejeitado por tamanho na primeira tentativa, forçar subdivisão em pelo menos 2x2
        nx, ny, tot_bytes, grid_tiles = calculate_spatial_grid(calc_bbox, safe_scale, len(bands), is_multi, max_chunk_mb=16, bytes_per_sample=bytes_per_sample)
        if len(grid_tiles) <= 1:
            minx, miny, maxx, maxy = calc_bbox
            midx = (minx + maxx) / 2.0
            midy = (miny + maxy) / 2.0
            grid_tiles = [
                (minx, miny, midx, midy),
                (midx, miny, maxx, midy),
                (minx, midy, midx, maxy),
                (midx, midy, maxx, maxy)
            ]
            nx, ny = 2, 2

    # Caso 2: Area grande (> 32 MB / > 48 MB, ate escala 1:500.000)
    # Particionamento automatico com 100% de resolucao nativa estrita e mosaico sem perda
    total_quads = len(grid_tiles)
    est_mb = tot_bytes / (1024.0 * 1024.0)
    sys.stderr.write(
        "[ArcGEE] Area extensa detectada (estimado: %.1f MB). Particionando em %d quadrantes (%dx%d) com 100%% da resolucao nativa (%.1fm)...\n"
        % (est_mb, total_quads, nx, ny, safe_scale)
    )
    sys.stderr.flush()

    temp_tiles_dir = tempfile.mkdtemp(prefix='arcgee_tiles_')

    def _fetch_sub_bbox(b_box, prefix_id):
        t_file = os.path.join(temp_tiles_dir, "tile_%s.tif" % prefix_id)
        t_reg = ee.Geometry.BBox(b_box[0], b_box[1], b_box[2], b_box[3])
        t_par = {
            'scale': safe_scale,
            'crs': crs,
            'region': t_reg,
            'format': 'GEO_TIFF'
        }
        last_err = None
        for attempt in range(2):
            try:
                u = export_img.getDownloadURL(t_par)
                if u:
                    download_url_with_timeout(u, t_file, timeout=120)
                    if os.path.exists(t_file) and os.path.getsize(t_file) > 0:
                        return [t_file]
            except Exception as ex:
                err_text = str(ex)
                last_err = ex
                # Se exceder o limite de tamanho do GEE, subdividir recursivamente em 2x2
                if 'Total request size' in err_text or 'must be less than or equal to' in err_text:
                    sys.stderr.write("[ArcGEE] Quadrante %s excede limite do GEE. Subdividindo em 2x2...\n" % prefix_id)
                    sys.stderr.flush()
                    mid_x = (b_box[0] + b_box[2]) / 2.0
                    mid_y = (b_box[1] + b_box[3]) / 2.0
                    sub_quads = [
                        [b_box[0], b_box[1], mid_x, mid_y],
                        [mid_x, b_box[1], b_box[2], mid_y],
                        [b_box[0], mid_y, mid_x, b_box[3]],
                        [mid_x, mid_y, b_box[2], b_box[3]],
                    ]
                    res_files = []
                    for s_i, s_box in enumerate(sub_quads):
                        res_files.extend(_fetch_sub_bbox(s_box, "%s_%d" % (prefix_id, s_i)))
                    return res_files

                # Se for 'empty' ou '0 bytes': apenas ignorar se houver geometria vetorial AOI real poligonal
                if aoi_geometry and ('0 bytes' in err_text or 'empty' in err_text.lower()):
                    sys.stderr.write("[ArcGEE] Quadrante %s fora da geometria vetorial AOI, ignorado.\n" % prefix_id)
                    sys.stderr.flush()
                    return []
                time.sleep(1.0 + attempt * 1.5)
        raise RuntimeError("Falha ao baixar quadrante %s: %s" % (prefix_id, str(last_err)))

    def _download_tile(item):
        idx, sub_bbox = item
        files = _fetch_sub_bbox(sub_bbox, "%03d" % idx)
        if files:
            sys.stderr.write("[ArcGEE] Quadrante %d/%d concluído (%d arquivo(s)).\n" % (idx + 1, total_quads, len(files)))
            sys.stderr.flush()
            return (idx, files)
        return None

    # Download multithread paralelo dos quadrantes
    max_workers = min(4, total_quads)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_download_tile, (i, b)) for i, b in enumerate(grid_tiles)]
        raw_results = [f.result() for f in concurrent.futures.as_completed(futures)]

    # Filtrar quadrantes vazios e ordenar por indice
    valid_results = [r for r in raw_results if r is not None]
    valid_results.sort(key=lambda x: x[0])
    ordered_tile_files = [f for r in valid_results for f in r[1]]

    if not ordered_tile_files:
        raise RuntimeError("Nenhum dado retornado para a regiao solicitada.")

    sys.stderr.write("[ArcGEE] Mesclando %d quadrantes em GeoTIFF unico final via GDAL...\n" % len(ordered_tile_files))
    sys.stderr.flush()
    merge_geotiff_tiles(ordered_tile_files, out_tif_path, expected_bands_count=len(bands))

    # Limpeza da pasta temporaria de quadrantes
    try:
        shutil.rmtree(temp_tiles_dir)
    except Exception:
        pass

    sys.stderr.write("[ArcGEE] Validando integridade atômica do mosaico GeoTIFF (Health Check)...\n")
    sys.stderr.flush()
    validate_geotiff_health(out_tif_path, expected_bands=bands, sensor=sensor)
    sys.stderr.write("[ArcGEE] Mosaico concluído e verificado com sucesso (%d bandas íntegras).\n" % len(bands))
    sys.stderr.flush()

    return out_tif_path
