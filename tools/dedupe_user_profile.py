# -*- coding: utf-8 -*-
"""清理画像库里的**存量完全重复行**（一次性；去重 bug 修好之前攒下来的）。

【判据】`content` **strip 后逐字相等**才算重复 —— **不做模糊匹配**。
  · 实测存量里「用户 25 岁」有 **15 条一模一样**的（hit_count 全是 0）；
  · 另有一条「25 岁的年轻人，处于事业起步阶段。」**不是完全相等**，
    所以**保留它**（模糊匹配会把"我爱吃香菜"和"我不吃香菜"并成一条 —— 那是载体替它判断）。

【做法】每组保留**最早那条**，把同组其它行的 `hit_count` 累加到它上面，其余删掉。
先备份真库；`--dry` 只报告不改。

运行：python tools/dedupe_user_profile.py [--dry]
"""
import io
import json
import os
import shutil
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from core import user_profile as up  # noqa: E402


def main():
    dry = "--dry" in sys.argv
    rows = up.all_records()
    groups = {}
    for r in rows:
        key = str(r.get("content") or "").strip()
        groups.setdefault(key, []).append(r)
    dups = {k: v for k, v in groups.items() if len(v) > 1}
    extra = sum(len(v) - 1 for v in dups.values())
    print("库里 %d 条；完全重复的组 %d 组，多余行 %d 条" % (len(rows), len(dups), extra))
    for k, v in sorted(dups.items(), key=lambda x: -len(x[1]))[:10]:
        print("  ×%-3d %s" % (len(v), k[:40]))
    if not dups:
        print("没有完全重复，什么都不用做。")
        return 0
    if dry:
        print("（--dry：只报告，不改库）")
        return 0

    if os.path.exists(up.path()):
        bak = os.path.join(_ROOT, "logs", "_user_profile_before_dedupe_%s.jsonl"
                           % time.strftime("%Y%m%d_%H%M%S"))
        shutil.copy2(up.path(), bak)
        print("已备份真库 → %s" % bak)

    keep = []
    seen = {}
    for r in rows:                      # rows 已按时间排序（all_records 保持写入顺序）
        key = str(r.get("content") or "").strip()
        if key and key in seen:
            seen[key]["hit_count"] = int(seen[key].get("hit_count") or 0) + int(r.get("hit_count") or 0)
            continue                    # 多余的这条丢掉（hit_count 已累加到第一条上）
        if key:
            seen[key] = r
        keep.append(r)

    tmp = up.path() + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        for r in keep:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, up.path())
    print("清理后：%d 条（删掉 %d 条完全重复）" % (up.count(), len(rows) - len(keep)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
