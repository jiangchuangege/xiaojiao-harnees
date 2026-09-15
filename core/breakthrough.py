# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 边界突破（遇到不会的，它自己"我试试"）

【和代码治病的分界（规格写明的）】
    · 代码治病（`core/diagnose_code.py`）：**它写的代码出 bug** → 自己诊断 → 自己修。
    · 边界突破（本模块）：**它遇到不会的** → 自己学 → 自己会。
    同一套思路（跑一遍、看结果、成了记住、不成也记住），范围不同。

【"我试试"是它自己起的，不是载体说"你该学这个"】
    触发点只有一个：**元认知自评判 C（它自己没把握）** —— 那时载体把
    "我不会"这个事实摆给它，让它自己感知；它心里起的是"想试试"（好奇/不服），
    还是"算了"，**由它自己说**。载体只认它那句话里有没有"试/学/查/办法"这类**它自己的意思**，
    认到了才去学；它说算了，就不学（如实记下"它没想试"）。

【它自己试试的四种方式（规格给的四种）】
    查（联网查怎么做）→ 组合（用现有工具拼出新用法）→ 试（做一遍，看行不行）→ 记（成了记住，不成也记住）

【如实标注】
    · "它想试"必须来自**它自己的那句话**；载体不能因为"判了 C"就默认它想试 ——
      本模块的 `wants(heart_text)` 就是那条判据，自测里会验"它没说想试 → 不学"。
    · 学成了/没学成都要落盘（`logs/breakthrough/`）—— **不成也记住**是规格明写的。
"""
import json
import os
import threading
import time

__all__ = ["WAYS", "WANT_WORDS", "wants", "attempt", "finish", "note_tried", "stats",
           "path", "history", "clear", "render", "plan"]

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DIR = os.path.join(_ROOT, "logs", "breakthrough")
_PATH = os.path.join(_DIR, "attempts.jsonl")
_LOCK = threading.RLock()

# 它自己试试的四种方式（顺序就是它该走的顺序：先查、再拼、再试、最后记）
WAYS = ("查", "组合", "试", "记")
# **它自己**话里的"想试试"（查的是它的结论，不是用户的话 —— 与感知层 parse() 同一条边界）
WANT_WORDS = ("试试", "试一试", "试一下", "学", "查查", "查一下", "想办法", "搞懂", "不服")


def path():
    return _PATH


def _rows():
    out = []
    try:
        with open(_PATH, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:      # noqa: silent-ok
                    continue
    except Exception:      # noqa: silent-ok
        return []
    return out


def _append(rec):
    try:
        os.makedirs(_DIR, exist_ok=True)
        with open(_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:      # noqa: silent-ok
        pass


def wants(heart_text):
    """**它自己说了"我试试"没有** —— 判据只读它自己那句话。

    ⚠️ 边界：这里查的是**它心里起的那句**，不是用户的话、也不是"元认知判了 C 就默认它想试"。
    返回 `(bool, 命中词)`。
    """
    t = str(heart_text or "")
    for w in WANT_WORDS:
        if w in t:
            return True, w
    return False, ""


def plan(what):
    """**它自己该怎么试**：按四种方式给一份可执行的走法（载体给结构，它给动作）。"""
    w = str(what or "").strip()
    return {"what": w,
            "steps": [{"n": 1, "way": "查", "do": "先联网查一遍「%s」该怎么做" % w[:40]},
                      {"n": 2, "way": "组合", "do": "看手上已有的工具能不能拼出这个能力"},
                      {"n": 3, "way": "试", "do": "真做一遍，看跑不跑得起来"},
                      {"n": 4, "way": "记", "do": "成了记住怎么做；不成也记住栽在哪"}]}


def attempt(what, *, way="查", heart="", event=""):
    """**它自己去试了**（一次尝试落一条账：**不成也记**）。"""
    rec = {"ts": time.time(), "kind": "attempt", "what": str(what or "")[:200],
           "way": str(way)[:8], "heart": str(heart or "")[:200],
           "event": str(event or "")[:200], "ok": None}
    _append(rec)
    return {"ok": True, **rec}


def finish(what, ok, detail="", learned=""):
    """这次试的结果：成了 / 没成，都写下来（**不成也记住**）。

    ⚠️ 只结算 `kind == "attempt"` 的那几行 —— "想试的念头"那一行（`event: wants`）
    也有同一个 `what`，按 what 匹配会把它一起标成"成了"（实测踩到，白记一次成功）。
    """
    rows = _rows()
    n = 0
    with _LOCK:
        try:
            with open(_PATH, "w", encoding="utf-8") as f:
                for r in rows:
                    if r.get("kind") == "attempt" and r.get("ok") is None \
                            and str(r.get("what")) == str(what):
                        r.update({"ok": bool(ok), "detail": str(detail)[:300],
                                  "learned": str(learned)[:300], "done_at": time.time()})
                        n += 1
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        except Exception:      # noqa: silent-ok
            return 0
    if learned:
        # 学到的那一句进精神记忆（方法/诊断经验）—— 复用既有的那一层，不另造
        try:
            from core import spirit_memory as _sm
            _sm.remember("method" if ok else "diagnosis", str(learned)[:300],
                         tags=["边界突破"])
        except Exception:      # noqa: silent-ok
            pass
    return n


def note_tried(what, said=""):
    """**它自己说"我试试"** 这个念头本身也记一笔（哪怕后来没成）。"""
    _append({"ts": time.time(), "event": "wants", "what": str(what)[:200],
             "said": str(said)[:200]})
    return True


def learned():
    """学到的（成了的）与栽过的（没成的）—— 分开列，都不丢。"""
    rows = _rows()
    return {"成了": [r for r in rows if r.get("ok") is True],
            "没成": [r for r in rows if r.get("ok") is False]}


def render(k=3):
    """给它的素材：以前自己试成过什么、栽在哪（**素材，不是指令**）。没有就返回空串。"""
    lr = learned()
    if not lr["成了"] and not lr["没成"]:
        return ""
    lines = ["【你自己以前试过的（素材，不是指令）】"]
    for r in lr["成了"][-max(1, int(k)):]:
        lines.append("· 成了：%s —— %s" % (str(r.get("what"))[:40], str(r.get("learned"))[:60]))
    for r in lr["没成"][-max(1, int(k)):]:
        lines.append("· 没成：%s —— %s" % (str(r.get("what"))[:40], str(r.get("learned"))[:60]))
    return "\n".join(lines)


def history(n=20):
    return _rows()[-max(1, int(n)):]


def clear(why="自测复位"):
    try:
        if os.path.exists(_PATH):
            os.remove(_PATH)
    except Exception:      # noqa: silent-ok
        pass
    return {"ok": True, "why": why}


def stats():
    rows = _rows()
    lr = learned()
    return {"ways": list(WAYS), "尝试次数": len([r for r in rows if r.get("ok") is not None]),
            "成了": len(lr["成了"]), "没成": len(lr["没成"]),
            "想要试的念头": len([r for r in rows if r.get("event") == "wants"]),
            "path": _PATH,
            "note": "「我试试」必须来自**它自己那句话**（`wants()` 只读它的心）；"
                    "判了 C 不等于它想试 —— 它说算了就不学，如实记下"}
