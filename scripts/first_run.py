"""Run on every start: makes sure an owner login exists.
If the database has no users at all, creates  owner / Luxe2026."""
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import User
from app.security import hash_password

DEFAULT_USER, DEFAULT_PASS = "owner", "Luxe2026"


def main():
    db = SessionLocal()
    try:
        if db.scalar(select(func.count(User.id))):
            print("Login is ready. Use your owner username and password.")
            return
        db.add(User(username=DEFAULT_USER, full_name="Owner", password_hash=hash_password(DEFAULT_PASS), role="owner"))
        db.commit()
        print(f"First start: login created ->  username: {DEFAULT_USER}   password: {DEFAULT_PASS}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
