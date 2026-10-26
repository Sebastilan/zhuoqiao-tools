"""Verify a PDF is the requested paper."""
import re
import subprocess

def check_pdf(raw):
    info = {'kind': 'pdf', 'bytes': len(raw), 'head': raw[:4].decode('latin1')}
    info['eof'] = raw.rstrip().endswith(b'%%EOF') or b'%%EOF' in raw[-1024:]
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        f.write(raw)
        p = f.name
    try:
        out = subprocess.run(['pdfinfo', p], capture_output=True, text=True).stdout
        m = re.search('Pages:\\s+(\\d+)', out)
        info['pages'] = int(m.group(1)) if m else 0
        for k in ('Producer', 'Creator'):
            m = re.search('^%s:\\s*(.*)$' % k, out, re.M)
            info[k.lower()] = m.group(1).strip() if m else ''
    finally:
        os.unlink(p)
    info['pass'] = info['head'] == '%PDF' and info['eof'] and (info['pages'] > 0) and (info['bytes'] >= 20000)
    return info

def check_xml(raw):
    paras = len(re.findall(b'<ce:para', raw))
    return {'kind': 'xml', 'bytes': len(raw), 'ce_para': paras, 'pass': paras > 0}

def check(raw, fmt):
    return check_pdf(raw) if fmt == 'pdf' else check_xml(raw)

def pages_short(pages, first_page=None, last_page=None):
    exp = 0
    try:
        a, b = (int(first_page), int(last_page))
        if b > a > 0:
            exp = b - a + 1
    except (TypeError, ValueError):
        exp = 0
    p = int(pages or 0)
    if not exp or p <= 0:
        return {'pass': True, 'expected': exp, 'pages': p}
    ok = p >= exp / 2.0
    return {'pass': ok, 'expected': exp, 'pages': p, 'why': [] if ok else ['pages_short:%d<expected:%d' % (p, exp)]}

def pages_suspect(pages):
    p = int(pages or 0)
    if p == 1:
        return {'pass': False, 'pages': p, 'why': ['pages=1']}
    return {'pass': True, 'pages': p}

def _front_text(raw, fmt, pages=2):
    if fmt == 'pdf':
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
            f.write(raw)
            p = f.name
        try:
            return subprocess.run(['pdftotext', '-l', str(pages), p, '-'], capture_output=True, text=True).stdout
        finally:
            os.unlink(p)
    return re.sub('<[^>]+>', ' ', raw.decode('utf-8', 'replace'))[:4000]
_DOI_FIND = re.compile('10\\.\\d{4,9}/[^\\s\\"\'<>(){}\\[\\]]+', re.I)
_DOI_TAIL = '.,;:)]}›»"\''

def foreign_doi(raw, fmt, doi=None):
    text = _front_text(raw, fmt)
    flat = re.sub('\\s+', '', text).lower()
    target = re.sub('\\s+', '', doi or '').lower()
    if target and target in flat:
        return []
    cands = []
    for m in _DOI_FIND.findall(text):
        d = m.lower().rstrip(_DOI_TAIL)
        if d and d not in cands:
            cands.append(d)
    if not cands:
        for m in re.finditer('10\\.\\d{4,9}/[a-z0-9._\\-/()]+', flat):
            d = m.group(0).rstrip(_DOI_TAIL).rstrip('(')
            if d and d not in cands:
                cands.append(d)
    return [d for d in cands if not (target and (target.startswith(d) or d.startswith(target)))]

def _why_list(x):
    if isinstance(x, str):
        return [x] if x else []
    return [str(i) for i in x or []]

def _ntitle(t):
    return re.sub('[^a-z0-9]+', '', _norm(t)) if t else ''

def _front_has_title(raw, fmt, title):
    t = _ntitle(title)
    if len(t) < 12:
        return False
    return t in re.sub('[^a-z0-9]+', '', _norm(_front_text(raw, fmt)))

def _same_work(doi, foreign, meta, meta_of, raw=None, fmt='pdf'):
    if not foreign:
        return False
    t1 = _ntitle((meta or {}).get('title'))
    if not t1:
        return False
    m2 = None
    if meta_of:
        try:
            m2 = meta_of(foreign[0])
        except Exception:
            m2 = None
    if m2 and _ntitle(m2.get('title')) == t1:
        return True
    if m2 is None and raw is not None and _front_has_title(raw, fmt, (meta or {}).get('title')):
        return True
    return False
OLD_CONV_PREFIX = ('10.1016/',)
OLD_CONV_REASON = '旧转换版,缺参考文献与图'

def _chrome_made(checks):
    return (checks.get('producer') or '').startswith('Skia/PDF') or 'HeadlessChrome' in (checks.get('creator') or '')

def conversion_of(raw, fmt='pdf', checks=None):
    if fmt != 'pdf':
        return None
    import xml2pdf as xml转pdf
    text = _front_text(raw, fmt, 1)
    if xml转pdf.MARK in text:
        flat = re.sub('\\s+', '', text)
        m = re.search('参考文献(\\d+)/(\\d+)\\D*?图(\\d+)/(\\d+)\\D*?表(\\d+)/(\\d+)', flat)
        n = [int(x) for x in m.groups()] if m else None
        miss = []
        for kind, tag in (('图', 'fig'), ('表', 'table')):
            g = re.search('缺%s\\s*\\d+\\s*张（([^）]*)）' % kind, text)
            if g:
                miss += ['%s:%s' % (tag, x.strip().rstrip('…')) for x in g.group(1).split('、') if x.strip().rstrip('…')]
        g = re.search('缺参考文献\\s*(\\d+)\\s*条', text)
        if g:
            miss.append('ref:缺%s条' % g.group(1))
        comp = {'refs': n[0:2], 'figs': n[2:4], 'tables': n[4:6], 'missing': miss, 'v': 2} if n else {'v': 2, 'unparsed': True}
        return {'converted_from': 'xml', 'completeness': comp}
    if _chrome_made(checks if checks is not None else check_pdf(raw)):
        return {'converted_from': 'xml?', 'completeness': {'v': 1}}
    return None

def check_cached(raw, fmt, meta=None, doi=None, meta_of=None):
    checks = check(raw, fmt)
    foreign = foreign_doi(raw, fmt, doi)
    ident = check_identity(raw, fmt, meta, doi)
    by = ident.get('by') or ''
    why, reasons = ([], [])
    if not checks.get('pass'):
        why.append('unparseable' if fmt == 'pdf' else 'no_text')
        reasons.append('残件')
    same_work = False
    if foreign:
        if _same_work(doi, foreign, meta, meta_of, raw, fmt):
            same_work = True
            if not ident.get('identity'):
                ident = dict(ident, identity=True, by=ident.get('by') or 'doi_alias')
        else:
            why.append('doi_mismatch:' + foreign[0])
            reasons.append('身份不符')
    if not ident.get('identity'):
        why += ['identity:' + x for x in _why_list(ident.get('why'))]
        reasons.append('身份不符')
    sus = pages_suspect(checks.get('pages')) if fmt == 'pdf' else {'pass': True, 'pages': None}
    if not sus.get('pass'):
        why += sus.get('why') or []
        reasons.append('残件')
    m = meta or {}
    pr = pages_short(checks.get('pages'), m.get('first_page'), m.get('last_page'))
    if not pr.get('pass'):
        why += pr.get('why') or []
        reasons.append('残件')
    conv = conversion_of(raw, fmt, checks) if checks.get('pass') else None
    conv_out = {}
    if conv and conv['completeness'].get('v') == 2:
        conv_out = conv
    elif conv and str(doi or '').lower().startswith(OLD_CONV_PREFIX):
        why.append('old_conversion_v1')
        reasons.append(OLD_CONV_REASON)
        conv_out = {'converted_from': 'xml', 'completeness': {'v': 1}}
    identity = by or ('unverified' if not meta else 'no')
    return {**conv_out, 'pass': not why, 'why': why, 'pages': checks.get('pages'), 'bytes': checks.get('bytes'), 'identity': identity, 'identity_why': _why_list(ident.get('why')) if not by else [], 'identity_by': by, 'meta_by': (meta or {}).get('by'), 'foreign_doi': foreign[:3], 'same_work_as': foreign[0] if same_work else None, 'reason': ';'.join(dict.fromkeys(reasons)) if reasons else '', 'title_ratio': ident.get('title_ratio'), 'pages_short': pr}

def check_cached_file(path, fmt=None, meta=None, doi=None, meta_of=None):
    try:
        with open(path, 'rb') as f:
            raw = f.read()
    except OSError:
        return {'pass': False, 'why': ['unreadable'], 'pages': 0, 'bytes': 0, 'identity': 'no'}
    fmt = fmt or ('pdf' if str(path).lower().endswith('.pdf') else 'xml')
    return check_cached(raw, fmt, meta, doi, meta_of)
import unicodedata as _ud

def _norm(s):
    s = _ud.normalize('NFKD', s or '').encode('ascii', 'ignore').decode().lower()
    return re.sub('[^a-z0-9]+', ' ', s)

def _text_of(raw, fmt):
    if fmt == 'pdf':
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
            f.write(raw)
            p = f.name
        try:
            out = subprocess.run(['pdftotext', '-l', '1', p, '-'], capture_output=True, text=True).stdout
        finally:
            os.unlink(p)
        return _ud.normalize('NFKC', out)
    return re.sub('<[^>]+>', ' ', raw.decode('utf-8', 'replace'))
_CJK = re.compile('[\\u4e00-\\u9fff]')

def _doi_in_front(raw, fmt, doi):
    if not doi:
        return False
    import tempfile, os
    if fmt == 'pdf':
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
            f.write(raw)
            p = f.name
        try:
            t = subprocess.run(['pdftotext', '-l', '2', p, '-'], capture_output=True, text=True).stdout
        finally:
            os.unlink(p)
    else:
        t = raw.decode('utf-8', 'replace')
    flat = re.sub('\\s+', '', t).lower()
    d = re.sub('\\s+', '', doi).lower()
    if d in flat:
        return True
    m = re.match('^10\\.48550/arxiv\\.(.+)$', d)
    return bool(m and 'arxiv:' + m.group(1) in flat)

def check_identity(raw, fmt, meta, doi=None):
    if _doi_in_front(raw, fmt, doi):
        return {'identity': True, 'by': 'doi', 'why': []}
    if not meta:
        return {'identity': False, 'why': ['no_metadata']}
    raw_text = _text_of(raw, fmt)
    text = _norm(raw_text)
    title = meta.get('title', '')
    tokens = [t for t in _norm(title).split() if len(t) >= 3]
    cjk_title = set(_CJK.findall(title))
    if len(cjk_title) >= 4:
        t_ratio = sum((1 for c in cjk_title if c in raw_text)) / len(cjk_title)
    elif tokens:
        hit = sum((1 for t in tokens if ' ' + t + ' ' in ' ' + text + ' '))
        t_ratio = hit / len(tokens)
    else:
        cjk = set(_CJK.findall(title))
        t_ratio = sum((1 for c in cjk if c in raw_text)) / len(cjk) if cjk else 0.0
    text_nodig = re.sub('(?<=[a-z])\\d+', ' ', text)
    nospace_raw = re.sub('\\s+', '', raw_text)
    author_hit = []
    for a in meta.get('authors', []):
        if _CJK.search(a):
            key = re.sub('\\s+', '', a)
            rev = ''.join(reversed(a.split())) if len(a.split()) > 1 else key
            if key and (key in nospace_raw or rev in nospace_raw):
                author_hit.append(a)
        else:
            parts = _norm(a).split()
            if not parts:
                continue
            sn = parts[-1]
            if ' ' + sn + ' ' in ' ' + text_nodig + ' ' or (len(sn) >= 4 and re.search('(?<![a-z])' + re.escape(sn) + '[tf](?![a-z])', text_nodig)):
                author_hit.append(sn)
    if not meta.get('authors'):
        ok = t_ratio >= 0.8 and len(tokens) >= 3
        return {'identity': ok, 'title_ratio': round(t_ratio, 2), 'author_hits': [], 'by': 'title_only', 'why': [] if ok else ['title_low_no_authors']}
    ok = t_ratio >= 0.6 and len(author_hit) >= 1
    why = (['title_low'] if t_ratio < 0.6 else []) + (['no_author'] if not author_hit else [])
    return {'identity': ok, 'title_ratio': round(t_ratio, 2), 'author_hits': author_hit[:3], 'why': why, 'by': 'title_author' if ok else ''}
