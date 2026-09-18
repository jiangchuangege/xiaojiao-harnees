# -*- coding: utf-8 -*-
"""★ **一条命令跑完全部** ★ —— 仓库里所有该跑的东西，最后给一张表。

跑什么（自动发现，不用维护清单）：
  ① `tools/check_*.py`            —— 文档/图/密钥/原理/尺寸等闸门
  ② `tools/test_*.py`             —— 各模块自测（默认包括；**需要大脑或联网的会自动跳过**，
                                     并如实标成「跳过」，绝不算通过）
  ③ `tools/*.py --selftest`       —— 自带自测的工具（如 dedupe_preference）
  ④ `tests/stress/run_all.py`     —— 249 条全量套件（四个子套件）

用法：
    python run_all_tests.py            # 全跑
    python run_all_tests.py --fast     # 跳过全量套件里最慢的部分（只跑 ①②③）
退出码：0 = 全绿（跳过的另计）；1 = 有失败。
"""
import io
import os
import re
import subprocess
import sys
import time

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:      # noqa: silent-ok
        pass

ROOT = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
ENV = dict(os.environ, PYTHONUTF8="1")

# 需要外部条件（大脑 / 联网 / 浏览器 / 服务在跑）的脚本：**跳过并如实标注**，不当通过
NEED_BRAIN = ("test_event_what_retrieval", "test_last_jump", "test_closed_loop",
              "test_profile_recall_integration", "test_impression_usage",
              "test_module_integration", "test_mind_stream_live", "test_tool_infinity_live",
              "test_perception_infinity", "test_stream_render", "test_single_request_limit")
NEED_NET = ("test_scrape_retry", "test_bug2_dedup", "test_network")
SKIP_BY_NAME = NEED_BRAIN + NEED_NET

SUMMARY = re.compile(r"通过\s*(\d+)\s*/\s*共\s*(\d+)|通过\s*(\d+)\s*/\s*(\d+)|(\d+)\s*/\s*(\d+)\s*通过")
FAIL = re.compile(r"(❌|FAIL|Traceback|AssertionError)")


def _run(cmd, timeout=1800):
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=ROOT, env=ENV, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        out = (r.stdout or "") + (r.stderr or "")
        return r.returncode, out, time.time() - t0
    except subprocess.TimeoutExpired:
        return 999, "（超时 %ds）" % timeout, time.time() - t0
    except Exception as e:      # noqa: silent-ok
        return 998, "（跑不起来：%r）" % e, time.time() - t0


def _tail_line(out):
    """从输出里挑出最能说明结果的一行。"""
    for line in reversed(out.strip().splitlines()):
        s = line.strip()
        if not s:
            continue
        if SUMMARY.search(s) or "结论" in s or "✅" in s or "❌" in s or "总计" in s:
            return s[:120]
    return (out.strip().splitlines() or ["（无输出）"])[-1][:120]


def main():
    fast = "--fast" in sys.argv
    rows = []

    tests = sorted(f for f in os.listdir(os.path.join(ROOT, "tools"))
                   if f.startswith("test_") and f.endswith(".py"))
    checks = sorted(f for f in os.listdir(os.path.join(ROOT, "tools"))
                    if f.startswith("check_") and f.endswith(".py"))
    selftests = ["dedupe_preference.py"]

    work = ([("闸门", "tools/" + c, []) for c in checks]
            + [("自测", "tools/" + t, []) for t in tests]
            + [("工具自测", "tools/" + s, ["--selftest"]) for s in selftests])
    print("=" * 96)
    print("  一条命令跑完全部 ｜ 闸门 %d 个 · 自测 %d 个 · 工具自测 %d 个%s"
          % (len(checks), len(tests), len(selftests), "" if fast else " · 全量套件 1 个"))
    print("=" * 96)

    for kind, path, extra in work:
        name = os.path.basename(path)
        if any(s in name for s in SKIP_BY_NAME):
            rows.append((kind, name, "跳过", "需要大脑/联网/浏览器（不算通过）", 0.0))
            print("  ⏭  %-16s %-40s %s" % (kind, name, "跳过（需要外部条件）"))
            continue
        rc, out, el = _run([PY, path] + extra)
        ok = (rc == 0) and not FAIL.search(out.split("通过")[0] if "通过" in out else out[:0])
        ok = (rc == 0)
        rows.append((kind, name, "通过" if ok else "失败", _tail_line(out), el))
        print("  %s %-16s %-40s %6.1fs  %s"
              % ("✅" if ok else "❌", kind, name, el, _tail_line(out)[:60]))

    if not fast:
        rc, out, el = _run([PY, "tests/stress/run_all.py"], timeout=2400)
        ok = (rc == 0)
        rows.append(("全量套件", "tests/stress/run_all.py", "通过" if ok else "失败",
                     _tail_line(out), el))
        print("  %s %-16s %-40s %6.1fs  %s"
              % ("✅" if ok else "❌", "全量套件", "tests/stress/run_all.py", el,
                 _tail_line(out)[:60]))

    bad = [r for r in rows if r[2] == "失败"]
    skip = [r for r in rows if r[2] == "跳过"]
    print("\n" + "=" * 96)
    print("  合计 %d 项 ｜ 通过 %d ｜ 失败 %d ｜ 跳过 %d（跳过的不算通过）"
          % (len(rows), len(rows) - len(bad) - len(skip), len(bad), len(skip)))
    if bad:
        print("  ❌ 失败清单：")
        for r in bad:
            print("      %-40s %s" % (r[1], r[3]))
    if skip:
        print("  ⏭ 跳过清单：%s" % "、".join(r[1] for r in skip))
    print("=" * 96)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
