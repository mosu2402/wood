from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..backup import create_backup, list_backups
from ..config import settings
from ..database import get_db
from ..deps import Page, opt_date, paged
from ..models import AuditLog, User
from ..security import require_owner
from ..services import audit

router = APIRouter(prefix="/api/admin", tags=["owner tools"])


@router.get("/audit")
def audit_log(action: str = "", entity: str = "", username: str = "", date_from: Optional[str] = None,
              date_to: Optional[str] = None, page: Page = Depends(), db: Session = Depends(get_db),
              _: User = Depends(require_owner)):
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action.like(f"%{action}%"))
    if entity:
        stmt = stmt.where(AuditLog.entity == entity)
    if username:
        stmt = stmt.where(AuditLog.username == username.lower())
    if date_from:
        stmt = stmt.where(func.date(AuditLog.created_at) >= opt_date(date_from))
    if date_to:
        stmt = stmt.where(func.date(AuditLog.created_at) <= opt_date(date_to))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(stmt.order_by(AuditLog.id.desc()).offset(page.offset).limit(page.size)).scalars().all()
    return paged([{"id": a.id, "at": a.created_at.isoformat(), "user": a.username, "action": a.action,
                   "entity": a.entity, "entity_id": a.entity_id, "details": a.details} for a in rows], total, page)


@router.get("/backups")
def backups(_: User = Depends(require_owner)):
    return {"database": "SQLite" if settings.is_sqlite else "PostgreSQL", "folder": str(settings.BACKUP_DIR),
            "files": list_backups()}


@router.post("/backups")
def make_backup(db: Session = Depends(get_db), owner: User = Depends(require_owner)):
    try:
        path = create_backup("manual")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"Backup failed: {e}")
    audit(db, owner, "backup_created", "backup", None, file=path.name)
    db.commit()
    return {"message": f"Backup saved: {path.name}", "name": path.name}


@router.get("/backups/{name}")
def download_backup(name: str, _: User = Depends(require_owner)):
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, "Invalid file name.")
    path = settings.BACKUP_DIR / name
    if not path.exists():
        raise HTTPException(404, "Backup not found.")
    return FileResponse(path, filename=name, media_type="application/octet-stream")
