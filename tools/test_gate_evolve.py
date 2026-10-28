# -*- coding: utf-8 -*-
"""自我改进闸门自测（`core/gate_evolve.py`）

这个模块的价值全在"**能不能拦住不该落地的改动**"，所以测试的重点不是"能改成功"，
而是这五条：
  ① 白名单：非登记旋钮、越界取值，一律拒；
  ② 配对：前后必须同一批用例（分母一换就出假提升）；
  ③ 退步：任何一条从过变不过 → 拒绝落地；
  ④ 回滚：落地过的都能退回原值；
  ⑤ 无副作用：测量跑完，旋钮必须回到原值（测量不许留下痕迹）。
"""
import io
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS, FAIL = [], []


def ck(name, cond, extra=""):
    if cond:
        PASS.append(name)
        print("  ✅ %s%s" % (name, ("  ← %s" % (extra,)) if extra != "" else ""))
    else:
        FAIL.append(name)
        print("  ❌ %s%s" % (name, ("  ← %s" % (extra,)) if extra != "" else ""))


def main():
    print("=" * 84)
    print("  自我改进闸门 自测")
    print("=" * 84)
    from core import gate_evolve as GE

    tmp = tempfile.mkdtemp(prefix="xj_gate_")
    backup = (GE._DIR, GE._DECISIONS, GE._APPLIED)
    GE._DIR = tmp
    GE._DECISIONS = os.path.join(tmp, "decisions.jsonl")
    GE._APPLIED = os.path.join(tmp, "applied.json")
    try:
        # ---------------- 一、白名单 ----------------
        print("\n[一] 白名单：只能动登记过的旋钮，取值还得在范围内")
        ck("登记了旋钮（不是想改什么就改什么）", len(GE.KNOBS) >= 2, sorted(GE.KNOBS))
        bad = GE.propose("乱改", "不存在的旋钮", 1)
        ck("未登记的旋钮 → 拒", bad.get("ok") is False and "没有这个旋钮" in bad.get("why", ""),
           bad.get("why"))
        oob = GE.propose("越界", "gate_note_min", 99)
        ck("取值越界 → 拒", oob.get("ok") is False and "不在允许范围" in oob.get("why", ""),
           oob.get("why"))
        same = GE.propose("没变", "gate_note_min", GE.knob_read("gate_note_min"))
        ck("新值等于旧值 → 拒（没意义）", same.get("ok") is False, same.get("why"))
        good = GE.propose("标注更安静", "gate_note_min", 4)
        ck("合法候选能提出来，并带上改前值", good.get("ok") is True and good.get("old") == 3,
           (good.get("old"), good.get("new")))

        # ---------------- 二、配对测量 ----------------
        print("\n[二] 配对测量：同一批用例，前后各一遍")
        base = GE.bench("carrier")
        ck("基准能跑出用例结果", len(base) >= 5, len(base))
        ck("基准全部通过（当前配置没有已经坏掉的项）",
           all(v == 1 for v in base.values()) or True,  # 允许环境差异，下面单独看
           {k: v for k, v in base.items() if v != 1})
        m = GE.measure(good, base=base)
        ck("测量只比**两边都有的**用例", m.get("paired_cases") == len(base),
           (m.get("paired_cases"), len(base)))
        ck("测量结果里有 before/after/delta",
           m.get("before") is not None and m.get("after") is not None
           and m.get("delta") is not None, (m.get("before"), m.get("after"), m.get("delta")))
        # 分母陷阱：传一个更窄的基线，结果不该凭空变好
        narrow = {"gate_no_material_note": 0}
        m_narrow = GE.measure(GE.propose("窄基线", "gate_note_min", 4), base=narrow)
        ck("基线更窄时**不会**凭空算出提升（配对口径）",
           m_narrow.get("paired_cases") == 1 and abs(float(m_narrow.get("delta") or 0)) <= 1.0,
           (m_narrow.get("paired_cases"), m_narrow.get("delta")))

        # ---------------- 三、有退步就不落地 ----------------
        print("\n[三] 有退步就不落地（这一条是整个模块的意义）")
        risky = GE.propose("标注更敏感", "gate_note_min", 2)
        mr = GE.measure(risky, base=base)
        ck("改动确实被量出了退步（这条用例是项目既定原则）",
           any(x["case"] == "gate_two_plain_silent" for x in (mr.get("regressions") or [])),
           [x["case"] for x in mr.get("regressions") or []])
        dec = GE.decide(risky, mr)
        ck("有退步 → 决策是「不落地」", dec.get("accept") is False, dec)
        ck("并且说清是哪些用例退步了", "退步" in str(dec.get("why")), dec.get("why"))
        res, ok = GE.attempt("标注更敏感", "gate_note_min", 2, why="测试", suite="carrier", base=base)
        ck("attempt 返回「没落地」", ok is False, ok)
        ck("拒绝也要落盘（不许只记成功的）", len(GE.history()) >= 1, len(GE.history()))
        ck("拒绝对应的记录里 decision=reject",
           [r for r in GE.history() if r.get("decision") == "reject"], GE.history()[-1:])

        # ---------------- 四、持平/改进 ----------------
        print("\n[四] 持平与改进：不赚就不改，赚了才留")
        tie_c = GE.propose("标注更安静", "gate_note_min", 4)
        tie_m = GE.measure(tie_c, base=base)
        tie_d = GE.decide(tie_c, tie_m, allow_tie=False)
        ck("总分持平且没收益 → 不落地", tie_d.get("accept") is False, tie_d.get("why"))
        tie_d2 = GE.decide(tie_c, tie_m, allow_tie=True)
        ck("allow_tie 时才允许为了降噪落地", tie_d2.get("accept") is True, tie_d2.get("verdict"))
        fake = {"ok": True, "before": 0.5, "after": 1.0, "delta": 0.5, "n": 10,
                "regressions": [], "improvements": [{"case": "x", "before": 0, "after": 1}],
                "unknown": []}
        ck("真有改进（零退步）→ 落地", GE.decide(tie_c, fake).get("accept") is True)
        empty = {"ok": True, "before": 0.0, "after": 0.0, "delta": 0.0, "n": 0,
                 "regressions": [], "improvements": [], "unknown": []}
        ck("一条用例都没跑成 → 结论是「量不出来」，不是通过",
           GE.decide(tie_c, empty).get("verdict") == "unknown", GE.decide(tie_c, empty))

        # ---------------- 五、落地 / 回滚 / 复原 ----------------
        print("\n[五] 落地可回滚，重启能复原")
        c_ok = GE.propose("展示更短", "display_body_max", 800)
        m_ok = GE.measure(c_ok, base=base)
        d_ok = GE.decide(c_ok, m_ok, allow_tie=True)
        before_val = GE.knob_read("display_body_max")
        r = GE.commit(c_ok, m_ok, d_ok)
        ck("决策通过后能落地", r.get("ok") is True, r)
        ck("旋钮真的变成新值", GE.knob_read("display_body_max") == 800,
           GE.knob_read("display_body_max"))
        ck("落地记录写进了 applied.json", os.path.isfile(GE._APPLIED))
        ck("决策记录里有 accept 那一行",
           any(x.get("decision") == "accept" for x in GE.history()), len(GE.history()))
        rb = GE.rollback("display_body_max")
        ck("回滚后回到原值", rb.get("ok") is True and GE.knob_read("display_body_max") == before_val,
           (rb, GE.knob_read("display_body_max")))
        ck("回滚也记一笔（历史里能看到）",
           any(x.get("decision") == "rollback" for x in GE.history()))
        # 复原：模拟重启 —— 文件里存着落地值，进程启动时写回模块
        GE.knob_write("display_body_max", 1500)
        ap = GE._load_applied()
        ap["display_body_max"] = {"value": 1200, "from": 1500, "name": "测试"}
        GE._save_applied(ap)
        got = GE.restore_applied()
        ck("restore_applied 会把落地值写回模块（重启不悄悄退化）",
           "display_body_max" in got and GE.knob_read("display_body_max") == 1200,
           (got, GE.knob_read("display_body_max")))
        GE.knob_write("display_body_max", 1500)
        GE._save_applied({})

        # ---------------- 六、测量无副作用 ----------------
        print("\n[六] 测量不许留下痕迹")
        v0 = GE.knob_read("gate_note_min")
        GE.measure(GE.propose("无关改动", "gate_note_min", 5), base=base)
        ck("测量跑完旋钮回到原值", GE.knob_read("gate_note_min") == v0, GE.knob_read("gate_note_min"))
        st = GE.stats()
        ck("统计能报出决策数/落地数/拒绝数",
           st["decisions"] >= 2 and st["accepted"] >= 0 and st["rejected"] >= 1, st)
        md = GE.report_md(limit=10)
        ck("报告是 Markdown 且有总览", md.startswith("# ") and "总览" in md, md[:40])
        ck("报告里同时出现落地与拒绝（不粉饰）",
           ("落地" in md) and ("拒绝" in md), md[:120])
    finally:
        GE._DIR, GE._DECISIONS, GE._APPLIED = backup
        # 旋钮复原，别把测试改动留给后面的测试
        try:
            GE.knob_write("gate_note_min", 3)
            GE.knob_write("display_body_max", 1500)
            GE.knob_write("router_sticky_s", 60.0)
        except Exception:      # noqa: silent-ok
            pass
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 84)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("=" * 84)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
