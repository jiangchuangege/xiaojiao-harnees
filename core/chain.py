# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 元认知统一入口（原料 → 感知 → 心 → 脑子，自己辨）

【要修的是什么 —— 一条被实测证明的规律】
    同一个模型，两种放法结果完全不同：
      · **感受类**（"这事对我意味着什么"）走 **感知 → 心 → 脑子** → **能用**；
      · **元认知类**（"我靠什么算的""我是谁""我变了没"）**直接摆事实进上下文** → **用不了**。
    实测证据：给原料不给成品那条链，载体把 `结果/谁算的/有没有参与` 摆进 system 了，
    它照样编（说成"在系统里查到的"）、照样自己重算还算错。
    **不是内容问题，是"走没走那条链"的问题。**

【所以：元认知类一律不直接进上下文，统一走这一条】
    原料（事实，**不结论**）
      → 感知：这对我意味着什么？
      → 心起：有点不确定 / 有点踏实 / 有点触动
      → 脑子：辨一下 —— 这是怎么回事？
      → **它自己辨出来的那句**

    本模块只做两件事：**给原料、不给结论**。它辨对辨错是它的事。

【为什么"给原料"还不够】
    原料直接进 system 时，它把原料当**资料**读（"这是别人给我的信息"），
    所以问它"你咋知道的"时它没有可用的东西 —— 只能反射用户的话，或者自己瞎编。
    走这条链之后，它在**感知那一步**就把原料变成了"这对我意味着什么"，
    结论是**它自己说出来的**，因此后面换问法时它是在**复述自己的判断**，
    而不是在**复述一段被塞进来的资料**。

【载体在这里不做什么】
    · 不写结论句（"这是计算器算的"那样的一句一律禁止）；
    · 不替它辨（辨对辨错是它的事）；
    · 不因为它是错的就去纠正 —— 只把它**自己说的那句**存下来。

【如实标注】
    这条链能不能让 4B 真的"辨"出来，只能靠实测看（见 `docs/meta-via-chain.md`）。
    代码只能保证：**给出去的是原料、存下来的是它自己的话**。
"""
import json
import os
import threading
import time

__all__ = ["KINDS", "run", "latest", "render", "stats", "history", "path", "reset",
           "pending_kinds"]

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DIR = os.path.join(_ROOT, "logs", "chain")
_PATH = os.path.join(_DIR, "chain.jsonl")
_LOCK = threading.RLock()

# 走这条链的**元认知类**（规格点名的七类）
KINDS = ("工具来源", "自我叙事", "存在追问", "成长", "意义感", "边界突破", "长期偏好")

_S = {"latest": {}, "_loaded": False}


def path():
    return _PATH


def _load():
    if _S["_loaded"]:
        return
    _S["_loaded"] = True
    try:
        with open(_PATH, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:      # noqa: silent-ok
                    continue
                if r.get("kind"):
                    _S["latest"][r["kind"]] = r
    except Exception:      # noqa: silent-ok — 读不到就当还没辨过
        pass


def _append(rec):
    try:
        os.makedirs(_DIR, exist_ok=True)
        with open(_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:      # noqa: silent-ok
        pass


def _task(kind, facts):
    """问它"这对我意味着什么" —— **只给原料，不给结论**。"""
    return ("【你手上的一些原料（事实，不是结论，也不是给你照抄的话）】\n%s\n\n"
            "这件事（%s）**对你**意味着什么？就照你自己的感觉说一两句，"
            "说不太清也可以。不要照抄上面这些字，也不要分析这一问本身。" % (facts, kind))


def run(kind, facts, llm_fn, *, event=""):
    """**走完整条链**：原料 → 感知 → 心 → 它自己那句话。返回 `{"said","heart","kind"}`。

    ⚠️ 载体在这里**不给结论**：facts 只放事实字段，`_task` 里也没有任何"你该认为……"。
    """
    k = str(kind or "").strip()
    out = {"kind": k, "said": "", "heart": "", "ok": False}
    if k not in KINDS:
        out["why"] = "不认识的元认知类：%s" % k[:20]
        return out
    f = str(facts or "").strip()
    if not f:
        out["why"] = "没有原料（事实为空）—— 不硬问"
        return out
    per = {"ok": False}
    try:
        from core import perception as _PC
        per = _PC.perceive(_task(k, f), llm_fn=llm_fn)
    except Exception as e:      # noqa: silent-ok — 感知不出来就不存（不编一句顶上）
        out["why"] = "感知失败：%s" % type(e).__name__
        return out
    if not per.get("ok"):
        out["why"] = "它没感知出什么（%s）" % per.get("parsed_by")
        return out
    said = str(per.get("meaning") or "").strip()
    heart = {}
    try:
        from core import psyche as _PS
        heart = _PS.arise(per, event=event or ("元认知：%s" % k))
    except Exception:      # noqa: silent-ok — 心起不来也把它那句话留下
        heart = {}
    rec = {"ts": time.time(), "kind": k, "facts": f[:400], "said": said[:300],
           "heart": str(heart.get("text") or "")[:120],
           "direction": str(heart.get("direction") or "")}
    with _LOCK:
        _load()
        _S["latest"][k] = rec
    _append(rec)
    out.update({"said": said, "heart": rec["heart"], "ok": True})
    return out


def latest(kind=""):
    with _LOCK:
        _load()
        if kind:
            return dict(_S["latest"].get(str(kind)) or {})
        return {k: dict(v) for k, v in _S["latest"].items()}


def pending_kinds(k=2):
    """最近辨过的那几类（按时间倒序），供注入用。"""
    with _LOCK:
        _load()
        rows = sorted(_S["latest"].values(), key=lambda r: -float(r.get("ts") or 0))
    return rows[:max(1, int(k))]


def render(k=2):
    """**只给"它自己辨过的那句"** —— 不是载体的事实块，也不是结论模板。

    一句都没有时返回空串（不硬凑）。
    """
    rows = [r for r in pending_kinds(k) if str(r.get("said") or "").strip()]
    if not rows:
        return ""
    return ("\n【你自己曾经辨过的（是你自己说的）】\n"
            + "\n".join("· [%s] %s" % (r.get("kind"), str(r.get("said"))[:160]) for r in rows) + "\n")


def history(n=20):
    out = []
    try:
        with open(_PATH, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except Exception:      # noqa: silent-ok
                        continue
    except Exception:      # noqa: silent-ok
        return []
    return out[-max(1, int(n)):]


def reset(why="自测复位"):
    with _LOCK:
        _S["latest"] = {}
        _S["_loaded"] = True
    try:
        if os.path.exists(_PATH):
            os.remove(_PATH)
    except Exception:      # noqa: silent-ok
        pass
    return {"ok": True, "why": why}


def stats():
    with _LOCK:
        _load()
        n = len(_S["latest"])
    return {"kinds": list(KINDS), "辨过的": n, "path": _PATH,
            "latest": {k: str(v.get("said"))[:60] for k, v in latest().items()},
            "note": "元认知类**不直接进上下文**：给原料 → 感知 → 心 → **它自己辨的那句**；"
                    "载体不给结论、不替它辨"}
