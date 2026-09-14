# -*- coding: utf-8 -*-
"""问题 1 回归测试：复读检测必须挂在**所有输出路径**上，而不是只挂在流式那条。

运行：python tools/test_repeat_all_paths.py

用户实测现象：回答里整张表格被「预算」刷满几十行，健康系统那边**明明报了 repeat 症状**，
用户却还是看到了那一屏垃圾。也就是说 —— **检测是好的，接线是漏的。**

本测试证明两件事，缺一不可：
  A. 判据本身能抓住各种刷屏形态（短语串联 / 短块扎堆 / 单字符洪水），且**不误杀**正常文本；
  B. 每一条真实的输出路径都接上了它 —— 主对话出口、流式出口、工具总结、
     以及最关键的**二级治疗路径**（实测就是从这里漏出去的）。

判据（用户口径）：
  · 2 字以上短块连续 ≥5 次 → 触发（我们更严：≥4 字的块 3 次就触发）
  · 同一字符在 100 字内 ≥10 次 → 触发（再叠加"占满窗口 35%"防表格误杀）
  · 日志 logs/health/degeneration.jsonl 记录每次触发
  · 端到端：强制复读场景必须被自动掐断
"""
import json
import os
import sys
import tempfile
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import xiaojiao_app as X  # noqa: E402
from core.health import degeneration as D  # noqa: E402

PASS, FAIL = [], []
DEGEN_LOG = os.path.join(_ROOT, "logs", "health", "degeneration.jsonl")


def ck(group, name, cond, info=""):
    (PASS if cond else FAIL).append("%s/%s" % (group, name))
    print("  %s [%s] %s%s" % ("✅" if cond else "❌", group, name,
                              ("  ← " + str(info)) if info else ""))


# ---- 用户实测的四种刷屏形态 ----
TABLE = "".join("| 第{i}项 | 预算 | 预算 | 预算 | 预算 | 预算 |\n".format(i=i) for i in range(1, 26))
SLASH_BODY = "预算 / 预算 / 预算 / 预算 / 预算 / 预算 / 预算 / 预算 / 预算 / 预算 /\n" * 6
SLASH_FLOOD = "以下是明细：" + "/" * 60 + "结束。"
SENT_LOOP = "开头正常。" + "然后说：嗯。然后说：哦。然后说：好的。" * 20

# ---- 必须放行的正常文本（误杀比漏检更糟：截断不可逆）----
NORMAL = [
    ("正常 4 行表格",
     "| 项目 | 金额 | 说明 |\n|---|---|---|\n| 服务器 | 12000 | 一年期 |\n"
     "| 带宽 | 3000 | 按量 |\n| 人力 | 80000 | 两人月 |\n| 合计 | 95000 | 含税 |\n"),
    ("正常编号列表",
     "".join("%d. 第一步先确认需求；第二步再拆任务；第三步才动手。\n" % i for i in range(1, 9))),
    ("markdown 分隔线",
     "这一节讲完了。\n\n---\n\n下一节讲装配：载体按意图只装当前需要的那一小块。\n"),
    ("正常中文长文",
     "".join("第%d个要点：载体把上下文按需装配，模型只处理当前这一小块。\n" % i
             for i in range(1, 14))),
    ("正常英文段落",
     "Our product helps small teams do professional data reporting. First you connect sources. "
     "Second you build metrics visually. Third you share dashboards with role based permissions. "),
    ("带大量逗号的中文", "他先说了一件事，然后又说了另一件事，接着补充了第三点，" * 6),
    ("代码块（含大量符号）",
     "```powershell\nGet-ChildItem -Recurse -Filter *.py | Select-String -Pattern 'x' | "
     "ForEach-Object { $_.Path }\n```\n"),
    ("含引号对话的正常小说段落",
     "他说：「这件事我知道了。」然后转身走开。她愣了一下，追上去问：「你确定吗？」" * 3),
]


def _log_lines():
    if not os.path.exists(DEGEN_LOG):
        return []
    out = []
    with open(DEGEN_LOG, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    out.append(json.loads(line))
                except Exception:      # noqa: silent-ok — 半截行跳过
                    pass
    return out


def main():
    print("=" * 66)
    print("  问题 1 回归：复读检测挂在所有输出路径上")
    print("=" * 66)

    # ===== A 判据：四种刷屏都要抓住 =====
    print("\n[A] 判据 · 用户实测的刷屏形态必须抓住")
    n0 = len(_log_lines())
    for name, text, want in [("表格被『预算』刷满", TABLE, "phrase_repeat"),
                             ("正文反复『预算 / 』", SLASH_BODY, "phrase_repeat"),
                             ("整屏单个字符『/』", SLASH_FLOOD, "char_flood"),
                             ("整段复读句 ×20", SENT_LOOP, "ngram_repeat")]:
        cut, hit, n = D.truncate_repeat(text)
        ck("A", "%s 被检出并截断" % name,
           hit is not None and n > 0 and len(cut) < len(text),
           "%s 砍 %d 字" % (hit.kind if hit else "没检出", n))
        ck("A", "%s 落在完整句/有效片段" % name,
           bool(cut.strip()) and (cut.rstrip()[-1] in "。！？!?；;…" or len(cut.strip()) < 40),
           repr(cut[-14:]))
    ck("A", "每次触发都写进病历 degeneration.jsonl", len(_log_lines()) >= n0 + 4,
       "%d → %d 条" % (n0, len(_log_lines())))

    # ===== A2 新增判据：单字符洪水 + 短块门槛 =====
    print("\n[A2] 判据细节（用户明确要求的两条）")
    PAD = ("这一节讲载体如何按意图装配上下文，只装当前需要的那一小块，其余按需加载；"
           "单次请求永远装得下，总量靠循环与拼接做到无限。")
    d = D.DegenerationDetector()
    hit_short = d.check(PAD + "谢谢 " * 6, where="t")
    ck("A2", "① 2 字以上短块连续 ≥5 次 → 触发", hit_short is not None, str(hit_short))
    ck("A2", "① 但 3 次的口语修辞不触发（防误杀）",
       D.detect(PAD + "加油！加油！加油！") is None)
    ck("A2", "② 同一字符 100 字内 ≥10 次 → 触发",
       D.detect(PAD + "/" * 40) is not None, str(D.detect(PAD + "/" * 40)))
    ck("A2", "② 但正常 markdown 表格的 『|』不触发（次数够、占比不够）",
       D.detect(NORMAL[0][1]) is None)

    # ===== B 不误杀 =====
    print("\n[B] 判据 · 正常文本一个都不许动")
    bad = [n for n, t in NORMAL if D.detect(t, where="t") is not None]
    ck("B", "8 类正常文本全部不触发", not bad, bad or "0 误杀")
    bad2 = [n for n, t in NORMAL if X._degeneration_net(t, where="t")[1]]
    ck("B", "出口解毒网对正常文本也是原样放行", not bad2, bad2 or "0 误杀")

    # ===== C 路径 1：主对话出口（/api/chat）=====
    print("\n[C] 路径 · 主对话出口 /api/chat")
    tmp = tempfile.mkdtemp(prefix="p1_")
    X.SESSIONS_FILE = os.path.join(tmp, "sessions.json")
    with open(X.SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump({"current": "p1s", "sessions": [{"id": "p1s", "title": "t", "messages": []}]}, f)
    _orig_agent = X.agent_run
    _orig_cont = X._needs_continuation
    X._needs_continuation = lambda t: False
    try:
        X.agent_run = lambda *a, **k: (TABLE, True, [], False, [])
        cli = X.app.test_client()
        d1 = cli.post("/api/chat", json={"message": "你仔细查肯定不够12万的"}).get_json()
        ans = d1.get("answer") or ""
        ck("C", "表格刷屏没有原样返回给用户", "预算 | 预算 | 预算 | 预算" not in ans, ans[:60].replace("\n", " "))
        ck("C", "如实说明了这一轮发生了什么", ("复读" in ans) or ("重复" in ans), ans[:70].replace("\n", " "))
        hist = json.load(open(X.SESSIONS_FILE, encoding="utf-8"))["sessions"][0]["messages"]
        ck("C", "进历史的同样不是刷屏原文",
           all("预算 | 预算 | 预算 | 预算" not in str(m.get("content")) for m in hist),
           hist[-1]["content"][:40].replace("\n", " "))

        # ===== D 路径 2：流式出口 =====
        print("\n[D] 路径 · 流式出口 /api/chat/stream")
        with open(X.SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump({"current": "p2s", "sessions": [{"id": "p2s", "title": "t", "messages": []}]}, f)

        def _agent_slash(*a, **k):
            cb = k.get("on_delta")
            if cb:
                cb(SLASH_FLOOD)
            return SLASH_FLOOD, True, [], False, []
        X.agent_run = _agent_slash
        r = cli.post("/api/chat/stream", json={"message": "查一下明细"})
        body = r.get_data(as_text=True)
        ck("D", "推给前端的正文里没有整屏斜杠（源头闸门）", ("/" * 40) not in body,
           "含 40 连斜杠=%s" % ("/" * 40 in body))
        ck("D", "流结束后用解毒结果对齐正文（done.answer 不含刷屏）",
           "/" * 40 not in body and "以下是明细" in body,
           [l for l in body.split("\n\n") if '"type": "done"' in l][-1][:110])
        # 顺序验证：源头闸门必须在**推 delta 之前**（否则用户先看到满屏垃圾再被覆盖）
        deltas = [l for l in body.split("\n\n") if '"type": "delta"' in l]
        ck("D", "delta 事件里也一个刷屏字都没有",
           all(("/" * 40) not in l for l in deltas), "delta 条数=%d" % len(deltas))

        # ===== E 路径 3：工具总结 =====
        print("\n[E] 路径 · 工具总结（_summarize_tool）")
        X.agent_run = _orig_agent
        _orig_ask = X._llm_ask_raw
        X._llm_ask_raw = lambda p: TABLE
        try:
            s = X._summarize_tool("查一下预算", "工具结果", "get")
        finally:
            X._llm_ask_raw = _orig_ask
        ck("E", "工具总结里的刷屏被解毒", "预算 | 预算 | 预算 | 预算" not in s, s[:60].replace("\n", " "))

        # ===== F 路径 4：二级治疗（**实测就是从这条漏出去的**）=====
        print("\n[F] 路径 · 二级治疗（本轮真 bug：诊断出来了却把原文还回去）")
        from core.health.heal import HealthHealer
        h = HealthHealer(hooks={"retry": lambda *a, **k: ""})   # 模拟重试拿不到内容
        res = h.heal("MEDIUM", {"sid": "p1s"}, ["repeat", "broken_sentence", "off_topic"],
                     output=TABLE, question="你仔细查肯定不够12万的")
        ck("F", "二级治疗不再把病态原文原样交回",
           "预算 | 预算 | 预算 | 预算" not in (res.output or ""),
           (res.output or "")[:60].replace("\n", " "))
        ck("F", "二级治疗确实做了事（有动作）", bool(res.action), res.action)
        ck("F", "复查如实记录治完还有没有复读", "still_degenerate" in (res.detail or {}),
           (res.detail or {}).get("still_degenerate"))
        # 走真实健康门：3 个症状 → MEDIUM → 二级 → 出口仍然干净
        X.agent_run = _orig_agent
        H = X._health_layer()
        H["monitor"].reset()
        H["healer"].hooks["retry"] = lambda *a, **k: ""
        out, note = X._health_gate("你仔细查肯定不够12万的", TABLE, [])
        ck("F", "健康门（二级路径）交给用户的也不是刷屏", "预算 | 预算 | 预算 | 预算" not in out,
           out[:70].replace("\n", " "))
        ck("F", "二级会给用户一句提示", "重新组织" in (note or ""), (note or "")[:50])
    finally:
        X.agent_run = _orig_agent
        X._needs_continuation = _orig_cont

    # ===== G 端到端：续写里强制复读必须被掐断 =====
    print("\n[G] 端到端 · 续写里强制复读 → 自动掐断")
    import core.continuation as C
    st = {"n": 0}

    def bad_llm(messages, max_tokens, **kw):
        st["n"] += 1
        u = messages[-1]["content"]
        if "自然的结尾" in u:
            return "以上把这件事讲完了，先跑通再优化。"
        if st["n"] >= 2:
            return SLASH_BODY * 4
        return "".join("第%d步：载体按意图装配上下文，只装当前需要的一小块。\n" % i for i in range(1, 8))
    res = C.generate_unlimited("写一篇 3000 字的产品介绍", "你是小焦。", max_per_chunk=2000,
                               llm_fn=bad_llm, buffer_size=1)
    ck("G", "续写检测到复读并标记", res.get("degeneration") is True, res.get("stopped"))
    ck("G", "正文里没有成片的『预算 / 』", res["text"].count("预算 /") <= 20,
       "出现 %d 次" % res["text"].count("预算 /"))
    ck("G", "结尾落在完整句", res["text"].rstrip()[-1] in "。！？!?；;…", repr(res["text"][-14:]))

    print("\n" + "=" * 66)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % ", ".join(FAIL)) if FAIL else ""))
    print("=" * 66)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
