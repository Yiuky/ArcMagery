# -*- coding: utf-8 -*-
"""
Suíte abrangente de testes para os botões e controle de cancelamento da GUI do QMagery.

Testa especificamente:
1. Eliminação da tela preta do console (CREATE_NO_WINDOW / SW_HIDE).
2. Botão '■ Interromper' e terminação imediata do processo em segundo plano (taskkill / kill).
3. Botões de atalho de data (30d, 60d, 90d, 180d).
4. Botões seletores de fonte (GEE, INPE, SPOT, Google Earth Hist., Esri Wayback).
5. Botões de ação do TOC e escala (Ajustar 1:500.000, Atualizar TOC).
6. Estado dos botões de ação conforme a seleção de imagens (Carregar, Miniatura, Substituir).
7. Restauração suave da interface e supressão de modais de erro após interrupção pelo usuário.
"""
import os
import sys
import time
import subprocess
import tempfile
import unittest
from datetime import date, timedelta
from typing import Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import _paths

plugin_dir = _paths.PLUGIN_ROOT
if plugin_dir not in sys.path:
    sys.path.insert(0, plugin_dir)


class TestBackendSubprocessFlagsAndCancellation(unittest.TestCase):
    """Testes para garantir que o backend nunca abra tela preta e cancele imediatamente."""

    def test_subprocess_kwargs_no_window_on_windows(self):
        """No Windows, deve incluir CREATE_NO_WINDOW e SW_HIDE."""
        from qmagery.core.backend_runner import _get_subprocess_kwargs
        kwargs = _get_subprocess_kwargs()
        if sys.platform == 'win32':
            self.assertIn('creationflags', kwargs)
            self.assertEqual(kwargs['creationflags'], 0x08000000)
            self.assertIn('startupinfo', kwargs)
            si = kwargs['startupinfo']
            self.assertTrue(si.dwFlags & subprocess.STARTF_USESHOWWINDOW)
            self.assertEqual(si.wShowWindow, subprocess.SW_HIDE)
        else:
            self.assertEqual(kwargs, {})

    def test_worker_cancellation_terminates_process_immediately(self):
        """Verifica que o worker cancela imediatamente e encerra o processo sem travar."""
        from qmagery.core.backend_runner import _BackendWorker, _get_subprocess_kwargs, get_python_executable

        # Cria um worker simulado com um processo que duraria 15 segundos
        worker = _BackendWorker('sleep_test', {})
        py_exe = get_python_executable()

        # Inicia processo longo
        proc = subprocess.Popen(
            [py_exe, '-c', 'import time; time.sleep(15)'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **_get_subprocess_kwargs()
        )
        worker._proc = proc

        self.assertIsNone(proc.poll(), "O processo deveria estar em execução")

        t0 = time.time()
        worker.cancel()
        # Aguarda brevemente para garantir terminação
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            self.fail("O processo não foi terminado dentro de 3 segundos após cancel()!")
        finally:
            if proc.stdout:
                proc.stdout.close()
            if proc.stderr:
                proc.stderr.close()

        elapsed = time.time() - t0
        self.assertLess(elapsed, 4.0, f"Cancelamento demorou {elapsed:.2f}s, esperado < 4s")
        self.assertIsNotNone(proc.poll(), "O processo deve estar finalizado após o cancel")


class TestGuiButtonsFunctionality(unittest.TestCase):
    """Testes unitários para cada botão da interface do QMagery."""

    @classmethod
    def setUpClass(cls):
        _paths.ensure_qgis_app()

    def setUp(self):
        if not _paths.HAS_PYQGIS:
            self.skipTest("Requer ambiente PyQGIS")

        from qgis.core import QgsRectangle, QgsCoordinateReferenceSystem

        class MockCanvas:
            def __init__(self):
                self._scale = 250000.0

            def extent(self):
                return QgsRectangle(-56.15, -15.65, -56.05, -15.55)

            def scale(self):
                return self._scale

            def zoomScale(self, s):
                self._scale = s

            def mapSettings(self):
                class Settings:
                    def destinationCrs(self):
                        return QgsCoordinateReferenceSystem("EPSG:4326")
                return Settings()

        canvas = MockCanvas()

        class MockIface:
            def mainWindow(self):
                return None

            def mapCanvas(self):
                return canvas

        from qmagery.gui.main_dialog import MainDialog
        self.dlg = MainDialog(iface=MockIface(), auto_check=False)

    def tearDown(self):
        if hasattr(self, 'dlg') and self.dlg:
            if self.dlg._runner:
                self.dlg._runner.cancel()
            if self.dlg._check_runner:
                self.dlg._check_runner.cancel()
            self.dlg.close()

    def test_quick_date_buttons(self):
        """Testa se os botões de atalho de datas [30d, 60d, 90d, 180d] calculam o intervalo correto."""
        today = date.today()
        today_str = today.strftime("%d/%m/%Y")

        for days in [30, 60, 90, 180]:
            btn = self.dlg._quick_date_buttons.get(days)
            self.assertIsNotNone(btn, f"Botão {days}d não encontrado")
            btn.click()

            expected_start = (today - timedelta(days=days)).strftime("%d/%m/%Y")
            self.assertEqual(self.dlg._txt_end.text(), today_str)
            self.assertEqual(self.dlg._txt_start.text(), expected_start)

    def test_source_radio_buttons_and_labels(self):
        """Testa se clicar nos botões de fonte altera o sensor e o texto do botão de busca."""
        sources = {
            'gee': '[ Buscar Imagens no GEE ]',
            'inpe': '[ Buscar Cenas no INPE ]',
            'spot': '[ Buscar Cenas SPOT (GEODES) ]',
            'gehist': '[ Listar Datas do Google Earth ]',
            'wayback': '[ Listar Versões do Esri Wayback ]',
        }
        for src, expected_search_text in sources.items():
            self.dlg._on_source_toggled(src, True)
            self.assertEqual(self.dlg._current_source, src)
            self.assertEqual(self.dlg._btn_search.text(), expected_search_text)
            self.assertGreater(self.dlg._cbo_sensor.count(), 0)

    def test_fit_scale_button(self):
        """Testa o botão 'Ajustar 1:500.000' do topo (ajusta para 450.000, abaixo de 500k)."""
        self.dlg.iface.mapCanvas()._scale = 100000.0
        self.dlg._btn_fit.click()
        self.assertEqual(self.dlg.iface.mapCanvas().scale(), 450000.0)
        self.assertIn("1:450.000", self.dlg._lbl_scale.text())

    def test_table_selection_controls_action_buttons(self):
        """Testa habilitação/desabilitação dos botões de ação conforme seleção da tabela."""
        from qgis.PyQt.QtWidgets import QTableWidgetItem

        # Insere 2 linhas simuladas
        self.dlg._table.setRowCount(0)
        self.dlg._images_cache = [
            {"id": "COPERNICUS/S2/IMG1", "date": "2026-10-01", "clouds": 2.5},
            {"id": "COPERNICUS/S2/IMG2", "date": "2026-09-30", "clouds": 8.0},
        ]
        for i, item in enumerate(self.dlg._images_cache):
            self.dlg._table.insertRow(i)
            self.dlg._table.setItem(i, 0, QTableWidgetItem(item["date"]))
            self.dlg._table.setItem(i, 1, QTableWidgetItem(str(item["clouds"])))
            self.dlg._table.setItem(i, 2, QTableWidgetItem("T21KTT"))
            self.dlg._table.setItem(i, 3, QTableWidgetItem(item["id"]))
            self.dlg._table.setItem(i, 4, QTableWidgetItem("Disponível"))

        # Caso 1: Nenhuma seleção
        self.dlg._table.clearSelection()
        self.dlg._on_table_selection_changed()
        self.assertFalse(self.dlg._btn_load.isEnabled())
        self.assertFalse(self.dlg._btn_thumb.isEnabled())
        self.assertFalse(self.dlg._btn_replace.isEnabled())

        # Caso 2: 1 linha selecionada
        self.dlg._table.selectRow(0)
        self.dlg._on_table_selection_changed()
        self.assertTrue(self.dlg._btn_load.isEnabled())
        self.assertTrue(self.dlg._btn_thumb.isEnabled())

        # Caso 3: Múltiplas linhas selecionadas
        self.dlg._table.selectAll()
        self.dlg._on_table_selection_changed()
        self.assertTrue(self.dlg._btn_load.isEnabled())
        self.assertFalse(self.dlg._btn_thumb.isEnabled(), "Miniatura deve desabilitar com seleção múltipla")
        self.assertFalse(self.dlg._btn_replace.isEnabled(), "Substituição deve desabilitar com seleção múltipla")

    def test_cancel_button_restores_interface_state(self):
        """Testa se clicar em '■ Interromper' restaura o estado da GUI imediatamente."""
        # Simula estado em que uma operação estava rodando
        self.dlg._btn_search.setEnabled(False)
        self.dlg._btn_cancel.setEnabled(True)
        self.dlg._pbar.setValue(45)
        self.dlg._lbl_pct.setText("45%")

        # Clica em Interromper
        self.dlg._btn_cancel.click()

        self.assertTrue(self.dlg._btn_search.isEnabled(), "Botão de busca deve ser reabilitado após cancelamento")
        self.assertFalse(self.dlg._btn_cancel.isEnabled(), "Botão de interromper deve ser desabilitado após cancelamento")
        self.assertEqual(self.dlg._pbar.value(), 0, "Barra de progresso deve ser resetada")
        self.assertEqual(self.dlg._lbl_pct.text(), "0%")
        self.assertIn("interrompida", self.dlg._lbl_progress.text().lower())

    def test_quiet_error_handling_on_cancellation(self):
        """Verifica que mensagens com 'cancelad' ou 'interrompid' não travam a UI com erro crítico."""
        self.dlg._btn_search.setEnabled(False)
        self.dlg._btn_cancel.setEnabled(True)

        # Dispara erro simulando cancelamento
        self.dlg._on_search_error("Operação cancelada pelo usuário.")
        self.assertTrue(self.dlg._btn_search.isEnabled())
        self.assertFalse(self.dlg._btn_cancel.isEnabled())
        self.assertIn("interrompida", self.dlg._lbl_progress.text().lower())

        # Dispara erro de carga simulando cancelamento
        self.dlg._btn_cancel.setEnabled(True)
        self.dlg._on_load_error("Download cancelado pelo usuário.")
        self.assertFalse(self.dlg._btn_cancel.isEnabled())
        self.assertIn("interrompido", self.dlg._lbl_progress.text().lower())

    def test_top_bar_project_config_button(self):
        """Testa o botão 'Configurar Projeto GEE'."""
        from unittest.mock import patch
        with patch('qgis.PyQt.QtWidgets.QInputDialog.getText', return_value=('novo-projeto-gee-123', True)):
            with patch.object(self.dlg, 'check_gee_connection') as mock_check:
                self.dlg._btn_proj.click()
                self.assertEqual(self.dlg._gee_project, 'novo-projeto-gee-123')
                mock_check.assert_called_once()

    def test_top_bar_verify_gee_connection_button(self):
        """Testa o botão 'Verificar conexão'."""
        self.dlg._lbl_status.setText("Status Anterior")
        self.dlg._btn_check.click()
        self.assertEqual(self.dlg._lbl_status_icon.text(), "[*]")
        self.assertIn("Verificando", self.dlg._lbl_status.text())

    def test_top_bar_dialog_buttons_settings_and_about(self):
        """Testa botões '⚙ Configurações' e 'ℹ Sobre'."""
        from unittest.mock import patch
        with patch('qmagery.gui.support_dialogs.SettingsDialog.exec_', return_value=1) as mock_sett:
            self.dlg._btn_settings.click()
            mock_sett.assert_called_once()

        with patch('qmagery.gui.support_dialogs.AboutDialog.exec_', return_value=1) as mock_about:
            self.dlg._btn_about.click()
            mock_about.assert_called_once()

    def test_extra_sources_button(self):
        """Testa o botão 'Google Earth / XYZ...'."""
        from unittest.mock import patch
        with patch('qmagery.gui.support_dialogs.ExtraSourcesDialog.exec_', return_value=1) as mock_xyz:
            self.dlg._btn_xyz.click()
            mock_xyz.assert_called_once()

    def test_toc_refresh_button(self):
        """Testa o botão 'Atualizar' camadas do TOC."""
        self.dlg._btn_ref_toc.click()
        self.assertGreater(self.dlg._cbo_toc.count(), 0)

    def test_search_button_triggers_runner_and_ui_states(self):
        """Testa se o botão de busca invoca o backend e altera o estado da interface."""
        from unittest.mock import patch, MagicMock
        with patch('qmagery.gui.main_dialog.BackendRunner') as mock_runner_cls:
            mock_runner = MagicMock()
            mock_runner_cls.return_value = mock_runner

            self.dlg._btn_search.click()

            self.assertFalse(self.dlg._btn_search.isEnabled())
            self.assertTrue(self.dlg._btn_cancel.isEnabled())
            mock_runner.run.assert_called_once()
            args, _ = mock_runner.run.call_args
            self.assertEqual(args[0], 'search')
            self.assertIn('sensor', args[1])

    def test_load_button_triggers_runner_and_ui_states(self):
        """Testa se o botão 'Carregar no QGIS' invoca o backend e atualiza a barra de status."""
        from unittest.mock import patch, MagicMock
        from qgis.PyQt.QtWidgets import QTableWidgetItem

        # Preenche uma cena simulada
        self.dlg._table.setRowCount(0)
        self.dlg._images_cache = [{"id": "COPERNICUS/S2/IMG1", "date": "2026-10-01"}]
        self.dlg._table.insertRow(0)
        for c in range(5):
            self.dlg._table.setItem(0, c, QTableWidgetItem(f"Val_{c}"))
        self.dlg._table.selectRow(0)
        self.dlg._on_table_selection_changed()

        with patch('qmagery.gui.main_dialog.BackendRunner') as mock_runner_cls:
            mock_runner = MagicMock()
            mock_runner_cls.return_value = mock_runner

            self.dlg._btn_load.click()

            self.assertFalse(self.dlg._btn_load.isEnabled())
            self.assertTrue(self.dlg._btn_cancel.isEnabled())
            mock_runner.run.assert_called_once()
            args, _ = mock_runner.run.call_args
            self.assertEqual(args[0], 'download')

            # Testa atualização de status para Carregado
            with tempfile.NamedTemporaryFile(suffix='.tif', delete=False) as tf:
                tmp_tif = tf.name
            try:
                with patch('qmagery.gui.main_dialog.add_raster_layer'):
                    self.dlg._on_load_finished({"success": True, "file": tmp_tif}, None, loaded_row=0)
                    self.assertEqual(self.dlg._table.item(0, 4).text(), "✓ Carregado")
            finally:
                if os.path.exists(tmp_tif):
                    os.remove(tmp_tif)

    def test_thumb_button_triggers_runner_and_ui_states(self):
        """Testa se o botão 'Miniatura' invoca o backend para gerar prévia."""
        from unittest.mock import patch, MagicMock
        from qgis.PyQt.QtWidgets import QTableWidgetItem

        self.dlg._table.setRowCount(0)
        self.dlg._images_cache = [{"id": "COPERNICUS/S2/IMG1", "date": "2026-10-01"}]
        self.dlg._table.insertRow(0)
        for c in range(5):
            self.dlg._table.setItem(0, c, QTableWidgetItem(f"Val_{c}"))
        self.dlg._table.selectRow(0)
        self.dlg._on_table_selection_changed()

        with patch('qmagery.gui.main_dialog.BackendRunner') as mock_runner_cls:
            mock_runner = MagicMock()
            mock_runner_cls.return_value = mock_runner

            self.dlg._btn_thumb.click()

            self.assertTrue(self.dlg._btn_cancel.isEnabled())
            mock_runner.run.assert_called_once()
            args, _ = mock_runner.run.call_args
            self.assertEqual(args[0], 'thumb')

    def test_replace_button_invokes_load(self):
        """Testa se o botão '[ Substituir nas Camadas ]' dispara o carregamento."""
        from unittest.mock import patch
        self.dlg._btn_replace.setEnabled(True)
        with patch.object(self.dlg, '_on_load_clicked') as mock_load:
            with patch('qgis.PyQt.QtWidgets.QMessageBox.information'):
                self.dlg._btn_replace.click()
                mock_load.assert_called_once()

    def test_inpe_cbers2_collections_and_composition_modes(self):
        """Testa se as coleções CBERS-2 e CBERS-2B estão disponíveis e suas composições ajustadas."""
        # Muda para fonte INPE
        self.dlg._on_source_toggled('inpe', True)

        # Coleta todas as coleções do combo sensor
        inpe_items = [self.dlg._cbo_sensor.itemData(i) for i in range(self.dlg._cbo_sensor.count())]
        self.assertIn('INPE:CB2-CCD-L2-DN-1', inpe_items, "CBERS-2 CCD deve estar nas opções INPE")
        self.assertIn('INPE:CB2B-CCD-L2-DN-1', inpe_items, "CBERS-2B CCD deve estar nas opções INPE")
        self.assertIn('INPE:CB2B-HRC-L2-DN-1', inpe_items, "CBERS-2B HRC deve estar nas opções INPE")
        self.assertIn('INPE:CB2-WFI-L2-DN-1', inpe_items, "CBERS-2 WFI deve estar nas opções INPE")
        self.assertIn('INPE:CB2B-WFI-L2-DN-1', inpe_items, "CBERS-2B WFI deve estar nas opções INPE")

        # Seleciona CB2-CCD-L2-DN-1 e verifica composições
        idx_ccd = self.dlg._cbo_sensor.findData('INPE:CB2-CCD-L2-DN-1')
        self.dlg._cbo_sensor.setCurrentIndex(idx_ccd)
        modes_ccd = [self.dlg._cbo_comp.itemData(i) for i in range(self.dlg._cbo_comp.count())]
        self.assertEqual(modes_ccd, ['rgb', 'false', 'multi', 'pan'])

        # Seleciona CB2B-HRC-L2-DN-1 e verifica modo pan
        idx_hrc = self.dlg._cbo_sensor.findData('INPE:CB2B-HRC-L2-DN-1')
        self.dlg._cbo_sensor.setCurrentIndex(idx_hrc)
        modes_hrc = [self.dlg._cbo_comp.itemData(i) for i in range(self.dlg._cbo_comp.count())]
        self.assertEqual(modes_hrc, ['pan'])

        # Verifica exibição da nota informativa
        self.assertFalse(self.dlg._lbl_notes.isHidden())
        self.assertIn("Nível 2", self.dlg._lbl_notes.text())


if __name__ == '__main__':
    unittest.main()
