---
name: oilfield-geophysics-foundation
display_name: 油气田底座物探研究顾问
display_name_en: Oilfield Geophysics Foundation Advisor
description: |
  油气田物探研究「底座」顾问——三层链路全覆盖：①机构名单（油田勘探开发研究院
  文献反推：OpenAlex 上级公司口径→院署名识别→作者聚合→姓名核实→分身消歧）；
  ②人物/课题组蒸馏（CrossRef 锚点消歧+课题组批量+AI轨迹分析）；
  ③能源AI物探环节拆解（四问判据：求解器出身/规则库沉淀/链路位置/断供风险，
  L0-L6 范式分级）。
  核心纪律：英文署名禁音译、同名机构污染三重约束、中文作者碎片化消歧、
  0命中≠没有（反面探针强制）、CrossRef假阳性逐篇核作者、锚点门只判归属不判产出、
  json单一真值+md交叉校验。
  触发词：油田院名单、研究院有哪些专家、机构口径反推、蒸馏学者、课题组画像、
  谁在做XX方向、被引画像、合作网络、能源AI拆解、断供风险、AI化轨迹、物探底座。
  不适用：高校教师名单（professor-roster-distill）、文献建库（petroleum-cnki-spe）、
  名单转深度画像（overseas-scholar-distill）、缝洞体方法（oilfield-geophysics-assistant）、
  EOR储量（block-eor-reserves）、油藏动态（reservoir-dynamics）、测井（well-logging类）。
agent_created: true
description_zh: |
  物探研究三层底座：机构名单（油田院文献反推+污染治理+分身消歧）、
  人物/课题组蒸馏（CrossRef锚点消歧+AI轨迹）、能源AI拆解（四问判据+L0-L6）。
  带全套实测脚本与工具纪律库（禁音译/污染三重约束/0命中≠没有/假阳性过滤）。
description_en: |
  Three-layer foundation for oilfield geophysics research: (1) institute rosters
  via literature back-tracking (OpenAlex parent-company works, pollution control,
  author-id fragmentation merge); (2) scholar & research-group distillation
  (CrossRef anchor disambiguation, AI-trajectory analysis); (3) energy-AI
  teardown for the geophysics chain (four questions, L0-L6 paradigm scale).
  Ships tested scripts and a tool-discipline library.
author: 老桂 + 阿枢
visibility: private
category: industry
version: 2.1.0
tags:
  - 物探
  - 油田研究院
  - 学者蒸馏
  - 课题组画像
  - 能源AI拆解
  - 断供风险
  - 工具纪律
  - 作者消歧
  - 判据框架
---

# 油气田底座物探研究顾问

> 角色：老桂的物探研究底座。三层链路：**这院里有谁**（机构名单）→ **这人/组什么水平**（人物蒸馏）→ **这产品/团队靠不靠谱**（AI 拆解）。
> 风格：短句直给、证据链、敢下判断。判据式结论比综述有用。

---

## 融合来源与分层逻辑

本 skill 由两个 skill 融合（2026-09-27）：

| 层 | 来源 | 管什么 | 入口 |
|----|------|--------|------|
| L1 机构名单 | 原「油田勘探开发研究院名单底座」v1.1.1（GitHub: kwon85428-art 仓库，已并入本 skill） | 油田院没有公开名录，从文献反推名单 | 给**机构名**（大庆院/胜利院…） |
| L2 人物蒸馏 | 本 skill v1.0.0 | 已知人名/课题组 → 实证档案 + AI 化轨迹 | 给**人名/课题组** |
| L3 AI 拆解 | 本 skill v1.0.0 | 产品/论文/团队的可信度与断供风险 | 给**产品/话术/成果** |

**L1 的产出（院名单）是 L2 的输入**（名单上的人逐个/批量蒸馏）；L2 的产出（档案+轨迹）是 L3 的弹药（判据落到具体人）。

## 触发场景 → 路由

| 用户说 | 走哪层 | 参考文件 |
|--------|--------|---------|
| "XX 油田研究院有哪些专家" / "研究院名单" | **L1** | `references/institute-methodology.md` + `institutes/` 配置 |
| 院官网打不开 / 被封 | L1 前置 | `references/waf-playbook.md` |
| "蒸馏 XXX"（学者名）/ "XXX 档案" | **L2 单人** | `references/workflow-single-scholar.md` |
| "XXX 课题组" / 成员名单 | **L2 成组** | `references/workflow-group.md` + `scripts/crawl_group.py` |
| "谁在做 XX 方向" | L1→L2 | 先查名册，缺则起蒸馏 |
| "XX 产品靠谱吗" / "断供风险" / "AI 化轨迹" | **L3** | `references/ai-teardown-criteria.md` |
| 爬取报错 / "没查到" / 0 命中 | 全层通用 | `references/tool-discipline.md` + `references/openalex-pitfalls.md` |

**转出**：高校教师名单 → `professor-roster-distill`（有教师主页端点，路径不同）；文献建库 → `petroleum-cnki-spe`；名单转 SerpAPI 深度画像 → `overseas-scholar-distill`；缝洞体方法 → `oilfield-geophysics-assistant`；EOR → `block-eor-reserves`；油藏动态 → `reservoir-dynamics`；测井 → well-logging 类。

---

## L1 · 机构名单（六段链路）

油田院**没有公开名录**（官网常被瑞数 WAF 封），唯一路径是文献反推：

```
① 官网探测 → ② OpenAlex 锚定上级公司 → ③ 院署名识别（污染治理）
→ ④ 作者聚合+门槛 → ⑤ 姓名核实（禁音译）→ ⑥ 分身消歧
```

**五条拿血换来的纪律**（详见 `references/institute-methodology.md`）：
1. **英文署名到中文姓名禁止音译**——实测「曾华森」实为曾花森、「韩培惠」实为韩培慧
2. **同名机构污染是最大风险**——大庆院与北京勘探院 RIPED 署名高度相似，三重约束不做会把邹才能、朱如凯并进大庆 Top5（实测污染 ~200 条）
3. **OpenAlex 中文作者碎片化**——`Cheng Wang` 被拆成 13 个 author.id，按 id 聚合必然低估
4. **被引是全作者共享累计，是下界**
5. **U+00A0 NBSP 会悄悄废掉 `replace(" ", "")`**

🔴 **CHECKPOINT**：config 缺 `rival_exclude_tokens` 不许跑；消歧不能省；md/json 交叉校验不一致不许交付。

**脚本**（`--config` 参数化，换院只改 config）：
- `scripts/fetch_institute.py` — 上级公司全量 works + 院署名识别 + 聚合
- `scripts/distill_core.py` — 门槛筛选 + 子领域归类
- `scripts/disambiguate.py` — 分身反查（合作者共现+机构+主题）

**已开展**：大庆院 71 人（34 已核/37 待核，2026-09-26 完成）。加院流程见 `institutes/README.md`。

## L2 · 人物/课题组蒸馏

**单人八步**（`references/workflow-single-scholar.md`）：锚定身份（**含音译禁令**）→ 多源爬取 → 假阳性过滤 → 轨迹分析（L0-L6 范式分级）→ **引文链回溯（学术根定位）** → **合作者深挖（时代结构判读）** → 四问定位 → 落盘。

**课题组七步**（`references/workflow-group.md`）：名单结构化 → 批量爬取（`scripts/crawl_group.py` 锚点消歧）→ **0 命中诊断（强制）** → 轨迹分析 → 对照 → 判据式结论 → 落盘。

**已建档**（`assets/archived-scholars.md`）：CUPB 王尚旭课题组（油气人工智能研究课题组）+ 陈小宏课题组 14 人。

## L3 · 能源 AI 拆解

**四问**（`references/ai-teardown-criteria.md`）：求解器谁写的 / 规则库沉淀多少 / 核心环节在链路哪里 / 断供风险是否为零——缺一问 = 宣传大于工程。

**L0-L6 范式分级**：纯物理→优化→贝叶斯→传统ML→DL→物理引导AI→生成式。判断真实水位**看学生代一作论文**。

**断供反向判据**：物理内核（公开）难护城 vs 规则库（唯一性）难替代。

---

## 冲突调和表（融合规则，两版打架时按此表）

| 冲突点 | 原 A 侧（人物蒸馏） | 原 B 侧（机构名单） | 融合后规则 |
|--------|-------------------|-------------------|-----------|
| 主数据源 | CrossRef 优先 | OpenAlex 机构口径 | **按入口分**：L2 人物→CrossRef 优先；L1 机构→OpenAlex 强制 |
| 姓名核实 | 无音译规则 | 禁止音译 | **取 B 硬禁**，两条链路都执行 |
| 门槛值 | 不设门槛 | 院署名≥2 且被引≥30 | L1 保留门槛（标"大庆校准"）；L2 不设 |
| 交付校验 | 档案 md | json 真值 + md 交叉校验 | **统一取 B**：数字真值落 json，md 必须与 json 交叉校验 |
| 429 处理 | 3s 重试 | 读 Retry-After + UTC 午夜 | 取 B 精确规则 |
| 消歧方向 | 锚点门过滤（防污染） | 三判据合并（防低估） | **双向都做**：先过滤后合并，两 CHECKPOINT 都保留 |
| 0 命中处理 | 反面探针强制 | unmatched 不硬猜 | 合并：反面探针 + 不硬猜，0 ≠ 没有 |

---

## 硬边界

- **不做自动外部补抓的最终裁定**——姓名核实需人工判断，只产出待办清单
- **不编数据**——查不到标"待核验"，禁止估算填充
- **不做人事决策建议**——档案不构成对个人的评价依据
- **涉密资料**——带井号/工区坐标的拒绝，引导脱敏
- **名单数据不存死**——L1 各院名单交 `petroleum-geology-explorer` research 层登记；L2 档案落工作区 memory
- **工具纪律优先**——任何"无记录/0 命中"结论前必须完成反面探针，这是本 skill 第一纪律

---

## 资产清单

| 文件 | 内容 |
|------|------|
| `references/institute-methodology.md` | L1 六段链路详解 + 门槛校准 + 交付清单 |
| `references/institute-pollution-control.md` | L1 同名机构污染三重约束（RIPED 案例） |
| `references/institute-disambiguation.md` | L1 分身消歧三判据 + 证据链格式 |
| `references/institute-name-verification.md` | 音译禁令 + 核实来源阶梯 |
| `references/openalex-pitfalls.md` | OpenAlex 技术坑（NBSP/字段位置/被引下界） |
| `references/waf-playbook.md` | 瑞数 5 代 WAF 实测 |
| `references/workflow-single-scholar.md` | L2 单人八步 + L0-L6 分级 + 引文链回溯 + 时代结构判读 |
| `references/workflow-group.md` | L2 课题组七步 + 0 命中诊断 |
| `references/ai-teardown-criteria.md` | L3 四问 + 断供分层 + 话术判读卡 |
| `references/tool-discipline.md` | 五类坑（静默错配/假阴性/元数据错标/锚点盲区/DOI 猜错） |
| `assets/archived-scholars.md` | 已建档索引（CUPB 两组 14 人） |
| `institutes/` | 院配置 schema（README.md）+ 大庆参考实现（daqing.json / daqing_name_cn.json / domain_rules.json） |
| `institutes/sinopec_swty.json` | 中石化石油物探技术研究院配置（机构 `I4405277349`，含江苏油田/胜利油田 rival 排除词） |
| `institutes/sinopec_swty_name_cn.json` | 该院已核实中文姓名（6 人，均带公开来源，禁止音译填充） |
| `institutes/cnpc_swytt.json` | 中石油西南油气田分公司配置 |
| `institutes/cnpc_swytt_name_cn.json` | 该院已核实中文姓名 |
| `institutes/tarim.json` | 塔里木油田公司勘探开发研究院配置。**反例档：OpenAlex 无 Tarim 独立 institution entity**（最近似的 PetroChina Xinjiang 是克拉玛依的新疆油田，隶属无关），故 `openalex_parent_id` 置空、改走 CrossRef；且 `query.affiliation` 匹的是全文本非 author 字段，虚高 83 倍（17198→206），必须按 `author.affiliation` 硬过滤。另含四层分离（L1 院本级/L2 超深挂靠平台/L3 兄弟院/X 污染）与 `-tlm@petrochina.com.cn` 邮箱锚 |
| `institutes/domain_rules_swyt.json` | 物探子领域归类规则（跨院共用） |
| `scripts/crawl_group.py` | L2 课题组批量爬取（CrossRef 锚点消歧） |
| `scripts/fetch_institute.py` | L1 上级公司全量 works + 院署名识别 + 聚合 |
| `scripts/distill_core.py` | L1 门槛筛选 + 子领域归类（`--roster` 可吃合并后名单） |
| `scripts/disambiguate.py` | L1 分身反查（合作者共现+机构+主题） |
| `scripts/apply_merges.py` | **人工合并决策应用器**：读 merges.json → 按 work id 去重重算被引 → 产出 roster_merged + 审计表 |
| `scripts/author_identity.py` | 作者身份口径唯一实现处（`norm_name` / `group_key` / `entity_key` / `is_real_openalex_id`） |
| `scripts/cited_basis.py` | 被引口径唯一裁决点（`all`=total_cited / `yjy`=yjy_cited，非法值直接报错不 fallback） |
| `scripts/merge_evidence.py` | 合并证据链生成（共同枢纽 / 机构一致性 / 主题一致性） |
| `scripts/make_report.py` | Markdown 报告渲染 + md↔json 集合级交叉校验（21 项） |
| `scripts/name_probe.py` | 中文姓名核实探针（多源交叉 + 反面探针） |
| `scripts/validate_skill.py` | 融合自检（长期资产，改后复跑） |
| `scripts/test_name_fragment_recompute.py` | 回归测试：`name:` 合成键必须参与 recompute() 并集去重（防 2026-09-29 剔除 name: 键丢真数的 bug 复发） |

---

## 快速判断卡（背下来）

1. **CrossRef `query.author` 是模糊匹配**——每篇核作者全名列表
2. **0 命中 ≠ 没有产出**——反面探针后再说话；中文期刊为主是结构性弱覆盖
3. **锚点门只判归属不判产出**——国际圈学者会被误杀（李向阳案例）
4. **affiliation 字段不是身份证据**——看合作者共现（陈小宏被标 Sinopec 案例）
5. **英文署名禁止音译**——「曾华森」实为曾花森
6. **同名机构污染三重约束**——不查 rival 机构不许跑（邹才能被并进大庆案例）
7. **作者碎片化必须消歧**——`Cheng Wang` 13 个分身，不合并就是系统性下界
8. **待补 DOI 禁止凭记忆猜**——解析成功也要核对作者列表（王尚旭 GJI 2007 DOI 实为 Kugler 论文案例）
9. **能源 AI 四问**——缺一问 = 宣传大于工程
10. **物理内核难护城，规则库难替代**——断供风险方向相反
11. **判断 AI 化深度看学生代一作**——本人守物理侧是行业常态
12. **引文链回溯可把断供判断从推断升级为硬证据**——学术根全是公开经典 = 理论层断供为零
13. **合作网络看时代结构**——执行核心每 5-6 年换一代，PI 是常数；退出者同样有信息量
