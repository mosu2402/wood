from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ..database import get_db
from ..deps import file_response
from ..importer import FIELDS, commit_batch, parse_file, template_xlsx, validate_rows
from ..models import ImportBatch, User
from ..security import require
from ..services import BizError, audit

router = APIRouter(prefix="/api/imports", tags=["inventory import"])
perm = require("inventory.import")
MAX_BYTES = 40 * 1024 * 1024


def _view(b: ImportBatch, only_errors: bool = False, page: int = 1, size: int = 100) -> dict:
    rows = b.rows
    if only_errors:
        rows = [r for r in rows if r["errors"] or r["warnings"]]
    start = (page - 1) * size
    return {"id": b.id, "filename": b.filename, "mode": b.mode, "status": b.status, "summary": b.summary,
            "fields": FIELDS, "rows": rows[start:start + size], "rows_total": len(rows), "page": page, "size": size,
            "created_at": b.created_at.isoformat()}


@router.get("/template")
def template(_: User = Depends(perm)):
    return file_response(template_xlsx(), "luxe_inventory_template.xlsx",
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.get("")
def list_batches(db: Session = Depends(get_db), _: User = Depends(perm)):
    rows = db.execute(select(ImportBatch.id, ImportBatch.filename, ImportBatch.mode, ImportBatch.status,
                             ImportBatch.summary, ImportBatch.created_at).order_by(ImportBatch.id.desc()).limit(50)).all()
    return [{"id": r.id, "filename": r.filename, "mode": r.mode, "status": r.status, "summary": r.summary,
             "created_at": r.created_at.isoformat()} for r in rows]


@router.post("")
async def upload(file: UploadFile = File(...), mode: str = Form("create"), db: Session = Depends(get_db),
                 user: User = Depends(perm)):
    if mode not in ("create", "upsert"):
        raise HTTPException(400, "Mode must be 'create' or 'upsert'.")
    content = await file.read()
    if len(content) > MAX_BYTES:
        raise HTTPException(413, "File is larger than 40 MB. Split it into smaller files.")
    rows, unknown = parse_file(file.filename or "upload", content)
    summary = validate_rows(db, rows, mode)
    summary["ignored_columns"] = unknown
    b = ImportBatch(filename=file.filename or "upload", mode=mode, rows=rows, summary=summary, created_by=user.id)
    db.add(b)
    db.flush()
    audit(db, user, "import_uploaded", "import", b.id, filename=b.filename, rows=len(rows), errors=summary["errors"])
    db.commit()
    return _view(b, only_errors=True)


@router.get("/{batch_id}")
def get_batch(batch_id: int, only_errors: bool = False, page: int = 1, size: int = 100,
              db: Session = Depends(get_db), _: User = Depends(perm)):
    b = db.get(ImportBatch, batch_id)
    if not b:
        raise HTTPException(404, "Import not found.")
    return _view(b, only_errors, max(page, 1), min(max(size, 1), 500))


class RowFix(BaseModel):
    data: dict
    remove: bool = False


@router.put("/{batch_id}/rows/{row_no}")
def fix_row(batch_id: int, row_no: int, body: RowFix, db: Session = Depends(get_db), user: User = Depends(perm)):
    b = db.get(ImportBatch, batch_id)
    if not b or b.status != "PREVIEW":
        raise HTTPException(400, "This import can no longer be changed.")
    rows = b.rows
    idx = next((i for i, r in enumerate(rows) if r["row"] == row_no), None)
    if idx is None:
        raise HTTPException(404, "Row not found.")
    if body.remove:
        rows.pop(idx)
    else:
        rows[idx]["data"] = {f: str(body.data.get(f, rows[idx]["data"].get(f, "")) or "").strip() for f in FIELDS}
    summary = validate_rows(db, rows, b.mode)
    summary["ignored_columns"] = (b.summary or {}).get("ignored_columns", [])
    b.rows, b.summary = rows, summary
    flag_modified(b, "rows")
    flag_modified(b, "summary")
    db.commit()
    row = next((r for r in rows if r["row"] == row_no), None)
    return {"summary": summary, "row": row}


class CommitIn(BaseModel):
    skip_errors: bool = False


@router.post("/{batch_id}/commit")
def commit(batch_id: int, body: CommitIn, db: Session = Depends(get_db), user: User = Depends(perm)):
    b = db.get(ImportBatch, batch_id)
    if not b or b.status != "PREVIEW":
        raise HTTPException(400, "This import was already saved or discarded.")
    try:
        summary = commit_batch(db, b, user, body.skip_errors)
        flag_modified(b, "rows")
        db.commit()
    except BizError:
        db.rollback()
        raise
    return {"message": f"Imported: {summary['created']} new, {summary['updated']} updated, {summary['skipped']} skipped.",
            "summary": summary}


@router.post("/{batch_id}/discard")
def discard(batch_id: int, db: Session = Depends(get_db), user: User = Depends(perm)):
    b = db.get(ImportBatch, batch_id)
    if not b or b.status != "PREVIEW":
        raise HTTPException(400, "Nothing to discard.")
    b.status = "DISCARDED"
    b.rows = []
    audit(db, user, "import_discarded", "import", b.id)
    db.commit()
    return {"message": "Import discarded."}
