#!/usr/bin/env python3
"""Continuously back the scrape up to GitHub.

Strategy:
  - raw pages -> incremental tarball shards, one per N pages (permanent, no duplication)
  - parsed CSVs -> rebuilt and overwritten each cycle (small)
  - progress.json -> overwritten each cycle

Uses the Contents API so no local git clone is needed (keeps the workspace small
and avoids the 128 MB snapshot cap).
"""
import base64, io, json, os, tarfile, time, urllib.request, urllib.error

REPO='RogerAirs11/basalt-data-vault'
BRANCH='main'
BASE='/home/user/scrape-2026-11-25'
PAGES=os.path.join(BASE,'pages')
STATE=os.path.join(BASE,'sync_state.json')
SHARD_SIZE=100

tok=json.load(open('/home/user/.horse-private/accounts.json'))['github']
H={'Authorization':'Bearer '+tok,'Accept':'application/vnd.github+json','User-Agent':'scraper-sync'}

def api(path, method='GET', body=None):
    url=f'https://api.github.com/repos/{REPO}/{path}'
    data=json.dumps(body).encode() if body else None
    r=urllib.request.Request(url,data=data,headers={**H,'Content-Type':'application/json'},method=method)
    try:
        with urllib.request.urlopen(r,timeout=120) as x: return json.loads(x.read())
    except urllib.error.HTTPError as e:
        return {'error':e.code,'detail':e.read().decode()[:200]}

def put_file(path, content: bytes, message):
    """Create or update a file on GitHub."""
    cur=api(f'contents/{path}?ref={BRANCH}')
    sha=cur.get('sha') if isinstance(cur,dict) and 'sha' in cur else None
    body={'message':message,'content':base64.b64encode(content).decode(),'branch':BRANCH}
    if sha: body['sha']=sha
    return api(f'contents/{path}','PUT',body)

def load_state():
    if os.path.exists(STATE): return json.load(open(STATE))
    return {'shards':0,'sharded':[],'last_sync':None}

def save_state(s):
    s['last_sync']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
    json.dump(s,open(STATE,'w'),indent=1)

def cycle(s):
    pages=sorted(os.listdir(PAGES))
    have={p[:-4] for p in pages}
    unsharded=[p for p in sorted(have) if p not in set(s['sharded'])]

    # 1. raw shard when we have a full batch
    if len(unsharded) >= SHARD_SIZE:
        batch=unsharded[:SHARD_SIZE]
        buf=io.BytesIO()
        with tarfile.open(fileobj=buf,mode='w:gz') as tf:
            for slug in batch:
                tf.add(os.path.join(PAGES,slug+'.txt'),arcname=slug+'.txt')
        s['shards']+=1
        name=f'scrape-2026-11-25/raw/batch-{s["shards"]:04d}.tar.gz'
        r=put_file(name,buf.getvalue(),f'scrape raw batch {s["shards"]:04d} ({len(batch)} pages)')
        if 'error' in r: return False, f'shard failed {r}'
        s['sharded']+=batch
        print(f'  shard {s["shards"]:04d}: {len(batch)} pages, {len(buf.getvalue())/1024:.0f} KB',flush=True)

    # 2. parsed exports + progress
    import subprocess
    subprocess.run(['python3',os.path.join(BASE,'build_exports.py')],capture_output=True)
    prog={'pages_scraped':len(have),'targets':5647,'shards':s['shards'],
          'updated':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
          'note':'continuous backup; raw pages in raw/*.tar.gz, load-ready CSVs alongside'}
    put_file('scrape-2026-11-25/progress.json',json.dumps(prog,indent=1).encode(),f'scrape progress {len(have)} pages')
    for fn in ['new_race_rows.csv','new_stats_rows.csv','new_doping.csv','coverage_report.json']:
        p=os.path.join(BASE,'out',fn)
        if os.path.exists(p):
            put_file(f'scrape-2026-11-25/out/{fn}',open(p,'rb').read(),f'parsed {fn} ({len(have)} pages)')
    save_state(s)
    return True,'ok'

if __name__=='__main__':
    s=load_state()
    print(f'sync starting: {len(s["sharded"])} already sharded, {s["shards"]} shards',flush=True)
    while True:
        try:
            ok,msg=cycle(s)
            if not ok: print(' ',msg,flush=True)
        except Exception as e:
            print('  sync error:',type(e).__name__,str(e)[:150],flush=True)
        time.sleep(180)
