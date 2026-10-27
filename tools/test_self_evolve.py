# -*- coding: utf-8 -*-
"""自进化内核 + 经验库 · 自测（离线、确定性）

钉住四件事：
  ① 经验库：记进去能读回来、失败能提炼成教训、同一条坑去重、太长会滚动（只加不删）；
  ② 诊断：能从评测/体检的实跑产物里**读出红点**，并归成"病"、给出可执行动作；
  ③ 排序：坏的 > 判据 > 答案 > 慢 > 未测 > 缺条件；
  ④ 边界：诊断**不自动改源码**；只有"缺能力"这一类标为可自动。
"""
import io
import json
import os
import shutil
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


def main():
    print("=" * 80)
    print("  自进化内核 + 经验库 自测")
    print("=" * 80)
    from core import experience as EXP
    from core import self_evolve as SE

    # ---------------- 一、经验库 ----------------
    print("\n[一] 经验库：记、读、提炼教训、去重")
    real_path = EXP._PATH
    tmpdir = tempfile.mkdtemp()
    try:
        EXP._PATH = os.path.join(tmpdir, "experience.jsonl")
        ck("一开始是空的", EXP.stats()["total"] == 0, EXP.stats())
        EXP.record("forge_fail", False, why="语法错误：第 107 行 '(' was never closed",
                   need="把中文数字转成阿拉伯数字", stage="static")
        st = EXP.stats()
        ck("记一条失败能读回来", st["total"] == 1 and st["rate"] == 0.0, st)
        lesson = EXP.suggest_lesson("static", "语法错误：第 107 行 '(' was never closed")
        ck("失败能被翻译成教训（这句才是失败样本的价值）", "截断" in lesson or "写更短" in lesson,
           lesson)
        EXP.record("forge_ok", True, need="统计字数", stage="written")
        ck("成功也记账（算成功率要用）", EXP.stats()["rate"] == 50.0, EXP.stats())
        got = EXP.lessons("forge_fail", keyword="中文数字", limit=5)
        ck("按关键词能取到同类失败的教训", len(got) == 1 and not got[0]["ok"], len(got))
        EXP.record("forge_fail", False, why="语法错误：第 107 行 '(' was never closed",
                   need="把中文数字转成阿拉伯数字", stage="static")
        got2 = EXP.lessons("forge_fail", keyword="中文数字", limit=5)
        ck("同一个坑反复记，取的时候去重（只留一条）", len(got2) == 1, len(got2))
        ck("按关键词不相关就取不到（不会乱注教训）",
           EXP.lessons("forge_fail", keyword="完全无关的需求", limit=5) == [])
        # 滚动：把上限临时压到 2，写第 3 条时应备份旧文件
        EXP._MAX_LINES = 2
        EXP.record("forge_ok", True, need="第三条")
        ck("太长会滚动备份（只加不删）",
           any(f.endswith(".1") or ".1" in f for f in os.listdir(tmpdir)),
           os.listdir(tmpdir))
    finally:
        EXP._PATH = real_path
        EXP._MAX_LINES = 4000
        shutil.rmtree(tmpdir, ignore_errors=True)

    # ---------------- 二、诊断：能读红点、能归类 ----------------
    print("\n[二] 诊断：从实跑产物里读出红点并归类")
    hist_backup, md_backup, health_backup = SE._EVAL_HIST, SE._EVAL_MD, SE._HEALTH_MD
    try:
        SE._EVAL_HIST = os.path.join(tmpdir, "eval-history.jsonl")
        SE._EVAL_MD = os.path.join(tmpdir, "eval-baseline.md")
        SE._HEALTH_MD = os.path.join(tmpdir, "capability-health.md")
        os.makedirs(tmpdir, exist_ok=True)
        io.open(SE._EVAL_HIST, "w", encoding="utf-8").write(json.dumps(
            {"score": 95.0, "total": 41, "pass": 39, "half": 2, "fail": 0,
             "failed": ["最近去菏泽旅游根据天去是否可以去 该用 get_weather，实际 无",
                        "3.11 和 3.9 哪个大 太慢 45.3s > 30s"]}, ensure_ascii=False) + "\n")
        io.open(SE._EVAL_MD, "w", encoding="utf-8").write(
            "# 评测\n\n| 问 | 工具 | 结果 | 说明 |\n| --- | --- | --- | --- |\n"
            "| 帮我抓 https://a.com | get | ✅ | ok |\n")
        io.open(SE._HEALTH_MD, "w", encoding="utf-8").write(
            "# 体检\n\n| 工具 | 来源 | 结论 | 说明 |\n| --- | --- | --- | --- |\n"
            "| `broken_tool` | 插件 | fail | 抛异常：KeyError |\n"
            "| `needs_param` | 插件 | 需参数 | 参数不合适：需要提供 session_id |\n"
            "| `needs_env` | 插件 | 需条件 | 缺：ComfyUI 没开 |\n"
            "| `untested` | 内置 | 未实测 | 会弹窗打扰 |\n"
            "| `good_tool` | 内置 | ok | 156 字 |\n")
        items = SE.diagnose(limit=20)
        kinds = [i["kind"] for i in items]
        ck("读出了评测里的判据问题", "judge" in kinds, kinds)
        ck("读出了评测里的性能问题", "perf" in kinds, kinds)
        ck("读出了体检里的真坏", "tool_bug" in kinds, kinds)
        ck("「需参数」没有当成工具坏了（这是最关键的区分）",
           "health_param" in kinds and [i for i in items if i["kind"] == "tool_bug"
                                        and i["target"] == "needs_param"] == [], kinds)
        ck("缺外部条件单独一类", "env" in kinds, kinds)
        ck("没测过单独一类", "health_untested" in kinds, kinds)
        ck("体检正常的那条不进清单", all(i["target"] != "good_tool" for i in items),
           [i["target"] for i in items])
        ck("排序：真坏排在最前", items[0]["kind"] == "tool_bug", items[0])

        # ---------------- 三、每条都要有"动作"，不许只说病名 ----------------
        print("\n[三] 每条改进项都必须给出可执行动作（不是「再优化一下」）")
        ck("每条都有动作且不是空话",
           all(len(str(i.get("action") or "")) >= 10 for i in items),
           [i.get("action", "")[:20] for i in items[:3]])
        ck("每条都有证据", all(bool(str(i.get("evidence") or "")) for i in items))
        rep = SE.report(limit=5)
        ck("报告是人话（带编号与证据）", "下一步该修什么" in rep and "证据：" in rep, rep[:60])
        ck("报告里写明「不自动改源码」这条边界", "不自动改源码" in rep, rep[-80:])

        # ---------------- 四、边界：只有「缺能力」标为可自动 ----------------
        print("\n[四] 边界：唯一可自动的是「缺能力」")
        for i in items:
            if i["kind"] == "capability":
                ck("缺能力 → 标为可自动（走 forge 带闸门落地）", i["auto"] is True, i)
        ck("其它类一律不自动（改源码必须人看）",
           all(i["auto"] is False for i in items if i["kind"] != "capability"),
           [(i["kind"], i["auto"]) for i in items if i["auto"]])
        st = SE.stats()
        ck("stats() 给出结构化快照（找了几项、按病分类）",
           "findings" in st and "by_kind" in st, st)
    finally:
        SE._EVAL_HIST, SE._EVAL_MD, SE._HEALTH_MD = hist_backup, md_backup, health_backup
        shutil.rmtree(tmpdir, ignore_errors=True)

    # ---------------- 五、文档类：文档和事实对不上要能查出来 ----------------
    print("\n[五] 文档类：文档写的和事实不一致时要报出来")
    docs_backup = SE._DOCS
    try:
        d2 = tempfile.mkdtemp()
        SE._DOCS = d2
        io.open(os.path.join(d2, "tool-catalog.md"), "w", encoding="utf-8").write(
            "# 工具清单\n\n工具总数：999 个\n")            # 故意写错
        io.open(os.path.join(d2, "eval-baseline.md"), "w", encoding="utf-8").write(
            "# 评测\n\n得分 42.0%\n")
        io.open(os.path.join(d2, "capability-health.md"), "w", encoding="utf-8").write(
            "# 体检\n\n**合计 999 ｜ 可用 1**\n\n| 工具 | 来源 | 结论 | 说明 |\n"
            "| --- | --- | --- | --- |\n| `a` | 内置 | ok | x |\n")
        SE._EVAL_HIST = os.path.join(d2, "eval-history.jsonl")
        io.open(SE._EVAL_HIST, "w", encoding="utf-8").write(json.dumps(
            {"score": 100.0, "total": 41, "pass": 41, "half": 0, "fail": 0},
            ensure_ascii=False) + "\n")
        SE._EVAL_MD = os.path.join(d2, "eval-baseline.md")
        SE._HEALTH_MD = os.path.join(d2, "capability-health.md")
        docs = SE._doc_checks()
        ck("查出工具数与实际不符", any("tool-catalog" in x["target"] for x in docs),
           [x["target"] for x in docs])
        ck("查出评测基线与趋势不一致", any("eval-baseline" in x["target"] for x in docs),
           [x["target"] for x in docs])
        ck("查出体检合计与表格行数不符",
           any("capability-health" in x["target"] for x in docs),
           [x["target"] for x in docs])
        ck("每条文档问题都给了重生成命令",
           all("python tools/" in x["action"] for x in docs), [x["action"][:20] for x in docs])
        st2 = SE.stats()
        ck("文档问题计入诊断（kind=doc）", st2["by_kind"].get("doc", 0) >= 1, st2["by_kind"])
    finally:
        SE._DOCS = docs_backup
        SE._EVAL_HIST = os.path.join(_ROOT, "docs", "eval-history.jsonl")
        SE._EVAL_MD = os.path.join(_ROOT, "docs", "eval-baseline.md")
        SE._HEALTH_MD = os.path.join(_ROOT, "docs", "capability-health.md")
        shutil.rmtree(d2, ignore_errors=True)

    print("\n" + "=" * 80)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("=" * 80)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
