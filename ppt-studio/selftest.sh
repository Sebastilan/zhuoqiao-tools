#!/bin/sh
# 离线自检:不联网、不花钱、不开浏览器;rc=0 且输出 selftest OK 即包完整
set -e
cd "$(dirname "$0")"
python3 -m py_compile tools/render_check.py
python3 - <<'PY'
import re, sys
from pathlib import Path
need = ["AGENTS.md", "画法.md", "tools/render_check.py", "tools/deck.js", "tools/deck.css"]
bad = [f for f in need if not Path(f).is_file()]
for st in ("lecture", "professional"):
    d = Path("styles") / st
    bad += [str(d / f) for f in ("spec.md", "tokens.css") if not (d / f).is_file()]
    pal = {c.lower() for c in re.findall(r"#[0-9A-Fa-f]{6}\b", (d / "tokens.css").read_text(encoding="utf-8"))}
    if len(pal) < 5:
        bad.append(f"{d}/tokens.css 色板不足")
    pages = sorted((d / "samples").glob("P*.html"))
    if len(pages) != 5:
        bad.append(f"{d}/samples 应有 5 页,现 {len(pages)}")
    for p in pages:
        t = p.read_text(encoding="utf-8")
        if len(re.findall(r'<section\b[^>]*class="[^"]*\bslide\b', t)) != 1:
            bad.append(f"{p}: 须恰有一个 section.slide")
        if '<aside class="notes">' not in t:
            bad.append(f"{p}: 缺讲稿备注")
        if re.search(r'(?:src|href)\s*=\s*"(?:https?:)?//', t) or "@import" in t:
            bad.append(f"{p}: 引了外部资源")
        if not (p.with_suffix(".jpg")).is_file():
            bad.append(f"{p}: 缺同名 JPG")
if bad:
    print("selftest FAIL\n" + "\n".join(bad)); sys.exit(1)
PY
if command -v node >/dev/null 2>&1; then node --check tools/deck.js; fi
echo "selftest OK"
