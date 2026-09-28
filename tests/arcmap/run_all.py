# -*- coding: utf-8 -*-
"""Executa a suite do lado ArcMap/GUI com o Python 2.7 do ArcGIS:

    C:\\Python27\\ArcGIS10.8\\python.exe tests\\arcmap\\run_all.py [-v]
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

if __name__ == '__main__':
    if sys.version_info[0] != 2:
        sys.stderr.write("Esta suite deve rodar no Python 2.7 do ArcGIS.\n")
        sys.exit(2)
    suite = unittest.defaultTestLoader.discover(HERE, pattern='test_*.py', top_level_dir=HERE)
    result = unittest.TextTestRunner(verbosity=2 if '-v' in sys.argv else 1).run(suite)
    sys.stdout.flush()
    os._exit(0 if result.wasSuccessful() else 1)
