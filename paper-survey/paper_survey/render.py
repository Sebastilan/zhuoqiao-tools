"""成品页渲染:index.html(综述 + 文献)与 result.json;结果里不含任何 key。"""
import html
import json
import re
from pathlib import Path

CACHE = Path.cwd() / "surveys"   # 默认输出到当前目录下 surveys/<时间>/


def _e(s):
    return html.escape(str(s or ""))


# ======================= 瘦版成品页:编号 + 中英切换 + 综述式总结 =======================

def _bi(zh, en):
    return f'<span class="zh">{zh}</span><span class="en">{en}</span>'


def _para_html(text):
    """综述文本 → 段落;[n] 变成可点击的跳转链接;**词** 加粗。"""
    safe = _e(text)
    safe = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", safe)
    safe = re.sub(r"\[(\d+)\]", r'<a class="c" href="#ref-\1">[\1]</a>', safe)
    paras = [p.strip() for p in re.split(r"\n\s*\n", safe) if p.strip()]
    return "".join(f"<p>{p.replace(chr(10), '<br>')}</p>" for p in paras)


def _summary_block(sid, zh_title, en_title, texts):
    zh, en = texts.get("zh", ""), texts.get("en", "")
    if not (zh or en):
        return ""
    return (f'<section id="{sid}"><h2>{_bi(zh_title, en_title)} '
            f'<button class="local-lang" type="button" data-target="{sid}-lang">English</button></h2>'
            f'<div id="{sid}-lang" class="i18n" data-lang="zh">'
            f'<div class="zh sum">{_para_html(zh or en)}</div><div class="en sum">{_para_html(en or zh)}</div>'
            f'</div></section>')


_ZONE_EN = {"1区": "Zone 1", "2区": "Zone 2", "3区": "Zone 3", "4区": "Zone 4"}


def _cas_pair(cas):
    """中科院分区 → (中文, 英文)。命中给 区/TOP/IF;未命中说明原因,不留空。"""
    cas = cas or {}
    if cas.get("hit"):
        zn, jc, top, iv = cas.get("zone"), cas.get("jcr_zone"), cas.get("top"), cas.get("if")
        if zn:
            tzh = (" TOP" if top else "") + (f"（IF {iv}）" if iv is not None else "")
            ten = (" TOP" if top else "") + (f" (IF {iv})" if iv is not None else "")
            return "中科院 " + zn + tzh, "CAS " + _ZONE_EN.get(zn, zn) + ten
        if jc:
            return f"无中科院分区(仅 JCR {jc})", f"no CAS zone (JCR {jc} only)"
        return "无中科院分区", "no CAS zone"
    return cas.get("why") or "未查到分区", cas.get("why_en") or "partition not found"


def _authors_pair(au):
    au = [a for a in (au or []) if a]
    if not au:
        return "—", "—"
    head = ", ".join(au[:3])
    return head + (" 等" if len(au) > 3 else ""), head + (", et al." if len(au) > 3 else "")


# ---------------- GB/T 7714-2015 引用 ----------------

def _gbt_cjk(s):
    return bool(re.search(r"[\u4e00-\u9fff]", s or ""))


def _author_gbt(name):
    """全名 → 「姓全大写 名缩写」;中文名原样。"""
    s = re.sub(r"\s+", " ", (name or "").strip())
    if not s:
        return ""
    if _gbt_cjk(s):
        return s
    if "," in s:                                  # "Salzmann, Tim" 逗号前是姓
        last, rest = s.split(",", 1)
        toks = re.split(r"[\s.\-]+", rest.strip())
    else:
        toks = re.split(r"[\s.\-]+", s)
        if len(toks) >= 2 and 0 < len(toks[-1]) <= 2:   # "SALZMANN T":姓在倒数第二位
            last, toks = toks[-2], toks[:-2] + [toks[-1]]
        else:
            last, toks = toks[-1], toks[:-1]
    ini = [t[0].upper() for t in toks if t]
    out = last.upper()
    return out + (" " + " ".join(ini) if ini else "")


def _authors_gbt(au):
    """超过 3 人取前 3 人加 ", et al"。"""
    names = [_author_gbt(a) for a in (au or []) if a]
    if not names:
        return ""
    return ", ".join(names[:3]) + (", et al" if len(names) > 3 else "")


def _venue_clean(v):
    """刊名清洗:OpenAlex 偶有「A / Proceedings of the ... A」式的重复名,去省略号段与重复尾巴。
    只做去掉冗余,不改写刊名本身。"""
    s = re.sub(r"\s+", " ", (v or "").strip())
    if not s:
        return ""
    parts = [x.strip() for x in s.split("/") if x.strip()]
    if len(parts) > 1:
        clean = [x for x in parts if "..." not in x and "…" not in x]
        s = clean[0] if clean else parts[0]
    return re.sub(r"\.{3,}\s*|…\s*", "", s).strip()


_DOCTYPES = {"J": "J", "M": "M", "C": "C", "D": "D", "R": "R", "S": "S", "P": "P",
             "DB/OL": "DB/OL", "DB-OL": "DB/OL", "EB/OL": "EB/OL", "EB-OL": "EB/OL"}


def _doc_type(p):
    """文献类型标识(不带方括号)。enrich 的 doctype 为准,未知按 J;缺了才就地推断。"""
    dt = _DOCTYPES.get(re.sub(r"\s+", "", (p.get("doctype") or "").upper()))
    if dt:
        return dt
    t = (p.get("type") or p.get("_type") or "").lower()
    st = (p.get("src_type") or p.get("_src_type") or "").lower()
    venue = (p.get("venue") or "").strip()
    b = p.get("biblio") or {}
    if any(k in t or k in st for k in ("proceedings", "conference", "symposium")):
        return "C"
    if re.search(r"\b(proceedings|conference|symposium|workshop|congress)\b", venue, re.I):
        return "C"
    if not venue:
        return "EB/OL"
    if not str(b.get("volume") or "").strip() and (b.get("first_page") or b.get("last_page")):
        return "C"
    return "J"


_GBT_TITLE_SLOT = "\x00gbt-title\x00"


def _gbt7714(p, title_html=None):
    """按 GB/T 7714-2015 组装一条引用;缺的字段不写,不编造、不留空括号。

    返回纯文本。title_html 给了(已转义的 HTML 片段)时,题名位置留 _GBT_TITLE_SLOT
    哨兵,由 _gbt_cit_html 整体转义后再贴回;格式仍全由本函数出,不另写一套。
    """
    pre = (p.get("cite_gb") or "").strip()
    if pre:
        return pre
    au = _authors_gbt(p.get("authors"))
    raw_title = (p.get("title") or "").strip().rstrip(".")
    title = _GBT_TITLE_SLOT if (title_html is not None and raw_title) else raw_title
    year = str(p.get("year") or "").strip()
    venue = _venue_clean(p.get("venue"))
    b = p.get("biblio") or {}
    vol = str(b.get("volume") or "").strip()
    iss = str(b.get("issue") or "").strip()
    fp = str(b.get("first_page") or "").strip()
    lp = str(b.get("last_page") or "").strip()
    pages = (fp + ("-" + lp if lp and lp != fp else "")) if fp else lp
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", (p.get("doi") or "").strip())
    dt = _doc_type(p)
    s = (au + ". " if au else "") + (title or "") + "[" + dt + "]"
    if dt == "C":
        if venue:
            s += "//" + venue
        if year:
            s += ", " + year
        if pages:
            s += ": " + pages
        s += "."
    elif dt in ("EB/OL", "DB/OL"):
        s += "."
        if year:
            s += " " + year + "."
    elif dt != "J":                                # 专著/学位论文/报告/标准/专利
        s += "."
        if venue:
            s += " " + venue + ","
        if year:
            s += " " + year + "."
        elif venue:
            s = s[:-1] + "."
    else:
        s += "."
        if venue:
            s += " " + venue
            if year:
                s += ", " + year
            if vol:
                s += ", " + vol + ("(" + iss + ")" if iss else "")
            elif iss:
                s += ", (" + iss + ")"
            if pages:
                s += ": " + pages
        elif year:
            s += " " + year
        s += "."
    if doi:
        s += " DOI: " + doi + "."
    return s


def _gbt_html(p, key, bi=False):
    """引用行 + 复制按钮;不给英文切换的页面(旧版)就只写「复制」。"""
    s = _gbt7714(p)
    if not s:
        return ""
    label = _bi("复制", "Copy") if bi else "复制"
    return (f'<div class="gbt"><b>GB/T 7714-2015</b>'
            f'<button class="cp" type="button" data-copy="gbt-{_e(key)}">{label}</button>'
            f'<span class="gc" id="gbt-{_e(key)}">{_e(s)}</span></div>')


def _gbt_cit_html(p):
    """cit 行:作者. <a>题名</a>[J]. 刊名, 年, 卷(期): 起页-止页. DOI: xxx.
    标题即引用,点题名跳原文;引用格式全部由 _gbt7714 出,这里只贴链接。"""
    link = (p.get("url") or "").strip()
    raw = (p.get("title") or "").strip().rstrip(".")
    title = _e(raw)
    if raw and link.startswith("http"):
        title = f'<a href="{_e(link)}" target="_blank" rel="noopener">{title}</a>'
    s = _gbt7714(p, title_html=title if raw else None)
    if not s:
        return ""
    return '<div class="cit">' + _e(s).replace(_GBT_TITLE_SLOT, title) + "</div>"


def _ref_li(p):
    n = p["n"]
    tags = []
    if p.get("sec") == "more":
        tags.append(_bi("必读", "Key") if p.get("rec") == "must" else _bi("可能相关", "Related"))
    if p.get("tier") == "背景":
        tags.append(_bi("相关背景", "Background"))
    if p.get("kind") == "survey":
        tags.append(_bi("综述", "Survey"))
    tag_html = "".join(f'<span class="tag">{t}</span>' for t in tags)
    names = {"gs": ("谷歌学术", "Google Scholar"), "oa种子": ("OpenAlex 检索", "OpenAlex search"), "landmark": ("奠基论文", "landmark"),
             "backward": ("关键文献的参考文献", "cited by a key paper"), "forward": ("引用了关键文献", "cites a key paper"),
             "oa": ("OpenAlex", "OpenAlex"), "s2": ("Semantic Scholar", "Semantic Scholar")}
    routes = " / ".join(_bi(*names.get(r, (r, r))) for r in (p.get("routes") or p.get("srcs", [])))
    dc = (f" · {_bi('被 ' + str(p['doors_cnt']) + ' 篇关键文献共同引用', 'co-cited by ' + str(p['doors_cnt']) + ' key papers')}"
          if p.get("doors_cnt", 0) >= 2 else "")
    cas_zh, cas_en = _cas_pair(p.get("cas"))
    sm_parts = ([tag_html] if tag_html else []) + ([_bi(cas_zh, cas_en)] if p.get("cas") is not None else []) + [
                f'{_bi("被引", "cited")} {p.get("cites") or 0}',
                f'{_bi("相关度", "relevance")} {_e(p.get("relevance"))}{dc}']
    if routes:
        sm_parts.append(f'<span class="rt">{_bi("途经", "via")} {routes}</span>')
    sm_html = '<div class="sm">' + " · ".join(sm_parts) + "</div>"
    cit = _gbt_cit_html(p)
    num = f'<span class="num">[{n}]</span> '
    if cit:
        cit = cit.replace('<div class="cit">', '<div class="cit">' + num, 1)
    else:
        cit = f'<div class="cit">{num}{_e(p.get("title"))}</div>'
    ab_en = (p.get("abstract") or "").strip()
    ab_zh = (p.get("abstract_zh") or "").strip()
    only_gs = list(p.get("srcs", [])) == ["gs"]
    note_zh = note_en = ""
    if ab_en.startswith("[一句话总结]"):
        note_zh, note_en = "（仅一句话总结）", "(one-sentence TL;DR only)"
        ab_en = ab_en[len("[一句话总结]"):].strip()
    elif ab_en and only_gs and len(ab_en) < 400:
        note_zh, note_en = "（谷歌学术片段，非完整摘要）", "(Google Scholar snippet, not the full abstract)"
    opened = " open" if n <= 3 else ""
    if ab_en:
        ab_html = (f'<details class="ab"{opened}><summary>{_bi("摘要", "Abstract")}</summary>'
                   f'<button class="local-lang" type="button" data-target="ab-{n}">English</button>'
                   f'<div id="ab-{n}" class="i18n" data-lang="zh"><div class="zh"><b>摘要</b>{_e(note_zh)} {_e(ab_zh or ab_en)}</div>'
                   f'<div class="en"><b>Abstract</b>{_e(note_en)} {_e(ab_en)}</div></div></details>')
    else:
        ab_html = f'<div class="ab none">{_bi("（无摘要，仅标题；相关度依据标题判断）", "(no abstract; relevance judged from the title only)")}</div>'
    tz = _e(p.get("title_zh") or "")
    tz_html = f'<div class="tz zh">{tz}</div>' if tz else ""
    one = _e(p.get("one_line") or "")
    why_html = f'<div class="why"><b>{_bi("为什么相关：", "Why relevant: ")}</b>{one}</div>' if one else ""
    return (f'<li class="ref" id="ref-{n}" data-slot="ref-{n}">'
            f'{cit}{tz_html}{why_html}{sm_html}{ab_html}</li>')


_LEAN_CSS = """
:root { --bg:#fdfdfc; --fg:#1c1c1e; --mute:#6b6b70; --line:#dcdcd6; --accent:#1a56c4; --card:#f5f5f1; --hl:#fff3b8; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#17181a; --fg:#ececea; --mute:#a0a0a6; --line:#34363a; --accent:#7ab0ff; --card:#202226; --hl:#4a4320; color-scheme:dark; } }
:root[data-theme="dark"] { --bg:#17181a; --fg:#ececea; --mute:#a0a0a6; --line:#34363a; --accent:#7ab0ff; --card:#202226; --hl:#4a4320; color-scheme:dark; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:16px/1.75 -apple-system,"PingFang SC","Microsoft YaHei","Noto Sans CJK SC",sans-serif; }
body[data-lang="zh"] .en, body[data-lang="en"] .zh { display:none !important; }
.i18n[data-lang="zh"] .en { display:none !important; }
.i18n[data-lang="en"] .zh { display:none !important; }
.i18n[data-lang="en"] .en { display:block !important; }
.bar { position:sticky; top:0; z-index:5; background:var(--bg); border-bottom:1px solid var(--line); display:flex; gap:14px; align-items:center; padding:8px 16px; }
.bar .brand { font-weight:700; margin-right:auto; }
.bar a { color:var(--accent); text-decoration:none; font-size:14px; white-space:nowrap; }
.bar button, .local-lang { font:inherit; font-size:14px; padding:3px 12px; border:1px solid var(--accent); background:transparent; color:var(--accent); border-radius:14px; cursor:pointer; }
.back-summary[hidden] { display:none; }
.local-lang { font-size:12px; padding:1px 8px; vertical-align:middle; }
main { max-width:860px; margin:0 auto; padding:18px 16px 60px; }
h1 { font-size:21px; line-height:1.45; margin:6px 0 10px; }
h2 { font-size:18px; margin:30px 0 10px; padding-bottom:5px; border-bottom:1px solid var(--line); }
h3 { font-size:15.5px; margin:18px 0 6px; color:var(--mute); font-weight:600; }
.bd { margin:8px 0 0; padding:9px 12px; border-left:3px solid var(--accent); background:var(--card); font-size:14.5px; color:var(--fg); }
.sum p { margin:0 0 12px; text-align:justify; }
a.c { color:var(--accent); text-decoration:none; font-size:12.5px; vertical-align:baseline; padding:0 1px; }
a.c:hover { text-decoration:underline; }
ol.refs { list-style:none; margin:0; padding:0; }
li.ref { padding:13px 0; border-bottom:1px solid var(--line); scroll-margin-top:56px; }
li.ref:target { background:var(--hl); outline:6px solid var(--hl); }
.hd { display:flex; gap:6px; align-items:center; flex-wrap:wrap; }
.num { color:var(--accent); font-weight:700; font-variant-numeric:tabular-nums; }
.tag { font-size:12px; color:var(--accent); border:1px solid var(--accent); border-radius:4px; padding:0 5px; line-height:1.5; }
.t { font-weight:600; line-height:1.5; }
.t a { color:var(--fg); text-decoration:none; } .t a:hover { color:var(--accent); text-decoration:underline; }
.tz { color:var(--mute); font-size:14.5px; }
.m { color:var(--mute); font-size:13px; } .rt { color:var(--mute); }
.v { color:var(--mute); font-size:13.5px; margin-top:2px; }
.o { font-size:14.5px; margin-top:2px; }
.cit { font-size:14.5px; line-height:1.75; color:var(--fg); text-align:justify; }
.cit a { color:var(--fg); text-decoration:none; border-bottom:1px solid var(--line); }
.cit a:hover { color:var(--accent); border-bottom-color:var(--accent); }
.cit a.doi, .doi { color:var(--accent); word-break:break-all; }
.sm { color:var(--mute); font-size:12.5px; margin-top:4px; line-height:1.6; }
.why { font-size:14px; margin-top:4px; color:var(--fg); }
.why b { color:var(--mute); font-weight:600; }
.ab { font-size:14.5px; margin-top:6px; color:var(--fg); text-align:justify; } .ab b { margin-right:6px; }
.ab.none { color:var(--mute); }
details { margin-top:14px; } summary { cursor:pointer; color:var(--accent); font-weight:600; padding:6px 0; }
.gbt { font-size:13px; color:var(--mute); margin-top:5px; line-height:1.6; }
.gbt b { font-weight:600; margin-right:6px; }
.gbt .cp { font:inherit; font-size:12px; padding:0 7px; margin-right:6px; border:1px solid var(--line); background:transparent; color:var(--accent); border-radius:10px; cursor:pointer; }
.gbt .gc { color:var(--fg); user-select:text; }
.meta { color:var(--mute); font-size:12.5px; margin-top:30px; line-height:1.7; }
.meta a { color:var(--accent); text-decoration:none; }
@media (max-width:560px) { .bar { gap:8px; padding:8px 12px; } .bar nav a:nth-child(3) { display:none; } h1 { font-size:19px; } }
"""

_LEAN_JS = """
(function(){
  var b=document.body, btn=document.getElementById('lang');
  function set(l){ b.setAttribute('data-lang',l); document.documentElement.lang=(l==='zh'?'zh-CN':'en'); btn.textContent=(l==='zh'?'English':'中文'); }
  set('zh');
  btn.onclick=function(){ set(b.getAttribute('data-lang')==='zh'?'en':'zh'); };
  document.querySelectorAll('.local-lang').forEach(function(x){
    x.onclick=function(){
      var t=document.getElementById(x.getAttribute('data-target')); if(!t) return;
      var en=t.getAttribute('data-lang')==='zh'; t.setAttribute('data-lang',en?'en':'zh');
      x.textContent=en?'中文':'English';
    };
  });
  var back=document.getElementById('back-summary'), origin='';
  if(back) back.onclick=function(){ if(origin) location.hash=origin.slice(1); };
  function reveal(id){ var t=document.getElementById(id); if(!t) return; var d=t.closest('details'); if(d) d.open=true; }
  document.addEventListener('click',function(ev){ var a=ev.target.closest('a.c'); if(a){ origin=location.hash; reveal(a.getAttribute('href').slice(1)); if(back && origin) back.hidden=false; } });
  function fromHash(){ var h=location.hash; if(h.length>1){ reveal(h.slice(1)); var t=document.getElementById(h.slice(1)); if(t) t.scrollIntoView(); } }
  window.addEventListener('hashchange',fromHash); fromHash();
})();
"""


_CP_JS = """
(function(){
  document.querySelectorAll('button.cp').forEach(function(b){
    b.dataset.label = b.textContent;
    function flash(){ var o=b.dataset.label; b.textContent='\u2713'; setTimeout(function(){ b.textContent=o; },1200); }
    b.onclick = function(){
      var t = document.getElementById(b.getAttribute('data-copy')); if(!t) return;
      var s = t.textContent;
      function fallback(){
        var ta=document.createElement('textarea'); ta.value=s; document.body.appendChild(ta); ta.select();
        try{ document.execCommand('copy'); flash(); }catch(e){}
        ta.remove();
      }
      if(navigator.clipboard && navigator.clipboard.writeText){
        navigator.clipboard.writeText(s).then(flash, fallback);
      } else { fallback(); }
    };
  });
})();
"""


def render_lean(result, out_dir=None):
    out = Path(out_dir) if out_dir else CACHE / result["generated_at"].replace(":", "-")
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    items = result["items"]
    by_sec = {"relevant": [], "recent": [], "more": []}
    for p in items:
        by_sec[p["sec"]].append(p)
    ol = lambda L: '<ol class="refs">' + "".join(_ref_li(p) for p in L) + "</ol>"
    sums = result["summary"]
    id2n = {p["id"]: p["n"] for p in items}
    doors = result.get("doors") or []
    door_html = "；".join((f'<a class="c" href="#ref-{id2n[d["id"]]}">[{id2n[d["id"]]}]</a> ' if d["id"] in id2n else "") + _e(d["title"][:70]) for d in doors)
    st = result["stats"]
    cov = int(result.get("coverage", 0) * 100)
    parts = []
    if doors:
        parts.append(f'<div>{_bi("起点（关键文献）", "Starting points")}：{door_html}。'
                     f'{_bi(f"结果中约 {cov}% 被两条以上独立途径找到（越高说明覆盖越稳）。", f"About {cov}% of the listed papers were found by two or more independent routes (higher = more stable coverage).")}</div>')
    parts.append(f'<div>{_bi(f"检索到并评分 {st["merged"]} 篇，必读级 {st["must"]} 篇。", f"{st["merged"]} papers retrieved and scored; {st["must"]} judged key.")} '
                 f'{_bi("摘要级判断：只依据标题和摘要；中文由模型翻译，仅供参考。", "Abstract-level judgment only; Chinese text is machine-translated.")}</div>')
    parts.append(f'<div>{_e(result["generated_at"])}</div>')
    meta = '<div class="meta">' + "".join(parts) + "</div>"
    more_n = len(by_sec["more"])
    page = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>快速调研</title>
<style>{_LEAN_CSS}</style></head>
<body data-lang="zh">
<div class="bar"><span class="brand">{_bi("快速调研", "Quick Survey")}</span>
<nav><a href="#summary">{_bi("总结", "Summary")}</a> <a href="#recent-sum">{_bi("近两年", "Recent")}</a> <a href="#refs">{_bi("文献", "References")}</a></nav>
<button id="back-summary" class="back-summary" type="button" hidden>{_bi("返回综述", "Back to review")}</button>
<button id="lang" type="button">English</button></div>
<main>
<h1>{_e(result['need'])}</h1>
{('<section class="setup"><h2>' + _bi('调研需求与检索方案', 'Request and search plan') + '</h2>'
  '<div class="bd"><b>' + _bi('用户调研需求理解：', 'Understanding of the user’s research request: ') + '</b>' + _e(result['boundary']) + '</div>'
  '<div class="bd"><b>' + _bi('最终搜索词：', 'Final search queries: ') + '</b>' + _e(' | '.join(result['queries'])) + '</div>'
  '<div class="bd"><b>' + _bi('检索与筛选方法：', 'Search and screening method: ') + '</b>'
  + _bi('先用 Google Scholar 与 OpenAlex 获取种子文献，并核对奠基论文；再从高相关“关键文献”向前取参考文献、向后取近两年施引文献。OpenAlex 参考文献稀疏或论文缺摘要时，用 Semantic Scholar（S2）兜底补充。最后合并去重并按标题和摘要评分。页面是摘要级调研，不下载全文。',
        'We first collect seed papers from Google Scholar and OpenAlex and verify landmark papers. We then expand backward through references and forward through recent citing papers of high-relevance key papers. Semantic Scholar (S2) is used as a fallback when OpenAlex references are sparse or an abstract is missing. We then deduplicate and score by title and abstract. This is an abstract-level survey; no full texts are downloaded.') + '</div></section>') if result.get('boundary') else ''}
{_summary_block("summary", "总结", "Summary", sums.get("overall", {}))}
{_summary_block("recent-sum", "近两年新进展", "Recent progress (last two years)", sums.get("recent", {}))}
<section id="refs"><h2>{_bi("参考文献(GB/T 7714-2015)", "References (GB/T 7714-2015)")}</h2>
<h3>{_bi("最相关文献", "Most relevant papers")}</h3>{ol(by_sec["relevant"]) if by_sec["relevant"] else "<p>—</p>"}
<h3>{_bi("近两年新进展文献", "Recent papers")}</h3>{ol(by_sec["recent"]) if by_sec["recent"] else '<p>' + _bi("窗口内没有达到必读级的文献。", "No paper in the window reached the key level.") + '</p>'}
{('<details><summary>' + _bi(f"更多相关文献（{more_n} 篇）", f"More related papers ({more_n})") + '</summary>' + ol(by_sec["more"]) + '</details>') if more_n else ''}
</section>
{meta}
</main>
<script>{_LEAN_JS}{_CP_JS}</script>
</body></html>"""
    (out / "index.html").write_text(page, encoding="utf-8")
    return out / "index.html"
