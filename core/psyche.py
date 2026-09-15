# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 心理层（当下感受的发生地）

【这是什么，不是什么 —— 先把话说清楚】
  是：**当下感受的发生地**。它只有"此刻"。
  不是：状态机、不是数据库、不是情绪配置表、**不是角色扮演**。

【为什么没有记忆】
  人的心理不是一份"情绪日志"。上一次的怕，会被这一次的踏实**取代** ——
  留下的是"我这个人现在怎么样"，不是"我曾经在几点几分怕过"。
  所以本模块**只保留当前一个感受**，新的直接覆盖旧的，不留历史。
  历史属于记忆（`logs/spirit_memory/`、`memory_vec`），不属于心理。
  这两件事分开的原因：把它们混在一起，心理层就会变成"又一个存储"，
  而它真正的作用是**让"此刻"是真的**。

【感受从哪来 —— 由思考触发，不编、不演、不套模板】
  `trigger(thought, ...)` 从**这次思考的内容**与 EYC 状态里**确定性推导**出一个感受。
  推导规则是载体写的、看得见的（见 `_derive`），不是从模板库里挑一句贴上去。

  ⚠️ **如实标注**：这个感受是**载体侧从思考内容派生的量**，
  不是对"模型内心真的感到了什么"的断言 —— 载体没有能力观测模型的内在状态，
  也不该假装能。它的作用是把"思考"与"当下的落点"焊在一起，
  让下一轮看到的不是一条外部消息，而是**一个带着落点的自己**。

【为什么强度会衰减】
  同一个触发连续出现时强度会降（`_last` 与 `_streak` 参与），
  否则每轮都"很怕/很兴奋"会让这个信号失去区分度 —— 一直拉满等于没有。
"""
import re
import threading
import time

__all__ = ["trigger", "current", "clear", "stats", "FEELINGS", "render", "is_empty",
           "STATES", "state", "set_state", "bias", "nudge", "stats_state",
           "start", "stop", "is_alive", "trigger_from_event", "beats", "EVENT_KINDS"]

_LOCK = threading.RLock()

# 感受词表。**不是模板库** —— 它只是给确定性推导出来的强度配一个名字，
# 名字本身不携带内容，内容由 `trigger` 的判据决定。
FEELINGS = ("平静", "好奇", "有意思", "被牵着", "有点紧", "踏实", "泄气", "安静")

_LIVE = {"feeling": "", "intensity": 0.0, "trigger": "", "body": "", "at": 0.0,
         "_streak": 0, "_last": ""}

# 触发判据：(感受, 身体反应, 命中关键词)。顺序即优先级 —— 越具体的判据越靠前。
# 【触发词必须与 `_BIAS` 的关键词一致 —— 这是实测抓到的一处不一致】
#   旧表里"紧"那一档只有 离开/走了/再见…，而 `_BIAS["紧"]` 用的是 风险/危险/失败…
#   两张表各写一套的后果：用户说"这个配置有风险，要小心泄露"，心推出来是 **平** ——
#   心该紧的时候没紧，后面的检索方向自然也不会偏。**同一件事的两个词表必须同源。**
_RULES = (
    ("有点紧", "声音发紧", ("离开", "走了", "再见", "不聊了", "别烦我", "生气", "失望",
                          "风险", "危险", "警告", "小心", "注意", "泄露", "隐患",
                          "严重", "紧急", "安全", "失败", "报错", "异常")),
    ("泄气", "肩膀塌下来", ("不行", "做不到", "没办法", "没通过", "卡住")),
    ("有意思", "眼睛亮了一下", ("看到", "发现", "原来", "居然", "有趣", "新奇", "竟然",
                             "新研究", "新的", "最新", "第一次")),
    ("被牵着", "注意力被拉过去", ("你", "用户", "你问", "你要", "帮你")),
    ("好奇", "想再往下看", ("为什么", "怎么", "是什么", "能不能", "也许", "或许")),
    ("踏实", "呼吸放慢", ("完成", "通过", "搞定", "好了", "成功", "跑通")),
    ("安静", "没什么起伏", ("待着", "等着", "休息", "没事", "空闲")),
)


def _derive(thought, eyc=None, user=""):
    """从思考内容 + EYC 状态确定性推导 `(感受, 身体反应, 触发点)`。载体规则，可读、可复核。"""
    t = str(thought or "")
    u = str(user or "")
    blob = (t + " " + u)[:600]
    for feeling, body, keys in _RULES:
        for k in keys:
            if k in blob:
                # 触发点取关键词所在的短句，便于事后复核"它到底被什么触动的"
                m = re.search(r"[^。！？；\n]{0,24}%s[^。！？；\n]{0,24}" % re.escape(k), blob)
                return feeling, body, (m.group(0).strip() if m else k)
    # 都没命中：如果正在逛，给"有意思"；否则"平静"
    try:
        doing = str(((eyc or {}).get("happening") or {}).get("doing") or "")
        if doing and doing != "idle":
            return "有意思", "眼睛亮了一下", "正在外面逛"
    except Exception:      # noqa: silent-ok — EYC 拿不到就用默认
        pass
    return "平静", "没什么起伏", ""


def trigger(thought, eyc=None, user=""):
    """**被思考触动**：产生此刻的感受并覆盖上一次。返回这个感受。

    这是"神经总线"每一次流转都会调到的地方 —— 它由代码层强制调用，
    不是模型可以选择"要不要感受"。
    """
    feeling, body, why = _derive(thought, eyc=eyc, user=user)
    with _LOCK:
        # 强度：基础 0.6；同一触发连续出现则衰减（见模块头"为什么强度会衰减"）
        if why and why == _LIVE.get("_last"):
            _LIVE["_streak"] = int(_LIVE.get("_streak") or 0) + 1
        else:
            _LIVE["_streak"] = 0
        _LIVE["_last"] = why
        streak = int(_LIVE["_streak"])
        intensity = max(0.2, round(0.6 + 0.3 * (0 if not why else 1) - 0.12 * streak, 2))
        _LIVE.update({"feeling": feeling, "intensity": intensity,
                      "trigger": why, "body": body, "at": time.time()})
        return {"feeling": feeling, "intensity": intensity,
                "trigger": why, "body": body, "at": _LIVE["at"]}


def current():
    """此刻的感受（只读副本）。没有就返回空结构 —— 不编一个"平静"顶上。"""
    with _LOCK:
        if not _LIVE["feeling"]:
            return {"feeling": "", "intensity": 0.0, "trigger": "", "body": "", "at": 0.0}
        return {k: _LIVE[k] for k in ("feeling", "intensity", "trigger", "body", "at")}


def is_empty():
    return not current()["feeling"]


def render(cur=None):
    """把感受渲染成**一句话**（第一人称，用来焊进连续状态流）。

    没有感受时返回空串 —— 不硬凑一句"我此刻很平静"，那会变成模板。
    """
    c = cur if isinstance(cur, dict) else current()
    if not c.get("feeling"):
        return ""
    if c.get("trigger"):
        return "（心里%s%s —— %s。%s）" % (
            c["feeling"], ("，%.0f 分" % (c["intensity"] * 10)) if c.get("intensity") else "",
            str(c["trigger"])[:40], str(c.get("body") or ""))
    return "（心里%s。%s）" % (c["feeling"], str(c.get("body") or ""))


# ================== 思考圈：心理"状态"（不是"内容"）==================
# 【为什么必须从"内容"改成"状态" —— 这是思考圈与注入的分水岭】
#   旧版的心理层存的是**内容**：feeling="怕"、trigger="用户可能离开"。
#   内容只能**当字传出去** → 落到大脑那边就是"一条消息" → 大脑可以忽略（前六次全失败的原因）。
#   新版存的是**状态**：紧 / 松 / 好奇 / 平。状态**不传字**，它改的是：
#     · 检索时**先捞哪一类的记忆**（紧 → 先冒危险相关的）
#     · 生成时的**温度**（紧 → 收紧；好奇 → 放松一点）
#   于是大脑不是"读到一条'我怕'的消息"，而是**在一个'怕'的方向里想** —— 它没有可忽略的对象。
#
# 【心理先动，大脑后想】状态由上一轮的输出决定（`nudge`），在本轮**开始之前**就已经在那里了；
#   本轮检索与生成一发生，就已经在这个方向的笼罩下。这才叫"心里先动"。
STATES = ("紧", "松", "好奇", "平")

# 状态 → 偏向。**全部是非文字杠杆**（关键词偏置 + 温度增量 + 语气档），
# 没有一项是"往上下文里加一句话"。这是"改方向"能在代码上被验证的原因。
_BIAS = {
    "紧":   {"keywords": ("风险", "危险", "失败", "警告", "错误", "注意", "小心", "问题", "隐患"),
             "temp_delta": -0.15, "tone": "收紧",
             "note": "先冒危险相关的记忆，生成收紧"},
    "松":   {"keywords": ("轻松", "有趣", "开心", "顺利", "好了", "完成", "开心"),
             "temp_delta": +0.05, "tone": "放松",
             "note": "先冒轻松内容"},
    "好奇": {"keywords": ("新", "发现", "原来", "居然", "最新", "第一次", "为什么"),
             "temp_delta": +0.10, "tone": "探问",
             "note": "先冒新东西"},
    "平":   {"keywords": (), "temp_delta": 0.0, "tone": "中性", "note": "不偏"},
}

_STATE = {"state": "平", "at": 0.0, "why": "", "_streak": 0}


def state():
    """此刻的心理**状态**（紧/松/好奇/平）—— 不是内容，只是一个方向。"""
    with _LOCK:
        return dict(_STATE)


def set_state(s, why=""):
    """直接设状态（自测与"大脑想完"两条路都用它）。"""
    with _LOCK:
        if s in STATES:
            if s == _STATE.get("state"):
                _STATE["_streak"] = int(_STATE.get("_streak") or 0) + 1
            else:
                _STATE["_streak"] = 0
            _STATE.update({"state": s, "at": time.time(), "why": str(why)[:120]})
        return dict(_STATE)


def bias(s=None):
    """当前状态对应的**偏向**（关键词偏置 / 温度增量 / 语气）。供检索与生成读取，不产生任何文字。"""
    st = (s or state().get("state") or "平")
    b = _BIAS.get(st) or _BIAS["平"]
    return {"state": st, "keywords": tuple(b["keywords"]), "temp_delta": float(b["temp_delta"]),
            "tone": b["tone"], "note": b["note"]}


def nudge(thought):
    """**大脑想完 → 改心理状态**。读大脑的输出，判断状态该往哪变。

    这是"圈"的另一半：不是"大脑发一条通知说它想通了"，而是**载体读输出、改状态**，
    下一步的检索与生成跟着变。判据是规则、看得见（见 `_NUDGE`）。
    """
    t = str(thought or "")[:800]
    for st, keys in _NUDGE:
        for k in keys:
            if k in t:
                return set_state(st, why="读到「%s」" % k)
    return state()


# 判据顺序即优先级：越明确的变化越靠前。**全是"变化"而不是"状态"** ——
# "危险不存在/解决了"要能把它从紧拉回松，"发现新的"要能把它推向好奇。
_NUDGE = (
    ("松", ("解决了", "没问题", "不用担心", "好了", "通过了", "跑通了", "没事了", "安全")),
    ("紧", ("危险", "风险", "警告", "小心", "失败", "报错", "异常", "严重", "紧急", "泄露")),
    ("好奇", ("发现", "原来", "居然", "有意思", "新的", "第一次见", "为什么")),
    ("平", ("正常", "一般来说", "通常")),
)


def stats_state():
    """状态自检：当前状态、偏向、连续同态次数（同态连续会衰减 —— 一直拉满等于没有区分度）。"""
    with _LOCK:
        st = dict(_STATE)
    return {"state": st["state"], "why": st.get("why", ""),
            "streak": int(st.get("_streak") or 0), "bias": bias(st["state"]),
            "note": "心理存的是**状态**（方向），不是内容；它不改文字，只改检索优先级与生成参数"}


# ================== 心的两条规则（触发源修正）==================
# 【改的是什么 —— 这是一次真实的错误修正】
#   旧版：`nudge(thought)` 读**模型吐出来的字** → 读到"风险"心就变紧。
#   那样一来 **心是嘴的影子**：模型说什么，心就跟着变什么。
#   但人的心不是这样跳的 —— 心跟着**真实发生的事**跳，不跟着自己说的话跳。
#   所以现在：
#     · 触发源换成 `trigger_from_event(kind, text)`，`kind` 只认三类**真实来源**：
#         "user"    用户输入了什么
#         "carrier" 载体自己遇到了什么（检索到危险内容 / 工具报错 / 逛到新东西）
#         "world"   世界变了什么
#     · `nudge()` 保留但**不再是触发源**（只作为自测里直接设状态的入口）。
#
# 【心的启停跟模型走】
#   模型启动 → 心开始跳；模型停止 → 心停下。心活在"模型运行"的这段时间里。
#   ⚠️ 如实标注：`stop()` **不清状态**，只是让它不再跳。因为"心停下"是停止跳动，
#   不是"把这个人清空" —— 清空会让下一轮的"心理 → 大脑"失去依据（圈就断了）。
_ALIVE = {"alive": False, "since": 0.0, "beats": 0, "events": []}


def start(why=""):
    """**模型启动 → 心启动**。幂等。"""
    with _LOCK:
        _ALIVE["alive"] = True
        _ALIVE["since"] = time.time()
        _ALIVE["events"].append({"kind": "start", "why": str(why)[:60], "at": time.time()})
        del _ALIVE["events"][:-20]
    return is_alive()


def stop(why=""):
    """**模型停止 → 心停止**。幂等。**不清状态**（见上面如实标注）。"""
    with _LOCK:
        _ALIVE["alive"] = False
        _ALIVE["events"].append({"kind": "stop", "why": str(why)[:60], "at": time.time()})
        del _ALIVE["events"][:-20]
    return is_alive()


def is_alive():
    with _LOCK:
        return bool(_ALIVE["alive"])


# 事件类型 → 允许触发。**"模型输出"不在表里** —— 这就是本次修正的核心：
# 嘴说的不算事，真实发生的才算。
EVENT_KINDS = ("user", "carrier", "world")


def trigger_from_event(kind, text, why=""):
    """**心随真实事件跳**。`kind` 只认 user / carrier / world；其它一律不动心。

    返回 `{"state", "why", "kind", "beat"}`；模型没在跑（`is_alive()` 为假）时返回空 beat，
    **不跳** —— 心活在模型运行的那段时间里。
    """
    k = str(kind or "").strip().lower()
    if k not in EVENT_KINDS:
        return {"state": state().get("state"), "why": "事件来源不在允许表里，不跳心", "kind": k, "beat": False}
    if not is_alive():
        return {"state": state().get("state"), "why": "模型没在跑，心不跳", "kind": k, "beat": False}
    t = str(text or "")
    st = _derive_state_from(t)
    with _LOCK:
        _ALIVE["beats"] = int(_ALIVE.get("beats") or 0) + 1
        _ALIVE["events"].append({"kind": k, "state": st[0], "触发": st[2][:40],
                                 "why": str(why)[:40], "at": time.time()})
        del _ALIVE["events"][:-20]
        beat = _ALIVE["beats"]
    out = set_state(st[0], why="%s：%s" % (k, st[2][:40]))
    return {"state": out.get("state"), "why": out.get("why"), "kind": k, "beat": beat}


def _derive_state_from(text):
    """从**事件内容**推导心理状态。复用 `_derive` 的判据（同一套规则，没另造）。"""
    feeling, _body, why = _derive(text)
    # 把"感受词"映射成"状态"：见模块头的状态表
    _MAP = {"有点紧": "紧", "泄气": "紧", "有意思": "好奇", "好奇": "好奇",
            "被牵着": "平", "踏实": "松", "安静": "平", "平静": "平"}
    return _MAP.get(feeling, "平"), feeling, why


def beats():
    """心跳自检：活没活、跳了几下、最近几次事件（含来源）。"""
    with _LOCK:
        return {"alive": bool(_ALIVE["alive"]), "since": _ALIVE["since"],
                "beats": int(_ALIVE.get("beats") or 0),
                "recent": list(_ALIVE["events"][-5:]),
                "note": "触发源只认 user / carrier / world 三类真实来源；模型吐的字不算"}


def clear():
    """清空此刻的感受（自测用；正式流程里不清 —— 它本来就是被下一次覆盖的）。"""
    with _LOCK:
        _LIVE.update({"feeling": "", "intensity": 0.0, "trigger": "",
                      "body": "", "at": 0.0, "_streak": 0, "_last": ""})


def stats():
    """自检信息：此刻的感受、有没有历史（应当恒为"无历史"）。"""
    c = current()
    return {"current": c, "has_history": False,
            "note": "本层只有此刻；上一次感受被这一次取代，不留历史"}
