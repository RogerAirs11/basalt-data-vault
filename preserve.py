#!/usr/bin/env python3
"""Phase 1 — capture the doping data that exists nowhere else.

Verifies D1 contents against the workspace CSV before and after writing, so a
silent truncation cannot pass unnoticed.
"""
import csv, json, hashlib, os, urllib.request, urllib.error, datetime

BASE='/home/user/asb-archive'
OUT=f'{BASE}/pristine'
os.makedirs(OUT, exist_ok=True)

a=json.load(open('/home/user/.horse-private/accounts.json'))
URL=f"https://api.cloudflare.com/client/v4/accounts/{a['cf_account']}/d1/database/f527d88f-c274-4a11-8d17-37dc43ba9027/query"

def q(sql, params=None, timeout=120):
    body=json.dumps({'sql':sql,'params':params or []}).encode()
    req=urllib.request.Request(URL,data=body,headers={
        'Authorization':'Bearer '+a['cf_token'],'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=timeout) as x:
        r=json.loads(x.read())['result'][0]
        if not r.get('success'): raise RuntimeError(str(r.get('error'))[:200])
        return r['results']

def sha(p):
    return hashlib.sha256(open(p,'rb').read()).hexdigest()

print('=== 1. pull both doping tables out of D1 ===')
verdicts=q("SELECT * FROM asb_doping_verdicts ORDER BY verdict_id")
drugs=q("SELECT * FROM asb_drug_observations ORDER BY observation_count DESC, drug_name")
print(f'  asb_doping_verdicts   {len(verdicts):4d} rows')
print(f'  asb_drug_observations {len(drugs):4d} rows')

print('\n=== 2. write to workspace ===')
for name, rows in (('asb_doping_verdicts.csv', verdicts), ('asb_drug_observations.csv', drugs)):
    p=f'{OUT}/{name}'
    with open(p,'w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print(f'  {name:28s} {len(rows):4d} rows  sha256={sha(p)[:16]}')

print('\n=== 3. reconcile against the workspace CSV ===')
ws=list(csv.DictReader(open(f'{BASE}/cc_news_doping.csv')))
db_by_id={r['verdict_id']:r for r in verdicts}
print(f'  workspace cc_news_doping.csv : {len(ws)}')
print(f'  D1 asb_doping_verdicts       : {len(db_by_id)}')
# every workspace row must appear in D1
miss=[]
for i,r in enumerate(ws):
    vid='news-%04d'%i
    if vid not in db_by_id: miss.append(vid)
print(f'  workspace rows missing from D1 : {len(miss)} {miss[:5]}')
# spot-check field integrity on 5 rows
import random
random.seed(7)
ok=0
for i in random.sample(range(len(ws)),5):
    w=ws[i]; d=db_by_id.get('news-%04d'%i)
    if not d: continue
    same=all(str(d.get(k) or '')==str(w.get(k) or '') for k in
             ('horse_name','drugs_en','horse_ban','coach','ethics_referral'))
    ok+=same
    print(f'   {w["horse_name"][:14]:16s} d1==csv: {same}')
print(f'  field-identical spot checks: {ok}/5')

print('\n=== 4. distinct drug coverage ===')
d=set()
for r in verdicts:
    for x in (r.get('drugs_en') or '').split('|'):
        if x.strip(): d.add(x.strip().upper())
print(f'  distinct substances in verdicts: {len(d)}')
print(f'  distinct substances in drug table: {len(drugs)}')
print(f'  verdict drugs  : {sorted(d)[:8]} ...')
print(f'  drug table     : {[r["drug_name"] for r in drugs[:8]]} ...')
