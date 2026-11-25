# MIDNIGHT RUNBOOK — 2026-11-26 00:00 UTC

Everything here is written and waiting. D1 hit both its read **and** write
quota; Turso reads are blocked; Supabase is down. At 00:00 UTC the D1 quotas
reset and steps 1–4 can run without any further authoring.

Check status first:

```bash
date -u                          # must be >= 2026-11-26T00:00Z
python3 asb-archive/rebuild_stats_from_results.py      # dry run
```

---

## Step 0 — confirm quota reset

```bash
curl -s -X POST "https://api.cloudflare.com/client/v4/accounts/$CF_ACCOUNT/d1/database/f527d88f-c274-4a11-8d17-37dc43ba9027/query" \
  -H "Authorization: Bearer $CF_TOKEN" -H 'Content-Type: application/json' \
  -d '{"sql":"SELECT COUNT(*) c FROM horses"}'
```

If it returns a count → proceed. If it mentions `free tier daily row` → stop,
wait another hour.

## Step 1 — clean the duplicate/inflated tables (~17.6k rows freed)

```bash
python3 asb-archive/phase2_cleanup.py            # dry run, confirm numbers
python3 asb-archive/phase2_cleanup.py --commit   # apply
```

Deletes 17,592 duplicate `racing_results_archive` rows, keeps 67 genuinely new
ones, and **protects the 189 doping rows** (they hold the only doping record
for 135 horses). Step 4b aborts the whole script if
`pristine/doping_evidence_from_results.csv` is missing — verified by test.

## Step 2 — rebuild `horse_racing_stats` from `racing_results`

```bash
python3 asb-archive/rebuild_stats_from_results.py            # dry run
python3 asb-archive/rebuild_stats_from_results.py --commit
```

This is the correctness fix. Current state: 2,135 wins recorded vs **12,499
actual**; 12,547 horses have the wrong `starts`, 4,979 the wrong `win`.
The script recomputes every row from `racing_results` (where `is_run=1`), so it
is re-runnable and never drifts. It also inserts the **206 horses** that have
career data but no stats row.

## Step 3 — load the canonical doping set

```bash
python3 asb-archive/load_canonical.py --commit
```

314 horses / 65 substances from the 3-source union. **This has never run
successfully** — it failed on error 7500 every time. Watch for it silently
doing nothing; verify with:

```sql
SELECT COUNT(*) FROM doping_horse_master;
```

Expect 314. If it is 0, the script failed and must be reported, not ignored.

## Step 4 — backfill the 2,360 missing rider names

```bash
python3 asb-archive/fix_rows.py --riders --commit
```

Check the flag actually exists first — this was written earlier and I have not
re-run it since.

## Step 5 — indexes (make cache misses cheap)

```sql
CREATE INDEX IF NOT EXISTS idx_rr_cover
  ON racing_results(registry_horse_id, is_run, week_date, rank);
CREATE INDEX IF NOT EXISTS idx_rr_race
  ON racing_results(race_id, rank);
```

`idx_rr_cover` carries `is_run`, so the per-horse career aggregate is answered
from the index without touching the table. This is the index Turso was missing
when it hit 14.5× its row-read allowance.

Verify with a no-op re-assertion (writes < 1,000 rows if it already exists) —
**never** drop an index to check for it.

## Step 6 — deploy the cache patch (**not written yet**)

The cache TTL fix in `WORKER-EFFICIENCY-AUDIT.md` is a design, not a patch. It
needs the worker source built, which needs the build toolchain. Until it is
deployed, every horse page still hits the database on every request — this is
what burns the quota.

**Order matters:** do Steps 1–5 first, because they reduce the data volume the
worker has to scan. Deploy the cache last, and only with a rollback binary
staged (`turso-rebuild/worker/original-rollback.js`).

---

## What is ready vs not

| # | Item | State |
|---|---|---|
| 1 | `phase2_cleanup.py` | ✅ written, dry-run tested, guard tested |
| 2 | `rebuild_stats_from_results.py` | ✅ written, **untested against live D1** |
| 3 | `load_canonical.py` | ⚠️ existing, has never succeeded |
| 4 | `fix_rows.py` | ⚠️ existing, flag unverified |
| 5 | Index DDL | ✅ ready to paste |
| 6 | Cache patch | ❌ design only |

Steps 2, 3 and 4 are the ones I would not run unattended. Each should be
run dry, checked, then committed.

---

## Scrape status (running now, independent of all the above)

5,647 horses were discovered on asbdavani but have no race rows — 80% of the
herd. A scraper is running at the sustainable rate of 20 pages/min (r.jina.ai
hard limit), ETA ~4.5 h. Output lands in `scrape-2026-11-25/pages/`, one text
file per horse, parsed by `scrape-2026-11-25/parse.py`.

Validated on پناه کاسیت: parser reproduces the live page exactly (9 starts,
3 wins, 1 second, 4 thirds, 11 race rows, MORPHINE positive). If that holds
across the batch, this closes the largest coverage gap in the database.

The new rows are written as **separate insert files**, never merged into
`racing_results` in place, so the load can be reviewed before it lands.

---

# Scrape findings (measured during the run)

## The site caps the race table at 20 rows

Verified on مون راکت (`clpniflmw0iguwrdoiczv3isb`): the page **declares 53
starts** but renders exactly **20 race rows**, most-recent-first, ending in
1401/9/11. The older 33 races are simply not on the page.

This is a **site-side limit, not a parser bug.** No query parameter opens it
(`?page=2` returns the same page).

## What that means for the load

| Field | Complete? |
|---|---|
| Career summary (starts, p1/p2/p3, ratings) | ✅ **complete and authoritative** |
| Most recent 20 races per horse | ✅ complete |
| Races older than the last 20 | ❌ not obtainable from this page |

Validation across 230 scraped horses: **83.5% exact**, 9.1% within one,
7.4% mismatch — and every mismatch is a horse declaring >24 starts, i.e.
exactly the truncated ones. 7 of 230 horses (3.0%) exceed 20 races.

**Consequence:** load the summary for all 5,647 horses (that is real, complete
data), and load the race rows we have, but mark horses with
`declared_starts > rows_captured` as `career_rows_partial=1` rather than
presenting a truncated history as complete.

## Where the rest of the history might come from

- `/pedigree` and `/productions` tabs — untested, blocked by rate limit at the
  time of writing. Worth one probe before concluding.
- A horse's full history is a *subset* of every racecard for the meetings it
  ran at. We already hold 12,950 racecard-backed races in `racing_races`, so
  older races may be recoverable by joining racecards rather than by scraping
  more horse pages.
- CommonCrawl copies of the site, which we have used successfully before.

## Rate limit (hard numbers)

`r.jina.ai` allows **20 requests per minute**, reported in
`x-ratelimit-limit: 20, 20;w=60`. Bursting above it triggers 429s and takes
minutes to recover. The working configuration is 5 worker threads sharing a
token bucket at 18/min — sustained, zero failures. At that rate the 5,364
remaining pages take ~5 hours.
