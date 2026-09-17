# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 固化层（memory_deep 的第四层）
前三层住文件，这一层住权重。
不新造器官，是 memory_deep 三层的上一层。
"""
import json, os, threading, time
from .health import append_jsonl, read_jsonl
from . import memory_deep
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PATH = os.path.join(_ROOT, "logs", "psyche", "solidify.jsonl")
_LOCK = threading.RLock()
# 够格进固化的条件（都可配）
MIN_AGE_DAYS = 7         # fact 层里至少存在 7 天
MIN_HIT = 3              # 被命中过至少 3 次
SOLID_KINDS = None  # 已拆：载体不判类别
MAX_QUEUE = 50           # 待固化队列上限
def path(): return _PATH
# ---------- 判据：这条记忆该不该固化 ----------
def should_solidify(rec, now=None):
    """返回 (bool, 原因)。
    载体只判"事实"，不判"类别"：
      · 存在够久（事实）
      · 命中够多（事实）
    至于"该不该记住这条"，那是 user_profile 的事，不是这一层的事。
    """
    now = now or time.time()
    ts = float(rec.get("ts") or 0)
    if ts <= 0:
        return False, "没有时间戳"
    age_days = (now - ts) / 86400.0
    if age_days < MIN_AGE_DAYS:
        return False, f"存在 {age_days:.1f} 天，不足 {MIN_AGE_DAYS} 天"
    # 读 `hit_count`（**被召回几次**），不是 `said_count`：
    #   本层这一关的语义写在上面那句注释里 —— "被命中过至少 3 次"，问的是
    #   **这条记忆在真实对话里被用过几次**（用得多 = 稳 = 值得进权重），
    #   不是"用户强调过几次"。用户把同一句话说过三遍，不能证明它该固化。
    #   （拆计数时特意逐个看过：`MIN_HIT` 在这层只服务"召回频率"这一个语义，故保持不变。）
    hits = int(rec.get("hit_count") or 0)
    if hits < MIN_HIT:
        return False, f"命中 {hits} 次，不足 {MIN_HIT} 次"
    return True, "够格固化（时间+命中都达标）"


def check_conflict(new_rec, solidified, llm_fn=None):
    """【已拆】载体不判冲突。
    理由：判"两条信息顶不顶"是判断，不是事实。载体做判断 = 替模型决定，
    跟 user_profile 的原则冲突（判据由模型给，存储由载体执行）。
    改成：全部进队列，不判。矛盾留给"用的时候"——
    召回时如果拿到两条说法不同的，两条都摆到模型面前，让它自己看。
    """
    return False, None


def enqueue(rec, reason="够格固化"):
    """把一条记忆放进待固化队列。
    去重：相同 content 且 status=pending 的，不重复入队。
    上限：pending 已达 MAX_QUEUE，拒绝入队，返回 None。
    """
    content = rec.get("content") or rec.get("text")
    if not content:
        return None
    with _LOCK:
        rows = read_jsonl(_PATH)
        for r in rows:
            if r.get("status") == "pending" and r.get("content") == content:
                return r
        pending_n = sum(1 for r in rows if r.get("status") == "pending")
        if pending_n >= MAX_QUEUE:
            return None
        item = {
            "ts": rec.get("ts") or time.time(),
            "content": content,
            "kind": rec.get("kind") or rec.get("type"),
            "source_id": rec.get("id", ""),
            "reason": reason,
            "status": "pending",
            "solidified_at": None,
            "lora_path": None,
        }
        append_jsonl(_PATH, item)
        return item


def pending():
    rows = read_jsonl(_PATH)
    return [r for r in rows if r.get("status") == "pending"]
def mark_solidified(source_id, lora_path):
    """把某条标记为已固化（写了 LoRA）"""
    rows = read_jsonl(_PATH)
    for r in rows:
        if r.get("source_id") == source_id and r.get("status") == "pending":
            r["status"] = "solidified"
            r["solidified_at"] = time.time()
            r["lora_path"] = lora_path
    # 重写（队列小，整写可以）
    with _LOCK:
        tmp = _PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(tmp, _PATH)
def purge_stale(days=30, now=None):
    """清掉 pending 超过 N 天的条目。返回清掉的条数。
    不清已 solidified 的。
    """
    now = now or time.time()
    cutoff = now - days * 86400.0
    with _LOCK:
        rows = read_jsonl(_PATH)
        kept = []
        removed = 0
        for r in rows:
            if r.get("status") == "pending":
                ts = float(r.get("ts") or 0)
                if ts and ts < cutoff:
                    removed += 1
                    continue
            kept.append(r)
        if removed:
            tmp = _PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                for r in kept:
                    f.write(json.dumps(r, ensure_ascii=False) + chr(10))
            os.replace(tmp, _PATH)
        return removed
def stats():
    rows = read_jsonl(_PATH)
    return {
        "total": len(rows),
        "pending": sum(1 for r in rows if r.get("status")=="pending"),
        "solidified": sum(1 for r in rows if r.get("status")=="solidified"),
    }
# ---------- 来源标注（补元认知那半个） ----------
_SOURCES = {
    "solidified": "权重层",   # 写进 LoRA 的
    "fact": "长期记忆",       # memory_deep fact 层
    "expression": "长期记忆",
    "impression": "长期记忆",
    "conversation": "刚才对话", # 本轮上下文
    "learned": "我刚学的",    # 本轮新写入
}
def source_of(rec):
    """判断这条记忆来自哪——权重/长期/刚才/刚学"""
    # 1. 是不是已固化的
    if rec.get("source_id"):
        rows = read_jsonl(_PATH)
        for r in rows:
            if r.get("source_id") == rec["source_id"] and r.get("status") == "solidified":
                return "权重层"
    # 2. 是不是本轮的
    ts = float(rec.get("ts") or 0)
    if ts and (time.time() - ts) < 300:   # 5 分钟内算"刚"
        return "刚学的"
    # 3. 看 memory_deep 的层
    layer = rec.get("layer")
    if layer in _SOURCES:
        return _SOURCES[layer]
    # 4. 默认长期
    return "长期记忆"
def render_source(rec):
    """给模型看的"来源标签"——别让它以为所有记忆都一样"""
    src = source_of(rec)
    text = rec.get("content") or rec.get("text") or ""
    return f"[{src}] {text}"
