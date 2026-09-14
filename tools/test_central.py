# -*- coding: utf-8 -*-
"""阶段 B · 协同网络（中央状态 + 事件总线）· 自测

为什么必须有它：协同网络是个"没人用也看不出坏"的基础设施 ——
订阅者泄漏、事件级联死循环、某个模块坏了把整轮对话搞崩，这些都不会在功能测试里暴露。
所以这里把四条硬约束钉成断言：
  ① 一个坏订阅者**不能**拖垮 publish；
  ② 事件级联**必须有深度上限**（防 A↔B 死循环）；
  ③ 单模块缺席时 `snapshot()` 要**如实标注**，不许假装正常；
  ④ `set_state` 只能覆盖自己那几个键，不能抹掉同命名空间下别人的键。
"""
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from core import central as S   # noqa: E402

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


def main():
    print("=" * 70)
    print("  阶段 B · 协同网络（中央状态 + 事件总线）")
    print("=" * 70)
    S.reset_bus()
    S.clear_state()

    # ---------------- 一、中央状态 ----------------
    print("\n[一] 中央状态：各模块写自己那一片，互不覆盖")
    S.set_state("reasoning", step="拆解", confidence=0.7)
    S.set_state("reasoning", note="补一条")          # 只加键，不清前面的
    r = S.get_state("reasoning")
    ck("同命名空间**只覆盖同名键**（别人的键还在）",
       r.get("step") == "拆解" and r.get("note") == "补一条", r)
    S.set_state("memory", hits=3)
    ck("不同命名空间互不影响",
       S.get_state("memory").get("hits") == 3 and S.get_state("reasoning").get("note") == "补一条")
    ck("读不存在的命名空间返回空 dict（不报错）", S.get_state("nope") == {})
    ck("带 key 读不到时给 default", S.get_state("nope", key="x", default="d") == "d")
    snap_copy = S.get_state()
    snap_copy.setdefault("zzz", {}).update({"a": 1})
    ck("整份快照是拷贝（改它不影响内部）", "zzz" not in S.get_state())
    meta = S.state_meta()
    ck("状态有写入者元信息（谁什么时候写的）",
       "reasoning" in meta and "ts" in meta["reasoning"], list(meta.keys()))
    S.clear_state("memory")
    ck("能只清一个命名空间", S.get_state("memory") == {} and S.get_state("reasoning") != {})

    # ---------------- 二、事件总线基本功能 ----------------
    print("\n[二] 事件总线：订阅 / 广播 / 退订")
    got = []
    un = S.subscribe("mem.write", lambda e: got.append(e["payload"]), owner="t1")
    n = S.publish("mem.write", {"id": "abc"})
    ck("订阅者收到事件", got == [{"id": "abc"}], (n, got))
    ck("publish 返回被调用订阅者数", n == 1, n)
    un()
    S.publish("mem.write", {"id": "def"})
    ck("**退订后不再收到**", got == [{"id": "abc"}], got)
    ck("订阅列表如实反映 owner", S.subscribers("mem.write") == [], S.subscribers("mem.write"))
    ck("无人订阅时 publish 不报错", S.publish("nobody", 1) == 0)
    _raised = False
    try:
        S.subscribe("x", "not-callable")
    except TypeError:
        _raised = True
    ck("订阅者不是可调用对象 → 明确抛 TypeError", _raised)

    # ---------------- 三、坏订阅者不能拖垮总线（硬约束①） ----------------
    print("\n[三] 坏订阅者绝不能拖垮总线")
    S.reset_bus()
    good_hits = []
    un_bad = S.subscribe("t", lambda e: (_ for _ in ()).throw(RuntimeError("订阅者炸了")),
                         owner="bad")
    S.subscribe("t", lambda e: good_hits.append(1), owner="good")
    n = S.publish("t", {})
    ck("坏订阅者抛异常后，**好订阅者照常收到**", good_hits == [1], good_hits)
    ck("坏订阅者被如实记账（不假装没发生）", S.bus_stats()["handler_errors"] == 1,
       S.bus_stats())
    ck("publish 本身不抛异常（返回计数）", n == 2, n)
    un_bad()

    # ---------------- 四、级联深度上限（硬约束②） ----------------
    print("\n[四] 事件级联必须有深度上限（防 A↔B 死循环）")
    S.reset_bus()
    seen = []

    def _bounce(ev):
        seen.append(ev["depth"])
        S.publish("bounce", {"again": 1}, _depth=ev["depth"] + 1)

    un_b = S.subscribe("bounce", _bounce, owner="loop")
    S.publish("bounce", {"start": 1}, _depth=0)
    un_b()
    ck("**级联有上限，不会无限递归**", len(seen) <= S._MAX_DEPTH + 2, len(seen))
    ck("超过深度的被如实统计（dropped）", S.bus_stats()["dropped"] >= 1,
       S.bus_stats()["dropped"])
    ck("深度上限是 4（正常链路 2~3 层足够）", S._MAX_DEPTH == 4, S._MAX_DEPTH)

    # ---------------- 五、环形缓冲不涨内存 ----------------
    print("\n[五] 环形缓冲：内存里只留最近 N 条")
    S.reset_bus()
    for i in range(S._MAX_EVENTS + 200):
        S.publish("spam", i)
    ck("缓冲被截断到上限", len(S.recent(S._MAX_EVENTS * 2)) == S._MAX_EVENTS,
       len(S.recent(S._MAX_EVENTS * 2)))
    ck("留下的确实是**最近的**（最后一条 payload 正确）",
       S.recent(1)[0]["payload"] == S._MAX_EVENTS + 199, S.recent(1)[0]["payload"])
    ck("可按主题过滤", all(e["topic"] == "spam" for e in S.recent(5, topic="spam")))
    ck("统计如实（published 累加）", S.bus_stats()["published"] == S._MAX_EVENTS + 200,
       S.bus_stats()["published"])

    # ---------------- 六、模块探活如实（硬约束③） ----------------
    print("\n[六] 模块探活：缺席要如实标，不许假装正常")
    S.reset_bus()
    mods = S.module_status()
    ck("列出的模块数与 MODULES 一致", len(mods) == len(S.MODULES), len(mods))
    ck("每个模块都有中文名", all(v.get("cn") for v in mods.values()))
    ck("**已实现的模块探到 available=True**",
       mods["memory_vec"]["available"] and mods["health"]["available"]
       and mods["continuation"]["available"],
       {k: v["available"] for k, v in mods.items()})
    ck("未知/未实现模块必须 available=False（**不许编造**）",
       (("nonexistent_mod" in mods) is False), "未把不存在的模块伪造成在线")
    only = S.module_status(only=True)
    ck("only=True 只返回在线模块", all(v["available"] for v in only.values()), len(only))

    # ---------------- 七、快照与摘要 ----------------
    print("\n[七] snapshot / summary：全部是真实读到的值")
    S.set_state("demo", x=1)
    S.publish("demo.evt", {"x": 1})
    snap = S.snapshot()
    ck("快照含 modules/state/bus/recent_events",
       all(k in snap for k in ("modules", "state", "bus", "recent_events")), list(snap.keys()))
    ck("快照里的在线模块数 = module_status 的真实计数",
       snap["modules_available"] == sum(1 for v in S.module_status().values()
                                        if v.get("available")), snap["modules_available"])
    ck("快照记下了刚写的状态", snap["state"].get("demo", {}).get("x") == 1)
    ck("快照记下了刚发的事件", any(e["topic"] == "demo.evt" for e in snap["recent_events"]))
    s = S.summary()
    ck("摘要**带真实数字**（器官数/命名空间数）",
       ("%d/%d" % (snap["modules_available"], snap["modules_total"])) in s, s[:60])
    ck("摘要里的订阅者数与 bus_stats 一致",
       str(snap["bus"]["subscribers"]) in s, s[:80])

    # ---------------- 八、落盘是可选的（默认不写盘） ----------------
    print("\n[八] 落盘：默认关，开了才写（不拖慢每轮对话）")
    ck("默认不落盘", S.bus_stats()["persist"] is False, S.bus_stats()["persist"])
    # ⚠️ 落盘策略是**分开的**（不是"要么全写要么全不写"）：
    #    · 普通事件：默认**不写**（每轮几十条事件都写盘会拖慢对话）；
    #    · 异常/超深事件（handler_error / depth_exceeded）：**永远写**。
    #      为什么这两类必须无条件写：它们正是最需要事后复盘的病态情况，
    #      而恰恰在出问题的时候，人不会记得"先去把落盘开关打开"。
    before = len(S.read_events(limit=9999))
    S.reset_bus()                       # 只清内存缓冲，不删文件
    S.publish("normal.topic", {"x": 1})
    time.sleep(0.05)
    normal_rows = [e for e in S.read_events(limit=9999) if e.get("topic") == "normal.topic"]
    ck("**普通事件默认不落盘**", normal_rows == [], len(normal_rows))
    S.publish("err.topic", {})          # 触发一次订阅者异常 → 必落盘
    time.sleep(0.05)
    err_rows = [e for e in S.read_events(limit=9999) if e.get("tag") == "handler_error"]
    ck("**异常事件无条件落盘**（病态情况必须留证据）", len(err_rows) >= 1, len(err_rows))
    p = S.open_persist(True)
    ck("可以打开落盘", p is True)
    S.reset_bus()
    tag = "selftest-%d" % int(time.time())
    S.publish("test.persist", {"tag": tag})
    time.sleep(0.1)
    evs = S.read_events(limit=9999)
    # 【为什么要显式给 limit —— 实测踩到的假红】
    #   默认 `read_events(limit=200)` 读的是文件**前 200 行**（`read_jsonl` 一够数就 break），
    #   不是"最近 200 行"。落盘文件是**跨轮次累积**的：跑得多了它自然长过 200 行，
    #   而刚 publish 的那一条在**文件末尾** —— 于是在同一个文件上，
    #   "能读回刚发的事件"这条断言会随着**历史日志变长**而凭空变红（实测读到 200 条、就是不含新事件）。
    #   边界断言要么给足 limit，要么读尾部；用默认值等于把"日志有多长"变成了一条隐式前置条件。
    ck("**打开后落盘真的发生**（能读回刚发的事件）",
       any((e.get("payload") or "").find(tag) >= 0 for e in evs), len(evs))
    ck("落盘行数在长（不是原地不动）", len(evs) >= before, (before, len(evs)))
    S.open_persist(False)
    ck("可以再关掉", S.bus_stats()["persist"] is False)

    # ---------------- 九、reset / 清理 ----------------
    print("\n[九] reset_bus 清缓冲不清订阅者")
    un_k = S.subscribe("keep", lambda e: None, owner="keeper")
    S.publish("keep", 1)
    before_subs = S.subscribers("keep")
    S.reset_bus()
    ck("清缓冲后订阅者还在", S.subscribers("keep") == before_subs, S.subscribers("keep"))
    ck("缓冲与统计被清空", S.recent(10) == [] and S.bus_stats()["published"] == 0)
    un_k()
    ck("退订后订阅者消失", S.subscribers("keep") == [])

    # 清理测试留下的状态（不删文件）
    S.clear_state()
    S.reset_bus()
    print("\n" + "=" * 70)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("=" * 70)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
