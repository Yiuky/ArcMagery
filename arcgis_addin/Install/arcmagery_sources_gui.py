# -*- coding: utf-8 -*-
"""
ArcMagery - Janela Google Earth / Mosaicos XYZ (Python 2.7 / Tkinter, processo da GUI).

  * Google Earth / Satelite e outros mosaicos XYZ (Esri, Bing)  -> backend xyz_core
  (O CBERS / Amazonia-1 fica integrado a janela principal: ver arcmagery_inpe.py.)

Regras de threading: todo acesso a widgets acontece na thread do Tk. Os workers leem os
parametros ANTES de iniciar (via _collect_*) e devolvem resultados com parent.post_to_gui.
As funcoes de nivel de modulo sao puras (sem Tk) e cobertas por testes em Python 2.7.
"""
from __future__ import division

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

# Espelho leve dos catalogos do backend (a lista completa e confirmada via 'sources_info').
XYZ_PROVIDERS = [
    ('google', u'Google Earth / Satélite', 21, True),
    ('google-hybrid', u'Google Híbrido (satélite + rótulos)', 21, True),
    ('esri', u'Esri World Imagery', 19, False),
    ('esri-clarity', u'Esri World Imagery (Clarity)', 19, False),
    ('bing', u'Bing Aerial', 19, True),
]

TOS_TEXT = (u"ATENÇÃO - Termos de Uso\n\n"
            u"O download em massa de tiles do Google e do Bing fora das APIs oficiais viola os Termos "
            u"de Serviço desses provedores. Use apenas quando houver respaldo (licença/autorização) e "
            u"cite a fonte. Para uso institucional, prefira a Esri World Imagery ou o CBERS (dados "
            u"públicos do INPE).\n\nDeseja continuar com o download?")


# ------------------------------------------------------------------------ funcoes puras
ESRI_KEYS = ('esri', 'esri-clarity')
NO_DATES_TEXT = (u"Datas de captura indisponíveis para esta fonte: o Google e o Bing não oferecem API pública "
                 u"com a data das imagens. Use a Esri World Imagery para obter data e histórico.")


def is_esri(provider_key):
    return provider_key in ESRI_KEYS


def date_br(iso):
    s = (iso or u'')[:10]
    return u"%s/%s/%s" % (s[8:10], s[5:7], s[0:4]) if len(s) == 10 else (s or u"n/d")


def version_label(v):
    """Rotulo de uma versao Wayback no combobox: data de CAPTURA primeiro (o que importa ao usuario)."""
    res = v.get('resolution_m')
    res_txt = (u" · %.2f m" % float(res)).replace(u'.', u',') if res not in (None, '') else u''
    return u"Captura %s · %s %s%s  (Wayback %s)" % (
        date_br(v.get('capture_date')), v.get('sensor_name') or v.get('sensor') or u'?', v.get('provider') or u'', res_txt,
        date_br(v.get('release_date')))


def dates_summary_text(dates):
    """Linhas curtas com as datas da area: '05/05/2024 · GE01 Vantor · 0,46 m · 100% da área'."""
    lines = []
    for d in dates[:6]:
        res = d.get('resolution_m')
        lines.append(u"%s · %s %s · %s · %.0f%% da área" % (
            date_br(d.get('date')), d.get('sensor_name') or d.get('sensor') or u'?', d.get('provider') or u'',
            (u"%.2f m" % float(res)).replace(u'.', u',') if res not in (None, '') else u'n/d',
            float(d.get('coverage_pct') or 0)))
    if len(dates) > 6:
        lines.append(u"... +%d datas" % (len(dates) - 6))
    return u"\n".join(lines) or u"Nenhuma data informada para a área neste zoom."


CRS_CHOICES = [
    (None, u"Web Mercator (EPSG:3857) - nativo dos tiles, sem reamostragem"),
    ('EPSG:4326', u"WGS 84 (EPSG:4326)"),
    ('EPSG:4674', u"SIRGAS 2000 (EPSG:4674)"),
]


def google_reference_text(esri_reference):
    """Google/Bing nao publicam a data: a da Esri e apenas REFERENCIA (pode ser outra cena)."""
    txt = u"Data da imagem: não publicada pelo provedor (Google/Bing não têm API de datas)."
    if esri_reference and not esri_reference.startswith(u'data de captura não'):
        txt += (u"\nReferência: a imagem Esri desta área é de %s. ATENÇÃO: é outra fonte e pode ser "
                u"outra cena; não use como data da imagem do Google." % esri_reference)
    return txt


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
        self.top.title(u"ArcMagery - Google Earth / Mosaicos XYZ")
        self.top.geometry("900x640")
        self.top.minsize(820, 560)
        self.busy = {'xyz': False}
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

        ttk.Label(f, text=u"Sistema de coordenadas:").grid(row=3, column=0, sticky=tk.W)
        self.cbo_crs = ttk.Combobox(f, state="readonly", width=58, values=[c[1] for c in CRS_CHOICES])
        saved_crs = self.settings.get('arcmagery_xyz_crs')
        self.cbo_crs.current(max(0, [c[0] for c in CRS_CHOICES].index(saved_crs))
                             if saved_crs in [c[0] for c in CRS_CHOICES] else 0)
        self.cbo_crs.grid(row=3, column=1, sticky=tk.W, pady=4)

        dates_box = ttk.LabelFrame(f, text=u" Data das imagens (Esri World Imagery / Wayback) ", padding=6)
        dates_box.grid(row=4, column=0, columnspan=2, sticky=tk.EW, pady=(6, 2))
        ttk.Label(dates_box, text=u"Imagem:").grid(row=0, column=0, sticky=tk.W)
        self.cbo_version = ttk.Combobox(dates_box, state="readonly", width=78)
        self.cbo_version.grid(row=0, column=1, sticky=tk.W, padx=4)
        self.btn_dates = ttk.Button(dates_box, text=u"Consultar datas desta área", command=self.on_query_dates)
        self.btn_dates.grid(row=0, column=2, sticky=tk.W, padx=4)
        self.var_footprints = tk.BooleanVar(value=bool(self.settings.get('arcmagery_date_footprints', True)))
        self.chk_footprints = ttk.Checkbutton(dates_box, text=u"Carregar também os polígonos com as datas de captura",
                                              variable=self.var_footprints)
        self.chk_footprints.grid(row=1, column=1, columnspan=2, sticky=tk.W, pady=(3, 0))
        self.lbl_dates = tk.Label(dates_box, text=u"", font=("Segoe UI", 8), fg="#1d6a3a", justify=tk.LEFT,
                                  anchor=tk.W, wraplength=820)
        self.lbl_dates.grid(row=2, column=0, columnspan=3, sticky=tk.W, pady=(3, 0))
        self._versions = []
        self._dates_key = None
        self._reset_versions()

        self.lbl_estimate = tk.Label(f, text=u"", font=("Segoe UI", 9), fg="#1b4f72", justify=tk.LEFT)
        self.lbl_estimate.grid(row=5, column=0, columnspan=2, sticky=tk.W, pady=(8, 2))
        self.lbl_tos = tk.Label(f, text=u"", font=("Segoe UI", 8), fg="#922b21", justify=tk.LEFT, wraplength=820)
        self.lbl_tos.grid(row=6, column=0, columnspan=2, sticky=tk.W)

        self.btn_xyz = ttk.Button(f, text=u"Baixar mosaico e carregar no ArcMap", style="Primary.TButton",
                                  command=self.on_xyz_download)
        self.btn_xyz.grid(row=7, column=0, columnspan=2, sticky=tk.W, pady=(12, 4))
        self.prog_xyz = ttk.Progressbar(f, mode="determinate", length=600)
        self.prog_xyz.grid(row=8, column=0, columnspan=2, sticky=tk.EW, pady=2)
        self.lbl_xyz_status = tk.Label(f, text=u"Pronto.", font=("Segoe UI", 9), anchor=tk.W, justify=tk.LEFT)
        self.lbl_xyz_status.grid(row=9, column=0, columnspan=2, sticky=tk.W)
        f.columnconfigure(1, weight=1)

    # --------------------------------------------------------------------- helpers UI
    def _pick_outdir(self):
        d = filedialog.askdirectory(parent=self.top, initialdir=self.var_outdir.get())
        if d:
            self.var_outdir.set(d)

    def _provider(self):
        return XYZ_PROVIDERS[max(0, self.cbo_provider.current())]

    def _current_extent_bbox(self):
        ctx = getattr(self.parent, 'arcmap_context', {}) or {}
        return ctx.get('bbox')

    def _reset_versions(self, text=None):
        self._versions = []
        self.cbo_version['values'] = [u"Mais recente (World Imagery atual)"]
        self.cbo_version.current(0)
        if text is not None:
            self.lbl_dates.config(text=text)

    def _update_dates_availability(self):
        key = self._provider()[0]
        esri = is_esri(key)
        wayback_ok = key == 'esri'
        self.btn_dates.config(state=tk.NORMAL if (esri and not self.busy.get('dates')) else tk.DISABLED)
        self.cbo_version.config(state="readonly" if wayback_ok else tk.DISABLED)
        self.chk_footprints.config(state=tk.NORMAL if esri else tk.DISABLED)
        context = (key, self.var_zoom.get(), self.var_area.get())
        if context != self._dates_key:
            self._dates_key = context
            if not esri:
                self._reset_versions(NO_DATES_TEXT)
            elif self._versions or not self.lbl_dates.cget('text') or self.lbl_dates.cget('text') == NO_DATES_TEXT:
                self._reset_versions(u"Clique em 'Consultar datas desta área' para ver a data de captura e o "
                                     u"histórico (versões anteriores) desta área. A data também vai no nome da camada.")

    def _selected_release(self):
        idx = self.cbo_version.current()
        if self._provider()[0] != 'esri' or idx <= 0 or idx > len(self._versions):
            return None
        return self._versions[idx - 1]

    def _update_estimate(self):
        if hasattr(self, 'cbo_version'):
            self._update_dates_availability()
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
        self.lbl_xyz_status.config(text=text)
        if pct is not None:
            self.prog_xyz['value'] = max(0, min(100, pct))

    def _set_busy(self, which, busy):
        self.busy[which] = busy
        self.btn_xyz.config(state=tk.DISABLED if busy else tk.NORMAL)

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

    # --------------------------------------------------------------- datas (Esri)
    def on_query_dates(self):
        if self.busy.get('dates') or not is_esri(self._provider()[0]):
            return
        try:
            zoom = int(self.var_zoom.get())
        except ValueError:
            messagebox.showwarning(u"Zoom", u"Informe um zoom numérico.", parent=self.top)
            return
        self.busy['dates'] = True
        self.btn_dates.config(state=tk.DISABLED)
        self.lbl_dates.config(text=u"Consultando datas de captura e o histórico Wayback da Esri... (cerca de 20 s)")
        area = self._collect_area()
        wayback = self._provider()[0] == 'esri'
        t = threading.Thread(target=self._dates_worker, args=(area, zoom, wayback))
        t.daemon = True
        t.start()

    def _dates_worker(self, area, zoom, wayback):
        try:
            bbox = self._resolve_bbox(area)
            params = {'bbox': ','.join('%.8f' % v for v in bbox), 'zoom': zoom}
            cur = gee_bridge.run_backend_cmd('esri_dates', params, python_exe=gee_bridge.find_python3_gdal())
            if not cur.get('success'):
                raise RuntimeError(cur.get('message') or u"Falha ao consultar as datas.")
            versions = []
            if wayback:
                ver = gee_bridge.run_backend_cmd('esri_versions', params, python_exe=gee_bridge.find_python3_gdal())
                if ver.get('success'):
                    versions = ver.get('versions', [])
            self._post(lambda: self._show_dates(cur, versions))
        except Exception as e:
            err = to_text(e)
            self._post(lambda: self.lbl_dates.config(text=u"Falha na consulta de datas: " + err))
        finally:
            def done():
                self.busy['dates'] = False
                self._update_dates_availability()
            self._post(done)

    def _show_dates(self, cur, versions):
        self._versions = list(versions)
        values = [u"Mais recente (World Imagery atual)"] + [version_label(v) for v in self._versions]
        self.cbo_version['values'] = values
        self.cbo_version.current(0)
        txt = u"Imagem atual nesta área:\n" + dates_summary_text(cur.get('dates', []))
        if self._versions:
            txt += u"\n\n%d data(s) de captura no histórico (escolha em 'Imagem' acima)." % len(self._versions)
        self.lbl_dates.config(text=txt)

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
        release = self._selected_release()
        params = {
            'area': self._collect_area(), 'provider': key, 'label': label, 'zoom': zoom,
            'compression': 'LZW' if self.cbo_compress.current() == 1 else 'JPEG',
            'crs': CRS_CHOICES[max(0, self.cbo_crs.current())][0], 'out_dir': out_dir,
            'wayback_release': release.get('release_num') if release else None,
            'footprints': bool(self.var_footprints.get()) and is_esri(key),
        }
        self.settings['arcmagery_date_footprints'] = bool(self.var_footprints.get())
        self.settings['arcmagery_xyz_crs'] = params['crs']
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
                'wayback_release': p.get('wayback_release'), 'footprints': p.get('footprints', False),
            }, on_progress=on_progress, python_exe=gee_bridge.find_python3_gdal())
            if not res.get('success'):
                raise RuntimeError(res.get('message') or u"Falha no download do mosaico.")
            self._post(lambda: self._set_status('xyz', u"Carregando no ArcMap...", 100))
            capture = res.get('capture_summary')
            if capture and not capture.startswith(u'indispon'):
                name = u"%s z%d · captura %s" % (p['label'], p['zoom'], capture)
            else:
                name = u"%s z%d (%s)" % (p['label'], p['zoom'], time.strftime('%d/%m/%Y %H:%M'))
            if res.get('wayback_date'):
                name += u" · Wayback %s" % date_br(res['wayback_date'])
            rep = self._load_into_arcmap(res['file'], name, XYZ_GROUP, [0, 1, 2], 'XYZ', True)
            if p.get('footprints') and res.get('footprints_json') and rep.get('success'):
                with self.parent.ipc_lock:
                    gee_bridge.send_arcmap_command({'action': 'load_date_footprints', 'file': res['footprints_json'],
                                                    'name': u"Datas de captura - " + name, 'group': XYZ_GROUP},
                                                   timeout=120)
            msg = u"Concluído: %d x %d px, %.2f m/px, %d tiles em %.0f s." % (
                res.get('width', 0), res.get('height', 0), res.get('ground_res_m', 0), res.get('tiles', 0),
                res.get('seconds', 0))
            if res.get('missing_tiles'):
                msg += u" %d tiles sem imagem no provedor." % res['missing_tiles']
            if not rep.get('success'):
                msg += u" ATENÇÃO: arquivo salvo, mas não foi carregado no ArcMap: %s" % to_text(rep.get('message', u''))
            if capture:
                msg += u"\nData de captura: %s" % capture
            elif 'esri_reference' in res:
                msg += u"\n" + google_reference_text(res.get('esri_reference'))
            if res.get('attribution'):
                msg += u"\nFonte: %s" % res['attribution']
            self._post(lambda: self._set_status('xyz', msg, 100))
        except Exception as e:
            err = to_text(e)
            self._post(lambda: self._set_status('xyz', u"Falha: " + err, 0))
            self._post(lambda: messagebox.showerror(u"Google Earth / XYZ", err, parent=self.top))
        finally:
            self._post(lambda: self._set_busy('xyz', False))
