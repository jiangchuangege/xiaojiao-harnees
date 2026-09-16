# -*- coding: utf-8 -*-
"""视角状态自测（第二阶段）

用法：python tools/test_perspective.py

【这一阶段要证明的四件事】
    [A] **慢**：一次 update 只挪一点点（`DECAY = 0.92`），像"处境"不像"情绪"
    [B] **持久化**：落盘 → 重新加载 → 值还在（重启后恢复）
    [C] **绝不随对话重置**：连续几轮对话后，扰动留下的痕迹**仍可检测**
    [D] **不是叙事机器**：本层只有三个数，**不产出任何一句话**
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.perspective as P              # noqa: E402
from core import energy as EN             # noqa: E402
from core import interoceptive as IN      # noqa: E402
from core import psyche as PS             # noqa: E402

_COUNT = {"pass": 0, "total": 0}
_FAILED = []
_TMP = tempfile.mkdtemp(prefix="xiaojiao_persp_")


def ck(name, cond, extra=""):
    _COUNT["total"] += 1
    if cond:
        _COUNT["pass"] += 1
        print("  [OK]   %s%s" % (name, ("  | " + str(extra)) if extra else ""))
    else:
        _FAILED.append(name)
        print("  [FAIL] %s  | %s" % (name, extra))


def _iso():
    IN._DIR = _TMP
    IN._PATH = os.path.join(_TMP, "interoceptive.jsonl")
    P._DIR = _TMP
    P._PATH = os.path.join(_TMP, "perspective.json")
    P._LOG = os.path.join(_TMP, "perspective.jsonl")
    EN.reset()
    IN.reset()
    P.reset("自测")


def main():
    print("=" * 78)
    print("  视角状态自测")
    print("=" * 78)
    PS.start(why="自测")

    print("\n[A] 慢：一次只挪一点点")
    _iso()
    g0 = dict(P.G)
    EN.set_level(0.20, why="自测：精力低")
    g1 = P.update()
    ck("**一次 update 变化很小**（<0.2：它要像处境，不像情绪）",
       abs(g1["vigilance"] - g0["vigilance"]) < 0.20,
       (g0["vigilance"], g1["vigilance"]))
    ck("方向对：精力低 → **警觉往上走**", g1["vigilance"] >= g0["vigilance"],
       (g0["vigilance"], g1["vigilance"]))
    ck("演化公式就是 `g ← decay·g + (1−decay)·perturbation`",
       "cur * DECAY + float(p.get(k)" in
       open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "core", "perspective.py"), encoding="utf-8").read(), "")
    for _ in range(30):
        P.update()
    g2 = P.G["vigilance"]
    ck("**持续偏离时会累积上去**（不是只挪一次就停）", g2 > g1["vigilance"],
       (g1["vigilance"], g2))
    ck("但有**上限**（0~1，不会失控）", 0.0 <= g2 <= 1.0, g2)

    print("\n[B] 持久化（重启后恢复）")
    saved = P.save()
    ck("落盘了", os.path.exists(P.path()), P.path())
    before = dict(P.G)
    P.G = dict(P.NEUTRAL)          # 模拟"进程重启，内存里没了"
    P._S["_loaded"] = False
    again = P.load()
    ck("**重新加载后值还在**（重启后恢复）",
       abs(again["vigilance"] - before["vigilance"]) < 1e-6, (before["vigilance"], again["vigilance"]))
    d = json.load(open(P.path(), encoding="utf-8"))
    ck("盘上存的是**三个维度 + 计数**", all(k in d for k in list(P.DIMS) + ["updates", "turns"]),
       sorted(d.keys()))

    print("\n[C] **绝不随对话重置**（规格点名的铁律）")
    _iso()
    EN.set_level(0.15, why="自测：先制造一次扰动")
    for _ in range(20):
        P.update()
    peak = P.G["vigilance"]
    ck("扰动已经把警觉抬起来了", peak > 0.25, peak)
    marks = []
    for i in range(3):
        P.note_dialogue_turn(why="自测第 %d 轮" % (i + 1))
        marks.append(P.G["vigilance"])
    ck("**连续 3 轮对话后，痕迹仍在**（没有一轮把它清零）",
       all(m > 0.10 for m in marks), marks)
    ck("**对话轮次被记下来了**", P.state()["turns"] == 3, P.state()["turns"])
    ck("对话让它继续演化，而不是重置（3 轮不是单调归零）",
       marks[-1] > 0.10, marks)
    # 恢复精力后，它应当**缓慢**回落，而不是立刻回中性
    EN.set_level(0.95, why="自测：精力回来了")
    for _ in range(3):
        P.update()
    ck("**恢复精力后是缓慢回落**（不是啪一下回中性）",
       P.G["vigilance"] > P.NEUTRAL["vigilance"], P.G["vigilance"])

    print("\n[D] 不是叙事机器")
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "core", "perspective.py"), encoding="utf-8").read()
    ck("模块里**没有任何模型调用**（不生成一句话）", "llm" not in src and "requests" not in src, "")
    ck("`bias()` 只回数（三个维度 + 一个档），没有句子",
       all(not isinstance(v, str) or v in ("轻", "中", "重")
           for k, v in P.bias().items() if k != "note"), "")
    ck("扰动源写清楚了（来自内感受层，不是编的）",
       "interoceptive" in src and "sources" in src, "")

    print("\n" + "=" * 78)
    print("  通过 %d / 共 %d" % (_COUNT["pass"], _COUNT["total"]))
    if _FAILED:
        print("  ❌ 未通过：%s" % "、".join(_FAILED))
    print("=" * 78)
    EN.reset()
    IN.reset()
    P.reset("自测收尾")
    PS.stop(why="自测收尾")
    sys.exit(0 if not _FAILED else 1)


if __name__ == "__main__":
    main()
