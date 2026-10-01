# -*- coding: utf-8 -*-
"""
Ferramenta de desenvolvimento: gera o logotipo do ArcMagery (sem texto) a partir de docs/images/icon_large.png.

Saidas:
  docs/images/logo.png                      256 px, fundo transparente (README e manual)
  arcgis_addin/{Images,Install}/about_logo.png / .gif   112 px (janela Sobre; GIF para o Tk 8.5 do Python 2.7)

Uso (Python 3 com Pillow e numpy, ex.: o Python do QGIS):  python tools/build_logo.py
"""

import os

import numpy as np
from PIL import Image

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE_DIR, "docs", "images", "icon_large.png")
SUPERSAMPLE = 4


def circle_radius(arr, cx, cy):
    """Raio do disco escuro central: primeiro pixel, da borda para o centro, bem mais escuro que o fundo."""
    bg = arr[cy, 2, :3].astype(int)
    for x in range(2, cx):
        if np.abs(arr[cy, x, :3].astype(int) - bg).sum() > 45:
            return cx - x
    return cx - 2


def masked_logo():
    img = Image.open(SRC).convert("RGBA")
    arr = np.array(img)
    h, w = arr.shape[:2]
    cx, cy = w // 2, h // 2
    r = circle_radius(arr, cx, cy) - 1
    # mascara circular suavizada (supersample)
    big = SUPERSAMPLE
    yy, xx = np.mgrid[0:h * big, 0:w * big]
    inside = ((xx + 0.5) / big - cx) ** 2 + ((yy + 0.5) / big - cy) ** 2 <= r * r
    mask = Image.fromarray((inside * 255).astype(np.uint8)).resize((w, h), Image.LANCZOS)
    img.putalpha(mask)
    return img.crop((cx - r - 1, cy - r - 1, cx + r + 2, cy + r + 2))


def save_gif(im_rgba, path, bg=(240, 240, 240)):
    alpha = im_rgba.getchannel("A")
    hole = Image.eval(alpha, lambda a: 255 if a <= 128 else 0)
    flat = Image.alpha_composite(Image.new("RGBA", im_rgba.size, bg + (255,)), im_rgba)
    pal = flat.convert("RGB").convert("P", palette=Image.ADAPTIVE, colors=255)
    pal.paste(255, hole)
    pal.save(path, "GIF", transparency=255)


def main():
    logo = masked_logo()
    out = os.path.join(BASE_DIR, "docs", "images", "logo.png")
    logo.resize((256, 256), Image.LANCZOS).save(out, "PNG", optimize=True)
    print("logo:", out)
    small = logo.resize((112, 112), Image.LANCZOS)
    for d in ("Images", "Install"):
        folder = os.path.join(BASE_DIR, "arcgis_addin", d)
        small.save(os.path.join(folder, "about_logo.png"), "PNG", optimize=True)
        save_gif(small, os.path.join(folder, "about_logo.gif"))
        print("about_logo:", folder)


if __name__ == "__main__":
    main()
