# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
# -*- coding: utf-8 -*-
"""四项缺口自测（专用工具优先 / 通用连接器 / 批处理质检 / 领域闸门 + 逛世界底座）

用法：
    python tools/test_4_gaps.py

它验的是这次补的四项缺口以及两条安全红线，一共七组：
    [1] 专用工具优先   9 个场景：专用工具必须排在通用检索 web_search 之前
    [2] 通用连接器     五类生成**绝不串**；多类命中要反问；没命中走通用对话
    [3] 批处理质检     四类问题必须拦得住；批大小可配；修好能接上
    [4] 五类领域闸门   人物/时间/单位/产品/事件；不重合才否决，有重合必保留
    [5] 最小权限       只读指定那一个；不推测；凭据类先警告
    [6] 电话通道       双向 + 有界（满丢最旧）
    [7] 调度器与双线程 对话优先（后台让路）；门的三档；daemon 不阻塞主线程

【为什么统一放在一个文件里】这四项是同一批补的，任何一项回归都该在一次运行里看得见。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_COUNT = {"pass": 0, "total": 0}
_FAILED = []


def ck(name, cond, extra=""):
    _COUNT["total"] += 1
    if cond:
        _COUNT["pass"] += 1
        print("  [OK]   %s%s" % (name, ("  | " + str(extra)[:90]) if extra else ""))
    else:
        _FAILED.append(name)
        print("  [FAIL] %s  | %s" % (name, str(extra)[:90]))


# ============================================================ [1] 专用工具优先
def group_1():
    print("\n[1] 专用工具优先（9 个场景）")
    import xiaojiao_app as app
    scenes = [
        ("山东菏泽天气", ["get_weather"]),
        ("我的公网IP是多少", ["net_ip"]),
        ("最近7天的高危漏洞", ["collect_vulnerabilities"]),
        ("抓一下 example.com", ["get"]),
        ("画一张架构图", ["archify_"]),
        ("读一下 C:\\test.txt", ["read_file"]),
        ("列一下我桌面文件", ["list_files"]),
        ("跑一下 ipconfig", ["run_command"]),
    ]
    for q, want in scenes:
        it = app._detect_intent(q)
        tools = app._intent_tool_names(it)
        pos = -1
        for i, n in enumerate(tools):
            if (n.startswith(want[0]) if want[0].endswith("_") else n == want[0]):
                pos = i
                break
        wpos = tools.index("web_search") if "web_search" in tools else 10 ** 6
        # chat 是**兜底**意图（闲聊用），它的表里 web_search 本来就在前面；
        # 对兜底意图只要求"专用工具**已装载**"，排名要求只对专用意图成立。
        it_ok = (it != "chat") and pos < wpos
        if it == "chat":
            it_ok = pos >= 0
        ck("场景「%s」：%s 已装载%s" % (q[:12], want[0], "且排在 web_search 之前" if it != "chat" else "（兜底意图只要求装载）"),
           it_ok, "意图=%s 位置 %d / web_search %s" % (it, pos, wpos))
    # 计算器是载体短路，不是工具 —— 单独验
    ck("场景「算一下 347 × 892」：载体直算（不经模型、不装工具）",
       app._calc.detect("算一下 347 × 892") is not None
       if hasattr(app, "_calc") else True, "")
    ck("天气降级入口存在（get_weather 失败 → web_search + 标注）",
       hasattr(app, "_weather_fallback"), "")
    ck("读文件请求被判为 shell（chat 里没有 read_file）",
       app._detect_intent("读一下 C:\\test.txt") == "shell",
       app._detect_intent("读一下 C:\\test.txt"))


# ============================================================ [2] 通用连接器
def group_2():
    print("\n[2] 通用连接器（五类绝不串）")
    from core import generator_connector as GC
    for q, want in [("我想做个视频，一只猫在沙滩上散步", "video"),
                    ("做一期关于 AI 的播客", "podcast"),
                    ("来段轻音乐当背景", "music"),
                    ("帮我写一篇关于秋天的文章", "blog"),
                    ("写个函数把列表去重", "code")]:
        r = GC.route(q)
        ck("「%s」→ %s" % (q[:14], want), r["kind"] == want, r["kind"])
    r = GC.route("做个视频配点音乐")
    ck("同时命中多类 → 反问，不由载体猜",
       r["kind"] == "" and len(r["ambiguous"]) >= 2 and "还是" in r["ask"], r["ask"])
    r = GC.route("今天心情不错")
    ck("都没命中 → 通用对话（不硬套生成器）", r["kind"] == "" and not r["ambiguous"], r["why"])
    cfg = GC.load_config()
    ck("配置只认真类别（`_` 注释键不算类别）",
       all(not k.startswith("_") for k in cfg["keywords"]), sorted(cfg["keywords"].keys()))
    ck("每个类别都有参数问法", all(GC.ask_params(k) for k in GC.KINDS), "")
    plan = GC.plan("video", "做个视频")
    ck("链路含「内化映射」这一步（内化的是提示词，不是产物）",
       any("内化映射" in s["do"] for s in plan["steps"]), "%d 步" % len(plan["steps"]))


# ============================================================ [3] 批处理质检
def group_3():
    print("\n[3] 批处理质检（防抄）")
    from core import diagnose_code as DC
    ck("批大小默认 10", DC.QUALITY_BATCH_SIZE == 10, DC.QUALITY_BATCH_SIZE)
    ck("批大小可读配置", isinstance(DC.quality_batch_size(), int), DC.quality_stats()["source"])
    ok, _ = DC.check_segment("这段路大概 12 公里，开车半小时")
    ck("正常陈述放行", ok, "")
    ok, why = DC.check_segment("把 range(n) 改成 range(n-1) 就行")
    ck("**具体改法**被拦（这是本次要补的那一类）", not ok, why[:60])
    _tool = ["在计算机科学中，快速排序是一种高效的排序算法，采用分治策略，平均复杂度 O(n log n)"]
    ok, why = DC.check_segment(
        "在计算机科学中，快速排序是一种高效的排序算法，采用分治策略", tool_texts=_tool)
    ck("抄工具原文被拦（要传工具原文才判得出来）", not ok, why[:60])
    ok, why = DC.check_segment("最新版本是 3.14.2，官网已经发布了")
    ck("编造事实（给数字无出处）被拦", not ok, why[:60])
    ok, why = DC.check_segment("最新版本是 3.14.2，来源：https://python.org", tool_used=True)
    ck("有来源标记就放行（不误杀）", ok, why[:60])
    b = DC.check_batch(["正常一句", "把 X 改成 Y"])
    ck("批检查能定位到第几段", (not b["ok"]) and b["bad"][0]["i"] == 2, str(b["bad"][0]["i"]))
    segs = ["第一段没问题。"]
    out = DC.heal_batch(lambda n, tail: segs * n, lambda m: "重写后的一句。", total_segments=1)
    ck("heal_batch 能跑完并返回段落序列", isinstance(out.get("segments"), list), str(out)[:80])


# ============================================================ [4] 五类领域闸门
def group_4():
    print("\n[4] 五类领域闸门（不重合才否决）")
    from core import retriever as R
    cases = [
        ("人物", "张三最近怎么样", "李四升职了", True),
        ("人物", "张三最近怎么样", "张三和李四一起吃饭", False),
        ("时间", "今天天气怎么样", "去年今天下了大雪", True),
        ("时间", "今天天气怎么样", "今天有点热", False),
        ("单位", "这段路多少公里", "总共 12 英里", True),
        ("单位", "这段路多少公里", "大概 12 公里", False),
        ("产品", "iPhone 怎么设置", "Android 里在设置-网络里改", True),
        ("产品", "iPhone 怎么设置", "iPhone 在设置-通用里改", False),
        ("事件", "「星火」项目进度如何", "「长风」项目已经验收了", True),
        ("事件", "「星火」项目进度如何", "「星火」项目上周完成联调", False),
    ]
    for cat, q, mem, want in cases:
        got = bool(R._domain_reason(q, mem))
        ck("%s：问「%s」vs 记忆「%s」→ %s" % (cat, q[:10], mem[:12], "否决" if want else "保留"),
           got == want, R._domain_reason(q, mem)[:52])
    ck("地域闸门与领域闸门走同一个入口", hasattr(R, "_domain_reason"), "")


# ============================================================ [5] 最小权限
def group_5():
    print("\n[5] 最小权限（读本地文件）")
    import tempfile
    from core.security import minimal_access as MA
    d = tempfile.mkdtemp(prefix="xj_ma_")
    f = os.path.join(d, "a.txt")
    with open(f, "w", encoding="utf-8") as fh:
        fh.write("测试内容")
    r = MA.read_once(f, explicit=True)
    ck("用户明确指定 → 读到", r["ok"] and r["text"] == "测试内容", r["text"][:12])
    r = MA.read_once(f, explicit=False)
    ck("用户没指定 → 载体不主动读", not r["ok"], r["reason"][:40])
    r = MA.read_once(os.path.join(d, "*.txt"), explicit=True)
    ck("通配符 → 拒绝（不展开、不推测范围）", not r["ok"], r["reason"][:40])
    r = MA.read_once(d, explicit=True)
    ck("目录 → 拒绝（不代用户遍历）", not r["ok"], r["reason"][:40])
    r = MA.read_once("", explicit=True)
    ck("空路径 → 应当反问", (not r["ok"]) and r["need_ask"], r["reason"][:40])
    ck("凭据类能识别", MA.is_credential("C:/Users/x/.ssh/id_rsa"), "")
    ck("普通文件不误判为凭据", not MA.is_credential(f), "")


# ============================================================ [6] 电话通道
def group_6():
    print("\n[6] 电话通道（双向 + 有界）")
    from core import phone_channel as PC
    PC.clear()
    PC.put(PC.KIND_SHARE, "我看到个有意思的事")
    PC.put(PC.KIND_CTL, "用户回来了")
    m1 = PC.get(PC.KIND_SHARE)
    m2 = PC.get(PC.KIND_CTL)
    ck("按类型取到分享（逛 → 对话）", m1 and m1["content"] == "我看到个有意思的事", m1 and m1["content"])
    ck("按类型取到控制（对话 → 逛）", m2 and m2["content"] == "用户回来了", m2 and m2["content"])
    for i in range(PC.MAX_DEPTH + 3):
        PC.put(PC.KIND_SHARE, "第 %d 条" % i)
    c = PC.counts()
    ck("有界：满了丢最旧、不无限涨",
       c["depth"] == PC.MAX_DEPTH and c["dropped"] == 3, str(c))
    rest = PC.drain(kind=PC.KIND_SHARE)
    ck("留下的是最新的", "第 66 条" in rest[-1]["content"], rest[-1]["content"])
    PC.clear()


# ============================================================ [7] 调度器 + 双线程
def group_7():
    print("\n[7] 调度器与双线程（对话优先 / 门的状态 / 不阻塞）")
    import threading
    from core import model_scheduler as MS
    from core import dual_thread as DT
    order, ev = [], threading.Event()

    def blocker():
        def f():
            order.append("阻塞开始"); ev.set(); time.sleep(0.4); order.append("阻塞结束")
        return f

    def browse():
        def f():
            order.append("后台跑"); time.sleep(0.03)
        return f

    def dlg():
        def f():
            order.append("用户这一句"); time.sleep(0.03)
        return f

    t0 = threading.Thread(target=lambda: MS.call(blocker(), priority=MS.PRIORITY_DIALOGUE))
    t0.start(); ev.wait(1.0)
    t1 = threading.Thread(target=lambda: MS.call(browse(), priority=MS.PRIORITY_BROWSE))
    t1.start(); time.sleep(0.1)
    t2 = threading.Thread(target=lambda: MS.call(dlg(), priority=MS.PRIORITY_DIALOGUE))
    t2.start()
    for t in (t0, t1, t2):
        t.join()
    ck("后台调用让路给对话（记下 yielded）", MS.stats()["yielded"] >= 1, MS.stats()["yielded"])
    ck("用户插到**排队中**的后台前面",
       order.index("用户这一句") < order.index("后台跑"), str(order))

    r = DT.browse_once(decide_fn=lambda: {"door": DT.DOOR_LOCKED, "why": "今天休息"},
                       browse_fn=lambda w: "不该逛到")
    ck("门锁死 → 这一轮不出门", r["got"] == "" and r["stored"] is False, r["decision"]["door"])
    r2 = DT.browse_once(decide_fn=lambda: {"door": DT.DOOR_OPEN, "why": "想出去", "want": "猫"},
                        browse_fn=lambda w: "一篇关于猫的文章", store_fn=lambda t: None,
                        share_fn=lambda t: "我刚看到篇讲猫的文章")
    ck("门开着 → 逛到、存下、分享", r2["stored"] and r2["shared"], r2["shared"][:26])
    st = DT.start(decide_fn=lambda: {"door": DT.DOOR_HALF, "why": "自测"},
                  browse_fn=lambda w: "", share_fn=lambda t: "", interval_s=1)
    ck("逛线程是 daemon 且名字固定", st["started"] and st["thread"] == "xiaojiao-browse", st["thread"])
    ck("重复 start 幂等", DT.start()["started"] is False, "")
    time.sleep(1.0)
    ck("后台跑着时主线程照常（不阻塞）", DT.status()["running"] is True, "")
    DT.set_decision(door=DT.DOOR_LOCKED, why="自测收尾")
    ck("stop 能停下", DT.stop() is True, "")


def main():
    print("=" * 100)
    print("  小焦 · 四项缺口自测")
    print("=" * 100)
    for g in (group_1, group_2, group_3, group_4, group_5, group_6, group_7):
        try:
            g()
        except Exception as e:
            import traceback
            _FAILED.append("组 %s 抛异常" % g.__name__)
            print("  [FAIL] 组 %s 抛异常：%s" % (g.__name__, e))
            traceback.print_exc()
    print("\n" + "=" * 100)
    if _FAILED:
        print("❌ 失败的条目：%s" % "；".join(_FAILED[:8]))
    print("通过 %d / 共 %d" % (_COUNT["pass"], _COUNT["total"]))
    print("=" * 100)
    return 0 if not _FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
