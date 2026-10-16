# -*- coding: utf-8 -*-
"""接入前后对比（可反复跑；**只碰临时库，不碰真实记忆库**）。

用途：把"没接入"和"已接入"两种状态**用同一份数据各跑一遍**，把差别摊开看。
比讲道理有用 —— 这套机制最容易犯的错不是写错，而是**接上了没在跑**（改了也不报错）。

跑法：
    python tools\\demo_memory_depth_before_after.py

它对比四件事：
    ① 记忆保养：同一份库（含 8/45/200/400 天前的条目 + 被引用过的条目 + 寒暄），
       不跑保养 vs 跑一轮保养 → 清晰度分布 / 印象条目数 / 锁定数 / 库大小怎么变；
    ② 检索出口的口径：问"没记过的事"和"只像但不重合的事"，闸门开 vs 关 → 注入文本差多少；
    ③ 联想：同一条命中，开 vs 关 → 注入素材多出什么；
    ④ 写入路径的分层 + 引用记账：行里有没有 `layer/layer_reason`、`refs` 会不会涨。
最后打印一份"两种状态"的并排小结。
"""
import io
import json
import os
import shutil
import sys
import tempfile
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from core import memory_deep as MD       # noqa: E402
from core import memory_upkeep as MU     # noqa: E402
from core import memory_vec as MV        # noqa: E402
from core import memory_gate as MG       # noqa: E402

DAY = 86400.0
_NOW = time.time()

# 一份"什么都有"的测试库：新条目 / 一周前 / 45 天前 / 200 天前 / 400 天前 /
# 被引用过 3 次的重要条目（也是 400 天前）/ 两条寒暄 / 一条"只有它自己说过"的旧条目
ROWS = [
    ("d1", 1, "用户：我住在济南\n小焦：记下了", "dialogue", {}, ["济南"]),
    ("d2", 8, "用户：我养的猫叫豆豆\n小焦：好记的名字", "dialogue", {}, ["豆豆"]),
    ("d3", 45, "用户：我下周三要去成都出差\n小焦：行程我记着了", "dialogue", {}, ["成都"]),
    ("d4", 200, "用户：我常用的数据库是 PostgreSQL\n小焦：记住了", "dialogue", {}, []),
    ("d5", 400, "用户：我把家里的旧路由器换了\n小焦：好", "dialogue", {}, []),
    ("d6", 400, "用户：我的车牌是京 A12345\n小焦：记下了", "dialogue", {"refs": 5}, []),
    ("d7", 3, "用户：你好\n小焦：你好呀！很高兴见到你。", "dialogue",
     {"layer": "expression", "layer_reason": "短句且命中寒暄词「你好」"}, []),
    ("d8", 2, "用户：在吗\n小焦：在的呀，我在这儿呢。", "dialogue",
     {"layer": "expression", "layer_reason": "短句且命中寒暄词「在吗」"}, []),
    # 与 d1 共用实体「济南」→ 用来演示"联想"里的**实体链**（同一件事的其他侧面）
    ("d9", 12, "用户：济南西站离我家远吗\n小焦：打车大概 20 分钟", "dialogue", {}, ["济南"]),
]


def _build_library(path):
    """造一份可控的测试库（直接写 JSONL，再让 memory_vec 重建索引）。"""
    lines = []
    for rid, age, text, kind, meta, ents in ROWS:
        rec = {"id": rid, "ts": _NOW - age * DAY, "kind": kind, "entities": list(ents),
               "len": len(text), "text": text, "meta": dict(meta)}
        # 向量：直接用 embedder 算一遍（不写死假向量，检索才能真跑）
        vec = MV.embedder.embed(text)
        rec["v"] = MV._pack(vec)
        rec["key"] = text[:400]
        lines.append(json.dumps(rec, ensure_ascii=False))
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def _snapshot():
    """当前库的状态快照（全是真数字）。"""
    rows = MD._all_rows()
    st = MD.stats()
    imp = [r for r in rows if (r.get("kind") or "") == MD.LAYER_IMPRESSION]
    locked = [r for r in rows if (r.get("meta") or {}).get("locked")]
    refs = sum(int((r.get("meta") or {}).get("refs") or 0) for r in rows)
    return {"rows": len(rows), "clarity": st.get("by_clarity_cn") or {},
            "impressions": len(imp), "locked": len(locked), "refs": refs,
            "bytes": os.path.getsize(MV.path()), "rows_obj": rows}


def _clarity_of(rows, rid):
    r = next((x for x in rows if x.get("id") == rid), None)
    if not r:
        return "（那条已经不在了）"
    cl = MD._clarity_of_row(r, _NOW)
    return "%s%s" % (MD.CLARITY_CN.get(cl, cl),
                     "·锁定" if (r.get("meta") or {}).get("locked") else "")


def main():
    real = MV.path()
    tmpdir = tempfile.mkdtemp(prefix="xj_demo_")
    print("=" * 86)
    print("  记忆深度 · 接入前后对比（同一份数据各跑一遍；真实记忆库：%s）" % real)
    print("  临时目录：%s" % tmpdir)
    print("=" * 86)

    orig_path, orig_report = MV.path, MU._REPORT
    try:
        # ---------------- ① 保养：不跑 vs 跑一轮 ----------------
        print("\n【① 记忆保养】同一份库（8 / 45 / 200 / 400 天前 + 一条被引用 5 次的重要条目）\n")
        p_off = os.path.join(tmpdir, "off.jsonl")
        p_on = os.path.join(tmpdir, "on.jsonl")
        p_old = os.path.join(tmpdir, "old_order.jsonl")
        _build_library(p_off)
        shutil.copy2(p_off, p_on)
        shutil.copy2(p_off, p_old)

        MV.path = lambda: p_off
        MV.reload()
        off = _snapshot()

        MV.path = lambda: p_on
        MV.reload()
        MU._REPORT = os.path.join(tmpdir, "report.jsonl")
        rep = MU.run_once(apply=True)          # 今天的顺序：巩固 → 降级 → 压缩
        on = _snapshot()

        # 旧顺序（降级 → 压缩 → 巩固）：写对比时才发现的错法，留在这里当反面证据
        MV.path = lambda: p_old
        MV.reload()
        MD.degrade(now=_NOW)
        MD.compress(now=_NOW)
        MD.consolidate(now=_NOW)
        old_order = _snapshot()

        hdr = "%-24s %-20s %-20s %-20s"
        print(hdr % ("看什么", "没接入（没人调）", "接入后（今天的顺序）", "旧顺序（错的）"))
        print("-" * 90)
        def line(label, a, b, c):
            print(hdr % (label, str(a), str(b), str(c)))
        line("库里条目数", off["rows"], on["rows"], old_order["rows"])
        line("清晰度分布", off["clarity"], on["clarity"], old_order["clarity"])
        line("印象层条目", off["impressions"], on["impressions"], old_order["impressions"])
        line("被锁定（重要）", off["locked"], on["locked"], old_order["locked"])
        line("库文件大小", "%d 字节" % off["bytes"], "%d 字节" % on["bytes"],
             "%d 字节" % old_order["bytes"])
        line("这一轮做了什么", "（没有这一轮）",
             "锁定 %s 降级 %s 压缩 %s" % (rep.get("locked"), rep.get("degraded"),
                                          rep.get("compressed")), "三步都跑了（顺序错）")
        print("\n  逐条看（同一批条目，三种状态下的档位）：")
        print("  %-6s %-8s %-20s %-20s %-20s" % ("id", "多旧", "没接入", "接入后", "旧顺序（错的）"))
        for rid, age, text, kind, meta, ents in ROWS:
            print("  %-6s %-8s %-20s %-20s %-20s" % (rid, "%d 天" % age,
                                                     _clarity_of(off["rows_obj"], rid),
                                                     _clarity_of(on["rows_obj"], rid),
                                                     _clarity_of(old_order["rows_obj"], rid)))
        print("\n  ⚠️ 看 d6：那是**被引用过 5 次**的重要条目（400 天前）。"
              "旧顺序下它先被压成印象、再上锁 —— 锁上也没用了；")
        print("     今天这个顺序（巩固→降级→压缩）先把它锁住，于是它**不会**被降级、也不会被压缩。")
        print("\n  报告落盘那一行（`logs/memory_upkeep.jsonl` 的真实格式）：")
        with io.open(MU._REPORT, encoding="utf-8") as f:
            print("    " + (f.read().strip().splitlines() or ["(空)"])[0][:170])

        # ---------------- ② 口径闸门：关 vs 开 ----------------
        print("\n【② 检索出口的口径】四种情形各来一个（全是真检索 + 真判据）\n")
        MV.path = lambda: p_on
        MV.reload()
        from core import retriever as R
        cases = [("我的手机号是多少", "库里没有"),
                 ("我在哪家公司上班", "库里没有"),
                 ("我住在哪", "库里确实有（1 天前那条）"),
                 ("我的车牌是京 A12345 吗", "库里确实有：400 天前那条，但被巩固锁住了")]
        print("  %-22s %-8s %-6s %s" % ("问", "判成", "重合", "注入给模型的那句话"))
        print("  " + "-" * 96)
        for q, note in cases:
            hits = (R.retrieve(q, top_k=5, threshold=0.6) or {}).get("hits") or []
            r = MG.judge(q, hits)                          # 已接入：开关默认开
            r_off = MG.judge(q, hits, cfg={"on": False})    # 没接入：等于没有这道闸门
            best = r.get("best") or {}
            print("  %-22s %-8s %-6s %s" % (q, r["verdict"] or "（不介入）",
                                            best.get("overlap") if best else "-",
                                            (r["note"] or "（一个字都不加）")[:40]))
            print("  %-22s %-8s %-6s ↳ 情形：%s ｜ 检索命中 %s ｜ 判据用最优那条 %s：%s"
                  % ("", "", "", note,
                     "、".join("%s(%.2f)" % (h.get("id"), float(h.get("score") or 0))
                               for h in hits) or "（0 条）",
                     best.get("id") or "-",
                     str(best.get("text") or "")[:36].replace("\n", " ")))
            assert r_off["note"] == "" and r_off["applied"] is False
        print("\n  差别就是：没接入时**一个字都不加**（模型只能自己决定怎么答），"
              "接入后这句约束会进 system；")
        print("  而「确实记得」那一条（precise）两边**完全一样** —— 好用的地方一个字没动。")
        print("  （「没接入」那侧是 `memory_gate=false` 的真实返回值，不是假装的空串。）")

        # ---- 同一句问句，三种库状态下的口径（这一步最能说明"保养到底帮了什么"）----
        print("\n  ★ 同一句「我的车牌是京 A12345 吗」，在三种库状态下的回答口径：")
        q_plate = "我的车牌是京 A12345 吗"
        for label, path in (("没接入（没人保养）", p_off),
                            ("接入后但顺序是错的", p_old),
                            ("接入后（今天的顺序）", p_on)):
            MV.path = lambda p=path: p
            MV.reload()
            hh = (R.retrieve(q_plate, top_k=5, threshold=0.6) or {}).get("hits") or []
            rr = MG.judge(q_plate, hh)
            bb = rr.get("best") or {}
            plate = next((r for r in MD._all_rows() if r.get("id") == "d6"), {})
            cl = MD.CLARITY_CN.get(MD._clarity_of_row(plate, _NOW), "?") if plate else "?"
            print("    %-22s 那条的状态=%-10s → 口径=%-8s（%s）"
                  % (label, cl + ("·锁定" if (plate.get("meta") or {}).get("locked") else ""),
                     rr["verdict"], rr["reason"][:38]))
        print("    读法：没保养 → 那条随时间变成「印象」，回答只能含糊；顺序错 → 被压掉再上锁，救不回来；")
        print("          今天的顺序 → 先锁住，**400 天前的事仍能精确回答**。")

        # ---------------- ③ 联想：关 vs 开 ----------------
        print("\n【③ 联想】同一条命中，看看「其他侧面」能不能捞出来\n")
        for rid, age, text, kind, meta, ents in ROWS:
            asso = MD.associations(rid, limit=3, now=_NOW) or []
            if asso and any(a.get("kind") == "实体" for a in asso):
                print("  从「%s」出发（它的实体：%s）→" % (text.replace("\n", " ")[:26],
                                                          "、".join(ents) or "无"))
                for a in asso:
                    print("      · [%s] %s（隔 %.1f 天）" % (a.get("kind"), a.get("text")[:34],
                                                             float(a.get("gap_days") or 0)))
                break
        else:
            print("  （这份测试库里没有形成联想关系的条目）")
        print("  没接入：注入的只有检索命中的那几条；接入后：额外补 ≤2 条邻居当素材"
              "（每条 ≤60 字，不替代检索排序）。")

        # ---------------- ④ 写入路径：分层 + 记账 ----------------
        print("\n【④ 写入路径】分层结果有没有记下来、引用数会不会涨\n")
        # 两条**不同的 key**，免得写入侧去重把它们合成一行（去重是既有行为，演示要避开它）
        old = next((r for r in MD._all_rows() if r.get("id") == "d1"), {})
        layer, why = MD.classify("我下周三要去成都出差")
        rid_new = MV.add_memory("用户：我下周三要去成都出差（分层演示）\n小焦：行程我记着了",
                                kind="dialogue", key_text="我下周三要去成都出差（分层演示）",
                                meta={"layer": layer, "layer_reason": why})
        rows = MD._all_rows()
        new = next((r for r in rows if r.get("id") == rid_new), {})
        print("  没接入那行的 meta（直接写库、不带分层）:", old.get("meta") or "（空的）")
        print("  接入后那行的 meta（带分层 + 理由）    :", new.get("meta"))
        before_refs = int((new.get("meta") or {}).get("refs") or 0)
        got = 0
        for _ in range(3):                      # 模拟"三轮对话都检索到它"
            got += MD.note_usages([rid_new]) or 0
        after_refs = int(((next((r for r in MD._all_rows() if r.get("id") == rid_new), {})
                           .get("meta") or {}).get("refs") or 0))
        locked_before = len([r for r in MD._all_rows() if (r.get("meta") or {}).get("locked")])
        MD.consolidate(now=_NOW)
        locked_after = len([r for r in MD._all_rows() if (r.get("meta") or {}).get("locked")])
        print("  引用记账（模拟被检索到 3 次）        : refs %d → %d（写进去 %d 次）"
              % (before_refs, after_refs, got))
        print("  够 3 次 → 再跑一轮巩固                : 锁定数 %d → %d（%s）"
              % (locked_before, locked_after,
                 "锁上了" if locked_after > locked_before else "没锁上"))
        print("  没接入：`note_usage()` 一个调用方都没有 → refs 永远是 0 → 巩固永远不锁任何东西。")

        # ---------------- ⑤ 并排小结 ----------------
        print("\n" + "=" * 86)
        print("  一句话小结")
        print("=" * 86)
        print("  · 保养：没接入 = 库里所有条目**永远是高清**、半年前的事永远不压成印象"
              "（库只涨不瘦、检索越来越吵）；")
        print("          接入后 = 重要条目被锁住不变模糊，其余按时间降级 + 压成印象（原条目仍在，只是更模糊）。")
        print("  · 口径：没接入 = 问「我有没有说过这件事」时，注入是空的，模型自己决定怎么答；")
        print("          接入后 = 载体先给结论（记得 / 只记得大概 / 没记过），模型只负责措辞。")
        print("  · 联想：没接入 = 只有命中的那几条；接入后 = 额外给 ≤2 条「后来呢 / 同一件事的其他侧面」。")
        print("  · 分层与记账：没接入 = 分层结果不落盘、refs 恒为 0（巩固空转）；接入后两者都真的在动。")
    finally:
        MV.path, MU._REPORT = orig_path, orig_report
        MV.reload()
        print("\n（已切回真实记忆库：%s ｜ 临时目录已清理）" % MV.path())
        shutil.rmtree(tmpdir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
