# -*- coding: utf-8 -*-
"""
Interface Grafica (GUI) para ArcMap 10.8.2
Foco: Estabilidade total, processo independente via IPC, zero risco de crash no ArcMap.
Recursos:
- Execucao em processo proprio (pythonw.exe) sem travar o ArcMap
- Selecao multipla de imagens (selectmode extended)
- Download e carregamento em segundo plano (background) com atualizacao no TOC
- Suporte a Multibanda completa (todas as bandas brutas) ou RGB Rapido
- Mapeamento e substituicao de camadas existentes no TOC
- Controle e validacao da escala maxima 1:500.000
- Miniaturas sob medida com abertura no navegador
"""

import os
import sys
import tempfile
import threading
import datetime
import webbrowser
import time
import multiprocessing
try:
    import concurrent.futures
except ImportError:
    concurrent = None

try:
    unicode
except NameError:
    unicode = str

class SafeStream(object):
    def __init__(self, log_path=None):
        self.log_path = log_path
    def write(self, s):
        if not self.log_path:
            return
        try:
            if os.path.exists(self.log_path) and os.path.getsize(self.log_path) > 3 * 1024 * 1024:
                try:
                    bak = self.log_path + ".bak"
                    if os.path.exists(bak): os.remove(bak)
                    os.rename(self.log_path, bak)
                except Exception:
                    pass
            with open(self.log_path, "a") as f:
                if isinstance(s, unicode):
                    s = s.encode("utf-8", "replace")
                f.write(s)
        except Exception:
            pass
    def flush(self):
        pass

def _stream_is_usable(stream):
    """Sob pythonw.exe (Python 2.7) sys.stdout EXISTE e write("") funciona, mas o descritor e
    invalido (fileno() == -2): o primeiro flush de ~4 KB levanta IOError(9, 'Bad file
    descriptor'). Streams sem fileno() (ex.: janela Python do ArcMap) sao consideradas validas."""
    if stream is None or not hasattr(stream, 'write'):
        return False
    try:
        return stream.fileno() >= 0
    except Exception:
        return True

# Redirecionar sys.stdout e sys.stderr para evitar IOError silencioso em pythonw
if not _stream_is_usable(sys.stdout):
    sys.stdout = SafeStream(os.path.join(tempfile.gettempdir(), "arcgee_gui_stdout.log"))
if not _stream_is_usable(sys.stderr):
    sys.stderr = SafeStream(os.path.join(tempfile.gettempdir(), "arcgee_gui_stderr.log"))

# Compatibilidade Python 2.7 e Python 3
if sys.version_info[0] < 3:
    import Tkinter as tk
    import ttk
    import tkMessageBox as messagebox
    import tkSimpleDialog as simpledialog
    import tkFileDialog as filedialog
    import Queue as queue_mod
else:
    import tkinter as tk
    from tkinter import ttk
    from tkinter import messagebox
    from tkinter import simpledialog
    from tkinter import filedialog
    import queue as queue_mod

import gee_bridge
import arcmagery_inpe as inpe

def get_icon_path(filename="app_icon.ico"):
    curr_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(curr_dir, filename),
        os.path.join(curr_dir, "Images", filename),
        os.path.join(curr_dir, "..", "Images", filename),
        os.path.join(curr_dir, "..", "..", "arcgis_addin", "Images", filename)
    ]
    for c in candidates:
        if os.path.exists(c):
            return os.path.abspath(c)
    return None

def get_tk_image(base_name):
    """Retorna PhotoImage compativel com Tkinter (prioriza .gif para suporte a Tcl/Tk 8.5 no Python 2.7)"""
    for ext in [".gif", ".png"]:
        p = get_icon_path(base_name + ext)
        if p and os.path.exists(p):
            try:
                return tk.PhotoImage(file=p)
            except Exception:
                pass
    return None

def setup_window_icon(window):
    """Aplica o ícone oficial da ferramenta na barra de título e barra de tarefas do Windows"""
    ico_p = get_icon_path("app_icon.ico")
    if ico_p:
        try:
            window.iconbitmap(default=ico_p)
            return
        except Exception:
            try:
                window.iconbitmap(ico_p)
                return
            except Exception:
                pass

    for name in ["icon32", "icon24", "icon16", "icon"]:
        img = get_tk_image(name)
        if img:
            try:
                window.iconphoto(True, img)
                window._icon_photo_ref = img
                return
            except Exception:
                pass

def _safe_float(val, default=0.0):
    try:
        if val is None:
            return default
        s = unicode(val).strip().replace(',', '.')
        return float(s)
    except Exception:
        return default

def _safe_int(val, default=0):
    try:
        if val is None:
            return default
        s = unicode(val).strip().replace(',', '.')
        return int(float(s))
    except Exception:
        return default

class GEESettingsDialog(object):
    """Janela modal para configuracao de Stretch, Estatisticas (DRA), Visibilidade TOC e Multicore"""
    def __init__(self, parent):
        self.parent = parent
        p_win = parent.root if hasattr(parent, 'root') else parent
        self.top = tk.Toplevel(p_win)
        self.top.title(u"Configurações - ArcMagery")
        self.top.geometry("540x510")
        self.top.resizable(False, False)
        setup_window_icon(self.top)
        self.top.transient(p_win)
        self.top.grab_set()

        # Centralizar na janela pai
        try:
            x = p_win.winfo_rootx() + (p_win.winfo_width() // 2) - 270
            y = p_win.winfo_rooty() + (p_win.winfo_height() // 2) - 255
            self.top.geometry("+%d+%d" % (max(0, x), max(0, y)))
        except Exception:
            pass

        # Detectar CPU cores
        try:
            self.max_system_cores = multiprocessing.cpu_count()
        except Exception:
            self.max_system_cores = 4

        # Carregar configuracoes salvas
        self.settings = gee_bridge.load_plugin_settings()

        self.setup_ui()

    def setup_ui(self):
        # 1. Barra de Botoes FIXA NA BASE (garante que NUNCA seja suprimida ou empurrada para fora)
        btn_bar = ttk.Frame(self.top, padding=(12, 10))
        btn_bar.pack(side=tk.BOTTOM, fill=tk.X)

        btn_defaults = ttk.Button(btn_bar, text=u"Restaurar Padrões", command=self.on_restore_defaults)
        btn_defaults.pack(side=tk.LEFT)

        btn_cancel = ttk.Button(btn_bar, text=u"Cancelar", command=self.top.destroy)
        btn_cancel.pack(side=tk.RIGHT, padx=(6, 0))

        btn_save = ttk.Button(btn_bar, text=u"Salvar Configurações", style="Primary.TButton", command=self.on_save)
        btn_save.pack(side=tk.RIGHT)

        # 2. Notebook com Abas (Visualizacao & TOC | Processamento & Sistema)
        nb = ttk.Notebook(self.top)
        nb.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=(10, 4))

        # --- ABA 1: VISUALIZACAO & TOC ---
        tab_vis = ttk.Frame(nb, padding=10)
        nb.add(tab_vis, text=u"  Visualização & TOC  ")

        # 1. Grupo Stretch (Realce)
        grp_stretch = ttk.LabelFrame(tab_vis, text=u" Realce de Contraste Padrão (Stretch) ", padding=8)
        grp_stretch.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(grp_stretch, text=u"Tipo de Stretch:").grid(row=0, column=0, sticky=tk.W, pady=3)
        self.var_stretch = tk.StringVar(value=self.settings.get('stretch_type', 'Standard Deviations'))
        self.cbo_stretch = ttk.Combobox(
            grp_stretch,
            textvariable=self.var_stretch,
            state="readonly",
            values=[
                "Standard Deviations",
                "Percent Clip",
                "Minimum-Maximum",
                "Histogram Equalize",
                "None",
                "Esri",
                "Sigmoid"
            ],
            width=24
        )
        self.cbo_stretch.grid(row=0, column=1, sticky=tk.W, padx=8, pady=3)
        self.cbo_stretch.bind("<<ComboboxSelected>>", self._on_stretch_changed)

        ttk.Label(grp_stretch, text=u"Desvios Padrão (n):").grid(row=1, column=0, sticky=tk.W, pady=3)
        init_std = str(self.settings.get('stretch_std_param', 2.0)).replace(',', '.')
        self.var_std_param = tk.StringVar(value=init_std)
        self.spn_std = tk.Spinbox(
            grp_stretch,
            from_=0.5,
            to=5.0,
            increment=0.5,
            textvariable=self.var_std_param,
            width=8
        )
        self.spn_std.grid(row=1, column=1, sticky=tk.W, padx=8, pady=3)
        self.lbl_std_hint = ttk.Label(grp_stretch, text=u"(Padrão recomendado: 2.0)", font=("Segoe UI", 8), foreground="#555")
        self.lbl_std_hint.grid(row=1, column=1, sticky=tk.W, padx=(85, 0), pady=3)

        btn_apply_now = ttk.Button(
            grp_stretch,
            text=u"⚡ Aplicar e Garantir Stretch Atual nas Camadas do ArcMap",
            command=self.on_apply_stretch_now
        )
        btn_apply_now.grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(6, 2))

        # 2. Grupo Estatisticas (DRA)
        grp_stats = ttk.LabelFrame(tab_vis, text=u" Cálculo de Estatísticas do Raster (DRA) ", padding=8)
        grp_stats.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(grp_stats, text=u"Origem das Estatísticas:").grid(row=0, column=0, sticky=tk.W, pady=3)
        self.var_stats = tk.StringVar(value=self.settings.get('statistics_type', 'From Current Display Extent'))
        self.cbo_stats = ttk.Combobox(
            grp_stats,
            textvariable=self.var_stats,
            state="readonly",
            values=[
                "From Current Display Extent",
                "From Each Raster Dataset",
                "From Custom Settings"
            ],
            width=28
        )
        self.cbo_stats.grid(row=0, column=1, sticky=tk.W, padx=8, pady=3)

        lbl_stats_desc = ttk.Label(
            grp_stats,
            text=u"• 'From Current Display Extent' (DRA) adapta o contraste dinamicamente\n  à extensão visível na tela para nitidez ideal das bandas.",
            font=("Segoe UI", 8),
            foreground="#1b4f72"
        )
        lbl_stats_desc.grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(3, 0))

        # 3. Grupo Visualizacao no TOC (ArcMap)
        grp_vis = ttk.LabelFrame(tab_vis, text=u" Visualização de Camadas no TOC (ArcMap) ", padding=8)
        grp_vis.pack(fill=tk.X, pady=(0, 4))

        self.var_layer_visible = tk.BooleanVar(value=bool(self.settings.get('load_layer_visible', True)))
        self.chk_layer_visible = ttk.Checkbutton(
            grp_vis,
            text=u"Carregar imagens no TOC com visualização ativada (visíveis no mapa)",
            variable=self.var_layer_visible
        )
        self.chk_layer_visible.pack(anchor=tk.W, pady=2)

        lbl_vis_desc = ttk.Label(
            grp_vis,
            text=u"• Ativado: Imagens entram marcadas no TOC e renderizadas na tela.\n• Desativado: Imagens entram desmarcadas no TOC, ideal para carregar\n  várias cenas sem travar ou congelar a renderização do ArcMap.",
            font=("Segoe UI", 8),
            foreground="#1b4f72"
        )
        lbl_vis_desc.pack(anchor=tk.W, pady=(2, 0))

        # --- ABA 2: PROCESSO & SISTEMA ---
        tab_sys = ttk.Frame(nb, padding=10)
        nb.add(tab_sys, text=u"  Processamento & Sistema  ")

        # 4. Grupo Multicore
        grp_multi = ttk.LabelFrame(tab_sys, text=u" Desempenho e Aceleração Multicore ", padding=8)
        grp_multi.pack(fill=tk.X, pady=(0, 8))

        self.var_multicore = tk.BooleanVar(value=bool(self.settings.get('multicore_enabled', True)))
        self.chk_multi = ttk.Checkbutton(
            grp_multi,
            text=u"Ativar processamento e downloads paralelos Multicore",
            variable=self.var_multicore,
            command=self._on_multi_toggled
        )
        self.chk_multi.grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=2)

        ttk.Label(grp_multi, text=u"Número de Cores (Threads):").grid(row=1, column=0, sticky=tk.W, pady=3)
        init_cores = int(self.settings.get('multicore_cores', min(4, self.max_system_cores)))
        self.var_cores = tk.StringVar(value=str(min(max(1, init_cores), self.max_system_cores)))
        self.spn_cores = tk.Spinbox(
            grp_multi,
            from_=1,
            to=self.max_system_cores,
            increment=1,
            textvariable=self.var_cores,
            width=8
        )
        self.spn_cores.grid(row=1, column=1, sticky=tk.W, padx=8, pady=3)

        lbl_cores_hint = ttk.Label(
            grp_multi,
            text=u"(Detectados: %d núcleos na CPU)" % self.max_system_cores,
            font=("Segoe UI", 8),
            foreground="#555"
        )
        lbl_cores_hint.grid(row=1, column=1, sticky=tk.W, padx=(85, 0), pady=3)

        lbl_multi_desc = ttk.Label(
            grp_multi,
            text=u"• Acelera a geração de pirâmides e estatísticas no ArcMap.\n• Permite o download simultâneo de múltiplos quadrantes em segundo plano.",
            font=("Segoe UI", 8),
            foreground="#0b5345"
        )
        lbl_multi_desc.grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(3, 0))

        # 5. Grupo Buffer da Camada Vetorial (AOI)
        grp_aoi = ttk.LabelFrame(tab_sys, text=u" Buffer do Retângulo Envolvente (AOI) ", padding=8)
        grp_aoi.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(grp_aoi, text=u"Buffer Adicional (metros):").grid(row=0, column=0, sticky=tk.W, pady=3)
        init_buffer = self.settings.get('aoi_buffer_meters', 1000.0)
        self.var_aoi_buffer = tk.StringVar(value=str(int(init_buffer) if float(init_buffer).is_integer() else init_buffer).replace(',', '.'))
        self.spn_aoi_buffer = tk.Spinbox(
            grp_aoi,
            from_=0,
            to=50000,
            increment=100,
            textvariable=self.var_aoi_buffer,
            width=10
        )
        self.spn_aoi_buffer.grid(row=0, column=1, sticky=tk.W, padx=8, pady=3)

        lbl_buffer_hint = ttk.Label(
            grp_aoi,
            text=u"(Padrão: 1000m = 1 km | ex: 0m, 500m, 1000m)",
            font=("Segoe UI", 8),
            foreground="#555"
        )
        lbl_buffer_hint.grid(row=0, column=1, sticky=tk.W, padx=(100, 0), pady=3)

        lbl_aoi_desc = ttk.Label(
            grp_aoi,
            text=u"• Expande o retângulo da AOI em N metros em todas as direções.",
            font=("Segoe UI", 8),
            foreground="#1b4f72"
        )
        lbl_aoi_desc.grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(3, 0))

        # 6. Grupo Atualizacao do Plugin
        grp_update = ttk.LabelFrame(tab_sys, text=u" Atualização do Plugin ", padding=8)
        grp_update.pack(fill=tk.X, pady=(0, 4))

        ttk.Label(
            grp_update,
            text=u"Sincronize o plugin com as últimas melhorias via GitHub ou arquivo ZIP local:",
            font=("Segoe UI", 8),
            foreground="#333"
        ).pack(anchor=tk.W, pady=(0, 4))

        btn_open_updater = ttk.Button(
            grp_update,
            text=u"🔄 Abrir Assistente de Atualização (GitHub / ZIP)",
            command=self._open_updater
        )
        btn_open_updater.pack(anchor=tk.W)

        self._on_stretch_changed()
        self._on_multi_toggled()

    def _open_updater(self):
        GEEUpdaterDialog(self.parent)

    def _on_stretch_changed(self, event=None):
        st = self.var_stretch.get()
        if st in ("Standard Deviations", "Standard Deviation"):
            self.spn_std.config(state=tk.NORMAL)
            self.lbl_std_hint.config(foreground="#555")
        else:
            self.spn_std.config(state=tk.DISABLED)
            self.lbl_std_hint.config(foreground="#aaa")

    def _on_multi_toggled(self):
        if self.var_multicore.get():
            self.spn_cores.config(state=tk.NORMAL)
        else:
            self.spn_cores.config(state=tk.DISABLED)

    def on_restore_defaults(self):
        self.var_stretch.set("Standard Deviations")
        self.var_std_param.set("2.0")
        self.var_stats.set("From Current Display Extent")
        self.var_multicore.set(True)
        self.var_cores.set(str(min(4, self.max_system_cores)))
        self.var_aoi_buffer.set("1000")
        self.var_layer_visible.set(True)
        self._on_stretch_changed()
        self._on_multi_toggled()

    def on_apply_stretch_now(self):
        try:
            new_settings = {
                'stretch_type': self.var_stretch.get(),
                'stretch_std_param': _safe_float(self.var_std_param.get(), 2.0),
                'statistics_type': self.var_stats.get(),
                'multicore_enabled': bool(self.var_multicore.get()),
                'multicore_cores': _safe_int(self.var_cores.get(), min(4, self.max_system_cores)),
                'aoi_buffer_meters': _safe_float(self.var_aoi_buffer.get(), 1000.0),
                'load_layer_visible': bool(self.var_layer_visible.get())
            }
            new_settings = dict(gee_bridge.load_plugin_settings(), **new_settings)
            gee_bridge.save_plugin_settings(new_settings)
            if hasattr(self.parent, 'settings'):
                self.parent.settings = new_settings

            rep = gee_bridge.apply_stretch(None, settings=new_settings)
            if rep.get('success'):
                messagebox.showinfo(u"Stretch Garantido", rep.get('message', u"Stretch aplicado com sucesso!"), parent=self.top)
            else:
                messagebox.showwarning(u"Aviso ArcMap", rep.get('message', u"Não foi possível aplicar nas camadas do TOC."), parent=self.top)
        except Exception as e:
            messagebox.showerror(u"Erro ao Aplicar", u"Erro ao aplicar configurações:\n" + unicode(e), parent=self.top)

    def on_save(self):
        try:
            new_settings = {
                'stretch_type': self.var_stretch.get(),
                'stretch_std_param': _safe_float(self.var_std_param.get(), 2.0),
                'statistics_type': self.var_stats.get(),
                'multicore_enabled': bool(self.var_multicore.get()),
                'multicore_cores': _safe_int(self.var_cores.get(), min(4, self.max_system_cores)),
                'aoi_buffer_meters': _safe_float(self.var_aoi_buffer.get(), 1000.0),
                'load_layer_visible': bool(self.var_layer_visible.get())
            }
            new_settings = dict(gee_bridge.load_plugin_settings(), **new_settings)
            if gee_bridge.save_plugin_settings(new_settings):
                if hasattr(self.parent, 'settings'):
                    self.parent.settings = new_settings
                messagebox.showinfo(
                    u"Configurações Salvas",
                    u"As preferências de Stretch, Estatísticas, Multicore, Buffer e Visibilidade no TOC foram salvas com sucesso!",
                    parent=self.top
                )
                self.top.destroy()
            else:
                messagebox.showerror(u"Erro", u"Falha ao salvar arquivo de configurações.", parent=self.top)
        except Exception as e:
            messagebox.showerror(u"Erro ao Salvar", u"Erro ao processar as configurações:\n" + unicode(e), parent=self.top)

class GEEAboutDialog(object):
    """Janela modal Sobre com informações institucionais, versão, links e dicas"""
    def __init__(self, parent):
        self.parent = parent
        p_win = parent.root if hasattr(parent, 'root') else parent
        self.top = tk.Toplevel(p_win)
        self.top.title(u"Sobre - ArcMagery")
        self.top.geometry("580x525")
        self.top.resizable(False, False)
        setup_window_icon(self.top)
        self.top.transient(p_win)
        self.top.grab_set()

        try:
            x = p_win.winfo_rootx() + (p_win.winfo_width() // 2) - 290
            y = p_win.winfo_rooty() + (p_win.winfo_height() // 2) - 262
            self.top.geometry("+%d+%d" % (max(0, x), max(0, y)))
        except Exception:
            pass

        pad = ttk.Frame(self.top, padding=16)
        pad.pack(fill=tk.BOTH, expand=True)

        head_frame = ttk.Frame(pad)
        head_frame.pack(fill=tk.X, pady=(0, 10))

        # Logo em destaque de alta definicao no dialogo Sobre
        self.about_photo = get_tk_image("about_logo") or get_tk_image("icon64") or get_tk_image("icon")
        if self.about_photo:
            lbl_about_ico = ttk.Label(head_frame, image=self.about_photo)
            lbl_about_ico.pack(side=tk.LEFT, padx=(0, 16))

        title_box = ttk.Frame(head_frame)
        title_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        lbl_title = tk.Label(
            title_box,
            text=u"ArcMagery",
            font=("Segoe UI", 16, "bold"),
            fg="#0b5345"
        )
        lbl_title.pack(anchor=tk.W, pady=(4, 2))

        lbl_sub = tk.Label(
            title_box,
            text=u"Google Earth Engine, Google Earth e CBERS/INPE no ArcGIS Desktop 10.8 (ArcMap)  |  v%s" % CURRENT_VERSION,
            font=("Segoe UI", 9, "italic"),
            fg="#566573"
        )
        lbl_sub.pack(anchor=tk.W, pady=(0, 4))

        lbl_tag = tk.Label(
            title_box,
            text=u"Sensoriamento Remoto & Observação da Terra com Qualidade Nativa 100%",
            font=("Segoe UI", 8, "bold"),
            fg="#1b4f72"
        )
        lbl_tag.pack(anchor=tk.W)

        sep1 = ttk.Separator(pad, orient=tk.HORIZONTAL)
        sep1.pack(fill=tk.X, pady=(0, 10))

        info_frame = ttk.LabelFrame(pad, text=u" Informações do Sistema ", padding=10)
        info_frame.pack(fill=tk.X, pady=(0, 10))

        info_text = (
            u"• Versão: v2.3.2 (ArcMagery: GEE, CBERS/INPE, Google Earth / XYZ e datas Esri Wayback)\n"
            u"• Organização: Coordenadoria de Geoprocessamento e Monitoramento Ambiental\n"
            u"  Secretaria de Estado de Meio Ambiente de Mato Grosso (CGMA / SEMA-MT)\n"
            u"• Desenvolvedor: Joberth Firmino Gambati\n"
            u"• Compatibilidade: ArcGIS Desktop 10.8 / 10.8.2 (ArcMap) & Python 3.9+\n"
            u"• Licença: Código Aberto (MIT License)"
        )
        ttk.Label(info_frame, text=info_text, justify=tk.LEFT).pack(anchor=tk.W)

        tips_frame = ttk.LabelFrame(pad, text=u" Dicas Rápidas de Operação ", padding=10)
        tips_frame.pack(fill=tk.X, pady=(0, 12))

        tips_text = (
            u"1. Resolução Nativa: Sentinel-2 (10m) e Landsat (30m) sem qualquer perda.\n"
            u"2. Áreas Extensas (> 48 MB): Particionamento automático em quadrantes até 1:500.000 com resolução nativa estrita.\n"
            u"3. Buffer de AOI: Ajuste em 'Configurações' a margem em metros ao redor do vetor.\n"
            u"4. Simbologia e Bandas: Altere as bandas RGB no TOC diretamente com botão direito."
        )
        ttk.Label(tips_frame, text=tips_text, justify=tk.LEFT).pack(anchor=tk.W)

        btn_bar = ttk.Frame(pad)
        btn_bar.pack(fill=tk.X, side=tk.BOTTOM)

        btn_gh = ttk.Button(btn_bar, text=u"🌐 Abrir Repositório no GitHub", command=self._open_github)
        btn_gh.pack(side=tk.LEFT)

        btn_close = ttk.Button(btn_bar, text=u"Fechar", command=self.top.destroy)
        btn_close.pack(side=tk.RIGHT)

    def _open_github(self):
        try:
            webbrowser.open("https://github.com/Yiuky/arcgis-google-earth-engine-explorer")
        except Exception:
            pass

def safe_makedirs(path):
    if not path:
        return
    try:
        os.makedirs(path)
    except OSError:
        if not os.path.isdir(path):
            raise

class GEEUpdaterErrorDialog(object):
    """Janela modal amigável para exibição de falhas de atualização com orientações práticas de resolução"""
    def __init__(self, parent_win, exc):
        self.top = tk.Toplevel(parent_win)
        title_text = getattr(exc, 'title', None) or u"Falha na Atualização"
        self.top.title(title_text)
        self.top.geometry("540x380")
        self.top.resizable(False, False)
        setup_window_icon(self.top)
        self.top.transient(parent_win)
        self.top.grab_set()

        try:
            x = parent_win.winfo_rootx() + (parent_win.winfo_width() // 2) - 270
            y = parent_win.winfo_rooty() + (parent_win.winfo_height() // 2) - 190
            self.top.geometry("+%d+%d" % (max(0, x), max(0, y)))
        except Exception:
            pass

        pad = ttk.Frame(self.top, padding=16)
        pad.pack(fill=tk.BOTH, expand=True)

        hdr_frame = ttk.Frame(pad)
        hdr_frame.pack(fill=tk.X, pady=(0, 10))

        lbl_icon = tk.Label(hdr_frame, text=u"⚠️", font=("Segoe UI", 22), fg="#c0392b")
        lbl_icon.pack(side=tk.LEFT, padx=(0, 10))

        lbl_title = tk.Label(
            hdr_frame,
            text=title_text,
            font=("Segoe UI", 12, "bold"),
            fg="#c0392b",
            wraplength=440,
            justify=tk.LEFT
        )
        lbl_title.pack(side=tk.LEFT, fill=tk.X, expand=True)

        user_msg = getattr(exc, 'user_message', None) or str(exc)
        if sys.version_info[0] < 3 and isinstance(user_msg, str):
            try:
                user_msg = user_msg.decode("utf-8", "replace")
            except Exception:
                pass

        lbl_msg = ttk.Label(pad, text=user_msg, wraplength=500, justify=tk.LEFT)
        lbl_msg.pack(anchor=tk.W, pady=(0, 10))

        remediation = getattr(exc, 'remediation', None) or []
        if remediation:
            box_rem = ttk.LabelFrame(pad, text=u" 💡 O que você pode fazer para resolver: ", padding=10)
            box_rem.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
            rem_lines = []
            for idx, r in enumerate(remediation, 1):
                if sys.version_info[0] < 3 and isinstance(r, str):
                    try:
                        r = r.decode("utf-8", "replace")
                    except Exception:
                        pass
                rem_lines.append(u"%d. %s" % (idx, r))
            lbl_rem = ttk.Label(box_rem, text="\n".join(rem_lines), wraplength=470, justify=tk.LEFT)
            lbl_rem.pack(anchor=tk.W)

        bot_bar = ttk.Frame(pad)
        bot_bar.pack(fill=tk.X, side=tk.BOTTOM)

        def open_log():
            try:
                import gee_updater
                log_p = gee_updater.get_updater_log_path()
                if os.path.exists(log_p):
                    try:
                        os.startfile(log_p)
                    except Exception:
                        subprocess.Popen(["notepad.exe", log_p])
                else:
                    messagebox.showinfo(u"Log", u"Arquivo de log ainda não criado.", parent=self.top)
            except Exception as e_log:
                messagebox.showerror(u"Erro", str(e_log), parent=self.top)

        btn_log = ttk.Button(bot_bar, text=u"📄 Abrir Log de Diagnóstico", command=open_log)
        btn_log.pack(side=tk.LEFT)

        btn_ok = ttk.Button(bot_bar, text=u"Fechar", command=self.top.destroy)
        btn_ok.pack(side=tk.RIGHT)


class GEEUpdaterDialog(object):
    """Janela modal para atualização do plugin com pre-flight checks, backup e rollback automático"""
    def __init__(self, parent):
        self.parent = parent
        self.top = tk.Toplevel(parent.root if hasattr(parent, 'root') else parent)
        self.top.title(u"Atualização Segura - ArcMagery")
        self.top.geometry("560x420")
        self.top.resizable(False, False)
        setup_window_icon(self.top)
        self.top.transient(parent.root if hasattr(parent, 'root') else parent)
        self.top.grab_set()

        try:
            p_win = parent.root if hasattr(parent, 'root') else parent
            x = p_win.winfo_rootx() + (p_win.winfo_width() // 2) - 280
            y = p_win.winfo_rooty() + (p_win.winfo_height() // 2) - 210
            self.top.geometry("+%d+%d" % (max(0, x), max(0, y)))
        except Exception:
            pass

        pad = ttk.Frame(self.top, padding=16)
        pad.pack(fill=tk.BOTH, expand=True)

        lbl_head = tk.Label(
            pad,
            text=u"Atualização do ArcMagery (v%s)" % CURRENT_VERSION,
            font=("Segoe UI", 12, "bold"),
            fg="#1b4f72"
        )
        lbl_head.pack(anchor=tk.W, pady=(0, 4))

        lbl_desc = ttk.Label(
            pad,
            text=u"Sistema transacional com pré-validação, backup automático e proteção contra falhas."
        )
        lbl_desc.pack(anchor=tk.W, pady=(0, 10))

        # Método 1: GitHub Online
        box_git = ttk.LabelFrame(pad, text=u" Método 1: Atualização Online (GitHub Oficial) ", padding=10)
        box_git.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(
            box_git,
            text=u"Verifica conexão, valida alterações e atualiza os arquivos mantendo backup prévio."
        ).pack(anchor=tk.W, pady=(0, 6))

        self.btn_git_update = ttk.Button(box_git, text=u"⬇ Iniciar Atualização Online", command=self._do_github_update)
        self.btn_git_update.pack(anchor=tk.W)

        # Método 2: Arquivo ZIP Local
        box_zip = ttk.LabelFrame(pad, text=u" Método 2: Atualização Offline (Arquivo ZIP ou Add-In) ", padding=10)
        box_zip.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(
            box_zip,
            text=u"Instala nova versão via arquivo .zip ou .esriaddin com teste de integridade e Zip Slip."
        ).pack(anchor=tk.W, pady=(0, 6))

        self.btn_zip_update = ttk.Button(box_zip, text=u"📂 Selecionar Arquivo ZIP e Atualizar", command=self._do_zip_update)
        self.btn_zip_update.pack(anchor=tk.W)

        # Barra de progresso e status
        self.prog_bar = ttk.Progressbar(pad, mode="indeterminate")
        self.prog_bar.pack(fill=tk.X, pady=(6, 4))

        self.lbl_status = ttk.Label(pad, text=u"Pronto para verificar atualizações.", font=("Segoe UI", 8), foreground="#555")
        self.lbl_status.pack(anchor=tk.W, pady=(0, 8))

        # Rodapé com utilitários e fechar
        bot_frame = ttk.Frame(pad)
        bot_frame.pack(fill=tk.X, side=tk.BOTTOM)

        btn_log = ttk.Button(bot_frame, text=u"📄 Ver Log", command=self._open_log_file)
        btn_log.pack(side=tk.LEFT, padx=(0, 6))

        btn_backups = ttk.Button(bot_frame, text=u"📂 Pasta de Backups", command=self._open_backups_folder)
        btn_backups.pack(side=tk.LEFT)

        btn_close = ttk.Button(bot_frame, text=u"Fechar", command=self.top.destroy)
        btn_close.pack(side=tk.RIGHT)

    def _open_log_file(self):
        try:
            import gee_updater
            log_p = gee_updater.get_updater_log_path()
            if os.path.exists(log_p):
                try:
                    os.startfile(log_p)
                except Exception:
                    subprocess.Popen(["notepad.exe", log_p])
            else:
                messagebox.showinfo(u"Log", u"O arquivo de log ainda não foi criado.", parent=self.top)
        except Exception as e:
            messagebox.showerror(u"Erro", str(e), parent=self.top)

    def _open_backups_folder(self):
        try:
            import gee_updater
            b_dir = gee_updater.get_backups_dir()
            if os.path.exists(b_dir):
                os.startfile(b_dir)
            else:
                messagebox.showinfo(u"Backups", u"Nenhum backup realizado ainda.", parent=self.top)
        except Exception as e:
            messagebox.showerror(u"Erro", str(e), parent=self.top)

    def _set_busy(self, is_busy, status_text=u""):
        if is_busy:
            self.btn_git_update.config(state=tk.DISABLED)
            self.btn_zip_update.config(state=tk.DISABLED)
            self.prog_bar.start(10)
        else:
            self.btn_git_update.config(state=tk.NORMAL)
            self.btn_zip_update.config(state=tk.NORMAL)
            self.prog_bar.stop()

        if status_text:
            self.lbl_status.config(text=status_text)

    def _ask_confirmation_and_retry(self, ex, retry_fn, flags):
        """Trata gee_updater.ConfirmationRequired: pergunta ao usuario e repete com a flag."""
        self._set_busy(False, u"Aguardando confirmação do usuário...")
        msg = ex.user_message if isinstance(ex.user_message, unicode) else unicode(str(ex.user_message), 'utf-8', 'replace')
        if messagebox.askyesno(ex.title, msg, parent=self.top, icon=messagebox.WARNING):
            new_flags = dict(flags)
            new_flags[ex.flag] = True
            retry_fn(**new_flags)
        else:
            self._set_busy(False, u"Atualização cancelada pelo usuário.")

    def _do_zip_update(self, zip_path=None, **flags):
        if not zip_path:
            zip_path = filedialog.askopenfilename(
                title=u"Selecione o arquivo ZIP de atualização do Plugin",
                filetypes=[("Arquivos ZIP ou Add-In (*.zip;*.esriaddin)", "*.zip;*.esriaddin"), ("Todos os arquivos (*.*)", "*.*")],
                parent=self.top
            )
        if not zip_path or not os.path.exists(zip_path):
            return

        self._set_busy(True, u"Iniciando validação prévia do arquivo ZIP...")

        def worker():
            try:
                import gee_updater

                def on_progress(step_msg):
                    def update_ui():
                        self.lbl_status.config(text=step_msg)
                    self.top.after(0, update_ui)

                # Executa pre-flight checks, backup, staging e despacho desacoplado com rollback
                gee_updater.execute_zip_update_flow(
                    zip_path,
                    current_version=CURRENT_VERSION,
                    progress_callback=on_progress,
                    **flags
                )

                # Notifica o usuário e encerra o processo da interface
                def show_success_and_exit():
                    messagebox.showinfo(
                        u"Validação Concluída com Sucesso",
                        u"O pacote foi validado e o backup de segurança foi criado!\n\n"
                        u"A interface gráfica será encerrada agora para que os arquivos sejam "
                        u"atualizados sem conflitos de arquivo.\n\n"
                        u"Uma notificação do Windows confirmará o término da instalação.",
                        parent=self.top
                    )
                    try:
                        self.top.destroy()
                    except Exception:
                        pass
                    try:
                        if hasattr(self.parent, 'root'):
                            self.parent.root.destroy()
                    except Exception:
                        pass
                    sys.exit(0)

                self.top.after(0, show_success_and_exit)

            except Exception as ex:
                import gee_updater as _gu
                if isinstance(ex, _gu.ConfirmationRequired):
                    self.top.after(0, lambda: self._ask_confirmation_and_retry(
                        ex, lambda **f: self._do_zip_update(zip_path=zip_path, **f), flags))
                    return
                def show_err():
                    self._set_busy(False, u"Falha na validação da atualização.")
                    GEEUpdaterErrorDialog(self.top, ex)
                self.top.after(0, show_err)

        threading.Thread(target=worker).start()

    def _do_github_update(self, **flags):
        self._set_busy(True, u"Conectando ao GitHub para verificar atualizações...")

        def worker():
            try:
                import gee_updater

                def on_progress(step_msg):
                    def update_ui():
                        self.lbl_status.config(text=step_msg)
                    self.top.after(0, update_ui)

                gee_updater.execute_online_github_update_flow(
                    current_version=CURRENT_VERSION,
                    progress_callback=on_progress,
                    **flags
                )

                def show_success_and_exit():
                    messagebox.showinfo(
                        u"Validação Concluída com Sucesso",
                        u"A nova versão foi baixada, validada e o backup foi gerado com sucesso!\n\n"
                        u"A interface será fechada para finalizar a aplicação das alterações.\n\n"
                        u"Uma mensagem do sistema confirmará a conclusão em instantes.",
                        parent=self.top
                    )
                    try:
                        self.top.destroy()
                    except Exception:
                        pass
                    try:
                        if hasattr(self.parent, 'root'):
                            self.parent.root.destroy()
                    except Exception:
                        pass
                    sys.exit(0)

                self.top.after(0, show_success_and_exit)

            except Exception as ex:
                import gee_updater as _gu
                if isinstance(ex, _gu.ConfirmationRequired):
                    self.top.after(0, lambda: self._ask_confirmation_and_retry(ex, self._do_github_update, flags))
                    return
                def show_err():
                    self._set_busy(False, u"Falha na atualização pelo GitHub.")
                    GEEUpdaterErrorDialog(self.top, ex)
                self.top.after(0, show_err)

        threading.Thread(target=worker).start()


CURRENT_VERSION = "2.3.2"
APP_NAME = u"ArcMagery"
APP_WINDOW_TITLE = u"ArcMagery (ArcGIS 10.8)  |  v" + CURRENT_VERSION

SENSOR_METADATA = {
    'S2': {
        'name': u'Sentinel-2 (MSI)',
        'agency': u'ESA / Copernicus',
        'collection': 'COPERNICUS/S2_SR_HARMONIZED',
        'period_start': '28/03/2017',
        'period_end': u'Presente (Ativo)',
        'period_display': u'28/03/2017 até o Presente (Ativo)',
        'start_year': 2017,
        'end_year': None,
        'res': '10m / 20m',
        'available_bands': u"B1, B2, B3, B4, B5, B6, B7, B8, B8A, B9, B11, B12",
        'default_dates': ('30d', None),
        'notes': u'Refletância de Superfície (Nível 2A Harmonizado), bandas de 10m e 20m.'
    },
    'L8': {
        'name': u'Landsat 8 & 9 (OLI / TIRS)',
        'agency': u'USGS / NASA',
        'collection': 'LANDSAT/LC08/C02/T1_L2 (+ LC09)',
        'period_start': '11/04/2013',
        'period_end': u'Presente (Ativo)',
        'period_display': u'11/04/2013 até o Presente (L8: 2013+ | L9: 2021+)',
        'start_year': 2013,
        'end_year': None,
        'res': '30m',
        'available_bands': u"SR_B1 a SR_B7, ST_B10 (aceita B1 a B7)",
        'default_dates': ('30d', None),
        'notes': u'Refletância de Superfície USGS Col. 2 Nível 2 (L8 e L9 unificados).'
    },
    'L7': {
        'name': u'Landsat 7 (ETM+)',
        'agency': u'USGS / NASA',
        'collection': 'LANDSAT/LE07/C02/T1_L2',
        'period_start': '15/04/1999',
        'period_end': u'Presente (Ativo)',
        'period_display': u'15/04/1999 até o Presente (SLC-off após 31/05/2003)',
        'start_year': 1999,
        'end_year': None,
        'res': '30m',
        'available_bands': u"SR_B1 a SR_B5, SR_B7, ST_B6 (aceita B1 a B7)",
        'default_dates': ('30d', None),
        'notes': u'Atenção: falha mecânica no corretor de linhas (SLC-off) a partir de 31/05/2003.'
    },
    'L5': {
        'name': u'Landsat 5 (TM)',
        'agency': u'USGS / NASA',
        'collection': 'LANDSAT/LT05/C02/T1_L2',
        'period_start': '01/03/1984',
        'period_end': '05/05/2012',
        'period_display': u'01/03/1984 até 05/05/2012 (Missão Concluída)',
        'start_year': 1984,
        'end_year': 2012,
        'res': '30m',
        'available_bands': u"SR_B1 a SR_B5, SR_B7, ST_B6 (aceita B1 a B7)",
        'default_dates': ('01/06/2011', '30/09/2011'),
        'notes': u'Série histórica TM de 28 anos. Calibração geométrica e radiométrica Col. 2.'
    },
    'L4': {
        'name': u'Landsat 4 (TM)',
        'agency': u'USGS / NASA',
        'collection': 'LANDSAT/LT04/C02/T1_L2',
        'period_start': '16/07/1982',
        'period_end': '14/12/1993',
        'period_display': u'16/07/1982 até 14/12/1993 (Missão Concluída)',
        'start_year': 1982,
        'end_year': 1993,
        'res': '30m',
        'available_bands': u"SR_B1 a SR_B5, SR_B7, ST_B6 (aceita B1 a B7)",
        'default_dates': ('01/06/1990', '30/09/1990'),
        'notes': u'Série histórica TM preliminar. Disponibilidade intermitente de dados.'
    },
    'L3': {
        'name': u'Landsat 3 (MSS)',
        'agency': u'USGS / NASA',
        'collection': 'LANDSAT/LM03/C02/T1 + T2',
        'period_start': '05/03/1978',
        'period_end': '31/03/1983',
        'period_display': u'05/03/1978 até 31/03/1983 (Missão Concluída)',
        'start_year': 1978,
        'end_year': 1983,
        'res': '60m',
        'available_bands': u"B4, B5, B6, B7",
        'default_dates': ('01/06/1980', '30/09/1980'),
        'notes': u'Sensor MSS (Bandas B4, B5, B6, B7). Resolução espacial nativa de 60m.'
    },
    'L2': {
        'name': u'Landsat 2 (MSS)',
        'agency': u'USGS / NASA',
        'collection': 'LANDSAT/LM02/C02/T1 + T2',
        'period_start': '22/01/1975',
        'period_end': '25/02/1982',
        'period_display': u'22/01/1975 até 25/02/1982 (Missão Concluída)',
        'start_year': 1975,
        'end_year': 1982,
        'res': '60m',
        'available_bands': u"B4, B5, B6, B7",
        'default_dates': ('01/06/1977', '30/09/1977'),
        'notes': u'Sensor MSS (Bandas B4, B5, B6, B7). Resolução espacial nativa de 60m.'
    },
    'L1': {
        'name': u'Landsat 1 (MSS)',
        'agency': u'USGS / NASA',
        'collection': 'LANDSAT/LM01/C02/T1 + T2',
        'period_start': '23/07/1972',
        'period_end': '06/01/1978',
        'period_display': u'23/07/1972 até 06/01/1978 (Missão Concluída)',
        'start_year': 1972,
        'end_year': 1978,
        'res': '60m',
        'available_bands': u"B4, B5, B6, B7",
        'default_dates': ('01/06/1975', '30/09/1975'),
        'notes': u'Primeiro satélite de observação civil da Terra. Sensor MSS 60m.'
    }
}

SENSOR_DISPLAY = [
    (u"Sentinel-2 (MSI - Nível 2A Harmonizado)", "S2"),
    (u"Landsat 8 & 9 (OLI/TIRS - Col. 2 L2)", "L8"),
    (u"Landsat 7 (ETM+ - Col. 2 L2)", "L7"),
    (u"Landsat 5 (TM - Col. 2 L2)", "L5"),
    (u"Landsat 4 (TM - Col. 2 L2)", "L4"),
    (u"Landsat 3 (MSS - Col. 2 T1/T2)", "L3"),
    (u"Landsat 2 (MSS - Col. 2 T1/T2)", "L2"),
    (u"Landsat 1 (MSS - Col. 2 T1/T2)", "L1")
]

MAX_ALLOWED_SCALE = 500000.0

def normalize_date(d_str):
    if not d_str:
        return ""
    d_str = str(d_str).strip()
    import re
    m = re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$", d_str)
    if m:
        day, month, year = m.groups()
        return "%04d-%02d-%02d" % (int(year), int(month), int(day))
    m2 = re.match(r"^(\d{4})[/.-](\d{1,2})[/.-](\d{1,2})$", d_str)
    if m2:
        year, month, day = m2.groups()
        return "%04d-%02d-%02d" % (int(year), int(month), int(day))
    return d_str

class GEEPluginWindow(object):
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(APP_WINDOW_TITLE)
        self.root.geometry("1100x740")
        self.root.minsize(960, 640)
        setup_window_icon(self.root)

        # Interceptar fechamento da janela
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # Fila de comunicacao interna da GUI
        self.queue = queue_mod.Queue()
        self._alive = True
        self.arcmap_context = {}

        # Configuracao visual ttk
        self.style = ttk.Style()
        try:
            self.style.theme_use('clam')
        except Exception:
            pass

        self.style.configure("TLabel", font=("Segoe UI", 9))
        self.style.configure("TButton", font=("Segoe UI", 9))
        self.style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), foreground="#0b5345")
        self.style.configure("Action.TButton", font=("Segoe UI", 9, "bold"), foreground="#1a5276")

        try:
            self.max_system_cores = multiprocessing.cpu_count()
        except Exception:
            self.max_system_cores = 4

        self.is_authenticated = False
        self.images_cache = []
        self.is_downloading = False
        self.download_thread = None
        self.download_queue = queue_mod.Queue()
        self.download_worker_thread = None
        self.queued_ids = set()
        self.current_downloading_ids = set()
        self._queue_lock = threading.Lock()
        self._active_search_token = 0
        self.ipc_lock = threading.Lock()
        self.settings = gee_bridge.load_plugin_settings()

        self.setup_ui()
        self.populate_initial_data()

        # Iniciar verificacoes em segundo plano de forma diferida
        self.root.after(100, self._deferred_init)

    def on_close(self):
        """Encerra o processo da GUI de forma limpa"""
        try:
            self._alive = False
            hb_file = gee_bridge.HEARTBEAT_FILE
            if os.path.exists(hb_file):
                try:
                    os.remove(hb_file)
                except Exception:
                    pass
            self.root.destroy()
        except Exception:
            pass
        sys.exit(0)

    def on_open_extra_sources(self):
        """Abre (ou traz para frente) a janela Google Earth / XYZ e CBERS / INPE."""
        try:
            dlg = getattr(self, '_sources_dlg', None)
            if dlg is not None and dlg.top.winfo_exists():
                dlg.top.deiconify()
                dlg.top.lift()
                return
            import arcmagery_sources_gui
            self._sources_dlg = arcmagery_sources_gui.ExtraSourcesDialog(self)
        except Exception as e:
            messagebox.showerror(u"ArcMagery", u"Falha ao abrir as fontes adicionais: %s" % e, parent=self.root)

    def post_to_gui(self, callback):
        """Envia uma acao para ser executada na thread principal do Tkinter"""
        if self._alive:
            self.queue.put(callback)

    def ui_call(self, fn, timeout=900):
        """Executa fn na thread do Tk e devolve o resultado ao chamador (worker thread).
        Tkinter nao e thread-safe: workers nunca devem tocar widgets diretamente."""
        if threading.current_thread().name == 'MainThread':
            return fn()
        done = threading.Event()
        box = {}

        def run():
            try:
                box['value'] = fn()
            except Exception as e:
                box['error'] = e
            finally:
                done.set()

        self.post_to_gui(run)
        if not done.wait(timeout):
            raise RuntimeError(u"Tempo esgotado aguardando a interface.")
        if 'error' in box:
            raise box['error']
        return box.get('value')

    def _mb(self, kind, *args, **kwargs):
        """messagebox.<kind>(...) seguro a partir de qualquer thread."""
        return self.ui_call(lambda: getattr(messagebox, kind)(*args, **kwargs))

    def _schedule_poll(self):
        if self._alive:
            self.root.after(100, self._process_queue)

    def _process_queue(self):
        """Processa mensagens internas da fila de tarefas"""
        if not self._alive:
            return
        try:
            while True:
                cb = self.queue.get_nowait()
                try:
                    cb()
                except Exception as e:
                    print("Erro executando item da fila:", e)
        except queue_mod.Empty:
            pass
        except Exception:
            pass

        # Watchdog: verificar se thread de download terminou e destravar botoes da interface
        if getattr(self, 'is_downloading', False):
            d_worker = getattr(self, 'download_worker_thread', None)
            d_single = getattr(self, 'download_thread', None)
            worker_alive = (d_worker is not None and d_worker.is_alive())
            single_alive = (d_single is not None and d_single.is_alive())
            q_empty = hasattr(self, 'download_queue') and self.download_queue.empty()
            if not worker_alive and not single_alive and q_empty:
                self.is_downloading = False
                self.download_worker_thread = None
                self.download_thread = None
                if hasattr(self, 'queued_ids'):
                    self.queued_ids.clear()
                if hasattr(self, 'current_downloading_ids'):
                    self.current_downloading_ids.clear()
                self.update_action_buttons_state()

        if self._alive:
            self._schedule_poll()

    def set_progress(self, percent, text=None):
        """Atualiza a barra de progresso, percentual e mensagem de status de forma segura na GUI"""
        def _update():
            if percent is not None and hasattr(self, 'pbar') and hasattr(self, 'lbl_pct'):
                p = max(0, min(100, int(percent)))
                self.pbar['value'] = p
                self.lbl_pct.config(text="%d%%" % p)
            if text and hasattr(self, 'lbl_progress'):
                self.lbl_progress.config(text=text)
        self.post_to_gui(_update)

    def set_row_status(self, img_id_or_short_name, status_text, tag=None):
        """Atualiza a coluna de status de uma linha especifica na tabela de imagens"""
        def _update():
            if not hasattr(self, 'tree'):
                return
            children = self.tree.get_children()
            target_str = unicode(img_id_or_short_name).strip() if sys.version_info[0] < 3 else str(img_id_or_short_name).strip()
            for idx, item in enumerate(children):
                if idx < len(self.images_cache):
                    img_data = self.images_cache[idx]
                    cid = img_data.get('id', '')
                    cname = img_data.get('name') or cid.split('/')[-1]
                    if cid == target_str or cname == target_str or cid.endswith(target_str) or target_str.endswith(cname):
                        self.tree.set(item, "status", status_text)
                        if tag:
                            self.tree.item(item, tags=(tag,))
                        elif status_text == u"✓ Carregado":
                            self.tree.item(item, tags=("loaded",))
                        elif u"Na Fila" in status_text:
                            self.tree.item(item, tags=("queued",))
                        elif u"..." in status_text or u"Baixando" in status_text:
                            self.tree.item(item, tags=("downloading",))
                        elif u"Erro" in status_text or u"Falha" in status_text:
                            self.tree.item(item, tags=("error",))
                        else:
                            self.tree.item(item, tags=())
                        break
        self.post_to_gui(_update)

    def check_image_loaded_status(self, short_name):
        """Verifica se uma cena ja esta presente em qualquer camada raster do TOC do ArcMap"""
        try:
            rasters = self.arcmap_context.get('raster_layers', [])
            target = unicode(short_name).strip().lower() if sys.version_info[0] < 3 else str(short_name).strip().lower()
            for r in rasters:
                r_layer = r.split('\\')[-1].strip().lower()
                if r_layer == target or r_layer.startswith(target) or target in r_layer:
                    return u"✓ Carregado"
        except Exception:
            pass
        return u"-"

    def refresh_tree_status_columns(self):
        """Atualiza a coluna de status de todas as imagens listadas na tabela com base no TOC atual"""
        if not hasattr(self, 'tree') or not self.images_cache:
            return
        children = self.tree.get_children()
        for idx, item in enumerate(children):
            if idx < len(self.images_cache):
                cur_status = self.tree.set(item, "status")
                if cur_status == u"Baixando..." or cur_status == u"Na Fila":
                    continue
                img_data = self.images_cache[idx]
                sname = img_data.get('name') or img_data.get('id', '').split('/')[-1]
                new_st = self.check_image_loaded_status(sname)
                self.tree.set(item, "status", new_st)
                if new_st == u"✓ Carregado":
                    self.tree.item(item, tags=("loaded",))
                else:
                    self.tree.item(item, tags=())

    def find_existing_layer_in_group(self, short_name, comp, group_name):
        """Verifica se uma cena ja existe carregada no grupo alvo do ArcMap.
        Retorna o longName da camada existente se encontrada, ou None.
        Camadas de pré-visualização (previa_) sao explicitamente ignoradas.
        """
        try:
            self.sync_arcmap_context()
            rasters = self.arcmap_context.get('raster_layers', [])
            target_short = unicode(short_name).strip().lower() if sys.version_info[0] < 3 else str(short_name).strip().lower()
            target_title = ("%s_%s" % (short_name, comp)).lower()
            target_grp = unicode(group_name).strip().lower() if (group_name and unicode(group_name).strip()) else None

            for r in rasters:
                if "\\" in r:
                    parts = r.split("\\")
                    r_group = parts[0].strip().lower()
                    r_layer = parts[-1].strip().lower()
                else:
                    r_group = None
                    r_layer = r.strip().lower()

                # Ignorar pré-visualizações para nao confundir com a imagem final
                if r_layer.startswith("previa_") or (r_group and "pre-visualizacoes" in r_group):
                    continue

                group_matches = False
                if target_grp:
                    if r_group and r_group == target_grp:
                        group_matches = True
                else:
                    if r_group is None:
                        group_matches = True

                if group_matches:
                    if r_layer == target_title or r_layer == target_short or r_layer.startswith(target_short):
                        return r  # Retorna o longName original para replace_layer
        except Exception as e:
            print("Erro verificando camada existente no grupo:", e)
        return None

    def update_action_buttons_state(self):
        """Gerencia de forma centralizada e sem efeitos colaterais o estado
        de todos os botoes de acao conforme a selecao da tabela e o status de download."""
        try:
            # 1. Watchdog das threads de download e worker da fila
            worker_alive = hasattr(self, 'download_worker_thread') and self.download_worker_thread is not None and self.download_worker_thread.is_alive()
            single_alive = hasattr(self, 'download_thread') and self.download_thread is not None and self.download_thread.is_alive()
            q_empty = hasattr(self, 'download_queue') and self.download_queue.empty()
            if not worker_alive and not single_alive and q_empty:
                self.is_downloading = False
                self.download_worker_thread = None
                self.download_thread = None

            # 2. Obter contagem de itens selecionados
            selected_ids = self.get_all_selected_image_ids() if hasattr(self, 'tree') else []
            count = len(selected_ids)

            # 3. Verificar raster no TOC
            has_toc_raster = False
            is_single_layer = False
            cur_toc = ""
            if hasattr(self, 'cbo_toc_rasters'):
                cur_toc = self.cbo_toc_rasters.get().strip()
                if cur_toc and cur_toc not in (u"Nenhuma camada raster no TOC", u"Nenhuma camada encontrada"):
                    has_toc_raster = True
                    if not cur_toc.startswith(u"[Todo o TOC]") and not cur_toc.startswith(u"[Grupo]"):
                        is_single_layer = True

            is_dl = getattr(self, 'is_downloading', False)

            # 4. Botao Carregar / Enfileirar no ArcMap
            if hasattr(self, 'btn_add_toc'):
                if is_dl:
                    self.btn_add_toc.config(
                        text=u"[ + Adicionar à Fila ]",
                        state=tk.NORMAL if count >= 1 else tk.DISABLED
                    )
                else:
                    self.btn_add_toc.config(
                        text=u"[ Carregar no ArcMap ]",
                        state=tk.NORMAL if count >= 1 else tk.DISABLED
                    )

            # 5. Botao Substituir no TOC (apenas camada individual)
            if hasattr(self, 'btn_replace_toc'):
                if is_dl:
                    self.btn_replace_toc.config(
                        text=u"[ + Enfileirar Substituição ]",
                        state=tk.NORMAL if (count == 1 and is_single_layer) else tk.DISABLED
                    )
                else:
                    self.btn_replace_toc.config(
                        text=u"[ Substituir no TOC ]",
                        state=tk.NORMAL if (count == 1 and is_single_layer) else tk.DISABLED
                    )

            if hasattr(self, 'btn_thumb'):
                self.btn_thumb.config(state=tk.NORMAL if count == 1 else tk.DISABLED)


        except Exception as e:
            print("Erro ao atualizar estado dos botoes:", e)

    def _deferred_init(self):
        self._schedule_poll()
        self.sync_arcmap_context()
        self.async_check_gee()
        self.root.after(2000, self._poll_arcmap_context)
        self.root.after(2500, self._start_startup_update_check)

    def _start_startup_update_check(self):
        t = threading.Thread(target=self._async_check_update_on_startup)
        t.daemon = True
        t.start()

    def _async_check_update_on_startup(self):
        """Verifica silenciosamente no GitHub se existe uma nova versão ou commit do projeto."""
        try:
            curr = os.path.dirname(os.path.abspath(__file__))
            p = os.path.abspath(os.path.join(curr, "..", ".."))
            root_dir = p if os.path.exists(os.path.join(p, "arcgis_addin")) else curr
        except Exception:
            root_dir = None

        has_update = False
        update_info = ""

        # 1. Checagem via commit SHA do GitHub se o repositório Git existir
        git_dir = os.path.join(root_dir, ".git") if root_dir else None
        if git_dir and os.path.exists(git_dir):
            try:
                import subprocess
                p = subprocess.Popen(["git", "rev-parse", "HEAD"], cwd=root_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                local_sha, _ = p.communicate()
                local_sha = local_sha.decode('utf-8', 'ignore').strip()
            except Exception:
                local_sha = None

            if local_sha:
                try:
                    if sys.version_info[0] < 3:
                        import urllib2
                        req = urllib2.Request(
                            "https://api.github.com/repos/Yiuky/arcgis-google-earth-engine-explorer/commits/main",
                            headers={'User-Agent': 'ArcMagery-UpdateCheck'}
                        )
                        res = urllib2.urlopen(req, timeout=5)
                        import json
                        remote_data = json.loads(res.read())
                    else:
                        import urllib.request
                        import json
                        req = urllib.request.Request(
                            "https://api.github.com/repos/Yiuky/arcgis-google-earth-engine-explorer/commits/main",
                            headers={'User-Agent': 'ArcMagery-UpdateCheck'}
                        )
                        res = urllib.request.urlopen(req, timeout=5)
                        remote_data = json.loads(res.read().decode('utf-8'))

                    remote_sha = remote_data.get('sha', '').strip()
                    commit_msg = remote_data.get('commit', {}).get('message', '').splitlines()[0]

                    if remote_sha and local_sha and remote_sha != local_sha:
                        has_update = True
                        update_info = u"Novo commit no GitHub: %s (%s...)" % (commit_msg, remote_sha[:7])
                except Exception:
                    pass

        # 2. Checagem de versão no config.xml remoto caso commit não tenha apontado ou não use git
        if not has_update:
            try:
                raw_url = "https://raw.githubusercontent.com/Yiuky/arcgis-google-earth-engine-explorer/main/arcgis_addin/config.xml?t=%d" % int(time.time())
                hdrs = {'User-Agent': 'ArcMagery-UpdateCheck', 'Cache-Control': 'no-cache', 'Pragma': 'no-cache'}
                if sys.version_info[0] < 3:
                    import urllib2
                    req = urllib2.Request(raw_url, headers=hdrs)
                    res = urllib2.urlopen(req, timeout=5)
                    xml_content = res.read()
                else:
                    import urllib.request
                    req = urllib.request.Request(raw_url, headers=hdrs)
                    res = urllib.request.urlopen(req, timeout=5)
                    xml_content = res.read().decode('utf-8')

                import re
                m = re.search(r'<Version>(.*?)</Version>', xml_content)
                if m:
                    remote_ver = m.group(1).strip()
                    def ver_tuple(v):
                        return [int(x) for x in re.findall(r'\d+', v)]
                    if ver_tuple(remote_ver) > ver_tuple(CURRENT_VERSION):
                        has_update = True
                        update_info = u"Nova versão v%s disponível (versão atual: v%s)" % (remote_ver, CURRENT_VERSION)
            except Exception:
                pass

        if has_update and self._alive:
            def notify_user():
                if not self._alive:
                    return
                # Mostrar botão de atualização em destaque na barra de topo
                if hasattr(self, 'btn_update_notify'):
                    self.btn_update_notify.pack(side=tk.RIGHT, padx=6)
                if hasattr(self, 'lbl_progress'):
                    self.lbl_progress.config(
                        text=u"🚀 Nova atualização disponível no GitHub! Clique no botão superior para atualizar."
                    )
                # Notificar o usuário com opção de abrir o atualizador imediatamente
                resp = messagebox.askyesno(
                    u"Nova Atualização Disponível",
                    u"Uma nova atualização do ArcMagery foi detectada no repositório oficial!\n\n"
                    u"%s\n\nDeseja abrir o assistente de atualização agora para aplicar?" % update_info,
                    parent=self.root
                )
                if resp:
                    self.on_open_updater()

            self.post_to_gui(notify_user)

    def _poll_arcmap_context(self):
        """Sincroniza periodicamente com o contexto do ArcMap (escala, camadas)"""
        if not self._alive:
            return
        try:
            hb_file = gee_bridge.HEARTBEAT_FILE
            with open(hb_file, "w") as f:
                f.write(str(time.time()))
        except Exception:
            pass
        self.sync_arcmap_context()
        if self._alive:
            self.root.after(350, self._poll_arcmap_context)

    def sync_arcmap_context(self):
        ctx = gee_bridge.read_arcmap_context()
        if ctx:
            old_time = self.arcmap_context.get('time', 0)
            new_time = ctx.get('time', 0)
            self.arcmap_context = ctx
            self.update_map_scale_display()

            if new_time != old_time:
                # Atualizar lista de alvos (TOC / Grupos / Camadas) se houver novidades
                r_layers = ctx.get('raster_layers', [])
                grp_list = ctx.get('groups_with_rasters', [])
                targets = gee_bridge.build_toc_targets(r_layers, grp_list)

                cur = self.cbo_toc_rasters.get() if hasattr(self, 'cbo_toc_rasters') else ""
                if hasattr(self, 'cbo_toc_rasters'):
                    self.cbo_toc_rasters['values'] = targets
                    sel_target = ctx.get('selected_target')
                    if sel_target and sel_target in targets and (not cur or cur in (u"Nenhuma camada raster no TOC", u"")):
                        self.cbo_toc_rasters.set(sel_target)
                    elif cur and cur in targets:
                        self.cbo_toc_rasters.set(cur)
                    elif targets:
                        self.cbo_toc_rasters.current(0)
                    self.update_action_buttons_state()

                # Atualizar camadas vetoriais
                vectors = ctx.get('vector_layers', [])
                if hasattr(self, 'cbo_layers'):
                    if vectors and (not self.cbo_layers['values'] or self.cbo_layers['values'][0] == "Nenhuma camada encontrada"):
                        self.cbo_layers['values'] = vectors
                        self.cbo_layers.current(0)

    def setup_ui(self):
        # 1. Barra de Topo: Status de Conexao, Projeto e Escala Atual
        self.top_frame = tk.Frame(self.root, bg="#fcf3cf", padx=10, pady=6, relief=tk.GROOVE, bd=1)
        self.top_frame.pack(fill=tk.X, side=tk.TOP, padx=6, pady=4)

        # Icone simples e nitido da aplicacao na barra superior (a esquerda de v1.5)
        self.top_icon_img = get_tk_image("icon24") or get_tk_image("icon20") or get_tk_image("icon16")
        if self.top_icon_img:
            self.lbl_top_ico = tk.Label(self.top_frame, image=self.top_icon_img, bg="#fcf3cf", bd=0)
            self.lbl_top_ico.pack(side=tk.LEFT, padx=(0, 6))

        # Badge de Versao bem visivel
        self.lbl_v_badge = tk.Label(
            self.top_frame,
            text=u" v%s " % CURRENT_VERSION,
            font=("Segoe UI", 9, "bold"),
            bg="#1b4f72",
            fg="#ffffff",
            relief=tk.RIDGE,
            bd=1,
            padx=4,
            pady=1
        )
        self.lbl_v_badge.pack(side=tk.LEFT, padx=(0, 8))

        self.lbl_status_icon = tk.Label(self.top_frame, text="[*]", font=("Segoe UI", 10, "bold"), bg="#fcf3cf", fg="#7d6608")
        self.lbl_status_icon.pack(side=tk.LEFT, padx=(2, 6))

        self.lbl_status = tk.Label(
            self.top_frame,
            text=u"Verificando conexao com Google Earth Engine...",
            font=("Segoe UI", 9, "bold"),
            bg="#fcf3cf",
            fg="#7d6608"
        )
        self.lbl_status.pack(side=tk.LEFT, padx=2)

        # Indicador de Escala na barra superior
        self.lbl_scale_info = tk.Label(
            self.top_frame,
            text=u"| Escala: Verificando...",
            font=("Segoe UI", 9),
            bg="#fcf3cf",
            fg="#1b4f72"
        )
        self.lbl_scale_info.pack(side=tk.LEFT, padx=10)

        self.btn_about = ttk.Button(self.top_frame, text=u"ℹ Sobre", command=self.on_open_about)
        self.btn_about.pack(side=tk.RIGHT, padx=4)


        self.btn_settings = ttk.Button(self.top_frame, text=u"⚙ Configurações", command=self.on_open_settings)
        self.btn_settings.pack(side=tk.RIGHT, padx=4)

        btn_fit_scale = ttk.Button(self.top_frame, text="Ajustar 1:500.000", command=self.on_fit_scale_clicked)
        btn_fit_scale.pack(side=tk.RIGHT, padx=4)

        self.btn_check_auth = ttk.Button(self.top_frame, text="Verificar Conexao", command=self.async_check_gee)
        self.btn_check_auth.pack(side=tk.RIGHT, padx=4)

        self.btn_auth = ttk.Button(self.top_frame, text="Configurar Projeto GEE", command=self.on_configure_project)
        self.btn_auth.pack(side=tk.RIGHT, padx=4)

        # Botão/Badge de Notificação de Nova Atualização (exibido se houver update no GitHub)
        self.btn_update_notify = tk.Button(
            self.top_frame,
            text=u"🚀 Nova Atualização Disponível!",
            font=("Segoe UI", 9, "bold"),
            bg="#c0392b",
            fg="#ffffff",
            activebackground="#962d22",
            activeforeground="#ffffff",
            relief=tk.RAISED,
            bd=2,
            padx=8,
            pady=1,
            cursor="hand2",
            command=self.on_open_updater
        )

        # 1b. Barra "Fonte de imagens": GEE e INPE usam a mesma janela; Google Earth/XYZ abre o seu painel
        source_bar = tk.Frame(self.root, bg="#eaf2f8", padx=10, pady=5, relief=tk.GROOVE, bd=1)
        source_bar.pack(fill=tk.X, side=tk.TOP, padx=6, pady=(0, 2))
        tk.Label(source_bar, text=u"Fonte de imagens:", font=("Segoe UI", 9, "bold"),
                 bg="#eaf2f8", fg="#1b4f72").pack(side=tk.LEFT, padx=(0, 8))
        self.var_source = tk.StringVar(value="gee")
        for value, text in (("gee", u"Google Earth Engine (Sentinel-2 / Landsat)"),
                            ("inpe", u"CBERS / Amazônia-1 (INPE)")):
            tk.Radiobutton(source_bar, text=text, variable=self.var_source, value=value, indicatoron=0,
                           font=("Segoe UI", 9), padx=10, pady=2, selectcolor="#aed6f1", bg="#fdfefe",
                           command=self.on_source_changed).pack(side=tk.LEFT, padx=2)
        self.btn_sources = ttk.Button(source_bar, text=u"Google Earth / Mosaicos XYZ...", style="Action.TButton",
                                      command=self.on_open_extra_sources)
        self.btn_sources.pack(side=tk.LEFT, padx=(12, 2))

        # 2. Painel Central Dividido (PanedWindow)
        middle_paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        middle_paned.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)

        # --- PAINEL ESQUERDO: PARAMETROS ---
        left_frame = ttk.LabelFrame(middle_paned, text=u" 1. Parametros e Bandas ", padding=10)
        middle_paned.add(left_frame, weight=1)

        # Satelite
        ttk.Label(left_frame, text=u"Satélite / Sensor:", font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky=tk.W, pady=2)
        self.var_sensor = tk.StringVar(value="S2")
        self.cbo_sensor = ttk.Combobox(left_frame, textvariable=self.var_sensor, state="readonly", width=34)
        self.cbo_sensor['values'] = [item[0] for item in SENSOR_DISPLAY]
        self.cbo_sensor.current(0)
        self.cbo_sensor.bind("<<ComboboxSelected>>", self.on_sensor_changed)
        self.cbo_sensor.grid(row=1, column=0, columnspan=2, sticky=tk.EW, pady=(0, 4))

        # Quadro Informativo do Sensor Selecionado (Período Operacional, Resolução e Fonte GEE)
        self.sensor_info_frame = tk.Frame(left_frame, bg="#eaf2f8", bd=1, relief=tk.SOLID, padx=6, pady=4)
        self.sensor_info_frame.grid(row=2, column=0, columnspan=2, sticky=tk.EW, pady=(0, 6))

        self.lbl_sensor_period = tk.Label(
            self.sensor_info_frame,
            text=u"📅 Período: 28/03/2017 até o Presente (Ativo)",
            font=("Segoe UI", 8, "bold"),
            bg="#eaf2f8",
            fg="#1a5276",
            anchor=tk.W,
            justify=tk.LEFT
        )
        self.lbl_sensor_period.pack(fill=tk.X, anchor=tk.W)

        self.lbl_sensor_detail = tk.Label(
            self.sensor_info_frame,
            text=u"📡 GEE: COPERNICUS/S2_SR_HARMONIZED (ESA | 10m / 20m)",
            font=("Segoe UI", 7),
            bg="#eaf2f8",
            fg="#2c3e50",
            anchor=tk.W,
            justify=tk.LEFT
        )
        self.lbl_sensor_detail.pack(fill=tk.X, anchor=tk.W)

        self.lbl_sensor_bands = tk.Label(
            self.sensor_info_frame,
            text=u"🌈 Bandas: B1, B2, B3, B4, B5, B6, B7, B8, B8A, B9, B11, B12",
            font=("Segoe UI", 7, "bold"),
            bg="#eaf2f8",
            fg="#117864",
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=250
        )
        self.lbl_sensor_bands.pack(fill=tk.X, anchor=tk.W, pady=(2, 0))

        # Composicao de Bandas
        ttk.Label(left_frame, text="Composicao / Multibanda:", font=("Segoe UI", 9, "bold")).grid(row=3, column=0, sticky=tk.W, pady=2)
        self.var_comp = tk.StringVar()
        self.cbo_comp = ttk.Combobox(left_frame, textvariable=self.var_comp, state="readonly", width=34)
        self.cbo_comp.bind("<<ComboboxSelected>>", self.on_composition_changed)
        self.cbo_comp.grid(row=4, column=0, columnspan=2, sticky=tk.EW, pady=(0, 4))

        # Bandas personalizadas opcionais (> 3 bandas) ou Formula de Indice
        self.lbl_custom_bands = ttk.Label(left_frame, text=u"Bandas Personalizadas (opcional, ex: B4,B3,B2):", font=("Segoe UI", 8))
        self.lbl_custom_bands.grid(row=5, column=0, columnspan=2, sticky=tk.W, pady=(2, 1))
        self.txt_custom_bands = ttk.Entry(left_frame, width=34)
        self.txt_custom_bands.grid(row=6, column=0, columnspan=2, sticky=tk.EW, pady=(0, 4))

        # Modo de Carga no ArcMap (Multibanda vs RGB Rapido)
        mode_box = ttk.LabelFrame(left_frame, text=" Modo de Carga no ArcMap ", padding=4)
        mode_box.grid(row=7, column=0, columnspan=2, sticky=tk.EW, pady=(0, 6))

        self.var_load_mode = tk.StringVar(value="multiband")
        rb_multi = self.rb_multi = ttk.Radiobutton(
            mode_box,
            text=u"Multibanda Bruta (Permite Trocar Bandas)",
            variable=self.var_load_mode,
            value="multiband"
        )
        rb_multi.pack(anchor=tk.W, pady=1)

        rb_rgb = self.rb_rgb = ttk.Radiobutton(
            mode_box,
            text=u"RGB Rapido (Visualizacao Pronta 3 Bandas)",
            variable=self.var_load_mode,
            value="rgb"
        )
        rb_rgb.pack(anchor=tk.W, pady=1)

        # Tamanho do Pixel / Resolucao (metros)
        ttk.Label(left_frame, text=u"Tamanho do Pixel (m):", font=("Segoe UI", 9, "bold")).grid(row=8, column=0, sticky=tk.W, pady=2)
        self.var_pixel_size = tk.StringVar(value="10")
        self.cbo_pixel_size = ttk.Combobox(
            left_frame,
            textvariable=self.var_pixel_size,
            values=["10", "15", "20", "30", "60", "100"],
            width=15
        )
        self.cbo_pixel_size.grid(row=8, column=1, sticky=tk.E, pady=2)

        # Intervalo de Datas (Padrao brasileiro DD/MM/AAAA)
        ttk.Label(left_frame, text="Data Inicial (DD/MM/AAAA):").grid(row=9, column=0, sticky=tk.W, pady=2)
        self.txt_start_date = ttk.Entry(left_frame, width=15)
        d_end = datetime.date.today()
        d_start = d_end - datetime.timedelta(days=45)
        self.txt_start_date.insert(0, d_start.strftime("%d/%m/%Y"))
        self.txt_start_date.grid(row=9, column=1, sticky=tk.E, pady=2)

        ttk.Label(left_frame, text="Data Final (DD/MM/AAAA):").grid(row=10, column=0, sticky=tk.W, pady=2)
        self.txt_end_date = ttk.Entry(left_frame, width=15)
        self.txt_end_date.insert(0, d_end.strftime("%d/%m/%Y"))
        self.txt_end_date.grid(row=10, column=1, sticky=tk.E, pady=2)

        # Atalhos de data
        frame_date_shortcuts = ttk.Frame(left_frame)
        frame_date_shortcuts.grid(row=11, column=0, columnspan=2, sticky=tk.EW, pady=(3, 8))

        btn_d30 = ttk.Button(frame_date_shortcuts, text="30d", width=8, command=lambda: self.set_quick_dates(30))
        btn_d30.pack(side=tk.LEFT, padx=1)
        btn_d60 = ttk.Button(frame_date_shortcuts, text="60d", width=8, command=lambda: self.set_quick_dates(60))
        btn_d60.pack(side=tk.LEFT, padx=1)
        btn_d90 = ttk.Button(frame_date_shortcuts, text="90d", width=8, command=lambda: self.set_quick_dates(90))
        btn_d90.pack(side=tk.LEFT, padx=1)

        sep_loc = ttk.Separator(left_frame, orient=tk.HORIZONTAL)
        sep_loc.grid(row=12, column=0, columnspan=2, sticky=tk.EW, pady=6)

        # Filtro Espacial (Apenas Extensao da Tela e Camada Vetorial AOI para garantir 100% de qualidade nativa)
        ttk.Label(left_frame, text=u"Filtro de Localizacao (Resolução Nativa 100%):", font=("Segoe UI", 9, "bold")).grid(row=13, column=0, columnspan=2, sticky=tk.W, pady=2)

        self.var_spatial_type = tk.StringVar(value="extent")

        rb_ext = ttk.Radiobutton(left_frame, text=u"Extensao da Tela do ArcMap (<= 1:500k)", variable=self.var_spatial_type, value="extent")
        rb_ext.grid(row=14, column=0, columnspan=2, sticky=tk.W, pady=2)

        rb_lyr = ttk.Radiobutton(left_frame, text="Camada Vetorial (AOI):", variable=self.var_spatial_type, value="layer")
        rb_lyr.grid(row=15, column=0, sticky=tk.W, pady=2)

        self.cbo_layers = ttk.Combobox(left_frame, state="readonly", width=18)
        self.cbo_layers.grid(row=15, column=1, sticky=tk.EW, padx=2)

        # Botao de Busca
        self.btn_search = ttk.Button(left_frame, text="[ Buscar Imagens no GEE ]", style="Primary.TButton", command=self.on_search_clicked)
        self.btn_search.grid(row=16, column=0, columnspan=2, sticky=tk.EW, pady=12)

        # --- PAINEL DIREITO: TABELA MULTISELECAO E MINIATURA ---
        right_frame = ttk.Frame(middle_paned)
        middle_paned.add(right_frame, weight=3)

        # Tabela com Multi-seleção (selectmode extended)
        table_frame = self.table_frame = ttk.LabelFrame(right_frame, text=u" 2. Imagens Disponiveis (Selecione uma ou varias com Ctrl / Shift) ", padding=6)
        table_frame.pack(fill=tk.BOTH, expand=True, side=tk.TOP, pady=(0, 4))

        cols = ("date", "cloud", "tile", "name", "status")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", selectmode="extended")
        self.tree.heading("date", text=u"Data / Hora")
        self.tree.heading("cloud", text=u"Nuvens (%)")
        self.tree.heading("tile", text=u"Tile / P-R")
        self.tree.heading("name", text=u"Nome da Cena")
        self.tree.heading("status", text=u"Status")

        self.tree.column("date", width=125, anchor=tk.CENTER)
        self.tree.column("cloud", width=70, anchor=tk.CENTER)
        self.tree.column("tile", width=80, anchor=tk.CENTER)
        self.tree.column("name", width=320, anchor=tk.W)
        self.tree.column("status", width=95, anchor=tk.CENTER)

        # Tags visuais de status na tabela
        self.tree.tag_configure("loaded", background="#e8f8f5", foreground="#117a65")
        self.tree.tag_configure("downloading", background="#fef9e7", foreground="#b7950b")
        self.tree.tag_configure("queued", background="#ebf5fb", foreground="#1b4f72")
        self.tree.tag_configure("preview", background="#f4ecf7", foreground="#6c3483")
        self.tree.tag_configure("error", background="#fdedec", foreground="#922b21")

        tree_scroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<<TreeviewSelect>>", self.on_image_selected)

        # Painel de Carregamento de Imagens no ArcMap
        load_frame = ttk.LabelFrame(right_frame, text=u" 3. Carregamento de Imagens no ArcMap ", padding=10)
        load_frame.pack(fill=tk.X, expand=False, side=tk.BOTTOM, pady=(6, 0))

        info_actions = ttk.Frame(load_frame)
        info_actions.pack(fill=tk.BOTH, expand=True)

        self.lbl_selected_title = ttk.Label(info_actions, text="Nenhuma imagem selecionada", font=("Segoe UI", 9, "bold"))
        self.lbl_selected_title.pack(anchor=tk.W, pady=1)

        self.lbl_selected_info = ttk.Label(info_actions, text=u"Selecione uma ou mais cenas na tabela para carregar no ArcMap.", font=("Segoe UI", 8), foreground="#566573")
        self.lbl_selected_info.pack(anchor=tk.W, pady=1)

        # Agrupamento no TOC (Group Layer)
        grp_frame = ttk.Frame(info_actions)
        grp_frame.pack(anchor=tk.W, fill=tk.X, pady=(4, 3))

        self.var_use_group = tk.BooleanVar(value=True)
        self.chk_group = ttk.Checkbutton(
            grp_frame,
            text="Agrupar no TOC (Grupo):",
            variable=self.var_use_group,
            command=self.on_toggle_group
        )
        self.chk_group.pack(side=tk.LEFT, padx=(0, 6))

        self.txt_group_name = ttk.Entry(grp_frame, width=28)
        self.txt_group_name.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Mapeamento e Operacoes de Camadas no TOC
        replace_box = ttk.LabelFrame(info_actions, text=u" Substituir camada existente no TOC ", padding=(4, 3))
        replace_box.pack(anchor=tk.W, fill=tk.X, pady=(2, 4))

        row_cbo = ttk.Frame(replace_box)
        row_cbo.pack(anchor=tk.W, fill=tk.X, pady=(1, 2))
        ttk.Label(row_cbo, text="Alvo no TOC:", font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(0, 4))
        self.cbo_toc_rasters = ttk.Combobox(row_cbo, state="readonly", width=22)
        self.cbo_toc_rasters.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        btn_refresh_toc = ttk.Button(row_cbo, text="Atualizar", width=9, command=self.on_btn_refresh_toc_clicked)
        btn_refresh_toc.pack(side=tk.LEFT, padx=(0, 2))

        row_btns = ttk.Frame(replace_box)
        row_btns.pack(anchor=tk.W, fill=tk.X, pady=(2, 2))

        self.btn_replace_toc = ttk.Button(
            row_btns,
            text=u"🔁 [ Substituir ]",
            command=self.on_replace_selected_background
        )
        self.btn_replace_toc.pack(side=tk.LEFT, padx=(0, 4))
        ttk.Label(row_btns, text=u"(bandas e stretch são aplicados e conferidos automaticamente na carga)",
                  font=("Segoe UI", 8), foreground="#566573").pack(side=tk.LEFT, padx=(6, 0))

        # Botoes de Acao Principais
        btn_bar = ttk.Frame(info_actions)
        btn_bar.pack(anchor=tk.W, pady=(6, 2))

        self.btn_add_toc = ttk.Button(
            btn_bar,
            text="[ Carregar no ArcMap ]",
            style="Action.TButton",
            command=self.on_load_selected_background
        )
        self.btn_add_toc.pack(side=tk.LEFT, padx=(0, 6))

        self.btn_thumb = ttk.Button(btn_bar, text=u"[ Miniatura ]", command=self.on_thumbnail_clicked)
        self.btn_thumb.pack(side=tk.LEFT, padx=(0, 6))

        # 3. Barra de Status Inferior com Progresso e Percentual
        status_bar_frame = ttk.Frame(self.root, relief=tk.SUNKEN, padding=(4, 2))
        status_bar_frame.pack(fill=tk.X, side=tk.BOTTOM)

        self.lbl_progress = ttk.Label(
            status_bar_frame,
            text=u"Pronto. (ArcMagery v%s - Google Earth Engine, Google Earth e CBERS/INPE)" % CURRENT_VERSION,
            anchor=tk.W
        )
        self.lbl_progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 6))

        self.pbar = ttk.Progressbar(
            status_bar_frame,
            orient=tk.HORIZONTAL,
            mode='determinate',
            length=180,
            maximum=100
        )
        self.pbar.pack(side=tk.LEFT, padx=(0, 6))

        self.lbl_pct = ttk.Label(
            status_bar_frame,
            text="0%",
            width=5,
            anchor=tk.CENTER,
            font=("Segoe UI", 8, "bold")
        )
        self.lbl_pct.pack(side=tk.LEFT, padx=(0, 4))

        self.cbo_toc_rasters.bind("<<ComboboxSelected>>", lambda e: self.update_action_buttons_state())
        self.update_action_buttons_state()

    def update_map_scale_display(self):
        scale = self.arcmap_context.get('scale')
        if scale is not None:
            if scale <= MAX_ALLOWED_SCALE:
                self.lbl_scale_info.config(
                    text=u"| Escala ArcMap: 1:{:,.0f} (Valida <= 1:500k [OK])".format(scale),
                    fg="#145a32"
                )
            else:
                self.lbl_scale_info.config(
                    text=u"| Escala ArcMap: 1:{:,.0f} (Excede 1:500k [Alerta])".format(scale),
                    fg="#922b21"
                )
        else:
            self.lbl_scale_info.config(text=u"| Escala: N/D", fg="#555")

    def on_fit_scale_clicked(self):
        self.lbl_progress.config(text="Ajustando escala no ArcMap para 1:500.000...")
        def worker():
            rep = gee_bridge.send_arcmap_command({'action': 'set_scale', 'scale': MAX_ALLOWED_SCALE}, timeout=15)
            def done():
                if rep.get('success'):
                    self.sync_arcmap_context()
                    messagebox.showinfo("Escala Ajustada", "A escala do mapa foi ajustada para 1:500.000 no ArcMap!", parent=self.root)
                    self.lbl_progress.config(text="Escala ajustada para 1:500.000.")
                else:
                    messagebox.showwarning("Aviso", "Nao foi possivel ajustar a escala: " + rep.get('message', ''), parent=self.root)
                    self.lbl_progress.config(text="Pronto.")
            self.post_to_gui(done)
        t = threading.Thread(target=worker)
        t.daemon = True
        t.start()

    def set_quick_dates(self, days):
        d_end = datetime.date.today()
        d_start = d_end - datetime.timedelta(days=days)
        self.txt_start_date.delete(0, tk.END)
        self.txt_start_date.insert(0, d_start.strftime("%d/%m/%Y"))
        self.txt_end_date.delete(0, tk.END)
        self.txt_end_date.insert(0, d_end.strftime("%d/%m/%Y"))

    def populate_initial_data(self):
        ctx = gee_bridge.read_arcmap_context() or {}
        self.arcmap_context = ctx
        layers = ctx.get('vector_layers', [])
        if layers:
            self.cbo_layers['values'] = layers
            self.cbo_layers.current(0)
        else:
            self.cbo_layers['values'] = ["Nenhuma camada encontrada"]
            self.cbo_layers.current(0)

        self.update_sensor_info_display()
        self.update_compositions_list()
        self.update_default_group_name()
        self.refresh_toc_rasters()

    def on_btn_refresh_toc_clicked(self):
        """Solicita ao ArcMap para re-exportar o contexto imediatamente e atualiza a combobox com todos os alvos e grupos"""
        def async_refresh():
            try:
                gee_bridge.send_arcmap_command({'action': 'refresh_context'}, timeout=3)
            except Exception:
                pass
            self.post_to_gui(self.refresh_toc_rasters)

        t = threading.Thread(target=async_refresh)
        t.daemon = True
        t.start()
        self.refresh_toc_rasters()

    def refresh_toc_rasters(self):
        try:
            self.sync_arcmap_context()
            r_layers = self.arcmap_context.get('raster_layers', [])
            grp_list = self.arcmap_context.get('groups_with_rasters', [])
            targets = gee_bridge.build_toc_targets(r_layers, grp_list)

            cur = self.cbo_toc_rasters.get()
            self.cbo_toc_rasters['values'] = targets

            sel_target = self.arcmap_context.get('selected_target')
            if sel_target and sel_target in targets:
                self.cbo_toc_rasters.set(sel_target)
            elif cur and cur in targets:
                self.cbo_toc_rasters.set(cur)
            elif targets:
                self.cbo_toc_rasters.current(0)

            self.refresh_tree_status_columns()
            self.update_action_buttons_state()
        except Exception as e:
            print("Erro ao atualizar camadas raster do TOC:", e)

    def update_default_group_name(self):
        try:
            sensor = self.get_selected_sensor_code()
            comp = self.get_selected_composition_code()
            today_str = datetime.date.today().strftime("%Y%m%d")
            if inpe.is_inpe(sensor):
                default_name = "INPE_%s_%s_%s" % (inpe.collection_of(sensor), comp, today_str)
            else:
                default_name = "GEE_%s_%s_%s" % (sensor, comp, today_str)
            if hasattr(self, 'txt_group_name'):
                current = self.txt_group_name.get().strip()
                if not current or current.startswith("GEE_") or current.startswith("INPE_"):
                    self.txt_group_name.delete(0, tk.END)
                    self.txt_group_name.insert(0, default_name)
        except Exception:
            pass

    def on_toggle_group(self):
        if self.var_use_group.get():
            self.txt_group_name.config(state=tk.NORMAL)
        else:
            self.txt_group_name.config(state=tk.DISABLED)

    def get_selected_sensor_code(self):
        items = getattr(self, '_sensor_items', SENSOR_DISPLAY)
        idx = self.cbo_sensor.current()
        if 0 <= idx < len(items):
            return items[idx][1]
        return items[0][1] if items else "S2"

    def is_inpe_source(self):
        return getattr(self, 'var_source', None) is not None and self.var_source.get() == 'inpe'

    def on_source_changed(self):
        """Alterna a janela entre Google Earth Engine e CBERS / Amazonia-1 (STAC do INPE)."""
        is_inpe = self.is_inpe_source()
        self._sensor_items = inpe.INPE_SENSOR_DISPLAY if is_inpe else SENSOR_DISPLAY
        self.cbo_sensor['values'] = [item[0] for item in self._sensor_items]
        self.cbo_sensor.current(0)
        gee_only = tk.DISABLED if is_inpe else tk.NORMAL
        for w in (getattr(self, 'txt_custom_bands', None), getattr(self, 'rb_multi', None),
                  getattr(self, 'rb_rgb', None), getattr(self, 'cbo_pixel_size', None)):
            if w is not None:
                w.config(state=gee_only)
        if hasattr(self, 'btn_search'):
            self.btn_search.config(text=u"[ Buscar Cenas no INPE ]" if is_inpe else u"[ Buscar Imagens no GEE ]")
        if hasattr(self, 'tree'):
            self.tree.heading("tile", text=u"Órbita/Ponto · Cobertura" if is_inpe else u"Tile / P-R")
        if hasattr(self, 'table_frame'):
            self.table_frame.config(text=(u" 2. Cenas CBERS / Amazônia-1 (STAC INPE) - selecione uma ou várias " if is_inpe
                                          else u" 2. Imagens Disponiveis (Selecione uma ou varias com Ctrl / Shift) "))
        if is_inpe:
            self.set_quick_dates(120)
        self.on_sensor_changed()

    def update_sensor_info_display(self):
        sensor = self.get_selected_sensor_code()
        meta = SENSOR_METADATA.get(sensor) or inpe.INPE_SENSOR_METADATA.get(sensor, {})
        if meta and hasattr(self, 'lbl_sensor_period') and self.lbl_sensor_period is not None:
            period_str = meta.get('period_display', '')
            collection = meta.get('collection', '')
            agency = meta.get('agency', '')
            res = meta.get('res', '')
            bands_str = meta.get('available_bands', '')

            self.lbl_sensor_period.config(text=u"📅 Período: %s" % period_str)
            source_tag = u"STAC INPE" if inpe.is_inpe(sensor) else u"GEE"
            self.lbl_sensor_detail.config(text=u"📡 %s: %s (%s | %s)" % (source_tag, collection, agency, res))
            if hasattr(self, 'lbl_sensor_bands') and self.lbl_sensor_bands is not None:
                self.lbl_sensor_bands.config(text=u"🌈 Bandas: %s" % bands_str)

    def on_sensor_changed(self, event=None):
        self._active_search_token += 1
        if hasattr(self, 'txt_custom_bands') and self.txt_custom_bands is not None:
            self.txt_custom_bands.delete(0, tk.END)
        self.update_sensor_info_display()
        self.update_compositions_list()
        self.on_composition_changed()
        self.update_default_group_name()

        # Limpar tabela de resultados anteriores para evitar baixar imagem de satelite incompativel
        if hasattr(self, 'tree') and self.tree is not None:
            for item in self.tree.get_children():
                self.tree.delete(item)
            self.images_cache = []
        if hasattr(self, 'lbl_results_count') and self.lbl_results_count is not None:
            self.lbl_results_count.config(text=u"Satélite alterado. Clique em [Buscar] para listar as cenas.")

        # Atualizar tamanho do pixel padrao de acordo com a resolucao nativa do satelite
        s = self.get_selected_sensor_code()
        meta = SENSOR_METADATA.get(s) or inpe.INPE_SENSOR_METADATA.get(s, {})
        if hasattr(self, 'var_pixel_size'):
            if inpe.is_inpe(s):
                self.var_pixel_size.set(str(inpe.native_res(s) or ''))  # grade nativa da cena
            elif s == "S2":
                self.var_pixel_size.set("10")
            elif s in ["L8", "L7", "L5", "L4"]:
                self.var_pixel_size.set("30")
            elif s in ["L1", "L2", "L3"]:
                self.var_pixel_size.set("60")

        # Ajuste inteligente de datas caso selecione missao historica concluida
        end_y = meta.get('end_year')
        if end_y is not None and hasattr(self, 'txt_end_date') and hasattr(self, 'txt_start_date'):
            def_start, def_end = meta.get('default_dates', ('01/06/1990', '30/09/1990'))
            cur_end = self.txt_end_date.get().strip()
            try:
                cur_end_y = int(cur_end.split('/')[-1])
                if cur_end_y > end_y:
                    self.txt_start_date.delete(0, tk.END)
                    self.txt_start_date.insert(0, def_start)
                    self.txt_end_date.delete(0, tk.END)
                    self.txt_end_date.insert(0, def_end)
                    if hasattr(self, 'lbl_progress'):
                        self.lbl_progress.config(
                            text=u"Período ajustado automaticamente para intervalo operacional do %s (%s a %s)." % (meta.get('name', s), def_start, def_end)
                        )
            except Exception:
                pass
        else:
            cur_end = self.txt_end_date.get().strip() if hasattr(self, 'txt_end_date') else ""
            try:
                cur_end_y = int(cur_end.split('/')[-1])
                if s == 'S2' and cur_end_y < 2016:
                    self.set_quick_dates(45)
                elif s == 'L8' and cur_end_y < 2013:
                    self.set_quick_dates(45)
            except Exception:
                pass

    def update_compositions_list(self):
        sensor = self.get_selected_sensor_code()
        if inpe.is_inpe(sensor):
            items = inpe.composition_items(sensor)
            self.cbo_comp['values'] = items
            if items:
                self.cbo_comp.current(0)
            return
        resp = gee_bridge.get_compositions(sensor)
        if resp.get('success'):
            comps = resp.get('compositions', {})
            items = []
            for code, data in sorted(comps.items()):
                label = data.get('label', '')
                items.append("%s - %s" % (code, label))
            self.cbo_comp['values'] = items
            if items:
                self.cbo_comp.current(0)
        else:
            self.cbo_comp['values'] = []

    def on_composition_changed(self, event=None):
        self.update_default_group_name()
        comp = self.get_selected_composition_code()
        sensor = self.get_selected_sensor_code()

        if inpe.is_inpe(sensor):
            if hasattr(self, 'lbl_custom_bands'):
                self.lbl_custom_bands.config(text=u"CBERS/INPE: bandas definidas pelo produto, recorte na grade nativa.")
            return

        if hasattr(self, 'lbl_custom_bands'):
            if comp == 'CUSTOM_MATH':
                self.lbl_custom_bands.config(text=u"Fórmula Matemática de Índice (ex: (B8-B4)/(B8+B4)):")
                curr = self.txt_custom_bands.get().strip()
                if not curr or not gee_bridge.is_math_expr(curr):
                    if sensor == "S2":
                        def_formula = "(B8-B4)/(B8+B4)"
                    elif sensor in ["L5", "L7", "L4"]:
                        def_formula = "(SR_B4-SR_B3)/(SR_B4+SR_B3)"
                    elif sensor in ["L1", "L2", "L3"]:
                        def_formula = "(B7-B5)/(B7+B5)"
                    else:
                        def_formula = "(SR_B5-SR_B4)/(SR_B5+SR_B4)"
                    self.txt_custom_bands.delete(0, tk.END)
                    self.txt_custom_bands.insert(0, def_formula)
            elif comp == 'CUSTOM_BANDS':
                self.lbl_custom_bands.config(text=u"Bandas Personalizadas (ex: B8,B4,B3 ou SR_B5,SR_B4,SR_B2):")
                curr = self.txt_custom_bands.get().strip()
                if not curr or gee_bridge.is_math_expr(curr):
                    if sensor == "S2":
                        def_bands = "B4,B3,B2"
                    elif sensor in ["L5", "L7", "L4"]:
                        def_bands = "SR_B3,SR_B2,SR_B1"
                    elif sensor in ["L1", "L2", "L3"]:
                        def_bands = "B7,B5,B4"
                    else:
                        def_bands = "SR_B4,SR_B3,SR_B2"
                    self.txt_custom_bands.delete(0, tk.END)
                    self.txt_custom_bands.insert(0, def_bands)
            elif comp in ['NDVI', 'NDWI', 'NDMI', 'NBR', 'EVI', 'SAVI']:
                self.lbl_custom_bands.config(text=u"Índice Espectral (cálculo e paleta automáticos no GEE):")
            else:
                self.lbl_custom_bands.config(text=u"Bandas Personalizadas (opcional, separadas por vírgula):")

    def async_check_gee(self):
        def do_check():
            resp = gee_bridge.check_gee()
            def apply_status():
                try:
                    if not self._alive:
                        return
                    if resp.get('success'):
                        self.is_authenticated = True
                        self.top_frame.config(bg="#d4efdf")
                        if hasattr(self, 'lbl_top_ico') and self.lbl_top_ico is not None:
                            self.lbl_top_ico.config(bg="#d4efdf")
                        self.lbl_status_icon.config(text="[OK]", bg="#d4efdf", fg="#145a32")
                        self.lbl_status.config(text=resp.get('message', 'Conectado ao Google Earth Engine!'), bg="#d4efdf", fg="#145a32")
                        self.btn_auth.config(text="Configurar Projeto GEE")
                    else:
                        self.is_authenticated = False
                        self.top_frame.config(bg="#fadbd8")
                        if hasattr(self, 'lbl_top_ico') and self.lbl_top_ico is not None:
                            self.lbl_top_ico.config(bg="#fadbd8")
                        self.lbl_status_icon.config(text="[X]", bg="#fadbd8", fg="#922b21")
                        self.lbl_status.config(text=resp.get('message', 'Nao conectado ao GEE'), bg="#fadbd8", fg="#922b21")
                        self.btn_auth.config(text="Autenticar GEE")
                except Exception as ex:
                    print("Erro ao atualizar status:", ex)

            self.post_to_gui(apply_status)

        threading.Thread(target=do_check).start()

    def on_configure_project(self):
        proj = simpledialog.askstring(
            "Configurar Projeto Google Cloud / GEE",
            "Informe o ID do Projeto Google Cloud habilitado no Earth Engine:\n(Exemplo: meu-projeto-gee-123)",
            parent=self.root
        )
        if proj is not None and proj.strip():
            proj = proj.strip()
            self.lbl_status.config(text="Configurando projeto '%s'..." % proj)
            def do_auth():
                resp = gee_bridge.authenticate_gee(project=proj)
                def apply_auth():
                    if resp.get('success'):
                        messagebox.showinfo("Sucesso", resp.get('message'), parent=self.root)
                        self.async_check_gee()
                    else:
                        if "Nao autenticado" in resp.get('message', ''):
                            if messagebox.askyesno(
                                "Autenticacao Necessaria",
                                "Sua conta ainda nao esta logada neste computador.\n\nDeseja abrir a janela de autenticacao agora?",
                                parent=self.root
                            ):
                                gee_bridge.launch_auth_console(project=proj)
                        else:
                            messagebox.showerror("Erro de Conexao", resp.get('message'), parent=self.root)
                        self.async_check_gee()
                self.post_to_gui(apply_auth)

            threading.Thread(target=do_auth).start()
        elif proj is not None and not proj.strip():
            gee_bridge.launch_auth_console()

    def on_open_settings(self):
        """Abre a janela modal de configuracoes de Stretch, Estatisticas, Multicore e AOI Buffer"""
        GEESettingsDialog(self)

    def on_open_about(self):
        """Abre a janela modal Sobre com informacoes institucionais e dicas"""
        GEEAboutDialog(self.root)

    def on_open_updater(self):
        """Abre a janela modal de atualizacao do plugin via GitHub ou ZIP local"""
        GEEUpdaterDialog(self)

    def get_selected_composition_code(self):
        val = self.var_comp.get()
        if val and " - " in val:
            return val.split(" - ")[0].strip()
        return "432"

    def get_selected_image_id(self):
        selected = self.tree.selection()
        if not selected:
            return None
        idx = self.tree.index(selected[0])
        if 0 <= idx < len(self.images_cache):
            return self.images_cache[idx].get('id')
        return None

    def get_all_selected_image_ids(self):
        selected = self.tree.selection()
        ids = []
        for s in selected:
            idx = self.tree.index(s)
            if 0 <= idx < len(self.images_cache):
                ids.append(self.images_cache[idx].get('id'))
        return ids

    def on_search_clicked(self):
        if not self.is_authenticated and not self.is_inpe_source():
            if messagebox.askyesno(
                "Autenticacao Necessaria",
                "O Google Earth Engine ainda nao esta conectado.\n\nDeseja abrir a tela de autenticacao agora no navegador?",
                parent=self.root
            ):
                self.on_configure_project()
            return

        # Failsafe: se nao ha download ativo, garante que botoes estejam liberados
        worker_alive = (hasattr(self, 'download_worker_thread') and self.download_worker_thread is not None and self.download_worker_thread.is_alive()) or \
                       (hasattr(self, 'download_thread') and self.download_thread is not None and self.download_thread.is_alive())
        if not worker_alive:
            self.is_downloading = False
            self.queued_ids.clear()
            self.current_downloading_ids.clear()

        self.sync_arcmap_context()

        st = self.var_spatial_type.get()
        bbox = None
        geojson_file = None

        if st == "extent":
            bbox = self.arcmap_context.get('bbox')
            if not bbox:
                bbox = [-61.64, -18.04, -50.22, -7.35]

        sensor = self.get_selected_sensor_code()
        s_date = normalize_date(self.txt_start_date.get())
        e_date = normalize_date(self.txt_end_date.get())

        self._active_search_token += 1
        current_token = self._active_search_token

        use_inpe = inpe.is_inpe(sensor)
        src_name = u"STAC do INPE" if use_inpe else u"Google Earth Engine"
        self.btn_search.config(state=tk.DISABLED)
        self.set_progress(0, u"Iniciando busca no %s..." % src_name)
        self.update_action_buttons_state()

        def run_search_thread():
            try:
                g_file = None
                if st == "layer":
                    lyr_name = self.cbo_layers.get()
                    if lyr_name and lyr_name != "Nenhuma camada encontrada":
                        buf = float(self.settings.get('aoi_buffer_meters', 0.0) if hasattr(self, 'settings') else 0.0)
                        self.post_to_gui(lambda: self.set_progress(0, "Exportando AOI da camada '%s' do ArcMap..." % lyr_name))
                        rep = gee_bridge.send_arcmap_command({'action': 'export_aoi', 'layer_name': lyr_name, 'buffer_meters': buf}, timeout=15)
                        if rep.get('success'):
                            g_file = rep.get('file')

                self.post_to_gui(lambda: self.set_progress(0, u"Buscando cenas no catálogo do %s... Aguarde." % src_name))
                if use_inpe:
                    resp = inpe.search(sensor, s_date, e_date, bbox=bbox, geojson_file=g_file, max_images=100)
                else:
                    resp = gee_bridge.search_images(
                        sensor=sensor,
                        start_date=s_date,
                        end_date=e_date,
                        bbox=bbox,
                        geojson_file=g_file,
                        max_images=100
                    )

                def update_tree():
                    if current_token != self._active_search_token:
                        return
                    for row_id in self.tree.get_children():
                        self.tree.delete(row_id)
                    self.images_cache = []

                    if not resp.get('success'):
                        err_msg = resp.get('message', 'Erro desconhecido')
                        messagebox.showerror("Erro de Busca", err_msg, parent=self.root)
                        self.set_progress(0, "Falha na busca: " + err_msg[:60])
                        self.update_action_buttons_state()
                        return

                    images = resp.get('images', [])
                    self.images_cache = images

                    for img in images:
                        tile_str = img.get('mgrs') or ("%s/%s" % (img.get('path', ''), img.get('row', '')) if img.get('path') else '')
                        short_name = img.get('name') or img.get('id', '').split('/')[-1]
                        full_img_id = img.get('id', '')

                        if full_img_id in getattr(self, 'current_downloading_ids', set()):
                            status_val = u"Baixando..."
                            tag_val = "downloading"
                        elif full_img_id in getattr(self, 'queued_ids', set()):
                            status_val = u"Na Fila"
                            tag_val = "queued"
                        else:
                            status_val = self.check_image_loaded_status(short_name)
                            tag_val = "loaded" if (status_val == u"✓ Carregado") else ""

                        item_id = self.tree.insert("", tk.END, values=(
                            img.get('date'),
                            inpe.format_cloud(img.get('cloud_pct')),
                            tile_str,
                            short_name,
                            status_val
                        ))
                        if tag_val:
                            self.tree.item(item_id, tags=(tag_val,))

                    count = len(images)
                    self.set_progress(0, "Busca concluida: %d imagens encontradas." % count)
                    if count > 0:
                        first_item = self.tree.get_children()[0]
                        self.tree.selection_set(first_item)
                        self.on_image_selected()
                    else:
                        self.update_action_buttons_state()
                        messagebox.showinfo("Nenhum Resultado", "Nenhuma imagem foi encontrada para os filtros e periodo especificados.", parent=self.root)

                self.post_to_gui(update_tree)
            except Exception as e:
                err_text = str(e)
                def show_err():
                    messagebox.showerror("Erro Inesperado", err_text, parent=self.root)
                    self.set_progress(0, "Erro: " + err_text[:60])
                    self.update_action_buttons_state()
                self.post_to_gui(show_err)
            finally:
                def reenable():
                    try:
                        if current_token == self._active_search_token:
                            self.btn_search.config(state=tk.NORMAL)
                            self.update_action_buttons_state()
                    except Exception:
                        pass
                self.post_to_gui(reenable)

        threading.Thread(target=run_search_thread).start()

    def on_image_selected(self, event=None):
        selected_ids = self.get_all_selected_image_ids()
        count = len(selected_ids)
        if count == 0:
            self.lbl_selected_title.config(text="Nenhuma imagem selecionada")
            self.lbl_selected_info.config(text="Selecione uma ou mais imagens na tabela.")
            self.update_action_buttons_state()
            return

        if count == 1:
            full_id = selected_ids[0]
            short_name = full_id.split('/')[-1]
            self.lbl_selected_title.config(text=short_name)

            for img in self.images_cache:
                if img.get('id') == full_id:
                    self.lbl_selected_info.config(
                        text=u"Data: %s | Nuvens: %s | %s: %s" % (
                            img.get('date'),
                            inpe.format_cloud(img.get('cloud_pct')),
                            u"Órbita/Ponto" if img.get('source') == 'INPE' else u"Tile",
                            img.get('mgrs') or ("%s/%s" % (img.get('path', ''), img.get('row', '')))
                        )
                    )
        else:
            self.lbl_selected_title.config(text="%d imagens selecionadas" % count)
            self.lbl_selected_info.config(
                text=u"Multi-seleção ativa (%d cenas). Clique em '[ Carregar no ArcMap ]' para adicionar à fila." % count
            )

        self.update_action_buttons_state()

    def validate_scale_and_get_bbox(self):
        """Valida se a escala do ArcMap esta dentro de 1:500.000 para busca por extensao.
        Executada em worker threads: widgets e caixas de dialogo passam por ui_call/_mb.
        Executada em worker threads: widgets e caixas de dialogo passam por ui_call/_mb.
        Retorna (ok, bbox, auto_zoom):
        - Para Camada (AOI): exporta geojson, bbox=None e auto_zoom=True.
        - Para Extensao da Tela: valida escala <= 1:500k, bbox da tela e auto_zoom=False.
        """
        st = self.ui_call(self.var_spatial_type.get)

        if st == "layer":
            lyr_name = self.ui_call(self.cbo_layers.get)
            if not lyr_name or lyr_name == "Nenhuma camada encontrada":
                self._mb('showwarning', u"Camada Inválida", u"Selecione uma camada vetorial (AOI) válida no ArcMap.", parent=self.root)
                return False, None, False
            buf = float(self.settings.get('aoi_buffer_meters', 0.0) if hasattr(self, 'settings') else 0.0)
            rep = gee_bridge.send_arcmap_command({'action': 'export_aoi', 'layer_name': lyr_name, 'buffer_meters': buf}, timeout=10)
            if rep.get('success'):
                self.current_aoi_file = rep.get('file')
            else:
                self._mb('showerror', u"Erro AOI", u"Falha ao exportar limite vetorial da camada '%s': %s" % (lyr_name, rep.get('message', '')), parent=self.root)
                return False, None, False
            return True, None, True

        # st == "extent"
        self.ui_call(self.sync_arcmap_context)
        scale = self.arcmap_context.get('scale')

        if scale is not None and scale > MAX_ALLOWED_SCALE:
            msg = (
                "A escala atual do mapa e 1:{:,.0f}, superior a escala maxima permitida de 1:500.000.\n\n"
                "Deseja ajustar o zoom do ArcMap automaticamente para 1:500.000 para continuar?"
            ).format(scale)
            if self._mb('askyesno', "Limite de Escala (1:500.000)", msg, parent=self.root):
                rep_scale = gee_bridge.send_arcmap_command({'action': 'set_scale', 'scale': MAX_ALLOWED_SCALE}, timeout=10)
                if rep_scale.get('success'):
                    self.ui_call(self.sync_arcmap_context)
                else:
                    self._mb('showwarning', u"Aviso Escala", u"Não foi possível ajustar a escala no ArcMap: " + rep_scale.get('message', ''), parent=self.root)
                    return False, None, False
            else:
                return False, None, False

        bbox = self.arcmap_context.get('bbox')
        if not bbox:
            self.ui_call(self.sync_arcmap_context)
            bbox = self.arcmap_context.get('bbox')
        if not bbox:
            rep = gee_bridge.send_arcmap_command({'action': 'refresh_context'}, timeout=4)
            if rep.get('success') and rep.get('context'):
                self.arcmap_context = rep['context']
                bbox = self.arcmap_context.get('bbox')

        if not bbox:
            self._mb('showwarning', 
                u"Extensão ArcMap Indefinida",
                u"Não foi possível obter a extensão geográfica atual do ArcMap.\n\n"
                u"Verifique se o mapa no ArcMap possui uma camada visível ou sistema de coordenadas definido, ou utilize uma camada vetorial (AOI).",
                parent=self.root
            )
            return False, None, False

        return True, bbox, False

    def on_load_selected_background(self):
        """Carrega todas as imagens selecionadas no ArcMap em segundo plano com deteccao de duplicatas no mesmo grupo"""
        ids = self.get_all_selected_image_ids()
        if not ids:
            messagebox.showwarning("Aviso", "Selecione pelo menos uma imagem na tabela.", parent=self.root)
            return

        def async_prep_and_load():
            ok, bbox, auto_zoom = self.validate_scale_and_get_bbox()
            if not ok:
                return

            def on_validated():
                comp = self.get_selected_composition_code()
                group_name = self.txt_group_name.get().strip() if self.var_use_group.get() else None

                self.sync_arcmap_context()

                # Deteccao de imagens ja carregadas no mesmo grupo
                replace_map = {}
                ids_to_process = []

                for img_id in ids:
                    short_name = img_id.split('/')[-1]
                    existing_target = self.find_existing_layer_in_group(short_name, comp, group_name)

                    if existing_target:
                        grp_display = group_name if group_name else u"TOC principal"
                        resp = messagebox.askyesno(
                            u"Camada Já Carregada",
                            u"A imagem '%s' já está carregada no grupo '%s'.\n\n"
                            u"Deseja carregar novamente e substituir a camada existente?" % (short_name, grp_display),
                            parent=self.root
                        )
                        if resp:
                            replace_map[img_id] = existing_target
                            ids_to_process.append(img_id)
                        else:
                            self.set_progress(None, u"Imagem '%s' mantida sem alteração." % short_name)
                            continue
                    else:
                        ids_to_process.append(img_id)

                if not ids_to_process:
                    self.set_progress(0, u"Carregamento cancelado. Nenhuma imagem a processar.")
                    return

                self._start_background_download(
                    ids_to_process,
                    bbox=bbox,
                    replace_map=replace_map,
                    auto_zoom=auto_zoom
                )

            self.post_to_gui(on_validated)

        t = threading.Thread(target=async_prep_and_load)
        t.daemon = True
        t.start()

    def on_replace_selected_background(self):
        """Substitui uma camada selecionada no TOC pela imagem atual do GEE"""
        ids = self.get_all_selected_image_ids()
        if not ids:
            messagebox.showwarning("Aviso", "Selecione uma imagem na tabela para substituir.", parent=self.root)
            return

        target_layer = self.cbo_toc_rasters.get().strip()
        if not target_layer or target_layer in ("Nenhuma camada raster no TOC", "Nenhuma camada encontrada"):
            messagebox.showwarning("Aviso", "Selecione qual camada do TOC voce deseja substituir na lista ao lado.", parent=self.root)
            return

        if target_layer.startswith("[Todo o TOC]") or target_layer.startswith("[Grupo]"):
            messagebox.showwarning(
                u"Substituição Inválida",
                u"A substituição direta de arquivo só pode ser realizada sobre uma camada raster individual.\n\n"
                u"Para aplicar alterações de composição e realce sobre um Grupo ou sobre Todo o TOC, utilize os botões:\n"
                u" • [ Composição ]\n"
                u" • [ Forçar RGB ]\n"
                u" • [ Garantir Stretch ]",
                parent=self.root
            )
            return

        def async_prep_and_replace():
            ok, bbox, auto_zoom = self.validate_scale_and_get_bbox()
            if not ok:
                return

            def on_validated():
                replace_map = {ids[0]: target_layer}
                self._start_background_download(
                    ids[:1],
                    bbox=bbox,
                    replace_map=replace_map,
                    auto_zoom=auto_zoom
                )

            self.post_to_gui(on_validated)

        t = threading.Thread(target=async_prep_and_replace)
        t.daemon = True
        t.start()

    def _enqueue_download_task(self, image_ids, bbox, replace_map=None, auto_zoom=False):
        if replace_map is None:
            replace_map = {}

        sensor = self.get_selected_sensor_code()
        comp = self.get_selected_composition_code()
        custom_bands = self.txt_custom_bands.get().strip() or None
        load_mode = self.var_load_mode.get() if hasattr(self, 'var_load_mode') else 'multiband'
        st = self.var_spatial_type.get()
        geojson_file = getattr(self, 'current_aoi_file', None) if (st == "layer") else None

        # Obter tamanho do pixel / resolucao definida pelo usuario
        pixel_size = None
        if hasattr(self, 'var_pixel_size'):
            raw_px = self.var_pixel_size.get().strip()
            if raw_px:
                try:
                    pixel_size = float(raw_px)
                except Exception:
                    pixel_size = None

        # Validacao preventiva de tamanho para resolucao nativa estrita (100% de qualidade)
        # (especifica do GEE: o limite do INPE e verificado no backend ao recortar a cena)
        if st == "extent" and bbox and not inpe.is_inpe(sensor):
            import math
            req_scale = pixel_size
            if req_scale is None or req_scale <= 0:
                if sensor == "S2":
                    req_scale = 10.0
                elif sensor in ["L8", "L7", "L5", "L4"]:
                    req_scale = 30.0
                elif sensor in ["L1", "L2", "L3"]:
                    req_scale = 60.0
                else:
                    req_scale = 30.0

            has_custom = bool(custom_bands and custom_bands.strip())
            is_formula = has_custom and gee_bridge.is_math_expr(custom_bands)

            if is_formula or (comp in ['NDVI', 'NDWI', 'NDMI', 'NBR', 'EVI', 'SAVI'] and not has_custom) or (comp == 'CUSTOM_MATH' and (is_formula or not has_custom)):
                comp_is_index = True
                n_b = 1
                bpp = 4
            else:
                comp_is_index = False
                if has_custom and not is_formula:
                    n_b = max(1, len(gee_bridge.parse_bands(custom_bands, sensor)))
                elif load_mode == 'multiband':
                    if comp == 'MB_10':
                        n_b = 10
                    elif comp == 'MB_12':
                        n_b = 12
                    elif comp in ['MB_8', 'MB_7', 'MB_6']:
                        n_b = int(comp.split('_')[1])
                    else:
                        n_b = 3
                else:
                    n_b = 3
                bpp = 2 * n_b

            minx, miny, maxx, maxy = bbox
            lat_center = (miny + maxy) / 2.0
            lat_rad = math.radians(lat_center)
            width_m = abs(maxx - minx) * 111320.0 * math.cos(lat_rad)
            height_m = abs(maxy - miny) * 110540.0
            area_m2 = max(width_m * height_m, 1000.0)
            if len(image_ids) == 1:
                max_single_m2 = 1.5e10 if sensor == "S2" else 3.5e10
                area_m2 = min(area_m2, max_single_m2)
            est_bytes = (area_m2 / (req_scale * req_scale)) * bpp
            chunk_target = 32 * 1024 * 1024
            if est_bytes > chunk_target:
                est_mb = round(est_bytes / (1024.0 * 1024.0), 1)
                num_quads = max(1, int(math.ceil(est_bytes / float(chunk_target))))
                if num_quads > 120:
                    area_km2 = round(area_m2 / 1000000.0, 1)
                    messagebox.showerror(
                        u"Área Excessivamente Extensa",
                        u"A área selecionada (%.0f km²) requer mais de %d quadrantes (> 3.5 GB) na resolução nativa de %.0fm com %d bandas.\n\n"
                        u"Para viabilizar o processamento, aproxime o zoom no ArcMap (escala <= 1:500.000) ou utilize uma camada vetorial (AOI) menor." % (
                            area_km2, num_quads, req_scale, n_b
                        ),
                        parent=self.root
                    )
                    return

        group_name = None
        if self.var_use_group.get():
            g_val = self.txt_group_name.get().strip()
            if g_val:
                group_name = g_val

        with self._queue_lock:
            # Filtrar IDs ja na fila ou em download ativo para evitar duplicatas por duplo clique
            clean_image_ids = [
                i_id for i_id in image_ids
                if i_id not in self.queued_ids and i_id not in self.current_downloading_ids
            ]
            if not clean_image_ids:
                return

            task = {
                'image_ids': list(clean_image_ids),
                'bbox': bbox,
                'replace_map': replace_map,
                'auto_zoom': auto_zoom,
                'sensor': sensor,
                'comp': comp,
                'custom_bands': custom_bands,
                'load_mode': load_mode,
                'pixel_size': pixel_size,
                'group_name': group_name,
                'geojson_file': geojson_file
            }

            is_already_running = getattr(self, 'is_downloading', False) and (
                hasattr(self, 'download_worker_thread') and self.download_worker_thread is not None and self.download_worker_thread.is_alive()
            )

            for i_id in clean_image_ids:
                self.queued_ids.add(i_id)
                if is_already_running:
                    short = i_id.split('/')[-1]
                    self.set_row_status(short, u"Na Fila", tag="queued")

            self.download_queue.put(task)

            if is_already_running:
                q_size = self.download_queue.qsize()
                msg = u"+ %d item(ns) adicionado(s) à fila! (%d tarefa(s) aguardando)" % (len(clean_image_ids), q_size)
                self.set_progress(None, msg)
                self.update_action_buttons_state()
            else:
                self.is_downloading = True
                self.update_action_buttons_state()
                self.download_worker_thread = threading.Thread(target=self._run_download_queue_worker)
                self.download_worker_thread.daemon = True
                self.download_worker_thread.start()

    def _start_background_download(self, image_ids, bbox=None, replace_map=None, auto_zoom=False, is_mosaic=False):
        """Enfileira a solicitacao de carregamento sem bloquear novas adições à fila"""
        self._enqueue_download_task(image_ids, bbox=bbox, replace_map=replace_map, auto_zoom=auto_zoom)

    def _run_download_queue_worker(self):
        """Worker em segundo plano que executa tarefas da fila sequencialmente"""
        errors_occurred = []
        try:
            while self._alive:
                task = None
                try:
                    task = self.download_queue.get(timeout=0.5)
                except queue_mod.Empty:
                    with self._queue_lock:
                        if self.download_queue.empty():
                            break
                        continue

                self.is_downloading = True
                self.post_to_gui(self.update_action_buttons_state)

                try:
                    self._execute_single_download_task(task)
                except Exception as ex:
                    import traceback
                    tb = traceback.format_exc()
                    try:
                        print("Erro executando tarefa da fila:\n" + tb)
                    except Exception:
                        pass
                    errors_occurred.append(str(ex))
                    for i_id in task.get('image_ids', []):
                        short = i_id.split('/')[-1]
                        self.set_row_status(short, u"Falha", tag="error")
                    self.post_to_gui(lambda m=str(ex): messagebox.showerror(
                        u"Erro de Execução",
                        u"Falha ao executar download da cena:\n\n%s" % m,
                        parent=self.root
                    ))
                finally:
                    self.download_queue.task_done()

        finally:
            def finish_queue():
                with self._queue_lock:
                    if self.download_queue.empty():
                        self.is_downloading = False
                        self.download_worker_thread = None
                        self.queued_ids.clear()
                        self.current_downloading_ids.clear()
                        self.refresh_toc_rasters()
                        self.update_action_buttons_state()
                        if errors_occurred:
                            self.set_progress(0, u"Aviso: Ocorreu erro no processamento (%s)" % errors_occurred[0][:40])
                        else:
                            self.set_progress(100, u"Concluído! Todas as tarefas da fila foram processadas com sucesso.")

            self.post_to_gui(finish_queue)

    def _warn_if_symbology_not_guaranteed(self, rep, layer_title):
        """load_layer/replace_layer retornam sucesso mesmo se bandas/stretch nao puderem ser
        garantidos; nesse caso a mensagem traz o prefixo de aviso e o usuario e informado."""
        msg = rep.get('message') or u''
        if not isinstance(msg, unicode):
            msg = unicode(msg, 'utf-8', 'replace')
        if getattr(gee_bridge, 'SYMBOLOGY_WARNING_PREFIX', u'ATENÇÃO') in msg:
            detail = msg.split(u' | ', 1)[-1]
            self.post_to_gui(lambda: messagebox.showwarning(
                u"Simbologia", u"A camada '%s' foi carregada, mas:\n\n%s" % (layer_title, detail), parent=self.root))
            return True
        return False

    def _download_any(self, img_id, sensor, comp, out_tif, custom_bands, load_mode, bbox, geojson_file,
                      pixel_size, on_progress=None):
        """Baixa uma cena do GEE ou recorta uma cena do INPE; a resposta traz 'file' (e 'rgb_bands')."""
        if inpe.is_inpe(sensor):
            return inpe.download(img_id, sensor, comp, out_tif, bbox=bbox, geojson_file=geojson_file,
                                 on_progress=on_progress)
        return gee_bridge.download_image(
            image_ids=[img_id], sensor=sensor, comp_code=comp, out_tif=out_tif, custom_bands=custom_bands,
            load_mode=load_mode, bbox=bbox, geojson_file=geojson_file, scale=pixel_size, on_progress=on_progress)

    def on_thumbnail_clicked(self):
        """Miniatura da cena selecionada (GEE ou INPE) numa janela propria."""
        ids = self.get_all_selected_image_ids()
        if len(ids) != 1:
            messagebox.showwarning(u"Miniatura", u"Selecione exatamente uma cena na tabela.", parent=self.root)
            return
        row = next((img for img in self.images_cache if img.get('id') == ids[0]), {})
        sensor = self.get_selected_sensor_code()
        comp = self.get_selected_composition_code()
        bbox = self.arcmap_context.get('bbox')
        short = ids[0].split('/')[-1]
        out_png = os.path.join(tempfile.gettempdir(), u"arcmagery_thumb_%s.png" % short)
        self.btn_thumb.config(state=tk.DISABLED)
        self.set_progress(None, u"Gerando miniatura de %s..." % short)

        def worker():
            try:
                if row.get('source') == 'INPE':
                    resp = inpe.thumbnail(row, out_png)
                else:
                    resp = gee_bridge.get_thumbnail(ids[0], sensor, comp, out_png, bbox=bbox)
                gif = resp.get('gif') if resp.get('success') else None
                if not gif or not os.path.exists(gif):
                    raise RuntimeError(resp.get('message') or u"Miniatura indisponível para esta cena.")
                self.post_to_gui(lambda: self._show_thumbnail_window(short, gif))
                self.post_to_gui(lambda: self.set_progress(None, u"Miniatura de %s pronta." % short))
            except Exception as e:
                err = unicode(e) if not isinstance(e, unicode) else e
                self.post_to_gui(lambda: messagebox.showerror(u"Miniatura", err, parent=self.root))
                self.post_to_gui(lambda: self.set_progress(None, u"Falha na miniatura."))
            finally:
                self.post_to_gui(self.update_action_buttons_state)

        t = threading.Thread(target=worker)
        t.daemon = True
        t.start()

    def _show_thumbnail_window(self, title, gif_path):
        win = tk.Toplevel(self.root)
        win.title(u"Miniatura - %s" % title)
        img = tk.PhotoImage(file=gif_path)
        lbl = tk.Label(win, image=img)
        lbl.image = img  # manter referencia (evita a imagem sumir pelo GC)
        lbl.pack(padx=6, pady=6)

    def _execute_single_download_task(self, task):
        image_ids = task['image_ids']
        bbox = task['bbox']
        replace_map = task.get('replace_map', {})
        auto_zoom = task.get('auto_zoom', False)
        sensor = task['sensor']
        comp = task['comp']
        custom_bands = task.get('custom_bands')
        load_mode = task.get('load_mode', 'multiband')
        pixel_size = task.get('pixel_size')
        group_name = task.get('group_name')
        geojson_file = task.get('geojson_file')

        total = len(image_ids)
        for i_id in image_ids:
            self.current_downloading_ids.add(i_id)
            if i_id in self.queued_ids:
                self.queued_ids.remove(i_id)

        settings = self.settings if hasattr(self, 'settings') else {}
        system_cores = getattr(self, 'max_system_cores', 4)
        use_multicore = bool(settings.get('multicore_enabled', True)) and (concurrent is not None)
        max_cores = int(settings.get('multicore_cores', min(4, system_cores)))

        loaded_count = 0

        # Carregamento de imagens (Multicore paralelo para múltiplas imagens ou Sequencial)
        if use_multicore and total > 1 and not replace_map:
            num_workers = min(total, max_cores)
            q_remaining = self.download_queue.qsize()
            q_info = (u"[Fila: %d pendente(s)] " % q_remaining) if q_remaining > 0 else ""
            self.set_progress(5, u"%s[Multicore %d threads] Baixando %d imagens em paralelo..." % (q_info, num_workers, total))

            def process_single_image(idx, img_id):
                short_name = img_id.split('/')[-1]
                layer_title = "%s_%s" % (short_name, comp)
                out_tif = os.path.join(tempfile.gettempdir(), "%s.tif" % layer_title)
                self.set_row_status(short_name, u"Baixando...", tag="downloading")

                resp = self._download_any(img_id, sensor, comp, out_tif, custom_bands, load_mode,
                                          bbox, geojson_file, pixel_size)

                if resp.get('success'):
                    tif_file = resp.get('file')
                    with self.ipc_lock:
                        rep = gee_bridge.send_arcmap_command({
                            'action': 'load_layer',
                            'file': tif_file,
                            'name': layer_title,
                            'group': group_name,
                            'zoom': auto_zoom if (idx == 0) else False,
                            'comp': comp,
                            'sensor': sensor,
                            'custom_bands': custom_bands,
                            'rgb_bands': resp.get('rgb_bands')
                        }, timeout=120)

                    if rep.get('success'):
                        self._warn_if_symbology_not_guaranteed(rep, layer_title)
                        return True, short_name, None
                    else:
                        return False, short_name, rep.get('message', '')
                else:
                    return False, short_name, resp.get('message', 'Erro ao baixar imagem.')

            with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
                future_map = {
                    executor.submit(process_single_image, idx, img_id): img_id 
                    for idx, img_id in enumerate(image_ids)
                }
                for future in concurrent.futures.as_completed(future_map):
                    ok, short_name, err_msg = future.result()
                    if ok:
                        loaded_count += 1
                        pct = int((float(loaded_count) / total) * 90)
                        self.set_progress(pct, u"%s[Multicore %d/%d] '%s' carregada!" % (q_info, loaded_count, total, short_name))
                        self.set_row_status(short_name, u"✓ Carregado", tag="loaded")
                    else:
                        self.set_row_status(short_name, u"Falha", tag="error")
                        if err_msg:
                            self.post_to_gui(lambda m=err_msg, s=short_name: messagebox.showwarning(
                                "Aviso ArcMap", 
                                u"Falha ao carregar '%s': %s" % (s, m), 
                                parent=self.root
                            ))
        else:
            # Sequencial
            for idx, img_id in enumerate(image_ids):
                short_name = img_id.split('/')[-1]
                layer_title = "%s_%s" % (short_name, comp)
                out_tif = os.path.join(tempfile.gettempdir(), "%s.tif" % layer_title)

                base_pct = int((float(idx) / total) * 90)
                q_remaining = self.download_queue.qsize()
                q_info = (u"[Fila: %d pendente(s)] " % q_remaining) if q_remaining > 0 else ""
                prog_msg = u"%sBaixando %d de %d: %s..." % (q_info, idx + 1, total, short_name)
                self.set_progress(base_pct, prog_msg)
                self.set_row_status(short_name, u"Baixando...", tag="downloading")

                def on_single_prog(msg):
                    if total == 1:
                        if u"Particionando" in msg:
                            self.set_progress(10, msg)
                        elif u"Quadrante" in msg and u"/" in msg:
                            try:
                                import re
                                m = re.search(r'Quadrante\s+(\d+)/(\d+)', msg)
                                if m:
                                    cq = int(m.group(1))
                                    tq = int(m.group(2))
                                    p = int(10 + (float(cq) / float(tq)) * 60)
                                    self.set_progress(p, u"%sQuadrante %d de %d baixado..." % (q_info, cq, tq))
                            except Exception:
                                pass
                        elif u"Mesclando" in msg:
                            self.set_progress(75, u"%sMesclando quadrantes com 100%% resolução nativa..." % q_info)
                        elif u"salvando" in msg:
                            self.set_progress(70, u"%sDownload concluído, finalizando arquivo..." % q_info)
                        else:
                            self.set_progress(None, msg)

                resp = self._download_any(img_id, sensor, comp, out_tif, custom_bands, load_mode,
                                          bbox, geojson_file, pixel_size, on_progress=on_single_prog)

                if resp.get('success'):
                    tif_file = resp.get('file')
                    action_name = u"Substituindo" if (img_id in replace_map) else u"Carregando"
                    self.set_progress(int(base_pct + (90.0 / total) * 0.8), u"%s%s %s no TOC..." % (q_info, action_name, short_name))

                    with self.ipc_lock:
                        if img_id in replace_map:
                            rep = gee_bridge.send_arcmap_command({
                                'action': 'replace_layer',
                                'file': tif_file,
                                'target_layer': replace_map[img_id],
                                'name': layer_title,
                                'comp': comp,
                                'sensor': sensor,
                                'custom_bands': custom_bands,
                                'rgb_bands': resp.get('rgb_bands')
                            }, timeout=120)
                        else:
                            rep = gee_bridge.send_arcmap_command({
                                'action': 'load_layer',
                                'file': tif_file,
                                'name': layer_title,
                                'group': group_name,
                                'zoom': auto_zoom if (idx == 0) else False,
                                'comp': comp,
                                'sensor': sensor,
                                'custom_bands': custom_bands,
                                'rgb_bands': resp.get('rgb_bands')
                            }, timeout=120)

                    if rep.get('success'):
                        loaded_count += 1
                        self.set_row_status(short_name, u"✓ Carregado", tag="loaded")
                        self._warn_if_symbology_not_guaranteed(rep, layer_title)
                    else:
                        self.set_row_status(short_name, u"Falha", tag="error")
                        err_msg = rep.get('message', '')
                        self.post_to_gui(lambda m=err_msg: messagebox.showwarning("Aviso ArcMap", "ArcMap retornou: " + m, parent=self.root))
                else:
                    self.set_row_status(short_name, u"Falha", tag="error")
                    err_msg = resp.get('message', 'Erro ao baixar imagem.')
                    self.post_to_gui(lambda m=err_msg: messagebox.showerror("Erro de Download GEE", m, parent=self.root))

        for i_id in image_ids:
            if i_id in self.current_downloading_ids:
                self.current_downloading_ids.remove(i_id)

_SINGLE_INSTANCE_MUTEX = None

def acquire_single_instance():
    """Garante uma unica GUI por ArcMap (mutex nomeado por sessao IPC). Se ja existir, traz a
    janela existente para frente e retorna False."""
    global _SINGLE_INSTANCE_MUTEX
    if os.name != 'nt':
        return True
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        handle = k32.CreateMutexW(None, False, u"Local\\ArcMagery_GUI_%s" % gee_bridge.IPC_SESSION)
        if k32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            hwnd = ctypes.windll.user32.FindWindowW(None, APP_WINDOW_TITLE)
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                ctypes.windll.user32.SetForegroundWindow(hwnd)
            return False
        _SINGLE_INSTANCE_MUTEX = handle
    except Exception:
        pass
    return True

def main():
    if not acquire_single_instance():
        return
    win = GEEPluginWindow()
    win.root.mainloop()

if __name__ == "__main__":
    main()
