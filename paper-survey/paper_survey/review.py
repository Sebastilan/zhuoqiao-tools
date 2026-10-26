"""审阅层:结果页叠加勾选/批注与导出,篇号索引,按勾选批量下载。

页面是本地静态 HTML:勾选与批注存在浏览器 localStorage,点「导出勾选与批注」下载 review.json;
批量下载读 review.json 或 --picks 给的篇号,逐篇调 PAPER_DOWNLOAD_CMD(用户自装的下载工具,
推荐开源工具 paper-download),本包不实现下载。篇号 = 结果里的 n,与综述正文的 [n] 同号。
"""
import html
import json
import re
import shlex
import subprocess
import time
from pathlib import Path

import config

REC_ORDER = {"must": 0, "maybe": 1}
REC_LABEL = {"must": "必读", "maybe": "可看"}
ZIP_OVER = 3        # 成功篇数超过这个就额外打一个压缩包
MAX_PICKS = 20
ZIP_MAX_MB = 80


class SchemaError(ValueError):
    pass


def esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def validate(res):
    """result.json 字段自检:缺关键字段就抛 SchemaError 写清缺什么,不静默出空页。"""
    if not isinstance(res, dict):
        raise SchemaError("调研结果不是对象")
    miss = [k for k in ("items", "summary", "need") if k not in res]
    if miss:
        raise SchemaError("调研结果缺字段: " + "、".join(miss))
    if not isinstance(res["items"], list) or not res["items"]:
        raise SchemaError("调研结果里没有文献(items 为空)")
    for i, it in enumerate(res["items"]):
        if not (isinstance(it, dict) and it.get("title")):
            raise SchemaError("第 %d 篇缺字段: title" % (i + 1))
    return res


def pid(it):
    return str(it.get("n") or it.get("id") or "")


def download_input(it):
    """交给下载工具的入口:DOI > 链接 > 题名。"""
    return (it.get("doi") or "").strip() or (it.get("url") or "").strip() or (it.get("title") or "").strip()


def download_basis(it):
    return "doi" if (it.get("doi") or "").strip() else "url" if (it.get("url") or "").strip() else "title"


def basis_text(p):
    """重要性依据短句:必读/可看 · 相关度 · 被引;缺了写"未记录",不编。"""
    rel, cit = p.get("relevance"), p.get("cites")
    return "%s · 相关度%s · 被引%s" % (REC_LABEL.get(p.get("rec"), "未分级"),
                                    rel if rel is not None else "未记录", cit if cit is not None else "未记录")


def build_index(res, sid):
    """篇号索引:篇号 → 下载要用的字段;展示之外的文献也存。"""
    papers = {}
    for it in res["items"]:
        k = pid(it)
        if not k:
            continue
        papers[k] = {"title": it.get("title", ""), "title_zh": it.get("title_zh") or "", "year": it.get("year"),
                     "doi": it.get("doi") or "", "url": it.get("url") or "", "venue": it.get("venue") or "",
                     "rec": it.get("rec") or "", "relevance": it.get("relevance"), "cites": it.get("cites"),
                     "one_line": it.get("one_line") or "", "input": download_input(it), "basis": download_basis(it)}
        for f in ("authors", "cas"):
            if it.get(f):
                papers[k][f] = it[f]
    return {"sid": sid, "need": res.get("need", ""), "made": time.strftime("%Y-%m-%d %H:%M"), "papers": papers}


def rank_top(idx, n):
    """按重要性取前 n 篇:必读>可看,再相关度、被引、篇号。"""
    def key(kv):
        k, p = kv
        return (REC_ORDER.get(p.get("rec"), 9), -(p.get("relevance") or 0), -(p.get("cites") or 0),
                int(k) if str(k).isdigit() else 10 ** 9)
    return sorted((idx.get("papers") or {}).items(), key=key)[:n]


# ───────────── 页面叠加(只叠加,不改正文) ─────────────
_LI_RE = re.compile(r'<li class="ref" id="ref-(\d+)"[^>]*>')
_LI_TAG_RE = re.compile(r'<li\b|</li>')
_MORE_RE = re.compile(r'(<details>\s*<summary[^>]*>)(.*?)(</summary>)', re.S)
TOP_ZH, TOP_EN = "浅层调研(仅根据摘要)", "Shallow Survey (abstract-based only)"

_CSS = """<style id="review-css">
.rv{display:flex;gap:8px;flex-wrap:wrap;margin:6px 0 2px}
label.anno-pick,button.anno-note-btn{display:inline-flex;align-items:center;gap:6px;padding:4px 12px;border-radius:9px;border:0;
 background:var(--card,#f1f5f9);color:var(--fg,#334155);font:600 14px system-ui;cursor:pointer}
label.anno-pick input{width:18px;height:18px}
textarea.anno-note{display:block;width:100%;min-height:56px;margin-top:6px;font:14px system-ui;padding:6px;border:1px solid var(--line,#ccc);border-radius:6px;background:var(--bg,#fff);color:var(--fg,#111)}
textarea.anno-note[hidden]{display:none}
li.ref.anno-picked{background:rgba(22,163,74,.08);outline:1px solid rgba(22,163,74,.5)}
li.ref.anno-picked label.anno-pick{background:#16a34a;color:#fff}
#review-bar{position:fixed;right:14px;bottom:14px;z-index:9;display:flex;gap:8px;align-items:center;background:var(--bg,#fff);border:1px solid var(--line,#ccc);border-radius:12px;padding:6px 10px;font:14px system-ui}
#review-bar button{font:600 14px system-ui;padding:4px 12px;border-radius:9px;border:1px solid var(--accent,#2563eb);background:transparent;color:var(--accent,#2563eb);cursor:pointer}
summary .fold-hint{display:block;margin-top:4px;font:500 13px system-ui;color:var(--accent,#2563eb)}
details[open]>summary .fold-hint .fc,details:not([open])>summary .fold-hint .fo{display:none}
</style>"""

_JS = """<script id="review-js">
(function(){
  var KEY='paper-survey:'+document.body.getAttribute('data-sid'), st={picks:{},notes:{}};
  try{ var o=JSON.parse(localStorage.getItem(KEY)||'{}'); st.picks=o.picks||{}; st.notes=o.notes||{}; }catch(e){}
  function save(){ try{ localStorage.setItem(KEY, JSON.stringify(st)); }catch(e){} count(); }
  function count(){ var n=Object.keys(st.picks).filter(function(k){return st.picks[k];}).length;
    var c=document.getElementById('review-count'); if(c) c.textContent='已勾 '+n+' 篇'; }
  document.querySelectorAll('input.anno-pick-cb').forEach(function(cb){
    var k=cb.getAttribute('data-pick'), li=cb.closest('li.ref');
    cb.checked=!!st.picks[k]; if(li) li.classList.toggle('anno-picked',cb.checked);
    cb.onchange=function(){ st.picks[k]=cb.checked; if(li) li.classList.toggle('anno-picked',cb.checked); save(); };
  });
  document.querySelectorAll('textarea.anno-note').forEach(function(ta){
    var k=ta.getAttribute('data-note'); if(st.notes[k]){ ta.value=st.notes[k]; ta.hidden=false; }
    ta.oninput=function(){ st.notes[k]=ta.value; save(); };
  });
  document.querySelectorAll('button.anno-note-btn').forEach(function(b){
    b.onclick=function(){ var ta=document.querySelector('textarea[data-note="'+b.getAttribute('data-for')+'"]');
      if(ta){ ta.hidden=!ta.hidden; if(!ta.hidden) ta.focus(); } };
  });
  var ex=document.getElementById('review-export');
  if(ex) ex.onclick=function(){
    var picks=Object.keys(st.picks).filter(function(k){return st.picks[k];}).map(function(k){return k.split(':')[1];});
    var notes={}; Object.keys(st.notes).forEach(function(k){ if((st.notes[k]||'').trim()) notes[k]=st.notes[k].trim(); });
    var blob=new Blob([JSON.stringify({sid:document.body.getAttribute('data-sid'),picks:picks,notes:notes},null,2)],{type:'application/json'});
    var a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download='review.json'; document.body.appendChild(a); a.click(); a.remove();
  };
  count();
})();
</script>"""


def _hint_html(what=""):
    w = (what + " ") if what else ""
    return ('<span class="fold-hint"><span class="fc">%s▸ 已折叠,点击展开</span>'
            '<span class="fo">%s▾ 点击收起</span></span>') % (w, w)


def _fold_hint(inner):
    what = "摘要" if re.search(r"<b>(摘要|Abstract)</b>", inner) and 'class="ab none"' not in inner else "详情"
    return _hint_html(what)


def retitle(page):
    page = page.replace("<title>快速调研</title>", "<title>%s</title>" % TOP_ZH, 1)
    return re.sub(r'(<span class="brand">)<span class="zh">快速调研</span><span class="en">Quick Survey</span>',
                  r'\1<span class="zh">%s</span><span class="en">%s</span>' % (TOP_ZH, TOP_EN), page, count=1)


def decorate(page, sid, shown_ids=None, basis=None):
    """每篇 <li> 加 data-slot=paper:<篇号>、条尾「下载这篇」勾选 + 「批注」框;综述段落可批注;右下角导出条。
    shown_ids 给定则只给这些篇号放勾选框。"""
    out, last, cnt = [], 0, 0
    for m in _LI_RE.finditer(page):
        if m.start() < last:
            continue
        depth, end = 1, None
        for t in _LI_TAG_RE.finditer(page, m.end()):
            if t.group(0) == "</li>":
                depth -= 1
                if depth == 0:
                    end = t.start()
                    break
            else:
                depth += 1
        if end is None:
            raise SchemaError("调研页里的文献条目没有闭合(<li> 缺 </li>)")
        n = m.group(1)
        inner = page[m.end():end]
        if "<details" in inner and "</summary>" in inner:
            inner = inner.replace("</summary>", _fold_hint(inner) + "</summary>", 1)
        bt = ('<span class="tag">依据:%s</span>' % esc(basis_text(basis[n]))) if basis and n in basis else ""
        pick = ('<label class="anno-pick"><input type="checkbox" class="anno-pick-cb" data-pick="paper:%s"> 下载这篇</label>' % n
                if shown_ids is None or n in shown_ids else "")
        note = ('<button type="button" class="anno-note-btn" data-for="paper:%s">批注</button>' % n)
        box = '<div class="rv">%s%s%s</div><textarea class="anno-note" data-note="paper:%s" hidden placeholder="写批注…"></textarea>' % (bt, pick, note, n)
        out.append(page[last:m.start()])
        out.append('<li class="ref" id="ref-%s" data-slot="paper:%s">%s%s</li>' % (n, n, inner, box))
        last = end + len("</li>")
        cnt += 1
    if not cnt:
        raise SchemaError("调研页里找不到文献条目(页面结构可能变了)")
    out.append(page[last:])
    page = retitle("".join(out))
    page = _MORE_RE.sub(lambda m: m.group(1) + m.group(2) + _hint_html() + m.group(3), page)
    page = re.sub(r"<body([^>]*)>", lambda m: '<body%s data-sid="%s">' % (m.group(1), esc(sid)), page, count=1)
    bar = ('<div id="review-bar"><span id="review-count">已勾 0 篇</span>'
           '<button id="review-export" type="button">导出勾选与批注</button></div>')
    page = page.replace("</body>", bar + _JS + "</body>", 1)
    return page.replace("</head>", _CSS + "</head>", 1)


def make_review(res, sid, html_path):
    """result.json → 叠加后的 index.html(就地覆盖)+ papers.json 篇号索引。返回 (索引路径, 篇数, 必读数)。"""
    validate(res)
    html_path = Path(html_path)
    ids = {pid(it) for it in res["items"] if pid(it)}
    page = decorate(html_path.read_text(encoding="utf-8"), sid, ids, {pid(it): it for it in res["items"] if pid(it)})
    html_path.write_text(page, encoding="utf-8")
    idx_path = html_path.parent / "papers.json"
    idx_path.write_text(json.dumps(build_index(res, sid), ensure_ascii=False, indent=1), encoding="utf-8")
    return idx_path, len(ids), sum(1 for it in res["items"] if it.get("rec") == "must")


# ───────────── 批量下载 ─────────────

def parse_picks(text):
    """"12,15、18 20" → ['12','15','18','20'](去重保序;007 → 7)。"""
    out = []
    for t in re.split(r"[\s,，、;；]+", str(text or "")):
        t = t.strip().lstrip("[P#").rstrip("]")
        t = str(int(t)) if t.isdigit() else t
        if t and t not in out:
            out.append(t)
    return out


def make_zips(files, out_dir, sid, max_mb=ZIP_MAX_MB):
    """files: [(篇号, 本地路径, 题名)] → 压缩包路径列表(超过 max_mb 拆包);包里带 清单.txt。"""
    import zipfile
    groups, cur, size = [], [], 0
    for f in files:
        sz = Path(f[1]).stat().st_size
        if cur and size + sz > max_mb * 1024 * 1024:
            groups.append(cur)
            cur, size = [], 0
        cur.append(f)
        size += sz
    if cur:
        groups.append(cur)
    zips = []
    for i, g in enumerate(groups, 1):
        zp = Path(out_dir) / ("papers-%s-%d%s.zip" % (sid, len(files), ("-part%d" % i) if len(groups) > 1 else ""))
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_STORED) as z:
            for k, path, title in g:
                z.write(path, "[%s]%s" % (k, Path(path).name))
            z.writestr("清单.txt", "\n".join("[%s] %s  (%s)" % (k, title, Path(path).name) for k, path, title in g))
        zips.append(zp)
    return zips


def command_downloader(template=None, timeout=300):
    """按 PAPER_DOWNLOAD_CMD 模板下载一篇:{input} 换成 DOI/链接/题名,{out} 换成该篇目录;
    rc=0 且目录里出现 PDF 才算成功。"""
    template = template or config.get("PAPER_DOWNLOAD_CMD")
    if not template:
        raise SchemaError("未配置 PAPER_DOWNLOAD_CMD(下载工具命令模板,见 .env.example)")

    def dl(inp, out):
        out = Path(out)
        out.mkdir(parents=True, exist_ok=True)
        cmd = [a.replace("{input}", inp).replace("{out}", str(out)) for a in shlex.split(template)]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"ok": False, "why": "超时"}
        pdfs = sorted(out.glob("*.pdf"), key=lambda p: p.stat().st_mtime)
        if r.returncode == 0 and pdfs:
            return {"ok": True, "path": str(pdfs[-1])}
        tail = ((r.stderr or r.stdout).strip().splitlines() or ["无输出"])[-1][:160]
        return {"ok": False, "why": "rc=%d %s" % (r.returncode, tail)}
    return dl


def download_batch(idx, picks, out_dir, downloader, zip_over=ZIP_OVER, workers=2):
    """逐篇下载到 out_dir/<篇号>/;成功超过 zip_over 篇另打包。返回 (报告文本, 结果列表)。"""
    from concurrent.futures import ThreadPoolExecutor
    papers = idx.get("papers") or {}
    unknown = [k for k in picks if k not in papers]
    known = [k for k in picks if k in papers][:MAX_PICKS]
    if not known:
        return "失败: 篇号 %s 在这次调研里都找不到。" % ("、".join(picks) or "(空)"), []
    out_dir = Path(out_dir)

    def one(k):
        p = papers[k]
        try:
            return k, downloader(p.get("input") or p.get("title"), out_dir / k)
        except Exception as e:
            return k, {"ok": False, "why": "下载出错: %s" % type(e).__name__}

    with ThreadPoolExecutor(max_workers=workers) as ex:
        res = list(ex.map(one, known))
    ok = [(k, r["path"], papers[k].get("title", "")) for k, r in res if r.get("ok") and r.get("path")]
    bad = [(k, papers[k].get("title", ""), r.get("why") or "原因未知") for k, r in res if not (r.get("ok") and r.get("path"))]
    parts = []
    if ok:
        parts.append("下到 %d 篇:\n  " % len(ok) + "\n  ".join("[%s]《%s》 %s" % (k, t[:50], p) for k, p, t in ok))
        if len(ok) > zip_over:
            parts.append("压缩包: " + ", ".join(str(z) for z in make_zips(ok, out_dir, idx.get("sid", "x"))))
    if bad:
        parts.append("没下到 %d 篇:\n  " % len(bad) + "\n  ".join("[%s]《%s》(依据 %s)%s" % (k, t[:50], papers[k].get("basis") or "?", w) for k, t, w in bad))
    if unknown:
        parts.append("篇号 %s 不在这次调研里,已跳过。" % "、".join(unknown))
    return "\n".join(parts), res
