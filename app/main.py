import logging
import mimetypes

# Windows registry sometimes maps .js to text/plain; browsers then refuse to run it.
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError

from .config import BASE_DIR, settings
from .routers import admin, auth, customers, factory, imports, invoices, payments, portal, products, reports, stock
from .services import BizError

log = logging.getLogger("luxe")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Luxe Laminate Management System", version="1.0.0")

if settings.SECRET_KEY in ("dev-only-change-me", "change-this-to-a-long-random-string"):
    log.warning("SECRET_KEY is not set. Set a long random SECRET_KEY in .env before real use.")


@app.exception_handler(BizError)
async def biz_error(_: Request, exc: BizError):
    return JSONResponse({"detail": exc.message, **exc.extra}, status_code=exc.status)


@app.exception_handler(IntegrityError)
async def integrity_error(_: Request, exc: IntegrityError):
    log.warning("Integrity error: %s", exc.orig)
    return JSONResponse({"detail": "This record clashes with an existing one (duplicate number or a double "
                                   "submit). Refresh and check before trying again."}, status_code=409)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    msgs = []
    for e in exc.errors():
        field = ".".join(str(x) for x in e.get("loc", [])[1:]) or "input"
        msgs.append(f"{field}: {e.get('msg')}")
    return JSONResponse({"detail": "Please check: " + "; ".join(msgs[:5])}, status_code=422)


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    log.exception("Unhandled error")
    return JSONResponse({"detail": "Something went wrong on the server. Nothing was saved. "
                                   "Try again, and tell the owner if it repeats."}, status_code=500)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    if request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    elif request.url.path == "/" or request.url.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"  # browser must check for a newer file every time
    return resp


for r in (auth, products, imports, customers, invoices, payments, factory, stock, reports, admin, portal):
    app.include_router(r.router)


@app.get("/api/health")
def health():
    return {"ok": True}


app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


APP_VERSION = "2026-10-23"


@app.get("/")
def index():
    """Serve the page with versioned links so browsers never keep an old app.js / styles.css."""
    static = BASE_DIR / "static"
    v = str(int(max((static / "app.js").stat().st_mtime, (static / "styles.css").stat().st_mtime)))
    html = (static / "index.html").read_text(encoding="utf-8")
    html = html.replace("/static/app.js", f"/static/app.js?v={v}").replace("/static/styles.css", f"/static/styles.css?v={v}")
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})
