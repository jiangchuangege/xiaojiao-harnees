# -*- coding: utf-8 -*-
"""把血管那条链的旧库 `xiaojiao_profiles.json` 迁移进**唯一画像库** core.user_profile。

【为什么迁】原来两份画像数据并存（user_profile.jsonl 与 xiaojiao_profiles.json），早晚打架。
现在分工是死的：画像系统（core.user_profile）= 唯一写入口；血管 = 只召回。
所以旧库里的记录要搬进 user_profile，搬完把旧文件改名 `.bak`（**不删**）。

【幂等】`up.add()` 现在按 content 完全相等去重 —— 重复跑不会写出第二份。

运行：python tools/migrate_profiles_to_user_profile.py
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

OLD = os.path.join(_ROOT, "xiaojiao_profiles.json")


def main():
    if not os.path.exists(OLD):
        print("没有 %s —— 已经迁过了（或本来就没有），不用做。" % OLD)
        return 0
    # 先备份真库（迁移改的是它，出错要能退回去）
    if os.path.exists(up.path()):
        bak = os.path.join(_ROOT, "logs", "_user_profile_before_migrate_%s.jsonl"
                           % time.strftime("%Y%m%d_%H%M%S"))
        shutil.copy2(up.path(), bak)
        print("已备份真库 → %s" % bak)

    try:
        doc = json.load(io.open(OLD, encoding="utf-8"))
    except Exception as e:
        print("❌ 读不了旧库：%s" % e)
        return 1
    rows = doc.get("profiles") if isinstance(doc, dict) else doc
    if not isinstance(rows, list):
        print("❌ 旧库结构不认识（既不是 {profiles:[…]} 也不是 […]）")
        return 1

    before = up.count()
    moved = skipped = 0
    for r in rows:
        if not isinstance(r, dict):
            skipped += 1
            continue
        text = str(r.get("text") or r.get("content") or "").strip()
        kind = r.get("type") or r.get("kind") or "背景"
        if not text:
            skipped += 1
            continue
        rid = up.add(kind, text, source="迁移自 xiaojiao_profiles.json")
        if rid:
            moved += 1
        else:
            skipped += 1

    # 搬完把旧文件改名（**不删**）
    bak = OLD + ".bak"
    if os.path.exists(bak):
        bak = OLD + ".bak.%s" % time.strftime("%H%M%S")
    os.rename(OLD, bak)

    print("旧库 %d 条 → 迁移调用 %d 次（成功 %d / 跳过 %d）" % (len(rows), moved + skipped, moved, skipped))
    print("唯一画像库：%d 条 → %d 条" % (before, up.count()))
    print("旧库已改名：%s（没删）" % os.path.basename(bak))
    return 0


if __name__ == "__main__":
    sys.exit(main())
