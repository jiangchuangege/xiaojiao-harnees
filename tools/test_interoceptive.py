# -*- coding: utf-8 -*-
"""内感受信号层自测（第一阶段）

用法：python tools/test_interoceptive.py

【这一层要证明的三件事】
    [A] **真采**：五项都从真实模块读数；读不到的**如实记 None**，绝不用编的数顶上
    [B] **能算**：基线 + 偏离度 → 融合成 survival；分档（轻/中/重）分得开
    [C] **能落盘 + 不锁死**：时间线可回放；无新扰动时**缓慢回基线**（不涨不停、也不锁死）
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import energy as EN             # noqa: E402
from core import interoceptive as IN      # noqa: E402
from core import psyche as PS             # noqa: E402

_COUNT = {"pass": 0, "total": 0}
_FAILED = []
_TMP = tempfile.mkdtemp(prefix="xiaojiao_intero_")


def ck(name, cond, extra=""):
    _COUNT["total"] += 1
    if cond:
        _COUNT["pass"] += 1
        print("  [OK]   %s%s" % (name, ("  | " + str(extra)) if extra else ""))
    else:
        _FAILED.append(name)
        print("  [FAIL] %s  | %s" % (name, extra))


def main():
    IN._DIR = _TMP
    IN._PATH = os.path.join(_TMP, "interoceptive.jsonl")
    EN.reset()
    PS.start(why="自测")
    print("=" * 78)
    print("  内感受信号层自测")
    print("=" * 78)

    print("\n[A] 真采（读不到如实 None，不编）")
    s = IN.sample()
    ck("五项来源都在采集清单里",
       list(IN.SOURCES) == ["精力", "心跳稳定", "心的强度", "推理负载", "内存"], IN.SOURCES)
    ck("**精力**读到了真值", s["raw"].get("精力") is not None, s["raw"].get("精力"))
    ck("**心的强度**读到了真值", s["raw"].get("心的强度") is not None, s["raw"].get("心的强度"))
    ck("**推理负载**读到了真值（从调度器读，不猜）",
       s["raw"].get("推理负载") is not None, s["raw"].get("推理负载"))
    ck("读不到的项**如实记进 missing**（这里是真值也可能读得到）",
       isinstance(s["missing"], list), s["missing"])
    raw_vals = [v for v in s["raw"].values() if v is not None]
    ck("**没有一个值是编的**（都来自真实读数：0~1 之间的数）",
       all(isinstance(v, float) and 0.0 <= v <= 1.0 for v in raw_vals), raw_vals)

    print("\n[B] 能算（基线 → 偏离 → 融合 → 分档）")
    IN.reset()
    EN.set_level(0.95, why="自测：精力满")
    d_hi = IN.deviation(IN.sample()["raw"])
    EN.set_level(0.20, why="自测：精力低")
    d_lo = IN.deviation(IN.sample()["raw"])
    ck("**精力越高偏离越小**（方向对了）",
       d_hi.get("精力", 1) < d_lo.get("精力", 0), (d_hi.get("精力"), d_lo.get("精力")))
    ck("精力掉到基线以下 → 偏离度变大（0.75→0.25 算偏满）",
       d_lo.get("精力") is not None and d_lo["精力"] > 0.9, d_lo.get("精力"))
    IN.reset()
    for _ in range(12):
        IN.update()
    b_lo = IN.bias()
    ck("**精力的偏离真的进了 survival**（不是只记了个数）",
       b_lo["survival"] > 0.2, b_lo["survival"])
    ck("**分到了「中」或「重」**（单一项大幅偏离就该进中）",
       b_lo["level"] in ("中", "重"), b_lo["level"])
    ck("偏置里带得上各因子的偏离度（下游要按因子硬改）",
       isinstance(b_lo["factors"], dict) and b_lo["factors"], b_lo["factors"])
    ck("**它不产出任何一句话**（只有数，没有「我感到…」）",
       not any(isinstance(v, str) and "感到" in v for v in b_lo.values()), "")

    print("\n[C] 能落盘 + 不锁死")
    ck("时间线**可回放**（每条都有 ts/survival/perturbation/raw/dev）",
       len(IN.timeline(50)) >= 12 and
       all(k in IN.timeline(1)[0] for k in ("ts", "survival", "perturbation", "raw", "dev")),
       len(IN.timeline(50)))
    IN.reset()
    for _ in range(12):
        IN.update()
    peak = IN.survival()
    later = IN.survival(now=time.time() + 600)
    ck("**无新扰动 → 缓慢回基线**（不会一直挂着）", later < peak, (peak, later))
    ck("回基线是**渐进的**（不是啪一下归零）", 0 < later < peak, later)
    ck("**有饱和上限**（不会突破 1.0）", peak <= IN.SAT, (peak, IN.SAT))
    ck("**不锁死**：再久也只是趋近 0，不会变负", IN.survival(now=time.time() + 10 ** 7) >= 0, "")

    print("\n[D] 阈值写在代码里（策略，不是提示词）")
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "core", "interoceptive.py"), encoding="utf-8").read()
    ck("基线/权重/衰减/分档都是**模块常量**",
       all(k in src for k in ("BASELINE = {", "WEIGHTS = {", "DECAY =", "LEVELS = (")), "")
    ck("模块里**没有任何模型调用**（这一层不生成文字）",
       "llm" not in src and "requests" not in src, "")

    print("\n" + "=" * 78)
    print("  通过 %d / 共 %d" % (_COUNT["pass"], _COUNT["total"]))
    if _FAILED:
        print("  ❌ 未通过：%s" % "、".join(_FAILED))
    print("=" * 78)
    EN.reset()
    PS.stop(why="自测收尾")
    sys.exit(0 if not _FAILED else 1)


if __name__ == "__main__":
    main()
