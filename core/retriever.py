# -*- coding: utf-8 -*-
"""小焦 · 载体层 · 记忆检索（无限 1：记忆无限 —— 策略层）

memory_vec 负责"存 + 算余弦"，这里负责**策略**：时间衰减、相似度阈值、top-K、
注入 token 上限、以及把每次检索如实写进 `logs/memory_retrieval.log`。

┌─ 一条关键设计（载体优先的取舍，和 spec 字面略有不同，理由在下面）────────────┐
│ spec 写的是"余弦相似度 + 时间衰减，阈值 0.6"。如果**把衰减乘进阈值判定**，会出事：│
│ 一条 0.85 分的老记忆，衰减 0.4 后只剩 0.34 < 0.6 → 被丢掉。                  │
│ 那"三年前说的那个事"就永远检索不到了 —— 正好打死无限 1 的招牌场景。            │
│                                                                          │
│ 所以这里拆开用：                                                          │
│   · **阈值只判原始余弦**（判"这条到底相不相关"）—— 相关就是相关，跟多久以前无关；│
│   · **时间衰减只参与排序**（同样相关时，优先想起最近的）—— 这才是我们真正想要的 │
│     人类式记忆：老的能想起来，但新的更靠前。                                 │
└──────────────────────────────────────────────────────────────────────────┘

衰减分档照 spec：7 天内 ×1.0 / 30 天内 ×0.7 / 更早 ×0.4。
"""
import json
import os
import threading
import time

from . import embedder, memory_vec

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOG_PATH = os.path.join(_ROOT, "logs", "memory_retrieval.log")
_LOG_LOCK = threading.Lock()

# ===== 策略参数（都可被操控文件覆盖，见 xiaojiao_app 里的 _memory_cfg）=====
TOP_K = 5                 # 默认取最像的 5 条
THRESHOLD = 0.6           # 相似度阈值（判在原始余弦上）
MAX_TOKENS = 2000         # 注入进 system 的记忆文本上限
DECAY_7D = 1.0
DECAY_30D = 0.7
DECAY_OLD = 0.4
_D7 = 7 * 86400.0
_D30 = 30 * 86400.0


def decay(age_seconds):
    """时间衰减系数：7 天内 1.0 / 30 天内 0.7 / 更早 0.4。"""
    if age_seconds is None:
        return DECAY_7D
    if age_seconds <= _D7:
        return DECAY_7D
    if age_seconds <= _D30:
        return DECAY_30D
    return DECAY_OLD


def estimate_tokens(text):
    """与 xiaojiao_app._estimate_tokens 同一口径（cjk×1.5 + other/3）。

    优先借 app 的实现，保证"注入预算"和"上下文预算"是同一把尺子；借不到就用本地等价式。
    """
    try:
        import sys
        app = sys.modules.get("xiaojiao_app")
        if app is not None and hasattr(app, "_estimate_tokens"):
            return int(app._estimate_tokens(text))
    except Exception:      # noqa: silent-ok — 借不到就本地算，结果一致
        pass
    t = str(text or "")
    if not t:
        return 0
    cjk = sum(1 for ch in t if "\u4e00" <= ch <= "\u9fff")
    return int(cjk * 1.5 + (len(t) - cjk) / 3) + 1


def retrieve(query, top_k=None, threshold=None, max_tokens=None,
             log=True, kind=None, now=None):
    """检索相关记忆并拼成可注入的文本。

    返回 dict：
      hits       全部命中（含 score / decayed / ts / kind）
      used       真正被注入的（受 max_tokens 限制）
      text       注入用文本（空串表示没有可用记忆）
      tokens     注入文本的 token 数
      latency_ms 本次检索耗时
      rid        本次检索 id（给 record_usage 回填"模型是否用了"）
    """
    t0 = time.time()
    top_k = int(TOP_K if top_k is None else top_k)
    threshold = float(THRESHOLD if threshold is None else threshold)
    max_tokens = int(MAX_TOKENS if max_tokens is None else max_tokens)
    now = time.time() if now is None else float(now)

    raw = memory_vec.search_memory(query, top_k=max(top_k * 3, top_k),
                                   threshold=threshold, dedup_text=True)
    if kind:
        raw = [h for h in raw if h.get("kind") == kind]

    hits = []
    for h in raw:
        age = max(0.0, now - float(h.get("ts") or now))
        d = decay(age)
        hits.append({"id": h["id"], "text": h["text"], "kind": h.get("kind", "dialogue"),
                     "entities": h.get("entities") or [], "ts": h.get("ts"),
                     "score": h["score"], "decay": d,
                     "decayed": round(h["score"] * d, 4),
                     "age_days": round(age / 86400.0, 2)})
    # 排序：衰减后的分数（同样相关时，最近的更靠前）
    hits.sort(key=lambda h: -h["decayed"])
    hits = hits[:top_k]
    for i, h in enumerate(hits, 1):        # 补回 rank（memory_vec 那边的 rank 是按原始余弦排的，
        h["rank"] = i                      # 这里重排过，必须重编号，否则日志/自检会对不上）

    # 按 token 预算装（至少装 1 条：命中了就一定要给模型看到）
    used, lines, tok = [], [], 0
    for h in hits:
        # 「说话人是谁」必须由载体写清楚，不能指望模型自己猜到 —— 实测不加这层框定，
        # 模型会把记忆里的「我叫张三」当成在说它自己，回答"你叫小焦"。
        # 若正文已经是「用户：…／小焦：…」的对话格式，就不必再加前缀（别叠成"用户曾说过：用户：…"）。
        body = (h["text"] or "").replace("\n", " ").strip()
        line = body if body.startswith("用户：") else "- 用户曾说过：" + body
        if not line.startswith("-"):
            line = "- " + line
        if len(line) > 240:
            line = line[:240] + "…"
        add = estimate_tokens(line) + 1
        if used and tok + add > max_tokens:
            break
        used.append(h)
        lines.append(line)
        tok += add

    text = "\n".join(lines)
    latency = (time.time() - t0) * 1000.0
    rid = "%d" % int(time.time() * 1000)
    if log:
        log_retrieval(rid, query, hits, used, tok, latency)
    return {"hits": hits, "used": used, "text": text, "tokens": tok,
            "latency_ms": round(latency, 2), "rid": rid,
            "backend": embedder.backend()}


# ------------------------------------------------------------------ 日志
def log_retrieval(rid, query, hits, used, tokens, latency_ms, verdict=None):
    """如实记录一次检索：query / 检索条数 / 每条相似度 / 注入 token / （回填）模型是否使用。"""
    try:
        os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)
        sims = ", ".join("%.3f" % h["score"] for h in hits) or "无"
        ids = ",".join(h["id"].split("-")[0] for h in used) or "无"
        line = ("[%s] rid=%s 后端=%s 检索=%d条 注入=%d条 相似度=[%s] 注入token=%d "
                "耗时=%.1fms 模型使用=%s ｜ query=%s | 注入id=%s"
                % (time.strftime("%Y-%m-%d %H:%M:%S"), rid, embedder.backend(),
                   len(hits), len(used), sims, tokens, latency_ms,
                   "待定" if verdict is None else ("是" if verdict else "否"),
                   (query or "").replace("\n", " ")[:80], ids))
        with _LOG_LOCK:
            with open(_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:      # noqa: silent-ok — 记日志失败绝不能影响对话
        pass


def record_usage(rid, used, note=""):
    """对话结束后回填"模型到底有没有用上检索到的记忆"（写同一份日志，便于统计使用率）。"""
    try:
        os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)
        line = ("[%s] rid=%s 回填 模型使用=%s %s"
                % (time.strftime("%Y-%m-%d %H:%M:%S"), rid, "是" if used else "否", note[:60]))
        with _LOG_LOCK:
            with open(_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:      # noqa: silent-ok — 同上
        pass


def usage_rate(path=None):
    """从日志统计"使用率"：回填为"是"的比例。给自检和面板用。"""
    p = path or _LOG_PATH
    if not os.path.exists(p):
        return {"total": 0, "used": 0, "rate": 0.0}
    total = used = 0
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if "回填 模型使用=" not in line:
                continue
            total += 1
            if "回填 模型使用=是" in line:
                used += 1
    return {"total": total, "used": used, "rate": (used / total) if total else 0.0}


def config(**kw):
    """覆盖策略参数（供操控文件热改）。返回生效后的参数。"""
    global TOP_K, THRESHOLD, MAX_TOKENS
    if kw.get("top_k"):
        TOP_K = max(1, int(kw["top_k"]))
    if kw.get("threshold") is not None:
        THRESHOLD = float(kw["threshold"])
    if kw.get("max_tokens"):
        MAX_TOKENS = max(100, int(kw["max_tokens"]))
    return {"top_k": TOP_K, "threshold": THRESHOLD, "max_tokens": MAX_TOKENS}
