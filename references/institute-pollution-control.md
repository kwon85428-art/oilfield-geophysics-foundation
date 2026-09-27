# 同名机构污染治理

> 这是全链路最大的坑。大庆实例：初版规则把北京勘探院 RIPED 的论文并入大庆名单，
> 导致**邹才能、朱如凯等北京勘探院院士进了大庆 Top5**。

## 为什么会发生

油田勘探开发研究院的英文署名高度相似：

```
大庆院：  Exploration and Development Research Institute of Daqing Oilfield Company
北京院：  Research Institute of Petroleum Exploration & Development, Beijing 100083
```

两者都含 `Exploration` / `Development` / `Research Institute`。一个只匹配
「exploration and development research institute」的正则，会把两家全收。

## 三重约束（必须全做）

**约束 ①：排除同名机构的特征词**

硬排除命中下列任一特征词的署名：

```
Beijing 100083 | Langfang | Lanzhou | Northwest | Xinjiang | 杭州
```

这是北京勘探院 RIPED 及其分院的地址特征。命中即判非本院。

**约束 ②：英文命中必须共现本城市名**

英文正则匹配到「勘探开发研究院」类表述时，**同一 authorship 的署名串里必须还出现
本城市名**（大庆：`Daqing` / `大庆`），否则不算。

**约束 ③：中文院名必须与本地名共现**

中文「勘探开发研究院」单独出现不算（全国几十家油田都有同名机构），
必须与本地名（`大庆`）共现。

## 大庆实测效果

| 阶段 | 污染条数 |
|---|---|
| 初版（无三重约束） | ~200 条误并入 |
| 加三重约束后 | 15 条残余 |

残余 15 条是**双单位合作论文**（作者同时挂大庆院与北京 RIPED），
用 `dual_aff` 字段标记保留，不删除——它们是大庆院学者的真实合作产出。

## 正则模板（通用）

```python
# 院名识别（英文 + 中文，按院改）
RE_YJY_EN = re.compile(
    r"exploration\s*(?:and|&)\s*development\s*research\s*institute|"
    r"research\s*institute\s*of\s*exploration\s*(?:and|&)\s*development|"
    r"E\s*&\s*D\s*Research\s*Institute", re.I)
RE_YJY_CN = re.compile(r"<城市>(?:油田)?(?:勘探开发研究院|研究院)|勘探开发研究院", re.I)
RE_CITY   = re.compile(r"<城市英文>|<城市中文>")
# 同名机构排除词（按院改：列出同名机构的地址特征）
RE_RIVAL  = re.compile(r"<同名机构地址特征>", re.I)

def is_institute(affs):
    joined = " | ".join(affs or [])
    if not joined:
        return False
    if RE_RIVAL.search(joined):
        return False
    cn = bool(RE_YJY_CN.search(joined))
    en = bool(RE_YJY_EN.search(joined))
    if not (cn or en):
        return False
    if en and not RE_CITY.search(joined):
        return False
    if cn and not RE_CITY.search(joined) and not RE_YJY_EN.search(joined):
        return False
    return True
```

## 换院改造清单

每换一家院，`institutes/<院>.json` 里必须配齐：

- `city_tokens`：本城市的中英文写法（`["Daqing", "大庆"]`）
- `institute_patterns_cn` / `institute_patterns_en`：本院的院名表述变体
- `rival_exclude_tokens`：**同名机构**的地址特征词。这一项最关键——
  换院前先查清楚：全国有哪些机构和本院同名或近名？它们的地址特征是什么？
  （例：长庆院 vs 西安/银川的某院；塔里木院 vs 库尔勒的某院）

**没有 rival_exclude_tokens 的 config 不许开跑**——会重蹈大庆覆辙。
