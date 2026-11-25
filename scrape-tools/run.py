import json, os, sys, time, threading
sys.path.insert(0,'/home/user/scrape-2026-11-25')
from fetch import get

targets=json.load(open('/home/user/scrape-2026-11-25/targets.json'))
todo=[t for t in targets if not (os.path.exists(f'/home/user/scrape-2026-11-25/pages/{t}.txt')
      and os.path.getsize(f'/home/user/scrape-2026-11-25/pages/{t}.txt')>800)]
print(f'targets {len(targets)}, pending {len(todo)}',flush=True)

WIN=60.0; CAP=18          # 18/min, under the 20 limit for safety margin
lock=threading.Lock(); sent=[]; idx=[0]
st=time.time(); done=[0]; fail=[0]

def acquire():
    with lock:
        while True:
            now=time.time()
            sent[:]=[x for x in sent if now-x < WIN]
            if len(sent) < CAP:
                sent.append(now); return
            wait=WIN-(now-sent[0])+0.1
        # unreachable

def worker():
    while True:
        with lock:
            if idx[0] >= len(todo): return
            t=todo[idx[0]]; idx[0]+=1
        acquire()
        r=get(t,tries=2)
        with lock:
            done[0]+=1
            if r is None: fail[0]+=1
            if done[0]%100==0:
                el=time.time()-st
                print(f'  {done[0]}/{len(todo)}  {el/60:.1f}min  {done[0]/el*3600:.0f}/h  fails={fail[0]}',flush=True)

N=5
ths=[threading.Thread(target=worker,daemon=True) for _ in range(N)]
[t.start() for t in ths]
[t.join() for t in ths]
print(f'DONE {done[0]} in {(time.time()-st)/60:.1f} min, fails={fail[0]}',flush=True)
