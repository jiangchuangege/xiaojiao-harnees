# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 用户轮的车道（2026-10-28）

【要解决的问题：一句话为什么能等半分钟】
  实测（live 计时，把每一轮的总耗时和"调模型累计"都打出来之后才看清）：
     · 问「今年是哪一年」：**载体 1 毫秒就答完了**，可这一轮总耗时 58 秒，
       期间模型累计被占用 **247 秒**（多次调用并发在飞）。
  也就是说：慢的**不是回答这一步**，而是**后台的那些模型调用**在抢同一颗本地模型。
  本机只有一张卡、一个 llama 进程：谁先到谁先算，用户的一句问话排在
  逛世界 / 记忆保养 / 画像写入 / 固化队列 / 双模型审校 / 元认知 后面 —— 体感就是"慢得要死"。

【这一层做什么】给"用户轮"一条**专属车道**：
  · 用户轮开始 → `begin()`；结束 → `end()`；
  · 后台线程在调模型前调用 `wait_if_background()`：用户轮期间它**等着**，
    等不到（超时）就按调用方自己的策略降级（跳过这次、或延迟到下一轮）。
  这样用户轮几乎独占模型，后台的东西在人看不见的时候再跑。

【边界（不粉饰）】
  1. 这是**让路**，不是"变快"：模型本身的出字速度一点没变，只是不再和后台抢；
  2. 后台任务可能被推迟 —— 它们本来就不该和用户抢，但极端情况下（用户一直说话）
     后台会被一直推迟，所以 `wait_if_background` 有超时上限，超了就照常跑；
  3. 只在**同一进程**内有效（多进程部署要换成文件锁，本轮不需要）。
"""
import logging
import threading
import time

LOG = logging.getLogger(__name__)

_LOCK = threading.Lock()
_STATE = {"active": False, "tid": None, "since": 0.0, "turns": 0, "wait_ms": 0.0,
          "yields": 0}


def begin():
    """用户轮开始（`/api/chat` 入口调）。可重入保护：同一线程重复调用不重复计数。"""
    with _LOCK:
        tid = threading.get_ident()
        if _STATE["active"] and _STATE["tid"] == tid:
            return
        _STATE["active"] = True
        _STATE["tid"] = tid
        _STATE["since"] = time.time()
        _STATE["turns"] = int(_STATE["turns"]) + 1


def end():
    """用户轮结束（无论成功失败都要调，放 finally 里）。"""
    with _LOCK:
        _STATE["active"] = False
        _STATE["tid"] = None
        _STATE["since"] = 0.0


def is_user_turn():
    """当前线程是不是那条用户轮（不是 → 说明是后台线程）。"""
    with _LOCK:
        return bool(_STATE["active"]) and _STATE["tid"] == threading.get_ident()


def wait_if_background(max_wait=20.0, poll=0.05):
    """后台线程调模型前先问一句：「用户正等着吗？」

    返回 True = 让过路（用户轮已结束，可以调）；
    返回 False = 仍在用户轮里（调用方应该**跳过这次后台调用**，别抢）。
    """
    if is_user_turn():
        return True                      # 用户轮自己：永远放行
    t0 = time.time()
    while time.time() - t0 < float(max_wait):
        with _LOCK:
            if not _STATE["active"]:
                waited = (time.time() - t0) * 1000.0
                _STATE["wait_ms"] = round(float(_STATE["wait_ms"]) + waited, 1)
                return True
        time.sleep(poll)
    with _LOCK:
        _STATE["yields"] = int(_STATE["yields"]) + 1
    LOG.info("后台调用让路：用户轮仍在进行（等了 %.1f 秒）→ 这次后台调用先跳过", max_wait)
    return False


def stats():
    with _LOCK:
        return {"active": bool(_STATE["active"]), "turns": int(_STATE["turns"]),
                "wait_ms_total": round(float(_STATE["wait_ms"]), 1),
                "yields": int(_STATE["yields"])}
