# OpenAlex 坑位清单

> 本库每一条都是实测踩出来的，附症状与正解。

## 1. 油田院通常没有独立机构实体

**症状**：`institutions?search=<油田院名>` 返回 0 条。大庆院、很多油田院都没有。

**正解**：抓**上级公司**实体（`Daqing Oilfield of CNPC` = `I4387155657`），
再逐篇 `authorships.raw_affiliation_strings` 正则识别本院。

## 2. `raw_affiliation_strings` 的位置

**症状**：放进 `select=` 直接 400。

**正解**：它在 **authorship 内部**（`works[].authorships[].raw_affiliation_strings`），
不是 works 顶层字段。但它**随 authorships 一起返回**，所以在 `select` 里写
`authorships` 就行，不要单独写 `raw_affiliation_strings`。

**回退**：部分 authorship 没有该字段，取 `authorships[].institutions[].display_name`。

## 3. U+00A0（NBSP）静默废掉归一化

**症状**：姓名归一化全部「无匹配」，脚本 exit 0，不报错。

**根因**：`raw_affiliation_strings` 含不间断空格
（`...PetroChina Daqing Oilfield Company,\xa0Daqi`），
`.replace(" ", "")` **去不掉**（NBSP 不是 U+0020）。

**正解**：用 `isspace()` 判断所有空白类字符：

```python
def norm(name):
    if not name:
        return ""
    s = name.lower()
    s = "".join(ch for ch in s if not ch.isspace())
    return s.replace("-", "").replace(".", "").replace(",", "")
```

`isspace()` 覆盖 U+0020 / U+00A0 / 全角空格 U+3000 / 制表符等。

**这条坑的可怕之处在于它静默**——没有任何异常，只是全部匹配失败。
如果后面不 assert 命中数，会以为「这些人都不在库里」。

## 4. 被引是全作者共享累计（下界）

OpenAlex 的 `cited_by_count` 是**论文级**的，按论文加到每个作者头上。
同一篇论文的所有作者共享同一被引数。

**后果**：作者的 `total_cited` 是**下界**，不可用于跨人精确比较。
一个挂名 100 篇大合作论文的人，被引可能虚高。

**正解**：名单里标明「被引为全作者共享累计下界」；要精确排名用别的口径
（explorer 14 层的 S2 全量被引 + h 指数）。

## 5. 中文作者碎片化（最重要）

同一人的多种署名形态被拆成多个 author.id：姓氏大小写、连字符、首字母写法。

大庆实测（全库口径）：`Cheng Wang` = **13 个** author.id，`Junhui Li` = 5 个。
⚠️ 口径要说清：13 是**全库** author.id 数，其中院署名 ≥1 篇的只有 11 个；
   「门槛外 N 个」= 全库数 − 门槛内数，两个口径混用会算错。

**正解**：见 `disambiguation-rules.md`（三判据合并 + 证据链 + 门槛外不硬并）。

## 6. 中文期刊覆盖不全

OpenAlex 收《大庆石油地质与开发》**英文版**（197 篇），**不收中文版**。

油田院主力发中文核心刊——**这些产出在本链路里结构性缺失**。
这不是「这些人没产出」，是「OpenAlex 看不见」。

**正解**：交付件必须写明这条边界。中文补采需 CNKI/万方，
但 2026-09-26 实测两者都被滑块验证封死（见 `waf-playbook.md`）。

## 7. `grep -c` 返回 0 时 exit 1

**症状**：`grep -c "xxx" file && do_next` —— 没匹配时 `&&` 后面的命令被吞，
诊断输出丢失，看起来像跑完了。

**正解**：用 `;` 分隔，或 `|| true`，或直接用 Python 脚本做检查。
