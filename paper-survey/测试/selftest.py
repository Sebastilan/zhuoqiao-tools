"""离线自检:不联网、不花钱、不需要任何 key。rc=0 即代码完整。

覆盖:所有模块可导入;合成调研结果 → 渲染页面 → 叠加审阅层 → 篇号索引;
假下载器走一遍批量下载与打包;byline 拆作者;用户自备分区 CSV 查表;篇号解析;
页面泄密自查;联网函数被禁用(本自检一旦触网即失败)。
"""
import importlib
import json
import os
import socket
import sys
import tempfile
import traceback
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PKG / "paper_survey"))
sys.path.insert(0, str(PKG))

MODULES = ["config", "pool", "llm", "sources", "scholar", "stages", "core", "enrich",
           "cas", "report", "render", "review", "lean"]


def _no_net(*a, **k):
    raise RuntimeError("selftest 不许联网")


def _fixture():
    items = []
    for i in range(1, 6):
        items.append({
            "n": i, "id": "W%d" % (1000 + i), "sec": "relevant" if i <= 2 else "recent" if i <= 4 else "more",
            "title": "Branch-cut-and-price for vehicle routing, part %d" % i,
            "title_zh": "车辆路径的分支定价切割 第 %d 部分" % i,
            "abstract": "We study exact algorithms. Part %d." % i, "abstract_zh": "研究精确算法。第 %d 部分。" % i,
            "year": 2020 + i, "doi": "10.1234/selftest.%d" % i if i != 3 else "", "url": "https://example.org/p%d" % i,
            "venue": "Transportation Science", "volume": "5%d" % i, "issue": "2", "pages": "1-20",
            "authors": ["Alice Smith", "Bob Lee"], "cites": 10 * i, "relevance": 10 - i,
            "rec": "must" if i <= 3 else "maybe", "srcs": ["oa"], "routes": ["oa种子", "backward"],
            "doctype": "journal-article",
            "cas": {"hit": True, "zone": "2区", "top": False, "if": 4.5, "jcr_zone": "Q2", "src": "cas_table"} if i % 2 else
                   {"hit": False, "why": "分区表未收录", "why_en": "not in the CAS table"},
        })
    return {"mode": "lean", "need": "自检:分支定价求解车辆路径", "boundary": "BCP 求解 CVRP 本体",
            "queries": ["branch cut price CVRP"], "exclude": [], "generated_at": "2026-01-01T00:00:00",
            "recent_from": 2024,
            "stats": {"merged": 5, "must": 3, "scored": 5},
            "doors": [{"id": "W1001", "title": items[0]["title"], "year": 2021, "kind": "survey"}],
            "coverage": 0.6,
            "summary": {"overall": {"zh": "综述段落 [1][2]。", "en": "Overview [1][2]."},
                        "recent": {"zh": "近两年 [3]。", "en": "Recent [3]."}},
            "items": items}


def check(name, fn, fails):
    try:
        fn()
        print("ok   " + name)
    except Exception:
        fails.append(name)
        print("FAIL " + name)
        traceback.print_exc(limit=3)


def main():
    socket.socket.connect = _no_net
    socket.create_connection = _no_net
    for k in ("LLM_API_KEY", "SERPER_API_KEY", "OPENALEX_API_KEY", "S2_API_KEY", "CAS_TABLE_CSV", "PAPER_DOWNLOAD_CMD"):
        os.environ[k] = ""
    fails = []
    tmp = Path(tempfile.mkdtemp(prefix="paper-survey-selftest-"))
    mods = {}

    def imports():
        for m in MODULES:
            mods[m] = importlib.import_module(m)
    check("导入全部模块", imports, fails)
    if fails:
        return 1
    render, review, enrich, cas, llm, config = (mods[k] for k in ("render", "review", "enrich", "cas", "llm", "config"))

    res = _fixture()
    out = tmp / "run"
    page = {}

    def do_render():
        p = render.render_lean(json.loads(json.dumps(res)), str(out))
        s = p.read_text(encoding="utf-8")
        assert "GB/T 7714" in s and "[1]" in s and "ref-1" in s
        assert (out / "result.json").is_file()
        page["p"] = p
    check("渲染结果页", do_render, fails)

    def do_review():
        idx, n, must = review.make_review(res, "selftest", page["p"])
        s = page["p"].read_text(encoding="utf-8")
        assert n == 5 and must == 3, (n, must)
        assert s.count('data-pick="paper:') == 5, "每篇恰好一个下载勾选"
        assert 'type="checkbox" class="pick"' not in s
        j = json.loads(Path(idx).read_text(encoding="utf-8"))
        assert j["papers"]["1"]["basis"] == "doi" and j["papers"]["3"]["basis"] == "url"
    check("审阅层与篇号索引", do_review, fails)

    def do_schema():
        try:
            review.validate({"items": []})
        except review.SchemaError:
            return
        raise AssertionError("空结果应抛 SchemaError")
    check("结果字段校验", do_schema, fails)

    def do_picks():
        assert review.parse_picks("12,15、18 007 [3]") == ["12", "15", "18", "7", "3"]
    check("篇号解析", do_picks, fails)

    def do_download():
        fake = tmp / "fake_dl.py"
        fake.write_text("import sys,pathlib\np=pathlib.Path(sys.argv[2]);p.mkdir(parents=True,exist_ok=True)\n"
                        "(p/'x.pdf').write_bytes(b'%PDF-1.4 selftest')\n", encoding="utf-8")
        dl = review.command_downloader('"%s" "%s" {input} {out}' % (sys.executable, fake))
        idx = json.loads((out / "papers.json").read_text(encoding="utf-8"))
        text, r = review.download_batch(idx, ["1", "2", "3", "4", "99"], out / "downloads", dl)
        assert sum(1 for _, x in r if x.get("ok")) == 4, text
        assert list((out / "downloads").glob("*.zip")), "成功超过 3 篇应打包"
        assert "99" in text
    check("批量下载(假下载器)", do_download, fails)

    def do_byline():
        f = enrich._authors_from_byline
        got = f("A Smith, B Lee - Transportation Science, 2021 - pubsonline.informs.org")
        assert got and "Smith" in " ".join(got), got
        assert not f("Branch and price: column generation for solving - Operations Research, 1998")
    check("byline 拆作者(宁空不编)", do_byline, fails)

    def do_cas():
        csvp = tmp / "cas.csv"
        csvp.write_text("journal,issn,zone,top\nTransportation Science,0041-1655,2区,否\n", encoding="utf-8")
        t = cas.load(str(csvp))
        hit = cas.lookup(t, "0041-1655", "")
        assert hit and "2" in str(hit.get("zone")), hit
    check("分区表(用户自备 CSV)", do_cas, fails)

    def do_llm_cfg():
        b = llm.body_for([{"role": "user", "content": "hi"}], 10, "m", {"reasoning_effort": "none"})
        assert b["model"] == "m" and b["reasoning_effort"] == "none"
        os.environ["LLM_BASE_URL"], os.environ["LLM_MODEL"] = "", ""
        llm._cfg.clear()
        try:
            llm.chat([{"role": "user", "content": "x"}])
        except llm.LLMError as e:
            assert "LLM_BASE_URL" in str(e)
            return
        raise AssertionError("缺配置应报 LLMError")
    check("大模型配置与报错", do_llm_cfg, fails)

    def do_leak():
        import survey
        os.environ["S2_API_KEY"] = "selftest-secret-0123456789"
        f = tmp / "leak.html"
        f.write_text("ok selftest-secret-0123456789", encoding="utf-8")
        assert survey.leaks([f]) == ["leak.html"]
        assert survey.leaks([page["p"]]) == []
        os.environ["S2_API_KEY"] = ""
    check("页面泄密自查", do_leak, fails)

    print("\n%d 项失败" % len(fails) if fails else "\n全部通过(离线)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
