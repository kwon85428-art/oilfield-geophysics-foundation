# -*- coding: utf-8 -*-
"""
课题组批量蒸馏：王尚旭课题组 + 陈小宏课题组 12 名成员 CrossRef 爬取
核心纪律（2026-09-27 陈小宏案例沉淀）：
1. CrossRef query.author 是模糊匹配，必须逐篇核对作者全名列表
2. 常见中文名（Liu Yang / Zhou Hui / Wu Di）必须锚点共现（已知 CUPB 圈合作者）
3. 记录每篇论文的锚点共现情况，供下游人工复核
"""
import urllib.request, urllib.parse, json, time, sys, os

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(OUT_DIR, exist_ok=True)

MAILTO = "research@example.org"  # polite pool

# 课题组名单：姓名变体 + 消歧锚点（已知 CUPB 物探圈合作者，来自已验证的王尚旭/陈小宏 CrossRef 数据）
SCHOLARS = [
    # --- 王尚旭课题组 ---
    {"key": "yuan_sanyi", "zh": "袁三一", "group": "王尚旭课题组", "role": "教授·AI地震处理/储层预测/速度建模",
     "variants": [("Yuan", "Sanyi")],
     "anchors": ["Wang Shangxu", "Shangxu Wang", "Wei Jianxin", "Di Bangrang", "Zhao Jianguo", "Chai Xintao", "Wang Kunxi"],
     "common_name": False},
    {"key": "liu_yang", "zh": "刘洋", "group": "王尚旭课题组", "role": "教授·地震正反演与偏移/AI地震资料处理与解释",
     "variants": [("Liu", "Yang")],
     "anchors": ["Wang Shangxu", "Shangxu Wang", "Yuan Sanyi", "Wei Jianxin", "Di Bangrang", "Li Jingye", "Chen Xiaohong"],
     "common_name": True},
    {"key": "huang_handong", "zh": "黄捍东", "group": "王尚旭课题组（跨组：陈小宏课题组）", "role": "教授·复杂油气藏预测/碳酸盐岩缝洞储层",
     "variants": [("Huang", "Handong")],
     "anchors": ["Wang Shangxu", "Yuan Sanyi", "Chen Xiaohong", "Li Jingye", "Zhang Rong"],
     "common_name": False},
    {"key": "shen_jinsong", "zh": "沈金松", "group": "王尚旭课题组（跨组：陈小宏课题组）", "role": "教授·地震反演/储层预测",
     "variants": [("Shen", "Jinsong")],
     "anchors": ["Wang Shangxu", "Chen Xiaohong", "Li Jingye", "Fan Yuxiang"],
     "common_name": False},
    {"key": "zhou_hui", "zh": "周辉", "group": "王尚旭课题组", "role": "教授·地震波动理论",
     "variants": [("Zhou", "Hui")],
     "anchors": ["Wang Shangxu", "Yuan Sanyi", "Chen Xiaohong", "Li Jingye", "Wei Jianxin"],
     "common_name": True},
    {"key": "rao_ying", "zh": "饶莹", "group": "王尚旭课题组", "role": "教授·地震资料处理",
     "variants": [("Rao", "Ying")],
     "anchors": ["Wang Shangxu", "Chen Xiaohong", "Li Jingye", "Liu Guochang", "Yuan Cheng"],
     "common_name": True},
    {"key": "wang_shoudong", "zh": "王守东", "group": "王尚旭课题组", "role": "教授·地震资料解释",
     "variants": [("Wang", "Shoudong")],
     "anchors": ["Chen Xiaohong", "Li Jingye", "Gan Shuwei", "Chen Yangkang", "Wang Shangxu"],
     "common_name": False},
    {"key": "he_yanxiao", "zh": "贺艳晓", "group": "王尚旭课题组", "role": "副研究员·岩石物理",
     "variants": [("He", "Yanxiao"), ("He", "Yan-Xiao"), ("He", "Yan Xiao")],
     "anchors": ["Wang Shangxu", "Tang Genyang", "Zhao Jianguo", "Deng Jixin", "Yuan Sanyi"],
     "common_name": False},
    {"key": "wu_di", "zh": "吴迪", "group": "王尚旭课题组", "role": "副研究员·稀疏反演/逆时偏移",
     "variants": [("Wu", "Di")],
     "anchors": ["Wang Shangxu", "Yuan Sanyi", "Wei Jianxin", "Chen Xiaohong"],
     "common_name": True},
    {"key": "tang_genyang", "zh": "唐跟阳", "group": "王尚旭课题组", "role": "副教授·地震资料处理",
     "variants": [("Tang", "Genyang")],
     "anchors": ["Wang Shangxu", "Zhao Jianguo", "Chai Xintao", "Deng Jixin", "He Yanxiao", "He Yan-Xiao"],
     "common_name": False},
    # --- 陈小宏课题组 ---
    {"key": "li_xiangyang", "zh": "李向阳", "group": "陈小宏课题组", "role": "教授·地震勘探（各向异性/裂隙检测）",
     "variants": [("Li", "Xiang-Yang"), ("Li", "Xiangyang"), ("Li", "Xiang Yang")],
     "anchors": ["Wang Shangxu", "Chen Shuangquan", "Crampin", "Di Bangrang", "Wei Jianxin", "Chapman"],
     "common_name": True},
    {"key": "chen_shuangquan", "zh": "陈双全", "group": "陈小宏课题组（跨组：王尚旭课题组）", "role": "教授·地震各向异性/岩石物理/反演",
     "variants": [("Chen", "Shuangquan")],
     "anchors": ["Wang Shangxu", "Li Xiang-Yang", "Li Xiangyang", "Chapman", "Deng Jixin"],
     "common_name": False},
]

def name_matches(author, variants):
    """检查作者是否匹配目标变体（family + given，given 允许首字母缩写）"""
    fam = (author.get("family") or "").strip()
    giv = (author.get("given") or "").strip()
    if not fam:
        return False
    for vf, vg in variants:
        if fam.lower() != vf.lower():
            continue
        # given 匹配：全等 / 首字母 / 连字符折叠
        giv_norm = giv.lower().replace("-", "").replace(" ", "")
        vg_norm = vg.lower().replace("-", "").replace(" ", "")
        if giv_norm == vg_norm:
            return True
        # 首字母匹配：Y.-X. / YX / Y
        giv_initials = [p for p in giv.replace(".", " ").replace("-", " ").split() if p]
        vg_parts = [p for p in vg.replace("-", " ").split() if p]
        if giv_initials and vg_parts:
            if all(g[0].lower() == v[0].lower() for g, v in zip(giv_initials, vg_parts)):
                return True
    return False

def author_str(a):
    g = (a.get("given") or "").strip()
    f = (a.get("family") or "").strip()
    return (g + " " + f).strip() if (g or f) else (a.get("name") or "")

def fetch(url, retries=4):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": f"scholar-crawl/1.0 (mailto:{MAILTO})"})
            resp = urllib.request.urlopen(req, timeout=20)
            return json.loads(resp.read())
        except Exception as e:
            if i < retries - 1:
                wait = 2 + i * 3
                print(f"    retry {i+1} after {wait}s: {e}", file=sys.stderr)
                time.sleep(wait)
            else:
                raise

def crawl_scholar(s):
    q_author = f"{s['variants'][0][1]} {s['variants'][0][0]}"  # "Sanyi Yuan"
    params = {
        "query.author": q_author,
        "query.bibliographic": "seismic geophysics petroleum inversion reservoir",
        "rows": "60",
        "select": "DOI,title,author,container-title,published,is-referenced-by-count",
        "mailto": MAILTO,
    }
    url = "https://api.crossref.org/works?" + urllib.parse.urlencode(params)
    print(f"[{s['zh']}] querying: {q_author} ...")
    data = fetch(url)
    items = data.get("message", {}).get("items", [])
    total = data.get("message", {}).get("total-results", 0)

    hits, rejected = [], 0
    for item in items:
        authors = item.get("author", []) or []
        auth_strs = [author_str(a) for a in authors]
        # 1) 目标名必须在作者列表里（硬条件）
        if not any(name_matches(a, s["variants"]) for a in authors):
            rejected += 1
            continue
        # 2) 常见名必须锚点共现（硬条件）
        anchor_hits = [a for a in s["anchors"] if any(a.lower() in x.lower() for x in auth_strs)]
        if s["common_name"] and not anchor_hits:
            rejected += 1
            continue
        hits.append({
            "title": (item.get("title") or [""])[0],
            "doi": item.get("DOI", ""),
            "journal": (item.get("container-title") or [""])[0],
            "year": (item.get("published", {}).get("date-parts", [[0]]) or [[0]])[0][0],
            "cited": item.get("is-referenced-by-count", 0),
            "authors": auth_strs,
            "anchor_cooccur": anchor_hits,
        })
    hits.sort(key=lambda x: -x["cited"])
    return {"total_results": total, "returned": len(items), "verified_hits": len(hits), "rejected_no_name_or_anchor": rejected, "papers": hits}

def main():
    results = {}
    for s in SCHOLARS:
        try:
            r = crawl_scholar(s)
            r.update({"zh": s["zh"], "group": s["group"], "role": s["role"], "common_name": s["common_name"]})
            results[s["key"]] = r
            top = r["papers"][0] if r["papers"] else None
            top_str = f"top: {top['cited']}被引 {top['title'][:50]}" if top else "无命中"
            print(f"  -> {r['verified_hits']} verified / {r['returned']} returned / {r['rejected_no_name_or_anchor']} rejected | {top_str}")
        except Exception as e:
            print(f"  -> FAILED: {e}", file=sys.stderr)
            results[s["key"]] = {"error": str(e), "zh": s["zh"], "group": s["group"]}
        time.sleep(1.5)

    out = os.path.join(OUT_DIR, "group_members_crossref.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nsaved: {out}")

    # 汇总表
    print("\n" + "=" * 80)
    print(f"{'姓名':<8}{'组':<12}{'验证命中':<10}{'最高被引':<10}{'代表作'}")
    print("-" * 80)
    for k, r in results.items():
        if "error" in r:
            print(f"{r['zh']:<8}{r['group'][:10]:<12}ERROR")
            continue
        top = r["papers"][0] if r["papers"] else None
        tc = top["cited"] if top else 0
        tt = (top["title"][:40] + "...") if top and len(top["title"]) > 40 else (top["title"] if top else "—")
        print(f"{r['zh']:<8}{r['group'][:10]:<12}{r['verified_hits']:<12}{tc:<12}{tt}")

if __name__ == "__main__":
    main()
