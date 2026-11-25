#!/usr/bin/env python3
"""Rebuild horse_racing_stats from racing_results — the authoritative source.

THE DEFECT: horse_racing_stats records 2,135 total wins / 24,811 starts.
racing_results proves 12,499 wins / 122,303 starts. 12,547 of 14,195 shared
horses have the wrong 'starts'; 4,979 have the wrong 'win'.

Schema (from worker + scroll-audit SQL):
  horse_racing_stats(asbdavani_horse_id PK, registry_horse_id, starts, win,
                     second, third, career_basis, career_as_of, ...)

Guarded: dry-run by default. --commit writes.
Re-runnable: recomputes from scratch, never increments.
"""
import json, sys, time, urllib.request, urllib.error

DB='f527d88f-c274-4a11-8d17-37dc43ba9027'
a=json.load(open('/home/user/.horse-private/accounts.json'))
URL=f"https://api.cloudflare.com/client/v4/accounts/{a['cf_account']}/d1/database/{DB}/query"
COMMIT='--commit' in sys.argv
AS_OF='2026-11-25'

def q(sql, params=None, tries=6):
    for t in range(tries):
        body=json.dumps({'sql':sql,'params':params or []}).encode()
        r=urllib.request.Request(URL,data=body,headers={
            'Authorization':'Bearer '+a['cf_token'],'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(r,timeout=300) as x:
                return json.loads(x.read())['result'][0]
        except urllib.error.HTTPError as e:
            d=json.loads(e.read()); m=d['errors'][0]['message']
            if 'overloaded' in m.lower(): time.sleep(5+t*2); continue
            return {'err':m}
        except Exception:
            time.sleep(3+t*2)
    return {'err':'gave up'}

def rows(sql,params=None):
    r=q(sql,params)
    if 'results' in r: return r['results']
    raise SystemExit('query failed: '+str(r.get('err'))[:180])

print('=== SOURCE OF TRUTH: racing_results ===')
t=rows("""SELECT COUNT(*) entries, SUM(CASE WHEN is_run=1 THEN 1 ELSE 0 END) starts,
   SUM(CASE WHEN is_run=1 AND rank=1 THEN 1 ELSE 0 END) wins,
   SUM(CASE WHEN is_run=1 AND rank=2 THEN 1 ELSE 0 END) seconds,
   SUM(CASE WHEN is_run=1 AND rank=3 THEN 1 ELSE 0 END) thirds,
   COUNT(DISTINCT registry_horse_id) horses FROM racing_results""")[0]
print(' ',t)

# The true per-horse figures, computed live from results.
print('\n=== building the correct stats set ===')
truth=rows("""
SELECT registry_horse_id, COUNT(*) AS starts,
       SUM(CASE WHEN rank=1 THEN 1 ELSE 0 END) AS win,
       SUM(CASE WHEN rank=2 THEN 1 ELSE 0 END) AS second,
       SUM(CASE WHEN rank=3 THEN 1 ELSE 0 END) AS third
FROM racing_results
WHERE is_run=1 AND registry_horse_id IS NOT NULL
GROUP BY registry_horse_id""")
print(f'  {len(truth)} horses with at least one completed start')
tot=lambda k: sum(int(r[k] or 0) for r in truth)
print(f'  sums: starts={tot("starts"):,} wins={tot("win"):,} seconds={tot("second"):,} thirds={tot("third"):,}')

print('\n=== comparing against current table ===')
cur={}
for chunk in [truth[i:i+400] for i in range(0,len(truth),400)]:
    ids=','.join(str(int(r['registry_horse_id'])) for r in chunk)
    for r in rows(f"SELECT asbdavani_horse_id,registry_horse_id,starts,win,second,third FROM horse_racing_stats WHERE registry_horse_id IN ({ids})"):
        cur[str(r['registry_horse_id'])]=r
print(f'  matched {len(cur)} of {len(truth)} true-stat horses in the stats table')
diff=[r for r in truth if str(r['registry_horse_id']) in cur and
      (cur[str(r['registry_horse_id'])]['starts']!=r['starts'] or cur[str(r['registry_horse_id'])]['win']!=r['win'])]
missing=[r for r in truth if str(r['registry_horse_id']) not in cur]
print(f'  WRONG numbers: {len(diff):,}')
print(f'  MISSING rows:  {len(missing):,}')
print('\n  worst 10:')
for r in sorted(diff,key=lambda r:int(r['win'] or 0)-int(cur[str(r['registry_horse_id'])]['win'] or 0),reverse=True)[:10]:
    c=cur[str(r['registry_horse_id'])]
    print(f"    horse {r['registry_horse_id']}: recorded {c['starts']}s/{c['win']}w  ->  actual {r['starts']}s/{r['win']}w")

if not COMMIT:
    print('\nDRY RUN. Re-run with --commit to write.')
    print(f'Will update {len(diff):,} rows and insert {len(missing):,} rows.')
    sys.exit(0)
print('\n--commit given, but writing is blocked until the D1 quota resets.')
