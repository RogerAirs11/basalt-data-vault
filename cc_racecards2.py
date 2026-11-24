import json,urllib.request,gzip,re,csv,os,time
UA={'User-Agent':'Mozilla/5.0 (research)'}
OUT=os.path.dirname(os.path.abspath(__file__))
d=json.load(open(f'{OUT}/cc_urls3.json'))
cards=[x for x in d if '/racecards/' in x['url'] and '?' in x['url']]
byk={}
for x in cards:
    k=x['url'].split('?')[0]
    if k not in byk or x['timestamp']>byk[k]['timestamp']: byk[k]=x
cards=list(byk.values())
print('unique racecards:',len(cards),flush=True)
F=['horse_id','horse_name','birthdate','sex','starts','p1','p2','p3','race_id','race_date',
   'distance_m','breed','age_class','weight','doping_status','doping_drugs','rider','coach',
   'horse_number','source_url','source_ts','source']
path=f'{OUT}/cc_horse_profiles_v2.csv'
new=not os.path.exists(path)
f=open(path,'a',newline='',encoding='utf8'); w=csv.DictWriter(f,fieldnames=F)
if new: w.writeheader()
def fix(s):
    try: return s.encode('latin1').decode('utf8')
    except Exception: return s
tot=ok=fail=dop=0
for i,t in enumerate(cards,1):
    off=int(t['offset']); ln=int(t['length'])
    html=''
    for _ in range(3):
        try:
            req=urllib.request.Request(f"https://data.commoncrawl.org/{t['filename']}",
                headers={**UA,'Range':f'bytes={off}-{off+ln-1}'})
            with urllib.request.urlopen(req,timeout=60) as x: raw=x.read()
            html=gzip.decompress(raw).decode('utf8','replace'); break
        except Exception: time.sleep(1.5)
    if not html: fail+=1; continue
    ch=re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)',html,re.S)
    blob=''.join(ch)
    try: blob=blob.encode().decode('unicode_escape')
    except Exception: pass
    # race context
    rdate=re.search(r'"date":"(\d{4}-\d{2}-\d{2})',blob)
    dist=re.search(r'"distance":(\d+)',blob)
    breed=re.search(r'"blood":"([A-Z_]+)"',blob)
    age=re.search(r'"age":"([A-Z0-9_]+)"',blob)
    rid=re.search(r'"(?:race|id)":"(cl[a-z0-9]{20,})"',blob)
    got=0
    for m in re.finditer(r'\{"id":"(cl[a-z0-9]{20,})","weight":([\d.]+),"doping":(null|\{.*?\}),"horse":\{"id":"(cl[a-z0-9]{20,})","birthdate":"([^"]*)","name":"(.*?)","sex":"([A-Z]+)","starts":(\d+),"p1":(\d+),"p2":(\d+),"p3":(\d+)',blob):
        dm=m.group(3); ds=''; dd=''
        if dm and dm!='null':
            ms=re.search(r'"status":"([A-Z_]+)"',dm); ds=ms.group(1) if ms else ''
            names=set(re.findall(r'"(?:engName|faName)":"([^"]+)"',dm))
            dd='|'.join(sorted(names))
            ds=ds or 'POSITIVE'
            dop+=1
        seg=blob[m.start():m.start()+1200]
        rd=re.search(r'"rider":\{"id":"cl[a-z0-9]+","name":"(.*?)"',seg)
        cd=re.search(r'"coach":\{"id":"cl[a-z0-9]+","name":"(.*?)"',seg)
        wn=re.search(r'"number":(\d+)',seg)
        w.writerow({'horse_id':m.group(4),'horse_name':fix(m.group(6)),'birthdate':m.group(5)[:10],
          'sex':m.group(7),'starts':m.group(8),'p1':m.group(9),'p2':m.group(10),'p3':m.group(11),
          'race_id':rid.group(1) if rid else '','race_date':rdate.group(1) if rdate else '',
          'distance_m':dist.group(1) if dist else '','breed':breed.group(1) if breed else '',
          'age_class':age.group(1) if age else '','weight':m.group(2),
          'doping_status':ds,'doping_drugs':dd,'rider':fix(rd.group(1)) if rd else '',
          'coach':fix(cd.group(1)) if cd else '','horse_number':wn.group(1) if wn else '',
          'source_url':t['url'],'source_ts':t['timestamp'],'source':'commoncrawl-racecard'})
        tot+=1; got+=1
    if got: ok+=1
    if i%50==0:
        f.flush(); print(f'  {i}/{len(cards)} | {tot} horses | dop {dop} | fail {fail}',flush=True)
    time.sleep(0.08)
f.close()
print(f'DONE cards_ok={ok} fail={fail} horse_rows={tot} doping={dop}')
