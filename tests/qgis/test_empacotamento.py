# -*- coding: utf-8 -*-
"""
Distribuição do QMagery: pacote QMagery-<versão>.zip, repositório de plugins do QGIS (plugins.xml),
versões e localização do backend. Roda no CI (sem QGIS).
"""
import configparser
import hashlib
import io
import os
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import _paths  # noqa: E402

sys.path.insert(0, _paths.REPO)
sys.path.insert(0, os.path.join(_paths.REPO, 'tools'))
import build_release  # noqa: E402
import qgis_repo  # noqa: E402
from qmagery.core import config  # noqa: E402

HAS_GIT = shutil.which('git') is not None and os.path.isdir(os.path.join(_paths.REPO, '.git'))


def metadata():
    p = configparser.ConfigParser(interpolation=None)
    p.optionxform = str
    with io.open(os.path.join(_paths.PLUGIN_DIR, 'metadata.txt'), encoding='utf-8') as f:
        p.read_file(f)
    return dict(p['general'])


class Versoes(unittest.TestCase):

    def test_metadata_acompanha_a_versao_do_projeto(self):
        self.assertEqual(metadata()['version'], qgis_repo.qgis_version(build_release.read_version()))

    def test_nightly_vira_beta_para_o_qgis(self):
        # para o QGIS, "2.4.3-nightly.X" seria MAIS NOVA que "2.4.3" (a estável nunca seria oferecida)
        self.assertEqual(qgis_repo.qgis_version('2.4.3-nightly.20261002'), '2.4.3-beta.20261002')
        self.assertEqual(qgis_repo.qgis_version('2.4.3'), '2.4.3')
        k = qgis_repo.version_key
        self.assertLess(k('2.4.3-beta.20261002'), k('2.4.3'))
        self.assertLess(k('2.4.3-beta.20261002'), k('2.4.3-beta.20261005'))
        self.assertLess(k('2.4.3'), k('2.4.4-beta.20261101'))

    def test_versao_exibida_vem_do_metadata(self):
        self.assertEqual(config.plugin_version(), metadata()['version'])
        self.assertIn(metadata()['version'], config.version_label())
        for rel in ('gui/main_dialog.py', 'gui/support_dialogs.py'):
            src = io.open(os.path.join(_paths.PLUGIN_DIR, rel), encoding='utf-8').read()
            self.assertNotIn('1.0.0', src, msg='versão fixa em %s' % rel)


class LocalizacaoDoBackend(unittest.TestCase):

    def test_pacote_usa_o_backend_embutido(self):
        tmp = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(tmp, 'qmagery', 'backend'))
            io.open(os.path.join(tmp, 'qmagery', 'backend', 'run_gee.py'), 'w').close()
            self.assertEqual(config.backend_dir(os.path.join(tmp, 'qmagery')),
                             os.path.normpath(os.path.join(tmp, 'qmagery', 'backend')))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_repositorio_usa_o_backend_do_arcmagery(self):
        self.assertEqual(os.path.normcase(config.backend_dir()), os.path.normcase(_paths.BACKEND))

    def test_configuracao_fica_fora_da_pasta_do_plugin(self):
        # o Gerenciador de Complementos apaga a pasta do plugin a cada atualização
        for path in (config.gee_config_file(), config.geodes_config_file(), config.settings_file()):
            self.assertFalse(os.path.normcase(path).startswith(os.path.normcase(_paths.PLUGIN_DIR)), msg=path)
            self.assertEqual(os.path.basename(os.path.dirname(path)), 'ArcGEE')


@unittest.skipUnless(HAS_GIT, 'requer git e o repositório clonado')
class Pacotes(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.dist = tempfile.mkdtemp(prefix='qmagery_dist_')
        build_release.build(cls.dist)
        cls.version = build_release.read_version()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dist, ignore_errors=True)

    def test_zip_do_qmagery_instalavel_pelo_qgis(self):
        path = os.path.join(self.dist, 'QMagery-%s.zip' % self.version)
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            self.assertTrue(all(n.startswith('qmagery/') for n in names), msg='a raiz deve ser a pasta qmagery/')
            for required in ('qmagery/__init__.py', 'qmagery/metadata.txt', 'qmagery/plugin.py', 'qmagery/LICENSE',
                             'qmagery/backend/run_gee.py', 'qmagery/backend/pylibs_manifest.json',
                             'qmagery/backend/ee_auth.py', 'qmagery/resources/icons/icon64.png',
                             'qmagery/core/config.py', 'qmagery/core/sources.py', 'qmagery/gui/main_dialog.py'):
                self.assertIn(required, names)
            self.assertFalse([n for n in names if '__pycache__' in n or n.endswith('.pyc') or '/tests/' in n])
            meta = z.read('qmagery/metadata.txt').decode('utf-8')
            self.assertIn('version=%s' % qgis_repo.qgis_version(self.version), meta)

    def test_sha256sums_lista_os_dois_pacotes_com_o_arcmagery_primeiro(self):
        with io.open(os.path.join(self.dist, 'SHA256SUMS.txt'), encoding='ascii') as f:
            lines = [l.split() for l in f.read().splitlines()]
        self.assertEqual([n for _h, n in lines], ['ArcMagery-%s.zip' % self.version, 'QMagery-%s.zip' % self.version])
        for digest, name in lines:
            with open(os.path.join(self.dist, name), 'rb') as f:
                self.assertEqual(hashlib.sha256(f.read()).hexdigest(), digest)

    def test_pacotes_reprodutiveis(self):
        other = tempfile.mkdtemp(prefix='qmagery_dist2_')
        try:
            build_release.build(other)
            with io.open(os.path.join(self.dist, 'SHA256SUMS.txt')) as a, io.open(os.path.join(other, 'SHA256SUMS.txt')) as b:
                self.assertEqual(a.read(), b.read())
        finally:
            shutil.rmtree(other, ignore_errors=True)


class RepositorioDePlugins(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.xml = os.path.join(self.tmp, 'plugins.xml')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def meta(self, version):
        return dict(metadata(), version=qgis_repo.qgis_version(version))

    def entries(self):
        return dict((n.find('experimental').text, n) for n in ET.parse(self.xml).getroot().findall('pyqgis_plugin'))

    def update(self, version, date='2026-10-02'):
        return qgis_repo.update(version, self.xml, self.meta(version), date)

    def test_canais_estavel_e_experimental(self):
        self.update('2.4.3-nightly.20261002')
        e = self.entries()
        self.assertEqual(list(e), ['True'])
        node = e['True']
        self.assertEqual(node.get('version'), '2.4.3-beta.20261002')
        # o QGIS identifica o plugin pelo texto do file_name antes do primeiro ponto
        self.assertTrue(node.find('file_name').text.startswith('qmagery.'))
        self.assertEqual(node.find('download_url').text,
                         'https://github.com/Yiuky/ArcMagery/releases/download/v2.4.3-nightly.20261002/'
                         'QMagery-2.4.3-nightly.20261002.zip')
        self.assertEqual(node.find('qgis_minimum_version').text, '3.18.0')

        self.update('2.4.3')                       # a estável alcança a nightly: a experimental sai
        self.assertEqual(list(self.entries()), ['False'])
        self.update('2.4.4-nightly.20261101')      # nova nightly convive com a estável
        e = self.entries()
        self.assertEqual((e['False'].get('version'), e['True'].get('version')), ('2.4.3', '2.4.4-beta.20261101'))
        self.assertFalse(self.update('2.4.4-nightly.20261020'))   # mais velha não substitui
        self.assertEqual(self.entries()['True'].get('version'), '2.4.4-beta.20261101')

    def test_metadata_divergente_e_recusado(self):
        with self.assertRaises(SystemExit):
            qgis_repo.update('2.4.3', self.xml, dict(metadata(), version='9.9.9'), '2026-10-02')

    def test_xml_publicado_e_valido(self):
        path = os.path.join(_paths.PLUGIN_ROOT, 'plugins.xml')
        if not os.path.exists(path):
            self.skipTest('plugins.xml ainda não publicado')
        for node in ET.parse(path).getroot().findall('pyqgis_plugin'):
            self.assertEqual(node.get('name'), 'QMagery')
            self.assertTrue(node.find('file_name').text.startswith('qmagery.'))
            self.assertTrue(node.find('download_url').text.startswith(
                'https://github.com/Yiuky/ArcMagery/releases/download/v'))


if __name__ == '__main__':
    unittest.main()
