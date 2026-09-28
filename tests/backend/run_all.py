# -*- coding: utf-8 -*-
"""Executa a suite do backend (Python 3). Uso: python tests/backend/run_all.py [-v]

Variaveis opcionais:
  ARCMAGERY_LIVE=1                 habilita testes com internet (INPE, Esri, Google)
  ARCMAGERY_GEE_PROJECT=<id>       habilita o teste real no Earth Engine (exige credenciais)
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

if __name__ == '__main__':
    suite = unittest.defaultTestLoader.discover(HERE, pattern='test_*.py', top_level_dir=HERE)
    verbosity = 2 if '-v' in sys.argv else 1
    result = unittest.TextTestRunner(verbosity=verbosity).run(suite)
    sys.stdout.flush()
    sys.stderr.flush()
    # os._exit: threads do GDAL/curl (/vsicurl/) podem impedir o encerramento normal
    os._exit(0 if result.wasSuccessful() else 1)
