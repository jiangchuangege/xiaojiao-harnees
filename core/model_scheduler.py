# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 模型调用调度器（对话优先的排队）

【这段为什么这么设计 —— 一句话：物理上串行，逻辑上并行】
    本地只有一个 4B，显存不够跑两个实例。所以**推理本身必须一个接一个**，
    这一点绕不过去。但"推理串行"**不等于**"两条线程要互相等"：
      · 逛线程的推理在排队时，逛线程的**状态机照常跑**（它在想什么、逛到哪了，都不丢）；
      · 用户一说话，对话线程的调用**插到队头**，逛线程那些**还没开始**的调用让路；
      · 已经跑起来的那一次跑完就交还（不能中途打断 —— 打断了这一轮的 KV 就废了）。
    用户感受到的是"毫秒级排队"，不是"等后台逛完"。这就是"真并行"的落点：
    **并行的是状态，串行的是算力。**

【为什么必须有调度器，而不是让两条线程直接抢模型】
    直接抢会退化成"谁先抢到谁先跑"：逛线程一个小时发几十次调用，对话线程每次都要排队，
    用户就会觉得"小焦答话怎么一顿一顿的"。优先级必须在**载体层**上保证，
    不能指望两条线程自己客气。

【去掉会怎样】
    要么用户被后台拖慢，要么逛线程被对话饿死（永远排不上队，逛到的东西一直说不出来）。
"""
import threading
import time

__all__ = ["call", "PRIORITY_DIALOGUE", "PRIORITY_BROWSE", "stats", "wait_idle"]

PRIORITY_DIALOGUE = "dialogue"
PRIORITY_BROWSE = "browse"

_COND = threading.Condition()
_BUSY = False            # 当前是否有一次推理在跑（物理串行）
_DLG_WAIT = 0            # 有多少个**对话级**调用在等（它们一出现，后台就没资格插队）
_STATS = {"dialogue": 0, "browse": 0, "yielded": 0, "wait_ms_total": 0.0, "max_wait_ms": 0.0}


def call(fn, priority=PRIORITY_BROWSE, tag=""):
    """排队调一次模型。返回 `fn()` 的返回值。

    规则（见模块头）：
      · 有人在跑 → 等；
      · 自己是**后台**调用、且此刻有**对话级**调用在等 → 让路（记一次 `yielded`）；
      · 自己是对话调用 → 只要当前没人跑，立刻上。
    """
    global _BUSY, _DLG_WAIT
    is_dlg = (str(priority) == PRIORITY_DIALOGUE)
    t0 = time.time()
    with _COND:
        if is_dlg:
            _DLG_WAIT += 1
        try:
            while True:
                if not _BUSY and (is_dlg or _DLG_WAIT == 0):
                    break
                if not _BUSY and not is_dlg and _DLG_WAIT > 0:
                    _STATS["yielded"] += 1          # 让路：记一次，供自检看优先级真的生效
                _COND.wait(timeout=0.05)
            _BUSY = True
        finally:
            if is_dlg:
                _DLG_WAIT -= 1
    waited = (time.time() - t0) * 1000.0
    _STATS["dialogue" if is_dlg else "browse"] += 1
    _STATS["wait_ms_total"] += waited
    _STATS["max_wait_ms"] = max(_STATS["max_wait_ms"], waited)
    try:
        return fn()
    finally:
        with _COND:
            _BUSY = False
            _COND.notify_all()


def wait_idle(timeout=5.0):
    """等所有推理跑完（自测与收尾用）。返回是否已空闲。"""
    deadline = time.time() + max(0.0, float(timeout))
    with _COND:
        while _BUSY and time.time() < deadline:
            _COND.wait(timeout=0.05)
        return not _BUSY


def stats():
    """调度器自检：各优先级调用数、后台让路次数、平均/最大排队时间。"""
    n = _STATS["dialogue"] + _STATS["browse"]
    return {"dialogue_calls": _STATS["dialogue"], "browse_calls": _STATS["browse"],
            "yielded": _STATS["yielded"],
            "avg_wait_ms": round(_STATS["wait_ms_total"] / n, 2) if n else 0.0,
            "max_wait_ms": round(_STATS["max_wait_ms"], 2),
            "busy": _BUSY, "dialogue_waiting": _DLG_WAIT}
