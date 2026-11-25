#!/usr/bin/env python3
"""Rebuild loader rows with EXPLICIT column names (the positional array was
38 wide against a 41-column table, which silently failed every batch)."""
import csv, json, re

BASE = '/home/user/asb-archive'
rows = list(csv.DictReader(open(f'{BASE}/race_records_FINAL.csv')))

def num(v, cast=float):
    v = (v or '').strip()
    if v == '': return None
    try: return cast(float(v)) if cast is int else cast(v)
    except Exception: return None

def clean(s, maxlen=200):
    """Regex overruns in the original scrape left JSON fragments in some fields."""
    s = (s or '').strip()
    s = s.replace('\\"', '"')
    for bad in ('","date":', '","leagueId":', '","id":', '"}'):
        i = s.find(bad)
        if i > 0: s = s[:i]
    s = s.strip(' ,"')
    return s[:maxlen] if s else None

COLS = ['result_id','source_horse_id','race_id','week_id','week_date','round_no','plan_name',
        'distance_m','number','rank','time_s','weight','carried_weight','tools_weight',
        'entrance_rating','dl','owner_text','horse_name','rider_name','coach_name',
        'data_origin','doping_status','doping_drugs','source_url']

out = []
for r in rows:
    rid = (r['result_id'] or '').strip()
    if not rid: continue
    tms = num(r.get('time_ms'))
    out.append([
        rid,
        clean(r.get('horse_id'), 60) or ('nm:' + re.sub(r'[^a-z0-9]+', '-',
              (r.get('horse_name') or '').lower()).strip('-')),
        clean(r.get('race_id'), 60),
        clean(r.get('week_id'), 60),
        clean(r.get('week_date'), 40),
        num(r.get('round'), int),
        clean(r.get('race_name'), 120),
        num(r.get('distance_m'), int),
        num(r.get('number'), int),
        num(r.get('rank'), int),
        round(tms / 1000.0, 3) if tms else None,
        num(r.get('weight')),
        num(r.get('carried_weight')),
        num(r.get('tools_weight')),
        num(r.get('entrance_rating'), int),
        num(r.get('dl')),
        clean(r.get('owner'), 120),
        clean(r.get('horse_name'), 120),
        clean(r.get('rider_name'), 80),
        clean(r.get('coach_name'), 80),
        'asbdavani',
        clean(r.get('doping_status'), 20),
        clean(r.get('doping_drugs'), 300),
        clean(r.get('source_url'), 200),
    ])

for row in out:
    assert len(row) == len(COLS), f'{len(row)} != {len(COLS)}'
json.dump({'cols': COLS, 'rows': out}, open(f'{BASE}/loader-input/results_rows2.json', 'w'))
print(f'rows: {len(out)}  cols: {len(COLS)}')
print('with doping:', sum(1 for r in out if r[22]))
print('sample plan_name:', repr(out[0][6])[:70])
print('sample row len ok')
