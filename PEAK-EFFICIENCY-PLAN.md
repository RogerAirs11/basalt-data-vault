# Peak-efficiency plan — D1, Turso, Supabase

Goal: the same workload should be fast and cheap on all three backends, and a
database outage should never take the site down.

Everything below comes from reading the deployed worker and the schema files we
hold. Where I could not verify something (Turso reads are blocked, Supabase is
down), I say so instead of guessing.

---

## The one structural fact that drives everything

The worker has **two query dialects** — `sqlite` for D1/Turso, `postgres` for
Supabase. Same tables, same handlers, same routing. That is genuinely good
design and it means every fix below can be written once.

The problem is that the *indexes* were never brought up to the same standard.

| | D1 | Turso | Supabase |
|---|---|---|---|
| Horses table indexes | good (sort/filter covering) | mostly | **79 indexes, no racing table coverage** |
| `racing_results(horse)` | ✅ yes | ✅ yes (verified) | ❌ none |
| `racing_results` covering w/ `is_run` | ❌ | ❌ | ❌ |
| `race_id` → race lookups | ? | ? | ❌ none |
| Full-text search | ✅ FTS5 + trigram | ✅ | ⚠️ `pg_trgm` only, no GIN on `all_text` |
| Read cache | ❌ (see below) | ❌ | ❌ |

**Supabase is the weakest of the three.** It has 79 indexes on the editorial
side of the schema (AI conversations, attestations, breeding, content) and
essentially none on the racing tables — and racing is what users actually load.
If Supabase ever comes back and gets traffic, it will be the slowest of the
three, not the fastest.

---

## Fix 1 — cache the read endpoints (all backends, biggest win)

Already documented in `WORKER-EFFICIENCY-AUDIT.md`. Restating the shape:

```js
function dk(p) {
  if (/^\/api\/horses\/[^/]+$/.test(p))            return 120;  // horse page
  if (/^\/api\/horses\/?$/.test(p))                 return 60;   // list
  if (/^\/api\/races\/[^/]+$/.test(p))              return 120;
  if (/^\/api\/races\/?$/.test(p))                  return 60;
  if (/^\/api\/search/.test(p))                     return 30;   // see Fix 4
  if (/^\/api\/content\/posts\/?$/.test(p))         return 300;
  if (/^\/api\/content\/posts\/[^/]+\/?$/.test(p))  return 300;
  if (/^\/api\/content\/comments\/?$/.test(p))      return 20;
  if (/^\/api\/ai\/status\/?$/.test(p))             return 60;
  if (/^\/api\/search\/meta\/?$/.test(p))           return 120;
  return null;
}
```

This is backend-agnostic — it sits in front of all three. It is the single
highest-leverage change in this document.

## Fix 2 — make cache misses cheap (schema, per backend)

### D1 + Turso (SQLite) — one index does four jobs

```sql
CREATE INDEX IF NOT EXISTS idx_rr_cover
  ON racing_results(registry_horse_id, is_run, week_date, rank);
```

Covers: the career aggregate (starts/wins/placings/first+last date), the
results list ordering, and the `rank` used for placings. `is_run` in the key
means the table page is never read.

```sql
CREATE INDEX IF NOT EXISTS idx_rr_race
  ON racing_results(race_id, rank);
```

Racecard page: "all runners in this race, ordered by finishing position",
without a sort step.

### Supabase (Postgres) — mirror the same two, plus GIN for search

```sql
CREATE INDEX IF NOT EXISTS idx_rr_horse_cover
  ON racing_results(registry_horse_id, is_run, week_date DESC, rank);
CREATE INDEX IF NOT EXISTS idx_rr_race ON racing_results(race_id, rank);
CREATE INDEX IF NOT EXISTS idx_rr_racecard ON racing_races(race_id);
```

And for search, because `pg_trgm` is installed but under-used:

```sql
CREATE INDEX IF NOT EXISTS idx_hss_all_text_trgm
  ON horse_search_source USING gin(all_text gin_trgm_ops);
```

## Fix 3 — stop computing stats twice

`horse_racing_stats` exists as a materialised summary, and it is **wrong**
(2,135 wins recorded vs 12,499 actual). Meanwhile the worker recomputes the
true numbers from `racing_results` on every page load.

So today we pay for both: a stale table that is not trusted, and a live
aggregate that is. Pick one:

- **Recommended:** keep the live aggregate (it is always correct), and once
  `idx_rr_cover` exists it is an index-only scan — cheap enough that the table
  is redundant. Drop or archive `horse_racing_stats`.
- If you would rather serve from a summary, then it must be rebuilt from
  `racing_results` on a schedule and never hand-maintained.

Either way the current arrangement is the worst of both.

## Fix 4 — search: cache it, it is already well built

Search is in better shape than I expected:

- FTS5 (`horse_search_fts`) with `ORDER BY rank LIMIT 120/160`
- trigram fallback (`horse_search_trigram`) for substring and Persian-name typos
- a reindex queue with a staleness flag (`registry_state.analytics_stale`)
- Postgres path uses `to_tsvector('simple', …)` + similarity()

It is bounded and indexed. The one gap: **search is repeatedly recomputed for
identical queries.** Even 30 seconds of caching on `/api/search` removes most
of that traffic. (This endpoint is safe to cache because it is read-only and
public; per-user counts are handled in a separate authenticated path.)

## Fix 5 — login: correct, but slow on a free tier

Verified from the bundle:

```js
PBKDF2(SHA-256, salt=16B, iterations=100_000, dkLen=256)   // format: pbkdf2-sha256$100000$salt$hash
```

100k PBKDF2-SHA256 is **acceptable and honest** — it is the OWASP floor. It is
not "peak efficiency" though: on Workers CPU limits it costs roughly 30–60 ms
per login, and it is paid on every attempt.

Two cheap wins that do not weaken security:

1. **Rate limit is already there** (AUTH 10/min) — good, keep it.
2. **Return the session from the same round trip.** If login does a separate
   `GET /api/auth/me` right after `POST /api/auth/login`, that second query is
   pure waste. (I could not confirm the client does this — worth checking in the
   frontend.)

⚠️ Do **not** lower the iteration count to make it feel faster. That trades a
real security property for milliseconds.

## Fix 6 — connection/round-trip hygiene

- Worker already **batches** related reads (`e.batch([...])`) — keep doing this
  everywhere. Each batch is one round trip to the database.
- Every row-returning query is `LIMIT`-bounded. Verified across all
  `racing_results` handlers.
- Rate limiters: PUBLIC 300/min, ACCOUNT 5/min, AUTH 10/min, WRITE 30/min,
  EXPENSIVE 12/min. Reasonable.

---

## What I could not verify

- Turso: reads blocked, so no `EXPLAIN QUERY PLAN`. The index list above is
  from `CREATE INDEX` statements I already ran, not from introspection.
- Supabase: down, so the schema above is from our saved
  `supabase-backup/schema/postgres-full-schema.sql`, which may lag the live
  database.
- D1: read quota now exhausted until midnight UTC, so index coverage there is
  from the schema files, not a live check.

## Order I would apply them

1. Fix 1 (cache TTLs) — biggest win, no schema change, reversible
2. Fix 2 (`idx_rr_cover`, `idx_rr_race`) — one write each on D1/Turso
3. Fix 2-Supabase (same two + GIN) — only once the database is reachable
4. Fix 3 (decide the stats arrangement)
5. Fix 4 (30 s search cache)
