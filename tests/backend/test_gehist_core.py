# -*- coding: utf-8 -*-
"""Google Earth historico (gehist_core): protocolo Keyhole simulado, grade EPSG:4326 e GeoTIFF."""
import io
import os
import random
import shutil
import tempfile
import unittest
import zlib

import _paths
import gehist_core as gh
import tilemath

LEVEL = 6                                  # tiles de 5,625 graus; caminho com 7 digitos (1 salto)
BBOX = [-60.0, -16.0, -50.0, -10.0]        # 3 colunas x 2 linhas no nivel 6
DATE_A, DATE_B = (2019, 5, 10), (2022, 6, 28)
EPOCH_PACKET, EPOCH_TILE = 77, 308


def catalog(year, month, day):
    """Codigo do catalogo para uma data EXIBIDA (Google Earth Pro): o catalogo guarda o dia seguinte."""
    import datetime
    d = datetime.date(year, month, day) + datetime.timedelta(days=1)
    return gh.encode_date(d.year, d.month, d.day)


def _no_default_cache():
    raise AssertionError(r"teste tentou usar o cache real do usuario (%LOCALAPPDATA%\ArcMagery\cache)")


gh.default_cache_dir = _no_default_cache   # pacotes simulados nunca podem contaminar o cache real


# ------------------------------------------------------------------- codificacao protobuf
def varint(v):
    out = bytearray()
    while True:
        b = v & 0x7F
        v >>= 7
        if v:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def field(num, wire, value=None):
    tag = varint((num << 3) | wire)
    if wire == 0:
        return tag + varint(value)
    if wire == 2:
        return tag + varint(len(value)) + value
    return tag                                  # 3/4: inicio/fim de grupo


def node_bytes(epoch=0, dates=()):
    """dates: inteiros de data (provedor 308) ou tuplas (data, provedor)."""
    body = field(1, 0, 0) + field(2, 0, epoch)
    if dates:
        dates = [d if isinstance(d, tuple) else (d, 308) for d in dates]
        dates_b = b''.join(field(1, 2, field(1, 0, d) + field(2, 0, EPOCH_TILE) + field(3, 0, prov))
                           for d, prov in dates)
        body += field(3, 2, field(4, 2, dates_b))
    return body


def packet_bytes(nodes):
    return b''.join(field(1, 3) + field(3, 0, idx) + field(4, 2, nb) + field(1, 4) for idx, nb in nodes.items())


def reference_xor(key, data):
    """Algoritmo original do historical_engine.py (byte a byte)."""
    cipher, off = bytearray(data), 16
    for j in range(len(cipher)):
        cipher[j] ^= key[off]
        off += 1
        if (off & 7) == 0:
            off += 16
        if off >= len(key):
            off = (off + 8) % 24
    return bytes(cipher)


class FakeKeyhole(object):
    """Servidor simulado: tiles com DATE_A em toda a grade e DATE_B so na linha norte."""

    def __init__(self):
        rnd = random.Random(7)
        self.key = bytes(rnd.randrange(256) for _ in range(1016))
        self.win = tilemath.keyhole_crop_window(BBOX, LEVEL)
        self.tiles = {}
        root, children = {}, {}
        for r in range(self.win['r0'], self.win['r1'] + 1):
            for c in range(self.win['c0'], self.win['c1'] + 1):
                path = tilemath.keyhole_quadtree_path(r, c, LEVEL)
                dates = [catalog(*DATE_A), (catalog(2023, 1, 1), gh.BASE_IMAGERY_PROVIDER)]
                if r == self.win['r1']:
                    dates.append(catalog(*DATE_B))
                self.tiles[path] = (r, c)
                root[gh.quadtree_subindex(path[:4])] = node_bytes(epoch=EPOCH_PACKET)
                children.setdefault(path[:4], {})[gh.quadtree_subindex(path)] = node_bytes(dates=dates)
        self.packets = {('0', 370): packet_bytes(root)}
        for prefix, nodes in children.items():
            self.packets[(prefix, EPOCH_PACKET)] = packet_bytes(nodes)
        self.requests = []

    def enc_packet(self, data):
        return reference_xor(self.key, b'\x00' * 8 + zlib.compress(data))

    def color(self, r, c):
        return (40 * (c - self.win['c0']) + 20, 90 * (self.win['r1'] - r) + 20, 150)

    def jpeg(self, r, c):
        from PIL import Image
        buf = io.BytesIO()
        Image.new('RGB', (256, 256), self.color(r, c)).save(buf, 'JPEG', quality=95)
        return buf.getvalue()

    def fetch(self, url):
        self.requests.append(url)
        q = url.split('?', 1)[1]
        if q.startswith('db=tm&hl'):
            db = field(13, 2, field(1, 0, 370))
            return field(2, 2, self.key) + field(3, 2, self.enc_packet(db))
        kind, rest = q.split('&', 1)[1].split('-', 1)
        if kind == 'qp':
            path, epoch = rest.split('-q.')
            data = self.packets.get((path, int(epoch)))
            return self.enc_packet(data) if data is not None else None
        path, tail = rest.split('-i.')
        epoch, date_hex = tail.split('-')
        if path not in self.tiles or int(epoch) != EPOCH_TILE:
            return None
        return reference_xor(self.key, self.jpeg(*self.tiles[path]))


class ProtocolTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='arcmagery_gehist_')
        self.srv = FakeKeyhole()
        self.client = gh.KeyholeClient(cache_dir=os.path.join(self.tmp, 'cache'), fetch=self.srv.fetch)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_vectorized_decrypt_matches_original_algorithm(self):
        data = bytes(random.Random(1).randrange(256) for _ in range(200000))
        self.assertEqual(self.client.decrypt(data), reference_xor(self.srv.key, data))
        self.assertEqual(self.client.decrypt(data[:100]), reference_xor(self.srv.key, data[:100]))

    def test_google_earth_pro_date_convention(self):
        # conferido pelo mantenedor no Google Earth Pro: catalogo 2017-07-09 = 8/7/2017; 2022-06-28 = 27/6/2022
        self.assertEqual(gh.google_earth_date('2017-07-09'), '2017-07-08')
        self.assertEqual(gh.google_earth_date('2022-06-28'), '2022-06-27')
        self.assertEqual(gh.google_earth_date('2020-03-01'), '2020-02-29')
        self.assertEqual(gh.google_earth_date('2021-01-01'), '2020-12-31')
        layers = gh.parse_dated_layers(gh.parse_node(tg_node := node_bytes(dates=[gh.encode_date(2017, 7, 9)])))
        self.assertEqual((layers[0]['date'], layers[0]['catalog_date']), ('2017-07-08', '2017-07-09'))

    def test_dbroot_and_dates(self):
        self.assertEqual(self.client.quadtree_version, 370)
        self.assertEqual(gh.decode_date(gh.encode_date(2019, 5, 10)), '2019-05-10')
        dates = gh.list_dates(BBOX, LEVEL, client=self.client)
        self.assertEqual([d['date'] for d in dates], ['2022-06-28', '2019-05-10'])
        self.assertEqual((dates[1]['coverage_pct'], dates[1]['total_tiles']), (100.0, 6))
        self.assertEqual(dates[0]['coverage_pct'], 50.0)                   # so a linha norte
        self.assertEqual(dates[0]['provider'], 'Maxar Technologies')
        # provedor 0 (imagem-base atual) nao e baixavel pelo catalogo historico: nunca listar
        self.assertNotIn('2023-01-01', [d['date'] for d in dates])

    def test_packets_cached_on_disk(self):
        child = lambda: [u for u in self.srv.requests if 'qp-' in u and 'qp-0-' not in u]
        root = lambda: [u for u in self.srv.requests if 'qp-0-' in u]
        gh.list_dates(BBOX, LEVEL, client=self.client)
        n = len(child())
        other = gh.KeyholeClient(cache_dir=os.path.join(self.tmp, 'cache'), fetch=self.srv.fetch)
        gh.list_dates(BBOX, LEVEL, client=other)
        self.assertEqual(len(child()), n)          # pacotes filhos vieram do disco
        self.assertEqual(len(root()), 2)           # o raiz nunca e cacheado em disco

    def test_corrupted_cache_file_is_refetched(self):
        cache = os.path.join(self.tmp, 'cache')
        gh.list_dates(BBOX, LEVEL, client=self.client)
        for name in os.listdir(cache):
            with open(os.path.join(cache, name), 'wb') as f:
                f.write(b'\xff\xff\xff')
        other = gh.KeyholeClient(cache_dir=cache, fetch=self.srv.fetch)
        self.assertEqual(len(gh.list_dates(BBOX, LEVEL, client=other)), 2)

    def test_quadtree_path_and_grid(self):
        self.assertEqual(tilemath.keyhole_quadtree_path(0, 0, 3), '0000')
        self.assertEqual(tilemath.keyhole_quadtree_path(5, 9, 4), '01302')
        r0, r1, c0, c1 = tilemath.keyhole_tile_range(BBOX, LEVEL)
        self.assertEqual((r1 - r0 + 1, c1 - c0 + 1), (2, 3))
        # borda exatamente no limite do tile nao inclui o vizinho
        deg = tilemath.keyhole_tile_deg(LEVEL)
        edge = [c0 * deg - 180, r0 * deg - 180, (c0 + 1) * deg - 180, (r0 + 1) * deg - 180]
        self.assertEqual(tilemath.keyhole_tile_range(edge, LEVEL), (r0, r0, c0, c0))

    def test_keyhole_grid_is_not_web_mercator(self):
        """Regressao do bug da v2.3.3-dev: a grade historica e geografica, nao XYZ."""
        big = [-56.3, -15.9, -55.9, -15.6]
        kh = tilemath.keyhole_estimate(big, 18)
        xyz = tilemath.estimate(big, 18)
        self.assertNotEqual(kh['rows'], xyz['rows'])
        self.assertEqual(kh['cols'], xyz['cols'])

    def test_limits_and_validation(self):
        with self.assertRaises(ValueError):
            gh.download(BBOX, LEVEL, '28/06/2022', os.path.join(self.tmp, 'x.tif'), client=self.client)
        with self.assertRaises(ValueError):
            gh.list_dates([-60, -20, -40, 0], 16, client=self.client)
        with self.assertRaises(RuntimeError):
            gh.download(BBOX, LEVEL, '2001-01-01', os.path.join(self.tmp, 'y.tif'), client=self.client)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, 'y.tif.part.tif')))


class DownloadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='arcmagery_gehist_')
        self.srv = FakeKeyhole()
        self.client = gh.KeyholeClient(cache_dir='', fetch=self.srv.fetch)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _check_origin(self, left, top):
        """Origem encaixada na grade de pixels: no maximo 1 pixel fora do BBOX, nunca dentro."""
        res = self.srv.win['res']
        self.assertTrue(left <= BBOX[0] < left + res, (left, BBOX[0]))
        self.assertTrue(top - res < BBOX[3] <= top, (top, BBOX[3]))

    def _check_pixels(self, px):
        """px(col, row) -> RGB. Canto NO vem do tile (r1, c0); canto SE do tile (r0, c1)."""
        win = self.srv.win
        for (col, row), tile in (((0, 0), (win['r1'], win['c0'])),
                                 ((win['width'] - 1, win['height'] - 1), (win['r0'], win['c1']))):
            got, exp = px(col, row), self.srv.color(*tile)
            for g, e in zip(got, exp):
                self.assertLess(abs(g - e), 6, (col, row, got, exp))

    def test_pil_engine_native_4326(self):
        from PIL import Image
        out = os.path.join(self.tmp, 'h.tif')
        res = gh.download(BBOX, LEVEL, '2019-05-10', out, compression='LZW', client=self.client, engine='pil')
        win = self.srv.win
        self.assertEqual((res['crs'], res['coverage_pct'], res['tiles_with_date']), ('EPSG:4326', 100.0, 6))
        with open(os.path.splitext(out)[0] + '.tfw') as f:
            tfw = [float(v) for v in f.read().split()]
        self.assertAlmostEqual(tfw[4] - win['res'] / 2, win['left'], places=6)
        self.assertAlmostEqual(tfw[5] + win['res'] / 2, win['top'], places=6)
        self._check_origin(win['left'], win['top'])
        with open(os.path.splitext(out)[0] + '.prj') as f:
            self.assertIn('GCS_WGS_1984', f.read())
        with Image.open(out) as im:
            self.assertEqual(im.size, (win['width'], win['height']))
            self._check_pixels(lambda c, r: im.getpixel((c, r)))

    def test_partial_date_leaves_black_and_reports_coverage(self):
        from PIL import Image
        out = os.path.join(self.tmp, 'p.tif')
        res = gh.download(BBOX, LEVEL, '2022-06-28', out, compression='LZW', client=self.client, engine='pil')
        self.assertGreater(res['coverage_pct'], 5.0)
        self.assertLess(res['coverage_pct'], 95.0)
        with Image.open(out) as im:
            self.assertEqual(im.getpixel((im.width - 1, im.height - 1)), (0, 0, 0))

    def test_thumbnail_uses_center_tiles_of_the_date(self):
        from PIL import Image
        res = gh.thumbnail(BBOX, LEVEL, '2019-05-10', os.path.join(self.tmp, 't.png'), client=self.client)
        self.assertTrue(os.path.exists(res['gif']))
        with Image.open(res['file']) as im:
            self.assertEqual(im.size, (3 * 256, 2 * 256))           # grade 3 x 2 inteira cabe no 3 x 3
        with self.assertRaises(RuntimeError):
            gh.thumbnail(BBOX, LEVEL, '2001-01-01', os.path.join(self.tmp, 'u.png'), client=self.client)

    @unittest.skipUnless(_paths.HAS_GDAL, "requer GDAL")
    def test_gdal_engine_geotransform_tags_and_reprojection(self):
        from osgeo import gdal
        out = os.path.join(self.tmp, 'g.tif')
        gh.download(BBOX, LEVEL, '2019-05-10', out, compression='LZW', client=self.client, engine='gdal')
        ds = gdal.Open(out)
        gt = ds.GetGeoTransform()
        win = self.srv.win
        self.assertAlmostEqual(gt[0], win['left'], places=9)
        self.assertAlmostEqual(gt[3], win['top'], places=9)
        self.assertAlmostEqual(gt[1], win['res'], places=12)
        self._check_origin(gt[0], gt[3])
        self.assertEqual(ds.GetSpatialRef().GetAuthorityCode(None), '4326')
        arr = ds.ReadAsArray()
        self._check_pixels(lambda c, r: [int(v) for v in arr[:, r, c]])
        ds = None
        gh.write_tags(out, '2019-05-10', 'Maxar', 100.0)
        self.assertEqual(gdal.Open(out).GetMetadataItem('ACQUISITION_DATE'), '2019-05-10')
        out3857 = os.path.join(self.tmp, 'g3857.tif')
        res = gh.download(BBOX, LEVEL, '2019-05-10', out3857, target_crs='EPSG:3857', client=self.client)
        self.assertEqual(res['crs'], 'EPSG:3857')
        self.assertEqual(gdal.Open(out3857).GetSpatialRef().GetAuthorityCode(None), '3857')


@unittest.skipUnless(_paths.LIVE, "defina ARCMAGERY_LIVE=1 (acessa o Google Earth)")
class LiveTest(unittest.TestCase):
    BBOX = [-59.36, -10.25, -59.33, -10.22]

    def test_list_and_download(self):
        tmp = tempfile.mkdtemp(prefix='arcmagery_gehist_live_')
        try:
            client = gh.KeyholeClient(cache_dir=os.path.join(tmp, 'cache'))
            dates = gh.list_dates(self.BBOX, 15, client=client)
            self.assertTrue(dates)
            full = [d for d in dates if d['coverage_pct'] >= 99.9][0]
            res = gh.download(self.BBOX, 15, full['date'], os.path.join(tmp, 'live.tif'), client=client)
            self.assertGreater(res['coverage_pct'], 99.0)
            self.assertTrue(os.path.getsize(res['file']) > 1000)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
