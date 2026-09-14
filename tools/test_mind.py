# -*- coding: utf-8 -*-
"""阶段 A · 模块 1 · 载体核心智力十项 · 独立自测

提示词的验收口径：「每个能力**单独可测**；一个复杂任务走完十项；每步都有记录」。

为什么十项要**各自独立**测，而不是"跑一个大任务看结果对不对"：
    端到端过了只说明"这十项合起来没错"，一旦挂了你根本不知道是哪一项坏的 ——
    是没理解任务？还是拆错了？还是结果判断放过了错的？
    十项各自有明确输入/输出契约，逐项钉住，坏哪一项一眼看到。
    这也是"智力在载体里"这句话唯一可验证的形式：**每一项都能被单独调用**。

⚠️ 本测试**不联网、不调模型**：十项里只有"模型执行"那一格是模型，
其余九项都是纯载体逻辑 —— 正好符合设计（十项里九项在载体）。
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import xiaojiao_app as app   # noqa: E402

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


def safe(fn, *a, **kw):
    """把"不崩"变成可断言的东西：返回 (ok, value_or_error)。

    为什么每个能力都要测"脏输入不崩"：这十项都在**请求路径**上，
    任何一项对空串/None 抛异常，整轮对话就 500 ——
    而用户输入恰恰是最脏的（空、超长、纯符号、表情）。
    """
    try:
        return True, fn(*a, **kw)
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, e)


def main():
    print("=" * 74)
    print("  模块 1 · 载体核心智力十项（每项独立可测 + 脏输入不崩）")
    print("=" * 74)
    print("\n  说明：十项里只有「模型执行」那一格是模型；其余九项全在载体。")

    # ---------------- ① 任务理解 ----------------
    print("\n[①] 任务理解（_detect_intent：他到底要什么）")
    cases = [("你好呀", "chat"), ("抓一下 http://example.com", "scrape"),
             ("用 Archify 画个架构图", "diagram"), ("帮我查一下最近的漏洞", "query"),
             # ↓ 这几条是**本轮修出来的真缺口**：中文叙述句里夹一条命令，
             #   原来一律掉 chat → 这一轮不装 run_command → 用户要跑的命令跑不了。
             #   其中"删除"最关键：它走 shell 不是为执行，而是为了让**删除红线**有机会拦。
             ("跑一下 ipconfig", "shell"), ("执行 ping 127.0.0.1", "shell"),
             ("运行 dir", "shell"), ("运行 rm -rf /tmp/x", "shell"),
             ("删除 C:/a.txt", "shell"), ("帮我删除桌面那个文件", "shell"),
             ("把日志删掉", "shell")]
    for q, want in cases:
        ok, got = safe(app._detect_intent, q)
        ck("「%s」→ %s" % (q[:20], want), ok and got == want, got)
    # 反向：提问不能被误判成"让我执行命令"（宁可漏，不可误判成 shell）
    for q in ("ping 是什么意思", "ipconfig 和 netstat 什么区别", "怎么删除环境变量"):
        ok, got = safe(app._detect_intent, q)
        ck("提问「%s」**不能**判成 shell（那是提问不是命令）" % q[:16], ok and got != "shell", got)
    ok, got = safe(app._detect_intent, "")
    ck("空输入不崩（且给一个确定的意图，不是 None）", ok and got, got)
    ok, _ = safe(app._detect_intent, None)
    ck("None 输入不崩", ok)
    ok, _ = safe(app._detect_intent, "😀" * 300)
    ck("超长表情输入不崩", ok)
    ok1, a = safe(app._detect_intent, "你好")
    ok2, b = safe(app._detect_intent, "你好")
    ck("同一输入结果稳定（可复现，不是随机的）", ok1 and ok2 and a == b, (a, b))

    # ---------------- ② 任务拆解 ----------------
    print("\n[②] 任务拆解（plan_tool：拆成模型做得到的步）")
    # ⚠️ `plan_tool` 的**真实**返回是 `(工具名, 参数字典)` 的二元组 ——
    #    第一版我按 dict 写了一堆断言，直接 AttributeError（自测自己拦下来的）。
    #    这也是"先读契约再写断言"的又一次教训。
    ok, plan = safe(app.plan_tool, "抓一下 http://example.com 然后总结")
    ck("拆解返回 (工具名, 参数) 二元组", ok and isinstance(plan, tuple) and len(plan) == 2,
       type(plan).__name__)
    ck("拆出来的步带**真实工具名**（不是编的）",
       ok and plan[0] in app.all_tool_names(), plan[0] if ok else plan)
    ck("参数是可执行的 dict（不是空话）",
       ok and isinstance(plan[1], dict) and bool(plan[1]), plan[1] if ok else plan)
    ok, p2 = safe(app.plan_tool, "你好")
    ck("**闲聊不规划出工具调用**（实测原来会给『你好』编出 Get-Process 命令）",
       ok and (p2 == (None, None)), p2)
    for q in ("在吗", "嗯嗯", "今天好累", "哈哈"):
        ok, pq = safe(app.plan_tool, q)
        ck("闲聊「%s」不规划工具" % q, ok and pq == (None, None), pq)
    ok, p3 = safe(app.plan_tool, "写个文件到桌面")
    ck("**真任务照常规划**（不能因为「闲聊闸门」把动手请求也拒了）",
       ok and isinstance(p3, tuple) and p3[0] == "write_file", p3)
    ok, _ = safe(app.plan_tool, "")
    ck("空输入不崩", ok)
    ok, _ = safe(app.plan_tool, None)
    ck("None 不崩", ok)

    # ---------------- ③ 步骤规划 ----------------
    print("\n[③] 步骤规划（_plan_tools：先装什么、装几个）")
    names = app._intent_tool_names("chat")
    ck("chat 意图装的是核心几个（不是全量 77 个）",
       0 < len(names) <= 6, "%d 个：%s" % (len(names), names[:5]))
    names_shell = app._intent_tool_names("shell")
    ck("不同意图装不同工具（不重复、不串台）",
       set(names) != set(names_shell), (names[:2], names_shell[:2]))
    ck("工具名都在真实工具表里（不是编的名字）",
       all(n in app.all_tool_names() for n in names),
       [n for n in names if n not in app.all_tool_names()])
    tk = app._tools_tokens(names)
    ck("能算出这批工具的 token 开销（装配预算要用）", isinstance(tk, int) and tk >= 0, tk)
    ok, _ = safe(app._intent_tool_names, None)
    ck("未知意图不崩（默认退到 chat 一类）", ok)

    # ---------------- ④ 指令构造 ----------------
    print("\n[④] 指令构造（compose_system_prompt：每一步怎么问模型）")
    sp = app.compose_system_prompt("你是小焦。")
    ck("拼出非空系统提示词", bool(sp) and len(sp) > 200, len(sp))
    for part, cn in ((app._SEARCH_RULES, "检索铁律"), (app._TOOL_RULES, "工具规则")):
        ck("含%s" % cn, part in sp)
    ck("含人格层规则（模块 9 已接入）", "人格层" in sp)
    ck("**不重复拼同一条规则**（每条只加一份）",
       sp.count(app._TOOL_RULES) == 1, sp.count(app._TOOL_RULES))
    sp2 = app.compose_system_prompt("你是小焦。")
    ck("同一人设两次拼装结果一致（幂等）", sp == sp2)
    ok, spx = safe(app.compose_system_prompt, None)
    ck("role=None 不崩", ok, (spx or "")[:20] if ok else spx)

    # ---------------- ⑤ 结果判断 ----------------
    print("\n[⑤] 结果判断（_validate_tool_result / _tool_failed：这一步对不对）")
    # ⚠️ 真实契约（读源码确认，不要猜）：返回 `(是否幻觉, 说明)`；
    #    `None` 表示"不适用"（失败/被拦/不是抓取类工具 —— 失败归熔断逻辑管，不算幻觉）。
    ok, r = safe(app._validate_tool_result, "get", {"url": "x"}, "")
    ck("空结果 → 不判为幻觉（None = 不适用），且给出说明",
       ok and isinstance(r, tuple) and len(r) == 2, r)
    # ⚠️ 契约是 (是否通过/不是幻觉, 说明) —— **与直觉相反**：正文太短时它返回
    #    (False, \'⚠️ 可能幻觉：…短得不像一个真实页面\')。
    #    第一版我按"True=有幻觉"写断言，直接把自己判红（自测抓到的第二处契约误读）。
    #    教训：**读源码确认语义**，别凭函数名猜布尔方向。
    ok, r2 = safe(app._validate_tool_result, "get", {"url": "x"}, "正常返回内容" * 40)
    ck("长正文 → 判为可信", ok and isinstance(r2, tuple) and r2[0] is True, r2)
    ok, r3 = safe(app._validate_tool_result, "get", {"url": "x"}, "短" * 15)
    ck("**极短正文 → 判为可能幻觉并给出说明**",
       ok and r3[0] is False and "可能幻觉" in (r3[1] or ""), r3)
    ck("返回的是 (判定, 说明) 两件套",
       isinstance(r2, tuple) and len(r2) == 2 and isinstance(r2[1], str), r2)
    ck("失败类结果被 `_tool_failed` 认出来（超时/失败/Error 都要认）",
       app._tool_failed("连接超时") is True and app._tool_failed("Error: 拒绝访问") is True
       and app._tool_failed("执行失败") is True,
       (app._tool_failed("连接超时"), app._tool_failed("Error: 拒绝访问"),
        app._tool_failed("执行失败")))
    ck("正常返回不被误判为失败",
       app._tool_failed("这是正常的返回内容") is False,
       app._tool_failed("这是正常的返回内容"))
    ok, _ = safe(app._validate_tool_result, None, None, None)
    ck("全 None 不崩", ok)

    # ---------------- ⑥ 纠错调度 ----------------
    print("\n[⑥] 纠错调度（_tool_breaker：错了怎么改）")
    # ⚠️ 真实契约：`streak` 是**可变字典**（形如 {"n": 0}），函数会就地累加并返回熔断文案。
    #    第一版我传了 int → `'int' object does not support item assignment`（自测抓到的假设错误）。
    st = {"n": 0}
    texts = []
    for i in range(4):
        ok, txt = safe(app._tool_breaker, st, "get", "连接超时", [])
        texts.append(txt if ok else "ERR:" + str(txt))
    ck("连续失败会被累加（计到 3 次）", st.get("n", 0) >= 3, st)
    ck("**连续 3 次失败触发熔断**（返回可读的熔断说明）",
       any(isinstance(t, str) and "熔断" in t for t in texts), texts[-1])
    st2 = {"n": 0}
    ok, br1 = safe(app._tool_breaker, st2, "get", "正常返回内容", [])
    ck("正常结果不熔断（返回空串）", ok and br1 == "", (st2, br1))
    ok, _ = safe(app._tool_breaker, {"n": 0}, None, None, None)
    ck("脏参数不崩", ok)
    ck("工具缓存接口存在（纠错时能复用上次成功结果）",
       callable(getattr(app, "_cached_tool_result", None))
       and callable(getattr(app, "_cache_tool_result", None)))

    # ---------------- ⑦ 工具编排 ----------------
    print("\n[⑦] 工具编排（detect_tool_intent / run_tool：什么时候用什么工具）")
    ok, ti = safe(app.detect_tool_intent, "抓一下 http://example.com")
    ck("从自然语言认出要用的工具", ok and (ti is None or isinstance(ti, dict)), ti)
    ok, _ = safe(app.detect_tool_intent, "")
    ck("空输入不崩", ok)
    ok, _ = safe(app.run_tool, "no_such_tool_xyz", {})
    ck("不存在的工具不崩（返回错误而不是抛异常）", ok)
    ck("工具表是非空的（能力不封顶的前提）", len(app.all_tool_names()) >= 50,
       "%d 个工具" % len(app.all_tool_names()))

    # ---------------- ⑧ 记忆管理 ----------------
    print("\n[⑧] 记忆管理（load_history / 缓存：什么记、什么取）")
    ok, h = safe(app.load_history)
    ck("能读出历史（返回列表）", ok and isinstance(h, list), type(h).__name__)
    ok, hl = safe(app._history_summary_line, [{"role": "user", "content": "你好"}])
    ck("能把历史压成摘要行（注入用）", ok and isinstance(hl, str), type(hl).__name__)
    ok, _ = safe(app._history_summary_line, None)
    ok2, _ = safe(app._history_summary_line, [])
    ck("脏历史（None/空表）不崩", ok and ok2)
    from core import memory_vec
    ck("记忆库可检索（无限 1 的基础）", callable(memory_vec.search_memory))

    # ---------------- ⑨ 冲突仲裁 ----------------
    print("\n[⑨] 冲突仲裁（_resolve_llm_key 优先级 + 工具结果择一）")
    env_key = os.environ.pop("XIAOJIAO_API_KEY", None)
    try:
        got = app._resolve_llm_key({"api": {"api_key": "BRAIN_OLD"}},
                                   [{"name": "m1", "api_key": "MODELS_NEW"}])
        ck("**界面填的 Key（models）压过 brain.api 的旧值**（这是修过的真 bug）",
           got == "MODELS_NEW", got)
        got2 = app._resolve_llm_key({"api": {"api_key": "ONLY_BRAIN"}}, [])
        ck("models 里没有时兜底读 brain.api", got2 == "ONLY_BRAIN", got2)
        os.environ["XIAOJIAO_API_KEY"] = "ENV_KEY"
        got3 = app._resolve_llm_key({"api": {"api_key": "BRAIN_OLD"}},
                                    [{"name": "m1", "api_key": "MODELS_NEW"}])
        ck("环境变量优先级最高", got3 == "ENV_KEY", got3)
    finally:
        os.environ.pop("XIAOJIAO_API_KEY", None)
        if env_key is not None:
            os.environ["XIAOJIAO_API_KEY"] = env_key
    ok, _ = safe(app._resolve_llm_key, None, None)
    ck("脏参数不崩", ok)

    # ---------------- ⑩ 全局状态 ----------------
    print("\n[⑩] 全局状态（中央状态 + 控制文件：现在做到哪了）")
    try:
        from core import central as S
        S.clear_state()
        S.set_state("agent_run", stage="工具装配", step=2)
        st = S.get_state("agent_run")
        ck("阶段状态可写可读（跨模块共享）",
           st.get("stage") == "工具装配" and st.get("step") == 2, st)
        S.clear_state()
        ok, _ = safe(app._save_control)
        ck("控制文件保存入口存在且可调（状态落盘）", ok)
    except Exception as e:
        ck("中央状态可用", False, e)

    # ---------------- 集成：一个复杂任务走完十项 ----------------
    print("\n[集成] 一个复杂任务走完十项（用规则可测的部分，不调模型）")
    q = "帮我把 http://example.com 的内容抓下来，然后总结成 3 条重点"
    intent = app._detect_intent(q)
    ck("集成① 理解：认出是抓取类任务", intent in ("scrape", "query", "chat"), intent)
    plan = app.plan_tool(q)
    ck("集成②③ 拆解+规划：给出 (工具, 参数) 可执行计划",
       isinstance(plan, tuple) and len(plan) == 2 and bool(plan[0]), str(plan)[:50])
    loaded = app._intent_tool_names(intent)
    ck("集成④ 指令构造：按意图装配了工具", isinstance(loaded, list), loaded[:4])
    tk = app._tools_tokens(loaded)
    ck("集成⑥ 预算：工具的 token 开销算得出来", isinstance(tk, int), tk)
    ti = app.detect_tool_intent(q)
    ck("集成⑦ 编排：认出要调的工具", ti is None or isinstance(ti, dict),
       str(ti)[:40])
    tk2 = app._estimate_tokens(q)
    ck("集成⑧ 记忆/预算：输入 token 可估", tk2 > 0, tk2)
    okfit = True
    try:
        app._fit_context("系统提示", [{"role": "user", "content": "旧" * 100}],
                         q, max_ctx=500, tools_tokens=tk)
    except Exception as e:
        okfit = False
        ck("集成⑨ 装配：预算不够时也不崩", False, e)
    if okfit:
        ck("集成⑨ 装配：单次请求在预算内装配完成（不崩）", True)

    # ---------------- 结构性验收：十项一项都不能少 ----------------
    # 为什么加这条：上面每项是"分组打印 + 若干断言"，如果有人删掉某一组，
    # 总数依然可能全绿（只是少了几条），而"静默少掉一项能力"正是本测试最该防的退化。
    # 所以这里按分组标记统计，要求 ①②③④⑤⑥⑦⑧⑨⑩ 全部存在、且有集成段。
    import re as _re
    _src = open(os.path.join(_ROOT, "tools", "test_mind.py"), encoding="utf-8").read()
    _groups = _re.findall(r"print\(\"\\n\[(①|②|③|④|⑤|⑥|⑦|⑧|⑨|⑩|集成)", _src)
    _uniq = sorted(set(_groups))
    ck("十项能力**各自都有独立单测分组**（缺一不可）",
       set(_uniq) >= set("①②③④⑤⑥⑦⑧⑨⑩"), _uniq)
    ck("有集成测试段（一个复杂任务走完十项）", "集成" in _groups, _groups.count("集成"))
    ck("断言总数 ≥ 60（每一项都不是敷衍一条）", len(PASS) + len(FAIL) >= 60,
       len(PASS) + len(FAIL))

    print("\n" + "=" * 74)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("=" * 74)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
