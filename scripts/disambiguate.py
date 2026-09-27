#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""油田勘探开发研究院 · OpenAlex 中文作者分身消歧反查。

吃 fetch_institute.py 抓的 works 原始 json，按归一化姓名分组，
找出「同一姓名 → 多个 author.id」的碎片化案例，输出诊断报告：
姓名变体、院署名篇数、被引、机构样本、代表作 top3、合作者共现 top8。

人工按三判据判定是否合并（合作者网络连通性 + 机构 + 主题一致性）。
本脚本只做诊断，不做自动合并——合并决策必须人眼过。

用法：
    python disambiguate.py --config institutes/daqing.json [--outdir out/daqing]
        [--names "Junhui Li,Cheng Wang"]   只看指定姓名（默认扫全部多分身姓名）

输出：
    <outdir>/<short>_disambig.json    分身诊断报告

⚠️ 三判据缺一不可，单一证据会把同名不同人错并。反证案例见
   references/institute-disambiguation.md。
"""
import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


def norm_name(s):
    if not s:
        return ""
    s = "".join(ch for ch in s.lower() if not ch.isspace())
    return s.replace("-", "").replace(".", "").replace(",", "")


def load_config(path):
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    inst = cfg["institution"]
    ident = cfg["identify"]
    rival = re.compile("|".join(re.escape(t) for t in ident["rival_exclude_tokens"]), re.I)
    yjy_en = re.compile("|".join(ident["institute_patterns_en"]), re.I)
    yjy_cn = re.compile("|".join(ident["institute_patterns_cn"]), re.I)
    city = re.compile("|".join(re.escape(t) for t in ident["city_tokens"]), re.I)

    def is_yjy(affs):
        joined = " | ".join(affs or [])
        if not joined or rival.search(joined):
            return False
        cn, en = bool(yjy_cn.search(joined)), bool(yjy_en.search(joined))
        if not (cn or en):
            return False
        if en and not city.search(joined):
            return False
        if cn and not city.search(joined) and not yjy_en.search(joined):
            return False
        return True

    cfg["_is_yjy"] = is_yjy
    return cfg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--names", default=None, help="只看这些姓名（逗号分隔），默认全部")
    args = ap.parse_args()

    cfg = load_config(args.config)
    inst = cfg["institution"]
    outdir = Path(args.outdir) if args.outdir else Path(args.config).parent / f"out_{inst['short']}"
    works = json.loads(
        (outdir / f"{inst['short']}_works_raw.json").read_text(encoding="utf-8"))
    is_yjy = cfg["_is_yjy"]

    # author.id → 聚合；同时记录归一化姓名分组
    by_id = defaultdict(lambda: {
        "name": "", "variants": Counter(), "yjy": 0, "cited": 0,
        "affs": Counter(), "titles": [], "coauthors": Counter(), "years": [],
    })
    for w in works:
        cited = w.get("cited_by_count") or 0
        yr = w.get("publication_year") or 0
        title = (w.get("title") or "")[:100]
        authorships = w.get("authorships") or []
        # 先收集本篇所有作者名（用于合作者共现）
        all_names = [(a.get("author") or {}).get("display_name") or ""
                     for a in authorships]
        for a in authorships:
            author = a.get("author") or {}
            aid = author.get("id") or author.get("display_name") or "unknown"
            name = author.get("display_name") or ""
            affs = a.get("raw_affiliation_strings") or []
            if not affs:
                affs = [i.get("display_name", "") for i in a.get("institutions", [])]
            hit = is_yjy(affs)
            rec = by_id[aid]
            rec["name"] = name
            rec["variants"][name] += 1
            if hit:
                rec["yjy"] += 1
                rec["cited"] += cited
                if yr:
                    rec["years"].append(yr)
                if len(rec["titles"]) < 3:
                    rec["titles"].append((yr, title))
                if affs:
                    rec["affs"][" | ".join(affs)[:160]] += 1
                # 合作者共现（排除自己）
                for n in all_names:
                    if n and n != name:
                        rec["coauthors"][n] += 1

    # 按归一化姓名分组
    groups = defaultdict(list)
    for aid, r in by_id.items():
        if r["yjy"] > 0:
            groups[norm_name(r["name"])].append(aid)

    targets = None
    if args.names:
        targets = set(norm_name(n.strip()) for n in args.names.split(","))

    report = []
    for gname, aids in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if len(aids) < 2:
            continue
        if targets is not None and gname not in targets:
            continue
        recs = []
        for aid in aids:
            r = by_id[aid]
            years = sorted(y for y in r["years"] if y)
            recs.append({
                "openalex_id": (aid or "").split("/")[-1],
                "name_variants": [n for n, _ in r["variants"].most_common(4)],
                "yjy_papers": r["yjy"],
                "total_cited": r["cited"],
                "year_range": [min(years), max(years)] if years else [None, None],
                "aff_sample": [a for a, _ in r["affs"].most_common(2)],
                "top_works": [{"year": y, "title": t} for y, t in r["titles"]],
                "top_coauthors": [c for c, _ in r["coauthors"].most_common(8)],
            })
        report.append({
            "norm_name": gname,
            "n_fragments": len(aids),
            "fragments": recs,
        })

    out = outdir / f"{inst['short']}_disambig.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"多分身姓名（院署名 ≥1 篇）共 {len(report)} 组")
    for g in report:
        print(f"\n### {g['norm_name']} — {g['n_fragments']} 个 author.id")
        for f in g["fragments"]:
            yrs = f["year_range"]
            print(f"  {f['openalex_id']:15s} yjy={f['yjy_papers']:3d} "
                  f"cited={f['total_cited']:5d} {yrs[0]}-{yrs[1]}")
            print(f"    变体: {f['name_variants'][:3]}")
            print(f"    合作: {f['top_coauthors'][:5]}")
            tw = f["top_works"][0] if f["top_works"] else {"title": ""}
            print(f"    代表: {tw['title'][:70]}")
    print(f"\nSAVED → {out}")
    print("\n⚠️ 本脚本只诊断，不自动合并。按三判据人工判定：")
    print("   1. 合作者网络连通性（top_coauthors 有无共同枢纽）")
    print("   2. 机构（aff_sample 是否都命中本院）")
    print("   3. 主题一致性（top_works 是否同一方向）")
    print("   三者叠合才可并；合作者零重叠的同名分身判同名不同人。")


if __name__ == "__main__":
    main()
