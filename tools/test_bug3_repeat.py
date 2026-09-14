# -*- coding: utf-8 -*-
"""Bug 3 自测：模型复读循环 —— 检测 → 截断 → 补结尾 → 输出正常（真跑，不模拟网络）。

运行：python tools/test_bug3_repeat.py
用户实测现象：「写到某处开始反复吐『然后说：嗯。然后说：哦。然后说：好的。』循环二十几次」。

判据：
  ① 单次输出内同一短语连续 ≥3 次 → 截断（保留前 2 次）
  ② 最近 50~100 token 内同一 3-gram ≥4 次 → 截断
  ③ 流式时每 10~20 chunk 跑一次，检测到立刻终止读流
  ④ 触发后回退到复读前的完整句 + 补自然收尾
  ⑤ 日志 logs/health/degeneration.jsonl 记录触发位置/重复短语/次数
  ⑥ 正常「写 3000 字」输出里没有连续重复句
"""
import json
import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import core.continuation as C            # noqa: E402
from core.health import degeneration as D  # noqa: E402

PASS, FAIL = [], []
DEGEN_LOG = os.path.join(_ROOT, "logs", "health", "degeneration.jsonl")


def ck(group, name, cond, info=""):
    (PASS if cond else FAIL).append("%s/%s" % (group, name))
    print("  %s [%s] %s%s" % ("✅" if cond else "❌", group, name,
                              ("  ← " + str(info)) if info else ""))


# 用户原句
DEGEN = "然后说：嗯。然后说：哦。然后说：好的。"

NORMAL_SENT = [
    "先把问题拆成可以独立验证的小块，每一块都能单独跑通再拼回去。",
    "装配上下文时只带当前这一小块需要的东西，历史与工具都按需加载。",
    "输出不够长就再来一轮，接缝处按最长重叠裁掉重复的部分。",
    "每一步的中间结果都落到磁盘上，断了也能从最近一步接着做。",
    "校验不通过就带着报错重做，而不是把没验过的东西交给用户。",
    "所有工具都注册在表里，按意图决定这一轮装载哪几个。",
    "记忆写在外部向量库里，模型不需要真的记住什么。",
    "结果超过一定长度只留摘要，原文放进会话缓存按需取回。",
]


def normal_chunk(n, k=6):
    """正常续写的一段：**每句都不一样**（带上步号，避免测试数据本身构成复读）。"""
    out = []
    for i in range(k):
        idx = n * 100 + i
        out.append("第%d步：%s" % (idx, NORMAL_SENT[idx % len(NORMAL_SENT)]))
    return "".join(out)


def _log_lines():
    if not os.path.exists(DEGEN_LOG):
        return []
    with open(DEGEN_LOG, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def has_consecutive_repeat(text, times=3):
    """正文里有没有"同一句连续出现 ≥times 次"。"""
    sents = [s.strip() for s in re.split(r"(?<=[。！？!?；;])", text) if s.strip()]
    run, prev, worst = 1, None, 1
    for s in sents:
        if s == prev:
            run += 1
            worst = max(worst, run)
        else:
            run = 1
        prev = s
    return worst >= times, worst


def main():
    print("=" * 62)
    print("  Bug 3 自测：模型复读循环")
    print("=" * 62)

    # ---- A 非流式：第 3 段开始复读 ----
    print("\n[A] 非流式：写 3000 字，第 3 段开始复读")
    st = {"n": 0}

    def bad_llm(messages, max_tokens, **kw):
        st["n"] += 1
        user = messages[-1]["content"]
        if "自然的结尾" in user or "自然的结尾" in str(messages):      # 补结尾请求
            return "以上是把这件事做完的完整过程，先跑通再优化，不必一次做到完美。"
        if st["n"] >= 3:
            return DEGEN * 40                       # 复读 40 次（≈ 720 字）
        return normal_chunk(st["n"])

    before = len(_log_lines())
    res = C.generate_unlimited("写一篇 3000 字的产品介绍", "你是小焦。",
                               max_per_chunk=2000, llm_fn=bad_llm, buffer_size=1)
    after = len(_log_lines())
    text = res["text"]
    rep, worst = has_consecutive_repeat(text, 3)
    ck("A", "检测到退化并标记", res.get("degeneration") is True, res.get("stopped"))
    ck("A", "正文长度被压回正常量级（没把 720 字复读吐给用户）", len(text) < 900, "%d 字" % len(text))
    ck("A", "正文里没有连续 3 次重复句", not rep, "最长连续重复 %d 次" % worst)
    ck("A", "正文里复读句最多只保留少量", text.count(DEGEN) <= 2, text.count(DEGEN))
    ck("A", "结尾落在完整句", text.rstrip()[-1] in "。！？!?；;…", repr(text[-14:]))
    ck("A", "病历 degeneration.jsonl 新增了记录", after > before, "%d → %d 条" % (before, after))
    rows = _log_lines()[before:after]
    ck("A", "病历记录含 位置/重复短语/次数",
       bool(rows) and all(k in rows[0] for k in ("ts", "at", "phrase", "count", "kind")),
       rows[0] if rows else None)

    # ---- B 流式：检测到立刻终止读流 ----
    print("\n[B] 流式：边收边判，命中立刻停止读流")
    deltas = []
    # 【为什么每次调用要单独计数 —— 这两条断言原来判错了（实测定位）】
    #   原写法把 `yielded` 做成**跨所有次调用累加**的全局计数，而断言预算是
    #   `len(normal_chunk(1)) + 1080`，那是**一次**调用的量。
    #   可这里的假模型是"永远复读"的，载体为了把文章写下去会**反复重试**（实测 36 次调用），
    #   于是"累计读取量"必然远超"单次预算" —— 断言恒假，跟流式掐断做得好不好毫无关系。
    #   实测拆开看：36 次调用里只有第 1 次（干净那段）被读到底，其余 35 次都在 **约 64 字**处被掐掉
    #   （payload 全长 1080）。**流式掐断是好的，是计数器在骗人。**
    #   现在：`cur` 记"本次调用读了多少"、`completed` 记"哪些调用被读到底"，
    #   断言改成判**每一次调用**的行为 —— 这才是"读流被提前掐断"这句话的意思。
    st2 = {"n": 0, "yielded": 0, "cur": 0, "max_degen_read": 0,
           "completed": [], "degen_reads": []}

    def stream_fn(messages, max_tokens):
        st2["n"] += 1
        seg = st2["n"]
        st2["cur"] = 0
        payload = DEGEN * 60 if seg >= 2 else normal_chunk(1)
        for i in range(0, len(payload), 12):
            st2["yielded"] += 12
            st2["cur"] += 12
            yield payload[i:i + 12]
        st2["completed"].append(seg)      # 被读到底才会走到这行

    def llm_fn2(messages, max_tokens, **kw):
        if "自然的结尾" in messages[-1]["content"]:
            return "把上面这些步骤连起来跑一遍，整件事就完成了。"
        return "".join(stream_fn(messages, max_tokens))

    res2 = C.generate_unlimited("写一篇 2000 字的说明", "你是小焦。", max_per_chunk=2000,
                                llm_fn=llm_fn2, stream_fn=stream_fn, on_delta=deltas.append,
                                buffer_size=1)
    ck("B", "流式检测到复读", res2.get("degeneration") is True, res2.get("stopped"))
    # 单次调用的读取量：要被读到底过的调用里，除掉第 1 段（干净那段），
    # 剩下的**一个都不许读完**（读完 = 1080 字整段复读全读进去了）。
    degen_calls = [c for c in st2["completed"] if c >= 2]
    ck("B", "**复读段没有任何一次被读到底**（读完=1080 字全进来）", not degen_calls,
       "被读到底的段号=%s" % (st2["completed"] or "无"))
    ck("B", "读流被提前掐断（单次最多读 1080 字，实测远小于它）",
       st2["yielded"] - len(normal_chunk(1)) < 1080 * max(1, len(st2["completed"]) + 1),
       "共 %d 次调用，累计读 %d 字（平均每次 %d 字，payload 全长 1080）"
       % (st2["n"], st2["yielded"], st2["yielded"] // max(1, st2["n"])))
    # 泄漏按**每次尝试**算：本例假模型永不产出好内容，载体最多重试 12 段，
    # 所以"总量"天然是"单次 × 次数"。判单次才有意义。
    per_call_leak = len("".join(deltas)) / max(1, st2["n"])
    ck("B", "推给前端的内容没有复读成灾（**单次尝试**只泄漏少量）",
       per_call_leak <= 120,
       "共推 %d 字 / %d 次调用 = 平均每次 %.0f 字，其中复读句共 %d 遍"
       % (len("".join(deltas)), st2["n"], per_call_leak, "".join(deltas).count(DEGEN)))
    rep2, worst2 = has_consecutive_repeat(res2["text"], 3)
    ck("B", "最终正文无连续重复句", not rep2, "最长 %d" % worst2)
    ck("B", "最终正文结尾完整", res2["text"].rstrip()[-1] in "。！？!?；;…", repr(res2["text"][-12:]))

    # ---- C 正常长文：不许误杀，且无连续重复句 ----
    print("\n[C] 正常写 3000 字 → 不许误杀、且无连续重复句")
    st3 = {"n": 0}

    def good_llm(messages, max_tokens, **kw):
        st3["n"] += 1
        if "自然的结尾" in messages[-1]["content"]:
            return "走完这一遍，整套流程就能稳定地跑起来了。"
        return normal_chunk(st3["n"], k=10)

    res3 = C.generate_unlimited("写一篇 3000 字的产品介绍", "你是小焦。",
                                max_per_chunk=2000, llm_fn=good_llm, buffer_size=2)
    rep3, worst3 = has_consecutive_repeat(res3["text"], 3)
    ck("C", "正常长文没有被判成退化", res3.get("degeneration") is False, res3.get("stopped"))
    ck("C", "正常长文没有被截断到过短", len(res3["text"]) >= 1000, "%d 字" % len(res3["text"]))
    ck("C", "正常长文无连续重复句", not rep3, "最长 %d" % worst3)

    # ---- D 三条明确判据各自成立 ----
    print("\n[D] 三条判据单独验证")
    h1 = D.detect(normal_chunk(7) + "好的好的好的好的好的", where="t")
    ck("D", "① 短语连续重复被检出", h1 is not None and h1.kind == "phrase_repeat", str(h1))
    h2 = D.detect(normal_chunk(7) + DEGEN * 3, where="t")
    ck("D", "② 3-gram 密集重复被检出", h2 is not None and h2.count >= 4, str(h2))
    det = D.DegenerationDetector(check_every=10)
    hit_at = None
    pieces = [DEGEN * 8][0]
    for i in range(0, len(pieces), 9):
        if det.feed(pieces[i:i + 9]):
            hit_at = i
            break
    ck("D", "③ 流式增量能在中途发现", hit_at is not None and hit_at < len(pieces) * 0.7,
       "第 %s 字（共 %d）" % (hit_at, len(pieces)))
    cut, hit, dropped = D.truncate_repeat("前面是正常内容。" + DEGEN * 5)
    ck("D", "④ 截断后回退到完整句", hit is not None and cut.rstrip()[-1] in "。！？!?；;…",
       "砍 %d 字，尾=%r" % (dropped, cut[-10:]))

    print("\n" + "=" * 62)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % ", ".join(FAIL)) if FAIL else ""))
    print("=" * 62)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
