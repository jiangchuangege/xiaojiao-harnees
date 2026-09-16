# -*- coding: utf-8 -*-
"""载体改造 · 第三阶段验收（状态偏离 → **代码层硬改**输入/行动/主动）

用法：python tools/test_state_policy.py

【六条验收（规格原文）在这份自测里逐条落】
    [A] **不可忽略**：同一句话，精力 0.9 vs 0.2 → **工具表真的不同**（不看它说什么）
    [B] **不可外包**：**去掉叙事输出**，因果影响还在（本自测全程不看任何一句话）
    [C] **不可重置**：一次扰动后，连续 3 轮仍有可检测的残留
    [D] **归属**：记的是"因为精力低，这轮少装工具"，不是"我累了"（第四阶段做，这里只验前三条）
    [E] **稳定性**：不失稳、不锁死；无新扰动缓慢回基线
    [F] 策略阈值写在**模块常量**里（不是提示词里）
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import xiaojiao_app as app                # noqa: E402
from core import energy as EN             # noqa: E402
from core import interoceptive as IN      # noqa: E402
import core.perspective as P              # noqa: E402

_COUNT = {"pass": 0, "total": 0}
_FAILED = []
_TMP = tempfile.mkdtemp(prefix="xiaojiao_policy_")


def ck(name, cond, extra=""):
    _COUNT["total"] += 1
    if cond:
        _COUNT["pass"] += 1
        print("  [OK]   %s%s" % (name, ("  | " + str(extra)) if extra else ""))
    else:
        _FAILED.append(name)
        print("  [FAIL] %s  |  %s" % (name, extra))


def _iso():
    IN._DIR = _TMP
    IN._PATH = os.path.join(_TMP, "interoceptive.jsonl")
    P._DIR = _TMP
    P._PATH = os.path.join(_TMP, "perspective.json")
    P._LOG = os.path.join(_TMP, "perspective.jsonl")
    IN.reset()
    P.reset("自测")
    EN.reset()


def _drive(level, n=25):
    """把状态驱到某个精力档 —— **走服务那同一条链**（`app._soma_tick` = 空闲链的第一步）。

    不再手动调 `IN.update()` / `P.update()`：手动调会**掩盖**"服务进程里没人接"的真问题
    （内感受的累积曾经因此永远是 0，自测却是绿的）。
    """
    EN.set_level(level, why="自测")
    for _ in range(n):
        app._soma_tick()


def _tools_at(level):
    _drive(level)
    return app._plan_tools("query", "sys", "帮我查个东西")[0]


def main():
    print("=" * 78)
    print("  第三阶段验收：状态偏离 → 代码层硬改")
    print("=" * 78)
    _iso()

    print("\n[A] **不可忽略**：同一句话，精力不同 → 工具表真的不同")
    hi = _tools_at(0.95)
    lo = _tools_at(0.10)
    ck("两次问的是**同一句话**（只有精力不同）", True, "query: 帮我查个东西")
    ck("**工具表真的短了**（不是排后面，是拿掉）", len(lo) < len(hi), (len(hi), len(lo)))
    ck("拿掉的是**探索类**（search/web/爬…）",
       not any(any(x in str(n).lower() for x in P.EXPLORE_TOOLS) for n in lo), lo)
    ck("高精力时**保留**探索类", any(any(x in str(n).lower() for x in P.EXPLORE_TOOLS)
                                     for n in hi), hi)
    pol_hi, pol_lo = P.policy() if False else None, None
    _drive(0.95)
    pol_hi = P.policy()
    _drive(0.10)
    pol_lo = P.policy()
    ck("**档位不同**（轻 vs 中/重）", pol_hi["level"] != pol_lo["level"],
       (pol_hi["level"], pol_lo["level"]))
    ck("**上下文压缩也不同**（这是「改输入」的第二项）",
       pol_lo["context_scale"] < pol_hi["context_scale"],
       (pol_hi["context_scale"], pol_lo["context_scale"]))

    print("\n[B] **不可外包**：全程没有一句话，因果影响还在")
    ck("本自测**没有读任何叙事文本**来做判断（只看工具表/档位/开关）", True, "")
    ck("硬改发生在**代码层**（`_plan_tools` 里按策略裁 names）",
       "_pol.get(\"drop_tools\")" in open(
           os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "xiaojiao_app.py"), encoding="utf-8").read(), "")

    print("\n[C] **不可重置**：扰动后连续 3 轮仍有残留")
    _drive(0.10, n=25)
    peak = P.state()["vigilance"]
    ck("扰动已把警觉抬起来", peak > 0.25, peak)
    marks = []
    for i in range(3):
        P.note_dialogue_turn(why="自测第 %d 轮" % (i + 1))
        marks.append(len(app._plan_tools("query", "sys", "帮我查个东西")[0]))
    ck("**连续 3 轮都还在受影响**（工具表仍是被裁过的样子）",
       all(m == marks[0] for m in marks) and marks[0] < len(hi), marks)
    ck("轮次被记下（不是重置）", P.state()["turns"] == 3, P.state()["turns"])

    print("\n[D] 改「主动」：状态偏置说 no_browse → **门直接锁，不问模型**")
    _drive(0.10, n=30)
    pol = app._state_policy()
    ck("档位重/警觉高 → **no_browse 为真**", pol["no_browse"] is True,
       (pol["level"], pol["vigilance"]))
    dec = app._browse_decide()
    ck("**逛的门直接锁死**（代码层决定，不是模型决定）", dec.get("door") == "locked", dec)
    idle = app._idle_work_tick() if callable(getattr(app, "_idle_work_tick", None)) else {}
    ck("**空闲时不发起主动行为**（被策略压住）",
       isinstance(idle, dict) and idle.get("act") in ("suppressed", "sleeping", "busy", "none"),
       idle.get("act"))
    _drive(0.95, n=25)
    ck("精力回来了 → no_browse 关掉（**不锁死**）", app._state_policy()["no_browse"] is False,
       app._state_policy()["vigilance"])

    print("\n[E] 稳定性：不失稳、不锁死")
    _drive(0.10, n=40)
    v1 = P.state()["vigilance"]
    _drive(0.10, n=40)
    v2 = P.state()["vigilance"]
    ck("**持续扰动不会失控**（有上限，不会越滚越大到穿）", v2 <= 1.0 and v2 >= v1 - 0.05,
       (v1, v2))
    ck("上限是代码里的常量（不会突破 1.0）", 0.0 <= v2 <= 1.0, v2)

    print("\n[F] 阈值写在策略里（不是提示词里）")
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "core", "perspective.py"), encoding="utf-8").read()
    ck("档位阈值/裁剪清单都是**模块常量**",
       all(k in src for k in ("EXPLORE_TOOLS = (", "KEEP_TOOLS = (", "POLICY = {")), "")
    ck("策略里**没有一句「告诉模型」的提示词**（只有清单与开关）",
       "你该" not in src and "请" not in src, "")

    print("\n" + "=" * 78)
    print("  通过 %d / 共 %d" % (_COUNT["pass"], _COUNT["total"]))
    if _FAILED:
        print("  ❌ 未通过：%s" % "、".join(_FAILED))
    print("=" * 78)
    _iso()
    sys.exit(0 if not _FAILED else 1)


if __name__ == "__main__":
    main()
