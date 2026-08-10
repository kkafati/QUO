import os
import re
import json
import mimetypes
from functools import wraps
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_from_directory, session, redirect, url_for, abort
from werkzeug.security import check_password_hash, generate_password_hash
from models import db, Account, Material, Labor, Tool, Transport, Gasto, CostCard, CostCardItem, Quote, QuoteLine, QuoteFee, SupplierPrice, RegulacionStudy, Admin, LoginEvent, PageView, Invoice, InvoiceLine, Cliente, Cotizacion, CotizacionLine
from numero_a_letras import numero_a_letras
from pdf_render import render_invoice_pdf
from pdf_render_cotizacion import render_cotizacion_pdf

# On some Windows machines, a corrupted registry entry makes Python think
# .html/.js/.css are text/plain, causing browsers to show raw source instead
# of rendering the page. Force the correct types explicitly so it never
# depends on that registry state.
mimetypes.add_type("text/html", ".html")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/javascript", ".js")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(os.path.dirname(BASE_DIR), "frontend")
LANDING_DIR = os.path.join(os.path.dirname(BASE_DIR), "landing")
REGULACION_DIR = os.path.join(os.path.dirname(BASE_DIR), "regulacion")
AUTH_DIR = os.path.join(os.path.dirname(BASE_DIR), "auth")
PANEL_DIR = os.path.join(os.path.dirname(BASE_DIR), "panel")
CUENTA_DIR = os.path.join(os.path.dirname(BASE_DIR), "cuenta")
ADMIN_DIR = os.path.join(os.path.dirname(BASE_DIR), "admin")
FACTURACION_DIR = os.path.join(os.path.dirname(BASE_DIR), "facturacion")
COTIZACION_CLASICA_DIR = os.path.join(os.path.dirname(BASE_DIR), "cotizacion-clasica")
CLIENTES_DIR = os.path.join(os.path.dirname(BASE_DIR), "clientes")

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="/cotizaciones")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "quoting.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
# IMPORTANT: change this to a long random value before deploying for real.
# Anyone who has this value can forge login sessions.
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-me-before-deploying")
# Only send the session cookie over HTTPS. Set FORCE_HTTPS=1 once you're
# actually serving over HTTPS (e.g. behind Cloudflare Tunnel) — leave unset
# for local http://localhost testing, or login won't work.
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("FORCE_HTTPS", "0") == "1"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
db.init_app(app)

with app.app_context():
    db.create_all()
    # db.create_all() only creates missing TABLES, not new COLUMNS on tables
    # that already exist - which is exactly the case for accounts.next_cotizacion_number
    # on any database that predates this feature. Self-heal it here so a normal
    # "pull the new code, restart" deploy just works, no manual SQL required.
    try:
        cols = [row[1] for row in db.session.execute(db.text("PRAGMA table_info(accounts)")).fetchall()]
        if "next_cotizacion_number" not in cols:
            db.session.execute(db.text("ALTER TABLE accounts ADD COLUMN next_cotizacion_number INTEGER DEFAULT 1"))
            db.session.commit()
    except Exception:
        db.session.rollback()  # non-SQLite DBs or unexpected schema - don't block startup over this

CATEGORY_MODELS = {"material": Material, "labor": Labor, "tool": Tool, "transport": Transport, "gasto": Gasto}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def current_account_id():
    return session.get("account_id")


def current_admin_id():
    return session.get("admin_id")


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_admin_id():
            if request.path.startswith("/api/"):
                return jsonify({"error": "not_authenticated"}), 401
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def log_page_view(path):
    """Best-effort page view log; never let a logging failure break the page."""
    try:
        db.session.add(PageView(
            account_id=current_account_id(),
            path=path,
            timestamp=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            ip_address=request.headers.get("CF-Connecting-IP", request.remote_addr),
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()


@app.before_request
def touch_last_seen():
    """Keep Account.last_seen fresh for the admin's 'online now' indicator.
    Throttled to avoid a write on every single request."""
    account_id = session.get("account_id")
    if not account_id:
        return
    account = Account.query.get(account_id)
    if not account:
        return
    now = datetime.utcnow()
    if account.last_seen:
        try:
            last = datetime.strptime(account.last_seen, "%Y-%m-%d %H:%M:%S")
            if (now - last).total_seconds() < 30:
                return  # updated recently enough, skip the write
        except ValueError:
            pass
    account.last_seen = now.strftime("%Y-%m-%d %H:%M:%S")
    db.session.commit()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_account_id():
            if request.path.startswith("/api/"):
                return jsonify({"error": "not_authenticated"}), 401
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@app.route("/login", methods=["GET"])
def login():
    log_page_view("/login")
    return send_from_directory(AUTH_DIR, "login.html")


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.json or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    account = Account.query.filter_by(username=username).first()
    if not account or not check_password_hash(account.password_hash, password):
        return jsonify({"error": "Usuario o contraseña incorrectos."}), 401
    session["account_id"] = account.id
    session["company_name"] = account.company_name
    session.permanent = True
    account.last_seen = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    db.session.add(LoginEvent(
        account_id=account.id, event_type="login",
        timestamp=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        ip_address=request.headers.get("CF-Connecting-IP", request.remote_addr),
        user_agent=(request.headers.get("User-Agent") or "")[:255],
    ))
    db.session.commit()
    return jsonify({"ok": True, "company_name": account.company_name})


@app.route("/api/me", methods=["GET"])
def api_me():
    if not current_account_id():
        return jsonify({"authenticated": False})
    return jsonify({"authenticated": True, "company_name": session.get("company_name")})


def account_profile_dict(account):
    return {
        "company_name": account.company_name,
        "legal_name": account.legal_name,
        "tax_id": account.tax_id,
        "address": account.address,
        "phone": account.phone,
        "email": account.email,
        "website": account.website,
        "currency": account.currency,
        "logo_data_url": account.logo_data_url,
        "invoice_prefix": account.invoice_prefix,
        "next_invoice_number": account.next_invoice_number,
        "next_cotizacion_number": account.next_cotizacion_number,
        "cai": account.cai,
        "cai_fecha_limite": account.cai_fecha_limite,
        "rango_autorizado_desde": account.rango_autorizado_desde,
        "rango_autorizado_hasta": account.rango_autorizado_hasta,
        "default_invoice_template": account.default_invoice_template or "clasica",
    }


@app.route("/api/account", methods=["GET"])
@login_required
def get_account_profile():
    account = Account.query.get_or_404(current_account_id())
    return jsonify(account_profile_dict(account))


@app.route("/api/account", methods=["PUT"])
@login_required
def update_account_profile():
    account = Account.query.get_or_404(current_account_id())
    data = request.json or {}

    company_name = data.get("company_name", account.company_name).strip()
    if not company_name:
        return jsonify({"error": "El nombre comercial es requerido."}), 400
    account.company_name = company_name
    account.legal_name = (data.get("legal_name", account.legal_name) or "").strip()
    account.tax_id = (data.get("tax_id", account.tax_id) or "").strip()
    account.address = (data.get("address", account.address) or "").strip()
    account.phone = (data.get("phone", account.phone) or "").strip()
    account.email = (data.get("email", account.email) or "").strip()
    account.website = (data.get("website", account.website) or "").strip()
    account.currency = (data.get("currency", account.currency) or "HNL").strip()
    account.invoice_prefix = (data.get("invoice_prefix", account.invoice_prefix) or "").strip()
    try:
        account.next_invoice_number = int(data.get("next_invoice_number", account.next_invoice_number) or 1)
    except (TypeError, ValueError):
        pass
    try:
        account.next_cotizacion_number = int(data.get("next_cotizacion_number", account.next_cotizacion_number) or 1)
    except (TypeError, ValueError):
        pass
    account.cai = (data.get("cai", account.cai) or "").strip().upper()
    account.cai_fecha_limite = (data.get("cai_fecha_limite", account.cai_fecha_limite) or "").strip()
    account.rango_autorizado_desde = (data.get("rango_autorizado_desde", account.rango_autorizado_desde) or "").strip()
    account.rango_autorizado_hasta = (data.get("rango_autorizado_hasta", account.rango_autorizado_hasta) or "").strip()
    incoming_template = (data.get("default_invoice_template", account.default_invoice_template) or "clasica").strip()
    account.default_invoice_template = incoming_template if incoming_template in TEMPLATE_FILES else "clasica"
    if "logo_data_url" in data:
        account.logo_data_url = data.get("logo_data_url") or None

    db.session.commit()
    session["company_name"] = account.company_name  # keep topbar/session in sync
    return jsonify(account_profile_dict(account))


@app.route("/logout", methods=["GET", "POST"])
def logout():
    account_id = current_account_id()
    if account_id:
        db.session.add(LoginEvent(
            account_id=account_id, event_type="logout",
            timestamp=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            ip_address=request.headers.get("CF-Connecting-IP", request.remote_addr),
            user_agent=(request.headers.get("User-Agent") or "")[:255],
        ))
        db.session.commit()
    session.clear()
    return redirect(url_for("login"))


@app.route("/api/account/activity", methods=["GET"])
@login_required
def get_own_activity():
    """A business account's own login/logout history - not other accounts'.
    Last 3 months, not just a flat recent-N-events limit."""
    since = (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d %H:%M:%S")
    events = (LoginEvent.query.filter(LoginEvent.account_id == current_account_id(),
                                       LoginEvent.timestamp >= since)
              .order_by(LoginEvent.timestamp.desc()).all())
    return jsonify([{
        "event_type": e.event_type, "timestamp": e.timestamp, "ip_address": e.ip_address,
    } for e in events])


# ---------------------------------------------------------------------------
# Admin - platform-wide view across every business account. Separate login,
# separate session key (admin_id), not tied to any Account.
# ---------------------------------------------------------------------------

ONLINE_THRESHOLD_SECONDS = 5 * 60  # "online now" = active within the last 5 minutes


@app.route("/admin/login", methods=["GET"])
def admin_login():
    return send_from_directory(ADMIN_DIR, "login.html")


@app.route("/api/admin/login", methods=["POST"])
def api_admin_login():
    data = request.json or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    admin = Admin.query.filter_by(username=username).first()
    if not admin or not check_password_hash(admin.password_hash, password):
        return jsonify({"error": "Usuario o contraseña incorrectos."}), 401
    session["admin_id"] = admin.id
    session.permanent = True
    return jsonify({"ok": True})


@app.route("/admin/logout", methods=["GET", "POST"])
def admin_logout():
    session.pop("admin_id", None)
    return redirect(url_for("admin_login"))


@app.route("/admin/")
@admin_required
def admin_dashboard():
    return send_from_directory(ADMIN_DIR, "index.html")


def _is_online(account):
    if not account.last_seen:
        return False
    try:
        last = datetime.strptime(account.last_seen, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return False
    return (datetime.utcnow() - last).total_seconds() < ONLINE_THRESHOLD_SECONDS


@app.route("/api/admin/accounts", methods=["GET"])
@admin_required
def admin_list_accounts():
    accounts = Account.query.order_by(Account.id).all()
    result = []
    for a in accounts:
        last_login = (LoginEvent.query.filter_by(account_id=a.id, event_type="login")
                      .order_by(LoginEvent.timestamp.desc()).first())
        result.append({
            "id": a.id,
            "username": a.username,
            "company_name": a.company_name,
            "created_at": a.created_at,
            "last_seen": a.last_seen,
            "online": _is_online(a),
            "last_login": last_login.timestamp if last_login else None,
        })
    return jsonify(result)


@app.route("/api/admin/events", methods=["GET"])
@admin_required
def admin_list_events():
    account_id = request.args.get("account_id", type=int)
    q = LoginEvent.query
    if account_id:
        q = q.filter_by(account_id=account_id)
    events = q.order_by(LoginEvent.timestamp.desc()).limit(200).all()
    return jsonify([{
        "id": e.id, "account_id": e.account_id,
        "company_name": e.account.company_name if e.account else None,
        "event_type": e.event_type, "timestamp": e.timestamp,
        "ip_address": e.ip_address, "user_agent": e.user_agent,
    } for e in events])


@app.route("/api/admin/pageviews", methods=["GET"])
@admin_required
def admin_pageview_stats():
    """All-time by default (not just a recent window), grouped by month and by day.
    ?account_id=<id>   -> scope everything to that one business account
    ?account_id=none   -> scope to anonymous views only (not logged in - e.g. the public landing page)
    (omit account_id)  -> platform-wide, every view"""
    account_filter = request.args.get("account_id")

    q = PageView.query
    if account_filter == "none":
        q = q.filter(PageView.account_id.is_(None))
    elif account_filter:
        try:
            q = q.filter(PageView.account_id == int(account_filter))
        except ValueError:
            pass

    total = q.count()

    by_path = (q.with_entities(PageView.path, db.func.count(PageView.id))
               .group_by(PageView.path).order_by(db.func.count(PageView.id).desc()).all())

    by_month = (q.with_entities(db.func.substr(PageView.timestamp, 1, 7), db.func.count(PageView.id))
                .group_by(db.func.substr(PageView.timestamp, 1, 7))
                .order_by(db.func.substr(PageView.timestamp, 1, 7)).all())

    by_day = (q.with_entities(db.func.substr(PageView.timestamp, 1, 10), db.func.count(PageView.id))
              .group_by(db.func.substr(PageView.timestamp, 1, 10))
              .order_by(db.func.substr(PageView.timestamp, 1, 10)).all())

    return jsonify({
        "total": total,
        "by_path": [{"path": p, "count": c} for p, c in by_path],
        "by_month": [{"month": m, "count": c} for m, c in by_month],
        "by_day": [{"day": d, "count": c} for d, c in by_day],
    })


# ---------------------------------------------------------------------------
# Static frontend
# ---------------------------------------------------------------------------

@app.route("/")
def landing():
    log_page_view("/")
    return send_from_directory(LANDING_DIR, "index.html")


@app.route("/panel/")
@login_required
def panel():
    log_page_view("/panel/")
    return send_from_directory(PANEL_DIR, "index.html")


@app.route("/cuenta/")
@login_required
def cuenta():
    log_page_view("/cuenta/")
    return send_from_directory(CUENTA_DIR, "index.html")


@app.route("/cotizaciones/")
@login_required
def index():
    log_page_view("/cotizaciones/")
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/regulación/")
@app.route("/regulacion/")
@login_required
def regulacion():
    log_page_view("/regulacion/")
    return send_from_directory(REGULACION_DIR, "index.html")


# ---------------------------------------------------------------------------
# Catalog endpoints (materials / labor / tools / transport / gasto) - shared shape
# ---------------------------------------------------------------------------

def catalog_to_dict(item):
    return {
        "id": item.id,
        "code": item.code,
        "description": item.description,
        "unit": item.unit,
        "unit_price": item.unit_price,
        "updated_at": item.updated_at,
    }


def compute_material_auto_price(suppliers):
    """Highest price among the supplier quotes sharing the most recent date."""
    if not suppliers:
        return None
    max_date = max((s.date or "") for s in suppliers)
    candidates = [s for s in suppliers if (s.date or "") == max_date]
    return max(c.price for c in candidates)


def material_to_dict(item):
    base = catalog_to_dict(item)
    base["created_at"] = item.created_at
    suppliers = item.suppliers
    auto_price = compute_material_auto_price(suppliers)
    if auto_price is not None:
        base["unit_price"] = auto_price
    if suppliers:
        cheapest = min(suppliers, key=lambda s: s.price)
        priciest = max(suppliers, key=lambda s: s.price)
        latest = max(suppliers, key=lambda s: s.date or "")
        base.update({
            "price_min": cheapest.price,
            "price_min_proveedor": cheapest.proveedor,
            "price_max": priciest.price,
            "price_max_proveedor": priciest.proveedor,
            "latest_date": latest.date,
            "supplier_count": len(suppliers),
        })
    else:
        base.update({
            "price_min": None, "price_min_proveedor": None,
            "price_max": None, "price_max_proveedor": None,
            "latest_date": None, "supplier_count": 0,
        })
    return base


def register_catalog_routes(category, Model, to_dict=catalog_to_dict):
    endpoint = f"catalog_{category}"

    @app.route(f"/api/catalog/{category}", methods=["GET"], endpoint=f"{endpoint}_list")
    @login_required
    def list_items():
        q = request.args.get("q", "").strip().lower()
        items = Model.query.filter_by(account_id=current_account_id(), deleted_at=None).order_by(Model.code).all()
        if q:
            items = [i for i in items if q in i.code.lower() or q in i.description.lower()]
        return jsonify([to_dict(i) for i in items])

    @app.route(f"/api/catalog/{category}/trash", methods=["GET"], endpoint=f"{endpoint}_trash_list")
    @login_required
    def list_trash():
        items = (Model.query.filter(Model.account_id == current_account_id(), Model.deleted_at.isnot(None))
                 .order_by(Model.deleted_at.desc()).all())
        return jsonify([to_dict(i) for i in items])

    @app.route(f"/api/catalog/{category}", methods=["POST"], endpoint=f"{endpoint}_create")
    @login_required
    def create_item():
        data = request.json or {}
        code = data.get("code", "").strip()
        if Model.query.filter_by(account_id=current_account_id(), code=code, deleted_at=None).first():
            return jsonify({"error": f"El código '{code}' ya está en uso."}), 400
        kwargs = dict(
            account_id=current_account_id(),
            code=code,
            description=data.get("description", "").strip(),
            unit=data.get("unit", "").strip(),
            unit_price=float(data.get("unit_price", 0) or 0),
            updated_at=datetime.utcnow().strftime("%Y-%m-%d"),
        )
        if category == "material":
            kwargs["created_at"] = datetime.utcnow().strftime("%Y-%m-%d")
        item = Model(**kwargs)
        db.session.add(item)
        db.session.commit()
        return jsonify(to_dict(item)), 201

    @app.route(f"/api/catalog/{category}/<int:item_id>", methods=["PUT"], endpoint=f"{endpoint}_update")
    @login_required
    def update_item(item_id):
        item = Model.query.filter_by(id=item_id, account_id=current_account_id()).first_or_404()
        data = request.json or {}
        new_code = data.get("code", item.code).strip()
        if new_code != item.code and Model.query.filter_by(account_id=current_account_id(), code=new_code, deleted_at=None).first():
            return jsonify({"error": f"El código '{new_code}' ya está en uso."}), 400
        item.code = new_code
        item.description = data.get("description", item.description).strip()
        item.unit = data.get("unit", item.unit).strip()
        item.unit_price = float(data.get("unit_price", item.unit_price) or 0)
        item.updated_at = datetime.utcnow().strftime("%Y-%m-%d")
        db.session.commit()
        return jsonify(to_dict(item))

    @app.route(f"/api/catalog/{category}/<int:item_id>", methods=["DELETE"], endpoint=f"{endpoint}_delete")
    @login_required
    def delete_item(item_id):
        item = Model.query.filter_by(id=item_id, account_id=current_account_id(), deleted_at=None).first_or_404()
        item.deleted_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
        db.session.commit()
        return "", 204

    @app.route(f"/api/catalog/{category}/<int:item_id>/restore", methods=["POST"], endpoint=f"{endpoint}_restore")
    @login_required
    def restore_item(item_id):
        item = Model.query.filter(Model.id == item_id, Model.account_id == current_account_id(),
                                   Model.deleted_at.isnot(None)).first_or_404()
        if Model.query.filter_by(account_id=current_account_id(), code=item.code, deleted_at=None).first():
            return jsonify({"error": f"No se puede restaurar: el código '{item.code}' ya está en uso por otro artículo activo."}), 400
        item.deleted_at = None
        db.session.commit()
        return jsonify(to_dict(item))

    @app.route(f"/api/catalog/{category}/<int:item_id>/permanent", methods=["DELETE"], endpoint=f"{endpoint}_permanent")
    @login_required
    def permanent_delete_item(item_id):
        item = Model.query.filter(Model.id == item_id, Model.account_id == current_account_id(),
                                   Model.deleted_at.isnot(None)).first_or_404()
        db.session.delete(item)
        db.session.commit()
        return "", 204


for cat, Model in CATEGORY_MODELS.items():
    register_catalog_routes(cat, Model, to_dict=material_to_dict if cat == "material" else catalog_to_dict)


# ---------------------------------------------------------------------------
# Supplier prices (Proveedores) - per-material list of independent supplier quotes
# ---------------------------------------------------------------------------

def supplier_to_dict(s):
    return {
        "id": s.id,
        "material_id": s.material_id,
        "proveedor": s.proveedor,
        "code": s.code,
        "description": s.description,
        "unit": s.unit,
        "price": s.price,
        "date": s.date,
    }


@app.route("/api/suppliers", methods=["GET"])
@login_required
def list_all_suppliers():
    q = request.args.get("q", "").strip().lower()
    rows = (SupplierPrice.query.join(Material)
            .filter(Material.account_id == current_account_id())
            .order_by(SupplierPrice.date.desc()).all())
    result = []
    for s in rows:
        d = supplier_to_dict(s)
        d["material_code"] = s.material.code if s.material else None
        d["material_description"] = s.material.description if s.material else None
        result.append(d)
    if q:
        result = [r for r in result if q in (r["proveedor"] or "").lower()
                  or q in (r["code"] or "").lower()
                  or q in (r["material_code"] or "").lower()
                  or q in (r["material_description"] or "").lower()]
    return jsonify(result)


@app.route("/api/materials/<int:material_id>/suppliers", methods=["GET"])
@login_required
def list_suppliers(material_id):
    Material.query.filter_by(id=material_id, account_id=current_account_id()).first_or_404()
    rows = SupplierPrice.query.filter_by(material_id=material_id).order_by(SupplierPrice.date.desc()).all()
    return jsonify([supplier_to_dict(s) for s in rows])


@app.route("/api/materials/<int:material_id>/suppliers", methods=["POST"])
@login_required
def create_supplier(material_id):
    Material.query.filter_by(id=material_id, account_id=current_account_id()).first_or_404()
    data = request.json or {}
    s = SupplierPrice(
        material_id=material_id,
        proveedor=data.get("proveedor", "").strip(),
        code=data.get("code", "").strip(),
        description=data.get("description", "").strip(),
        unit=data.get("unit", "").strip(),
        price=float(data.get("price", 0) or 0),
        date=data.get("date") or datetime.utcnow().strftime("%Y-%m-%d"),
    )
    db.session.add(s)
    db.session.commit()
    return jsonify(supplier_to_dict(s)), 201


def _owned_supplier_or_404(supplier_id):
    s = SupplierPrice.query.filter_by(id=supplier_id).first_or_404()
    if not s.material or s.material.account_id != current_account_id():
        abort(404)
    return s


@app.route("/api/suppliers/<int:supplier_id>", methods=["PUT"])
@login_required
def update_supplier(supplier_id):
    s = _owned_supplier_or_404(supplier_id)
    data = request.json or {}
    s.proveedor = data.get("proveedor", s.proveedor).strip()
    s.code = data.get("code", s.code)
    s.description = data.get("description", s.description)
    s.unit = data.get("unit", s.unit)
    s.price = float(data.get("price", s.price) or 0)
    s.date = data.get("date", s.date)
    db.session.commit()
    return jsonify(supplier_to_dict(s))


@app.route("/api/suppliers/<int:supplier_id>", methods=["DELETE"])
@login_required
def delete_supplier(supplier_id):
    s = _owned_supplier_or_404(supplier_id)
    db.session.delete(s)
    db.session.commit()
    return "", 204


# ---------------------------------------------------------------------------
# Cost cards (Fichas de Costo)
# ---------------------------------------------------------------------------

def compute_card_totals(card):
    """Compute all derived totals for a cost card. Returns a dict."""
    groups = {"material": [], "labor": [], "tool": [], "transport": [], "gasto": []}
    for it in card.items:
        rendimiento = it.rendimiento or 0
        desperdicio = (it.desperdicio_pct or 0) / 100.0
        unit_price = it.unit_price or 0
        subtotal = rendimiento * unit_price
        total = subtotal * (1 + desperdicio)
        groups[it.category].append({
            "id": it.id,
            "code": it.code,
            "description": it.description,
            "unit": it.unit,
            "rendimiento": rendimiento,
            "desperdicio_pct": it.desperdicio_pct or 0,
            "unit_price": unit_price,
            "subtotal": round(subtotal, 4),
            "total": round(total, 4),
        })

    total_materials = sum(x["total"] for x in groups["material"])
    total_labor = sum(x["total"] for x in groups["labor"])
    total_tools = sum(x["total"] for x in groups["tool"])
    total_transport = sum(x["total"] for x in groups["transport"])
    total_gastos = sum(x["total"] for x in groups["gasto"])
    direct_cost = total_materials + total_labor + total_tools + total_transport + total_gastos
    admin_amount = direct_cost * (card.admin_pct / 100.0)
    utilidad_amount = direct_cost * (card.utilidad_pct / 100.0)
    total_cost = direct_cost + admin_amount + utilidad_amount

    return {
        "id": card.id,
        "code": card.code,
        "name": card.name,
        "description": card.description,
        "created_at": card.created_at,
        "updated_at": card.updated_at,
        "unit": card.unit,
        "admin_pct": card.admin_pct,
        "utilidad_pct": card.utilidad_pct,
        "materials": groups["material"],
        "labor": groups["labor"],
        "tools": groups["tool"],
        "transport": groups["transport"],
        "gastos": groups["gasto"],
        "total_materials": round(total_materials, 4),
        "total_labor": round(total_labor, 4),
        "total_tools": round(total_tools, 4),
        "total_transport": round(total_transport, 4),
        "total_gastos": round(total_gastos, 4),
        "direct_cost": round(direct_cost, 4),
        "admin_amount": round(admin_amount, 4),
        "utilidad_amount": round(utilidad_amount, 4),
        "total_cost": round(total_cost, 4),
    }


@app.route("/api/costcards", methods=["GET"])
@login_required
def list_costcards():
    q = request.args.get("q", "").strip().lower()
    cards = CostCard.query.filter_by(account_id=current_account_id(), deleted_at=None).order_by(CostCard.code).all()
    if q:
        cards = [c for c in cards if q in c.code.lower() or q in c.name.lower() or q in (c.description or "").lower()]
    return jsonify([compute_card_totals(c) for c in cards])


@app.route("/api/costcards/trash", methods=["GET"])
@login_required
def list_costcards_trash():
    cards = (CostCard.query.filter(CostCard.account_id == current_account_id(), CostCard.deleted_at.isnot(None))
             .order_by(CostCard.deleted_at.desc()).all())
    return jsonify([compute_card_totals(c) for c in cards])


@app.route("/api/costcards/<int:card_id>", methods=["GET"])
@login_required
def get_costcard(card_id):
    card = CostCard.query.filter_by(id=card_id, account_id=current_account_id()).first_or_404()
    return jsonify(compute_card_totals(card))


@app.route("/api/costcards", methods=["POST"])
@login_required
def create_costcard():
    data = request.json or {}
    code = data.get("code", "").strip()
    if CostCard.query.filter_by(account_id=current_account_id(), code=code, deleted_at=None).first():
        return jsonify({"error": f"El código de ficha '{code}' ya está en uso."}), 400
    card = CostCard(
        account_id=current_account_id(),
        code=code,
        name=data.get("name", "").strip(),
        description=data.get("description", "").strip(),
        unit=data.get("unit", "").strip(),
        admin_pct=float(data.get("admin_pct", 10) or 0),
        utilidad_pct=float(data.get("utilidad_pct", 15) or 0),
        created_at=datetime.utcnow().strftime("%Y-%m-%d"),
        updated_at=datetime.utcnow().strftime("%Y-%m-%d"),
    )
    db.session.add(card)
    db.session.commit()
    _sync_items(card, data.get("items", []))
    return jsonify(compute_card_totals(card)), 201


@app.route("/api/costcards/<int:card_id>", methods=["PUT"])
@login_required
def update_costcard(card_id):
    card = CostCard.query.filter_by(id=card_id, account_id=current_account_id()).first_or_404()
    data = request.json or {}
    new_code = data.get("code", card.code).strip()
    if new_code != card.code and CostCard.query.filter_by(account_id=current_account_id(), code=new_code, deleted_at=None).first():
        return jsonify({"error": f"El código de ficha '{new_code}' ya está en uso."}), 400
    card.code = new_code
    card.name = data.get("name", card.name).strip()
    card.description = data.get("description", card.description or "").strip()
    card.unit = data.get("unit", card.unit).strip()
    card.admin_pct = float(data.get("admin_pct", card.admin_pct) or 0)
    card.utilidad_pct = float(data.get("utilidad_pct", card.utilidad_pct) or 0)
    if not card.created_at:
        card.created_at = datetime.utcnow().strftime("%Y-%m-%d")
    card.updated_at = datetime.utcnow().strftime("%Y-%m-%d")
    if "items" in data:
        _sync_items(card, data["items"])
    db.session.commit()
    return jsonify(compute_card_totals(card))


def _sync_items(card, items_data):
    # Replace all items with the provided set (simplest consistent approach)
    for it in list(card.items):
        db.session.delete(it)
    db.session.flush()
    for it in items_data:
        db.session.add(CostCardItem(
            cost_card_id=card.id,
            category=it.get("category"),
            code=it.get("code", ""),
            description=it.get("description", ""),
            unit=it.get("unit", ""),
            rendimiento=float(it.get("rendimiento", 0) or 0),
            desperdicio_pct=float(it.get("desperdicio_pct", 0) or 0),
            unit_price=float(it.get("unit_price", 0) or 0),
        ))
    db.session.commit()


@app.route("/api/costcards/<int:card_id>", methods=["DELETE"])
@login_required
def delete_costcard(card_id):
    card = CostCard.query.filter_by(id=card_id, account_id=current_account_id(), deleted_at=None).first_or_404()
    card.deleted_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    db.session.commit()
    return "", 204


@app.route("/api/costcards/<int:card_id>/restore", methods=["POST"])
@login_required
def restore_costcard(card_id):
    card = CostCard.query.filter(CostCard.id == card_id, CostCard.account_id == current_account_id(),
                                  CostCard.deleted_at.isnot(None)).first_or_404()
    if CostCard.query.filter_by(account_id=current_account_id(), code=card.code, deleted_at=None).first():
        return jsonify({"error": f"No se puede restaurar: el código '{card.code}' ya está en uso por otra ficha activa."}), 400
    card.deleted_at = None
    db.session.commit()
    return jsonify(compute_card_totals(card))


@app.route("/api/costcards/<int:card_id>/permanent", methods=["DELETE"])
@login_required
def permanent_delete_costcard(card_id):
    card = CostCard.query.filter(CostCard.id == card_id, CostCard.account_id == current_account_id(),
                                  CostCard.deleted_at.isnot(None)).first_or_404()
    db.session.delete(card)
    db.session.commit()
    return "", 204



# ---------------------------------------------------------------------------
# Quotes (Cotizaciones)
# ---------------------------------------------------------------------------

def compute_quote_totals(quote):
    lines = []
    lines_total = 0.0
    for ln in quote.lines:
        card_totals = compute_card_totals(ln.cost_card)
        line_total = card_totals["total_cost"] * (ln.quantity or 0)
        lines_total += line_total
        lines.append({
            "id": ln.id,
            "cost_card_id": ln.cost_card_id,
            "code": card_totals["code"],
            "name": card_totals["name"],
            "unit": card_totals["unit"],
            "unit_cost": card_totals["total_cost"],
            "quantity": ln.quantity,
            "line_total": round(line_total, 2),
        })

    fees = {"transportation": [], "other": []}
    fees_total = 0.0
    for fee in quote.fees:
        fees_total += fee.amount or 0
        entry = {"id": fee.id, "description": fee.description, "amount": fee.amount}
        if fee.category == "transportation":
            entry.update({"code": fee.code, "unit": fee.unit, "quantity": fee.quantity, "unit_price": fee.unit_price})
        fees[fee.category].append(entry)

    subtotal = lines_total + fees_total
    isv_amount = 0.0 if quote.exento else subtotal * 0.15
    grand_total = subtotal + isv_amount

    return {
        "id": quote.id,
        "name": quote.name,
        "client": quote.client,
        "date": quote.date,
        "exento": quote.exento,
        "lines": lines,
        "lines_total": round(lines_total, 2),
        "transportation": fees["transportation"],
        "other_fees": fees["other"],
        "fees_total": round(fees_total, 2),
        "subtotal": round(subtotal, 2),
        "isv_amount": round(isv_amount, 2),
        "grand_total": round(grand_total, 2),
    }


@app.route("/api/quotes", methods=["GET"])
@login_required
def list_quotes():
    quotes = Quote.query.filter_by(account_id=current_account_id(), deleted_at=None).order_by(Quote.id.desc()).all()
    return jsonify([compute_quote_totals(q) for q in quotes])


@app.route("/api/quotes/trash", methods=["GET"])
@login_required
def list_quotes_trash():
    quotes = (Quote.query.filter(Quote.account_id == current_account_id(), Quote.deleted_at.isnot(None))
              .order_by(Quote.deleted_at.desc()).all())
    return jsonify([compute_quote_totals(q) for q in quotes])


@app.route("/api/quotes/<int:quote_id>", methods=["GET"])
@login_required
def get_quote(quote_id):
    quote = Quote.query.filter_by(id=quote_id, account_id=current_account_id()).first_or_404()
    return jsonify(compute_quote_totals(quote))


CATEGORY_LABELS = {"material": "Materiales", "labor": "Mano de Obra", "tool": "Herramientas",
                   "transport": "Transporte", "gasto": "Otros Gastos"}


@app.route("/api/quotes/<int:quote_id>/summary", methods=["GET"])
@login_required
def get_quote_summary(quote_id):
    """Consolidated bill-of-materials style rollup: for every material/labor/tool/
    transport/gasto item across every ficha in this quote, sum the total quantity
    and cost needed for the whole project (item.total-per-ficha-unit x the quote
    line's quantity), merging by category+code so the same item used in multiple
    fichas shows up once with a combined total."""
    quote = Quote.query.filter_by(id=quote_id, account_id=current_account_id()).first_or_404()

    groups = {cat: {} for cat in CATEGORY_LABELS}
    for ln in quote.lines:
        card = ln.cost_card
        line_qty = ln.quantity or 0
        for item in card.items:
            cat = item.category
            if cat not in groups:
                continue
            rendimiento = item.rendimiento or 0
            desperdicio = (item.desperdicio_pct or 0) / 100.0
            per_unit_qty = rendimiento * (1 + desperdicio)
            total_qty = per_unit_qty * line_qty
            total_cost = per_unit_qty * (item.unit_price or 0) * line_qty

            key = item.code or item.description
            bucket = groups[cat].setdefault(key, {
                "code": item.code, "description": item.description, "unit": item.unit,
                "total_quantity": 0.0, "total_cost": 0.0,
            })
            bucket["total_quantity"] += total_qty
            bucket["total_cost"] += total_cost

    result = {}
    grand_total = 0.0
    for cat, label in CATEGORY_LABELS.items():
        items = sorted(groups[cat].values(), key=lambda x: (x["code"] or ""))
        for it in items:
            it["total_quantity"] = round(it["total_quantity"], 4)
            it["total_cost"] = round(it["total_cost"], 2)
        cat_total = round(sum(it["total_cost"] for it in items), 2)
        grand_total += cat_total
        result[cat] = {"label": label, "items": items, "total": cat_total}

    result["grand_total"] = round(grand_total, 2)
    result["quote_name"] = quote.name
    return jsonify(result)


@app.route("/api/quotes/<int:quote_id>/refresh-prices", methods=["POST"])
@login_required
def refresh_quote_prices(quote_id):
    """Pushes each ficha's material item prices to match the current catalog
    auto-price (highest quote at the most recent date), and PERSISTS it —
    unlike the client-side 'refresh' which only affects what's on screen until
    you separately open, refresh, and save each ficha. This lets one click on
    the quote update every ficha it actually uses."""
    quote = Quote.query.filter_by(id=quote_id, account_id=current_account_id(), deleted_at=None).first_or_404()

    materials_by_code = {m.code: m for m in Material.query.filter_by(account_id=current_account_id()).all()}
    cards = {ln.cost_card_id: ln.cost_card for ln in quote.lines}

    updated_items = 0
    for card in cards.values():
        for item in card.items:
            if item.category != "material":
                continue
            material = materials_by_code.get(item.code)
            if material is None:
                continue
            new_price = compute_material_auto_price(material.suppliers)
            if new_price is None:
                new_price = material.unit_price or 0
            if item.unit_price != new_price:
                item.unit_price = new_price
                updated_items += 1
        card.updated_at = datetime.utcnow().strftime("%Y-%m-%d")

    db.session.commit()
    return jsonify({"fichas_updated": len(cards), "items_updated": updated_items, **compute_quote_totals(quote)})


@app.route("/api/quotes", methods=["POST"])
@login_required
def create_quote():
    data = request.json or {}
    quote = Quote(
        account_id=current_account_id(),
        name=data.get("name", "").strip(),
        client=data.get("client", "").strip(),
        date=data.get("date") or datetime.utcnow().strftime("%Y-%m-%d"),
        exento=bool(data.get("exento", False)),
    )
    db.session.add(quote)
    db.session.commit()
    _sync_quote_children(quote, data)
    return jsonify(compute_quote_totals(quote)), 201


@app.route("/api/quotes/<int:quote_id>", methods=["PUT"])
@login_required
def update_quote(quote_id):
    quote = Quote.query.filter_by(id=quote_id, account_id=current_account_id()).first_or_404()
    data = request.json or {}
    quote.name = data.get("name", quote.name).strip()
    quote.client = data.get("client", quote.client).strip()
    quote.date = data.get("date", quote.date)
    if "exento" in data:
        quote.exento = bool(data.get("exento"))
    _sync_quote_children(quote, data)
    db.session.commit()
    return jsonify(compute_quote_totals(quote))


def _sync_quote_children(quote, data):
    account_id = current_account_id()
    if "lines" in data:
        for ln in list(quote.lines):
            db.session.delete(ln)
        db.session.flush()
        for ln in data["lines"]:
            # verify the referenced cost card actually belongs to this account
            card = CostCard.query.filter_by(id=ln["cost_card_id"], account_id=account_id).first()
            if not card:
                continue
            db.session.add(QuoteLine(
                quote_id=quote.id,
                cost_card_id=card.id,
                quantity=float(ln.get("quantity", 0) or 0),
            ))
    if "transportation" in data or "other_fees" in data:
        for fee in list(quote.fees):
            db.session.delete(fee)
        db.session.flush()
        for fee in data.get("transportation", []):
            qty = float(fee.get("quantity", 1) or 0)
            price = float(fee.get("unit_price", 0) or 0)
            db.session.add(QuoteFee(quote_id=quote.id, category="transportation",
                                     code=fee.get("code", ""),
                                     description=fee.get("description", ""),
                                     unit=fee.get("unit", ""),
                                     quantity=qty,
                                     unit_price=price,
                                     amount=qty * price))
        for fee in data.get("other_fees", []):
            db.session.add(QuoteFee(quote_id=quote.id, category="other",
                                     description=fee.get("description", ""),
                                     amount=float(fee.get("amount", 0) or 0)))
    db.session.commit()


@app.route("/api/quotes/<int:quote_id>", methods=["DELETE"])
@login_required
def delete_quote(quote_id):
    quote = Quote.query.filter_by(id=quote_id, account_id=current_account_id(), deleted_at=None).first_or_404()
    quote.deleted_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    db.session.commit()
    return "", 204


@app.route("/api/quotes/<int:quote_id>/restore", methods=["POST"])
@login_required
def restore_quote(quote_id):
    quote = Quote.query.filter(Quote.id == quote_id, Quote.account_id == current_account_id(),
                                Quote.deleted_at.isnot(None)).first_or_404()
    quote.deleted_at = None
    db.session.commit()
    return jsonify(compute_quote_totals(quote))


@app.route("/api/quotes/<int:quote_id>/permanent", methods=["DELETE"])
@login_required
def permanent_delete_quote(quote_id):
    quote = Quote.query.filter(Quote.id == quote_id, Quote.account_id == current_account_id(),
                                Quote.deleted_at.isnot(None)).first_or_404()
    db.session.delete(quote)
    db.session.commit()
    return "", 204


# ---------------------------------------------------------------------------
# Regulación studies (Planificador de Demanda) - save/load full tool state
# ---------------------------------------------------------------------------

def regulacion_summary(r):
    return {"id": r.id, "name": r.name, "updated_at": r.updated_at}


@app.route("/api/regulacion", methods=["GET"])
@login_required
def list_regulacion_studies():
    rows = RegulacionStudy.query.filter_by(account_id=current_account_id()).order_by(RegulacionStudy.id.desc()).all()
    return jsonify([regulacion_summary(r) for r in rows])


@app.route("/api/regulacion/<int:study_id>", methods=["GET"])
@login_required
def get_regulacion_study(study_id):
    r = RegulacionStudy.query.filter_by(id=study_id, account_id=current_account_id()).first_or_404()
    return jsonify({**regulacion_summary(r), "data": json.loads(r.data)})


@app.route("/api/regulacion", methods=["POST"])
@login_required
def create_regulacion_study():
    body = request.json or {}
    name = (body.get("name") or "").strip() or "Estudio sin título"
    r = RegulacionStudy(
        account_id=current_account_id(),
        name=name,
        data=json.dumps(body.get("data", {})),
        updated_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
    )
    db.session.add(r)
    db.session.commit()
    return jsonify(regulacion_summary(r)), 201


@app.route("/api/regulacion/<int:study_id>", methods=["PUT"])
@login_required
def update_regulacion_study(study_id):
    r = RegulacionStudy.query.filter_by(id=study_id, account_id=current_account_id()).first_or_404()
    body = request.json or {}
    if "name" in body and (body["name"] or "").strip():
        r.name = body["name"].strip()
    if "data" in body:
        r.data = json.dumps(body["data"])
    r.updated_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    db.session.commit()
    return jsonify(regulacion_summary(r))


@app.route("/api/regulacion/<int:study_id>", methods=["DELETE"])
@login_required
def delete_regulacion_study(study_id):
    r = RegulacionStudy.query.filter_by(id=study_id, account_id=current_account_id()).first_or_404()
    db.session.delete(r)
    db.session.commit()
    return "", 204


# ---------------------------------------------------------------------------
# Facturación (Invoicing)
# ---------------------------------------------------------------------------

@app.route("/facturacion/")
@login_required
def facturacion():
    log_page_view("/facturacion/")
    return send_from_directory(FACTURACION_DIR, "index.html")


@app.route("/facturacion/factura-common.js")
@login_required
def facturacion_common_js():
    return send_from_directory(FACTURACION_DIR, "factura-common.js", mimetype="application/javascript")


TEMPLATE_FILES = {
    "clasica": "ver.html",
    "moderna": "ver-moderna.html",
    "elegante": "ver-elegante.html",
    "compacta": "ver-compacta.html",
    "colorblock": "ver-colorblock.html",
    "termica58": "ver-termica58.html",
    "termica80": "ver-termica80.html",
}


@app.route("/facturacion/ver/")
@login_required
def factura_ver():
    log_page_view("/facturacion/ver/")
    invoice_id = request.args.get("id", type=int)
    if invoice_id:
        invoice = Invoice.query.filter_by(id=invoice_id, account_id=current_account_id()).first()
        template = invoice.template if invoice else "clasica"
    else:
        account = Account.query.get(current_account_id())
        template = (account.default_invoice_template if account else None) or "clasica"
    filename = TEMPLATE_FILES.get(template, "ver.html")
    return send_from_directory(FACTURACION_DIR, filename)


# ---------------------------------------------------------------------------
# Cotización Clásica (quote in the same visual format as Factura Clásica)
# ---------------------------------------------------------------------------

@app.route("/cotizacion-clasica/ver/")
@login_required
def cotizacion_clasica_ver():
    log_page_view("/cotizacion-clasica/ver/")
    return send_from_directory(COTIZACION_CLASICA_DIR, "ver.html")


@app.route("/cotizacion-clasica/cotizacion-common.js")
@login_required
def cotizacion_clasica_common_js():
    return send_from_directory(COTIZACION_CLASICA_DIR, "cotizacion-common.js", mimetype="application/javascript")


# ---------------------------------------------------------------------------
# Clientes (customer records)
# ---------------------------------------------------------------------------

@app.route("/clientes/")
@login_required
def clientes_page():
    log_page_view("/clientes/")
    return send_from_directory(CLIENTES_DIR, "index.html")


def cliente_to_dict(c):
    campos_requeridos = [c.rtn, c.direccion, c.contacto, c.telefono, c.correo]
    return {
        "id": c.id, "nombre": c.nombre, "rtn": c.rtn, "direccion": c.direccion,
        "contacto": c.contacto, "telefono": c.telefono, "correo": c.correo,
        "created_at": c.created_at, "updated_at": c.updated_at,
        "datos_incompletos": any(not (f or "").strip() for f in campos_requeridos),
    }


@app.route("/api/clientes", methods=["GET"])
@login_required
def list_clientes():
    q = request.args.get("q", "").strip().lower()
    clientes = Cliente.query.filter_by(account_id=current_account_id(), deleted_at=None).order_by(Cliente.nombre).all()
    if q:
        clientes = [c for c in clientes if q in c.nombre.lower() or q in (c.rtn or "").lower()
                    or q in (c.correo or "").lower() or q in (c.telefono or "").lower()]
    return jsonify([cliente_to_dict(c) for c in clientes])


@app.route("/api/clientes/trash", methods=["GET"])
@login_required
def list_clientes_trash():
    clientes = (Cliente.query.filter(Cliente.account_id == current_account_id(), Cliente.deleted_at.isnot(None))
                .order_by(Cliente.deleted_at.desc()).all())
    return jsonify([cliente_to_dict(c) for c in clientes])


@app.route("/api/clientes/<int:cliente_id>", methods=["GET"])
@login_required
def get_cliente(cliente_id):
    c = Cliente.query.filter_by(id=cliente_id, account_id=current_account_id()).first_or_404()
    return jsonify(cliente_to_dict(c))


@app.route("/api/clientes/<int:cliente_id>/invoices", methods=["GET"])
@login_required
def get_cliente_invoices(cliente_id):
    cliente = Cliente.query.filter_by(id=cliente_id, account_id=current_account_id()).first_or_404()
    # Match invoices linked by cliente_id, plus older invoices that predate the
    # link and were only ever recorded by name (kept so history isn't lost).
    invoices = (Invoice.query.filter_by(account_id=current_account_id(), deleted_at=None)
                .filter(db.or_(Invoice.cliente_id == cliente_id, Invoice.cliente_nombre == cliente.nombre))
                .order_by(Invoice.fecha.desc()).all())
    return jsonify([compute_invoice_totals(i) for i in invoices])


@app.route("/api/clientes", methods=["POST"])
@login_required
def create_cliente():
    data = request.json or {}
    nombre = (data.get("nombre") or "").strip()
    if not nombre:
        return jsonify({"error": "El nombre del cliente es requerido."}), 400
    c = Cliente(
        account_id=current_account_id(),
        nombre=nombre,
        rtn=(data.get("rtn") or "").strip(),
        direccion=(data.get("direccion") or "").strip(),
        contacto=(data.get("contacto") or "").strip(),
        telefono=(data.get("telefono") or "").strip(),
        correo=(data.get("correo") or "").strip(),
        created_at=datetime.utcnow().strftime("%Y-%m-%d"),
        updated_at=datetime.utcnow().strftime("%Y-%m-%d"),
    )
    db.session.add(c)
    db.session.commit()
    return jsonify(cliente_to_dict(c)), 201


@app.route("/api/clientes/<int:cliente_id>", methods=["PUT"])
@login_required
def update_cliente(cliente_id):
    c = Cliente.query.filter_by(id=cliente_id, account_id=current_account_id()).first_or_404()
    data = request.json or {}
    nombre = (data.get("nombre") or c.nombre).strip()
    if not nombre:
        return jsonify({"error": "El nombre del cliente es requerido."}), 400
    c.nombre = nombre
    c.rtn = (data.get("rtn", c.rtn) or "").strip()
    c.direccion = (data.get("direccion", c.direccion) or "").strip()
    c.contacto = (data.get("contacto", c.contacto) or "").strip()
    c.telefono = (data.get("telefono", c.telefono) or "").strip()
    c.correo = (data.get("correo", c.correo) or "").strip()
    c.updated_at = datetime.utcnow().strftime("%Y-%m-%d")
    db.session.commit()
    return jsonify(cliente_to_dict(c))


@app.route("/api/clientes/<int:cliente_id>", methods=["DELETE"])
@login_required
def delete_cliente(cliente_id):
    c = Cliente.query.filter_by(id=cliente_id, account_id=current_account_id(), deleted_at=None).first_or_404()
    c.deleted_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    db.session.commit()
    return "", 204


@app.route("/api/clientes/<int:cliente_id>/restore", methods=["POST"])
@login_required
def restore_cliente(cliente_id):
    c = Cliente.query.filter(Cliente.id == cliente_id, Cliente.account_id == current_account_id(),
                              Cliente.deleted_at.isnot(None)).first_or_404()
    c.deleted_at = None
    db.session.commit()
    return jsonify(cliente_to_dict(c))


@app.route("/api/clientes/<int:cliente_id>/permanent", methods=["DELETE"])
@login_required
def permanent_delete_cliente(cliente_id):
    c = Cliente.query.filter(Cliente.id == cliente_id, Cliente.account_id == current_account_id(),
                              Cliente.deleted_at.isnot(None)).first_or_404()
    db.session.delete(c)
    db.session.commit()
    return "", 204


def compute_invoice_totals(invoice):
    lines = []
    subtotal = 0.0
    for ln in invoice.lines:
        total = round((ln.cantidad or 0) * (ln.precio_unitario or 0), 2)
        subtotal += total
        lines.append({
            "id": ln.id, "cantidad": ln.cantidad,
            "descripcion": ln.descripcion, "precio_unitario": ln.precio_unitario,
            "total": total,
        })
    subtotal = round(subtotal, 2)

    descuentos = invoice.descuentos or 0
    importe_exonerado = invoice.importe_exonerado or 0
    importe_exento = invoice.importe_exento or 0
    base_gravable = max(0.0, round(subtotal - descuentos - importe_exonerado - importe_exento, 2))

    if invoice.gravado_18_pct:
        importe_gravado_15, importe_gravado_18 = 0.0, base_gravable
        isv_15, isv_18 = 0.0, round(base_gravable * 0.18, 2)
    else:
        importe_gravado_15, importe_gravado_18 = base_gravable, 0.0
        isv_15, isv_18 = round(base_gravable * 0.15, 2), 0.0

    total_a_pagar = round(subtotal - descuentos + isv_15 + isv_18, 2)

    return {
        "id": invoice.id,
        "numero": invoice.numero,
        "template": invoice.template,
        "cliente_nombre": invoice.cliente_nombre,
        "cliente_rtn": invoice.cliente_rtn,
        "cliente_id": invoice.cliente_id,
        "estado": invoice.estado,
        "fecha": invoice.fecha,
        "termino_pago": invoice.termino_pago,
        "lines": lines,
        "subtotal": subtotal,
        "descuentos": descuentos,
        "importe_exonerado": importe_exonerado,
        "importe_exento": importe_exento,
        "importe_gravado_15": importe_gravado_15,
        "importe_gravado_18": importe_gravado_18,
        "isv_15": isv_15,
        "isv_18": isv_18,
        "total_a_pagar": total_a_pagar,
        "total_en_letras": numero_a_letras(total_a_pagar),
        "orden_compra_exenta": invoice.orden_compra_exenta,
        "constancia_registro_exonerado": invoice.constancia_registro_exonerado,
        "registro_sag": invoice.registro_sag,
        "created_at": invoice.created_at,
        "updated_at": invoice.updated_at,
    }


@app.route("/api/invoices", methods=["GET"])
@login_required
def list_invoices():
    invoices = (Invoice.query.filter_by(account_id=current_account_id(), deleted_at=None)
                .order_by(Invoice.id.desc()).all())
    return jsonify([compute_invoice_totals(i) for i in invoices])


@app.route("/api/invoices/trash", methods=["GET"])
@login_required
def list_invoices_trash():
    invoices = (Invoice.query.filter(Invoice.account_id == current_account_id(), Invoice.deleted_at.isnot(None))
                .order_by(Invoice.deleted_at.desc()).all())
    return jsonify([compute_invoice_totals(i) for i in invoices])


@app.route("/api/invoices/<int:invoice_id>", methods=["GET"])
@login_required
def get_invoice(invoice_id):
    invoice = Invoice.query.filter_by(id=invoice_id, account_id=current_account_id()).first_or_404()
    return jsonify(compute_invoice_totals(invoice))


@app.route("/api/invoices/<int:invoice_id>/pdf", methods=["GET"])
@login_required
def get_invoice_pdf(invoice_id):
    invoice = Invoice.query.filter_by(id=invoice_id, account_id=current_account_id()).first_or_404()
    account = Account.query.get_or_404(current_account_id())
    invoice_dict = compute_invoice_totals(invoice)
    try:
        pdf_bytes = render_invoice_pdf(invoice_dict, account)
    except Exception as e:
        return jsonify({"error": f"No se pudo generar el PDF: {e}"}), 500
    filename = _build_invoice_pdf_filename(invoice)
    return pdf_bytes, 200, {
        "Content-Type": "application/pdf",
        "Content-Disposition": f'inline; filename="{filename}"',
    }


def _build_invoice_pdf_filename(invoice):
    """Factura_{numero}_{ClienteName}_{DD-MM-YYYY}.pdf - sanitized since the
    client name is free-text and could contain characters invalid in
    Windows/Unix filenames."""
    def _safe(s):
        s = re.sub(r'[\\/:*?"<>|]', '', s or '')
        s = re.sub(r'\s+', '_', s.strip())
        return s or "SinNombre"

    cliente_part = _safe(invoice.cliente_nombre)
    numero_part = _safe(invoice.numero)

    raw_fecha = invoice.fecha or ""
    try:
        y, m, d = raw_fecha.split("-")
        fecha_part = f"{d}-{m}-{y}"
    except (ValueError, AttributeError):
        fecha_part = _safe(raw_fecha)

    return f"Factura_{numero_part}_{cliente_part}_{fecha_part}.pdf"


def _next_invoice_numero(account):
    parts = (account.invoice_prefix or "").split("-")
    if len(parts) < 3 or not all(parts[:3]):
        return None  # prefijo not configured yet
    seq = str(account.next_invoice_number or 1).zfill(8)
    return f"{parts[0]}-{parts[1]}-{parts[2]}-{seq}"


def _resolve_cliente_id(account_id, cliente_id, cliente_nombre, cliente_rtn):
    """Figures out which Cliente this invoice should link to:
    - If cliente_id was given explicitly (picked from the search box), use it.
    - Otherwise, if an existing client's name matches exactly (case-insensitive),
      link to that one instead of creating a duplicate.
    - Otherwise, this is a genuinely new client typed on the invoice - create it
      with just the name/RTN we have, so it shows up in Clientes ready to fill in."""
    if cliente_id:
        exists = Cliente.query.filter_by(id=cliente_id, account_id=account_id, deleted_at=None).first()
        if exists:
            return cliente_id
    if not cliente_nombre:
        return None
    match = (Cliente.query.filter_by(account_id=account_id, deleted_at=None)
             .filter(db.func.lower(Cliente.nombre) == cliente_nombre.strip().lower()).first())
    if match:
        return match.id
    nuevo = Cliente(
        account_id=account_id, nombre=cliente_nombre.strip(), rtn=(cliente_rtn or "").strip(),
        created_at=datetime.utcnow().strftime("%Y-%m-%d"), updated_at=datetime.utcnow().strftime("%Y-%m-%d"),
    )
    db.session.add(nuevo)
    db.session.flush()  # get nuevo.id without a full commit yet
    return nuevo.id


def _validate_invoice_date(account_id, fecha, exclude_invoice_id=None):
    """Facturas must stay in chronological order (matches sequential numbering
    conventions in Honduras). Returns an error message, or None if the date is OK."""
    q = Invoice.query.filter(Invoice.account_id == account_id, Invoice.deleted_at.is_(None),
                              Invoice.fecha > fecha)
    if exclude_invoice_id:
        q = q.filter(Invoice.id != exclude_invoice_id)
    later = q.order_by(Invoice.fecha.desc()).first()
    if later:
        return (f"Esta fecha es anterior a otra factura ya existente ({later.numero}, "
                f"fechada {later.fecha}). Las facturas deben mantener orden cronológico.")
    return None


def _sync_invoice_lines(invoice, lines_data):
    for ln in list(invoice.lines):
        db.session.delete(ln)
    db.session.flush()
    for ln in lines_data:
        db.session.add(InvoiceLine(
            invoice_id=invoice.id,
            cantidad=float(ln.get("cantidad", 1) or 0),
            descripcion=(ln.get("descripcion") or "").strip(),
            precio_unitario=float(ln.get("precio_unitario", 0) or 0),
        ))
    db.session.commit()


@app.route("/api/invoices", methods=["POST"])
@login_required
def create_invoice():
    account = Account.query.get_or_404(current_account_id())
    numero = _next_invoice_numero(account)
    if not numero:
        return jsonify({"error": "Configura el Prefijo de Factura en Configuración de la Cuenta antes de crear facturas."}), 400

    data = request.json or {}
    cliente_nombre = (data.get("cliente_nombre") or "").strip()
    if not cliente_nombre:
        return jsonify({"error": "El nombre del cliente es requerido."}), 400

    fecha = data.get("fecha") or datetime.utcnow().strftime("%Y-%m-%d")
    date_error = _validate_invoice_date(account.id, fecha)
    if date_error:
        return jsonify({"error": date_error}), 400

    cliente_rtn = (data.get("cliente_rtn") or "").strip()
    resolved_cliente_id = _resolve_cliente_id(account.id, data.get("cliente_id"), cliente_nombre, cliente_rtn)

    invoice = Invoice(
        account_id=account.id,
        numero=numero,
        template=account.default_invoice_template or "clasica",
        cliente_nombre=cliente_nombre,
        cliente_rtn=cliente_rtn,
        cliente_id=resolved_cliente_id,
        estado=(data.get("estado") or "Falta Pago").strip(),
        fecha=fecha,
        termino_pago=data.get("termino_pago") or "contado",
        descuentos=float(data.get("descuentos", 0) or 0),
        importe_exonerado=float(data.get("importe_exonerado", 0) or 0),
        importe_exento=float(data.get("importe_exento", 0) or 0),
        gravado_18_pct=bool(data.get("gravado_18_pct", False)),
        orden_compra_exenta=(data.get("orden_compra_exenta") or "").strip(),
        constancia_registro_exonerado=(data.get("constancia_registro_exonerado") or "").strip(),
        registro_sag=(data.get("registro_sag") or "").strip(),
        created_at=datetime.utcnow().strftime("%Y-%m-%d"),
        updated_at=datetime.utcnow().strftime("%Y-%m-%d"),
    )
    db.session.add(invoice)
    db.session.commit()
    _sync_invoice_lines(invoice, data.get("lines", []))

    account.next_invoice_number = (account.next_invoice_number or 1) + 1
    db.session.commit()

    return jsonify(compute_invoice_totals(invoice)), 201


@app.route("/api/invoices/<int:invoice_id>", methods=["PUT"])
@login_required
def update_invoice(invoice_id):
    invoice = Invoice.query.filter_by(id=invoice_id, account_id=current_account_id()).first_or_404()
    data = request.json or {}

    cliente_nombre = (data.get("cliente_nombre") or invoice.cliente_nombre).strip()
    if not cliente_nombre:
        return jsonify({"error": "El nombre del cliente es requerido."}), 400
    invoice.cliente_nombre = cliente_nombre
    invoice.cliente_rtn = (data.get("cliente_rtn", invoice.cliente_rtn) or "").strip()
    invoice.cliente_id = _resolve_cliente_id(invoice.account_id, data.get("cliente_id", invoice.cliente_id),
                                              invoice.cliente_nombre, invoice.cliente_rtn)
    invoice.estado = (data.get("estado", invoice.estado) or "Falta Pago").strip()

    new_fecha = data.get("fecha", invoice.fecha)
    if new_fecha != invoice.fecha:
        date_error = _validate_invoice_date(invoice.account_id, new_fecha, exclude_invoice_id=invoice.id)
        if date_error:
            return jsonify({"error": date_error}), 400
    invoice.fecha = new_fecha

    invoice.termino_pago = data.get("termino_pago", invoice.termino_pago)
    invoice.template = (data.get("template", invoice.template) or "clasica").strip()
    if "descuentos" in data:
        invoice.descuentos = float(data.get("descuentos") or 0)
    if "importe_exonerado" in data:
        invoice.importe_exonerado = float(data.get("importe_exonerado") or 0)
    if "importe_exento" in data:
        invoice.importe_exento = float(data.get("importe_exento") or 0)
    if "gravado_18_pct" in data:
        invoice.gravado_18_pct = bool(data.get("gravado_18_pct"))
    invoice.orden_compra_exenta = (data.get("orden_compra_exenta", invoice.orden_compra_exenta) or "").strip()
    invoice.constancia_registro_exonerado = (data.get("constancia_registro_exonerado", invoice.constancia_registro_exonerado) or "").strip()
    invoice.registro_sag = (data.get("registro_sag", invoice.registro_sag) or "").strip()
    invoice.updated_at = datetime.utcnow().strftime("%Y-%m-%d")

    if "lines" in data:
        _sync_invoice_lines(invoice, data["lines"])
    db.session.commit()
    return jsonify(compute_invoice_totals(invoice))


@app.route("/api/invoices/<int:invoice_id>", methods=["DELETE"])
@login_required
def delete_invoice(invoice_id):
    invoice = Invoice.query.filter_by(id=invoice_id, account_id=current_account_id(), deleted_at=None).first_or_404()
    invoice.deleted_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    db.session.commit()
    return "", 204


@app.route("/api/invoices/<int:invoice_id>/restore", methods=["POST"])
@login_required
def restore_invoice(invoice_id):
    invoice = Invoice.query.filter(Invoice.id == invoice_id, Invoice.account_id == current_account_id(),
                                    Invoice.deleted_at.isnot(None)).first_or_404()
    invoice.deleted_at = None
    db.session.commit()
    return jsonify(compute_invoice_totals(invoice))


@app.route("/api/invoices/<int:invoice_id>/permanent", methods=["DELETE"])
@login_required
def permanent_delete_invoice(invoice_id):
    invoice = Invoice.query.filter(Invoice.id == invoice_id, Invoice.account_id == current_account_id(),
                                    Invoice.deleted_at.isnot(None)).first_or_404()
    db.session.delete(invoice)
    db.session.commit()
    return "", 204


# ---------------------------------------------------------------------------
# Cotización Clásica API
# ---------------------------------------------------------------------------

def compute_cotizacion_totals(cot):
    lines = []
    subtotal = 0.0
    for ln in cot.lines:
        total = round((ln.cantidad or 0) * (ln.precio_unitario or 0), 2)
        subtotal += total
        lines.append({
            "id": ln.id, "cantidad": ln.cantidad,
            "descripcion": ln.descripcion, "precio_unitario": ln.precio_unitario,
            "total": total,
        })
    subtotal = round(subtotal, 2)

    descuentos = cot.descuentos or 0
    importe_exonerado = cot.importe_exonerado or 0
    importe_exento = cot.importe_exento or 0
    base_gravable = max(0.0, round(subtotal - descuentos - importe_exonerado - importe_exento, 2))

    if cot.gravado_18_pct:
        importe_gravado_15, importe_gravado_18 = 0.0, base_gravable
        isv_15, isv_18 = 0.0, round(base_gravable * 0.18, 2)
    else:
        importe_gravado_15, importe_gravado_18 = base_gravable, 0.0
        isv_15, isv_18 = round(base_gravable * 0.15, 2), 0.0

    total_a_pagar = round(subtotal - descuentos + isv_15 + isv_18, 2)

    return {
        "id": cot.id,
        "numero": cot.numero,
        "cliente_nombre": cot.cliente_nombre,
        "cliente_rtn": cot.cliente_rtn,
        "cliente_id": cot.cliente_id,
        "fecha": cot.fecha,
        "termino_pago": cot.termino_pago,
        "nota": cot.nota,
        "lines": lines,
        "subtotal": subtotal,
        "descuentos": descuentos,
        "importe_exonerado": importe_exonerado,
        "importe_exento": importe_exento,
        "importe_gravado_15": importe_gravado_15,
        "importe_gravado_18": importe_gravado_18,
        "isv_15": isv_15,
        "isv_18": isv_18,
        "total_a_pagar": total_a_pagar,
        "created_at": cot.created_at,
        "updated_at": cot.updated_at,
    }


def _sync_cotizacion_lines(cot, lines_data):
    for ln in list(cot.lines):
        db.session.delete(ln)
    db.session.flush()
    for ln in lines_data:
        db.session.add(CotizacionLine(
            cotizacion_id=cot.id,
            cantidad=float(ln.get("cantidad", 1) or 0),
            descripcion=(ln.get("descripcion") or "").strip(),
            precio_unitario=float(ln.get("precio_unitario", 0) or 0),
        ))
    db.session.commit()


def _build_cotizacion_pdf_filename(cot):
    """Cotizacion_{numero}_{ClienteName}_{DD-MM-YYYY}.pdf - sanitized since
    the client name is free-text and could contain characters invalid in
    Windows/Unix filenames."""
    def _safe(s):
        s = re.sub(r'[\\/:*?"<>|]', '', s or '')
        s = re.sub(r'\s+', '_', s.strip())
        return s or "SinNombre"

    cliente_part = _safe(cot.cliente_nombre)
    numero_part = "{:06d}".format(cot.numero)

    raw_fecha = cot.fecha or ""
    try:
        y, m, d = raw_fecha.split("-")
        fecha_part = f"{d}-{m}-{y}"
    except (ValueError, AttributeError):
        fecha_part = _safe(raw_fecha)

    return f"Cotizacion_{numero_part}_{cliente_part}_{fecha_part}.pdf"


@app.route("/api/cotizaciones-clasica", methods=["GET"])
@login_required
def list_cotizaciones_clasica():
    cots = (Cotizacion.query.filter_by(account_id=current_account_id(), deleted_at=None)
            .order_by(Cotizacion.id.desc()).all())
    return jsonify([compute_cotizacion_totals(c) for c in cots])


@app.route("/api/cotizaciones-clasica/trash", methods=["GET"])
@login_required
def list_cotizaciones_clasica_trash():
    cots = (Cotizacion.query.filter(Cotizacion.account_id == current_account_id(), Cotizacion.deleted_at.isnot(None))
            .order_by(Cotizacion.deleted_at.desc()).all())
    return jsonify([compute_cotizacion_totals(c) for c in cots])


@app.route("/api/cotizaciones-clasica/<int:cot_id>", methods=["GET"])
@login_required
def get_cotizacion_clasica(cot_id):
    cot = Cotizacion.query.filter_by(id=cot_id, account_id=current_account_id()).first_or_404()
    return jsonify(compute_cotizacion_totals(cot))


@app.route("/api/cotizaciones-clasica/<int:cot_id>/pdf", methods=["GET"])
@login_required
def get_cotizacion_clasica_pdf(cot_id):
    cot = Cotizacion.query.filter_by(id=cot_id, account_id=current_account_id()).first_or_404()
    account = Account.query.get_or_404(current_account_id())
    cot_dict = compute_cotizacion_totals(cot)
    try:
        pdf_bytes = render_cotizacion_pdf(cot_dict, account)
    except Exception as e:
        return jsonify({"error": f"No se pudo generar el PDF: {e}"}), 500
    filename = _build_cotizacion_pdf_filename(cot)
    return pdf_bytes, 200, {
        "Content-Type": "application/pdf",
        "Content-Disposition": f'inline; filename="{filename}"',
    }


@app.route("/api/cotizaciones-clasica", methods=["POST"])
@login_required
def create_cotizacion_clasica():
    account = Account.query.get_or_404(current_account_id())
    data = request.json or {}
    cliente_nombre = (data.get("cliente_nombre") or "").strip()
    if not cliente_nombre:
        return jsonify({"error": "El nombre del cliente es requerido."}), 400

    numero = account.next_cotizacion_number or 1
    cliente_rtn = (data.get("cliente_rtn") or "").strip()
    resolved_cliente_id = _resolve_cliente_id(account.id, data.get("cliente_id"), cliente_nombre, cliente_rtn)

    cot = Cotizacion(
        account_id=account.id,
        numero=numero,
        cliente_nombre=cliente_nombre,
        cliente_rtn=cliente_rtn,
        cliente_id=resolved_cliente_id,
        fecha=data.get("fecha") or datetime.utcnow().strftime("%Y-%m-%d"),
        termino_pago=data.get("termino_pago") or "contado",
        nota=(data.get("nota") or "").strip(),
        descuentos=float(data.get("descuentos", 0) or 0),
        importe_exonerado=float(data.get("importe_exonerado", 0) or 0),
        importe_exento=float(data.get("importe_exento", 0) or 0),
        gravado_18_pct=bool(data.get("gravado_18_pct", False)),
        created_at=datetime.utcnow().strftime("%Y-%m-%d"),
        updated_at=datetime.utcnow().strftime("%Y-%m-%d"),
    )
    db.session.add(cot)
    db.session.commit()
    _sync_cotizacion_lines(cot, data.get("lines", []))

    account.next_cotizacion_number = numero + 1
    db.session.commit()

    return jsonify(compute_cotizacion_totals(cot)), 201


@app.route("/api/cotizaciones-clasica/<int:cot_id>", methods=["PUT"])
@login_required
def update_cotizacion_clasica(cot_id):
    cot = Cotizacion.query.filter_by(id=cot_id, account_id=current_account_id()).first_or_404()
    data = request.json or {}

    cliente_nombre = (data.get("cliente_nombre") or cot.cliente_nombre).strip()
    if not cliente_nombre:
        return jsonify({"error": "El nombre del cliente es requerido."}), 400
    cot.cliente_nombre = cliente_nombre
    cot.cliente_rtn = (data.get("cliente_rtn", cot.cliente_rtn) or "").strip()
    cot.cliente_id = _resolve_cliente_id(cot.account_id, data.get("cliente_id", cot.cliente_id),
                                          cot.cliente_nombre, cot.cliente_rtn)
    cot.fecha = data.get("fecha", cot.fecha)
    cot.termino_pago = data.get("termino_pago", cot.termino_pago)
    if "nota" in data:
        cot.nota = (data.get("nota") or "").strip()
    if "descuentos" in data:
        cot.descuentos = float(data.get("descuentos") or 0)
    if "importe_exonerado" in data:
        cot.importe_exonerado = float(data.get("importe_exonerado") or 0)
    if "importe_exento" in data:
        cot.importe_exento = float(data.get("importe_exento") or 0)
    if "gravado_18_pct" in data:
        cot.gravado_18_pct = bool(data.get("gravado_18_pct"))
    cot.updated_at = datetime.utcnow().strftime("%Y-%m-%d")

    if "lines" in data:
        _sync_cotizacion_lines(cot, data["lines"])
    db.session.commit()
    return jsonify(compute_cotizacion_totals(cot))


@app.route("/api/cotizaciones-clasica/<int:cot_id>", methods=["DELETE"])
@login_required
def delete_cotizacion_clasica(cot_id):
    cot = Cotizacion.query.filter_by(id=cot_id, account_id=current_account_id(), deleted_at=None).first_or_404()
    cot.deleted_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    db.session.commit()
    return "", 204


@app.route("/api/cotizaciones-clasica/<int:cot_id>/restore", methods=["POST"])
@login_required
def restore_cotizacion_clasica(cot_id):
    cot = Cotizacion.query.filter(Cotizacion.id == cot_id, Cotizacion.account_id == current_account_id(),
                                   Cotizacion.deleted_at.isnot(None)).first_or_404()
    cot.deleted_at = None
    db.session.commit()
    return jsonify(compute_cotizacion_totals(cot))


@app.route("/api/cotizaciones-clasica/<int:cot_id>/permanent", methods=["DELETE"])
@login_required
def permanent_delete_cotizacion_clasica(cot_id):
    cot = Cotizacion.query.filter(Cotizacion.id == cot_id, Cotizacion.account_id == current_account_id(),
                                   Cotizacion.deleted_at.isnot(None)).first_or_404()
    db.session.delete(cot)
    db.session.commit()
    return "", 204


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
