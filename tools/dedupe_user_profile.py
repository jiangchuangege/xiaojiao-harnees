# -*- coding: utf-8 -*-
"""清理画像库里的**存量完全重复行**（一次性；去重 bug 修好之前攒下来的）。

【判据】`content` **strip 后逐字相等**才算重复 —— **不做模糊匹配**。
  · 实测存量里「用户 25 岁」有 **15 条一模一样**的（hit_count 全是 0）；
  · 另有一条「25 岁的年轻人，处于事业起步阶段。」**不是完全相等**，
    所以**保留它**（模糊匹配会把"我爱吃香菜"和"我不吃香菜"并成一条 —— 那是载体替它判断）。

【做法】每组保留**最早那条**，把同组其它行的计数并到它上面，其余删掉。
  计数怎么并（计数已拆成两个，见 `core/user_profile.py` 头部）：
  · `said_count`（**用户说过几次**）：每多一行就是**多说过一次** → 并进来。
    ⚠️ 老记录没有 `said_count` 字段（拆分前写的），那**不代表用户没说过** ——
    它在库里存在一次就是"被说过一次"，按 **1** 算，不是按 0 算。
    （照字面把老记录当 0 累加，15 行一模一样的东西会并成 `said_count=0` —— 那是把真事记丢。）
  · `hit_count`（**被召回几次**）：**取最大值**，不是求和。
    同一个事实被召回的那些次，是**同一条记忆**被召回，不是几条各召回一次 —— 求和会凭空放大。

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


def merge_duplicates(rows):
    """把**完全重复**的行并成一条。返回 `(keep, merged_info)`，**不改盘**（纯函数，可自测）。

    · 每组保留**最早那条**（rows 是写入顺序）；
    · `said_count` 并起来：**每一行都至少是"被说过一次"** → `max(1, 行自己的 said_count)` 求和，
      保留的那条**自己也算一次**（它不是"零次"）。
      ⚠️ 第一版漏了"自己算一次"这一步：15 行一模一样的东西并出来是 14 不是 15 —— 自测当场抓到，已修。
    · `hit_count` 取**最大值**（同一条记忆被召回几次，不是几条各召回一次）。
    · **没有重复的行一个字不动**（不借这次机会去"顺手规范化"别人的字段）。
    `merged_info` 每项 = (content, said 前, said 后, hit 前, hit 后, 并掉几行)
    """
    first = {}
    dups = {}
    keep = []
    for r in rows:
        key = str(r.get("content") or "").strip()
        if not key:                 # 空 content 不是"重复"，原样留下
            keep.append(r)
            continue
        if key in first:
            dups.setdefault(key, []).append(r)
        else:
            first[key] = r
            keep.append(r)

    merged = []
    for key, extras in dups.items():
        host = first[key]
        said_before = int(host.get("said_count") or 0)
        hit_before = int(host.get("hit_count") or 0)
        host["said_count"] = max(1, said_before) + sum(
            max(1, int(x.get("said_count") or 0)) for x in extras)
        host["hit_count"] = max([hit_before] + [int(x.get("hit_count") or 0) for x in extras])
        merged.append((key, said_before, host["said_count"], hit_before, host["hit_count"],
                       len(extras)))
    return keep, merged


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
        # dry-run 也要把"并完是什么样"算出来（不然看不到它并的是哪个计数）
        _, merged = merge_duplicates(rows)
        print("（--dry：只报告，不改库）")
        for key, so, sn, ho, hn, n in merged[:10]:
            print("  并 %d 行：%s → said_count %d→%d ／ hit_count %d→%d"
                  % (n, key[:24], so, sn, ho, hn))
        print("  预计并掉 %d 行（%d → %d 条）" % (extra, len(rows), len(rows) - extra))
        return 0

    if os.path.exists(up.path()):
        bak = os.path.join(_ROOT, "logs", "_user_profile_before_dedupe_%s.jsonl"
                           % time.strftime("%Y%m%d_%H%M%S"))
        shutil.copy2(up.path(), bak)
        print("已备份真库 → %s" % bak)

    keep, merged = merge_duplicates(rows)
    print("并了 %d 组；例：" % len(merged))
    for key, so, sn, ho, hn, n in merged[:5]:
        print("  %s（并 %d 行）→ said_count %d→%d ／ hit_count %d→%d"
              % (key[:24], n, so, sn, ho, hn))

    tmp = up.path() + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        for r in keep:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, up.path())
    print("清理后：%d 条（删掉 %d 条完全重复）" % (up.count(), len(rows) - len(keep)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
