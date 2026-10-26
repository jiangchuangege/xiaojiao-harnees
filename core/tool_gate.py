# -*- coding: utf-8 -*-
"""小焦 · 载体层 · 本轮工具门（执行时再拦一次，防止"看不见但还是调得到"）

【为什么需要它】`core/tool_isolation.py` 只决定了"这一轮工具表里摆哪几个"。
实测：隔离之后模型**照样**照着历史去调那个没装载的工具（问天气时它仍发起了 `web_search`），
因为载体执行工具时只看"这个名字存不存在"，不看"这一轮有没有装载"。

这个项目自己在**渠道隔离**那段就写过同一条道理：
> 只过滤工具表 = **假隔离**；4B 会硬编工具名（实测出现过），看不到不等于调不到。**必须执行时再拦一次。**

本文件就是本轮装载这一层的那道门。

【放行规则（宁放勿误杀）】
  ① 没有本轮上下文（后台任务、内部流水线、非聊天入口）→ **放行**：那道门只属于"聊天这一轮"；
  ② 本轮装载集合里有它 → 放行；
  ③ 用户这一轮**亲口点名**了这个工具名（"用 get_weather 查…"）→ 放行（点名即装，下一轮真会装）；
  ④ 其余 → 拒绝，并回一句中文：本轮可用哪些、想用它该怎么开口。
  ⑤ 拒绝时**绝不抛异常**，也绝不说"已执行"。
"""
import time

_TTL = 300.0          # 一轮的有效期（秒）：超过就当没有上下文，放行
_state = {"tools": frozenset(), "text": "", "at": 0.0, "denied": 0}


def set_turn(names, user_text=""):
    """聊天这一轮开始装载工具时调用：记下"这一轮摆了哪些"。"""
    try:
        _state["tools"] = frozenset(str(x) for x in (names or []) if x)
        _state["text"] = str(user_text or "")
        _state["at"] = time.time()
    except Exception:      # noqa: silent-ok — 记不下来就当没有上下文（放行）
        pass


def clear():
    _state.update({"tools": frozenset(), "text": "", "at": 0.0})


def current():
    """给界面/自检看的真实状态。"""
    fresh = bool(_state["tools"]) and (time.time() - float(_state["at"] or 0)) <= _TTL
    return {"loaded": sorted(_state["tools"]), "count": len(_state["tools"]),
            "fresh": fresh, "denied": int(_state["denied"])}


def check(name):
    """返回 (allowed, note)。note 只在拒绝时非空，且是给模型/用户看的中文。"""
    try:
        name = str(name or "")
        if not name:
            return True, ""
        loaded = _state["tools"]
        if not loaded:                                  # ① 没有本轮上下文
            return True, ""
        if (time.time() - float(_state["at"] or 0)) > _TTL:
            return True, ""
        if name in loaded:                              # ② 本轮装载了
            return True, ""
        if name and name in _state["text"]:             # ③ 用户亲口点名
            return True, ""
        _state["denied"] = int(_state["denied"]) + 1
        avail = sorted(loaded)
        return False, ("⚠️ 这一轮没有装载「%s」，所以不能调用它。本轮可用的是：%s。"
                       "如果确实需要它，直接跟我说「用 %s」，下一轮就会为你装上。"
                       % (name, "、".join(avail[:12]) or "（空）", name))
    except Exception:      # noqa: silent-ok — 门自己出错就放行，绝不把对话卡死
        return True, ""
