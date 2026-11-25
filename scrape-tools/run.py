#!/usr/bin/env python3
"""Scrape missing horse pages, paced by a single token bucket.

Deadlock history: earlier versions slept while holding the pacing lock, so all
workers froze. Here workers NEVER sleep holding a lock; they poll take_slot().
"""
import json, os, time, threading, urllib.request, queue

BASE = '/home/user/scrape-2026-11-25'
PAGES = os.path.join(BASE, 'pages')
os.makedirs(PAGES, exist_ok=True)
TARGETS = json.load(open(os.path.join(BASE, 'targets.json')))
todo = [t for t in TARGETS
        if not (os.path.exists(os.path.join(PAGES, t + '.txt'))
                and os.path.getsize(os.path.join(PAGES, t + '.txt')) > 800)]
print(f'targets {len(TARGETS)}, pending {len(todo)}', flush=True)

CAP = 18          # requests allowed per window
WIN = 60.0        # window in seconds
NW = 5            # worker threads
q = queue.Queue()
for t in todo:
    q.put(t)

sent = []
slock = threading.Lock()
done = [0]
fail = [0]
st = time.time()
MAXRUN = int(os.environ.get('MAX_RUNTIME', '10800'))


def take_slot():
    """Try to claim one request slot. Never sleeps."""
    with slock:
        now = time.time()
        sent[:] = [x for x in sent if now - x < WIN]
        if len(sent) < CAP:
            sent.append(now)
            return True
        return False


def worker():
    while True:
        if time.time() - st > MAXRUN:
            return
        try:
            slug = q.get_nowait()
        except queue.Empty:
            return
        p = os.path.join(PAGES, slug + '.txt')
        ok = False
        for attempt in range(2):
            while not take_slot():
                if time.time() - st > MAXRUN:
                    return
                time.sleep(0.5)
            try:
                u = ('https://r.jina.ai/https://asbdavani.app'
                     f'/performance/horses/{slug}/info')
                req = urllib.request.Request(
                    u, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'text/plain'})
                d = urllib.request.urlopen(req, timeout=40).read().decode('utf-8', 'replace')
                if len(d) > 500:
                    tmp = p + '.tmp'
                    open(tmp, 'w', encoding='utf-8').write(d)
                    os.replace(tmp, p)      # atomic write, never a half file
                    ok = True
                    break
            except Exception:
                time.sleep(1 + attempt * 2)
        done[0] += 1
        if not ok:
            fail[0] += 1
        if done[0] % 100 == 0:
            el = time.time() - st
            print(f'  {done[0]}/{len(todo)}  {el/60:.1f}min  '
                  f'{done[0]/el*3600:.0f}/h  fails={fail[0]}', flush=True)
        q.task_done()


ths = [threading.Thread(target=worker, daemon=False) for _ in range(NW)]
for t in ths:
    t.start()
for t in ths:
    t.join()
print(f'CHUNK DONE after {(time.time()-st)/60:.1f}min: {done[0]} tried, '
      f'{fail[0]} failed, {len(os.listdir(PAGES))} on disk', flush=True)
