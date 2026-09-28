# -*- coding: utf-8 -*-
"""
Script para processar e gerar os icones do CGMA ArcGEE Explorer.
Gera versoes PNG, GIF (com transparencia para compatibilidade Tkinter Python 2.7) e ICO multi-resolucao.
"""

import os
from collections import deque
from PIL import Image
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BRAIN_DIR = os.environ.get("BRAIN_DIR", os.path.join(os.path.expanduser("~"), ".gemini", "antigravity", "brain"))

SIMPLE_SRC = os.path.join(BRAIN_DIR, "arcgee_simple_icon_1790259266530.jpg")
LARGE_SRC = os.path.join(BRAIN_DIR, "arcgee_large_icon_1790259248763.jpg")

DEST_DIRS = [
    os.path.join(BASE_DIR, "arcgis_addin", "Images"),
    os.path.join(BASE_DIR, "arcgis_addin", "Install")
]

def flood_remove_bg(img, thresh=240):
    arr = np.array(img.convert('RGBA'))
    h, w = arr.shape[:2]
    mask = np.zeros((h, w), dtype=bool)
    is_bg = (arr[:, :, 0] > thresh) & (arr[:, :, 1] > thresh) & (arr[:, :, 2] > thresh)
    q = deque([(0, 0), (w-1, 0), (0, h-1), (w-1, h-1)])
    for x, y in list(q):
        mask[y, x] = True
    while q:
        cx, cy = q.popleft()
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nx, ny = cx + dx, cy + dy
            if 0 <= nx < w and 0 <= ny < h:
                if not mask[ny, nx] and is_bg[ny, nx]:
                    mask[ny, nx] = True
                    q.append((nx, ny))
    arr[mask, 3] = 0
    res = Image.fromarray(arr)
    bbox = res.getbbox()
    res = res.crop(bbox)
    max_d = max(res.size)
    sq = Image.new('RGBA', (max_d + 16, max_d + 16), (255, 255, 255, 0))
    sq.paste(res, ((max_d + 16 - res.width) // 2, (max_d + 16 - res.height) // 2))
    return sq

def save_gif(im_rgba, path, size=None, bg_fallback=(240, 240, 240)):
    if size:
        im = im_rgba.resize(size, Image.LANCZOS)
    else:
        im = im_rgba
    alpha = im.getchannel('A')
    mask = Image.eval(alpha, lambda a: 255 if a <= 128 else 0)
    bg = Image.new('RGBA', im.size, bg_fallback + (255,))
    blended = Image.alpha_composite(bg, im)
    im_p = blended.convert('RGB').convert('P', palette=Image.ADAPTIVE, colors=255)
    im_p.paste(255, mask)
    im_p.save(path, 'GIF', transparency=255)

def main():
    print("Processando imagens base...")
    sm_base = flood_remove_bg(Image.open(SIMPLE_SRC), thresh=242)
    lg_base = flood_remove_bg(Image.open(LARGE_SRC), thresh=240)

    # Preparar tamanhos
    sizes = {
        'icon.png': (16, 16, sm_base),
        'icon16.png': (16, 16, sm_base),
        'icon20.png': (20, 20, sm_base),
        'icon24.png': (24, 24, sm_base),
        'icon32.png': (32, 32, sm_base),
        'icon48.png': (48, 48, sm_base),
        'icon64.png': (64, 64, sm_base),
        'about_logo.png': (112, 112, lg_base),
    }

    for d in DEST_DIRS:
        if not os.path.exists(d):
            os.makedirs(d)
        print("Gerando arquivos em: %s" % d)
        for fname, (w, h, base_img) in sizes.items():
            resized = base_img.resize((w, h), Image.LANCZOS)
            png_path = os.path.join(d, fname)
            resized.save(png_path, 'PNG')

            # Salvar tambem versao .gif para Tkinter Tk 8.5
            gif_name = os.path.splitext(fname)[0] + '.gif'
            gif_path = os.path.join(d, gif_name)
            save_gif(base_img, gif_path, size=(w, h))

        # Criar Windows ICO multi-resolucao do icone simples e claro
        ico_path = os.path.join(d, 'app_icon.ico')
        sm_base.save(
            ico_path,
            format='ICO',
            sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
        )
        print("ICO multi-resolucao salvo: %s (%d bytes)" % (ico_path, os.path.getsize(ico_path)))

    print("Todos os icones gerados com sucesso!")

if __name__ == '__main__':
    main()
