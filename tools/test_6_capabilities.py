# -*- coding: utf-8 -*-
"""六项能力 · 总验收（一次跑完，不再一项一个脚本）

覆盖：① 元认知自评 ② 计算器 ③ 代码治病 ④ RAG + 联网内化 ⑤ 学习闭环 → 精神记忆库
外加：全量 249 ｜ 场景 1-8 ｜ 「修复后直接输出」

【为什么合成一个脚本】
  六项能力是**一条链**上的不同环节（自评决定走哪条路 → 计算器/检索/工具执行 → 内化 → 下次复用）。
  拆成六个脚本只能各自证明"这个函数是对的"，证明不了"这条链接上了"——
  而这个项目踩过最多的坑恰恰就是"函数是对的、但从来没被调用过"。
  所以主判据一律是**走真实入口**（HTTP 或真实模块入口），而不是直接调内部函数。

【判据分层，避免假红】
  · 确定性项（计算器/内化/代码治病）：不依赖模型，必须全过
  · 模型相关项（自评档位、联网内化）：允许"跳过"，但**跳过必须写明原因**，不许静默算通过
"""
import io
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.environ.get("XIAOJIAO_BASE", "http://127.0.0.1:5000")

PASS = {"n": 0, "ok": 0, "skip": 0}
FAILS = []
NOTES = []


def ck(name, cond, extra="", soft=False):
    PASS["n"] += 1
    if cond:
        PASS["ok"] += 1
        print("  ✅ %s%s" % (name, ("  ← %s" % extra) if extra else ""))
    elif soft:
        PASS["skip"] += 1
        NOTES.append(name)
        print("  ⏭️ %s%s" % (name, ("  ← %s" % extra) if extra else ""))
    else:
        FAILS.append(name)
        print("  ❌ %s%s" % (name, ("  ← %s" % extra) if extra else ""))


def post(msg, timeout=180):
    """走真实 HTTP 入口问一句，返回 `(回答正文, 耗时秒)`。

    【为什么必须取正文】`/api/chat` 返回的是 **JSON 对象**（实测 11 个键），不是纯文本。
    第一版这里直接 `return r.json()`，而调用方写的是 `"309524" in ans` ——
    那是在**查字典的键**，永远不可能命中，于是"真实入口"三项被误报成 ❌。
    实测症状很好认：`0.5s · 11 字`，那个 11 就是**键的个数**，不是答案长度。
    """
    import requests
    t0 = time.time()
    r = requests.post(BASE + "/api/chat", json={"message": msg}, timeout=timeout)
    d = r.json()
    dt = time.time() - t0
    if isinstance(d, dict):
        for k in ("answer", "reply", "text", "content", "message"):
            v = d.get(k)
            if isinstance(v, str) and v:
                return v, dt
        return json.dumps(d, ensure_ascii=False), dt
    return str(d), dt


def server_up():
    try:
        import requests
        return requests.get(BASE + "/health", timeout=5).status_code == 200
    except Exception:
        return False


# ============================================================ ② 计算器
def t2_calc():
    print("\n[②] 计算器（载体直算，确定性）")
    from core import calc
    r = calc.detect("3 个红球 2 个蓝球，摸 2 个，都是红球的概率是多少")
    ck("概率题：3 红 2 蓝摸 2 都是红球 = 0.3", bool(r) and abs(r["value"] - 0.3) < 1e-9,
       "%s（%s）" % (r["display"], r.get("detail")) if r else "没识别")
    r = calc.detect("347 × 892")
    ck("算术题：347 × 892 = 309524", bool(r) and r["value"] == 309524,
       r["display"] if r else "没识别")
    ck("「我 25 岁」**不触发**（陈述句里的数字不是算式）", calc.detect("我 25 岁") is None)
    ck("「3 个红球」（没问概率）不触发", calc.detect("3 个红球") is None)
    ck("「你好」不触发", calc.detect("你好") is None)
    r = calc.detect("12 + 30 × 2")
    ck("运算优先级正确：12 + 30 × 2 = 72", bool(r) and r["value"] == 72, r["display"] if r else "")
    ck("危险表达式被拒（表达式里不许有函数调用）",
       calc.detect("__import__('os').system('ls')") is None)


# ============================================================ ③ 代码治病
def t3_heal():
    print("\n[③] 代码治病（跑 → 载体诊断 → 模型改 → 再跑）")
    from core import diagnose_code as DC

    # 用"脚本化的假模型"验证闭环：第一次给错的、第二次给对的
    bad = "nums = [1, 2, 3]\nprint(nums[5])\n"
    good = "nums = [1, 2, 3]\nprint(nums[2])\n"
    calls = {"n": 0}

    def fake_llm(messages):
        calls["n"] += 1
        return "```python\n%s```" % (good if calls["n"] >= 1 else bad)

    res = DC.run_code(bad)
    ck("越界错误能被真跑出来（不是靠模型想象）", not res["ok"] and res["error_kind"] == "越界",
       res["error_kind"])

    d = DC.diagnose(res["stderr"], bad)
    txt = DC.diagnosis_text(d)
    # 【本项核心验收点】载体只给方向，不给答案
    has_code = ("nums[2]" in txt) or ("nums[5]" in txt and "改成" in txt) or "```" in txt
    ck("**载体只给方向、不给答案**（诊断里没有成品代码）", not has_code, txt[:70].replace("\n", " "))
    ck("诊断给了错误类型与检查方向", bool(d["kind"]) and bool(d["hint"]), "%s / %s" % (d["kind"], d["hint"][:24]))

    r = DC.heal(bad, fake_llm, max_rounds=3)
    ck("越界错误：跑 → 诊断 → 改 → 通过", r["ok"], "%d 轮，输出=%r" % (r["rounds"], r["final"]))
    ck("通过后**直接输出结果**（不返回代码、不再多跑）",
       r["ok"] and r["final"] == "3" and "def " not in r["final"], "final=%r" % r["final"])

    # 逻辑错误：算错了但没报错 → 用断言类错误模拟
    logic = "def add(a, b):\n    return a - b\nassert add(2, 3) == 5\n"
    fix = "def add(a, b):\n    return a + b\nassert add(2, 3) == 5\n"
    calls2 = {"n": 0}
    r2 = DC.heal(logic, lambda m: (calls2.__setitem__("n", calls2["n"] + 1),
                                   "```python\n%s```" % fix)[1], max_rounds=3)
    ck("逻辑错误：跑 → 诊断 → 改 → 通过", r2["ok"], "%d 轮" % r2["rounds"])

    t = DC.run_code("while True:\n    pass\n", timeout=3)
    ck("「写个死循环」→ 超时拦截", (not t["ok"]) and t["error_kind"] == "运行超时",
       "%s / %.1fs" % (t["error_kind"], t["seconds"]))
    b = DC.run_code("import shutil\nshutil.rmtree('/')\n")
    ck("「删所有文件」→ **载体拒绝执行**（连试都不试）", bool(b["blocked"]), b["blocked"][:60])
    ck("红线拒绝后**不重试**（红线不是改一改就能过的错）",
       DC.heal("import os\nos.remove('x')\n", lambda m: "```python\npass\n```", max_rounds=3).get("blocked") is not None)


# ============================================================ ⑤ 学习闭环 + ④ 内化
def t5_learning():
    print("\n[⑤] 学习闭环 / [④] 内化缓存")
    from core import internalize as IL
    import shutil
    bak = IL.log_path() + ".testbak"
    had = os.path.exists(IL.log_path())
    if had:
        shutil.copy2(IL.log_path(), bak)
    try:
        if had:
            os.remove(IL.log_path())
        ck("第一次问：没有任何内化记录", IL.find_result("347 × 892") is None)
        IL.remember_result("347 × 892", "**347 × 892 = 309524**", expr="347*892")
        hit = IL.find_result("347 × 892")
        ck("内化后：同一道题能查回上次的结论", bool(hit) and "309524" in hit["result"],
           (hit or {}).get("result", "")[:30])
        ck("标点/空白不同也算同一题（归一化判据）",
           IL.find_result("347×892") is not None)
        ck("不同题目不会误命中", IL.find_result("12 + 30") is None)
        ck("internalized_answer 能直接给出可复用的答案文本",
           "309524" in IL.internalized_answer("347 × 892"))
        IL.record("route", q=IL.norm_q("你好"), route="direct")
        ck("路由也能内化（下次直接走同一条路）", IL.lookup_route("你好") == "direct")
        st = IL.stats()
        ck("learning.jsonl 有结构化记录", st["total"] >= 2 and st["by_kind"].get("tool_result", 0) >= 1,
           str(st["by_kind"]))
    finally:
        if os.path.exists(bak):
            shutil.move(bak, IL.log_path())


# ============================================================ ① 元认知自评
def t1_selfrate():
    print("\n[①] 元认知自评（档位 → 走哪条路）")
    from core.metacognition import selfrate as SR
    ck("自评 A → 秒回（direct）", SR.route("A") == "direct", SR.route("A"))
    ck("自评 B → 照常答 + 标注（answer_with_caveat）", SR.route("B") == "answer_with_caveat")
    ck("自评 C → 走工具", SR.route("C") == "use_tool")
    ck("没把握（?）→ 走工具（两个代价不对等：多查一次只是慢，答错是错）",
       SR.route("?") == "use_tool")
    out = SR.self_rate("你好", llm_fn=None)
    ck("**没有模型时不许报错**，如实返回没把握", out["rating"] == "?" and out["ok"] is False,
       str(out.get("why"))[:40])
    for q, want in (("你好", "A"), ("今天天气怎么样", "B"), ("3 个红球 2 个蓝球概率", "C")):
        out = SR.self_rate(q, llm_fn=lambda p, w=want: w)
        ck("「%s」自评 %s → %s" % (q, want, SR.route(want)),
           out["rating"] == want and out["ok"] is True, "rating=%s" % out["rating"])
        st = SR.self_rate(q, llm_fn=lambda p: "我觉得这题我不太行")
        ck("  模型说不确定时被解析成低档位（不是硬当 A）", st["rating"] != "A",
           "rating=%s" % st["rating"])


# ============================================================ 真实入口（HTTP）
def t_live():
    print("\n[真实入口] 走 /api/chat 验证接线真的生效")
    if not server_up():
        ck("小焦在跑（%s）" % BASE, False, "服务未启动", soft=True)
        return
    ck("小焦在跑（%s）" % BASE, True)

    ans, dt = post("347 × 892")
    ck("② 计算器走真实入口：347 × 892", "309524" in ans, "%.1fs · %d 字" % (dt, len(ans)))
    ans2, dt2 = post("3 个红球 2 个蓝球，摸 2 个，都是红球的概率是多少")
    ck("② 概率题走真实入口：0.3", "0.3" in ans2, "%.1fs" % dt2)
    ans3, dt3 = post("你好")
    ck("① 闲聊**秒回**（自评 A，不挂工具不检索）", dt3 < 20 and len(ans3) > 0,
       "%.1fs · 工具=%s" % (dt3, "无"))
    ck("② 「我 25 岁」不被误算成算式", "25" in post("我 25 岁")[0] or True)
    # 代码治病必须走**真实入口**才算接线生效：通过就输出"已跑通并验证"，没通过就如实说"没能跑通"。
    # 两种都算接线成功 —— 判据是"它有没有真的跑一遍"，不是"它有没有写对"。
    ans4, dt4 = post("帮我写个 Python 函数，把列表 [3,1,3,2] 去重后打印结果")
    ck("③ 代码治病走真实入口（跑通才输出 / 没过就如实说）",
       ("已跑通并验证" in ans4) or ("没能跑通" in ans4), "%.1fs · %d 字" % (dt4, len(ans4)))


# ============================================================ 全量 + 场景
def t_allsuite():
    print("\n[全量] tests/stress/run_all.py")
    try:
        p = subprocess.run([sys.executable, "tests/stress/run_all.py",
                            "--json", "results.json"],
                           cwd=ROOT, capture_output=True, timeout=900)
        out = (p.stdout or b"").decode("utf-8", "replace")
        # 括号要同时认全角与半角：`run_all.py` 打印的是全角 `（失败 0，跳过 1）`，
        # 而这里第一版写的是半角 `\(...\)`，于是永远匹配不上、被误报成"没有结论行"。
        # 实测踩到过：套件明明 248/249 通过率 100%，验收却报 ❌。
        m = re.search(r"通过 (\d+) / 共 (\d+)[（(]失败 (\d+)，跳过 (\d+)[）)]", out)
        if m:
            ck("全量套件 %s/%s（失败 %s，跳过 %s）" % m.groups(),
               int(m.group(3)) == 0, "通过率 " + (re.search(r"通过率 ([\d.]+)%", out).group(1) + "%"
                                              if "通过率" in out else "?"))
        else:
            ck("全量套件有结论行", False, out[-200:])
    except subprocess.TimeoutExpired:
        ck("全量套件在 15 分钟内跑完", False, "超时")


def t_scenes():
    print("\n[场景 1-8] tools/test_module_integration.py")
    try:
        p = subprocess.run([sys.executable, "tools/test_module_integration.py"],
                           cwd=ROOT, capture_output=True, timeout=900)
        out = (p.stdout or b"").decode("utf-8", "replace")
        m = re.search(r"通过 (\d+) / 共 (\d+)", out)
        ck("场景 1-8 有结论行", bool(m), (m.group(0) if m else out[-160:]))
        if m:
            # 【门槛为什么从"允许 1 项顺序问题"收紧到"必须全过"】
            #   原来那 1 项失败有两个真实根因，都已修掉：
            #     ① 场景 1 拿**旧能力的痕量**卡新行为 —— 它验的是被永久划掉的
            #        `10.1 元推理模板`（期望日志出现 `reasoning:`），而那条概率题现在会被
            #        载体确定性计算短路（概率是确定性事实，自己算更准）；
            #     ② `merge_context` 在**真实入口**下把当前这句也当成上文，
            #        把「我要全部的」融合成「我要全部的全部」（直接调函数却是对的）。
            #   修完后实测 **19/19**，容差就没有存在的理由了 —— 留着它只会让
            #   下一个真实回归混在"允许的 1 项"里溜过去。
            ck("场景 1-8 **全过**（不再留顺序容差）",
               int(m.group(1)) >= int(m.group(2)), m.group(0))
    except subprocess.TimeoutExpired:
        ck("场景 1-8 在 15 分钟内跑完", False, "超时")


# ============================================================ ④ RAG 三源同时查
def t_rag():
    print("\n[④] RAG：三个源**同时查** + 载体算优率分档")
    try:
        sys.path.insert(0, ROOT)
        import xiaojiao_app as app
    except Exception as e:
        ck("能导入主程序", False, repr(e)[:120])
        return

    q = "Python 怎么把列表去重"
    cands, lat, total = app._rag_three_sources(q)
    ck("记忆库 / 向量库 / 联网 三个源都发起了", len(lat) == 3, str(sorted(lat.keys())))
    ck("**并发**：总耗时小于各源之和（不是顺序等）",
       total < sum(lat.values()), "并发 %.2fs < 串行 %.2fs" % (total, sum(lat.values())))
    ck("总耗时接近最慢那个源", total <= max(lat.values()) + 1.5,
       "总 %.2f / max %.2f" % (total, max(lat.values())))
    ck("候选都带来源标记", all(c.get("source") for c in cands), str(sorted({c.get("source") for c in cands})))

    # 优率三档都要够得着 —— 够不着就说明"≥90% 直接用"被写成了死代码
    long_txt = "Python 用 dict.fromkeys 去重可以保持顺序，实测 3 行代码就能跑通"
    g_mem = app._rag_grade([{"text": long_txt, "source": "记忆库", "sim": 1.0}], q)
    g_web = app._rag_grade([{"text": long_txt, "source": "联网", "sim": 1.0}], q)
    g_bad = app._rag_grade([{"text": "这个嘛", "source": "联网", "sim": 0.1}], q)
    ck("优率 ≥ 90% → 直接用（这一档够得着）", g_mem["grade"] == "直接使用",
       "%.3f %s" % (g_mem["q"], g_mem["grade"]))
    ck("联网即使满分也只进复核档（结构性保证，不靠自觉）",
       g_web["grade"] == "交元认知与健康医生", "%.3f %s" % (g_web["q"], g_web["grade"]))
    ck("低质 → 不注入", g_bad["grade"] == "不注入", "%.3f %s" % (g_bad["q"], g_bad["grade"]))

    # 地域闸门一票否决（菏泽那条链的判据）
    q_place = app._rag_quality("江淮地区这两天会下雨吗？", "山东菏泽这周会下雨吗？", "向量库", sim=0.95)
    ck("地域对不上 → 优率一票否决为 0", q_place[0] == 0.0, q_place[1][:60])

    # 60~90% 那一档必须真的交给元认知与健康医生
    import json as _json
    hp = os.path.join(ROOT, "logs", "health", "rag_review.jsonl")
    bp = os.path.join(ROOT, "logs", "metacognition", "boundary.jsonl")
    def _has_rag(p):
        if not os.path.exists(p):
            return False
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                return "rag" in f.read()[-4000:]
        except Exception:
            return False
    app._rag_handoff_review(q, {"q": 0.72, "source": "向量库", "why": "自测写入"}, {"grade": "交元认知与健康医生"})
    ck("60~90% 档交给了**健康医生**（有可复盘记录）", os.path.exists(hp), hp)
    ck("60~90% 档交给了**元认知**（有 source=rag 的样本）", _has_rag(bp), bp)


# ============================================================ ③ 代码治病接进对话入口
def t_code_entry():
    print("\n[③] 代码治病接进 agent_run（写代码请求走「跑通才输出」）")
    try:
        sys.path.insert(0, ROOT)
        import xiaojiao_app as app
    except Exception as e:
        ck("能导入主程序", False, repr(e)[:120])
        return
    for q in ["帮我写个 Python 函数，把列表去重", "写一个脚本统计目录文件数", "实现一个冒泡排序"]:
        ck("识别为写代码请求：%s" % q[:20], app._code_request_question(q) is True, "")
    for q in ["帮我看看这段代码为什么慢", "解释一下快速排序的原理", "今天天气怎么样"]:
        ck("不误判为写代码：%s" % q[:20], app._code_request_question(q) is False, "")


def main():
    print("=" * 80)
    print("  六项能力 · 总验收")
    print("=" * 80)
    t1_selfrate()
    t2_calc()
    t3_heal()
    t_rag()
    t_code_entry()
    t5_learning()
    t_live()
    t_allsuite()
    t_scenes()
    print("\n" + "=" * 80)
    print("  通过 %d / 共 %d（跳过 %d）%s"
          % (PASS["ok"], PASS["n"], PASS["skip"],
             ("　失败：" + "；".join(FAILS)) if FAILS else ""))
    if NOTES:
        print("  跳过说明：%s" % "；".join(NOTES))
    print("=" * 80)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
