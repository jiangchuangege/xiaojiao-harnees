# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 原料（给原料，不给成品）

【要修的是什么 —— 一次实测】
    用户问「100000乘以100000呢」→ 它答「100000 * 100000 = 10000000000」。
    用户再问「你咋知道的」→ 它答「你问『你咋知道的』？……我记你说过：『你咋知道的』——
    你当时问的，是『你咋知道的』啊。」

    **它在原样反射用户的话，没回答。** 根因不在模型笨：
    它只拿到了**结果**，没拿到**这结果怎么来的** ——
    它不知道自己靠什么算的，所以被问"怎么知道的"时手里没信息，只能抓着用户那句话打转。

【改法：给原料，不给成品】
    ❌ 死模板：载体写一句完整的话（"这是计算器算的"）→ 它照搬 → **换种问法就崩**。
    ✅ 给原料：结果 + 谁产的 + 它有没有参与 + 怎么来的 → **它自己推、自己组织、自己说**。

    `render()` 给出去的是**一条一条的事实字段**，不是一句能照抄的话 ——
    这是"原料"和"成品"在代码上的分界线。

【它拿到原料后要自己推的四步（规格给的）】
    ① 这个结果是谁产生的？→ 不是我，我没算过
    ② 我为什么不知道过程？→ 因为它是被塞给我的，我没参与
    ③ 用户问的是什么？→ （不同问法问的是不同的事）
    ④ 把这些推出来的，组织成话 —— **不背那一句**

【判据：换种问法它还能推出来】
    「你咋知道的」「你自己算的？」「这数对吗」—— 三种问法，三种组织。
    因为它每次是**推**，不是**背**。这一条只能靠实测看（见 `docs/raw-material.md`）。

【为什么台账要跨轮留着】
    用户问"你咋知道的"时，那一轮**没有**任何计算 —— 如果原料只活在算完的那一轮，
    它下一轮手里就又是空的。所以原料记进台账，后面几轮继续摆在它面前。

【和已有规矩一致】
    · 「记忆是素材不是答案」→ 这里：**结果是原料不是回答**；
    · 「心由模型感知产生、不由载体写」→ 这里：**话由模型组织，不由载体写**；
    · 「感知层不查表」→ 这里：**不给它成品句子**。
    统一原则：**载体给原料，模型自己推、自己组织、自己说。**
"""
import json
import os
import threading
import time

__all__ = ["FIELDS", "record", "recent", "render", "render_item", "stats", "path",
           "history", "clear", "MAX_KEEP", "SOURCE_CALC"]

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DIR = os.path.join(_ROOT, "logs", "raw")
_PATH = os.path.join(_DIR, "material.jsonl")
_LOCK = threading.RLock()

# 一条原料由这几个字段构成（**一条都不能少** —— 少了哪个，它就推不出那一角）
FIELDS = ("result", "source", "took_part", "raw", "who_asked", "how")
# 台账在内存里留几条（跨轮读的就是这几条）
MAX_KEEP = 6
# 载体自己的计算器（直算，不经过模型）
SOURCE_CALC = "载体的计算器"

_STATE = {"items": [], "_loaded": False}


def path():
    return _PATH


def _load():
    if _STATE["_loaded"]:
        return
    _STATE["_loaded"] = True
    try:
        with open(_PATH, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    _STATE["items"].append(json.loads(line))
                except Exception:      # noqa: silent-ok — 坏行跳过
                    continue
    except Exception:      # noqa: silent-ok — 读不到就从空台账开始
        pass
    del _STATE["items"][:-MAX_KEEP]


def _append(rec):
    try:
        os.makedirs(_DIR, exist_ok=True)
        with open(_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:      # noqa: silent-ok — 记不上台账不影响这一轮的答案
        pass


def record(result, source, took_part=False, raw="", who_asked="载体", how="", kind=""):
    """**记一条原料**：结果 + 谁产的 + 它有没有参与 + 怎么来的。

    `took_part` 是"**这一步的执行它有没有参与**"：
      · 载体直算、工具跑出来的 → `False`（它没算过，结果是被塞给它的）；
      · 它自己写的代码跑出来的 → `True`（那一步是它做的）。
    这一栏不许含糊：把它写成 True 就是**把"塞给它"说成"它自己算的"**。
    """
    rec = {"ts": round(time.time(), 3), "result": str(result or "")[:200],
           "source": str(source or "")[:60], "took_part": bool(took_part),
           "raw": str(raw or "")[:300], "who_asked": str(who_asked or "载体")[:20],
           "how": str(how or "")[:200], "kind": str(kind or "")[:20]}
    with _LOCK:
        _load()
        _STATE["items"].append(rec)
        del _STATE["items"][:-MAX_KEEP]
    _append(rec)
    return rec


def recent(n=3):
    """最近几条原料（跨轮还留着 —— 用户问"你咋知道的"时靠的就是这几条）。"""
    with _LOCK:
        _load()
        return list(_STATE["items"][-max(1, int(n)):])


def render_item(rec):
    """**一条原料**写成字段（不是一句话）—— 它自己推、自己组织。"""
    r = rec or {}
    took = "没有 —— 你没算过这一步，这个数是塞给你的" if not r.get("took_part") \
        else "有 —— 这一步是你自己做的"
    lines = ["结果：%s" % (r.get("result") or ""),
             "谁产出的：%s" % (r.get("source") or ""),
             "这一步你参与了吗：%s" % took]
    if r.get("how"):
        lines.append("怎么来的：%s" % r["how"])
    if r.get("raw"):
        lines.append("原始数据：%s" % r["raw"])
    if r.get("who_asked"):
        lines.append("谁发起的：%s" % r["who_asked"])
    return "\n".join(lines)


def render(n=3):
    """给模型的**原料块**：一条一条的事实字段，**没有一句是能照抄的话**。

    最后那一行是**怎么用**（不是答案）：自己推、自己组织、不要照抄这一块。
    """
    items = recent(n)
    if not items:
        return ""
    out = ["【你手上刚拿到的原料（事实字段，不是成品、不是给你的话、更不是答案）】"]
    for i, it in enumerate(items, 1):
        out.append("%d.\n%s" % (i, render_item(it)))
    out.append("怎么用：**你自己推**用户问的是什么，再**自己组织**成话；"
               "数字要一字不差，但说法不要照抄上面这一块。"
               "**不要自己重算** —— 上面的结果已经是算好的，直接用那个数"
               "（实测踩到：被问「这数对吗」时它自己重算了一遍，位数都算错了）。")
    return "\n" + "\n".join(out) + "\n"


def history(n=10):
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
    return out[-max(1, int(n)):]


def clear(why="自测复位"):
    with _LOCK:
        _STATE["items"] = []
        _STATE["_loaded"] = True
    try:
        if os.path.exists(_PATH):
            os.remove(_PATH)
    except Exception:      # noqa: silent-ok
        pass
    return {"ok": True, "why": why}


def stats():
    items = recent(MAX_KEEP)
    return {"fields": list(FIELDS), "count": len(items), "keep": MAX_KEEP,
            "path": _PATH, "last": (items[-1] if items else {}),
            "note": "给的是**原料**（结果/谁产的/有没有参与/怎么来的），"
                    "不是一句写好给它照搬的话；话由它自己组织"}
