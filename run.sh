#!/usr/bin/env bash
# Luxe Laminate: start script for Linux / macOS
set -e
cd "$(dirname "$0")"
[ -d .venv ] || { python3 -m venv .venv; .venv/bin/pip install -r requirements.txt; }
if [ ! -f .env ]; then
  cp .env.example .env
  .venv/bin/python -c "import secrets,re,pathlib;p=pathlib.Path('.env');p.write_text(re.sub(r'SECRET_KEY=.*','SECRET_KEY='+secrets.token_urlsafe(48),p.read_text()))"
fi
.venv/bin/alembic upgrade head
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
