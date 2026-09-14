# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 答后交叉检查（元认知 2：同一件事多问几遍，对得上才敢交出去）

【这段为什么这么设计】
    答前自评问的是"你觉得你有把握吗"—— 那是**模型的主观判断**，它自己也会吹。
    答后交叉检查问的是另一个问题：**同一个问题，换个角度问，它答的还是同一件事吗**。
    这条判据是客观的：不需要模型诚实，只需要它前后一致 —— 而"前后不一致"这件事，
    恰恰是编造最典型的症状（编的东西没有内在结构，换个问法就露馅）。
    去掉它会怎样：一个前后自相矛盾的答案会原样交给用户；而"自相矛盾"比"我不知道"
    严重得多 —— 用户对"不知道"是理解的，对"它胡说还不自知"是不再信任的。

【为什么要换角度问，而不是"再问一遍"】
    再问一遍（同一个问题原样再发一次）必然得到同一个复读答案，一致性永远 1.0 ——
    这个检查就等于没做。所以三个角度是三种**不同的推理路径**：
      ① 直接答：拿到基线答案；
      ② 反着问：逼它从"如果相反的说法才对"这一侧走一遍（同一个错误很难在相反路径上重现）；
      ③ 只讲关键事实：剥掉修辞和铺垫，只留人名/时间/数字/结论（编造最爱藏在修辞里）。
    三条路径都落到同一件事上，才叫"一致"。
    去掉角度设计：这个模块会退化成"复读检测器"，永远报一致，永远不产生价值。

【判据为什么这么定（宁严不宽）】
    agree ≥ 0.6            → consistent（一致）
    agree ≤ 0.3            → conflict（矛盾）
    0.3 < agree < 0.6      → **也判矛盾**（不是"说不准"）
    为什么中间地带也判矛盾：矛盾比不确定危险得多。两个答案"半像"的时候，
    我们无法证明它们说的是同一件事，也无法证明不是 —— 而把"半像"当"一致"放出去，
    错了就是编；判成"矛盾"最坏也只是让载体重答一次、附一句提醒。
    只有 1 个答案 → unknown：**一个样本永远不能宣布"一致"**（那等于没做检查还说做了）。

【已知边界（如实写下来，别假装它没有）】
    2-gram 比对的是**字面重合**，它认不出"相反的意思"：
    "小焦有记忆系统"和"小焦没有记忆系统"的字面重合度 0.8，会被判成"一致"。
    为什么不为此加一套否定词判据：中文否定有几十种说法（不/没/非/无/未/别/莫…），
    漏一个否定的代价是"把矛盾判成一致"，加进去写错一个的代价是"把一致判成矛盾"，
    而后者会让每一轮回答都被拉去重答。所以这里只声明边界：
    **交叉检查负责抓"两次答的不是同一件事"（跑题、编造、复读），不负责抓"同一个句式说了反话"。**
    反话类问题由答前自评和健康系统（fact_reversal 症状）去管，那里有前后文可比。
"""
from . import cfg, features, log_line

# 一致性判据（阈值放模块级：调用方要能引用同一个数，而不是各写一份 0.6）
CONSISTENT_MIN = 0.6      # ≥ 这个值 → 一致
CONFLICT_MAX = 0.3        # ≤ 这个值 → 明确矛盾；中间地带（见模块说明）也倒向矛盾

VERDICTS = ("consistent", "conflict", "unknown")

# 判据 → 出口。为什么 unknown 也**允许输出**（output_with_caveat）而不是"拦住不答"：
# 检查没做成（比如只答上来一个角度）不代表答案不能用 —— 那只是"没验证过"，
# 加一句提醒交给用户比直接拒答更有用。去掉这个区分：一次调用失败就整轮不答，代价过大。
PREFER = {
    "consistent": "output",
    "conflict": "reanswer_with_caveat",
    "unknown": "output_with_caveat",
}
PREFER_CN = {
    "output": "直接输出",
    "reanswer_with_caveat": "重答并标注不确定",
    "output_with_caveat": "输出但标注'没做过交叉验证'",
}

# 角度模板：(角度名, 模板)。模板里的 %s 是原问题。
# 为什么是"纯规则拼装、不调模型"：生成角度这件事**本身就是一次判断**，
# 要是也交给模型去生成，就等于"让被检查的人自己出考卷" —— 它完全可以出三道一模一样的题。
ANGLES = (
    ("直接答", "请直接回答这个问题：%s"),
    ("反着问", "换个角度想：如果这个问题里那个说法的**相反**版本才是对的，"
               "那么正确的说法应该是什么？请仍然针对原问题给出你的答案：%s"),
    ("只讲关键事实", "只讲关键事实：用最少的字说出与这个问题有关的事实（人名、时间、数字、结论），"
                     "不要铺垫，不要解释，不要客套：%s"),
    ("换个说法", "把这个问题换一种更直白的说法重新问自己一遍，然后回答"
                 "（要求与原问题的意思一致，不要偷换概念）：%s"),
    ("列要点", "把与这个问题有关的要点一条一条列出来（只列要点，每条一行，不要展开）：%s"),
)


def _want_n(n):
    """把 n 归一成合法的角度数：None → 读配置的 `cross_check_n` → 默认 3；脏值也退回 3。

    为什么夹在 [1, len(ANGLES)]：0 个角度等于没检查（调用方会误以为"检查过了、没事"），
    多于 5 个角度也不会让一致性更可信（再多也只是同一批事实的重复问法），只是白烧 token。
    """
    if n is None:
        try:
            n = cfg().get("cross_check_n")
        except Exception:      # noqa: silent-ok — 配置读不动就用默认角度数
            n = None
    try:
        k = int(n)
    except Exception:      # noqa: silent-ok — n 传了脏值（"3个"等）时退回默认 3，绝不抛
        k = 3
    return max(1, min(k, len(ANGLES)))


def angles(question, n=3):
    """生成 n 个不同角度的问法（**纯规则拼装，不调模型**）。

    返回 list[str]，前 n 个模板依次套用原问题；同一个原问题配不同包装 → 必定互不相同。
    空问题返回 `[]`：没有问题就没有角度 —— 比返回三个"（空问题）"的提示词更诚实，
    调用方看到空列表自然就跳过这次检查（而不是拿空问题去问模型、再拿它答的话当真）。
    """
    q = (question or "").strip()
    if not q:
        return []
    return [tpl % q for _name, tpl in ANGLES[:_want_n(n)]]


def angle_names(n=3):
    """返回本次实际用到的角度名（跟 angles 同一套夹取规则，供日志/报告用）。

    为什么要单独一个函数：如果日志里自己数"用了 3 个角度"、而 angles 实际只给了 2 个
    （比如 n 被夹过），日志就会说一句假话，排查时反而被误导。宁可从同一份模板里取。
    """
    return [name for name, _tpl in ANGLES[:_want_n(n)]]


def similarity(a, b):
    """两段答案的一致性 0~1：中文 2-gram 集合的 **Dice 系数**（纯标准库，不用向量模型）。

    为什么不用向量模型：一致性判据要的是"这两句话是不是在说同一件事"，而不是"语义有多远"。
    向量在中文短句上的相似度基线（0.55~0.67）本来就重叠，用它会把"答对了"和"答跑了"
    混在一个区间里（`core/memory_deep` 里实测过这件事）；而 2-gram 重合对"同一件事"
    有明确区分度，还**不依赖任何模型**（换火种这条判据不用跟着换，这才是载体）。
    为什么用 Dice 而不是 Jaccard：分子算的是重合片段的**两倍**，对长度差异更宽容 ——
    "只讲关键事实"那个角度天生更短，Jaccard 会因为长度差把它判成不一致，
    那不是它答错了，是我们问得短。宽容交给公式，**严格交给阈值**（0.6/0.3 那两刀才是闸门）。
    任一为空 → 0.0：空文本没有任何可比的内容，算 0 而不是 1 ——
    否则"两个没答上来的角度"会被判成"完全一致"，那是最荒唐的一种假一致。
    """
    fa, fb = features(a), features(b)
    if not fa or not fb:
        return 0.0
    return round(2.0 * len(fa & fb) / float(len(fa) + len(fb)), 4)


def _detail(count, fails, agree, hi, lo, verdict):
    """把判据过程拼成一句给人看的中文（**每个数字都是真算出来的**）。"""
    head = "%d 个角度" % count
    if fails:
        head += "（另有 %d 个角度没答上来：%s）" % (len(fails), "；".join(fails[:2]))
    if count < 1:
        return "%s一个可用答案都没拿到 —— 没有可比的东西，如实判 unknown" % (
            ("；".join(fails) + "；") if fails else "")
    if count < 2:
        return ("%s只拿到 %d 个可用答案，样本不够 —— 1 个样本不能说'一致'，"
                "如实判 unknown" % (head, count))
    return ("%s两两平均一致性 %.3f（最高 %.3f / 最低 %.3f）→ 判为%s"
            % (head, agree, hi, lo,
               {"consistent": "一致（≥%.1f）" % CONSISTENT_MIN,
                "conflict": "矛盾（<%.1f 一律按矛盾处理，矛盾比不确定更危险）" % CONSISTENT_MIN,
                "unknown": "unknown"}[verdict]))


def cross_check(question, llm_fn=None, n=3):
    """同一问题按 n 个角度各答一次，比对一致性。

    返回 `{"answers": [...], "agree": float, "verdict": "consistent|conflict|unknown", "detail": "..."}`；
    `llm_fn(prompt) -> str` 由调用方注入，**`llm_fn=None` 时返回 unknown 且不报错**
    （载体不认识任何具体模型；没模型时"没做过检查"就是没做过，绝不假装检查过）。

    agree 的口径：**所有两两组合相似度的平均**。为什么不是最小/最大：
    取最小 → 三次里有一次口误就永远判矛盾，区分度归零（天天报矛盾的告警等于没告警）；
    取最大 → 只要有一对像就算"一致"，正好放过"两个相似、一个完全不同"这种最危险的组合。
    平均是唯一既不放过矛盾、又能容忍单点噪声的折中；真正的严格交给上面那两刀阈值。
    答案不足 2 个（调用失败/模型空回）→ verdict=unknown：**不能拿 1 个样本说"一致"**。
    """
    q = (question or "").strip()
    qs = angles(q, n)
    if not qs:
        return {"answers": [], "agree": 0.0, "verdict": "unknown",
                "detail": "问题为空，没有可交叉检查的角度 —— 如实判 unknown，不假装检查过"}
    if llm_fn is None or not callable(llm_fn):
        return {"answers": [], "agree": 0.0, "verdict": "unknown",
                "detail": "没有可用的模型，无法交叉检查 —— 如实判 unknown，绝不假装一致"}

    answers, fails = [], []
    for i, aq in enumerate(qs, 1):
        try:
            raw = llm_fn(aq)
        except Exception as e:      # noqa: silent-ok — 某个角度失败只是少一个样本，不该炸掉整次检查
            fails.append("第 %d 个角度调用失败（%s）" % (i, type(e).__name__))
            continue
        text = raw if isinstance(raw, str) else ("" if raw is None else str(raw))
        text = text.strip()
        if text:
            answers.append(text)
        else:
            fails.append("第 %d 个角度没答上来" % i)

    if len(answers) < 2:
        detail = _detail(len(answers), fails, 0.0, 0.0, 0.0, "unknown")
        _log(q, "unknown", 0.0, len(answers), detail)
        return {"answers": answers, "agree": 0.0, "verdict": "unknown", "detail": detail}

    pairs = []
    for i in range(len(answers)):
        for j in range(i + 1, len(answers)):
            pairs.append(similarity(answers[i], answers[j]))
    agree = round(sum(pairs) / float(len(pairs)), 4)
    hi, lo = max(pairs), min(pairs)
    if agree >= CONSISTENT_MIN:
        verdict = "consistent"
    elif agree <= CONFLICT_MAX:
        verdict = "conflict"
    else:
        # 中间地带：**故意判矛盾**（宁严不宽）。见模块开头的那段说明。
        verdict = "conflict"
    detail = _detail(len(answers), fails, agree, hi, lo, verdict)
    _log(q, verdict, agree, len(answers), detail)
    return {"answers": answers, "agree": agree, "verdict": verdict, "detail": detail}


def _log(question, verdict, agree, count, detail):
    """把这次检查写进 `logs/metacognition/crosscheck.log`（**只写人读日志，不写 JSONL**）。

    为什么不落 JSONL 档案：档案（`boundary.jsonl`）记的是"自评样本 + 事后对不对"，
    那是**能力边界**的账；交叉检查是即时的过程量，两者混在一个文件里，
    `stats`/`should_use_tool` 的统计口径就会被过程噪音污染（数字再也对不上）。
    过程要留痕就留在日志里；要看结论就去 boundary。去掉这个区分：一本账里混两套口径。
    """
    try:
        log_line("crosscheck", "%s agree=%.3f n=%d q=%s | %s"
                 % (verdict, agree, count, (question or "")[:40], detail[:120]))
    except Exception:      # noqa: silent-ok — 记日志失败绝不能影响检查结论
        pass


def prefer(verdict):
    """判据 → 出口：consistent→output、conflict→reanswer_with_caveat、unknown→output_with_caveat。

    认不出的 verdict（None / 拼错）一律走 `output_with_caveat`：
    "没做过验证"是**唯一诚实**的解释 —— 判据解析不出来时，说"直接输出"是在替一个
    我们根本没做过的检查背书。去掉这个兜底：一个拼错的 verdict 会静默变成"放行"。
    """
    key = verdict.strip().lower() if isinstance(verdict, str) else ""
    return PREFER.get(key, "output_with_caveat")
