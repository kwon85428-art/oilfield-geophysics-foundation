# -*- coding: utf-8 -*-
"""oilfield-geophysics-foundation 融合自检（长期资产，改 skill 后可复跑）
按 skill-fusion v1.3.0 陷阱清单设计：
- 陷阱7：文件清单比对要含自身；文本卫生扫描要跳过自身
- 陷阱9：兄弟 skill 名只扫 .md 文档层（agent 照着说的转交话术），不扫 .py
- 陷阱10：对 .git/ 免疫，统一 walk_files() 入口
- root 自 Path(__file__)，与调用位置无关
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SELF = "scripts/validate_skill.py"

SKIP_DIRS = {".git", ".github", "__pycache__", ".venv", "venv", "node_modules", ".idea", ".vscode"}
# 运行产物目录：不参与「SKILL.md 是否列全」的资产清点。
#
# 为什么要按**前缀**跳而不是整个 institutes/ 跳掉：
# institutes/ 里既有长期资产（*.json 配置），也有 out_<short>/ 这类
# 一次性运行输出（含 works_raw.json 好几个 MB、临时探针脚本）。
# 混在一起会导致 30+ 条「SKILL.md 未列出的文件」警告，
# 而警告一多就没人看了——**清单失去信号价值**。
# 判据：能重跑生成的（out_* 下的东西）不是资产，不该进清单。
OUTPUT_DIR_PREFIXES = ("out_",)
BIN_EXT = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".csv", ".tsv"}


def _is_output_dir(rel_parts):
    return any(p.startswith(OUTPUT_DIR_PREFIXES) for p in rel_parts)

# 本机确认存在的兄弟 skill（转交话术合法目标，2026-09-27 核验）
VALID_SIBLINGS = {
    "professor-roster-distill", "overseas-scholar-distill", "petroleum-cnki-spe",
    "petroleum-geology-explorer", "reservoir-dynamics", "block-eor-reserves",
    "oilfield-geophysics-assistant", "oilfield-well-logging-advisor",
    "well-logging-expert-v1",
}
# 已融合/归档的前身 skill：README 融合来源章节提及其 GitHub 链接是合法的（历史溯源，非转交话术）
MERGED_ANCESTORS = {"oilfield-institute-hub"}

# 关键条款落地清单（SKILL.md 必须 assert 出现）
KEY_CLAUSES = [
    "institute-methodology.md", "institute-pollution-control.md",
    "institute-disambiguation.md", "institute-name-verification.md",
    "openalex-pitfalls.md", "waf-playbook.md",
    "workflow-single-scholar.md", "workflow-group.md",
    "ai-teardown-criteria.md", "tool-discipline.md",
    "archived-scholars.md", "crawl_group.py",
    "fetch_institute.py", "distill_core.py", "disambiguate.py",
    "禁止音译", "同名机构污染", "反面探针", "锚点门", "四问", "L0-L6",
    "冲突调和表", "rival_exclude_tokens",
]

errors, warnings = [], []

def walk_files():
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT)
        if SKIP_DIRS & set(rel.parts[:-1]):
            continue
        if _is_output_dir(rel.parts[:-1]):
            continue
        yield p

# ---- 1. frontmatter 合规 ----
skill_md = (ROOT / "SKILL.md").read_text(encoding="utf-8")
m = re.search(r"^name:\s*(\S+)", skill_md, re.M)
if not m or m.group(1) != ROOT.name:
    errors.append(f"frontmatter name={m.group(1) if m else 'MISSING'} != dir {ROOT.name}")
for field in ["display_name", "agent_created: true", "version:", "author:"]:
    if field not in skill_md:
        errors.append(f"frontmatter 缺 {field}")

# ---- 2. SKILL.md 引用的 references 都存在 ----
for ref in re.findall(r"(?:references|scripts|institutes|assets)/[\w\-./]+", skill_md):
    if not (ROOT / ref).exists():
        errors.append(f"SKILL.md 引用不存在: {ref}")

# ---- 3. 关键条款落地 ----
for clause in KEY_CLAUSES:
    if clause not in skill_md:
        errors.append(f"关键条款未落地: {clause}")

# ---- 4. 文本卫生（跳过自身；.md 才扫兄弟 skill 名与绝对路径）----
for p in walk_files():
    rel = p.relative_to(ROOT).as_posix()
    if rel == SELF:
        continue
    if p.suffix in BIN_EXT:
        continue
    try:
        txt = p.read_text(encoding="utf-8")
    except (UnicodeDecodeError, ValueError):
        warnings.append(f"非 UTF-8: {rel}")
        continue
    if "\r\n" in txt:
        errors.append(f"CRLF 换行: {rel}")
    if p.suffix == ".md":
        for m2 in re.finditer(r"([A-Za-z][\w\-]*-(?:skill|distill|explorer|advisor|assistant|reserves|dynamics|hub|foundation|roster|cnki-spe))", txt):
            name = m2.group(1)
            if name not in VALID_SIBLINGS and name not in MERGED_ANCESTORS and name != ROOT.name:
                errors.append(f"未安装的兄弟 skill 名: {name} ({rel})")
        if re.search(r"[C]:\\\\Users|/Users/[a-z]", txt):
            errors.append(f"绝对路径: {rel}")

# ---- 5. 文件清单（含自身）----
actual = {p.relative_to(ROOT).as_posix() for p in walk_files()}
listed = set(re.findall(r"(?:references|scripts|institutes|assets)/[\w\-./.]+", skill_md))
# institutes/ 目录在资产清单里以目录行列出，其下 json 属于该目录内容，不算孤儿
listed |= {"institutes/daqing.json", "institutes/daqing_name_cn.json", "institutes/domain_rules.json"}
orphan = actual - listed - {"SKILL.md", "README.md", "test-prompts.json", ".gitignore"}
if orphan:
    warnings.append(f"SKILL.md 未列出的文件: {sorted(orphan)}")

# ---- 6. 脚本语法检查 ----
import ast
for p in walk_files():
    if p.suffix == ".py":
        try:
            ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError as e:
            errors.append(f"语法错误 {p.relative_to(ROOT)}: {e}")

print("=" * 60)
print(f"文件总数: {len(actual)} ｜ references: {len(list((ROOT/'references').glob('*.md')))} ｜ scripts: {len(list((ROOT/'scripts').glob('*.py')))}")
print("=" * 60)
if errors:
    print(f"FAIL {len(errors)}:")
    for e in errors:
        print(f"  [✗] {e}")
if warnings:
    print(f"WARN {len(warnings)}:")
    for w in warnings:
        print(f"  [!] {w}")
if not errors:
    print("ALL PASS")
sys.exit(1 if errors else 0)
