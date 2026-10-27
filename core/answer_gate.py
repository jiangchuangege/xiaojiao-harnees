# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 通用答案闸门（2026-10-17）

【它解决什么】模型最坏的毛病不是答得浅，是**答得具体但不真** ——
  「西班牙 1-0 阿根廷 · 2026年7月20日 · 大都会人寿体育场 · 第106分钟」
这种细节没人能一眼看出真假，用户只能信。所以载体必须替用户做一件事：
**把回答里"可以被核查的断言"挑出来，逐条问一句"本轮的材料里有依据吗"**，
没有依据就当场标出来。

【和另外两道闸门的分工】
  · `core/world/firewall.py`：管**进来的**内容脏不脏（注入/钓鱼/过时）；
  · `core/memory_gate.py`：管**记住的**内容该不该记；
  · 本模块：管**出去的**话该不该这么说 —— 三道合起来才是闭环。

【只挑四类断言，宁少不滥】
  ① 带单位的数值（气温、价格、百分比、比分…）：最容易编，也最容易被抓；
  ② 日期/时间点（2026年7月20日、昨天 14:30）；
  ③ 网址（用户会去点，错一个字符就废）；
  ④ 文件路径（用户会拿去用，写错就是白干）。
  人名地名这类不在这里判 —— 中文实体边界难切，硬判会大面积误报，
  那种事交给"来源覆盖率"（`_is_realtime_fact` 那条）和人工复核。

【判据是"能不能在本轮材料里找到"，不是"对不对"】
  载体不是真理裁判，它只做一件事：**没依据就别装成有依据**。
  所以输出永远是"未核实"而不是"错误"——这两句话分量完全不同。

【绝不改写答案】只在前面加一段标注。用户要的原文一个字不动，
  ——因为"改内容"意味着载体在替用户重写事实，那比标注更危险。
"""
import re

# 带单位的数值：气温/温度、金额、百分比、比分、数量+单位
_NUM_UNIT = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*"
    r"(°C|°F|℃|度|元|块|万元|亿元|美元|元/|%|％|MB|GB|KB|MB/s|km|公里|米|千克|kg|"
    r"分钟|小时|秒|天|人|条|次|倍|分|球)"
)
# 比分/若干比若干
_SCORE = re.compile(r"(\d+)\s*[-:比]\s*(\d+)")
# 日期：2026年7月20日 / 2026-07-20 / 7月20日
_DATE = re.compile(r"(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日|\d{4}-\d{2}-\d{2}|"
                   r"\d{1,2}\s*月\s*\d{1,2}\s*日)")
# 网址与文件路径
_URL = re.compile(r"https?://[^\s\)\]\"'，。；]+")
_PATH = re.compile(r"[A-Za-z]:\\[^\s\"'，。；\)]+|/(?:[\w.\-]+/){2,}[\w.\-]+")


def _norm(s):
    """比对用的归一化：去掉空白与千分位逗号、全角转半角常见符号。"""
    t = str(s or "")
    t = t.replace("，", ",").replace("．", ".").replace("　", " ")
    t = re.sub(r"[\s,]", "", t)
    return t


def extract_claims(text):
    """挑出回答里"可以被核查"的断言。返回 list[dict]（kind/value/raw）。"""
    t = str(text or "")
    out, seen = [], set()

    def add(kind, value, raw):
        k = (kind, _norm(value))
        if not value or k in seen:
            return
        seen.add(k)
        out.append({"kind": kind, "value": str(value), "raw": str(raw)[:80]})

    for m in _NUM_UNIT.finditer(t):
        add("数值", m.group(1), m.group(0))
    for m in _SCORE.finditer(t):
        add("比分", "%s:%s" % (m.group(1), m.group(2)), m.group(0))
    for m in _DATE.finditer(t):
        add("日期", m.group(1), m.group(1))
    for m in _URL.finditer(t):
        add("网址", m.group(0), m.group(0))
    for m in _PATH.finditer(t):
        add("路径", m.group(0), m.group(0))
    return out


def _found(value, evidence_norm, kind):
    """这个断言在材料里能找到吗？找不到的依据是什么。

    比对口径偏**宽**（只要数字/路径串出现在材料里就算找到）：
    闸门的成本是不对称的 —— 误报（说"未核实"但其实有依据）只是让用户多看一眼；
    漏报（编的东西没人提）会让用户当真。所以宁可宽。
    """
    v = _norm(value)
    if not v:
        return True
    if kind in ("网址", "路径"):
        # 网址/路径要求"主干"能对上（去掉协议、斜杠、盘符后比）
        core = re.sub(r"^(https?://|[A-Za-z]:)", "", v).strip("/\\")
        core = core.split("?")[0]
        return bool(core) and (core in evidence_norm or core.replace("/", "\\") in evidence_norm
                               or core.replace("\\", "/") in evidence_norm)
    if kind == "比分":
        a, _, b = v.partition(":")
        return (a in evidence_norm and b in evidence_norm)
    return v in evidence_norm


def audit(answer, evidence="", question=""):
    """审一遍回答。返回 dict：

        {"claims": n, "unverified": [...], "ratio": 0~1, "note": 用户可见标注 或 ""}

    `evidence` 是本轮所有可核查材料的拼接（工具结果 + 检索片段）。
    `question` 只用于判断"这条断言是不是用户自己给的"（用户说的数字不算模型编的）。
    """
    ans = str(answer or "")
    ev = _norm(evidence)
    qn = _norm(question)
    claims = extract_claims(ans)
    if not claims:
        return {"claims": 0, "unverified": [], "ratio": 1.0, "note": ""}

    unverified = []
    for c in claims:
        if not ev:
            # 一点材料都没有 → 全部记未核实（但下面统一标注，不逐条堆）
            unverified.append(c)
            continue
        if _found(c["value"], ev, c["kind"]):
            continue
        # 用户自己在问题里说过的数字，不算模型编的
        if _norm(c["value"]) and _norm(c["value"]) in qn:
            continue
        unverified.append(c)

    n = len(claims)
    ratio = 1.0 - (len(unverified) / float(n)) if n else 1.0
    note = ""
    # 标注强度分三档（避免"每句都弹警告"，那样用户会直接把警告当背景噪声）
    _strong_kinds = {"比分", "日期", "网址", "路径"}
    if unverified and not ev:
        note = ("⚠️ **本条没有可核查的来源**（这一轮没有检索/工具结果），"
                "下面提到的具体细节都是模型凭先验说的，**请自行核实**。")
    elif len(unverified) >= 3:
        kinds = {}
        for c in unverified:
            kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
        desc = "、".join("%s %d 处" % (k, v) for k, v in kinds.items())
        note = ("⚠️ **有 %d 处细节我无法在本轮材料里核实**（%s）。"
                "下面照原样给你，但这些数字/日期/链接请别直接当真。" % (len(unverified), desc))
    elif any(c["kind"] in _strong_kinds for c in unverified):
        # 只有 1~2 处、但属于"用户会拿去用"的类型（比分/日期/链接/路径）→ 轻提示
        c = [x for x in unverified if x["kind"] in _strong_kinds][0]
        note = ("⚠️ 这条里的「%s」在本轮材料里没找到依据，可能不准。" % c["raw"][:40])
    return {"claims": n, "unverified": unverified, "ratio": round(ratio, 3), "note": note}


def apply(answer, evidence="", question=""):
    """审完把标注加在**前面**（正文一个字不动）。返回 (新 answer, 审计结果)。"""
    r = audit(answer, evidence, question)
    if not r.get("note"):
        return answer, r
    return (r["note"] + "\n\n" + str(answer or "")), r
