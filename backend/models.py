from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Account(db.Model):
    """A client/company tenant. One login per account (not per individual user)."""
    __tablename__ = "accounts"
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(255), nullable=False)  # trade name, shown in the UI
    username = db.Column(db.String(80), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.String(16))

    # Business profile (Account Settings) - feeds Invoicing/Accounting later
    legal_name = db.Column(db.String(255))       # Razón Social
    tax_id = db.Column(db.String(64))            # RTN
    address = db.Column(db.String(255))
    phone = db.Column(db.String(64))
    email = db.Column(db.String(255))
    website = db.Column(db.String(255))
    currency = db.Column(db.String(8), default="HNL")
    logo_data_url = db.Column(db.Text)           # base64 data: URL, optional custom logo
    invoice_prefix = db.Column(db.String(24), default="")   # e.g. 000-001-01-00000000
    next_invoice_number = db.Column(db.Integer, default=1)
    cai = db.Column(db.String(40))                          # Código de Autorización de Impresión
    cai_fecha_limite = db.Column(db.String(10))              # DD/MM/AAAA
    rango_autorizado_desde = db.Column(db.String(24))
    rango_autorizado_hasta = db.Column(db.String(24))
    last_seen = db.Column(db.String(32))  # updated on each authenticated request, for "online now"


class Material(db.Model):
    __tablename__ = "materials"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    code = db.Column(db.String(64), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    unit = db.Column(db.String(32), nullable=False)
    unit_price = db.Column(db.Float, nullable=False, default=0)
    created_at = db.Column(db.String(16))  # set once, when the material is first added
    updated_at = db.Column(db.String(16))  # refreshed on every edit
    deleted_at = db.Column(db.String(16))  # set when moved to trash; None = active

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
    deleted_at = db.Column(db.String(16))


class Tool(db.Model):
    __tablename__ = "tools"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    code = db.Column(db.String(64), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    unit = db.Column(db.String(32), nullable=False)
    unit_price = db.Column(db.Float, nullable=False, default=0)
    updated_at = db.Column(db.String(16))
    deleted_at = db.Column(db.String(16))


class Transport(db.Model):
    __tablename__ = "transport"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    code = db.Column(db.String(64), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    unit = db.Column(db.String(32), nullable=False)
    unit_price = db.Column(db.Float, nullable=False, default=0)
    updated_at = db.Column(db.String(16))
    deleted_at = db.Column(db.String(16))


class Gasto(db.Model):
    __tablename__ = "gastos"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    code = db.Column(db.String(64), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    unit = db.Column(db.String(32), nullable=False)
    unit_price = db.Column(db.Float, nullable=False, default=0)
    updated_at = db.Column(db.String(16))
    deleted_at = db.Column(db.String(16))


class CostCard(db.Model):
    __tablename__ = "cost_cards"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    code = db.Column(db.String(64), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    unit = db.Column(db.String(32), default="")
    admin_pct = db.Column(db.Float, nullable=False, default=10)
    utilidad_pct = db.Column(db.Float, nullable=False, default=15)
    created_at = db.Column(db.String(16))  # set once, when the ficha is first created
    updated_at = db.Column(db.String(16))  # refreshed on every edit
    deleted_at = db.Column(db.String(16))  # set when moved to trash; None = active

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
    deleted_at = db.Column(db.String(16))  # set when moved to trash; None = active

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


class Admin(db.Model):
    """Platform operator login - separate from business Accounts entirely.
    Can see analytics/activity across every account. Not tied to any one business."""
    __tablename__ = "admins"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.String(16))


class LoginEvent(db.Model):
    """One row per login or logout, for activity history (both the business's own
    'Actividad' view and the admin's platform-wide view)."""
    __tablename__ = "login_events"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    event_type = db.Column(db.String(16), nullable=False)  # login | logout
    timestamp = db.Column(db.String(32), nullable=False)
    ip_address = db.Column(db.String(64))
    user_agent = db.Column(db.String(255))

    account = db.relationship("Account")


class PageView(db.Model):
    """One row per page load (not API calls) - for basic traffic counts.
    account_id is null for anonymous views (e.g. the public landing page)."""
    __tablename__ = "page_views"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"))
    path = db.Column(db.String(255), nullable=False)
    timestamp = db.Column(db.String(32), nullable=False)
    ip_address = db.Column(db.String(64))


class Invoice(db.Model):
    """A Factura. CAI, Rango Autorizado, Fecha Límite, and the business's own
    RTN/contact info all come live from the Account profile at render time -
    not duplicated here - so updating them in Cuenta updates every invoice."""
    __tablename__ = "invoices"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    numero = db.Column(db.String(32), nullable=False)   # e.g. 000-001-01-00000001
    template = db.Column(db.String(32), nullable=False, default="clasica")

    cliente_nombre = db.Column(db.String(255), nullable=False)
    cliente_rtn = db.Column(db.String(32))
    fecha = db.Column(db.String(16), nullable=False)
    termino_pago = db.Column(db.String(16), nullable=False, default="contado")  # contado | credito

    descuentos = db.Column(db.Float, default=0)
    importe_exonerado = db.Column(db.Float, default=0)
    importe_exento = db.Column(db.Float, default=0)
    gravado_18_pct = db.Column(db.Boolean, default=False)  # if true, items are taxed at 18% instead of 15%

    orden_compra_exenta = db.Column(db.String(64))
    constancia_registro_exonerado = db.Column(db.String(64))
    registro_sag = db.Column(db.String(64))

    created_at = db.Column(db.String(16))
    updated_at = db.Column(db.String(16))
    deleted_at = db.Column(db.String(16))

    lines = db.relationship("InvoiceLine", backref="invoice", cascade="all, delete-orphan")


class InvoiceLine(db.Model):
    __tablename__ = "invoice_lines"
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), nullable=False)
    cantidad = db.Column(db.Float, nullable=False, default=1)
    descripcion = db.Column(db.String(500), nullable=False)
    precio_unitario = db.Column(db.Float, nullable=False, default=0)

