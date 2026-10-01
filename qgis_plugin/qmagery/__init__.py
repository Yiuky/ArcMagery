# -*- coding: utf-8 -*-
"""
QMagery — Plugin QGIS para carregamento de imagens de satélite.
Porta do ArcMagery (ArcMap 10.8) para o QGIS 3.x.

Ponto de entrada exigido pelo Plugin Manager do QGIS.
"""


def classFactory(iface):  # noqa: N802
    """Instancia o plugin. Chamado pelo Plugin Manager do QGIS."""
    from .plugin import QMageryPlugin
    return QMageryPlugin(iface)
