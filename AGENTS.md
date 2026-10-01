# AGENTS.md: guia para modelos de IA e desenvolvedores

Leia antes de alterar o ArcMagery. O trabalho pendente está no [BACKLOG.md](BACKLOG.md).

## 1. O que é

Add-In Python do **ArcMap 10.8.x** para baixar imagens de satélite do **Google Earth Engine**, do
**CBERS/Amazônia-1 (STAC do INPE)**, do **SPOT 1-5 (CNES/GEODES)**, do **Google Earth histórico**, do
**Esri Wayback** e de **mosaicos XYZ (Google Earth, Esri, Bing)** e carregá-las no TOC. Nome do produto:
**ArcMagery**, projeto pessoal e independente (não cite instituições como autoras ou donas). Os nomes
internos `gee_*`, `ArcGEE`, `GEE_Image_Selector.esriaddin` e a pasta `%LOCALAPPDATA%\CGMA_ArcGEE` são
legados e **devem ser mantidos** (ver R-04): mudá-los quebra a atualização e o rollback das instalações
existentes.

## 2. Arquitetura: três processos, dois Pythons

```
ArcMap.exe (Python 2.7 32-bit, arcpy)          <- gee_selector_addin.py + gee_bridge.py
   | arquivos JSON por sessao em %TEMP%: arcmagery_<PID-do-ArcMap>_{cmd,reply,context}.json
   v
pythonw.exe do ArcGIS (Python 2.7, Tkinter)    <- gee_gui.py (+ arcmagery_inpe.py, arcmagery_gehist.py) + arcmagery_sources_gui.py
   | subprocess: backend/run_gee.py <comando> --params-file=<json UTF-8>
   v
Python 3 do QGIS + %LOCALAPPDATA%\ArcMagery\pylibs\py3XY  <- backend/gee_core.py | stac_core.py | spot_core.py | xyz_core.py | ...
```

- **Nunca** rode `mainloop()` nem chamadas demoradas dentro do ArcMap. O ArcMap só processa
  comandos IPC num timer Win32 (`gee_bridge.start_arcmap_ipc_timer`).
- A interface (processo `pythonw`) só toca widgets Tk **na thread principal**. Threads de
  trabalho usam `post_to_gui(fn)` (assíncrono) ou `ui_call(fn)` (espera o resultado).
- Contrato do backend: **exatamente uma linha JSON no stdout** (a última linha que começa com
  `{`). O progresso vai para o stderr com o prefixo `[ArcGEE]` (ex.: `[ArcGEE] PROGRESS 12/40`),
  que a ponte repassa à interface. O prefixo `[ArcGEE]` é protocolo: não renomeie.
- Os comandos das fontes novas (`sources_info`, `xyz_estimate`, `xyz_download`, `stac_search`,
  `stac_thumb`, `stac_download`, `esri_*`, `gehist_dates`, `gehist_download`) não importam o `earthengine-api` (import tardio em `run_gee.py`)
  e encerram com `os._exit`, porque o GDAL/curl pode travar o encerramento do interpretador.

## 3. Onde fica cada coisa

| Caminho | Python | Papel |
|---|---|---|
| `arcgis_addin/config.xml` | — | Metadados do Add-In. **Não altere o `AddInID`** (quebra a atualização das instalações existentes) |
| `arcgis_addin/Install/gee_selector_addin.py` | 2.7 | Botão/extensão do ArcMap |
| `arcgis_addin/Install/gee_bridge.py` | 2.7 (também importável em 3) | IPC, arcpy/TOC, simbologia, chamada ao backend, seleção do Python 3 |
| `arcgis_addin/Install/gee_gui.py` | 2.7 | Janela principal (GEE), configurações, atualizador. (fim de linha LF, como os demais) |
| `arcgis_addin/Install/arcmagery_sources_gui.py` | 2.7 | Janela Google Earth / XYZ (botão *Google Earth / XYZ...*) |
| `arcgis_addin/Install/arcmagery_gehist.py` | 2.7 | Google Earth histórico na janela principal: zooms como "sensores" `GEH:<zoom>`, cada data como uma linha da tabela; busca/download/miniatura via backend; limite de tiles igual ao do `gehist_core` |
| `arcgis_addin/Install/arcmagery_wayback.py` | 2.7 | Esri Wayback na janela principal: zooms como "sensores" `EWB:<zoom>` / `EWB:ALL`, cada versão como uma linha; usa `esri_versions`, `xyz_download` e `wayback_thumb`. Mesma interface do `arcmagery_gehist` (a janela usa `gee_gui.tile_source_of`) |
| `arcgis_addin/Install/arcmagery_tilesource.py` | 2.7 | Funções comuns das fontes de tiles com data (`arcmagery_gehist`, `arcmagery_wayback`): área/AOI, progresso, período, estimativa e limite |
| `arcgis_addin/Install/arcmagery_spot.py` | 2.7 | SPOT 1-5 (CNES/GEODES) na janela principal: grupos como "sensores" `SPOT:<grupo>`, cenas, chave do GEODES (`%APPDATA%\ArcGEE\geodes_config.json`), tutorial; usa `spot_search`, `spot_download`, `spot_thumb`, `spot_check_key` |
| `arcgis_addin/Install/arcmagery_startup.py` | 2.7 | Tela de abertura (verificações em paralelo, regras puras testáveis), `GeodesKeyFrame`/`GeodesKeyDialog` e o tutorial da chave. `ARCMAGERY_NO_SPLASH=1` desliga a splash (os testes em `tests/arcmap` fazem isso) |
| `arcgis_addin/Install/arcmagery_inpe.py` | 2.7 | CBERS/Amazônia-1 na janela principal: coleções como "sensores" `INPE:<coleção>`, produtos, busca/recorte/miniatura via backend |
| `arcgis_addin/Install/arcmagery_symbology.py` | 2.7 | Simbologia garantida (ArcObjects/comtypes): monta, grava, relê e confere bandas RGB + Stretch; localiza camadas pelo caminho exato |
| `arcgis_addin/Install/gee_updater.py` | 2.7/3 | Atualização (Release + SHA256SUMS, backup, staging, rollback) |
| `arcgis_addin/Install/backend/` | 3 | **Fonte única** do backend (não existe mais `backend/` na raiz) |
| `backend/tilemath.py` | **2.7 e 3** | Matemática XYZ usada pelo backend e pela interface. Sem dependências |
| `backend/xyz_core.py` | 3 | Mosaicos XYZ (urllib + GDAL ou Pillow) |
| `backend/stac_core.py` | 3 + GDAL | STAC do INPE e recorte `/vsicurl/` na grade nativa |
| `backend/esri_core.py` | 3 | Data de captura (metadados públicos da World Imagery) e histórico Wayback (`tilemap`: `select` aponta para a versão MAIS ANTIGA de onde vem o tile) |
| `backend/pylibs.py` | 3 | earthengine-api **sem pip**: baixa as rodas fixadas em `pylibs_manifest.json` (urllib + certificados do Windows, SHA-256) para `%LOCALAPPDATA%\ArcMagery\pylibs\py3XY`; `activate()` (chamado no início do `run_gee.py`) só entra se o Python não tiver `ee` próprio. Regenere o manifesto com `tools/build_pylibs_manifest.py` |
| `backend/doctor.py` | 3 | Diagnóstico do ambiente com correção automática (comando `doctor`; `run_gee.py doctor --text` no `install.bat`, botão da splash). Cada checagem: `ok`/`warn`/`fail`/`fixed` + "o que fazer". Manifestos por Python: `pylibs_manifest.json` (3.10–3.14), `_py39`, `_py38` |
| `backend/ee_auth.py` | 3 | Autenticação interativa do GEE (console) com qualquer Python 3 apto, via `pylibs` |
| `backend/spot_core.py` | 3 + GDAL + numpy | SPOT 1-5 via STAC do GEODES: busca (filtrar coleções por `query.dataset`; a data de aquisição é `start_datetime`), download com `X-API-Key` + MD5 + cache, georreferência pelo `Simplified_Location_Model` do L1A e **alinhamento à Esri** por correlação de fase |
| `backend/gehist_core.py` | 3 | Google Earth histórico por data (catálogo *Time Machine*, protocolo Keyhole: dbRoot + quadtree protobuf + XOR), porta de um projeto pessoal anterior (DOWNLOADER_EARTH). **A grade é geográfica EPSG:4326, não Web Mercator** (`tilemath.keyhole_*`) |
| `backend/parallel.py` | 3 | `imap_bounded` (no máximo `workers × 4` tiles em andamento: memória constante), threads de rede padrão (48, teto 64) e núcleos do GDAL (CPU − 2, teto 16). Todo download de tiles passa por aqui |
| `backend/qgis_env.py` | 3 | Registra `<QGIS>\\bin` como diretório de DLLs antes do import do GDAL (o `sitecustomize` do QGIS pula isso se `OSGEO4W_ROOT` já existir) |
| `tests/backend/`, `tests/arcmap/` | 3 / 2.7 | Suítes automatizadas |

## 4. Regras de código

- **Python 2.7** (tudo em `Install/*.py`, exceto `backend/`): sem f-strings, `print()` só com
  `from __future__`, sem `nonlocal` e sem `exist_ok`. Use literais `u"..."` para texto com
  acento. Nada de `str(e)` sobre unicode: use um `to_text()`.
- **`pythonw` no Python 2.7:** `sys.stdout` existe, mas `fileno() == -2`, e um `print` grande
  lança `IOError(9)`. Os módulos redirecionam com `_stream_is_usable`. Não remova isso.
- **Caminhos com acento** (ex.: `C:\Users\João`): parâmetros vão ao backend num JSON UTF-8
  (`--params-file`), nunca como argumentos unicode no `Popen` do Python 2.
- **Dependências Python 3:** não adicione pacotes que exijam `pip` na máquina do usuário. O backend deve
  rodar no Python do QGIS (GDAL, numpy, Pillow) + `pylibs`. Pacote novo = entrada nova no manifesto
  (roda pura ou abi3/cp310–cp314 win_amd64). `No module named 'ee'` vira `EarthEngineMissing` (JSON
  com `ee_missing`), nunca traceback.
- **Rede corporativa com inspeção SSL:** use `urllib` com `ssl.create_default_context()`, que
  lê o repositório do Windows. O `requests`/`certifi` falha nessa rede. Para o curl do GDAL,
  `stac_core.windows_ca_bundle()` exporta os certificados do Windows para
  `GDAL_CURL_CA_BUNDLE`.
- **Earth Engine:** nada de `getInfo()` dentro de `ImageCollection.map()`, e o tipo nativo é
  preservado (Landsat L2/S2 = uint16). Veja C-01 e C-02 no backlog.
- **CBERS:** recorte por `srcWin` em pixels inteiros (grade nativa, sem reamostragem). Rejeite
  recortes 100% NoData. O footprint real vem de `coverage_pct`, porque o servidor do INPE trata
  `intersects` como bbox.
- **Simbologia:** nunca aplique renderer "no escuro". Use `arcmagery_symbology` (construct → save → reler →
  `compare`) e localize camadas por `IRasterLayer.FilePath` (via `normalize_path`, que expande 8.3),
  nunca por nome. O ArcObjects pode ser testado fora do ArcMap (ver `tests/arcmap/test_symbology.py`).
- **Logs e arquivos de IPC:** o ArcMap define um `%TEMP%` próprio por sessão (`%LOCALAPPDATA%\Temp\arcXXXX\`),
  herdado pela GUI. O `arcgee_debug.log` do ArcMap e os `arcmagery_<PID>_*.json` ficam nessa subpasta, e não
  em `%TEMP%` direto. Cada carga registra ali `_ensure_live_symbology(...)` com a simbologia conferida.
- Mensagens para o usuário em **português**. Ao editar arquivos CRLF, preserve o fim de linha.
- Termos de Uso: Google/Bing exigem o aviso (`TOS_TEXT`) antes do primeiro download.
- **SPOT (L1A):** termos do modelo direto = `[1, linha, coluna, linha*coluna, linha², coluna²]` (índices
  DIMAP, origem 1); o `IMAGERY.TIF` grava XS3, XS2, XS1, SWIR (inverso do XML). Não remova o
  alinhamento: sem ele o erro é de 150–480 m. Nunca gaste a cota do usuário em testes: o GEODES tem
  `/processing/download/get` para validar a chave.
- **Fonte ativa na janela principal:** `var_source` (`gee` | `inpe` | `gehist` | `wayback` | `spot`). Os códigos de sensor
  do INPE começam com `INPE:`, os do Google Earth histórico com `GEH:` e os do Esri Wayback com `EWB:`
  (`...:ALL` = todos os zooms; o zoom de cada linha vem do identificador `..._z<zoom>`). Decida sempre por `inpe.is_inpe(sensor)` /
  `gehist.is_gehist(sensor)`, nunca por listas fixas de sensores GEE. O download passa por
  `GEEPluginWindow._download_any`.

## 5. Ambiente e testes

```bat
install.bat                     :: acha o Python do QGIS (tools\find_python3.bat), roda o diagnostico e instala o Add-In
run_tests.bat                   :: suite backend (Python 3) + suite ArcMap/GUI (Python 2.7)
set ARCMAGERY_LIVE=1            :: + testes com internet (INPE, Esri, Google, GEODES)
set ARCMAGERY_GEE_PROJECT=<id>  :: + teste real no Earth Engine (requer autenticar_gee.bat)
```

- Os testes do backend usam servidores HTTP locais (`tests/backend/_servers.py`): provedor XYZ,
  servidor com HTTP Range (para o `/vsicurl/`) e um STAC simulado. Nada toca a internet sem
  `ARCMAGERY_LIVE=1`.
- Os testes do atualizador simulam tudo: **nunca** tocam o AssemblyCache nem backups reais.
- `tests/arcmap/legacy_gee_updater_check.py` é um diagnóstico manual antigo (faz `git fetch` real)
  e fica fora da suíte.
- Integração com o ArcMap real (TOC, simbologia) não é automatizável: use o checklist **V** do
  backlog.

## 6. Publicar uma versão

1. Atualize `<Version>` em `arcgis_addin/config.xml`, `CURRENT_VERSION` em `gee_gui.py` e os
   padrões `current_version=` em `gee_updater.py`. O teste `test_versions_are_consistent` falha
   se divergirem.
2. Escreva a entrada no `CHANGELOG.md` e rode `run_tests.bat` (idealmente com `ARCMAGERY_LIVE=1`).
3. `git tag v<versão>` e `git push origin v<versão>`. O workflow `.github/workflows/release.yml` confere se a
   tag bate com o `config.xml`, roda o `build_release.py` e publica a Release com o `.zip`, o
   `SHA256SUMS.txt` e as notas da versão no CHANGELOG. Sem a Release, o atualizador dos usuários pede
   confirmação para instalar do `main` sem verificação.
4. Localmente, `python build_release.py` gera os mesmos artefatos em `dist/`, para conferência.
5. **Versão experimental (nightly):** use `X.Y.Z-nightly.AAAAMMDD`, em que **X.Y.Z é a PRÓXIMA versão**
   (depois da 2.4.1: `2.4.2-nightly.AAAAMMDD`; `2.4.1-nightly.*` ordena antes de `2.4.1` e nunca seria
   oferecida a quem já está nela), nos mesmos lugares do passo 1, com o selo do README em laranja (`E67E22`; o shields.io escreve `-` como `--`) e o
   título do CHANGELOG `## [X.Y.Z-nightly.AAAAMMDD] - data (experimental)`. A tag com sufixo vira *pre-release*
   no workflow: o canal estável (`releases/latest`) nunca a instala; o canal experimental (lista de Releases)
   pega a mais nova entre estáveis e nightlies. Compare versões sempre com `gee_updater.version_key`, nunca
   com `parse_version` (que descarta o sufixo).

## 7. Integração contínua

- `.github/workflows/tests.yml` roda a suíte do backend (Python 3.12, Windows) e confere a consistência
  de versão a cada push ou PR. Testes que exigem GDAL/QGIS, internet ou ArcGIS são pulados ali.
- Um teste novo que dependa de GDAL deve usar `@unittest.skipUnless(_paths.HAS_GDAL, ...)`; um que
  dependa de internet, `_paths.LIVE`.
- O workflow `release.yml` roda a suíte do backend no commit da tag antes de publicar. O `build_release.py`
  é reprodutível (data das entradas do ZIP = data do último commit): o mesmo commit gera o mesmo SHA-256.
- Ferramentas de desenvolvimento ficam em `tools/` (`build_icons.py`, `build_logo.py`,
  `build_pylibs_manifest.py`) e não entram no Add-In. `tools/find_python3.bat` é usado pelos `.bat` da raiz
  e segue a mesma regra de `gee_bridge.python3_candidates` (QGIS mais novo primeiro).
