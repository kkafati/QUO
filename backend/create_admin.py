"""
Creates an admin login — the platform-operator account that can see
activity/analytics across ALL business accounts. Separate from any
business account entirely (its own table, its own login at /admin/login).

Run from the backend/ folder:
    python3 create_admin.py
"""
import getpass
from datetime import date

from app import app
from models import db, Admin
from werkzeug.security import generate_password_hash


def run():
    with app.app_context():
        db.create_all()

        print("=== Nuevo login de administrador ===")
        username = input("Usuario: ").strip()

        if Admin.query.filter_by(username=username).first():
            print(f"\n✗ Ya existe un administrador con el usuario '{username}'.")
            return

        password = getpass.getpass("Contraseña: ")
        password2 = getpass.getpass("Confirmar contraseña: ")
        if password != password2:
            print("\n✗ Las contraseñas no coinciden. Intenta de nuevo.")
            return
        if len(password) < 6:
            print("\n✗ La contraseña debe tener al menos 6 caracteres.")
            return

        admin = Admin(
            username=username,
            password_hash=generate_password_hash(password),
            created_at=date.today().strftime("%Y-%m-%d"),
        )
        db.session.add(admin)
        db.session.commit()

        print(f"\n✓ Administrador '{username}' creado.")
        print("  Inicia sesión en /admin/login con estas credenciales.")


if __name__ == "__main__":
    run()
