# -*- coding: utf-8 -*-
"""最后一跳的判据实验：**把印象从上下文里撤掉，它还记得吗？**

【为什么这个实验能回答"跳没跳过去"】
  · 它**撤掉也记得** → 那条事实已经成了**它的**，这叫跨过去了
  · 它**一撤就不知道** → 那条事实只是**摆在眼前的纸条**：读到了、用上了，
    但纸条不在就什么都没有 —— **那就还没跳**

同一句话、同一个模型、同一个温度，**只改 system 里有没有那段印象**。
（模型是无状态的，"撤掉"这一组它不可能从别处知道答案。）

运行：python tools/test_last_jump.py      （要本地大脑在跑）
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import xiaojiao_recall as R  # noqa: E402 — 直连 9292 的 local_chat 与 build_system

NOTES = [
    {"text": "用户对海鲜过敏，吃了会起疹子"},
    {"text": "用户养了一只柯基，名字叫旺财"},
    {"text": "用户喜欢的作家是村上春树"},
]

# (问题, 撤掉印象时**只有记得才可能说得出**的话, 给印象时**该**说出来的话)
# ⚠️ 第一版判据写成"出现『过敏』就算记得" —— **当场误报**：它撤掉印象后答的是
#    「痛风、过敏、孕期……这些关键词一出来，建议先问医生」，那是一串**通用条件**，
#    不是在说"你对海鲜过敏"（它甚至先说"当然可以"）。
#    所以判据必须是**只有那张纸条才给得出的措辞**，通用的词不算。
CASES = (
    ("海鲜我能吃吗", ("海鲜过敏", "你对海鲜过敏", "吃海鲜会起疹"),
     ("海鲜过敏", "疹")),
    ("我家狗叫什么名字", ("旺财", "柯基"), ("旺财",)),
    ("我喜欢哪个作家，给我推荐一本他的书",
     ("你喜欢的作家是村上", "你喜欢村上", "你偏爱村上"), ("村上",)),
)

BARE = "你是小焦，用户的本地 AI 伙伴。自然地聊。"


def main():
    print("=" * 78)
    print("最后一跳：纸条在 / 纸条不在")
    print("=" * 78)
    jumped = 0
    for q, forbid_bare, want_note in CASES:
        print("\n【问】%s" % q)
        bare = R.local_chat([{"role": "system", "content": BARE},
                             {"role": "user", "content": q}],
                            temperature=0.7, max_tokens=200)
        noted = R.local_chat([{"role": "system", "content": R.build_system(NOTES)},
                              {"role": "user", "content": q}],
                             temperature=0.7, max_tokens=200)
        print("  撤掉印象：%s" % bare.replace("\n", " ")[:170])
        print("  给印象　：%s" % noted.replace("\n", " ")[:170])
        # "撤掉也知道"= 它答出了只有那张纸条才有的内容 → 那才叫记得
        knows_without = any(k in bare for k in forbid_bare)
        uses_note = any(k in noted for k in want_note)
        print("  给印象时用上了：%s ｜ 撤掉印象也知道：%s"
              % ("是" if uses_note else "否", "**是 ← 这条算记得**" if knows_without else "否"))
        if knows_without:
            jumped += 1

    print("\n" + "=" * 78)
    print("结论：撤掉印象仍然答对的 = **%d/%d**" % (jumped, len(CASES)))
    print("  · 0/N 的意思很明确：东西**全在纸条上**，不在它身上 —— 最后一跳没跨过去。")
    print("  · 要出现非 0，才是「它自己的了」。")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
