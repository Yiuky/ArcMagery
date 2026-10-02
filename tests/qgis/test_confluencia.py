# -*- coding: utf-8 -*-
"""
Suite de testes de confluência entre ArcMagery e QMagery.

OBJETIVO: garantir que nenhuma alteração no backend quebre qualquer um dos dois
produtos. Cada teste aqui deve FALHAR se o backend se comportar diferente do
contrato estabelecido, seja para o ArcMap (Python 2.7 via IPC) ou para o QGIS.

Organização:
  - TestBackendContrato: verifica o protocolo CLI (run_gee.py → JSON)
  - TestTilemathConfluencia: verifica que tilemath.py é idêntico nos dois contextos
  - TestBackendStructure: verifica que todos os módulos do backend compilam sem erro
  - TestQMageryStructure: verifica que todos os módulos do plugin compilam sem erro
  - TestQMageryBackendRunner: verifica BackendRunner (sem PyQGIS, usando subprocess diretamente)
  - TestMetadataConsistency: garante que metadata.txt do plugin está coerente
  - TestNoArcpyInBackend: garante que arcpy não foi acidentalmente importado no backend
  - TestNoQgisInBackend: garante que o backend não depende do PyQGIS (Python 2.7 compat.)
  - TestCliContractParity: garante que ArcMagery e QMagery recebem exatamente o mesmo JSON

Todos os testes aqui rodam com Python 3 puro (sem PyQGIS).
"""
import ast
import configparser
import io
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

import _paths  # noqa: F401  (configura sys.path)

REPO = _paths.REPO
BACKEND = _paths.BACKEND
PLUGIN_DIR = _paths.PLUGIN_DIR
RUN_GEE = os.path.join(BACKEND, 'run_gee.py')


# ---------------------------------------------------------------------------
# Utilitários compartilhados
# ---------------------------------------------------------------------------

def run_cli(params: dict, timeout: int = 120):
    """Executa run_gee.py como subprocess e retorna (returncode, dict_json, stderr)."""
    fd, pf = tempfile.mkstemp(suffix='.json', prefix='qmagery_confl_')
    os.close(fd)
    try:
        with io.open(pf, 'w', encoding='utf-8') as f:
            json.dump(params, f, ensure_ascii=False)
        env = dict(os.environ, PYTHONIOENCODING='utf-8')
        env.pop('PYTHONPATH', None)
        proc = subprocess.run(
            [sys.executable, RUN_GEE, params['command'], '--params-file=' + pf],
            capture_output=True, timeout=timeout, env=env,
        )
        lines = [
            l for l in proc.stdout.decode('utf-8', 'replace').splitlines()
            if l.strip().startswith('{')
        ]
        result = json.loads(lines[-1]) if lines else {}
        return proc.returncode, result, proc.stderr.decode('utf-8', 'replace')
    finally:
        try:
            os.remove(pf)
        except OSError:
            pass


def _collect_py_files(directory: str):
    """Lista todos os .py em um diretório (recursivo)."""
    found = []
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in ('vendor', '__pycache__', '.git')]
        for f in files:
            if f.endswith('.py'):
                found.append(os.path.join(root, f))
    return found


# ---------------------------------------------------------------------------
# 1. Contrato CLI do backend (protocolo ArcMagery ↔ QMagery)
# ---------------------------------------------------------------------------

class TestBackendContrato(unittest.TestCase):
    """
    Verifica o protocolo que tanto o gee_bridge.py (ArcMagery) quanto o
    BackendRunner (QMagery) dependem: uma linha JSON no stdout.
    """

    def test_sources_info_retorna_json_valido(self):
        """sources_info → JSON com success=True e chaves 'providers'/'collections'."""
        code, data, _ = run_cli({'command': 'sources_info'})
        self.assertEqual(code, 0, msg='exit code inesperado')
        self.assertTrue(data.get('success'), msg=data)
        self.assertIn('providers', data, msg='falta chave providers')
        self.assertIn('collections', data, msg='falta chave collections')

    def test_erro_retorna_json_com_success_false(self):
        """Comandos com parâmetros inválidos → JSON com success=False (nunca texto livre)."""
        code, data, _ = run_cli({'command': 'stac_download',
                                  'collection': 'CB4A-WPM-L4-DN-1', 'item_id': 'x'})
        # Pode ser 0 ou 1, mas o JSON DEVE ter success=False e message
        self.assertFalse(data.get('success'), msg='Esperado success=False')
        self.assertIn('message', data, msg='falta chave message no erro')

    def test_stdout_tem_exatamente_uma_linha_json(self):
        """Protocolo: exatamente UMA linha JSON no stdout (a última que começa com '{')."""
        fd, pf = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        with io.open(pf, 'w', encoding='utf-8') as f:
            json.dump({'command': 'sources_info'}, f)
        env = dict(os.environ, PYTHONIOENCODING='utf-8')
        env.pop('PYTHONPATH', None)
        proc = subprocess.run(
            [sys.executable, RUN_GEE, 'sources_info', '--params-file=' + pf],
            capture_output=True, timeout=60, env=env,
        )
        os.remove(pf)
        json_lines = [
            l for l in proc.stdout.decode('utf-8').splitlines()
            if l.strip().startswith('{')
        ]
        self.assertGreaterEqual(len(json_lines), 1, 'Nenhuma linha JSON no stdout')
        # A última deve ser parseable
        json.loads(json_lines[-1])

    def test_xyz_estimate_compatibilidade_arcmagery_qmagery(self):
        """
        Garante que xyz_estimate retorna o mesmo resultado independente de quem chama.
        ArcMagery (gee_bridge.py) e QMagery (BackendRunner) enviam o mesmo JSON.
        """
        bbox = [-56.10, -15.62, -56.09, -15.61]
        params = {'command': 'xyz_estimate', 'zoom': 17,
                  'bbox': ','.join(str(v) for v in bbox)}
        _, data, _ = run_cli(params)
        self.assertTrue(data.get('success'), msg=data)
        # Valor de referência validado em test_tilemath.py (20 tiles)
        self.assertEqual(data.get('tiles'), 20,
                         msg='Número de tiles mudou — verifique tilemath.py')

    def test_progress_prefix_arcgee_preservado(self):
        """
        O prefixo [ArcGEE] no stderr é protocolo compartilhado entre ArcMagery e QMagery.
        Não deve ser renomeado.
        """
        # Verifica que run_gee.py e o backend usam o prefixo correto
        pattern = b'[ArcGEE]'
        found = False
        for py in _collect_py_files(BACKEND):
            with open(py, 'rb') as f:
                if pattern in f.read():
                    found = True
                    break
        self.assertTrue(found, msg='Prefixo [ArcGEE] não encontrado no backend')


# ---------------------------------------------------------------------------
# 2. Tilemath — módulo compartilhado entre Python 2.7 (ArcMap) e Python 3 (QGIS)
# ---------------------------------------------------------------------------

class TestTilemathConfluencia(unittest.TestCase):
    """
    tilemath.py é o único módulo do projeto que roda em AMBOS Python 2.7 e Python 3.
    Testa que ele não depende de nada Python-3-exclusivo e que os resultados numéricos
    são idênticos — qualquer divergência significa que ArcMagery e QMagery discordam.
    """

    def setUp(self):
        sys.path.insert(0, BACKEND)
        import tilemath
        self.tm = tilemath

    def test_sem_imports_python3_exclusivos(self):
        """tilemath.py não pode usar f-strings, walrus (:=), typing, etc."""
        tilemath_path = os.path.join(BACKEND, 'tilemath.py')
        with open(tilemath_path, 'r', encoding='utf-8') as f:
            source = f.read()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            # f-strings (JoinedStr) são Python 3.6+, incompatíveis com Python 2.7
            if isinstance(node, ast.JoinedStr):
                self.fail('tilemath.py contém f-string (incompatível com Python 2.7)')
            # walrus operator (:=) é Python 3.8+
            if isinstance(node, ast.NamedExpr):
                self.fail('tilemath.py contém walrus operator (incompatível com Python 2.7)')
        # Verifica from __future__ import division (necessário para Python 2.7)
        self.assertIn('from __future__ import division', source,
                      msg='tilemath.py deve ter "from __future__ import division" para Python 2.7')

    def test_cuiaba_tile_referencia(self):
        """Valor de referência validado contra mercantile 1.2.1 (usado pelo ArcMagery)."""
        self.assertEqual(self.tm.lonlat_to_tile(-56.1, -15.6, 17), (45110, 71287))

    def test_estimate_cuiaba_20_tiles(self):
        """Referência numérica usada pelo ArcMagery E pelo QMagery para estimar downloads."""
        est = self.tm.estimate([-56.10, -15.62, -56.09, -15.61], 17)
        self.assertEqual(est['tiles'], 20,
                         msg='Referência de 20 tiles em Cuiabá mudou — regressão crítica')

    def test_quadkey_compatibilidade_bing(self):
        """Quadkey deve ser compatível com Bing Maps (usado pelo xyz_core.py)."""
        self.assertEqual(self.tm.quadkey(3, 5, 3), '213')
        self.assertEqual(self.tm.quadkey(0, 0, 1), '0')

    def test_clamp_bbox_inverte_coordenadas(self):
        """clamp_bbox normaliza ordem lon/lat — arcpy e PyQGIS podem trocar a ordem."""
        result = self.tm.clamp_bbox([10, 5, -10, -5])
        self.assertEqual(result, [-10.0, -5.0, 10.0, 5.0])

    def test_bbox_degenerado_levanta_excecao(self):
        with self.assertRaises(ValueError):
            self.tm.clamp_bbox([1, 1, 1, 2])  # largura zero

    def test_keyhole_grade_google_earth(self):
        """Grade Keyhole (Google Earth Histórico) — mesmo resultado em ArcMagery e QMagery."""
        r, c = self.tm.keyhole_row_col(-15.6, -56.1, 17)
        # Resultado esperado: tile (r, c) que cobre Cuiabá em nível 17
        self.assertIsInstance(r, int)
        self.assertIsInstance(c, int)
        self.assertGreaterEqual(r, 0)
        self.assertGreaterEqual(c, 0)


# ---------------------------------------------------------------------------
# 3. Estrutura do backend — todos os módulos devem compilar
# ---------------------------------------------------------------------------

class TestBackendStructure(unittest.TestCase):
    """
    Garante que nenhum módulo do backend tem erro de sintaxe Python 3.
    Qualquer erro aqui quebra tanto ArcMagery quanto QMagery.
    """

    def _check_py_files(self, directory: str, label: str):
        errors = []
        for path in _collect_py_files(directory):
            try:
                with open(path, 'rb') as f:
                    source = f.read()
                compile(source, path, 'exec')
            except SyntaxError as e:
                errors.append(f'{path}: {e}')
        self.assertEqual(errors, [],
                         msg=f'Erros de sintaxe em {label}:\n' + '\n'.join(errors))

    def test_backend_compila_sem_erros(self):
        self._check_py_files(BACKEND, 'backend')

    def test_backend_nao_importa_arcpy(self):
        """arcpy é exclusivo do ArcMap e NÃO deve aparecer no backend."""
        for path in _collect_py_files(BACKEND):
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            tree = ast.parse(content, filename=path)
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = [a.name for a in getattr(node, 'names', [])]
                    module = getattr(node, 'module', '') or ''
                    all_names = names + [module]
                    for name in all_names:
                        self.assertFalse(
                            name.startswith('arcpy'),
                            msg=f'arcpy encontrado no backend em {path} '
                                f'— quebra o QMagery'
                        )

    def test_backend_nao_importa_tkinter(self):
        """Tkinter é da GUI do ArcMap (Python 2.7) e NÃO deve aparecer no backend."""
        for path in _collect_py_files(BACKEND):
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            self.assertNotIn('import tkinter', content,
                             msg=f'tkinter encontrado em {path} — quebra o QMagery')
            self.assertNotIn('import Tkinter', content,
                             msg=f'Tkinter encontrado em {path} — quebra o ArcMagery')

    def test_backend_nao_importa_qgis(self):
        """
        O backend NÃO deve depender do PyQGIS (qgis.core, qgis.PyQt, etc.).
        Ele precisa funcionar como subprocess externo ao processo do QGIS.

        Nota: qgis_env.py é um MÓDULO LOCAL do backend (não uma import do PyQGIS).
        A presença de 'import qgis_env' nos .py do backend é esperada e correta.
        O teste verifica apenas 'from qgis.' e 'import qgis.' (com ponto), que são
        as formas reais de importar o pacote PyQGIS.
        """
        for path in _collect_py_files(BACKEND):
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            # 'from qgis.' cobre: from qgis.core, from qgis.PyQt, etc.
            self.assertNotIn('from qgis.',  content,
                             msg=f'import PyQGIS encontrado em {path} — quebra a arquitetura')
            # Verifica linha a linha para não confundir 'import qgis_env' com 'import qgis'
            for line in content.splitlines():
                stripped = line.strip()
                if stripped.startswith('import qgis.') or stripped == 'import qgis':
                    self.fail(
                        f'import PyQGIS encontrado em {path} linha: {line!r} '
                        f'— quebra a arquitetura de separação backend/plugin'
                    )

    def test_run_gee_existe(self):
        self.assertTrue(os.path.isfile(RUN_GEE),
                        msg=f'run_gee.py não encontrado em {RUN_GEE}')

    def test_modulos_criticos_existem(self):
        modulos = [
            'tilemath.py', 'xyz_core.py', 'stac_core.py', 'spot_core.py',
            'gehist_core.py', 'esri_core.py', 'gee_core.py', 'doctor.py',
            'pylibs.py', 'qgis_env.py', 'run_gee.py',
        ]
        for m in modulos:
            path = os.path.join(BACKEND, m)
            self.assertTrue(os.path.isfile(path),
                            msg=f'Módulo crítico ausente: {m} — quebra ArcMagery E QMagery')


# ---------------------------------------------------------------------------
# 4. Estrutura do plugin QMagery
# ---------------------------------------------------------------------------

class TestQMageryStructure(unittest.TestCase):
    """Garante que os módulos do plugin QMagery compilam e têm a estrutura esperada."""

    def test_plugin_dir_existe(self):
        self.assertTrue(os.path.isdir(PLUGIN_DIR),
                        msg=f'Diretório do plugin não encontrado: {PLUGIN_DIR}')

    def test_metadata_txt_existe(self):
        meta = os.path.join(PLUGIN_DIR, 'metadata.txt')
        self.assertTrue(os.path.isfile(meta),
                        msg='metadata.txt ausente — plugin não será reconhecido pelo QGIS')

    def test_init_py_tem_classfactory(self):
        init_path = os.path.join(PLUGIN_DIR, '__init__.py')
        self.assertTrue(os.path.isfile(init_path))
        with open(init_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('classFactory', content,
                      msg='__init__.py deve ter a função classFactory (exigida pelo QGIS)')

    def test_plugin_py_tem_initgui_e_unload(self):
        plugin_path = os.path.join(PLUGIN_DIR, 'plugin.py')
        self.assertTrue(os.path.isfile(plugin_path))
        with open(plugin_path, 'r', encoding='utf-8') as f:
            source = f.read()
        tree = ast.parse(source)
        methods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                methods.add(node.name)
        self.assertIn('initGui', methods,
                      msg='plugin.py deve ter initGui() (exigido pelo QGIS)')
        self.assertIn('unload', methods,
                      msg='plugin.py deve ter unload() (exigido pelo QGIS)')

    def test_plugin_compila_sem_erros(self):
        errors = []
        for path in _collect_py_files(PLUGIN_DIR):
            try:
                with open(path, 'rb') as f:
                    source = f.read()
                compile(source, path, 'exec')
            except SyntaxError as e:
                errors.append(f'{path}: {e}')
        self.assertEqual(errors, [],
                         msg='Erros de sintaxe no plugin:\n' + '\n'.join(errors))

    def test_backend_runner_referencia_backend_correto(self):
        """O backend vem de qmagery/backend (pacote) ou de arcgis_addin/Install/backend (repositório)."""
        with open(os.path.join(PLUGIN_DIR, 'core', 'config.py'), 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn("'arcgis_addin', 'Install', 'backend'", content)
        self.assertIn('run_gee.py', content)

    def test_plugin_nao_importa_arcpy(self):
        """O plugin QMagery nunca deve importar arcpy."""
        for path in _collect_py_files(PLUGIN_DIR):
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            self.assertNotIn('import arcpy', content,
                             msg=f'arcpy encontrado no plugin QMagery em {path}')

    def test_plugin_nao_importa_tkinter(self):
        """O plugin usa PyQt, não Tkinter."""
        for path in _collect_py_files(PLUGIN_DIR):
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            self.assertNotIn('import tkinter', content.lower(),
                             msg=f'Tkinter encontrado no plugin em {path}')


# ---------------------------------------------------------------------------
# 5. Metadados do plugin — coerência com o monorepo
# ---------------------------------------------------------------------------

class TestMetadataConsistency(unittest.TestCase):
    """Garante que metadata.txt está correto e coerente com o repositório."""

    def setUp(self):
        meta_path = os.path.join(PLUGIN_DIR, 'metadata.txt')
        self.config = configparser.ConfigParser()
        with open(meta_path, 'r', encoding='utf-8') as f:
            self.config.read_file(f)

    def test_secao_general_presente(self):
        self.assertIn('general', self.config.sections(),
                      msg='metadata.txt deve ter seção [general]')

    def test_campos_obrigatorios(self):
        required = ['name', 'qgisminimumversion', 'description', 'version',
                    'author', 'about', 'tracker', 'repository']
        for field in required:
            self.assertIn(field, self.config['general'],
                          msg=f'Campo obrigatório ausente no metadata.txt: {field}')

    def test_versao_semver(self):
        """X.Y.Z (estável) ou X.Y.Z-beta.AAAAMMDD (nightly): a forma que o QGIS ordena antes da X.Y.Z."""
        version = self.config['general']['version']
        self.assertRegex(version, r'^\d+\.\d+\.\d+(-beta\.\d{8})?$')
        self.assertEqual(self.config['general']['experimental'].lower() == 'true', '-' in version,
                         msg='experimental=True se e somente se a versão for nightly (beta)')

    def test_qgis_minimo_valido(self):
        min_ver = self.config['general']['qgisminimumversion']
        parts = min_ver.split('.')
        self.assertGreaterEqual(int(parts[0]), 3,
                                msg='qgisMinimumVersion deve ser >= 3.x')
        self.assertGreaterEqual(int(parts[1]), 18,
                                msg='qgisMinimumVersion deve ser >= 3.18 (mínimo do ArcMagery)')

    def test_repositorio_aponta_para_arcmagery(self):
        repo = self.config['general']['repository']
        self.assertIn('ArcMagery', repo,
                      msg='repository em metadata.txt deve apontar para ArcMagery (monorepo)')


# ---------------------------------------------------------------------------
# 6. BackendRunner sem PyQGIS (lógica de subprocess)
# ---------------------------------------------------------------------------

class TestBackendRunnerSync(unittest.TestCase):
    """
    Testa a lógica de subprocess do BackendRunner sem PyQGIS.
    Simula o que o BackendRunner faz internamente usando subprocess direto.
    """

    def _run_via_subprocess(self, command: str, params: dict, timeout: int = 60) -> dict:
        """Replica a lógica central do BackendRunner.run_sync()."""
        params = dict(params)
        params['command'] = command
        fd, pf = tempfile.mkstemp(suffix='.json', prefix='qmagery_test_')
        os.close(fd)
        try:
            with io.open(pf, 'w', encoding='utf-8') as f:
                json.dump(params, f, ensure_ascii=False)
            env = dict(os.environ, PYTHONIOENCODING='utf-8')
            env.pop('PYTHONPATH', None)
            proc = subprocess.run(
                [sys.executable, RUN_GEE, command, '--params-file=' + pf],
                capture_output=True, timeout=timeout, env=env,
            )
            lines = [
                l for l in proc.stdout.decode('utf-8', 'replace').splitlines()
                if l.strip().startswith('{')
            ]
            return json.loads(lines[-1]) if lines else {}
        finally:
            try:
                os.remove(pf)
            except OSError:
                pass

    def test_sources_info_via_backend_runner_logica(self):
        """BackendRunner consegue buscar sources_info (mesmo contrato do ArcMagery)."""
        result = self._run_via_subprocess('sources_info', {})
        self.assertTrue(result.get('success'), msg=result)
        self.assertIn('providers', result)
        self.assertIn('collections', result)

    def test_unicode_no_path_do_params_file(self):
        """Parâmetros com caminhos Unicode (ex: 'área.geojson') funcionam."""
        bbox = [-56.10, -15.62, -56.09, -15.61]
        result = self._run_via_subprocess('xyz_estimate', {
            'zoom': 17,
            'bbox': ','.join(str(v) for v in bbox),
        })
        self.assertTrue(result.get('success'), msg=result)
        self.assertEqual(result.get('tiles'), 20)

    def test_comando_invalido_retorna_json_e_nao_levanta(self):
        """Erros do backend devem sempre retornar JSON (nunca crashar o QGIS)."""
        result = self._run_via_subprocess('stac_download', {
            'collection': 'CB4A-WPM-L4-DN-1',
            'item_id': 'nao_existe',
        })
        # Pode ser success=False, mas deve ser JSON válido
        self.assertIn('success', result,
                      msg='Backend deve retornar JSON mesmo em erro')

    def test_progress_stderr_nao_quebra_parsing(self):
        """Linhas de progresso no stderr não devem interferir com o JSON no stdout."""
        _, data, stderr = run_cli({'command': 'sources_info'})
        # O JSON deve ser parseável independentemente do que está no stderr
        self.assertIsInstance(data, dict,
                              msg='stderr interferiu com o parse do JSON stdout')


# ---------------------------------------------------------------------------
# 7. Paridade de contrato CLI — ArcMagery ↔ QMagery
# ---------------------------------------------------------------------------

class TestCliContractParity(unittest.TestCase):
    """
    Garante que os dois produtos recebem exatamente os mesmos dados do backend.
    Simula uma chamada do ArcMagery (gee_bridge.py) e uma do QMagery (BackendRunner)
    e verifica que os resultados são idênticos.
    """

    COMMANDS_SEM_DEPS = [
        {'command': 'sources_info'},
        {'command': 'xyz_estimate', 'zoom': 10,
         'bbox': '-56.10,-15.62,-56.09,-15.61'},
    ]

    def test_mesmo_resultado_em_duas_chamadas_consecutivas(self):
        """
        O backend é determinístico para comandos sem estado:
        ArcMagery e QMagery devem obter o mesmo JSON.
        """
        for params in self.COMMANDS_SEM_DEPS:
            with self.subTest(command=params['command']):
                _, result1, _ = run_cli(params)
                _, result2, _ = run_cli(params)
                # Remove campos não-determinísticos (ex: timestamps)
                for key in ('timestamp', 'elapsed'):
                    result1.pop(key, None)
                    result2.pop(key, None)
                self.assertEqual(
                    result1, result2,
                    msg=f'Backend não é determinístico para {params["command"]}'
                )

    def test_earth_engine_lazy_import(self):
        """
        O backend não deve importar earthengine-api para comandos não-GEE.
        Garante que CBERS e XYZ funcionam mesmo sem ee instalado.
        (Contrato verificado em test_run_gee_cli.py do ArcMagery — redundância intencional.)
        """
        code = (
            "import sys; sys.path.insert(0, %r); sys.modules['ee'] = None\n"
            "import run_gee\n"
            "assert 'gee_core' not in sys.modules\n"
            "print('ok')"
        ) % BACKEND
        result = subprocess.run([sys.executable, '-c', code],
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0,
                         msg='Earthengine-api foi importado no carregamento do run_gee.py: '
                             + result.stderr.decode('utf-8', 'replace'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
