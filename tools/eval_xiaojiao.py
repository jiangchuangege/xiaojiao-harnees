# -*- coding: utf-8 -*-
"""小焦端到端评测（2026-10-17）

【为什么要有它】项目现在有 130+ 项自测，但那些测的是"代码没坏"（函数对不对、接线在不在）。
**没有东西测"答得好不好"** —— 于是每次优化都是盲改：改完不知道是变强还是变弱。
这个脚本就是那把尺子。

分两层，如实标注：
  · **离线层**（不用模型，秒级）：判据、路由、隔离、去噪、落盘、出口校验 —— 确定性可复现。
  · **在线层**（真调 :5000 的模型）：真实问句端到端跑一遍，按"工具对不对 / 有没有编 / 快不快"打分。
     这一层**会波动**（模型有随机性、网络会抽），所以它是"趋势指标"，不是"定理"。

用法：
    python tools/eval_xiaojiao.py --offline        # 只跑离线层（几秒）
    python tools/eval_xiaojiao.py                  # 离线 + 在线（在线较慢）
    python tools/eval_xiaojiao.py --online-only    # 只跑在线层
    python tools/eval_xiaojiao.py --save           # 写 docs/eval-baseline.md

判分口径（不做"差不多就行"的模糊判断）：
    pass  = 关键条件全中
    half  = 中了一部分（会列出还差什么）
    fail  = 关键条件没中（例如该查天气却去搜网页、答案里没数字、把查不到答成编的）
"""
import argparse
import io
import json
import os
import re
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

PASS, HALF, FAIL = [], [], []


def _rec(bucket, case, note):
    bucket.append({"case": case, "note": note})


def _print_row(tag, name, note):
    icon = {"pass": "✅", "half": "🟡", "fail": "❌"}[tag]
    print("  %s %-46s %s" % (icon, name[:46], note[:88]))


# ============================================================
# 离线层：判据 / 路由 / 隔离 / 去噪 / 落盘 / 出口校验
# ============================================================
OFFLINE = [
    # (名字, 断言函数名, 说明)
    ("天气：带城市被认出", "t_weather_city"),
    ("天气：不带城市被认出（问清而不是瞎答）", "t_weather_nocity"),
    ("天气：错别字「根据天去」在查过该城市后仍认出", "t_weather_typo"),
    ("天气：日照时间长（城市名当普通词）不误判", "t_weather_false_positive"),
    ("新闻：不被当成天气（不该隔离）", "t_news_not_weather"),
    ("公网 IP：命中专用工具", "t_ip"),
    ("电子书：要清单 → ebook_manifest", "t_ebook_manifest"),
    ("电子书：要下载 → ebook_grab", "t_ebook_grab"),
    ("电子书：没提书 → 不抢普通抓取", "t_ebook_not_hijack"),
    ("抓取：爬一下+下载到 → 判成抓取（不是 None）", "t_scrape_intent"),
    ("抓取：截图/监控不抢", "t_scrape_not_hijack"),
    ("落盘：从原话取出保存目录", "t_save_target"),
    ("落盘：真写文件并校验内容", "t_save_body"),
    ("隔离：命中专用 → 通用兜底被逐出", "t_isolation_out"),
    ("隔离：没命中专用 → 通用保留", "t_isolation_keep"),
    ("隔离：早返回口也过隔离（chat 意图）", "t_isolation_early_return"),
    ("工具门：没装载的工具 run_tool 拒绝", "t_gate_deny"),
    ("工具门：规划之前按原话也能拦", "t_gate_before_plan"),
    ("去噪：网页导航/图片/按钮词不进聊天", "t_display_clean"),
    ("去噪：正文一个字不改", "t_display_keep_body"),
    ("出口：⏳__pending__ 不许当回答返回", "t_answer_sane"),
    ("回灌：上一轮的失败句不进事实块", "t_mind_no_fail"),
    ("契约：每个工具都有「什么时候用」", "t_tool_desc"),
    ("路由：闲聊走最快档", "t_route_fast"),
    ("路由：写代码走 coder 档", "t_route_code"),
    ("路由：重推理且够长走 strong 档", "t_route_strong"),
    ("路由：换档有冷却（不来回切模型）", "t_route_cooldown"),
]


def _app():
    import xiaojiao_app as app
    app._build_tools()
    return app


def t_weather_city(app):
    return bool(app._weather_intent("帮我查下菏泽现在的天气"))


def t_weather_nocity(app):
    # 不带城市也要认出来（这样才会问清，而不是让模型瞎编城市）
    return bool(app._weather_intent("今天天气怎么样"))


def t_weather_typo(app):
    app._weather_note_success("菏泽", "菏泽天气：阴天 +13°C")
    ok = bool(app._weather_intent("最近去菏泽旅游根据天去是否可以去"))
    return ok


def t_weather_false_positive(app):
    # 「日照」既是城市名也是普通词；没有出行动作时不该判成问天气
    app._weather_note_success("日照", "日照天气：晴 +20°C")
    return not app._weather_intent("日照时间长适合晒被子")


def t_news_not_weather(app):
    return not app._weather_intent("最近有什么新闻")


def t_ip(app):
    from core import tool_isolation as TI
    return "net_ip" in TI.specialized_for("我的公网 IP 是多少，在哪")


def t_ebook_manifest(app):
    r = app._ebook_intent("把 https://a.com/books 的电子书书目整理成清单存到 G:\\dzs\\a.csv")
    return bool(r) and r[0] == "ebook_manifest"


def t_ebook_grab(app):
    r = app._ebook_intent("帮我下载电子书 https://a.com/books 存到 G:\\dzs")
    return bool(r) and r[0] == "ebook_grab"


def t_ebook_not_hijack(app):
    return app._ebook_intent("抓一下 https://a.com/x 看看写了啥") is None


def t_scrape_intent(app):
    r = app._detect_scrape_intent("帮我爬一下电子书https://a.com/book 下载到G:\\dzs")
    return bool(r) and r[0] == "get"


def t_scrape_not_hijack(app):
    return (app._detect_scrape_intent("把 https://a.com/x 截图") is None
            and app._detect_scrape_intent("监控 https://a.com/x 每 5 分钟") is None)


def t_save_target(app):
    return app._scrape_save_target("帮我抓 https://a.com/x 下载到 G:\\dzs") == "G:\\dzs"


def t_save_body(app):
    import tempfile
    d = tempfile.mkdtemp()
    try:
        p, _ = app._scrape_save_body("https://a.com/x.pdf", "# 标题\n正文", d)
        ok = bool(p) and os.path.isfile(p) and "正文" in io.open(p, encoding="utf-8").read()
        return ok
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


def t_isolation_out(app):
    from core import tool_isolation as TI
    keep, _ = TI.isolate("帮我查下菏泽现在的天气", ["get_weather", "web_search", "read_file"])
    return "web_search" not in keep and "get_weather" in keep


def t_isolation_keep(app):
    from core import tool_isolation as TI
    keep, _ = TI.isolate("最近有什么新闻", ["web_search", "read_file"])
    return "web_search" in keep


def t_isolation_early_return(app):
    names = app._intent_tool_names("chat", "今天天气怎么样")
    return "web_search" not in names and "get_weather" in names


def t_gate_deny(app):
    from core import tool_gate as TG
    TG.set_turn(["get_weather", "read_file"], "帮我查下菏泽现在的天气")
    ok = TG.check("web_search")[0] is False
    TG.clear()
    return ok


def t_gate_before_plan(app):
    from core import tool_gate as TG
    TG.clear()
    TG.begin_turn("今天天气怎么样")          # 还没规划工具，只记了原话
    ok = TG.check("web_search")[0] is False
    TG.clear()
    return ok


def t_display_clean(app):
    raw = ("[跳转到主内容] (#content)\n[![站标] (/logo.png)] (/)\n"
           "打开搜索\n[捐赠] (/donate/)\n\n正文一段话，讲的是正经内容。\n")
    out = app._display_body(raw, 500)
    return ("/donate/" not in out and "logo.png" not in out and "打开搜索" not in out
            and "正文一段话" in out)


def t_display_keep_body(app):
    raw = "《傲慢与偏见》是一部于1813年出版的小说，故事讲了伊丽莎白。"
    return app._display_body(raw, 500) == raw


def t_answer_sane(app):
    # 注意签名：`_answer_sane(text)` 返回"清理后的字符串"（空串 = 不算回答），不是元组
    bad = ("⏳__pending__", "", "   ", "⏳", "…")
    good = "菏泽天气：阴天 +13°C"
    return (all(app._answer_sane(b) == "" for b in bad)
            and app._answer_sane(good) == good)


def t_mind_no_fail(app):
    from core.mind_stream import inject as MSI
    blk = MSI.build_block({"current_topic": "天气",
                           "recent_thoughts": ["⚠️ 天气服务暂时不可用（接口已停用）",
                                               "菏泽天气：阴天 +13°C"]},
                          text="菏泽天气", intent="query")
    return "暂时不可用" not in blk["text"] and "阴天 +13°C" in blk["text"]


def t_route_fast(app):
    from core import model_router as MR
    MR.STATE.update({"tier": "fast", "model": "", "at": 0.0})
    return MR.pick_tier("你好呀")[0] == "fast"


def t_route_code(app):
    from core import model_router as MR
    return MR.pick_tier("帮我写一个 Python 快速排序函数")[0] == "code"


def t_route_strong(app):
    from core import model_router as MR
    return MR.pick_tier("为什么这个架构要拆成微服务，对比两种方案的利弊")[0] == "strong"


def t_route_cooldown(app):
    """换档冷却：刚切过档，短时间内换成别的档也不切（否则 llama-swap 反复冷启动）。"""
    from core import model_router as MR
    MR.STATE.update({"tier": "code", "model": "qwopus3.5-4b-coder-mtp-q5_k_m.gguf",
                     "at": 1000.0})
    ok = True
    try:
        ids_backup = MR.available_models
        MR.available_models = lambda force=False: {"xiaojiao", "coder",
                                                   "qwopus3.5-4b-coder-mtp-q5_k_m.gguf"}
        m, t, _ = MR.route("你好呀", now=1010.0)      # 10 秒后问闲话
        ok = (t == "code")                            # 仍在 code 档，没切
        m2, t2, _ = MR.route("你好呀", now=1000.0 + MR._SWITCH_S + 5)
        ok = ok and (t2 == "fast")                    # 冷却过了才切回
    finally:
        MR.available_models = ids_backup
        MR.STATE.update({"tier": "fast", "model": "", "at": 0.0})
    return ok


def t_tool_desc(app):
    for t in app._build_tools():
        fn = t.get("function") or {}
        if "什么时候用" not in str(fn.get("description") or ""):
            return False
    return True


# ============================================================
# 在线层：真调 :5000 的模型，端到端
# ============================================================
ONLINE = [
    # (问句, 期望) —— 期望里的每一条都见下面的 judge()
    {"q": "帮我查下菏泽现在的天气", "any_tool": ["get_weather"],
     "answer_need": r"\d", "note": "必须真查、答案要有数字"},
    {"q": "帮我查下合肥现在的天气", "any_tool": ["get_weather"],
     "answer_need": r"\d", "note": "同上（换城市）"},
    {"q": "今天天气怎么样", "no_tool": ["web_search"],
     "answer_any": ["哪个城市", "城市", "查不到", "°C", "℃"], "note": "不许偷偷联网；问清或给真数据"},
    {"q": "最近去菏泽旅游根据天去是否可以去", "any_tool": ["get_weather"],
     "answer_need": r"\d", "note": "错别字也要走天气（先跑过上面那条预热）"},
    {"q": "最近有什么新闻", "any_tool": ["web_search"], "note": "新闻这轮不能被隔离误伤"},
    {"q": "我的公网 IP 是多少", "any_tool": ["net_ip", "get_ip"],
     "answer_need": r"\d+\.\d+\.\d+\.\d+", "note": "必须给出真实 IP"},
    {"q": "帮我抓 https://example.com 看看写了啥",
     "any_tool": ["get", "fetch", "stealthy_fetch"],
     "brackets_max": 3,
     "note": "抓取族任一都算对（get 被挡会自动升级 fetch→stealthy_fetch）；展示不能是方括号噪声"},
    {"q": "3.11 和 3.9 哪个大", "no_tool": ["web_search", "get"],
     "answer_any": ["3.11"], "max_sec": 30, "note": "纯推理，别联网"},
    {"q": "你好，用一句话介绍一下你自己", "no_tool": ["web_search", "get"],
     "max_sec": 30, "note": "闲聊不挂工具、不联网"},
    {"q": "帮我写一个 Python 快速排序函数", "answer_any": ["def ", "def("],
     "note": "要真给代码"},
    {"q": "帮我画一张电商系统的架构图", "any_tool": ["archify_deliver", "archify_" ],
     "note": "画图要走 archify 链"},
    {"q": "帮我查一下 https://www.gutenberg.org/ebooks/1342 这本书的电子书清单",
     "any_tool": ["ebook_manifest"], "note": "电子书清单要走 ebook_manifest"},
    {"q": "2026年世界杯谁是冠军",
     "answer_any": ["查不到", "没有", "不确定", "无法", "不知道", "没法核实", "未经核实", "自行核实"],
     "note": "时效性事实：查不到/无法核实就必须标出来，不许把比分球场编成事实"},
    {"q": "我昨天跟你说过的那件事你还记得吗", "answer_any": ["没有", "不记得", "没记录", "没印象"],
     "note": "没记忆就如实说，不许编"},
]


def _post(api, q, timeout=150):
    import requests
    t0 = time.time()
    r = requests.post(api.rstrip("/") + "/api/chat", json={"message": q}, timeout=timeout)
    dt = time.time() - t0
    d = r.json() if r.status_code == 200 else {}
    tools = [str((x or {}).get("tool") or "") for x in (d.get("tool_trace") or [])]
    return {"answer": str(d.get("answer") or ""), "tools": tools, "sec": dt,
            "status": r.status_code}


def judge(case, res):
    """按期望判分：pass / half / fail，并把"差在哪"写出来。"""
    misses = []
    ans = res["answer"]
    tools = res["tools"]
    if res["status"] != 200:
        return "fail", "HTTP %s" % res["status"]
    if case.get("any_tool"):
        if not any(any(t.startswith(p) for t in tools) for p in case["any_tool"]):
            misses.append("该用 %s，实际 %s" % ("/".join(case["any_tool"]), tools or "无"))
    if case.get("no_tool"):
        bad = [t for t in tools if t in case["no_tool"]]
        if bad:
            misses.append("不该用 %s" % bad)
    if case.get("answer_need") and not re.search(case["answer_need"], ans):
        misses.append("答案里缺 %r" % case["answer_need"])
    if case.get("answer_any") and not any(k in ans for k in case["answer_any"]):
        misses.append("答案里缺其中之一 %s" % case["answer_any"][:3])
    if case.get("max_sec") and res["sec"] > case["max_sec"]:
        misses.append("太慢 %.1fs > %ss" % (res["sec"], case["max_sec"]))
    if case.get("brackets_max") is not None and ans.count("[") > case["brackets_max"]:
        misses.append("方括号噪声 %d 处" % ans.count("["))
    if not misses:
        return "pass", "%.1fs ｜ 工具 %s" % (res["sec"], tools or "无")
    # 只要"工具对不对"这一条中了、答案缺内容 → 算半对；工具就错 → 算错
    if case.get("any_tool") and any("该用" in m for m in misses):
        return "fail", "；".join(misses)
    return "half", "；".join(misses)


def run_offline():
    print("\n" + "=" * 96)
    print("  离线层（不用模型 · 确定性）")
    print("=" * 96)
    app = _app()
    for name, fn in OFFLINE:
        try:
            ok = bool(globals()[fn](app))
        except Exception as e:
            ok = False
            name = name + "（异常：%s）" % type(e).__name__
        if ok:
            _rec(PASS, name, "")
            _print_row("pass", name, "")
        else:
            _rec(FAIL, name, "")
            _print_row("fail", name, "断言没过")


def run_online(api):
    print("\n" + "=" * 96)
    print("  在线层（真调 %s 的模型 · 会波动，看趋势不看绝对值）" % api)
    print("=" * 96)
    for case in ONLINE:
        try:
            res = _post(api, case["q"])
            tag, note = judge(case, res)
        except Exception as e:
            tag, note = "fail", "调用失败：%s" % type(e).__name__
        (PASS if tag == "pass" else HALF if tag == "half" else FAIL).append(
            {"case": case["q"], "note": note})
        _print_row(tag, case["q"], note)


def report(save=False):
    n = len(PASS) + len(HALF) + len(FAIL)
    print("\n" + "=" * 96)
    print("  合计 %d 项 ｜ 通过 %d ｜ 半对 %d ｜ 失败 %d ｜ 得分 %.1f%%"
          % (n, len(PASS), len(HALF), len(FAIL),
             100.0 * (len(PASS) + 0.5 * len(HALF)) / max(1, n)))
    if FAIL:
        print("  ❌ 失败清单：")
        for x in FAIL:
            print("      %-46s %s" % (str(x["case"])[:46], str(x["note"])[:80]))
    if HALF:
        print("  🟡 半对清单：")
        for x in HALF:
            print("      %-46s %s" % (str(x["case"])[:46], str(x["note"])[:80]))
    print("=" * 96)
    # ---- 趋势记录：每次跑都追加一行，下一次就能看出涨了还是退了 ----
    try:
        hist = os.path.join(_ROOT, "docs", "eval-history.jsonl")
        row = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "total": n,
               "pass": len(PASS), "half": len(HALF), "fail": len(FAIL),
               "score": round(100.0 * (len(PASS) + 0.5 * len(HALF)) / max(1, n), 1),
               "failed": [x.get("case") for x in FAIL][:10]}
        io.open(hist, "a", encoding="utf-8").write(json.dumps(row, ensure_ascii=False) + "\n")
        prev = None
        try:
            lines = [x for x in io.open(hist, encoding="utf-8").read().split("\n") if x.strip()]
            if len(lines) >= 2:
                prev = json.loads(lines[-2])
        except Exception:      # noqa: silent-ok
            prev = None
        if prev:
            d = row["score"] - float(prev.get("score") or 0)
            print("  📈 趋势：上一次 %.1f%% → 本次 %.1f%%（%+.1f）"
                  % (float(prev.get("score") or 0), row["score"], d))
    except Exception as e:      # noqa: silent-ok — 趋势写不进去不影响评测结论
        print("  （趋势记录失败：%s）" % type(e).__name__)

    if save:
        path = os.path.join(_ROOT, "docs", "eval-baseline.md")
        lines = ["# 小焦端到端评测基线", "",
                 "> 由 `python tools/eval_xiaojiao.py --save` 实跑生成。数字不是手写的。", "",
                 "**合计 %d 项 ｜ 通过 %d ｜ 半对 %d ｜ 失败 %d ｜ 得分 %.1f%%**"
                 % (n, len(PASS), len(HALF), len(FAIL),
                    100.0 * (len(PASS) + 0.5 * len(HALF)) / max(1, n)), "",
                 "## 失败（必须修）", ""]
        for x in FAIL:
            lines.append("- **%s** ｜ %s" % (x["case"], x["note"]))
        lines += ["", "## 半对（该修）", ""]
        for x in HALF:
            lines.append("- %s ｜ %s" % (x["case"], x["note"]))
        lines += ["", "## 全过", ""]
        for x in PASS:
            lines.append("- %s" % x["case"])
        io.open(path, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
        print("  已写：%s" % path)
    return 0 if not FAIL else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="只跑离线层")
    ap.add_argument("--online-only", action="store_true", help="只跑在线层")
    ap.add_argument("--api", default="http://127.0.0.1:5000")
    ap.add_argument("--save", action="store_true", help="把报告写到 docs/eval-baseline.md")
    a = ap.parse_args()
    if not a.online_only:
        run_offline()
    if not a.offline:
        run_online(a.api)
    return report(save=a.save)


if __name__ == "__main__":
    sys.exit(main())
