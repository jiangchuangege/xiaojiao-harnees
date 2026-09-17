# -*- coding: utf-8 -*-
"""第二处自测：`core/inner.py` render() 只给事实 + 事实与用户的话一起送感知层。

钉五条：
  ① render() 里**没有任何情绪命名**（孤独/低沉/抑郁/俏皮/没事干/此刻的心…）
  ② 给的是**原始字段名与数值**（lonely=0.xx 这种），不是中文情绪名
  ③ 没有任何"要不要…你自己定"这种**替它定语气**的指令
  ④ 读不到 / 没内容 → 返回空串（一个字不硬凑）
  ⑤ **事实真的进了感知层**：抓 `perception.perceive` 收到的原文，
     必须同时含「事实块」和「用户那句话」 ← 这是这次改动的关键接线

运行：python tools/test_inner_facts.py
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from core import inner as IN            # noqa: E402
import xiaojiao_app as app              # noqa: E402
from core import perception as PC       # noqa: E402

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)[:170]) if info else ""))


BANNED = ("孤独", "低沉", "抑郁", "俏皮", "没事干", "此刻的心", "要不要", "底色", "程度）")


def main():
    print("①+②+③ render() 只给事实，不带命名、不带语气指令")
    out = IN.render()
    print("---- 原样输出 ----")
    print(out if out.strip() else "（空）")
    print("------------------")
    ck("带 [此刻的事实] 表头", "[此刻的事实]" in out, out[:30])
    ck("没有情绪命名", not any(b in out for b in BANNED), [b for b in BANNED if b in out])
    ck("刻度用原始字段名（如 lonely= / depress=），不用中文情绪名",
       ("=" in out) or ("多久没人说话" in out), out[:120])
    ck("没有「要不要…你自己定」这类替它定语气的指令", "你自己定" not in out, out)

    print("\n④ 没内容 → 空串（一个字不硬凑）")
    _real_lonely, _real_bored, _real_S = IN.loneliness, IN.boredom, IN._S
    IN.loneliness = lambda now=None: {"idle_hours": 0.0, "lonely": 0.0}
    IN.boredom = lambda now=None: {"idle_minutes": 0.0, "bored": 0.0, "enough_to_act": False}
    IN._S = dict(_real_S)
    for _k in ("lonely", "low", "depress", "bored", "meaning", "guilt", "pride"):
        IN._S[_k] = 0
    _real_att, _real_grat, _real_bel = IN.attention, IN.gratitude, IN.beliefs
    IN.attention = lambda sources=None: {"bias": [], "text": ""}
    IN.gratitude = lambda k=5: []
    IN.beliefs = lambda k=5: []
    out2 = IN.render()
    ck("全空时返回空串", out2 == "", repr(out2))
    IN.loneliness, IN.boredom, IN._S = _real_lonely, _real_bored, _real_S
    IN.attention, IN.gratitude, IN.beliefs = _real_att, _real_grat, _real_bel

    print("\n⑤ 事实真的进了感知层（抓 perception.perceive 收到的原文）")
    got = {}

    def _fake_perceive(text, llm_fn=None, doing=None):
        got["text"] = text
        return {"meaning": "打桩", "direction": "无", "touches_life": []}

    _real = PC.perceive
    PC.perceive = _fake_perceive
    try:
        app._perceive_event("你真笨，什么都做不好")
    finally:
        PC.perceive = _real
    t = got.get("text") or ""
    print("---- 感知层收到的原文（前 260 字）----")
    print(t[:260])
    print("-------------------------------------")
    ck("含**用户那句话**", "你真笨，什么都做不好" in t, t[-60:])
    ck("含**它自己此刻的事实块**", "[此刻的事实]" in t, t[:60])

    print("\n" + "=" * 66)
    print("第二处（inner 只给事实 + 送进感知层）自测：通过 %d / 共 %d" % (len(PASS), len(PASS) + len(FAIL)))
    if FAIL:
        print("❌ 失败：%s" % FAIL)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
