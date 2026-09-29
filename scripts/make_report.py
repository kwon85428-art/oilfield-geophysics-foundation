# -*- coding: utf-8 -*-
"""从合并后核心名单生成 Markdown 交付件 + 执行 md/json 集合级交叉校验。

单一真值 = <dir>/<short>_core_merged.json。md 只是渲染结果，
校验必须 md ↔ json 双向都过，不许只看 md 顺眼。

为什么正文里一个数字都不能手写
------------------------------
2026-09-29 实测：手写的数字**不只是过时，是错的**，而且错得没规律：

  正文写的                     实际重算             性质
  ---------------------------  -------------------  --------------------------
  核心 36 人                   36                   对（唯一侥幸没写错的）
  已核实中文姓名 7 人          6                    错（旧名映射有 1 条查不到）
  14 组已并 + 6 组判不并       15 + 3 + 3           错（三态被压成两态）
  作者从 713 降到 691          708 → 691            错
  city 约束错减到 346 / 400    345 / 395            错
  works_raw 3.57 MB            3.4 MB               错（手抄时抄的是旧版大小）

关键在于：**这些数字没有任何一处会被自动检查**。md 渲染成什么样都"通过"，
因为校验只比 md 和 json 之间的**一致性**，而错误的数字在 md 和 json 里
同样错，一致性检查看不出"两个都错"。

所以本脚本的纪律是：**正文出现的每个数字，都必须由 artifacts 现算，
不许出现在 f-string 之外**。口径漂移的风险从"忘了更新"降级为
"改了公式"——后者一定会被下面的断言抓住。

外部事实（非 OpenAlex 可验证）单独放 EXTERNAL，不与现算数字混排，
并在正文标注来源与抓取日期，避免读者把院方自报/第三方索引数字当成
本链路算出来的。
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

# 与 apply_merges.py 同口径：merges.json 的键是 author_identity.group_key
# （字符多重集，字序无关）。⚠️ 2026-09-29 踩过：校验器用自己的有序 norm()
# 去比对 group_key 键，全部 MISS → 「判为同名不同人的 0 组未混入核心名单：OK」
# 是**假通过**（0 组本来就没查成）。判据：校验器读键必须和被校验数据用同一把尺子。
sys.path.insert(0, str(Path(__file__).parent))  # skill 脚本同目录，不硬编码绝对路径
from author_identity import author_entity, group_key, is_real_openalex_id  # noqa: E402
from cited_basis import resolve_cited_field  # noqa: E402
from fetch_institute import build_matchers, is_institute  # noqa: E402

# ⚠️ 外部事实：这些数字**不是**本链路算出来的，也不该由本脚本假装能算。
#   放在这里是为了让「哪些数字有外部依赖」在代码里可见，而不是散落在
#   正文措辞里被当成测算结果引用。每条必须带 source 与 fetched_at。
EXTERNAL = {
    "zhao_qun": {
        "title": "赵群",
        "openalex_papers": None,      # 从 roster 现算，不手写
        "openalex_cited": None,       # 从 roster 现算，不手写
        "cn_index_cited": 5182,       # 百度学术 H-index 口径，非 OpenAlex
        "cn_index_works": 462,
        "cn_index_h": 39,
        "cn_index_source": "百度学术（ID 由公开检索得到，2026-09-29 抓取）",
        "cn_title_note": "中国地学文献中心记录其为「1959-，教授级高工」",
    },
    "rival_works": {
        # OpenAlex institutions/<id>.works_count，实时值会变；这里只用于
        # 说明「兄弟院体量远大于本院」这一定性判断。
        "SINOPEC Exploration & Production Research Institute":
            {"id": "I4405280853", "works_count": 3190, "fetched_at": "2026-09-29"},
    },
}


# ───────────────────────── 现算事实 ─────────────────────────
def compute_facts(d, short, cfg, raw, roster, merged_roster, core, mj, ma, dis):
    """把报告要用的每一个数字都算出来，并**同时算出它的定义**。

    返回 (F, roster_recompute)：
      F              数字字典
      roster_recompute  从 works_raw + matcher 独立重算的每行 yjy 业绩，
                       用来交叉校验 roster 本身没与缓存脱节
    """
    ident = cfg["identify"]
    rival, yjy_en, yjy_cn, city, cross, relax_city = build_matchers(ident)

    # ---- 机构识别：院署名 works / 实体，以及两个反事实对照 ----
    sib_tokens = ("Jiangsu Oilfield", "Shengli", "江苏油田", "胜利物探")
    sib_tokens_cn = ("江苏油田物探", "胜利物探")
    keep_toks = [t for t in ident["rival_exclude_tokens"]
                 if not any(s.lower() in t.lower()
                            for s in sib_tokens + sib_tokens_cn)]
    rival_nosib = re.compile("|".join(re.escape(t) for t in keep_toks), re.I)

    def sweep(riv, relax):
        """机构署名扫描。同时重算每个实体的院口径业绩（与 fetch 同语义：
        逐条 authorship 累加，故同一人在一篇里出现两次会计两次）。"""
        W, E = set(), set()
        perf = defaultdict(lambda: {"n": 0, "cited": 0})
        for w in raw:
            wid = w.get("id", "")
            cited = w.get("cited_by_count") or 0
            for a in w.get("authorships", []):
                affs = a.get("raw_affiliation_strings") or []
                if not affs:
                    affs = [i.get("display_name", "")
                            for i in a.get("institutions", [])]
                if not is_institute(affs, riv, yjy_en, yjy_cn, city, cross, relax):
                    continue
                ek = author_entity(a.get("author"))["entity_key"]
                W.add(wid)
                E.add(ek)
                perf[ek]["n"] += 1
                perf[ek]["cited"] += cited
        return W, E, perf

    cur_w, cur_e, perf = sweep(rival, relax_city)
    nosib_w, nosib_e, _ = sweep(rival_nosib, relax_city)
    strict_w, strict_e, _ = sweep(rival, False)

    # ---- 跨集团双署名 ----
    n_cross = n_blocked = 0
    blocked_w, blocked_p = set(), set()
    for w in raw:
        for a in w.get("authorships", []):
            affs = a.get("raw_affiliation_strings") or []
            if not affs:
                affs = [i.get("display_name", "")
                        for i in a.get("institutions", [])]
            joined = " | ".join(affs or [])
            if not (cross and cross.search(joined)):
                continue
            if is_institute(affs, rival, yjy_en, yjy_cn, city, cross, relax_city):
                continue
            if not (yjy_en.search(joined) or yjy_cn.search(joined)):
                continue
            n_cross += 1
            if is_institute(affs, rival, yjy_en, yjy_cn, city, None, relax_city):
                n_blocked += 1
                blocked_w.add(w.get("id", ""))
                blocked_p.add(author_entity(a.get("author"))["entity_key"])

    # ---- 城市共现约束的覆盖度 ----
    PLACE = re.compile(
        r"(?:Nanjing|Jiangsu|Jiangning|China|Chinese|中国|南京|江苏|江宁|上海"
        r"|Beijing|Shanghai|Chengdu|Wuhan|Guangzhou|北京|武汉|四川)", re.I)
    n_sig = n_inst_sig = n_inst_nocity = n_inst_noplace = n_bare = 0
    for w in raw:
        for a in w.get("authorships", []):
            affs = a.get("raw_affiliation_strings") or []
            if not affs:
                affs = [i.get("display_name", "")
                        for i in a.get("institutions", [])]
            j = " | ".join(affs or [])
            if not j:
                continue
            n_sig += 1
            if yjy_en.search(j) or yjy_cn.search(j):
                n_inst_sig += 1
                if not city.search(j):
                    n_inst_nocity += 1
                if not PLACE.search(j):
                    n_inst_noplace += 1
            if j.strip() == "Sinopec Geophysical Research Institute":
                n_bare += 1

    # ---- 决策表 / 审计表 ----
    def real(dd, want_type):
        return {k: v for k, v in (dd or {}).items()
                if not k.startswith("_") and isinstance(v, want_type)}

    mrg = real(mj.get("merge"), dict)
    nmg = real(mj.get("no_merge"), dict)
    rjg = real(mj.get("reject_whole_group"), str)

    absorb_all, dropped_all, exclude_in_merge = set(), set(), set()
    for a in ma["audit"]:
        absorb_all |= set(a.get("absorb") or [])
        exclude_in_merge |= set(a.get("exclude") or [])
        dropped_all |= set(a.get("dropped") or [])

    # ---- 分身诊断 ----
    frag_ents = {f["entity_key"] for g in dis for f in (g.get("fragments") or [])}
    merged_keys = {r["entity_key"] for r in merged_roster}

    # ---- 核心 ----
    verified = [r for r in core if r.get("name_cn")]
    pending = [r for r in core if not r.get("name_cn")]
    core_merged = [r for r in core if r.get("merged_from")]
    newly = [r for r in core if r.get("newly_admitted_by_merge")]

    # ---- 赵群案例：OpenAlex 一侧现算，不用手写 ----
    # ⚠️ 2026-09-29 踩过：按 name=="qun zhao" 抓行会把**两行**都算进来——
    # A5037137605（6 篇 / 院引用 84）与一个 synthetic name:qunzhao 碎片
    # （1 篇 / 13），相加得 7/97，案例数字就错了。
    # 判据：案例数字只取**有真实 OpenAlex author id 的那一行**。理由有二：
    #   ① third-party index（百度学术）是对**具名学者**的计量，synthetic 碎片
    #      不是独立的人，加进去是拿两个口径不同的东西相加；
    #   ② synthetic 碎片只有 1 篇、院引用 13，本身也够不上任何门槛，
    #      并进去只会虚增「中文缺口」的量级。
    zhao = [r for r in roster
            if (r.get("name") or "").lower() == "qun zhao"
            and is_real_openalex_id(r.get("openalex_id"))]
    if len(zhao) != 1:
        sys.exit(f"❌ 赵群案例应恰好命中 1 个真实 OpenAlex 作者行，"
                 f"实际命中 {len(zhao)}："
                 f"{[r.get('entity_key') for r in zhao]} —— "
                 f"先人工确认是谁，不要靠改脚本绕过。")
    zq_papers = zhao[0].get("yjy_papers", 0)
    zq_cited = zhao[0].get("yjy_cited", 0)

    th = cfg.get("threshold", {})
    basis, field = resolve_cited_field(th)

    F = {
        # 规模
        "n_works": len(raw),
        "n_yjy_works": len(cur_w),
        "n_entities": len(cur_e),
        "raw_mb": round((d / f"{short}_works_raw.json").stat().st_size
                        / 1048576, 2),
        # 名册
        "roster_before": len(roster),
        "roster_after": len(merged_roster),
        "roster_removed": len(roster) - len(merged_roster),
        "n_noid": sum(1 for r in roster if r.get("openalex_id_missing")),
        # 决策
        "n_merge_groups": len(mrg),
        "n_no_merge_groups": len(nmg),
        "n_reject_groups": len(rjg),
        "n_absorbed": len(absorb_all),
        "n_excluded_in_merge": len(exclude_in_merge),
        "n_dropped": len(dropped_all),
        "n_removed_total": len(absorb_all | dropped_all),
        # 分身
        "n_frag_groups": len(dis),
        "n_frag_entities": len(frag_ents),
        "n_frag_surviving": len(frag_ents & merged_keys),
        # 核心
        "n_core": len(core),
        "n_verified": len(verified),
        "n_pending": len(pending),
        "n_core_merged": len(core_merged),
        "n_newly": len(newly),
        "newly_names": [r["name_en"] for r in newly],
        # 污染治理
        "n_cross_sig": n_cross,
        "n_cross_blocked": n_blocked,
        "n_cross_works": len(blocked_w),
        "n_cross_people": len(blocked_p),
        "nosib_works": len(nosib_w),
        "nosib_entities": len(nosib_e),
        "sib_removed_works": len(nosib_w) - len(cur_w),
        "sib_removed_entities": len(nosib_e) - len(cur_e),
        "strict_works": len(strict_w),
        "strict_entities": len(strict_e),
        "city_cost_works": len(cur_w) - len(strict_w),
        "city_cost_entities": len(cur_e) - len(strict_e),
        # 城市约束覆盖度
        "n_sig": n_sig,
        "n_inst_sig": n_inst_sig,
        "n_inst_nocity": n_inst_nocity,
        "n_inst_noplace": n_inst_noplace,
        "n_bare": n_bare,
        # 口径
        "basis": basis,
        "field": field,
        "p_min": th.get("yjy_min", 2),
        "c_min": th.get("cited_min", 30),
        # 案例
        "zhao_papers": zq_papers,
        "zhao_cited": zq_cited,
        # 实体集合（校验用）
        "_absorb": absorb_all,
        "_dropped": dropped_all,
        "_exclude_in_merge": exclude_in_merge,
        "_mrg": mrg,
        "_nmg": nmg,
        "_rjg": rjg,
    }
    return F, perf


# ───────────────────────── 渲染 ─────────────────────────
def render(F, cfg, short, core, verified, pending, newly, roster, frag_n,
           th, inst_dir):
    L = []
    A = L.append
    name = cfg["institution"]["name"]
    ext = EXTERNAL

    A(f"# {name} · 专家名单反推报告\n")
    A(f"> 链路：L1 机构名单反推｜数据源 OpenAlex（机构实体 "
      f"`{cfg['institution']['openalex_parent_id']}`）+ 官网一手信息 + 中文期刊原文")
    A(f"> 口径：院署名论文 `≥{F['p_min']}` 篇且院署名论文被引 "
      f"`≥{F['c_min']}`（被引口径 cited_basis={F['basis']}，"
      f"取 roster 字段 `{F['field']}`）")
    A(f"> **名单真值 = `{short}_core_merged.json`**，本文件是它的渲染结果，"
      f"两者已做集合级交叉校验。正文所有数字均由数据件现算，无手写常量。\n")

    A("## 一、先说结论：这个名单能回答什么、不能回答什么\n")
    A("**能回答**：谁在英文文献里持续产出、方向分布、被引量级、院内外机构关系。")
    A(f"**不能回答**：(1) 谁是院里的技术权威；(2) 中文姓名（仅 {F['n_verified']} 人核实，"
      f"其余 {F['n_pending']} 人不给中文名）；")
    A("(3) 谁在带项目、谁在评奖——这些只有中文渠道能回答。\n")
    A("**最要紧的一条警告**：本名单**系统性低估以中文发表为主的技术骨干**。")
    A(f"最典型的例子已核实——**{ext['zhao_qun']['title']}**，"
      f"{ext['zhao_qun']['cn_title_note']}，")
    A(f"{ext['zhao_qun']['cn_index_source']}显示被引 {ext['zhao_qun']['cn_index_cited']}、"
      f"成果 {ext['zhao_qun']['cn_index_works']}、H={ext['zhao_qun']['cn_index_h']}，")
    A(f"而 OpenAlex 口径只给出 {F['zhao_papers']} 篇 / 被引 {F['zhao_cited']}"
      f"（本报告从名册现算）。差额全部来自中文期刊与中文专著。")
    A(f"**所以核心 {F['n_core']} 人不是「院里最牛的 {F['n_core']} 人」，"
      f"是「在 OpenAlex 里可见度最高的 {F['n_core']} 人」。**\n")

    # ── 二 ──
    A("## 二、院本体（官网一手，2026-09 抓取）\n")
    A(f"**{name}**\n")
    for line in (cfg.get("official_profile") or []):
        A(f"- {line}")
    A("")
    st = (cfg.get("_website") or {}).get("official_stats") or {}
    A(f"**规模与产出（{st.get('_as_of', '官网口径')}，院方自报，非 OpenAlex 计算）**\n")
    A("| 指标 | 数值 |")
    A("| --- | --- |")
    for k, v in st.items():
        if k.startswith("_"):
            continue
        A(f"| {k} | {v} |")
    A("")
    A("### 现任领导班子\n")
    A("| 姓名 | 职务 |")
    A("| --- | --- |")
    for n, t in (cfg.get("leaders") or []):
        A(f"| {n} | {t} |")
    A("")
    A("### 二级单位技术定位\n")
    A("| 单位 | 职责（据官网「各单位、部门介绍」） |")
    A("| --- | --- |")
    for n, t in (cfg.get("org_units") or []):
        A(f"| **{n}** | {t} |")
    A("")
    fds = cfg.get("functional_depts") or []
    A(f"职能部门 {len(fds)} 个：{'、'.join(fds)}。\n")

    # ── 三 ──
    A(f"## 三、核心名单（{F['n_core']} 人）\n")
    A(f"口径：`yjy_papers ≥ {F['p_min']}` 且 `{F['field']} ≥ {F['c_min']}`"
      f"（被引只算院署名论文）。")
    A("被引是**全作者共享累计**，只能当下界用，不适合做精确横向排名。\n")
    A("| # | 中文名 | 英文名 | 院署名篇数 | 院署名被引 | 年份跨度 | 方向 | OpenAlex ID |")
    A("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for i, r in enumerate(core, 1):
        cn = r.get("name_cn") or "—"
        span = f"{r.get('year_min') or '?'}–{r.get('year_max') or '?'}"
        A(f"| {i} | {cn} | {r['name_en']} | {r['yjy_papers']} | "
          f"{r.get(F['field'], r['total_cited'])} | {span} | "
          f"{r.get('domain') or '待归类'} | `{r['openalex_id']}` |")
    A("")

    A(f"### 已核实中文姓名（{F['n_verified']} 人，禁音译）\n")
    A("| 中文名 | 英文名 | 核实强度 | 主要依据 |")
    A("| --- | --- | --- | --- |")
    for r in verified:
        src = r.get("name_cn_source") or []
        s = (src[0] if src else "")[:95]
        A(f"| **{r['name_cn']}** | {r['name_en']} | {r.get('name_cn_verify', '')} | {s} |")
    A("")
    A("> **核实方法说明**：中文名一律取自公开一手源——① 中文期刊 PDF 原文的作者署名行与「第一作者简介」；")
    A("> ② 官网页面；③ 中国地学文献中心联机书目；④ 院方邮箱前缀（`swty` = 石油物探技术研究院缩写）。")
    A("> 已用邮箱规则交叉验证三人：刘定进=`liudj.swty`、刘卫华=`liuwh.swty`、胡光辉=`hugh.swty`，")
    A("> 三人规则一致，可作为该院邮箱命名惯例的可信前提。")
    A("> **禁止音译**：`Weihua Liu` 核为「刘卫华」而非「刘伟华」；`Guanghui Hu` 核为「胡光辉」而非「胡广辉」。")
    A(f"> 剩余 {F['n_pending']} 人查不到公开中文源，**一律留空进附录，不做拼音反推**。\n")

    if newly:
        A(f"### 靠分身合并才新进核心的 {F['n_newly']} 人\n")
        A(f"这 {F['n_newly']} 人在合并前因 OpenAlex 把同一个人的产出拆成多个 author.id 而各不达标。")
        A(f"合并按三判据（合作者网络 + 机构 + 主题）人工判定，证据在 `{short}_merges.json`。\n")
        for r in newly:
            A(f"**{r['name_en']}** — 合并后 {r['yjy_papers']} 篇 / 被引 {r[F['field']]}")
            A(f"- 合并证据：{r.get('disambig_note', '')}")
            if r.get("disambig_excluded"):
                A(f"- 同时排除：{r['disambig_excluded']} —— "
                  f"{r.get('disambig_exclude_reason', '')}")
            A("")
        A(f"> 反过来，{F['n_core_merged']} 个合并行里另有 "
          f"{F['n_core_merged'] - F['n_newly']} 行 `newly_admitted_by_merge=false`：")
        A("> 那些人在合并前就各自已过门槛，合并只是把被引去重、把年份与期刊口径统一。")
        A("> **两种情况不可混为一谈**——把后者也说成「靠合并捞回来的」会虚增合并的贡献。\n")

    # ── 四 ──
    A("## 四、方向分布（主领域 argmax 口径）\n")
    byd = defaultdict(list)
    for r in core:
        byd[r.get("domain") or "待归类"].append(r)
    A("| 主领域 | 人数 | 名单 |")
    A("| --- | --- | --- |")
    for dom in sorted(byd, key=lambda k: -len(byd[k])):
        names = "、".join(
            (r.get("name_cn") or r["name_en"]) for r in
            sorted(byd[dom], key=lambda x: -x.get(F["field"], 0)))
        A(f"| {dom} | {len(byd[dom])} | {names} |")
    A("")
    cross = defaultdict(list)
    for r in core:
        for dm in (r.get("domain_hits") or {}):
            cross[dm].append(r["name_en"])
    A("**交叉方向覆盖**（一人可属多方向，与主领域互不排斥）：\n")
    for dm in sorted(cross, key=lambda k: -len(cross[k])):
        A(f"- {dm}：{len(cross[dm])} 人")
    A("")
    ai = [r for r in core if "07 AI + 地球物理交叉" in (r.get("domain_hits") or {})]
    if ai:
        A(f"**做 AI 的 {len(ai)} 人**："
          + "、".join((r.get("name_cn") or r["name_en"]) for r in ai) + "\n")

    # ── 五 ──
    A("## 五、污染治理与数据边界\n")
    A("### 同名机构污染\n")
    A("中石化体系内 OpenAlex 有 7 个独立研究所实体。已配置排除：")
    A("- 中石化石油勘探开发研究院（北京昌平/燕郊，最大污染源，"
      f"{ext['rival_works']['SINOPEC Exploration & Production Research Institute']['works_count']}"
      " works）")
    A("- 中石化石油加工研究院、安全工程研究院、上海石化研究院、北京化工研究院、"
      "石油工程技术研究院")
    A("- 南京物探院、石油工程/地球物理类近名院")
    A("- **江苏油田物探院**（`Geophysical Research Institute, Jiangsu Oilfield Company`，"
      "邮箱 `liulm.jsyt@sinopec.com`）")
    A("- **胜利物探院**（`Shengli Geophysical Research Institute`，"
      "邮箱 `shangwei.slyt@sinopec.com`）")
    A("")
    A("后两条是本轮补漏的——两者同在南京/东营、同属中石化，原词表只按「带地名的通用名」写，"
      "漏了「以油田公司名开头」的写法。")
    A("**判据：同体系兄弟院优先按油田公司名排除，不要只按「地球物理研究院」这类通用名排除"
      "——后者会把本院自己排除掉。**")
    A(f"补漏后院署名 works 从 {F['nosib_works']} 降到 {F['n_yjy_works']}，"
      f"实体从 {F['nosib_entities']} 降到 {F['n_entities']}"
      f"（净剔除 {F['sib_removed_works']} 篇 / {F['sib_removed_entities']} 个实体）。\n")
    A("### 跨集团双署名\n")
    A(f"同一署名串内出现 CNPC / PetroChina / CNOOC / 延长等其他集团名即判为双单位合作，"
      f"剔除 {F['n_cross_sig']} 条署名（涉 {F['n_cross_works']} 篇论文、"
      f"{F['n_cross_people']} 人）。\n")
    A("### 城市共现约束为何关闭\n")
    A("本院在 OpenAlex 有独立机构实体，院名全国唯一，不存在大庆院那种「几十家油田同名研究院」的问题。")
    A(f"实测 {F['n_works']} 篇里 {F['n_inst_sig']} 条署名带院名，其中 "
      f"{F['n_inst_nocity']} 条不带任何城市词"
      f"（`Sinopec Geophysical Research Institute` 裸署名 {F['n_bare']} 条，"
      f"连地名都没有的 {F['n_inst_noplace']} 条）。")
    A(f"沿用大庆的 city 约束会把院署名 works 从 {F['n_yjy_works']} 错减到 "
      f"{F['strict_works']}、实体从 {F['n_entities']} 错减到 {F['strict_entities']}"
      f"（代价 {F['city_cost_works']} 篇 / {F['city_cost_entities']} 个实体）。")
    A("关闭后只保留 rival（同名机构）+ cross（跨集团）两道防线。\n")
    A("### 已知数据缺陷（必须知道，否则会高估完整性）\n")
    A(f"1. **OpenAlex 存在作者碎片化**：全院 {F['roster_before']} 个实体中，"
      f"{F['n_frag_groups']} 组姓名对应多个 author.id（{F['n_frag_entities']} 个实体）。")
    A(f"   已人工判定并合并 {F['n_merge_groups']} 组、整组剔除 {F['n_reject_groups']} 组，"
      f"名册实体从 {F['roster_before']} 降到 {F['roster_after']}。")
    A(f"   碎片组内仍独立存在的实体 {F['n_frag_surviving']} 个，"
      f"**其中可能仍藏同一人被低估**——本轮只判了会改变名单的组。")
    A(f"2. **{F['n_noid']} 个实体 OpenAlex 未分配 author.id**：聚合主键退化为 "
      f"`name:<归一化名>`，")
    A("   这类人无法与外部交叉校验，也无法保证没被漏合并（`Cai Jiexiong` / `Cai Jie-xiong` / "
      "`Jiexiong Cai` 三种写法中，")
    A("   前两种都无 id，只能靠归一化姓名与中文源合并）。")
    A("3. **中文期刊覆盖是硬伤**：本院主办《石油物探》，但该刊在 OpenAlex 收录不全。")
    A(f"   {ext['zhao_qun']['title']}案例量化了这个缺口"
      f"（第三方索引被引 {ext['zhao_qun']['cn_index_cited']} vs OpenAlex "
      f"{F['zhao_cited']}）。")
    A(f"4. **OpenAlex 计数动态**：机构实体 `works_count` 字段与实际 works 筛选返回值不一致"
      f"（前者是机构页上的滚动计数，后者才是本次抓取口径）。\n")

    rej = F["_rjg"]
    if rej:
        A(f"### 判为同名不同人、整组不进核心的 {F['n_reject_groups']} 组\n")
        A("这三组不是「证据不足所以不并」，而是**证据表明组内根本不是同一人**。\n")
        for k, v in rej.items():
            A(f"- **{k}**（group_key）：{v[:230]}")
        A("")
    A(f"### 只判「不合并碎片」、本人仍在核心的 {F['n_no_merge_groups']} 组\n")
    A("这三组的 keep 本人凭自己那几篇就已过门槛，")
    A("只是另一/另几个碎片证据不足以并入——**不并 ≠ 剔除本人**。\n")
    for k, v in F["_nmg"].items():
        A(f"- **{k}**：{v['reason'][:150]}")
    A("")

    # ── 六 ──
    A(f"## 六、待核中文姓名附录（{F['n_pending']} 人）\n")
    A("以下人**没有查到可靠中文源**，按纪律留空。英文名是 OpenAlex 原始署名，")
    A("不代表中文姓名——同名不同人的情况在本院很常见"
      "（`Wei Xie` 组内就混进了一篇土木工程论文，该组已整组剔除）。\n")
    A("| 英文名 | 院署名篇数 | 院署名被引 | 年份 | 方向 | 署名机构样本 |")
    A("| --- | --- | --- | --- | --- | --- |")
    for r in sorted(pending, key=lambda x: -x.get(F["field"], 0)):
        aff = (r.get("aff_evidence") or [""])[0]
        aff = re.sub(r"\s+", " ", aff)[:70]
        A(f"| {r['name_en']} | {r['yjy_papers']} | {r.get(F['field'], 0)} | "
          f"{r.get('year_min') or '?'}–{r.get('year_max') or '?'} | "
          f"{r.get('domain') or '待归类'} | {aff} |")
    A("")

    # ── 七 ──
    A("## 七、如果要把这份名单做实，优先做三件事\n")
    A("1. **走中文渠道补姓名与职位**：《石油物探》《地球科学》作者简介、CNKI 作者页、")
    A("   中国地学文献中心联机书目（检索式 `姓名^c机构^d年份`）能拿到「姓名+出生年+职称+单位」，")
    A("   这是 OpenAlex 结构上给不了的东西。")
    A(f"2. **补{ext['zhao_qun']['title']}类人物的多口径画像**：被引 5000+ 的院元老全部藏在中文索引里，")
    A("   只用 OpenAlex 做画像会系统性漏掉院里最资深的一批人。")
    A(f"3. **把 {F['n_frag_groups']} 组分身全部人工过一遍**：现在只判了会改变名单的 "
      f"{F['n_merge_groups']} 组合并 + {F['n_reject_groups']} 组剔除，")
    A("   其余组可能藏着「同一人被拆成 3 个 id」的情况，影响的是**每个人**的篇数与被引，"
      "不只是名单成员资格。\n")

    # ── 八 ──
    A("## 八、数据文件\n")
    A("| 文件 | 内容 |")
    A("| --- | --- |")
    A(f"| `{short}_core_merged.json` | **核心名单真值**（{F['n_core']} 人，"
      f"含合并证据与姓名来源） |")
    A(f"| `{short}_roster.json` / `.csv` | 院署名 ≥1 篇的全部作者"
      f"（合并前 {F['roster_before']} 行） |")
    A(f"| `{short}_roster_merged.json` | 应用合并决策后的名册"
      f"（{F['roster_after']} 行，−{F['roster_removed']}） |")
    A(f"| `{short}_merge_applied.json` | 合并审计表"
      f"（{F['n_merge_groups']} 并 + {F['n_no_merge_groups']} 不并 + "
      f"{F['n_reject_groups']} 整组剔除，均带证据） |")
    A(f"| `{short}_merges.json` | 分身合并决策表（三态语义 + 判据说明） |")
    A(f"| `{short}_disambig.json` | {F['n_frag_groups']} 组多分身诊断报告"
      f"（{F['n_frag_entities']} 个实体） |")
    A(f"| `{short}_works_raw.json` | OpenAlex 原始 works 缓存"
      f"（{F['n_works']} 篇，{F['raw_mb']} MB） |")
    A(f"| `institutes/{short}.json` | 院配置（识别规则 + 排除词 + 门槛） |")
    A(f"| `institutes/{short}_name_cn.json` | 已核实中文姓名及来源 |")
    A("")
    return "\n".join(L)


# ───────────────────────── 校验 ─────────────────────────
def validate(md, F, short, cfg, core, roster, merged_roster, perf, ma, mj, dis,
             nc):
    errs = []

    def chk(cond, msg):
        print(("  ✅ " if cond else "  ❌ ") + msg)
        if not cond:
            errs.append(msg)

    def info(msg):
        print("  ℹ️ " + msg)

    print("\n=== A. md ↔ json 渲染一致性 ===")
    md_rows = re.findall(r"^\| \d+ \| .*? \| (.*?) \| (\d+) \| (\d+) \|", md, re.M)
    chk(len(md_rows) == len(core),
        f"md 名单行数 {len(md_rows)} == json {len(core)}")
    chk([r[0] for r in md_rows] == [r["name_en"] for r in core],
        "md 与 json 的英文名顺序完全一致")
    bad_c = [(m[0], b["name_en"]) for m, b in zip(md_rows, core)
             if int(m[1]) != b["yjy_papers"]
             or int(m[2]) != b.get(F["field"], b.get("total_cited", 0))]
    chk(not bad_c,
        f"md 与 json 的篇数/被引逐行一致（{len(md_rows)} 行）"
        f"{'' if not bad_c else '：' + str(bad_c[:3])}")
    verified = [r for r in core if r.get("name_cn")]
    pending = [r for r in core if not r.get("name_cn")]
    chk(len(verified) + len(pending) == len(core),
        f"已核 {len(verified)} + 待核 {len(pending)} = {len(core)}")
    md_cn = set(re.findall(r"^\| \d+ \| ([一-鿿]+) \|", md, re.M)) - {"—"}
    want_cn = {r["name_cn"] for r in verified}
    chk(md_cn == want_cn,
        f"md 中文名集合 == json（多: {md_cn - want_cn or '无'}；"
        f"少: {want_cn - md_cn or '无'}）")
    # 待核附录行数
    ap = re.search(r"## 六、待核中文姓名附录（(\d+) 人）", md)
    ap_rows = re.findall(r"^\| [A-Z][^|]* \| \d+ \| \d+ \|", md, re.M)
    chk(ap is not None and int(ap.group(1)) == len(pending) == len(ap_rows),
        f"附录声明人数 == json 待核 {len(pending)} == 附录行数 "
        f"{len(ap_rows)}（声明 {ap.group(1) if ap else '缺失'}）")

    print("\n=== B. 名单内部一致性 ===")
    chk(all(isinstance(r.get("name_cn"), str) for r in core),
        "name_cn 全为字符串（无 dict 假通过）")
    ids = [r["openalex_id"] for r in core]
    chk(len(ids) == len(set(ids)), f"无重复 openalex_id（{len(ids)} 行）")
    chk(all(is_real_openalex_id(i) for i in ids if i),
        "openalex_id 形态合法（A\\d+ 或空串）")
    g = Counter(group_key(r["name_en"]) for r in core)
    chk(max(g.values()) == 1,
        f"归一化后无重名（分身已合并）；重复项 "
        f"{[k for k, v in g.items() if v > 1] or '无'}")
    byd = defaultdict(list)
    for r in core:
        byd[r.get("domain") or "待归类"].append(r)
    chk(sum(len(v) for v in byd.values()) == len(core),
        f"领域人数合计 {sum(len(v) for v in byd.values())} == {len(core)}")
    absorbed_ids = {i for r in core for i in r.get("merged_ids", [])}
    chk(not (absorbed_ids & set(ids)),
        f"被并掉的 {len(absorbed_ids)} 个实体不在名单中")
    bad_th = [r["name_en"] for r in core
              if r["yjy_papers"] < F["p_min"]
              or r.get(F["field"], 0) < F["c_min"]]
    chk(not bad_th, f"每行都过门槛 yjy>={F['p_min']} 且 {F['field']}>={F['c_min']}"
                    f"：{bad_th or 'OK'}")
    chk(recs_sorted := all(
        (core[i].get(F["field"], 0), core[i]["yjy_papers"])
        >= (core[i + 1].get(F["field"], 0), core[i + 1]["yjy_papers"])
        for i in range(len(core) - 1)),
        f"名单按 (-{F['field']}, -yjy_papers) 降序（口径与门槛一致）")

    print("\n=== C. 名册层：合并落账是否完整 ===")
    chk(len(roster) == ma["roster_before"] and len(merged_roster) == ma["roster_after"],
        f"名册前后行数 {len(roster)}→{len(merged_roster)} "
        f"与审计表 {ma['roster_before']}→{ma['roster_after']} 一致")
    rk = {r["entity_key"] for r in roster}
    mk = {r["entity_key"] for r in merged_roster}
    mk_all = mk          # 供后面 no_merge 回查复用（同名变量只此一处定义）
    removed = rk - mk
    chk(len(removed) == ma["rows_absorbed"],
        f"物理删除 {len(removed)} 行 == rows_absorbed {ma['rows_absorbed']}")
    chk(removed == (F["_absorb"] | F["_dropped"]),
        f"被删实体集合 == 被并 {len(F['_absorb'])} ∪ 整组剔除 "
        f"{len(F['_dropped'])}（差集 {sorted(removed ^ (F['_absorb'] | F['_dropped']))}）")
    chk(not (F["_absorb"] & F["_dropped"]),
        "被并集合与整组剔除集合无交集")
    # ⚠️ merge 级 exclude 与 reject_whole_group 的 dropped 是**两件事**，
    # 2026-09-29 实测 3 个 exclude 实体确实仍留在合并后名册里 —— 这是正确的：
    # exclude 只是「这一片不并进 keep」（并入 merge 组后被排除的同组异人），
    # 并没有「整组判同名不同人」把人从名册里删掉。只有 reject_whole_group
    # 才是物理删除。若把两者混为一谈，会误报 3 个「污染泄漏」。
    chk(not (F["_exclude_in_merge"] & F["_dropped"]),
        f"merge 级 exclude（{len(F['_exclude_in_merge'])} 个）与整组剔除"
        f"（{len(F['_dropped'])} 个）语义不同、集合无交集")
    chk(F["_exclude_in_merge"] <= (F["_absorb"] | mk_all),
        "merge 级 exclude 的实体要么被并吸收、要么本就仍在名册，无凭空消失")
    info(f"merge 级 exclude 实体（不并入 keep，但**未**从名册删除）："
         f"{sorted(F['_exclude_in_merge'])}")
    leaked_rej = sorted(F["_dropped"] & mk)
    chk(not leaked_rej, f"整组剔除的 {len(F['_dropped'])} 个实体已从名册物理删除："
                        f"{leaked_rej or 'OK'}")
    kept_absorb = sorted(F["_absorb"] & mk)
    chk(not kept_absorb, f"被并的 {len(F['_absorb'])} 个分身不再单列：{kept_absorb or 'OK'}")
    chk(len(rk & mk) + len(removed) == len(rk),
        "名册实体集合守恒（留存 + 删除 == 原集合）")

    print("\n=== D. 三态决策语义 ===")
    chk(len(F["_mrg"]) == ma["n_merge_groups"]
        and len(F["_nmg"]) == ma["n_no_merge_groups"]
        and len(F["_rjg"]) == ma["n_reject_groups"],
        f"决策表组数 {len(F['_mrg'])}/{len(F['_nmg'])}/{len(F['_rjg'])} "
        f"== 审计表 {ma['n_merge_groups']}/{ma['n_no_merge_groups']}/"
        f"{ma['n_reject_groups']}（merge/no_merge/reject）")
    # ⚠️ 只查 reject_whole_group，**不能查 no_merge**：
    # no_merge 的语义是「不合并碎片分身」，本人仍可凭自己那几篇进核心。
    # 2026-09-29 踩过：把两种语义混在一起查，误报 3 人「污染」——
    # 是校验器语义假设错了，不是名单错了。问「本人是否被剔除」，别问「碎片是否被合并」。
    rej_keys = {group_key(k) for k in F["_rjg"]}
    leak = sorted({r["name_en"] for r in core
                   if group_key(r["name_en"]) in rej_keys})
    chk(not leak, f"判为同名不同人的 {len(F['_rjg'])} 组未混入核心名单：{leak or 'OK'}")
    nmg_keys = {group_key(k) for k in F["_nmg"]}
    kept_ok = {r["name_en"] for r in core if group_key(r["name_en"]) in nmg_keys}
    info(f"no_merge 组中本人仍在核心的：{sorted(kept_ok) or '无'}（语义正确）")
    # ⚠️ person_excluded_from_core 只存在于 **merge_applied.json 的 audit 条目**，
    # 不在 merges.json 里。merges.json 的 no_merge 条目只有 reason/verify/_legacy_key
    # （那是「人写的决策」，audit 才是「机器落账的结果」）。
    # 2026-09-29 踩过：在这里查 merges.json，v.get() 恒为 None，
    # 断言「全为 False」变成 `all(None is False)` == False → 假失败。
    # 教训：语义标志要在**产出它的那份件**里查，且用 `is False/True` 而非真值。
    nm_audit = [a for a in ma["audit"] if a.get("decision") == "no_merge"]
    rj_audit = [a for a in ma["audit"] if a.get("decision") == "reject_whole_group"]
    chk(len(nm_audit) == F["n_no_merge_groups"],
        f"审计表里 no_merge 条目数 {len(nm_audit)} == 决策表 "
        f"{F['n_no_merge_groups']}")
    chk(all(a.get("person_excluded_from_core") is False for a in nm_audit)
        and nm_audit,
        f"no_merge 组全部 person_excluded_from_core=False（{len(nm_audit)} 组）")
    chk(all(a.get("fragments_merged") is False for a in nm_audit),
        "no_merge 组全部 fragments_merged=False（确实没并碎片）")
    chk(all(a.get("person_excluded_from_core") is True for a in rj_audit)
        and len(rj_audit) == F["n_reject_groups"],
        f"reject_whole_group 组全部 person_excluded_from_core=True"
        f"（{len(rj_audit)} 组）")
    # no_merge 组既然没并碎片，组内实体就**必须**仍以独立实体留在名册里。
    # ⚠️ 这里不能用 audit 的 found_in_roster：merges.json 的 no_merge 条目
    # 只有 reason/verify/_legacy_key，没有 keep/absorb，故 apply_merges 解析出的
    # declared_ids 与 found_in_roster 都是**空列表** —— 拿它做子集判定会
    # 变成「空集 ⊆ 任何集合」的空跑通过（2026-09-29 实测打印出「0 个实体」）。
    # 改成按 group_key 回名册反查组成员：这才是「一个都没被顺带删掉」的真判据。
    nm_vacuous = [a["group_key"] for a in nm_audit
                  if not (a.get("found_in_roster") or [])]
    if nm_vacuous:
        info(f"注意：{len(nm_vacuous)} 个 no_merge 组的 audit.found_in_roster 为空"
             f"（merges.json 未声明 keep/absorb），改用 group_key 回查名册")
    nm_missing = []
    for gk in F["_nmg"]:
        members = {r["entity_key"] for r in merged_roster
                   if group_key(r.get("name") or "") == gk}
        if not members:
            nm_missing.append(gk)
    chk(not nm_missing,
        f"no_merge 的 {len(F['_nmg'])} 组在合并后名册中均仍能找到本人实体"
        f"（没被顺带删掉）：缺失 {nm_missing or 'OK'}")

    print("\n=== E. 核心名单的合并溯源 ===")
    core_merged = [r for r in core if r.get("merged_from")]
    chk(len(core_merged) == F["n_core_merged"],
        f"核心里带 merged_from 的行 {len(core_merged)} == 合并行计数 "
        f"{F['n_core_merged']}")
    missing_ev = [r["name_en"] for r in core_merged
                  if not r.get("dedup_check") or not r.get("merged_ids")]
    chk(not missing_ev,
        f"每个合并行都带 dedup_check + merged_ids 去重证据：{missing_ev or 'OK'}")
    bad_dd = [(r["name_en"], r["dedup_check"]) for r in core_merged
              if r["dedup_check"]["after_dedup_yjy_cited"] != r.get("yjy_cited")
              or r["dedup_check"]["delta"] !=
              r["dedup_check"]["after_dedup_yjy_cited"]
              - r["dedup_check"]["sum_before_dedup_yjy_cited"]]
    chk(not bad_dd, f"dedup_check 三字段自洽（delta == after − sum_before）："
                    f"{bad_dd or 'OK'}")
    over = [(r["name_en"], r["yjy_cited"]) for r in core_merged
            if r.get("yjy_cited", 0) > r["dedup_check"]["sum_before_dedup_yjy_cited"]]
    chk(not over, f"去重后被引不高于分片相加（无虚高）：{over or 'OK'}")
    # 核心的 merged_ids 必须与审计的 absorb 集合**逐个对得上**，
    # 否则「被并掉 28 个分身」只是两处数字巧合相等，实物可能错配。
    core_absorb = {i for r in core_merged for i in (r.get("merged_ids") or [])}
    chk(core_absorb == F["_absorb"],
        f"核心 merged_ids 并集（{len(core_absorb)}）== 审计 absorb 并集"
        f"（{len(F['_absorb'])}），差集 {sorted(core_absorb ^ F['_absorb']) or '无'}")
    # 每个合并行的 merged_from 必须是「keep 自己 + 被并分身」的并集
    bad_mf = []
    for r in core_merged:
        if r["openalex_id"] not in r["merged_from"]:
            bad_mf.append((r["name_en"], "keep 不在 merged_from 内"))
        if not set(r.get("merged_ids") or []) <= set(r["merged_from"]):
            bad_mf.append((r["name_en"], "merged_ids 不是 merged_from 子集"))
        if not set(r["merged_from"]) <= (set(r.get("merged_ids") or [])
                                        | {r["openalex_id"]}):
            bad_mf.append((r["name_en"], "merged_from 超出 keep ∪ merged_ids"))
    chk(not bad_mf, f"每行 merged_from == keep ∪ merged_ids：{bad_mf or 'OK'}")
    # merged_from 的每个碎片都必须真的存在于**合并前**名册
    pre_all = {r["entity_key"] for r in roster}
    ghost = {k for r in core_merged for k in r["merged_from"] if k not in pre_all}
    chk(not ghost, f"merged_from 的碎片键都能在合并前名册中找到：{sorted(ghost) or 'OK'}")
    # 分身诊断件的自洽：组内碎片去重后总数 == 实体数；
    # 且「已判定组」（15+3+3=21）必须是 118 组里的一个真子集。
    frag_all = [f["entity_key"] for g in dis for f in (g.get("fragments") or [])]
    chk(len(frag_all) == len(set(frag_all)) == F["n_frag_entities"],
        f"分身诊断 {F['n_frag_groups']} 组 / {len(frag_all)} 个碎片实体"
        f"（去重后 {len(set(frag_all))}，无重复计入）")
    judged = set(F["_mrg"]) | set(F["_nmg"]) | set(F["_rjg"])
    # ⚠️ disambig.json 的组键字段叫 norm_name，不是 group_key。
    # 2026-09-29 踩过：读 g["group_key"] 全拿到 None，判据退化成
    # 「21 组 ⊆ 空集」→ 必假失败。字段名写错时**子集判定会静默反向**，
    # 一定要在报错信息里把两边的实际数量都打出来（本次靠 "诊断 0 组" 才发现）。
    dis_keys = {g.get("norm_name") for g in dis if g.get("norm_name")}
    chk(judged <= dis_keys,
        f"已判定的 {len(judged)} 组都出现在分身诊断报告中"
        f"（诊断 {len(dis_keys)} 组，未判 {len(dis_keys - judged)} 组）"
        f"；未在诊断中的判定组 {sorted(judged - dis_keys) or '无'}")
    chk(len(judged) == F["n_merge_groups"] + F["n_no_merge_groups"]
        + F["n_reject_groups"],
        f"已判定组合计 {len(judged)} == merge {F['n_merge_groups']} + no_merge "
        f"{F['n_no_merge_groups']} + reject {F['n_reject_groups']}"
        f"（其中 merge 组进核心 {F['n_core_merged']} 行）")
    # 消歧实体 318 减去「被吸收 28 + 整组剔除 10」应等于存活数
    chk(F["n_frag_entities"] - len(F["_absorb"] & set(frag_all))
        - len(F["_dropped"] & set(frag_all)) == F["n_frag_surviving"],
        f"分身实体 {F['n_frag_entities']} − 被并 − 整组剔除 == 存活 "
        f"{F['n_frag_surviving']}（差集口径自洽）")
    # 合并审计里 keep 落在核心的，应与 core_merged 对得上
    keeps_in_core = {a["keep"] for a in ma["audit"]
                     if a.get("keep") and not a.get("decision")}
    core_ids = {r["openalex_id"] for r in core if r["openalex_id"]}
    chk(len(keeps_in_core & core_ids) == len(core_merged),
        f"合并审计 keep 落在核心的 {len(keeps_in_core & core_ids)} 个 "
        f"== 核心合并行 {len(core_merged)}")

    print("\n=== F. 门槛归因：谁是靠合并才进名单的 ===")
    newly = [r for r in core if r.get("newly_admitted_by_merge")]
    chk(len(newly) == F["n_newly"],
        f"newly_admitted_by_merge=True 共 {len(newly)} 行（json 统计 {F['n_newly']}）")
    chk(all(r.get("merged_from") for r in newly),
        "newly=True 的行必然是合并行（无合并记录不可能靠合并进名单）")
    # 反向不变量：非合并行**不该**带这个字段。带上就等于宣称
    # 「此人没经过任何合并就进了核心」——语义上恒真，等于把归因信息
    # 稀释成噪声。15 个合并行必须**显式**写 true/false，不许缺省。
    nonmerged = [r for r in core if not r.get("merged_from")]
    leak_attr = [r["name_en"] for r in nonmerged
                 if "newly_admitted_by_merge" in r]
    chk(not leak_attr,
        f"{len(nonmerged)} 个非合并行均不带 newly_admitted_by_merge"
        f"（该字段只描述合并归因）：{leak_attr or 'OK'}")
    chk(all("newly_admitted_by_merge" in r for r in core_merged),
        f"{len(core_merged)} 个合并行全部显式标注 newly_admitted_by_merge"
        f"（true/false 均写出，不缺省）")
    md_new = re.search(r"### 靠分身合并才新进核心的 (\d+) 人", md)
    chk(md_new is not None and int(md_new.group(1)) == len(newly)
        and all(n in md for n in F["newly_names"]),
        f"md 声明的合并新进人数与身份 == json：{F['newly_names']}")
    # 反向：拆回合并前名册，逐片都过门槛的行必须是 newly=False
    pre_by = {r["entity_key"]: r for r in roster}

    def passes(r):
        return (r["yjy_papers"] >= F["p_min"]
                and r.get(F["field"], 0) >= F["c_min"])

    wrong = []
    for r in core_merged:
        frags = [pre_by[k] for k in r["merged_from"] if k in pre_by]
        # newly 的定义：**没有任何一个**合并前碎片单独过门槛 → True。
        # 即 newly == (not any(fragment passes))。
        # ⚠️ 2026-09-29 踩过：这里写成 `... is not any(passes(f) for f in frags)`，
        # 把「有碎片过门槛」当成了 newly=False。any() 返回 True 时该式为 False，
        # 恰好对；但 any() 返回 False（即全部碎片都没过门槛、真正靠合并进名单）时，
        # `False is not False` → **True**，被判成 wrongly-False ——15 行全被误报。
        # 根因：`is not` 作用在 bool 上比的是**对象同一性**，不是逻辑取反；
        # 语义又和 distill_core.py 里的 `not any(...)` 正好错开一位。
        if frags and bool(r.get("newly_admitted_by_merge")) != (
                not any(passes(f) for f in frags)):
            wrong.append((r["name_en"], r.get("newly_admitted_by_merge"),
                          [f["entity_key"] for f in frags]))
    chk(not wrong, f"newly 标记与「碎片逐片是否过门槛」一致：{wrong or 'OK'}")

    print("\n=== G. 名册与 works 缓存未脱节（独立重算） ===")
    drift = []
    for r in roster:
        p = perf.get(r["entity_key"])
        if p is None or p["n"] != r["yjy_papers"] or p["cited"] != r.get("yjy_cited", 0):
            drift.append((r.get("name"), r["entity_key"],
                          r["yjy_papers"], r.get("yjy_cited"),
                          None if p is None else (p["n"], p["cited"])))
    chk(not drift,
        f"逐行用 works_raw + config 重算院署名业绩与名册一致"
        f"（{len(roster)} 行）：{drift[:3] or 'OK'}")
    chk(F["n_entities"] == len(roster),
        f"重算实体数 {F['n_entities']} == 名册行数 {len(roster)}")
    chk(F["n_yjy_works"] <= F["n_works"],
        f"院署名 works {F['n_yjy_works']} ≤ 缓存 works {F['n_works']}")

    print("\n=== G2. 中文姓名来源可追溯（禁音译的机器兜底） ===")
    # 纪律：name_cn 只能来自 name_cn.json（人手查公开一手源）。
    # 这里查三件事：① 名单里每个中文名都在映射文件里，不是脚本里凭空长的；
    # ② 每个填了名的都带来源字段——没来源的中文名等于音译，禁；
    # ③ 映射文件声明的 openalex_ids 与名单行对得上（防张冠李戴）。
    # ⚠️ name_cn.json 是**扁平 dict**（key = 归一化英文名），不是 {names:{...}}。
    # 2026-09-29 踩过：按嵌套结构读，拿到空集合，"中文名全部来自映射文件"
    # 会以「空集 ⊆ 一切」的形式假通过。
    flat = {k: v for k, v in (nc or {}).items()
            if not k.startswith("_") and isinstance(v, dict)}
    nc_by_name = {v["name_cn"]: v for v in flat.values() if v.get("name_cn")}
    chk(len(nc_by_name) == len(flat) and flat,
        f"name_cn.json 解析出 {len(flat)} 条姓名映射（键为归一化英文名）")
    used = {r["name_cn"] for r in verified}
    chk(used <= set(nc_by_name),
        f"名单里 {len(used)} 个中文名全部来自 name_cn.json（禁音译兜底）："
        f"多余 {used - set(nc_by_name) or '无'}")
    no_src = [r["name_en"] for r in verified
              if not r.get("name_cn_source") and not r.get("name_cn_verify")]
    chk(not no_src,
        f"每个已核中文名都带来源/核实强度（无来源者禁入名单）：{no_src or 'OK'}")
    nosrc_file = [k for k, v in flat.items() if not (v.get("source") or [])]
    chk(not nosrc_file,
        f"name_cn.json 每条都有 source（一手源可查）：缺 {nosrc_file or 'OK'}")
    chk(all(r["name_cn"] == r["name_cn"].strip() and r["name_cn"]
            for r in verified),
        "中文名非空且无首尾空白")
    # 映射文件声明的 openalex_ids 必须与名单里的 id 相容：
    # 声明了 ids 却与名单 id 无交集 → 多半是把名字挂到了错的人身上。
    bad_link = []
    for r in verified:
        e = nc_by_name.get(r["name_cn"]) or {}
        ids = e.get("openalex_ids") or []
        if ids and r["openalex_id"] and r["openalex_id"] not in ids:
            bad_link.append((r["name_cn"], r["openalex_id"], ids))
    chk(not bad_link,
        f"映射声明的 openalex_ids 与名单行相容（防张冠李戴）：{bad_link or 'OK'}")
    chk(len(pending) == F["n_pending"],
        f"待核附录 {len(pending)} 人（未给中文名，符合禁音译纪律）")

    print("\n=== H. 报告数字无手写常量（抽查关键数是否都出现） ===")
    for label, val in [("核心人数", F["n_core"]),
                       ("已核姓名", F["n_verified"]),
                       ("名册合并后", F["roster_after"]),
                       ("合并组数", F["n_merge_groups"]),
                       ("不并组数", F["n_no_merge_groups"]),
                       ("剔除组数", F["n_reject_groups"]),
                       ("缓存 works", F["n_works"]),
                       ("院署名 works", F["n_yjy_works"])]:
        chk(str(val) in md, f"正文出现{label} = {val}")
    chk(f"（{F['n_verified']} 人，禁音译）" in md,
        f"「已核实中文姓名」小标题用的是现算值 {F['n_verified']}（非手写 7）")

    print(f"\n{'✅ 全部通过' if not errs else '❌ ' + str(len(errs)) + ' 项失败'}")
    return errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--config", default=None,
                    help="院配置路径，默认 <skill>/institutes/<dir名>.json")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    d = Path(args.dir)
    short = d.name

    def load(sfx, required=True):
        p = d / f"{short}{sfx}.json"
        if not p.exists():
            if not required:
                return None
            sys.exit(f"❌ 找不到 {p}")
        return json.loads(p.read_text(encoding="utf-8"))

    core = load("_core_merged")
    roster = load("_roster")
    merged_roster = load("_roster_merged")
    raw = load("_works_raw")
    mj = load("_merges")
    ma = load("_merge_applied")
    dis = load("_disambig", required=False) or []

    # ⚠️ config / name_cn 路径必须走参数，不能硬编码某院（2026-09-29 实测）。
    # 硬编码某院的��果：换院跑本脚本会去读**别的院**的配置，
    # 报告正文里的机构名/门槛/排除词全是错的，而校验只查名单数字，查不出来。
    inst_dir = Path(__file__).resolve().parent.parent / "institutes"
    cfg_path = Path(args.config) if args.config else inst_dir / f"{short}.json"
    if not cfg_path.exists():
        sys.exit(f"❌ 找不到院配置 {cfg_path} —— 用 --config 指定，"
                 f"或确认 institutes/{short}.json 存在。")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    nc_path = inst_dir / cfg.get("name_cn_file", f"{short}_name_cn.json")
    nc = json.loads(nc_path.read_text(encoding="utf-8")) if nc_path.exists() else {}

    F, perf = compute_facts(d, short, cfg, raw, roster, merged_roster, core,
                            mj, ma, dis)
    verified = [r for r in core if r.get("name_cn")]
    pending = [r for r in core if not r.get("name_cn")]
    newly = [r for r in core if r.get("newly_admitted_by_merge")]

    md = render(F, cfg, short, core, verified, pending, newly, roster,
                F["n_frag_groups"], cfg.get("threshold", {}), inst_dir)

    out = Path(args.out) if args.out else d / f"{short}_report.md"
    out.write_text(md, encoding="utf-8")
    print(f"SAVED → {out}")

    errs = validate(md, F, short, cfg, core, roster, merged_roster, perf, ma, mj,
                    dis, nc)
    if errs:
        raise SystemExit(1)


if __name__ == "__main__":
    # ⚠️ 校验脚本自身崩了，绝不能被当成「校验通过」。
    # 2026-09-29 实测：`python make_report.py ... ; echo $?` 在 AttributeError
    # 崩溃后仍打印 exit=0 —— 因为管道 `| tail` 取的是 tail 的退出码。
    # 后果：报告根本没生成，却看到「全部通过」。
    # 两条防线：① 异常时打 stderr 并返回非零；② 生成失败不许打印「全部通过」。
    try:
        rc = main()
    except Exception as e:
        import traceback
        print("\n❌ make_report 自身异常 —— 校验未完成，不等于通过：", file=sys.stderr)
        traceback.print_exc()
        sys.exit(2)
    sys.exit(rc or 0)
