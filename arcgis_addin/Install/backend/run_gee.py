# -*- coding: utf-8 -*-
"""
Interface de Linha de Comando (CLI) para ser executada pelo ArcMap (Python 2.7)
Comunica-se via JSON.
"""

import sys
import os
import json
import argparse
import urllib.request

# Adicionar pasta atual ao path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gee_core

def cmd_check(args):
    ok, msg = gee_core.init_gee(args.project)
    print(json.dumps({'success': ok, 'message': msg}))

def cmd_auth(args):
    ok, msg = gee_core.authenticate_gee(args.project)
    print(json.dumps({'success': ok, 'message': msg}))

def cmd_compositions(args):
    comps = gee_core.COMPOSITIONS.get(args.sensor, {})
    print(json.dumps({'success': True, 'compositions': comps}))

def cmd_search(args):
    ok, msg = gee_core.init_gee(args.project)
    if not ok:
        print(json.dumps({'success': False, 'message': "Falha na inicialização do GEE: " + msg}))
        return

    bbox = None
    if args.bbox:
        try:
            bbox = [float(x.strip()) for x in args.bbox.split(',')]
        except Exception:
            pass

    geom = None
    if args.geojson_file and os.path.exists(args.geojson_file):
        try:
            with open(args.geojson_file, 'r') as f:
                geom = json.load(f)
        except Exception as e:
            print(json.dumps({'success': False, 'message': "Erro lendo GeoJSON: " + str(e)}))
            return

    try:
        results = gee_core.search_collection(
            sensor=args.sensor,
            start_date=args.start_date,
            end_date=args.end_date,
            bbox=bbox,
            geometry=geom,
            path=args.path,
            row=args.row,
            mgrs=args.mgrs,
            max_images=args.max_images
        )
        print(json.dumps({'success': True, 'images': results, 'count': len(results)}))
    except Exception as e:
        print(json.dumps({'success': False, 'message': str(e)}))

def cmd_thumb(args):
    ok, msg = gee_core.init_gee(args.project)
    if not ok:
        print(json.dumps({'success': False, 'message': msg}))
        return

    bbox = None
    if args.bbox:
        try:
            bbox = [float(x.strip()) for x in args.bbox.split(',')]
        except Exception:
            pass

    try:
        url = gee_core.get_thumbnail_url(
            image_id=args.image_id,
            sensor=args.sensor,
            composition_code=args.comp,
            dimensions=args.dim,
            bbox=bbox
        )
        if args.out:
            os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
            urllib.request.urlretrieve(url, args.out)
            gif_path = os.path.splitext(args.out)[0] + ".gif"
            try:
                from PIL import Image
                im = Image.open(args.out)
                # Redimensionar se necessário e salvar como GIF
                im.save(gif_path, "GIF")
            except Exception:
                gif_path = None
            print(json.dumps({'success': True, 'url': url, 'file': args.out, 'gif': gif_path}))
        else:
            print(json.dumps({'success': True, 'url': url}))
    except Exception as e:
        print(json.dumps({'success': False, 'message': str(e)}))

def cmd_download(args):
    ok, msg = gee_core.init_gee(args.project)
    if not ok:
        print(json.dumps({'success': False, 'message': msg}))
        return

    image_ids = [x.strip() for x in args.ids.split(',') if x.strip()]
    bbox = None
    if args.bbox:
        try:
            bbox = [float(x.strip()) for x in args.bbox.split(',')]
        except Exception:
            pass

    geom = None
    if args.geojson_file and os.path.exists(args.geojson_file):
        try:
            with open(args.geojson_file, 'r') as f:
                geom = json.load(f)
        except Exception:
            pass

    try:
        out_tif = gee_core.download_geotiff(
            image_ids=image_ids,
            sensor=args.sensor,
            composition_code=args.comp,
            custom_bands=args.custom_bands,
            load_mode=getattr(args, 'load_mode', 'multiband'),
            aoi_geometry=geom,
            bbox=bbox,
            out_tif_path=args.out,
            scale=args.scale,
            crs=args.crs
        )
        print(json.dumps({'success': True, 'file': out_tif}))
    except gee_core.RasterHealthCheckError as ex:
        sys.stderr.write("[ArcGEE][HealthCheckError] " + str(ex) + "\n")
        sys.stderr.flush()
        print(json.dumps({'success': False, 'message': str(ex), 'diagnostics': ex.diagnostics}))
    except Exception as e:
        print(json.dumps({'success': False, 'message': str(e)}))

def main():
    parser = argparse.ArgumentParser(description="GEE CLI Backend para ArcGIS")
    subparsers = parser.add_subparsers(dest="command")

    # check
    p_check = subparsers.add_parser("check")
    p_check.add_argument("--project", default=None)

    # auth
    p_auth = subparsers.add_parser("auth")
    p_auth.add_argument("--project", default=None)

    # compositions
    p_comp = subparsers.add_parser("compositions")
    p_comp.add_argument("--sensor", required=True)

    # search
    p_search = subparsers.add_parser("search")
    p_search.add_argument("--sensor", required=True)
    p_search.add_argument("--start-date", default=None)
    p_search.add_argument("--end-date", default=None)
    p_search.add_argument("--bbox", default=None)
    p_search.add_argument("--geojson-file", default=None)
    p_search.add_argument("--path", default=None)
    p_search.add_argument("--row", default=None)
    p_search.add_argument("--mgrs", default=None)
    p_search.add_argument("--max-images", type=int, default=100)
    p_search.add_argument("--project", default=None)

    # thumb
    p_thumb = subparsers.add_parser("thumb")
    p_thumb.add_argument("--image-id", required=True)
    p_thumb.add_argument("--sensor", required=True)
    p_thumb.add_argument("--comp", required=True)
    p_thumb.add_argument("--dim", type=int, default=350)
    p_thumb.add_argument("--bbox", default=None)
    p_thumb.add_argument("--out", default=None)
    p_thumb.add_argument("--project", default=None)

    # download
    p_dl = subparsers.add_parser("download")
    p_dl.add_argument("--ids", required=True)
    p_dl.add_argument("--sensor", required=True)
    p_dl.add_argument("--comp", required=True)
    p_dl.add_argument("--custom-bands", default=None)
    p_dl.add_argument("--load-mode", default="multiband", choices=["multiband", "rgb"])
    p_dl.add_argument("--bbox", default=None)
    p_dl.add_argument("--geojson-file", default=None)
    p_dl.add_argument("--out", default=None)
    p_dl.add_argument("--scale", type=float, default=None)
    p_dl.add_argument("--crs", default="EPSG:4674")
    p_dl.add_argument("--project", default=None)

    args = parser.parse_args()

    if args.command == "check":
        cmd_check(args)
    elif args.command == "auth":
        cmd_auth(args)
    elif args.command == "compositions":
        cmd_compositions(args)
    elif args.command == "search":
        cmd_search(args)
    elif args.command == "thumb":
        cmd_thumb(args)
    elif args.command == "download":
        cmd_download(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
