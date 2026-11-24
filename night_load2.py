#!/usr/bin/env python3
"""Night load v2 — D1 archive loader built around the 5M row-read budget.

Lessons from v1 (which burned the whole daily budget in one page):
  * OFFSET pagination on a 95k-row table re-scans the skipped rows, so
    `LIMIT 25000 OFFSET 25000` can cost ~50k rows read. Use KEYSET pagination
    (`WHERE id > ? ORDER BY id`) which is O(1) seek via the primary key.
  * Writing rows costs NO row reads. Writes are a separate 100k/day budget,
    so all inserts use literal SQL (no bound params) and batches of 100.
  * A cheap `SELECT 1` can be served from cache and lie. Always probe with a
    real table read.

Order of operations once the budget resets:
  1. probe real read
  2. keyset-page the whole horses table into memory (95k rows ~= 95k budget)
  3. build the name crosswalk in memory (no per-row lookups, ever)
  4. create archive tables + indexes
  5. batch-insert results / profiles / news verdicts / drug counts
  6. verify with COUNT(*) only
"""
import csv, json, os, re, sys, time, urllib.request, urllib.error, datetime, random

BASE = '/home/user/asb-archive'
LOG = open(f'{BASE}/night_load.log', 'a', buffering=1)
STAGE = f'{BASE}/night_load_state.json'


def log(*a):
    msg = ' '.join(str(x) for x in a)
    print(datetime.datetime.now(datetime.UTC).isoformat(timespec='seconds'), msg, file=LOG)
    print(msg, flush=True)


ACC = json.load(open('/home/user/.horse-private/accounts.json'))
DB = 'f527d88f-c274-4a11-8d17-37dc43ba9027'
URL = f"https://api.cloudflare.com/client/v4/accounts/{ACC['cf_account']}/d1/database/{DB}/query"


def q(sql, params=None, tries=2, timeout=180):
    body = json.dumps({'sql': sql, 'params': params or []}).encode()
    last = None
    for t in range(tries):
        req = urllib.request.Request(URL, data=body, headers={
            'Authorization': 'Bearer ' + ACC['cf_token'], 'Content-Type': 'application/json'})
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
            time.sleep(3)
        except Exception as e:
            last = str(e)[:200]
            time.sleep(3)
    raise RuntimeError(last)


def lit(v):
    """SQL literal — keeps statements parameter-free so batches are tiny."""
    if v is None or v == '':
        return 'NULL'
    if isinstance(v, bool):
        return '1' if v else '0'
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v).replace("'", "''")
    return "'" + s + "'"


# ---------------------------------------------------------------- 1. wait
def probe_ok():
    try:
        r = q("SELECT id FROM horses WHERE id > ? ORDER BY id LIMIT 1",
              [random.randint(0, 10100000)], tries=1, timeout=60)
        return bool(r)
    except RuntimeError as e:
        return False


waited = 0
while True:
    if probe_ok():
        log('D1 reads AVAILABLE')
        break
    if waited % 1800 == 0:
        log(f'reads capped; waited {waited//60} min; next probe in 300s')
    time.sleep(300)
    waited += 300

# ---------------------------------------------------------------- 2. read horses
# wait again: a probe can pass from cache while the real read is still capped
while True:
    try:
        q("SELECT id,name_native FROM horses WHERE id > ? ORDER BY id LIMIT 1",
          [random.randint(0, 10100000)], tries=1, timeout=90)
        break
    except RuntimeError as e:
        if str(e).startswith('CAP:'):
            log('probe passed but real read capped; sleeping 300s')
            time.sleep(300)
        else:
            raise

horses = []
off = 0                      # keyset cursor (not OFFSET)
PAGE = 5000
resumed = 0
while True:
    try:
        b = q("SELECT id,name_native,name_latin,birth_year FROM horses "
              "WHERE id > ? ORDER BY id LIMIT ?", [off, PAGE], timeout=120)
    except RuntimeError as e:
        if str(e).startswith('CAP:'):
            log(f'READ BUDGET EXHAUSTED after {len(horses):,} horses — will resume next turn')
            json.dump({'horses': horses, 'cursor': off}, open(STAGE, 'w'))
            sys.exit(3)
        raise
    if not b:
        break
    horses.extend(b)
    off = b[-1]['id']
    if len(b) < PAGE:
        break
    if len(horses) % 25000 < PAGE:
        log(f'  horses read {len(horses):,} (cursor {off})')
json.dump({'horses': horses, 'cursor': off}, open(STAGE, 'w'))
log(f'TOTAL horses in memory: {len(horses):,}')

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
    cands = by_name.get(norm(name)) or []
    if not cands:
        return None, 'none'
    if byear:
        same = [c for c in cands if str(c.get('birth_year')) == str(byear)]
        if len(same) == 1:
            return same[0]['id'], 'name+year'
    if len(cands) == 1:
        return cands[0]['id'], 'exact'
    return None, 'ambiguous'


# ---------------------------------------------------------------- 4. schema
DDL = [
    """CREATE TABLE IF NOT EXISTS racing_results_archive (
  result_id TEXT PRIMARY KEY, source_horse_id TEXT, race_id TEXT, week_id TEXT, week_date TEXT,
  season TEXT, location TEXT, round_no INTEGER, plan_name TEXT, distance_m INTEGER, number INTEGER,
  rank INTEGER, is_run INTEGER, time_s NUMERIC, weight NUMERIC, carried_weight NUMERIC,
  tools_weight NUMERIC, entrance_rating INTEGER, dl NUMERIC, registration_cost NUMERIC,
  owner_text TEXT, source_horse_name TEXT, horse_name TEXT, horse_sex TEXT, horse_birthdate TEXT,
  horse_starts INTEGER, horse_p1 INTEGER, horse_p2 INTEGER, horse_p3 INTEGER, sire_id TEXT,
  sire_name TEXT, dam_id TEXT, dam_name TEXT, rider_id TEXT, rider_name TEXT, coach_id TEXT,
  coach_name TEXT, data_origin TEXT, registry_horse_id INTEGER, doping_status TEXT, doping_drugs TEXT)""",
    """CREATE TABLE IF NOT EXISTS horse_profiles_archive (
  source_horse_id TEXT PRIMARY KEY, registry_horse_id INTEGER, horse_name TEXT, birthdate TEXT,
  birth_year INTEGER, sex TEXT, starts INTEGER, p1 INTEGER, p2 INTEGER, p3 INTEGER,
  doping_drugs TEXT, data_origin TEXT)""",
    """CREATE TABLE IF NOT EXISTS asb_doping_verdicts (
  verdict_id TEXT PRIMARY KEY, registry_horse_id INTEGER, horse_name TEXT, article_heading TEXT,
  race_no TEXT, place TEXT, coach TEXT, drugs_fa TEXT, drugs_en TEXT, horse_ban TEXT,
  coach_fine TEXT, ethics_referral TEXT, source_url TEXT, source_ts TEXT)""",
    """CREATE TABLE IF NOT EXISTS asb_drug_observations (
  drug_name TEXT PRIMARY KEY, observation_count INTEGER, updated_at TEXT)""",
]
for d in DDL:
    try:
        q(d, timeout=90)
        log('ddl ok:', d.split('(')[0].strip()[-40:])
    except RuntimeError as e:
        log('ddl FAIL', str(e)[:120])

for idx in ["CREATE INDEX IF NOT EXISTS idx_rra_registry ON racing_results_archive(registry_horse_id)",
            "CREATE INDEX IF NOT EXISTS idx_rra_race ON racing_results_archive(race_id)",
            "CREATE INDEX IF NOT EXISTS idx_hpa_registry ON horse_profiles_archive(registry_horse_id)",
            "CREATE INDEX IF NOT EXISTS idx_adv_registry ON asb_doping_verdicts(registry_horse_id)"]:
    try:
        q(idx, timeout=90)
        log('idx ok', idx.split(' ON ')[1][:40])
    except RuntimeError as e:
        log('idx skip', str(e)[:90])

# ---------------------------------------------------------------- 5. insert
def insert_many(table, cols, rows, chunk=100, label=''):
    done = fail = 0
    for i in range(0, len(rows), chunk):
        part = rows[i:i + chunk]
        sql = f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES " + ','.join(
            '(' + ','.join(lit(v) for v in r) + ')' for r in part)
        try:
            q(sql, timeout=180)
            done += len(part)
        except Exception:
            for r in part:
                one = (f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ("
                       + ','.join(lit(v) for v in r) + ')')
                try:
                    q(one, timeout=90)
                    done += 1
                except Exception:
                    fail += 1
        if (i // chunk) % 25 == 0:
            log(f'  {label} {done}/{len(rows)} (fail {fail})')
    log(f'{label} DONE {done} ok / {fail} failed of {len(rows)}')
    return done, fail


# ---- results
results = json.load(open(f'{BASE}/loader-input/results_rows.json'))
profiles = json.load(open(f'{BASE}/loader-input/profile_rows.json'))
drugs = json.load(open(f'{BASE}/loader-input/drugs.json'))

stat = {}
rows = []
for r in results:
    gid, how = match(r[22], None)
    stat[how] = stat.get(how, 0) + 1
    r[36] = gid
    rows.append(r)
log('result crosswalk:', json.dumps(stat))

COLS = ['result_id', 'source_horse_id', 'race_id', 'week_id', 'week_date', 'season', 'location',
        'round_no', 'plan_name', 'distance_m', 'number', 'rank', 'is_run', 'time_s', 'weight',
        'carried_weight', 'tools_weight', 'entrance_rating', 'dl', 'registration_cost',
        'owner_text', 'source_horse_name', 'horse_name', 'horse_sex', 'horse_birthdate',
        'horse_starts', 'horse_p1', 'horse_p2', 'horse_p3', 'sire_id', 'sire_name', 'dam_id',
        'dam_name', 'rider_id', 'rider_name', 'coach_id', 'coach_name', 'data_origin',
        'registry_horse_id', 'doping_status', 'doping_drugs']
insert_many('racing_results_archive', COLS, rows, 100, 'racing_results_archive')

# ---- profiles
pstat = {}
prows = []
for p in profiles:
    gid, how = match(p['name'], (p['birthdate'] or '')[:4])
    pstat[how] = pstat.get(how, 0) + 1
    by = (p['birthdate'] or '')[:4]
    prows.append([p['hid'], gid, p['name'], p['birthdate'],
                  int(by) if by.isdigit() else None,
                  p['sex'], p['starts'], p['p1'], p['p2'], p['p3'],
                  p['doping'] or None, 'commoncrawl-racecards'])
log('profile crosswalk:', json.dumps(pstat))
insert_many('horse_profiles_archive',
            ['source_horse_id', 'registry_horse_id', 'horse_name', 'birthdate', 'birth_year',
             'sex', 'starts', 'p1', 'p2', 'p3', 'doping_drugs', 'data_origin'],
            prows, 100, 'horse_profiles_archive')

# ---- news verdicts
nrows = []
nf = f'{BASE}/cc_news_doping.csv'
if os.path.exists(nf):
    for i, r in enumerate(csv.DictReader(open(nf))):
        gid, _ = match(r['horse_name'], None)
        vid = 'news-%04d' % i
        nrows.append([vid, gid, r['horse_name'], r['article_heading'], r['race_no'], r['place'],
                      r['coach'], r['drugs_fa'], r['drugs_en'], r['horse_ban'], r['coach_fine'],
                      r['ethics_referral'], r['source_url'], r['source_ts']])
    insert_many('asb_doping_verdicts',
                ['verdict_id', 'registry_horse_id', 'horse_name', 'article_heading', 'race_no',
                 'place', 'coach', 'drugs_fa', 'drugs_en', 'horse_ban', 'coach_fine',
                 'ethics_referral', 'source_url', 'source_ts'],
                nrows, 100, 'asb_doping_verdicts')

# ---- drug counts (recomputed across all three sources)
allc = {}
for r in rows:
    if r[40]:
        for d in str(r[40]).split('|'):
            d = d.strip().upper()
            if d:
                allc[d] = allc.get(d, 0) + 1
for p in prows:
    if p[10]:
        for d in str(p[10]).split('|'):
            d = d.strip().upper()
            if d:
                allc[d] = allc.get(d, 0) + 1
for r in nrows:
    if r[8]:
        for d in r[8].split('|'):
            d = d.strip().upper()
            if d:
                allc[d] = allc.get(d, 0) + 1
now = datetime.datetime.now(datetime.UTC).isoformat(timespec='seconds')
insert_many('asb_drug_observations', ['drug_name', 'observation_count', 'updated_at'],
            [[d, c, now] for d, c in sorted(allc.items(), key=lambda kv: -kv[1])], 100,
            'asb_drug_observations')
log(f'distinct drugs across all sources: {len(allc)}')

# ---------------------------------------------------------------- 6. verify
for t in ['racing_results_archive', 'horse_profiles_archive', 'asb_doping_verdicts',
          'asb_drug_observations']:
    try:
        n = q(f"SELECT COUNT(*) AS n FROM {t}", timeout=90)[0]['n']
        log(f'VERIFY {t} = {n}')
    except Exception as e:
        log('VERIFY FAIL', t, str(e)[:120])
log('NIGHT LOAD COMPLETE')
