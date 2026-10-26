"""展示篇的补取:作者全名、干净刊名、ISSN、OpenAlex type、卷期页与文献类型标识。

只对最终入选展示的那几十篇补取,不碰整个候选池。有 oa_id 的按编号批量取;没有的回 OpenAlex 按标题匹配
(小 select、12 并发)拿到编号再批量取。刊名取 OpenAlex 的 source 名(比谷歌学术 byline 干净);
原值是 byline 又抠不出干净刊名就留空。写回 items[].authors / items[].venue / items[].biblio
{volume,issue,first_page,last_page} / items[].doctype(GB/T 7714 文献类型标识,如 J、C、M、EB/OL),
以及供 cas 判因的 _issn / _type / _src_type。
"""
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import sources

TITLE_WORKERS = 12     # 小 select 标题搜索实测 12~16 并发零失败;默认信号量 6 会让 ~50 篇多花约 8 秒
BATCH = 50
SELECT = "id,doi,title,publication_year,type,authorships,primary_location,biblio"
MATCH_SELECT = "id,title"


def _norm(t):
    return re.sub(r"[^0-9a-z]", "", (t or "").lower())


def _looks_dirty(v):
    """谷歌学术 byline 不是刊名:形如「A B, C D … - 刊名, 2026 - 出版商」。"""
    s = (v or "").strip()
    if not s:
        return False
    if "…" in s or "..." in s:
        return True
    return " - " in s and bool(re.search(r"(?:19|20)\d{2}", s))


# GB/T 7714 文献类型标识(方括号内的部分),与 文献·字段/引文格式 的 citation.py 同一套约定。
_DOCTYPE = {
    "article": "J", "review": "J", "letter": "J", "editorial": "J", "erratum": "J",
    "book": "M", "book-chapter": "M", "chapter": "M",
    "conference": "C", "conference-paper": "C", "proceedings-article": "C",
    "dissertation": "D", "thesis": "D",
    "report": "R", "standard": "S", "patent": "P",
    "dataset": "DB/OL", "preprint": "EB/OL",
}
_BIBLIO_KEYS = ("volume", "issue", "first_page", "last_page")


def _biblio(w):
    b = w.get("biblio") or {}
    return {k: str(b.get(k) or "").strip() for k in _BIBLIO_KEYS}


def _doctype(wtype, src_type=""):
    t = (wtype or "").strip().lower()
    if t in _DOCTYPE:
        return _DOCTYPE[t]
    st = (src_type or "").strip().lower()
    return {"journal": "J", "conference": "C", "repository": "EB/OL", "ebook platform": "M"}.get(st, "J")


def _from_work(w):
    src = (w.get("primary_location") or {}).get("source") or {}
    au = [((a.get("author") or {}).get("display_name") or "").strip() for a in (w.get("authorships") or [])]
    return {"authors": [x for x in au if x], "venue": (src.get("display_name") or "").strip(),
            "issn": (src.get("issn_l") or "").strip(), "type": (w.get("type") or "").strip(),
            "src_type": (src.get("type") or "").strip(),
            "biblio": _biblio(w), "doctype": _doctype(w.get("type"), src.get("type"))}


def _by_ids(ids):
    out = {}
    ids = list(dict.fromkeys(i for i in ids if i))
    for i in range(0, len(ids), BATCH):
        js = sources._oa_json({"filter": "openalex:" + "|".join(ids[i:i + BATCH]),
                               "per-page": BATCH, "select": SELECT})
        for w in js.get("results", []):
            out[(w.get("id") or "").rsplit("/", 1)[-1]] = _from_work(w)
    return out


def _match_id(p):
    """按标题回到 OpenAlex 找编号;标题归一后含于彼此即算同一篇。"""
    tr = {"search": p.get("title") or "", "per-page": 3, "select": MATCH_SELECT}
    if p.get("year"):
        tr["filter"] = "publication_year:%d-%d" % (p["year"] - 3, p["year"] + 3)
    try:
        js = sources._oa_json(tr)
    except Exception:
        return None
    for w in js.get("results", []):
        a, b = _norm(w.get("title")), _norm(p.get("title"))
        if a and b and (a == b or a in b or b in a):
            return (w.get("id") or "").rsplit("/", 1)[-1] or None
    return None


_VENUE_WORDS = ("preprint", "proceedings", "conference", "symposium", "journal",
                "letters", "transactions", "arxiv", " on ", ".org", ".com")


def _looks_venue(seg):
    t = (seg or "").lower()
    return any(w in t for w in _VENUE_WORDS) or " on " in " %s " % t


_PARTICLES = ("van", "von", "de", "der", "den", "del", "della", "da", "di", "du",
              "la", "le", "dos", "das", "ter", "ten", "bin", "al", "el")


def _is_initial(t):
    return len(t) == 1 and t.isalpha() and t.isupper()


def _looks_name_word(t):
    """一个词像不像人名的一部分:全大写(缩写/姓)、首字母大写其余小写、带连字符各段同理。"""
    t = t.strip()
    if not t:
        return False
    if re.search(r"[^A-Za-z\u00c0-\u024f'\-.]", t):
        return False
    if t.lower() in _PARTICLES:
        return True                      # 介词小写是常态
    for x in re.split(r"[-'\u2019]", t):
        if not x:
            return False
        if not (x.isupper() or (x[0].isupper() and x[1:] == x[1:].lower())):
            return False
    return True


def _one_name(n):
    """单个作者名 → 「姓, 名」;不像人名返回空(宁可空,不许把标题当作者)。"""
    t = re.sub(r"\s+", " ", (n or "").strip())
    if not t or len(t) < 3 or re.search(r"\d", t) or _looks_venue(t):
        return ""
    if not t.isascii():
        return t if re.search(r"[\u4e00-\u9fff]", t) else ""   # 中文名原样;其它非 ASCII 不认
    if re.search(r"[:;?!]", t):         # 标题常带冒号/问号
        return ""
    raw = t.split()
    if len(raw) > 5:                    # 人名词数不会太多;标题会
        return ""
    toks = [x[:-1] if x.endswith(".") and len(x) > 1 else x for x in raw]
    toks = [x for x in toks if x]
    if len(toks) < 2:
        return ""
    for x in toks:                      # 每个词都要像人名词
        if x.lower() in _PARTICLES:
            continue
        if not _looks_name_word(x):
            return ""
    # 拆姓名。三种形态:
    #   1. 「Van de Panne」:全是介词 + 姓,且首词大写 —— 首词当名(缩写式),其余当姓
    #   2. 「P van der Smagt」:名缩写在前,介词连姓
    #   3. 「Tim Salzmann」/「HESTER T」:常规名在前;全大写首词且两词 → 姓在前
    if len(toks) == 2 and toks[0].isupper() and len(toks[0]) <= 3:
        return toks[1] + ", " + toks[0]          # 「TD Sanger」「Z Yu」:首词姓名缩写
    if len(toks) == 2 and toks[0].isupper() and len(toks[0]) >= 4:
        return toks[0] + ", " + toks[1]          # 「HESTER T」:全大写长词是姓
    if len(toks) >= 3 and toks[0][0].isupper() and toks[0].lower() in _PARTICLES and all(x.lower() in _PARTICLES for x in toks[1:-1]):
        return (" ".join([toks[0].lower()] + [x.lower() for x in toks[1:-1]] + [toks[-1]]) + ", " + toks[0])
    k = len(toks) - 1
    while k - 1 >= 1 and toks[k - 1].lower() in _PARTICLES:
        k -= 1
    given = toks[:k]
    if not given:
        return ""
    return " ".join(toks[k:]) + ", " + " ".join(given)


def _authors_from_byline(byline):
    """谷歌学术 byline「A B, C D… - 刊名, 2026 - 出版商」→ [「姓, 名」…];拆不出返回 []。"""
    s = re.sub(r"[\u00a0\u2000-\u200b\u202f\u3000]", " ", byline or "").strip()   # 谷歌学术偶有不间断空格
    if not s:
        return []
    head = s.split(" - ", 1)[0].strip()
    if not head or head.startswith("…") or head.startswith("..."):
        return []
    if _looks_venue(head):
        return []
    out = []
    for seg in head.split(","):
        seg = re.sub(r"…|\.{3,}", "", seg).strip()   # 每段都清省略号:末段常带「Zhang…」
        n = _one_name(seg)
        if n:
            out.append(n)
    return out


def attach(items, log=print):
    """就地补 authors/venue/_issn/_type/_src_type。返回补取统计。"""
    t0 = time.time()
    lack = [p for p in items if not p.get("oa_id")]
    old_sem = sources._OA_SEM
    matched = 0
    try:
        if lack:                                   # 只在补编号这一步放开并发,结束还原
            sources._OA_SEM = threading.BoundedSemaphore(TITLE_WORKERS)
        with ThreadPoolExecutor(max_workers=max(1, min(TITLE_WORKERS, len(lack)))) as ex:
            got = list(ex.map(_match_id, lack))
        for p, oid in zip(lack, got):
            if oid:
                p["oa_id"] = oid
                matched += 1
    finally:
        sources._OA_SEM = old_sem
    det = _by_ids([p.get("oa_id") for p in items])
    n_au = n_ven = n_bib = n_dt = 0
    for p in items:
        d = det.get(p.get("oa_id") or "") or {}
        byline = p.get("venue") or ""
        p["authors"] = d.get("authors") or []
        if not p["authors"]:                        # OpenAlex 没作者才从 byline 抠
            p["authors"] = _authors_from_byline(byline)
        ven = d.get("venue") or ""
        if not ven and not _looks_dirty(byline):
            ven = byline.strip()                   # 取不到刊名时,原值若不像 byline 就留着
        p["venue"] = ven
        p["_issn"] = d.get("issn") or ""
        p["_type"] = d.get("type") or ""
        p["_src_type"] = d.get("src_type") or ""
        p["biblio"] = d.get("biblio") or {k: "" for k in _BIBLIO_KEYS}
        p["doctype"] = d.get("doctype") or "J"
        n_au += 1 if p["authors"] else 0
        n_ven += 1 if (p["venue"] or p["_issn"]) else 0
        n_bib += 1 if (p["biblio"]["volume"] or p["biblio"]["first_page"]) else 0
        n_dt += 1 if p["doctype"] else 0
    st = {"n": len(items), "lack_oa": len(lack), "matched_title": matched,
          "authors": n_au, "venue": n_ven, "biblio": n_bib, "doctype": n_dt,
          "seconds": round(time.time() - t0, 1)}
    log("  [补取] 现有编号 %d 篇;按标题补编号 %d/%d;作者非空 %d/%d;刊名或 ISSN 可用 %d/%d;"
        "卷期页可用 %d/%d;类型标识可用 %d/%d;耗时 %.1fs"
        % (len(items) - len(lack), matched, len(lack), n_au, len(items), n_ven, len(items),
           n_bib, len(items), n_dt, len(items), st["seconds"]))
    return st