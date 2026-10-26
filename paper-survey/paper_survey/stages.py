"""大模型三步:拆搜索词(plan)、摘要级评分(score)、摘要总结(summarize)。"""
import json
import re

from llm import chat

MAX_QUERIES = 5
MAX_LANDMARKS = 8
MAX_COMPONENTS = 4


def _json_from(text):
    m = re.search(r"[\[{].*[\]}]", text, re.S)
    if not m:
        raise ValueError("模型输出里没有 JSON")
    return json.loads(m.group(0))


PLAN_PROMPT = """你是文献检索助手。把用户的需求改写成学术检索词。
要求:
- 只给完成检索所需的最少搜索词。常见 2–3 个;确实需要更多时最多 {n} 个。不要凑数。搜索词要覆盖问题的**不同侧面**,不要同义改写:一个对准总题;如果问题建立在某个成熟的经典领域或传统做法上(例如"用新技术改进某个经典任务"),另给一个覆盖那个经典脉络的词——研究者必读的往往是经典脉络。
- 用英文学术术语,每个词是一个短语(2–6 个词),不要整句。
- 排除用户明确不要的内容。
- boundary:用一两句中文写出你对调研范围的理解——要找什么,什么不算。注意:问题的方法链条上的各个环节(模型、子问题、关键技术组件)只要服务于这个问题,都算在范围内,不要因为一篇文章只涉及其中一个环节就排除它;只有另一个问题的变体、行业应用、以及用户不要的方法类别才不算。用户会看到它,用来确认你理解对没有。
- components:该问题在方法上的关键组成部分(子问题/核心技术),每个一个短语(2–5 个词),用来补召回——有些重要论文的标题里根本不含总题目的词,只写技术组件。题目没有明显分解就给空数组;最多 {c} 个。
- landmarks:该领域公认的奠基或代表性论文,最多 {m} 篇。你对标题的记忆可能走样,**可靠的是第一作者姓和年份**,所以每篇给 {{"author": "第一作者姓", "year": 年份, "title": "你记得的英文标题"}};没把握的不要写。这些会去数据库按作者+年份核对,对不上的丢弃。
只输出 JSON,格式:{{"boundary": "...", "queries": ["..."], "components": ["..."], "exclude": ["..."], "landmarks": [{{"author": "...", "year": 2000, "title": "..."}}]}}

用户需求:
{need}
"""


def plan(need):
    out = chat([{"role": "user", "content": PLAN_PROMPT.format(n=MAX_QUERIES, m=MAX_LANDMARKS, c=MAX_COMPONENTS, need=need)}],
               max_tokens=1200)
    js = _json_from(out)
    queries = [q.strip() for q in js.get("queries", []) if q and q.strip()]
    queries = list(dict.fromkeys(queries))[:MAX_QUERIES]
    if not queries:
        raise ValueError("模型没有给出搜索词")
    lm = []
    for x in js.get("landmarks", []):
        try:
            if isinstance(x, dict) and x.get("author") and int(x.get("year")):
                lm.append({"author": str(x["author"]).strip(), "year": int(x["year"]),
                           "title": str(x.get("title") or "").strip()})
        except (TypeError, ValueError):
            continue
    comps = [c.strip() for c in js.get("components", []) if isinstance(c, str) and c.strip()]
    comps = [c for c in dict.fromkeys(comps) if c not in queries][:MAX_COMPONENTS]
    return {"boundary": str(js.get("boundary") or "")[:400], "queries": queries, "components": comps, "exclude": js.get("exclude", []),
            "landmarks": lm[:MAX_LANDMARKS]}


SCORE_PROMPT = """你是文献相关性判断员。只依据下面的标题和摘要判断,不得推断摘要之外的内容。
用户需求:{need}
排除项:{exclude}

边界声明(调研范围的理解,按它判断):{boundary}

对每篇输出:
- relevance:0–5,与用户需求的相关程度。锚点:
  5 = 直接研究用户问题本身,方法或结论可直接用于该问题;
  4 = 明确针对该问题的相邻方法或子问题;
  2–3 = 只在同一大领域内,或只提及相关概念;
  0–1 = 无关。
  不要因为论文「属于同一大方向」就给 5。
- scope:core 或 out。
  core = 论文的**贡献本体**落在用户问题本身,或落在解决该问题的方法链条上的某个环节(关键组件见下)——
         即使它写在更宽的框架里、标题里没有出现问题名称,也算 core。
  out  = 用户没问的另一个问题、把方法当现成工具用在具体行业的应用、只在背景里提到、或属于排除项。
         判变体的操作办法:论文标题给「问题名」多加了限定语(额外的约束、对象或场景),而用户需求里并没有这个限定语,
         就是变体,一律 out——不论质量与被引多高,也不论它的算法有多接近。标题没写出限定语就不要自己推断它是变体。
关键方法组件:{components}
- kind:论文类型。survey(综述/教程/述评)、method(提出或改进方法)、application(应用)、other
- one_line:40 字以内的中文定位

只输出 JSON 数组,每项为 {{"id": "...", "relevance": 0, "scope": "core", "kind": "method", "one_line": "..."}}。

论文:
{items}
"""


def score(need, exclude, batch, components=(), boundary=""):
    items = "\n".join(
        f"[{p['id']}] {p['title']} | {p.get('year') or '?'} | "
        f"摘要:{(p.get('abstract') or '无')[:600]}"
        for p in batch)
    msg = [{"role": "user", "content": SCORE_PROMPT.format(
        need=need, exclude="、".join(exclude) or "无",
        components="、".join(components) or "无",
        boundary=boundary or "无", items=items)}]
    rows = None
    for attempt in range(2):   # 一篇一批时模型偶尔输出格式不规范,重试一次
        try:
            rows = _json_from(chat(msg, max_tokens=300 * max(1, len(batch))))
            if isinstance(rows, dict):
                rows = [rows]
            break
        except (ValueError, TypeError):
            continue
    if rows is None:
        raise ValueError("评分输出无法解析")
    res = {}
    for r in rows:
        pid = str(r.get("id", ""))
        try:
            rel = int(r.get("relevance", 0))
        except (TypeError, ValueError):
            rel = 0
        scope = r.get("scope") if r.get("scope") in ("core", "out") else "out"
        kind = r.get("kind") if r.get("kind") in ("survey", "method", "application", "other") else "other"
        res[pid] = {"relevance": max(0, min(5, rel)), "scope": scope, "kind": kind,
                    "one_line": str(r.get("one_line", ""))[:80]}
    return res


def recommend(rel, scope):
    """沿用 survey-lab 的机械规则:core 且 ≥4 为 must;out 最多 maybe;≥2 为 maybe;其余 skip。"""
    if scope == "core" and rel >= 4:
        return "must"
    if rel >= 2:
        return "maybe"
    return "skip"


SUM_PROMPT = """下面是一组相近的文献(标题、年份、摘要)。写一段 2–4 句的中文总结,说明它们共同讨论什么、主要结论或做法是什么。
要求:
- 只陈述摘要里有的内容,不做摘要之外的推断。
- 每条结论后面用 [id] 标出出处。
- 不要逐篇复述。

{title}
{items}
"""


def summarize(title, papers):
    if not papers:
        return ""
    items = "\n".join(
        f"[{p['id']}] {p['title']} ({p.get('year') or '?'}) 摘要:{(p.get('abstract') or '无')[:400]}"
        for p in papers)
    return chat([{"role": "user", "content": SUM_PROMPT.format(title=title, items=items)}],
                max_tokens=600)
