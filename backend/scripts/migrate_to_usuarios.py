"""
ONE-TIME, MANUALLY-RUN script: creates one Usuario per existing Account, so
every business that could log in before the Usuario/roles system existed can
still log in afterward - as an administrador, with the exact same username
and password it already had.

This is deliberately NOT run automatically anywhere (not at app startup, not
as a migration) - it changes who can log in, so it should be reviewed and
run by a human, not happen as a side effect of pulling new code.

For each Account:
  - If a Usuario with that Account's username ALREADY exists, it is skipped
    (with a message) - this is what makes the script safe to run more than
    once. Existing password_hash is never touched or reset.
  - If that username is already taken by a Usuario belonging to a DIFFERENT
    account (a collision), the account is skipped and reported - resolve
    this by hand (usernames are unique platform-wide), then re-run.
  - Otherwise, creates exactly one Usuario: same username, same
    password_hash (copied byte-for-byte, NOT reset or rehashed), nombre
    defaulting to the account's company_name, rol "administrador",
    activo True.

Account.username / Account.password_hash are left completely alone by this
script - they are not deleted, cleared, or altered in any way.

Usage (from the repo root):
    python backend/scripts/migrate_to_usuarios.py                # dry run - lists what
                                                                    # WOULD be created, writes nothing
    python backend/scripts/migrate_to_usuarios.py --apply         # actually creates the Usuario rows
"""
import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app import app
from models import db, Account, Usuario


def migrate(apply_changes):
    migrated = 0
    already_migrated = 0
    collisions = []

    accounts = Account.query.order_by(Account.id).all()
    for account in accounts:
        existing = Usuario.query.filter_by(username=account.username).first()
        if existing:
            if existing.account_id == account.id:
                print(f"  [skip - ya migrado]  cuenta {account.id} ({account.company_name}): "
                      f"usuario '{account.username}' ya existe")
                already_migrated += 1
            else:
                print(f"  [COLISIÓN]  cuenta {account.id} ({account.company_name}): "
                      f"el usuario '{account.username}' ya pertenece a la cuenta {existing.account_id} - "
                      f"omitido, resolver manualmente")
                collisions.append((account.id, account.username, existing.account_id))
            continue

        print(f"  [crear]  cuenta {account.id} ({account.company_name}): "
              f"usuario '{account.username}', rol administrador")
        if apply_changes:
            usuario = Usuario(
                account_id=account.id,
                username=account.username,
                password_hash=account.password_hash,  # copied as-is, never rehashed/reset
                nombre=account.company_name,
                rol="administrador",
                activo=True,
                created_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            )
            db.session.add(usuario)
        migrated += 1

    if apply_changes:
        db.session.commit()

    print()
    print("=" * 60)
    print(f"Cuentas totales examinadas: {len(accounts)}")
    print(f"Usuarios {'creados' if apply_changes else 'A CREAR (dry run)'}: {migrated}")
    print(f"Ya migradas (sin cambios): {already_migrated}")
    print(f"Colisiones de username (omitidas, revisar a mano): {len(collisions)}")
    for account_id, username, other_account_id in collisions:
        print(f"    - cuenta {account_id}: '{username}' ya usado por la cuenta {other_account_id}")
    if not apply_changes:
        print()
        print("Esto fue un dry run - no se escribió nada. Vuelve a correr con --apply para aplicar.")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Actually create the Usuario rows (default: dry run)")
    args = parser.parse_args()

    with app.app_context():
        migrate(apply_changes=args.apply)
