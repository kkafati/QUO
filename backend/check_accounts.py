from app import app
from models import Account

with app.app_context():
    accounts = Account.query.all()
    if not accounts:
        print("No accounts found in this database at all.")
    for a in accounts:
        print(f"username={a.username!r}  company={a.company_name!r}")