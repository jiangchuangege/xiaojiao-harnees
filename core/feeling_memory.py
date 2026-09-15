# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 心的累积（"一朝被蛇咬，十年怕井绳"）

【这不是一张表】
  它不是"事件 → 感受"的对照表。它记的是**印象**：
      "上次那种事，我心紧过。"
  下次再遇到**类似**的，心**起得更快**（强度起点更高、认出来"这我经历过"）。

【为什么用"像不像"而不是"是不是同一类"】
  "同类"要靠分类，而分类就是表 —— 一写表，心就退回成查表机器。
  所以这里只用**像不像**：把印象与这次的事各取一个向量，算余弦；
  够像就算"这我经历过"。像不像是个程度问题，不是归类问题。

【和记忆层的分工】
  · 记忆层（`spirit_memory` / `memory_vec`）记的是**事实与知识**：发生过什么、学到什么。
  · 本层记的是**心自己起过什么**：没有事实、没有答案，只有"那次我心是什么样"。
  两者不混 —— 混在一起，心就又变成"又一个存储"。

【掉电会怎样】
  印象存在盘上（`logs/psyche/impressions.jsonl`）。文件不在，心就只是"第一次遇见"，
  不会起得更快 —— 但**心照样会起**（那是 `psyche.arise` 的事，不依赖本层）。
"""
import json
import os
import threading
import time

__all__ = ["remember", "similar", "impression_of", "stats", "path", "clear", "MAX_ROWS"]

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PATH = os.path.join(_ROOT, "logs", "psyche", "impressions.jsonl")
_LOCK = threading.RLock()
MAX_ROWS = 2000
# "够像就算经历过"的门槛。**这是"像不像"的线，不是分类线** ——
# 低于它只是"没认出来"，不影响心这一次照样起。
FAMILIAR = 0.72


def path():
    return _PATH


def _vec(text):
    try:
        from core import embedder as E
        v = E.embed(str(text or "")[:400])
        return [round(float(x), 4) for x in v] if v else None
    except Exception:      # noqa: silent-ok — 向量服务不可用就退回"没认出来"
        return None


def _cos(a, b):
    if not a or not b or len(a) != len(b):
        return None
    num = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return (num / (na * nb)) if na and nb else None


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
    except Exception:      # noqa: silent-ok — 读不到就当还没经历过
        return []
    return out


def remember(event, feeling, intensity=0.0, source=""):
    """记一条**印象**：这件事发生时，心是什么样。**只追加，不改写。**"""
    rec = {"ts": time.time(), "event": str(event or "")[:300],
           "feeling": str(feeling or "")[:200], "intensity": float(intensity or 0.0),
           "source": str(source or "")[:40]}
    v = _vec(rec["event"])
    if v:
        rec["vec"] = v
    try:
        os.makedirs(os.path.dirname(_PATH), exist_ok=True)
        with _LOCK:
            with open(_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:      # noqa: silent-ok — 记不上只是"下次不会起得更快"
        pass
    return rec


def similar(event, threshold=FAMILIAR):
    """这件事**像不像**我经历过的某一次。返回 `(印象, 相似度)`；没认出来返回 `(None, None)`。

    只做一件事：**认出来**。它不决定心起什么 —— 那是 `psyche.arise` 的事。
    """
    t = str(event or "")
    if not t.strip():
        return None, None
    tv = _vec(t)
    if not tv:
        return None, None
    best, bs = None, None
    for r in _rows():
        s = _cos(tv, r.get("vec"))
        if s is None:
            continue
        if bs is None or s > bs:
            best, bs = r, s
    if best is not None and bs is not None and bs >= float(threshold):
        return best, round(bs, 4)
    return None, (round(bs, 4) if bs is not None else None)


def impression_of(event, threshold=FAMILIAR):
    """这次像不像经历过 → 给一句人话（供日志与 `psyche.arise` 的"起得更快"用）。"""
    r, s = similar(event, threshold=threshold)
    if not r:
        return {"familiar": False, "sim": s, "feel": "", "note": "没见过这种，第一次"}
    return {"familiar": True, "sim": s, "feel": str(r.get("feeling") or "")[:80],
            "note": "像以前那次（%.2f）：%s" % (s, str(r.get("feeling") or "")[:40])}


def clear():
    """清空印象（自测用）。正式流程里从不调用 —— 印象是攒出来的。"""
    try:
        if os.path.exists(_PATH):
            os.remove(_PATH)
    except Exception:      # noqa: silent-ok
        pass


def stats():
    rows = _rows()
    return {"count": len(rows), "path": _PATH, "familiar_line": FAMILIAR,
            "recent": [{"feeling": str(r.get("feeling") or "")[:30],
                        "event": str(r.get("event") or "")[:40]} for r in rows[-3:]],
            "note": "记的是印象（心起过什么），不是清单；用「像不像」而不是「是不是同类」"}
