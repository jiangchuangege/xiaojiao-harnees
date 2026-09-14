# -*- coding: utf-8 -*-
"""钉住"复读后继续写、连续才收口"这条策略（确定性，不依赖真模型）。

为什么要单独有这个测试：
    场景 8 重测 3/3 过、字数也达标，但 `logs/xiaojiao.log` 里**找不到**"继续写下一段"这行 ——
    可能是"这次模型压根没复读"（那 3/3 只证明了它没退化时的表现），
    也可能是"这条路径根本没生效"。**两种情况必须分清**，不能拿"跑绿了"当"改动生效了"。
    所以这里用**假模型精确构造复读**，直接验证策略本身：
      A. 单段复读 → 截断 + **继续写**（不收口），整篇仍能写满目标篇幅
      B. 连续 3 段复读 → 才收口（且如实说明原因）
      C. 复读不会留在成稿里（截断确实生效）

【本轮真正修掉的东西（全部由 logs/_degen_debug.log 定位，不靠猜）】
    ① 测试侧：假模型原来按"提示词前 400 字"判段号 —— 而 `build_prompt` 的前 400 字
       是「原任务 + 梗概(300 字) + 写作纪律」，**段间完全不变**。实测
       `CALL seq=37 n=13` / `FAKE seg_index=2`：13 段全被判成第 2 段 →
       "只有第 2 段该退化"变成"段段都退化" → 12 段全复读 → 撞 `_SKIP_MAX` 收口。
       **[A] 那三项红断言是测试脚本自己造的假象。** 现在按"载体给模型的原文里
       逐段递增的 第N段"（`_gen_mark`）判段，段号与载体完全对齐。
    ② 产品侧：`degen_streak` 原来只在"复用池子/自己生成一段"那条路上累加，
       而真实的复读段截断后往往**一个字都不剩**，走的是 `continue` 跳过分支 ——
       于是"连续 N 段复读"永远数不到，`_DEGEN_STREAK_MAX=3` 是死代码，
       真正兜底的是 `_SKIP_MAX=12`（实测收口原文："连续 12 段都没有可用内容"）。
       现在载体用"这一段**出现过**复读"（`degen_ever_by_n`）计数，并放在所有分支之前。
"""
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import core.continuation as C  # noqa: E402

# 【闭环定位】假模型侧的判段轨迹也落盘到**同一份**文件里。
# 为什么必须打这一侧：载体侧只打了 `degen_by_n`，看不到"假模型把这次调用归成了第几段"。
# 段号归类一旦错位，"只有第 2 段该退化"就会被判成"段段都退化"，
# 从载体日志上完全看不出来（两边的段号根本没有对齐过）。
# 这份日志只属于**测试**：产品代码里的临时落盘通道已经撤掉（改成 logger.debug）。
_FAKE_DBG = os.path.join(_ROOT, "logs", "_degen_fake.log")


def _dbg(msg, path=None):
    """测试侧的一行轨迹（失败时靠它复盘"假模型判成了第几段"）。"""
    try:
        with open(path or _FAKE_DBG, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%H:%M:%S"), msg))
    except Exception:      # noqa: silent-ok — 轨迹写不进去不能影响测试判定
        pass

PASS, FAIL = [], []
# 复读正文：**故意带任务关键词**（"产品介绍"）。
# 为什么必须带：`_generate_raw` 末尾有 `looks_offtopic`，一个与任务关键词零重合的
# 残句会被判成"跑题"，于是走的是"跳过"而不是"提交"——
# 两条路的断言完全不同，测试得能控制自己落在哪一条上。
DEGEN = "产品介绍：然后说：嗯。然后说：哦。然后说：好的。" * 30
GOOD = ("".join("第%d步：载体把上下文按需装配，模型只处理当前这一小块，单次请求永远装得下。\n" % i
                for i in range(1, 9)))


def ck(group, name, cond, info=""):
    (PASS if cond else FAIL).append("%s/%s" % (group, name))
    print("  %s [%s] %s%s" % ("✅" if cond else "❌", group, name,
                              ("  ← " + str(info)) if info else ""))


def make_llm(degen_from, degen_span, normal_len=1000):
    """假模型：从第 `degen_from` **段**开始，连续 `degen_span` **段**吐复读，其余写正常内容。

    每段非复读内容必须**各不相同**（**日志定位出来的坑**）：
      早期版本所有非复读段都返回同一段常量 GOOD，于是第 1 段与第 3 段逐句相同 →
      合并期"整段都是重复内容"把第 3 段全丢掉 → 全篇 `retry_ctr` 被吃满 →
      以"整段都是重复内容"判死整篇。那是**测试数据自己造的**，不是产品行为。
      真实模型每段都写新内容，所以这里把**段号与句序**都编进正文。

    `_gen_mark()` 是判段的唯一依据 —— 它读的是"载体交给模型的那段原文"里的
    `第N段`。踩过的两个坑都记在这个函数里，别再退回去。
    """
    st = {"n": 0}

    _BODY_MARK = "你上一次写到的最后一段原文："
    _GEN_HEAD = "【本次要写的是第"          # 由 C._GEN_MARK_TMPL 生成，逐段递增

    def _gen_mark(u):
        """判 "载体这次是在写第几段"。

        为什么不能按"提示词前 400 字"判（第一版就是这么错的）：
            `build_prompt` 的开头是「原任务 + 你已经写到（梗概）_brief(300 字) + 写作纪律」，
            **段间完全不变** —— 前 400 字里 330+ 字是固定内容，于是每段算出来都一样。
            实测：`CALL seq=37 n=13` 配 `FAKE seg_index=2`，13 段全被判成第 2 段，
            退化窗口 `degen_from=2, degen_span=1` 于是命中每一段。
        为什么不能按"重试标记（别再重复 / 还没到篇幅）"判（第二版这么错）：
            一旦某段复读过，`degen_flag` 会**一直为真**，之后每个**新段**的提示词也都带
            "别再重复" → 新段全被判成"重试" → 永远停在同一个段号
            （实测 `retry=True` 一路黏到 call=40）。
        所以直接用载体自己写进提示词的"本次要写的是第 N 段"标记 —— 零猜测、与载体同源。
        注意必须用 **rfind（最后一次出现）**：载体会把"上一段原文"整段喂回去，而上一段的
        正文里**也含**这个标记（比如第 1 段的正文里带着"【本次要写的是第 1 段】"），
        用 find 会取到那个**过期的**标记 → 每段都判成第 1 段
        （实测 `FAKE call=2 gen_mark=1` 而载体给的其实是第 2 段，于是又变成"段段都退化"）。
        """
        i = u.rfind(_GEN_HEAD)
        if i < 0:
            return 1                      # 第 1 段：提示词里只有任务本身
        j = i + len(_GEN_HEAD)
        while j < len(u) and u[j].isspace():     # 标记是"第 N 段"，中间有空格
            j += 1
        k = j
        while k < len(u) and u[k].isdigit():
            k += 1
        return int(u[j:k]) if k > j else 1

    def llm(messages, max_tokens, **kw):
        u = messages[-1]["content"]
        if "自然的结尾" in u:
            return "以上把这件事讲完了，先跑通再优化，不必一次做到完美。"
        st["n"] += 1
        i = _gen_mark(u)
        degen = degen_from <= i < degen_from + degen_span
        # ---- 闭环定位：段号（载体给的）与本次是否退化，两边都落盘 ----
        _dbg("FAKE call=%s gen_mark=%s has_mark=%s tail=%r"
             % (st["n"], i, _GEN_HEAD in u, u[-40:]), _FAKE_DBG)
        if degen:
            return DEGEN
        # 每段长度必须 > 1200 字：`_merge` 的接缝去重窗口是 `_OVERLAP_WIN=800`，
        # 段太短会让相邻段落进同一个窗口，去重把正常内容当成"接缝重复"裁掉。
        n = max(1, normal_len // 44)
        return "".join(
            "第%d段第%d句：载体把上下文按需装配，模型只处理当前这一小块，单次请求永远装得下。\n"
            % (i, k) for k in range(1, n + 1))
    return llm, st


def main():
    print("=" * 66)
    print("  复读处置策略 · 确定性验证（假模型精确构造复读）")
    print("=" * 66)

    # ---- A 只复读 1 段 → 应当截断后**继续写**，不收口 ----
    print("\n[A] 单段复读 → 截断 + 继续写（不收口）")
    llm, st = make_llm(degen_from=2, degen_span=1)
    r = C.generate_unlimited("写一篇 3000 字的产品介绍", "你是小焦。", max_per_chunk=2000,
                             llm_fn=llm, buffer_size=1)
    txt, chunks = r["text"], r["chunks"]
    ck("A", "载体确实检出了复读（结果里标了 degeneration）", r.get("degeneration") is True,
       r.get("stopped"))
    ck("A", "**没有**因为这一段复读就收口（段数 > 2，继续往下写了）", len(chunks) > 2,
       "共 %d 段" % len(chunks))
    ck("A", "停止原因不是『连续复读收口』（是正常写满）",
       "连续" not in r["stopped"], r["stopped"][:60])
    ck("A", "篇幅写到了目标附近（≥2400）", len(txt) >= 2400, "%d 字" % len(txt))
    ck("A", "复读没有留在成稿里", txt.count("然后说") <= 6, "出现 %d 次『然后说』" % txt.count("然后说"))
    ck("A", "结尾完整", txt.rstrip()[-1] in "。！？!?；;…", repr(txt[-14:]))

    # ---- B 连续 3 段复读 → 收口 ----
    print("\n[B] 连续 3 段复读 → 收口（并如实说明）")
    llm2, st2 = make_llm(degen_from=2, degen_span=5)
    r2 = C.generate_unlimited("写一篇 3000 字的产品介绍", "你是小焦。", max_per_chunk=2000,
                              llm_fn=llm2, buffer_size=1)
    ck("B", "连续复读后确实收口了", "连续" in r2["stopped"] and "收口" in r2["stopped"],
       r2["stopped"][:70])
    ck("B", "收口说明里给出了连续段数", "%d 段" % C._DEGEN_STREAK_MAX in r2["stopped"],
       r2["stopped"][:50])
    ck("B", "没有无限写下去（段数有界）", len(r2["chunks"]) < 60, "%d 段" % len(r2["chunks"]))
    ck("B", "收口后仍保证结尾完整",
       (not r2["text"].strip()) or r2["text"].rstrip()[-1] in "。！？!?；;…", repr(r2["text"][-12:]))

    # ---- C 阈值就是 3（可配置项本身也对）----
    print("\n[C] 阈值可配、且默认 3")
    ck("C", "默认阈值 = 3", C._DEGEN_STREAK_MAX == 3, C._DEGEN_STREAK_MAX)
    src = open(os.path.join(_ROOT, "core", "continuation.py"), encoding="utf-8").read()
    ck("C", "按段号记录（不用共享布尔量，预取才不会记错段）",
       "degen_by_n[n] = False" in src and "degen_by_n.get(n" in src)
    ck("C", "单段复读时不再直接 break（源码里已无旧逻辑）",
       'stop_reason[0] = "检测到复读，已截断并收口"' not in src)

    print("\n" + "=" * 66)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % ", ".join(FAIL)) if FAIL else ""))
    print("=" * 66)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
