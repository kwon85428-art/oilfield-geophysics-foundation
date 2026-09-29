#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""油田勘探开发研究院 · OpenAlex 机构口径抓取 + 院署名识别 + 作者聚合。

通用化版本：机构识别规则、城市名、同名机构排除词全部由 --config 指定的
institutes/<院>.json 驱动，换院只改 config 不改代码。

用法：
    python fetch_institute.py --config institutes/daqing.json [--outdir out/daqing]

输出：
    <outdir>/<short>_works_raw.json     上级公司全量 works（含完整 authorships）
    <outdir>/<short>_roster.json        院口径作者聚合名单
    <outdir>/<short>_roster.csv         同上 CSV

roster 字段语义（2026-09-29 收紧，踩过坑）：
    openalex_id        真实 author id（`A\d+`），**没有就是 None**。
                        绝不放姓名字符串——那会让「没分配到 id」和
                        「id 就是他名字」两种情况分不开，字段名在骗人。
    openalex_id_missing  True = OpenAlex 未给该作者分配 id
    entity_key         聚合主键 = openalex_id，缺失时为 `name:<归一化名>`
    total_cited        宽口径，恒定 = 作者在本次抓到的**全部**论文被引之和
                        （含其挂别家单位的论文）。**不随配置变脸。**
    两者同时落盘、语义固定。门槛与排序用哪个，由 config.threshold.cited_basis
    决定，裁决逻辑只在 cited_basis.py 一处；任何脚本都不许自己写口径字面量。

⚠️ 开跑前必审 config 的 rival_exclude_tokens（同名机构排除词），
   缺失会重蹈污染覆辙。见 references/institute-pollution-control.md。
"""
import argparse
import csv
import json
import re
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from author_identity import author_entity  # noqa: E402  身份口径唯一实现处
from cited_basis import (  # noqa: E402  被引口径唯一裁决点
    normalize_basis,
    resolve_cited_field,
)

PER_PAGE = 200
SELECT = ("id,doi,title,publication_year,cited_by_count,authorships,"
          "primary_location")
MAILTO = "research@example.com"
UA = {"User-Agent": f"research/1.0 (mailto:{MAILTO})", "Accept": "application/json"}


def load_config(path):
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    # 必填校验——缺 rival_exclude_tokens 不许跑
    inst = cfg.get("institution", {})
    ident = cfg.get("identify", {})
    missing = []
    for k in ("name", "short", "openalex_parent_id"):
        if not inst.get(k):
            missing.append("institution." + k)
    for k in ("city_tokens", "institute_patterns_en", "institute_patterns_cn"):
        if not ident.get(k):
            missing.append("identify." + k)
    if not ident.get("rival_exclude_tokens"):
        sys.exit(
            "❌ config 缺 identify.rival_exclude_tokens（同名机构排除词）。\n"
            "   换院前先查全国同名/近名机构及其地址特征，见 "
            "references/institute-pollution-control.md。\n   不许跳过这步开跑。")
    if missing:
        sys.exit("❌ config 缺字段：" + ", ".join(missing))
    return cfg


def build_matchers(ident):
    """从 config 构造四重约束识别器。

    返回 6 元组：(rival, yjy_en, yjy_cn, city, cross, relax_city)。
    cross 由可选字段 cross_group_tokens 编译；缺省为 None（不参与判定，向后兼容）。
    relax_city 由可选字段 relax_city_constraint 编译；缺省为 False（大庆口径）。

    relax_city=True 适用场景（2026-09-29 中石化物探院实测新增）：
        院在 OpenAlex 有独立实体且院名全国唯一，不存在「几十家同名油田院」
        的同名污染。此时 city 共现约束是净负担——实测 588 篇里 555 条署名
        只写院名不带城市（`Sinopec Geophysical Research Institute` 177 条），
        全部被 city 约束误杀，院署名 works 从 549 掉到 345。
        此时只保留 rival（同名机构）+ cross（跨集团双署名）两道防线。

    ⚠️ relax_city=True 的**前提是 rival 已覆盖同体系兄弟院**（2026-09-29 实测）：
        中石化物探院关掉 city 后，rival 词表里原只按「带地名的通用名」写
        （Nanjing Geophysical Research Institute），漏掉了两种真实污染——
        「Geophysical Research Institute, Jiangsu Oilfield Company」（江苏油田
        物探院，邮箱 liulm.jsyt@sinopec.com）与「Shengli Geophysical Research
        Institute」（胜利物探院，shangwei.slyt@sinopec.com）。两者同在南京/东营、
        同属中石化，邮箱后缀 jsyt/syty 与本院 swty 同格式，肉眼极难分辨。
        **判据：同集团兄弟院优先按油田公司名排除，不要只按「XX地球物理研究院」
        这类通用名排除——通用名会把本院自己一起排除掉。**
    """
    rival = re.compile("|".join(re.escape(t) for t in ident["rival_exclude_tokens"]), re.I)
    yjy_en = re.compile("|".join(ident["institute_patterns_en"]), re.I)
    yjy_cn = re.compile("|".join(ident["institute_patterns_cn"]), re.I)
    city = re.compile("|".join(re.escape(t) for t in ident["city_tokens"]), re.I)
    cross = None
    if ident.get("cross_group_tokens"):
        cross = re.compile("|".join(re.escape(t) for t in ident["cross_group_tokens"]),
                           re.I)
    relax_city = bool(ident.get("relax_city_constraint"))
    return rival, yjy_en, yjy_cn, city, cross, relax_city


def is_institute(affs, rival, yjy_en, yjy_cn, city, cross=None, relax_city=False):
    """四重约束判定。

    ① 排除同名机构（rival_exclude_tokens）
    ② 排除跨集团双署名（cross_group_tokens）—— v1.1.0 新增
    ③ 英文命中须共现城市名 —— relax_city=True 时跳过
    ④ 中文院名须共现城市名或英文院名 —— relax_city=True 时跳过

    v1.1.0 修的 bug：OpenAlex 会把两个单位的署名拼进同一条
    raw_affiliation_strings（实测 "CNOOC China Limited, Tianjin Branch
    | Exploration and Development Research Institute, PetroChina Daqing
    Oilfield Company Limited, Daqing"）。此时 rival 词表没命中（CNOOC 不在
    rival 里）、city 共现成立（串里有 Daqing），双署名就被算成本院产出，
    且 city 这道防线对它完全失效。见 institutes/daqing.json 的 dual_aff_note。

    v1.2.0（2026-09-29）：新增 relax_city，见 build_matchers 的 docstring。
    """
    joined = " | ".join(affs or [])
    if not joined:
        return False
    if rival.search(joined):
        return False
    if cross is not None and cross.search(joined):
        return False
    cn = bool(yjy_cn.search(joined))
    en = bool(yjy_en.search(joined))
    if not (cn or en):
        return False
    if relax_city:
        return True
    if en and not city.search(joined):
        return False
    if cn and not city.search(joined) and not yjy_en.search(joined):
        return False
    return True


def has_city(affs, city):
    return bool(city.search(" | ".join(affs or [])))


def api(url, tries=4):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            return json.load(urllib.request.urlopen(req, timeout=60))
        except Exception as e:
            last = e
            time.sleep(4 * (i + 1))
    raise last


def fetch_works(inst_id):
    base = "https://api.openalex.org/works"
    total = api(f"{base}?filter=institutions.id:{inst_id}&per-page=1")["meta"]["count"]
    print(f"上级公司 {inst_id} 总 works = {total}", flush=True)

    all_w, cursor, page = [], "*", 0
    while True:
        u = (f"{base}?filter=institutions.id:{inst_id}&per-page={PER_PAGE}"
             f"&cursor={cursor}&select={SELECT}")
        d = api(u)
        res = d["results"]
        all_w.extend(res)
        page += 1
        print(f"  page {page}: +{len(res)} (cum {len(all_w)})", flush=True)
        cursor = d["meta"].get("next_cursor")
        if not cursor or not res:
            break
        time.sleep(0.5)
    print(f"抓取完成：{len(all_w)} 篇", flush=True)
    return all_w


def aggregate(all_w, matchers):
    """把 works 聚合成作者级记录。**本函数与被引口径无关。**

    落两个语义固定的数字，任何配置都改不了它们：
        cited     -> total_cited  宽口径：该作者在本次抓到的全部论文被引
        yjy_cited -> yjy_cited    院口径：仅院署名命中的论文被引

    ⚠️ 2026-09-29 修掉的漂移：旧签名是 `aggregate(all_w, matchers,
    cited_basis="all")`，cited_basis="yjy" 时 `cited` 也只累院署名，
    于是 `total_cited == yjy_cited`，字段名与内容脱钩。下游若此时选
    "宽口径"就会拿到院口径数字却顶着宽口径标签。**采集层不许知道
    门槛口径这件事**——它只负责如实落两个数，口径由cited_basis.py
    在下游裁决。
    """
    rival, yjy_en, yjy_cn, city, cross, relax_city = matchers
    authors = defaultdict(lambda: {
        "name": "", "name_variants": Counter(), "aff_variants": Counter(),
        "yjy_papers": 0, "city_papers": 0, "cited": 0, "yjy_cited": 0,
        "years": [], "venues": Counter(), "ids": Counter(),
        "sample_titles": [], "all_yjy_titles": [], "dual_aff": 0,
        "cross_group_papers": 0,
    })
    yjy_works = 0
    n_cross = 0       # cross 词表命中、且含院名的署名（含本来就因 city 不成立而不会被算的）
    n_blocked = 0     # 其中「旧三重约束会通过、加 cross 后不再通过」的——真正的剔除量
    blocked_ids = set()

    for w in all_w:
        cited = w.get("cited_by_count") or 0
        yr = w.get("publication_year") or 0
        pl = w.get("primary_location") or {}
        venue = ((pl.get("source") or {}).get("display_name")) or ""
        any_yjy = False
        for a in w.get("authorships", []):
            author = a.get("author") or {}
            # ⚠️ 身份主键取author_entity().entity_key，不要在这里手写
            #    `aid or display_name` —— 那会把姓名字符串塞进 openalex_id 字段，
            #    2026-09-29 实测 713 行里 97 行中招。字段名在骗人是很难查的 bug。
            ent = author_entity(author)
            key = ent["entity_key"]
            aid = ent["openalex_id"] or ""
            name = ent["display_name"]
            affs = a.get("raw_affiliation_strings") or []
            if not affs:
                affs = [i.get("display_name", "") for i in a.get("institutions", [])]
            joined = " | ".join(affs or [])
            yjy = is_institute(affs, rival, yjy_en, yjy_cn, city, cross, relax_city)
            # 被 cross_group 挡掉的署名单独记账——它是虚高院署名的来源，
            # 不是「合作论文」，不能混进 dual_aff。
            #
            # 两个计数必须分开，否则会把「本来就会被 city 共现挡掉」的署名
            # 算成 cross 的功劳。2026-09-27 实测：2109 篇里有 7 条「含院名 +
            # 跨集团词」的署名，但其中 4 条无城市共现、旧三重约束本就不通过，
            # 真正被 cross 剔除的只有 3 条（同一篇 32 人综述上的 CNOOC 双署名）。
            # n_cross 是「cross 词表覆盖面」，n_blocked 才是「修复影响面」。
            if cross is not None and cross.search(joined) and not yjy \
                    and (yjy_en.search(joined) or yjy_cn.search(joined)):
                n_cross += 1
                authors[key]["cross_group_papers"] += 1
                if is_institute(affs, rival, yjy_en, yjy_cn, city, None, relax_city):
                    n_blocked += 1
                    blocked_ids.add(w.get("id", ""))
            if yjy:
                any_yjy = True
            rec = authors[key]
            rec["name"] = name
            rec["name_variants"][name] += 1
            if affs:
                rec["aff_variants"][" | ".join(affs)[:200]] += 1
            # 两个口径各自无条件累加，谁也不看配置。
            rec["cited"] += cited          # 宽口径：全部论文
            if yr:
                rec["years"].append(yr)
            if venue:
                rec["venues"][venue] += 1
            rec["ids"][(ent["orcid"], aid)] += 1
            if yjy:
                rec["yjy_papers"] += 1
                rec["yjy_cited"] += cited
                if rival.search(joined):
                    rec["dual_aff"] += 1
                if len(rec["sample_titles"]) < 8:
                    rec["sample_titles"].append((yr, (w.get("title") or "")[:110]))
                # 全量院署名标题：领域分类必须吃全量，不能只吃 sample_titles。
                # 2026-09-29 踩过——sample_titles 硬截断 8 条，一个 51 篇论文
                # 的作者只用 8 条做词频决胜负，导致 07(AI交叉) 方向在全量池里
                # 有 39 次命中却被挤成 0 人，看起来像"院里没人做 AI"，
                # 实际是采样丢信息。sample_titles 只用于人看，不用于机器判。
                rec["all_yjy_titles"].append((yr, w.get("title") or ""))
            if has_city(affs, city):
                rec["city_papers"] += 1
        if any_yjy:
            yjy_works += 1

    print(f"含本院署名的 works = {yjy_works}", flush=True)
    if cross is not None:
        n_cross_people = sum(1 for r in authors.values() if r["cross_group_papers"])
        print(f"跨集团词表命中的院名署名 = {n_cross} 条 / {n_cross_people} 人"
              f"（覆盖面）", flush=True)
        print(f"其中真正被剔除的 = {n_blocked} 条 / {len(blocked_ids)} 篇论文"
              f"（旧三重约束本会通过、加 cross 后不再通过）", flush=True)
        if n_cross - n_blocked:
            print(f"  其余 {n_cross - n_blocked} 条无城市共现，旧约束本就不通过，"
                  f"与 cross 无关", flush=True)
    return authors


def to_roster(authors, sort_field="yjy_cited"):
    """作者记录 -> roster 行。

    `sort_field` 只是**排序**用的字段名，默认院口径：院名单按外单位业绩
    排会把挂别家的高被引作者领到榜首，那不是本院的业绩榜。
    （2026-09-29 修正：这里原先既没有 `sort_key` 参数，排序里又读一个
    从没被赋值过的 `_sort_cited`，注释描述的是一个不存在的开关。）
    """
    roster = []
    for key, r in authors.items():
        if r["yjy_papers"] == 0:
            continue
        orcid, oid = r["ids"].most_common(1)[0][0]
        years = sorted(y for y in r["years"] if y)
        real = bool(re.fullmatch(r"A\d+", oid or ""))
        roster.append({
            # 语义严格：要么是真OpenAlex ID（A\d+），要么是 None。
            # 绝不放姓名字符串——放进去就分不清"这个专家没分配到 id"
            # 和"这个专家的 id 就是他名字"。
            "openalex_id": oid if real else None,
            "openalex_id_missing": not real,
            "entity_key": key,
            "display_name_fallback": None if real else (r["name"] or key),
            "orcid": orcid or "",
            "name": r["name"],
            "name_variants": [n for n, _ in r["name_variants"].most_common(8)],
            "yjy_papers": r["yjy_papers"],
            "dual_aff_papers": r["dual_aff"],
            "cross_group_papers": r["cross_group_papers"],
            "city_papers": r["city_papers"],
            "total_cited": r["cited"],
            "yjy_cited": r["yjy_cited"],
            "year_min": min(years) if years else None,
            "year_max": max(years) if years else None,
            "top_venues": [v for v, _ in r["venues"].most_common(5)],
            "aff_signatures": [a for a, _ in r["aff_variants"].most_common(4)],
            "sample_titles": r["sample_titles"],
            "all_yjy_titles": r["all_yjy_titles"],
        })
    # 排序字段必须真实存在，否则 sort key 静默取 0 = 全体并列，
    # "排序失效"长得和"所有人被引一样"一模一样。
    if sort_field not in ("total_cited", "yjy_cited"):
        raise SystemExit(f"❌ sort_field={sort_field!r} 非法，只能是 "
                         f"total_cited / yjy_cited")
    roster.sort(key=lambda x: ((x.get(sort_field) or 0) * -1,
                               x["yjy_papers"] * -1))
    return roster


def write_csv(path, roster):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["name", "openalex_id", "openalex_id_missing", "entity_key",
                     "orcid", "yjy_papers", "city_papers", "total_cited",
                     "yjy_cited", "year_min", "year_max", "top_venue",
                     "name_variants", "aff_signature"])
        for r in roster:
            wr.writerow([r["name"], r["openalex_id"] or "",
                         "Y" if r["openalex_id_missing"] else "N",
                         r["entity_key"], r["orcid"], r["yjy_papers"],
                         r["city_papers"], r["total_cited"], r["yjy_cited"],
                         r["year_min"], r["year_max"],
                         (r["top_venues"] or [""])[0],
                         "; ".join(r["name_variants"]),
                         (r["aff_signatures"] or [""])[0]])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="institutes/<院>.json")
    ap.add_argument("--outdir", default=None, help="输出目录，默认 <config 同级>/out_<short>")
    ap.add_argument("--reuse-raw", action="store_true",
                    help="若 works_raw.json 已存在则直接复用，不重新调 OpenAlex。"
                         "调config 重跑时务必带上——OpenAlex 免费额度按 IP 共享"
                         "每日耗尽（2026-09-29 实测撞过），重抓是纯浪费。")
    ap.add_argument("--sort-field", default=None,
                    choices=["total_cited", "yjy_cited"],
                    help="roster.json 排序字段（只影响文件内行序）。"
                         "缺省跟随 config.threshold.cited_basis。")
    args = ap.parse_args()

    cfg = load_config(args.config)
    inst, ident = cfg["institution"], cfg["identify"]
    th = cfg.get("threshold", {})
    # 门槛与排序用哪个口径，只从 config 读。命令行不再提供 cited-basis：
    # 两个入口给同一个语义有两种写法，必然漂移过一次（2026-09-29 已修）。
    basis, field = resolve_cited_field(th)
    # 归一化后写回配置：历史别名（如 total）当场变成规范词，
    # 免得下游脚本各自猜一遍。
    if th.get("cited_basis") != basis:
        th["cited_basis"] = basis
    sort_field = args.sort_field or field
    outdir = Path(args.outdir) if args.outdir else Path(args.config).parent / f"out_{inst['short']}"
    outdir.mkdir(parents=True, exist_ok=True)

    matchers = build_matchers(ident)
    raw_path = outdir / f"{inst['short']}_works_raw.json"
    if args.reuse_raw and raw_path.exists():
        works = json.loads(raw_path.read_text(encoding="utf-8"))
        print(f"复用已缓存 works_raw：{len(works)} 篇（--reuse-raw）", flush=True)
    else:
        works = fetch_works(inst["openalex_parent_id"])
        raw_path.write_text(json.dumps(works, ensure_ascii=False), encoding="utf-8")
    relax = bool(ident.get("relax_city_constraint"))
    print(f"city 共现约束 = {'关闭(relax_city)' if relax else '启用(大庆口径)'}", flush=True)
    print(f"门槛被引口径 = {field}（cited_basis={basis}；两口径恒定同时落盘）",
          flush=True)

    authors = aggregate(works, matchers)
    roster = to_roster(authors, sort_field=sort_field)
    print(f"本院口径作者 = {len(roster)} 人（门槛 ≥1 篇院署名）", flush=True)
    n_noid = sum(1 for r in roster if r["openalex_id_missing"])
    print(f"  其中 OpenAlex 未分配 author.id = {n_noid} 人（entity_key 走 name: 前缀）",
          flush=True)

    (outdir / f"{inst['short']}_roster.json").write_text(
        json.dumps(roster, ensure_ascii=False, indent=1), encoding="utf-8")
    write_csv(outdir / f"{inst['short']}_roster.csv", roster)

    core = [x for x in roster
            if x["yjy_papers"] >= th.get("yjy_min", 2)
            and x[field] >= th.get("cited_min", 30)]
    n_drift = sum(1 for x in roster
                  if x["total_cited"] != x.get("yjy_cited", 0))
    print(f"\n门槛 yjy>={th.get('yjy_min',2)} 且 {field}>={th.get('cited_min',30)}"
          f"（口径={basis}）：核心 {len(core)} 人", flush=True)
    print(f"两口径漂移 = {n_drift}/{len(roster)} 人"
          f"（total_cited != yjy_cited，即该作者有挂别家单位的论文）", flush=True)
    if basis == "all":
        print(f"  ⚠️ 当前用宽口径卡门槛：这 {n_drift} 人的门槛业绩里含外单位被引，"
              f"改用 yjy 口径核心会缩到 {sum(1 for x in roster if x['yjy_papers'] >= th.get('yjy_min', 2) and x['yjy_cited'] >= th.get('cited_min', 30))} 人",
              flush=True)
    print(f"\n=== Top 20（按 {field} 排序）===")
    for r in roster[:20]:
        v = r["top_venues"][0] if r["top_venues"] else ""
        flag = "  [无id]" if r["openalex_id_missing"] else ""
        print(f"  {r['name'][:28]:28s} yjy={r['yjy_papers']:3d} "
              f"all={r['total_cited']:5d} yjy_cited={r['yjy_cited']:5d} "
              f"{r['year_min']}-{r['year_max']} | {v}{flag}")
    print(f"\nSAVED → {outdir}")


if __name__ == "__main__":
    main()
