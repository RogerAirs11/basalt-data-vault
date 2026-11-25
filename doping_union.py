#!/usr/bin/env python3
"""One de-duplicated, canonical view of every doping finding we hold.

Three sources overlap:
  A. news verdicts          (119)  - richest: ban, fine, ethics
  B. results doping columns (189)  - 135 horses unique to this source
  C. racecard profiles      (119 rows / 40 substances)

This produces:
  doping_horses.csv    one row per (horse, source) with canonical substances
  doping_master.csv    one row per horse, merged across sources
"""
import csv, sys, json, collections, re
sys.path.insert(0,'/home/user/asb-archive')
from drug_normalize import canonicalise

BASE='/home/user/asb-archive'
FA2EN={'۰':'0','۱':'1','۲':'2','۳':'3','۴':'4','۵':'5','۶':'6','۷':'7','۸':'8','۹':'9'}

def norm_name(s):
    s=(s or '').strip().lower()
    s=s.replace('\u064a','\u06cc').replace('\u0643','\u06a9')
    s=re.sub(r'[\u064b-\u065f\u0670]','',s)
    s=s.replace('\u200c',' ')
    s=re.sub(r'\s+',' ',s)
    return s.strip()

records=[]

# ---------- A. news verdicts
for r in csv.DictReader(open(f'{BASE}/pristine/asb_doping_verdicts_canonical.csv')):
    records.append({
        'horse':r['horse_name'].strip(),'key':norm_name(r['horse_name']),
        'source':'news','substances':r['drugs_en'],'raw_text':r['drugs_fa'],
        'ban':r['horse_ban'],'fine':r['coach_fine'],'ethics':r['ethics_referral'],
        'coach':r['coach'],'race':r['race_no'],'place':r['place'],
        'date':'','ref':r['source_url'],
    })

# ---------- B. results doping columns
for r in csv.DictReader(open(f'{BASE}/pristine/doping_evidence_from_results.csv')):
    names,_=canonicalise(r['doping_drugs'])
    records.append({
        'horse':r['horse_name'].strip(),'key':norm_name(r['horse_name']),
        'source':'results','substances':'|'.join(names),'raw_text':r['doping_drugs'],
        'ban':'','fine':'','ethics':'','coach':'','race':'','place':'',
        'date':(r['week_date'] or '')[:10],'ref':r['source_url'],
    })

# ---------- C. racecard profiles
for r in csv.DictReader(open(f'{BASE}/cc_horse_profiles_FINAL.csv')):
    if not (r['doping_drugs'] or '').strip(): continue
    names,_=canonicalise(r['doping_drugs'])
    records.append({
        'horse':r['horse_name'].strip(),'key':norm_name(r['horse_name']),
        'source':'racecard','substances':'|'.join(names),'raw_text':r['doping_drugs'],
        'ban':'','fine':'','ethics':'','coach':r.get('coach',''),'race':'','place':'',
        'date':(r.get('race_date') or '')[:10],'ref':r['source_url'],
    })

print(f'raw records across 3 sources: {len(records)}')
print(f'  news     : {sum(1 for r in records if r["source"]=="news")}')
print(f'  results  : {sum(1 for r in records if r["source"]=="results")}')
print(f'  racecard : {sum(1 for r in records if r["source"]=="racecard")}')

with open(f'{BASE}/pristine/doping_records.csv','w',newline='',encoding='utf-8') as f:
    w=csv.DictWriter(f,fieldnames=['horse','key','source','substances','raw_text','ban','fine',
                                   'ethics','coach','race','place','date','ref'])
    w.writeheader(); w.writerows(records)

# ---------- merge per horse
by=collections.defaultdict(lambda:{'sources':set(),'drugs':set(),'bans':set(),'fines':set(),
                                   'ethics':0,'coaches':set(),'first':'','last':''})
for r in records:
    h=by[r['key']]
    h['sources'].add(r['source'])
    for d in r['substances'].split('|'):
        if d.strip(): h['drugs'].add(d.strip().upper())
    if r['ban']: h['bans'].add(r['ban'])
    if r['fine']: h['fines'].add(r['fine'])
    if r['ethics']=='yes': h['ethics']+=1
    if r['coach']: h['coaches'].add(r['coach'].strip())
    d=r['date'] or ''
    if d:
        h['first']=min(h['first'],d) if h['first'] else d
        h['last']=max(h['last'],d) if h['last'] else d

out=[]
name_of={r['key']:r['horse'] for r in records}
for k,h in by.items():
    out.append({'horse':name_of.get(k,k),'key':k,'sources':'+'.join(sorted(h['sources'])),
                'substance_count':len(h['drugs']),'substances':'|'.join(sorted(h['drugs'])),
                'bans':'|'.join(sorted(h['bans'])),'fines':'|'.join(sorted(h['fines'])),
                'ethics_referrals':h['ethics'],'coaches':'|'.join(sorted(h['coaches'])),
                'first_date':h['first'],'last_date':h['last']})
out.sort(key=lambda r:(-r['substance_count'],r['horse']))
with open(f'{BASE}/pristine/doping_master.csv','w',newline='',encoding='utf-8') as f:
    w=csv.DictWriter(f,fieldnames=list(out[0].keys()))
    w.writeheader(); w.writerows(out)

allsub=collections.Counter()
for r in out:
    for d in r['substances'].split('|'):
        if d: allsub[d]+=1

print(f'\n=== MERGED RESULT ===')
print(f'  distinct horses with doping evidence : {len(out)}')
print(f'  distinct substances                  : {len(allsub)}')
print(f'  horses named in only ONE source      : {sum(1 for r in out if "+" not in r["sources"])}')
print(f'  horses named in 2+ sources           : {sum(1 for r in out if "+" in r["sources"])}')
print(f'  horses with a recorded ban           : {sum(1 for r in out if r["bans"])}')
print(f'  horses with a recorded fine          : {sum(1 for r in out if r["fines"])}')
print('\n  top substances:')
for k,v in allsub.most_common(10): print(f'    {k:26s} {v}')
print('\n  source combinations:')
c=collections.Counter(r['sources'] for r in out)
for k,v in c.most_common(): print(f'    {k:34s} {v}')
