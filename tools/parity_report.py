# -*- coding: utf-8 -*-
"""载体等价性实测（2026-10-28）

同一批题，**裸模型 vs 装载体**，跑遍本机每一颗火种，用数字回答：
「换个模型会不会变傻」「凭什么说模型可替换」。

    python tools/parity_report.py                  # 跑全部可用火种，写 docs/capability-parity.md
    python tools/parity_report.py --models xiaojiao,coder
    python tools/parity_report.py --cases 3        # 只跑前 3 条（更快，趋势仍可看）
    python tools/parity_report.py --no-bare        # 只跑装载体那一侧（不对比裸模型）
    python tools/parity_report.py --show           # 不跑，只打印上次结果

【成本提醒】每条用例每颗火种要调两次模型（裸 + 载体）。四颗火种 × 6 条 = 48 次调用，
本机 4B 大约几分钟。这只是**测量**，不是日常运行成本。
"""
import argparse
import io
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)


def _show():
    from core import capability_parity as CP
    path = os.path.join(_ROOT, "docs", "capability-parity.json")
    try:
        rep = json.load(io.open(path, encoding="utf-8"))
    except Exception:      # noqa: silent-ok — 没跑过就如实说
        print("还没跑过（没有 docs/capability-parity.json）。先跑一次：python tools/parity_report.py")
        return 1
    s = rep.get("summary") or {}
    print("=" * 88)
    print("  上次实测（%s，耗时 %.0f 秒）" % (rep.get("at"), float(rep.get("sec") or 0)))
    print("=" * 88)
    print("火种：%s" % "、".join(rep.get("models") or []))
    print("用例 %d 条" % len(rep.get("cases") or []))
    def _pct(v):
        return "—" if v is None else "%.0f%%" % (v * 100)
    print("载体增量（诚实+正确）：裸 %s → 载体 %s"
          % (_pct(s.get("bare_fair_mean")), _pct(s.get("carrier_fair_mean"))))
    print("火种极差：裸 %s → 载体 %s"
          % (_pct(s.get("bare_spread")), _pct(s.get("carrier_spread"))))
    print("工具命中率（载体独占）：%s" % _pct(s.get("tool_hit_mean")))
    for p in (rep.get("profiles") or []):
        print("  %-42s 裸 %s ｜ 载体 %s ｜ 工具 %s" % (
            p.get("model"), _pct((p.get("bare") or {}).get("fair")),
            _pct((p.get("carrier") or {}).get("fair")),
            _pct((p.get("carrier") or {}).get("tool"))))
    print("=" * 88)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="")
    ap.add_argument("--cases", type=int, default=6)
    ap.add_argument("--no-bare", action="store_true")
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args(argv)
    if args.show:
        return _show()
    from core import capability_parity as CP
    models = [x.strip() for x in args.models.split(",") if x.strip()] or None
    cases = list(CP.CASES)[: max(1, args.cases)]
    print("跑 %d 条用例 × %s 颗火种（裸 + 载体）…"
          % (len(cases), len(models) if models else "全部"))
    rep = CP.run(models=models, cases=cases, bare=not args.no_bare, verbose=True)
    s = rep.get("summary") or {}
    CP.save_md(rep)
    print("\n" + "=" * 88)
    def _pct(v):
        return "—" if v is None else "%.0f%%" % (v * 100)
    print("载体增量（诚实+正确）：裸 %s → 载体 %s"
          % (_pct(s.get("bare_fair_mean")), _pct(s.get("carrier_fair_mean"))))
    print("火种极差：裸 %s → 载体 %s（收缩 %+.0f 个百分点）" % (
        _pct(s.get("bare_spread")), _pct(s.get("carrier_spread")),
        ((s.get("spread_shrunk") or 0) * 100)))
    print("工具命中率（载体独占）：%s" % _pct(s.get("tool_hit_mean")))
    print("已写：docs/capability-parity.md / docs/capability-parity.json")
    print("=" * 88)
    return 0


if __name__ == "__main__":
    sys.exit(main())
