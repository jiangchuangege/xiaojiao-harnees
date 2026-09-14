# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 协同网络（阶段 B：中央状态 + 事件总线）

【这段为什么这么设计】
    模块单独看都还行，但用户感受到的"聪明"来自**模块互相加分**：
        好记忆 → 理解更准 → 推理更对 → 提取更精准 → 记忆更有用
           ↑                                              ↓
           └────── 表达更自然 ← 人格更立体 ←──────────────┘
    要让这条环转起来，必须有两个东西：
      ① **中央状态**：所有模块共享一份"现在这个任务进行到哪了"（阶段/事实/实体/工具轨迹/健康）。
         各模块写自己的那一片（命名空间），读别人的那一片 —— 不互相 import，不形成依赖网。
      ② **事件总线**：模块之间不直接调用，而是"广播我做了什么"，别人按需订阅。
         这样加模块不用改老模块（这才是"能力不封顶"的工程前提）。
    去掉它会怎样：每个模块各自为政，只有"独立能力"、没有"协同增益" ——
    也就是提示词里说的"不是每项都强的简单相加"。

【设计要点（都是踩过才有的取舍）】
    · **总线绝不阻塞生成**：订阅者抛异常必须被吞掉并**如实记进日志**（不能假装没发生，
      也不能让一个坏订阅者把整轮对话搞崩）。
    · **必须有传播深度上限**：A 的事件触发 B、B 又触发 A 就是死循环。
      取 4 层：正常的"记忆→推理→表达"链路最多 2~3 层，4 已经很宽松。
    · **环形缓冲 + 可选落盘**：内存里只留最近 N 条（默认 500），
      需要复盘时再开落盘（`logs/central/events.jsonl`），避免"每轮都写盘"拖慢对话。
    · **模块缺席不能算错**：`snapshot()` 对拿不到的模块如实标 `available=False`，
      不许编造 0 或假装正常（这是"绝假记忆"在系统层的同一条原则）。
"""
import json
import os
import sys
import threading
import time

from ..health import append_jsonl, read_jsonl

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 事件总线
_MAX_EVENTS = 500          # 内存环形缓冲上限（够复盘，不吃内存）
_MAX_DEPTH = 4             # 事件级联深度上限（防死循环）
_LOCK = threading.RLock()

_EVENTS = []               # [{ts, topic, payload, depth, seq}]
_SUBS = {}                 # topic -> [(fn, owner)]
_SEQ = [0]
_STATS = {"published": 0, "dropped": 0, "handler_errors": 0, "cascades": 0}
_PERSIST = [False]         # 默认不落盘（每轮写盘会拖慢对话），需要时 open_persist()
_STATE = {}                # 中央状态：namespace -> dict
_STATE_META = {}           # namespace -> {"ts", "owner"}


# ------------------------------------------------------------------ 中央状态
def set_state(namespace, **kv):
    """写自己命名空间下的一片状态（**只覆盖同名键**，不清别人的）。

    为什么是"合并"而不是"整体替换"：模块 A 写 `reasoning.step`、模块 B 写
    `reasoning.confidence`，如果 B 一写就把 A 的那片抹掉，协同就变成互相打架。
    """
    ns = str(namespace or "default")
    with _LOCK:
        cur = _STATE.setdefault(ns, {})
        cur.update(kv)
        _STATE_META[ns] = {"ts": time.time(), "keys": sorted(cur.keys())}
        return dict(cur)


def get_state(namespace=None, key=None, default=None):
    """读状态。`namespace=None` 返回整份快照的浅拷贝（给界面/自检看）。"""
    with _LOCK:
        if namespace is None:
            return {ns: dict(v) for ns, v in _STATE.items()}
        ns = _STATE.get(str(namespace))
        if ns is None:
            return {} if key is None else default
        if key is None:
            return dict(ns)
        return ns.get(key, default)


def clear_state(namespace=None):
    """清一个命名空间（或全部）。为什么要它：一轮任务结束要归零，
    否则上一轮的"阶段"会被下一轮读到 —— 那是最典型的串台。"""
    with _LOCK:
        if namespace is None:
            _STATE.clear()
            _STATE_META.clear()
        else:
            _STATE.pop(str(namespace), None)
            _STATE_META.pop(str(namespace), None)


def state_meta():
    """每个命名空间是谁在什么时候写的（排查"这数据谁写的"用）。"""
    with _LOCK:
        return {k: dict(v) for k, v in _STATE_META.items()}


# ------------------------------------------------------------------ 事件总线
def subscribe(topic, fn, owner=""):
    """订阅一个主题。返回**退订函数**（调用方拿它来反注册）。

    为什么返回退订函数而不是要求记住 (topic, fn)：模块重载/关闭时最容易漏反注册，
    漏了就是"死订阅者"——它会在下次事件里对着已销毁的状态报错。
    """
    if not callable(fn):
        raise TypeError("订阅者必须是可调用对象")
    t = str(topic)
    with _LOCK:
        _SUBS.setdefault(t, []).append((fn, str(owner or "")))

    def _unsubscribe():
        with _LOCK:
            lst = _SUBS.get(t) or []
            _SUBS[t] = [(f, o) for (f, o) in lst if not (f is fn and o == str(owner or ""))]
            if not _SUBS[t]:
                _SUBS.pop(t, None)
    return _unsubscribe


def subscribers(topic=None):
    """当前订阅情况（给自检/界面看，**如实列出 owner**）。"""
    with _LOCK:
        if topic is None:
            return {t: [o for _, o in lst] for t, lst in _SUBS.items()}
        return [o for _, o in (_SUBS.get(str(topic)) or [])]


def publish(topic, payload=None, _depth=0):
    """广播一个事件，同步调用订阅者。返回被调用的订阅者数量。

    ⚠️ 两条硬约束（见模块说明）：**订阅者异常必须吞掉并记账**；
    **级联深度超上限就停**（超了要如实统计到 `cascades`，不能装作没发生）。

    【为什么这么设计】发布出去的每一件事都是一次"别人可能关心的变化"，
    发布方**不该知道谁在听**（否则加一个模块就要改所有老模块）。
    而吞异常+记账是配套的：一个坏订阅者不能把整轮对话搞崩，
    但也不能悄悄消失 —— 否则"某模块一直在报错"这件事会永远没人发现。

    【去掉它会怎样】模块之间只能直接互相 import 调用：
    依赖网一旦成环就再也拆不开，加模块必须回头改老模块 ——
    "能力不封顶"在工程上就不成立了。
    """
    t = str(topic)
    with _LOCK:
        _SEQ[0] += 1
        ev = {"ts": time.time(), "topic": t, "payload": payload,
              "depth": int(_depth), "seq": _SEQ[0]}
        _EVENTS.append(ev)
        if len(_EVENTS) > _MAX_EVENTS:
            del _EVENTS[:len(_EVENTS) - _MAX_EVENTS]
        _STATS["published"] += 1
        if _depth > 0:
            _STATS["cascades"] += 1
        subs = list(_SUBS.get(t) or [])
        persist = _PERSIST[0]
    if _depth > _MAX_DEPTH:
        with _LOCK:
            _STATS["dropped"] += 1
        _safe_log_event(ev, "depth_exceeded")
        return 0
    if persist:
        _safe_log_event(ev, "")
    n = 0
    for fn, owner in subs:
        try:
            fn({"topic": t, "payload": payload, "depth": _depth, "ts": ev["ts"]})
        except Exception as e:      # noqa: silent-ok — 一个坏订阅者绝不能拖垮整轮对话
            with _LOCK:
                _STATS["handler_errors"] += 1
            _safe_log_event({"ts": time.time(), "topic": t, "payload": {"owner": owner,
                                                                       "error": str(e)[:200]}},
                            "handler_error")
        n += 1
    return n


def _safe_log_event(ev, tag):
    """落盘事件（只有 open_persist() 之后才走这里；写失败绝不能影响主流程）。"""
    try:
        rec = {"ts": ev.get("ts"), "topic": ev.get("topic"), "depth": ev.get("depth")}
        if tag:
            rec["tag"] = tag
        p = ev.get("payload")
        if isinstance(p, (str, int, float, bool)) or p is None:
            rec["payload"] = p
        else:
            rec["payload"] = json.dumps(p, ensure_ascii=False)[:500]
        append_jsonl(_events_path(), rec)
    except Exception:      # noqa: silent-ok — 事件落盘失败不影响业务
        pass


def open_persist(on=True):
    """开关事件落盘（默认关）。"""
    _PERSIST[0] = bool(on)
    return _PERSIST[0]


def recent(n=50, topic=None):
    """最近 n 条事件（可按主题过滤）。"""
    with _LOCK:
        evs = list(_EVENTS)
    if topic is not None:
        evs = [e for e in evs if e["topic"] == str(topic)]
    return evs[-max(1, int(n)):]


def bus_stats():
    with _LOCK:
        return dict(_STATS, buffered=len(_EVENTS), topics=len(_SUBS),
                    subscribers=sum(len(v) for v in _SUBS.values()),
                    persist=_PERSIST[0], max_depth=_MAX_DEPTH)


def reset_bus():
    """清空缓冲/统计（**不删订阅者**）。给测试与"新一轮任务"用。"""
    with _LOCK:
        _EVENTS.clear()
        for k in ("published", "dropped", "handler_errors", "cascades"):
            _STATS[k] = 0


# ------------------------------------------------------------------ 落盘位置
def _dir():
    d = os.path.join(_ROOT, "logs", "central")
    os.makedirs(d, exist_ok=True)
    return d


def _events_path():
    return os.path.join(_dir(), "events.jsonl")


# ------------------------------------------------------------------ 模块健康 / 快照
# 哪些模块算"器官"。这里**不 import 任何模块**（import 会形成依赖网、还会拖慢启动），
# 只检查"文件在不在、能不能 import" —— 要的是"缺席要如实说"，不是"必须全都在"。
MODULES = (
    ("memory_vec", "core.memory_vec", "记忆向量库"),
    ("memory_deep", "core.memory_deep", "记忆深度（事实/表达/印象）"),
    ("retriever", "core.retriever", "记忆检索"),
    ("continuation", "core.continuation", "输出无限（无缝续写）"),
    ("input_splitter", "core.input_splitter", "输入无限（切片）"),
    ("health", "core.health", "健康系统"),
    ("autonomy", "core.autonomy", "自主性"),
    ("world", "core.world", "世界层"),
    ("carrier", "core.carrier", "变形金刚（火种/能力）"),
    ("security", "core.security", "安全（删除红线）"),
    ("metacognition", "core.metacognition", "元认知"),
    ("persona", "core.persona", "人格层"),
    ("boost", "core.boost", "极限补刀 7 项"),
)


def module_status(only=False):
    """逐个模块探活。返回 {name: {"available", "cn", "error"?}}。

    ⚠️ 这里**故意不抛任何异常**：某个模块坏了只影响它自己那一行，
    绝不能因为"探活"把调用方（可能是一轮对话）搞崩。
    `only=True` 只返回 available=True 的（给界面显示"当前有哪些能力"）。
    """
    out = {}
    for name, mod, cn in MODULES:
        st = {"available": False, "cn": cn}
        try:
            if mod in sys.modules:
                st["available"] = True
            else:
                __import__(mod)
                st["available"] = True
        except Exception as e:      # noqa: silent-ok — 模块缺席要如实标，不能编造
            st["error"] = "%s: %s" % (type(e).__name__, str(e)[:120])
        out[name] = st
    if only:
        return {k: v for k, v in out.items() if v.get("available")}
    return out


def snapshot():
    """整份系统快照（给界面/自检/报告用）。**全部是真实读到的值**。

    【为什么这么设计】这是"现在系统是什么状态"的**唯一**权威出口：
    界面、自检、报告都读它。所以它必须做到两件事 ——
    ① 拿得到的就如实给（模块在线数、中央状态、总线统计）；
    ② 拿不到的就**如实标缺**（`available=False` + error），绝不用 0 或"正常"糊过去。
    这与"绝假记忆"是同一条原则在系统层的体现：**不知道就说不知道**。

    【去掉它会怎样】每个消费方各自去 `sys.modules` 里翻、各自判断模块在不在，
    于是同一时刻三个地方报出三种"系统状态"，而用户看到的那个报表永远不可信。
    """
    mods = module_status()
    return {
        "ts": time.time(),
        "modules": mods,
        "modules_available": sum(1 for v in mods.values() if v.get("available")),
        "modules_total": len(mods),
        "state": get_state(),
        "state_meta": state_meta(),
        "bus": bus_stats(),
        "recent_events": [{"ts": e["ts"], "topic": e["topic"], "depth": e["depth"]}
                          for e in recent(20)],
    }


def summary():
    """一句中文概括（**带真实数字**；拿不到就说拿不到，不许编）。"""
    s = snapshot()
    return ("%d/%d 个器官在线；中央状态 %d 个命名空间；事件总线：publish %d 次、"
            "订阅者 %d 个、处理异常 %d 次、级联 %d 次。"
            % (s["modules_available"], s["modules_total"], len(s["state"]),
               s["bus"]["published"], s["bus"]["subscribers"],
               s["bus"]["handler_errors"], s["bus"]["cascades"]))


def read_events(days=None, limit=200):
    """读落盘的事件（没开落盘就返回空表 —— 如实，不编）。"""
    try:
        return read_jsonl(_events_path(), days=days, limit=limit)
    except Exception:      # noqa: silent-ok — 读不到按"没有"处理
        return []
