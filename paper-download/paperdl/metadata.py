"""Paper metadata from Crossref/OpenAlex/arXiv."""
import html
import json
import re
import urllib.parse
import urllib.request
import os as _os_env
UA = {'User-Agent': 'paper-download/1.0' + (' (mailto:%s)' % _os_env.environ['PAPERDL_EMAIL'] if _os_env.environ.get('PAPERDL_EMAIL') else '')}
TIMEOUT = 8

def _get_json(url, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8', 'replace'))

def _clean(x):
    return ' '.join(html.unescape(re.sub('<[^>]+>', ' ', x or '')).split())

def _pages(*cands):
    for c in cands:
        c = str(c or '').strip()
        m = re.match('^([A-Za-z]?\\d+)\\s*[-–]\\s*([A-Za-z]?\\d+)$', c)
        if m:
            return (m.group(1), m.group(2))
        if re.fullmatch('[A-Za-z]?\\d+', c):
            return (c, c)
    return (None, None)

def crossref(doi, timeout=TIMEOUT):
    try:
        j = _get_json('https://api.crossref.org/works/' + urllib.parse.quote(doi.strip(), safe=''), timeout)
    except Exception:
        return None
    m = (j or {}).get('message') or {}
    title = _clean((m.get('title') or [''])[0])
    if not title:
        return None
    authors = []
    for a in m.get('author') or []:
        n = _clean(' '.join((x for x in ((a.get('given') or '').strip(), (a.get('family') or '').strip()) if x)))
        n = n or _clean(a.get('name') or '')
        if n:
            authors.append(n)
    fp, lp = _pages(m.get('page'), m.get('article-number'))
    yr = (((m.get('issued') or {}).get('date-parts') or [[None]])[0] or [None])[0]
    return {'title': title, 'authors': authors, 'by': 'crossref', 'journal': _clean((m.get('container-title') or [''])[0]), 'year': yr, 'first_page': fp, 'last_page': lp}

def openalex(doi, timeout=20):
    try:
        j = _get_json('https://api.openalex.org/works/https://doi.org/' + doi.strip(), timeout)
    except Exception:
        return None
    title = _clean(j.get('title') or j.get('display_name') or '')
    if not title:
        return None
    bib = j.get('biblio') or {}
    src = (j.get('primary_location') or {}).get('source') or {}
    return {'title': title, 'by': 'openalex', 'authors': [_clean((x.get('author') or {}).get('display_name', '')) for x in j.get('authorships', []) if _clean((x.get('author') or {}).get('display_name', ''))], 'journal': _clean(src.get('display_name') or ''), 'year': j.get('publication_year'), 'first_page': bib.get('first_page'), 'last_page': bib.get('last_page')}

def arxiv(aid, timeout=12):
    try:
        url = 'https://export.arxiv.org/api/query?id_list=' + urllib.parse.quote(aid, safe='')
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            txt = r.read().decode('utf-8', 'replace')
    except Exception:
        return None
    e = re.search('<entry>(.*?)</entry>', txt, re.S)
    if not e:
        return None
    t = re.search('<title>(.*?)</title>', e.group(1), re.S)
    if not t:
        return None
    title = _clean(t.group(1))
    authors = [_clean(x) for x in re.findall('<author>\\s*<name>(.*?)</name>', e.group(1)) if _clean(x)]
    return {'title': title, 'authors': authors, 'by': 'arxiv', 'journal': '', 'year': None, 'first_page': None, 'last_page': None} if title else None

def get_meta_node(doi):
    doi = (doi or '').strip()
    m = re.match('^10\\.48550/arxiv\\.(.+)$', doi, re.I)
    if m:
        return arxiv(m.group(1))
    return crossref(doi) or openalex(doi)
