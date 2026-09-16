# -*- coding: utf-8 -*-
"""文档体检（对外可见的质量闸门）—— 检查 check_docs.py 管不到的四类腐烂。

`tools/check_docs.py` 只管**链接/路径/端点/工具名**是否存在。
但对外最容易丢脸的是另外四类，它一类都不管：

  ① **数字过期**：文档里写"42 图""286 次提交""六项能力"—— 实际早变了。
     实测踩到：Release 正文写着 42 图（实为 150）、press-kit 写 286 次提交（实为 350+）、
     全仓 57 处"六个无限"（已变七个）。**数字是最容易烂、也最显眼的地方。**
  ② **孤儿文档**：`docs/` 下有一份文档，但**没有任何地方链接它** ——
     对外的人根本找不到，等于没写。
  ③ **模块没文档**：`core/` 下的模块在任何文档里都没被提到。
  ④ **旧说法残留**：已经改名/改口径的说法还留着（如"健康系统"应叫"医生"）。

用法：python tools/check_docs_quality.py
"""
from __future__ import annotations

import io
import os
import re
import subprocess
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:      # noqa: silent-ok — 老环境没有 reconfigure 也不该让工具挂掉
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP = {".git", "logs", "node_modules", "__pycache__", ".pytest_cache",
        "books", "downloads", "media"}


def read(p):
    return io.open(p, encoding="utf-8", errors="replace").read()


def all_md():
    out = []
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP]
        for fn in files:
            if fn.endswith(".md"):
                out.append(os.path.join(root, fn))
    return out


def rel(p):
    return os.path.relpath(p, ROOT).replace("\\", "/")


MDS = all_md()
TEXTS = {rel(p): read(p) for p in MDS}
ALL = "\n".join(TEXTS.values())

# ---------------------------------------------------------------- ① 数字
def real_figures():
    n = 0
    for s in TEXTS.values():
        n += len(re.findall(r"```mermaid", s))
    return n


def real_commits():
    try:
        r = subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=ROOT,
                           capture_output=True, text=True)
        return int((r.stdout or "0").strip() or 0)
    except Exception:      # noqa: silent-ok — 没有 git 就跳过这一项
        return 0


def real_tools():
    """数插件里注册的工具（`T("name"` 与 `"name":` 的并集够用）。"""
    names = set()
    pdir = os.path.join(ROOT, "plugins")
    if os.path.isdir(pdir):
        for fn in os.listdir(pdir):
            if fn.endswith(".py"):
                s = read(os.path.join(pdir, fn))
                names |= set(re.findall(r'\bT\(\s*"([a-z_0-9]+)"', s))
    app = os.path.join(ROOT, "xiaojiao_app.py")
    if os.path.exists(app):
        names |= set(re.findall(r'if name == "([a-z_0-9]+)"', read(app)))
    return len(names)


def real_docs():
    return len([k for k in TEXTS if k.startswith("docs/")])


FACTS = {
    "图数": real_figures(),
    "提交数": real_commits(),
    "工具数": real_tools(),
    "文档数": real_docs(),
}
# 每个事实对应的"文档里会怎么写的"关键词；命中后取邻近数字比对
NEAR = {
    "图数": [r"(\d+)\s*[张个]图", r"(\d+)\s*个 mermaid", r"图[册数]\D{0,6}(\d+)"],
    "提交数": [r"(\d+)\s*次提交", r"提交\D{0,6}(\d+)"],
    "工具数": [r"(\d+)\s*个工具", r"工具\D{0,6}(\d+)\s*个"],
}

print("=" * 74)
print("【① 数字实况】—— **只报实况，不自动判错**")
print("-" * 74)
print("  %s" % " ｜ ".join("%s=%s" % (k, v) for k, v in FACTS.items()))
print("""
  ⚠️ 为什么这一节**不自动判错**（第一版我让它判，结果全是误报，必须记下来）：
    · 「架构图册（20 张）」里的 20 指的是**那一份文件**的图数，不是全仓 153 张 ——
      拿全仓数字去比，把对的判成错的。
    · 「工具 77 个」是**实测口径**（`tools/test_tool_infinity_live.py` 逐条数过），
      而我按 `T("name")` / `"name":` / `if name ==` 三种注册方式数出来是 35 或 74 ——
      **我算不准**，那就没有资格去判定文档写错了。
    · 「286 次提交」这类是**当时**的数字，只有 ChangeLog 该保留；但普通文档里
      写死提交数本身就会过期，这属于"该不该写"的判断，不是数字对错。
  结论：**数字这类只能人看**。工具给出实况，判断留给人和版本记录。
""")

# ---------------------------------------------------------------- ② 孤儿文档
print()
print("=" * 74)
print("【② 孤儿文档】docs/ 下没有任何地方链接它的")
print("-" * 74)
linked = set()
for f, s in TEXTS.items():
    for m in re.finditer(r"\]\(([^)\s]+\.md)[^)\s]*\)", s):
        t = m.group(1)
        base = os.path.basename(t)
        linked.add(base)
        linked.add(os.path.normpath(os.path.join(os.path.dirname(f), t)).replace("\\", "/"))
orphan = []
for f in sorted(TEXTS):
    if not f.startswith("docs/"):
        continue
    base = os.path.basename(f)
    if base in linked or f in linked:
        continue
    orphan.append(f)
for f in orphan:
    print("  %s" % f)
print("  共 %d 份孤儿文档（共 %d 份 docs/ 文档）" % (len(orphan), real_docs()))

# ---------------------------------------------------------------- ③ 模块没文档
print()
print("=" * 74)
print("【③ 模块没文档】core/ 下的模块在任何文档里都没被提到")
print("-" * 74)
mods = []
for root, dirs, files in os.walk(os.path.join(ROOT, "core")):
    dirs[:] = [d for d in dirs if d not in SKIP]
    for fn in files:
        if fn.endswith(".py") and not fn.startswith("__"):
            mods.append(os.path.splitext(fn)[0])
doc_all = "\n".join(s for f, s in TEXTS.items() if f.startswith(("docs/", "README", "ARCHITECTURE")))
undoc = sorted(set(m for m in mods if m not in doc_all))
for m in undoc:
    print("  core/%s.py" % m)
print("  共 %d 个模块没有任何文档提到（core/ 下共 %d 个）" % (len(undoc), len(set(mods))))

# ---------------------------------------------------------------- ④ 旧说法
print()
print("=" * 74)
print("【④ 已改名/已改口径的旧说法残留】")
print("-" * 74)
STALE_PHRASES = [
    ("六个无限", "已改为「七个无限」"),
    ("六张原理图", "已改为「七张原理图」"),
    ("3.3 健康系统", "已改名为「3.3 医生」"),
]
hit4 = 0
for phrase, why in STALE_PHRASES:
    for f, s in sorted(TEXTS.items()):
        if f.startswith("CHANGELOG"):
            continue
        for m in re.finditer(re.escape(phrase), s):
            line = s[:m.start()].count("\n") + 1
            text = s.splitlines()[line - 1] if line - 1 < len(s.splitlines()) else ""
            # ⚠️ 排除"在讲这次改名"的句子 —— 第一版没排除，把
            #    「六个无限 → 七个无限」「『3.3 健康系统』改名为…」这种**正确**的描述
            #    也报成了残留（自测当场抓到）。
            if any(k in text for k in ("→", "改名", "改为", "已改", "原来是", "旧称")):
                continue
            print("  %-46s 行%-5d 「%s」 —— %s" % (f, line, phrase, why))
            hit4 += 1
print("  共 %d 处（已排除在讲这次改名的句子）" % hit4)
