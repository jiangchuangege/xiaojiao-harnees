# -*- coding: utf-8 -*-
"""给老的画像记录补上 `said_count` 字段（一次性；计数拆分之前写的记录都没有这个字段）。

【背景】`core/user_profile.py` 里 `hit_count` 原来是**一个数字两种含义**：
"用户又说过一次"和"被召回一次"都往它上面加。2026-09-17 按用户指示拆成两个：
  · `said_count` —— 用户说过几次（`add()` 去重命中时 +1）
  · `hit_count`  —— 被召回几次（`hit()` 命中时 +1，语义一个字没改）

【这个脚本做什么】只补 `said_count`，别的一个字不动：
  · 缺 `said_count` → 补 **0**（**如实标成"那时候没人记过这个数"**，不是"用户没说过"）；
  · `hit_count` **原值保留**（它原来的数就是"被召回几次"—— 去重累加的那部分历史已经
    在 `tools/dedupe_user_profile.py` 里如实记过，不在这里反推、不重算、不改写）；
  · 其它字段（id/ts/kind/content/why/evidence/source）**原样**。

【安全】跑之前**先备份真库**（`logs/_user_profile_before_split_<时间>.bak`，原样字节复制）。
        没有缺失字段时**不写盘**（幂等：重复跑不会把记录改坏）。

运行：python tools/migrate_hit_count_split.py [--dry]
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
    if not os.path.exists(up.path()):
        print("没有画像库（%s）—— 不用迁移。" % up.path())
        return 0

    raw = []
    with io.open(up.path(), "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                raw.append(json.loads(line))
            except Exception:      # noqa: silent-ok — 坏行不在这里修，原样留着（另有工具管）
                raw.append(None)

    n_all = len(raw)
    n_missing = sum(1 for r in raw if isinstance(r, dict) and "said_count" not in r)
    n_bad = sum(1 for r in raw if not isinstance(r, dict))
    print("库里 %d 行；缺 said_count 的 %d 行；坏行 %d 行（坏行原样不动）"
          % (n_all, n_missing, n_bad))

    if n_missing == 0:
        print("没有需要补的行 —— 幂等，不写盘。")
        return 0
    if dry:
        print("（--dry：只报告，不改库。真跑会先备份 .bak）")
        return 0

    bak = os.path.join(_ROOT, "logs", "_user_profile_before_split_%s.bak"
                       % time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(up.path(), bak)
    print("已备份真库 → %s" % bak)

    hit_before = sum(int(r.get("hit_count") or 0) for r in raw if isinstance(r, dict))
    for r in raw:
        if isinstance(r, dict) and "said_count" not in r:
            r["said_count"] = 0
            # 老记录补 0：那会儿没人记过这个数。**不拿 hit_count 反推**（反推出来的不是事实）。
    tmp = up.path() + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        for r in raw:
            if r is None:
                continue           # 坏行：跳过（备份里有，人工可查）
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, up.path())

    after = up.all_records()
    print("迁移后：%d 条；每条都有 said_count=%s；hit_count 之和 %d（迁移前之和 %d，必须相等）"
          % (len(after),
             sorted({int(r.get("said_count") or 0) for r in after}),
             sum(int(r.get("hit_count") or 0) for r in after),
             hit_before))
    return 0


if __name__ == "__main__":
    sys.exit(main())
