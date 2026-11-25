import os,subprocess,time,sys
RUN='/home/user/scrape-2026-11-25/run.py'
LOG=open('/home/user/scrape-2026-11-25/run.log','a')
while True:
    time.sleep(60)
    pages=len(os.listdir('/home/user/scrape-2026-11-25/pages'))
    alive=subprocess.run(['pgrep','-f','scrape-2026-11-25/run.py'],capture_output=True).returncode==0
    done=open('/home/user/scrape-2026-11-25/run.log').read().count('DONE')
    if done: print('finished',flush=True); break
    if not alive:
        print(f'[{time.strftime("%H:%M")}] restarting runner (pages={pages})',flush=True)
        subprocess.Popen(['nohup','python3',RUN],stdout=LOG,stderr=LOG,
                         env={**os.environ,'JINA_GAP':'3.05'})
