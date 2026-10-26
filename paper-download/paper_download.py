#!/usr/bin/env python3
"""paper-download: any reference (DOI / URL / title) -> DOI -> verified PDF, on a single machine.

Pipeline: local library -> open-access layer (identity-verified) -> publisher module -> XML->PDF if needed
-> verification (PDF sanity, title/author/DOI identity, page count vs. registered page range) -> local library.
No fallback to unrelated sources: no module / no access / failed verification are reported as failures.

Usage: python3 paper_download.py <DOI|URL|title> [--out DIR] [--no-oa] [--no-library] [--min-confidence high|medium|low]
stdout: one JSON object. rc: 0 delivered, 2 not delivered (no_module / no_access / verify_failed), 3 could not resolve, 1 usage/config.
"""
import argparse
import json
import os
import re
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "paperdl"))   # verify_pdf imports xml2pdf as a top-level module
sys.dont_write_bytecode = True

OA_MAX = 3
OA_SKIP = ("10.48550/", "10.3390/")   # arXiv and MDPI: own modules are open and fast; OA lookup only adds latency
CONF_RANK = {"exact": 3, "high": 2, "medium": 1, "low": 0}


def library_dir():
    return os.path.expanduser(os.environ.get("PAPERDL_LIBRARY") or "~/paper-library")


def key_of(doi):
    return re.sub(r"[^a-z0-9]+", "_", doi.lower()).strip("_")


def adapters():
    from lib.handlers.ieee import IEEEDirectAdapter
    from lib.handlers.elsevier import ElsevierAdapter
    from lib.handlers.mdpi import MDPIAdapter
    from lib.handlers.arxiv import ArXivAdapter
    from lib.handlers import browser_seq as b
    return [IEEEDirectAdapter(), ElsevierAdapter(), b.SpringerSeqAdapter(), b.NatureSeqAdapter(), b.ApsHttpAdapter(),
            b.PlosHttpAdapter(), b.CambridgeHttpAdapter(), b.FrontiersHttpAdapter(), b.IopSeqAdapter(), b.AcsSeqAdapter(),
            b.AcmSeqAdapter(), b.DeGruyterSeqAdapter(), b.CnkiSeqAdapter(), b.WanfangSeqAdapter(), b.WileySeqAdapter(),
            MDPIAdapter(), ArXivAdapter(), b.GenericLandingHttpAdapter()]


def match_module(doi, mods=None):
    """Longest DOI-prefix match; substring rules (CNKI/Wanfang) outrank prefixes; else the generic landing-page module."""
    d = doi.strip().lower()
    mods = mods if mods is not None else adapters()
    best, best_len = None, 0
    for m in mods:
        for pre in m.doi_prefixes:
            if d.startswith(pre.lower()) and len(pre) > best_len:
                best, best_len = m, len(pre)
        for sub in getattr(m, "doi_substrings", []):
            if sub.lower() in d and best_len < 100:
                best, best_len = m, 100
    if best is None:
        best = next((m for m in mods if getattr(m, "catch_all", False)), None)
    return best


def verify(raw, doi, meta):
    import verify_pdf
    checks = verify_pdf.check(raw, "pdf")
    ident = verify_pdf.check_identity(raw, "pdf", meta, doi)
    checks["identity"] = ident
    m = meta or {}
    checks["pages_range"] = verify_pdf.pages_short(checks.get("pages"), m.get("first_page"), m.get("last_page"))
    ok = bool(checks.get("pass") and ident.get("identity") and checks["pages_range"].get("pass", True))
    return ok, checks


def store(doi, raw):
    lib = library_dir()
    os.makedirs(lib, exist_ok=True)
    dst = os.path.join(lib, key_of(doi) + ".pdf")
    if os.path.exists(dst):   # only reached when the cached copy failed verification: keep it as a backup
        os.replace(dst, dst + ".rejected." + time.strftime("%Y%m%dT%H%M%S"))
    tmp = dst + ".part"
    with open(tmp, "wb") as f:
        f.write(raw)
    os.replace(tmp, dst)
    return dst


def deliver(path, out_dir, doi):
    if not out_dir:
        return path
    os.makedirs(out_dir, exist_ok=True)
    dst = os.path.join(out_dir, key_of(doi) + ".pdf")
    if os.path.abspath(dst) != os.path.abspath(path):
        shutil.copyfile(path, dst)
    return dst


def run(doi, out_dir=None, use_oa=True, use_library=True):
    import metadata
    T = {}
    mark = lambda k, t: T.__setitem__(k, round(time.time() - t, 2))
    meta_f = ThreadPoolExecutor(1).submit(metadata.get_meta_node, doi)

    def meta(wait=60):
        try:
            return meta_f.result(timeout=wait)
        except Exception:
            return None

    rejected = None
    lp = os.path.join(library_dir(), key_of(doi) + ".pdf")
    if use_library and os.path.exists(lp):
        import verify_pdf
        t = time.time()
        c = verify_pdf.check_cached_file(lp, "pdf", meta(20), doi,
                                         meta_of=lambda d: metadata.crossref(d) or metadata.openalex(d))
        mark("library_verify", t)
        if c.get("pass"):
            return {"ok": True, "doi": doi, "source": "library", "file": deliver(lp, out_dir, doi), "checks": c, "timing": T}
        rejected = {"reason": c.get("reason"), "why": c.get("why"), "pages": c.get("pages")}

    mod = match_module(doi)
    cls = type(mod).__name__ if mod else ""
    if use_oa and not doi.lower().startswith(OA_SKIP):
        from lib.handlers.oa_layer import OALayerAdapter
        t, idx = time.time(), 0
        for _ in range(OA_MAX):
            r = OALayerAdapter()._fetch_local("%s#c=%d" % (doi, idx))
            if not (r.ok and r.pdf_bytes):
                break
            k, version, src, host = (r.channel.split(":", 4) + ["", "", "", ""])[1:5]
            ok, checks = verify(r.pdf_bytes, doi, meta())
            if ok:
                mark("oa_layer", t)
                p = store(doi, r.pdf_bytes)
                return {"ok": True, "doi": doi, "source": "open_access", "oa": {"version": version, "source": src, "host": host},
                        "file": deliver(p, out_dir, doi), "checks": checks, "timing": T,
                        **({"library_rejected": rejected} if rejected else {})}
            try:
                idx = int(k) + 1
            except ValueError:
                break
        mark("oa_layer", t)
    if mod is None:
        return {"ok": False, "doi": doi, "error": "no_module", "timing": T}
    t = time.time()
    try:
        r = mod._fetch_local(doi)
    except Exception as e:   # noqa: BLE001
        return {"ok": False, "doi": doi, "module": cls, "error": "module_exception: %s: %s" % (type(e).__name__, str(e)[:160]), "timing": T}
    mark("module", t)
    base = {"doi": doi, "module": cls, "channel": r.channel, "timing": T}
    payload = r.pdf_bytes if r.pdf_bytes else (r.fulltext.encode("utf-8") if r.fulltext else None)
    if not (r.ok and payload):
        return dict(base, ok=False, error=r.error or "no_payload")
    fmt, conv = r.format or "pdf", {}
    if fmt != "pdf":   # full-text XML is never delivered as-is: render to PDF or fail
        t = time.time()
        try:
            import xml2pdf
            pdf = xml2pdf.to_pdf(payload, getattr(r, "assets", None) or {})
        except Exception as e:   # noqa: BLE001
            return dict(base, ok=False, error="not_pdf_and_render_failed(%s): %s: %s" % (fmt, type(e).__name__, str(e)[:160]))
        conv = {"converted_from": fmt, "completeness": getattr(pdf, "completeness", None)}
        payload = bytes(pdf)
        mark("xml_to_pdf", t)
    t = time.time()
    ok, checks = verify(payload, doi, meta())
    mark("verify", t)
    if not ok:
        return dict(base, ok=False, error="verify_failed", checks=checks)
    p = store(doi, payload)
    return dict(base, ok=True, source="publisher", file=deliver(p, out_dir, doi), checks=checks, **conv,
                **({"library_rejected": rejected} if rejected else {}))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("ref", nargs="+", help="DOI, URL, or free-text title/citation")
    ap.add_argument("--out", help="copy the delivered PDF here (default: only the library copy)")
    ap.add_argument("--no-oa", action="store_true", help="skip the open-access layer")
    ap.add_argument("--no-library", action="store_true", help="ignore the local library cache")
    ap.add_argument("--min-confidence", default="high", choices=["high", "medium", "low"],
                    help="minimum resolver confidence for non-DOI input (default high)")
    a = ap.parse_args(argv)
    from paperdl.resolve import resolve
    res = resolve(" ".join(a.ref))
    if not res.get("ok") or not res.get("doi"):
        print(json.dumps({"ok": False, "error": "unresolved", "resolved": res}, ensure_ascii=False))
        return 3
    if CONF_RANK.get(res.get("confidence"), 0) < CONF_RANK[a.min_confidence]:
        print(json.dumps({"ok": False, "error": "low_confidence", "resolved": res}, ensure_ascii=False))
        return 3
    out = run(res["doi"], a.out, not a.no_oa, not a.no_library)
    out["resolved"] = res
    print(json.dumps(out, ensure_ascii=False, default=str))
    sys.stdout.flush()
    return 0 if out.get("ok") else 2


if __name__ == "__main__":
    rc = main()
    os._exit(rc)   # module threads (metadata) may still be running; do not wait for them
