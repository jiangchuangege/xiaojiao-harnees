# -*- coding: utf-8 -*-
"""一次性收尾：① 把仓库根的 `_princ.json` 移到 `tools/` ② 删掉 2 条自测误写的记忆。

【为什么写成脚本而不是手敲命令】
两件事都是**不可逆**的：移动要删来源、删记忆要改用户的数据文件。
脚本里把"改之前先留证据、改之后立刻复核"写死，比手敲一遍可靠：
  · 移动：先复制、校验字节一致、再删来源；
  · 删记忆：**先备份整个文件**，再按"内容精确匹配"删，绝不按行号删
    （子代理报的"第 138/139 行"是 **0 起算**的，直接按 1 起算的行号删会误删一条
     真实的对话记忆 —— 实测核对时发现的，所以这里改成按内容匹配）。
"""
import io
import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRINC = os.path.join(ROOT, "_princ.json")
PRINC_DST_DIR = os.path.join(ROOT, "tools")
PRINC_DST = os.path.join(PRINC_DST_DIR, "_princ.json")
VEC = os.path.join(ROOT, "logs", "xiaojiao_memory_vec.jsonl")
NEEDLE = "自主学习落盘验证话题"          # 这两条是自主性子代理早期自测误写的


def do_move():
    print("① 移动 _princ.json → tools/")
    if not os.path.exists(PRINC):
        print("   源文件不存在（可能已经移过了）：%s" % PRINC)
        return os.path.exists(PRINC_DST)
    src_bytes = io.open(PRINC, "rb").read()
    shutil.copyfile(PRINC, PRINC_DST)                       # 先复制
    dst_bytes = io.open(PRINC_DST, "rb").read()
    if src_bytes != dst_bytes:
        print("   ❌ 复制后字节不一致，**不删来源**（宁可留着也不冒险）")
        return False
    print("   已复制到 tools/_princ.json（%d 字节，与来源逐字节一致）" % len(dst_bytes))
    os.remove(PRINC)                                        # 校验通过才删来源
    print("   已删除仓库根的 _princ.json（内容已在 tools/ 下）")
    return True


def do_trim():
    print("\n② 删掉 2 条自测误写的记忆")
    if not os.path.exists(VEC):
        print("   记忆文件不存在，跳过")
        return 0
    raw = io.open(VEC, "r", encoding="utf-8").read()
    lines = raw.split("\n")
    # 备份（**先备份再改**：这是用户的数据文件，不可逆的改动必须留退路）
    bak = os.path.join(ROOT, "logs", "_backup_memory_vec_before_trim_%s.jsonl"
                       % time.strftime("%Y%m%d_%H%M%S"))
    io.open(bak, "w", encoding="utf-8").write(raw)
    print("   已备份：%s" % os.path.relpath(bak, ROOT))
    kept, removed = [], []
    for i, ln in enumerate(lines):
        if not ln.strip():
            kept.append(ln)
            continue
        try:
            d = json.loads(ln)
        except Exception:          # noqa: BLE001 — 解析不了的行原样保留（不动看不懂的东西）
            kept.append(ln)
            continue
        if NEEDLE in str(d.get("text") or ""):
            removed.append((i + 1, str(d.get("text"))[:60]))
            continue
        kept.append(ln)
    if not removed:
        print("   没找到那两条（可能已经被清理过）")
        return 0
    print("   将删除 %d 条：" % len(removed))
    for n, t in removed:
        print("     原第 %d 行：%s" % (n, t))
    io.open(VEC, "w", encoding="utf-8").write("\n".join(kept))
    return len(removed)


def verify():
    print("\n③ 复核")
    ok = True
    if os.path.exists(PRINC):
        print("   ❌ 仓库根仍有 _princ.json")
        ok = False
    else:
        print("   ✅ 仓库根已无 _princ.json")
    if os.path.exists(PRINC_DST):
        print("   ✅ tools/_princ.json 存在（%d 字节）" % os.path.getsize(PRINC_DST))
    else:
        print("   ❌ tools/_princ.json 不存在")
        ok = False
    left = 0
    total = 0
    dialogue_kept = False
    for ln in io.open(VEC, encoding="utf-8"):
        if not ln.strip():
            continue
        total += 1
        if NEEDLE in ln:
            left += 1
        try:
            if "写 10000 字产品介绍" in str(json.loads(ln).get("text") or ""):
                dialogue_kept = True
        except Exception:          # noqa: BLE001 — 坏行不影响统计
            pass
    print("   ✅ 记忆库剩 %d 条，其中含关键词的还有 %d 条" % (total, left))
    print("   %s 那条真实对话记忆（写 10000 字产品介绍）没有被误删"
          % ("✅" if dialogue_kept else "❌"))
    return ok and left == 0 and dialogue_kept


def main():
    print("=" * 64)
    print("  收尾：移动审计报告 + 清理 2 条自测记忆")
    print("=" * 64)
    m = do_move()
    n = do_trim()
    ok = verify() and m and (n >= 0)
    print("\n结果：%s" % ("✅ 两件事都完成" if ok else "⚠️ 见上面的提示"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
