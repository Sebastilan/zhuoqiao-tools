"""arXiv module: PDF by arXiv id."""
import re
import time
import httpx
from lib.core.protocol import PublisherAdapter
import os as _os_env
_PX = _os_env.environ.get('PAPERDL_PROXY', '')
_UA = 'Mozilla/5.0 (compatible; academic-fetcher/1.0)'
_ARXIV_ID_RE = re.compile('10\\.48550/arXiv\\.(.+)', re.IGNORECASE)

def _ok(pdf_bytes=None, channel='arxiv_pdf', steps=None):
    result = {'ok': True, 'pdf_bytes': pdf_bytes, 'fulltext': None, 'format': 'pdf', 'channel': channel, 'error': ''}
    if steps is not None:
        result['trace'] = {'steps': steps}
    return result

def _fail(channel='arxiv_pdf', error='', steps=None):
    result = {'ok': False, 'pdf_bytes': None, 'fulltext': None, 'format': None, 'channel': channel, 'error': error}
    if steps is not None:
        result['trace'] = {'steps': steps}
    return result

def fetch_arxiv_pdf(doi: str, gs_link: str=None) -> dict:
    if not doi:
        return _fail(error='no doi')
    steps = []
    m = _ARXIV_ID_RE.match(doi.strip())
    if not m:
        return _fail(error=f'cannot_parse_arxiv_id: {doi}')
    arxiv_id = m.group(1)
    pdf_url = f'https://arxiv.org/pdf/{arxiv_id}.pdf'
    steps.append('http:arxiv.org')
    resp, err = (None, '')
    for proxy in (None,) + ((_PX,) if _PX else ()):
        try:
            with httpx.Client(proxy=proxy, headers={'User-Agent': _UA}, follow_redirects=True, timeout=httpx.Timeout(60, connect=5)) as c:
                resp = c.get(pdf_url)
            steps.append('via_proxy' if proxy else 'direct')
            break
        except Exception as e:
            err = str(e)
    if resp is None:
        return _fail(error=f'http_error: {err}', steps=steps)
    if resp.status_code != 200:
        return _fail(error=f'http_{resp.status_code}', steps=steps)
    pdf_bytes = resp.content
    if pdf_bytes[:4] != b'%PDF':
        return _fail(error=f'not_pdf: magic={pdf_bytes[:8]!r}', steps=steps)
    if len(pdf_bytes) < 100000:
        return _fail(error=f'pdf_too_small: {len(pdf_bytes)} bytes', steps=steps)
    return _ok(pdf_bytes=pdf_bytes, steps=steps)

class ArXivAdapter(PublisherAdapter):
    publisher_name = 'arXiv'
    doi_prefixes = ['10.48550/']
    channel_name = 'arxiv_pdf'
    max_concurrency_per_node = 5
    estimated_seconds = 7.0
    protocol_version = '1.2'
    output_format = 'pdf'
    execution_location = 'local'
    title_only = False

    def _fetch_local(self, doi, **kwargs):
        import socket
        res = self._legacy_fetch(doi, **kwargs)
        res.node = socket.gethostname()
        return res

    def _legacy_fetch(self, doi, **kwargs):
        from lib.core.protocol import FetchResult, EC_HTTP_403, EC_TIMEOUT, EC_OTHER
        t0 = time.time()
        raw = fetch_arxiv_pdf(doi)
        elapsed_ms = int((time.time() - t0) * 1000)
        if raw.get('ok'):
            return FetchResult(ok=True, channel=raw.get('channel', self.channel_name), format=raw.get('format', 'pdf'), pdf_bytes=raw.get('pdf_bytes'), fulltext=raw.get('fulltext'), elapsed_ms=elapsed_ms, error_class='', error='', steps=(raw.get('trace') or {}).get('steps', []))
        error_msg = raw.get('error', '')
        return FetchResult(ok=False, channel=raw.get('channel', self.channel_name), format=None, pdf_bytes=None, fulltext=None, elapsed_ms=elapsed_ms, error_class=_classify_error(error_msg), error=error_msg, steps=(raw.get('trace') or {}).get('steps', []))

    def sample_dois(self):
        return ['10.48550/arXiv.1706.03762', '10.48550/arXiv.2307.09288', '10.48550/arXiv.1512.03385']

def _classify_error(error_msg):
    from lib.core.protocol import EC_HTTP_403, EC_TIMEOUT, EC_OTHER
    msg = error_msg.lower()
    if '403' in msg or 'forbidden' in msg:
        return EC_HTTP_403
    if 'timeout' in msg or 'timed out' in msg:
        return EC_TIMEOUT
    return EC_OTHER
