"""Create (or reset) the owner login.
Usage:  python -m scripts.create_owner <username> <password> ["Full Name"]"""
import sys

from sqlalchemy import select

from app.database import SessionLocal
from app.models import User
from app.security import hash_password


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    username, password = sys.argv[1].strip().lower(), sys.argv[2]
    full_name = sys.argv[3] if len(sys.argv) > 3 else "Owner"
    db = SessionLocal()
    u = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if u:
        u.password_hash, u.role, u.is_active = hash_password(password), "owner", True
        u.token_version += 1
        print(f"Owner '{username}' password reset.")
    else:
        db.add(User(username=username, full_name=full_name, password_hash=hash_password(password), role="owner",
                    permissions=[]))
        print(f"Owner '{username}' created.")
    db.commit()


if __name__ == "__main__":
    main()
