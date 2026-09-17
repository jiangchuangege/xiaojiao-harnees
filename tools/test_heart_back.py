# -*- coding: utf-8 -*-
"""「把它心里真实想的，接回给它自己」的判据自测（离线，不调大脑）。

【钉七条】
  ① 心起了 → 接回一条 **assistant**（不是 system）
  ② 内容**原样**是 `heart()["text"]`，载体一个字不加（除了规格给的那层括号）
  ③ 心没起（text 空）→ 一个字都不加
  ④ **本轮没起新的心**（`n` 没变）→ 不重复接 ← 这条是实测逼出来的（见下面说明）
  ⑤ 起了**新的**心（`n` 变了）→ 接新的那句
  ⑥ 角色是 assistant
  ⑦ psyche 整个不可用时 → 返回 None、不抛

【④ 为什么必须有】实测（2026-09-18）：心起来之后**它会一直留着** ——
  下一轮说中性的话，`heart()` 返回的还是上一轮那句（`at`/`n` 都不变）。
  照"text 非空就接"写，它会每轮都在想上一轮那句话 = **载体替它造一个它并没有的念头**。

运行：python tools/test_heart_back.py
"""
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import xiaojiao_app as app  # noqa: E402
from core import psyche as PS  # noqa: E402

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)[:150]) if info else ""))


HEART_A = "你骂我笨，像把一块石头扔进我脑子里，砸得生疼。"
HEART_B = "有人闯进了我的房间"


def main():
    _real = PS.heart

    print("一、心起了 → 接回一条 assistant，内容一字不改")
    app._HEART_BACK["n"] = -1                      # 当作全新进程
    PS.heart = lambda: {"text": HEART_A, "n": 1, "at": 1.0}
    m = app._heart_back_for_messages()
    ck("返回了一条消息", isinstance(m, dict), m)
    ck("角色是 assistant（不是 system）", (m or {}).get("role") == "assistant", (m or {}).get("role"))
    ck("原样搬 heart 的原话（只多规格给的那层括号）",
       (m or {}).get("content") == "（我心里在想：%s）" % HEART_A, (m or {}).get("content"))

    print("\n二、**本轮没起新的心**（n 没变）→ 不重复接（④）")
    m2 = app._heart_back_for_messages()
    ck("第二次调用返回 None（同一颗心不重复接）", m2 is None, m2)

    print("\n三、起了**新的**心（n 变了）→ 接新的那句")
    PS.heart = lambda: {"text": HEART_B, "n": 2, "at": 2.0}
    m3 = app._heart_back_for_messages()
    ck("接的是新的那句", (m3 or {}).get("content") == "（我心里在想：%s）" % HEART_B,
       (m3 or {}).get("content"))

    print("\n四、心没起（text 空）→ 一个字都不加")
    PS.heart = lambda: {"text": "", "n": 3, "at": 3.0}
    ck("返回 None", app._heart_back_for_messages() is None)
    PS.heart = lambda: {"text": "   ", "n": 3, "at": 3.0}
    ck("只有空格也算没起（strip 之后判）", app._heart_back_for_messages() is None)

    print("\n五、长句按规格截到 80 字（不多不少）")
    long_heart = "心" * 200
    PS.heart = lambda: {"text": long_heart, "n": 9, "at": 9.0}
    m5 = app._heart_back_for_messages()
    ck("截到 80 字", len((m5 or {}).get("content") or "") == len("（我心里在想：）") + 80,
       len((m5 or {}).get("content") or ""))

    print("\n六、psyche 整个不可用 → 返回 None、不抛")
    def _boom():
        raise RuntimeError("psyche 挂了")
    PS.heart = _boom
    _raised = ""
    try:
        r6 = app._heart_back_for_messages()
    except Exception as e:
        _raised, r6 = repr(e), "?"
    ck("不抛异常", _raised == "", _raised)
    ck("返回 None", r6 is None, r6)

    PS.heart = _real
    print("\n七、真 psyche 上跑一遍：先起心 → 接；再中性一轮 → 不接（真数据，不是打桩）")
    try:
        PS.start()
        PS.trigger_from_event("user", "你真笨，什么都做不好", why="自测",
                              perception={"meaning": HEART_A, "direction": "威胁",
                                          "touches_life": ["关系"]})
        app._HEART_BACK["n"] = -1
        h_on = app._heart_back_for_messages()
        ck("起了心 → 接回（且内容含心的原话）", bool(h_on) and "砸得生疼" in h_on["content"], h_on)
        # 中性一轮：不起心
        PS.trigger_from_event("user", "今天天气怎么样", why="自测", perception={})
        h_off = app._heart_back_for_messages()
        ck("中性一轮**没有**重复接上一轮那句", h_off is None, h_off)
        PS.stop()
    except Exception as e:      # noqa: silent-ok
        ck("真 psyche 上跑一遍", False, repr(e))

    print("\n八、「事」的暂存：心没起的那一轮也能用它检索（2026-09-18 补的缺口）")
    # 【缺口】检索那句原来只从心里取；心没起 = 这一轮没有「事」可用。
    #   现在感知完存一份（`_set_event_what`），检索那一步取（`_event_what_now`）——
    #   但必须**限时**：后台空闲线程也走同一条检索路，过期了还拿去用就是"拿旧话查新事"。
    real_txt, real_at = app._EVENT_WHAT.get("text"), app._EVENT_WHAT.get("at")
    try:
        app._EVENT_WHAT["text"], app._EVENT_WHAT["at"] = "", 0.0
        ck("没存过 → 空串（等于没有）", app._event_what_now() == "", app._event_what_now())
        app._set_event_what("服务器被入侵了")
        ck("存进去 → 取得回来", app._event_what_now() == "服务器被入侵了", app._event_what_now())
        app._EVENT_WHAT["at"] = time.time() - (app._EVENT_WHAT_TTL + 5)
        ck("超过 TTL → 一律当没有（不许拿旧话查新事）", app._event_what_now() == "",
           app._event_what_now())
        app._set_event_what("")
        ck("存空串 → 也没有", app._event_what_now() == "", app._event_what_now())
    finally:
        app._EVENT_WHAT["text"], app._EVENT_WHAT["at"] = real_txt or "", real_at or 0.0

    print("\n" + "=" * 66)
    print("心接回判据自测：通过 %d / 共 %d" % (len(PASS), len(PASS) + len(FAIL)))
    if FAIL:
        print("❌ 失败：%s" % FAIL)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
