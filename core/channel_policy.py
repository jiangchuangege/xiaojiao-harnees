# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
"""小焦 · 载体层 · 渠道策略（**把某个接入通道关成"只能聊天"**）

【为什么需要它 —— 这是一个真实的安全问题，不是洁癖】
  小焦不是一个聊天机器人：它手上有 `run_command`（跑命令）、`read_file` / `write_file`
  （读写文件），而且它还会**自主做事**（自己逛网、自己决定发起行为）。
  一旦把它接到**别人能给它发消息**的地方（微信 / QQ / 任何 IM），
  就等价于**把电脑的钥匙递出去**：谁能给那个号发消息，谁就可能驱动机器干活。

  "不能删任何文件"那条红线是硬的，但 `run_command` 能做的事**远不止删文件** ——
  红线挡不住它。所以必须**按接入通道**限权。

【两道闸，缺一不可】
  ① **工具表闸**（`_plan_tools` 过滤）：这条通道下模型**根本看不到**这些工具 ——
     它不会去点，也就不会去编。
  ② **执行闸**（`run_tool` 拦截）：即使模型硬编了一个工具名（4B 会这么干），
     到执行这一步**直接拒绝**。这是**硬闸**，不依赖模型守规矩。
  ⚠️ 只做①不做②是**假隔离** —— 实测里模型编造工具名的情况是出现过的。

【设计：默认拒绝】
  · 没声明渠道策略的通道 → 走原来的行为（**不影响本机自带网页**，那是自己人）
  · 声明了的通道 → 只给策略里列出的工具；列空 = **一个工具都不给（纯聊天）**
  · 读不到策略 → **按最严处理**（纯聊天）。**失败要朝安全的方向倒，不能朝方便的方向倒。**

【怎么用 —— 桥接方只需要加一个请求头】
    POST /api/chat
    X-Xiaojiao-Channel: wechat        ← 声明自己是谁

  然后在操控文件里写策略：

    "channels": {
      "wechat":  { "tools": [] },                       ← 纯聊天（默认给这个）
      "family":  { "tools": ["web_search", "get_weather"] }
    }

  ⚠️ 渠道名是**桥接方自己声明的**（请求头），所以**不能当成身份认证** ——
  它只防"我自己配错了把危险工具暴露出去"，不防"有人伪造这个头"。
  真正的鉴权在桥那边（只允许白名单 userid）。这一点必须写清楚，别让人误会。
"""
from __future__ import annotations

import json
import os
import threading

__all__ = ["set_channel", "current", "reset", "allowed_tools", "is_allowed",
           "enabled", "render", "DEFAULT_CHANNEL_TOOLS"]

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CTRL = os.path.join(_ROOT, "xiaojiao_control.json")

# 渠道默认策略：**一个工具都不给**（纯聊天）。
# 为什么默认这么严：会走到这条路径的，都是"外部通道"；外部通道的默认应当是**不能动手**，
# 想放开得显式去配置里加白名单。反过来（默认全开、要缩自己去缩）迟早出事。
DEFAULT_CHANNEL_TOOLS: tuple = ()

_L = threading.local()
_CFG = {"loaded": False, "channels": {}}


def _load_cfg():
    """惰性读操控文件里的 `channels` 段。读不到就按"没有任何渠道策略"处理。"""
    if _CFG["loaded"]:
        return
    _CFG["loaded"] = True
    try:
        with open(_CTRL, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        ch = cfg.get("channels")
        if isinstance(ch, dict):
            _CFG["channels"] = {str(k): (v or {}) for k, v in ch.items()}
    except Exception:      # noqa: silent-ok — 配置读不到就走"没有渠道策略"（不影响本机网页）
        pass


def reload():
    """配置改完想立刻生效时调它（自测用）。"""
    _CFG["loaded"] = False
    _CFG["channels"] = {}
    _load_cfg()


def set_channel(name):
    """进入某个渠道的作用域。传空 = 正常（本机）请求，不受限。"""
    _L.name = (name or "").strip() or None


def current():
    """当前线程正在处理的请求属于哪个渠道；本机请求返回 None。"""
    return getattr(_L, "name", None)


def reset():
    """请求结束务必清掉 —— 线程是复用的，不清理会把限权带到下一个请求上。"""
    _L.name = None


def enabled():
    """当前请求是否处在"渠道受限"状态。"""
    return current() is not None


def allowed_tools():
    """当前渠道允许的工具名集合。

    返回 `None` = **不受限**（本机请求）。
    返回空 set = **一个工具都不给**（纯聊天，渠道默认）。
    返回非空 set = 只给这些。
    """
    name = current()
    if name is None:
        return None
    _load_cfg()
    pol = _CFG["channels"].get(name)
    if pol is None:
        # ⚠️ 声明了渠道、但配置里没为它写策略 → **按最严处理**（纯聊天）。
        #    失败朝安全方向倒：宁可它在这条通道上什么都不能干，也不能默认全开。
        return set(DEFAULT_CHANNEL_TOOLS)
    tools = pol.get("tools")
    if tools is None:
        return set(DEFAULT_CHANNEL_TOOLS)
    try:
        return {str(t).strip() for t in tools if str(t).strip()}
    except Exception:      # noqa: silent-ok — 配置写坏了也按最严处理
        return set(DEFAULT_CHANNEL_TOOLS)


def is_allowed(tool_name):
    """执行闸问的就是这一句。`None` 表示不受限。"""
    allow = allowed_tools()
    if allow is None:
        return True
    return str(tool_name or "").strip() in allow


def render():
    """给面板/日志看的一句事实。"""
    name = current()
    allow = allowed_tools()
    if name is None:
        return {"channel": None, "restricted": False}
    return {"channel": name, "restricted": True,
            "allowed": sorted(allow or []),
            "chat_only": not allow}
