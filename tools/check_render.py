# -*- coding: utf-8 -*-
"""渲染缺陷检查：**代码围栏没闭合** + **Mermaid 标签里写 Markdown 加粗**。

【为什么要有它 —— 用户截图直接看到的两个问题，现有检查器全都没抓到】
  · `tools/check_docs.py` 管链接/路径/端点/工具名 —— 不管渲染
  · `tools/check_mermaid.py` 管 Mermaid 的括号/引号配对 —— 不管标签里写了什么
  于是下面两类"人一眼就能看出来"的毛病一路漏过去：

  ① **``` 围栏没闭合**：一旦有一处少了收尾的 ```，**后面整篇都被 GitHub 当成代码块**，
     里面所有 `**加粗**`、`> 引用`、`| 表格` 全部原样显示 —— 用户看到的就是"格式全不对、
     到处是星号"。这是**灾难级**的显示问题，但一个字符都不会报错。
  ② **Mermaid 标签里的 `**加粗**`**：Mermaid 默认**不解析** Markdown 加粗，
     写在节点标签里会**原样显示成 `**文字**`**。所以图里也会"带星号"。

用法：python tools/check_render.py
退出码：0 = 没问题；1 = 有问题
"""
from __future__ import annotations

import io
import os
import re
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:      # noqa: silent-ok — 老环境没有 reconfigure 也不该让工具挂掉
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP = {".git", "logs", "node_modules", "__pycache__", ".pytest_cache",
        "books", "downloads", "media"}


def md_files():
    out = []
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP]
        for fn in files:
            if fn.endswith(".md"):
                out.append(os.path.join(root, fn))
    return sorted(out)


bad_fence, bad_bold = [], []

for p in md_files():
    rel = os.path.relpath(p, ROOT).replace("\\", "/")
    lines = io.open(p, encoding="utf-8", errors="replace").read().splitlines()

    # ---- ① 围栏闭合 ----
    open_at = None
    in_mermaid = False
    for i, ln in enumerate(lines, 1):
        s = ln.strip()
        if s.startswith("```"):
            if open_at is None:
                open_at = i
                in_mermaid = s[3:].strip().lower().startswith("mermaid")
            else:
                open_at = None
                in_mermaid = False
            continue
        # ---- ② Mermaid 标签里的加粗 ----
        if in_mermaid and "**" in ln:
            # 排除 Mermaid 注释行（%% 开头）
            if not s.startswith("%%"):
                bad_bold.append((rel, i, ln.strip()[:100]))
    if open_at is not None:
        bad_fence.append((rel, open_at, lines[open_at - 1].strip()[:60]))

print("=" * 74)
print("【① 代码围栏没闭合】（一旦有，后面整篇都被当成代码块 → 加粗/引用/表格全露原样）")
print("-" * 74)
for rel, ln, txt in bad_fence:
    print("  ❌ %-46s 第 %d 行开了没关：%s" % (rel, ln, txt))
print("  共 %d 处" % len(bad_fence))

print()
print("=" * 74)
print("【② Mermaid 标签里写了 Markdown 加粗】（Mermaid 不解析 → 原样显示 ** 星号）")
print("-" * 74)
byfile = {}
for rel, ln, txt in bad_bold:
    byfile.setdefault(rel, []).append((ln, txt))
for rel, v in sorted(byfile.items(), key=lambda z: -len(z[1])):
    print("  %-46s %d 处（首个在第 %d 行）" % (rel, len(v), v[0][0]))
print("  共 %d 处，涉及 %d 份文档" % (len(bad_bold), len(byfile)))

print()
print("=" * 74)
print("结论：围栏问题 %d ｜ Mermaid 加粗问题 %d" % (len(bad_fence), len(bad_bold)))
print("=" * 74)
sys.exit(0 if not (bad_fence or bad_bold) else 1)
