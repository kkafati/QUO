import os
import json
from functools import wraps
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory, session, redirect, url_for, abort
from werkzeug.security import check_password_hash
from models import db, Account, Material, Labor, Tool, Transport, Gasto, CostCard, CostCardItem, Quote, QuoteLine, QuoteFee, SupplierPrice, RegulacionStudy

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(os.path.dirname(BASE_DIR), "frontend")
LANDING_DIR = os.path.join(os.path.dirname(BASE_DIR), "landing")
REGULACION_DIR = os.path.join(os.path.dirname(BASE_DIR), "regulacion")
AUTH_DIR = os.path.join(os.path.dirname(BASE_DIR), "auth")

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="/cotizaciones")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "quoting.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
# IMPORTANT: change this to a long random value before deploying for real.
# Anyone who has this value can forge login sessions.
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-me-before-deploying")
db.init_app(app)

with app.app_context():
    db.create_all()

CATEGORY_MODELS = {"material": Material, "labor": Labor, "tool": Tool, "transport": Transport, "gasto": Gasto}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def current_account_id():
    return session.get("account_id")


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
    return jsonify({"ok": True, "company_name": account.company_name})


@app.route("/api/me", methods=["GET"])
def api_me():
    if not current_account_id():
        return jsonify({"authenticated": False})
    return jsonify({"authenticated": True, "company_name": session.get("company_name")})


@app.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Static frontend
# ---------------------------------------------------------------------------

@app.route("/")
def landing():
    return send_from_directory(LANDING_DIR, "index.html")


@app.route("/cotizaciones/")
@login_required
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/regulación/")
@app.route("/regulacion/")
@login_required
def regulacion():
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
        cards = [c for c in cards if q in c.code.lower() or q in c.name.lower()]
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
