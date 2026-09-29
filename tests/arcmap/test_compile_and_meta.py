# -*- coding: utf-8 -*-
"""Compila todos os modulos do lado ArcMap em Python 2.7 e confere a consistencia de versao/nome."""
from __future__ import print_function

import glob
import io
import os
import re
import unittest
import xml.etree.ElementTree as ET

import _paths

PY2_FILES = glob.glob(os.path.join(_paths.INSTALL, '*.py')) + [
    os.path.join(_paths.REPO, 'pyt', 'GEE_Tools.pyt'),
    os.path.join(_paths.REPO, 'arcgis_addin', 'makeaddin.py'),
    os.path.join(_paths.REPO, 'build_release.py'),
    os.path.join(_paths.BACKEND, 'tilemath.py'),   # compartilhado com a GUI (Py2) e o backend (Py3)
]


class CompileTest(unittest.TestCase):
    def test_all_py2_modules_compile(self):
        errors = []
        for path in PY2_FILES:
            try:
                compile(io.open(path, 'rb').read(), path, 'exec')
            except SyntaxError as e:
                errors.append('%s:%s %s' % (path, e.lineno, e.msg))
        self.assertEqual(errors, [])


class MetadataTest(unittest.TestCase):
    def setUp(self):
        tree = ET.parse(os.path.join(_paths.REPO, 'arcgis_addin', 'config.xml'))
        ns = {'e': 'http://schemas.esri.com/Desktop/AddIns'}
        self.version = tree.getroot().find('e:Version', ns).text.strip()
        self.name = tree.getroot().find('e:Name', ns).text.strip()
        self.addin_id = tree.getroot().find('e:AddInID', ns).text.strip()

    def test_name_and_stable_addin_id(self):
        self.assertEqual(self.name, 'ArcMagery')
        # O AddInID NAO pode mudar: instalacoes existentes dependem dele para atualizar
        self.assertEqual(self.addin_id.lower(), '{ceae58c4-c44e-4edd-b8f4-1ba7d13b6b7d}')

    def test_versions_are_consistent(self):
        gui = io.open(os.path.join(_paths.INSTALL, 'gee_gui.py'), encoding='utf-8').read()
        m = re.search(r'^CURRENT_VERSION = "([^"]+)"', gui, re.M)
        self.assertEqual(m.group(1), self.version)
        upd = io.open(os.path.join(_paths.INSTALL, 'gee_updater.py'), encoding='utf-8').read()
        for v in re.findall(r'current_version="([^"]+)"', upd):
            self.assertEqual(v, self.version)
        self.assertNotIn('v1.12', gui)
        readme = io.open(os.path.join(_paths.REPO, 'README.md'), encoding='utf-8').read()
        badge = re.search(u'Versão-v([0-9.]+)-', readme)
        self.assertTrue(badge, u"selo de versao nao encontrado no README")
        self.assertEqual(badge.group(1), self.version, u"selo de versao do README desatualizado")

    def test_old_product_name_not_visible(self):
        for fname in ('gee_gui.py', 'arcmagery_sources_gui.py'):
            src = io.open(os.path.join(_paths.INSTALL, fname), encoding='utf-8').read()
            self.assertNotIn(u'CGMA ArcGEE Explorer', src, fname)
        cfg = io.open(os.path.join(_paths.REPO, 'arcgis_addin', 'config.xml'), encoding='utf-8').read()
        self.assertNotIn(u'ArcGEE', cfg)

    def test_single_backend_copy(self):
        self.assertFalse(os.path.exists(os.path.join(_paths.REPO, 'backend', 'gee_core.py')),
                         "backend duplicado na raiz: a fonte unica e arcgis_addin/Install/backend")


if __name__ == '__main__':
    unittest.main()
