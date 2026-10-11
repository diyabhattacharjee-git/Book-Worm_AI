# Recommendation engine

Code: `backend/app/recommender/`. Everything here is deterministic Python (scikit-learn, NumPy, SciPy);
no LLM is involved in ranking or explanations.

## 1. Signals (`signals.py`)

| Event | Value |
|---|---|
| Rating r (1–5) | `1.5 × (r − 3) / 2` → −1.5 … +1.5 |
| Save / Interested | +1.0 |
| Not interested | −1.5 |
| Dismissed recommendation | −0.7 |
| Shelf: want to read / reading / read / abandoned | +0.8 / +1.2 / +1.5 / −0.5 |
| Book view | +0.3 (at most once per book) |
| “Books I enjoyed” (onboarding) | +1.2, no decay |

Each event decays with age: `value × 0.5^(age_days / REC_RECENCY_HALF_LIFE_DAYS)` (default 60 days), so recent
explicit feedback outweighs old or weak signals. Values per (user, book) are summed and clipped to [−2, 3].
Interested/Not interested replace each other (latest wins).

## 2. Content model (`content.py`) — *fitted*

Each book becomes a document: title, subtitle, authors, subjects, curated genres (×3 weight) and up to
2,500 characters of description. `TfidfVectorizer(ngram_range=(1,2), sublinear_tf=True, max_df=0.6)` is
**fitted on the catalogue** and refitted whenever books change. Optional: `EMBEDDINGS_BACKEND=sentence-transformers`
(after `pip install -r requirements-ml.txt`) uses `all-MiniLM-L6-v2` embeddings instead; if the package or model
is unavailable it falls back to TF-IDF and reports the active backend.

User content profile = Σ signal × book vector (negatives included) + 0.8 × preference text + 0.3 × recent searches.
Content score = cosine(profile, candidate). The liked book most responsible for each match is kept as evidence.

## 3. Collaborative filtering (`collaborative.py`) — item-item

Cosine similarity between book columns of the user × book signal matrix, shrunk by co-occurrence:
`sim' = cos × n_ij / (n_ij + 10)`. Score = similarity-weighted average of the user's own signals.

**Reliability rule:** CF is used only when at least `REC_CF_MIN_USERS` (5) users have ≥ `REC_CF_MIN_USER_INTERACTIONS`
(3) signals, and the target user has ≥ 3 signals. Otherwise its weight is 0 and the API returns a note
(“Collaborative filtering is off: not enough readers with overlapping activity yet.”).

## 4. Popularity (`popularity.py`)

Bayesian average: `bayes = (m × C + Σ ratings) / (m + n)` with C = global mean, m = `REC_BAYES_PRIOR_COUNT` (5).
One 5★ rating therefore lands near the mean. Books without app ratings may use an external provider rating,
shrunk the same way and discounted ×0.8 (different reader population).
`popularity = 0.6 × (bayes − 1) / 4 + 0.4 × log1p(positive interactions) / log1p(max)`.

## 5. Stated preferences

+0.4 per matching favourite genre (max 2), +0.5 favourite author, +0.1 preferred language (−0.3 if the book's
known language differs), ±0.25/−0.1 for length bucket (short ≤ 250, medium ≤ 450, long), +0.15 per theme/topic
found in the book text (max 3).

## 6. Hybrid ranking (`hybrid.py`)

```
final(c) = Σ_s w_s · minmax_s(c) / Σ_{available s} w_s
```

| Weight | Default | Env var | Purpose |
|---|---|---|---|
| content | 0.40 | `REC_WEIGHT_CONTENT` | Similarity to what you liked / asked for |
| collaborative | 0.25 | `REC_WEIGHT_COLLABORATIVE` | What similar readers liked (only when reliable) |
| popularity | 0.15 | `REC_WEIGHT_POPULARITY` | Quality prior and cold-start fallback |
| preference | 0.20 | `REC_WEIGHT_PREFERENCE` | Explicit onboarding answers |
| diversity λ | 0.80 | `REC_DIVERSITY_LAMBDA` | MMR trade-off between relevance and novelty |

* Signals that are unavailable or have no variance are dropped and the weights renormalised.
* Already-rated, shelved, dismissed and “not interested” books are excluded.
* Diversity: Maximal Marginal Relevance `λ·score − (1−λ)·max content-similarity to already chosen`, plus at most
  two books per author per list.

## 7. Explanations

Built only from contributing signals and their evidence, e.g. “Shares themes and subjects with ‘Clean Code’ from
your reading activity” (nearest liked book), “Readers who liked X also responded well to this book” (top CF
contributor), “This book matches your favourite genres (Thriller)”, “Well rated by BookWorm readers (4.6★ from 12
ratings)”. **Mode** is `personalized` when the user has positive activity, otherwise `cold_start` (preferences +
popularity), and the UI says which.

## 8. Cold start

* New users: optional onboarding (genres, authors, languages, themes, topics, enjoyed books, length, goal) → preference
  and content signals; otherwise popularity. Onboarding can be skipped.
* New books: content similarity works immediately from metadata; popularity falls back to external ratings or the mean.

## 9. Adaptation & control

Feedback (`POST /api/recommendations/feedback`), shelf changes and ratings change the data signature, so the model
refits on the next request; `POST /api/recommendations/recompute` forces it. Users can reset learned preferences or
delete reading history in Settings. Nothing sensitive (health, religion, politics…) is inferred; only book-level signals are used.

## 10. Offline evaluation (`evaluation.py`)

* Relevant = rated ≥ 4 or marked read. Eligible users: ≥ 5 relevant books. **Temporal hold-out**: most recent 20%
  (≥ 1) of each eligible user's relevant books are hidden; all events for those pairs are removed from training.
* Configurations compared: hybrid, content-only, collaborative-only, popularity-only.
* Metrics: Precision@K, Recall@K, NDCG@K (binary), catalogue coverage, intra-list diversity (1 − mean pairwise
  content cosine), popularity concentration (share of slots from the top-10% most-interacted training books),
  cold-start precision (users with < 3 training signals, reported only with ≥ 3 such users).
* With fewer than 5 eligible users the result is **“Not enough evaluation data”**.

The app ships with no invented readers or ratings, so evaluation becomes possible only as real people use it.
The test suite uses synthetic readers (tests/factories.py) purely to check the code; those numbers are not
published as model performance.
