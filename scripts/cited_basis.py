r"""被引口径的唯一裁决点（2026-09-29 立）

## 为什么要单独一个模块

2026-09-29 在中石化物探院这条链上踩到：`fetch_institute.py` 的门槛词表
是 `all | yjy`，`distill_core.py` 的是 `total | yjy`。同一个配置键
`threshold.cited_basis` 写`all` 时 fetch 认得、distill 直接
`sys.exit`；写 `total` 时 fetch 静默 fallback 成all（不报错）、distill
才认。**一个报错一个静默** —— 这是最坏的一种漂移：报错的那天你立刻知道，
静默的那天你拿到一个看起来正常、实际是另一个口径的数字。

更阴的一层：如果哪天 fetch 以 `--cited-basis yjy` 跑完，
`total_cited == yjy_cited`，此时 distill 的 `"total"` 选项会**静默返回
院口径的数字，却顶着"宽口径"的标签**。数据是对的，标签是错的，比数据错更难查。

## 判据

1. **采集层与口径无关。** roster 永远同时写两个数：
   - `total_cited` = 作者在本次抓到的**全部**论文的被引之和（恒定宽口径）
   - `yjy_cited`   = 作者**院署名命中**论文的被引之和（恒定院口径）
   两者都不许随配置变脸。`aggregate()` 因此不再接`cited_basis` 参数。
2. **口径只决定门槛和排序用哪个数**，由 `resolve_cited_field()` 唯一裁决。
3. **词表只有一套。** 对外只认 `all` / `yjy`；`total` 作为 `all` 的历史别名
   接受但归一化，归一化后写回 `cited_basis`，让配置自己变干净。
4. 拿不准就默认 `yjy`：名单是"院的人"，门槛必须与名单同口径。用宽口径卡
   门槛 = 拿该作者挂在别家单位时被引的业绩给自己院发名单。

## 变更纪律

新增口径 → 只改这里的 `CITED_BASES` 和 `ALIASES`，并在roster 里同时落一个
新字段。任何脚本都**不许**自己写 `("all", "yjy", "total")` 这种字面量列表。
"""
from __future__ import annotations

# 对外唯一合法词表 -> roster 字段名
CITED_BASES = {
    "all": "total_cited",   # 宽口径：作者全部缓存论文
    "yjy": "yjy_cited",     # 院口径：院署名命中论文
}

# 历史别名 -> 规范词。写total 是fetch 时代的叫法。
ALIASES = {
    "total": "all",
    "total_cited": "all",
    "yjy_cited": "yjy",
    "院署名": "yjy",
}

DEFAULT_BASIS = "yjy"


def normalize_basis(raw, default: str = DEFAULT_BASIS) -> str:
    """把任意写法的 cited_basis 归一化成 CITED_BASES 的key。

    认不出来时**报错退出**，绝不静默 fallback —— 本模块存在的全部意义
    就是消灭"静默用另一个口径"这件事。
    """
    if raw is None or raw == "":
        raw = default
    key = str(raw).strip().lower()
    key = ALIASES.get(key, key)
    if key not in CITED_BASES:
        raise SystemExit(
            f"❌ cited_basis={raw!r} 无法识别。合法值：{sorted(CITED_BASES)}"
            f"（历史别名：{sorted(ALIASES)}）。"
            f"不静默 fallback —— 静默换口径会让门槛数字失去含义。"
        )
    return key


def resolve_cited_field(threshold: dict | None, default: str = DEFAULT_BASIS):
    """从 config.threshold 取出被引口径，返回 (口径名, roster 字段名)。

    `threshold.cited_basis` 缺省时用 `default`（默认 yjy）。
    """
    th = threshold or {}
    basis = normalize_basis(th.get("cited_basis"), default=default)
    return basis, CITED_BASES[basis]


def drift_count(roster) -> int:
    """两口径不相等的行数——口径敏感度的量化指标，报告里要写。"""
    return sum(1 for x in roster
               if x.get("total_cited") != x.get("yjy_cited", 0))


def selfcheck():
    """自检：别名必须能全部归一化，且不撞默认口径。"""
    problems = []
    for alias, target in ALIASES.items():
        try:
            got = normalize_basis(alias)
        except SystemExit as e:
            problems.append(f"别名 {alias!r} 归一化失败：{e}")
            continue
        if got != target:
            problems.append(f"别名 {alias!r} → {got!r}，期望 {target!r}")
    for bad in ("", " ", "ALL_CITED", "院", None):
        if bad == "" or bad is None:
            continue
        try:
            normalize_basis(bad, default="yjy")
        except SystemExit:
            continue
        problems.append(f"非法值 {bad!r} 竟被接受")
    if normalize_basis(None) != DEFAULT_BASIS:
        problems.append(f"缺省应为 {DEFAULT_BASIS!r}")
    return problems


if __name__ == "__main__":
    bad = selfcheck()
    print(f"别名表 {len(ALIASES)} 条，词表 {sorted(CITED_BASES)}，"
          f"默认 {DEFAULT_BASIS}")
    if bad:
        for p in bad:
            print("✗", p)
        raise SystemExit(1)
    print("✓ cited_basis 自检通过")
