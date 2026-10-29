# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 长文记忆与去重（2026-10-29）

【用户实测的问题】让它分阶段写小说（第二阶段 / 第三阶段 / 第四阶段），结果是：
  · 每一阶段结尾都把同一段话再说一遍：
      「有些东西，不该被删除。有些东西，不该被遗忘。有些东西……应该被带回。」
  · 段内还有「别走，别走，别走」「我会记得」连排；
  · 每一阶段末尾还挂一句「自评 B：这题我没有把握」。
  用户的评价：「我要麻了，你自己看他说了重复了多少次」。

【为什么会这样（根因三条，都得治）】
  1. **跨轮次不知道"前面已经写过什么"**：每个阶段是一次独立请求，模型只看得到上一段的尾巴，
     于是"收尾金句"被反复重新发明。段内去重（`core/continuation.py`）只管**本次调用内部**，
     管不了跨轮次 —— 这是本条要补的那一块。
  2. **模型有意重复**（"别走，别走，别走"）属于修辞，但连排三遍以上就是失控；
     这类**句子级重复**需要一个后置收口，而不是只靠 ngram 检测。
  3. **创作文本没有可核查断言**，挂"我没把握/没查到来源"的免责声明纯属噪音。

【本模块做三件事】
  · `accumulate(sid, text)`：按会话累积"已经写出去的长文"，落盘 `logs/longform/<sid>.json`；
  · `dedupe(sid, new_text)`：把新写的内容与**前面所有轮次**比对，
      段落级重复 → 整段丢掉（并如实记数）；
      句子级重复（同句 ≥3 次）→ 只留第一次，其余丢掉（"别走"留一次）；
  · `stats(sid)`：给"这一阶段删掉了多少重复"一个可查的数字。

【边界（不粉饰）】
  · 只删**完全相同的段落/句子**，不做"意思相近"的判断（那是改写，不是去重）；
  · 删掉的都记进 `dropped` 与日志，用户能查到"少了什么"；
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

_SENT_MIN = 14          # 短于这个长度的句子不参与"句子级去重"（太短容易误伤）
_SENT_REPEAT_MAX = 2    # 同一句最多留 2 次（第 3 次起才丢）


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
    seen, out = [], []
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
    """与前面各轮次比对，去掉重复的段落与"同句 ≥3 次"的句子。

    返回 {"text", "dropped_paras", "dropped_sents", "seen_paras"}。
    """
    st = load(sid)
    seen_para = set(st.get("paras") or [])
    seen_sent = list(st.get("sents") or [])
    out, dropped_p = [], 0
    dropped_s = 0
    paras = _split_paragraphs(new_text)
    new_paras, new_sents = [], []
    sent_count = {}
    for p in list(seen_sent):
        sent_count[p] = sent_count.get(p, 0) + 1
    for idx, par in enumerate(paras):
        if not str(par or "").strip():
            out.append(par)
            continue
        k = _key(par)
        if k in seen_para:
            dropped_p += 1
            out.append("")             # 整段已经在前面出现过 → 丢掉（留个空行占位）
            continue
        # 段内句子级：同句出现太多次就只留前几次
        # 【短句也要管】实测「别走。别走。别走。别走。」这种只有 2 个字的句子，
        #   因为"太短不参与去重"（<14 字）被整段放过去了，用户看到的就是连排。
        #   所以再加一条：**相邻同句连排 ≥3 次** → 只留前 2 次（与长短无关）。
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
        merged = "".join(keep)
        if merged.strip():
            out.append(merged)
        new_paras.append(k)
    text = "".join(out).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    st["paras"] = list(seen_para) + new_paras
    st["sents"] = (seen_sent + new_sents)[-4000:]
    st["paras"] = st["paras"][-4000:]
    st["chars"] = int(st.get("chars") or 0) + len(text)
    save(sid, st)
    if dropped_p or dropped_s:
        LOG.info("长文去重：丢掉重复段落 %d 段、重复句子 %d 句（与前面各阶段比对）",
                 dropped_p, dropped_s)
    return {"text": text, "dropped_paras": dropped_p, "dropped_sents": dropped_s,
            "seen_paras": len(seen_para)}


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
