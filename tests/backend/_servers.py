# -*- coding: utf-8 -*-
"""Servidores HTTP locais para os testes do backend (sem internet).

- TileServer: provedor XYZ falso. Cada tile tem cor unica (x % 256, y % 256, z * 10) para
  verificar a posicao no mosaico; suporta 404, falhas 503 temporarias e contagem de acessos.
- RangeFileServer: serve arquivos locais com suporte a HTTP Range (necessario ao /vsicurl/).
- StacServer: /search com paginacao (link 'next' via POST) e /collections/<c>/items/<id>.
"""
import io
import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _Base(object):
    def __init__(self, handler_cls):
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), handler_cls)
        self.httpd.owner = self
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def base(self):
        return 'http://127.0.0.1:%d' % self.port

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


class _TileHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        owner = self.server.owner
        m = re.match(r'^/(\d+)/(\d+)/(\d+)\.(png|jpg)$', self.path)
        if not m:
            self.send_error(400)
            return
        z, x, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        with owner.lock:
            owner.hits[(x, y)] = owner.hits.get((x, y), 0) + 1
            n = owner.hits[(x, y)]
        if (x, y) in owner.missing:
            self.send_error(404)
            return
        if owner.flaky.get((x, y), 0) >= n:
            self.send_error(503)
            return
        if (x, y) in owner.garbage:
            body = b'<html>erro</html>'
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
        else:
            from PIL import Image
            im = Image.new('RGB', (owner.tile_size, owner.tile_size), (x % 256, y % 256, (z * 10) % 256))
            buf = io.BytesIO()
            im.save(buf, 'PNG')
            body = buf.getvalue()
            self.send_response(200)
            self.send_header('Content-Type', 'image/png')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class TileServer(_Base):
    def __init__(self, tile_size=256, missing=(), flaky=None, garbage=()):
        self.tile_size = tile_size
        self.missing = set(missing)
        self.flaky = dict(flaky or {})   # {(x, y): numero_de_503_antes_de_responder}
        self.garbage = set(garbage)
        self.hits = {}
        self.lock = threading.Lock()
        super(TileServer, self).__init__(_TileHandler)

    @property
    def template(self):
        return self.base + '/{z}/{x}/{y}.png'


class _RangeHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _resolve(self):
        path = os.path.join(self.server.owner.root, self.path.lstrip('/').split('?')[0])
        return path if os.path.isfile(path) else None

    def do_HEAD(self):
        path = self._resolve()
        if not path:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Length', str(os.path.getsize(path)))
        self.send_header('Accept-Ranges', 'bytes')
        self.end_headers()

    def do_GET(self):
        path = self._resolve()
        if not path:
            self.send_error(404)
            return
        size = os.path.getsize(path)
        rng = self.headers.get('Range')
        with open(path, 'rb') as f:
            if rng:
                m = re.match(r'bytes=(\d+)-(\d*)', rng)
                start = int(m.group(1))
                end = min(int(m.group(2)) if m.group(2) else size - 1, size - 1)
                f.seek(start)
                data = f.read(end - start + 1)
                self.send_response(206)
                self.send_header('Content-Range', 'bytes %d-%d/%d' % (start, end, size))
            else:
                data = f.read()
                self.send_response(200)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Accept-Ranges', 'bytes')
            self.end_headers()
            self.wfile.write(data)


class RangeFileServer(_Base):
    def __init__(self, root):
        self.root = root
        super(RangeFileServer, self).__init__(_RangeHandler)


class _StacHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/geo+json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        owner = self.server.owner
        if self.path != '/search':
            self.send_error(404)
            return
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))).decode('utf-8'))
        owner.requests.append(body)
        if getattr(owner, 'fail_intersects', False) and 'intersects' in body:
            self._json({'code': 'InternalServerError'}, code=500)   # como o INPE nos mosaicos
            return
        page = int(body.get('page', 1))
        limit = int(body.get('limit', 10))
        feats = [f for f in owner.features if f['collection'] in body.get('collections', [])]
        chunk = feats[(page - 1) * limit: page * limit]
        links = []
        if page * limit < len(feats):
            links.append({'rel': 'next', 'href': self.server.owner.base + '/search', 'method': 'POST',
                          'body': {'page': page + 1}, 'merge': True})
        self._json({'type': 'FeatureCollection', 'features': chunk, 'links': links})

    def do_GET(self):
        owner = self.server.owner
        m = re.match(r'^/collections/([^/]+)/items/([^/?]+)$', self.path)
        if m:
            for f in owner.features:
                if f['collection'] == m.group(1) and f['id'] == m.group(2):
                    self._json(f)
                    return
        self.send_error(404)


class StacServer(_Base):
    def __init__(self, features):
        self.features = features
        self.requests = []
        super(StacServer, self).__init__(_StacHandler)
