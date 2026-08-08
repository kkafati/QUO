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

## Actualizar precios (en una Cotización)

Clicking **🔄 Actualizar precios** inside a saved Cotización now does more than just refresh what's on screen — it pushes the current catalog auto-price into every material item of every ficha actually used by that quote, and **saves it immediately**, no separate "Guardar Cotización" step needed. This means Resumen de Insumos, and the ficha itself if you open it separately, reflect the update right away.

This only touches material-category items (matching how material prices are auto-computed elsewhere in the app); it doesn't touch labor/tool/transport/gasto items, since those aren't tied to the same "auto-price from supplier quotes" mechanism.

## Resumen de Insumos (per cotización)

Open any saved Cotización and click **📊 Resumen de Insumos** to see a consolidated breakdown across all its fichas: every unique material, labor type, tool, transport, and gasto used anywhere in the project, with the total quantity and total cost needed for the whole job — not per ficha. If the same material shows up in five different fichas within the quote, it appears once here with the combined total, which is exactly what you'd want for actually going out and purchasing materials for the project. It's printable on its own, separate from printing the full quote.

Note: the totals shown are direct cost only (materials/labor/tools/transport/gastos at raw cost) — they don't include each ficha's admin %/utilidad % markup or the quote's ISV, since this view is meant for procurement, not the client-facing price.

## Papelera (trash / restore)

Deleting a Material, Labor, Herramienta, Transporte, Gasto, Ficha de Costo, or Cotización no longer erases it immediately — it moves to a **Papelera** (trash), where you can restore it or permanently delete it later.

- Every "×" delete button now shows a confirmation that names the specific item and explains it's recoverable, instead of a generic "cannot be undone" warning.
- A **🗑 Papelera** button sits next to "+ Nuevo"/"+ Nueva Ficha"/"+ Nueva Cotización" in each area, showing everything currently in the trash with **Restaurar** and **Eliminar permanentemente** options.
- Restoring an item is blocked if its código is now in use by something else active (you'd need to rename one of them first) — this prevents silently creating a duplicate.
- Deleting a Ficha does **not** affect any Cotización that already uses it — the ficha just stops being available to add to *new* cotizaciones until restored.
- This is a manual trash, not a timed one — items stay in the Papelera until you explicitly restore or permanently delete them.

**Scope note:** this covers the items people most often worry about losing by accident. Individual supplier price quotes (Cotización de Proveedores entries) are still deleted immediately when removed — those are quick to re-enter and lower-stakes than losing a whole ficha or cotización, so they weren't included in this system. Ask if you'd like that extended to cover them too.

**Now connected to Facturación**: the Cliente and RTN fields on every invoice (all 7 templates) are searchable — type a few letters into either one and matching clients show up in a dropdown; picking one fills both fields and links the invoice to that client. Type a name that doesn't match anyone, save the invoice, and a new Cliente record gets created automatically from just the name/RTN you entered — no separate step required. Retype an *existing* client's exact name without clicking the suggestion and it still links correctly rather than creating a duplicate (matched by exact name, case-insensitive).

Any client missing RTN, Dirección, Contacto, Teléfono, or Correo shows a **"Datos Incompletos"** badge in the Clientes list — this is exactly what you'll see on clients auto-created from Facturación, since those only start with a name and RTN.

## Clientes

Live at `/clientes/`, linked from the dashboard. Full CRUD (create/edit/delete-to-trash/restore, same soft-delete pattern as everywhere else) for customer records — Nombre, RTN, Dirección, Contacto, Teléfono, Correo — with a search bar and a click-to-select list.

Selecting a client shows their full invoice history, each with a payment-status badge (**Falta Pago / En Proceso / Pagado**) that can be changed right from that list, no need to open the invoice itself. That same status selector is also on the Facturación list page and on every invoice's own edit toolbar — change it from wherever's convenient, it's the same underlying field everywhere.

**Scope note on linking**: new invoices can be tied to a client via `cliente_id`, but I didn't rebuild the invoice-creation flow to require picking one from a dropdown — `cliente_nombre`/`cliente_rtn` stay as free-text fields on the invoice (so a printed invoice's client info never silently changes if you later edit the Cliente record). A client's invoice list picks up both explicitly-linked invoices and older/unlinked ones matched by name, so nothing existing gets orphaned.

## Plantilla de Factura (account-level, not per-invoice)

Which of the 7 invoice templates gets used is now set once in `/cuenta/` (Facturación section → "Plantilla de Factura"), not chosen per-invoice. "+ Nueva Factura" always uses whatever's configured there; the picker modal and the per-invoice "Plantilla" switcher have both been removed. Changing this setting only affects *new* invoices going forward — existing invoices keep whichever template they were created with, so a previously-printed/saved invoice never silently changes format after the fact.

## Facturación (billing/invoicing)

**5 templates now available**: Clásica (your real format), Moderna (light, minimalist, colored accent bar), Elegante (formal/corporate, centered, muted palette), Compacta (dense, print-economical), and Color Block (bold branded header band). Pick one when creating a new invoice via "+ Nueva Factura," or switch an existing invoice's template anytime from the "Plantilla" dropdown in its toolbar — your data carries over, only the visual layout changes.

All 5 share one JS file (`facturacion/factura-common.js`) for data loading, line-item editing, totals math, and saving — so a fix or improvement to that logic applies to every template at once, rather than needing to be repeated 5 times.

**Now 7 templates total** — the 5 above, plus **Térmica 58mm** and **Térmica 80mm** for Epson-style thermal receipt printers. These use `@page { size: 58mm/80mm auto }` so the print dialog outputs a continuous receipt-width strip instead of a full page, monospace typography for that classic receipt look, and a stacked (not tabular) line-item layout — description on its own line, then quantity/price/total below it — since a 4-column table simply doesn't fit on a 58mm roll. All the same legally-required fields (CAI, RTN, Rango Autorizado, Fecha Límite, Total en Letras, exemption references) are still there, just condensed to fit.



**Live now** at `/facturacion/`, replacing the old "Próximamente" placeholder. This is Template 1 of the planned set — built to match your exact real invoice format (logo/contact header, C.A.I., línea items, Total en Letras, exemption references, Rango Autorizado footer, all of it).

**Before creating your first invoice**, fill in the Facturación section of `/cuenta/` — Prefijo de Factura, C.A.I., Fecha Límite de Emisión, and Rango Autorizado. The system won't let you create an invoice until Prefijo de Factura is set (it needs that to generate the invoice number), and every invoice pulls your CAI/RTN/contact info live from that same page — set it once there, not per-invoice.

**Invoice numbering is now real, not just a display field**: each new invoice takes the current "Próximo Número," assembles it into the full `000-001-01-00000001` format using your Prefijo, and automatically advances the counter for the next one. No manual bookkeeping needed.

**"Total en Letras"** (the amount spelled out in words, e.g. "TRES MIL TRESCIENTOS NOVENTA Y SEIS LEMPIRAS CON 24/100") is generated automatically by `backend/numero_a_letras.py` — a from-scratch Spanish number-to-words converter, tested against 13 cases including the tricky ones (teens, "veintiuno" contraction, "cien" vs "ciento", singular "un millón" vs plural "millones").

**Tax handling in this first version**: every invoice is either fully 15%-gravado or fully 18%-gravado (a toggle on the invoice) — not per-line-item tax classification. Importe Exonerado/Exento are entered as manual override amounts subtracted from the taxable base. This covers the common case cleanly; true per-line tax categorization would be a meaningful follow-up if you need it.

**Soft-delete/trash** works the same as everywhere else in the app — deleting an invoice moves it to Papelera, recoverable, never an instant permanent loss.

**What's next**: templates 2-5 (different visual styles, same underlying data/math) are a much smaller lift now that this foundation is solid — say the word when you want them.

## Analytics: online status, login history, page views

**For you (platform admin)** — a completely separate login at `/admin/login`, not tied to any business account. Set it up once:
```bash
cd backend
python3 create_admin.py
```
Then log in at `/admin/login` (not `/login` — that's for business accounts). The dashboard shows:
- Every business account, whether they're online right now (active within the last 5 minutes), their last login, and when their account was created
- **Page views, all-time**, broken down by month and by day, plus by page — with a filter to view platform-wide, one specific account, or just anonymous views (visits to `/` and `/login` before anyone's authenticated)
- A live feed of every login/logout across every account, click any account in the table to filter the feed to just them

**For each business** — their own "Actividad" section, now at the bottom of `/cuenta/` (Account Settings): their own login/logout history for the last 3 months.

Page views are only logged for actual page loads (landing, login, panel, cotizaciones, regulación, cuenta) — not every API call, so the numbers reflect real visits, not internal chatter.

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

## Dashboard and platform structure

`/panel/` is now a real module dashboard, not just two links. It shows all the planned modules — **Facturación**, **Contabilidad**, and **Inventario** are visible but marked "Próximamente" (coming soon, disabled) until built. **Cotizaciones** and **Planificador de Demanda** work exactly as before, just reframed as reference/calculator add-ins rather than the main app. **Configuración de la Cuenta** is live now (see below).

Every future module (Invoicing, Accounting, Inventory) will follow the same pattern already proven out for Cotizaciones: its own tables scoped by `account_id` in the same shared database — no separate database per business, ever. This is a deliberate architectural decision: real multi-tenant isolation (already tested — one account genuinely cannot see or write another's data) doesn't require separate files, and a shared database is dramatically simpler to back up, migrate, and maintain as more businesses sign up.

## Configuración de la Cuenta (`/cuenta/`)

A business-profile page: nombre comercial, razón social, RTN, dirección, teléfono, correo, sitio web, moneda, logo (uploaded and stored directly on the account, shown wherever the account's identity appears), and invoice numbering (prefix + next number) — ready for when Facturación is built. This is the single source of truth other modules will pull from instead of asking for the same business info repeatedly.

## URL structure

The app now serves four things from one Flask process:
- **`/`** — the public Grupo Liquidámbar landing page (`landing/index.html`) — an "under construction" page with the logo and an "Iniciar sesión" button. Public, no login needed.
- **`/login`** — the login form, styled to match the brand (`auth/login.html`).
- **`/panel/`** — the post-login options screen (`panel/index.html`): "Sistema de Cotizaciones" and "Planificador de Demanda" as two cards. This is where a fresh login lands by default; direct links to a specific tool (e.g. someone bookmarked `/cotizaciones/`) still go straight there instead, login only redirects to `/panel/` when there's no more specific destination.
- **`/cotizaciones/`** — the quoting app.
- **`/regulación/`** (also `/regulacion/`) — the demand planner.

The logo is embedded directly in each of these pages' HTML (as a data URI), so there's no separate image file to keep track of or a route to break.

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
