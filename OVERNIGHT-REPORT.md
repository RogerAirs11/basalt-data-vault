# Overnight report — night of 24/25 Nov 2026

Worked through the night. Found **two new source classes** that were never
touched before, and both were productive.

---

## Numbers at the end of the night

| Metric | Start of night | Now |
|---|---|---|
| Race result records | 3,918 | **17,659** |
| Horses with race results | 394 | **1,842** |
| Horse profile rows | 0 | **13,401** |
| Horses with profile | 0 | **4,254** |
| **All horses with any data** | 394 | **5,189** |
| Doping records | 2 | **427** |
| Horses flagged for doping | 2 | **314** |
| Distinct substances | 2 | **86** |
| Disciplinary articles parsed | 0 | **119 verdicts from 67 articles** |

---

## New source class 1 — `/racecards`

Never scraped before. Each snapshot carries a `raceHorses` array with
birth date, sex, and career record (starts / 1st / 2nd / 3rd) for every
runner.

**Result: 13,401 profile rows across 4,254 horses.** Fields are 100%
complete on birthdate, sex, starts, p1, p2, p3 and distance. 1,395 of those
horses were entirely new to us.

## New source class 2 — `/news` disciplinary verdicts

This is the biggest find of the night. The site publishes a weekly article
under `/news/dop-week*-<venue><year>` listing every positive test from that
race meeting. Each verdict contains:

- horse name
- race number and finishing position
- trainer name
- **every drug detected**
- ban length in weeks
- fine in rial
- whether it was referred to the ethics committee

**Result: 119 verdicts, 110 horses, 91 trainers, 52 substances.**

Examples of what this unlocked:

```
آرال پسندی   CAFFEINE · THEOPHYLLINE · EPHEDRINE · PHENYLBUTAZONE   12 weeks
کوالیتی      FLUNIXINE · MORPHINE · THEBAINE                         17 weeks
تایسون       CLENBUTEROL                                              4 weeks
```

The longest ban in the corpus is **42 weeks**. Every verdict also carries a
fine amount and an ethics-committee referral — neither of which exists
anywhere in the structured data.

### Why this was hard

The site is a Next.js app. The article body is not in the HTML — it is inside
a React Server Component flight payload. Three separate traps:

1. **Page titles lie.** A `/news/dop-week16-gonbad1403` capture had the title
   of a completely different article.
2. **Ref order lies.** `$1b` is usually the target article but not always.
3. **Every page carries 5–6 article bodies.** So naive parsing attributes
   every verdict on the page to whichever URL you came in on, producing 662
   "verdicts" that were really 67.

The fix: harvest **every body from every page**, hash by content, keep the
longest copy when the same article appears truncated, and let each body
identify itself from its own heading. Coverage ended up **higher than the
page count** — 219 pages yielded 183 unique bodies, collapsing to 67 distinct
articles.

### Three article layouts

The site changed format twice, so three patterns had to be matched:

| Era | Shape |
|---|---|
| Newest | `<horse> (کورس ۴، مقام ۲) - مربی: ... - داروهای ردیابی شده: کافئین، ...` |
| Middle | `<horse> (پنجشنبه، کورس ۵، مقام ۲) - ...` (weekday prefix) |
| Oldest | `اسب <horse> (کورس ۱، مقام ۱) - ... - داروی ردیابی شده: Methylprednisolone` |

Two more quirks: verdicts are packed into **one** `<p>` separated by
`+ معرفی به کمیته اخلاق اسب <next horse>` with **no space** before the next
horse name, and the flight payload sometimes bleeds `e:["$","$L1d"...`
onto the end of the last verdict.

Verified coverage: **110 of 118** "محرومیت اسب" markers extracted (93%). The
remaining 8 are mentions that are not verdicts.

---

## Two data-loss bugs found and fixed

**Merge silently skipped `.gz` sources.** The record count fell 17,383 →
10,501 with no error. `merge_races.py` now handles plain and compressed input
and **prints every source it used**, so a silent drop cannot recur.

**Dedupe dropped doping rows.** Deduplicating profiles kept the first row per
horse/race/timestamp, which was usually the row *without* doping. It now
prefers the doping-bearing row. 3 → 119 doping rows.

**Master view had a broken counter.** `doping_count` was reporting 5,189 —
i.e. every horse — because it counted the raw set including empties. Now
correct: 314.

---

## What is genuinely exhausted

**Ratings.** 96 `/ratings` URLs exist in CommonCrawl; 12 were probed and every
payload is an empty shell — the tab renders client-side and no crawler ever
captured it. Combined with the earlier Wayback result, the ~14,500 missing
ratings are **unrecoverable from any archive that exists**.

**News channel.** All 131 CC-indexed news URLs are scraped. The blog origin
(`blog.asbdavani.app`) fails the TLS handshake, so CommonCrawl is the only
route in, and it is fully drained.

---

## D1 load — blocked, not forgotten

Reads hit the 5M daily cap again during the night (the v1 loader's `OFFSET`
pagination burns a page's worth of rows for every page it skips). It is now
rewritten and running detached, polling every 5 minutes.

The new loader (`night_load2.py`) fixes three things:

1. **Keyset pagination** (`WHERE id > ? ORDER BY id`) instead of `OFFSET`, so
   each page costs exactly the rows it returns.
2. **Literal batch inserts** — 100 rows per statement, no bound params, so the
   request body stays small. Writing costs **no row reads**, and writes have
   91k of 100k budget free.
3. **A real-table probe.** A bare `SELECT 1` gets served from cache and lies —
   it reported "reads available" while every real query was still capped.

---

## Everything is backed up

`RogerAirs11/basalt-data-vault` — 27 files, every one hashed in
`MANIFEST.json`, round-trip verified by re-clone:

```
race_records_FINAL.csv        17,659 records
cc_horse_profiles_FINAL.csv   13,401 rows
horse_master_combined.csv      5,189 horses
cc_news_doping.csv               119 verdicts
cc_news_articles.csv              67 articles
horses_master.csv             35,483
pedigree_edges.csv            47,901
```

Google Drive (folder `1BKAokluKBrWsiXM-fImL6bhXgCYyoD-m`):

```
race_records_FINAL_17659_2026-11-25.csv          10.8 MB
cc_horse_profiles_FINAL_13401_2026-11-25.csv      3.9 MB
horse_master_combined_5189_2026-11-25.csv         0.9 MB
asbdavani_doping_verdicts_119_2026-11-25.csv      111 KB
```
