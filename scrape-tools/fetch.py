import json,os,sys,time,random,urllib.request,urllib.error
BASE='https://asbdavani.app/performance/horses/{}/info'
OUT='/home/user/scrape-2026-11-25/pages'
os.makedirs(OUT,exist_ok=True)

def get(slug, tries=3):
    p=os.path.join(OUT,slug+'.txt')
    if os.path.exists(p) and os.path.getsize(p)>800: return open(p,encoding='utf-8').read()
    url='https://r.jina.ai/'+BASE.format(slug)
    for t in range(tries):
        try:
            r=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Accept':'text/plain'})
            d=urllib.request.urlopen(r,timeout=90).read().decode('utf-8','replace')
            if len(d)>500:
                open(p,'w',encoding='utf-8').write(d)
                return d
        except Exception as e:
            time.sleep(2+t*3)
    return None

if __name__=='__main__':
    d=get('clpniifd30xrvwrdou43sfs9b')
    print('bytes:',len(d) if d else 'FAIL')
