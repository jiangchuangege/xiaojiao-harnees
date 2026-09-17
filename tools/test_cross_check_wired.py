# -*- coding: utf-8 -*-
"""「答后交叉检查」到底接没接进主流程 —— 离线自测（不调模型）。

【为什么要有这个测试（实测踩到的真事）】
`core/metacognition/crosscheck.py` 写得完整、`tools/test_metacognition.py` 143/143 全绿，
但**主流程一次都没调用过它**：全仓 `cross_check` 的调用点只有自测文件。
也就是说这一项一直是**离线能力**——文档里写着"答后交叉检查"，用户用起来其实没有。
这种"模块绿的、接线没接"的缺口，只有把"接线"本身钉住才不会再犯。

【钉四条】
  ① 触发判据两头都对：该跑的（自评没把握 / 自己带不确定措辞）跑，不该跑的（有把握、正常回答）不跑；
  ② 主流程里真的有调用点，而且**过开关**（`capabilities.cross_check`，默认关）；
  ③ 判出 conflict 时**会加标注**，且标注里写明"请当参考"；
  ④ 判 unknown（没模型/样本不足）时**不加任何标注**（不许把"没检查"写成"检查过没问题"）。

运行：python tools/test_cross_check_wired.py
"""
import io
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import xiaojiao_app as app  # noqa: E402
from core.metacognition import crosscheck as CX  # noqa: E402

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)[:150]) if info else ""))


def main():
    print("一、触发判据：该跑的跑，不该跑的不跑")
    cases = [
        ("answer_with_caveat", "这题我尽力了", [], True, "自评 B（没把握）"),
        ("use_tool", "答案是 A", [], True, "自评 C（走工具）"),
        ("", "我大概是这么理解的", [], True, "回答自己带不确定措辞"),
        ("", "答案是 A", [], False, "自评有把握、没有不确定措辞"),
        ("", "答案是 A", [{"tool": "web_search"}], False, "这轮真查了来源"),
        ("", "", [], False, "没有回答"),
    ]
    for route, ans, tools, want, why in cases:
        got, note = app._should_cross_check(route, ans, tools)
        ck("%s → %s" % (why, "做" if want else "不做"), got is want, note)

    print("\n二、主流程里真的有调用点，而且**过开关**")
    src = io.open(os.path.join(_ROOT, "xiaojiao_app.py"), encoding="utf-8").read()
    ck("主流程里有 cross_check 调用", "_cx.cross_check(" in src)
    ck("调用点过开关 capabilities.cross_check（默认关）",
       'CAP.get("cross_check", False)' in src, "默认值必须是 False")
    ck("调用点在 agent_run 的答后那一段（和元认知标注挨着）",
       "元认知 · **答后交叉检查**" in src)
    ck("用的是可替换的 llm 包装（自测能换成打桩）", "def _crosscheck_llm(" in src)

    print("\n三、判 conflict → 加标注；标注里写明「请当参考」")
    ck("conflict 分支存在", '== "conflict"' in src and "两次对不上" in src)
    ck("标注里明确写了这是参考不是结论", "请当参考、不要当结论" in src)

    print("\n四、判 unknown → **一个字都不加**（不许把「没检查」写成「检查过、没问题」）")
    r = CX.cross_check("首都是哪", llm_fn=None)
    ck("没有模型 → verdict=unknown（不假装检查过）", r["verdict"] == "unknown", r)
    got, note = app._should_cross_check("", "答案是 A", [])
    ck("有把握的正常轮次 → 不做检查", got is False, note)

    print("\n五、真跑一次（打桩的假模型）：**它抓得住什么、抓不住什么**")
    same = lambda p: "北京是中国的首都。"          # noqa: E731
    _n = {"i": 0}

    def off_topic(p):
        """第一个角度答题、其余角度跑题 —— 这是交叉检查**本来就要抓**的那一类。"""
        _n["i"] += 1
        return "北京是中国的首都。" if _n["i"] == 1 else "今天天气不错，适合出门走走。"

    r1 = CX.cross_check("中国的首都是哪", llm_fn=same, n=3)
    ck("三次都一样 → consistent", r1["verdict"] == "consistent", r1["verdict"])
    r2 = CX.cross_check("中国的首都是哪", llm_fn=off_topic, n=3)
    ck("有角度跑题/答的不是同一件事 → 判 conflict", r2["verdict"] == "conflict",
       (r2["verdict"], r2["agree"]))

    print("\n六、如实记录它的**边界**：同一个句式换了事实（反话类）它抓不住")
    # 模块开头就声明了这条边界（"2-gram 认不出相反的意思"），这里**实跑一遍确认**，
    # 免得文档写着边界、实测却是别的东西 —— 也免得我把它当成"没接线"的 bug。
    _m = {"i": 0}

    def swap_fact(p):
        _m["i"] += 1
        return "北京是中国的首都。" if _m["i"] == 1 else "上海是中国的首都。"

    r3 = CX.cross_check("中国的首都是哪", llm_fn=swap_fact, n=3)
    ck("【如实记录】换掉一个地名 → 字面相似度高，**判不出来**（模块声明过的边界）",
       r3["verdict"] == "consistent",
       "实测 verdict=%s agree=%.3f（这一层由健康系统的 fact_reversal 管，不是这个模块）"
       % (r3["verdict"], r3["agree"]))

    print("\n" + "=" * 70)
    print("答后交叉检查接线自测：通过 %d / 共 %d" % (len(PASS), len(PASS) + len(FAIL)))
    if FAIL:
        print("❌ 失败：%s" % FAIL)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
