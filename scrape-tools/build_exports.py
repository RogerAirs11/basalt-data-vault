#!/usr/bin/env python3
"""Turn scraped horse pages into load-ready CSVs.

Outputs (scrape-2026-11-25/out/):
  new_race_rows.csv    one row per race entry, shaped for racing_results
  new_stats_rows.csv   one row per horse, shaped for horse_racing_stats
  new_doping.csv       one row per doping observation
  coverage_report.json counts + validation

Re-runnable: rebuilds from pages/ every time.
"""
import csv,glob,json,os,re,sys
sys.path.insert(0,'/home/user/scrape-2026-11-25')
from parse import parse

OUT='/home/user/scrape-2026-11-25/out'
os.makedirs(OUT,exist_ok=True)
FA='۰۱۲۳۴۵۶۷۸۹'; EN='0123456789'

def jalali_to_gregorian(jy, jm, jd):
    jy += 1595
    days = (-355668 + (365*jy) + ((jy//33)*8) + (((jy%33)+3)//4) + jd
            + ((jm-1)*31 if jm < 7 else ((jm-7)*30)+186))
    gy = 400*(days//146097); days %= 146097
    if days > 36524:
        days -= 1; gy += 100*(days//36524); days %= 36524
        if days >= 365: days += 1
    gy += 4*(days//1461); days %= 1461
    if days > 365: gy += (days-1)//365; days = (days-1)%365
    gd = days+1
    leap = (gy%4==0 and gy%100!=0) or gy%400==0
    sal=[0,31,29 if leap else 28,31,30,31,30,31,31,30,31,30,31]
    gm=0
    while gm < 13 and gd > sal[gm]: gd -= sal[gm]; gm += 1
    return gy, gm, gd

def race_date(label):
    """'هفته 6 یزد ۱۴۰۲/۸/۶ شنبه' -> '2023-10-28'"""
    if not label: return None
    n=str(label).translate(str.maketrans(FA,EN))
    m=re.search(r'(\d{4})/(\d{1,2})/(\d{1,2})',n)
    if not m: return None
    jy,jm,jd=int(m.group(1)),int(m.group(2)),int(m.group(3))
    if not (1300<=jy<=1500 and 1<=jm<=12 and 1<=jd<=31): return None
    gy,gm,gd=jalali_to_gregorian(jy,jm,jd)
    return f'{gy:04d}-{gm:02d}-{gd:02d}'
def num(s):
    if s is None: return None
    s=str(s).translate(str.maketrans(FA,EN)).strip()
    m=re.match(r'^([\d.]+)',s)
    return m.group(1) if m else None

rows=[]; stats=[]; dop=[]; ok=bad=0
for f in sorted(glob.glob('/home/user/scrape-2026-11-25/pages/*.txt')):
    slug=os.path.basename(f)[:-4]
    try: d=parse(slug)
    except Exception: d=None
    if not d or not d.get('name'): bad+=1; continue
    ok+=1
    st,first,sec,third=d.get('starts'),d.get('p1'),d.get('p2'),d.get('p3')
    stats.append({'asbdavani_horse_id':slug,'name':d['name'],'sex':d.get('sex'),
                  'breed':d.get('breed'),'age':d.get('age'),
                  'starts':st,'win':first,'second':sec,'third':third,
                  'ior_1000':d.get('ior_1000'),'ior_1200':d.get('ior_1200'),
                  'ior_distance':d.get('ior_distance'),'ior_best':d.get('ior_best'),
                  'row_count':len(d['races'])})
    for r in d['races']:
        rows.append({'asbdavani_horse_id':slug,'horse_name':d['name'],
                     'race_label':r['race_label'],'week_date':race_date(r['race_label']),
                     'round':r['round'],'class':r['class'],
                     'owner':r['owner'],'coach_name':r['coach'],'rider_name':r['rider'],
                     'distance_m':num(r['distance_m']),'weight':num(r['weight']),
                     'placing':r['placing'],'doping_raw':r['doping'],
                     'time_raw':r['time'],'ior':num(r['ior'])})
        if r['doping']:
            dop.append({'asbdavani_horse_id':slug,'horse_name':d['name'],
                        'race_label':r['race_label'],'week_date':race_date(r['race_label']),
                        'raw':r['doping']})

def dump(fn,data):
    if not data: open(os.path.join(OUT,fn),'w').write(''); return
    with open(os.path.join(OUT,fn),'w',newline='',encoding='utf-8') as fh:
        w=csv.DictWriter(fh,fieldnames=list(data[0].keys())); w.writeheader(); w.writerows(data)

dump('new_race_rows.csv',rows); dump('new_stats_rows.csv',stats); dump('new_doping.csv',dop)
rep={'generated_utc':'2026-11-25','pages_parsed':ok,'pages_failed':bad,
     'race_rows':len(rows),'horse_stats_rows':len(stats),'doping_rows':len(dop),
     'horses_with_doping':len({x['asbdavani_horse_id'] for x in dop}),
     'horses_with_races':len({x['asbdavani_horse_id'] for x in rows})}
json.dump(rep,open(os.path.join(OUT,'coverage_report.json'),'w'),indent=2,ensure_ascii=False)
print(json.dumps(rep,ensure_ascii=False,indent=1))
