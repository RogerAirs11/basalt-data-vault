# Ops notes — what actually happens to this sandbox

## The hard fact, proven

Processes do **not** survive between turns. Evidence: after a gap, all three
background processes were gone at once, with no error in any log, and every
file's mtime had been reset to the same instant — the workspace had been
restored from a snapshot rather than left running.

So a supervisor loop inside the sandbox cannot protect anything across turns.
Any design that assumes "it keeps running while I'm away" is wrong.

## The design that follows

1. **Safety is per-page, not per-run.** A page is "safe" the moment it is inside
   a shard on GitHub. `microsync.py` shards every 30 s, so at most ~10 pages
   are ever unsaved. Measured under live load: 1054 scraped, 1046 safe, 8 at risk.
2. **Restart is instant and stateless.** `resume.py` rebuilds its work list from
   the files on disk and the shards on GitHub. No state to corrupt.
3. **Safety comes first on every start.** `resume.py` PHASE 1 shards anything
   unsaved *before* it scraps a single new page.
4. **Truth is queried, never assumed.** `remote_sharded()` downloads every shard
   and reads its members. That is how "963 local, 963 safe" is known rather than
   guessed.

## Commands

```bash
python3 resume.py 12        # 12 minutes of work: secure, scrape, secure, verify
python3 microsync.py        # run alongside: shards every 30s
python3 status.py           # full report
```

## What is lost in the worst case

If the sandbox vanishes mid-run, the loss is whatever `microsync` has not yet
sharded — bounded at ~10 pages, and those are simply re-scraped on restart
because `resume.py` derives its todo from absence on disk.

Nothing else is at risk: shards are permanent and never rewritten, and
`scraped_slugs.json` records the full list.

## Rate limits (measured, not assumed)

- `r.jina.ai`: 20 requests/minute (`x-ratelimit-limit: 20, 20;w=60`).
- Sustainable configuration: 5 workers on a shared 18/min bucket — zero 429s.
- Above that, 429s start and each one costs ~8 s of backoff.
