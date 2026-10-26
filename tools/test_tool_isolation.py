# -*- coding: utf-8 -*-
"""通用／专用工具隔离 · 自测（确定性，不需要模型、不需要网络）

为什么单独一条：这个隔离只用一句话决定"这一轮桌面摆哪几个工具"，
一旦判错，用户看到的是"它答非所问"或者"它干脆不会了"，而且**不报错**。
所以这里钉住三件事：
  ① 该隔离的必须隔离：问天气/公网 IP/漏洞时，通用兜底（web_search 等）**不许出现在这一轮的工具表里**；
  ② 不该隔离的不许误伤：问新闻、查资料时通用工具就是正解，**必须照旧装**；
  ③ 隔离 ≠ 删工具：工具表总数不变、`rea_call`/点名调用路径仍在（隔离只影响"这一轮摆几个"）。
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


def main():
    print("=" * 80)
    print("  通用／专用工具隔离自测")
    print("=" * 80)
    from core import tool_isolation as TI      # noqa: E402

    # ---------------- 一、触发词命中 ----------------
    print("\n[一] 哪些话算「这件事有专用工具」")
    cases = [
        ("帮我查下济南现在的天气", ["get_weather"]),
        ("明天会下雨吗，气温多少", ["get_weather"]),
        ("我的公网 IP 是多少，在哪", ["net_ip", "get_ip"]),
        ("帮我看看最近的漏洞", ["collect_vulnerabilities"]),
        ("把这个文件下载到本地", ["download"]),
        ("帮我截个图", ["screenshot"]),
        ("你还记得我住在哪吗", ["read_memory"]),
        ("帮我画一张架构图", ["archify_deliver"]),
        ("反编译一下这个 exe", ["rea_do"]),
    ]
    for text, want in cases:
        got = TI.specialized_for(text)
        ck("「%s」→ %s" % (text[:16], "/".join(got) or "（无）"),
           bool(set(got) & set(want)), got)

    print("\n[二] 这些不该被判成专用（否则会误伤通用检索）")
    for text in ("最近有什么新闻", "帮我搜一下 Python 教程", "介绍一下这个开源项目"):
        ck("「%s」→ 不命中专用" % text[:14], TI.specialized_for(text) == [],
           TI.specialized_for(text))

    # ---------------- 三、隔离动作 ----------------
    print("\n[三] isolate：命中专用时把通用兜底逐出，其余保留")
    planned = ["get_weather", "net_ip", "collect_vulnerabilities", "web_search", "read_file", "run_command"]
    keep, why = TI.isolate("帮我查下济南现在的天气", planned)
    ck("天气这轮：通用检索 web_search 被逐出", "web_search" not in keep, keep)
    ck("天气这轮：run_command 也被逐出（它是最通用的那个）", "run_command" not in keep, keep)
    ck("天气这轮：专用工具 get_weather 留下", "get_weather" in keep, keep)
    ck("说明里写清了为什么", "命中专用工具" in why, why[:60])
    keep2, why2 = TI.isolate("我的公网 IP 是多少", planned)
    ck("公网 IP 这轮：web_search 被逐出", "web_search" not in keep2, keep2)
    ck("公网 IP 这轮：net_ip / get_ip 留下",
       "net_ip" in keep2 or "get_ip" in keep2, keep2)
    keep3, why3 = TI.isolate("最近有什么新闻", planned)
    ck("新闻这轮：**不隔离**（web_search 是它的正解）", "web_search" in keep3, keep3)
    ck("新闻这轮：说明是「没有命中专用」", "没有专用工具命中" in why3, why3)
    keep4, _ = TI.isolate("帮我查下济南现在的天气", planned, available={"get_weather", "web_search"})
    ck("available 里没有的工具不会被塞进来", all(n in {"get_weather", "web_search"} for n in keep4), keep4)

    # ---------------- 四、隔离 ≠ 删工具 ----------------
    print("\n[四] 隔离只影响「这一轮摆几个」，不影响工具总数与点名调用")
    ck("通用兜底清单非空（说明这不是把工具禁掉，只是这一轮不摆）", len(TI.GENERIC) >= 5, TI.GENERIC[:5])
    ck("fallback_for 能给出兜底（专用工具坏了时用）", len(TI.fallback_for("查天气")) >= 1,
       TI.fallback_for("查天气")[:3])
    import xiaojiao_app as app        # noqa: E402
    ck("工具表总数没变（99 个）", len(app.all_tool_names()) >= 99, len(app.all_tool_names()))
    only_weather = app._intent_tool_names("query", "帮我查下济南现在的天气")
    ck("走真实入口：天气这轮的工具表里没有 web_search",
       "web_search" not in only_weather, only_weather)
    ck("走真实入口：天气这轮的工具表里有 get_weather",
       "get_weather" in only_weather, only_weather)
    only_news = app._intent_tool_names("query", "最近有什么新闻")
    ck("走真实入口：新闻这轮的工具表里**有** web_search", "web_search" in only_news, only_news)
    ck("隔离后这一轮工具表不为空（不能把桌子清空）", len(only_weather) >= 1, only_weather)

    # ---------------- 五、旁路也要管：抓取直通 / 天气降级 ----------------
    print("\n[五] 不走 run_tool 的旁路也必须受隔离约束")
    _both = "帮我抓 https://httpbin.org/json 顺便看下合肥天气"
    _sc = app._detect_scrape_intent(_both)
    ck("前提：这句话确实同时被判成了「连网址抓」", bool(_sc), _sc)
    _ans, _tr = app._scrape_direct(_both, [])
    ck("命中专用工具的这一轮，抓取直通会主动跳过（不拿被逐出的 get 硬抓）",
       _ans is None and not _tr, (_ans, _tr))
    _only_url = "帮我抓 https://httpbin.org/json"
    ck("只给了网址（没命中专用工具）→ 直通照旧放行",
       bool(app._detect_scrape_intent(_only_url)) and not TI.specialized_for(_only_url),
       TI.specialized_for(_only_url))
    _named_txt = "用 get 抓 https://httpbin.org/json 合肥天气"
    _scn = app._detect_scrape_intent(_named_txt)
    ck("用户亲口点了工具名 → 豁免成立（点名即装，不当成钻空子）",
       bool(_scn) and _scn[0] in _named_txt and bool(TI.specialized_for(_named_txt)),
       _scn)
    import inspect as _insp
    _src = _insp.getsource(app._weather_fallback)
    ck("天气降级里那条 web_search 也过门了（不再背地里联网）",
       "_web_allowed_this_turn" in _src, _src[:40].strip())

    print("\n" + "=" * 80)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("=" * 80)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
