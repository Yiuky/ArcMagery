# Backlog do ArcMagery

Backlog vivo para o mantenedor e para **outros modelos de IA / desenvolvedores**. Antes de
pegar um item, leia o [AGENTS.md](AGENTS.md): arquitetura, restrições Python 2.7 × 3 e como
rodar os testes.

**Como usar este arquivo**
- Cada item tem um ID estável. Não reutilize nem renumere IDs.
- Ao iniciar um item, mude o status para `EM ANDAMENTO (<quem>, <data>)`.
- Ao concluir, mova-o para **Concluídos** com a versão, o commit e o teste que o cobre.
- Todo item concluído precisa de teste automatizado em `tests/` ou, se depender do ArcMap
  real, de uma entrada no checklist manual (seção **V**).
- Prioridade: **P0** (bloqueia uso/segurança) · **P1** (resultado errado ou travamento) ·
  **P2** (robustez e experiência) · **P3** (melhoria e refatoração).
- Estado de referência: v2.4.2, 2026-10-01.

---

## V. Validação manual pendente (não automatizável fora do ArcMap)

Estes pontos foram implementados e cobertos por testes unitários ou simulados, mas **ainda
não foram exercitados dentro de um ArcMap 10.8 real**. Faça antes de publicar a Release:

| ID | Verificar no ArcMap | Arquivos |
|---|---|---|
| V-01 | Barra **Fonte de imagens**: alternar GEE ↔ CBERS adapta a janela; o botão **Google Earth / XYZ...** abre uma única janela; na largura padrão (1100 px) todos os botões da barra e do cabeçalho aparecem | `gee_gui.on_source_changed`, `on_open_extra_sources` |
| V-15 | Máquina **sem venv** (ex.: a do colega com `No module named 'ee'`): abrir o ArcMagery, clicar em **Instalar componentes do Earth Engine** na tela de abertura, autenticar e buscar Sentinel-2; rodar o `install.bat` numa máquina limpa com o QGIS | `backend/pylibs.py`, `arcmagery_startup.py`, `install.bat` |
| V-14 | Fonte **SPOT 1-5 (CNES)** no ArcMap real: tela de abertura (tudo ✔ com ArcMap aberto); buscar uma área, Miniatura, carregar 2 cenas (fila) com a chave configurada; a camada cai sobre a Esri World Imagery (alinhada) em falsa cor; *Substituir no TOC*; sem chave, o carregamento oferece o tutorial | `arcmagery_spot.py`, `arcmagery_startup.py`, `backend/spot_core.py` |
| V-13 | Janela principal, fontes **Google Earth histórico** e **Esri Wayback**: com *todos os zooms*, a tabela mostra a coluna Zoom e uma linha por data/versão e zoom; **Miniatura**; carregar 2 linhas (fila) numa área grande (ex.: 47.920 × 29.369 px no z18) sem o aviso "Tempo limite esgotado (120s)"; a imagem cai no lugar certo; Properties › Source mostra `ACQUISITION_DATE`; Configurações › Threads de download de tiles é respeitado | `arcmagery_gehist.py`, `arcmagery_wayback.py`, `gee_gui.py`, `gee_bridge._stats_and_pyramids` |
| V-12 | Janela Google Earth / XYZ com a fonte Esri: **Consultar datas desta área** lista a data atual e o histórico; baixar uma versão antiga; o nome da camada traz a data; os polígonos de datas entram com contorno amarelo sem preenchimento e rótulo | `esri_core.py`, `arcmagery_sources_gui.py`, `gee_bridge.load_date_footprints` |
| V-11 ✅ 2026-09-29 (S2 1182 e CBERS WPM rgb conferidos no ArcMap real) | Carregar uma imagem multibanda (ex.: CBERS multibanda, S2 B8-B4-B3) e uma de 1 banda (NDVI): Properties › Symbology mostra RGB Composite com as bandas pedidas / Stretched, com o Stretch e a origem das estatísticas das Configurações | `arcmagery_symbology.py`, `gee_bridge.load_into_toc` |
| V-10 | CBERS pela janela principal: buscar, ver a **Miniatura**, carregar 2 cenas (fila) e usar **Substituir no TOC** numa camada CBERS | `gee_gui`, `arcmagery_inpe.py` |
| V-02 | Mosaico Google/Esri entra no TOC no grupo `ArcMagery - Google Earth / XYZ`, em RGB e na posição correta sobre uma camada de referência | `arcmagery_sources_gui.py`, `gee_bridge.load_into_toc` |
| V-03 | CBERS multibanda entra com `rgb_bands=[2,1,0]` (cor natural) e a pancromática entra em tons de cinza | `gee_bridge._rgb_override` |
| V-04 | Dois ArcMaps abertos: cada interface conversa só com o seu ArcMap (arquivos `arcmagery_<PID>_*.json` em `%TEMP%`) | `gee_bridge.IPC_SESSION` |
| V-05 | Clicar duas vezes no botão da barra traz a janela existente para frente, sem abrir uma segunda | `gee_gui.acquire_single_instance` |
| V-06 | Validação de escala/AOI (diálogos de 1:500.000) funciona sem congelar e sem erro de Tcl | `gee_gui.validate_scale_and_get_bbox` |
| V-07 | `install.bat` numa máquina limpa (sem venv): acha o QGIS mais novo (`tools\find_python3.bat`), o diagnóstico instala os componentes e o Add-In aparece no ArcMap; com o ArcMap aberto, o instalador para | `install.bat` |
| V-16 | Atualizador num perfil com acento e numa pasta Documentos no OneDrive: atualizar (Método 1) e voltar (Método 3) por dentro do ArcMap; só a interface do ArcMagery é encerrada (outro `pythonw` continua aberto) | `gee_updater.py`, `gee_gui.GEEUpdaterDialog` |
| V-17 | Download SPOT longo (cena SPOT 5 + alinhamento) passa de 2 min sem "Tempo limite"; fechar a janela no meio e reabrir pelo botão do ArcMap | `gee_bridge.backend_timeout`, `gee_gui.on_close` |
| V-08 | Atualizador: com a Release v2.3.2 publicada, a descoberta, o hash SHA-256 e a validação do pacote foram conferidos fora do ArcMap (2026-09-29); falta atualizar por dentro do ArcMap a partir de uma versão anterior | `gee_updater.py`, `gee_gui.GEEUpdaterDialog` |
| V-09 | Download GEE em mosaico (≥2 cenas) com nuvens: a máscara remove nuvens e o ST_B10 não satura | `gee_core.mask_clouds_and_shadows`, `cast_mosaic_to_native_type` |

---

## P0 — Bloqueia uso ou segurança

Nenhum item aberto (o U-02 foi concluído; ver **Concluídos**).

---

## P1 — Resultado errado ou travamento

### U-03 · Rollback do atualizador não garante o estado anterior
- **Status:** ABERTO
- **Onde:** `gee_updater.create_snapshot_backup`, template do `.bat` (ROLLBACK).
- **Problemas restantes** (backup incompleto agora interrompe a atualização e o rollback confere os
  arquivos essenciais):
  - o rollback faz `xcopy` por cima, então arquivos novos da versão com falha permanecem;
  - o smoke test só confere se o arquivo existe.
- **Correção sugerida:** trocar por renomeação (cache → `.old`, staging → cache; no rollback, desfazer), com manifest de hashes do backup e `python -c "import gee_gui"` como smoke test.

### B-01 · Fórmula `CUSTOM_MATH` com intervalo crescente vira lista de bandas
- **Status:** ABERTO (parcialmente tratado na v1.10)
- **Onde:** `gee_core.is_math_expr` / `download_geotiff`.
- **Cenário:** com a composição "Matemática de bandas", `B3-B5` é interpretado como intervalo (`B3,B4,B5`), e não como subtração.
- **Correção sugerida:** com `composition_code == 'CUSTOM_MATH'`, sempre tratar o texto como fórmula.

### B-02 · Intervalos de bandas geram nomes inexistentes
- **Status:** VERIFICAR (achado da v1.10, não reconferido na v2.0)
- **Onde:** `gee_core.parse_bands`.
- **Cenários:**
  - S2: `B8-B11` pula o `B8A` e gera o `B10`, que não existe no `S2_SR_HARMONIZED`.
  - L8: `SR_B1-SR_B10` gera `SR_B8`, `SR_B9` e `SR_B10`.
- **Correção sugerida:** expandir intervalos sobre `MULTIBAND_DEFAULT_BANDS[sensor]` e validar contra `bandNames()`.

### G-02 · Condição de corrida ao encerrar o worker da fila de download
- **Status:** VERIFICAR
- **Onde:** `gee_gui._enqueue_download_task` e o laço do worker (`get_nowait` + `is_alive`).
- **Cenário:** uma tarefa adicionada no instante em que o worker sai fica em "Na Fila" para sempre.
- **Correção sugerida:** worker permanente com `queue.get()` bloqueante, ou lock na decisão de iniciar/encerrar.

---

## P2 — Robustez e experiência

| ID | Item | Onde | Nota |
|---|---|---|---|
| G-04 | Fórmula padrão não-S2 `(SR_B5-SR_B4)/…` só é NDVI no L8 (no L5/L7 é outro índice) | `gee_gui` (padrões por sensor) | Criar tabela NIR/Red por sensor |
| G-05 | Combobox de camadas vetoriais não reflete camadas adicionadas/removidas depois | `gee_gui.sync_arcmap_context` | Sempre atualizar `values` preservando a seleção |
| G-06 | Validação de entradas: pixel 0/negativo, núcleos 0 (`ThreadPoolExecutor(0)`), buffer negativo | `gee_gui` | Limitar valores antes de salvar/enfileirar |
| G-07 | Busca sem bbox cai numa bbox fixa de MT sem avisar | `gee_gui.run_search_thread` | Avisar e abortar |
| G-08 | Caminho multicore: `future.result()` sem try; a limpeza de `current_downloading_ids` fora do `finally` | `gee_gui` | try por cena + `finally` |
| G-09 | `str(e)` sobre unicode em handlers Py2 (UnicodeEncodeError esconde o erro real) | `gee_gui`, `gee_bridge` | Usar um helper `to_text()` (há um em `arcmagery_sources_gui`) |
| P-02 | `contentsChanged`/`activeViewChanged` exportam contexto sem guarda de reentrância durante `load_into_toc` | `gee_selector_addin.py` | Aplicar `_is_processing_cmd` |
| P-03 | `launch_auth_console` usa `shell=True` e procura `earthengine.exe` no lugar errado | `gee_bridge.py:~575` | `Popen([py3, '-c', 'import ee; ee.Authenticate()'], env=clean_env)` |
| P-04 | `.lyr` em `%TEMP%\arcgee_lyr_cache` e TIFFs do GEE em `%TEMP%` nunca são limpos | `gee_bridge`, `gee_gui` | Limpeza por idade ao iniciar |
| B-03 | Miniatura multibanda MSS (L1–L3) falha; a de L5/L7 sai em falsa cor | `gee_core.get_visualization_image` | Mapa RGB por sensor. VERIFICAR |
| B-04 | `apply_sensor_scaling` aplica o fator de refletância a `ST_*`/QA em fórmulas | `gee_core` | Aplicar só a `SR_*`/`B*` |
| B-05 | `has_credentials` exige o arquivo `credentials` e rejeita conta de serviço/ADC | `gee_core` | Tentar `ee.Initialize` antes de negar |
| U-05 | O passo 7 do atualizador (sincronizar repositório de desenvolvimento) sobrescreve edições locais no canal ZIP | `gee_updater` (template) | Remover: o atualizador não deve mexer no repositório |
| N-10 | Percent Clip: percentuais por camada não são expostos pelo ArcObjects 10.8 (vale o padrão do ArcMap). Avaliar se `IRasterDefaultsEnv7.MinPercent/MaxPercent` deve ser ajustado pelo plugin (altera um padrão global do usuário) | `arcmagery_symbology.py` | Decisão do mantenedor |
| X-01 | Cache de tiles XYZ (`<saída>_tiles`) fica órfão quando o download falha: a janela XYZ dá nome com data/hora a cada download, então nunca retoma | `xyz_core.py`, `arcmagery_sources_gui.py` | Cache com chave estável (provedor, zoom, bbox) em `%LOCALAPPDATA%\ArcMagery\cache\xyz`, com expiração |
| G-10 | Landsat 7 aparece como "Presente (Ativo)" no quadro do sensor, mas a missão terminou | `gee_gui` (metadados dos sensores) | Conferir a última data no acervo e mostrar o período fechado |
| N-07 | Rede com inspeção SSL que não confia no bundle do Windows: não há opção de CA na interface | `stac_core.configure_gdal_http` | Campo "CA bundle (.pem)" nas Configurações → `GDAL_CURL_CA_BUNDLE` |

---

## P3 — Novas funcionalidades e refatoração

| ID | Item | Nota |
|---|---|---|
| N-01 | **CBERS: mosaico de várias cenas** num só GeoTIFF e recorte pelo polígono da AOI (cutline), não só pelo bbox | `gdal.Warp(cutlineDSName=...)`, mantendo a resolução nativa |
| N-02 | **CBERS: aplicar o `CMASK`** (máscara de nuvem) nas coleções SR | O asset `CMASK` existe em MUX/WFI SR |
| N-03 | **CBERS-4A WPM: pansharpening 2 m** (PAN + MS) | `gdal_pansharpen` ou Brovey. A coleção `CB4A-WPM-PCA-FUSED-1` já cobre parte do caso |
| N-04 | Desempenho da pancromática WPM: arquivos em faixas (strips), 33 s para 1,6 × 1,7 mil px | Paralelizar bandas, `GDAL_NUM_THREADS`, avaliar leitura por blocos |
| N-05 | Botão **Cancelar** nos downloads XYZ/CBERS (e no GEE) | Hoje só existe o timeout (30 min) |
| N-06 | Campo de **URL XYZ personalizada** na interface (o backend já aceita `{z}/{x}/{y}`, `{s}` e `{q}`) | `xyz_core.get_provider` |
| N-08 | Teste de fumaça da janela principal (`GEEPluginWindow`) com a ponte simulada | `tests/arcmap` |
| R-01 | Centralizar versão e nome (hoje em `config.xml`, `gee_gui.CURRENT_VERSION` e padrões do atualizador; o teste `test_versions_are_consistent` garante que coincidem) | Ler de `config.xml` |
| R-02 | Renomear o repositório GitHub para `arcmagery` (o GitHub redireciona o antigo) e atualizar as URLs em `gee_updater.py`, `gee_gui.py` e `README.md` | Fazer depois da U-01 |
| R-03 | `gee_gui.py` tem 3.200 linhas: dividir `setup_ui` (~365 linhas) e unificar os caminhos multicore/sequencial de download | Refatoração sem mudar comportamento, protegida por testes |
| R-05 | Proveniência da build: `actions/attest-build-provenance` e actions fixadas por SHA no `release.yml` | O `SHA256SUMS.txt` publicado na mesma Release não protege contra conta comprometida |
| R-06 | Renomear `GEE_Image_Selector.esriaddin` para `ArcMagery.esriaddin` (mesmo `AddInID`) e migrar `%LOCALAPPDATA%\CGMA_ArcGEE` para `%LOCALAPPDATA%\ArcMagery`, lendo a pasta antiga | Exige migração no atualizador e no rollback; ver R-04 |
| R-04 | Nomes internos legados (`gee_*`, tag `[ArcGEE]`, pastas `ArcGEE`/`CGMA_ArcGEE`) | Manter até haver migração de dados; a tag faz parte do protocolo de progresso |

---

## Concluídos

| ID | Versão | Descrição | Coberto por |
|---|---|---|---|
| U-02 | 2.4.2 | `.bat` do atualizador encerrava todos os `pythonw.exe`; agora espera/encerra só o PID da interface | `tests/arcmap/test_robustness_fixes.py` (execução real desanexada) |
| U-04 | 2.4.2 | Atualizador e `.bat` com caminhos acentuados (unicode + `.bat` em ANSI/8.3, sem `chcp`) | `test_robustness_fixes.py` |
| G-01 | 2.4.2 | Atualizador usa a fila da GUI (`post_to_gui`) em vez de `top.after` nas threads | `test_robustness_fixes.py` |
| B-06 | 2.4.2 | Caixa de ferramentas `.pyt` quebrada removida | `tests/arcmap/test_compile_and_meta.py` |
| B-07 | 2.4.2 | Tiles temporários e parciais do GEE/SPOT/CBERS removidos em falha; varredura de pastas antigas | `tests/backend/test_hardening.py` |
| C-01 | 2.0.0 | Máscara de nuvem dos mosaicos nunca aplicada (`getInfo` dentro de `map`) | `tests/backend/test_gee_core_mosaic.py` (+ teste ao vivo no EE) |
| C-02 | 2.0.0 | `toInt16` truncava Landsat L2 (SR > 0,70 e ST_B10) | `test_gee_core_mosaic.py` |
| C-03 | 2.0.0 | Worker morria sob `pythonw` (a detecção de stdout da v1.12 era ineficaz) | `tests/arcmap/test_gui_core.py::PythonwStdoutTest` |
| C-04 | 2.0.0 | Atualizador sem verificação de integridade: Release + SHA256SUMS, confirmação para `main`/downgrade | `tests/arcmap/test_updater_security.py` |
| C-05 | 2.0.0 | Tk acessado de threads de trabalho na validação de escala/AOI (`ui_call`) | `test_gui_core.py::UiCallTest` |
| C-06 | 2.0.0 | IPC por sessão (PID do ArcMap), escrita atômica e instância única | `test_bridge.py`, `test_gui_core.py` |
| C-07 | 2.0.0 | Seleção do Python 3 validando `ee`/GDAL, sem o alias da MS Store; `pythonw` via `sys.prefix` | `test_bridge.py::PythonDiscoveryTest` |
| C-08 | 2.0.0 | Miniatura GEE sem timeout; Pillow não declarado | `run_gee.py` (revisão), `requirements.txt` |
| C-09 | 2.0.0 | `install.bat` instalava pacotes no Python do QGIS ou no venv de outro projeto: agora cria um venv próprio | V-07 (manual) |
| C-10 | 2.0.0 | Backend duplicado na raiz removido (fonte única) | `test_compile_and_meta.py::test_single_backend_copy` |
| C-11 | 2.0.0 | Nova fonte Google Earth / XYZ | `tests/backend/test_xyz_core.py` |
| C-12 | 2.0.0 | Nova fonte CBERS / Amazônia-1 (STAC INPE), com cobertura real da AOI | `tests/backend/test_stac_core.py` |
| C-13 | 2.0.0 | `gdal.Unlink` no `finally` mascarava o erro real do recorte CBERS | `test_stac_core.py::test_aoi_outside_raster` |
| C-16 | 2.0.0 | Versão do pacote ZIP lida como "Desconhecida" (namespace do config.xml), o que anulava o bloqueio de downgrade | `test_updater_security.py::RealZipValidationTest` |
| C-34 | 2.3.3 | Revisão de código: concorrência de fontes de tiles e limite de 4 downloads simultâneos; falhas de rede por tile/pacote no Google Earth histórico (2ª rodada, sem abortar); pirâmides/estatísticas antigas descartadas; miniatura com a AOI; amostragem de faixas estreitas; Interromper por janela e sem bloquear; estado da busca por token; funções comuns das fontes de tiles em `arcmagery_tilesource.py` | `tests/backend/test_review_fixes.py`, `tests/arcmap/test_review_fixes.py` |
| C-33 | 2.3.3 | Plugin preso após carga CBERS (backend vivo 5-15 min por conexões `/vsicurl/` abertas: `VSICurlClearCache` antes de sair), interface usa o resultado sem esperar o processo, `taskkill /T` (sem órfãos), botão Interromper, CBERS-2/2B duplicados mesclados. Deslocamento CBERS-2 entre datas (~650 m medidos) é do produto Nível 2 do INPE: aviso na descrição da coleção | `tests/arcmap/test_cancel_and_hang.py` (processos reais), `test_stac_core.py::test_duplicate_cbers2_entries_are_merged` |
| C-32 | 2.3.3 | CBERS fusionada 2 m (asset `tci` multibanda: "sem as bandas rgb" e, depois, só 1 banda) e mosaicos RGB visual; data do Google Earth histórico igual à do Google Earth Pro (catálogo UTC − 1 dia) | `test_stac_core.py::test_single_multiband_asset_keeps_all_bands`, `test_gehist_core.py::test_google_earth_pro_date_convention` |
| C-31 | 2.3.3 | Esri Wayback como quarta fonte da janela principal (versões na tabela com data de captura, satélite e resolução; zoom numa coluna; todos os zooms em paralelo; miniatura; fila). Google Earth histórico varrendo todos os zooms (15-20) numa busca, com a cobertura de cada zoom (estimada por amostragem em áreas grandes e no z20) | `tests/arcmap/test_wayback_integration.py`, `test_gehist_integration.py`, `test_parallel_and_overviews.py::MultiZoomTest` |
| C-30 | 2.3.3 | P-01: carga de rasters grandes estourava o prazo de 120 s (mosaico de 1,4 Gpx). O backend gera as pirâmides (.ovr, GDAL multinúcleo) e o ArcMap as reaproveita (`SKIP_EXISTING`); estatísticas por amostragem (~25 Mpx); prazo proporcional ao tamanho. Medido com arcpy em 167 Mpx: 38,6 s → 2,1 s. Download com janela limitada de tiles em andamento (memória constante) e 48 threads por padrão (Google Earth: 82 s → 20 s em 2.596 tiles) | `test_parallel_and_overviews.py`, `test_wayback_integration.py::BridgePerformanceHelpersTest` |
| C-29 | 2.3.3 | N-09: Google Earth histórico por data como terceira fonte da janela principal (mesmo fluxo do CBERS: zoom como "sensor", datas na tabela, fila, miniatura, TOC), implementado direto em Python (`gehist_core.py`, porta do `C:\DOWNLOADER_EARTH`), sem executável; grade geográfica EPSG:4326; limite de 100 mil tiles (também no XYZ). O bloqueio antes registrado no N-09 não foi determinado pelo mantenedor e foi revogado por ele em 2026-09-29. Uma versão intermediária (não publicada) usava o `downloader_earth.exe` e georreferenciava como Web Mercator: deslocava a imagem (~35 m a 10° S) e abortava em áreas grandes ("Imagem com 30208x21248 px, mas a grade... tem 30208x21760 px") | `tests/backend/test_gehist_core.py` (servidor Keyhole simulado, `test_keyhole_grid_is_not_web_mercator`), `tests/arcmap/test_gehist_integration.py` |
| C-28 | 2.3.3 | Carga no TOC quebrava com `UnicodeEncodeError` (mensagem acentuada via `str(e)`) em máquina sem `comtypes`; `comtypes` embutido; diagnóstico de "nenhum tile" (Clarity) | `test_bridge.py::ErrTextTest`, `test_xyz_core.py::test_no_tiles_reports_server_answer` |
| C-27 | 2.3.3 | CBERS: 20 coleções novas (WFI L4 DN, cubos com NDVI/EVI, Nível 2, CBERS-2/2B, mosaicos), cobertura estimada em footprints retangulares, aviso de cobertura parcial, plano B `bbox` no HTTP 500 dos mosaicos | `test_stac_core.py`, `test_inpe_integration.py::test_catalog_sync_with_backend` |
| C-26 | 2.3.2 | U-01: primeira Release verificável publicada automaticamente pela tag v2.3.2 (zip + SHA256SUMS), reconhecida e validada pelo atualizador do plugin | `.github/workflows/release.yml` |
| C-25 | 2.3.2 | Repositório: CI (testes do backend + consistência de versão), Release automática por tag, modelos de issue/PR, `desinstalar.bat` e `atualizar.bat` seguros, remoção de imagens não usadas, `tools/` | `.github/workflows/*.yml` |
| C-24 | 2.3.1 | DOWNLOADER_EARTH: nomes de satélites, tags TIFF padrão e EPSG:4326 integrados; a data Esri em tiles Google foi rejeitada (vira só referência); data em z18+ corrigida | `test_esri_core.py`, `test_sources_gui.py` |
| C-22 | 2.3.0 | Data de captura + histórico Wayback + polígonos de datas (Esri) | `tests/backend/test_esri_core.py`, `test_symbology.py::test_date_footprints_layer`, `test_sources_gui.py` |
| C-23 | 2.3.0 | GDAL falhava com `OSGEO4W_ROOT` herdada (sitecustomize do QGIS) | `test_run_gee_cli.py::test_gdal_loads_even_with_inherited_osgeo4w_root` |
| C-21 | 2.2.1 | Camada viva: QueryInterface(IMxDocument) para FocusMap/SelectedLayer (erro "FocusMap" no ArcMap real) | `test_symbology.py::test_live_arcmap_path_uses_imxdocument` |
| C-19 | 2.2.0 | Simbologia garantida: bandas RGB + Stretch aplicados, relidos e conferidos; camada localizada pelo caminho exato (e 8.3); aviso quando não garantida; botões Composição/Forçar RGB/Garantir Stretch removidos | `tests/arcmap/test_symbology.py` |
| C-20 | 2.2.0 | "Aplicar stretch" das Configurações redefinia as bandas para 1-2-3; salvar Configurações apagava as demais opções | `test_symbology.py::test_restretch_preserves_band_combination` |
| C-17 | 2.1.0 | CBERS/Amazônia-1 integrado à janela principal (barra *Fonte de imagens*, tabela, fila, TOC) e botão Miniatura | `tests/arcmap/test_inpe_integration.py` |
| C-18 | 1.12 | Duplo clique não enfileira a mesma cena duas vezes (filtro por `queued_ids`/`current_downloading_ids`, reconferido) | — |
| C-14 | 1.12 | Troca de sensor durante a busca (token de geração) e limpeza do campo de bandas ao trocar de sensor | Já estavam na v1.12 (reconferido) |
| C-15 | 1.12 | `eval_code` removido, `gee_config.json` sem o ID de projeto, `.bat` em CRLF | Já estavam na v1.12 |
