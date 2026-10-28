# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 统一跑测器（2026-10-28）

【为什么需要】原来的"一次性跑全部自测"是手写 PowerShell 循环，**没有超时**。
实测：`tools/test_bug45_ui.py` 会卡死（它开浏览器/等界面），整个批次就停在那一个文件上，
后面一百多个测试根本没跑 —— 于是"全绿"是假的，是没跑到。

【三件事】
  1. 每个测试文件**单独子进程 + 超时**（默认 150 秒），超时就杀掉并记「卡死」；
  2. 从输出里读「通过 X / 共 Y」；读不出来就按退出码判；
  3. **并行跑**（默认 4 路，因为一共 120+ 个文件，串行要几小时），
     跑完把"没通过"的**单独再跑一次**（串行、超时放宽）——
     并行时抢端口/抢模型会造出假失败，不重测就分不清是"真坏"还是"被挤坏"。

用法：
    python tools/run_all_tests.py                    # 并行 4 路，超时 150 秒，失败的再单跑复测
    python tools/run_all_tests.py --jobs 1           # 串行
    python tools/run_all_tests.py --timeout 300      # 改超时
    python tools/run_all_tests.py --no-recheck       # 不复测
    python tools/run_all_tests.py task_runner        # 只跑名字里带这个的
"""
import argparse
import io
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TOOLS = os.path.join(_ROOT, "tools")
_OUT = os.path.join(_ROOT, "docs", "test-report.md")

_SUM_RE = re.compile(r"通过\s*(\d+)\s*/\s*共\s*(\d+)")
_SUM_RE2 = re.compile(r"通过\s*(\d+)\s*项.*?失败\s*(\d+)\s*项")
# 「跳过」是"这台机器没有前提"，不是通过也不是失败 —— 必须单列，不然会虚报成绿。
_SKIP_RE = re.compile(r"(^|\n)\s*跳过[：:]")

# 慢测/联网测：它们不是"卡死"，是真的要跑很久（真对话、真浏览器）。
#   实测口径：`test_closed_loop` 是 8 条案例 × 3 次真模型对话 = 24 轮；给它 150 秒必然被误杀，
#   而"被超时杀掉"报成失败，等于拿尺子量错了对象。所以按文件给不同超时，其余默认 150 秒。
_SLOW = {
    "test_closed_loop.py": 900,
    "test_agnes_live.py": 900,
    "test_mind_stream_live.py": 600,
    "test_6_capabilities.py": 600,
    "test_module_integration.py": 600,
    "test_single_request_limit.py": 600,
    "test_stream_render.py": 600,
    "test_impression_usage.py": 600,
    "test_tool_infinity_live.py": 400,
    "test_math_render.py": 300,
}


def _files(only=""):
    out = []
    for fn in sorted(os.listdir(_TOOLS)):
        if not (fn.startswith("test_") and fn.endswith(".py")):
            continue
        if only and only not in fn:
            continue
        out.append(os.path.join(_TOOLS, fn))
    return out


def _parse(out, code):
    """从输出里读出 (通过数, 总数)。读不出来就按退出码给个保守结论。"""
    if code == 0 and _SKIP_RE.search(out) and not _SUM_RE.search(out):
        return 0, 0           # 跳过：不算通过，也不算失败
    m = _SUM_RE.search(out)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = _SUM_RE2.search(out)
    if m:
        p, f = int(m.group(1)), int(m.group(2))
        return p, p + f
    if code == 0:
        return 1, 1          # 没打印计数但退出码 0：按"这一个文件通过"计
    return 0, 1


def run_one(path, timeout):
    name = os.path.basename(path)
    timeout = _SLOW.get(name, timeout)      # 慢测/联网测给它更长的绳（见 _SLOW 的说明）
    t0 = time.time()
    try:
        p = subprocess.run([sys.executable, path], cwd=_ROOT, timeout=timeout,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out = (p.stdout or b"").decode("utf-8", "replace")
        ok_n, all_n = _parse(out, p.returncode)
        state = "跳过" if (ok_n == 0 and all_n == 0) else ("通过" if ok_n == all_n else "有失败")
        return {"name": name, "state": state,
                "ok": ok_n, "all": all_n, "sec": round(time.time() - t0, 1), "note": ""}
    except subprocess.TimeoutExpired:
        return {"name": name, "state": "卡死", "ok": 0, "all": 1,
                "sec": round(time.time() - t0, 1),
                "note": "超过 %d 秒没结束（已杀掉）" % timeout}
    except Exception as e:      # noqa: silent-ok — 单个文件起不来不能拖死整批
        return {"name": name, "state": "起不来", "ok": 0, "all": 1,
                "sec": round(time.time() - t0, 1),
                "note": "%s: %s" % (type(e).__name__, str(e)[:80])}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("only", nargs="?", default="")
    ap.add_argument("--timeout", type=int, default=150)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--no-recheck", action="store_true")
    ap.add_argument("--recheck-timeout", type=int, default=300)
    args = ap.parse_args(argv)
    files = _files(args.only)
    if not files:
        print("没有匹配的测试文件")
        return 1
    t_all = time.time()
    print("跑 %d 个测试文件（%d 路并行，超时 %d 秒）…" % (len(files), args.jobs, args.timeout))
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
        rows = list(ex.map(lambda f: run_one(f, args.timeout), files))
    for r in rows:
        if r["state"] not in ("通过", "跳过"):
            print("  ✗ %-42s %-6s %s/%s%s" % (r["name"], r["state"], r["ok"], r["all"],
                                              ("  ← " + r["note"]) if r["note"] else ""))
    # ---- 复测：并行时的失败可能只是"被挤的"，单独再跑一次才算数 ----
    bad = [r for r in rows if r["state"] not in ("通过", "跳过")]
    n_skip = sum(1 for r in rows if r["state"] == "跳过")
    if bad and not args.no_recheck:
        print("\n复测 %d 个没通过的（串行、超时 %d 秒）—— 分清「真坏」和「并行挤的」…"
              % (len(bad), args.recheck_timeout))
        by_name = {r["name"]: r for r in rows}
        for r in bad:
            # 复测的超时**不能比这个文件自己的预算更小** —— 否则慢测在复测里必被误杀，
            # 于是「卡死」这个结论就成了自己造成的（第一版踩过：closed_loop 主跑给 900 秒，
            # 复测只给 300 秒，永远卡死）。
            _t = max(args.recheck_timeout, _SLOW.get(r["name"], 0))
            r2 = run_one(os.path.join(_TOOLS, r["name"]), _t)
            r2["note"] = ("复测：%s%s" % (r2["state"], ("；" + r2["note"]) if r2["note"] else ""))
            by_name[r["name"]] = r2
            print("  %s → 复测 %s（%s/%s）" % (r["name"], r2["state"], r2["ok"], r2["all"]))
        rows = [by_name[r["name"]] for r in rows]
    ok_n = sum(r["ok"] for r in rows)
    all_n = sum(r["all"] for r in rows)
    bad = [r for r in rows if r["state"] not in ("通过", "跳过")]
    lines = ["# 自测报告（`tools/run_all_tests.py` 生成）", "",
             "- 文件：%d 个（跳过 %d）｜ 断言：%d / %d ｜ 没通过的文件：%d 个" % (
                 len(rows), n_skip, ok_n, all_n, len(bad)),
             "- 每文件单独子进程 + 超时 %d 秒（超时算「卡死」）；%d 路并行，没通过的已串行复测"
             % (args.timeout, args.jobs),
             "- 总耗时 %.1f 分钟" % ((time.time() - t_all) / 60.0),
             "", "| 测试文件 | 结论 | 通过/共 | 耗时(秒) | 备注 |", "| --- | --- | --- | --- | --- |"]
    for r in rows:
        lines.append("| `%s` | %s | %d/%d | %.1f | %s |" % (
            r["name"], r["state"], r["ok"], r["all"], r["sec"], r["note"] or ""))
    try:
        if args.only:
            # 只跑个别文件时**不要**覆盖全量报告 —— 实测踩过：单跑一个文件把
            # `docs/test-report.md` 盖成了"1 个文件"的报告，全量结论就此丢失。
            print("\n（单文件/子集运行，不覆盖 docs/test-report.md）")
        else:
            io.open(_OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
            print("\n已写：docs/test-report.md")
    except Exception as e:      # noqa: silent-ok — 写不出报告不影响结论
        print("报告没写成（%s）" % e)
    print("\n合计：%d / %d；跳过 %d 个；没通过的文件 %d 个%s" % (
        ok_n, all_n, n_skip, len(bad),
        ("：" + "、".join(r["name"] for r in bad)) if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
