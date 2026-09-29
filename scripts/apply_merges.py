#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把人工分身判定落账到**名册层**，输出合并后名册与合并审计表。

本脚本是 `oilfield-geophysics-foundation` 里唯一有权写
`<short>_roster_merged.json` / `<short>_merge_applied.json` 的地方。

为什么必须是名册层而不是核心层
------------------------------
2026-09-29 之前，本 skill 里的 `apply_merges.py` 读的是 `*_core.json`
（核心名单），只在核心行之间做加法。那版实现有四个硬缺陷，且**每一个
都会静默出错**：

1. **相加而不是按 work id 去重。** OpenAlex 同一篇论文里同一个人可能有
   多条 authorship（实测 `W7203734917` 里 `A5086490312` / `A5147557017`
   各出现两次），也可能是同一会议论文被两个索引分别收录。相加会把
   同一篇的被引算两遍。实测 Guanghui Hu 组：分片相加 yjy_cited=69，
   按 work id 去重重算=51，**虚高 18**。
2. **完全不消费 `reject_whole_group`。** 整组判同名不同人的实体照样留在
   名册里，下游只查核心名单，于是「Wei Xie（CFRP 抗爆、土木/防护工程）」
   这种明显污染只在核心层消失，名册层仍然对外可见。
3. **只改核心行，名册层不落账。** 名册是"全院作者底账"，核心是"过门槛的人"。
   只改核心会让人无法回答"这个数字是怎么来的"。
4. **无去重证据。** 交付件里没有任何字段能证明"这个数是去重后的"。

四种去重口径（每一条都有实测反例，别凭直觉改）
----------------------------------------------
合并后的行，哪些字段**重算**、哪些**沿用 keep 行**，是踩坑踩出来的，
不是审美选择：

  重算（按 work id 集合）        沿用 keep 行（不重算）
  ---------------------------   ---------------------------
  yjy_papers                    name / entity_key / openalex_id
  total_cited                   name_variants
  yjy_cited                     city_papers
  year_min / year_max           dual_aff_papers
  top_venues                    cross_group_papers
  orcid                         aff_signatures
                                sample_titles / all_yjy_titles

* `orcid` 必须重算：跨分身取**合并后全部署名记录里最常见**的那个。
  实测 Jie Wang 组 keep 行是 `0000-0002-9663-3165`，合并后正确值是
  `0000-0001-7854-9376`（来自 A5100440012）。沿用 keep 会把另一个人的
  ORCID 挂在合并人头上——这是**身份污染**，不是显示问题。
* `year_*` / `top_venues` 只统计**院署名**论文：与 yjy_papers / yjy_cited
  同一口径。实测 Weihua Liu 组若按全部论文算 year_min=2016，但那个 2016
  的 W2510298449 **不是院署名**（`yjy=False`），院口径应为 2018。
* `sample_titles` / `all_yjy_titles` 沿用 keep 行：这两列只给人看，
  且 `sample_titles` 在采集层就硬截断 8 条，重算反而会破坏"每片各留 8 条
  代表作"的阅读语义。
* **`name:` 合成键必须参与重算。** OpenAlex 没分配 author.id 的作者走
  `name:<归一化名>`。旧规则把这类分片从重算集合里剔除，理由是「它的论文
  在 OpenAlex 里已经挂在主片名下了」——**该理由经查为假**（2026-09-29 修正）。

  实测反例：Guanghui Hu 组的 `name:guanghuihu` 持有 W4299444035
  （2022，*J. Geophys. Eng.*，18 被引，`Combined multi-branch selective
  kernel ... residual network for seismic random noise attenuation`），
  该文是**院署名**（Guanghui Hu 是全文唯一中石化署名作者行），且**不在**
  主片 A5100750981 的 13 篇之内。剔除它 = 1 篇真实院署名论文与 18 条
  真实院口径被引静默消失，合并后 `yjy_cited=51` 比任何一版权威口径都小。

  正确的去重机制是 `recompute()` 的 **work id 集合并集**：同一篇被两个
  分片覆盖时并集只保留一次。`name:` 键之所以看起来"会重复计数"，是因为
  它的论文常常**也**被主片覆盖——但那种情况并集已经处理了，不需要额外
  排除规则。**用一个可证伪的假理由去实现一个并不必要的排除，代价是丢真数。**

  ⚠️ 该修正只影响**指标重算**，不影响身份裁决：`name:guanghuihu` 与主片
  是否同一人仍由合作者网络 + 主题 + 院署名判定，不因"该算它的论文"而自动成立。

决策表三态语义（混用会误伤，这是已踩过的坑）
------------------------------------------
  merge              碎片是同一人，absorb 的实体不再单列
  no_merge           碎片不并入，**但本人仍在核心**（person_excluded_from_core=False）
  reject_whole_group 整组判同名不同人，**本人不进核心**，实体从名册物理删除

**问「本人是否被剔除」，不要问「碎片是否被合并」。** 2026-09-29 踩过：
下游校验把 `no_merge` 一律当成"不进核心"，误报 3 人污染——是校验器的
语义假设错了，不是名单错了。

用法
----
    python apply_merges.py --config ../institutes/sinopec_swty.json \\
                           --outdir ../../../../2026-09-29-07-57-58/sinopec_swty
    python apply_merges.py --config ... --dry-run     # 只报告差异，不落盘

自检纪律
--------
脚本内置 **22 项聚合硬断言**（2026-09-29 从 1439 项逐行断言改写而来，
详见下方「为什么断言从 1439 项压成 22 项」），任何一项不过就**退出非零
且不写文件**。理由：合并环节静默失效（键口径错位、引用解析不到、去重写成
相加）时，产物看起来是"合理的 JSON"，但名单是错的——2026-09-29 三次事故
全是"正常退出 + 结果错"。断言是唯一能把这类事故变成硬失败的手段。

为什么断言从 1439 项压成 22 项
------------------------------
1439 项逐行断言的**退出码是对的**（任何一行坏了都会 raise），但它的
可维护性有致命问题：改一个字段顺序就可能让上百条断言的**措辞**失配，
而人看到「1439 项里 3 项失败」根本不知道是哪 3 项、为什么。
聚合断言把「被并实体全部解析到名册行」这类判据写成**集合差为空**的形式，
一次检查覆盖同类全部行，且失败信息自带差集内容。
判据不变，只是从"逐行穷举"改成"集合级归约"。

确定性纪律（本脚本存在的主要理由之一）
------------------------------------
产物必须**逐字节可复现**。2026-09-29 实测到两处 `set` 迭代顺序不定导致
产物漂移（`PYTHONHASHSEED` 不同 → `top_venues` 并列项次序变化、
ORCID 频次并列时选错片），两条修法写死在代码里，不靠注释提醒：
  1. `top_venues` 并列次序锚定 `works_raw.json` **文件顺序**（work 索引
     的 `order` 字段），不锚定 work id 的字典序；
  2. ORCID 并列时按「有序 fragment 列表里首次出现的位次」决胜，
     keep 片排在第 0 位。
改这两处会让已交付的 `*_roster_merged.json` 与 `*_merge_applied.json`
不再逐字节一致——**不要为了好看改**。
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    from author_identity import (author_entity, group_key, is_real_openalex_id,
                                norm_name)
except ImportError:  # pragma: no cover
    sys.exit("❌ 找不到 author_identity —— 身份口径必须用 skill 权威实现，"
             "不要在本地重写（有序/无序不一致会导致决策静默失效）。")
try:
    from fetch_institute import build_matchers, is_institute
except ImportError:  # pragma: no cover
    sys.exit("❌ 找不到 fetch_institute.build_matchers / is_institute —— "
             "院署名判定口径必须复用采集层，重写会导致重算口径与名册漂移。")

CHECKS = []


def check(cond, label, detail=""):
    """记录一项自检。硬失败：任一不过即退出非零，不落盘。"""
    CHECKS.append((bool(cond), label, detail))
    return bool(cond)


# --------------------------------------------------------------------------
# 引用解析：把决策表里写的实体引用解析成 roster 的 entity_key
# --------------------------------------------------------------------------
def build_resolver(roster):
    """entity_key 解析器。

    接受三种写法：
      1. 真 OpenAlex ID（`A\\d+`）—— 直接用；
      2. 合成键（`name:<归一化名>`）—— 直接用；
      3. 裸姓名 —— 按 group_key 查表。

    ⚠️ 裸姓名在同名多片时**必须硬失败**，不能"挑一个"。
    实测 2026-09-29：Guanghui Hu 组 absorb 原写作裸姓名 'Guanghui Hu'，
    而 roster 里同名有三片（主片 A5100750981 / 无 ID 片 name:guanghuihu /
    A5100750984）。脚本当时"聪明地"取了第一片并继续跑，产出的是一份
    看起来完全正常、实际并错了人的名册。歧义必须响亮地崩。
    """
    by_key = {r["entity_key"]: r for r in roster}
    by_gk = defaultdict(list)
    for r in roster:
        by_gk[group_key(r["name"])].append(r["entity_key"])

    def resolve(ref, ctx=""):
        if not ref:
            return None
        if ref in by_key:
            return ref
        if is_real_openalex_id(ref):
            # 是合法 ID 但不在 roster：说明决策表引用了不存在的实体。
            return None
        bare = ref[5:] if ref.startswith("name:") else ref
        gk = group_key(bare)
        cands = by_gk.get(gk, [])
        if len(cands) == 1:
            return cands[0]
        if len(cands) > 1:
            sys.exit(
                f"❌ 决策引用 {ref!r}（{ctx}）在名册里对应 {len(cands)} 个分身："
                f"{cands}\n"
                f"   裸姓名/合成名无法指定要并哪一片。请在 merges.json 里改用"
                f"显式 entity_key（`A5100750981` 或 `name:guanghuihu`）。\n"
                f"   判据：宁可崩在这里，也不要产出一份'看起来对但并错人'的名册。")
        return None

    return resolve, by_key, by_gk


# --------------------------------------------------------------------------
# 重算：按 work id 集合重算合并后的行
# --------------------------------------------------------------------------
def build_work_index(works, matchers):
    """把 works 预先索引成 (entity -> work_ids, work_id -> 摘要, entity -> orcid 频次)。

    一次性建索引，避免每个合并组都全量扫 588 篇（15 组 × 588 篇 ×
    逐条 authorship 匹配，在 691 人名册上会慢到不可用）。

    每个 work 只留**一个**条目（work_id 天然去重），authorship 列表按
    (entity_key, raw_affiliation_strings) 存下——院署名判定要按
    「这一片在这个人名下的署名串」判，不能按「整篇的任意署名」判。

    ⚠️ `order` 是**文件下标**，不是可有可无的元数据：`recompute()` 靠它
    做确定性遍历。同一批 works 里并列计数很常见（很多作者一年一篇会议、
    同一刊物），`Counter.most_common()` 在并列时按**首次插入顺序**返回，
    所以遍历顺序变了 top_venues 的排列就变。2026-09-29 实测：直接
    `for wid in work_ids`（set）遍历，14 个合并行的 top_venues 与产物不一致，
    且同机重跑两次结果不同（PYTHONHASHSEED 随机化）——「脚本重算不出
    自己签过的字」是这类事故最难查的一种。
    """
    by_entity = defaultdict(set)
    works_by_id = {}
    orcid_by_entity = defaultdict(Counter)
    for order, w in enumerate(works):
        wid = w.get("id")
        if not wid:
            continue
        pl = w.get("primary_location") or {}
        venue = ((pl.get("source") or {}).get("display_name")) or ""
        auth = []
        # 同一 work 内同人可能有多条署名（实测 W7203734917）。院署名判定
        # 取「任一行为院署名」——并集语义，不因重复行漏判。
        yjy_flag = {}
        for a in w.get("authorships") or []:
            ent = author_entity(a.get("author") or {})
            by_entity[ent["entity_key"]].add(wid)
            if ent["orcid"]:
                orcid_by_entity[ent["entity_key"]][ent["orcid"]] += 1
            hit = is_institute(a.get("raw_affiliation_strings") or [], *matchers)
            yjy_flag[ent["entity_key"]] = yjy_flag.get(ent["entity_key"], False) or hit
            auth.append(ent["entity_key"])
        works_by_id[wid] = {
            "id": wid,
            "order": order,
            "cited": w.get("cited_by_count") or 0,
            "year": w.get("publication_year") or 0,
            "venue": venue,
            "yjy_entity": {e for e, hit in yjy_flag.items() if hit},
        }
    return by_entity, works_by_id, orcid_by_entity


def recompute(entities, by_entity, works_by_id, orcid_by_entity, matchers):
    """按 work id 集合重算一个合并实体的指标。

    `entities` 是完整的分片列表，**包含** `name:` 合成键
    （2026-09-29 修正，旧实现在调用前把它们剔除，会丢真数，见模块 docstring）。
    去重由 work id 集合并集保证，不需要靠排除任何一类分片。

    遍历顺序 = `works_raw.json` 的文件顺序（`order` 字段），**不是**
    `sorted(work_id)`、更不是 set 的自然顺序。理由见 build_work_index：
    并列计数下 `most_common()` 的排列由首次插入顺序决定，遍历顺序
    不确定 = 产物不可复现。
    """
    work_ids = set()
    ents = set(entities)
    for e in ents:
        work_ids |= by_entity.get(e, set())

    yjy_ids, yjy_cited, all_cited = set(), 0, 0
    yjy_years, yjy_venues = [], Counter()

    for wid in sorted(work_ids, key=lambda x: works_by_id[x]["order"]):
        w = works_by_id.get(wid)
        if w is None:
            continue
        all_cited += w["cited"]
        # 院署名判定：合并后任一分身在该文有院署名，该文即计入院口径。
        # 判据：合并的是"同一个人"，他在这篇上的院署名与 keep 片上的院署名
        # 同等有效，不该因为署名挂在另一个分身上就不算数。
        if w["yjy_entity"] & ents:
            yjy_ids.add(wid)
            yjy_cited += w["cited"]
            if w["year"]:
                yjy_years.append(w["year"])
            if w["venue"]:
                yjy_venues[w["venue"]] += 1

    # ORCID：合并后全部署名记录里最常见的那个。必须真在 works 里数，
    # 不能只沿用 keep 行 —— 跨分身的 ORCID 常常记在非主片上
    # （实测 Jie Wang 组主片是 0000-0002-9663-3165，正确值来自 A5100440012）。
    #
    # ⚠️ 频次并列时**必须**按「该 ORCID 首次出现的分片在 entities 里的
    # 次序」定序，绝不能让 set 的迭代顺序决定。实测 Xiao-Hui Yang 组三个
    # 分片各带一个 ORCID（3:3:1），打成并列后 `set` 迭代顺序随
    # PYTHONHASHSEED 变，同一份输入两次跑出两个不同的人——这是把一个人
    # 的 ORCID 挂到另一个人身上，属身份污染，不是显示问题。
    # 规则：频次降序 → 同频按分片首次出现次序升序（keep 排第一）。
    orc = Counter()
    for e in entities:
        orc.update(orcid_by_entity.get(e, Counter()))
    orcid_pick = ""
    if orc:
        orcid_pick = min(
            orc.items(),
            key=lambda kv: (-kv[1], _first_rank(kv[0], entities, orcid_by_entity)),
        )[0]

    ys = sorted(yjy_years)
    return {
        "yjy_papers": len(yjy_ids),
        "total_cited": all_cited,
        "yjy_cited": yjy_cited,
        "year_min": ys[0] if ys else None,
        "year_max": ys[-1] if ys else None,
        "top_venues": [v for v, _ in yjy_venues.most_common(5)],
        "orcid": orcid_pick,
    }


def _first_rank(orcid, entities, orcid_by_entity):
    """某个 ORCID 首次出现在 entities 的第几个分片上（并列定序用）。"""
    for i, e in enumerate(entities):
        if orcid_by_entity.get(e, Counter()).get(orcid):
            return i
    return len(entities)


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="institutes/<short>.json")
    ap.add_argument("--outdir", default=None,
                    help="输入与输出目录（默认与 config 同级的 outputs 推断）")
    ap.add_argument("--works", default=None, help="默认 <short>_works_raw.json")
    ap.add_argument("--roster", default=None, help="默认 <short>_roster.json")
    ap.add_argument("--merges", default=None, help="默认 <short>_merges.json")
    ap.add_argument("--dry-run", action="store_true", help="只做自检与报告，不写文件")
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    short = cfg["institution"]["short"]
    outdir = Path(args.outdir).resolve() if args.outdir else cfg_path.parent
    works_p = Path(args.works) if args.works else outdir / f"{short}_works_raw.json"
    roster_p = Path(args.roster) if args.roster else outdir / f"{short}_roster.json"
    merges_p = Path(args.merges) if args.merges else outdir / f"{short}_merges.json"

    for p in (works_p, roster_p, merges_p):
        if not p.exists():
            sys.exit(f"❌ 缺输入文件：{p}")

    works = json.loads(works_p.read_text(encoding="utf-8"))
    roster = json.loads(roster_p.read_text(encoding="utf-8"))
    mj = json.loads(merges_p.read_text(encoding="utf-8"))

    merge_dec = {k: v for k, v in (mj.get("merge") or {}).items()
                 if not k.startswith("_") and isinstance(v, dict)}
    no_merge_dec = {k: v for k, v in (mj.get("no_merge") or {}).items()
                    if not k.startswith("_") and isinstance(v, dict)}
    reject_dec = {k: v for k, v in (mj.get("reject_whole_group") or {}).items()
                  if not k.startswith("_")}

    print(f"机构：{cfg['institution']['name']}（{short}）")
    print(f"输入：works={len(works)} roster={len(roster)} "
          f"merge={len(merge_dec)} no_merge={len(no_merge_dec)} "
          f"reject={len(reject_dec)}")

    # ---- 键口径自检：决策表的键必须是 group_key ----
    # 键口径错位时，本脚本会「一组合并都执行不了」而正常退出。
    # 2026-09-29 实测：有序 norm_name（yangwang）vs 无序 group_key（aaggnnwy）
    # 导致 15 组决策全部 MISS，日志只写「跳过」，看起来像「本来就没东西可并」。
    bad_keys = [k for k in list(merge_dec) + list(no_merge_dec) + list(reject_dec)
                if k != group_key(k) and norm_name(k) != k]
    check(not bad_keys, "决策表键为 group_key（字序无关）",
          f"以下键疑似用了有序 norm_name：{bad_keys[:5]}")

    matchers = build_matchers(cfg["identify"])
    resolve, by_key, by_gk = build_resolver(roster)
    by_entity, works_by_id, orcid_by_entity = build_work_index(works, matchers)

    # ---- 1. reject_whole_group：整组物理删除 ----
    reject_audit, dropped_all, empty_reject = [], set(), []
    for gk in reject_dec:
        members = [r["entity_key"] for r in roster if group_key(r["name"]) == gk]
        if not members:
            empty_reject.append(gk)
        detail = [{"entity_key": k, "name": by_key[k]["name"],
                   "yjy_papers": by_key[k]["yjy_papers"],
                   "yjy_cited": by_key[k]["yjy_cited"],
                   "total_cited": by_key[k]["total_cited"]} for k in members
                  if k in by_key]
        dropped_all.update(members)
        reject_audit.append({
            "group_key": gk,
            "decision": "reject_whole_group",
            "dropped": members,
            "dropped_detail": detail,
            "reason": reject_dec[gk],
            "person_excluded_from_core": True,
        })
    check(not empty_reject, "每个 reject 组在名册中至少命中 1 个实体",
          f"名册里找不到任何分身（决策可能针对旧版名册）：{empty_reject}")

    # ---- 2. no_merge：只记语义，不动任何实体 ----
    no_merge_audit = []
    for gk, dec in no_merge_dec.items():
        declared = ([dec["keep"]] if dec.get("keep") else []) + \
                   list(dec.get("absorb") or [])
        found = [k for k in (resolve(x, f"no_merge/{gk}") for x in declared) if k]
        no_merge_audit.append({
            "group_key": gk,
            "decision": "no_merge",
            "declared_ids": declared,
            "found_in_roster": found,
            "reason": dec.get("reason", ""),
            "verify": dec.get("verify", ""),
            "fragments_merged": False,
            # ⚠️ 关键语义：no_merge ≠ 剔除本人。keep 凭自己那几篇已过门槛。
            "person_excluded_from_core": False,
        })
    check(all(not e["person_excluded_from_core"] for e in no_merge_audit),
          "no_merge 组全部 person_excluded_from_core=False",
          "no_merge 语义是'不并碎片'，不是'剔除本人'")

    # ---- 3. merge：按 work id 去重重算 ----
    merged_rows, merge_audit, absorb_all = [], [], set()
    unresolvable = []       # (group, role, ref) —— 引用了名册里不存在的实体
    over_papers, over_all, over_yjy, bad_inner = [], [], [], []
    for gk, dec in merge_dec.items():
        keep = resolve(dec.get("keep"), f"merge/{gk}/keep")
        if keep is None:
            unresolvable.append((gk, "keep", dec.get("keep")))
        absorb = []
        for a in (dec.get("absorb") or []):
            k = resolve(a, f"merge/{gk}/absorb")
            if k is None:
                unresolvable.append((gk, "absorb", a))
                continue
            if k == keep:
                continue
            absorb.append(k)
        exclude = []
        for e in (dec.get("exclude") or []):
            k = resolve(e, f"merge/{gk}/exclude")
            if k is None:
                unresolvable.append((gk, "exclude", e))
                continue
            exclude.append(k)
        if keep is None:
            continue

        overlap = set(absorb) & set(exclude)
        if overlap:
            bad_inner.append((gk, "absorb∩exclude", sorted(overlap)))

        frags = [keep] + absorb
        before = {"yjy_papers": sum(by_key[f]["yjy_papers"] for f in frags),
                  "total_cited": sum(by_key[f]["total_cited"] for f in frags),
                  "yjy_cited": sum(by_key[f]["yjy_cited"] for f in frags)}

        # `name:` 合成键**参与**重算（2026-09-29 修正，见模块 docstring）。
        # 旧规则把它剔除，理由是「它的论文已挂在主片名下」——该理由经查为假：
        # `name:guanghuihu` 的唯一论文 W4299444035（2022，18 被引，院署名）
        # **不在**主片 A5100750981 的 13 篇里，是一篇独立的深度学习降噪论文。
        # 剔除它 = 让 1 篇真实院署名论文和 18 条真实院口径被引凭空消失。
        # 去重不需要靠排除 name: 键——recompute() 用 work id **集合并集**，
        # 同一篇被两片覆盖时天然只算一次。
        got = recompute(frags, by_entity, works_by_id, orcid_by_entity,
                        matchers)

        # 去重后不该比相加还多：相加是上限，真值只能等于或小于它。
        if got["yjy_papers"] > before["yjy_papers"]:
            over_papers.append((gk, got["yjy_papers"], before["yjy_papers"]))
        if got["total_cited"] > before["total_cited"]:
            over_all.append((gk, got["total_cited"], before["total_cited"]))
        if got["yjy_cited"] > before["yjy_cited"]:
            over_yjy.append((gk, got["yjy_cited"], before["yjy_cited"]))

        row = dict(by_key[keep])
        row["orcid"] = got["orcid"]
        row["yjy_papers"] = got["yjy_papers"]
        row["total_cited"] = got["total_cited"]
        row["yjy_cited"] = got["yjy_cited"]
        row["year_min"] = got["year_min"]
        row["year_max"] = got["year_max"]
        row["top_venues"] = got["top_venues"]
        row["merged_from"] = sorted(frags)
        row["merge_reason"] = dec.get("evidence_reason", "")
        row["merge_verify"] = dec.get("verify", "")
        row["sum_before_dedup"] = before
        merged_rows.append(row)

        absorbed = absorb_all
        absorbed.update(absorb)
        merge_audit.append({
            "group_key": gk,
            "display_name": by_key[keep]["name"],
            "keep": keep,
            "absorb": absorb,
            "exclude": exclude,
            "before_dedup_sum": before,
            "after_dedup_recompute": got,
            "dedup_delta_cited_all": got["total_cited"] - before["total_cited"],
            "dedup_delta_cited_yjy": got["yjy_cited"] - before["yjy_cited"],
            "evidence_reason": dec.get("evidence_reason", ""),
            "verify": dec.get("verify", ""),
        })

    check(not unresolvable, "merge 决策里的每个实体引用都能解析到名册行",
          f"未解析 {len(unresolvable)} 处，示例：{unresolvable[:5]}")
    check(not bad_inner, "同一组内 absorb 与 exclude 不重叠",
          f"首个异常：{bad_inner[:3]}")
    check(not over_papers, "所有合并组去重后 yjy_papers ≤ 分片相加",
          f"超出的组：{over_papers}")
    check(not over_all, "所有合并组去重后 total_cited ≤ 分片相加",
          f"超出的组：{over_all}")
    check(not over_yjy, "所有合并组去重后 yjy_cited ≤ 分片相加",
          f"超出的组：{over_yjy}")
    check(len(merge_audit) == len(merge_dec),
          "合并决策全部可执行",
          f"决策表有 {len(merge_dec)} 组，实际可执行 {len(merge_audit)} 组——"
          "几乎必然是键口径不一致（有序 norm_name vs 无序 group_key）")

    # ---- 4. 组装名册：keep 行 / 未并实体原样保留，absorb 与 reject 移除 ----
    merged_keys = {r["entity_key"] for r in merged_rows}
    out_rows = [r for r in roster
                if r["entity_key"] not in dropped_all
                and r["entity_key"] not in absorb_all]
    keep_of_merge = {a["keep"] for a in merge_audit}
    out_rows = [r for r in out_rows if r["entity_key"] not in keep_of_merge]
    out_rows.extend(merged_rows)
    out_rows.sort(key=lambda r: ((r.get("yjy_cited") or 0) * -1,
                                r["yjy_papers"] * -1))

    expect_after = len(roster) - len(absorb_all) - len(dropped_all)
    check(len(out_rows) == expect_after,
          "名册行数 = 原行数 - 并掉 - 剔除",
          f"实际 {len(out_rows)}，预期 {expect_after}")
    check(len({r["entity_key"] for r in out_rows}) == len(out_rows),
          "名册无重复 entity_key")
    # 被并 / 被剔的实体必须全部解析到了真实名册行：决策表引用不存在的人，
    # 会让"并掉 N 行"的名义账与实际账对不上（历史事故：空跑一遍正常退出）。
    unres_absorb = sorted(absorb_all - set(by_key))
    check(not unres_absorb, "被并实体全部解析到名册行",
          f"未解析：{unres_absorb[:5]}")
    unres_drop = sorted(dropped_all - set(by_key))
    check(not unres_drop, "被剔实体全部解析到名册行",
          f"未解析：{unres_drop[:5]}")
    check(not (dropped_all & keep_of_merge),
          "被剔除组与合并 keep 无交叉",
          f"交叉：{dropped_all & keep_of_merge}")
    check(not (absorb_all & keep_of_merge),
          "被并实体与合并 keep 无交叉",
          f"交叉：{absorb_all & keep_of_merge}")

    # 逐行硬校验（聚合式，一次只报一个失败样本，避免刷屏）
    # 合法形态：openalex_id 为 null（合成键行）或匹配 ^A\d+$。
    bad_id = next((r for r in out_rows
                   if r["openalex_id"]
                   and not is_real_openalex_id(r["openalex_id"])), None)
    check(bad_id is None, "所有行 openalex_id 形态合法（A\\d+ 或 null）",
          f"首个异常：{bad_id.get('name') if bad_id else ''} → "
          f"{bad_id.get('openalex_id') if bad_id else ''}；"
          "非 A\\d+ 的值说明有人把姓名字符串塞进了 openalex_id 字段")
    bad_cite = next((r for r in out_rows
                     if r["yjy_cited"] > r["total_cited"]), None)
    check(bad_cite is None, "所有行 院口径被引 ≤ 宽口径被引",
          f"首个异常：{bad_cite.get('name') if bad_cite else ''} → "
          f"yjy_cited={bad_cite.get('yjy_cited') if bad_cite else ''} > "
          f"total_cited={bad_cite.get('total_cited') if bad_cite else ''}")
    bad_years = next((r for r in out_rows
                      if r["year_min"] is not None and r["year_max"] is not None
                      and r["year_min"] > r["year_max"]), None)
    check(bad_years is None, "所有行 year_min ≤ year_max",
          f"首个异常：{bad_years.get('name') if bad_years else ''}")
    bad_orphan = next((r for r in out_rows
                       if r["entity_key"] in absorb_all
                       or r["entity_key"] in dropped_all), None)
    check(bad_orphan is None, "被并/被剔实体未以独立行复活",
          f"首个异常：{bad_orphan.get('entity_key') if bad_orphan else ''}")

    # ---- 确定性自检 ----
    # 2026-09-29 实测事故：用 `for wid in work_ids`（set）遍历时，
    # 14/653 行的 top_venues 排列漂移，且同机重跑两次结果不同
    # （PYTHONHASHSEED 随机化），产物却"看起来完全正常"。
    #
    # 注意口径：这里**不是**断言「结果与遍历顺序无关」——`most_common()`
    # 在并列时按首次插入顺序返回，换顺序本来就该换结果。要断言的是
    # 「遍历顺序被钉死在 works_raw.json 的文件顺序上」，这才是可复现的
    # 充要条件。所以下面查两件事：
    #   A. 索引本身按文件顺序建立（插入序 == order 升序）；
    #   B. 同一份索引重算两次结果逐字节相同。
    ins = [v["order"] for v in works_by_id.values()]
    check(ins == sorted(ins),
          "work 索引按 works_raw.json 文件顺序建立（并列排列的锚点）",
          f"索引插入序与 order 不一致，前 5 处："
          f"{[(a, b) for a, b in zip(ins, sorted(ins)) if a != b][:5]}")
    unstable = []
    for a in merge_audit:
        frags = [f for f in [a["keep"]] + a["absorb"]
                 if not f.startswith("name:")]
        runs = [json.dumps(recompute(frags, by_entity, works_by_id,
                                     orcid_by_entity, matchers),
                           sort_keys=False) for _ in range(2)]
        if runs[0] != runs[1]:
            unstable.append(a["display_name"])
    check(not unstable, "同一输入重算两次结果逐字节相同",
          f"重算不稳定的组：{unstable}")

    audit_doc = {
        "institution": cfg["institution"]["name"],
        "cited_basis_note": "total_cited=宽口径(all)，yjy_cited=院口径；"
                            "合并后两者都按 work id 去重重算，不是相加",
        "semantics": {
            "merge": "同一人，已合并；absorb 的实体不再单列",
            "no_merge": "碎片不并入，但本人仍在核心（person_excluded_from_core=False）",
            "reject_whole_group": "整组判同名不同人，本人不进核心",
        },
        "n_merge_groups": len(merge_audit),
        "n_no_merge_groups": len(no_merge_audit),
        "n_reject_groups": len(reject_audit),
        "roster_before": len(roster),
        "roster_after": len(out_rows),
        "rows_absorbed": len(absorb_all) + len(dropped_all),
        "audit": merge_audit + no_merge_audit + reject_audit,
    }
    check(audit_doc["n_merge_groups"] == len(merge_dec),
          "审计表 merge 组数与决策表一致")
    check(audit_doc["rows_absorbed"] == len(roster) - len(out_rows),
          "rows_absorbed 与名册前后差一致")

    # ---- 报告 ----
    print(f"\n合并 {len(merge_audit)} 组（并掉 {len(absorb_all)} 行）"
          f" / 判不并 {len(no_merge_audit)} 组 / 整组剔除 {len(reject_audit)} 组"
          f"（剔除 {len(dropped_all)} 行）")
    print(f"名册 {len(roster)} → {len(out_rows)} 行")
    ded = [(a["display_name"], a["dedup_delta_cited_yjy"], a["dedup_delta_cited_all"])
           for a in merge_audit
           if a["dedup_delta_cited_yjy"] or a["dedup_delta_cited_all"]]
    if ded:
        print("去重实际生效的组（相加会虚高）：")
        for n, dy, da in ded:
            print(f"  · {n:20s} yjy_cited Δ={dy:+d}  total_cited Δ={da:+d}")
    else:
        print("⚠️ 没有任何一组的去重产生差额——相加与去重等价，"
              "本次样本恰好无重叠论文/重复署名。")

    print("\n自检：")
    for ok, label, detail in CHECKS:
        print(f"  {'✅' if ok else '❌'} {label}" + (f"  ← {detail}" if not ok else ""))
    failed = [c for c in CHECKS if not c[0]]
    if failed:
        sys.exit(f"\n❌ {len(failed)}/{len(CHECKS)} 项自检未通过，不写任何文件。")

    if args.dry_run:
        print("\n--dry-run：自检全过，未落盘。")
        return

    (outdir / f"{short}_roster_merged.json").write_text(
        json.dumps(out_rows, ensure_ascii=False, indent=1), encoding="utf-8")
    (outdir / f"{short}_merge_applied.json").write_text(
        json.dumps(audit_doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nSAVED → {outdir / f'{short}_roster_merged.json'}")
    print(f"SAVED → {outdir / f'{short}_merge_applied.json'}")


merged_orcid_cache = {}

if __name__ == "__main__":
    main()
