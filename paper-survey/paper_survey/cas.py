"""中科院分区(可选):用户自备 CSV 表,ISSN 优先、刊名归一后完全相等才算命中。

分区表授权不明,不随包分发。CAS_TABLE_CSV 指向你自己的表;不配就跳过,页面不显示分区。
CSV 需要表头,列名(大小写不敏感):journal, issn, eissn, zone, top, if, jcr_zone;
只有 journal 与 zone 必需。zone 写「1区」或「1」都行;top 写 是/否、Y/N、1/0、TRUE/FALSE。
每篇写 items[].cas:
  命中   {"hit": true, "zone": "2区", "top": false, "if": 4.5, "jcr_zone": "Q2", "src": "cas_table"}
  未命中 {"hit": false, "why": "会议论文,无中科院分区", "why_en": "conference paper, no CAS partition"}
"""
import csv
import re
import time

import config

NA_TYPE = {
    "preprint": ("预印本,无中科院分区", "preprint, no CAS partition"),
    "conference-paper": ("会议论文,无中科院分区", "conference paper, no CAS partition"),
    "book-chapter": ("图书/丛书章节,无中科院分区", "book/series chapter, no CAS partition"),
    "dissertation": ("学位论文,无中科院分区", "dissertation, no CAS partition"),
}
NA_SRC = {
    "repository": ("预印本,无中科院分区", "preprint, no CAS partition"),
    "conference": ("会议论文,无中科院分区", "conference paper, no CAS partition"),
    "book series": ("丛书章节,无中科院分区", "book/series chapter, no CAS partition"),
}
NO_ID = ("无刊名与 ISSN,无法查分区", "no journal name or ISSN, cannot look up")
UNLISTED = ("分区表未收录", "not in the CAS table")
_YES = {"是", "y", "yes", "1", "true", "top"}
_table = {}


def na_reason(wtype, src_type):
    """会议/预印本/丛书/学位论文 → (why, why_en);是期刊/未知 → None。"""
    return NA_TYPE.get((wtype or "").strip()) or NA_SRC.get((src_type or "").strip().lower())


def _miss(pair):
    return {"hit": False, "why": pair[0], "why_en": pair[1]}


def norm_issn(s):
    s = re.sub(r"[^0-9Xx]", "", s or "").upper()
    return s if len(s) == 8 else ""


def norm_name(s):
    s = (s or "").lower().replace("&", " and ")
    s = re.sub(r"^the\s+", "", s.strip())
    return re.sub(r"[^0-9a-z一-鿿]", "", s)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load(path):
    """读 CSV → {"issn": {...}, "name": {...}};一行一刊。"""
    by_issn, by_name = {}, {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            r = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            z = r.get("zone", "")
            if not (r.get("journal") or r.get("issn")) or not z:
                continue
            zone = z if z.endswith("区") else (z + "区" if z.isdigit() else z)
            rec = {"hit": True, "zone": zone, "top": r.get("top", "").lower() in _YES,
                   "if": _num(r.get("if")), "jcr_zone": r.get("jcr_zone") or None, "src": "cas_table"}
            for k in ("issn", "eissn"):
                for x in re.split(r"[;,/\s]+", r.get(k, "")):
                    if norm_issn(x):
                        by_issn[norm_issn(x)] = rec
            if norm_name(r.get("journal")):
                by_name[norm_name(r["journal"])] = rec
    return {"issn": by_issn, "name": by_name}


def table():
    path = config.get("CAS_TABLE_CSV")
    if not path:
        return None
    if path not in _table:
        _table[path] = load(path)
    return _table[path]


def lookup(t, issn, venue):
    return t["issn"].get(norm_issn(issn)) or t["name"].get(norm_name(venue))


def attach(items, log=print):
    """就地给 items 补 cas;没配表返回 {"skipped": ...} 且不写 cas。"""
    t0 = time.time()
    t = table()
    if t is None:
        log("  [分区] 未配置 CAS_TABLE_CSV,跳过")
        return {"skipped": "no CAS_TABLE_CSV"}
    stat = {"hit": 0, "not_applicable": 0, "unlisted": 0, "no_id": 0}
    for p in items:
        na = na_reason(p.get("_type"), p.get("_src_type"))
        if na:
            p["cas"], k = _miss(na), "not_applicable"
        elif not ((p.get("_issn") or "").strip() or (p.get("venue") or "").strip()):
            p["cas"], k = _miss(NO_ID), "no_id"
        else:
            hit = lookup(t, p.get("_issn"), p.get("venue"))
            p["cas"], k = (dict(hit), "hit") if hit else (_miss(UNLISTED), "unlisted")
        stat[k] += 1
    stat["seconds"] = round(time.time() - t0, 1)
    log("  [分区] 命中 %d、会议/预印本等不适用 %d、未收录 %d、无刊名 %d"
        % (stat["hit"], stat["not_applicable"], stat["unlisted"], stat["no_id"]))
    return stat
