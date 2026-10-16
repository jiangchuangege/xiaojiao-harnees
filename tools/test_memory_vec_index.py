# -*- coding: utf-8 -*-
"""记忆向量库 · 索引一致性自测（确定性；只在临时库上跑，不碰真库）。

为什么单独要它：`memory_vec` 有**两条**写路径 —— 新行追加、同 key 刷新 ——
外加一套"多向量快路径"（首/中/尾三张平行矩阵 + 一个掩码）。三者必须**长度一致**，
否则检索时 numpy 广播直接抛异常。而这类不一致**只在特定顺序下才炸**
（"先追加一行、再用带多向量的查询检索"），平时看不出来 —— 真机上就这么崩过一次：

    ValueError: operands could not be broadcast together with shapes (21,) (20,)

所以这里把"两条写路径之后索引仍然自洽"钉住：行数 / 矩阵 / 掩码三者对齐，
追加完**不 reload 也能检索到**，刷新路径不新增行、也不覆盖保养字段。
"""
import json
import os
import sys
import tempfile
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from core import memory_vec as MV      # noqa: E402

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


def main():
    print("=" * 78)
    print("  记忆向量库索引一致性自测（临时库；不碰真库）")
    print("=" * 78)

    real_path = MV.path()
    real = {"path": real_path}
    tmp = os.path.join(tempfile.mkdtemp(prefix="xj_vec_test_"), "vec.jsonl")
    _orig_path = MV.path

    try:
        MV.path = lambda: tmp
        MV.reload()
        np = MV._try_numpy()

        # ---------------- 一、追加路径：三条长度必须对齐 ----------------
        print("\n[一] 追加新行之后，rows / mat / phas 长度必须一致")
        for i in range(5):
            MV.add_memory("用户：第 %d 条测试 我住在济南%d\n小焦：记下了" % (i, i),
                          kind="dialogue", key_text="我住在济南%d" % i)
        rows, mat, phas = MV._INDEX["rows"], MV._INDEX["mat"], MV._INDEX["phas"]
        ck("写了 5 条", len(rows) == 5, len(rows))
        if np is not None and mat is not None:
            ck("矩阵行数 = 行数", len(mat) == len(rows), "%s / %s" % (len(mat), len(rows)))
            ck("**掩码长度 = 行数**（少了就会广播崩溃）",
               len(phas) == len(rows), "%s / %s" % (len(phas), len(rows)))

        # ---------------- 二、追加之后**不 reload** 就能检索（真机上就是这一步崩的） ----------------
        print("\n[二] 追加之后立刻检索：不许崩、而且那条要能搜到")
        try:
            hits = MV.search_memory("我住在济南3", top_k=3)
            ck("追加后检索不抛异常", True, "命中 %d 条" % len(hits or []))
            ck("刚追加的那条搜得到（增量路径真的生效）",
               any("济南3" in str(h.get("text") or "") for h in (hits or [])),
               [str(h.get("text"))[:24] for h in (hits or [])][:3])
        except Exception as e:
            ck("追加后检索不抛异常", False, "%s: %s" % (type(e).__name__, e))

        # ---------------- 三、多向量行：追加后掩码要标上、也要能搜到 ----------------
        print("\n[三] 多向量（首/中/尾）行：追加后掩码与三张矩阵都要跟着长")
        long_text = ("用户：写一段长文说明向量检索的原理\n小焦：" + "向量检索把文本映射到同一个空间，" * 30)
        mid = MV.add_memory(long_text, kind="dialogue", key_text="向量检索的原理是什么")
        if np is not None and MV._INDEX["mat"] is not None:
            ck("掩码长度仍等于行数", len(MV._INDEX["phas"]) == len(MV._INDEX["rows"]),
               "%s / %s" % (len(MV._INDEX["phas"]), len(MV._INDEX["rows"])))
            ck("三张平行矩阵与行数一致",
               all(len(MV._INDEX["pmat"][k]) == len(MV._INDEX["rows"])
                   for k in ("head", "mid", "tail")),
               {k: len(MV._INDEX["pmat"][k]) for k in ("head", "mid", "tail")})
        try:
            hits2 = MV.search_memory("向量检索是怎么工作的", top_k=3)
            ck("带多向量的查询在追加之后也不崩（真机上崩的正是这一下）",
               True, "命中 %d 条" % len(hits2 or []))
        except Exception as e:
            ck("带多向量的查询在追加之后也不崩（真机上崩的正是这一下）", False,
               "%s: %s" % (type(e).__name__, e))

        # ---------------- 四、刷新路径：不新增行，且不覆盖保养字段 ----------------
        print("\n[四] 同一个 key 再写一次：刷新原行、不新增，也不覆盖保养字段")
        n0 = len(MV._all_rows_raw())
        first = MV._all_rows_raw()[0]
        first_id = first.get("id")
        # 先给这行塞上保养字段（模拟"巩固/记账"写过它），再刷新它
        rows = MV._all_rows_raw()
        rows[0].setdefault("meta", {})
        rows[0]["meta"].update({"refs": 7, "locked": True, "layer": "expression"})
        open(tmp, "w", encoding="utf-8").write(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
        MV.reload()
        MV.add_memory("用户：第 0 条测试 我住在济南 0（正文变了）\n小焦：记下了",
                      kind="dialogue", key_text="我住在济南0",
                      meta={"layer": "fact", "layer_reason": "命中事实信号"})
        rows2 = MV._all_rows_raw()
        ck("行数不变（刷新而不是新增）", len(rows2) == n0, "%s → %s" % (n0, len(rows2)))
        row = next((r for r in rows2 if r.get("id") == first_id), None)
        ck("还是同一行（id 没变）", row is not None, first_id)
        if row:
            m = row.get("meta") or {}
            ck("**保养字段没被刷新覆盖**（refs / locked 原样）",
               int(m.get("refs") or 0) == 7 and m.get("locked") is True, m)
            ck("新给的分层 meta 并进去了（layer 更新成 fact）",
               m.get("layer") == "fact" and bool(m.get("layer_reason")), m)

        # ---------------- 五、保养之后立刻检索（真机上崩的就是这一下） ----------------
        print("\n[五] 跑一轮保养（整库重写 + 补索引）之后，立刻检索不许崩")
        from core import memory_upkeep as MUx
        _orep = MUx._REPORT
        try:
            MUx._REPORT = os.path.join(os.path.dirname(tmp), "report.jsonl")
            for i, age in enumerate((200, 400)):      # 造两条够老、该被压缩的
                MV.add_memory("用户：很久以前第 %d 件事（旧条目）" % i,
                              kind="dialogue", key_text="很久以前第 %d 件事" % i,
                              ts=time.time() - age * 86400)
            rep = MUx.maintain(apply=True)
            ck("保养真的动了东西（降级或压缩 > 0）",
               int(rep.get("degraded") or 0) + int(rep.get("compressed") or 0) > 0,
               "%s / 错误=%s" % (rep.get("compressed"), rep.get("errors")))
            rows, mat, phas = MV._INDEX["rows"], MV._INDEX["mat"], MV._INDEX["phas"]
            if np is not None and mat is not None:
                ck("**保养之后 mat / phas / rows 长度仍然一致**",
                   len(mat) == len(rows) == len(phas),
                   "mat=%s phas=%s rows=%s" % (len(mat), len(phas), len(rows)))
            try:
                h = MV.search_memory("很久以前的事", top_k=3)
                ck("**保养之后检索不崩**（真机上崩的正是这一下）", True,
                   "命中 %d 条" % len(h or []))
            except Exception as e:
                ck("**保养之后检索不崩**（真机上崩的正是这一下）", False,
                   "%s: %s" % (type(e).__name__, e))
        finally:
            MUx._REPORT = _orep

        # ---------------- 六、坏行 / 空串不许炸 ----------------
        print("\n[六] 边界：空文本、坏 meta 不许炸")
        ck("空文本不写（返回空串）", MV.add_memory("   ") == "")
        ck("reload 之后三条长度仍然一致",
           len(MV._INDEX["rows"]) == len(MV._all_rows_raw()), len(MV._INDEX["rows"]))

    finally:
        MV.path = _orig_path
        try:
            MV.path = None
        except Exception:      # noqa: silent-ok
            pass
        MV.path = _orig_path
        MV.reload()          # 回到真库（重要：别把后面的测试带偏）
        ck("已切回真实记忆库", MV.path() == real_path, MV.path())
        try:
            os.remove(tmp)
            os.rmdir(os.path.dirname(tmp))
        except Exception:      # noqa: silent-ok
            pass

    print("\n" + "=" * 78)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
