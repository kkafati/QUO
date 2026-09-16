"""
ONE-TIME, MANUALLY-RUN script: posts journal entries for historical
Invoice / Pago / GastoOperativo / CuentaPorPagar / PagoProveedor rows that
existed BEFORE the double-entry ledger (Phase 2) was deployed, and so never
posted an AsientoContable when they were created.

This is deliberately NOT run automatically anywhere (not at app startup, not
as a migration) - backfilling history means picking what date and account
each old row should post against, and that's a judgment call this script
makes using the exact same rules as the live app (see post_factura_asiento,
post_pago_asiento, post_gasto_asiento, post_cuenta_por_pagar_asiento, and
post_pago_proveedor_asiento in backend/app.py - this script imports and
calls those SAME functions, it does not reimplement the posting logic), but
it should still be reviewed and run by a human, not happen as a side effect.

Idempotent: a row that already has a matching AsientoContable (by
origen_type + origen_id) is skipped, so running this twice is safe.

Usage (from the repo root):
    python scripts/backfill_ledger.py                 # dry run - lists what
                                                        # WOULD be posted, writes nothing
    python scripts/backfill_ledger.py --apply          # actually posts the entries
    python scripts/backfill_ledger.py --apply --account-id 3   # limit to one tenant
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

from app import (
    app, ensure_chart_of_accounts,
    post_factura_asiento, post_pago_asiento, post_gasto_asiento,
    post_cuenta_por_pagar_asiento, post_pago_proveedor_asiento,
)
from models import db, Account, Invoice, Pago, GastoOperativo, CuentaPorPagar, PagoProveedor, AsientoContable


def _ya_posteado(origen_type, origen_id):
    return AsientoContable.query.filter_by(origen_type=origen_type, origen_id=origen_id).first() is not None


def backfill_account(account, apply_changes):
    """Returns (posted_count, skipped_count, error_count) for this account."""
    ensure_chart_of_accounts(account.id)
    posted = skipped = errors = 0

    # Facturas - excludes soft-deleted invoices on purpose: a trashed invoice
    # was presumably a mistake/duplicate and shouldn't get a real ledger entry.
    # If that's wrong for your data, adjust this filter before running --apply.
    for invoice in Invoice.query.filter_by(account_id=account.id, deleted_at=None).order_by(Invoice.fecha).all():
        if _ya_posteado("factura", invoice.id):
            skipped += 1
            continue
        print(f"  [factura]  {invoice.numero}  {invoice.fecha}  {invoice.cliente_nombre}")
        if apply_changes:
            try:
                post_factura_asiento(invoice)
                posted += 1
            except ValueError as e:
                print(f"    ERROR: {e}")
                errors += 1
        else:
            posted += 1  # counted as "would post" in dry-run

    # Pagos - each needs its invoice for the description; skip orphans quietly.
    for pago in Pago.query.filter_by(account_id=account.id).order_by(Pago.fecha).all():
        if _ya_posteado("pago", pago.id):
            skipped += 1
            continue
        invoice = db.session.get(Invoice, pago.invoice_id)
        if not invoice:
            continue
        print(f"  [pago]     factura {invoice.numero}  {pago.fecha}  L.{pago.monto:.2f}")
        if apply_changes:
            try:
                post_pago_asiento(pago, invoice)
                posted += 1
            except ValueError as e:
                print(f"    ERROR: {e}")
                errors += 1
        else:
            posted += 1

    # Gastos - same deleted_at exclusion reasoning as facturas above.
    for gasto in GastoOperativo.query.filter_by(account_id=account.id, deleted_at=None).order_by(GastoOperativo.fecha).all():
        if _ya_posteado("gasto", gasto.id):
            skipped += 1
            continue
        print(f"  [gasto]    {gasto.fecha}  {gasto.categoria}  {gasto.descripcion}")
        if apply_changes:
            try:
                post_gasto_asiento(gasto)
                posted += 1
            except ValueError as e:
                print(f"    ERROR: {e}")
                errors += 1
        else:
            posted += 1

    # Cuentas por pagar + sus pagos.
    for cxp in CuentaPorPagar.query.filter_by(account_id=account.id, deleted_at=None).order_by(CuentaPorPagar.fecha_emision).all():
        if _ya_posteado("cuenta_por_pagar", cxp.id):
            skipped += 1
        else:
            print(f"  [cxp]      {cxp.proveedor}  {cxp.fecha_emision}  L.{cxp.monto:.2f}")
            if apply_changes:
                try:
                    post_cuenta_por_pagar_asiento(cxp)
                    posted += 1
                except ValueError as e:
                    print(f"    ERROR: {e}")
                    errors += 1
            else:
                posted += 1

        for pago in PagoProveedor.query.filter_by(cuenta_por_pagar_id=cxp.id).order_by(PagoProveedor.fecha).all():
            if _ya_posteado("pago_proveedor", pago.id):
                skipped += 1
                continue
            print(f"  [pago_prov] {cxp.proveedor}  {pago.fecha}  L.{pago.monto:.2f}")
            if apply_changes:
                try:
                    post_pago_proveedor_asiento(pago, cxp)
                    posted += 1
                except ValueError as e:
                    print(f"    ERROR: {e}")
                    errors += 1
            else:
                posted += 1

    return posted, skipped, errors


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Actually write the entries. Without this flag, it's a dry run.")
    parser.add_argument("--account-id", type=int, help="Limit the backfill to one tenant account.")
    args = parser.parse_args()

    with app.app_context():
        accounts = Account.query.all()
        if args.account_id:
            accounts = [a for a in accounts if a.id == args.account_id]
            if not accounts:
                print(f"No account with id {args.account_id}.")
                return

        mode = "APPLYING" if args.apply else "DRY RUN (nothing will be written - pass --apply to commit)"
        print(f"=== Backfill Ledger: {mode} ===\n")

        total_posted = total_skipped = total_errors = 0
        for account in accounts:
            print(f"Account #{account.id} - {account.company_name}")
            posted, skipped, errors = backfill_account(account, args.apply)
            total_posted += posted
            total_skipped += skipped
            total_errors += errors
            print(f"  -> {posted} {'posted' if args.apply else 'would post'}, {skipped} already posted (skipped), {errors} errors\n")

        print("=== Summary ===")
        print(f"Total {'posted' if args.apply else 'would post'}: {total_posted}")
        print(f"Total already posted (skipped): {total_skipped}")
        print(f"Total errors: {total_errors}")
        if not args.apply:
            print("\nThis was a dry run. Re-run with --apply to actually write these entries.")


if __name__ == "__main__":
    main()
