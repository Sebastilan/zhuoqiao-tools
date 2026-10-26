"""谷歌学术种子:经 Serper 官方 /scholar 接口(可选;没配 key 就跳过,只用 OpenAlex)。

Serper 每次调用是谷歌学术结果的一次抽样(条数 0–10 不定,重复调用结果不同),所以每词多抽几次取并集。
每次调用都计费(含空结果)。输出、日志不含 key。
"""
import json
import random
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

import config
from pool import KeyPool

URL = "https://google.serper.dev/scholar"
_pool = []


def enabled():
    return bool(config.get_list("SERPER_API_KEY"))


def _keys():
    if not _pool:
        _pool.append(KeyPool(config.get_list("SERPER_API_KEY")))
    return _pool[0]


def _norm(x):
    return {"src": "gs", "title": (x.get("title") or "").strip(),
            "year": x.get("year") if isinstance(x.get("year"), int) else None,
            "cites": x.get("citedBy") or 0, "abstract": (x.get("snippet") or "").strip(),
            "doi": None, "venue": (x.get("publicationInfo") or "").strip(), "url": x.get("link") or ""}


def scholar(query, page=1, as_ylo=None, num=10, timeout=20):
    pool = _keys()
    body = {"q": query, "num": num, "page": page}
    if as_ylo:
        body["as_ylo"] = as_ylo
    last = "无"
    for _ in range(3):
        key = pool.next()
        if key is None:
            break
        req = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST",
                                     headers={"X-API-KEY": key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return [_norm(x) for x in json.loads(r.read()).get("organic", [])]
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code in (401, 403):       # key 无效或额度用完:踢出,换下一把
                pool.kill(key)
        except Exception as e:
            last = type(e).__name__
    raise RuntimeError(f"serper 失败: {last}")


def search(queries, from_year=None, draws=6, timeout=60):
    """返回 {"value": [论文…]};每条带 leg(classic/recent)、query、via=serper。全空时抛错。"""
    if not enabled():
        raise RuntimeError("未配置 SERPER_API_KEY,跳过谷歌学术")
    legs = [("classic", None)] + ([("recent", from_year)] if from_year else [])
    rows, fail = [], 0
    with ThreadPoolExecutor(max_workers=max(4, len(queries) * len(legs) * draws)) as ex:
        jobs = {ex.submit(scholar, q, i % 3 + 1 if i < 3 else random.randint(1, 3), y): (leg, q)
                for q in queries for leg, y in legs for i in range(draws)}
        for f in as_completed(jobs, timeout=timeout):
            leg, q = jobs[f]
            try:
                for r in f.result():
                    r.update(leg=leg, query=q, via="serper")
                    rows.append(r)
            except Exception:
                fail += 1
    if not rows:
        raise RuntimeError(f"谷歌学术无结果(失败 {fail} 次)")
    return {"value": rows}
