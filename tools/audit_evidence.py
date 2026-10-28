# -*- coding: utf-8 -*-
"""证据账本审计器（2026-10-28）

把「历史回答可被重新审计」变成一个命令：

    python tools/audit_evidence.py              # 审最近 20 轮，打印结论
    python tools/audit_evidence.py --save       # 同时写 docs/evidence-audit.md
    python tools/audit_evidence.py --limit 50   # 审更多
    python tools/audit_evidence.py --round <轮次号>   # 只审一轮
    python tools/audit_evidence.py --chain      # 只核哈希链

【为什么要有它】账本的价值在于**能被别人复查**。如果只有插件里那一个入口，
用户想问「上周你说的那句话现在还有依据吗」就得先开着小焦 —— 那不算可核查。
"""
import argparse
import io
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from core import evidence_ledger as EL   # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--round", default="")
    ap.add_argument("--chain", action="store_true")
    ap.add_argument("--save", action="store_true")
    args = ap.parse_args(argv)

    if args.chain:
        c = EL.verify_chain()
        print("哈希链：%s（核对 %d 条）" % ("完整" if c["ok"] else "断了", c["checked"]))
        for b in c["broken"][:5]:
            print("  第 %s 行：%s" % (b.get("line"), b.get("why")))
        return 0 if c["ok"] else 1

    if args.round:
        r = EL.audit_round(args.round)
        print("轮次 %s ｜ %s" % (r.get("id"), r.get("verdict") or r.get("error")))
        print("  断言 %s 条 ｜ 复算有据 %s 条 ｜ 有据比例 %s"
              % (r.get("claims"), r.get("supported"), r.get("ratio")))
        for b in (r.get("recheck_bad") or []):
            print("  ⚠️ %s：%s" % (b.get("value"), b.get("why")))
        for b in (r.get("stale_files") or []):
            print("  ⚠️ 产物已变：%s（%s → %s）" % (b.get("path"), b.get("当时"), b.get("现在")))
        return 0 if not (r.get("recheck_bad") or r.get("missing_blobs")) else 1

    ag = EL.audit_recent(limit=max(1, args.limit))
    st = EL.stats()
    ch = EL.verify_chain()
    print("=" * 88)
    print("  证据账本审计")
    print("=" * 88)
    print("账本：%d 轮 ｜ 快照 %d 份 ｜ 断言 %d 条（有据 %d 条，%.1f%%）"
          % (st["rounds"], st["blobs"], st["claims"], st["supported"], 100.0 * st["ratio"]))
    print("本次复算：审 %d 轮 ｜ 断言 %d 条 ｜ 复算仍有据 %d 条（%.1f%%）"
          % (ag["rounds"], ag["claims"], ag["supported"], 100.0 * ag["ratio"]))
    print("复算不一致：%d 轮 ｜ 有「当时有据、现在失效」：%d 轮 ｜ 哈希链：%s"
          % (ag["recheck_failed"], ag["stale_rounds"], "完整" if ch["ok"] else "断了"))
    bad = [r for r in ag["details"] if (r.get("recheck_bad") or r.get("missing_blobs")
                                        or r.get("stale_files"))]
    if bad:
        print("\n需要看这几轮：")
        for r in bad[:8]:
            print("  `%s` ｜ %s ｜ %s" % (r.get("id"), r.get("verdict"),
                                          str(r.get("question") or "")[:40]))
            for b in (r.get("recheck_bad") or [])[:2]:
                print("      ⚠️ %s：%s" % (b.get("value"), b.get("why")))
            for b in (r.get("stale_files") or [])[:2]:
                print("      ⚠️ 产物已变：%s" % b.get("path"))
    if args.save:
        md = EL.report_md(limit=max(1, args.limit))
        path = os.path.join(_ROOT, "docs", "evidence-audit.md")
        io.open(path, "w", encoding="utf-8", newline="").write(md)
        print("\n已写：docs/evidence-audit.md")
    print("=" * 88)
    return 0 if not (ag["recheck_failed"] or not ch["ok"]) else 1


if __name__ == "__main__":
    sys.exit(main())
