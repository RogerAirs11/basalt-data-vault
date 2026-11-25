#!/usr/bin/env python3
"""Rebuild the drug tables from canonicalised names. Writes an audit file."""
import csv, json, collections, sys
sys.path.insert(0,'/home/user/asb-archive')
from drug_normalize import canonicalise, canonicalise_one

BASE='/home/user/asb-archive'

print('=== BEFORE ===')
before=list(csv.DictReader(open(f'{BASE}/pristine/asb_drug_observations.csv')))
print(f'  distinct keys in asb_drug_observations : {len(before)}')

# ---- canonicalise every key, keep the audit trail
audit=[]
canon_counts=collections.Counter()
for r in before:
    names, notes = canonicalise(r['drug_name'])
    cnt=int(r['observation_count'])
    for n in names: canon_counts[n]+=cnt
    if notes or not names:
        audit.append({'raw':r['drug_name'],'count':cnt,'canonical':'|'.join(names) or '(class term - excluded)',
                      'reason':'; '.join(f'{a}->{b}' for a,b in notes) or 'class'})

print(f'  distinct canonical substances         : {len(canon_counts)}')
print(f'  corrections applied                   : {len(audit)}')

with open(f'{BASE}/pristine/drug_name_audit.csv','w',newline='',encoding='utf-8') as f:
    w=csv.DictWriter(f,fieldnames=['raw','count','canonical','reason'])
    w.writeheader(); w.writerows(sorted(audit,key=lambda x:-x['count']))

print('\n=== EVERY CORRECTION (nothing merged silently) ===')
for a in sorted(audit,key=lambda x:-x['count']):
    print(f'  {a["raw"]!r:36s} x{a["count"]:<3d} -> {a["canonical"]:<34s} [{a["reason"]}]')

print('\n=== canonical distribution (top 20) ===')
for k,v in canon_counts.most_common(20):
    print(f'  {k:28s} {v}')
print(f'\nremaining substances: {len(canon_counts)-20} more')

# ---- write canonical table
with open(f'{BASE}/pristine/asb_drug_observations_canonical.csv','w',newline='',encoding='utf-8') as f:
    w=csv.writer(f); w.writerow(['drug_name','observation_count'])
    for k,v in sorted(canon_counts.items(), key=lambda kv:(-kv[1],kv[0])):
        w.writerow([k,v])
print(f'\nwrote asb_drug_observations_canonical.csv ({len(canon_counts)} rows)')
