import csv, json, re, os
BASE='/home/user/asb-archive'
rows=list(csv.DictReader(open(f'{BASE}/race_records_FINAL.csv')))
prof=list(csv.DictReader(open(f'{BASE}/cc_horse_profiles_FINAL.csv')))

def num(v, cast=str):
    if v is None: return None
    v=v.strip()
    if v=='' : return None
    try: return cast(v)
    except Exception: return None

def slug(s):
    return re.sub(r'[^a-z0-9]+','-', (s or '').lower()).strip('-')

out=[]; seen=set()
for r in rows:
    rid=r['result_id'].strip()
    if not rid or rid in seen: continue
    seen.add(rid)
    hid=r['horse_id'].strip() or ('nm-'+re.sub(r'[^a-z0-9]+','-',(r['horse_name'] or '').lower()).strip('-')+'-'+(r['birthdate'] if 'birthdate' in r else '')+ '-' + (r['horse_name'] or '')[:0])
    if not r['horse_id'].strip():
        hid='nm:'+slug(r['horse_name'])
    out.append([rid, hid, r['race_id'].strip() or None, r.get('week_id') or None,
        r.get('week_date') or None, None, None, num(r.get('round'), int), r.get('race_name') or None,
        num(r.get('distance_m'), int), num(r.get('number'), int), num(r.get('rank'), int),
        None, num(r.get('time_ms'), lambda x: float(x)/1000.0 if x else None),
        num(r.get('weight'), float), num(r.get('carried_weight'), float), num(r.get('tools_weight'), float),
        num(r.get('entrance_rating'), int), num(r.get('dl'), float), None,
        r.get('owner') or None, r['horse_id'].strip() or None, r.get('horse_name') or None,
        None, None, None, None, None, None, None, None,
        r.get('rider_name') or None, None, r.get('coach_name') or None,
        'asbdavani-archive:'+(r.get('source_url') or '')[:180], None,
        r.get('doping_status') or None, r.get('doping_drugs') or None])
json.dump(out, open('/tmp/results_rows.json','w'))
print('results rows:',len(out))

# profiles -> horse-level
best={}
for p in prof:
    key=(p['horse_id'] or '').strip() or 'nm:'+slug(p['horse_name'])
    cur=best.get(key)
    rec={'hid':key,'name':p.get('horse_name'),'birthdate':p.get('birthdate'),
         'sex':p.get('sex'),'starts':num(p.get('starts'),int),'p1':num(p.get('p1'),int),
         'p2':num(p.get('p2'),int),'p3':num(p.get('p3'),int),
         'doping':p.get('doping_drugs') or ''}
    if cur is None: best[key]=rec
    else:
        if rec['doping'] and not cur['doping']: cur['doping']=rec['doping']
        for f in ['birthdate','sex','starts','p1','p2','p3','name']:
            if not cur.get(f) and rec.get(f): cur[f]=rec[f]
json.dump(list(best.values()), open('/tmp/profile_rows.json','w'))
print('profile horses:',len(best))

drugs={}
for r in out:
    if r[37]:
        for d in str(r[37]).split('|'):
            d=d.strip().upper()
            if d: drugs[d]=drugs.get(d,0)+1
for p in best.values():
    if p['doping']:
        for d in str(p['doping']).split('|'):
            d=d.strip().upper()
            if d: drugs[d]=drugs.get(d,0)+1
json.dump(drugs, open('/tmp/drugs.json','w'))
print('distinct drugs:',len(drugs))
