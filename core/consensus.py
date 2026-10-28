# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 多火种交叉核验（2026-10-28）

【一句话】同一个问题，**换两颗火种各答一遍**，然后只做一件事：把两边的可核查断言摆在一起对账。

【为什么这件事非做不可（它是"自己审自己"的正面解法）】
  市面上的 AI 说自己"可靠"，靠的是自己的判断。可"自己审自己"有两个死穴：
    ① 同一个模型同一套偏见 —— 它觉得对的地方，再审 10 次还是对（`core/dual_check.py` 已经证明了
       同基座换量化只能缓解，不能解决）；
    ② 它不知道"自己不知道" —— 编出来的数字，自评里照样是 A。
  载体这边的独特条件是：**材料是它自己用工具拿回来的，字节在我们手里**。
  于是可以做一个更硬的动作：让**两颗不同的火种**都读同一批材料、各说一遍，然后：

      · 两边都有、且都能在材料里找到 → 记「一致且有据」（这才叫可靠）
      · 两边都有、但只在一边能对上材料 → 记「一边有据一边没有」（另一方在编）
      · 两边说的**数值不一样** → 记「明确分歧」（这是最值钱的信号：必有一边错）
      · 只有一颗火种提到、且在材料里找不到 → 记「独有且无据」（高危，优先复核）

  **没有一个环节是"让它自己说它对"**：判据是材料字节，第二意见来自另一颗火种。

【和另外两件的关系】
  · `core/evidence_ledger.py`：给**一轮**回答记账（谁说的、依据哪份字节）；
  · `core/dual_check.py`：拿另一个模型审"这条答案靠不靠谱"（判断题）；
  · 本模块：拿另一个模型**重新答一遍**，然后**逐条断言对账**（比对题）。
    三个一起，才叫"多源核验"，缺一个都还能被"它自己说了算"绕过。

【边界（不粉饰）】
  1. 两颗火种同基座时，可能**一起错**（`dual_check` 的实测结论同样适用）；
  2. 交叉核验只判"是否一致/是否有据"，**不判谁对** —— 两边都不一致时只报分歧，不猜答案；
  3. 多跑一颗火种就多一次模型调用，**这是成本**：默认只在用户要求、或答案属高风险时才跑。

落盘：`logs/consensus/<id>.json`（含逐条对账表，可复查）
"""
import io
import json
import logging
import os
import re
import time
import uuid

LOG = logging.getLogger(__name__)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DIR = os.path.join(_ROOT, "logs", "consensus")


def _ensure():
    if not os.path.isdir(_DIR):
        os.makedirs(_DIR, exist_ok=True)


def _models(want=None, max_n=3):
    """挑几颗**不同的**火种。取不到就退回当前那颗（并如实标注只有一个来源）。"""
    out = []
    for m in (want or []):
        if m and m not in out:
            out.append(m)
    if len(out) < 2:
        try:
            from core import model_router as MR
            for m in sorted(MR.available_models() or []):
                if m not in out:
                    out.append(m)
                if len(out) >= max_n:
                    break
        except Exception as e:      # noqa: silent-ok — 拿不到列表就只用一个来源
            LOG.debug("交叉核验：取火种列表失败（%s）", e)
    return out[:max_n]


def _claim_key(c):
    """断言的对账键：同一类 + 归一化后的值（数值/日期/路径都按字符串比）。"""
    try:
        from core import answer_gate as AG
        v = AG._norm(c.get("value"))
    except Exception:      # noqa: silent-ok — 归一化失败就用原值
        v = str(c.get("value") or "").strip()
    return "%s｜%s" % (c.get("kind"), v)


def _kind_zh(kind):
    return {"数值": "数值", "比分": "比分", "日期": "日期", "网址": "网址",
            "路径": "路径", "IP": "IP"}.get(str(kind), str(kind))


def check(question, models=None, max_models=3):
    """跑一次交叉核验。返回报告 dict（并落盘）。

    `models` 不给就自动挑本机可用的（最多 3 颗）。
    """
    q = str(question or "").strip()
    if not q:
        return {"ok": False, "why": "没有要核验的问题"}
    ms = _models(models, max_models)
    if not ms:
        return {"ok": False, "why": "本机没有可用的火种，核验不了"}
    try:
        from core import capability_parity as CP
    except Exception as e:      # noqa: silent-ok — 没有那条腿就走不了
        return {"ok": False, "why": "缺少 capability_parity（%s）" % e}
    try:
        from core import answer_gate as AG
    except Exception as e:      # noqa: silent-ok
        return {"ok": False, "why": "缺少 answer_gate（%s）" % e}

    runs = []
    for m in ms:
        try:
            r = CP.carrier_answer(m, q)
        except Exception as e:      # noqa: silent-ok — 单颗火种崩了不影响别的
            r = {"answer": "", "tools": [], "sec": 0.0,
                 "error": "%s: %s" % (type(e).__name__, str(e)[:80])}
        ans = str(r.get("answer") or "")
        runs.append({"model": m, "answer": ans, "answer_head": ans[:300],
                     "tools": r.get("tools") or [], "evidence": str(r.get("evidence") or ""),
                     "sec": round(float(r.get("sec") or 0.0), 1),
                     "error": r.get("error") or "",
                     "claims": AG.extract_claims(ans)})
    live = [r for r in runs if r.get("claims") or r.get("answer")]
    if len(live) < 2:
        return {"ok": False, "why": "能跑出答案的火种不足两颗（%s）" % (
            "、".join(r["model"] for r in runs))}

    # ---- 逐条对账：同一断言出现在几颗火种里、能不能对上材料 ----
    table = {}
    for r in live:
        ev = AG._norm(r.get("evidence") or "")
        for c in r.get("claims") or []:
            k = _claim_key(c)
            row = table.setdefault(k, {"kind": c.get("kind"), "value": str(c.get("value")),
                                       "models": {}, "supported_by": []})
            supported = bool(ev) and AG._found(c.get("value"), ev, c.get("kind"))
            row["models"][r["model"]] = bool(supported)
            if supported:
                row["supported_by"].append(r["model"])
    n_models = len(live)
    agree, one_side_sup, unique_unsup, mixed = [], [], [], []
    for k, row in table.items():
        who = list(row["models"].keys())
        sup = row["supported_by"]
        if len(who) >= 2:
            if sup and len(sup) < len(who):
                one_side_sup.append(row)
            elif not sup:
                mixed.append(row)          # 多颗火种都提到、但都对不上材料 → 集体无据
            else:
                agree.append(row)
        else:
            if sup:
                agree.append(row)          # 只有一颗提到、但材料支持 → 算有据
            else:
                unique_unsup.append(row)   # 只有一颗提到、且无据 → 高危
    # ---- 数值分歧：同类断言在不同火种里值不同（必有一边错）----
    vals_by_kind = {}
    for k, row in table.items():
        vals_by_kind.setdefault(str(row.get("kind")), set()).add(
            (row.get("value") or "").strip())
    numeric_kinds = {"数值", "比分", "日期", "IP"}
    disputes = [{"kind": kd, "values": sorted(v)}
                for kd, v in vals_by_kind.items() if kd in numeric_kinds and len(v) > 1]

    ok_all = not unique_unsup and not mixed and not one_side_sup
    verdict = ("两颗火种一致，且都能对上材料" if ok_all
               else "有需要复核的地方（见下表）")
    rid = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    rep = {"id": rid, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "question": q[:300],
           "models": [r["model"] for r in live], "n_models": n_models,
           "runs": [{"model": r["model"], "answer_head": r["answer_head"],
                     "tools": r["tools"], "sec": r["sec"], "error": r["error"],
                     "claims": len(r.get("claims") or [])} for r in live],
           "agree": agree, "one_side_supported": one_side_sup,
           "unique_unsupported": unique_unsup, "all_unsupported": mixed,
           "disputes": disputes, "verdict": verdict, "ok": ok_all}
    _ensure()
    try:
        with io.open(os.path.join(_DIR, rid + ".json"), "w", encoding="utf-8",
                     newline="") as f:
            f.write(json.dumps(rep, ensure_ascii=False, indent=1))
    except Exception as e:      # noqa: silent-ok — 存不下不影响结论
        LOG.debug("交叉核验：落盘失败（%s）", e)
    # 顺手记进证据账本（这次核验本身也是一轮"有结论的话"，该被能被复查）
    try:
        from core import evidence_ledger as EL
        _txt = format_report(rep)
        EL.record_round(q, _txt,
                        [{"tool": "cross_check", "args": {"models": rep["models"]},
                          "result": _txt}])
    except Exception as e:      # noqa: silent-ok
        LOG.debug("交叉核验：记账失败（%s）", e)
    LOG.info("交叉核验：%d 颗火种，一致 %d 条，单边有据 %d 条，独有无据 %d 条，集体无据 %d 条",
             n_models, len(agree), len(one_side_sup), len(unique_unsup), len(mixed))
    return rep


def _row_line(row, mark=""):
    who = "、".join(sorted(row.get("models") or {}))
    sup = "、".join(row.get("supported_by") or []) or "都对不上材料"
    return "%s`%s`（%s）— 提到它的火种：%s ｜ 材料支持：%s" % (
        mark, str(row.get("value"))[:40], _kind_zh(row.get("kind")), who, sup)


def format_report(rep):
    """给人看的对账表（也是写进账本的那段话）。"""
    if not rep or rep.get("ok") is False and rep.get("why"):
        return "交叉核验没做成：%s" % (rep or {}).get("why", "未知原因")
    lines = ["🧪 **多火种交叉核验** ｜ %s" % (rep.get("question") or "")[:60], "",
             "火种：%s（%d 颗）" % ("、".join("`%s`" % m for m in rep.get("models") or []),
                                  rep.get("n_models") or 0), ""]
    for r in rep.get("runs") or []:
        tag = "（跑挂了：%s）" % r["error"] if r.get("error") else ""
        tools = ("，工具 %s" % "、".join(r["tools"][:3])) if r.get("tools") else ""
        lines.append("- `%s`：%s%s%s" % (r["model"], str(r["answer_head"])[:110].replace("\n", " "),
                                         tools, tag))
    lines += ["", "**结论：%s**" % rep.get("verdict"), ""]
    agree = rep.get("agree") or []
    if agree:
        lines.append("✅ 一致且有据（%d 条）" % len(agree))
        for row in agree[:6]:
            lines.append("   " + _row_line(row))
    if rep.get("one_side_supported"):
        lines += ["", "⚠️ 一边有据、一边没有（%d 条）—— 没对上材料的那一边可能在编" %
                  len(rep["one_side_supported"])]
        for row in rep["one_side_supported"][:6]:
            lines.append("   " + _row_line(row))
    if rep.get("unique_unsupported"):
        lines += ["", "🔴 只有一颗火种提到、且**材料里找不到**（%d 条）—— 优先复核" %
                  len(rep["unique_unsupported"])]
        for row in rep["unique_unsupported"][:6]:
            lines.append("   " + _row_line(row))
    if rep.get("all_unsupported"):
        lines += ["", "🟡 多颗火种都提到、但都对不上材料（%d 条）—— 可能是共同先验错误" %
                  len(rep["all_unsupported"])]
        for row in rep["all_unsupported"][:6]:
            lines.append("   " + _row_line(row))
    if rep.get("disputes"):
        lines += ["", "⚔️ 明确分歧（同类断言值不一样，**必有一边错**）："]
        for d in rep["disputes"][:5]:
            lines.append("   %s：%s" % (_kind_zh(d.get("kind")),
                                        " ／ ".join(d.get("values") or [])))
    lines += ["", "—— 判据只有两条：**材料字节**（能不能对上）和**另一颗火种**（是不是都这么说）。"
              "没有一环是让它自己说它对。",
              "—— 边界：两颗同基座的火种可能一起错；这里只报「一致/有据/分歧」，不替你猜谁对。"]
    return "\n".join(lines)


def recent(limit=5):
    """最近几次核验（给面板/命令行看）。"""
    out = []
    try:
        names = sorted(os.listdir(_DIR)) if os.path.isdir(_DIR) else []
    except Exception:      # noqa: silent-ok
        names = []
    for fn in reversed(names[-max(1, limit) * 3:]):
        if not fn.endswith(".json"):
            continue
        try:
            with io.open(os.path.join(_DIR, fn), encoding="utf-8") as f:
                out.append(json.load(f))
        except Exception:      # noqa: silent-ok — 坏一个跳过
            continue
        if len(out) >= limit:
            break
    return out


def stats():
    rows = recent(limit=200)
    ok = sum(1 for r in rows if r.get("ok"))
    return {"total": len(rows), "clean": ok, "flagged": len(rows) - ok,
            "dir": _DIR}
