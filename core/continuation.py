# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 无缝续写（无限 3：输出无限）

问题：模型单次只能吐 2000 token。用户要"写 5 万字"，模型**物理上**做不到一次给完。
载体解法：多次请求 + 无缝合并，用户看到的是一段连续输出，**看不出是分了几次**。

载体负责的事（一样都不推给模型）：
  ① 定长度：从任务里解析「3000 字 / 5 万字 / 20000 words」→ 目标总字数
  ② 装上下文：第 1 次给完整任务；第 N 次给「任务 + 已写摘要 + 上段最后 200 字」让模型接着写
  ③ 去重：与已写正文末尾做**最长重叠**比对（后缀=前缀），重叠部分裁掉 —— 这是"无缝"的关键
  ④ 断句：段落结束必须是完整句子；半句回退到上一个句号，残句带入下一轮
  ⑤ 校验：空输出 / 重新开场 / 又短又零重合 → 丢弃重试（≤ max_retries 次）
  ⑥ 提速：**并发预取**下一段 + 缓冲池（段与段之间不留空档）
  ⑦ 停止：模型说「【完成】」/ 达到目标长度 / 用户叫停

模型只干一件事：**接着写下一小段**。它不知道自己在被循环调度。

── 并发预取为什么这么写（踩过就想明白了）────────────────────────────────
预取第 N+1 段，必须知道"第 N 段已经写了什么"（要拿它当衔接锚点、还要拿它做去重）。
所以**不能**让预取线程和主循环同时对着同一份状态写 —— 那样第 N+1 段拿到的锚点是残缺的，
去重也会算错，拼出来就会重句。
这里的做法：**只有一条生成线程**（预取线程），它自己维护一份"影子正文"
（= 已提交正文 + 池子里已生成但还没被取走的部分），一直把池子填到 buffer_size 为止。
主循环只从池子里取、只做合并（去重/断句），从不并发生成。
这样既拿到了预取的速度，又保证每段的锚点都是**确定**的。
"""
import re
import threading
import time
import logging

logger = logging.getLogger(__name__)

# 说明：本模块的日志走 `logging.getLogger(__name__)`，**不会**自动进 `logs/xiaojiao.log`
# （宿主没给这个 logger 装文件 handler）。排查复读策略时曾经一度以为"日志没打"、
# "这条路径没生效"，其实是看错了地方 —— 复读相关的分支现在一律用 `logger.debug/info/warning`，
# 要落盘由宿主的 logging 配置决定，模块自己**不写文件**（临时落盘通道已撤）。


def _degen_detector():
    """拿一个退化检测器（`core/health/degeneration.py`）—— 拿不到就返回 None（功能降级，不报错）。

    为什么放在**这里**（续写的每次生成里）而不是只放在最外层：
    Bug 3 的复读是"某一个请求内部"退化成灾的（2000 token 全烧在复读上）。
    等整篇生成完再查，那一段已经废了、还已经推给前端了。
    每个 `_generate_raw` 各配一个检测器，就能做到"这一段一复读就掐断"。
    """
    try:
        import os
        import sys
        _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if _root not in sys.path:
            sys.path.insert(0, _root)
        from core.health import degeneration as _d
        return _d
    except Exception as e:      # noqa: silent-ok — 检测器拿不到就退化成"不检测"，绝不能中断生成
        logger.debug("退化检测器不可用（忽略）：%s", e)
        return None


def _safe_delta(on_delta, text):
    """推一个小片给前端；推失败绝不能中断生成。"""
    try:
        on_delta(text)
    except Exception:      # noqa: silent-ok — 推流失败只是少显示几个字，不能影响生成
        pass

DONE_MARK = "【完成】"
_TAIL_CTX = 200            # 带上"上段最后 200 字"作为衔接锚点
_SENT_END = "。！？!?；;…"  # 句子结束符（不含逗号/顿号 —— 那些是半句）
_OVERLAP_WIN = 800         # 去重时比对的窗口（字符）
_MIN_OVERLAP = 8           # 小于这个长度的"重叠"多半是巧合，不裁
# 问题 3①：「模型声明完成」只在**已经写了目标篇幅的一大半**时才认。
# 用户实测："要 10000 字，实际 2500-3000 就结束"—— 根因就是模型在第 5 段吐了个【完成】，
# 载体二话不说就收工了。模型对"够不够篇幅"没有概念（它只看得见最后 200 字），
# 这个判断属于载体：**没到 60% 就不算完成**，继续让它接着写。
_DONE_MIN_RATIO = 0.85
# 为什么是 0.85：用户对"参考篇幅"的口径是「写到 8000 自然结束就停（0.8×），
# 写到 12000 还没完就强制收尾（1.2×）」。所以【完成】必须写在 0.85 倍之后才算数 ——
# 定在 0.6 会让"要 10000 字"实际只给 6000（本轮实测就是这么只写到 6576 的）。
# 忽略【完成】继续写的**硬上限**（真正的"什么时候停"由"还在不在长字"决定，见下方 stall 判据）。
# 它只是一道防死循环的保险：正常写作永远碰不到它。
_DONE_IGNORE_MAX = 200
# 连续多少段复读才认定"火种在这个上下文里不行了" → 收口。
# 取 3 的理由：单段复读很常见（模型偶尔打嗝），实测下一段往往就换了说法；
# 连着 3 段都在复读，才是真的进了重复模式 —— 那时继续写只是在烧算力产垃圾。
_DEGEN_STREAK_MAX = 3
# 连续跳过多少段就认输（**空转上界**：宁可如实收口，也绝不让循环停不下来）。
# 为什么必须有它：跳过分支是 `continue`，它**不经过**下面的 `n >= 2000` 段数上限检查 ——
# 一旦"每段都没剩下可用内容"，while True 就会一直转（实测跑测试时直接超时）。
_SKIP_MAX = 12
# 成稿的"定稿规则"：每次续写都带上，别让模型自己在收尾时瞎编。
_FINAL_RULES = ("\n\n【写作纪律】① 人名前后必须完全一致，用第一次出现的写法；"
                "② 对话引号必须成对闭合；"
                "③ 绝对不要写「全书共 X 章」「后续章节将展开」这类目录/说明性句子，"
                "正文就是正文；④ 不要声明完成，写满就停，我会让你接着写。")

_NUM = {"零": 0, "一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
        "七": 7, "八": 8, "九": 9, "十": 10}


def _cn_num(s):
    """把「三」「十五」「二十」这类中文数字转成 int（够用即可）。"""
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if s in _NUM:
        return _NUM[s]
    m = re.fullmatch(r"([一二两三四五六七八九])?十([一二三四五六七八九])?", s)
    if m:
        return _NUM.get(m.group(1) or "一", 1) * 10 + _NUM.get(m.group(2) or "", 0)
    return None


def parse_target_chars(task):
    """从任务里解析用户想要的**总字数**；解析不到返回 None（= 写到模型说完成）。

    支持：3000字 / 3千字 / 5万字 / 两万字 / 20 万字 / 20000 words / 2000 词
    """
    t = (task or "").replace(" ", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*万\s*(?:字|词|words?)", t, re.I)
    if m:
        return int(float(m.group(1)) * 10000)
    m = re.search(r"(\d+(?:\.\d+)?)\s*千\s*(?:字|词|words?)", t, re.I)
    if m:
        return int(float(m.group(1)) * 1000)
    m = re.search(r"(\d+)\s*(?:字|词|words?)", t, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"([一二两三四五六七八九十]+)\s*万\s*(?:字|词)", t)
    if m:
        n = _cn_num(m.group(1))
        return n * 10000 if n else None
    m = re.search(r"([一二两三四五六七八九十]+)\s*(?:字|词)", t)
    if m:
        return _cn_num(m.group(1))
    return None


def overlap_len(a, b, win=_OVERLAP_WIN):
    """a 的后缀与 b 的前缀的**最长重叠长度** —— 无缝拼接就靠它。

    模型"接着写"时几乎总会把上段末尾又抄一遍
    （上段"……他走进房间。" → 本段"他走进房间。屋里很暗……"）。
    直接把两段接起来就出现重复句；这里找出重叠并把第二段的开头裁掉。
    """
    if not a or not b:
        return 0
    A, B = a[-win:], b[:win]
    for L in range(min(len(A), len(B)), 0, -1):
        if A[-L:] == B[:L]:
            return L
    return 0


def cut_at_sentence(text, min_ratio=0.5):
    """切成 (完整句子部分, 残留半句)。整段不成句时原样返回（切不出东西就别切）。"""
    if not text:
        return "", ""
    idx = max(text.rfind(ch) for ch in _SENT_END)
    if idx < 0:
        return "", text
    if (idx + 1) < len(text) * min_ratio:
        return "", text
    return text[:idx + 1], text[idx + 1:]


_SENT_SPLIT = re.compile(r"(?<=[。！？!?；;])")


def split_sentences(text):
    """按句末标点切句（保留标点）。"""
    return [s for s in _SENT_SPLIT.split(text or "") if s.strip()]


def drop_repeated_sentences(chunk, seen, min_len=12):
    """把**整句复读**从本段去掉，返回 (清洗后的段落, 去掉的句数)。

    为什么"末尾重叠裁剪"不够：那只裁得掉**接缝处那一句**。而弱模型（4B）在"接着写"
    时常见的是**整句复读**——第二句、第三句又把同一句话抄一遍。只裁接缝，正文里照样
    会留下重复句，用户一眼就看出"这是拼的"。
    所以每段合并前再过滤一次：只要这个整句（≥ min_len 字）已经出现过，就丢掉。
    `seen` 是跨段累积的集合（调用方维护），段内重复同样会被这一遍挡住。
    """
    out, dropped = [], 0
    for s in split_sentences(chunk):
        t = s.strip()
        if len(t) >= min_len and t in seen:
            dropped += 1
            continue
        if len(t) >= min_len:
            seen.add(t)
        out.append(s)
    return "".join(out), dropped


def drop_repeated_paragraphs(text, seen, min_len=24):
    """把**整段复读**去掉（问题 3 实测：1 万字里出现 55 处紧邻重复段落）。

    为什么句子级去重不够：一轮生成的**多句整段**被重抄时，逐句看每句都"没出现过"
    （因为它们是被一起重抄的，第一次出现时已经加进了 seen）—— 不对，逐句能挡住。
    真正漏掉的是：段落里带了**轻微差异**（多一个空格、少一个标点），逐句比不相等，
    于是整段又被写了一遍。按**段落**归一化后再比，才挡得住这种"几乎一样的整段"。
    """
    if not text:
        return text, 0
    parts = re.split(r"(\n\s*\n)", text)          # 保留分隔符，方便原样拼回
    out, dropped = [], 0
    for p in parts:
        if not p.strip() or re.fullmatch(r"\n\s*\n", p):
            out.append(p)
            continue
        key = re.sub(r"\s+", "", p)               # 归一化：去掉空白再比
        if len(key) >= min_len and key in seen:
            dropped += 1
            continue
        if len(key) >= min_len:
            seen.add(key)
        out.append(p)
    merged = "".join(out)
    merged = re.sub(r"\n{3,}", "\n\n", merged)     # 去掉被删段留下的空档
    return merged, dropped


_STOPWORDS = ("写一篇", "写一个", "写一份", "写一段", "写个", "帮我写", "给我写", "请写", "替我写",
              "帮我", "给我", "请你", "麻烦", "请", "写", "生成", "创作", "来一篇", "一篇", "一个",
              "一份", "一段", "关于", "有关", "左右", "以上", "不少于", "至少", "字", "词", "的",
              "介绍一下", "介绍", "我", "你", "要", "把", "用", "和", "与", "或", "在")


def _keywords(task, limit=12):
    """任务里的**主题**关键词（连续中文/英文片段），用于偏题校验。

    坑（第 3 步单测抓到）：直接把整句里的连续中文抠出来当关键词，抠到的是**指令措辞**
    而不是主题 —— 「写一篇 3000 字的产品介绍」会抠出「写一篇」「字的产品介绍」，
    模型正文里当然不会出现这些，于是每一段都被误判"跑题"、整篇生成不出来。
    现在先把数字与指令/助词剥掉，剩下的才是主题（这里 →「产品介绍」）。
    """
    t = re.sub(r"\d+", "", task or "")
    for w in _STOPWORDS:
        t = t.replace(w, " ")
    kws = re.findall(r"[\u4e00-\u9fff]{2,6}|[A-Za-z]{3,}", t)
    out, seen = [], set()
    for k in kws:
        kl = k.lower()
        if kl in seen:
            continue
        seen.add(kl)
        out.append(k)
        if len(out) >= limit:
            break
    return out


_OPENERS = ("好的，我来", "好的，以下", "以下是", "下面我", "当然可以", "没问题，我",
            "我来为你写", "我将为你", "这是一篇", "《")


def looks_offtopic(chunk, kws):
    """偏题/空转判定（**保守**：只抓明显跑掉的，不误杀正常长文）。

    长文的后段不复述任务关键词是正常的，所以只在"又短、又与关键词零重合"时才判跑题。
    """
    c = (chunk or "").strip()
    if not c:
        return True, "空输出"
    head = c[:40].lstrip("#* \t")
    for p in _OPENERS:
        if head.startswith(p):
            return True, "重新开场（不是接着写）"
    if len(c) < 200 and kws and not any(k in c for k in kws):
        return True, "又短又与任务关键词零重合"
    return False, ""


def _brief(text, limit=180):
    """已写内容的极简梗概（给下一轮当"已经写到哪了"）。"""
    parts = [s for s in re.split(r"(?<=[。！？!?])", text or "") if s.strip()]
    if not parts:
        return (text or "")[-limit:]
    out = parts[0][:80]
    for p in parts[1:]:
        if len(out) + len(p) > limit:
            break
        out += p[:60]
    return out[-limit:]


# ===== 收尾与编号（用户实测："写 10000 字到第八章突然就断了，像断网一样"）=====
_CN_DIGITS = "零一二三四五六七八九"


def _cn_to_int(s):
    """中文数字 → int（支持 一/十/十五/二十/一百零三 这类常见写法）。"""
    s = str(s or "").strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if any(ch not in _CN_DIGITS + "十百" for ch in s):
        return None
    total, cur = 0, 0
    for ch in s:
        if ch == "十":
            cur = (cur or 1) * 10
        elif ch == "百":
            cur = (cur or 1) * 100
        else:
            cur += _CN_DIGITS.index(ch)
    return total + cur


def _int_to_cn(n):
    """int → 中文数字（1→一 10→十 11→十一 21→二十一 100→一百）。够用即可。"""
    n = int(n)
    if n <= 0:
        return str(n)
    if n < 10:
        return _CN_DIGITS[n]
    if n < 20:
        return "十" + (_CN_DIGITS[n % 10] if n % 10 else "")
    if n < 100:
        return _CN_DIGITS[n // 10] + "十" + (_CN_DIGITS[n % 10] if n % 10 else "")
    return str(n)


def renumber_units(text, unit="章"):
    """把重复/回退的「第X章」重排成单调递增，返回 (新文本, 改动处数)。

    为什么这是载体的活：续写的每一次请求都是**独立**的一次生成，模型不知道"上一段已经用到第
    五章了"，于是每段都从「第一章/第二章」重新起头 —— 用户看到的是一篇文章里章节号来回跳
    （实测："第一章…第五章、第二章…第六章、第二章…"）。
    让模型"记住编到第几章"是奢望（它连上一段是靠我们喂的最后 200 字才知道的）；
    **编号是纯机械的，就该载体统一重排**。已经单调递增的正文一个字都不动。
    """
    try:
        pat = re.compile(r"第([零一二三四五六七八九十百\d]+)%s" % re.escape(unit))
        ms = list(pat.finditer(text or ""))
        if len(ms) < 2:
            return text, 0
        nums = [_cn_to_int(m.group(1)) for m in ms]
        if all(n is not None for n in nums) and all(nums[i] < nums[i + 1] for i in range(len(nums) - 1)):
            return text, 0                      # 本来就规范 → 不动
        out, pos, fixed = [], 0, 0
        for i, m in enumerate(ms, 1):
            use_digit = str(m.group(1)).isdigit()
            newno = str(i) if use_digit else _int_to_cn(i)
            out.append(text[pos:m.start()])
            out.append("第%s%s" % (newno, unit))
            pos = m.end()
            if newno != m.group(1):
                fixed += 1
        out.append(text[pos:])
        return "".join(out), fixed
    except Exception:      # noqa: silent-ok — 重排失败就用原文，绝不能因此丢内容
        return text, 0


# ===== 问题 3：长文的四项质检（字数 / 章节 / 引号 / 人名）=====
# 用户实测："要 10000 字，实际 2500-3000 就结束；只 5 章但结尾编造『共 24 章』；
#           引号大量未闭合；人名打错（沈清清舟）。"
# 这四件事**没有一件该指望模型自己做到** —— 它们全是机械校验，属于载体的活。
# （分工和"章节编号重排"完全一致：模型负责写，载体负责让它自洽。）

# 引号/括号配对表：开 → 闭
_QUOTE_PAIRS = (("“", "”"), ("‘", "’"), ("「", "」"), ("『", "』"),
                ("《", "》"), ("（", "）"), ("【", "】"))
# 「目录说明式」结尾：不是正文，却常被模型当正文写进结尾（用户实测："把目录说明当正文"）
_META_PATTERNS = (
    r"(全书|全文|本文|本篇|本书|这篇|这一篇|以上)\s*共\s*[0-9一二三四五六七八九十百千]+\s*[章节回篇字]",
    r"共\s*[0-9一二三四五六七八九十百千]+\s*[章节回]\b",
    r"后续章节(将|会)(展开|介绍|讲述|说明)",
    r"(接下来|下面)(我们)?将(展开|介绍|讲述|说明)(后续|其余|剩下)",
    r"敬请(期待|关注)",
    r"^\s*目\s*录\s*$",
)
# 人名统一时要排除的"功能字"：带这些字的候选块几乎一定是普通词组，不是人名
_NAME_STOP_CHARS = set("的了是在和与也都就而被把对从到着过呢吗吧啊呀哦嗯说道看走来去个好很就不没我有你他她它们这那什么怎么因为所以但是而且如果")


def balance_quotes(text):
    """引号配对：该补的补、该去杂的去掉。返回 (新文本, 修补处数)。

    为什么必须由载体做（用户实测"引号大量未闭合"）：
    引号是**成对**的语法标记，而模型是逐 token 生成的 —— 它开了一个 “ 之后，
    可能在几十个字之后就已经"忘了"自己开过。让模型"记得配对"是反着它的工作方式提要求；
    而配对检查是**纯机械**的：数一遍就知道，补一个字符就能修好。
    去掉它会怎样：整篇小说的对话全是坏的 —— 读者根本分不清哪句是谁说的。

    分寸：**按段落各自配对**（对话引号不会跨段），只做两件事 ——
    ① 段落里"开了没关" → 在段末补上关闭符；
    ② 段落里"关了没开"（多余的关闭符）→ 去掉那一个字符。
    其余一个字都不动（不做任何智能改写，改写是模型的事）。
    """
    if not text:
        return text, 0
    fixes = 0
    out_paras = []
    for para in text.split("\n"):
        p = para
        for op, cl in _QUOTE_PAIRS:
            depth = 0
            buf = []
            for ch in p:
                if ch == op:
                    depth += 1
                elif ch == cl:
                    if depth <= 0:
                        fixes += 1          # 多余的关闭符：去掉它（否则整段配对全错位）
                        continue
                    depth -= 1
                buf.append(ch)
            if depth > 0:
                buf.append(cl * depth)      # 开了没关：在段末补上
                fixes += depth
            p = "".join(buf)
        out_paras.append(p)
    return "\n".join(out_paras), fixes


def strip_meta_ending(text):
    """删掉"目录说明式"的句子（用户实测：结尾把目录说明当正文）。

    为什么必须删：一句「全书共 24 章」出现在小说结尾，等于**当面撒谎** ——
    正文只有 5 章。用户看到的是"它自己都不知道自己写了多少"，比少写更伤信任。
    （章节数由载体数得出来，不该让模型猜；猜测的章节数一律清掉。）
    返回 (新文本, 删掉的句子数)。
    """
    if not text:
        return text, 0
    removed = 0
    keep_lines = []
    for line in text.split("\n"):
        s = line.strip()
        if not s:
            keep_lines.append(line)
            continue
        # 整行就是一句目录说明 → 整行丢掉
        if any(re.search(p, s, re.M) for p in _META_PATTERNS) and len(s) <= 60:
            removed += 1
            continue
        keep_lines.append(line)
    t = "\n".join(keep_lines)
    # 句内出现目录说明 → 只摘掉那一句，前后正文保留
    sents = split_sentences(t)
    out = []
    for s in sents:
        if any(re.search(p, s.strip(), re.M) for p in _META_PATTERNS):
            removed += 1
            continue
        out.append(s)
    return "".join(out), removed


def _cjk_counts(text, lengths=(2, 3, 4), min_count=2):
    """统计所有长度 2~4 的中文片段出现次数（**重叠地数**，用前瞻取子串）。

    坑（本轮实测）：直接写 `[\u4e00-\u9fff]{2,4}` 拿到的是**最长的连续片段**
    （"沈清清听见" 会整块被当成一个候选），而我们要的是"沈清""沈清清"这种**子串**。
    所以必须用前瞻 `(?=(...))` 在**每个位置**都取一次。
    """
    counts = {}
    for L in lengths:
        pat = re.compile("(?=([\u4e00-\u9fff]{%d}))" % L)
        for m in pat.finditer(text or ""):
            g = m.group(1)
            if any(c in _NAME_STOP_CHARS for c in g):
                continue
            counts[g] = counts.get(g, 0) + 1
    return {g: n for g, n in counts.items() if n >= min_count}


def character_names(text, limit=6, min_count=4):
    """从已写正文里抽出"像角色名的词"，给下一段当**提示**用。

    为什么只当提示、不当改写依据：提示写错了模型自己会忽略（代价≈0）；
    改写写错了就是**毁原文**（代价不可逆）。所以这个函数可以宽松。
    """
    try:
        if len(text or "") < 200:
            return []
        counts = _cjk_counts(text, min_count=min_count)
        cands = sorted(counts, key=lambda x: -counts[x])
        out = []
        for g in cands:
            if any(g in o for o in out):     # 是更长候选的一部分 → 留长的那个
                continue
            # 后继字符太单一的多半是普通词组（"忽然亮"后面永远跟"了"），不是名字
            if len(_followers(text, g)) < 2:
                continue
            out.append(g)
            if len(out) >= limit:
                break
        return out
    except Exception:      # noqa: silent-ok — 抽不出来就不提示，不影响写作
        return []


def check_name_consistency(text, min_count=3):
    """人名一致性**检查**：找出"像是同一个人的不同写法"，返回说明列表（**不改文本**）。

    【为什么最后做成"只报不改"—— 本轮实测把一个想当然的做法打回来了】
    第一版是"自动统一"：把出现得多的那个写法当作正名，其余的替换掉。
    结果在一个完全正常的文本上，它把
        「声音又密又急」→「声音密又急」、「忽然亮了一瞬」→「忽然了一瞬」、
        「时候发出沙沙声」→「时候出沙沙声」
    全改坏了 —— 因为"时候/时候发""忽然/忽然亮"在统计上跟"沈清/沈清舟"长得一模一样。
    **没有词典的情况下，二者无法可靠区分。**
    而这两种错的代价完全不对等：
      · 人名不一致 → 读者困惑一下，但**原文是完整的**；
      · 误改正文 → **原文被破坏，不可逆**。
    所以载体在这里的职责是**报告 + 预防**，不是替用户改稿：
      ① 报告：把可疑的不一致列出来（下方返回），写进结果与日志；
      ② 预防：把已出现的名字喂回给下一段的提示词（`character_names`），
         让模型自己从一开始就用同一个写法 —— 这才是"载体优先"该走的路。
    """
    try:
        t = text or ""
        if len(t) < 200:
            return []
        counts = {}
        for m in re.finditer(r"[\u4e00-\u9fff]{2,4}", t):
            g = m.group(0)
            if any(c in _NAME_STOP_CHARS for c in g):
                continue
            counts[g] = counts.get(g, 0) + 1
        cands = {g: n for g, n in counts.items() if n >= min_count}
        groups = {}
        for g in cands:
            groups.setdefault(g[:2], []).append(g)
        notes = []
        for root, members in sorted(groups.items()):
            if len(members) < 2:
                continue
            members.sort(key=lambda x: -cands[x])
            if cands[members[0]] < min_count * 2:
                continue
            notes.append("%s（%s）" % ("、".join("%s×%d" % (m, cands[m]) for m in members[:4]),
                                      "可能是同一个人的不同写法"))
        return notes
    except Exception as e:      # noqa: silent-ok — 检查失败就不报，绝不因为检查而丢正文
        logger.debug("人名一致性检查失败（忽略）：%s", e)
        return []


def _followers(t, tok):
    """紧跟在 tok 后面的那些字符（用来判断"它在句子里扮演的角色"）。"""
    out = set()
    try:
        for m in re.finditer(re.escape(tok), t):
            j = m.end()
            if j < len(t):
                out.add(t[j])
    except Exception:      # noqa: silent-ok — 取不到就当空集（空集一律不放行，见下）
        return set()
    return out


def unify_names(text, min_count=3, apply=True):
    """人名统一：把"同一个人的不同写法"归一成出现最多的那个。返回 (新文本, 说明列表)。

    【第一版为什么把正常句子改坏了 —— 以及这一版靠什么不再改坏】
    第一版只看"出现次数 + 前缀关系"，于是把
        「声音又密又急」→「声音密又急」、「忽然亮了一瞬」→「忽然了一瞬」
    全改坏了：在纯统计上，"忽然/忽然亮"和"沈清/沈清舟"长得**一模一样**。
    这一版加了一道**语法角色**判据（`_followers`）：同一个人的两种写法，会出现在
    **同一批动词前面** ——「沈清**走**」「沈清舟**走**」「沈清**听**」「沈清舟**听**」；
    而"忽然亮"只是"忽然"碰巧接了个"亮"，它后面永远跟着"了"——
    两者的"后继字符集合"几乎不重叠。实测：
      · 沈清 / 沈清舟 → 后继集合交集 {走,听,想,摸,记…} → 判为同一人 ✅
      · 忽然 / 忽然亮 → 交集 {}（亮后面只有"了"）→ 不判 ✅
      · 时候 / 时候发 → 交集 {}（发后面只有"出"）→ 不判 ✅
    再加三道老闸：① 前缀关系；② 主写法 ≥ 2× 从属写法；③ 双方都 ≥ min_count。
    `apply=False` 时只报告不改写（调用方可自行选择保守策略）。
    """
    try:
        t = text or ""
        if len(t) < 200:
            return t, []
        counts = _cjk_counts(t, min_count=min_count)
        if not counts:
            return t, []
        groups = {}
        for g in counts:
            groups.setdefault(g[:2], []).append(g)
        notes = []
        for root, members in sorted(groups.items()):
            if len(members) < 2:
                continue
            members.sort(key=lambda x: -counts[x])
            dom = members[0]
            if counts[dom] < min_count * 2:
                continue
            changed = []
            for v in members[1:]:
                if len(v) != len(dom) + 1 or not v.startswith(dom):
                    # 只处理"正名 + 多一个字"这种最典型的人名走样（沈清 → 沈清舟）
                    continue
                if counts[v] * 2 > counts[dom]:
                    continue                     # 势均力敌 → 可能是两个人，不动
                fa = _followers(t, dom) - {v[len(dom)]}
                fb = _followers(t, v)
                if len(fb) < 2 or len(fa & fb) < 2:
                    continue                     # 语法角色对不上 → 不是同一个人（关键的一道闸）
                if apply and v in t:
                    t = t.replace(v, dom)
                    changed.append("%s→%s×%d" % (v, dom, counts[v]))
                else:
                    changed.append("%s×%d 可能是 %s 的写法" % (v, counts[v], dom))
            if changed:
                notes.append("、".join(changed))
        return t, notes
    except Exception as e:      # noqa: silent-ok — 归一失败就用原文（宁可名字乱，也不能丢正文）
        logger.debug("人名归一失败（忽略）：%s", e)
        return text, []


def drop_final_repeat(text):
    """整篇再查一次复读（含"短句循环"），返回 (新文本, 砍掉字数, 命中)。

    为什么合并期去重挡不住、必须再来一遍（问题 1/3 共同的教训）：
    `drop_repeated_sentences` 的 `min_len=12` —— 短句（"”老人说。" 5 个字）**压根不在它的
    去重范围里**。可实测里最刺眼的恰恰是短句循环："”老人说。" 连着出现七次。
    这不是"去重没做好"，而是**两类问题的分工不同**：
      · 去重处理"段与段之间的搬运"（模型把上一段抄回来）；
      · 复读检测处理"同一段内部的失控重复"。
    最终成稿必须两类都过一遍 —— 少一类，用户就会在成稿里看见它。
    """
    try:
        import os
        import sys
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if root not in sys.path:
            sys.path.insert(0, root)
        from core.health import degeneration as _D
        cut, hit, n = _D.truncate_repeat(text)
        if hit is None or n <= 0:
            return text, 0, None
        cut, _n2 = _D.repair_tail(cut)
        logger.warning("成稿复读检查：命中 %s，砍掉 %d 字", hit, n)
        return cut, n + _n2, hit
    except Exception as e:      # noqa: silent-ok — 查不了就用原文，绝不能因此丢正文
        logger.debug("成稿复读检查失败（忽略）：%s", e)
        return text, 0, None


def clean_ending(text):
    """保证结尾落在**完整句子**上；半句一律回退到上一个句末，返回 (新文本, 砍掉的字符数)。
    为什么必须做（用户实测）：循环是靠"达到目标字数"停的，而最后一段可能正好写到半句 ——
    之前的实现把这半句原样接了上去（`text = written + carry`），于是正文以"……小焦的"收尾，
    用户看到的就是**像断网一样突然截断**。
    宁可少写半句，也不能给一个断掉的结尾：完整比多几个字重要。
    """
    t = text or ""
    if not t.strip():
        return t, 0
    if t.rstrip()[-1] in _SENT_END or t.rstrip().endswith(("\n", "”", "\"", "）", ")")):
        return t, 0
    idx = max(t.rfind(ch) for ch in _SENT_END)
    if idx < 0:
        return t, 0                      # 通篇没有句末标点 → 无从下手，原样返回
    return t[:idx + 1], len(t) - (idx + 1)


CLOSING_ASK = ("这篇内容已经写够了，请为它写一个**自然的结尾**：2~3 句话收束全文，"
               "不要重复前文，不要再开新章节，不要标题，直接写正文即可。")



def written_chapters(text, limit=40):
    """把已写正文里的章节标题列出来（载体维护的"已写清单"，问题 3 的核心）。

    为什么要它：续写的每一次请求都是**独立**的一次生成，模型并不知道"前面已经写到第几章、
    讲过哪些内容" —— 于是它会**从头再讲一遍**（实测：写完第一~八章后又冒出"第二章"，
    同一主题重复三遍）。光靠"最后 200 字"当锚点不够，它看不到全局目录。
    所以载体把**已写章节清单**一起喂回去，并明确要求"接着写新的，不要重复、不要重编号"。
    """
    hits = re.findall(r"第[零一二三四五六七八九十百\d]+[章节][^\n。！？]{0,24}", text or "")
    return [h.strip() for h in hits[-limit:]]


_CONCLUSION_HINTS = ("结语", "总结", "综上", "总而言之", "尾声", "结尾", "以上就是", "最后想说",
                     "写在最后", "收束")


def looks_concluded(text):
    """正文看起来"已经讲完了"吗（末尾出现收尾性标题/措辞）。"""
    tail = (text or "")[-300:]
    return any(k in tail for k in _CONCLUSION_HINTS)


def build_prompt(task, n, written, summary=""):
    """第 1 次给完整任务；第 N 次给「任务 + 已写章节清单 + 已写摘要 + 上段最后 200 字」。"""
    # 【本次要写第几段】显式写进提示词，且必须放在**最开头**。
    # 为什么必须有（日志定位出来的）：确定性测试要用"假模型"精确构造"只有第 2 段退化"，
    # 而假模型**只能看提示词**。原来它靠"提示词前 400 字"猜段号，可 `build_prompt` 的前
    # 400 字是「原任务 + 梗概(300字) + 写作纪律」，**段间完全不变** ——
    # 实测 `CALL seq=37 n=13` 配 `FAKE seg_index=2`：13 段全被猜成第 2 段，
    # "只有第 2 段该退化"变成"段段都退化"，测试自己把断言跑红了。
    # 为什么必须是**开头**而不是追加在末尾：载体会把"上一段原文"整段喂回来，
    # 上一段正文里也带这句话 —— 拼在中间时它会被后面的正文挤走，
    # 读提示词的一侧只能看到"上一段的那个旧段号"（实测 `gen_mark=1` 而真实段号是 10）。
    # 放在开头同时也**对真模型更清楚**：先知道"这是第 n 段"，再读任务与上文。
    _mark = "【本次要写的是第 %d 段】\n\n" % n
    if n == 1:
        return (_mark + "%s\n\n请直接开始写正文（不要解释、不要客套、不要复述我的要求）。"
                "写满就停下，我随后会让你接着写。" % task)
    body = written[-_TAIL_CTX:] if written else ""
    _chs = written_chapters(written)
    _chlist = ("\n\n**你已经写过的章节（这些内容已经写过了，绝对不要重写、也不要重新编号）**：\n"
               + "\n".join("- " + c for c in _chs)) if _chs else ""
    # 人名一致性：把已出现的名字**喂回去**，让模型从头就沿用同一个写法。
    # 为什么这是比"事后替换"正确得多的做法（本轮实测）：事后替换分不清"沈清/沈清舟"和
    # "忽然/忽然亮"，一改就把正常句子改坏；而"告诉它前面用过什么名字"是**零风险**的 ——
    # 提示写错它顶多忽略，绝不会破坏原文。
    _names = character_names(written)
    _namelist = ("\n\n**已经出现过的人物名字（必须沿用同样的写法，不要换字、不要加字）**：\n"
                 + "、".join(_names)) if _names else ""
    _next = ("\n\n请接着写**新的**内容：如果是分章的，就写**下一章**（编号继续往下排，"
             "不要回到第二章）；如果已经讲到收尾了，就直接写出自然的结语。") if _chs else ""
    user = ("%s原任务：%s\n\n你已经写到（梗概）：%s%s%s\n\n"
            "你上一次写到的最后一段原文：\n……%s\n\n"
            "请**紧接着上面最后一句往下写**：不要重抄已写过的内容，不要另起标题，"
            "不要重新开场，不要总结前文。直接续写正文。%s"
            % (_mark, task, summary or _brief(written), _chlist, _namelist, body, _next))
    return user


def _default_call(messages, max_tokens, temperature=0.8):
    """默认模型调用：复用 xiaojiao_app 的 `_llm_targets` + `_llm_post`
    （自带重试 + 云端被拒自动兜到本地大脑，不另起一套）。"""
    try:
        import sys
        app = sys.modules.get("xiaojiao_app")
        if app is None:
            import xiaojiao_app as app
    except Exception:
        return ""
    for t in app._llm_targets():
        r, code, _body = app._llm_post(t, {"model": t["model"], "messages": messages,
                                           "temperature": temperature,
                                           "max_tokens": int(max_tokens)}, timeout=180, tries=2)
        if code == 200 and r is not None:
            try:
                return (r.json()["choices"][0]["message"]["content"] or "").strip()
            except Exception:
                continue
    return ""


def generate_unlimited(task, system="", max_per_chunk=2000, max_total=None,
                       max_retries=3, summary_interval=5, buffer_size=3,
                       parallel_prefetch=True, llm_fn=None, on_chunk=None,
                       should_stop=None, cfg=None, close_with_model=True,
                       stream_fn=None, on_delta=None):
    """按需生成任意长度的文本，段与段之间**无缝**。

      max_per_chunk   单次请求的输出上限（token）
      max_total       目标总**字符数**；None 时自动从 task 解析（"5 万字" → 50000）
      on_chunk(chunk, n, total_chars)  每通过一段回调一次 —— SSE 就靠它
      should_stop()   返回 True 立刻停（用户叫停）
    返回 dict：text/chunks/chars/stopped/elapsed_s/dedup_chars/retries/seams

    【为什么这么设计】它是"无限 3 · 输出无限"的实现：单次请求的输出上限是物理的
    （本地 2000 token），而用户要的篇幅不是。所以把"长文"拆成多次请求，
    每次只带「任务 + 已写摘要 + 上段最后 200 字」，再把每段**当成一次合并**处理
    （去重 / 断句 / 偏题丢弃 / 复读截断），让用户看不到接缝。
    关键取舍：分段是载体的事，**模型永远不知道自己在被分段** ——
    这样换任何模型都不用改这套逻辑，也不会出现"第 X 段"这种技术痕迹（无限 5）。

    【去掉它会怎样】用户要 3000 字就只能拿到 2000 token 左右，
    再往下要就得自己说"继续"——而"继续"之后模型会重抄上一段开头，
    于是出现重复段落、半句话结尾。这就是这个函数诞生前用户实测到的体验
    （"写 10000 字到第八章突然就断了，像断网一样"）。
    """
    llm_fn = llm_fn or _default_call
    if cfg:
        max_per_chunk = int(cfg.get("chunk_size") or max_per_chunk)
        max_retries = int(cfg.get("max_retries") or max_retries)
        summary_interval = int(cfg.get("summary_interval") or summary_interval)
        buffer_size = int(cfg.get("buffer_size") or buffer_size)
        if cfg.get("parallel_prefetch") is not None:
            parallel_prefetch = bool(cfg["parallel_prefetch"])
    if max_total is None:
        max_total = parse_target_chars(task)

    kws = _keywords(task)
    written = ""                     # 已提交正文（只在主线程改）
    carry = ""                       # 上一段切下来的半句
    summary = ""
    seen_sents = set()               # 已经出现过的整句（跨段累积，专治"整句复读"）
    seen_paras = set()               # 已经出现过的整段（归一化后，专治"整段复读"）
    chunks = []
    dedup_chars = 0
    t0 = time.time()
    buffer_size = max(1, int(buffer_size))

    lock = threading.Lock()
    cond = threading.Condition(lock)
    pool = []                        # [(n, raw, done)] 已生成待取
    shadow = ""                      # 池子里那些段落接上去之后的正文（预取线程自己维护）
    next_n = 1
    inflight = [0]                   # 正在生成第几段（0 = 没人在生成）
    stop_flag = threading.Event()
    stop_reason = [""]

    def _generate_raw(n, upto_text, upto_summary):
        """调模型拿一段**原始**输出（不做去重/断句 —— 那是合并时的事）。

        返回 (正文, 失败原因, 是否声明完成)
        `【完成】` 必须在偏题校验**之前**处理：模型说完结了就是完结了，
        不能让"风格校验"把它的收尾句当成跑题丢掉（第 3 步单测抓到的第二只虫子）。

        **Bug 3：这一段里同时做"复读实时检测"** —— 边收边判，命中就立刻停止读流、
        把这一段截断到复读之前的完整句，并置 `degen_flag`（上层据此收口 + 补结尾）。
        """
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        # 【调试日志定位到的真根因】这个标记必须表示**本次调用最终交出去的那份内容**
        # 是不是"复读截断后的产物"，而不是"这一段历史上曾经复读过"。
        # 原来只在命中时写 True、从不写 False —— 于是"第一次尝试复读、重试后拿到干净内容"
        # 这一段会被永久标成复读段：干净内容被当成复读去走"跳过"分支，
        # 反而绕开了正常流程（日志里 `CONSUME seg_degen=True` 配着 303 字干净正文就是它）。
        # 每次调用先清、命中再置位 —— 最后一次尝试的结果就是交出去的内容。
        degen_by_n[n] = False
        _prompt = build_prompt(task, n, upto_text, upto_summary) + _FINAL_RULES
        if degen_flag[0]:
            # 上一次已经复读了 → 这次把"别再重复"明确说出来。
            # 小模型不会自己意识到自己在复读，必须在**提示词**上再拦一道。
            _prompt += ("\n\n（重要：上一次续写陷入了重复。这次请**换一种说法**继续写新的内容，"
                        "不要重复任何已经出现过的句子或短语，也不要重复开场。）")
        if done_ignored[0]:
            # 模型刚说过【完成】但篇幅差得远 → 明确告诉它"还不够，接着写"。
            # 不说的话它会继续每段都吐一个【完成】（它以为自己在收尾），一直空转。
            _prompt += ("\n\n（重要：现在**还没到目标篇幅**，请继续往下写新的内容，"
                        "**不要**声明完成、不要写结语、不要写「全书共X章」。）")
        msgs.append({"role": "user", "content": _prompt})
        logger.debug("续写请求：第 %d 段，提示词 %d 字", n, len(_prompt))
        _det_mod = _degen_detector()
        _det = _det_mod.DegenerationDetector() if _det_mod else None
        if stream_fn and on_delta:
            # ---- 真·流式：边收边推，用户看到的是连续流出，而不是"一大块蹦出来" ----
            # 但开头那一小段必须先攥在手里（闸门）：接缝去重要拿它跟上文末尾比最长重叠，
            # 比完才能确定"哪几个字是不该显示的重复"。闸门一放行，后面就是逐 delta 直推。
            # ---- 同一段里再加一道闸门：复读检测（Bug 3）----
            # 命中就 break —— 一个字都不再读、不再推，剩下的时间留给"补结尾"。
            raw, gate, gated = "", "", False
            try:
                for ch in stream_fn(msgs, max_per_chunk):
                    if not ch:
                        continue
                    raw += ch
                    if _det is not None and _det.feed(ch):
                        logger.warning("续写第 %d 段检测到复读（%s），立刻停止读流并截断",
                                       n, _det.hit)
                        degen_flag[0] = True
                        break
                    if not gated:
                        gate += ch
                        if len(gate) < _TAIL_CTX and not any(t in gate for t in _SENT_END):
                            continue
                        _ov = overlap_len(upto_text or "", gate)
                        if _ov >= _MIN_OVERLAP:
                            gate = gate[_ov:]
                        gated = True
                        if gate:
                            _safe_delta(on_delta, gate)
                        continue
                    _safe_delta(on_delta, ch)
                if not gated and gate:
                    _ov = overlap_len(upto_text or "", gate)
                    if _ov >= _MIN_OVERLAP:
                        gate = gate[_ov:]
                    if gate:
                        _safe_delta(on_delta, gate)
            except Exception as e:      # noqa: silent-ok — 流断了就用已经收到的部分，别整段丢掉
                logger.debug("流式读取中断：%s", e)
            raw = raw.strip()
        else:
            raw = (llm_fn(msgs, max_per_chunk) or "").strip()
            # 非流式没有"边收边判"的机会 → 拿到整段之后补一刀（同样只能事后查）
            if _det is not None and _det.check(raw, where="continuation_single"):
                logger.warning("续写第 %d 段（非流式）检测到复读（%s），截断", n, _det.hit)
                degen_flag[0] = True
        # ---- 截断 + 回退到完整句：绝不让复读的尾巴进正文 ----
        # 「保留前 N 次」而不是砍到复读起点：那几次还读得通，一刀切会让上下文断得生硬；
        # 再由 repair_tail 回退到句号，读起来就是"作者换了个说法接着说"。
        if _det is not None and _det.hit:
            _cut, _dropped = _det.truncated(raw)
            if _det_mod is not None:
                _cut, _t2 = _det_mod.repair_tail(_cut)
            raw = _cut
            logger.info("复读截断：砍掉 %d 字，保留 %d 字（%s）", _dropped, len(raw), _det.hit)
            degen_flag[0] = True
            degen_by_n[n] = True          # 按**段号**记录，预取也不会记错段
            # 【"这一段复读过"的粘性标记】它跟 `degen_by_n` 是**两个不同的语义**，
            # 不能合并：
            #   · `degen_by_n`      = 本次调用**最终交出去**的是不是截断产物（会被重试清掉）
            #   · `degen_ever_by_n` = 这一段的多次尝试里**出现过**复读（只置位、从不清除）
            # 前者用来决定"这段内容还能不能用"，后者用来数"连续几段都出现复读"。
            # 日志实测：同一段重试 3 次（call=2 复读 / call=5 干净），只有前者会被清成 False，
            # 于是连续复读永远数不到 —— 见下面 CONSUME 处的详细说明。
            degen_ever_by_n[n] = True
            logger.debug("续写第 %d 段复读已截断：剩 %d 字 / %s", n, len(raw), raw[:60])
        done = DONE_MARK in raw
        if done:
            raw = raw.replace(DONE_MARK, "").strip()
            # ---- 问题 3①：**别信模型的"完成"** ----
            # 模型只看得见最后 200 字，它对"整篇够不够篇幅"没有任何概念。
            # 实测用户要 10000 字、它写到 2500 就吐【完成】—— 载体照单全收 →
            # 用户拿到的是一篇残篇。判断"够不够"是载体的活：没到 60% 就**不认**这个完成，
            # 继续让它写（同时把 done_ignored 置位，下一轮的提示词里明确告诉它"还没到篇幅"）。
            _wrote = len(upto_text or "")
            _tgt_now = int(max_total) if max_total else 0
            # ---- 什么时候该"不认"这个完成 ----
            # 判据**不是"忽略了几次"**（用一个固定次数当开关，等于用次数代替篇幅：
            # 段短的时候 6 次也填不满 10000 字 —— 本轮实测就是这么只写到 24% 的），
            # 而是**"还在不在往前走"**：
            #   · 只要篇幅不够、且模型一直在产出新内容 → 就一直让它接着写（不封顶）；
            #   · 连续 4 次忽略之间几乎没长字（< 目标的 5%）→ 它在空转，认了这个完成并如实报告。
            # 这样"到达目标篇幅"是**产出的函数**，不是"次数的函数"。
            if _tgt_now and _wrote < _tgt_now * _DONE_MIN_RATIO and done_ignored[0] < _DONE_IGNORE_MAX:
                ignore_marks.append(_wrote)
                _stalled = (len(ignore_marks) >= 4
                            and (ignore_marks[-1] - ignore_marks[-4]) < _tgt_now * 0.05)
                if _stalled:
                    logger.warning("模型连续 4 次声明完成且几乎没写出新内容"
                                   "（最近 4 次之间只长了 %d 字）→ 认输，如实报告篇幅不足",
                                   ignore_marks[-1] - ignore_marks[-4])
                    done_ignored[0] = _DONE_IGNORE_MAX      # 不再忽略
                    stalled_flag[0] = True
                else:
                    done_ignored[0] += 1
                    logger.info("模型声明完成，但只写了 %d 字（目标 %d 的 %.0f%%）→ 不认，继续写"
                                "（第 %d 次忽略）",
                                _wrote, _tgt_now, 100.0 * _wrote / max(1, _tgt_now),
                                done_ignored[0])
                    done = False
                    if not raw:
                        return "", "模型声明完成但篇幅不足", False
            if not raw and not done:
                return "", "模型声明完成但篇幅不足", False
            if not raw:
                return "", "模型声明完成", True
            # 注意这里必须回 `done` 而**不是** `True`。
            # 第一版写死了 True —— 于是上面刚把 done 改成 False（"篇幅不够，继续写"），
            # 这一行又把它当"真的完成了"交上去，主循环立刻收口，**修复形同虚设**。
            # 这类"改了变量却没用上"的错，靠读代码很难发现，是实测跑出来的。
            return raw, "", done          # 收尾句照样收下，由调用方决定停止
        off, why = looks_offtopic(raw, kws)
        if off:
            return "", why, False
        return raw, "", False

    retry_ctr = [0]
    # Bug 3：这一轮续写有没有出现过复读。置位后：① 后续提示词里加"别再重复"；
    # ② 循环收口（不再往下硬写）；③ 强制走"补结尾"，给一个自然的结束。
    degen_flag = [False]
    # 问题 3①：模型已经说过几次【完成】但被我们以"篇幅不够"驳回（用于提示词与上限）
    done_ignored = [0]
    # 每次"忽略完成"时的已写字数 —— 用来判断"它还在往前走，还是在原地空转"
    ignore_marks = []
    # 模型一直在喊完成、却几乎不产出新内容 → 载体认输（如实报告，不无限烧算力）
    stalled_flag = [False]
    # ---- 复读的处置策略（真端到端实测后调整）----
    # 【为什么改成"按段记录 + 连续才收口"】
    # 原来是"只要这一段复读过，立刻收口停写"。实测场景 8 三次里有一次因此只写到 2057 字
    # （目标 3000 的 69%）—— 那一段确实退化了，但**整篇并没有坏**：
    # 模型下一段往往就换过说法了，直接收口等于因为一次打嗝就放弃整篇。
    # 现在：单段复读 → 截断 + **继续写下一段**（提示词里已经带了"别再重复"）；
    #       连续 `_DEGEN_STREAK_MAX` 段都复读 → 才认定"这个火种在这个上下文里已经不行了"，收口。
    # 关键：**按段号记录**。预取是"提前生成后几段"的，用一个共享的布尔量会把
    # "下一段的复读"错记成"这一段的复读"，收口时机就乱了。
    degen_by_n = {}
    degen_ever_by_n = {}
    degen_streak = [0]
    # 上一段交给合并的原始文本（定位用：空结果时要知道"那一段本来长什么样"）
    last_raw = [""]
    # 连续跳过多少段了（防"每段都被跳过"导致 while True 空转 —— 实测超时抓到的）
    skip_ctr = [0]

    def _gen_one(n, upto, summ, attempts):
        """带重试地生成第 n 段的原始输出。返回 (raw, done, why)。

        `done=True` 表示模型这一轮声明了【完成】—— 此时哪怕 raw 为空也算"正常结束"，
        不能被当成"校验不通过"。
        """
        why = ""
        for _ in range(max(1, attempts)):
            raw, w, done = _generate_raw(n, upto, summ)
            if done:
                return raw, True, ""
            if raw:
                return raw, False, ""
            why = w
            retry_ctr[0] += 1
        return "", False, why

    def _prefetch():
        """唯一的预取线程：把池子填到 buffer_size。影子正文只有它动。

        **必须认领 inflight**：否则主循环等不到池子就自己生成一段，两边同时产出同一个 n，
        后到的那段锚点是过期的（不知道前一段已经存在）→ 接缝会错位、还会白烧一次模型调用。
        第 3 步实测就撞上了：chunk 编号出现 [1,2,2]。
        """
        nonlocal shadow, next_n
        while not stop_flag.is_set():
            with cond:
                if len(pool) >= buffer_size or inflight[0]:
                    return
                n = next_n
                inflight[0] = n
                upto = shadow or written
                summ = summary
            raw, done, why = _gen_one(n, upto, summ, max_retries)
            with cond:
                inflight[0] = 0
                if stop_flag.is_set():
                    cond.notify_all()
                    return
                if done:
                    pool.append((n, raw, True))          # 收尾段（可能为空）
                    next_n = n + 1
                    cond.notify_all()
                    return
                if not raw:
                    stop_reason[0] = why or "预取失败"
                    cond.notify_all()
                    return
                pool.append((n, raw, False))
                # 影子正文 = 已提交 + 池内全部：下一段的锚点/去重基准才是对的
                shadow = (written + "".join(p for _, p, _ in pool))
                next_n = n + 1
                cond.notify_all()

    def _merge(raw):
        """去重 + 断句。返回 (可提交片段, 残留半句, 说明)。片段为空时说明里给原因。"""
        nonlocal dedup_chars
        body = raw
        if written:
            ov = overlap_len(written, body)
            if ov >= _MIN_OVERLAP:
                body = body[ov:]
                dedup_chars += ov
        # 再过滤"整句复读"（接缝裁剪管不到段中间/段尾的复读）
        body, dropped = drop_repeated_sentences(body, seen_sents)
        dedup_chars += dropped * 20      # 按句粗估裁掉的字符量，只用于汇报
        # 再过滤"整段复读"（段落里带轻微差异时，逐句比不相等，只有段级归一化比才挡得住）
        body, drop_p = drop_repeated_paragraphs(body, seen_paras)
        dedup_chars += drop_p * 40
        if not body.strip():
            return "", "", "整段都是重复内容"
        complete, rest = cut_at_sentence(body)
        if not complete:
            complete, rest = body, ""     # 整段不成句 → 原样用，别丢内容
        return complete, rest, ""

    while True:
        if should_stop and should_stop():
            stop_reason[0] = "用户叫停"
            break

        # ---- 取一段：优先缓冲池；池空但有人在预取就等它（绝不重复生成同一个 n）----
        item = None
        if parallel_prefetch:
            with cond:
                if pool:
                    item = pool.pop(0)
                elif inflight[0]:
                    deadline = time.time() + 300
                    while not pool and inflight[0] and time.time() < deadline:
                        cond.wait(timeout=0.2)
                    if pool:
                        item = pool.pop(0)
        if item is None:
            with cond:
                n_try = next_n
                inflight[0] = n_try          # 认领，免得预取线程同时产出同一个 n
            raw, done, why = _gen_one(n_try, written, summary, max_retries)
            with cond:
                inflight[0] = 0
                cond.notify_all()
            if not raw and not done:
                # 【日志定位出来的最后一处】这条路径（池空时自己生成）原来**直接判死全篇**，
                # 用的是 `_gen_one` 的 why（"又短又与任务关键词零重合"）。
                # 而复读段被截断后剩下的那 19 个字正好会撞上这条判据 ——
                # 于是"一段复读"就把整篇文章结束了，前面写的全白费。
                # 复读段没剩下可用内容 → 跳过这一段、推进段号继续写（和上面两条分支一致）。
                if degen_by_n.get(n_try, False):
                    skip_ctr[0] += 1
                    if skip_ctr[0] >= _SKIP_MAX:
                        logger.debug("第 %d 段连续跳过 %d 段 → 收口", n_try, skip_ctr[0])
                        stop_reason[0] = ("连续 %d 段都没有可用内容（模型持续复读/空转），已收口"
                                          % skip_ctr[0])
                        break
                    logger.debug("第 %d 段复读且无可用内容（%s）→ 跳过继续写（第 %d 次）",
                                 n_try, why, skip_ctr[0])
                    with cond:
                        next_n = n_try + 1
                        shadow = written + "".join(p for _, p, _ in pool)
                    continue
                logger.debug("第 %d 段无可用内容（%s）→ 收口", n_try, why)
                stop_reason[0] = why or ("校验不通过（连续 %d 次）" % max_retries)
                break
            item = (n_try, raw, done)
            with cond:
                next_n = n_try + 1
                shadow = written + "".join(p for _, p, _ in pool)

        n, raw, done = item
        # 这一段的复读情况（按段号取，预取也不会串）
        # **用 get 而不是 pop**：同一段可能被处理到不止一次（预取线程放进来过、
        # 主循环重试时又生成了一遍）—— pop 会把标记吃掉，第二次读就变成 False，
        # 于是"复读段"被当成正常段、走回老的收口逻辑（确定性测试就是这么抓到的）。
        _seg_degen = bool(degen_by_n.get(n, False))
        # "这一段出现过复读"（粘性）—— 数"连续几段复读"必须用这个，不能用上面那个：
        # 上面那个会被同段的重试清掉，导致整段复读在载体眼里凭空消失（实测 CONSUME
        # seg_degen=False streak=0 配着 WRITE degen_by_n={2: True}）。
        _seg_degen_ever = bool(degen_ever_by_n.get(n, False))
        _prev_head = (last_raw[0] or "")[:200]
        logger.debug("第 %d 段：本段复读=%s 曾复读=%s 连续复读=%d 重试=%d 完成=%s 原始=%d 字 "
                     "（原始开头 %r）",
                     n, _seg_degen, _seg_degen_ever, degen_streak[0], retry_ctr[0], done,
                     len(raw or ""), _prev_head[:80])
        last_raw[0] = raw or ""
        # 【日志定位出来的第三处真根因】"连续复读"这几个字**必须由载体来数**，不能靠
        # "交出去的那一份还带着复读标记"。实测（当时用临时落盘日志 `logs/_degen_debug.log`
        # 抓到的，通道已撤，证据保留在 tools/test_degen_strategy.py 的说明里）：
        #     PROBE2 call=2..4 n=2 degen=True  →  WRITE n=2 degen_by_n={2: True}
        #     PROBE2 call=5    n=2 degen=False →  degen_by_n 被重试清成 {2: False}
        #     CONSUME n=2 seg_degen=False streak=0      ← 整段复读**一次都没被数到**
        # 原因：`_gen_one` 对同一段最多重试 `max_retries` 次，而 `_generate_raw` 每次都先
        # `degen_by_n[n] = False`；只要**最后一次尝试没有复读**，这一段在载体看来就是"干净"的。
        # 于是 `degen_streak` 永远停在 0/1，`_DEGEN_STREAK_MAX = 3` 这条设计好的收口
        # 在实际的复读场景里**一次都不会触发**（写死代码），真正兜底的是 `_SKIP_MAX`。
        # 修法：这一段**出现过**复读就计入连续 —— "连续 N 段都出现复读"本来就是这个意思。
        # 位置也关键：放在所有分支之前，后面每个 `continue`/`break` 路径读到的都是含本段的连续数。
        if _seg_degen_ever:
            degen_streak[0] += 1
        else:
            degen_streak[0] = 0
        # 连续复读到上限 → 认定火种在这个上下文里不稳定，收口（这一步优先于其它终止条件）
        if degen_streak[0] >= _DEGEN_STREAK_MAX:
            logger.warning("连续 %d 段复读（本段曾复读=%s）→ 认定火种在当前上下文里不稳定，收口",
                           degen_streak[0], _seg_degen_ever)
            stop_reason[0] = ("连续 %d 段复读（火种在当前上下文里不稳定），已截断并收口"
                              % degen_streak[0])
            break
        if not raw:
            if _seg_degen:
                # 【确定性测试抓到的关键点】复读被截断后**这一段可能一个字都不剩**
                #（"然后说：嗯。…" 截到前 3 次之后，剩下的既不成句也没内容）。
                # 这时**不能**当成"模型声明完成"收工，也不能让它去消耗 retry 预算 ——
                # 跳过这一段、接着写下一段就对了（提示词里已经带了"别再重复"）。
                logger.info("第 %d 段复读后无可用内容 → 跳过该段，继续写下一段", n)
                continue
            logger.debug("第 %d 段为空且非复读（完成=%s）→ 按『模型声明完成』收口", n, done)
            stop_reason[0] = "模型声明完成"
            break

        # ---- 合并（去重 + 断句）----
        piece, rest, mwhy = _merge(raw)
        if not piece:
            logger.debug("第 %d 段合并后为空（%s，复读=%s，重试=%d，原始开头 %r）",
                         n, mwhy, _seg_degen, retry_ctr[0], (raw or "")[:80])
            if _seg_degen:
                # 同上：整段都是复读、合并后什么都不剩 → 跳过这一段继续写，
                # **不要**去动全篇的 retry 预算（那会把整篇提前判死）。
                logger.info("第 %d 段整段是重复内容 → 跳过该段（不消耗全篇重试预算）", n)
                continue
            retry_ctr[0] += 1
            if retry_ctr[0] >= max(1, max_retries) * 3:
                logger.debug("合并持续为空且重试到上限（%d）→ 收口（%s）", retry_ctr[0], mwhy)
                stop_reason[0] = mwhy or "连续产出重复内容"
                break
            logger.debug("第 %d 段合并后为空 → 重试（第 %d 次）", n, retry_ctr[0])
            continue

        written += piece
        skip_ctr[0] = 0          # 成功提交一段就把"连续跳过"清零
        carry = rest
        chunks.append({"n": n, "chars": len(piece)})
        if summary_interval and (n % summary_interval == 0):
            summary = _brief(written, 300)
        if on_chunk:
            try:
                on_chunk(piece, n, len(written))
            except Exception:
                pass                       # 推流失败不能中断生成

        if done:
            stop_reason[0] = "模型声明完成"
            break
        # ---- 复读的处置（策略见 degen_streak 的说明）----
        # 单段复读：截断已经做完了，**接着写下一段**（提示词会带"别再重复"），不收口；
        # 连续 `_DEGEN_STREAK_MAX` 段复读：这个火种在当前上下文里已经不行了 → 收口 + 补结尾。
        if _seg_degen and degen_streak[0] < _DEGEN_STREAK_MAX:
            logger.info("第 %d 段复读已截断（连续第 %d 段），篇幅 %d 字 → **继续写下一段**",
                        n, degen_streak[0], len(written))
        if degen_streak[0] >= _DEGEN_STREAK_MAX:
            stop_reason[0] = ("连续 %d 段复读（火种在当前上下文里不稳定），已截断并收口"
                              % degen_streak[0])
            break
        # ---- 终止条件（问题 4：按优先级，**不是字数一到就砍**）----
        # 用户原话：「"10000 字"是参考篇幅，不是硬性截断点：写到 8000 字自然结束就停；
        #          写到 12000 字还没完就强制收尾」。
        # 优先级：a 模型【完成】 > b 内容自然结束 > c 用户叫停 > d 达到参考字数×1.2（上限保护）
        _tgt = int(max_total) if max_total else 0
        if _tgt:
            _n = len(written) + len(carry)
            # 「自然结束」的门槛取 **0.8 倍**（用户给的例子正是这个口径：
            #   「写 10000 字 → 写到 8000 字自然结束 → 停在 8000」）。
            # 门槛放到 0.6 会太早收口（实测 10000 参考只写了 6389 就停了，用户会觉得"没写完"）。
            if looks_concluded(written) and _n >= _tgt * 0.8:
                stop_reason[0] = "内容自然结束（%d 字，参考篇幅 %d）" % (_n, _tgt)
                break
            # 硬上限取 **1.05 倍**而不是 1.2 倍：循环是"整段提交"的，一段就有 2000~3000 字，
            # 等真的越过 1.2 倍才停，实际会落到 1.6 倍（实测 10000 字参考 → 16112 字）。
            # 提前在 1.05 倍收口，再加上后面"补结尾"那一小段，最终落在 1.2 倍附近 —— 才是用户要的语义。
            if _n >= _tgt * 1.05:
                stop_reason[0] = "达到参考篇幅的 120%%上限（收口 %d 字 / 参考 %d）" % (_n, _tgt)
                break
        if n >= 2000:                      # 兜底：真要一直写也不会无限循环
            stop_reason[0] = "达到单段数上限（2000 段）"
            break

        # ---- 把下一段预取起来（占住"客户端正在渲染本段"的这段时间）----
        if parallel_prefetch:
            with cond:
                shadow = written + "".join(p for _, p, _ in pool)
            threading.Thread(target=_prefetch, daemon=True).start()

    stop_flag.set()

    # ---- 收尾：绝不让正文停在半句（用户实测："写 10000 字到第八章突然就断了，像断网一样"）----
    # 循环是按"达到目标字数"停的，而停的那一刻最后一段很可能正好写到半句。以前直接
    # `text = written + carry` 把这半句接了上去 → 正文以"……小焦的"收尾，看着就是被截断了。
    # 正确做法分两步：
    #   ① 先请模型补一个**自然结尾**（2~3 句收束）—— 比硬砍半句体验好得多；
    #   ② 万一补不出来（模型空转/报错），就**回退到上一个句末**，保证结尾一定完整。
    _tail_bad = bool(carry) or (bool(written.strip()) and written.rstrip()[-1] not in _SENT_END)
    # Bug 3：复读截断之后**一律**走"补结尾"（哪怕尾巴看起来是完整句）。
    # 为什么：截断点前那一句往往是复读串里的半截（"……然后说：嗯。"），语法完整、语义空洞 ——
    # 不补一个收束句，用户会觉得"这篇东西没头没尾就停了"。
    if degen_flag[0]:
        _tail_bad = True
    trimmed = 0
    if _tail_bad and close_with_model:
        try:
            _msgs = []
            if system:
                _msgs.append({"role": "system", "content": system})
            _n_last = (chunks[-1]["n"] if chunks else 1) + 1
            _msgs.append({"role": "user",
                          "content": build_prompt(task, _n_last, written, summary)
                          + "\n\n" + CLOSING_ASK})
            # 补结尾只需要 2~3 句，给 300 token 足够；给太多会白白把篇幅撑过参考字数（实测溢出）。
            _raw = (llm_fn(_msgs, min(300, int(max_per_chunk))) or "").strip()
            if DONE_MARK in _raw:
                _raw = _raw.replace(DONE_MARK, "").strip()
            _ov = overlap_len(written, _raw)
            if _ov >= _MIN_OVERLAP:
                _raw = _raw[_ov:]
            _piece, _rest = cut_at_sentence(_raw)
            if not _piece:
                _piece = _raw                      # 整段不成句 → 交给下面的 clean_ending 兜底
            if _piece.strip():
                written += _piece
                chunks.append({"n": _n_last, "chars": len(_piece), "closing": True})
                dedup_chars += _ov
                if on_chunk:
                    try:
                        on_chunk(_piece, _n_last, len(written))
                    except Exception:      # noqa: silent-ok — 推流失败不能中断生成
                        pass
                carry = _rest
        except Exception:      # noqa: silent-ok — 补结尾失败就靠 clean_ending 保底
            pass

    text = written + carry
    # **全文再兜一次段落去重**（问题 3 的保证）。
    # 为什么合并阶段挡过了还要再来一遍：合并只处理"循环提交的段"，而**收尾轮**是另一条路径
    # （它不走 _merge），复读的段落能从那里漏进来（实测 1 万字里还残留 5 处）。
    # 这一段是纯文本处理、代价极小，但能把"无重复段落"从"大多数情况成立"变成**一定成立**。
    text, _dp = drop_repeated_paragraphs(text, set())
    if _dp:
        dedup_chars += _dp * 40
    # ---- 问题 3 的四项质检（全部由载体做，一律机械可验证）----
    # 顺序有讲究：先去复读（可能砍掉一大段）→ 再去目录说明（可能删掉结尾句）→
    # 然后才是引号/人名（此时正文已经稳定，修补不会白做）→ 最后回退到完整句。
    quality = {}
    text, _fr, _fhit = drop_final_repeat(text)
    # 质检报告**永远给全字段**（没发现问题就写 0），这样"查过、是干净的"
    # 与"根本没查"在报告里能分清 —— 不然看日志的人没法判断该不该信这篇稿子。
    quality["checked"] = True
    quality["final_repeat_cut"] = _fr
    if _fhit is not None:
        quality["final_repeat"] = {"kind": _fhit.kind, "phrase": _fhit.phrase[:20],
                                   "cut_chars": _fr}
        dedup_chars += _fr
        stop_reason[0] += "；成稿复读已截断（%s）" % _fhit.kind
    text, _meta_gone = strip_meta_ending(text)
    quality["meta_removed"] = _meta_gone
    if _meta_gone:
        stop_reason[0] += "；清掉目录说明式句子 %d 处" % _meta_gone
    text, _qfix = balance_quotes(text)
    quality["quotes_fixed"] = _qfix
    if _qfix:
        stop_reason[0] += "；引号配对修补 %d 处" % _qfix
    text, _names = unify_names(text)
    quality["names_unified"] = _names
    if _names:
        stop_reason[0] += "；人名统一 %s" % "；".join(_names)
    text, trimmed = clean_ending(text)             # 兜底：一定落在完整句子上
    # 章节编号重排：每段独立生成，模型不知道上一段编到第几章，于是章节号会来回跳。
    # 编号是纯机械的，交给载体统一重排（已经规范就不动）。
    text, _renum = renumber_units(text, "章")
    text, _renum2 = renumber_units(text, "节")
    if _renum or _renum2:
        stop_reason[0] += "；重排章节编号 %d 处" % (_renum + _renum2)
    if trimmed:
        stop_reason[0] += "；结尾回退到完整句（砍掉半句 %d 字）" % trimmed
    # Bug 3：这回真的复读过 —— 在结果里如实标出来，界面/病历都看得到（不许悄悄修好不说）
    if degen_flag[0]:
        stop_reason[0] += "；期间检测到复读并已截断"
    # 问题 3①：把"没写到目标篇幅"如实说清楚 —— 不许把残篇说成完稿
    if stalled_flag[0]:
        quality["gave_up"] = True
        stop_reason[0] += "；模型持续空转（一直喊完成却不产出新内容），已停止续写"
    _tgt_final = int(max_total) if max_total else 0
    if _tgt_final and len(text) < _tgt_final * _DONE_MIN_RATIO:
        stop_reason[0] += ("；⚠️ 只写到目标篇幅的 %.0f%%（%d/%d 字）——"
                           "这是**如实报告**，不是达标"
                           % (100.0 * len(text) / max(1, _tgt_final), len(text), _tgt_final))
        quality["under_target"] = {"chars": len(text), "target": _tgt_final,
                                   "ratio": round(len(text) / float(_tgt_final), 3)}
    return {"text": text, "chunks": chunks, "chars": len(text),
            "stopped": stop_reason[0] or "未知", "elapsed_s": round(time.time() - t0, 2),
            "dedup_chars": dedup_chars, "retries": retry_ctr[0],
            "trimmed": trimmed, "renumbered": _renum + _renum2,
            "quality": quality, "done_ignored": done_ignored[0],
            "target_chars": max_total, "seams": max(0, len(chunks) - 1),
            "degeneration": bool(degen_flag[0]),
            "ends_clean": (not text.strip()) or text.rstrip()[-1] in _SENT_END}


def needs_continuation(task, cfg=None):
    """这一轮要不要走续写？—— 只有用户**明确要长文**才走，短回答一律不触发（用户无感）。

    判据：① 任务里写明了目标字数（"写 3000 字…"）；或 ② capabilities 里打开 always。
    """
    cfg = cfg or {}
    if cfg.get("enabled") is False:
        return False
    if cfg.get("always"):
        return True
    t = parse_target_chars(task)
    return bool(t and t >= int(cfg.get("min_chars", 800) or 800))
