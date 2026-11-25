#!/usr/bin/env python3
"""Scrape horse pages DIRECTLY (no proxy), in parallel, committing ALL progress.

Rewritten after a real failure: the first version kept scraped pages in the
runner's /tmp and only committed them at the end. The job hit its time limit,
so 3,648 of 4,684 pages were scraped and then thrown away with the runner.
The slug list still claimed they were done — a false record.

Fixes:
  1. All scraped bytes are held IN MEMORY (they are small), and the batch is
     committed on a timer every FLUSH_EVERY seconds, never only at the end.
  2. The slug list is only advanced for pages that are inside a COMMITTED
     shard. A page is never recorded as done unless its bytes are in the repo.
  3. Before writing, the previously committed slug list is read fresh, so a
     cancelled run cannot mark uncommitted work as complete.
"""
import base64, io, json, os, sys, tarfile, threading, time, urllib.request, queue

REPO = os.environ.get('REPO', 'RogerAirs11/basalt-data-vault')
TOKEN = os.environ['GITHUB_TOKEN']
WORKERS = int(os.environ.get('WORKERS', '24'))
MAX_MIN = int(os.environ.get('MAX_MIN', '40'))
FLUSH_EVERY = int(os.environ.get('FLUSH_EVERY', '45'))   # seconds
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
    for t in range(retries):
        cur = api(f'contents/{path}?ref=main')
        sha = cur.get('sha') if isinstance(cur, dict) and 'sha' in cur else None
        body = {'message': message,
                'content': base64.b64encode(content).decode(), 'branch': 'main'}
        if sha:
            body['sha'] = sha
        r = api(f'contents/{path}', 'PUT', body, retries=2)
        if 'content' in r:
            return True
        time.sleep(2 + t * 4)
    return False


def read_slugs():
    d = api('contents/scrape-2026-11-25/scraped_slugs.json?ref=main')
    if isinstance(d, dict) and 'content' in d:
        try:
            return set(json.loads(base64.b64decode(d['content'])).get('complete', []))
        except Exception:
            return set()
    return set()


def read_targets():
    d = api('contents/scrape-2026-11-25/targets.json?ref=main')
    if isinstance(d, dict) and 'content' in d:
        return json.loads(base64.b64decode(d['content']))
    raise SystemExit('cannot read targets.json')


# ---- state ----------------------------------------------------------------
print('loading state...', flush=True)
committed = read_slugs()                 # pages PROVEN to be in a shard
targets = read_targets()
todo = [t for t in targets if t not in committed]
print(f'targets {len(targets)} | committed {len(committed)} | todo {len(todo)}', flush=True)

q = queue.Queue()
for t in todo:
    q.put(t)

# in-memory buffer of scraped-but-not-yet-committed pages
buffer = {}          # slug -> bytes
bl = threading.Lock()
stats = {'ok': 0, 'fail': 0}
start = time.time()
STOP = start + MAX_MIN * 60
shard_no = [int(time.time()) % 10000]


def fetch(slug):
    u = f'https://asbdavani.app/performance/horses/{slug}/info'
    r = urllib.request.Request(u, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                      'AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/131.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'fa,en;q=0.9'})
    with urllib.request.urlopen(r, timeout=30) as x:
        return x.read()


def worker():
    while time.time() < STOP:
        try:
            slug = q.get_nowait()
        except queue.Empty:
            return
        for attempt in range(3):
            try:
                body = fetch(slug)
                if len(body) > 2000:
                    with bl:
                        buffer[slug] = body
                        stats['ok'] += 1
                        n = stats['ok'] + stats['fail']
                        if n % 250 == 0:
                            el = time.time() - start
                            print(f"  {n}/{len(todo)}  {el/60:.1f}min  "
                                  f"{n/el*3600:.0f}/h  fail={stats['fail']}", flush=True)
                    break
            except Exception:
                time.sleep(0.5 + attempt)
        else:
            with bl:
                stats['fail'] += 1


def flush():
    """Commit everything buffered. Only then advance the slug list."""
    with bl:
        if not buffer:
            return
        batch = dict(buffer)
        buffer.clear()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tf:
        for slug, body in batch.items():
            info = tarfile.TarInfo(name=slug + '.html')
            info.size = len(body)
            info.mtime = int(time.time())
            tf.addfile(info, io.BytesIO(body))
    shard_no[0] += 1
    name = f'scrape-2026-11-25/raw/gha-{shard_no[0]:04d}-{len(batch)}.tar.gz'
    if not put_file(name, buf.getvalue(), f'gha shard {len(batch)} pages'):
        print(f'  ❌ shard failed, {len(batch)} pages re-queued', flush=True)
        with bl:
            for k, v in batch.items():
                buffer.setdefault(k, v)
        return
    # only now is it honest to say these are done
    now = read_slugs() | set(batch)
    payload = {'complete': sorted(now), 'count': len(now),
               'updated': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    put_file('scrape-2026-11-25/scraped_slugs.json',
             json.dumps(payload, ensure_ascii=False).encode(),
             f'slugs: {len(now)} committed')
    print(f'  ✅ committed {len(batch)} pages -> total {len(now)}', flush=True)


ths = [threading.Thread(target=worker, daemon=True) for _ in range(WORKERS)]
[t.start() for t in ths]
last = time.time()
while any(t.is_alive() for t in ths):
    time.sleep(5)
    if time.time() - last >= FLUSH_EVERY:
        flush()
        last = time.time()
flush()
print(f"DONE ok={stats['ok']} fail={stats['fail']} "
      f"in {(time.time()-start)/60:.1f}min", flush=True)
