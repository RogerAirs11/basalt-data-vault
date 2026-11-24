#!/usr/bin/env python3
"""Harvest every asbdavani news article body from CommonCrawl and extract
Persian doping verdicts.

Key insight: a /news page snapshot carries the target article PLUS 5-6 sidebar
articles, and neither the page <title> nor the ref order identifies which is
which. But every body starts with its own heading, e.g.
  "نتایج دوپینگ هفته پنجم مسابقات اسبدوانی کورس بهار ۱۴۰۴ گنبد"
so we harvest ALL bodies from ALL pages, dedupe by content hash, and let each
body identify itself. Coverage ends up higher than the page count.

Verdict line:
  <horse> (کورس <race>, مقام <place>) - مربی: <coach> -
  داروهای ردیابی شده: <drugs> - محرومیت اسب: <ban> -
  جریمه و محرومیت مربی: <fine> [+ معرفی به کمیته اخلاق]
"""
import json, gzip, re, urllib.request, csv, hashlib, os, sys, time

UA = {'User-Agent': 'Mozilla/5.0 (compatible; archive-research/1.0)'}
OUT = 'cc_news_doping.csv'
ART = 'cc_news_articles.csv'
VF = ['article_key','article_heading','horse_name','race_no','place','coach',
      'drugs_fa','drugs_en','horse_ban','coach_fine','ethics_referral','raw_verdict',
      'source_url','source_ts']
AF = ['article_key','heading','body_chars','verdicts','source_url','source_ts']

AR2EN = {'۰':'0','۱':'1','۲':'2','۳':'3','۴':'4','۵':'5','۶':'6','۷':'7','۸':'8','۹':'9',
         '٠':'0','١':'1','٢':'2','٣':'3','٤':'4','٥':'5','٦':'6','٧':'7','٨':'8','٩':'9'}

DRUG_MAP = {
 'کافئین':'CAFFEINE','تئوفیلین':'THEOPHYLLINE','افدرین':'EPHEDRINE','نور افدرین':'NOREPHEDRINE',
 'فنیل بوتازون':'PHENYLBUTAZONE','فنیل‌بوتازون':'PHENYLBUTAZONE','فینل بوتازون':'PHENYLBUTAZONE',
 'اکسی فنیل بوتازون':'OXYPHENYLBUTAZONE','اکسی‌فنیل بوتازون':'OXYPHENYLBUTAZONE',
 'مورفین':'MORPHINE','کدئین':'CODEINE','کودیین':'CODEINE',
 'فلونیکسین':'FLUNIXINE','فلونکسین':'FLUNIXINE','فلونکسن':'FLUNIXINE','فلوپنیکسین':'FLUNIXINE',
 'دگزامتازون':'DEXAMETHASONE','دگزا متازون':'DEXAMETHASONE','دکسامتازون':'DEXAMETHASONE',
 'کتوپروفن':'KETOPROFEN','لوانیزول':'LEVAMISOLE','لوامیزول':'LEVAMISOLE',
 'دی ایزوپروپیل آمین':'DIISOPROPYLAMIN','دی‌ایزوپروپیل‌آمین':'DIISOPROPYLAMIN',
 'کلن بوترول':'CLENBUTEROL','کلنبوترول':'CLENBUTEROL',
 'متامفتامین':'METHAMPHETAMINE','آمفتامین':'AMPHETAMINE','کوکائین':'COCAINE',
 'تستوسترون':'TESTOSTERONE','ناندورلون':'NANDROLONE','استانوزولول':'STANOZOLOL',
 'بولدنون':'BOLDENONE','پروکائین':'PROCAINE','نوسکاپین':'NOSCAPINE','ایزوآمینیل':'ISOAMINILE',
 'دسومتیل ترامادول':'DESMETHYLTRAMADOL','ترامادول':'TRAMADOL','تبائین':'THEBAINE',
 'متیل پردنیزولون':'METHYLPREDNISOLONE','آتنولول':'ATENOLOL','لیگنوکائین':'LIGNOCAINE',
 'زایلازین':'XYLAZINE','هیدروکسی زایلازین':'HYDROXYZINE','ناپروکسن':'NAPROXEN',
 'مپریدین':'MEPERIDINE','دیکلوفناک':'DICLOFENAC','آمپیرون':'AMPYRONE',
 'آنتی پیرین':'ANTIPYRINE','آنتی‌پیرین':'ANTIPYRINE','متیل آمینو آنتی پیرین':'METHYLAMINO ANTIPYRINE',
 'فوروزماید':'FUROSEMIDE','لازیکس':'FUROSEMIDE','هیدروکلروتیازید':'HYDROCHLOROTHIAZIDE',
 'پرازپام':'PRAZEPAM','دیازپام':'DIAZEPAM','کلردیازپوکساید':'CHLORDIAZEPOXIDE',
 'فنتانیل':'FENTANYL','بوپرنورفین':'BUPRENORPHINE','پنتازوسین':'PENTAZOCINE',
 'مکلوکسیکام':'MELOXICAM','کارپروفن':'CARPROFEN','استیل سیستئین':'ACETYLCYSTEINE',
 'فنیل افرین':'PHENYLEPHRINE','سالبوتامول':'SALBUTAMOL','پردنیزولون':'PREDNISOLONE',
 'هیدروکورتیزون':'HYDROCORTISONE','اپی نفرین':'EPINEPHRINE','نوراپی نفرین':'NOREPINEPHRINE',
 'پیروکسیکام':'PIROXICAM','فلورفنیکل':'FLORFENICOL','اکسی تتراسایکلین':'OXYTETRACYCLINE',
}

def translate(drugs_fa):
    out = []
    for raw in [x.strip() for x in re.split(r'[,،]', drugs_fa or '') if x.strip()]:
        clean = re.sub(r'\([^)]*\)', '', raw).strip()
        en = DRUG_MAP.get(clean)
        if not en:
            for k, v in sorted(DRUG_MAP.items(), key=lambda kv: -len(kv[0])):
                if k in clean:
                    en = v; break
        if not en:
            # parenthesised latin name inside the persian, if any
            m = re.search(r'\(([A-Za-z][A-Za-z \-]{3,})\)', raw)
            en = m.group(1).upper() if m else clean.upper()
        out.append(en)
    # collapse spelling variants so counts are not split
    NORM = {'FLUNIXIN':'FLUNIXINE','TESTESTRONE':'TESTOSTERONE','OXI PHENYLBUTAZONE':'OXYPHENYLBUTAZONE',
            'OXY PHENYL BUTAZONE':'OXYPHENYLBUTAZONE','PHENYLBUTAZON':'PHENYLBUTAZONE',
            'DEXAMETAZONE':'DEXAMETHASONE','KETOPROFEN':'KETOPROFEN','THEOPHYLIN':'THEOPHYLLINE',
            'CAFFEIN':'CAFFEINE','MORPHIN':'MORPHINE','CLENBUTEROL HCL':'CLENBUTEROL',
            'METHYL PREDNISOLONE':'METHYLPREDNISOLONE'}
    out = [NORM.get(x, x) for x in out]
    return '|'.join(dict.fromkeys(out))

def fetch(r):
    url = f"https://data.commoncrawl.org/{r['filename']}"
    off, ln = int(r['offset']), int(r['length'])
    for _ in range(3):
        try:
            req = urllib.request.Request(url, headers={**UA, 'Range': f'bytes={off}-{off+ln-1}'})
            with urllib.request.urlopen(req, timeout=30) as x:
                raw = x.read()
            try: return gzip.decompress(raw).decode('utf-8', 'replace')
            except Exception: return raw.decode('utf-8', 'replace')
        except Exception:
            time.sleep(2)
    return None

def decode_flight(html):
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html, re.S)
    dec = []
    for c in chunks:
        try: dec.append(json.loads('"' + c + '"'))
        except Exception: dec.append(c)
    return ''.join(dec)

def strip_html(s):
    s = re.sub(r'<figure.*?</figure>', ' ', s, flags=re.S)
    s = re.sub(r'<br\s*/?>', '\n', s)
    s = re.sub(r'</p>', '\n', s)
    s = re.sub(r'<[^>]+>', ' ', s)
    for a, b in (('&nbsp;',' '),('&amp;','&'),('&quot;','"'),('&#x27;',"'"),('&lt;','<'),('&gt;','>')):
        s = s.replace(a, b)
    s = re.sub(r'[ \t]+', ' ', s)
    return s

VERDICT = re.compile(
    # Two layouts exist on the site. Older posts prefix the horse with "اسب " and
    # use singular "داروی ردیابی شده"; newer ones drop the prefix and use plural
    # "داروهای ردیابی شده". Both are matched here.
    r'(?:^|\n|اخلاق)(?:اسب\s*)?([^\n<>()]{2,60}?)\s*\(\s*(?:[^()،,\n]{0,22}?[،,]\s*)?کورس\s*([^,،)\n]{1,25})\s*[،,]\s*مقام\s*([^)\n]{1,20})\s*\)\s*[-–—]\s*'
    r'مربی\s*:\s*([^\-–—\n]{2,60}?)\s*[-–—]\s*'
    r'دارو(?:ی|های)\s*ردیابی\s*شده\s*:\s*([^\-–—\n]{2,300}?)\s*[-–—]\s*'
    r'محرومیت\s*اسب\s*:\s*([^\-–—\n]{1,90}?)\s*'
    r'(?:[-–—]\s*جریمه\s*و\s*محرومیت\s*مربی\s*:\s*([^\-–—\n]{1,160}?))?\s*'
    r'(?:[-–—+]\s*معرفی\s*به\s*کمیته\s*اخلاق)?\s*(?=\n|$|اسب)')

LATIN_DRUGS = {
 'methylprednisolone':'METHYLPREDNISOLONE','prednisolone':'PREDNISOLONE','levamisole':'LEVAMISOLE',
 'triamcinolone':'TRIAMCINOLONE','acetonid':'TRIAMCINOLONE ACETONIDE','acetonide':'TRIAMCINOLONE ACETONIDE',
 'dexamethasone':'DEXAMETHASONE','papaverine':'PAPAVERINE','phenylbutazone':'PHENYLBUTAZONE',
 'morphine':'MORPHINE','caffeine':'CAFFEINE','theophylline':'THEOPHYLLINE','ephedrine':'EPHEDRINE',
 'codeine':'CODEINE','ketoprofen':'KETOPROFEN','flunixin':'FLUNIXINE','clenbuterol':'CLENBUTEROL',
 'testosterone':'TESTOSTERONE','stanozolol':'STANOZOLOL','nandrolone':'NANDROLONE',
 'boldenone':'BOLDENONE','amphetamine':'AMPHETAMINE','methamphetamine':'METHAMPHETAMINE',
 'cocaine':'COCAINE','procaine':'PROCAINE','thebaine':'THEBAINE','noscapine':'NOSCAPINE',
 'xylazine':'XYLAZINE','detomidine':'DETOMIDINE','acepromazine':'ACEPROMAZINE','atenolol':'ATENOLOL',
 'naproxen':'NAPROXEN','meperidine':'MEPERIDINE','diclofenac':'DICLOFENAC','antipyrine':'ANTIPYRINE',
 'aminopyrine':'AMINOPYRINE','metamizole':'METAMIZOLE','dipyrone':'DIPYRONE','furosemide':'FUROSEMIDE',
 'hydrochlorothiazide':'HYDROCHLOROTHIAZIDE','prednisone':'PREDNISONE','betamethasone':'BETAMETHASONE',
 'isoflupredone':'ISOFLUPREDONE','flumethasone':'FLUMETHASONE','triamcinolone acetonide':'TRIAMCINOLONE ACETONIDE',
 'salbutamol':'SALBUTAMOL','albuterol':'SALBUTAMOL','terbutaline':'TERBUTALINE','guanabenz':'GUANABENZ',
 'reserpine':'RESERPINE','omeprazole':'OMEPRAZOLE','cimetidine':'CIMETIDINE','ranitidine':'RANITIDINE',
}
def translate_latin(s):
    parts = [x.strip() for x in re.split(r'[,،;]', s or '') if x.strip()]
    out = []
    for p in parts:
        key = re.sub(r'[^a-z ]', '', p.lower()).strip()
        out.append(LATIN_DRUGS.get(key, re.sub(r'[^A-Za-z0-9 ]', '', p).upper().strip()))
    NORM = {'FLUNIXIN':'FLUNIXINE','TESTESTRONE':'TESTOSTERONE','OXI PHENYLBUTAZONE':'OXYPHENYLBUTAZONE',
            'OXY PHENYL BUTAZONE':'OXYPHENYLBUTAZONE','METHYL PREDNISOLONE':'METHYLPREDNISOLONE',
            'TRIAMCINOLONE ACETONID':'TRIAMCINOLONE ACETONIDE','AMINOPYRINE':'METAMIZOLE','DIPYRONE':'METAMIZOLE'}
    return '|'.join(dict.fromkeys(NORM.get(x, x) for x in out if x))

def is_latin(s):
    return bool(s) and not re.search(r'[\u0600-\u06FF]', s)

def translate_any(s):
    return translate_latin(s) if is_latin(s) else translate(s)

def main():
    news = json.load(open('/tmp/news_urls.json'))
    seen = {}
    for r in news:
        p = re.sub(r'https?://[^/]+', '', r['url']).split('?')[0].rstrip('/')
        if p not in seen: seen[p] = r
    todo = list(seen.values())
    print(f'pages to fetch: {len(todo)}', flush=True)

    bodies = {}      # sha1 -> dict
    pages_ok = pages_fail = 0
    for i, r in enumerate(todo):
        html = fetch(r)
        if not html:
            pages_fail += 1; continue
        blob = decode_flight(html)
        refs = list(re.finditer(r'([0-9a-f]{1,3}):T([0-9a-f]{2,6}),', blob))
        got = 0
        for m0 in refs:
            L = int(m0.group(2), 16)
            if L < 400 or L > 400000: continue
            b = blob[m0.end(): m0.end() + L]
            if '<p' not in b: continue
            text = strip_html(b)
            # the flight segment can bleed into the next record ("e:[\"$\",...")
            # which glues metadata onto the last verdict. Cut at that marker.
            for cut in ('e:[\"$\"', ':[\"$\",\"$L'):
                ci = text.find(cut)
                if ci > 200: text = text[:ci]
            if 'دوپینگ' not in text and 'دارو' not in text: continue
            # verdicts are often packed into ONE <p>, separated by
            # "... + معرفی به کمیته اخلاق اسب <next horse>". Insert the newline
            # the regex boundary needs.
            text = text.replace('کمیته اخلاق', 'کمیته اخلاق\n')
            key = hashlib.sha1(re.sub(r'\s+', '', text).encode()).hexdigest()[:16]
            if key not in bodies:
                head = ''
                for line in text.split('\n'):
                    line = line.strip()
                    if len(line) > 15: head = line; break
                bodies[key] = {'heading': head, 'text': text, 'url': r['url'],
                               'ts': r.get('timestamp', ''), 'L': L}
                got += 1
        pages_ok += 1
        if (i+1) % 25 == 0:
            print(f'  [{i+1}/{len(todo)}] pages_ok={pages_ok} fail={pages_fail} unique_bodies={len(bodies)}', flush=True)
    print(f'PAGES ok={pages_ok} fail={pages_fail} | unique bodies={len(bodies)}', flush=True)

    # ---- collapse truncated CommonCrawl snapshots of the same article ----
    # Several captures hold only part of a body, so the same article appears
    # with different lengths. Keep the longest (most complete) one per heading.
    def hkey(h):
        h = re.sub(r'\s+', ' ', h or '').strip()
        return h[:70]
    byh = {}
    for k, b in bodies.items():
        hk = hkey(b['heading'])
        if hk not in byh or b['L'] > byh[hk]['L']:
            byh[hk] = b
    print(f'  collapsed {len(bodies)} bodies -> {len(byh)} distinct articles', flush=True)
    bodies = {k: v for k, v in byh.items()}

    # ---- extract verdicts
    vrows, arows = [], []
    for key, b in bodies.items():
        found = []
        seenv = set()
        for m in VERDICT.finditer(b['text']):
            horse = re.sub(r'\s+', ' ', m.group(1)).strip(' -–—')
            horse = re.sub(r'^اسب\s+', '', horse).strip()
            if len(horse) < 2: continue
            if any(k in horse for k in ('دارو', 'مربی', 'کورس', 'مقام', 'نتایج', 'هفته', 'مسابقات', 'دوپینگ')):
                continue
            drugs_fa = re.sub(r'\s+', ' ', m.group(5)).strip()
            if not drugs_fa: continue
            vk = (horse, drugs_fa, m.group(6))
            if vk in seenv: continue
            seenv.add(vk)
            row = {'article_key': key, 'article_heading': b['heading'],
                   'horse_name': horse,
                   'race_no': re.sub(r'\s+', ' ', m.group(2)).strip(),
                   'place': re.sub(r'\s+', ' ', m.group(3)).strip(),
                   'coach': re.sub(r'\s+', ' ', m.group(4)).strip(),
                   'drugs_fa': drugs_fa, 'drugs_en': translate_any(drugs_fa),
                   'horse_ban': re.sub(r'\s+', ' ', m.group(6)).strip(),
                   'coach_fine': re.sub(r'\s+', ' ', m.group(7) or '').strip(),
                   'ethics_referral': 'yes' if 'کمیته اخلاق' in m.group(0) else 'no',
                   'raw_verdict': re.sub(r'\s+', ' ', m.group(0)).strip(),
                   'source_url': b['url'], 'source_ts': b['ts']}
            found.append(row)
        vrows.extend(found)
        arows.append({'article_key': key, 'heading': b['heading'], 'body_chars': len(b['text']),
                      'verdicts': len(found), 'source_url': b['url'], 'source_ts': b['ts']})

    # global dedupe: one case per (horse, drug set, ban)
    uniq = {}
    for r in vrows:
        k = (r['horse_name'].strip(), r['drugs_en'].strip(), r['horse_ban'].strip())
        if k not in uniq or len(r['raw_verdict']) > len(uniq[k]['raw_verdict']):
            uniq[k] = r
    vrows = list(uniq.values())
    print(f'  global dedupe -> {len(vrows)} distinct cases', flush=True)
    vrows.sort(key=lambda r: (r['article_heading'], r['horse_name']))
    arows.sort(key=lambda r: (-r['verdicts'], r['heading']))
    with open(OUT, 'w', newline='') as f:
        w = csv.DictWriter(f, VF); w.writeheader(); w.writerows(vrows)
    with open(ART, 'w', newline='') as f:
        w = csv.DictWriter(f, AF); w.writeheader(); w.writerows(arows)
    withdrugs = sum(1 for r in vrows if r['drugs_en'])
    print(f'DONE verdicts={len(vrows)} with_drugs={withdrugs} articles_with_verdicts={sum(1 for a in arows if a["verdicts"])} total_articles={len(arows)}', flush=True)

if __name__ == '__main__':
    main()
