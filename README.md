# 油气田底座物探研究顾问 · Oilfield Geophysics Foundation Advisor

> 三层链路：**这院里有谁**（机构名单）→ **这人/组什么水平**（人物蒸馏）→ **这产品/团队靠不靠谱**（AI 拆解）。

一个 [WorkBuddy](https://www.workbuddy.cn/) Skill。给油气物探研究做"底座"——不教方法，回答三个可判据的问题：谁在做、做到哪、怎么查证。

## 为什么需要它

油田勘探开发研究院**没有公开名录**（官网常被 WAF 封）；学者档案在英文索引里**碎片化且被污染**（同名机构、同名作者、元数据错标）；能源 AI 产品的宣传**大于工程**。这个 skill 把三条查证链路固化成可复跑的工作流 + 实测脚本 + 纪律库。

## 三层架构

| 层 | 管什么 | 核心方法 |
|----|--------|---------|
| **L1 机构名单** | 油田院文献反推名单 | OpenAlex 上级公司口径 → 院署名识别（污染治理）→ 作者聚合 → 姓名核实 → 分身消歧 |
| **L2 人物蒸馏** | 学者/课题组实证档案 | CrossRef 锚点消歧（目标名在作者列表 + 常见名锚点共现）→ AI 轨迹分析（L0-L6 范式分级） |
| **L3 AI 拆解** | 产品/团队可信度 | 四问判据（求解器出身/规则库沉淀/链路位置/断供风险）+ 话术判读卡 |

L1 的产出（院名单）是 L2 的输入；L2 的产出（档案+轨迹）是 L3 的弹药。

## 十条拿血换来的纪律

1. CrossRef `query.author` 是模糊匹配——每篇核作者全名列表
2. 0 命中 ≠ 没有产出——反面探针后再说话
3. 锚点门只判归属不判产出——国际圈学者会被误杀
4. affiliation 字段不是身份证据——看合作者共现
5. **英文署名禁止音译**——实测「曾华森」实为曾花森
6. 同名机构污染三重约束——不做会把北京院士并进大庆 Top5（实测 ~200 条污染）
7. 作者碎片化必须消歧——`Cheng Wang` 被拆成 13 个 author.id
8. 能源 AI 四问——缺一问 = 宣传大于工程
9. 物理内核难护城，规则库难替代——断供风险方向相反
10. 判断 AI 化深度看学生代一作——本人守物理侧是行业常态

## 脚本（全部实测过）

| 脚本 | 作用 |
|------|------|
| `scripts/fetch_institute.py` | L1：OpenAlex 上级公司全量 works + 院署名识别 + 聚合（`--config` 参数化，换院只改 config） |
| `scripts/distill_core.py` | L1：门槛筛选 + 子领域归类 |
| `scripts/disambiguate.py` | L1：分身反查（合作者共现 + 机构 + 主题） |
| `scripts/crawl_group.py` | L2：课题组批量 CrossRef 爬取（内置锚点消歧 + 0 命中诊断） |
| `scripts/validate_skill.py` | 融合自检（frontmatter / 引用 / 关键条款 / 换行 / 兄弟 skill 名 / 语法） |

## 实证案例（已建档）

- **大庆油田勘探开发研究院**：71 人核心名单（34 已核 / 37 待核），含分身消歧
- **CUPB 王尚旭课题组**（官方名"油气人工智能研究课题组"）+ **陈小宏课题组**：14 人档案，AI 化轨迹判读（袁三一 53 篇/41% AI/L5 数据驱动正演；李景叶线 2026 到扩散模型）

## 目录

```
├── SKILL.md                     # 主文件：三层架构 + 冲突调和表 + 快速判断卡
├── README.md
├── references/                  # 10 份工作流与纪律文档
│   ├── institute-methodology.md         # L1 六段链路
│   ├── institute-pollution-control.md   # 同名机构污染治理
│   ├── institute-disambiguation.md      # 分身消歧三判据
│   ├── institute-name-verification.md   # 音译禁令 + 核实阶梯
│   ├── openalex-pitfalls.md             # OpenAlex 技术坑
│   ├── waf-playbook.md                  # 瑞数 WAF 实测
│   ├── workflow-single-scholar.md       # L2 单人六步 + L0-L6
│   ├── workflow-group.md                # L2 课题组七步
│   ├── ai-teardown-criteria.md          # L3 四问 + 断供分层
│   └── tool-discipline.md               # 四类坑纪律库
├── institutes/                  # 院配置 schema + 大庆参考实现
├── scripts/                     # 5 个实测脚本
└── assets/archived-scholars.md  # 已建档索引
```

## 融合来源

v2.0.0 由两个 skill 融合：
- **人物侧**（v1.0.0，2026-09-27）：CrossRef 锚点消歧 + 课题组蒸馏 + AI 拆解判据
- **机构侧**（[oilfield-institute-hub](https://github.com/kwon85428-art/oilfield-institute-hub) v1.1.1）：油田院文献反推 + 污染治理 + 分身消歧

冲突调和表见 SKILL.md（数据源按入口分、音译禁令取硬禁、消歧双向都做等 7 条）。

## 使用

WorkBuddy 用户：把本目录放进 `~/.workbuddy-ai/skills/oilfield-geophysics-foundation/`。

触发词：油田院名单 / 蒸馏学者 / 课题组画像 / 谁在做XX方向 / 能源AI拆解 / 断供风险 / AI化轨迹。

## 免责声明

本仓库基于公开文献与公开网页整理，不构成任何勘探、人事或采购决策建议。学者档案数据含"待核验"标注，使用前请自行核实。
