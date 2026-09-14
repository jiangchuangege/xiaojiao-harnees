# -*- coding: utf-8 -*-
"""收尾：把剩下的「本该是引号却被换成了「」」的行还原（只处理两种确凿形态）。

`fix_quote_syntax.py` 用的是"整行就是一个字符串字面量"这个判据，它有两类误伤：
  ① **字典项** `"key": "value",` —— 也被当成了单个字符串，于是变成 `"key「: 」",`
     （判据：行里出现 `「:` 或 `: 」` 这种"引号贴着冒号"的组合，正常中文不会这么写）
  ② **多段引号的行** `"提到"系统提示词"并试图改写它",` —— 非贪婪匹配没吃下整行，
     反而**没被修**，于是语法照样不通（判据：这一行是列表元素、内部有偶数个 `"`）
这两类都还原/收敛成"用中文引号包裹内部引用"，改完再编译验证。
"""
import io
import os
import re
import sys
import ast

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def fix_dict_entry(line):
    """`"key「: 」",` → `"key": "",` 这类：引号贴着冒号，一定是字典项被误改。"""
    if "「:" in line or ": 」" in line or "「: 「" in line:
        return line.replace("「", '"').replace("」", '"'), True
    return line, False


def fix_list_element(line):
    """列表元素里还有未转义的英文引号 → 把内部那些换成中文引号（左右交替）。"""
    s = line.strip()
    m = re.fullmatch(r'(.*?")(.*)(".*)', s, re.S)
    if not m:
        return line, False
    # 只处理"看起来是列表/元组的字符串元素"的行：以引号开头、以引号+逗号或右括号结尾
    if not (s.startswith('"') or s.startswith('(r"') or s.startswith('r"')):
        return line, False
    head, mid, tail = m.group(1), m.group(2), m.group(3)
    if '"' not in mid:
        return line, False
    out, left = [], True
    for ch in mid:
        if ch == '"':
            out.append("「" if left else "」")
            left = not left
        else:
            out.append(ch)
    return line.replace(s, head + "".join(out) + tail), True


def main():
    total = 0
    for rel in sys.argv[1:]:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            continue
        lines = io.open(p, encoding="utf-8").read().split("\n")
        n = 0
        for i, ln in enumerate(lines):
            nl, ok = fix_dict_entry(ln)
            if ok:
                lines[i] = nl
                n += 1
        io.open(p, "w", encoding="utf-8").write("\n".join(lines))
        # 编译 → 报错行 → 就地修 → 再来一遍（最多 40 轮，防死循环）
        for _ in range(40):
            src = io.open(p, encoding="utf-8").read()
            try:
                ast.parse(src)
                break
            except SyntaxError as e:
                rows = src.split("\n")
                idx = (e.lineno or 1) - 1
                if idx < 0 or idx >= len(rows):
                    break
                nl, ok = fix_list_element(rows[idx])
                if not ok:
                    nl, ok = fix_dict_entry(rows[idx])
                if not ok:
                    print("  ⚠️ %s 第 %d 行需要人工看：%s" % (rel, idx + 1, rows[idx][:120]))
                    break
                rows[idx] = nl
                io.open(p, "w", encoding="utf-8").write("\n".join(rows))
                n += 1
        src = io.open(p, encoding="utf-8").read()
        try:
            ast.parse(src)
            print("%-28s 共修 %3d 行  ✅ 语法通过" % (rel, n))
        except SyntaxError as e:
            print("%-28s 共修 %3d 行  ❌ 第 %s 行：%s" % (rel, n, e.lineno, e.msg))
            rows = src.split("\n")
            for k in range(max(0, (e.lineno or 1) - 2), min(len(rows), (e.lineno or 1) + 1)):
                print("      %4d %s" % (k + 1, rows[k][:140]))
        total += n
    print("\n合计修改 %d 行" % total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
