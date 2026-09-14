# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
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
_INDEX = {"loaded": False, "count": 0, "rows": [], "meta": [], "mat": None, "bad": 0,
           "parts": [], "pmat": None, "phas": None}


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
    # 多向量（首/中/尾）快路径：三条平行矩阵 + 一个"哪些行有多向量"的掩码。
    # 为什么要有掩码：没多向量的行在矩阵里是补零的，点积恒为 0；
    # 不掩码就会把这些行的分数**抬到 0**（原本可能是负分或低分），凭空制造命中。
    parts = _INDEX.get("parts") or []
    if len(parts) != len(_INDEX["rows"]):
        parts = [None] * len(_INDEX["rows"])
    has = np.zeros(len(parts), dtype=bool)
    pm = {}
    for name in ("head", "mid", "tail"):
        m = np.zeros((len(parts), _DIM), dtype="float32")
        for i, pp in enumerate(parts):
            if pp and pp.get(name):
                m[i] = pp[name]
                has[i] = True
        pm[name] = m
    _INDEX["pmat"], _INDEX["phas"] = pm, has


def reload():
    """从磁盘重建索引。返回装载条数。"""
    with _LOCK:
        rows, metas, parts, bad = [], [], [], 0
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
    else:
        # 【为什么无条件留 key】向量永远按 key 算（没给 key_text 就是 text）。
        # 不留下来 → 事后**没法按同一把键重建这条的向量**：
        #   `memory_deep.flush_index()` 要把"文件里有、索引里没有"的行补回索引，
        #   没有 key 就只能拿 text 重算，两条向量就会微妙地不一样（检索结果不稳定）。
        # 存下来=让"重建索引"这件事变成**可精确重放**的，代价只是每行多几十字节。
        rec["key"] = text[:400]
    # 多向量：首/中/尾各存一个（短文本只有一个 full，不写这个字段，行为与旧版一致）
    try:
        _parts = embedder.embed_parts((key_text or text).strip() or text)
        if _parts and "full" not in _parts:
            rec["vectors"] = {k: _pack(v) for k, v in _parts.items()}
    except Exception:      # noqa: silent-ok — 多向量算不出来不写，退回单向量（旧行为）
        pass
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


def ids():
    """当前索引里所有记忆的 id（给 `memory_deep.flush_index()` 对账用）。

    为什么要暴露这个：`reload()` 只保证"文件里已有的行"在索引里，
    但"先 `add_memory` 追加、再整体重写文件"这条路径上，重写可能把新行挤掉 ——
    于是出现"文件里有、搜不到"。对账需要先知道索引里到底有哪些 id。
    """
    with _LOCK:
        _ensure_loaded()
        return [m.get("id", "") for m in _INDEX["meta"]]


def reindex_row(rec):
    """把一条**已经存在于文件里**的记录补进内存索引（不写文件）。

    与 `add_memory` 的区别：不重新生成 id/时间戳、不写盘，只用记录里存的 `key`
    重算向量并挂上索引 —— 保证"补回来的"和"原本该有的"是同一把键算出来的。
    返回 True/False（算不出向量就 False，绝不抛错影响调用方）。
    """
    if not isinstance(rec, dict) or not rec.get("id"):
        return False
    vec = _unpack(rec.get("v") or "")
    if vec is None:
        vec = embedder.embed((rec.get("key") or rec.get("text") or "").strip())
    if vec is None:
        return False
    with _LOCK:
        _ensure_loaded()
        for m in _INDEX["meta"]:
            if m.get("id") == rec.get("id"):
                return True                     # 已在索引里，不重复挂
        _INDEX["rows"].append(vec)
        _INDEX["meta"].append(rec)
        _INDEX["count"] = len(_INDEX["rows"])
        np = _try_numpy()
        if np is not None and _INDEX["mat"] is not None:
            try:
                _INDEX["mat"] = np.vstack([_INDEX["mat"], np.asarray([vec], dtype="float32")])
            except Exception:      # noqa: silent-ok — 拼不上就下次整体重建
                _INDEX["mat"] = None
        return True


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
            # 多向量：整条的分与"首/中/尾"各段的分取最大 → 用哪一段查都能命中。
            pm = _INDEX.get("pmat")
            if pm:
                for nm in ("head", "mid", "tail"):
                    ps = pm[nm] @ qv
                    sims = np.where(_INDEX["phas"], np.maximum(sims, ps), sims)
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


def migrate_multivec(backup_dir=None, dry_run=False):
    """把库里每条记忆重算一次：`v`（整条向量）+ `vectors`（首/中/尾）。

    ① 为什么必须备份：这是**覆盖写**整个记忆库。写到一半崩了就是全库报废。
    ② 备份策略：整文件复制到 `logs/backup_before_multivec/<时间戳>/`，**只增不删**；
      已存在同名目录就换一个时间戳，绝不覆盖旧备份。
    ③ 只补不删：原有字段（id/text/kind/entities/ts/key）一律原样保留，只动 v 与 vectors。
    """
    import shutil
    import time as _t
    p = path()
    if not os.path.exists(p):
        return {"ok": False, "why": "库文件不存在", "total": 0, "done": 0}
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bdir = backup_dir or os.path.join(root, "logs", "backup_before_multivec",
                                      _t.strftime("%Y%m%d_%H%M%S"))
    rows = _all_rows_raw()
    total = len(rows)
    done = longn = 0
    out = []
    for r in rows:
        if not isinstance(r, dict):
            out.append(r)
            continue
        key = str(r.get("key") or r.get("text") or "").strip()
        if not key:
            out.append(r)
            continue
        v = embedder.embed(key)
        if not v:
            out.append(r)
            continue
        r = dict(r)
        r["v"] = _pack(v)
        parts = embedder.embed_parts(key)
        if parts and "full" not in parts:
            r["vectors"] = {k: _pack(x) for k, x in parts.items()}
            longn += 1
        else:
            r.pop("vectors", None)
        out.append(r)
        done += 1
    res = {"ok": True, "path": p, "total": total, "done": done, "long": longn,
           "dry_run": bool(dry_run)}
    if dry_run:
        return res
    os.makedirs(bdir, exist_ok=True)
    shutil.copy2(p, os.path.join(bdir, os.path.basename(p)))
    res["backup"] = bdir
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, p)
    reload()
    return res


def _all_rows_raw():
    """读原始行（解析不了的按原文保留）。"""
    p = path()
    out = []
    if not os.path.exists(p):
        return out
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:      # noqa: silent-ok — 坏行原样留着
                out.append(line)
    return out
