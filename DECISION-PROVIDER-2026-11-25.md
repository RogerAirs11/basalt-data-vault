# Decision record — provider fallback, 2026-11-25

**Decision: do not repoint the worker yet. Prepare a tested fallback, and spend
the next 33 days eliminating the read pattern that caused the block.**

Written down so the reasoning can be checked later rather than trusted.

---

## The situation, measured

| Fact | Value | Source |
|---|---|---|
| Worker provider mode | `turso_full` | live bindings |
| Turso reads this period | 7,254,569,340 | org usage API |
| Turso Starter quota | 500,000,000 | plan API |
| Over quota by | **14.5×** | — |
| Turso writes | 4,575,732 / 10,000,000 | 46%, not blocked |
| `blocked_reads` | **true** | org API |
| `overages` | **false** — hard block, no billing | org API |
| Site right now | 200s, served from Worker cache | live probe |

## Why the reads exploded

The worker's horse-detail path runs, on every request:

```sql
FROM racing_results WHERE registry_horse_id=?
ORDER BY week_date DESC, race_id DESC, rank ASC
LIMIT 120
```

Turso has 13 indexes. **None is on `racing_results(registry_horse_id)`.**
So that query is a full scan of ~122,800 rows, every time, per request.
Roughly 60,000 horse-detail page views exhausts a whole month.

---

## Why I am not repointing to D1 today

D1 **would** work — 200 tables, daily reset, 5M rows/day. But three facts make
it a rollback rather than a fallback:

| | Turso canonical | D1 |
|---|---|---|
| Freshness | 2026-11-22 | `max(updated_at)` = **2026-10-29** |
| Live horses | 92,020 | 95,113 |
| `is_run` repair (7,810 rows) | applied | not applied |
| `horse_racing_stats` repair | applied | 14,757, unverified |

D1 is **24 days stale and carries 3,093 more live horses than Turso** — the two
have genuinely diverged, not merely aged. Repointing would silently revert
three weeks of repairs and change the horse count the public sees.

It would also be trading a 33-day outage of unknown length for a guaranteed
daily one: 122,807 result rows is 2.5% of D1's daily read budget, so a few
hundred page views would re-break it every single day.

**Conclusion: D1 is the right fallback to *stage*, and the wrong thing to
switch on without a reconcile. I will build and test it, and switch only if the
cache actually stops carrying the site.**

---

## Why there is time to do this properly

- Turso's period resets **29 December 2026 — 33 days away**
- `blocked_writes: false` — the database can still be **prepared** during the outage
- The site is serving from cache right now
- Turso's Starter quota is 500M reads/month. Fixing the missing index makes the
  steady-state cost approach zero, so the next period starts clean

The single highest-value action is therefore not a provider switch. It is
**adding the missing index during the window when writes still work.**

---

## What I will do, in order

1. **Preserve** the only data with no other copy — 119 doping verdicts + 86 drug
   rows — to three places.
2. **Clean D1** so it stops double-counting: delete the 17,592 duplicate result
   rows, keep the 67 new ones, merge the 287 new horses and 2,360 jockey names.
3. **Prepare the Turso index change** as an exact, reviewable script, ready to
   run the moment writes are confirmable.
4. **Build and test the D1 fallback** end-to-end without promoting it.
5. **Report** every step with before/after counts.

## What would make me switch providers

Any one of:

- the site starts returning 5xx on a cache miss
- `/api/horses` shows stale or empty results to a real visitor
- the cache TTL is confirmed to be short

None of those have happened yet. I am monitoring rather than pre-empting.
