"""成品页的数据:统一显示编号(1,2,3…)、中英文摘要、综述式总结(中英)。

编号按页面显示顺序:最相关 → 近两年 → 更多相关文献。总结里的 [n] 就是这个编号,页面里可点击跳到对应文献。
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor

from llm import chat

MORE_MUST = 40       # "更多相关文献"里最多放多少篇必读级
MORE_MAYBE = 40      # 最多放多少篇可能相关(按相关度、共同引用、被引排序取前面的)
SUM_CONTEXT_MORE = 12  # 总结除最相关和近两年外,再参考"更多"里靠前的几篇
ABS_CHARS = 1500


def select_display(scored, relevant, recent):
    """显示顺序并编号。返回 [paper...](同一批 dict,写入 n 和 sec)。"""
    key = lambda p: (p.get("relevance") or 0, p.get("doors_cnt", 0), p.get("cites") or 0)
    items = [("relevant", p) for p in relevant] + [("recent", p) for p in recent]
    ids = {p["id"] for _, p in items}
    more_must = sorted([p for p in scored if p.get("rec") == "must" and p["id"] not in ids], key=key, reverse=True)[:MORE_MUST]
    more_maybe = sorted([p for p in scored if p.get("rec") == "maybe" and p["id"] not in ids],
                        key=key, reverse=True)[:MORE_MAYBE]
    items += [("more", p) for p in more_must + more_maybe]
    out = []
    for n, (sec, p) in enumerate(items, 1):
        p["n"], p["sec"] = n, sec
        out.append(p)
    return out


def _json_from(text):
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else {}


TRANS_PROMPT = """把下面这篇论文的标题和摘要翻译成中文。忠实翻译,不增不减,不加解释,专业术语用学界通行译法(拿不准的保留英文)。
只输出 JSON:{{"title_zh": "...", "abstract_zh": "..."}};没有摘要时 abstract_zh 给空字符串。

标题:{title}
摘要:{abstract}"""


def translate(p):
    ab = (p.get("abstract") or "")[:ABS_CHARS]
    try:
        js = _json_from(chat([{"role": "user", "content": TRANS_PROMPT.format(title=p["title"], abstract=ab or "无")}],
                             max_tokens=900))
        return str(js.get("title_zh") or ""), (str(js.get("abstract_zh") or "") if ab else "")
    except Exception:
        return "", ""


SUM_ZH = """你在为科研人员写一份文献调研综述。下面是 {n} 篇相关文献(编号、年份、标题、摘要)。
用户的需求:{need}
调研范围:{boundary}

请写一篇结构清晰的中文综述,{length}:
1. 开头 2–3 句交代这个问题是什么、为什么重要(只能依据文献内容);
2. 按主题或技术路线分成若干段,每段说明该路线的核心思想、代表工作、主要结论或结果;
3. 说明各路线之间的关系、争议、局限和尚未解决的问题;
4. 结尾 2–3 句概括整体脉络。
硬性要求:
- 每一个具体论断后面标注来源编号,格式为 [3] 或 [3][7](一个方括号一个编号),只能用下面给出的编号。
- 只陈述摘要或标题里有的内容,不编造数据、结论或作者观点;没有摘要的文献只能引用标题所体现的内容。
- 不要逐篇罗列,要综合、对比、归纳;可以用「**关键词**」加粗每段的主题。
- 段落之间空一行,不要用标题和列表符号。

文献:
{items}
"""

SUM_EN = """You are writing a literature-survey synthesis for researchers. Below are {n} relevant papers (number, year, title, abstract).
User's request: {need}
Scope: {boundary}

Write a well-structured review in English, {length}:
1. Open with 2–3 sentences on what the problem is and why it matters (grounded only in the papers);
2. Then several paragraphs organized by theme or technical approach: the core idea, representative work, main findings or results;
3. Discuss relations between approaches, disagreements, limitations and open problems;
4. Close with 2–3 sentences summarizing the overall trajectory.
Hard rules:
- After every concrete claim, cite the source number as [3] or [3][7] (one number per bracket), using only the numbers given below.
- State only what the abstracts/titles support; never invent numbers, results or opinions; for papers with no abstract cite only what the title shows.
- Synthesize, compare and generalize — do not list paper by paper. You may bold a paragraph's topic with **keyword**.
- Separate paragraphs with a blank line; no headings or bullet symbols.

Papers:
{items}
"""

LENGTH = {
    ("overall", "zh"): "约 800–1200 字", ("overall", "en"): "about 500–800 words",
    ("recent", "zh"): "约 400–700 字,聚焦最近两年出现的新方向、新做法和新趋势,并指出它们相对更早工作的变化", ("recent", "en"): "about 250–450 words, focusing on new directions, methods and trends of the last two years and how they differ from earlier work",
}


def clean_cites(text, n_max):
    """把 [3, 7] 规整成 [3][7],删掉不存在的编号。"""
    def fix(m):
        nums = [int(x) for x in re.findall(r"\d+", m.group(1))]
        return "".join(f"[{x}]" for x in nums if 1 <= x <= n_max)
    return re.sub(r"\[([0-9][0-9,，、\s]*)\]", fix, text or "")


def _item_line(p, lang):
    ab = (p.get("abstract") or "")[:700]
    no = "(无摘要)" if lang == "zh" else "(no abstract)"
    lab = "摘要" if lang == "zh" else "Abstract"
    return f"[{p['n']}] {p.get('year') or '?'} | {p['title']} | {lab}: {ab or no}"


def write_summary(kind, lang, need, boundary, papers, n_max):
    if not papers:
        return ""
    tpl = SUM_ZH if lang == "zh" else SUM_EN
    prompt = tpl.format(n=len(papers), need=need, boundary=boundary or "-", length=LENGTH[(kind, lang)],
                        items="\n".join(_item_line(p, lang) for p in papers))
    try:
        return clean_cites(chat([{"role": "user", "content": prompt}], max_tokens=3500, timeout=180), n_max).strip()
    except Exception:
        return ""


def _attach_meta(items, log):
    """给展示篇补作者、干净刊名、中科院分区。与翻译在同一个池里并发跑,不额外占串行时间。
    enrich 先取 authors/venue/_issn/_type(供 cas 判因);cas 再挂中科院分区;最后清掉私有键。"""
    st = {}
    try:
        import enrich
        st["enrich"] = enrich.attach(items, log)
    except Exception as e:
        log(f"  [补取失败] {type(e).__name__} {str(e)[:100]}")
    try:
        import cas
        st["cas"] = cas.attach(items, log)
    except Exception as e:
        log(f"  [分区失败] {type(e).__name__} {str(e)[:100]}")
    for p in items:
        for k in ("_issn", "_type", "_src_type"):
            p.pop(k, None)
    return st


def build(need, boundary, scored, relevant, recent, log=print):
    """返回 (items, summary, extra)。items 带编号、中英文标题/摘要、作者/刊名/分区;
    summary={overall:{zh,en}, recent:{zh,en}};extra=补取统计。"""
    items = select_display(scored, relevant, recent)
    n_max = len(items)
    main = [p for p in items if p["sec"] in ("relevant", "recent")]
    ctx_overall = main + [p for p in items if p["sec"] == "more"][:SUM_CONTEXT_MORE]
    rec_items = [p for p in items if p["sec"] == "recent"]
    with ThreadPoolExecutor(max_workers=min(200, len(items) + 4)) as ex:
        f_tr = {p["n"]: ex.submit(translate, p) for p in items}
        f_sum = {(k, l): ex.submit(write_summary, k, l, need, boundary, ps, n_max)
                 for k, ps in (("overall", ctx_overall), ("recent", rec_items)) for l in ("zh", "en")}
        f_meta = ex.submit(_attach_meta, items, log)          # 作者/刊名/分区:与翻译同一个池并发
        for p in items:
            p["title_zh"], p["abstract_zh"] = f_tr[p["n"]].result()
        summary = {"overall": {}, "recent": {}}
        for (k, l), f in f_sum.items():
            summary[k][l] = f.result()
        extra = f_meta.result()
    failed = sum(1 for p in items if not p["title_zh"])
    if failed:
        log(f"  [报告] {failed}/{n_max} 篇翻译失败(页面里中文模式回退为英文原文)")
    return items, summary, extra
