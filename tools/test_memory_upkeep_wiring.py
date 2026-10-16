# -*- coding: utf-8 -*-
"""记忆保养 · 接线自测（验的是"真接进主链路了"，不是"函数写好了"）。

为什么单独要一条：这个模块补的正是 `docs/modules/03-memory-depth.md` 7.1 那张表
记着的那个缺口 —— **机制写好了、自测全绿、但主链路一次都没调过**。
所以这里不测保养内部（那是 `test_memory_upkeep.py` 的事），只测三件事：

  ① 检索出口**真的**在记账（`_retrieve_memory` 调过 `note_usages_async`）；
  ② 检索出口**真的**在补联想素材（`associations()` 被调、且结果拼进了注入文本）；
  ③ 写入路径**真的**在用分层判断（`classify()` 被调；寒暄进表达层不存原句、
     事实层把分层理由写进 meta），以及启动时**真的**会起保养线程。

⚠️ 不联网、不调模型：检索走本机向量库，`_remember_turn` 只做写入侧的确定性处理。
   真写库的那几条**先备份、完事还原**（记忆库是用户资产）。
"""
import json
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from core import memory_deep as MD      # noqa: E402
from core import memory_upkeep as MU    # noqa: E402
from core import memory_vec as MV       # noqa: E402

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


def main():
    t0 = time.time()
    print("=" * 78)
    print("  记忆保养 · 接线自测（检索出口记账/联想 + 写入路径分层 + 启动起线程）")
    print("=" * 78)

    import xiaojiao_app as app       # noqa: E402

    db = MV.path()
    blob = None
    if os.path.exists(db):
        with open(db, "rb") as f:
            blob = f.read()

    try:
        # ---------------- 一、检索出口：记账 ----------------
        print("\n[一] 检索出口真的在记账（引用数是巩固的唯一输入）")
        MU._state["note_at"] = 0.0
        runs0 = MU.status()["note_runs"]
        hits = []
        try:
            from core import retriever as _R
            hits = (_R.retrieve("我住在哪", top_k=3, threshold=0.6) or {}).get("hits") or []
        except Exception as e:      # noqa
            ck("检索本身可用（否则下面测不到接线）", False, "%s: %s" % (type(e).__name__, e))
        app._retrieve_memory("我住在哪")
        for _ in range(60):
            if MU.status()["note_runs"] > runs0:
                break
            time.sleep(0.05)
        if hits:
            ck("**检索一命中就记账**（note_runs 增加）",
               MU.status()["note_runs"] > runs0, "%s → %s" % (runs0, MU.status()["note_runs"]))
        else:
            ck("本机这个库对这句没有命中：记账不触发是**正确行为**（不编数字）",
               MU.status()["note_runs"] == runs0, "命中 0 条")

        # ---------------- 二、检索出口：联想 ----------------
        print("\n[二] 检索出口真的在补联想素材")
        ck("联想开关默认开（capabilities.memory_associations）",
           app.CAP.get("memory_associations", True) is True)
        src = open(os.path.join(_ROOT, "xiaojiao_app.py"), encoding="utf-8").read()
        ck("`_retrieve_memory` 里调了 associations()（静态核对接线在）",
           "associations(_top.get(\"id\")" in src or "associations(_top.get('id')" in src)
        if hits:
            top = hits[0]
            asso = MD.associations(top.get("id"), limit=2) or []
            txt = app._retrieve_memory("我住在哪") or ""
            if asso:
                ck("联想结果被拼进注入文本（素材真的多出来了）",
                   "同一件事的其他侧面" in txt, txt[-60:].replace("\n", " "))
            else:
                ck("这条记忆没有邻居：不拼任何东西也是正确行为",
                   "同一件事的其他侧面" not in txt)
        else:
            ck("没有命中 → 不联想（不编素材）", True, "跳过")

        # ---------------- 三、写入路径：分层判断 ----------------
        print("\n[三] 写入路径真的在用分层判断（只加不删：不改「存不存」）")
        ck("`_remember_turn` 里调了 classify()（静态核对接线在）", "classify(_q)" in src)
        ck("表达层那条会额外学一次风格（remember_expression）",
           "remember_expression(_q)" in src)
        # 行为核对：分层结果与理由真的落进 meta；**是否入库不受影响**（既有契约不动）
        n0 = len(MD._all_rows())
        app._remember_turn("在吗", "在的呀，我在这儿呢，你说。")
        rows1 = MD._all_rows()
        # 注意：写入侧有**去重**（同一句问题又问一次 → 刷新原行、不新增），
        # 所以这里不能拿"行数 +1"当判据（"在吗"这种句子库里很可能早就有了）；
        # 判据是"这一轮的内容在库里找得到"，那才是"照常入库"的意思。
        _said = [r for r in rows1 if "我在这儿呢" in str(r.get("text") or "")]
        ck("**寒暄照常入库**（`_remember_turn` 的契约是「所有历史对话永久保存」，"
           "`test_mem_filter` 也钉着这一条）", bool(_said),
           "行数 %s → %s ｜ 找到 %d 条" % (n0, len(rows1), len(_said)))
        if _said:
            m0 = _said[0].get("meta") or {}
            ck("寒暄那条被**判成表达层**并记下理由",
               m0.get("layer") == MD.LAYER_EXPRESSION and bool(m0.get("layer_reason")), m0)
        app._remember_turn("我住在济南，是一名后端工程师",
                           "好的，我记住了：你住在济南，是一名后端工程师，以后聊到住址或工作我会按这个说。")
        rows = MD._all_rows()
        n2 = len(rows)
        ck("事实句照常进库（宁可多存，不可丢）", n2 == len(rows1) + 1, "%s → %s" % (len(rows1), n2))
        if n2 > len(rows1):
            last = rows[-1]
            meta = last.get("meta") or {}
            ck("分层结果与理由写进了 meta（事后能回答「这条为什么进这一层」）",
               meta.get("layer") == MD.LAYER_FACT and bool(meta.get("layer_reason")),
               meta)
            ck("kind 没被改（界面统计与既有自测的口径不动）",
               (last.get("kind") or "") in ("dialogue", "tool"), last.get("kind"))

        # ---------------- 四、启动时会起保养线程 ----------------
        print("\n[四] 启动时真的会起保养线程")
        ck("main() 里有 memory_upkeep 的启动调用（静态核对）",
           "memory_upkeep" in src and "_MU.start(" in src)
        ck("保养的开关与间隔走控制文件",
           set(MU.config(app.CAP).keys()) == {"on", "interval_s"}, MU.config(app.CAP))

    finally:
        MU.stop()
        if blob is not None:
            with open(db, "wb") as f:
                f.write(blob)
            MV.reload()
        left = [r for r in MD._all_rows() if "我住在济南，是一名后端工程师" in str(r.get("text") or "")]
        ck("**还原后真实记忆库里没有测试残留**", not left, "残留 %d 条" % len(left))

    print("\n" + "=" * 78)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("  耗时 %.1fs" % (time.time() - t0))
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
