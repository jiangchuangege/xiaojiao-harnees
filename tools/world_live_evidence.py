# -*- coding: utf-8 -*-
"""世界层 + 防火墙的**真实运行证据**（真联网、真落盘）—— 回答"有没有真跑过"。

跑：python tools/world_live_evidence.py
它做三件真事（不是自测桩）：
  ① 用真实搜索找几个真实站点 → 真抓 → 真判断 → 真过防火墙 → 真吸收/隔离
  ② 用真实抓取的页面内容更新世界模型（站点类型/可信度/刷新周期 + 小焦自己的判断）
  ③ 让校验器真跑一轮，对旧判断做修正/降权
跑完把**每一步的证据**和**日志增量**打出来。
"""
import json
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

WD = os.path.join(_ROOT, "logs", "world")
WATCH = ["absorption.jsonl", "exploration.jsonl", "snapshots.jsonl", "changes.jsonl",
         "conflicts.jsonl", "verification.jsonl", "quarantine/index.jsonl", "blacklist.json"]


def counts():
    out = {}
    for f in WATCH:
        p = os.path.join(WD, f)
        if not os.path.exists(p):
            out[f] = 0
        elif f.endswith(".json"):
            try:
                out[f] = len(json.load(open(p, encoding="utf-8")) or {})
            except Exception:      # noqa: silent-ok — 读不了当 0
                out[f] = 0
        else:
            with open(p, encoding="utf-8", errors="ignore") as fh:
                out[f] = sum(1 for l in fh if l.strip())
    return out


def main():
    print("=" * 70)
    print("  世界层 · 真实运行证据（真联网 / 真判断 / 真吸收）")
    print("=" * 70)
    before = counts()
    print("\n起始：", {k: v for k, v in before.items() if k.endswith(("absorption.jsonl", "exploration.jsonl", "quarantine/index.jsonl"))})

    from core.world.model import WorldModel
    from core.world.perception import WorldPerception
    from core.world.judge import SiteJudge
    from core.world.firewall import PollutionFirewall
    from core.world.explorer import WorldExplorer
    from core.world.verifier import WorldVerifier

    wm = WorldModel(os.path.join(WD, "model.json"))
    wp = WorldPerception(model=wm)
    fw = PollutionFirewall(model=wm, state_dir=WD)
    judge = SiteJudge(model=wm)

    def searcher(q, n=5):
        """真搜索：用宿主的 web_search（真联网）。"""
        try:
            import xiaojiao_app as X
            return [(t, u, c) for (t, u, c) in (X.web_search(q, num=n) or [])][:n]
        except Exception as e:      # noqa: silent-ok — 搜不到就返回空，如实报告
            print("    搜索失败：%s" % str(e)[:80])
            return []

    ex = WorldExplorer(model=wm, perception=wp, judge=judge, firewall=fw, state_dir=WD,
                       searcher=searcher,
                       history_getter=lambda: [{"role": "用户", "content": "我关心 向量检索 与 抓取"}] * 3)

    print("\n① 推理：推出值得看的话题")
    topics = ex.infer_topics(limit=4)
    print("    话题：%s" % topics[:4])
    plan = (ex.plan(limit=2) or [{}])[0]
    print("    计划：%s（%s）" % (plan.get("topic"), plan.get("why")))

    print("\n② 走一遍完整五步（真联网）")
    for i in range(2):
        r = ex.explore_once(topic=topics[min(i, len(topics) - 1)] if topics else None)
        st = r.get("steps") or {}
        print("    第%d轮 topic=%s ok=%s" % (i + 1, (r.get("plan") or {}).get("topic"), r.get("ok")))
        print("      RAG：找到 %s 个候选 ｜ %s" % ((st.get("rag") or {}).get("found"),
                                                (st.get("rag") or {}).get("urls", [])[:2]))
        print("      匹对：%s" % (st.get("match") or {}).get("why"))
        print("      校验：%s（分 %.2f）" % ((st.get("verify") or {}).get("verdict"),
                                          (st.get("verify") or {}).get("score") or 0))
        print("      吸收：%s ｜ %s" % ((st.get("absorb") or {}).get("absorbed"),
                                      (st.get("absorb") or {}).get("why")))

    print("\n③ 世界模型里现在有什么（小焦自己画的图）")
    sites = wm.snapshot().get("sites") or {}
    for dom, rec in list(sites.items())[:6]:
        print("    %-28s 类型=%-12s 可信度=%.2f 判断=%s" %
              (dom, rec.get("judged_type") or rec.get("type") or "?",
               float(rec.get("judged_trust") or rec.get("trust") or 0),
               (wm.judgment_of(dom) or {}).get("by") or "-"))
    print("    话题表：%s" % [t.get("name") for t in (wm.topics(top=5) or [])])

    print("\n④ 校验器跑一轮（回看判断准不准）")
    vf = WorldVerifier(model=wm, state_dir=WD)
    rep = vf.review(days=7, limit=10)
    print("    复核 %d 个 ｜ 结论分布 %s ｜ 降权 %d 个"
          % (rep["reviewed"], rep["summary"], rep["decayed"]))
    print("    " + vf.report(days=7).replace("\n", "\n    "))

    print("\n⑤ 防火墙：真实内容的闸门结论")
    print("    " + fw.report(days=1).replace("\n", "\n    "))

    after = counts()
    print("\n" + "=" * 70)
    print("  真实运行带来的日志增量：")
    grew = 0
    for k in WATCH:
        d = after[k] - before[k]
        if d:
            grew += 1
        print("    %-26s %5d → %-5d %s" % (k, before[k], after[k], ("⭐ +%d" % d) if d else "—"))
    print("\n  有新增的日志：%d / %d" % (grew, len(WATCH)))
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
