# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 中文数字翻译（规则为主，模型只兜底）

【这段为什么这么设计】
    中文数字是**确定性的**：「三千二百五十六」就是 3256，只有一个答案。
    它跟阿拉伯数字的差别只是"写法"，不是"语义推理" —— 这种活本来就该载体干。
    为什么不让 4B 去翻译：**（⚠️ 这段理由在 2026-09-16 被实测推翻了一半，如实记）**
    原注释写的是"4B 对『两万三』『一千二』这类口语省略写法非常不稳，
    实测会把『两万三』翻成 2300 或 20300（漏一位/多一位）"。
    但 2026-09-16 直接测了一遍（`temperature=0`、只取一行数字）：
    **三千二百五十六/两万三/一千二/三万五/十五万/两千三百万/一点五万/百分之三十/
    负的两万三/二十三点五 —— 10 个全对**。所以"模型翻不对"这个理由**现在复现不出来**
    （它可能来自更早的模型或更早的提示词，但没留原始记录，只能标成"复现不出来"）。
    **真正该保留的理由换成了"确定性"**：中文数字只有唯一个答案，
    规则必然正确、零延迟、同一输入永远同一输出、还能单测；
    模型即便全对，本质也是"大概率对"、每次 0.2~0.4 秒、还取决于模型版本与温度。
    所以分工照旧（规则覆盖的一律走规则），但**依据不是"模型不会"，是"这题该用确定性解法"**。
    规则覆盖不到的极端写法，才让 4B 给一个**纯数字表达式**，
    而且**必须过载体的格式校验**才采信。

【去掉会怎样】
    用户说「三千二百五十六 乘以 十二」时，计算器短路识别不到（因为它只认阿拉伯数字），
    只能交给概率模型去算 —— 又回到"看起来算得很认真，但结果是错的"。

【口语省略写法是这里的重点，不是边角】
    「两万三」= 23000、「三万五」= 35000、「一千二」= 1200、「一百二」= 120。
    规则：末尾一个**光杆数字**（后面没有单位字）时，它继承上一个单位再降一级
    （万→千、千→百、百→十）。但一旦出现过「零」，这个省略规则必须关掉 ——
    否则「一百零八」会被算成 180（实测口径要求它是 108）。
"""
import re

__all__ = ["cn_to_int", "to_arabic", "has_cn_number", "CN_CHARS"]

# 数字字（含"两/俩"这类口语写法）
_DIGITS = {"零": 0, "〇": 0, "0": 0, "一": 1, "壹": 1, "二": 2, "两": 2, "俩": 2, "贰": 2,
           "三": 3, "叁": 3, "四": 4, "肆": 4, "五": 5, "伍": 5, "六": 6, "陆": 6,
           "七": 7, "柒": 7, "八": 8, "捌": 8, "九": 9, "玖": 9}
# 阿拉伯数字也当数字字认："3千2百" 这种中阿混写日常真的会出现（实测用例里有）。
for _c in "123456789":
    _DIGITS[_c] = int(_c)
# 节内单位（十/百/千）
_UNITS = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000}
# 大节单位
_BIG = {"万": 10 ** 4, "萬": 10 ** 4, "亿": 10 ** 8, "億": 10 ** 8}

CN_CHARS = "".join(sorted(set(_DIGITS) | set(_UNITS) | set(_BIG) | {"零", "〇"}))

# 「一起 / 一样 / 一直」这类词里的"一"不是数量 —— 逐字替换会把它们改成"1起/1样"。
# 为什么要在这里挡：`to_arabic` 是**逐段替换**的，不挡住的话用户闲聊里的常用词会被改坏，
# 而它换来的只是一堆无意义的数字。挡的成本是几个词表，收益是"不改坏正常句子"。
_PROTECT = ("一起", "一样", "一直", "一定", "一般", "一切", "一旦", "一边", "一点",
            "一些", "一直", "一时", "一共几", "十分", "十足", "万一", "千万",
            "不二", "独一无二", "说一不二", "一无所", "一律", "一口气")


def _section(s):
    """一节（十/百/千 以内）的中文数字 → 整数。不合法返回 None。"""
    total = 0
    num = 0            # 当前待用的数字字
    last_unit = 0      # 最近用过的单位（给"一千二"这种省略写法用）
    zero_seen = False  # 出现过"零" → 关掉省略规则（见模块文档）
    for ch in s:
        if ch in _DIGITS:
            num = _DIGITS[ch]
            if ch == "零" or ch == "〇" or ch == "0":
                zero_seen = True
        elif ch in _UNITS:
            u = _UNITS[ch]
            # 单位必须**严格递减**（千→百→十）。"十十"这种重复单位不是合法数字 ——
            # 不拦的话它会算出 10 这种假结果，而用户拿去用的是一个根本不存在的数。
            if last_unit and u >= last_unit:
                return None
            if not num and not last_unit:
                num = 1            # "十五" 开头的"十"就是 1 个十
            total += num * u
            num = 0
            last_unit = u
            zero_seen = False      # 新的一节开始，"零"的作用已用完
        else:
            return None
    if num:
        if last_unit and not zero_seen:
            total += num * (last_unit // 10)     # 省略写法：继承上一单位再降一级
        else:
            total += num
    return total


def cn_to_int(text):
    """中文数字 → 整数。翻不出来返回 None（**不许猜**）。

    覆盖：三千二百五十六→3256、一百零八→108、两万三→23000、三万五→35000、
          一千二→1200、十五→15、十→10、二十→20、一亿三千万→130000000、
          以及中阿混写（"3千2百"→3200）。
    """
    s = str(text or "").strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if not all(ch in _DIGITS or ch in _UNITS or ch in _BIG for ch in s):
        return None
    # 大节单位按"最靠右的那个"切：一亿三千万 → 亿左边 一，右边 三千万
    total = 0
    for big in ("亿", "億"):
        if big in s:
            i = s.rindex(big)
            left, right = s[:i], s[i + 1:]
            lv = cn_to_int(left) if left else 1
            if lv is None:
                return None
            total += lv * _BIG[big]
            s = right
            break
    if "万" in s or "萬" in s:
        i = s.rindex("万") if "万" in s else s.rindex("萬")
        left, right = s[:i], s[i + 1:]
        lv = _section(left) if left else 1
        if lv is None:
            return None
        total += lv * 10 ** 4
        if not right:
            return total
        # 省略写法：「两万三」的"三"是 3 千（该节无单位字）
        if all(ch in _DIGITS for ch in right):
            if len(right) == 1:
                return total + _DIGITS[right] * 1000
            return None
        rv = _section(right)
        return None if rv is None else total + rv
    v = _section(s)
    if v is None:
        return None
    return total + v


def has_cn_number(text):
    """句子里有没有中文数字（**只判有没有**，不负责翻）。"""
    return any(ch in _DIGITS or ch in _UNITS or ch in _BIG for ch in str(text or ""))


def to_arabic(text):
    """把句子里的中文数字段换成阿拉伯数字（其余原文保留）。

    ⚠️ 这是给**算式/检索词**用的规范化，不是给自然语言用的：
    它会把"三"变成"3"，所以只该在"这句话本来就是个算式"的场景调用。
    常用词（一起/一直/十分…）已经在 `_PROTECT` 里挡掉，但那只是**兜底**，不是许可。
    """
    s = str(text or "")
    if not s:
        return ""
    protected = {}
    for i, w in enumerate(_PROTECT):
        if w in s:
            key = "\ue000%d\ue001" % i        # 私用区占位符：句子正文里不会出现
            protected[key] = w
            s = s.replace(w, key)
    out = []
    buf = []
    for ch in s:
        if ch in _DIGITS or ch in _UNITS or ch in _BIG:
            buf.append(ch)
            continue
        out.append(_flush(buf))
        out.append(ch)
    out.append(_flush(buf))
    r = "".join(out)
    for key, w in protected.items():
        r = r.replace(key, w)
    return r


def _flush(buf):
    """把缓冲里的一段中文数字翻掉（翻不出来就原样吐回去，绝不吞字）。"""
    if not buf:
        return ""
    raw = "".join(buf)
    buf.clear()
    v = cn_to_int(raw)
    return raw if v is None else str(v)
