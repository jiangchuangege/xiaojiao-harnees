# -*- coding: utf-8 -*-
"""第三处自测：`core/mind_stream/inject.py` build_block() 只给事实。

钉六条：
  ① 输出里**没有载体标题框**（【你刚才在想什么】/当前在聊/你对用户的了解/当前语气…）
  ② 输出里**没有载体行为指令**（接着这条线往下说 / 别把这些当答案念出来）
  ③ 值里的**载体句式被剥掉**：`聊到「X」时我回应了：Y` → 只留 Y（它自己的话，原样）
  ④ 事实的**归属写清**（谁说的）：用户说过 / 它自己说过
  ⑤ `temp` 照旧算（机制没动）；预算裁剪还在
  ⑥ 状态空 → 空串

运行：python tools/test_mind_facts.py
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from core.mind_stream import inject as IJ     # noqa: E402

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)[:170]) if info else ""))


BANNED = ("【你刚才在想什么", "当前在聊", "你对用户的了解", "你刚才在想", "你上次有没说完",
          "用户还悬着的问题", "当前语气", "接着这条线", "不要重新开始", "别把这些当答案念出来",
          "载体", "你该")


def main():
    print("①-④ 真实状态的形状（值里带载体句式，看它剥不剥得掉）")
    st = {"current_topic": "工具能力",
          "user_understanding": ["名字：张三", "城市：济南"],
          "recent_thoughts": ["聊到「工具能力」时我回应了：你好呀，我是小焦，有什么可以帮你的？",
                              "聊到「工具能力」时我回应了：我一共 77 个工具，一个都没砍。"],
          "unsaid": ["没说完：还有一段没展开"],
          "open_questions": ["工具怎么加"],
          "tone_state": "casual"}
    blk = IJ.build_block(st, "帮我看看有哪些工具", intent="chat")
    print("---- 原样输出 ----")
    print(blk["text"])
    print("------------------")
    t = blk["text"]
    ck("带 [此刻的事实] 表头", "[此刻的事实]" in t, t[:24])
    ck("没有载体标题框/语气命名", not any(b in t for b in BANNED), [b for b in BANNED if b in t])
    ck("**载体句式被剥掉**（不再出现「聊到…时我回应了：」）",
       "聊到「" not in t and "时我回应了" not in t, t)
    ck("它自己的原话留下了（一字不改）",
       "我一共 77 个工具，一个都没砍。" in t, t)
    ck("「没说完：」这个载体框也剥掉了", "没说完：" not in t, t)
    ck("归属写清（用户说过 / 它自己说过）",
       ("用户说过：" in t) and ("它自己说过：" in t), t)
    ck("话题是事实不是命名框", "当前话题：工具能力" in t, t)

    print("\n⑤ temp 照旧算 + 预算裁剪还在")
    ck("闲聊 → 0.8（机制没动）", abs(float(blk["temp"]) - 0.8) < 1e-6, blk["temp"])
    ck("事实类问题 → 0.2", abs(float(IJ.build_block(st, "这个是多少", intent="query")["temp"]) - 0.2) < 1e-6)
    long_st = dict(st)
    long_st["recent_thoughts"] = ["很长很长的一句话" * 12] * 3
    long_st["unsaid"] = ["很长很长" * 12] * 2
    lb = IJ.build_block(long_st, "聊两句", intent="chat")
    ck("超预算被裁到 MAX_CHARS 以内", len(lb["text"]) <= IJ.MAX_CHARS, len(lb["text"]))
    ck("裁完仍然只给事实（没把砍掉的东西变成别的话）",
       not any(b in lb["text"] for b in BANNED), lb["text"][:80])

    print("\n⑥ 状态空 → 空串")
    empty = IJ.build_block({}, "你好", intent="chat")
    ck("空状态 → text 为空、used=False", empty["text"] == "" and empty["used"] is False, empty)

    print("\n" + "=" * 66)
    print("第三处（build_block 只给事实）自测：通过 %d / 共 %d" % (len(PASS), len(PASS) + len(FAIL)))
    if FAIL:
        print("❌ 失败：%s" % FAIL)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
