# Scrape: where it runs, where it stores, how it survives

## Where it runs

Inside **my sandbox** — an ephemeral machine, not a server you control.

That has one hard consequence: **the process dies when the sandbox is
recycled**, even though the files persist. So a running scraper cannot be
relied on across a long gap. Everything is therefore built to be restartable
and to lose nothing when it stops.

## Where it stores

| Layer | Location | Survives sandbox recycle? |
|---|---|---|
| Raw pages | `/home/user/scrape-2026-11-25/pages/*.txt` | ✅ files persist |
| Running process | sandbox memory | ❌ dies |
| **GitHub backup** | `basalt-data-vault/scrape-2026-11-25/` | ✅ **permanent** |
| Parsed CSVs | `.../out/*.csv` on GitHub | ✅ **permanent** |

Nothing lives only in the process. The page files are the unit of work and they
are written atomically (`os.replace`), so a crash mid-write cannot leave a
truncated file that the resume logic would then trust.

## How the backup works

`sync.py` runs continuously and, every 3 minutes:

1. Takes any 100 pages not yet backed up → `raw/batch-NNNN.tar.gz` → commits to
   GitHub via the Contents API. **Shards are permanent and never rewritten**, so
   each page is uploaded exactly once.
2. Rebuilds `out/new_race_rows.csv`, `out/new_stats_rows.csv`,
   `out/new_doping.csv`, `out/coverage_report.json` from every page on disk
   and re-commits them (small, overwrite each cycle).
3. Updates `scrape-2026-11-25/progress.json` so the progress is visible from
   any browser without cloning anything.

Verified: shard 0001 downloaded back from GitHub, gunzipped, 100 members, page
content intact. The backup is real, not assumed.

## How it survives a crash

`keepalive.py` checks every 30 s. Liveness is determined by scanning `/proc`
for a `python3` process whose argv[1] is exactly the script path.

> This matters. The first supervisor used `pgrep -f scrape-2026-11-25/run.py`,
> which matched **its own command line** and any shell that merely mentioned the
> path. It therefore always believed the scraper was alive and never restarted
> it. Tested: kill the scraper → supervisor logs `scraper down` → restart within
> 30 s.

## Resume behaviour

`run.py` rebuilds its work list from **what is already on disk**:

```python
todo = [t for t in TARGETS if not (exists(t+'.txt') and size > 800)]
```

So a restart resumes exactly where it stopped, with no bookkeeping to corrupt.
The only way to lose work is to lose the files — which is what the shards
prevent.

## Full restore from GitHub

```bash
git clone https://github.com/RogerAirs11/basalt-data-vault
cd basalt-data-vault/scrape-2026-11-25/raw
mkdir -p ~/scrape-2026-11-25/pages && cd ~/scrape-2026-11-25/pages
for f in /path/to/basalt-data-vault/scrape-2026-11-25/raw/*.tar.gz; do tar xzf "$f"; done
# then re-parse: python3 scrape-tools/build_exports.py
```

## Rates and reality

- Hard limit: **20 requests/min** (`x-ratelimit-limit: 20, 20;w=60`).
- Working configuration: 5 workers on a shared 18/min token bucket, measured at
  ~18/min with zero 429s.
- 5,647 targets at 18/min ≈ **5.2 hours** of continuous running.
- `run.py` has a `MAX_RUNTIME` guard (default 3 h) so it exits cleanly rather
  than being killed mid-flight; the supervisor simply restarts it and the
  disk-based work list resumes.

Because the sandbox does not run while nobody is talking to it, the realistic
plan is: it runs while this session is active, restarts itself if it dies, and
every 100 pages is already on GitHub. Worst case, we resume from the last shard.
