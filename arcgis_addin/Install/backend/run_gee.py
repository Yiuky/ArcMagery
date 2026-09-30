# -*- coding: utf-8 -*-
"""
Interface de Linha de Comando (CLI) para ser executada pelo ArcMap (Python 2.7)
Comunica-se via JSON.
"""

import sys
import os
import json
import argparse

# Adicionar pasta atual ao path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qgis_env  # noqa: E402,F401  (registra <QGIS>\bin antes de qualquer import do GDAL)


class _LazyGeeCore(object):
    """Importa gee_core (e o earthengine-api) apenas quando um comando GEE e executado.
    Assim as fontes Google Earth/XYZ e CBERS/INPE funcionam mesmo num Python sem 'ee'."""
    _mod = None

    def __getattr__(self, name):
        if _LazyGeeCore._mod is None:
            import gee_core as _gc
            _LazyGeeCore._mod = _gc
        return getattr(_LazyGeeCore._mod, name)


gee_core = _LazyGeeCore()

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
            gee_core.download_url_with_timeout(url, args.out, timeout=60, max_retries=2)
            gif_path = os.path.splitext(args.out)[0] + ".gif"
            try:
                from PIL import Image
                with Image.open(args.out) as im:
                    im.convert("RGB").save(gif_path, "GIF")  # Tk 8.5 do ArcGIS so exibe GIF
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

# ------------------------------------------------------------------------------------------
# Fontes adicionais (sem Earth Engine): Google Earth / XYZ e CBERS / Amazonia-1 (STAC INPE).
# Recebem o dicionario de parametros do --params-file diretamente (sem argparse).
# ------------------------------------------------------------------------------------------
def _parse_bbox(value):
    if value is None or value == '':
        return None
    if isinstance(value, (list, tuple)):
        vals = [float(v) for v in value]
    else:
        vals = [float(v.strip()) for v in str(value).split(',')]
    if len(vals) != 4:
        raise ValueError("bbox deve ter 4 valores: min_lon,min_lat,max_lon,max_lat")
    return vals


def _bbox_from_geojson_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        gj = json.load(f)
    xs, ys = [], []

    def walk(c):
        if isinstance(c, (list, tuple)) and c and isinstance(c[0], (int, float)):
            xs.append(float(c[0]))
            ys.append(float(c[1]))
        elif isinstance(c, (list, tuple)):
            for sub in c:
                walk(sub)

    feats = gj.get('features') if gj.get('type') == 'FeatureCollection' else [gj]
    for ft in feats:
        geom = ft.get('geometry', ft) if isinstance(ft, dict) else None
        if geom:
            walk(geom.get('coordinates', []))
    if not xs:
        raise ValueError("GeoJSON sem coordenadas: %s" % path)
    return [min(xs), min(ys), max(xs), max(ys)]


def _resolve_bbox(p):
    if p.get('geojson_file'):
        if not os.path.exists(p['geojson_file']):
            raise ValueError("Arquivo GeoJSON da AOI nao encontrado: %s" % p['geojson_file'])
        return _bbox_from_geojson_file(p['geojson_file'])
    bbox = _parse_bbox(p.get('bbox'))
    if not bbox:
        raise ValueError("Filtro espacial obrigatorio: informe bbox ou geojson_file.")
    return bbox


def src_sources_info(p):
    import xyz_core
    import stac_core
    return {
        'success': True,
        'providers': dict((k, {'label': v['label'], 'max_zoom': v['max_zoom'],
                               'tos_warning': v['tos_warning'], 'attribution': v['attribution']})
                          for k, v in xyz_core.PROVIDERS.items()),
        'collections': dict((k, {'label': v['label'], 'res': v['res'],
                                 'modes': stac_core.available_modes(k)})
                            for k, v in stac_core.COLLECTIONS.items()),
        'modes': stac_core.MODES,
        'gdal': xyz_core.HAS_GDAL, 'pil': xyz_core.HAS_PIL,
    }


def src_xyz_estimate(p):
    import tilemath
    return dict(tilemath.estimate(_resolve_bbox(p), int(p.get('zoom', 17))), success=True)


def _is_esri_imagery(p):
    return p.get('provider') in ('esri', 'esri-clarity') or bool(p.get('wayback_release'))


def src_xyz_download(p):
    import xyz_core
    bbox = _resolve_bbox(p)
    zoom = int(p.get('zoom', 17))
    provider = p.get('provider', 'esri')
    release = None
    if p.get('wayback_release'):
        import esri_core
        release = esri_core.release_by_num(p['wayback_release'])
        provider = release['tile_url']  # template {z}/{y}/{x} da versao escolhida
    res = xyz_core.download_mosaic(
        bbox, zoom, provider=provider,
        out_tif=p.get('out'), workers=p.get('workers'),
        max_tiles=int(p.get('max_tiles', xyz_core.DEFAULT_MAX_TILES)),
        compression=p.get('compression', 'JPEG'), target_crs=p.get('crs') or None,
        keep_cache=bool(p.get('keep_cache', False)))
    res = dict(res, success=True)
    if release:
        res.update(provider='esri-wayback', wayback_release=release['num'], wayback_date=release['date'],
                   attribution=u"Esri World Imagery Wayback (%s)" % release['date'])
    if _is_esri_imagery(p):
        res.update(_attach_capture_dates(res['file'], bbox, zoom, release, bool(p.get('footprints', True))))
    elif p.get('provider') in ('google', 'google-hybrid', 'bing'):
        res.update(_esri_reference(bbox, zoom))
    return res


def _esri_reference(bbox, zoom):
    """Google/Bing nao publicam a data das imagens. Como REFERENCIA (nunca como data da imagem
    baixada), informa a data da cena Esri na mesma area - pode ser outra cena."""
    import esri_core
    try:
        dates = esri_core.capture_dates(bbox, zoom, coverage=False)
        return {'capture_summary': None, 'esri_reference': esri_core.summarize_dates(dates)}
    except Exception:
        return {'capture_summary': None, 'esri_reference': None}


def _attach_capture_dates(tif, bbox, zoom, release, footprints):
    """Datas de captura (metadados publicos da Esri) gravadas no GeoTIFF e, opcionalmente, os
    poligonos de cada data em Esri JSON. Falha aqui nunca derruba o download."""
    import esri_core
    try:
        dates = esri_core.capture_dates(bbox, zoom, release, with_geometry=footprints)
    except Exception as e:
        return {'capture_summary': u"indisponível (%s)" % e, 'capture_dates': []}
    out = {'capture_summary': esri_core.summarize_dates(dates),
           'capture_dates': [dict((k, v) for k, v in d.items() if k != 'rings') for d in dates]}
    try:
        _write_capture_tags(tif, dates, out['capture_summary'])
    except Exception:
        pass
    if footprints and any(d.get('rings') for d in dates):
        out['footprints_json'] = esri_core.write_footprints(dates, os.path.splitext(tif)[0] + '_datas.json')
    return out


def _write_capture_tags(tif, dates, summary):
    """Data e sensor no GeoTIFF, com as tags padrao que ArcGIS/QGIS exibem nas propriedades
    (TIFFTAG_DATETIME, ACQUISITION_DATE, SATELLITE_SENSOR, IMAGE_PROVIDER) - ideia do
    C:/DOWNLOADER_EARTH - mais o detalhamento completo (JSON) quando ha varias capturas."""
    from osgeo import gdal
    main = next((d for d in dates if d.get('date')), None)  # maior cobertura primeiro
    ascii_ = lambda s: (s or u'').encode('ascii', 'replace').decode('ascii')
    ds = gdal.Open(tif, gdal.GA_Update)
    try:
        if main:
            ds.SetMetadataItem('TIFFTAG_DATETIME', main['date'].replace('-', ':') + ' 00:00:00')
            ds.SetMetadataItem('ACQUISITION_DATE', main['date'])
            ds.SetMetadataItem('SATELLITE_SENSOR', ascii_(main.get('sensor_name') or main.get('sensor')))
            ds.SetMetadataItem('IMAGE_PROVIDER', ascii_(main.get('provider')))
        ds.SetMetadataItem('ARCMAGERY_CAPTURE_SUMMARY', ascii_(summary))
        ds.SetMetadataItem('ARCMAGERY_CAPTURE_DATES', json.dumps(
            [dict((k, v) for k, v in d.items() if k != 'rings') for d in dates], ensure_ascii=True))
    finally:
        ds = None


def src_esri_dates(p):
    """Datas de captura da area para a versao atual ou uma versao Wayback."""
    import esri_core
    release = esri_core.release_by_num(p['wayback_release']) if p.get('wayback_release') else None
    dates = esri_core.capture_dates(_resolve_bbox(p), int(p.get('zoom', 17)), release)
    return {'success': True, 'dates': dates, 'summary': esri_core.summarize_dates(dates),
            'release_date': (release or esri_core.load_releases()[0])['date']}


def src_esri_versions(p):
    """Versoes do Wayback com imagem diferente na area (uma por data de captura)."""
    import esri_core
    bbox = _resolve_bbox(p)
    zooms = p.get('zooms')
    if not zooms:
        versions = esri_core.local_versions_cached(bbox, int(p.get('zoom', 17)))
        return {'success': True, 'versions': versions, 'count': len(versions)}
    # 2 zooms por vez: cada consulta ja usa 8 threads internas, e 5 zooms simultaneos (40 conexoes)
    # coincidiram com o servidor de metadados da Esri recusando conexoes ("Remote end closed").
    from concurrent.futures import ThreadPoolExecutor
    zooms = [int(z) for z in (WAYBACK_ZOOMS if zooms == 'all' else zooms)]
    with ThreadPoolExecutor(max_workers=min(2, len(zooms))) as pool:
        per_zoom = list(pool.map(lambda z: [dict(v, zoom=z) for v in esri_core.local_versions_cached(bbox, z)], zooms))
    versions = [v for vs in per_zoom for v in vs]
    versions.sort(key=lambda v: (v.get('capture_date') or '', v['zoom']), reverse=True)
    return {'success': True, 'versions': versions, 'count': len(versions)}


WAYBACK_ZOOMS = (15, 16, 17, 18, 19)


def src_gehist_dates(p):
    """Datas do catalogo historico do Google Earth (protocolo Keyhole) na area."""
    import gehist_core
    zooms = p.get('zooms')
    if zooms == 'all':
        zooms = gehist_core.ALL_ZOOMS
    if zooms:
        dates = gehist_core.list_dates_multi(_resolve_bbox(p), [int(z) for z in zooms], workers=p.get('workers'))
    else:
        dates = gehist_core.list_dates(_resolve_bbox(p), int(p.get('zoom', 18)), workers=p.get('workers'))
    return {'success': True, 'dates': dates, 'count': len(dates), 'summary': gehist_core.summarize(dates)}


def src_gehist_download(p):
    """Imagem historica do Google Earth de uma data exata (grade nativa EPSG:4326)."""
    import gehist_core
    res = gehist_core.download(_resolve_bbox(p), int(p.get('zoom', 18)), p.get('date'), p.get('out'),
                               compression=p.get('compression', 'JPEG'), target_crs=p.get('crs') or None,
                               workers=p.get('workers'))
    providers = u', '.join(res.get('providers') or []) or p.get('providers') or u''
    res.update(success=True, capture_summary=u"%s%s" % (p['date'], u" (%s)" % providers if providers else u''))
    try:
        gehist_core.write_tags(res['file'], p['date'], providers, res['coverage_pct'], res.get('catalog_date'))
    except Exception:
        pass  # sem GDAL: o GeoTIFF continua valido, so sem as tags de data
    return res


def src_gehist_thumb(p):
    import gehist_core
    return dict(gehist_core.thumbnail(_resolve_bbox(p), int(p.get('zoom', 18)), p.get('date'), p.get('out')),
                success=True)


def src_wayback_thumb(p):
    """Previa de uma versao Wayback: ate 3x3 tiles no centro da area, no zoom da busca."""
    import io as _io
    import esri_core
    import xyz_core
    from PIL import Image
    import tilemath
    bbox = _resolve_bbox(p)
    zoom = int(p.get('zoom', 17))
    release = esri_core.release_by_num(p['wayback_release'])
    prov = xyz_core.get_provider(release['tile_url'])
    x0, x1, y0, y1 = tilemath.tile_range(bbox, zoom)
    cx, cy = tilemath.lonlat_to_tile((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0, zoom)
    xs = [x for x in range(cx - 1, cx + 2) if x0 <= x <= x1]
    ys = [y for y in range(cy - 1, cy + 2) if y0 <= y <= y1]
    canvas = Image.new('RGB', (len(xs) * 256, len(ys) * 256), (0, 0, 0))
    got = 0
    for j, y in enumerate(ys):
        for i, x in enumerate(xs):
            data = xyz_core.fetch_tile(xyz_core.tile_url(prov, x, y, zoom), retries=2)
            if data:
                with Image.open(_io.BytesIO(data)) as im:
                    canvas.paste(im.convert('RGB').resize((256, 256)), (i * 256, j * 256))
                got += 1
    if not got:
        raise ValueError(u"A versão Wayback não tem imagem no centro da área.")
    out = p.get('out')
    canvas.save(out, 'PNG')
    gif = os.path.splitext(out)[0] + '.gif'
    canvas.save(gif, 'GIF')
    return {'success': True, 'file': out, 'gif': gif, 'tiles': got}


def src_stac_search(p):
    import stac_core
    items = stac_core.search(
        p.get('collections') or p.get('collection'), _resolve_bbox(p),
        start_date=p.get('start_date'), end_date=p.get('end_date'),
        max_cloud=p.get('max_cloud'), max_items=int(p.get('max_items', 100)),
        min_coverage=float(p['min_coverage']) if p.get('min_coverage') not in (None, '') else 0.5)
    return {'success': True, 'items': items, 'count': len(items)}


def src_stac_thumb(p):
    import stac_core
    return dict(stac_core.thumbnail(p.get('collection'), p.get('item_id'), out_png=p.get('out'),
                                    href=p.get('href')), success=True)


def src_stac_download(p):
    import stac_core
    return dict(stac_core.download(p.get('collection'), p.get('item_id'), _resolve_bbox(p),
                                   out_tif=p.get('out'), mode=p.get('mode', 'rgb')), success=True)


SOURCE_COMMANDS = {
    'sources_info': src_sources_info,
    'xyz_estimate': src_xyz_estimate,
    'xyz_download': src_xyz_download,
    'stac_search': src_stac_search,
    'stac_thumb': src_stac_thumb,
    'stac_download': src_stac_download,
    'esri_dates': src_esri_dates,
    'esri_versions': src_esri_versions,
    'gehist_dates': src_gehist_dates,
    'gehist_download': src_gehist_download,
    'gehist_thumb': src_gehist_thumb,
    'wayback_thumb': src_wayback_thumb,
}


def run_source_command(name, params):
    """Executa um comando de fonte adicional e imprime UMA linha JSON (contrato com a ponte Py2)."""
    try:
        result = SOURCE_COMMANDS[name](params)
    except Exception as e:
        result = {'success': False, 'message': str(e)}
    sys.stdout.write(json.dumps(result) + "\n")
    sys.stdout.flush()
    sys.stderr.flush()
    # O GDAL/curl pode manter threads que travam o encerramento normal do interpretador
    # (observado com /vsicurl/). Todo o resultado ja foi entregue: encerrar imediatamente.
    hard_exit(0 if result.get('success') else 1)


def hard_exit(code):
    """Encerra o processo sem esperar a limpeza do interpretador.

    Causa raiz do travamento de 5 a 15 min apos um recorte CBERS (medido: recorte em 4 s, processo
    vivo por 300-900 s): conexoes /vsicurl/ do GDAL ainda abertas com o servidor do INPE. O Windows
    so encerra o processo depois de cancelar essa E/S de rede - nem os._exit nem TerminateProcess
    adiantam. Fechar as conexoes antes (VSICurlClearCache) faz o processo sair na hora."""
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    gdal_mod = sys.modules.get('osgeo.gdal')
    if gdal_mod is not None:
        try:
            gdal_mod.VSICurlClearCache()
        except Exception:
            pass
    if os.name == 'nt':
        try:
            import ctypes
            k32 = ctypes.windll.kernel32
            k32.TerminateProcess(k32.GetCurrentProcess(), int(code))
        except Exception:
            pass
    os._exit(code)


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

    # Suporte a passagem de argumentos via arquivo JSON UTF-8 (--params-file)
    parser.add_argument("--params-file", default=None, help="Caminho para arquivo JSON UTF-8 com argumentos")

    for p in [p_check, p_auth, p_comp, p_search, p_thumb, p_dl]:
        p.add_argument("--params-file", default=None, help="Caminho para arquivo JSON UTF-8 com argumentos")

    params_file = None
    for i, a in enumerate(sys.argv):
        if a.startswith("--params-file="):
            params_file = a.split("=", 1)[1]
            break
        elif a == "--params-file" and i + 1 < len(sys.argv):
            params_file = sys.argv[i + 1]
            break

    if params_file and os.path.exists(params_file):
        with open(params_file, "r", encoding="utf-8") as pf:
            data = json.load(pf)
        cmd_name = data.get("command")
        if not cmd_name and len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
            cmd_name = sys.argv[1]
        if cmd_name in SOURCE_COMMANDS:
            run_source_command(cmd_name, data)
            return
        
        cli_tokens = [cmd_name] if cmd_name else []
        for k, v in data.items():
            if k == "command" or v is None:
                continue
            flag = "--" + k.replace("_", "-")
            cli_tokens.append("%s=%s" % (flag, str(v)))
        args = parser.parse_args(cli_tokens)
    else:
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
