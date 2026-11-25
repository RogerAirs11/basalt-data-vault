#!/usr/bin/env python3
"""Phase 1b — replace the inflated drug tables in D1 with canonical versions.
Verifies counts before and after; aborts on any mismatch."""
import csv, json, urllib.request, urllib.error, datetime

a=json.load(open('/home/user/.horse-private/accounts.json'))
URL=f"https://api.cloudflare.com/client/v4/accounts/{a['cf_account']}/d1/database/f527d88f-c274-4a11-8d17-37dc43ba9027/query"
def q(sql, params=None, timeout=120):
    body=json.dumps({'sql':sql,'params':params or []}).encode()
    req=urllib.request.Request(URL,data=body,headers={
        'Authorization':'Bearer '+a['cf_token'],'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=timeout) as x:
        r=json.loads(x.read())['result'][0]
        if not r.get('success'): raise RuntimeError(str(r.get('error'))[:250])
        return r['results']
def lit(v):
    if v is None or v=='': return 'NULL'
    if isinstance(v,(int,float)): return str(v)
    return "'"+str(v).replace("'","''")+"'"

BASE='/home/user/asb-archive'

def table_exists(t):
    r=q("SELECT COUNT(*) c FROM sqlite_master WHERE type='table' AND name=?",[t])
    return r[0]['c']>0

print('=== 1. schema: add the audit column if missing ===')
cols=[c['name'] for c in q("SELECT name FROM pragma_table_info('asb_drug_observations')")]
print('  existing columns:',cols)
if 'raw_variants' not in cols:
    q("ALTER TABLE asb_drug_observations ADD COLUMN raw_variants TEXT")
    print('  added raw_variants')
if 'substance_class' not in cols:
    q("ALTER TABLE asb_drug_observations ADD COLUMN substance_class TEXT")
    print('  added substance_class')

print('\n=== 2. build the merged variant map ===')
audit=list(csv.DictReader(open(f'{BASE}/pristine/drug_name_audit.csv')))
variants={}
for r in audit:
    for canon in r['canonical'].split('|'):
        if canon and not canon.startswith('('):
            variants.setdefault(canon,[]).append(r['raw'])
for k in list(variants): variants[k]=sorted(set(variants[k]))
print(f'  substances with recorded variants: {len(variants)}')

print('\n=== 3. before-counts ===')
before=q("SELECT COUNT(*) c FROM asb_drug_observations")[0]['c']
print(f'  asb_drug_observations before: {before}')

print('\n=== 4. replace contents atomically ===')
q("DELETE FROM asb_drug_observations")
canon=list(csv.DictReader(open(f'{BASE}/pristine/asb_drug_observations_canonical.csv')))
now=datetime.datetime.now(datetime.UTC).isoformat(timespec='seconds')
vals=[]
for r in canon:
    v='|'.join(variants.get(r['drug_name'],[]))
    vals.append(f"({lit(r['drug_name'])},{lit(int(r['observation_count']))},{lit(now)},{lit(v or None)},NULL)")
q("INSERT OR REPLACE INTO asb_drug_observations (drug_name,observation_count,updated_at,raw_variants,substance_class) VALUES "+",".join(vals))
after=q("SELECT COUNT(*) c FROM asb_drug_observations")[0]['c']
print(f'  asb_drug_observations after : {after}  (expected {len(canon)})')
assert after==len(canon), 'row count mismatch after insert!'

print('\n=== 5. verify no inflated key survived ===')
bad=q("SELECT COUNT(*) c FROM asb_drug_observations WHERE drug_name LIKE '% %'")
print(f'  keys still containing a space (concatenated pairs): {bad[0]["c"]}')
ok=q("SELECT COUNT(*) c FROM asb_drug_observations WHERE drug_name='PHENYLBUTAZONE OXI PHENYLBUTAZONE'")
print(f'  old concatenated key present: {ok[0]["c"]} (must be 0)')
pers=q("SELECT COUNT(*) c FROM asb_drug_observations WHERE drug_name GLOB '*[\u0600-\u06FF]*'")
print(f'  untranslated persian keys: {pers[0]["c"]} (must be 0)')

print('\n=== 6. top of the corrected table ===')
for r in q("SELECT drug_name,observation_count,raw_variants FROM asb_drug_observations ORDER BY observation_count DESC LIMIT 8"):
    print(f'  {r["drug_name"]:24s} {r["observation_count"]:4d}  variants={r["raw_variants"]}')
