import os
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from models import db, Material, Labor, Tool, CostCard, CostCardItem, Quote, QuoteLine, QuoteFee, SupplierPrice

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(os.path.dirname(BASE_DIR), "frontend")

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "quoting.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)

with app.app_context():
    db.create_all()

CATEGORY_MODELS = {"material": Material, "labor": Labor, "tool": Tool}

# ---------------------------------------------------------------------------
# Static frontend
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


# ---------------------------------------------------------------------------
# Catalog endpoints (materials / labor / tools) - shared shape
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


def material_to_dict(item):
    base = catalog_to_dict(item)
    suppliers = item.suppliers
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
    def list_items():
        q = request.args.get("q", "").strip().lower()
        items = Model.query.order_by(Model.code).all()
        if q:
            items = [i for i in items if q in i.code.lower() or q in i.description.lower()]
        return jsonify([to_dict(i) for i in items])

    @app.route(f"/api/catalog/{category}", methods=["POST"], endpoint=f"{endpoint}_create")
    def create_item():
        data = request.json or {}
        item = Model(
            code=data.get("code", "").strip(),
            description=data.get("description", "").strip(),
            unit=data.get("unit", "").strip(),
            unit_price=float(data.get("unit_price", 0) or 0),
            updated_at=datetime.utcnow().strftime("%Y-%m-%d"),
        )
        db.session.add(item)
        db.session.commit()
        return jsonify(to_dict(item)), 201

    @app.route(f"/api/catalog/{category}/<int:item_id>", methods=["PUT"], endpoint=f"{endpoint}_update")
    def update_item(item_id):
        item = Model.query.get_or_404(item_id)
        data = request.json or {}
        item.code = data.get("code", item.code).strip()
        item.description = data.get("description", item.description).strip()
        item.unit = data.get("unit", item.unit).strip()
        item.unit_price = float(data.get("unit_price", item.unit_price) or 0)
        item.updated_at = datetime.utcnow().strftime("%Y-%m-%d")
        db.session.commit()
        return jsonify(to_dict(item))

    @app.route(f"/api/catalog/{category}/<int:item_id>", methods=["DELETE"], endpoint=f"{endpoint}_delete")
    def delete_item(item_id):
        item = Model.query.get_or_404(item_id)
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
def list_all_suppliers():
    q = request.args.get("q", "").strip().lower()
    rows = SupplierPrice.query.order_by(SupplierPrice.date.desc()).all()
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
def list_suppliers(material_id):
    Material.query.get_or_404(material_id)
    rows = SupplierPrice.query.filter_by(material_id=material_id).order_by(SupplierPrice.date.desc()).all()
    return jsonify([supplier_to_dict(s) for s in rows])


@app.route("/api/materials/<int:material_id>/suppliers", methods=["POST"])
def create_supplier(material_id):
    Material.query.get_or_404(material_id)
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


@app.route("/api/suppliers/<int:supplier_id>", methods=["PUT"])
def update_supplier(supplier_id):
    s = SupplierPrice.query.get_or_404(supplier_id)
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
def delete_supplier(supplier_id):
    s = SupplierPrice.query.get_or_404(supplier_id)
    db.session.delete(s)
    db.session.commit()
    return "", 204


# ---------------------------------------------------------------------------
# Cost cards (Fichas de Costo)
# ---------------------------------------------------------------------------

def compute_card_totals(card):
    """Compute all derived totals for a cost card. Returns a dict."""
    groups = {"material": [], "labor": [], "tool": []}
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
    direct_cost = total_materials + total_labor + total_tools
    admin_amount = direct_cost * (card.admin_pct / 100.0)
    utilidad_amount = direct_cost * (card.utilidad_pct / 100.0)
    total_cost = direct_cost + admin_amount + utilidad_amount

    return {
        "id": card.id,
        "code": card.code,
        "name": card.name,
        "unit": card.unit,
        "admin_pct": card.admin_pct,
        "utilidad_pct": card.utilidad_pct,
        "materials": groups["material"],
        "labor": groups["labor"],
        "tools": groups["tool"],
        "total_materials": round(total_materials, 4),
        "total_labor": round(total_labor, 4),
        "total_tools": round(total_tools, 4),
        "direct_cost": round(direct_cost, 4),
        "admin_amount": round(admin_amount, 4),
        "utilidad_amount": round(utilidad_amount, 4),
        "total_cost": round(total_cost, 4),
    }


@app.route("/api/costcards", methods=["GET"])
def list_costcards():
    q = request.args.get("q", "").strip().lower()
    cards = CostCard.query.order_by(CostCard.code).all()
    if q:
        cards = [c for c in cards if q in c.code.lower() or q in c.name.lower()]
    return jsonify([compute_card_totals(c) for c in cards])


@app.route("/api/costcards/<int:card_id>", methods=["GET"])
def get_costcard(card_id):
    card = CostCard.query.get_or_404(card_id)
    return jsonify(compute_card_totals(card))


@app.route("/api/costcards", methods=["POST"])
def create_costcard():
    data = request.json or {}
    card = CostCard(
        code=data.get("code", "").strip(),
        name=data.get("name", "").strip(),
        unit=data.get("unit", "").strip(),
        admin_pct=float(data.get("admin_pct", 10) or 0),
        utilidad_pct=float(data.get("utilidad_pct", 15) or 0),
    )
    db.session.add(card)
    db.session.commit()
    _sync_items(card, data.get("items", []))
    return jsonify(compute_card_totals(card)), 201


@app.route("/api/costcards/<int:card_id>", methods=["PUT"])
def update_costcard(card_id):
    card = CostCard.query.get_or_404(card_id)
    data = request.json or {}
    card.code = data.get("code", card.code).strip()
    card.name = data.get("name", card.name).strip()
    card.unit = data.get("unit", card.unit).strip()
    card.admin_pct = float(data.get("admin_pct", card.admin_pct) or 0)
    card.utilidad_pct = float(data.get("utilidad_pct", card.utilidad_pct) or 0)
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
def delete_costcard(card_id):
    card = CostCard.query.get_or_404(card_id)
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
        fees[fee.category].append({
            "id": fee.id,
            "description": fee.description,
            "amount": fee.amount,
        })

    grand_total = lines_total + fees_total

    return {
        "id": quote.id,
        "name": quote.name,
        "client": quote.client,
        "date": quote.date,
        "lines": lines,
        "lines_total": round(lines_total, 2),
        "transportation": fees["transportation"],
        "other_fees": fees["other"],
        "fees_total": round(fees_total, 2),
        "grand_total": round(grand_total, 2),
    }


@app.route("/api/quotes", methods=["GET"])
def list_quotes():
    quotes = Quote.query.order_by(Quote.id.desc()).all()
    return jsonify([compute_quote_totals(q) for q in quotes])


@app.route("/api/quotes/<int:quote_id>", methods=["GET"])
def get_quote(quote_id):
    quote = Quote.query.get_or_404(quote_id)
    return jsonify(compute_quote_totals(quote))


@app.route("/api/quotes", methods=["POST"])
def create_quote():
    data = request.json or {}
    quote = Quote(
        name=data.get("name", "").strip(),
        client=data.get("client", "").strip(),
        date=data.get("date") or datetime.utcnow().strftime("%Y-%m-%d"),
    )
    db.session.add(quote)
    db.session.commit()
    _sync_quote_children(quote, data)
    return jsonify(compute_quote_totals(quote)), 201


@app.route("/api/quotes/<int:quote_id>", methods=["PUT"])
def update_quote(quote_id):
    quote = Quote.query.get_or_404(quote_id)
    data = request.json or {}
    quote.name = data.get("name", quote.name).strip()
    quote.client = data.get("client", quote.client).strip()
    quote.date = data.get("date", quote.date)
    _sync_quote_children(quote, data)
    db.session.commit()
    return jsonify(compute_quote_totals(quote))


def _sync_quote_children(quote, data):
    if "lines" in data:
        for ln in list(quote.lines):
            db.session.delete(ln)
        db.session.flush()
        for ln in data["lines"]:
            db.session.add(QuoteLine(
                quote_id=quote.id,
                cost_card_id=ln["cost_card_id"],
                quantity=float(ln.get("quantity", 0) or 0),
            ))
    if "transportation" in data or "other_fees" in data:
        for fee in list(quote.fees):
            db.session.delete(fee)
        db.session.flush()
        for fee in data.get("transportation", []):
            db.session.add(QuoteFee(quote_id=quote.id, category="transportation",
                                     description=fee.get("description", ""),
                                     amount=float(fee.get("amount", 0) or 0)))
        for fee in data.get("other_fees", []):
            db.session.add(QuoteFee(quote_id=quote.id, category="other",
                                     description=fee.get("description", ""),
                                     amount=float(fee.get("amount", 0) or 0)))
    db.session.commit()


@app.route("/api/quotes/<int:quote_id>", methods=["DELETE"])
def delete_quote(quote_id):
    quote = Quote.query.get_or_404(quote_id)
    db.session.delete(quote)
    db.session.commit()
    return "", 204


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
