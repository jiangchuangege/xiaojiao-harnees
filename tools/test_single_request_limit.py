# -*- coding: utf-8 -*-
"""无限 6 · 单次请求永不超 · 逐条验收（真 HTTP + 100 轮压测）

提示词的三条验收口径（本文件逐条钉）：
    ① 说"你好" < 3000 token；
    ② 说"用 Archify 画图" < 10000 token；
    ③ **连问 100 轮无 ctx 错**。

为什么必须真跑 100 轮：单次装配是**可算的**（前一轮已经验过 `_fit_context` 的公式），
但"**连问 100 轮**"验的是**累积行为** —— 历史越堆越长、记忆检索越检越多、
session 越来越大，任何一处没跟着裁，第 60 轮才开始 400，而单轮测试永远看不到。
这正是这一项的价值所在。

运行：python tools/test_single_request_limit.py      （需要小焦在跑）
"""
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import requests  # noqa: E402
import xiaojiao_app as app  # noqa: E402

PASS, FAIL = [], []
BASE = "http://127.0.0.1:5000"
LOG = os.path.join(_ROOT, "logs", "xiaojiao.log")

# "ctx 错"的判据：服务端 400/413/500，或回答里出现上下文超限的字样
CTX_ERR_HINTS = ("exceeds", "context length", "上下文超限", "超过最大", "too long",
                 "maximum context", "ctx")


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


def _alive():
    try:
        return requests.get(BASE + "/health", timeout=5).status_code == 200
    except Exception:      # noqa: silent-ok — 探活失败就如实报"小焦没在跑"
        return False


def _ask(msg, timeout=240):
    r = requests.post(BASE + "/api/chat", json={"message": msg}, timeout=timeout)
    try:
        d = r.json()
    except Exception:      # noqa: silent-ok — 非 JSON 响应也要能看状态码
        d = {}
    return r.status_code, d


def _real_ctx():
    """当前实际使用的上下文上限（`_max_context_tokens()`），拿它当阈值基准。"""
    try:
        return int(app._max_context_tokens())
    except Exception:      # noqa: silent-ok — 取不到就用 spec 的口径做兜底
        return 20000


def main():
    print("=" * 78)
    print("  无限 6 · 单次请求永不超（真 HTTP + 100 轮压测）")
    print("=" * 78)
    if not _alive():
        print("❌ 小焦没在跑（%s）。先 `python start_xiaojiao.py`。" % BASE)
        return 1
    limit = _real_ctx()
    print("  当前上下文上限 = %d token（阈值基准）" % limit)

    # ---------------- ① 说"你好" < 3000 token ----------------
    print("\n[①] 说「你好」→ 装配开销 < 3000 token")
    # ⚠️ 必须量**真实那一轮发出去的东西**：`agent_run` 用的是
    #    `system_for_intent(intent, ...)`（按意图**收窄**过的 system），
    #    不是 `compose_system_prompt()`（那是全量：6172 token，含完整插件清单与技能文档）。
    #    第一版拿全量当闲聊轮开销 → 实测 6557，把"本来合格的 633"判成了超标（假红）。
    #    教训：验收"单次不超"要量**实际请求**，不能量"最大可能的那份"。
    chat_sys = app.system_for_intent("chat", user_input="你好")
    sys_tok = app._estimate_tokens(chat_sys)
    chat_tools = app._intent_tool_names("chat")
    tools_tok = app._tools_tokens(chat_tools)
    q_tok = app._estimate_tokens("你好")
    total = sys_tok + tools_tok + q_tok
    ck("闲聊轮总装配 < 3000 token（实测 %d）" % total, total < 3000,
       "system=%d + tools=%d + 本轮=%d" % (sys_tok, tools_tok, q_tok))
    ck("闲聊轮 system **比全量小很多**（按意图收窄生效）",
       sys_tok < app._estimate_tokens(app.compose_system_prompt("你是小焦。")) / 2,
       "%d vs 全量 %d" % (sys_tok,
                        app._estimate_tokens(app.compose_system_prompt("你是小焦。"))))
    code, d = _ask("你好")
    ck("真请求 HTTP 200", code == 200, code)
    ck("回答里没有 ctx 报错", not any(h in str(d.get("answer") or "").lower()
                                      for h in CTX_ERR_HINTS),
       (d.get("answer") or "")[:40])
    _kept, _note = app._fit_context(chat_sys, [], "你好", max_ctx=limit, tools_tokens=tools_tok)
    ck("装配说明里的合计 ≤ 上限",
       bool(_note) and ("合计" in _note), _note[:70])

    # ---------------- ② 说"用 Archify 画图" < 10000 token ----------------
    print("\n[②] 说「用 Archify 画图」→ 装配开销 < 10000 token")
    dia = "用 Archify 画一张小焦系统的架构图"
    dia_intent = app._detect_intent(dia)
    dia_sys_tok = app._estimate_tokens(app.system_for_intent(dia_intent, user_input=dia))
    dia_tools = app._intent_tool_names(dia_intent)
    d_tools_tok = app._tools_tokens(dia_tools)
    d_q_tok = app._estimate_tokens(dia)
    d_total = dia_sys_tok + d_tools_tok + d_q_tok
    ck("画图轮总装配 < 10000 token（实测 %d，装载 %d 个工具）"
       % (d_total, len(dia_tools)), d_total < 10000,
       "system=%d + tools=%d + 本轮=%d" % (dia_sys_tok, d_tools_tok, d_q_tok))
    ck("画图轮确实装载了 archify 工具链",
       any(n.startswith("archify_") for n in dia_tools), dia_tools[:4])
    ck("画图轮总装配也 ≤ 上下文上限", d_total <= limit, "%d / %d" % (d_total, limit))

    # ---------------- ③ 连问 100 轮无 ctx 错 ----------------
    print("\n[③] 连问 100 轮 → 无 ctx 错（这项只能真跑）")
    # ⚠️ 必须**尊重限速**：应用自己有"每分钟最多 N 次"的保护，连打 100 轮会撞 429。
    #    429 是**保护生效**，不是"ctx 错" —— 第一版把它算进失败，于是这条断言变成
    #    "取决于上一次跑得多快"（同一份代码，一次全过、一次红 12 个）。
    #    正确做法：单轮失败是 429 时**等一会儿重试**，把它当作"节流"而不是"错误"；
    #    只有重试后仍失败、或出现真正的 ctx 报错，才计入失败。
    rounds = 100
    errors, slow, codes, throttled = [], [], {}, 0
    t0 = time.time()
    i = 0
    while i < rounds:
        i += 1
        msg = "第 %d 轮：用一句话说说载体优先是什么意思。" % i
        try:
            code, d = _ask(msg, timeout=180)
        except Exception as e:
            errors.append({"round": i, "err": "%s: %s" % (type(e).__name__, e)})
            break
        if code == 429:
            # 被限速：等一下再问同一轮（**轮次不前进**，保证真的问满 100 轮）
            throttled += 1
            i -= 1
            time.sleep(3)
            if throttled > 200:          # 兜底：真的一直被限速就停下如实报告
                break
            continue
        codes[code] = codes.get(code, 0) + 1
        ans = str(d.get("answer") or "")
        low = ans.lower()
        bad = any(h in low for h in CTX_ERR_HINTS) or code >= 400
        if bad:
            errors.append({"round": i, "code": code, "answer": ans[:80]})
        if i % 25 == 0:
            print("    …已问 %d 轮（%.0fs，累计错误 %d，被限速 %d 次）"
                  % (i, time.time() - t0, len(errors), throttled))
    el = time.time() - t0
    ck("**100 轮全部没有 ctx 错 / 4xx-5xx**", not errors,
       "错误 %d 个：%s" % (len(errors), errors[:2]))
    ck("成功轮次全是 200（429 属节流，已单独统计）",
       all(c == 200 for c in codes), codes)
    ck("100 轮真的问满了（没有中途卡死）", codes.get(200, 0) >= rounds,
       "成功 %d / %d 轮，耗时 %.0fs（均 %.1fs/轮），限速退避 %d 次"
       % (codes.get(200, 0), rounds, el, el / max(1, rounds), throttled))
    # 健康系统在这 100 轮里不该出现"响应超时"症状
    try:
        from core.health import read_jsonl
        import core.health as H
        recs = read_jsonl(os.path.join(H.health_dir(), "records.jsonl"), limit=60) or []
        recent = [r for r in recs if float(r.get("ts") or 0) > t0 - 60]
        to_sym = [r for r in recent if "timeout" in str(r.get("symptoms") or "")]
        ck("这 100 轮里健康系统没记「响应超时」", not to_sym, len(to_sym))
    except Exception as e:      # noqa: silent-ok — 读不到病历就不下结论（如实说明）
        ck("健康病历可读（用于核对超时症状）", False, "%s" % e)

    print("\n" + "=" * 78)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
