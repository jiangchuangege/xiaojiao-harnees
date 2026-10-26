# -*- coding: utf-8 -*-
"""本轮工具门 · 自测（确定性；不需要模型、不需要网络）

验的是"看不见的工具是不是**真的调不到**"——这正是项目在渠道隔离那里写过的道理：
只过滤工具表 = 假隔离，必须执行时再拦一次。

四条放行规则逐条钉住：
  ① 没有本轮上下文（后台/内部流水线）→ 放行；
  ② 本轮装载了 → 放行；
  ③ 用户这一轮亲口点名 → 放行（点名即装）；
  ④ 其余 → 拒绝，并且回的是**中文说明 + 本轮可用清单**；
另外：过期（超过 TTL）→ 放行（那已经不是"这一轮"了）；`force=True` 的调用一律不经过这道门。
"""
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


def main():
    print("=" * 80)
    print("  本轮工具门自测（执行时再拦一次）")
    print("=" * 80)
    from core import tool_gate as TG      # noqa: E402

    # ---------------- 一、没有上下文就放行 ----------------
    print("\n[一] 没有本轮上下文时不拦（后台任务、内部流水线）")
    TG.clear()
    ck("没记账 → 放行", TG.check("web_search") == (True, ""))
    ck("current() 如实说没有装载", TG.current()["count"] == 0 and not TG.current()["fresh"],
       TG.current())

    # ---------------- 二、装载了就放行、没装载就拒绝 ----------------
    print("\n[二] 这一轮装了哪些，决定能不能调")
    TG.set_turn(["get_weather", "read_file"], "帮我查下济南现在的天气")
    ck("装载了的工具 → 放行", TG.check("get_weather")[0] is True)
    ok, note = TG.check("web_search")
    ck("没装载的通用工具 → 拒绝", ok is False, ok)
    ck("拒绝时说清楚「这一轮没有装载」", "没有装载" in note, note[:40])
    ck("拒绝时列出本轮可用工具", "get_weather" in note, note[:80])
    ck("拒绝时告诉用户怎么才能用上它", "用 web_search" in note, note[-40:])
    ck("拒绝时**不说**已执行/已完成", "已执行" not in note and "已完成" not in note)

    # ---------------- 三、用户点名要用的放行 ----------------
    print("\n[三] 用户亲口点名 → 放行（点名即装，下一轮真会装）")
    TG.set_turn(["get_weather"], "帮我用 web_search 搜一下济南天气新闻")
    ck("用户话里点了名 → 放行", TG.check("web_search")[0] is True)
    TG.set_turn(["get_weather"], "帮我查下济南现在的天气")
    ck("没点名 → 仍然拒绝", TG.check("web_search")[0] is False)

    # ---------------- 四、过期即放行 ----------------
    print("\n[四] 过了有效期就当没有上下文（不拿上一轮管这一轮）")
    TG.set_turn(["get_weather"], "查天气")
    _state = TG._state
    old = _state["at"]
    _state["at"] = time.time() - (TG._TTL + 10)
    ck("超过 TTL → 放行", TG.check("web_search")[0] is True)
    _state["at"] = old

    # ---------------- 五、坏输入不抛异常 ----------------
    print("\n[五] 门自己不许崩")
    for bad in (None, "", 123, [], {"a": 1}):
        try:
            ok, _ = TG.check(bad)
            ck("check(%r) 不抛异常（返回 %s）" % (str(bad)[:10], ok), isinstance(ok, bool))
        except Exception as e:
            ck("check(%r) 不该抛异常" % str(bad)[:10], False, "%s: %s" % (type(e).__name__, e))

    # ---------------- 六、接进真入口了吗 ----------------
    print("\n[六] 真实入口：run_tool 会拒绝「这一轮没装载」的工具")
    import xiaojiao_app as app        # noqa: E402
    TG.set_turn(["get_weather", "read_file"], "帮我查下济南现在的天气")
    out = app.run_tool("web_search", {"query": "济南天气"})
    ck("run_tool('web_search') 被拒（返回中文说明而不是搜索结果）",
       isinstance(out, str) and "没有装载" in out, str(out)[:60])
    ck("被拒时没有真的去联网（返回里没有搜索结果特征）",
       "http" not in str(out).lower(), str(out)[:60])
    out2 = app.run_tool("web_search", {"query": "济南天气"}, force=True)
    ck("force=True 的调用不经过这道门（载体自己发起的照旧执行）",
       not (isinstance(out2, str) and "没有装载" in out2), str(out2)[:50])
    TG.clear()
    out3 = app.run_tool("web_search", {"query": "济南天气"})
    ck("清掉上下文后放行（后台/其它入口不受影响）",
       not (isinstance(out3, str) and "没有装载" in out3), str(out3)[:50])

    print("\n" + "=" * 80)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("=" * 80)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
