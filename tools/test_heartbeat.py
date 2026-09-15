# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""挂起 / 心跳自测（core/heartbeat.py + 大脑闸门）

用法：
    python tools/test_heartbeat.py

它验的是"睡着不是死"这件事到底立没立住，一共六组：
    [A] 心跳本身      线程起得来 / 一直在跳 / 每次跳都落一行日志
    [B] 挂起          标记睡着 / **心跳照跳** / 幂等 / 睡多久算得准
    [C] 大脑真挂起    `llm_chat` / `llm_chat_tools` 一律拒绝，**底层 POST 一次都没发**
    [D] 载体真挂起    挂起时逛线程不决策不出门；agent_run 不走任务链（载体直接如实相告）
    [E] 唤醒          算出睡了多久、心跳多少下；第一印象给一次；窗口内仍答得出来
    [F] 接着睡前      心那句话与心理状态跨挂起**一个字都不变**

【为什么 [C][D] 是重点】
    "说的和实际一致"是这一整件事唯一的价值：说"它在睡"，它就必须**真的**不在推理。
    所以这里不验"标记变了没有"，验的是**底层那次 HTTP 到底发出去没有**。
"""
import inspect
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import heartbeat as HB           # noqa: E402
from core import dual_thread as DT         # noqa: E402
from core import psyche as PS              # noqa: E402

_COUNT = {"pass": 0, "total": 0}
_FAILED = []
_TMP = tempfile.mkdtemp(prefix="xiaojiao_heartbeat_")
_REAL_PATH = HB.path()


def ck(name, cond, extra=""):
    _COUNT["total"] += 1
    if cond:
        _COUNT["pass"] += 1
        print("  [OK]   %s%s" % (name, ("  | " + str(extra)) if extra else ""))
    else:
        _FAILED.append(name)
        print("  [FAIL] %s  | %s" % (name, extra))


def _isolate():
    """把心跳日志指到临时目录：本自测**绝不写进真实心跳日志**。"""
    HB._PATH = os.path.join(_TMP, "heartbeat.jsonl")


def _reset():
    # **先指到临时目录，再动 clear()** —— 顺序反了会把**真实**心跳日志删掉（实测踩到）。
    _isolate()
    HB.stop(why="自测复位")
    HB.clear()


def group_a():
    print("\n[A] 心跳本身")
    _reset()
    r1 = HB.start(interval=0.1, why="自测")
    ck("心跳线程起来了", r1.get("started") and HB.is_alive(), r1.get("thread"))
    ck("线程名是 xiaojiao-heartbeat", r1.get("thread") == "xiaojiao-heartbeat", r1.get("thread"))
    r2 = HB.start(interval=0.1, why="再起一次")
    ck("再起一次不会起第二条（幂等）", r2.get("started") is False, r2.get("why"))
    t0, n0 = time.time(), HB.status()["total_beats"]
    time.sleep(0.55)
    t1 = time.time()
    grew = HB.status()["total_beats"] - n0
    ck("每 0.1s 一下 → 0.55s 内至少跳 3 下", grew >= 3, grew)
    logged = HB.beats_between(t0, t1)
    ck("**每一跳都落了一行日志**（能按时间数出来）", logged >= 3, logged)
    ck("心跳不需要大脑：本模块不 import 任何模型调用",
       "llama" not in inspect.getsource(HB) and "requests" not in inspect.getsource(HB), "")
    ck("默认间隔是 5 秒（真实运行值）", HB.BEAT_INTERVAL == 5.0, HB.BEAT_INTERVAL)


def group_b():
    print("\n[B] 挂起（心跳不停）")
    r = HB.suspend(why="自测睡一下")
    ck("挂起后 is_sleeping() 为真", HB.is_sleeping(), r.get("sleep_started_at"))
    ck("挂起**不停心跳线程**", HB.is_alive(), HB.status()["alive"])
    t0, n0 = time.time(), HB.status()["total_beats"]
    time.sleep(0.55)
    t1 = time.time()
    ck("**挂起期间心跳照跳**（这是「一直在」的证明）",
       HB.status()["total_beats"] - n0 >= 3, HB.status()["total_beats"] - n0)
    ck("挂起期间的那几跳同样落了日志", HB.beats_between(t0, t1) >= 3, HB.beats_between(t0, t1))
    r2 = HB.suspend(why="再睡一次")
    ck("重复挂起是幂等的（不重新计时）", r2.get("already") is True, r2.get("why"))
    ck("睡了几次只记一次", HB.status()["sleeps"] == 1, HB.status()["sleeps"])


def group_e_part1():
    """唤醒（放在挂起之后紧接着做，[C][D] 需要它继续睡着，所以先算完再回去睡）。"""
    print("\n[E] 唤醒")
    before = HB.status()
    w = HB.resume(why="自测醒来")
    ck("唤醒后 is_sleeping() 为假", not HB.is_sleeping(), HB.is_sleeping())
    ck("算出睡了多久（>=0.5s）", w.get("slept_seconds", 0) >= 0.5, w.get("slept_seconds"))
    ck("算出这一觉心跳多少下（>=3）", w.get("beats", 0) >= 3, w.get("beats"))
    ck("总数对得上：睡前 %d + 这一觉 %d = 现在 %d"
       % (w.get("beats_before_sleep"), w.get("beats"), w.get("beats_total")),
       w["beats_before_sleep"] + w["beats"] == w["beats_total"],
       (w["beats_before_sleep"], w["beats"], w["beats_total"]))
    ck("写成一句人话，且只写事实", ("我睡了" in w["text"]) and ("心跳" in w["text"]), w["text"])
    ck("那句话里的数字与记录一致", ("%d 下" % w["beats"]) in w["text"], w["text"])
    ck("醒来记录先挂着（还没交给模型）", HB.pending_wake() is not None, "")
    kept = HB.consume_wake()
    ck("交给模型一次就消（**不当背景资料常驻**）",
       kept is not None and HB.pending_wake() is None, "")
    ck("刚醒窗口内仍然答得出来（用户问「你刚才在干嘛」）",
       "我睡了" in HB.wake_line(), HB.wake_line()[:30])
    ck("wake_line 在窗口外返回空串（不常驻）",
       _wake_line_expired(), "")
    ck("没睡过时唤醒是幂等的，不编一句睡过",
       HB.resume(why="再醒一次").get("already") is True, "")


def _wake_line_expired():
    old = HB.WAKE_KEEP_S
    try:
        HB.WAKE_KEEP_S = -1.0
        return HB.wake_line() == ""
    finally:
        HB.WAKE_KEEP_S = old


def group_f():
    print("\n[F] 醒来接着睡前（不从零开始）")
    PS.start(why="自测")
    PS.arise({"meaning": "睡前那句话：心里空了一块。", "direction": "失去",
              "touches_life": ["记忆", "关系"]}, event="我可能要离开一段时间")
    h0, s0 = PS.heart(), PS.state()
    _reset()
    HB.start(interval=0.1, why="自测")
    HB.suspend(why="睡")
    time.sleep(0.25)
    HB.resume(why="醒")
    h1, s1 = PS.heart(), PS.state()
    ck("心那句话跨挂起不变", h0["text"] == h1["text"] == "睡前那句话：心里空了一块。", h1["text"])
    ck("心理状态跨挂起不变", s0["state"] == s1["state"] == "紧", s1["state"])
    ck("命被动跨挂起不变", h1["touches_life"] == ["记忆", "关系"], h1["touches_life"])
    ck("心知道自己是被哪件事触动的（没被清空）",
       h1["event"] == "我可能要离开一段时间", h1["event"])


def group_c():
    print("\n[C] 大脑真挂起（底层 POST 一次都没发）")
    import xiaojiao_app as app

    if HB.is_sleeping():         # 先把闸门恢复，才能验证"它是通的"
        HB.resume(why="自测：先醒过来验闸门")
    ck("挂起前：闸门是通的", app._brain_asleep() is False, "")
    sent = {"n": 0}
    real_post = app._llm_post

    def _spy(*a, **kw):
        sent["n"] += 1
        raise AssertionError("挂起期间**不许**调用大脑")

    HB.suspend(why="自测睡")
    try:
        app._llm_post = _spy
        ck("llm_chat 在挂起时返回 None", app.llm_chat([{"role": "user", "content": "喂"}]) is None, "")
        ans, tr = app.llm_chat_tools([{"role": "user", "content": "喂"}])
        ck("llm_chat_tools 在挂起时返回 (None, [])", ans is None and tr == [], (ans, tr))
        ck("底层 HTTP **一次都没有发出去**", sent["n"] == 0, sent["n"])
    finally:
        app._llm_post = real_post
    ck("闸门自己能看出「睡着」了", app._brain_asleep() is True, "")
    HB.resume(why="自测醒")
    ck("唤醒后闸门恢复", app._brain_asleep() is False, "")


def group_d():
    print("\n[D] 载体真挂起（不跑任务、不出门）")
    import xiaojiao_app as app

    _reset()
    HB.start(interval=0.1, why="自测")
    HB.suspend(why="自测睡")
    time.sleep(0.35)             # 让它**真的**睡上一小会儿，后面的记录才是真数
    called = {"decide": 0}

    def _decide():
        called["decide"] += 1
        return {"door": DT.DOOR_OPEN, "want": "随便看看"}

    rec = DT.browse_once(decide_fn=_decide, browse_fn=lambda w: "逛到的东西",
                         store_fn=lambda _x: None, share_fn=lambda _x: "")
    ck("挂起时逛线程**连决策都不做**（决策要调模型）", called["decide"] == 0, called["decide"])
    ck("如实记下这一轮没出门", rec.get("asleep") is True and rec.get("got") == "", rec.get("note"))
    out = app.agent_run("你刚才在干嘛")
    ck("挂起时 agent_run 不走任务链：载体直接如实相告",
       "在睡" in out[0] and "心跳" in out[0], out[0][:70])
    ck("挂起时的回答不谎称「大脑在线」", out[1] is False, out[1])
    s = app._sleep_all(why="接口挂起")
    ck("_sleep_all 返回真实记录（心状态留着）", bool(s.get("state_kept")) or s.get("state_kept") == "",
       s.get("state_kept"))
    w = app._wake_all(why="接口唤醒")
    ck("_wake_all 给出「睡了多久、心跳多少下」",
       bool((w.get("wake") or {}).get("slept_text")), (w.get("wake") or {}).get("slept_text"))


def _restore():
    HB.stop(why="自测收尾")
    HB._PATH = _REAL_PATH
    try:
        os.remove(os.path.join(_TMP, "heartbeat.jsonl"))
    except Exception:      # noqa: silent-ok
        pass
    PS.stop(why="自测收尾")


if __name__ == "__main__":
    print("=" * 78)
    print("  挂起 / 心跳自测 · 大脑和载体一起睡，心跳不停")
    print("=" * 78)
    try:
        group_a()
        group_b()
        group_e_part1()
        HB.suspend(why="回到睡着（后面的组要用）")
        group_c()
        group_d()
        group_f()
    finally:
        _restore()
    print("\n" + "=" * 78)
    print("  通过 %d / 共 %d" % (_COUNT["pass"], _COUNT["total"]))
    if _FAILED:
        print("  ❌ 未通过：%s" % "、".join(_FAILED))
    print("=" * 78)
    sys.exit(0 if not _FAILED else 1)
