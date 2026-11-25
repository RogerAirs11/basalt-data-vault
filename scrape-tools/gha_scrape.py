#!/usr/bin/env python3
"""Scrape horse pages DIRECTLY (no proxy), in parallel, committing progress as
it goes. Designed to run inside GitHub Actions, where direct access works and
there is no 20/min proxy limit.

Resume-safe: reads scraped_slugs.json from the repo, skips anything already done,
commits every SHARD_SIZE pages so a cancelled run loses almost nothing.
"""
import base64, io, json, os, sys, tarfile, threading, time, urllib.request, queue

REPO = os.environ.get('REPO', 'RogerAirs11/basalt-data-vault')
TOKEN = os.environ['GITHUB_TOKEN']
PAGES_DIR = '/tmp/pages'
SHARD_SIZE = int(os.environ.get('SHARD_SIZE', '100'))
WORKERS = int(os.environ.get('WORKERS', '24'))
MAX_MIN = int(os.environ.get('MAX_MIN', '50'))
os.makedirs(PAGES_DIR, exist_ok=True)

H = {'Authorization': 'Bearer ' + TOKEN, 'Accept': 'application/vnd.github+json',
     'User-Agent': 'gha-scrape'}
API = f'https://api.github.com/repos/{REPO}'


def api(path, method='GET', body=None, retries=4):
    for t in range(retries):
        try:
            data = json.dumps(body).encode() if body else None
            r = urllib.request.Request(f'{API}/{path}', data=data, method=method,
                                       headers={**H, 'Content-Type': 'application/json'})
            with urllib.request.urlopen(r, timeout=120) as x:
                return json.loads(x.read())
        except Exception as e:
            if t == retries - 1:
                return {'error': str(e)[:150]}
            time.sleep(2 + t * 3)


def put_file(path, content, message, retries=5):
    """Commit a file, retrying on sha races (concurrent shards)."""
    for t in range(retries):
        cur = api(f'contents/{path}?ref=main')
        sha = cur.get('sha') if isinstance(cur, dict) and 'sha' in cur else None
        body = {'message': message,
                'content': base64.b64encode(content).decode(),
                'branch': 'main'}
        if sha:
            body['sha'] = sha
        r = api(f'contents/{path}', 'PUT', body, retries=2)
        if 'content' in r:
            return True
        time.sleep(2 + t * 4)
    return False


def load_done():
    """Everything already scraped, from the committed slug list + shards."""
    done = set()
    d = api('contents/scrape-2026-11-25/scraped_slugs.json?ref=main')
    if isinstance(d, dict) and 'content' in d:
        try:
            done |= set(json.loads(base64.b64decode(d['content']))['complete'])
        except Exception:
            pass
    return done


def load_targets():
    d = api('contents/scrape-2026-11-25/targets.json?ref=main')
    if isinstance(d, dict) and 'content' in d:
        return json.loads(base64.b64decode(d['content']))
    raise SystemExit('cannot read targets.json')


print('loading state...', flush=True)
done = load_done()
targets = load_targets()
todo = [t for t in targets if t not in done]
print(f'targets {len(targets)} | already done {len(done)} | todo {len(todo)}', flush=True)

q = queue.Queue()
for t in todo:
    q.put(t)

got = []
glock = threading.Lock()
stats = {'ok': 0, 'fail': 0}
start = time.time()
STOP = start + MAX_MIN * 60


def fetch(slug):
    u = f'https://asbdavani.app/performance/horses/{slug}/info'
    r = urllib.request.Request(u, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                      'AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/131.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'fa,en;q=0.9',
    })
    with urllib.request.urlopen(r, timeout=30) as x:
        return x.read()


def worker():
    while time.time() < STOP:
        try:
            slug = q.get_nowait()
        except queue.Empty:
            return
        ok = False
        for attempt in range(3):
            try:
                body = fetch(slug)
                if len(body) > 2000:
                    p = os.path.join(PAGES_DIR, slug + '.html')
                    open(p + '.tmp', 'wb').write(body)
                    os.replace(p + '.tmp', p)
                    ok = True
                    break
            except Exception:
                time.sleep(0.5 + attempt)
        with glock:
            stats['ok' if ok else 'fail'] += 1
            if ok:
                got.append(slug)
            n = stats['ok'] + stats['fail']
            if n % 250 == 0:
                el = time.time() - start
                print(f"  {n}/{len(todo)}  {el/60:.1f}min  {n/el*3600:.0f}/h  "
                      f"fail={stats['fail']}", flush=True)


def flush(final=False):
    """Commit everything scraped so far as a shard + updated slug list."""
    with glock:
        batch = list(got)
        got.clear()
    if not batch:
        return
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tf:
        for slug in batch:
            p = os.path.join(PAGES_DIR, slug + '.html')
            if os.path.exists(p):
                tf.add(p, arcname=slug + '.html')
    ts = time.strftime('%H%M%S', time.gmtime())
    name = f'scrape-2026-11-25/raw/gha-{ts}-{len(batch)}.tar.gz'
    if put_file(name, buf.getvalue(), f'gha shard: {len(batch)} pages'):
        print(f'  ✅ committed {name} ({len(batch)} pages)', flush=True)
    else:
        print(f'  ❌ commit failed for {len(batch)} pages', flush=True)

    # update the authoritative slug list
    d = api('contents/scrape-2026-11-25/scraped_slugs.json?ref=main')
    complete = set()
    if isinstance(d, dict) and 'content' in d:
        try:
            complete = set(json.loads(base64.b64decode(d['content']))['complete'])
        except Exception:
            pass
    complete |= set(batch)
    payload = {'complete': sorted(complete), 'count': len(complete),
               'updated': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    put_file('scrape-2026-11-25/scraped_slugs.json',
             json.dumps(payload, ensure_ascii=False).encode(),
             f'slugs: {len(complete)} complete')
    print(f'  slug list now {len(complete)}', flush=True)


ths = [threading.Thread(target=worker, daemon=True) for _ in range(WORKERS)]
[t.start() for t in ths]

# commit periodically while working
while any(t.is_alive() for t in ths):
    time.sleep(60)
    flush()
flush(final=True)

print(f"DONE ok={stats['ok']} fail={stats['fail']} "
      f"in {(time.time()-start)/60:.1f}min", flush=True)
