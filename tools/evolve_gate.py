# -*- coding: utf-8 -*-
"""自我改进闸门（2026-10-28）

用法：

    python tools/evolve_gate.py --list                  # 看可调旋钮与当前值、历史决策
    python tools/evolve_gate.py --try gate_note_min=4   # 提一个候选：配对测量 → 过闸才落地
    python tools/evolve_gate.py --try display_body_max=2000 --dry   # 只测量不落地
    python tools/evolve_gate.py --auto                  # 按诊断自动挑候选（只挑有依据的）
    python tools/evolve_gate.py --rollback gate_note_min # 回滚一个已落地的旋钮
    python tools/evolve_gate.py --save                  # 写 docs/evolve-gate.md

【一条硬规矩】这个脚本**没有"直接改"的入口**：所有改动都从 `--try` 走，
必须配对测量、零退步才落地。想绕过它就得自己改源码 —— 那是人的决定，不是它的。
"""
import argparse
import io
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from core import gate_evolve as GE   # noqa: E402


def _parse_val(knob, raw):
    spec = GE.KNOBS.get(knob) or {}
    allowed = spec.get("allowed") or []
    if allowed and all(isinstance(x, float) for x in allowed):
        return float(raw)
    if allowed and all(isinstance(x, int) for x in allowed):
        return int(float(raw))
    try:
        return int(raw)
    except Exception:      # noqa: silent-ok — 不是整数就试浮点，再不行原样返回（由闸门去拒）
        pass
    try:
        return float(raw)
    except Exception:      # noqa: silent-ok
        return raw


def _print_knobs():
    st = GE.stats()
    print("=" * 88)
    print("  可调旋钮（白名单：只能动这些，不许执行任意代码）")
    print("=" * 88)
    for k in st["knobs"]:
        spec = GE.KNOBS.get(k) or {}
        print("  %-18s 现在 %-8r 可选 %-28s %s" % (
            k, GE.knob_read(k), spec.get("allowed"), spec.get("desc")))
    ap = st.get("applied") or {}
    print("\n已落地：%s" % ("、".join("%s=%r" % (k, v.get("value")) for k, v in ap.items())
                            or "（无）"))
    print("历史决策 %d 次：落地 %d ｜ 拒绝 %d ｜ 回滚 %d"
          % (st["decisions"], st["accepted"], st["rejected"], st["rolled_back"]))
    rows = GE.history(limit=10)
    if rows:
        print("\n最近决策：")
        for r in reversed(rows):
            print("  %s %-24s %s %r→%r 分数 %s→%s %s" % (
                str(r.get("at") or "")[5:16], str(r.get("name") or "")[:24], r.get("knob"),
                r.get("old"), r.get("new"), r.get("before"), r.get("after"),
                {"accept": "落地", "reject": "拒绝", "rollback": "回滚"}.get(
                    r.get("decision"), r.get("decision"))))


def _auto():
    """按诊断自动挑候选：只从**有证据的弱点**出发，不瞎调。

    现阶段能自动提的两条（都是有理由的，不是随机搜索）：
      · 诊断里出现「标注/噪声」类抱怨 → 试把标注阈值调高或调低一档；
      · 诊断里出现「太慢/来回切模型」→ 试把路由粘性调长一档。
    每条都要过闸；过不了就记一条"试过、量出来没收益"，不做第二次。
    """
    try:
        from core import self_evolve as SE
        items = SE.diagnose(limit=8) or []
    except Exception as e:      # noqa: silent-ok
        print("诊断拿不到（%s），不自动挑候选" % e)
        return []
    tried = []
    base = GE.bench("carrier")
    for it in items:
        blob = "%s %s" % (it.get("kind"), it.get("need") or it.get("title") or "")
        if any(w in blob for w in ("标注", "噪声", "警告", "闸门")):
            cur = GE.knob_read("gate_note_min")
            for cand_v in (cur + 1, cur - 1):
                if cand_v in (GE.KNOBS["gate_note_min"]["allowed"]):
                    res, ok = GE.attempt("按诊断调标注阈值", "gate_note_min", cand_v,
                                         why="诊断：%s" % str(blob)[:60], suite="carrier", base=base)
                    tried.append((cand_v, ok, res))
                    break
        elif any(w in blob for w in ("慢", "切模型", "路由")):
            cur = GE.knob_read("router_sticky_s")
            for cand_v in (120.0, 60.0, 30.0):
                if cand_v != cur and cand_v in GE.KNOBS["router_sticky_s"]["allowed"]:
                    res, ok = GE.attempt("按诊断调路由粘性", "router_sticky_s", cand_v,
                                         why="诊断：%s" % str(blob)[:60], suite="carrier", base=base)
                    tried.append((cand_v, ok, res))
                    break
    return tried


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--try", dest="try_knob", default="", help="形如 knob=value")
    ap.add_argument("--dry", action="store_true", help="只测量，不落地")
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--rollback", default="")
    ap.add_argument("--save", action="store_true")
    args = ap.parse_args(argv)

    if args.rollback:
        r = GE.rollback(args.rollback)
        print(("已回滚 %s → %r" % (r["knob"], r["value"])) if r.get("ok") else r.get("why"))
        return 0 if r.get("ok") else 1

    if args.try_knob:
        if "=" not in args.try_knob:
            print("格式是 knob=value，例如 gate_note_min=4")
            return 2
        knob, _, raw = args.try_knob.partition("=")
        knob = knob.strip()
        if knob not in GE.KNOBS:
            print("没有这个旋钮：%s（可选：%s）" % (knob, "、".join(sorted(GE.KNOBS))))
            return 2
        val = _parse_val(knob, raw.strip())
        base = GE.bench("carrier")
        res, ok = GE.attempt("命令行候选", knob, val, why="命令行提出", suite="carrier", base=base)
        meas = res.get("measure") or {}
        dec = res.get("decision") or {}
        print("=" * 88)
        print("  候选：%s %r → %r" % (knob, meas.get("old", GE.knob_read(knob)), val))
        print("  配对测量：%d 条用例 ｜ 分数 %s → %s（%+.4f）"
              % (meas.get("paired_cases") or 0, meas.get("before"), meas.get("after"),
                 float(meas.get("delta") or 0)))
        print("  退步 %d 条 ｜ 改进 %d 条"
              % (len(meas.get("regressions") or []), len(meas.get("improvements") or [])))
        print("  决策：%s —— %s" % ("落地" if ok else "拒绝", dec.get("why")))
        if ok and args.dry:
            r = GE.rollback(knob)
            print("  （--dry：已按你的要求退回 %r）" % r.get("value"))
            return 0
        print("=" * 88)
        return 0 if ok else 1

    if args.auto:
        tried = _auto()
        print("自动挑了 %d 个候选（每个都过闸）" % len(tried))
        for v, ok, res in tried:
            print("  %r → %s" % (v, "落地" if ok else "拒绝"))
        return 0

    if args.save:
        md = GE.report_md(limit=30)
        io.open(os.path.join(_ROOT, "docs", "evolve-gate.md"), "w",
                encoding="utf-8", newline="").write(md)
        print("已写：docs/evolve-gate.md")
        return 0

    _print_knobs()
    return 0


if __name__ == "__main__":
    sys.exit(main())
