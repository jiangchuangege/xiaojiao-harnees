# -*- coding: utf-8 -*-
"""技能库 + 无人值守自我改进 · 自测（离线、确定性）

钉住四件事：
  ① 技能库**宁可少记也不记脏**：单工具不记、有失败痕迹不记、同一问题只留最近一条；
  ② 召回**宁可召不回也不套错**：相似度不够就返回空；
  ③ 自主改进**不空转、不重复撞坑**：间隔未到/今日超额/24 小时内同项 → 都不动手；
  ④ 自动动手**只走白名单**，且需求取不准就干脆不做（实测踩过：取成 `x` 生成垃圾插件）。
"""
import io
import json
import os
import shutil
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


def main():
    print("=" * 80)
    print("  技能库 + 无人值守自我改进 自测")
    print("=" * 80)
    from core import skill_memory as SK
    from core import auto_evolve as AE

    tmp = tempfile.mkdtemp()
    sk_backup, hist_backup, cards_backup = SK._PATH, AE._HIST, AE._CARDS
    try:
        SK._PATH = os.path.join(tmp, "skills.jsonl")
        AE._HIST = os.path.join(tmp, "auto", "history.jsonl")
        AE._CARDS = os.path.join(tmp, "auto", "cards")

        # ---------------- 一、技能库：宁少不脏 ----------------
        print("\n[一] 技能库：什么才配叫「技能」")
        trace_one = [{"tool": "get_weather", "args": {"city": "菏泽"}, "result": "阴 +13°C"}]
        ok1, why1 = SK.remember_task("查菏泽天气", trace_one, "阴 +13°C", 1.2)
        ck("只用了 1 个工具 → 不记（那叫调一下，不叫技能）", ok1 is False, why1)

        trace_bad = [{"tool": "get", "args": {"url": "x"}, "result": "抓取失败：超时"},
                     {"tool": "fetch", "args": {"url": "x"}, "result": "ok"}]
        ok2, why2 = SK.remember_task("抓这个网页", trace_bad, "", 2.0)
        ck("有工具返回失败痕迹 → 不记（不把错路径当经验）", ok2 is False, why2)

        trace_ok = [{"tool": "get", "args": {"url": "https://a.com/book"}},
                    {"tool": "write_file", "args": {"path": "G:\\dzs\\a.md"}}]
        ok3, why3 = SK.remember_task("帮我爬一下这个电子书存到 G:\\dzs", trace_ok,
                                     "已抓取并保存", 5.5)
        ck("两个工具且都成功 → 记下", ok3 is True, why3)
        st = SK.stats()
        ck("统计能报出步数与热门工具",
           st["total"] == 1 and st["avg_steps"] == 2.0 and st["top_tools"], st)

        # 同一问题再记一次 → 列表里只留一条
        SK.remember_task("帮我爬一下这个电子书存到 G:\\dzs", trace_ok, "又存了一次", 6.0)
        lst = SK.list_skills(limit=10)
        ck("同一问题只留最近一条（去重键是归一化后的问题）", len(lst) == 1, len(lst))
        ck("留下的是最近那条", "又存了一次" in str(lst[0].get("answer_head")), lst[0].get("sec"))

        # ---------------- 二、召回：宁可不回，也不套错 ----------------
        print("\n[二] 召回：宁可召不回，也不拿错技能去套")
        hit = SK.recall("帮我爬一下这个电子书存到 G:\\dzs")
        ck("同一句话能召回", hit is not None, (hit or {}).get("score"))
        ck("召回给出工具序列", hit and [s["tool"] for s in hit["steps"]] == ["get", "write_file"],
           hit and [s["tool"] for s in hit["steps"]])
        ck("完全不相干的问题召回为空",
           SK.recall("用 Python 写一个快速排序函数") is None)
        hint = SK.plan_for("帮我爬一下这个电子书存到 G:\\dzs")
        ck("plan_for 给出一句话提示（含序列）", "get → write_file" in hint, hint[:60])
        ck("plan_for 召不回时返回空串", SK.plan_for("写个快速排序") == "")

        # ---------------- 三、自主改进：不空转、不重复撞坑 ----------------
        print("\n[三] 自主改进：间隔/日限额/同项不重试")
        AE._STATE.update({"last_tick": 0.0, "started": False})
        r1 = AE.tick(dry_run=True, force=True)
        ck("force + dry_run 能跑一轮（做了什么或说明为什么没做）",
           "did" in r1, {k: r1.get(k) for k in ("did", "why")})
        AE._record("judge", "某条判据", "card", True, "测试记录")
        ck("24 小时内同一项不重试", AE._recently_tried("judge", "某条判据") is True)
        ck("没记录过的项可以试", AE._recently_tried("judge", "另一条判据") is False)
        AE._STATE["last_tick"] = 0.0
        cfg = AE._cfg()
        ck("配置默认开着、6 小时、每天 3 次",
           cfg["on"] is True and cfg["interval_h"] == 6 and cfg["per_day"] == 3, cfg)
        # 间隔未到 → 不动
        AE._STATE["last_tick"] = 9e9
        r2 = AE.tick(dry_run=True)
        ck("间隔没到 → 不动（说明还剩多久）", r2["did"] is False and "间隔" in str(r2.get("why")), r2.get("why"))

        # ---------------- 四、自动动手：只走白名单，需求取不准就不做 ----------------
        print("\n[四] 自动动手：白名单 + 需求取不准就不做")
        ck("非白名单项只写卡（不动源码）",
           AE.act({"kind": "judge", "target": "某条判据", "action": "改词表",
                   "evidence": "评测失败：该用 get_weather"}, dry_run=True)["action"] == "card")
        need_ok = AE._extract_need("最近 3 条失败：需求：把秒数换算成时分秒")
        ck("能从证据里提取「需求：…」", need_ok.startswith("把秒数"), need_ok)
        ck("引号里的短句也能提取",
           AE._extract_need("失败记录「把中文数字转成阿拉伯数字」") == "把中文数字转成阿拉伯数字")
        ck("故障描述不会被当成需求（取不到就空）",
           AE._extract_need("最近 5 条失败：语法错误：第 107 行 '(' was never closed") == "",
           AE._extract_need("最近 5 条失败：语法错误：第 107 行 '(' was never closed"))
        skip = AE.act({"kind": "capability", "target": "能力自增长", "auto": True,
                       "evidence": "最近 5 条失败：语法错误：第 107 行"}, dry_run=True)
        ck("需求取不准 → 不动手（实测踩过：取成 x 生成垃圾插件）",
           skip["action"] == "skip" and skip["ok"] is False, skip)

        # forge 也拒绝了过短的需求
        from core import plugin_forge as PF
        r_short = PF.forge("x", dry_run=True)
        ck("forge 直接拒过短需求（<6 字符）",
           r_short.get("ok") is False and r_short.get("stage") == "input", r_short.get("why"))
        r_sym = PF.forge("!!!???", dry_run=True)
        ck("forge 拒纯符号需求（没实际含义）",
           r_sym.get("ok") is False and r_sym.get("stage") == "input", r_sym.get("why"))
    finally:
        SK._PATH, AE._HIST, AE._CARDS = sk_backup, hist_backup, cards_backup
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 80)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("=" * 80)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
