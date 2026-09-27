# 单人蒸馏六步工作流

> 目标：给一个学者（通常是中文名）建实证档案——被引真值、合作网络、AI 化轨迹、判据式结论。
> 全程纪律：**任何"查不到/无记录"结论前必须做反面探针**（见 tool-discipline.md）。

---

## Step 1 · 锚定身份

先解决"这人是谁、别张冠李戴"：

1. **中文名 → 英文名变体**：王尚旭 → Wang Shangxu / Shangxu Wang；连字符变体：Xiang-Yang / Xiangyang / Xiang Yang
2. **机构锚点**：单位全称 + 简称（CUPB / 中国石油大学(北京)）
3. **已知合作者圈**（如果是从课题组名单来的）：作为后续锚点消歧的种子
4. **同名预警**：常见姓（Liu Yang / Zhou Hui / Wu Di / Chen Xiaohong）必须标记 `common_name: true`，后续走锚点门

**一手资料先抓**：学校主页 / 学院页 / 百科——拿教育履历、头衔、项目、获奖。这些是身份锚，也是后面判断"档案说的是同一个人"的依据。

## Step 2 · 多源爬取

| 通道 | 用法 | 注意 |
|------|------|------|
| **CrossRef API** | `query.author={given} {family}` + `query.bibliographic=主题词`，rows=50-60 | **模糊匹配**，必须逐篇核作者列表；429 时等 3s 重试 |
| **OpenAlex API** | 配额内首选：`/institutions?search=` 定 id → `/works?filter=institutions.id:X,raw_author_name.search:变体` | 429/配额耗尽是常态，别把"没查到"当"没有" |
| **Semantic Scholar** | `/author/search?query=` | 覆盖不稳定，空返回≠无此人 |
| **百度学术** | WebFetch 学者主页（ScholarID 页） | **affiliation 字段会错标**，看合作者名单 |
| **学校主页/学院页** | WebFetch | 中文一手资料，可信度最高 |

**执行顺序**：先 CrossRef（最稳）→ OpenAlex（配额内）→ 百度学术网页 → 一手主页。全被拦时换 WebSearch 间接查。

## Step 3 · 假阳性过滤

CrossRef/OpenAlex 返回的每篇论文：

1. **硬条件一**：目标名（含变体、首字母缩写、连字符折叠）真正出现在作者列表
2. **硬条件二**（仅常见名）：锚点共现——已知合作者圈至少一人出现在该篇作者列表
3. **记录**：过滤掉多少条、为什么（同名/圈外）——这些数字要写进档案的反面探针节

**已知陷阱**（实例，2026-09-27）：
- `Chen Xiaohong` 检索捞进 Chen Yuqing/Schuster（KAUST）、Chen Fubin/宗兆云-印兴耀（CUP华东）、Chen Wenchao/高静怀（西安交大）
- `Di Wu` 捞进 Ru-Shan Wu（UCSC 泰斗 439 被引）
- `Yang Liu` 捞进中石油勘探院 Jinshui Liu 团队的 Yang Liu

## Step 4 · 轨迹分析

对验证命中论文做关键词扫描：

```
AI/ML 关键词：neural, learning, network, deep, machine, GAN, generative,
             diffusion, data-driven, Bayesian, sparse, clustering,
             ensemble smoother, self-supervised
```

输出：AI/ML 论文占比 + 时间轨迹（哪年开始、峰值在哪、最新到什么范式）。

**范式分级**（判断 AI 化深度）：
- L0 纯物理（波动方程/正演）
- L1 优化算法（群体智能/蚁群）
- L2 贝叶斯/稀疏统计学习
- L3 传统 ML（HMM/随机森林/SVM）
- L4 深度学习（CNN/DNN 监督）
- L5 物理引导 AI（PINN/自监督/数据驱动正演）
- L6 生成式 AI（GAN/VAE/扩散模型）

**判读经验**（CUPB 案例沉淀）：
- "物理核 × AI 外壳"转型通常**在学生代执行**——本人守物理侧。判断一个组的 AI 化深度，看学生一作论文
- 轨迹连续性比占比重要：2009 群体智能 → 2013 贝叶斯 → 2021 数据驱动正演 → 2023 自监督，是连续迁移；只在 2023 突然出现一篇 DL 是跟风

## Step 5 · 四问定位 + 判据式结论

用能源 AI 拆解四问（详见 ai-teardown-criteria.md）定位该学者：
1. 求解器/内核出身？（物理内核提供者 / 规则库持有者 / 算法说明书作者 / 编译器作者）
2. 规则库沉淀多少？（可量化的"多少区块的坑"式答案）
3. 核心专业环节在链路哪里？（正演/标度化/反演/解释/监测）
4. 断供风险？（物理规律公开不怕断供；规则库唯一性怕开源复刻）

**判据式结论模板**：
> {姓名} = {一句话身份定位}；核心资产是{X}，断供风险{高/中/低}，因为{Y}；值得盯的是{Z}。

## Step 6 · 落盘

```
工作区/.workbuddy-ai/memory/scholars/{拼音}.md     # 档案
工作区/scholar_crawl/data/{key}_crossref.json      # 原始数据
```

档案必含：反面探针记录（哪个索引查了/查到什么/哪个没查）+ 待核验清单。
完成后更新 `assets/archived-scholars.md` 索引 + 工作区日志。
