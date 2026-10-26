"""IEEE module: stampPDF download."""
import base64
import time
_SCRIPT_TEMPLATE = "import httpx, re, base64, sys\ndoi = '{doi}'\nhdrs = {{'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36', 'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8'}}\ndef _arn(u):\n    m = re.search(r'/document/(\\d+)', u or '') or re.search(r'arnumber=(\\d+)', u or '')\n    return m.group(1) if m else None\narnumber = None\nwhy = ''\nfor _i in range(2):\n    try:\n        with httpx.Client(follow_redirects=False, timeout=httpx.Timeout(8, connect=4), headers=hdrs) as c:\n            r0 = c.head('https://doi.org/' + doi)\n        if r0.status_code == 404:\n            sys.exit('doi_not_found:' + doi)\n        arnumber = _arn(r0.headers.get('location'))\n        if arnumber:\n            break\n        why = 'no_location status=' + str(r0.status_code)\n    except SystemExit:\n        raise\n    except Exception as e:\n        why = 'doi_error:' + type(e).__name__\nif not arnumber:\n    try:\n        j = httpx.get('https://api.crossref.org/works/' + doi, timeout=8).json()\n        arnumber = _arn(dict((j.get('message') or dict()).get('resource') or dict()).get('primary', dict()).get('URL'))\n    except Exception as e:\n        why += ' crossref_error:' + type(e).__name__\nif not arnumber:\n    sys.exit('no_arnumber:' + why)\nurl = 'https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber=' + arnumber + '&ref='\nref = 'https://ieeexplore.ieee.org/stamp/stamp.jsp?tp=&arnumber=' + arnumber\npdf_hdrs = {{'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36', 'Referer': ref, 'Accept': 'application/pdf,*/*'}}\npdf = None\nlast = ''\nfor _i in range(2):\n    try:\n        with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60, connect=8), headers=pdf_hdrs) as c2:\n            r2 = c2.get(url)\n            pdf = r2.content\n        break\n    except Exception as e:\n        last = str(e)\nif pdf is None:\n    sys.exit('pdf_error:' + last)\nif len(pdf) < 50000:\n    sys.exit('pdf_too_small:size=' + str(len(pdf)) + ' status=' + str(r2.status_code))\nif not pdf[:5].startswith(b'%PDF'):\n    sys.exit('not_pdf:' + repr(pdf[:20]))\nprint(base64.b64encode(pdf).decode())\n"

class IEEEDirectAdapter(object):
    publisher_name = 'IEEE'
    doi_prefixes = ['10.1109/']
    channel_name = 'ieee_direct'
    max_concurrency_per_node = 10
    estimated_seconds = 17.0
    protocol_version = '1.2'
    output_format = 'pdf'
    execution_location = 'local'
    title_only = False

    def _fetch_local(self, doi, **kwargs):
        import base64
        import socket
        import subprocess
        import sys
        import time
        from lib.core.protocol import FetchResult, EC_OTHER
        t0 = time.time()
        script = _SCRIPT_TEMPLATE.format(doi=doi.replace("'", "\\'"))
        p = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, timeout=150)
        elapsed_ms = int((time.time() - t0) * 1000)
        out = p.stdout.strip().splitlines()
        if p.returncode == 0 and out:
            return FetchResult(ok=True, channel=self.channel_name, format='pdf', pdf_bytes=base64.b64decode(out[-1]), fulltext=None, elapsed_ms=elapsed_ms, error_class='', error='', steps=['doi:http_redirect', 'http:stampPDF'], node=socket.gethostname())
        return FetchResult(ok=False, channel=self.channel_name, format=None, pdf_bytes=None, fulltext=None, elapsed_ms=elapsed_ms, error_class=EC_OTHER, error=((p.stderr or '') + (p.stdout or ''))[-300:] or 'no_output', steps=['doi:http_redirect'], node=socket.gethostname())

    def sample_dois(self):
        return ['10.1109/TITS.2025.3557442', '10.1109/CEC60901.2024.10612120', '10.1109/TEVC.2023.3281666']
