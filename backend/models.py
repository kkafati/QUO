from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Account(db.Model):
    """A client/company tenant. One login per account (not per individual user)."""
    __tablename__ = "accounts"
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(255), nullable=False)
    username = db.Column(db.String(80), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.String(16))


class Material(db.Model):
    __tablename__ = "materials"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    code = db.Column(db.String(64), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    unit = db.Column(db.String(32), nullable=False)
    unit_price = db.Column(db.Float, nullable=False, default=0)
    updated_at = db.Column(db.String(16))

    suppliers = db.relationship("SupplierPrice", backref="material", cascade="all, delete-orphan")


class SupplierPrice(db.Model):
    """A specific supplier's (proveedor's) quote for a given Material.
    The proveedor may use its own code/description for the item; price_min/max
    on the Material are derived from these rows, they don't overwrite Material.unit_price."""
    __tablename__ = "supplier_prices"
    id = db.Column(db.Integer, primary_key=True)
    material_id = db.Column(db.Integer, db.ForeignKey("materials.id"), nullable=False)
    proveedor = db.Column(db.String(255), nullable=False)
    code = db.Column(db.String(64))
    description = db.Column(db.String(255))
    unit = db.Column(db.String(32))
    price = db.Column(db.Float, nullable=False, default=0)
    date = db.Column(db.String(16))


class Labor(db.Model):
    __tablename__ = "labor"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    code = db.Column(db.String(64), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    unit = db.Column(db.String(32), nullable=False)
    unit_price = db.Column(db.Float, nullable=False, default=0)
    updated_at = db.Column(db.String(16))


class Tool(db.Model):
    __tablename__ = "tools"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    code = db.Column(db.String(64), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    unit = db.Column(db.String(32), nullable=False)
    unit_price = db.Column(db.Float, nullable=False, default=0)
    updated_at = db.Column(db.String(16))


class Transport(db.Model):
    __tablename__ = "transport"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    code = db.Column(db.String(64), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    unit = db.Column(db.String(32), nullable=False)
    unit_price = db.Column(db.Float, nullable=False, default=0)
    updated_at = db.Column(db.String(16))


class Gasto(db.Model):
    __tablename__ = "gastos"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    code = db.Column(db.String(64), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    unit = db.Column(db.String(32), nullable=False)
    unit_price = db.Column(db.Float, nullable=False, default=0)
    updated_at = db.Column(db.String(16))


class CostCard(db.Model):
    __tablename__ = "cost_cards"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    code = db.Column(db.String(64), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    unit = db.Column(db.String(32), default="")
    admin_pct = db.Column(db.Float, nullable=False, default=10)
    utilidad_pct = db.Column(db.Float, nullable=False, default=15)

    items = db.relationship("CostCardItem", backref="cost_card", cascade="all, delete-orphan")


class CostCardItem(db.Model):
    __tablename__ = "cost_card_items"
    id = db.Column(db.Integer, primary_key=True)
    cost_card_id = db.Column(db.Integer, db.ForeignKey("cost_cards.id"), nullable=False)
    category = db.Column(db.String(16), nullable=False)  # material | labor | tool | transport | gasto
    code = db.Column(db.String(64))
    description = db.Column(db.String(255))
    unit = db.Column(db.String(32))
    rendimiento = db.Column(db.Float, default=0)
    desperdicio_pct = db.Column(db.Float, default=0)
    unit_price = db.Column(db.Float, default=0)


class Quote(db.Model):
    __tablename__ = "quotes"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    client = db.Column(db.String(255))
    date = db.Column(db.String(16))
    exento = db.Column(db.Boolean, nullable=False, default=False)

    lines = db.relationship("QuoteLine", backref="quote", cascade="all, delete-orphan")
    fees = db.relationship("QuoteFee", backref="quote", cascade="all, delete-orphan")


class QuoteLine(db.Model):
    __tablename__ = "quote_lines"
    id = db.Column(db.Integer, primary_key=True)
    quote_id = db.Column(db.Integer, db.ForeignKey("quotes.id"), nullable=False)
    cost_card_id = db.Column(db.Integer, db.ForeignKey("cost_cards.id"), nullable=False)
    quantity = db.Column(db.Float, nullable=False, default=0)

    cost_card = db.relationship("CostCard")


class QuoteFee(db.Model):
    __tablename__ = "quote_fees"
    id = db.Column(db.Integer, primary_key=True)
    quote_id = db.Column(db.Integer, db.ForeignKey("quotes.id"), nullable=False)
    category = db.Column(db.String(16), nullable=False)  # transportation | other
    code = db.Column(db.String(64))
    description = db.Column(db.String(255))
    unit = db.Column(db.String(32))
    quantity = db.Column(db.Float, default=1)
    unit_price = db.Column(db.Float, default=0)
    amount = db.Column(db.Float, default=0)  # for "other": entered directly. for "transportation": quantity * unit_price


class RegulacionStudy(db.Model):
    """A saved study from the Planificador de Demanda y Regulación tool.
    'data' stores the tool's full state (project fields + node graph) as JSON."""
    __tablename__ = "regulacion_studies"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    data = db.Column(db.Text, nullable=False)
    updated_at = db.Column(db.String(32))
