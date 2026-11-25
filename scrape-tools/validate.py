#!/usr/bin/env python3
"""Self-consistency check: do the parsed race rows reproduce the page's own
summary numbers (starts / p1 / p2 / p3)?

If the parser drops or double-counts a race, these will diverge. That is the
only available validation, because these horses have no prior stored rows.
"""
import json,sys
from build_exports import rows,stats

by={}
for r in rows: by.setdefault(r['asbdavani_horse_id'],[]).append(r)

match=close=bad=nodata=0; examples=[]
for s in stats:
    k=s['asbdavani_horse_id']; rs=by.get(k,[])
    if s['starts'] is None: nodata+=1; continue
    # rows with a real placing count as completed starts
    started=[r for r in rs if r['placing'] and r['placing'].strip()]
    wins=sum(1 for r in started if r['placing'].split('/')[0].strip()=='1')
    st=int(s['starts']); p1=int(s['win'] or 0)
    if st==len(started) and p1==wins: match+=1
    elif abs(st-len(started))<=1 and abs(p1-wins)<=1: close+=1
    else:
        bad+=1
        if len(examples)<8: examples.append((k,s['name'],st,len(started),p1,wins,len(rs)))

n=match+close+bad
print(f'horses compared: {n} (no summary data: {nodata})')
print(f'  EXACT (rows reproduce page): {match} = {match/n*100:.1f}%')
print(f'  within 1:                    {close} = {close/n*100:.1f}%')
print(f'  MISMATCH:                    {bad} = {bad/n*100:.1f}%')
if examples:
    print('\n  mismatches (declared starts/rows, declared wins/wins-from-rows, total rows):')
    for e in examples: print('   ',e)
json.dump({'compared':n,'exact':match,'close':close,'mismatch':bad},
          open('/home/user/scrape-2026-11-25/out/validation.json','w'),indent=2)
