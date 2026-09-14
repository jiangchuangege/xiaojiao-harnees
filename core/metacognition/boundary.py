# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 能力边界档案（元认知 3：把"它哪块不行"记成一本能查的账）

【这段为什么这么设计】
    前两个模块是**当场**的判断（答前自评、答后检查），但它们都只看得到眼前这一轮。
    真正让系统变聪明的是**跨轮次的记忆**：上个月在"某类问题"上自评有把握却答错了，
    这个月遇到同类问题就该直接去走工具，而不是让模型再赌一把。
    人靠经验做到这件事；载体的做法就是把每次自评 + 事后对不对如实落盘，再回来查这本账。
    去掉它会怎样：同一个坑一遍遍踩，而且**谁都不知道它错过**（没有账，连人都没法复盘）。

【"自评 A 却答错"为什么是这本账里最值钱的一条】
    C 档（没把握）只是"它知道自己不行"，那是诚实，代价可控。
    A 档答错才是真正的灾难：**它很有把握地编了一个**，用户最容易信的就是这一种。
    所以 should_use_tool 把这一条单独拎出来判 —— 只要同类问题上出现过一次"自评 A 却答错"，
    以后这类问题直接走工具（工具慢一点，但不会编）。

【样本不足宁可不动】
    一条 C 就说"这类问题我都没把握"，是**过度归纳**：可能只是那天那一个问题难。
    所以判"以后走工具"至少要有 3 条同类样本（阈值可配），不足就明确说"样本不足，先按常规走" ——
    这句话比一个假的"我了解我的边界"有用得多。
    去掉这条下限：系统会在看过一两条记录后就开始胡乱改行为，而且没人能发现是它自己改坏的。

【数据落盘】`logs/metacognition/boundary.jsonl`（append-only 一行一条）——
    用 `core.health` 的 append_jsonl/read_jsonl：**绝不自己写一套**读写的容错
    （半截行、坏 ts 的取舍在那边已经踩过坑），两套容错早晚对不上，
    于是会出现"账里明明有这条、统计时却看不见"。
"""
import os
import time

from . import append_jsonl, bigrams, cfg, features, meta_dir, read_jsonl
from . import selfrate

# 档案文件名（放在 logs/metacognition/ 下）。
# 为什么写成常量而不是各处写字面量：三个函数（读/写/统计）都要用它，
# 各写一遍迟早出现"写入用 boundary.jsonl、统计读 boundary_v2.jsonl"这种瞎账。
BOUNDARY_NAME = "boundary.jsonl"

# 判"以后走工具"的最少同类样本数。为什么是 3：1 条是噪声，2 条可能是同一次事故的两条记录，
# 3 条才勉强够说"这类问题反复如此"。可被 xiaojiao_control.json 的 metacognition.min_samples 覆盖。
MIN_SAMPLES = 3
# C 档"居多"的线：占比 ≥ 0.5 就算。为什么正好一半也倒向走工具：
# 走工具的代价是慢一点、多花一次调用；硬答的代价是编。两个代价不对等（见本包 __init__ 的①）。
C_RATIO = 0.5
# 判"同一个话题"的 2-gram 重合线：重合片段的个数 ÷ 较短一侧的片段数 ≥ 0.5。
# 为什么要 0.5 这么松：用户问同一个事情会有很多种说法（"小焦的记忆怎么存" / "小焦的记忆存哪了"），
# 要求字面一致就等于没归类；而松到 0.4 以下，两个无关问题也会因为共用"怎么""这个"被算成同类。
SAME_TOPIC_MIN = 0.5

# 只有 **样本 ≥ 2 条** 的话题才进 low_conf_topics：1 条不叫"一类问题"。
# 为什么这个下限（2）和决策用的下限（3）不一样：这里是**给人看的报告**（少归纳没关系），
# 那里是**真要改行为**（宁可不动）。两个口径不一样是故意的，不是笔误。
TOPIC_MIN_SAMPLES = 2
TOP_LIMIT = 5          # 报告最多列 5 个话题：再多也没人看，还会把总结那句话撑爆
QUESTION_MAX = 200     # 档案里存的问题前 200 字：账本不是原文仓库，够人认出"哪一类"就行


def _setting(key, default):
    """从配置里取一个阈值，取不到/值不合法就用默认（**绝不抛**）。"""
    try:
        v = cfg().get(key)
        return int(v) if v is not None else default
    except Exception:      # noqa: silent-ok — 用户把阈值写成了"很多条"这种文字，退回默认值
        return default


def boundary_path(path=None):
    """档案文件绝对路径（默认 `logs/metacognition/boundary.jsonl`）。

    为什么单独留一个函数而不是各处拼字符串：测试要核对"真的写进了这个文件"，
    调用方要能注入别的文件（离线推演）；各处拼一遍的话，早晚有一处拼错目录，
    记录看着存在，只是存在别的地方。去掉它：账本可能悄悄分叉成两本。
    """
    return path or os.path.join(meta_dir(), BOUNDARY_NAME)


def topic_of(question):
    """粗聚话题：取问题里**第一个有实义的中文 2-gram** 当话题键（纯规则，不调模型）。

    为什么取"第一个"而不是"出现次数最多的"：中文问题的话题词通常在句首
    （"小焦的记忆是怎么存的" → "小焦"；"明天的天气怎么样" → "明天"），
    而在一句话内部，绝大多数 2-gram 都只出现一次 —— 按次数取会退化成按字典序取，
    结果是一堆"么存"这种读都读不通的话题名（这版改掉的就是这个）。
    为什么要有个稳定的键：同一类问题必须落到同一个键上，历史才攒得起来。
    没有实义片段（英文问题、"你好"这种）→ 返回空串；空串的话题**不参与话题统计**，
    否则一群毫不相干的问题会被并成一个叫"空"的话题，得出一个假结论。
    """
    bs = bigrams(question)
    return bs[0] if bs else ""


def same_topic(a, b):
    """两个问题是不是同一类：2-gram 特征重合 ÷ 较短一侧 ≥ SAME_TOPIC_MIN。

    为什么用"较短一侧"当分母：长问题里常常包含短问题的全部内容
    （"帮我看看小焦的记忆是怎么存的" 包含 "小焦的记忆怎么存"）——
    用较长一侧当分母会把这种明显同类的判成不同类，而我们的目标是**别漏**。
    任何一侧没有特征 → False：没有可比的内容时不许说"同类"（宁可少归一类也不误伤）。
    """
    fa, fb = features(a), features(b)
    if not fa or not fb:
        return False
    return len(fa & fb) / float(min(len(fa), len(fb))) >= SAME_TOPIC_MIN


def record(question, rating, correct=None, note="", source="", path=None):
    """记一条边界样本，返回**写进档案的那一行**（dict）。

    参数：
      question  原始问题（存前 200 字）
      rating    自评档位。**走 selfrate.parse_rating 归一**，所以模型原话（"我认为是B"）
                也能直接传进来 —— 为什么必须同源：档案里的档位要和路由用的档位是同一套解析，
                两套解析早晚不一致，于是"路由按 B 走、账本按 ? 记"，后面所有统计全是歪的。
      correct   事后知道的对错：True / False / **None（还不知道）**。
                None 必须保留成 None，不许折成 False —— 把"没验证"记成"错了"，
                会让 false_confidence 和准确率一起撒谎（那正是这本账唯一的用处）。
      note      人写的一句备注（为什么对/为什么错）
      source    这条从哪来（"对话"/"自测"/"复盘"……），事后要能区分真假样本
      path      注入别的档案文件（自测/推演用）；默认就是真实档案
    """
    q = "" if question is None else str(question).strip()
    rating_norm = selfrate.parse_rating(rating)
    raw = "" if rating is None else str(rating)[:20]
    p = boundary_path(path)
    row = {
        "ts": time.time(),
        # 存一份人能读的时间：JSONL 里全是 1757xxxxxxxx 的话，人肉排查时要先算一遍才看得懂
        "iso_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "question": q[:QUESTION_MAX],
        "topic": topic_of(q),
        "rating": rating_norm,
        "rating_raw": raw,       # 模型原话：解析规则以后改了，旧记录还能重新审视
        "correct": None if correct is None else bool(correct),
        "note": ("" if note is None else str(note))[:200],
        "source": ("" if source is None else str(source))[:40],
    }
    row["written"] = bool(append_jsonl(p, row))
    row["path"] = p
    return row


def _rows(days=30, path=None):
    """读回窗口内的档案行（读不动就是空表，**绝不抛**）。

    为什么要限定窗口：能力边界会**变**（换了火种、补了记忆、工具接进来了都会变）。
    拿三年前的记录说"这类问题你不行"，等于用旧账否定现在的它。
    窗口默认 30 天，可按需拉长（days=None 表示全部）。
    """
    try:
        return read_jsonl(boundary_path(path), days=days)
    except Exception:      # noqa: silent-ok — 账本读不动等价于"没有历史"，由调用方如实说明
        return []


def _rating_of(row):
    """从一行里取出档位（认不出的归到 "?"，不许凭空多出一个键）。"""
    r = row.get("rating")
    return r if r in selfrate.ALL_RATINGS else selfrate.RATING_UNKNOWN


def stats(days=30, path=None):
    """统计窗口内的边界情况，返回
    `{"total", "by_rating", "low_conf_topics", "false_confidence"}`。

    · by_rating        固定带 A/B/C/? 四个键（没有的记 0）—— 调用方不用先判键在不在，
                       少一次"KeyError 还是 0"的分支，也就少一处写错的机会。
    · low_conf_topics  同类问题里 C 档占比最高的话题，元素形如
                       {"topic": "小焦", "samples": 5, "c": 2, "c_ratio": 0.4}；
                       只列**样本 ≥2 且至少 1 条 C** 的话题（见常量处的说明），按占比降序。
    · false_confidence **自评 A 但事后证明答错**的条数（本账最值钱的一项）。

    为什么这里全用真实数字、一个都不补：这本账的用处就是"它到底行不行"，
    补一个数就是把这个用处毁掉。没有数据就返回 0 / 空表，由 summary 去说"没有数据"。
    """
    rows = _rows(days, path)
    by_rating = {r: 0 for r in selfrate.ALL_RATINGS}
    false_conf = 0
    topics = {}
    for row in rows:
        r = _rating_of(row)
        by_rating[r] += 1
        if r == selfrate.RATING_A and row.get("correct") is False:
            false_conf += 1
        t = row.get("topic") or topic_of(row.get("question") or "")
        if not t:
            continue
        cell = topics.setdefault(t, {"samples": 0, "c": 0})
        cell["samples"] += 1
        if r == selfrate.RATING_C:
            cell["c"] += 1
    low = []
    for t, cell in topics.items():
        if cell["samples"] < TOPIC_MIN_SAMPLES or cell["c"] < 1:
            continue
        low.append({"topic": t, "samples": cell["samples"], "c": cell["c"],
                    "c_ratio": round(cell["c"] / float(cell["samples"]), 3)})
    # 排序键里的 topic 是**为了稳定**：占比和样本数都一样时，字的顺序决定先后，
    # 否则同一份数据两次跑出来的总结顺序会不一样（看起来像"结论变了"）。
    low.sort(key=lambda z: (-z["c_ratio"], -z["samples"], z["topic"]))
    return {"total": len(rows), "by_rating": by_rating,
            "low_conf_topics": low[:TOP_LIMIT], "false_confidence": false_conf}


def should_use_tool(question, days=30, path=None):
    """**关键功能**：这类问题以后该不该直接走工具，而不是让模型硬答。

    返回 `{"use_tool": bool, "why": "人话理由", "samples": n}`。
    判据（按严重程度排，先判最严重的）：
      ① 同类样本 < MIN_SAMPLES(3) → **不动**，why 说明"样本不足，先按常规走"；
      ② 同类里出现过"自评 A 却答错" → 走工具（自评在这类问题上不可信）；
      ③ 同类里 C 档占比 ≥ 0.5 → 走工具（历史上多半要靠猜）；
      ④ 其余 → 按常规走，并如实说明看过几条、C 档几条。

    为什么"归类"用重合度（same_topic）而不是话题键相等：
    决策要的是**别漏**（同一个问题的不同说法必须算同类，否则历史攒不起来就一直"样本不足"）；
    而报告里的 low_conf_topics 要的是**人能看懂的话题名**，所以用话题键分组。
    两个口径不同是故意的：报告宁可少归纳，决策宁可多归并。
    """
    q = "" if question is None else str(question).strip()
    mins = _setting("min_samples", MIN_SAMPLES)
    rows = _rows(days, path)
    if not q:
        return {"use_tool": False, "why": "问题为空，没有可比对的历史样本，先按常规走", "samples": 0}
    same = [r for r in rows if same_topic(q, r.get("question") or "")]
    n = len(same)
    if n < mins:
        return {"use_tool": False,
                "why": "同类问题的历史样本只有 %d 条（不到 %d 条），样本不足，先按常规走" % (n, mins),
                "samples": n}
    wrong = [r for r in same if _rating_of(r) == selfrate.RATING_A and r.get("correct") is False]
    if wrong:
        return {"use_tool": True,
                "why": "这类问题以前有 %d 次自评「有把握」却答错了（同类共 %d 条）——"
                       "它的自评在这类问题上不可信，直接走工具更稳" % (len(wrong), n),
                "samples": n}
    c_n = sum(1 for r in same if _rating_of(r) == selfrate.RATING_C)
    ratio = c_n / float(n)
    if ratio >= C_RATIO:
        return {"use_tool": True,
                "why": "这类问题历史 %d 条里有 %d 条自评「没把握」（占 %d%%）——"
                       "多半要靠猜，直接走工具更稳" % (n, c_n, int(round(ratio * 100))),
                "samples": n}
    return {"use_tool": False,
            "why": "这类问题历史 %d 条里自评「没把握」只有 %d 条，也没有出现过「自评有把握却答错」，"
                   "还靠得住 —— 按常规走" % (n, c_n),
            "samples": n}


def _days_cn(days):
    """把窗口天数变成一句人话（"30" / "全部"）；**传了脏值也照样显示，绝不抛**。

    为什么容错也要写在这里：这行字是要给用户看的总结，而 days 是从调用方/配置来的。
    为了一个显示用的数字把整句话炸掉（自测里就这么炸过一次：days="abc" 时 %d 报 TypeError），
    是最不划算的交换 —— 显示不出来的话，就照原样把它写出来，人看得懂就行。
    """
    if days is None:
        return "全部"
    try:
        return "%d" % int(days)
    except Exception:      # noqa: silent-ok — 脏值就原样显示，绝不因此炸掉总结
        return "%s" % (days,)


def summary(days=30, path=None):
    """一句中文概括当前的能力边界，**必须带真实数字**（没有数据就说没有，不许编）。

    为什么数字全部从 stats() 取、这里一个都不另算：
    一旦这里自己再算一遍（哪怕只是个数），迟早和 stats/界面上的数字对不上，
    而这种"两个地方说两套话"的账本，没有人会再信第二次。
    """
    st = stats(days, path)
    total = st["total"]
    by = st["by_rating"]
    fc = st["false_confidence"]
    tops = st["low_conf_topics"]
    win = _days_cn(days)
    if not total:
        return "最近 %s 天没有一条边界记录 —— 我还不知道自己哪块不行，没有数据就不编，先照常走。" % win
    parts = ["最近 %s 天记了 %d 条自评：A 档（有把握）%d 条、B 档（有点）%d 条、C 档（没把握）%d 条、"
             "解析不出档位 %d 条" % (win, total,
                                     by.get(selfrate.RATING_A, 0), by.get(selfrate.RATING_B, 0),
                                     by.get(selfrate.RATING_C, 0),
                                     by.get(selfrate.RATING_UNKNOWN, 0))]
    a_n = by.get(selfrate.RATING_A, 0)
    if fc:
        # fc > 0 必然意味着至少有一条 A 档，所以这里的除法是安全的（不用再判 a_n 为 0）
        parts.append("其中 %d 条自评「有把握」却答错了（占 A 档 %d%%）"
                     % (fc, int(round(fc / float(a_n) * 100))))
    else:
        parts.append("还没有出现过「自评有把握却答错」的记录")
    if tops:
        t0 = tops[0]
        parts.append("C 档最集中的话题是「%s」（%d 条里 %d 条没把握，占 %d%%）"
                     % (t0["topic"], t0["samples"], t0["c"], int(round(t0["c_ratio"] * 100))))
    else:
        parts.append("还没有哪个话题攒够 %d 条样本，暂不归纳话题" % TOPIC_MIN_SAMPLES)
    return "；".join(parts) + "。"
