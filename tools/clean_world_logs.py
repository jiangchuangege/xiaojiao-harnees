# -*- coding: utf-8 -*-
"""清掉 `logs/world/` 里**自测留下的假内容**（真日志被 example.com 那些测试站点污染了）。

【为什么要清】用户要看"它自己逛了什么"，打开 `logs/world/snapshots.jsonl` 看到的却是
`s1.example.com`、`s2.example.com`、`http://www.baidu.com/s?wd=uuid` 这种**自测桩**，
正文甚至是一个字母 `t` —— 那是测试脚本写进**真日志**的，不是它逛回来的东西。

【做法（照本项目规矩）】**先备份再动**；只清"明确的测试桩"，真内容一条不碰：
  · 域名里含 `example.com` / `example.org` / `localhost` / `127.0.0.1` / `.test` 的条目；
  · 正文/标题只有 1 个字符（`t` 这种）或空白的条目。
被清掉的每一条都写进备份目录的 `removed.txt`（**留档，不丢**）。

用法：
    python tools/clean_world_logs.py          # 只列（默认，不改任何文件）
    python tools/clean_world_logs.py --apply  # 备份 + 真清
"""
import argparse
import io
import json
import os
import shutil
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W = os.path.join(ROOT, "logs", "world")
BACKUP = os.path.join(ROOT, "logs", "backup_before_world_clean")
FAKE_HOSTS = ("example.com", "example.org", "example.net", "localhost", "127.0.0.1",
              ".test", "test.com", "uuid")


def _fake(d):
    """这条是不是测试桩。返回原因或空串。"""
    blob = " ".join(str(d.get(k) or "") for k in ("url", "domain", "title", "text", "detail"))
    low = blob.lower()
    for h in FAKE_HOSTS:
        if h in low:
            return "测试桩地址（%s）" % h
    for k in ("text", "title", "detail"):
        v = str(d.get(k) or "").strip()
        if v and len(v) <= 2:
            return "%s 只有 %d 个字符（占位数据）" % (k, len(v))
    return ""


def main():
    ap = argparse.ArgumentParser(description="清理世界层日志里的自测桩（默认只列）")
    ap.add_argument("--apply", action="store_true", help="备份后真清")
    args = ap.parse_args()

    if not os.path.isdir(W):
        print("没有 logs/world/ 目录，没什么可清")
        return 0
    files = [f for f in sorted(os.listdir(W)) if f.endswith(".jsonl")]
    plan = {}
    for fn in files:
        p = os.path.join(W, fn)
        keep, kill = [], []
        for ln in io.open(p, encoding="utf-8", errors="replace").read().split("\n"):
            if not ln.strip():
                continue
            try:
                d = json.loads(ln)
            except Exception:      # noqa: silent-ok — 坏行原样留着（不丢数据）
                keep.append(ln)
                continue
            why = _fake(d) if isinstance(d, dict) else ""
            (kill if why else keep).append((ln, why) if why else ln)
        if kill:
            plan[fn] = (keep, kill)

    print("=" * 74)
    print("  世界层日志体检：哪些是**自测桩**（不是它逛回来的）")
    print("=" * 74)
    if not plan:
        print("  没有发现自测桩 —— 日志是干净的（幂等，不写盘）")
        return 0
    total = 0
    for fn, (keep, kill) in plan.items():
        print("  %-26s 保留 %-5d 清掉 %d" % (fn, len(keep), len(kill)))
        for ln, why in kill[:3]:
            print("      · %s" % why)
        total += len(kill)
    print("\n  合计要清 %d 条" % total)
    if not args.apply:
        print("\n（这是干跑，一个字都没改。真清请加 --apply）")
        return 0

    bdir = os.path.join(BACKUP, time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(bdir, exist_ok=True)
    rep = io.open(os.path.join(bdir, "removed.txt"), "w", encoding="utf-8")
    for fn, (keep, kill) in plan.items():
        p = os.path.join(W, fn)
        shutil.copy2(p, os.path.join(bdir, fn))            # 先备份
        rep.write("=" * 70 + "\n【%s】清掉 %d 条\n" % (fn, len(kill)))
        for ln, why in kill:
            rep.write("\n[%s]\n%s\n" % (why, ln[:600]))
        tmp = p + ".tmp"
        with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(keep) + ("\n" if keep else ""))
        os.replace(tmp, p)
        print("  已清 %s：%d → %d 行" % (fn, len(keep) + len(kill), len(keep)))
    rep.close()
    # model.json 里的站点表也顺手清（同一类污染）
    mp = os.path.join(W, "model.json")
    if os.path.exists(mp):
        shutil.copy2(mp, os.path.join(bdir, "model.json"))
        try:
            m = json.load(io.open(mp, encoding="utf-8", errors="replace"))
            sites = m.get("sites") or {}
            bad = [k for k in sites if any(h in str(k).lower() for h in FAKE_HOSTS)]
            for k in bad:
                sites.pop(k, None)
            with io.open(mp, "w", encoding="utf-8") as f:
                json.dump(m, f, ensure_ascii=False)
            print("  已清 model.json：去掉 %d 个测试站点（剩 %d 个）" % (len(bad), len(sites)))
        except Exception as e:      # noqa: silent-ok — 清不动就留着
            print("  model.json 清理失败（保留原样）：%r" % e)
    print("\n  备份：%s" % os.path.relpath(bdir, ROOT))
    print("  清单：%s（每一条都在里面，没丢）" % os.path.relpath(os.path.join(bdir, "removed.txt"), ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
