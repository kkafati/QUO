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
    default_invoice_template = db.Column(db.String(32), default="clasica")
    next_invoice_number = db.Column(db.Integer, default=1)
    next_cotizacion_number = db.Column(db.Integer, default=1)  # plain 6-digit sequential, no prefix needed
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
    minimo_stock = db.Column(db.Float, nullable=False, default=0)  # reorder-point alert threshold
    created_at = db.Column(db.String(16))  # set once, when the material is first added
    updated_at = db.Column(db.String(16))  # refreshed on every edit
    deleted_at = db.Column(db.String(16))  # set when moved to trash; None = active

    suppliers = db.relationship("SupplierPrice", backref="material", cascade="all, delete-orphan")
    movimientos = db.relationship("StockMovimiento", backref="material", cascade="all, delete-orphan")


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


class StockMovimiento(db.Model):
    """One entry in a Material's stock ledger. Stock on hand is never stored
    as a mutable number - it's always the computed sum of these movements
    (entrada and positive ajuste add, salida and negative ajuste subtract),
    so there's always an audit trail and no number that can drift out of
    sync with its history."""
    __tablename__ = "stock_movimientos"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    material_id = db.Column(db.Integer, db.ForeignKey("materials.id"), nullable=False)
    tipo = db.Column(db.String(16), nullable=False)  # entrada | salida | ajuste
    cantidad = db.Column(db.Float, nullable=False, default=0)
    fecha = db.Column(db.String(16), nullable=False)
    referencia = db.Column(db.String(255))
    created_at = db.Column(db.String(16))


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


class LoginAttempt(db.Model):
    """Every login attempt against /api/login OR /api/admin/login, successful
    or not - this is the rate-limiting/lockout audit trail. Tracked by the
    attempted username (not account_id): a failed attempt may not match any
    real account at all, so there's nothing to foreign-key to. Rows are never
    deleted on success - the rolling window in app.py's lockout check handles
    that naturally, and erasing history here would defeat the audit-trail
    purpose of this table."""
    __tablename__ = "login_attempts"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False)
    ip_address = db.Column(db.String(64))
    success = db.Column(db.Boolean, nullable=False, default=False)
    timestamp = db.Column(db.String(32), nullable=False)


class PageView(db.Model):
    """One row per page load (not API calls) - for basic traffic counts.
    account_id is null for anonymous views (e.g. the public landing page)."""
    __tablename__ = "page_views"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"))
    path = db.Column(db.String(255), nullable=False)
    timestamp = db.Column(db.String(32), nullable=False)
    ip_address = db.Column(db.String(64))


class Cliente(db.Model):
    """A saved customer/client record - separate from Invoice.cliente_nombre/cliente_rtn,
    which stay as free text on each invoice for backward compatibility and so an
    invoice's printed client info doesn't retroactively change if the Cliente record
    is edited later."""
    __tablename__ = "clientes"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    nombre = db.Column(db.String(255), nullable=False)
    rtn = db.Column(db.String(32))
    direccion = db.Column(db.String(255))
    contacto = db.Column(db.String(255))
    telefono = db.Column(db.String(64))
    correo = db.Column(db.String(255))
    created_at = db.Column(db.String(16))
    updated_at = db.Column(db.String(16))
    deleted_at = db.Column(db.String(16))


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
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"))  # optional link to a saved Cliente
    fecha = db.Column(db.String(16), nullable=False)
    termino_pago = db.Column(db.String(16), nullable=False, default="contado")  # contado | credito
    estado = db.Column(db.String(32), nullable=False, default="Falta Pago")  # Pagado | Falta Pago | En Proceso | ...

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
    pagos = db.relationship("Pago", backref="invoice", cascade="all, delete-orphan")


class InvoiceLine(db.Model):
    __tablename__ = "invoice_lines"
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), nullable=False)
    cantidad = db.Column(db.Float, nullable=False, default=1)
    descripcion = db.Column(db.String(500), nullable=False)
    precio_unitario = db.Column(db.Float, nullable=False, default=0)


class Pago(db.Model):
    """A payment recorded against an Invoice - partial or full. Invoice.estado
    stays a manually-settable field (the dropdown on the invoice page), but
    once payments exist, a payment that fully covers total_a_pagar auto-sets
    estado to "Pagado" (see create_pago in app.py). A payment's monto is
    validated on create to never push the running total above total_a_pagar."""
    __tablename__ = "pagos"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), nullable=False)
    monto = db.Column(db.Float, nullable=False, default=0)
    fecha = db.Column(db.String(16), nullable=False)
    metodo = db.Column(db.String(32))  # efectivo | transferencia | cheque | tarjeta
    referencia = db.Column(db.String(255))
    created_at = db.Column(db.String(16))


class Cotizacion(db.Model):
    """A Cotización Clásica - same visual format as a Factura, but for
    quotes rather than tax invoices. No CAI, no Rango Autorizado, no
    exempt-purchase correlativo numbers - those are invoice-specific SAR
    requirements. numero is a plain sequential integer (6 digits, zero
    padded at render time), not the long SAR invoice format."""
    __tablename__ = "cotizaciones_clasica"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    numero = db.Column(db.Integer, nullable=False)

    cliente_nombre = db.Column(db.String(255), nullable=False)
    cliente_rtn = db.Column(db.String(32))
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"))  # optional link to a saved Cliente
    fecha = db.Column(db.String(16), nullable=False)
    termino_pago = db.Column(db.String(16), nullable=False, default="contado")  # contado | credito

    nota = db.Column(db.Text)

    descuentos = db.Column(db.Float, default=0)
    importe_exonerado = db.Column(db.Float, default=0)
    importe_exento = db.Column(db.Float, default=0)
    gravado_18_pct = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.String(16))
    updated_at = db.Column(db.String(16))
    deleted_at = db.Column(db.String(16))

    lines = db.relationship("CotizacionLine", backref="cotizacion", cascade="all, delete-orphan")


class CotizacionLine(db.Model):
    __tablename__ = "cotizacion_clasica_lines"
    id = db.Column(db.Integer, primary_key=True)
    cotizacion_id = db.Column(db.Integer, db.ForeignKey("cotizaciones_clasica.id"), nullable=False)
    cantidad = db.Column(db.Float, nullable=False, default=1)
    descripcion = db.Column(db.String(500), nullable=False)
    precio_unitario = db.Column(db.Float, nullable=False, default=0)


class Proforma(db.Model):
    """A Factura Proforma - same visual format/fields as a Factura Clásica
    (total en letras, No. Correlativo, CAI), but with no invoice numbering
    (that's assigned only when/if it's converted into a real Factura) and
    without the RTN/Rango-Autorizado/Original-Copia issuance footer."""
    __tablename__ = "proformas"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)

    cliente_nombre = db.Column(db.String(255), nullable=False)
    cliente_rtn = db.Column(db.String(32))
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"))
    fecha = db.Column(db.String(16), nullable=False)
    termino_pago = db.Column(db.String(16), nullable=False, default="contado")

    descuentos = db.Column(db.Float, default=0)
    importe_exonerado = db.Column(db.Float, default=0)
    importe_exento = db.Column(db.Float, default=0)
    gravado_18_pct = db.Column(db.Boolean, default=False)

    orden_compra_exenta = db.Column(db.String(64))
    constancia_registro_exonerado = db.Column(db.String(64))
    registro_sag = db.Column(db.String(64))

    created_at = db.Column(db.String(16))
    updated_at = db.Column(db.String(16))
    deleted_at = db.Column(db.String(16))

    lines = db.relationship("ProformaLine", backref="proforma", cascade="all, delete-orphan")


class ProformaLine(db.Model):
    __tablename__ = "proforma_lines"
    id = db.Column(db.Integer, primary_key=True)
    proforma_id = db.Column(db.Integer, db.ForeignKey("proformas.id"), nullable=False)
    cantidad = db.Column(db.Float, nullable=False, default=1)
    descripcion = db.Column(db.String(500), nullable=False)
    precio_unitario = db.Column(db.Float, nullable=False, default=0)


GASTO_CATEGORIAS = [
    "Materiales", "Mano de Obra / Nómina", "Transporte", "Servicios (agua, luz, internet)",
    "Alquiler", "Impuestos", "Herramientas / Equipo", "Otros",
]


class GastoOperativo(db.Model):
    """A real business operating expense (rent, payroll, fuel, utilities...) -
    this is the Contabilidad module's expense ledger. Not to be confused with
    the `Gasto` model above, which is a cost-catalog line item used only for
    pricing quotes/fichas, not an actual company expense.

    Modeled after a real supplier invoice: a set of line items (qty x unit
    price, each with its own discount and ISV, since not every line on a real
    invoice is taxed or discounted the same way). subtotal/descuento/isv/monto
    here are just the sum of those per-line figures, kept denormalized on the
    header row so listing/summary queries don't need to join+aggregate items."""
    __tablename__ = "gastos_operativos"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    fecha = db.Column(db.String(16), nullable=False)
    numero_factura = db.Column(db.String(64))
    categoria = db.Column(db.String(64), nullable=False, default="Otros")
    descripcion = db.Column(db.String(255), nullable=False)
    proveedor = db.Column(db.String(255))
    subtotal = db.Column(db.Float, nullable=False, default=0)
    descuento = db.Column(db.Float, nullable=False, default=0)
    isv = db.Column(db.Float, nullable=False, default=0)
    monto = db.Column(db.Float, nullable=False, default=0)
    created_at = db.Column(db.String(16))
    updated_at = db.Column(db.String(16))
    deleted_at = db.Column(db.String(16))

    items = db.relationship("GastoOperativoItem", backref="gasto", cascade="all, delete-orphan")


class GastoOperativoItem(db.Model):
    """One invoice line making up a GastoOperativo: qty x unit price, with its
    own discount (amount) and ISV (%) - a real invoice can mix taxed/untaxed
    or discounted/full-price lines, so these live per-line, not on the header."""
    __tablename__ = "gastos_operativos_items"
    id = db.Column(db.Integer, primary_key=True)
    gasto_id = db.Column(db.Integer, db.ForeignKey("gastos_operativos.id"), nullable=False)
    descripcion = db.Column(db.String(255), nullable=False)
    cantidad = db.Column(db.Float, nullable=False, default=1)
    precio_unitario = db.Column(db.Float, nullable=False, default=0)
    descuento = db.Column(db.Float, nullable=False, default=0)
    isv_pct = db.Column(db.Float, nullable=False, default=15)


# ---------------------------------------------------------------------------
# Phase 2 - real double-entry bookkeeping: chart of accounts + journal ledger,
# with Cuentas por Pagar and bank reconciliation built on top of it.
# ---------------------------------------------------------------------------

# Maps each GASTO_CATEGORIAS entry to its seeded 5000-series CuentaContable
# codigo, so gasto/cuenta-por-pagar postings know which sub-account to debit.
GASTO_CATEGORIA_CODIGOS = {
    "Materiales": "5010",
    "Mano de Obra / Nómina": "5020",
    "Transporte": "5030",
    "Servicios (agua, luz, internet)": "5040",
    "Alquiler": "5050",
    "Impuestos": "5060",
    "Herramientas / Equipo": "5070",
    "Otros": "5080",
}


class CuentaContable(db.Model):
    """One line in the Catálogo de Cuentas (chart of accounts) - NOT the same
    "account" concept as the `Account` model above (which is the tenant/login).
    Every field here is scoped to a tenant via account_id, same as every other
    model in this file; cuenta_padre_id is the self-referential parent for
    grouping sub-accounts under e.g. "1000 Activo Circulante"."""
    __tablename__ = "cuentas_contables"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    codigo = db.Column(db.String(16), nullable=False)
    nombre = db.Column(db.String(255), nullable=False)
    tipo = db.Column(db.String(16), nullable=False)  # activo | pasivo | patrimonio | ingreso | gasto
    cuenta_padre_id = db.Column(db.Integer, db.ForeignKey("cuentas_contables.id"))
    created_at = db.Column(db.String(16))
    deleted_at = db.Column(db.String(16))  # soft delete - blocked in app.py if any AsientoLinea references it

    hijos = db.relationship("CuentaContable", backref=db.backref("padre", remote_side=[id]))


class AsientoContable(db.Model):
    """One journal entry (asiento) in the Libro Diario. origen_type/origen_id
    trace back to whatever business record generated it (a factura, pago,
    gasto, etc.) - both null for a manually-entered asiento. Every asiento is
    created through crear_asiento() in app.py, which is the ONLY place that
    validates sum(debe) == sum(haber); nothing should construct one directly."""
    __tablename__ = "asientos_contables"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    fecha = db.Column(db.String(16), nullable=False)
    descripcion = db.Column(db.String(255))
    origen_type = db.Column(db.String(32))  # factura | pago | gasto | cuenta_por_pagar | pago_proveedor | manual
    origen_id = db.Column(db.Integer)
    created_at = db.Column(db.String(16))

    lineas = db.relationship("AsientoLinea", backref="asiento", cascade="all, delete-orphan")


class AsientoLinea(db.Model):
    __tablename__ = "asiento_lineas"
    id = db.Column(db.Integer, primary_key=True)
    asiento_id = db.Column(db.Integer, db.ForeignKey("asientos_contables.id"), nullable=False)
    cuenta_contable_id = db.Column(db.Integer, db.ForeignKey("cuentas_contables.id"), nullable=False)
    debe = db.Column(db.Float, nullable=False, default=0)
    haber = db.Column(db.Float, nullable=False, default=0)
    descripcion = db.Column(db.String(255))

    cuenta = db.relationship("CuentaContable")


class CuentaPorPagar(db.Model):
    """A vendor bill (factura de proveedor) owed by the business - the mirror
    image of GastoOperativo's categoria/monto shape, but for credit purchases
    tracked to a due date rather than gastos paid immediately in cash. Posts
    Debe [categoria's 5000 account] / Haber Cuentas por Pagar on creation."""
    __tablename__ = "cuentas_por_pagar"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    proveedor = db.Column(db.String(255), nullable=False)
    categoria = db.Column(db.String(64), nullable=False, default="Otros")
    descripcion = db.Column(db.String(255), nullable=False)
    fecha_emision = db.Column(db.String(16), nullable=False)
    fecha_vencimiento = db.Column(db.String(16))
    monto = db.Column(db.Float, nullable=False, default=0)
    created_at = db.Column(db.String(16))
    updated_at = db.Column(db.String(16))
    deleted_at = db.Column(db.String(16))

    pagos = db.relationship("PagoProveedor", backref="cuenta_por_pagar", cascade="all, delete-orphan")


class PagoProveedor(db.Model):
    """A payment made against a CuentaPorPagar - same shape as Phase 1's Pago
    (which pays down an Invoice), just pointed at a vendor bill instead of a
    customer invoice. Same overpayment validation: monto can never push the
    running total above the bill's monto (enforced in app.py on create)."""
    __tablename__ = "pagos_proveedor"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    cuenta_por_pagar_id = db.Column(db.Integer, db.ForeignKey("cuentas_por_pagar.id"), nullable=False)
    monto = db.Column(db.Float, nullable=False, default=0)
    fecha = db.Column(db.String(16), nullable=False)
    metodo = db.Column(db.String(32))  # efectivo | transferencia | cheque | tarjeta
    referencia = db.Column(db.String(255))
    created_at = db.Column(db.String(16))


class MovimientoBancario(db.Model):
    """One line from a bank statement, entered manually (no bank-feed import
    or fuzzy auto-matching in this pass - matching is a deliberate human
    action). asiento_id is an optional link to the AsientoContable this bank
    line corresponds to, for traceability once conciliado - some lines (bank
    fees, interest) may need a manual asiento created first via POST
    /api/asientos, then matched here; not every bank line requires one."""
    __tablename__ = "movimientos_bancarios"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    fecha = db.Column(db.String(16), nullable=False)
    descripcion = db.Column(db.String(255), nullable=False)
    tipo = db.Column(db.String(16), nullable=False)  # cargo (withdrawal) | abono (deposit)
    monto = db.Column(db.Float, nullable=False, default=0)
    referencia = db.Column(db.String(255))
    conciliado = db.Column(db.Boolean, nullable=False, default=False)
    asiento_id = db.Column(db.Integer, db.ForeignKey("asientos_contables.id"))
    created_at = db.Column(db.String(16))

    asiento = db.relationship("AsientoContable")


# ---------------------------------------------------------------------------
# Phase 4 - Fixed Asset tracking (straight-line depreciation only) and tying
# the Inventario module into Costo de Ventas. Both post to the same ledger.
# ---------------------------------------------------------------------------

class ActivoFijo(db.Model):
    """A depreciable fixed asset. Straight-line depreciation only (no
    declining balance, no units-of-production) - see DepreciacionRegistro
    for the monthly entries. No disposal/sale flow in this phase: an asset
    can be created and depreciated, but "selling" or writing it off before
    end of useful life is a separate feature, out of scope here."""
    __tablename__ = "activos_fijos"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    nombre = db.Column(db.String(255), nullable=False)
    descripcion = db.Column(db.String(255))
    fecha_adquisicion = db.Column(db.String(16), nullable=False)
    costo_adquisicion = db.Column(db.Float, nullable=False, default=0)
    valor_residual = db.Column(db.Float, nullable=False, default=0)
    vida_util_anos = db.Column(db.Integer, nullable=False, default=5)
    created_at = db.Column(db.String(16))
    deleted_at = db.Column(db.String(16))  # soft delete - blocked in app.py once any depreciación is registered

    depreciaciones = db.relationship("DepreciacionRegistro", backref="activo_fijo", cascade="all, delete-orphan")


class DepreciacionRegistro(db.Model):
    """One month's straight-line depreciation posted for one ActivoFijo.
    Accumulated depreciation for an asset is always computed by summing its
    OWN rows here (never by trying to split the shared Depreciación Acumulada
    ledger account back out per-asset). The unique constraint is the actual
    guarantee against double-depreciating the same asset for the same
    período - not just app-level checks."""
    __tablename__ = "depreciacion_registros"
    id = db.Column(db.Integer, primary_key=True)
    activo_fijo_id = db.Column(db.Integer, db.ForeignKey("activos_fijos.id"), nullable=False)
    periodo = db.Column(db.String(7), nullable=False)  # "YYYY-MM"
    monto = db.Column(db.Float, nullable=False, default=0)
    asiento_id = db.Column(db.Integer, db.ForeignKey("asientos_contables.id"))
    created_at = db.Column(db.String(16))

    __table_args__ = (db.UniqueConstraint("activo_fijo_id", "periodo", name="uq_depreciacion_activo_periodo"),)

    asiento = db.relationship("AsientoContable")

