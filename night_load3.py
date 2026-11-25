#!/usr/bin/env python3
"""D1 archive loader v3 — validated against the real limits.

Facts measured against this database (not guessed):

  * reads   : 5,000,000 rows/day. Keyset pagination over `horses` costs
              exactly the rows returned (~95k for the full table). OFFSET
              pagination costs a page's worth again for every page skipped.
  * writes  : 100,000 rows/day. A write costs ZERO row reads.
  * statement: SQLITE_TOOBIG above ~100 KB of SQL text. 200 wide rows
              (~70 KB) is safe, 400 (~139 KB) is not.
  * a bare `SELECT 1` is served from cache and will report success while
    every real read is still capped. Always probe with a real table read.

Row arrays are built with EXPLICIT column names. The previous version used a
positional 38-value array against a 41-column table, so every batch failed
validation and then fell into a per-row retry loop that hung for six minutes.
"""
import csv, json, os, re, sys, time, urllib.request, urllib.error
import datetime, random

BASE = '/home/user/asb-archive'
LOG = open(f'{BASE}/night_load.log', 'a', buffering=1)
MAX_SQL_BYTES = 90_000          # measured ceiling is ~100 KB


def log(*a):
    msg = ' '.join(str(x) for x in a)
    now = datetime.datetime.now(datetime.UTC).isoformat(timespec='seconds')
    print(now, msg, file=LOG)
    print(msg, flush=True)


ACC = json.load(open('/home/user/.horse-private/accounts.json'))
DB = 'f527d88f-c274-4a11-8d17-37dc43ba9027'
URL = f"https://api.cloudflare.com/client/v4/accounts/{ACC['cf_account']}/d1/database/{DB}/query"


def q(sql, params=None, tries=2, timeout=90):
    body = json.dumps({'sql': sql, 'params': params or []}).encode()
    last = None
    for _ in range(tries):
        req = urllib.request.Request(URL, data=body, headers={
            'Authorization': 'Bearer ' + ACC['cf_token'],
            'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as x:
                d = json.loads(x.read())
                r = d['result'][0]
                if not r.get('success'):
                    raise RuntimeError(json.dumps(r.get('error'))[:300])
                return r['results']
        except urllib.error.HTTPError as e:
            txt = e.read().decode()[:300]
            last = f'HTTP {e.code} {txt}'
            if 'read limit' in txt or 'exceeded' in txt:
                raise RuntimeError('CAP:' + txt)
            if 'TOOBIG' in txt or 'too long' in txt:
                raise RuntimeError('TOOBIG:' + txt)
            time.sleep(2)
        except Exception as e:
            last = str(e)[:200]
            time.sleep(2)
    raise RuntimeError(last)


def lit(v):
    """SQL literal. Cheaper and smaller than a bound-parameter array."""
    if v is None or v == '':
        return 'NULL'
    if isinstance(v, bool):
        return '1' if v else '0'
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def lit_len(v):
    if v is None or v == '':
        return 0
    if isinstance(v, (int, float)):
        return len(str(v))
    return len(str(v)) + 2 + str(v).count("'")


# ---------------------------------------------------------------- 1. wait for a real read
def real_read_works():
    try:
        r = q("SELECT id FROM horses WHERE id > ? ORDER BY id LIMIT 1",
              [random.randint(0, 10100000)], tries=1, timeout=45)
        return bool(r)
    except RuntimeError:
        return False


waited = 0
while not real_read_works():
    if waited % 1800 == 0:
        log(f'reads capped; waited {waited // 60} min')
    time.sleep(300)
    waited += 300
log('D1 reads AVAILABLE')

# ---------------------------------------------------------------- 2. read horses (keyset)
horses, cursor, PAGE = [], 0, 5000
while True:
    b = q("SELECT id,name_native,name_latin,birth_year FROM horses "
          "WHERE id > ? ORDER BY id LIMIT ?", [cursor, PAGE], timeout=120)
    if not b:
        break
    horses.extend(b)
    cursor = b[-1]['id']
    if len(b) < PAGE:
        break
    if len(horses) % 25000 < PAGE:
        log(f'  horses {len(horses):,} (cursor {cursor})')
log(f'horses in memory: {len(horses):,}')

# ---------------------------------------------------------------- 3. crosswalk
def norm(s):
    s = (s or '').lower()
    s = re.sub(r'[\u064b-\u065f\u0670]', '', s)
    s = s.replace('\u064a', 'i').replace('\u0643', 'k')
    s = re.sub(r'[^a-z0-9\u0600-\u06ff]+', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


by_name = {}
for h in horses:
    for f in ('name_native', 'name_latin'):
        n = norm(h.get(f))
        if n:
            by_name.setdefault(n, []).append(h)


def match(name, byear=None):
    c = by_name.get(norm(name)) or []
    if not c:
        return None, 'none'
    if byear:
        same = [x for x in c if str(x.get('birth_year')) == str(byear)]
        if len(same) == 1:
            return same[0]['id'], 'name+year'
    if len(c) == 1:
        return c[0]['id'], 'exact'
    return None, 'ambiguous'


# ---------------------------------------------------------------- 4. insert helper
def insert_many(table, cols, rows, label, start_bytes=MAX_SQL_BYTES):
    """Pack rows into statements kept safely under SQLITE_TOOBIG (~100 KB).

    Verified on this database: 200 wide rows (~70 KB) succeed, 400 (~139 KB)
    fail with SQLITE_TOOBIG. If a statement is rejected we halve the byte
    target and retry the same span — never silently skip a span of rows.
    """
    head = f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES "
    done = fail = 0
    target = start_bytes
    i = 0
    while i < len(rows):
        # greedily take rows until the next one would cross the byte target
        batch, size = [], len(head)
        j = i
        while j < len(rows):
            body = '(' + ','.join(lit(v) for v in rows[j]) + ')'
            if batch and size + len(body) + 1 > target:
                break
            batch.append(body)
            size += len(body) + 1
            j += 1
        if not batch:
            log(f'  {label} SKIP one oversized row at {i}')
            i += 1
            fail += 1
            continue
        try:
            q(head + ','.join(batch), timeout=150)
            done += len(batch)
            i = j
        except RuntimeError as e:
            msg = str(e)
            if msg.startswith('CAP:'):
                raise
            if msg.startswith('TOOBIG') or 'too long' in msg:
                if len(batch) == 1:
                    log(f'  {label} SKIP oversized row at {i}')
                    i += 1
                    fail += 1
                    continue
                target = max(4000, target // 2)
                log(f'  {label} too big -> target {target} B, retrying')
                continue
            # unknown error: fall back to one row at a time for this batch
            log(f'  {label} batch failed ({msg[:70]}); row-by-row')
            for body in batch:
                try:
                    q(head + body, timeout=90)
                    done += 1
                except Exception:
                    fail += 1
            i = j
        if done and (done // 2000) != ((done - len(batch)) // 2000):
            log(f'  {label} {done}/{len(rows)} (fail {fail})')
    log(f'{label} DONE {done} ok / {fail} failed of {len(rows)}')
    return done, fail


# ---------------------------------------------------------------- 5. results
d = json.load(open(f'{BASE}/loader-input/results_rows2.json'))
RCOLS, RROWS = d['cols'], d['rows']

stat = {}
enriched = []
for r in RROWS:
    gid, how = match(r[RCOLS.index('horse_name')], None)
    stat[how] = stat.get(how, 0) + 1
    enriched.append(r + [gid])
RCOLS2 = RCOLS + ['registry_horse_id']
log('result crosswalk:', json.dumps(stat))
insert_many('racing_results_archive', RCOLS2, enriched, 'racing_results_archive')

# ---------------------------------------------------------------- 6. profiles
profiles = json.load(open(f'{BASE}/loader-input/profile_rows.json'))
PCOLS = ['source_horse_id', 'registry_horse_id', 'horse_name', 'birthdate', 'birth_year',
         'sex', 'starts', 'p1', 'p2', 'p3', 'doping_drugs', 'data_origin']
pstat, prows = {}, []
for p in profiles:
    by = (p['birthdate'] or '')[:4]
    gid, how = match(p['name'], by)
    pstat[how] = pstat.get(how, 0) + 1
    prows.append([p['hid'], gid, p['name'], p['birthdate'],
                  int(by) if by.isdigit() else None,
                  p['sex'], p['starts'], p['p1'], p['p2'], p['p3'],
                  p['doping'] or None, 'commoncrawl-racecards'])
log('profile crosswalk:', json.dumps(pstat))
insert_many('horse_profiles_archive', PCOLS, prows, 'horse_profiles_archive')

# ---------------------------------------------------------------- 7. news verdicts
NCOLS = ['verdict_id', 'registry_horse_id', 'horse_name', 'article_heading', 'race_no',
         'place', 'coach', 'drugs_fa', 'drugs_en', 'horse_ban', 'coach_fine',
         'ethics_referral', 'source_url', 'source_ts']
nrows = []
nf = f'{BASE}/cc_news_doping.csv'
if os.path.exists(nf):
    for i, r in enumerate(csv.DictReader(open(nf))):
        gid, _ = match(r['horse_name'], None)
        nrows.append(['news-%04d' % i, gid, r['horse_name'], r['article_heading'],
                      r['race_no'], r['place'], r['coach'], r['drugs_fa'], r['drugs_en'],
                      r['horse_ban'], r['coach_fine'], r['ethics_referral'],
                      r['source_url'], r['source_ts']])
    insert_many('asb_doping_verdicts', NCOLS, nrows, 'asb_doping_verdicts')

# ---------------------------------------------------------------- 8. drug counts
allc = {}
def bump(v):
    if not v:
        return
    for x in str(v).split('|'):
        x = x.strip().upper()
        if x:
            allc[x] = allc.get(x, 0) + 1
for r in enriched:
    bump(r[RCOLS2.index('doping_drugs')])
for r in prows:
    bump(r[PCOLS.index('doping_drugs')])
for r in nrows:
    bump(r[NCOLS.index('drugs_en')])
now = datetime.datetime.now(datetime.UTC).isoformat(timespec='seconds')
insert_many('asb_drug_observations', ['drug_name', 'observation_count', 'updated_at'],
            [[k, v, now] for k, v in sorted(allc.items(), key=lambda kv: -kv[1])],
            'asb_drug_observations')
log(f'distinct drugs: {len(allc)}')

# ---------------------------------------------------------------- 9. verify
for t in ['racing_results_archive', 'horse_profiles_archive', 'asb_doping_verdicts',
          'asb_drug_observations']:
    try:
        n = q(f"SELECT COUNT(*) AS n FROM {t}", timeout=90)[0]['n']
        log(f'VERIFY {t} = {n}')
    except Exception as e:
        log('VERIFY FAIL', t, str(e)[:100])
log('NIGHT LOAD COMPLETE')
