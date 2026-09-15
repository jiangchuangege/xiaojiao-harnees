# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""原料自测（给原料，不给成品）

用法：
    python tools/test_raw.py

它验的是"载体给原料、模型自己组织"这条规矩到底立没立住，一共五组：
    [A] 原料的形状    四个字段一个都不能少；`took_part` 不许含糊
    [B] 是原料不是成品 给出去的是**字段**，不是一句能照抄的话
    [C] 跨轮留着       "你咋知道的"那一轮本身没有计算，台账必须还在
    [D] 直算走原料     `calc.material()` 给原料；`answer_text()` 只剩兜底
    [E] 工具也进台账   结果 + 谁产的 + 它有没有参与 + 原始参数
    [F] 数字校验       模型把数字说错时，载体兜底（正确性底线）

【为什么 [B] 是重点】
    规格的分界线就这一条：**给原料 = 一条一条的事实字段；给成品 = 一句能照搬的话**。
    这里用机器把 render() 的输出形状钉住 —— 每一行都必须是「字段：值」。
"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import calc as C                 # noqa: E402
from core import raw as RW                 # noqa: E402

_COUNT = {"pass": 0, "total": 0}
_FAILED = []
_TMP = tempfile.mkdtemp(prefix="xiaojiao_raw_")
_REAL_PATH = RW.path()


def ck(name, cond, extra=""):
    _COUNT["total"] += 1
    if cond:
        _COUNT["pass"] += 1
        print("  [OK]   %s%s" % (name, ("  | " + str(extra)) if extra else ""))
    else:
        _FAILED.append(name)
        print("  [FAIL] %s  | %s" % (name, extra))


def _isolate():
    RW._DIR = _TMP
    RW._PATH = os.path.join(_TMP, "material.jsonl")
    RW.clear("自测")


def group_a():
    print("\n[A] 原料的形状（四个字段一个都不能少）")
    _isolate()
    r = RW.record(result="10000000000", source=RW.SOURCE_CALC, took_part=False,
                  raw="100000 * 100000", who_asked="载体", how="十进制乘法", kind="arithmetic_cn")
    ck("字段齐全", all(k in r for k in RW.FIELDS), list(r.keys()))
    ck("结果在里面", r["result"] == "10000000000", r["result"])
    ck("**谁产的**在里面", RW.SOURCE_CALC in r["source"], r["source"])
    ck("**它有没有参与**在里面，且载体直算 = 没有参与", r["took_part"] is False, r["took_part"])
    ck("怎么来的（原始数据）在里面", r["raw"] == "100000 * 100000", r["raw"])
    r2 = RW.record(result="x", source="工具 web_search", took_part=True)
    ck("它自己参与过的那一步可以标成 True（这一栏不许含糊）", r2["took_part"] is True, "")
    ck("有人发起也记下来了", "who_asked" in r2, r2["who_asked"])


def group_b():
    print("\n[B] 是原料不是成品（给字段，不给一句能照抄的话）")
    _isolate()
    RW.record(result="10000000000", source=RW.SOURCE_CALC, took_part=False,
              raw="100000 * 100000", who_asked="载体", how="十进制乘法", kind="arithmetic_cn")
    body = RW.render(3)
    line_re = re.compile(r"^(【|怎么用|结果：|谁产出的：|这一步你参与了吗：|怎么来的：|原始数据：|谁发起的：|\d+\.)")
    bad = [ln for ln in body.split("\n") if ln.strip() and not line_re.match(ln.strip())]
    ck("**每一行都是「字段：值」**（没有一整句话给它照搬）", bad == [], bad[:2])
    ck("明说这是原料、不是话、不是答案",
       "不是成品" in body and "不是给你的话" in body and "不是答案" in body, "")
    ck("**没有那句成品**（不许出现「这是计算器算的」这种整句）",
       "这是计算器算的" not in body, "")
    ck("给了「怎么用」：自己推、自己组织、不要照抄", "你自己推" in body and "不要照抄" in body, "")
    ck("渲染出来带上了「你参与了吗：没有」", "没有 ——" in body, "")


def group_c():
    print("\n[C] 跨轮留着（「你咋知道的」那一轮本身没有计算）")
    _isolate()
    RW.record(result="10000000000", source=RW.SOURCE_CALC, took_part=False, raw="100000 * 100000")
    # 模拟：算完这一轮之后，用户又说了几句别的话 —— 台账还在
    RW.record(result="无关的一条", source="工具 x", took_part=False)
    RW.record(result="无关的一条 2", source="工具 y", took_part=False)
    got = [x["result"] for x in RW.recent(3)]
    ck("**算过的原料还在台账里**（问「你咋知道的」时手里有东西）",
       "10000000000" in got, got)
    ck("台账有上限（不会无限涨）", RW.MAX_KEEP == 6, RW.MAX_KEEP)
    for i in range(10):
        RW.record(result="灌水 %d" % i, source="工具 z", took_part=False)
    ck("超上限后只留最近几条", len(RW.recent(99)) <= RW.MAX_KEEP, len(RW.recent(99)))


def group_d():
    print("\n[D] 直算走原料（answer_text 只剩兜底）")
    _isolate()
    m = C.material("100000乘以100000呢")
    ck("给得出原料", bool(m), m)
    ck("结果对", str(m.get("result")) == "10000000000", m.get("result"))
    ck("**谁算的写清楚了**（载体的计算器，不经过它）", "计算器" in str(m.get("source")), m.get("source"))
    ck("**它没参与**（这一栏是 False，不许写成它自己算的）", m.get("took_part") is False, "")
    ck("原始算式在里面", "100000" in str(m.get("raw")), m.get("raw"))
    ck("怎么来的也说了（中文算式翻成什么）", "乘法" in str(m.get("how")), m.get("how"))
    at = C.answer_text("100000乘以100000呢")
    ck("兜底那句仍然是完整成品（它现在的用处只剩兜底）",
       "10000000000" in at and "载体" in at, at[:40])
    ck("原料比成品多了「谁产的/有没有参与」这两样",
       "source" in m and "took_part" in m and "source" not in at, "")


def group_e():
    print("\n[E] 工具结果也进台账")
    _isolate()
    import xiaojiao_app as app
    app._raw_record_tool("get_weather", {"city": "成都"}, "成都 26℃ 晴")
    it = RW.recent(1)[-1]
    ck("工具结果记下来了", "成都 26℃" in it["result"], it["result"])
    ck("**谁产的**写的是哪个工具", "get_weather" in it["source"], it["source"])
    ck("**执行不是它做的**（took_part=False）", it["took_part"] is False, it["took_part"])
    ck("发起人如实写成「你自己决定要调这个工具」（别把塞给它说成它自己做的）",
       "你自己决定" in it["who_asked"], it["who_asked"])
    ck("原始参数也在（可复核）", "成都" in it["raw"], it["raw"])


def group_f():
    print("\n[F] 数字校验（模型说错时载体兜底）")
    import xiaojiao_app as app
    ck("说得对 → 认", app._has_number("那个数是 10000000000 呢", "10000000000") is True, "")
    ck("**加了千分位也认**", app._has_number("10,000,000,000", "10000000000") is True, "")
    ck("**说错了 → 不认**（这才轮得到兜底）", app._has_number("等于 1000000", "10000000000") is False, "")
    ck("没提这个数 → 不认", app._has_number("我算不出来", "10000000000") is False, "")
    ck("小数也对得上", app._has_number("概率是 0.3", "0.3") is True, "")


def _restore():
    RW._PATH = _REAL_PATH
    RW._STATE["_loaded"] = False
    RW._STATE["items"] = []
    try:
        os.remove(os.path.join(_TMP, "material.jsonl"))
    except Exception:      # noqa: silent-ok
        pass


if __name__ == "__main__":
    print("=" * 78)
    print("  原料自测 · 给原料，不给成品")
    print("=" * 78)
    try:
        group_a()
        group_b()
        group_c()
        group_d()
        group_e()
        group_f()
    finally:
        _restore()
    print("\n" + "=" * 78)
    print("  通过 %d / 共 %d" % (_COUNT["pass"], _COUNT["total"]))
    if _FAILED:
        print("  ❌ 未通过：%s" % "、".join(_FAILED))
    print("=" * 78)
    sys.exit(0 if not _FAILED else 1)
