# -*- coding: utf-8 -*-
"""小焦 · 载体层 · 大输入切片（无限 2：输入无限）

问题：用户能贴任意长度的内容（10 万字文章、50 万字报告），但模型单次只装得下 2 万 token。
载体解法：**载体负责切片、循环、落盘、拼装**；模型每次只处理"当前这一片"。
用户看到的是"完整总结"，实际是循环了 N 次 —— 但用户看不到 N，只看到"正在处理"。

切片的硬要求（照 spec）：
  · 按**段落边界**切，**绝不切在句中**（半句单独喂模型，它会当成残缺输入去猜）；
  · 段落本身超长 → 退到句边界；单句还超长（罕见）→ 才硬切，并如实记一笔；
  · 每片保持语义完整 —— 一段完整的话比"刚好凑满 5000 token"重要得多。
"""
import os
import re
import time

_SENT_SPLIT = re.compile(r"(?<=[。！？!?；;…])")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CHUNK_DIR = os.path.join(_ROOT, "logs", "_chunks")

DEFAULT_MAX_CHUNK = 5000        # 单片 token 上限（spec 指定）


def _estimate(text):
    """与 xiaojiao_app._estimate_tokens 同口径；借不到就本地等价式。"""
    try:
        import sys
        app = sys.modules.get("xiaojiao_app")
        if app is not None and hasattr(app, "_estimate_tokens"):
            return int(app._estimate_tokens(text))
    except Exception:      # noqa: silent-ok — 借不到就本地算，口径一致
        pass
    t = str(text or "")
    if not t:
        return 0
    cjk = sum(1 for ch in t if "\u4e00" <= ch <= "\u9fff")
    return int(cjk * 1.5 + (len(t) - cjk) / 3) + 1


def split_paragraphs(text):
    """按空行/换行切段（保留非空段）。"""
    parts = re.split(r"\n\s*\n|\n", text or "")
    return [p.strip() for p in parts if p.strip()]


def _hard_split(text, max_tokens):
    """最后一道保险：按字符比例硬切（片内实在找不到句/段边界时用）。

    留 **0.85** 的余量：字符数→token 是线性估计，边界上会差几个 token。
    实测（第 4 步单测抓到的）：不留余量时切出来 5010 > 5000 —— 差一点点也是超。
    """
    text = text or ""
    if _estimate(text) <= max_tokens:
        return [text]
    per = max(50, int(len(text) * max_tokens / max(1, _estimate(text)) * 0.85))
    return [text[i:i + per] for i in range(0, len(text), per)]


def _split_oversize(para, max_tokens):
    """单段超长 → 先按句切、再按硬长度切。返回 [str]。"""
    out = []
    for sent in _SENT_SPLIT.split(para):
        if not sent:
            continue
        if _estimate(sent) <= max_tokens:
            out.append(sent)
        else:
            out.extend(_hard_split(sent, max_tokens))
    return out


def split_input(text, max_chunk=DEFAULT_MAX_CHUNK):
    """把长文本切成若干片，每片 ≤ max_chunk token，且**不切在句中**。

    返回 [str]（原样返回单片的情况最常见：短输入不切片）。
    """
    text = text or ""
    max_chunk = max(200, int(max_chunk or DEFAULT_MAX_CHUNK))
    if _estimate(text) <= max_chunk:
        return [text] if text.strip() else []
    units = []
    for para in split_paragraphs(text):
        if _estimate(para) <= max_chunk:
            units.append(para)
        else:
            units.extend(_split_oversize(para, max_chunk))
    # 粘合开销必须算进去：每多粘一段就多一个 "\n\n"。
    # 第 4 步单测实测：只累加各段自己的 token，拼出来会超（sum=4988 → 实际 5003）。
    sep_tok = max(1, _estimate("\n\n"))
    chunks, cur, cur_tok = [], [], 0
    for u in units:
        t = _estimate(u)
        if cur and cur_tok + sep_tok + t > max_chunk:
            chunks.append("\n\n".join(cur))
            cur, cur_tok = [], 0
        if cur:
            cur_tok += sep_tok
        cur.append(u)
        cur_tok += t
    if cur:
        chunks.append("\n\n".join(cur))
    # 兜底校验：任何一片仍然超限就硬切（保证"每片都装得下"这个不变量）
    fixed = []
    for c in chunks:
        if _estimate(c) <= max_chunk:
            fixed.append(c)
        else:
            fixed.extend(_hard_split(c, max_chunk))
    return fixed


def split_task(text, max_chunk=DEFAULT_MAX_CHUNK):
    """把"指令 + 一大坨内容"分开，并只对内容切片。

    返回 (instruction, [片])。

    判据（载体启发式，够用且可解释）：第一段很短（≤ 200 字）且总段数 ≥ 3 时，
    认为第一段是**用户的要求**（"帮我总结一下""提炼要点"），后面才是待处理内容。
    这样每片都能带着同一条要求去处理，而不是把要求也切碎。
    找不到明显指令时，用一句通用要求兜底。
    """
    text = text or ""
    paras = split_paragraphs(text)
    instr = ""
    if len(paras) >= 3 and _estimate(paras[0]) <= 200:
        instr = paras[0]
        body = "\n\n".join(paras[1:])
    elif len(paras) >= 2 and len(paras[0]) <= 60:
        instr = paras[0]
        body = "\n\n".join(paras[1:])
    else:
        body = text
    if not instr:
        instr = "请完整、如实地处理下面这段内容，不要遗漏要点。"
    return instr, split_input(body, max_chunk)


def save_chunk(index, text, tag=""):
    """每一片的产出落到 logs/_chunks/（外部存储：进度不丢、可核对、可续跑）。

    `logs/_chunks/` 已随 `logs/` 一起被 .gitignore 忽略 —— 那是运行产物，不入库。
    """
    try:
        os.makedirs(_CHUNK_DIR, exist_ok=True)
        fn = os.path.join(_CHUNK_DIR, "%s_%04d%s.txt"
                          % (time.strftime("%Y%m%d_%H%M%S"), index, ("_" + tag) if tag else ""))
        with open(fn, "w", encoding="utf-8") as f:
            f.write(text or "")
        return fn
    except Exception:      # noqa: silent-ok — 落盘失败不影响处理
        return ""


def merge_outputs(parts, joiner="\n\n"):
    """把各片产出拼装成一份结果。

    拼装时**再做一次去重**：模型处理相邻两片时会把上一片结尾的结论又复述一遍，
    直接拼会出现重复段落（和第 3 步续写的接缝问题是同一类）。
    去重手法沿用 core/continuation.py 的那套：整句去重（跨片累积）。
    """
    from . import continuation as _c
    seen, out = set(), []
    for p in (parts or []):
        if not p or not p.strip():
            continue
        cleaned, _ = _c.drop_repeated_sentences(p, seen)
        body = cleaned.strip()
        if body:
            out.append(body)
    return joiner.join(out)


def process_long_input(text, system, max_chunk=DEFAULT_MAX_CHUNK, on_progress=None,
                       llm_fn=None, cfg=None):
    """整条"输入无限"流水线：切片 → 逐片调模型 → 每片落盘 → 拼装。

    `on_progress(done, total)`：只用来给界面显示"正在处理…"（**不暴露总片数**，
    用户看不到"第 X/Y 片"这种技术痕迹 —— 无限 5：感知无限）。
    返回 dict：answer / slices / tokens_in / elapsed_s / chunk_files
    """
    from . import continuation as _c
    if cfg and cfg.get("max_chunk"):
        max_chunk = int(cfg["max_chunk"])
    llm_fn = llm_fn or _c._default_call
    instr, slices = split_task(text, max_chunk)
    t0 = time.time()
    files, parts = [], []
    for i, s in enumerate(slices, 1):
        prompt = ("用户的要求：%s\n\n"
                  "下面是一份长材料的一段（全文共 %d 段）。**只处理这一段**，"
                  "不要重复上一段的结论，不要写「以下是第几段」这类话。\n\n"
                  "材料：\n%s" % (instr, len(slices), s))
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": prompt})
        try:
            out = (llm_fn(msgs, max_chunk) or "").strip()
        except Exception:
            out = ""
        parts.append(out)
        files.append(save_chunk(i, out))
        if on_progress:
            try:
                on_progress(i, len(slices))
            except Exception:
                pass
    return {"answer": merge_outputs(parts), "slices": len(slices),
            "tokens_in": _estimate(text), "elapsed_s": round(time.time() - t0, 2),
            "chunk_files": [f for f in files if f]}
