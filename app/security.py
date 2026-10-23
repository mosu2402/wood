import time
from datetime import datetime, timedelta, timezone
from threading import Lock

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import User

ALGO = "HS256"
_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    if len(password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters.")
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], hashed.encode())
    except ValueError:
        return False


def create_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "ver": user.token_version,
        "role": user.role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=settings.TOKEN_HOURS),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGO)


# --- simple brute-force protection on login --------------------------------
_fail: dict[str, list[float]] = {}
_fail_lock = Lock()
MAX_FAILS, WINDOW = 5, 300


def check_login_allowed(username: str):
    with _fail_lock:
        recent = [t for t in _fail.get(username, []) if time.time() - t < WINDOW]
        _fail[username] = recent
        if len(recent) >= MAX_FAILS:
            raise HTTPException(429, "Too many wrong attempts. Wait 5 minutes and try again.")


def record_login_failure(username: str):
    with _fail_lock:
        _fail.setdefault(username, []).append(time.time())


def clear_login_failures(username: str):
    with _fail_lock:
        _fail.pop(username, None)


# --- dependencies ------------------------------------------------------------
def get_current_user(cred: HTTPAuthorizationCredentials = Depends(_bearer),
                     db: Session = Depends(get_db)) -> User:
    if not cred:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please log in.")
    try:
        data = jwt.decode(cred.credentials, settings.SECRET_KEY, algorithms=[ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Your session has expired. Please log in again.")
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid session. Please log in again.")
    user = db.get(User, int(data["sub"]))
    if not user or not user.is_active or user.token_version != data.get("ver"):
        raise HTTPException(401, "Your session is no longer valid. Please log in again.")
    return user


def require_owner(user: User = Depends(get_current_user)) -> User:
    if user.role != "owner":
        raise HTTPException(403, "Only the owner can do this.")
    return user


def require(*perms: str):
    """Staff/owner with ALL the given permissions. Customers never pass."""
    def dep(user: User = Depends(get_current_user)) -> User:
        if user.role == "customer":
            raise HTTPException(403, "Not allowed.")
        missing = [p for p in perms if not user.can(p)]
        if missing:
            raise HTTPException(403, f"You don't have permission for this ({', '.join(missing)}). Ask the owner.")
        return user
    return dep


def require_any(*perms: str):
    def dep(user: User = Depends(get_current_user)) -> User:
        if user.role == "customer" or not any(user.can(p) for p in perms):
            raise HTTPException(403, "You don't have permission for this. Ask the owner.")
        return user
    return dep


def require_customer(user: User = Depends(get_current_user)) -> User:
    if user.role != "customer" or not user.customer_id:
        raise HTTPException(403, "This page is for customer accounts.")
    return user
