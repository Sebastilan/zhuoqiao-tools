#!/usr/bin/env python3
"""渲染自查:把页渲染成图,查字数、图占比、相交、越界、字号、色板"""
import asyncio, glob, json, os, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
包 = HERE.parent
默认css = 包 / "styles/lecture/tokens.css"
用法 = """用法:render_check.py <页目录> [--out 输出目录] [--css 风格.css] [--deck]
页目录里每页一个 P<n>.html,内容是一个 <section class="slide B-s" data-title="…" [data-kind="text|table"] [data-max="字数上限"]>…</section>(画布 1920×1080,讲稿逐字放 <aside class="notes">)。
--css 风格.css:选风格(styles/<风格>/tokens.css;缺省讲座版)。色板=该 css 里出现的 #rrggbb 加黑白;字数上限可在 css 里写 --max-art/--max-text/--max-table(缺省 130/160/260),页上 data-max 仍优先。
输出:<out>/P<n>.png(1920×1080)、自查.json、自查.md;--deck 另出翻页整稿 deck.html。退出码 0=全过,2=有问题。"""

JS = r"""
(lim) => {
  const R = e => e.getBoundingClientRect();
  const res = [];
  document.querySelectorAll('section.slide').forEach((s, i) => {
    const sr = R(s), iss = [], warn = [];
    const rel = r => ({l: r.left - sr.left, t: r.top - sr.top, r: r.right - sr.left, b: r.bottom - sr.top});
    const kind = s.dataset.kind || '';
    const items = [];            // 文字块:HTML 叶子文本元素 + svg text
    const walker = document.createTreeWalker(s, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = walker.nextNode())) {
      const t = n.nodeValue.replace(/\s/g, '');
      if (!t) continue;
      const el = n.parentElement;
      if (el.closest('aside,style,script,defs')) continue;
      const inSvg = !!el.closest('svg');
      const box = inSvg ? (el.closest('text') || el) : el;
      const rg = document.createRange(); rg.selectNodeContents(n);
      const rr = rg.getBoundingClientRect();
      if (rr.width < 1 || rr.height < 1) continue;
      items.push({el: box, r: rel(rr), txt: t, svg: inSvg, fs: parseFloat(getComputedStyle(el).fontSize)});
    }
    items.forEach(it => {
      if (it.r.l < 20 || it.r.r > 1900 || it.r.t < 0 || it.r.b > 1070) iss.push('越界:' + it.txt.slice(0, 12) + ` [${Math.round(it.r.l)},${Math.round(it.r.t)},${Math.round(it.r.r)},${Math.round(it.r.b)}]`);
      if (/[\u4e00-\u9fff][,;:!?]|[,;:!?][\u4e00-\u9fff]/.test(it.txt)) warn.push('中文间疑似半角标点:' + it.txt.slice(0, 10));
      if (it.fs < 22) warn.push(`字号 ${Math.round(it.fs)}px 偏小:` + it.txt.slice(0, 8));
    });
    for (let a = 0; a < items.length; a++) for (let b = a + 1; b < items.length; b++) {
      const x = items[a].r, y = items[b].r;
      const w = Math.min(x.r, y.r) - Math.max(x.l, y.l), h = Math.min(x.b, y.b) - Math.max(x.t, y.t);
      if (w > 4 && h > 4) {
        const small = Math.min((x.r - x.l) * (x.b - x.t), (y.r - y.l) * (y.b - y.t));
        if (w * h > 0.2 * small) iss.push('文字相交:' + items[a].txt.slice(0, 8) + ' × ' + items[b].txt.slice(0, 8));
      }
    }
    // 图占比:顶层 svg/img 的面积
    let art = 0;
    s.querySelectorAll('svg,img,canvas').forEach(e => { if (e.parentElement.closest('svg')) return; const r = rel(R(e)); const w = Math.max(0, Math.min(r.r, 1920) - Math.max(r.l, 0)), h = Math.max(0, Math.min(r.b, 1080) - Math.max(r.t, 0)); art += w * h; });
    const ratio = art / (1920 * 1080);
    if (!/text|table/.test(kind) && ratio < 0.22) iss.push('图占比 ' + Math.round(ratio * 100) + '% < 22%');
    const nchar = items.reduce((a, b) => a + b.txt.length, 0);
    const max = parseInt(s.dataset.max || (/table/.test(kind) ? lim.table : /text/.test(kind) ? lim.text : lim.art));
    if (nchar > max) iss.push(`上屏字数 ${nchar} > ${max}`);
    const h1 = s.querySelector('h1,.B-title');
    if (h1) { const cs = getComputedStyle(h1); if (parseFloat(cs.fontSize) < 64) iss.push('标题字号 ' + cs.fontSize + ' < 64'); if (!/serif|SimSun/i.test(cs.fontFamily)) iss.push('标题应用衬线字体'); }
    else iss.push('没有标题(h1 或 .B-title)');
    const html = s.outerHTML.replace(/<aside[\s\S]*?<\/aside>/, '');
    if (/https?:\/\//i.test(html.replace(/xmlns="[^"]*"/g, ''))) iss.push('含外链');
    const cols = [...new Set((html.match(/#[0-9a-fA-F]{6}\b/g) || []).map(c => c.toLowerCase()))];
    const notes = s.querySelector('aside.notes'); if (!notes || !notes.textContent.trim()) warn.push('备注(讲稿)缺');
    res.push({n: i + 1, title: s.dataset.title || '', nchar, ratio: Math.round(ratio * 100), iss, warn: [...new Set(warn)].slice(0, 6), colors: cols});
  });
  return res;
}
"""


def 风格(css):
    # 色板与字数上限跟着风格 css 走(否则换风格时色板会误报)
    色 = {c.lower() for c in re.findall(r"#[0-9a-fA-F]{6}\b", css)} | {"#ffffff", "#000000"}
    限 = {"art": 130, "text": 160, "table": 260}
    for k in 限:
        m = re.search(r"--max-%s\s*:\s*(\d+)" % k, css)
        if m:
            限[k] = int(m.group(1))
    return 色, 限


def 页文件(d):
    return sorted(glob.glob(os.path.join(d, "P*.html")), key=lambda p: int(re.search(r"P(\d+)", os.path.basename(p)).group(1)))


def 静态(secs, out, css):
    doc = ('<!DOCTYPE html><meta charset="utf-8"><style>*{box-sizing:border-box;margin:0;padding:0}body{background:#888;font-family:"Noto Sans CJK SC","Source Han Sans SC","PingFang SC","Microsoft YaHei",sans-serif}'
           'section.slide{position:relative;width:1920px;height:1080px;overflow:hidden;margin:0 0 8px;display:block}section.slide>aside{display:none}'
           '*{animation:none!important;transition:none!important}.rise,.B-in,[data-s]{opacity:1!important;transform:none!important}'
           + css + '</style><body>' + "\n".join(secs))
    Path(out).write_text(doc, encoding="utf-8")


async def 跑(静, 图目录, 限):
    from playwright.async_api import async_playwright
    # 浏览器:CHROME_BIN → playwright 缓存里已有的 chromium → playwright 默认(python -m playwright install chromium)
    exe = os.environ.get("CHROME_BIN") or (sorted(glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome"))) or [None])[-1]
    async with async_playwright() as p:
        b = await (p.chromium.launch(executable_path=exe) if exe else p.chromium.launch())
        pg = await b.new_page(viewport={"width": 1920, "height": 1080})
        await pg.goto(Path(静).resolve().as_uri())
        await pg.wait_for_timeout(600)
        res = await pg.evaluate(JS, 限)
        os.makedirs(图目录, exist_ok=True)
        for i, e in enumerate(await pg.query_selector_all("section.slide"), 1):
            await e.screenshot(path=os.path.join(图目录, f"P{i}.png"))
        await b.close()
    return res


def 拼deck(secs, out, tok):
    css = (HERE / "deck.css").read_text(encoding="utf-8")
    js = (HERE / "deck.js").read_text(encoding="utf-8")
    Path(out).write_text(f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>deck</title><style>{css}\n{tok}</style></head>
<body class="deck"><div id="deck"><div id="stage">{chr(10).join(secs)}</div><div id="pg"></div></div><div id="notes"></div><div id="jump"></div>
<div id="pv"><div class="now"></div><div class="next"></div><div class="meta"><span class="clock">00:00</span><span class="idx"></span></div><div class="txt"></div></div><script>{js}</script></body></html>""", encoding="utf-8")


def main():
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        sys.exit(用法)
    d = a[0]
    out = a[a.index("--out") + 1] if "--out" in a else os.path.join(d, "自查")
    fs = 页文件(d)
    if not fs:
        sys.exit(f"{d} 里没有 P<n>.html")
    secs = [Path(f).read_text(encoding="utf-8").strip() for f in fs]
    css文件 = a[a.index("--css") + 1] if "--css" in a else str(默认css)
    if not os.path.exists(css文件):
        sys.exit(f"找不到风格 css:{css文件}\n{用法}")
    css = Path(css文件).read_text(encoding="utf-8")
    色板, 限 = 风格(css)
    os.makedirs(out, exist_ok=True)
    静 = os.path.join(out, "静态.html")
    静态(secs, 静, css)
    res = asyncio.run(跑(静, out, 限))
    for r, f in zip(res, fs):
        r["file"] = os.path.basename(f)
        外 = [c for c in r["colors"] if c not in 色板]
        if 外:
            r["warn"].append("色板外颜色:" + ",".join(外[:4]))
    json.dump(res, open(os.path.join(out, "自查.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    md = ["# 渲染自查\n"] + [f"- {r['file']} 字数{r['nchar']} 图占比{r['ratio']}% " + ("✅" if not r["iss"] else "❌ " + ";".join(r["iss"])) + (" ⚠ " + ";".join(r["warn"]) if r["warn"] else "") for r in res]
    open(os.path.join(out, "自查.md"), "w", encoding="utf-8").write("\n".join(md))
    print("\n".join(md[1:]))
    if "--deck" in a:
        拼deck(secs, os.path.join(out, "deck.html"), css)
        print("整稿 →", os.path.join(out, "deck.html"))
    print("截图 →", out, "(P<n>.png,请逐张亲眼看:画面是否在说那句话)")
    sys.exit(0 if all(not r["iss"] for r in res) else 2)


main()
