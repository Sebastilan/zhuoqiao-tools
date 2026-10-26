"""MDPI module: open PDF download."""
import re
import time
import httpx
from lib.core.protocol import PublisherAdapter
_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
_DOI_RE = re.compile('^([a-z]+)(\\d{1,2})(\\d{2})(\\d{4,5})$')
_CODE_TO_SLUG = {'a': 'algorithms', 'act': 'actuators', 'atmos': 'atmosphere', 'info': 'information', 'catal': 'catalysts', 'nano': 'nanomaterials', 'mi': 'micromachines', 'fi': 'futureinternet', 'bs': 'behavsci', 'ijgi': 'ijgi', 'jsan': 'jsan', 'bdcc': 'BDCC', 'sym': 'symmetry', 'pr': 'processes', 'su': 'sustainability', 's': 'sensors', 'app': 'applsci', 'ma': 'materials', 'ijerph': 'ijerph', 'w': 'water', 'en': 'energies', 'rs': 'remotesensing', 'ijms': 'ijms', 'nu': 'nutrients', 'ag': 'agronomy', 'f': 'foods', 'v': 'viruses', 'e': 'entropy', 'ph': 'pharmaceutics', 'pm': 'pharmaceuticals', 'jcm': 'jcm', 'jof': 'jof', 'jmse': 'jmse', 'math': 'mathematics', 'md': 'marinedrugs', 'polym': 'polymers', 'antiox': 'antioxidants', 'b': 'biosensors', 'fp': 'fermentation', 'dj': 'diagnostics', 'land': 'land', 'cells': 'cells', 'animals': 'animals', 'biology': 'biology', 'biomolecules': 'biomolecules', 'cancers': 'cancers', 'diagnostics': 'diagnostics', 'electronics': 'electronics', 'molecules': 'molecules', 'healthcare': 'healthcare', 'antibiotics': 'antibiotics', 'pathogens': 'pathogens', 'viruses': 'viruses'}

def _ok(pdf_bytes=None, fmt='pdf', channel='mdpi_html', steps=None):
    result = {'ok': True, 'pdf_bytes': pdf_bytes, 'fulltext': None, 'format': fmt, 'channel': channel, 'error': ''}
    if steps is not None:
        result['trace'] = {'steps': steps}
    return result

def _fail(channel='mdpi_html', error='', steps=None):
    result = {'ok': False, 'pdf_bytes': None, 'fulltext': None, 'format': None, 'channel': channel, 'error': error}
    if steps is not None:
        result['trace'] = {'steps': steps}
    return result

def _parse_doi_suffix(doi: str):
    suffix = doi.strip().lower()
    if suffix.startswith('10.3390/'):
        suffix = suffix[len('10.3390/'):]
    m = _DOI_RE.match(suffix)
    if not m:
        return (None, None, None, None)
    return m.groups()

def _slug_from_crossref(doi: str):
    try:
        with httpx.Client(trust_env=False) as c:
            r = c.get('https://api.crossref.org/works/' + doi, headers={'User-Agent': _UA}, timeout=8)
        if r.status_code != 200:
            return None
        titles = (r.json().get('message') or {}).get('container-title') or []
        if not titles:
            return None
        return re.sub('[^a-z0-9]', '', titles[0].lower()) or None
    except Exception:
        return None

def _get_slug_candidates(code: str) -> list:
    candidates = []
    if code in _CODE_TO_SLUG:
        candidates.append(_CODE_TO_SLUG[code])
    if code not in candidates:
        candidates.append(code)
    return candidates

def _try_download(slug: str, vol: str, article: str):
    art5 = article.zfill(5)
    vol2 = vol.zfill(2)
    base = f'{slug}-{vol2}-{art5}'
    url = f'https://res.mdpi.com/d_attachment/{slug}/{base}/article_deploy/{base}.pdf'
    try:
        with httpx.Client(trust_env=False) as client:
            resp = client.get(url, headers={'User-Agent': _UA}, follow_redirects=True, timeout=90)
        if resp.status_code == 200 and resp.content[:4] == b'%PDF':
            if len(resp.content) > 50000:
                return resp.content
    except Exception:
        pass
    return None

def fetch_mdpi_html(doi: str, gs_link: str=None) -> dict:
    if not doi:
        return _fail(error='no doi')
    steps = []
    code, vol, issue, article = _parse_doi_suffix(doi)
    if not code:
        return _fail(error=f'cannot_parse_doi_suffix: {doi}')
    steps.append('http:res.mdpi.com')
    tried = _get_slug_candidates(code)
    for slug in tried:
        pdf_bytes = _try_download(slug, vol, article)
        if pdf_bytes:
            return _ok(pdf_bytes=pdf_bytes, fmt='pdf', channel='mdpi_html', steps=steps)
    extra = _slug_from_crossref(doi)
    if extra and extra not in tried:
        steps.append('http:api.crossref.org')
        tried.append(extra)
        pdf_bytes = _try_download(extra, vol, article)
        if pdf_bytes:
            return _ok(pdf_bytes=pdf_bytes, fmt='pdf', channel='mdpi_html', steps=steps)
    return _fail(error='res_mdpi_not_found: code=%s vol=%s article=%s slugs_tried=%s' % (code, vol, article, ','.join(tried)), steps=steps)

class MDPIAdapter(PublisherAdapter):
    publisher_name = 'MDPI'
    doi_prefixes = ['10.3390/']
    channel_name = 'mdpi_html'
    max_concurrency_per_node = 10
    estimated_seconds = 8.0
    protocol_version = '1.2'
    output_format = 'pdf'
    execution_location = 'local'
    title_only = False

    def _fetch_local(self, doi):
        from lib.core.protocol import FetchResult, EC_HTTP_403, EC_TIMEOUT, EC_OTHER
        t0 = time.time()
        raw = fetch_mdpi_html(doi)
        elapsed_ms = int((time.time() - t0) * 1000)
        if raw.get('ok'):
            return FetchResult(ok=True, channel=raw.get('channel', self.channel_name), format=raw.get('format', 'pdf'), pdf_bytes=raw.get('pdf_bytes'), fulltext=raw.get('fulltext'), elapsed_ms=elapsed_ms, error_class='', error='', steps=(raw.get('trace') or {}).get('steps', []))
        error_msg = raw.get('error', '')
        return FetchResult(ok=False, channel=raw.get('channel', self.channel_name), format=None, pdf_bytes=None, fulltext=None, elapsed_ms=elapsed_ms, error_class=_classify_error(error_msg), error=error_msg, steps=(raw.get('trace') or {}).get('steps', []))

    def sample_dois(self):
        return ['10.3390/s22030001', '10.3390/en16030001', '10.3390/ma15010001']

def _classify_error(error_msg):
    from lib.core.protocol import EC_HTTP_403, EC_TIMEOUT, EC_OTHER
    msg = error_msg.lower()
    if '403' in msg or 'forbidden' in msg:
        return EC_HTTP_403
    if 'timeout' in msg or 'timed out' in msg:
        return EC_TIMEOUT
    return EC_OTHER
