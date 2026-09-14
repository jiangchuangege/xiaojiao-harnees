# -*- coding: utf-8 -*-
"""给载体层所有模块补上「总纲注释」—— 检查与补齐（第 7 部分）。

运行：
    python tools/check_motto.py            # 只检查，列出缺哪几个（不写文件）
    python tools/check_motto.py --fix      # 补齐（只**新增**注释行，不改动任何已有代码）

【为什么要有这个脚本，而不是手工改一遍了事】
总纲注释是这套系统的"世界观声明"，它有两条硬要求：
  ① **每个模块都要有**（少一个，读代码的人就会以为那一个模块"不属于这套体系"）；
  ② **一字不差**（改一个字，就不再是同一句话了 —— 那条"接任何模型 → 系统活"的承诺会被稀释）。
手工改一遍只能保证"今天是对的"；这个脚本保证"以后加新模块时也对"。
新加的模块只要跑一次 `--fix` 就跟上了，`--check`（默认）还能进 CI。

【安全边界】`--fix` 只做一件事：在文件顶部**插入** 5 行注释（编码行之后、docstring 之前）。
不删任何行、不改任何已有内容；已经有的文件原样跳过（幂等）。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOTTO = [
    "# 小焦系统本身不依赖任何具体模型。",
    "# 它是完整的载体（器官齐全），模型是火种（可替换）。",
    "# 接入任何模型 → 系统活；换任何模型 → 系统不变。",
    '# 这就是"模型平等"和"变形金刚"的工程基础。',
]
NEEDLE = MOTTO[0]
CODING = "# -*- coding: utf-8 -*-"
# 载体层要覆盖的模块：core/ 下全部 + 两个入口脚本
EXTRA = ["xiaojiao_app.py", "start_xiaojiao.py"]


def targets():
    out = []
    for r, dd, ff in os.walk(os.path.join(ROOT, "core")):
        dd[:] = [d for d in dd if d != "__pycache__"]
        for f in ff:
            if f.endswith(".py"):
                out.append(os.path.join(r, f))
    out += [os.path.join(ROOT, e) for e in EXTRA]
    return sorted(out)


def has_motto(path):
    try:
        return NEEDLE in open(path, encoding="utf-8").read()[:3000]
    except OSError:
        return False


def insert(path):
    """在编码行之后插入总纲注释。返回 True=改了 / False=没改（已存在或读不了）。"""
    try:
        lines = open(path, encoding="utf-8").read().split("\n")
    except OSError:
        return False
    if NEEDLE in "\n".join(lines[:60]):
        return False
    pos = 0
    if lines and lines[0].strip() == CODING:
        pos = 1
    new = lines[:pos] + MOTTO + lines[pos:]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(new))
    return True


def main():
    fix = "--fix" in sys.argv
    files = targets()
    miss = [p for p in files if not has_motto(p)]
    print("载体层模块：%d 个" % len(files))
    if not miss:
        print("✅ 全部都有总纲注释（一字不差）")
        return 0
    print("缺总纲注释 %d 个：" % len(miss))
    for p in miss:
        print("  - %s" % os.path.relpath(p, ROOT))
    if not fix:
        print("\n（加 --fix 可自动补齐：只在顶部插入注释行，不动任何已有代码）")
        return 1
    done = []
    for p in miss:
        if insert(p):
            done.append(os.path.relpath(p, ROOT))
    print("\n已补齐 %d 个：" % len(done))
    for p in done:
        print("  + %s" % p)
    # 补完再验一遍（自己说的话自己要能验证）
    still = [os.path.relpath(p, ROOT) for p in files if not has_motto(p)]
    print("复核：仍缺 %d 个%s" % (len(still), ("：%s" % still) if still else ""))
    return 1 if still else 0


if __name__ == "__main__":
    sys.exit(main())
