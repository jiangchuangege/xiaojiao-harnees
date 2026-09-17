# -*- coding: utf-8 -*-
"""自我回灌：它自己说过的话，不许当成"用户说过的事实"（离线、不调模型）

【实测症状（2026-09-17）】问「2026年世界杯谁是冠军」，优率最高的那条**就是它自己上一轮**的
错答（「还没开赛」），优率 **0.94 → 直接使用**。它能那么高的原因有两条叠在一起：
  ① 向量库按**用户那句话**做索引键（那是"按用户问过的去找"的正确做法）——
     所以同一句问题再问一次，相似度天然就是 1.00；
  ② 「记忆库」这一源的信任度写死 **1.00**（它代表"用户亲口说的话"）。
→ 合起来 = **它自己的回答被当成了用户说过的事实**，越答越像真的（闭环自噬）。

【这一轮改的判据】记忆库不再无条件 1.00，改看「你说过的」那几段：
  · 只要**有一句是用户在陈述事实** → 仍按 1.00（用户说过的话照旧最可信）；
  · **全是提问** → 这条记忆的价值只剩"它上次怎么答的" → 按 **0.60**（与联网同级）。
这两头都必须钉住：只堵自我回灌、不能把"用户亲口说的"一起降档。

运行：python tools/test_self_echo.py
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import xiaojiao_app as app  # noqa: E402

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)[:170]) if info else ""))


SELF_ECHO = "- 【你说过的】2026年世界杯谁是冠军 ｜ 【小焦说过的】还没开赛呢，冠军还不清楚"
USER_FACT = "- 【你说过的】我叫张三 ｜ 【小焦说过的】好的，张三"
MIXED = ("- 【你说过的】我住在杭州 ｜ 【小焦说过的】知道了\n"
         "- 【你说过的】今天冷吗 ｜ 【小焦说过的】有点冷")
NO_MARK = "- 【它自己记下的一条】HTTP 是一个协议"
SELF_ONLY = "- 【小焦说过的】我觉得是这样"


def main():
    print("一、它自己说过的话 → 不按事实来源计（0.60，与联网同级）")
    trust, why = app._rag_mem_trust(SELF_ECHO)
    ck("全是提问的记忆 → 信任度 0.60", trust == 0.60, "%.2f ｜ %s" % (trust, why))
    ck("判据说明里写明了为什么", "提问" in why, why)
    trust2, _ = app._rag_mem_trust(SELF_ONLY)
    ck("只有它自己说过、没有用户那句 → 也是 0.60", trust2 == 0.60, trust2)

    print("\n二、用户亲口说的照旧最可信（1.00，一个字不许降）")
    trust3, why3 = app._rag_mem_trust(USER_FACT)
    ck("用户陈述事实 → 1.00", trust3 == 1.00, "%.2f ｜ %s" % (trust3, why3))
    trust4, _ = app._rag_mem_trust(MIXED)
    ck("一段里既有陈述又有提问 → 仍 1.00（不能误伤）", trust4 == 1.00, trust4)
    trust5, _ = app._rag_mem_trust(NO_MARK)
    ck("没有来源标记的老文本 → 仍 1.00（行为不变）", trust5 == 1.00, trust5)

    print("\n三、优率与档位：**这条改动真正要挡住的东西**")
    # 复现实测那一条：同一句问题、相似度 1.00（索引键就是用户那句话）
    q_self, why_self = app._rag_quality(SELF_ECHO, "2026年世界杯谁是冠军", "记忆库", sim=1.0)
    ck("自我回灌那条的优率**掉出「直接使用」档**（< 0.90）", q_self < app.RAG_USE_DIRECTLY,
       "优率=%.4f ｜ %s" % (q_self, why_self))
    ck("但**没被一棒子打死**：仍在「交元认知/健康医生」档内（≥ 0.60）",
       q_self >= app.RAG_REVIEW_FLOOR, "优率=%.4f" % q_self)
    g = app._rag_grade([{"text": SELF_ECHO, "source": "记忆库", "sim": 1.0}],
                       "2026年世界杯谁是冠军")
    ck("档位从「直接使用」变成「交元认知与健康医生」", g["grade"] == "交元认知与健康医生", g["grade"])

    q_user, why_user = app._rag_quality(USER_FACT, "我叫什么名字来着", "记忆库", sim=1.0)
    ck("用户亲口说的那条**仍然是「直接使用」档**（没被误伤）",
       q_user >= app.RAG_USE_DIRECTLY, "优率=%.4f ｜ %s" % (q_user, why_user))
    g2 = app._rag_grade([{"text": USER_FACT, "source": "记忆库", "sim": 1.0}], "我叫什么名字来着")
    ck("它的档位仍是「直接使用」", g2["grade"] == "直接使用", g2["grade"])

    print("\n四、别的源一个都不许受影响")
    q_web, _ = app._rag_quality("世界杯冠军是西班牙", "2026年世界杯谁是冠军", "联网")
    ck("联网仍按 0.60 权重（不进直接使用）", q_web < app.RAG_USE_DIRECTLY, "%.4f" % q_web)
    q_vec, _ = app._rag_quality("- 用户喜欢猫", "我喜欢什么", "向量库", sim=1.0)
    ck("向量库那一源不受影响（仍是 0.90 权重）", q_vec > 0.60, "%.4f" % q_vec)

    print("\n五、判据本身：只认明确问句，不误伤陈述")
    for s, want in [("2026年世界杯谁是冠军", True), ("今天冷吗", True), ("这是怎么回事", True),
                    ("几点", True), ("我住在杭州", False), ("我喜欢猫", False)]:
        ck("「%s」判成问句=%s" % (s, want), app._looks_like_question(s) is want,
           app._looks_like_question(s))

    print("\n" + "=" * 70)
    print("自我回灌判据自测：通过 %d / 共 %d" % (len(PASS), len(PASS) + len(FAIL)))
    if FAIL:
        print("❌ 失败：%s" % FAIL)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
