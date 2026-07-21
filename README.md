# Sistema de Costeo y Cotización

Web app for engineering/construction cost cards ("Fichas de Costo") and project quotes, built with a Python (Flask) backend, SQLite database, and a plain HTML/JS frontend — no build step required.

## What it does

1. **Catálogos** — maintain reference price lists for Materials, Labor, and Tools (code, description, unit, unit price). This is your "recent prices" list.
2. **Fichas de Costo** — build a unit cost card per activity: pull line items from the catalogs (or type manually), enter *Rendimiento* (quantity needed) and *Desperdicio %* (waste). The app calculates:
   - `Subtotal = Rendimiento × Precio Unitario`
   - `Total = Subtotal × (1 + Desperdicio%)`
   - Then totals Materials + Labor + Tools → Direct Cost → + Admin % + Utilidad % → **Costo Total** (the card's unit price).
3. **Cotizaciones** — build a project quote: select cost cards and enter quantities needed, add ad-hoc Transportation and Other fees, and get a project grand total (like your `Costo Total Proyecto` sheet).

All calculations happen in real Python code on the backend (see `backend/app.py`), so the logic is easy to audit or extend as your pricing rules change.

## Login and client accounts

`/cotizaciones/` and `/regulación/` now require logging in. The homepage (`/`) stays public.

Each **account = one client/company**, completely isolated from every other account — their own materials, labor, tools, transport, gastos, fichas, cotizaciones, and regulación studies. One account has one shared login (not individual logins per person within a company); if you need per-person logins inside one company later, that's a straightforward extension of this same structure.

### Creating a new client account

You create every account yourself — there's no public signup form. From the `backend` folder:

```bash
python3 create_account.py
```

It'll ask for the company name, a username, and a password (hidden as you type), then create the account. Give those credentials to the client — they log in at `/login`.

### Resetting a client's password

Passwords are stored as one-way hashes, so there's no way to look up or "recover" a forgotten one — only reset it to something new. From the `backend` folder:

```bash
python3 reset_password.py
```

It asks for the account's username, then a new password (twice, to confirm), and updates it immediately. The client can log in with the new password right away.

### Kamel Kafati's account

Along with the general sample database, there's a second one: `quoting_kamel.db` — a real client account with 245 materials already imported from an Excel materials list (código + descripción), nothing else mixed in.
- **Usuario:** `kamel`
- **Contraseña:** `master`

To use it instead of the demo data:
```bash
cd backend
cp quoting_kamel.db quoting.db
python3 app.py
```

Each imported material has its unit set to a default of "Unidad" and its price at 0 — add supplier quotes (Catálogos → Cotizaciones de Proveedores) to populate real prices, same as any other material.

### Fecha Agregado

Materiales now tracks two separate dates: **Fecha Agregado** (set once, when the material is first created — never changes afterward) and **Actualizado** (refreshed every time the material is edited, e.g. price changes). This lets you see how long something has been in the catalog even after you've updated its price a dozen times since.

### The sample/demo account

The seed script (`seed_data.py`) now also creates a demo account and scopes all the sample data to it:
- **Usuario:** `demo`
- **Contraseña:** `demo1234`

### ⚠️ Before deploying for real

Two things in `app.py` are set to safe-but-temporary defaults for local testing — change both before this goes live on the internet:

1. **`SECRET_KEY`** — currently defaults to a placeholder string if you haven't set one. This key is what makes login sessions unforgeable; anyone who has it can log in as anyone. Set a real one as an environment variable before deploying:
   ```bash
   export SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
   ```
   (however your host lets you set environment variables — Railway, Render, etc. all have a place for this in their dashboard).

2. **Cookies over HTTPS** — once you're running on a real domain with SSL (which you should be, for a login system), it's worth adding `app.config["SESSION_COOKIE_SECURE"] = True` in `app.py` so session cookies are never sent over plain HTTP.

## URL structure

The app now serves three things from one Flask process:
- **`/`** — a simple placeholder homepage (`landing/index.html`). Replace this file with your real homepage whenever it's ready — it's a completely independent file, not wired into the app in any other way.
- **`/cotizaciones/`** — the quoting app itself (what used to be at `/`).
- **`/regulación/`** (also reachable at `/regulacion/`, no accent) — the demand-planning / transformer-sizing tool. This page's own logic is self-contained, but it now saves/loads full studies (project info + node graph + cable data) through the same backend database as the rest of the app, so studies persist and can be reopened and modified later — see "Estudios guardados" at the top of the tool.

This means once deployed, `tudominio.com` shows your homepage, `tudominio.com/cotizaciones` shows the quoting tool, and `tudominio.com/regulacion` shows the demand planner — all from the same server, no extra setup needed.

## Connecting your GoDaddy domain

Buying the domain from GoDaddy doesn't mean the app has to be *hosted* on GoDaddy — the domain and the hosting are separate, and you point one at the other with a DNS record.

1. Deploy this app to whichever host you choose (Railway, Render, a VPS, GoDaddy VPS, etc.) and note the address it gives you (e.g. `your-app.up.railway.app`, or an IP address if it's a VPS).
2. In GoDaddy, go to **My Products → Domains → DNS** for your domain.
3. Add a record pointing your domain at that host:
   - If your host gives you a **hostname** (Railway, Render, most PaaS platforms): add a **CNAME** record — Host: `@` (or `www`), Value: the hostname they gave you. Some registrars don't allow a CNAME on the root (`@`); if GoDaddy blocks that, use their "domain forwarding" feature or point `www` instead and forward the root to `www`.
   - If your host gives you an **IP address** (a VPS): add an **A** record — Host: `@`, Value: that IP address.
4. Most platforms (Railway, Render) also want you to add the domain in *their* dashboard under "Custom Domains" so they can issue an SSL certificate for it — do that step too, using the exact instructions they show once you enter your domain.
5. DNS changes can take anywhere from a few minutes to a few hours to propagate.

## Test / sample data

There are two ways to try the app with realistic sample data instead of starting from a blank slate — a small electrical-distribution project with 7 materials (some with multiple supplier quotes so you can see the price comparison in action), labor, tools, transport, gastos, 3 complete Fichas de Costo, and 2 Cotizaciones (one taxable, one exempt).

**Option A — load the ready-made sample database (fastest):**
```bash
cd backend
cp quoting_sample.db quoting.db
python3 app.py
```

**Option B — regenerate sample data yourself** (useful any time you want to reset back to a clean sample state):
```bash
cd backend
python3 seed_data.py   # WIPES the current database and recreates the sample data
python3 app.py
```

Either way, once running, browse Catálogos → Materiales to see the auto-computed prices, or open one of the two seeded Cotizaciones to see a full multi-ficha project total with ISV applied.

## Running it locally

Requires Python 3.9+.

```bash
cd backend
pip install -r requirements.txt
python3 app.py
```

Then open **http://localhost:5000** in your browser. Your data is stored in `backend/quoting.db` (SQLite) — back this file up regularly, it's your whole database.

## Deploying to your own hosting later

This is a standard Flask app, so it runs anywhere Python does:

- **Render / Railway / Fly.io**: point them at this repo, set the start command to `cd backend && python3 app.py` (or better, use `gunicorn` — see below), and it'll deploy as-is.
- **PythonAnywhere**: upload the folder, point the WSGI file at `backend/app.py`'s `app` object.
- **Your own VPS**: use a real WSGI server instead of Flask's dev server:
  ```bash
  pip install gunicorn
  cd backend
  gunicorn -w 2 -b 0.0.0.0:8000 app:app
  ```
  then put Nginx in front of it.

### One important note on the database
SQLite (`quoting.db`) is a single file — great for one person or a small office on one server, but it doesn't handle many simultaneous writers well. If this grows into a multi-user tool accessed by several people at once, migrate to Postgres: change the `SQLALCHEMY_DATABASE_URI` in `app.py` to a Postgres connection string — the rest of the code (models, routes) doesn't need to change since SQLAlchemy handles the difference.

## Project structure

```
backend/
  app.py          — Flask routes + all cost/quote calculation logic
  models.py        — SQLAlchemy database models
  requirements.txt
  quoting.db        — created automatically on first run (your data)
frontend/
  index.html
  style.css
  app.js           — all UI logic, calls the backend API
```

## Extending it

Some natural next additions if you want them later:
- Export a quote to PDF or Word for sending to clients
- User accounts / login if multiple people will use it
- An "audit trail" of price changes over time in the catalogs
- Locking a cost card's prices at the moment it's added to a quote (currently quotes always use the cost card's *current* calculated total, so if you edit a card's prices later, past quotes using it will reflect the new total unless you keep a saved snapshot)
