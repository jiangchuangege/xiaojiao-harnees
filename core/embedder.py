# -*- coding: utf-8 -*-
"""小焦 · 载体层 · 文本向量化（记忆无限的地基）

职责（载体优先）：把任意文本变成 **512 维** 向量。这一步**不依赖大脑**，只用小脑。

┌─ 主后端：小脑 MiniGPT 的 embed=512 ────────────────────────────────────────┐
│ 把字过完**整个编码器栈**（embedding + pos + 8 层 Transformer），再对序列做    │
│ 均值池化，最后 L2 归一化 —— 输出 512 维，与 model_config.json 的 embed_size  │
│ 一致。                                                                     │
│                                                                            │
│ 为什么不是"只用 nn.Embedding 那一层"（更贴 spec 字面）：实测同一批 20 条记忆， │
│   · 只用 embedding 层：rank-1 命中 4/5，gold 分 0.49~0.66，而无关项最高 0.52 │
│     —— 相关与无关几乎分不开；                                             │
│   · 过完编码器栈：    rank-1 命中 5/5，gold 分 0.72~0.85，无关项 ≤0.72      │
│     —— 区分度好得多。                                                      │
│ 两者都是 512 维，载体选**更能干活**的那个（载体优先）。                      │
└────────────────────────────────────────────────────────────────────────────┘

┌─ 兜底后端：字符 2/3-gram 哈希向量 ─────────────────────────────────────────┐
│ 小脑不可用（没装 torch / 没训模型 / 加载失败）时自动退化。与 self_learn/     │
│ vstore.py 同源思路，但固定 512 维，保证**库里的向量永远同维**。               │
│ 记忆功能绝不因为小脑缺失就整个瘫掉 —— 载体出错是载体的锅，不能把用户卡住。     │
└────────────────────────────────────────────────────────────────────────────┘

硬隔离：本模块**只读小脑权重**，绝不碰 self_learn/knowledge_vec.json
（那是小脑的工具经验库；把对话记忆写进去会污染它）。
"""
import hashlib
import math
import os
import sys
import threading

DIM = 512                      # 与 model_config.json 的 embed_size 对齐
_MAX_CHARS = 512               # 小脑 pos_embedding 只有 2048 位置，且长文本池化会糊；截断足够
_BACKEND = {"name": "", "model": None, "c2i": None, "tried": False, "reason": ""}
_LOCK = threading.Lock()

_SELF_TEST = {"text": "", "vec": None}


# ---------------------------------------------------------------- 小脑（主后端）
def _grab_brain():
    """拿到小脑 MiniGPT + char2idx。优先用 xiaojiao_app **已经加载好**的那份（不重复占内存）。

    返回 (model, char2idx)；拿不到返回 (None, None) 并记下原因。
    """
    # ① xiaojiao_app 模块级已经加载过（XJ_MODEL / XJ_C2I），直接借用 —— 零成本
    try:
        app = sys.modules.get("xiaojiao_app")
        if app is not None:
            m = getattr(app, "XJ_MODEL", None)
            c = getattr(app, "XJ_C2I", None)
            if m is not None and c:
                return m, c
    except Exception:      # noqa: silent-ok — 借不到就自己加载，不能因此中断
        pass
    # ② 自己加载一份（独立运行、或被别处 import 时）
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if root not in sys.path:
            sys.path.insert(0, root)
        import xiaojiao_harness as xh
        if os.path.exists(xh.MODEL_PATH) and os.path.exists(xh.VOCAB_PATH):
            model, c2i, _ = xh.load_model()
            return model, c2i
        _BACKEND["reason"] = "找不到小脑文件 %s / %s" % (xh.MODEL_PATH, xh.VOCAB_PATH)
    except Exception as e:
        _BACKEND["reason"] = "小脑加载失败：%s" % e
    return None, None


def _embed_minigpt(text, model, c2i):
    """过编码器栈 + 均值池化 → 512 维单位向量。返回 list[float] 或 None。"""
    import torch
    ids = [c2i.get(ch, 0) for ch in (text or "")][:_MAX_CHARS]
    if not ids:
        return None
    dev = getattr(model.embedding.weight, "device", "cpu")
    with torch.no_grad():
        t = torch.tensor([ids], dtype=torch.long, device=dev)
        pos = torch.arange(t.size(1), device=dev).unsqueeze(0)
        h = model.embedding(t) + model.pos_embedding(pos)
        n = t.size(1)
        mask = torch.triu(torch.ones(n, n, device=dev, dtype=torch.bool), diagonal=1)
        for layer in model.layers:
            h = layer(h, src_mask=mask)
        v = h.mean(dim=1).squeeze(0)
        v = v / (v.norm() + 1e-9)
    return [float(x) for x in v.detach().cpu().tolist()]


# ------------------------------------------------------- 哈希（兜底后端，512 维）
def _hash_bucket(s):
    """确定性哈希（跨进程稳定）：不能用 Python 内置 hash（PYTHONHASHSEED 会变）。"""
    return int(hashlib.md5(s.encode("utf-8")).hexdigest()[:8], 16) % DIM


def _embed_hash(text):
    """字符 2/3-gram 计数 → 512 维单位向量。"""
    t = (text or "").lower()
    if not t:
        return None
    v = [0.0] * DIM
    for n, w in ((2, 1.0), (3, 0.6)):
        for i in range(len(t) - n + 1):
            v[_hash_bucket(t[i:i + n])] += w
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


# ---------------------------------------------------------------------- 对外接口
def _resolve_backend():
    """确定后端（只做一次）。返回 'minigpt' 或 'hash'。"""
    if _BACKEND["tried"]:
        return _BACKEND["name"]
    with _LOCK:
        if _BACKEND["tried"]:
            return _BACKEND["name"]
        model, c2i = _grab_brain()
        if model is not None and c2i:
            _BACKEND["model"], _BACKEND["c2i"] = model, c2i
            _BACKEND["name"] = "minigpt"
            # 冒烟：真跑一次，跑不通就老实退到 hash（别等到检索时才炸）
            try:
                got = _embed_minigpt("小焦自检", model, c2i)
                if not got or len(got) != DIM:
                    raise RuntimeError("输出维度 %s != %d" % (len(got or []), DIM))
            except Exception as e:
                _BACKEND["name"] = "hash"
                _BACKEND["reason"] = "小脑前向失败：%s" % e
                _BACKEND["model"] = _BACKEND["c2i"] = None
        else:
            _BACKEND["name"] = "hash"
            _BACKEND.setdefault("reason", "小脑不可用")
        _BACKEND["tried"] = True
    return _BACKEND["name"]


def backend():
    """当前后端名（'minigpt' / 'hash'）。"""
    return _resolve_backend()


def reason():
    """退化到 hash 的原因（正常时为空串），便于排查。"""
    _resolve_backend()
    return _BACKEND.get("reason", "")


def embed(text):
    """文本 → 512 维单位向量（list[float]）。空文本返回 None。"""
    if not text or not str(text).strip():
        return None
    if _resolve_backend() == "minigpt":
        # 同一段文本反复问（检索时的 query、写入时的去重）不必重复前向
        if _SELF_TEST["text"] == text and _SELF_TEST["vec"] is not None:
            return list(_SELF_TEST["vec"])
        try:
            v = _embed_minigpt(str(text), _BACKEND["model"], _BACKEND["c2i"])
            if v:
                _SELF_TEST["text"], _SELF_TEST["vec"] = text, list(v)
                return v
        except Exception:
            pass          # 单次失败就退 hash，绝不把异常抛给调用方
    return _embed_hash(str(text))


def embed_many(texts):
    """批量向量化，顺序与入参一致（失败的为 None）。"""
    return [embed(t) for t in (texts or [])]


def dim():
    return DIM


def info():
    """自检用：后端 / 维度 / 退化原因。"""
    return {"backend": backend(), "dim": DIM, "reason": reason()}
