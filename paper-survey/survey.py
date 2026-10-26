#!/usr/bin/env python3
"""paper-survey 入口:一段模糊需求 → 本地摘要级文献调研页(可勾选、可批注)。

用法:
  python survey.py "调研需求" [--out 目录] [--draws 6] [--verbose]
  python survey.py --download <输出目录> [--picks 3,5,8 | --review review.json]
  python survey.py --check-config      列出哪些资源已配、哪些缺(只报变量名,不显示值)
  python survey.py --selftest          离线自检,不联网不花钱,rc=0 即代码完整
"""
import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "paper_survey"))

import config  # noqa: E402

RESOURCES = [  # (变量, 必需?, 用途)
    ("LLM_BASE_URL", True, "OpenAI 兼容接口地址"),
    ("LLM_MODEL", True, "模型名"),
    ("LLM_API_KEY", True, "接口 key(本地无鉴权的服务可留空)"),
    ("SERPER_API_KEY", False, "谷歌学术种子(缺则只用 OpenAlex,召回降低)"),
    ("OPENALEX_API_KEY", False, "OpenAlex 额度"),
    ("OPENALEX_MAILTO", False, "OpenAlex 礼貌池邮箱"),
    ("S2_API_KEY", False, "Semantic Scholar 限流放宽"),
    ("CAS_TABLE_CSV", False, "中科院分区表(用户自备 CSV)"),
    ("PAPER_DOWNLOAD_CMD", False, "批量下载用的下载工具命令模板"),
]


def check_config():
    miss_req = []
    for name, req, why in RESOURCES:
        have = bool(config.get(name))
        if name == "CAS_TABLE_CSV" and have and not Path(config.get(name)).is_file():
            have = False
        print("%-20s %-4s %s  %s" % (name, "必需" if req else "可选", "已配" if have else "缺", why))
        if req and not have and name != "LLM_API_KEY":
            miss_req.append(name)
    return 2 if miss_req else 0


def leaks(paths):
    """写出的文件里有没有出现任何已配置的 key 值;返回命中的文件名(不返回值)。"""
    vals = config.secret_values()
    hit = []
    for p in paths:
        p = Path(p)
        if p.is_file() and vals:
            s = p.read_text(encoding="utf-8", errors="ignore")
            if any(v in s for v in vals):
                hit.append(p.name)
    return hit


def make_log(verbose):
    def log(s):
        if verbose or not str(s).startswith("  "):
            print(s, flush=True)
    return log


def run_survey(a):
    import lean
    import review
    if not (config.get("LLM_BASE_URL") and config.get("LLM_MODEL")):
        print("缺配置:LLM_BASE_URL / LLM_MODEL。先 python survey.py --check-config", file=sys.stderr)
        return 2
    out = Path(a.out) if a.out else Path.cwd() / "surveys" / time.strftime("%Y%m%d-%H%M%S")
    res = lean.run(a.need, draws=a.draws, ban_dois=a.ban_doi, out_dir=str(out), log=make_log(a.verbose))
    page = Path(res["_path"])
    bad = leaks([page, page.parent / "result.json", page.parent / "all.json"])
    if bad:
        for f in bad:
            (page.parent / f).unlink()
        print("拒绝输出:%s 里出现了 key 值,已删除" % "、".join(bad), file=sys.stderr)
        return 4
    try:
        idx, n, must = review.make_review(res, page.parent.name, page)
    except review.SchemaError as e:
        print("审阅层没叠上(%s);原始页面仍可看: %s" % (e, page), file=sys.stderr)
        return 3
    print("共 %d 篇(必读 %d);篇号索引 %s" % (n, must, idx))
    print("页面: %s" % page)
    return 0


def run_download(a):
    import review
    d = Path(a.download)
    idx_f = d / "papers.json"
    if not idx_f.is_file():
        print("找不到 %s(先跑一次调研)" % idx_f, file=sys.stderr)
        return 2
    idx = json.loads(idx_f.read_text(encoding="utf-8"))
    if a.review:
        picks = [str(x) for x in json.loads(Path(a.review).read_text(encoding="utf-8")).get("picks", [])]
    else:
        picks = review.parse_picks(a.picks)
    if not picks:
        print("没有篇号:给 --picks 3,5 或 --review review.json", file=sys.stderr)
        return 2
    try:
        dl = review.command_downloader()
    except review.SchemaError as e:
        print(str(e), file=sys.stderr)
        return 2
    text, res = review.download_batch(idx, picks, d / "downloads", dl)
    print(text)
    return 0 if any(r.get("ok") for _, r in res) else 1


def main():
    ap = argparse.ArgumentParser(description="paper-survey:摘要级快速文献调研")
    ap.add_argument("need", nargs="?", help="调研需求,可以是一段模糊的话")
    ap.add_argument("--out", help="输出目录(默认 ./surveys/<时间>/)")
    ap.add_argument("--draws", type=int, default=6, help="Serper 每词每路抽样次数;0=不用谷歌学术")
    ap.add_argument("--ban-doi", action="append", default=[], help="评测用:不把这个 DOI 当起点")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--download", metavar="输出目录", help="按勾选批量下载")
    ap.add_argument("--picks", default="", help="篇号,如 3,5,8")
    ap.add_argument("--review", help="页面导出的 review.json")
    ap.add_argument("--check-config", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.path.insert(0, str(HERE / "测试"))
        import selftest
        return selftest.main()
    if a.check_config:
        return check_config()
    if a.download:
        return run_download(a)
    if not a.need:
        ap.error("需要给出调研需求")
    return run_survey(a)


if __name__ == "__main__":
    sys.exit(main())
