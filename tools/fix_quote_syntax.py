# -*- coding: utf-8 -*-
"""修掉「中文字符串里嵌了未转义的英文双引号」造成的语法错误。

背景：子代理写 `core/world/firewall.py`（2118 行、内容完整）时，把
    "提到"系统提示词"并试图改写它"
这种中文引号写成了英文双引号，直接让整个文件语法不通 —— 一个字符就让 2000 行全部不可用。

做法（**只改有问题的那些行，别的一个字不动**）：
  对每一行，若它整体是一个字符串元素（strip 后以 " 开头、以 " 或 ", 结尾），
  且内部还有多余的未转义双引号 → 把内部那些成对的引号换成中文引号「」（左右交替），
  保证字符串边界不变、语义不变。
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGETS = sys.argv[1:] or ["core/world/firewall.py"]


def fix_line(line):
    """返回 (新行, 是否改过)。只在"整行就是一个字符串字面量"时才动手。"""
    s = line.strip()
    m = re.fullmatch(r'(".*?")(,?)\s*', s, re.S)
    if not m:
        return line, False
    body = m.group(1)
    inner = body[1:-1]
    if '"' not in inner:
        return line, False
    # 内部多余的引号：左右交替换成中文引号（中文语境里本来该用这个）
    out, left = [], True
    for ch in inner:
        if ch == '"':
            out.append("「" if left else "」")
            left = not left
        else:
            out.append(ch)
    new = '"%s"%s' % ("".join(out), m.group(2))
    return line.replace(s, new), True


def main():
    total = 0
    for rel in TARGETS:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            print("跳过（不存在）：%s" % rel)
            continue
        lines = io.open(p, encoding="utf-8").read().split("\n")
        changed = 0
        for i, ln in enumerate(lines):
            nl, ok = fix_line(ln)
            if ok:
                lines[i] = nl
                changed += 1
        if changed:
            io.open(p, "w", encoding="utf-8").write("\n".join(lines))
        print("%s：修了 %d 行" % (rel, changed))
        total += changed
        # 修完立刻验证能不能编译（自己说的话自己要能验证）
        import ast
        try:
            ast.parse(io.open(p, encoding="utf-8").read())
            print("   ✅ 语法通过")
        except SyntaxError as e:
            print("   ❌ 还有语法错：第 %s 行 %s" % (e.lineno, e.msg))
            src = io.open(p, encoding="utf-8").read().split("\n")
            if e.lineno:
                for k in range(max(0, e.lineno - 2), min(len(src), e.lineno + 1)):
                    print("      %4d %s" % (k + 1, src[k]))
    print("\n合计修改 %d 行" % total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
