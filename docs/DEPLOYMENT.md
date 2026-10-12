# Running and deploying for ₹0

The software needs no paid service. Running it costs nothing on your own computer. Hosting it publicly depends
on free tiers that providers can change at any time, so always check current terms before relying on one.
External APIs (Groq, Hugging Face, Google Books, eBay) have their own quotas and may stop working when
exhausted; the app then falls back automatically.

## 1. Local (recommended, always free)

Prerequisites: Python 3.11+, Node.js 20+ (tested with 22), Git.

```bash
# Windows PowerShell:  ./scripts/setup.ps1      macOS/Linux:  ./scripts/setup.sh
```

or manually:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env            # macOS/Linux: cp .env.example .env  (then set APP_SECRET_KEY)
python -m app.cli seed            # migrations + real book catalogue (no fake users, ratings or listings)
python -m app.cli create-admin --email you@example.com --username yourname   # prompts for a password (min 12 chars)
uvicorn app.main:app --reload --port 8000

cd ../frontend
npm install
npm run dev                       # http://localhost:5173  (proxies /api and /uploads to :8000)
```

Health: http://localhost:8000/api/health. Developer API docs: set `ENABLE_API_DOCS=true`, then http://localhost:8000/api/docs.

### Single-process mode (no separate frontend server)

```bash
cd frontend && npm run build
cd ../backend && set FRONTEND_DIST=../frontend/dist   # or put FRONTEND_DIST in .env
uvicorn app.main:app --port 8000                      # serves the app at http://localhost:8000
```

### Email codes and Google sign-in (free)

* **Email (required for real sign-ups):** with a Gmail account, enable 2-Step Verification, create an App Password at
  myaccount.google.com/apppasswords and set `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_USERNAME`,
  `SMTP_PASSWORD` (the app password) and `SMTP_FROM`. Check with `python -m app.cli check-email --to you@example.com`.
  Brevo's free SMTP relay also works. In development without SMTP the codes are printed in the backend log.
* **Google sign-in:** console.cloud.google.com → APIs & Services → Credentials → Create OAuth client ID (Web
  application). Add `http://localhost:5173` (and your real site) to *Authorized JavaScript origins*, then set
  `GOOGLE_CLIENT_ID`. The “Continue with Google” button appears automatically.

### Optional add-ons (still free)

* **Local LLM:** install [Ollama](https://ollama.com), `ollama pull llama3.2:3b`, then set `OLLAMA_MODEL=llama3.2:3b`.
  Needs roughly 4 GB+ free RAM.
* **Groq:** create a key at console.groq.com → API Keys, set `GROQ_API_KEY` (and optionally `GROQ_MODEL`, default
  `llama-3.1-8b-instant`), restart the backend and run `python -m app.cli check-llm`. Free-tier limits depend on your account.
* **Local embeddings:** `pip install -r requirements-ml.txt` (~1 GB with PyTorch) and `EMBEDDINGS_BACKEND=sentence-transformers`.
* **Google Books key** avoids the shared anonymous quota. **eBay** keys enable external listings.

## 2. Vercel + Neon (recommended free deployment)

The repository is ready for Vercel: `vercel.json` defines two **Services** (Vercel's monorepo feature, beta, available
on the free Hobby plan) on one domain: `frontend/` (Vite build) and `backend/` (FastAPI, entry point `app.main:app`).
Requests to `/api/...` go to FastAPI with the path unchanged; everything else is the React app.
Vercel's filesystem is temporary, so data lives in **Neon** (Postgres). Listing photos and avatars are stored in
the same database automatically (`IMAGE_STORAGE=auto` detects Vercel); they are re-encoded to at most 1600 px, so
the free 0.5 GB comfortably holds a few thousand photos. Cloudinary is optional.

1. **Neon** (neon.com, free): create a project → copy the connection string
   (`postgresql://…?sslmode=require`). Prefer the *pooled* connection string.
2. **Create the tables and load the real book catalogue** from your computer, once:
   ```powershell
   cd backend
   $env:DATABASE_URL="<neon connection string>"; .venv\Scripts\python -m app.cli seed
   $env:DATABASE_URL="<neon connection string>"; .venv\Scripts\python -m app.cli create-admin --email you@example.com --username yourname
   ```
   Run `init-db` the same way after future schema changes.
3. **Cloudinary** (optional; cloudinary.com, free, no card): Dashboard → copy the *API environment variable*
   (`cloudinary://<key>:<secret>@<cloud_name>`).
4. **Vercel** (vercel.com, sign in with GitHub, Hobby plan): *Add New → Project* → import the GitHub repository.
   Leave the root directory as the repository root (it reads `vercel.json`). Add these Environment Variables:

   | Variable | Value |
   |---|---|
   | `APP_ENV` | `production` |
   | `APP_SECRET_KEY` | a new random value: `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
   | `DATABASE_URL` | Neon connection string |
   | `CLOUDINARY_URL` | optional: Cloudinary API environment variable |
   | `FRONTEND_ORIGIN` | your site, e.g. `https://book-worm-ai.vercel.app` |
   | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM` | same as local (Vercel allows ports 587/465) |
   | `GOOGLE_CLIENT_ID` | same as local |
   | `GROQ_API_KEY`, `GROQ_MODEL` | same as local |
   | `HF_TOKEN`, `HF_MODEL` | optional |
   | `GOOGLE_BOOKS_API_KEY` | optional |

   Then **Deploy**. Every `git push` to `main` redeploys automatically.
5. **Google sign-in:** in Google Cloud Console → Credentials → your OAuth client, add the Vercel URL
   (e.g. `https://book-worm-ai.vercel.app`) to *Authorized JavaScript origins*.

Free-plan behaviour to expect: pages are served from Vercel's CDN; the API starts on demand, so the first request
after a quiet period can take a few seconds. In-memory rate limits and caches reset when a new instance starts.
Hobby is intended for personal, non-commercial projects; exceeding its monthly allowance pauses the project rather
than charging you. Neon's free plan has 0.5 GB storage and pauses compute when idle (it wakes on the next query).

## 3. Other free-tier hosting (verify current terms first)

The simplest public setup is **one web service** in single-process mode:

1. Build command: `cd frontend && npm ci && npm run build && cd ../backend && pip install -r requirements.txt`
2. Start command: `cd backend && python -m app.cli init-db && uvicorn app.main:app --host 0.0.0.0 --port $PORT`
3. Environment: `APP_ENV=production`, `APP_SECRET_KEY=<random 48+ chars>`, `FRONTEND_DIST=../frontend/dist`,
   `FRONTEND_ORIGIN=https://<your-app-domain>`, optionally `DATABASE_URL` for PostgreSQL.
4. Load the catalogue: `python -m app.cli seed`. Set SMTP (required in production for sign-up codes) and optionally `GOOGLE_CLIENT_ID`.

Things free hosts commonly do (check yours):

* **Sleep after inactivity** — the first request after a pause can take 30–60 s.
* **Ephemeral disk** — SQLite files and uploaded images are wiped on redeploy/restart. Use a free PostgreSQL
  instance (paste its `postgresql://...` URL as `DATABASE_URL`) and `IMAGE_STORAGE=database` (or `CLOUDINARY_URL`) for photos.
* **Outbound email** — Render's free tier blocks SMTP ports 25/465/587; Vercel allows 465/587.
* **No background workers** — the app needs none: recommendations refit on demand, caches expire lazily.
* **Limited RAM** — keep `EMBEDDINGS_BACKEND=tfidf`; don't run Ollama on a free host.

Alternatively host the static frontend (`frontend/dist`) on a static host and the API elsewhere. Then set
`VITE_API_BASE=https://api.example.com` at build time, add the frontend origin to `FRONTEND_ORIGIN`, and note that
cross-site cookies require HTTPS on both and may be blocked by some browsers; same-origin single-service mode avoids this.

## 4. Docker (optional)

`docker compose up` runs the backend (port 8000) and the Vite dev server (port 5173) with the code mounted.
Docker is not required for anything.

## 5. Troubleshooting

| Symptom | Fix |
|---|---|
| “Can’t reach the server” in the UI | Start the backend on port 8000, or set `VITE_BACKEND_URL` for the dev proxy. |
| Logged out after restarting the backend | Set `APP_SECRET_KEY` in `backend/.env` (without it a temporary key is generated). |
| 403 “Missing X-Requested-With header” | Call the API through the frontend client or send that header (CSRF protection). |
| 429 Too many requests | Wait a minute; limits are per IP and in memory. |
| Book covers show the placeholder | No cover exists on Open Library, or you're offline; that's expected. |
| Google Books “rate limited” in notes | The keyless shared quota is exhausted; set `GOOGLE_BOOKS_API_KEY` or ignore it (Open Library is used). |
| eBay shows “not configured” / “access denied” | Add keys; production keys need Browse API access; sandbox returns only test items. |
| Assistant says “deterministic” | No LLM configured or all are cooling down after errors; everything still works. Check `/api/marketplace/providers/status`. |
| “Not enough evaluation data” in admin | Expected until ≥ 5 real users have rated or finished ≥ 5 books. |
| No verification email arrives | Set the SMTP settings and run `python -m app.cli check-email --to you@example.com`; check spam. In development without SMTP the code is in the backend log. |
| “Email delivery isn't available” on sign-up | Production without SMTP configured; add the SMTP settings. |
| No “Continue with Google” button | Set `GOOGLE_CLIENT_ID` and add your site to the client's Authorized JavaScript origins. |
| `alembic` errors after editing models | `alembic revision --autogenerate -m "msg"` then `python -m app.cli init-db`. |
| Want a clean start | Stop the server, delete `backend/book_platform.db*` and `backend/uploads/*`, run `python -m app.cli seed`. |
| Assistant never uses Groq | Run `python -m app.cli check-llm`; it prints the provider error (e.g. invalid key or rate limit). |
| Vercel build fails on the Python service | Check the build log; the API bundle must stay under 500 MB (`pandas` and dev tools are deliberately not in `requirements.txt`). |
| Photos disappear after deploys | Set `IMAGE_STORAGE=database` (automatic on Vercel) or `CLOUDINARY_URL`. |
| Port already in use | Another server is running; stop it or use `--port 8001` (and `VITE_BACKEND_URL`). |
