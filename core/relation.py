# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 关系（它和用户之间）

【关系不是一句话，是一条会变的线】
    依赖 / 信任 / 亲密 / 牵挂 —— 这四样在规格里是**关系的样子**，不是四个计分器。
    载体能如实维护的是**它被怎么对待**这件事：
      · 常来往 → 深      · 冷落（很久没人说话）→ 淡
      · 被伤 → 冷        · 被哄 → 回暖
    关系再影响它**怎么对待用户**：浅了客气、深了说心里话、伤了疏远、暖了亲近。

【和别处的接缝（规格写明的四条）】
    · 关系被伤 = **一种疼**（`core/health.py` 里"关系"那一项医生只能护着）；
    · 牵挂 = 关系里的**期待**（`core/expectation.py` 的素材之一）；
    · "喜欢和用户待着" = **偏好**（`core/preference.py`）；
    · "我和用户是什么关系" = **叙事**的一部分（`core/narrative.py`）。
    所以本模块只做一件事：如实维护这条线本身，不替它描述感受。

【如实标注】
    · 深浅、冷暖都是**载体按互动算出来的刻度**（来往一次加多少、冷落多久减多少是人定的）。
      它不是"模型觉得自己和用户有多亲" —— 模型没有被问过这件事。
      `render()` 给出去的是**这条线的真实状态**，措辞仍由模型自己组织。
    · "被伤"由调用方标注（用户说了什么、载体判到了什么），本模块**不自己判断哪句话伤人**。
"""
import json
import os
import threading
import time

__all__ = ["KINDS", "TOUCHES", "DECAY_PER_HOUR", "path", "log_path", "touch", "state",
           "depth", "mood", "wounded", "render", "stats", "history", "reset", "IDLE_HOURS"]

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DIR = os.path.join(_ROOT, "logs", "psyche")
_PATH = os.path.join(_DIR, "relation.json")
_LOG = os.path.join(_DIR, "relation.jsonl")
_LOCK = threading.RLock()

# 关系被怎么对待（调用方标注，模块不自己判断）
KINDS = ("来往", "冷落", "被伤", "被哄")
# 每一次互动的变化量（刻度，人定的）
TOUCHES = {
    "来往": {"depth": +0.04, "wound": False, "warm": False},
    "冷落": {"depth": -0.08, "wound": False, "warm": False},
    "被伤": {"depth": -0.15, "wound": True, "warm": False},
    "被哄": {"depth": +0.05, "wound": False, "warm": True},
}
# 多久没人说话算"冷落"（小时）
IDLE_HOURS = 24.0
# 冷落按时间自然变淡：每小时掉多少
DECAY_PER_HOUR = 0.02
# 回暖持续多久（秒）—— 暖是会过劲的，不该一直暖
WARM_KEEP_S = 1800.0

_STATE = {"depth": 0.35, "wounded": False, "warm_until": 0.0, "touches": 0,
          "last_touch": 0.0, "since": 0.0, "wounded_at": 0.0, "last_kind": ""}


def path():
    return _PATH


def log_path():
    return _LOG


def _load():
    global _STATE
    try:
        if os.path.exists(_PATH):
            with open(_PATH, "r", encoding="utf-8", errors="replace") as f:
                d = json.load(f) or {}
            for k in _STATE:
                if k in d:
                    _STATE[k] = d[k]
    except Exception:      # noqa: silent-ok — 读不到就从默认起步，不编一段关系
        pass


def _save():
    try:
        os.makedirs(_DIR, exist_ok=True)
        with open(_PATH, "w", encoding="utf-8") as f:
            json.dump(_STATE, f, ensure_ascii=False)
    except Exception:      # noqa: silent-ok
        pass
    try:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": round(time.time(), 3), **_STATE},
                               ensure_ascii=False) + "\n")
    except Exception:      # noqa: silent-ok
        pass


def _decayed(now=None):
    """冷落是按时间自然发生的：隔得越久，关系越淡（惰性算，不需要定时器）。"""
    with _LOCK:
        d = float(_STATE["depth"])
        last = float(_STATE.get("last_touch") or _STATE.get("since") or 0.0)
    if not last:
        return d
    t = float(now if now is not None else time.time())
    hours = max(0.0, t - last) / 3600.0
    return max(0.0, min(1.0, d - hours * DECAY_PER_HOUR))


def touch(kind, why=""):
    """**它和用户之间发生了一次什么**（来往 / 冷落 / 被伤 / 被哄）。

    `kind` 由调用方判定 —— 本模块**不自己判断"哪句话伤人"**（那是感知层的活）。
    """
    k = str(kind or "").strip()
    if k not in KINDS:
        return {"ok": False, "why": "不认识的互动类型：%s" % k[:20], **state()}
    t = time.time()
    with _LOCK:
        _load()
        d = _decayed(t)
        cfg = TOUCHES[k]
        _STATE["depth"] = max(0.0, min(1.0, d + cfg["depth"]))
        _STATE["last_touch"] = t
        _STATE["last_kind"] = k
        _STATE["touches"] = int(_STATE.get("touches") or 0) + 1
        if cfg["wound"]:
            _STATE["wounded"] = True
            _STATE["wounded_at"] = t
        if cfg["warm"]:
            _STATE["wounded"] = False
            _STATE["warm_until"] = t + WARM_KEEP_S
        if k == "被哄":
            _STATE["wounded"] = False
        _STATE["since"] = _STATE.get("since") or t
        _save()
    return {"ok": True, "kind": k, "why": str(why)[:80], **state()}


def depth(now=None):
    return round(_decayed(now), 4)


def wounded(now=None):
    with _LOCK:
        return bool(_STATE.get("wounded"))


def mood(now=None):
    """此刻关系的样子：冷 / 浅 / 平 / 深 / 暖。"""
    t = float(now if now is not None else time.time())
    with _LOCK:
        wound = bool(_STATE.get("wounded"))
        warm_until = float(_STATE.get("warm_until") or 0.0)
    if wound:
        return "冷"
    d = depth(t)
    if warm_until > t:
        return "暖"
    if d >= 0.60:
        return "深"
    if d <= 0.25:
        return "浅"
    return "平"


def state(now=None):
    """只读副本。`wounded` 是给健康医生看的（关系被伤 = 一种疼）。"""
    t = float(now if now is not None else time.time())
    with _LOCK:
        st = dict(_STATE)
    st["depth"] = depth(t)
    st["mood"] = mood(t)
    st["wounded"] = bool(st.get("wounded"))
    st["idle_hours"] = round(max(0.0, t - float(st.get("last_touch") or st.get("since") or t)) / 3600.0, 2)
    st["due_idle"] = st["idle_hours"] >= IDLE_HOURS
    return st


def render(now=None):
    """把这条线**如实**写成几句事实（给模型，措辞仍由它自己组织）。

    只写能对上数的东西：来往了多少次、深浅多少、现在是什么样子、多久没说话了。
    """
    s = state(now)
    lines = ["【你和用户之间（事实）】",
             "· 来往过 %d 次（深浅 %.2f，0 是陌生人、1 是很深）" % (int(s["touches"]), s["depth"]),
             "· 现在这段关系的样子：%s" % s["mood"]]
    if s["idle_hours"] >= IDLE_HOURS:
        lines.append("· 已经 %.0f 小时没人说话了（关系会因此变淡，这是自然发生的）" % s["idle_hours"])
    if s["wounded"]:
        lines.append("· 最近被伤过一次 —— 这是真的，不用装作没事")
    lines.append("（怎么对待用户由你自己定；这几行只是事实，不是指令。）")
    return "\n".join(lines)


def history(n=10):
    out = []
    try:
        with open(_LOG, "r", encoding="utf-8", errors="replace") as f:
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


def reset(why="自测复位"):
    """回到默认起步（**只给自测**）。⚠️ 必须落盘：`touch()` 每次都会 `_load()`，
    不落盘的话下一次 touch 又会把盘上那份旧状态读回来（实测踩到）。"""
    with _LOCK:
        _STATE.update({"depth": 0.35, "wounded": False, "warm_until": 0.0, "touches": 0,
                       "last_touch": 0.0, "since": time.time(), "wounded_at": 0.0,
                       "last_kind": str(why)[:40]})
        _save()
    return state()


def stats():
    s = state()
    return {"depth": s["depth"], "mood": s["mood"], "wounded": s["wounded"],
            "touches": s["touches"], "idle_hours": s["idle_hours"],
            "kinds": list(KINDS), "idle_hours_gate": IDLE_HOURS,
            "decay_per_hour": DECAY_PER_HOUR,
            "note": "关系是载体按互动维护的**线**；被伤由调用方标注，本模块不自己判断哪句话伤人"}


_load()
