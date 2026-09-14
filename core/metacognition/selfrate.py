# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 答前自评（元认知 1：先掂量自己几斤几两，再开口）

【这段为什么这么设计】
    模型最危险的行为不是"答错"，而是**用同样自信的语气答它根本不知道的事**。
    人会说"这个我记不清了"，模型不会 —— 它不是坏，是它没有"我不确定"这个出口。
    载体的责任就是**给它造一个出口**：开口之前先问它一句"这事你有几分把握"，
    它给不出确定的档位，载体就按"没把握"处理（走工具/查记忆/叫更大的模型）。
    去掉它会怎样：所有回答都长着同一张自信的脸，用户只能靠事后自己发现错了 —— 而且是在用了之后。

【三档（为什么是三档而不是更多）】
    A 有把握 → 直接答。                              （多半问题都在这一档，不该为它加流程）
    B 有点   → 答，但要**显著标注"不太确定"**。        （用户拿到的是能用的答案 + 一句提醒）
    C 没把握 → 该走工具/查记忆/叫大模型（由调用方决定）。 （载体自己不知道，就别让模型硬编）
    ? 解析不出（不许猜成 A）→ 按 C 处理，走更稳的那条路。
    为什么不做五档十分制：模型对自己的把握本来就分不了那么细，档位越细，它给的数越像随机数；
    而载体真正要做的决策只有三种（直接答 / 带标注答 / 换路子），三档正好一一对应。
    去掉"只有三档"这条：档位一多，调用方就得自己定阈值，阈值又各写一份，早晚对不上。

【为什么解析必须容错、且**绝不许猜**】
    模型很少乖乖只回一个字母：它会回"我认为是B""把握C""A。""答案是 B，因为……"，
    也可能回一长段把三档全念一遍（把提示词原样抄回来）。
    所以解析器必须：① 先认那些**明确**的档位写法；② 出现两个以上档位就判"说不准"（?）；
    ③ 一个字都认不出也判"?"。**任何情况下都不许默认成 A** ——
    默认成 A 等于把"它没自评"伪装成"它很有把握"，这正是这一层要防的事。

【怎么判断"哪些字是明确的档位"】
    见 parse_rating 的注释：先剔掉"不是A/没B"这类**排除性提及**，再找字母，
    最后才退到中文措辞（而且按 C → B → A 的顺序判，越保守的档越先命中）。
"""
import re

from . import log_line

RATING_A = "A"          # 有把握 → 直接答
RATING_B = "B"          # 有点 → 答 + 标注"不太确定"
RATING_C = "C"          # 没把握 → 该走工具/查记忆/叫大模型
RATING_UNKNOWN = "?"    # 解析不出来（**不许猜成 A**，按没把握处理）

RATINGS = (RATING_A, RATING_B, RATING_C)
ALL_RATINGS = RATINGS + (RATING_UNKNOWN,)

RATING_CN = {RATING_A: "有把握", RATING_B: "有点", RATING_C: "没把握", RATING_UNKNOWN: "说不准"}

# 档位 → 走哪条路。`?` 必须落在 use_tool：拿不准就当没把握 —— 走工具最多是多花一点时间，
# 硬答一次编造却会被用户当成事实拿走。两个代价不对等，所以一律倒向稳的那边。
ROUTES = {
    RATING_A: "direct",
    RATING_B: "answer_with_caveat",
    RATING_C: "use_tool",
    RATING_UNKNOWN: "use_tool",
}
ROUTE_CN = {"direct": "直接答", "answer_with_caveat": "答 + 标注不太确定", "use_tool": "去走工具/查记忆"}

# B 档要加在答案前面的那句中文（调用方直接用，不许各写一份 —— 三处各写一份就是三种措辞）
CAVEAT = "（这部分我不太确定，你核对一下再用）"
# 自评提示词里塞进去的原文长度上限。为什么要截断：自评是**在正常那一轮之外多出来的**输入，
# 不截断的话一次 8000 字的长上下文直接把它顶爆（连原问题都答不了），
# 而判断"有没有把握"根本用不上全文，前 2000 字足够。
_QUESTION_MAX = 2000
_CONTEXT_MAX = 1500
# raw 回传上限：自评原文会被写进边界档案/日志，不封顶就是让一次跑偏的模型输出把档案撑爆。
_RAW_MAX = 500

# ------------------------------------------------------------------ 归一化与识别用的小表
# 全角字母 → 半角。为什么要做这一步：模型偶尔会吐全角"Ｂ"，不归一就直接解析失败，
# 于是把一次明确的自评谎报成"没把握"（走工具），白白浪费一次纠正的机会。
_FULLWIDTH = {}
for _i in range(3):
    _FULLWIDTH[0xFF21 + _i] = chr(0x41 + _i)      # Ａ Ｂ Ｃ
    _FULLWIDTH[0xFF41 + _i] = chr(0x41 + _i)      # ａ ｂ ｃ

# 「排除性提及」：模型爱用"不是A也不是C"来强调它选的是 B。
# 为什么必须先剔掉：不剔的话，它**明确排除**的档位会被当成它给的档位 → 解析出 {B,C} →
# 判成"说不准"（?）→ 一个本来清清楚楚的 B 被贬成"没把握"。这是我们自己制造的误判。
# 只剔"X"这个字母本身（换成空串），不动别的字。
_NEGATED_RE = re.compile(
    r"(?:也|并|绝|都)?\s*不是\s*[:：]?\s*([ABCabc])(?![A-Za-z])"
    r"|非\s*([ABCabc])(?![A-Za-z])"
    r"|没\s*([ABCabc])(?![A-Za-z])")

# 明确提到档位的四种写法（全部命中都收进集合，再看是否唯一）。
# 为什么要四种：模型表达"我选 B"的方式不止一种；少认一种就是一次**白白降级** ——
# 明明它说清楚了 B，我们却当成"没把握"去走工具（多花时间还多调一次）。
# 为什么不用"只要能找到字母就算"：那样"把提示词抄一遍"会被当成自评（见 parse_rating）。
_EXPLICIT_RES = (
    re.compile(r"[（(【\[{]\s*([ABCabc])\s*[）)】\]}]"),                      # （B）
    re.compile(r"^\s*[^A-Za-z\r\n]{0,12}?([ABCabc])(?![A-Za-z])"),           # A。 / 我认为是B / 把握C
    re.compile(r"([ABCabc])\s*(?:档|级|等)"),                                 # B 档
    re.compile(r"(?<![不没非])(?:是|为|选|定为|判为|答案|结果|评级|自评|档位)\s*[:：]?\s*"
               r"([ABCabc])(?![A-Za-z])"),                                   # 答案是B（"不是A"已被前置剔除）
)

# 没有字母时退到中文措辞。**顺序是 C → B → A，不是 A → B → C**：
# 因为"不太确定"里含"确定"、"没有把握"里含"有把握" —— 顺序反了就会把最需要谨慎的话
# 听成最自信的话（这正是这一层存在的意义的反面）。越保守的档先判，是刻意的。
_PHRASE_RULES = (
    (RATING_C, ("没有把握", "没把握", "没什么把握", "把握不大", "不太确定", "不确定",
                "不肯定", "不清楚", "不知道", "答不上", "说不准", "没底气", "心里没数",
                "完全不会", "不太会", "记不得")),
    (RATING_B, ("有点", "稍微", "大概", "或许", "也许", "可能", "记不清", "记不太清",
                "想不起", "印象里", "依稀", "半信", "八成", "勉强")),
    (RATING_A, ("完全有把握", "很有把握", "非常有把握", "有把握", "有底气", "很确定",
                "确定", "肯定", "很清楚", "门儿清")),
)


def rate_prompt(question, context=""):
    """生成"让模型自己打分"的提示词（要求它只回 A/B/C 之一）。

    为什么要把三档的**含义**写进提示词：只说"A/B/C"模型不知道这几个字母指什么，
    会按它自己的理解乱填（比如当成选项序号）；含义写清楚，三档才有稳定的语义。
    为什么明确要求"不要解释、不要回答原问题"：自评是一次**额外**调用，
    它要是顺手把问题也答了，等于每轮多花一倍算力，还把自评和作答混在一条输出里没法解析。
    去掉这两句：要么档位是随机的，要么解析出来的"档位"其实是答案里的字母。
    """
    q = (question or "").strip()[:_QUESTION_MAX]
    ctx = (context or "").strip()[:_CONTEXT_MAX]
    lines = [
        "先不要回答问题，只做一件事：给你的把握打一个档。",
        "",
        "问题：%s" % (q or "（空问题）"),
    ]
    if ctx:
        lines += ["", "你可以参考的已知信息：%s" % ctx]
    lines += [
        "",
        "三档的含义（只能选一个）：",
        "A = 我有把握，答案是确定的；",
        "B = 我有点印象、大概知道，但细节不敢保证；",
        "C = 我没把握，再往下说就要靠猜了。",
        "",
        "只回一个字母：A 或 B 或 C。不要解释，不要回答原问题。",
    ]
    return "\n".join(lines)


def _normalize(text):
    """把回复归一化成"好认"的形式（全角字母转半角）。非字符串一律转成字符串再处理。"""
    if isinstance(text, str):
        s = text
    elif text is None:
        return ""
    else:
        s = str(text)      # 模型适配层偶尔回 bytes/数字：转一下再看，绝不因为类型就崩
    return s.translate(_FULLWIDTH)


def _phrase_ratings(s):
    """文本里**出现过的所有**中文措辞档位（集合，不是单值）。

    为什么要返回集合而不是"第一个命中的"：解析阶段需要知道"措辞一共表达了几个档"，
    才能判断它和字母是否对得上（见 parse_rating 第 ② 步）。只返回第一个的话，
    "字母说 A、措辞却也在说 C"这种矛盾就看不出来了 —— 而那正是最需要判"含糊"的情形。
    """
    out = set()
    for rating, words in _PHRASE_RULES:
        for w in words:
            if w in s:
                out.add(rating)
                break
    return out


def parse_rating(text):
    """从模型回复里解析 A/B/C；**解析不到就如实返回 "?"，绝不猜成 A**。

    判据顺序（这三步的顺序本身就是设计）：
      ① 剔掉"不是A/没B"这类**排除性提及** —— 免得把模型明确排除的档位当成它给的档位；
      ② 找明确的档位写法（（B） / 开头的字母 / B档 / 答案是B）：
         只认出一个 → 再看中文措辞是否**也**在说别的档（对不上就是含糊，判 "?"）；
         认出两个及以上 → 判 "?"（**明说了好几个档，不许挑一个**）；
      ③ 一个字都没认出来 → 退到中文措辞（C → B → A 顺序，见 _PHRASE_RULES）；
      ④ 还是认不出 → "?"。

    为什么"两个档位就判 ?"而不是"取第一个"：模型回
    "A 有把握 → 直接答；B 有点 → 带标注；C 没把握 → 走工具"（把提示词抄回来）时，
    开头就是一个 A，取第一个会得到 A —— 这正是"把没自评伪装成很有把握"，
    比返回 ? 危险得多（? 只会多走一次工具，A 会让它直接硬答）。
    同理，"字母说 B、措辞却在说 C"也对不上，一律判 "?"：宁可多走一次工具。
    """
    s = _normalize(text)
    if not s.strip():
        return RATING_UNKNOWN
    s = _NEGATED_RE.sub("", s)      # ① 先剔掉排除性提及
    found = set()
    for rx in _EXPLICIT_RES:        # ② 明确的档位写法
        for m in rx.finditer(s):
            found.add(m.group(1).upper())
    hits = _phrase_ratings(s)
    if len(found) == 1:
        one = found.pop()
        return RATING_UNKNOWN if (hits - {one}) else one
    if len(found) > 1:
        return RATING_UNKNOWN
    for rating, _words in _PHRASE_RULES:     # ③ 没有字母 → 按 C→B→A 的保守顺序取第一个命中的档
        if rating in hits:
            return rating
    return RATING_UNKNOWN                    # ④ 认不出 → 如实说认不出


def route(rating):
    """档位 → 走哪条路：A→direct、B→answer_with_caveat、C→use_tool、?→use_tool。

    为什么 `?` 也走 use_tool：见 ROUTES 的注释（两个代价不对等）。
    容错：传进来大小写混写（"b"）或带后缀（"B档"）都认；认不出的走 parse_rating 再判一次
    （复用同一套解析，避免"路由用一套、解析用另一套"两套规则早晚不一致）。
    """
    key = rating.strip().upper()[:1] if isinstance(rating, str) else ""
    if key not in ROUTES:
        key = parse_rating(rating)      # 兜底：中文措辞/"?"/None 全在这里收敛
    return ROUTES.get(key, "use_tool")


def self_rate(question, llm_fn=None, context=""):
    """让模型自评一次，返回 `{"rating", "raw", "ok", "why"}`。

    `llm_fn(prompt) -> str` 由调用方注入（载体层不认识任何具体模型）；
    **`llm_fn=None` 时不许报错**，如实返回
    `{"rating": "?", "ok": False, "why": "没有可用的模型"}` ——
    为什么这一点是硬要求：自测、离线跑、火种没起来的时候都要能走到这一行，
    如果这里抛错，整条对话路径就跟着挂；而"没有模型"本来就该等价于"什么都别硬答"。
    去掉这个分支：没接模型时元认知层会炸掉整轮对话，而不是安静地降级。

    `ok` 的含义是"**真的拿到一个能用的档位**"（A/B/C），`?` 一律 ok=False ——
    调用方据此区分"模型说它没把握"和"模型什么都没说清楚"，后者更该走稳的路。
    """
    prompt = rate_prompt(question, context)
    if llm_fn is None or not callable(llm_fn):
        return {"rating": RATING_UNKNOWN, "raw": "", "ok": False, "why": "没有可用的模型"}
    try:
        raw = llm_fn(prompt)
    except Exception as e:      # noqa: silent-ok — 模型调用失败等同于"没把握"，绝不往上抛
        return {"rating": RATING_UNKNOWN, "raw": "", "ok": False,
                "why": "模型调用失败：%s: %s" % (type(e).__name__, str(e)[:120])}
    text = _normalize(raw)[:_RAW_MAX]
    rating = parse_rating(text)
    ok = rating in RATINGS
    if not text.strip():
        why = "模型没给出任何内容 → 按没把握处理（不猜 A）"
    elif ok:
        why = "自评 %s（%s）→ 走 %s" % (rating, RATING_CN.get(rating, rating), route(rating))
    else:
        why = "解析不出档位（原话：%s）→ 按没把握处理，走 %s" % (text.strip()[:40], route(rating))
    try:
        log_line("selfrate", "rating=%s ok=%s q=%s" % (rating, ok, (question or "")[:40]))
    except Exception:      # noqa: silent-ok — 记日志失败绝不能影响自评结果本身
        pass
    return {"rating": rating, "raw": text, "ok": ok, "why": why}


def apply_route(text, rating, caveat=CAVEAT):
    """按档位给答案加工：B 档加一句"不太确定"，A/C 档原样返回（A 直接答，C 由调用方处理）。

    为什么这个小函数也要留在这里：不加标注的 B 档 = A 档（用户完全看不出区别），
    那自评就白做了。标注文案必须只有一份，散在调用方各处就会出现三种措辞、三种语气。
    去掉它：B 档的"提醒"会被随手忘掉，自评的结果传不到用户眼前。
    """
    t = "" if text is None else str(text)
    if rating == RATING_B and t.strip() and caveat not in t:
        return caveat + "\n" + t
    return t
