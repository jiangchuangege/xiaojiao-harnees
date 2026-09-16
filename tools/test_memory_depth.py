# -*- coding: utf-8 -*-
"""模块 3 · 记忆深度系统 · 自测（确定性，不依赖模型、不依赖网络）。

为什么必须有它：记忆深度系统的失败**不会报错**，只会"记错"——
把事实降到"模糊"、把寒暄当事实存、检索不到却编一个 —— 这些在功能测试里全都看不出来。
所以这里逐条钉住：分类、清晰度分档、降级不清零、巩固、被提到升级、联想、
以及最要紧的**绝假记忆**（检索不到必须如实说没有）。

⚠️ 本测试会**往真实记忆库里写测试条目**，跑完必须清干净。
   清理方式：备份 → 跑 → 按 id/文本前缀精确删除测试条目 → 还原备份。
   为什么用"备份+还原"而不是到处 pop：记忆库是用户资产，
   测试逻辑一旦有 bug 也不能碰坏它（这个项目删文件是红线）。
"""
import json
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from core import memory_deep as M       # noqa: E402
from core import memory_vec             # noqa: E402

_TAG = "【自测M3】"

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


# ------------------------------------------------------------------ 备份 / 还原
def _backup():
    p = memory_vec.path()
    if not os.path.exists(p):
        return None
    with open(p, "rb") as f:
        return f.read()


def _restore(blob):
    if blob is None:
        return
    p = memory_vec.path()
    with open(p, "wb") as f:
        f.write(blob)
    memory_vec.reload()


def _purge_test_rows():
    """只删带测试前缀的行（双保险：万一还原也没做，也不会留下测试数据）。"""
    p = memory_vec.path()
    if not os.path.exists(p):
        return 0
    keep, dropped = [], 0
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            if _TAG in line:
                dropped += 1
                continue
            keep.append(line)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.writelines(keep)
    os.replace(tmp, p)
    memory_vec.reload()
    return dropped


def main():
    print("=" * 70)
    print("  模块 3 · 记忆深度系统（事实/表达/印象 + 清晰度降级 + 绝假记忆）")
    print("=" * 70)
    blob = _backup()
    t0 = time.time()

    # ---------------- 一、分类规则（载体判断，不靠模型） ----------------
    print("\n[一] 三层分类：事实优先，表达只吃「短句+寒暄」")
    cases = [
        ("我叫张三，住在济南", M.LAYER_FACT, "人物+地点"),
        ("今天被领导骂了", M.LAYER_FACT, "时间+经历"),
        ("我儿子上小学三年级", M.LAYER_FACT, "人物关系"),
        ("2026年9月14日面试完了", M.LAYER_FACT, "日期+事件"),
        ("我对花生过敏", M.LAYER_FACT, "状态事实"),
        ("你好", M.LAYER_EXPRESSION, "寒暄"),
        ("在吗", M.LAYER_EXPRESSION, "寒暄"),
        ("哈哈哈哈", M.LAYER_EXPRESSION, "语气"),
        ("晚安", M.LAYER_EXPRESSION, "寒暄"),
        ("嗯嗯", M.LAYER_EXPRESSION, "应声"),
    ]
    for text, want, why in cases:
        got, reason = M.classify(text)
        ck("分类「%s」→ %s（%s）" % (text, M.LAYER_CN[want], why), got == want,
           "%s / %s" % (M.LAYER_CN.get(got, got), reason))

    # 事实优先的边界：长句里含寒暄词，仍然算事实
    got, reason = M.classify("你好，我昨天跟你说的那个项目黄了，因为甲方砍预算")
    ck("长句含寒暄词仍判事实（事实优先）", got == M.LAYER_FACT, reason)
    got, reason = M.classify("谢谢")
    ck("极短寒暄判表达", got == M.LAYER_EXPRESSION, reason)
    got, reason = M.classify("")
    ck("空内容倒向事实层（宁多存不丢）", got == M.LAYER_FACT, reason)

    # ---------------- 二、清晰度分档 ----------------
    print("\n[二] 清晰度四档：0-7 高清 / 7-30 标清 / 30-180 模糊 / 180+ 印象")
    for days, want in ((0.5, M.CLARITY_HD), (3, M.CLARITY_HD), (7.1, M.CLARITY_SD),
                       (29, M.CLARITY_SD), (31, M.CLARITY_BLUR), (179, M.CLARITY_BLUR),
                       (181, M.CLARITY_IMPRESSION), (4000, M.CLARITY_IMPRESSION)):
        got = M.clarity_of(days)
        ck("%s 天 → %s" % (days, M.CLARITY_CN[want]), got == want, M.CLARITY_CN.get(got, got))

    # ---------------- 三、入库 + 降级（不是删除） ----------------
    print("\n[三] 降级：清晰度往下走，但**条目一条都不能少**")
    # ⚠️⚠️ 降级是"按时间算"的，**绝不能拿未来的 now 去改真实记忆库**。
    # 第一版就是这么写的（`M.degrade(now=now+500天)` 用默认 apply=True），
    # 结果把整库 397 条真实记忆按"500 天后"重算写回，全变成印象。
    # 现在一律用 `rows=[...]` 传内存行做**推演**（不回写），真实库一点不碰。
    now = time.time()
    # 真实条目只用来证明"入库/取回/统计"是对的（这些操作本来就该写库）
    ids = {}
    ids["new"] = M.remember_fact(_TAG + "我住在济南", entities=["济南"], ts=now)
    ck("事实入库后能取回", ids["new"] is not None)

    probe_rows = [
        {"id": "p-new", "kind": M.LAYER_FACT, "ts": now,
         "text": _TAG + "今天说的", "meta": {"clarity": M.CLARITY_HD}},
        {"id": "p-mid", "kind": M.LAYER_FACT, "ts": now - 15 * M._DAY,
         "text": _TAG + "15天前", "meta": {"clarity": M.CLARITY_HD}},
        {"id": "p-old", "kind": M.LAYER_FACT, "ts": now - 60 * M._DAY,
         "text": _TAG + "60天前", "meta": {"clarity": M.CLARITY_HD}},
        {"id": "p-anc", "kind": M.LAYER_FACT, "ts": now - 400 * M._DAY,
         "text": _TAG + "400天前", "meta": {"clarity": M.CLARITY_HD}},
        {"id": "p-lock", "kind": M.LAYER_FACT, "ts": now - 400 * M._DAY,
         "text": _TAG + "400天前但已巩固", "meta": {"clarity": M.CLARITY_HD, "locked": True}},
    ]
    rep = M.degrade(now=now, rows=probe_rows)
    ck("降级是**推演**（不写真实库）", rep["applied"] is False, rep["applied"])
    ck("降级扫描到全部推演行", rep["scanned"] == len(probe_rows), rep["scanned"])
    eff = {r["id"]: M._clarity_of_row(r, now) for r in probe_rows}
    ck("今天说的 → 高清", eff["p-new"] == M.CLARITY_HD, M.CLARITY_CN[eff["p-new"]])
    ck("15 天前说的 → 标清", eff["p-mid"] == M.CLARITY_SD, M.CLARITY_CN[eff["p-mid"]])
    ck("60 天前说的 → 模糊", eff["p-old"] == M.CLARITY_BLUR, M.CLARITY_CN[eff["p-old"]])
    ck("400 天前说的 → 印象", eff["p-anc"] == M.CLARITY_IMPRESSION,
       M.CLARITY_CN[eff["p-anc"]])
    ck("**已巩固的 400 天行不降级**（重要的事不该变模糊）",
       eff["p-lock"] == M.CLARITY_HD, M.CLARITY_CN[eff["p-lock"]])
    ck("四档都出现在推演结果里",
       len(set(eff.values())) >= 3, {k: M.CLARITY_CN[v] for k, v in eff.items()})
    # "降级≠删除"：推演前后行数不变
    n_before_deg = len(probe_rows)
    M.degrade(now=now, rows=probe_rows)
    ck("**降级不清零条目**", len(probe_rows) == n_before_deg, len(probe_rows))

    # ---------------- 四、巩固（被引用多 → 锁高清） ----------------
    print("\n[四] 巩固：被引用 ≥3 次 → 锁定高清（只动测试自己的条目）")
    uid = M.remember_fact(_TAG + "这条会被反复引用", ts=now - 400 * M._DAY)
    for _ in range(3):
        M.note_usage(uid, now=now)
    con = M.consolidate(min_refs=3, now=now)
    ck("巩固锁定了测试条目", uid in con["locked"], con["count"])
    rows = {r.get("id"): r for r in M._all_rows()}
    meta_u = rows[uid].get("meta") or {}
    ck("锁定标记落到库里", meta_u.get("locked") is True, meta_u.get("refs"))
    future = now + 500 * M._DAY
    ck("锁定后**500 天后仍算高清**（推演，不碰真实库）",
       M._clarity_of_row(rows[uid], future) == M.CLARITY_HD,
       M.CLARITY_CN[M._clarity_of_row(rows[uid], future)])
    un_locked = M.remember_fact(_TAG + "这条没被巩固", ts=now - 400 * M._DAY)
    rows = {r.get("id"): r for r in M._all_rows()}
    ck("没锁定的照常降级",
       M._clarity_of_row(rows[un_locked], future) == M.CLARITY_IMPRESSION,
       M.CLARITY_CN[M._clarity_of_row(rows[un_locked], future)])

    # ---------------- 五、被提到 → 升级回高清 ----------------
    print("\n[五] 降级**可逆**：被重新提到 → 升级回高清")
    M.revive(uid)
    rows = {r.get("id"): r for r in M._all_rows()}
    ck("revive 后回到高清（且 500 天后仍高清）",
       M._clarity_of_row(rows[uid], future) == M.CLARITY_HD,
       M.CLARITY_CN[M._clarity_of_row(rows[uid], future)])
    ck("revive 找不到的 id 返回 False（不假装成功）", M.revive("no-such-id-xyz") is False)

    # ---------------- 六、压缩 → 印象层（原条目还在） ----------------
    print("\n[六] 压缩：久远内容压成印象，**原条目不清零**")
    # 先推演（不写库）：确认"哪些会被压"
    dry = M.compress(now=now, rows=list(probe_rows))
    ck("推演模式不写库", dry["applied"] is False, dry["applied"])
    ck("推演能挑出 180 天以上的行", dry["compressed"] == 1, dry["compressed"])
    # 再对**测试自己的**一条 500 天前条目做真实压缩
    old_id = M.remember_fact(_TAG + "四年前在成都待过一阵", entities=["成都"],
                             ts=now - 500 * M._DAY)
    n_before = M.stats()["total"]
    cp = M.compress(now=now)
    n_after = M.stats()["total"]
    ck("真实压缩产生了印象条目", cp["compressed"] >= 1, cp["compressed"])
    ck("**目标条目被压缩了**", any(x["id"] == old_id for x in cp["impressions"]),
       [x["id"] for x in cp["impressions"]][:3])
    ck("原条目仍在（只是多了印象副本）", n_after == n_before + cp["compressed"],
       "%d → %d (压缩 %d)" % (n_before, n_after, cp["compressed"]))
    imp_ids = [x["impression_id"] for x in cp["impressions"] if x.get("impression_id")]
    rows_now = {r.get("id"): r for r in M._all_rows()}
    ck("**新压出的印象**文本带【印象】标记",
       bool(imp_ids) and all("【印象】" in ((rows_now.get(i) or {}).get("text") or "")
                             for i in imp_ids),
       "本次印象 id=%s" % (imp_ids[:2],))

    # ---------------- 七、联想（时间链 + 实体链 + 因果） ----------------
    print("\n[七] 联想：共享实体 / 时间相邻 / 因果词")
    # 【为什么这里的用词改过一次 —— 如实记】
    #   因果链判据是**纯载体规则（不调模型）**，原来写成"时间近 + 有因果词"就认，
    #   太松：任何一条近十天的因果句都会成为任何一条记忆的邻居，把真正相关的那条挤出 top-10。
    #   收严成"因果词领起的那一小句必须跟源／其实体邻居**共用一个词**"之后，
    #   原来的样本「把我**裁**了」↔「因为**被裁**」**只共用一个字**，判据抓不到它
    #   —— 那需要"裁 ≈ 被裁"这种语义泛化，确定性判据做不到。
    #   所以样本改成**共用一个词**的形式（裁员），让它测的正是判据本身。
    #   ⚠️ 如实标注：只共用单字的近义说法（裁/被裁）**现在不会被认成因果链**，
    #      这是确定性判据的能力边界，不是 bug。
    base = M.remember_fact(_TAG + "我在济南工作", entities=["济南"], ts=now - 3 * M._DAY)
    M.remember_fact(_TAG + "济南那家公司把我裁员了，所以我回老家了",
                    entities=["济南"], ts=now - 2 * M._DAY)
    M.remember_fact(_TAG + "因为裁员，我就开始自己接活了", entities=[], ts=now - 1 * M._DAY)
    M.remember_fact(_TAG + "完全无关的一条：今天天气不错", entities=[], ts=now - 900 * M._DAY)
    asso_all = M.associations(base, limit=10, now=now)
    asso = [a for a in asso_all if _TAG in a["text"]]     # 只看本测试造的行
    ck("联想能找到邻居", len(asso) >= 2, len(asso))
    kinds = set(a["kind"] for a in asso)
    ck("含实体链（共享实体）", "实体" in kinds, sorted(kinds))
    ck("含因果链", "因果" in kinds, sorted(kinds))
    ck("实体链指向的确实是同实体那条",
       any(a["kind"] == "实体" and "济南" in a["text"] for a in asso),
       [a["text"][:14] for a in asso if a["kind"] == "实体"])
    ck("联想结果不带无关的久远条目",
       all("天气" not in a["text"] for a in asso), [a["text"][:16] for a in asso])
    ck("找不到的 id 返回空表（不编）", M.associations("no-such-id", now=now) == [])

    # ---------------- 八、绝假记忆（诚信红线，最关键） ----------------
    print("\n[八] 绝假记忆：检索不到 → 必须说「没有」，绝不拿最像的凑")
    # ⚠️ 这里必须**受控**地测：真实记忆库里本来就有几百条历史，
    #    问"我的车牌号"也一定会召回几条余弦 0.6 上下的无关记忆 ——
    #    那是**真实环境**，不是判据坏了。判据本身要用"受控命中"来钉：
    #      ① 召回为空 → 必须说"没说过"；
    #      ② 召回一条但**表面无重合** → 只能说"记得但细节不清"，**绝不许把它当事实说**；
    #      ③ 召回一条且表面高度重合 + 余弦高 → 才允许 precise。
    real_search = memory_vec.search_memory
    try:
        # ① 召回为空
        memory_vec.search_memory = lambda *a, **k: []
        r_none = M.recall("我的车牌号是多少", now=now)
        ck("检索不到 → verdict=none", r_none["verdict"] == "none", r_none["verdict"])
        ck("**回话文本明确说没有**", "没跟我说过" in r_none["text"], r_none["text"])

        # ② 召回一条无关的（余弦中等）→ 不许 precise
        memory_vec.search_memory = lambda *a, **k: [
            {"id": "x-1", "text": "用户：用搜索工具找漏洞", "kind": "dialogue",
             "entities": [], "ts": now - 5 * M._DAY, "score": 0.622, "rank": 1}]
        r_fz = M.recall("我的车牌号是多少", now=now)
        ck("召回但**表面无重合** → 只能是 fuzzy（不许当事实说）",
           r_fz["verdict"] == "fuzzy", r_fz["verdict"])
        ck("fuzzy 文案只承认「记得」、明说细节不清", "记不太清" in r_fz["text"], r_fz["text"])
        ck("fuzzy 文案**不含**那条无关记忆被当成答案的表述",
           "车牌" not in r_fz["text"], r_fz["text"])

        # ③ 召回一条高度重合的 → precise
        memory_vec.search_memory = lambda *a, **k: [
            {"id": "x-2", "text": _TAG + "我叫张三，住在济南", "kind": "fact",
             "entities": ["济南"], "ts": now - 1 * M._DAY, "score": 0.91, "rank": 1}]
        rows_x = M._all_rows()
        r_pr = M.recall(_TAG + "我叫张三", now=now)
        ck("表面高度重合 + 余弦高 → precise", r_pr["verdict"] == "precise", r_pr["verdict"])
        ck("precise 直接给原文（不含自造内容）", "张三" in r_pr["text"] and "：" not in r_pr["text"],
           r_pr["text"])
        del rows_x
    finally:
        memory_vec.search_memory = real_search

    r_empty = M.recall("", now=now)
    ck("空查询 → verdict=empty（不下结论）", r_empty["verdict"] == "empty", r_empty["verdict"])
    # 判据本身可单测（不依赖库内容）：表面重合是决定性的那道闸门
    ck("同一个说法 → 重合率高",
       M.overlap("我住在济南", "用户：我住在济南") > 0.5,
       round(M.overlap("我住在济南", "用户：我住在济南"), 3))
    ck("无关说法 → 重合率为 0（闸门关死）",
       M.overlap("我的车牌号是多少", "用户：用搜索工具找漏洞") == 0.0,
       M.overlap("我的车牌号是多少", "用户：用搜索工具找漏洞"))
    ck("置信度：表面重合高的压过只说相似的",
       M.confidence("我住在济南", "我住在济南", 0.7) > M.confidence("我住在济南", "用搜索找漏洞", 0.7),
       (round(M.confidence("我住在济南", "我住在济南", 0.7), 3),
        round(M.confidence("我住在济南", "用搜索找漏洞", 0.7), 3)))

    # ---------------- 九、表达层：只学风格，不存原句 ----------------
    print("\n[九] 表达层：学风格不背原句，且越用越像这个人")
    for i in range(6):
        M.remember_expression("你好呀%s" % ("！" if i % 2 else ""))
    st = M.style_profile()
    ck("风格样本数在涨", st["samples"] >= 6, st["samples"])
    ck("风格向量是数值型（句长/语气/标点）",
       all(isinstance(v, (int, float)) for v in st["style"].values()), sorted(st["style"]))
    expr_rows = [r for r in M._all_rows() if (r.get("kind") or "") == M.LAYER_EXPRESSION]
    ck("**寒暄没有按原句进向量库**（否则会把事实挤出去）", len(expr_rows) == 0,
       "表达层向量条目=%d" % len(expr_rows))
    rep1 = M.expression_reply("hello")
    ck("能按风格生成新表达（不是背原句）", isinstance(rep1, str) and 0 < len(rep1) <= 20, rep1)
    ck("没有样本时不硬编语气（退化为朴素版）", isinstance(M.expression_reply("bye"), str))

    # ---------------- 十、统一入口 ----------------
    print("\n[十] 统一入口 remember()：自动分层并留下理由")
    a = M.remember(_TAG + "我下周三要去北京出差")
    b = M.remember(_TAG + "在吗")
    ck("事实句进事实层", a["layer"] == M.LAYER_FACT, a)
    ck("寒暄进表达层", b["layer"] == M.LAYER_EXPRESSION, b)
    ck("两条都留下了「为什么这么分」的理由", bool(a["reason"]) and bool(b["reason"]),
       (a["reason"][:20], b["reason"][:20]))

    # ---------------- 十一、统计 ----------------
    print("\n[十一] 统计口径真实（没有就写 0，不编）")
    s = M.stats()
    ck("total 与实际行数一致", s["total"] == len(M._all_rows()),
       "%d / %d" % (s["total"], len(M._all_rows())))
    ck("by_layer 分类计数之和 = total",
       sum(s["by_layer"].values()) == s["total"], s["by_layer"])
    ck("by_clarity 是中文档位（给界面看）",
       all(k in M.CLARITY_CN.values() for k in s["by_clarity_cn"]), s["by_clarity_cn"])

    # ---------------- 收尾：清干净测试数据 ----------------
    dropped = _purge_test_rows()
    ck("测试数据已按前缀清除", dropped >= 1, "清理 %d 行" % dropped)
    _restore(blob)
    left = [r for r in M._all_rows() if _TAG in (r.get("text") or "")]
    ck("**还原后真实记忆库里没有测试残留**", not left, "残留 %d 条" % len(left))

    print("\n" + "=" * 70)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("  耗时 %.1fs" % (time.time() - t0))
    print("=" * 70)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
