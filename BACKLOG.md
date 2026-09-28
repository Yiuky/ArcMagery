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
- Estado de referência: v2.2.0, branch `feature/arcmagery-2.0`, 2026-09-28.

---

## V. Validação manual pendente (não automatizável fora do ArcMap)

Estes pontos foram implementados e cobertos por testes unitários ou simulados, mas **ainda
não foram exercitados dentro de um ArcMap 10.8 real**. Faça antes de publicar a Release:

| ID | Verificar no ArcMap | Arquivos |
|---|---|---|
| V-01 | Barra **Fonte de imagens**: alternar GEE ↔ CBERS adapta a janela; o botão **Google Earth / Mosaicos XYZ...** abre uma única janela | `gee_gui.on_source_changed`, `on_open_extra_sources` |
| V-11 | Carregar uma imagem multibanda (ex.: CBERS multibanda, S2 B8-B4-B3) e uma de 1 banda (NDVI): Properties › Symbology mostra RGB Composite com as bandas pedidas / Stretched, com o Stretch e a origem das estatísticas das Configurações | `arcmagery_symbology.py`, `gee_bridge.load_into_toc` |
| V-10 | CBERS pela janela principal: buscar, ver a **Miniatura**, carregar 2 cenas (fila) e usar **Substituir no TOC** numa camada CBERS | `gee_gui`, `arcmagery_inpe.py` |
| V-02 | Mosaico Google/Esri entra no TOC no grupo `ArcMagery - Google Earth / XYZ`, em RGB e na posição correta sobre uma camada de referência | `arcmagery_sources_gui.py`, `gee_bridge.load_into_toc` |
| V-03 | CBERS multibanda entra com `rgb_bands=[2,1,0]` (cor natural) e a pancromática entra em tons de cinza | `gee_bridge._rgb_override` |
| V-04 | Dois ArcMaps abertos: cada interface conversa só com o seu ArcMap (arquivos `arcmagery_<PID>_*.json` em `%TEMP%`) | `gee_bridge.IPC_SESSION` |
| V-05 | Clicar duas vezes no botão da barra traz a janela existente para frente, sem abrir uma segunda | `gee_gui.acquire_single_instance` |
| V-06 | Validação de escala/AOI (diálogos de 1:500.000) funciona sem congelar e sem erro de Tcl | `gee_gui.validate_scale_and_get_bbox` |
| V-07 | `install.bat` numa máquina limpa (sem venv): cria `%LOCALAPPDATA%\ArcMagery\venv`, `import ee` e GDAL passam | `install.bat` |
| V-08 | Atualizador sem Release publicada pede confirmação para usar o `main`; com a Release v2.0.0, verifica o SHA-256 | `gee_updater.py`, `gee_gui.GEEUpdaterDialog` |
| V-09 | Download GEE em mosaico (≥2 cenas) com nuvens: a máscara remove nuvens e o ST_B10 não satura | `gee_core.mask_clouds_and_shadows`, `cast_mosaic_to_native_type` |

---

## P0 — Bloqueia uso ou segurança

### N-09 · Data de captura e imagens históricas do Google Earth ("Data das imagens")
- **Status:** BLOQUEADO / AGUARDANDO DECISÃO (2026-09-28)
- **Pedido:** mostrar a data das imagens (como no rodapé do Google Earth Pro e do Google Earth
  Online) e permitir baixar imagens históricas por data.
- **Bloqueio:** não existe API pública do Google para isso. Os dados vêm de um banco interno e
  não documentado do Google Earth (histórico "timemachine"), cujo acesso exige engenharia reversa
  e decifração do protocolo. A tentativa de pesquisar e implementar esse caminho foi **negada
  pela política de segurança do ambiente de desenvolvimento**. Além disso, violaria os Termos de
  Serviço do Google. **Não implemente por esse caminho.**
- **Alternativas legítimas (a decidir com o mantenedor):**
  1. **Esri World Imagery com data de captura:** o serviço público de metadados da World Imagery
     informa, por área, a data da cena, a fonte (Maxar, Airbus...) e a resolução.
  2. **Esri World Imagery Wayback:** versões históricas publicadas pela Esri desde 2014, com datas
     de lançamento. Permite escolher uma versão por data e baixar como XYZ, com o mesmo `xyz_core`.
  3. **CBERS / Sentinel / Landsat:** já datados por cena (INPE e GEE).
  4. Imagens comerciais datadas (Maxar/Airbus) apenas via licença ou API oficial.

### U-01 · Publicar a primeira GitHub Release verificável (v2.2.0)
- **Status:** ABERTO (ação do mantenedor)
- **Problema:** desde a v2.0 o atualizador só instala sem confirmação a partir de uma Release com `SHA256SUMS.txt`. Hoje o repositório **não tem Releases**, então todo usuário verá o aviso "Atualização sem verificação".
- **Como fazer:** `python build_release.py`, depois `gh release create v2.2.0 dist/ArcMagery-2.2.0.zip dist/SHA256SUMS.txt --title "ArcMagery v2.2.0" --notes-file CHANGELOG.md`.
- **Aceite:** `gee_updater.fetch_latest_release()` retorna `version=2.2.0` com `zip_url` e `sums_url`.

### U-02 · O script gerado pelo atualizador encerra TODOS os `pythonw.exe`
- **Status:** ABERTO
- **Onde:** `gee_updater.py`, no template do `.bat` desacoplado (`taskkill /f /im pythonw.exe`, perto da linha 1195).
- **Problema:** mata outras ferramentas Python do usuário (scripts do QGIS, outras interfaces Tk). A espera também é por tempo fixo, sem aguardar o PID da interface.
- **Correção sugerida:** passar o PID da interface ao `.bat` e esperar/encerrar só ele (`tasklist /FI "PID eq N"`), ou filtrar por linha de comando contendo `gee_gui.py`, como já faz o `deploy.ps1`.
- **Aceite:** teste que gera o `.bat` (sem executá-lo) e confirma que não há `/im pythonw.exe`.

---

## P1 — Resultado errado ou travamento

### U-03 · Rollback do atualizador não garante o estado anterior
- **Status:** ABERTO
- **Onde:** `gee_updater.create_snapshot_backup`, template do `.bat` (ROLLBACK).
- **Problemas:**
  - falhas no backup viram apenas aviso;
  - o rollback faz `xcopy` por cima, então arquivos novos da versão com falha permanecem;
  - não há checagem de `errorlevel` no rollback;
  - o smoke test só confere se o arquivo existe.
- **Correção sugerida:** trocar por renomeação (cache → `.old`, staging → cache; no rollback, desfazer), com manifest de hashes do backup e `python -c "import gee_gui"` como smoke test.

### U-04 · `.bat` do atualizador com caminhos acentuados
- **Status:** ABERTO
- **Onde:** `gee_updater.generate_and_launch_detached_runner` (`chcp 65001` + arquivo gravado em ANSI/bytes).
- **Cenário:** usuário `C:\Users\joão.silva`, onde todos os caminhos do `.bat` ficam inválidos.
- **Correção sugerida:** gravar com `io.open(..., encoding='utf-8')` e caminhos unicode, ou substituir o `.bat` por um executor Python desacoplado.

### P-01 · Timeout de IPC menor que `CalculateStatistics`/`BuildPyramids` em rasters grandes
- **Status:** ABERTO
- **Onde:** `gee_bridge.load_into_toc` (roda na thread de interface do ArcMap) e os timeouts de `send_arcmap_command` (120–300 s).
- **Cenário:** um mosaico XYZ de vários GB passa do tempo limite. A interface mostra "falha", a camada aparece depois, e o usuário baixa de novo.
- **Correção sugerida:** o ArcMap grava um "ack/em andamento" ao consumir o comando, e a interface estende o prazo enquanto houver heartbeat. Pirâmides opcionais para mosaicos XYZ.

### G-01 · Janela do atualizador chama `self.top.after` de threads de trabalho
- **Status:** ABERTO
- **Onde:** `gee_gui.GEEUpdaterDialog._do_zip_update` / `_do_github_update`.
- **Cenário:** o usuário fecha a janela durante a atualização. Ocorre `TclError` no meio do fluxo (depois do backup), e o erro não é mostrado.
- **Correção sugerida:** usar `self.parent.post_to_gui(...)` (a fila da janela principal) e checar `winfo_exists()`.

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
| B-06 | `.pyt`: escala do usuário sobrescrita; cena mais recente escolhida sem considerar nuvem; falha de import vira `AttributeError` | `pyt/GEE_Tools.pyt` | Ver revisão v1.10 |
| B-07 | Tiles temporários do GEE não são removidos em caso de falha; `tempfile.mktemp` | `gee_core.download_geotiff` | `try/finally` + `mkstemp` |
| U-05 | O passo 7 do atualizador (sincronizar repositório de desenvolvimento) sobrescreve edições locais no canal ZIP | `gee_updater` (template) | Remover: o atualizador não deve mexer no repositório |
| U-06 | `desinstalar.bat`: `rd /s /q` sem checar erro nem se o ArcMap está aberto | `desinstalar.bat` | Mesmo padrão do `install.bat` v2.0 |
| N-10 | Percent Clip: percentuais por camada não são expostos pelo ArcObjects 10.8 (vale o padrão do ArcMap). Avaliar se `IRasterDefaultsEnv7.MinPercent/MaxPercent` deve ser ajustado pelo plugin (altera um padrão global do usuário) | `arcmagery_symbology.py` | Decisão do mantenedor |
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
| R-04 | Nomes internos legados (`gee_*`, tag `[ArcGEE]`, pastas `ArcGEE`/`CGMA_ArcGEE`) | Manter até haver migração de dados; a tag faz parte do protocolo de progresso |

---

## Concluídos

| ID | Versão | Descrição | Coberto por |
|---|---|---|---|
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
| C-19 | 2.2.0 | Simbologia garantida: bandas RGB + Stretch aplicados, relidos e conferidos; camada localizada pelo caminho exato (e 8.3); aviso quando não garantida; botões Composição/Forçar RGB/Garantir Stretch removidos | `tests/arcmap/test_symbology.py` |
| C-20 | 2.2.0 | "Aplicar stretch" das Configurações redefinia as bandas para 1-2-3; salvar Configurações apagava as demais opções | `test_symbology.py::test_restretch_preserves_band_combination` |
| C-17 | 2.1.0 | CBERS/Amazônia-1 integrado à janela principal (barra *Fonte de imagens*, tabela, fila, TOC) e botão Miniatura | `tests/arcmap/test_inpe_integration.py` |
| C-18 | 1.12 | Duplo clique não enfileira a mesma cena duas vezes (filtro por `queued_ids`/`current_downloading_ids`, reconferido) | — |
| C-14 | 1.12 | Troca de sensor durante a busca (token de geração) e limpeza do campo de bandas ao trocar de sensor | Já estavam na v1.12 (reconferido) |
| C-15 | 1.12 | `eval_code` removido, `gee_config.json` sem o ID de projeto, `.bat` em CRLF | Já estavam na v1.12 |
