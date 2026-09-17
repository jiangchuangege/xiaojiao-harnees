# -*- coding: utf-8 -*-
"""跑一遍本轮新增的**全部**自测脚本，汇总通过/失败（不含 249 全量回归，那个单独跑）。

运行：python tools/run_new_tests.py
为什么要有它：本轮新增了 12 个自测脚本，一个个手敲容易漏。
这个脚本把"每个模块都要有单测且能实测"这句话变成一条命令 + 一张汇总表。
退出码：0 = 全绿；1 = 有失败（CI 据此判定）。

【2026-09-18 补登 8 个】那轮"事/我 + 接回 + 精排"改动新增的自测，全部**离线可跑**
（不调大脑、不联网），已经补进下面的 TESTS：
  test_rerank_gate（精排两处改动）、test_realtime_fact（时效性事实）、
  test_memory_plugin_gate（写记忆闸门）、test_brain_line_cleanup（直连清理）、
  test_thinking_loop_vector（向量路径硬化）、test_heart_back（心接回）、
  test_mind_facts（思维流事实块）、test_inner_facts（内里只列事实）。
【2026-09-18 再补 2 个】收尾那批：test_self_echo（自我回灌）、
  test_cross_check_wired（答后交叉检查真的接进主流程 —— 这条钉的是"接线"，不是模块本身）。
**故意没登进来**的两个：`tools/test_event_what_retrieval.py` 与 `tools/test_last_jump.py`
—— 它们**必须调本地大脑**（要 llama-swap 在 :9292 跑着），登进来会让这个脚本在大脑没起时红。
"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable

# (脚本, 说明)
TESTS = [
    ("tools/test_no_delete.py", "删除红线 · 判定模块（core/security）"),
    ("tools/test_redline_integration.py", "删除红线 · 接线（走真实工具入口 run_tool）"),
    ("tools/test_degeneration.py", "退化检测（Bug 3 地基）"),
    ("tools/test_bug3_repeat.py", "Bug 3 · 复读循环端到端"),
    ("tools/test_bug2_dedup.py", "Bug 2 · get 去重"),
    ("tools/test_bug45_ui.py", "Bug 4/5 · 停止按钮 + 切会话"),
    ("tools/test_bug6_open_html.py", "Bug 6 · 画完自动打开 HTML"),
    ("tools/test_health.py", "健康系统 · 模块（monitor/diagnose/heal/records）"),
    ("tools/test_health_integration.py", "健康系统 · 接线（走 _health_gate）"),
    ("tools/test_autonomy.py", "自主性（scheduler/learner/watcher）"),
    ("tools/test_world.py", "世界层（perception/model）"),
    ("tools/test_carrier.py", "变形金刚（brain_registry/capability）"),
    ("tools/test_platform_integration.py", "平台接线（世界/变形金刚/自主性在主程序里生效）"),
    ("tools/test_repeat_all_paths.py", "问题 1 · 复读检测挂在所有输出路径上"),
    ("tools/test_longform_quality.py", "问题 3 · 长文四项质检（字数/章节/引号/人名）"),
    ("tools/test_scrape_retry.py", "问题 4 · 忽略 robots 抓一次必须真去抓"),
    ("tools/test_world_firewall.py", "世界层重构 + 信息污染防火墙"),
    ("tools/check_frontend_js.py", "前端 JS 语法与结构契约"),
    ("tools/check_motto.py", "载体层总纲注释覆盖（26 个模块）"),
    # ---- 2026-09-18 补登：事/我 + 心接回 + 精排那轮新增的 8 个（都离线可跑）----
    ("tools/test_rerank_gate.py", "精排两处改动（RERANK_GAP 0.50 / 判官不可用改卡阈值）"),
    ("tools/test_realtime_fact.py", "时效性事实（时间词 + 事实词才放行联网结果）"),
    ("tools/test_memory_plugin_gate.py", "写记忆闸门（复读/乱码/重复不写，如实说没记）"),
    ("tools/test_brain_line_cleanup.py", "直连清理只杀 llama-server（不误杀别的进程）"),
    ("tools/test_thinking_loop_vector.py", "思维流向量路径硬化（空候选不崩、用事/我检索）"),
    ("tools/test_heart_back.py", "心接回（心跳 n 变了才接、原文照搬、assistant 角色）"),
    ("tools/test_mind_facts.py", "思维流事实块（只列事实、剥掉载体框）"),
    ("tools/test_inner_facts.py", "内里只列事实（不再写孤独/低沉这些词）"),
    # ---- 2026-09-18 第二批：收尾那一批（自我回灌 / 交叉检查接线）----
    ("tools/test_self_echo.py", "自我回灌（它自己说过的话不算事实来源）"),
    ("tools/test_cross_check_wired.py", "答后交叉检查**真的接进主流程**（接线 + 触发判据 + 边界）"),
]


def main():
    env = dict(os.environ, PYTHONUTF8="1")
    rows = []
    print("=" * 70)
    print("  本轮新增自测 · 全量扫一遍")
    print("=" * 70)
    for path, desc in TESTS:
        full = os.path.join(ROOT, path)
        if not os.path.exists(full):
            rows.append((path, desc, "缺失", 0.0))
            print("  ❌ %-42s 缺失" % path)
            continue
        t0 = time.time()
        r = subprocess.run([PY, full], cwd=ROOT, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        el = time.time() - t0
        out = (r.stdout or "") + (r.stderr or "")
        # 抓脚本自己打印的汇总行（每个脚本都按统一格式输出"通过 N / 共 M"）
        tail = ""
        for line in reversed(out.splitlines()):
            if "通过" in line and "/" in line:
                tail = line.strip()
                break
        status = "✅" if r.returncode == 0 else "❌"
        rows.append((path, desc, tail or ("exit=%d" % r.returncode), el, r.returncode))
        print("  %s %-42s %-28s %5.1fs" % (status, path, tail[:28], el))
        if r.returncode != 0:
            last = out.strip().splitlines()[-1][:110] if out.strip() else "(无输出)"
            print("      ↳ %s" % last)
    failed = [r[0] for r in rows if r[4] != 0]
    print("-" * 70)
    print("  脚本 %d 个 ｜ 全绿 %d 个 ｜ 失败 %d 个%s ｜ 总耗时 %.1fs"
          % (len(rows), len(rows) - len(failed), len(failed),
             ("：" + "、".join(failed)) if failed else "", sum(r[3] for r in rows)))
    print("=" * 70)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
