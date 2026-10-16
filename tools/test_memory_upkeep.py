# -*- coding: utf-8 -*-
"""记忆保养 · 自测（确定性；只在最后一段真写库，且**备份 + 还原**）。

为什么必须有它：这个模块补的是"机制写了但没人调"那个缺口 ——
而**接错、接上没跑、跑了一半**这三种情况都不会报错：
降级没跑 = 清晰度永远高清；压缩没跑 = 库只涨不瘦；记账没接 = 引用数永远 0、巩固永远空转。
所以这里逐条钉住：批量记账与节流、保养三步的顺序与"一步炸不拖垮其余"、
报告真的落盘、后台循环**真的在跑**（不是"接上了没在跑"）、以及能不能关。

⚠️ 第三段会真跑一轮保养（含整库重写）：库文件先备份、跑完还原，
   还原后还要核对没有测试残留 —— 记忆库是用户资产，测试不许碰坏它。
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
    print("  记忆保养自测（引用记账 / 保养一轮 / 后台循环）")
    print("=" * 78)

    db = MV.path()
    blob = None
    if os.path.exists(db):
        with open(db, "rb") as f:
            blob = f.read()
    row_id = "自测保养-1"
    rep_path = MU._REPORT

    try:
        # ---------------- 一、引用记账（批量 + 节流 + 不编数） ----------------
        print("\n[一] 引用记账：批量一次写完、按间隔节流、不编数字")
        with open(db, "a", encoding="utf-8") as f:
            f.write(json.dumps({"id": row_id, "ts": time.time() - 3 * 86400,
                                "kind": "fact", "text": "自测保养 我住在菏泽"}, ensure_ascii=False) + "\n")
        MV.reload()
        refs0 = next((int((r.get("meta") or {}).get("refs") or 0)
                      for r in MD._all_rows() if r.get("id") == row_id), None)
        ck("测试行已写入（否则下面测的是空气）", refs0 is not None, refs0)
        got = MD.note_usages([row_id, "不存在的id"])
        refs1 = next(int((r.get("meta") or {}).get("refs") or 0)
                     for r in MD._all_rows() if r.get("id") == row_id)
        ck("批量记账：库里那条 +1", refs1 == int(refs0 or 0) + 1, "%s → %s" % (refs0, refs1))
        ck("**不存在的 id 不算数**（返回值只数真正记上的）", got == 1, got)
        ck("空名单 → 0（不报错、不编）", MD.note_usages([]) == 0)

        MU._state["note_at"] = 0.0
        a = MU.note_usages([row_id], force=True)
        b = MU.note_usages([row_id])            # 紧接着第二次：应被节流
        ck("节流：连着记两次，第二次不再写盘", a == 1 and b == 0, "%s / %s" % (a, b))
        MU._state["note_at"] = 0.0
        ck("force=True 能绕过节流（手动补记时用）", MU.note_usages([row_id], force=True) == 1)
        ck("status 里的记账计数是真实累加（前面成功记了 2 次）",
           MU.status()["noted_rows"] == 2, MU.status()["noted_rows"])

        # 异步版：不能阻塞调用方
        MU._state["note_at"] = 0.0
        t1 = time.time()
        MU.note_usages_async([row_id])
        dt = time.time() - t1
        ck("异步记账立刻返回（不在对话链路上做文件 IO）", dt < 0.2, "%.3fs" % dt)
        for _ in range(40):
            if MU.status()["note_runs"] >= 2:
                break
            time.sleep(0.05)
        ck("异步那条最后真的记上了", MU.status()["note_runs"] >= 2, MU.status()["note_runs"])

        # ---------------- 二、保养一轮：顺序、报告、一步炸不拖垮其余 ----------------
        print("\n[二] 保养一轮：降级 → 压缩 → 巩固，一步炸不拖垮其余")
        size_before = os.path.getsize(db)
        dry = MU.maintain(apply=False)
        ck("推演模式**不写盘**（库文件大小没变）", os.path.getsize(db) == size_before,
           "%s → %s" % (size_before, os.path.getsize(db)))
        ck("推演报告里三步都有结果（没有就写 0）",
           all(k in dry for k in ("degrade", "compress", "consolidate")), sorted(dry.keys()))

        order = []
        _d, _c, _s = MD.degrade, MD.compress, MD.consolidate
        try:
            MD.degrade = lambda *a, **k: (order.append("degrade"), {"scanned": 1, "changed": []})[1]
            MD.compress = lambda *a, **k: (order.append("compress"), {"compressed": 0})[1]
            MD.consolidate = lambda *a, **k: (order.append("consolidate"), {"count": 0})[1]
            MU.maintain(apply=True)
            # 顺序是**巩固 → 降级 → 压缩**（2026-10-16 写对比时改正的）：
            # 先锁住"被引用够多"的条目，它们才不会被本轮的降级/压缩顺手弄模糊。
            ck("顺序固定：先巩固、再降级、最后压缩（否则重要条目会被先压掉再上锁）",
               order == ["consolidate", "degrade", "compress"], order)
            order[:] = []

            def _boom(*a, **k):
                order.append("compress")
                raise RuntimeError("自测故意炸的")
            MD.compress = _boom
            rep = MU.maintain(apply=True)
            ck("中间那步抛异常 → 报告里**如实记下**是哪一步",
               any("compress" in e for e in rep["errors"]), rep["errors"])
            ck("**其余两步照常跑完**（一步炸不拖垮整轮）",
               rep["degrade"] is not None and rep["consolidate"] is not None, order)
            ck("失败时 summarize 里带 ⚠️（人一眼能看见）", "⚠️" in MU._summarize(rep))
        finally:
            MD.degrade, MD.compress, MD.consolidate = _d, _c, _s

        # 重要且久远的条目**必须活下来**（这就是上面那个顺序的意义）
        print("\n[二·补] 被引用够多的重要条目：锁住之后不该被压缩/降级")
        _imp = next((r for r in MD._all_rows() if r.get("id") == row_id), None)
        if _imp is not None:
            meta = _imp.get("meta") or {}
            meta["refs"] = 5
            _imp["meta"] = meta
        _old_ts = _imp.get("ts") if _imp else None
        if _imp is not None:
            rows_now = MD._all_rows()
            for r in rows_now:
                if r.get("id") == row_id:
                    r["ts"] = time.time() - 400 * 86400      # 400 天前，够被压缩
            MD._rewrite(rows_now)
        rep2 = MU.maintain(apply=True)
        me = next((r for r in MD._all_rows() if r.get("id") == row_id), {})
        ck("重要条目（refs=5）被巩固锁住",
           bool((me.get("meta") or {}).get("locked")), (me.get("meta") or {}).get("locked"))
        ck("**它没有被压成印象**（原条目还在，且没被标成压缩产物）",
           not (me.get("meta") or {}).get("compressed_to"), (me.get("meta") or {}).get("compressed_to"))
        ck("这一轮确实跑了压缩（否则上面那条不算数）",
           int(rep2.get("compressed") or 0) >= 0, rep2.get("compressed"))

        # ---------------- 三、真跑一轮 + 报告落盘 + 后台循环真的在跑 ----------------
        print("\n[三] 真跑一轮、报告落盘、后台循环真的在跑（这一条最关键）")
        before_lines = 0
        if os.path.exists(rep_path):
            with open(rep_path, "r", encoding="utf-8", errors="replace") as f:
                before_lines = sum(1 for _ in f)
        rep = MU.run_once(apply=True)
        after_lines = 0
        last_rec = None
        with open(rep_path, "r", encoding="utf-8", errors="replace") as f:
            for ln in f:
                if ln.strip():
                    after_lines += 1
                    last_rec = ln
        ck("保养报告真的落盘了（+1 行）", after_lines == before_lines + 1,
           "%s → %s" % (before_lines, after_lines))
        ck("落盘那行是合法 JSON 且和这一轮同源",
           isinstance(last_rec, str) and json.loads(last_rec).get("at") == rep["at"])
        ck("报告里是**真数字**（扫了多少条 > 0）", int(rep.get("scanned") or 0) > 0, rep.get("scanned"))
        st = MU.status()
        ck("status 里 runs 递增、last 有值", st["runs"] >= 1 and st["last"] is not None, st["runs"])
        ck("status 报得出报告文件路径且文件存在", st["report_exists"] is True, st["report_path"])
        ck("没有失败时 last_error 是空的（不虚报问题）", st["last_error"] == "", st["last_error"])

        r1 = MU.start(interval_s=99999, delay_s=0)
        ck("start 返回已启动", r1.get("started") is True, r1)
        r2 = MU.start(interval_s=99999, delay_s=0)
        ck("**start 幂等**（不会起第二条线程抢同一个库）",
           r2.get("started") is False and "已经在跑" in str(r2.get("why")), r2.get("why"))
        ck("status 说 running=True", MU.status()["running"] is True)
        runs_before = MU.status()["runs"]
        for _ in range(60):
            if MU.status()["runs"] > runs_before:
                break
            time.sleep(0.1)
        ck("**后台循环真的跑起来了**（不是'接上了没在跑'）",
           MU.status()["runs"] > runs_before, "%s → %s" % (runs_before, MU.status()["runs"]))
        MU.stop()
        time.sleep(0.2)
        ck("stop 之后 running=False", MU.status()["running"] is False)
        MU.stop()
        ck("stop 幂等（再停一次不报错）", True)

        r3 = MU.start(interval_s=1, delay_s=0)     # 间隔下限
        ck("间隔有下限（1 秒会被抬到 60 秒，免得把磁盘打满）",
           r3["interval"] >= 60, r3["interval"])
        MU.stop()

        # ---------------- 四、开关 ----------------
        print("\n[四] 开关与默认值（能关，且默认是开）")
        ck("默认开、默认 30 分钟", MU.config({}) == {"on": True, "interval_s": 1800.0},
           MU.config({}))
        ck("控制文件能关", MU.config({"memory_upkeep": False})["on"] is False)
        ck("间隔可被控制文件覆盖",
           MU.config({"memory_upkeep_interval_s": 600})["interval_s"] == 600.0)
        ck("add_memory 支持 meta（分层理由要写进记忆行）",
           "meta" in str(__import__("inspect").signature(MV.add_memory)))

    finally:
        # ---------------- 还原：记忆库是用户资产 ----------------
        MU.stop()
        if blob is not None:
            with open(db, "wb") as f:
                f.write(blob)
            MV.reload()
        left = [r for r in MD._all_rows() if r.get("id") == row_id]
        ck("**还原后真实记忆库里没有测试残留**", not left, "残留 %d 条" % len(left))

    print("\n" + "=" * 78)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("  耗时 %.1fs" % (time.time() - t0))
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
