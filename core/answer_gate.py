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
     **数量词也算**（7 个链接 / 3 位作者 / 120 页）—— 实测「这页有 7 个链接」原来完全不算断言，
     而用户会拿这个数去决定"要不要逐章抓"；个/位/名/岁/页/篇/章 因此并入数值类。
     它们不进"强类型"（不单独弹提示），只在累计到阈值时一起算，避免误报变多；
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

# 【可测量旋钮】几处以上「找不到依据」才强标注。
#   默认 3（与历史行为一致）。`core/gate_evolve.py` 只允许把这类**声明式旋钮**当候选，
#   而且要 A/B 量过、不退步才留 —— 自我改进不能是"我觉得更好就改"。
NOTE_MIN_STRONG = 3

# 带单位的数值：气温/温度、金额、百分比、比分、数量+单位
_NUM_UNIT = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*"
    r"(°C|°F|℃|度|元|块|万元|亿元|美元|元/|%|％|MB|GB|KB|MB/s|km|公里|米|千克|kg|"
    r"分钟|小时|秒|天|人|条|次|倍|分|球|个|位|名|岁|页|篇|章)"
)
# 比分/若干比若干
_SCORE = re.compile(r"(\d+)\s*[-:比]\s*(\d+)")
# 日期：2026年7月20日 / 2026-07-20 / 7月20日
_DATE = re.compile(r"(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日|\d{4}-\d{2}-\d{2}|"
                   r"\d{1,2}\s*月\s*\d{1,2}\s*日)")
# 网址与文件路径
_URL = re.compile(r"https?://[^\s\)\]\"'，。；]+")
_PATH = re.compile(r"[A-Za-z]:\\[^\s\"'，。；\)]+|/(?:[\w.\-]+/){2,}[\w.\-]+")
# IP 地址：用户会直接拿去用（配防火墙、报故障），错一位就废 —— 必须算可核查断言。
#   【2026-10-28 加】实测：「我的公网 IP 是多少」的回答里 111.17.158.64 原来**不算断言**，
#   于是审计说「没有可核查的断言」—— 最常见、最该被核的一类反而漏了。
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


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
    for m in _IPV4.finditer(t):
        # 只认像样的 IPv4（每段 0~255），否则会把版本号 1.2.3.4 之类也当 IP —— 那正合适，
        # 因为版本号同样"用户会拿去用"。这里只排除明显非法的（999.1.1.1）。
        octets = m.group(0).split(".")
        if all(str(int(x)) == str(x) for x in octets) and all(0 <= int(x) <= 255 for x in octets):
            add("IP", m.group(0), m.group(0))
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


# 【创作类不适用"可核查"】虚构创作里的日期、地名、数字是**作品的一部分**，不是事实断言。
#   给小说挂「本条没有可核查的来源，请自行核实」等于给诗加脚注 —— 是噪音，不是诚实。
#   ⚠️ 只在**问题本身就是创作请求**时才跳过；其余一切照旧审。
#   跳过的理由会写进返回值的 `skipped` 字段，不静默。
_CREATIVE_RE = re.compile(
    r"(写小说|写一段|写一章|写个故事|写故事|续写|接着写|往下写|下一段|下一章|"
    r"第[一二三四五六七八九十\d]+(?:阶段|章|段|回|幕|节)|"
    r"小说|故事|剧本|台词|人物设定|角色设定|大纲|文笔|字数|字左右|"
    r"散文|诗歌|歌词|作文)")


def is_creative(question):
    """这句话是不是要它写/续写创作类内容。与 app 侧的判据保持同一口径。"""
    return bool(_CREATIVE_RE.search(str(question or "")))


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
    if is_creative(question):
        return {"claims": len(claims), "unverified": [], "ratio": 1.0, "note": "",
                "skipped": "creative"}      # 创作类的数字/地名不当作事实断言审

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
    # 【2026-10-28 改】这里的「3 处以上才强标注」原来是写死的字面量。
    #   改成模块级常量，是为了让 `core/gate_evolve.py` 能把它当成**可测量、可回滚的旋钮**：
    #   自我改进不是"我觉得这个数更好就改"，而是"A/B 量过、不退步才留"。
    #   默认值与改动前**完全一致**（3），不改变现有行为。
    if unverified and not ev:
        note = ("⚠️ **本条没有可核查的来源**（这一轮没有检索/工具结果），"
                "下面提到的具体细节都是模型凭先验说的，**请自行核实**。")
    elif len(unverified) >= NOTE_MIN_STRONG:
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
