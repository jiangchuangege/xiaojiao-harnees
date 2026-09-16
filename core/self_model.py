# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任意模型 → 系统活；换任意模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 自我模型（第四阶段：因果归属）

【这是什么】
    记"**我的状态变化导致了什么**"。一条典型记录：

        因为精力低（0.28 / 档位中），这一轮我少装了工具（探索类 5→0），且没主动逛。

    **不是**"我感到累" —— 那是叙事；这一层记的是**因果**：
    状态 → 真的改了输入/行动 → 结果。

【归属测试（规格点名的）】
    **把"我感到X"这类叙事输出全去掉，因果影响仍在。**
    所以本模块：
      · 只记**可核对的事实**（前值→后值、档位、开关）；
      · 模块里**没有任何模型调用**，**不产出任何一句话**；
      · 自测里专门钉住"全程不看任何一句话，归属记录照样在"。

【立场状态必须回流（不是记完就完了）】
    `stance()` 给出一个累积量 `trim_pressure`：**最近被状态裁过多少次**。
    它**成为下一轮硬改的输入之一** —— `core/perspective.py` 的 `policy()` 会读它，
    于是"上一次因为精力低被裁了工具"这件事**会累积进这一轮的裁剪程度**。
    这就是规格要求的："不是记完就完了。"

【如实标注】
    · 记的是**载体侧可观测的因果**（我裁了工具、我锁了门），
      不是"它心里怎么想" —— 载体观测不到后者，也不假装能。
    · 权重、条数、压制阈值都是**人定的常量**（策略写在代码里）。
"""
import json
import os
import threading
import time

__all__ = ["KINDS", "STANCE_DECAY", "TRIM_AT", "note", "attributions", "stance",
           "render", "stats", "timeline", "reset", "path"]

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DIR = os.path.join(_ROOT, "logs")
_PATH = os.path.join(_DIR, "self_model.jsonl")
_LOCK = threading.RLock()

# 记哪几类因果（都是"状态 → 真的改了东西"）
KINDS = ("输入被裁", "行动被裁", "主动被压")
# 立场：被裁压力的衰减速度与"够格压制"的条数
STANCE_DECAY = 0.90
TRIM_AT = 3
MAX_KEEP = 200

_S = {"trim_pressure": 0.0, "counts": {}, "last": {}, "updates": 0, "_loaded": False}


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
                k = str(r.get("kind") or "")
                if k in KINDS:
                    _S["counts"][k] = int(_S["counts"].get(k) or 0) + 1
                    _S["updates"] = int(_S["updates"]) + 1
    except Exception:      # noqa: silent-ok — 读不到就从零起步，不编一段历史
        pass


def note(kind, cause, effect, before=None, after=None, level=""):
    """**记一条因果归属**：状态（cause）→ 真的改了什么（effect，带前值/后值）。

    `before` / `after` 是**可核对的数**（比如工具个数）—— 有它们才叫"真的改了"。
    """
    k = str(kind or "").strip()
    if k not in KINDS:
        return {"ok": False, "why": "不认识的因果类型：%s" % k[:20]}
    rec = {"ts": round(time.time(), 3), "kind": k, "level": str(level or "")[:8],
           "cause": str(cause or "")[:120], "effect": str(effect or "")[:160],
           "before": before, "after": after}
    with _LOCK:
        _load()
        _S["counts"][k] = int(_S["counts"].get(k) or 0) + 1
        _S["updates"] = int(_S["updates"]) + 1
        # **立场累积**：被裁一次就抬一点（会被时间/新扰动衰减）
        _S["trim_pressure"] = round(min(1.0, float(_S["trim_pressure"]) * STANCE_DECAY + 0.25), 4)
        _S["last"] = dict(rec)
    try:
        os.makedirs(_DIR, exist_ok=True)
        with open(_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:      # noqa: silent-ok — 记不上不影响这一轮
        pass
    return {"ok": True, **rec}


def attributions(n=5):
    """最近几条因果归属（从盘上读，可复核）。"""
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


def stance(now=None, decay_step=1.0):
    """**立场状态**：最近被状态裁过多少次（`trim_pressure`）+ 三类计数。

    它**回流进下一轮的硬改**（`perspective.policy()` 会读它）——
    上一次被裁这件事会累积进这一轮的裁剪程度。
    惰性衰减：没有新裁时慢慢回落（不会永久压制）。
    """
    with _LOCK:
        _load()
        p = float(_S["trim_pressure"]) * (STANCE_DECAY ** max(0.0, float(decay_step)))
        c = dict(_S["counts"])
        last = dict(_S.get("last") or {})
    return {"trim_pressure": round(p, 4), "counts": c, "updates": int(_S["updates"]),
            "suppress": p >= (TRIM_AT * 0.25) * 0.6,
            "last": last,
            "note": "立场状态（被裁压力 + 计数）——它会回流进下一轮的裁剪程度，不是记完就完了"}


def render(n=3):
    """**只给事实**（前值→后值 + 档位），**一句感受词都没有**。空时返回空串。"""
    rows = attributions(n)
    if not rows:
        return ""
    lines = ["【你自己的状态这一阵导致了什么（事实，不是感受）】"]
    for r in rows:
        seg = "· [%s] 因为%s → %s" % (r.get("kind"), str(r.get("cause"))[:40],
                                      str(r.get("effect"))[:60])
        if r.get("before") is not None or r.get("after") is not None:
            seg += "（%s→%s）" % (r.get("before"), r.get("after"))
        lines.append(seg)
    return "\n".join(lines) + "\n"


def timeline(n=20):
    return attributions(n)


def reset(why="自测复位"):
    with _LOCK:
        _S.update({"trim_pressure": 0.0, "counts": {}, "last": {}, "updates": 0, "_loaded": True})
    try:
        if os.path.exists(_PATH):
            os.remove(_PATH)
    except Exception:      # noqa: silent-ok
        pass
    return {"ok": True, "why": why}


def stats():
    return {"kinds": list(KINDS), "path": _PATH, "stance": stance(),
            "recent": attributions(3), "trim_at": TRIM_AT, "stance_decay": STANCE_DECAY,
            "note": "记的是**因果**（状态→真的改了输入/行动），不是叙事；"
                    "立场状态会回流进下一轮硬改"}
