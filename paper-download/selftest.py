#!/usr/bin/env python3
"""Offline self-test for paper-download.

No network, no keys, no money. rc=0 means the code is complete and the pipeline logic works.
Run: python3 -I selftest.py   (needs `pip install -r requirements.txt`; PDF checks also need poppler-utils)"""
import os
import shutil
import socket
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "paperdl")]
sys.dont_write_bytecode = True


def _no_net(*a, **k):
    raise OSError("selftest: network disabled")


socket.create_connection = _no_net
socket.socket.connect = _no_net
socket.getaddrinfo = _no_net

FAILS = []


def ok(cond, name):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        FAILS.append(name)


def make_pdf(lines_per_page, pad=24000):
    """Minimal valid PDF (Helvetica text pages) padded above the 20 kB sanity floor."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for lines in lines_per_page:
        esc = [ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for ln in lines]
        body = "BT /F1 11 Tf 50 750 Td 14 TL " + " ".join("(%s) '" % s for s in esc) + " ET"
        objs.append("<< /Length %d >>\nstream\n%s\nendstream" % (len(body), body))
        objs.append("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>" % len(objs))
        kids.append(len(objs))
    objs[1] = "<< /Type /Pages /Kids [%s] /Count %d >>" % (" ".join("%d 0 R" % k for k in kids), len(kids))
    out, offs = b"%PDF-1.4\n%" + b"x" * pad + b"\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += ("%d 0 obj\n%s\nendobj\n" % (i, o)).encode("latin1")
    x = len(out)
    out += ("xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)).encode()
    out += b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += ("trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)).encode()
    return out


def main():
    # 1. every module imports
    try:
        import paper_download as pd
        import verify_pdf, metadata, xml2pdf  # noqa: F401
        from paperdl import resolve as rs
        from lib.handlers import oa_layer, browser_seq, elsevier, ieee, mdpi, arxiv  # noqa: F401
        mods = pd.adapters()
        ok(len(mods) == 18, "imports + 18 modules")
    except ImportError as e:
        print("FAIL import: %s  (run: pip install -r requirements.txt)" % e)
        return 1

    # 2. routing
    route = {"10.1016/j.x.2020.1": "ElsevierAdapter", "10.1109/TEVC.2023.1": "IEEEDirectAdapter",
             "10.1007/s001": "SpringerSeqAdapter", "10.1038/s41586-1": "NatureSeqAdapter",
             "10.1002/abc": "WileySeqAdapter", "10.3390/s1": "MDPIAdapter", "10.48550/arXiv.1706.03762": "ArXivAdapter",
             "10.13374/j.cnki.x.1": "CnkiSeqAdapter", "10.3969/j.issn.1": "WanfangSeqAdapter",
             "10.9999/unknown": "GenericLandingHttpAdapter"}
    for d, want in route.items():
        got = type(pd.match_module(d, mods)).__name__
        ok(got == want, "route %s -> %s (got %s)" % (d, want, got))

    # 3. resolver, offline paths
    r = rs.resolve("10.1038/s41586-021-03819-2")
    ok(r.get("ok") and r.get("confidence") == "exact" and r["doi"].lower() == "10.1038/s41586-021-03819-2", "resolve bare DOI")
    r = rs.resolve("https://doi.org/10.1109/TEVC.2023.3281666")
    ok((r.get("doi") or "").lower() == "10.1109/tevc.2023.3281666", "resolve doi.org URL")
    old = os.environ.pop("SERPER_API_KEY", None)
    ok(rs._web("anything") == [], "web search without key returns [] (no crash)")
    if old is not None:
        os.environ["SERPER_API_KEY"] = old

    # 4. page-count gate
    ok(not verify_pdf.pages_short(1, 100, 112)["pass"], "pages_short rejects 1-page preview of a 13-page article")
    ok(verify_pdf.pages_short(12, 100, 112)["pass"], "pages_short accepts full article")

    # 5. config without credentials fails cleanly
    os.environ.pop("ELSEVIER_API_KEY", None)
    ok("ELSEVIER_API_KEY" in elsevier._KEYFILE_READ, "Elsevier key comes from env")
    os.environ.pop("DESK_ACT", None)
    try:
        browser_seq._desk_act()
        ok(False, "browser publishers refuse to run without DESK_ACT")
    except RuntimeError:
        ok(True, "browser publishers refuse to run without DESK_ACT")

    # 6. full pipeline with a fake publisher module (needs poppler-utils)
    if not (shutil.which("pdfinfo") and shutil.which("pdftotext")):
        print("SKIP pipeline/verification checks: poppler-utils (pdfinfo, pdftotext) not installed")
        return 1 if FAILS else 0
    doi = "10.9999/selftest.0001"
    meta = {"title": "A Self Test Article on Verified Downloads", "authors": ["Ada Lovelace", "Alan Turing"],
            "first_page": "1", "last_page": "4"}
    good = make_pdf([["A Self Test Article on Verified Downloads", "Ada Lovelace, Alan Turing", "doi: " + doi]] +
                    [["page %d body text" % i] for i in range(2, 5)])
    wrong = make_pdf([["Some Other Paper Entirely", "Someone Else", "doi: 10.9999/other"]] + [["x"]] * 3)
    preview = make_pdf([["A Self Test Article on Verified Downloads", "Ada Lovelace", "doi: " + doi]])
    ok(pd.verify(good, doi, meta)[0], "verify accepts the right paper")
    ok(not pd.verify(wrong, doi, meta)[0], "verify rejects a different paper")
    ok(not pd.verify(preview, doi, meta)[0], "verify rejects a 1-page preview")

    from lib.core.protocol import FetchResult

    class Fake:
        doi_prefixes, publisher_name = ["10.9999/"], "Fake"
        payload = good

        def _fetch_local(self, d, **k):
            return FetchResult(ok=True, channel="fake", format="pdf", pdf_bytes=self.payload, fulltext=None,
                               elapsed_ms=1, error_class="", error="")

    lib = tempfile.mkdtemp(prefix="paperdl-selftest-")
    out = tempfile.mkdtemp(prefix="paperdl-selftest-out-")
    os.environ["PAPERDL_LIBRARY"] = lib
    metadata.get_meta_node = lambda d: meta
    metadata.crossref = metadata.openalex = lambda d: None
    fake = Fake()
    pd.match_module = lambda d, m=None: fake
    try:
        r1 = pd.run(doi, out, use_oa=False)
        ok(r1.get("ok") and r1.get("source") == "publisher" and os.path.isfile(r1.get("file", "")), "pipeline: publisher -> verify -> library -> out")
        r2 = pd.run(doi, out, use_oa=False)
        ok(r2.get("ok") and r2.get("source") == "library", "pipeline: second call is a verified library hit")
        with open(os.path.join(lib, pd.key_of(doi) + ".pdf"), "wb") as f:
            f.write(preview)
        r3 = pd.run(doi, None, use_oa=False)
        ok(r3.get("ok") and r3.get("source") == "publisher" and r3.get("library_rejected"), "pipeline: bad cached copy is rejected and replaced")
        ok(any(n.endswith(".pdf") and ".rejected." in n for n in os.listdir(lib)) or
           any(".rejected." in n for n in os.listdir(lib)), "pipeline: rejected copy kept as backup")
        fake.payload = wrong
        os.environ["PAPERDL_LIBRARY"] = tempfile.mkdtemp(prefix="paperdl-selftest-")
        r4 = pd.run(doi, None, use_oa=False)
        ok(not r4.get("ok") and r4.get("error") == "verify_failed", "pipeline: wrong paper is not delivered")
        pd.match_module = lambda d, m=None: None
        r5 = pd.run("10.9999/none", None, use_oa=False)
        ok(not r5.get("ok") and r5.get("error") == "no_module", "pipeline: no module -> honest failure")
    finally:
        shutil.rmtree(lib, ignore_errors=True)
        shutil.rmtree(out, ignore_errors=True)
    print("selftest: %d failure(s)" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    rc = main()
    sys.stdout.flush()
    os._exit(rc)
