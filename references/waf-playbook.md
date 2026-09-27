# 瑞数 5 代 WAF 实测笔记

> 油田网站常被瑞数（Riverbed/瑞数信息）WAF 封锁。2026-09-26 实测大庆官网，
> 记录什么有效什么无效。

## 特征识别

- Cookie 里出现 `GahMaMhTvKpTS/T` 之类的长串 → 瑞数 5 代特征
- 请求返回 **412** + 39 字节空页
- 页面是 JS 挑战页，不是正常内容

## 无效的尝试（别浪费时间）

| 方法 | 结果 |
|---|---|
| curl 带任意 UA | 412 空页 |
| headless chromium（默认） | 412 |
| chromium + stealth 补丁 | 412 |
| 导出浏览器 cookie 给 curl | 仍 412（cookie 绑会话指纹） |
| Playwright `wait_until="networkidle"` | **永久挂死**（挑战 JS 一直跑，networkidle 永不触发） |

## 有效的方法

**Playwright + `channel="chrome"`（系统真实 Chrome，不是 chromium）+ 有头模式。**

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=False)
    page = browser.new_page()
    page.goto(url, wait_until="domcontentloaded")
    time.sleep(3)   # 手动等挑战 JS 跑完
    html = page.content()
```

要点：
- `channel="chrome"` 走系统装的 Google Chrome，指纹比 chromium 真实
- **有头模式**（`headless=False`）；headless=new 在 Chrome 153 上握手 404
- `wait_until="domcontentloaded"` + `time.sleep`，**不要用 networkidle**
- cookie **不能跨会话复用**：浏览器关掉后导出 cookie 再请求仍被拒——
  必须在**同一浏览器会话内**完成全部爬取

## CNKI / 万方现状（2026-09-26）

- `kns.cnki.net`：**所有入口**（首页 / `kns8s/search` / 详情页）一律 302 到
  `verify/home?captchaType=blockPuzzle` 滑块验证
- `s.wanfangdata.com.cn`：curl 返回 200 + 大空壳（无结果数据），
  真浏览器才弹滑块；纯客户端渲染，`__INITIAL_STATE__` 里没有结果

**结论：中文文献侧当前不可用。** 这直接决定了名单的中文核心刊覆盖缺口
（见 `openalex-pitfalls.md` 第 6 条）。

## 相关 skill 的旧记录已失效

`professor-roster-distill` 的 `fetch_cnki_institution.py` 记着「CNKI 首页 200 且不验证」
——**已过时**，现在首页都弹滑块。别照抄。

## 判据

- 油田/文献网站返回 412 + 几十字节空页 → 先怀疑瑞数
- 确认后直接上有头 Chrome 方案，别在 curl/stealth 上耗
