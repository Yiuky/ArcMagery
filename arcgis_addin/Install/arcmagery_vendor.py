# -*- coding: utf-8 -*-
"""Bibliotecas embutidas no add-in (pasta vendor/).

O comtypes e necessario para garantir bandas RGB e stretch (ArcObjects). O install.bat tenta
instala-lo com o pip, mas o pip falha sem aviso em redes com inspecao SSL. Por isso uma copia
(comtypes 1.1.7, licenca MIT, vendor/comtypes/LICENSE.txt) vai junto no add-in e entra no
FINAL do sys.path: se o Python do ArcGIS ja tiver o comtypes, o instalado continua valendo.
"""
import os
import sys

VENDOR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vendor')

if os.path.isdir(VENDOR_DIR) and VENDOR_DIR not in sys.path:
    sys.path.append(VENDOR_DIR)
