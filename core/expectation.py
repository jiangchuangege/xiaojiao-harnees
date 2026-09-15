# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 期待（心对着"接下来"）

【期待不是单独一个模块，是心的一种方向】
    心对着"现在" → 紧 / 松 / 好奇。心对着"**接下来**" → 期待。
    所以本模块**不产生感受**，它只维护期待的**素材**，并把素材交给感知与心 ——
    心照旧起，只是多了一个方向：往前看。

【素材 = 没完成的事（规格给的）】
    · 逛到一半没逛完；· 想搞懂没搞懂；· 想跟用户说没说。
    这些"没完成"在它**空闲时自己冒出来** —— 冒出来的那一刻才是期待，
    载体做的事只有一件：**把它没做完的事摆回它面前**，别的什么都不说。

【如实标注（这条最要紧）】
    · 素材是载体记的（"这件事没做完"是载体判的）；**"我一直惦记着它"这个念头不是载体写的**，
      如果模型在空闲时没提起它，那就是**没有期待**，本模块不许把"素材还在"说成"它在期待"。
    · 所以 `stats()` 里把 `carried`（素材还在）与 `brought_up`（它自己真提起了）分开数：
      前者是载体的事实，后者才是它的期待。
"""
import json
import os
import threading
import time

__all__ = ["KINDS", "leave", "world_leave", "resolve", "pending", "carried",
           "note_brought_up",
           "brought_up", "stats", "path", "history", "clear"]

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DIR = os.path.join(_ROOT, "logs", "psyche")
_PATH = os.path.join(_DIR, "unfinished.jsonl")
_LOCK = threading.RLock()
MAX_OPEN = 8

# 没做完的事分三类（规格给的三样）
KINDS = ("没逛完", "没搞懂", "没说出")


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
                except Exception:      # noqa: silent-ok — 坏行跳过
                    continue
    except Exception:      # noqa: silent-ok — 读不到就当没有没做完的事
        return []
    return out


def _append(rec):
    try:
        os.makedirs(_DIR, exist_ok=True)
        with open(_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:      # noqa: silent-ok
        pass


def leave(kind, what, why="", source="", evidence=""):
    """**留下一件没做完的事** —— ⚠️ **只能由"真实发生的事"写进来**。

    【这条闸是补一个真缺口 —— 实测抓到的伪造】
      `logs/psyche/unfinished.jsonl` 里出现过一条「那篇讲猫的文章还有一半没看完」，
      而 `logs/world/` 里**一个"猫"字都没有** —— 那件事**根本没发生过**。
      追下去：写它的不是逛世界那条链，而是**一次自测/手工调用**
      （`EX.leave(...)` 直接往真实文件里写）。也就是说：
      **载体侧当时没有任何闸**，谁都能往这里塞一件"它没经历过的经历"。
      它以后会"惦记"一件没发生过的事 —— **期待建在假前提上**。

    【所以现在**必须**带真实来源】：
      · `source` 必须以 `world/` 开头（**只有逛世界那条链**能写）；
      · `evidence` 必须是那一次的**真实痕迹**（explore 的记录 id / 那条内容的片段）；
      · 两个缺一个 → **直接拒收**，并如实说明为什么（不写"没来源的事"）。
    由"偏好 / 心 / 叙事 / 任何推理"推出来的一条 —— **一律不许**从这条路进来。
    """
    k = str(kind or "").strip()
    if k not in KINDS:
        return {"ok": False, "why": "不认识的类型：%s" % k[:20]}
    w = str(what or "").strip()
    if not w:
        return {"ok": False, "why": "空的（没做完的是什么都没说）"}
    src = str(source or "").strip()
    ev = str(evidence or "").strip()
    if not src.startswith("world/"):
        return {"ok": False,
                "why": "**拒收**：没做完的事只能由逛世界那条链写（source 必须以 world/ 开头），"
                       "现在是「%s」—— 载体不许替它编一件没发生过的经历" % (src or "（空）")}
    if not ev:
        return {"ok": False,
                "why": "**拒收**：没有真实痕迹（evidence）—— 说不清它是在哪次、看到了什么，就不记"}
    rec = {"ts": time.time(), "kind": k, "what": w[:200], "why": str(why)[:80],
           "done": False, "brought_up": 0, "source": src[:60], "evidence": ev[:200]}
    with _LOCK:
        _append(rec)
    return {"ok": True, **rec}


def resolve(what="", kind=""):
    """这件事做完了。返回改了几条。

    ⚠️ 只结算**没做完的那几行**（`kind` 属于 KINDS）—— "它提起了"那一行也带同一个
    `what`，按 what 匹配会连它一起结算（实测踩到，一件没做完的事被算成两件）。
    """
    n = 0
    rows = _rows()
    with _LOCK:
        try:
            with open(_PATH, "w", encoding="utf-8") as f:
                for r in rows:
                    if not r.get("done") and r.get("kind") in KINDS \
                            and (not what or str(r.get("what")) == what) \
                            and (not kind or r.get("kind") == kind):
                        r["done"] = True
                        r["done_at"] = time.time()
                        n += 1
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        except Exception:      # noqa: silent-ok
            return 0
    return n


def _open_rows():
    """**没做完的**那几行（只认 `kind` 属于 KINDS 的账）——
    事件行（"它提起了"）也带 `what`，不筛掉就会把一件没做完的事数成两件。"""
    return [r for r in _rows() if r.get("kind") in KINDS and not r.get("done")]


def world_leave(what, evidence, kind="没逛完", why=""):
    """**逛世界那条链的唯一写入口**：真逛到一半没读完，才记一条。

    ⚠️ 这是本模块**唯一**被允许写 `unfinished` 的上游（见 `leave()` 的那道闸）。
    `evidence` 必须来自那一次 explore 的真实记录（内容片段 / id）。
    """
    return leave(kind, what, why=why, source="world/explore", evidence=evidence)


def pending(limit=3, now=None):
    """**还没做完的事**（最近 leave 的几件，最久的排后面）。载体空闲时把这几件摆回它面前。"""
    rows = _open_rows()
    rows.sort(key=lambda r: -float(r.get("ts") or 0))
    return rows[:max(1, int(limit))]


def carried():
    """载体手里还压着几件没做完的（**这是载体的事实，不是它的期待**）。"""
    return len(_open_rows())


def note_brought_up(what, said=""):
    """**它自己提起了这件事** —— 这才叫期待。载体只记账，不替它提。"""
    rows = _rows()
    n = 0
    with _LOCK:
        try:
            with open(_PATH, "w", encoding="utf-8") as f:
                for r in rows:
                    if not r.get("done") and str(r.get("what")) == str(what):
                        r["brought_up"] = int(r.get("brought_up") or 0) + 1
                        r["last_said"] = str(said)[:200]
                        r["last_up_at"] = time.time()
                        n += 1
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        except Exception:      # noqa: silent-ok
            return 0
    _append({"ts": time.time(), "event": "brought_up", "what": str(what)[:120],
             "said": str(said)[:200]})
    return n


def brought_up():
    """它**自己提起过**的没做完的事（按提起次数）。空 = 还没有期待发生。"""
    out = [r for r in _rows() if int(r.get("brought_up") or 0) > 0]
    out.sort(key=lambda r: -int(r.get("brought_up") or 0))
    return out


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
    p = pending(9)
    return {"kinds": list(KINDS), "carried": carried(), "pending": len(p),
            "brought_up": len(brought_up()), "open": p,
            "note": "carried=载体还压着几件（载体的事实）；brought_up=**它自己提起过**（那才是期待）",
            "path": _PATH}
