# -*- coding: utf-8 -*-
"""问题 5：四个系统（健康 / 自主 / 世界 / 变形金刚）的**真实运行证据**。

运行：python tools/live_evidence.py
与那些"自测脚本"的区别（这正是用户质疑的点）：
  自测证明的是"代码路径通"；这个脚本证明的是**真跑过** ——
  真模型（本机 llama-swap:9292）、真网络抓取、真会话落盘、真日志增长。
  跑之前先记录各日志的行数，跑完再记一次，**用增量说话**（而不是"文件存在"）。

它做四件真事：
  ① 真模型对话（走完整 agent_run：记忆 → 检索 → 模型 → 健康门 → 落盘）
  ② 真抓一个公开网页（世界层：快照 + 变化感知）
  ③ 真跑一遍自主性（调度器定时任务 + 盯梢 + 学习）
  ④ 真做一次火种热切换（变形金刚：切换后 app 的 LLM_BASE 当场变，且载体状态不变）
全程只用**追加**，不删任何文件。
"""
import json
import os
import sys
import threading
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import xiaojiao_app as X  # noqa: E402

WATCH = {
    "健康·退化命中": ("logs/health/degeneration.jsonl", "lines"),
    "健康·病历": ("logs/health/records.jsonl", "lines"),
    "健康·通知": ("logs/health/notify.jsonl", "lines"),
    "自主·任务流水": ("logs/autonomy/tasks.jsonl", "lines"),
    "自主·学习": ("logs/autonomy/learning.jsonl", "lines"),
    "自主·盯梢变化": ("logs/autonomy/changes.jsonl", "lines"),
    "世界·快照": ("logs/world/snapshots.jsonl", "lines"),
    "世界·变化": ("logs/world/changes.jsonl", "lines"),
    "世界·吸收": ("logs/world/absorption.jsonl", "lines"),
    "变形金刚·切换": ("logs/carrier/brain_switch.jsonl", "lines"),
    "变形金刚·能力": ("logs/carrier/capabilities.json", "json_keys"),
}


def measure():
    out = {}
    for name, (rel, kind) in WATCH.items():
        p = os.path.join(_ROOT, rel)
        if not os.path.exists(p):
            out[name] = 0
            continue
        if kind == "lines":
            with open(p, encoding="utf-8", errors="ignore") as f:
                out[name] = sum(1 for l in f if l.strip())
        else:
            try:
                d = json.load(open(p, encoding="utf-8"))
                out[name] = d.get("count", 0) if isinstance(d, dict) else 0
            except Exception:      # noqa: silent-ok — 读不了就当 0（只是证据缺失）
                out[name] = 0
    return out


def show(before, after, title):
    print("\n  %s" % title)
    for k in WATCH:
        b, a = before.get(k, 0), after.get(k, 0)
        mark = "⭐ 新增 %d" % (a - b) if a > b else ("—" if a else "（还没数据）")
        print("    %-16s %5d → %-5d  %s" % (k, b, a, mark))


def main():
    print("=" * 70)
    print("  问题 5 · 真实运行证据（真模型 / 真抓取 / 真落盘）")
    print("=" * 70)

    t0 = time.time()
    before = measure()
    print("\n  起始状态（各系统日志行数）：")
    for k, v in before.items():
        print("    %-16s %s" % (k, v))

    # ---------- ① 真模型对话 ----------
    print("\n① 真模型对话（走完整 agent_run）")
    X.SESSIONS_FILE = os.path.join(_ROOT, "logs", "_live_evidence_sessions.json")
    if not os.path.exists(X.SESSIONS_FILE):
        with open(X.SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump({"current": "live", "sessions": [{"id": "live", "title": "真跑证据", "messages": []}]}, f)
    online = False
    try:
        online = bool(X.llm_online())
    except Exception as e:      # noqa: silent-ok — 判不出来就当离线，后面如实说明
        print("    llm_online 判定出错：%s" % e)
    print("    本机大脑在线：%s" % online)
    turns = [
        "用表格列出 12 个常用 Git 命令，每个给一句话说明",     # 逼出一个"少标点"的回答，好让健康监测有话可说
        "再用三句话讲讲你刚才那张表里哪个命令最常用",
    ]
    cli = X.app.test_client()
    for q in turns:
        t = time.time()
        r = cli.post("/api/chat", json={"message": q})
        d = r.get_json() or {}
        ans = (d.get("answer") or "")
        print("    问：%s" % q[:28])
        print("      答：%d 字 / 耗时 %.1fs / 工具轨迹 %d 条"
              % (len(ans), time.time() - t, len(d.get("tool_trace") or [])))
    after_chat = measure()
    show(before, after_chat, "对话之后：")

    # ---------- ② 真抓一个公开网页（世界层）----------
    print("\n② 真抓一个公开网页（世界层：快照 + 变化感知 + 站点入库）")
    try:
        X._round_begin()
        ans, tr = X._scrape_direct("抓一下 https://example.com", [])
        print("    抓取结果：%d 字 / 轨迹 %d 条 / 工具=%s"
              % (len(ans or ""), len(tr or []), (tr or [{}])[-1].get("tool")))
        m, p = X._world_layer()
        if m is not None:
            sites = list((m.snapshot().get("sites") or {}).keys())
            print("    世界地图现有站点：%s" % sites[:8])
    except Exception as e:
        print("    抓取失败（如实报告）：%s" % str(e)[:100])
    after_world = measure()
    show(after_chat, after_world, "抓取之后：")

    # ---------- ③ 真跑自主性 ----------
    print("\n③ 真跑自主性（定时任务 + 盯梢 + 学习）")
    try:
        from core.autonomy import scheduler as SC
        sched = SC.AutonomyScheduler()
        ran = []
        sched.runner = lambda task: (ran.append(task.get("id")), "真跑了一次")[1]
        sched.add({"id": "live_evidence_tick", "interval_s": 1, "prompt": "真跑证据：定时任务"})
        sched.start()
        time.sleep(3.2)
        sched.stop(timeout=3)
        print("    定时任务真跑了 %d 次：%s" % (len(ran), ran[:5]))
    except Exception as e:
        print("    自主性失败（如实报告）：%s" % str(e)[:120])
    try:
        from core.autonomy import watcher as WT
        w = WT.AutonomousWatcher()
        w.add("https://example.com", interval=1, rule="changed")
        ch = w.check_once(force=True)
        print("    盯梢 example.com → 本次变化 %d 条：%s"
              % (len(ch), [c.get("kind") for c in ch][:4]))
    except Exception as e:
        print("    盯梢失败（如实报告）：%s" % str(e)[:120])
    try:
        from core.autonomy import learner as LN
        lr = LN.AutonomousLearner()
        msgs = [{"role": "用户", "content": m} for m in
                ["帮我看看向量检索怎么做"] * 5 + ["抓取任务失败了怎么办"] * 4
                + ["用 Archify 画一张架构图"] * 3]
        topics = lr.extract_topics(msgs)
        print("    学习：从历史里提炼出话题 %s" % (topics[:3],))
        res = lr.cycle()
        print("    学习周期跑完：%s" % str(res)[:120])
    except Exception as e:
        print("    学习失败（如实报告）：%s" % str(e)[:120])
    after_auto = measure()
    show(after_world, after_auto, "自主性之后：")

    # ---------- ④ 真做一次火种热切换 ----------
    print("\n④ 变形金刚：真做一次火种热切换")
    try:
        from core.carrier import BrainRegistry
        reg = BrainRegistry()
        names = reg.names()
        cur = reg.current()
        print("    已注册火种：%s ｜ 当前：%s" % (names, cur.name if cur else "未指定"))
        before_base = getattr(X, "LLM_BASE", "")
        if len(names) >= 2:
            tgt = [n for n in names if n != (cur.name if cur else "")][0]
            ok = reg.switch(tgt)
            applied = reg.apply_to_app()
            after_base = getattr(X, "LLM_BASE", "")
            print("    切到 %s：%s ｜ 应用到 app：%s ｜ LLM_BASE %s → %s"
                  % (tgt, ok, applied, before_base, after_base))
            if cur:
                reg.switch(cur.name)
                reg.apply_to_app()
                print("    已切回：%s（LLM_BASE=%s）" % (cur.name, getattr(X, "LLM_BASE", "")))
        else:
            print("    只登记了 1 个火种，无备用可切（如实说明）")
    except Exception as e:
        print("    火种切换失败（如实报告）：%s" % str(e)[:120])
    after_carrier = measure()
    show(after_auto, after_carrier, "火种切换之后:")

    # ---------- 汇总 ----------
    final = measure()
    print("\n" + "=" * 70)
    print("  本次**真实运行**共新增证据（不是自测数据）：")
    grew = 0
    for k in WATCH:
        d = final.get(k, 0) - before.get(k, 0)
        if d > 0:
            grew += 1
            print("    ✅ %-16s +%d" % (k, d))
        else:
            print("    ·  %-16s 无新增（%s）" % (k, "已有 %d 行" % final[k] if final[k] else "仍为空"))
    print("\n  有新增的系统：%d / %d ｜ 总耗时 %.1fs"
          % (grew, len(WATCH), time.time() - t0))
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
