"""Resolve DOI, URL or title to a DOI."""
import json
import re
import unicodedata
import urllib.parse
import urllib.request
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'
DOI_IN_TEXT = re.compile('10\\.\\d{4,9}/[^\\s\\"\'<>?#]+')
STOP = set('the and for with from that this using based via into over under between their its are was were has have into nature science journal transactions proceedings conference international ieee acm springer elsevier wiley et al paper pdf doi'.split())

def _get(url, timeout=15, headers=None):
    req = urllib.request.Request(url, headers={'User-Agent': UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return (r.read().decode('utf-8', 'replace'), r.geturl())

def _json(url, timeout=15):
    try:
        return json.loads(_get(url, timeout)[0])
    except Exception:
        return None

def _norm(s):
    s = unicodedata.normalize('NFKD', s or '')
    return re.sub('[^a-z0-9一-鿿]+', ' ', s.encode('ascii', 'ignore').decode().lower() + ' ' + ''.join((ch for ch in s if '一' <= ch <= '鿿')))

def _words(s):
    return {w for w in _norm(s).split() if len(w) >= 3 and w not in STOP and (not w.isdigit())}
_DOI_TAIL = re.compile('/(?:mediaobjects|pdf|epdf|full|fulltext|abstract|figures|references|suppinfo|suppl|html)\\b.*$', re.I)

def _clean_doi(d):
    d = _DOI_TAIL.sub('', d)
    return d.rstrip('.,;)]}>').lower()

def from_url(url):
    u = urllib.parse.urlparse(url)
    host, path = (u.netloc.lower(), urllib.parse.unquote(u.path))
    m = DOI_IN_TEXT.search(path)
    if 'doi.org' in host and m:
        return (_clean_doi(m.group(0)), 'doi.org')
    m2 = re.search('arxiv\\.org/(?:abs|pdf|html)/([^\\s?#]+?)(?:v\\d+)?(?:\\.pdf)?$', url.split('?')[0].split('#')[0].rstrip('/'))
    if m2:
        return ('10.48550/arXiv.' + m2.group(1), 'arxiv_url')
    m3 = re.match('^/articles/([^/]+)$', path)
    if 'nature.com' in host and m3:
        return ('10.1038/' + m3.group(1).lower(), 'nature_url')
    if m and host not in ('scholar.google.com',):
        return (_clean_doi(m.group(0)), 'doi_in_path')
    if 'ieeexplore.ieee.org' in host:
        n = re.search('/document/(\\d+)', path)
        if n:
            doi = _ieee_doi(n.group(1))
            return (doi, 'ieee_document_id') if doi else (None, 'ieee_doi_not_found')
    try:
        html, _ = _get(url, 15)
    except Exception as e:
        return (None, 'page_unreachable:' + type(e).__name__)
    for pat in ('name="citation_doi"\\s+content="([^"]+)"', 'content="([^"]+)"\\s+name="citation_doi"', 'name="(?:dc|DC)\\.[Ii]dentifier"\\s+content="(10\\.[^"]+)"', 'name="prism\\.doi"\\s+content="([^"]+)"'):
        mm = re.search(pat, html)
        if mm and DOI_IN_TEXT.search(mm.group(1)):
            return (_clean_doi(DOI_IN_TEXT.search(mm.group(1)).group(0)), 'page_meta')
    t = re.search('name="citation_title"\\s+content="([^"]+)"', html) or re.search('content="([^"]+)"\\s+name="citation_title"', html)
    if t:
        import html as _h
        authors = re.findall('name="citation_author"\\s+content="([^"]+)"', html)
        return (None, 'title:' + _h.unescape(t.group(1)) + (' ' + ' '.join(authors[:3]) if authors else ''))
    return (None, 'no_doi_in_page')

def _ieee_doi(num):
    d = _json('https://api.openalex.org/works?filter=locations.landing_page_url:https://ieeexplore.ieee.org/document/%s&select=doi&per-page=1' % num)
    try:
        v = d['results'][0]['doi']
        if v:
            return _clean_doi(v.replace('https://doi.org/', ''))
    except Exception:
        pass
    return _ieee_doi_via_pdf(num)
_IEEE_PDF_SCRIPT = "\nimport httpx, re, subprocess, sys, tempfile, os\nn = sys.argv[1]\nh = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',\n     'Referer': 'https://ieeexplore.ieee.org/stamp/stamp.jsp?tp=&arnumber=' + n, 'Accept': 'application/pdf,*/*'}\nr = httpx.get('https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber=' + n + '&ref=', headers=h, follow_redirects=True, timeout=httpx.Timeout(40, connect=8))\nif r.content[:5] != b'%PDF-':\n    sys.exit(2)\nf = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False); f.write(r.content); f.close()\nt = subprocess.run(['pdftotext', '-l', '2', f.name, '-'], capture_output=True, text=True).stdout\nos.unlink(f.name)\nm = re.search(r'(10\\.1109/[A-Za-z0-9.\\-_()/]+)', t)\nprint(m.group(1) if m else '')\n"

def _ieee_doi_via_pdf(num):
    import subprocess, sys
    try:
        p = subprocess.run([sys.executable, '-', num], input=_IEEE_PDF_SCRIPT, capture_output=True, text=True, timeout=70)
        d = (p.stdout or '').strip().splitlines()
        return _clean_doi(d[-1]) if d and d[-1].startswith('10.1109/') else None
    except Exception:
        return None

def _cands_crossref(q):
    d = _json('https://api.crossref.org/works?rows=6&select=DOI,title,author,issued,container-title,type&query.bibliographic=' + urllib.parse.quote(q))
    out = []
    for i in (d or {}).get('message', {}).get('items') or []:
        out.append({'doi': _clean_doi(i['DOI']), 'title': (i.get('title') or [''])[0], 'year': ((i.get('issued') or {}).get('date-parts') or [[None]])[0][0], 'type': i.get('type'), 'venue': (i.get('container-title') or [''])[0], 'authors': [a.get('family', '') for a in i.get('author') or []][:12], 'src': 'crossref'})
    return out

def _cands_openalex(q):
    d = _json('https://api.openalex.org/works?per-page=6&select=doi,title,publication_year,authorships,primary_location,type&search=' + urllib.parse.quote(q))
    out = []
    for w in (d or {}).get('results') or []:
        doi = (w.get('doi') or '').replace('https://doi.org/', '')
        if not doi:
            continue
        src = ((w.get('primary_location') or {}).get('source') or {}).get('display_name') or ''
        out.append({'doi': _clean_doi(doi), 'title': w.get('title') or '', 'year': w.get('publication_year'), 'venue': src, 'type': w.get('type'), 'authors': [((a.get('author') or {}).get('display_name') or '').split(' ')[-1] for a in w.get('authorships') or []][:12], 'src': 'openalex'})
    return out

def _cands_arxiv(q):
    words = [w for w in _norm(q).split() if len(w) >= 3][:10]
    if len(words) < 3:
        return []
    try:
        xml, _ = _get('https://export.arxiv.org/api/query?max_results=4&search_query=' + urllib.parse.quote(' AND '.join(('all:' + w for w in words[:6]))), 8)
    except Exception:
        return []
    out = []
    for e in re.findall('<entry>(.*?)</entry>', xml, re.S):
        idm = re.search('<id>https?://arxiv\\.org/abs/([^<]+?)(?:v\\d+)?</id>', e)
        t = re.search('<title>(.*?)</title>', e, re.S)
        y = re.search('<published>(\\d{4})', e)
        if idm and t:
            out.append({'doi': '10.48550/arxiv.' + idm.group(1).lower(), 'title': ' '.join(t.group(1).split()), 'year': int(y.group(1)) if y else None, 'venue': 'arXiv', 'authors': [a.split()[-1] for a in re.findall('<name>(.*?)</name>', e)][:12], 'src': 'arxiv'})
    return out

def _web(q, n=6):
    import os
    key = os.environ.get('SERPER_API_KEY', '')
    if not key:
        return []
    try:
        req = urllib.request.Request('https://google.serper.dev/search', data=json.dumps({'q': q, 'num': n}).encode(), headers={'X-API-KEY': key, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read().decode('utf-8', 'replace'))
        return [(i.get('title', ''), i.get('link', '')) for i in (d.get('organic') or [])[:n]]
    except Exception:
        return []

def _title_to_doi(title):
    t = _words(title)
    if len(t) < 3:
        return None
    for c in _cands_crossref(title)[:3]:
        cw = _words(c['title'])
        if cw and len(t & cw) / max(len(t), len(cw)) >= 0.85:
            return c
    return None

def from_web(q, titles=True):
    items = _web(q)
    out, seen, pending = ([], set(), [])
    for rank, (title, link) in enumerate(items, 1):
        if not link:
            continue
        doi, by = from_url_light(link)
        if doi and doi not in seen:
            seen.add(doi)
            out.append({'doi': doi, 'title': re.sub('\\s*\\.\\.\\.$', '', title), 'year': None, 'venue': '', 'authors': [], 'src': 'web:' + by, 'type': 'journal-article', 'rank': rank})
        elif not doi and titles and (not any((h in link for h in ('scholar.google', 'baidu.com')))) and (len(pending) < 4):
            pending.append((rank, re.sub('\\s*\\.\\.\\.$', '', title).replace('(PDF) ', '')))
    if pending:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(len(pending)) as ex:
            res = list(ex.map(lambda rt: _title_to_doi(rt[1]), pending))
        for (rank, _), t in zip(pending, res):
            if t and t['doi'] not in seen:
                seen.add(t['doi'])
                out.append(dict(t, src='web:title', rank=rank))
    out.sort(key=lambda c: c['rank'])
    return out[:3]

def from_url_light(url):
    u = urllib.parse.urlparse(url)
    host, path = (u.netloc.lower(), urllib.parse.unquote(u.path))
    if 'doi.org' in host and DOI_IN_TEXT.search(path):
        return (_clean_doi(DOI_IN_TEXT.search(path).group(0)), 'doi.org')
    m2 = re.search('arxiv\\.org/(?:abs|pdf)/([^\\s?#]+?)(?:v\\d+)?(?:\\.pdf)?$', url.split('?')[0].rstrip('/'))
    if m2:
        return ('10.48550/arXiv.' + m2.group(1), 'arxiv')
    m3 = re.match('^/articles/([^/]+)$', path)
    if 'nature.com' in host and m3 and (not m3.group(1).startswith('d41586')):
        return ('10.1038/' + m3.group(1).lower(), 'nature')
    m = DOI_IN_TEXT.search(path)
    if m:
        return (_clean_doi(m.group(0)), 'doi_in_path')
    if 'ieeexplore.ieee.org' in host:
        n = re.search('/document/(\\d+)', path)
        if n:
            d = _ieee_doi(n.group(1))
            if d:
                return (d, 'ieee')
    return (None, None)

def _crossref_work(doi):
    d = _json('https://api.crossref.org/works/' + urllib.parse.quote(doi, safe='/'))
    i = (d or {}).get('message')
    if not i:
        return None
    return {'doi': _clean_doi(i['DOI']), 'title': (i.get('title') or [''])[0], 'year': ((i.get('issued') or {}).get('date-parts') or [[None]])[0][0], 'type': i.get('type'), 'venue': (i.get('container-title') or [''])[0], 'authors': [a.get('family', '') for a in i.get('author') or []][:12], 'src': 'crossref'}

def _score(q, c):
    qw = _words(q)
    tw = _words(c['title'])
    title_cov = len(qw & tw) / len(tw) if tw else 0.0
    qn = _norm(q).split()
    fam = [_norm(a).replace(' ', '') for a in c['authors'] if len(_norm(a).replace(' ', '')) >= 3]
    qjoin = ' '.join(qn)
    s_auth = 1.0 if any((f in qjoin.replace(' ', '') for f in fam[:12])) else 0.0
    vw = {w for w in _norm(c['venue']).split() if len(w) >= 4 and w not in ('journal', 'transactions', 'proceedings', 'conference', 'international')}
    s_venue = 1.0 if vw & set(qn) else 0.0
    if len(vw) >= 2 and vw <= set(qn):
        s_venue = 2.0
    ys = [int(y) for y in re.findall('\\b(19\\d\\d|20\\d\\d)\\b', q)]
    s_year = 1.0 if ys and c['year'] and (abs(int(c['year']) - ys[0]) <= 1) else 0.0
    exact_title = 1.0 if tw and title_cov >= 0.9 and (len(qw & tw) >= 4) else 0.0
    total = 2.5 * title_cov + 2.0 * s_auth + 1.0 * s_venue + 0.5 * s_year + 1.0 * exact_title
    if c.get('type') and c['type'] not in ('journal-article', 'proceedings-article', 'posted-content', 'preprint', 'article', 'report'):
        total -= 1.5
    if '/d41586-' in c['doi']:
        total -= 1.5
    if c.get('rank'):
        total += max(0.0, 2.5 - 0.5 * c['rank'])
    return (round(total, 2), {'title': round(title_cov, 2), 'auth': s_auth, 'venue': s_venue, 'year': s_year, 'exact': exact_title, 'web': 1.0 if c.get('rank') else 0.0})

def _rank(q, cands):
    for c in cands:
        c['score'], c['why'] = _score(q, c)
    cands.sort(key=lambda c: -c['score'])
    top = cands[:4]
    if not top:
        return {'ok': False, 'by': 'text', 'confidence': 'none', 'why': 'no_candidates', 'candidates': []}
    gap = top[0]['score'] - (top[1]['score'] if len(top) > 1 else 0)
    w = top[0]['why']
    solid = bool(w['exact'] or (w['auth'] and (w['venue'] or w['year'])) or (w['web'] and w['title'] >= 0.8))
    conf = 'high' if top[0]['score'] >= 3.5 and gap >= 1.0 and solid else 'medium' if top[0]['score'] >= 3.0 and gap >= 0.5 or (top[0]['score'] >= 2.0 and gap >= 1.0) else 'none'
    r = {'by': 'text', 'confidence': conf, 'candidates': [{k: c[k] for k in ('doi', 'title', 'year', 'venue', 'score', 'src') if k in c} for c in top]}
    if conf == 'none':
        r.update(ok=False, why='ambiguous_or_low_confidence')
    else:
        b = top[0]
        r.update(ok=True, doi=b['doi'], title=b['title'], year=b['year'], venue=b['venue'], authors=b['authors'])
    return r

def from_text(q):
    from concurrent.futures import ThreadPoolExecutor
    q = ' '.join(q.split())
    web = from_web(q, titles=False)
    cands, seen = ([], set())
    if web:
        with ThreadPoolExecutor(len(web)) as ex:
            metas = list(ex.map(lambda c: _crossref_work(c['doi']), web))
        for c, m in zip(web, metas):
            c2 = dict(m, src=c['src'], rank=c['rank']) if m else c
            if c2['doi'] not in seen:
                seen.add(c2['doi'])
                cands.append(c2)
        r = _rank(q, cands)
        if r['confidence'] == 'high':
            r['by'] = 'web'
            return r
    from concurrent.futures import wait
    ex = ThreadPoolExecutor(4)
    futs = [ex.submit(fn, q) for fn in (_cands_crossref, _cands_openalex, _cands_arxiv, from_web)]
    wait(futs, timeout=20)
    for f in futs:
        if not f.done():
            continue
        try:
            for c in f.result():
                if c['doi'] not in seen:
                    seen.add(c['doi'])
                    cands.append(c)
                elif c.get('rank'):
                    for e in cands:
                        if e['doi'] == c['doi']:
                            e['rank'] = c['rank']
        except Exception:
            pass
    ex.shutdown(wait=False, cancel_futures=True)
    return _rank(q, cands)

def resolve(ref):
    ref = (ref or '').strip()
    m = re.fullmatch('(?:https?://(?:dx\\.)?doi\\.org/)?(10\\.\\d{4,9}/\\S+)', ref, re.I)
    if m:
        return {'ok': True, 'doi': _clean_doi(m.group(1)), 'by': 'doi', 'confidence': 'exact'}
    if re.match('^https?://', ref):
        doi, why = from_url(ref)
        if doi:
            return {'ok': True, 'doi': doi, 'by': why, 'confidence': 'exact'}
        if why.startswith('title:'):
            r = from_text(why[6:])
            r['by'] = 'url_page_title'
            return r
        return {'ok': False, 'by': 'url', 'confidence': 'none', 'why': why, 'candidates': []}
    m2 = DOI_IN_TEXT.search(ref)
    if m2 and len(ref) > len(m2.group(0)) + 3:
        return {'ok': True, 'doi': _clean_doi(m2.group(0)), 'by': 'doi_in_text', 'confidence': 'exact'}
    return from_text(ref)
if __name__ == '__main__':
    import sys
    print(json.dumps(resolve(' '.join(sys.argv[1:])), ensure_ascii=False, indent=1))
