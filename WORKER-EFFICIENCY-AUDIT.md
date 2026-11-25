# Worker interrogation — is it as efficient as it can be?

**Short answer: no.** I found three real problems. Two are cheap to fix, one
needs a data change.

Everything below is from reading the deployed bundle
(`turso-rebuild/worker/patched.js`), not from assumption.

---

## Problem 1 — the read cache covers almost nothing

The worker has a proper edge cache with a stale-copy fallback. But look at
which paths are allowed to use it:

```js
function dk(path) {
  return /^\/api\/content\/posts\/?$/        ? 300
       : /^\/api\/content\/posts\/[^/]+\/?$/ ? 300
       : /^\/api\/content\/comments\/?$/     ? 20
       : /^\/api\/ai\/status\/?$/            ? 60
       : /^\/api\/search\/meta\/?$/          ? 120
       : null;                              // <- everything else: no cache
}
```

**Four content endpoints. That is the entire cacheable surface.**

`/api/horses` returns `null` → never cached. `/api/horses/:id` → never cached.
`/api/races` → never cached. Every expensive horse query runs fresh, on every
request, forever.

That single function is why 7.25 billion reads accumulated. It is not that the
queries are slow — it is that **the results are never remembered.**

## Problem 2 — the long stale-copy fallback is dead code

The cache writes two copies per response:

```js
const n = ... // max-age = r
const a = ... // max-age = r + 1800   <- 30-minute stale copy
```

But the stale copy is only written when `ck(path)` is true:

```js
function ck(path) { return dk(path) !== null; }
```

So the 30-minute stale-tolerance — the exact mechanism that would keep the site
alive while a database is unreachable — **only ever applies to the four content
endpoints.** For horses and racing, which is what this site is actually about,
it never engages.

Right now the site stays up on cache. That is luck about which paths were hit,
not design.

## Problem 3 — the summary aggregate has no covering index

On every horse page the worker runs, in one batch:

```sql
SELECT COUNT(*) AS entries,
       SUM(CASE WHEN is_run=1 THEN 1 ELSE 0 END) AS starts,
       SUM(CASE WHEN is_run=1 AND rank=1 THEN 1 ELSE 0 END) AS wins,
       MIN(CASE WHEN is_run=1 THEN week_date ELSE NULL END) AS first_race_date,
       MAX(CASE WHEN is_run=1 THEN week_date ELSE NULL END) AS last_race_date,
       ...
FROM racing_results WHERE registry_horse_id=?
```

I added `racing_results(registry_horse_id, week_date DESC, race_id DESC, rank ASC)`
to Turso. That index finds the rows, but it does **not carry `is_run`**, so
every matching row still needs a table lookup to evaluate the CASE expressions.

The fix is a **covering index** including `is_run`:

```sql
CREATE INDEX idx_rr_cover
  ON racing_results(registry_horse_id, is_run, week_date, rank);
```

With that, the whole aggregate is answered from the index and the table is
never touched. This is a Turso/D1 write and costs nothing to add.

---

## What is already good

- **Rate limiters are in place and sane**: PUBLIC 300/min, ACCOUNT 5/min,
  AUTH 10/min, WRITE 30/min, EXPENSIVE 12/min.
- **All row-returning queries are bounded.** Every `racing_results` read has a
  `LIMIT`; no unbounded table scans escape to the client.
- **Requests are batched** — `e.batch([...])` issues the horse row and its
  summary in one round trip rather than two.
- **Indexes on D1 are correct**: `idx_racing_results_horse(registry_horse_id,
  week_date DESC)` already exists there. The missing index was a **Turso-only**
  defect, which is what caused the block.
- **Auth and write paths bypass the cache** deliberately, which is right.

---

## What I would change, in order of payoff

| # | Change | Effect | Risk |
|---|---|---|---|
| 1 | Add `/api/horses`, `/api/horses/:id`, `/api/races`, `/api/races/:id` to `dk()` with a 60–300 s TTL | **orders of magnitude** fewer reads; this is the whole problem | low — stale-by-a-minute data on a stud book |
| 2 | Enable the 30-min stale fallback for those paths | site survives future database outages instead of erroring | low |
| 3 | Add the covering index with `is_run` | makes each cache miss cheap | none |
| 4 | Rebuild `horse_racing_stats` from `racing_results` | correct numbers; may allow dropping the live aggregate entirely | none — it is currently wrong anyway |

Item 1 alone would have prevented the block. Items 3 and 4 are what make a
cache miss survivable.

---

## Honest answer to your question

I built the indexes yesterday and called the quota problem fixed. That was
half the story. The indexes make each query cheap; the missing cache is why
the site was running those queries millions of times.

If you want me to fix the cache TTLs, say so and I will prepare the patch — but
I cannot deploy or test it while Turso reads are blocked, so I would stage it
rather than push it blind.
