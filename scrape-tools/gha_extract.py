#!/usr/bin/env python3
"""Extract race + doping + summary data from the scraped HTML in the repo.

Runs inside GitHub Actions (fast, no sandbox limits). Downloads each shard,
parses every page, and commits CSV output.

The HTML is a Next.js RSC payload: the race table is a real <table> in the
server-rendered markup, so plain text extraction works — this was validated
against the live page for پناه کاسیت (9 starts / 3 wins / 1 second / 4 thirds,
11 race rows, MORPHINE positive).
"""
import base64, csv, io, json, os, re, sys, tarfile, time, urllib.request
from html import unescape

REPO = os.environ.get('REPO', 'RogerAirs11/basalt-data-vault')
TOKEN = os.environ['GITHUB_TOKEN']
H = {'Authorization': 'Bearer ' + TOKEN, 'Accept': 'application/vnd.github+json',
     'User-Agent': 'gha-extract'}
API = f'https://api.github.com/repos/{REPO}'
RAW = f'https://raw.githubusercontent.com/{REPO}/main'
FA = '۰۱۲۳۴۵۶۷۸۹'
EN = '0123456789'


def api(path, method='GET', body=None, retries=4, timeout=240):
    for t in range(retries):
        try:
            data = json.dumps(body).encode() if body else None
            r = urllib.request.Request(f'{API}/{path}', data=data, method=method,
                                       headers={**H, 'Content-Type': 'application/json'})
            with urllib.request.urlopen(r, timeout=timeout) as x:
                return json.loads(x.read())
        except Exception as e:
            if t == retries - 1:
                return {'error': str(e)[:150]}
            time.sleep(3 + t * 4)


def put_file(path, content, message, retries=4):
    for t in range(retries):
        cur = api(f'contents/{path}?ref=main')
        sha = cur.get('sha') if isinstance(cur, dict) and 'sha' in cur else None
        body = {'message': message,
                'content': base64.b64encode(content).decode(), 'branch': 'main'}
        if sha:
            body['sha'] = sha
        if 'content' in api(f'contents/{path}', 'PUT', body, retries=2):
            return True
        time.sleep(3 + t * 4)
    return False


def jalali_to_gregorian(jy, jm, jd):
    jy += 1595
    days = (-355668 + 365 * jy + (jy // 33) * 8 + ((jy % 33) + 3) // 4 + jd
            + ((jm - 1) * 31 if jm < 7 else (jm - 7) * 30 + 186))
    gy = 400 * (days // 146097); days %= 146097
    if days > 36524:
        days -= 1; gy += 100 * (days // 36524); days %= 36524
        if days >= 365: days += 1
    gy += 4 * (days // 1461); days %= 1461
    if days > 365:
        gy += (days - 1) // 365; days = (days - 1) % 365
    gd = days + 1
    leap = (gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0
    mon = [0, 31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 0
    while gm < 13 and gd > mon[gm]:
        gd -= mon[gm]; gm += 1
    return gy, gm, gd


def race_date(label):
    if not label:
        return None
    n = str(label).translate(str.maketrans(FA, EN))
    m = re.search(r'(\d{4})/(\d{1,2})/(\d{1,2})', n)
    if not m:
        return None
    jy, jm, jd = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1300 <= jy <= 1500 and 1 <= jm <= 12 and 1 <= jd <= 31):
        return None
    gy, gm, gd = jalali_to_gregorian(jy, jm, jd)
    return f'{gy:04d}-{gm:02d}-{gd:02d}'


def strip_tags(s):
    s = re.sub(r'<script[^>]*>.*?</script>', ' ', s, flags=re.S | re.I)
    s = re.sub(r'<style[^>]*>.*?</style>', ' ', s, flags=re.S | re.I)
    s = re.sub(r'<[^>]+>', ' ', s)
    s = unescape(s)
    return re.sub(r'[ \t\u200c]+', ' ', s).strip()


def parse_page(slug, html):
    """Return summary dict + list of race row dicts."""
    text = strip_tags(html)
    out = {'asbdavani_horse_id': slug}
    # name: first h1-ish heading
    m = re.search(r'<h[12][^>]*>([\s\S]{1,300}?)</h[12]>', html, re.S | re.I)
    if m:
        out['name'] = strip_tags(m.group(1))[:80]
    else:
        t = re.search(r'<title[^>]*>([\s\S]{1,200}?)</title>', html, re.S | re.I)
        nm = strip_tags(t.group(1)) if t else ''
        out['name'] = re.sub(r'^عملکرد اسب\s*|\s*\|.*$', '', nm).strip()[:80] or None
    # summary numbers sit next to their Persian labels
    for label, key in [('تعداد استارت', 'starts'), ('مقام اول', 'win'),
                       ('مقام دوم', 'second'), ('مقام سوم', 'third'),
                       ('بهترین ریتینگ', 'ior_best'), ('ریتینگ مسافت', 'ior_distance'),
                       ('ریتینگ ۱۲۰۰ متر', 'ior_1200'), ('ریتینگ ۱۰۰۰ متر', 'ior_1000')]:
        # the value sits immediately after the label; keep the window tight and
        # stop at the next Persian letter so we never swallow the next label's digit
        mm = re.search(re.escape(label) + r'[\s\S]{0,30}?([0-9۰-۹]+|-)', text)
        if mm:
            v = mm.group(1).translate(str.maketrans(FA, EN))
            out[key] = None if v == '-' else int(v)
        else:
            out[key] = None
    # age / sex / breed line: "8 ساله مادیان عرب"
    a = re.search(r'(\d+)\s*ساله\s*(مادیان|نریان|اسب)\s*([^\s|]{0,20})', text)
    out['age'] = int(a.group(1)) if a else None
    out['sex'] = a.group(2) if a else None
    out['breed'] = a.group(3) if a else None

    races = []
    # Race rows are div-grids (no <tr>), and each row carries a racecard link:
    #   <a href="/racecards/<race_id>?round=N"><div>هفته 13 گنبدکاووس ۱۴۰۳/۱۰/۲۷ ...</div></a>
    # Split the table body on the racecard link so each chunk is one row.
    for chunk in re.split(r'(?=<a[^>]+href="/racecards/)', html):
        if '/racecards/' not in chunk:
            continue
        idm = re.search(r'href="/racecards/([a-z0-9]+)\?round=(\d+)', chunk)
        if not idm:
            continue
        t = strip_tags(chunk)
        dm = re.search(r'(\d{4}/\d{1,2}/\d{1,2})', t.translate(str.maketrans(FA, EN)))
        if not dm:
            continue
        # the label runs until the next cell; keep it short
        label = re.split(r'\s{2,}|کلاس|هندیکاپ|کاندیشن|Maiden', t)[0][:120]
        cells = [strip_tags(c) for c in re.findall(r'<td[^>]*>([\s\S]*?)</td>', chunk, re.I)]
        doping = ''
        for c in cells:
            cc = c.replace('|', ' ').strip()
            if re.fullmatch(r'[A-Z0-9 ,()\-/&+]{4,}', cc) and re.search(r'[A-Z]{4,}', cc):
                doping = cc
                break
        # locating the placing: a cell like "1 / 0" or "3 / 4.5"
        placing = ''
        for c in cells:
            if re.fullmatch(r'\d+\s*/\s*[\d.]+', c.strip()):
                placing = c.strip()
                break
        races.append({
            'asbdavani_horse_id': slug,
            'horse_name': out['name'],
            'race_id': idm.group(1),
            'round': idm.group(2),
            'week_date': race_date(t),
            'race_label': label,
            'placing': placing,
            'doping_raw': doping[:200],
            'cells': ' | '.join(cells)[:500],
        })
    return out, races


def main():
    d = api('contents/scrape-2026-11-25/raw')
    shards = [x for x in d if x['name'].endswith('.tar.gz')]
    print(f'shards: {len(shards)}', flush=True)

    stats_rows, race_rows, dop_rows = [], [], []
    seen = set()
    pages = 0
    for i, s in enumerate(shards, 1):
        raw_url = f"{RAW}/scrape-2026-11-25/raw/{s['name']}"
        try:
            data = urllib.request.urlopen(raw_url, timeout=300).read()
        except Exception as e:
            print(f'  {s["name"]}: download failed {e}', flush=True)
            continue
        try:
            tf = tarfile.open(fileobj=io.BytesIO(data), mode='r:gz')
        except Exception:
            continue
        members = [m for m in tf.getmembers() if m.size > 1000]
        for m in members:
            slug = os.path.basename(m.name).rsplit('.', 1)[0]
            if slug in seen:
                continue
            seen.add(slug)
            try:
                body = tf.extractfile(m).read().decode('utf-8', 'replace')
            except Exception:
                continue
            if m.name.endswith('.txt'):        # markdown from the proxy runs
                body = '<tr><td>' + body.replace('\n', '</td></tr><tr><td>') + '</td></tr>'
            summ, races = parse_page(slug, body)
            stats_rows.append(summ)
            race_rows.extend(races)
            for r in races:
                if r['doping_raw']:
                    dop_rows.append({'asbdavani_horse_id': slug, 'horse_name': summ['name'],
                                     'week_date': r['week_date'], 'raw': r['doping_raw']})
            pages += 1
        if i % 10 == 0:
            print(f'  {i}/{len(shards)} shards, {pages} pages, {len(race_rows)} races, '
                  f'{len(dop_rows)} doping', flush=True)

    print(f'parsed {pages} pages | races {len(race_rows)} | doping {len(dop_rows)}', flush=True)

    def to_csv(rows, fields):
        if not rows:
            return b''
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)
        return buf.getvalue().encode('utf-8-sig')

    sf = ['asbdavani_horse_id', 'name', 'age', 'sex', 'breed', 'starts', 'win',
          'second', 'third', 'ior_best', 'ior_distance', 'ior_1200', 'ior_1000']
    rf = ['asbdavani_horse_id', 'horse_name', 'week_date', 'race_label', 'cells', 'doping_raw']
    df = ['asbdavani_horse_id', 'horse_name', 'week_date', 'raw']

    for name, rows, fields in [('horse_summary.csv', stats_rows, sf),
                               ('race_rows.csv', race_rows, rf),
                               ('doping_rows.csv', dop_rows, df)]:
        ok = put_file(f'scrape-2026-11-25/extracted/{name}',
                      to_csv(rows, fields), f'{name}: {len(rows)} rows')
        print(f'  {name}: {len(rows)} rows -> {"committed" if ok else "FAILED"}', flush=True)


if __name__ == '__main__':
    main()
