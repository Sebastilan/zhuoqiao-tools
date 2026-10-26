#!/usr/bin/env python3
"""离线自检:不联网、不花钱、不需 key。rc=0 即代码完整。"""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pdf2md

# 1 接口齐全
assert callable(pdf2md.convert) and callable(pdf2md.main)
# 2 缺 key 时报清晰错误
for k in ("MINERU_TOKEN", "MINERU_TOKENS"):
    os.environ.pop(k, None)
pdf2md.load_env = lambda: None
try:
    pdf2md.tokens(); raise SystemExit("应当缺 key 报错")
except RuntimeError:
    pass
os.environ["MINERU_TOKENS"] = "a, b"
assert pdf2md.tokens() == ["a", "b"]
# 3 缓存命中路径(不联网):预置缓存后 convert 直接返回
with tempfile.TemporaryDirectory() as d:
    pdf = os.path.join(d, "x.pdf")
    open(pdf, "wb").write(b"%PDF-1.4 test")
    os.environ["PDF2MD_CACHE"] = os.path.join(d, "cache")
    k = pdf2md.file_key(pdf, "vlm")
    os.makedirs(os.path.join(d, "cache", k))
    open(os.path.join(d, "cache", k, "full.md"), "w").write("# hi")
    os.environ.pop("MINERU_TOKENS")
    r = pdf2md.convert([pdf], out=os.path.join(d, "out"))
    assert r[0]["ok"] and r[0]["cached"] and open(r[0]["md_path"]).read() == "# hi"
    # 4 不同 mode 不串缓存
    assert pdf2md.file_key(pdf, "pipeline") != k
print("selftest ok")
