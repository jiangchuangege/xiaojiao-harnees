# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 模糊意图（模块 10.4）

【这段为什么这么设计】
    用户说"帮我搞一下"。模型会立刻猜一个意思，然后洋洋洒洒答一大段 ——
    猜错了就是白答，而且用户的感觉不是"这次没答对"，而是"它根本不懂我"。
    真正该发生的事只有一件：**先判断这句话到底清不清楚**。
      · 不清楚 → 反问，并且要给出**能点选的候选问法**（"你是想让我改代码，还是改配置？"），
        让用户一秒钟点一下就能说清，而不是让用户自己组织语言重说一遍；
      · 清楚 → **闭嘴**。对一句信息完整的问句再反问一遍，是纯粹的骚扰。
    所以本模块做的不是"理解用户"，而是"判断自己该不该开口问" ——
    这件事完全可以用规则算出来，不需要模型，也不该交给模型
    （模型天然倾向于"假装自己懂了"，那正是最坏的失败模式）。

【去掉它会怎样】
    系统会稳定地在两种错误之间摇摆：
      · 没有它：对"帮我搞一下"直接编一个答案 → 答非所问，且用户没法表达"我不是这个意思"；
      · 只有"一律反问"：对"请把这段 Python 代码里的死循环改成 for 循环"也反问 → 用户
        会觉得"我都说这么清楚了你还问"，体验比答错更差。
    这两种错误都是**载体缺结构**造成的，换更大的模型只能减少频率、不能消除。

【为什么判据全用词表 + 阈值，而不是让模型给个 0~1 的"模糊度"】
    ① 确定性：同一句话永远同一个分，自测能断言，用户不会觉得"它一会儿懂一会儿不懂"；
    ② 可解释：每个信号都有中文名（"缺宾语"、"含歧义词「搞一下」"），
       `explain()` 能直接说出"我为什么反问你"，出问题查得到；
    ③ 可增长：用户骂过"这也要问"的例子，可以变成词表里的一行（见 `record_case`）。

【数据落盘】（logs/ 已被 .gitignore 忽略，不脏仓库）
    logs/boost/vague.jsonl   被判定过的案例（问题 + 分数 + 信号），"越用越大"的原料
    logs/boost/boost.jsonl   事件流水（走公共 note()）
    为什么把落盘做成**显式的 record_case()**、不在 ambiguity() 里自动写：
    判据函数是热路径（可能每条用户消息调一次），塞进磁盘写会把一个纯函数变成
    有副作用的函数，还会让自测结果依赖"之前跑过什么"。要不要记，由调用方决定。
【绝不删除任何文件】
    本模块只"追加写 + 读"，没有 os.remove / unlink / rmtree，也不做 tmp+rename。
"""
import re

from . import boost_dir, boost_path, norm, cjk_count, bigrams, hits, has_any, weighted_hits, now, note
from . import append_jsonl, read_jsonl, read_json, write_json

__all__ = ["ambiguity", "clarify_candidates", "hypotheses", "should_ask", "explain",
           "record_case", "case_stats"]

# 上面两行 import 里的 `boost_dir` / `weighted_hits` / `read_json` / `write_json`
# 本模块暂时用不上，但仍然从公共层拿而不是各写一份：判据要用的"命中哪些词"
# 必须与 analogy / reasoning 走同一套口径，各写一份必然出现两种口径。
# 去掉这几行改成本地实现：口径立刻分叉，而且没人会同时改两个文件。
# noqa: F401

# ------------------------------------------------------------------ 判据与权重
# 反问的阈值：score ≥ 0.5 才反问。
# 为什么盯在 0.5 而不是更低：误判的代价是不对称的 ——
# 把清楚的问题当模糊 → 多问一句（烦，但用户点一下就能继续）；
# 把模糊的问题当清楚 → 答一大段错的方向（用户要重说一遍，还丢了信任）。
# 两者都不是零成本，所以取中间值；但**宁可多问**（见 ambiguity 的异常兜底）。
_VAGUE_THRESHOLD = 0.5

# 过短的两个口径（两个都要看）：
#   · 中文有效字数 ≤3：中文 2~3 字常常已经是完整一句话（"在吗"），
#     但作为需求它一定不够 —— "帮我"、"好的" 都无法推出要做什么；
#   · 全长 ≤6 字符：抓 "ok"、"hi"、"随便" 这类几乎没有信息量的输入。
# 只看字符数会把"你好"（2 字）和一段完整问题混为一谈；
# 只看中文字数会漏掉纯英文/数字的短输入。所以两个都放，命中任一即算过短。
_SHORT_CJK = 3
_SHORT_TOTAL = 6

# 判据扫描的长度上限：超长输入只拿前 4000 字做判据。
# 为什么要截：判"这句话清不清楚"看开头就够（后面全是补细节），
# 而全文扫描（两百多个词各做一次 find）会把热路径拖慢 ——
# 截断是"确定性的性能兜底"，不是省事。去掉它：一段 10 万字的粘贴文本
# 会让每条消息多花几百毫秒，用户能感觉到卡。
_MAX_SCAN = 4000
# 落盘时问题原文的截断长度（案例是给词表扩充用的样本，不需要全文）。
_CASE_MAX_CHARS = 200

# 各项判据的权重。为什么过短给到 0.45 这么高：
# 一句话只有几个字时，"缺什么"其实是无法判断的（连猜的余地都没有），
# 这是最强的不确定性证据。其余各项都在 0.25~0.35 之间 ——
# 单项都不足以单独触发反问（0.5 阈值），必须**两条以上同时命中**才算真的模糊。
# 这个设计是刻意的：单个信号极容易误伤（"优化一下"里有个"优化"很正常），
# 只有多个信号同时出现，才说明这句话真的没法直接动手。
_W_SHORT = 0.45          # 过短
_W_NO_SUBJECT = 0.25     # 缺主语（不知道谁做/对谁做）
_W_NO_OBJECT = 0.30      # 缺宾语（不知道对什么做）——比缺主语更致命，所以给更高
_W_PRONOUN = 0.25        # 代词没有先行词（不知道"这个"指什么）
_W_VAGUE_WORD = 0.35     # 含歧义词（"搞一下"这类本身就是模糊表达的词）
_W_AMBIG_VERB = 0.25     # 多义动词但没有对象（"优化""处理"可以指十件事）

# ------------------------------------------------------------------ 词表
# 第一人称/称呼：出现它至少说明"谁在说话、为谁做"是清楚的。
# 为什么把"麻烦你""请"也算：它们是明确的委托语气，等价于把主语说清了。
_FIRST_PERSON = ("我", "咱", "俺")
_IMPERATIVE = ("请", "帮忙", "麻烦")

# 事物名词（宾语候选）。判"有没有明确动作对象"就靠它 + 下面那条"把/将"句型。
# 为什么用具体词表而不是词性标注：本项目禁止新增 pip 依赖，
# 而且真正要判的不是"有没有名词"，而是"有没有**可操作的对象**" ——
# "空气""感觉"这种名词无助于动手，反而会让载体误以为说清楚了。
_NOUN_HINTS = (
    "代码", "文件", "函数", "脚本", "变量", "报错", "日志", "配置", "接口",
    "数据库", "表格", "文档", "句子", "文案", "文章", "邮件", "报告", "计划",
    "方案", "设计", "图片", "视频", "音频", "网页", "页面", "按钮", "样式",
    "字体", "颜色", "名字", "标题", "清单", "数据", "程序", "项目", "任务",
    "需求", "流程", "策略", "模型", "提示词", "死循环", "循环", "算法",
    "性能", "内存", "端口", "命令", "终端", "笔记", "目录", "首页",
    "python", "json", "html", "css", "flask", "sql", "api", "git", "excel", "ppt",
)

# 代词。**按长度从长到短排**：同一个位置上"这个事"和"这个"会同时命中，
# `hits` 在位置并列时按 words 的书写顺序取，长形式写前面才能报出更具体的那个 ——
# 否则日志里永远只写"这个"，人看不出到底在说哪类代词。
# 为什么"这段/这句"不算：它们几乎总是带着后面的名词出现（"这段代码"），
# 把它们当代词会让大量清楚的问句被误判成"指代不明"。
_PRONOUNS = (
    "这个事", "这件事", "这个东西", "那个东西", "那件事", "这个", "那个",
    "它们", "它", "这边", "那边", "这里", "那里", "此事", "上述",
)

# 歧义词：**本身就不携带信息**的表达。命中的是"词"，不是"语气" ——
# 用户说"随便"不是在表达模糊，而是真的把决定权交出去了，
# 这时载体该做的恰恰是"给几个选项让他挑"（见 clarify_candidates）。
_VAGUE_WORDS = (
    "弄一下", "搞一下", "优化下", "处理下", "看一下", "改一下", "调整下",
    "优化一下", "处理一下", "整一下", "整整", "那个啥", "随便", "搞一搞",
    "弄一弄", "差不多", "看着办", "你看着办", "弄个", "搞个", "搞点", "弄点",
    "弄好", "搞好", "随便弄", "随便搞", "啥的", "之类", "若干", "咋弄", "咋搞",
)

# 多义动词：单独出现时**可以指十件不同的事**（"优化"是改性能？改文案？改结构？）。
# 只有"光有动词、没有对象"时才算模糊信号 —— 有对象（"优化这个函数"）就不算。
# 为什么不用单个字"改""弄"：单字命中率太高，"改成""弄明白"都会被误伤，
# 而误伤的代价是让清楚的问句被反问（体验最差的一种错）。
_ACTION_WORDS = (
    "调整", "优化", "处理", "搞", "弄", "完善", "润色", "梳理", "规整", "整理",
    "修复", "升级", "改进", "加强", "提升", "弄好", "做好", "跟进", "对接",
    "推动", "落实", "安排", "规划", "重整", "重做", "折腾", "搞定", "改一下",
    "改改", "看一下", "看看", "瞅瞅",
)

# "把/将 + 至少两个字"的句型：出现它就说明宾语被明确说出来了（"把这段代码改成…"）。
# 这是词表之外的第二条宾语判据 —— 只靠词表会漏掉"把那段录音剪一下"这类
# 词表里没有的名词，而那句话其实是清楚的。
_OBJECT_PATTERN = re.compile(r"[把将][^，。；！？,;!?]{2,}")

# 引用符：引号里的内容一定是具体对象（"把'周报'改成'月报'"）。
_QUOTES = ("「", "“", "\"", "'")

# 通用候选问法（兜底池，5 条：任何情况下都要凑得出 3~5 条，否则 UI 会抖）。
# 它们之所以"通用"但仍然能点选：每条都给了明确的二选一或三选一，
# 用户点一下就能继续，不需要自己重新组织语言。
_GENERIC_QUESTIONS = (
    "你要的是能直接用的成品，还是先给结论和步骤就行？",
    "要不要我先按最字面的理解试一版，你再指出哪里不对？",
    "你希望答案长一点（详细解释）还是短一点（只要结论）？",
    "这件事什么时候要：现在就得动手，还是等你补充完信息再做？",
    "如果只能问一句：你这次最想解决的问题是哪个？",
)


# ------------------------------------------------------------------ 内部工具
def _is_cjk(ch):
    """单个字符是不是中日韩表意文字（判官用的最小单位）。"""
    return bool(ch) and ("\u4e00" <= ch <= "\u9fff")


def _cjk_runs(text):
    """把中文连续片段切出来（如 "帮我搞一下" → ["帮我搞一下"]）。

    为什么用 bigram 首尾相接来拼、而不引分词：本项目禁止新增 pip 依赖，
    而这里要的只是"原句里那段中文长什么样"，用来在候选问法里**引用用户自己的话**。
    首尾相接的规则是：下一个 bigram 的第一字 == 当前片段最后一字，就继续拼。
    去掉它（只取整句前 N 字）：候选问法会引用到标点和英文，
    读起来像"你说的「帮我搞一下，」是指"，用户会觉得它没认真看。
    """
    s = norm(text)
    runs, cur = [], ""
    for bg in bigrams(s):
        if len(bg) < 2 or not _is_cjk(bg[0]) or not _is_cjk(bg[1]):
            if cur:
                runs.append(cur)
                cur = ""
            continue
        if not cur:
            cur = bg
        elif bg[0] == cur[-1]:
            cur += bg[1]
        else:
            runs.append(cur)
            cur = bg
    if cur:
        runs.append(cur)
    return runs


def _has_object(scan, nouns):
    """这句话里有没有**明确的动作对象**（有 → 不算缺宾语）。

    三条判据（任一成立即算有）：命中了事物名词词表；出现"把/将 + 内容"句型；
    出现引号包裹的具体内容。
    为什么宁可用三条宽松判据：**误判"有对象"只是少反问一次**（用户顶多觉得它答得粗），
    而误判"没对象"会把一句清楚的话打断 —— 后者体验差得多。
    """
    if nouns:
        return True
    try:
        if _OBJECT_PATTERN.search(scan):
            return True
    except Exception:      # noqa: silent-ok — 正则引擎出问题就当没命中，继续往下判
        pass
    for q in _QUOTES:
        if q in scan:
            return True
    return False


def _has_subject(scan):
    """这句话里有没有主语信息来源（第一人称 / 事物名词 / 委托语气，任一即有）。"""
    return (has_any(scan, _FIRST_PERSON) or has_any(scan, _IMPERATIVE)
            or bool(hits(scan, _NOUN_HINTS)))


def _has_antecedent(scan, pronoun):
    """代词 `pronoun` 在这句话里有没有可指代的具体名词。

    判据：代词**后面紧跟**的名词（"这个文件"）、代词**之前出现过**的名词
    （"那段代码…把它改一下"）、或代词之前出现过引号内容。
    为什么只看同一句：本模块的入参就是一句话（没有多轮上下文），
    所以"先行词"只能在句内找 —— 这会造成"跨句指代"被当成缺先行词，
    但那正是我们想要的保守方向：载体拿不到上下文时，反问一句比猜对了更安全。
    去掉这个检查（见到代词就判模糊）会误伤"把这个函数改成异步"这类清楚的话。
    """
    if not pronoun:
        return True
    i = scan.find(pronoun)
    if i < 0:
        return True
    after = scan[i:i + 8]
    before = scan[:i]
    if has_any(after, _NOUN_HINTS) or has_any(before, _NOUN_HINTS):
        return True
    for q in _QUOTES:
        if q in before:
            return True
    return False


def _keywords(text):
    """从原句里抽"可以引用回去的关键词"（候选问法要用它，别让自己的话听着像另一个人说的）。

    返回 `{nouns, verbs, vague, pronoun, quote, ascii}`，全部按原文出现顺序、去重。
    为什么要有 ascii 这一项：用户说"这个 json 怎么改"时，最该被引用的就是 "json" ——
    中文词表一个都命不中，只有把英文标识符捞出来，候选问法才具体。
    去掉它：候选问法会退化成"你要我改什么？"这种什么都不指的问法，
    用户会觉得"你连我说的 json 都没看见"。
    """
    t = norm(text)
    t_low = t.lower()
    scan = t_low[:_MAX_SCAN]
    out = {
        "nouns": hits(scan, _NOUN_HINTS),
        "verbs": hits(scan, _ACTION_WORDS),
        "vague": hits(scan, _VAGUE_WORDS),
        "pronoun": "",
        "quote": "",
        "ascii": [],
    }
    pron = hits(scan, _PRONOUNS)
    out["pronoun"] = pron[0] if pron else ""
    runs = _cjk_runs(t)
    if runs:
        longest = sorted(runs, key=lambda r: (-len(r), runs.index(r)))[0]
        out["quote"] = longest[:12]
    try:
        for m in re.finditer(r"[A-Za-z][A-Za-z0-9_+#.\-]{1,24}", t):
            s = m.group(0)
            if s.lower() not in [a.lower() for a in out["ascii"]]:
                out["ascii"].append(s)
            if len(out["ascii"]) >= 3:
                break
    except Exception:      # noqa: silent-ok — 抽不出英文词只是少一点具体性
        pass
    return out


def _analyze(text):
    """**唯一的判据实现**：四个对外函数都走这里，绝不各判一套。

    为什么必须收成一个函数：`ambiguity` 说模糊、`explain` 说不模糊，
    这种自相矛盾一旦出现，排查成本极高（两边代码看着都对）。收到一处之后，
    "口径"成了一个可以被单独测试的对象。
    去掉它会怎样：clarify_candidates / hypotheses / explain 各自再实现一遍判据，
    改动权重时必定漏改一处 —— 于是"跟着 reason 去查却查不出原因"。

    返回 `{signals, score, is_vague, facts}`；**任何输入都不抛**
    （空/None → score 1.0，理由见 docstring 末段）。
    """
    t = norm(text)
    facts = {"chars": len(t), "cjk": cjk_count(t), "nouns": [], "verbs": [],
             "vague": [], "pronoun": "", "empty": not t}
    if not t:
        # 没说任何内容就是没说清：这里的"模糊"不是"用户话说不清"，
        # 而是"载体没有任何可动手的信息"。给 1.0 而不是 0.5，
        # 是为了让调用方一眼看出"这是空输入"，而不是"差一点点就清楚了"。
        return {"signals": ["空输入"], "score": 1.0, "is_vague": True, "facts": facts}

    scan = t.lower()[:_MAX_SCAN]
    nouns = hits(scan, _NOUN_HINTS)
    verbs = hits(scan, _ACTION_WORDS)
    vague = hits(scan, _VAGUE_WORDS)
    pron = hits(scan, _PRONOUNS)
    has_obj = _has_object(scan, nouns)
    facts.update({"nouns": nouns, "verbs": verbs, "vague": vague,
                  "pronoun": pron[0] if pron else ""})

    sig, score = [], 0.0
    if facts["cjk"] <= _SHORT_CJK or facts["chars"] <= _SHORT_TOTAL:
        sig.append("过短")
        score += _W_SHORT
    if not _has_subject(scan):
        sig.append("缺主语")
        score += _W_NO_SUBJECT
    if not has_obj:
        sig.append("缺宾语")
        score += _W_NO_OBJECT
    if pron and not _has_antecedent(scan, pron[0]):
        sig.append("代词「%s」缺先行词" % pron[0])
        score += _W_PRONOUN
    if vague:
        # 只把**第一个**歧义词计入权重：一句话里出现三个"随便"，
        # 并不会比出现一个更模糊三倍 —— 那是语言习惯，不是信息量的线性叠加。
        # 但信号里把所有命中的歧义词都列出来，方便日志看出用户的口癖。
        for w in vague:
            sig.append("含歧义词「%s」" % w)
        score += _W_VAGUE_WORD
    if verbs and not has_obj:
        sig.append("多义动词「%s」缺对象" % verbs[0])
        score += _W_AMBIG_VERB
    score = round(min(1.0, score), 4)
    return {"signals": sig, "score": score,
            "is_vague": score >= _VAGUE_THRESHOLD, "facts": facts}


# ------------------------------------------------------------------ 对外主函数
def ambiguity(question):
    """判断 `question` 清不清楚：返回 `{"is_vague", "score", "signals"}`。

    判据与权重见文件顶部常量；这里只负责把结果算出来并保证**绝不抛**。
    为什么异常时按"模糊"兜底、而不是按"清楚"：
      多反问一句的代价是用户点一下；少问一句的代价是答错一大段、还得重说一遍。
      这条不对称是本模块所有兜底方向的依据。
    score 语义：`[0,1]`，是**规则证据的累加和**（不是概率），
    0.5 是本模块约定"够不够模糊"的分界；`is_vague` 就是 `score >= 0.5`，
    与 `should_ask` 的默认阈值一致 —— 两者不一致会让"该不该问"出现两个答案。
    """
    try:
        a = _analyze(question)
        return {"is_vague": bool(a["is_vague"]), "score": float(a["score"]),
                "signals": list(a["signals"])}
    except Exception:      # noqa: silent-ok — 判据出问题时宁可多问一句，不可答错一大段
        return {"is_vague": True, "score": 1.0, "signals": ["判据异常（按模糊兜底）"]}


def clarify_candidates(question, n=5):
    """给出 `n` 条**能点选**的反问候选（`n` 夹到 `[3, 5]`）。

    生成方式全是规则：**先按命中的信号类别挑模板，再把原句里的关键词填进去**。
    关键词来自 `_keywords()`（对象名词 / 动作词 / 歧义词 / 代词 / 英文标识符），
    所以候选问法里会出现用户自己说过的词 —— 这是"它在认真看我这句话"的全部来源。
    为什么必须是"二选一/三选一"而不是"请再详细说明一下"：
      后者等于把组织语言的活推回给用户；而用户来找助手，就是因为不想自己想。
    为什么条数固定给 `n`（而不是"有几个给几个"）：下游要把它渲染成可点选项，
      数量忽多忽少会让 UI 抖动、打断用户的手指记忆。
    `question=None/空` → 走通用候选（不抛）。
    注意：本函数**不判断该不该问**（那是 `should_ask` 的职责）——
    单一职责，否则"该不该问"和"问什么"会各有一套判断，早晚互相矛盾。
    """
    try:
        t = norm(question)
        try:
            k = int(n)
        except Exception:      # noqa: silent-ok — 传了怪东西就按默认 5
            k = 5
        k = max(3, min(5, k))
        a = _analyze(t)
        kw = _keywords(t)
        sig = a["signals"]
        pool = []
        if not t:
            pool.append("你是想让我做点什么？给我一个对象 + 一个动作就行。")
            pool.append("要不你先说一件具体的事，我照着做？")
        else:
            if "过短" in sig:
                pool.append("能再多说一句吗：**对什么**做、**做什么**、**做到什么程度**？")
            if "缺宾语" in sig:
                if kw["nouns"]:
                    pool.append("你要我处理的是「%s」，还是另一份（文件/段落/消息）？" % kw["nouns"][0])
                elif kw["ascii"]:
                    pool.append("你要我动的是这个「%s」，还是它旁边的别的东西？" % kw["ascii"][0])
                else:
                    pool.append("你要我处理的具体是哪一个：代码 / 文档 / 配置 / 数据？")
            if kw["vague"]:
                pool.append("「%s」换成具体动作可以吗：重写一遍 / 修掉报错 / 加个功能 / 只解释？" % kw["vague"][0])
            if any(s.startswith("多义动词") for s in sig):
                v = kw["verbs"][0] if kw["verbs"] else "搞/弄"
                pool.append("「%s」是指哪一件事：改代码 / 只改格式 / 只解释原理 / 先给方案？" % v)
            if "缺主语" in sig:
                pool.append("这件事是你自己动手，还是要我直接做出来？")
            if kw["pronoun"]:
                pool.append("「%s」具体指哪一份：刚才那段代码 / 那个文件 / 那条消息？" % kw["pronoun"])
            if kw["quote"]:
                pool.append("如果按最省事的理解：你要的是「%s」这件事的一份可执行步骤清单吗？" % kw["quote"])
        pool.extend(_GENERIC_QUESTIONS)
        # 去重（保序）+ 截到 k 条。兜底池有 5 条，所以 k ∈ [3,5] 一定凑得满，
        # 不会出现"返回 2 条"这种让下游 UI 猜数量的情况。
        out = []
        for s in pool:
            s = norm(s)
            if s and s not in out:
                out.append(s)
        return out[:k]
    except Exception:      # noqa: silent-ok — 生成候选失败也要保证下游拿到 3 条可用问法
        return list(_GENERIC_QUESTIONS[:3])


def hypotheses(question, n=3):
    """给出 `n` 个**并行假设**（`n` 夹到 `[1, 5]`），每条含假设、答案形态、confidence。

    【confidence 是启发式的，**不是**模型的置信度，也**不是**概率】
      它是"这条假设值不值得先试"的规则分：由命中的信号种类 + `ambiguity` 的
      score 线性推出来（见 `_conf`）。它**没有**校准过，绝不能：
        · 当成概率去和别的来源做加权求和；
        · 用来做阈值判断（"置信度 < 0.5 就丢掉"）；
        · 展示给用户当"我有多确定"。
      它唯一的用途是**排序**（先试哪条）和**日志对比**（同一用户前后是否变清晰）。
      为什么还要给这个字段：模糊意图的价值就在于"多假设并行" ——
      载体可以把几个假设分别往下一步走，看哪条能自洽（这正是"载体承担智力"的做法），
      而排序总得有个数。去掉它，下游只能靠模板顺序猜，且无法记录"变的更清楚了没有"。
    `answer_shape` 是"这条假设成立时答案长什么样"：它让下游能**先对形态**再生成内容 ——
      假设是"只是试探"，答案就该是一句反问而不是三段解释；对不上形态就是白答。
    `question=None/空` → 返回"你还没说要做什么"这条假设 + 通用假设，不抛。
    """
    try:
        t = norm(question)
        a = _analyze(t)
        kw = _keywords(t)
        sc = a["score"]
        sig = a["signals"]
        rows = []          # [(base, assumption, answer_shape)]，顺序即优先级
        if not t:
            rows.append((0.55, "你还没说要做什么（这条消息里没有需求）",
                         "先反问一句「你想让我做什么」，不猜、不展开。"))
        if "过短" in sig:
            rows.append((0.55, "你只是随口一句，还没真想要结果",
                         "一句话反问澄清：对象 + 动作 + 目标，各说一个词就够。"))
        if ("缺宾语" in sig) or any(s.startswith("多义动词") for s in sig):
            rows.append((0.50, "你要我**动手改**现有的东西，而不是只要一段说明",
                         "先列「要改哪几处」，再给改后的片段。"))
        if kw["vague"]:
            rows.append((0.45, "「%s」= 一次实际改动（重写 / 修 bug 这类动手活）" % kw["vague"][0],
                         "先按最小改动给一版，末尾问一句「是不是这个意思」。"))
        if "缺宾语" in sig:
            rows.append((0.40, "对象就是上文里最显眼的那一份（最近提到过的代码 / 文件）",
                         "开头写明「我按 X 理解」，再给针对它的做法。"))
        if kw["nouns"]:
            rows.append((0.45, "你要的是能直接用上的「%s」改动" % kw["nouns"][0],
                         "给最小可运行片段 + 改动点说明。"))
        if any(s.startswith("代词") for s in sig):
            rows.append((0.30, "「%s」指最近一条消息里最相关的那件事" % (kw["pronoun"] or "这个"),
                         "先写出假定的指代对象，再给针对它的做法。"))
        rows.append((0.25, "你要的是思路和结论，不是成品",
                     "先给三条结论要点，末尾问要不要展开。"))
        if not a["is_vague"]:
            rows.insert(0, (0.80, "问题已经说清楚了，按字面理解即可",
                            "直接按字面回答：不反问、不加多余前提。"))
        # 保险池：无论前面命中多少，这几条保证 n ∈ [1,5] 一定凑得满。
        # 凑不满会让下游"少走一条假设"，而少试一条假设等于少一次纠错机会。
        rows.extend([
            (0.20, "你其实是在问「该不该做」，而不是「怎么做」",
             "先给判断和建议，再给做法。"),
            (0.15, "你要一份可以直接照抄的清单或模板",
             "给编号清单，每条一句可执行的话。"),
            (0.18, "你说的对象就是这条消息本身（没有别的上下文）",
             "只看这一句给答案，并声明「仅按这一句理解」。"),
            (0.10, "你想让我先复述理解、等你点头再动手",
             "先用一句话复述需求，再问「对不对」。"),
        ])
        try:
            k = int(n)
        except Exception:      # noqa: silent-ok — 传了怪东西就按默认 3
            k = 3
        k = max(1, min(5, k))
        seen, out = set(), []
        for base, asm, shape in rows:
            if asm in seen:
                continue
            seen.add(asm)
            out.append({"assumption": asm, "answer_shape": shape,
                        "confidence": _conf(base, sc)})
        # 按 confidence 降序；并列时保持上面的书写顺序（Python 稳定排序）→ 确定性。
        out.sort(key=lambda h: -h["confidence"])
        return out[:k]
    except Exception:      # noqa: silent-ok — 生成假设失败也要给下游一个可用的假设
        return [{"assumption": "问题没说清，先按字面最省事的理解试一次",
                 "answer_shape": "先反问一句确认，再动手。",
                 "confidence": _conf(0.5, 0.5)}]


def _conf(base, score):
    """启发式置信度：`base + 0.15 × 判据总分`，封顶 0.95、保底 0.05。

    为什么要跟 score 挂钩（而不是各模板写死一个数）：这句话越模糊，
    "试探性假设"就越该排在前面、"按字面直接答"就越该靠后 ——
    这个单调关系是模糊意图模块唯一能保证的性质，写死就丢了。
    为什么封顶 0.95 而不是 1.0：**载体永远不该声称自己 100% 确定**。
    去掉封顶会怎样：日志里出现一排 1.0，看的人会以为那是概率，进而拿去做判断。
    """
    try:
        v = float(base) + 0.15 * float(score)
        return round(min(0.95, max(0.05, v)), 3)
    except Exception:      # noqa: silent-ok — 算不出来就给一个中庸值，不抛
        return 0.3


def should_ask(question, threshold=0.5):
    """真模糊才反问：**当且仅当** `ambiguity(question)["score"] >= threshold` 时返回 True。

    这条"当且仅当"是本模块对外的硬契约（自测直接断言它）：
      它保证"问"这个动作和我给出的理由**完全一致** —— 不会出现
      "score 只有 0.3 却反问了"，那种情况下用户和开发者都不知道是谁的判断。
    为什么阈值做成参数：不同渠道的容忍度不一样（语音助手打断用户更烦、
    终端里的批处理更怕答错），阈值该由调用方按场景定，但默认必须是 0.5，
    与 `ambiguity` 的 `is_vague` 同源。
    `threshold` 传了非数字 / None / NaN → 退回默认值（绝不抛）。
    """
    a = ambiguity(question)
    try:
        th = float(threshold)
        if th != th:               # NaN：任何比较都是 False，会让"该问"变成"不问"
            th = _VAGUE_THRESHOLD
    except Exception:      # noqa: silent-ok — 阈值传坏就用默认阈值，不抛
        th = _VAGUE_THRESHOLD
    try:
        return bool(a["score"] >= th)
    except Exception:      # noqa: silent-ok — 拿不到分数时宁可问一句
        return True


def explain(question):
    """一句中文说明"为什么判它模糊 / 为什么判它清楚"，给日志和调试用。

    为什么要专门有这么一个函数（而不是让调用方自己拼 signals）：
      日志里真正需要的不是信号的原始列表，而是"信号 + 量化事实 + 结论"三件事，
      缺了量化事实（有效中文字数、命中了哪些对象词）就没法判断
      "这次是不是阈值卡边缘"。边缘案例是调权重的唯一依据，必须被写下来。
      去掉它：遇到"它为什么又问了一遍"只能去读代码，而不是读一行日志。
    实现上**复用 `ambiguity()`**而不是自己再判一次：两处判断必然分叉，
    而分叉之后 explain 给出的理由会和实际行为对不上 —— 那比没有理由更坏。
    """
    try:
        r = ambiguity(question)
        f = _analyze(question)["facts"]
        detail = "有效中文 %d 字 / 全长 %d 字符" % (f["cjk"], f["chars"])
        if f["nouns"]:
            detail += "，命中的对象词 %s" % "/".join(f["nouns"][:3])
        if f["empty"]:
            return "判它模糊：输入为空（%s）；没说的话就是没说清 → 先反问一句。" % detail
        if r["is_vague"]:
            return "判它模糊：命中「%s」；%s；score=%.2f ≥ 阈值 %.2f → 先反问，别猜。" % (
                "、".join(r["signals"]), detail, r["score"], _VAGUE_THRESHOLD)
        return "判它清楚：命中信号 %s；%s；score=%.2f < 阈值 %.2f → 直接回答，不反问。" % (
            "、".join(r["signals"]) if r["signals"] else "无", detail,
            r["score"], _VAGUE_THRESHOLD)
    except Exception:      # noqa: silent-ok — 解释不出来也要给一句话，不能抛
        return "判据计算失败，按模糊处理（宁可多问一句，也别答错一大段）。"


# ------------------------------------------------------------------ 越用越大
def record_case(question):
    """把一次判断追加进 `logs/boost/vague.jsonl`（问题 + 分数 + 信号），返回该记录。

    这就是公式④在本模块的落点：**每次执行结果存回结构**。
    攒下来的案例是将来扩充 `_VAGUE_WORDS` / 调权重的唯一实证来源 ——
    "哪些句子被误当成模糊"这件事，只有落盘才查得出来；不落盘就只能靠回忆。
    为什么不做成自动调用：见文件顶部说明（热路径 + 纯函数不该有副作用）。
    任何输入都不抛；写不进去也照样返回记录（记不上只影响"以后能不能复用"）。
    """
    try:
        t = norm(question)
        r = ambiguity(t)
        rec = {"ts": now(), "question": t[:_CASE_MAX_CHARS], "score": r["score"],
               "is_vague": r["is_vague"], "signals": list(r["signals"])}
        append_jsonl(boost_path("vague.jsonl"), rec)
        note("vague.record_case", score=r["score"], is_vague=r["is_vague"])
        return rec
    except Exception:      # noqa: silent-ok — 记不上不能影响调用方的正常流程
        return {"ts": now(), "question": norm(question)[:_CASE_MAX_CHARS], "score": 0.0,
                "is_vague": True, "signals": []}


def case_stats():
    """读回 `logs/boost/vague.jsonl` 的统计：总数 / 模糊数 / 各信号命中次数。

    为什么要有它：`record_case` 只证明"写了"，`case_stats` 才能回答
    "攒下来有没有用" —— 比如"过短"命中几百次说明用户说话就是短，
    该考虑放宽这条权重；某个歧义词从没命中过说明该从词表里挪走。
    去掉它：落盘的数据永远不会被读，等于白写（这也是很多系统日志的现状）。
    读不动返回全 0 的统计（不是 None）：调用方拿到的永远是同一个结构。
    """
    rows = []
    try:
        rows = read_jsonl(boost_path("vague.jsonl")) or []
    except Exception:      # noqa: silent-ok — 读不动就当作没有案例
        rows = []
    vague, by_sig = 0, {}
    for r in rows:
        try:
            if r.get("is_vague"):
                vague += 1
            for s in (r.get("signals") or []):
                s = norm(s)
                if s:
                    by_sig[s] = by_sig.get(s, 0) + 1
        except Exception:      # noqa: silent-ok — 单条记录坏掉不能连累统计
            continue
    return {"total": len(rows), "vague": vague, "clear": len(rows) - vague,
            "by_signal": by_sig}
