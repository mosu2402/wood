"""Backups. SQLite: consistent online copy via the sqlite3 backup API.
PostgreSQL: pg_dump (must be installed and on PATH)."""
import os
import shutil
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

from .config import settings


def create_backup(label: str = "manual") -> Path:
    settings.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if settings.is_sqlite:
        target = settings.BACKUP_DIR / f"luxe_{stamp}_{label}.db"
        src = sqlite3.connect(str(settings.sqlite_path))
        dst = sqlite3.connect(str(target))
        with dst:
            src.backup(dst)
        dst.close()
        src.close()
    else:
        target = settings.BACKUP_DIR / f"luxe_{stamp}_{label}.dump"
        url = settings.DATABASE_URL.replace("postgresql+psycopg2://", "postgresql://")
        subprocess.run(["pg_dump", "--format=custom", f"--file={target}", url], check=True)
    prune()
    return target


def list_backups() -> list[dict]:
    if not settings.BACKUP_DIR.exists():
        return []
    files = sorted((f for f in settings.BACKUP_DIR.iterdir() if f.suffix in (".db", ".dump")),
                   key=lambda f: f.stat().st_mtime, reverse=True)
    return [{"name": f.name, "size_mb": round(f.stat().st_size / 1_048_576, 2),
             "created": datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds")} for f in files]


def prune():
    files = sorted((f for f in settings.BACKUP_DIR.iterdir() if f.suffix in (".db", ".dump") and "_auto" in f.name),
                   key=lambda f: f.stat().st_mtime, reverse=True)
    for f in files[settings.BACKUP_KEEP:]:
        f.unlink(missing_ok=True)


def restore_backup(path: Path):
    """Run ONLY while the server is stopped (scripts/restore.py)."""
    if not path.exists():
        raise FileNotFoundError(path)
    if settings.is_sqlite:
        safety = create_backup("before_restore")
        db_path = settings.sqlite_path
        for ext in ("-wal", "-shm"):
            Path(str(db_path) + ext).unlink(missing_ok=True)
        shutil.copyfile(path, db_path)
        return safety
    url = settings.DATABASE_URL.replace("postgresql+psycopg2://", "postgresql://")
    safety = create_backup("before_restore")
    subprocess.run(["pg_restore", "--clean", "--if-exists", "--no-owner", f"--dbname={url}", str(path)], check=True)
    return safety
