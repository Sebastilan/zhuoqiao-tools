"""Elsevier module: full-text API, PDF or XML."""
import re
import base64
from lib.core.protocol import PublisherAdapter
_KEYFILE_READ = "import os\nkey = os.environ.get('ELSEVIER_API_KEY', '').strip()\nif not key:\n    sys.exit('no_key: ELSEVIER_API_KEY not set')\n"
_ELSEVIER_SCRIPT_TEMPLATE = 'import httpx, base64, sys, subprocess, tempfile, os, re\ndoi = \'{doi}\'\nkey = \'{key}\'\nurl = \'https://api.elsevier.com/content/article/doi/\' + doi\nMIN_PAGES = 3\ndef pdf_pages(b):\n    try:\n        f = tempfile.NamedTemporaryFile(suffix=\'.pdf\', delete=False)\n        f.write(b); f.close()\n        try:\n            out = subprocess.run([\'pdfinfo\', f.name], capture_output=True, text=True, timeout=20).stdout\n        finally:\n            os.unlink(f.name)\n        m = re.search(r\'Pages:\\s+(\\d+)\', out)\n        if m:\n            return int(m.group(1))\n    except Exception:\n        pass\n    m = re.search(rb\'/Type\\s*/Pages[^>]*?/Count\\s+(\\d+)\', b, re.S)\n    return int(m.group(1)) if m else 0\ntry:\n    rp = httpx.get(url, headers={{\'X-ELS-APIKey\': key, \'Accept\': \'application/pdf\'}}, timeout=60)\nexcept Exception as e:\n    sys.exit(\'http_error:\' + str(e))\npages = 0\nif rp.status_code == 200 and rp.content[:5] == b\'%PDF-\':\n    pages = pdf_pages(rp.content)\n    if pages >= MIN_PAGES:\n        print(\'PDF:%d:\' % pages + base64.b64encode(rp.content).decode())\n        sys.exit(0)\ntry:\n    resp = httpx.get(url, headers={{\'X-ELS-APIKey\': key, \'Accept\': \'text/xml\'}}, timeout=30)\nexcept Exception as e:\n    sys.exit(\'http_error:\' + str(e))\nif resp.status_code != 200:\n    sys.exit(\'status=\' + str(resp.status_code) + \' len=\' + str(len(resp.text)) + \' pdf_pages=\' + str(pages))\nxml = resp.text\nbibs = xml.count(\'<ce:bib-reference\')\nif len(xml) < 3000 or bibs == 0:\n    sys.exit(\'no_fulltext:status=\' + str(resp.status_code) + \' len=\' + str(len(xml)) + \' bibs=\' + str(bibs) + \' pdf_pages=\' + str(pages))\nimport time\nfrom concurrent.futures import ThreadPoolExecutor, wait as _wait\nASSET_BUDGET = 20\nobjs = re.findall(r\'<object\\b([^>]*)>([^<]+)</object>\', xml)\nbest = {{}}\nfor attrs, link in objs:\n    a = dict(re.findall(r\'([\\w-]+)="([^"]*)"\', attrs))\n    rank = {{\'high\': 2, \'standard\': 1}}.get(a.get(\'category\'), 0)\n    if rank and a.get(\'type\') != \'ALTIMG\' and a.get(\'mimetype\', \'image/\').startswith(\'image/\') and a.get(\'ref\') and rank > best.get(a[\'ref\'], (0, \'\'))[0]:\n        best[a[\'ref\']] = (rank, link.strip().replace(\'&amp;\', \'&\'))\nwant = [(ref, v[1]) for ref, v in best.items()]\ndef _get(item):\n    ref, link = item\n    for i in range(5):\n        try:\n            r = httpx.get(link, headers={{\'X-ELS-APIKey\': key}}, timeout=20)\n        except Exception as e:\n            return ref, None, \'http_error:\' + type(e).__name__\n        if r.status_code != 429:\n            break\n        time.sleep(0.4 * (2 ** i))\n    b = r.content\n    if r.status_code != 200 or not (b[:3] == b\'\\xff\\xd8\\xff\' or b[:8] == b\'\\x89PNG\\r\\n\\x1a\\n\' or b[:4] == b\'GIF8\'):\n        return ref, None, \'status=%d bytes=%d\' % (r.status_code, len(b))\n    return ref, _fit(b), \'\'\nMAX_SIDE = 2000\ndef _fit(b):\n    try:\n        import io\n        from PIL import Image\n        im = Image.open(io.BytesIO(b))\n        if max(im.size) <= MAX_SIDE:\n            return b\n        im.thumbnail((MAX_SIDE, MAX_SIDE))\n        out = io.BytesIO()\n        im.convert(\'RGB\').save(out, \'JPEG\', quality=85, optimize=True)\n        return out.getvalue()\n    except Exception:\n        return b\nif want:\n    pool = ThreadPoolExecutor(4)\n    futs = {{pool.submit(_get, it): it[0] for it in want}}\n    done, pending = _wait(futs, timeout=ASSET_BUDGET)\n    for f in done:\n        ref, b, why = f.result()\n        if b:\n            print(\'ASSET:%s:\' % ref + base64.b64encode(b).decode())\n        else:\n            print(\'ASSETMISS:%s:%s\' % (ref, why))\n    for f in pending:\n        print(\'ASSETMISS:%s:timeout_%ds\' % (futs[f], ASSET_BUDGET))\n    pool.shutdown(wait=False, cancel_futures=True)\nprint(\'XML:%d:%d:\' % (pages, bibs) + base64.b64encode(xml.encode()).decode())\nsys.stdout.flush()\nos._exit(0)\n'

def _split_assets(lines):
    import base64
    lines = [ln for ln in lines if ln.strip()]
    assets, missing = ({}, [])
    for ln in lines[:-1]:
        if ln.startswith('ASSET:'):
            ref, _, b64 = ln[6:].partition(':')
            try:
                assets[ref] = base64.b64decode(b64)
            except Exception:
                missing.append(ref)
        elif ln.startswith('ASSETMISS:'):
            missing.append(ln[10:].partition(':')[0])
    return (lines[-1] if lines else '', assets, missing)

def _decode_payload(payload):
    m = re.match('^(PDF|XML):(\\d+):(?:(\\d+):)?(.+)$', payload, re.S)
    if not m:
        return ('XML', 0, 0, base64.b64decode(payload))
    fmt, pages, bibs, b64 = (m.group(1), int(m.group(2)), int(m.group(3) or 0), m.group(4))
    return (fmt, pages, bibs, base64.b64decode(b64))

class ElsevierAdapter(PublisherAdapter):
    publisher_name = 'Elsevier'
    doi_prefixes = ['10.1016/']
    channel_name = 'elsevier_api_xml'
    max_concurrency_per_node = 10
    estimated_seconds = 4.9
    protocol_version = '1.2'
    output_format = 'xml'
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
        doi_safe = doi.replace("'", "\\'")
        script = _ELSEVIER_SCRIPT_TEMPLATE.format(doi=doi_safe, key='').replace("key = ''", _KEYFILE_READ, 1)
        p = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, timeout=120)
        elapsed_ms = int((time.time() - t0) * 1000)
        out = p.stdout.strip().splitlines()
        if p.returncode == 0 and out:
            last, assets, missing = _split_assets(out)
            fmt, pages, bibs, raw = _decode_payload(last)
            if fmt == 'PDF':
                if pages and pages < 3:
                    return FetchResult(ok=False, channel=self.channel_name, format=None, pdf_bytes=None, fulltext=None, elapsed_ms=elapsed_ms, error_class=EC_OTHER, error='incomplete_pdf_preview: pages=%d (API 未回退 XML)' % pages, steps=['http:api.elsevier.com:pdf'], node=socket.gethostname())
                return FetchResult(ok=True, channel=self.channel_name + '_pdf', format='pdf', pdf_bytes=raw, fulltext=None, elapsed_ms=elapsed_ms, error_class='', error='', steps=['http:api.elsevier.com:pdf'], node=socket.gethostname(), pages=pages)
            steps = ['http:api.elsevier.com:xml']
            if pages:
                steps.insert(0, 'http:api.elsevier.com:pdf_preview:%d' % pages)
            return FetchResult(ok=True, channel=self.channel_name, format='xml', pdf_bytes=None, fulltext=raw.decode('utf-8', 'replace'), elapsed_ms=elapsed_ms, error_class='', error='', steps=steps, node=socket.gethostname(), assets=assets, assets_missing=missing)
        return FetchResult(ok=False, channel=self.channel_name, format=None, pdf_bytes=None, fulltext=None, elapsed_ms=elapsed_ms, error_class=EC_OTHER, error=((p.stderr or '') + (p.stdout or ''))[-300:] or 'no_output', steps=['http:api.elsevier.com'], node=socket.gethostname())

    def sample_dois(self):
        return ['10.1016/j.neucom.2015.11.009', '10.1016/j.ins.2016.01.081', '10.1016/j.asoc.2022.108606']
