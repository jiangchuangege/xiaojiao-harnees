# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
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

【2026-10-17 补的第五道判据：不信"记下来的表"，按用户原话再判一次】
  实战漏过一次：`_plan_tools` 有一处早记账，那次 `user_text` 是空的 → 隔离没生效 →
  记下来的表里仍有 `web_search` → 门照着表放行，问天气时旁路照样联网。
  根因是"门完全信任调用方记什么"。现在多一条**独立判据**：
  这一轮用户原话命中了某个专用工具（`tool_isolation.specialized_for`）时，
  通用兜底工具（`GENERIC`）即使出现在记账里也不放行（除非用户亲口点了它的名字）。
  这样即便某条 plan 路径记错了表，隔离也不会被记账错误抹掉。
"""
import time

_TTL = 300.0          # 一轮的有效期（秒）：超过就当没有上下文，放行
_state = {"tools": frozenset(), "text": "", "at": 0.0, "text_at": 0.0, "denied": 0}


def begin_turn(user_text=""):
    """聊天这一轮**一开始**就调用：只记"用户这句话"，不碰装载表。

    为什么需要它：这一轮里有几处联网发生在**工具规划之前**（RAG 的联网源、"提醒词前先检索"），
    那时候 `set_turn` 还没被调用过，`check()` 会当成"没有本轮上下文（后台任务）"而放行。
    实测漏点就在这里：问天气时先打出"检索命中"，之后才打出"工具隔离"。
    记下原话之后，即使装载表还没到，第 ④ 条独立判据也能立刻生效。
    """
    try:
        _state["text"] = str(user_text or "")
        _state["text_at"] = time.time()
        # **上一轮的装载表当场作废**：新的一轮还没规划工具，拿上一轮的表来管这一轮
        # 就会误伤（实测：上一轮问天气只装了 4 个 → 下一轮问新闻，联网在规划之前被
        # "这一轮没有装载 web_search"挡掉，新闻也答不出来了）。
        # 作废之后，规划之前只按第 ④ 条独立判据（用户原话）判，其余一律放行。
        _state["tools"] = frozenset()
        _state["at"] = 0.0
    except Exception:      # noqa: silent-ok — 记不下来就当没有上下文（放行）
        pass


def _text_fresh():
    """这一轮的用户原话还在有效期里吗？"""
    t = str(_state.get("text") or "")
    return bool(t) and (time.time() - float(_state.get("text_at") or 0)) <= _TTL


def set_turn(names, user_text=""):
    """聊天这一轮开始装载工具时调用：记下"这一轮摆了哪些"。"""
    try:
        _state["tools"] = frozenset(str(x) for x in (names or []) if x)
        _state["text"] = str(user_text or "")
        _state["at"] = time.time()
        _state["text_at"] = time.time()
    except Exception:      # noqa: silent-ok — 记不下来就当没有上下文（放行）
        pass


def clear():
    _state.update({"tools": frozenset(), "text": "", "at": 0.0, "text_at": 0.0})


def current():
    """给界面/自检看的真实状态。"""
    fresh = bool(_state["tools"]) and (time.time() - float(_state["at"] or 0)) <= _TTL
    return {"loaded": sorted(_state["tools"]), "count": len(_state["tools"]),
            "fresh": fresh, "denied": int(_state["denied"])}


def _blocked_by_specialized(name, text):
    """按「用户这一轮原话」独立判一次：命中专用工具时，通用兜底不该被执行。

    判错、模块缺失、任何异常 → False（放行）。这道门的立场始终是"宁可放行，也不误杀能力"。
    """
    try:
        from core import tool_isolation as TI
        if str(name) not in TI.GENERIC:
            return False
        return bool(TI.specialized_for(str(text or "")))
    except Exception:      # noqa: silent-ok — 判不了就不额外限制
        return False


def check(name):
    """返回 (allowed, note)。note 只在拒绝时非空，且是给模型/用户看的中文。

    判序（这个顺序本身就是结论，改动前先读一遍上面那五条放行规则）：
      空名 → 放行；装载表过期 → 放行；用户亲口点名 → 放行；
      **命中专用工具的轮次里通用兜底 → 拒（④，不信记账表）**；
      装载了 → 放行；其余 → 拒（说清没装载、本轮可用、怎么才用得上）。
    """
    try:
        name = str(name or "")
        if not name:
            return True, ""
        loaded = _state["tools"]
        if loaded and (time.time() - float(_state["at"] or 0)) > _TTL:
            return True, ""                              # 已经不是"这一轮"了
        # 完全没有上下文（装载表没有、原话也没有）→ 真·后台任务，放行
        if not loaded and not _text_fresh():
            return True, ""
        if name and name in _state["text"]:             # ③ 用户亲口点名
            return True, ""
        # ④ 独立判据：命中专用工具时，通用兜底一律不放行。
        #    **排在"② 装载了"之前**是刻意的：万一某条规划路径把通用兜底又记进表里，
        #    那也不该变成放行的理由（记账错误不能抹掉隔离）。
        if _blocked_by_specialized(name, _state["text"]):
            _state["denied"] = int(_state["denied"]) + 1
            avail = sorted(loaded)
            if not loaded:      # 规划还没跑，这时说"没装载"更准确
                return False, ("⚠️ 这一轮要的是专用工具，通用兜底「%s」不参与"
                               "（还没装载任何通用检索）。要用它就直说「用 %s」。"
                               % (name, name))
            return False, ("⚠️ 这一轮没有装载「%s」（这一轮要的是专用工具，通用兜底不参与）。"
                           "本轮可用的是：%s。要用它就直说「用 %s」。"
                           % (name, "、".join(avail[:12]) or "（空）", name))
        if name in loaded:                              # ② 本轮装载了
            return True, ""
        if not loaded:
            # 装载表还没到（规划之前）：只要没命中专用工具，就不额外限制 ——
            # 这一层只用来挡"该用专用工具却去用通用兜底"，不是给整轮加锁。
            return True, ""
        _state["denied"] = int(_state["denied"]) + 1
        avail = sorted(loaded)
        return False, ("⚠️ 这一轮没有装载「%s」，所以不能调用它。本轮可用的是：%s。"
                       "如果确实需要它，直接跟我说「用 %s」，下一轮就会为你装上。"
                       % (name, "、".join(avail[:12]) or "（空）", name))
    except Exception:      # noqa: silent-ok — 门自己出错就放行，绝不把对话卡死
        return True, ""
