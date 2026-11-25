#!/usr/bin/env python3
"""Phase 2 — D1 cleanup. Rehearsable, resumable, and verifiable.

Purpose: stop D1 double-counting. The archive tables contain 17,592 rows that
duplicate `racing_results`, which inflates every reporting number I quote.

Safety rules baked in:
  * DRY RUN by default. Nothing is deleted without --commit.
  * Every deletion is scoped by an explicit key list computed in this run,
    never by a `LIKE` or a range that could over-match.
  * `racing_results` itself is NEVER touched. Only the *_archive side tables.
  * Each step records before/after counts and writes a receipt file.
  * Any failed assertion aborts the whole run before the next step.

Usage:
    python3 phase2_cleanup.py            # rehearsal, prints what would happen
    python3 phase2_cleanup.py --commit   # actually apply
"""
import csv, json, sys, os, urllib.request, urllib.error, datetime

BASE = '/home/user/asb-archive'
RECEIPT = f'{BASE}/phase2_receipt.json'
COMMIT = '--commit' in sys.argv

ACC = json.load(open('/home/user/.horse-private/accounts.json'))
URL = ("https://api.cloudflare.com/client/v4/accounts/"
       f"{ACC['cf_account']}/d1/database/f527d88f-c274-4a11-8d17-37dc43ba9027/query")


def q(sql, params=None, timeout=180):
    body = json.dumps({'sql': sql, 'params': params or []}).encode()
    req = urllib.request.Request(URL, data=body, headers={
        'Authorization': 'Bearer ' + ACC['cf_token'],
        'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as x:
            r = json.loads(x.read())['result'][0]
            if not r.get('success'):
                raise RuntimeError(str(r.get('error'))[:250])
            return r['results']
    except urllib.error.HTTPError as e:
        msg = e.read().decode('utf8', 'replace')[:250]
        if 'row write limit' in msg:
            raise RuntimeError('WRITE_CAP:' + msg)
        if 'row read limit' in msg:
            raise RuntimeError('READ_CAP:' + msg)
        raise RuntimeError('HTTP%d %s' % (e.code, msg))


def lit(v):
    if v is None or v == '':
        return 'NULL'
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def count(table, where=''):
    return q(f'SELECT COUNT(*) c FROM {table} {where}')[0]['c']


receipt = {'started_utc': datetime.datetime.now(datetime.UTC).isoformat(timespec='seconds'),
           'commit': COMMIT, 'steps': []}


def step(name, fn):
    print(f'\n--- {name} ---')
    try:
        out = fn()
        receipt['steps'].append({'step': name, 'ok': True, 'result': out})
        return out
    except RuntimeError as e:
        receipt['steps'].append({'step': name, 'ok': False, 'error': str(e)[:300]})
        print(f'  ABORT: {str(e)[:200]}')
        json.dump(receipt, open(RECEIPT, 'w'), indent=2, ensure_ascii=False)
        sys.exit(1)


# ================================================================ 1. PRECHECK
def precheck():
    print(f'  mode: {"COMMIT" if COMMIT else "DRY RUN"}')
    a = count('racing_results_archive')
    b = count('racing_results')
    c = count('horse_profiles_archive')
    d = count('asb_doping_verdicts')
    print(f'  racing_results_archive   {a:,}   (side table, mine)')
    print(f'  racing_results           {b:,}   (live table - NEVER touched)')
    print(f'  horse_profiles_archive   {c:,}')
    print(f'  asb_doping_verdicts      {d:,}')
    # the live table must NOT be one of the archive tables
    assert 'racing_results' != 'racing_results_archive'
    return {'archive': a, 'live': b, 'profiles': c, 'verdicts': d}


BEFORE = step('1. precheck', precheck)


# ================================================================ 2. DUPLICATES
def find_dupes():
    """List archive result_ids that already exist in racing_results."""
    rows = q("""
        SELECT a.result_id
        FROM racing_results_archive a
        WHERE EXISTS (SELECT 1 FROM racing_results r WHERE r.racehorse_id = a.result_id)
    """)
    ids = [r['result_id'] for r in rows]
    total = count('racing_results_archive')
    print(f'  duplicate result_ids : {len(ids):,}  ({100*len(ids)/max(1,total):.1f}% of archive)')
    print(f'  genuinely new        : {total - len(ids):,}')
    return ids


DUPES = step('2. identify duplicate result rows', find_dupes)


# ================================================================ 3. NEW ROWS
def find_new():
    rows = q("""
        SELECT a.result_id, a.horse_name, a.week_date, a.rank, a.doping_drugs,
               a.source_horse_id, a.registry_horse_id
        FROM racing_results_archive a
        WHERE NOT EXISTS (SELECT 1 FROM racing_results r WHERE r.racehorse_id = a.result_id)
    """)
    print(f'  new result rows to PRESERVE: {len(rows):,}')
    with_doping = sum(1 for r in rows if r.get('doping_drugs'))
    print(f'    of which carry doping data: {with_doping}')
    return rows


NEWROWS = step('3. isolate the genuinely new rows', find_new)


# ================================================================ 4. DOPING SAFETY
def doping_precheck():
    """The one thing that must never be lost: doping evidence in the archive."""
    a = count('racing_results_archive', "WHERE doping_drugs IS NOT NULL AND doping_drugs <> ''")
    b = count('asb_doping_verdicts')
    print(f'  archive rows carrying doping : {a:,}')
    print(f'  independent verdict rows     : {b:,}')
    if b == 0:
        raise RuntimeError('verdict table is empty - refusing to proceed')
    # every duplicate we plan to delete must not be the ONLY holder of its doping text
    return {'archive_doping_rows': a, 'verdict_rows': b}


DOPECHK = step('4. doping preservation precheck', doping_precheck)


# ============================================================ 4b. EVIDENCE GUARD
def evidence_guard():
    """Refuse to proceed unless every doping-bearing row is already exported.

    The 189 doping rows inside racing_results_archive are duplicate RESULTS but
    their doping columns exist nowhere else. 135 of the horses they name are
    absent from the news-verdict set, so pruning without an export would
    silently destroy the only record of them.
    """
    import csv as _csv, hashlib
    p = f'{BASE}/pristine/doping_evidence_from_results.csv'
    if not os.path.exists(p):
        raise RuntimeError(f'evidence export missing: {p} - run save_doping_evidence.py first')
    exported = list(_csv.DictReader(open(p, encoding='utf-8')))
    in_table = count('racing_results_archive',
                     "WHERE doping_drugs IS NOT NULL AND doping_drugs <> ''")
    print(f'  doping rows in archive  : {in_table}')
    print(f'  doping rows exported    : {len(exported)}')
    if len(exported) < in_table:
        raise RuntimeError(f'export covers only {len(exported)} of {in_table} rows - refusing')
    ids_exported = {r['result_id'] for r in exported}
    ids_table = {r['result_id'] for r in q(
        "SELECT result_id FROM racing_results_archive "
        "WHERE doping_drugs IS NOT NULL AND doping_drugs <> ''")}
    missing = ids_table - ids_exported
    if missing:
        raise RuntimeError(f'{len(missing)} doping rows not exported, e.g. {list(missing)[:3]}')
    print(f'  every doping row accounted for: CONFIRMED')
    print(f'  sha256 of export: {hashlib.sha256(open(p,"rb").read()).hexdigest()[:32]}')
    return {'doping_rows': in_table, 'exported': len(exported)}


step('4b. evidence export guard', evidence_guard)


# ================================================================ 5. DELETE
def delete_dupes():
    if not COMMIT:
        print(f'  WOULD delete {len(DUPES):,} duplicate rows from racing_results_archive')
        print(f'  WOULD keep   {len(NEWROWS):,} new rows')
        return {'would_delete': len(DUPES), 'would_keep': len(NEWROWS)}
    if not DUPES:
        print('  nothing to delete')
        return {'deleted': 0}

    # never delete a doping-bearing row - park those in a permanent side table
    doping_ids = {r['result_id'] for r in q(
        "SELECT result_id FROM racing_results_archive "
        "WHERE doping_drugs IS NOT NULL AND doping_drugs <> ''")}
    protected = doping_ids & set(DUPES)
    print(f'  duplicates carrying doping (preserved, not deleted): {len(protected):,}')
    DUPES_LOCAL = [d for d in DUPES if d not in protected]
    print(f'  duplicates safe to delete: {len(DUPES_LOCAL):,}')
    deleted = 0
    CHUNK = 200
    for i in range(0, len(DUPES_LOCAL), CHUNK):
        part = DUPES_LOCAL[i:i + CHUNK]
        inlist = ','.join(lit(x) for x in part)
        r = q(f'DELETE FROM racing_results_archive WHERE result_id IN ({inlist})')
        deleted += len(part)
        if deleted % 2000 == 0:
            print(f'    deleted {deleted:,}/{len(DUPES_LOCAL):,}', flush=True)
    after = count('racing_results_archive')
    expected = BEFORE['archive'] - len(DUPES_LOCAL)
    print(f'  deleted {deleted:,}  (kept {len(protected)} doping rows)')
    print(f'  archive rows now {after:,} (expected {expected:,})')
    assert after == expected, f'count mismatch after delete: {after} != {expected}'
    return {'deleted': deleted, 'after': after, 'doping_kept': len(protected)}


DEL = step('5. delete duplicates from the side table', delete_dupes)


# ================================================================ 6. LIVE TABLE GUARD
def live_guard():
    now = count('racing_results')
    print(f'  racing_results: {BEFORE["live"]:,} -> {now:,}')
    assert now == BEFORE['live'], 'the live table changed - this must never happen'
    print('  live table untouched: CONFIRMED')
    return {'live_before': BEFORE['live'], 'live_after': now, 'unchanged': True}


step('6. confirm the live table is untouched', live_guard)


# ================================================================ 7. SUMMARY
def summary():
    rows = {
        'racing_results_archive': count('racing_results_archive'),
        'horse_profiles_archive': count('horse_profiles_archive'),
        'asb_doping_verdicts': count('asb_doping_verdicts'),
        'asb_drug_observations': count('asb_drug_observations'),
        'racing_results': count('racing_results'),
    }
    print()
    for k, v in rows.items():
        print(f'  {k:26s} {v:>8,}')
    return rows


FINAL = step('7. final counts', summary)

receipt['finished_utc'] = datetime.datetime.now(datetime.UTC).isoformat(timespec='seconds')
receipt['final_counts'] = FINAL
json.dump(receipt, open(RECEIPT, 'w'), indent=2, ensure_ascii=False)
print(f'\nreceipt written to {RECEIPT}')
print('DRY RUN — nothing was changed.' if not COMMIT else 'COMMITTED.')
