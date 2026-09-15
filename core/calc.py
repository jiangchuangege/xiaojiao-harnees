# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 确定性计算（纯算式 + 概率组合）

【这段为什么这么设计】
    算术与概率是**确定性事实**：347 × 892 只有一个正确答案，而且必须每一次都对。
    这类东西不该交给概率模型 —— 4B 算多位乘法会错，位数越多越错。

【去掉会怎样】
    用户问算术题时只能靠模型猜。实测症状是"看起来算得很认真，但结果是错的" ——
    比明确说"我不会"更糟，因为用户会照着错结果做决定。

【边界：只认"明确的算式/概率题"，不做模糊解析】
    带计算能力的功能最常见的误触是**把陈述句里的数字当算式**：
    「我 25 岁」「3 个红球」（没问概率）都不能触发。
    所以判据是"整句就是一个算式"或"整句在问一个可组合计算的概率"，
    拿不准就**不接**（不接最多是模型自己算，乱接会答非所问）。
"""
import ast
import math
import re

from . import cn_number as _cn

__all__ = ["detect", "solve", "looks_like_arithmetic", "solve_chinese_arithmetic",
           "looks_like_cn_math", "answer_text"]

# 纯算式：整句只由数字 / 运算符 / 括号 / 空白组成
_ARITH_CHARS = re.compile(r"^[\s\d+\-*/×÷xX＊＋－（）()．.,%^]+$")
_HAS_DIGIT = re.compile(r"\d")
_MUL = re.compile(r"[×xX＊]")
_DIV = re.compile(r"[÷]")
_FULL2HALF = {"×": "*", "＊": "*", "x": "*", "X": "*", "÷": "/",
              "＋": "+", "－": "-", "（": "(", "）": ")", "．": ".", "，": ","}

# 颜色 / 球类名词（概率题的主体）
_COLORS = ("红", "蓝", "黄", "绿", "白", "黑", "紫", "橙")
_NOUNS = ("球", "球了", "牌", "卡片", "糖", "果", "笔", "鼠标")
_COUNT = re.compile(r"(\d+)\s*(?:个|颗|只|张|支|块)?\s*(%s)" % "|".join(_COLORS))
_TOTAL = re.compile(r"(?:一共|总共|共|有)\s*(\d+)\s*(?:个|颗|只|张|支|块)?")


# 自然语言外壳：用户很少只打一个光秃秃的算式，多半会带这些前后缀。
# 【为什么要剥壳】实测：「347 × 892」触发载体直算，而「347 × 892 等于多少」
#   **不触发** —— 于是最自然的问法反而走了慢路径，交给概率模型列竖式去算。
#   剥壳只是在算式两边摘掉已知的套话，**不是放宽"是不是算式"的判据**：
#   摘完仍然要求整句是纯算数表达式且含运算符，所以「我 25 岁」照旧不触发。
_WRAP_HEAD = ("请问一下", "请问", "帮我算一下", "帮我算算", "帮我计算", "帮我算",
              "算一下", "算算", "计算一下", "计算", "求解", "求")
_WRAP_TAIL = ("等于多少", "等于几", "是多少钱", "得多少", "结果是多少", "是多少",
              "等于", "＝", "=", "？", "?")


def _strip_wrapper(t):
    """摘掉算式两端的自然语言套话。返回摘干净后的字符串。"""
    s = str(t or "").strip()
    changed = True
    while changed:
        changed = False
        for w in _WRAP_HEAD:
            if s.startswith(w):
                s = s[len(w):].strip()
                changed = True
                break
        for w in _WRAP_TAIL:
            if s.endswith(w):
                s = s[:-len(w)].strip()
                changed = True
                break
        s2 = s.strip("=＝?？ 　")
        if s2 != s:
            s = s2
            changed = True
    return s


def looks_like_arithmetic(text):
    """整句是不是一个纯算式（不是"句子里出现了数字"）。"""
    t = _strip_wrapper(text)
    if not t or len(t) > 120:
        return False
    if not _HAS_DIGIT.search(t):
        return False
    if not _ARITH_CHARS.match(t):
        return False
    # 至少要有一个运算符，否则"25"这种纯数字也算算式了
    return bool(re.search(r"[+\-*/×÷xX＊＋－]", t))


def _safe_eval(expr):
    """只允许算术节点的安全求值（禁用一切名字/属性/调用）。"""
    node = ast.parse(expr, mode="eval")
    allowed = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant,
               ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod,
               ast.USub, ast.UAdd, ast.FloorDiv)
    for n in ast.walk(node):
        if not isinstance(n, allowed):
            raise ValueError("表达式里有不允许的语法：%s" % type(n).__name__)
        if isinstance(n, ast.Constant) and not isinstance(n.value, (int, float)):
            raise ValueError("表达式里只能有数字")
    return eval(compile(node, "<calc>", "eval"), {"__builtins__": {}}, {})  # noqa: S307


def _norm_expr(t):
    s = str(t or "").strip()
    for a, b in _FULL2HALF.items():
        s = s.replace(a, b)
    s = s.replace("^", "**")
    # 去掉句末的等号/问号/中文标点
    s = s.strip(" =？?。，,、")
    return s


def _fmt(v):
    """数字转成给人看的字符串：整数不带小数点，浮点最多 10 位有效数字。"""
    if isinstance(v, float) and abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    if isinstance(v, float):
        return ("%.10g" % v)
    return str(v)


def solve_arithmetic(text):
    """纯算式求解。不是算式返回 None。"""
    if not looks_like_arithmetic(text):
        return None
    expr = _norm_expr(_strip_wrapper(text))
    try:
        v = _safe_eval(expr)
    except ZeroDivisionError:
        return {"kind": "arithmetic", "expr": expr, "value": None,
                "display": "除数为 0，算不了", "ok": False}
    except Exception:      # noqa: silent-ok — 解析不了就不接，交给模型
        return None
    if isinstance(v, complex):
        return None
    return {"kind": "arithmetic", "expr": expr, "value": v,
            "display": _fmt(v), "ok": True}


def solve_probability(text):
    """概率组合题求解。不是概率题返回 None。

    支持两类（覆盖日常绝大多数问法）：
      · 「3 红球 2 蓝球，摸 2 个，都是红球的概率」→ C(3,2) / C(5,2)
      · 「……至少一个红球的概率」           → 1 − C(总−红, 摸) / C(总, 摸)
    """
    t = str(text or "")
    if "概率" not in t and "可能性" not in t:
        return None
    found = {c: int(n) for n, c in _COUNT.findall(t)}
    if not found:
        return None
    total = sum(found.values())
    m = _TOTAL.search(t)
    if m:
        total = max(total, int(m.group(1)))
    draw = re.search(r"(?:摸|取|抽|抓|拿)\s*(\d+)\s*(?:个|颗|只|张|支|块)?", t)
    k = int(draw.group(1)) if draw else 1
    if k <= 0 or k > total:
        return None
    allofthem = re.search(r"(?:都|全)\s*(?:是)?\s*(%s)" % "|".join(_COLORS), t)
    if allofthem:
        c = allofthem.group(1)
        if found.get(c, 0) < k:
            return {"kind": "probability", "value": 0.0, "display": "0",
                    "detail": "%s球不足 %d 个，概率为 0" % (c, k), "ok": True}
        num = math.comb(found[c], k)
        den = math.comb(total, k)
        v = num / den
        return {"kind": "probability", "value": v, "display": _fmt(v),
                "detail": "C(%d,%d)/C(%d,%d) = %d/%d" % (found[c], k, total, k, num, den),
                "ok": True}
    if re.search(r"至少\s*(?:有)?\s*(?:一个|一颗|一只|1\s*个)?\s*(%s)" % "|".join(_COLORS), t):
        c = re.search(r"至少\s*(?:有)?\s*(?:一个|一颗|一只|1\s*个)?\s*(%s)" % "|".join(_COLORS), t).group(1)
        if total - found.get(c, 0) < k:
            v = 1.0
            detail = "非%s球不足 %d 个，必中" % (c, k)
        else:
            v = 1 - math.comb(total - found.get(c, 0), k) / math.comb(total, k)
            detail = "1 − C(%d,%d)/C(%d,%d)" % (total - found.get(c, 0), k, total, k)
        return {"kind": "probability", "value": v, "display": _fmt(v),
                "detail": detail, "ok": True}
    return None


# ================== 中文数字算式（载体翻译，模型只兜底）==================
# 【为什么单独一条路】「三千二百五十六 乘以 十二」整句里**没有一个阿拉伯数字**，
#   既过不了 `looks_like_arithmetic`（它要求整句只有数字和运算符），也不是概率题 ——
#   不单独接这条路，用户用中文说算式就永远只会掉给模型去猜。
# 【翻译归载体，判定归载体】数字翻译是确定性的（见 core/cn_number.py），
#   所以先做"中文数字 → 阿拉伯数字 + 中文运算符 → 符号"的确定性替换，再交给同一个安全求值。
_CN_OPS = (("除以", "/"), ("乘以", "*"), ("乘上", "*"), ("加上", "+"), ("减去", "-"),
           ("减掉", "-"), ("乘", "*"), ("除", "/"), ("加", "+"), ("减", "-"))
# 问法尾巴：它们是"在问结果"，不是算式的一部分
_CN_TAIL = ("等于多少", "等于几", "是多少钱", "得多少", "是多少", "等于", "结果是多少",
            "结果", "是几", "多少", "一共", "总共", "共")
_CN_FILLER = re.compile(r"[，。！？、；：,\.!\?;:＝=]")
# 翻译后**整句**必须长这样：只有数字/运算符/括号/空格。
# 为什么卡这么死：中文句子里"减"和"加"可能出现在无关的地方（"我加个班"），
# 只做替换不校验，就会把一句闲话算出个数字来 —— 乱算比不算更糟。
_CN_EXPR_OK = re.compile(r"^[\d\s+\-*/().^]+$")


def looks_like_cn_math(text):
    """这句"像不像"一道中文数字算式（只判形状，不做翻译）。"""
    t = str(text or "")
    if not _cn.has_cn_number(t):
        return False
    if any(op in t for op, _sym in _CN_OPS):
        return True
    return bool(re.search(r"[+\-*/×÷]", t))


def solve_chinese_arithmetic(text):
    """中文数字算式求解：「三千二百五十六 乘以 十二」→ 3256*12。不认返回 None。"""
    # 先剥自然语言外壳：实测「100 除以 4」能算，而「**求** 100 除以 4」返回 None ——
    # 中文这条路原来只去掉了"请"，没去掉"求 / 请问 / 帮我算一下"这类前后缀。
    t = _strip_wrapper(text)
    if not looks_like_cn_math(t):
        return None
    expr = _cn.to_arabic(t)                      # 中文数字 → 阿拉伯数字（载体规则）
    for w, sym in _CN_OPS:                       # 中文运算符 → 符号
        expr = expr.replace(w, " %s " % sym)
    for w in _CN_TAIL:                           # 去掉"等于多少"这类问法尾巴
        expr = expr.replace(w, " ")
    expr = _CN_FILLER.sub(" ", expr)
    expr = expr.replace("的", " ").replace("呢", " ").replace("请", " ")
    expr = re.sub(r"\s+", " ", expr).strip()
    if not expr or not _CN_EXPR_OK.match(expr) or not re.search(r"[+\-*/^]", expr):
        return None
    try:
        v = _safe_eval(expr)
    except ZeroDivisionError:
        return {"kind": "arithmetic_cn", "expr": expr, "value": None,
                "display": "除数为 0，算不了", "ok": False,
                "source": "中文数字（载体规则翻译）"}
    except Exception:      # noqa: silent-ok — 翻不干净就不接，交给模型
        return None
    if isinstance(v, complex):
        return None
    return {"kind": "arithmetic_cn", "expr": expr, "value": v, "display": _fmt(v),
            "ok": True, "source": "中文数字（载体规则翻译）"}


# 4B 兜底提示词：**只准输出一个算式**。为什么要强调"不要解释、不要中文"：
# 输出的用途是喂给 `_safe_eval`，任何解释文字都会让它变成一个非法表达式；
# 而不强调的话小模型十有八九会回一整句中文。
_CN_LLM_PROMPT = (
    "把下面这句话翻译成一个**纯算式**（只用阿拉伯数字和 + - * / ( ) ）。\n"
    "只输出算式本身，不要解释、不要中文、不要等于号、不要单位。\n"
    "如果这句话不是一个算式，只输出：无\n\n句子：%s")


def solve_chinese_by_llm(text, llm_fn):
    """规则翻不出来时的**极端写法兜底**：让 4B 给一个纯数字算式，再由载体校验并求值。

    【为什么兜底必须这么窄】① 只在 `looks_like_cn_math` 为真、且规则翻译失败时才问；
      ② 回来的东西必须**完全匹配** `^[\\d +-*/().^]+$` 才采信，否则一律丢弃。
    这样"模型兜底"不会变成"每句话都多花一次模型调用"，也不会把模型编的中文当算式执行。
    """
    if not looks_like_cn_math(text):
        return None
    if not callable(llm_fn):
        return None
    try:
        out = llm_fn(_CN_LLM_PROMPT % str(text or "")[:200])
    except Exception:      # noqa: silent-ok — 兜底调用失败就当没兜底，绝不把错推给用户
        return None
    if not out:
        return None
    expr = str(out).strip().splitlines()[0].strip() if str(out).strip() else ""
    expr = expr.replace("×", "*").replace("÷", "/").replace("－", "-").replace("＋", "+")
    expr = expr.strip(" =？?").strip()
    if not expr or not _CN_EXPR_OK.match(expr) or not re.search(r"\d", expr):
        return None                      # 格式不过 → 丢弃（**不采信**模型的任何中文）
    try:
        v = _safe_eval(expr)
    except Exception:      # noqa: silent-ok — 表达式非法就丢弃
        return None
    if isinstance(v, complex):
        return None
    return {"kind": "arithmetic_llm", "expr": expr, "value": v, "display": _fmt(v),
            "ok": True, "source": "中文数字（4B 兜底，已过载体的格式校验）"}


def detect(text, llm_fn=None):
    """这句能不能用载体直接算？能就返回结果 dict，不能返回 None。

    顺序：整句算式 → **中文数字算式** → 概率题。三者都不认就**不接**。
    `llm_fn` 只在"规则全都翻不出来、但这句确实长得像中文数字算式"时才被调用
    （见 `solve_chinese_by_llm` 的说明：兜底必须窄，不能变成"每句都问一次模型"）。
    """
    if not str(text or "").strip():
        return None
    r = solve_arithmetic(text)
    if r:
        return r
    r = solve_chinese_arithmetic(text)
    if r:
        return r
    r = solve_probability(text)
    if r:
        return r
    if llm_fn is not None:
        r = solve_chinese_by_llm(text, llm_fn)
        if r:
            return r
    return None


def solve(text):
    return detect(text)


def material(text):
    """**原料**（给模型自己推的，不是给它照搬的话）。

    规格：载体直算时不该返回"结果 + 一句解释"（那是成品，换种问法就崩），
    而该返回 **结果 + 谁算的 + 它有没有参与 + 怎么来的**。
    那条解释句仍然留在 `answer_text()` 里 —— 它现在的用处只剩**兜底**
    （模型没应答、或把数字说错了，载体才用它顶上）。
    """
    r = detect(text)
    if not r:
        return {}
    if r["kind"] in ("arithmetic", "arithmetic_cn", "arithmetic_llm"):
        how = ("%s 的十进制乘法（%s）"
               % (r.get("expr") or "", r.get("kind"))).strip()
        if r["kind"] in ("arithmetic_cn", "arithmetic_llm"):
            how = "中文算式「%s」翻成 `%s` 后的十进制乘法" % (text.strip()[:40], r.get("expr") or "")
    else:
        how = "组合数计算：%s" % (r.get("detail") or "")
    return {"result": str(r.get("display") or r.get("value") or ""),
            "source": "载体的计算器（直算，不经过你）",
            "took_part": False,
            "raw": str(r.get("expr") or r.get("detail") or ""),
            "how": how, "kind": str(r.get("kind") or "")}


def answer_text(text):
    """给用户的直答文本（载体算出来的，带出处说明）。

    ⚠️ **这是成品，不是原料**：它现在的用处只剩"兜底"——
    正常路径改成 `material()` 给原料、让模型自己组织（见 `core/raw.py`）。
    """
    r = detect(text)
    if not r:
        return ""
    if r["kind"] in ("arithmetic", "arithmetic_cn", "arithmetic_llm"):
        _src = ("（这题由载体直接算，不经过模型 —— 算术是确定性事实，不该让概率模型猜）"
                if r["kind"] == "arithmetic" else
                "（这道中文算式由%s翻成 `%s` 后由载体直接算 —— 数字翻译是确定性的）"
                % (r.get("source") or "载体", r["expr"]))
        return "**%s = %s**\n\n%s" % (r["expr"], r["display"], _src)
    return "**概率 = %s**\n\n算式：`%s`\n\n（同样由载体直接算，组合数是确定性事实）" % (
        r["display"], r.get("detail") or "")
