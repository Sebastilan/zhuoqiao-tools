#!/usr/bin/env python3
"""pdf2md: 批量 PDF -> Markdown,调 MinerU 官方 API。仅标准库 + 系统 curl。

用法: python3 pdf2md.py a.pdf b.pdf [--mode vlm|pipeline] [--out DIR] [--no-cache] [--multi]
凭证: 环境变量 MINERU_TOKEN(单个)或 MINERU_TOKENS(逗号分隔,配合 --multi);
      也可放在脚本同目录 .env(KEY=VALUE 行)。缓存目录: PDF2MD_CACHE(默认 ~/.cache/pdf2md)。
"""
import argparse, hashlib, io, json, os, shutil, subprocess, sys, time, urllib.error, urllib.request, zipfile
from concurrent.futures import ThreadPoolExecutor

BASE = "https://mineru.net/api/v4"
SUBMIT_CAP = 45  # MinerU 限流约 50 文件/分钟,留余量
HERE = os.path.dirname(os.path.abspath(__file__))


def load_env():
    p = os.path.join(HERE, ".env")
    if os.path.isfile(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def tokens():
    load_env()
    ts = [t.strip() for t in os.environ.get("MINERU_TOKENS", "").split(",") if t.strip()]
    if not ts and os.environ.get("MINERU_TOKEN"):
        ts = [os.environ["MINERU_TOKEN"].strip()]
    if not ts:
        raise RuntimeError("缺 MINERU_TOKEN:到 https://mineru.net/apiManage 申请,写进环境变量或同目录 .env;向用户索取,勿编造")
    return ts


def cache_dir():
    return os.environ.get("PDF2MD_CACHE") or os.path.expanduser("~/.cache/pdf2md")


def file_key(path, mode):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return "%s-%s" % (h.hexdigest()[:32], mode)


def api(method, path, token, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Authorization", "Bearer " + token)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError("MinerU %s %s HTTP %s" % (method, path, e.code))
    if resp.get("code") not in (0, None) or "data" not in resp:
        raise RuntimeError("MinerU %s %s 业务失败 code=%s msg=%s" % (method, path, resp.get("code"), resp.get("msg")))
    return resp


def put_file(url, path):
    code = subprocess.check_output(["curl", "-s", "-X", "PUT", url, "--upload-file", path,
                                    "-o", "/dev/null", "-w", "%{http_code}"], timeout=300).decode().strip()
    if code != "200":
        raise RuntimeError("上传失败 HTTP %s: %s" % (code, path))


def run_batch(paths, mode, language, out, token, timeout=900, poll=5):
    names = [os.path.basename(p) for p in paths]
    body = {"enable_formula": True, "language": language, "model_version": mode,
            "files": [{"name": n, "is_ocr": False, "data_id": n[:128]} for n in names]}
    d = api("POST", "/file-urls/batch", token, body)["data"]
    for p, u in zip(paths, d["file_urls"]):
        put_file(u, p)
    t0, done = time.time(), {}
    while len(done) < len(names):
        if time.time() - t0 > timeout:
            raise TimeoutError("轮询超时 batch_id=%s" % d["batch_id"])
        time.sleep(poll)
        r = api("GET", "/extract-results/batch/" + d["batch_id"], token)
        for it in r["data"]["extract_result"]:
            if it.get("state") in ("done", "failed") and it["file_name"] not in done:
                done[it["file_name"]] = it
    res = []
    for p, n in zip(paths, names):
        it = done[n]
        if it["state"] != "done":
            res.append({"file": n, "ok": False, "error": it.get("err_msg")})
            continue
        dest = os.path.join(out, os.path.splitext(n)[0])
        os.makedirs(dest, exist_ok=True)
        with urllib.request.urlopen(it["full_zip_url"], timeout=300) as z:
            zipfile.ZipFile(io.BytesIO(z.read())).extractall(dest)
        md = os.path.join(dest, "full.md")
        res.append({"file": n, "ok": os.path.exists(md), "md_path": md})
    return res


def convert(pdfs, mode="vlm", language="en", out=None, use_cache=True, multi=False):
    for p in pdfs:
        if not os.path.isfile(p):
            raise FileNotFoundError(p)
    names = [os.path.basename(p) for p in pdfs]
    if len(set(names)) != len(names):
        raise ValueError("存在同名文件,请改名")
    out = out or os.path.join(os.path.dirname(os.path.abspath(pdfs[0])), "pdf2md_out")
    os.makedirs(out, exist_ok=True)
    cdir = cache_dir()
    results, todo = [], []
    for p in pdfs:
        k = file_key(p, mode) if use_cache else None
        hit = os.path.join(cdir, k) if k else None
        if hit and os.path.isdir(hit) and os.path.exists(os.path.join(hit, "full.md")):
            dest = os.path.join(out, os.path.splitext(os.path.basename(p))[0])
            shutil.copytree(hit, dest, dirs_exist_ok=True)
            results.append({"file": os.path.basename(p), "ok": True, "cached": True, "md_path": os.path.join(dest, "full.md")})
        else:
            todo.append((p, k))
    if todo:
        toks = tokens() if multi else tokens()[:1]
        groups = [[] for _ in toks]
        for i, it in enumerate(todo):
            groups[i % len(toks)].append(it)

        def work(tok, items):
            res = []
            for i in range(0, len(items), SUBMIT_CAP):
                if i:
                    time.sleep(62)
                res += run_batch([x[0] for x in items[i:i + SUBMIT_CAP]], mode, language, out, tok)
            return res

        with ThreadPoolExecutor(max_workers=len(toks)) as ex:
            futs = [ex.submit(work, t, g) for t, g in zip(toks, groups) if g]
            fresh = [r for f in futs for r in f.result()]
        keymap = {os.path.basename(p): k for p, k in todo}
        for r in fresh:
            k = keymap.get(r["file"])
            if r.get("ok") and k:
                try:
                    shutil.copytree(os.path.dirname(r["md_path"]), os.path.join(cdir, k), dirs_exist_ok=True)
                except OSError as e:
                    sys.stderr.write("缓存写入失败: %s\n" % e)
            results.append(r)
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(description="PDF -> Markdown (MinerU)")
    ap.add_argument("pdfs", nargs="+")
    ap.add_argument("--mode", default="vlm", choices=["vlm", "pipeline"])
    ap.add_argument("--language", default="en")
    ap.add_argument("--out")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--multi", action="store_true", help="多账号并行(MINERU_TOKENS)")
    a = ap.parse_args(argv)
    try:
        res = convert(a.pdfs, a.mode, a.language, a.out, not a.no_cache, a.multi)
    except Exception as e:
        print(json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False))
        return 1
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0 if all(r.get("ok") for r in res) else 2


if __name__ == "__main__":
    sys.exit(main())
