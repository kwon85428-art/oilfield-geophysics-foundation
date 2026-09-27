#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""油田勘探开发研究院 · OpenAlex 机构口径抓取 + 院署名识别 + 作者聚合。

通用化版本：机构识别规则、城市名、同名机构排除词全部由 --config 指定的
institutes/<院>.json 驱动，换院只改 config 不改代码。

用法：
    python fetch_institute.py --config institutes/daqing.json [--outdir out/daqing]

输出：
    <outdir>/<short>_works_raw.json     上级公司全量 works（含完整 authorships）
    <outdir>/<short>_roster.json        院口径作者聚合名单
    <outdir>/<short>_roster.csv         同上 CSV

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

    返回 5 元组：(rival, yjy_en, yjy_cn, city, cross)。
    cross 由可选字段 cross_group_tokens 编译；缺省为 None（不参与判定，向后兼容）。
    """
    rival = re.compile("|".join(re.escape(t) for t in ident["rival_exclude_tokens"]), re.I)
    yjy_en = re.compile("|".join(ident["institute_patterns_en"]), re.I)
    yjy_cn = re.compile("|".join(ident["institute_patterns_cn"]), re.I)
    city = re.compile("|".join(re.escape(t) for t in ident["city_tokens"]), re.I)
    cross = None
    if ident.get("cross_group_tokens"):
        cross = re.compile("|".join(re.escape(t) for t in ident["cross_group_tokens"]),
                           re.I)
    return rival, yjy_en, yjy_cn, city, cross


def is_institute(affs, rival, yjy_en, yjy_cn, city, cross=None):
    """四重约束判定。

    ① 排除同名机构（rival_exclude_tokens）
    ② 排除跨集团双署名（cross_group_tokens）—— v1.1.0 新增
    ③ 英文命中须共现城市名
    ④ 中文院名须共现城市名或英文院名

    v1.1.0 修的 bug：OpenAlex 会把两个单位的署名拼进同一条
    raw_affiliation_strings（实测 "CNOOC China Limited, Tianjin Branch
    | Exploration and Development Research Institute, PetroChina Daqing
    Oilfield Company Limited, Daqing"）。此时 rival 词表没命中（CNOOC 不在
    rival 里）、city 共现成立（串里有 Daqing），双署名就被算成本院产出，
    且 city 这道防线对它完全失效。见 institutes/daqing.json 的 dual_aff_note。
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
    rival, yjy_en, yjy_cn, city, cross = matchers
    authors = defaultdict(lambda: {
        "name": "", "name_variants": Counter(), "aff_variants": Counter(),
        "yjy_papers": 0, "city_papers": 0, "cited": 0, "years": [],
        "venues": Counter(), "ids": Counter(), "sample_titles": [],
        "dual_aff": 0, "cross_group_papers": 0,
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
            # OpenAlex 返回的是全 URL（https://openalex.org/A5047240344），
            # 统一取末段裸 ID。不统一会导致与已交付名单的 openalex_id 对不上，
            # 做交叉校验时会「交集为 0」，看起来像数据全错，其实只是 ID 形式不同。
            aid = (author.get("id") or "").split("/")[-1]
            key = aid or author.get("display_name") or "unknown"
            name = author.get("display_name") or ""
            affs = a.get("raw_affiliation_strings") or []
            if not affs:
                affs = [i.get("display_name", "") for i in a.get("institutions", [])]
            joined = " | ".join(affs or [])
            yjy = is_institute(affs, rival, yjy_en, yjy_cn, city, cross)
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
                if is_institute(affs, rival, yjy_en, yjy_cn, city, None):
                    n_blocked += 1
                    blocked_ids.add(w.get("id", ""))
            if yjy:
                any_yjy = True
            rec = authors[key]
            rec["name"] = name
            rec["name_variants"][name] += 1
            if affs:
                rec["aff_variants"][" | ".join(affs)[:200]] += 1
            rec["cited"] += cited
            if yr:
                rec["years"].append(yr)
            if venue:
                rec["venues"][venue] += 1
            rec["ids"][(author.get("orcid") or "", aid)] += 1
            if yjy:
                rec["yjy_papers"] += 1
                if rival.search(joined):
                    rec["dual_aff"] += 1
                if len(rec["sample_titles"]) < 5:
                    rec["sample_titles"].append((yr, (w.get("title") or "")[:90]))
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


def to_roster(authors):
    roster = []
    for key, r in authors.items():
        if r["yjy_papers"] == 0:
            continue
        orcid, oid = r["ids"].most_common(1)[0][0]
        years = sorted(y for y in r["years"] if y)
        roster.append({
            "openalex_id": oid or key,
            "orcid": orcid or "",
            "name": r["name"],
            "name_variants": [n for n, _ in r["name_variants"].most_common(6)],
            "yjy_papers": r["yjy_papers"],
            "dual_aff_papers": r["dual_aff"],
            "cross_group_papers": r["cross_group_papers"],
            "city_papers": r["city_papers"],
            "total_cited": r["cited"],
            "year_min": min(years) if years else None,
            "year_max": max(years) if years else None,
            "top_venues": [v for v, _ in r["venues"].most_common(5)],
            "aff_signatures": [a for a, _ in r["aff_variants"].most_common(4)],
            "sample_titles": r["sample_titles"],
        })
    roster.sort(key=lambda x: (-x["total_cited"], -x["yjy_papers"]))
    return roster


def write_csv(path, roster):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["name", "openalex_id", "orcid", "yjy_papers", "city_papers",
                     "total_cited", "year_min", "year_max", "top_venue",
                     "name_variants", "aff_signature"])
        for r in roster:
            wr.writerow([r["name"], r["openalex_id"], r["orcid"], r["yjy_papers"],
                         r["city_papers"], r["total_cited"], r["year_min"],
                         r["year_max"], (r["top_venues"] or [""])[0],
                         "; ".join(r["name_variants"]),
                         (r["aff_signatures"] or [""])[0]])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="institutes/<院>.json")
    ap.add_argument("--outdir", default=None, help="输出目录，默认 <config 同级>/out_<short>")
    args = ap.parse_args()

    cfg = load_config(args.config)
    inst, ident = cfg["institution"], cfg["identify"]
    outdir = Path(args.outdir) if args.outdir else Path(args.config).parent / f"out_{inst['short']}"
    outdir.mkdir(parents=True, exist_ok=True)

    matchers = build_matchers(ident)
    works = fetch_works(inst["openalex_parent_id"])
    (outdir / f"{inst['short']}_works_raw.json").write_text(
        json.dumps(works, ensure_ascii=False), encoding="utf-8")

    authors = aggregate(works, matchers)
    roster = to_roster(authors)
    print(f"本院口径作者 = {len(roster)} 人（门槛 ≥1 篇院署名）", flush=True)

    (outdir / f"{inst['short']}_roster.json").write_text(
        json.dumps(roster, ensure_ascii=False, indent=1), encoding="utf-8")
    write_csv(outdir / f"{inst['short']}_roster.csv", roster)

    th = cfg.get("threshold", {})
    core = [x for x in roster
            if x["yjy_papers"] >= th.get("yjy_min", 2)
            and x["total_cited"] >= th.get("cited_min", 30)]
    print(f"\n门槛 yjy>={th.get('yjy_min',2)} 且 cited>={th.get('cited_min',30)}："
          f"核心 {len(core)} 人", flush=True)
    print(f"\n=== Top 20（按被引）===")
    for r in roster[:20]:
        v = r["top_venues"][0] if r["top_venues"] else ""
        print(f"  {r['name'][:28]:28s} yjy={r['yjy_papers']:3d} "
              f"cited={r['total_cited']:5d} {r['year_min']}-{r['year_max']} | {v}")
    print(f"\nSAVED → {outdir}")


if __name__ == "__main__":
    main()
