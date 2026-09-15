# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 电话通道（两条线程之间的双向通信）

【这段为什么这么设计】
    小焦同时活在两件事里：跟用户对话、自己在外面逛。这是**两条独立的线程**，
    各有各的状态机与上下文。它们需要互相说话：
      · 逛线程逛到一篇有意思的文章 → 想告诉对话线程"我看到个事"
      · 对话线程读了用户消息 → 想告诉逛线程"用户回来了，先别插话"

    "电话通道"就是这条线：一个**线程安全的双向队列**。为什么用打电话打比方 ——
    打电话时你随时能接、对方随时能说，但**同一时刻只有一个人说话**，
    接口不会因为对方正在说就打不进来。

【三个设计点】
    ① **必须加锁**：`queue.Queue` 本身是线程安全的，但"查一眼有没有消息再取"是
       两步操作，中间会被另一条线程插进来 —— 那就要一个额外的锁把复合操作护住。
    ② **有界**：队列不能无限长。逛线程跑一整天、对话线程一直没读，无界队列就是内存泄漏。
       满了就**丢最旧的**（旧消息的时效性已经没了，留着反而会让小焦说起陈年旧事）。
    ③ **分类投递**：分享（share）/ 提问（ask）/ 控制（ctl）分开，读的人可以只取自己关心的。

【去掉会怎样】
    两条线程就只能各干各的：逛到的有意思的东西永远说不出口，用户回来时逛线程还在闷头跑。
    "真并行"退化回"各跑各的"。
"""
import queue
import threading
import time

__all__ = ["put", "get", "peek", "drain", "counts", "kind_counts", "MAX_DEPTH", "clear"]

# 队列上限。满了丢最旧的（见设计点②）。
MAX_DEPTH = 64

# 消息类型
KIND_SHARE = "share"      # 逛线程 → 对话线程：我逛到什么了，要不要告诉用户
KIND_ASK = "ask"          # 逛线程 → 对话线程：我在想一件事，帮我看看
KIND_CTL = "ctl"          # 对话线程 → 逛线程：用户回来了 / 先别插话 / 继续逛
KIND_REPLY = "reply"      # 对话线程 → 逛线程：对某个 ask 的回答

_Q = queue.Queue(maxsize=MAX_DEPTH)
_LOCK = threading.Lock()
_DROPPED = {"n": 0}


def put(kind, content="", **kw):
    """往通道里放一条消息。**永不阻塞**：满了就丢最旧的，然后放新的。

    为什么是"丢最旧"而不是"丢新的"：新消息代表**此刻**的状态，旧消息已经过时了。
    小焦在用户面前说一句十分钟前的"我刚看到…"，比不说更奇怪。
    """
    msg = {"ts": time.time(), "kind": str(kind), "content": str(content or "")}
    msg.update(kw)
    with _LOCK:
        try:
            _Q.put_nowait(msg)
        except queue.Full:
            try:
                _Q.get_nowait()          # 丢最旧
                _DROPPED["n"] += 1
            except queue.Empty:          # noqa: silent-ok — 竞态下被别人取走了，忽略
                pass
            try:
                _Q.put_nowait(msg)
            except queue.Full:           # noqa: silent-ok — 极窄竞态，放不进去就算了
                pass
    return msg


def get(kind=None, timeout=0.0):
    """取一条消息；指定 `kind` 时只取那一类（别的放回去）。没有则返回 None。"""
    deadline = time.time() + max(0.0, float(timeout))
    while True:
        try:
            msg = _Q.get(timeout=max(0.0, deadline - time.time()))
        except queue.Empty:
            return None
        if kind is None or msg.get("kind") == kind:
            return msg
        # 不是要的类型：放回去，继续找（队列小，开销可忽略）
        with _LOCK:
            try:
                _Q.put_nowait(msg)
            except queue.Full:           # noqa: silent-ok
                pass
        if time.time() >= deadline:
            return None


def peek(kind=None):
    """看一眼**不取走**。用于"对话线程判断要不要提一句"，避免取走后又用不上、白丢一条。"""
    with _LOCK:
        items = list(_Q.queue)
    if kind is None:
        return items[0] if items else None
    for m in items:
        if m.get("kind") == kind:
            return m
    return None


def drain(kind=None, limit=100):
    """一次把消息都取出来（按时间序）。返回列表。"""
    out = []
    while len(out) < limit:
        m = get(kind=kind)
        if m is None:
            break
        out.append(m)
    return out


def counts():
    """通道现状：队列长度、上限、累计丢了多少条。"""
    with _LOCK:
        n = _Q.qsize()
    return {"depth": n, "max": MAX_DEPTH, "dropped": _DROPPED["n"]}


def kind_counts():
    """各类型的条数（自测与自检用）。"""
    with _LOCK:
        items = list(_Q.queue)
    out = {}
    for m in items:
        k = m.get("kind") or "?"
        out[k] = out.get(k, 0) + 1
    return out


def clear():
    """清空通道（自测用；正式流程里不清 —— 消息是两条线程之间的实时状态，不该被清掉）。"""
    with _LOCK:
        while True:
            try:
                _Q.get_nowait()
            except queue.Empty:
                break
