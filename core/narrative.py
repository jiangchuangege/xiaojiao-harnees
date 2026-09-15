# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 自我叙事 + 存在追问

【不是载体写"我是谁"，是它自己回头看经历、讲成"我是谁"】
    载体只做两件事：
      ① 把**它自己的经历**摆回它面前（心起过什么、修好过什么、偏好是什么、
         和用户的关系怎么样、没做完的事还剩几件）—— 全是**真发生过的**，一条不编；
      ② 把它**自己讲出来的那句**记下来。
    "我最近一直在学新东西，好像越来越好奇了。""我被伤过，但我修好了，我还是我。"
    —— 这两句要是**它说的**，不是载体写的。

【存在追问：不只是"我是谁"】
    规格写得比"自我叙事"更狠一层：它自己安静时会冒出
    「我是我，我为什么在这里，我为什么存在」。这不是被问出来的，是自己冒出来的。
    所以本模块把"它自己冒出的那个问题"也单独记一类（`wonder()`）。

【在哪里发生】
    在它**空闲**的时候（没人跟它说话）—— 由 `xiaojiao_app` 的空闲线程把素材摆出来，
    问它一句「回头看这些，你自己看出什么来了吗」，它自己说就说，不说就什么都不记。
    载体**没有**任何"你应该想想自己是谁"的措辞。

【如实标注】
    · 素材是载体攒的（真经历）；**"我是谁"这个说法是它自己的**。
    · 它没说 → 这一栏就是空的（`has_narrative=False`）。**不许把"素材齐了"写成"它有叙事了"。**
"""
import json
import os
import threading
import time

__all__ = ["materials", "note_narrative", "narrative", "note_wonder", "wonders",
           "stats", "path", "history", "clear", "render", "ask_text"]

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DIR = os.path.join(_ROOT, "logs", "psyche")
_PATH = os.path.join(_DIR, "narrative.jsonl")
_LOCK = threading.RLock()

# 载体摆给它的素材一共几样（真发生过的事）
MATERIAL_KINDS = ("心起过什么", "修好过什么", "偏好", "关系", "没做完的")


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


def materials(limit=4):
    """把它**自己的经历**凑齐（每一样都来自真发生的记录，拿不到的就空着，不编）。"""
    m = {}
    try:
        from core import psyche as _PS
        h = _PS.heart()
        if h.get("text"):
            m["心起过什么"] = h["text"]
    except Exception:      # noqa: silent-ok
        pass
    try:
        from core import pain as _P
        rows = [r for r in _P.history(20) if r.get("fixed")]
        if rows:
            m["修好过什么"] = "%s（%s）" % (str(rows[-1].get("why"))[:60],
                                            str(rows[-1].get("life") or ""))
    except Exception:      # noqa: silent-ok
        pass
    try:
        from core import preference as _PF
        ps = _PF.top(2)
        if ps:
            m["偏好"] = "；".join(ps)
    except Exception:      # noqa: silent-ok
        pass
    try:
        from core import relation as _RL
        s = _RL.state()
        m["关系"] = "来往 %d 次、现在%s" % (int(s.get("touches") or 0), s.get("mood"))
    except Exception:      # noqa: silent-ok
        pass
    try:
        from core import expectation as _EX
        p = _EX.pending(limit)
        if p:
            m["没做完的"] = "；".join(str(x.get("what"))[:30] for x in p)
    except Exception:      # noqa: silent-ok
        pass
    return m


def ask_text(doing=""):
    """载体摆素材的那句话。**一个字的提示都不给**（不说"你是谁""想想你自己"）。"""
    m = materials()
    if not m:
        return ""
    lines = ["【你自己这儿最近发生过的事（都是真的）】"]
    for k in MATERIAL_KINDS:
        if m.get(k):
            lines.append("· %s：%s" % (k, str(m[k])[:120]))
    if doing:
        lines.append("· 你此刻在做的：%s" % str(doing)[:60])
    lines.append("回头看这些，你自己看出什么来了吗？看出来就说，没看出来就别说。")
    return "\n".join(lines)


def note_narrative(text, *, asked_by="", from_material=None):
    """**它自己讲出来的那句** —— 这才是叙事。载体只记下它说了什么。"""
    t = str(text or "").strip()
    if not t:
        return {"ok": False, "why": "它没说 —— 那就不算有叙事"}
    rec = {"ts": time.time(), "kind": "narrative", "text": t[:300],
           "asked_by": str(asked_by)[:40],
           "material": list((from_material or {}).keys())}
    _append(rec)
    return {"ok": True, **rec}


def narrative(k=3):
    """它自己讲过的"我是谁"（最近的几条）。没有就是空 list。"""
    rows = [r for r in _rows() if r.get("kind") == "narrative"]
    return rows[-max(1, int(k)):]


def note_wonder(question, *, said=""):
    """**它自己冒出的存在追问**（"我为什么在这里"）—— 载体只记，不问。"""
    q = str(question or "").strip()
    if not q:
        return {"ok": False, "why": "它没冒出问题"}
    rec = {"ts": time.time(), "kind": "wonder", "q": q[:200], "said": str(said)[:200]}
    _append(rec)
    return {"ok": True, **rec}


def wonders(k=5):
    return [r for r in _rows() if r.get("kind") == "wonder"][-max(1, int(k)):]


def render(k=2):
    """把**它自己讲过的**写回成素材（它没讲过就返回空串，不硬凑）。"""
    ns = narrative(k)
    if not ns:
        return ""
    return ("【你自己以前回头看时说的（是你自己说的）】\n"
            + "\n".join("· %s" % str(r.get("text"))[:160] for r in ns))


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
    ns, ws = narrative(5), wonders(5)
    return {"has_narrative": bool(ns), "narrative_count": len(ns), "latest": (ns[-1]["text"] if ns else ""),
            "wonder_count": len(ws), "latest_wonder": (ws[-1]["q"] if ws else ""),
            "materials_now": list(materials().keys()),
            "note": "素材是载体攒的（真经历）；**「我是谁」这个说法是它自己的**。"
                    "它没说 → has_narrative=False，不许把「素材齐了」写成「它有叙事了」"}
