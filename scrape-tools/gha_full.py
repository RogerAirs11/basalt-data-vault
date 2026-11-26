#!/usr/bin/env python3
"""Full-fidelity scrape: 4 tabs per horse, raw HTML, resumable.

Why this exists: 1,286 horses were scraped as markdown (via the proxy) before
the GitHub-Actions pivot, which silently lost their race tables — a markdown
table collapses into one cell, so 0 race rows were parsed for those horses.
This re-scrapes every horse at full fidelity and adds the three tabs that were
never collected:

  /info        career summary + race table
  /ratings     full rating-change history   <- never scraped before
  /pedigree    sire/dam with ids
  /productions offspring list

Resumable per TAB, not per horse: a run that dies loses at most one tab of one
horse.
"""
import base64, io, json, os, re, sys, tarfile, threading, time, urllib.request, queue

REPO = os.environ.get('REPO', 'RogerAirs11/basalt-data-vault')
TOKEN = os.environ['GITHUB_TOKEN']
WORKERS = int(os.environ.get('WORKERS', '20'))
MAX_MIN = int(os.environ.get('MAX_MIN', '40'))
FLUSH_EVERY = 25
MAX_PAGES_PER_SHARD = 120
MODE = os.environ.get('MODE', 'missing')   # 'missing' | 'all'
TABS = ['info', 'ratings', 'pedigree', 'productions']

H = {'Authorization': 'Bearer ' + TOKEN, 'Accept': 'application/vnd.github+json',
     'User-Agent': 'gha-full'}
API = f'https://api.github.com/repos/{REPO}'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')


def api(path, method='GET', body=None, retries=4, timeout=300):
    for t in range(retries):
        try:
            data = json.dumps(body).encode() if body else None
            r = urllib.request.Request(f'{API}/{path}', data=data, method=method,
                                       headers={**H, 'Content-Type': 'application/json'})
            with urllib.request.urlopen(r, timeout=timeout) as x:
                return json.loads(x.read())
        except Exception as e:
            if t == retries - 1:
                return {'error': str(e)[:150]}
            time.sleep(2 + t * 3)


def put_file(path, content, message, retries=4):
    for t in range(retries):
        cur = api(f'contents/{path}?ref=main')
        sha = cur.get('sha') if isinstance(cur, dict) and 'sha' in cur else None
        body = {'message': message,
                'content': base64.b64encode(content).decode(), 'branch': 'main'}
        if sha:
            body['sha'] = sha
        if 'content' in api(f'contents/{path}', 'PUT', body, retries=2):
            return True
        time.sleep(3 + t * 4)
    return False


def list_shards(prefix='scrape-2026-11-25/full'):
    """Every shard currently in the repo for this job."""
    d = api(f'contents/{prefix}?ref=main')
    return d if isinstance(d, list) else []


def read_json(path, default):
    d = api(f'contents/{path}?ref=main')
    if isinstance(d, dict) and 'content' in d:
        try:
            return json.loads(base64.b64decode(d['content']))
        except Exception:
            return default
    return default


print('loading state...', flush=True)
targets = read_json('scrape-2026-11-25/targets.json', None)
if not targets:
    raise SystemExit('no targets')
# resume from the shards actually present (authoritative, race-free)
done = set()
_sh = list_shards()
print(f'  existing shards: {len(_sh)}', flush=True)
for _s in _sh:
    try:
        if _s['size'] > 900000:
            _raw = urllib.request.urlopen(
                f"https://raw.githubusercontent.com/{REPO}/main/"
                f"scrape-2026-11-25/full/{_s['name']}", timeout=240).read()
        else:
            _raw = base64.b64decode(api(f"contents/scrape-2026-11-25/full/{_s['name']}")['content'])
        _tf = tarfile.open(fileobj=io.BytesIO(_raw), mode='r:gz')
        for _m in _tf.getmembers():
            _b = os.path.basename(_m.name)
            if '__' in _b:
                _sl, _tb = _b.rsplit('.', 1)[0].split('__', 1)
                done.add(f'{_sl}/{_tb}')
    except Exception:
        pass
print(f'  pages already stored: {len(done)}', flush=True)

if MODE == 'missing':
    legacy = set(read_json('scrape-2026-11-25/legacy_markdown.json', []))
    horses = sorted(legacy)
else:
    horses = list(targets)

work = [(s, t) for s in horses for t in TABS if f'{s}/{t}' not in done]
print(f'horses {len(horses)} | tabs already done {len(done)} | work items {len(work)}',
      flush=True)

q = queue.Queue()
for item in work:
    q.put(item)

buf = {}
bl = threading.Lock()
stats = {'ok': 0, 'fail': 0}
start = time.time()
STOP = start + MAX_MIN * 60
serial = [int(time.time()) % 10000]


def fetch(slug, tab):
    suffix = '/info' if tab == 'info' else f'/{tab}'
    u = f'https://asbdavani.app/performance/horses/{slug}{suffix}'
    r = urllib.request.Request(u, headers={'User-Agent': UA,
                                           'Accept': 'text/html,application/xhtml+xml',
                                           'Accept-Language': 'fa,en;q=0.9'})
    with urllib.request.urlopen(r, timeout=30) as x:
        return x.read()


def worker():
    while time.time() < STOP:
        try:
            slug, tab = q.get_nowait()
        except queue.Empty:
            return
        for attempt in range(3):
            try:
                body = fetch(slug, tab)
                if len(body) > 2000:
                    with bl:
                        buf[f'{slug}/{tab}'] = body
                        stats['ok'] += 1
                        n = stats['ok'] + stats['fail']
                        if n % 200 == 0:
                            el = time.time() - start
                            print(f'  {n}/{len(work)}  {el/60:.1f}min  '
                                  f'{n/el*3600:.0f}/h  fail={stats["fail"]}', flush=True)
                    break
            except Exception:
                time.sleep(0.4 + attempt)


def flush():
    with bl:
        if not buf:
            return
        items = list(buf.items())[:MAX_PAGES_PER_SHARD]
        for k, _ in items:
            buf.pop(k, None)
    payload = dict(items)
    tb = io.BytesIO()
    with tarfile.open(fileobj=tb, mode='w:gz') as tf:
        for key, body in payload.items():
            slug, tab = key.split('/')
            info = tarfile.TarInfo(name=f'{slug}__{tab}.html')
            info.size = len(body)
            info.mtime = int(time.time())
            tf.addfile(info, io.BytesIO(body))
    serial[0] += 1
    name = f'scrape-2026-11-25/full/full-{serial[0]:04d}-{len(payload)}.tar.gz'
    if not put_file(name, tb.getvalue(), f'full scrape: {len(payload)} pages'):
        print(f'  ❌ commit failed for {len(payload)}, re-buffering', flush=True)
        with bl:
            for k, v in payload.items():
                buf.setdefault(k, v)
        return
    # do NOT maintain a counter; report the shard count instead (race-free)
    n = len(list_shards())
    put_file('scrape-2026-11-25/full_status.json',
             json.dumps({'shards': n,
                         'expected_pages': len(horses) * len(TABS),
                         'updated': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())},
                        ensure_ascii=False).encode(),
             f'full_status: {n} shards')
    print(f'  ✅ committed {len(payload)} pages (shard #{n})', flush=True)


ths = [threading.Thread(target=worker, daemon=True) for _ in range(WORKERS)]
[t.start() for t in ths]
last = time.time()
while any(t.is_alive() for t in ths):
    time.sleep(4)
    if time.time() - last >= FLUSH_EVERY:
        flush()
        last = time.time()
while buf:
    flush()
print(f'DONE ok={stats["ok"]} fail={stats["fail"]} in '
      f'{(time.time()-start)/60:.1f}min', flush=True)
