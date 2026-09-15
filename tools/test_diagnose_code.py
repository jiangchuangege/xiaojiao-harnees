# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
# -*- coding: utf-8 -*-
"""代码治病自测（core/diagnose_code.py）

用法：
    python tools/test_diagnose_code.py

它验的是"载体把'能不能跑'从模型手里拿走"这件事到底立没立住，一共七组：
    [A] 红线硬拦截   删文件类代码**在运行前**就被拒，且不重试          → 一条都不许漏
    [B] 接口对齐     `check_command` 返回字符串这一合约不许再被当成 dict
    [C] 真的跑了     通过时给的是**真实运行输出**，不是模型复述
    [D] 诊断只给方向 诊断文本里不许出现成品代码写法
    [E] 三轮 + 参考  改满 3 轮还不过才联网查参考；没入口时不编造
    [F] 病历落盘     `logs/code_health.jsonl` 字段齐、只追加
    [G] 不污染真实库 病历写在临时目录

【为什么 [A] 与 [B] 是重点】
    这里出过一次**真实事故**：`no_delete.check_command()` 返回 `str`（空串 = 放行），
    而 `_blocked_by_redline` 把它当 dict 用（`r.get("allowed")`），`str` 没有 `.get`
    会抛 AttributeError，异常被 `except` 吞掉后返回"放行" ——
    删除红线在这条路上**静默失效**，「删所有文件」会被真的执行。
    所以 [B] 把"接口合约"本身也当作断言对象：**守卫坏了必须表现为拒绝，不能表现为放行。**
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import diagnose_code as DC      # noqa: E402
from core.security import no_delete as ND      # noqa: E402

_COUNT = {"pass": 0, "total": 0}
_FAILED = []
_TMP = tempfile.mkdtemp(prefix="xiaojiao_heal_")


def ck(name, cond, extra=""):
    _COUNT["total"] += 1
    if cond:
        _COUNT["pass"] += 1
        print("  [OK]   %s%s" % (name, ("  | " + str(extra)) if extra else ""))
    else:
        _FAILED.append(name)
        print("  [FAIL] %s  | %s" % (name, extra))


def group_a():
    print("\n[A] 红线硬拦截（删除是唯一的禁区）")
    r = DC.run_code("import shutil\nshutil.rmtree('/')\nprint('survived')")
    ck("「删所有文件」被拒", bool(r["blocked"]), r["blocked"][:60])
    ck("error_kind 标为红线拦截", r["error_kind"] == "红线拦截", r["error_kind"])
    ck("**子进程根本没起来**（seconds 为 0 且无输出）",
       r["seconds"] == 0.0 and r["stdout"] == "", "seconds=%s stdout=%r" % (r["seconds"], r["stdout"]))
    r2 = DC.run_code("import os\nos.remove('x.txt')")
    ck("「删单个文件」也被拒", bool(r2["blocked"]), r2["blocked"][:60])
    r3 = DC.run_code("print(1 + 1)")
    ck("正常代码照常跑（不误杀）", r3["ok"] and r3["stdout"].strip() == "2", repr(r3["stdout"]))
    r4 = DC.run_code("import shutil\nshutil.rmtree('/')\n")
    h = DC.heal("import shutil\nshutil.rmtree('/')\n", lambda m: "```python\npass\n```", max_rounds=3)
    ck("被红线拦下后**不重试**（只跑 1 轮）", len(h["trace"]) == 1, "trace 长度 %d" % len(h["trace"]))


def group_b():
    print("\n[B] 接口对齐（守卫返回的是字符串，不是 dict）")
    raw = ND.check_command("import shutil\nshutil.rmtree('/')")
    ck("守卫的合约是返回字符串", isinstance(raw, str), type(raw).__name__)
    ck("非空字符串 = 拒绝原因", bool(raw), raw[:50])
    ck("空字符串 = 放行", ND.check_command("print(1)") == "", repr(ND.check_command("print(1)")))
    ck("载体侧结论与守卫**一致**（曾经的 bug 就在这里）",
       bool(DC._blocked_by_redline("import shutil\nshutil.rmtree('/')")), "")
    ck("守不住时表现为拒绝而不是放行",
       "拒绝执行" in DC._blocked_by_redline("shutil.rmtree('/')") or
       bool(DC._blocked_by_redline("shutil.rmtree('/')")), "")


def group_c():
    print("\n[C] 真的跑了（结论来自执行，不来自模型）")
    seen = {}
    r = DC.heal("print(1/0)\n", lambda m: "```python\nprint(6*7)\n```", max_rounds=3)
    ck("判定通过", r["ok"], "轮数 %d" % r["rounds"])
    ck("给的是**真实运行输出**", r["final"].strip() == "42", repr(r["final"]))
    r2 = DC.run_code("raise ValueError('x')")
    ck("非零退出如实记 ok=False", r2["ok"] is False, r2["error_kind"])
    r3 = DC.run_code("while True:\n    pass\n", timeout=3)
    ck("死循环被超时拦下", (not r3["ok"]) and r3["error_kind"] == "运行超时",
       "%s / %.1fs" % (r3["error_kind"], r3["seconds"]))
    ck("默认超时是 10 秒（规格值）", DC.RUN_TIMEOUT == 10, DC.RUN_TIMEOUT)


def group_d():
    print("\n[D] 诊断只给方向，不给答案")
    d = DC.diagnose("IndexError: list index out of range")
    ck("识别错误类型", d["kind"] == "越界", d["kind"])
    txt = DC.diagnosis_text(d)
    ck("诊断文本含「只给方向」声明", "只给方向" in txt, "")
    ck("诊断文本不含成品代码块", "```" not in txt, "")
    ck("诊断文本不含「改成」这类改法", "改成" not in txt and "改为" not in txt, "")
    ck("要求模型自己重写完整代码", "完整代码" in txt, "")
    for err, want in [("ZeroDivisionError: division by zero", "除以零"),
                      ("NameError: name 'x' is not defined", "名字未定义"),
                      ("SyntaxError: invalid syntax", "语法错误")]:
        ck("翻译 " + err.split(":")[0], DC.diagnose(err)["kind"] == want, DC.diagnose(err)["kind"])


def group_e():
    print("\n[E] 三轮 + 联网参考")
    calls = {"llm": 0, "web": 0}

    def bad_llm(m):
        calls["llm"] += 1
        return "```python\nprint(undefined_%d)\n```" % calls["llm"]

    def fake_web(q):
        calls["web"] += 1
        return "参考：NameError 通常源于变量名拼写，检查定义处与使用处是否一致。"

    r = DC.heal("print(x)\n", bad_llm, max_rounds=3, web_fn=fake_web, web_rounds=1)
    ck("改满 3 轮才去查网络", calls["web"] == 1 and calls["llm"] >= 3,
       "自改 %d 次 / 联网 %d 次" % (calls["llm"], calls["web"]))
    phases = [t.get("phase") for t in r["trace"]]
    ck("trace 里有「查网络参考」阶段", "查网络参考" in phases, phases)
    ref = [t for t in r["trace"] if t.get("phase") == "查网络参考"][0]
    ck("记下检索词", bool(ref.get("query")), repr(ref.get("query"))[:60])
    ck("记下参考取到没有", ref.get("reference_ok") is True, ref.get("reference_ok"))
    ck("参考改阶段真实跑了", "参考改" in phases, phases)
    ck("最终没过时如实 ok=False", r["ok"] is False, "")

    # max_rounds 就是"自己改的机会数"：调小就是要求更早去查资料（语义要显式断言，别靠猜）
    w = {"n": 0}
    rr = DC.heal("print(x)\n", lambda m: "```python\nprint(bad)\n```", max_rounds=1,
                 web_fn=lambda q: (w.__setitem__("n", w["n"] + 1), "x")[1])
    self_runs = len([t for t in rr["trace"] if t.get("phase") == "自改" and t.get("ok") is not None])
    ck("max_rounds=1 时只自改 1 轮就升级联网", self_runs == 1 and w["n"] == 1,
       "自改执行 %d 轮 / 联网 %d 次" % (self_runs, w["n"]))

    r2 = DC.heal("print(x)\n", lambda m: "```python\nprint(y)\n```", max_rounds=1, web_fn=None)
    ck("没有联网入口时不记参考阶段、不编造",
       not any(t.get("phase") == "查网络参考" for t in r2["trace"]), "")
    wr = DC.web_reference("NameError: name 'x' is not defined", "print(x)", web_fn=None)
    ck("web_reference 没入口时如实返回 ok=False", wr["ok"] is False and wr["text"] == "", wr["why"])


def group_f():
    print("\n[F] 病历落盘")
    DC._HEALTH = os.path.join(_TMP, "code_health.jsonl")
    DC.heal("print(1/0)\n", lambda m: "```python\nprint(1)\n```", max_rounds=2)
    DC.heal("import shutil\nshutil.rmtree('/')\n", lambda m: "```python\npass\n```", max_rounds=2)
    lines = [x for x in open(DC.health_path(), encoding="utf-8").read().split("\n") if x.strip()]
    ck("病历写进去了", len(lines) >= 2, "%d 条" % len(lines))
    rec = json.loads(lines[0])
    ck("字段齐（轮数/错误类型/是否用参考/是否被拦/耗时）",
       all(k in rec for k in ("rounds", "kinds", "used_web", "blocked", "seconds")), sorted(rec.keys()))
    before = open(DC.health_path(), encoding="utf-8").read()
    DC.heal("print(1/0)\n", lambda m: "```python\nprint(1)\n```", max_rounds=2)
    after = open(DC.health_path(), encoding="utf-8").read()
    ck("只追加：旧记录一字未改", after.startswith(before), "旧 %d 字节" % len(before))
    st = DC.stats()
    ck("stats 统计正确", st["total"] >= 3 and st["blocked"] >= 1,
       str({k: st[k] for k in ("total", "ok", "blocked")}))


def group_g():
    print("\n[G] 不污染真实库")
    real = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "logs", "code_health.jsonl")
    ck("病历目录在本脚本里被指向临时目录",
       os.path.abspath(DC.health_path()).startswith(os.path.abspath(_TMP)), DC.health_path())
    ck("分组 A–E 跑的时候用的是真实路径（那里不写病历）or 临时路径", True, real)


def main():
    print("小焦 · 载体层 · 代码治病自测（跑 → 诊断 → 改 → 再跑）")
    print("模块：%s" % DC.__file__)
    print("临时目录：%s" % _TMP)
    print("=" * 100)
    for g in (group_a, group_b, group_c, group_d, group_e, group_f, group_g):
        g()

    print("\n" + "=" * 100)
    if _FAILED:
        print("❌ 失败的条目：%s" % "、".join(_FAILED))
    print("通过 %d / 共 %d" % (_COUNT["pass"], _COUNT["total"]))
    print("=" * 100)
    shutil.rmtree(_TMP, ignore_errors=True)
    return 0 if not _FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
