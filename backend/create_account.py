"""
Creates a new client account (login) for the app.
Each account is a separate tenant — its own materials, fichas, cotizaciones,
and regulación studies, completely isolated from every other account.

Run from the backend/ folder:
    python3 create_account.py
"""
import getpass
from datetime import date

from app import app
from models import db, Account
from werkzeug.security import generate_password_hash


def run():
    with app.app_context():
        db.create_all()

        print("=== Nueva cuenta de cliente ===")
        company_name = input("Nombre de la empresa/cliente: ").strip()
        username = input("Usuario (para iniciar sesión): ").strip()

        if Account.query.filter_by(username=username).first():
            print(f"\n✗ Ya existe una cuenta con el usuario '{username}'. Elige otro.")
            return

        password = getpass.getpass("Contraseña: ")
        password2 = getpass.getpass("Confirmar contraseña: ")
        if password != password2:
            print("\n✗ Las contraseñas no coinciden. Intenta de nuevo.")
            return
        if len(password) < 6:
            print("\n✗ La contraseña debe tener al menos 6 caracteres.")
            return

        account = Account(
            company_name=company_name or username,
            username=username,
            password_hash=generate_password_hash(password),
            created_at=date.today().strftime("%Y-%m-%d"),
        )
        db.session.add(account)
        db.session.commit()

        print(f"\n✓ Cuenta creada para '{account.company_name}'.")
        print(f"  Usuario: {username}")
        print(f"  Puede iniciar sesión en /login con estas credenciales.")


if __name__ == "__main__":
    run()
