# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 长文记忆与去重（2026-10-29；2026-10-30 加近似去重）

【用户实测的问题】让它分阶段写小说（第二阶段 / 第三阶段…），结果是：
  · 每一阶段结尾都把同一段话再说一遍；
  · **换了标点、换了几个字又写一遍**（近似重复比完全重复更难抓）：
      阶段1「老屋的门缝里漏出一丝灰黄的灯光」
      阶段2「老屋的门缝里透出一丝灰黄的灯光，像只睁不睁的眼睛」
      阶段1「他站在原地，忽然觉得——自己好像也不是第一次回来了」
      阶段2「他站在门口，看着雨…忽然觉得——／自己好像，也不是第一次回来了」
  · 段内还有「别走，别走，别走」连排；
  · 每一阶段末尾还挂一句「自评 B：这题我没有把握」。
  用户的评价：「我要麻了，你自己看他说了重复了多少次」。

【根因三条，都得治】
  1. **跨轮次不知道前面写过什么**：每个阶段是一次独立请求，模型只看得到上一段尾巴，
     于是"收尾金句"被反复重新发明。
  2. **模型有意重复**（「别走，别走，别走」）属于修辞，但连排三遍以上就是失控。
  3. **创作文本没有可核查断言**，挂「我没把握/没查到来源」的免责声明纯属噪音（在 app 侧处理）。

【本模块做三件事】
  · 段落级：完全相同 → 整段丢掉；**近似（二字组重合度 ≥ 阈值）→ 也丢掉**；
  · 句子级：同句累计 >2 次丢掉；相邻同句连排 ≥3 次只留两次；跨轮次近似句同样收口；
  · 账目：去掉多少、其中多少是"近似"、多少是"一字不差"，全部如实返回并落日志。

【为什么用二字组（bigram）而不是编辑距离】
  中文没有空格，编辑距离对"换了三个字的同一句话"给分很怪；二字组重合度（Jaccard）
  对中文近重复最直接：同一句话改标点 → 重合度仍接近 1；换成完全不同的内容 → 接近 0。
  纯 CPU，一轮几毫秒。

【边界（不粉饰）】
  · 只删**能被量出来的重复**（一字不差 / 二字组重合度 ≥ 阈值），不做"意思相近"的判断
    —— 那是改写，不是去重，载体不假装自己能判文学；
  · 删掉的都记进返回值与日志，用户能查到"少了什么"；
  · 阈值是**可测量、可回滚**的常量，改这里必须重跑本模块的验收用例；
  · 这不是"让它写得好"的方案 —— 它只保证**不重复**，写得好不好取决于火种。
"""
import hashlib
import io
import json
import logging
import os
import re

LOG = logging.getLogger(__name__)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DIR = os.path.join(_ROOT, "logs", "longform")

_SENT_MIN = 14          # 短于这个长度的句子不参与"句子级累计去重"（太短容易误伤）
_SENT_REPEAT_MAX = 2    # 同一句最多留 2 次（第 3 次起才丢）

# ---- 近似重复阈值（改这里等于改行为，必须重跑验收用例）----
# 【两个判据一起用，取大的那个】
#   · 重合度（Jaccard）：两段差不多长、换了几个字 → 高；
#   · 包含度（intersection / 短的那个）：**长句被截短再说一遍**、或整句被塞进更长的句子
#     → 重合度会被长度差拉低（实测 0.46），但包含度接近 1。
#   实测（live 真文本）这两类都出现过，只用 Jaccard 会漏掉后者。
_NEAR_PARA_MIN = 30     # 短段落不参与近似比对（「屋里没人。」这种可能是有意的节拍）
_NEAR_PARA_JAC = 0.70   # 段落：重合度 ≥ 这个值算重复
_NEAR_PARA_CONTAIN = 0.88   # 段落：包含度 ≥ 这个值也算重复
_NEAR_SENT_MIN = 10     # 短句不参与近似比对
_NEAR_SENT_JAC = 0.58   # 句子：重合度 ≥ 这个值算重复
_NEAR_SENT_CONTAIN = 0.85   # 句子：包含度 ≥ 这个值也算重复
_NEAR_WINDOW = 60      # 只跟最近这么多段/句比（再往前的多半是别的章节）

_KEEP_PARA_TXT = 400    # 每段只存前这么多字（够比对，不把磁盘写爆）
_KEEP_SENT_TXT = 120


def _ensure():
    if not os.path.isdir(_DIR):
        os.makedirs(_DIR, exist_ok=True)


def _path(sid):
    safe = re.sub(r"[^0-9A-Za-z_\-]", "_", str(sid or "default"))[:64] or "default"
    return os.path.join(_DIR, safe + ".json")


def _norm(s):
    """比对用归一化：去空白与常见标点，只留文字和数字。"""
    return re.sub(r"[\s，。！？；：、,.!?;:~…\-—「」（）()【】\"'’‘“”]", "", str(s or ""))


def _key(s):
    return hashlib.sha256(_norm(s).encode("utf-8")).hexdigest()[:16]


def _bigrams(s):
    """二字组集合（中文近重复比对的基本单位）。"""
    t = _norm(s)
    if len(t) < 2:
        return set()
    return {t[i:i + 2] for i in range(len(t) - 1)}


def _jac(a, b):
    """二字组 Jaccard 重合度 0~1。任一方为空返回 0。"""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if not inter:
        return 0.0
    return inter / float(len(a) + len(b) - inter)


def _contain(a, b):
    """包含度：交集 / 短的那一方的二字组数。0~1。

    为什么要它：把长句截短再说一遍（或整句塞进更长的句子）时，
    Jaccard 会被长度差拉低（实测 0.46），而包含度接近 1 —— 那正是要抓的重复。
    """
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if not inter:
        return 0.0
    return inter / float(min(len(a), len(b)))


def _score(a, b):
    """相似度 = max(重合度, 包含度)。两个判据各管一类重复。"""
    return max(_jac(a, b), _contain(a, b))


def _best_match(bg, pool, floor_jac, floor_contain):
    """在 pool（[(二字组, 原文)]）里找最像的一个。

    判重条件：**重合度 ≥ floor_jac 或 包含度 ≥ floor_contain**（两个判据各管一类重复）。
    返回 (相似度, 原文)；都不达标返回 (0, "")。
    """
    best, best_txt = 0.0, ""
    for other, txt in pool:
        j = _jac(bg, other)
        c = _contain(bg, other)
        if not ((j >= floor_jac) or (c >= floor_contain)):
            continue
        r = max(j, c)
        if r > best:
            best, best_txt = r, txt
    return (best, best_txt) if best else (0.0, "")


def load(sid):
    try:
        with io.open(_path(sid), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:      # noqa: silent-ok — 没有记录就是新会话
        return {}


def save(sid, d):
    _ensure()
    try:
        tmp = _path(sid) + ".tmp"
        with io.open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(json.dumps(d, ensure_ascii=False))
        os.replace(tmp, _path(sid))
    except Exception as e:      # noqa: silent-ok — 落盘失败不影响这次写作
        LOG.debug("长文记忆写入失败（忽略）：%s", e)


def _split_paragraphs(text):
    """按空行切段，保留原文（切完再拼回去，一个字都不改）。"""
    parts = re.split(r"(\n\s*\n)", str(text or ""))
    out = []
    buf = ""
    for p in parts:
        if re.fullmatch(r"\n\s*\n", p or ""):
            if buf.strip():
                out.append(buf)
            buf = ""
            out.append(p)          # 分隔符原样保留
        else:
            buf += p
    if buf.strip():
        out.append(buf)
    return out


def _sentences(par):
    return [s for s in re.split(r"(?<=[。！？!?…])", par) if str(s or "").strip()]


def dedupe(sid, new_text):
    """与前面各轮次比对，去掉重复（一字不差 + 近似）的段落与句子。

    返回 {"text", "dropped_paras", "dropped_sents", "seen_paras",
          "near_paras", "near_sents", "already"}。
      · dropped_paras / dropped_sents：判为重复而丢掉的段/句总数
      · near_paras / near_sents：其中属于**近似重复**（不是一字不差）的个数
    """
    st = load(sid)
    # 【同一份文本不重复去重】去重现在被两处调用（分块长文那条路 + 每一轮回答那条路）。
    #   同一份文本第二次进来时，它自己的段落已经在「已写过」里了 → 会被整篇删光。
    #   所以先认指纹：这份文本刚刚处理过，就原样返回，绝不再删一遍。
    _tk = hashlib.sha256(str(new_text or "").encode("utf-8")).hexdigest()[:16]
    if st.get("last_text_key") == _tk:
        return {"text": str(new_text or ""), "dropped_paras": 0, "dropped_sents": 0,
                "seen_paras": len(st.get("paras") or []), "near_paras": 0, "near_sents": 0,
                "already": True}

    seen_para = set(st.get("paras") or [])
    seen_sent = list(st.get("sents") or [])
    # 近似比对要原文，不只是哈希
    para_pool = [(_bigrams(t), t) for t in (st.get("para_txt") or [])][-_NEAR_WINDOW:]
    sent_pool = [(_bigrams(t), t) for t in (st.get("sent_txt") or [])][-_NEAR_WINDOW:]

    out, dropped_p, dropped_s = [], 0, 0
    near_p, near_s = 0, 0
    paras = _split_paragraphs(new_text)
    new_paras, new_sents, new_para_txt, new_sent_txt = [], [], [], []
    sent_count = {}
    for p in list(seen_sent):
        sent_count[p] = sent_count.get(p, 0) + 1

    for par in paras:
        if not str(par or "").strip():
            out.append(par)
            continue
        k = _key(par)
        npar = _norm(par)
        if k in seen_para:
            dropped_p += 1
            out.append("")             # 整段已经在前面出现过 → 丢掉（留空行占位）
            continue
        # ---- 近似整段重复（换标点/换几个字又写一遍）----
        if len(npar) >= _NEAR_PARA_MIN:
            r, hit = _best_match(_bigrams(par), para_pool, _NEAR_PARA_JAC, _NEAR_PARA_CONTAIN)
            if r:
                dropped_p += 1
                near_p += 1
                LOG.info("近似整段重复（重合度 %.2f）→ 丢掉：%s ／ 前文：%s",
                         r, npar[:24], _norm(hit)[:24])
                out.append("")
                continue
        # ---- 段内句子级 ----
        # 【短句也要管】实测「别走。别走。别走。别走。」只有 2 个字，
        #   因为"太短不参与去重"（<14 字）被整段放过去了，用户看到的就是连排。
        #   所以：相邻同句连排 ≥3 次只留前两次（与长短无关）。
        keep = []
        _prev, _run = "", 0
        for s in _sentences(par):
            ns = _norm(s)
            if ns and ns == _prev:
                _run += 1
            else:
                _prev, _run = ns, 1
            if _run > _SENT_REPEAT_MAX:
                dropped_s += 1          # 连排第 3 次及以后：丢掉
                continue
            # 跨轮次的近似句（例如「自己好像，也不是第一次回来了」）
            if len(ns) >= _NEAR_SENT_MIN:
                r, hit = _best_match(_bigrams(s), sent_pool, _NEAR_SENT_JAC, _NEAR_SENT_CONTAIN)
                if r:
                    dropped_s += 1
                    near_s += 1
                    LOG.info("近似重复句（重合度 %.2f）→ 丢掉：%s ／ 前文：%s",
                             r, ns[:20], _norm(hit)[:20])
                    continue
            if len(ns) < _SENT_MIN:
                keep.append(s)
                continue
            c = sent_count.get(ns, 0)
            if c >= _SENT_REPEAT_MAX:
                dropped_s += 1
                continue
            sent_count[ns] = c + 1
            keep.append(s)
            new_sents.append(ns)
            new_sent_txt.append(ns[:_KEEP_SENT_TXT])
        merged = "".join(keep)
        if merged.strip():
            out.append(merged)
            new_para_txt.append(npar[:_KEEP_PARA_TXT])
        new_paras.append(k)

    text = "".join(out).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    st["paras"] = (list(seen_para) + new_paras)[-4000:]
    st["sents"] = (seen_sent + new_sents)[-4000:]
    st["para_txt"] = (list(st.get("para_txt") or []) + new_para_txt)[-_NEAR_WINDOW:]
    st["sent_txt"] = (list(st.get("sent_txt") or []) + new_sent_txt)[-_NEAR_WINDOW:]
    st["chars"] = int(st.get("chars") or 0) + len(text)
    st["last_text_key"] = _tk
    save(sid, st)
    if dropped_p or dropped_s:
        LOG.info("长文去重：丢掉重复段落 %d 段（其中近似 %d）、重复句子 %d 句（其中近似 %d）",
                 dropped_p, near_p, dropped_s, near_s)
    return {"text": text, "dropped_paras": dropped_p, "dropped_sents": dropped_s,
            "seen_paras": len(seen_para), "near_paras": near_p, "near_sents": near_s,
            "already": False}


def accumulate(sid, text):
    """只记不算的别名（老调用点用这个名字）：仍走 dedupe，账目一致。"""
    return dedupe(sid, text)


def stats(sid):
    st = load(sid)
    return {"paras": len(st.get("paras") or []), "chars": int(st.get("chars") or 0),
            "sents": len(st.get("sents") or []), "path": _path(sid)}


def reset(sid):
    """换了新作品（不是同一篇的下一阶段）时清掉累积。"""
    try:
        if os.path.isfile(_path(sid)):
            os.remove(_path(sid))
            return True
    except Exception as e:      # noqa: silent-ok
        LOG.debug("长文记忆清理失败（忽略）：%s", e)
    return False
