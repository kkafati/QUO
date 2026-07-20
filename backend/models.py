from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Material(db.Model):
    __tablename__ = "materials"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(64), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    unit = db.Column(db.String(32), nullable=False)
    unit_price = db.Column(db.Float, nullable=False, default=0)
    updated_at = db.Column(db.String(16))


class Labor(db.Model):
    __tablename__ = "labor"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(64), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    unit = db.Column(db.String(32), nullable=False)
    unit_price = db.Column(db.Float, nullable=False, default=0)
    updated_at = db.Column(db.String(16))


class Tool(db.Model):
    __tablename__ = "tools"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(64), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    unit = db.Column(db.String(32), nullable=False)
    unit_price = db.Column(db.Float, nullable=False, default=0)
    updated_at = db.Column(db.String(16))


class CostCard(db.Model):
    __tablename__ = "cost_cards"
    id = db.Column(db.Integer, primary_key=True)
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
    category = db.Column(db.String(16), nullable=False)  # material | labor | tool
    code = db.Column(db.String(64))
    description = db.Column(db.String(255))
    unit = db.Column(db.String(32))
    rendimiento = db.Column(db.Float, default=0)
    desperdicio_pct = db.Column(db.Float, default=0)
    unit_price = db.Column(db.Float, default=0)


class Quote(db.Model):
    __tablename__ = "quotes"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    client = db.Column(db.String(255))
    date = db.Column(db.String(16))

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
    description = db.Column(db.String(255))
    amount = db.Column(db.Float, default=0)
