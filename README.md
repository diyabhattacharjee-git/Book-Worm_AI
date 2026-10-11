# BookWorm — book discovery, explainable recommendations & a fair-price second-hand marketplace

A full-stack web app that helps readers find their next book, understand *why* it was recommended, organise their
reading, and buy or sell second-hand copies at reasonable prices. Its standout feature is a **multi-step
LangGraph workflow** that identifies the exact book, gathers listings, validates and de-duplicates them,
estimates a fair asking-price range from comparable listings, scores listing quality and ranks deals — showing
its evidence and refusing to guess when data is thin.

**Built to cost ₹0:** open-source stack, SQLite by default, no paid APIs. LLMs (Groq / Hugging Face / Ollama),
Google Books keys, eBay and sentence-transformer embeddings are all *optional*; without any of them the app runs
fully offline in a clearly labelled deterministic mode. (Running locally is free; public hosting and third-party
API quotas depend on providers' current free tiers.)

| | |
|---|---|
| Frontend | React 19, Vite, TypeScript, Tailwind CSS v4, React Router 7, Lucide, Vitest + Testing Library |
| Backend | Python 3.11, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, PyJWT, bcrypt, httpx, Pillow |
| ML / agents | scikit-learn (TF-IDF), NumPy/SciPy, LangGraph; optional Groq SDK, Hugging Face Hub, Ollama, sentence-transformers |
| Data | SQLite locally, PostgreSQL (Neon) in production; Cloudinary for photos; Open Library + Google Books metadata; optional eBay Browse API |
| Tests | 92 backend tests (pytest, SQLite and PostgreSQL) · 13 frontend tests (Vitest) · all run offline |

## Quick start

```powershell
./scripts/setup.ps1          # Windows   (macOS/Linux: ./scripts/setup.sh)
```

Then, in two terminals:

```bash
cd backend  && .venv/Scripts/uvicorn app.main:app --reload --port 8000   # (.venv/bin/... on macOS/Linux)
cd frontend && npm run dev                                                # http://localhost:5173
```

The setup script installs dependencies, creates `backend/.env` with a random secret, applies migrations and loads
**real data only**: 70 books whose metadata (descriptions, page counts, publishers, covers, Open Library ratings)
was fetched from Open Library / Google Books. No users, ratings, reviews or listings are invented — those come
only from people using the app, so the marketplace and BookWorm ratings start empty.

Create an administrator with `python -m app.cli create-admin --email you@example.com --username yourname`
(there is no way to become admin through the website).

### Accounts & sign-in

* **Sign up:** enter your email → a 6-digit one-time code is emailed → enter it → choose a username, display name and password.
* **Sign in:** username *or* email + password, or **“Email me a sign-in code”** (passwordless), or **Continue with Google**.
* **Forgot password:** emailed code → new password. Google-created accounts can add a password the same way.

Email codes need SMTP settings (a free Gmail app password works; see `backend/.env.example`). Until SMTP is set,
development prints codes to the backend log. Google sign-in appears once `GOOGLE_CLIENT_ID` is set.
Test both with `python -m app.cli check-email --to you@example.com` and `python -m app.cli check-llm`.

Full instructions, the free **Vercel + Neon + Cloudinary** deployment and a troubleshooting table: **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**.

## Feature checklist

| # | Feature | Status | Notes |
|---|---|---|---|
| 1 | Smart discovery: search by title/author/ISBN/genre/publisher/keyword; filters (genre, author, language, year, rating, pages, format, used availability); 7 sorts; pagination | ✅ | Import missing books by ISBN from Open Library / Google Books |
| 2 | Personalised home feed with optional, skippable onboarding | ✅ | Save / dismiss / rate feedback adapts results |
| 3 | Natural-language search with refinements (“shorter”, “more technical”, “cheaper copies”) | ✅ | TF-IDF semantic + keyword + rating; embeddings optional |
| 4 | Ratings & reviews: one per user per book, edit/delete, helpful votes, reports, moderation states | ✅ | App ratings shown separately from external provider ratings |
| 5 | Bookshelf (4 statuses), progress (no % when pages unknown), dates, custom lists, goals, history, recently viewed | ✅ | |
| 6 | Hybrid recommender: content (fitted TF-IDF), item-item CF with reliability rule, Bayesian popularity, preferences, MMR diversity | ✅ | Weights configurable via env |
| 7 | Evidence-based explanations | ✅ | Built from contributing signals only |
| 8 | Cold start for users and new books | ✅ | Mode is labelled in the UI |
| 9 | Admin recommendation dashboard: P@K, R@K, NDCG@K, coverage, diversity, popularity concentration, cold-start | ✅ | Temporal hold-out on real users only; shows “Not enough evaluation data” until enough readers exist |
| 10 | Adaptive recs, preference editing, reset learned preferences, delete history | ✅ | Recency decay, on-demand refit |
| 11 | Conversational assistant with tools (search, recommend, similar, compare, used copies, save, plans), multi-turn context | ✅ | Rules first; optional validated LLM routing/phrasing |
| 12 | Book comparison with evidence-based advice, “Not available” for missing fields | ✅ | |
| 13 | Reading-plan generator with progress, rescheduling and .ics export | ✅ | No server reminders: export to your own calendar |
| 14 | New-copy offers via provider adapters | ✅ / ⚠️ | Only real prices returned by sources (Google Play Books prices, eBay “new”). Often none are available; the page says so |
| 15 | Used-book search across community + eBay | ✅ / ⚠️ | eBay requires your own free developer keys; otherwise community only, clearly stated |
| 16 | Accounts: email-OTP sign-up, username/email + password, email-code sign-in, Google sign-in, password reset; seller profiles, avatar, privacy controls | ✅ | Email needs SMTP; Google needs a client ID |
| 17 | Sell a book: create/edit/deactivate/reactivate/mark sold/delete, up to 6 validated photos | ✅ | Local disk storage |
| 18 | Buyer experience: browse/filter/sort, favourites, private inquiries & replies, reports, same-book comparison | ✅ | No payments by design |
| 19 | Price intelligence with documented confidence and refusal on thin data | ✅ | Asking prices, not sale prices |
| 20 | Listing validation, dedup, quality scoring, deal ranking | ✅ | Suspicious bargains not auto-ranked first |
| 21–28 | LangGraph agents: intent, identification, retrieval, validation, price, quality, ranking, explanation | ✅ | Typed state, conditional routing, per-node timing, streamed status |
| 29 | Auth & authorisation (user/seller/admin), account deletion | ✅ | Every permission enforced server-side |
| 30 | Admin dashboard & moderation queue with audit log | ✅ | |
| 31 | Security & privacy | ✅ | See [docs/SECURITY.md](docs/SECURITY.md) incl. limitations |
| 32 | Logging, migrations, caching, timeouts, health check, tests, docs | ✅ | |

All 24 requested pages exist (landing, discover, book detail, for-you, smart search, assistant, compare, reading
plans, new-copy offers, marketplace, used-book search, listing detail, sell, seller dashboard, seller profile,
saved, bookshelf, history & goals, settings, login, register, admin, moderation, 404).

## Project structure

```
backend/
  app/
    api/            routers: auth, books, reading, recommendations, marketplace, intelligence, assistant, admin
    agents/         used_book_graph (LangGraph), intent, assistant, llm provider layer
    marketplace/    providers, identify, validate, pricing, quality, ranking, types
    recommender/    signals, content, collaborative, popularity, hybrid, service, evaluation
    integrations/   http cache/timeouts, Open Library + Google Books, eBay
    services/ repositories/ schemas/ models/ security/ core/ db/
    cli.py          init-db, seed, create-admin, promote-admin, evaluate
  alembic/  tests/  requirements.txt  requirements-ml.txt (optional)  .env.example
frontend/
  src/ pages/ components/ layouts/ contexts/ hooks/ services/ types/ utils/ test/
docs/  ARCHITECTURE.md  RECOMMENDER.md  MARKETPLACE_INTELLIGENCE.md  SECURITY.md  DEPLOYMENT.md  API.md
scripts/  setup.ps1  setup.sh
vercel.json  .vercelignore  (Vercel deployment)
docker-compose.yml (optional)
```

## Running tests

```bash
cd backend  && pip install -r requirements-dev.txt && .venv/Scripts/python -m pytest -q   # 92 tests, temporary DB, no network
# Against Postgres: set TEST_DATABASE_URL=postgresql://... (an empty, disposable database)
cd frontend && npm test && npm run typecheck && npm run build
```

## Configuration

Everything lives in `backend/.env` (see the commented [backend/.env.example](backend/.env.example)). Key options:
`APP_SECRET_KEY`, `DATABASE_URL`, `SMTP_*`, `GOOGLE_CLIENT_ID`, `GROQ_API_KEY`/`GROQ_MODEL`, `HF_TOKEN`/`HF_MODEL`, `OLLAMA_BASE_URL`/`OLLAMA_MODEL`,
`GOOGLE_BOOKS_API_KEY`, `EBAY_CLIENT_ID`/`EBAY_CLIENT_SECRET`/`EBAY_ENVIRONMENT`, `FX_RATES_JSON`,
`EMBEDDINGS_BACKEND`, `REC_WEIGHT_*`, `FRONTEND_DIST`. Missing optional keys only disable that integration;
`/api/health` and `/api/marketplace/providers/status` report what is active.

## Honest limitations

* **Starts empty by design.** With no invented data, a fresh install has no listings, no BookWorm ratings and no
  price estimates (“Insufficient data”) until real people list and rate books; recommendations start from the
  real Open Library ratings and your stated preferences.
* **Synthetic data exists only in the test suite** (`backend/tests/factories.py`) to exercise the recommender and
  pricing logic; it is never loaded into the app.
* **New-copy prices:** free metadata APIs rarely expose retail prices, so the offers page is often empty apart from
  reference links. No prices are scraped or invented.
* **eBay** needs your own keys and Browse API access; India-specific availability/shipping is never assumed.
* **Google Books** without a key shares a public quota that is frequently exhausted (Open Library still works).
* **Free hosting** typically sleeps when idle and wipes local disk (SQLite file, uploaded photos). See DEPLOYMENT.md.
* Rate limiting is in-memory per process; no email verification or password-reset email (no free mail service assumed).

## Documentation

* [Architecture & data model](docs/ARCHITECTURE.md) (ER diagram, schema decisions)
* [Recommendation engine](docs/RECOMMENDER.md) (formulas, weights, evaluation method)
* [Second-hand intelligence](docs/MARKETPLACE_INTELLIGENCE.md) (graph, pricing/confidence formulas, ranking)
* [Security & privacy](docs/SECURITY.md)
* [Deployment & troubleshooting](docs/DEPLOYMENT.md)
* [API reference](docs/API.md) — the interactive `/api/docs` page is off unless `ENABLE_API_DOCS=true` (developers only)
