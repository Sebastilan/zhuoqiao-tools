"""OpenAlex 与 Semantic Scholar(S2)检索。各返回统一结构的 dict 列表;两家的 key 都可选。

错误信息只含 HTTP 状态码,不含 URL 和 key,避免进日志。
"""
import json
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import config


def openalex_keys():
    return config.get_list("OPENALEX_API_KEY")


def s2_key():
    return config.get("S2_API_KEY")


def _s2_headers(extra=None):
    h = dict(extra or {})
    if s2_key():
        h["x-api-key"] = s2_key()
    return h


def _oa_polite(params):
    """OpenAlex 建议带 mailto 进"礼貌池";没配就不带。"""
    m = config.get("OPENALEX_MAILTO")
    if m:
        params["mailto"] = m
    return params
from pool import KeyPool

OA_WORKS = "https://api.openalex.org/works"
S2_SEARCH = "https://api.semanticscholar.org/graph/v1/paper/search"


class SourceError(Exception):
    pass


def _err_code(e):
    return getattr(e, "code", None)


def _err_text(e):
    try:
        return e.read().decode("utf-8", "ignore")[:300]
    except Exception:
        return ""


_OA_SEM = threading.BoundedSemaphore(6)   # 小请求 8 并发实测零失败;大响应(100 条带摘要)高并发会失败
_pools = {}
_pool_lock = threading.Lock()


def _pool(name, keys_fn):
    with _pool_lock:
        if name not in _pools:
            _pools[name] = KeyPool(keys_fn())
        return _pools[name]


# ---------- OpenAlex ----------

def openalex(query, per_page=100, by_cites=False, years=None, page=1, with_total=False, timeout=30, retries=3):
    """by_cites=False:全文相关度前 per_page 条;True:标题摘要里命中的、按被引降序前 per_page 条(召回经典)。"""
    pool = _pool("openalex", openalex_keys)
    last = "无"
    for attempt in range(retries + 1):
        key = pool.next()
        if key is None:
            # 没配 key 或全部用完,退回匿名一次
            key = ""
        params = {"per-page": per_page, "page": page,
                  "select": "id,title,publication_year,cited_by_count,abstract_inverted_index,doi,primary_location,authorships"}
        flt = []
        if by_cites:
            flt.append("title_and_abstract.search:" + query)
            params["sort"] = "cited_by_count:desc"
        else:
            params["search"] = query
        if years:
            flt.append(f"publication_year:{years[0]}-{years[1]}")
        if flt:
            params["filter"] = ",".join(flt)
        if key:
            params["api_key"] = key
        url = OA_WORKS + "?" + urllib.parse.urlencode(_oa_polite(params))
        try:
            with _OA_SEM, urllib.request.urlopen(url, timeout=timeout) as r:
                js = json.loads(r.read())
            rows = [_norm_oa(w) for w in js.get("results", [])]
            return (rows, (js.get("meta") or {}).get("count") or 0) if with_total else rows
        except urllib.error.HTTPError as e:
            code = _err_code(e)
            text = _err_text(e)
            if key and code in (402, 403, 429) and "budget" in text.lower():
                pool.kill(key)
                last = f"HTTP {code}(当日额度用完,key 已踢出)"
                continue
            if code == 429:
                time.sleep(min(4.0, 0.5 * (2 ** attempt)))
                last = "HTTP 429"
                continue
            last = f"HTTP {code}"
            time.sleep(0.5)
        except Exception as e:
            last = f"网络 {type(e).__name__}"
            time.sleep(0.5)
    raise SourceError(f"openalex 失败: {last}")


def openalex_deep(query, by_cites=False, max_pages=3):
    """翻到最多 max_pages 页(每页 100):先取第 1 页拿到总命中数,有需要再并发取后面几页。稳定可重复。"""
    from concurrent.futures import ThreadPoolExecutor
    rows, total = openalex(query, by_cites=by_cites, with_total=True)
    need = min(max_pages, -(-total // 100))
    if need <= 1:
        return rows
    with ThreadPoolExecutor(max_workers=need - 1) as ex:
        for part in ex.map(lambda pg: openalex(query, by_cites=by_cites, page=pg), range(2, need + 1)):
            rows += part
    return rows


def openalex_title(title, year=None, timeout=30):
    """按标题找论文(有年份就限 ±3 年),返回前 10 条候选;由调用方用作者+年份判断是否真是同一篇。"""
    return openalex(title, per_page=10, years=(year - 3, year + 3) if year else None, timeout=timeout)


def _oa_abstract(inv):
    if not inv:
        return ""
    pos = {}
    for word, idxs in inv.items():
        for i in idxs:
            pos[i] = word
    return " ".join(pos[i] for i in sorted(pos))


def _norm_oa(w):
    loc = (w.get("primary_location") or {}).get("source") or {}
    return {
        "src": "oa",
        "oa_id": (w.get("id") or "").rsplit("/", 1)[-1],
        "title": (w.get("title") or "").strip(),
        "year": w.get("publication_year"),
        "cites": w.get("cited_by_count") or 0,
        "abstract": _oa_abstract(w.get("abstract_inverted_index")),
        "doi": (w.get("doi") or "").replace("https://doi.org/", "") or None,
        "venue": loc.get("display_name") or "",
        "authors": [((a.get("author") or {}).get("display_name") or "") for a in (w.get("authorships") or [])[:4]],
        "url": w.get("doi") or w.get("id") or "",
    }


# ---------- Semantic Scholar ----------

_s2_lock = threading.Lock()
_s2_last = [0.0]
S2_INTERVAL = 1.1  # 秒;S2 key 限流约 1 请求/秒


def _s2_wait():
    with _s2_lock:
        gap = S2_INTERVAL - (time.time() - _s2_last[0])
        if gap > 0:
            time.sleep(gap)
        _s2_last[0] = time.time()


def s2(query, limit=100, offset=0, with_total=False, timeout=30, retries=8):
    params = {"query": query, "limit": limit, "offset": offset,
              "fields": "title,year,citationCount,abstract,externalIds,venue,url"}
    url = S2_SEARCH + "?" + urllib.parse.urlencode(params)
    last = "无"
    for attempt in range(retries + 1):
        _s2_wait()
        req = urllib.request.Request(url, headers=_s2_headers())
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                js = json.loads(r.read())
            rows = [_norm_s2(p) for p in js.get("data", [])]
            return (rows, js.get("total") or 0) if with_total else rows
        except urllib.error.HTTPError as e:
            code = _err_code(e)
            if code == 429:
                time.sleep(min(6.0, 1.0 * (2 ** attempt)) + random.random())
                last = "HTTP 429"
                continue
            last = f"HTTP {code}"
            break
        except Exception as e:
            last = f"网络 {type(e).__name__}"
            time.sleep(0.5)
    raise SourceError(f"s2 失败: {last}")


def s2_deep(query, max_pages=3):
    """S2 搜索最多翻 max_pages 页;总命中数不够就不请求后面的页(超出范围会 400)。S2 限速约 1 次/秒,依次取。"""
    rows, total = s2(query, with_total=True)
    for pg in range(1, min(max_pages, -(-total // 100))):
        rows += s2(query, offset=pg * 100)
    return rows


def _norm_s2(p):
    ext = p.get("externalIds") or {}
    return {
        "src": "s2",
        "title": (p.get("title") or "").strip(),
        "year": p.get("year"),
        "cites": p.get("citationCount") or 0,
        "abstract": (p.get("abstract") or "").strip(),
        "doi": ext.get("DOI"),
        "venue": p.get("venue") or "",
        "url": p.get("url") or "",
    }


# ---------- 滚雪球用的 OpenAlex 查询 ----------

OA_SELECT = ("id,title,publication_year,cited_by_count,abstract_inverted_index,doi,"
             "primary_location")   # 不取 authorships:响应缩小到约 40%


def _oa_json(params, timeout=40, retries=3):
    pool = _pool("openalex", openalex_keys)
    last = "无"
    for attempt in range(retries + 1):
        key = pool.next() or ""
        q = dict(params)
        if key:
            q["api_key"] = key
        url = OA_WORKS + "?" + urllib.parse.urlencode(_oa_polite(q))
        try:
            with _OA_SEM, urllib.request.urlopen(url, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            code = _err_code(e)
            if key and code in (402, 403, 429) and "budget" in _err_text(e).lower():
                pool.kill(key)
                last = f"HTTP {code}(额度用完,key 已踢出)"
                continue
            last = f"HTTP {code}"
        except Exception as e:
            last = f"网络 {type(e).__name__}"
        time.sleep(0.6 * (2 ** attempt))
    raise SourceError(f"openalex 失败: {last}")


def oa_seed(query, by_cites=False, n=25):
    """稳定种子:主搜索词的相关度前 n(默认)或标题摘要命中按被引前 n。"""
    p = {"per-page": n, "select": OA_SELECT}
    if by_cites:
        p["filter"] = "title_and_abstract.search:" + query
        p["sort"] = "cited_by_count:desc"
    else:
        p["search"] = query
    return [_norm_oa(w) for w in _oa_json(p).get("results", [])]


def oa_refs_of(ids):
    """{门编号: [参考文献编号...]}。一次请求。"""
    js = _oa_json({"filter": "openalex:" + "|".join(ids), "per-page": 50,
                   "select": "id,referenced_works"})
    return {(w["id"]).rsplit("/", 1)[-1]: [x.rsplit("/", 1)[-1] for x in (w.get("referenced_works") or [])]
            for w in js.get("results", [])}


def oa_cited_by(door_id, year_from, n=100):
    """谁在 year_from 年及以后引用了这篇门,按被引降序前 n。"""
    p = {"filter": f"cites:{door_id},publication_year:{year_from}-{year_from + 5}",
         "sort": "cited_by_count:desc", "per-page": n, "select": OA_SELECT}
    return [_norm_oa(w) for w in _oa_json(p).get("results", [])]


def oa_fetch_ids(ids):
    """按编号批量取详情(每批 50,OpenAlex 并发上限 3 由信号量保证)。"""
    from concurrent.futures import ThreadPoolExecutor
    ids = list(dict.fromkeys(ids))
    batches = [ids[i:i + 50] for i in range(0, len(ids), 50)]

    def one(b):
        js = _oa_json({"filter": "openalex:" + "|".join(b), "per-page": 50, "select": OA_SELECT})
        return [_norm_oa(w) for w in js.get("results", [])]

    out = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for part in ex.map(one, batches):
            out += part
    return out


S2_FILL_DEADLINE = 12   # 秒:补文本是锦上添花,S2 限流时不能拖慢整条流程,超时就用标题评分


def s2_fill_text(papers):
    """没有摘要的,有 DOI 的向 S2 批量要一句话总结(tldr)/摘要,写回 abstract。返回补到几篇。总共最多花 S2_FILL_DEADLINE 秒。"""
    todo = [p for p in papers if not p.get("abstract") and p.get("doi")]
    filled = 0
    t_end = time.time() + S2_FILL_DEADLINE
    for i in range(0, len(todo), 400):
        part = todo[i:i + 400]
        body = json.dumps({"ids": ["DOI:" + p["doi"] for p in part]}).encode()
        res = []
        for attempt in range(6):
            if time.time() > t_end:
                break
            _s2_wait()
            req = urllib.request.Request(
                "https://api.semanticscholar.org/graph/v1/paper/batch?fields=abstract,tldr",
                data=body, method="POST",
                headers=_s2_headers({"Content-Type": "application/json"}))
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    res = json.loads(r.read())
                break
            except urllib.error.HTTPError as e:
                if _err_code(e) == 429:
                    time.sleep(2 + attempt)
                    continue
                break
            except Exception:
                time.sleep(1)
        for p, x in zip(part, res):
            if not x:
                continue
            if x.get("abstract"):
                p["abstract"], p["text_level"] = x["abstract"], "abstract"
                filled += 1
            elif (x.get("tldr") or {}).get("text"):
                p["abstract"], p["text_level"] = "[一句话总结] " + x["tldr"]["text"], "tldr"
                filled += 1
    return filled


def oa_match(title, year=None, n=5):
    """轻量匹配(奠基论文核对用):只取编号、标题、年份、被引、DOI、作者,不取摘要,响应很小。
    有年份就限 ±3 年。返回 [{oa_id,title,year,cites,doi,authors}]。"""
    p = {"search": title, "per-page": n,
         "select": "id,title,publication_year,cited_by_count,doi,authorships"}
    if year:
        p["filter"] = f"publication_year:{year - 3}-{year + 3}"
    out = []
    for w in _oa_json(p).get("results", []):
        out.append({"oa_id": (w.get("id") or "").rsplit("/", 1)[-1], "title": (w.get("title") or "").strip(),
                    "year": w.get("publication_year"), "cites": w.get("cited_by_count") or 0,
                    "doi": (w.get("doi") or "").replace("https://doi.org/", "") or None,
                    "authors": [((a.get("author") or {}).get("display_name") or "") for a in (w.get("authorships") or [])[:4]]})
    return out


def s2_references(doi, limit=150, deadline=12):
    """某篇论文的参考文献(含标题、年份、被引、摘要、DOI),用于 OpenAlex 缺参考文献时兜底。失败返回空列表。"""
    t_end = time.time() + deadline
    url = ("https://api.semanticscholar.org/graph/v1/paper/DOI:" + urllib.parse.quote(doi, safe="/") +
           "/references?" + urllib.parse.urlencode({
               "fields": "title,year,citationCount,abstract,externalIds,venue,url", "limit": limit}))
    for attempt in range(5):
        if time.time() > t_end:
            break
        _s2_wait()
        req = urllib.request.Request(url, headers=_s2_headers())
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                js = json.loads(r.read())
            return [_norm_s2(x["citedPaper"]) for x in js.get("data", []) if x.get("citedPaper") and x["citedPaper"].get("title")]
        except urllib.error.HTTPError as e:
            if _err_code(e) == 429:
                time.sleep(1.5 + attempt)
                continue
            return []
        except Exception:
            time.sleep(0.5)
    return []
