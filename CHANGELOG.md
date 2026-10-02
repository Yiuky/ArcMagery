# Changelog

Todas as alterações notáveis neste projeto serão documentadas neste arquivo.

O formato baseia-se no [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/) e este projeto segue o [Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [Não lançado]

## [2.4.3-nightly.20261006] - 2026-10-02

> Versão experimental (nightly): a busca do GEE não lista mais cenas sem nenhum pixel na área.

### 🛡️ Corrigido
- **GEE (Sentinel-2 e Landsat): cenas sem nenhum pixel na área.** A busca listava cenas cujo contorno
  publicado (aproximado) toca a área, mas que não têm imagem nela, como as da borda da faixa imageada
  (ex.: Sentinel-2C de 30/09/2026 no tile 21LVD, com 66% do tile sem dado). O download saía todo zero/NoData
  e o health check recusava. Agora a busca mede no servidor, na mesma consulta, a fração da área com
  pixel válido em cada cena: descarta as que cobrem menos de 0,5% (mesmo critério do INPE) e mostra a
  cobertura parcial na coluna Tile ("21LVD · 21% da AOI"). Vale para o ArcMagery e o QMagery.
- A janela de erro do health check não mostra mais o JSON inteiro do diagnóstico (ele continua no log do
  backend): mostra a falha, o que fazer e uma linha com tamanho, canto e bandas do recorte.

## [2.4.3-nightly.20261005] - 2026-10-02

> Versão experimental (nightly): login no Google Earth Engine sem prazo curto e atualizador que mostra a
> versão disponível e funciona quando a API do GitHub recusa a consulta.

### 🌟 Adicionado
- **Janela de atualização:** mostra a versão publicada no canal escolhido comparada à instalada
  ("Disponível no canal Experimental (nightly): v… (instalada: v…)" ou "Você já está na versão mais
  recente"), consultada em segundo plano ao abrir a janela e ao trocar de canal.

### 🛡️ Corrigido
- **Login no Google Earth Engine (ArcMagery):** o comando de autenticação era encerrado depois de 30 s sem
  atividade, enquanto a pessoa ainda entrava com a conta Google no navegador. O prazo passou a 300 s.
- **"Falha ao Consultar Releases":** a API do GitHub aceita só 60 consultas por hora por endereço sem
  login, e numa rede corporativa todos os computadores saem pelo mesmo endereço. Quando a API recusa ou
  falha, o atualizador agora consulta o feed de Releases e o `SHA256SUMS.txt` da Release, que não contam
  nesse limite (o pacote continua conferido pelo SHA-256). Se os dois falharem, a mensagem diz o motivo
  (limite do GitHub, certificado SSL do proxy, conexão recusada) e onde baixar o ZIP.

## [2.4.3-nightly.20261004] - 2026-10-02

> Versão experimental (nightly): autenticação do Google Earth Engine e diagnóstico no QGIS 3.26 (Python 3.9).

### 🛡️ Corrigido
- **QGIS 3.26 e anteriores (Python 3.9):** o `autenticar_gee.bat` (e o botão de autenticação do ArcMagery
  e do QMagery) falhava com `ImportError: DLL load failed while importing _ssl`. O `_ssl` desse Python
  usa o `libssl` de `<QGIS>\bin`, e o `ee_auth.py`, o `doctor.py` (diagnóstico do `install.bat`) e o
  `pylibs.py` importavam o `ssl` antes de registrar essa pasta (`qgis_env`). O mesmo erro fazia o teste
  de Python do ArcMagery descartar o Python do QGIS 3.26 para o GEE. No QGIS 3.28+ o Python já traz o
  `libssl` e não era afetado.
- Todos os módulos do backend registram o `<QGIS>\bin` antes de qualquer import (antes, `esri_core`,
  `gehist_core`, `spot_core`, `stac_core`, `sysenv`, `xyz_core` e `gee_core` só funcionavam no QGIS 3.26
  quando importados depois do `run_gee`; o `urllib` desligava o HTTPS em silêncio).
- GEE: os mosaicos e a inspeção de reserva por outro Python do QGIS registram as DLLs dele e acham
  qualquer versão instalada (a lista fixa só tinha QGIS 3.44.10, 3.34.10 e 3.28).
- Python 3.9: os avisos em inglês do Google sobre o fim do suporte ao Python 3.9 não aparecem mais na
  janela de autenticação; o diagnóstico mostra um alerta em português recomendando atualizar o QGIS.

### 🧪 Testes
- `tests/backend/test_qgis_dlls.py`: monta uma cópia do Python com o layout do QGIS 3.26 (`libssl` só em
  `<raiz>\bin`), confirma que ela reproduz o erro relatado e importa cada módulo do backend num processo
  novo. A suíte do backend passou inteira no Python 3.9 (com GDAL, numpy, Pillow e o earthengine-api
  instalado pelo `pylibs`), inclusive os testes ao vivo.

## [2.4.3-nightly.20261003] - 2026-10-02

> Versão experimental (nightly): correção do carregamento de cenas CBERS/Amazônia-1 de Nível 2 e testes ao vivo de todas as fontes.

### 🛡️ Corrigido
- **CBERS/Amazônia-1 Nível 2 (e histórico CBERS-2/2B):** cenas que não passavam pela área apareciam na
  tabela com "até 100% da área" e o carregamento falhava com "recorte 100% NoData". O INPE publica para
  elas só o retângulo envolvente da passagem (~10° no WFI), e no CBERS-2 Nível 2 até o polígono publicado
  erra (32 de 61 cenas de Cuiabá diziam cobrir a área e não tinham imagem nela). Agora a busca **mede a
  cobertura real** na própria imagem (leitura reduzida da janela da área) das cenas de Nível 2, das que só
  têm o retângulo e das de cobertura parcial, e descarta as que não cobrem. A busca dessas coleções leva
  ~15 s em vez de ~2 s. Vale para o ArcMagery e o QMagery.
- QMagery: os testes de interface gravavam nas configurações reais do usuário (pasta de saída temporária
  e aviso de termos aceito); agora rodam com um `%APPDATA%` próprio.

### 🧪 Testes
- **Suíte ao vivo de todas as fontes** (`tests/qgis/test_ao_vivo.py`, `ARCMAGERY_LIVE=1`): busca de cada
  sensor do GEE, coleção do INPE, grupo do SPOT, zoom do Google Earth histórico e do Wayback e provedor
  XYZ; download de cada produto e carga no QGIS, conferindo pixels válidos, simbologia e posição sobre a
  área. `tests/arcmap/test_carga_ao_vivo.py` carrega as mesmas imagens pelo caminho do ArcMagery
  (`.lyr`, bandas RGB, Stretch, camada num `.mxd`, simbologia conferida).

## [2.4.3-nightly.20261002] - 2026-10-02

> Versão experimental (nightly): o QMagery (plugin do QGIS) passa a ser instalável e atualizável por
> qualquer usuário, com as fontes funcionando de ponta a ponta. A 2.4.3-nightly.20261001 só funcionava
> numa cópia do repositório e tinha falhas no SPOT, no Landsat e nas camadas XYZ.

### 🌟 Adicionado
- **Distribuição do QMagery:** a Release traz o `QMagery-<versão>.zip` (pasta `qmagery/` com o backend
  embutido), pronto para *Instalar a partir do ZIP*, e o **repositório de plugins do QGIS**
  (`qgis_plugin/plugins.xml`, atualizado pelo workflow de Release): cadastrado uma vez, o Gerenciador de
  Complementos avisa e instala as novas versões. Manual: [docs/QMAGERY.md](docs/QMAGERY.md).
- QMagery: área de interesse por **camada vetorial** (só as feições selecionadas, se houver), **fila** de
  várias cenas, **Substituir camada** (mesmo grupo e posição), **miniatura** em todas as fontes,
  **chave do GEODES** com teste e cota, **projeto e autenticação do GEE**, **verificação do ambiente** com
  instalação dos componentes do Earth Engine e **Configurações** que salvam de verdade (pasta de saída,
  threads de tiles).
- QMagery: simbologia automática (multibanda do GEE em cor natural, índices com rampa de cores, SPOT e
  CBERS conforme a composição) e GeoTIFFs numa pasta permanente (Documentos\QMagery), não mais no `%TEMP%`.

### 🛡️ Corrigido
- QMagery: download do **SPOT** sempre falhava (a chave do GEODES não era enviada); a busca ignorava o
  grupo escolhido (satélite e multiespectral/pancromático) e a opção "cor natural" virava falsa cor sem aviso.
- QMagery: **Landsat 1–7** usavam as composições do Sentinel-2 (códigos inválidos para o backend).
- QMagery: **camadas XYZ** inválidas (o endereço perdia `{x}`, `{y}` e `{z}`).
- QMagery: o **ID do projeto do GEE** era lido e gravado num caminho errado; agora usa o mesmo
  `%APPDATA%\ArcGEE\gee_config.json` do ArcMagery (a chave do GEODES também é compartilhada).
- QMagery: o zoom escolhido no Google Earth histórico e no Wayback era ignorado; "todos os zooms" funciona.
- QMagery: fechar a janela ou atualizar o plugin com uma operação em andamento podia derrubar o QGIS.
- QMagery: versão "v1.0.0" fixa na interface; agora vem do `metadata.txt` (nightly aparece no QGIS como
  `X.Y.Z-beta.AAAAMMDD`, que ele ordena antes da estável).
- Atualizador do ArcMagery: escolhe o pacote da Release pelo nome (`ArcMagery-*.zip`), não pelo primeiro
  `.zip` (a Release agora traz também o do QMagery); a sincronização do repositório de desenvolvimento
  leva o `qgis_plugin`.
- CI: a checagem do selo de versão do README falhava desde a nightly anterior; a Release agora roda também
  a suíte do QMagery e a checagem de versões antes de publicar.

### 🔧 Alterado
- Repositório renomeado de `arcgis-google-earth-engine-explorer` para **`ArcMagery`**. O GitHub
  redireciona o endereço antigo, então o atualizador das versões já instaladas continua encontrando as
  novas versões.
- QMagery: código morto removido (as antigas abas `gui/*_tab.py`) e testes refeitos: contrato com o
  backend, paridade com o ArcMagery, empacotamento e interface (90 testes).

## [2.4.3-nightly.20261001] - 2026-10-01

> Versão experimental (nightly): inclusão do plugin QMagery para QGIS (suporte completo a GEE,
> INPE STAC com CBERS-2/2B/4/4A e Amazônia-1, SPOT 1-5, Google Earth Histórico, Esri Wayback e XYZ),
> integração de status de carga e paridade monorepo com ArcMagery.

### 🌟 Adicionado
- **Plugin QMagery para QGIS:**
  - Porta completa da funcionalidade do ArcMagery para o QGIS 3.x (PyQGIS).
  - Catálogo completo do INPE com suporte a todas as 30 coleções, incluindo CBERS-2, CBERS-2B, Cubes e Mosaicos.
  - Carregamento de rasters diretamente no painel de camadas do QGIS em resolução nativa.
  - Integração de status com marcação visual na tabela (`✓ Carregado`), barra de progresso com porcentagem centralizada e botões de ação alinhados.
  - Cancelamento atômico e imediato de tarefas em segundo plano sem travamentos ou janelas de console.

### 🛡️ Corrigido
- Tratamento de caracteres especiais e formato de data no salvamento de arquivos temporários no Windows.
- Ocultação da janela de console (`CREATE_NO_WINDOW` e `SW_HIDE`) em todas as operações de subprocesso.

## [2.4.2] - 2026-10-01

> Versão estável de correções: atualizador, interface, ponte com o ArcMap, backend e
> instaladores, com a documentação revisada.

### 🛡️ Corrigido
- **Atualizador:**
  - funciona com perfil ou `%TEMP%` com acento (ex.: `C:\Users\joão`): caminhos em unicode e `.bat` gravado
    na codificação do Windows, sem depender do `chcp`;
  - o `.bat` não encerra mais todos os `pythonw.exe` do computador, só a interface do ArcMagery (U-02);
  - caminhos com `&` e mensagens finais com acento legíveis;
  - "Voltar para a versão anterior" ignora backups da própria versão instalada, e um backup incompleto
    interrompe a atualização antes de mexer em qualquer arquivo;
  - pasta Documentos redirecionada para o OneDrive é respeitada.
- **Interface:**
  - na largura padrão, o botão **SPOT 1-5 (CNES)** e o **Configurar Projeto GEE** ficavam fora da tela;
    rótulos da barra de fontes encurtados e cabeçalho reorganizado;
  - fechar a janela durante uma operação não impede mais que ela reabra (threads e processos do backend
    encerrados junto);
  - a barra de status não fica mais presa em "Verificando..." quando o Python 3 falha ao iniciar;
  - configurações da janela XYZ não sobrescrevem mais as alteradas em Configurações;
  - acentuação dos rótulos da janela principal e textos sem exageros ("100%").
- **Ponte com o ArcMap:** erros do arcpy em português não deixam mais a carga esperando até o tempo
  limite; comandos curtos não ficam presos atrás de uma carga longa ("ArcMap ocupado").
- **Prazos do backend:** o download SPOT era encerrado após 120 s; agora o prazo conta inatividade (cada
  linha de progresso renova a contagem), com limites próprios para SPOT e para a instalação de componentes.
- **Backend:**
  - Earth Engine atrás de proxy com inspeção SSL: os certificados do Windows passam a valer também para a
    biblioteca do Google;
  - CBERS: o NoData original da cena (ex.: −9999 nos cubos NDVI/EVI) é mantido, em vez de ser trocado por 0;
  - CBERS em QGIS com GDAL anterior ao 3.4;
  - arquivos temporários e parciais (SPOT, quadrantes do GEE, `.part`) são apagados quando o download falha,
    e pastas temporárias antigas são limpas;
  - busca SPOT com cobertura mínima 0; nome de arquivo do GEODES saneado;
  - todo comando termina com uma linha JSON, mesmo em erro inesperado.
- **Extensão do ArcMap:** sem a interface aberta, o Add-In não exporta mais o contexto do mapa a cada
  0,6 s nem grava uma linha de log por ciclo.
- **Instaladores:**
  - `install.bat` encontra o QGIS mais novo (inclusive QGIS 4, `Program Files (x86)` e a variável
    `GEE_PYTHON3`), a mesma escolha da interface (`tools\find_python3.bat`);
  - corrigido o argumento `--install-path` que chegava ao diagnóstico com uma aspa no fim;
  - para se o ArcMap estiver aberto ou se o ArcGIS não estiver instalado; confere os erros de cópia;
  - `desinstalar.bat` oferece remover também os dados do plugin;
  - `atualizar.bat` avisa que traz a versão de desenvolvimento.
- **Release:** pacote reprodutível (mesmo commit, mesmo SHA-256), `SHA256SUMS.txt` sem CRLF e testes rodando
  antes da publicação.

### 🗑️ Removido
- Caixa de ferramentas `GEE_Tools.pyt`: estava quebrada (a ferramenta 1 chamava uma função inexistente e
  a 2, copiada para `Documentos\ArcGIS`, não encontrava a ponte). O `install.bat` apaga a cópia antiga.

### 📝 Documentação
- Manual reescrito: seções do Google Earth histórico e do Esri Wayback, tabela de satélites conferida com o
  código, recorte pela AOI descrito como ele é (retângulo envolvente), dados guardados no computador,
  endereços de rede, limitações conhecidas e capturas de tela atuais.
- Novos `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `CITATION.cff` e modelos de issue
  revisados.
- Logotipo sem texto, janela "Sobre" com versão automática e requisitos corretos (Python 3.8 a 3.14).

## [2.4.1] - 2026-09-30

> Versão estável com o mesmo conteúdo da prévia experimental `v2.4.1-nightly.20260930`. É por ela que
> quem está na v2.4.0 passa a ter o seletor de canal (a 2.4.0 ainda não o tinha).

### ✨ Adicionado
- **Canais de atualização estável × experimental:** seletor *Canal* no Assistente de Atualização (salvo nas
  Configurações). O experimental recebe as Releases nightly (`X.Y.Z-nightly.AAAAMMDD`, publicadas como
  pre-release); o estável nunca as instala. Quem está numa nightly e escolhe *Estável* recebe a oferta de
  voltar para a última estável (com backup). O aviso de nova versão na abertura segue o canal escolhido.
- **Sinalizador de versão experimental:** selo laranja **EXPERIMENTAL** na barra do topo, `[EXPERIMENTAL]` no
  título da janela e na tela de abertura.
- Ordenação de versões com sufixo (2.4.0 < 2.4.1-nightly.20260930 < 2.4.1) no atualizador e na checagem de
  downgrade do fluxo ZIP. O workflow de Release marca como pre-release as tags com sufixo.
- **Diagnóstico com correção automática** (`backend/doctor.py`): o `install.bat` enumera os problemas da
  máquina (Python e bits, GDAL/numpy/Pillow, internet e certificados por serviço, componentes do Earth
  Engine, login e projeto do GEE com teste real, venv antigo, espaço em disco, tamanho do caminho do
  pacote), **corrige o que é seguro** (instala os componentes do Earth Engine; tira de uso um venv
  quebrado) e diz "o que fazer" no resto. Relatório em `%LOCALAPPDATA%\ArcMagery\diagnostico.txt`.
  A tela de abertura ganhou o botão **Diagnosticar e corrigir** quando há problemas.
- **Earth Engine no QGIS antigo:** manifestos próprios para Python 3.9 (QGIS 3.2x; earthengine-api
  1.6.15) e 3.8 (earthengine-api 1.1.5). Antes só havia rodas para Python 3.10 a 3.14.

### 🛡️ Corrigido
- QGIS 3.26 (Python 3.9): "Sem roda compatível ... cffi" e `DLL load failed while importing _ssl` no
  `install.bat` (as verificações rodavam sem as DLLs do QGIS e acusavam GDAL ausente sem estar).
- Tela de abertura com altura fixa: textos longos empurravam os botões (inclusive "Instalar componentes do
  Earth Engine") para fora da janela. Agora a janela cresce com o conteúdo e os botões ficam numa linha própria.
- A linha do login do GEE repetia a mensagem longa dos componentes ausentes; agora só aponta para ela.

## [2.4.0] - 2026-09-30

### ✨ Adicionado
- **SPOT 1–5 (CNES SPOT World Heritage, 1986–2015):** quinta fonte da janela principal
  (*Fonte de imagens* › *SPOT 1-5 (CNES)*), pela API STAC do GEODES, com o mesmo fluxo do CBERS:
  grupos por satélite (multiespectral/pancromática), busca livre, miniatura, fila, grupo e
  *Substituir no TOC*. Composições falsa cor, SWIR/NIR/vermelho, multibanda e pancromática.
  - **Alinhamento automático à Esri World Imagery:** o produto L1A tem erro de posição de 150–480 m
    (medido em Cuiabá: SPOT 2 ~477 m, SPOT 5 ~145 m, translação quase uniforme). A correlação de fase
    em várias janelas mede e corrige o deslocamento: resíduo de 2–5 m, conferido de forma independente
    contra a Esri z16. Sem medição confiável, a cena entra sem correção e com aviso.
  - GeoTIFF em UTM SIRGAS 2000 na resolução nativa, bandas nomeadas (XS3, XS2, XS1, SWIR: o
    `IMAGERY.TIF` grava as bandas em ordem inversa ao XML do produto), pirâmides e `ACQUISITION_DATE`.
  - Pacotes baixados uma vez para `%LOCALAPPDATA%\ArcMagery\spot_cache`, com MD5 conferido.
- **Chave do GEODES:** aba *Configurações › Chave do GEODES (SPOT)* com *Testar chave* (valida e mostra
  a cota de downloads sem gastá-la), *Salvar* e um **tutorial** passo a passo com botão para o portal.
  A chave fica em `%APPDATA%\ArcGEE\geodes_config.json`. Sem chave, o download SPOT oferece a
  configuração em vez de falhar.
- **Tela de abertura:** confere em paralelo o Python 3, GDAL/numpy, internet (GEODES, INPE, Esri),
  login do GEE, chave do GEODES e ArcMap enquanto a janela principal é montada; ela abre já com o
  estado do GEE aplicado. Novo comando de backend `selfcheck` (~3 s).

- **Earth Engine sem pip (menos requisitos na máquina):** o `earthengine-api` e suas 25 dependências
  são baixados pelo próprio ArcMagery com `urllib` e os **certificados do Windows** (funciona com o
  proxy de inspeção SSL, onde o `pip` falhava), com versões fixas e SHA-256 conferido
  (`backend/pylibs_manifest.json`), para `%LOCALAPPDATA%\ArcMagery\pylibs\py3XY` (~26 MB, ~15 s).
  Basta o **Python do QGIS**: não é mais preciso venv, pip nem compilador. Um venv existente continua
  sendo usado sem mudança (a pasta só é ativada se o Python não tiver o `ee` próprio).
  - A tela de abertura ganhou a linha *Componentes do Earth Engine* e o botão **Instalar componentes
    do Earth Engine**, que instala e reverifica o login sem fechar a tela.
  - `install.bat` e `autenticar_gee.bat` usam o mesmo mecanismo; a autenticação passou a usar
    `backend/ee_auth.py` (não depende mais do `earthengine.exe` do venv).
  - Manutenção: `tools/build_pylibs_manifest.py` regenera o manifesto (pura > abi3 > uma roda por CPython 3.10–3.14).

### 🛡️ Corrigido
- `No module named 'ee'` aparecia como traceback cru na barra do topo e na autenticação (visto na máquina de
  um colega com a v2.3.2): agora é uma mensagem clara com a ação a tomar.

- **Rollback para a versão anterior:** *Assistente de Atualização › Método 3* reinstala o backup
  salvo antes da última atualização, pelo mesmo executor transacional (a versão atual é salva antes;
  se a restauração falhar, o executor volta a ela). Nunca copia a versão antiga para o repositório de
  desenvolvimento, e o mesmo botão desfaz o rollback.

### 🔧 Alterado
- O botão *Google Earth / Mosaicos XYZ...* fica fixo à direita da barra de fontes (não some quando os
  botões de fonte não cabem).
- O aviso de nova versão só aparece depois que a janela principal está visível.

## [2.3.3] - 2026-09-29

### ✨ Adicionado
- **Google Earth histórico (N-09):** terceira fonte da janela principal (*Fonte de imagens* › *Google Earth histórico (por data)*), com o mesmo fluxo do CBERS e do GEE:
  - o zoom (15 a 20, ~4,8 a ~0,15 m) ocupa o lugar do satélite. **Listar Datas do Google Earth** preenche a tabela com cada data do histórico da área no período (como no Google Earth Pro), a **cobertura** e o **provedor** (Maxar, CNES/Airbus...);
  - **Miniatura** da data, carga de uma ou várias datas pela **fila**, grupo no TOC e **Substituir no TOC**. A seleção mostra a estimativa de tiles, tamanho e tempo;
  - GeoTIFF recortado à área na **grade nativa EPSG:4326** (sem reamostragem), com a data em `ACQUISITION_DATE`/`TIFFTAG_DATETIME`. Datas com cobertura parcial ficam pretas fora da imagem e geram aviso;
  - implementado direto em Python (protocolo do catálogo *Time Machine*), sem executável externo: usa o repositório de certificados do Windows (rede com inspeção SSL), grava o GeoTIFF por partes e guarda os índices do catálogo em cache (`%LOCALAPPDATA%\ArcMagery\cache\gehist`).
- **Botão ■ Interromper** na barra de status: encerra a busca e os downloads em andamento (GEE, CBERS, Google Earth, Wayback) e esvazia a fila; as linhas ficam como *Cancelado*.
- **Esri Wayback** como quarta fonte da janela principal: versões com data de captura, satélite e resolução, zoom numa coluna (todos os zooms numa busca), miniatura, fila e carga no TOC.
- **Google Earth histórico em todos os zooms (15 a 20)** numa só busca, com a cobertura de cada zoom; em áreas grandes e no z20 a cobertura é estimada por amostragem (marcada com `~`).
- **Downloads de tiles mais rápidos e com memória constante:** 48 threads por padrão (configurável até 64 em *Configurações*), decodificação nas threads e no máximo `threads × 4` tiles em andamento. Google Earth, 2.596 tiles: 82 s → 20 s. Núcleos padrão = CPU − 2 (antes 4). Reprojeção GDAL multithread com memória limitada.
- **Limite de tiles de 20 mil para 100 mil** (Google Earth histórico e mosaicos XYZ, cerca de 6,5 Gpx no zoom 18), com tempo limite de 4 h por download.
- **Catálogo CBERS / Amazônia-1 ampliado de 12 para 32 coleções do STAC do INPE:**
  - **WFI Nível 4 DN** do CBERS-4A (55 m) e do CBERS-4 (64 m);
  - **cubos de dados sem nuvens (Brazil Data Cube):** CBERS-4 WFI 16 dias, CBERS-4/4A WFI 8 dias e CBERS-4 MUX 2 meses, com os produtos **NDVI** e **EVI** prontos;
  - **Nível 2** (correção sistemática, sem ortorretificação): CBERS-4A WPM, MUX e WFI; CBERS-4 MUX, WFI e PAN 10/5 m; Amazônia-1 WFI;
  - **histórico CBERS-2 / 2B (2003–2010):** CCD 20 m, HRC 2,5 m pancromática e WFI 260 m;
  - **mosaicos** CBERS-4 WFI do Brasil (abr–jun/2020) e CBERS-4A WFI da Paraíba (jul–set/2020), produto *RGB visual*.
- **Cobertura estimada:** os footprints do CBERS-2/2B são o retângulo envolvente da cena. A tabela mostra então "até X% da AOI".
- **Aviso de cobertura parcial:** após o recorte, o backend mede os pixels com imagem (`valid_pct`). Abaixo de 50% o usuário é avisado.

### 🛡️ Corrigido
- **Revisão de código (antes da publicação):**
  - várias datas do Google Earth / Wayback selecionadas baixavam em paralelo, cada uma com 48 threads (até ~288 conexões): agora uma linha por vez; downloads simultâneos de cenas GEE/CBERS limitados a 4 (os núcleos das Configurações servem ao geoprocessamento);
  - um tile do Google Earth com falha de rede abortava o download inteiro (e uma consulta sem resposta anulava a busca de datas): agora há uma segunda rodada para os tiles que falharam e aviso dos que faltarem;
  - pirâmides/estatísticas de um download anterior com o mesmo nome podiam ser reaproveitadas para a imagem nova;
  - a miniatura ignorava a camada AOI da busca; a amostragem de áreas longas e estreitas no z20 ficava vazia;
  - **Interromper** não encerra mais os downloads da janela *Mosaicos XYZ* e não trava a interface; uma busca antiga que terminava depois desligava o Interromper da busca atual.
- **Plugin preso por minutos depois de carregar uma cena CBERS** (visto no CBERS-2): o recorte terminava em ~4 s, mas o processo do backend ficava 5 a 15 min sem encerrar, com as conexões `/vsicurl/` do GDAL abertas com o servidor do INPE, e a interface esperava o fim do processo (até 30 min). Agora as conexões são fechadas antes da saída (4 s), a interface usa o resultado assim que ele chega e, ao estourar o prazo, encerra também o processo filho (antes ficavam backends órfãos).
- **Cenas CBERS-2/2B duplicadas na lista** (`CBERS_2_CCD_...` e `CBERS2_CCD_...` apontam para os mesmos arquivos no INPE): uma linha por cena, com o polígono real de uma e o horário real de aquisição da outra.
- **CBERS-4A WPM 2 m fusionada: "Cena ... sem as bandas rgb"**. O STAC do INPE publica a fusionada como um único COG `tci` com as 3 bandas (conferido em cenas de 2023 a 2026), e o plugin procurava `rgb`. Com o nome certo, o recorte ainda pegaria só a 1ª banda (`BuildVRT(separate=True)` num arquivo multibanda): assets únicos multibanda agora entram inteiros. Corrige também os mosaicos *RGB visual* do INPE.
- **Google Earth histórico: data 1 dia depois da do Google Earth Pro.** O catálogo guarda a data à 00:00 UTC e o Google Earth Pro a exibe no fuso local (UTC−3/−4), que cai no dia anterior. A lista, o nome da camada e a tag `ACQUISITION_DATE` passam a usar a data do Google Earth Pro (conferido pelo mantenedor: catálogo 2017-07-09 = 8/7/2017, 2022-06-28 = 27/6/2022); a data do catálogo fica em `ARCMAGERY_CATALOG_DATE_UTC`.
- **"Tempo limite esgotado (120s) aguardando resposta do ArcMap" ao carregar rasters grandes** (P-01): o ArcMap calculava estatísticas de todos os pixels e as pirâmides na própria thread. Agora o backend gera as pirâmides (.ovr) com o GDAL em vários núcleos, o ArcMap as reaproveita, as estatísticas são por amostragem (~25 Mpx) e o prazo cresce com o tamanho do raster. Medido com arcpy em 167 Mpx: 38,6 s → 2,1 s.
- **"'ascii' codec can't encode character u'ó' in position 1" ao carregar qualquer camada** (GEE, CBERS, Google, Esri) em máquinas sem o módulo `comtypes`:
  - a mensagem acentuada "Módulo 'comtypes' ausente..." passava por `str(e)` no Python 2 e derrubava a carga, embora o arquivo tivesse sido baixado;
  - as mensagens de erro agora são convertidas com segurança (`gee_bridge.err_text`, aceita unicode, UTF-8 e cp1252 do arcpy em pt-BR);
  - o **`comtypes` passa a vir embutido no add-in** (`Install/vendor`, licença MIT). O `pip` do `install.bat` falhava sem aviso na rede com inspeção SSL. Se o Python do ArcGIS já tiver o `comtypes`, o instalado continua valendo.
- **"O provedor não retornou nenhum tile"** (visto na Esri Clarity): a mensagem agora diz o que o servidor respondeu (ex.: `HTTP 404 × 2160`), mostra um tile de exemplo para abrir no navegador e indica o bloqueio do domínio pela rede ou a alternativa *Esri World Imagery*. O cache só de tiles vazios é descartado.
- As buscas nos mosaicos do INPE falhavam: o servidor responde HTTP 500 ao filtro `intersects`. A busca agora repete com `bbox` e calcula a cobertura real localmente.
- Os nomes dos assets passaram a ser comparados sem diferenciar maiúsculas e minúsculas.

## [2.3.2] - 2026-09-29

### 🧰 Repositório
- **Integração contínua (GitHub Actions):** a suíte do backend roda a cada push/PR no Windows com Python 3.12, e a consistência de versão entre `config.xml`, `gee_gui.py`, `gee_updater.py` e o selo do README é conferida.
- **Release automática por tag:** `git push origin vX.Y.Z` gera `ArcMagery-<versão>.zip` e `SHA256SUMS.txt` e publica a Release com as notas da versão. Não depende mais da GitHub CLI na máquina do mantenedor.
- **Modelos de issue** (bug e melhoria, indicando onde fica o log do ArcMap) e **modelo de pull request** com checklist.
- `build_icons.py` foi para `tools/`, pois é uma ferramenta de desenvolvimento.
- Removidas 5 imagens não usadas que entravam em todo `.esriaddin`.

### 🛡️ Corrigido
- **`desinstalar.bat`:**
  - encerrava **todos** os `pythonw.exe` do usuário; agora só a interface do ArcMagery;
  - recusa rodar com o ArcMap aberto;
  - confere cada remoção e remove a caixa de ferramentas `.pyt`;
  - limpa os arquivos de comunicação atuais;
  - oferece remover o ambiente Python do plugin.
- **`atualizar.bat`:**
  - numa pasta git, atualiza só por avanço rápido (`--ff-only`) e se recusa a sobrescrever alterações locais;
  - numa pasta ZIP, indica a Release verificada em vez de baixar o `main` sem verificação e copiá-lo por cima da pasta.
- O **selo de versão do README** estava desatualizado (v2.3.0); agora um teste impede isso.
- Os testes antigos de *health check* de raster falhavam sem GDAL e agora são pulados nesse caso.

---

## [2.3.1] - 2026-09-29

### ♻️ Integrado do C:\DOWNLOADER_EARTH (ideias revisadas, não o código literal)
- **Nomes legíveis dos satélites** nas datas e nos polígonos (ex.: `WorldView-3 (WV03)`, `GeoEye-1 (GE01)`, `WorldView Legion`, `Pléiades Neo`).
- **Tags padrão no GeoTIFF**, exibidas nas propriedades pelo ArcGIS e pelo QGIS: `TIFFTAG_DATETIME`, `ACQUISITION_DATE`, `SATELLITE_SENSOR` e `IMAGE_PROVIDER`.
- **Sistema de coordenadas** na janela Google Earth / XYZ: Web Mercator nativo, **WGS 84 (EPSG:4326)** ou SIRGAS 2000.
- **Não integrado, de propósito:**
  - a data da Esri gravada nos tiles do **Google**: é outra fonte, e a cena pode ser outra, então essa data não pode aparecer como data da imagem do Google. Agora ela é exibida só como *referência* explícita;
  - `verify=False` (desativava a verificação SSL);
  - o downloader do Google, que já existia no ArcMagery.

### 🛡️ Corrigido
- **Data não informada em zoom 18+** quando a imagem Esri daquela área só existe até o zoom 17 (a cena é apenas ampliada): a consulta agora desce para a camada de metadados seguinte.

---

## [2.3.0] - 2026-09-29

### 🌟 Adicionado: data das imagens e histórico (Esri World Imagery / Wayback)
- **Data de captura:** na janela Google Earth / Mosaicos XYZ, com a fonte Esri, o botão **Consultar datas desta área** mostra, para cada parte da área, a data da cena, o satélite (ex.: GE01, WV03), o fornecedor (Maxar/Vantor/Airbus), a resolução e quanto da área cada data cobre. Os dados vêm dos metadados públicos da Esri, conforme o zoom.
- **Histórico (Wayback):** lista as versões da World Imagery em que a imagem **mudou** naquele local, desde 2014, uma por data de captura (mesmo algoritmo do app Esri Wayback). Escolha a data e baixe aquela imagem.
- A data de captura entra no **nome da camada** (ex.: `Esri World Imagery z17 · captura 2020-06-29 (WV03) · Wayback 02/02/2022`) e nos **metadados do GeoTIFF**.
- **Polígonos com as datas de captura** (opcional), carregados junto do mosaico com contorno sem preenchimento e rótulo "data satélite", equivalentes à "Data das imagens" do Google Earth Pro.
- Google e Bing não têm API pública com a data das imagens, e isso é informado na janela.

### 🛡️ Corrigido
- **GDAL não carregava** ("No module named '_gdal'") quando o Python do QGIS era iniciado com `OSGEO4W_ROOT` já definida no ambiente (outro Python do QGIS, o shell do OSGeo4W ou uma variável de sistema), porque o `sitecustomize` do QGIS deixava de registrar `<QGIS>\bin`. O backend agora registra o diretório de DLLs por conta própria (`qgis_env.py`).
- A mensagem de "GDAL/numpy indisponível" agora inclui o erro real de importação.

---

## [2.2.1] - 2026-09-29

### 🛡️ Corrigido
- **"Simbologia não pôde ser verificada: FocusMap" ao carregar no ArcMap:** `IApplication.Document` devolve a interface genérica `IDocument`, e `FocusMap`, `SelectedLayer`, `ActiveView` e `UpdateContents` só existem em `IMxDocument` (`esriArcMapUI`). Agora é feito o `QueryInterface(IMxDocument)`, e o TOC e o mapa são atualizados depois da correção. O mesmo defeito, antes mascarado, afetava a localização da camada viva nos fluxos antigos e a detecção da camada selecionada no TOC.

### 🧪 Testes
- Regressão que simula o `AppRef` do ArcMap (um `IDocument` sem `FocusMap`) com um mapa real por trás.

---

## [2.2.0] - 2026-09-28

### 🛡️ Simbologia garantida na carga
- **Novo motor `arcmagery_symbology.py`:** o renderer é montado de uma vez (RGB Composite com as bandas escolhidas, ou Stretched para uma banda), com tipo de stretch, nº de desvios padrão e origem das estatísticas (DRA). O `.lyr` é gravado e **relido do disco** para conferir cada propriedade, incluindo o stretch.
- **Camada viva localizada pelo caminho exato do arquivo** (`IRasterLayer.FilePath`), com expansão de nomes curtos 8.3 do `%TEMP%`. Antes era por nome aproximado, e a simbologia podia cair numa camada anterior de nome parecido; essa era a causa provável do *"às vezes o stretch falha"*. A camada é conferida depois da inserção e corrigida se preciso.
- Rasters de **uma banda** (índices, pancromática) agora também têm stretch aplicado e conferido.
- Quando a simbologia não pode ser garantida (ex.: `comtypes` ausente), o usuário recebe **aviso** em vez de sucesso silencioso.
- **Configurações › Aplicar e garantir stretch** preserva a combinação de bandas de cada camada; antes redefinia para 1-2-3.
- **Configurações:** salvar ou aplicar não apaga mais outras opções (Python 3 escolhido, pasta de saída, aceite dos Termos de Uso).

### ♻️ Removido
- Botões **Composição**, **Forçar RGB** e **Garantir Stretch** da janela principal: a carga já entra composta e com stretch conferido.

### 🧪 Testes
- `tests/arcmap/test_symbology.py` exercita o **ArcObjects real** fora do ArcMap: `.lyr` → inserção num `.mxd` com `arcpy.mapping` → leitura via COM. Cobre todos os tipos de stretch, uma banda, correção da camada certa sem tocar vizinhas de nome parecido, caminho 8.3 e preservação de bandas.

---

## [2.1.0] - 2026-09-28

### 🌟 Aprimorado
- **CBERS / Amazônia-1 integrado à janela principal:** a nova barra **Fonte de imagens** alterna entre *Google Earth Engine* e *CBERS / Amazônia-1 (INPE)*. A troca adapta a janela:
  - a lista de satélites passa a mostrar as 12 coleções do INPE, com período, resolução e bandas no quadro informativo;
  - a lista de composições passa a oferecer cor natural, falsa cor, multibanda, pancromática e fusionada;
  - o botão de busca muda para "Buscar Cenas no INPE";
  - os campos exclusivos do GEE (bandas personalizadas, modo de carga, tamanho do pixel) ficam desabilitados, porque o recorte do INPE é sempre na grade nativa.
- **O CBERS usa os recursos da janela principal:**
  - mesmo período e mesma área (extensão da tela ou AOI);
  - mesma tabela de resultados, com a coluna *Órbita/Ponto · Cobertura da AOI %*;
  - mesma fila de download e multicore;
  - mesmo "Carregar" e "Substituir no TOC";
  - mesmo agrupamento no TOC (padrão `INPE_<coleção>_<produto>_<data>`).
  - Não exige login no Google Earth Engine.
- **Botão [ Miniatura ]** na janela principal, para cenas do GEE e do INPE.
- A janela separada passa a ser só **Google Earth / Mosaicos XYZ**, com acesso pela barra *Fonte de imagens*.

### 🧪 Testes
- `tests/arcmap/test_inpe_integration.py`: monta a janela principal real (com a ponte simulada) e percorre troca de fonte → busca → tabela → download → `load_layer` com `rgb_bands`, e confirma que o fluxo do GEE continua igual.

---

## [2.0.0] - 2026-09-28

O projeto passa a se chamar **ArcMagery**. O identificador do Add-In (`AddInID`), os nomes internos dos módulos e as pastas de dados (`%APPDATA%\ArcGEE`, `%LOCALAPPDATA%\CGMA_ArcGEE`) foram mantidos para que as instalações existentes continuem atualizando e preservem configurações e backups.

### 🌟 Adicionado
- **Google Earth / Mosaicos XYZ** (botão `Google Earth / CBERS` → aba *Google Earth / Mosaicos XYZ*):
  - Fontes: Google Earth / Satélite, Google Híbrido, Esri World Imagery, Esri Clarity e Bing Aerial.
  - Estimativa instantânea (tiles, pixels, m/pixel e MB) antes de baixar, com limite de segurança de 20.000 tiles.
  - Download paralelo com retentativas, cache em disco e **retomada** após falhas.
  - GeoTIFF gravado tile a tile via GDAL (BigTIFF, compressão JPEG ou LZW), recortado exatamente à área em EPSG:3857 nativo. Reprojeção opcional para SIRGAS 2000 (EPSG:4674).
  - Aviso de Termos de Uso antes do primeiro download do Google ou do Bing.
- **CBERS-4/4A e Amazônia-1 via STAC do INPE** (aba *CBERS / Amazônia-1*):
  - 12 coleções: WPM 2 m/8 m, WPM fusionada 2 m, MUX 16/20 m, WFI 55/64 m, PAN 5/10 m e Amazônia-1 WFI.
  - Busca por período, nuvens e área, com **cobertura real da AOI (%)** calculada sobre o footprint de cada cena.
  - Miniaturas das cenas.
  - Recorte por leitura parcial HTTP (`/vsicurl/`): só a janela da área é transferida, na **grade e resolução nativas** (sem reamostragem).
  - Produtos: cor natural, falsa cor, multibanda e pancromática.
- Suítes de testes automatizados (`run_tests.bat`):
  - `tests/backend` (Python 3) com servidores HTTP locais que simulam o provedor XYZ e o STAC.
  - `tests/arcmap` (Python 2.7), cobrindo ponte, interface, atualizador e regressão do `pythonw`.
  - Testes ao vivo opcionais (`ARCMAGERY_LIVE=1`).
- `build_release.py`: gera `ArcMagery-<versão>.zip` + `SHA256SUMS.txt` para publicação como GitHub Release.
- `BACKLOG.md` e `AGENTS.md`: backlog priorizado e guia de contribuição para outros desenvolvedores e modelos de IA.

### 🛡️ Corrigido
- **Máscara de nuvem dos mosaicos nunca era aplicada:** `mask_clouds_and_shadows` chamava `getInfo()` dentro de `ImageCollection.map()`, que o Earth Engine rejeita; o `except` engolia o erro. A máscara agora é 100% server-side (SCL no S2 e QA_PIXEL no Landsat).
- **Mosaicos Landsat truncados:** `toInt16()` sobre valores L2 uint16 cortava a refletância acima de 0,70 e a banda térmica ST_B10 (~45.000 DN). A mediana volta ao tipo nativo (uint16/uint8).
- **Worker de download morria sob `pythonw`:** o redirecionamento de `stdout` da v1.12 nunca era ativado, porque `write("")` funciona com o descritor inválido (`fileno() == -2`). Um `print` grande gerava `IOError(9)`. A detecção agora usa `fileno()`.
- **Interface acessando o Tk fora da thread principal:** a validação de escala/AOI, que roda em threads de trabalho, lia widgets e abria diálogos diretamente. Agora usa `ui_call`/`_mb`.
- **Comunicação entre processos:** arquivos por sessão (PID do ArcMap), escrita atômica (`MoveFileEx`) e **instância única** da interface por ArcMap.
- **Seleção do Python 3:** o Python do backend deve ter `earthengine-api`; o alias da Microsoft Store é ignorado. Um interpretador com GDAL é escolhido para CBERS/XYZ, e o `pythonw` da interface é obtido do próprio ArcGIS (`sys.prefix`).
- `PYTHONIOENCODING=utf-8` no backend: os acentos não somem mais das mensagens de progresso.
- Miniatura do GEE com timeout, e o arquivo de imagem passa a ser fechado.
- **Bloqueio de downgrade no atualizador nunca era ativado:** a versão do pacote ZIP era lida como "Desconhecida", porque o `config.xml` usa namespace XML.
- O erro real do recorte CBERS não era mais mascarado por uma falha no `gdal.Unlink` do `finally`.

### 🔐 Segurança
- **Atualizador:** o canal padrão passa a ser a **GitHub Release**, com `SHA256SUMS.txt` conferido antes de qualquer extração. Instalar do branch `main` sem verificação exige confirmação explícita, downgrade exige confirmação, e o download incompleto é detectado.

### 🔧 Instalação e manutenção
- `install.bat` cria um **venv próprio** (`%LOCALAPPDATA%\ArcMagery\venv`, com `--system-site-packages` sobre o Python do QGIS). O QGIS não é alterado, outros projetos não são afetados, e o venv tem `earthengine-api` e GDAL juntos. Os erros agora são verificados em cada etapa.
- `autenticar_gee.bat` usa o venv do ArcMagery (sem caminhos fixos da máquina do desenvolvedor).
- `deploy.ps1`: sem caminhos fixos; encerra só a interface do ArcMagery, não todos os `pythonw.exe`; falha com código de saída.
- Removida a cópia duplicada `backend/` da raiz: a fonte única é `arcgis_addin/Install/backend`.
- `requirements.txt` declara Pillow e numpy e documenta a dependência de GDAL.

---

## [1.12.0] - 2026-09-28

### 🌟 Adicionado & Aprimorado
- **Modo RGB Composite Nativo Padrão na Carga Inicial:**
  - Corrigido o comportamento em computadores sem `comtypes` ou onde o acesso COM não está disponível: a imagem agora entra nativamente em modo **RGB COMPOSITE** em vez de escala de cinza (`RasterStretchRenderer`).
  - Utilização primária da geoprocessing tool `arcpy.MakeRasterLayer_management` para criar a camada em memória já inicializada com `IRasterRGBRenderer` nativo do ArcGIS Desktop para rasters multibanda ($\ge 3$ bandas).
  - Preservado fallback gracioso com `arcpy.mapping.Layer` e pipeline comtypes / percent clip stretch em Red, Green e Blue (`0.5%` / `0.5%`).
- **Execução Multi-Escopo no TOC (Camada, Grupo ou Todo o TOC):**
  - Os botões de controle de simbologia da interface:
    - `[ Composição ]` (Presets: 4-3-2, 8-4-3, 7-6-4, etc.)
    - `[ Forçar RGB ]` (Mapeia canais 1, 2, 3 em Red, Green, Blue)
    - `[ Garantir Stretch ]` (Aplica Percent Clip DRA automático nos 3 canais)
    agora operam de forma dinâmica e abrangente sobre qualquer escopo selecionado na lista suspensa do TOC.
  - A lista do TOC passa a listar organizadamente:
    - `[Todo o TOC]` — executa a operação em todos os rasters de todas as camadas do projeto.
    - `[Grupo] <nome_do_grupo>` — executa a operação em todas as subcamadas raster pertencentes ao grupo selecionado.
    - Camadas individuais — executa a operação estritamente na camada escolhida.
- **Extração Dinâmica de Grupos e Despacho Desacoplado no Cliente:**
  - Extração inteligente de nomes de grupos do TOC via inspeção da propriedade hierárquica `longName` das camadas do ArcMap.
  - Resolução dinâmica client-side no módulo GUI (`resolve_layer_names`): expande seleções de grupo ou TOC completo para chamadas individuais ao backend sem exigir reinicialização do processo do ArcMap ou do bridge.

---

## [1.11.0] - 2026-09-28

### 🛡️ Corrigido & Otimizado
- **Eliminação de Deadlock no Pipe do Windows (`run_backend_cmd`):**
  - Identificada e corrigida a causa-raiz que congelava a busca de imagens por vários minutos: o buffer de pipe anônimo do Windows (4 KB) lotava ao receber o JSON de resultados da busca (> 6 KB a 30 KB), fazendo com que o subprocesso Python bloqueasse em kernel space enquanto o processo pai aguardava término sem ler `stdout`.
  - Implementadas threads leitoras em segundo plano (`_stream_out` e `_stream_err`) que drenam ativamente os descritores de arquivo em tempo real, eliminando qualquer possibilidade de travamento de buffer.
- **Aceleração da Busca no Google Earth Engine (`search_collection`):**
  - Otimização com `coll.select([])` para suprimir a serialização de metadados das 15–20 bandas espectrais de cada imagem, reduzindo o volume de tráfego de rede e latência de resposta em até 80% (respostas em ~0.8 a 5 segundos).
  - Validação, ordenação e normalização defensiva das coordenadas de `bbox` (min/max e limites de longitude/latitude WGS84).
- **Timeouts Adaptativos e Recuperação Graciosa da UI:**
  - Definidos timeouts específicos por operação (90s para buscas, 600s para downloads pesados, 30s para verificações de conexão).
  - Garantida a liberação do botão `[ Buscar Imagens no GEE ]` e exibição de feedback imediato ao usuário em caso de timeout de rede ou catálogo vazio.

---

## [1.10.0] - 2026-09-28

### 🌟 Adicionado & Aprimorado
- **Validação Atômica Pós-Processamento (Health Check Defensivo de Raster):**
  - Implementada a engine multi-camadas `validate_geotiff_health` para inspeção rigorosa do produto antes da entrega ao usuário:
    - **Contagem Estrita de Bandas:** Valida que `raster.count == len(selected_bands)`. Se 4 bandas foram solicitadas, o arquivo final conterá obrigatoriamente 4 canais.
    - **Integridade Espacial e CRS:** Asserção de dimensões válidas ($W > 0, H > 0$), resolução espacial no geotransform e definição de projeção.
    - **Análise Per-Band de Dados:** Detecção proativa e bloqueio de rasters com dados nulos, all-NaN ou constantes vazias (`stdDev == 0.0` com `mean == 0.0`).
  - **Descarte Atômico e Diagnósticos Estruturados:** Em caso de falha, descarta imediatamente o arquivo defeituoso e tiles temporários, grava diagnósticos estruturados em JSON e levanta a exceção tipada `RasterHealthCheckError`.
- **Discriminador Robusto de Bandas vs. Fórmulas Matemáticas (`is_math_expr` / `parse_bands`):**
  - Suporte a listas de bandas envolvidas em parênteses `(SR_B3, SR_B4, SR_B5, SR_B7)` ou colchetes `[SR_B3, ...]` sem falso positivo de fórmula matemática.
  - Expansão inteligente de intervalos por hífen (ex: `B3-B5, B7` ou `SR_B3-SR_B5, SR_B7` expande automaticamente para `['SR_B3', 'SR_B4', 'SR_B5', 'SR_B7']`).
  - Normalização automática para satélites da série Landsat (prefixos `SR_` ópticos e `ST_` termais) e Sentinel-2, com tratamento específico para Landsat 5 TM (`ST_B6`, eliminando erros por `SR_B6`).
- **Mecanismo de Atualização Transacional e Atômico (`gee_updater.py`):**
  - Pré-validações rígidas (*pre-flight checks*) tanto para Git (conectividade, status de working tree, divergência) quanto para arquivos ZIP (integridade de checksum/hash, proteção contra Zip Slip, espaço em disco e permissões).
  - Snapshot completo de segurança e backup pré-atualização com retenção automática dos 5 backups mais recentes e reversão (*rollback*) automática em caso de interrupção ou falha.
  - Janela modal amigável com orientações práticas de resolução (*remediation steps*).

### 🛡️ Corrigido
- **Correção Definitiva do Colapso de Bandas no Landsat 5 / Multibanda:**
  - Corrigido o gargalo onde expressões com parênteses eram enviadas ao motor de expressões do GEE, que retornava apenas a última banda como índice monocanal `CUSTOM_INDEX` (Float32).
  - Corrigido o empilhamento nos mosaicos espaciais particionados (`merge_geotiff_tiles`): inclusão mandatória de `bandList` no GDAL nativo, no subprocesso Python QGIS e flags `-b` no GDAL CLI, garantindo que todas as bandas dos quadrantes sejam preservadas.
  - Corrigida a renderização ArcObjects no ArcMap: inclusão da chamada mandatória `rend_base.Update()` ao configurar o `IRasterRGBRenderer`, eliminando o fallback silencioso para exibição em escala de cinza (`RasterStretchRenderer`).

---

## [1.8.0] - 2026-09-25

### 🌟 Adicionado
- **Exibição de Bandas Disponíveis em Tempo Real:**
  - Novo indicador visual dinâmico integrado ao quadro azul do sensor selecionado, exibindo a lista completa de bandas disponíveis no catálogo GEE (ex: `B1 a B12` no Sentinel-2, `SR_B1 a SR_B7, ST_B10` no Landsat 8/9, `B4 a B7` no Landsat MSS).
  - Inclui ajuste automático de quebra de linha (`wraplength`) e atualização instantânea ao alternar o satélite.
- **Opção Explícita de Bandas Personalizadas no Combobox:**
  - Adicionada a opção `CUSTOM_BANDS - BANDAS PERSONALIZADAS (Digite na caixa abaixo: ex: B8,B4,B3)` em todos os sensores, diferenciando explicitamente a digitação de bandas soltas da digitação de fórmulas de índices biofísicos.

### 🛡️ Corrigido
- **Correção na Carga de Bandas Personalizadas Separadas por Vírgula:**
  - Corrigido problema onde digitação de bandas separadas por vírgula (ex: `B4,B3,B2` ou `B8,B4,B3`) sob a opção de personalização caía no cálculo de expressão matemática do GEE, que retornava apenas a última banda como índice monobanda (`Float32`).
  - Implementado discriminador inteligente: se o texto não contiver operadores matemáticos (`+`, `-`, `*`, `/`, `(`, `)`), é tratado categoricamente como lista de bandas (`is_index = False`), baixado em resolução nativa estrita e mapeado diretamente como RGB Composite `(0, 1, 2)` no ArcMap.
- **Auto-Detecção de Satélite e Tradução Cruzada de Bandas:**
  - O backend agora inspeciona o ID canônico da imagem no GEE e detecta o satélite real, traduzindo automaticamente prefixos de bandas (ex: converte `SR_B5` para `B5` em cenas Sentinel-2 e `B5` para `SR_B5` em cenas Landsat), eliminando o erro `Image.select: Band pattern did not match any bands`.
  - Ao alterar o satélite no combobox, a lista de resultados da busca anterior é limpa automaticamente com aviso ao usuário, prevenindo disparar downloads com satélites conflitantes.
- **Novo Atualizador Totalmente Desacoplado (Prevenção de Locks no Windows):**
  - O instalador embutido via ZIP e GitHub agora utiliza ambiente de Staging temporário e despacha o processo de atualização de forma desanexada (`apply_arcgee_update.bat`), encerrando a interface gráfica antes de substituir arquivos no `AssemblyCache` e no `Documents\ArcGIS\AddIns`.
  - Elimina completamente o erro de acesso negado (`[WinError 32]`) causado por travas de arquivo no Windows, garantindo atualização segura sem necessidade de desinstalar e reinstalar o Add-In.

---

## [1.7.0] - 2026-09-25

### 🌟 Adicionado
- **Opção de Controle de Visibilidade de Camadas no TOC:**
  - Nova preferência em **⚙ Configurações**: *Carregar imagens no TOC com visualização ativada (visíveis no mapa)*.
  - Quando desmarcada, as novas imagens entram desmarcadas no TOC (`[ ]`), ideal para carregar lotes de cenas pesadas sem congelar a renderização da tela do ArcMap.
  - Preferência gravada de forma persistente em `~/.gee_plugin_settings.json` e aplicada tanto em camadas individuais quanto dentro de grupos.
- **Redesenho Completo da Janela de Configurações:**
  - Interface moderna com Abas (`ttk.Notebook`): *Visualização & TOC* e *Processamento & Sistema*.
  - A barra inferior de botões (*Restaurar Padrões*, *Cancelar* e *Salvar Configurações*) agora fica prioritariamente fixada na base da janela (`side=BOTTOM`), garantindo que nunca seja suprimida ou empurrada para fora da tela.
  - Dimensão compacta (540x510px) 100% compatível com monitores de qualquer resolução e escalas de DPI (125%, 150%).

### 🛡️ Corrigido
- **Simbologia RGB Composite e Exibição em Bandas no ArcMap:**
  - Correção na simbologia de rasters com 3 ou mais bandas: injeção direta de `esriCarto.RasterRGBRenderer` (`IRasterRGBRenderer`) via ArcObjects com Stretch dinâmico (DRA), garantindo que a camada abra imediatamente como RGB no TOC (com canais Red, Green e Blue) em vez de rampa única de valores em escala de cinza (*Value High/Low*).
- **Seleção Estrita de Bandas no Download Multibanda:**
  - Ao selecionar uma composição (ex: `1182 - AGRICULTURA - 11.8.2`), o plugin agora exporta estritamente as bandas da composição selecionada (B11, B8, B2), em vez de forçar o download desnecessário de todas as 12 bandas do satélite.
- **Tratamento de Localização Regional e Vírgula Decimal no Salvamento de Configurações:**
  - Implementação de parsing resiliente de números (`_safe_float` e `_safe_int`), prevenindo exceções de `ValueError` causadas por vírgula em locale pt-BR nos Spinboxes (`2,0` -> `2.0`).

---

## [1.6.0] - 2026-09-25

### 🌟 Adicionado
- **Download Inteligente de Áreas Extensas (> 48 MB) com Particionamento Espacial (*Smart Spatial Tiling*):**
  - Permite o download de imagens e mosaicos cobrindo grandes extensões territoriais em escalas de até **1:500.000** sem bloqueio ou cancelamento pela cota de 48 MB do Google Earth Engine.
  - **Garantia Estrita de Qualidade Nativa 100%:** Elimina qualquer necessidade de reamostragem, preservando estritamente os 10 metros nativos no Sentinel-2 e os 30 metros no Landsat em toda a extensão do mapa.
  - **Grade Espacial Automatizada ($N_x \times N_y$):** O backend calcula a partição ótima de quadrantes baseada no número de bandas e resolução solicitada, mantendo cada requisição individual abaixo de 32 MB (com margem de segurança contra o teto de 48 MB).
  - **Micro-Sobreposição (*Overlap*) de Bordas:** Adição de margem de 1.5 pixels entre quadrantes internos adjacentes para garantir zero costuras, frestas ou artefatos de arredondamento cartográfico.
  - **Download Paralelo Multithread:** Os quadrantes da grade são baixados simultaneamente em segundo plano utilizando `concurrent.futures.ThreadPoolExecutor`, maximizando a velocidade de transferência.
  - **Mosaico Automatizado com GDAL:** Motor de fusão inteligente multi-plataforma que mescla os quadrantes em um único GeoTIFF contínuo georreferenciado com compressão LZW, estrutura interna em blocos (`TILED=YES`) e suporte a BigTIFF (`BIGTIFF=IF_SAFER`).
  - **Detecção e Descarte de Quadrantes Vazios na AOI:** Para camadas vetoriais irregulares, quadrantes que não interceptam o polígono de interesse são ignorados automaticamente, economizando banda e tempo de processamento.
  - **Feedback Visual Dinâmico:** A barra de status e o diálogo de progresso informam em tempo real a estimativa de tamanho em megabytes e a quantidade de quadrantes sendo baixados e mesclados.

### 🔄 Modificado
- **Priorização de Interpretadores Python com GDAL Nativo:** A busca por interpretadores Python 3 agora prioriza ambientes com suporte simultâneo à Earth Engine API e à biblioteca `osgeo.gdal` nativa (como o Python do QGIS 3.x), com fallback automático para subprocessos e CLI.
- **Atualização do Limite de Escala na Interface:** As mensagens e dicas da interface agora confirmam o suporte pleno a downloads de áreas de trabalho em escalas de até 1:500.000 em resolução nativa.

### 🛡️ Corrigido
- **Correção de Atribuição da Variável `is_multi`:** Resolução de erro em execuções no modo de carga rápida RGB (`load_mode='rgb'`), garantindo compatibilidade uniforme em todos os modos de exportação.

---

## [1.5.0] - 2026-09-24

### 🌟 Adicionado
- **Metadados de Período Operacional dos Sensores:** Exibição dinâmica do intervalo temporal de dados e do status de operação de cada satélite/sensor selecionado (Sentinel-2 MSI, Landsat 8/9 OLI, Landsat 7 ETM+, Landsat 4-5 TM, Landsat 1-5 MSS).
- **Verificação Automática de Atualização na Inicialização:** Rotina assíncrona em segundo plano que consulta o GitHub para verificar a existência de novas versões do plugin sem congelar a interface.
- **Bypass de Cache CDN do GitHub:** Requisições de checagem com cabeçalhos anti-cache (`Cache-Control: no-cache, no-store`) e parâmetro aleatório de timestamp para garantir que o cliente receba a versão mais recente em tempo real.
- **Notificação Não-Intrusiva na UI:** Indicação sutil na barra de status informando quando há uma nova versão disponível, com acesso direto ao atualizador integrado.

### 🔄 Modificado
- **Otimização de SEO e Rebranding do Repositório:** O repositório oficial no GitHub foi renomeado para `arcgis-google-earth-engine-explorer`, maximizando a relevância e indexação em mecanismos de busca (Google, Bing e GitHub Search).
- **Evolução do Mecanismo de Deploy:** O script de implantação foi aprimorado para validar a compatibilidade de bytecode entre diferentes revisões do ArcGIS 10.8 e 10.8.2.

### 🛡️ Corrigido
- **Correção de Sintaxe no Bloco de Checagem (Python 2.7):** Resolução de um erro de indentação e omissão de bloco condicional que causava encerramento silencioso do processo `pythonw.exe`.
- **Purga Atômica de Bytecode (`.pyc`) no AssemblyCache:** Eliminação de arquivos de bytecode antigos e corrompidos na pasta de cache do ArcGIS durante o processo de atualização via ZIP ou Git, impedindo que o ArcMap execute códigos compilados obsoletos.
- **Isolamento de Arquivos no Instalador:** Prevenção contra extração acidental de arquivos de raiz do repositório (`.gitignore`, `README.md`) para dentro do diretório de montagem de extensões do ArcGIS.

---

## [1.4.2] - 2026-09-24

### 🌟 Adicionado
- **Nova Identidade Visual Oficial (Ícone 3D):** Criação e integração do logotipo moderno do satélite em múltiplos formatos e resoluções (`16x16`, `20x20`, `24x24`, `32x32`, `48x48`, `64x64`, `.ico` e `.png`).
- **Botão Oficial com Ícone e Texto no ArcMap:** Barra de ferramentas configurada para exibir o rótulo **ArcGEE Explorer** acompanhado do ícone temático.
- **Exibição do Logotipo em Alta Resolução:** Janela "Sobre" enriquecida com o emblema do satélite.

### 🔄 Modificado
- **Padronização de Nomenclatura:** Atualização do nome oficial da aplicação em toda a interface e documentação para **ArcGEE Explorer**.
- **Simplificação da Barra Superior:** Remoção do botão redundante de stretch no topo da janela, consolidando todas as configurações de realce radiométrico dentro do painel de preferências avançadas.

---

## [1.4.1] - 2026-09-24

### 🌟 Adicionado
- **Assistente Integrado de Atualizações (Dual-Mode Updater):**
  - *Método 1 (Online):* Download direto e atualização automática em 1 clique a partir da branch principal do GitHub.
  - *Método 2 (Offline / Manual):* Atualização a partir de arquivo `.zip` baixado manualmente pelo usuário.
- **Janela Modal "Sobre" (About Dialog):** Informações detalhadas da versão, arquitetura, licença MIT, créditos de desenvolvimento e atalhos rápidos.
- **Buffer Envolvente Configurável para Camada Vetorial (AOI):** Adição de margem de segurança configurável (padrão de 1.000 metros) ao redor de polígonos de estudo para garantir cobertura completa de bordas.
- **Scripts Auxiliares de Manutenção:** Inclusão dos scripts `desinstalar.bat` (limpeza completa de Add-In e caches) e `atualizar.bat` (atualizador via terminal).

### 🛡️ Corrigido
- **Compatibilidade do Descompactador ZIP no Python 2.7:** Substituição da chamada `ZipInfo.is_dir()` (incompatível com Python 2.7) por validação de terminação de diretório (`name.endswith('/')`).
- **Sanitização de Geometria GeoJSON para AOI:** Reprojeção prévia para WGS84 (EPSG:4326) e correção de polígonos complexos, eliminando a mensagem de erro `"Invalid GeoJSON geometry"`.

---

## [1.4.0] - 2026-09-23

### 🌟 Adicionado
- **Garantia Estrita de Qualidade Nativa 100%:**
  - Proibição de reamostragem silenciosa: preserva estritamente os 10 metros nativos no Sentinel-2 e os 30 metros no Landsat.
  - Eliminação de qualquer risco de degradação de dados espectrais ou espaciais.
- **Checagem Preventiva do Limite do Earth Engine (48 MB):**
  - Estimativa do tamanho da cena antes do download com base no número de bandas e tamanho do pixel.
  - Bloqueio preventivo caso a requisição exceda o teto de download da API do GEE, fornecendo instruções claras ao usuário para ajustar o zoom (escala <= 1:250.000) ou refinar a AOI.
- **Painel de Configurações Avançadas de Realce (Stretch & Statistics):**
  - Controle completo sobre o método de stretch padrão no ArcMap: *Standard Deviations* (`n` desvios configuráveis), *Dynamic Range Adjustment (DRA)*, *Percent Clip*, *Minimum-Maximum* e *Histogram Equalization*.
- **Agrupamento Puro no TOC (`GroupLayer`):** Inserção de imagens dentro de camadas de grupo convencionais do ArcMap, evitando o bloqueio de simbologia característico de basemaps compostos.

### 🔄 Modificado
- **Remoção do Modo "Cena Completa":** Substituído pelo foco estrito na extensão de tela e em polígonos vetoriais, otimizando o consumo de banda e garantindo alta performance.

---

## [1.3.0] - 2026-09-23

### 🌟 Adicionado
- **Cálculo de Índices Espectrais no Earth Engine:** Suporte nativo para geração direta de rasters Float32 monocamada:
  - **NDVI** (Índice de Vegetação por Diferença Normalizada)
  - **NDWI** (Índice de Água por Diferença Normalizada)
  - **NDMI** (Índice de Umidade por Diferença Normalizada)
  - **NBR** (Razão de Queima Normalizada / Detecção de Incêndios)
  - **EVI** (Índice de Vegetação Melhorado)
  - **SAVI** (Índice de Vegetação Ajustado ao Solo)
- **Matemática de Bandas Personalizada (Custom Band Math):** Permite ao operador inserir expressões matemáticas arbitrárias (ex: `(B8-B4)/(B8+B4)` ou `(SR_B5-SR_B4)/(SR_B5+SR_B4)`).
- **Modo Multibanda Bruta Completa:** Exporta todas as bandas espectrais nativas em um único GeoTIFF, permitindo ao usuário alterar a composição RGB diretamente nas propriedades da camada no TOC sem necessidade de refazer o download.
- **Suporte a Datas no Formato Brasileiro:** Campos de pesquisa com suporte nativo a `DD/MM/AAAA` (ex: `15/08/2024`) com validação automática e conversão para o padrão ISO `AAAA-MM-DD`.

### 🔄 Modificado
- **Busca Orbital Global:** Remoção do filtro espacial restrito ao território de Mato Grosso, permitindo buscas em qualquer localidade do planeta.

---

## [1.2.0] - 2026-09-23

### 🌟 Adicionado
- **Geração de Mosaicos Automáticos (Mediana Temporal):** Criação de mosaicos homogêneos e livres de nuvens a partir de múltiplas imagens selecionadas na grade de resultados.
- **Filtro Espacial por Camada Vetorial (AOI):** Seleção de qualquer camada vetorial (Shapefile ou Feature Class) ativa na Tabela de Conteúdos do ArcMap.
- **Seletor de Resolução Espacial Customizável:** Campo dedicado para definir o tamanho do pixel em metros (ex: 10m, 20m, 30m ou valores arbitrários).
- **Aceleração Multicore em Segundo Plano:** Processamento paralelo de múltiplos downloads simultâneos e cálculo paralelo de pirâmides e estatísticas no ArcPy (`parallelProcessingFactor`).
- **Caixa de Ferramentas Python Toolbox (`GEE_Tools.pyt`):** Disponibilização de ferramentas de geoprocessamento integradas ao ArcToolbox para workflows automatizados em ModelBuilder e scripts de linha de comando.

---

## [1.0.0] - 2026-09-23

### 🌟 Lançamento Inicial
- Arquitetura desacoplada e assíncrona via IPC estruturado (arquivos de comando JSON com bloqueio atômico) conectando o ArcMap 10.8 (Python 2.7) ao motor de geoprocessamento (Python 3.9+ e `earthengine-api`).
- Interface gráfica moderna e responsiva construída em Tkinter/ttk.
- Suporte inicial a coleções de dados Sentinel-2 (TOA/SR Harmonized) e Landsat 1 a 9 (MSS, TM, ETM+, OLI/TIRS).
- Filtros por satélite, período de datas, porcentagem máxima de cobertura de nuvens e escala visual.
- Sistema de miniaturas sob demanda (*On-Demand Thumbnails*) para inspeção rápida de cenas sem consumo excessivo de tráfego de dados.
- Configuração e autenticação persistente com projetos no Google Earth Engine.
