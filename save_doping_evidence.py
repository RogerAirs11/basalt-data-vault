#!/usr/bin/env python3
"""PRESERVE the 189 doping rows inside racing_results_archive before prune.

These rows are duplicate RESULTS but their doping columns are the extraction
output of the scrape and have no other home. Deleting them without first
copying the doping evidence would destroy data. Read-only: touches nothing.
"""
import csv, json, urllib.request, urllib.error, hashlib

ACC=json.load(open('/home/user/.horse-private/accounts.json'))
URL=("https://api.cloudflare.com/client/v4/accounts/"
     f"{ACC['cf_account']}/d1/database/f527d88f-c274-4a11-8d17-37dc43ba9027/query")
def q(sql, params=None, timeout=180):
    body=json.dumps({'sql':sql,'params':params or []}).encode()
    req=urllib.request.Request(URL,data=body,headers={
        'Authorization':'Bearer '+ACC['cf_token'],'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=timeout) as x:
        r=json.loads(x.read())['result'][0]
        if not r.get('success'): raise RuntimeError(str(r.get('error'))[:200])
        return r['results']

rows=q("""
  SELECT result_id, source_horse_id, horse_name, registry_horse_id, race_id,
         week_id, week_date, plan_name, distance_m, rank, number,
         doping_status, doping_drugs, source_url
  FROM racing_results_archive
  WHERE doping_drugs IS NOT NULL AND doping_drugs <> ''
  ORDER BY week_date DESC, horse_name
""")
print(f'doping-bearing result rows: {len(rows)}')

p='/home/user/asb-archive/pristine/doping_evidence_from_results.csv'
with open(p,'w',newline='',encoding='utf-8') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0].keys()))
    w.writeheader(); w.writerows(rows)
h=hashlib.sha256(open(p,'rb').read()).hexdigest()
print(f'wrote {p}')
print(f'  sha256 {h}')

# how many distinct horses / substances in this set?
horses=set(); drugs=set()
for r in rows:
    horses.add(r['horse_name'])
    for d in (r['doping_drugs'] or '').split('|'):
        if d.strip(): drugs.add(d.strip().upper())
print(f'  distinct horses    : {len(horses)}')
print(f'  distinct substances: {len(drugs)}')
print(f'  sample: {[r["horse_name"] for r in rows[:5]]}')

# overlap with the news verdicts
import csv as _csv
vd=list(_csv.DictReader(open('/home/user/asb-archive/pristine/asb_doping_verdicts.csv')))
vnames={v['horse_name'].strip() for v in vd}
overlap=horses & vnames
print(f'\n  horses also covered by news verdicts: {len(overlap)}')
print(f'  horses ONLY in results doping data  : {len(horses-vnames)}')
print(f'    -> these {len(horses-vnames)} exist nowhere else')
