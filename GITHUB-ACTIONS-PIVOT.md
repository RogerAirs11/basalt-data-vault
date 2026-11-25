# The pivot: scraping moved off the sandbox onto GitHub Actions

## Why

The sandbox stops between turns. Every process dies with it. Three separate
attempts to run a resident scraper inside it failed the same way, and the
supervisor always died alongside the workers, because they share a fate.

## What was tested

A probe workflow proved that **GitHub Actions can reach asbdavani.app
directly**:

```
DIRECT_HTTP=200   DIRECT_BYTES=119776
```

No proxy, no rate limit. The sandbox, by contrast, cannot open a TLS connection
to the site at all and was limited to 20 requests/minute through r.jina.ai.

## What that changed

| | sandbox + proxy | GitHub Actions direct |
|---|---|---|
| Rate | 18 pages/min | ~60,000 pages/hour |
| 5,647 pages | ~5.2 hours | **13.8 minutes** |
| Survives sandbox stop | no | yes (it is not in the sandbox) |
| Loses work on timeout | yes | no (commits continuously) |

## Result

**5,647 / 5,647 pages scraped, 0 failures.** 67 shards, 454 MB, all committed
to `scrape-2026-11-25/raw/`.

## Bugs this exposed, and the fixes

1. **Scraped data held in runner `/tmp` is discarded when the job ends.**
   3,648 pages were scraped and thrown away in the first run. The slug list
   still claimed success — a false record. Fixed by buffering in memory and
   committing every 30 s.
2. **GitHub rejects very large single-file commits.** Shards of 1,411 and 3,088
   pages failed; the base64 body exceeded the request timeout. Fixed by capping
   shards at 150 pages (~5 MB).
3. **The slug list must only advance for pages that are inside a committed
   shard.** Otherwise a cancelled run marks uncommitted work as done. Fixed,
   and the false 5,647 claim was reset to the true 1,999 at the time.

## Extraction

`gha_extract.py` parses the 5,647 stored pages into:

| file | rows | what |
|---|---|---|
| `extracted/horse_summary.csv` | 5,647 | starts / wins / 2nd / 3rd / ratings per horse |
| `extracted/race_rows.csv` | 25,401 | individual race entries with race IDs and Gregorian dates |
| `extracted/doping_rows.csv` | 244 | doping observations (219 distinct horses) |

**Validation:** 5,593 of 5,647 have complete summary numbers, and
**100% of them have placements within valid bounds** (win ≤ starts, etc.).
Zero impossible values. Date conversion is Jalali → Gregorian, verified
(۱۴۰۳/۱۰/۲۷ → 2025-01-16).

## Honest remaining gaps

- **77% of pages yielded a name.** 1,287 did not — the heading markup varies.
  Fixable by another pass; the numeric data is unaffected.
- **Race tables cap at 20 rows** on the site. Horses with more than 20 career
  starts show only their most recent 20. The summary counts are complete.
- **244 doping rows from 219 horses** — this is from the horse pages only. The
  wider doping union (314 horses) lives in the existing CSVs on Drive.
