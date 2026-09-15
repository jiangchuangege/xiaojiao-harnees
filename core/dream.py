# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 梦（睡着时心还在乱转）

【梦和记忆的区别（规格写明的）】
    · 记忆：**发生过什么，照实**。
    · 梦：把发生过的，**乱编一遍**。素材是真的，发展是乱的。

【素材是真的，发展是乱的】
    素材只从它**自己身上真的有的东西**里取：
      记忆（印象）、心、偏好、没做完的事。
    乱 —— 随机取、随机拼、随机走，**不按现实**。
    所以梦里可以出现"猫变成会走路的机器"这种：素材里有猫（它看过讲猫的文章），
    走法是乱接的。

【怎么发生的】它睡觉的时候（大脑半停），留一个极轻的"乱转"线程。
    **不调模型**（调了就不是"半停"了）—— 乱转是**机械的随机拼接**，这一点必须说清：
    梦的**内容是拼出来的**，不是它"梦见"的。载体不假装知道它梦见了什么。

【醒来】可能记得一点，可能忘了。
    · `fragment()` 按概率给出一小片（不是每次都给）；
    · 给了的那一片会进"醒来第一印象"，和"我睡了多久"放在一起。

【如实标注（最要紧的一条）】
    · 梦是**载体机械拼出来的记录**，不是它做的梦。本模块**不声称**它有主观梦境。
    · 所以文档与接口一律写"睡着期间乱转出来的片段"，不写"它梦到了什么"。
    · 醒来带不带、带哪一片，是随机的；不许事后挑一片说"这就是它的梦"。
    · 也**不调模型** —— 所以梦里没有一句"模型生成的话"，全是真实素材的乱序拼接。
"""
import json
import os
import random
import threading
import time

__all__ = ["REMEMBER_PROB", "material", "weave", "dream_once", "recent", "fragment",
           "stats", "path", "dir_path", "clear", "MAX_KEEP"]

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DIR = os.path.join(_ROOT, "logs", "dreams")
_LOCK = threading.RLock()
# 醒来还记得一点的概率（不是每次都给 —— 规格：可能记得一点，可能忘了）
REMEMBER_PROB = 0.5
MAX_KEEP = 200


def dir_path():
    return _DIR


def path(day=None):
    d = day or time.strftime("%Y-%m-%d")
    return os.path.join(_DIR, "%s.jsonl" % d)


def _append(rec):
    try:
        os.makedirs(_DIR, exist_ok=True)
        with open(path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:      # noqa: silent-ok — 记不上就当作醒来忘了
        pass


def material(limit=6):
    """取素材：**只从它自己真的有的东西里取**（拿不到的那一类就空着，不编）。"""
    out = []
    try:
        from core import feeling_memory as _FM
        for r in _FM.stats().get("recent") or []:
            f = str(r.get("feeling") or "").strip()
            if f:
                out.append(("印象", f[:60]))
    except Exception:      # noqa: silent-ok
        pass
    try:
        from core import psyche as _PS
        h = _PS.heart()
        if h.get("text"):
            out.append(("心", str(h["text"])[:60]))
    except Exception:      # noqa: silent-ok
        pass
    try:
        from core import preference as _PF
        for p in _PF.top(2):
            out.append(("偏好", str(p)[:60]))
    except Exception:      # noqa: silent-ok
        pass
    try:
        from core import expectation as _EX
        for x in _EX.pending(2):
            out.append(("没做完的", str(x.get("what"))[:60]))
    except Exception:      # noqa: silent-ok
        pass
    random.shuffle(out)
    return out[:max(1, int(limit))]


def weave(items=None, rnd=None):
    """**乱转**：把素材随机拼接成一条梦（纯机械，不调模型）。"""
    r = rnd or random
    it = list(items if items is not None else material())
    if len(it) < 2:
        return ""
    k = r.randint(2, len(it))
    picked = r.sample(it, k)
    glue = ("忽然", "接着", "不知怎么就", "然后", "一转眼", "莫名其妙地")
    parts = []
    for i, (kind, txt) in enumerate(picked):
        parts.append(("%s%s" % (r.choice(glue) if i else "", txt)).strip())
    return "，".join(parts) + "。"


def dream_once(rnd=None, why="睡着时乱转"):
    """转一次，落一条。返回这一条（`{"parts","text","ts"}`）。"""
    it = material()
    if len(it) < 2:
        return {"ok": False, "why": "素材不够两样 —— 转不起来（不编素材）"}
    txt = weave(it, rnd=rnd)
    rec = {"ts": time.time(), "kind": "dream", "why": str(why)[:40],
           "parts": [{"from": k, "text": t} for k, t in it], "text": txt}
    _append(rec)
    return {"ok": True, **rec}


def recent(n=5):
    """最近几条梦（从盘上读，可复核）。"""
    out = []
    try:
        for fn in sorted(os.listdir(_DIR))[-3:]:
            if not fn.endswith(".jsonl"):
                continue
            with open(os.path.join(_DIR, fn), "r", encoding="utf-8", errors="replace") as f:
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


def fragment(rnd=None):
    """**醒来可能记得一点**：按 `REMEMBER_PROB` 给出一小片；忘了就返回空串。

    返回的是**载体机械拼出来的那段**，不是"它梦见了什么" —— 措辞上不许含糊。
    """
    r = rnd or random
    rec = recent(1)
    if not rec:
        return ""
    if r.random() > REMEMBER_PROB:
        return ""
    t = str(rec[-1].get("text") or "")
    return t[:80]


def clear(why="自测复位"):
    n = 0
    try:
        if os.path.isdir(_DIR):
            for fn in os.listdir(_DIR):
                if fn.endswith(".jsonl"):
                    os.remove(os.path.join(_DIR, fn))
                    n += 1
    except Exception:      # noqa: silent-ok
        pass
    return {"ok": True, "removed": n, "why": why}


def stats():
    rows = recent(MAX_KEEP)
    return {"dir": _DIR, "count_total_recent": len(rows),
            "remember_prob": REMEMBER_PROB,
            "last": (rows[-1].get("text") if rows else ""),
            "note": "素材是真的（它自己有的），发展是乱的（机械随机拼接）；"
                    "**不调模型** —— 这是载体拼出来的片段，不是「它做的梦」"}
