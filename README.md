<p align="center">
  <img src="docs/images/logo.png" alt="ArcMagery" width="170" />
</p>

<h1 align="center">ArcMagery</h1>

<p align="center">
  <strong>Imagens de satélite no ArcGIS Desktop (ArcMap 10.8 / 10.8.2)</strong><br>
  <em>Google Earth Engine · Google Earth e mosaicos XYZ · CBERS-4/4A e Amazônia-1 (INPE)</em>
</p>

<p align="center">
  <a href="https://www.esri.com/"><img src="https://img.shields.io/badge/ArcGIS%20Desktop-10.8%20%7C%2010.8.2-0079C1.svg?logo=esri&logoColor=white" alt="ArcGIS Desktop"></a>
  <a href="https://earthengine.google.com/"><img src="https://img.shields.io/badge/Google%20Earth%20Engine-API-4285F4.svg?logo=googleearthengine&logoColor=white" alt="Google Earth Engine"></a>
  <a href="https://data.inpe.br/stac/browser/"><img src="https://img.shields.io/badge/INPE-STAC%20CBERS-00843D.svg" alt="STAC INPE"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-2.7%20%7C%203.10+-3776AB.svg?logo=python&logoColor=white" alt="Python"></a>
  <a href="CHANGELOG.md"><img src="https://img.shields.io/badge/Versão-v2.3.3-28A745.svg" alt="Versão v2.3.3"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License MIT"></a>
  <a href="https://github.com/Yiuky/arcgis-google-earth-engine-explorer/actions/workflows/tests.yml"><img src="https://github.com/Yiuky/arcgis-google-earth-engine-explorer/actions/workflows/tests.yml/badge.svg" alt="Testes"></a>
</p>

<p align="center">
  <a href="docs/MANUAL_DE_USO_E_INSTALACAO.md"><strong>📖 Manual</strong></a> •
  <a href="CHANGELOG.md"><strong>📋 Changelog</strong></a> •
  <a href="BACKLOG.md"><strong>🗂️ Backlog</strong></a> •
  <a href="AGENTS.md"><strong>🤖 Guia para desenvolvedores / IA</strong></a> •
  <a href="#-english-abstract"><strong>🌐 English</strong></a>
</p>

---

<p align="center">
  <img src="docs/images/interface_arcmap.png" alt="ArcMagery no ArcMap" width="94%" />
</p>

> **ArcMagery** é o novo nome do *CGMA ArcGEE Explorer* a partir da v2.0.0. Instalações
> anteriores são atualizadas normalmente (mesmo identificador de Add-In).

## 📌 O que faz

O ArcMagery é um Python Add-In para o **ArcMap 10.8/10.8.2**. Ele busca, recorta e carrega
imagens de satélite direto no TOC, na **resolução nativa**, sem sair do ArcMap e sem downloads
manuais. Foi desenvolvido na Coordenadoria de Geoprocessamento e Monitoramento Ambiental
(**CGMA / SEMA-MT**) para fiscalização ambiental, sensoriamento remoto e perícias.

### Fontes de imagens

| Fonte | O que oferece | Resolução |
|---|---|---|
| **Google Earth Engine** | Sentinel-2, Landsat 1–9: cenas, mosaicos por mediana com máscara de nuvem, índices (NDVI, NDWI, NDMI, NBR, EVI, SAVI), matemática de bandas e multibanda completa | 10–60 m |
| **Google Earth / XYZ** *(novo)* | Google Satélite, Google Híbrido, Esri World Imagery, Esri Clarity e Bing Aerial, costurados num GeoTIFF georreferenciado. Com a Esri: **data de captura** e **histórico Wayback** desde 2014 | até ~0,15 m (zoom 20) |
| **Google Earth histórico** *(novo)* | Datas do histórico do Google Earth (como no Google Earth Pro), com provedor e cobertura da área; baixa a imagem de uma ou várias datas na grade nativa EPSG:4326, até 100 mil tiles | ~0,15–4,8 m (zoom 20–15) |
| **Esri Wayback** *(novo)* | Versões históricas da Esri World Imagery desde 2014, com a **data de captura**, o satélite e a resolução de cada uma; todos os zooms numa busca | ~0,3–4,6 m (zoom 19–15) |
| **CBERS / Amazônia-1** *(novo)* | STAC do INPE, 32 coleções: CBERS-4A WPM (2 m pan e 8 m multiespectral, fusionada 2 m), MUX, WFI, PAN 5/10 m e Amazônia-1 WFI (Níveis 4 e 2); cubos sem nuvens com NDVI/EVI; histórico CBERS-2/2B (2003–2010, HRC 2,5 m); mosaicos | 2–260 m |

### Destaques
- **Qualidade nativa:** GEE sem reamostragem involuntária. CBERS recortado na grade original da
  cena por leitura parcial HTTP, transferindo só a área de interesse. XYZ recortado exatamente à
  área em Web Mercator.
- **Áreas extensas:** particionamento automático (GEE > 48 MB e mosaicos XYZ com milhares de
  tiles), com cache e retomada após falhas.
- **Área de interesse:** extensão atual do mapa ou camada vetorial (AOI) do TOC. No CBERS, cada
  cena mostra quanto da AOI ela **realmente** cobre.
- **Estável:** a interface roda em processo próprio, e o ArcMap nunca congela.
- **Atualização segura:** pela GitHub Release, com verificação SHA-256, ou por arquivo ZIP, com
  backup e rollback.

---

## 🏗️ Arquitetura

```text
ArcMap 10.8 (Python 2.7)  ── JSON por sessão (%TEMP%) ──  Interface Tk (pythonw, Python 2.7)
   Add-In, arcpy, TOC                                        │ subprocess --params-file (UTF-8)
                                                             ▼
                                   Backend Python 3 (venv %LOCALAPPDATA%\ArcMagery\venv)
                                   gee_core (Earth Engine) · xyz_core (XYZ) · stac_core (INPE + GDAL)
```

Detalhes técnicos, convenções e armadilhas conhecidas estão em [AGENTS.md](AGENTS.md).

## 💻 Requisitos

| Item | Versão |
|---|---|
| Windows | 10 ou 11 (64-bit) |
| ArcGIS Desktop | 10.8 / 10.8.2 (ArcMap, Python 2.7 em `C:\Python27\ArcGIS10.8`) |
| Python 3 do backend | **QGIS 3.x (recomendado: traz o GDAL, necessário ao CBERS)** ou Python 3.10+ |
| Google Earth Engine | Conta com Project ID do Google Cloud (só para a fonte GEE) |

## ⚡ Instalação

1. Baixe o pacote da [última Release](https://github.com/Yiuky/arcgis-google-earth-engine-explorer/releases/latest) e extraia (ex.: `C:\ArcMagery`).
2. Feche o ArcMap e execute **`install.bat`**. O instalador:
   - cria um ambiente Python 3 isolado em `%LOCALAPPDATA%\ArcMagery\venv`, sobre o Python do
     QGIS, sem alterar o QGIS nem outros projetos;
   - instala o `earthengine-api` e as dependências;
   - empacota e registra o Add-In.
3. Só para o GEE, uma única vez: execute **`autenticar_gee.bat`**.
4. No ArcMap: **Customize › Toolbars › ArcMagery** e clique no botão **ArcMagery**.

## 🚀 Uso rápido

- **Google Earth Engine:** configure o Project ID (**Configurar Projeto GEE**), escolha o
  sensor, a composição, o período e a área, e clique em **Buscar Imagens no GEE**. Depois
  selecione a cena e clique em **Carregar no ArcMap**.
- **Google Earth / XYZ:** barra **Fonte de imagens** › **Google Earth / Mosaicos XYZ...**.
  Escolha a fonte e o zoom (a estimativa de tiles e m/pixel aparece na hora) e clique em
  **Baixar mosaico e carregar no ArcMap**.
- **CBERS / Amazônia-1:** na janela principal, barra **Fonte de imagens** › *CBERS / Amazônia-1
  (INPE)*. O fluxo é o mesmo do GEE: escolha a coleção (satélite), o produto (composição), o
  período e a área, e clique em **Buscar Cenas no INPE**. Confira a *Cobertura da AOI %* e a
  **Miniatura**, e use **Carregar no ArcMap**. Não exige login no GEE.
- **Google Earth histórico:** barra **Fonte de imagens** › *Google Earth histórico (por data)*. Escolha o
  zoom (no lugar do satélite), o período e a área, e clique em **Listar Datas do Google Earth**. A tabela
  mostra cada data com a cobertura e o provedor. Veja a **Miniatura** e use **Carregar no ArcMap** (uma ou
  várias datas, com fila). Não exige login no GEE. Com *TODOS os zooms* (padrão), cada data aparece em cada zoom
  disponível, com a cobertura daquele zoom na coluna **Zoom** (`~` = estimada por amostragem).
- **Esri Wayback:** barra **Fonte de imagens** › *Esri Wayback (por versão)* › **Listar Versões do Esri Wayback**.
  Cada linha é uma versão com imagem diferente na área, com a data de captura. A consulta depende dos servidores
  de metadados da Esri (15 s a 3 min) e fica em cache.
- **Desempenho:** *Configurações › Processamento & Sistema* define os núcleos (padrão: CPU − 2) e as **threads de
  download de tiles** (padrão 48, até 64).

> ⚠️ **Termos de Uso:** o download em massa de tiles do **Google** e do **Bing** fora das APIs
> oficiais viola os Termos de Serviço desses provedores. O ArcMagery exibe um aviso antes do
> primeiro uso. Para trabalho institucional, prefira a **Esri World Imagery** (com atribuição)
> ou o **CBERS/INPE** (dados públicos).

## 🧪 Testes

```bat
run_tests.bat                    :: backend (Python 3) + ArcMap/GUI (Python 2.7)
set ARCMAGERY_LIVE=1             :: inclui testes com internet (INPE, Esri, Google)
set ARCMAGERY_GEE_PROJECT=<id>   :: inclui teste real no Earth Engine
```

## 🔄 Atualizar e desinstalar

- **Pelo plugin:** ⚙ Configurações › Assistente de Atualização (Release do GitHub verificada por
  SHA-256, ou arquivo ZIP).
- **Por script:** feche o ArcMap e execute `atualizar.bat`. Numa pasta clonada com git, ele atualiza só por
  avanço rápido (sem merge e sem sobrescrever alterações locais) e reinstala. Numa pasta baixada como ZIP,
  ele indica a Release verificada.
- **Desinstalar:** feche o ArcMap e execute `desinstalar.bat`.

## 📦 Publicar uma versão (mantenedor)

Com a versão atualizada em `config.xml`, `gee_gui.py` e `gee_updater.py`, e com a entrada no `CHANGELOG.md`:

```bat
git tag v2.3.3
git push origin v2.3.3
```

O workflow **Release** do GitHub Actions gera `ArcMagery-<versão>.zip` e `SHA256SUMS.txt` e publica a Release,
com as notas daquela versão do CHANGELOG. O atualizador embutido só instala sem confirmação Releases
com `SHA256SUMS.txt`.

## 🤝 Contribuindo

- Leia o [AGENTS.md](AGENTS.md): arquitetura, regras de Python 2.7 × 3 e armadilhas conhecidas.
- Trabalho pendente e prioridades: [BACKLOG.md](BACKLOG.md).
- Problemas e sugestões: abra uma *issue* pelos modelos do repositório. Para um bug, anexe o
  `arcgee_debug.log` da sessão (`%LOCALAPPDATA%\Temp\arcXXXX\`).
- Antes do PR, rode o `run_tests.bat`. O GitHub Actions roda a suíte do backend a cada push; a suíte
  do ArcMap exige ArcGIS Desktop e roda localmente.

---

## 🌐 English Abstract

**ArcMagery** (formerly *CGMA ArcGEE Explorer*) is a Python Add-In for **ArcGIS Desktop 10.8 /
10.8.2 (ArcMap)** that searches, clips and loads satellite imagery straight into the table of
contents, at native resolution:

- **Google Earth Engine:** Sentinel-2 and Landsat 1–9 scenes, cloud-masked median mosaics,
  spectral indices, band math and full multiband exports.
- **Google Earth / XYZ basemaps:** Google Satellite, Esri World Imagery and Bing, stitched into a
  georeferenced GeoTIFF with resumable parallel downloads.
- **CBERS-4/4A and Amazonia-1:** from INPE's STAC catalog, clipped on the native pixel grid via
  HTTP range reads. Each scene reports its true AOI coverage.
- **Architecture:** decoupled processes (ArcMap never freezes). Signed-hash (SHA-256) GitHub
  Release updater and automated test suites for Python 2.7 and 3.

## 🔍 Tópicos

`arcgis` • `arcmap` • `arcgis-addin` • `google-earth-engine` • `google-earth` • `cbers` • `amazonia-1` • `inpe` • `stac` • `sentinel-2` • `landsat` • `satellite-imagery-downloader` • `remote-sensing` • `sema-mt-cgma`

## 👤 Autor e licença

- **Desenvolvedor:** Joberth Firmino Gambati ([@Yiuky](https://github.com/Yiuky))
- **Organização:** CGMA, Secretaria de Estado de Meio Ambiente de Mato Grosso (SEMA-MT)
- **Licença:** [MIT](LICENSE)
- Imagens: © Google, © Esri e parceiros, © Microsoft, CBERS/Amazônia-1 © INPE, e os provedores
  do Google Earth Engine. Respeite as licenças de cada fonte.
