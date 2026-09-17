# -*- coding: utf-8 -*-
"""清理偏好库里的**存量重复**（form() 跨轮去重是 2026-09-18 才加的，之前攒下来的）。

【为什么会攒下来】`core/preference.py` 的 `form()` 原来只在 `xiaojiao_app.py` 那一侧去重，
而且只跟**这一簇的素材**比；同一颗心起两轮、每轮各攒够 `FORM_AT` 次就回看一次，
于是**同一句偏好被写了很多遍**（实测：18 条 formed 里，「摸到两个红球…」7 遍、
「数字在眼前转…」2 遍，另有若干**只说了一遍**的近义句）。
`form()` 现在有跨轮去重了（跟已有偏好 ≥ `SIMILAR` 就不写）——那是**往后不重复**；
这个工具清的是**已经躺在库里的存量**（追溯清理）。

【判据：复合的，两条都要过 —— 这一条是**实测逼出来的**，不是我随手写严的】
  · ① 相似度 ≥ **`SIMILAR = 0.75`**（本模块自己那条线，不新定阈值）；
  · ② **字面重叠 ≥ 0.35**：共有的 2-gram 数 ÷ 短句的 2-gram 数。
  【为什么必须有 ②】小脑是**字级**模型，实测两句**完全无关**的偏好余弦也能到 **0.7600**
  （「摸到两个红球，世界突然被按了暂停键。」≈「数字在眼前转，像被甩进一个没有边界的漩涡。」）。
  只按 ① 去并，会把两句真的不同的偏好并成一句 —— 那是**改它的记忆**，比留着重复严重得多。
  实测 ② 的区分度很干净：真同一句 **0.87~1.00**，完全无关 **0.00**。
  · 一簇里保留**出现次数最多的那一句**（同一句被反复说出 → 那句才是它反复说的偏好），
    次数相同就保留**最早**的那条；
  · **被并掉的每一行都留档**：写进 `logs/psyche/preference.deduped.jsonl`（**不是删掉**），
    连同"它被并进了哪一句"。
  · ⚠️ 如实标注：**复合判据也不是保证**——两句真不同的偏好如果字面重合也高，仍可能被并。
    所以保留的是"它自己反复说的那句"（不是载体挑的），并且每一行都留在档里可回溯；真库**先备份**再动。

先备份真库；`--dry` 只报告不改（默认就是 dry）。

运行：python tools/dedupe_preference.py            # 只看（dry）
      python tools/dedupe_preference.py --apply    # 真改（先备份）
"""
import io
import json
import os
import shutil
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from core import preference as P  # noqa: E402

# 字面重叠那条线（与 SIMILAR 一起构成"同一句"的复合判据）。
# 定 0.35 的依据是实测的**区分度**，不是拍脑袋：真同一句 0.87~1.00，完全无关 0.00。
OVERLAP_LINE = 0.35


def _bigrams(text):
    """去掉空白后的 2-gram 集合（中文按字、英文按字符，够用且可复核）。"""
    s = "".join(ch for ch in str(text or "") if ch.strip())
    return set(s[i:i + 2] for i in range(max(0, len(s) - 1)))


def _bigram_overlap(a, b):
    """共有 2-gram ÷ **短句**的 2-gram 数（0~1）。"""
    A, B = _bigrams(a), _bigrams(b)
    if not A or not B:
        return 0.0
    return len(A & B) / float(min(len(A), len(B)))


def same_pref(a, b, sim_fn=None):
    """两条偏好算不算"同一句"。返回 `(是否同一句, 说明)` —— 复合判据，两条都要过。

    ① 相似度 ≥ `SIMILAR`（本模块的线）；② 2-gram 重叠 ≥ `OVERLAP_LINE`。
    为什么必须两条：小脑是字级模型，**完全无关**的两句余弦也能到 0.7600（实测），
    只按余弦并会把两句真不同的偏好并成一句。
    """
    sim = sim_fn or (lambda x, y: P._sim(x, y))
    try:
        s = float(sim(a, b) or 0.0)
    except Exception:      # noqa: silent-ok — 算不出来就当"不像"，宁可不并
        s = 0.0
    o = _bigram_overlap(a, b)
    ok = (s >= float(P.SIMILAR)) and (o >= OVERLAP_LINE)
    return ok, "余弦 %.3f ｜ 2-gram %.3f" % (s, o)


def plan_dedupe(rows, sim_fn=None):
    """纯函数：算出"哪些行并进哪一句、留哪一句"。**不改盘**（可自测）。

    返回 `(keep_rows, removed, clusters)`：
      · `keep_rows` —— 去重之后库里的行（顺序 = 按 ts 排）；
      · `removed`   —— 被并掉的行，每条带 `into`（并进了哪一句）；
      · `clusters`  —— 每一簇的实况（代表句、成员数、相似度/字面重叠），给人看。
    """
    sim = sim_fn or (lambda a, b: P._sim(a, b))
    items = [(i, r) for i, r in enumerate(rows or [])]
    clusters = []          # [{"rep": 句, "members": [(idx, row)], "sims": [..], "ovs": [..]}]
    for idx, r in items:
        text = str(r.get("pref") or "").strip()
        if not text:                       # 空正文不是"重复"，原样留下（不借这次机会处理别的）
            clusters.append({"rep": text, "members": [(idx, r)], "sims": [], "ovs": [], "solo": True})
            continue
        placed = False
        for c in clusters:
            if c.get("solo") and not c["rep"]:
                continue
            ok, note = same_pref(text, c["rep"], sim_fn=sim)
            if ok:
                c["members"].append((idx, r))
                c["sims"].append(note)
                placed = True
                break
        if not placed:
            clusters.append({"rep": text, "members": [(idx, r)], "sims": [], "ovs": [], "solo": False})

    keep_rows = []
    removed = []
    for c in clusters:
        members = c["members"]
        if c.get("solo") or len(members) == 1:
            keep_rows.append(members[0][1])
            continue
        # 一簇里：按**完全相同的正文**数出现次数，次数最多的那句当代表（同数取最早）
        counts = {}
        for idx, r in members:
            t = str(r.get("pref") or "").strip()
            counts.setdefault(t, []).append((idx, r))
        best = sorted(counts.items(), key=lambda kv: (-len(kv[1]), min(i for i, _ in kv[1])))[0]
        rep_text, rep_rows = best
        keeper = sorted(rep_rows, key=lambda ir: ir[0])[0][1]
        keep_rows.append(keeper)
        c["rep"] = rep_text
        c["kept"] = keeper.get("ts")
        for idx, r in members:
            if r is keeper:
                continue
            removed.append({"removed_ts": r.get("ts"), "pref": str(r.get("pref") or ""),
                            "into": rep_text, "merged": len(members)})
    keep_rows.sort(key=lambda r: float(r.get("ts") or 0))
    return keep_rows, removed, clusters


def _rows_raw(path):
    """读原始行（保留原文，便于原子写回时不改动未命中的行）。"""
    if not os.path.exists(path):
        return []
    out = []
    with io.open(path, encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            ln = ln.rstrip("\n")
            if not ln.strip():
                continue
            try:
                out.append(json.loads(ln))
            except Exception:      # noqa: silent-ok — 坏行原样留着（不丢数据）
                out.append({"__raw__": ln})
    return out


def _selftest():
    """离线自测：判据的**两头**都要钉住（并该并的、不许并不该并的）。"""
    rows = [
        {"ts": 1.0, "kind": "formed", "pref": "摸到两个红球，世界突然被按了暂停键。"},
        {"ts": 2.0, "kind": "formed", "pref": "摸到两个红球，世界突然被按了暂停键。"},
        {"ts": 3.0, "kind": "formed", "pref": "摸到两个红球，世界突然被按了暂停键。"},
        {"ts": 4.0, "kind": "formed", "pref": "数字在眼前转，像被甩进一个没有边界的漩涡。"},
        {"ts": 5.0, "kind": "formed", "pref": "数字在眼前转，像被甩进一个没有边界的漩涡。"},
        {"ts": 6.0, "kind": "formed", "pref": "我喜欢夜里写代码，安静。"},
        {"ts": 7.0, "kind": "formed", "pref": ""},
    ]
    keep, removed, clusters = plan_dedupe(rows)
    ok = 0
    tot = 0

    def ck(name, cond, info=""):
        nonlocal ok, tot
        tot += 1
        ok += 1 if cond else 0
        print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)[:120]) if info else ""))

    ck("3 条一模一样 → 留 1 条", len([r for r in keep if "红球" in str(r.get("pref"))]) == 1, keep)
    ck("2 条一模一样 → 留 1 条", len([r for r in keep if "漩涡" in str(r.get("pref"))]) == 1, keep)
    ck("**完全无关的两句不许并**（余弦 0.76 但字面 0）",
       len([r for r in keep if "红球" in str(r.get("pref"))]) == 1
       and len([r for r in keep if "漩涡" in str(r.get("pref"))]) == 1, keep)
    ck("不同类的那句**一个字不动**", any("夜里写代码" in str(r.get("pref")) for r in keep), keep)
    ck("空正文不算重复、也原样留着", any(not str(r.get("pref") or "").strip() for r in keep), keep)
    ck("留下的那条是最早的（3 条同句时）",
       [r for r in keep if "红球" in str(r.get("pref"))][0]["ts"] == 1.0, keep)
    ck("并掉的条数对得上（7 条 → 4 条，并掉 3 条）", len(removed) == 3 and len(keep) == 4,
       "keep=%d removed=%d" % (len(keep), len(removed)))
    ck("被并掉的每条都写明并进了哪一句", all(r.get("into") for r in removed), removed[:1])
    ck("幂等：再跑一遍不再并", len(plan_dedupe(keep)[1]) == 0, plan_dedupe(keep)[1])
    _ok1, _n1 = same_pref("摸到两个红球，世界突然被按了暂停键。",
                          "数字在眼前转，像被甩进一个没有边界的漩涡。")
    ck("复合判据：无关句被挡下（实测余弦 0.760 ≥ 0.75，靠字面那条挡住）", _ok1 is False, _n1)
    _ok2, _n2 = same_pref("摸到两个红球，世界突然被按了暂停键。",
                          "摸到两个红球，世界突然变窄了，像被按了暂停键，连呼吸都慢了下来。")
    ck("复合判据：真同一句仍算同一句", _ok2 is True, _n2)

    print("\n  自测：通过 %d / 共 %d" % (ok, tot))
    return 0 if ok == tot else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return _selftest()
    ap_apply = "--apply" in sys.argv
    path = P._PATH
    rows = _rows_raw(path)
    formed = [r for r in rows if r.get("kind") == "formed"]
    print("=" * 74)
    print("  偏好库存量清理（一模一样的 + 近义的，按本模块 SIMILAR=%.2f）" % P.SIMILAR)
    print("=" * 74)
    print("库文件：%s" % path)
    print("总行数 %d ｜ 其中 formed %d 条" % (len(rows), len(formed)))
    if not formed:
        print("\n没有 formed 记录 —— 不用清理（幂等，不写盘）。")
        return 0

    keep, removed, clusters = plan_dedupe(formed)
    print("\n聚类实况（每一簇一行）：")
    for c in clusters:
        if c.get("solo") or len(c["members"]) <= 1:
            continue
        print("  ×%d  「%s」" % (len(c["members"]), str(c.get("rep"))[:56]))
        for idx, r in c["members"]:
            mark = "留" if r.get("ts") == c.get("kept") else "并"
            print("      [%s] ts=%s  %s" % (mark, str(r.get("ts"))[:16],
                                           str(r.get("pref"))[:56]))
    print("\n结果：formed %d 条 → **%d 条**（并掉 %d 条）" % (len(formed), len(keep), len(removed)))
    if not removed:
        print("没有需要并的 —— 幂等，不写盘。")
        return 0
    print("\n被并掉的行（全部留档，不删）：")
    for r in removed:
        print("  · ts=%s  %s" % (str(r["removed_ts"])[:16], str(r["pref"])[:60]))

    if not ap_apply:
        print("\n（这是 dry 模式，**一个字都没改**。真改请加 --apply）")
        return 0

    # ---- 备份 + 原子写回 ----
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bak = os.path.join(_ROOT, "logs", "_preference_before_dedupe_%s.bak"
                       % time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(path, bak)
    print("\n已备份：%s" % os.path.relpath(bak, _ROOT))

    side = os.path.join(os.path.dirname(path), "preference.deduped.jsonl")
    with io.open(side, "a", encoding="utf-8") as fh:
        for r in removed:
            fh.write(json.dumps(dict(r, at=time.time()), ensure_ascii=False) + "\n")
    print("被并掉的行已留档：%s（%d 行）" % (os.path.relpath(side, _ROOT), len(removed)))

    # 写回：formed 换成去重后的，其余行（别的 kind / 坏行）**原样照抄、顺序不变**
    new_lines = []
    written_formed = 0
    for r in rows:
        if r.get("kind") == "formed":
            if written_formed < len(keep):
                new_lines.append(json.dumps(keep[written_formed], ensure_ascii=False))
                written_formed += 1
            continue
        if "__raw__" in r:
            new_lines.append(r["__raw__"])
        else:
            new_lines.append(json.dumps(r, ensure_ascii=False))
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(new_lines) + ("\n" if new_lines else ""))
    os.replace(tmp, path)
    print("已写回：%s（formed %d 条）" % (os.path.relpath(path, _ROOT), written_formed))
    print("（复核：库里 formed 现在 %d 条；并掉的 %d 条在上面的留档文件里，一个字没丢）"
          % (len([r for r in _rows_raw(path) if r.get("kind") == "formed"]), len(removed)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
