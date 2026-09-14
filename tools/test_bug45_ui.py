# -*- coding: utf-8 -*-
"""Bug 4 / Bug 5 自测（真跑 Flask 接口，不模拟）。

运行：python tools/test_bug45_ui.py

Bug 4 · 停止按钮生成完不消失
  判据：① ensureBubble 不再碰停止按钮；② cleanup() 一定在 finally 里；
        ③ 生成开始才挂出来；④ 收到结束信号（[DONE]）立刻收尾；⑤ 流结束后读流被关掉。
Bug 5 · 切会话再切回来卡在"正在回答…"
  判据：① 切会话前端先停旧流（断连 + 清标志）；② 切回来从历史全量渲染；
        ③ 没有人在生成时，占位符不能再装成"正在回答"；④ 生成到一半断开时，
           已经生成的部分要落盘（切回来能看到内容 + 中断说明）。

隔离性：整个测试用**临时会话文件**，绝不碰用户真实的 xiaojiao_sessions.json。
"""
import json
import os
import re
import sys
import tempfile
import threading
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import xiaojiao_app as X  # noqa: E402

PASS, FAIL = [], []


def ck(group, name, cond, info=""):
    (PASS if cond else FAIL).append("%s/%s" % (group, name))
    print("  %s [%s] %s%s" % ("✅" if cond else "❌", group, name,
                              ("  ← " + str(info)) if info else ""))


def _html():
    src = open(os.path.join(_ROOT, "xiaojiao_app.py"), encoding="utf-8").read()
    i = src.index('HTML = r"""') + len('HTML = r"""')
    return src[i:src.index('"""', i)]


def main():
    print("=" * 62)
    print("  Bug 4 / Bug 5 自测")
    print("=" * 62)

    # ===== 静态结构：Bug 4 的四条修法必须在代码里成立 =====
    print("\n[A] Bug 4 静态结构（前端生命周期）")
    html = _html()
    ck("A", "ensureBubble 里不再挂停止按钮",
       "const ensureBubble=()=>{if(bubble)return;if(th.parentNode)th.remove();" in html
       and "feed.appendChild(stopBtn)" in html)
    # 只看 ensureBubble 的**函数体本体**（到它的结束 `};` 为止），不含后面的注释 ——
    # 注释里本来就要写"以前这里会 appendChild(stopBtn)"，把注释算进去等于自己骗自己。
    _b0 = html.index("const ensureBubble=()=>{")
    _body = html[_b0:html.index("feed.appendChild(bubble);};", _b0) + len("feed.appendChild(bubble);};")]
    ck("A", "ensureBubble 函数体内不含 stopBtn", "stopBtn" not in _body,
       _body.replace("\n", " ")[:90])
    ck("A", "新增 cleanup() 且放进 finally",
       "const cleanup=()=>{" in html and "}finally{\n   cleanup();" in html)
    ck("A", "生成开始时才挂出停止按钮",
       html.index("feed.appendChild(stopBtn)") > html.index("const cleanup=()=>{"))
    ck("A", "收到 [DONE] 哨兵立刻收尾", "'[DONE]'" in html and "ended=true;break;" in html)
    ck("A", "流结束后主动放掉读流", "try{rd.cancel();}catch(e){}" in html)

    # ===== 后端：结束哨兵 + 生成状态注销 =====
    print("\n[B] Bug 4 后端：SSE 显式结束 + 生成状态一定被注销")
    tmpdir = tempfile.mkdtemp(prefix="bug45_")
    X.SESSIONS_FILE = os.path.join(tmpdir, "sessions.json")
    with open(X.SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump({"current": "s1", "sessions": [{"id": "s1", "title": "t", "messages": []}]}, f)

    _orig_agent = X.agent_run
    _orig_continuation = X._needs_continuation

    def fake_agent(user_input, lean=False, on_chunk=None, on_progress=None, on_delta=None):
        if on_delta:
            for i in range(0, 60, 12):
                on_delta("这是一段真实流出来的回答。"[i:i + 12])
                time.sleep(0.005)
        return "这是一段真实流出来的回答。", True, [], False, [{"tool": "get", "args": {}, "result": "ok"}]

    X.agent_run = fake_agent
    X._needs_continuation = lambda t: False          # 别让"写 xx 字"触发续写
    try:
        cli = X.app.test_client()
        r = cli.post("/api/chat/stream", json={"message": "你好"})
        body = r.get_data(as_text=True)
        ck("B", "SSE 返回 200", r.status_code == 200, r.status_code)
        ck("B", "流里有 done 事件", '"type": "done"' in body or '"type":"done"' in body)
        ck("B", "流末尾有 [DONE] 哨兵", body.rstrip().endswith("data: [DONE]"), repr(body[-40:]))
        ck("B", "流里有 delta 正文", '"type": "delta"' in body)
        ck("B", "结束后生成状态已注销（不残留）", not X._inflight_has("s1"), X._inflight_all())
        # 会话里那条占位符必须被替换成真实回答
        s = json.load(open(X.SESSIONS_FILE, encoding="utf-8"))
        msgs = s["sessions"][0]["messages"]
        ck("B", "占位符被回填成真实回答",
           msgs and "__pending__" not in msgs[-1]["content"] and "真实流出来" in msgs[-1]["content"],
           msgs[-1]["content"][:30] if msgs else None)
    finally:
        X.agent_run = _orig_agent
        X._needs_continuation = _orig_continuation

    # ===== Bug 5：孤儿占位符不能装成"正在回答" =====
    print("\n[C] Bug 5：没人在生成时，占位符一律标成「中断了」")
    with open(X.SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump({"current": "s2",
                   "sessions": [{"id": "s2", "title": "t",
                                 "messages": [{"role": "用户", "content": "写一篇长文"},
                                              {"role": "小焦", "content": "⏳__pending__"}]}]}, f)
    cli = X.app.test_client()
    d = cli.get("/api/session/s2").get_json()
    ck("C", "打开会话：generating=False", d.get("generating") is False, d.get("generating"))
    ck("C", "孤儿占位符被就地清理成中断说明",
       "__pending__" not in json.dumps(d["messages"], ensure_ascii=False)
       and "中断" in json.dumps(d["messages"], ensure_ascii=False), d["messages"][-1]["content"][:40])
    p = cli.get("/api/chat/pending").get_json()
    ck("C", "/api/chat/pending 不再谎报 pending", p.get("pending") is False, p)
    ck("C", "并如实标了 interrupted", p.get("interrupted") is True or "中断" in (p.get("content") or ""), p)

    # 真在生成时 → 必须仍然是"正在回答"
    with open(X.SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump({"current": "s3",
                   "sessions": [{"id": "s3", "title": "t",
                                 "messages": [{"role": "用户", "content": "写一篇长文"},
                                              {"role": "小焦", "content": "⏳__pending__"}]}]}, f)
    X._inflight_begin("s3")
    d3 = cli.get("/api/session/s3").get_json()
    ck("C", "真在生成时：generating=True（不误杀）", d3.get("generating") is True, d3.get("generating"))
    ck("C", "真在生成时：占位符保留", "__pending__" in json.dumps(d3["messages"], ensure_ascii=False))
    ck("C", "真在生成时：pending=True", cli.get("/api/chat/pending").get_json().get("pending") is True)
    X._inflight_end("s3")

    # ===== Bug 5：生成到一半断开 → 已生成部分落盘 =====
    print("\n[D] Bug 5：生成到一半断开 → 已生成部分落盘")
    with open(X.SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump({"current": "s4",
                   "sessions": [{"id": "s4", "title": "t",
                                 "messages": [{"role": "用户", "content": "写一篇长文"},
                                              {"role": "小焦", "content": "⏳__pending__"}]}]}, f)
    partial = "已经把开头的三个要点写完了，分别是目标、边界和验收口径。" * 2
    ok = X._flush_partial_answer("s4", partial)
    got = json.load(open(X.SESSIONS_FILE, encoding="utf-8"))["sessions"][0]["messages"][-1]["content"]
    ck("D", "落盘成功", ok is True)
    ck("D", "已生成的部分真的写回了会话", partial[:20] in got, got[:40])
    ck("D", "并附上中断说明", "中断" in got, got[-30:])
    ck("D", "占位符已消失", "__pending__" not in got)
    # 太短的内容不写正文，只留中断说明（半句话比没有更让人困惑）
    with open(X.SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump({"current": "s5",
                   "sessions": [{"id": "s5", "title": "t",
                                 "messages": [{"role": "小焦", "content": "⏳__pending__"}]}]}, f)
    X._flush_partial_answer("s5", "刚开头")
    got5 = json.load(open(X.SESSIONS_FILE, encoding="utf-8"))["sessions"][0]["messages"][-1]["content"]
    ck("D", "内容过短时不写半句话，只留中断说明", "刚开头" not in got5 and "中断" in got5, got5[:40])

    # ===== Bug 5：客户端断开时，生成器 finally 也会收尾 =====
    print("\n[E] Bug 5：客户端提前断开 → 生成器 finally 仍收尾（不残留『正在回答』）")
    with open(X.SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump({"current": "s6", "sessions": [{"id": "s6", "title": "t", "messages": []}]}, f)
    started = threading.Event()

    def slow_agent(user_input, lean=False, on_chunk=None, on_progress=None, on_delta=None):
        started.set()
        if on_delta:
            on_delta("第一段已经写出来的内容，足够长了，应该被落盘。" * 3)
        time.sleep(3.0)                       # 拖住，让客户端有时间断开
        return "完整回答", True, [], False, []

    X.agent_run = slow_agent
    X._needs_continuation = lambda t: False
    try:
        rv = cli.post("/api/chat/stream", json={"message": "写一篇长文"},
                      buffered=False)
        # 只读一点点就把连接关掉 —— 模拟"切会话/关页面"
        it = rv.response
        next(iter(it))
        rv.close()
        started.wait(timeout=3)
        time.sleep(1.2)                       # 让服务端走完 finally
        ck("E", "断开后生成状态被注销", not X._inflight_has("s6"), X._inflight_all())
        got6 = json.load(open(X.SESSIONS_FILE, encoding="utf-8"))["sessions"][0]["messages"][-1]["content"]
        ck("E", "断开后占位符不残留（不再是正在回答）", "__pending__" not in got6, got6[:40])
        ck("E", "断开后如实标了中断或落盘了已生成内容",
           ("中断" in got6) or ("第一段" in got6), got6[:40])
    finally:
        X.agent_run = _orig_agent
        X._needs_continuation = _orig_continuation

    # ===== F 问题 2：竞态（"时好时坏"的根因）=====
    print("\n[F] 问题 2：切会话竞态 —— 生成器没被关掉时不能永久卡住")
    with open(X.SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump({"current": "s7",
                   "sessions": [{"id": "s7", "title": "t",
                                 "messages": [{"role": "用户", "content": "写一篇长文"},
                                              {"role": "小焦", "content": "⏳__pending__"}]}]}, f)
    # ① 在册但心跳已经停了 → 必须判"死了"（这正是"客户端断开、生成器没被关"的现场）
    X._inflight_begin("s7")
    with X._INFLIGHT_LOCK:
        X._INFLIGHT["s7"]["at"] = time.time() - (X._INFLIGHT_DEAD_S + 5)
    ck("F", "心跳停了 → generating=False（不再假装在生成）",
       cli.get("/api/session/s7").get_json().get("generating") is False)
    ck("F", "心跳停了 → 占位符被标成中断",
       "中断" in json.dumps(cli.get("/api/session/s7").get_json()["messages"], ensure_ascii=False))
    ck("F", "死掉的在册项被回收", "s7" not in X._inflight_all(), list(X._inflight_all()))
    # ② 心跳是新的 → 必须仍然算"在生成"（不能把活的误判成死的）
    with open(X.SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump({"current": "s8",
                   "sessions": [{"id": "s8", "title": "t",
                                 "messages": [{"role": "小焦", "content": "⏳__pending__"}]}]}, f)
    X._inflight_begin("s8")
    X._inflight_tick("s8")
    ck("F", "心跳是新的 → generating=True（活的不会被误杀）",
       cli.get("/api/session/s8").get_json().get("generating") is True)
    ck("F", "心跳是新的 → 占位符保留", "__pending__" in json.dumps(
        cli.get("/api/session/s8").get_json()["messages"], ensure_ascii=False))
    X._inflight_end("s8")
    # ③ /api/chat/abandon：前端 3 秒超时后的强制清标志（**死轮**：心跳早停了）
    with open(X.SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump({"current": "s9",
                   "sessions": [{"id": "s9", "title": "t",
                                 "messages": [{"role": "小焦", "content": "⏳__pending__"}]}]}, f)
    X._inflight_begin("s9")
    with X._INFLIGHT_LOCK:
        X._INFLIGHT["s9"]["at"] = time.time() - (X._INFLIGHT_DEAD_S + 5)
    ab = cli.post("/api/chat/abandon", json={"session_id": "s9"}).get_json()
    ck("F", "对死轮：abandon 报 was_alive=False", ab.get("was_alive") is False, ab)
    ck("F", "对死轮：abandon 撤掉了注册项", X._inflight_has("s9", max_idle=999) is False)
    ck("F", "对死轮：abandon 之后界面不再显示正在生成",
       cli.get("/api/session/s9").get_json().get("generating") is False)
    ck("F", "对死轮：占位符已清成中断",
       "__pending__" not in json.dumps(cli.get("/api/session/s9").get_json()["messages"],
                                      ensure_ascii=False))
    # ④ abandon 不许误伤"真的还在跑"的轮：只让它从界面消失，绝不动占位符
    #    （动了占位符 = 那一轮结束时回填不进去 = 半截内容永久丢）
    with open(X.SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump({"current": "s10",
                   "sessions": [{"id": "s10", "title": "t",
                                 "messages": [{"role": "小焦", "content": "⏳__pending__"}]}]}, f)
    X._inflight_begin("s10")
    X._inflight_tick("s10")
    ab2 = cli.post("/api/chat/abandon", json={"session_id": "s10"}).get_json()
    ck("F", "对活轮：abandon 如实报 was_alive=True", ab2.get("was_alive") is True, ab2)
    s10 = cli.get("/api/session/s10").get_json()
    ck("F", "对活轮：界面不再转圈（generating=False）", s10.get("generating") is False)
    ck("F", "对活轮：在册状态仍在（alive=True，它还能回填内容）", s10.get("alive") is True, s10.get("alive"))
    got10 = json.dumps(s10["messages"], ensure_ascii=False)
    ck("F", "对活轮：占位符**一个字没动**（否则答案会丢）", "__pending__" in got10, got10[:60])
    X._inflight_end("s10")

    # ===== F2 心跳：活着的轮自己证明自己活着 =====
    print("\n[F2] 心跳：长时间没有输出也不会被误判成死")
    with open(X.SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump({"current": "s11", "sessions": [{"id": "s11", "title": "t", "messages": []}]}, f)
    started = threading.Event()

    def hold_agent(*a, **k):
        started.set()
        time.sleep(X._INFLIGHT_HEARTBEAT_S * 2 + 1.0)     # 全程不产出任何内容
        return "拖了很久但活着", True, [], False, []
    X.agent_run = hold_agent
    X._needs_continuation = lambda t: False
    try:
        rv = cli.post("/api/chat/stream", json={"message": "慢慢来"}, buffered=False)
        it = rv.response
        next(iter(it))                                     # 拿到第一个事件（session 事件）
        started.wait(timeout=3)
        time.sleep(X._INFLIGHT_HEARTBEAT_S + 1.0)
        ck("F2", "静默 %d 秒后仍算『活着』（心跳在顶时间戳）" % int(X._INFLIGHT_HEARTBEAT_S + 1),
           X._inflight_has("s11") is True, "idle=%.1fs" % (X._inflight_idle("s11") or -1))
        ck("F2", "静默期间占位符不会被误清",
           "__pending__" in json.dumps(json.load(open(X.SESSIONS_FILE, encoding="utf-8")),
                                       ensure_ascii=False))
        rv.close()
        time.sleep(1.2)
    finally:
        X.agent_run = _orig_agent
        X._needs_continuation = _orig_continuation

    print("\n" + "=" * 62)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % ", ".join(FAIL)) if FAIL else ""))
    print("=" * 62)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
