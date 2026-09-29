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
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from author_identity import group_key, norm_name  # noqa: E402  身份/姓名口径唯一实现处
from cited_basis import resolve_cited_field  # noqa: E402  被引口径唯一裁决点


def name_keys(s):
    """返回姓名的**全部可接受键形式**：原名 + 姓/名互换形式。

    ⚠️ 2026-09-29 实测踩过：中文姓名映射文件里习惯写中文顺序（"刘定进"→键写
    `liu dingjin`），而 OpenAlex display_name 是西式顺序（`Dingjin Liu`）。
    norm_name 只做小写/去标点，**不统一姓与名的顺序**，于是
    `liudingjin` 永远匹配不上 `dingjinliu`——症状是「查名字查不到」，
    但脚本不报错、门槛判断照过、已核实人数显示 0，像「一个都没核实成功」
    而不是「键写错了」。这是沉默失败，不是失败。

    正解：查找时把两种顺序都试一遍。代价是同名歧义概率上升，
    所以匹配到多个不同中文名时必须硬报错，不能静默取第一个——
    那正是 user memory 里「CrossRef query.author 模糊匹配」那类污染。

    norm_name 已从 author_identity 导入，此处不再自定义，
    免得两处实现漂移（2026-09-29 统一）。
    """
    if not s:
        return []
    base = norm_name(s)
    out = [base]
    parts = [p for p in re.split(r"[\s\-.,]+", s.strip()) if p]
    if len(parts) == 2:
        out.append(norm_name(parts[1] + parts[0]))
    elif len(parts) > 2:
        out.append(norm_name("".join(parts[1:]) + parts[0]))
    # 中文顺序兜底：姓 + 名
    if parts:
        out.append(norm_name(parts[0] + "".join(parts[1:])))
    seen, uniq = set(), []
    for k in out:
        if k and k not in seen:
            seen.add(k)
            uniq.append(k)
    return uniq


def lookup_name_cn(cfg, name):
    """按多种键形式查中文姓名；命中多个不同中文名则硬报错。"""
    hits = set()
    for k in name_keys(name):
        v = cfg["_name_cn"].get(k) or cfg["_name_cn_norm"].get(k)
        if v:
            hits.add(v)
    if len(hits) > 1:
        sys.exit(
            f"❌ 姓名 {name!r} 匹配到多个不同中文名 {sorted(hits)}。\n"
            f"   说明 name_cn 映射里同一归一化键写了冲突的归属，"
            f"必须人工裁定后才能继续——否则会静默挑一个错的填进交付件。")
    return hits.pop() if hits else ""


def load_config(path):
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    base = Path(path).parent
    dr = cfg.get("domain_rules_file")
    nc = cfg.get("name_cn_file")
    cfg["_domain_rules"] = json.loads((base / dr).read_text(encoding="utf-8"))
    raw_nc = json.loads((base / nc).read_text(encoding="utf-8"))
    # 姓名映射的 value 有两种写法，2026-09-29 实测踩过不兼容：
    #   A) "Weihua Liu": "刘卫华"                —— 裸字符串
    #   B) "Liu Weihua": {"name_cn": "刘卫华", "source": [...]}  —— 带证据的字典
    # 早先只兼容 A，写 B 时 `cn = cfg["_name_cn"].get(name, "")` 拿到的是整个 dict，
    # 于是 name_cn 非空 → 「已核实 37/37」全绿，但值是 dict 不是姓名字符串。
    # 这是最典型的**假通过**：门槛判断的是真值，展示给人看的也是真值，
    # 只有类型不对——不报错、不崩、校验脚本也照样过。
    # 正解：这里统一归一成 str，证据另存到 _name_cn_evidence 供交付件引用。
    nc, ev = {}, {}
    for k, v in raw_nc.items():
        if k.startswith("_"):
            continue
        if isinstance(v, str):
            nc[k] = v
        elif isinstance(v, dict):
            cn = (v.get("name_cn") or "").strip()
            if cn:
                nc[k] = cn
                ev[cn] = v
        else:
            sys.exit(f"❌ name_cn 映射 {k!r} 的值类型非法：{type(v).__name__}，"
                     f"应为 str 或 dict")
    cfg["_name_cn"] = nc
    cfg["_name_cn_evidence"] = ev
    # 归一化后的姓名映射，避免大小写/连字符/姓名前后顺序差异导致漏匹配。
    #
    # ⚠️ 2026-09-29 修：原来用 setdefault，冲突时**后来者被静默丢弃**。
    # 症状是两个不同英文名归一到同一个键时，只有先写的那条生效，
    # 另一人的中文名永远匹配不上——而 name_cn 非空率只降不报，
    # 看起来像"这个人还没核实"，实际是"键冲突被吞了"。
    # 这跟 CrossRef query.author 模糊匹配是同一类病：
    # **归一化把不同的东西合并了，却不告诉你合并错了。**
    # 正解：归一化后若同一键对应不同中文名，硬报错要求人工裁定。
    cfg["_name_cn_norm"] = {}
    conflicts = {}
    for k, v in nc.items():
        for kk in name_keys(k):
            prev = cfg["_name_cn_norm"].get(kk)
            if prev is not None and prev != v:
                conflicts.setdefault(kk, set()).update({prev, v})
            else:
                cfg["_name_cn_norm"][kk] = v
    if conflicts:
        detail = "\n".join(f"   {kk} → {sorted(vs)}" for kk, vs in conflicts.items())
        sys.exit(f"❌ 中文姓名映射归一化后出现键冲突：\n{detail}\n"
                 f"   同一归一化键被两个不同中文名占用。不静默取第一个——"
                 f"那会把 A 的英文名配上 B 的中文名。请先在 "
                 f"{cfg.get('name_cn_file')} 里裁定。")
    return cfg


def classify(titles, venues, domain_rules):
    """按标题+期刊做领域归类。返回 (主领域, {全部命中方向: 命中数})。

    ⚠️ 必须跳过 `_` 前缀的键（2026-09-29 踩过）：domain_rules 文件里允许写
    `_note` / `_calibration` 之类的元数据说明，它们的值不是正则。直接
    `re.findall(p, ...)` 会把 `_note` 的整段中文当正则编译，抛
    `re.PatternError: nothing to repeat at position 0`（`_` 开头在正则里
    是非法量词）。症状是「领域规则一改就崩」，很容易误判成规则文件写错。

    ⚠️ 必须吃**全量**院署名标题（2026-09-29 踩过）：只吃 sample_titles
    （截断 8 条）时，一个 51 篇论文的作者只用 8 条做词频决胜负，
    跨方向词（"deep learning" 夹在地质建模标题里）被单一地质词压成
    非冠军，07(AI交叉) 在全量池 39 次命中却显示 0 人——看起来像
    "院里没人做 AI"，实际是采样丢信息。

    ⚠️ 返回全部命中方向而不是只返冠军（2026-09-29）：一个石油地质
    工程师的论文天然跨 03含油气系统/06非常规/07AI交叉，只给一个冠军
    会让跨方向的人凭空消失。下游要按单一方向统计就取 argmax，
    要看交叉能力就看 hits。
    """
    txt = " ".join((t or "") for _, t in titles) + " " + " ".join(venues or [])
    scores = {}
    for dom, pats in domain_rules.items():
        if dom.startswith("_"):
            continue
        if isinstance(pats, str):
            pats = [pats]
        n = sum(len(re.findall(p, txt, re.I)) for p in pats)
        if n:
            scores[dom] = n
    if not scores:
        return "未归类", {}
    best = max(scores.values())
    primary = sorted(d for d, n in scores.items() if n == best)[0]
    return primary, scores


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--roster", default=None,
                    help="吃哪份 roster。默认 <short>_roster.json（合并前）；"
                         "分身合并后应传 <short>_roster_merged.json，"
                         "否则同一个人会占两行，且被引是相加虚高值。")
    ap.add_argument("--out-suffix", default="",
                    help="输出文件名后缀。读合并后 roster 时用 _merged，"
                         "避免覆盖合并前的 core 造成口径混淆")
    args = ap.parse_args()

    cfg = load_config(args.config)
    inst = cfg["institution"]
    outdir = Path(args.outdir) if args.outdir else Path(args.config).parent / f"out_{inst['short']}"

    roster_path = Path(args.roster) if args.roster else outdir / f"{inst['short']}_roster.json"
    if not roster_path.exists():
        sys.exit(f"❌ 找不到 roster：{roster_path}")
    roster = json.loads(roster_path.read_text(encoding="utf-8"))
    n_absorbed = sum(1 for r in roster if r.get("absorbed_into"))
    if roster_path.name.endswith("_roster_merged.json"):
        print(f"roster = {roster_path.name}（已应用人工合并决策）")
    else:
        print(f"roster = {roster_path.name}（合并前 —— 同一人的分身会各占一行）")
        if n_absorbed == 0:
            print("  ⚠️ 若已跑过 apply_merges.py，请加 --roster <outdir>/"
                  f"{inst['short']}_roster_merged.json，否则名单里会有重复人")
    th = cfg.get("threshold", {"yjy_min": 2, "cited_min": 30})
    # ⚠️ 门槛的被引口径由 cited_basis.py 唯一裁决，**不要在这里重写字面量
    # 词表**（2026-09-29 踩过：fetch 认 all|yjy、distill 认 total|yjy，
    # 同一个配置键一个报错一个静默 fallback）。
    #
    # 为什么默认 yjy：名单是"院的人"，门槛必须与名单同口径。用宽口径卡门槛
    # = 拿该作者挂在别家单位时被引的业绩给自己院发名单。西南院实测 938 人里
    # 266 人两口径不等，最极端 Jianfa Wu 院署名被引 6、total_cited 1908
    # （那 1902 引自页岩气院与外院合作，跟院本部没关系）。
    basis, field = resolve_cited_field(th)
    n_drift = sum(1 for x in roster
                  if x["total_cited"] != x.get("yjy_cited", 0))
    print(f"门槛被引口径 = {field}（cited_basis={basis}，来自 cited_basis.py）")
    print(f"  两口径漂移 = {n_drift}/{len(roster)} 人（total_cited != yjy_cited）")
    if basis == "all":
        print(f"  ⚠️ 宽口径模式：门槛含外单位被引，院口径核心只有 "
              f"{sum(1 for x in roster if x['yjy_papers'] >= th.get('yjy_min', 2) and x['yjy_cited'] >= th.get('cited_min', 30))} 人。"
              f"报告里必须同时给出两口径对照。")

    core = [x for x in roster
            if x["yjy_papers"] >= th.get("yjy_min", 2)
            and x.get(field, 0) >= th["cited_min"]]
    print(f"门槛 yjy>={th.get('yjy_min',2)} 且 {field}>={th.get('cited_min',30)}："
          f"核心 {len(core)} 人")

    recs = []
    merge_note = {}
    mp = outdir / f"{inst['short']}_merges.json"
    if mp.exists():
        mj = json.loads(mp.read_text(encoding="utf-8"))
        for grp, d in (mj.get("merge") or {}).items():
            # 键统一用 group_key（字序无关的多重集）。旧代码用 norm_name，
            # 是顺序敏感的：`Cai Jiexiong` 和 `Jiexiong Cai` 会落进两个
            # 不同的 merge_note 键，于是"这两个片合并过了"这条说明
            # 挂不上去——**合并做了，记录没挂上**，报告里看不到。
            # 副作用（Wang Yang / Yang Wang 折叠）在此处无害：
            # merges.json 的一组本来就该合并，把它折叠到同一桶是想要的。
            merge_note[group_key(grp)] = d

    # ---- newly_admitted_by_merge：谁是因为「合并」才进的门槛 ----
    # 判据不是"这行有 merged_from"（那是合并过，不等于合并后才够门槛），
    # 而是：**把被并的碎片拆回去，逐片都够门槛吗？**
    #   全部够 → 合并前就在核心，合并只是去重（newly = False）；
    #   全部不够 → 合并后才够门槛，合并**改变了他的入选结论**（newly = True）。
    # 这个字段回答"名册↔核心差异里，有几个人是靠分身合并捞回来的"，
    # 答不了这个问题就无法审计门槛口径。
    #
    # ⚠️ 必须吃**合并前**名册（<short>_roster.json）才推得出来；缺它时字段
    #   留空不猜。猜错的后果是把"靠合并才达标的人"说成"本来就在名单里"，
    #   直接把名单解读引到错误方向。
    # 实测 sinopec_swty：15 个合并行里 **4 行 newly=True**
    # （Jie Wang / Hui Zhang / Kai Xu / Lixin Wang），其余 11 行 False。
    pre_roster_p = outdir / f"{inst['short']}_roster.json"
    pre_by_key = {}
    if pre_roster_p.exists():
        pre_by_key = {r["entity_key"]: r for r in
                      json.loads(pre_roster_p.read_text(encoding="utf-8"))}

    def passes(r):
        return (r["yjy_papers"] >= th.get("yjy_min", 2)
                and r.get(field, 0) >= th["cited_min"])

    admitted_by_merge = 0
    for x in core:
        # 姓名映射：多键形式查找，冲突则硬报错（见 lookup_name_cn）
        cn = lookup_name_cn(cfg, x["name"])
        dom, hits = classify(
            x.get("all_yjy_titles") or x["sample_titles"],
            x["top_venues"], cfg["_domain_rules"])
        # 分身合并证据：把「已被判定合并的其他 openalex_id」挂到该行
        mg = merge_note.get(group_key(x["name"]), {})
        rec = {
            "name_en": x["name"],
            "name_cn": cn,
            "openalex_id": (x["openalex_id"] or "").split("/")[-1],
            "orcid": x.get("orcid", ""),
            "domain": dom,
            "domain_hits": dict(sorted(hits.items(), key=lambda kv: -kv[1])),
            "yjy_papers": x["yjy_papers"],
            "dual_aff": x.get("dual_aff_papers", 0),
            "total_cited": x["total_cited"],
            "yjy_cited": x.get("yjy_cited", 0),
            "year_min": x["year_min"], "year_max": x["year_max"],
            "top_venues": x["top_venues"][:3],
            "aff_evidence": x["aff_signatures"][:1],
            "key_works": [{"year": y, "title": t} for y, t in x["sample_titles"][:5]],
        }
        if cn and cn in cfg.get("_name_cn_evidence", {}):
            ev = cfg["_name_cn_evidence"][cn]
            rec["name_cn_source"] = ev.get("source", [])[:3]
            rec["name_cn_verify"] = ev.get("verify", "")
        if mg:
            rec["merged_ids"] = [i for i in (mg.get("absorb") or [])
                                 if not i.startswith("__")]
            rec["disambig_note"] = mg.get("evidence_reason", "")
            rec["disambig_verify"] = mg.get("verify", "")
            if mg.get("exclude"):
                rec["disambig_excluded"] = mg["exclude"]
                rec["disambig_exclude_reason"] = mg.get("exclude_reason", "")
        # 合并器已把去重重算结果写进 roster 行，合并后这里能直接读到
        # 完整的合并溯源（比只挂 absorb 列表更准：absorb 里可能有 exclude 掉的片）。
        if x.get("merged_from") and len(x["merged_from"]) > 1:
            rec["merged_from"] = x["merged_from"]
            sb = x.get("sum_before_dedup")
            if sb:
                rec["dedup_check"] = {
                    "sum_before_dedup_yjy_cited": sb.get("yjy_cited"),
                    "after_dedup_yjy_cited": x.get("yjy_cited"),
                    "delta": x.get("yjy_cited", 0) - sb.get("yjy_cited", 0),
                }
            # 合并前每一片各自够不够门槛？全够 = 合并只去重；全不够 = 合并
            # 才让他够门槛。拿不到合并前名册时留 None，不猜。
            if pre_by_key:
                frags = [pre_by_key[k] for k in x["merged_from"]
                         if k in pre_by_key]
                if frags:
                    rec["newly_admitted_by_merge"] = not any(passes(f)
                                                            for f in frags)
                    if rec["newly_admitted_by_merge"]:
                        admitted_by_merge += 1
        recs.append(rec)
    # 排序跟门槛用同一个口径，否则「按 yjy_cited 卡门槛、按 total_cited 排序」
    # 会让榜单头部全是外单位高被引的人，门槛形同虚设。
    recs.sort(key=lambda r: (-r.get(field, r["total_cited"]), -r["yjy_papers"]))

    out = outdir / f"{inst['short']}_core{args.out_suffix}.json"
    out.write_text(json.dumps(recs, ensure_ascii=False, indent=1), encoding="utf-8")

    verified = sum(1 for r in recs if r["name_cn"])
    print(f"已核实中文姓名 {verified} / {len(recs)}，余 {len(recs) - verified} 待核实")
    n_merged = sum(1 for r in recs if r.get("merged_from"))
    if n_merged:
        print(f"合并行 {n_merged} 人，其中因合并才够门槛（newly_admitted）"
              f"{admitted_by_merge} 人")
        print("  判据：把被并碎片逐片拆回合并前名册，若每片都不够门槛，"
              "则合并改变了他的入选结论")
    print(f"⚠️ 被引是全作者共享累计（下界），不可用于精确排序")

    by = defaultdict(list)
    for r in recs:
        by[r["domain"]].append(r)
    print("\n=== 领域分布（主领域，argmax 口径）===")
    for d in sorted(by):
        print(f"\n## {d}  ({len(by[d])} 人)")
        for r in by[d]:
            cn = r["name_cn"] or "⚠️中文姓名待核"
            print(f"  {r['name_en'][:22]:22s} {cn:8s} yjy={r['yjy_papers']:2d} "
                  f"cited={r.get(field, r['total_cited']):4d} "
                  f"{r['year_min']}-{r['year_max']}")

    # 交叉方向统计：一个人可同时算进多个方向，与 argmax 主领域互不排斥。
    cross = defaultdict(list)
    for r in recs:
        for d in r["domain_hits"]:
            cross[d].append(r["name_en"])
    print("\n=== 交叉方向覆盖（可重复计入，一人可属多方向）===")
    for d in sorted(cross):
        print(f"  {len(cross[d]):3d} 人  {d}")
    print(f"\nSAVED → {out}")


if __name__ == "__main__":
    main()
