# 方法论详解 · 六段链路

> 本文展开 SKILL.md 的六段链路，每段附大庆实测数字作为基线。

## ① 官网探测：先判断有没有名录

**别假设油田院官网有专家栏目。** 实测大庆（2026-09-26）：

| 位置 | 结果 |
|---|---|
| `dqyt.cnpc.com.cn/dq/yjy/` 子站 | 只有 `common.shtml` 一个真实页面（企业简介） |
| 栏目页 `index.shtml` | 0 字节空文件 |
| 专家/人才/教师栏目 | **不存在** |

结论：**该院无公开专家名录**，被迫走文献反推。这步必须先做——如果人家有名录，
直接用，省掉后面全部环节。

被瑞数 WAF 封的解法见 `waf-playbook.md`。

## ② 机构锚定：从上级公司找

OpenAlex 通常**没有油田院的独立机构实体**（`institutions?search=<院名>` 返回 0）。
解法：抓**上级公司**实体，再逐篇筛署名。

大庆实测：
- `Daqing Oilfield of CNPC` = `I4387155657`，2109 works
- 抓取用 cursor 分页，`per-page=200`，`select=id,doi,title,publication_year,cited_by_count,authorships,primary_location`
- ⚠️ **`raw_affiliation_strings` 在 authorship 内部**，不能放进 `select=`（会 400），
  也不能在 works 顶层取——它随 authorships 一起返回

找公司实体 id 的稳妥流程：
```
institutions?search=<油田公司名>   → 看返回列表的 display_name / works_count / country_code
                                   → 确认是本公司（不是同名其他机构）→ 取 id
```

## ③ 院署名识别：正则 + 污染治理

逐篇遍历 `works[].authorships[]`，对每个 authorship 的 `raw_affiliation_strings`
（列表）做正则识别。识别规则必须区分「本院」与「同名外院」——详见
`pollution-control.md`。大庆实测：2109 篇 → 876 篇含大庆院署名。

**字段回退**：部分 authorship 没有 `raw_affiliation_strings`，回退取
`authorships[].institutions[].display_name`（粒度粗，但聊胜于无）。

## ④ 作者聚合 + 门槛

按 `author.id`（或 display_name 兜底）聚合：院署名论文数、累计被引、活跃年、
署名变体、机构证据样本、代表作样本。

**门槛是经验值，必须写明**：

| 门槛 | 大庆结果 |
|---|---|
| 院署名 ≥1 | 1245 人（大量合作过路者） |
| **院署名 ≥2 且被引 ≥30** | **71 人核心**（本链路的校准值） |
| 院署名 ≥5 | 40 人 |

报告里必须给出三档数字，读者才能判断名单松紧。门槛值不是行业惯例，是单院校准。

## ⑤ 姓名核实：禁止音译

见 `name-verification.md`。核心：英文署名 → 中文姓名**必须逐人公开来源核实**。
大庆实测：71 人核心中 34 人已核实、37 人待核实（进附录，不硬填）。

## ⑥ 分身消歧

见 `disambiguation-rules.md`。OpenAlex 中文作者碎片化是系统性的，不做消歧数字必然偏低。
大庆实测合并 3 组：核心 74 → 71 人；李军辉 5 个 author.id 合并 3 个真分身，院署名 16→21 篇（含 1 篇门槛外但证据确凿的）。

## 交付清单

每家院的交付应包含（大庆为参考实现）：

1. **数据件 json**（单一真值来源）——每条至少：
   `name_en` / `name_cn`（空 = 待核实）/ `openalex_id` / `orcid` /
   `domain` / `yjy_papers`（院署名论文数）/ `dual_aff`（双单位论文数）/
   `total_cited` / `year_min` / `year_max` / `top_venues` /
   `aff_evidence`（机构证据样本）/ `key_works`（代表作）
   合并过的追加 `merged_ids` + `disambig_note`（证据链）
2. **方法论 md**：污染治理、门槛校准、音译纠错、分身消歧证据、章节有序
3. **可读交付件 md**：分组表 + 关键人物侧写 + 数据边界，可直接给用户
4. **数字交叉校验**（交付前必做）：
   - md 核心表行数 == json `name_cn` 非空条数
   - md 附录行数 == json `name_cn` 为空条数
   - 逐人英文名归一化（去标点、小写、去连字符）后**集合相等**
   - 子领域标注合计 == 核心表行数（大庆曾在此翻车，见下）

## ⚠️ 已踩过的交付坑

**「凑得上总数」不等于「数字正确」。** 大庆名单曾写「已核实 35 人 + 待核实 36 人 = 71」，
算术自洽，实际核心表只有 34 行——两个数字都是抄写偏差，没人逐行对过。
**判据：数字必须来自比它更上游的真值**（json），并做集合级交叉校验，
不是「两个数字加起来等于总数」。

## 数据边界（必须写进交付件）

1. **被引是全作者共享累计，是下界**，不可用于跨人精确比较
2. **中文核心刊覆盖严重不全**：油田院主力发中文刊，OpenAlex 只收其英文版
   （大庆《大庆石油地质与开发》英文版 197 篇，中文版不收）——
   **这是结构性偏差，不是这些人没产出**
3. **CNKI / 万方滑块墙**：2026-09-26 实测全入口封死，中文侧补采当前不可行
4. **官网无名录**：被迫走反推路径的前提
5. **门槛是经验值**：见上表

## 与其他 skill 的接口

- 产出名单 → 交给 `petroleum-geology-explorer` 的 research 层（每院一层）
- 若要某院学者的深度画像 → 名单喂 `overseas-scholar-distill`
- 若要建中文文献底座 → `petroleum-cnki-spe`（当前受滑块墙限制）
