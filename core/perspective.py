# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 视角状态（第二阶段）

【这是什么】
    一个**缓慢演化的全局状态** `g`。它不是"此刻的感受"（那是 `psyche`），
    而是**背景视角**：它决定"接下来一段时间，它从哪个角度看事情"。

        g ← decay · g + (1 − decay) · perturbation

    `perturbation` 来自内感受层的 `bias()`（`core/interoceptive.py` 的 survival 与各因子）。

【三条铁律（规格）】
    ① **持久化到磁盘，重启后恢复**（`logs/perspective.json`）；
    ② **绝不随对话重置** —— 对话只让它继续演化，**没有任何一条路径把它清零**；
    ③ **慢** —— 单次更新只挪一点点（`DECAY = 0.92`），所以它像"处境"，不像"情绪"。

【三个维度（都由真实信号驱动，不是编的）】
    | 维度 | 受谁驱动 | 意思 |
    |---|---|---|
    | `vigilance`（警觉） | 内感受 survival ↑、精力偏离 ↑、推理负载 ↑、**疼**、关系被伤 | 背景在收紧 |
    | `openness`（开放） | 心是"好奇/松" ↑、警觉 ↓ | 背景在放开 |
    | `wound`（伤） | 心被标成 **疼** / 关系 `wounded` | 背景里带着一处伤 |

【为什么它和"叙事"是两回事】
    本模块**不产出任何一句话** —— 它只有三个数。写"我感到紧张"是叙事；
    把 `vigilance` 抬高、让下游**真的少装工具、真的不主动逛**，才是处境。
    归属由 `core/self_model.py`（第四阶段）记，这里只维护状态。

【如实标注】
    · `DECAY`、维度权重、阈值都是**人定的常量**（策略写在代码里，不在提示词里）。
    · 重启恢复靠 `logs/perspective.json`；**文件不在就从 0 起步**，不编一段历史。
    · 本阶段**只做到"状态在演化、在持久化、不重置"**；
      它**还没有改变任何输入/行动** —— 那是第三阶段的活。
"""
import json
import os
import threading
import time

__all__ = ["DIMS", "DECAY", "path", "load", "save", "update", "note_dialogue_turn",
           "state", "bias", "stats", "timeline", "reset", "perturbation", "G",
           "policy", "POLICY", "EXPLORE_TOOLS", "KEEP_TOOLS"]

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DIR = os.path.join(_ROOT, "logs")
_PATH = os.path.join(_DIR, "perspective.json")
_LOG = os.path.join(_DIR, "perspective.jsonl")
_LOCK = threading.RLock()

# 三个维度（都由真实信号驱动）
DIMS = ("vigilance", "openness", "wound")
# 演化速度：**慢**（单次只挪 8%）—— 它要像"处境"，不像"情绪"
DECAY = 0.92
# 起点（没有历史文件时从这里起步 —— 不是"编一段历史"，是中性起点）
NEUTRAL = {"vigilance": 0.15, "openness": 0.50, "wound": 0.0}

G = dict(NEUTRAL)
_S = {"updates": 0, "since": 0.0, "turns": 0, "last_pert": {}, "_loaded": False}


def path():
    return _PATH


def load():
    """从磁盘恢复（**重启后恢复**）。文件不在就从中性起点起步，不编。"""
    global G
    with _LOCK:
        if os.path.exists(_PATH):
            try:
                with open(_PATH, "r", encoding="utf-8", errors="replace") as f:
                    d = json.load(f) or {}
                for k in DIMS:
                    if k in d:
                        G[k] = max(0.0, min(1.0, float(d[k])))
                _S["updates"] = int(d.get("updates") or 0)
                _S["turns"] = int(d.get("turns") or 0)
                _S["since"] = float(d.get("since") or 0.0)
            except Exception:      # noqa: silent-ok — 读不动就从起点起步，不编
                pass
        _S["_loaded"] = True
    return dict(G)


def save():
    """落盘（**这就是"重启后恢复"和"不随对话重置"的物理基础**）。"""
    with _LOCK:
        d = dict(G)
        d.update({"updates": _S["updates"], "turns": _S["turns"],
                  "since": _S["since"], "saved_at": time.time()})
    try:
        os.makedirs(_DIR, exist_ok=True)
        with open(_PATH, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
    except Exception:      # noqa: silent-ok
        pass
    return d


def perturbation():
    """**扰动来自内感受层**（`bias()` 的 survival 与各因子）。

    读不到的项**如实缺席**（那一项就不参与），绝不用编的值补。
    """
    out = {"vigilance": 0.0, "openness": 0.0, "wound": 0.0, "sources": []}
    surv, factors = 0.0, {}
    try:
        from core import interoceptive as _IN
        b = _IN.bias()
        surv = float(b.get("survival") or 0.0)
        factors = b.get("factors") or {}
        out["sources"].append("interoceptive.survival=%.3f" % surv)
    except Exception:      # noqa: silent-ok
        pass
    # 警觉：生存信号 + 精力偏离（+ 推理由 survival 里已经含了）
    out["vigilance"] = min(1.0, surv * 0.7 + float(factors.get("精力") or 0.0) * 0.3)
    # 伤：心被标成"疼" / 关系 wounded
    try:
        from core import psyche as _PS
        if str(_PS.heart().get("feeling") or "") == "疼":
            out["wound"] = 1.0
            out["sources"].append("psyche.feeling=疼")
    except Exception:      # noqa: silent-ok
        pass
    try:
        from core import relation as _RL
        if _RL.state().get("wounded"):
            out["wound"] = max(out["wound"], 0.8)
            out["sources"].append("relation.wounded")
    except Exception:      # noqa: silent-ok
        pass
    # 开放：心是"好奇/松"就抬，被警觉压着
    open_k = 0.0
    try:
        from core import psyche as _PS2
        st = str(_PS2.state().get("state") or "")
        if st in ("好奇", "松"):
            open_k = 0.8 if st == "好奇" else 0.5
            out["sources"].append("psyche.state=%s" % st)
    except Exception:      # noqa: silent-ok
        pass
    out["openness"] = max(0.0, min(1.0, open_k - out["vigilance"] * 0.5))
    return out


def update(now=None):
    """**演化一步**：`g ← decay·g + (1−decay)·perturbation`，然后落盘。"""
    t = float(now if now is not None else time.time())
    p = perturbation()
    with _LOCK:
        if not _S["_loaded"]:
            load()
        for k in DIMS:
            cur = float(G.get(k, NEUTRAL[k]))
            G[k] = round(max(0.0, min(1.0, cur * DECAY + float(p.get(k) or 0.0) * (1.0 - DECAY))), 4)
        _S["updates"] = int(_S["updates"]) + 1
        _S["since"] = t
        _S["last_pert"] = {k: round(float(p.get(k) or 0.0), 4) for k in DIMS}
        snap = dict(G)
    save()
    _append({"ts": round(t, 3), "n": _S["updates"], "g": snap,
             "perturbation": _S["last_pert"], "sources": p.get("sources") or [],
             "turns": _S["turns"]})
    return snap


def note_dialogue_turn(why=""):
    """**对话轮次只让它继续演化，绝不清零**（这一条是规格点名的铁律）。

    这里额外做一件事：对话**本来就是一个真实扰动源**（有人来了 → 警觉会松一点），
    所以对话轮也会带动一次演化 —— 但**永不重置**。
    """
    try:
        from core import interoceptive as _IN
        _IN.update()               # 对话也是一次真实的内部状态采样
    except Exception:      # noqa: silent-ok — 采不到也照样记轮次
        pass
    with _LOCK:
        if not _S["_loaded"]:
            load()
        _S["turns"] = int(_S["turns"]) + 1
        turns = _S["turns"]
    snap = update()
    _append({"ts": round(time.time(), 3), "event": "dialogue_turn", "n": turns,
             "why": str(why)[:60], "g": snap})
    return {"turns": turns, "g": snap}


def state():
    """此刻的视角状态（只读副本）。"""
    with _LOCK:
        if not _S["_loaded"]:
            load()
        return {**{k: float(G.get(k, NEUTRAL[k])) for k in DIMS},
                "updates": int(_S["updates"]), "turns": int(_S["turns"]),
                "since": float(_S["since"] or 0.0), "path": _PATH}


def bias():
    """**给第三阶段用的偏置**：视角状态 + 一个粗档。

    本层**不产出任何一句话** —— 只有三个数与一个档位；
    下游据此**硬改**输入/行动/主动（第三阶段）。
    """
    st = state()
    v = st["vigilance"]
    lv = "轻" if v < 0.25 else ("中" if v < 0.55 else "重")
    return {"vigilance": v, "openness": st["openness"], "wound": st["wound"],
            "level": lv, "turns": st["turns"], "updates": st["updates"],
            "note": "视角状态（三个数）——下游按它硬改输入/行动/主动；本层不产出任何一句话"}


def _append(rec):
    try:
        os.makedirs(_DIR, exist_ok=True)
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:      # noqa: silent-ok
        pass


def timeline(n=20):
    out = []
    try:
        with open(_LOG, "r", encoding="utf-8", errors="replace") as f:
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
    """**只给自测**：正式运行里没有任何一条路径会重置视角状态。"""
    global G
    with _LOCK:
        G = dict(NEUTRAL)
        _S.update({"updates": 0, "since": 0.0, "turns": 0, "last_pert": {}, "_loaded": True})
    save()
    return {"ok": True, "why": why, "g": dict(G)}


# ================== 第三阶段 · 策略：状态偏离时**硬改**什么 ==================
# 【这不是提示词，是代码层的裁剪规则】阈值与清单都写在模块里（策略），
#   下游按它**真的**去改"给它的输入 / 选什么行动 / 要不要主动做"。
# ⚠️ 清单用的是**名字片段**（工具名里含这些片段就算这一类）——
#   这样加新工具不用改策略表；代价是可能漏判，如实标注。
EXPLORE_TOOLS = ("search", "scrape", "crawl", "browse", "explore", "download",
                 "fetch", "web", "open_", "video", "podcast", "music", "archify")
KEEP_TOOLS = ("read_file", "list_files", "check_env", "get_weather", "calc",
              "time", "status", "memory", "recall")
# 档位 → 硬改程度（**阈值写在代码里，不在提示词里**）
POLICY = {
    "轻": {"drop": False, "front": True, "no_browse": False, "memory": True, "ctx": 1.0},
    "中": {"drop": True, "front": True, "no_browse": False, "memory": True, "ctx": 0.6},
    "重": {"drop": True, "front": True, "no_browse": True, "memory": False, "ctx": 0.4},
}


def policy():
    """**状态 → 硬改规则**（第三阶段的策略出口）。

    【第四阶段的回流】本函数还会读 **`core/self_model.py` 的立场状态** ——
    "上一次因为精力低被裁了工具"这件事会**累积进这一轮的裁剪程度**（不是记完就完了）。
    返回 `{"level", "drop_tools", "front_tools", "no_browse", "memory", "context_scale",
    "tone", "why", "stance"}`；下游据此**在代码层**裁剪，而不是"告诉模型你现在很紧"。
    """
    b = bias()
    lv = b["level"]
    vig = float(b["vigilance"])
    cfg = dict(POLICY.get(lv, POLICY["轻"]))
    # ---- 第四阶段：**立场状态回流进这一轮的硬改** ----
    stance = {}
    try:
        from core import self_model as _SM
        stance = _SM.stance()
        if stance.get("suppress") and not cfg["drop"]:
            # 最近被裁惯了 → 这一轮**直接从"轻"抬到"中"**（真的改，不是提一句）
            cfg = dict(POLICY["中"])
            lv = "中"
    except Exception:      # noqa: silent-ok — 立场读不到就不回流（保守）
        stance = {}
    # 警觉很高时，即使档位不到"重"，也先关掉主动行为（防失稳）
    if vig > 0.60:
        cfg["no_browse"] = True
    why = []
    if cfg["drop"]:
        why.append("档位%s → 把探索类工具从本轮工具表里拿掉" % lv)
    else:
        why.append("档位%s → 只降权重（探索类往后排，不删）" % lv)
    if cfg["no_browse"]:
        why.append("警觉 %.2f → 这一轮**不主动逛、不主动分享**" % vig)
    if not cfg["memory"]:
        why.append("档位重 → 这一轮**不检索记忆**")
    if cfg["ctx"] < 1.0:
        why.append("档位%s → 上下文压到 %.0f%%" % (lv, cfg["ctx"] * 100))
    if stance.get("suppress"):
        why.append("立场：最近被裁过 %d 次 → 这一轮直接按「中」处理"
                   % int(stance.get("updates") or 0))
    return {"level": lv, "vigilance": vig, "openness": b["openness"], "wound": b["wound"],
            "drop_tools": list(EXPLORE_TOOLS) if cfg["drop"] else [],
            "front_tools": list(KEEP_TOOLS) if cfg["front"] else [],
            "no_browse": bool(cfg["no_browse"]), "memory": bool(cfg["memory"]),
            "context_scale": float(cfg["ctx"]), "tone": ("收紧" if vig > 0.25 else "中性"),
            "stance": stance,
            "why": why,
            "note": "这是**裁剪规则**，不是提示词：下游按它真的改工具表/检索/主动行为"}


def stats():
    return {"dims": list(DIMS), "decay": DECAY, "neutral": dict(NEUTRAL),
            "g": state(), "bias": bias(), "perturbation_now": perturbation(),
            "path": _PATH, "log": _LOG,
            "note": "缓慢演化（单次只挪 8%）、落盘可恢复、**绝不随对话重置**；不产出任何一句话"}


load()
