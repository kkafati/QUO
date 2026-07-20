"""
Populates the database with realistic sample data for testing:
catalogs (materials, labor, tools, transport, gastos), supplier price
quotes for a few materials, three complete Fichas de Costo (each using
all five sections), and two Cotizaciones (one taxable, one exempt).

Run from the backend/ folder:
    python3 seed_data.py

This WIPES the current database and replaces it with the sample data.
"""
import os
from datetime import date

from app import app
from models import (
    db, Material, SupplierPrice, Labor, Tool, Transport, Gasto,
    CostCard, CostCardItem, Quote, QuoteLine,
)

TODAY = date.today().strftime("%Y-%m-%d")


def run():
    with app.app_context():
        db.drop_all()
        db.create_all()

        # ---------------- Materiales ----------------
        materials = {
            "X01": Material(code="X01", description="Poste PM-30 clase 5", unit="Unidad", unit_price=0, updated_at=TODAY),
            "X02": Material(code="X02", description="Poste PM-40 clase 5", unit="Unidad", unit_price=0, updated_at=TODAY),
            "X03": Material(code="X03", description="Transformador TS-15", unit="Unidad", unit_price=0, updated_at=TODAY),
            "X04": Material(code="X04", description="Cable SF#2 ACSR-1FASE", unit="Metros", unit_price=0, updated_at=TODAY),
            "X05": Material(code="X05", description="Cruceta CS-2", unit="Unidad", unit_price=0, updated_at=TODAY),
            "X06": Material(code="X06", description="Aislador tipo Pin", unit="Unidad", unit_price=0, updated_at=TODAY),
            "X07": Material(code="X07", description="Grapa de retención LL40W", unit="Unidad", unit_price=0, updated_at=TODAY),
        }
        for m in materials.values():
            db.session.add(m)
        db.session.flush()

        # ---------------- Cotizaciones de Proveedores (per material) ----------------
        supplier_quotes = [
            ("X01", "Ferretería Central", "FC-102", "Poste concreto 30ft clase 5", "Unidad", 9200, "2026-06-01"),
            ("X01", "Distribuidora Norte", "DN-88", "Poste PM30 clase 5", "Unidad", 9800, "2026-07-10"),
            ("X01", "Comercial Sur", "CS-40", "Poste 30ft clase 5", "Unidad", 9600, "2026-07-10"),
            ("X02", "Distribuidora Norte", "DN-90", "Poste PM40 clase 5", "Unidad", 17200, "2026-06-15"),
            ("X02", "Ferretería Central", "FC-140", "Poste concreto 40ft clase 5", "Unidad", 17500, "2026-07-05"),
            ("X03", "Electro Suministros HN", "ESH-15", "Transformador monofásico 15kVA", "Unidad", 86000, "2026-05-20"),
            ("X03", "Distribuidora Norte", "DN-TS15", "Transformador TS-15", "Unidad", 87500, "2026-07-12"),
            ("X04", "Cables de Honduras", "CH-SF2", "Cable ACSR calibre SF#2", "Metros", 62, "2026-06-01"),
            ("X04", "Distribuidora Norte", "DN-SF2", "Cable SF#2 ACSR 1 fase", "Metros", 64, "2026-07-08"),
            ("X05", "Ferretería Central", "FC-CS2", "Cruceta de concreto CS-2", "Unidad", 1260, "2026-06-20"),
            ("X06", "Electro Suministros HN", "ESH-PIN", "Aislador tipo Pin porcelana", "Unidad", 320, "2026-06-25"),
            ("X07", "Distribuidora Norte", "DN-LL40", "Grapa de retención LL40W", "Unidad", 4300, "2026-06-28"),
        ]
        for code, proveedor, sup_code, sup_desc, unit, price, dt in supplier_quotes:
            db.session.add(SupplierPrice(
                material_id=materials[code].id, proveedor=proveedor, code=sup_code,
                description=sup_desc, unit=unit, price=price, date=dt,
            ))

        # ---------------- Mano de Obra ----------------
        labor = {
            "M01": Labor(code="M01", description="Cuadrilla de instalación (linero + ayudante)", unit="Hora", unit_price=350, updated_at=TODAY),
            "M02": Labor(code="M02", description="Electricista certificado", unit="Hora", unit_price=280, updated_at=TODAY),
            "M03": Labor(code="M03", description="Ayudante de línea", unit="Hora", unit_price=150, updated_at=TODAY),
        }
        for l in labor.values():
            db.session.add(l)

        # ---------------- Herramientas ----------------
        tools = {
            "H01": Tool(code="H01", description="Grúa hidráulica 10T", unit="Día", unit_price=4500, updated_at=TODAY),
            "H02": Tool(code="H02", description="Excavadora compacta", unit="Día", unit_price=3800, updated_at=TODAY),
            "H03": Tool(code="H03", description="Equipo de puesta a tierra", unit="Día", unit_price=900, updated_at=TODAY),
            "H04": Tool(code="H04", description="Camión canasta (hidrogrúa)", unit="Día", unit_price=5200, updated_at=TODAY),
        }
        for t in tools.values():
            db.session.add(t)

        # ---------------- Transporte ----------------
        transport = {
            "T01": Transport(code="T01", description="Flete camión 10T", unit="Viaje", unit_price=3500, updated_at=TODAY),
            "T02": Transport(code="T02", description="Flete camión plataforma", unit="Viaje", unit_price=5800, updated_at=TODAY),
        }
        for tr in transport.values():
            db.session.add(tr)

        # ---------------- Otros Gastos ----------------
        gastos = {
            "G01": Gasto(code="G01", description="Permisos municipales", unit="Global", unit_price=6000, updated_at=TODAY),
            "G02": Gasto(code="G02", description="Supervisión y fiscalización ENEE", unit="Global", unit_price=15000, updated_at=TODAY),
            "G03": Gasto(code="G03", description="Seguro de obra (póliza)", unit="Global", unit_price=8000, updated_at=TODAY),
        }
        for g in gastos.values():
            db.session.add(g)

        db.session.flush()

        # ---------------- Fichas de Costo ----------------
        def item(cat, code, desc, unit, rendimiento, desperdicio, price):
            return CostCardItem(category=cat, code=code, description=desc, unit=unit,
                                 rendimiento=rendimiento, desperdicio_pct=desperdicio, unit_price=price)

        card1 = CostCard(code="001", name="Instalación de poste PM-30 con crucetas y aisladores", unit="Unidad", admin_pct=10, utilidad_pct=15)
        card1.items = [
            item("material", "X01", materials["X01"].description, "Unidad", 1, 5, 9800),
            item("material", "X05", materials["X05"].description, "Unidad", 1, 5, 1260),
            item("material", "X06", materials["X06"].description, "Unidad", 2, 3, 320),
            item("labor", "M01", labor["M01"].description, "Hora", 6, 0, 350),
            item("labor", "M03", labor["M03"].description, "Hora", 6, 0, 150),
            item("tool", "H01", tools["H01"].description, "Día", 0.5, 0, 4500),
            item("tool", "H03", tools["H03"].description, "Día", 0.5, 0, 900),
            item("transport", "T01", transport["T01"].description, "Viaje", 1, 0, 3500),
            item("gasto", "G01", gastos["G01"].description, "Global", 0.02, 0, 6000),
        ]
        db.session.add(card1)

        card2 = CostCard(code="002", name="Tendido de cable SF#2 ACSR", unit="Metro", admin_pct=10, utilidad_pct=15)
        card2.items = [
            item("material", "X04", materials["X04"].description, "Metros", 1, 5, 64),
            item("labor", "M01", labor["M01"].description, "Hora", 0.05, 0, 350),
            item("tool", "H04", tools["H04"].description, "Día", 0.01, 0, 5200),
            item("transport", "T01", transport["T01"].description, "Viaje", 0.001, 0, 3500),
        ]
        db.session.add(card2)

        card3 = CostCard(code="003", name="Instalación de transformador TS-15", unit="Unidad", admin_pct=10, utilidad_pct=15)
        card3.items = [
            item("material", "X03", materials["X03"].description, "Unidad", 1, 2, 87500),
            item("material", "X07", materials["X07"].description, "Unidad", 4, 5, 4300),
            item("labor", "M02", labor["M02"].description, "Hora", 8, 0, 280),
            item("labor", "M03", labor["M03"].description, "Hora", 8, 0, 150),
            item("tool", "H01", tools["H01"].description, "Día", 1, 0, 4500),
            item("transport", "T02", transport["T02"].description, "Viaje", 1, 0, 5800),
            item("gasto", "G02", gastos["G02"].description, "Global", 0.1, 0, 15000),
            item("gasto", "G03", gastos["G03"].description, "Global", 0.1, 0, 8000),
        ]
        db.session.add(card3)

        db.session.flush()

        # ---------------- Cotizaciones ----------------
        quote1 = Quote(name="Proyecto Ampliación El Rosario", client="ENEE", date=TODAY, exento=False)
        quote1.lines = [
            QuoteLine(cost_card_id=card1.id, quantity=24),
            QuoteLine(cost_card_id=card2.id, quantity=2900),
            QuoteLine(cost_card_id=card3.id, quantity=3),
        ]
        db.session.add(quote1)

        quote2 = Quote(name="Proyecto Comunidad La Esperanza", client="Alcaldía Municipal", date=TODAY, exento=True)
        quote2.lines = [
            QuoteLine(cost_card_id=card1.id, quantity=5),
            QuoteLine(cost_card_id=card3.id, quantity=1),
        ]
        db.session.add(quote2)

        db.session.commit()

        print("Seed data created:")
        print(f"  Materiales: {Material.query.count()}")
        print(f"  Cotizaciones de Proveedores: {SupplierPrice.query.count()}")
        print(f"  Mano de Obra: {Labor.query.count()}")
        print(f"  Herramientas: {Tool.query.count()}")
        print(f"  Transporte: {Transport.query.count()}")
        print(f"  Gastos: {Gasto.query.count()}")
        print(f"  Fichas de Costo: {CostCard.query.count()}")
        print(f"  Cotizaciones: {Quote.query.count()}")


if __name__ == "__main__":
    run()
