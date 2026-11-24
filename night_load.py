#!/usr/bin/env python3
"""Night load: waits for D1 daily read reset, then loads archive into D1.

 1. wait until 00:00:05 UTC
 2. ONE paged read of horses -> /tmp/horses_mem.json  (25k pages)
 3. build crosswalk in memory (normalised name + birth year)
 4. create archive tables if absent
 5. batch-insert racing_results_archive / horse_profiles_archive / asb_rating_observations
 6. verify with COUNT(*) only (cheap), log to /home/user/asb-archive/night_load.log
"""
import csv, json, os, re, sys, time, urllib.request, urllib.error, datetime

LOG = open('/home/user/asb-archive/night_load.log', 'a', buffering=1)
def log(*a):
    msg = ' '.join(str(x) for x in a)
    print(datetime.datetime.utcnow().isoformat(timespec='seconds'), msg, file=LOG)
    print(msg, flush=True)

ACC = json.load(open('/home/user/.horse-private/accounts.json'))
DB = 'f527d88f-c274-4a11-8d17-37dc43ba9027'
URL = f"https://api.cloudflare.com/client/v4/accounts/{ACC['cf_account']}/d1/database/{DB}/query"

def q(sql, params=None, tries=3):
    body = json.dumps({'sql': sql, 'params': params or []}).encode()
    last = None
    for t in range(tries):
        req = urllib.request.Request(URL, data=body, headers={
            'Authorization': 'Bearer ' + ACC['cf_token'], 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=180) as x:
                d = json.loads(x.read()); r = d['result'][0]
                if not r.get('success'):
                    raise RuntimeError(json.dumps(r.get('error'))[:300])
                return r['results']
        except urllib.error.HTTPError as e:
            txt = e.read().decode()[:300]
            last = f'HTTP {e.code} {txt}'
            if 'read limit' in txt or 'exceeded' in txt:
                if tries == 1:
                    raise RuntimeError(last)
                time.sleep(600); continue
            raise RuntimeError(last)
        except Exception as e:
            last = str(e)[:200]; time.sleep(5)
    raise RuntimeError(last)

# ---------- 1. wait for reset (no attempt cap) ----------
def probe_ok():
    try:
        import random
        r = q("SELECT id FROM horses WHERE id > ? LIMIT 1", [random.randint(0, 10100000)], tries=1)
        return bool(r)
    except RuntimeError as e:
        if 'read limit' in str(e):
            return False
        log('probe odd:', str(e)[:120]); return False

waited = 0
while True:
    if probe_ok():
        log('D1 reads AVAILABLE at', datetime.datetime.utcnow().isoformat(timespec='seconds'))
        break
    if waited % 1800 == 0:
        log('reads capped; %.0f min waited; next probe in 300s' % (waited/60))
    time.sleep(300); waited += 300

# ---------- 2. one paged read ----------
if os.path.exists('/tmp/horses_mem.json'):
    horses = json.load(open('/tmp/horses_mem.json'))
    log('horses loaded from cache', len(horses))
else:
    horses = []; off = 0; PAGE = 25000
    while True:
        b = q(f"SELECT id,name_native,name_latin,birth_year FROM horses LIMIT {PAGE} OFFSET {off}")
        horses.extend(b or [])
        log(f'  read {len(horses):,}')
        if not b or len(b) < PAGE: break
        off += PAGE
    json.dump(horses, open('/tmp/horses_mem.json', 'w'))
log('TOTAL horses in memory:', len(horses))

# ---------- 3. crosswalk ----------
def norm(s):
    s = (s or '').lower()
    s = re.sub(r'[\u064b-\u065f\u0670]', '', s)      # harakat
    s = s.replace('\u064a', 'i').replace('\u0643', 'k')
    s = re.sub(r'[^a-z0-9\u0600-\u06ff]+', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()

by_name = {}
for h in horses:
    for f in ('name_native', 'name_latin'):
        n = norm(h.get(f))
        if n: by_name.setdefault(n, []).append(h)

def match(name, byear=None):
    n = norm(name)
    cands = by_name.get(n) or []
    if not cands: return None, 'none'
    if len(cands) == 1:
        return cands[0]['id'], ('exact' if byear is None else 'exact+year-ok' if str(cands[0].get('birth_year')) == str(byear) else 'exact-year-clash')
    if byear:
        same = [c for c in cands if str(c.get('birth_year')) == str(byear)]
        if len(same) == 1: return same[0]['id'], 'name+year'
    return None, 'ambiguous'

results = json.load(open('/home/user/asb-archive/loader-input/results_rows.json'))
profiles = json.load(open('/home/user/asb-archive/loader-input/profile_rows.json'))
drugs = json.load(open('/home/user/asb-archive/loader-input/drugs.json'))

stat = {}
# enrich results with registry id
names_for = {}
for r in results:
    if r[22]:  # horse_name
        names_for[r[1]] = r[22]
for p in profiles:
    names_for.setdefault(p['hid'], p['name'])
p_byear = {p['hid']: (p['birthdate'] or '')[:4] for p in profiles}

for r in results:
    if not str(r[1]).startswith('nm:'):
        gid, how = match(r[22], None)
    else:
        gid, how = match(r[22], None)
    r[36] = gid
    stat[how] = stat.get(how, 0) + 1
log('result crosswalk:', json.dumps(stat))

pstat = {}
for p in profiles:
    gid, how = match(p['name'], (p['birthdate'] or '')[:4])
    p['gid'] = gid
    pstat[how] = pstat.get(how, 0) + 1
log('profile crosswalk:', json.dumps(pstat))

# ---------- 4. schema ----------
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
"""CREATE TABLE IF NOT EXISTS asb_drug_observations (
  drug_name TEXT PRIMARY KEY, observation_count INTEGER, updated_at TEXT)""",
]
for d in DDL:
    q(d); log('ddl ok:', d.split('(')[0].strip())
for idx in ["CREATE INDEX IF NOT EXISTS idx_rra_registry ON racing_results_archive(registry_horse_id)",
            "CREATE INDEX IF NOT EXISTS idx_rra_race ON racing_results_archive(race_id)",
            "CREATE INDEX IF NOT EXISTS idx_hpa_registry ON horse_profiles_archive(registry_horse_id)"]:
    try: q(idx); log('idx ok')
    except RuntimeError as e: log('idx skip', str(e)[:80])

# ---------- 5. insert ----------
def insert(sql, payload, chunk=100, label=''):
    done = 0; fail = 0
    for i in range(0, len(payload), chunk):
        part = payload[i:i+chunk]
        try:
            q(sql, part); done += len(part)
        except Exception as e:
            # row-by-row fallback so one bad row can't sink the batch
            for row in part:
                try: q(sql, row); done += 1
                except Exception: fail += 1
        if (i // chunk) % 20 == 0:
            log(f'  {label} {done}/{len(payload)} (fail {fail})')
    log(f'{label} DONE {done} ok / {fail} failed of {len(payload)}')
    return done, fail

flat = []
for r in results:
    flat.extend(r)
INS = ("INSERT OR REPLACE INTO racing_results_archive VALUES (" + ",".join(["?"]*41) + ")")
insert(INS, flat, 60, 'racing_results_archive')

flatp = []
for p in profiles:
    flatp.extend([p['hid'], p.get('gid'), p['name'], p['birthdate'],
                  int((p['birthdate'] or '0')[:4]) if (p['birthdate'] or '')[:4].isdigit() else None,
                  p['sex'], p['starts'], p['p1'], p['p2'], p['p3'], p['doping'] or None, 'commoncrawl-racecards'])
INS2 = ("INSERT OR REPLACE INTO horse_profiles_archive VALUES (" + ",".join(["?"]*12) + ")")
insert(INS2, flatp, 80, 'horse_profiles_archive')

flatd = []
for d, c in sorted(drugs.items(), key=lambda kv: -kv[1]):
    flatd.extend([d, c, datetime.datetime.utcnow().isoformat(timespec='seconds')])
insert("INSERT OR REPLACE INTO asb_drug_observations VALUES (?,?,?)", flatd, 50, 'asb_drug_observations')

# ---------- 6. verify ----------
for t in ['racing_results_archive', 'horse_profiles_archive', 'asb_drug_observations']:
    try:
        n = q(f"SELECT COUNT(*) AS n FROM {t}")[0]['n']
        log(f'VERIFY {t} = {n}')
    except Exception as e:
        log('VERIFY FAIL', t, str(e)[:120])
log('NIGHT LOAD COMPLETE')
