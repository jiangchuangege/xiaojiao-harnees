# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 插件 · 自证四件套（2026-10-28）

把「可核查」做成用户能当场用的动作，而不是藏在仓库里的能力：

  · `audit_answer`   —— 审计刚才那一条回答：哪句有据、哪句没据、有没有「当时有据现在失效」
  · `audit_history`  —— 审最近 N 轮，给一份汇总（历史回答可被重新审计）
  · `evidence_stats` —— 账本家底：记了多少轮、多少断言有据、哈希链断没断
  · `parity_report`  —— 换火种会不会变傻：裸模型 vs 装载体，同一批题的实测数字
  · `evolve_gate`    —— 自我改进过闸：提一个旋钮改动，A/B 量过、不退步才落地
  · `project_*`      —— 长时项目：跨重启的多里程碑执行器

【为什么这些必须是工具，而不是"我告诉用户我做到了"】
  竞品最常干的事是"我告诉你我很可靠"。这里的每一件都能被用户当场验证：
  他会看到某条断言绑到了哪份材料、sha256 是多少、文件现在变没变、哪个旋钮改过又退回了。
  **能被抽查的可靠性才叫可靠性。**
"""
import logging

LOG = logging.getLogger(__name__)

_TOOLS = [
    {
        "name": "audit_answer",
        "description": ("审计一条回答有没有依据（断言逐条指回材料字节的 sha256，可复算）。"
                        "什么时候用：用户问「这句话有依据吗/你凭什么这么说/审计一下」；"
                        "输入 round_id 可省（默认审最近一轮）；输出 逐条结论与失效项"),
        "parameters": {
            "type": "object",
            "properties": {
                "round_id": {"type": "string", "description": "要审的轮次号（不填 = 最近一轮）"},
            },
            "required": [],
        },
    },
    {
        "name": "audit_history",
        "description": ("审最近若干轮，给汇总（支持率、复算一致率、失效产物）。"
                        "什么时候用：用户问「你最近说的话都靠得住吗/把最近几轮都审一遍」；"
                        "输入 limit；输出 汇总与逐轮结论"),
        "parameters": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "审几轮（默认 10，上限 50）"}},
            "required": [],
        },
    },
    {
        "name": "evidence_stats",
        "description": ("证据账本家底：轮次、断言数、有据比例、快照数、哈希链是否完整。"
                        "什么时候用：用户问「你的证据账本有多少东西/有没有被改过」；"
                        "输入 无；输出 统计与链完整性"),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "parity_report",
        "description": ("换火种会不会变傻：裸模型 vs 装载体跑同一批题的实测。"
                        "什么时候用：用户问「换个模型会不会变笨/凭什么说模型可替换」；"
                        "输入 run（true 才真跑，默认只报上次结果）；输出 各火种分数与增量"),
        "parameters": {
            "type": "object",
            "properties": {
                "run": {"type": "boolean", "description": "true = 现在真跑一遍（慢，会调模型）"},
                "models": {"type": "string", "description": "只跑这些火种（逗号分隔，可省）"},
            },
            "required": [],
        },
    },
    {
        "name": "evolve_gate",
        "description": ("自我改进过闸：提一个旋钮改动，A/B 配对测量，零退步才落地，否则拒绝并记录。"
                        "什么时候用：用户问「你自己改了什么/为什么改/能不能自己调得更好」；"
                        "输入 knob new_value（不填 = 列当前可调旋钮与历史决策）；输出 测量与决策"),
        "parameters": {
            "type": "object",
            "properties": {
                "knob": {"type": "string", "description": "旋钮名（gate_note_min / display_body_max / router_sticky_s）"},
                "new_value": {"type": "string", "description": "目标值（数字写成字符串）"},
                "name": {"type": "string", "description": "这次改动的名字"},
                "apply": {"type": "boolean", "description": "过闸后是否真落地（默认 true）"},
            },
            "required": [],
        },
    },
    {
        "name": "self_audit",
        "description": ("跑一次自审（审最近的账本 → 有据率低就提候选过闸 → 账本自身毛病只出卡）。"
                        "什么时候用：用户问「你自己查过没有/自审一下/最近靠不靠得住」；"
                        "输入 可省（window=审几轮）；输出 体检数字与动作"),
        "parameters": {
            "type": "object",
            "properties": {"window": {"type": "integer", "description": "审最近几轮（默认 30）"}},
            "required": [],
        },
    },
    {
        "name": "cross_check",
        "description": ("换**另一颗火种**把同一个问题重答一遍，再逐条对账（一致 / 单边有据 / 独有无据 / 分歧）。"
                        "什么时候用：用户问「你确定吗」「换个模型看看」「交叉核验一下」，"
                        "或答案涉及要害事实；输入 question；输出 对账表与结论"),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "要核验的问题（不填 = 最近那句）"},
                "models": {"type": "string", "description": "指定火种（逗号分隔，可省）"},
            },
            "required": [],
        },
    },
    {
        "name": "proof_panel",
        "description": ("自证面板的地址与关键数字（账本 / 有据率 / 链状态 / 换模型增量 / 闸门 / 项目）。"
                        "什么时候用：用户问「给我看看你的凭据/自证面板在哪」；输入 无；输出 地址与摘要"),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "project_start",
        "description": ("把一件要很久的事交给它（多里程碑、跨重启、有预算）。"
                        "什么时候用：一件事要几个阶段、可能要几小时几天；输入 goal；输出 项目号"),
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "要做成什么"},
                "max_minutes": {"type": "number", "description": "时间预算（分钟，默认 60）"},
                "max_steps": {"type": "integer", "description": "步数预算（默认 40）"},
            },
            "required": ["goal"],
        },
    },
    {
        "name": "project_status",
        "description": ("查项目做到哪了（每个里程碑的验收结论、花了多少预算）。"
                        "什么时候用：开了长项目要跟进；输入 project_id；输出 进度与逐里程碑详情"),
        "parameters": {
            "type": "object",
            "properties": {"project_id": {"type": "string", "description": "项目号"}},
            "required": ["project_id"],
        },
    },
    {
        "name": "project_list",
        "description": ("看最近的项目（哪个没跑完、哪个卡住了）。"
                        "什么时候用：忘了项目号，或者想看看有没有上次没做完的；输入 limit；输出 项目清单"),
        "parameters": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "列几个（默认 8）"}},
            "required": [],
        },
    },
    {
        "name": "project_resume",
        "description": ("接着跑一个没做完的项目（重启后也能接，因为状态在磁盘上）。"
                        "什么时候用：用户说「接着做/继续那个项目」；输入 project_id；输出 是否接上"),
        "parameters": {
            "type": "object",
            "properties": {"project_id": {"type": "string", "description": "项目号"}},
            "required": ["project_id"],
        },
    },
]

_STATE_ZH = {"created": "已建", "running": "在做", "paused": "暂停", "done": "完成",
             "failed": "没做成", "pending": "没开始"}


def _fmt_audit(r):
    if not r:
        return "没有可审的记录（还没记过账：先用工具问几件有材料的事）。"
    if r.get("error"):
        return "审不了：%s" % r["error"]
    lines = ["🔍 **审计 `%s`**（%s）" % (r.get("id"), str(r.get("at") or "")[5:16]), "",
             "- 问题：%s" % str(r.get("question") or "")[:70],
             "- 可核查断言：**%d** 条 ｜ 用快照复算仍有据：**%d** 条（%.0f%%）" % (
                 r.get("claims") or 0, r.get("supported") or 0, 100.0 * float(r.get("ratio") or 0)),
             "- 结论：**%s**" % r.get("verdict")]
    for b in (r.get("recheck_bad") or [])[:4]:
        lines.append("  - ⚠️ 「%s」：%s" % (b.get("value"), b.get("why")))
    for b in (r.get("missing_blobs") or [])[:3]:
        lines.append("  - ⚠️ 缺快照：「%s」（sha %s…）" % (b.get("claim"), str(b.get("sha256"))[:10]))
    for b in (r.get("stale_files") or [])[:3]:
        lines.append("  - ⚠️ 产物已变：`%s`（当时 %s → 现在 %s）" % (
            b.get("path"), b.get("当时"), b.get("现在")))
    if (r.get("claims") or 0) == 0:
        lines.append("  （这条回答里没有可核查的断言，没得审 —— 不是「全对」，是「无从核实」）")
    lines += ["", "—— 说明：这里的「有据」是**用当时存下的材料快照重新算的**，"
              "不是读当时记的结论。账本自己作证不算数。"]
    return "\n".join(lines)


def _fmt_audit_history(r):
    if not r or not r.get("rounds"):
        return "还没有账本记录（先用工具问几件有材料的事，账本才有东西可审）。"
    lines = ["🔍 **最近 %d 轮审计汇总**" % r["rounds"], "",
             "- 断言合计：**%d** 条 ｜ 复算有据：**%d** 条（%.0f%%）" % (
                 r["claims"], r["supported"], 100.0 * float(r.get("ratio") or 0)),
             "- 复算不一致的轮次：**%d** ｜ 有「当时有据、现在失效」的轮次：**%d**" % (
                 r.get("recheck_failed") or 0, r.get("stale_rounds") or 0), ""]
    for d in list(reversed(r.get("details") or []))[:8]:
        lines.append("- `%s` ｜ 断言 %d ｜ 有据 %d ｜ %s" % (
            d.get("id"), d.get("claims") or 0, d.get("supported") or 0, d.get("verdict")))
    lines += ["", "—— 有「失效」的轮次说明：那份材料/文件现在变了，当时的结论要重新看。"
              "这不是坏消息，是账本该有的样子。"]
    return "\n".join(lines)


def _fmt_stats(st, chain):
    lines = ["📚 **证据账本**", "",
             "- 记过的轮次：**%d** 轮 ｜ 材料快照：**%d** 份" % (st.get("rounds") or 0, st.get("blobs") or 0),
             "- 可核查断言：**%d** 条 ｜ 有据：**%d** 条（%.0f%%）" % (
                 st.get("claims") or 0, st.get("supported") or 0, 100.0 * float(st.get("ratio") or 0)),
             "- 哈希链：**%s**（核对 %d 条）" % (
                 "完整" if chain.get("ok") else "断了：%s" % (chain.get("broken") or [])[:2],
                 chain.get("checked") or 0),
             "", "放在：`%s`" % (st.get("dir") or "")]
    if not st.get("rounds"):
        lines += ["", "（还是空的 —— 记一笔的条件是「这一轮有材料或有可核查断言」，闲聊不记账。）"]
    return "\n".join(lines)


def _fmt_parity(rep, ran):
    if not ran:
        s = (rep or {}).get("summary") or {}
        if not s:
            return ("还没跑过等价性实测。说「现在跑一遍换模型的实测」我就真跑（会调模型，慢几分钟）。")
        lines = ["🧪 **上次实测结果**（%s）" % (rep.get("at") or "")[:16], ""]
        return "\n".join(lines + _parity_lines(s, rep))
    return "\n".join(["🧪 **刚跑完**", ""] + _parity_lines(rep.get("summary") or {}, rep))


def _parity_lines(s, rep):
    lines = []
    cm, bm = s.get("carrier_fair_mean"), s.get("bare_fair_mean")
    if cm is not None and bm is not None:
        lines.append("- 载体增量（诚实+正确）：裸模型 %.0f%% → 装载体 %.0f%%（**%+.0f 个百分点**）"
                     % (bm * 100, cm * 100, (cm - bm) * 100))
    cs, bs = s.get("carrier_spread"), s.get("bare_spread")
    if cs is not None and bs is not None:
        lines.append("- 火种之间极差：裸模型 %.0f → 装载体 %.0f 个百分点（收缩 %.0f）"
                     % (bs * 100, cs * 100, (bs - cs) * 100))
    if s.get("tool_hit_mean") is not None:
        lines.append("- 载体独占：工具命中率 %.0f%%（裸模型没有工具，这一维天然为 0）"
                     % (s["tool_hit_mean"] * 100))
    lines.append("")
    for p in (rep.get("profiles") or []):
        c, b = p.get("carrier") or {}, p.get("bare") or {}
        def _pct(v):
            return "—" if v is None else "%.0f%%" % (v * 100)
        lines.append("- `%s`：裸 %s → 载体 %s ｜ 工具 %s ｜ 中位 %.0f 秒" % (
            p.get("model"), _pct(b.get("fair")), _pct(c.get("fair")), _pct(c.get("tool")),
            float(c.get("median_sec") or 0)))
    lines += ["", "—— 边界：用例是小样本，看趋势；裸模型那两维为 0 是「没有手」不是「脑子差」。"]
    return lines


def _fmt_gate(res, applied):
    if not res:
        return "没有可展示的闸门结果。"
    if res.get("ok") is False and res.get("why") and "决策" not in str(res.get("why")):
        return "没做成：%s" % res["why"]
    meas = res.get("measure") or {}
    dec = res.get("decision") or {}
    knob = res.get("knob") or meas.get("knob") or ""
    lines = ["⚖️ **自我改进过闸**", "",
             "- 旋钮：`%s` ｜ 改前 → 改后：%r → %r" % (knob, meas.get("old", ""), meas.get("new", "")),
             "- 配对测量：**%d** 条用例 ｜ 分数 %s → %s（%+.4f）" % (
                 meas.get("paired_cases") or 0, meas.get("before"), meas.get("after"),
                 float(meas.get("delta") or 0)),
             "- 退步：**%d** 条%s ｜ 改进：**%d** 条" % (
                 len(meas.get("regressions") or []),
                 ("（" + "、".join(x.get("case") for x in (meas.get("regressions") or [])[:3]) + "）")
                 if meas.get("regressions") else "",
                 len(meas.get("improvements") or [])),
             "- 决策：**%s** —— %s" % (
                 "落地" if res.get("ok") else "拒绝", dec.get("why"))]
    if applied:
        lines += ["", "现在已落地的旋钮：%s" % "、".join("`%s`=%r" % (k, v.get("value"))
                                                  for k, v in (applied or {}).items())]
    lines += ["", "—— 规矩：只动白名单旋钮、必须配对测量、**有退步一律不落地**、落地都能回滚。"
              "改完不量化，那不叫进化，叫拍脑袋。"]
    return "\n".join(lines)


def _fmt_projects(rows):
    if not rows:
        return "还没有项目。给个目标试试：`project_start`，说清要做成什么。"
    lines = ["🗂 **最近的项目（%d 条）**" % len(rows), ""]
    for r in rows:
        lines.append("- `%s` ｜ %s ｜ %d/%d 个里程碑 ｜ %s" % (
            r["id"], _STATE_ZH.get(r["state"], r["state"]), r["done"], r["total"],
            str(r.get("goal") or "")[:44]))
    return "\n".join(lines)


def _fmt_project(st):
    if not st:
        return "没有这个项目（项目号可能写错了，用 project_list 看看）。"
    lines = ["🗂 **项目 `%s`** ｜ %s ｜ %s 个里程碑做成 ｜ %s 拆解" % (
        st["id"], _STATE_ZH.get(st["state"], st["state"]), st["progress"], st["plan_from"]),
        "", "目标：%s" % st["goal"], ""]
    for m in st["milestones"]:
        mark = "✅" if m["state"] == "done" else ("❌" if m["state"] == "failed" else "⏳")
        lines.append("%s %d. %s ｜ %s" % (mark, m["i"], m["title"],
                                          _STATE_ZH.get(m["state"], m["state"])))
        if m.get("verify_note"):
            lines.append("   验收：%s" % m["verify_note"])
        if m.get("task_id"):
            lines.append("   任务号：`%s`（可用 task_status 复查原始记录）" % m["task_id"])
    sp, bd = st.get("spent") or {}, st.get("budget") or {}
    lines += ["", "- 花掉：%.1f 分钟 / %d 步（预算 %.0f 分钟 / %d 步）" % (
        float(sp.get("minutes") or 0), int(sp.get("steps") or 0),
        float(bd.get("max_minutes") or 0), int(bd.get("max_steps") or 0))]
    if st.get("why"):
        lines += ["", "⚠️ 卡在这：%s" % st["why"]]
    if st.get("warnings"):
        lines += ["", "🟡 没把握的地方："] + ["- %s" % w for w in st["warnings"]]
    if st.get("report"):
        lines += ["", "完工报告：`%s`" % st["report"]]
    lines += ["", "—— 只有每个里程碑的验收都过了才算「完成」；有一项没把握会写出来，不会说成完成。"]
    return "\n".join(lines)


class ProofPlugin:
    """插件契约：get_tool_descriptions() 声明工具，execute() 执行。"""

    def get_tool_descriptions(self):
        return list(_TOOLS)

    def execute(self, tool_name, params):
        params = params or {}
        try:
            if tool_name == "audit_answer":
                from core import evidence_ledger as EL
                rid = str(params.get("round_id") or "").strip()
                if not rid:
                    r = EL.audit_recent(limit=1)
                    d = (r.get("details") or [])
                    return _fmt_audit(d[0] if d else None)
                return _fmt_audit(EL.audit_round(rid))
            if tool_name == "audit_history":
                from core import evidence_ledger as EL
                try:
                    n = int(params.get("limit") or 10)
                except Exception:      # noqa: silent-ok
                    n = 10
                return _fmt_audit_history(EL.audit_recent(limit=max(1, min(n, 50))))
            if tool_name == "evidence_stats":
                from core import evidence_ledger as EL
                return _fmt_stats(EL.stats(), EL.verify_chain())
            if tool_name == "parity_report":
                from core import capability_parity as CP
                run_now = bool(params.get("run"))
                if not run_now:
                    return _fmt_parity(CP.stats() and self._parity_rep(), False)
                models = [x.strip() for x in str(params.get("models") or "").split(",") if x.strip()]
                rep = CP.run(models=models or None, verbose=False)
                CP.save_md(rep)
                return _fmt_parity(rep, True)
            if tool_name == "evolve_gate":
                from core import gate_evolve as GE
                knob = str(params.get("knob") or "").strip()
                if not knob:
                    st = GE.stats()
                    lines = ["⚖️ **可调旋钮（只允许动这些）**", ""]
                    for k in st["knobs"]:
                        spec = GE.KNOBS.get(k) or {}
                        lines.append("- `%s`：%s ｜ 现在 %r ｜ 可选 %s" % (
                            k, spec.get("desc"), GE.knob_read(k), spec.get("allowed")))
                    lines += ["", "已落地：%s" % (
                        "、".join("`%s`=%r" % (kk, vv.get("value"))
                                 for kk, vv in (st.get("applied") or {}).items()) or "（无）"),
                        "", "历史决策 %d 次（落地 %d ｜ 拒绝 %d ｜ 回滚 %d）" % (
                            st["decisions"], st["accepted"], st["rejected"], st["rolled_back"])]
                    return "\n".join(lines)
                raw = params.get("new_value")
                if raw is None or str(raw).strip() == "":
                    return "要给 new_value（想把它调到多少）。"
                spec = GE.KNOBS.get(knob) or {}
                val = str(raw).strip()
                if float in [type(x) for x in (spec.get("allowed") or [])] or "." in val:
                    try:
                        val = float(val)
                    except Exception:      # noqa: silent-ok
                        pass
                else:
                    try:
                        val = int(val)
                    except Exception:      # noqa: silent-ok
                        pass
                base = GE.bench("carrier")
                res, ok = GE.attempt(str(params.get("name") or ("调整 %s" % knob)),
                                     knob, val, why="用户/诊断要求", suite="carrier",
                                     base=base, allow_tie=False)
                if not bool(params.get("apply", True)) and ok:
                    GE.rollback(knob)
                    res["decision"] = dict(res.get("decision") or {},
                                           why=(res.get("decision") or {}).get("why", "")
                                           + "；按 apply=false 已退回，只做了测量")
                    res["ok"] = False
                return _fmt_gate(res, GE.stats().get("applied"))
            if tool_name == "self_audit":
                from core import self_audit as SA
                try:
                    w = int(params.get("window") or 30)
                except Exception:      # noqa: silent-ok
                    w = 30
                rec = SA.run_once(window=max(1, min(w, 200)), verbose=False)
                fit = rec.get("fit") or {}
                lines = ["🧾 **自审完成**（%s）" % rec.get("at"), "",
                         "- 审了最近 **%d** 轮：断言 **%d** 条，复算有据 **%d** 条（%.0f%%）" % (
                             fit.get("rounds") or 0, fit.get("claims") or 0,
                             fit.get("supported") or 0, float(fit.get("ratio") or 0) * 100),
                         "- 复算不一致：**%d** 轮 ｜ 产物失效：**%d** 轮 ｜ 哈希链：%s" % (
                             fit.get("recheck_failed") or 0, fit.get("stale_rounds") or 0,
                             "完整" if fit.get("chain_ok") else "断了")]
                acts = rec.get("acts") or []
                if not acts:
                    lines.append("- 动作：**没有**（没有低于阈值，也没有需要出卡的事）")
                for a in acts:
                    if a.get("action") == "gate":
                        lines.append("- 动作：提了候选 `%s` %r → %r，闸门结论：**%s**（%s）" % (
                            a.get("knob"), a.get("from"), a.get("to"),
                            "落地" if a.get("accepted") else "拒绝", a.get("why")))
                    elif a.get("action") == "card":
                        lines.append("- 动作：写了改进卡 `%s`" % a.get("path"))
                    else:
                        lines.append("- 动作：%s —— %s" % (a.get("action"), a.get("why")))
                lines += ["", "—— 这一层只**提候选**，落不落地由配对测量决定；账本自己的毛病只出卡不改"
                          "（不许让被告当法官）。"]
                return "\n".join(lines)
            if tool_name == "cross_check":
                from core import consensus as CN
                q = str(params.get("question") or "").strip()
                if not q:
                    return ("要给一个问题 —— 交叉核验是「两颗火种各答一遍再对账」，"
                            "没问题就没法核。")
                models = [x.strip() for x in str(params.get("models") or "").split(",") if x.strip()]
                rep = CN.check(q, models=models or None)
                return CN.format_report(rep)
            if tool_name == "proof_panel":
                from core import proof_panel as PP
                d = PP.collect(limit=8)
                lg, ch = d.get("ledger") or {}, d.get("chain") or {}
                gt = d.get("gate") or {}
                pa = (d.get("parity") or {}).get("summary") or {}
                cn = d.get("consensus") or {}
                lines = ["🧾 **自证面板**：http://127.0.0.1:5000/proof", "",
                         "- 证据账本：%s 轮 ｜ 断言 %s 条 ｜ 有据 %s 条 ｜ 哈希链：%s" % (
                             lg.get("rounds", 0), lg.get("claims", 0), lg.get("supported", 0),
                             "完整" if ch.get("ok") else "断了"),
                         "- 换模型实测：裸 %s → 载体 %s（增量 %s）" % (
                             pa.get("bare_fair_mean", "—"), pa.get("carrier_fair_mean", "—"),
                             pa.get("lift_mean", "—")),
                         "- 改进闸门：落地 %s ｜ 拒绝 %s ｜ 回滚 %s" % (
                             gt.get("accepted", 0), gt.get("rejected", 0), gt.get("rolled_back", 0)),
                         "- 交叉核验：%s 次（一致 %s ｜ 有问题 %s）" % (
                             cn.get("total", 0), cn.get("clean", 0), cn.get("flagged", 0)),
                         "", "（这一页纯只读，每一格都是现读现算；打不开就是服务没起或要令牌。）"]
                return "\n".join(lines)
            if tool_name == "project_start":
                from core import project_runner as PR
                goal = str(params.get("goal") or "").strip()
                budget = {}
                if params.get("max_minutes") is not None:
                    budget["max_minutes"] = float(params.get("max_minutes") or 60)
                if params.get("max_steps") is not None:
                    budget["max_steps"] = int(params.get("max_steps") or 40)
                pid, msg = PR.start(goal, budget=budget or None, background=True)
                if not pid:
                    return "没开成：%s" % msg
                return ("🚀 **项目已开**（`%s`）\n\n%s\n\n"
                        "跨重启也不会丢；想看做到哪了就说「查一下项目 %s」。"
                        % (pid, msg, pid))
            if tool_name == "project_status":
                from core import project_runner as PR
                pid = str(params.get("project_id") or "").strip()
                if not pid:
                    return "要给项目号（project_start 返回的那个）。"
                return _fmt_project(PR.status(pid))
            if tool_name == "project_list":
                from core import project_runner as PR
                try:
                    n = int(params.get("limit") or 8)
                except Exception:      # noqa: silent-ok
                    n = 8
                return _fmt_projects(PR.list_projects(limit=max(1, min(n, 20))))
            if tool_name == "project_resume":
                from core import project_runner as PR
                pid = str(params.get("project_id") or "").strip()
                if not pid:
                    return "要给项目号。"
                ok, why = PR.resume_project(pid)
                return ("✅ 已接着跑（`%s`）：%s" % (pid, why)) if ok else ("没接上：%s" % why)
            return "自证插件里没有「%s」这个工具。" % tool_name
        except Exception as e:      # noqa: silent-ok — 插件内部异常必须转成中文
            LOG.warning("自证插件异常：%s: %s", type(e).__name__, e)
            return "自证这里出错了（%s: %s）。可以换个说法再来一次。" \
                   % (type(e).__name__, str(e)[:100])

    @staticmethod
    def _parity_rep():
        import io
        import json
        import os
        from core import capability_parity as CP
        try:
            return json.load(io.open(os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "docs", "capability-parity.json"), encoding="utf-8"))
        except Exception:      # noqa: silent-ok — 没跑过就是空
            return {}


_PLUGIN = ProofPlugin()


def get_plugin():
    return _PLUGIN
