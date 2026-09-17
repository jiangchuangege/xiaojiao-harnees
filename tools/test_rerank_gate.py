# -*- coding: utf-8 -*-
"""`core/retriever.rerank` 两处改动的判据自测（离线，不调大脑 —— 判官用假的）。

【为什么还要这个】用户给的验证脚本只覆盖了"判官不可用"那条路（`judge=None`）。
但这次改动还有第二处（RERANK_GAP 0.10 → 0.50），它的效果是"**以前会跳过、现在要跑**"——
必须用**假判官**证明"判官真的被调到了"，否则等于没验。

钉六条：
  ① RERANK_GAP 是 0.50
  ② 领先 0.236（< 0.50）→ **精排真的跑了**（假判官被调用）← 这是本次改动的核心
  ③ 领先 0.60（≥ 0.50）→ **仍然跳过精排**（机制保留，不是关掉）
  ④ 判官在时：**尊重它挑的那几条**（载体不越权改它的判断）
  ⑤ 判官说"全不相关"→ 仍保守保留（这条**故意没改**，如实钉住）
  ⑥ 判官不可用 + 分数在 `decayed` 上（生产链的形状）：也能按阈值卡

运行：python tools/test_rerank_gate.py
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from core import retriever as R  # noqa: E402

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)[:150]) if info else ""))


Q = "服务器安全这块我该注意什么"          # 不含地名，避免走"点名了地方"的分支


def main():
    print("一、常量")
    ck("RERANK_GAP = 0.50", float(R.RERANK_GAP) == 0.50, R.RERANK_GAP)
    ck("THRESHOLD = 0.60（没被动过）", float(R.THRESHOLD) == 0.60, R.THRESHOLD)

    print("\n二、领先 0.236：以前跳过、现在必须跑（本次改动核心）")
    hits = [
        {"text": "上次服务器被入侵是弱密码导致的", "score": 0.82, "decayed": 0.90},
        {"text": "防火墙规则需要定期检查", "score": 0.75, "decayed": 0.664},   # 差 0.236
        {"text": "用户最近在学游泳", "score": 0.45, "decayed": 0.40},
    ]
    calls = []

    def _judge(prompt):
        calls.append(prompt)
        return "1"               # 只挑第 1 条

    keep, rec = R.rerank(Q, [dict(h) for h in hits], judge=_judge)
    ck("精排**真的跑了**（假判官被调用 1 次）", len(calls) == 1, len(calls))
    ck("尊重判官的结果（只剩它挑的那条）", [h["text"] for h in keep] == ["上次服务器被入侵是弱密码导致的"],
       [h["text"] for h in keep])
    ck("判官在时**不再**按阈值卡（1 条 0.45 也交给它看了）",
       all(h["text"] != "用户最近在学游泳" for h in keep), [h["text"] for h in keep])

    print("\n三、领先 0.60：仍然跳过精排（机制保留）")
    hits2 = [
        {"text": "甲", "score": 0.90, "decayed": 0.90},
        {"text": "乙", "score": 0.30, "decayed": 0.30},   # 差 0.60 ≥ 0.50
        {"text": "丙", "score": 0.20, "decayed": 0.20},
    ]
    calls2 = []
    keep2, rec2 = R.rerank(Q, [dict(h) for h in hits2], judge=lambda p: calls2.append(p) or "1")
    ck("判官**没被调用**（跳过精排）", len(calls2) == 0, len(calls2))
    ck("如实写明为什么跳过", "跳过精排" in rec2, rec2)
    ck("候选原样保留", len(keep2) == 3, len(keep2))

    print("\n四、判官说「全不相关」→ 仍保守保留（这条**故意没改**，如实钉住）")
    keep3, rec3 = R.rerank(Q, [{"text": "甲", "score": 0.9, "decayed": 0.9},
                               {"text": "乙", "score": 0.8, "decayed": 0.5}],
                           judge=lambda p: "无")
    ck("保守保留（不清空记忆）", len(keep3) == 2, len(keep3))
    ck("如实标注", "保守保留" in rec3, rec3)

    print("\n五、判官不可用 + 分数在 `decayed` 上（生产链的真实形状）")
    hits5 = [
        {"text": "相关的", "decayed": 0.71},
        {"text": "也很相关", "decayed": 0.66},
        {"text": "不相关", "decayed": 0.31},
    ]
    keep5, rec5 = R.rerank(Q, [dict(h) for h in hits5], judge=None)
    ck("按 decayed 卡阈值也能工作（0.31 被卡掉）", len(keep5) == 2, [h["text"] for h in keep5])
    ck("记录里写了保留/卡掉的条数", "保留 2/3" in rec5 and "卡掉 1" in rec5, rec5)

    print("\n六、判官不可用 + 全低分 → 至少留 top1（不空手而归）")
    keep6, rec6 = R.rerank(Q, [{"text": "甲", "decayed": 0.4}, {"text": "乙", "decayed": 0.3}],
                           judge=None)
    ck("保留 1 条（top1）", len(keep6) == 1 and keep6[0]["text"] == "甲", [h["text"] for h in keep6])
    ck("如实写明「不空手而归」", "不空手而归" in rec6, rec6)

    print("\n" + "=" * 66)
    print("rerank 两处改动判据自测：通过 %d / 共 %d" % (len(PASS), len(PASS) + len(FAIL)))
    if FAIL:
        print("❌ 失败：%s" % FAIL)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
