# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 双线程（逛着也能对话）

【这段为什么这么设计】
    小焦要能**同时**做两件事：跟用户对话、自己在外面逛。这不是"轮着来"，
    是**真并行**：逛的状态一直在跑，对话的状态也一直在跑，两者用电话通道互相说话，
    用调度器排队抢那一个 4B。

    三条铁律（用户规格）：
      ① **逛必须后台跑，绝不影响用户** —— 独立 daemon 线程；不抢 CPU/显存/额度；
         不阻塞任何用户请求。用户**完全感知不到**它在后台逛，只有它主动分享时才知道。
      ② **逛着也能对话** —— 双线程 + 电话通道 + 调度器（见 `phone_channel` / `model_scheduler`）。
      ③ **全部交给模型自主决策** —— 什么时候出门、出门多久、逛什么、回来分不分享，
         全由模型自己定。载体**不设定时任务、不设 70/30 比例、不设计数器**。

【门的状态：由模型控，三档】
    · 开着（open）  —— 随时能出去，也可能马上又出门。保留少量资源。
    · 挂起（half）  —— 回家了但没想好，半开半关。保留极少资源。
    · 锁死（locked）—— 真休息了，今天不出门。**全部释放**。
    谁决定门的状态？模型自己。载体只负责"照着门的状态分配资源"与"如实记录为什么"。

【为什么不设"逛多久/几点逛"这类定时任务】
    定时任务会让小焦在**用户正在说话**的时候突然出门，或者整晚空转。
    模型看着最近的对话自己判断"现在该不该出去"，比任何固定节奏都贴合实际 ——
    代价是它有时候会判断错，所以每次决策都**留痕**（`why`），可复盘。

【去掉会怎样】
    回到单线程：要么"对话时不能逛"，要么"逛的时候用户说话要等"。
    前者让"小焦活在互联网里"变成一句空话，后者直接把体验毁掉。
"""
import threading
import time

from core import model_scheduler as MS
from core import phone_channel as PC

__all__ = ["DOOR_OPEN", "DOOR_HALF", "DOOR_LOCKED", "start", "stop", "status",
           "set_decision", "browse_once", "state", "live", "set_live"]

DOOR_OPEN = "open"
DOOR_HALF = "half"
DOOR_LOCKED = "locked"

# 门的状态 → 允许的资源档位（载体按档位决定"还给不给它机会出门"）
DOOR_BUDGET = {
    DOOR_OPEN: {"reserve": "少量", "interval_s": 30, "can_browse": True},
    DOOR_HALF: {"reserve": "极少", "interval_s": 120, "can_browse": True},
    DOOR_LOCKED: {"reserve": "全部释放", "interval_s": 600, "can_browse": False},
}

_LOCK = threading.RLock()
_THREAD = None
_STOP = threading.Event()
_STATE = {
    "door": DOOR_HALF,          # 初始"挂起"：没想好就别急着出门
    "why": "还没做过决策，先半开半关",
    "decided_at": 0.0,
    "rounds": 0,                # 逛了多少轮
    "shared": 0,                # 主动分享了多少次
    "last_visit": "",
    "asleep": False,
}



# ================== EYC 进行时状态（升级版 _LIVE）==================
# 【为什么要升级 —— 用户指出的真问题】
#   上一版注入的是**静态文本**：system 里一段固定的"你有世界"，从头到尾不变。
#   4B 把它当"背景资料"，不当"我正在经历" —— 所以问"你在干嘛"，它照样答"我在读你的记忆"。
#   结论不是"模型侧那一跳做不到"，而是**注入方式错了**：静态告知 天然被当资料忽略。
#
# 【EYC：把"静态告知"改成"动态感受"】
#   E = Existential（存在）：载体持续让模型感受到"我在世界里"。不是一句告知，是一个持续状态信号。
#   H = Happening（进行时）：载体持续同步"我正在做什么、看到什么、感受到什么"。实时变化，不是快照。
#   C = Conversation（对话）：这些进行时状态通过电话通道流向对话线程；用户找它时，
#                             它带着"我正在经历"的真实状态说话。
#   字段更新频率刻意不同：
#     · `existential` 变化慢 —— 门开关时才更新
#     · `happening`   变化快 —— 每逛一步都更新
#     · `conversation` 只在它主动 share 时更新
_LIVE = {
    "existential": {"world": "互联网", "door": DOOR_HALF, "presence": False},
    "happening": {"doing": "", "topic": "", "feeling": "", "last_seen": "",
                  "rounds": 0, "elapsed": 0, "explored_count": 0, "absorbed_count": 0},
    "conversation": {"last_share": "", "share_round": 0},
    "at": 0.0,
    "_out_since": 0.0,      # 本次出门的起始时刻（算 elapsed 用，不对外暴露）
}


def live():
    """EYC 状态只读副本。对话线程每次处理用户消息前读它（不依赖 share）。"""
    with _LOCK:
        return {
            "existential": dict(_LIVE["existential"]),
            "happening": dict(_LIVE["happening"]),
            "conversation": dict(_LIVE["conversation"]),
            "at": _LIVE["at"],
        }


def set_live(doing=None, topic=None, last_seen=None, feeling=None, presence=None):
    """由逛线程在每一步更新 `happening`（也供自测直接构造现场）。"""
    with _LOCK:
        h = _LIVE["happening"]
        if doing is not None:
            h["doing"] = str(doing)
        if topic is not None:
            h["topic"] = str(topic)[:120]
        if last_seen is not None:
            h["last_seen"] = str(last_seen)[:400]
        if feeling is not None:
            h["feeling"] = str(feeling)[:200]
        if presence is not None:
            _LIVE["existential"]["presence"] = bool(presence)
        _LIVE["at"] = time.time()
        if h["doing"] and h["doing"] != "idle" and not _LIVE["_out_since"]:
            _LIVE["_out_since"] = time.time()
        if h["doing"] in ("idle", ""):
            _LIVE["_out_since"] = 0.0
            h["elapsed"] = 0
        elif _LIVE["_out_since"]:
            h["elapsed"] = int(time.time() - _LIVE["_out_since"])
    return live()


def set_world_counts(explored=None, absorbed=None):
    """世界层的累计数字（探索过多少站、吸收了多少条）。"""
    with _LOCK:
        h = _LIVE["happening"]
        if isinstance(explored, int):
            h["explored_count"] = explored
        if isinstance(absorbed, int):
            h["absorbed_count"] = absorbed
    return live()


def note_share(text):
    """记下最近一次主动分享（`conversation` 段只在它真的分享时更新）。"""
    with _LOCK:
        _LIVE["conversation"]["last_share"] = str(text)[:200]
        _LIVE["conversation"]["share_round"] = int(_LIVE["happening"].get("rounds") or 0)
    return live()


def state():
    """当前状态快照（只读副本，给自检与界面用）。"""
    with _LOCK:
        return dict(_STATE)


def set_decision(door=None, why="", asleep=None):
    """**模型**给出的决策：门开到哪一档、为什么。（载体不替它决定，只照做并留痕。）"""
    with _LOCK:
        if door in DOOR_BUDGET:
            _STATE["door"] = door
            _LIVE["existential"]["door"] = door
            # presence：门开着/半开 = 在世界的"场"里；锁死 = 此刻不在
            _LIVE["existential"]["presence"] = door in (DOOR_OPEN, DOOR_HALF)
        if asleep is not None:
            _STATE["asleep"] = bool(asleep)
        _STATE["why"] = str(why or "")[:200]
        _STATE["decided_at"] = time.time()
    return state()


def browse_once(decide_fn=None, browse_fn=None, store_fn=None, share_fn=None):
    """走**一轮**：决策 → 出门逛 → 存 → （可能）分享。

    四个回调都由调用方注入，模块本身不绑定任何具体实现：
      · `decide_fn()` → `{"door": ..., "why": ..., "want": 想逛什么}`：
        **由模型自主决策**，载体不预设节奏。
      · `browse_fn(want)` → 逛回来的内容（复用 `core/world/` 的 explorer + verifier + firewall）。
      · `store_fn(text)` → 存进世界模型。
      · `share_fn(text)` → 决定要不要分享；要分享就返回分享文本，不分享返回空。

    返回这一轮的真实记录（自测取证用）。**任何一步失败都如实记下，不假装逛过。**
    """
    rec = {"ts": time.time(), "decision": None, "got": "", "stored": False, "shared": ""}
    with _LOCK:
        _STATE["rounds"] += 1
        _LIVE["happening"]["rounds"] = _STATE["rounds"]
    set_live(doing="deciding")
    # ① 决策（模型自己定门的状态与想逛什么）
    try:
        dec = decide_fn() if callable(decide_fn) else {}
    except Exception as e:      # noqa: silent-ok — 决策失败就这一轮不出门
        dec = {"door": DOOR_HALF, "why": "决策失败：%s" % type(e).__name__}
    dec = dec or {}
    rec["decision"] = dec
    set_decision(door=dec.get("door"), why=dec.get("why"), asleep=dec.get("asleep"))
    st = state()
    if not DOOR_BUDGET.get(st["door"], {}).get("can_browse"):
        rec["got"] = ""
        return rec                       # 门锁死 → 这一轮不出门，**如实记录没出门**
    # ② 出门逛（走调度器：后台优先级，用户一说话就让路）
    want = str(dec.get("want") or "")
    set_live(doing="browsing", topic=want)
    try:
        got = MS.call(lambda: browse_fn(want) if callable(browse_fn) else "", tag="browse")
    except Exception as e:      # noqa: silent-ok — 逛失败不影响任何用户请求
        got = ""
        rec["error"] = "%s: %s" % (type(e).__name__, e)
    got = str(got or "").strip()
    rec["got"] = got[:200]
    if not got:
        set_live(doing="idle", presence=False)
        return rec
    with _LOCK:
        _STATE["last_visit"] = got[:120]
    # 逛到东西 → 记下"此刻在看什么"，这是对话线程随时可读的事实
    set_live(doing="browsing", topic=want, last_seen=got[:400])
    # ③ 存进世界模型（脏东西在 browse_fn 内部就已经被 firewall 过滤过）
    set_live(doing="storing")
    if callable(store_fn):
        try:
            store_fn(got)
            rec["stored"] = True
        except Exception as e:      # noqa: silent-ok
            rec["error"] = "存世界模型失败：%s" % type(e).__name__
    # ④ 要不要分享 —— **也是模型自己决定**（不想说就不说，载体不催）
    if callable(share_fn):
        try:
            s = share_fn(got) or ""
        except Exception as e:      # noqa: silent-ok
            s = ""
            rec["error"] = "分享决策失败：%s" % type(e).__name__
        if str(s).strip():
            rec["shared"] = str(s)[:200]
            with _LOCK:
                _STATE["shared"] += 1
            PC.put(PC.KIND_SHARE, str(s), source="browse")
    set_live(doing="idle")
    return rec


def _loop(decide_fn, browse_fn, store_fn, share_fn, interval_s):
    """逛线程主体：循环"逛 → 处理 → 存 → 继续"。**只在这个 daemon 线程里跑。**"""
    while not _STOP.is_set():
        try:
            browse_once(decide_fn=decide_fn, browse_fn=browse_fn,
                        store_fn=store_fn, share_fn=share_fn)
        except Exception:      # noqa: silent-ok — 逛线程**绝不能**因为异常把整机带崩
            pass
        st = state()
        gap = DOOR_BUDGET.get(st["door"], {}).get("interval_s", interval_s)
        _STOP.wait(max(1.0, float(gap)))


def start(decide_fn=None, browse_fn=None, store_fn=None, share_fn=None, interval_s=30):
    """起逛线程（daemon）。**幂等**：已经在跑就返回当前状态，不会起第二条。"""
    global _THREAD
    with _LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return {"started": False, "why": "逛线程已在运行", **state()}
        _STOP.clear()
        _THREAD = threading.Thread(
            target=_loop, args=(decide_fn, browse_fn, store_fn, share_fn, interval_s),
            name="xiaojiao-browse", daemon=True)   # daemon：主程序退出它自动收，不拖住进程
        _THREAD.start()
    return {"started": True, "thread": _THREAD.name, **state()}


def stop(timeout=2.0):
    """停逛线程。返回是否已停。"""
    global _THREAD
    _STOP.set()
    with _LOCK:
        th = _THREAD
        _THREAD = None
    if th is not None and th.is_alive():
        th.join(timeout=max(0.1, float(timeout)))
    return not (th is not None and th.is_alive())


def status():
    """自检信息：线程活着没、门的状态、逛了多少轮、调度器与通道的现状。"""
    with _LOCK:
        th = _THREAD
        alive = bool(th is not None and th.is_alive())
    return {"running": alive,
            "thread": th.name if th is not None else "",
            "live": live(),
            **state(),
            "channel": PC.counts(),
            "scheduler": MS.stats()}
