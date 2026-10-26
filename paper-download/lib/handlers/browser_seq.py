"""HTTP and desktop-browser publisher modules."""
import fcntl
import os
import re
import socket
import subprocess
import sys
import time
from lib.core.protocol import PublisherAdapter, FetchResult, EC_OTHER

def _desk_act():
    p = os.environ.get('DESK_ACT', '')
    if not p or not os.path.isfile(p):
        raise RuntimeError('DESK_ACT not set: path to desk_act.py of the desktop-control tool (see AGENTS.md, browser publishers)')
    return p
DL_DIR = os.environ.get('PAPERDL_BROWSER_DOWNLOADS') or os.path.expanduser('~/Downloads')
LOCK = '/tmp/paperdl-browser.lock'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

def _act(*steps):
    args = []
    for i, st in enumerate(steps):
        if i:
            args.append('--')
        args += list(st)
    env = dict(os.environ, DESK_TYPE_PAUSE='0.004')
    p = subprocess.run([sys.executable, _desk_act(), *args], capture_output=True, text=True, timeout=60, env=env)
    return (p.returncode == 0, (p.stdout + p.stderr)[-200:])

def _act_bg(*steps):
    args = []
    for i, st in enumerate(steps):
        if i:
            args.append('--')
        args += list(st)
    subprocess.Popen([sys.executable, _desk_act(), *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=dict(os.environ, DESK_TYPE_PAUSE='0.004'))

def _fail_shot():
    try:
        p = subprocess.run([sys.executable, os.path.join(os.path.dirname(_desk_act()), 'desk_shot.py')], capture_output=True, text=True, timeout=30)
        return (p.stdout.strip().splitlines() or ['?'])[-1][-120:]
    except Exception:
        return '?'

def _listing():
    try:
        return set(os.listdir(DL_DIR))
    except OSError:
        return set()

def _cleanup_new(before, keep=None):
    import shutil
    for f in _listing() - before:
        p = os.path.join(DL_DIR, f)
        if keep and os.path.abspath(p) == os.path.abspath(keep):
            continue
        try:
            shutil.rmtree(p) if os.path.isdir(p) else os.unlink(p)
        except OSError:
            pass

def _wait_new_file(before, wait_s):
    start = time.time()
    end = start + wait_s
    hard = start + wait_s + 25
    last, part_sz = ({}, {})
    while time.time() < end:
        new = _listing() - before
        done = [f for f in new if not f.endswith('.crdownload') and os.path.isfile(os.path.join(DL_DIR, f))]
        for f in done:
            p = os.path.join(DL_DIR, f)
            try:
                sz = os.path.getsize(p)
            except OSError:
                continue
            if sz > 0 and last.get(f) == sz:
                return (p, '')
            last[f] = sz
        for f in new:
            if f.endswith('.crdownload'):
                try:
                    sz = os.path.getsize(os.path.join(DL_DIR, f))
                except OSError:
                    continue
                if sz > part_sz.get(f, -1):
                    part_sz[f] = sz
                    end = min(hard, max(end, time.time() + 4))
        time.sleep(0.5)
    if any((f.endswith('.crdownload') for f in _listing() - before)):
        return (None, 'chrome_download_stuck(.crdownload)')
    return (None, 'no_file_within_%ds' % wait_s)

class BrowserSeqAdapter(PublisherAdapter):
    publisher_name = ''
    doi_prefixes = []
    channel_name = ''
    max_concurrency_per_node = 1
    estimated_seconds = 10.0
    output_format = 'pdf'
    execution_location = 'local'
    title_only = False
    uses_screen = True
    min_interval_s = 8.0
    wait_s = 20
    fail_hint = ''
    landing_wait = '6'
    retry_landing = False
    viewer_wait = '4'
    mode = 'download'

    def landing_for(self, doi):
        return None

    def url_for(self, doi):
        raise NotImplementedError

    def extra_steps(self, doi):
        return []

    def _result(self, t0, ok, error='', pdf=None, steps=None):
        return FetchResult(ok=ok, channel=self.channel_name, format='pdf' if ok else None, pdf_bytes=pdf, fulltext=None, elapsed_ms=int((time.time() - t0) * 1000), error_class='' if ok else EC_OTHER, error=error, steps=steps or [], node=socket.gethostname())

    def _fetch_local(self, doi, **kwargs):
        t0 = time.time()
        self._mode = self.mode
        url = self.url_for(doi)
        if isinstance(url, tuple):
            return self._result(t0, False, url[1], steps=['resolve:' + url[1].split(':')[0]])
        if not url:
            return self._result(t0, False, 'not_on_platform', steps=['resolve:off_platform'])
        with open(LOCK, 'w') as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            stamp = '/tmp/paperdl-last-%s' % self.channel_name
            try:
                gap = self.min_interval_s - (time.time() - os.path.getmtime(stamp))
                if gap > 0:
                    time.sleep(gap)
            except OSError:
                pass
            open(stamp, 'w').close()
            t0 = time.time()
            before = _listing()
            seq = [('key', 'Escape'), ('sleep', '0.1'), ('key', 'Escape'), ('sleep', '0.1'), ('key', 'ctrl+t'), ('sleep', '0.3'), ('key', 'ctrl+l')]
            land = getattr(self, '_force_landing', None) or self.landing_for(doi)
            if land:
                seq += [('type', land), ('key', 'Return'), ('sleep', self.landing_wait), ('key', 'ctrl+l')]
            seq += [('type', url), ('key', 'Return')]
            seq += self.extra_steps(doi)
            if self._mode == 'viewer':
                seq += [('sleep', self.viewer_wait), ('key', 'ctrl+s'), ('sleep', '1.0'), ('key', 'Return')]
            ok, out = _act(*seq)
            if not ok:
                return self._result(t0, False, 'desk_act_failed: ' + out.strip()[-120:], steps=['desk:seq'])
            path, why = _wait_new_file(before, self.wait_s)
            shot = _fail_shot() if not path else ''
            _act_bg(('key', 'Escape'), ('sleep', '0.15'), ('key', 'Escape'), ('sleep', '0.15'), ('key', 'ctrl+w'))
            if not path:
                _cleanup_new(before)
                return self._result(t0, False, why + self.fail_hint + ' shot=' + shot, steps=['desk:seq'])
            try:
                with open(path, 'rb') as f:
                    raw = f.read()
            except OSError as e:
                _cleanup_new(before)
                return self._result(t0, False, 'read_failed:' + type(e).__name__, steps=['desk:seq'])
            _cleanup_new(before)
        if raw[:5] != b'%PDF-' and self.retry_landing and (not kwargs.get('_landed')):
            self._force_landing = 'https://doi.org/' + doi
            try:
                return self._fetch_local(doi, _landed=True)
            finally:
                self._force_landing = None
        if raw[:5] != b'%PDF-':
            return self._result(t0, False, 'saved_page_not_pdf(verification_or_error_page) head=%r' % raw[:12], steps=['desk:seq'])
        return self._result(t0, True, pdf=raw, steps=['desk:seq', 'file:' + os.path.basename(path)[:60]])

class SpringerSeqAdapter(BrowserSeqAdapter):
    publisher_name = 'Springer'
    doi_prefixes = ['10.1007/', '10.1023/', '10.1007/978-']
    channel_name = 'springer_seq'
    uses_screen = False
    mode = 'viewer'
    min_interval_s = 8.0

    def url_for(self, doi):
        return 'https://link.springer.com/content/pdf/%s.pdf' % doi

    def referer_for(self, doi):
        return 'https://link.springer.com/article/%s' % doi

    def _fetch_local(self, doi, **kwargs):
        import httpx
        t0 = time.time()
        url = self.url_for(doi)
        hdrs = {'User-Agent': UA, 'Referer': self.referer_for(doi)}
        try:
            with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(45, connect=6), headers=hdrs) as c:
                r = c.get(url)
            if r.status_code == 200 and r.content[:5] == b'%PDF-':
                return self._result(t0, True, pdf=r.content, steps=['http:link.springer.com'])
            return self._result(t0, False, 'no_access_or_not_pdf(http_%d): 校园IP无该文机构权限或文章无PDF' % r.status_code, steps=['http:link.springer.com'])
        except Exception as e:
            why = type(e).__name__
        res = super()._fetch_local(doi, **kwargs)
        res.steps = ['http_failed:' + why] + list(res.steps or [])
        return res

    def sample_dois(self):
        return ['10.1007/s11263-015-0816-y', '10.1023/A:1010933404324']

class WileySeqAdapter(BrowserSeqAdapter):
    publisher_name = 'Wiley'
    doi_prefixes = ['10.1002/', '10.1049/', '10.1111/', '10.1155/']
    channel_name = 'wiley_seq'
    mode = 'download'
    min_interval_s = 10.0
    wait_s = 12
    parallel_with_oa = True
    fail_hint = '(wiley_abs_redirect:likely_no_subscription)'

    def url_for(self, doi):
        import httpx
        origin = 'https://onlinelibrary.wiley.com'
        try:
            with httpx.Client(follow_redirects=False, timeout=httpx.Timeout(8, connect=4), headers={'User-Agent': UA}) as c:
                h = c.head('https://doi.org/' + doi)
            loc, sc = (h.headers.get('location') or '', h.status_code)
            if sc == 404:
                return ('error', 'doi_not_found:' + doi)
            m = re.match('^(https://[^/]*wiley\\.com)/', loc)
            if m:
                origin = m.group(1)
            elif 'hindawi.com/' in loc:
                pass
            elif loc and 'wiley.com' not in loc:
                return None
        except Exception:
            pass
        return '%s/doi/pdfdirect/%s?download=true' % (origin, doi)

    def sample_dois(self):
        return ['10.1111/j.1540-6261.1964.tb02865.x']

class NatureSeqAdapter(SpringerSeqAdapter):
    publisher_name = 'Nature'
    doi_prefixes = ['10.1038/']
    channel_name = 'nature_http'
    uses_screen = False
    mode = 'viewer'
    min_interval_s = 5.0

    def url_for(self, doi):
        return 'https://www.nature.com/articles/%s.pdf' % doi.split('/', 1)[1]

    def referer_for(self, doi):
        return 'https://www.nature.com/articles/%s' % doi.split('/', 1)[1]

    def sample_dois(self):
        return ['10.1038/nature14539']

class ApsHttpAdapter(BrowserSeqAdapter):
    publisher_name = 'APS'
    doi_prefixes = ['10.1103/']
    channel_name = 'aps_http'
    uses_screen = False
    min_interval_s = 4.0

    def url_for(self, doi):
        return 'https://doi.org/' + doi

    def _fetch_local(self, doi, **kwargs):
        import httpx
        t0 = time.time()
        hdrs = {'User-Agent': UA, 'Accept': 'application/pdf,text/html'}
        try:
            with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(40, connect=6), headers=hdrs) as c:
                land = c.get('https://doi.org/' + doi)
                m = re.match('^https://journals\\.aps\\.org/(\\w+)/abstract/(.+)$', str(land.url).split('?')[0])
                if land.status_code == 404:
                    return self._result(t0, False, 'doi_not_found:' + doi, steps=['resolve:doi_not_found'])
                if not m:
                    return self._result(t0, False, 'not_on_platform(landing=%s)' % str(land.url)[:80], steps=['resolve:off_platform'])
                r = c.get('https://journals.aps.org/%s/pdf/%s' % (m.group(1), m.group(2)), headers={'Referer': str(land.url)})
            if r.status_code == 200 and r.content[:5] == b'%PDF-':
                return self._result(t0, True, pdf=r.content, steps=['http:journals.aps.org'])
            return self._result(t0, False, 'no_access_or_not_pdf(http_%d): 校园IP无该文权限或文章无PDF' % r.status_code, steps=['http:journals.aps.org'])
        except Exception as e:
            return self._result(t0, False, 'http_error:' + type(e).__name__, steps=['http:journals.aps.org'])

    def sample_dois(self):
        return ['10.1103/physrevb.109.165433']

class PlosHttpAdapter(BrowserSeqAdapter):
    publisher_name = 'PLOS'
    doi_prefixes = ['10.1371/']
    channel_name = 'plos_http'
    uses_screen = False
    min_interval_s = 2.0
    JOURNALS = {'pone': 'plosone', 'pcbi': 'ploscompbiol', 'pbio': 'plosbiology', 'pmed': 'plosmedicine', 'ppat': 'plospathogens', 'pgen': 'plosgenetics', 'pntd': 'plosntds', 'pgph': 'globalpublichealth', 'pclm': 'climate', 'pdig': 'digitalhealth', 'pwat': 'water', 'pstr': 'sustainabilitytransformation'}

    def url_for(self, doi):
        m = re.match('^10\\.1371/journal\\.(p[a-z]+)\\.', doi.lower())
        j = self.JOURNALS.get(m.group(1)) if m else None
        if not j:
            return ('error', 'unknown_plos_journal:' + doi)
        return 'https://journals.plos.org/%s/article/file?id=%s&type=printable' % (j, doi)

    def _fetch_local(self, doi, **kwargs):
        import httpx
        t0 = time.time()
        url = self.url_for(doi)
        if isinstance(url, tuple):
            return self._result(t0, False, url[1], steps=['resolve:' + url[1].split(':')[0]])
        try:
            with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(40, connect=6), headers={'User-Agent': UA}) as c:
                r = c.get(url)
            if r.status_code == 200 and r.content[:5] == b'%PDF-':
                return self._result(t0, True, pdf=r.content, steps=['http:journals.plos.org'])
            if r.status_code == 404:
                return self._result(t0, False, 'doi_not_found:' + doi, steps=['http:journals.plos.org'])
            return self._result(t0, False, 'not_pdf(http_%d)' % r.status_code, steps=['http:journals.plos.org'])
        except Exception as e:
            return self._result(t0, False, 'http_error:' + type(e).__name__, steps=['http:journals.plos.org'])

    def sample_dois(self):
        return ['10.1371/journal.pone.0185146']

class CambridgeHttpAdapter(BrowserSeqAdapter):
    publisher_name = 'Cambridge'
    doi_prefixes = ['10.1017/']
    channel_name = 'cambridge_http'
    uses_screen = False
    min_interval_s = 3.0

    def url_for(self, doi):
        return 'https://doi.org/' + doi

    def _fetch_local(self, doi, **kwargs):
        import httpx
        import html as _h
        t0 = time.time()
        try:
            with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(40, connect=6), headers={'User-Agent': UA}) as c:
                land = c.get('https://doi.org/' + doi)
                if land.status_code == 404:
                    return self._result(t0, False, 'doi_not_found:' + doi, steps=['resolve:doi_not_found'])
                if 'cambridge.org' not in str(land.url):
                    return self._result(t0, False, 'not_on_platform(landing=%s)' % str(land.url)[:80], steps=['resolve:off_platform'])
                m = re.search('name="citation_pdf_url"\\s+content="([^"]+)"', land.text) or re.search('content="([^"]+)"\\s+name="citation_pdf_url"', land.text)
                if not m:
                    return self._result(t0, False, 'no_pdf_link(http_%d): 无 citation_pdf_url（无PDF或被验证页挡）' % land.status_code, steps=['http:cambridge.org'])
                r = c.get(_h.unescape(m.group(1)), headers={'Referer': str(land.url)})
            if r.status_code == 200 and r.content[:5] == b'%PDF-':
                return self._result(t0, True, pdf=r.content, steps=['http:cambridge.org'])
            return self._result(t0, False, 'no_access_or_not_pdf(http_%d)' % r.status_code, steps=['http:cambridge.org'])
        except Exception as e:
            return self._result(t0, False, 'http_error:' + type(e).__name__, steps=['http:cambridge.org'])

    def sample_dois(self):
        return ['10.1017/dce.2026.10047']

class FrontiersHttpAdapter(BrowserSeqAdapter):
    publisher_name = 'Frontiers'
    doi_prefixes = ['10.3389/']
    channel_name = 'frontiers_http'
    uses_screen = False
    min_interval_s = 2.0

    def url_for(self, doi):
        return 'https://www.frontiersin.org/articles/%s/pdf' % doi

    def _fetch_local(self, doi, **kwargs):
        import httpx
        t0 = time.time()
        try:
            with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60, connect=6), headers={'User-Agent': UA}) as c:
                r = c.get(self.url_for(doi))
            if r.status_code == 200 and r.content[:5] == b'%PDF-':
                return self._result(t0, True, pdf=r.content, steps=['http:frontiersin.org'])
            if r.status_code == 404:
                return self._result(t0, False, 'doi_not_found:' + doi, steps=['http:frontiersin.org'])
            return self._result(t0, False, 'not_pdf(http_%d)' % r.status_code, steps=['http:frontiersin.org'])
        except Exception as e:
            return self._result(t0, False, 'http_error:' + type(e).__name__, steps=['http:frontiersin.org'])

    def sample_dois(self):
        return ['10.3389/fphy.2024.1304570']

class IopSeqAdapter(BrowserSeqAdapter):
    publisher_name = 'IOP'
    doi_prefixes = ['10.1088/']
    channel_name = 'iop_seq'
    mode = 'viewer'
    min_interval_s = 10.0
    wait_s = 15
    parallel_with_oa = True
    fail_hint = '(iop: 若 Chrome 停在 Radware 验证页，需用户重新勾选)'

    def url_for(self, doi):
        return 'https://iopscience.iop.org/article/%s/pdf' % doi

    def sample_dois(self):
        return ['10.1088/2053-1591/aca5f0']

class AcsSeqAdapter(BrowserSeqAdapter):
    publisher_name = 'ACS'
    doi_prefixes = ['10.1021/']
    channel_name = 'acs_seq'
    retry_landing = True
    landing_wait = '5'
    mode = 'viewer'
    min_interval_s = 10.0
    parallel_with_oa = True

    def url_for(self, doi):
        return 'https://pubs.acs.org/doi/pdf/%s' % doi

    def sample_dois(self):
        return ['10.1021/acssynbio.4c00356']

class AcmSeqAdapter(BrowserSeqAdapter):
    publisher_name = 'ACM'
    doi_prefixes = ['10.1145/']
    channel_name = 'acm_seq'
    retry_landing = True
    landing_wait = '5'
    mode = 'viewer'
    min_interval_s = 10.0

    def url_for(self, doi):
        return 'https://dl.acm.org/doi/pdf/%s' % doi

    def sample_dois(self):
        return ['10.1145/3292500.3330701']

class DeGruyterSeqAdapter(BrowserSeqAdapter):
    publisher_name = 'De Gruyter'
    doi_prefixes = ['10.1515/']
    channel_name = 'degruyter_seq'
    retry_landing = True
    landing_wait = '5'
    mode = 'viewer'
    min_interval_s = 10.0
    wait_s = 12
    parallel_with_oa = True
    fail_hint = '(degruyter_unauthorizedDownload:likely_no_subscription)'

    def url_for(self, doi):
        return 'https://www.degruyterbrill.com/document/doi/%s/pdf' % doi

    def sample_dois(self):
        return ['10.1515/icl-2021-0046']

class CnkiSeqAdapter(BrowserSeqAdapter):
    publisher_name = 'CNKI'
    doi_prefixes = []
    doi_substrings = ['/j.cnki.']
    channel_name = 'cnki_seq'
    mode = 'download'
    landing_wait = '3'
    min_interval_s = 6.0
    wait_s = 12
    parallel_with_oa = True
    fail_hint = '(cnki:slider_verify_or_no_result_or_no_subscription)'

    def landing_for(self, doi):
        import urllib.parse
        return 'https://kns.cnki.net/kns8s/defaultresult/index?korder=DOI&kw=' + urllib.parse.quote(doi, safe='')

    def url_for(self, doi):
        return "javascript:location.href=document.querySelector('td.name a.fz14').href"

    def extra_steps(self, doi):
        return [('sleep', '3.5'), ('key', 'ctrl+l'), ('type', "javascript:document.querySelector('#pdfDown').click()"), ('key', 'Return')]

    def sample_dois(self):
        return ['10.19580/j.cnki.1007-3000.2025090020']

class WanfangSeqAdapter(BrowserSeqAdapter):
    publisher_name = 'Wanfang'
    doi_prefixes = ['10.3969/']
    doi_substrings = ['/j.issn.']
    channel_name = 'wanfang_seq'
    mode = 'download'
    landing_wait = '4'
    min_interval_s = 6.0
    wait_s = 12
    parallel_with_oa = True
    fail_hint = '(wanfang:no_result_or_no_fulltext)'

    def landing_for(self, doi):
        import urllib.parse
        return 'https://s.wanfangdata.com.cn/paper?q=' + urllib.parse.quote('DOI:"%s"' % doi, safe='')

    def url_for(self, doi):
        return "javascript:(function(){var w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT),n;while(n=w.nextNode()){if(n.data.trim()=='\\u4e0b\\u8f7d'){n.parentElement.parentElement.click();return}}})()"

    def sample_dois(self):
        return ['10.3969/j.issn.1672-397x.2019.01.002']

class GenericLandingHttpAdapter(BrowserSeqAdapter):
    publisher_name = 'Generic'
    doi_prefixes = []
    catch_all = True
    channel_name = 'generic_landing_http'
    uses_screen = False
    min_interval_s = 2.0
    estimated_seconds = 8.0

    def url_for(self, doi):
        return 'https://doi.org/' + doi

    def _fetch_local(self, doi, **kwargs):
        import httpx
        import html as _h
        t0 = time.time()
        try:
            with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(25, connect=6), headers={'User-Agent': UA}) as c:
                land = c.get('https://doi.org/' + doi)
                host = str(land.url).split('/')[2] if '//' in str(land.url) else '?'
                if land.status_code == 404:
                    return self._result(t0, False, 'doi_not_found:' + doi, steps=['resolve:doi_not_found'])
                if land.status_code in (401, 403, 429):
                    return self._result(t0, False, 'landing_blocked(http_%d,host=%s)' % (land.status_code, host), steps=['http:' + host])
                m = re.search('name="citation_pdf_url"\\s+content="([^"]+)"', land.text) or re.search('content="([^"]+)"\\s+name="citation_pdf_url"', land.text)
                if not m:
                    return self._result(t0, False, 'no_module(generic:no_citation_pdf_url,host=%s)' % host, steps=['http:' + host])
                r = c.get(_h.unescape(m.group(1)), headers={'Referer': str(land.url)})
            if r.status_code == 200 and r.content[:5] == b'%PDF-':
                return self._result(t0, True, pdf=r.content, steps=['http:' + host])
            return self._result(t0, False, 'no_access_or_not_pdf(http_%d,host=%s)' % (r.status_code, host), steps=['http:' + host])
        except Exception as e:
            return self._result(t0, False, 'http_error:' + type(e).__name__, steps=['http:generic'])

    def sample_dois(self):
        return ['10.22061/jecei.2020.6898.346']
