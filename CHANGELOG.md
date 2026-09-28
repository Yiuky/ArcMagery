# Changelog

Todas as alterações notáveis neste projeto serão documentadas neste arquivo.

O formato baseia-se no [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/) e este projeto segue o [Versionamento Semântico](https://semver.org/lang/pt-BR/).

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
- **Exibição do Logotipo em Alta Resolução:** Janela "Sobre" enriquecida com o emblema oficial do satélite e identificação visual da CGMA / SEMA-MT.

### 🔄 Modificado
- **Padronização de Nomenclatura:** Atualização do nome oficial da aplicação em toda a interface e documentação para **CGMA ArcGEE Explorer**.
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
