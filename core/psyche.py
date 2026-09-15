# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 心理层（当下感受的发生地）

【这是什么，不是什么 —— 先把话说清楚】
  是：**当下感受的发生地**。它只有"此刻"。
  不是：状态机、不是数据库、不是情绪配置表、**不是角色扮演**。

【为什么没有记忆】
  人的心理不是一份"情绪日志"。上一次的怕，会被这一次的踏实**取代** ——
  留下的是"我这个人现在怎么样"，不是"我曾经在几点几分怕过"。
  所以本模块**只保留当前一个感受**，新的直接覆盖旧的，不留历史。
  历史属于记忆（`logs/spirit_memory/`、`memory_vec`），不属于心理。
  这两件事分开的原因：把它们混在一起，心理层就会变成"又一个存储"，
  而它真正的作用是**让"此刻"是真的**。

【感受从哪来 —— 由思考触发，不编、不演、不套模板】
  `trigger(thought, ...)` 从**这次思考的内容**与 EYC 状态里**确定性推导**出一个感受。
  推导规则是载体写的、看得见的（见 `_derive`），不是从模板库里挑一句贴上去。

  ⚠️ **如实标注**：这个感受是**载体侧从思考内容派生的量**，
  不是对"模型内心真的感到了什么"的断言 —— 载体没有能力观测模型的内在状态，
  也不该假装能。它的作用是把"思考"与"当下的落点"焊在一起，
  让下一轮看到的不是一条外部消息，而是**一个带着落点的自己**。

【为什么强度会衰减】
  同一个触发连续出现时强度会降（`_last` 与 `_streak` 参与），
  否则每轮都"很怕/很兴奋"会让这个信号失去区分度 —— 一直拉满等于没有。
"""
import re
import threading
import time

__all__ = ["trigger", "current", "clear", "stats", "FEELINGS", "render", "is_empty"]

_LOCK = threading.RLock()

# 感受词表。**不是模板库** —— 它只是给确定性推导出来的强度配一个名字，
# 名字本身不携带内容，内容由 `trigger` 的判据决定。
FEELINGS = ("平静", "好奇", "有意思", "被牵着", "有点紧", "踏实", "泄气", "安静")

_LIVE = {"feeling": "", "intensity": 0.0, "trigger": "", "body": "", "at": 0.0,
         "_streak": 0, "_last": ""}

# 触发判据：(感受, 身体反应, 命中关键词)。顺序即优先级 —— 越具体的判据越靠前。
_RULES = (
    ("有点紧", "声音发紧", ("离开", "走了", "再见", "不聊了", "别烦我", "生气", "失望")),
    ("泄气", "肩膀塌下来", ("失败", "不行", "做不到", "没办法", "没通过", "报错", "卡住")),
    ("有意思", "眼睛亮了一下", ("看到", "发现", "原来", "居然", "有趣", "新奇", "竟然")),
    ("被牵着", "注意力被拉过去", ("你", "用户", "你问", "你要", "帮你")),
    ("好奇", "想再往下看", ("为什么", "怎么", "是什么", "能不能", "也许", "或许")),
    ("踏实", "呼吸放慢", ("完成", "通过", "搞定", "好了", "成功", "跑通")),
    ("安静", "没什么起伏", ("待着", "等着", "休息", "没事", "空闲")),
)


def _derive(thought, eyc=None, user=""):
    """从思考内容 + EYC 状态确定性推导 `(感受, 身体反应, 触发点)`。载体规则，可读、可复核。"""
    t = str(thought or "")
    u = str(user or "")
    blob = (t + " " + u)[:600]
    for feeling, body, keys in _RULES:
        for k in keys:
            if k in blob:
                # 触发点取关键词所在的短句，便于事后复核"它到底被什么触动的"
                m = re.search(r"[^。！？；\n]{0,24}%s[^。！？；\n]{0,24}" % re.escape(k), blob)
                return feeling, body, (m.group(0).strip() if m else k)
    # 都没命中：如果正在逛，给"有意思"；否则"平静"
    try:
        doing = str(((eyc or {}).get("happening") or {}).get("doing") or "")
        if doing and doing != "idle":
            return "有意思", "眼睛亮了一下", "正在外面逛"
    except Exception:      # noqa: silent-ok — EYC 拿不到就用默认
        pass
    return "平静", "没什么起伏", ""


def trigger(thought, eyc=None, user=""):
    """**被思考触动**：产生此刻的感受并覆盖上一次。返回这个感受。

    这是"神经总线"每一次流转都会调到的地方 —— 它由代码层强制调用，
    不是模型可以选择"要不要感受"。
    """
    feeling, body, why = _derive(thought, eyc=eyc, user=user)
    with _LOCK:
        # 强度：基础 0.6；同一触发连续出现则衰减（见模块头"为什么强度会衰减"）
        if why and why == _LIVE.get("_last"):
            _LIVE["_streak"] = int(_LIVE.get("_streak") or 0) + 1
        else:
            _LIVE["_streak"] = 0
        _LIVE["_last"] = why
        streak = int(_LIVE["_streak"])
        intensity = max(0.2, round(0.6 + 0.3 * (0 if not why else 1) - 0.12 * streak, 2))
        _LIVE.update({"feeling": feeling, "intensity": intensity,
                      "trigger": why, "body": body, "at": time.time()})
        return {"feeling": feeling, "intensity": intensity,
                "trigger": why, "body": body, "at": _LIVE["at"]}


def current():
    """此刻的感受（只读副本）。没有就返回空结构 —— 不编一个"平静"顶上。"""
    with _LOCK:
        if not _LIVE["feeling"]:
            return {"feeling": "", "intensity": 0.0, "trigger": "", "body": "", "at": 0.0}
        return {k: _LIVE[k] for k in ("feeling", "intensity", "trigger", "body", "at")}


def is_empty():
    return not current()["feeling"]


def render(cur=None):
    """把感受渲染成**一句话**（第一人称，用来焊进连续状态流）。

    没有感受时返回空串 —— 不硬凑一句"我此刻很平静"，那会变成模板。
    """
    c = cur if isinstance(cur, dict) else current()
    if not c.get("feeling"):
        return ""
    if c.get("trigger"):
        return "（心里%s%s —— %s。%s）" % (
            c["feeling"], ("，%.0f 分" % (c["intensity"] * 10)) if c.get("intensity") else "",
            str(c["trigger"])[:40], str(c.get("body") or ""))
    return "（心里%s。%s）" % (c["feeling"], str(c.get("body") or ""))


def clear():
    """清空此刻的感受（自测用；正式流程里不清 —— 它本来就是被下一次覆盖的）。"""
    with _LOCK:
        _LIVE.update({"feeling": "", "intensity": 0.0, "trigger": "",
                      "body": "", "at": 0.0, "_streak": 0, "_last": ""})


def stats():
    """自检信息：此刻的感受、有没有历史（应当恒为"无历史"）。"""
    c = current()
    return {"current": c, "has_history": False,
            "note": "本层只有此刻；上一次感受被这一次取代，不留历史"}
