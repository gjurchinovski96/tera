# Tera Elements

Website for Tera Elements – handmade walnut serving boards – with an admin panel for managing products.

## Run it

Needs Python 3.8+ (standard library only, nothing to install).

```bash
python server.py
```

- Site: http://localhost:8001
- Admin: http://localhost:8001/admin

Use another port with `PORT=8002 python server.py` (PowerShell: `$env:PORT=8002; python server.py`).
The server listens on 127.0.0.1 only; set `HOST=0.0.0.0` when deploying behind a reverse proxy.

## Admin login

The dev password is `tera-dev` (from `config.example.json`). To set your own, copy the example and edit it:

```bash
cp config.example.json config.json
```

```json
{
  "admin_password": "your-strong-password",
  "secret_key": "any long random string"
}
```

`config.json` is git-ignored and overrides the example. `secret_key` signs the login cookie; set it so logins survive server restarts.
You can instead set the environment variables `TERA_ADMIN_PASSWORD` and `TERA_SECRET_KEY`.
Restart the server after changing the config.

## Editing products

Log in at `/admin`. On the left is the product list, on the right the editor.

- **Edit**: click a product, change name, price, subtitle, description, details, then **Зачувај** (Save).
- **Availability**: *На залиха* / *Нема на залиха* (in / out of stock). Optionally set a stock quantity; leave it empty to not track stock, `0` means sold out.
  Sold-out products show "Нема на залиха" in the shop and cannot be added to the cart. Customers can't add more than the stock quantity.
- **Images**: upload JPG/PNG/WebP (saved into `img/`) or choose a photo already in `img/`. The first image is the main one; the second shows on hover in the shop. Use the arrows to reorder.
- **Order**: drag products in the list (or use ▲ ▼); the shop shows them in that order. Saved immediately.
- **Home page bestsellers**: tick "Прикажи во Најпродавани"; the first three ticked products are shown.
- **Add / delete**: **+ Нов** creates a product, **Избриши** deletes it.
- **English version**: the site has an МК | EN switch (remembered per browser). Each product has an "Англиска верзија (EN)" section;
  empty English fields fall back to the Macedonian text. Interface texts for both languages are in the `T` table in `index.html`.

The free-delivery threshold is `FREE_SHIPPING` near the top of the `<script>` in `index.html`.

Changes are visible on the site after a page refresh.

## Files

- `server.py` – serves the site, the product API and the admin
- `index.html` – the whole public site (home, shop, product pages, cart, checkout, contact, about); loads products from `/api/products`
- `admin/index.html` – the admin panel
- `data/products.json` – the products (written by the admin; back it up)
- `img/` – product photos, hero image and logo; uploads land here too
- `config.example.json` – dev config; your own goes in `config.json`

## Deploying

Any host that can run a Python process works (VPS, PythonAnywhere, Render, Railway…). Run `python server.py` behind HTTPS
(e.g. nginx or Caddy as a reverse proxy) and make sure `data/` and `img/` are on persistent storage, since the admin writes there.
GitHub Pages or other static-only hosts can't run the admin.
