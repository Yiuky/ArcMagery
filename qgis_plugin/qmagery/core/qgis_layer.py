# -*- coding: utf-8 -*-
"""
Camadas no QGIS: inserção (com grupo ou no lugar de outra camada), simbologia e camadas XYZ.
"""
from qgis.core import (
    QgsColorRampShader,
    QgsContrastEnhancement,
    QgsDataSourceUri,
    QgsLayerTreeGroup,
    QgsMultiBandColorRenderer,
    QgsProject,
    QgsRasterLayer,
    QgsRasterShader,
    QgsSingleBandGrayRenderer,
    QgsSingleBandPseudoColorRenderer,
    QgsStyle,
)
from qgis.PyQt.QtGui import QColor


class LayerLoaderError(RuntimeError):
    pass


# --------------------------------------------------------------------------- inserção
def add_raster_layer(path, name, group_name=None, replace_layer_id=None, provider='gdal'):
    """Carrega o raster. replace_layer_id: a nova camada ocupa a posição (grupo e ordem) da antiga, que
    é removida do projeto. group_name: grupo na raiz do painel (criado se não existir)."""
    layer = QgsRasterLayer(path, name, provider)
    if not layer.isValid():
        raise LayerLoaderError(u"Camada raster inválida: %s\n%s" % (path, layer.error().message()))
    project = QgsProject.instance()
    root = project.layerTreeRoot()
    old_node = root.findLayer(replace_layer_id) if replace_layer_id else None
    if old_node is not None:
        parent = old_node.parent() or root
        index = parent.children().index(old_node)
        project.addMapLayer(layer, False)
        parent.insertLayer(index, layer)
        project.removeMapLayer(replace_layer_id)
    elif group_name:
        project.addMapLayer(layer, False)
        get_or_create_group(root, group_name).insertLayer(0, layer)
    else:
        project.addMapLayer(layer, True)
    return layer


def add_xyz_tile_layer(url_template, name, min_zoom=0, max_zoom=21, group_name=None):
    """Camada XYZ "ao vivo" (sem download). A URL mantém {x}, {y} e {z}: o QgsDataSourceUri codifica o
    '&' das URLs com parâmetros (ex.: Google) para não quebrar a lista de parâmetros do provedor."""
    uri = QgsDataSourceUri()
    uri.setParam('type', 'xyz')
    uri.setParam('url', url_template)
    uri.setParam('zmin', str(int(min_zoom)))
    uri.setParam('zmax', str(int(max_zoom)))
    encoded = bytes(uri.encodedUri()).decode('utf-8')
    return add_raster_layer(encoded, name, group_name=group_name, provider='wms')


def get_or_create_group(parent, name):
    for child in parent.children():
        if isinstance(child, QgsLayerTreeGroup) and child.name() == name:
            return child
    return parent.insertGroup(0, name)


_get_or_create_group = get_or_create_group   # nome antigo


def raster_layers():
    """[(id, nome)] das camadas raster do projeto, na ordem do painel."""
    out = []
    for node in QgsProject.instance().layerTreeRoot().findLayers():
        lyr = node.layer()
        if isinstance(lyr, QgsRasterLayer):
            out.append((lyr.id(), lyr.name()))
    return out


# --------------------------------------------------------------------------- simbologia
def _cut(provider, band, lower=0.02, upper=0.98):
    try:
        vmin, vmax = provider.cumulativeCut(band, lower, upper, provider.extent(), 250000)
    except Exception:
        vmin = vmax = None
    if vmin is None or vmax is None or vmax <= vmin:
        stats = provider.bandStatistics(band)
        vmin, vmax = stats.minimumValue, stats.maximumValue
    return vmin, vmax


def _enhancement(provider, band):
    ce = QgsContrastEnhancement(provider.dataType(band))
    vmin, vmax = _cut(provider, band)
    ce.setContrastEnhancementAlgorithm(QgsContrastEnhancement.StretchToMinimumMaximum, True)
    ce.setMinimumValue(vmin)
    ce.setMaximumValue(vmax)
    return ce


def style_rgb(layer, bands0):
    """bands0: índices 0-based (resposta do backend); o QGIS usa 1-based."""
    provider = layer.dataProvider()
    count = layer.bandCount()
    bands = [b + 1 for b in bands0 if 0 <= b < count]
    if len(bands) < 3:
        return style_gray(layer)
    r, g, b = bands[:3]
    renderer = QgsMultiBandColorRenderer(provider, r, g, b)
    renderer.setRedContrastEnhancement(_enhancement(provider, r))
    renderer.setGreenContrastEnhancement(_enhancement(provider, g))
    renderer.setBlueContrastEnhancement(_enhancement(provider, b))
    layer.setRenderer(renderer)
    layer.triggerRepaint()


def style_gray(layer, band=1):
    provider = layer.dataProvider()
    renderer = QgsSingleBandGrayRenderer(provider, band)
    renderer.setContrastEnhancement(_enhancement(provider, band))
    layer.setRenderer(renderer)
    layer.triggerRepaint()


def style_index(layer, ramp_name='RdYlGn', band=1, stops=7):
    """Índice espectral (NDVI, NDWI...): rampa de cores entre os percentis 2 e 98."""
    provider = layer.dataProvider()
    vmin, vmax = _cut(provider, band)
    ramp = QgsStyle.defaultStyle().colorRamp(ramp_name)
    items = []
    for i in range(stops):
        f = i / float(stops - 1)
        color = ramp.color(f) if ramp is not None else QColor.fromHsvF(0.33 * f, 0.8, 0.8)
        value = vmin + (vmax - vmin) * f
        items.append(QgsColorRampShader.ColorRampItem(value, color, u"%.3g" % value))
    fn = QgsColorRampShader(vmin, vmax)
    fn.setColorRampType(QgsColorRampShader.Interpolated)
    fn.setColorRampItemList(items)
    shader = QgsRasterShader()
    shader.setRasterShaderFunction(fn)
    renderer = QgsSingleBandPseudoColorRenderer(provider, band, shader)
    renderer.setClassificationMin(vmin)
    renderer.setClassificationMax(vmax)
    layer.setRenderer(renderer)
    layer.triggerRepaint()


def apply_style(layer, kind, bands0=None):
    """kind: 'rgb' (com bands0), 'index', 'gray' ou None (padrão do QGIS). Nunca levanta exceção:
    a camada já está no mapa; a simbologia é só conveniência."""
    try:
        if kind == 'rgb' and bands0 and layer.bandCount() >= 3:
            style_rgb(layer, bands0)
        elif kind == 'index' and layer.bandCount() == 1:
            style_index(layer)
        elif kind == 'gray' or layer.bandCount() == 1:
            style_gray(layer)
        return True
    except Exception:
        return False
