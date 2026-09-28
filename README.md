<p align="center">
  <img src="docs/images/logo.png" alt="CGMA ArcGEE Explorer Logo" width="170" />
</p>

<h1 align="center">CGMA ArcGEE Explorer</h1>

<p align="center">
  <strong>Google Earth Engine Integrado ao ArcGIS Desktop (ArcMap 10.8 / 10.8.2)</strong><br>
  <em>Pesquise, filtre, processe e descarregue imagens de satélite em resolução espacial nativa 100% diretamente no ArcMap</em>
</p>

<p align="center">
  <a href="https://www.esri.com/"><img src="https://img.shields.io/badge/ArcGIS%20Desktop-10.8%20%7C%2010.8.2-0079C1.svg?logo=esri&logoColor=white" alt="ArcGIS Desktop"></a>
  <a href="https://earthengine.google.com/"><img src="https://img.shields.io/badge/Google%20Earth%20Engine-API-4285F4.svg?logo=googleearthengine&logoColor=white" alt="Google Earth Engine"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-2.7%20%7C%203.9+-3776AB.svg?logo=python&logoColor=white" alt="Python Version"></a>
  <a href="CHANGELOG.md"><img src="https://img.shields.io/badge/Versão-v1.12%20Estável-28A745.svg" alt="Versão v1.12"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License MIT"></a>
  <a href="https://github.com/Yiuky/arcgis-google-earth-engine-explorer"><img src="https://img.shields.io/badge/GitHub-arcgis--google--earth--engine--explorer-181717.svg?logo=github&logoColor=white" alt="GitHub Repository"></a>
</p>

<p align="center">
  <a href="docs/MANUAL_DE_USO_E_INSTALACAO.md"><strong>📖 Manual de Instalação e Uso</strong></a> •
  <a href="CHANGELOG.md"><strong>📋 Changelog (Histórico)</strong></a> •
  <a href="https://github.com/Yiuky/arcgis-google-earth-engine-explorer/archive/refs/heads/main.zip"><strong>📥 Baixar Plugin (.ZIP)</strong></a> •
  <a href="#-instalação-rápida-em-1-clique"><strong>⚡ Início Rápido</strong></a> •
  <a href="#-english-abstract"><strong>🌐 English Summary</strong></a>
</p>

---

<p align="center">
  <img src="docs/images/interface_arcmap.png" alt="Visão Geral do CGMA ArcGEE Explorer no ArcMap" width="94%" />
</p>

---

## 📌 Visão Geral

O **CGMA ArcGEE Explorer** é uma extensão oficial (Python Add-In) para **ArcGIS Desktop 10.8 e 10.8.2 (ArcMap)** que conecta o ambiente cartográfico da ESRI diretamente ao catálogo e à infraestrutura de computação em nuvem do **Google Earth Engine (GEE)**.

Desenvolvido para operações de fiscalização ambiental, sensoriamento remoto e perícias territoriais na **Coordenadoria de Geoprocessamento e Monitoramento Ambiental (CGMA / SEMA-MT)**, o plugin elimina gargalos clássicos de trabalho (como downloads manuais pelo Google Drive, recortes pesados de cenas inteiras ou reamostragens involuntárias).

Com o ArcGEE Explorer, o operador filtra cenas orbitais no tempo e no espaço, inspeciona miniaturas sob demanda, calcula índices biofísicos em tempo real e carrega imagens com **100% de qualidade nativa** diretamente na Tabela de Conteúdos (**TOC**) do ArcMap.

---

## 🌟 Principais Recursos e Diferenciais

* **🛰️ Bandas Personalizadas, Atualizador Desacoplado & Informações de Sensores (Novidade v1.8):**
  * **Bandas Personalizadas Resilientes:** Digite qualquer combinação de bandas separadas por vírgula (ex: `B4,B3,B2` ou `B8,B4,B3`) e carregue diretamente como RGB nativo no ArcMap sem conversão indevida para índice espectral monobanda.
  * **Conversão e Auto-Detecção de Satélite:** O plugin detecta automaticamente a coleção correta da cena e traduz nomenclaturas cruzadas (ex: `SR_B5` $\leftrightarrow$ `B5`).
  * **Exibição de Bandas Disponíveis:** Quadro azul informativo exibe em tempo real todas as bandas válidas do satélite selecionado.
  * **Atualizador Offline e Online Desacoplado:** Atualização via arquivo ZIP local ou repositório GitHub sem qualquer travamento de arquivos do Windows (`WinError 32`), graças ao pipeline de execução desanexada em Staging.

* **🎨 Simbologia RGB Nativa e Seleção Estrita de Bandas (v1.7):**
  * **Renderização RGB Composite Imediata:** Ao carregar no ArcMap, rasters com 3 bandas utilizam o renderizador nativo `IRasterRGBRenderer`, abrindo os canais Red, Green e Blue no TOC com contraste e estatísticas dinâmicas (DRA) perfeitas.
  * **Seleção Estrita de Bandas:** Ao escolher uma composição (ex: `1182 - AGRICULTURA`), o plugin exporta estritamente as bandas selecionadas (B11, B8, B2), sem sobrecarregar o arquivo com bandas desnecessárias.
  * **Controle de Visibilidade no TOC:** Opção em Configurações para carregar novas camadas ativadas (`[x]`) ou desativadas (`[ ]`), ideal para baixar lotes pesados sem travar a renderização inicial da tela.
  * **Janela de Configurações Redesenhada:** Interface moderna com Abas (`ttk.Notebook`), botões de salvar fixados na base e suporte total à vírgula decimal regional.

* **🚀 Particionamento Espacial Inteligente (> 48 MB) e Qualidade Nativa 100% (v1.6):**
  * **Downloads de Áreas Extensas até 1:500.000:** Requisições que superam o limite de 48 MB do Earth Engine são automaticamente particionadas em uma grade dinâmica de quadrantes seguros, baixadas em paralelo multithread e mescladas em um único GeoTIFF contínuo via GDAL (com compressão LZW e BigTIFF).
  * **Zero degradação silenciosa:** Proibição absoluta de reamostragem espacial ou perda de nitidez. Os dados do Sentinel-2 preservam estritamente seus 10 metros e o Landsat seus 30 metros em toda a tela de trabalho.
  * **Micro-sobreposição (*Overlap*) de 1.5 pixels:** Bordas internas sobrepostas garantem zero costuras, frestas ou descontinuidades visuais no raster final.

* **🛰️ Período Operacional dos Sensores em Tempo Real (Novidade v1.5):**
  * Ao selecionar qualquer satélite/sensor na interface, os metadados de disponibilidade temporal de dados e o status de operação da missão são apresentados dinamicamente na tela (Sentinel-2, Landsat 9, Landsat 8, Landsat 7 ETM+, Landsat 4-5 TM e Landsat 1-5 MSS).

* **🔔 Verificação Automática de Atualizações (Novidade v1.5):**
  * O plugin consulta assincronamente o repositório remoto a cada inicialização (com bypass de cache de CDN) e avisa de forma sutil na barra de status quando houver novas versões estáveis disponíveis.

* **🔄 Assistente Integrado de Atualizações (Dual-Mode Updater):**
  * Atualize o plugin diretamente pela interface com **1 clique via GitHub** ou a partir de um arquivo **ZIP local**, com purga atômica de cache e recompilação automática de bytecode.

* **⚡ Arquitetura Assíncrona Desacoplada (IPC Seguro):**
  * A interface gráfica opera em processo próprio (`pythonw.exe`) comunicando-se com o ArcMap via arquivos JSON atômicos com trava contra reentrância.
  * **O ArcMap nunca trava ou congela** durante consultas pesadas ou downloads simultâneos.

* **🌱 Índices Espectrais e Matemática de Bandas (Float32):**
  * Cálculo em nuvem de índices como **NDVI**, **NDWI**, **NDMI**, **NBR (Queimadas)**, **EVI** e **SAVI**.
  * **Matemática de Bandas Personalizada:** Insira fórmulas arbitrárias (ex: `(B8-B4)/(B8+B4)` ou `(SR_B5-SR_B4)/(SR_B5+SR_B4)`) para descarregar rasters monocamada em ponto flutuante de 32-bit com rampa de cores automática e estatísticas calculadas.

* **🌈 Modo Multibanda Bruta Completo:**
  * Baixa todas as bandas espectrais nativas (ex: 10 bandas no Sentinel-2) em um único arquivo GeoTIFF.
  * Permite **alterar as bandas RGB diretamente no ArcMap TOC** a qualquer instante sem precisar refazer o download.

* **🎨 Painel Avançado de Realce Radiométrico (Stretch & DRA):**
  * Configuração padrão personalizável para exibição de imagens:
    * *Standard Deviations* (Desvios Padrão configuráveis: 1.5, 2.0, 2.5).
    * *DRA - Dynamic Range Adjustment* (Ajuste dinâmico à extensão visível).
    * *Percent Clip*, *Minimum-Maximum* e *Histogram Equalization*.

* **🗺️ Filtro Espacial Duplo (Tela e Vetor AOI com Buffer):**
  * **Extensão da Tela:** Utiliza a visualização cartográfica ativa do ArcMap.
  * **Camada Vetorial (AOI):** Seleciona Shapefiles ou Feature Classes do TOC e recorta a geometria exata, aplicando buffer de segurança configurável (padrão 1.000m) e reprojeção transparente para WGS84 (EPSG:4326).

* **🚀 Aceleração Multicore e Mosaicos Automáticos:**
  * Downloads simultâneos em segundo plano utilizando múltiplas threads de CPU.
  * Geração instantânea de mosaicos homogêneos livres de nuvens através de agregação por mediana temporal.

---

## 🏗️ Arquitetura do Sistema

```text
┌────────────────────────────────────────────────────────┐
│                   ArcMap 10.8 / 10.8.2                │
│  - Toolbar "CGMA ArcGEE Explorer" (Python Add-In)     │
│  - ESRI ArcPy Engine (TOC, Data Frames, Symbology)    │
│  - Win32 Native Timer IPC Listener (500ms)            │
└───────────────────────────▲────────────────────────────┘
                            │
               Arquivos de Comando JSON Atômicos
               (arcgis_gee_cmd.json / arcgis_gee_reply.json)
                            │
┌───────────────────────────▼────────────────────────────┐
│              Processo da GUI Independente              │
│  - Interface Tkinter / ttk (pythonw.exe isolado)       │
│  - Validação de Escala (1:500.000) e Cota (48 MB)      │
│  - Assistente de Atualização e Gerenciador de Tarefas  │
└───────────────────────────▲────────────────────────────┘
                            │ Subprocesso com Pipes JSON
┌───────────────────────────▼────────────────────────────┐
│            Motor Backend GEE (Python 3.9+)             │
│  - earthengine-api (ee.ImageCollection, Reducers)      │
│  - Filtragem Espacial, Mascaramento QA e Índices       │
│  - Download de GeoTIFF Multibanda 100% Nativo         │
└────────────────────────────────────────────────────────┘
```

---

## 💻 Requisitos do Sistema

| Requisito | Versão Homologada |
| :--- | :--- |
| **Sistema Operacional** | Windows 10 ou Windows 11 (64-bit) |
| **Software GIS** | ArcGIS Desktop 10.8 ou 10.8.2 (ArcMap) |
| **Python do ArcGIS** | Python 2.7 (32-bit, padrão do ArcMap em `C:\Python27\ArcGIS10.8`) |
| **Python do Backend** | Python 3.9, 3.10, 3.11 ou 3.12 (Python oficial, Anaconda, Miniconda ou QGIS 3.x) |
| **Biblioteca GEE** | `earthengine-api` (instalada automaticamente pelo script `install.bat`) |
| **Conta de Acesso** | Conta no Google Earth Engine com Google Cloud Project ID ativo |

---

## ⚡ Instalação Rápida em 1 Clique

O repositório disponibiliza um script automatizado que prepara o ambiente completo do Windows:

1. **Baixar o repositório:**
   ```bash
   git clone https://github.com/Yiuky/arcgis-google-earth-engine-explorer.git
   ```
   *(Ou [baixe o arquivo ZIP](https://github.com/Yiuky/arcgis-google-earth-engine-explorer/archive/refs/heads/main.zip) e extraia em qualquer pasta, ex: `C:\ArcGEE_Explorer`)*.
2. Certifique-se de que o **ArcMap esteja fechado**.
3. Dê um duplo clique no arquivo **`install.bat`**.
   * O script detectará o ArcGIS 10.8, localizará o interpretador Python 3 da máquina, instalará a biblioteca `earthengine-api`, compilará o Add-In `.esriaddin` e limpará o cache do sistema.
4. **Autenticar no Earth Engine (apenas na 1ª vez):**
   * Dê um duplo clique em **`autenticar_gee.bat`**.
   * O navegador abrirá a página de autorização do Google. Conceda o acesso para salvar as credenciais permanentes.

> [!TIP]
> Para obter instruções detalhadas de configuração de contas Google Cloud, instalação manual ou ambientes corporativos restritos, consulte o [📖 Manual de Instalação e Uso](MANUAL_DE_USO_E_INSTALACAO.md).

---

## 🚀 Como Utilizar no ArcMap

1. Abra o **ArcMap 10.8** ou **10.8.2**.
2. No menu **Customize** > **Toolbars**, ative **`CGMA ArcGEE Explorer`**.
3. Clique no botão **`🛰️ ArcGEE Explorer`**.
4. Na barra superior da interface, clique em **`[ Configurar Projeto GEE ]`** e informe o seu Project ID do Google Cloud (ex: `ee-meuprojeto`).
5. **Configurar a busca:**
   * Escolha o **Satélite / Sensor** (ex: Sentinel-2 ou Landsat 8).
   * Escolha a **Composição RGB** ou selecione um **Índice Espectral (NDVI, NDWI, NBR)**.
   * Insira o período de datas no padrão brasileiro (`DD/MM/AAAA`) ou use os botões de atalho (`30d`, `60d`, `90d`).
   * Escolha a **Área de Estudo**:
     * *Extensão da Tela do ArcMap* (ajuste o zoom para escala <= 1:250.000).
     * *Camada Vetorial (AOI)* (selecione um Shapefile de interesse aberto no mapa).
6. Clique em **`[ Buscar Imagens no GEE ]`**.
7. Selecione a cena desejada na tabela e clique em **`[ Gerar Miniatura ]`** para inspecionar a nebulosidade.
8. Clique em **`[ Carregar no ArcMap ]`** para baixar e visualizar a imagem na resolução nativa com realce radiométrico automático.

---

## 🗂️ Estrutura do Repositório

```text
arcgis-google-earth-engine-explorer/
├── arcgis_addin/
│   ├── config.xml                      # Metadados do Add-In (versão, toolbar, comandos)
│   ├── makeaddin.py                    # Script de empacotamento do .esriaddin
│   ├── GEE_Image_Selector.esriaddin    # Pacote compilado instalável no ArcMap
│   ├── Images/                         # Ícones e identidade visual da Toolbar
│   └── Install/
│       ├── gee_selector_addin.py       # Ponto de entrada COM do ArcMap
│       ├── gee_gui.py                  # Interface gráfica desacoplada (Tkinter/ttk)
│       ├── gee_bridge.py               # Ponte IPC, controle de TOC e ArcPy
│       ├── empty_group_template.lyr    # Template de GroupLayer puro
│       └── backend/                    # Backend autocontido no pacote
├── backend/
│   ├── gee_core.py                     # Motor principal do GEE, coleções e GeoTIFF
│   ├── run_gee.py                      # Linha de comando para comunicação JSON
│   └── gee_config.json                 # Configuração persistente do projeto GEE
├── pyt/
│   └── GEE_Tools.pyt                   # Caixa de ferramentas Python para o ArcToolbox
├── docs/                               # Documentação técnica e manuais ilustrados
│   ├── images/                         # Capturas de tela e logotipos em alta definição
│   └── MANUAL_DE_USO_E_INSTALACAO.md   # Cópia documental do manual de operação
├── install.bat                         # Instalador automatizado para Windows (1 clique)
├── desinstalar.bat                     # Desinstalador automático e limpeza de cache
├── atualizar.bat                       # Atualizador direto via GitHub ou ZIP
├── autenticar_gee.bat                  # Utilitário de autenticação OAuth2 GEE
├── requirements.txt                    # Dependências do Python 3
├── CHANGELOG.md                        # Histórico detalhado de versões e alterações
├── MANUAL_DE_USO_E_INSTALACAO.md       # Manual completo de instalação e operação
├── LICENSE                             # Licença de código aberto MIT
└── README.md                           # Documentação principal do repositório
```

---

## 🔄 Como Atualizar ou Desinstalar

* **Atualização Direta:** Abra a interface do ArcGEE Explorer > clique em **Configurações (⚙)** > clique em **`[ 🔄 Abrir Assistente de Atualização (GitHub / ZIP) ]`**.
* **Atualização via Script:** Feche o ArcMap e execute **`atualizar.bat`**.
* **Desinstalação Completa:** Feche o ArcMap e execute **`desinstalar.bat`** para remover o Add-In e limpar todos os registros do `AssemblyCache`.

---

## ❓ Perguntas Frequentes (FAQ)

<details>
<summary><strong>1. Por que a resolução nativa de 10m/30m é estritamente garantida?</strong></summary>

Em fiscalizações ambientais e perícias cartográficas, a acurácia geométrica e radiométrica é fundamental. Ao contrário de ferramentas que reamostram silenciosamente o pixel para 60m ou 120m quando a área de tela é grande, o ArcGEE Explorer impede a perda de qualidade e orienta o operador a aproximar o zoom ou selecionar uma camada vetorial de recorte.
</details>

<details>
<summary><strong>2. O que fazer se a janela não abrir após clicar no botão do ArcMap?</strong></summary>

Geralmente indica falta da biblioteca `earthengine-api` no Python 3 ou arquivos de cache `.pyc` antigos do ArcGIS 10.8. Execute o arquivo `install.bat` na pasta do plugin para reconstruir o ambiente de execução e purgar o cache do `AssemblyCache`.
</details>

<details>
<summary><strong>3. É possível usar o plugin fora do estado de Mato Grosso?</strong></summary>

**Sim, perfeitamente!** Desde a versão 1.3.0, o filtro territorial de Mato Grosso foi tornado opcional e a ferramenta opera em escala global para qualquer localidade do planeta.
</details>

<details>
<summary><strong>4. Como personalizar as bandas de um GeoTIFF já carregado no ArcMap?</strong></summary>

Quando descarregado no modo *Multibanda Bruta*, o arquivo contém todas as bandas espectrais nativas. Clique com o botão direito na camada no TOC > **Properties** > aba **Symbology** e selecione livremente quais canais deseja atribuir ao Vermelho, Verde e Azul.
</details>

---

## 🌐 English Abstract

**CGMA ArcGEE Explorer** is a high-performance Python Add-In designed for **ArcGIS Desktop 10.8 and 10.8.2 (ArcMap)**, providing seamless, two-way integration with the **Google Earth Engine (GEE)** cloud computing platform.

### Key Highlights:
- **Strict 100% Native Resolution Guarantee:** Prevents silent downsampling, strictly preserving 10m Sentinel-2 and 30m Landsat pixel sizes.
- **Asynchronous Decoupled Architecture:** Runs GUI and GEE processing on isolated processes via atomic JSON IPC, ensuring ArcMap never freezes or locks up.
- **Full Historical & Contemporary Sensor Catalog:** Dynamically displays operational timelines for Sentinel-2 MSI, Landsat 9/8 OLI, Landsat 7 ETM+, Landsat 4-5 TM, and Landsat 1-5 MSS.
- **Spectral Indices & Custom Band Math:** Computes NDVI, NDWI, NDMI, NBR, EVI, SAVI, and arbitrary user-defined math formulas directly in GEE, exporting 32-bit floating-point rasters with automatic symbology.
- **Raw Multiband GeoTIFF Downloads:** Downloads all native bands in a single GeoTIFF file, enabling on-the-fly RGB band adjustments directly within ArcMap's TOC.
- **Built-in Auto-Updater:** Checks for new GitHub releases on launch and offers 1-click updates via GitHub or local ZIP archives.

---

## 🔍 Tópicos e Tags de Busca (GitHub / Google SEO)

`arcgis-google-earth-engine` • `arcgis-gee-plugin` • `arcmap-earth-engine` • `arcgis-desktop-gee` • `google-earth-engine-explorer` • `arcgee-explorer` • `sentinel-2-arcgis` • `landsat-arcgis-download` • `remote-sensing-arcgis` • `geoprocessamento-arcgis-gee` • `sema-mt-cgma` • `arcgis-addin-gee` • `esri-google-earth-engine` • `python-arcpy-gee` • `google-earth-engine-arcmap-addin` • `satellite-imagery-downloader` • `gis-remote-sensing`

---

## 👤 Autor e Licença

* **Desenvolvedor:** Joberth Firmino Gambati
* **GitHub:** [@Yiuky](https://github.com/Yiuky)
* **Organização:** Coordenadoria de Geoprocessamento e Monitoramento Ambiental (CGMA)  
  *Secretaria de Estado de Meio Ambiente de Mato Grosso (SEMA-MT)*
* **Licença:** Código aberto sob a licença [MIT](LICENSE).
