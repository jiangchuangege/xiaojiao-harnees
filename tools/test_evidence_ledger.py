# -*- coding: utf-8 -*-
"""证据账本自测（`core/evidence_ledger.py`）

判据分三层，缺一层这个模块就没意义：
  ① **绑定**：断言能不能指回正确的材料（错绑比不绑更糟）；
  ② **复算**：审计必须**重新算**，不读当时记的结论（否则等于自己作证）；
  ③ **失效**：材料/产物后来变了，能不能如实报出来（"当时有据、现在失效"）。
"""
import io
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS, FAIL = [], []


def ck(name, cond, extra=""):
    if cond:
        PASS.append(name)
        print("  ✅ %s%s" % (name, ("  ← %s" % (extra,)) if extra != "" else ""))
    else:
        FAIL.append(name)
        print("  ❌ %s%s" % (name, ("  ← %s" % (extra,)) if extra != "" else ""))


def main():
    print("=" * 84)
    print("  证据账本 自测")
    print("=" * 84)
    from core import evidence_ledger as EL

    tmp = tempfile.mkdtemp(prefix="xj_ev_")
    backup = (EL._DIR, EL._ROUNDS, EL._BLOBS, EL._LEDGER)
    EL._DIR = tmp
    EL._ROUNDS = os.path.join(tmp, "rounds")
    EL._BLOBS = os.path.join(tmp, "blobs")
    EL._LEDGER = os.path.join(tmp, "ledger.jsonl")
    try:
        # ---------------- 一、绑定 ----------------
        print("\n[一] 绑定：断言要指回**正确**的那份材料")
        trace = [
            {"tool": "get_weather", "args": {"city": "菏泽"}, "result": "菏泽天气：阴 +13°C"},
            {"tool": "web_search", "args": {"q": "比分"}, "result": "报道：西班牙 1:0 阿根廷"},
        ]
        ans = "菏泽今天 +13°C；那场比赛是 1:0。文件在 G:\\dzs\\不存在.md。"
        rid = EL.record_round("菏泽天气和比分", ans, trace)
        ck("带材料的回答会入账", bool(rid), rid)
        rec = EL.load_round(rid)
        ck("单轮文件真的落盘了", bool(rec) and rec.get("id") == rid)
        ck("材料条数对（两条工具结果）", len(rec.get("sources") or []) == 2,
           [s.get("tool") for s in rec.get("sources") or []])
        claims = {c["value"]: c for c in (rec.get("claims") or [])}
        ck("抽到了气温断言 13", any("13" in k for k in claims), list(claims)[:4])
        ck("抽到了比分断言", any(c.get("kind") == "比分" for c in claims.values()),
           [c.get("kind") for c in claims.values()])
        ck("抽到了路径断言", any(c.get("kind") == "路径" for c in claims.values()),
           [c.get("kind") for c in claims.values()])
        sup = [c for c in claims.values() if c.get("status") == "supported"]
        ck("有据的断言绑到了来源 id", all(c.get("sources") for c in sup) and sup, len(sup))
        unbound = [c for c in claims.values() if c.get("status") == "unbound"]
        ck("编出来的路径**没被硬绑**（如实记 unbound）",
           any("不存在" in c["value"] or "dzs" in c["value"].lower() for c in unbound),
           [c["value"] for c in unbound])
        ck("统计里区分了有据/无据",
           (rec.get("stats") or {}).get("claims") and
           (rec.get("stats") or {}).get("supported") is not None, rec.get("stats"))

        # 快照内容寻址：同样的材料只存一份
        rid2 = EL.record_round("再问一次天气", "菏泽 +13°C", [trace[0]])
        rec2 = EL.load_round(rid2)
        s1 = (rec.get("sources") or [])[0].get("sha256")
        s2 = (rec2.get("sources") or [])[0].get("sha256")
        ck("同一份材料 → 同一个 sha256（内容寻址）", s1 == s2 and bool(s1), s1[:12])
        ck("快照按 sha 命名", os.path.isfile(os.path.join(EL._BLOBS, str(s1) + ".txt")))
        n_blobs = len([x for x in os.listdir(EL._BLOBS) if x.endswith(".txt")])
        ck("重复材料没有重复存（去重）", n_blobs == 2, "%d 份" % n_blobs)

        # 闲聊不记账
        rid3 = EL.record_round("你好", "你好呀，今天想干点什么？", [], [])
        ck("没有材料也没有断言的闲聊**不记账**", rid3 == "", rid3)

        # ---------------- 二、复算 ----------------
        print("\n[二] 复算：审计要重新算，不读当时记的结论")
        a = EL.audit_round(rid)
        # 这一轮里有一条**编出来的路径**（unbound），所以正确结论是
        # 「部分断言当时就没有依据」—— 既不是"全对"，也不是"账本有问题"。
        ck("审计结论如实区分三种情况（全对/部分无据/账本有问题）",
           a.get("verdict") == "部分断言当时就没有依据", a.get("verdict"))
        ck("复算出来的有据条数 = 当时绑定的条数",
           a.get("supported") == (rec.get("stats") or {}).get("supported"),
           (a.get("supported"), (rec.get("stats") or {}).get("supported")))
        ck("审计结果里没有「复算不一致」", not a.get("recheck_bad"), a.get("recheck_bad"))

        # 篡改：把当时记录的 status 从 unbound 改成 supported → 复算必须抓出来
        tam = EL.load_round(rid)
        for c in tam.get("claims") or []:
            if c.get("status") == "unbound":
                c["status"] = "supported"
                c["sources"] = [c for c in [c.get("sources") or []]][0] or ["s1"]
                break
        EL._atomic_write(os.path.join(EL._ROUNDS, rid + ".json"),
                         json.dumps(tam, ensure_ascii=False, indent=1))
        a2 = EL.audit_round(rid)
        ck("**改了当时记的结论 → 复算能抓出来**", bool(a2.get("recheck_bad")), a2.get("recheck_bad"))
        ck("结论不会因为记录被改就变成「一致」", a2.get("verdict") != "可复算一致", a2.get("verdict"))

        # 快照被删 → 复算必须报"缺证据"，而不是默默算通过
        EL._atomic_write(os.path.join(EL._ROUNDS, rid + ".json"),
                         json.dumps(rec, ensure_ascii=False, indent=1))
        vict = (rec.get("sources") or [])[0].get("sha256")
        os.remove(os.path.join(EL._BLOBS, vict + ".txt"))
        a3 = EL.audit_round(rid)
        ck("快照没了 → 记「缺快照」", bool(a3.get("missing_blobs")), a3.get("missing_blobs"))
        ck("缺证据时结论不是「一致」", a3.get("verdict") != "可复算一致", a3.get("verdict"))

        # ---------------- 三、失效 ----------------
        print("\n[三] 失效：材料/产物后来变了，要如实报")
        d = tempfile.mkdtemp(prefix="xj_art_")
        art = os.path.join(d, "out.md")
        io.open(art, "w", encoding="utf-8").write("原始内容：气温 +13°C\n" * 20)
        trace3 = [{"tool": "get", "args": {"url": "https://a.com"}, "result": "页面：气温 +13°C"},
                  {"tool": "write_file", "args": {"path": art}, "result": "已写入：%s" % art}]
        rid4 = EL.record_round("抓下来存好", "已存 %s，气温 +13°C" % art, trace3)
        rec4 = EL.load_round(rid4)
        files = [s for s in (rec4.get("sources") or []) if s.get("kind") == "file"]
        ck("落盘工具把**产物文件**也登记成来源", bool(files), len(files))
        ck("登记时记了产物当时的 sha256", bool((files or [{}])[0].get("path_sha256")),
           str((files or [{}])[0].get("path_sha256"))[:12])
        a4 = EL.audit_round(rid4)
        ck("文件没变时不算失效", not a4.get("stale_files"), a4.get("stale_files"))
        io.open(art, "w", encoding="utf-8").write("后来被改成了别的内容\n" * 20)
        a5 = EL.audit_round(rid4)
        ck("文件被改 → 报「产物已变」", bool(a5.get("stale_files")), a5.get("stale_files"))
        ck("失效时结论写明「当时有据，现在失效」",
           "失效" in str(a5.get("verdict")), a5.get("verdict"))
        os.remove(art)
        a6 = EL.audit_round(rid4)
        ck("文件被删 → 也说清楚（文件不在了）",
           any("不在" in str(x.get("现在")) for x in (a6.get("stale_files") or [])),
           a6.get("stale_files"))

        # ---------------- 四、哈希链 ----------------
        print("\n[四] 防篡改：哈希链断在哪一条要说出来")
        ch = EL.verify_chain()
        ck("刚写好的链是完整的", ch["ok"] is True and ch["checked"] >= 3, ch)
        lines = [x for x in io.open(EL._LEDGER, encoding="utf-8").read().split("\n") if x.strip()]
        if len(lines) >= 3:
            rec_mid = json.loads(lines[1])
            rec_mid["question"] = "被人改过的问题"
            lines[1] = json.dumps(rec_mid, ensure_ascii=False)
            io.open(EL._LEDGER, "w", encoding="utf-8").write("\n".join(lines) + "\n")
            ch2 = EL.verify_chain()
            ck("中间那条被改 → 链断", ch2["ok"] is False, ch2.get("broken"))
            ck("并且指出是第几条", any(b.get("line") == 3 for b in ch2.get("broken") or []),
               ch2.get("broken"))

        # ---------------- 五、统计与报告 ----------------
        print("\n[五] 统计与给人看的报告")
        st = EL.stats()
        ck("统计能报出轮次/断言/有据比例", st["rounds"] >= 3 and st["claims"] >= 3, st)
        ck("统计里没有负数（口径不乱）", st["ratio"] >= 0 and st["blobs"] >= 1, st)
        md = EL.report_md(limit=10)
        ck("报告是 Markdown 且带总览", md.startswith("# ") and "总览" in md, md[:40])
        ck("报告里写了「复算」而不是只抄当时结论", "复算" in md)
        agg = EL.audit_recent(limit=10)
        ck("汇总能一次审多轮", agg["rounds"] >= 3, agg["rounds"])
        ck("汇总里有逐轮细节", len(agg["details"]) == agg["rounds"])
    finally:
        EL._DIR, EL._ROUNDS, EL._BLOBS, EL._LEDGER = backup
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 84)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("=" * 84)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
