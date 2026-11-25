#!/usr/bin/env python3
"""Recompute registry_horse_id for the archive tables using the fixed
Arabic/Persian-aware crosswalk, then patch the rows in D1.

Updates are cheap: an UPDATE costs rows WRITTEN, not rows read.
"""
import json, urllib.request, urllib.error, time, sys, collections, datetime
from crosswalk2 import q, match_year, norm, squash, by_name, by_squash

BASE = '/home/user/asb-archive'

def lit(v):
    if v is None or v == '': return 'NULL'
    if isinstance(v, bool): return '1' if v else '0'
    if isinstance(v, (int, float)): return str(v)
    return "'" + str(v).replace("'", "''") + "'"

# ---------- results: match each (horse_name, week_date) once
d = json.load(open(f'{BASE}/loader-input/results_rows2.json'))
cols, rows = d['cols'], d['rows']
hi = cols.index('horse_name'); wi = cols.index('week_date'); ri = cols.index('result_id')
cache, stat = {}, collections.Counter()
updates = []
for r in rows:
    y = (r[wi] or '')[:4] if r[wi] else None
    k = (r[hi], y)
    if k not in cache:
        cache[k], how = match_year(r[hi], race_year=y)
        stat[how] += 1
    gid = cache[k]
    if gid is not None:
        updates.append([gid, r[ri]])
print('result crosswalk:', dict(stat))
print(f'results to link: {len(updates):,} of {len(rows):,}')

def push(sql_head, pairs, label, target=45000):
    done = fail = 0
    i = 0
    while i < len(pairs):
        batch, size = [], len(sql_head)
        j = i
        while j < len(pairs) and size < target:
            body = '(' + ','.join(lit(v) for v in pairs[j]) + ')'
            batch.append(body); size += len(body) + 1; j += 1
        sql = sql_head + ','.join(batch)
        try:
            q(sql, timeout=150); done += len(batch); i = j
        except RuntimeError as e:
            if str(e).startswith('CAP:'): raise
            for body in batch:
                try: q(sql_head + body, timeout=90); done += 1
                except Exception: fail += 1
            i = j
        if done and (done // 4000) != ((done - len(batch)) // 4000):
            print(f'  {label} {done}/{len(pairs)} (fail {fail})', flush=True)
    print(f'{label} DONE {done} ok / {fail} failed')

# SQLite has no multi-row UPDATE, so use a CASE expression.
def case_update(table, key_col, pairs, label, chunk=400):
    done = fail = 0
    for s in range(0, len(pairs), chunk):
        part = pairs[s:s+chunk]
        when = ' CASE ' + key_col + ' ' + ' '.join(
            f"WHEN {lit(k)} THEN {lit(v)}" for v, k in part) + ' END '
        ids = ','.join(lit(k) for _, k in part)
        sql = f'UPDATE {table} SET registry_horse_id = {when} WHERE {key_col} IN ({ids})'
        try:
            q(sql, timeout=180); done += len(part)
        except RuntimeError as e:
            if str(e).startswith('CAP:'): raise
            if 'TOOBIG' in str(e) or 'too long' in str(e):
                if chunk > 50:
                    # recurse smaller
                    sub = max(50, chunk // 2)
                    for t in range(0, len(part), sub):
                        case_update(table, key_col, part[t:t+sub], label, sub)
                    continue
            for v, k in part:
                try:
                    q(f'UPDATE {table} SET registry_horse_id={lit(v)} WHERE {key_col}={lit(k)}', timeout=60)
                    done += 1
                except Exception: fail += 1
        if done and (done // 4000) != ((done - len(part)) // 4000):
            print(f'  {label} {done}/{len(pairs)} (fail {fail})', flush=True)
    print(f'{label} DONE {done} ok / {fail} failed')

case_update('racing_results_archive', 'result_id', updates, 'results link')

# ---------- profiles
prof = json.load(open(f'{BASE}/loader-input/profile_rows.json'))
pcache, pstat, pupd = {}, collections.Counter(), []
for p in prof:
    by = (p['birthdate'] or '')[:4]
    k = (p['name'], by)
    if k not in pcache:
        pcache[k], how = match_year(p['name'], birth_year=by)
        pstat[how] += 1
    if pcache[k] is not None:
        pupd.append([pcache[k], p['hid']])
print('profile crosswalk:', dict(pstat))
print(f'profiles to link: {len(pupd):,} of {len(prof):,}')
case_update('horse_profiles_archive', 'source_horse_id', pupd, 'profiles link')

# ---------- verdicts
import csv, os
nf = f'{BASE}/cc_news_doping.csv'
if os.path.exists(nf):
    nu = []
    for i, r in enumerate(csv.DictReader(open(nf))):
        gid, _ = match_year(r['horse_name'])
        if gid is not None:
            nu.append([gid, 'news-%04d' % i])
    print(f'verdicts to link: {len(nu):,}')
    case_update('asb_doping_verdicts', 'verdict_id', nu, 'verdicts link')

# ---------- report
for t in ['racing_results_archive', 'horse_profiles_archive', 'asb_doping_verdicts']:
    n = q(f'SELECT COUNT(*) c FROM {t} WHERE registry_horse_id IS NOT NULL')[0]['c']
    tot = q(f'SELECT COUNT(*) c FROM {t}')[0]['c']
    print(f'{t:26s} {n:6,} / {tot:6,}  ({100*n/max(1,tot):.1f}%)')
