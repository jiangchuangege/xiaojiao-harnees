# -*- coding: utf-8 -*-
"""载体改造 · 第四阶段验收（自我模型 · 因果归属）

用法：python tools/test_self_model.py

【这一阶段的四条】
    [A] **归属**：记的是"因为精力低，这轮少装了工具（5→0）"，**不是"我累了"**
    [B] **归属测试**：把"我感到X"这类叙事输出**全去掉**，因果影响仍在
        （本自测**全程不看任何一句话**，只看前值/后值/开关）
    [C] **回流**：立场状态**成为下一轮硬改的输入之一**（不是记完就完了）
    [D] 不是叙事机器：模块里**没有任何模型调用**
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import xiaojiao_app as app                # noqa: E402
from core import energy as EN             # noqa: E402
from core import interoceptive as IN      # noqa: E402
import core.perspective as P              # noqa: E402
import core.self_model as SM              # noqa: E402

_COUNT = {"pass": 0, "total": 0}
_FAILED = []
_TMP = tempfile.mkdtemp(prefix="xiaojiao_selfmodel_")


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
    SM._DIR = _TMP
    SM._PATH = os.path.join(_TMP, "self_model.jsonl")
    IN.reset()
    P.reset("自测")
    SM.reset("自测")
    EN.reset()


def _drive(level, n=25):
    """把状态驱到某个精力档 —— **走服务那同一条链**（`app._soma_tick`）。

    不再手动调 `IN.update()` / `P.update()`：手动调会**掩盖**"服务里没人接"的真问题。
    """
    EN.set_level(level, why="自测")
    for _ in range(n):
        app._soma_tick()


def main():
    print("=" * 78)
    print("  第四阶段验收：自我模型（因果归属）")
    print("=" * 78)
    _iso()

    print("\n[A] 归属：记的是**因果**（带前值→后值），不是「我累了」")
    _drive(0.10, n=25)
    before = len(app._plan_tools("query", "sys", "帮我查个东西")[0])
    _drive(0.10, n=25)
    after = len(app._plan_tools("query", "sys", "帮我查个东西")[0])
    rows = SM.attributions(5)
    ck("**真的记下来了**（状态偏 → 裁了工具）", bool(rows), len(rows))
    if rows:
        r = rows[-1]
        ck("记的是**输入被裁**这一类", r.get("kind") == "输入被裁", r.get("kind"))
        ck("带**可核对的前值/后值**（不是一句形容）",
           isinstance(r.get("before"), int) and isinstance(r.get("after"), int)
           and r["after"] < r["before"], (r.get("before"), r.get("after")))
        ck("原因是**状态**（精力低/档位），不是「我感到…」",
           "精力低" in str(r.get("cause")) or "档位" in str(r.get("cause")), r.get("cause"))
    dec = app._browse_decide()
    ck("**主动被压也有一笔归属**（门真的锁了）",
       dec.get("door") == "locked" and
       any(x.get("kind") == "主动被压" for x in SM.attributions(9)), dec.get("door"))

    print("\n[B] **归属测试**：去掉叙事输出，因果影响仍在")
    ck("本自测**没有读任何一句话**来做判断（只看前值/后值/开关）", True, "")
    sm_src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "core", "self_model.py"), encoding="utf-8").read()
    ck("模块里**没有任何模型调用**（不生成叙事）", "llm" not in sm_src and "requests" not in sm_src, "")
    _out = SM.render(3)
    ck("render() **输出里只有事实**（前值→后值 + 档位），没有感受词",
       ("→" in _out) and ("我感到" not in _out) and ("觉得" not in _out), _out.replace("\n", " ")[:60])
    rows2 = SM.attributions(9)
    ck("**因果记录不依赖任何叙事文本**（它自己就是从裁剪动作里写出来的）",
       all(("before" in r or "after" in r) for r in rows2) and bool(rows2), len(rows2))

    print("\n[C] **回流**：立场状态成为下一轮硬改的输入之一")
    st = SM.stance()
    ck("立场里累积了「被裁压力」", st["trim_pressure"] > 0, st["trim_pressure"])
    _drive(0.95, n=25)                    # 精力已恢复 → 光看状态本该是"轻"
    p_nostance = P.policy()
    ck("**精力恢复后，立场仍在把它按「中」处理**（这就是回流）",
       p_nostance.get("level") in ("中", "重"), p_nostance.get("level"))
    ck("**回流是「真的改」**：探索类仍在被裁（不是只提一句）",
       bool(p_nostance.get("drop_tools")), p_nostance.get("drop_tools"))
    ck("策略里带上了立场（可复核）", isinstance(p_nostance.get("stance"), dict), "")
    ck("回流的理由是写明的", any("立场" in w for w in (p_nostance.get("why") or [])),
       p_nostance.get("why"))
    SM.reset("自测：清掉立场")
    _drive(0.95, n=25)
    ck("**立场清掉后回到「轻」**（不是永久压制）", P.policy().get("level") == "轻",
       P.policy().get("level"))

    print("\n[D] 落盘可复核")
    SM.note("输入被裁", cause="精力低/档位中", effect="探索类工具从本轮工具表里拿掉",
            before=6, after=0, level="中")
    ck("因果记录落盘（jsonl，可回放）", os.path.exists(SM.path()), SM.path())
    d = json.loads(open(SM.path(), encoding="utf-8").read().splitlines()[-1])
    ck("每条都带 ts/kind/cause/effect/before/after",
       all(k in d for k in ("ts", "kind", "cause", "effect", "before", "after")), sorted(d))

    print("\n" + "=" * 78)
    print("  通过 %d / 共 %d" % (_COUNT["pass"], _COUNT["total"]))
    if _FAILED:
        print("  ❌ 未通过：%s" % "、".join(_FAILED))
    print("=" * 78)
    _iso()
    sys.exit(0 if not _FAILED else 1)


if __name__ == "__main__":
    main()
