"""Tera Elements – site + admin server.

Standard library only. Run:  python server.py   (then open http://localhost:8001)

- Serves index.html, img/ and the admin page at /admin
- Products live in data/products.json
- Admin login password comes from config.json (copy config.example.json),
  or the TERA_ADMIN_PASSWORD environment variable.
"""
import base64
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import threading
import time
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

ROOT = os.path.dirname(os.path.realpath(__file__))
DATA_FILE = os.path.join(ROOT, 'data', 'products.json')
IMG_DIR = os.path.join(ROOT, 'img')
IMG_EXT = {'.jpg', '.jpeg', '.png', '.webp'}
MAX_UPLOAD = 10 * 1024 * 1024
SESSION_HOURS = 12
COOKIE = 'tera_admin'


def load_config():
    cfg = {}
    for name in ('config.example.json', 'config.json'):
        path = os.path.join(ROOT, name)
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                cfg.update(json.load(f))
    if os.environ.get('TERA_ADMIN_PASSWORD'):
        cfg['admin_password'] = os.environ['TERA_ADMIN_PASSWORD']
    if os.environ.get('TERA_SECRET_KEY'):
        cfg['secret_key'] = os.environ['TERA_SECRET_KEY']
    # Without a configured key, sessions last until the server restarts.
    cfg['secret_key'] = (cfg.get('secret_key') or secrets.token_hex(32)).encode()
    return cfg


CONFIG = load_config()
LOCK = threading.Lock()


# ---------- products store ----------

def read_products():
    with open(DATA_FILE, encoding='utf-8') as f:
        return json.load(f)


def write_products(products):
    tmp = DATA_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(products, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)


TRANSLIT = dict(zip('абвгдѓежзѕијклљмнњопрстќуфхцчџш',
                    ['a', 'b', 'v', 'g', 'd', 'gj', 'e', 'zh', 'z', 'dz', 'i', 'j', 'k', 'l', 'lj', 'm', 'n', 'nj',
                     'o', 'p', 'r', 's', 't', 'kj', 'u', 'f', 'h', 'c', 'ch', 'dj', 'sh']))


def make_id(name, taken):
    slug = ''.join(TRANSLIT.get(c, c) for c in name.lower())
    slug = re.sub(r'[^a-z0-9]+', '-', slug).strip('-')[:40] or 'product'
    pid, n = slug, 2
    while pid in taken:
        pid, n = f'{slug}-{n}', n + 1
    return pid


def clean_product(data):
    """Validate admin input; returns (product_fields, error)."""
    name = str(data.get('name', '')).strip()
    if not name:
        return None, 'Name is required.'
    try:
        price = int(round(float(data.get('price'))))
    except (TypeError, ValueError):
        return None, 'Price must be a number.'
    if price < 0:
        return None, 'Price cannot be negative.'
    qty = data.get('quantity')
    if qty in (None, ''):
        qty = None
    else:
        try:
            qty = int(qty)
        except (TypeError, ValueError):
            return None, 'Quantity must be a whole number.'
        if qty < 0:
            return None, 'Quantity cannot be negative.'
    images = []
    for src in data.get('images') or []:
        src = str(src)
        if not src.startswith('img/') or not os.path.isfile(safe_path(src) or ''):
            return None, f'Image not found: {src}'
        images.append(src)
    text = lambda k: str(data.get(k) or '').strip()
    return {
        'name': name, 'subtitle': text('subtitle'), 'price': price, 'desc': text('desc'),
        'material': text('material'), 'dims': text('dims'), 'lead': text('lead'), 'care': text('care'),
        'in_stock': bool(data.get('in_stock', True)), 'quantity': qty,
        'featured': bool(data.get('featured')), 'images': images,
        **{k + '_en': text(k + '_en') for k in EN_FIELDS},
    }, None


# English versions of these fields are optional; the site falls back to Macedonian.
EN_FIELDS = ('name', 'subtitle', 'desc', 'material', 'lead', 'care')


def safe_path(rel):
    """Resolve a site-relative path inside ROOT, or None."""
    full = os.path.realpath(os.path.join(ROOT, rel))
    return full if full.startswith(ROOT + os.sep) else None


# ---------- sessions ----------

def sign(value):
    return hmac.new(CONFIG['secret_key'], value.encode(), hashlib.sha256).hexdigest()


def new_session():
    exp = str(int(time.time()) + SESSION_HOURS * 3600)
    return f'{exp}.{sign(exp)}'


def valid_session(token):
    exp, _, sig = (token or '').partition('.')
    return exp.isdigit() and hmac.compare_digest(sig, sign(exp)) and int(exp) > time.time()


# ---------- HTTP ----------

class Handler(BaseHTTPRequestHandler):
    server_version = 'Tera/1.0'

    def log_message(self, fmt, *args):
        print('%s %s' % (self.address_string(), fmt % args))

    # responses
    def send_json(self, obj, status=200, headers=None):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def error(self, msg, status=400):
        self.send_json({'error': msg}, status)

    def send_file(self, path, cache='no-cache'):
        if not path or not os.path.isfile(path):
            return self.error('Not found', 404)
        ctype = mimetypes.guess_type(path)[0] or 'application/octet-stream'
        if ctype.startswith('text/'):
            ctype += '; charset=utf-8'
        with open(path, 'rb') as f:
            body = f.read()
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', cache)
        self.end_headers()
        self.wfile.write(body)

    # request helpers
    def body_json(self):
        if 'application/json' not in (self.headers.get('Content-Type') or ''):
            raise ValueError('Expected JSON')
        n = int(self.headers.get('Content-Length') or 0)
        if n > MAX_UPLOAD * 1.4:
            raise ValueError('Request too large')
        return json.loads(self.rfile.read(n) or b'{}')

    def is_admin(self):
        c = cookies.SimpleCookie(self.headers.get('Cookie') or '')
        return COOKIE in c and valid_session(c[COOKIE].value)

    @property
    def path_only(self):
        return unquote(urlsplit(self.path).path)

    # routing
    def do_GET(self):
        p = self.path_only
        if p in ('/', '/index.html'):
            return self.send_file(os.path.join(ROOT, 'index.html'))
        if p in ('/admin', '/admin/'):
            return self.send_file(os.path.join(ROOT, 'admin', 'index.html'))
        if p.startswith('/img/'):
            path = safe_path(p[1:])
            if path and os.path.splitext(path)[1].lower() in IMG_EXT:
                return self.send_file(path, 'public, max-age=300')
            return self.error('Not found', 404)
        if p == '/api/products':
            with LOCK:
                return self.send_json(read_products())
        if p == '/api/admin/me':
            return self.send_json({'admin': self.is_admin()})
        if p == '/api/admin/images':
            if not self.is_admin():
                return self.error('Login required', 401)
            files = sorted(f for f in os.listdir(IMG_DIR)
                           if os.path.splitext(f)[1].lower() in IMG_EXT and f not in ('logo.png', 'hero.jpg'))
            return self.send_json(['img/' + f for f in files])
        self.error('Not found', 404)

    def do_POST(self):
        self.mutate('POST')

    def do_PUT(self):
        self.mutate('PUT')

    def do_DELETE(self):
        self.mutate('DELETE')

    def mutate(self, method):
        p = self.path_only
        try:
            data = self.body_json() if method != 'DELETE' else {}
        except ValueError as e:
            return self.error(str(e))

        if p == '/api/admin/login' and method == 'POST':
            pw = CONFIG.get('admin_password') or ''
            if pw and hmac.compare_digest(str(data.get('password', '')).encode(), pw.encode()):
                ck = f'{COOKIE}={new_session()}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_HOURS * 3600}'
                return self.send_json({'ok': True}, headers={'Set-Cookie': ck})
            time.sleep(1)  # slow down guessing
            return self.error('Wrong password', 401)
        if p == '/api/admin/logout' and method == 'POST':
            return self.send_json({'ok': True}, headers={'Set-Cookie': f'{COOKIE}=; Path=/; Max-Age=0'})

        if not self.is_admin():
            return self.error('Login required', 401)

        if p == '/api/admin/upload' and method == 'POST':
            return self.upload(data)

        with LOCK:
            products = read_products()
            if p == '/api/admin/products' and method == 'POST':
                fields, err = clean_product(data)
                if err:
                    return self.error(err)
                prod = {'id': make_id(fields['name'], {x['id'] for x in products}), **fields}
                products.append(prod)
                write_products(products)
                return self.send_json(prod, 201)
            if p == '/api/admin/order' and method == 'PUT':
                ids = data.get('ids') or []
                by_id = {x['id']: x for x in products}
                if sorted(ids) != sorted(by_id):
                    return self.error('Order must list every product once.')
                write_products([by_id[i] for i in ids])
                return self.send_json({'ok': True})
            m = re.fullmatch(r'/api/admin/products/([\w-]+)', p)
            if m:
                idx = next((i for i, x in enumerate(products) if x['id'] == m[1]), None)
                if idx is None:
                    return self.error('Product not found', 404)
                if method == 'PUT':
                    fields, err = clean_product(data)
                    if err:
                        return self.error(err)
                    products[idx] = {'id': m[1], **fields}
                    write_products(products)
                    return self.send_json(products[idx])
                if method == 'DELETE':
                    products.pop(idx)
                    write_products(products)
                    return self.send_json({'ok': True})
        self.error('Not found', 404)

    def upload(self, data):
        name = os.path.basename(str(data.get('name', '')))
        stem, ext = os.path.splitext(name)
        ext = ext.lower()
        if ext not in IMG_EXT:
            return self.error('Only JPG, PNG or WebP images.')
        try:
            raw = base64.b64decode(data.get('data', ''), validate=True)
        except ValueError:
            return self.error('Bad image data.')
        if not raw or len(raw) > MAX_UPLOAD:
            return self.error('Image must be under 10 MB.')
        if not (raw[:3] == b'\xff\xd8\xff' or raw[:8] == b'\x89PNG\r\n\x1a\n' or raw[8:12] == b'WEBP'):
            return self.error('File is not a valid image.')
        stem = re.sub(r'[^a-z0-9]+', '-', stem.lower()).strip('-')[:40] or 'photo'
        fname, n = stem + ext, 2
        while os.path.exists(os.path.join(IMG_DIR, fname)):
            fname, n = f'{stem}-{n}{ext}', n + 1
        with open(os.path.join(IMG_DIR, fname), 'wb') as f:
            f.write(raw)
        self.send_json({'path': 'img/' + fname}, 201)


def main():
    port = int(os.environ.get('PORT', 8001))
    host = os.environ.get('HOST', '127.0.0.1')
    if not CONFIG.get('admin_password'):
        print('Warning: no admin password set – the admin login is disabled.')
    elif not os.path.exists(os.path.join(ROOT, 'config.json')) and not os.environ.get('TERA_ADMIN_PASSWORD'):
        print('Note: using the dev password from config.example.json. Create config.json before going live.')
    print(f'Tera Elements on http://localhost:{port}  (admin: http://localhost:{port}/admin)')
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == '__main__':
    main()
