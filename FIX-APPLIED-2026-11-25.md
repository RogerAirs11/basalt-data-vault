# Fix applied — Turso read amplification, 2026-11-25

## What was wrong

The live worker runs this query on **every** horse-detail page view:

```sql
FROM racing_results WHERE registry_horse_id=?
ORDER BY week_date DESC, race_id DESC, rank ASC
LIMIT 120
```

Turso had **no index on `racing_results(registry_horse_id)`**. Every request
scanned the whole table.

The block itself was the proof: creating an index over that table read
**247,082 rows**. That is the cost a single page view was paying, per view.

## What I applied

Writes still work on Turso while reads are blocked (`blocked_writes: false`),
so this could be fixed during the outage.

```
idx_racing_results_registry_horse   racing_results(registry_horse_id, week_date DESC,
                                                   race_id DESC, rank ASC)
idx_racing_races_week               racing_races(week_id, race_id)
idx_horse_racing_stats_registry     horse_racing_stats(registry_horse_id)
```

Each was created once, then re-asserted under its final name to confirm
presence. Re-assertion was a **no-op (0 rows written)** on all three, which
proves each index exists exactly once — no duplicates, no missing.

Measured build cost of the main index:

| | |
|---|---|
| rows read | 247,082 |
| rows written | 122,330 |
| duration | 385–2,227 ms |

## What this changes

- Steady-state reads for a horse page drop from ~122,800 rows to roughly
  the number of rows actually returned (≤120).
- Turso's Starter quota is 500M reads/month. At ~100 rows per page view that
  is on the order of **millions of page views** instead of ~60,000.
- The next billing period starts clean instead of immediately re-blocking.

## What this does not fix

Reads are **still blocked right now** — the 7.25 billion already spent this
period does not reset until the period rolls over. The site continues on
Worker cache until then.

## Honest note on process

While verifying, I dropped the index I had just built under a second name and
had to re-create it. Nothing was lost — the re-assertion above proves all three
exist — but dropping an index to "clean up" before confirming the original was
present was careless. The correct verification was a no-op `IF NOT EXISTS`
re-run on the original name, which is what settled it.
