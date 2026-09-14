# -*- coding: utf-8 -*-
"""通用收尾：反复「编译 → 修报错那一行 → 再编译」，直到文件语法通过。

判据（只对**编译报错的那一行**动手，其它行一个字不碰）：
  把这一行里**第一个引号和最后一个引号之间**那些未转义的英文双引号
  换成中文引号「」（左右交替）。理由是这类中文说明文字本来就该用中文引号，
  换完语义不变、字符串边界恢复到"首尾各一个引号"。
  若报错行以三引号开头（docstring）则跳过 —— 那种行不该用这套规则。
"""
import io
import os
import sys
import ast

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def fix_error_line(line):
    s = line
    if s.lstrip().startswith('"""') or s.lstrip().startswith("'''"):
        return line, False
    first = s.find('"')
    last = s.rfind('"')
    if first < 0 or last <= first:
        return line, False
    mid = s[first + 1:last]
    if '"' not in mid:
        return line, False
    out, left = [], True
    for ch in mid:
        if ch == '"':
            out.append("「" if left else "」")
            left = not left
        else:
            out.append(ch)
    return s[:first + 1] + "".join(out) + s[last:], True


def main():
    total = 0
    for rel in sys.argv[1:]:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            continue
        n = 0
        for _ in range(200):
            src = io.open(p, encoding="utf-8").read()
            try:
                ast.parse(src)
                break
            except SyntaxError as e:
                rows = src.split("\n")
                idx = (e.lineno or 1) - 1
                if idx < 0 or idx >= len(rows):
                    break
                nl, ok = fix_error_line(rows[idx])
                if not ok:
                    print("  ⚠️ %s 第 %d 行修不动，需要人工：%s"
                          % (rel, idx + 1, rows[idx].strip()[:120]))
                    break
                rows[idx] = nl
                io.open(p, "w", encoding="utf-8").write("\n".join(rows))
                n += 1
        src = io.open(p, encoding="utf-8").read()
        try:
            ast.parse(src)
            print("%-28s 修 %3d 行  ✅ 语法通过" % (rel, n))
        except SyntaxError as e:
            print("%-28s 修 %3d 行  ❌ 第 %s 行：%s" % (rel, n, e.lineno, e.msg))
            rows = src.split("\n")
            for k in range(max(0, (e.lineno or 1) - 2), min(len(rows), (e.lineno or 1) + 1)):
                print("      %4d %s" % (k + 1, rows[k][:150]))
        total += n
    print("\n合计修 %d 行" % total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
