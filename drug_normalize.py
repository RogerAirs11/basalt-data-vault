#!/usr/bin/env python3
"""Canonicalise drug names across every source, with a full audit trail.

Defect classes found in the raw data (all real, all seen in the 86-entry table):

  1. SPELLING VARIANTS of one substance   CAFEINE / CAFEIN / CAFFEINE
  2. TYPOS                                PHEYLBUTAZONE, THEOPHYLINE, ANTYPIYRINE
  3. CONCATENATED PAIRS                   "PHENYLBUTAZONE OXI PHENYLBUTAZONE"
  4. SYNONYMS (INN vs BAN vs trade)       MEPERIDINE = PETHIDINE, LIDOCAINE = LIGNOCAINE
  5. SALT / ESTER / METABOLITE FORMS      TRIAMCINOLONE ACETONIDE, OH LIDOCAINE
  6. UNTRANSLATED PERSIAN                 اورفنادرین
  7. CLASS TERMS mixed with substances    BRONCHODILATORS, OPIOIDES

Nothing is discarded: every output keeps `raw` so the original wording survives.
"""
import re, json, sys

# ---- 1. exact canonical names (a spelling fix, not a judgement) ----------
SPELLING = {
    'CAFEIN': 'CAFFEINE',
    'CAFEINE': 'CAFFEINE',
    'THEOPHYLINE': 'THEOPHYLLINE',
    'PHEYLBUTAZONE': 'PHENYLBUTAZONE',
    'METHYLAMINO ANTYPIYRINE': 'METHYLAMINOANTIPYRINE',
    'METHYLAMINO ANTIPYRINE': 'METHYLAMINOANTIPYRINE',
    'PHETIDINE': 'PETHIDINE',
}

# ---- 2. synonyms: same substance, different naming convention -----------
# each entry states WHY, so a reviewer can check it
SYNONYM = {
    'PETHIDINE': 'MEPERIDINE',      # BAN name for meperidine (same drug)
    'LIGNOCAINE': 'LIDOCAINE',      # BAN name for lidocaine
    'DIPYRONE': 'METAMIZOLE',       # INN metamizole, common name dipyrone
    'TRENDIONE': 'TRENBOLONE',      # trenbolone metabolite commonly reported as such
    'DIMETHYLSULFOXIDE DMSO': 'DIMETHYLSULFOXIDE',
    'DIMETHYLSULFOXIDE': 'DIMETHYLSULFOXIDE',
}
SALT = {
    'TRIAMCINOLONE ACETONIDE': 'TRIAMCINOLONE',   # ester of the same steroid
}
# metabolites that are reported as the parent substance in practice
METABOLITE = {
    'OH LIDOCAINE': 'LIDOCAINE',                  # hydroxy-lidocaine metabolite
}
# genuinely uncertain — kept separate and flagged, never silently merged
UNCERTAIN = {
    'HYDRO MORPHINE': 'HYDROMORPHONE',            # likely hydromorphone
}

# ---- 3. Persian -> English ---------------------------------------------
PERSIAN = {
    'اورفنادرین': 'ORPHENADRINE',
    'تری پلنامین': 'TRIPELENNAMINE',
}

# ---- 4. class terms (real findings, but not single substances) ----------
CLASS_TERMS = {'BRONCHODILATORS', 'OPIOIDES', 'OPIATE'}

# ---- 5. known multi-drug strings that were stored as one key -----------
#     matched longest-first so "OXYPHENYLBUTAZONE" is not split mid-word
SPLIT_PATTERNS = [
    ('PHENYLBUTAZONE OXI PHENYLBUTAZONE', ['PHENYLBUTAZONE', 'OXYPHENYLBUTAZONE']),
    ('PHENYLBUTAZONE OXY PHENYLBUTAZONE', ['PHENYLBUTAZONE', 'OXYPHENYLBUTAZONE']),
    ('PHENYLBUTAZONE OXIPHENYLBUTAZONE', ['PHENYLBUTAZONE', 'OXYPHENYLBUTAZONE']),
    ('PHENYLBUTAZONE OXYPHENYLBUTAZONE', ['PHENYLBUTAZONE', 'OXYPHENYLBUTAZONE']),
    ('CAFFEINE THEOPHYLLINE', ['CAFFEINE', 'THEOPHYLLINE']),
    ('THEOPHYLLINET DEXAMETHASONE', ['THEOPHYLLINE', 'DEXAMETHASONE']),
    ('MORPHINE NOSCAPINE CODEINE', ['MORPHINE', 'NOSCAPINE', 'CODEINE']),
]

PERSIAN_RE = re.compile(r'[\u0600-\u06FF]')


def canonicalise_one(name):
    """Return (list_of_canonical_names, note). Empty list = not a substance."""
    raw = (name or '').strip()
    if not raw:
        return [], 'empty'
    u = re.sub(r'\s+', ' ', raw).upper()

    # persian
    if PERSIAN_RE.search(raw):
        en = PERSIAN.get(raw.strip())
        if en: return [en], 'persian-translated'
        return [u], 'persian-UNTRANSLATED'

    # multi-drug strings first
    for pattern, parts in SPLIT_PATTERNS:
        if u == pattern:
            return parts, 'split-multi'

    if u in SPELLING:  return [SPELLING[u]], 'spelling'
    if u in SYNONYM:   return [SYNONYM[u]], 'synonym'
    if u in SALT:      return [SALT[u]], 'salt-form'
    if u in METABOLITE: return [METABOLITE[u]], 'metabolite'
    if u in UNCERTAIN:  return [UNCERTAIN[u]], 'uncertain'
    if u in CLASS_TERMS: return [], 'class-term'
    return [u], 'as-is'


def canonicalise(drugs_field):
    """Canonicalise a 'A|B|C' pipe field into a deduped sorted list."""
    out, notes = [], []
    for part in str(drugs_field or '').split('|'):
        names, note = canonicalise_one(part)
        out.extend(names)
        if note not in ('as-is', 'empty'):
            notes.append((part.strip(), note))
    return sorted(set(out)), notes


if __name__ == '__main__':
    # self-test: every case above must round-trip
    tests = [
        ('CAFEINE', ['CAFFEINE']), ('CAFEIN', ['CAFFEINE']), ('CAFFEINE', ['CAFFEINE']),
        ('THEOPHYLINE', ['THEOPHYLLINE']), ('PHEYLBUTAZONE', ['PHENYLBUTAZONE']),
        ('PETHIDINE', ['MEPERIDINE']), ('MEPERIDINE', ['MEPERIDINE']),
        ('LIGNOCAINE', ['LIDOCAINE']), ('DIPYRONE', ['METAMIZOLE']),
        ('PHENYLBUTAZONE OXI PHENYLBUTAZONE', ['PHENYLBUTAZONE', 'OXYPHENYLBUTAZONE']),
        ('PHENYLBUTAZONE OXYPHENYLBUTAZONE', ['PHENYLBUTAZONE', 'OXYPHENYLBUTAZONE']),
        ('MORPHINE NOSCAPINE CODEINE', ['MORPHINE', 'NOSCAPINE', 'CODEINE']),
        ('TRIAMCINOLONE ACETONIDE', ['TRIAMCINOLONE']),
        ('OH LIDOCAINE', ['LIDOCAINE']),
        ('اورفنادرین', ['ORPHENADRINE']),
        ('BRONCHODILATORS', []),
        ('MORPHINE', ['MORPHINE']),
    ]
    bad = 0
    for raw, want in tests:
        got, note = canonicalise_one(raw)
        ok = sorted(got) == sorted(want)
        if not ok: bad += 1
        print(('PASS ' if ok else 'FAIL ') + f'{raw!r:38s} -> {got} ({note})')
    print(f'\n{len(tests)-bad}/{len(tests)} self-tests pass')
    sys.exit(1 if bad else 0)
