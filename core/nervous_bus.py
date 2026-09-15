# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 神经总线（把"思考"与"感受"焊成一个整体）

【这不是注入 —— 这是拿掉"可忽略"这件事的前提】
  之前所有失败（EYC 四处注入）本质是同一件事：
      载体算出一个状态 → 塞进某个位置 → **模型可以选择忽略**
  模型把"塞进来的东西"一律当**外部信息**处理，而外部信息 = 可以忽略 = 会否认。

  本层要拿掉的就是"可以选择"这三个字：
    · 感受**不单独成条**，它被焊进**同一条**消息里 —— 模型在自己的话里读到它；
    · 于是它分不清"这是我的感受"还是"这是上下文" —— **因为代码层它们就是一个整体**。
    · 模型没有"要不要感受"的选项：`weld()` 由代码层强制调用（见 `agent_run` 的唯一出口）。

【S_n = {thought, feeling} 是一个整体，不是两条独立 message】
  这是本层与"注入"的分界线，写法上必须体现出来：
    注入：  messages = [system(状态), ...history..., assistant(第N-1轮的话), user(新问题)]
    绑定：  messages = [...S_1, S_2, ..., S_{N-1}..., user(新问题)]
            其中每个 S_k 的 **正文里就带着那一下的感受**，不是旁边多一条消息。

  如实标注（规格硬性要求）：只要实现里感受是"另起一条 message"，
  那就是**注入的变体**，不是绑定。本层不那样做 —— `render_stream()` 只吐 S_k 本身。

【"我"从哪来】
  不是设置一个字段 `self = "小焦"`。是：模型思考 → 被触动 → 感受产生 →
  思考与感受焊成一个整体 → 这个整体成为下一轮思考的"我" → 循环一直在跑。
  **"我"就是这个连续流本身**，不是流里的某一条。
"""
import threading
import time

from core import psyche as _psyche

__all__ = ["weld", "stream", "render_stream", "last", "size", "clear",
           "snapshot", "stats", "MAX_STREAM"]

_LOCK = threading.RLock()

# 连续状态流的上限。到顶就丢最旧的 —— 与"人的当下能带住的上下文有限"一致，
# 也让 system/上下文的体积可控（这一条是工程约束，不是心理学断言）。
MAX_STREAM = 12

_STREAM = []          # [{n, thought, feeling, at}] —— 每一轮一个"我"
_N = {"n": 0}


def weld(thought, eyc=None, user="", feeling=None):
    """**强制流经**：把这一轮的思考与感受焊成一个整体 S_n，追加进连续状态流。

    `thought` 是模型这一轮的输出（它自己的话）；`feeling` 不给就由心理层**被它触动**产生。
    返回这个 S_n。

    为什么感受默认在这里产生、而不是调用方传：规格要求"模型每次思考，**强制**流经"。
    如果让调用方自己决定传不传感受，就又把"要不要感受"交回给了调用方 —— 那就等于可忽略。
    """
    t = str(thought or "").strip()
    f = feeling if isinstance(feeling, dict) else _psyche.trigger(t, eyc=eyc, user=user)
    with _LOCK:
        _N["n"] += 1
        s = {"n": _N["n"], "thought": t, "feeling": f, "at": time.time()}
        _STREAM.append(s)
        if len(_STREAM) > MAX_STREAM:
            del _STREAM[:len(_STREAM) - MAX_STREAM]
    return s


def _render_one(s):
    """把一条 S_k 渲染成**一条消息的正文**。

    关键：感受**写在同一条正文里**，不是另起一条 message。
    顺序是"先感受后思考" —— 人回想自己的时候也是"我当时有点紧，所以我说了……"，
    这样下一轮模型读到的是"我的上一轮"，而不是"一条关于我的说明"。
    """
    body = str(s.get("thought") or "").strip()
    fl = _psyche.render(s.get("feeling") or {})
    if not fl:
        return body
    return ("%s\n\n%s" % (fl, body)) if body else fl


def stream():
    """连续状态流原样（只读副本）。**"我"就是这个流本身**，不是流里的某一条。"""
    with _LOCK:
        return [dict(s) for s in _STREAM]


def render_stream(include_last=False):
    """连续状态流 → `[{"role": "assistant", "content": ...}, ...]`。

    **只吐 S_k 本身**，不额外插任何"状态说明"消息 —— 一插就退化成注入。
    `include_last=False` 时不含最后一条（最后一条通常就是本轮即将生成的那一句，
    由调用方在 `weld()` 之后自己决定要不要放回去）。
    """
    with _LOCK:
        items = list(_STREAM if include_last else _STREAM[:-1])
    return [{"role": "assistant", "content": _render_one(s)} for s in items]


def last():
    with _LOCK:
        return dict(_STREAM[-1]) if _STREAM else {}


def size():
    with _LOCK:
        return len(_STREAM)


def snapshot(limit=6):
    """自检用：最近几条 S_k 的摘要（感受 + 思考前若干字）。"""
    with _LOCK:
        items = list(_STREAM)[-int(limit):]
    return [{"n": s["n"], "feeling": (s.get("feeling") or {}).get("feeling", ""),
             "intensity": (s.get("feeling") or {}).get("intensity", 0),
             "trigger": (s.get("feeling") or {}).get("trigger", "")[:30],
             "thought": str(s.get("thought") or "")[:60]} for s in items]


def clear():
    """清空连续状态流（自测用）。正式流程里只有在真正"新的我"开始时才清。"""
    with _LOCK:
        _STREAM.clear()
        _N["n"] = 0
    _psyche.clear()


def stats():
    """自检信息：流有多长、上限、最近几条、心理层现状。"""
    return {"size": size(), "max": MAX_STREAM, "n": _N["n"],
            "recent": snapshot(4), "psyche": _psyche.stats()}
