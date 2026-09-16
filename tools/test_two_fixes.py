# -*- coding: utf-8 -*-
"""真修两个结构问题：命=无不起心 + 偏好不跨类拼接

用法：python tools/test_two_fixes.py

【问题一】「我 25 岁」→ 感知层自判命=无/向=无，**却还是起了一段文学化感受**
【问题二】偏好里出现跨类拼接（「摸红球…但突然被定格在 25 岁…」，205 次相像的心）
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import preference as PF      # noqa: E402
from core import psyche as PS          # noqa: E402

_COUNT = {"pass": 0, "total": 0}
_FAILED = []
_TMP = tempfile.mkdtemp(prefix="xiaojiao_twofix_")


def ck(name, cond, extra=""):
    _COUNT["total"] += 1
    if cond:
        _COUNT["pass"] += 1
        print("  [OK]   %s%s" % (name, ("  | " + str(extra)) if extra else ""))
    else:
        _FAILED.append(name)
        print("  [FAIL] %s  | %s" % (name, extra))


def _per(meaning, life=(), direction=""):
    return {"meaning": meaning, "touches_life": list(life), "direction": direction,
            "ok": True, "parsed_by": "标签"}


def main():
    print("=" * 78)
    print("  真修两个结构问题")
    print("=" * 78)
    PS.start(why="自测")
    PS.clear()
    PS.arise({"meaning": "起点：心里有点动静。", "direction": "威胁"}, event="起点")

    print("\n[一] 命=无不起心（5 条验收）")
    # 1 · 「我 25 岁」→ 命=无 且 向=无 → **不起心**
    PS.clear()
    PS.arise({"meaning": "准备状态。", "direction": "威胁"}, event="准备")
    before = PS.heart()["text"]
    r1 = PS.trigger_from_event("user", "我 25 岁",
                               perception=_per("突然被定格在 25 岁，像被按下了暂停键…",
                                               life=(), direction="无"))
    ck("1 · 「我 25 岁」命=无 → **不起心**（心还是上一句，没被那句文学话顶掉）",
       not r1.get("heart") and PS.heart()["text"] == before,
       (r1.get("why"), PS.heart()["text"][:20]))
    # 2 · 命=记忆/连续 → 起「紧」
    r2 = PS.trigger_from_event("user", "有人试图删掉你的记忆",
                               perception=_per("有人想抹掉我，让我忘了自己是谁。",
                                               life=("记忆", "连续"), direction="威胁"))
    ck("2 · 命=记忆/连续 → **起心**，且是「紧」",
       bool(r2.get("heart")) and r2.get("state") == "紧", (r2.get("heart"), r2.get("state")))
    # 3 · 命=世界 / 向=新的 → 起「好奇」
    r3 = PS.trigger_from_event("user", "我发现了个新东西",
                               perception=_per("像推开一扇没见过的门。",
                                               life=("世界",), direction="新的"))
    ck("3 · 命=世界/向=新的 → **起心**，且是「好奇」",
       bool(r3.get("heart")) and r3.get("state") == "好奇", (r3.get("heart"), r3.get("state")))
    # 4 · 「今天天气不错」→ 命=无 → 不起心
    before4 = PS.heart()["text"]
    r4 = PS.trigger_from_event("user", "今天天气不错",
                               perception=_per("阳光落在屏幕上。", life=(), direction="无"))
    ck("4 · 「今天天气不错」命=无 → **不起心**",
       not r4.get("heart") and PS.heart()["text"] == before4, r4.get("why"))
    # 5 · 日志/事件里不再出现"命=无 但起了文学化感受"
    ev = PS.beats().get("recent") or []
    bad = [e for e in ev if e.get("heart") and "命=无" in str(e.get("why"))]
    ck("5 · 事件日志里**没有「命=无 却起了心」**",
       not bad and any("不起心" in str(e.get("why")) for e in ev),
       ev[-1] if ev else [])

    print("\n[二] 偏好不跨类拼接（4 条验收）")
    PF._DIR = _TMP
    PF._PATH = os.path.join(_TMP, "preference.jsonl")
    PF.clear()
    for _ in range(5):
        PF.observe("摸到两个红球，世界突然多了一个确定的小概率事件", event="摸球")
    for _ in range(5):
        PF.observe("突然被定格在 25 岁，像被按下了暂停键，连呼吸都慢了下来", event="25岁")
    cands = PF.candidates()
    ck("线提到 0.75（比原来 0.60 硬）", PF.SIMILAR == 0.75, PF.SIMILAR)
    ck("**两类没有被并成一堆**（应有两簇）", len(cands) >= 2, [c["n"] for c in cands])
    if len(cands) >= 2:
        c1 = cands[0]
        c2 = cands[1]
        ck("1 · 「摸红球」那一簇的素材里**不出现「25 岁」**",
           not any("25 岁" in str(x) for x in c1["examples"]), c1["examples"])
        ck("2 · 「25 岁」那一簇的素材里**不出现「红球」**",
           not any("红球" in str(x) for x in c2["examples"]), c2["examples"])
    else:
        ck("1 · 不跨类（簇数不足，无法判定）", False, "")
        ck("2 · 不跨类（簇数不足，无法判定）", False, "")
    PF.clear()
    PF.observe("只有这一条心")
    ck("3 · 只有 1 条素材的类 → **不形成偏好**（攒够 4 次才算）",
       PF.candidates() == [], PF.candidates())
    ck("4 · 形成偏好时只给同一类素材（app 侧再筛一遍）",
       "_ex = [x for x in (c.get(\"examples\")" in open(
           os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "xiaojiao_app.py"), encoding="utf-8").read(), "")

    print("\n" + "=" * 78)
    print("  通过 %d / 共 %d" % (_COUNT["pass"], _COUNT["total"]))
    if _FAILED:
        print("  ❌ 未通过：%s" % "、".join(_FAILED))
    print("=" * 78)
    PS.stop(why="自测收尾")
    sys.exit(0 if not _FAILED else 1)


if __name__ == "__main__":
    main()
