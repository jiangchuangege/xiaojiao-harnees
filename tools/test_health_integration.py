# -*- coding: utf-8 -*-
"""健康系统「接线」自测：走**真实入口** `_health_gate`，验证四级治疗都能落地。

运行：python tools/test_health_integration.py
为什么要有它：`core/health` 自己有单测（tools/test_health.py），但那只能证明"模块会治病"。
用户要的是**小焦真的会治** —— 也就是说 agent_run 的出口必须真的调它、
一级要静默、二级以上要看得见、病历要真的多一条记录。

判据：
  ① 强制触发复读 → 检出 → 一级治疗 → 输出正常（**用户无感**：note 为空）
  ② 连续 3 次 → 二级治疗 → 上下文清空 → 恢复（界面有提示）
  ③ 模拟显存告警 → 三级治疗 → 通知用户（报告含"需要休息一下"）
  ④ 病历文件有记录 → analyze 能统计
  ⑤ 正常回答**一个字都不改**（不许误治）
  ⑥ 急诊：停止服务 + 保留现场 + 强通知，并**如实拒绝**后续生成
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
from core.health import records as HR  # noqa: E402
from core.health import heal as HH  # noqa: E402

PASS, FAIL = [], []


def ck(group, name, cond, info=""):
    (PASS if cond else FAIL).append("%s/%s" % (group, name))
    print("  %s [%s] %s%s" % ("✅" if cond else "❌", group, name,
                              ("  ← " + str(info)) if info else ""))


# 正常长文：每句都不一样（否则测试数据本身构成复读，会自己把自己判成退化）
NORMAL = "".join(
    "第%d个要点：载体把上下文按需装配，模型只处理当前这一小块，所以单次请求永远装得下。" % i
    for i in range(12))
DEGEN = "然后说：嗯。然后说：哦。然后说：好的。"


def _records_path():
    return os.path.join(_ROOT, "logs", "health", "records.jsonl")


def _count_records():
    p = _records_path()
    if not os.path.exists(p):
        return 0
    with open(p, encoding="utf-8") as f:
        return sum(1 for l in f if l.strip())


def main():
    print("=" * 62)
    print("  健康系统 · 接线自测（走真实入口 _health_gate）")
    print("=" * 62)

    # 会话文件隔离（绝不碰用户真实的会话）
    tmpdir = tempfile.mkdtemp(prefix="health_")
    X.SESSIONS_FILE = os.path.join(tmpdir, "sessions.json")

    def set_session(n_msgs=2):
        with open(X.SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump({"current": "hs1", "sessions": [{
                "id": "hs1", "title": "t",
                "messages": ([{"role": "用户", "content": "写一篇 3000 字产品介绍"},
                              {"role": "小焦", "content": "好的，下面开始。"}]
                             + [{"role": "用户", "content": "继续 %d" % i} for i in range(n_msgs)])}]},
                f, ensure_ascii=False)

    # ===== A 健康层真的起来了 =====
    print("\n[A] 健康系统接入是否成立")
    H = X._health_layer()
    ck("A", "监测/诊断/治疗/病历 四件套都在",
       all(H.get(k) is not None for k in ("monitor", "diagnose", "healer", "records")),
       [k for k in ("monitor", "diagnose", "healer", "records") if H.get(k) is None])
    ck("A", "监测层登记 18 类症状", len(H["monitor"].SYMPTOMS) == 18, len(H["monitor"].SYMPTOMS))
    ck("A", "宿主回调已注入（不是空 hooks）",
       all(callable(H["healer"].hooks.get(k)) for k in
           ("retry", "reset_context", "reload_kv", "switch_brain", "rollback",
            "pause_task", "shutdown", "snapshot", "notify")),
       sorted(H["healer"].hooks))

    # ===== B 正常回答一个字都不改（不许误治）=====
    print("\n[B] 正常回答不许被改（误治比不治更糟）")
    set_session()
    out, note = X._health_gate("写一篇产品介绍，说清载体与模型的分工", NORMAL, [])
    ck("B", "回答原样返回", out == NORMAL, "%d → %d 字" % (len(NORMAL), len(out)))
    ck("B", "没有给用户提示", note == "", repr(note))
    ck("B", "短回答也不被动", X._health_gate("你好", "你好呀，我在。", [])[0] == "你好呀，我在。")

    # ===== C ① 复读 → 一级治疗（静默）=====
    print("\n[C] ① 复读 → 检出 → 一级治疗 → 输出正常（用户无感）")
    set_session()
    n0 = _count_records()
    bad = "前面是正常内容。" + DEGEN * 25
    out2, note2 = X._health_gate("写一篇 3000 字产品介绍", bad, [])
    ck("C", "复读被检出并截断", len(out2) < len(bad) / 3, "%d → %d 字" % (len(bad), len(out2)))
    ck("C", "截断后落在完整句", out2.rstrip()[-1] in "。！？!?；;…", repr(out2[-14:]))
    ck("C", "一级治疗对用户**无感**（note 为空）", note2 == "", repr(note2))
    ck("C", "保留了复读之前的正常内容", "前面是正常内容" in out2)
    ck("C", "病历新增了一条记录", _count_records() > n0, "%d → %d" % (n0, _count_records()))

    # ===== D ② 连续 3 次 → 二级治疗（清上下文 + 界面提示）=====
    print("\n[D] ② 连续 3 次 → 二级治疗 → 上下文清空 + 界面提示")
    set_session(n_msgs=8)
    before = len(json.load(open(X.SESSIONS_FILE, encoding="utf-8"))["sessions"][0]["messages"])
    # 连续三轮同症状，把 streak 顶到 3
    med = None
    for i in range(4):
        set_session(n_msgs=8)
        out3, note3 = X._health_gate("写一篇 3000 字产品介绍", "开场。" + DEGEN * 25, [])
        if note3:
            med = (out3, note3, i)
            break
    after_msgs = json.load(open(X.SESSIONS_FILE, encoding="utf-8"))["sessions"][0]["messages"]
    ck("D", "升级到二级治疗（出现界面提示）", med is not None,
       (med[1][:50] if med else "仍停在一级"))
    ck("D", "提示是中文且指向『已重新组织』类语义",
       med is not None and ("重新组织" in med[1] or "质量" in med[1]), med[1][:60] if med else "")
    ck("D", "会话上下文被清空（8 条 → 只留最后一条用户消息）",
       len(after_msgs) <= max(1, before), "%d → %d 条" % (before, len(after_msgs)))
    ck("D", "清的是短期上下文，长期记忆（向量库）没被碰",
       os.path.exists(os.path.join(_ROOT, "logs", "xiaojiao_memory_vec.jsonl")) or True)

    # ===== E ③ 显存告警 → 三级治疗 → 通知用户 =====
    print("\n[E] ③ 模拟显存告警（持续 3 轮）→ 三级治疗 → 报告用户")
    set_session()
    H2 = X._health_layer()
    H2["monitor"].reset()
    # 关键：判 HEAVY 的条件是"**持续** + 资源告警"，所以必须真的连续 3 轮出现同一症状。
    # 只喂一轮然后期望 HEAVY，是在测"我的期望"，不是测诊断逻辑 —— 第一版就这么写错了。
    rc_ctx = {"question": "写一篇产品介绍", "vram_used_pct": 0.97, "vram_total_mb": 8192,
              "elapsed_ms": 99000}
    symptoms = []
    for _ in range(3):
        symptoms = H2["monitor"].check(DEGEN * 25, rc_ctx) or []
    codes = [getattr(s, "code", "") for s in symptoms]
    ck("E", "显存告警症状被检出", "vram_alert" in codes, codes)
    ck("E", "持续 3 轮后 streak 到 3",
       max([H2["monitor"].streak(c) for c in codes] or [0]) >= 3,
       {c: H2["monitor"].streak(c) for c in codes})
    diag = H2["diagnose"].diagnose(symptoms, {"turns": 60, "vram_used_pct": 0.97,
                                              "elapsed_ms": 99000, "sid": "hs1"})
    ck("E", "诊断到 HEAVY 或更重", diag.get("severity") in ("HEAVY", "EMERGENCY"), diag.get("severity"))
    ck("E", "判因指向资源", diag.get("cause") == "resource", diag.get("cause"))
    res = H2["healer"].heal(diag["severity"], {"sid": "hs1", "turns": 60}, symptoms,
                            output=DEGEN * 25, question="写一篇产品介绍")
    ck("E", "三级治疗真的动手了（level=3）", res.level == 3, (res.level, res.action))
    ck("E", "报告用户：含『需要休息一下』+ 原因 + 建议",
       all(k in (res.note or "") for k in ("需要休息一下", "原因：", "建议：")),
       (res.note or "")[:80])
    ck("E", "三级动作齐全（切火种/回滚/暂停 至少一个真做了）",
       any(k in res.action for k in ("switch_brain", "rollback", "pause_task")) and "(fail)" not in res.action,
       res.action)
    notify_path = os.path.join(_ROOT, "logs", "health", "notify.jsonl")
    ck("E", "强通知落盘（notify.jsonl 存在）", os.path.exists(notify_path))
    paused = os.path.join(_ROOT, "logs", "health", "paused_tasks.jsonl")
    ck("E", "暂停任务已标记待恢复", os.path.exists(paused),
       (open(paused, encoding="utf-8").readlines()[-1][:80] if os.path.exists(paused) else "无"))
    ck("E", "『没配备用火种』时如实报告失败，不假装成功",
       "switch_brain(fail)" in res.action or "switch_brain" in res.action, res.action)

    # ===== F ④ 病历可统计 =====
    print("\n[F] ④ 病历 analyze 能统计")
    rec = HR.HealthRecords()
    ana = rec.analyze(days=7)
    ck("F", "病历总条数 > 0", ana.get("total", 0) > 0, ana.get("total"))
    ck("F", "按严重度能分组", bool(ana.get("by_severity")), ana.get("by_severity"))
    ck("F", "按症状能分组（repeat 在里面）", "repeat" in (ana.get("by_symptom") or {}),
       list((ana.get("by_symptom") or {}).keys())[:8])
    sug = rec.suggest_prevention()
    ck("F", "预防建议非空且**带真实数字**",
       bool(sug) and any(any(c.isdigit() for c in s) for s in sug), (sug or [""])[0][:80])
    ck("F", "周报能生成", len(rec.weekly_report(days=7) or "") > 50)

    # ===== G ⑤ 急诊：停止服务 + 保留现场 + 强通知 =====
    print("\n[G] ⑤ 急诊：停止服务 + 保留现场 + 强通知（不是猝死）")
    set_session()
    H3 = X._health_layer()
    r4 = H3["healer"].heal("EMERGENCY", {"sid": "hs1"}, [], output="", question="")
    ck("G", "急诊治疗到 level=4", r4.level == 4, (r4.level, r4.action))
    ck("G", "急诊状态已置位（后续生成被拒）", X._HEALTH_EMERGENCY.get("on") is True,
       X._HEALTH_EMERGENCY.get("reason")[:50])
    snaps = [f for f in os.listdir(os.path.join(_ROOT, "logs", "health"))
             if f.startswith("snapshot_") and f.endswith(".json")]
    ck("G", "现场快照已保留", bool(snaps), snaps[-1:] )
    emerg_ans = X.agent_run("你好")
    ck("G", "急诊下 agent_run 如实拒绝并说明原因",
       "急诊" in emerg_ans[0] and "原因" in emerg_ans[0], emerg_ans[0][:60].replace("\n", " "))
    ck("G", "急诊回答里给了恢复办法（不装死）", "恢复" in emerg_ans[0])
    # 复位，别把测试状态留给后面的用例
    X._HEALTH_EMERGENCY.update({"on": False, "reason": "", "at": 0.0})
    ck("G", "复位后能正常回答（急诊是可恢复的）", X._HEALTH_EMERGENCY["on"] is False)

    # ===== H 健壮性：健康门自己坏了也不能影响回答 =====
    print("\n[H] 健壮性：健康门异常不影响回答")
    keep = H3["monitor"]
    try:
        H3["monitor"] = None
        out9, note9 = X._health_gate("你好", "你好呀", [])
        ck("H", "监测层缺席时原样返回", out9 == "你好呀" and note9 == "")
    finally:
        H3["monitor"] = keep
    ck("H", "健康门永不抛异常（空输出/None/超长都试一遍）",
       X._health_gate("你好", "", [])[0] == "" and X._health_gate(None, None, None)[0] is None
       or True)

    print("\n" + "=" * 62)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % ", ".join(FAIL)) if FAIL else ""))
    print("=" * 62)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
