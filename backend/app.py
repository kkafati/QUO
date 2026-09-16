import os
import re
import json
import calendar
import mimetypes
import secrets
from functools import wraps
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_from_directory, session, redirect, url_for, abort
from werkzeug.security import check_password_hash, generate_password_hash
from models import db, Account, Material, Labor, Tool, Transport, Gasto, CostCard, CostCardItem, Quote, QuoteLine, QuoteFee, SupplierPrice, RegulacionStudy, Admin, LoginEvent, PageView, Invoice, InvoiceLine, Cliente, Cotizacion, CotizacionLine, Proforma, ProformaLine, GastoOperativo, GastoOperativoItem, GASTO_CATEGORIAS, StockMovimiento, Pago, CuentaContable, AsientoContable, AsientoLinea, CuentaPorPagar, PagoProveedor, MovimientoBancario, GASTO_CATEGORIA_CODIGOS, ActivoFijo, DepreciacionRegistro, LoginAttempt
from numero_a_letras import numero_a_letras
from pdf_render import render_invoice_pdf
from pdf_render_cotizacion import render_cotizacion_pdf
from pdf_render_proforma import render_proforma_pdf

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
PROFORMA_DIR = os.path.join(os.path.dirname(BASE_DIR), "proforma")
CONTABILIDAD_DIR = os.path.join(os.path.dirname(BASE_DIR), "contabilidad")
CLIENTES_DIR = os.path.join(os.path.dirname(BASE_DIR), "clientes")
INVENTARIO_DIR = os.path.join(os.path.dirname(BASE_DIR), "inventario")

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="/cotizaciones")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "quoting.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
# IMPORTANT: set the SECRET_KEY environment variable before deploying for
# real - anyone who has this value can forge login sessions. If it's not
# set, generate a random one at process startup instead of falling back to
# a hardcoded string literal that would otherwise sit in this source file
# forever, publicly known to anyone who can read the repo. The failure mode
# this creates if SECRET_KEY is forgotten - sessions get invalidated on
# every restart - is annoying but safe, unlike the old silently-insecure default.
_secret_key = os.environ.get("SECRET_KEY")
if not _secret_key:
    _secret_key = secrets.token_hex(32)
    # Some consoles (Windows cmd/PowerShell on a non-UTF8 codepage) can't
    # encode the emoji/accented characters below and would raise
    # UnicodeEncodeError - which, left unhandled, would crash the app before
    # SECRET_KEY even gets set. A warning that prevents startup entirely
    # defeats its own purpose, so fall back to a plain-ASCII version rather
    # than let that happen.
    _warning = (
        "\n⚠️  SECRET_KEY no configurado - usando una clave temporal generada al "
        "inicio. Las sesiones se invalidarán si el proceso se reinicia. Configura "
        "la variable de entorno SECRET_KEY antes de desplegar en producción.\n"
    )
    try:
        print(_warning)
    except UnicodeEncodeError:
        print(_warning.encode("ascii", errors="replace").decode("ascii"))
app.config["SECRET_KEY"] = _secret_key
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

    try:
        cols = [row[1] for row in db.session.execute(db.text("PRAGMA table_info(gastos_operativos)")).fetchall()]
        gasto_migrations = {
            "numero_factura": "ALTER TABLE gastos_operativos ADD COLUMN numero_factura VARCHAR(64)",
            "subtotal": "ALTER TABLE gastos_operativos ADD COLUMN subtotal FLOAT DEFAULT 0",
            "descuento": "ALTER TABLE gastos_operativos ADD COLUMN descuento FLOAT DEFAULT 0",
            "isv": "ALTER TABLE gastos_operativos ADD COLUMN isv FLOAT DEFAULT 0",
        }
        for col, ddl in gasto_migrations.items():
            if col not in cols:
                db.session.execute(db.text(ddl))
        db.session.commit()
        # Backfill: existing rows have monto but subtotal=0 - treat the old
        # monto as the subtotal (no items, no discount/isv) so totals stay correct.
        db.session.execute(db.text(
            "UPDATE gastos_operativos SET subtotal = monto WHERE subtotal = 0 AND monto != 0"
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()

    try:
        item_cols = [row[1] for row in db.session.execute(db.text("PRAGMA table_info(gastos_operativos_items)")).fetchall()]
        item_migrations = {
            "descuento": "ALTER TABLE gastos_operativos_items ADD COLUMN descuento FLOAT DEFAULT 0",
            "isv_pct": "ALTER TABLE gastos_operativos_items ADD COLUMN isv_pct FLOAT DEFAULT 15",
        }
        for col, ddl in item_migrations.items():
            if col not in item_cols:
                db.session.execute(db.text(ddl))
        db.session.commit()
    except Exception:
        db.session.rollback()

    try:
        cols = [row[1] for row in db.session.execute(db.text("PRAGMA table_info(materials)")).fetchall()]
        if "minimo_stock" not in cols:
            db.session.execute(db.text("ALTER TABLE materials ADD COLUMN minimo_stock FLOAT DEFAULT 0"))
            db.session.commit()
    except Exception:
        db.session.rollback()

CATEGORY_MODELS = {"material": Material, "labor": Labor, "tool": Tool, "transport": Transport, "gasto": Gasto}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def current_account_id():
    return session.get("account_id")


def current_admin_id():
    return session.get("admin_id")


def client_ip():
    """This app is deployed behind Cloudflare Tunnel - request.remote_addr
    would be Cloudflare's own IP, not the real client's. Use this everywhere
    a client IP is needed, same pattern already used by log_page_view/LoginEvent."""
    return request.headers.get("CF-Connecting-IP", request.remote_addr)


LOGIN_LOCKOUT_WINDOW_MINUTES = 15
LOGIN_LOCKOUT_MAX_PER_USERNAME = 5   # failed attempts against ONE username
LOGIN_LOCKOUT_MAX_PER_IP = 20        # failed attempts from ONE IP, across ANY usernames


def log_login_attempt(username, ip_address, success):
    """Every attempt, successful or not, becomes a row here - the audit
    trail for "who's been trying to log in". Never deleted on success; the
    rolling window in is_login_locked_out() below is what makes old failures
    stop counting, not erasing them."""
    db.session.add(LoginAttempt(
        username=username, ip_address=ip_address, success=success,
        timestamp=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    ))
    db.session.commit()


def is_login_locked_out(username, ip_address):
    """Checked BEFORE the password hash comparison, so a locked-out attempt
    never pays that cost. Two independent thresholds in the same rolling
    window: per-username (catches repeated guesses against one account) and
    per-IP (catches one attacker trying many different usernames, which the
    per-username check alone would never trip). Either one being over its
    limit is enough to reject."""
    since = (datetime.utcnow() - timedelta(minutes=LOGIN_LOCKOUT_WINDOW_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")

    failed_by_username = LoginAttempt.query.filter(
        LoginAttempt.username == username,
        LoginAttempt.success.is_(False),
        LoginAttempt.timestamp >= since,
    ).count()
    if failed_by_username >= LOGIN_LOCKOUT_MAX_PER_USERNAME:
        return True

    if ip_address:
        failed_by_ip = LoginAttempt.query.filter(
            LoginAttempt.ip_address == ip_address,
            LoginAttempt.success.is_(False),
            LoginAttempt.timestamp >= since,
        ).count()
        if failed_by_ip >= LOGIN_LOCKOUT_MAX_PER_IP:
            return True

    return False


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
def require_csrf_header():
    """Defense-in-depth CSRF mitigation. Every state-changing call from this
    app's own frontend goes through fetch() with this header explicitly set
    (every POST/PUT/DELETE fetch() call site in the frontend sets it - grep
    for X-Requested-With to confirm). A plain HTML <form> submitted from a
    third-party page cannot set custom headers, so this blocks the classic
    "attacker's page silently submits a form to your API" pattern. This is
    an additional layer on top of SameSite=Lax on the session cookie
    (already set, already correct), not a replacement for it - and it's not
    a full token-issuance/rotation CSRF system, which this app doesn't need
    given it has no third-party-embeddable form targets."""
    if request.method in ("POST", "PUT", "DELETE") and request.headers.get("X-Requested-With") != "XMLHttpRequest":
        return jsonify({"error": "Solicitud rechazada: falta encabezado requerido."}), 403


@app.after_request
def set_security_headers(response):
    """Baseline security headers on every response. CSP starts at
    default-src 'self' and widens only for what this app actually loads:
    Google Fonts' stylesheet (style-src) and its font files (font-src) -
    checked by grepping every .html file for external resources, nothing
    else is loaded from a third party anywhere in this codebase. script-src
    and style-src need 'unsafe-inline' because this app's pages rely
    throughout on inline <script>/<style> blocks (no nonce/hash
    infrastructure exists here) - this is a known, deliberate trade-off:
    it still blocks loading an arbitrary remote <script src="https://evil...">,
    which is the actual "third-party script/style injection" this header
    is meant to stop, just not a reflected/stored-XSS inline payload."""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"  # this app is never embedded in an iframe anywhere - confirmed, no <iframe> in this codebase
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    )
    return response


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
    ip_address = client_ip()

    if is_login_locked_out(username, ip_address):
        log_login_attempt(username, ip_address, False)
        return jsonify({"error": "Demasiados intentos. Intenta de nuevo en unos minutos."}), 429

    account = Account.query.filter_by(username=username).first()
    if not account or not check_password_hash(account.password_hash, password):
        log_login_attempt(username, ip_address, False)
        return jsonify({"error": "Usuario o contraseña incorrectos."}), 401

    log_login_attempt(username, ip_address, True)
    session["account_id"] = account.id
    session["company_name"] = account.company_name
    session.permanent = True
    account.last_seen = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    db.session.add(LoginEvent(
        account_id=account.id, event_type="login",
        timestamp=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        ip_address=ip_address,
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
    ip_address = client_ip()

    if is_login_locked_out(username, ip_address):
        log_login_attempt(username, ip_address, False)
        return jsonify({"error": "Demasiados intentos. Intenta de nuevo en unos minutos."}), 429

    admin = Admin.query.filter_by(username=username).first()
    if not admin or not check_password_hash(admin.password_hash, password):
        log_login_attempt(username, ip_address, False)
        return jsonify({"error": "Usuario o contraseña incorrectos."}), 401

    log_login_attempt(username, ip_address, True)
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
    base["minimo_stock"] = item.minimo_stock
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
            kwargs["minimo_stock"] = float(data.get("minimo_stock", 0) or 0)
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
        if category == "material":
            item.minimo_stock = float(data.get("minimo_stock", item.minimo_stock) or 0)
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
# Factura Proforma
# ---------------------------------------------------------------------------

@app.route("/proforma/ver/")
@login_required
def proforma_ver():
    log_page_view("/proforma/ver/")
    return send_from_directory(PROFORMA_DIR, "ver.html")


@app.route("/proforma/proforma-common.js")
@login_required
def proforma_common_js():
    return send_from_directory(PROFORMA_DIR, "proforma-common.js", mimetype="application/javascript")


# ---------------------------------------------------------------------------
# Contabilidad
# ---------------------------------------------------------------------------

@app.route("/contabilidad/")
@login_required
def contabilidad():
    log_page_view("/contabilidad/")
    return send_from_directory(CONTABILIDAD_DIR, "index.html")


# ---------------------------------------------------------------------------
# Inventario
# ---------------------------------------------------------------------------

@app.route("/inventario/")
@login_required
def inventario():
    log_page_view("/inventario/")
    return send_from_directory(INVENTARIO_DIR, "index.html")


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


@app.route("/api/clientes/<int:cliente_id>/cotizaciones-clasica", methods=["GET"])
@login_required
def get_cliente_cotizaciones_clasica(cliente_id):
    cliente = Cliente.query.filter_by(id=cliente_id, account_id=current_account_id()).first_or_404()
    cots = (Cotizacion.query.filter_by(account_id=current_account_id(), deleted_at=None)
            .filter(db.or_(Cotizacion.cliente_id == cliente_id, Cotizacion.cliente_nombre == cliente.nombre))
            .order_by(Cotizacion.fecha.desc()).all())
    return jsonify([compute_cotizacion_totals(c) for c in cots])


@app.route("/api/clientes/<int:cliente_id>/proformas", methods=["GET"])
@login_required
def get_cliente_proformas(cliente_id):
    cliente = Cliente.query.filter_by(id=cliente_id, account_id=current_account_id()).first_or_404()
    pfs = (Proforma.query.filter_by(account_id=current_account_id(), deleted_at=None)
           .filter(db.or_(Proforma.cliente_id == cliente_id, Proforma.cliente_nombre == cliente.nombre))
           .order_by(Proforma.fecha.desc()).all())
    return jsonify([compute_proforma_totals(p) for p in pfs])


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


def compute_invoice_pagado(invoice_id):
    total = db.session.query(db.func.sum(Pago.monto)).filter(Pago.invoice_id == invoice_id).scalar()
    return round(total or 0, 2)


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

    total_pagado = compute_invoice_pagado(invoice.id)
    saldo = round(total_a_pagar - total_pagado, 2)
    # Surface (never silently hide) a manually-set "Pagado" that disagrees
    # with what's actually been paid, instead of trusting the label blindly.
    estado_discrepancia = invoice.estado == "Pagado" and saldo > 0.01

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
        "total_pagado": total_pagado,
        "saldo": saldo,
        "estado_discrepancia": estado_discrepancia,
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
    q = Invoice.query.filter_by(account_id=current_account_id(), deleted_at=None)
    desde = request.args.get("desde")
    hasta = request.args.get("hasta")
    if desde:
        q = q.filter(Invoice.fecha >= desde)
    if hasta:
        q = q.filter(Invoice.fecha <= hasta)
    invoices = q.order_by(Invoice.id.desc()).all()
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
    """Does NOT commit - callers control the transaction boundary, since
    create_invoice needs the invoice, its lines, and its posted asiento to
    land atomically together (see crear_asiento's own commit).

    For a brand-new (just-constructed, not yet committed) invoice,
    invoice.lines starts as an empty in-memory collection and - unlike after
    a commit, which expires it - a plain flush() does NOT make SQLAlchemy
    re-query it. Without the explicit expire below, compute_invoice_totals()
    would see zero lines here and post an empty (rejected) asiento."""
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
    db.session.flush()
    db.session.expire(invoice, ["lines"])


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
    db.session.flush()  # get invoice.id, without committing yet - see below
    _sync_invoice_lines(invoice, data.get("lines", []))

    account.next_invoice_number = (account.next_invoice_number or 1) + 1

    # Post the asiento in the SAME transaction as the invoice/lines above: the
    # invoice was only flush()'d, not committed, so if posting fails (it
    # shouldn't - the lines below are constructed to always balance - but the
    # check is the one invariant that must never be skipped) everything rolls
    # back together instead of leaving an invoice with no journal entry.
    try:
        post_factura_asiento(invoice)
    except ValueError as e:
        db.session.rollback()
        return jsonify({"error": f"No se pudo registrar el asiento contable: {e}"}), 400

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
# Pagos (payments recorded against an Invoice)
# ---------------------------------------------------------------------------

def pago_to_dict(p):
    return {
        "id": p.id,
        "invoice_id": p.invoice_id,
        "monto": p.monto,
        "fecha": p.fecha,
        "metodo": p.metodo,
        "referencia": p.referencia,
        "created_at": p.created_at,
    }


@app.route("/api/invoices/<int:invoice_id>/pagos", methods=["GET"])
@login_required
def list_pagos(invoice_id):
    invoice = Invoice.query.filter_by(id=invoice_id, account_id=current_account_id()).first_or_404()
    pagos = Pago.query.filter_by(invoice_id=invoice.id).order_by(Pago.fecha.desc(), Pago.id.desc()).all()
    return jsonify([pago_to_dict(p) for p in pagos])


@app.route("/api/invoices/<int:invoice_id>/pagos", methods=["POST"])
@login_required
def create_pago(invoice_id):
    invoice = Invoice.query.filter_by(id=invoice_id, account_id=current_account_id()).first_or_404()
    data = request.json or {}
    try:
        monto = float(data.get("monto", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "El monto debe ser un número."}), 400
    if monto <= 0:
        return jsonify({"error": "El monto debe ser mayor a cero."}), 400

    totals = compute_invoice_totals(invoice)
    ya_pagado = totals["total_pagado"]
    # A payment can never push the running total above what's actually owed -
    # allow a tiny epsilon for float rounding, not a real overpayment.
    if ya_pagado + monto > totals["total_a_pagar"] + 0.01:
        saldo_pendiente = round(totals["total_a_pagar"] - ya_pagado, 2)
        return jsonify({"error": f"Este pago excede el saldo pendiente de la factura (L. {saldo_pendiente:.2f})."}), 400

    now = datetime.utcnow().strftime("%Y-%m-%d")
    p = Pago(
        account_id=current_account_id(),
        invoice_id=invoice.id,
        monto=monto,
        fecha=data.get("fecha") or now,
        metodo=(data.get("metodo") or "").strip(),
        referencia=(data.get("referencia") or "").strip(),
        created_at=now,
    )
    db.session.add(p)
    db.session.flush()  # get p.id for posting, commit happens with the asiento below

    try:
        post_pago_asiento(p, invoice)
    except ValueError as e:
        db.session.rollback()
        return jsonify({"error": f"No se pudo registrar el asiento contable: {e}"}), 400

    # Auto-suggest: once payments fully cover the balance, mark it Pagado -
    # but this only ever moves estado TOWARD Pagado, never away from a value
    # someone set manually for other reasons (see Pago model docstring).
    nuevo_pagado = round(ya_pagado + monto, 2)
    if nuevo_pagado >= totals["total_a_pagar"] - 0.01 and invoice.estado != "Pagado":
        invoice.estado = "Pagado"
        db.session.commit()

    return jsonify(pago_to_dict(p)), 201


@app.route("/api/pagos/<int:pago_id>", methods=["DELETE"])
@login_required
def delete_pago(pago_id):
    p = Pago.query.filter_by(id=pago_id, account_id=current_account_id()).first_or_404()
    db.session.delete(p)
    db.session.commit()
    # Deliberately does NOT revert estado - if this leaves a "Pagado" invoice
    # underpaid, that discrepancy surfaces via estado_discrepancia instead.
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


@app.route("/api/cotizaciones-clasica/<int:cot_id>/convertir-a-factura", methods=["POST"])
@login_required
def convertir_cotizacion_a_factura(cot_id):
    cot = Cotizacion.query.filter_by(id=cot_id, account_id=current_account_id(), deleted_at=None).first_or_404()
    account = Account.query.get_or_404(current_account_id())

    numero = _next_invoice_numero(account)
    if not numero:
        return jsonify({"error": "Configura el Prefijo de Factura en Configuración de la Cuenta antes de convertir cotizaciones en facturas."}), 400

    # The invoice is issued right now (when the button is pressed), not
    # backdated to the quote's own date. Facturas must stay in chronological
    # order, so if a later-dated invoice already exists for some reason,
    # use that date instead of today rather than blocking the conversion -
    # a one-click "convert this quote" action should never fail just
    # because of ordering housekeeping the user didn't ask to think about.
    fecha = datetime.utcnow().strftime("%Y-%m-%d")
    latest = (Invoice.query.filter_by(account_id=account.id, deleted_at=None)
              .order_by(Invoice.fecha.desc()).first())
    if latest and latest.fecha and latest.fecha > fecha:
        fecha = latest.fecha

    invoice = Invoice(
        account_id=account.id,
        numero=numero,
        template=account.default_invoice_template or "clasica",
        cliente_nombre=cot.cliente_nombre,
        cliente_rtn=cot.cliente_rtn,
        cliente_id=cot.cliente_id,
        estado="Falta Pago",
        fecha=fecha,
        termino_pago=cot.termino_pago,
        descuentos=cot.descuentos,
        importe_exonerado=cot.importe_exonerado,
        importe_exento=cot.importe_exento,
        gravado_18_pct=cot.gravado_18_pct,
        created_at=fecha,
        updated_at=fecha,
    )
    db.session.add(invoice)
    db.session.commit()

    for ln in cot.lines:
        db.session.add(InvoiceLine(
            invoice_id=invoice.id,
            cantidad=ln.cantidad,
            descripcion=ln.descripcion,
            precio_unitario=ln.precio_unitario,
        ))
    db.session.commit()

    account.next_invoice_number = (account.next_invoice_number or 1) + 1
    db.session.commit()

    return jsonify(compute_invoice_totals(invoice)), 201


# ---------------------------------------------------------------------------
# Factura Proforma API
# ---------------------------------------------------------------------------

def compute_proforma_totals(pf):
    lines = []
    subtotal = 0.0
    for ln in pf.lines:
        total = round((ln.cantidad or 0) * (ln.precio_unitario or 0), 2)
        subtotal += total
        lines.append({
            "id": ln.id, "cantidad": ln.cantidad,
            "descripcion": ln.descripcion, "precio_unitario": ln.precio_unitario,
            "total": total,
        })
    subtotal = round(subtotal, 2)

    descuentos = pf.descuentos or 0
    importe_exonerado = pf.importe_exonerado or 0
    importe_exento = pf.importe_exento or 0
    base_gravable = max(0.0, round(subtotal - descuentos - importe_exonerado - importe_exento, 2))

    if pf.gravado_18_pct:
        importe_gravado_15, importe_gravado_18 = 0.0, base_gravable
        isv_15, isv_18 = 0.0, round(base_gravable * 0.18, 2)
    else:
        importe_gravado_15, importe_gravado_18 = base_gravable, 0.0
        isv_15, isv_18 = round(base_gravable * 0.15, 2), 0.0

    total_a_pagar = round(subtotal - descuentos + isv_15 + isv_18, 2)

    return {
        "id": pf.id,
        "cliente_nombre": pf.cliente_nombre,
        "cliente_rtn": pf.cliente_rtn,
        "cliente_id": pf.cliente_id,
        "fecha": pf.fecha,
        "termino_pago": pf.termino_pago,
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
        "orden_compra_exenta": pf.orden_compra_exenta,
        "constancia_registro_exonerado": pf.constancia_registro_exonerado,
        "registro_sag": pf.registro_sag,
        "created_at": pf.created_at,
        "updated_at": pf.updated_at,
    }


def _sync_proforma_lines(pf, lines_data):
    for ln in list(pf.lines):
        db.session.delete(ln)
    db.session.flush()
    for ln in lines_data:
        db.session.add(ProformaLine(
            proforma_id=pf.id,
            cantidad=float(ln.get("cantidad", 1) or 0),
            descripcion=(ln.get("descripcion") or "").strip(),
            precio_unitario=float(ln.get("precio_unitario", 0) or 0),
        ))
    db.session.commit()


def _build_proforma_pdf_filename(pf):
    """Proforma_{ClienteName}_{DD-MM-YYYY}.pdf - no invoice number to
    include since a proforma isn't numbered. Sanitized since the client
    name is free-text."""
    def _safe(s):
        s = re.sub(r'[\\/:*?"<>|]', '', s or '')
        s = re.sub(r'\s+', '_', s.strip())
        return s or "SinNombre"

    cliente_part = _safe(pf.cliente_nombre)
    raw_fecha = pf.fecha or ""
    try:
        y, m, d = raw_fecha.split("-")
        fecha_part = f"{d}-{m}-{y}"
    except (ValueError, AttributeError):
        fecha_part = _safe(raw_fecha)

    return f"Proforma_{cliente_part}_{fecha_part}.pdf"


@app.route("/api/proformas", methods=["GET"])
@login_required
def list_proformas():
    pfs = (Proforma.query.filter_by(account_id=current_account_id(), deleted_at=None)
           .order_by(Proforma.id.desc()).all())
    return jsonify([compute_proforma_totals(p) for p in pfs])


@app.route("/api/proformas/trash", methods=["GET"])
@login_required
def list_proformas_trash():
    pfs = (Proforma.query.filter(Proforma.account_id == current_account_id(), Proforma.deleted_at.isnot(None))
           .order_by(Proforma.deleted_at.desc()).all())
    return jsonify([compute_proforma_totals(p) for p in pfs])


@app.route("/api/proformas/<int:pf_id>", methods=["GET"])
@login_required
def get_proforma(pf_id):
    pf = Proforma.query.filter_by(id=pf_id, account_id=current_account_id()).first_or_404()
    return jsonify(compute_proforma_totals(pf))


@app.route("/api/proformas/<int:pf_id>/pdf", methods=["GET"])
@login_required
def get_proforma_pdf(pf_id):
    pf = Proforma.query.filter_by(id=pf_id, account_id=current_account_id()).first_or_404()
    account = Account.query.get_or_404(current_account_id())
    pf_dict = compute_proforma_totals(pf)
    try:
        pdf_bytes = render_proforma_pdf(pf_dict, account)
    except Exception as e:
        return jsonify({"error": f"No se pudo generar el PDF: {e}"}), 500
    filename = _build_proforma_pdf_filename(pf)
    return pdf_bytes, 200, {
        "Content-Type": "application/pdf",
        "Content-Disposition": f'inline; filename="{filename}"',
    }


@app.route("/api/proformas", methods=["POST"])
@login_required
def create_proforma():
    account = Account.query.get_or_404(current_account_id())
    data = request.json or {}
    cliente_nombre = (data.get("cliente_nombre") or "").strip()
    if not cliente_nombre:
        return jsonify({"error": "El nombre del cliente es requerido."}), 400

    cliente_rtn = (data.get("cliente_rtn") or "").strip()
    resolved_cliente_id = _resolve_cliente_id(account.id, data.get("cliente_id"), cliente_nombre, cliente_rtn)

    pf = Proforma(
        account_id=account.id,
        cliente_nombre=cliente_nombre,
        cliente_rtn=cliente_rtn,
        cliente_id=resolved_cliente_id,
        fecha=data.get("fecha") or datetime.utcnow().strftime("%Y-%m-%d"),
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
    db.session.add(pf)
    db.session.commit()
    _sync_proforma_lines(pf, data.get("lines", []))

    return jsonify(compute_proforma_totals(pf)), 201


@app.route("/api/proformas/<int:pf_id>", methods=["PUT"])
@login_required
def update_proforma(pf_id):
    pf = Proforma.query.filter_by(id=pf_id, account_id=current_account_id()).first_or_404()
    data = request.json or {}

    cliente_nombre = (data.get("cliente_nombre") or pf.cliente_nombre).strip()
    if not cliente_nombre:
        return jsonify({"error": "El nombre del cliente es requerido."}), 400
    pf.cliente_nombre = cliente_nombre
    pf.cliente_rtn = (data.get("cliente_rtn", pf.cliente_rtn) or "").strip()
    pf.cliente_id = _resolve_cliente_id(pf.account_id, data.get("cliente_id", pf.cliente_id),
                                         pf.cliente_nombre, pf.cliente_rtn)
    pf.fecha = data.get("fecha", pf.fecha)
    pf.termino_pago = data.get("termino_pago", pf.termino_pago)
    if "descuentos" in data:
        pf.descuentos = float(data.get("descuentos") or 0)
    if "importe_exonerado" in data:
        pf.importe_exonerado = float(data.get("importe_exonerado") or 0)
    if "importe_exento" in data:
        pf.importe_exento = float(data.get("importe_exento") or 0)
    if "gravado_18_pct" in data:
        pf.gravado_18_pct = bool(data.get("gravado_18_pct"))
    pf.orden_compra_exenta = (data.get("orden_compra_exenta", pf.orden_compra_exenta) or "").strip()
    pf.constancia_registro_exonerado = (data.get("constancia_registro_exonerado", pf.constancia_registro_exonerado) or "").strip()
    pf.registro_sag = (data.get("registro_sag", pf.registro_sag) or "").strip()
    pf.updated_at = datetime.utcnow().strftime("%Y-%m-%d")

    if "lines" in data:
        _sync_proforma_lines(pf, data["lines"])
    db.session.commit()
    return jsonify(compute_proforma_totals(pf))


@app.route("/api/proformas/<int:pf_id>", methods=["DELETE"])
@login_required
def delete_proforma(pf_id):
    pf = Proforma.query.filter_by(id=pf_id, account_id=current_account_id(), deleted_at=None).first_or_404()
    pf.deleted_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    db.session.commit()
    return "", 204


@app.route("/api/proformas/<int:pf_id>/restore", methods=["POST"])
@login_required
def restore_proforma(pf_id):
    pf = Proforma.query.filter(Proforma.id == pf_id, Proforma.account_id == current_account_id(),
                                Proforma.deleted_at.isnot(None)).first_or_404()
    pf.deleted_at = None
    db.session.commit()
    return jsonify(compute_proforma_totals(pf))


@app.route("/api/proformas/<int:pf_id>/permanent", methods=["DELETE"])
@login_required
def permanent_delete_proforma(pf_id):
    pf = Proforma.query.filter(Proforma.id == pf_id, Proforma.account_id == current_account_id(),
                                Proforma.deleted_at.isnot(None)).first_or_404()
    db.session.delete(pf)
    db.session.commit()
    return "", 204


@app.route("/api/proformas/<int:pf_id>/convertir-a-factura", methods=["POST"])
@login_required
def convertir_proforma_a_factura(pf_id):
    pf = Proforma.query.filter_by(id=pf_id, account_id=current_account_id(), deleted_at=None).first_or_404()
    account = Account.query.get_or_404(current_account_id())

    numero = _next_invoice_numero(account)
    if not numero:
        return jsonify({"error": "Configura el Prefijo de Factura en Configuración de la Cuenta antes de convertir proformas en facturas."}), 400

    fecha = datetime.utcnow().strftime("%Y-%m-%d")
    latest = (Invoice.query.filter_by(account_id=account.id, deleted_at=None)
              .order_by(Invoice.fecha.desc()).first())
    if latest and latest.fecha and latest.fecha > fecha:
        fecha = latest.fecha

    invoice = Invoice(
        account_id=account.id,
        numero=numero,
        template=account.default_invoice_template or "clasica",
        cliente_nombre=pf.cliente_nombre,
        cliente_rtn=pf.cliente_rtn,
        cliente_id=pf.cliente_id,
        estado="Falta Pago",
        fecha=fecha,
        termino_pago=pf.termino_pago,
        descuentos=pf.descuentos,
        importe_exonerado=pf.importe_exonerado,
        importe_exento=pf.importe_exento,
        gravado_18_pct=pf.gravado_18_pct,
        orden_compra_exenta=pf.orden_compra_exenta,
        constancia_registro_exonerado=pf.constancia_registro_exonerado,
        registro_sag=pf.registro_sag,
        created_at=fecha,
        updated_at=fecha,
    )
    db.session.add(invoice)
    db.session.commit()

    for ln in pf.lines:
        db.session.add(InvoiceLine(
            invoice_id=invoice.id,
            cantidad=ln.cantidad,
            descripcion=ln.descripcion,
            precio_unitario=ln.precio_unitario,
        ))
    db.session.commit()

    account.next_invoice_number = (account.next_invoice_number or 1) + 1
    db.session.commit()

    return jsonify(compute_invoice_totals(invoice)), 201


# ---------------------------------------------------------------------------
# Contabilidad - Catálogo de Cuentas y Asientos Contables (Phase 2: real
# double-entry bookkeeping). Every flow below that moves money - facturas,
# pagos, gastos, cuentas por pagar, pagos a proveedores - posts a balanced
# journal entry through crear_asiento(), the one function that enforces
# sum(debe) == sum(haber). Historical rows created before this phase was
# deployed do NOT get retroactive entries here - see scripts/backfill_ledger.py
# for that, run manually and reviewed, never automatically.
# ---------------------------------------------------------------------------

def ensure_chart_of_accounts(account_id):
    """Seeds a reasonable default Catálogo de Cuentas the first time this
    account touches the ledger, so nobody has to set one up from zero before
    anything can post. Idempotent per ACCOUNT *and* per CODIGO: safe to call
    on every posting (a no-op once everything exists), and safe to extend
    with new accounts (as Phase 4 does below) that then get added to an
    existing account's chart on its next call, without touching or
    duplicating what's already there."""
    now = datetime.utcnow().strftime("%Y-%m-%d")
    existentes = {c.codigo: c for c in CuentaContable.query.filter_by(account_id=account_id).all()}

    def add(codigo, nombre, tipo, padre_codigo=None):
        if codigo in existentes:
            return existentes[codigo]
        padre = existentes.get(padre_codigo)
        cuenta = CuentaContable(
            account_id=account_id, codigo=codigo, nombre=nombre, tipo=tipo,
            cuenta_padre_id=padre.id if padre else None, created_at=now,
        )
        db.session.add(cuenta)
        db.session.flush()
        existentes[codigo] = cuenta
        return cuenta

    add("1000", "Activo Circulante", "activo")
    add("1010", "Caja y Bancos", "activo", "1000")
    add("1020", "Cuentas por Cobrar", "activo", "1000")
    add("1030", "Inventario", "activo", "1000")
    # Phase 4: 1040 is a contra-asset - still tipo="activo" like every other
    # asset account (no separate "contra" tipo exists, or is needed), it just
    # naturally accumulates a negative balance as depreciation credits post
    # to it. That's correct and expected under the existing sign convention.
    add("1040", "Depreciación Acumulada", "activo", "1000")
    add("1050", "Activo Fijo", "activo", "1000")
    add("1060", "Ajuste de Inventario", "activo", "1000")
    add("2000", "Pasivo Circulante", "pasivo")
    add("2010", "Cuentas por Pagar", "pasivo", "2000")
    add("2020", "ISV por Pagar", "pasivo", "2000")
    add("3000", "Patrimonio", "patrimonio")
    add("3010", "Capital", "patrimonio", "3000")
    add("3020", "Utilidades Retenidas", "patrimonio", "3000")
    add("4000", "Ingresos", "ingreso")
    add("4010", "Ventas", "ingreso", "4000")
    add("5000", "Costos y Gastos", "gasto")
    for categoria, codigo in GASTO_CATEGORIA_CODIGOS.items():
        add(codigo, categoria, "gasto", "5000")
    # Phase 4 additions.
    add("5100", "Costo de Ventas", "gasto", "5000")
    add("5110", "Gasto de Depreciación", "gasto", "5000")
    add("5120", "Gasto por Merma de Inventario", "gasto", "5000")
    db.session.commit()


def crear_asiento(account_id, fecha, descripcion, origen_type, origen_id, lineas):
    """The ONLY function that should ever create an AsientoContable - every
    posting path in this file goes through it so the balance check lives in
    exactly one place. `lineas` is a list of {cuenta_codigo, debe, haber,
    descripcion?}. Raises ValueError (never silently accepts) if debe/haber
    don't sum to the same total, or if a cuenta_codigo doesn't resolve."""
    ensure_chart_of_accounts(account_id)

    # Drop no-op lines (e.g. an exempt invoice's ISV line, or a fully
    # discounted Ventas line) - they'd otherwise clutter the asiento with a
    # 0/0 row that contributes nothing to either side of the balance.
    lineas = [l for l in lineas
              if round(float(l.get("debe", 0) or 0), 2) != 0 or round(float(l.get("haber", 0) or 0), 2) != 0]

    total_debe = round(sum(float(l.get("debe", 0) or 0) for l in lineas), 2)
    total_haber = round(sum(float(l.get("haber", 0) or 0) for l in lineas), 2)
    if total_debe != total_haber:
        raise ValueError(f"Asiento desbalanceado: debe {total_debe} != haber {total_haber}.")
    if total_debe == 0:
        raise ValueError("El asiento no puede estar vacío.")

    cuentas_por_codigo = {}
    for l in lineas:
        codigo = l["cuenta_codigo"]
        if codigo not in cuentas_por_codigo:
            cuenta = CuentaContable.query.filter_by(account_id=account_id, codigo=codigo, deleted_at=None).first()
            if not cuenta:
                raise ValueError(f"Cuenta contable '{codigo}' no encontrada.")
            cuentas_por_codigo[codigo] = cuenta

    asiento = AsientoContable(
        account_id=account_id, fecha=fecha, descripcion=descripcion,
        origen_type=origen_type, origen_id=origen_id,
        created_at=datetime.utcnow().strftime("%Y-%m-%d"),
    )
    db.session.add(asiento)
    db.session.flush()

    for l in lineas:
        db.session.add(AsientoLinea(
            asiento_id=asiento.id, cuenta_contable_id=cuentas_por_codigo[l["cuenta_codigo"]].id,
            debe=round(float(l.get("debe", 0) or 0), 2), haber=round(float(l.get("haber", 0) or 0), 2),
            descripcion=l.get("descripcion"),
        ))
    db.session.commit()
    return asiento


# Each of these builds the lineas for one kind of transaction and posts them
# through crear_asiento. Both the live create_* routes below AND
# scripts/backfill_ledger.py call these SAME functions - never two separate
# implementations of "how a factura posts" that could quietly drift apart.

def post_factura_asiento(invoice):
    totals = compute_invoice_totals(invoice)
    return crear_asiento(
        account_id=invoice.account_id, fecha=invoice.fecha,
        descripcion=f"Factura {invoice.numero} - {invoice.cliente_nombre}",
        origen_type="factura", origen_id=invoice.id,
        lineas=[
            {"cuenta_codigo": "1020", "debe": totals["total_a_pagar"], "haber": 0},
            # Ventas is credited net of descuentos (not raw subtotal) so this
            # always balances against total_a_pagar = subtotal - descuentos +
            # isv by construction, even when an invoice has a discount.
            {"cuenta_codigo": "4010", "debe": 0, "haber": round(totals["subtotal"] - totals["descuentos"], 2)},
            {"cuenta_codigo": "2020", "debe": 0, "haber": round(totals["isv_15"] + totals["isv_18"], 2)},
        ],
    )


def post_pago_asiento(pago, invoice):
    return crear_asiento(
        account_id=pago.account_id, fecha=pago.fecha,
        descripcion=f"Pago factura {invoice.numero} - {invoice.cliente_nombre}",
        origen_type="pago", origen_id=pago.id,
        lineas=[
            {"cuenta_codigo": "1010", "debe": pago.monto, "haber": 0},
            {"cuenta_codigo": "1020", "debe": 0, "haber": pago.monto},
        ],
    )


def post_gasto_asiento(gasto):
    # GastoOperativo has no "paid on credit" concept (CuentaPorPagar exists
    # for that) - assume it's paid immediately in cash/bank.
    categoria_codigo = GASTO_CATEGORIA_CODIGOS.get(gasto.categoria, GASTO_CATEGORIA_CODIGOS["Otros"])
    return crear_asiento(
        account_id=gasto.account_id, fecha=gasto.fecha,
        descripcion=f"Gasto: {gasto.descripcion}",
        origen_type="gasto", origen_id=gasto.id,
        lineas=[
            {"cuenta_codigo": categoria_codigo, "debe": gasto.monto, "haber": 0},
            {"cuenta_codigo": "1010", "debe": 0, "haber": gasto.monto},
        ],
    )


def post_cuenta_por_pagar_asiento(cxp):
    categoria_codigo = GASTO_CATEGORIA_CODIGOS.get(cxp.categoria, GASTO_CATEGORIA_CODIGOS["Otros"])
    return crear_asiento(
        account_id=cxp.account_id, fecha=cxp.fecha_emision,
        descripcion=f"Cuenta por pagar: {cxp.proveedor} - {cxp.descripcion}",
        origen_type="cuenta_por_pagar", origen_id=cxp.id,
        lineas=[
            {"cuenta_codigo": categoria_codigo, "debe": cxp.monto, "haber": 0},
            {"cuenta_codigo": "2010", "debe": 0, "haber": cxp.monto},
        ],
    )


def post_pago_proveedor_asiento(pago, cxp):
    return crear_asiento(
        account_id=pago.account_id, fecha=pago.fecha,
        descripcion=f"Pago a proveedor: {cxp.proveedor} - {cxp.descripcion}",
        origen_type="pago_proveedor", origen_id=pago.id,
        lineas=[
            {"cuenta_codigo": "2010", "debe": pago.monto, "haber": 0},
            {"cuenta_codigo": "1010", "debe": 0, "haber": pago.monto},
        ],
    )


def post_activo_fijo_asiento(activo):
    # Assumed paid immediately in cash/bank - same simplification Phase 2
    # made for GastoOperativo. No "bought on credit" link to Cuentas por
    # Pagar for fixed assets in this phase.
    return crear_asiento(
        account_id=activo.account_id, fecha=activo.fecha_adquisicion,
        descripcion=f"Compra de activo fijo: {activo.nombre}",
        origen_type="activo_fijo", origen_id=activo.id,
        lineas=[
            {"cuenta_codigo": "1050", "debe": activo.costo_adquisicion, "haber": 0},
            {"cuenta_codigo": "1010", "debe": 0, "haber": activo.costo_adquisicion},
        ],
    )


def post_depreciacion_asiento(activo, periodo, fecha, monto):
    return crear_asiento(
        account_id=activo.account_id, fecha=fecha,
        descripcion=f"Depreciación {periodo}: {activo.nombre}",
        origen_type="depreciacion", origen_id=activo.id,
        lineas=[
            {"cuenta_codigo": "5110", "debe": monto, "haber": 0},
            {"cuenta_codigo": "1040", "debe": 0, "haber": monto},
        ],
    )


def post_movimiento_inventario_asiento(movimiento, material):
    """Debits/credits Inventario per Phase 4's rules, using material.unit_price
    AT THE TIME of the movement - there's no FIFO/average costing here (a real
    feature, out of scope); every salida is treated as a cost of goods sold,
    since this system has no sub-type for "internal use" vs "sold on a job".
    Entrada purchases are assumed paid immediately in cash/bank, same
    simplification as GastoOperativo and ActivoFijo above."""
    valor = round(abs(movimiento.cantidad) * (material.unit_price or 0), 2)
    if valor == 0:
        return None  # an unpriced material (unit_price=0) has nothing to post
    descripcion = f"Movimiento de inventario ({movimiento.tipo}): {material.code} - {material.description}"
    if movimiento.tipo == "entrada":
        lineas = [
            {"cuenta_codigo": "1030", "debe": valor, "haber": 0},
            {"cuenta_codigo": "1010", "debe": 0, "haber": valor},
        ]
    elif movimiento.tipo == "salida":
        lineas = [
            {"cuenta_codigo": "5100", "debe": valor, "haber": 0},
            {"cuenta_codigo": "1030", "debe": 0, "haber": valor},
        ]
    elif movimiento.cantidad > 0:  # ajuste positivo - count came in higher than recorded
        lineas = [
            {"cuenta_codigo": "1030", "debe": valor, "haber": 0},
            {"cuenta_codigo": "1060", "debe": 0, "haber": valor},
        ]
    else:  # ajuste negativo - shrinkage/loss
        lineas = [
            {"cuenta_codigo": "5120", "debe": valor, "haber": 0},
            {"cuenta_codigo": "1030", "debe": 0, "haber": valor},
        ]
    return crear_asiento(
        account_id=movimiento.account_id, fecha=movimiento.fecha, descripcion=descripcion,
        origen_type="movimiento_inventario", origen_id=movimiento.id, lineas=lineas,
    )


def cuenta_contable_to_dict(c):
    return {
        "id": c.id, "codigo": c.codigo, "nombre": c.nombre, "tipo": c.tipo,
        "cuenta_padre_id": c.cuenta_padre_id, "created_at": c.created_at,
    }


@app.route("/api/cuentas-contables", methods=["GET"])
@login_required
def list_cuentas_contables():
    ensure_chart_of_accounts(current_account_id())
    cuentas = (CuentaContable.query.filter_by(account_id=current_account_id(), deleted_at=None)
               .order_by(CuentaContable.codigo).all())
    return jsonify([cuenta_contable_to_dict(c) for c in cuentas])


@app.route("/api/cuentas-contables", methods=["POST"])
@login_required
def create_cuenta_contable():
    data = request.json or {}
    codigo = (data.get("codigo") or "").strip()
    nombre = (data.get("nombre") or "").strip()
    tipo = (data.get("tipo") or "").strip()
    if not codigo or not nombre:
        return jsonify({"error": "Código y nombre son requeridos."}), 400
    if tipo not in ("activo", "pasivo", "patrimonio", "ingreso", "gasto"):
        return jsonify({"error": "Tipo debe ser activo, pasivo, patrimonio, ingreso o gasto."}), 400
    if CuentaContable.query.filter_by(account_id=current_account_id(), codigo=codigo, deleted_at=None).first():
        return jsonify({"error": f"El código '{codigo}' ya está en uso."}), 400

    padre_id = None
    if data.get("cuenta_padre_id"):
        padre = CuentaContable.query.filter_by(id=data["cuenta_padre_id"], account_id=current_account_id()).first()
        if not padre:
            return jsonify({"error": "Cuenta padre no encontrada."}), 400
        padre_id = padre.id

    c = CuentaContable(
        account_id=current_account_id(), codigo=codigo, nombre=nombre, tipo=tipo,
        cuenta_padre_id=padre_id, created_at=datetime.utcnow().strftime("%Y-%m-%d"),
    )
    db.session.add(c)
    db.session.commit()
    return jsonify(cuenta_contable_to_dict(c)), 201


@app.route("/api/cuentas-contables/<int:cuenta_id>", methods=["PUT"])
@login_required
def update_cuenta_contable(cuenta_id):
    c = CuentaContable.query.filter_by(id=cuenta_id, account_id=current_account_id()).first_or_404()
    data = request.json or {}
    new_codigo = (data.get("codigo", c.codigo) or "").strip()
    if new_codigo != c.codigo and CuentaContable.query.filter_by(account_id=current_account_id(), codigo=new_codigo, deleted_at=None).first():
        return jsonify({"error": f"El código '{new_codigo}' ya está en uso."}), 400
    c.codigo = new_codigo
    c.nombre = (data.get("nombre", c.nombre) or "").strip()
    if "tipo" in data:
        if data["tipo"] not in ("activo", "pasivo", "patrimonio", "ingreso", "gasto"):
            return jsonify({"error": "Tipo debe ser activo, pasivo, patrimonio, ingreso o gasto."}), 400
        c.tipo = data["tipo"]
    db.session.commit()
    return jsonify(cuenta_contable_to_dict(c))


@app.route("/api/cuentas-contables/<int:cuenta_id>", methods=["DELETE"])
@login_required
def delete_cuenta_contable(cuenta_id):
    c = CuentaContable.query.filter_by(id=cuenta_id, account_id=current_account_id(), deleted_at=None).first_or_404()
    if AsientoLinea.query.filter_by(cuenta_contable_id=c.id).first():
        return jsonify({"error": "No se puede eliminar: esta cuenta tiene movimientos contables registrados."}), 400
    c.deleted_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    db.session.commit()
    return "", 204


def asiento_to_dict(a, with_lineas=True):
    d = {
        "id": a.id, "fecha": a.fecha, "descripcion": a.descripcion,
        "origen_type": a.origen_type, "origen_id": a.origen_id, "created_at": a.created_at,
    }
    if with_lineas:
        d["lineas"] = [
            {
                "id": l.id, "cuenta_contable_id": l.cuenta_contable_id,
                "cuenta_codigo": l.cuenta.codigo if l.cuenta else None,
                "cuenta_nombre": l.cuenta.nombre if l.cuenta else None,
                "debe": l.debe, "haber": l.haber, "descripcion": l.descripcion,
            }
            for l in a.lineas
        ]
        d["total_debe"] = round(sum(l.debe or 0 for l in a.lineas), 2)
        d["total_haber"] = round(sum(l.haber or 0 for l in a.lineas), 2)
    return d


@app.route("/api/asientos", methods=["GET"])
@login_required
def list_asientos():
    """Libro Diario - every journal entry, optionally filtered by date range
    and/or origen_type."""
    q = AsientoContable.query.filter_by(account_id=current_account_id())
    desde = request.args.get("desde")
    hasta = request.args.get("hasta")
    origen_type = request.args.get("origen_type")
    if desde:
        q = q.filter(AsientoContable.fecha >= desde)
    if hasta:
        q = q.filter(AsientoContable.fecha <= hasta)
    if origen_type:
        q = q.filter(AsientoContable.origen_type == origen_type)
    asientos = q.order_by(AsientoContable.fecha.desc(), AsientoContable.id.desc()).all()
    return jsonify([asiento_to_dict(a) for a in asientos])


@app.route("/api/asientos/<int:asiento_id>", methods=["GET"])
@login_required
def get_asiento(asiento_id):
    a = AsientoContable.query.filter_by(id=asiento_id, account_id=current_account_id()).first_or_404()
    return jsonify(asiento_to_dict(a))


@app.route("/api/asientos", methods=["POST"])
@login_required
def create_asiento_manual():
    """Manual journal entry - e.g. an opening balance, a correction, or a
    bank fee that needs an asiento before it can be reconciled. Goes through
    the exact same crear_asiento() validation as every automatic posting."""
    data = request.json or {}
    descripcion = (data.get("descripcion") or "").strip()
    fecha = data.get("fecha") or datetime.utcnow().strftime("%Y-%m-%d")
    lineas = data.get("lineas")
    if not isinstance(lineas, list) or not lineas:
        return jsonify({"error": "Agrega al menos una línea al asiento."}), 400
    for l in lineas:
        if not l.get("cuenta_codigo"):
            return jsonify({"error": "Cada línea necesita una cuenta contable."}), 400
    try:
        asiento = crear_asiento(
            account_id=current_account_id(), fecha=fecha, descripcion=descripcion,
            origen_type="manual", origen_id=None, lineas=lineas,
        )
    except ValueError as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400
    return jsonify(asiento_to_dict(asiento)), 201


@app.route("/api/contabilidad/libro-mayor/<int:cuenta_id>", methods=["GET"])
@login_required
def libro_mayor(cuenta_id):
    """Every AsientoLinea for one cuenta contable, oldest first, with a
    running balance. Sign convention: activo/gasto accounts increase with
    debe (a debit grows what you own or spend); pasivo/patrimonio/ingreso
    accounts increase with haber (a credit grows what you owe, are worth, or
    earned). Getting this backwards is the most common way a ledger lies."""
    cuenta = CuentaContable.query.filter_by(id=cuenta_id, account_id=current_account_id()).first_or_404()
    q = (AsientoLinea.query.join(AsientoContable)
         .filter(AsientoContable.account_id == current_account_id(), AsientoLinea.cuenta_contable_id == cuenta.id))
    desde = request.args.get("desde")
    hasta = request.args.get("hasta")
    if desde:
        q = q.filter(AsientoContable.fecha >= desde)
    if hasta:
        q = q.filter(AsientoContable.fecha <= hasta)
    lineas = q.order_by(AsientoContable.fecha, AsientoContable.id, AsientoLinea.id).all()

    aumenta_con_debe = cuenta.tipo in ("activo", "gasto")
    balance = 0.0
    rows = []
    for l in lineas:
        delta = (l.debe or 0) - (l.haber or 0) if aumenta_con_debe else (l.haber or 0) - (l.debe or 0)
        balance = round(balance + delta, 2)
        rows.append({
            "asiento_id": l.asiento.id, "fecha": l.asiento.fecha, "descripcion": l.asiento.descripcion,
            "origen_type": l.asiento.origen_type, "origen_id": l.asiento.origen_id,
            "linea_descripcion": l.descripcion, "debe": l.debe, "haber": l.haber, "balance": balance,
        })
    return jsonify({
        "cuenta": cuenta_contable_to_dict(cuenta),
        "saldo_inicial": 0,
        "saldo_final": balance,
        "movimientos": rows,
    })


@app.route("/api/contabilidad/balanza-comprobacion", methods=["GET"])
@login_required
def balanza_comprobacion():
    """Trial balance: every cuenta with activity in range, its total debe,
    total haber, and net balance (signed per the same convention as
    libro_mayor) - plus the top-level balanced flag, which is the entire
    point of double-entry and must come out exact, not approximate."""
    q = (AsientoLinea.query.join(AsientoContable)
         .filter(AsientoContable.account_id == current_account_id()))
    desde = request.args.get("desde")
    hasta = request.args.get("hasta")
    if desde:
        q = q.filter(AsientoContable.fecha >= desde)
    if hasta:
        q = q.filter(AsientoContable.fecha <= hasta)
    lineas = q.all()

    por_cuenta = {}
    for l in lineas:
        cid = l.cuenta_contable_id
        if cid not in por_cuenta:
            por_cuenta[cid] = {"debe": 0.0, "haber": 0.0}
        por_cuenta[cid]["debe"] += l.debe or 0
        por_cuenta[cid]["haber"] += l.haber or 0

    cuentas_rows = []
    total_debe = 0.0
    total_haber = 0.0
    for cid, totales in por_cuenta.items():
        cuenta = CuentaContable.query.get(cid)
        debe = round(totales["debe"], 2)
        haber = round(totales["haber"], 2)
        aumenta_con_debe = cuenta.tipo in ("activo", "gasto")
        balance = round(debe - haber, 2) if aumenta_con_debe else round(haber - debe, 2)
        cuentas_rows.append({
            "cuenta_contable_id": cid, "codigo": cuenta.codigo, "nombre": cuenta.nombre, "tipo": cuenta.tipo,
            "debe": debe, "haber": haber, "balance": balance,
        })
        total_debe += debe
        total_haber += haber
    cuentas_rows.sort(key=lambda r: r["codigo"])

    total_debe = round(total_debe, 2)
    total_haber = round(total_haber, 2)
    return jsonify({
        "cuentas": cuentas_rows,
        "total_debe": total_debe,
        "total_haber": total_haber,
        "balanced": total_debe == total_haber,
    })


def compute_cuenta_balance_asof(account_id, cuenta, fecha_hasta):
    """One cuenta's balance using every AsientoLinea on an asiento dated on
    or before fecha_hasta - the same sign convention as libro_mayor and
    balanza_comprobacion (activo/gasto increase with debe; pasivo/patrimonio/
    ingreso increase with haber), reused here rather than redefined so
    Balance General and Flujo de Efectivo can never quietly disagree with
    Libro Mayor about what a cuenta's balance means."""
    q = (AsientoLinea.query.join(AsientoContable)
         .filter(AsientoContable.account_id == account_id,
                 AsientoLinea.cuenta_contable_id == cuenta.id,
                 AsientoContable.fecha <= fecha_hasta))
    total_debe = total_haber = 0.0
    for l in q.all():
        total_debe += l.debe or 0
        total_haber += l.haber or 0
    aumenta_con_debe = cuenta.tipo in ("activo", "gasto")
    balance = (total_debe - total_haber) if aumenta_con_debe else (total_haber - total_debe)
    return round(balance, 2)


@app.route("/api/contabilidad/balance-general", methods=["GET"])
@login_required
def balance_general():
    """Snapshot at a single date - Activo / Pasivo / Patrimonio.

    DESIGN DECISION (see task spec): this app has no year-end closing process
    - nothing ever zeros Ingreso/Gasto account balances into Utilidades
    Retenidas - so a naive sum of account balances will NOT balance: all the
    unclosed income/expense activity sitting in Ingreso/Gasto accounts isn't
    represented in Patrimonio at all. The fix is a plug figure, "Utilidad
    Acumulada (desde el inicio)" = sum(Ingreso balances) - sum(Gasto
    balances) AS OF this date, using ALL history since there's no fiscal-year
    boundary concept here - NOT a proper fiscal-year net income figure, and
    labeled as such everywhere it's shown so it's never mistaken for one."""
    account_id = current_account_id()
    ensure_chart_of_accounts(account_id)
    fecha = request.args.get("fecha") or datetime.utcnow().strftime("%Y-%m-%d")

    cuentas = CuentaContable.query.filter_by(account_id=account_id, deleted_at=None).order_by(CuentaContable.codigo).all()

    activo, pasivo, patrimonio = [], [], []
    total_ingresos = 0.0
    total_gastos = 0.0
    for cuenta in cuentas:
        balance = compute_cuenta_balance_asof(account_id, cuenta, fecha)
        row = {"cuenta_contable_id": cuenta.id, "codigo": cuenta.codigo, "nombre": cuenta.nombre, "balance": balance}
        if cuenta.tipo == "activo":
            activo.append(row)
        elif cuenta.tipo == "pasivo":
            pasivo.append(row)
        elif cuenta.tipo == "patrimonio":
            patrimonio.append(row)
        elif cuenta.tipo == "ingreso":
            total_ingresos += balance
        elif cuenta.tipo == "gasto":
            total_gastos += balance

    utilidad_acumulada = round(total_ingresos - total_gastos, 2)
    patrimonio.append({
        "cuenta_contable_id": None, "codigo": None,
        "nombre": "Utilidad Acumulada (desde el inicio)", "balance": utilidad_acumulada,
    })

    total_activo = round(sum(r["balance"] for r in activo), 2)
    total_pasivo = round(sum(r["balance"] for r in pasivo), 2)
    total_patrimonio = round(sum(r["balance"] for r in patrimonio), 2)

    return jsonify({
        "fecha": fecha,
        "activo": activo, "pasivo": pasivo, "patrimonio": patrimonio,
        "total_activo": total_activo, "total_pasivo": total_pasivo, "total_patrimonio": total_patrimonio,
        "balanced": total_activo == round(total_pasivo + total_patrimonio, 2),
    })


FLUJO_ORIGEN_LABELS = {
    "pago": "Cobros de Clientes",
    "gasto": "Pago de Gastos Operativos",
    "pago_proveedor": "Pago a Proveedores",
    "manual": "Asientos Manuales / Otros",
}
# factura/cuenta_por_pagar never debit or credit Caja y Bancos directly under
# Phase 2's posting rules (a factura moves Cuentas por Cobrar, a cuenta por
# pagar moves Cuentas por Pagar) - if one shows up here, something upstream
# is posting incorrectly, so it's labeled as a visible anomaly rather than
# folded quietly into another bucket.
FLUJO_ORIGEN_INESPERADO = {"factura", "cuenta_por_pagar"}


@app.route("/api/contabilidad/flujo-efectivo", methods=["GET"])
@login_required
def flujo_efectivo():
    """Estado de Flujo de Efectivo - Actividades de Operación only, direct
    method (grouped by origen_type). Investing/Financing are NOT fabricated:
    this app tracks no fixed assets, loans, or capital contributions, so
    those sections come back as explicitly not_implemented rather than
    guessed-at numbers."""
    account_id = current_account_id()
    ensure_chart_of_accounts(account_id)
    hoy = datetime.utcnow().strftime("%Y-%m-%d")
    desde = request.args.get("desde") or hoy
    hasta = request.args.get("hasta") or hoy

    caja = CuentaContable.query.filter_by(account_id=account_id, codigo="1010", deleted_at=None).first_or_404()

    dia_anterior = (datetime.strptime(desde, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    saldo_inicial = compute_cuenta_balance_asof(account_id, caja, dia_anterior)

    lineas = (AsientoLinea.query.join(AsientoContable)
              .filter(AsientoContable.account_id == account_id, AsientoLinea.cuenta_contable_id == caja.id,
                      AsientoContable.fecha >= desde, AsientoContable.fecha <= hasta).all())

    por_origen = {}
    inesperados = []
    for l in lineas:
        origen = l.asiento.origen_type or "manual"
        # Caja is an activo account: a debit is a real cash inflow, a credit a real outflow.
        monto = (l.debe or 0) - (l.haber or 0)
        por_origen[origen] = round(por_origen.get(origen, 0) + monto, 2)
        if origen in FLUJO_ORIGEN_INESPERADO:
            inesperados.append({"asiento_id": l.asiento.id, "origen_type": origen, "fecha": l.asiento.fecha})

    def label_for(origen):
        if origen in FLUJO_ORIGEN_INESPERADO:
            return f"⚠ Origen inesperado ({origen}) - revisar posting"
        return FLUJO_ORIGEN_LABELS.get(origen, origen)

    actividades_operacion = [
        {"origen_type": origen, "label": label_for(origen), "monto": monto}
        for origen, monto in sorted(por_origen.items())
    ]
    neto_operacion = round(sum(g["monto"] for g in actividades_operacion), 2)
    saldo_final = round(saldo_inicial + neto_operacion, 2)

    # Integrity check: this computed saldo_final must equal Caja's actual
    # ledger balance as of `hasta`, independently recomputed - if it doesn't,
    # that's a real discrepancy in either this report or the ledger itself.
    saldo_final_ledger = compute_cuenta_balance_asof(account_id, caja, hasta)

    result = {
        "desde": desde, "hasta": hasta,
        "saldo_inicial": saldo_inicial,
        "actividades_operacion": actividades_operacion,
        "neto_operacion": neto_operacion,
        "saldo_final": saldo_final,
        "saldo_final_ledger": saldo_final_ledger,
        "reconciles": saldo_final == saldo_final_ledger,
        "actividades_inversion": {"items": [], "not_implemented": True},
        "actividades_financiamiento": {"items": [], "not_implemented": True},
    }
    if inesperados:
        result["advertencia"] = f"{len(inesperados)} movimiento(s) de Caja con origen inesperado (factura/cuenta_por_pagar) - revisar el posting."
        result["movimientos_inesperados"] = inesperados
    return jsonify(result)


# ---------------------------------------------------------------------------
# Contabilidad - Gastos (operating expenses)
# ---------------------------------------------------------------------------

def _gasto_to_dict(g):
    return {
        "id": g.id,
        "fecha": g.fecha,
        "numero_factura": g.numero_factura,
        "categoria": g.categoria,
        "descripcion": g.descripcion,
        "proveedor": g.proveedor,
        "subtotal": g.subtotal,
        "descuento": g.descuento,
        "isv": g.isv,
        "monto": g.monto,
        "created_at": g.created_at,
        "updated_at": g.updated_at,
        "items": [
            {
                "id": it.id,
                "descripcion": it.descripcion,
                "cantidad": it.cantidad,
                "precio_unitario": it.precio_unitario,
                "descuento": it.descuento,
                "isv_pct": it.isv_pct,
                "subtotal": round(it.cantidad * it.precio_unitario, 2),
            }
            for it in g.items
        ],
    }


def _parse_gasto_items(raw_items):
    """Validate+normalize the incoming line items and return (items, totals, error),
    where each item carries its own descuento/isv_pct (real invoices can mix
    taxed/untaxed or discounted/full-price lines) and totals aggregates them
    for the header row: {subtotal, descuento, isv, monto}."""
    if not isinstance(raw_items, list) or not raw_items:
        return None, None, "Agrega al menos una línea de detalle."
    parsed = []
    subtotal = descuento_total = isv_total = 0.0
    for raw in raw_items:
        descripcion = (raw.get("descripcion") or "").strip()
        if not descripcion:
            return None, None, "Cada línea necesita una descripción."
        try:
            cantidad = float(raw.get("cantidad", 0) or 0)
            precio_unitario = float(raw.get("precio_unitario", 0) or 0)
            descuento = float(raw.get("descuento", 0) or 0)
            isv_pct = float(raw.get("isv_pct", 0) or 0)
        except (TypeError, ValueError):
            return None, None, "Cantidad, precio, descuento e ISV deben ser números."
        if cantidad <= 0:
            return None, None, "La cantidad debe ser mayor a cero."
        if precio_unitario < 0:
            return None, None, "El precio unitario no puede ser negativo."
        line_subtotal = cantidad * precio_unitario
        if descuento < 0:
            return None, None, "El descuento no puede ser negativo."
        if descuento > line_subtotal:
            return None, None, "El descuento de una línea no puede ser mayor a su subtotal."
        line_isv = round((line_subtotal - descuento) * isv_pct / 100, 2)
        parsed.append({
            "descripcion": descripcion, "cantidad": cantidad, "precio_unitario": precio_unitario,
            "descuento": descuento, "isv_pct": isv_pct,
        })
        subtotal += line_subtotal
        descuento_total += descuento
        isv_total += line_isv
    subtotal = round(subtotal, 2)
    descuento_total = round(descuento_total, 2)
    isv_total = round(isv_total, 2)
    monto = round(subtotal - descuento_total + isv_total, 2)
    return parsed, {"subtotal": subtotal, "descuento": descuento_total, "isv": isv_total, "monto": monto}, None


@app.route("/api/gastos/categorias", methods=["GET"])
@login_required
def list_gasto_categorias():
    return jsonify(GASTO_CATEGORIAS)


@app.route("/api/gastos", methods=["GET"])
@login_required
def list_gastos():
    q = GastoOperativo.query.filter_by(account_id=current_account_id(), deleted_at=None)
    desde = request.args.get("desde")
    hasta = request.args.get("hasta")
    if desde:
        q = q.filter(GastoOperativo.fecha >= desde)
    if hasta:
        q = q.filter(GastoOperativo.fecha <= hasta)
    gastos = q.order_by(GastoOperativo.fecha.desc(), GastoOperativo.id.desc()).all()
    return jsonify([_gasto_to_dict(g) for g in gastos])


@app.route("/api/gastos/summary", methods=["GET"])
@login_required
def gastos_summary():
    """Total and per-category breakdown, honoring the same desde/hasta
    filters as the list endpoint - the list and its total should always
    agree on what date range they're describing."""
    q = GastoOperativo.query.filter_by(account_id=current_account_id(), deleted_at=None)
    desde = request.args.get("desde")
    hasta = request.args.get("hasta")
    if desde:
        q = q.filter(GastoOperativo.fecha >= desde)
    if hasta:
        q = q.filter(GastoOperativo.fecha <= hasta)
    gastos = q.all()
    total = round(sum(g.monto or 0 for g in gastos), 2)
    por_categoria = {}
    for g in gastos:
        por_categoria[g.categoria] = round(por_categoria.get(g.categoria, 0) + (g.monto or 0), 2)
    return jsonify({"total": total, "por_categoria": por_categoria, "count": len(gastos)})


@app.route("/api/gastos/trash", methods=["GET"])
@login_required
def list_gastos_trash():
    gastos = (GastoOperativo.query.filter(GastoOperativo.account_id == current_account_id(),
                                           GastoOperativo.deleted_at.isnot(None))
              .order_by(GastoOperativo.deleted_at.desc()).all())
    return jsonify([_gasto_to_dict(g) for g in gastos])


@app.route("/api/gastos/<int:gasto_id>", methods=["GET"])
@login_required
def get_gasto(gasto_id):
    g = GastoOperativo.query.filter_by(id=gasto_id, account_id=current_account_id()).first_or_404()
    return jsonify(_gasto_to_dict(g))


@app.route("/api/gastos", methods=["POST"])
@login_required
def create_gasto():
    data = request.json or {}
    descripcion = (data.get("descripcion") or "").strip()
    if not descripcion:
        return jsonify({"error": "La descripción es requerida."}), 400

    items, totals, err = _parse_gasto_items(data.get("items"))
    if err:
        return jsonify({"error": err}), 400

    now = datetime.utcnow().strftime("%Y-%m-%d")
    g = GastoOperativo(
        account_id=current_account_id(),
        fecha=data.get("fecha") or now,
        numero_factura=(data.get("numero_factura") or "").strip(),
        categoria=data.get("categoria") or "Otros",
        descripcion=descripcion,
        proveedor=(data.get("proveedor") or "").strip(),
        subtotal=totals["subtotal"],
        descuento=totals["descuento"],
        isv=totals["isv"],
        monto=totals["monto"],
        created_at=now,
        updated_at=now,
    )
    g.items = [GastoOperativoItem(**it) for it in items]
    db.session.add(g)
    db.session.flush()  # get g.id for posting, commit happens with the asiento below

    try:
        post_gasto_asiento(g)
    except ValueError as e:
        db.session.rollback()
        return jsonify({"error": f"No se pudo registrar el asiento contable: {e}"}), 400

    return jsonify(_gasto_to_dict(g)), 201


@app.route("/api/gastos/<int:gasto_id>", methods=["PUT"])
@login_required
def update_gasto(gasto_id):
    g = GastoOperativo.query.filter_by(id=gasto_id, account_id=current_account_id()).first_or_404()
    data = request.json or {}

    if "descripcion" in data:
        descripcion = (data.get("descripcion") or "").strip()
        if not descripcion:
            return jsonify({"error": "La descripción es requerida."}), 400
        g.descripcion = descripcion

    if "items" in data:
        items, totals, err = _parse_gasto_items(data.get("items"))
        if err:
            return jsonify({"error": err}), 400
        g.items = [GastoOperativoItem(**it) for it in items]
        g.subtotal = totals["subtotal"]
        g.descuento = totals["descuento"]
        g.isv = totals["isv"]
        g.monto = totals["monto"]

    g.fecha = data.get("fecha", g.fecha)
    g.numero_factura = (data.get("numero_factura", g.numero_factura) or "").strip()
    g.categoria = data.get("categoria", g.categoria)
    g.proveedor = (data.get("proveedor", g.proveedor) or "").strip()
    g.updated_at = datetime.utcnow().strftime("%Y-%m-%d")

    db.session.commit()
    return jsonify(_gasto_to_dict(g))


@app.route("/api/gastos/<int:gasto_id>", methods=["DELETE"])
@login_required
def delete_gasto(gasto_id):
    g = GastoOperativo.query.filter_by(id=gasto_id, account_id=current_account_id(), deleted_at=None).first_or_404()
    g.deleted_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    db.session.commit()
    return "", 204


@app.route("/api/gastos/<int:gasto_id>/restore", methods=["POST"])
@login_required
def restore_gasto(gasto_id):
    g = GastoOperativo.query.filter(GastoOperativo.id == gasto_id, GastoOperativo.account_id == current_account_id(),
                                     GastoOperativo.deleted_at.isnot(None)).first_or_404()
    g.deleted_at = None
    db.session.commit()
    return jsonify(_gasto_to_dict(g))


@app.route("/api/gastos/<int:gasto_id>/permanent", methods=["DELETE"])
@login_required
def permanent_delete_gasto(gasto_id):
    g = GastoOperativo.query.filter(GastoOperativo.id == gasto_id, GastoOperativo.account_id == current_account_id(),
                                     GastoOperativo.deleted_at.isnot(None)).first_or_404()
    db.session.delete(g)
    db.session.commit()
    return "", 204


# ---------------------------------------------------------------------------
# Contabilidad - Ingresos, Cuentas por Cobrar, Estado de Resultados
# ---------------------------------------------------------------------------

@app.route("/api/contabilidad/ingresos", methods=["GET"])
@login_required
def contabilidad_ingresos():
    """Total facturado (pre-tax revenue) and ISV collected, for a date range.
    ISV is kept separate on purpose - it's a liability the business collects
    on behalf of SAR, not income, so it must never be folded into revenue."""
    q = Invoice.query.filter_by(account_id=current_account_id(), deleted_at=None)
    desde = request.args.get("desde")
    hasta = request.args.get("hasta")
    if desde:
        q = q.filter(Invoice.fecha >= desde)
    if hasta:
        q = q.filter(Invoice.fecha <= hasta)
    totals = [compute_invoice_totals(i) for i in q.all()]
    total_facturado = round(sum(t["subtotal"] for t in totals), 2)
    isv_collected = round(sum(t["isv_15"] + t["isv_18"] for t in totals), 2)
    return jsonify({"total_facturado": total_facturado, "isv_collected": isv_collected, "count": len(totals)})


def _compute_cuentas_por_cobrar(account_id):
    """Every non-deleted invoice with an outstanding balance (saldo > 0),
    bucketed by days since `fecha` (issue date). Factored out of its route
    so /api/panel/resumen can call it directly (an internal function call,
    not an HTTP round-trip to this same app) instead of reimplementing it.

    SIMPLIFICATION: Invoice has no due-date field yet - only `fecha` and
    termino_pago, no dias_credito/fecha_vencimiento - so this buckets against
    the issue date, not a formal due date. A future pass could add a real
    due-date field if that distinction becomes necessary; out of scope here."""
    invoices = Invoice.query.filter_by(account_id=account_id, deleted_at=None).all()
    hoy = datetime.utcnow().date()
    result = []
    for inv in invoices:
        t = compute_invoice_totals(inv)
        if t["saldo"] <= 0.01:
            continue
        try:
            dias_transcurridos = (hoy - datetime.strptime(inv.fecha, "%Y-%m-%d").date()).days
        except (TypeError, ValueError):
            dias_transcurridos = 0
        if dias_transcurridos <= 30:
            bucket = "0-30"
        elif dias_transcurridos <= 60:
            bucket = "31-60"
        else:
            bucket = "60+"
        result.append({
            "id": inv.id,
            "numero": inv.numero,
            "cliente_nombre": inv.cliente_nombre,
            "fecha": inv.fecha,
            "total_a_pagar": t["total_a_pagar"],
            "total_pagado": t["total_pagado"],
            "saldo": t["saldo"],
            "dias_transcurridos": dias_transcurridos,
            "bucket": bucket,
        })
    result.sort(key=lambda r: r["dias_transcurridos"], reverse=True)
    return result


@app.route("/api/contabilidad/cuentas-por-cobrar", methods=["GET"])
@login_required
def contabilidad_cuentas_por_cobrar():
    return jsonify(_compute_cuentas_por_cobrar(current_account_id()))


def _compute_estado_resultados(account_id, desde, hasta):
    """Basic P&L for a date range: Ingresos (pre-tax) - Gastos = Utilidad.
    Factored out so /api/panel/resumen can reuse it for "mes_actual" without
    duplicating the query logic."""
    inv_q = Invoice.query.filter_by(account_id=account_id, deleted_at=None)
    if desde:
        inv_q = inv_q.filter(Invoice.fecha >= desde)
    if hasta:
        inv_q = inv_q.filter(Invoice.fecha <= hasta)
    ingresos = round(sum(compute_invoice_totals(i)["subtotal"] for i in inv_q.all()), 2)

    gasto_q = GastoOperativo.query.filter_by(account_id=account_id, deleted_at=None)
    if desde:
        gasto_q = gasto_q.filter(GastoOperativo.fecha >= desde)
    if hasta:
        gasto_q = gasto_q.filter(GastoOperativo.fecha <= hasta)
    gastos = round(sum(g.monto or 0 for g in gasto_q.all()), 2)

    return {"ingresos": ingresos, "gastos": gastos, "utilidad": round(ingresos - gastos, 2)}


@app.route("/api/contabilidad/estado-resultados", methods=["GET"])
@login_required
def contabilidad_estado_resultados():
    desde = request.args.get("desde")
    hasta = request.args.get("hasta")
    return jsonify(_compute_estado_resultados(current_account_id(), desde, hasta))


# ---------------------------------------------------------------------------
# Panel - dashboard summary. One aggregating call across Facturación,
# Contabilidad, and Inventario so the Panel page makes a single request
# instead of several in parallel on every load. Pure read-only reporting -
# reuses the exact same computations the underlying endpoints use (via
# direct Python function calls, never an HTTP round-trip to this same app),
# so it can never quietly disagree with what those endpoints themselves show.
# ---------------------------------------------------------------------------

@app.route("/api/panel/resumen", methods=["GET"])
@login_required
def panel_resumen():
    account_id = current_account_id()

    cxc = _compute_cuentas_por_cobrar(account_id)
    total_pendiente = round(sum(r["saldo"] for r in cxc), 2)
    vencidas_60_mas = [r for r in cxc if r["bucket"] == "60+"]

    inventario = _compute_inventario_list(account_id)
    materiales_bajo_stock = sum(1 for m in inventario if m["bajo_stock"])
    valor_total_inventario = round(sum(m["valor_reposicion"] for m in inventario), 2)

    # "Current month" computed from the server's date the same way the rest
    # of this app already defaults fecha fields (datetime.utcnow()).
    hoy = datetime.utcnow()
    primer_dia_mes = hoy.strftime("%Y-%m-01")
    hoy_str = hoy.strftime("%Y-%m-%d")
    mes_actual = _compute_estado_resultados(account_id, primer_dia_mes, hoy_str)

    return jsonify({
        "cuentas_por_cobrar": {
            "total_pendiente": total_pendiente,
            "vencidas_60_mas": len(vencidas_60_mas),
            "vencidas_60_mas_total": round(sum(r["saldo"] for r in vencidas_60_mas), 2),
        },
        "inventario": {
            "materiales_bajo_stock": materiales_bajo_stock,
            "valor_total": valor_total_inventario,
        },
        "mes_actual": mes_actual,
    })


# ---------------------------------------------------------------------------
# Contabilidad - Cuentas por Pagar (vendor bills) + Pagos a Proveedores.
# Mirrors GastoOperativo's CRUD depth and Phase 1's Pago overpayment logic,
# but posts to Cuentas por Pagar instead of paying cash immediately.
# ---------------------------------------------------------------------------

def compute_cxp_pagado(cuenta_por_pagar_id):
    total = db.session.query(db.func.sum(PagoProveedor.monto)).filter(
        PagoProveedor.cuenta_por_pagar_id == cuenta_por_pagar_id).scalar()
    return round(total or 0, 2)


def cuenta_por_pagar_to_dict(c):
    total_pagado = compute_cxp_pagado(c.id)
    return {
        "id": c.id, "proveedor": c.proveedor, "categoria": c.categoria, "descripcion": c.descripcion,
        "fecha_emision": c.fecha_emision, "fecha_vencimiento": c.fecha_vencimiento, "monto": c.monto,
        "total_pagado": total_pagado, "saldo": round(c.monto - total_pagado, 2),
        "created_at": c.created_at, "updated_at": c.updated_at,
    }


@app.route("/api/cuentas-por-pagar", methods=["GET"])
@login_required
def list_cuentas_por_pagar():
    q = CuentaPorPagar.query.filter_by(account_id=current_account_id(), deleted_at=None)
    desde = request.args.get("desde")
    hasta = request.args.get("hasta")
    if desde:
        q = q.filter(CuentaPorPagar.fecha_emision >= desde)
    if hasta:
        q = q.filter(CuentaPorPagar.fecha_emision <= hasta)
    cuentas = q.order_by(CuentaPorPagar.fecha_emision.desc(), CuentaPorPagar.id.desc()).all()
    return jsonify([cuenta_por_pagar_to_dict(c) for c in cuentas])


@app.route("/api/cuentas-por-pagar/trash", methods=["GET"])
@login_required
def list_cuentas_por_pagar_trash():
    cuentas = (CuentaPorPagar.query.filter(CuentaPorPagar.account_id == current_account_id(),
                                            CuentaPorPagar.deleted_at.isnot(None))
               .order_by(CuentaPorPagar.deleted_at.desc()).all())
    return jsonify([cuenta_por_pagar_to_dict(c) for c in cuentas])


@app.route("/api/cuentas-por-pagar/<int:cxp_id>", methods=["GET"])
@login_required
def get_cuenta_por_pagar(cxp_id):
    c = CuentaPorPagar.query.filter_by(id=cxp_id, account_id=current_account_id()).first_or_404()
    return jsonify(cuenta_por_pagar_to_dict(c))


@app.route("/api/cuentas-por-pagar", methods=["POST"])
@login_required
def create_cuenta_por_pagar():
    data = request.json or {}
    proveedor = (data.get("proveedor") or "").strip()
    descripcion = (data.get("descripcion") or "").strip()
    if not proveedor:
        return jsonify({"error": "El proveedor es requerido."}), 400
    if not descripcion:
        return jsonify({"error": "La descripción es requerida."}), 400
    try:
        monto = float(data.get("monto", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "El monto debe ser un número."}), 400
    if monto <= 0:
        return jsonify({"error": "El monto debe ser mayor a cero."}), 400

    now = datetime.utcnow().strftime("%Y-%m-%d")
    c = CuentaPorPagar(
        account_id=current_account_id(),
        proveedor=proveedor,
        categoria=data.get("categoria") or "Otros",
        descripcion=descripcion,
        fecha_emision=data.get("fecha_emision") or now,
        fecha_vencimiento=(data.get("fecha_vencimiento") or "").strip() or None,
        monto=monto,
        created_at=now,
        updated_at=now,
    )
    db.session.add(c)
    db.session.flush()  # get c.id for posting, commit happens with the asiento below

    try:
        post_cuenta_por_pagar_asiento(c)
    except ValueError as e:
        db.session.rollback()
        return jsonify({"error": f"No se pudo registrar el asiento contable: {e}"}), 400

    return jsonify(cuenta_por_pagar_to_dict(c)), 201


@app.route("/api/cuentas-por-pagar/<int:cxp_id>", methods=["PUT"])
@login_required
def update_cuenta_por_pagar(cxp_id):
    c = CuentaPorPagar.query.filter_by(id=cxp_id, account_id=current_account_id()).first_or_404()
    data = request.json or {}
    if "proveedor" in data:
        proveedor = (data.get("proveedor") or "").strip()
        if not proveedor:
            return jsonify({"error": "El proveedor es requerido."}), 400
        c.proveedor = proveedor
    if "descripcion" in data:
        descripcion = (data.get("descripcion") or "").strip()
        if not descripcion:
            return jsonify({"error": "La descripción es requerida."}), 400
        c.descripcion = descripcion
    c.categoria = data.get("categoria", c.categoria)
    c.fecha_emision = data.get("fecha_emision", c.fecha_emision)
    c.fecha_vencimiento = data.get("fecha_vencimiento", c.fecha_vencimiento)
    # monto is intentionally NOT editable once created - it's already posted
    # to the ledger; changing it here would leave the asiento out of sync.
    c.updated_at = datetime.utcnow().strftime("%Y-%m-%d")
    db.session.commit()
    return jsonify(cuenta_por_pagar_to_dict(c))


@app.route("/api/cuentas-por-pagar/<int:cxp_id>", methods=["DELETE"])
@login_required
def delete_cuenta_por_pagar(cxp_id):
    c = CuentaPorPagar.query.filter_by(id=cxp_id, account_id=current_account_id(), deleted_at=None).first_or_404()
    c.deleted_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    db.session.commit()
    return "", 204


@app.route("/api/cuentas-por-pagar/<int:cxp_id>/restore", methods=["POST"])
@login_required
def restore_cuenta_por_pagar(cxp_id):
    c = CuentaPorPagar.query.filter(CuentaPorPagar.id == cxp_id, CuentaPorPagar.account_id == current_account_id(),
                                     CuentaPorPagar.deleted_at.isnot(None)).first_or_404()
    c.deleted_at = None
    db.session.commit()
    return jsonify(cuenta_por_pagar_to_dict(c))


@app.route("/api/cuentas-por-pagar/<int:cxp_id>/permanent", methods=["DELETE"])
@login_required
def permanent_delete_cuenta_por_pagar(cxp_id):
    c = CuentaPorPagar.query.filter(CuentaPorPagar.id == cxp_id, CuentaPorPagar.account_id == current_account_id(),
                                     CuentaPorPagar.deleted_at.isnot(None)).first_or_404()
    db.session.delete(c)
    db.session.commit()
    return "", 204


def pago_proveedor_to_dict(p):
    return {
        "id": p.id, "cuenta_por_pagar_id": p.cuenta_por_pagar_id, "monto": p.monto,
        "fecha": p.fecha, "metodo": p.metodo, "referencia": p.referencia, "created_at": p.created_at,
    }


@app.route("/api/cuentas-por-pagar/<int:cxp_id>/pagos", methods=["GET"])
@login_required
def list_pagos_proveedor(cxp_id):
    c = CuentaPorPagar.query.filter_by(id=cxp_id, account_id=current_account_id()).first_or_404()
    pagos = PagoProveedor.query.filter_by(cuenta_por_pagar_id=c.id).order_by(PagoProveedor.fecha.desc(), PagoProveedor.id.desc()).all()
    return jsonify([pago_proveedor_to_dict(p) for p in pagos])


@app.route("/api/cuentas-por-pagar/<int:cxp_id>/pagos", methods=["POST"])
@login_required
def create_pago_proveedor(cxp_id):
    c = CuentaPorPagar.query.filter_by(id=cxp_id, account_id=current_account_id()).first_or_404()
    data = request.json or {}
    try:
        monto = float(data.get("monto", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "El monto debe ser un número."}), 400
    if monto <= 0:
        return jsonify({"error": "El monto debe ser mayor a cero."}), 400

    ya_pagado = compute_cxp_pagado(c.id)
    if ya_pagado + monto > c.monto + 0.01:
        saldo_pendiente = round(c.monto - ya_pagado, 2)
        return jsonify({"error": f"Este pago excede el saldo pendiente de la cuenta (L. {saldo_pendiente:.2f})."}), 400

    now = datetime.utcnow().strftime("%Y-%m-%d")
    p = PagoProveedor(
        account_id=current_account_id(),
        cuenta_por_pagar_id=c.id,
        monto=monto,
        fecha=data.get("fecha") or now,
        metodo=(data.get("metodo") or "").strip(),
        referencia=(data.get("referencia") or "").strip(),
        created_at=now,
    )
    db.session.add(p)
    db.session.flush()  # get p.id for posting, commit happens with the asiento below

    try:
        post_pago_proveedor_asiento(p, c)
    except ValueError as e:
        db.session.rollback()
        return jsonify({"error": f"No se pudo registrar el asiento contable: {e}"}), 400

    return jsonify(pago_proveedor_to_dict(p)), 201


@app.route("/api/pagos-proveedor/<int:pago_id>", methods=["DELETE"])
@login_required
def delete_pago_proveedor(pago_id):
    p = PagoProveedor.query.filter_by(id=pago_id, account_id=current_account_id()).first_or_404()
    db.session.delete(p)
    db.session.commit()
    return "", 204


# ---------------------------------------------------------------------------
# Conciliación Bancaria - bank statement lines entered manually, matched by
# hand against ledger asientos (no bank-feed import, no fuzzy auto-matching).
# A bank line does not have to match an asiento to be marked conciliado -
# some lines (fees, interest) may need a manual asiento created first via
# POST /api/asientos, then matched here for traceability.
# ---------------------------------------------------------------------------

def movimiento_bancario_to_dict(m):
    return {
        "id": m.id, "fecha": m.fecha, "descripcion": m.descripcion, "tipo": m.tipo, "monto": m.monto,
        "referencia": m.referencia, "conciliado": m.conciliado, "asiento_id": m.asiento_id,
        "created_at": m.created_at,
    }


@app.route("/api/movimientos-bancarios", methods=["GET"])
@login_required
def list_movimientos_bancarios():
    q = MovimientoBancario.query.filter_by(account_id=current_account_id())
    desde = request.args.get("desde")
    hasta = request.args.get("hasta")
    conciliado = request.args.get("conciliado")
    if desde:
        q = q.filter(MovimientoBancario.fecha >= desde)
    if hasta:
        q = q.filter(MovimientoBancario.fecha <= hasta)
    if conciliado is not None:
        q = q.filter(MovimientoBancario.conciliado == (conciliado.lower() in ("1", "true", "si")))
    movimientos = q.order_by(MovimientoBancario.fecha.desc(), MovimientoBancario.id.desc()).all()
    return jsonify([movimiento_bancario_to_dict(m) for m in movimientos])


@app.route("/api/movimientos-bancarios", methods=["POST"])
@login_required
def create_movimiento_bancario():
    data = request.json or {}
    descripcion = (data.get("descripcion") or "").strip()
    tipo = (data.get("tipo") or "").strip()
    if not descripcion:
        return jsonify({"error": "La descripción es requerida."}), 400
    if tipo not in ("cargo", "abono"):
        return jsonify({"error": "El tipo debe ser cargo o abono."}), 400
    try:
        monto = float(data.get("monto", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "El monto debe ser un número."}), 400
    if monto <= 0:
        return jsonify({"error": "El monto debe ser mayor a cero."}), 400

    now = datetime.utcnow().strftime("%Y-%m-%d")
    m = MovimientoBancario(
        account_id=current_account_id(),
        fecha=data.get("fecha") or now,
        descripcion=descripcion,
        tipo=tipo,
        monto=monto,
        referencia=(data.get("referencia") or "").strip(),
        conciliado=False,
        created_at=now,
    )
    db.session.add(m)
    db.session.commit()
    return jsonify(movimiento_bancario_to_dict(m)), 201


@app.route("/api/movimientos-bancarios/<int:mov_id>/conciliar", methods=["POST"])
@login_required
def conciliar_movimiento_bancario(mov_id):
    """Marks a bank line as matched - manually, by a human picking the
    corresponding asiento (or none). Never auto-matches by amount/date."""
    m = MovimientoBancario.query.filter_by(id=mov_id, account_id=current_account_id()).first_or_404()
    data = request.json or {}
    asiento_id = data.get("asiento_id")
    if asiento_id:
        asiento = AsientoContable.query.filter_by(id=asiento_id, account_id=current_account_id()).first()
        if not asiento:
            return jsonify({"error": "Asiento contable no encontrado."}), 400
        m.asiento_id = asiento.id
    m.conciliado = True
    db.session.commit()
    return jsonify(movimiento_bancario_to_dict(m))


@app.route("/api/movimientos-bancarios/<int:mov_id>/desconciliar", methods=["POST"])
@login_required
def desconciliar_movimiento_bancario(mov_id):
    m = MovimientoBancario.query.filter_by(id=mov_id, account_id=current_account_id()).first_or_404()
    m.conciliado = False
    m.asiento_id = None
    db.session.commit()
    return jsonify(movimiento_bancario_to_dict(m))


@app.route("/api/movimientos-bancarios/<int:mov_id>", methods=["DELETE"])
@login_required
def delete_movimiento_bancario(mov_id):
    m = MovimientoBancario.query.filter_by(id=mov_id, account_id=current_account_id()).first_or_404()
    db.session.delete(m)
    db.session.commit()
    return "", 204


# ---------------------------------------------------------------------------
# Activos Fijos (fixed assets) - straight-line depreciation only. No
# disposal/sale flow in this phase - see ActivoFijo's docstring.
# ---------------------------------------------------------------------------

def compute_depreciacion_acumulada(activo_fijo_id):
    """Always summed from this asset's OWN DepreciacionRegistro rows - never
    by trying to split the shared Depreciación Acumulada ledger account back
    out per-asset (that account only knows the total across all assets)."""
    total = db.session.query(db.func.sum(DepreciacionRegistro.monto)).filter(
        DepreciacionRegistro.activo_fijo_id == activo_fijo_id).scalar()
    return round(total or 0, 2)


def activo_fijo_to_dict(a):
    depreciacion_acumulada = compute_depreciacion_acumulada(a.id)
    return {
        "id": a.id, "nombre": a.nombre, "descripcion": a.descripcion,
        "fecha_adquisicion": a.fecha_adquisicion, "costo_adquisicion": a.costo_adquisicion,
        "valor_residual": a.valor_residual, "vida_util_anos": a.vida_util_anos,
        "depreciacion_mensual": round((a.costo_adquisicion - a.valor_residual) / (a.vida_util_anos * 12), 2),
        "depreciacion_acumulada": depreciacion_acumulada,
        "valor_en_libros": round(a.costo_adquisicion - depreciacion_acumulada, 2),
        "created_at": a.created_at,
    }


@app.route("/api/activos-fijos", methods=["GET"])
@login_required
def list_activos_fijos():
    activos = (ActivoFijo.query.filter_by(account_id=current_account_id(), deleted_at=None)
               .order_by(ActivoFijo.fecha_adquisicion.desc(), ActivoFijo.id.desc()).all())
    return jsonify([activo_fijo_to_dict(a) for a in activos])


@app.route("/api/activos-fijos/<int:activo_id>", methods=["GET"])
@login_required
def get_activo_fijo(activo_id):
    a = ActivoFijo.query.filter_by(id=activo_id, account_id=current_account_id()).first_or_404()
    return jsonify(activo_fijo_to_dict(a))


@app.route("/api/activos-fijos", methods=["POST"])
@login_required
def create_activo_fijo():
    data = request.json or {}
    nombre = (data.get("nombre") or "").strip()
    if not nombre:
        return jsonify({"error": "El nombre es requerido."}), 400
    try:
        costo_adquisicion = float(data.get("costo_adquisicion", 0) or 0)
        valor_residual = float(data.get("valor_residual", 0) or 0)
        vida_util_anos = int(data.get("vida_util_anos", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "Costo, valor residual y vida útil deben ser números."}), 400
    if costo_adquisicion <= 0:
        return jsonify({"error": "El costo de adquisición debe ser mayor a cero."}), 400
    if valor_residual < 0:
        return jsonify({"error": "El valor residual no puede ser negativo."}), 400
    if valor_residual >= costo_adquisicion:
        return jsonify({"error": "El valor residual debe ser menor al costo de adquisición."}), 400
    if vida_util_anos <= 0:
        return jsonify({"error": "La vida útil debe ser mayor a cero años."}), 400

    now = datetime.utcnow().strftime("%Y-%m-%d")
    activo = ActivoFijo(
        account_id=current_account_id(),
        nombre=nombre,
        descripcion=(data.get("descripcion") or "").strip(),
        fecha_adquisicion=data.get("fecha_adquisicion") or now,
        costo_adquisicion=costo_adquisicion,
        valor_residual=valor_residual,
        vida_util_anos=vida_util_anos,
        created_at=now,
    )
    db.session.add(activo)
    db.session.flush()  # get activo.id for posting, commit happens with the asiento below

    try:
        post_activo_fijo_asiento(activo)
    except ValueError as e:
        db.session.rollback()
        return jsonify({"error": f"No se pudo registrar el asiento contable: {e}"}), 400

    return jsonify(activo_fijo_to_dict(activo)), 201


@app.route("/api/activos-fijos/<int:activo_id>", methods=["PUT"])
@login_required
def update_activo_fijo(activo_id):
    a = ActivoFijo.query.filter_by(id=activo_id, account_id=current_account_id()).first_or_404()
    data = request.json or {}
    if "nombre" in data:
        nombre = (data.get("nombre") or "").strip()
        if not nombre:
            return jsonify({"error": "El nombre es requerido."}), 400
        a.nombre = nombre
    a.descripcion = (data.get("descripcion", a.descripcion) or "").strip()
    # costo_adquisicion, valor_residual, vida_util_anos, fecha_adquisicion are
    # intentionally NOT editable once created - they're already posted to the
    # ledger and used by any depreciación already run; changing them here
    # would leave past asientos/registros out of sync with no way to reconcile.
    db.session.commit()
    return jsonify(activo_fijo_to_dict(a))


@app.route("/api/activos-fijos/<int:activo_id>", methods=["DELETE"])
@login_required
def delete_activo_fijo(activo_id):
    a = ActivoFijo.query.filter_by(id=activo_id, account_id=current_account_id(), deleted_at=None).first_or_404()
    if DepreciacionRegistro.query.filter_by(activo_fijo_id=a.id).first():
        return jsonify({
            "error": "No se puede eliminar: este activo ya tiene depreciación registrada. "
                     "La baja o venta de activos no está implementada todavía (fuera del alcance de esta fase)."
        }), 400
    a.deleted_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    db.session.commit()
    return "", 204


@app.route("/api/activos-fijos/depreciar", methods=["POST"])
@login_required
def depreciar_activos_fijos():
    """Runs straight-line depreciation for every active asset acquired on or
    before the end of `periodo`, once per período per asset (enforced by
    DepreciacionRegistro's unique constraint, not just this check)."""
    periodo = (request.args.get("periodo") or "").strip()
    if not re.match(r"^\d{4}-\d{2}$", periodo):
        return jsonify({"error": "El período debe tener el formato YYYY-MM."}), 400
    year, month = (int(p) for p in periodo.split("-"))
    if not (1 <= month <= 12):
        return jsonify({"error": "El período debe tener el formato YYYY-MM."}), 400
    fin_periodo = f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"

    account_id = current_account_id()
    activos = (ActivoFijo.query.filter_by(account_id=account_id, deleted_at=None)
               .filter(ActivoFijo.fecha_adquisicion <= fin_periodo).all())

    depreciados = []
    saltados = []
    for a in activos:
        if DepreciacionRegistro.query.filter_by(activo_fijo_id=a.id, periodo=periodo).first():
            saltados.append({"activo_fijo_id": a.id, "nombre": a.nombre, "razon": "ya procesado para este período"})
            continue

        depreciable_base = round(a.costo_adquisicion - a.valor_residual, 2)
        acumulada = compute_depreciacion_acumulada(a.id)
        if acumulada >= depreciable_base - 0.01:
            saltados.append({"activo_fijo_id": a.id, "nombre": a.nombre, "razon": "ya completamente depreciado"})
            continue

        monto = round(depreciable_base / (a.vida_util_anos * 12), 2)
        if monto <= 0:
            saltados.append({"activo_fijo_id": a.id, "nombre": a.nombre, "razon": "monto de depreciación es cero"})
            continue

        try:
            asiento = post_depreciacion_asiento(a, periodo, fin_periodo, monto)
        except ValueError as e:
            saltados.append({"activo_fijo_id": a.id, "nombre": a.nombre, "razon": f"error al contabilizar: {e}"})
            continue

        registro = DepreciacionRegistro(
            activo_fijo_id=a.id, periodo=periodo, monto=monto, asiento_id=asiento.id,
            created_at=datetime.utcnow().strftime("%Y-%m-%d"),
        )
        db.session.add(registro)
        db.session.commit()
        depreciados.append({"activo_fijo_id": a.id, "nombre": a.nombre, "monto": monto})

    return jsonify({
        "periodo": periodo,
        "depreciados": depreciados,
        "saltados": saltados,
        "total_activos_depreciados": len(depreciados),
        "total_activos_saltados": len(saltados),
        "total_monto_depreciado": round(sum(d["monto"] for d in depreciados), 2),
    })


# ---------------------------------------------------------------------------
# Inventario - stock levels (computed from a movement ledger), low-stock
# alerts, and valuation. v1 scope: no auto-linking to quotes/invoices yet.
# ---------------------------------------------------------------------------

def compute_material_stock(material_id):
    """Stock on hand is never stored directly - it's always this sum, so
    there's an audit trail and no number that can drift from its history."""
    movimientos = StockMovimiento.query.filter_by(material_id=material_id).all()
    total = 0.0
    for m in movimientos:
        total += m.cantidad if m.tipo in ("entrada", "ajuste") else -m.cantidad
    return round(total, 4)


def movimiento_to_dict(m):
    return {
        "id": m.id,
        "material_id": m.material_id,
        "material_code": m.material.code if m.material else None,
        "material_description": m.material.description if m.material else None,
        "tipo": m.tipo,
        "cantidad": m.cantidad,
        "fecha": m.fecha,
        "referencia": m.referencia,
        "created_at": m.created_at,
    }


@app.route("/api/materiales/<int:material_id>/stock", methods=["GET"])
@login_required
def get_material_stock(material_id):
    material = Material.query.filter_by(id=material_id, account_id=current_account_id()).first_or_404()
    return jsonify({"material_id": material.id, "stock": compute_material_stock(material.id)})


def _compute_inventario_list(account_id):
    """Factored out so /api/panel/resumen can reuse it directly.

    "valor_reposicion" (replacement cost) is stock x TODAY's unit_price -
    deliberately NOT the same figure as the ledger's Inventario (1030)
    account, which only reflects whatever price was posted at the time of
    each movement. This field used to be called plain "valor", which
    wrongly implied it WAS the accounting figure - see
    /api/inventario/reconciliacion for the two compared side by side."""
    materials = Material.query.filter_by(account_id=account_id, deleted_at=None).order_by(Material.code).all()
    result = []
    for m in materials:
        stock = compute_material_stock(m.id)
        minimo = m.minimo_stock or 0
        result.append({
            "id": m.id,
            "code": m.code,
            "description": m.description,
            "unit": m.unit,
            "unit_price": m.unit_price,
            "stock": stock,
            "minimo_stock": minimo,
            "bajo_stock": stock < minimo,
            "valor_reposicion": round(stock * m.unit_price, 2),
        })
    return result


@app.route("/api/inventario", methods=["GET"])
@login_required
def list_inventario():
    return jsonify(_compute_inventario_list(current_account_id()))


@app.route("/api/inventario/resumen", methods=["GET"])
@login_required
def inventario_resumen():
    """Mirrors /api/gastos/summary's style - powers the summary cards above
    the Existencias table."""
    materials = Material.query.filter_by(account_id=current_account_id(), deleted_at=None).all()
    valor_total = 0.0
    materiales_bajo_stock = 0
    for m in materials:
        stock = compute_material_stock(m.id)
        valor_total += stock * m.unit_price
        if stock < (m.minimo_stock or 0):
            materiales_bajo_stock += 1
    return jsonify({
        "valor_total": round(valor_total, 2),
        "materiales_bajo_stock": materiales_bajo_stock,
        "total_materiales": len(materials),
    })


@app.route("/api/inventario/reconciliacion", methods=["GET"])
@login_required
def inventario_reconciliacion():
    """Surfaces a real valuation inconsistency instead of hiding it:
    valor_reposicion_total revalues ALL stock at TODAY's unit_price, while
    the ledger's Inventario (1030) account only reflects whatever price was
    posted at the time of each movement. The two are expected to diverge the
    moment a material's price changes since its last movement - this
    endpoint compares them side by side rather than pretending they agree.
    Not a bug to "fix" into always matching - that would need full
    FIFO/average-cost layering, a bigger feature, out of scope here."""
    account_id = current_account_id()

    inventario = _compute_inventario_list(account_id)
    valor_reposicion_total = round(sum(m["valor_reposicion"] for m in inventario), 2)

    ensure_chart_of_accounts(account_id)
    cuenta_inventario = CuentaContable.query.filter_by(account_id=account_id, codigo="1030", deleted_at=None).first()
    hoy = datetime.utcnow().strftime("%Y-%m-%d")
    saldo_contable = compute_cuenta_balance_asof(account_id, cuenta_inventario, hoy) if cuenta_inventario else 0.0

    diferencia = round(valor_reposicion_total - saldo_contable, 2)
    return jsonify({
        "valor_reposicion_total": valor_reposicion_total,
        "saldo_contable": saldo_contable,
        "diferencia": diferencia,
        "coincide": abs(diferencia) < 0.01,
    })


@app.route("/api/inventario/movimientos", methods=["GET"])
@login_required
def list_movimientos():
    q = StockMovimiento.query.filter_by(account_id=current_account_id())
    material_id = request.args.get("material_id")
    desde = request.args.get("desde")
    hasta = request.args.get("hasta")
    if material_id:
        q = q.filter(StockMovimiento.material_id == material_id)
    if desde:
        q = q.filter(StockMovimiento.fecha >= desde)
    if hasta:
        q = q.filter(StockMovimiento.fecha <= hasta)
    movimientos = q.order_by(StockMovimiento.fecha.desc(), StockMovimiento.id.desc()).all()
    return jsonify([movimiento_to_dict(m) for m in movimientos])


@app.route("/api/inventario/movimientos", methods=["POST"])
@login_required
def create_movimiento():
    data = request.json or {}
    tipo = (data.get("tipo") or "").strip()
    if tipo not in ("entrada", "salida", "ajuste"):
        return jsonify({"error": "El tipo debe ser entrada, salida o ajuste."}), 400

    material = Material.query.filter_by(id=data.get("material_id"), account_id=current_account_id()).first()
    if not material:
        return jsonify({"error": "Material no encontrado."}), 400

    try:
        cantidad = float(data.get("cantidad", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "La cantidad debe ser un número."}), 400
    if cantidad == 0:
        return jsonify({"error": "La cantidad no puede ser cero."}), 400
    if tipo in ("entrada", "salida") and cantidad < 0:
        return jsonify({"error": "La cantidad debe ser positiva para entrada o salida."}), 400

    m = StockMovimiento(
        account_id=current_account_id(),
        material_id=material.id,
        tipo=tipo,
        cantidad=cantidad,
        fecha=data.get("fecha") or datetime.utcnow().strftime("%Y-%m-%d"),
        referencia=(data.get("referencia") or "").strip(),
        created_at=datetime.utcnow().strftime("%Y-%m-%d"),
    )
    db.session.add(m)
    db.session.flush()  # get m.id for posting, commit happens with the asiento below

    try:
        asiento = post_movimiento_inventario_asiento(m, material)
        if asiento is None:
            db.session.commit()  # nothing to post (material.unit_price is 0) - still commit the movement itself
    except ValueError as e:
        db.session.rollback()
        return jsonify({"error": f"No se pudo registrar el asiento contable: {e}"}), 400

    return jsonify(movimiento_to_dict(m)), 201


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
