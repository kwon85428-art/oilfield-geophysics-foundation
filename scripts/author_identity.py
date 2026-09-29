#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""作者身份口径唯一实现处 —— 机构名单反推链路的第0 层。

为什么要有这个文件
------------------
2026-09-29 之前，`norm_name()` 在 fetch_institute.py / disambiguate.py /
distill_core.py 里各写了一份，三份都不一样：
  - fetch_institute  根本不调norm_name（直接拿 author.id 当 key）
  - disambiguate     调自己的 norm_name（只去空白/连字符/标点，**不管姓名字顺**）
  - distill_core     又抄了一份一样的

后果有两个，都是静默的：
  1. `Cai Jiexiong` / `Jiexiong Cai` / `Cai Jie-xiong` 被当成三个人 →
     同一个专家在 roster 里裂成 3 行，每行论文数都不够门槛，人就凭空消失。
  2. 姓名映射文件 `*_name_cn.json` 的 key 用哪种归一化，全看写映射那天
     顺手用了哪一种 → 查不到就静默留空，看起来像"查不到中文名"。

另外还有一个更危险的字段污染：author.id 缺失时（旧脚本）把 display_name
直接写进 `openalex_id` 字段。交付件里 97 行 roster 的 `openalex_id` 其实
是姓名字符串——**字段名在骗人**。任何下游按 `openalex_id` 拉 OpenAlex 都会
静默失败或拉错人。

本模块给出三个函数，全链路只用这三个：

  norm_name(s)      词内归一化（小写、去空白/连字符/标点）
  group_key(s)      跨分身聚合键 = norm_name 的**字符多重集**（字序无关）
  author_entity(a)  从 OpenAlex authorship.author 抽身份三元组

判据：group_key 只用于**分组与查表**（"这几个分身是不是同一个人"这个问题
要交给人看 coauthor/机构/主题），绝不用于自动合并。实体主键永远是
author.id；没有 id 时用带前缀的 synthetic key，**绝不允许冒充 OpenAlex ID**。
"""
import re
import unicodedata

__all__ = ["norm_name", "group_key", "author_entity", "is_real_openalex_id",
           "synthetic_key"]

# 归一化时直接删掉的字符：连字符、句点、逗号、撇号、括号类
_PUNCT = re.compile(r"[-.,'’`()\[\]·・]")

# OpenAlex author id 形态：A + 数字
_REAL_ID = re.compile(r"^A\d+$")


def norm_name(s):
    """词内归一化：小写、去所有空白、去连字符与标点。

    ⚠️ 必须用 isspace() 判断空白，.replace(" ", "") 去不掉 U+00A0（NBSP）
       和全角空格。见 references/openalex-pitfalls.md 第 3 条。

    ⚠️ 这一步**不处理姓名字顺**。`Cai Jiexiong` 与 `Jiexiong Cai` 经此函数
       仍是两个不同的串——字序问题交给 group_key。
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    s = "".join(ch for ch in s.lower() if not ch.isspace())
    return _PUNCT.sub("", s)


def group_key(s):
    """跨分身聚合键：norm_name 之后按字符排序（字序无关）。

    存在的理由（2026-09-29 实测）
    ------------------------------
    OpenAlex 同一个中国作者在原文里会出现多种署名顺序：
        `Jiexiong Cai`（given-family） / `Cai Jiexiong`（family-given）
        / `Cai Jie-xiong`（family-hyphenated-given）
    三者在 norm_name 下是三个键，于是这个专家在 roster 里裂成三行，
    每行 yjy_papers 都够不上门槛 → 专家凭空消失，且**不报任何错**。

    字符多重集能把三种写法折叠成一个键 `caijiexiong`。

    ⚠️ 副作用必须知道：它同时会把 `Wang Yang` 和 `Yang Wang` 折叠成一组，
       而这两个完全可能是两个不同的人。所以 group_key 的输出只能用于
       「把候选摆到一起让人看证据」，**不能**作为自动合并的依据。
       合并必须人眼按三判据过，见 references/institute-disambiguation.md。
    """
    n = norm_name(s)
    if not n:
        return ""
    return "".join(sorted(n))


def is_real_openalex_id(x):
    """x 是否是真正的 OpenAlex author id（`A` + 数字）。"""
    return bool(x) and bool(_REAL_ID.match(str(x)))


def synthetic_key(display_name):
    """无 author.id 时的稳定替身键。带 `name:` 前缀，肉眼不可能误认成 OpenAlex ID。"""
    n = norm_name(display_name)
    return f"name:{n}" if n else "name:unknown"


def author_entity(author):
    r"""从 OpenAlex 的 `authorship.author` 抽身份，字段语义严格分开。

    返回 dict:
        openalex_id           真实 author id（`A\d+`），没有则为 None
        display_name          OpenAlex 上的原始显示名（可为空）
        id_missing            True 表示 OpenAlex 没给这个作者分配 id
        synthetic_key         稳定替身键，形如 `name:caijiexiong`
        entity_key            聚合主键 = openalex_id or synthetic_key
        orcid                 有则给

    ⚠️ 不要再把 display_name 塞进 `openalex_id` 字段。那是 2026-09-29
       之前的老做法，后果是 97/713 行 roster 的 openalex_id 其实是姓名，
       字段名在骗人。判据：任何交付件里出现 `openalex_id` 不匹配 `^A\d+$`
       的行，就是这个 bug 复发了。
    """
    author = author or {}
    raw = author.get("id") or ""
    aid = raw.split("/")[-1].strip() if raw else ""
    name = (author.get("display_name") or "").strip()
    real = is_real_openalex_id(aid)
    return {
        "openalex_id": aid if real else None,
        "display_name": name,
        "id_missing": not real,
        "synthetic_key": synthetic_key(name) if not real else None,
        "entity_key": aid if real else synthetic_key(name),
        "orcid": (author.get("orcid") or "").strip(),
    }


if __name__ == "__main__":  # 自检：python author_identity.py
    cases = [
        "Cai Jiexiong", "Jiexiong Cai", "Cai Jie-xiong", "CAI JIEXIONG",
        "Weihua Liu", "Wei-Hua Liu", "Liu, Weihua", "liu　weihua",
    ]
    print("-- group_key 折叠（应全部同组）--")
    for c in cases:
        print(f"  {c:20s} -> {group_key(c)}")
    print("\n-- group_key 已知副作用（两人折叠，需人眼判）--")
    for c in ["Wang Yang", "Yang Wang", "Yan Wang", "Wang Yan"]:
        print(f"  {c:20s} -> {group_key(c)}")
    print("\n-- author_entity --")
    for a in [
        {"id": "https://openalex.org/A5025661565", "display_name": "Dingjin Liu"},
        {"id": None, "display_name": "Jiexiong Cai"},
        {"id": "", "display_name": "Wei Xie"},
        {"id": "https://openalex.org/", "display_name": ""},
    ]:
        e = author_entity(a)
        print(f"  in={a} -> openalex_id={e['openalex_id']} "
              f"missing={e['id_missing']} entity={e['entity_key']}")
