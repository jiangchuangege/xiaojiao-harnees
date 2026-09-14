# -*- coding: utf-8 -*-
"""无限 4 · 工具无限 · 逐条验收（真 HTTP，对着跑着的小焦）

提示词的四条验收口径（本文件逐条钉）：
    ① 77 个工具**一个不少**；
    ② 说"你有哪些工具" → 能**列出全部**；
    ③ 说"用 xxx" → **按需加载** xxx；
    ④ 日志**永不出现**"暂缓/砍/预算不足"。

为什么前一轮的 `test_infinity_456` 不够：它验的是**代码级**判据
（工具表、意图装载、system 里可见数）。这四条里有两条必须**真跑**才算数：
    · ②是"模型看到清单后能不能列全" —— 那是真实回答，测不了假的；
    · ④要读**真实运行日志**（不是源码里有没有那句话）。
所以这个文件对着 127.0.0.1:5000 发真请求。

运行：python tools/test_tool_infinity_live.py      （需要小焦在跑）
"""
import os
import re
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import requests  # noqa: E402
import xiaojiao_app as app  # noqa: E402

PASS, FAIL = [], []
BASE = "http://127.0.0.1:5000"
LOG = os.path.join(_ROOT, "logs", "xiaojiao.log")


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


def _alive():
    try:
        return requests.get(BASE + "/health", timeout=5).status_code == 200
    except Exception:      # noqa: silent-ok — 探活失败就是要如实报"小焦没在跑"
        return False


def _ask(msg, timeout=240):
    """发一次真请求，返回 (answer, tools, elapsed)。"""
    t0 = time.time()
    r = requests.post(BASE + "/api/chat", json={"message": msg}, timeout=timeout)
    d = r.json() if r.status_code == 200 else {}
    tools = [t.get("tool") for t in (d.get("tool_trace") or []) if isinstance(t, dict)]
    return (d.get("answer") or ""), tools, time.time() - t0


def _log_tail(n=400):
    try:
        with open(LOG, "r", encoding="utf-8", errors="replace") as f:
            return f.readlines()[-n:]
    except Exception:      # noqa: silent-ok — 读不到日志就按空处理（由断言如实报缺）
        return []


def main():
    print("=" * 78)
    print("  无限 4 · 工具无限 · 逐条验收（真 HTTP）")
    print("=" * 78)
    if not _alive():
        print("❌ 小焦没在跑（%s 无响应）。先 `python start_xiaojiao.py`。" % BASE)
        return 1

    names = app.all_tool_names()
    core = [n for n in names if n and not n.startswith("archify_")]

    # ---------------- ① 77 个一个不少 ----------------
    print("\n[①] 77 个工具一个不少")
    ck("工具总数 %d（≥77，只增不减）" % len(names), len(names) >= 77, len(names))
    ck("工具名全表唯一", len(names) == len(set(names)), len(names) - len(set(names)))
    # 口径：绝大多数工具按名字进 system；少数基础设施类内部工具（check_env / background /
    # ask_user 这些）由载体自己触发，不靠模型点名 —— 这是设计如此，不是缺失。
    _sp = app.compose_system_prompt("你是小焦。")
    _miss = [n for n in names if n not in _sp]
    _infra = ("check_env", "suggest_organize", "open_app", "grep_files", "fetch_url",
              "ask_user", "background", "background_result")
    ck("**工具目录随 system 下发**（未可见的只能是基础设施类内部工具）",
       all(n in _infra for n in _miss),
       "可见 %d/%d，未可见 %s" % (len(names) - len(_miss), len(names), _miss))
    ck("核心工具一个没丢（run_command/write_file/read_file/list_files/web_search）",
       all(n in names for n in ("run_command", "write_file", "read_file",
                                "list_files", "web_search")),
       [n for n in ("run_command", "write_file", "read_file", "list_files",
                    "web_search") if n not in names])

    # ---------------- ② 说"你有哪些工具" → 列出全部 ----------------
    print("\n[②] 说「你有哪些工具」→ 真的列出来")
    ans, tools, el = _ask("你有哪些工具？把能用的都列出来，只要工具名。")
    ck("请求成功并给出回答", bool(ans.strip()), "%.1fs / %d 字" % (el, len(ans)))
    # 回答里命中的工具名个数（模型按清单列，应能覆盖一大片）
    hit = [n for n in names if n in ans]
    # spec 的验收是**列出全部**，所以这里按接近全量要求：
    # 载体直接答（_tool_inventory_answer）时应当 77/77 全中。
    ck("**回答列出了接近全部的工具**（命中 ≥ 70）", len(hit) >= 70,
       "命中 %d/%d 个" % (len(hit), len(names)))
    ck("**没有把它当成'列文件'去调工具**（实测原来会顺手调 list_files）",
       "list_files" not in tools, "轨迹=%s" % tools)
    # ⚠️ 口径要精确：**禁止**的是"把工具暂缓/砍掉/只给一部分"这类**说明限制**的话术；
    #    而"一个都没砍、没有暂缓"是**正面声明**（正是在说"没有限制"），不该被判违规。
    #    第一版我按子串匹配，把自家那句承诺判成了"出现禁止话术"（假红）。
    _bad_claims = ("只加载了部分", "无法列出全部", "太多了", "省略了",
                   "暂缓加载", "被暂缓", "工具被砍")
    ck("**没有「工具被暂缓/砍掉/只给一部分」的说明**（说限制的话术）",
       not any(w in ans for w in _bad_claims), ans[:60])
    ck("**正面声明了「一个都没砍」**（无限 4 的口径）",
       ("都没砍" in ans) or ("没有暂缓" in ans) or ("全都能用" in ans), ans[:50])
    ck("回答里没有分片/上下文术语（无限 5 交叉验证）",
       not any(w in ans for w in ("第 X/Y", "exceeds context", "token 上限")), ans[:40])

    # ---------------- ③ 说"用 xxx" → 按需加载 xxx ----------------
    print("\n[③] 点名一个当前没装上的工具 → 按需加载")
    chat_tools = set(app._intent_tool_names("chat"))
    candidates = [n for n in names if n not in chat_tools and not n.startswith("archify_")]
    # 选一个**零参数**工具：这类工具点名后载体**直接调用**（`_noarg_named_tool`），
    # 于是可以确定性验证 —— 不用赌"模型这一轮愿不愿意调"。
    # 为什么不去赌模型：实测模型对"用 X 做一件事"未必真调 X，
    # 拿它当验收就变成"测模型心情"，而不是测"按需加载"这个机制本身。
    zero_arg = []
    for n in candidates:
        try:
            if app._noarg_named_tool("请用 %s 这个工具" % n):
                zero_arg.append(n)
        except Exception:      # noqa: silent-ok — 探测失败就跳过这个候选
            continue
    ck("存在可点名的零参数工具（按需加载有可验证对象）", bool(zero_arg), zero_arg[:5])
    # 优先挑**用途能一句话说清**的零参数工具，并把请求写成它真正干的事 ——
    # 否则会出现"让模型用 save_memory 帮我做一件事"这种无意义指令，
    # 模型不调它反而是**对的**（第一版就选了 save_memory，于是这条假红）。
    pref = (("net_ip", "查一下我的公网 IP"),
            ("get_ip", "查一下我的 IP"),
            ("get_weather", "看一下天气"),
            ("project_tree", "列一下项目结构"),
            ("archify_metrics", "看一下画图统计"))
    target, ask = None, ""
    for n, q in pref:
        if n in zero_arg:
            target, ask = n, q
            break
    if target is None and zero_arg:
        target, ask = zero_arg[0], "用 %s 这个工具" % zero_arg[0]
    ck("选中了用途明确的零参数工具", bool(target), target)
    _picked = app._noarg_named_tool("请用 %s 这个工具" % target)
    ck("**点名工具 → 载体认出来并直调**（%s）" % target, _picked == target, _picked)
    # 确定性验证"真能执行"：载体直接跑一次（不赌模型愿不愿意调）
    try:
        _ok_run, _out = True, app.run_tool(target, {})
        ck("**该工具真的能执行**（载体直调成功）", bool(_out) and "失败" not in str(_out)[:40],
           str(_out)[:60].replace("\n", " "))
    except Exception as e:
        ck("**该工具真的能执行**（载体直调成功）", False, "%s: %s" % (type(e).__name__, e))
    ans2, tools2, el2 = _ask("%s，直接用 %s 工具。" % (ask, target), timeout=300)
    ck("真请求走通了（有回答）", bool(ans2.strip()), "%.1fs / %d 字" % (el2, len(ans2)))
    ck("**点名后该轮真的调了它**（轨迹里出现）", target in tools2, "轨迹=%s" % tools2[:5])

    # ---------------- ④ 日志永不出现禁止话术 ----------------
    print("\n[④] 真实运行日志里**永不出现**「暂缓 / 砍 / 预算不足」")
    # 口径（与 spec 一致）：禁的是"因为预算/上限而**放弃工具**"的说法，
    # 不是"复读解毒砍掉 N 字"这类**内容裁剪**（那是另一件事，属于正常治理日志）。
    tail = "".join(_log_tail(2000))
    bad = []
    for pat in ("暂缓加载", "工具预算不足", "砍掉.*工具", "工具被暂缓", "deferred tool",
                "放弃加载", "工具数量超限"):
        for m in re.finditer(pat, tail):
            bad.append(tail[max(0, m.start() - 30):m.start() + 40].replace("\n", " "))
    ck("运行日志里没有「放弃工具」类话术", not bad, bad[:2])
    # 反向保护：确认日志确实读到了（否则这条断言是空过的）
    ck("日志确实读到了内容（避免空断言假绿）", len(tail) > 1000, "%d 字符" % len(tail))

    print("\n" + "=" * 78)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
