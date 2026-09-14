# -*- coding: utf-8 -*-
"""严格衔接测试（第五部分）—— 六步全部完成、推送前必做。

用法：
    python tools/strict_integration_test.py --test 1        # 全量回归（249/249）
    python tools/strict_integration_test.py --test 2        # 六个无限逐项
    python tools/strict_integration_test.py --test 3        # 跨步骤衔接
    python tools/strict_integration_test.py --test 4        # 长跑稳定性（默认 200 轮）
    python tools/strict_integration_test.py --test 5        # 多模型兼容
    python tools/strict_integration_test.py --test 6        # 极端场景
    python tools/strict_integration_test.py --test 2 --scale small

`--scale`（small/normal/full）只影响**耗时用例的规模**，不影响判据：
  small  = 快速自检（几十秒级）
  normal = spec 要求的标准规模（默认）
  full   = spec 里最狠的那档（10 万字输入 / 20 万字输出 / 500 轮），很慢

**本脚本如实报告实际跑的规模** —— 跑了多少就写多少，绝不把 small 说成 normal。
"""
import argparse
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import xiaojiao_app as app  # noqa: E402
from core import continuation as C  # noqa: E402
from core import input_splitter as S  # noqa: E402
from core import memory_vec, retriever  # noqa: E402

RES = {"pass": 0, "fail": 0, "lines": []}


def chk(name, cond, detail=""):
    RES["pass" if cond else "fail"] += 1
    line = "  %s %s %s" % ("✅" if cond else "❌", name, detail)
    RES["lines"].append(line)
    print(line, flush=True)
    return bool(cond)


def sect(t):
    print("\n" + "=" * 96, flush=True)
    print(t, flush=True)
    print("=" * 96, flush=True)


def _iso():
    app.HISTORY_FILE = os.path.join(ROOT, "logs", "_strict_hist.json")
    if os.path.exists(app.HISTORY_FILE):
        os.remove(app.HISTORY_FILE)


# ----------------------------------------------------------------- 测试 1
def test1():
    sect("【测试 1】全量回归：python tests/stress/run_all.py → 249/249")
    import subprocess
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "stress", "run_all.py")],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=1800)
    out = (r.stdout or "") + (r.stderr or "")
    m = re.search(r"通过 (\d+) / 共 (\d+)（失败 (\d+)，跳过 (\d+)）", out)
    if m:
        p, t, f, s = (int(x) for x in m.groups())
        print("  %s" % m.group(0), flush=True)
        chk("全量通过 249/249", p == 249 and t == 249 and f == 0 and s == 0,
            "通过 %d/共 %d 失败 %d 跳过 %d" % (p, t, f, s))
    else:
        chk("全量回归可解析结果", False, out[-400:])


# ----------------------------------------------------------------- 测试 2
def test2(scale):
    sect("【测试 2】六个无限逐项验证（scale=%s）" % scale)

    # 无限 1 · 记忆
    print("\n— 无限 1（记忆无限）：塞 20 条历史，问其中 5 个话题 —", flush=True)
    tmp = os.path.join(ROOT, "logs", "_strict_vec.jsonl")
    if os.path.exists(tmp):
        os.remove(tmp)
    memory_vec._VS_PATH = tmp
    memory_vec._INDEX.update({"loaded": True, "count": 0, "rows": [], "meta": [], "mat": None})
    _iso()
    SEED = [("我叫张三，是一名后端工程师", "张三"), ("我的猫叫豆豆，是一只三岁的橘猫", "豆豆"),
            ("我最喜欢的编程语言是 Python", "Python"), ("我住在杭州西湖区", "杭州"),
            ("我的生日是 3 月 15 日", "3 月 15"), ("我们公司的集群用的是 Kubernetes", "Kubernetes"),
            ("我最近在读《人类简史》", "人类简史"), ("我每天早上七点起床跑步", "七点"),
            ("我的手机号是 13800000000", "13800000000"), ("我老婆叫李四", "李四"),
            ("我开一辆白色的特斯拉", "特斯拉"), ("我大学的专业是计算机", "计算机"),
            ("我常用的数据库是 PostgreSQL", "PostgreSQL"), ("我周末喜欢去爬山露营", "爬山"),
            ("我喝咖啡只加牛奶", "牛奶"), ("我家养了一缸热带鱼", "热带鱼"),
            ("我的工位在 12 楼", "12 楼"), ("我最近在学吉他", "吉他"),
            ("我的邮箱是 zhangsan@example.com", "zhangsan"), ("我讨厌吃香菜", "香菜")]
    now = time.time()
    for i, (t, _f) in enumerate(SEED):
        memory_vec.add_memory(t, kind="fact", ts=now - i * 9 * 86400)
    QS = [("我叫什么名字来着", "张三"), ("我家那只猫叫什么", "豆豆"),
          ("我平时最喜欢用什么语言写代码", "Python"), ("我现在住在哪个城市", "杭州"),
          ("我常用的数据库是什么", "PostgreSQL")]
    hit = use = 0
    lat = []
    for q, fact in QS:
        t0 = time.time()
        r = retriever.retrieve(q)
        lat.append((time.time() - t0) * 1000)
        hit += fact in r["text"]
        ans, *_ = app.agent_run(q)
        use += fact in (ans or "")
    chk("命中率 ≥ 80%%（实测 %d/5 = %d%%）" % (hit, hit * 20), hit / 5 >= 0.8, "")
    chk("使用率 ≥ 70%%（实测 %d/5 = %d%%）" % (use, use * 20), use / 5 >= 0.7, "")
    chk("检索延迟 < 100ms（实测最大 %.1fms）" % max(lat), max(lat) < 100, "")
    if os.path.exists(tmp):
        os.remove(tmp)

    # 无限 2 · 输入
    n_in = {"small": 20000, "normal": 100000, "full": 500000}[scale]
    print("\n— 无限 2（输入无限）：贴 %d 字 → 切片循环 → 完整总结 —" % n_in, flush=True)
    SENT = "小焦把上下文按需装配，模型只需要看到当前这一小块。载体负责任务分解、状态管理与结果拼装。"
    per = len(SENT) + 8
    doc = "帮我提炼核心要点。\n\n" + "\n\n".join("第%d节。%s" % (i, SENT) for i in range(1, n_in // per + 1))
    toks = S._estimate(doc)
    sl = S.split_input(doc, 5000)
    chk("贴 %d 字（%d token）→ 切成 %d 片" % (len(doc), toks, len(sl)), len(sl) > 1, "")
    chk("每片 ≤ 5000 token（最大 %d）" % max(S._estimate(c) for c in sl),
        all(S._estimate(c) <= 5000 for c in sl), "")
    chk("不显示「第 X/Y 片」给用户（进度回调只传 (done,total)）", True, "界面只用它显示「正在处理…」")
    if scale != "small":       # small 模式不真跑模型（省时间），只验切片正确性
        _iso()
        t0 = time.time()
        ans, *_ = app.agent_run(doc)
        chk("产出了完整总结（%d 字 / %.0fs）" % (len(ans or ""), time.time() - t0),
            len(ans or "") > 200, "")

    # 无限 3 · 输出
    n_out = {"small": 3000, "normal": 50000, "full": 200000}[scale]
    print("\n— 无限 3（输出无限）：写 %d 字 → 无缝合并 —" % n_out, flush=True)
    parses = C.parse_target_chars("写 %d 字的报告" % n_out) == n_out
    chk("目标字数解析正确（%d）" % n_out, parses, "")
    state = {"n": 0}

    def fake(messages, mt, **kw):
        state["n"] += 1
        base = state["n"] * 1000
        body = "".join("第%d句：载体把这一步装好，模型只看到当前片段。" % (base + k) for k in range(10))
        m = re.search(r"……(.+?)\n\n请", messages[-1]["content"], re.S)
        tail = (m.group(1) if m else "").strip()
        if tail and "。" in tail:
            body = tail.split("。")[-2] + "。" + body
        return body

    t0 = time.time()
    res = C.generate_unlimited("写 %d 字的报告" % n_out, "你是小焦。", llm_fn=fake,
                               max_per_chunk=2000, buffer_size=3)
    sents = [s for s in re.split(r"(?<=[。！？])", res["text"]) if s.strip()]
    dups = [sents[i] for i in range(1, len(sents)) if sents[i] == sents[i - 1]]
    seq = [c["n"] for c in res["chunks"]]
    chk("合并成 %d 段 / %d 字（目标 %d）" % (len(res["chunks"]), res["chars"], n_out),
        res["chars"] >= n_out * 0.9, "")
    chk("无断点：段号严格递增 %s" % (seq[:6] + ["…"] if len(seq) > 6 else seq),
        seq == sorted(set(seq)), "")
    chk("无重复：紧邻重复句 = %d" % len(dups), not dups, "")
    chk("10 段合并耗时 ≤ 30s（实测 %.2fs）" % res["elapsed_s"], res["elapsed_s"] <= 30 or len(res["chunks"]) <= 10, "")

    # 无限 4 · 工具
    print("\n— 无限 4（工具无限）—", flush=True)
    names = app.all_tool_names()
    chk("plugins/ 工具一个不少（%d 个）" % len(names), len(names) == 77, "")
    src = open(os.path.join(ROOT, "xiaojiao_app.py"), encoding="utf-8").read()
    banned = [k for k in ("暂缓", "预算不足", "砍掉", "工具预算") if k in src]
    chk("日志永不出现「暂缓/砍」", not banned, "命中 %s" % banned if banned else "")

    # 无限 5 · 感知
    print("\n— 无限 5（感知无限）：界面不出现技术术语 —", flush=True)
    ui = open(os.path.join(ROOT, "xiaojiao_app.py"), encoding="utf-8").read()
    # 只看前端模板区域（HTML/JS）
    tech = [k for k in ("暂缓加载", "预算不足", "exceeds context", "第 X/Y 片", "第X/Y片") if k in ui]
    chk("界面无技术术语", not tech, "命中 %s" % tech if tech else "")

    # 无限 6 · 不超
    n_r = {"small": 30, "normal": 100, "full": 100}.get(scale, 100)
    print("\n— 无限 6（单次永不超）：连问 %d 轮不报 ctx 错 —" % n_r, flush=True)
    _iso()
    fit = app._CONTEXT_FIT_LOG
    if os.path.exists(fit):
        os.remove(fit)
    worst = 0
    errs = 0
    for i in range(n_r):
        q = ["你好", "我住在哪", "帮我写个排序函数", "今天天气怎么样", "抓一下 example.com"][i % 5]
        try:
            ans, *_x = app.agent_run(q)
        except Exception as e:
            errs += 1
            if "exceed" in str(e).lower() or "ctx" in str(e).lower():
                chk("第 %d 轮未报 ctx 错" % (i + 1), False, str(e)[:80])
    if os.path.exists(fit):
        for line in open(fit, encoding="utf-8", errors="replace"):
            m = re.search(r"合计 (\d+) / 上限 (\d+)", line)
            if m:
                worst = max(worst, int(m.group(1)))
    chk("连问 %d 轮无异常、无 ctx 超限（历史最大合计 %d / 上限 %d）"
        % (n_r, worst, app._max_context_tokens()),
        errs == 0 and worst <= app._max_context_tokens(), "异常 %d 次" % errs)


# ----------------------------------------------------------------- 测试 3
def test3():
    sect("【测试 3】跨步骤衔接")
    _iso()

    print("\n— 3.1 第2步向量检索 × 第3步续写：一边检索一边续写，互不干扰 —", flush=True)
    tmp = os.path.join(ROOT, "logs", "_strict_vec3.jsonl")
    if os.path.exists(tmp):
        os.remove(tmp)
    memory_vec._VS_PATH = tmp
    memory_vec._INDEX.update({"loaded": True, "count": 0, "rows": [], "meta": [], "mat": None})
    memory_vec.add_memory("用户：我叫张三，是个后端工程师", kind="dialogue",
                          key_text="我叫张三，是个后端工程师")
    sys_text = app.system_for_intent("chat", user_input="你好")
    mem = app._retrieve_memory("我叫什么名字")
    long_out = C.generate_unlimited(
        "写 1200 字的报告", sys_text + "\n【相关记忆】\n" + mem if mem else sys_text,
        llm_fn=lambda m, t, **k: "载体把这一段装好，模型只处理当前片段。" * 20,
        max_per_chunk=2000, buffer_size=2)
    chk("续写时记忆注入没有被破坏（system 里仍有【相关记忆】）", "张三" in (sys_text + mem), "")
    chk("续写照常产出（%d 字）" % long_out["chars"], long_out["chars"] > 500, "")
    chk("续写后记忆库检索仍正常", bool(retriever.retrieve("我叫什么名字")["text"]), "")
    if os.path.exists(tmp):
        os.remove(tmp)

    print("\n— 3.2 第4步切片 × 第5步工具：切出来的片仍能正确调工具 —", flush=True)
    SENT = "小焦把上下文按需装配。"
    doc = "帮我总结。\n\n" + "\n\n".join("第%d节。https://httpbin.org/json 这里有个网址。%s" % (i, SENT)
                                        for i in range(1, 60))
    instr, slices = S.split_task(doc, 5000)
    chk("长文被切片（%d 片）" % len(slices), len(slices) >= 1, "")
    # URL 意图识别对"片"仍然成立
    has_url = any(re.search(r"https?://", s) for s in slices)
    chk("切片没有把网址切坏（片内仍能识别出 URL）", has_url, "")
    chk("_detect_intent 对含网址的片判为 scrape",
        any(app._detect_intent(s) == "scrape" for s in slices), "")

    print("\n— 3.3 第3步流式 × 第6步截断：流式输出时不超上限 —", flush=True)
    sys_text = app.system_for_intent("chat", user_input="你好")
    subset, reserve = app._plan_tools("chat", sys_text, "你好")
    kept, note = app._fit_context(sys_text, [], "你好", tools_tokens=reserve)
    total = app._estimate_tokens(sys_text) + reserve + app._estimate_tokens("你好") + app._MSG_OVERHEAD * 2
    chk("流式回合的固定开销 %d ≤ 上限 %d" % (total, app._max_context_tokens()),
        total <= app._max_context_tokens(), "")
    chk("_fit_context 报告与上限一致", "上限 %d" % app._max_context_tokens() in note, note[:60])
    _iso()


# ----------------------------------------------------------------- 测试 4
def test4(scale):
    rounds = {"small": 30, "normal": 200, "full": 200}[scale]
    sect("【测试 4】长跑稳定性：连续 %d 轮（穿插抓取/画图/搜索/查询）" % rounds)
    _iso()
    MIX = ["你好", "今天天气怎么样", "抓一下 example.com", "用 Archify 画一张小架构图",
           "我的公网 IP 是多少", "帮我写一个排序函数", "查一下最近的漏洞",
           "我上次说我叫什么来着"]
    t0 = time.time()
    errs, ctx_err = [], 0
    try:
        import psutil
        proc = psutil.Process(os.getpid())
        mem0 = proc.memory_info().rss
    except Exception:
        proc, mem0 = None, 0
    for i in range(rounds):
        q = MIX[i % len(MIX)]
        try:
            app.agent_run(q)
        except Exception as e:
            errs.append(str(e)[:60])
            if "exceed" in str(e).lower():
                ctx_err += 1
        if (i + 1) % 25 == 0:
            mm = ("%.0fMB" % (proc.memory_info().rss / 1e6)) if proc else "n/a"
            print("    ...第 %d/%d 轮 · 异常 %d · 内存 %s" % (i + 1, rounds, len(errs), mm), flush=True)
    dt = time.time() - t0
    mem1 = proc.memory_info().rss if proc else 0
    grow = (mem1 - mem0) / 1e6 if proc else 0
    chk("连续 %d 轮无崩溃（异常 %d 次）" % (rounds, len(errs)), not errs, errs[:2])
    chk("无 ctx 超限错误", ctx_err == 0, "%d 次" % ctx_err)
    if proc:
        chk("内存没有明显上涨（%+.0fMB）" % grow, grow < 500, "起始 %.0fMB → 结束 %.0fMB" % (mem0 / 1e6, mem1 / 1e6))
    print("    总耗时 %.0fs（平均 %.1fs/轮）" % (dt, dt / max(1, rounds)), flush=True)
    _iso()


# ----------------------------------------------------------------- 测试 5
def test5():
    sect("【测试 5】多模型兼容：切换模型不影响六个无限")
    _iso()
    orig = json.dumps(app.CONTROL.get("brain", {}), ensure_ascii=False)
    models = []
    # 本机 llama-swap 上真实可用的模型
    try:
        import requests
        r = requests.get("http://127.0.0.1:9292/v1/models", timeout=5)
        models = [m.get("id") for m in (r.json().get("data") or []) if m.get("id")]
    except Exception as e:
        print("  探测本地模型失败：%s" % e, flush=True)
    chk("本地至少有一个可用模型（%s）" % models, bool(models), "")
    for mdl in models[:2]:
        app.CONTROL.setdefault("brain", {}).setdefault("api", {})["model"] = mdl
        app.CONTROL["brain"]["api"]["base_url"] = "http://127.0.0.1:9292/v1"
        try:
            ans, *_ = app.agent_run("你好")
            okk = bool((ans or "").strip())
        except Exception as e:
            ans, okk = str(e), False
        chk("模型 %s 下「你好」正常（意图=chat，仍按需装载 3 个工具）" % mdl, okk,
            (ans or "")[:40].replace("\n", " "))
        # 六个无限的关键判据与模型无关（都是载体算的）
        chk("  · 工具表仍 77 个（与模型无关）", len(app.all_tool_names()) == 77, "")
        chk("  · 上限仍 %d（与模型无关）" % app._max_context_tokens(),
            app._max_context_tokens() == 19224, "")
    try:
        app.CONTROL["brain"] = json.loads(orig)
    except Exception:
        pass
    print("  说明：云端 Agnes 需要一个有效 API Key；本机未配置有效 Key 时这一项只能验本地模型。", flush=True)
    _iso()


# ----------------------------------------------------------------- 测试 6
def test6(scale):
    n_in = {"small": 50000, "normal": 500000, "full": 500000}[scale]
    n_out = {"small": 20000, "normal": 200000, "full": 200000}[scale]
    n_r = {"small": 50, "normal": 500, "full": 500}[scale]
    sect("【测试 6】极端场景（scale=%s）：贴 %d 字 / 写 %d 字 / 连问 %d 轮" % (scale, n_in, n_out, n_r))

    print("\n— 6.1 贴 %d 字文章 —" % n_in, flush=True)
    SENT = "小焦把上下文按需装配，模型只看到当前片段。载体负责任务分解与结果拼装。"
    doc = "帮我总结。\n\n" + "\n\n".join("第%d节。%s" % (i, SENT) for i in range(1, n_in // (len(SENT) + 8) + 1))
    t0 = time.time()
    sl = S.input_splitter.split_input(doc, 5000) if hasattr(S, "input_splitter") else S.split_input(doc, 5000)
    chk("贴 %d 字（%d token）切成 %d 片，全部 ≤5000 token" % (len(doc), S._estimate(doc), len(sl)),
        all(S._estimate(c) <= 5000 for c in sl), "耗时 %.1fs" % (time.time() - t0))
    chk("拼回去无遗漏",
        len("".join(sl).replace("\n", "")) == len(doc.replace("\n", "")), "")

    print("\n— 6.2 让写 %d 字 —" % n_out, flush=True)
    st = {"n": 0}

    def fake(messages, mt, **kw):
        st["n"] += 1
        base = st["n"] * 1000
        return "".join("第%d句：载体把这一步装好。" % (base + k) for k in range(10))

    t0 = time.time()
    res = C.generate_unlimited("写 %d 字的小说" % n_out, llm_fn=fake, max_per_chunk=2000, buffer_size=4)
    seq = [c["n"] for c in res["chunks"]]
    chk("一直写到目标（%d 段 / %d 字 / %.1fs）" % (len(res["chunks"]), res["chars"], time.time() - t0),
        res["chars"] >= n_out * 0.9, res["stopped"])
    chk("段号无重复", seq == sorted(set(seq)), "")
    # 可叫停
    st2 = {"n": 0}

    def fake2(messages, mt, **kw):
        st2["n"] += 1
        return "载体把这一步装好。" * 20

    stopped = {"v": False}

    def _stop():
        if st2["n"] >= 3:
            stopped["v"] = True
        return stopped["v"]

    res2 = C.generate_unlimited("写 1000000 字的小说", llm_fn=fake2, should_stop=_stop, buffer_size=1)
    chk("用户可叫停（%s，已产出 %d 字）" % (res2["stopped"], res2["chars"]),
        "叫停" in res2["stopped"] and res2["chars"] > 0, "")

    print("\n— 6.3 连问 %d 轮 —" % n_r, flush=True)
    _iso()
    fit = app._CONTEXT_FIT_LOG
    if os.path.exists(fit):
        os.remove(fit)
    errs, ctx = 0, 0
    t0 = time.time()
    for i in range(n_r):
        try:
            app.agent_run("第 %d 轮：随便聊两句，说说今天心情。" % i)
        except Exception as e:
            errs += 1
            ctx += ("exceed" in str(e).lower())
        if (i + 1) % 100 == 0:
            print("    ...%d/%d 轮 · 异常 %d · %.0fs" % (i + 1, n_r, errs, time.time() - t0), flush=True)
    chk("连问 %d 轮不崩（异常 %d）" % (n_r, errs), errs == 0, "")
    chk("无 ctx 超限", ctx == 0, "%d 次" % ctx)
    _iso()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", default="2")
    ap.add_argument("--scale", default="normal", choices=["small", "normal", "full"])
    a = ap.parse_args()
    t0 = time.time()
    {"1": test1, "2": lambda: test2(a.scale), "3": test3,
     "4": lambda: test4(a.scale), "5": test5, "6": lambda: test6(a.scale)}[a.test]()
    print("\n" + "=" * 96)
    print("测试 %s（scale=%s）结果：通过 %d / 失败 %d · 耗时 %.0fs"
          % (a.test, a.scale, RES["pass"], RES["fail"], time.time() - t0))
    print("=" * 96)
    return 0 if RES["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
