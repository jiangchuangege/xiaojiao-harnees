# -*- coding: utf-8 -*-
"""按用户给的**特征串**拆掉他在 xiaojiao_app.py 里加的 mirage/DEBUG 那几段。

【为什么按特征串、不按行号】行号会随编辑漂移；特征串是用户自己给的，对得上才动手。
【绝不整文件覆盖】只在内存里删指定区间，写完立刻 `ast.parse` 复核；失败就还原。
【先备份】原文件整份备份到 logs/backup_before_unmirage/。
"""
import ast
import io
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
P = "xiaojiao_app.py"

# (起始特征, 结束特征, 说明) —— 删掉从起始行**到结束行**（含）
BLOCKS = [
    ("# ---- 用户点名了工具 → 强制装进本轮", "点名工具装表失败（忽略）：%s",
     "① 点名工具强制装表"),
    ("# ---- 命令里有 Linux 风格路径（/data、/s3）→ 转给 mirage", "mirage 路径分发失败（忽略）：%s",
     "② run_command 转 mirage"),
]
LINES = [
    ('LOG.info("DEBUG run_command：args=%r  cmd=%r", args, cmd)', "③ DEBUG run_command 日志"),
]


def main():
    src = io.open(P, encoding="utf-8").read()
    lines = src.split("\n")
    orig_n = len(lines)

    bak = os.path.join("logs", "backup_before_unmirage")
    os.makedirs(bak, exist_ok=True)
    bp = os.path.join(bak, "xiaojiao_app.py.bak_%s" % time.strftime("%Y%m%d_%H%M%S"))
    io.open(bp, "w", encoding="utf-8", newline="\n").write(src)
    print("备份：%s（%d 行）" % (bp, orig_n))

    drop = set()
    for start_mark, end_mark, name in BLOCKS:
        s = e = None
        for i, l in enumerate(lines):
            if s is None and start_mark in l:
                s = i
            elif s is not None and end_mark in l:
                e = i
                break
        if s is None or e is None:
            print("  ⚠️ %s：特征没找齐（起=%s 止=%s）→ 跳过，不动" % (name, s, e))
            continue
        for i in range(s, e + 1):
            drop.add(i)
        print("  ✅ %s：删第 %d–%d 行（%d 行）" % (name, s + 1, e + 1, e - s + 1))

    for mark, name in LINES:
        hit = [i for i, l in enumerate(lines) if mark in l]
        if not hit:
            print("  ⚠️ %s：没找到 → 跳过" % name)
            continue
        for i in hit:
            drop.add(i)
        print("  ✅ %s：删第 %s 行" % (name, [h + 1 for h in hit]))

    out = [l for i, l in enumerate(lines) if i not in drop]
    new = "\n".join(out)
    try:
        ast.parse(new)
        print("\n语法复核：✅ 通过（删掉 %d 行，%d → %d 行）" % (len(drop), orig_n, len(out)))
    except SyntaxError as ex:
        print("\n❌ 语法复核失败（%s）→ **不写回**，原文件一个字没动" % ex)
        return 1
    io.open(P, "w", encoding="utf-8", newline="\n").write(new)

    # 剩下的痕迹（给人看，不自动删）
    print("\n【残留检查】")
    for pat in ("mirage", "_named_tools", "DEBUG run_command", "DEBUG tool_call", "_RESERVED"):
        hits = [i + 1 for i, l in enumerate(new.split("\n")) if pat in l]
        print("  %-18s %s" % (pat, ("第 " + "、".join(map(str, hits[:6])) + " 行") if hits else "无"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
