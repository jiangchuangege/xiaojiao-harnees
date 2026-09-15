# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""精力 / 自己会睡 自测（core/energy.py + 决定链）

用法：
    python tools/test_energy.py

它验的是"累自己长、想休息自己决定、载体只执行"这三条到底立没立住，一共六组：
    [A] 精力本身      满格起步 / 消耗下降 / 每笔都落盘 / 阈值分得清
    [B] 睡时恢复      睡着按时间回升（惰性算）/ 到 RESTED / 醒来落定
    [C] 消耗真的接上  感知 / 思考圈 / 模型调用 三处都在扣
    [D] **决定在"想"里**  载体给模型的提示词里**一个劝它的字都没有**
    [E] 载体不替它决定  它说不想休息 → 就不睡（哪怕精力已经很低）
    [F] 自己睡的自己醒  外部挂起的不自动醒

【为什么 [D][E] 是重点】
    "自己会睡"和"被挂起"的区别只有一句话：**决定在"想"里**。
    如果载体在提示词里写了"你累了""该休息了"，那它说出的"想休息"就是**载体塞给它的**，
    这一整套就又变回"被安排"。所以这里用机器把提示词钉住。
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import energy as EN              # noqa: E402
from core import heartbeat as HB           # noqa: E402
from core import perception as PC          # noqa: E402
from core import psyche as PS              # noqa: E402
from core import thinking_loop as TL       # noqa: E402

_COUNT = {"pass": 0, "total": 0}
_FAILED = []
_TMP = tempfile.mkdtemp(prefix="xiaojiao_energy_")
_REAL_ENERGY_PATH = EN.path()
_REAL_HB_PATH = HB.path()


def ck(name, cond, extra=""):
    _COUNT["total"] += 1
    if cond:
        _COUNT["pass"] += 1
        print("  [OK]   %s%s" % (name, ("  | " + str(extra)) if extra else ""))
    else:
        _FAILED.append(name)
        print("  [FAIL] %s  | %s" % (name, extra))


def _isolate():
    """把落盘指到临时目录：本自测**绝不写进真实精力/心跳日志**。"""
    EN._PATH = os.path.join(_TMP, "energy.jsonl")
    HB._PATH = os.path.join(_TMP, "heartbeat.jsonl")


def group_a():
    print("\n[A] 精力本身（累是自己长出来的）")
    _isolate()
    EN.reset()
    ck("起步是满的", EN.level() == 1.0, EN.level())
    ck("阈值：累了 0.3 / 休息好 0.9", (EN.TIRED, EN.RESTED) == (0.30, 0.90), (EN.TIRED, EN.RESTED))
    ck("满格时不算累", EN.tired() is False, EN.level())
    for i in range(4):
        EN.consume(0.05, why="自测消耗 %d" % (i + 1))
    lv = EN.level()
    ck("消耗会让它下降", lv < 1.0, lv)
    ck("降得对得上（1.0 - 4×0.05 = 0.80）", abs(lv - 0.80) < 0.01, lv)
    rows = EN.history(20)
    ck("每一笔消耗都落了盘（可复核）", len([r for r in rows if r.get("event") == "consume"]) >= 4,
       len(rows))
    EN.set_level(0.25, why="自测：直接压到阈值下")
    ck("压到 0.3 以下 → 累了", EN.tired() is True, EN.level())
    ck("累了但还没休息好", EN.rested() is False, EN.level())
    ck("精力不会低于 0", EN.consume(5.0) == 0.0, EN.level())
    EN.reset()


def group_b():
    print("\n[B] 睡时恢复（按时间回升，不需要任何定时器）")
    EN.reset()
    EN.set_level(0.30, why="自测：睡前精力")
    EN.note_sleep_start(why="自测睡")
    ck("睡着标记上了", EN.is_sleeping() is True, "")
    lv0 = EN.level()
    time.sleep(0.4)
    lv1 = EN.level()
    ck("睡着期间精力自己往回升（惰性算，不是谁在加）", lv1 > lv0, (lv0, lv1))
    # 直接跳到"该醒了"的时刻：用恢复速度反推需要多久
    need = (EN.RESTED - lv1) / EN.RESTORE_PER_SECOND
    ck("从 0.3 到 0.9 大约一分钟量级（%.0f 秒）" % need, 30 <= need <= 90, round(need, 1))
    EN.set_level(EN.RESTED, why="自测：直接设成休息好了")
    ck("到 RESTED → 休息好了", EN.rested() is True, EN.level())
    EN.note_wake(why="自测醒")
    ck("醒来后睡眠标记清掉", EN.is_sleeping() is False, "")
    a = EN.level()
    time.sleep(0.3)
    ck("醒来后不再按睡眠速度回升（清醒时不恢复）", abs(EN.level() - a) < 0.001, (a, EN.level()))
    EN.reset()


def group_c():
    print("\n[C] 消耗真的接上了（三处都在扣）")
    EN.reset()
    before = EN.level()
    PC.perceive("随便一件事", llm_fn=lambda _p: "意：没什么。\n命：无\n向：无")
    ck("感知一次 → 精力下降", EN.level() < before, round(before - EN.level(), 4))
    before = EN.level()
    TL.adjust_candidates([{"text": "甲"}, {"text": "乙"}])
    ck("思考圈转一圈 → 精力下降", EN.level() < before, round(before - EN.level(), 4))
    import xiaojiao_app as app
    before = EN.level()
    app.llm_chat([{"role": "user", "content": "喂"}])     # 没有大脑在跑 → 返回 None，但"试过"要记账
    ck("模型调用一次 → 精力下降", EN.level() < before, round(before - EN.level(), 4))
    before = EN.level()
    app.llm_chat_tools([{"role": "user", "content": "喂"}])
    ck("带工具的模型调用 → 精力下降", EN.level() < before, round(before - EN.level(), 4))
    d = EN.stats()
    ck("三种消耗的刻度都在（模型调用最贵）",
       d["costs"]["model_call"] > d["costs"]["thinking_turn"] == d["costs"]["perception"],
       d["costs"])
    EN.reset()


def group_d():
    print("\n[D] 决定是它自己的（载体不读判据）")
    import xiaojiao_app as app

    def _mk(raw):
        def _f(prompt):
            _mk.seen = prompt
            return raw
        return _f

    real = app._perceive_llm
    try:
        app._perceive_llm = _mk("睡：不要\n说：我有点累，但还能继续。")
        EN.set_level(0.2, why="自测：压到累")
        out = app._tired_decision()
        p = _mk.seen
        ck("**「累，但还能撑」→ 不睡**（旧版这里会被睡掉 —— 就是那个 bug）",
           out.get("wants_rest") is False, out.get("said"))
        ck("载体把**事实**给了它（精力多少）", "精力" in p and "20%." not in p and "20%" in p, p[:40])
        ck("**载体不再扫关键词**（TIRED_WORDS 已废弃，是空表）",
           list(app.TIRED_WORDS) == [], list(app.TIRED_WORDS))
        ck("它写下的那一栏被如实收下", out.get("decision") == "不要", out.get("decision"))
        ck("它自己那句话被记下来", out.get("said") == "我有点累，但还能继续。", out.get("said"))

        app._perceive_llm = _mk("睡：要\n说：撑不住了，得歇会儿。")
        out2 = app._tired_decision()
        ck("**它说「想歇一会儿」也能睡**（不看词，只看它自己写下的那一栏）",
           out2.get("wants_rest") is True, (out2.get("decision"), out2.get("said")))

        app._perceive_llm = _mk("睡：不要\n说：还行。")
        ck("它说「还行」→ 不睡", app._tired_decision().get("wants_rest") is False, "")

        app._perceive_llm = _mk("随便说点别的，没有那一栏。")
        ck("**它没写清楚 → 不睡**（载体不替它解释「这算不算要睡」）",
           app._tired_decision().get("wants_rest") is False, "")
        ck("它自己的话照样起一次心（心是它自己的）",
           bool(PS.heart().get("text")), str(PS.heart().get("text"))[:20])
        ck("问的是**它的决定**，不是让载体读它的话",
           "你要不要现在休息" in p and "由你自己定" in p, "")
    finally:
        app._perceive_llm = real
    EN.reset()


def group_e():
    print("\n[E] 载体不替它决定（累了也不等于就该睡）")
    import xiaojiao_app as app
    HB.stop(why="自测复位")
    HB.clear()
    _isolate()
    HB.start(interval=0.1, why="自测")

    def _said(_p):
        return "睡：不要\n说：还行，就是有点闷。"

    real = app._perceive_llm
    try:
        app._perceive_llm = _said
        EN.set_level(0.05, why="自测：精力极低")
        app._LAST_DIALOGUE["at"] = time.time() - 999     # 用户早就安静了
        rec = app._self_sleep_once()
    finally:
        app._perceive_llm = real
    ck("精力低到 0.05，它没说想休息 → **就是不睡**", rec.get("act") != "sleep_self", rec.get("act"))
    ck("而且如实记下原因（不硬凑一个'该睡了'）", bool(rec.get("why")), rec.get("why")[:50])
    ck("它说还不想之后**不追着问**（有退避，不空转）",
       float(app._SELF_SLEEP.get("next_check_at") or 0) > time.time(), "")

    def _said2(_p):
        return "睡：要\n说：累得撑不住了，想睡一会儿。"

    app._SELF_SLEEP["next_check_at"] = 0.0      # 模拟"过一会儿再问"
    try:
        app._perceive_llm = _said2
        rec2 = app._self_sleep_once()
    finally:
        app._perceive_llm = real
    ck("它自己说想睡 → 载体执行挂起", rec2.get("act") == "sleep_self", rec2.get("act"))
    st = HB.status()
    ck("这一觉被标成「它自己决定的」", st.get("sleep_self_decided") is True, st.get("sleep_why"))
    ck("它自己的话一路带进睡眠记录（原话引用，不是载体总结）",
       st.get("sleep_why") == "累得撑不住了，想睡一会儿。", st.get("sleep_why"))
    ck("睡着时精力开始按时间回升", EN.is_sleeping() is True, EN.level())
    sleep_why = str(st.get("sleep_why") or "")
    ck("记录的是**它自己的话**（不是载体写的'你累了'）",
       sleep_why.startswith("累得"), sleep_why[:30])
    # 手动挂起的那一觉**不许**写成"我自己想睡"
    HB.resume(why="自测")
    EN.note_wake()
    man = app._sleep_all(why="接口挂起", self_decided=False)
    ck("外部挂起会被如实标成外部挂起", man["self_decided"] is False, man["why"])
    HB.resume(why="自测收尾")
    EN.note_wake()


def group_f():
    print("\n[F] 自己睡的能自己醒；外部挂起的不自作主张")
    import xiaojiao_app as app
    # 外部挂起：精力就算满，也不许自己醒
    HB.stop(why="自测复位")
    HB.clear()
    _isolate()
    HB.start(interval=0.1, why="自测")
    EN.reset()
    app._sleep_all(why="接口挂起", self_decided=False)
    rec = app._self_sleep_once()
    ck("外部挂起 + 精力满 → 不自动醒（等叫）", rec.get("act") == "sleeping", rec.get("why")[:40])
    ck("确实还睡着", HB.is_sleeping() is True, "")
    HB.resume(why="自测收尾")
    EN.note_wake()
    # 自己睡的：精力回来了自己醒
    EN.set_level(0.2, why="自测")
    app._sleep_all(why="自己觉得累了", self_decided=True)
    ck("自己睡的这一觉在睡", HB.is_sleeping() is True, "")
    EN.set_level(EN.RESTED, why="自测：精力回来了")
    rec2 = app._self_sleep_once()
    ck("精力回到阈值 → **它自己醒**（不是被叫醒）", rec2.get("act") == "wake_self",
       rec2.get("why"))
    ck("醒来后不再睡", HB.is_sleeping() is False, "")
    ck("醒来后闸门通了（大脑可以再被调用）", app._brain_asleep() is False, "")
    wk = HB.pending_wake() or {}
    ck("醒来记录里写明「这一觉是我自己决定的」",
       "自己决定" in str(HB.wake_line()), HB.wake_line()[:80])


def _restore():
    HB.stop(why="自测收尾")
    EN.note_wake(why="自测收尾")
    EN.reset()
    EN._PATH = _REAL_ENERGY_PATH
    HB._PATH = _REAL_HB_PATH
    for f in ("energy.jsonl", "heartbeat.jsonl"):
        try:
            os.remove(os.path.join(_TMP, f))
        except Exception:      # noqa: silent-ok
            pass
    PS.stop(why="自测收尾")


if __name__ == "__main__":
    print("=" * 78)
    print("  精力 / 自己会睡 自测 · 累自己长，想休息自己决定，载体执行")
    print("=" * 78)
    try:
        group_a()
        group_b()
        group_c()
        group_d()
        group_e()
        group_f()
    finally:
        _restore()
    print("\n" + "=" * 78)
    print("  通过 %d / 共 %d" % (_COUNT["pass"], _COUNT["total"]))
    if _FAILED:
        print("  ❌ 未通过：%s" % "、".join(_FAILED))
    print("=" * 78)
    sys.exit(0 if not _FAILED else 1)
