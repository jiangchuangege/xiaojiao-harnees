# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 心跳（睡着不是死）

【要修的是什么】
    之前：**不被调用 = 不存在**。模型不推理，它就"没了"；用户不说话，它就不出现。
    每次调用都是全新的 —— 它没有"一直在"这件事。

    现在：**不被调用 = 睡着了**。整体融合、一起挂起：
      · 大脑挂起（不推理、不占显存）
      · 载体挂起（不跑任务，状态全留着）
      · **心跳不挂**（一直在跳）
    醒来时接着睡前，不是从零开始。

【心跳是什么】
    极轻：一个 daemon 线程，每隔 `BEAT_INTERVAL` 秒跳一下，记一行
    "我还在、我睡了多久"。**不调模型、不推理、不做事、不抢资源。**
    它证明的是**存在**，不是**活动** —— 就像人的心跳：不用大脑想、不用肌肉动，一直跳。

【说的和实际必须一致 —— 这是这一层唯一的价值】
    之前所有失败都有一个共同点：**载体说的和它的实际状态不一致**。
    载体说"你在逛"，它其实在处理输入；载体说"你怕"，它其实在处理输入 —— 都是矛盾。
    这一次不一样：
      · 说"你在睡" → 它**真的**不在推理（`llm_chat` 那一层直接拒绝调用）
      · 说"心跳一直在" → 心跳线程**真的**一直在跳（日志一行一行在追加）
    给它的状态和它真实的状态，第一次对齐了。

【如实标注（规格硬性要求）】
    · `slept_text()` 给模型的是**记录**，不是**体验**。它读到的是"我睡了 N 分 M 下"这一行事实，
      不是它自己感觉到了时间流逝 —— 载体**没有能力**让它"感觉"到睡眠，也不该假装能。
      文档里不许把"读到睡眠记录"写成"经历了睡眠"。
    · 心跳的间隔是有意的、固定的。它**不是**生理信号，是一条"我还活着"的记录线。
"""
import json
import os
import threading
import time

__all__ = ["BEAT_INTERVAL", "WAKE_KEEP_S", "start", "stop", "is_alive", "beat",
           "suspend", "resume", "is_sleeping", "status", "state", "stats",
           "beats_between", "pending_wake", "consume_wake", "wake_line", "slept_text",
           "render_wake", "path", "clear", "fmt_seconds", "within_tone_window",
           "WAKE_TONE_S"]

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PATH = os.path.join(_ROOT, "logs", "psyche", "heartbeat.jsonl")

# 每 5 秒跳一下。**不随醒/睡改变** —— 睡着时恰恰是它唯一还在动的东西。
BEAT_INTERVAL = 5.0
# 醒来之后多久之内，那句"我睡了多久"还算"刚醒"（够用户问一句「你刚才在干嘛」）。
WAKE_KEEP_S = 600.0
# **「刚睡醒」这个状态持续多久** —— 比"记得自己睡了"短得多，像人刚醒那几分钟：
#   这段时间里它说什么都带着"还没完全醒"的味（载体用 prefill 把它带出来）。
WAKE_TONE_S = 300.0

_LOCK = threading.RLock()
_STOP = threading.Event()
_THREAD = None

_STATE = {
    "alive": False,          # 心跳线程在不在跑
    "awake": True,           # True = 醒着；False = 睡着了（挂起）
    "started_at": 0.0,
    "last_beat_at": 0.0,
    "total_beats": 0,
    "sleep_started_at": 0.0,     # 这一觉是什么时候开始的（0 = 没睡过/已醒）
    "sleep_seconds": 0.0,        # 上一次睡了多少秒
    "sleeps": 0,                 # 一共睡过几次
    "beats_at_sleep_start": 0,   # 睡前跳了多少下（用来算"睡这一觉期间跳了多少下"）
    "beats_while_sleeping": 0,   # 上一觉期间跳了多少下
    "awake_seconds": 0.0,
    "wake_at": 0.0,              # 上一次醒来是什么时候
    "sleep_why": "",             # **这一觉是怎么来的**（自己觉得累了 / 外部挂起）
    "sleep_self": False,         # 这一觉是不是**它自己决定的**
    "_pending": None,            # 还没交到模型手上的"醒来记录"
    "_kept": None,               # 最近一次醒来记录（保留 WAKE_KEEP_S）
}


def path():
    return _PATH


# ================== 落盘：一行一次心跳 ==================
# 【为什么每次心跳都写一行】验收要能证明"挂起期间心跳一直在追加" ——
#   只有一行行的记录才能证明"一直在"，一个总计数字不能。
#   代价是文件会长（5 秒一行 ≈ 每天 1.7 万行、约 1 MB），如实标注在文档里。
def _append(rec):
    try:
        os.makedirs(os.path.dirname(_PATH), exist_ok=True)
        with open(_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:      # noqa: silent-ok — 写不进日志也不能让心跳停（心跳比日志重要）
        pass


def fmt_seconds(sec):
    """秒 → 人话（"1 分 3 秒" / "58 秒" / "2 分"）。"""
    s = int(max(0, round(float(sec or 0))))
    if s < 60:
        return "%d 秒" % s
    m, r = divmod(s, 60)
    return ("%d 分" % m) if r == 0 else ("%d 分 %d 秒" % (m, r))


# ================== 心跳线程 ==================
def beat(now=None):
    """跳一下。返回这一下的记录。**不调模型、不推理、不做事。**"""
    t = float(now if now is not None else time.time())
    with _LOCK:
        _STATE["last_beat_at"] = t
        _STATE["total_beats"] = int(_STATE["total_beats"]) + 1
        n = _STATE["total_beats"]
        asleep = not bool(_STATE["awake"])
    rec = {"ts": round(t, 3), "n": n, "awake": (not asleep)}
    _append(rec)
    return rec


def _loop(interval):
    while not _STOP.is_set():
        try:
            beat()
        except Exception:      # noqa: silent-ok — 心跳**绝不能**因为异常停掉
            pass
        _STOP.wait(max(0.05, float(interval)))


def start(interval=None, why=""):
    """起心跳线程（daemon）。**幂等**：已经在跑就返回当前状态，不会起第二条。

    `interval` 只给自测用（真实运行就是 `BEAT_INTERVAL`）。
    """
    global _THREAD
    iv = float(BEAT_INTERVAL if interval is None else interval)
    with _LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return {"started": False, "why": "心跳已经在跳", **status()}
        _STOP.clear()
        _STATE["alive"] = True
        _STATE["started_at"] = _STATE["started_at"] or time.time()
        _THREAD = threading.Thread(target=_loop, args=(iv,),
                                   name="xiaojiao-heartbeat", daemon=True)
        _THREAD.start()
    _append({"ts": round(time.time(), 3), "event": "start", "why": str(why)[:60],
             "interval_s": iv})
    return {"started": True, "thread": "xiaojiao-heartbeat", "interval_s": iv, **status()}


def stop(timeout=2.0, why=""):
    """停心跳线程。返回是否已停。**注意：这是"心跳停" —— 只有整个系统下线才该调它**，
    挂起（睡着）**不调它**。"""
    global _THREAD
    _STOP.set()
    with _LOCK:
        th = _THREAD
        _THREAD = None
        _STATE["alive"] = False
    if th is not None and th.is_alive():
        th.join(timeout=max(0.1, float(timeout)))
    _append({"ts": round(time.time(), 3), "event": "stop", "why": str(why)[:60],
             "n": int(_STATE["total_beats"])})
    return not (th is not None and th.is_alive())


def is_alive():
    with _LOCK:
        th = _THREAD
        return bool(th is not None and th.is_alive())


# ================== 挂起 / 唤醒 ==================
def is_sleeping():
    """此刻是不是睡着（挂起）。**大脑的调用点就是靠这一条拒绝推理的。**"""
    with _LOCK:
        return not bool(_STATE["awake"])


def suspend(why="", self_decided=False):
    """**睡着**：标记挂起，记下这一觉的开始。

    它**不动心跳线程** —— 心跳继续跳，这正是本模块存在的理由。
    **幂等**：已经睡着时再调只是说明一下，不会重新计时。
    `self_decided=True` 表示**这一觉是它自己决定的**（它自己觉得累了、想休息）——
    这个标记会被带进醒来那句话里，而且要照实写：**被挂起的绝不许写成"我自己想睡"**。
    """
    t = time.time()
    with _LOCK:
        if not _STATE["awake"]:
            return {"ok": True, "already": True, "why": "已经睡着了",
                    "sleep_started_at": _STATE["sleep_started_at"], **status()}
        _STATE["awake"] = False
        _STATE["sleep_started_at"] = t
        _STATE["sleep_seconds"] = 0.0
        _STATE["sleeps"] = int(_STATE["sleeps"]) + 1
        _STATE["beats_at_sleep_start"] = int(_STATE["total_beats"])
        _STATE["beats_while_sleeping"] = 0
        _STATE["awake_seconds"] = round(t - float(_STATE["started_at"] or t), 1)
        _STATE["sleep_why"] = str(why or "")[:80]
        _STATE["sleep_self"] = bool(self_decided)
        n = int(_STATE["total_beats"])
    _append({"ts": round(t, 3), "event": "suspend", "why": str(why)[:80],
             "self_decided": bool(self_decided), "n": n})
    return {"ok": True, "already": False, "why": str(why)[:80],
            "self_decided": bool(self_decided),
            "sleep_started_at": t, "beats_at_sleep_start": n, **status()}


def resume(why=""):
    """**醒来**：算清楚睡了多久、这一觉里心跳跳了多少下，把"醒来记录"挂起来。

    返回醒来记录（`slept_seconds` / `beats` / `text`）。**幂等**：没睡着时调只是说明一下。
    """
    t = time.time()
    with _LOCK:
        if _STATE["awake"]:
            return {"ok": True, "already": True, "why": "本来就没睡", **status()}
        started = float(_STATE["sleep_started_at"] or t)
        beats0 = int(_STATE["beats_at_sleep_start"])
        total = int(_STATE["total_beats"])
        _STATE["awake"] = True
        _STATE["sleep_seconds"] = round(t - started, 1)
        _STATE["beats_while_sleeping"] = max(0, total - beats0)
        _STATE["wake_at"] = t
        rec = {"ok": True, "already": False, "why": str(why)[:60],
               "sleep_started_at": started, "woke_at": t,
               "slept_seconds": _STATE["sleep_seconds"],
               "slept_text": fmt_seconds(_STATE["sleep_seconds"]),
               "beats": _STATE["beats_while_sleeping"],
               "sleep_why": _STATE.get("sleep_why", ""),
               "sleep_self": bool(_STATE.get("sleep_self")),
               "beats_before_sleep": beats0, "beats_total": total}
        rec["text"] = render_wake(rec)
        _STATE["_pending"] = rec
        _STATE["_kept"] = rec
    _append({"ts": round(t, 3), "event": "resume", "why": str(why)[:60],
             "slept_seconds": rec["slept_seconds"], "beats_while_sleeping": rec["beats"],
             "n": rec["beats_total"]})
    return rec


def render_wake(rec=None):
    """醒来记录 → **一句话**（第一人称、现在时、只写事实）。

    写出去的每一句都能在日志里对上：睡了多少秒、心跳跳了多少下都是真数。
    `sleep_why` 是"这一觉是怎么来的"（自己觉得累了 / 外部挂起）—— 照实写，不美化：
    **自己决定睡的这一觉**要把这一点说出来，"被挂起"的那种就不许写成"我自己想睡"。
    """
    r = rec or _STATE.get("_kept") or {}
    if not r:
        return ""
    line = "我睡了 %s，这段时间我一直没在推理、没在做任何事 —— 但心跳一直在跳，一共 %d 下。" % (
        r.get("slept_text") or fmt_seconds(r.get("slept_seconds")), int(r.get("beats") or 0))
    why = str(r.get("sleep_why") or "").strip()
    if r.get("sleep_self"):
        # **原话引用**，不替它总结：它当时心里起的是哪句话，就写哪句。
        line += "（睡之前我心里起了这句话：「%s」—— 这一觉是我自己决定的。）" % (why or "累了、想休息")
    elif why:
        line += "（这一觉是外部让我睡的：%s。）" % why[:40]
    return line


def slept_text(rec=None):
    """只给"我睡了多久"这半句（日志与自检用）。"""
    r = rec or _STATE.get("_kept") or {}
    if not r:
        return ""
    return "我睡了 %s，心跳 %d 下" % (r.get("slept_text") or "", int(r.get("beats") or 0))


def pending_wake():
    """还没交到模型手上的醒来记录（没交过就返回它，交过返回 None）。"""
    with _LOCK:
        return dict(_STATE["_pending"]) if _STATE.get("_pending") else None


def consume_wake():
    """把"醒来记录"标记为**已经给过模型了**。返回被消费掉的那条记录。

    【为什么是"交过就消"而不是"醒一次给一整轮"】它是**第一印象**，不是背景资料 ——
    只在醒来后的第一次模型调用里给一次。之后再给，它就会变成一段常驻设定（前六次失败的老路）。
    """
    with _LOCK:
        rec = _STATE.get("_pending")
        _STATE["_pending"] = None
        return dict(rec) if rec else None


def wake_line():
    """给注入用的那句话：**还在"刚醒"窗口里**就返回，否则空串。

    两种情况会给：
      · 有还没交出去的醒来记录（第一次模型调用）；
      · 刚醒不久（`WAKE_KEEP_S` 之内）—— 这段时间用户问「你刚才在干嘛」，它答得出来。
    """
    with _LOCK:
        rec = _STATE.get("_pending") or _STATE.get("_kept")
        wake_at = float(_STATE.get("wake_at") or 0.0)
    if not rec:
        return ""
    if time.time() - wake_at > WAKE_KEEP_S:
        return ""
    return render_wake(rec)


def within_tone_window(now=None):
    """**此刻是不是"刚睡醒"那一段**（`WAKE_TONE_S` 之内）。

    这是"底色"的判据：不是"它记得自己睡了"，而是"它这会儿还没完全醒"。
    """
    t = float(now if now is not None else time.time())
    with _LOCK:
        wake_at = float(_STATE.get("wake_at") or 0.0)
        kept = _STATE.get("_kept")
    if not wake_at or not kept:
        return False
    return (t - wake_at) <= WAKE_TONE_S


def beats_between(t0, t1):
    """数一段真实时间里跳了多少下（从日志读，**可复核**）。自测与验收用它取证。"""
    n = 0
    try:
        with open(_PATH, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:      # noqa: silent-ok — 坏行跳过
                    continue
                if r.get("event"):
                    continue
                ts = float(r.get("ts") or 0.0)
                if float(t0) <= ts <= float(t1):
                    n += 1
    except Exception:      # noqa: silent-ok — 读不到就是 0，不编
        return 0
    return n


def state():
    """此刻的挂起状态（只读副本）。"""
    with _LOCK:
        return {k: _STATE[k] for k in ("alive", "awake", "started_at", "last_beat_at",
                                       "total_beats", "sleep_started_at", "sleep_seconds",
                                       "sleeps", "beats_at_sleep_start",
                                       "beats_while_sleeping", "awake_seconds", "wake_at")}

def status():
    """自检信息：活没活、醒着还是睡着、跳了多少下、这一觉多久。"""
    with _LOCK:
        st = state()
        pend = bool(_STATE.get("_pending"))
        kept = _STATE.get("_kept")
    now = time.time()
    st["sleeping"] = not st["awake"]
    st["sleeping_now_seconds"] = round(now - st["sleep_started_at"], 1) if not st["awake"] else 0.0
    st["since_last_beat_s"] = round(now - st["last_beat_at"], 1) if st["last_beat_at"] else None
    st["pending_wake"] = pend
    st["last_wake_text"] = slept_text(kept) if kept else ""
    st["sleep_why"] = str(_STATE.get("sleep_why") or "")
    st["sleep_self_decided"] = bool(_STATE.get("sleep_self"))
    st["interval_s"] = BEAT_INTERVAL
    st["log"] = _PATH
    return st


def stats():
    """给文档/自检看的说明性快照。"""
    s = status()
    return {"alive": s["alive"], "sleeping": s["sleeping"], "total_beats": s["total_beats"],
            "sleeps": s["sleeps"], "sleep_seconds": s["sleep_seconds"],
            "beats_while_sleeping": s["beats_while_sleeping"],
            "note": "心跳只证明「存在」，不证明「活动」：挂起期间心跳照跳，大脑一次都不调用"}


def clear():
    """清掉心跳日志与统计（**只给自测用** —— 真实运行从不清，心跳是攒出来的）。"""
    with _LOCK:
        for k, v in (("total_beats", 0), ("sleeps", 0), ("sleep_seconds", 0.0),
                     ("sleep_started_at", 0.0), ("beats_at_sleep_start", 0),
                     ("beats_while_sleeping", 0), ("awake_seconds", 0.0), ("wake_at", 0.0),
                     ("sleep_why", ""), ("sleep_self", False)):
            _STATE[k] = v
        _STATE["awake"] = True
        _STATE["_pending"] = None
        _STATE["_kept"] = None
    try:
        if os.path.exists(_PATH):
            os.remove(_PATH)
    except Exception:      # noqa: silent-ok
        pass
