#!/usr/bin/env python3
"""Build the registry crosswalk properly.

Bug in v1: normalize() mapped ARABIC yeh/kaf (U+064A/U+0643) to LATIN i/k, so
Arabic-script registry names could never match Persian-script source names.
The registry is written in Arabic script; asbdavani in Persian script.

Folding used here:
  أإآٱ -> ا     ي ى -> ی     ك -> ک     ة -> ه     ؤ->و  ئ->ی
  strip harakat + tatweel, unify ZWNJ, collapse whitespace
"""
import json, re, os, csv, sys, time, urllib.request, urllib.error, datetime, random

BASE = '/home/user/asb-archive'
CACHE = f'{BASE}/loader-input/horses_cache.json'
ACC = json.load(open('/home/user/.horse-private/accounts.json'))
DB = 'f527d88f-c274-4a11-8d17-37dc43ba9027'
URL = f"https://api.cloudflare.com/client/v4/accounts/{ACC['cf_account']}/d1/database/{DB}/query"

def q(sql, params=None, timeout=120):
    body = json.dumps({'sql': sql, 'params': params or []}).encode()
    for _ in range(2):
        req = urllib.request.Request(URL, data=body, headers={
            'Authorization': 'Bearer ' + ACC['cf_token'],
            'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as x:
                r = json.loads(x.read())['result'][0]
                if not r.get('success'):
                    raise RuntimeError(str(r.get('error'))[:200])
                return r['results']
        except urllib.error.HTTPError as e:
            txt = e.read().decode()[:200]
            if 'read limit' in txt:
                raise RuntimeError('CAP:' + txt)
            time.sleep(2)
    raise RuntimeError('query failed')

FOLD = str.maketrans({
    'أ':'ا','إ':'ا','آ':'ا','ٱ':'ا','ا':'ا',
    'ي':'ی','ى':'ی','ئ':'ی','ۍ':'ی',
    'ك':'ک','گ':'گ',
    'ة':'ه','ۀ':'ه','ؤ':'و',
    '٠':'0','١':'1','٢':'2','٣':'3','٤':'4','٥':'5','٦':'6','٧':'7','٨':'8','٩':'9',
    '۰':'0','۱':'1','۲':'2','۳':'3','۴':'4','۵':'5','۶':'6','۷':'7','۸':'8','۹':'9',
})

def norm(s):
    s = (s or '').lower().strip()
    s = s.replace('\u200c', ' ').replace('\u200f', '').replace('\u200e', '')
    s = s.translate(FOLD)
    s = re.sub(r'[\u064b-\u065f\u0670\u0640]', '', s)      # harakat, tatweel
    s = re.sub(r'[^\w\u0600-\u06ff]+', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()

def squash(s):
    """Aggressive form for fuzzy compare: drop spaces and vowel-ish chars."""
    s = norm(s).replace(' ', '')
    for a, b in (('ی',''),('ه',''),('ا',''),('و','')):
        s = s.replace(a, b) if len(s) > 4 else s
    return s

# ---------- load horses (cache to disk so this is a one-time read cost)
if os.path.exists(CACHE):
    horses = json.load(open(CACHE))
    print(f'horses from cache: {len(horses):,}')
else:
    horses, cursor, PAGE = [], 0, 5000
    while True:
        b = q("SELECT id,name_native,name_latin,birth_year FROM horses "
              "WHERE id > ? ORDER BY id LIMIT ?", [cursor, PAGE])
        if not b: break
        horses.extend(b); cursor = b[-1]['id']
        if len(b) < PAGE: break
    json.dump(horses, open(CACHE, 'w'))
    print(f'horses read from D1: {len(horses):,}')

# ---------- indexes
by_name, by_squash = {}, {}
for h in horses:
    for f in ('name_native', 'name_latin'):
        n = norm(h.get(f))
        if n: by_name.setdefault(n, []).append(h)
        s2 = squash(h.get(f))
        if s2: by_squash.setdefault(s2, []).append(h)
print(f'index: {len(by_name):,} names, {len(by_squash):,} squashed')

def match(name, byear=None):
    n = norm(name)
    cands = by_name.get(n) or []
    if not cands:
        cands = by_squash.get(squash(name)) or []
        if not cands:
            return None, 'none'
        if len(cands) == 1:
            return cands[0]['id'], 'squash'
        if byear:
            same = [c for c in cands if str(c.get('birth_year')) == str(byear)]
            if len(same) == 1: return same[0]['id'], 'squash+year'
        return None, 'ambiguous-squash'
    if byear:
        same = [c for c in cands if str(c.get('birth_year')) == str(byear)]
        if len(same) == 1: return same[0]['id'], 'name+year'
    if len(cands) == 1:
        return cands[0]['id'], 'exact'
    return None, 'ambiguous'

def match_year(name, race_year=None, birth_year=None):
    """Resolve ambiguous names using age information.

    The registry stores birth_year; the archive stores the race date and, in
    the profile set, the horse's birthdate. A horse racing in year Y with a
    recorded birth year B should satisfy Y-B between 2 and ~15. When exactly
    one candidate satisfies that, it is a confident match.
    """
    n = norm(name)
    cands = by_name.get(n) or []
    if not cands:
        cands = by_squash.get(squash(name)) or []
    if not cands:
        return None, 'none'
    if birth_year:
        same = [c for c in cands if str(c.get('birth_year')) == str(birth_year)]
        if len(same) == 1:
            return same[0]['id'], 'birthyear'
    if race_year:
        ok = []
        for c in cands:
            by = c.get('birth_year')
            if by is None:
                continue
            try:
                age = int(race_year) - int(by)
            except Exception:
                continue
            if 2 <= age <= 15:
                ok.append(c)
        if len(ok) == 1:
            return ok[0]['id'], 'race-year'
        if len(ok) > 1:
            return None, 'ambiguous-year'
    if len(cands) == 1:
        return cands[0]['id'], 'exact'
    return None, 'ambiguous'


if __name__ == '__main__':
    import collections
    # test on the archive horses
    rows = json.load(open(f'{BASE}/loader-input/results_rows2.json'))
    hname = rows['cols'].index('horse_name')
    seen = {}
    yidx = rows['cols'].index('week_date')
    for r in rows['rows']:
        y = (r[yidx] or '')[:4] if r[yidx] else None
        key = (r[hname], y)
        seen.setdefault(key, 0)
        seen[key] += 1
    stat = collections.Counter()
    uniq = 0
    for (nm, y) in seen:
        gid, how = match_year(nm, race_year=y)
        stat[how] += 1
        uniq += 1
    print(f'\nresult horses (unique names): {uniq}')
    for k, v in stat.most_common():
        print(f'   {k:18s} {v:6d}  {100*v/uniq:5.1f}%')
    # profiles
    prof = json.load(open(f'{BASE}/loader-input/profile_rows.json'))
    pstat = collections.Counter()
    for p in prof:
        gid, how = match_year(p['name'], birth_year=(p['birthdate'] or '')[:4])
        pstat[how] += 1
    n = len(prof)
    print(f'\nprofile rows: {n}')
    for k, v in pstat.most_common():
        print(f'   {k:18s} {v:6d}  {100*v/n:5.1f}%')
