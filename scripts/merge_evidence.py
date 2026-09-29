#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""分身合并的三判据证据导出器 —— 用**全量**共作者集，不是 top10。

为什么必须单独写这个（2026-09-29 踩坑记录）
------------------------------------------------
第一次判合并时，我在一个临时探针脚本里算共作者重叠，输出「共同枢纽：无」，
差点把 8 组判成同名不同人。回头一查，那个脚本有两处错：

  1. `affs` 取的是上一个 for 循环残留的变量（最后一个 authorship 的机构），
     不是当前作者自己的机构 → 篇数与正式报告对不上
     （A5112928770 正式报告 12 篇，探针算 11 篇）。这种错误**不报错**，
     只是安静地给出偏小的数字。
  2. 只取 top10 共作者。10 是显示需要，不是判定需要；真枢纽排第 11 位的
     时候会被丢掉，于是「无重叠」这个结论是**探针的假象**。

教训：判据用的尺子必须和交付件用同一套判定函数。本脚本 import
fetch_institute.is_institute —— 院署名判定只有一个实现处。

三判据（缺一不可，单一证据会错并）
  1. 合作者网络：全量共作者集两两交集的大小。这是最强证据，也是最强反证。
     交集为 0 **不必然是同名不同人**（1 篇碎片本来就没几个合作者），
     但交集为 0 时必须靠另外两判据补足，缺一不可并。
  2. 机构：碎片署名是否都命中本院；出现异行业机构是强反证。
  3. 主题 + 年份：代表作是否落在同一条技术线上、时间是否连续可衔接。

额外两个「一票强证据」——命中即可单独定案：
  · ORCID 相同
  · 署名邮箱相同（OpenAlex raw_affiliation_strings 里带 E-mail: xxx）

用法：
    python merge_evidence.py --config institutes/sinopec_swty.json \
        --outdir out/sinopec_swty --groups acegiiijnox,ahnoquz
    python merge_evidence.py --config ... --outdir ... --candidates-only
        # 自动筛出「合并后才可能跨过门槛」的组（需要 roster + threshold）

输出：
    <outdir>/<short>_merge_evidence.json
"""
import argparse
import json
import sys
from collections import Counter, defaultdict  # noqa: E402
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from author_identity import author_entity, group_key  # noqa: E402
from fetch_institute import build_matchers, is_institute  # noqa: E402

EMAIL_RE = None  # 机构串里的邮箱用正则粗提，避免漏掉一票强证据


def find_emails(affs):
    import re
    out = []
    for s in affs or []:
        for m in re.findall(r"[\w.\-+]+@[\w.\-]+\.\w+", s or ""):
            if m.lower() not in {e.lower() for e in out}:
                out.append(m)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--groups", default=None,
                    help="逗号分隔的 group_key（字序无关归一化名）。字序不重要时直接给英文名。")
    ap.add_argument("--candidates-only", action="store_true",
                    help="不指定 --groups 时，自动只导出「Σ 篇数与 Σ 被引都够门槛」的组")
    ap.add_argument("--min-yjy", type=int, default=None, help="覆盖 config.threshold.yjy_min")
    ap.add_argument("--min-cited", type=int, default=None, help="覆盖 config.threshold.cited_min")
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    inst, ident = cfg["institution"], cfg["identify"]
    th = cfg.get("threshold", {})
    yjy_min = args.min_yjy or th.get("yjy_min", 2)
    cited_min = args.min_cited if args.min_cited is not None else th.get("cited_min", 30)
    outdir = Path(args.outdir) if args.outdir else Path(args.config).parent / f"out_{inst['short']}"
    works = json.loads(
        (outdir / f"{inst['short']}_works_raw.json").read_text(encoding="utf-8"))

    matchers = build_matchers(ident)

    # ---- 单遍全量聚合 -------------------------------------------------
    # 每篇：先算出全部 authorship 的身份与机构命中结果，再做共作者配对。
    # ⚠️ 机构命中必须在**本 authorship 自己的** affs 上算，不能复用循环残留变量。
    rec = defaultdict(lambda: {
        "name": "", "papers": [], "coauthors": set(), "emails": set(),
        "orcid": "", "affs": Counter(),
    })
    for w in works:
        authorships = w.get("authorships") or []
        ents, hits, affs_list = [], [], []
        for a in authorships:
            e = author_entity(a.get("author") or {})
            affs = a.get("raw_affiliation_strings") or []
            if not affs:
                affs = [i.get("display_name", "") for i in a.get("institutions", [])]
            ents.append(e)
            affs_list.append(affs)
            hits.append(is_institute(affs, *matchers))
        yr = w.get("publication_year")
        doi = w.get("doi")
        title = (w.get("title") or "")[:120]
        for i, e in enumerate(ents):
            if not hits[i]:
                continue
            r = rec[e["entity_key"]]
            r["name"] = r["name"] or e["display_name"]
            r["orcid"] = r["orcid"] or e["orcid"]
            r["papers"].append({"year": yr, "title": title, "doi": doi,
                                "cited": w.get("cited_by_count") or 0})
            for j, other in enumerate(ents):
                if j == i or not other["display_name"]:
                    continue
                if other["display_name"] == e["display_name"]:
                    continue
                r["coauthors"].add(group_key(other["display_name"]))
            r["emails"].update(find_emails(affs_list[i]))
            r["affs"][" | ".join(affs_list[i])[:180]] += 1

    # ---- 按 group_key 分组 --------------------------------------------
    groups = defaultdict(list)
    for key, r in rec.items():
        groups[group_key(r["name"])].append(key)

    if args.groups:
        wanted = set()
        for g in args.groups.split(","):
            g = g.strip()
            wanted.add(group_key(g) if g else g)
    else:
        wanted = None

    out_groups = []
    for gname, keys in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if len(keys) < 2:
            continue
        sy = sum(len(rec[k]["papers"]) for k in keys)
        sc = sum(p["cited"] for k in keys for p in rec[k]["papers"])
        if wanted is not None:
            if gname not in wanted:
                continue
        elif args.candidates_only or wanted is None:
            if not (sy >= yjy_min and sc >= cited_min):
                continue
        frs = []
        for k in sorted(keys, key=lambda k: -len(rec[k]["papers"])):
            r = rec[k]
            e = author_entity({"id": k if k.startswith("A") else None,
                               "display_name": r["name"]})
            yrs = [p["year"] for p in r["papers"] if p["year"]]
            frs.append({
                "entity_key": k,
                "openalex_id": e["openalex_id"],
                "id_missing": e["id_missing"],
                "display_name": r["name"],
                "orcid": r["orcid"],
                "emails": sorted(r["emails"]),
                "yjy_papers": len(r["papers"]),
                "cited": sum(p["cited"] for p in r["papers"]),
                "year_range": [min(yrs), max(yrs)] if yrs else [None, None],
                "n_coauthors": len(r["coauthors"]),
                "aff_samples": [a for a, _ in r["affs"].most_common(3)],
                "papers": r["papers"],
            })
        # 全量交集 + 两两交集矩阵（判定「有没有枢纽」不能只看全局交集：
        # 3 片时 A∩B 有共同枢纽但 A∩B∩C 可能为空，此时 C 是可疑片）
        inter_all = set.intersection(*[rec[k]["coauthors"] for k in keys]) \
            if len(keys) > 1 else set()
        pairwise = {}
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                a, b = rec[keys[i]]["coauthors"], rec[keys[j]]["coauthors"]
                pairwise[f"{keys[i]}|{keys[j]}"] = sorted(a & b)
        email_overlap = {}
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                a = {x.lower() for x in rec[keys[i]]["emails"]}
                b = {x.lower() for x in rec[keys[j]]["emails"]}
                if a & b:
                    email_overlap[f"{keys[i]}|{keys[j]}"] = sorted(a & b)
        orcid_overlap = {}
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                a, b = rec[keys[i]]["orcid"], rec[keys[j]]["orcid"]
                if a and b and a == b:
                    orcid_overlap[f"{keys[i]}|{keys[j]}"] = a
        out_groups.append({
            "norm_name": gname,
            "n_fragments": len(keys),
            "sum_yjy_papers": sy,
            "sum_cited_upper_bound": sc,
            "meets_threshold_if_merged": sy >= yjy_min and sc >= cited_min,
            "coauthor_intersection_all": sorted(inter_all),
            "coauthor_intersection_all_n": len(inter_all),
            "coauthor_pairwise": pairwise,
            "email_overlap": email_overlap,
            "orcid_overlap": orcid_overlap,
            "fragments": frs,
        })

    out = outdir / f"{inst['short']}_merge_evidence.json"
    out.write_text(json.dumps(out_groups, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"门槛 yjy>={yjy_min} 且 Σcited>={cited_min}；导出 {len(out_groups)} 组")
    for g in out_groups:
        print("=" * 96)
        print(f"### {g['norm_name']}  片={g['n_fragments']}  "
              f"Σyjy={g['sum_yjy_papers']}  Σcited={g['sum_cited_upper_bound']}  "
              f"合并后过门槛={g['meets_threshold_if_merged']}")
        print(f"  全量共作者交集 = {g['coauthor_intersection_all_n']} 个"
              f" {g['coauthor_intersection_all'][:12]}")
        if g["orcid_overlap"]:
            print(f"  ★ORCID 相同：{g['orcid_overlap']}")
        if g["email_overlap"]:
            print(f"  ★邮箱相同：{g['email_overlap']}")
        for f in g["fragments"]:
            tag = f["entity_key"] + ("  [无id]" if f["id_missing"] else "")
            print(f"  - {tag}  「{f['display_name']}」 yjy={f['yjy_papers']} "
                  f"cited={f['cited']} {f['year_range']} 共作者={f['n_coauthors']}")
            if f["emails"]:
                print(f"    邮箱: {f['emails']}")
            for a in f["aff_samples"][:2]:
                print(f"    机构: {a}")
            for p in f["papers"]:
                print(f"    {p['year']} {p['title'][:92]}")
        nz = {k: v for k, v in g["coauthor_pairwise"].items() if v}
        print(f"  两两共有的非空交集：{len(nz)} 对")
        for k, v in sorted(nz.items(), key=lambda kv: -len(kv[1]))[:8]:
            print(f"    {k} → {len(v)} 个 {v[:8]}")
    print(f"\nSAVED → {out}")


if __name__ == "__main__":
    main()
