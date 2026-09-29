# -*- coding: utf-8 -*-
"""
ArcMagery - Simbologia garantida de rasters (Python 2.7 + ArcObjects via comtypes).

Objetivo: toda imagem entra no ArcMap EXATAMENTE como pedido e configurado:
  * multibanda (>= 3 bandas) -> RGB Composite com as bandas escolhidas (R, G, B);
  * uma banda (indices, pancromatica) -> Stretched (rampa de cinza);
  * Stretch das Configuracoes: tipo (Standard Deviations, Percent Clip, Minimum-Maximum, ...),
    n de desvios padrao e origem das estatisticas (DRA = From Current Display Extent).

Diferente da versao anterior, que "tentava aplicar":
  1. o renderer e montado de uma vez (construct), gravado no .lyr e RELIDO do disco para
     conferir cada propriedade, inclusive o stretch (verify);
  2. a camada viva no mapa e localizada pelo CAMINHO EXATO do arquivo (IRasterLayer.FilePath),
     nunca por nome aproximado (que podia pegar outra camada de nome parecido);
  3. toda divergencia e informada ao chamador (nada de print silencioso).

Limitacao conhecida do ArcObjects 10.8: os percentuais do "Percent Clip" nao sao expostos por
camada (IRasterDRAShader nao e suportado pelos renderers); vale o padrao do ArcMap
(Customize > ArcMap Options > Raster > Raster Dataset).
"""
import os

try:
    unicode
except NameError:  # pragma: no cover - Python 3
    unicode = str

try:
    import arcmagery_vendor  # noqa: F401  (comtypes embutido como plano B do pip)
except ImportError:
    pass

_CARTO = None

STRETCH_NAMES = {
    'Standard Deviations': 'esriRasterStretch_StandardDeviations',
    'Standard Deviation': 'esriRasterStretch_StandardDeviations',
    'Percent Clip': 'esriRasterStretch_PercentMinimumMaximum',
    'Minimum-Maximum': 'esriRasterStretch_MinimumMaximum',
    'Histogram Equalize': 'esriRasterStretch_HistogramEqualize',
    'None': 'esriRasterStretch_NONE',
    'Esri': 'esriRasterStretch_ESRI',
    'Sigmoid': 'esriRasterStretch_Sigmoid',
}
STATS_NAMES = {
    'From Current Display Extent': 'esriRasterStretchStats_AreaOfView',
    'From Each Raster Dataset': 'esriRasterStretchStats_Dataset',
    'From Custom Settings': 'esriRasterStretchStats_GlobalStats',
}
DEFAULTS = {'stretch_type': 'Standard Deviations', 'stretch_std_param': 2.0,
            'statistics_type': 'From Current Display Extent'}


class SymbologyError(Exception):
    pass


def _err_text(e):
    try:
        import gee_bridge
        return gee_bridge.err_text(e)
    except ImportError:
        return unicode(e)


def carto():
    """Modulo esriCarto gerado pelo comtypes (cache por processo)."""
    global _CARTO
    if _CARTO is None:
        try:
            import comtypes.client
        except ImportError:
            raise SymbologyError(u"Módulo 'comtypes' ausente no Python do ArcGIS: a simbologia (bandas RGB e "
                                 u"stretch) não pode ser garantida. Execute o install.bat novamente.")
        import gee_bridge
        _CARTO = comtypes.client.GetModule(gee_bridge.get_esricarto_olb_path())
    return _CARTO


def _create(progid_attr, interface):
    import comtypes.client
    C = carto()
    return comtypes.client.CreateObject(getattr(C, progid_attr), interface=getattr(C, interface))


def _qi(obj, interface_name):
    try:
        return obj.QueryInterface(getattr(carto(), interface_name))
    except Exception:
        return None


def _long_path(path):
    """Expande nomes curtos 8.3 (C:\\Users\\USUARI~1\\...) para o caminho longo que o ArcGIS
    grava nas camadas: o %TEMP% costuma vir na forma curta e a comparacao falharia."""
    if os.name != 'nt':
        return path
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(32768)
        n = ctypes.windll.kernel32.GetLongPathNameW(unicode(path), buf, 32768)
        if 0 < n < 32768:
            return buf.value
    except Exception:
        pass
    return path


def normalize_path(path):
    if not path:
        return u''
    if not isinstance(path, unicode):
        try:
            path = path.decode('mbcs')
        except Exception:
            path = unicode(path, 'utf-8', 'replace')
    return os.path.normcase(os.path.normpath(_long_path(path)))


# ------------------------------------------------------------------------------ estado
def expected_state(settings, band_count, rgb_bands=None):
    """O que a camada DEVE ter, a partir das Configuracoes e das bandas pedidas."""
    C = carto()
    s = dict(DEFAULTS)
    s.update(dict((k, v) for k, v in (settings or {}).items() if v not in (None, '')))
    st_name = STRETCH_NAMES.get(s['stretch_type'], STRETCH_NAMES['Standard Deviations'])
    stats_name = STATS_NAMES.get(s['statistics_type'], STATS_NAMES['From Current Display Extent'])
    exp = {
        'renderer': 'RGB' if band_count >= 3 else 'STRETCH',
        'stretch_type': getattr(C, st_name),
        'stats_type': getattr(C, stats_name),
        'std_param': None,
        'bands': None,
    }
    if exp['stretch_type'] == C.esriRasterStretch_StandardDeviations:
        exp['std_param'] = round(float(s['stretch_std_param']), 3)
    if band_count >= 3:
        bands = tuple(int(b) for b in (rgb_bands or (0, 1, 2))[:3])
        if max(bands) >= band_count or min(bands) < 0:
            raise SymbologyError(u"Bandas RGB %r fora do raster de %d bandas." % (bands, band_count))
        exp['bands'] = bands
    return exp


def read_state(raster_layer):
    """Estado real da simbologia de um IRasterLayer (lido do objeto, sem suposicoes)."""
    r = raster_layer.Renderer
    state = {'renderer': None, 'stretch_type': None, 'stats_type': None, 'std_param': None, 'bands': None}
    if r is None:
        return state
    rgb = _qi(r, 'IRasterRGBRenderer')
    if rgb is not None:
        state['renderer'] = 'RGB'
        state['bands'] = (rgb.RedBandIndex, rgb.GreenBandIndex, rgb.BlueBandIndex)
    elif _qi(r, 'IRasterStretchColorRampRenderer') is not None:
        state['renderer'] = 'STRETCH'
    else:
        state['renderer'] = 'OTHER'
    st = _qi(r, 'IRasterStretch2')
    if st is not None:
        state['stretch_type'] = st.StretchType
        state['stats_type'] = st.StretchStatsType
        state['std_param'] = round(float(st.StandardDeviationsParam), 3)
    return state


def compare(state, exp):
    """Lista de divergencias (vazia = simbologia correta)."""
    diffs = []
    for key in ('renderer', 'stretch_type', 'stats_type', 'bands'):
        if exp.get(key) is not None and state.get(key) != exp[key]:
            diffs.append(u"%s: %r (esperado %r)" % (key, state.get(key), exp[key]))
    if exp.get('std_param') is not None and state.get('std_param') != exp['std_param']:
        diffs.append(u"std_param: %r (esperado %r)" % (state.get('std_param'), exp['std_param']))
    return diffs


# --------------------------------------------------------------------------- construcao
def configure_raster_layer(raster_layer, settings=None, rgb_bands=None):
    """Monta um renderer novo, completo, e o atribui ao IRasterLayer. Retorna o estado esperado."""
    band_count = int(raster_layer.BandCount)
    exp = expected_state(settings, band_count, rgb_bands)
    if exp['renderer'] == 'RGB':
        rend = _create('RasterRGBRenderer', 'IRasterRGBRenderer')
    else:
        # reaproveitar a rampa de cores existente (ex.: indices com rampa definida pelo usuario)
        current = raster_layer.Renderer
        rend = _qi(current, 'IRasterStretchColorRampRenderer') if current is not None else None
        if rend is None:
            rend = _create('RasterStretchColorRampRenderer', 'IRasterStretchColorRampRenderer')
    base = rend.QueryInterface(carto().IRasterRenderer)
    base.Raster = raster_layer.Raster
    base.Update()
    if exp['renderer'] == 'RGB':
        rend.RedBandIndex, rend.GreenBandIndex, rend.BlueBandIndex = exp['bands']
    else:
        rend.BandIndex = 0
    st = rend.QueryInterface(carto().IRasterStretch2)
    st.StretchType = exp['stretch_type']
    if exp['std_param'] is not None:
        st.StandardDeviationsParam = exp['std_param']
    st.StretchStatsType = exp['stats_type']
    base.Update()
    raster_layer.Renderer = base
    return exp


def apply_to_layer_file(lyr_path, settings=None, rgb_bands=None):
    """Configura o .lyr, salva e RELE do disco para confirmar. Levanta SymbologyError se divergir."""
    C = carto()
    lf = _create('LayerFile', 'ILayerFile')
    try:
        lf.Open(lyr_path)
        rl = lf.Layer.QueryInterface(C.IRasterLayer)
        exp = configure_raster_layer(rl, settings, rgb_bands)
        lf.Save()
    finally:
        try:
            lf.Close()
        except Exception:
            pass
    lf2 = _create('LayerFile', 'ILayerFile')
    try:
        lf2.Open(lyr_path)
        state = read_state(lf2.Layer.QueryInterface(C.IRasterLayer))
    finally:
        try:
            lf2.Close()
        except Exception:
            pass
    diffs = compare(state, exp)
    if diffs:
        raise SymbologyError(u"Simbologia gravada no .lyr diverge: " + u"; ".join(diffs))
    return state


# ------------------------------------------------------------------------ camada viva
def iter_raster_layers(focus_map):
    """(ILayer, IRasterLayer) de todas as camadas raster do mapa, inclusive dentro de grupos."""
    enum = focus_map.Layers(None, True)
    enum.Reset()
    lyr = enum.Next()
    while lyr:
        rl = _qi(lyr, 'IRasterLayer')
        if rl is not None:
            yield lyr, rl
        lyr = enum.Next()


def find_layers_by_path(tif_path, focus_map):
    """Camadas raster cujo arquivo e exatamente tif_path (comparacao normalizada)."""
    target = normalize_path(tif_path)
    found = []
    for lyr, rl in iter_raster_layers(focus_map):
        try:
            if normalize_path(rl.FilePath) == target:
                found.append((lyr, rl))
        except Exception:
            continue
    return found


_ARCMAP_MODULES = None


def arcmap_modules():
    """(esriFramework, esriArcMapUI) gerados pelo comtypes (cache por processo)."""
    global _ARCMAP_MODULES
    if _ARCMAP_MODULES is None:
        import comtypes.client
        import gee_bridge
        com_dir = os.path.dirname(gee_bridge.get_esricarto_olb_path())
        carto()  # garante o esriCarto gerado antes (dependencia do ArcMapUI)
        _ARCMAP_MODULES = (comtypes.client.GetModule(os.path.join(com_dir, 'esriFramework.olb')),
                           comtypes.client.GetModule(os.path.join(com_dir, 'esriArcMapUI.olb')))
    return _ARCMAP_MODULES


def live_focus_map():
    """(IMxDocument, FocusMap) do ArcMap em execucao (somente dentro do processo ArcMap).

    IApplication.Document devolve a interface generica IDocument; FocusMap, ActiveView e
    UpdateContents so existem em IMxDocument (esriArcMapUI) -> QueryInterface obrigatorio.
    (Sem isso: "Simbologia nao pode ser verificada: FocusMap".)"""
    import comtypes.client
    framework, arcmap_ui = arcmap_modules()
    app = comtypes.client.CreateObject(framework.AppRef, interface=framework.IApplication)
    mx_doc = app.Document.QueryInterface(arcmap_ui.IMxDocument)
    return mx_doc, mx_doc.FocusMap


def refresh_live_views(mx_doc):
    """Atualiza TOC e mapa do ArcMap depois de trocar um renderer."""
    for action in (lambda: mx_doc.UpdateContents(), lambda: mx_doc.ActiveView.Refresh()):
        try:
            action()
        except Exception:
            pass


def ensure_layer_symbology(tif_path, settings=None, rgb_bands=None, layer_name=None, focus_map=None, retries=2):
    """Garante (e confere) a simbologia da camada viva do arquivo tif_path.
    Se houver mais de uma camada do mesmo arquivo, usa as de nome layer_name (ou todas).
    Retorna (ok, mensagem, estados)."""
    mx_doc = None
    if focus_map is None:
        mx_doc, focus_map = live_focus_map()
    matches = find_layers_by_path(tif_path, focus_map)
    if layer_name:
        named = [(l, rl) for (l, rl) in matches if unicode(l.Name) == unicode(layer_name)]
        matches = named or matches
    if not matches:
        return False, u"Camada do arquivo '%s' não encontrada no mapa." % tif_path, []
    states, problems = [], []
    for lyr, rl in matches:
        exp = expected_state(settings, int(rl.BandCount), rgb_bands)
        diffs = compare(read_state(rl), exp)
        attempt = 0
        while diffs and attempt < retries:
            configure_raster_layer(rl, settings, rgb_bands)
            diffs = compare(read_state(rl), exp)
            attempt += 1
        states.append(read_state(rl))
        if diffs:
            problems.append(u"'%s': %s" % (lyr.Name, u"; ".join(diffs)))
    if mx_doc is not None:
        refresh_live_views(mx_doc)
    if problems:
        return False, u"Simbologia não pôde ser garantida: " + u" | ".join(problems), states
    return True, u"Simbologia conferida (%s)." % describe(states[0]), states


def restretch_layers(settings, focus_map=None, only_paths=None):
    """Reaplica o Stretch das Configuracoes a camadas raster do mapa PRESERVANDO as bandas RGB
    atuais de cada uma (a versao anterior redefinia as bandas para 1-2-3).
    only_paths: lista de arquivos a atualizar (None = todas as camadas raster).
    Retorna (atualizadas, [problemas])."""
    mx_doc = None
    if focus_map is None:
        mx_doc, focus_map = live_focus_map()
    wanted = set(normalize_path(p) for p in only_paths) if only_paths else None
    updated, problems = 0, []
    for lyr, rl in list(iter_raster_layers(focus_map)):
        try:
            if wanted is not None and normalize_path(rl.FilePath) not in wanted:
                continue
            current = read_state(rl)
            bands = current['bands'] if current.get('renderer') == 'RGB' else None
            exp = configure_raster_layer(rl, settings, bands)
            diffs = compare(read_state(rl), exp)
            if diffs:
                problems.append(u"'%s': %s" % (lyr.Name, u"; ".join(diffs)))
            else:
                updated += 1
        except Exception as e:
            problems.append(u"'%s': %s" % (getattr(lyr, 'Name', '?'), _err_text(e)))
    if mx_doc is not None:
        refresh_live_views(mx_doc)
    return updated, problems


# ------------------------------------------------------------ poligonos de datas de captura
_DISPLAY = None


def display():
    global _DISPLAY
    if _DISPLAY is None:
        import comtypes.client
        import gee_bridge
        carto()
        _DISPLAY = comtypes.client.GetModule(
            os.path.join(os.path.dirname(gee_bridge.get_esricarto_olb_path()), 'esriDisplay.olb'))
    return _DISPLAY


def style_footprints_layer_file(lyr_path, rgb=(255, 255, 0), width=1.5):
    """Poligonos das datas de captura: contorno colorido SEM preenchimento (nao cobre a imagem).
    Grava no .lyr e rele para conferir. Retorna True."""
    import comtypes.client
    C, D = carto(), display()
    color = comtypes.client.CreateObject(D.RgbColor, interface=D.IRgbColor)
    color.Red, color.Green, color.Blue = rgb
    line = comtypes.client.CreateObject(D.SimpleLineSymbol, interface=D.ISimpleLineSymbol)
    line.Color = color
    line.Width = float(width)
    fill = comtypes.client.CreateObject(D.SimpleFillSymbol, interface=D.ISimpleFillSymbol)
    fill.Style = D.esriSFSHollow
    fill.Outline = line
    rend = comtypes.client.CreateObject(C.SimpleRenderer, interface=C.ISimpleRenderer)
    rend.Symbol = fill.QueryInterface(D.ISymbol)
    lf = _create('LayerFile', 'ILayerFile')
    try:
        lf.Open(lyr_path)
        lf.Layer.QueryInterface(C.IGeoFeatureLayer).Renderer = rend.QueryInterface(C.IFeatureRenderer)
        lf.Save()
    finally:
        try:
            lf.Close()
        except Exception:
            pass
    if footprints_style(lyr_path) != 'HOLLOW':
        raise SymbologyError(u"Estilo dos polígonos de datas não foi gravado no .lyr.")
    return True


def footprints_style(lyr_path):
    """'HOLLOW' se o .lyr tem SimpleRenderer com preenchimento vazado (usado nos testes)."""
    C, D = carto(), display()
    lf = _create('LayerFile', 'ILayerFile')
    try:
        lf.Open(lyr_path)
        rend = lf.Layer.QueryInterface(C.IGeoFeatureLayer).Renderer
        simple = rend.QueryInterface(C.ISimpleRenderer)
        fill = simple.Symbol.QueryInterface(D.ISimpleFillSymbol)
        return 'HOLLOW' if fill.Style == D.esriSFSHollow else 'FILLED'
    finally:
        try:
            lf.Close()
        except Exception:
            pass


def describe(state):
    C = carto()
    names = dict((getattr(C, v), k) for k, v in STRETCH_NAMES.items() if k != 'Standard Deviation')
    stats = dict((getattr(C, v), k) for k, v in STATS_NAMES.items())
    txt = u"RGB %s" % (tuple(b + 1 for b in state['bands']),) if state.get('renderer') == 'RGB' else u"1 banda"
    txt += u", stretch %s" % names.get(state.get('stretch_type'), state.get('stretch_type'))
    if state.get('std_param') and state.get('stretch_type') == C.esriRasterStretch_StandardDeviations:
        txt += u" n=%s" % state['std_param']
    return txt + u", estatísticas %s" % stats.get(state.get('stats_type'), state.get('stats_type'))
