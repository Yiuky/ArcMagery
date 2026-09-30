# -*- coding: utf-8 -*-
"""Autenticacao interativa do Google Earth Engine (janela de console aberta pelo ArcMagery).

Funciona com qualquer Python 3 apto ao backend - inclusive o do QGIS sem venv - porque ativa as
bibliotecas instaladas sem pip (pylibs). Uso: python ee_auth.py [projeto]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pylibs  # noqa: E402

pylibs.activate()


def main():
    project = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else None
    print("=" * 70)
    print("  ArcMagery - autenticacao do Google Earth Engine")
    print("=" * 70)
    try:
        import ee
    except ImportError:
        print("\n[ERRO] earthengine-api ausente neste Python (%s)." % sys.executable)
        print("       Instalando os componentes (sem pip)...\n")
        pylibs.install()
        pylibs.activate(force=True)
        import ee
    print("Python: %s | earthengine-api %s\n" % (sys.executable, ee.__version__))
    print("O navegador vai abrir: entre com a conta Google que tem acesso ao Earth Engine.\n")
    ee.Authenticate(auth_mode='localhost')
    try:
        ee.Initialize(project=project) if project else ee.Initialize()
        print("\n[SUCESSO] Conectado ao Google Earth Engine%s." % (" (projeto %s)" % project if project else ""))
    except Exception as e:
        print("\n[OK] Credenciais salvas. Ao inicializar: %s" % e)
        print("     Informe o ID do projeto em 'Configurar Projeto GEE' no ArcMagery.")
    print("\nVoce ja pode fechar esta janela e voltar ao ArcMap.")


if __name__ == '__main__':
    main()
