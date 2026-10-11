# Security & privacy

These are practical protections for a student project, not a guarantee that the app is fully secure.

## Implemented

| Area | Measure |
|---|---|
| Passwords | bcrypt (cost 12) over a SHA-256 pre-hash (so long passphrases aren't truncated at 72 bytes). Never stored or logged in plain text. Login runs one bcrypt check even for unknown emails to reduce user enumeration by timing. |
| Sign-up & codes | Accounts are created only after proving control of the email with a 6-digit one-time code (from `secrets`, 10-minute expiry, max 5 guesses, only an HMAC-SHA256 stored, 60 s resend cooldown and 6/hour per email, plus per-IP limits). Sign-up start never reveals whether an email is registered (an existing owner gets a notice instead). The verified step yields a 30-minute single-use token required to set the username/password. The same code mechanism powers passwordless sign-in and password reset (reset signs out all other sessions). |
| Google sign-in | ID tokens are verified server-side with Google's public keys (`google-auth`): signature, audience = `GOOGLE_CLIENT_ID`, issuer and `email_verified`. An existing account with the same verified email is linked. |
| Sessions | Signed JWT (HS256) in an `HttpOnly`, `SameSite=Lax` cookie (`Secure` when `APP_ENV=production`), 7-day expiry. A per-user `token_version` invalidates all sessions on logout-everywhere, password change, suspension or role change. |
| Secret | `APP_SECRET_KEY` (≥ 32 chars) is required in production; the app refuses to start without it. Development without a key uses a random per-process secret. |
| CSRF | SameSite cookie plus a required `X-Requested-With` header on every non-GET `/api` request (cross-site forms can't set it without a CORS preflight, which only `FRONTEND_ORIGIN` passes). |
| CORS | Explicit allow-list from `FRONTEND_ORIGIN`, credentials allowed only for those origins. |
| Authorisation | All checks on the server: ownership on listings, images, reviews, shelf entries, lists, plans, conversations and inquiry replies; admin routes require `role=admin`. Public registration can't set a role; admins are created only via the CLI. Other users' private records return 404. |
| Input validation | Pydantic schemas with length/range limits, ISBN checksum validation, enum checks; control characters stripped from free text; SQLAlchemy parameterised queries only. |
| Rate limiting | In-memory sliding window per IP on login, registration, password change, uploads, reviews, reports, inquiries, imports, search, assistant and used-book workflows. |
| Uploads | Size checked while streaming (`MAX_UPLOAD_MB`), content decoded by Pillow (declared type ignored), JPEG/PNG/WEBP only, decompression-bomb limit, re-encoded (strips EXIF incl. GPS and trailing data), random file names, path-traversal-safe deletion, served with `nosniff` and a sandboxing CSP. |
| API docs | `/api/docs`, `/api/redoc` and `/api/openapi.json` are disabled unless `ENABLE_API_DOCS=true`. |
| Errors & logs | Unhandled exceptions return a generic 500; stack traces go to logs only. JSON logs redact keys named password/token/secret/cookie/authorization; API keys are never logged. |
| Headers | `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`. |
| External data | Treated as untrusted: provider URLs must be HTTPS, text is length-limited and control-stripped, rendered by React (escaped). |
| Prompt injection | Listing/book text never reaches the assistant's tool router. LLMs get structured facts as data with no tools in that step; outputs are rejected if they introduce numbers, quoted titles or links not present in the facts. Write tools (save, create plan) require explicit intent in the current user message, a logged-in user, and can't be selected by the LLM router. Client-supplied assistant context is sanitised to known keys and integer IDs. |
| Privacy | Email is never shown publicly; location is approximate and hidden unless the user opts in; buyer–seller contact happens through private inquiries; account deletion removes personal data and uploaded files (reports filed are anonymised); users can reset learned preferences or delete reading history. No sensitive attributes are inferred. |

## Known limitations

* Rate limits are per process and in memory (reset on restart; not shared across workers).
* No two-factor authentication. Email codes are only as secure as the user's mailbox.
* In development without SMTP, codes are written to the server log (never in production).
* Uploaded images are stored on local disk; on hosts with ephemeral storage they disappear on redeploy.
* Sessions are stateless JWTs: individual tokens can't be revoked except via `token_version` (all sessions at once).
* No antivirus scanning of uploads (images are re-encoded, which neutralises most embedded payloads).
* The marketplace does not verify sellers, books or transactions, and does not handle payments.
* Dependencies should be updated regularly (`pip list --outdated`, `npm outdated`, `npm audit`).
