# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 健康系统 · 病历层（无限 8：它不生病 —— 第四步：病过就要记住）

【为什么必须有病历，而不是"治完就算了"】
    人看病最重要的产出不是这次吃的药，是**病历**：医生下次一看就知道
    "这人一到换季就犯、吃 A 药有效、吃 B 药没用"。
    小焦也一样：模型退化会**反复**发生，而且往往有规律 ——
    同一个火种、同一种上下文长度、同一类任务，就容易反复犯同一种病。
    没有病历，每次退化都是"第一次发生"，系统永远不会变聪明；
    有了病历，才能回答三个真正重要的问题：
      ① 主要病症是什么？（复读？乱码？答非所问？）
      ② 哪种治法管用？（重试有效？还是必须清上下文／换火种？）
      ③ 最近是在变好还是变坏？（trend）
    去掉它会怎样：同一个坑一遍遍踩，用户只会感觉"这软件越来越不行"。

【为什么是 append-only 的 JSONL，而不是一个会重写的大 JSON】
    · 病历是"一条一条发生"的，追加不用重写整个文件；
    · 大 JSON 重写有"写一半被 kill"的风险，一次就把**全部**历史毁掉；
    · JSONL 被写坏的最坏情况只是**最后一行**半截，跳过它就行（read_jsonl 会跳）。
    为什么"跳过坏行"这件事必须做：日志是边写边读的，正好在写的时候读到，
    最后一行天然就是半截 JSON。去掉容忍 = 一行半截 JSON 毁掉整部病历。

【字段为什么这么定（既要给人看，也要给机器算）】
    ts / iso_time   给机器排序、给人看时间
    symptom / group 给机器统计分布、给预防建议定位到"哪一组器官"
    severity        给机器算"重病比例"
    trigger         给**人**看"它是在什么条件下犯的"（这一条最值钱：复发的规律在这）
    action/result/ok 给机器算"哪种治法管用"（heal_rate 就是它算出来的）
    context         快照：轮数/模型/问题前 80 字/输出前 200 字/资源
                    —— 为什么只留前 80/200 字：病历是用来找规律的，不是备份对话的；
                    全存下来会把病历变成第二个会话库，还会把用户的隐私翻倍存一遍。
"""
import datetime
import json
import os
import time

from . import append_jsonl, health_dir, read_jsonl

DEFAULT_PATH = os.path.join(health_dir(), "records.jsonl")

# context 快照的字符上限（见文件头："病历是找规律的，不是备份对话的"）
_Q_CHARS = 80
_A_CHARS = 200
# trend 的判定门槛：前后半段次数差 >30% 才算变化（低于此都叫"平稳"）。
# 为什么要有门槛：病原本就是零星发生的，差 1~2 次纯属噪声，
# 天天报"恶化"会让这个报告失去可信度。
_TREND_DIFF = 0.30
# 样本太少时不谈趋势：3 条记录算"前半段后半段"，结论必然是随机的
_TREND_MIN = 4


def _iso(ts):
    try:
        return datetime.datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:      # noqa: silent-ok — 时间格式化失败就用空串，不影响主字段
        return ""


def _day_of(ts):
    try:
        return datetime.datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d")
    except Exception:      # noqa: silent-ok — 同上
        return "?"


def _short(v, n):
    """把任意值压成不超过 n 字的字符串（病历里的快照字段都要过这一道）。"""
    if v is None:
        return ""
    try:
        s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)
    except Exception:      # noqa: silent-ok — 序列化不了就用 repr，绝不让写病历失败
        s = repr(v)
    s = s.replace("\n", " ")
    return s if len(s) <= n else s[:n]


def _jsonable(v, depth=0):
    """把 context 洗成一定能落盘的 JSON（非 JSON 类型转成字符串）。

    为什么必须洗：context 是**别的模块**拼来的 dict，里面可能有对象、set、
    numpy 数字。json.dumps 一遇到它们就抛，而抛的后果是"这条病历丢了"——
    恰恰是出问题的时候最需要它。所以宁可有损（转成 repr），也不能丢。
    去掉它：一次 context 里塞了个对象 → 这条病历静默消失。
    """
    if depth > 3:
        return _short(v, 200)
    if v is None or isinstance(v, (bool, int, float, str)):
        if isinstance(v, str) and len(v) > 500:
            return v[:_A_CHARS] + "…"
        return v
    if isinstance(v, dict):
        out = {}
        for k, val in list(v.items())[:40]:
            try:
                out[str(k)] = _jsonable(val, depth + 1)
            except Exception:      # noqa: silent-ok — 单个键坏了就跳过它
                continue
        return out
    if isinstance(v, (list, tuple, set)):
        return [_jsonable(x, depth + 1) for x in list(v)[:40]]
    return _short(v, 200)


class HealthRecords:
    """病历本：`log()` 记一条，`read()/analyze()` 读回来算规律。

    为什么要一个类而不是几个函数：路径（`path`）是要能替换的 ——
    自测用临时文件、生产用 `logs/health/records.jsonl`，绝不能让自测
    往真病历里灌 5 条假记录（那会把用户的 trend 和预防建议算歪）。
    函数式写法就只能靠全局变量改路径，多进程/多实例立刻串味。
    """

    def __init__(self, path=None, monitor=None):
        self.path = path or DEFAULT_PATH
        self.monitor = monitor

    # ---------- 元信息 ----------
    def _group_of(self, codes):
        """症状 → 组（语言/逻辑/情绪/行为/生理）。拿不到登记表就填 "unknown"。"""
        groups = []
        table = None
        try:
            table = getattr(self.monitor, "SYMPTOMS", None) if self.monitor is not None else None
            if not table:
                from . import monitor as _m
                table = _m.SYMPTOMS
        except Exception:      # noqa: silent-ok — 拿不到登记表不影响记病历
            table = None
        for c in codes:
            g = "unknown"
            try:
                if table and table.get(c):
                    g = str(table[c][0])
            except Exception:      # noqa: silent-ok — 单个症状查不到就用 unknown
                g = "unknown"
            if g not in groups:
                groups.append(g)
        return ",".join(groups) if groups else "unknown"

    @staticmethod
    def _codes(symptom):
        """symptom 可以是单代码 / 列表 / Symptom 对象 / dict，统一成 list[str]。"""
        out = []
        if symptom is None:
            return out
        items = symptom if isinstance(symptom, (list, tuple, set)) else [symptom]
        for s in items:
            code = ""
            try:
                if isinstance(s, str):
                    code = s
                elif isinstance(s, dict):
                    code = s.get("code") or s.get("symptom") or ""
                else:
                    code = getattr(s, "code", "") or ""
            except Exception:      # noqa: silent-ok — 读不出来就跳过这一条
                code = ""
            code = str(code).strip()
            if code and code not in out:
                out.append(code)
        return out

    @staticmethod
    def _result_of(result, context):
        """把"治疗结果"归一成 (人话, ok)。

        为什么要容错这么多种形态：治疗层给的是 HealResult 对象、离线回放给的是
        dict、手写补录用的是 bool 或字符串。只认一种，另外两种调用方就写不进病历，
        而写不进病历等于这次治疗白做（学不到东西）。
        """
        ctx = context if isinstance(context, dict) else {}
        try:
            if isinstance(result, bool):
                return ("治疗成功" if result else "治疗未生效"), result
            if isinstance(result, str):
                s = result.strip()
                # 字符串没带 ok 时的判定：**"未治疗/只记录"必须算失败**。
                # 为什么较这个真：heal_rate 是病历里唯一的"治法有没有用"指标，
                # 而治疗层最危险的失效模式是"报告说治了、其实没动手"。
                # 把"未治疗"默认记成成功，会让治愈率虚高，恰好把这个失效模式盖住。
                if "ok" in ctx:
                    ok = bool(ctx.get("ok"))
                else:
                    ok = bool(s) and ("未治疗" not in s) and ("没治" not in s)
                return (s or "未治疗（仅记录）"), ok
            if isinstance(result, dict):
                note = result.get("note") or result.get("detail") or result.get("result")
                ok = bool(result.get("ok", ctx.get("ok", True)))
                if note is None:
                    note = "治疗成功" if ok else "治疗未生效"
                return _short(note, 300), ok
            if result is None:
                return "未治疗（仅记录）", bool(ctx.get("ok", False))
            note = getattr(result, "note", "") or getattr(result, "action", "")
            ok = bool(getattr(result, "ok", True))
            return _short(note or ("治疗成功" if ok else "治疗未生效"), 300), ok
        except Exception:      # noqa: silent-ok — 归一失败也不能丢这条病历
            return _short(result, 200) or "治疗结果未知", False

    def _trigger_of(self, codes, severity, context):
        """触发条件：优先用调用方给的，否则按症状+连续轮数拼一句人话。"""
        ctx = context if isinstance(context, dict) else {}
        for k in ("trigger", "reason", "detail"):
            v = ctx.get(k)
            if isinstance(v, str) and v.strip():
                return _short(v, 300)
        parts = []
        for c in codes:
            st = ""
            try:
                st = ctx.get("streak", {}).get(c) if isinstance(ctx.get("streak"), dict) else None
            except Exception:      # noqa: silent-ok — streak 读不到就不写轮数
                st = None
            parts.append("%s%s" % (c, ("（连续 %s 轮）" % st) if st else ""))
        turns = ctx.get("turns")
        where = ("第 %s 轮" % turns) if turns not in (None, "") else "本轮"
        return _short("%s 检出 %s，severity=%s" % (where, "、".join(parts) or "未知症状", severity), 300)

    def _snapshot(self, context):
        """上下文快照：只留"找规律用得上"的字段（轮数/模型/问题前 80 字/输出前 200 字/资源）。

        为什么值为 None 的键要**丢掉**而不是留着：调用方常常把一整排键都传进来
        （`{"turns": None, "model": None, ...}`），留下来就会让病历里塞满
        `"model": null`。等到统计"哪个模型最容易退化"时，一半记录是 null，
        这份病历就没法用了。丢掉 None = 让"有数据的记录"自带完整信息。
        """
        ctx = context if isinstance(context, dict) else {}
        snap = {}
        for k in ("turns", "model", "brain", "session", "sid", "where", "level", "cause"):
            if ctx.get(k) is not None:
                snap[k] = _jsonable(ctx.get(k))
        q = ctx.get("question") if ctx.get("question") is not None else ctx.get("user_input")
        if q:
            snap["question"] = _short(q, _Q_CHARS)
        out = ctx.get("output") if ctx.get("output") is not None else ctx.get("answer")
        if out:
            snap["output_head"] = _short(out, _A_CHARS)
        res = {}
        for k in ("elapsed_ms", "vram_used_pct", "vram_total_mb", "mem_growth_pct", "timeout_ms"):
            if ctx.get(k) is not None:
                res[k] = _jsonable(ctx.get(k))
        if res:
            snap["resource"] = res
        if ctx.get("extra") is not None:
            snap["extra"] = _jsonable(ctx.get("extra"))
        return snap

    # ---------- 写 ----------
    def log(self, symptom, severity, action, result, context=None):
        """记一条病历，返回这条记录（dict）。**绝不抛异常**，失败也返回 dict（ok=False）。

        为什么失败也要返回一条记录：调用方（治疗层）拿到的东西要能直接塞进
        HealResult.detail 或报告里；返回 None 会逼着每个调用点写 if 判断，
        早晚有人漏了 → 在治疗路径上抛 AttributeError。给个"没落盘"的记录最省事。
        """
        codes = self._codes(symptom)
        ctx = context if isinstance(context, dict) else {}
        try:
            text, ok = self._result_of(result, ctx)
            ts = time.time()
            row = {
                "ts": ts,
                "iso_time": _iso(ts),
                "symptom": codes if len(codes) > 1 else (codes[0] if codes else ""),
                "codes": codes,
                "group": self._group_of(codes),
                "severity": str(severity or "LIGHT"),
                "trigger": self._trigger_of(codes, severity, ctx),
                "action": _short(action if action is not None else "none", 120),
                "result": text,
                "ok": bool(ok),
                "context": self._snapshot(ctx),
                "day": _day_of(ts),
            }
            written = append_jsonl(self.path, row)
            row["written"] = bool(written)
            return row
        except Exception as e:      # noqa: silent-ok — 病历写不上绝不能影响对话
            return {"ts": time.time(), "iso_time": _iso(time.time()), "symptom": codes,
                    "codes": codes, "group": "unknown", "severity": str(severity or "LIGHT"),
                    "trigger": "", "action": _short(action, 120), "result": _short(result, 200),
                    "ok": False, "context": {}, "written": False, "error": repr(e)}

    # ---------- 读 ----------
    def read(self, days=7):
        """读回最近 N 天的病历（旧→新）。半截/坏行按 read_jsonl 的规则跳过。"""
        rows = read_jsonl(self.path, days=days)
        rows.sort(key=lambda r: float(r.get("ts") or 0))
        return rows

    def count(self, days=7):
        return len(self.read(days=days))

    # ---------- 分析 ----------
    def analyze(self, days=7):
        """算规律：多少、什么病、哪种治法管用、在变好还是变坏。"""
        rows = self.read(days=days)
        out = {"days": days, "total": len(rows), "by_severity": {}, "by_symptom": {},
               "by_action": {}, "heal_rate": 0.0, "top_symptoms": [], "worst_day": "",
               "trend": "平稳", "note": "", "ok_count": 0, "by_day": {}}
        if not rows:
            out["note"] = "最近 %d 天没有病历记录 —— 要么没退化，要么健康系统没接上。" % days
            return out
        days_count, ok = {}, 0
        for r in rows:
            try:
                sev = str(r.get("severity") or "?")
                out["by_severity"][sev] = out["by_severity"].get(sev, 0) + 1
                act = str(r.get("action") or "none")
                out["by_action"][act] = out["by_action"].get(act, 0) + 1
                codes = r.get("codes")
                if not isinstance(codes, (list, tuple)) or not codes:
                    codes = [r.get("symptom")] if r.get("symptom") else []
                for c in codes:
                    c = str(c)
                    if c:
                        out["by_symptom"][c] = out["by_symptom"].get(c, 0) + 1
                if r.get("ok"):
                    ok += 1
                d = str(r.get("day") or _day_of(r.get("ts") or 0))
                days_count[d] = days_count.get(d, 0) + 1
            except Exception:      # noqa: silent-ok — 单条病历脏了跳过它，不能让分析整体失败
                continue
        out["ok_count"] = ok
        out["by_day"] = days_count
        out["heal_rate"] = round(ok / float(len(rows)), 3)
        out["top_symptoms"] = sorted(out["by_symptom"].items(), key=lambda x: (-x[1], x[0]))
        out["worst_day"] = max(days_count.items(), key=lambda x: x[1])[0] if days_count else ""
        out["trend"] = self._trend(rows)
        out["note"] = ("最近 %d 天共 %d 次症状，治疗成功率 %.0f%%，趋势：%s。"
                       % (days, len(rows), out["heal_rate"] * 100, out["trend"]))
        return out

    @staticmethod
    def _trend(rows):
        """趋势：前半段 vs 后半段的次数对比（差 >30% 才算变化）。

        为什么按"时间窗对半分"而不是"按记录数对半"：按记录数对半，前半段永远
        等于后半段（各一半），趋势恒等于"平稳" —— 那这个指标就是废的。
        为什么样本 <4 条不判趋势：3 条记录分两段，结论必然是随机的；
        报一个随机趋势比不报更坏（用户会据此做决定）。
        为什么同一瞬间的记录直接判"平稳"：几条记录挤在同一秒时，"前半段"就是
        全部、"后半段"就是零，算出来必然是"好转/恶化" —— 那是时间戳精度造的假象。
        为什么分母用 max(first, second)：用 min(…, 1) 当分母时，"从 1 次变 2 次"
        也会算成 100% 恶化，把噪声放大成结论。
        """
        try:
            if len(rows) < _TREND_MIN:
                return "平稳"
            ts = [float(r.get("ts") or 0) for r in rows]
            lo, hi = min(ts), max(ts)
            if hi - lo < 1.0:          # 全在同一瞬间：没有"前后"可言
                return "平稳"
            mid = (lo + hi) / 2.0
            first = sum(1 for t in ts if t <= mid)
            second = sum(1 for t in ts if t > mid)
            if first <= 0 or second <= 0:
                return "平稳"
            diff = (second - first) / float(max(first, second))
            if diff > _TREND_DIFF:
                return "恶化"
            if -diff > _TREND_DIFF:
                return "好转"
            return "平稳"
        except Exception:      # noqa: silent-ok — 算不出来就说"平稳"（最保守，不吓人）
            return "平稳"

    # ---------- 预防建议 ----------
    def suggest_prevention(self):
        """基于病历给中文预防建议 —— **每条都必须带真实数字**。

        为什么强制带数字："多注意上下文长度"这种话没有可操作性，
        用户看完不知道该改什么。带上数字就变成了可执行的判断：
        "复读占 58%，建议把 max_tokens 从 2048 降到 1024"。
        去掉数字，这一层就退化成正确的废话 —— 而那正是大部分"智能建议"没用原因。
        """
        a = self.analyze(days=7)
        tips = []
        try:
            total = a["total"]
            if not total:
                return ["最近 7 天病历 0 条：没有退化记录，保持现状即可（下一步只需要盯住复读的偶发触发）。"]
            top = a["top_symptoms"][:3]
            if top:
                code, n = top[0]
                tips.append("最近 %d 天共 %d 次症状，最多的是「%s」%d 次（占 %.0f%%）——"
                            "它就是当前的主要病症，先治它。" % (a["days"], total, code, n, n * 100.0 / total))
            heavy = a["by_severity"].get("HEAVY", 0) + a["by_severity"].get("EMERGENCY", 0)
            if heavy:
                tips.append("其中重/急症 %d 次（占 %.0f%%，门槛：出现 1 次就值得排查资源）——"
                            "建议先看显存和上下文轮数，而不是换个问法重试。"
                            % (heavy, heavy * 100.0 / total))
            rate = a["heal_rate"]
            if rate < 0.5:
                tips.append("治疗成功率只有 %.0f%%（%d/%d 条 ok）——"
                            "说明当前的治疗动作选错了方向，建议提高一级治疗（清上下文/换火种）。"
                            % (rate * 100, a["ok_count"], total))
            else:
                tips.append("治疗成功率 %.0f%%（%d/%d 条 ok）——现有治法基本够用，保持。"
                            % (rate * 100, a["ok_count"], total))
            if a["trend"] == "恶化":
                tips.append("趋势为「恶化」（后半段比前半段多）——建议主动做一次全面自检，"
                            "并考虑把上下文轮数上限调小。")
            elif a["trend"] == "好转":
                tips.append("趋势为「好转」——说明这段时间的治法有效，可以继续。")
            if a["worst_day"]:
                tips.append("最忙的一天是 %s，当天 %d 次 —— 那天在做什么任务，值得看一眼病历里的 trigger。"
                            % (a["worst_day"], a["by_day"].get(a["worst_day"], 0)))
            rep = a["by_symptom"].get("repeat", 0)
            if rep >= 2:
                tips.append("复读出现 %d 次：建议把单次生成上限调小（max_tokens），"
                            "长文改成分段续写 —— 复读基本都是「一次吐太多」引发的。" % rep)
            res = sum(a["by_symptom"].get(c, 0) for c in ("vram_alert", "memory_growth", "timeout"))
            if res:
                tips.append("资源类症状共 %d 次：先腾显存/查内存增长，"
                            "这类问题重试一百次也不会好。" % res)
        except Exception:      # noqa: silent-ok — 建议算不出来也不能让调用方崩
            pass
        if not tips:
            tips = ["最近 %d 天 %d 次症状，没有发现值得提前干预的规律。" % (a["days"], a["total"])]
        return tips

    def weekly_report(self, days=7):
        """中文可读周报（给界面/日志/用户看）。"""
        a = self.analyze(days=days)
        lines = ["小焦健康周报（最近 %d 天）" % days, "=" * 34]
        lines.append("症状总数：%d 次；治疗成功率：%.0f%%（%d/%d）"
                     % (a["total"], a["heal_rate"] * 100, a["ok_count"], a["total"]))
        if a["by_severity"]:
            lines.append("严重度分布：" + "、".join("%s %d" % (k, v)
                                                for k, v in sorted(a["by_severity"].items())))
        if a["top_symptoms"]:
            lines.append("高频症状：" + "、".join("%s×%d" % (k, v) for k, v in a["top_symptoms"][:5]))
        if a["by_action"]:
            lines.append("治疗动作：" + "、".join("%s×%d" % (k, v)
                                              for k, v in sorted(a["by_action"].items(), key=lambda x: -x[1])[:5]))
        lines.append("趋势：%s；最忙的一天：%s" % (a["trend"], a["worst_day"] or "—"))
        lines.append("")
        lines.append("【预防建议】")
        for i, t in enumerate(self.suggest_prevention(), 1):
            lines.append("  %d. %s" % (i, t))
        lines.append("")
        lines.append("（数据来源：%s；病历只留问题前 %d 字/回答前 %d 字，不留全文）"
                     % (self.path, _Q_CHARS, _A_CHARS))
        return "\n".join(lines)


def log(symptom, severity, action, result, context=None, path=None):
    """便捷入口：用默认病历本记一条（不需要自己 new 对象时用）。"""
    return HealthRecords(path=path).log(symptom, severity, action, result, context)


__all__ = ["HealthRecords", "log", "DEFAULT_PATH"]
