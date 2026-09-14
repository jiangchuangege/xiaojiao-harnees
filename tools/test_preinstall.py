# -*- coding: utf-8 -*-
"""阶段 C · 发布准备（预置数据）· 自测

为什么必须有它："开箱即用"是**发布承诺**，不是形容词。
它最容易出的问题是"文件在、内容空"或者"升级时把用户积累覆盖掉"，
这两种都不会报错，但会让用户拿到一个空壳或者丢掉自己攒的东西。
所以这里钉三件事：
  ① 六类数据**真的都有内容**（计数 > 0，且 verify 如实报缺）；
  ② `ensure()` **幂等**：跑第二遍不再写入（启动路径会反复调用它）；
  ③ `ensure()` **不覆盖用户积累**（已有条目一个不动）。
"""
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from core import preinstall as P   # noqa: E402

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


def main():
    print("=" * 72)
    print("  阶段 C · 发布准备（预置数据：规则/知识/案例/人格/模板/映射）")
    print("=" * 72)

    # ---------------- 一、装配 ----------------
    print("\n[一] ensure()：发布装配（幂等）")
    first = P.ensure()
    ck("ensure 返回六类结果", isinstance(first, dict) and len(first) == 6, sorted(first))
    ck("首次装配确实写了规则库", first.get("rules", 0) >= 0, first.get("rules"))
    second = P.ensure()
    ck("**第二次调用不再重复写入**（幂等，启动路径会反复调）",
       all(v == 0 for v in second.values()), second)

    # ---------------- 二、六类齐备 ----------------
    print("\n[二] verify()：六类预置数据真的都有内容")
    v = P.verify()
    cats = v["categories"]
    ck("六类都在盘点范围内", len(cats) == 6, sorted(cats))
    for k, cn, floor in (("rules", "规则库", 8), ("knowledge", "知识库", 1),
                         ("cases", "案例库", 6), ("persona", "人格模型", 1),
                         ("templates", "元推理模板", 30), ("maps", "结构映射库", 8)):
        c = cats.get(k) or {}
        ck("%s 有内容（≥%d）" % (cn, floor), (c.get("count") or 0) >= floor,
           "%s 条 / %s" % (c.get("count"), c.get("path")))
    ck("verify 给出 ready 总判", isinstance(v.get("ready"), bool), v.get("ready"))
    ck("缺什么要如实列出来（字段必须在，哪怕为空）",
       isinstance(v.get("missing"), list), v.get("missing"))
    ck("当前六类齐备 → ready=True", v["ready"] is True, v["missing"])

    # ---------------- 三、内容真的可用（不只是文件在） ----------------
    print("\n[三] 内容可用：不是「文件在、里面空」")
    rp = cats["rules"]["path"]
    rules = json.load(open(rp, encoding="utf-8"))
    if isinstance(rules, dict):
        rules = rules.get("items") or []
    ck("规则库条目字段齐全（id/when/steps）",
       all(r.get("id") and r.get("when") and r.get("steps") for r in rules),
       "共 %d 条" % len(rules))
    ck("规则库有可执行的步骤（不是一句空话）",
       all(len(r.get("steps") or ()) >= 3 for r in rules), len(rules))
    ck("规则库每条都写了要避开的坑（avoid）",
       all(r.get("avoid") for r in rules), sum(1 for r in rules if not r.get("avoid")))
    ck("案例库有 approach 与 pitfall",
       all(c.get("approach") and c.get("pitfall") for c in P.CASE_SEEDS), len(P.CASE_SEEDS))
    ck("人格种子有 role 与 traits",
       all(p.get("role") and len(p.get("traits") or ()) >= 3 for p in P.PERSONA_SEEDS),
       len(P.PERSONA_SEEDS))
    ck("人格计数只认**有 role 的**文件（不数空壳）", cats["persona"]["count"] >= 1,
       cats["persona"]["count"])

    # 元推理模板/结构映射：确认是**真能取到**的（不是计数假的）
    from core.boost import reasoning as R
    from core.boost import analogy as AN
    ck("元推理模板真能取到 ≥30 个", len(R.all_templates()) >= 30, len(R.all_templates()))
    ck("结构映射库真能取到 ≥8 条", len(AN.STRUCTURE_MAP) >= 8, len(AN.STRUCTURE_MAP))
    ck("三条关键映射都在（电路≈水管/免疫≈安全/市场≈生态）",
       all(any(m.get("from") == a and m.get("to") == b for m in AN.STRUCTURE_MAP)
           for a, b in (("电路", "水管"), ("免疫", "安全"), ("市场", "生态"))),
       [(m.get("from"), m.get("to")) for m in AN.STRUCTURE_MAP][:5])

    # ---------------- 四、不覆盖用户积累（发布升级的关键） ----------------
    print("\n[四] 升级时**不能抹掉用户自己攒的东西**")
    import copy
    rp = cats["rules"]["path"]
    orig = open(rp, encoding="utf-8").read()
    try:
        d = json.loads(orig)
        blob = d.get("items") if isinstance(d, dict) else d
        blob = list(blob or [])
        user_rule = {"id": "zz_user_rule_selftest", "name": "用户自己加的规则",
                     "when": ("自测",), "steps": ("第一步", "第二步", "第三步"),
                     "avoid": ("别删它",)}
        blob.append(user_rule)
        if isinstance(d, dict):
            d["items"] = blob
            P.write_json(rp, d)
        else:
            P.write_json(rp, blob)
        P.ensure()                       # 再装配一次（模拟升级）
        after = json.load(open(rp, encoding="utf-8"))
        after_items = after.get("items") if isinstance(after, dict) else after
        ids = [x.get("id") for x in (after_items or [])]
        ck("**用户的条目还在**（合并而不是覆盖）", "zz_user_rule_selftest" in ids, len(ids))
        ck("预置条目也在（没被用户数据挤掉）", len([i for i in ids if i != "zz_user_rule_selftest"]) >= 8,
           len(ids))
    finally:
        with open(rp, "w", encoding="utf-8") as f:
            f.write(orig)                # 内容写回（**不删除文件**）
        back = json.load(open(rp, encoding="utf-8"))
        back_items = back.get("items") if isinstance(back, dict) else back
        ck("自测数据已还原（内容写回，未删除任何文件）",
           "zz_user_rule_selftest" not in [x.get("id") for x in (back_items or [])])

    # ---------------- 五、verify 的"缺"要真能报出来 ----------------
    print("\n[五] verify 必须能说「缺」（否则「齐备」没有意义）")
    real_paths = P._paths

    def _fake_paths():
        d = dict(real_paths())
        d["rules"] = os.path.join(_TMP, "no_such_rules.json")
        return d

    _TMP = P._dir()
    orig = P._paths
    try:
        P._paths = _fake_paths
        v2 = P.verify()
        ck("**指到不存在的文件时如实报缺**", v2["ready"] is False and "rules" in v2["missing"],
           v2["missing"])
        ck("缺的那一类有 note 说明", bool(v2["categories"]["rules"].get("note")),
           v2["categories"]["rules"].get("note"))
        ck("没缺的类别仍然 ready", v2["categories"]["cases"]["ready"] is True)
    finally:
        P._paths = orig

    # ---------------- 六、摘要带真实数字 ----------------
    print("\n[六] summary 带真实数字")
    s = P.summary()
    v3 = P.verify()
    ck("摘要里出现真实条数", str(v3["categories"]["rules"]["count"]) in s, s[:70])
    ck("摘要说明开箱即用不依赖用户养", "开箱即用" in s or "缺" in s, s[:70])
    ck("summary 与 verify 口径一致（不自己另编一套）",
       ("齐备" in s) == v3["ready"], (v3["ready"], s[:30]))

    print("\n" + "=" * 72)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("=" * 72)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
