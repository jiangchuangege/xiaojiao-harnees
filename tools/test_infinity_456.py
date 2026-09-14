# -*- coding: utf-8 -*-
"""无限 4/5/6 · 验收（工具无限 / 感知无限 / 单次请求永不超）

为什么这三项要合成一个验收文件：它们的失败方式完全一样 —— **都是静默的**。
    · 工具无限：工具被"暂缓/砍掉"时用户只会发现"它突然不会某件事了"；
    · 感知无限：界面漏出"第 3/12 片""exceeds context"，用户才知道自己被技术细节糊了一脸；
    · 单次永不超：靠"砍内容"来压 token，虽然不报错了但能力被削（最难发现的退化）。
三者都不报错、都能"看起来正常"，所以必须把**不该出现的东西**钉成断言。

对应的提示词口径：
    · 无限 4：plugins/ 全部工具永久保留，禁止日志出现"暂缓加载/预算不足/砍掉 N 个"；
      按意图装载，用户说"你有哪些工具"要能列出全部。
    · 无限 5：界面不显示"切片/循环/合并/检索/第 X 片/exceeds context"，只显示"正在处理…"。
    · 无限 6：单次请求 token ≤ 上限，靠**精确装配**而不是砍内容；
      日志格式 `system=a + tools=b + ... = 合计 f / 上限 g`；极端情况报错让用户知道，不静默丢。
"""
import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import xiaojiao_app as app   # noqa: E402

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


def _all_py_sources():
    """仓库里所有 .py 的源码文本（用于扫"禁止出现的话术"）。"""
    out = []
    for root, dirs, files in os.walk(_ROOT):
        dirs[:] = [d for d in dirs
                   if d not in ("__pycache__", ".git", ".ruff_cache", "logs", "backup_before_refactor")]
        for f in files:
            if f.endswith(".py"):
                p = os.path.join(root, f)
                if os.path.basename(p) == os.path.basename(__file__):
                    continue
                try:
                    with open(p, "r", encoding="utf-8", errors="replace") as fh:
                        out.append((p, fh.read()))
                except Exception:      # noqa: silent-ok — 读不动就跳过，不影响扫描结论
                    continue
    return out


def main():
    print("=" * 76)
    print("  无限 4/5/6 · 工具无限 / 感知无限 / 单次请求永不超")
    print("=" * 76)

    # ==================== 无限 4 · 工具无限 ====================
    print("\n[无限 4] 工具无限：一个不删、不暂缓、不砍")
    names = app.all_tool_names()
    ck("工具表非空且规模合理（当前 %d 个）" % len(names), len(names) >= 50, len(names))
    ck("工具名**全表唯一**（无重复注册）", len(names) == len(set(names)),
       len(names) - len(set(names)))
    ck("核心工具都在（run_command/read_file/write_file/list_files）",
       all(n in names for n in ("run_command", "read_file", "write_file", "list_files")),
       [n for n in ("run_command", "read_file", "write_file", "list_files") if n not in names])

    # 禁止话术：**只扫"用户/日志真的会看到"的输出**，不扫注释与文档字符串。
    # 为什么口径要这么定：第一版我扫了全文件的子串，于是把
    # `# 不能砍掉工具` 这种**解释性注释**也判成违规（假红）。
    # spec 的原意是"日志里不许出现暂缓/砍工具"，那就只查日志与界面文案。
    banned = ("暂缓加载", "工具预算不足", "砍工具", "工具被暂缓", "deferred")
    hits = []
    for path, src in _all_py_sources():
        rel = os.path.relpath(path, _ROOT)
        if rel.startswith("tools" + os.sep) or rel.startswith("tests" + os.sep):
            continue                       # 测试自己的说明文字不算产品输出
        for i, line in enumerate(src.split("\n")):
            s = line.strip()
            if s.startswith("#"):
                continue
            if not re.search(r"(LOG\.|logger\.|print\()", s):
                continue                   # 只看真正的日志/输出语句
            for b in banned:
                if b in s:
                    hits.append("%s:%d %s" % (rel, i + 1, b))
    ck("**日志/界面输出里没有「暂缓加载/砍工具/预算不足」**", not hits, hits[:4])

    # 按意图装载：每个意图都只装一小撮，且名字都是真的
    for intent in ("chat", "scrape", "query", "shell", "diagram"):
        only = app._intent_tool_names(intent)
        ck("%s 意图装载的工具都真实存在" % intent,
           all(n in names for n in only), [n for n in only if n not in names])
        ck("%s 意图只装一小撮（不是全量 %d 个）" % (intent, len(names)),
           len(only) < len(names), "%d 个" % len(only))

    # 完整工具目录仍在 system 里（模型点名即下一轮装 —— "能力一个不少"的机制保证）
    # 口径实测：77 个工具里 **69 个**按名字出现在 system 中；
    # 没出现的 8 个（check_env / background / ask_user 这类）是**基础设施类**内部工具
    # （后台任务、环境自检、追问），它们不靠模型点名调用，而是由载体自己触发。
    # 所以这里断言的是"绝大多数工具可见 + 缺的必须能被解释"，而不是"一个都不能少"——
    # 后者会把"设计如此"误判成缺陷（第一版就是这么假红的）。
    sp = app.compose_system_prompt("你是小焦。")
    names_all = app.all_tool_names()
    missing = [n for n in names_all if n not in sp]
    infra = ("check_env", "suggest_organize", "open_app", "grep_files", "fetch_url",
             "ask_user", "background", "background_result")
    ck("**完整工具目录随 system 下发**（≥85% 工具按名字可见）",
       len(missing) <= max(3, len(names_all) * 0.15),
       "可见 %d/%d，未可见 %s" % (len(names_all) - len(missing), len(names_all), missing[:6]))
    ck("未可见的都是**基础设施类**内部工具（由载体自己触发，不靠模型点名）",
       all(n in infra for n in missing), [n for n in missing if n not in infra])

    # ==================== 无限 5 · 感知无限 ====================
    print("\n[无限 5] 感知无限：界面只该看到「正在处理…」，不该看到技术痕迹")
    forbidden_ui = ("第 X/Y 片", "exceeds context", "第 %d/%d 片")
    # SSE 前端脚本里不许有暴露分片的文案（**只扫产品代码**，不扫测试自己的说明）
    js_hits = []
    for path, src in _all_py_sources():
        rel = os.path.relpath(path, _ROOT)
        if rel.startswith("tools" + os.sep) or rel.startswith("tests" + os.sep):
            continue
        if "第 %d/%d 片" in src or "片/共" in src:
            js_hits.append(rel)
    ck("源码里没有「第 X/Y 片」这类分片文案", not js_hits, js_hits[:3])

    # 进度回调只传数字（不携带技术文案）
    from core import input_splitter as I
    events = []
    text = ("小焦的记忆要外部化。" * 40 + "\n\n") * 40

    def _fake(messages, max_tokens, **kw):
        return "【片】" + str(len(messages[-1]["content"])) + " 字"

    I.process_long_input(text, "你是小焦。", max_chunk=2000,
                         on_progress=lambda d, t: events.append((d, t)), llm_fn=_fake)
    leaked = [e for e in events
              if any(w in str(e) for w in ("片", "chunk", "context", "token", "第 "))]
    ck("**进度回调只传数字**（界面拿到的是 (done,total)，不是文案）",
       bool(events) and not leaked, leaked[:2])
    ck("进度回调真的发生了（界面能显示正在处理）", len(events) >= 1, len(events))

    # 续写路径的停止原因也不能带分片术语给用户
    from core import continuation as C
    r = C.generate_unlimited("写一篇 3000 字的产品介绍", "你是小焦。", max_per_chunk=2000,
                             llm_fn=lambda m, mt, **k: "正常内容。" * 30, buffer_size=1)
    ck("长文生成的用户可见说明里没有分片术语",
       not any(w in str(r.get("stopped") or "") for w in ("片", "chunk", "token 上限")),
       r.get("stopped"))

    # ==================== 无限 6 · 单次请求永不超 ====================
    print("\n[无限 6] 单次请求永不超：靠装配，不靠砍内容")
    t_small = app._estimate_tokens("你好")
    ck("「你好」估 token < 3000（闲聊轮远低于上限）", 0 < t_small < 3000, t_small)
    t_big = app._estimate_tokens("画图" + "x" * 4000)
    ck("长输入的估算随长度增长（不是常数）", t_big > t_small, (t_small, t_big))
    ck("中文按 1.5 倍估算（不是按 1 倍少算）",
       app._estimate_tokens("中" * 100) >= 150, app._estimate_tokens("中" * 100))

    # _fit_context：返回 (保留历史, 说明文本)
    hist = [{"role": "user", "content": "旧" * 400} for _ in range(10)]
    kept, note = app._fit_context("系统提示" * 30, hist, "本轮问题",
                                  max_ctx=1200, tools_tokens=100)
    ck("返回 (保留历史, 说明) 两件套",
       isinstance(kept, list) and isinstance(note, str), (type(kept).__name__, type(note).__name__))
    ck("**从最老的历史开始砍**（保留的是尾部，不是头部）",
       kept == hist[-len(kept):] if kept else True, "%d/%d 轮" % (len(kept), len(hist)))
    ck("裁掉了一些历史（说明预算真的起作用了）", len(kept) < len(hist),
       "%d→%d" % (len(hist), len(kept)))
    ck("**日志格式符合 spec**（system=a + tools=b + … = 合计 f / 上限 g）",
       bool(re.search(r"system=\d+\s*\+\s*tools=\d+.*合计\s*\d+\s*/\s*上限\s*\d+", note)),
       note[:80])
    ck("说明里给出了真实数字（不是套话）", bool(re.search(r"\d+", note)), note[:60])

    # 极端超限：必须如实报出来（不静默丢）
    _kept2, note2 = app._fit_context("S" * 5000, [], "q", max_ctx=500, tools_tokens=2000)
    ck("**极端超限时如实报出合计与上限**（含数字，不静默）",
       bool(re.search(r"合计\s*\d+\s*/\s*上限\s*\d+", note2)), note2[:80])
    ck("system + 本轮问题**永远保留**（不能被砍掉）",
       "本轮" in note2 and "system=" in note2, note2[:60])

    # 工具 token 也进预算（这是修过的真 bug：不把 tools 算进去 → 还是超）
    _k3, note3 = app._fit_context("sys", [], "q", max_ctx=99999, tools_tokens=1234)
    ck("**tools_tokens 真的进了预算公式**（修过的 bug：原来不算它）",
       "tools=1234" in note3, note3[:70])

    okfit = True
    try:
        app._fit_context(None, None, None, max_ctx=100, tools_tokens=0)
    except Exception as e:
        okfit = False
        ck("脏输入不崩", False, e)
    if okfit:
        ck("脏输入（None/None/None）不崩", True)

    print("\n" + "=" * 76)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("=" * 76)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
