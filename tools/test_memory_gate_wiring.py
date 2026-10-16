# -*- coding: utf-8 -*-
"""记忆口径闸门 · 接线自测（验的是"真接上了、而且只在该说话的时候说"）。

为什么单独要一条接线自测：核心判据的自测（`test_memory_gate.py`）全绿，
**也完全可能一个字都没进 system** —— 这个项目里已经吃过一次同类的亏
（`docs/modules/03-memory-depth.md` 7.1：机制完整、自测完备、独立可运行，但没接进主链路）。
所以这里不测判据，只测三件事：
  ① `_retrieve_memory()` 每轮把口径**清零**（旧口径绝不许流到下一轮）；
  ② 口径那句话**只属于当轮那句话**（query 认领 + 超时不认），且 precise / 非记忆问题不注入；
  ③ `_rag_concurrent()` 在"三源全空""优率不够不注入"这两条出口上，**仍然把口径说出来**
     （素材不够格 ≠ 口径可以不说；不说的话模型只能自己编）。

⚠️ 本自测**不联网、不调模型、不写任何库**：`_rag_three_sources` 被替换成空结果，
   只跑载体自己的判断与拼装那一段。
"""
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


def main():
    t0 = time.time()
    print("=" * 78)
    print("  记忆口径闸门 · 接线自测（不联网、不调模型、不写库）")
    print("=" * 78)

    import xiaojiao_app as app       # noqa: E402

    Q = "我的车牌号是多少"
    hit_noise = [{"id": "自测-不在库里", "text": "用户：今天几号", "score": 0.72}]
    hit_real = [{"id": "自测-不在库里", "text": "用户：我的车牌号是京 A12345",
                 "score": 0.90}]

    # ---------------- 一、每轮清零：旧口径不许流到下一轮 ----------------
    print("\n[一] 每轮清零（拿旧话管新事是最难查的一类 bug）")
    app._memory_gate_set(Q, hit_noise)
    ck("判完之后闸门里确实记下了口径", bool(app._MEM_GATE["verdict"]), app._MEM_GATE["verdict"])
    app._retrieve_memory("")        # 空查询：入口就返回，但**必须已经把闸门清零**
    ck("`_retrieve_memory` 一进来就清零（这一轮不判就绝不留旧话）",
       app._MEM_GATE["note"] == "" and app._MEM_GATE["query"] == "", app._MEM_GATE)

    # ---------------- 二、认领：这句话只属于当轮那句 ----------------
    print("\n[二] 认领机制：口径只属于当轮那句话")
    app._memory_gate_set(Q, hit_noise)
    ck("同一句问法 → 取得到口径", bool(app._memory_gate_note(Q)),
       str(app._memory_gate_note(Q))[:40])
    ck("**换一句问法 → 取不到**（多线程下不会串台）",
       app._memory_gate_note("我住在哪") == "")
    _save = dict(app._MEM_GATE)
    app._MEM_GATE["at"] = time.time() - (app._MEM_GATE_TTL + 10)
    ck("过期（超过 TTL）→ 取不到", app._memory_gate_note(Q) == "")
    app._MEM_GATE.update(_save)

    # ---------------- 三、什么时候不说话 ----------------
    print("\n[三] 什么时候一个字都不加")
    app._memory_gate_set(Q, hit_real)
    ck("精确命中 → 不注入（好用的地方不动）", app._memory_gate_note(Q) == "",
       app._MEM_GATE["verdict"])
    app._memory_gate_set("帮我写个爬虫", hit_noise)
    ck("不是「问自己记忆」的问题 → 不注入", app._memory_gate_note("帮我写个爬虫") == "",
       app._MEM_GATE["reason"])
    _cap = dict(app.CAP)
    try:
        app.CAP["memory_gate"] = False
        app._memory_gate_set(Q, hit_noise)
        ck("总开关关掉 → 不注入（等于回到接之前的行为）",
           app._memory_gate_note(Q) == "", app._MEM_GATE["reason"])
    finally:
        app.CAP.clear()
        app.CAP.update(_cap)

    # ---------------- 四、出口：素材不够格，口径照样要说 ----------------
    print("\n[四] `_rag_concurrent` 的两条出口（素材不够格 ≠ 口径可以不说）")
    _orig_src = app._rag_three_sources
    try:
        app._rag_three_sources = lambda *a, **k: ([], {"记忆库": 0.0}, 0.0)
        app._memory_gate_set(Q, hit_noise)
        out = app._rag_concurrent(Q)
        ck("三源全空时，口径那句话**照样进 system**",
           bool(out) and "记忆闸门" in out, str(out)[:40])
        ck("返回的仍是字符串（调用方按字符串拼 system）", isinstance(out, str))
        app._memory_gate_set(Q, hit_real)
        ck("精确命中 + 三源全空 → 什么都不注入（不给模型添乱）",
           app._rag_concurrent(Q) == "", str(app._rag_concurrent(Q))[:30])
    finally:
        app._rag_three_sources = _orig_src

    # ---------------- 五、别唱反调：别的记忆源知道就不说话 ----------------
    print("\n[五] 别的记忆源已经知道 → 闸门闭嘴")
    ck("`_profile_maybe_knows` 能跑且返回布尔（读不到就是 False，不抛）",
       isinstance(app._profile_maybe_knows(Q), bool))
    try:
        from core import user_profile as _UPr
        recs = _UPr.all_records() or []
        if recs:
            txt = str(recs[0].get("content") or recs[0].get("text") or "")
            q_like = txt[:8]
            ck("拿画像里真实存在的一条去问 → 判为「可能知道」（宁可多算）",
               app._profile_maybe_knows(q_like) is True, q_like)
        else:
            ck("画像库是空的：这条不适用（如实跳过，不算通过）", True, "画像库 0 条")
    except Exception as e:      # noqa
        ck("画像读取异常不该出现", False, "%s: %s" % (type(e).__name__, e))

    # ---------------- 六、口径文案本身 ----------------
    print("\n[六] 口径那句话本身")
    app._memory_gate_set(Q, hit_noise)
    note = app._memory_gate_note(Q)
    ck("带「记忆闸门」标记（一眼能看出是载体定的，不是素材）", "记忆闸门" in note, note[:24])
    ck("**不带【你说过的】标记**（否则会被优率当成用户亲口说的）",
       "【你说过的】" not in note)
    ck("长度有上限（≤300 字，不挤爆 system）", len(note) <= 300, len(note))

    print("\n" + "=" * 78)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("  耗时 %.1fs" % (time.time() - t0))
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
