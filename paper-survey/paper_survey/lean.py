"""快速调研·瘦版(人的做法):种子 → 评分 → 选"门" → 滚雪球一轮 → 评分 → 排序。

种子:谷歌学术(经 Serper,可选;不限年份+近两年)为主,OpenAlex 小规模稳定种子(相关度/被引各前 25),
      可选:大模型提名并核对过的奠基论文。
门:种子里高分的核心论文,综述优先,需有 OpenAlex 编号。
滚雪球:每个门往前取参考文献(合并去重后批量取详情)、往后取近两年施引;缺摘要用 S2 一句话总结兜底。
不下载任何全文。
"""
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from datetime import datetime

import sources
import stages
import scholar
from core import (RECENT_YEARS, TOP_RECENT, TOP_RELEVANT, _merge, _norm_title,
                  _score_all, _verify_landmarks)
from render import render_lean
import report

N_DOORS = 8           # 往前(参考文献)用几个门:实测 4→47.8%、6→50%、8→58.7% 全池召回
FWD_DOORS = 4         # 往后(近两年施引)只用前几个门:施引每门要一次大请求,多了只拖时间
BACK_CAP = 300        # 参考文献合并去重后最多取详情的篇数(按被几个门共同引用优先)
FORWARD_N = 60        # 每个门取多少篇近两年施引
SPARSE_REFS = 10      # OpenAlex 里参考文献少于这个数的门,改用 S2 兜底
SEED_DEADLINE = 35    # 种子检索最多等多少秒,超时用已回来的
LM_GRACE = 8          # 只剩奠基论文核对没回来时,最多再等几秒(实测它让召回高出约 12 个百分点,值得等)
SNOWBALL_DEADLINE = 40  # 滚雪球取数最多等多少秒


def _routes(p):
    r = set()
    if "gs" in p.get("srcs", []):
        r.add("gs")
    if "oa" in p.get("srcs", []) and set(p.get("legs", [])) & {"classic", "cited"}:
        r.add("oa种子")
    for k in ("landmark", "backward", "forward"):
        if k in p.get("legs", []):
            r.add(k)
    return sorted(r)


def pick_doors(scored, n=N_DOORS, ban_dois=(), log=print):
    """选门。候选=有 OpenAlex 编号的高分核心论文(前 12)。
    打分=它的参考文献里含多少篇"已确认相关的种子"(重合越多越对题)+综述加 1;再看相关度、被引。
    返回 (门列表, {门编号:参考文献编号列表}),参考文献后面滚雪球直接用,不重复请求。"""
    ban = {d.lower() for d in ban_dois}
    pool = [p for p in scored if (p.get("doi") or "").lower() not in ban and p.get("oa_id")]
    cand = [p for p in pool if p.get("scope") == "core" and (p.get("relevance") or 0) >= 4]
    if len(cand) < 2:   # 太少就放宽到相关度≥3
        cand = [p for p in pool if (p.get("relevance") or 0) >= 3]
    cand.sort(key=lambda p: (p.get("relevance") or 0, p.get("cites") or 0), reverse=True)
    cand = cand[:12]
    # 起点不够的新兴领域:相关度≥3 的综述参考文献覆盖整片邻域,也纳入候选(靠"重合种子数"打分,不对题的上不来)
    have = {p["id"] for p in cand}
    extra = [p for p in pool if p["id"] not in have and p.get("kind") == "survey" and (p.get("relevance") or 0) >= 3]
    extra.sort(key=lambda p: (p.get("relevance") or 0, p.get("cites") or 0), reverse=True)
    cand += extra[:6]
    if not cand:
        return [], {}
    refs = sources.oa_refs_of([p["oa_id"] for p in cand])
    strong = {p["oa_id"] for p in pool if p.get("scope") == "core" and (p.get("relevance") or 0) >= 4}
    for p in cand:
        r = set(refs.get(p["oa_id"], []))
        p["door_score"] = len(r & strong) + (1 if p.get("kind") == "survey" else 0)
        p["ref_n"] = len(r)
    cand.sort(key=lambda p: (p["door_score"], p.get("relevance") or 0, p.get("cites") or 0), reverse=True)
    # OpenAlex 里新论文常缺参考文献(ref_n 很小):缺的靠 S2 兜底,所以 ref_n=0 的也留着,只要有 DOI
    doors = [p for p in cand if p["ref_n"] > 0 or p.get("doi")][:n]
    log("候选门打分(重合种子数,参考文献数): " + "; ".join(f"{p['door_score']}/{p['ref_n']} {p['title'][:28]}" for p in cand[:8]))
    return doors, refs


def snowball(doors, refs, seeds, now, log, fwd_doors=FWD_DOORS):
    """返回(新增论文列表, 统计)。新增已与种子去重;每篇带 doors_cnt(被几个门共同引用/引用了几个门)。"""
    door_ids = [d["oa_id"] for d in doors]
    seed_oa = {p["oa_id"] for p in seeds if p.get("oa_id")}
    seed_title = {_norm_title(p["title"]): p for p in seeds}
    t0 = time.time()
    cnt = Counter(i for d in door_ids for i in set(refs.get(d, [])))
    back_ids = [i for i, _ in cnt.most_common() if i not in seed_oa][:BACK_CAP]
    ex = ThreadPoolExecutor(max_workers=len(doors) + 4)
    s2n, s2cnt = 0, Counter()
    s2_doors = [d for d in doors if len(refs.get(d["oa_id"], [])) < SPARSE_REFS and d.get("doi")]
    try:
        f_s2 = {d["oa_id"]: ex.submit(sources.s2_references, d["doi"]) for d in s2_doors}
        f_back = ex.submit(sources.oa_fetch_ids, back_ids)
        f_fwd = {d["oa_id"]: ex.submit(sources.oa_cited_by, d["oa_id"], now - RECENT_YEARS, FORWARD_N) for d in doors[:fwd_doors]}
        dl = time.time() + SNOWBALL_DEADLINE
        left = lambda: max(0.1, dl - time.time())
        log(f"  [滚雪球] 参考文献编号 {time.time() - t0:.1f}s")
        try:
            back = f_back.result(timeout=left())
            log(f"  [滚雪球] 参考文献详情取回 {time.time() - t0:.1f}s ({len(back)} 篇)")
        except Exception as e:
            log(f"  参考文献详情未取全({type(e).__name__}),本轮不用")
            back = []
        fwd, fcnt = [], Counter()
        for did, f in f_fwd.items():
            try:
                rows = f.result(timeout=left())
                log(f"  [滚雪球] 施引取回 {time.time() - t0:.1f}s ({len(rows)} 篇)")
            except Exception as e:
                log(f"  施引获取失败/超时: {type(e).__name__}")
                continue
            for r in rows:
                fcnt[r["oa_id"]] += 1
            fwd += rows
        for did, f in f_s2.items():   # OpenAlex 缺参考文献的门,S2 兜底的结果(同样受总超时约束)
            try:
                rows = f.result(timeout=left())
            except Exception as e:
                log(f"  S2 参考文献兜底失败/超时: {type(e).__name__}")
                continue
            for r in rows:
                s2cnt[_norm_title(r["title"])] += 1
            back += rows
            s2n += len(rows)
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    for r in back:
        r["leg"], r["query"] = "backward", "门的参考文献"
    for r in fwd:
        r["leg"], r["query"] = "forward", "近两年施引门"
    stats = {"门数": len(doors), "参考文献去重后": len(cnt), "取详情": len(back), "施引取回": len(fwd), "S2兜底参考文献": s2n,
             "耗时s": round(time.time() - t0, 1)}
    merged = _merge(back + fwd, start=len(seeds) + 1)
    new = []
    for e in merged:
        dc = max(cnt.get(e.get("oa_id"), 0), fcnt.get(e.get("oa_id"), 0), s2cnt.get(_norm_title(e["title"]), 0))
        e["doors_cnt"] = dc
        hit = None
        if e.get("oa_id") in seed_oa:
            hit = next((p for p in seeds if p.get("oa_id") == e["oa_id"]), None)
        elif _norm_title(e["title"]) in seed_title:
            hit = seed_title[_norm_title(e["title"])]
        if hit:   # 种子里已有:只补路径和共同引用数
            hit["legs"] = sorted(set(hit.get("legs", [])) | set(e["legs"]))
            hit["doors_cnt"] = max(hit.get("doors_cnt", 0), dc)
        else:
            new.append(e)
    # 续编号保持连续
    for i, e in enumerate(new, len(seeds) + 1):
        e["id"] = f"P{i:03d}"
    return new, stats


MIN_RELEVANT = 8   # 最相关栏至少这么多条;必读级不够时用"相关度≥3的可能相关"补足并标为背景


def rank(scored, now):
    """先选近两年(宁缺勿滥:只要必读级),最相关栏放其余的,两栏互不重复。
    新兴领域必读级本来就少、还可能全是近两年的:最相关栏不够 MIN_RELEVANT 条时,用相关度≥3 的可能相关补足(标 tier=背景)。"""
    key = lambda p: (p.get("relevance") or 0, p.get("doors_cnt", 0), p.get("cites") or 0)
    must = sorted([p for p in scored if p.get("rec") == "must"], key=key, reverse=True)
    age = lambda p: max(1, now - (p.get("year") or now) + 1)
    pool = [p for p in must if (p.get("year") or 0) >= now - RECENT_YEARS]
    pool.sort(key=lambda p: (p.get("relevance") or 0, p.get("doors_cnt", 0), (p.get("cites") or 0) / age(p)), reverse=True)
    recent = pool[:TOP_RECENT]
    rec_ids = {p["id"] for p in recent}
    relevant = [p for p in must if p["id"] not in rec_ids][:TOP_RELEVANT]
    if len(relevant) < MIN_RELEVANT:
        chosen = {p["id"] for p in relevant} | rec_ids
        extra = sorted([p for p in scored if p.get("rec") == "maybe" and (p.get("relevance") or 0) >= 3 and p["id"] not in chosen],
                       key=key, reverse=True)[:TOP_RELEVANT - len(relevant)]
        for p in extra:
            p["tier"] = "背景"
        relevant += extra
    return must, relevant, recent


def run(need, draws=6, oa_seed_n=25, use_landmarks=True, use_components=False,
        n_doors=N_DOORS, fwd_doors=FWD_DOORS, ban_dois=(), plan_override=None, out_dir=None, log=print):
    t0 = time.time()
    now = datetime.now().year
    ph = {}

    plan = plan_override or stages.plan(need)   # plan_override 仅供评测:固定搜索词,隔离大模型每次给词不同带来的方差
    queries = plan["queries"][:3] + (plan["components"] if use_components else [])
    ph["理解"] = round(time.time() - t0, 1)
    log(f"边界: {plan['boundary']}")
    log(f"搜索词({len(queries)}): " + " | ".join(queries))

    # ---- 种子:谷歌 + OpenAlex 小种子 + 奠基论文,同时发出 ----
    t1 = time.time()
    papers, ok, fail = [], {}, {}
    ex = ThreadPoolExecutor(max_workers=16)
    jobs = {}
    if scholar.enabled() and draws > 0:
        jobs[ex.submit(scholar.search, queries, now - RECENT_YEARS, draws, SEED_DEADLINE)] = ("gs", "tool")
    else:
        log("未配置 SERPER_API_KEY:跳过谷歌学术,只用 OpenAlex 种子(召回会低一些)")
    if use_landmarks and plan["landmarks"]:   # 先提交,先占 OpenAlex 名额
        jobs[ex.submit(_verify_landmarks, plan["landmarks"], log)] = ("lm", "landmark")
    for q in queries[:3]:
        jobs[ex.submit(sources.oa_seed, q, False, oa_seed_n)] = ("oa", "classic", q)
        jobs[ex.submit(sources.oa_seed, q, True, oa_seed_n)] = ("oa", "cited", q)

    def take(f):
        tag = jobs[f]
        log(f"  [t+{time.time() - t0:5.1f}s] 种子任务完成 {'/'.join(map(str, tag[:3]))}")
        try:
            res = f.result()
        except Exception as e:
            k = "/".join(tag[:2])
            fail[k] = fail.get(k, 0) + 1
            log(f"  种子失败 {tag[:2]}: {type(e).__name__} {str(e)[:80]}")
            return
        if tag[0] == "gs":
            for r in res["value"]:
                k = f"gs/{r['via']}/{r['leg']}"
                ok[k] = ok.get(k, 0) + 1
                papers.append(r)
        elif tag[0] == "lm":
            found, dropped = res
            ok["奠基论文"] = len(found)
            papers.extend(found)
            log(f"奠基论文: 提名 {len(plan['landmarks'])}, 核对通过 {len(found)}, 丢弃 {len(dropped)}")
        else:
            ok[f"oa/{tag[1]}"] = ok.get(f"oa/{tag[1]}", 0) + len(res)
            for r in res:
                r["leg"], r["query"] = tag[1], tag[2]
                papers.append(r)

    pending = set(jobs)
    hard = time.time() + SEED_DEADLINE
    lm_deadline = None
    while pending:
        limit = hard if lm_deadline is None else min(hard, lm_deadline)
        if limit - time.time() <= 0:
            break
        done, pending = wait(pending, timeout=limit - time.time(), return_when=FIRST_COMPLETED)
        for f in done:
            take(f)
        # 只剩奠基论文还没回来:最多再等 LM_GRACE 秒(它是补充,不能拖住主线)
        if lm_deadline is None and pending and all(jobs[f][0] == "lm" for f in pending):
            lm_deadline = time.time() + LM_GRACE
    if pending:
        log(f"  种子阶段结束时仍有 {len(pending)} 个任务未回来,不再等待: {[jobs[f][0] for f in pending]}")
    ex.shutdown(wait=False, cancel_futures=True)
    seeds = [p for p in _merge(papers) if p.get("year") or p.get("abstract")]
    ph["种子检索"] = round(time.time() - t1, 1)
    log(f"种子 {len(seeds)} 篇 (检索 {ph['种子检索']}s) 成功 {ok} 失败 {fail or '无'}")

    t2 = time.time()
    _score_all(need, plan["exclude"], seeds, log, plan["components"], plan["boundary"])
    ph["种子评分"] = round(time.time() - t2, 1)

    # ---- 选门 + 滚雪球一轮 ----
    doors, refs = pick_doors(seeds, n=n_doors, ban_dois=ban_dois, log=log)
    new, sb = [], {}
    if doors:
        log("门: " + " | ".join(f"{d['year']} {d['title'][:50]}" for d in doors))
        t3 = time.time()
        try:
            new, sb = snowball(doors, refs, seeds, now, log, fwd_doors)
        except Exception as e:
            log(f"  滚雪球失败(只用种子): {type(e).__name__} {str(e)[:100]}")
        ph["滚雪球取数"] = round(time.time() - t3, 1)
        log(f"滚雪球: {sb}; 新增 {len(new)} 篇")
        t4 = time.time()
        new = [p for p in new if p.get("year") or p.get("abstract")]
        # 有摘要的立刻评分,同时去 S2 补没摘要的一句话总结;补好的再评一次(S2 补文本约 5 秒,与评分重叠)
        has = [p for p in new if p.get("abstract")]
        lacking = [p for p in new if not p.get("abstract")]
        with ThreadPoolExecutor(max_workers=1) as bg:
            f_has = bg.submit(_score_all, need, plan["exclude"], has, log, plan["components"], plan["boundary"])
            filled = sources.s2_fill_text(lacking)
            f_has.result()
        _score_all(need, plan["exclude"], lacking, log, plan["components"], plan["boundary"])
        sb.update({"无摘要": len(lacking), "一句话总结补回": filled})
        log(f"  [评分] 有摘要 {len(has)} 篇;无摘要 {len(lacking)} 篇,S2 补回 {filled}")
        ph["滚雪球评分"] = round(time.time() - t4, 1)
    else:
        log("  没有合格的门(没有带 OpenAlex 编号的高分核心论文),只用种子")

    scored = seeds + new
    for p in scored:
        p["routes"] = _routes(p)
    must, relevant, recent = rank(scored, now)
    final = {p["id"]: p for p in relevant + recent}.values()
    cover = round(sum(1 for p in final if len(p["routes"]) >= 2) / max(1, len(final)), 2)

    t5 = time.time()
    items, summary, extra = report.build(need, plan["boundary"], scored, relevant, recent, log)   # 编号、中英文摘要、综述、作者/刊名/分区
    ph["成文"] = round(time.time() - t5, 1)
    total = round(time.time() - t0, 1)
    log(f"总耗时 {total}s 分段 {ph}")

    result = {
        "mode": "lean", "need": need, "boundary": plan["boundary"], "queries": queries,
        "exclude": plan["exclude"], "generated_at": datetime.now().isoformat(timespec="seconds"),
        "recent_from": now - RECENT_YEARS,
        "stats": {"retrieved_ok": ok, "retrieved_fail": fail, "merged": len(scored), "scored": len(scored),
                  "seeds": len(seeds), "expansion_new": len(new), "snowball": sb,
                  "must": len(must), "maybe": sum(1 for p in scored if p.get("rec") == "maybe"),
                  "seconds": total, "phases": ph, "attach": extra},
        "doors": [{"id": d["id"], "title": d["title"], "year": d.get("year"), "kind": d.get("kind")} for d in doors],
        "coverage": cover,
        "summary": summary, "items": items,
    }
    path = render_lean(result, out_dir)
    import json
    (path.parent / "all.json").write_text(json.dumps(scored, ensure_ascii=False, default=list), encoding="utf-8")
    log(f"输出: {path}")
    result["_path"] = str(path)
    return result
