import concurrent.futures as cf, json, os, sys, time
sys.path.insert(0,'/home/user/scrape-2026-11-25')
from fetch import get
targets=json.load(open('/home/user/scrape-2026-11-25/targets.json'))
todo=[t for t in targets if not (os.path.exists(f'/home/user/scrape-2026-11-25/pages/{t}.txt')
      and os.path.getsize(f'/home/user/scrape-2026-11-25/pages/{t}.txt')>800)]
print(f'targets {len(targets)}, already done {len(targets)-len(todo)}, todo {len(todo)}',flush=True)
C=32; st=time.time(); done=0; fail=[]
with cf.ThreadPoolExecutor(C) as ex:
    futs={ex.submit(get,t):t for t in todo}
    for f in cf.as_completed(futs):
        done+=1
        if f.result() is None: fail.append(futs[f])
        if done%200==0:
            el=time.time()-st
            print(f'  {done}/{len(todo)}  {el/60:.1f}min  {done/el*3600:.0f}/h  fails={len(fail)}',flush=True)
el=time.time()-st
print(f'DONE {done} in {el/60:.1f} min, fails={len(fail)}',flush=True)
json.dump(fail,open('/home/user/scrape-2026-11-25/failed.json','w'))
