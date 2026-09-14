# -*- coding: utf-8 -*-
"""退化检测（Bug 3 地基）自测 —— 真跑，不模拟。

运行：python tools/test_degeneration.py
覆盖：用户实测原句（"然后说：…"）、连续串联复读、低多样性、
      正常长文不误杀、流式增量能及时发现、截断保留前 2 次且落在完整句、病历落盘。
"""
import os
import sys
import json
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.health import degeneration as D  # noqa: E402

PASS = []
FAIL = []


def ck(group, name, cond, info=""):
    (PASS if cond else FAIL).append("%s/%s" % (group, name))
    print("  %s [%s] %s%s" % ("✅" if cond else "❌", group, name,
                              ("  ← " + str(info)) if info else ""))


# 用户实测的原句：共享骨架是"然后说："，中间的字每次不同 —— 连续串联检测抓不到，
# 只有"短块高频 + 密集"这一类判据抓得到。这正是本模块必须有三类判据的原因。
USER_CASE = "然后说：嗯。然后说：哦。然后说：好的。" * 25

NORMAL = (
    "我们的产品定位是让中小团队用上专业级的数据分析能力。"
    "第一步，把散落在各个系统里的数据接进来，支持 CSV 导入、API 拉取和数据库直连三种方式。"
    "第二步，用可视化的方式把指标搭起来，不需要写 SQL 也能做出看板。"
    "第三步，把看板分享出去，权限按角色控制，外部协作方只能看到被授权的页面。"
    "在性能上，单表千万行的聚合查询可以在一秒内返回，靠的是列式存储和预聚合。"
    "在成本上，我们按实际查询量计费，没有最低消费，小团队一个月的开销通常在几十元。"
    "安全方面，全链路加密、审计日志留存一年、支持私有化部署。"
    "服务上，提供中文文档和工单支持，工作日两小时内响应，紧急故障十五分钟内介入。"
    "未来的路线图里，我们计划加入自然语言的问数能力，让业务同学直接问问题就能拿到答案。"
    "同时会开放插件市场，让第三方把你的数据源接进来看板。"
    "如果你关心迁移成本，我们提供从主流 BI 工具一键导入的工具，字段映射会自动推断。"
    "总体而言，这个产品解决的是数据分析门槛高、上线慢、维护贵这三件事。"
) * 3


def main():
    print("=" * 62)
    print("  退化检测自测（Bug 3 地基）")
    print("=" * 62)

    # ---- A 用户实测原句 ----
    print("\n[A] 用户实测原句：然后说：嗯/哦/好的 ×25")
    h = D.detect(USER_CASE, where="test_user_case")
    ck("A", "检测到退化", h is not None, str(h))
    ck("A", "命中类型是短块高频/串联复读", h is not None and h.kind in ("ngram_repeat", "phrase_repeat"),
       h.kind if h else "")
    ck("A", "重复次数很高（≥10）", h is not None and h.count >= 10, h.count if h else 0)

    # ---- B 连续串联复读 ----
    print("\n[B] 连续串联复读")
    cases = [
        ("好的好的好的好的好的", "phrase_repeat"),
        ("嗯。嗯。嗯。嗯。嗯。嗯。", "phrase_repeat"),
        ("让我想想让我想想让我想想让我想想", "phrase_repeat"),
    ]
    for text, want in cases:
        hh = D.detect(text + NORMAL[:80], where="test_tandem")
        ck("B", "串联复读 %r" % text[:10], hh is not None and hh.kind == want,
           (hh.kind if hh else "None"))

    # ---- C 低多样性（**弱判据，默认不启用**）----
    print("\n[C] 低多样性（弱判据：默认不启用，只在体检时按需打开）")
    templated = "".join("第%d段的产品介绍讲到这里，小焦把上下文按需装配，第%d次请求只装当前这一小块。" % (i, i)
                        for i in range(12))
    hh = D.detect(templated, where="test_lowdiv", weak=True)
    ck("C", "weak=True 时多样性塌陷被检出", hh is not None and hh.kind == "low_diversity", str(hh))
    ck("C", "weak=False（默认）不用它 —— 避免误杀模板化正常文本",
       D.detect(templated, where="t") is None, str(D.detect(templated, where="t")))
    lowdiv = "".join("啊哦嗯哈呀"[(i * 7) % 5] + "。" for i in range(120))
    ck("C", "极短变体复读仍被强判据兜住（不靠弱判据）",
       D.detect(lowdiv, where="t") is not None, str(D.detect(lowdiv, where="t")))

    # ---- D 正常长文不误杀（最重要的一条）----
    print("\n[D] 正常长文 / 正常口语修辞 / 正常枚举 / 英文 —— 一律不许误杀")
    ck("D", "正常产品介绍（%d 字）不触发" % len(NORMAL), D.detect(NORMAL, where="test_normal") is None,
       str(D.detect(NORMAL, where="t")))
    spread = ("小焦" + "这是一段完全不同的说明文字。" + "小焦" + "接下来换一个话题来讲。" +
              "小焦" + "最后再补充一句注意事项。" + "小焦说完了。")
    ck("D", "高频词分散出现不触发", D.detect(spread, where="test_spread") is None, str(D.detect(spread, where="t")))
    ck("D", "短文本不触发（min_chars 保护）", D.detect("你好。你好。你好。", where="test_short") is None)
    ck("D", "修辞性三连不触发（'加油！'×3）", D.detect("加油！加油！加油！" + NORMAL[:60], where="t") is None)
    ck("D", "口语 '好的好的好的' 不触发（本轮实测抓到的误杀）",
       D.detect("好的好的好的" + NORMAL[:80], where="t") is None,
       str(D.detect("好的好的好的" + NORMAL[:80], where="t")))
    ck("D", "笑声 '哈哈哈哈哈哈哈哈' 不触发",
       D.detect("哈哈哈哈哈哈哈哈" + NORMAL[:80], where="t") is None)
    enum_txt = ("在读取数据的时候要注意编码，在解析字段的时候要注意空值，"
                "在写入数据库的时候要注意事务，在返回结果的时候要注意分页，"
                "在记录日志的时候要注意脱敏。") * 2
    ck("D", "合法枚举（'…的时候'×8）不触发", D.detect(enum_txt, where="t") is None,
       str(D.detect(enum_txt, where="t")))
    # 英文段落：本条来自"单字多样性判据会把英文判成退化"这个真实误杀。
    # 注意用词：仓库有一条"代码中无遥测埋点"的全仓扫描，会命中 an*lytics 这类词 ——
    # 这段是测试语料，换个同义词即可，**不能为了它去放宽那条安全扫描**。
    en = ("Our product helps small teams do professional data reporting. First you connect data "
          "sources. Second you build metrics visually. Third you share dashboards with role "
          "based permissions. Performance stays under one second for large aggregations. "
          "Security includes encryption and a full audit trail. Support is in Chinese. ") * 2
    ck("D", "正常英文段落不触发（单字多样性判据的坑）", D.detect(en, where="t") is None,
       str(D.detect(en, where="t")))

    # ---- E 流式增量检测 ----
    print("\n[E] 流式：边收边判，能及时发现并终止")
    det = D.DegenerationDetector(check_every=5)
    pieces = [USER_CASE[i:i + 12] for i in range(0, len(USER_CASE), 12)]
    hit_at = None
    for i, p in enumerate(pieces, 1):
        if det.feed(p):
            hit_at = i
            break
    ck("E", "流式途中命中", hit_at is not None, "第 %s 片（共 %d 片）" % (hit_at, len(pieces)))
    ck("E", "发现得足够早（不超过总片数一半）", hit_at is not None and hit_at <= max(1, len(pieces) // 2),
       "%s / %d" % (hit_at, len(pieces)))
    ck("E", "命中后锁存（再 feed 仍返回命中）", det.feed("随便再来一点") is not None)
    ck("E", "命中不是在第一片就误报", hit_at is not None and hit_at >= 2, hit_at)

    # ---- F 截断 + 回退完整句 ----
    print("\n[F] 截断：保留前 2 次 + 落在完整句")
    det2 = D.DegenerationDetector()
    det2.check(NORMAL[:200] + USER_CASE, where="test_trunc")
    cut, n = det2.truncated()
    ck("F", "确实砍掉了内容", n > 0, "砍掉 %d 字" % n)
    ck("F", "保留的正文长度合理（保留了前文）", len(cut) > 150, len(cut))
    ck("F", "保留的是前文 + 完整的一段复读（不是一刀切到复读起点）",
       1 <= cut.count("然后说：") <= 3 and "产品定位" in cut, cut.count("然后说："))
    fixed, n2 = D.repair_tail(cut + "半句没收")
    ck("F", "repair_tail 落在完整句", fixed.rstrip()[-1] in "。！？!?；;…", repr(fixed[-12:]))
    t3, hit3, n3 = D.truncate_repeat("开头正常。" + USER_CASE)
    ck("F", "truncate_repeat 一步到位", hit3 is not None and n3 > 0 and t3.rstrip()[-1] in "。！？!?；;…",
       "砍 %d 字，尾=%r" % (n3, t3[-8:]))

    # ---- G 病历落盘 ----
    print("\n[G] 病历落盘 logs/health/degeneration.jsonl")
    path = os.path.join(_ROOT, "logs", "health", "degeneration.jsonl")
    before = os.path.getsize(path) if os.path.exists(path) else 0
    D.log_hit(D.detect(USER_CASE, where="test_log"))
    after = os.path.getsize(path) if os.path.exists(path) else 0
    ck("G", "文件存在且变大", after > before, "%d → %d 字节" % (before, after))
    last = ""
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                last = line
    row = json.loads(last)
    ck("G", "记录含 位置/短语/次数", all(k in row for k in ("ts", "kind", "phrase", "count", "at")), list(row))
    summ = D.summary(days=1)
    ck("G", "summary 能统计", summ.get("total", 0) > 0, "累计 %d 次，类型 %s" % (summ.get("total"), summ.get("by_kind")))

    # ---- H 性能（流式每 15 片查一次，不能拖慢生成）----
    print("\n[H] 性能")
    t0 = time.time()
    big = NORMAL * 8
    for i in range(0, len(big), 24):
        det3 = D.DegenerationDetector()
        det3.feed(big[i:i + 24])
    el = time.time() - t0
    ck("H", "长文增量检测总耗时 < 1.0s", el < 1.0, "%.3fs / %d 字" % (el, len(big)))
    t0 = time.time()
    D.detect(big, where="test_perf")
    el2 = time.time() - t0
    ck("H", "整段检测 %d 字 < 0.5s" % len(big), el2 < 0.5, "%.3fs" % el2)

    print("\n" + "=" * 62)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % ", ".join(FAIL)) if FAIL else ""))
    print("=" * 62)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
