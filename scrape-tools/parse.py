import re,json,os
PD='/home/user/scrape-2026-11-25/pages'

def clean(s):
    s=re.sub(r'\[!\[[^\]]*\]\([^)]*\)\]\([^)]*\)','',s)   # image links
    s=re.sub(r'!Image \d+\s*','',s)                          # stray image alt text
    s=re.sub(r'\[([^\]]*)\]\([^)]*\)',r'\1',s)            # links -> text
    s=re.sub(r'\s+',' ',s).strip()
    return s

def parse(slug):
    p=os.path.join(PD,slug+'.txt')
    if not os.path.exists(p): return None
    t=open(p,encoding='utf-8').read()
    out={'slug':slug,'races':[]}
    m=re.search(r'Markdown Content:\s*(.*)',t,re.S)
    body=m.group(1) if m else t
    # name = first heading line
    h=re.search(r'^#+\s*(.+)$',body,re.M)
    out['name']=clean(h.group(1)) if h else None
    # header line: "- 8 ساله مادیان  عرب"
    a=re.search(r'(\d+)\s*ساله\s*(مادیان|نریان|اسب)\s+([^\n|]+)',body)
    if a: out['age'],out['sex'],out['breed']=a.group(1),clean(a.group(2)),clean(a.group(3))
    # ratings block
    for label,key in [('ریتینگ ۱۲۰۰ متر','ior_1200'),('ریتینگ ۱۰۰۰ متر','ior_1000'),
                      ('ریتینگ مسافت','ior_distance'),('بهترین ریتینگ','ior_best'),
                      ('تعداد استارت','starts'),('مقام اول','p1'),('مقام دوم','p2'),('مقام سوم','p3')]:
        pat=re.escape(label)+r'\s*\n+\s*([\d۰-۹]+|-)'
        mm=re.search(pat,body)
        if mm:
            v=mm.group(1).translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹','0123456789'))
            out[key]=None if v=='-' else int(v)
    # race table rows: lines starting with | containing 'هفته'
    rows=[]
    for line in body.split('\n'):
        if not line.strip().startswith('|'): continue
        cells=[clean(c) for c in line.strip().strip('|').split('|')]
        if len(cells)<8: continue
        if 'هفته' not in cells[0] and not re.search(r'هفته',line): continue
        rows.append(cells)
    for c in rows:
        r={}
        head=c[0]
        hm=re.match(r'(.+?)\s*-\s*دور\s*\(?([\d۰-۹]+)\)?',head)
        r['race_label']=clean(hm.group(1)) if hm else head
        r['round']=hm.group(2).translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹','0123456789')) if hm else None
        r['class']=c[1] if len(c)>1 else None
        r['owner']=c[2] if len(c)>2 else None
        r['coach']=c[3] if len(c)>3 else None
        r['rider']=c[4] if len(c)>4 else None
        r['distance_m']=c[5] if len(c)>5 else None
        r['weight']=c[6] if len(c)>6 else None
        pl=(c[7] if len(c)>7 else None) or ''
        r['placing']=None if re.fullmatch(r'0\s*/\s*0',pl.strip()) else pl
        r['doping']=c[8] if len(c)>8 else None
        r['time']=c[9] if len(c)>9 else None
        r['ior']=c[10] if len(c)>10 else None
        r['video']=c[11] if len(c)>11 else None
        out['races'].append(r)
    return out

if __name__=='__main__':
    import sys
    d=parse(sys.argv[1] if len(sys.argv)>1 else 'clpniifd30xrvwrdou43sfs9b')
    print(json.dumps(d,ensure_ascii=False,indent=1)[:2000])
    print('\nPARSED RACES:',len(d['races']))
    print('starts/p1/p2/p3:',d.get('starts'),d.get('p1'),d.get('p2'),d.get('p3'))
