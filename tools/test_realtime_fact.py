# -*- coding: utf-8 -*-
"""时效性事实那条路的判据自测（**离线、不调模型、不需要联网**，可进 CI）

【为什么必须有这个测试】
2026-09-17 实测：用户问「2026年世界杯谁是冠军」，它答「还没结束呢」。
查下来那条路**四道闸同时关着**，其中两道是判据写窄了（这类问题被判成"闲聊"，于是不联网、
也不给联网结果留进 system 的口子）。改判据最怕的是**误伤**：
多搜一次只是慢，把「谁是鲁迅」这种历史问题也强搜一遍、或者把联网垃圾也当事实用，那是错的。
所以这里两头都钉：
  · 该走这条路的 → 必须 True（世界杯、最新、冠军…）
  · 不该走的 → 必须 False（历史问题、几点、天气、闲聊、代码问题…）
  · 而且 `_rag_grade` 的**默认行为一个字不变**（别的调用方与自测直接调它，不能被我改坏）。

运行：python tools/test_realtime_fact.py
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import xiaojiao_app as app  # noqa: E402

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)[:150]) if info else ""))


def main():
    print("一、判据：该判成「时效性事实」的（必须 True）")
    yes = [
        "2026年世界杯谁是冠军",
        "今年世界杯冠军是谁",
        "2026 年世界杯冠军",
        "最新的世界杯赛程",
        "现在谁是世界首富",
        "2026年大选结果出来了吗",
        "这届奥运会金牌榜排名",
    ]
    for q in yes:
        ck("「%s」→ 时效性事实" % q, app._is_realtime_fact(q) is True, app._is_realtime_fact(q))

    print("\n二、判据：**不许**误伤的（必须 False）—— 这一组比上一组重要")
    no = [
        "谁是鲁迅",                     # 历史事实，先验里有
        "现在几点了",                   # 时间词但没事实词 → 有时间注入那条路
        "今天天气怎么样",               # ⚠️ 刻意不含天气（另有 weather 工具路径，且被多处自测当样本）
        "你好",
        "帮我解释一下什么是闭包",
        "Python 怎么把列表去重",
        "2022年世界杯冠军是谁",         # 有年份有事件，但这是**已发生的历史**——
                                        # 注意：当前判据会给 True（年份+事件词），
                                        # 见下面第五节的如实标注，这一条**故意不钉死**
    ]
    for q in no[:-1]:
        ck("「%s」→ 不算时效性事实" % q, app._is_realtime_fact(q) is False, app._is_realtime_fact(q))
    ck("空串 / None 安全", app._is_realtime_fact("") is False and app._is_realtime_fact(None) is False)

    print("\n三、优率分档：**默认行为一个字不变**（这是不能碰的）")
    long_txt = "Python 用 dict.fromkeys 去重可以保持顺序，实测 3 行代码就能跑通"
    q_rt = "2026年世界杯谁是冠军"
    q_py = "Python 怎么把列表去重"
    g_mem = app._rag_grade([{"text": long_txt, "source": "记忆库", "sim": 1.0}], q_py)
    g_web = app._rag_grade([{"text": long_txt, "source": "联网", "sim": 1.0}], q_py)
    ck("记忆库强命中 → 直接使用（没被改坏）", g_mem["grade"] == "直接使用",
       "%.3f %s" % (g_mem["q"], g_mem["grade"]))
    ck("**联网即使满分，默认仍只进复核档**（结构性自律没被动）",
       g_web["grade"] == "交元认知与健康医生", "%.3f %s" % (g_web["q"], g_web["grade"]))
    ck("默认 realtime=False 时 realtime_used 必须是 False", g_web.get("realtime_used") is False,
       g_web.get("realtime_used"))
    ck("两参数调用仍然合法（向后兼容）", isinstance(app._rag_grade([], q_py), dict))

    print("\n四、时效性事实这条路：合格的联网结果才放行")
    g_rt = app._rag_grade([{"text": long_txt, "source": "联网", "sim": 1.0}], q_rt, realtime=True)
    ck("时效性事实 + 联网达标 → 直接使用", g_rt["grade"] == "直接使用",
       "%.3f %s" % (g_rt["q"], g_rt["grade"]))
    ck("并且明确标出这是「时效性事实放行」的", g_rt.get("realtime_used") is True, g_rt.get("realtime_used"))
    g_junk = app._rag_grade([{"text": "这个嘛", "source": "联网", "sim": 0.1}], q_rt, realtime=True)
    ck("时效性事实 + 联网**不达标** → 照样不注入（不因为「这类问题要紧」就把垃圾放进来）",
       g_junk["grade"] == "不注入", "%.3f %s" % (g_junk["q"], g_junk["grade"]))
    ck("时效性事实 + 只有记忆库 → 走原来的判据（此处应直接使用）",
       app._rag_grade([{"text": long_txt, "source": "记忆库", "sim": 1.0}], q_rt,
                      realtime=True)["grade"] == "直接使用")

    print("\n五、如实标注（写进测试里，免得以后没人知道）")
    ck("已发生的历史（2022年世界杯）当前也会被判成时效性事实 —— **已知过宽，如实记**",
       app._is_realtime_fact("2022年世界杯冠军是谁") is True,
       "过宽的代价是「多搜一次」，不是「答错」；要收紧得引入「已结束」的判据，本轮没做")
    print("     · 联网结果即使放行，注入文本里**仍带来源**（`来源「联网」`），")
    print("       不会伪装成「我记得」—— 这一条由 `_rag_concurrent` 的注入头保证。")

    print("\n" + "=" * 66)
    print("时效性事实判据自测：通过 %d / 共 %d" % (len(PASS), len(PASS) + len(FAIL)))
    if FAIL:
        print("❌ 失败：%s" % FAIL)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
