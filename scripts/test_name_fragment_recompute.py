#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归测试：`name:` 合成键必须参与 recompute() 的 work id 集合并集去重。

背景 / 为什么必须有这个测试
--------------------------
2026-09-29 在 `apply_merges.py` 踩到真实 bug：旧实现在调用 `recompute()`
前，把 `entities` 里所有 `name:` 前缀的合成键剔除，理由是「它的论文在
OpenAlex 里已经挂在主片名下了」。

该理由经查为**假**。反例是 Guanghui Hu 组的 `name:guanghuihu`：

    W4299444035（2022，J. Geophys. Eng.，18 被引，
      Combined multi-branch selective kernel hybrid-pooling skip
      connection residual network for seismic random noise attenuation）

该文是院署名，且**不在**主片 A5100750981 的 13 篇之内。剔除 `name:`
键 = 1 篇真实院署名论文 + 18 条真实院口径被引静默消失，合并后
`yjy_cited=51` 比任何一版权威口径都小。更阴险的是：产物「看起来是合理的
JSON」，没有任何报错。

本测试用最小 fixture 直接驱动真实 `recompute()`，锁定两个不变量：

  1. `name:` 键的唯一论文必须计入 yjy_papers / yjy_cited（旧 bug 会丢）；
  2. 同一 work 被两个分片同时覆盖时，并集只计一次（去重不靠排除 name:）。

运行：
    python test_name_fragment_recompute.py
    # 输出 SELFTEST PASS 且 exit=0 即通过
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from apply_merges import recompute  # noqa: E402

KEEP = "A5100000001"
NAME = "name:examplename"
OTHER = "A5100000002"


def build_fixture():
    """构造 works 缓存：一个 keep 分片 + 一个 name: 分片 + 一条覆盖重复。

    关键设计：
      * W1 只归 keep（2 引）
      * W2 只归 name:（18 引）—— 旧 bug 会把它整篇丢掉
      * W3 同时被 keep 和 name: 覆盖（7 引）—— 并集必须只计一次
    """
    works_by_id = {
        "W1": {"id": "W1", "order": 0, "cited": 2, "year": 2020,
               "venue": "VenueA", "yjy_entity": {KEEP}},
        "W2": {"id": "W2", "order": 1, "cited": 18, "year": 2022,
               "venue": "VenueB", "yjy_entity": {NAME}},
        "W3": {"id": "W3", "order": 2, "cited": 7, "year": 2021,
               "venue": "VenueC", "yjy_entity": {KEEP, NAME}},
    }
    by_entity = {
        KEEP: {"W1", "W3"},
        NAME: {"W2", "W3"},
    }
    return by_entity, works_by_id


def main():
    by_entity, works_by_id = build_fixture()

    # 不变式 1：name: 键参与重算。
    # 正确结果：yjy_papers=3（W1+W2+W3，去重后）、yjy_cited=27、total_cited=27。
    got = recompute([KEEP, NAME], by_entity, works_by_id, {}, None)
    assert got["yjy_papers"] == 3, f"yjy_papers 应为 3，实际 {got['yjy_papers']}"
    assert got["yjy_cited"] == 27, f"yjy_cited 应为 27，实际 {got['yjy_cited']}"
    assert got["total_cited"] == 27, f"total_cited 应为 27，实际 {got['total_cited']}"

    # 不变式 2（旧 bug 的复现路径）：若把 name: 键剔除，18 引会丢失。
    # 我们不该走到这一步——但把「剔除后的值」作为对照证据打印出来，
    # 证明该测试确实能拦住旧逻辑。
    buggy = recompute([KEEP], by_entity, works_by_id, {}, None)
    assert buggy["yjy_cited"] == 9, (
        f"对照：剔除 name: 后应为 9（W1 2 + W3 7），实际 {buggy['yjy_cited']}。"
        "这证明旧代码会丢 name: 片的 18 引。"
    )

    # 不变式 3：W3 单篇双覆盖时，并集只算一次；从 name: 单侧看也与并集等价。
    dedup = recompute([KEEP, NAME], by_entity, works_by_id, {}, None)
    assert dedup["yjy_papers"] == 3, "W3 被两片覆盖不应计两次"

    # 不变式 4：结果逐字节可复现（两次调用一致）。
    again = recompute([KEEP, NAME], by_entity, works_by_id, {}, None)
    assert json.dumps(got, sort_keys=False, ensure_ascii=False) == \
        json.dumps(again, sort_keys=False, ensure_ascii=False), "重算结果应逐字节稳定"

    print("SELFTEST PASS: name: 键参与 recompute 并集去重（yjy_papers=3, "
          "yjy_cited=27; 双覆盖只计一次; 结果可复现）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
