#!/usr/bin/env python3
"""Shard every 10 unscrapped-unsafe pages, continuously. Keeps risk <= ~10 pages."""
import sys,time
sys.path.insert(0,'/home/user/scrape-2026-11-25')
import resume, os
safe=resume.remote_sharded()
while True:
    local={f[:-4] for f in os.listdir(resume.PAGES) if f.endswith('.txt')}
    risk=local-safe
    if len(risk)>=10:
        n=resume.shard_pending(safe,'microsync')
        if n: safe=resume.remote_sharded()
    time.sleep(30)
