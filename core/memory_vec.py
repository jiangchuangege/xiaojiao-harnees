# -*- coding: utf-8 -*-
"""小焦 · 载体层 · 对话记忆向量库（无限 1：记忆无限）

定位：**所有历史对话永久留存到外部文件**，不占模型 ctx；要用的那一刻按需检索 top-K 注入。
硬盘多大就存多大（10 万条约 270MB），进程重启不丢。

存储：`logs/xiaojiao_memory_vec.jsonl` —— **一行一条、只追加**（append-only）。
      为什么是 JSONL 而不是一个 JSON 大对象：追加一条不必重写整个文件，
      10 万条时也不会出现"写到一半崩了整库报废"。
      向量用 **base64(float32 小端)** 存（2048 字节 → 2732 字符），比 JSON 浮点数组
      省 1/3 空间、且没有浮点文本精度损失；`text` 仍是明文，方便人肉排查。

检索：查询向量一次矩阵乘扫全库（numpy 快路径），20 条 ~2ms、10 万条也在几十 ms 内，
      满足"检索延迟 < 100ms"。没有 numpy 时退化为纯 Python 循环（慢但能用）。

硬隔离：**绝不读写 `self_learn/knowledge_vec.json`** —— 那是小脑的工具经验库（工具用法 +
      失败反思），对话记忆写进去会污染它。本模块启动时就把这条红线钉死。
"""
import base64
import json
import os
import struct
import threading
import time

from . import embedder

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_VS_PATH = os.path.join(_ROOT, "logs", "xiaojiao_memory_vec.jsonl")
_FORBIDDEN = os.path.abspath(os.path.join(_ROOT, "self_learn", "knowledge_vec.json"))

_DIM = embedder.DIM
_LOCK = threading.RLock()
_INDEX = {"loaded": False, "count": 0, "rows": [], "meta": [], "mat": None, "bad": 0}


# ------------------------------------------------------------------ 编码 / 解码
def _pack(vec):
    """512 个 float → base64（float32 小端，跨机器可读）。"""
    return base64.b64encode(struct.pack("<%df" % len(vec), *vec)).decode("ascii")


def _unpack(s):
    """base64 → list[float]；维度不对就返回 None（宁可丢这一条，也不污染索引）。"""
    raw = base64.b64decode(s.encode("ascii"))
    vals = list(struct.unpack("<%df" % (len(raw) // 4), raw))
    return vals if len(vals) == _DIM else None


# ------------------------------------------------------------------ 红线保护
def _assert_not_forbidden(path):
    """硬隔离：任何人想把库指到 knowledge_vec.json 都直接报错。"""
    if os.path.abspath(path) == _FORBIDDEN:
        raise RuntimeError(
            "禁止把对话记忆写进 %s —— 那是小脑的工具经验库（self_learn/knowledge_vec.json），"
            "两库必须隔离。" % _FORBIDDEN)


def path():
    """当前记忆库文件路径。"""
    _assert_not_forbidden(_VS_PATH)
    return _VS_PATH


# ------------------------------------------------------------------ 索引装载
def _try_numpy():
    try:
        import numpy as np
        return np
    except Exception:      # noqa: silent-ok — 没 numpy 就走纯 Python，功能不受影响
        return None


def _rebuild_matrix():
    """把 mem 里的行拼成 numpy 矩阵（快路径）。没有 numpy 就留 None。"""
    np = _try_numpy()
    if np is None or not _INDEX["rows"]:
        _INDEX["mat"] = None
        return
    _INDEX["mat"] = np.asarray(_INDEX["rows"], dtype="float32")


def reload():
    """从磁盘重建索引。返回装载条数。"""
    with _LOCK:
        rows, metas, bad = [], [], 0
        p = path()
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        vec = _unpack(rec.get("v") or "")
                    except Exception:
                        bad += 1
                        continue
                    if vec is None:
                        bad += 1
                        continue
                    rows.append(vec)
                    metas.append(rec)
        _INDEX.update({"loaded": True, "rows": rows, "meta": metas, "bad": bad,
                       "count": len(rows)})
        _rebuild_matrix()
        return len(rows)


def _ensure_loaded():
    if not _INDEX["loaded"]:
        reload()


# ------------------------------------------------------------------ 写入
def add_memory(text, kind="dialogue", entities=None, ts=None, meta=None, key_text=None):
    """向量化 + 追加到库。返回记录 id；text 为空则返回 "" 且不写。

    参数沿用 spec：add_memory(text, kind, entities)
      text     要长期记住的原文（对话轮次一般传「用户：… \\n 小焦：…」）
      kind     记忆类型：dialogue（对话）/ fact（明确事实）/ tool（工具结论）
      entities 相关实体（人名、地点、URL 等），只作元数据，检索不依赖它

    `key_text`（可选）：**拿什么去算向量**，默认就是 text。
    为什么需要它 —— 第 2 步实测踩到的坑：一轮对话的原文里，用户那句「我叫张三」很短，
    而小焦的回答又长又水（几百字寒暄）。均值池化是按长度加权的，于是"张三"这个信号
    被回答的水词淹掉，cos 掉到阈值以下 → 问「我叫什么」一条都检索不到（注入 0 条）。
    所以：**向量按「用户说了什么」算（key_text），注入时用完整原文（text）**。
    检索的本质就是"按用户问过的去找"，用户那句话才是索引键。
    """
    text = (text or "").strip()
    if not text:
        return ""
    vec = embedder.embed((key_text or text).strip() or text)
    if vec is None:
        return ""
    rec = {"id": "%d-%s" % (int(time.time() * 1000), os.urandom(3).hex()),
           "ts": float(ts if ts is not None else time.time()),
           "kind": kind or "dialogue",
           "entities": list(entities or []),
           "len": len(text),
           "text": text[:2000],
           "v": _pack(vec)}
    if key_text and key_text.strip() and key_text.strip() != text:
        rec["key"] = key_text.strip()[:400]     # 留一份索引键原文，便于人肉排查"为什么没检索到"
    if meta:
        rec["meta"] = meta
    with _LOCK:
        p = path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        _INDEX["rows"].append(vec)
        _INDEX["meta"].append(rec)
        _INDEX["count"] = len(_INDEX["rows"])
        _INDEX["loaded"] = True
        # 增量追加到矩阵（有 numpy 时）；否则清掉让它下次重建
        np = _try_numpy()
        if np is not None and _INDEX["mat"] is not None:
            try:
                _INDEX["mat"] = np.vstack([_INDEX["mat"], np.asarray([vec], dtype="float32")])
            except Exception:      # noqa: silent-ok — 拼不上就下次重建，别影响写入
                _INDEX["mat"] = None
        elif np is not None and len(_INDEX["rows"]) == 1:
            _rebuild_matrix()
    return rec["id"]


# ------------------------------------------------------------------ 检索
def search_memory(query, top_k=5, threshold=0.0, dedup_text=True):
    """按余弦相似度取最像的 top_k 条。

    返回 [{"id","text","kind","entities","ts","score"(原始余弦),"rank"}]，按 score 降序。
    **时间衰减不在这里做** —— 那是 retriever 的策略（阈值判"相关"，衰减只影响排序，
    这样"三年前说的那件事"不会被衰减掉出阈值，仍然检索得到）。
    """
    q = embedder.embed(query)
    if q is None:
        return []
    with _LOCK:
        _ensure_loaded()
        metas = _INDEX["meta"]
        if not metas:
            return []
        np = _try_numpy()
        out = []
        if np is not None and _INDEX["mat"] is not None:
            mat = _INDEX["mat"]
            qv = np.asarray(q, dtype="float32")
            sims = mat @ qv                              # 一次矩阵乘扫全库
            if top_k and top_k < len(sims):
                idx = np.argpartition(-sims, top_k)[:top_k * 3]
            else:
                idx = np.arange(len(sims))
            for i in idx:
                s = float(sims[i])
                if s >= threshold:
                    out.append((s, int(i)))
        else:                                            # 纯 Python 兜底
            for i, row in enumerate(_INDEX["rows"]):
                s = 0.0
                for a, b in zip(q, row):
                    s += a * b
                if s >= threshold:
                    out.append((s, i))
        out.sort(key=lambda z: -z[0])
        hits, seen = [], set()
        for s, i in out:
            m = metas[i]
            if dedup_text:
                key = (m.get("text") or "")[:120]
                if key in seen:
                    continue
                seen.add(key)
            hits.append({"id": m.get("id", ""), "text": m.get("text", ""),
                         "kind": m.get("kind", "dialogue"),
                         "entities": m.get("entities") or [], "ts": float(m.get("ts") or 0),
                         "score": round(s, 4), "rank": len(hits) + 1})
            if len(hits) >= max(1, int(top_k or 5)):
                break
        return hits


# ------------------------------------------------------------------ 统计 / 维护
def count():
    with _LOCK:
        _ensure_loaded()
        return _INDEX["count"]


def stats():
    """库的规模信息（面板/自检用）。"""
    with _LOCK:
        _ensure_loaded()
        p = path()
        size = os.path.getsize(p) if os.path.exists(p) else 0
        return {"count": _INDEX["count"], "bytes": size, "path": p,
                "bad_lines": _INDEX["bad"], "dim": _DIM,
                "backend": embedder.backend(), "matrix": _INDEX["mat"] is not None}


def forget_all():
    """清空记忆库（只给测试/用户显式重置用；日常没人会调它）。"""
    with _LOCK:
        p = path()
        if os.path.exists(p):
            os.remove(p)
        _INDEX.update({"loaded": True, "count": 0, "rows": [], "meta": [], "mat": None, "bad": 0})
