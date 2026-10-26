"""公共件:标题去重合并、奠基论文核对、并发评分。"""
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher

import llm
import sources
import stages

RECENT_YEARS = 2       # 最新 = 发表年份 ≥ 当前年 − 2
TOP_RELEVANT = 15
TOP_RECENT = 10
SCORE_BATCH = 1         # 一篇一批:互不干扰,质量略好(我们的基准:必读召回 34.8%→39.1%)


def _norm_title(t):
    return re.sub(r"[^0-9a-z一-鿿]+", "", t.lower())


def _tokens(t):
    """标题词序列(去词尾 s),用于识别 Network/Networks 这类细微差异的同一篇。"""
    return tuple(w[:-1] if len(w) > 3 and w.endswith("s") else w
                 for w in re.findall(r"[0-9a-z]+|[一-鿿]", t.lower()))


def _title_sim(ta, tb):
    """按词序比较(difflib);词袋比较会把词相同、顺序不同的两篇并成一篇。"""
    return SequenceMatcher(None, ta, tb, autojunk=False).ratio()


def _same_paper(a, b):
    ta, tb = a["_tok"], b["_tok"]
    if len(ta) < 4 or len(tb) < 4:
        return False
    if a.get("year") and b.get("year") and abs(a["year"] - b["year"]) > 2:
        return False
    return _title_sim(ta, tb) >= 0.9


def _merge(papers, start=1):
    """按标准化标题去重。记录命中的库和所在腿;保留字段更全的那条。"""
    by = {}
    for p in papers:
        key = _norm_title(p["title"])
        if not key:
            continue
        if key not in by:
            by[key] = dict(p, srcs={p["src"]}, legs={p["leg"]})
            continue
        cur = by[key]
        cur["srcs"].add(p["src"])
        cur["legs"].add(p["leg"])
        if len(p.get("abstract") or "") > len(cur.get("abstract") or ""):
            cur["abstract"] = p["abstract"]
        if p.get("doi") and not cur.get("doi"):
            cur["doi"] = p["doi"]
        if p.get("oa_id") and not cur.get("oa_id"):
            cur["oa_id"] = p["oa_id"]
        if (p.get("year") or 0) > (cur.get("year") or 0):
            cur["year"] = p["year"]
        cur["cites"] = max(cur.get("cites") or 0, p.get("cites") or 0)
    # 第二遍:标题词集合高度重合(Jaccard ≥ 0.8)且年份相近的并为一篇
    items = list(by.values())
    for p in items:
        p["_tok"] = _tokens(p["title"])
    kept = []
    for p in sorted(items, key=lambda x: -len(x.get("abstract") or "")):
        for q in kept:
            if _same_paper(p, q):
                q["srcs"] |= p["srcs"]
                q["legs"] |= p["legs"]
                q["cites"] = max(q.get("cites") or 0, p.get("cites") or 0)
                q["year"] = q.get("year") or p.get("year")
                if p.get("doi") and not q.get("doi"):
                    q["doi"] = p["doi"]
                if p.get("oa_id") and not q.get("oa_id"):
                    q["oa_id"] = p["oa_id"]
                break
        else:
            kept.append(p)
    out = []
    for i, p in enumerate(kept, start):
        p.pop("_tok", None)
        p["id"] = f"P{i:03d}"
        p["srcs"] = sorted(p["srcs"])
        p["legs"] = sorted(p["legs"])
        out.append(p)
    return out


def _surname(name):
    parts = re.findall(r"[a-zA-Z\u00c0-\u024f'-]+", name or "")
    return parts[-1].lower() if parts else ""


def _verify_landmarks(items, log):
    """大模型凭记忆给的奠基论文:标题常走样,可靠的是第一作者姓+年份。
    到 OpenAlex 在年份±3内按标题搜,要求前几位作者里有该姓、且标题与记忆有最低限度的词重合,才收;其余丢弃。"""
    found, dropped = [], []

    def one(it):
        rows = sources.oa_match(it["title"] or it["author"], it["year"])
        want = it["author"].lower().split()[-1] if it["author"] else ""
        tt = set(_tokens(it["title"]))
        best = None
        for r in rows:
            if not any(want == _surname(a) for a in r.get("authors", [])[:3]):
                continue
            if r.get("year") and abs(r["year"] - it["year"]) > 3:
                continue
            rt = set(_tokens(r["title"]))
            if tt and len(tt & rt) / len(tt | rt) < 0.2:
                continue
            if best is None or (r.get("cites") or 0) > (best.get("cites") or 0):
                best = r
        return best

    with ThreadPoolExecutor(max_workers=max(1, len(items))) as ex:
        futs = {ex.submit(one, it): it for it in items}
        for f in as_completed(futs):
            it = futs[f]
            try:
                best = f.result()
            except Exception as e:
                dropped.append(f"{it['author']} {it['year']}")
                log(f"  奠基论文核对失败: {type(e).__name__}")
                continue
            if best:
                best["_q"] = f"{it['author']} {it['year']}"
                found.append(best)
            else:
                dropped.append(f"{it['author']} {it['year']} {it['title'][:50]}")
    # 命中的一次批量取完整记录(摘要等),上面的核对只用了轻量字段
    if found:
        full = {r["oa_id"]: r for r in sources.oa_fetch_ids([b["oa_id"] for b in found])}
        out = []
        for b in found:
            r = full.get(b["oa_id"])
            if r:
                r["leg"], r["query"] = "landmark", b["_q"]
                out.append(r)
        found = out
    return found, dropped


def _score_all(need, exclude, papers, log, components=(), boundary=""):
    scored = {}
    batches = [papers[i:i + SCORE_BATCH] for i in range(0, len(papers), SCORE_BATCH)]
    with ThreadPoolExecutor(max_workers=min(llm.concurrency(), max(1, len(batches)))) as ex:
        futs = {ex.submit(stages.score, need, exclude, b, components, boundary): b for b in batches}
        for f in as_completed(futs):
            try:
                scored.update(f.result())
            except Exception as e:
                log(f"  评分批失败: {type(e).__name__}")
    for p in papers:
        s = scored.get(p["id"])
        if s:
            p.update(s)
            p["rec"] = stages.recommend(s["relevance"], s["scope"])
        else:
            p["rec"] = "skip"
            p["relevance"] = None
    return len(scored)
