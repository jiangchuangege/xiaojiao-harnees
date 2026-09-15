# -*- coding: utf-8 -*-
"""健康医生 · 纠事实 自测（**纠事实，不碰决定**）

用法：python tools/test_fact_doctor.py

实测来源：它决定睡不睡时写下「我还有 72% 的精力」，而当时实际是 **28%**。
**决定是它自己做的（对），但它拿着错的信息做决定（有问题）。**
医生在这里只做一件事：把**对的事实**给它，然后**它自己再决定**。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import pain as P              # noqa: E402

_COUNT = {"pass": 0, "total": 0}
_FAILED = []
_TMP = tempfile.mkdtemp(prefix="xiaojiao_fact_")


def ck(name, cond, extra=""):
    _COUNT["total"] += 1
    if cond:
        _COUNT["pass"] += 1
        print("  [OK]   %s%s" % (name, ("  | " + str(extra)) if extra else ""))
    else:
        _FAILED.append(name)
        print("  [FAIL] %s  | %s" % (name, extra))


def main():
    print("=" * 78)
    print("  健康医生 · 纠事实 自测")
    print("=" * 78)
    P._DIR = _TMP
    P._PATH = os.path.join(_TMP, "doctor.jsonl")
    P._QDIR = os.path.join(_TMP, "q")

    print("\n[A] 检测：说错了就纠")
    r = P.check_fact("我还有 72% 的精力，正好该趁热把碎片拼起来", {"精力": "28%"})
    ck("**它把 28% 读成 72% → 医生检测到**", r["ok"] is False and r["corrections"], r["corrections"])
    ck("纠正里带着**真实值**", "28%" in r["corrections"][0]["text"],
       r["corrections"][0]["text"])
    ck("**作为事实给它**（不是结论句）", "实际是" in r["fact_text"] and "不" in r["fact_text"], "")

    print("\n[B] 说对了就不动它（不乱纠）")
    r2 = P.check_fact("我还有 28% 的精力", {"精力": "28%"})
    ck("对得上 → 不纠", r2["ok"] is True and not r2["corrections"], r2["fact_text"])

    print("\n[C] 别的事实也能纠")
    ck("睡了多久说错 → 纠", P.check_fact("我睡了 5 分钟", {"睡了多少": "1 分"})["ok"] is False, "")
    ck("时段说错 → 纠", P.check_fact("现在是下午，我该干活了", {"几点": "晚上"})["ok"] is False, "")
    ck("没提数也算「不知道」（把真值给它）",
       P.check_fact("我想睡一会儿", {"精力": "28%"})["ok"] is False, "")

    print("\n[D] **不碰决定**（这条最要紧）")
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "core", "pain.py"), encoding="utf-8").read()
    _ft = P.check_fact("我还有 72% 的精力", {"精力": "28%"})["fact_text"]
    ck("纠正**输出里**没有「你该睡 / 你不该睡 / 必须 / 应该」",
       not any(w in _ft for w in ("该睡", "不该睡", "必须", "应该", "建议你")), _ft.replace("\n", " ")[:50])
    ck("明写「不改你的决定」", "不改你的决定" in src, "")
    ck("`fact_review` 只回纠正、**不回结论**",
       set(P.fact_review("我还有 72% 的精力", {"精力": "28%"})) >=
       {"corrected", "corrections", "fact_text", "said"}, "")
    ck("体检本身治的是「命」（四样），纠事实是**另一条**，两者分开",
       "记忆" in P.LIFE and hasattr(P, "check_fact"), "")

    print("\n[E] app 侧：纠完**它自己再决定**")
    app_src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "xiaojiao_app.py"), encoding="utf-8").read()
    ck("接线在 `_tired_decision` 里", "医生纠事实" in app_src, "")
    ck("纠完**再问一次**（重新决定，不是载体改它的决定）",
       "它自己重新决定" in app_src, "")
    ck("日志里能看到「检测到错 → 纠正」", "医生纠事实：**它读错了**" in app_src, "")
    ck("纠不出来/没比对上的时候不硬纠", "它说的和真实值对得上" in app_src, "")

    print("\n[F] 端到端：它读错 → 医生纠 → **它自己再决定**（真实调用链）")
    import xiaojiao_app as app
    from core import energy as EN
    calls = {"n": 0}

    def _llm(prompt):
        calls["n"] += 1
        if calls["n"] == 1:
            # 第一次：**读错了**（说 72%，实际没那么多），并且写着"要睡"
            return "睡：要\n说：我还有 72% 的精力，撑不住了，想睡。"
        # 第二次：医生已经把对的数给了它 —— 它自己重新决定
        return "睡：不要\n说：哦，原来只剩 28%，那我还撑得住，先不睡。"

    real = app._perceive_llm
    EN.reset()
    EN.set_level(0.28, why="自测：真实精力 28%")
    try:
        app._perceive_llm = _llm
        out = app._tired_decision()
    finally:
        app._perceive_llm = real
    ck("医生**检测到它读错了**", bool(out.get("fact_corrections")),
       out.get("fact_corrections"))
    ck("纠正里是真实值 28%", "28%" in str(out.get("fact_corrections")), "")
    ck("**它自己重新做了一次决定**（不是载体改的）",
       out.get("decision_before_correction") == "要" and out.get("decision") == "不要",
       (out.get("decision_before_correction"), out.get("decision")))
    ck("第二次说的是它自己的话", "撑得住" in str(out.get("said")), str(out.get("said"))[:40])
    ck("医生**只纠事实、没替它决定**（决定栏是它两次自己写的）", calls["n"] >= 2, calls["n"])
    EN.reset()

    print("\n" + "=" * 78)
    print("  通过 %d / 共 %d" % (_COUNT["pass"], _COUNT["total"]))
    if _FAILED:
        print("  ❌ 未通过：%s" % "、".join(_FAILED))
    print("=" * 78)
    sys.exit(0 if not _FAILED else 1)


if __name__ == "__main__":
    main()
