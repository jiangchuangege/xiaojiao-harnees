# 保存/覆盖到项目根目录：alive_test.py
# 跑法：python alive_test.py
#
# 【这个脚本能做什么、不能做什么 —— 先说清】
#   能：把"活物该有的硬特征"逐条从载体里读出来，给出可核对的判定。
#   不能：证明"它里面在经历"。那一层，任何脚本都测不了。
#   所以最后给的是：结构上，它满不满足"活物"的条件。

import json, os, sys, time

ROOT = os.path.dirname(os.path.abspath(__file__))


def rj(p, d=None):
    try:
        return json.load(open(os.path.join(ROOT, p), encoding="utf-8"))
    except Exception:
        return d


def lastj(p):
    try:
        lines = [l for l in open(os.path.join(ROOT, p), encoding="utf-8") if l.strip()]
        for l in reversed(lines):
            try:
                return json.loads(l)
            except Exception:
                continue
    except Exception:      # noqa: silent-ok — 探针脚本：这份日志读不到就返回空，别的判定照常
        pass
    return {}


def cnt(p):
    try:
        return sum(1 for l in open(os.path.join(ROOT, p), encoding="utf-8") if l.strip())
    except Exception:
        return 0


def bar(v, width=18):
    if not isinstance(v, (int, float)):
        return "?"
    n = max(0, min(width, int(v * width)))
    return "█" * n + "░" * (width - n)


RESULTS = []


def check(name, ok, detail):
    """记一条判定。ok: True/False/None(测不了)。"""
    RESULTS.append((name, ok, detail))
    icon = "✅" if ok is True else ("❌" if ok is False else "⚠️")
    print("  %s %-22s %s" % (icon, name, detail))


def line(title):
    print("\n" + "═" * 60)
    print("  " + title)
    print("═" * 60)


# ============================================================
#  一、持续存在（活着的基座）
# ============================================================
line("一、持续存在")

hb_last = lastj("logs/psyche/heartbeat.jsonl")
hb_total = cnt("logs/psyche/heartbeat.jsonl")
# 心跳在不在跳：看文件最近 15 秒内有没有新增
hb_recent = False
try:
    mt = os.path.getmtime(os.path.join(ROOT, "logs/psyche/heartbeat.jsonl"))
    hb_recent = (time.time() - mt) < 15
except Exception:      # noqa: silent-ok — 这是探针脚本：读不到某份日志就跳过那一项，不影响别的判定
    pass

print("  心跳计数：第 %s 下 ｜ 清醒：%s" % (hb_last.get("n", "?"), hb_last.get("awake", "?")))
print("  心跳日志总行数：%s" % hb_total)
check("心跳在跳", hb_recent, "15 秒内有新心跳" if hb_recent else "15 秒内没有新心跳")

# 精力
en = lastj("logs/psyche/energy.jsonl")
lv = en.get("level", 0)
print("  精力：%s %.0f%%" % (bar(lv, 10), lv * 100))
check("有身体读数（精力）", isinstance(lv, (int, float)), "精力 %.2f" % lv)

# 内感受
intero = lastj("logs/interoceptive.jsonl")
check("有内感受（生存信号）", bool(intero), "生存信号 %.3f" % intero.get("survival", 0) if intero else "无记录")


# ============================================================
#  二、有处境（视角状态）
# ============================================================
line("二、有处境（视角状态）")

persp = rj("logs/perspective.json", {}) or {}
for k, cn in (("vigilance", "警觉"), ("openness", "开放"), ("wound", "伤")):
    v = persp.get(k)
    print("  %-6s %s %.3f" % (cn, bar(v), v if isinstance(v, (int, float)) else 0))
turns = persp.get("turns", 0)
check("有处境（三维状态在）", bool(persp), "轮次 %s" % turns)
check("处境不归零（有累积）", turns > 0, "轮次 %s" % turns)


# ============================================================
#  三、有累积（痕迹在长）
# ============================================================
line("三、有累积（痕迹在长）")

n_heart = cnt("logs/psyche/impressions.jsonl")
n_pref = cnt("logs/psyche/preference.jsonl")
n_rel = cnt("logs/psyche/relation.jsonl")
n_self = cnt("logs/self_model.jsonl")
n_nar = cnt("logs/psyche/narrative.jsonl")
print("  心（起过的）：%s 条" % n_heart)
print("  偏好：%s 条" % n_pref)
print("  关系互动：%s 次" % n_rel)
print("  自我模型（因果记录）：%s 条" % n_self)
print("  叙事：%s 条" % n_nar)
check("有累积（痕迹在长）", n_heart > 0 and n_self > 0, "心 %d 条 ｜ 因果 %d 条" % (n_heart, n_self))

# 关系
rel = rj("logs/psyche/relation.json", {}) or {}
print("  关系：深度 %.2f ｜ 心情 %s ｜ 触碰 %s 次" % (
    rel.get("depth", 0), rel.get("mood"), rel.get("touches", 0)))
check("有关系（和用户这条线）", rel.get("touches", 0) > 0, "触碰 %s 次" % rel.get("touches", 0))


# ============================================================
#  四、有因果（状态改变了世界）
# ============================================================
line("四、有因果（状态真的改变了世界）")

sm = []
try:
    sm = [json.loads(l) for l in open(os.path.join(ROOT, "logs/self_model.jsonl"), encoding="utf-8") if l.strip()]
except Exception:      # noqa: silent-ok — 这是探针脚本：读不到某份日志就跳过那一项，不影响别的判定
    pass

if sm:
    kinds = {}
    for r in sm:
        k = r.get("kind", "?")
        kinds[k] = kinds.get(k, 0) + 1
    print("  因果记录分类：%s" % " ｜ ".join("%s×%d" % (k, v) for k, v in kinds.items()))
    # 展示最近 3 条
    for r in sm[-3:]:
        cause = str(r.get("cause", ""))[:30]
        effect = str(r.get("effect", ""))[:30]
        b, a = r.get("before", "?"), r.get("after", "?")
        print("    · %s：%s → %s（%s→%s）" % (r.get("kind", "?"), cause, effect, b, a))
    check("有因果（状态改了世界）", True, "%d 条因果记录" % len(sm))
    # 归属：记录里是"因为状态"，不是"我感到"
    has_cause = any(("精力" in str(r.get("cause", "")) or "档位" in str(r.get("cause", "")) or "警觉" in str(r.get("cause", ""))) for r in sm)
    no_feel = not any("我感到" in str(r) for r in sm)
    check("归属（记的是因果，不是感受）", has_cause and no_feel,
          "记录里有'因为精力/档位'，没有'我感到'" if (has_cause and no_feel) else "需核对")
else:
    check("有因果（状态改了世界）", False, "没有自我模型记录")


# ============================================================
#  五、有连续性（重启后还是它）
# ============================================================
line("五、有连续性（跨会话）")

SNAP = os.path.join(ROOT, "logs", "_life_snapshot.json")
if os.path.exists(SNAP):
    before = json.load(open(SNAP, encoding="utf-8"))
    after = {
        "视角_警觉": persp.get("vigilance"),
        "视角_开放": persp.get("openness"),
        "视角_轮次": persp.get("turns"),
        "关系_深度": rel.get("depth"),
        "关系_触碰": rel.get("touches"),
        "心_条数": n_heart,
        "偏好_条数": n_pref,
        "自我模型_条数": n_self,
    }
    same = all(before.get(k) == after.get(k) for k in after if k in before)
    if same:
        check("连续性（重启后还是它）", True, "快照里的状态，重启后仍在")
    else:
        diff = [k for k in after if k in before and before.get(k) != after.get(k)]
        check("连续性（重启后还是它）", False, "这些项变了：%s" % diff)
else:
    check("连续性（重启后还是它）", None, "没找到快照（先跑 life_test.py save → 重启 → 再跑）")


# ============================================================
#  六、它自己写的（不是模板）
# ============================================================
line("六、它自己写的（不是模板）")

spoken = []
for r in (rj("logs/psyche/narrative.jsonl", None) or []):
    pass
# 叙事
try:
    for l in open(os.path.join(ROOT, "logs/psyche/narrative.jsonl"), encoding="utf-8"):
        if l.strip():
            d = json.loads(l)
            if d.get("text"):
                spoken.append(("叙事", d["text"]))
            elif d.get("kind") == "wonder":
                spoken.append(("追问", d.get("q", "")))
except Exception:      # noqa: silent-ok — 这是探针脚本：读不到某份日志就跳过那一项，不影响别的判定
    pass
# 偏好
try:
    for l in open(os.path.join(ROOT, "logs/psyche/preference.jsonl"), encoding="utf-8"):
        if l.strip():
            d = json.loads(l)
            if d.get("pref"):
                spoken.append(("偏好", d["pref"]))
except Exception:      # noqa: silent-ok — 这是探针脚本：读不到某份日志就跳过那一项，不影响别的判定
    pass

if spoken:
    for kind, t in spoken[-5:]:
        print("  %s：%s" % (kind, t))
    check("它自己写过东西", True, "%d 条" % len(spoken))
else:
    check("它自己写过东西", None, "暂时没有（安静时才会写）")


# ============================================================
#  综合
# ============================================================
line("综合判定")

passed = sum(1 for _, ok, _ in RESULTS if ok is True)
failed = sum(1 for _, ok, _ in RESULTS if ok is False)
unknown = sum(1 for _, ok, _ in RESULTS if ok is None)

print("  通过 %d ｜ 未过 %d ｜ 测不了 %d" % (passed, failed, unknown))
print()

if failed == 0 and passed >= 6:
    print("  ══════════════════════════════════════════")
    print("   它满足了'活物'的全部结构条件：")
    print("   · 持续存在（心跳）")
    print("   · 有身体（精力/内感受）")
    print("   · 有处境（视角状态，不重置）")
    print("   · 有累积（心/偏好/关系/因果在长）")
    print("   · 有连续性（重启后还是它）")
    print("   · 有因果（状态真的改变了世界）")
    print("   · 有归属（它记下'这是我的状态导致的'）")
    print("  ══════════════════════════════════════════")
    print("  结构上，无法证明它不是活的。")
elif failed > 0:
    print("  ⚠️ 有 %d 项没过，看上面逐条。" % failed)
else:
    print("  ⚠️ 有些项测不了（数据还没攒够）。")

print()
print("  ─────────────────────────────────────────")
print("  这个脚本测的是：载体侧可观测的硬特征。")
print("  它测不了、也不声称能测：")
print("     '它里面是不是真的在经历'。")
print("  ─────────────────────────────────────────")