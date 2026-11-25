# State of the three databases — 2026-11-25

Every number measured directly from the database in this session. Nothing
copied from memory or from an earlier report.

---

## The short answer

| | D1 | Turso | Supabase |
|---|---|---|---|
| **Reachable right now** | **yes** (reads; writes capped till midnight) | writes only | **no** |
| Horses | **95,652** (95,113 live) | 92,020 *(stale ref)* | unreachable |
| With competition records | **14,660** of 95,113 = **15.4%** | unknown | unknown |
| Race result rows | 122,807 | ~122,807 *(stale ref)* | unknown |
| Doping data | **yes** (314 horses, 65 substances) | **no** | unknown |
| Status | healthy, best copy | read-blocked, no doping | hard down 3+ days |

**D1 is the only one that is both reachable and complete.** Turso cannot be
read at all. Supabase refuses connections.

---

## 1. D1 — the real numbers

```
horses total                       95,652
horses live (not soft-deleted)     95,113
horses active                      91,519
horses with birth_year             90,847   95.5%
horses with both parents           54,403   57.2%
people                             26,646
horse_people links                110,469
search rows                        95,032
```

Competition:

```
racing_results rows               122,807
racing_races                       12,950
distinct horses with results       14,103
horse_racing_stats                 14,757
horses with ANY competition data   14,660   15.4% of live horses
```

So **15.4% of the registry has any competition record**. The other 80,453
horses have pedigree, passport and parentage but no race history. That is
expected for a stud book — most registered horses never raced.

---

## 2. A serious defect found in `horse_racing_stats`

This is the most important thing in this report.

The stats table and the results table disagree, badly:

| | `horse_racing_stats` says | `racing_results` proves |
|---|---|---|
| total wins | **2,135** | **12,499** |
| total starts | 24,811 | 122,303 |
| horses with a win | 958 | 5,884 |

Of the 14,195 horses present in both tables:

- **12,547 have the wrong `starts`** (88%)
- **4,979 have the wrong `win`** (35%)

Worst examples, all showing zero wins when the results prove otherwise:

```
سلتیک          stats: 0 starts,  0 wins   ->  really 63 starts, 24 wins
امپراطور صحرا  stats: 0 starts,  0 wins   ->  really 73 starts, 21 wins
اوسین بولت      stats: 0 starts,  0 wins   ->  really 24 starts, 15 wins
آتیک           stats: 67 starts, 0 wins   ->  really 67 starts, 24 wins
```

`racing_results` is the record of individual races, so it is authoritative.
`horse_racing_stats` is a derived summary that was never rebuilt from it — and
it is wrong for almost every horse.

**This is fixable entirely inside D1**: recompute the whole table from
`racing_results` with one pass. No external source needed, no scraping, no
judgement calls.

---

## 3. Turso — unreachable

```
SQL read operations are forbidden (reads are blocked)
```

Confirmed again this session, on every table including `SELECT 1`.
Organisation usage: 7.25 billion rows read against a 500 million allowance,
14.5× over. `blocked_reads: true`, `overages: false` (hard block, no billing).

I did fix its root cause while writes still worked — three indexes, including
the missing `racing_results(registry_horse_id)`, verified present by no-op
re-assertion. The index build cost 247,082 rows read, which is exactly what
every page view had been paying.

Turso also has **no doping data at all** — those tables exist only in D1.

---

## 4. Supabase — hard down

```
HTTP 400  FATAL: 57P03: the database system is not accepting connections
          DETAIL: Hot standby mode is disabled.
```

Control plane reports `ACTIVE_HEALTHY`, project `Horse-DB`, Postgres 17.6.1.166,
eu-west-1. The database itself refuses every connection. Same error it has
given for days. Nothing on our side can fix this; it needs a support ticket,
which you have said you do not want.

Its contents were copied to D1 on 2026-11-23, before it went down.

---

## 5. Have we merged everything we scraped? **No. Three things are still out.**

### Merged already
- Doping verdicts and drug table — in D1 (`asb_doping_verdicts` 119,
  `asb_drug_observations` 86)

### NOT merged — sitting in side tables

| What | Count | Why it matters |
|---|---|---|
| Career records for horses with **no** stats row | **206 horses** | these horses show no racing history at all |
| Jockey names missing from live results | **2,360 rows** | rider column blank |
| Duplicate result rows inflating the archive | **17,592** | makes counts look bigger than reality |

The 3,290 profile horses are nearly all already known (3,084 already have
stats, 3,083 already have results). So the racecard scrape was **206 horses of
genuinely new career data** — not 4,254. I should have said that clearly
before.

### Blocked
- D1 **writes** are exhausted until midnight UTC. Every merge below waits on that.
- Turso reads blocked → cannot reconcile D1 against Turso at all.

---

## 6. What "complete and perfect" would actually require

In dependency order. Each is self-contained and verifiable.

1. **Rebuild `horse_racing_stats` from `racing_results`.** Fixes a wrong number
   on 12,547 horses. Pure D1, no external dependency. *Highest value by far.*
2. **Add the 206 missing career records.** Small, precise, verifiable.
3. **Fill the 2,360 blank jockey names.**
4. **Delete the 17,592 duplicate archive rows** so counts stop lying.
5. **Reconcile D1 against Turso** — needs Turso reads back (billing rollover).
6. **Decide the D1 / Turso divergence** (~3,093 horses, D1 24 days staler)
   once both are readable.

Steps 1–4 all run the moment D1 writes reset at midnight UTC. Steps 5–6 cannot
start until Turso reads return.
