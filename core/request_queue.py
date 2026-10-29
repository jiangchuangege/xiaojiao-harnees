# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 请求队列（2026-10-29）

【要解决什么：并发一压就雪崩】
  外部审计的实测结论（不是猜的）：
     · 空闲单轮完整对话 **58.6 秒**；
     · 有并发任务时 **200~231 秒**；
     · 最坏 **300 秒超时**，且"流式首字 13.5 秒后模型进程崩了一次"。
  根因不在模型，在**没有队列**：本机只有一颗 4B、一张 8G 卡，
  三个请求一起进来就是三个请求一起抢同一颗模型，谁都不快，而且没有任何人知道自己在排第几。

【这一层做什么（三件事，一件都不许多）】
  1. **排队**：同一时刻只让 `concurrency` 个请求进模型；其余**按先来后到**等，不插队、不饿死；
  2. **有位次**：等太久（默认 1.5 秒还没轮到）就**如实返回"你在第 K 位"**，
     而不是让浏览器转圈转到用户以为死机（`try_enter(wait=0)` 拿位次）；
  3. **可中断**：请求被放弃（前端 abort / 用户切走 / 显式 stop）时，`cancel()` 让它
     **在下一个阶段边界就退出**，不再继续烧模型 —— 这一条是"取消要真的取消"，
     不是"前端不看了、后端还在跑"。

【为什么不用第三方队列】
  这是单机单进程的小服务，引入 Redis/Celery 等于给用户加一个必须维护的依赖。
  一个进程内的 FIFO + 条件变量就够，而且**它的行为一眼能读懂**（读得懂才敢信）。

【边界（如实说）】
  · 这是**排队**，不是**加速**：模型出字速度不变，只是不再互相踩；
  · 队列只在**本进程内**有效，多进程部署要换成文件锁；
  · 排队号是"轮到你之前还有几个请求"，中途有人取消会让号往前跳 —— 这是正常的。
"""
import logging
import threading
import time
import uuid

LOG = logging.getLogger(__name__)

_LOCK = threading.Lock()
_CV = threading.Condition(_LOCK)

_STATE = {
    "busy": 0,              # 正在占用名额的请求数
    "concurrency": 1,       # 同时允许多少个（本机一颗卡，默认 1）
    "queue": [],            # 排队中的票号（先来先到）
    "served": 0,            # 累计服务过的请求数
    "cancelled": 0,         # 累计取消数
    "rejected": 0,          # 累计"等不及了直接告知排队中"的次数
    "tickets": {},          # 票号 → {"at", "question", "cancelled"}
    "inside": {},           # 票号 → 进去的时刻（用来兜住"没还名额"的泄漏）
    "wait_ms_total": 0.0,
    "last_wait_ms": 0.0,
    "max_hold_s": 300.0,    # 一次占用最多多久（超过就当它泄漏了，自动收回）
}


def _reap(now=None):
    """把"进去太久没出来"的名额收回。

    【为什么要这个（实测踩到）】`/api/chat/stream` 那条路是生成器：客户端断开时
    Flask **不保证**执行 finally，于是 `leave()` 可能永远不跑 → `busy` 永远停在 1 →
    **之后所有请求都被告知「你在第 1 位」**（实测：一轮评测里 422 个请求被这样挡回去，
    评测分数从 100% 掉到 87.8%）。
    所以名额必须能自愈：谁占太久就自动收回，并且记进日志（不静默）。
    """
    now = now or time.time()
    with _LOCK:
        for tid, at in list(_STATE["inside"].items()):
            if (now - float(at or 0)) > float(_STATE["max_hold_s"]):
                _STATE["inside"].pop(tid, None)
                if _STATE["busy"] > 0:
                    _STATE["busy"] -= 1
                tk = _STATE["tickets"].get(tid)
                if tk is not None:
                    tk["cancelled"] = True
                LOG.warning("队列自愈：票 %s 占了 %.0f 秒没还名额 → 已收回",
                            tid, now - float(at or 0))
        _CV.notify_all()


def configure(concurrency=None):
    """设置并发名额（默认 1：一张卡只装得下一颗模型）。"""
    if concurrency is None:
        return
    with _LOCK:
        _STATE["concurrency"] = max(1, int(concurrency))


def new_ticket(question=""):
    """发一张票（不排队，只是标识）。返回 ticket dict。"""
    tid = uuid.uuid4().hex[:12]
    t = {"id": tid, "at": time.time(),
         "question": str(question or "")[:80], "cancelled": False}
    with _LOCK:
        _STATE["tickets"][tid] = t
        # 顺手清掉 10 分钟前的旧票，别让字典无限长
        old = [k for k, v in _STATE["tickets"].items() if time.time() - v["at"] > 600]
        for k in old:
            _STATE["tickets"].pop(k, None)
    return t


def position(ticket_id):
    """这张票现在排第几（1 = 下一个就是我；0 = 已经进去了或票无效）。"""
    with _LOCK:
        try:
            return _STATE["queue"].index(ticket_id) + 1
        except ValueError:
            return 0


def try_enter(ticket_id, wait=1.5):
    """尝试进入。返回 (是否进去, 位次/说明)。

    · `wait` 秒内等到了名额 → (True, "ok")；
    · 没等到 → (False, 位次)：调用方应当**如实告诉用户**"你在第 K 位"，
      并且**不要**再占线程干等 —— 宁可让用户知道在排队，也不要让连接挂着装死。
    """
    t0 = time.time()
    deadline = t0 + max(0.0, float(wait))
    _reap()          # 进来先自愈一次（谁占太久就收回，别让所有人陪着卡）
    with _LOCK:
        _STATE["queue"].append(ticket_id)
        while True:
            tk = _STATE["tickets"].get(ticket_id) or {}
            if tk.get("cancelled"):
                if ticket_id in _STATE["queue"]:
                    _STATE["queue"].remove(ticket_id)
                return (False, "cancelled")
            # 只有在"队首 + 有空位"时才进 —— 保证先来后到（否则后来的大请求会插队饿死前者）
            first = bool(_STATE["queue"]) and _STATE["queue"][0] == ticket_id
            if first and _STATE["busy"] < int(_STATE["concurrency"]):
                _STATE["queue"].remove(ticket_id)
                _STATE["busy"] += 1
                _STATE["inside"][ticket_id] = time.time()
                waited = (time.time() - t0) * 1000.0
                _STATE["last_wait_ms"] = round(waited, 1)
                _STATE["wait_ms_total"] = round(float(_STATE["wait_ms_total"]) + waited, 1)
                _STATE["served"] += 1
                return (True, "ok")
            left = deadline - time.time()
            if left <= 0:
                # 【必须出队】否则一张"没等到、回去排队页刷新了"的票会**永久占住队首**，
                #   后面所有人都饿死（实测：t2 超时后没出队，t3 明明有空位却排第 2，永远进不去）。
                #   位次要**在出队前**取，否则用户看到的号会凭空少一位。
                pos = (_STATE["queue"].index(ticket_id) + 1) if ticket_id in _STATE["queue"] else 0
                if ticket_id in _STATE["queue"]:
                    _STATE["queue"].remove(ticket_id)
                    _CV.notify_all()
                _STATE["rejected"] += 1
                return (False, pos)
            _CV.wait(min(left, 0.2))


def leave(ticket_id=""):
    """离开（无论成功失败都要调，放 finally）。**幂等**：同张票调两次不会重复扣名额。"""
    with _LOCK:
        held = _STATE["inside"].pop(ticket_id, None) if ticket_id else None
        if held is not None or not ticket_id:
            if _STATE["busy"] > 0:
                _STATE["busy"] -= 1
        _STATE["tickets"].pop(ticket_id, None)
        _CV.notify_all()


def cancel(ticket_id):
    """取消一张票：还在排队的立刻出队；正在跑的会在下一个阶段边界自己退出。"""
    with _LOCK:
        tk = _STATE["tickets"].get(ticket_id)
        if tk is None:
            return False
        tk["cancelled"] = True
        if ticket_id in _STATE["queue"]:
            _STATE["queue"].remove(ticket_id)
        _STATE["cancelled"] += 1
        _CV.notify_all()
        return True


def is_cancelled(ticket_id):
    """这一轮被叫停了吗（长流程里在阶段边界查一次，别等它跑完）。"""
    with _LOCK:
        tk = _STATE["tickets"].get(ticket_id) or {}
        return bool(tk.get("cancelled"))


def stats():
    with _LOCK:
        conc = int(_STATE["concurrency"])
        return {"busy": _STATE["busy"], "concurrency": conc,
                "queued": len(_STATE["queue"]), "served": _STATE["served"],
                "cancelled": _STATE["cancelled"], "rejected": _STATE["rejected"],
                "inside": len(_STATE["inside"]),
                "avg_wait_ms": round(float(_STATE["wait_ms_total"]) /
                                     max(1, _STATE["served"]), 1),
                "last_wait_ms": _STATE["last_wait_ms"],
                "open_tickets": len(_STATE["tickets"])}


def reset():
    """测试用：清空状态（生产代码不要调）。"""
    with _LOCK:
        _STATE["busy"] = 0
        _STATE["queue"] = []
        _STATE["tickets"] = {}
        _STATE["served"] = 0
        _STATE["cancelled"] = 0
        _STATE["rejected"] = 0
        _STATE["wait_ms_total"] = 0.0
        _STATE["last_wait_ms"] = 0.0
        _CV.notify_all()
