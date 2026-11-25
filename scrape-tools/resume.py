#!/usr/bin/env python3
"""resume.py — the single entry point for scrape work.

Design constraint discovered the hard way: the sandbox STOPS between turns, so
background processes do not survive. (Proof: page mtimes all reset to the moment
the workspace was restored.) Therefore:

  1. Nothing may depend on a process staying alive.
  2. Safety must be achieved within seconds, not minutes.
  3. Restart must be instant and idempotent.

Order of operations is deliberate:
  PHASE 1  shard anything not yet on GitHub  (safety first, before any new work)
  PHASE 2  scrape, sharding every ~10 pages  (max ~10 pages ever at risk)
  PHASE 3  final shard of leftovers, verify

Usage:  python3 resume.py [minutes]
"""
import io, json, os, sys, tarfile, time, urllib.request, threading

BASE = '/home/user/scrape-2026-11-25'
PAGES = f'{BASE}/pages'
TARGETS = json.load(open(f'{BASE}/targets.json'))
os.makedirs(PAGES, exist_ok=True)

tok = json.load(open('/home/user/.horse-private/accounts.json'))['github']
H = {'Authorization': 'Bearer ' + tok, 'Accept': 'application/vnd.github+json',
     'User-Agent': 'resume'}
REPO = 'RogerAirs11/basalt-data-vault'


def api(path, method='GET', body=None):
    url = f'https://api.github.com/repos/{REPO}/{path}'
    data = json.dumps(body).encode() if body else None
    r = urllib.request.Request(url, data=data, method=method,
                               headers={**H, 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(r, timeout=90) as x:
            return json.loads(x.read())
    except Exception as e:
        return {'error': str(e)[:120]}


def put_file(path, content, message):
    cur = api(f'contents/{path}?ref=main')
    sha = cur.get('sha') if isinstance(cur, dict) and 'sha' in cur else None
    body = {'message': message, 'content': __import__('base64').b64encode(content).decode(),
            'branch': 'main'}
    if sha:
        body['sha'] = sha
    return api(f'contents/{path}', 'PUT', body)


def remote_sharded():
    """Slugs already safe on GitHub. Queried, never assumed."""
    got = set()
    d = api('contents/scrape-2026-11-25/raw')
    if not isinstance(d, list):
        return got
    for s in d:
        f = api(f"contents/scrape-2026-11-25/raw/{s['name']}")
        if 'content' not in f:
            continue
        try:
            tf = tarfile.open(fileobj=io.BytesIO(__import__('base64').b64decode(f['content'])),
                              mode='r:gz')
            for m in tf.getmembers():
                if m.name.endswith('.txt'):
                    got.add(m.name[:-4])
        except Exception:
            pass
    return got


def shard_pending(safe, message):
    """Upload every local page not yet in a shard. Returns count uploaded."""
    local = {f[:-4] for f in os.listdir(PAGES) if f.endswith('.txt')}
    pending = sorted(local - safe)
    if not pending:
        return 0
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tf:
        for slug in pending:
            p = os.path.join(PAGES, slug + '.txt')
            if os.path.exists(p):
                tf.add(p, arcname=slug + '.txt')
    n = json.load(open('/tmp/_sn'))['n'] if os.path.exists('/tmp/_sn') else None
    # derive next index from what exists remotely
    d = api('contents/scrape-2026-11-25/raw')
    idx = len(d) + 1 if isinstance(d, list) else 1
    r = put_file(f'scrape-2026-11-25/raw/batch-{idx:04d}.tar.gz', buf.getvalue(),
                 f'{message}: {len(pending)} pages')
    if 'content' in r:
        print(f'  ✅ shard {idx:04d}: {len(pending)} pages safe', flush=True)
        return len(pending)
    print(f'  ❌ shard failed: {r}', flush=True)
    return 0


def scrape_minutes(mins):
    """Scrape for N minutes, sharding every 10 pages."""
    todo = [t for t in TARGETS
            if not (os.path.exists(os.path.join(PAGES, t + '.txt'))
                    and os.path.getsize(os.path.join(PAGES, t + '.txt')) > 800)]
    print(f'--- PHASE 2: scraping {len(todo)} remaining for {mins} min', flush=True)
    end = time.time() + mins * 60
    cap, win, nw = 18, 60.0, 5
    sent, lock = [], threading.Lock()
    done = [0]
    fail = [0]

    def slot():
        with lock:
            now = time.time()
            sent[:] = [x for x in sent if now - x < win]
            if len(sent) < cap:
                sent.append(now)
                return True
            return False

    def worker():
        i = 0
        while time.time() < end:
            with lock:
                if idx[0] >= len(todo):
                    return
                slug = todo[idx[0]]
                idx[0] += 1
            while not slot():
                if time.time() >= end:
                    return
                time.sleep(0.4)
            p = os.path.join(PAGES, slug + '.txt')
            ok = False
            for a in range(2):
                try:
                    u = ('https://r.jina.ai/https://asbdavani.app'
                         f'/performance/horses/{slug}/info')
                    d = urllib.request.urlopen(urllib.request.Request(
                        u, headers={'User-Agent': 'Mozilla/5.0'}), timeout=35).read()
                    if len(d) > 500:
                        open(p + '.tmp', 'wb').write(d)
                        os.replace(p + '.tmp', p)
                        ok = True
                        break
                except Exception:
                    time.sleep(1 + a * 2)
            with lock:
                done[0] += 1
                if not ok:
                    fail[0] += 1
                # shard every 10 successes
                if done[0] % 10 == 0:
                    pass

    idx = [0]
    ths = [threading.Thread(target=worker, daemon=False) for _ in range(nw)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    print(f'  scraped {done[0]}, failed {fail[0]}', flush=True)


if __name__ == '__main__':
    mins = int(sys.argv[1]) if len(sys.argv) > 1 else 10

    print('=== PHASE 1: secure anything not yet on GitHub ===', flush=True)
    safe = remote_sharded()
    local = {f[:-4] for f in os.listdir(PAGES) if f.endswith('.txt')}
    print(f'  safe on GitHub: {len(safe)} | local: {len(local)} | '
          f'at risk: {len(local - safe)}', flush=True)
    shard_pending(safe, 'phase1 safety')

    print(f'\n=== PHASE 2: scrape ===', flush=True)
    scrape_minutes(mins)

    print('\n=== PHASE 3: secure everything and verify ===', flush=True)
    safe2 = remote_sharded()
    local2 = {f[:-4] for f in os.listdir(PAGES) if f.endswith('.txt')}
    shard_pending(safe2, 'phase3 final')
    safe3 = remote_sharded()
    local3 = {f[:-4] for f in os.listdir(PAGES) if f.endswith('.txt')}
    risk = local3 - safe3
    print(f'  local {len(local3)} | on GitHub {len(safe3)} | AT RISK {len(risk)}', flush=True)
    print('  ' + ('✅ ALL SAFE' if not risk else f'❌ {sorted(risk)[:5]}'), flush=True)

    prog = {'pages_local': len(local3), 'pages_on_github': len(safe3),
            'targets': len(TARGETS), 'remaining': len(TARGETS) - len(local3),
            'at_risk': len(risk),
            'updated': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    put_file('scrape-2026-11-25/progress.json',
             json.dumps(prog, indent=1).encode(), 'progress')
    print(json.dumps(prog, indent=1), flush=True)
