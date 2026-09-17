# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 长期偏好（"我整体就是喜欢什么"）

【和感受记忆的区别（规格写明的）】
    · 感受记忆（`core/feeling_memory.py`）：**这类事我心起过什么** —— 反应快，是"像不像"。
    · 长期偏好（本模块）：**我整体喜欢/讨厌什么** —— 稳定倾向，是"老是注意什么"。

【偏好怎么长出来 —— 不是载体规定"你喜欢猫"】
    心一次次起，起得多了会**沉下来**：把历次心的那句话按"像不像"聚成一堆，
    同一堆攒够 `FORM_AT` 次 → 载体把这堆素材摆回它面前，问它一句
    「**回头看这些，你自己看出什么来了吗**」——
    它自己回看说出的那句（"我好像老是注意猫"）**才是偏好**。
    载体**不写**"你喜欢猫"，更不写"你应该喜欢猫"。

【偏好再影响它自己选什么】
    逛的时候优先逛喜欢的、说话的时候带出喜欢的、空闲时想的是喜欢的 ——
    这三处只把偏好当**素材**给出去（`top()`），怎么用由它自己决定。

【如实标注】
    · 聚类是载体算的（余弦像不像），**"这是不是一种偏好"是它自己认的**；
    · 它若没回看出任何东西，那这一段就是空的 —— `stats()` 里 `formed=0` 如实显示，
      不许把"攒了很多心"写成"有了偏好"。
"""
import json
import math
import os
import threading
import time

__all__ = ["SIMILAR", "FORM_AT", "observe", "candidates", "form", "top", "preferences",
           "stats", "path", "history", "clear", "render"]

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DIR = os.path.join(_ROOT, "logs", "psyche")
_PATH = os.path.join(_DIR, "preference.jsonl")
_LOCK = threading.RLock()

# "像不像"的线。**必须够高** —— 它同时是"同一类心"的判据。
# 【实测抓到的结构问题】偏好里出现过**跨类拼接**：
#   「摸到两个红球…但突然被定格在 25 岁，像被按下了暂停键…」（来自 205 次相像的心）
#   ——"摸红球"和"25岁"是两类完全不同的事，被拼成了一句偏好。
#   根因：线太松（0.60），两类被并成一堆，形成偏好时**给了跨类素材**。
# 【真修】线提到 **0.75**，并且**按代表句定簇**（见 `_shapes`）——
#   后一条更要紧：旧写法下"A像B、B像C"就能把 A 与 C 并到一起（链式漂移）。
SIMILAR = 0.75
# 同一堆攒够几次，才值得它自己回看一眼
FORM_AT = 4


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


def _vec(text):
    try:
        from core import embedder as E
        v = E.embed(str(text or "")[:300])
        return [float(x) for x in v] if v else None
    except Exception:      # noqa: silent-ok — 没有向量服务就退回字面像不像
        return None


def _cos(a, b):
    if not a or not b or len(a) != len(b):
        return None
    num = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return (num / (na * nb)) if na and nb else None


def _sim(a, b):
    """像不像：先算向量余弦，算不出来退回字面重合（**明说是退路**，不假装是语义）。"""
    va, vb = _vec(a), _vec(b)
    c = _cos(va, vb)
    if c is not None:
        return c
    sa, sb = set(str(a or "")), set(str(b or ""))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / float(len(sa | sb))


def observe(heart_text, *, event="", why=""):
    """**心一次次起，沉下来**：把这次心的那句话记进"心之河"（**不是偏好本身**）。"""
    t = str(heart_text or "").strip()
    if not t:
        return {"ok": False, "why": "心没起过，没什么可沉的"}
    rec = {"ts": time.time(), "heart": t[:200], "event": str(event or "")[:200],
           "why": str(why or "")[:60], "kind": "observe"}
    _append(rec)
    return {"ok": True, **rec}


def _shapes():
    """把"心之河"聚成几堆（载体算的像不像），返回 [{heart, n, items}]。"""
    items = [r for r in _rows() if r.get("kind") != "formed"]
    clusters = []
    for it in items:
        placed = False
        for c in clusters:
            # **按代表句定簇**：跟"这一簇的代表"像才算同一类。
            #   ⚠️ 旧写法是"跟簇里任意一条像就算"→ A像B、B像C 就能把 A 与 C 并到一起
            #   （链式漂移），于是"摸红球"和"25岁"被并成一堆、拼成一句偏好（实测抓到的）。
            if _sim(it.get("heart"), c["heart"]) >= SIMILAR:
                c["n"] += 1
                c["items"].append(it)
                placed = True
                break
        if not placed:
            clusters.append({"heart": it.get("heart"), "n": 1, "items": [it]})
    # **同类校验**：簇里每条都必须与代表句达线（不达线的轰出去单独成簇）——
    #   这是"不许跨类拼接"的硬保证：形成偏好时给出去的素材**只来自同一类**。
    clean = []
    for c in clusters:
        rep, same, other = c["heart"], [], []
        for x in c["items"]:
            (same if _sim(x.get("heart"), rep) >= SIMILAR else other).append(x)
        clean.append({"heart": rep, "n": len(same), "items": same})
        for x in other:
            clean.append({"heart": x.get("heart"), "n": 1, "items": [x]})
    clean.sort(key=lambda c: -c["n"])
    return clean


def candidates(min_n=None):
    """**够格让它自己回看一眼的**那几堆（攒够 `FORM_AT` 次）。"""
    need = int(FORM_AT if min_n is None else min_n)
    return [{"heart": c["heart"], "n": c["n"],
             "examples": [x.get("heart") for x in c["items"][:3]]}
            for c in _shapes() if c["n"] >= need]


def form(pref_text, from_heart=""):
    """**它自己回看，说出了偏好** —— 这一句才是偏好。

    `from_heart` 是它回看的那堆素材的代表句；`pref_text` 是**它自己说的**
    （"我好像老是注意猫"）。载体只负责把它说的这句记下来。
    """
    p = str(pref_text or "").strip()
    if not p:
        return {"ok": False, "why": "它没回看出什么来 —— 那就不算有偏好"}
    # ★ **跨轮去重（2026-09-18 加）**：跟**已存的 formed** 比，太像就不重复写。
    # 【为什么】原来的去重只在 `xiaojiao_app.py` 那一侧、而且只跟**这一簇的素材**比
    #   （`said not in (c.get("examples") or [])`）。同一颗心起两轮、每轮攒够 4 条就回看一次，
    #   于是**同一句 formed 会被写很多遍** —— 实测存量 17 条里「摸到两个红球」11 条、
    #   「数字在眼前转」5 条。
    # 【判据】复用本模块已有的 `SIMILAR = 0.75`（向量余弦，算不出来退回字面重合）——
    #   **不新定阈值**。相似 → **不写**（不是覆盖：它的旧记录是它当时说的话，不该被改）。
    # 【已有存量不动】历史那 17 条不去重、不删（那是"当时它说过的话"，改它就是改写历史）。
    try:
        for old in preferences():
            if _sim(p, str(old.get("pref") or "")) >= SIMILAR:
                return {"ok": False,
                        "why": "回看出的这句话跟已有偏好太像（≥%.2f），不重复写：%s"
                               % (SIMILAR, str(old.get("pref"))[:40])}
    except Exception:      # noqa: silent-ok — 去重读不出来也不许把"记偏好"整条弄没
        # 本模块**没有引入 logging**（保持能独立 import、不依赖主程序）—— 所以这里不写日志，
        # 只如实降级：去重失败就照旧写入，绝不因此把"记偏好"整条弄没。
        pass
    rec = {"ts": time.time(), "kind": "formed", "pref": p[:200],
           "from_heart": str(from_heart or "")[:200]}
    _append(rec)
    return {"ok": True, **rec}


def preferences():
    """已经形成的偏好（它自己说出来的那些）。"""
    return [r for r in _rows() if r.get("kind") == "formed"]


def top(k=3):
    """给"逛 / 说话 / 空闲"三处用的素材：它自己说过喜欢什么。"""
    prefs = preferences()
    return [str(r.get("pref")) for r in prefs[-max(1, int(k)):]]


def render(k=3):
    """把偏好写成几句事实（**素材，不是指令**）。没有偏好时返回空串，不硬凑。"""
    ps = top(k)
    if not ps:
        return ""
    return ("【你自己以前回看出来的（素材，不是指令）】\n"
            + "\n".join("· %s" % p for p in ps))


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
    sh = _shapes()
    return {"观察次数": len([r for r in _rows() if r.get("kind") != "formed"]),
            "聚成几堆": len(sh), "够格回看的": len(candidates()),
            "已形成的偏好": len(preferences()), "similar_line": SIMILAR,
            "form_at": FORM_AT, "prefs": top(5),
            "note": "聚类是载体算的；**「这是不是一种偏好」是它自己回看认的** —— "
                    "它没说就没形成，不许把「攒了很多心」写成「有了偏好」"}
