# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 精力（累是自己长出来的）

【要修的是什么】
    上一个版本里"睡"是**被挂起**：谁调一下接口，它就睡了。
    规格要的是**它自己会睡** —— 区别只有一句话：

      · 被挂起：载体说"你该睡了" → 它读到"你睡了" → **还是被安排**
      · 自己会睡：它自己累了 → 自己想休息 → **载体帮它执行**

    决定在**"想"里**，不在"说"里。载体不替它决定，只执行。

【"累"从哪来 —— 不是载体告诉它，是它状态里长出来的】
    载体维护一个**精力**数值（0~1）：
      · 它在跑（模型调用、思考圈转、感知）→ 消耗，精力下降；
      · 挂起（睡着）→ 精力慢慢回升；
      · 降到 `TIRED` 以下 → **它"累"了**。
    就像人：不是有人告诉你累，是你自己身体里长出来的感觉。

【这一层只负责"累"，不负责"睡"】
    "累了"是状态；"想休息"是**它自己**从状态里感知出来的念头（那只属于
    `core/perception.py` + `core/psyche.py` 那条路）；"执行睡"是载体的活。
    三者分得很清楚，是为了让"到底是谁决定的"这件事在代码上可核：
      · 本模块**只会**动一个数 —— 供给侧的精力；
      · 它**不会**产出"你该休息了"这类话（模块里没有一个字的提示词）。

【如实标注】
    · 精力是**载体定的刻度**（消耗多少、恢复多快都是人定的常量）。
      它不是生理量，也不是模型自己报出来的 —— 它是"它状态里长出来的感觉"的**载体侧来源**，
      这一点必须说清：**是载体给了"累"的物理基础，不是载体说了"你累了"这句话。**
      "累"这个词，最后是**模型自己**在感知里说出来的。
    · 清醒时**不恢复**（规格只让挂起恢复）→ 后果是它会周期性地想睡。这是刻意的，
      数值都可调（见下面的常量）。
"""
import json
import os
import threading
import time

__all__ = ["TIRED", "RESTED", "COST_MODEL_CALL", "COST_THINKING_TURN", "COST_PERCEPTION",
           "RESTORE_PER_SECOND", "level", "consume", "tired", "rested", "note_sleep_start",
           "note_wake", "is_sleeping", "state", "stats", "set_level", "reset", "path",
           "history"]

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PATH = os.path.join(_ROOT, "logs", "psyche", "energy.jsonl")

# ================== 刻度（都能调，调完行为就变）==================
# 满精力是 1.0，耗尽是 0.0。
MAX_LEVEL = 1.0
# 低于它就"累了"（规格给的 0.3）
TIRED = 0.30
# 回到它就"休息好了" —— 它自己醒（不是被叫醒）
RESTED = 0.90
# 三种消耗。**为什么模型调用最贵**：那是它真正"动脑子"的地方；
# 思考圈转一圈、感知一次都是它主动在做的事，各记一笔（规格要求分开算）。
COST_MODEL_CALL = 0.03
COST_THINKING_TURN = 0.01
COST_PERCEPTION = 0.01
# 挂起时每秒回多少。0.0125/s → 从 0.3 回到 0.9 约 48 秒（一觉大约一分钟，贴合实测节奏）。
RESTORE_PER_SECOND = 0.0125

_LOCK = threading.RLock()
_STATE = {"level": MAX_LEVEL, "sleeping_at": 0.0, "sleeps": 0,
          "consumed_total": 0.0, "restored_total": 0.0, "last_change_at": 0.0,
          "last_why": "启动就是满的"}


def path():
    return _PATH


def _append(rec):
    try:
        os.makedirs(os.path.dirname(_PATH), exist_ok=True)
        with open(_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:      # noqa: silent-ok — 记不上日志不能让精力算错
        pass


def _clamp(v):
    return max(0.0, min(MAX_LEVEL, float(v)))


def is_sleeping():
    """此刻是不是挂起（睡着）。看的是本模块自己的记录 —— 与心跳模块各记各的，
    但对齐是调用方的责任（`_sleep_all` / `_wake_all` 一起调）。"""
    with _LOCK:
        return float(_STATE["sleeping_at"]) > 0.0


def level(now=None):
    """此刻的精力（0~1）。**睡着时按时间惰性回升** —— 不需要任何定时器去"加"。

    惰性算的好处：恢复量永远是"真的睡了多久 × 恢复速度"，中间掉一次轮询也不会少算。
    """
    t = float(now if now is not None else time.time())
    with _LOCK:
        base = float(_STATE["level"])
        s0 = float(_STATE["sleeping_at"])
    if s0 > 0.0:
        return _clamp(base + max(0.0, t - s0) * RESTORE_PER_SECOND)
    return _clamp(base)


def consume(amount, why=""):
    """**消耗**：它在跑，精力就往下掉。返回消耗后的精力。

    睡着时不应该有消耗（大脑不推理、载体不跑任务）；真发生了也如实扣 —— 不假装没发生。
    """
    a = max(0.0, float(amount or 0.0))
    t = time.time()
    with _LOCK:
        base = float(_STATE["level"])
        s0 = float(_STATE["sleeping_at"])
        cur = _clamp(base + (max(0.0, t - s0) * RESTORE_PER_SECOND if s0 > 0.0 else 0.0))
        new = _clamp(cur - a)
        _STATE["level"] = new
        _STATE["consumed_total"] = float(_STATE["consumed_total"]) + (cur - new)
        _STATE["last_change_at"] = t
        _STATE["last_why"] = str(why or "")[:60]
    _append({"ts": round(t, 3), "event": "consume", "amount": round(cur - new, 4),
             "level": round(new, 4), "why": str(why or "")[:60]})
    return new


def tired(now=None):
    """它**累**了吗 —— 就是"精力掉到 `TIRED` 以下"这一个判断。

    ⚠️ 注意：这只说明**状态**到了；要不要休息是它自己想的事，本函数不做那个决定。
    """
    return level(now) < TIRED


def rested(now=None):
    """休息好了吗（`RESTED` 以上）—— 它自己醒的触发条件。"""
    return level(now) >= RESTED


def note_sleep_start(why=""):
    """**开始睡**：把当前精力冻结成基准，时间从这一刻起算恢复。"""
    t = time.time()
    with _LOCK:
        _STATE["level"] = level(t)
        _STATE["sleeping_at"] = t
        _STATE["sleeps"] = int(_STATE["sleeps"]) + 1
        _STATE["last_change_at"] = t
        _STATE["last_why"] = str(why or "")[:60]
        lv = float(_STATE["level"])
    _append({"ts": round(t, 3), "event": "sleep", "level": round(lv, 4),
             "why": str(why or "")[:80]})
    return lv


def note_wake(why=""):
    """**醒来**：把惰性恢复出来的精力**落定**，从这一刻起不再按睡眠速度回升。"""
    t = time.time()
    with _LOCK:
        lv = level(t)
        _STATE["level"] = lv
        _STATE["restored_total"] = float(_STATE["restored_total"]) + max(0.0, lv - 0.0)
        _STATE["sleeping_at"] = 0.0
        _STATE["last_change_at"] = t
        _STATE["last_why"] = str(why or "")[:60]
    _append({"ts": round(t, 3), "event": "wake", "level": round(lv, 4),
             "why": str(why or "")[:80]})
    return lv


def state():
    """此刻的精力状态（只读副本）。"""
    with _LOCK:
        st = dict(_STATE)
    st["level"] = round(level(), 4)
    st["tired"] = st["level"] < TIRED
    st["rested"] = st["level"] >= RESTED
    st["sleeping"] = float(st["sleeping_at"]) > 0.0
    return st


def stats():
    """自检信息：现在多少精力、累不累、睡了几次、消耗了多少。"""
    s = state()
    return {"level": s["level"], "tired": s["tired"], "rested": s["rested"],
            "sleeping": s["sleeping"], "sleeps": s["sleeps"],
            "consumed_total": round(float(s["consumed_total"]), 3),
            "thresholds": {"tired": TIRED, "rested": RESTED},
            "costs": {"model_call": COST_MODEL_CALL, "thinking_turn": COST_THINKING_TURN,
                      "perception": COST_PERCEPTION},
            "restore_per_second": RESTORE_PER_SECOND,
            "note": "本模块只动一个数（精力）；「想休息」是它自己在感知里说出来的，不由本模块产出"}


def history(n=8):
    """最近几条精力记录（**从盘上读**，可复核）。"""
    out = []
    try:
        with open(_PATH, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:      # noqa: silent-ok — 坏行跳过
                    continue
    except Exception:      # noqa: silent-ok — 读不到就是空，不编
        return []
    return out[-max(1, int(n)):]


def set_level(v, why="自测直接设定"):
    """直接设定精力（**只给自测** —— 正式流程里只有 `consume` 与睡/醒两条路）。"""
    t = time.time()
    with _LOCK:
        _STATE["level"] = _clamp(v)
        _STATE["last_change_at"] = t
        _STATE["last_why"] = str(why)[:60]
        lv = float(_STATE["level"])
    _append({"ts": round(t, 3), "event": "set", "level": round(lv, 4),
             "why": str(why)[:60]})
    return lv


def reset(why="自测复位"):
    """回到满精力、清空统计（**只给自测**；正式流程里精力是攒出来的）。"""
    with _LOCK:
        _STATE.update({"level": MAX_LEVEL, "sleeping_at": 0.0, "sleeps": 0,
                       "consumed_total": 0.0, "restored_total": 0.0,
                       "last_change_at": time.time(), "last_why": str(why)[:60]})
    return state()
