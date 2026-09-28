# AGENTS.md: guia para modelos de IA e desenvolvedores

Leia antes de alterar o ArcMagery. O trabalho pendente está no [BACKLOG.md](BACKLOG.md).

## 1. O que é

Add-In Python do **ArcMap 10.8/10.8.2** para baixar imagens de satélite do **Google Earth
Engine**, de **mosaicos XYZ (Google Earth, Esri, Bing)** e do **CBERS/Amazônia-1 (STAC do INPE)**
e carregá-las no TOC. Nome do produto: **ArcMagery**. Os nomes internos `gee_*` são legados e
**devem ser mantidos** (ver R-04).

## 2. Arquitetura: três processos, dois Pythons

```
ArcMap.exe (Python 2.7 32-bit, arcpy)          <- gee_selector_addin.py + gee_bridge.py
   | arquivos JSON por sessao em %TEMP%: arcmagery_<PID-do-ArcMap>_{cmd,reply,context}.json
   v
pythonw.exe do ArcGIS (Python 2.7, Tkinter)    <- gee_gui.py (+ arcmagery_inpe.py) + arcmagery_sources_gui.py
   | subprocess: backend/run_gee.py <comando> --params-file=<json UTF-8>
   v
Python 3 (venv %LOCALAPPDATA%\ArcMagery\venv)  <- backend/gee_core.py | xyz_core.py | stac_core.py
```

- **Nunca** rode `mainloop()` nem chamadas demoradas dentro do ArcMap. O ArcMap só processa
  comandos IPC num timer Win32 (`gee_bridge.start_arcmap_ipc_timer`).
- A interface (processo `pythonw`) só toca widgets Tk **na thread principal**. Threads de
  trabalho usam `post_to_gui(fn)` (assíncrono) ou `ui_call(fn)` (espera o resultado).
- Contrato do backend: **exatamente uma linha JSON no stdout** (a última linha que começa com
  `{`). O progresso vai para o stderr com o prefixo `[ArcGEE]` (ex.: `[ArcGEE] PROGRESS 12/40`),
  que a ponte repassa à interface. O prefixo `[ArcGEE]` é protocolo: não renomeie.
- Os comandos das fontes novas (`sources_info`, `xyz_estimate`, `xyz_download`, `stac_search`,
  `stac_thumb`, `stac_download`) não importam o `earthengine-api` (import tardio em `run_gee.py`)
  e encerram com `os._exit`, porque o GDAL/curl pode travar o encerramento do interpretador.

## 3. Onde fica cada coisa

| Caminho | Python | Papel |
|---|---|---|
| `arcgis_addin/config.xml` | — | Metadados do Add-In. **Não altere o `AddInID`** (quebra a atualização das instalações existentes) |
| `arcgis_addin/Install/gee_selector_addin.py` | 2.7 | Botão/extensão do ArcMap |
| `arcgis_addin/Install/gee_bridge.py` | 2.7 (também importável em 3) | IPC, arcpy/TOC, simbologia, chamada ao backend, seleção do Python 3 |
| `arcgis_addin/Install/gee_gui.py` | 2.7 | Janela principal (GEE), configurações, atualizador. **Arquivo com CRLF** |
| `arcgis_addin/Install/arcmagery_sources_gui.py` | 2.7 | Janela Google Earth / Mosaicos XYZ |
| `arcgis_addin/Install/arcmagery_inpe.py` | 2.7 | CBERS/Amazônia-1 na janela principal: coleções como "sensores" `INPE:<coleção>`, produtos, busca/recorte/miniatura via backend |
| `arcgis_addin/Install/gee_updater.py` | 2.7/3 | Atualização (Release + SHA256SUMS, backup, staging, rollback) |
| `arcgis_addin/Install/backend/` | 3 | **Fonte única** do backend (não existe mais `backend/` na raiz) |
| `backend/tilemath.py` | **2.7 e 3** | Matemática XYZ usada pelo backend e pela interface. Sem dependências |
| `backend/xyz_core.py` | 3 | Mosaicos XYZ (urllib + GDAL ou Pillow) |
| `backend/stac_core.py` | 3 + GDAL | STAC do INPE e recorte `/vsicurl/` na grade nativa |
| `pyt/GEE_Tools.pyt` | 2.7 | Caixa de ferramentas do ArcToolbox |
| `tests/backend/`, `tests/arcmap/` | 3 / 2.7 | Suítes automatizadas |

## 4. Regras de código

- **Python 2.7** (tudo em `Install/*.py`, exceto `backend/`): sem f-strings, `print()` só com
  `from __future__`, sem `nonlocal` e sem `exist_ok`. Use literais `u"..."` para texto com
  acento. Nada de `str(e)` sobre unicode: use um `to_text()`.
- **`pythonw` no Python 2.7:** `sys.stdout` existe, mas `fileno() == -2`, e um `print` grande
  lança `IOError(9)`. Os módulos redirecionam com `_stream_is_usable`. Não remova isso.
- **Caminhos com acento** (ex.: `C:\Users\João`): parâmetros vão ao backend num JSON UTF-8
  (`--params-file`), nunca como argumentos unicode no `Popen` do Python 2.
- **Rede corporativa com inspeção SSL:** use `urllib` com `ssl.create_default_context()`, que
  lê o repositório do Windows. O `requests`/`certifi` falha nessa rede. Para o curl do GDAL,
  `stac_core.windows_ca_bundle()` exporta os certificados do Windows para
  `GDAL_CURL_CA_BUNDLE`.
- **Earth Engine:** nada de `getInfo()` dentro de `ImageCollection.map()`, e o tipo nativo é
  preservado (Landsat L2/S2 = uint16). Veja C-01 e C-02 no backlog.
- **CBERS:** recorte por `srcWin` em pixels inteiros (grade nativa, sem reamostragem). Rejeite
  recortes 100% NoData. O footprint real vem de `coverage_pct`, porque o servidor do INPE trata
  `intersects` como bbox.
- Mensagens para o usuário em **português**. Ao editar arquivos CRLF, preserve o fim de linha.
- Termos de Uso: Google/Bing exigem o aviso (`TOS_TEXT`) antes do primeiro download.
- **Fonte ativa na janela principal:** `var_source` (`gee` | `inpe`). Os códigos de sensor do INPE
  começam com `INPE:`. Decida sempre por `inpe.is_inpe(sensor)`, nunca por listas fixas de
  sensores GEE. O download passa por `GEEPluginWindow._download_any`.

## 5. Ambiente e testes

```bat
install.bat                     :: cria %LOCALAPPDATA%\ArcMagery\venv (sobre o Python do QGIS) e instala o Add-In
run_tests.bat                   :: suite backend (Python 3) + suite ArcMap/GUI (Python 2.7)
set ARCMAGERY_LIVE=1            :: + testes com internet (INPE, Esri, Google)
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
3. `python build_release.py` gera `dist/ArcMagery-<versão>.zip` e `dist/SHA256SUMS.txt`.
4. `gh release create v<versão> dist/ArcMagery-<versão>.zip dist/SHA256SUMS.txt --notes-file CHANGELOG.md`.
   Sem esse passo, o atualizador dos usuários pede confirmação para instalar do `main` sem
   verificação.
