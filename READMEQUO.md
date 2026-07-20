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
