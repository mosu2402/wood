from datetime import date
from typing import Optional

from fastapi import Query
from fastapi.responses import Response


class Page:
    def __init__(self, page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=500)):
        self.page, self.size = page, size

    @property
    def offset(self):
        return (self.page - 1) * self.size


def paged(items, total, page: Page):
    return {"items": items, "total": total, "page": page.page, "size": page.size,
            "pages": max(1, -(-total // page.size))}


def pdf_response(content: bytes, filename: str) -> Response:
    return Response(content, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{filename}"'})


def file_response(content: bytes, filename: str, media: str) -> Response:
    return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def opt_date(v: Optional[str]) -> Optional[date]:
    return date.fromisoformat(v) if v else None
