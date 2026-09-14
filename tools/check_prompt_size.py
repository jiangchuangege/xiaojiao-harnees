# -*- coding: utf-8 -*-
"""体检「单次请求到底装了什么」—— 各部分 token 占比 + 各意图的 system/tools 总量。

用法：
    python tools/check_prompt_size.py              # 全表
    python tools/check_prompt_size.py --intent chat   # 只看某一个意图

为什么要它（无限 6：单次永不超）：
本地 ctx 是 20224（llama.cpp 把 -c 20000 向上取整到 256 的倍数），可用上限
`_max_context_tokens()` = 20224 - 1000 安全余量 = **19224**。
"会不会超"不能靠感觉 —— 得能一眼看清 system 里哪一段最肥、哪个意图的工具最占地方，
否则每次撞上 "exceeds context" 都只能靠猜。这个脚本就是那把尺子。

判据（照 spec）：
  · 说"你好"      → 合计 < 3000
  · 说"用 Archify 画图" → 合计 < 10000
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import xiaojiao_app as x  # noqa: E402

T = x._estimate_tokens
INTENTS = ["chat", "scrape", "diagram", "query", "shell", "full"]


def _pct(a, b):
    return ("%.0f%%" % (100.0 * a / b)) if b else "-"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--intent", default="", help="只看某个意图")
    args = ap.parse_args()

    max_ctx = x._max_context_tokens()
    print("=" * 96)
    print("小焦 · 单次请求体检（可用上限 = %d token）" % max_ctx)
    print("=" * 96)

    # ---------- system 各段占比 ----------
    print()
    print("【SYSTEM_PROMPT 各部分 token 占比】")
    role = x.strip_search_rules(x.CONTROL.get("role", ""))
    parts = [
        ("role（纯人设）", role),
        ("_SEARCH_RULES（检索铁律）", x._SEARCH_RULES),
        ("_TOOL_RULES（工具铁律）", x._TOOL_RULES),
        ("_CHAT_SYSTEM_HINT（闲聊模式）", x._CHAT_SYSTEM_HINT),
        ("_CHAT_FALLBACK_HINT（兜底模式）", x._CHAT_FALLBACK_HINT),
        ("_DIAGRAM_SYSTEM_HINT（画图工作流）", x._DIAGRAM_SYSTEM_HINT),
        ("_MEMORY_INSTRUCTION（记忆指令）", x._MEMORY_INSTRUCTION),
    ]
    total_sys = T(x.SYSTEM_PROMPT)
    for name, txt in parts:
        t = T(txt)
        print("  %-34s %6d token   （占 SYSTEM_PROMPT 的 %s）" % (name, t, _pct(t, total_sys)))
    print("  %-34s %6d token" % ("SYSTEM_PROMPT 合计", total_sys))

    # ---------- 工具表 ----------
    print()
    print("【工具表】")
    all_names = x.all_tool_names()
    full_tools = x._tools_tokens(all_names)
    print("  全部工具：%d 个 → %d token（占上限的 %s）" % (len(all_names), full_tools, _pct(full_tools, max_ctx)))
    print("  （这就是「为什么不能一轮全发」的数字 —— 单它一项就吃掉上限的 %s）" % _pct(full_tools, max_ctx))

    # ---------- 各意图 ----------
    print()
    print("【各意图：system + 本轮 + 工具】")
    print("-" * 96)
    print("%-9s %8s %8s %8s %9s %9s  %s" % ("意图", "system", "tools", "本轮", "合计", "占上限", "本轮装载工具"))
    print("-" * 96)
    for intent in INTENTS:
        if args.intent and intent != args.intent:
            continue
        q = {"chat": "你好", "scrape": "抓一下 example.com", "diagram": "用 Archify 画图",
             "query": "我的 IP", "shell": "echo hello", "full": "随便来点"}.get(intent, "你好")
        sys_text = x.system_for_intent(intent, user_input=q)
        subset, reserve = x._plan_tools(intent, sys_text, q)
        s, c = T(sys_text), T(q)
        total = s + reserve + c + x._MSG_OVERHEAD * 2
        warn = "⚠️ 超 0.8×上限" if total > max_ctx * 0.8 else ""
        print("%-9s %8d %8d %8d %9d %9s  %d 个 %s"
              % (intent, s, reserve, c, total, _pct(total, max_ctx), len(subset), warn))
    print("-" * 96)

    # ---------- spec 判据 ----------
    print()
    print("【spec 判据】")
    for q, ceiling in (("你好", 3000), ("用 Archify 画图", 10000)):
        intent = x._detect_intent(q)
        sys_text = x.system_for_intent(intent, user_input=q)
        if intent != "chat":
            sys_text += "\n[环境] 当前时间：2026-01-01 00:00:00；当前工作目录：C:\\；用户主目录：C:\\Users\\x；桌面：C:\\Users\\x\\Desktop。"
        subset, reserve = x._plan_tools(intent, sys_text, q)
        total = T(sys_text) + reserve + T(q) + x._MSG_OVERHEAD * 2
        print("  %-18s 意图=%-8s 合计 %6d  < %d ？ %s"
              % (q, intent, total, ceiling, "✅" if total < ceiling else "❌"))
    print()
    print("提示：这里的「合计」是**固定开销**（system + tools + 本轮）。真实请求还要加历史与检索记忆，")
    print("      那部分由 _fit_context 按上限自动裁剪 —— 想看某一轮的真实数字看 logs/context_fit.log。")


if __name__ == "__main__":
    main()
