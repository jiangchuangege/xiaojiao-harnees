# -*- coding: utf-8 -*-
"""查**不会渲染**的 Markdown 加粗（星号会原样显示出来）。

【为什么正文里的 `**加粗**` 会露星号 —— CommonMark 的"侧翼规则"跟中文标点打架】
  `**` 要成对生效，开的那一对必须是 left-flanking、收的那一对必须是 right-flanking。
  规则里"标点"是个关键条件，而**中文标点（。，：；！？、）也算标点**，于是出现两种失败：

  ① **收尾失败**：`**加粗。**中文`  —— 收尾 `**` 前面是「。」(标点)、后面紧跟汉字(既非空白也非标点)
     → 判定不成对 → **两个星号原样显示**
  ② **开头失败**：`中文**加粗**` 一般没事，但 `（**加粗**）` 这类在某些组合下也会翻车

  实测里最容易踩的是 `**……。**说明` 和 `**……：**文字` 这两种写法 ——
  中文文档里到处都是，所以"很多字都带星号"。

【怎么修】把这类 `**X**` 换成 `<b>X</b>`（GitHub 一律渲染），或者在该有空格的地方补空格。
  本工具只**报告**，不自动改 —— 因为改法有两种，得看着上下文选。

用法：python tools/check_md_emphasis.py
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

CJK = r"\u4e00-\u9fff\u3400-\u4dbf"
# 中文标点（全角）与常见英文标点
PUNCT = r"。，：；！？、（）「」『』《》〈〉【】…—·“”‘’,.;:!?()\[\]{}<>\"'"

BOLD = re.compile(r"\*\*([^*\n]+?)\*\*")


def is_ws(ch):
    return ch == "" or ch.isspace()


def is_punct(ch):
    return bool(ch) and (ch in "。，：；！？、（）「」『』《》〈〉【】…—·“”‘’,.;:!?()[]{}<>\"'")


def flanking_ok(text, start, end, inner):
    """判断这一对 `**`（[start,end) 包住 inner）按 CommonMark 能不能生效。

    ⚠️ **这里我第一版写反了，必须记下来**：我把"后接标点但前面是空白/标点"当成了**失败**，
    于是 `**【感知】**`、`**【症状】把来源说错**` 这类**本来能正常渲染**的写法
    被报成 166 处"不渲染" —— **全是误报**。
    CommonMark 的原定义是：
      left-flanking  = 后接非空白 且（后接非标点 或 后接标点且前面是空白/标点）
      right-flanking = 前接非空白 且（前接非标点 或 前接标点且后面是空白/标点）
    **"且前面是空白/标点"是让它成立的条件，不是让它失败的条件。**
    所以真正会露星号的只有**收尾那一侧不成立**的情况（如 `**加粗。**中文`）。
    """
    before_open = text[start - 1] if start > 0 else ""
    after_open = text[start + 2] if start + 2 < len(text) else ""
    before_close = text[end - 1] if end > 0 else ""
    after_close = text[end] if end < len(text) else ""

    ok_left = (not is_ws(after_open)) and (
        (not is_punct(after_open)) or is_ws(before_open) or is_punct(before_open))
    if not ok_left:
        return False, "开头不成对（后接空白）"

    ok_right = (not is_ws(before_close)) and (
        (not is_punct(before_close)) or is_ws(after_close) or is_punct(after_close))
    if not ok_right:
        return False, "收尾不成对（前接标点且后接文字/数字）"
    return True, ""


bad = []
for root, dirs, files in os.walk(ROOT):
    dirs[:] = [d for d in dirs if d not in SKIP]
    for fn in sorted(files):
        if not fn.endswith(".md"):
            continue
        p = os.path.join(root, fn)
        rel = os.path.relpath(p, ROOT).replace("\\", "/")
        lines = io.open(p, encoding="utf-8", errors="replace").read().splitlines()
        in_fence = False
        for i, ln in enumerate(lines, 1):
            s = ln.strip()
            if s.startswith("```"):
                in_fence = not in_fence
                continue
            if "**" not in ln:
                continue
            # ⚠️ **代码块里也要查**：代码块里的 `**` 一定原样显示（CommonMark 不处理），
            #    但用户看到的就是"字带星号"。第一版我 `if in_fence: continue` 直接跳过，
            #    于是"提示词示例"那一类**全漏了** —— 用户截图抓到的正是这一批。
            #    这里单列一类（`代码块内`），因为它和正文那类**修法不一样**：
            #    正文能换 <b>，代码块里换 <b> 也照样显示字面标签 —— 得改fence或去掉星号。
            if in_fence:
                # ⚠️ 但**不能把正当代码也报出来**：`config(**kw)`、`x**2` 是 Python 语法，
                #    星号本来就是代码的一部分。判据：星号之间**含中文**才算"想强调"。
                pos2 = [m.start() for m in re.finditer(r"\*\*", ln)]
                hit = any(
                    re.search(r"[\u4e00-\u9fff]", ln[pos2[k] + 2:pos2[k + 1]])
                    for k in range(0, len(pos2) - 1, 2))
                if hit and not s.startswith("%%"):
                    bad.append((rel, i, "代码块内（一定是字面星号，换 <b> 也没用，要去星号）",
                                ln.strip()[:56], ln.strip()[:150]))
                continue
            # ⚠️ 配对要**按出现顺序两两配**（第 1 个配第 2 个、第 3 个配第 4 个 …）。
            #    第一版用非贪婪正则 `\*\*(.+?)\*\*` 去配，结果把**前一句加粗的收尾**
            #    和**后一句加粗的开头**配成了一对，凭空造出一堆"开头后接空白"的假问题。
            #    CommonMark 对同种分隔符本来也是顺序配的，所以这里改成顺序配对。
            pos = [m.start() for m in re.finditer(r"\*\*", ln)]
            for k in range(0, len(pos) - 1, 2):
                start, end = pos[k], pos[k + 1] + 2
                inner = ln[start + 2:pos[k + 1]]
                if not inner or "\n" in inner:
                    continue
                ok, why = flanking_ok(ln, start, end, inner)
                if not ok:
                    bad.append((rel, i, why, ln[start:end][:56], ln.strip()[:150]))

print("=" * 78)
print("【不会渲染的 Markdown 加粗】（星号会原样显示 = 用户看到的「字带 *」）")
print("-" * 78)
by = {}
for rel, i, why, txt, line in bad:
    by.setdefault(rel, []).append((i, why, txt, line))
for rel, v in sorted(by.items(), key=lambda z: -len(z[1])):
    print("\n  ── %s" % rel)
    for i, why, txt, line in v:
        print("     行%-5d [%s]" % (i, why))
        print("        抓到的：%s" % txt)
        print("        整行  ：%s" % line)
print()
print("  共 %d 处，涉及 %d 份文档" % (len(bad), len(by)))
reasons = {}
for _, _, why, _, _ in bad:
    reasons[why] = reasons.get(why, 0) + 1
print("\n按原因分布：")
for why, n in sorted(reasons.items(), key=lambda z: -z[1]):
    print("  %-42s %d 处" % (why, n))
print("=" * 78)
sys.exit(0 if not bad else 1)
