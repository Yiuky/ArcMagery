# -*- coding: utf-8 -*-
"""
ArcMagery - funcoes comuns as fontes de tiles com data da janela principal (Python 2.7):
Google Earth historico (arcmagery_gehist) e Esri Wayback (arcmagery_wayback).

Mantidas num lugar so para que a area (bbox/AOI), o progresso, o periodo e o limite de tiles se
comportem igual nas duas fontes.
"""
from __future__ import division

import re

PROGRESS_KEYWORDS = (u'Reprojetando', u'pir', u'threads', u'Repetindo', u'Aviso', u'Wayback')


def area_params(bbox, geojson_file):
    """AOI (camada vetorial exportada) tem prioridade sobre a extensao do mapa."""
    if geojson_file:
        return {'geojson_file': geojson_file}
    if bbox:
        return {'bbox': ','.join('%.8f' % float(v) for v in bbox)}
    return {}


def zoom_of_row_id(img_id):
    m = re.search(r'_z(\d+)$', img_id or '')
    return int(m.group(1)) if m else None


def in_period(date, start_date, end_date):
    """Datas ISO (AAAA-MM-DD); limites vazios nao filtram; linha sem data nunca entra."""
    return bool(date) and (not start_date or date >= start_date) and (not end_date or date <= end_date)


def progress_callback(on_progress, text):
    """Linha do backend -> on_progress(mensagem, percentual ou None)."""
    if not on_progress:
        return None

    def cb(line):
        m = re.search(r'PROGRESS\s+(\d+)\s*/\s*(\d+)', line or '')
        if m and int(m.group(2)) > 0:
            done, total = int(m.group(1)), int(m.group(2))
            on_progress(u"%s %d/%d tiles..." % (text, done, total), 100.0 * done / total)
        elif line and any(k in line for k in PROGRESS_KEYWORDS):
            on_progress(line.replace('[ArcGEE] ', ''), None)
    return cb


def estimate_text(est, zoom, tiles_per_second):
    minutes = est['tiles'] / float(tiles_per_second) / 60.0
    return (u"%d tiles no zoom %d · %d x %d px · ~%.0f MB de download · ~%s" % (
        est['tiles'], zoom, est['width'], est['height'], est['download_mb'],
        u"%.0f min" % minutes if minutes >= 1 else u"menos de 1 min"))


def limit_message(est, zoom, max_tiles):
    """Mensagem de erro se a area exceder o limite de tiles; None se estiver ok."""
    if est['tiles'] > max_tiles:
        return (u"A área exige %d tiles no zoom %d (limite %d). Aproxime o mapa, use uma camada AOI menor "
                u"ou escolha um zoom menor." % (est['tiles'], zoom, max_tiles))
    return None
