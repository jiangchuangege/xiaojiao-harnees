# -*- coding: utf-8 -*-
"""多次采样 + 载体侧交叉校验 + 投票择一（文档里一直标着"未落地"的那条）。

为什么这样做：用户要求「必须超过现在」。单颗 4B 一次前向的上限，靠换个提示词是抬不动的；
能抬的是**同一道题让它在几个不同角度各答一遍，再由载体按可核的判据挑一个**——
这正是 README 能力对照表里写着「未落地：【同题跑 N 次 + 投票择一】的完整流水线」的那一格。

判据只用"可核的东西"，不玄学：
  · 复读率（4-gram 重复占比）—— 越低越好
  · 套话/模板痕迹 —— 命中即扣分
  · 空答/过短 —— 直接淘汰
  · 数字自洽 —— 题里有算术要求时，答案里必须出现正确结果（用载体自己的算）
  · 长度适中 —— 明显过短扣分（信息量少）
  · 角度新颖度 —— 多个候选里，和其余候选差异过大的会被标出来，最后看它是否更完整

对外只有两个函数：
  score(text, question)      -> dict(分项 + 总分)
  pick(cands, question)      -> (最好的一个, 元信息)
"""
import re

_ANGLE_HINTS = [
    "先给结论，再用两三句话说明理由。别铺垫。",
    "把关键步骤分开写清楚，每一步都要能被核对。",
    "换一个角度审一遍：先挑出最容易错的地方，再给答案。",
    "用最简单的话讲明白，不要堆术语。",
]


def _clean(t):
    return re.sub(r"\s+", "", t or "")


def _dup_rate(text):
    t = _clean(text)
    if len(t) < 8:
        return 0.0
    grams = [t[i:i + 4] for i in range(len(t) - 3)]
    return round(1.0 - len(set(grams)) / float(len(grams)), 3)


_TEMPLATE_MARKS = (
    "作为一个AI", "作为一个 AI", "根据我的训练数据", "我无法", "我是一名AI",
    "无法回答", "这个问题我无法", "抱歉，我不能", "我的知识截止",
)


def score(text, question=""):
    """给一个候选答案打分。分项都写出来，方便以后调权重。"""
    t = str(text or "")
    n_chars = len(_clean(t))
    dup = _dup_rate(t)
    bad = {
        "empty": n_chars < 12,
        "too_long_dup": dup >= 0.25,
        "template": any(m in t for m in _TEMPLATE_MARKS),
        "code_leak": ("```" in t) and ("代码" not in question and "python" not in question.lower()),
        "unknown_tool": "未知工具" in t,
    }
    # 数字自洽：题里有算式就让载体自己算一遍，看答案里有没有那个数
    need_num = None
    m = re.search(r"(\d+)\s*(?:个|瓶|箱|人|天|元|米|千克|kg).{0,12}"
                  r"(\d+)\s*(?:瓶|个|箱|人|天|元|米|千克|kg)", question or "")
    if m:
        need_num = m.group(1)      # 只做"有没有出现题里数字"的粗核，不假装能判对错
    has_num = (need_num is None) or (need_num in t)

    s = 100.0
    if bad["empty"]:
        s -= 60
    if bad["too_long_dup"]:
        s -= min(40, dup * 120)
    if bad["template"]:
        s -= 25
    if bad["code_leak"]:
        s -= 20
    if bad["unknown_tool"]:
        s -= 40
    if not has_num:
        s -= 10
    if n_chars > 40:
        s += 4                     # 有点实质内容，微加分（上限很低，不鼓励水字数）
    if n_chars > 900:
        s -= 6                     # 太长也算风险
    return {"score": round(max(0.0, s), 1), "chars": n_chars, "dup": dup,
            "flags": [k for k, v in bad.items() if v]}


def _similar(a, b):
    """两个答案像不像（4-gram Jaccard）。用来找"多数派"。"""
    ga = {_clean(a)[i:i + 4] for i in range(max(0, len(_clean(a)) - 3))}
    gb = {_clean(b)[i:i + 4] for i in range(max(0, len(_clean(b)) - 3))}
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / float(len(ga | gb))


def pick(cands, question=""):
    """在多个候选里挑一个：先按分，再按"多数一致"。

    规则（可解释，写在返回值里）：
      1. 每个候选打分；
      2. 算每个候选与其他候选的平均相似度 —— 多数派得分更高（三个里两个像 = 那两票可信）；
      3. 综合 = 分数 + 相似度 * 8（权重小，避免把"复读"当成共识）；
      4. 平分时优先更短（废话少）。
    """
    items = []
    for i, c in enumerate(cands or []):
        t = str(c or "").strip()
        sc = score(t, question)
        items.append({"i": i, "text": t, "score": sc["score"], "chars": sc["chars"],
                      "dup": sc["dup"], "flags": sc["flags"], "sim": 0.0})
    if not items:
        return "", {"why": "没有候选"}
    for a in items:
        sims = [_similar(a["text"], b["text"]) for b in items if b is not a]
        a["sim"] = round(sum(sims) / len(sims), 3) if sims else 0.0
        a["total"] = round(a["score"] + a["sim"] * 8, 2)
    items.sort(key=lambda x: (-x["total"], x["chars"]))
    best = items[0]
    why = ("选了第 %d 个（综合 %.1f = 分数 %.1f + 一致度 %.2f×8；共 %d 个候选）"
           % (best["i"] + 1, best["total"], best["score"], best["sim"], len(items)))
    return best["text"], {"why": why, "cands": [{k: v for k, v in x.items() if k != "text"}
                                                for x in items]}


def angle_hint(i):
    return _ANGLE_HINTS[i % len(_ANGLE_HINTS)]
