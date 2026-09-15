# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 思维流 · 每轮更新

【这段为什么这么设计】
    思维状态必须是**演进**的，不是每轮**重新生成**的。
    区别很关键：重新生成 = 每轮都从头理解一次（那正是"每轮重读历史"的老毛病，
    只是换了个名字）；演进 = 在上一轮的基础上加/改/删。

    所以 `after_user()` 和 `after_assistant()` 都遵守同一套动作：
        · 话题：**变了才换**，没变就沿用（沿用才叫"接着聊"）
        · 理解：新事实**并进**去，不覆盖旧的（人也是慢慢了解另一个人的）
        · 疑问：新问题进队列，**上限 3 条**，FIFO 淘汰（悬而未决不能无限堆）
        · 语气：按本轮信号调整（情绪词→共情，事实问答→专注）
        · 没说出口的话：只在**这一轮确实有**时才记（截断/被跳过），
          而且下一轮用掉就该清掉 —— 记着不放会变成"永远在惦记同一件事"。

【为什么全用规则、不调模型】
    这段代码在**每轮对话的入口/出口**上跑。调模型意味着每轮多两次往返
    （慢 + 花钱 + 可能失败），而它要做的判断都是粗粒度的
    （"话题变没变""这句话带情绪吗"）—— 规则足够，且**确定性可测**。
    真要更细的语义理解，应该是"记忆检索"和"模型自己"的事，不该塞进状态维护里。
"""
import re
import time

from .state import (MAX_OPEN_QUESTIONS, MAX_THOUGHTS, MAX_UNSAID, TONES,
                    MAX_UNDERSTANDING)

# ---------------- 话题识别：从这句话里抽出"在聊什么" ----------------
# 为什么不用关键词硬匹配：话题是**语义级**的东西（"在聊概率题"而不是"出现了'概率'二字"），
# 但载体这层拿不到语义向量（那要调模型/embedder）。这里的折中是：
# **领域词表 + 取最长的那个名词短语**，并且**话题只加不减**（见 `after_user`），
# 于是"接着聊"天然成立 —— 话题不会因为一句话里没出现那个词就被清空。
_TOPIC_HINTS = (
    ("概率统计", ("概率", "组合", "排列", "期望", "统计", "随机", "抽样", "分布")),
    ("工具能力", ("工具", "插件", "能力", "有哪些", "功能")),
    ("抓取网页", ("抓", "爬", "网页", "网址", "http", "robots", "抓取")),
    ("代码编程", ("代码", "函数", "报错", "调试", "python", "接口", "sql", "部署")),
    ("写作长文", ("写", "文章", "小说", "故事", "报告", "文案", "开场白")),
    ("记忆与画像", ("我叫", "记住", "上次", "之前说", "记得", "我的名字")),
    ("天气时间", ("天气", "气温", "下雨", "几点", "日期")),
    ("新闻资讯", ("新闻", "热点", "资讯", "动态")),
    ("系统讲解", ("三次握手", "原理", "机制", "为什么", "解释", "讲讲", "什么是")),
)

# 情绪 → 语气
_EMO_SAD = ("累", "烦", "难受", "难过", "崩溃", "委屈", "焦虑", "压力", "emo", "不开心")
_EMO_HAPPY = ("开心", "高兴", "爽", "太好了", "棒", "顺利", "哈哈", "笑死", "😄", "🎉")
# 事实类问题（语气=专注，温度也低）
_FACT_Q = ("是什么", "什么是", "多少", "怎么算", "等于", "区别", "为什么", "原理",
           "机制", "定义", "能不能", "是否")
# 闲聊信号（语气=轻松，温度高）
_CHAT_WORDS = ("在吗", "你好", "嗨", "哈喽", "聊聊", "陪我", "无聊", "随便说", "嘿嘿")

# 用户事实抽取（"我叫张三，在济南做后端开发" → 名字 / 城市 / 职业）
_FACT_PATTERNS = (
    ("名字", r"(?:我叫|名字(?:是|叫)|叫我)\s*([\u4e00-\u9fa5A-Za-z]{2,8})"),
    ("城市", r"(?:住在|在|来自|老家在|搬到)\s*([\u4e00-\u9fa5]{2,6}?)(?:做|工作|上班|生活|，|,|。|$)"),
    ("职业", r"(?:做|干|是)\s*([\u4e00-\u9fa5]{2,8}?(?:开发|工程师|设计|运营|产品|测试|老师|医生|学生))"),
    # ⚠️ 偏好必须锚定"**我**喜欢/爱/讨厌"，不能只匹配"喜欢" ——
    #   否则"我喜欢写 Python"里的 `我喜欢` 会被当成"在说别人喜欢"，
    #   抽出来的是 `写 Python`（测试当场抓到：期望「偏好：…」却抽到「写 Python」）。
    ("偏好", r"我(?:喜欢|最爱|爱|讨厌|不喜欢)\s*([^\s，,。！？、]{1,12})"),
)


_tool_cache = {"names": None, "ts": 0.0}

# ---------------- 疑问句判据（**画像只能由陈述句更新**）----------------
# ① 为什么必须有这套判据（用户实测的真 bug，性质是"假记忆"）：
#   `_FACT_PATTERNS` 只认"我叫/住在/喜欢"这种**句式**，不认**语气**。于是
#     "我叫什么名字来着？" → 抽出 `名字：什么名字来着`
#     "我现在住在哪个城市？" → 抽出 `城市：住在哪个城市`
#   这两条都是**问题**，却被当成"用户说过的事实"存进了画像。更糟的是：
#   画像注入比检索到的记忆**更强势** —— 实测问"我叫什么名字"，检索明明捞回了
#   "我叫张三"，模型仍然答"你叫王五"（因为画像里有一条更"近"的名字类事实）。
#   也就是说：**一条假记忆不是安静地躺着，它会顶掉正确答案。**
# ② 去掉会怎样：用户每问一次"我叫什么名字"，画像就脏一条；
#   问得越多错得越狠 —— 而"记错用户是谁"是这套系统里最不可接受的错。
#   所以这里的策略是**宁可少记，绝不记错**：拿不准就当作疑问句，不记。
_Q_WORDS = ("什么", "哪个", "哪些", "哪一", "哪儿", "哪里", "谁", "怎么", "怎样", "如何",
            "为什么", "多少", "多久", "多大", "几时", "几个", "几号", "几点", "几年", "几岁",
            "几位", "是否", "能不能", "可不可以",
            "要不要", "该不该", "有没有", "是不是", "对不对", "好不好", "行不行", "贵姓")
_Q_TAIL = ("吗", "呢", "吧", "么")          # 句尾疑问语气词（中文里大量疑问句不写问号）


def _is_question(s):
    """这一句是不是**在问**（而不是在说）？

    三条判据，命中任意一条就算问：
      ① 带问号（？/?）—— 最直接；
      ② 句尾是疑问语气词（吗/呢/吧/么）—— "你叫什么名字呢" 这种不写问号的；
      ③ 句子里有疑问词（什么/哪个/谁/哪里/怎么/为什么/多少…）
         —— "我叫什么名字来着" 既没问号、句尾也不是语气词，只有这条抓得住。
    """
    t = str(s or "").strip()
    if not t:
        return False
    if "？" in t or "?" in t:
        return True
    body = t.rstrip("。！!.~…、,，；; \t")
    if body and body[-1] in _Q_TAIL:
        return True
    return any(w in t for w in _Q_WORDS)


def _clauses(text):
    """按标点切成小句，**标点保留在句尾**。

    【为什么必须切小句、而且不能把标点切掉】
      疑问是**逐句**的属性，不是整段的：「我叫张三，你叫什么名字？」前半句是陈述、
      后半句是疑问 —— 整段一起判就会把"张三"也丢掉（少记），或者反过来把问题也记下（记错）。
      而标点**必须留在句尾**：如果把「我叫张三？」切成「我叫张三」，
      `_is_question` 就再也看不到那个问号，反过来会把问句当陈述记下来 ——
      这个坑正是本次要修的那个 bug 的翻版（判据被自己切没了）。
    """
    out, buf = [], ""
    for ch in str(text or ""):
        buf += ch
        if ch in "，,。；;！!？?\n":
            if buf.strip():
                out.append(buf.strip())
            buf = ""
    if buf.strip():
        out.append(buf.strip())
    return out


def _mentions_tool(text):
    """这句话里有没有**具体的工具名**（net_ip / run_command / archify_…）？

    为什么要这一条（验收实测）：聊工具时用户问"给我解释一下 net_ip 是干嘛的" ——
    句子里既没有"工具"也没有"能力"，只有**一个工具名**，
    于是话题被"解释"抢成了「系统讲解」，思维的线就断了。
    而"提到了某个工具名"本身就是最强的"还在聊工具"证据。

    工具表**惰性从主程序取**（拿不到就退回空表）——
    mind_stream 必须能独立 import，所以不能在这里 `import xiaojiao_app`；
    但话题识别又偏偏需要"有哪些工具名"，所以用"取不到就少一条判据"的软依赖。
    """
    import time as _t
    now = _t.time()
    if _tool_cache["names"] is None or now - _tool_cache["ts"] > 300:
        names = []
        try:
            import sys as _sys
            app = _sys.modules.get("xiaojiao_app")
            if app is not None and hasattr(app, "all_tool_names"):
                names = [str(n) for n in (app.all_tool_names() or []) if n]
        except Exception:      # noqa: silent-ok — 取不到工具表就少一条判据，不影响其它话题
            names = []
        _tool_cache["names"] = names
        _tool_cache["ts"] = now
    s = str(text or "")
    for n in (_tool_cache["names"] or []):
        if len(n) >= 3 and n in s:
            return True
    return False


def _topic_of(text, current=""):
    """判断这句话属于哪个话题；判不出返回 ""（**不硬塞**）。

    判据顺序（这里踩过一次坑，值得记下来）：
      ① **延续优先**：如果当前话题的关键词又出现了，就**留在原话题**。
         实测：聊工具时用户问"给我解释一下 net_ip 是干嘛的" ——
         句子里有"解释"，而"系统讲解"那组也含"解释"，于是话题被从「工具能力」
         抢成了「系统讲解」，下一步状态就断线了。可这句话明明**还在聊工具**。
      ② 否则按**命中数**取最强的一组（不是按表里的先后）。
      ③ 都没命中返回 ""，由调用方**保留旧话题**。
    """
    s = str(text or "")
    # 提到具体工具名 → 直接算"工具能力"（最强的延续证据，见 `_mentions_tool` 说明）
    if _mentions_tool(s):
        return "工具能力"
    if current:
        for name, kws in _TOPIC_HINTS:
            if name == current and sum(1 for k in kws if k in s) > 0:
                return current                      # ① 延续
    best, best_n = "", 0
    for name, kws in _TOPIC_HINTS:
        n = sum(1 for k in kws if k in s)
        if n > best_n:
            best, best_n = name, n
    return best


def _facts_of(text):
    """抽"关于用户的事实"（名字/城市/职业/偏好）。抽不到返回 []。

    **只有陈述句才抽**（见 `_is_question` 的说明）：
    逐小句判语气，疑问句整句跳过 —— 否则"我叫什么名字来着"会被记成 `名字：什么名字来着`。
    一条假记忆会顶掉正确答案，所以这里一律**宁可少记，绝不记错**。
    """
    out = []
    for c in _clauses(text):
        if _is_question(c):
            continue                        # ← 疑问句不参与画像（本函数存在的全部意义）
        for label, pat in _FACT_PATTERNS:
            for m in re.finditer(pat, c):
                v = (m.group(1) or "").strip()
                # 抽出来的值本身也不能是疑问（"我住在这里是哪里"这类句子结构怪但抓得到）：
                # 值里带疑问词 = 这个"事实"其实是问题的一部分，整条丢掉。
                if v and len(v) <= 12 and not any(w in v for w in _Q_WORDS):
                    out.append("%s：%s" % (label, v))
    return out


def _tone_of(text, prev_tone="neutral"):
    """按本轮信号定语气。**判不出来就沿用上一次**（不是打回 neutral）。

    为什么沿用：语气是"当前状态"，不是"这句话的属性"。
    用户上一条在倾诉，这一条只是"嗯"，语气仍应是共情 ——
    打回 neutral 会让状态失去连续性，那正是这个模块要解决的问题。
    """
    s = str(text or "")
    if any(w in s for w in _EMO_SAD):
        return "empathetic"
    if any(w in s for w in _EMO_HAPPY):
        return "playful"
    if any(w in s for w in _FACT_Q):
        return "focused"
    if any(w in s for w in _CHAT_WORDS):
        return "casual"
    return prev_tone if prev_tone in TONES else "neutral"


def _has_question(text):
    """这句话里有没有"悬而未决的问题"（问号 / 疑问词）。

    为什么连"疑问词"也算：中文里"你为什么这样想"经常不写问号。
    而"悬而未决"记的是**用户的疑问**（载体要记着回答它）。
    """
    s = str(text or "")
    if "？" in s or "?" in s:
        return True
    return any(w in s for w in ("为什么", "怎么", "如何", "是不是", "能不能", "要不要",
                                "该不该", "什么", "哪里", "哪个"))


def after_user(st, text):
    """**用户说完一句之后**更新状态。返回新状态（就地改，也返回）。

    演进规则（每一处都对应一个"为什么"）：
      · 话题：**变了才换**。没变就沿用 —— 沿用才叫"接着聊"。
        判不出话题时**保留旧话题**（用户说"我要全部的"，不该把"工具能力"这个
        正在聊的话题清空 —— 那会让下一句失去上下文）。
      · 理解：新事实并进去，去重后保留最近 6 条。
      · 疑问：有疑问才入队，超过 3 条丢最老的。
      · 语气：按本轮信号，判不出沿用。
      · 轮数 +1。
    """
    st = st or {}
    s = str(text or "")

    t = _topic_of(s, st.get("current_topic") or "")
    if t:
        st["current_topic"] = t
    # 判不出话题 → 保留原话题（见上）

    facts = _facts_of(s)
    if facts:
        cur = list(st.get("user_understanding") or [])
        for f in facts:
            if f in cur:
                continue
            # 【按"键"合并，不是按整串去重 —— 这是一处真实 bug 的修复】
            #   画像里的事实都是「键：值」形状（`名字：张三` / `城市：济南` / `职业：后端开发`）。
            #   原来的写法只在**整串相同**时才去重，于是有两个后果：
            #     ① 用户改口（"我叫李四"）会**多出一条** `名字：李四`，与 `名字：张三` 并存，
            #        模型不知道该信哪条；
            #     ② 更关键的是 —— `inject.py` 只注入**最后 4 条**。只要之后又攒了几条别的理解，
            #        `名字：张三` 就被**挤出注入窗口**，表现就是用户实测的那句
            #        「我一开始就告诉你了我是张三」，**说两轮就不认识了**。
            #   改成按键覆盖：同名键只留最新一条；键的种类天然有限（名字/城市/职业/偏好…），
            #   不会被一次性理解挤掉。
            key = f.split("：", 1)[0] if "：" in f else ""
            if key:
                cur = [x for x in cur
                       if not (isinstance(x, str) and x.startswith(key + "："))]
            cur.append(f)
        st["user_understanding"] = cur[-MAX_UNDERSTANDING:]

    if _has_question(s):
        q = list(st.get("open_questions") or [])
        item = s[:60]
        if item not in q:
            q.append(item)
        st["open_questions"] = q[-MAX_OPEN_QUESTIONS:]

    st["tone_state"] = _tone_of(s, st.get("tone_state") or "neutral")
    st["turn_count"] = int(st.get("turn_count") or 0) + 1
    st["last_updated"] = time.time()
    return st


def after_assistant(st, text, truncated=False, skipped=""):
    """**小焦说完之后**再更新一次：记"我刚才在想什么"、以及"没说出口的话"。

    · recent_thoughts：记**这轮的思路**（不是原话）——
      为什么不留原话：原话已经在会话历史里了，状态里再放一份既费 token 又重复；
      这里要的是"我刚才在琢磨什么"，一句摘要就够（人回想时也不是逐字复述）。
    · unsaid：**只在真的有**时记（`truncated=True` 表示被截断/提前收口，
      `skipped` 是被跳过的那段内容）。这是需求里明确要的"没说出口的话"。
      下一轮用掉就清（见 `consume_unsaid`）—— 一直记着会变成"永远惦记同一件事"。
    """
    st = st or {}
    s = str(text or "").strip()
    if s:
        head = re.sub(r"\s+", " ", s)[:60]
        th = list(st.get("recent_thoughts") or [])
        item = "聊到「%s」时我回应了：%s" % (st.get("current_topic") or "这个话题", head)
        if item not in th:
            th.append(item)
        st["recent_thoughts"] = th[-MAX_THOUGHTS:]

    if truncated or skipped:
        u = list(st.get("unsaid") or [])
        note = str(skipped or "").strip()[:60] or "有一处没展开"
        item = "没说完：%s" % note
        if item not in u:
            u.append(item)
        st["unsaid"] = u[-MAX_UNSAID:]
    st["last_updated"] = time.time()
    return st


def consume_unsaid(st, keep=False):
    """取出并**清空**"没说出口的话"（默认取出即清）。

    为什么要清：它表达的语义是"我正惦记着这件事，下次有机会说"。
    如果一直留着，每一轮提示里都会出现它 —— 模型会反复往那件事上带，
    用户感觉像"这 AI 卡住了"。用掉（或用户换话题）就该放下。
    """
    st = st or {}
    u = list(st.get("unsaid") or [])
    if not keep:
        st["unsaid"] = []
    return u


def reset(sid_st):
    """清空状态（用户说"重新开始/换个话题聊"时用）。**只清内容，不动 schema。**"""
    st = sid_st or {}
    for k in ("current_topic", "user_understanding", "recent_thoughts",
              "open_questions", "unsaid"):
        st[k] = []
    st["current_topic"] = ""
    st["tone_state"] = "neutral"
    st["turn_count"] = 0
    return st
