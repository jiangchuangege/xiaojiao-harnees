# -*- coding: utf-8 -*-
"""修复 `fix_quote_syntax.py` 的**过度修正**（它把单行 docstring 也改了）。

发生了什么：
    `fix_quote_syntax.py` 用来修「中文字符串里嵌了英文双引号」的语法错，判据是
    "这一行整体就是一个字符串字面量"。可这个判据把**单行 docstring** 也算进去了——
    反引号里那行原本是三引号包起来的 docstring（例：三引号 + URL + 三引号），
    被它整体当成"一个字符串字面量"处理了。
    于是本来好端端的文件被改坏了。

怎么精确回退（不靠备份，靠**变换本身的指纹**）：
    我的替换是"内部每个 `"` 依次变成 `「`/`」`"，所以：
      · 三引号会被换成 `"「「` / `」」"` —— 出现**连续两个**「或」就是 docstring 的指纹；
      · 只有三个引号（空 docstring 行）会变成 `"「"` —— 单独一条规则处理。
    真正的目标行（原本坏掉的注入规则串）内部只有**成对的单引号**，不会出现连续两个。
    所以判据是干净的：见到连续两个「/」或 `"「"` → 这一行还原成单引号。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGETS = sys.argv[1:]


def repair_line(line):
    s = line.strip()
    if s == '"「"':                       # 空的单行 docstring：""" → "「"
        return line.replace(s, '"""'), True
    if ("「「" in line) or ("」」" in line):
        # 这一行原本是三引号 docstring → 把这一行里所有「」还原成 "
        return line.replace("「", '"').replace("」", '"'), True
    return line, False


def main():
    import ast
    total = 0
    for rel in TARGETS:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            print("跳过：%s" % rel)
            continue
        lines = io.open(p, encoding="utf-8").read().split("\n")
        n = 0
        for i, ln in enumerate(lines):
            nl, ok = repair_line(ln)
            if ok:
                lines[i] = nl
                n += 1
        if n:
            io.open(p, "w", encoding="utf-8").write("\n".join(lines))
        total += n
        src = io.open(p, encoding="utf-8").read()
        try:
            ast.parse(src)
            print("%-28s 还原 %3d 行  ✅ 语法通过" % (rel, n))
        except SyntaxError as e:
            print("%-28s 还原 %3d 行  ❌ 第 %s 行：%s" % (rel, n, e.lineno, e.msg))
            rows = src.split("\n")
            if e.lineno:
                for k in range(max(0, e.lineno - 2), min(len(rows), e.lineno + 1)):
                    print("      %4d %s" % (k + 1, rows[k][:150]))
    print("\n合计还原 %d 行" % total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
