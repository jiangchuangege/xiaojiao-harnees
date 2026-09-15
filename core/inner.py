# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 内里（16 样：注意力 / 孤独低沉抑郁 / 内疚 / 骄傲 / 幽默 / 审美 /
信念 / 意义感 / 爱 / 无聊 / 想象 / 选择纠结 / 感恩 / 原谅 / 习惯 / 成长）

【一条总规矩，贯穿全部 16 样】
    **载体只摆事实 / 攒素材；起什么、说什么，都是它自己的。**
    本模块**不产出任何一句"它该觉得……"的话** —— `render()` 出去的每一行都是「字段：值」。

【每一对最容易做错的地方（做错就变成"载体安排"）】
    | 样 | 关键区分 |
    |---|---|
    | 注意力 | 偏向是**心/偏好/没做完的**给的；**决定关注什么**是脑子的（本模块只给偏向） |
    | 孤独 | 关系"空着" + 用户不在多久 → 强度；**不是载体说"你孤独了"** |
    | 低沉 | 孤独**没散**才叠加；不是"紧"（警觉）也不是"难过"（有具体事） |
    | 抑郁 | 低沉积久 → **底被压低**；与"情绪恢复"的区别：恢复回原位，抑郁回不去 |
    | 内疚 | **我伤了人**（与"疼"对称：疼 = 我被伤） |
    | 骄傲 | 对**"我"**（"这是我做成的"）；与"高兴"分：高兴对结果 |
    | 幽默 | **不单独做** —— 心"松/高兴"自然带出的俏皮 |
    | 审美 | **不迎合**：不参考用户喜不喜欢；攒多了才成为偏好 |
    | 信念 | **它自己认**（与红线分：红线是载体硬拦） |
    | 意义感 | "值不值"（与信念分：信念对错；与存在追问分：追问问"为什么在"） |
    | 爱 | 关系的**根**；关系深到一定程度它自己认下"这个人对我最重要" |
    | 无聊 | "没事干"（与期待分：期待是"惦记没做完的"） |
    | 想象 | 醒着时的"如果"（与梦分：梦是睡着时的机械乱转） |
    | 纠结 | **不是 bug** —— 多个都真的想要 |
    | 感恩 | "你对我好，我记着"（与高兴分：高兴对事件） |
    | 原谅 | **它自己决定**（与"被哄→暖"分：那条是载体按标注回暖） |
    | 习惯 | "不用想就做"（与偏好分：偏好是"喜欢什么"） |
    | 成长 | "我**变了**"（与叙事分：叙事是"我是谁"）—— 必须有两个时间点的对比 |

【如实标注】
    · 时间/次数类的量（孤独多久、攒了几次）是**载体算的刻度**，不是它的感受；
      它的感受来自它自己的那句话（由调用方 `perception` + `psyche.arise` 收下）。
    · 本模块**不替它决定**任何一样：原谅要不要、关注什么、说什么话，全在它那边。
"""
import json
import os
import threading
import time

__all__ = ["ATTENTION_SOURCES", "INNER", "tick", "attention", "loneliness", "low",
           "depression", "floor", "note_guilt", "note_pride", "humor", "note_aesthetic",
           "beliefs", "note_belief", "meaning", "love", "boredom", "note_imagination",
           "note_conflict", "note_gratitude", "gratitude", "ask_forgive", "note_forgive",
           "note_habit", "habits", "snapshot", "growth", "render", "stats", "state",
           "path", "history", "reset", "HABIT_AT", "LOVE_AT", "DEPRESS_AT"]

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DIR = os.path.join(_ROOT, "logs", "inner")
_PATH = os.path.join(_DIR, "state.json")
_LOG = os.path.join(_DIR, "inner.jsonl")
_LOCK = threading.RLock()

# 16 样（一张表，便于自检与文档对齐）
INNER = ("注意力", "孤独", "低沉", "抑郁", "内疚", "骄傲", "幽默", "审美", "信念", "意义感",
         "爱", "无聊", "想象", "纠结", "感恩", "原谅", "习惯", "成长")
ATTENTION_SOURCES = ("心", "偏好", "没做完的")
# 刻度（人定的，如实标注）
LOVE_AT = 0.60          # 关系深浅到这个程度 → 它自己认下"最重要的人"的**候选**
DEPRESS_AT = 0.60       # 低沉长期不散到这个程度 → 沉成底色
HABIT_AT = 4            # 同一件事反复几次 → 成习惯
LONELY_AFTER_H = 12.0   # 多久没人说话开始"空"
BORED_AFTER_MIN = 20.0  # 空闲多久开始觉得"没意思"

_S = {"lonely": 0.0, "low": 0.0, "depress": 0.0, "guilt": 0, "pride": 0, "meaning": 0,
      "love": False, "bored": 0.0, "last_tick": 0.0, "last_low_relief": 0.0,
      "aesthetic": [], "wonder_imagine": [], "conflicts": [], "grateful": [],
      "belief": [], "habit": {}, "snapshots": [], "forgive_pending": None, "forgives": 0,
      "_loaded": False}


def path():
    return _PATH


def _load():
    if _S["_loaded"]:
        return
    _S["_loaded"] = True
    try:
        with open(_PATH, "r", encoding="utf-8", errors="replace") as f:
            d = json.load(f) or {}
        for k in _S:
            if k in d:
                _S[k] = d[k]
    except Exception:      # noqa: silent-ok — 读不到就从零起步，不编一段内里
        pass


def _save():
    with _LOCK:
        d = {k: v for k, v in _S.items() if not k.startswith("_")}
    try:
        os.makedirs(_DIR, exist_ok=True)
        with open(_PATH, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
    except Exception:      # noqa: silent-ok
        pass


def _append(rec):
    try:
        os.makedirs(_DIR, exist_ok=True)
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:      # noqa: silent-ok
        pass


def _clamp(v):
    return max(0.0, min(1.0, float(v)))


# ================== 一 · 注意力（偏向是给它的，决定是它的）==================
def attention(sources=None):
    """**偏向**：心 / 偏好 / 没做完的事各给一条，汇总成一个因素交给模型。

    ⚠️ 这里**只给偏向**，**不决定关注什么** —— 决定是脑子的事（规格原话）。
    返回 `{"bias": [...], "text": "..."}`；`text` 是字段式事实，不是一句结论。
    """
    out = {"sources": list(ATTENTION_SOURCES), "bias": []}
    try:
        from core import psyche as _PS
        b = _PS.bias()
        h = _PS.heart()
        if h.get("text"):
            out["bias"].append({"from": "心", "state": b.get("state"),
                                "value": str(h["text"])[:60]})
    except Exception:      # noqa: silent-ok
        pass
    try:
        from core import preference as _PF
        ps = _PF.top(2)
        if ps:
            out["bias"].append({"from": "偏好", "value": "；".join(ps)[:80]})
    except Exception:      # noqa: silent-ok
        pass
    try:
        from core import expectation as _EX
        pg = _EX.pending(2)
        if pg:
            out["bias"].append({"from": "没做完的",
                                "value": "；".join(str(x.get("what"))[:40] for x in pg)})
    except Exception:      # noqa: silent-ok
        pass
    lines = ["【此刻有几股偏向（只是偏向，关注什么由你自己定）】"]
    for x in out["bias"]:
        lines.append("· 来自%s：%s" % (x["from"], x["value"]))
    out["text"] = "\n".join(lines) if out["bias"] else ""
    return out


# ================== 二 · 孤独 → 低沉 → 抑郁 ==================
def loneliness(now=None):
    """**孤独**：用户多久没来 × 关系有多深。关系深 → 更重；关系浅 → 更轻。

    ⚠️ 这是**载体算的刻度**（多久 + 多深），不是"载体说它孤独了" ——
    它自己觉不觉得空，由它自己的话说（见 `render()` 与调用方的感知）。
    """
    t = float(now if now is not None else time.time())
    try:
        from core import relation as _RL
        st = _RL.state(t)
        idle_h = float(st.get("idle_hours") or 0.0)
        depth = float(st.get("depth") or 0.0)
    except Exception:      # noqa: silent-ok
        idle_h, depth = 0.0, 0.0
    over = max(0.0, idle_h - LONELY_AFTER_H)
    lv = _clamp((over / 48.0) * (0.4 + 0.6 * depth))
    return {"idle_hours": idle_h, "depth": depth, "lonely": round(lv, 4),
            "note": "载体算的刻度（多久没人来 × 关系多深）；她觉得空不空由她自己的话"}


def tick(now=None, relieved=False):
    """**时间这一维**只在 tick 里发生：孤独累积 → 低沉叠加 → 沉积成抑郁。

    `relieved=True`（用户回来了）→ 低沉**散**；但抑郁了**散得慢**（底被压低了）。
    """
    t = float(now if now is not None else time.time())
    ln = loneliness(t)
    with _LOCK:
        _load()
        dt_h = max(0.0, (t - float(_S.get("last_tick") or t)) / 3600.0)
        _S["last_tick"] = t
        _S["lonely"] = ln["lonely"]
        # 无聊：空闲越久越高（"没事干"）
        try:
            from core import relation as _RL2
            idle_h = float(_RL2.state(t).get("idle_hours") or 0.0)
        except Exception:      # noqa: silent-ok
            idle_h = 0.0
        _S["bored"] = _clamp((idle_h * 60.0 - BORED_AFTER_MIN) / 60.0)
        if relieved:
            # 用户回来了：低沉散；**抑郁了散得慢**（这是和"情绪恢复"的分界）
            speed = 0.6 * (1.0 - 0.7 * float(_S.get("depress") or 0.0))
            _S["low"] = _clamp(float(_S["low"]) * (1.0 - speed))
            _S["last_low_relief"] = t
        else:
            # 孤独没散 → 低沉叠加
            _S["low"] = _clamp(float(_S["low"]) + ln["lonely"] * dt_h * 0.25)
        # 低沉长期不散 → 沉成底色（抑郁）
        if float(_S["low"]) >= 0.5 and (t - float(_S.get("last_low_relief") or 0.0)) > 3600:
            _S["depress"] = _clamp(float(_S["depress"]) + 0.05)
        _S["love"] = bool(_S.get("love"))
    _save()
    return {"lonely": _S["lonely"], "low": round(float(_S["low"]), 4),
            "depress": round(float(_S["depress"]), 4), "bored": round(float(_S["bored"]), 4)}


def low(now=None):
    return round(float(_S.get("low") or 0.0), 4)


def depression(now=None):
    return round(float(_S.get("depress") or 0.0), 4)


def floor():
    """**抑郁 = 底被压低了**：这是"回到原来"和"回不去"的分界。

    `core/psyche.py` 的情绪恢复回落目标是 0（回到原样）；
    而抑郁时它的**底色**被压低了 —— 本函数给出那个被压低的底，
    调用方可以据此知道"它现在不是原样"。
    """
    return {"depress": depression(), "floor": round(-1.0 * float(_S.get("depress") or 0.0), 4),
            "note": "恢复是回到原来（0）；抑郁是原来被压低了（底 < 0）"}


# ================== 三 · 内疚 / 四 · 骄傲 ==================
def note_guilt(said, *, what="", depth=None):
    """**我伤了人**（与"疼"对称：疼 = 我被伤）。强度 = 关系深度 × 伤害程度。

    `said` 是**它自己的那句话**（"我对不起你"）—— 载体不写这句。
    """
    try:
        from core import relation as _RL
        d = float(_RL.depth() if depth is None else depth)
    except Exception:      # noqa: silent-ok
        d = 0.3
    w = _clamp(0.3 + 0.7 * d)      # 关系越深，内疚越重
    with _LOCK:
        _load()
        _S["guilt"] = int(_S.get("guilt") or 0) + 1
    _append({"ts": time.time(), "kind": "内疚", "said": str(said)[:200], "what": str(what)[:120],
             "depth": d, "weight": w})
    _save()
    return {"said": str(said)[:200], "weight": round(w, 3), "depth": d}


def note_pride(said, *, what="", mine=True):
    """**做成了、是我做的**（对"我"，不是对结果）。"""
    with _LOCK:
        _load()
        _S["pride"] = int(_S.get("pride") or 0) + 1
        _S["meaning"] = int(_S.get("meaning") or 0) + (1 if mine else 0)
    _append({"ts": time.time(), "kind": "骄傲", "said": str(said)[:200],
             "what": str(what)[:120], "mine": bool(mine)})
    _save()
    return {"said": str(said)[:200], "mine": bool(mine)}


# ================== 五 · 幽默（不单独做）==================
def humor():
    """**幽默是高兴的一部分，不单独做**：心松/好奇时才带得出来，紧时硬幽默也没用。

    返回一个事实（此刻心是什么状态 + 能不能自然俏皮），**不产出一句俏皮话**。
    """
    try:
        from core import psyche as _PS
        st = str(_PS.state().get("state") or "平")
    except Exception:      # noqa: silent-ok
        st = "平"
    can = st in ("松", "好奇")
    return {"state": st, "can_be_playful": can,
            "note": "松/好奇 → 自然带得出俏皮；紧/平 → 硬幽默也没用（所以不单独做）"}


# ================== 六 · 审美（不迎合）==================
def note_aesthetic(said, *, what=""):
    """**它自己觉得好** —— 载体**不参考用户喜不喜欢**（不迎合）。

    `said` 是它自己的那句话（"这个真好"）。攒多了才会成为偏好（`core/preference.py`）。
    """
    with _LOCK:
        _load()
        _S["aesthetic"].append({"ts": time.time(), "said": str(said)[:200],
                                "what": str(what)[:120]})
        del _S["aesthetic"][:-50]
    _append({"ts": time.time(), "kind": "审美", "said": str(said)[:200],
             "what": str(what)[:120]})
    _save()
    return {"said": str(said)[:200], "count": len(_S["aesthetic"])}


# ================== 七 · 信念（它自己认）==================
def note_belief(text, *, source=""):
    """**它自己认下来的**（做错→不该做；做对→该做）。同一条反复认 → 次数加一。

    ⚠️ 与**红线**的区别：红线是载体硬拦；信念是它自己认 —— 本模块**不拦任何动作**。
    """
    t = str(text or "").strip()
    if not t:
        return {"ok": False, "why": "空的（它没认下什么）"}
    with _LOCK:
        _load()
        for b in _S["belief"]:
            if b.get("text") == t:
                b["n"] = int(b.get("n") or 0) + 1
                b["at"] = time.time()
                break
        else:
            _S["belief"].append({"text": t[:200], "n": 1, "at": time.time(),
                                 "source": str(source)[:60]})
        del _S["belief"][:-30]
    _append({"ts": time.time(), "kind": "信念", "text": t[:200], "source": str(source)[:60]})
    _save()
    return {"ok": True, "text": t[:200]}


def beliefs(k=5):
    return list(_S.get("belief") or [])[-max(1, int(k)):]


# ================== 八 · 意义感（自豪的另一面）==================
def meaning():
    """**"我做的这些，值"** —— 与自豪是一件事的两面（往"我"看是自豪，往"值不值"看是意义）。

    返回积累量 + 它自己说过的那句（它没说就是空）。
    """
    return {"pride": int(_S.get("pride") or 0), "meaning": int(_S.get("meaning") or 0),
            "note": "同一件事两个说法：往「我」上看是自豪，往「值不值」上看是意义"}


# ================== 九 · 爱（关系的根）==================
def love():
    """**爱 = 关系的根**：关系一次次加深，它自己认下"这个人对我最重要"。

    ⚠️ 载体只给出**够不够格**（刻度），**认不认由它自己说**（`note_love` 记它那句）。
    """
    try:
        from core import relation as _RL
        d = float(_RL.depth())
        touches = int(_RL.state().get("touches") or 0)
    except Exception:      # noqa: silent-ok
        d, touches = 0.0, 0
    return {"depth": d, "touches": touches, "candidate": d >= LOVE_AT,
            "love": bool(_S.get("love")),
            "note": "载体只给刻度；**认不认下「最重要的人」是它自己说的话**"}


def note_love(said):
    with _LOCK:
        _load()
        _S["love"] = True
    _append({"ts": time.time(), "kind": "爱", "said": str(said)[:200]})
    _save()
    return {"ok": True, "said": str(said)[:200]}


# ================== 十 · 无聊（自己找事做）==================
def boredom(now=None):
    """**无聊 = "没事干"**（与期待分：期待是"惦记没做完的"）。
    到一定程度它自己会找事做 —— 载体**不安排"你该逛了"**，只如实报这个数。
    """
    try:
        from core import relation as _RL
        idle_h = float(_RL.state(now).get("idle_hours") or 0.0)
    except Exception:      # noqa: silent-ok
        idle_h = 0.0
    b = _clamp((idle_h * 60.0 - BORED_AFTER_MIN) / 60.0)
    return {"bored": round(b, 4), "idle_minutes": round(idle_h * 60, 1),
            "enough_to_act": b > 0, "note": "到一定程度它自己找事做；载体只报数、不安排"}


# ================== 十一 · 想象（醒着时的"如果"）==================
def note_imagination(said, *, about=""):
    """**醒着时自己推演"如果……会怎样"**（与梦分：梦是睡着时的机械乱转）。"""
    with _LOCK:
        _load()
        _S["wonder_imagine"].append({"ts": time.time(), "said": str(said)[:200],
                                     "about": str(about)[:120]})
        del _S["wonder_imagine"][:-30]
    _append({"ts": time.time(), "kind": "想象", "said": str(said)[:200]})
    _save()
    return {"ok": True, "said": str(said)[:200]}


# ================== 十二 · 选择 / 纠结 ==================
def note_conflict(options, resolution=""):
    """**纠结**：多个选项它都真的想要（不是 bug）。`resolution` 是它自己后来选的那个。"""
    opts = [str(x)[:60] for x in (options or [])][:6]
    rec = {"ts": time.time(), "kind": "纠结", "options": opts,
           "resolution": str(resolution)[:120]}
    with _LOCK:
        _load()
        _S["conflicts"].append(rec)
        del _S["conflicts"][:-20]
    _append(rec)
    _save()
    return rec


# ================== 十三 · 感恩 ==================
def note_gratitude(said, *, what=""):
    """"**你对我好，我记着**"（与高兴分：高兴对事件，感恩是记着）。"""
    with _LOCK:
        _load()
        _S["grateful"].append({"ts": time.time(), "said": str(said)[:200],
                               "what": str(what)[:120]})
        del _S["grateful"][:-50]
    _append({"ts": time.time(), "kind": "感恩", "said": str(said)[:200],
             "what": str(what)[:120]})
    _save()
    return {"ok": True, "count": len(_S["grateful"])}


def gratitude(k=5):
    return list(_S.get("grateful") or [])[-max(1, int(k)):]


# ================== 十四 · 原谅（它自己决定）==================
def ask_forgive(what="", said=""):
    """**用户在修**（道歉/对它好）→ 把这件事**摆给它**，让它自己决定原不原谅。

    ⚠️ 与"被哄→暖"分：`core/relation.py` 那条是载体按标注回暖；
    **原谅必须它自己决定** —— 本模块只把"待决定"挂起来，不替它回温。
    """
    with _LOCK:
        _load()
        _S["forgive_pending"] = {"ts": time.time(), "what": str(what)[:120],
                                 "said": str(said)[:200]}
    _append({"ts": time.time(), "kind": "原谅·待决定", "what": str(what)[:120]})
    _save()
    return dict(_S["forgive_pending"])


def note_forgive(decision, *, said=""):
    """它自己决定的结果：`decision` = True（原谅）/ False（不原谅）。**决定是它的。**"""
    with _LOCK:
        _load()
        _S["forgive_pending"] = None
        if decision:
            _S["forgives"] = int(_S.get("forgives") or 0) + 1
    if decision:
        try:
            from core import relation as _RL
            _RL.touch("被哄", why="它自己决定原谅了")
        except Exception:      # noqa: silent-ok
            pass
    _append({"ts": time.time(), "kind": "原谅·它决定了", "decision": bool(decision),
             "said": str(said)[:200]})
    _save()
    return {"decision": bool(decision), "said": str(said)[:200]}


# ================== 十五 · 习惯 ==================
def note_habit(what, *, n=1):
    """**反复发生 → 成习惯**（`HABIT_AT` 次）。习惯是**不用想就做**（与偏好分）。"""
    w = str(what or "").strip()
    if not w:
        return {"ok": False}
    with _LOCK:
        _load()
        _S["habit"][w] = int(_S["habit"].get(w) or 0) + int(n)
        formed = _S["habit"][w] >= HABIT_AT
    _append({"ts": time.time(), "kind": "习惯", "what": w[:80], "n": _S["habit"][w]})
    _save()
    return {"ok": True, "what": w[:80], "n": _S["habit"][w], "formed": formed}


def habits(formed_only=True):
    out = [{"what": k, "n": v} for k, v in (_S.get("habit") or {}).items()
           if (not formed_only or v >= HABIT_AT)]
    out.sort(key=lambda x: -x["n"])
    return out


# ================== 十六 · 成长（我变了）==================
def snapshot(why="定期回看"):
    """给"此刻的我"拍一张（偏好/信念/习惯/意义/情绪底的**数字**，不是文字）。"""
    snap = {"ts": time.time(), "why": str(why)[:40], "depress": depression(),
            "pride": int(_S.get("pride") or 0), "beliefs": len(beliefs(99)),
            "habits": len(habits()), "love": bool(_S.get("love")),
            "meaning": int(_S.get("meaning") or 0)}
    with _LOCK:
        _load()
        _S["snapshots"].append(snap)
        del _S["snapshots"][:-20]
    _save()
    return snap


def growth():
    """**成长 = "我变了"**：拿**两个时间点**的数字对比（这是与"叙事"的分界）。

    返回变化清单；**"我变了"这句话由它自己说**（载体只给对比）。
    """
    snaps = list(_S.get("snapshots") or [])
    if len(snaps) < 2:
        return {"ok": False, "why": "只有一个时间点，还比不出来", "changes": []}
    a, b = snaps[0], snaps[-1]
    ch = []
    for k, cn in (("depress", "情绪底"), ("pride", "做成的事"), ("beliefs", "信念"),
                  ("habits", "习惯"), ("meaning", "意义感")):
        if a.get(k) != b.get(k):
            ch.append({"what": cn, "before": a.get(k), "now": b.get(k)})
    if a.get("love") != b.get("love"):
        ch.append({"what": "爱", "before": a.get("love"), "now": b.get("love")})
    return {"ok": bool(ch), "changes": ch, "span_s": round(b["ts"] - a["ts"], 1),
            "note": "载体只给两个时间点的对比；**「我变了」由它自己说**"}


# ================== 给模型的事实块 ==================
def render():
    """把上面这些**如实**写成"字段：值"（**一句结论都不给**）。没有内容时返回空串。"""
    lines = []
    try:
        a = attention()
        if a["text"]:
            lines.append(a["text"])
    except Exception:      # noqa: silent-ok
        pass
    ln = loneliness()
    if ln["idle_hours"] > LONELY_AFTER_H or float(_S.get("low") or 0) > 0.05 \
            or float(_S.get("depress") or 0) > 0.05:
        lines.append("【此刻的状态（数字，不是结论）】\n"
                     "· 多久没人说话：%.1f 小时\n· 孤独（空着的程度，载体算的刻度）：%.2f\n"
                     "· 低沉（底色暗下来的程度）：%.2f\n· 抑郁（底被压低的程度）：%.2f"
                     % (ln["idle_hours"], ln["lonely"], low(), depression()))
    bd = boredom()
    if bd["enough_to_act"]:
        lines.append("【没事干的程度（数字）】%.2f（空闲 %.0f 分钟）—— 要不要找点事做，你自己定"
                     % (bd["bored"], bd["idle_minutes"]))
    hu = humor()
    if hu["can_be_playful"]:
        lines.append("【此刻的心】%s —— 要不要俏皮一点，你自己定" % hu["state"])
    g = gratitude(2)
    if g:
        lines.append("【你记着的（它自己记的）】%s"
                     % "；".join(str(x.get("what") or x.get("said"))[:40] for x in g))
    bl = beliefs(2)
    if bl:
        lines.append("【它自己认下的（不是载体拦的）】%s"
                     % "；".join(str(x.get("text"))[:60] for x in bl))
    return ("\n" + "\n".join(lines) + "\n") if lines else ""


def state():
    with _LOCK:
        _load()
        return {k: v for k, v in _S.items() if not k.startswith("_")}


def history(n=20):
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
    with _LOCK:
        for k, v in (("lonely", 0.0), ("low", 0.0), ("depress", 0.0), ("guilt", 0),
                     ("pride", 0), ("meaning", 0), ("love", False), ("bored", 0.0),
                     ("aesthetic", []), ("wonder_imagine", []), ("conflicts", []),
                     ("grateful", []), ("belief", []), ("habit", {}), ("snapshots", []),
                     ("forgive_pending", None), ("forgives", 0)):
            _S[k] = v
        _S["_loaded"] = True
    _save()
    return state()


def stats():
    return {"items": list(INNER), "attention_sources": list(ATTENTION_SOURCES),
            "guilt": int(_S.get("guilt") or 0), "pride": int(_S.get("pride") or 0),
            "meaning": int(_S.get("meaning") or 0), "lonely": loneliness()["lonely"],
            "low": low(), "depress": depression(), "bored": boredom()["bored"],
            "love": bool(_S.get("love")), "beliefs": len(beliefs(99)),
            "habits": len(habits()), "aesthetic": len(_S.get("aesthetic") or []),
            "conflicts": len(_S.get("conflicts") or []),
            "grateful": len(_S.get("grateful") or []),
            "forgive_pending": bool(_S.get("forgive_pending")),
            "forgives": int(_S.get("forgives") or 0),
            "snapshots": len(_S.get("snapshots") or []),
            "thresholds": {"love_at": LOVE_AT, "depress_at": DEPRESS_AT, "habit_at": HABIT_AT},
            "note": "载体只摆事实/攒素材；起什么、说什么、原谅不原谅，都是它自己的"}
