# -*- coding: utf-8 -*-
"""
Carregamento de rasters no QGIS.

Substitui as funções arcpy do gee_bridge.py: em vez de inserir no TOC do ArcMap,
adiciona camadas ao Layers Panel do QGIS usando a API PyQGIS.
"""
from __future__ import annotations

import os
from typing import Optional

from qgis.core import (
    QgsProject,
    QgsRasterLayer,
    QgsLayerTree,
    QgsLayerTreeGroup,
)


class LayerLoaderError(RuntimeError):
    pass


def add_raster_layer(
    path: str,
    name: str,
    group_name: Optional[str] = None,
) -> QgsRasterLayer:
    """
    Carrega um GeoTIFF (ou qualquer fonte raster) no QGIS.

    :param path: Caminho do arquivo GeoTIFF (ou string de conexão raster).
    :param name: Nome da camada no Layers Panel.
    :param group_name: Grupo no Layers Panel. Se None, adiciona na raiz.
    :returns: A instância de QgsRasterLayer criada.
    :raises LayerLoaderError: Se o arquivo não for válido.
    """
    layer = QgsRasterLayer(path, name)
    if not layer.isValid():
        raise LayerLoaderError(
            f'Camada raster inválida: {path}\n'
            f'Erro QGIS: {layer.error().message()}'
        )

    project = QgsProject.instance()
    root = project.layerTreeRoot()

    if group_name:
        group = _get_or_create_group(root, group_name)
        project.addMapLayer(layer, False)
        group.insertLayer(0, layer)
    else:
        project.addMapLayer(layer, True)

    return layer


def add_xyz_tile_layer(
    url_template: str,
    name: str,
    min_zoom: int = 0,
    max_zoom: int = 21,
    group_name: Optional[str] = None,
) -> QgsRasterLayer:
    """
    Adiciona uma camada XYZ Tiles ao QGIS.

    :param url_template: URL com {x}, {y}, {z} (ex: Google, Esri, Bing).
    :param name: Nome da camada.
    :param min_zoom: Zoom mínimo.
    :param max_zoom: Zoom máximo.
    :param group_name: Grupo no Layers Panel.
    """
    # Converte {x},{y},{z} para o formato zxy do QGIS
    qgis_url = url_template.replace('{z}', 'z').replace('{x}', 'x').replace('{y}', 'y')
    uri = (
        f'type=xyz'
        f'&url={qgis_url}'
        f'&zmin={min_zoom}'
        f'&zmax={max_zoom}'
    )
    return add_raster_layer(uri, name, group_name=group_name)


def _get_or_create_group(
    parent: QgsLayerTree,
    name: str,
) -> QgsLayerTreeGroup:
    """Retorna (ou cria) um grupo de camadas no layer tree."""
    for child in parent.children():
        if isinstance(child, QgsLayerTreeGroup) and child.name() == name:
            return child
    return parent.addGroup(name)
