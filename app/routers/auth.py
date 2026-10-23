from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import PERMISSIONS, ROLES, Customer, User
from ..security import (check_login_allowed, clear_login_failures, create_token, get_current_user, hash_password,
                        record_login_failure, require_owner, verify_password)
from ..services import audit
from ..config import settings

router = APIRouter(prefix="/api", tags=["auth & users"])


class LoginIn(BaseModel):
    username: str
    password: str


def user_dict(u: User) -> dict:
    return {"id": u.id, "username": u.username, "full_name": u.full_name, "role": u.role,
            "permissions": sorted(PERMISSIONS) if u.role == "owner" else (u.permissions or []),
            "customer_id": u.customer_id, "is_active": u.is_active, "created_at": u.created_at.isoformat()}


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    uname = body.username.strip().lower()
    check_login_allowed(uname)
    u = db.execute(select(User).where(func.lower(User.username) == uname)).scalar_one_or_none()
    if not u or not verify_password(body.password, u.password_hash):
        record_login_failure(uname)
        raise HTTPException(401, "Wrong username or password.")
    if not u.is_active:
        raise HTTPException(403, "This login is switched off. Contact the owner.")
    clear_login_failures(uname)
    audit(db, u, "login", "user", u.id)
    db.commit()
    return {"token": create_token(u), "user": user_dict(u), "business": settings.BUSINESS_NAME}


@router.get("/auth/me")
def me(user: User = Depends(get_current_user)):
    return {"user": user_dict(user), "business": settings.BUSINESS_NAME, "all_permissions": PERMISSIONS,
            "gst_round": settings.GST_ROUND_RUPEE, "version": "2026-10-23",
            "shop": {"name": settings.BUSINESS_NAME, "address": settings.BUSINESS_ADDRESS, "phone": settings.BUSINESS_PHONE,
                     "gstin": settings.BUSINESS_GSTIN, "terms": [t.strip() for t in settings.BILL_TERMS.split("|") if t.strip()]}}


class PasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=6)


@router.post("/auth/change-password")
def change_password(body: PasswordIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Current password is wrong.")
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1
    audit(db, user, "password_changed", "user", user.id)
    db.commit()
    return {"token": create_token(user), "message": "Password changed."}


@router.post("/auth/logout-everywhere")
def logout_all(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user.token_version += 1
    db.commit()
    return {"message": "Logged out on all devices."}


class UserIn(BaseModel):
    username: str = Field(min_length=3, max_length=60, pattern=r"^[A-Za-z0-9_.@-]+$")
    full_name: str = ""
    password: str = Field(min_length=6)
    role: str
    permissions: list[str] = []
    customer_id: Optional[int] = None


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    permissions: Optional[list[str]] = None
    is_active: Optional[bool] = None
    new_password: Optional[str] = Field(default=None, min_length=6)


def _check_role(db, role, permissions, customer_id):
    if role not in ROLES:
        raise HTTPException(400, "Role must be owner, staff or customer.")
    bad = [p for p in permissions if p not in PERMISSIONS]
    if bad:
        raise HTTPException(400, f"Unknown permissions: {', '.join(bad)}")
    if role == "customer":
        if not customer_id or not db.get(Customer, customer_id):
            raise HTTPException(400, "Pick the customer this login belongs to.")


@router.get("/users")
def list_users(db: Session = Depends(get_db), _: User = Depends(require_owner)):
    return [user_dict(u) for u in db.execute(select(User).order_by(User.role, User.username)).scalars()]


@router.post("/users")
def create_user(body: UserIn, db: Session = Depends(get_db), owner: User = Depends(require_owner)):
    _check_role(db, body.role, body.permissions, body.customer_id)
    if db.execute(select(User).where(func.lower(User.username) == body.username.lower())).scalar_one_or_none():
        raise HTTPException(409, "That username is already taken.")
    u = User(username=body.username.lower(), full_name=body.full_name, password_hash=hash_password(body.password),
             role=body.role, permissions=body.permissions if body.role == "staff" else [],
             customer_id=body.customer_id if body.role == "customer" else None)
    db.add(u)
    db.flush()
    audit(db, owner, "user_created", "user", u.id, username=u.username, role=u.role)
    db.commit()
    return user_dict(u)


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, db: Session = Depends(get_db), owner: User = Depends(require_owner)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found.")
    if body.permissions is not None:
        _check_role(db, u.role, body.permissions, u.customer_id)
        u.permissions = body.permissions
        u.token_version += 1
    if body.full_name is not None:
        u.full_name = body.full_name
    if body.is_active is not None:
        if u.id == owner.id and not body.is_active:
            raise HTTPException(400, "You cannot switch off your own login.")
        u.is_active = body.is_active
        u.token_version += 1
    if body.new_password:
        u.password_hash = hash_password(body.new_password)
        u.token_version += 1
    audit(db, owner, "user_updated", "user", u.id, username=u.username,
          fields=[k for k, v in body.model_dump().items() if v is not None and k != "new_password"],
          password_reset=bool(body.new_password))
    db.commit()
    return user_dict(u)
