# Overnight report — 2026-11-25

Worked through the night. Two new source classes found, both fruitful.

## Numbers at the end of the night

| Metric | Session start | Now |
|---|---|---|
Race result records | 3,918 | **17,659** |
Horses with race results | 394 | **1,841** |
Horse profile rows | 0 | **13,401** |
Horses with profile | 0 | **4,254** |
**All horses with racing data** | 394 | **5,155** |
Doping records | 2 | **308** |
Distinct drugs | 2 | **61** |

## What was done

### 1. Swept all 130 CommonCrawl collections
18 had been checked previously; the remaining 112 were swept. **9 more held
data**, and the 2024 crawls were the richest:

```
CC-MAIN-2024-38   991 URLs
CC-MAIN-2024-42   363
CC-MAIN-2024-30   256
CC-MAIN-2024-10   200
CC-MAIN-2024-46   162
```

Older crawls (2017–2023) are all empty for this domain — the site did not exist
yet or was not crawled.

### 2. Batch 3: +4,083 records
773 new performance pages from the 2024 collections.

### 3. NEW SOURCE CLASS: `/racecards`
This path was never scraped before. Each snapshot holds a `raceHorses` array
with, per entry:

- `birthdate` (100% present)
- `sex` (100%)
- `starts`, `p1`, `p2`, `p3` (100%)
- `rider` (86%), `coach` (99%)
- `doping` object

Result: **13,401 profile rows across 4,254 horses, 1,395 of them entirely new
to us.**

### 4. Doping parser fix — 6 drugs → 40
The real object is `{"dopingDrugs":[{"drug":{"faName":...}}]}` with **no status
key**. My first regex required `"status"`, so it silently matched nothing and
the run reported 0 doping rows. Reading `faName` and defaulting the status to
POSITIVE fixed it.

## Two bugs I found and fixed

**Data loss in merge.** The merge skipped `.gz` sources silently and the record
count fell from 17,383 to 10,501. `merge_races.py` now accepts both plain and
compressed input and **prints every source it used**, so a silent drop cannot
happen again.

**Dropped doping rows in dedupe.** Deduplicating profiles kept the first row per
`(horse, race, timestamp)`, which was often the row without doping. It now
prefers the row that carries doping data. 3 → 119 doping rows.

## What is genuinely exhausted

**Ratings.** I found 96 `/ratings` URLs in CommonCrawl and checked 12 of them.
Every payload is empty — the tab renders client-side and the crawler captured
nothing. Combined with the earlier Wayback finding, the ~14,500 missing ratings
are **unrecoverable from any archive that exists.**

## Still pending

**Loading into D1.** Reads are quota-blocked (363M of 5M used) until 00:00 UTC.
Two hours away. The load is prepared: one paged read of `horses`, match in
memory, batch insert. **Writes have 91k of 100k budget free**, so only the read
cap blocks it.

## Everything is backed up

`RogerAirs11/basalt-data-vault` — every file hashed in `MANIFEST.json`:

```
race_records_FINAL.csv        17,659
cc_horse_profiles_FINAL.csv   13,401
horses_master.csv             35,483
pedigree_edges.csv            47,901
lineage edges                598,392
```
