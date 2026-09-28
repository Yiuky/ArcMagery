# -*- coding: utf-8 -*-
"""
ArcMagery - Janela de fontes adicionais (Python 2.7 / Tkinter, processo da GUI).

  * Google Earth / Satelite e outros mosaicos XYZ (Esri, Bing)  -> backend xyz_core
  * CBERS-4/4A e Amazonia-1 (STAC do INPE)                        -> backend stac_core

Regras de threading: todo acesso a widgets acontece na thread do Tk. Os workers leem os
parametros ANTES de iniciar (via _collect_*) e devolvem resultados com parent.post_to_gui.
As funcoes de nivel de modulo sao puras (sem Tk) e cobertas por testes em Python 2.7.
"""
from __future__ import division

import datetime
import json
import os
import re
import sys
import threading
import time

if sys.version_info[0] < 3:
    import Tkinter as tk
    import ttk
    import tkMessageBox as messagebox
    import tkFileDialog as filedialog
    text_type = unicode  # noqa: F821
else:
    import tkinter as tk
    from tkinter import ttk
    from tkinter import messagebox
    from tkinter import filedialog
    text_type = str

import gee_bridge
from backend import tilemath

XYZ_GROUP = u"ArcMagery - Google Earth / XYZ"
CBERS_GROUP = u"ArcMagery - CBERS / Amazônia-1"

# Espelho leve dos catalogos do backend (a lista completa e confirmada via 'sources_info').
XYZ_PROVIDERS = [
    ('google', u'Google Earth / Satélite', 21, True),
    ('google-hybrid', u'Google Híbrido (satélite + rótulos)', 21, True),
    ('esri', u'Esri World Imagery', 19, False),
    ('esri-clarity', u'Esri World Imagery (Clarity)', 19, False),
    ('bing', u'Bing Aerial', 19, True),
]

CBERS_COLLECTIONS = [
    ('CB4A-WPM-L4-DN-1', u'CBERS-4A WPM - 8 m multiespectral + 2 m pancromática'),
    ('CB4A-WPM-PCA-FUSED-1', u'CBERS-4A WPM - 2 m fusionada RGB (PCA)'),
    ('CB4A-MUX-L4-DN-1', u'CBERS-4A MUX - 16 m'),
    ('CB4A-MUX-L4-SR-1', u'CBERS-4A MUX - 16 m reflectância de superfície'),
    ('CB4A-WFI-L4-SR-1', u'CBERS-4A WFI - 55 m reflectância de superfície'),
    ('CB4-MUX-L4-SR-1', u'CBERS-4 MUX - 20 m reflectância de superfície'),
    ('CB4-MUX-L4-DN-1', u'CBERS-4 MUX - 20 m'),
    ('CB4-WFI-L4-SR-1', u'CBERS-4 WFI - 64 m reflectância de superfície'),
    ('CB4-PAN10M-L4-DN-1', u'CBERS-4 PAN - 10 m (verde, vermelho, NIR)'),
    ('CB4-PAN5M-L4-DN-1', u'CBERS-4 PAN - 5 m pancromática'),
    ('AMZ1-WFI-L4-SR-1', u'Amazônia-1 WFI - 64 m reflectância de superfície'),
    ('AMZ1-WFI-L4-DN-1', u'Amazônia-1 WFI - 64 m'),
]

# Modos por colecao (mesma regra de stac_core.available_modes)
_MODE_LABELS = [
    ('rgb', u'Cor natural (R-G-B)'),
    ('false', u'Falsa cor (NIR-R-G)'),
    ('multi', u'Multibanda (todas as bandas)'),
    ('pan', u'Pancromática'),
    ('fused', u'Fusionada RGB'),
]
_COLLECTION_MODES = {
    'CB4A-WPM-L4-DN-1': ['rgb', 'false', 'multi', 'pan'],
    'CB4A-WPM-PCA-FUSED-1': ['fused'],
    'CB4-PAN10M-L4-DN-1': ['false', 'multi'],
    'CB4-PAN5M-L4-DN-1': ['pan'],
}

TOS_TEXT = (u"ATENÇÃO - Termos de Uso\n\n"
            u"O download em massa de tiles do Google e do Bing fora das APIs oficiais viola os Termos "
            u"de Serviço desses provedores. Use apenas quando houver respaldo (licença/autorização) e "
            u"cite a fonte. Para uso institucional, prefira a Esri World Imagery ou o CBERS (dados "
            u"públicos do INPE).\n\nDeseja continuar com o download?")


# ------------------------------------------------------------------------ funcoes puras
def modes_for_collection(collection_id):
    return _COLLECTION_MODES.get(collection_id, ['rgb', 'false', 'multi'])


def mode_label(mode):
    return dict(_MODE_LABELS).get(mode, mode)


def parse_br_date(text):
    """'DD/MM/AAAA' -> date. Levanta ValueError com mensagem amigavel."""
    s = (text or u'').strip()
    try:
        return datetime.datetime.strptime(s, '%d/%m/%Y').date()
    except ValueError:
        raise ValueError(u"Data inválida: '%s' (use DD/MM/AAAA)" % s)


def validate_date_range(start_text, end_text):
    d0, d1 = parse_br_date(start_text), parse_br_date(end_text)
    if d0 > d1:
        raise ValueError(u"A data inicial é posterior à data final.")
    return d0, d1


def parse_progress(line):
    """'[ArcGEE] PROGRESS 12/40 tiles' -> (12, 40); qualquer outra linha -> None."""
    m = re.search(r'PROGRESS\s+(\d+)\s*/\s*(\d+)', line or '')
    if not m:
        return None
    done, total = int(m.group(1)), int(m.group(2))
    return (done, total) if total > 0 else None


def bbox_from_geojson_data(gj):
    xs, ys = [], []

    def walk(c):
        if isinstance(c, (list, tuple)) and c and isinstance(c[0], (int, float)):
            xs.append(float(c[0]))
            ys.append(float(c[1]))
        elif isinstance(c, (list, tuple)):
            for sub in c:
                walk(sub)

    feats = gj.get('features') if gj.get('type') == 'FeatureCollection' else [gj]
    for ft in feats or []:
        geom = ft.get('geometry', ft) if isinstance(ft, dict) else None
        if geom:
            walk(geom.get('coordinates', []))
    if not xs:
        raise ValueError(u"GeoJSON da AOI sem coordenadas.")
    return [min(xs), min(ys), max(xs), max(ys)]


def format_estimate(est):
    return (u"%d tiles (%d x %d)  |  %d x %d px  |  ~%.2f m/pixel  |  download ~%.0f MB"
            % (est['tiles'], est['cols'], est['rows'], est['width'], est['height'],
               est['ground_res_m'], est['download_mb']))


def safe_filename(text):
    s = re.sub(r'[^A-Za-z0-9_.-]+', '_', text_type(text)).strip('_')
    return s[:120] or u'imagem'


def unique_path(folder, base, ext='.tif'):
    """Evita sobrescrever um arquivo possivelmente bloqueado pelo ArcMap."""
    path = os.path.join(folder, base + ext)
    if not os.path.exists(path):
        return path
    return os.path.join(folder, u"%s_%s%s" % (base, time.strftime('%Y%m%d_%H%M%S'), ext))


def default_output_dir():
    home = os.path.expanduser(u"~")
    if not isinstance(home, text_type):
        home = home.decode(sys.getfilesystemencoding() or 'mbcs')
    return os.path.join(home, u"Documents", u"ArcMagery")


def to_text(value):
    if isinstance(value, text_type):
        return value
    try:
        return value.decode('utf-8')
    except Exception:
        try:
            return text_type(value)
        except Exception:
            return repr(value)


# ------------------------------------------------------------------------------ janela
class ExtraSourcesDialog(object):
    def __init__(self, parent):
        self.parent = parent
        self.settings = parent.settings if hasattr(parent, 'settings') else {}
        self.top = tk.Toplevel(parent.root)
        self.top.title(u"ArcMagery - Google Earth e CBERS / INPE")
        self.top.geometry("900x640")
        self.top.minsize(820, 560)
        self.busy = {'xyz': False, 'cbers': False}
        self.cbers_items = {}
        self._thumb_img = None
        self._build()
        self._update_estimate()

    # ------------------------------------------------------------------ construcao
    def _build(self):
        area = ttk.LabelFrame(self.top, text=u" Área de interesse e saída ", padding=8)
        area.pack(fill=tk.X, padx=8, pady=6)

        self.var_area = tk.StringVar(value="extent")
        ttk.Radiobutton(area, text=u"Extensão atual do ArcMap", variable=self.var_area, value="extent",
                        command=self._update_estimate).grid(row=0, column=0, sticky=tk.W)
        ttk.Radiobutton(area, text=u"Camada vetorial (AOI):", variable=self.var_area, value="layer",
                        command=self._update_estimate).grid(row=0, column=1, sticky=tk.W, padx=(12, 4))
        self.cbo_layer = ttk.Combobox(area, state="readonly", width=34)
        vectors = (getattr(self.parent, 'arcmap_context', {}) or {}).get('vector_layers') or []
        self.cbo_layer['values'] = vectors or [u"Nenhuma camada encontrada"]
        self.cbo_layer.current(0)
        self.cbo_layer.grid(row=0, column=2, sticky=tk.W)

        ttk.Label(area, text=u"Pasta de saída:").grid(row=1, column=0, sticky=tk.W, pady=(6, 0))
        self.var_outdir = tk.StringVar(value=self.settings.get('arcmagery_output_dir') or default_output_dir())
        ttk.Entry(area, textvariable=self.var_outdir, width=70).grid(row=1, column=1, columnspan=2, sticky=tk.EW, pady=(6, 0))
        ttk.Button(area, text=u"...", width=3, command=self._pick_outdir).grid(row=1, column=3, padx=4, pady=(6, 0))
        area.columnconfigure(2, weight=1)

        nb = ttk.Notebook(self.top)
        nb.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        self._build_xyz_tab(nb)
        self._build_cbers_tab(nb)

    def _build_xyz_tab(self, nb):
        f = ttk.Frame(nb, padding=10)
        nb.add(f, text=u"  Google Earth / Mosaicos XYZ  ")

        ttk.Label(f, text=u"Fonte:", font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky=tk.W)
        self.cbo_provider = ttk.Combobox(f, state="readonly", width=40,
                                         values=[p[1] for p in XYZ_PROVIDERS])
        self.cbo_provider.current(0)
        self.cbo_provider.bind("<<ComboboxSelected>>", lambda e: self._update_estimate())
        self.cbo_provider.grid(row=0, column=1, sticky=tk.W, pady=2)

        ttk.Label(f, text=u"Zoom (nível de detalhe):", font=("Segoe UI", 9, "bold")).grid(row=1, column=0, sticky=tk.W)
        self.var_zoom = tk.StringVar(value=str(self.settings.get('arcmagery_xyz_zoom', 18)))
        sp = tk.Spinbox(f, from_=10, to=21, width=6, textvariable=self.var_zoom, command=self._update_estimate)
        sp.bind("<KeyRelease>", lambda e: self._update_estimate())
        sp.grid(row=1, column=1, sticky=tk.W, pady=2)

        ttk.Label(f, text=u"Compressão:").grid(row=2, column=0, sticky=tk.W)
        self.cbo_compress = ttk.Combobox(f, state="readonly", width=24,
                                         values=[u"JPEG (arquivo menor)", u"LZW (sem perdas)"])
        self.cbo_compress.current(0)
        self.cbo_compress.grid(row=2, column=1, sticky=tk.W, pady=2)

        self.var_reproject = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text=u"Reprojetar para SIRGAS 2000 (EPSG:4674) - por padrão mantém Web Mercator nativo",
                        variable=self.var_reproject).grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=4)

        self.lbl_estimate = tk.Label(f, text=u"", font=("Segoe UI", 9), fg="#1b4f72", justify=tk.LEFT)
        self.lbl_estimate.grid(row=4, column=0, columnspan=2, sticky=tk.W, pady=(8, 2))
        self.lbl_tos = tk.Label(f, text=u"", font=("Segoe UI", 8), fg="#922b21", justify=tk.LEFT, wraplength=820)
        self.lbl_tos.grid(row=5, column=0, columnspan=2, sticky=tk.W)

        self.btn_xyz = ttk.Button(f, text=u"Baixar mosaico e carregar no ArcMap", style="Primary.TButton",
                                  command=self.on_xyz_download)
        self.btn_xyz.grid(row=6, column=0, columnspan=2, sticky=tk.W, pady=(12, 4))
        self.prog_xyz = ttk.Progressbar(f, mode="determinate", length=600)
        self.prog_xyz.grid(row=7, column=0, columnspan=2, sticky=tk.EW, pady=2)
        self.lbl_xyz_status = tk.Label(f, text=u"Pronto.", font=("Segoe UI", 9), anchor=tk.W, justify=tk.LEFT)
        self.lbl_xyz_status.grid(row=8, column=0, columnspan=2, sticky=tk.W)
        f.columnconfigure(1, weight=1)

    def _build_cbers_tab(self, nb):
        f = ttk.Frame(nb, padding=10)
        nb.add(f, text=u"  CBERS / Amazônia-1 (INPE)  ")

        ttk.Label(f, text=u"Coleção:", font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky=tk.W)
        self.cbo_collection = ttk.Combobox(f, state="readonly", width=58, values=[c[1] for c in CBERS_COLLECTIONS])
        self.cbo_collection.current(0)
        self.cbo_collection.bind("<<ComboboxSelected>>", lambda e: self._refresh_modes())
        self.cbo_collection.grid(row=0, column=1, columnspan=4, sticky=tk.W, pady=2)

        today = datetime.date.today()
        ttk.Label(f, text=u"Período:").grid(row=1, column=0, sticky=tk.W)
        self.var_d0 = tk.StringVar(value=(today - datetime.timedelta(days=120)).strftime('%d/%m/%Y'))
        self.var_d1 = tk.StringVar(value=today.strftime('%d/%m/%Y'))
        ttk.Entry(f, textvariable=self.var_d0, width=12).grid(row=1, column=1, sticky=tk.W)
        ttk.Label(f, text=u"a").grid(row=1, column=2, padx=4)
        ttk.Entry(f, textvariable=self.var_d1, width=12).grid(row=1, column=3, sticky=tk.W)

        ttk.Label(f, text=u"Nuvens máx. (%):").grid(row=2, column=0, sticky=tk.W)
        self.var_cloud = tk.StringVar(value="100")
        tk.Spinbox(f, from_=0, to=100, increment=5, width=6, textvariable=self.var_cloud).grid(row=2, column=1, sticky=tk.W)
        ttk.Label(f, text=u"(cenas DN não informam nuvens)", foreground="#7b7d7d").grid(row=2, column=3, columnspan=2, sticky=tk.W)

        self.btn_search = ttk.Button(f, text=u"Buscar cenas", style="Action.TButton", command=self.on_cbers_search)
        self.btn_search.grid(row=3, column=0, sticky=tk.W, pady=6)
        self.lbl_cbers_status = tk.Label(f, text=u"Pronto.", font=("Segoe UI", 9), anchor=tk.W, justify=tk.LEFT)
        self.lbl_cbers_status.grid(row=3, column=1, columnspan=4, sticky=tk.W)

        cols = ("data", "colecao", "cena", "nuvem", "cobertura")
        self.tree = ttk.Treeview(f, columns=cols, show="headings", height=10, selectmode="extended")
        for c, t, w in (("data", u"Data", 90), ("colecao", u"Coleção", 170), ("cena", u"Cena", 320),
                        ("nuvem", u"Nuvens %", 80), ("cobertura", u"Cobertura da AOI %", 130)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor=tk.W if c in ("colecao", "cena") else tk.CENTER)
        self.tree.grid(row=4, column=0, columnspan=5, sticky=tk.NSEW)
        sb = ttk.Scrollbar(f, orient=tk.VERTICAL, command=self.tree.yview)
        sb.grid(row=4, column=5, sticky=tk.NS)
        self.tree.configure(yscrollcommand=sb.set)

        ttk.Label(f, text=u"Produto:").grid(row=5, column=0, sticky=tk.W, pady=(6, 0))
        self.cbo_mode = ttk.Combobox(f, state="readonly", width=32)
        self.cbo_mode.grid(row=5, column=1, columnspan=2, sticky=tk.W, pady=(6, 0))
        self.btn_thumb = ttk.Button(f, text=u"Miniatura", command=self.on_cbers_thumb)
        self.btn_thumb.grid(row=5, column=3, sticky=tk.W, pady=(6, 0))
        self.btn_cbers_dl = ttk.Button(f, text=u"Baixar recorte e carregar no ArcMap", style="Primary.TButton",
                                       command=self.on_cbers_download)
        self.btn_cbers_dl.grid(row=5, column=4, sticky=tk.E, pady=(6, 0))
        self.prog_cbers = ttk.Progressbar(f, mode="determinate", length=600)
        self.prog_cbers.grid(row=6, column=0, columnspan=5, sticky=tk.EW, pady=4)
        f.columnconfigure(4, weight=1)
        f.rowconfigure(4, weight=1)
        self._refresh_modes()

    # --------------------------------------------------------------------- helpers UI
    def _pick_outdir(self):
        d = filedialog.askdirectory(parent=self.top, initialdir=self.var_outdir.get())
        if d:
            self.var_outdir.set(d)

    def _provider(self):
        return XYZ_PROVIDERS[max(0, self.cbo_provider.current())]

    def _collection_id(self):
        return CBERS_COLLECTIONS[max(0, self.cbo_collection.current())][0]

    def _refresh_modes(self):
        modes = modes_for_collection(self._collection_id())
        self._modes = modes
        self.cbo_mode['values'] = [mode_label(m) for m in modes]
        self.cbo_mode.current(0)

    def _current_extent_bbox(self):
        ctx = getattr(self.parent, 'arcmap_context', {}) or {}
        return ctx.get('bbox')

    def _update_estimate(self):
        key, label, max_zoom, tos = self._provider()
        self.lbl_tos.config(text=(u"Atenção: o uso de tiles do %s está sujeito aos Termos de Serviço do provedor." % label.split(' ')[0]) if tos else u"")
        try:
            zoom = int(self.var_zoom.get())
        except ValueError:
            self.lbl_estimate.config(text=u"Zoom inválido.")
            return
        if zoom > max_zoom:
            self.lbl_estimate.config(text=u"%s oferece zoom até %d." % (label, max_zoom))
            return
        if self.var_area.get() != "extent":
            self.lbl_estimate.config(text=u"Estimativa exibida ao iniciar (a AOI é exportada do ArcMap).")
            return
        bbox = self._current_extent_bbox()
        if not bbox:
            self.lbl_estimate.config(text=u"Extensão do ArcMap indisponível.")
            return
        try:
            self.lbl_estimate.config(text=format_estimate(tilemath.estimate(bbox, zoom)))
        except Exception as e:
            self.lbl_estimate.config(text=to_text(e))

    def _set_status(self, which, text, pct=None):
        lbl = self.lbl_xyz_status if which == 'xyz' else self.lbl_cbers_status
        prog = self.prog_xyz if which == 'xyz' else self.prog_cbers
        lbl.config(text=text)
        if pct is not None:
            prog['value'] = max(0, min(100, pct))

    def _set_busy(self, which, busy):
        self.busy[which] = busy
        state = tk.DISABLED if busy else tk.NORMAL
        if which == 'xyz':
            self.btn_xyz.config(state=state)
        else:
            for b in (self.btn_search, self.btn_cbers_dl, self.btn_thumb):
                b.config(state=state)

    def _post(self, fn):
        self.parent.post_to_gui(fn)

    def _out_dir(self):
        d = self.var_outdir.get().strip() or default_output_dir()
        if not os.path.isdir(d):
            os.makedirs(d)
        return d

    # ---------------------------------------------- AOI (executado em worker thread)
    def _collect_area(self):
        """Lido na thread do Tk: o que o worker precisa para resolver a AOI."""
        return {'type': self.var_area.get(), 'layer': self.cbo_layer.get(),
                'buffer': float(self.settings.get('aoi_buffer_meters', 0.0) or 0.0)}

    def _resolve_bbox(self, area):
        """Roda no worker: devolve bbox WGS84 [min_lon, min_lat, max_lon, max_lat]."""
        if area['type'] == 'layer':
            if not area['layer'] or area['layer'] == u"Nenhuma camada encontrada":
                raise ValueError(u"Selecione uma camada vetorial (AOI) válida.")
            with self.parent.ipc_lock:
                rep = gee_bridge.send_arcmap_command({'action': 'export_aoi', 'layer_name': area['layer'],
                                                     'buffer_meters': area['buffer']}, timeout=30)
            if not rep.get('success') or not rep.get('file'):
                raise ValueError(u"Falha ao exportar a AOI '%s': %s" % (area['layer'], rep.get('message', u'')))
            with open(rep['file'], 'r') as f:
                return bbox_from_geojson_data(json.load(f))
        with self.parent.ipc_lock:
            rep = gee_bridge.send_arcmap_command({'action': 'refresh_context'}, timeout=15)
        ctx = rep.get('context') if rep.get('success') else None
        bbox = (ctx or {}).get('bbox') or self._current_extent_bbox()
        if not bbox:
            raise ValueError(u"Não foi possível obter a extensão atual do ArcMap. Verifique se o mapa tem "
                             u"sistema de coordenadas definido ou use uma camada AOI.")
        return [float(v) for v in bbox]

    def _load_into_arcmap(self, path, name, group, rgb_bands, sensor, zoom):
        with self.parent.ipc_lock:
            rep = gee_bridge.send_arcmap_command({
                'action': 'load_layer', 'file': path, 'name': name, 'group': group, 'zoom': zoom,
                'comp': None, 'sensor': sensor, 'custom_bands': None, 'rgb_bands': rgb_bands,
            }, timeout=300)
        return rep

    # ---------------------------------------------------------------------- XYZ
    def on_xyz_download(self):
        if self.busy['xyz']:
            return
        key, label, max_zoom, tos = self._provider()
        try:
            zoom = int(self.var_zoom.get())
        except ValueError:
            messagebox.showwarning(u"Zoom", u"Informe um zoom numérico.", parent=self.top)
            return
        if zoom > max_zoom:
            messagebox.showwarning(u"Zoom", u"%s oferece zoom até %d." % (label, max_zoom), parent=self.top)
            return
        if tos and not self.settings.get('arcmagery_tos_ack_' + key.split('-')[0]):
            if not messagebox.askyesno(u"Termos de Uso", TOS_TEXT, parent=self.top, icon=messagebox.WARNING):
                return
            self.settings['arcmagery_tos_ack_' + key.split('-')[0]] = True
            gee_bridge.save_plugin_settings(self.settings)
        try:
            out_dir = self._out_dir()
        except Exception as e:
            messagebox.showerror(u"Pasta de saída", to_text(e), parent=self.top)
            return
        params = {
            'area': self._collect_area(), 'provider': key, 'label': label, 'zoom': zoom,
            'compression': 'LZW' if self.cbo_compress.current() == 1 else 'JPEG',
            'crs': 'EPSG:4674' if self.var_reproject.get() else None, 'out_dir': out_dir,
        }
        self.settings['arcmagery_output_dir'] = out_dir
        self.settings['arcmagery_xyz_zoom'] = zoom
        self._set_busy('xyz', True)
        self._set_status('xyz', u"Obtendo a área de interesse...", 0)
        t = threading.Thread(target=self._xyz_worker, args=(params,))
        t.daemon = True
        t.start()

    def _xyz_worker(self, p):
        try:
            bbox = self._resolve_bbox(p['area'])
            est = tilemath.estimate(bbox, p['zoom'])
            self._post(lambda: self._set_status('xyz', u"Baixando: " + format_estimate(est), 0))
            stamp = time.strftime('%Y%m%d_%H%M%S')
            out = unique_path(p['out_dir'], u"arcmagery_%s_z%d_%s" % (p['provider'], p['zoom'], stamp))

            def on_progress(line):
                pr = parse_progress(line)
                if pr:
                    self._post(lambda: self._set_status('xyz', u"Baixando tiles %d/%d..." % pr, 100.0 * pr[0] / pr[1]))

            res = gee_bridge.run_backend_cmd('xyz_download', {
                'bbox': ','.join('%.8f' % v for v in bbox), 'zoom': p['zoom'], 'provider': p['provider'],
                'out': out, 'compression': p['compression'], 'crs': p['crs'],
            }, on_progress=on_progress, python_exe=gee_bridge.find_python3_gdal())
            if not res.get('success'):
                raise RuntimeError(res.get('message') or u"Falha no download do mosaico.")
            self._post(lambda: self._set_status('xyz', u"Carregando no ArcMap...", 100))
            name = u"%s z%d (%s)" % (p['label'], p['zoom'], time.strftime('%d/%m/%Y %H:%M'))
            rep = self._load_into_arcmap(res['file'], name, XYZ_GROUP, [0, 1, 2], 'XYZ', True)
            msg = u"Concluído: %d x %d px, %.2f m/px, %d tiles em %.0f s." % (
                res.get('width', 0), res.get('height', 0), res.get('ground_res_m', 0), res.get('tiles', 0),
                res.get('seconds', 0))
            if res.get('missing_tiles'):
                msg += u" %d tiles sem imagem no provedor." % res['missing_tiles']
            if not rep.get('success'):
                msg += u" ATENÇÃO: arquivo salvo, mas não foi carregado no ArcMap: %s" % to_text(rep.get('message', u''))
            if res.get('attribution'):
                msg += u"\nFonte: %s" % res['attribution']
            self._post(lambda: self._set_status('xyz', msg, 100))
        except Exception as e:
            err = to_text(e)
            self._post(lambda: self._set_status('xyz', u"Falha: " + err, 0))
            self._post(lambda: messagebox.showerror(u"Google Earth / XYZ", err, parent=self.top))
        finally:
            self._post(lambda: self._set_busy('xyz', False))

    # -------------------------------------------------------------------- CBERS
    def on_cbers_search(self):
        if self.busy['cbers']:
            return
        try:
            d0, d1 = validate_date_range(self.var_d0.get(), self.var_d1.get())
            cloud = float(self.var_cloud.get().replace(',', '.'))
            if not 0 <= cloud <= 100:
                raise ValueError(u"Nuvens máx. deve estar entre 0 e 100.")
        except ValueError as e:
            messagebox.showwarning(u"Parâmetros", to_text(e), parent=self.top)
            return
        params = {'area': self._collect_area(), 'collection': self._collection_id(),
                  'start': d0.strftime('%Y-%m-%d'), 'end': d1.strftime('%Y-%m-%d'),
                  'cloud': None if cloud >= 100 else cloud}
        self._set_busy('cbers', True)
        self._set_status('cbers', u"Consultando o catálogo STAC do INPE...", 0)
        t = threading.Thread(target=self._search_worker, args=(params,))
        t.daemon = True
        t.start()

    def _search_worker(self, p):
        try:
            bbox = self._resolve_bbox(p['area'])
            res = gee_bridge.run_backend_cmd('stac_search', {
                'collections': p['collection'], 'bbox': ','.join('%.8f' % v for v in bbox),
                'start_date': p['start'], 'end_date': p['end'], 'max_cloud': p['cloud'], 'max_items': 200,
            }, python_exe=gee_bridge.find_python3_gdal())
            if not res.get('success'):
                raise RuntimeError(res.get('message') or u"Falha na busca STAC.")
            items = res.get('items', [])
            self._post(lambda: self._fill_tree(items, bbox))
        except Exception as e:
            err = to_text(e)
            self._post(lambda: self._set_status('cbers', u"Falha: " + err))
            self._post(lambda: messagebox.showerror(u"CBERS / INPE", err, parent=self.top))
        finally:
            self._post(lambda: self._set_busy('cbers', False))

    def _fill_tree(self, items, bbox):
        self.tree.delete(*self.tree.get_children())
        self.cbers_items = {}
        self.cbers_bbox = bbox
        for it in items:
            iid = self.tree.insert('', tk.END, values=(
                it.get('date', ''), it.get('collection', ''), it.get('id', ''),
                u"n/d" if it.get('cloud_cover') is None else u"%.1f" % it['cloud_cover'],
                u"n/d" if it.get('coverage_pct') is None else u"%.0f" % it['coverage_pct']))
            self.cbers_items[iid] = it
        self._set_status('cbers', u"%d cena(s) cobrindo a área. Selecione e baixe o recorte." % len(items) if items
                         else u"Nenhuma cena cobre a área no período.")

    def _selected_items(self):
        return [self.cbers_items[i] for i in self.tree.selection() if i in self.cbers_items]

    def on_cbers_thumb(self):
        sel = self._selected_items()
        if not sel:
            messagebox.showwarning(u"Miniatura", u"Selecione uma cena na tabela.", parent=self.top)
            return
        it = sel[0]
        self._set_busy('cbers', True)
        self._set_status('cbers', u"Baixando miniatura de %s..." % it['id'])

        def worker():
            try:
                res = gee_bridge.run_backend_cmd('stac_thumb', {'collection': it['collection'], 'item_id': it['id'],
                                                                 'href': it.get('thumbnail')},
                                                 python_exe=gee_bridge.find_python3_gdal())
                if not res.get('success') or not res.get('gif'):
                    raise RuntimeError(res.get('message') or u"Miniatura indisponível.")
                self._post(lambda: self._show_thumb(it['id'], res['gif']))
                self._post(lambda: self._set_status('cbers', u"Pronto."))
            except Exception as e:
                err = to_text(e)
                self._post(lambda: self._set_status('cbers', u"Falha: " + err))
            finally:
                self._post(lambda: self._set_busy('cbers', False))

        t = threading.Thread(target=worker)
        t.daemon = True
        t.start()

    def _show_thumb(self, title, gif_path):
        win = tk.Toplevel(self.top)
        win.title(u"Miniatura - %s" % title)
        self._thumb_img = tk.PhotoImage(file=gif_path)
        tk.Label(win, image=self._thumb_img).pack(padx=6, pady=6)

    def on_cbers_download(self):
        if self.busy['cbers']:
            return
        sel = self._selected_items()
        if not sel:
            messagebox.showwarning(u"Download", u"Selecione ao menos uma cena na tabela.", parent=self.top)
            return
        try:
            out_dir = self._out_dir()
        except Exception as e:
            messagebox.showerror(u"Pasta de saída", to_text(e), parent=self.top)
            return
        mode = self._modes[max(0, self.cbo_mode.current())]
        self.settings['arcmagery_output_dir'] = out_dir
        params = {'items': sel, 'mode': mode, 'out_dir': out_dir, 'bbox': getattr(self, 'cbers_bbox', None),
                  'area': self._collect_area()}
        self._set_busy('cbers', True)
        self._set_status('cbers', u"Iniciando download de %d cena(s)..." % len(sel), 0)
        t = threading.Thread(target=self._cbers_download_worker, args=(params,))
        t.daemon = True
        t.start()

    def _cbers_download_worker(self, p):
        done, errors = 0, []
        try:
            bbox = p['bbox'] or self._resolve_bbox(p['area'])
            total = len(p['items'])
            for idx, it in enumerate(p['items']):
                def on_progress(line, idx=idx):
                    pr = parse_progress(line)
                    if pr:
                        pct = 100.0 * (idx + pr[0] / float(pr[1])) / total
                        self._post(lambda: self._set_status('cbers', u"Recortando cena %d/%d..." % (idx + 1, total), pct))
                try:
                    out = unique_path(p['out_dir'], safe_filename(u"%s_%s" % (it['id'], p['mode'])))
                    res = gee_bridge.run_backend_cmd('stac_download', {
                        'collection': it['collection'], 'item_id': it['id'], 'mode': p['mode'],
                        'bbox': ','.join('%.8f' % v for v in bbox), 'out': out,
                    }, on_progress=on_progress, python_exe=gee_bridge.find_python3_gdal())
                    if not res.get('success'):
                        raise RuntimeError(res.get('message') or u"Falha no recorte.")
                    name = u"%s %s (%s)" % (it['id'], mode_label(p['mode']), it.get('date', ''))
                    rep = self._load_into_arcmap(res['file'], name, CBERS_GROUP, res.get('rgb_bands'),
                                                 'CBERS', idx == 0)
                    if not rep.get('success'):
                        errors.append(u"%s: salvo em %s, mas não carregado (%s)" % (it['id'], res['file'], to_text(rep.get('message', u''))))
                    else:
                        done += 1
                except Exception as e:
                    errors.append(u"%s: %s" % (it['id'], to_text(e)))
            msg = u"%d de %d cena(s) carregadas no ArcMap." % (done, total)
            if errors:
                msg += u"\n" + u"\n".join(errors[:5])
            self._post(lambda: self._set_status('cbers', msg, 100 if done else 0))
            if errors:
                self._post(lambda: messagebox.showwarning(u"CBERS / INPE", msg, parent=self.top))
        except Exception as e:
            err = to_text(e)
            self._post(lambda: self._set_status('cbers', u"Falha: " + err, 0))
            self._post(lambda: messagebox.showerror(u"CBERS / INPE", err, parent=self.top))
        finally:
            self._post(lambda: self._set_busy('cbers', False))
