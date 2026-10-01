# -*- coding: utf-8 -*-
"""
Executa toda a suite de testes do QMagery (tests/qgis/).
Equivalente ao tests/backend/run_all.py e tests/arcmap/run_all.py.
"""
import os
import sys
import unittest

# Garante que _paths.py é encontrado
sys.path.insert(0, os.path.dirname(__file__))

if __name__ == '__main__':
    loader = unittest.TestLoader()
    suite = loader.discover(os.path.dirname(__file__), pattern='test_*.py')
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
