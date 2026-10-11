#!/usr/bin/env bash
# One-time local setup on macOS/Linux. Run from the repository root:  ./scripts/setup.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "== Backend =="
cd "$ROOT/backend"
[ -d .venv ] || python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip >/dev/null
./.venv/bin/python -m pip install -r requirements.txt
if [ ! -f .env ]; then
  SECRET="$(./.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(48))')"
  sed "s|^APP_SECRET_KEY=\$|APP_SECRET_KEY=${SECRET}|" .env.example > .env
  echo "Created backend/.env with a random APP_SECRET_KEY"
fi
./.venv/bin/python -m app.cli seed

echo "== Frontend =="
cd "$ROOT/frontend"
npm install

cat <<'MSG'

Done. Start the app in two terminals:
  cd backend  && ./.venv/bin/uvicorn app.main:app --reload --port 8000
  cd frontend && npm run dev        ->  http://localhost:5173
Optional admin:  cd backend && ./.venv/bin/python -m app.cli create-admin --email you@example.com --username yourname
MSG
