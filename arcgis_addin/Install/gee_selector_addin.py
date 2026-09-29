# -*- coding: utf-8 -*-
"""
Python Add-In para ArcMap 10.8.2
GEE Image Selector
"""

import sys
import os

# Garantir que a pasta Install esta no path
install_dir = os.path.dirname(os.path.abspath(__file__))
if install_dir not in sys.path:
    sys.path.insert(0, install_dir)

try:
    import arcmagery_vendor  # noqa: F401  (comtypes embutido como plano B do pip)
except ImportError:
    pass

try:
    import arcpy
    import pythonaddins
except ImportError:
    pass

def ensure_icon_and_text_style():
    """Tenta configurar automaticamente o estilo do botao na toolbar do ArcMap para exibir Icone e Texto"""
    try:
        import comtypes.client
        app = comtypes.client.CreateObject("esriFramework.AppRef")
        doc = getattr(app, 'Document', None)
        if doc and hasattr(doc, 'CommandBars'):
            cb = doc.CommandBars
            uid = comtypes.client.CreateObject("esriSystemUI.UID")
            for cand in ["gee_selector_addin.btn_open", "{ceae58c4-c44e-4edd-b8f4-1ba7d13b6b7d}_gee_selector_addin.btn_open"]:
                try:
                    uid.Value = cand
                    item = cb.Find(uid, False, False)
                    if item:
                        if getattr(item, 'Style', None) != 3:
                            item.Style = 3  # esriCommandStyleIconAndText
                            item.Refresh()
                        return True
                except Exception:
                    pass
    except Exception:
        pass
    return False

class OpenGEESelectorButton(object):
    """Implementacao do botao na Toolbar do ArcMap"""
    def __init__(self):
        self.enabled = True
        self.checked = False
        self._last_ctx_time = 0
        self._style_applied = False
        try:
            import gee_bridge
            gee_bridge.start_arcmap_ipc_timer(300)
            gee_bridge.export_arcmap_context()
        except Exception:
            pass
        ensure_icon_and_text_style()

    def onClick(self):
        try:
            ensure_icon_and_text_style()
        except Exception:
            pass
        try:
            import gee_bridge
            gee_bridge.start_arcmap_ipc_timer(300)
            gee_bridge.export_arcmap_context()
            ok, msg = gee_bridge.launch_gui_process()
            if not ok:
                pythonaddins.MessageBox(u"Falha ao iniciar processo da interface:\n" + unicode(msg), "Erro", 0)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            try:
                pythonaddins.MessageBox(u"Erro ao abrir Seletor GEE:\n" + unicode(e) + u"\n\n" + unicode(tb), "Erro", 0)
            except Exception:
                print("Erro:", tb)

    def onUpdate(self):
        try:
            if not self._style_applied:
                self._style_applied = True
                ensure_icon_and_text_style()

            import gee_bridge
            gee_bridge.start_arcmap_ipc_timer(250)

            # 1. Se o ArcMap ja estiver processando um comando, nao reentrar
            if getattr(gee_bridge, '_is_processing_cmd', False):
                return

            # 2. Processar acoes pendentes enviadas pela GUI somente se houver comando no disco
            if os.path.exists(gee_bridge.CMD_FILE):
                gee_bridge.process_pending_arcmap_commands()

            # 3. Atualizar contexto da tela periodicamente (a cada 0.6s) para manter escala da GUI atualizada
            import time
            now = time.time()
            if now - self._last_ctx_time > 0.6:
                self._last_ctx_time = now
                gee_bridge.export_arcmap_context()
        except Exception:
            pass

class GEEExtension(object):
    """Extensao nativa do ArcMap (autoLoad=True) para escutar eventos de tela, escala e TOC em tempo real"""
    def __init__(self):
        self.enabled = True
        try:
            import gee_bridge
            gee_bridge.start_arcmap_ipc_timer(250)
            gee_bridge.export_arcmap_context()
        except Exception:
            pass

    def startup(self):
        try:
            import gee_bridge
            gee_bridge.start_arcmap_ipc_timer(250)
            gee_bridge.export_arcmap_context()
        except Exception:
            pass

    def activeViewChanged(self):
        """Disparado instantaneamente pelo ArcMap sempre que o usuario faz zoom, pan ou muda a escala"""
        try:
            import gee_bridge
            gee_bridge.start_arcmap_ipc_timer(250)
            gee_bridge.export_arcmap_context()
            if os.path.exists(gee_bridge.CMD_FILE):
                gee_bridge.process_pending_arcmap_commands()
        except Exception:
            pass

    def contentsChanged(self):
        """Disparado imediatamente quando camadas sao adicionadas, removidas ou alteradas no TOC"""
        try:
            import gee_bridge
            gee_bridge.start_arcmap_ipc_timer(250)
            gee_bridge.export_arcmap_context()
            if os.path.exists(gee_bridge.CMD_FILE):
                gee_bridge.process_pending_arcmap_commands()
        except Exception:
            pass

    def spatialReferenceChanged(self):
        try:
            import gee_bridge
            gee_bridge.start_arcmap_ipc_timer(250)
            gee_bridge.export_arcmap_context()
        except Exception:
            pass

