"""
Resets the password for an existing client account.
Passwords are stored as one-way hashes, so the old password can never be
recovered — this sets a brand new one instead.

Run from the backend/ folder:
    python3 reset_password.py
"""
import getpass

from app import app
from models import db, Account
from werkzeug.security import generate_password_hash


def run():
    with app.app_context():
        print("=== Restablecer contraseña ===")
        username = input("Usuario de la cuenta: ").strip()

        account = Account.query.filter_by(username=username).first()
        if not account:
            print(f"\n✗ No existe ninguna cuenta con el usuario '{username}'.")
            print("  Cuentas existentes:", ", ".join(a.username for a in Account.query.all()) or "(ninguna)")
            return

        print(f"  Cuenta encontrada: {account.company_name}")
        password = getpass.getpass("Nueva contraseña: ")
        password2 = getpass.getpass("Confirmar nueva contraseña: ")
        if password != password2:
            print("\n✗ Las contraseñas no coinciden. Intenta de nuevo.")
            return
        if len(password) < 6:
            print("\n✗ La contraseña debe tener al menos 6 caracteres.")
            return

        account.password_hash = generate_password_hash(password)
        db.session.commit()

        print(f"\n✓ Contraseña actualizada para '{account.company_name}' (usuario: {username}).")


if __name__ == "__main__":
    run()
