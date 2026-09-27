# 院配置 schema

> 每家院一个 `institutes/<院>.json`。三个脚本都吃它，**换院只改 config 不改代码**。

## 必填字段

```json
{
  "institution": {
    "name": "大庆油田勘探开发研究院",
    "short": "daqing_yjy",
    "openalex_parent_id": "I4387155657",
    "parent_name": "Daqing Oilfield of CNPC"
  },
  "identify": {
    "city_tokens": ["Daqing", "大庆"],
    "institute_patterns_en": [
      "exploration\\s*(?:and|&)\\s*development\\s*research\\s*institute",
      "research\\s*institute\\s*of\\s*exploration\\s*(?:and|&)\\s*development",
      "E\\s*&\\s*D\\s*Research\\s*Institute"
    ],
    "institute_patterns_cn": [
      "大庆(?:油田)?(?:勘探开发研究院|研究院)|勘探开发研究院"
    ],
    "rival_exclude_tokens": [
      "Beijing 100083", "Langfang", "Lanzhou", "Northwest", "Xinjiang"
    ]
  },
  "threshold": { "yjy_min": 2, "cited_min": 30 },
  "name_cn_file": "daqing_name_cn.json",
  "domain_rules_file": "domain_rules.json"
}
```

## 字段说明

| 字段 | 说明 | 缺失后果 |
|---|---|---|
| `openalex_parent_id` | 上级公司的 OpenAlex institution id | 抓不了数据 |
| `city_tokens` | 本城市中英文写法，用于三重约束 ②③ | 英文署名无法确认归属 |
| `institute_patterns_*` | 本院院名表述的正则（en/cn） | 院署名识别失效 |
| `rival_exclude_tokens` | **同名机构的地址特征词** | **重蹈污染覆辙**（见下） |
| `threshold` | 门槛值；报告里必须原样引用 | 读者无法判断名单松紧 |

## ⚠️ rival_exclude_tokens 是开跑前唯一必审项

**没有这一项的 config 不许开跑。**

换院前先查清楚：全国有哪些机构与本院**同名或近名**？它们的地址特征是什么？

参考答案（需自行核实，勿照抄）：

| 本院 | 同名/近名风险机构 | 地址特征 |
|---|---|---|
| 大庆院 | 北京勘探院 RIPED 及分院 | `Beijing 100083` / `Langfang` / `Lanzhou` / `Northwest` / `Xinjiang` |
| 长庆院 | 西安/银川相关机构 | 待查 |
| 塔里木院 | 库尔勒相关机构 | 待查 |

判断方法：把本院的英文院名拆成关键词，在 OpenAlex `institutions?search=` 里搜，
看返回的都是哪些机构、在哪些城市。**每个同城市的近名机构都要写进排除词**。

## 可复用件

跨院通用、不需要每院重写的：

- `domain_rules.json` —— 八子领域关键词（01 沉积 … 08 微生物 EOR）
- `daqing_name_cn.json` —— 大庆的姓名映射（**每院一个**，`<short>_name_cn.json`）

`domain_rules.json` 是跨院共用的；`name_cn` 文件每院独立，因为中文姓名必须逐院核实。

## 换院五步

1. 探官网（有没有名录？被没被 WAF 封？）
2. OpenAlex 找上级公司 institution id（`institutions?search=`）
3. 查同名机构 → 填 `rival_exclude_tokens`
4. 写 `institutes/<院>.json`
5. 跑三脚本：
   ```
   python scripts/fetch_institute.py --config institutes/<院>.json
   python scripts/distill_core.py    --config institutes/<院>.json
   python scripts/disambiguate.py    --config institutes/<院>.json
   ```
