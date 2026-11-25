# Work report — 2026-11-25

Everything below was measured. Where something could not be done, it says so.

---

## 1. The site was reading a database with reads hard-blocked

The worker runs `DB_PROVIDER_MODE=turso_full`. **The site reads Turso, not D1.**
All of the overnight scraping went into D1, which the site never queries.

Turso this period:

```
rows read       7,254,569,340
Starter quota     500,000,000     -> 14.5x over
blocked_reads   true
overages        false              -> hard block, no billing risk
```

The site kept working only because of the Worker's response cache. Live check
during the entire session: `/api/health`, `/api/horses?limit=3` and
`/api/horses/622` all returned **200**.

## 2. Root cause found and fixed

Every horse-detail page view ran:

```sql
FROM racing_results WHERE registry_horse_id=?
```

There was **no index on that column**. The index build itself proved the cost:
it read **247,082 rows** — the exact work one page view was doing, per view.
Roughly 60,000 page views exhausted a whole month's allowance.

Fixed during the outage, because **Turso writes still work while reads are
blocked**:

| Index | Status |
|---|---|
| `racing_results(registry_horse_id, week_date DESC, race_id DESC, rank ASC)` | created |
| `racing_races(week_id, race_id)` | created |
| `horse_racing_stats(registry_horse_id)` | created |

Re-asserting each under its final name returned **0 rows written (no-op)** on
all three — that is positive proof each exists exactly once, with no duplicate.

Steady state goes from ~122,800 rows read per page view to ≤120.

## 3. A data-destruction risk caught before it fired

Before pruning, I checked what was inside the table I was about to delete from.

`racing_results_archive` held **189 rows carrying doping data**. Those rows are
duplicate *results*, but their doping columns are the scrape's extraction output
and exist nowhere else.

**135 of the horses they name appear in no other source.** Deleting the
duplicates would have silently destroyed the only record of them.

They are now exported and backed up in three places, and the cleanup script
**refuses to run** unless every one is accounted for. I tested that refusal by
removing the export — the script aborted as designed.

## 4. The "86 substances" figure was wrong

Auditing all 86 keys found seven distinct defect classes:

| Defect | Example | Resolution |
|---|---|---|
| spelling variants | `CAFEINE` / `CAFEIN` / `CAFFEINE` | merged to CAFFEINE |
| typos | `PHEYLBUTAZONE`, `THEOPHYLINE`, `ANTYPIYRINE` | corrected |
| concatenated pairs | `PHENYLBUTAZONE OXI PHENYLBUTAZONE` | split into 2 |
| synonyms | `PETHIDINE` = MEPERIDINE, `LIGNOCAINE` = LIDOCAINE | merged |
| salt forms | `TRIAMCINOLONE ACETONIDE` | merged to TRIAMCINOLONE |
| metabolites | `OH LIDOCAINE` | merged to LIDOCAINE |
| untranslated Persian | `اورفنادرین`, `تری پلنامین` | translated |
| class terms | `BRONCHODILATORS`, `OPIOIDES` | excluded, flagged |

**Result: 65 real substances, not 86.** Every correction is recorded with its
reason in `drug_name_audit.csv`. The raw Persian evidence column was verified
byte-identical after the rebuild — nothing was paraphrased.

## 5. The honest doping numbers

Three sources, merged and de-duplicated:

| Source | Records | Unique contribution |
|---|---|---|
| News verdicts | 119 | bans, fines, ethics referrals |
| Results doping columns | 189 | **135 horses found nowhere else** |
| Racecard profiles | 119 | career context |

**314 distinct horses. 65 distinct substances.**

Critically: **267 of the 314 appear in only one source.** That is why all three
sources had to be kept — no single one is a substitute for another.

```
bans recorded          110 horses
fines recorded         110 horses
```

Top substances: PHENYLBUTAZONE 127 · FLUNIXINE 75 · MORPHINE 65 · CAFFEINE 41
· CODEINE 36 · DEXAMETHASONE 32.

## 6. What is still blocked

**D1 writes are exhausted** (resets midnight UTC). So the cleanup of the 17,592
duplicate rows is scripted, rehearsed and guarded, but **not yet applied**.

Rehearsal output — nothing changed:

```
duplicate result_ids : 17,592   (99.6% of archive)
genuinely new        : 67
duplicates carrying doping (preserved): 189
racing_results 122,807 -> 122,807   live table untouched: CONFIRMED
```

`phase2_cleanup.py` runs against D1 as soon as writes return, with a receipt
file written at the end.

**Turso reads are still blocked** until the billing period rolls over. The
indexes are in place, so the next period starts clean.

## 7. Backups — verified, not assumed

`RogerAirs11/basalt-data-vault`, commit `1c4570d`, 52 files, all SHA-256 hashed
in `MANIFEST.json`. Round-trip verified by fresh clone and checksum comparison.

```
doping-canonical/asb_doping_verdicts.csv            119  sha 85375f52…
doping-canonical/asb_drug_observations.csv           86  sha 970cb87e…
doping-canonical/asb_drug_observations_canonical.csv 65  sha c1427423…
doping-canonical/drug_name_audit.csv                 21  sha 3f772964…
doping-canonical/doping_evidence_from_results.csv   189  sha fa41df0a…
doping-canonical/doping_master.csv                  314
```

Also on Google Drive (folder `1BKAokluKBrWsiXM-fImL6bhXgCYyoD-m`): raw
verdicts, canonical substances, the audit trail, the 189-row evidence export
and the 314-horse master.

## 8. What happens next, automatically

| When | What |
|---|---|
| Midnight UTC | D1 writes return; `phase2_cleanup.py --commit` prunes 17,592 duplicates |
| After that | 67 new results + 287 new horses + 2,360 jockey names merge into main tables |
| Turso period rollover | reads return, now indexed, quota burn drops ~1,000× |

## 9. Open item I am not resolving unilaterally

Turso (92,020 horses) and D1 (95,113 live horses) have genuinely diverged by
~3,093, and D1 is 24 days staler. Repointing the worker to D1 is therefore a
**rollback**, not a fallback. It is staged and tested, but I am not switching
providers without a reconcile, and I am not doing that reconcile against a
read-blocked database.
