#!/usr/bin/env python3
"""Rebuild verdict drug lists canonically, preserving the raw Persian wording."""
import csv, sys, collections, json
sys.path.insert(0,'/home/user/asb-archive')
from drug_normalize import canonicalise

BASE='/home/user/asb-archive'
rows=list(csv.DictReader(open(f'{BASE}/pristine/asb_doping_verdicts.csv')))
print(f'verdict rows: {len(rows)}')

changed=0; allnotes=[]
for r in rows:
    before=r['drugs_en']
    names, notes = canonicalise(before)
    after='|'.join(names)
    if after!=before:
        changed+=1
        allnotes.append((r['horse_name'],before,after,notes))
    r['drugs_en']=after
    # drugs_fa stays EXACTLY as scraped - it is the evidence
print(f'rows whose drug list changed: {changed}')
print('\n=== sample of changes (first 8) ===')
for h,b,a,n in allnotes[:8]:
    print(f'  {h[:14]:16s}')
    print(f'     before: {b}')
    print(f'     after : {a}')

with open(f'{BASE}/pristine/asb_doping_verdicts_canonical.csv','w',newline='',encoding='utf-8') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0].keys()))
    w.writeheader(); w.writerows(rows)

# integrity: drugs_fa must be untouched
orig=list(csv.DictReader(open(f'{BASE}/pristine/asb_doping_verdicts.csv')))
assert all(o['drugs_fa']==n['drugs_fa'] for o,n in zip(orig,rows)), 'drugs_fa was modified!'
print('\ndrugs_fa verified unchanged for all', len(rows), 'rows')

d=collections.Counter()
for r in rows:
    for x in r['drugs_en'].split('|'):
        if x: d[x]+=1
print(f'\ndistinct substances named in verdicts: {len(d)}')
print('top:', d.most_common(8))
