# API reference

Generated from the FastAPI OpenAPI schema. The interactive docs page is disabled for end users; developers can
set `ENABLE_API_DOCS=true` to serve it at `/api/docs`.

Conventions:

* JSON in and out. Errors: `{"detail": "..."}`; validation errors (422) add `errors: [{field, message}]`.
* Auth: HttpOnly session cookie `bw_session`, set after sign-up, password/code login or Google sign-in. Every non-GET request must send `X-Requested-With: XMLHttpRequest` (CSRF guard).
* Sign-up: `POST /api/auth/signup/start` (email) → `POST /api/auth/signup/verify` (6-digit code → verification_token) → `POST /api/auth/signup/complete` (token, username, display_name, password).
* Lists are paginated with `page` and `page_size` and return `{items, total, page, page_size}` where noted.
* 401 = not logged in, 403 = not allowed (ownership/role), 404 = missing or not yours, 409 = conflict/duplicate, 429 = rate limited.

## Auth & Users

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/auth/config` | Sign-in options the frontend should offer. |
| `POST` | `/api/auth/google` | Sign in (or sign up) with a Google ID token from Google Identity Services. |
| `POST` | `/api/auth/login` | Log in with username or email, plus password. |
| `POST` | `/api/auth/login/code/start` | Passwordless sign-in: email a one-time code (only sent if the account exists). |
| `POST` | `/api/auth/login/code/verify` | Login Code Verify |
| `POST` | `/api/auth/logout` | Logout |
| `POST` | `/api/auth/password/forgot` | Email a code to set a new password (also how Google-only accounts add a password). |
| `POST` | `/api/auth/password/reset` | Password Reset |
| `GET` | `/api/auth/session` | Session probe for the frontend: 200 with `user: null` when logged out (no 401 noise). |
| `POST` | `/api/auth/signup/complete` | Step 3: choose a username, display name and password; creates the account and signs in. |
| `POST` | `/api/auth/signup/start` | Step 1: email a 6-digit verification code. |
| `POST` | `/api/auth/signup/verify` | Step 2: check the code and return a short-lived token for step 3. |
| `GET` | `/api/auth/username-available` | Username Available |
| `DELETE` | `/api/users/me` | Permanently delete the account. |
| `GET` | `/api/users/me` | Me |
| `PATCH` | `/api/users/me` | Update Me |
| `DELETE` | `/api/users/me/avatar` | Delete Avatar |
| `POST` | `/api/users/me/avatar` | Upload Avatar |
| `POST` | `/api/users/me/password` | Change Password |
| `PATCH` | `/api/users/me/preferences` | Update Preferences |
| `DELETE` | `/api/users/me/reading-history` | Remove bookshelf entries, interactions, searches and assistant conversations. |
| `POST` | `/api/users/me/reset-recommendations` | Forget learned signals (views, saves, dismissals, searches, onboarding answers). |

## Books

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/books` | List Books |
| `POST` | `/api/books/compare` | Compare |
| `GET` | `/api/books/external-search` | Search Open Library / Google Books for books not yet in the catalogue. |
| `GET` | `/api/books/facets` | Facets |
| `POST` | `/api/books/import` | Import Book |
| `POST` | `/api/books/nl-search` | Nl Search |
| `GET` | `/api/books/{book_id}` | Get Book |
| `GET` | `/api/books/{book_id}/editions` | Get Editions |
| `POST` | `/api/books/{book_id}/interactions` | Add Interaction |
| `GET` | `/api/books/{book_id}/offers` | Get Offers |
| `GET` | `/api/books/{book_id}/reviews` | List Reviews |
| `POST` | `/api/books/{book_id}/reviews` | Create the user's rating/review, or update it if one exists (one per user per book). |
| `GET` | `/api/books/{book_id}/similar` | Get Similar |
| `DELETE` | `/api/reviews/{review_id}` | Delete Review |
| `PATCH` | `/api/reviews/{review_id}` | Update Review |
| `DELETE` | `/api/reviews/{review_id}/helpful` | Unvote Helpful |
| `POST` | `/api/reviews/{review_id}/helpful` | Vote Helpful |
| `POST` | `/api/reviews/{review_id}/report` | Report Review |

## Reading

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/bookshelf` | Get Bookshelf |
| `POST` | `/api/bookshelf` | Add To Shelf |
| `DELETE` | `/api/bookshelf/{entry_id}` | Remove From Shelf |
| `PATCH` | `/api/bookshelf/{entry_id}` | Update Shelf |
| `GET` | `/api/reading-goals` | List Goals |
| `POST` | `/api/reading-goals` | Create or update the goal for that year (and month, if given). |
| `DELETE` | `/api/reading-goals/{goal_id}` | Delete Goal |
| `GET` | `/api/reading-history` | Reading History |
| `GET` | `/api/reading-lists` | Get Lists |
| `POST` | `/api/reading-lists` | Create List |
| `DELETE` | `/api/reading-lists/{list_id}` | Delete List |
| `PATCH` | `/api/reading-lists/{list_id}` | Rename List |
| `POST` | `/api/reading-lists/{list_id}/items` | Add List Item |
| `DELETE` | `/api/reading-lists/{list_id}/items/{book_id}` | Remove List Item |
| `GET` | `/api/reading-plans` | List Plans |
| `POST` | `/api/reading-plans` | Create Plan |
| `POST` | `/api/reading-plans/generate` | Preview a schedule without saving it. |
| `DELETE` | `/api/reading-plans/{plan_id}` | Delete Plan |
| `GET` | `/api/reading-plans/{plan_id}` | Get Plan |
| `GET` | `/api/reading-plans/{plan_id}/calendar.ics` | Plan Calendar |
| `PATCH` | `/api/reading-plans/{plan_id}/items/{item_id}` | Update Plan Item |
| `POST` | `/api/reading-plans/{plan_id}/reschedule` | Rebuild the remaining schedule from today, starting where the reader actually is. |

## Recommendations

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/recommendations` | Get Recommendations |
| `POST` | `/api/recommendations/evaluate` | Run Evaluation |
| `GET` | `/api/recommendations/explain-settings` | Explain Settings |
| `POST` | `/api/recommendations/feedback` | Feedback |
| `GET` | `/api/recommendations/metrics` | Metrics |
| `POST` | `/api/recommendations/recompute` | Refit the recommender now (it also refits automatically when data changes). |

## Marketplace

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/marketplace/favorites` | My Favorites |
| `GET` | `/api/marketplace/inquiries` | My Inquiries |
| `POST` | `/api/marketplace/inquiries/{inquiry_id}/reply` | Reply Inquiry |
| `GET` | `/api/marketplace/listings` | Browse Listings |
| `POST` | `/api/marketplace/listings` | Create Listing |
| `DELETE` | `/api/marketplace/listings/{listing_id}` | Delete Listing |
| `GET` | `/api/marketplace/listings/{listing_id}` | Get Listing |
| `PATCH` | `/api/marketplace/listings/{listing_id}` | Update Listing |
| `POST` | `/api/marketplace/listings/{listing_id}/deactivate` | Deactivate |
| `DELETE` | `/api/marketplace/listings/{listing_id}/favorite` | Unfavorite |
| `POST` | `/api/marketplace/listings/{listing_id}/favorite` | Favorite |
| `POST` | `/api/marketplace/listings/{listing_id}/images` | Upload Listing Image |
| `DELETE` | `/api/marketplace/listings/{listing_id}/images/{image_id}` | Delete Listing Image |
| `POST` | `/api/marketplace/listings/{listing_id}/inquiries` | Send Inquiry |
| `POST` | `/api/marketplace/listings/{listing_id}/mark-sold` | Mark Sold |
| `POST` | `/api/marketplace/listings/{listing_id}/reactivate` | Reactivate |
| `POST` | `/api/marketplace/listings/{listing_id}/report` | Report Listing |
| `GET` | `/api/marketplace/listings/{listing_id}/same-book` | Other active listings of the same book, for side-by-side comparison. |
| `GET` | `/api/marketplace/seller-dashboard` | Seller Dashboard |
| `GET` | `/api/marketplace/sellers/{seller_id}` | Seller Profile |

## Marketplace Intelligence

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/marketplace/compare-listings` | Compare specific community listings side by side, with quality signals and price verdicts. |
| `POST` | `/api/marketplace/estimate-price` | Estimate |
| `GET` | `/api/marketplace/providers/status` | Provider Status |
| `POST` | `/api/marketplace/search-used-books` | Run the multi-step used-book workflow and return the final result with its trace. |
| `POST` | `/api/marketplace/search-used-books/stream` | Same workflow, streamed as NDJSON: one event per step as it starts and finishes, then the result. |

## Assistant

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/assistant/chat` | Chat |
| `DELETE` | `/api/assistant/conversations` | Clear Conversations |
| `GET` | `/api/assistant/conversations` | List Conversations |
| `DELETE` | `/api/assistant/conversations/{conversation_id}` | Delete Conversation |
| `GET` | `/api/assistant/conversations/{conversation_id}` | Get Conversation |
| `GET` | `/api/assistant/status` | Status |

## Admin

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/admin/audit-log` | Audit Log |
| `GET` | `/api/admin/books` | Admin Books |
| `DELETE` | `/api/admin/books/{book_id}` | Delete Book |
| `PATCH` | `/api/admin/books/{book_id}` | Update Book |
| `GET` | `/api/admin/listings` | Admin Listings |
| `PATCH` | `/api/admin/listings/{listing_id}` | Moderate Listing |
| `GET` | `/api/admin/overview` | Overview |
| `GET` | `/api/admin/reports` | Reports |
| `PATCH` | `/api/admin/reports/{kind}/{report_id}` | Resolve Report |
| `GET` | `/api/admin/reviews` | Admin Reviews |
| `PATCH` | `/api/admin/reviews/{review_id}` | Moderate Review |
| `GET` | `/api/admin/users` | List Users |
| `PATCH` | `/api/admin/users/{user_id}` | Update User |

## Health

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Health |
