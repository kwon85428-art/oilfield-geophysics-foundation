#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""油田勘探开发研究院 · 核心学者蒸馏。

吃 fetch_institute.py 的产出，做三件事：
  1. 门槛筛选（config.threshold）
  2. 子领域归类（config.domain_rules_file，跨院共用）
  3. 中文姓名映射（config.name_cn_file，每院独立，仅含已核实姓名）

用法：
    python distill_core.py --config institutes/daqing.json [--outdir out/daqing]

输出：
    <outdir>/<short>_core.json    核心学者数据件（单一真值来源）
        name_cn 非空 = 已核实；为空 = 待核实（进附录，不硬填）

⚠️ name_cn 映射里的每个中文姓名都必须有公开来源核实，禁止音译填充。
   见 references/institute-name-verification.md。
"""
import argparse
import json
import re
from collections import defaultdict
from pathlib import Path


def norm_name(s):
    """姓名归一化：小写、去所有空白（含 NBSP/全角）、去连字符与标点。

    ⚠️ 必须用 isspace() 判断空白，.replace(" ", "") 去不掉 U+00A0。
       见 references/openalex-pitfalls.md 第 3 条。
    """
    if not s:
        return ""
    s = "".join(ch for ch in s.lower() if not ch.isspace())
    return s.replace("-", "").replace(".", "").replace(",", "")


def load_config(path):
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    base = Path(path).parent
    dr = cfg.get("domain_rules_file")
    nc = cfg.get("name_cn_file")
    cfg["_domain_rules"] = json.loads((base / dr).read_text(encoding="utf-8"))
    cfg["_name_cn"] = json.loads((base / nc).read_text(encoding="utf-8"))
    # 归一化后的姓名映射，避免大小写/连字符差异导致漏匹配
    cfg["_name_cn_norm"] = {norm_name(k): v for k, v in cfg["_name_cn"].items()}
    return cfg


def classify(titles, venues, domain_rules):
    """按标题+期刊做领域归类。命中模式数决胜负，并列取编号最小。"""
    txt = " ".join((t or "") for _, t in titles) + " " + " ".join(venues or [])
    scores = {}
    for dom, pats in domain_rules.items():
        n = sum(len(re.findall(p, txt, re.I)) for p in pats)
        if n:
            scores[dom] = n
    if not scores:
        return "未归类"
    best = max(scores.values())
    return sorted(d for d, n in scores.items() if n == best)[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--outdir", default=None)
    args = ap.parse_args()

    cfg = load_config(args.config)
    inst = cfg["institution"]
    outdir = Path(args.outdir) if args.outdir else Path(args.config).parent / f"out_{inst['short']}"

    roster = json.loads(
        (outdir / f"{inst['short']}_roster.json").read_text(encoding="utf-8"))
    th = cfg.get("threshold", {"yjy_min": 2, "cited_min": 30})

    core = [x for x in roster
            if x["yjy_papers"] >= th["yjy_min"] and x["total_cited"] >= th["cited_min"]]
    print(f"门槛 yjy>={th['yjy_min']} 且 cited>={th['cited_min']}：核心 {len(core)} 人")

    recs = []
    for x in core:
        # 姓名映射：先精确查，再归一化查
        cn = cfg["_name_cn"].get(x["name"], "")
        if not cn:
            cn = cfg["_name_cn_norm"].get(norm_name(x["name"]), "")
        dom = classify(x["sample_titles"], x["top_venues"], cfg["_domain_rules"])
        recs.append({
            "name_en": x["name"],
            "name_cn": cn,
            "openalex_id": (x["openalex_id"] or "").split("/")[-1],
            "orcid": x.get("orcid", ""),
            "domain": dom,
            "yjy_papers": x["yjy_papers"],
            "dual_aff": x.get("dual_aff_papers", 0),
            "total_cited": x["total_cited"],
            "year_min": x["year_min"], "year_max": x["year_max"],
            "top_venues": x["top_venues"][:3],
            "aff_evidence": x["aff_signatures"][:1],
            "key_works": [{"year": y, "title": t} for y, t in x["sample_titles"][:5]],
        })
    recs.sort(key=lambda r: (-r["total_cited"], -r["yjy_papers"]))

    out = outdir / f"{inst['short']}_core.json"
    out.write_text(json.dumps(recs, ensure_ascii=False, indent=1), encoding="utf-8")

    verified = sum(1 for r in recs if r["name_cn"])
    print(f"已核实中文姓名 {verified} / {len(recs)}，余 {len(recs) - verified} 待核实")
    print(f"⚠️ 被引是全作者共享累计（下界），不可用于精确排序")

    by = defaultdict(list)
    for r in recs:
        by[r["domain"]].append(r)
    print("\n=== 领域分布 ===")
    for d in sorted(by):
        print(f"\n## {d}  ({len(by[d])} 人)")
        for r in by[d]:
            cn = r["name_cn"] or "⚠️中文姓名待核"
            print(f"  {r['name_en'][:22]:22s} {cn:8s} yjy={r['yjy_papers']:2d} "
                  f"cited={r['total_cited']:4d} {r['year_min']}-{r['year_max']}")
    print(f"\nSAVED → {out}")


if __name__ == "__main__":
    main()
