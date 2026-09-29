#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""油田勘探开发研究院 · OpenAlex 中文作者分身消歧反查。

吃 fetch_institute.py 抓的 works 原始 json，按**字序无关**的归一化姓名分组，
找出「同一姓名 → 多个 author.id」的碎片化案例，输出诊断报告：
姓名变体、院署名篇数、被引、机构样本、代表作 top3、合作者共现 top8。

人工按三判据判定是否合并（合作者网络连通性+ 机构 + 主题一致性）。
本脚本只做诊断，不做自动合并——合并决策必须人眼过。

用法：
    python disambiguate.py --config institutes/daqing.json [--outdir out/daqing]
        [--names "Junhui Li,Cheng Wang"]   只看指定姓名（默认扫全部多分身姓名）
    python disambiguate.py --config ... --list-groups   只打分组清单，不写文件

输出：
    <outdir>/<short>_disambig.json    分身诊断报告

分组键用 author_identity.group_key（字符多重集，字序无关）。2026-09-29 换成
这个口径的原因：`Cai Jiexiong` / `Jiexiong Cai` / `Cai Jie-xiong` 在旧的
norm_name 下是三个不同键 → 同一专家裂成三片，每片论文数都够不上门槛，
专家凭空消失且不报错。group_key 把它们折叠成一把键。
⚠️ 折叠有副作用：`Wang Yang` 与 `Yang Wang` 也会被折叠，而这两个可能是
   两个人。所以分组结果**只用于摆证据给人看**，绝不自动合并。

⚠️ 三判据缺一不可，单一证据会把同名不同人错并。反证案例见
   references/institute-disambiguation.md。
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from author_identity import author_entity, group_key  # noqa: E402
from fetch_institute import build_matchers, is_institute  # noqa: E402


def load_config(path):
    """⚠️ 不要在本地重写院署名判定器——直接 import fetch_institute 的那一份。

    2026-09-29 踩过：这里原本是 copy 一份 is_yjy（只有 rival + city 两道约束），
    结果 fetch_institute.py 升级后加的 cross_group_tokens（第四道防线）和
    relax_city_constraint（城市约束开关）在这个副本里都不生效。同一套判定逻辑
    两份实现 = 迟早漂移，且漂移方向是「静默算错」。**唯一实现处 = 唯一正确性。**
    """
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    inst = cfg["institution"]
    ident = cfg["identify"]
    rival, yjy_en, yjy_cn, city, cross, relax_city = build_matchers(ident)

    def is_yjy(affs):
        return is_institute(affs, rival, yjy_en, yjy_cn, city, cross, relax_city)

    cfg["_is_yjy"] = is_yjy
    return cfg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--names", default=None, help="只看这些姓名（逗号分隔），默认全部")
    ap.add_argument("--list-groups", action="store_true",
                    help="只打分组清单（组名+片数+院署名篇数+被引），不写文件。"
                         "用于快速找出哪些组可能跨过门槛。")
    args = ap.parse_args()

    cfg = load_config(args.config)
    inst = cfg["institution"]
    outdir = Path(args.outdir) if args.outdir else Path(args.config).parent / f"out_{inst['short']}"
    works = json.loads(
        (outdir / f"{inst['short']}_works_raw.json").read_text(encoding="utf-8"))
    is_yjy = cfg["_is_yjy"]

    # entity_key → 聚合；entity_key = 真实 author.id，无 id 时为 `name:<归一化名>`
    by_id = defaultdict(lambda: {
        "name": "", "variants": Counter(), "yjy": 0, "cited": 0,
        "affs": Counter(), "titles": [], "coauthors": Counter(), "years": [],
        "orcid": "",
    })
    for w in works:
        cited = w.get("cited_by_count") or 0
        yr = w.get("publication_year") or 0
        title = (w.get("title") or "")[:110]
        authorships = w.get("authorships") or []
        # 先收集本篇所有作者名（用于合作者共现）
        all_names = [(a.get("author") or {}).get("display_name") or ""
                     for a in authorships]
        for a in authorships:
            ent = author_entity(a.get("author") or {})
            key = ent["entity_key"]
            name = ent["display_name"]
            affs = a.get("raw_affiliation_strings") or []
            if not affs:
                affs = [i.get("display_name", "") for i in a.get("institutions", [])]
            hit = is_yjy(affs)
            rec = by_id[key]
            rec["name"] = name
            rec["orcid"] = rec["orcid"] or ent["orcid"]
            rec["variants"][name] += 1
            if hit:
                rec["yjy"] += 1
                rec["cited"] += cited
                if yr:
                    rec["years"].append(yr)
                if len(rec["titles"]) < 4:
                    rec["titles"].append((yr, title))
                if affs:
                    rec["affs"][" | ".join(affs)[:160]] += 1
                # 合作者共现（排除自己）
                for n in all_names:
                    if n and n != name:
                        rec["coauthors"][n] += 1

    # 按归一化姓名分组（group_key 字序无关，见 author_identity docstring）
    groups = defaultdict(list)
    for key, r in by_id.items():
        if r["yjy"] > 0:
            groups[group_key(r["name"])].append(key)

    targets = None
    if args.names:
        targets = set(group_key(n.strip()) for n in args.names.split(","))

    multi = []
    for gname, keys in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if len(keys) < 2:
            continue
        if targets is not None and gname not in targets:
            continue
        recs = []
        for key in keys:
            r = by_id[key]
            ent = author_entity({"id": key if key.startswith("A") else None,
                                 "display_name": r["name"]})
            years = sorted(y for y in r["years"] if y)
            recs.append({
                # 字段语义与 fetch_institute / author_identity 对齐：
                # openalex_id 只放真A\d+，无 id 时为 None，另给 entity_key。
                "entity_key": key,
                "openalex_id": ent["openalex_id"],
                "id_missing": ent["id_missing"],
                "display_name": r["name"],
                "orcid": r["orcid"],
                "name_variants": [n for n, _ in r["variants"].most_common(6)],
                "yjy_papers": r["yjy"],
                "total_cited": r["cited"],
                "year_range": [min(years), max(years)] if years else [None, None],
                "aff_sample": [a for a, _ in r["affs"].most_common(2)],
                "top_works": [{"year": y, "title": t} for y, t in r["titles"]],
                "top_coauthors": [c for c, _ in r["coauthors"].most_common(10)],
            })
        recs.sort(key=lambda x: (-x["yjy_papers"], -x["total_cited"]))
        multi.append((gname, recs))

    if args.list_groups:
        print(f"多分身姓名组（院署名 ≥1 篇，group_key 字序无关口径）= {len(multi)} 组")
        print(f"{'group_key':16s} {'片':>3s} {'Σyjy':>5s} {'Σcited':>7s} {'Σabsorbed?':>10s}  代表名")
        for gname, recs in multi:
            sy = sum(r["yjy_papers"] for r in recs)
            sc = sum(r["total_cited"] for r in recs)
            names = sorted({r["display_name"] for r in recs if r["display_name"]})
            print(f"{gname:16s} {len(recs):3d} {sy:5d} {sc:7d} {'':>10s}  "
                  f"{' / '.join(names[:3])}")
        print("\n（Σ 为组内各片相加的**上界**——真实被引在合并后需重算，"
              "因为同一人被拆成多片时每片的被引不重叠）")
        return

    report = [{
        # ⚠️ 字段名 2026-09-29 修正：这里存的是 group_key（字符多重集），
        # 不是 norm_name。原来叫 norm_name，害得下游 merges.json 按
        # `yangwang` 写键、这边存 `aaggnnwy`，20 组决策键全部 MISS。
        # **字段名在骗人**和"值算错了"是两种 bug，后者有 traceback 可查，
        # 前者会让一整批人工决策静默失效。
        "group_key": gname,
        # 人读用的代表名：取片数最多的片子的原名，不参与匹配。
        "display_name": recs[0]["display_name"],
        "n_fragments": len(recs),
        "sum_yjy_papers": sum(r["yjy_papers"] for r in recs),
        "sum_cited_upper_bound": sum(r["total_cited"] for r in recs),
        "fragments": recs,
    } for gname, recs in multi]

    out = outdir / f"{inst['short']}_disambig.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"多分身姓名（院署名 ≥1 篇）共 {len(report)} 组")
    for g in report:
        print(f"\n### {g['group_key']}  [{g['display_name']}] — "
              f"{g['n_fragments']} 个实体")
        for f in g["fragments"]:
            yrs = f["year_range"]
            tag = f["entity_key"] if f["id_missing"] else f["openalex_id"]
            noid = "  [无id]" if f["id_missing"] else ""
            print(f"  {tag:26s} yjy={f['yjy_papers']:3d} "
                  f"cited={f['total_cited']:5d} {yrs[0]}-{yrs[1]}{noid}")
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
    print("\n⚠️ group_key 是字序无关的，会把『Wang Yang』和『Yang Wang』折叠成")
    print("   一组。所以本输出是**候选**，不是结论。")


if __name__ == "__main__":
    main()
