# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 自进化内核（诊断 + 改进项，2026-10-27）

【它补的是最后一环】前面几轮已经有了：
  · 尺子：`tools/eval_xiaojiao.py`（端到端 41 项）、`tools/health_capability.py`（103 个工具真机体检）；
  · 手：`core/plugin_forge.py`（缺能力就自己写插件，带静态检查 + 沙箱）；
  · 记忆：`core/experience.py`（踩过的坑落盘）。
缺的是**看见红点之后知道下一步该动哪儿** —— 这就是本模块。

【它做什么】
  1. 读三份实跑产物：`docs/eval-history.jsonl`（趋势与失败清单）、
     `docs/eval-baseline.md`（失败/半对明细）、`docs/capability-health.md`（工具红点）；
  2. 把每个红点**归类成一种病**（判据/答案/性能/显示/工具参数/环境/未测），
     每种病给出**具体动作**（改哪一层、怎么验），而不是"再优化一下"这种废话；
  3. 按"影响面 × 修复成本"排序，输出前 N 项；
  4. 把诊断结论写进经验库（`evolve_find`），下次同类问题先查历史。

【它不做什么（写清边界，免得被当成万能）】
  · **不自动改源码**：改 `xiaojiao_app.py` / `core/*` 属于高风险动作，必须人看；
  · 只有"缺能力"这一类可以交给 `plugin_forge` 自动落地（它自己有静态检查 + 沙箱两道闸）；
  · 不猜：读不到文件就说读不到，不编红点。
"""
import io
import json
import logging
import os
import re

LOG = logging.getLogger(__name__)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DOCS = os.path.join(_ROOT, "docs")          # 抽出来是为了自测能指到临时目录
_EVAL_HIST = os.path.join(_DOCS, "eval-history.jsonl")
_EVAL_MD = os.path.join(_DOCS, "eval-baseline.md")
_HEALTH_MD = os.path.join(_DOCS, "capability-health.md")

# 病情 → 优先级（数字小 = 先修）与能否自动
_KINDS = {
    "tool_bug":    {"pri": 1, "auto": False, "name": "工具坏了（真报错）"},
    "judge":       {"pri": 2, "auto": False, "name": "判据/路由漏了"},
    "answer":      {"pri": 3, "auto": False, "name": "答案该有的东西没出现"},
    "perf":        {"pri": 4, "auto": False, "name": "太慢"},
    "display":     {"pri": 5, "auto": False, "name": "展示效果差"},
    "health_param":{"pri": 6, "auto": False, "name": "体检参数不合适（工具本身没坏）"},
    "health_untested": {"pri": 7, "auto": False, "name": "没测过"},
    "env":         {"pri": 8, "auto": False, "name": "缺外部条件"},
    "doc":         {"pri": 6, "auto": False, "name": "文档和事实对不上"},
    "capability":  {"pri": 3, "auto": True,  "name": "缺能力（可自动生成插件）"},
}


def _read(path):
    try:
        if not os.path.isfile(path):
            return ""
        return io.open(path, encoding="utf-8").read()
    except Exception as e:      # noqa: silent-ok — 读不到就当没有
        LOG.debug("自进化：读 %s 失败（忽略）：%s", os.path.basename(path), e)
        return ""


def _last_eval():
    """最后一条评测趋势（分数 + 失败清单）。"""
    try:
        lines = [x for x in _read(_EVAL_HIST).split("\n") if x.strip()]
        return json.loads(lines[-1]) if lines else {}
    except Exception:      # noqa: silent-ok
        return {}


def _md_items(path, want_states):
    """从体检/评测的 markdown 里挑出处于特定结论的行：[(名字, 结论, 说明)]。"""
    out = []
    for ln in _read(path).split("\n"):
        s = ln.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 3:
            continue
        name = cells[0].strip("` ")
        state = cells[2]
        if state in want_states:
            out.append((name, state, cells[3] if len(cells) > 3 else ""))
    return out


def _kind_of_eval(item):
    """把评测失败清单里的一句话归类，并给出动作。"""
    s = str(item or "")
    low = s.lower()
    if "太慢" in s or "slow" in low:
        return "perf", "查这一轮用了哪个档位、双模型审校有没有被触发；对纯计算/闲聊应走 fast 档且不审校"
    if "该用" in s or "实际" in s:
        return "judge", "把这句话原样加进判据词表（或路由正则），并补一条离线断言钉住它"
    if "答案里缺" in s or "缺其中之一" in s:
        return "answer", "要么补直答路径（载体先查后措辞），要么把该话术加进判据；别只改判据不改链"
    if "方括号" in s or "噪声" in s:
        return "display", "去噪规则里补这一类行（纯链接/图片/按钮词）"
    if "没有可核查" in s or "无法在本轮材料里核实" in s:
        return "answer", "这条是闸门在正常工作：若属误报，把证据来源补进 tool_trace 的 result"
    return "answer", "看这条属于哪条链，先复现一次再动手"


def _doc_checks():
    """文档与事实是否对得上（目标里的"文档类"改进项）。

    查的都是**能自动比对**的东西，不猜：
      ① `docs/tool-catalog.md` 里写的工具数 vs 真实工具表；
      ② `docs/eval-baseline.md` 的分数 vs `eval-history.jsonl` 最后一行；
      ③ `docs/capability-health.md` 的合计数字 vs 表格里实际行数。
    这三样一旦对不上，读者看到的就是过期数据 —— 比没有文档更误导。
    """
    out = []
    try:
        real_n = None
        try:
            import xiaojiao_app as _app
            real_n = len(_app.all_tool_names())
        except Exception:      # noqa: silent-ok — 拿不到真实工具表就跳过这条
            real_n = None
        cat = _read(os.path.join(_DOCS, "tool-catalog.md"))
        m = re.search(r"工具总数[：:]\s*(\d+)", cat) or re.search(r"工具表\s*(\d+)\s*个", cat)
        if real_n and m and int(m.group(1)) != real_n:
            out.append({"target": "docs/tool-catalog.md",
                        "evidence": "文档写 %s 个，实际 %d 个" % (m.group(1), real_n),
                        "action": "跑 `python tools/gen_tool_catalog.py` 重生成（别手改）"})
        # 评测基线 vs 趋势最后一行
        base = _read(_EVAL_MD)
        mb = re.search(r"得分\s*([\d.]+)%|(\d+\.\d)%", base or "")
        last = _last_eval()
        if last.get("score") is not None and mb:
            doc_score = float(mb.group(1) or mb.group(2))
            if abs(doc_score - float(last["score"])) > 0.05:
                out.append({"target": "docs/eval-baseline.md",
                            "evidence": "文档写 %.1f%%，趋势最后一行是 %s%%"
                                        % (doc_score, last["score"]),
                            "action": "跑 `python tools/eval_xiaojiao.py --save` 刷新"})
        # 体检合计 vs 表格行数
        health = _read(_HEALTH_MD)
        mh = re.search(r"合计\s*(\d+)\s*个?", health)
        if mh:
            rows = sum(1 for ln in health.split("\n")
                       if ln.strip().startswith("|") and "`" in ln)
            if rows and int(mh.group(1)) != rows:
                out.append({"target": "docs/capability-health.md",
                            "evidence": "合计写 %s，表格实际 %d 行" % (mh.group(1), rows),
                            "action": "跑 `python tools/health_capability.py --save` 刷新"})
    except Exception as e:      # noqa: silent-ok — 文档检查失败不许影响诊断
        LOG.debug("自进化：文档检查失败（忽略）：%s", e)
    return out


def _dup_generated():
    """自生成插件里**功能重复**的（只提示，不代删 —— 本项目只加不删）。

    【为什么这条要进诊断】实测膨胀：同一类需求被反复要，自增长长出了
    `cn_num_to_int` / `int_to_cn_num` / `cn_num_to_int_v2` / `int_to_cn_num_v2` / `gen_9dd4e461`
    五个重叠工具。工具表越堆越乱，模型选工具更难 —— 这类"自己给自己添乱"必须能看见。
    处理方式只提示：移不移进隔离区由人决定。
    """
    out = []
    try:
        plugins_dir = os.path.join(_ROOT, "plugins")
        if not os.path.isdir(plugins_dir):
            return out
        buckets = {}
        for fn in os.listdir(plugins_dir):
            if not (fn.startswith("gen_") and fn.endswith(".py")):
                continue
            try:
                src = io.open(os.path.join(plugins_dir, fn), encoding="utf-8").read()
            except Exception:      # noqa: silent-ok
                continue
            for name in re.findall(r'"name"\s*:\s*"([A-Za-z][A-Za-z0-9_]{2,40})"', src):
                # 【只按"去版本后缀后是否同名"判重复】第一版还做了语义归一
                # （把 cn_num_to_int 和 int_to_cn_num 都映射成 num_convert）→ 把两个
                # **互补**能力误报成"重叠"。互补不是重复，撤回那套归一。
                base = re.sub(r"(_v\d+)+$", "", name.lower())
                buckets.setdefault(base or name, []).append((name, fn))
        for base, items in buckets.items():
            if len(items) > 1:
                names = "、".join(sorted({n for n, _f in items}))
                files = "、".join(sorted({f for _n, f in items}))
                out.append({"target": "plugins/ 自生成插件",
                            "evidence": "功能重叠 %d 个：%s（文件 %s）" % (len(items), names, files),
                            "action": "确认后把多余的移进 logs/quarantine/（本项目不删文件），"
                                      "只留最有用的那个；以后同类需求会被 forge 的重复闸门直接拦下"})
    except Exception as e:      # noqa: silent-ok — 查不出来不影响诊断
        LOG.debug("自进化：重复插件检查失败（忽略）：%s", e)
    return out


def diagnose(limit=8):
    """返回改进项列表（已排序）。每项：kind/pri/auto/target/evidence/action。"""
    items = []

    # ---- ① 评测失败/半对 ----
    last = _last_eval()
    for name in (last.get("failed") or []):
        k, act = _kind_of_eval(name)
        items.append({"kind": k, "target": "评测", "evidence": str(name)[:80], "action": act})
    for name, state, note in _md_items(_EVAL_MD, {"🟡", "❌"}):
        if any(i["evidence"].startswith(name[:12]) for i in items):
            continue
        k, act = _kind_of_eval(note or name)
        items.append({"kind": k, "target": "评测", "evidence": ("%s ｜ %s" % (name, note))[:90],
                      "action": act})

    # ---- ② 能力体检红点 ----
    for name, state, note in _md_items(_HEALTH_MD, {"fail", "broken"}):
        items.append({"kind": "tool_bug", "target": name,
                      "evidence": note[:80] or "体检判为失败",
                      "action": "先运行 `python tools/health_capability.py --only %s` 复现，"
                                "再按报错原文修工具本体" % name})
    for name, state, note in _md_items(_HEALTH_MD, {"需参数"}):
        items.append({"kind": "health_param", "target": name, "evidence": note[:80],
                      "action": "给它写一条沙箱用例（真实前置条件 + 独立校验），"
                                "别再用通用默认参数去猜"})
    for name, state, note in _md_items(_HEALTH_MD, {"需条件"}):
        items.append({"kind": "env", "target": name, "evidence": note[:80],
                      "action": "写清依赖怎么起（配置项或启动脚本），或在体检里明确标成"})
    for name, state, note in _md_items(_HEALTH_MD, {"未实测"}):
        items.append({"kind": "health_untested", "target": name, "evidence": note[:80],
                      "action": "能沙箱化的就补用例；确实不能（会弹窗/要人回答/占显存）就在说明里写明代价"})

    # ---- ③ 经验库里的"反复失败"→ 缺能力或链条不稳 ----
    try:
        from core import experience as EXP
        rows = EXP.lessons("forge_fail", limit=5)
        if rows:
            items.append({"kind": "capability", "target": "能力自增长",
                          "evidence": "最近 %d 条失败：%s" % (len(rows), str(rows[0].get("why"))[:50]),
                          "action": "把教训注入生成提示词（已接），失败样本已进经验库；"
                                    "同类需求可直接走 forge_plugin 再试一次"})
    except Exception:      # noqa: silent-ok
        pass

    # ---- ④ 文档类：文档写的和事实对不对得上 ----
    for it in _doc_checks():
        items.append({"kind": "doc", "target": it["target"],
                      "evidence": it["evidence"], "action": it["action"]})
    # ---- ⑤ 自生成插件重复（自己给自己添乱，只提示不代删）----
    for it in _dup_generated():
        items.append({"kind": "doc", "target": it["target"],
                      "evidence": it["evidence"], "action": it["action"]})

    for it in items:
        meta = _KINDS.get(it["kind"], {"pri": 9, "auto": False, "name": it["kind"]})
        it["pri"] = meta["pri"]
        it["auto"] = meta["auto"]
        it["kind_name"] = meta["name"]
    items.sort(key=lambda x: (x["pri"], x["target"]))
    return items[:limit]


def _stale_note(max_hours=24.0):
    """证据新鲜度：报告是不是很久以前跑的？久了就得先重跑，否则诊断是在拿旧账说事。

    【为什么必须提示】实测踩到：体检报告是上一轮的（里面还写着 archify_deliver「未实测」，
    而那一条早就修好并实测通过了），诊断照旧把它列成待修项 —— 拿旧账诊断，比不诊断更误导。
    """
    import time as _t
    out = []
    now = _t.time()
    for path, label, cmd in (
            (_EVAL_HIST, "评测趋势", "python tools/eval_xiaojiao.py --save"),
            (_HEALTH_MD, "能力体检", "python tools/health_capability.py --save")):
        try:
            if not os.path.isfile(path):
                out.append("%s还没有（先跑 %s）" % (label, cmd))
                continue
            age_h = (now - os.path.getmtime(path)) / 3600.0
            if age_h > max_hours:
                out.append("%s是 %.1f 小时前的（建议先重跑 %s）" % (label, age_h, cmd))
        except Exception:      # noqa: silent-ok
            continue
    return out


def report(limit=8):
    """人话版诊断报告（给工具/界面用）。"""
    items = diagnose(limit=limit)
    last = _last_eval()
    head = []
    if last:
        head.append("最近一次评测：%s%%（%s 项，通过 %s ｜ 半对 %s ｜ 失败 %s）"
                    % (last.get("score"), last.get("total"), last.get("pass"),
                       last.get("half"), last.get("fail")))
    try:
        from core import experience as EXP
        st = EXP.stats()
        if st.get("total"):
            head.append("经验库：%d 条记录，成功率 %s%%" % (st["total"], st["rate"]))
    except Exception:      # noqa: silent-ok
        pass
    stale = _stale_note()
    fresh_block = ("\n\n⚠️ **证据可能过期**：" + "；".join(stale)) if stale else ""
    if not items:
        return ("✅ **没查出该修的地方**（评测与体检都没有红点）。\n\n"
                + "\n".join(head) + fresh_block).strip()

    lines = ["🔧 **下一步该修什么（按影响面×成本排序）**", ""]
    for i, it in enumerate(items, 1):
        auto = "可自动（走 forge）" if it["auto"] else "需要人看"
        lines.append("%d. **%s** ｜ %s ｜ %s" % (i, it["kind_name"], it["target"], auto))
        lines.append("   证据：%s" % it["evidence"])
        lines.append("   动作：%s" % it["action"])
    if head:
        lines += ["", "—— " + " ｜ ".join(head)]
    if fresh_block:
        lines.append(fresh_block)
    lines += ["", "（这份清单只诊断、**不自动改源码**；唯一可自动的是「缺能力」，由 forge 带闸门落地）"]
    try:
        from core import experience as EXP
        EXP.record("evolve_find", True, why="诊断出 %d 项" % len(items),
                   lesson=str(items[0]["evidence"])[:120] if items else "")
    except Exception:      # noqa: silent-ok
        pass
    return "\n".join(lines)


def stats():
    """给自检看的结构化快照。"""
    last = _last_eval()
    items = diagnose(limit=50)
    by = {}
    for it in items:
        by[it["kind"]] = by.get(it["kind"], 0) + 1
    return {"eval": last, "findings": len(items), "by_kind": by,
            "auto_ok": sum(1 for it in items if it["auto"])}
