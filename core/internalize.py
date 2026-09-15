# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 学习闭环（内化缓存）

【这段为什么这么设计】
    同一个问题问第二次时，载体不该再去干一遍同样的事。
    「第一次问数学题 → 走计算器 → 内化；第二次同类 → 模型自己答」——
    这里的"内化"是**载体把上次的确定性结论记下来，第二次直接复用**，
    并且把它当成**可复用的知识**交给模型，而不是让模型重新推一遍。

    三层记录各有分工（都落在 `logs/learning.jsonl`，一行一条）：
      · kind=tool_result  某类问题走了哪个工具、结论是什么（可复用的确定性结论）
      · kind=route        某类问题走哪条路（下次直接走，不必重新判断）
      · kind=feedback     用户对某次回答的反馈（点赞/纠正）

【去掉会怎样】
    每次都要重新走一遍完整流程：问算术题每次都调计算器、都要多一次往返。
    用户感觉不到"它记住了这道题怎么处理" —— 而"越用越顺"正是载体的核心卖点之一。

【边界：只内化确定性结论】
    模型生成的自然语言答案**不进这个缓存** —— 那是概率性的，复用它等于把上次的
    随机输出当成事实。只有"载体算出来的 / 工具拿回来的"确定性结论才内化。
"""
import json
import os
import re
import threading
import time

__all__ = ["log_path", "record", "lookup_route", "remember_result", "find_result",
           "stats", "internalized_answer"]

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PATH = os.path.join(_ROOT, "logs", "learning.jsonl")
_LOCK = threading.Lock()

# 归一化：去掉标点与空白，只留字与数字（用于"同类问题"的判据）
_NORM = re.compile(r"[\s，。！？、；：,.!?;:'\"“”‘’（）()\[\]【】]")


def log_path():
    return _PATH


def norm_q(text):
    """把问题归一化成"同类"的判据：去标点、去空白、转小写。"""
    return _NORM.sub("", str(text or "").lower())


def record(kind, **kw):
    """写一条学习记录。返回这条记录（写不进去也返回，只是没落盘）。"""
    rec = {"ts": time.time(), "kind": str(kind)}
    rec.update(kw)
    try:
        os.makedirs(os.path.dirname(_PATH), exist_ok=True)
        with _LOCK:
            with open(_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:      # noqa: silent-ok — 记不上只影响"越用越顺"，绝不影响这一轮回答
        pass
    return rec


def _rows():
    out = []
    if not os.path.exists(_PATH):
        return out
    try:
        with open(_PATH, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:      # noqa: silent-ok — 坏行跳过
                    continue
    except Exception:      # noqa: silent-ok — 读不到就当没记录
        return []
    return out


def remember_result(question, result, **kw):
    """内化一条**确定性结论**（算式结果 / 工具结论）。"""
    return record("tool_result", q=norm_q(question), q_raw=str(question)[:200],
                  result=str(result)[:2000], **kw)


def find_result(question):
    """找同一道题的旧结论（归一化后完全相同才算"同类"）。没有返回 None。"""
    q = norm_q(question)
    if not q:
        return None
    hit = None
    for r in _rows():
        if r.get("kind") == "tool_result" and r.get("q") == q:
            hit = r            # 取最后一条（最新的结论优先）
    return hit


def lookup_route(question):
    """这类问题以前走的是哪条路。返回 route 字符串或 None。"""
    q = norm_q(question)
    if not q:
        return None
    hit = None
    for r in _rows():
        if r.get("kind") == "route" and r.get("q") == q:
            hit = r.get("route")
    return hit


def internalized_answer(question):
    """第二次问同一个确定性问题时，直接复用上次的结论。

    返回可注入的文本（没有就返回空串）。**这条链就是"第二次不用再走工具"的实现。**
    """
    hit = find_result(question)
    if not hit:
        return ""
    return hit.get("result") or ""


def stats():
    rows = _rows()
    by = {}
    for r in rows:
        by[r.get("kind", "?")] = by.get(r.get("kind", "?"), 0) + 1
    return {"total": len(rows), "by_kind": by, "path": _PATH}
