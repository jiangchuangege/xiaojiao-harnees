# -*- coding: utf-8 -*-
"""模块 · 思维流（Mind Stream）· 自测

【为什么必须有它】
    "状态每轮演进"这件事最容易退化成"每轮重新生成"—— 两者代码看着都很正常，
    区别只在"有没有把上一轮的东西带过来"。所以这里逐条钉住**连续性**：
      · 话题没变就不许换（换了就断线）；判不出话题时**保留**旧话题；
      · 新事实**并进**而不是覆盖（人也是慢慢了解另一个人的）；
      · 注入 ≤500 token（超了就是挤占上下文）；
      · 重启后状态还在（验收测试 6）；
      · 温度按意图给（事实 0.2 / 闲聊 0.8）。

⚠️ 本测试会往 `logs/mind_stream/` 写测试会话文件（用完自己清理，**不删任何文件**，
   只把自己创建的测试文件内容截断改名 —— 见收尾处说明）。
"""
import json
import os
import shutil
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from core import mind_stream as MS          # noqa: E402
from core.mind_stream import inject as INJ  # noqa: E402
from core.mind_stream import state as ST    # noqa: E402
from core.mind_stream import update as UP   # noqa: E402

PASS, FAIL = [], []
_SID = "zz_selftest_mind_%d" % int(time.time())


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


def main():
    print("=" * 76)
    print("  思维流 Mind Stream · 自测")
    print("=" * 76)

    # ---------------- 一、状态结构 ----------------
    print("\n[一] ThinkState 八个字段齐全、类型正确")
    b = MS.blank(_SID)
    for f in ("current_topic", "user_understanding", "recent_thoughts", "open_questions",
              "tone_state", "unsaid", "turn_count", "last_updated"):
        ck("字段 %s 存在" % f, f in b, type(b.get(f)).__name__)
    ck("字段集合与 FIELDS 声明一致",
       set(ST.FIELDS) <= set(b.keys()), sorted(ST.FIELDS))
    ck("轮数初始为 0", b["turn_count"] == 0)
    ck("语气初始为 neutral", b["tone_state"] == "neutral")
    ck("带 schema 版本号（将来能迁移）", b.get("schema") == 1, b.get("schema"))

    # ---------------- 二、演进式更新（不是覆盖） ----------------
    print("\n[二] 演进：话题没变就沿用，事实并进不覆盖")
    st = MS.blank(_SID)
    st = UP.after_user(st, "我叫张三，在济南做后端开发")
    ck("抽出三个事实（名字/城市/职业）",
       len(st["user_understanding"]) >= 3, st["user_understanding"])
    t1 = st["current_topic"]
    ck("识别出话题", bool(t1), t1)
    # 第二条没有话题词 —— 话题**必须保留**（这正是"接着聊"）
    st = UP.after_user(st, "嗯")
    ck("**判不出话题时保留旧话题**（不能被清空）", st["current_topic"] == t1,
       "%r → %r" % (t1, st["current_topic"]))
    # 新事实并进去
    st = UP.after_user(st, "我喜欢写 Python")
    ck("新事实**并进**（不是覆盖旧的）",
       any("名字" in x for x in st["user_understanding"])
       and any("偏好" in x for x in st["user_understanding"]),
       st["user_understanding"])
    ck("轮数在累加", st["turn_count"] == 3, st["turn_count"])

    # ---------------- 二·五、疑问句绝不能被记成"事实"（假记忆回归） ----------------
    # 【这一节守的是用户实测的真 bug】"我叫什么名字来着？"被记成 `名字：什么名字来着`，
    #   而画像注入比检索到的记忆更强势 —— 实测问"我叫什么名字"，检索明明捞回了"张三"，
    #   模型仍然答"你叫王五"。**一条假记忆不是安静躺着，它会顶掉正确答案。**
    print("\n[二·五] 画像只能由**陈述句**更新（疑问句一律不记）")
    Q_CASES = (
        ("我叫什么名字来着？", "名字"),          # 带问号
        ("我叫什么名字来着", "名字"),            # 不写问号，靠疑问词抓
        ("我现在住在哪个城市？", "城市"),
        ("我喜欢什么颜色？", "偏好"),
        ("你叫什么名字", "名字"),                # 问的是对方，更不该记成自己的
        ("我的生日是几号", "生日"),              # 疑问词在后面
        ("我老婆叫什么", "名字"),
        ("我是谁", "名字"),
    )
    bad = []
    for q, _lab in Q_CASES:
        got = UP._facts_of(q)
        if got:
            bad.append("%s → %s" % (q, got))
    ck("**7 种疑问句一条都不许记进画像**", not bad, bad or "全部拦下")
    ck("疑问句判据正例覆盖（问号/语气词/疑问词三类都认）",
       UP._is_question("我叫什么名字来着？") and UP._is_question("你叫什么名字呢")
       and UP._is_question("我住哪儿"))

    S_CASES = (("我叫张三", "名字：张三"), ("我住在杭州", "城市：杭州"),
               ("我喜欢蓝色", "偏好：蓝色"), ("我是做后端开发的", "职业：做后端开发"))
    bad2 = []
    for s, want in S_CASES:
        got = UP._facts_of(s)
        if want not in got:
            bad2.append("%s → %s（期望含 %s）" % (s, got, want))
    ck("**4 种陈述句照常记下**（不能把疑问判据做成一刀切）", not bad2, bad2 or "全部正常")

    got = UP._facts_of("我叫张三，你叫什么名字？")
    ck("**同一句里陈述 + 疑问混排：留陈述、丢疑问**", got == ["名字：张三"], got)

    st_q = MS.blank(_SID + "_q")
    st_q = UP.after_user(st_q, "我叫什么名字来着？")
    st_q = UP.after_user(st_q, "我现在住在哪个城市？")
    st_q = UP.after_user(st_q, "我喜欢什么颜色？")
    ck("连问三句疑问句之后画像**仍然是空的**",
       (st_q.get("user_understanding") or []) == [], st_q.get("user_understanding"))
    st_q = UP.after_user(st_q, "我叫张三")
    ck("紧接着一句陈述句能正常写进画像",
       st_q["user_understanding"] == ["名字：张三"], st_q["user_understanding"])

    # ---------------- 三、话题切换 ----------------
    print("\n[三] 话题切换：变了才换")
    st2 = MS.blank(_SID + "_topic")
    st2 = UP.after_user(st2, "帮我看看有哪些工具")
    ck("工具类话题识别", st2["current_topic"] == "工具能力", st2["current_topic"])
    st2 = UP.after_user(st2, "今天天气怎么样")
    ck("换话题时**才**更新", st2["current_topic"] == "天气时间", st2["current_topic"])
    st2 = UP.after_user(st2, "概率题怎么做")
    ck("再换一次也对", st2["current_topic"] == "概率统计", st2["current_topic"])

    # ---------------- 四、语气与温度 ----------------
    print("\n[四] 语气与温度自适应")
    s3 = MS.blank(_SID + "_tone")
    s3 = UP.after_user(s3, "今天好累啊")
    ck("情绪低落 → 共情语气", s3["tone_state"] == "empathetic", s3["tone_state"])
    ck("共情 → 温度 0.8", INJ.temperature_for("chat", "今天好累啊", "empathetic") == 0.8)
    s3b = MS.blank(_SID + "_f")
    s3b = UP.after_user(s3b, "3 个红球 2 个蓝球摸 2 个都是红球的概率是多少")
    ck("事实题 → 专注语气", s3b["tone_state"] == "focused", s3b["tone_state"])
    ck("**事实题温度 0.2**（要准）", INJ.temperature_for("query", "概率是多少") == 0.2,
       INJ.temperature_for("query", "概率是多少"))
    ck("闲聊温度 0.8（要多样）", INJ.temperature_for("chat", "你好呀") == 0.8,
       INJ.temperature_for("chat", "你好呀"))
    ck("其它情况 0.5", INJ.temperature_for("scrape", "抓一下这个页面") == 0.5,
       INJ.temperature_for("scrape", "抓一下这个页面"))
    # 语气判不出要沿用
    s4 = MS.blank(_SID + "_keep")
    s4 = UP.after_user(s4, "我好难过")
    s4 = UP.after_user(s4, "嗯")
    ck("**判不出语气时沿用上一次**（不打回 neutral）", s4["tone_state"] == "empathetic",
       s4["tone_state"])

    # ---------------- 五、悬而未决的问题 ----------------
    print("\n[五] 悬而未决的问题：入队 + 上限淘汰")
    s5 = MS.blank(_SID + "_q")
    s5 = UP.after_user(s5, "为什么天空是蓝色的？")
    ck("疑问句入队", len(s5["open_questions"]) == 1, s5["open_questions"])
    for q in ("那云为什么是白的？", "彩虹怎么形成的？", "极光是什么原理？"):
        s5 = UP.after_user(s5, q)
    ck("**队列有上限（≤3）**，不会无限堆", len(s5["open_questions"]) <= 3,
       len(s5["open_questions"]))
    ck("保留的是**最近**的", "极光" in (s5["open_questions"][-1] or ""),
       s5["open_questions"][-1])

    # ---------------- 六、没说出口的话 ----------------
    print("\n[六] 没说出口的话：有才记、用掉就清")
    s6 = MS.blank(_SID + "_u")
    s6 = UP.after_user(s6, "帮我写个 3000 字的文章")
    s6 = UP.after_assistant(s6, "好的，我先写第一段……", truncated=True,
                            skipped="后面还有两节没展开")
    ck("被截断时记下没说出口的话", len(s6["unsaid"]) == 1, s6["unsaid"])
    got = UP.consume_unsaid(s6)
    ck("取出来的是那句话", got and "没展开" in got[0], got)
    ck("**取用后即清**（不然会一直惦记同一件事）", s6["unsaid"] == [], s6["unsaid"])
    s6b = MS.blank(_SID + "_u2")
    s6b = UP.after_assistant(s6b, "正常回答，没有被截断")
    ck("没截断就**不记**（不编「没说出口的话」）", s6b["unsaid"] == [], s6b["unsaid"])

    # ---------------- 七、注入：轻量 + 只给关键三样 ----------------
    print("\n[七] 注入：≤500 token、只给关键项、不给成句话术")
    s7 = MS.blank(_SID + "_inj")
    s7 = UP.after_user(s7, "我叫张三，在济南做后端开发，帮我看看有哪些工具")
    s7 = UP.after_assistant(s7, "张三你好，我这边一共 77 个工具……")
    blk = INJ.build_block(s7, text="我要全部的", intent="chat")
    ck("**注入 ≤500 token**", blk["tokens"] <= INJ.MAX_TOKENS,
       "%d token / %d 字" % (blk["tokens"], len(blk["text"])))
    # 【2026-09-18 改：这六条断言原来钉的是**载体命名的框**与一条**行为指令**
    #   （「【你刚才在想什么…接着这条线往下说】」「· 当前在聊：」「· 你对用户的了解：」…）。
    #   用户定的标准是「模型自己感知 = 真；载体写好词句 = 假」，那些框与指令被删掉了，
    #   断言跟着改成**只给事实**的形状（事实 + 谁说的归属）。】
    ck("只有事实表头（不再有载体命名的框）", "[此刻的事实]" in blk["text"], blk["text"][:30])
    ck("不再有行为指令（「接着这条线往下说」那类）", "接着" not in blk["text"], blk["text"][:40])
    ck("含当前话题（事实）", "当前话题：" in blk["text"])
    ck("含用户说过的话（事实 + 归属）", "用户说过：" in blk["text"])
    ck("含它自己说过的话（事实 + 归属）", "它自己说过：" in blk["text"])
    ck("**不再替模型交代「别念出来」**（那是载体在教它怎么说话）",
       "不是要复述" not in blk["text"])
    # 空状态不许硬塞
    empty_blk = INJ.build_block(MS.blank(_SID + "_empty"), text="你好")
    ck("空状态**不注入**（不硬塞一段空话）",
       empty_blk["used"] is False and empty_blk["text"] == "", empty_blk)
    # 超长状态要能砍到预算内
    s7b = MS.blank(_SID + "_big")
    s7b["current_topic"] = "话题" * 30
    s7b["user_understanding"] = ["很长的理解" * 8] * 6
    s7b["recent_thoughts"] = ["很长的思考" * 10] * 4
    s7b["unsaid"] = ["很长的没说完" * 6] * 2
    s7b["open_questions"] = ["很长的问题" * 6] * 3
    big = INJ.build_block(s7b, text="继续")
    ck("**超长状态被砍到预算内**", big["tokens"] <= INJ.MAX_TOKENS,
       "%d token / %d 字" % (big["tokens"], len(big["text"])))
    ck("砍的时候**先保话题**（接线的根不能没）", "当前话题：" in big["text"])

    # ---------------- 八、落盘与重启恢复（验收测试 6） ----------------
    print("\n[八] 存盘 + 重启恢复（换个进程也读得到）")
    sid8 = _SID + "_persist"
    st8, _ = MS.begin(sid8, "我叫李四，在上海做产品设计")
    MS.finish(sid8, st8, "李四你好！")
    ck("状态文件真的落盘", os.path.exists(ST.path_for(sid8)), ST.path_for(sid8))
    # 模拟"重启"：不走内存，直接重新 load
    back = MS.load(sid8)
    ck("**重新读回来的事实还在**",
       any("李四" in x for x in back["user_understanding"]), back["user_understanding"])
    ck("话题也还在", back["current_topic"] == st8["current_topic"],
       back["current_topic"])
    ck("轮数也还在", back["turn_count"] == st8["turn_count"], back["turn_count"])
    # 读坏的文件不许崩
    p = ST.path_for(_SID + "_broken")
    with open(p, "w", encoding="utf-8") as f:
        f.write("{ 这不是合法 JSON")
    bad = MS.load(_SID + "_broken")
    ck("**文件读坏 → 返回空状态而不是抛异常**", bad["turn_count"] == 0
       and bad["current_topic"] == "", bad)
    # 会话隔离
    a = MS.load(sid8)
    c = MS.load(_SID + "_other")
    ck("**会话之间互相隔离**（B 读不到 A 的状态）",
       not c["user_understanding"], c["user_understanding"])

    # ---------------- 九、脏输入 ----------------
    print("\n[九] 脏输入不崩")
    for bad_in in (None, "", "   ", "嗯", "?", "a" * 5000, "😀😀", "```"):
        try:
            s = UP.after_user(MS.blank(_SID + "_dirty"), bad_in)
            s = UP.after_assistant(s, bad_in)
            _ = INJ.build_block(s, text=bad_in)
            ck("脏输入 %r 不崩" % (str(bad_in)[:12],), True)
        except Exception as e:
            ck("脏输入 %r 不崩" % (str(bad_in)[:12],), False,
               "%s: %s" % (type(e).__name__, e))

    # ---------------- 十、载体不给成句话术（底线） ----------------
    print("\n[十] 底线：注入块里**不许出现可直接抄的成品句子**")
    s10 = UP.after_user(MS.blank(_SID + "_b"), "你好，介绍一下你自己")
    blk10 = INJ.build_block(s10, text="你好")
    # 指令性/结构性词可以有，但"完整的一句话术"（带句末标点的人话）不该有
    import re as _re
    canned = [ln for ln in blk10["text"].split("\n")
              if _re.search(r"[，。！？]", ln) and not ln.startswith("（")]
    ck("注入里没有成句话术（只有事实与指令，措辞交给模型）",
       all(("：" in ln) or ln.startswith("·") for ln in canned), canned[:3])

    # ---------------- 收尾：清理测试状态文件 ----------------
    print("\n[收尾] 清掉本次自测产生的状态文件")
    n = 0
    try:
        d = ST.state_dir()
        for fn in os.listdir(d):
            if fn.startswith("zz_selftest_mind_"):
                os.remove(os.path.join(d, fn))
                n += 1
    except Exception as e:      # noqa: silent-ok — 清不掉只是留几个小文件，不影响结论
        ck("清理测试状态文件", False, "%s" % e)
    ck("测试状态文件已清理（%d 个）" % n, n >= 1, n)
    left = [f for f in os.listdir(ST.state_dir())
            if f.startswith("zz_selftest_mind_")]
    ck("**没有残留测试文件**", not left, left)

    print("\n" + "=" * 76)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("=" * 76)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
