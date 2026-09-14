# -*- coding: utf-8 -*-
"""跑一遍本轮新增的**全部**自测脚本，汇总通过/失败（不含 249 全量回归，那个单独跑）。

运行：python tools/run_new_tests.py
为什么要有它：本轮新增了 12 个自测脚本，一个个手敲容易漏。
这个脚本把"每个模块都要有单测且能实测"这句话变成一条命令 + 一张汇总表。
退出码：0 = 全绿；1 = 有失败（CI 据此判定）。
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
