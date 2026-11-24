#!/usr/bin/env python3
"""Horse-level master: race results + profiles + news doping verdicts."""
import csv, collections

rows = list(csv.DictReader(open('race_records_FINAL.csv')))
prof = list(csv.DictReader(open('cc_horse_profiles_FINAL.csv')))
news = list(csv.DictReader(open('cc_news_doping.csv'))) if __import__('os').path.exists('cc_news_doping.csv') else []

def key(hid, name):
    return (hid or '').strip() or 'nm:' + (name or '').strip().lower()

m = {}
def get(k):
    if k not in m:
        m[k] = dict(horse_id=k if not k.startswith('nm:') else '', name='', birthdate='', sex='',
                    starts='', p1='', p2='', p3='', races=0, ranks=[], doping=set(),
                    doping_records=0, bans=set(), fines=set(), ethics=0,
                    first_date='', last_date='', dist=set(), owner='', coach='', rider='',
                    sources=set())
    return m[k]

for r in rows:
    h = get(key(r['horse_id'], r['horse_name']))
    h['sources'].add('results'); h['name'] = h['name'] or r['horse_name']; h['races'] += 1
    rk = r['rank'].strip()
    if rk.isdigit() and int(rk) > 0: h['ranks'].append(int(rk))
    if r['doping_drugs']:
        h['doping_records'] += 1
        for d in str(r['doping_drugs']).split('|'):
            if d.strip(): h['doping'].add(d.strip().upper())
    d = (r['week_date'] or '')[:10]
    if d:
        h['first_date'] = min(h['first_date'] or d, d); h['last_date'] = max(h['last_date'] or d, d)
    for f, s in (('owner', 'owner'), ('coach_name', 'coach'), ('rider_name', 'rider')):
        if r.get(f) and not h[s]: h[s] = r[f]

for p in prof:
    h = get(key(p['horse_id'], p['horse_name']))
    h['sources'].add('profiles'); h['name'] = h['name'] or p['horse_name']
    for f in ('birthdate', 'sex', 'starts', 'p1', 'p2', 'p3'):
        if not h[f] and p[f]: h[f] = p[f]
    if p['doping_drugs']:
        h['doping_records'] += 1
        for d in p['doping_drugs'].split('|'):
            if d.strip(): h['doping'].add(d.strip().upper())
    if p['coach'] and not h['coach']: h['coach'] = p['coach']
    if p['rider'] and not h['rider']: h['rider'] = p['rider']

# news verdicts are keyed by Persian name -> attach on normalised name
import re
def nz(s): return re.sub(r'\s+', ' ', (s or '').strip().lower())
byname = {}
for k, h in m.items():
    if h['name']: byname.setdefault(nz(h['name']), []).append(h)
news_matched = news_unmatched = 0
for n in news:
    tgt = byname.get(nz(n['horse_name'])) or []
    if tgt:
        h = tgt[0]; news_matched += 1
    else:
        h = get('news:' + nz(n['horse_name'])); h['name'] = n['horse_name']
        h['sources'].add('news'); news_unmatched += 1
    if tgt: h['sources'].add('news')
    for d in n['drugs_en'].split('|'):
        if d.strip(): h['doping'].add(d.strip().upper())
    h['doping_records'] += 1
    if n['horse_ban']: h['bans'].add(n['horse_ban'])
    if n['coach_fine']: h['fines'].add(n['coach_fine'])
    if n['ethics_referral'] == 'yes': h['ethics'] += 1
    if not h['coach'] and n['coach']: h['coach'] = n['coach']

FIELDS = ['horse_id','name','birthdate','sex','starts','p1','p2','p3','races','win','avg_rank',
          'best_rank','doping_records','doping_drugs','doping_count','bans','max_ban_weeks',
          'ethics_referrals','first_date','last_date','distances_seen','owner','coach','rider','sources']

def banweeks(bs):
    best = 0
    for b in bs:
        for tok in re.findall(r'[۰-۹0-9]+', b):
            n = int(''.join(str(ord(c)-0x6F0) if '۰' <= c <= '۹' else c for c in tok))
            best = max(best, n)
    return best

OUT = []
for k, h in m.items():
    rk = h['ranks']
    OUT.append({'horse_id': h['horse_id'], 'name': h['name'], 'birthdate': h['birthdate'],
                'sex': h['sex'], 'starts': h['starts'], 'p1': h['p1'], 'p2': h['p2'], 'p3': h['p3'],
                'races': h['races'], 'win': sum(1 for x in rk if x == 1),
                'avg_rank': round(sum(rk)/len(rk), 2) if rk else '',
                'best_rank': min(rk) if rk else '',
                'doping_records': h['doping_records'],
                'doping_drugs': '|'.join(sorted(h['doping'])),
                'doping_count': len([d for d in h['doping'] if d]),
                'bans': '|'.join(sorted(h['bans'])), 'max_ban_weeks': banweeks(h['bans']) or '',
                'ethics_referrals': h['ethics'],
                'first_date': h['first_date'], 'last_date': h['last_date'],
                'distances_seen': len(h['dist']), 'owner': h['owner'], 'coach': h['coach'],
                'rider': h['rider'], 'sources': '+'.join(sorted(h['sources']))})
OUT.sort(key=lambda r: (-r['races'], r['name']))
with open('horse_master_combined.csv', 'w', newline='') as f:
    w = csv.DictWriter(f, FIELDS); w.writeheader(); w.writerows(OUT)

drugs = collections.Counter()
for r in OUT:
    for d in r['doping_drugs'].split('|'):
        if d: drugs[d] += 1
print(f'horses: {len(OUT)}')
for s in ('results','profiles','news'):
    print(f'  from {s:9s}: {sum(1 for r in OUT if s in r["sources"])}')
print(f'  doping-flagged: {sum(1 for r in OUT if r["doping_count"])}')
print(f'  doping records: {sum(r["doping_records"] for r in OUT)}')
print(f'  distinct drugs: {len(drugs)}')
print(f'  news matched to existing horse: {news_matched} / new: {news_unmatched}')
print('top drugs:', drugs.most_common(8))
