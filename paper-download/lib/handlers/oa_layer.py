"""Open-access layer: OpenAlex/Unpaywall/S2 candidates."""
import re
import socket
import time
import httpx
from lib.core.protocol import PublisherAdapter, FetchResult, EC_OTHER
_UA = 'Mozilla/5.0 (compatible; academic-fetcher/1.0)'
import os as _os_env
_EMAIL = _os_env.environ.get('PAPERDL_EMAIL', '')
_RANK = {'publishedVersion': 0, 'acceptedVersion': 1, 'submittedVersion': 2}
MAX_BYTES = 60 * 1024 * 1024
BUDGET_S = 6.0
_T = httpx.Timeout(8, connect=2.5)
PROXY = _os_env.environ.get('PAPERDL_PROXY', '')
_PROXY_FIRST = ('semanticscholar.org',)
_NET_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RemoteProtocolError)

def _proxy_up():
    if not PROXY:
        return False
    try:
        import urllib.parse as _up
        u = _up.urlsplit(PROXY)
        socket.create_connection((u.hostname, u.port or 80), timeout=1).close()
        return True
    except (OSError, ValueError):
        return False

def _routes(url=''):
    r = [None] + ([PROXY] if _proxy_up() else [])
    return r[::-1] if any((h in url for h in _PROXY_FIRST)) else r

def _get(url, params=None):
    for proxy in _routes(url):
        try:
            with httpx.Client(proxy=proxy, timeout=_T, headers={'User-Agent': 'paper-download/1.0 (mailto:%s)' % _EMAIL}) as c:
                return c.get(url, params=params)
        except _NET_ERRORS:
            continue
        except Exception:
            return None
    return None

def _get_json(url, params=None):
    r = _get(url, params)
    return r.json() if r is not None and r.status_code == 200 else None

def _src_openalex(doi):
    out, title = ([], '')
    j = _get_json('https://api.openalex.org/works/doi:' + doi, {'select': 'title,locations'})
    if j:
        title = j.get('title') or ''
        for loc in j.get('locations', []):
            if loc.get('is_oa') and loc.get('pdf_url'):
                out.append((loc['pdf_url'], loc.get('version') or '', 'openalex'))
    return (out, title)

def _src_unpaywall(doi):
    out, title = ([], '')
    j = _get_json('https://api.unpaywall.org/v2/' + doi, {'email': _EMAIL})
    if j:
        title = j.get('title') or ''
        for loc in j.get('oa_locations', []):
            if loc.get('url_for_pdf'):
                out.append((loc['url_for_pdf'], loc.get('version') or '', 'unpaywall'))
    return (out, title)

def _src_s2(doi):
    out = []
    j = _get_json('https://api.semanticscholar.org/graph/v1/paper/DOI:' + doi, {'fields': 'externalIds,openAccessPdf'})
    if j:
        aid = (j.get('externalIds') or {}).get('ArXiv')
        if aid:
            out.append(('https://arxiv.org/pdf/%s' % aid, 'submittedVersion', 's2_arxiv'))
        u = (j.get('openAccessPdf') or {}).get('url')
        if u:
            out.append((u, '', 's2_oa'))
    return (out, '')

def candidates(doi):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(3) as ex:
        futs = [ex.submit(f, doi) for f in (_src_openalex, _src_unpaywall, _src_s2)]
        results = []
        for f in futs:
            try:
                results.append(f.result(timeout=12)[0])
            except Exception:
                results.append([])
    out, seen = ([], set())
    for lst in results:
        for c in lst:
            if c[0] not in seen:
                seen.add(c[0])
                out.append(c)
    out.sort(key=lambda c: _RANK.get(c[1], 3))
    return out

def _download_impl(url, deadline=None):
    err = 'no_route'
    _t_start = time.time()
    routes = _routes(url)
    for n, proxy in enumerate(routes):
        if deadline and time.time() > deadline:
            return (None, 'budget_exceeded')
        try:
            _left = max(1.5, (deadline - time.time()) / (len(routes) - n)) if deadline else 30.0
            with httpx.Client(proxy=proxy, timeout=httpx.Timeout(_left, connect=3), follow_redirects=True, headers={'User-Agent': _UA}) as c:
                with c.stream('GET', url) as r:
                    if r.status_code != 200:
                        return (None, 'http_%d' % r.status_code)
                    buf = b''
                    for chunk in r.iter_bytes():
                        buf += chunk
                        if len(buf) > MAX_BYTES:
                            return (None, 'too_big')
                        if deadline and time.time() > deadline:
                            return (None, 'budget_exceeded')
                        if time.time() - _t_start > 4 and len(buf) < 150000:
                            return (None, 'too_slow')
            if buf[:5] != b'%PDF-':
                return (None, 'not_pdf')
            return (buf, 'via_proxy' if proxy else '')
        except _NET_ERRORS as e:
            err = type(e).__name__
            continue
        except Exception as e:
            return (None, type(e).__name__)
    return (None, err)

def _download(url, deadline=None):
    import threading
    if not deadline:
        return _download_impl(url, None)
    box = {}
    th = threading.Thread(target=lambda: box.setdefault('r', _download_impl(url, deadline)), daemon=True)
    th.start()
    th.join(max(0.5, deadline - time.time()))
    return box.get('r') or (None, 'budget_exceeded')

class OALayerAdapter(PublisherAdapter):
    publisher_name = 'OA层'
    doi_prefixes = []
    channel_name = 'oa_layer'
    max_concurrency_per_node = 2
    estimated_seconds = 6.0
    output_format = 'pdf'
    execution_location = 'local'
    title_only = True

    def _fetch_local(self, doi, **kwargs):
        t0 = time.time()
        m = re.match('^(.*)#c=(\\d+)$', doi)
        base, idx = (m.group(1), int(m.group(2))) if m else (doi, 0)
        host = socket.gethostname()
        try:
            cands = candidates(base)
        except Exception as e:
            return FetchResult(ok=False, channel='oa_layer', format=None, pdf_bytes=None, fulltext=None, elapsed_ms=int((time.time() - t0) * 1000), error_class=EC_OTHER, error='oa_lookup_' + type(e).__name__, steps=[], node=host)
        for k in range(idx, len(cands)):
            url, ver, src = cands[k]
            if time.time() - t0 > BUDGET_S:
                break
            raw, err = _download(url, deadline=t0 + BUDGET_S)
            if raw:
                host_name = re.sub('^https?://([^/]+).*$', '\\1', url) + (' (proxy)' if err == 'via_proxy' else '')
                return FetchResult(ok=True, channel='oa:%d:%s:%s:%s' % (k, ver or 'unknown', src, host_name), format='pdf', pdf_bytes=raw, fulltext=None, elapsed_ms=int((time.time() - t0) * 1000), error_class='', error='', steps=['oa:' + src], node=host)
        return FetchResult(ok=False, channel='oa_layer', format=None, pdf_bytes=None, fulltext=None, elapsed_ms=int((time.time() - t0) * 1000), error_class=EC_OTHER, error='oa_no_candidate (candidates=%d)' % len(cands), steps=[], node=host)

    def sample_dois(self):
        return ['10.1145/2939672.2939785', '10.1038/nature14539']
