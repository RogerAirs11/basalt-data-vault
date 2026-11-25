#!/usr/bin/env python3
"""Supervisor for the scrape.

Bug this replaces: the old version used `pgrep -f scrape-2026-11-25/run.py`,
which also matches its OWN command line and any shell that merely mentions the
path — so it always believed the scraper was alive and never restarted it.

Here liveness is decided by scanning /proc for a python3 process whose argv[1]
is exactly the script path. No pattern matching, no false positives.
"""
import os, subprocess, time

BASE = '/home/user/scrape-2026-11-25'
PAGES = f'{BASE}/pages'


def running(script):
    """True only if a *python3* process is executing this exact script."""
    want = os.path.realpath(script)
    for pid in os.listdir('/proc'):
        if not pid.isdigit():
            continue
        try:
            argv = open(f'/proc/{pid}/cmdline', 'rb').read().split(b'\0')
            argv = [a.decode('utf-8', 'replace') for a in argv if a]
        except (OSError, PermissionError):
            continue
        if len(argv) >= 2 and 'python3' in os.path.basename(argv[0]):
            for a in argv[1:]:
                if os.path.realpath(a) == want:
                    return True
    return False


def start(script, log):
    print(f'[{time.strftime("%H:%M:%S")}] starting {os.path.basename(script)}', flush=True)
    f = open(log, 'a')
    subprocess.Popen(['python3', script], stdout=f, stderr=f, start_new_session=True)


if __name__ == '__main__':
    rlog = f'{BASE}/run.log'
    slog = f'{BASE}/sync.log'
    while True:
        time.sleep(30)
        try:
            pages = len(os.listdir(PAGES))
            done = 'CHUNK DONE' in open(rlog).read()
            if not running(f'{BASE}/run.py') and not done:
                print(f'  scraper down (pages={pages})', flush=True)
                start(f'{BASE}/run.py', rlog)
            if not running(f'{BASE}/sync.py'):
                start(f'{BASE}/sync.py', slog)
        except Exception as e:
            print('  supervisor error:', e, flush=True)
