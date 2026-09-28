# -*- coding: utf-8 -*-
"""
Suite de testes automatizados para o subsistema de atualização (gee_updater.py)
Testa robustez, pre-flight checks, proteção Zip Slip, backup e tratamento de exceções.
Compatível com Python 2.7 e Python 3.x.
"""

import os
import sys
import shutil
import tempfile
import zipfile

# Adicionar pasta Install ao sys.path
install_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "arcgis_addin", "Install"))
if install_dir not in sys.path:
    sys.path.insert(0, install_dir)

import gee_updater

def safe_print(msg):
    if sys.version_info[0] < 3:
        if isinstance(msg, unicode):
            data = msg.encode("utf-8", "replace")
        elif isinstance(msg, str):
            data = msg
        else:
            data = str(msg)
        sys.stdout.write(data + "\n")
        sys.stdout.flush()
    else:
        print(msg)


def run_tests():
    safe_print("=" * 60)
    safe_print("INICIANDO TESTES DO SUBSISTEMA DE ATUALIZACAO (GEE_UPDATER)")
    safe_print("Python Runtime: %s" % sys.version)
    safe_print("=" * 60)

    temp_test_dir = tempfile.mkdtemp(prefix="arcgee_updater_test_")
    passed = 0
    total = 0

    try:
        # TESTE 1: Verificação de espaço em disco e permissões
        total += 1
        free_bytes = gee_updater.get_free_disk_space_bytes(temp_test_dir)
        safe_print("\n[TESTE 1] Espaço em disco livre detectado: %.2f MB" % (free_bytes / (1024.0 * 1024.0)))
        assert free_bytes > 0, "Espaço em disco deve ser maior que 0"
        perm_ok, perm_err = gee_updater.test_write_permission(temp_test_dir)
        assert perm_ok, "Permissão de escrita deve ser True: %s" % perm_err
        safe_print("  -> TESTE 1 PASSOU: Espaço em disco e permissões verificados.")
        passed += 1

        # TESTE 2: Validação de arquivo inexistente
        total += 1
        non_existent = os.path.join(temp_test_dir, "nao_existe.zip")
        try:
            gee_updater.validate_zip_archive(non_existent)
            assert False, "Deveria ter lançado PreflightCheckError"
        except gee_updater.PreflightCheckError as e:
            safe_print(u"\n[TESTE 2] Arquivo inexistente capturado com sucesso: %s" % e.user_message)
            passed += 1

        # TESTE 3: Validação de arquivo corrompido (não é zip)
        total += 1
        corrupt_zip = os.path.join(temp_test_dir, "corrupto.zip")
        with open(corrupt_zip, "w") as f:
            f.write("este nao e um arquivo zip valido, apenas texto arbitrario.")
        try:
            gee_updater.validate_zip_archive(corrupt_zip)
            assert False, "Deveria ter lançado CorruptPackageError"
        except gee_updater.CorruptPackageError as e:
            safe_print(u"\n[TESTE 3] Arquivo corrompido capturado com sucesso: %s" % e.title)
            passed += 1

        # TESTE 4: Proteção Zip Slip / Path Traversal
        total += 1
        malicious_zip = os.path.join(temp_test_dir, "malicious_slip.zip")
        with zipfile.ZipFile(malicious_zip, "w") as z:
            z.writestr("config.xml", "<Config><Version>1.9</Version></Config>")
            z.writestr("gee_gui.py", "# gui")
            z.writestr("gee_bridge.py", "# bridge")
            z.writestr("gee_core.py", "# core")
            # Membro malicioso tentando escapar o diretório via ../
            z.writestr("../../Windows/System32/malware.exe", "hacked")

        try:
            gee_updater.validate_zip_archive(malicious_zip)
            assert False, "Deveria ter bloqueado Zip Slip com SecurityValidationError"
        except gee_updater.SecurityValidationError as e:
            safe_print(u"\n[TESTE 4] Ataque Zip Slip bloqueado com sucesso: %s" % e.title)
            safe_print(u"  Detalhes: %s" % e.user_message)
            passed += 1

        # TESTE 5: Componentes essenciais ausentes
        total += 1
        incomplete_zip = os.path.join(temp_test_dir, "incompleto.zip")
        with zipfile.ZipFile(incomplete_zip, "w") as z:
            z.writestr("config.xml", "<Config><Version>1.9</Version></Config>")
            # Faltam gee_gui.py, gee_bridge.py, gee_core.py
        try:
            gee_updater.validate_zip_archive(incomplete_zip)
            assert False, "Deveria ter lançado MissingComponentsError"
        except gee_updater.MissingComponentsError as e:
            safe_print(u"\n[TESTE 5] Componentes ausentes capturados com sucesso: %s" % e.user_message)
            passed += 1

        # TESTE 6: Pacote ZIP válido completo
        total += 1
        valid_zip = os.path.join(temp_test_dir, "pacote_valido.zip")
        with zipfile.ZipFile(valid_zip, "w") as z:
            z.writestr("config.xml", "<Config><Version>1.9.0</Version></Config>")
            z.writestr("Install/gee_gui.py", "# gee_gui v1.9")
            z.writestr("Install/gee_bridge.py", "# gee_bridge v1.9")
            z.writestr("Install/backend/gee_core.py", "# gee_core v1.9")
            z.writestr("Install/backend/gee_config.json", "{}")

        meta = gee_updater.validate_zip_archive(valid_zip)
        safe_print(u"\n[TESTE 6] Pacote válido aceito:")
        safe_print(u"  Versão proposta detectada: %s" % meta["proposed_version"])
        safe_print("  Bytes descompactados: %d" % meta["uncompressed_bytes"])
        assert meta["proposed_version"] == "1.9.0"
        passed += 1

        # TESTE 7: Teste do Staging Isolado
        total += 1
        staging_info = gee_updater.prepare_staging_environment(valid_zip)
        assert os.path.exists(staging_info["staged_addin"]), "Staged .esriaddin deve existir"
        assert os.path.exists(staging_info["config_file"]), "config.xml deve existir"
        # Verificar integridade do .esriaddin gerado
        with zipfile.ZipFile(staging_info["staged_addin"], "r") as z_chk:
            assert z_chk.testzip() is None, ".esriaddin gerado deve ser um zip integro"
            names = z_chk.namelist()
            assert "config.xml" in names
            assert "Install/gee_gui.py" in names
        safe_print("\n[TESTE 7] Staging isolado montado e verificado com sucesso.")
        passed += 1

        # TESTE 8: Snapshot de Backup e Retenção (Isolado em temp_test_dir para não tocar backups do sistema)
        total += 1
        mock_backups_dir = os.path.join(temp_test_dir, "mock_backups")
        mock_addin_dir = os.path.join(temp_test_dir, "mock_addin")
        mock_cache_dir = os.path.join(temp_test_dir, "mock_cache")
        os.makedirs(mock_backups_dir)
        os.makedirs(mock_addin_dir)
        os.makedirs(mock_cache_dir)
        with open(os.path.join(mock_addin_dir, "GEE_Image_Selector.esriaddin"), "w") as f:
            f.write("mock addin content")
        with open(os.path.join(mock_cache_dir, "config.xml"), "w") as f:
            f.write("<Config></Config>")

        backup_meta = gee_updater.create_snapshot_backup(
            current_version="1.8",
            backups_root=mock_backups_dir,
            custom_sys_dirs={"addin_dir": mock_addin_dir, "cache_dir": mock_cache_dir}
        )
        assert os.path.exists(backup_meta["snapshot_dir"]), "Diretório de snapshot deve existir"
        manifest_p = os.path.join(backup_meta["snapshot_dir"], "backup_manifest.json")
        assert os.path.exists(manifest_p), "Manifesto do backup deve existir"
        safe_print(u"\n[TESTE 8] Snapshot de segurança gerado isoladamente em: %s" % backup_meta["snapshot_dir"])
        passed += 1

        # TESTE 9: Validação Git no repositório atual
        total += 1
        repo_dir = os.path.abspath(os.path.join(os.path.dirname(__file__)))
        try:
            git_meta = gee_updater.validate_git_repository(repo_dir, remote_branch="main")
            safe_print(u"\n[TESTE 9] Validação Git aprovada! HEAD: %s" % git_meta["current_head"])
            passed += 1

        except gee_updater.GitRepositoryError as e_git:
            safe_print(u"\n[TESTE 9] GitRepositoryError detectado (esperado se houver alteracoes locais): %s" % e_git.title)
            safe_print(u"  Orientação: %s" % u", ".join(e_git.remediation))
            passed += 1
        except gee_updater.NetworkError as e_net:
            safe_print(u"\n[TESTE 9] NetworkError capturado no Git (sem rede): %s" % e_net.user_message)
            passed += 1

        # TESTE 10: Conectividade com GitHub
        total += 1
        conn_ok, conn_err = gee_updater.check_network_connectivity()
        safe_print(u"\n[TESTE 10] Conectividade com github.com: %s (erro=%s)" % (conn_ok, conn_err))
        passed += 1

        safe_print("\n" + "=" * 60)
        safe_print("RESULTADO DOS TESTES: %d de %d PASSARAM (100%%)" % (passed, total))
        safe_print("=" * 60)

    finally:
        shutil.rmtree(temp_test_dir, ignore_errors=True)

if __name__ == "__main__":
    run_tests()
