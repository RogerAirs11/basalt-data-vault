#!/usr/bin/env python3
"""Merge results + profiles into one horse-level master view."""
import csv, json, collections

rows = list(csv.DictReader(open('race_records_FINAL.csv')))
prof = list(csv.DictReader(open('cc_horse_profiles_FINAL.csv')))

def key(hid, name):
    return (hid or '').strip() or 'nm:' + (name or '').strip().lower()

m = {}

def get(k):
    if k not in m:
        m[k] = {'horse_id': k if not k.startswith('nm:') else '', 'name': '', 'birthdate': '', 'sex': '',
                'starts': '', 'p1': '', 'p2': '', 'p3': '',
                'races': 0, 'ranks': [], 'doping': set(), 'doping_records': 0,
                'first_date': '', 'last_date': '', 'distance_m': set(),
                'owner': '', 'coach': '', 'rider': '', 'sources': set()}
    return m[k]

for r in rows:
    k = key(r['horse_id'], r['horse_name'])
    h = get(k)
    h['name'] = h['name'] or r['horse_name']
    h['sources'].add('results')
    h['races'] += 1
    rk = r['rank'].strip()
    if rk.isdigit() and int(rk) > 0: h['ranks'].append(int(rk))
    if r['doping_drugs']:
        h['doping_records'] += 1
        for d in r['doping_drugs'].split('|'):
            if d.strip(): h['doping'].add(d.strip().upper())
    d = (r['week_date'] or '')[:10]
    if d:
        if not h['first_date'] or d < h['first_date']: h['first_date'] = d
        if not h['last_date'] or d > h['last_date']: h['last_date'] = d
    for f, src in (('owner','owner'), ('coach_name','coach'), ('rider_name','rider')):
        if r.get(f) and not h[src]: h[src] = r[f]

for p in prof:
    k = key(p['horse_id'], p['horse_name'])
    h = get(k)
    h['sources'].add('profiles')
    h['name'] = h['name'] or p['horse_name']
    if not h['birthdate'] and p['birthdate']: h['birthdate'] = p['birthdate']
    if not h['sex'] and p['sex']: h['sex'] = p['sex']
    if not h['starts'] and p['starts']: h['starts'] = p['starts']
    for f in ('p1','p2','p3'):
        if not h[f] and p[f]: h[f] = p[f]
    if p['doping_drugs']:
        h['doping_records'] += 1
        for d in p['doping_drugs'].split('|'):
            if d.strip(): h['doping'].add(d.strip().upper())
    if p['distance_m']:
        try: h['distance_m'].add(int(float(p['distance_m'])))
        except Exception: pass
    if not h['coach'] and p['coach']: h['coach'] = p['coach']
    if not h['rider'] and p['rider']: h['rider'] = p['rider']

FIELDS = ['horse_id','name','birthdate','sex','starts','p1','p2','p3','races','win',
          'avg_rank','best_rank','doping_records','doping_drugs','doping_count',
          'first_date','last_date','distances_seen','owner','coach','rider','sources']
OUT = []
for k, h in m.items():
    rk = h['ranks']
    OUT.append({
        'horse_id': h['horse_id'], 'name': h['name'], 'birthdate': h['birthdate'],
        'sex': h['sex'], 'starts': h['starts'], 'p1': h['p1'], 'p2': h['p2'], 'p3': h['p3'],
        'races': h['races'],
        'win': sum(1 for x in rk if x == 1),
        'avg_rank': round(sum(rk)/len(rk), 2) if rk else '',
        'best_rank': min(rk) if rk else '',
        'doping_records': h['doping_records'],
        'doping_drugs': '|'.join(sorted(h['doping'])),
        'doping_count': len(h['doping']),
        'first_date': h['first_date'], 'last_date': h['last_date'],
        'distances_seen': len(h['distance_m']),
        'owner': h['owner'], 'coach': h['coach'], 'rider': h['rider'],
        'sources': '+'.join(sorted(h['sources'])),
    })
OUT.sort(key=lambda r: (-r['races'], r['name']))
with open('horse_master_combined.csv','w',newline='') as f:
    w = csv.DictWriter(f, FIELDS); w.writeheader(); w.writerows(OUT)

drugs = collections.Counter()
for r in OUT:
    for d in r['doping_drugs'].split('|'):
        if d: drugs[d] += 1

print(f'horses: {len(OUT)}')
print(f'  with race results: {sum(1 for r in OUT if "results" in r["sources"])}')
print(f'  with profile only: {sum(1 for r in OUT if r["sources"]=="profiles")}')
print(f'  with both:         {sum(1 for r in OUT if "+" in r["sources"])}')
print(f'  doping:            {sum(1 for r in OUT if r["doping_count"])}')
print(f'  doping records:    {sum(r["doping_records"] for r in OUT)}')
print(f'  distinct drugs:    {len(drugs)}')
print('top drugs:', drugs.most_common(10))
