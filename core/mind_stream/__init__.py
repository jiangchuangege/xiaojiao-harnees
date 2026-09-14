# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 思维流（Mind Stream）

【一句话】
    让对话从"每轮重新读历史"变成"接着刚才的思考往下走"。

【为什么要它（用户实测）】
    同一会话里连说两次"我叫张三，在济南做后端开发"，小焦两次回答几乎一样。
    说明它每轮都在**重新理解**，没有思维的连续性 ——
    历史只是"参考资料"，没有"我正在想什么"这个状态。
    人的思维是：上一秒在想什么 → 影响下一秒怎么想。

【模块分工（为什么拆三个文件）】
    state.py   状态的定义与落盘（**只定义"有什么"**）
    update.py  每轮怎么演进（**只定义"怎么变"**）
    inject.py  怎么给模型 + 温度（**只定义"给多少/给多热"**）
    拆开的理由：这三件事的**变更频率完全不同** ——
    加字段改 state、改判据改 update、调预算/温度改 inject；
    混在一个文件里早晚长成一个"什么都管"的巨物，谁都改不动。

【使用姿势（一行接入）】
    from core.mind_stream import begin, finish
    st, block = begin(sid, user_input, intent)      # 读状态 + 更新 + 生成注入块
    ... 生成回答 ...
    finish(sid, st, answer, truncated=..., skipped=...)   # 再更新 + 存盘

【两条底线（来自需求，也是设计原则）】
    · 载体只维护**状态**，不给**成句话术**（措辞一律模型自由生成）；
    · 注入 ≤500 token（靠"只给关键的三样"+超预算从后往前砍来保证）。
"""
from . import inject as _inject
from . import state as _state
from . import update as _update

__all__ = ["begin", "finish", "load", "save", "blank", "temperature_for",
           "state", "update", "inject"]


def begin(sid, user_text, intent="chat"):
    """一轮开始时调用：读状态 → 更新 → 产出注入块。

    返回 `(状态, 注入块)`。注入块形如
    `{"text","tokens","used","temp"}`；`used=False` 表示这轮没有可用状态（不必注入）。
    **任何异常都不外抛**：状态是锦上添花，绝不能因为它答不了话。
    """
    try:
        st = _state.load(sid)
        st = _update.after_user(st, user_text)
        block = _inject.build_block(st, text=user_text, intent=intent)
        return st, block
    except Exception:      # noqa: silent-ok — 状态维护失败就当作"这轮没有状态"
        return _state.blank(sid), {"text": "", "tokens": 0, "used": False,
                                   "temp": _inject.TEMP_MID}


def finish(sid, st, answer, truncated=False, skipped=""):
    """一轮结束时调用：更新状态（我刚才在想什么 / 没说出口的话）→ 存盘。

    返回更新后的状态。同样**绝不外抛** —— 已经答好的话不能因为存状态失败而丢。
    """
    try:
        st = _update.after_assistant(st or _state.blank(sid), answer,
                                     truncated=truncated, skipped=skipped)
        _state.save(sid, st)
        return st
    except Exception:      # noqa: silent-ok — 存不上只影响下一轮连续性
        return st or _state.blank(sid)


def load(sid):
    """只读状态（给界面/自检/测试用）。"""
    return _state.load(sid)


def save(sid, st):
    """只写状态（测试与迁移用）。"""
    return _state.save(sid, st)


def blank(sid=""):
    """空状态。"""
    return _state.blank(sid)


def temperature_for(intent="chat", text="", tone="neutral"):
    """温度自适应的对外入口（app 在生成前调它）。"""
    return _inject.temperature_for(intent, text, tone)


def summary(sid):
    """一行摘要（日志/界面用）。"""
    return _state.summary(_state.load(sid))
