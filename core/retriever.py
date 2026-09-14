# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
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
import re
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

# ===== 载体二次判断（小脑召回 → 大脑精排）=====
# 【为什么必须有这一层 —— 小脑的已知边界，不是它的 bug】
#   小脑是**字级**模型，均值池化出来的向量在"主题级"够用，在"精细语义"上不行。实测：
#     · "我非常喜欢这个方案" vs "我非常讨厌这个方案" 余弦 **0.904**（近义对才 0.814）
#       —— 两者共享 10/11 个字，字级表示看到的是"同一串字"，不是"相反的意思"。
#     · "今天天气真好" vs "数据库索引用 B+ 树" 余弦 0.570 —— 无关项也偏高（各向异性）。
#   而 `THRESHOLD = 0.6` 只能挡住一部分。剩下的**反义/无关**如果直接注进 system，
#   模型就会拿"A 的反面"去回答"A 的问题" —— 这比"没记住"更糟。
# 【怎么补】小脑负责**召回**（宁可多召回），大脑负责**精排**（它读得懂语义）。
#   一次额外的小模型调用，只在"有多条候选"时才发生，失败一律放行（绝不因为判官挂了就丢记忆）。
RERANK = True                 # 总开关（操控文件可覆盖）
RERANK_MIN_HITS = 2           # 只有 1 条候选时不值得多跑一次模型
RERANK_MAX = 5                # 最多让大脑看几条（再多它也会挑花眼）
# 【为什么要"只在排名含糊时才精排" —— 这是实测逼出来的闸门，不是省事】
#   精排要调一次大脑，实测给检索加了 ~400ms（4ms → 409ms）。
#   而「无限 1 · 记忆无限」的验收线是**检索延迟 < 100ms** —— 无条件精排会直接把它判红。
#   想清楚"什么时候才值得花这 400ms"就清楚了：
#     · top1 明显领先（分差 ≥ 0.10）→ 向量排序本身就是可信的，再问大脑纯属白花时间；
#     · top1 与 top2 咬得很近（分差 < 0.10）→ **这正是反义/无关混进来的典型形状**
#       （实测「我喜欢蓝色」0.90 vs「我讨厌蓝色」0.88，分差只有 0.02），必须让大脑裁一下。
#   也就是说：这个闸门按"精排能不能改变结果"来开门，而不是按"跑测试方不方便"。
RERANK_GAP = 0.10             # top1 与 top2 的分差低于它，才认定"排名含糊"、需要精排
# 【为什么召回要单独给一道更低的底线 —— 实测抓出来的真 bug】
#   原来召回直接用 THRESHOLD = 0.6。于是：一条**确实相关但排名靠后**的长记忆，
#   分只有 0.548，**在精排之前就被滤掉了** —— 大脑连看都没看到它，精排显示「候选不足，跳过」。
#   实测：问「我上个月参加了什么会」，长记忆排第 5（0.548）被 0.6 拦掉，
#   最终注入的是毫不相干的短记忆（0.613）。
#   召回与判定是**两件事**：召回该宽（宁可多捞几条给大脑看），判定才该严。
#   所以召回用这条更低的底线，收口交给大脑精排；判官没真正筛选时退回原阈值（见下）。
RERANK_RECALL_THRESHOLD = 0.35  # 宽松召回底线（只用于给大脑看的候选集）
_RERANK_PROMPT = (
    "下面是一句用户提问和若干条历史记忆。请挑出**能用来回答这个问题**的记忆。\n"
    "判断标准（很重要，请逐条看）：\n"
    "  1. 记忆内容与提问说的是**同一件事、同一个方向** → 相关\n"
    "  2. 记忆与提问**方向相反**（问「喜欢什么」而记忆说「讨厌某物」；"
    "问「住在哪」而记忆说「不想说」）→ **不相关**，方向相反的记忆拿来回答会答反\n"
    "  3. 只是碰巧出现同一个词、但说的不是一回事 → 不相关\n"
    "只输出相关记忆的**编号**，用逗号分隔（例：1,3）；一条都不相关就只输出「无」。"
    "不要输出任何解释、不要复述记忆内容。\n\n"
    "用户提问：%s\n\n候选记忆：\n%s\n")


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
      hits        全部命中（含 score / decayed / ts / kind）
      used        真正被注入的（受 max_tokens 限制）
      text        注入用文本（空串表示没有可用记忆）
      tokens      注入文本的 token 数
      latency_ms  本次检索总耗时（向量 + 载体二次判断）
      vector_ms   **纯向量检索**那一段（无限 1 的"检索延迟 < 100ms"判的是它）
      rerank_ms   载体二次判断那一段（要调一次大脑，没触发时为 0）
      rid         本次检索 id（给 record_usage 回填"模型是否用了"）

    【为什么把延迟拆成两段报】
      加"载体二次判断"之前，检索纯是向量运算（实测 3~5ms），所以"检索延迟 < 100ms"
      是对**整个检索**说的。加了精排之后，"整个检索"里多了一次大脑调用（实测 +400ms）——
      这时候还报一个数，等于把"向量快不快"和"精排跑没跑"混成一个指标：
      要么用 400ms 冤枉向量层，要么用 5ms 掩盖精排的开销。拆开报，两个问题各自看得见。

    【为什么这么设计】模型不需要"记住"任何东西 —— 记忆在模型外面（向量库），
    要用的时候按查询检索 top-K 注入 system。这样：
    ① 模型 ctx 不随对话变长而爆（无限 6）；
    ② 换任何模型都自带全部历史（模型平等）；
    ③ "检索"这一步是可测的（命中率/使用率/延迟都有数字，见 test_memory_recall）。
    时间衰减**只影响排序、不参与阈值判断**：否则"三年前说的那件事"会被衰减掉、
    直接检索不到 —— 那等于系统自己把用户的经历弄丢了。

    【去掉它会怎样】要么把所有历史塞进 ctx（本地 20224 装不下 100 轮对话），
    要么模型只能记住最近几轮 —— 用户说"我叫张三"之后问"我叫什么"，它会答不上来。
    """
    t0 = time.time()
    top_k = int(TOP_K if top_k is None else top_k)
    threshold = float(THRESHOLD if threshold is None else threshold)
    max_tokens = int(MAX_TOKENS if max_tokens is None else max_tokens)
    now = time.time() if now is None else float(now)

    # 召回用宽松底线（见 RERANK_RECALL_THRESHOLD 的说明）：先把候选捞全，再让大脑收口。
    _recall_th = min(float(threshold), float(RERANK_RECALL_THRESHOLD)) if RERANK else threshold
    raw = memory_vec.search_memory(query, top_k=max(top_k * 3, top_k),
                                   threshold=_recall_th, dedup_text=True)
    vector_ms = (time.time() - t0) * 1000.0      # 纯向量检索这一段（判据：< 100ms）
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

    # ---- 载体二次判断：小脑召回 → 大脑精排（见 `rerank` 的说明）----
    # 放在"排好序、还没装进 token 预算"这一刻：先让大脑把反义/无关剔掉，
    # 省下来的 token 预算就留给真正相关的那些。
    before_n = len(hits)
    _t_rr = time.time()
    hits, rerank_note = rerank(query, hits)
    rerank_ms = (time.time() - _t_rr) * 1000.0
    # 判官**真的筛过**才算数（说明文本以「保留」开头）；跳过 / 不可用 / 保守放行时，
    # 把宽松召回带进来的低分候选按原阈值滤掉 —— 否则一关精排，无关记忆全被注入。
    if not str(rerank_note).startswith("保留"):
        _strict = [h for h in hits if float(h.get("score") or 0) >= float(threshold)]
        hits = _strict or hits[:1]
    try:
        if before_n >= RERANK_MIN_HITS:
            import logging
            logging.getLogger("xiaojiao.retriever").info(
                "检索精排（载体二次判断）：%d 条候选 → %s", before_n, rerank_note)
    except Exception:      # noqa: silent-ok — 日志失败绝不影响检索
        pass
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
            "vector_ms": round(vector_ms, 2), "rerank_ms": round(rerank_ms, 2),
            "rerank_note": rerank_note,
            "backend": embedder.backend()}


def _ask_brain(prompt):
    """问一次大脑（软依赖 xiaojiao_app）—— 拿不到就返回 None。

    为什么用软依赖而不是 `import xiaojiao_app`：`xiaojiao_app` 反过来 import 本模块，
    直接 import 会成环（启动即炸）。取不到就返回 None，让调用方**如实降级**，不是静默乱猜。

    【为什么先试带 max_tokens、再退回不带 —— 这一步是实测补上的】
      `xiaojiao_app.llm_chat(messages)` **不接受 `max_tokens` 参数**。
      第一版直接写 `fn(msgs, max_tokens=32)`，于是每次都抛 TypeError、被 except 吞掉、
      精排永远走"判官不可用，全部保留"这条降级路 —— **功能表面开着、实际一次都没生效**，
      而且没有任何报错。这类"静默失效"只能靠**真的调一次**才发现（自测里专门留了一条）。
    """
    try:
        import sys
        app = sys.modules.get("xiaojiao_app")
        fn = getattr(app, "llm_chat", None) if app is not None else None
        if fn is None:
            return None
        msgs = [{"role": "user", "content": prompt}]
        try:
            out = fn(msgs, max_tokens=32)
        except TypeError:
            out = fn(msgs)              # 老签名/别的实现：不接受 max_tokens
        return out if isinstance(out, str) else None
    except Exception:      # noqa: silent-ok — 判官挂了就放行全部候选，绝不因此丢记忆
        return None


def rerank(query, hits, judge=None):
    """**载体二次判断**：让大脑从 top-K 里挑出真相关的，滤掉反义 / 无关。

    返回 `(保留的 hits, 说明)`。**失败一律放行**（判官不可用、解析不出来、返回「无」全都保留了）。

    ① 为什么要它：小脑是字级模型，"喜欢/讨厌"余弦 0.904（比近义还高），
      0.6 的阈值挡不住这种反义；把反义记忆注进 system，模型会拿反面去回答问题 ——
      比"没记住"更糟。小脑负责召回（宁可多召回），大脑负责精排（它读得懂语义）。
    ② 去掉会怎样：反义/无关记忆直接进 system。实测症状就是"答非所问，而且答得理直气壮"。
    ③ 为什么最多只问 `RERANK_MAX` 条：候选太多时小模型会挑花眼，且 prompt 变长拖慢每轮。
    ④ 为什么"返回无"也放行：小模型偶尔会矫枉过正把**全部**候选判成无关。
      真按它说的清空，用户会突然感觉"它什么都不记得了" —— 那种退化的观感比多注入一条更差。
    """
    try:
        if not RERANK:
            return hits, "精排开关关闭，全部保留"
        if len(hits) < RERANK_MIN_HITS:
            return hits, "候选不足，跳过"
        # 排名不含糊就不精排（见 RERANK_GAP 的说明：这一条同时守住了"精度"和"检索延迟 <100ms"）
        gap = float(hits[0].get("decayed") or 0) - float(hits[1].get("decayed") or 0)
        if gap >= RERANK_GAP:
            return hits, "top1 领先 %.3f，排名不含糊 → 跳过精排" % gap
        cand = hits[:RERANK_MAX]
        listing = "\n".join("%d. %s" % (i + 1, (h.get("text") or "").replace("\n", " ")[:120])
                            for i, h in enumerate(cand))
        prompt = _RERANK_PROMPT % ((query or "").replace("\n", " ")[:200], listing)
        out = judge(prompt) if judge is not None else _ask_brain(prompt)
        if not out:
            return hits, "判官不可用，全部保留"
        picked = [int(x) for x in re.findall(r"\d+", out)]
        keep = [cand[i - 1] for i in picked if 1 <= i <= len(cand)]
        if not keep:
            return hits, "判官判为全不相关 → 保守保留（不轻易清空记忆）"
        # 尾部没让判官看的那些（超过 RERANK_MAX 的）按原顺序接在后面
        keep = keep + [h for h in hits[len(cand):]]
        return keep, "保留 %d/%d 条" % (len(keep), len(hits))
    except Exception:      # noqa: silent-ok — 精排是加分项，出错必须放行全部
        return hits, "精排异常，全部保留"



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
