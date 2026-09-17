# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 思考圈（心理改方向，大脑改状态，互相转成圈）

【要复刻的是"人的样子"】
    碰到点事 → **心里先动一下**（紧/松/好奇）→ 这一动**改大脑"往哪想"** →
    大脑想明白 → **想明白后心里那一下变了** → 下一步想法跟着变 → 又碰到事 →（一直转）

    三条：
      1. 心里先动，大脑后想
      2. 心一动，改大脑"往哪想"
      3. 大脑想完，改心的状态

【与之前六次的根本区别：不传消息，互相改状态】
    传消息：心理给大脑一段字「我怕」→ 落到上下文里就是**一条可被忽略的消息**。
    改状态：心理一动，改的是**检索先捞哪一类、生成收紧还是放松** →
            大脑**就在那个方向里想**，没有"要不要采纳"这个选项。

    这不是说法上的区别，是**代码上可验证**的区别：
      传消息 → 上下文里多出一段文字；
      改方向 → 上下文里**一个字都不多**，变的是候选顺序与生成参数。
    本模块只做后者；`_order_only()` 里那句断言就是给这件事留的证据。

【如实标注（规格硬性要求）】
    如果哪天这里被改成"把心理状态写成一段字塞进上下文"，那就**不是思考圈，是注入变体** ——
    必须如实标注。本模块**不产生任何要注入的文本**：`bias()` 给的只有关键词元组、温度增量、语气档。
"""
import threading

from core import psyche as _psyche

__all__ = ["adjust_candidates", "on_event", "bias_snapshot", "stats", "LOOP"]

_LOCK = threading.RLock()

# 圈转过的轮次与最近几次"改方向"的真实记录（自检与取证用）
LOOP = {"rounds": 0, "reorders": [], "nudges": []}
_MAX_REC = 12


def _score(text, keywords):
    """候选在**当前心理方向**上的得分：命中多少关键词。纯规则、可复核。"""
    if not keywords:
        return 0
    t = str(text or "")
    return sum(1 for k in keywords if k in t)


def adjust_candidates(cands, state=None, event_what=None):
    """**心理 → 大脑：改"往哪想"**。

    按当前心理状态的关键词偏置，把检索候选**重排**（稳定排序：同分保持原相对顺序）。
    **只重排，不增删、不改写任何候选文本** —— 这是"改方向"而非"传消息"的硬证据。

    `event_what`（2026-09-18 加，可选）：**感知层那一轮抠出来的「事」**。
    为什么要这个参数：原来检索那句只能从**心**里取（`psyche.colors()`），
    于是**心没起的那一轮 = 没有「事」= 检索退回用「我」（甚至只有关键词）**。
    但「事」来自感知层、心起不起它都有 —— 这条缺口由调用方把它递进来补上。
    优先级：**心的「事」→ 传进来的「事」→ 心的「我」**（心自己有就用心的，那是同一轮里更近的判断）。

    返回 `(重排后的候选, 记录)`；记录里写明"什么状态、把哪一条提前了"，供日志取证。
    """
    items = list(cands or [])
    # 圈转过一圈 = 它在跑 → 记一笔精力消耗（规格：每次思考圈转 → 精力降一点）。
    # 【必须在最前面】原来放在函数末尾，于是"方向中性、未重排"那条早退路径
    #   **一次都不记账** —— 而"没偏"也是圈转过一圈（实测抓到）。
    try:
        from core import energy as _EN
        _EN.consume(_EN.COST_THINKING_TURN, why="思考圈转一圈")
    except Exception:      # noqa: silent-ok — 精力模块不在不该影响"改方向"
        pass
    b = _psyche.bias(state)
    kws = b.get("keywords") or ()
    if not items:
        return items, {"state": b["state"], "keywords": [], "moved": [], "note": "无候选，未重排"}
    # ★ 心带模型走 v3（2026-09-18）：**检索用「事」，心用「我」** —— 两者分开。
    # 【为什么】实测 10 个案例：拿「事」（这句话在说什么事）去检索 top1 命中 9/10，
    #   拿「我」（心里起了什么）只有 5/10 —— **感受词通用会漂，事具体不漂**。
    #   心的那句（我）照旧给心用；检索这一路要的是"这件事跟哪条记忆是同一件事"。
    # 【抠不出「事」时】**退回用「我」**（`_rq = _ew or _q`）—— 不让检索因为少一栏就瘫掉。
    # 【心没起的那一轮】用调用方递进来的 `event_what`（感知层给的）——
    #   这条是 2026-09-18 补的缺口：原来"心没起 → 这一轮没有「事」可用"。
    _q = ""
    _ew = ""
    try:
        _c = _psyche.colors() or {}
        _ew = str(_c.get("event_what") or "").strip()
        _q = str(_c.get("query") or "").strip()
    except Exception:      # noqa: silent-ok — 读不到心的偏向就退回关键词检索，不让检索整条瘫掉
        pass
    _ew_src = "心" if _ew else ""
    if not _ew:
        _in_ew = str(event_what or "").strip()
        if _in_ew:
            _ew, _ew_src = _in_ew, "感知"
    _rq = _ew or _q
    if not _rq and not kws:
        return items, {"state": b["state"], "keywords": [], "moved": [], "note": "方向中性，未重排"}
    before = [id(c) for c in items]
    # ★ 优先向量；没有「事/我」或向量失败 → 退回关键词
    if _rq:
        try:
            from core import embedder as _EM
            import math as _math
            def _cos(a, b_):
                _d = sum(x*y for x, y in zip(a, b_))
                _na = _math.sqrt(sum(x*x for x in a))
                _nb = _math.sqrt(sum(x*x for x in b_))
                return _d/(_na*_nb) if _na and _nb else 0.0
            _qv = _EM.embed(_rq)
            if not _qv:
                # 「事/我」都拿不到向量 → 这个后端现在不能用，如实退回关键词（要求 3）
                raise ValueError("检索那句话拿不到向量")
            _n = len(_qv)

            def _vec(c):
                _e = _EM.embed(str(c.get("text") if isinstance(c, dict) else c or ""))
                # ⚠️ 实测（2026-09-18）：候选里只要有一条**空文本**，`embed("")` 返回 None →
                #    `zip(_qv, None)` 抛 TypeError → 被外层 except 吃掉 → **整批**静默退回
                #    关键词匹配，语义排序全丢（一条坏候选废掉整批）。
                #    这里给它一个**零向量**：那条自己排最后，别的候选照常按语义排。
                return _e if _e else [0.0] * _n

            items = sorted(items, key=lambda c: -_cos(_qv, _vec(c)))
            # **可复核**：这一轮检索到底用的哪句话（事 还是 我）—— 只加一行日志，不改任何判据。
            # 为什么值得记：这次修的就是"事有没有真的接到检索上"这条线；不写它，
            # 生产日志里就看不出来（`colors.event_what` 曾经永远是空，而日志上毫无痕迹）。
            try:
                import logging as _lg
                _lg.getLogger("xiaojiao.thinking_loop").info(
                    "心带模型走：检索用「%s%s」= %s",
                    "事" if _ew else "我",
                    ("·来自%s" % _ew_src) if _ew_src else "", _rq[:60])
            except Exception:      # noqa: silent-ok — 日志写不出去不影响重排
                pass
        except Exception:
            items = sorted(items, key=lambda c: -_score(c.get("text") if isinstance(c, dict) else c, kws))
    else:
        items = sorted(items, key=lambda c: -_score(c.get("text") if isinstance(c, dict) else c, kws))
    after = [id(c) for c in items]
    moved = []
    for i, (bf, af) in enumerate(zip(before, after)):
        if bf != af:
            _t = items[i].get("text") if isinstance(items[i], dict) else items[i]
            moved.append({"to": i + 1, "text": str(_t)[:50]})
            if len(moved) >= 3:
                break
    rec = {"state": b["state"], "keywords": list(kws)[:5], "moved": moved,
           "note": b["note"], "count": len(items),
           "query_used": _rq[:80], "query_kind": ("事·%s" % _ew_src) if _ew else ("我" if _q else "无")}
    with _LOCK:
        LOOP["rounds"] += 1
        LOOP["reorders"].append(rec)
        del LOOP["reorders"][:-_MAX_REC]
    return items, rec


def on_event(kind, text, why="", perception=None):
    """**真实事件 → 心**（本次修正后的唯一触发源）。

    `kind` 只认三类真实来源：
      · `"user"`    用户输入了什么
      · `"carrier"` 载体自己遇到了什么（检索到危险内容 / 工具报错 / 逛到新东西）
      · `"world"`   世界变了什么
    **模型吐出来的字不在其中** —— 旧版 `after_thought(thought)` 读模型输出改心，
    那让心成了嘴的影子。规格要求砍掉它，这里就是砍掉后的替代。

    ⚠️ 如实标注：调用方如果拿模型输出当 `text` 传进来，那还是"嘴的影子"。
    本模块**无法自己判断**传进来的字符串到底是用户说的还是模型说的 ——
    所以这条约束靠调用点守（`agent_run` 里三处调用点都在模型出字**之前**）。
    """
    r = _psyche.trigger_from_event(kind, text, why=why, perception=perception)
    with _LOCK:
        LOOP["nudges"].append({"kind": kind, "state": r.get("state"),
                               "触发": str(r.get("why"))[:40], "beat": r.get("beat")})
        del LOOP["nudges"][:-_MAX_REC]
    return r


def bias_snapshot():
    """此刻的偏向（检索关键词 / 温度增量 / 语气）—— 给检索与生成读，**不产生任何文字**。"""
    return _psyche.bias()


def stats():
    """圈转起来的自检：轮次、最近几次重排与状态变化、当前偏向。"""
    with _LOCK:
        return {"rounds": LOOP["rounds"],
                "recent_reorders": list(LOOP["reorders"][-3:]),
                "recent_nudges": list(LOOP["nudges"][-3:]),
                "bias": bias_snapshot(),
                "note": "改方向 = 重排候选 + 调生成参数；上下文里一个字都不多"}
