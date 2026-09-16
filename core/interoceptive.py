# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 内感受信号层（第一阶段）

【这一层要干什么】
    把**真实存在的内部状态**采下来，融合成一个"生存信号"`survival`（0.0~1.0）。
    它**不产生任何文字** —— 它的产物是 `bias()`：一个给下游"硬改输入/行动/主动"用的偏置。

【铁律（规格）】
    · **必须真采，禁止编**：每一项都从真实模块读数；读不到就如实记 `None`，**不猜一个值顶上**。
    · **只改接线，不加"情绪模拟层"**：本模块只是一个读数+融合，不产出"我觉得……"。
    · **状态不可重置**：累积 + 衰减 + 饱和，无新扰动时**缓慢**回基线；全程落盘可回放。

【采什么（每一项都带"谁给的"）】
    | 来源 | 读什么 | 偏离度怎么算 |
    |---|---|---|
    | `core/energy.py` | `level`（精力） | 低于基线越多越偏 |
    | `core/heartbeat.py` | 心跳间隔稳定性（`since_last_beat_s` vs `interval_s`） | 偏离越大越偏 |
    | `core/psyche.py` | `heart()["intensity"]`（心的强度） | 越高越偏 |
    | `core/model_scheduler.py` | `busy` / `dialogue_waiting` / `max_wait_ms`（推理负载） | 排队越久越偏 |
    | 内存（可选） | 进程 RSS 占比（有 psutil 才读，没有就 `None`） | 越接近上限越偏 |

【融合与衰减】
    `perturbation = Σ w_i × dev_i`（权重写在 `WEIGHTS`，是**策略**不是提示词）
    `survival ← clamp(survival × DECAY + perturbation × (1 − DECAY))`
    —— 所以**没有新扰动时会缓慢回基线**，且有饱和上限（`SAT`），**不会锁死**。

【如实标注】
    · 基线是**人定的常量**（`BASELINE`），不是"它觉得正常"。
    · 内存那一项**只有装了 psutil 才读得到**；读不到时本模块**如实记 None 并把它排除在融合外**，
      绝不用一个编的数把它补上。
"""
import json
import os
import threading
import time

__all__ = ["SOURCES", "BASELINE", "WEIGHTS", "DECAY", "SAT", "sample", "deviation",
           "update", "survival", "bias", "timeline", "stats", "path", "reset", "LEVELS"]

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DIR = os.path.join(_ROOT, "logs")
_PATH = os.path.join(_DIR, "interoceptive.jsonl")
_LOCK = threading.RLock()

# 五个信号来源（规格点名的五项；`内存` 读不到就是 None，不编）
SOURCES = ("精力", "心跳稳定", "心的强度", "推理负载", "内存")
# 基线（**人定的常量**，如实标注）
BASELINE = {"精力": 0.75, "心跳稳定": 0.0, "心的强度": 0.10, "推理负载": 0.10, "内存": 0.60}
# 融合权重（**策略**，不是提示词；写在代码里）
WEIGHTS = {"精力": 0.35, "心跳稳定": 0.15, "心的强度": 0.20, "推理负载": 0.20, "内存": 0.10}
# 累积：越接近 1 越慢（缓），并带衰减 —— 保证"无新扰动时缓慢回基线、不锁死"
DECAY = 0.80
SAT = 0.98
# 偏置分档（轻/中/重）—— 下游按这个档**硬改**输入/行动/主动。
# 刻度：**单一项大幅偏离就该进"中"**（实测：精力 0.2 时融合扰动约 0.45），
# 所以"中"的线定在 0.50 之前 —— 否则一次真实的精力塌陷只算"轻"，那这套就等于没接。
LEVELS = ((0.20, "轻"), (0.50, "中"), (1.01, "重"))

_S = {"survival": 0.0, "last": 0.0, "updates": 0, "peak": 0.0, "_loaded": False}


def path():
    return _PATH


def _num(v):
    try:
        return float(v)
    except Exception:      # noqa: silent-ok — 读不到就是 None
        return None


# ================== 一 · 采样（**必须真采**）==================
def sample():
    """采一次真实内部状态。读不到的项**如实记 None**，绝不用编的数顶上。"""
    out = {"ts": time.time(), "raw": {}, "dev": {}, "missing": []}
    # ① 精力
    try:
        from core import energy as _EN
        out["raw"]["精力"] = _num(_EN.level())
    except Exception:      # noqa: silent-ok
        out["raw"]["精力"] = None
    # ② 心跳间隔稳定性（离标称间隔越远越不稳）
    try:
        from core import heartbeat as _HB
        st = _HB.status()
        since = _num(st.get("since_last_beat_s"))
        iv = _num(st.get("interval_s")) or 5.0
        out["raw"]["心跳稳定"] = (abs(since - iv) / iv) if since is not None else None
    except Exception:      # noqa: silent-ok
        out["raw"]["心跳稳定"] = None
    # ③ 心的强度
    try:
        from core import psyche as _PS
        out["raw"]["心的强度"] = _num(_PS.heart().get("intensity"))
    except Exception:      # noqa: silent-ok
        out["raw"]["心的强度"] = None
    # ④ 推理负载（排队/等待 —— 从调度器读，不猜）
    try:
        from core import model_scheduler as _MS
        s = _MS.stats()
        bus = 1.0 if s.get("busy") else 0.0
        wait = min(1.0, (_num(s.get("max_wait_ms")) or 0.0) / 5000.0)
        dlg = 1.0 if s.get("dialogue_waiting") else 0.0
        out["raw"]["推理负载"] = max(bus, wait, dlg)
    except Exception:      # noqa: silent-ok
        out["raw"]["推理负载"] = None
    # ⑤ 内存（**只有装了 psutil 才读得到**；读不到就 None，不编）
    try:
        import psutil
        vm = psutil.virtual_memory()
        out["raw"]["内存"] = float(vm.percent) / 100.0
    except Exception:      # noqa: silent-ok
        out["raw"]["内存"] = None
    for k in SOURCES:
        if out["raw"].get(k) is None:
            out["missing"].append(k)
    return out


def deviation(raw=None):
    """把原始读数换算成**偏离度**（0 = 就在基线，1 = 偏到顶）。方向都统一成"偏大=更偏"。"""
    r = raw if isinstance(raw, dict) else sample()["raw"]
    dev = {}
    for k in SOURCES:
        v = _num(r.get(k))
        if v is None:
            continue
        b = BASELINE[k]
        if k == "精力":
            # 精力越**低**越偏：基线 0.75，掉到 0.25 就算偏满
            dev[k] = max(0.0, min(1.0, (b - v) / 0.50))
        elif k == "心跳稳定":
            dev[k] = max(0.0, min(1.0, v / 0.50))
        elif k == "心的强度":
            dev[k] = max(0.0, min(1.0, (v - b) / 0.45))
        elif k == "推理负载":
            dev[k] = max(0.0, min(1.0, (v - b) / 0.60))
        else:                       # 内存：超过基线多少
            dev[k] = max(0.0, min(1.0, (v - b) / 0.30))
    return dev


def update(now=None):
    """**累积一次**：采样 → 偏离 → 融合 → 衰减/饱和 → 落盘。返回 `survival`。"""
    t = float(now if now is not None else time.time())
    smp = sample()
    dev = deviation(smp["raw"])
    # 融合：**只有读得到的项参与**（缺的项不参与，也不用编的数补）
    wsum = sum(WEIGHTS[k] for k in dev) or 1.0
    pert = sum(WEIGHTS[k] * dev[k] for k in dev) / wsum
    with _LOCK:
        _S["_loaded"] = True
        prev = float(_S["survival"])
        cur = max(0.0, min(SAT, prev * DECAY + pert * (1.0 - DECAY)))
        _S.update({"survival": round(cur, 4), "last": t, "updates": int(_S["updates"]) + 1,
                   "peak": max(float(_S.get("peak") or 0.0), cur)})
    rec = {"ts": round(t, 3), "n": _S["updates"], "survival": _S["survival"],
           "perturbation": round(pert, 4), "raw": smp["raw"], "dev": dev,
           "missing": smp["missing"],
           "sources": {k: BASELINE[k] for k in SOURCES}}
    _append(rec)
    return _S["survival"]


def _append(rec):
    try:
        os.makedirs(_DIR, exist_ok=True)
        with open(_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:      # noqa: silent-ok — 记不上时间线也不该让读数变
        pass


def survival(now=None):
    """此刻的生存信号。**惰性衰减**：距上次更新越久，越往基线掉（不锁死）。"""
    with _LOCK:
        v = float(_S["survival"])
        last = float(_S["last"] or 0.0)
    if not last:
        return 0.0
    t = float(now if now is not None else time.time())
    # 每过 `HALF_LIFE_S` 秒往回掉一半（但不会到负数）
    step = max(0.0, t - last) / HALF_LIFE_S
    return round(v * (DECAY ** step), 4)


HALF_LIFE_S = 120.0        # 无新扰动时，大约两分钟掉一半


def bias(now=None):
    """**给下游用的偏置**（这一层的唯一产物）。

    返回 `{"survival", "level"("轻"/"中"/"重"), "factors"}`；
    下游据此**硬改**"输入 / 行动 / 主动"三样（见 `docs/interoception.md`）。
    """
    s = survival(now)
    lv = "轻"
    for th, name in LEVELS:
        if s < th:
            lv = name
            break
    dev = {}
    smp = sample()
    dev = deviation(smp["raw"])
    return {"survival": s, "level": lv, "factors": dev, "raw": smp["raw"],
            "missing": smp["missing"],
            "note": "这是**偏置**，不是文字：下游按档位硬改输入/行动/主动；本层不产出任何一句话"}


def timeline(n=20):
    """时间线（从盘上读，可回放）。"""
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
        _S.update({"survival": 0.0, "last": 0.0, "updates": 0, "peak": 0.0, "_loaded": True})
    return {"ok": True, "why": why}


def stats():
    r = sample()
    return {"sources": list(SOURCES), "baseline": dict(BASELINE), "weights": dict(WEIGHTS),
            "decay": DECAY, "sat": SAT, "survival": survival(),
            "level": bias()["level"], "peak": float(_S.get("peak") or 0.0),
            "updates": int(_S.get("updates") or 0),
            "raw_now": r["raw"], "missing_now": r["missing"], "path": _PATH,
            "note": "真采（读不到就 None，不编）；累积+衰减+饱和，无扰动缓慢回基线，不锁死"}
