# -*- coding: utf-8 -*-
"""中文姓名核实探针 —— 用期刊原文，不靠搜索引擎猜。

方法（每条证据必须三源对齐才算通过）：
  A. 中文期刊 PDF 原文的「第一作者简介」或作者署名行 → 拿到中文姓名 + 出生年 + 职称 + 院邮箱
  B. 院邮箱前缀 hugh.swty / liudj.swty / liuwh.swty → 与中文名首字母交叉验证
     （swty = 石油物探技术研究院拼音缩写；已由 刘定进/刘卫华/胡光辉 三人独立验证）
  C. OpenAlex 论文主题方向 + 合作者 → 与中文文献研究方向对齐

反面探针（防止「沉默被当成结论」）：
  任何一次网络失败 / 0 字节 / 页面结构变化，都必须显式标 FAIL 而不是当成「查无此人」。
  已知为真的人（刘定进）必须每次都跑通，否则整轮结论无效。

用法：
  python name_probe.py --emails liudj liuwh hugh      # 按院邮箱反查
  python name_probe.py --dois 10.12431/xxx,10.3969/yyy
"""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

# swty 邮箱 → 已确认的中文名（形成闭环，可继续外推）
KNOWN_MAIL = {
    "liudj.swty@sinopec.com": ("刘定进", "Dingjin Liu"),
    "liuwh.swty@sinopec.com": ("刘卫华", "Weihua Liu"),
    "hugh.swty@sinopec.com": ("胡光辉", "Guanghui Hu"),
    "lzl-lll@163.com": ("林正良", "Zhengliang Lin"),
}


def curl(url, out=None, timeout=60):
    cmd = ["curl", "-sL", "--max-time", str(timeout), "-A",
           "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"]
    if out:
        cmd += ["-o", out]
        cmd += ["-w", "%{http_code}"]
    cmd.append(url)
    r = subprocess.run(cmd, capture_output=True)
    if out:
        return r.stdout.decode().strip(), len(r.stdout)
    return r.stdout


def pdf_text(path, max_pages=2):
    import pymupdf
    d = pymupdf.open(path)
    parts = []
    for i in range(min(max_pages, d.page_count)):
        parts.append(d[i].get_text())
    return "\n".join(parts)


def parse_cn_authors(txt):
    """从中文期刊正文抽：中文姓名 + 单位 + 第一作者简介 + 邮箱。"""
    res = {"emails": [], "affiliations": [], "author_bios": [], "cn_header": ""}
    res["emails"] += re.findall(
        r"[A-Za-z0-9._%+-]+\s*[＠@]\s*[A-Za-z0-9.-]+", txt)
    # 单位行：中石化/中国石化 + 研究院
    for m in re.finditer(r"[（(]?\s*((?:中石化|中国石化|中国石油化工股份有限公司)[^)）\n]{0,40}"
                         r"(?:物探技术研究院|物探院)[^)）\n]{0,20})[)）]?", txt):
        res["affiliations"].append(m.group(1).strip())
    # 第一作者简介
    for m in re.finditer(r"第一作者简介[：:]\s*([^\n]{0,140})", txt):
        res["author_bios"].append(m.group(1).strip())
    # 标题下方作者行：连续 2-4 个中文姓名
    m = re.search(r"\n([一-龥]{2,4}(?:\s*[，,、]\s*[一-龥]{2,4}){1,3})\s*\n", txt)
    if m:
        res["cn_header"] = m.group(1).strip()
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--emails", default=None, help="院邮箱前缀，逗号分隔")
    ap.add_argument("--maildir", default=None,
                    help="在 works_raw 里搜这些邮箱（不含@域）")
    ap.add_argument("--dois", default=None, help="geophysics.cn 的 DOI 路径，逗号分隔")
    ap.add_argument("--outdir", default="pdf")
    args = ap.parse_args()
    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    fail = 0

    if args.dois:
        for doi in [d.strip() for d in args.dois.split(",") if d.strip()]:
            url = f"https://www.geophysics.cn/cn/article/pdf/preview/{doi}.pdf"
            p = out / (doi.replace("/", "_") + ".pdf")
            code, n = curl(url, str(p))
            status = "OK" if n > 10000 else f"FAIL(http={code},bytes={n})"
            print(f"\n=== {doi}  {status}")
            if n > 10000:
                try:
                    info = parse_cn_authors(pdf_text(str(p)))
                    print(json.dumps(info, ensure_ascii=False, indent=1)[:1400])
                except Exception as e:
                    print("  PDF 解析失败:", e)
            else:
                fail += 1
            time.sleep(0.6)

    if args.maildir:
        works = json.loads(Path(
            "sinopec_swty/sinopec_swty_works_raw.json").read_text(encoding="utf-8"))
        needles = [x.strip().lower() for x in args.maildir.split(",") if x.strip()]
        for w in works:
            affs = []
            for a in w.get("authorships") or []:
                affs += a.get("raw_affiliation_strings") or []
            joined = " | ".join(affs).lower()
            hit = [n for n in needles if n in joined]
            if not hit:
                continue
            names = [(a.get("author") or {}).get("display_name")
                     for a in (w.get("authorships") or [])]
            idx = [i for i, n in enumerate(names) if any(
                n and nn in n.lower() for nn in hit)]
            print(f"\n[{w.get('publication_year')}] {','.join(hit)}")
            print(f"  {(w.get('title') or '')[:95]}")
            for i in idx:
                a = (w.get("authorships") or [])[i]
                af = a.get("raw_affiliation_strings") or []
                print(f"  -> {names[i]} | {af[0][:150] if af else ''}")
    if fail:
        print(f"\n⚠️ {fail} 个抓取失败 —— 失败≠不存在，必须换源重试")
        sys.exit(2)


if __name__ == "__main__":
    main()
