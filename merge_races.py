import csv,gzip,os,statistics
from collections import Counter
FILES=['race_records_all.csv','cc_race_records_full.csv','cc_race_records_full.csv.gz',
       'cc_race_records.csv.gz','cc_race_records_b2.csv','cc_race_records_b2.csv.gz',
       'cc_race_records_b3.csv','cc_race_records_b3.csv.gz']
def op(p):
    return gzip.open(p,'rt',encoding='utf8',errors='replace') if p.endswith('.gz') else open(p,encoding='utf8',errors='replace')
seen={}; order=[]; allf=[]
used=[]
for f in FILES:
    if not os.path.exists(f): continue
    used.append(f)
    with op(f) as fh:
        r=csv.DictReader(fh)
        for c in r.fieldnames or []:
            if c not in allf: allf.append(c)
        for row in r:
            k=row.get('result_id') or (row.get('source_ts','')+str(row.get('number','')))
            if not k or k in seen: continue
            seen[k]=row; order.append(k)
rows=[seen[k] for k in order]
for r in rows:
    for c in allf: r.setdefault(c,'')
with open('race_records_FINAL.csv','w',newline='',encoding='utf8') as fh:
    w=csv.DictWriter(fh,fieldnames=allf,extrasaction='ignore'); w.writeheader(); w.writerows(rows)
h=Counter(x['horse_id'] for x in rows if x.get('horse_id'))
c=[v for v in h.values()]
dop=[x for x in rows if (x.get('doping_drugs') or '').strip()]
print('sources used:',len(used))
for u in used: print('   ',u)
print(f'\nrecords        : {len(rows):,}')
print(f'distinct horses: {len(h):,}')
print(f'matches/horse  : avg {sum(c)/len(c):.1f}, median {statistics.median(c):.0f}, max {max(c)}')
print(f'doping cases   : {len(dop):,}')
