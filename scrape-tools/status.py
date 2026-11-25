#!/usr/bin/env python3
"""Status monitor. Writes a single machine-readable + human-readable report.

Run:  python3 status.py          (prints)
      python3 status.py --push   (also commits STATUS.md to GitHub)
"""
import json, os, subprocess, sys, time, urllib.request

BASE = '/home/user/scrape-2026-11-25'
PAGES = f'{BASE}/pages'
TARGETS = json.load(open(f'{BASE}/targets.json'))
REPO = 'RogerAirs11/basalt-data-vault'


def procs():
    out = []
    for pid in os.listdir('/proc'):
        if not pid.isdigit():
            continue
        try:
            argv = [a.decode('utf-8', 'replace')
                    for a in open(f'/proc/{pid}/cmdline', 'rb').read().split(b'\0') if a]
            if len(argv) < 2 or 'python3' not in os.path.basename(argv[0]):
                continue
            for a in argv[1:]:
                b = os.path.basename(a)
                if b in ('run.py', 'sync.py', 'keepalive.py') and 'scrape' in a:
                    stat = open(f'/proc/{pid}/stat').read().split()
                    rss = int(open(f'/proc/{pid}/status').read().split('VmRSS:')[1].split()[0])
                    out.append({'name': b, 'pid': int(pid),
                                'state': stat[2], 'rss_mb': round(rss / 1024, 1)})
        except (OSError, IndexError, PermissionError):
            continue
    return out


def workspace():
    tot = sz = 0
    for root, _, files in os.walk('/home/user'):
        if set(root.split('/')) & {'.git', 'node_modules', '.cache', '.local', '__pycache__'}:
            continue
        for fn in files:
            tot += 1
            try:
                sz += os.path.getsize(os.path.join(root, fn))
            except OSError:
                pass
    return tot, sz


def gh_shards():
    try:
        tok = json.load(open('/home/user/.horse-private/accounts.json'))['github']
        u = f'https://api.github.com/repos/{REPO}/contents/scrape-2026-11-25/raw'
        r = urllib.request.Request(u, headers={'Authorization': 'Bearer ' + tok,
                                               'Accept': 'application/vnd.github+json',
                                               'User-Agent': 'status'})
        d = json.loads(urllib.request.urlopen(r, timeout=45).read())
        return len(d), sum(x['size'] for x in d)
    except Exception:
        return None, None


def main():
    local = {f[:-4] for f in os.listdir(PAGES) if f.endswith('.txt')}
    tmp = [f for f in os.listdir(PAGES) if f.endswith('.tmp')]
    todo = len(TARGETS) - len(local)
    files, size = workspace()
    shards, shard_bytes = gh_shards()

    # last progress line from run.log
    try:
        lines = [l for l in open(f'{BASE}/run.log').read().splitlines() if l.strip()]
        last_log = lines[-1] if lines else '(empty)'
    except Exception:
        last_log = '(no log)'

    # rate over the last N minutes, using file mtimes
    now = time.time()
    recent = sum(1 for f in local
                 if os.path.exists(os.path.join(PAGES, f + '.txt'))
                 and now - os.path.getmtime(os.path.join(PAGES, f + '.txt')) < 600)
    rate = recent / 10.0  # pages per minute over the last 10 min

    L = []
    L.append(f'# Scrape status — {time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime())}')
    L.append('')
    L.append('## Progress')
    L.append(f'- pages on disk: **{len(local):,}** of {len(TARGETS):,} targets')
    L.append(f'- remaining: {todo:,}')
    L.append(f'- rate (last 10 min): **{rate:.0f}/min**')
    if rate > 0:
        L.append(f'- ETA at this rate: {todo/rate/60:.1f} h')
    L.append(f'- half-written files: {len(tmp)} (should be 0)')
    L.append(f'- last runner log line: `{last_log}`')
    L.append('')
    L.append('## Backup (GitHub)')
    if shards is not None:
        L.append(f'- shards: **{shards}**, {shard_bytes/1024:.0f} KB')
        L.append(f'- backed-up pages: ~{shards * 50:,}')
        L.append(f'- **at risk (scraped but not yet sharded): {max(0, len(local) - shards * 50):,}**')
    else:
        L.append('- ⚠️ could not reach GitHub API')
    L.append('')
    L.append('## Processes')
    ps_ = procs()
    if not ps_:
        L.append('- ⚠️ **NOTHING RUNNING**')
    for p in ps_:
        flag = '⚠️' if p['state'] == 'Z' else '✅'
        L.append(f'- {flag} {p["name"]} pid={p["pid"]} state={p["state"]} rss={p["rss_mb"]} MB')
    L.append('')
    L.append('## Workspace safety')
    L.append(f'- files: {files:,} / 10,000 ({files/100:.1f}%)')
    L.append(f'- size: {size/1048576:.1f} MB / 128 MB ({size/134217728*100:.1f}%)')
    L.append('')
    report = '\n'.join(L)
    print(report)

    if '--push' in sys.argv:
        tok = json.load(open('/home/user/.horse-private/accounts.json'))['github']
        path = 'scrape-2026-11-25/STATUS.md'
        cur = f'https://api.github.com/repos/{REPO}/contents/{path}'
        H = {'Authorization': 'Bearer ' + tok, 'Accept': 'application/vnd.github+json',
             'User-Agent': 'status'}
        sha = None
        try:
            d = json.loads(urllib.request.urlopen(
                urllib.request.Request(cur + '?ref=main', headers=H), timeout=45).read())
            sha = d.get('sha')
        except Exception:
            pass
        import base64
        body = {'message': f'status {time.strftime("%H:%M:%SZ", time.gmtime())}',
                'content': base64.b64encode(report.encode()).decode(), 'branch': 'main'}
        if sha:
            body['sha'] = sha
        req = urllib.request.Request(cur, data=json.dumps(body).encode(),
                                     headers={**H, 'Content-Type': 'application/json'},
                                     method='PUT')
        urllib.request.urlopen(req, timeout=60)
        print('\n(pushed to GitHub)')


if __name__ == '__main__':
    main()
