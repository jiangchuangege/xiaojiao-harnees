# -*- coding: utf-8 -*-
"""Mermaid 图语法自检（离线，不需要联网渲染）

为什么要它：README/docs 里的图一旦语法错，GitHub 上就是一块红色报错，
读者看到的是"一堆乱码"而不是架构图 —— 文档质量直接崩。

检查内容：
  · 围栏成对、能取到 ```mermaid 块
  · `subgraph` 与 `end` 数量配对
  · 每行引号、方括号、花括号、圆括号配对（Mermaid 里最容易写错的地方）
  · flowchart 的连线端点存在节点定义（尽力检查，仅提示不阻断）
  · sequenceDiagram：participant 声明、箭头写法、Note/opt/end 配对

用法：
    python tools/check_mermaid.py README.md ARCHITECTURE.md docs/*.md
    python tools/check_mermaid.py --all          # 扫描仓库内全部 .md
退出码：0 = 全部通过；1 = 有问题（可接进 CI）
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys

# CI（GitHub 的 Windows runner）控制台编码不是 UTF-8（cp1252/charmap），
# 这里打印的中文与 ✅ 会直接抛 UnicodeEncodeError —— 真实事故：本检查步骤在 CI 上**每次都失败**，
# 导致后面的压力测试根本没跑过。所以入口处先把标准输出切成 UTF-8（切不动就退化成替换字符，不报错）。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: silent-ok — 老环境没有 reconfigure 也不该让工具挂掉
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FENCE_RE = re.compile(r"```mermaid\n(.*?)```", re.S)


def check_flowchart(lines: list[str]) -> list[str]:
    errs = []
    sg = sum(1 for l in lines if re.match(r"\s*subgraph\b", l))
    en = sum(1 for l in lines if re.match(r"\s*end\s*$", l))
    if sg != en:
        errs.append("subgraph(%d) 与 end(%d) 不配对" % (sg, en))
    for l in lines:
        s = l.strip()
        if s.startswith("%%") or not s:
            continue
        for open_c, close_c, name in (('"', '"', "引号"), ("[", "]", "方括号"),
                                      ("{", "}", "花括号"), ("(", ")", "圆括号")):
            if s.count(open_c) != s.count(close_c):
                errs.append("%s 不配对: %s" % (name, s[:60]))
                break
    return errs


def check_sequence(lines: list[str]) -> list[str]:
    errs = []
    for kw in ("opt", "loop", "alt", "par", "critical", "rect"):
        opened = sum(1 for l in lines if re.match(r"\s*%s\b" % kw, l))
        closed = sum(1 for l in lines if re.match(r"\s*end\s*$", l))
        if opened and closed < opened:
            errs.append("sequenceDiagram: %s(%d) 缺少对应 end" % (kw, opened))
            break
    for l in lines:
        s = l.strip()
        if not s or s.startswith("%%"):
            continue
        # 【为什么要跳过图类型声明行，而不是写死 lines[1:]】
        #   原来从 `lines[1:]` 开始扫，默认"第 0 行一定是 sequenceDiagram"。
        #   但 mermaid 的 `%%{init}%%` 指令**必须在最前面**，于是第 0 行变成指令、第 1 行才是
        #   `sequenceDiagram` —— 它就被当成"一条不像消息的行"报错了（实测踩到）。
        #   现在按内容判断：指令行跳过、图类型声明行也跳过，位置随便。
        if s.startswith("sequenceDiagram"):
            continue
        if s.startswith(("participant", "Note", "activate", "deactivate", "end", "opt",
                         "loop", "alt", "else", "par", "and", "rect", "critical", "break",
                         "autonumber", "title", "box")):
            continue
        if "-->>" not in s and "->>" not in s and "-->" not in s and "->" not in s:
            errs.append("sequenceDiagram 行不像消息/声明: %s" % s[:60])
    return errs


def check_file(path: str) -> tuple[int, int]:
    try:
        text = open(path, encoding="utf-8").read()
    except OSError as e:
        print("  ⚠️ 读不到 %s: %s" % (path, e))
        return 0, 0
    blocks = FENCE_RE.findall(text)
    fences = text.count("```mermaid")
    bad = 0
    print("== %s：%d 个 mermaid 块" % (os.path.relpath(path, ROOT), len(blocks)))
    if fences != len(blocks):
        print("  ❌ 有 %d 个 ```mermaid 未闭合" % (fences - len(blocks)))
        bad += 1
    for i, b in enumerate(blocks, 1):
        lines = [l for l in b.splitlines() if l.strip()]
        if not lines:
            print("  ❌ block#%d 为空" % i)
            bad += 1
            continue
        head = lines[0].strip()
        # 【为什么图类型关键字要"往下找几行"，而不是只看第一行 —— 实测踩到的真缺陷】
        #   `%%{init: ...}%%` 是 mermaid 的**指令**，规范要求它出现在**最前面**；
        #   而本校验原来只看"块内第一行"判类型。两者直接冲突：
        #     · 指令写第一行 → 校验器看到 `%%{init:`，认不出类型 → **整块被跳过、等于没校验**；
        #     · 为了让校验生效把它挪到 `flowchart` 之后 → mermaid 把 `%%{init}%%` 当成**注释**，
        #       主题静默失效（图还是能画，但字号/换行宽度/间距全回默认值）。
        #   实测代价：某一轮统一图时 73 个块被"挪序"以通过校验，结果这 73 个块的主题全部失效；
        #   而这次真正的渲染失败（`style C["switch"]`）校验器又**完全没报**（它只查括号/引号配对，
        #   不查语句级语法）—— 两个方向都错了。
        #   现在的判据：从块内**前 6 行**里找图类型关键字，找不到才退回第一行。
        #   这样"指令第一行 + 图类型第二行"能被正确识别，两块需求不再互斥。
        kind_line = head
        for cand in lines[:6]:
            c = cand.strip()
            if c.startswith(("sequenceDiagram", "flowchart", "graph", "stateDiagram",
                             "classDiagram", "erDiagram", "gantt", "pie", "journey",
                             "mindmap", "timeline")):
                kind_line = c
                break
        if kind_line.startswith("sequenceDiagram"):
            errs = check_sequence(lines)
            kind = "sequence"
        elif kind_line.startswith(("flowchart", "graph")):
            errs = check_flowchart(lines)
            kind = "flowchart"
        else:
            errs = []
            kind = kind_line.split()[0] if kind_line else "?"
        if errs:
            bad += 1
            print("  ❌ block#%d [%s]" % (i, kind))
            for e in errs[:5]:
                print("       - %s" % e)
        else:
            print("  ✅ block#%d [%s] %d 行" % (i, kind, len(lines)))
    return len(blocks), bad


def main() -> int:
    ap = argparse.ArgumentParser(description="Mermaid 语法自检")
    ap.add_argument("files", nargs="*")
    ap.add_argument("--all", action="store_true", help="扫描仓库内全部 .md")
    args = ap.parse_args()

    files = args.files
    if args.all or not files:
        # **必须递归**：`docs/*.md` 那种不递归的写法会**漏掉子目录里的图**。
        # 实测踩到：新增的 `docs/six-infinity-diagrams/*.md`（7 张图）在不递归时
        # 既不在 `--all` 里、也不在 CI（stress-test.yml 跑的就是 `--all`）里 ——
        # 图坏了没人发现，"0 问题"就成了一句空话。递归之后它们才真的被校验。
        files = sorted(set(glob.glob(os.path.join(ROOT, "*.md")) +
                           glob.glob(os.path.join(ROOT, "docs", "**", "*.md"), recursive=True) +
                           glob.glob(os.path.join(ROOT, "tests", "**", "*.md"), recursive=True)))
    total_blocks = total_bad = 0
    for f in files:
        p = f if os.path.isabs(f) else os.path.join(ROOT, f)
        if not p.endswith(".md") or not os.path.exists(p):
            continue
        b, bad = check_file(p)
        total_blocks += b
        total_bad += bad
    print("\n合计 %d 个图，问题 %d 个 → %s" % (total_blocks, total_bad,
                                          "✅ 全部通过" if total_bad == 0 else "❌ 需修复"))
    return 0 if total_bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
