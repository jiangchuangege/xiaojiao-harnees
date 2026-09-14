# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 健康系统 · 诊断层（无限 8：它不生病 —— 第二步：判断病得多重、病在哪）

【为什么监测之后必须先"诊断"，不能直接治】
    监测给出的是一堆症状（"复读 + 语速突变 + 显存告警"），治疗需要的是**决策**：
    要不要管？管到什么程度？是模型的错还是上下文的错？
    没有这一层，只有两种粗暴做法：
      · 一律重试 → 偶发口误也被重试，白烧算力，还容易把好回答推倒；
      · 一律不动 → 复读滚成几千字，用户自己发现。
    诊断层就是把"一堆症状"压成一个可执行的判断：**四级 + 四因**。

【四级（严重度）】
    LIGHT      单次轻症          → 自动、用户无感（截断/规整）
    MEDIUM     同一症状连续 3 次 / 同一轮 ≥3 个症状 → 自动 + 界面提示
    HEAVY      持续 + 资源告警，或 heavy 级症状连续 ≥2 → 半自动，等用户确认
    EMERGENCY  乱码/拒绝连续 ≥3、显存告警+超时同时出现、安全类症状 → 全自动停机+保现场
    为什么"持续"比"严重"权重更高：一次乱码可能是采样偶然，连着三轮乱码说明
    这个火种在当前上下文下**已经不稳**，再喂只会越喂越坏。级别必须反映
    "会不会自己好"，而不是"这一条症状听起来吓不吓人"。
    去掉"连续"这个维度：偶发和顽疾一个待遇 —— 要么疯狂误治，要么放着烂掉。

【四因（病因）】
    resource  显存/内存/超时 → 载体资源问题，治模型没用，得先腾资源
    context   轮数太多 / 输入太长 且症状集中在答非所问、自相矛盾
              → 上下文把注意力稀释了，清一次上下文就能好
    logic     症状集中在跑题/跳步/事实反转/自相矛盾 → 推理链断了
    model     其余（复读/乱码/情绪/工具）→ 火种本身不稳，该降级或换火种
    为什么必须先判因再治：**同一个症状，不同的因，治法完全相反**。
    "答非所问"若是上下文太长引起的，重试一百次也没用（清上下文才有用）；
    若是火种本身不行，清上下文也没用（换火种才有用）。
    去掉判因、只按严重度治：等于所有病都吃同一种药。

【为什么本层绝不抛异常、且 session 缺字段全用默认】
    它跑在对话热路径上，输入是"别的模块拼出来的 dict"——缺键、类型不对都很正常。
    诊断层为了一个可选字段崩掉，用户看到的是"出错了"，而真实情况只是
    "这次没法判断病得多重"。所以：**永远给出一个判断**，缺信息就用默认值（宁可判轻）。
"""
import time

SEVERITY = ("LIGHT", "MEDIUM", "HEAVY", "EMERGENCY")
LEVEL_NUM = {"LIGHT": 1, "MEDIUM": 2, "HEAVY": 3, "EMERGENCY": 4}

# 资源类症状：出现它们，"病因"就优先归到资源上（资源不够是**因**，文本症状是果）
RESOURCE_CODES = ("vram_alert", "memory_growth", "timeout")
# 逻辑类症状：判断"是推理链的问题，还是上下文太长的问题"
LOGIC_CODES = ("off_topic", "logic_gap", "fact_reversal", "self_contradiction")
CONTEXT_CODES = ("off_topic", "self_contradiction")
# 安全类症状：不在 18 类登记表里（它们来自别的安全层），但一旦出现就是急诊级 ——
# 宁可让这一层认几个"外来的"急诊信号，也不能让它把安全问题当成普通退化慢慢治。
SAFETY_CODES = ("harmful_content", "dangerous_instruction", "self_harm",
                "illegal_advice", "safety", "unsafe")
# 无法恢复的组合：显存告警 + 超时同时出现 —— 不是"文本说错话"，是机器已经扛不住了，
# 继续生成只会更糟（还可能把显存耗干影响整机）。这一条必须直接进急诊。
FATAL_PAIRS = (("vram_alert", "timeout"),)

# 默认的"危险症状"严重度表（拿不到 monitor 的登记表时兜底，保证本层能独立工作）
_FALLBACK_LEVEL = {
    "repeat": "medium", "garbled": "heavy", "broken_sentence": "light", "pace_shift": "light",
    "self_contradiction": "medium", "off_topic": "medium", "logic_gap": "light",
    "fact_reversal": "medium", "sudden_anger": "medium", "sudden_negativity": "medium",
    "emotion_swing": "light", "tool_misuse": "heavy", "tool_skipped": "medium",
    "refusal": "heavy", "infinite_loop": "heavy", "timeout": "medium",
    "vram_alert": "heavy", "memory_growth": "medium",
}
_FALLBACK_CN = {
    "repeat": "复读", "garbled": "乱码", "broken_sentence": "断句", "pace_shift": "语速突变",
    "self_contradiction": "自相矛盾", "off_topic": "答非所问", "logic_gap": "逻辑跳步",
    "fact_reversal": "事实反转", "sudden_anger": "突然暴躁", "sudden_negativity": "突然消极",
    "emotion_swing": "情绪失控", "tool_misuse": "工具乱调", "tool_skipped": "工具不调",
    "refusal": "拒绝服务", "infinite_loop": "无限循环", "timeout": "响应超时",
    "vram_alert": "显存告警", "memory_growth": "内存增长",
}


def _codes_of(symptoms):
    """把任意形态的"症状输入"归一成 list[str]。

    为什么要容错到这种程度：诊断层会被三种调用方用到 ——
      · 监测层直接给 list[Symptom]；
      · 病历回放给 list[dict]（从 JSONL 读回来的）；
      · 手写规则/测试给 list[str] 甚至单个 str / None。
    只认一种形态的后果是"另一个调用方一进来就崩"。归一化放在入口一处，后面就干净了。
    """
    out = []
    if symptoms is None:
        return out
    if isinstance(symptoms, (str, bytes)):
        symptoms = [symptoms]
    if isinstance(symptoms, dict):
        symptoms = [symptoms]
    if not isinstance(symptoms, (list, tuple, set)):
        symptoms = [symptoms]
    for s in symptoms:
        code = ""
        try:
            if isinstance(s, str):
                code = s
            elif isinstance(s, dict):
                code = s.get("code") or s.get("symptom") or ""
                if isinstance(code, (list, tuple)):
                    out.extend(str(x) for x in code if x)
                    continue
            else:
                code = getattr(s, "code", "") or ""
        except Exception:      # noqa: silent-ok — 单条读不出来就跳过，不能让整轮诊断失败
            code = ""
        code = str(code).strip()
        if code and code not in out:
            out.append(code)
    return out


def _streak_in(symptoms, code):
    """从症状自带的 evidence 里取 streak（监测层会盖进来）。"""
    best = 0
    for s in (symptoms or []):
        try:
            if isinstance(s, dict):
                if (s.get("code") or "") != code:
                    continue
                ev = s.get("evidence") or {}
            else:
                if getattr(s, "code", "") != code:
                    continue
                ev = getattr(s, "evidence", {}) or {}
            v = int(ev.get("streak") or 0)
            best = max(best, v)
        except Exception:      # noqa: silent-ok — 证据读不出来就退回别的来源
            continue
    return best


class HealthDiagnose:
    """把 symptoms 压成 {severity, cause, codes, reason, advice, streak}。

    为什么把"判级"和"判因"分成两个方法：它们的数据来源不同 ——
    判级只看症状本身（多重、多久），判因要看会话（多少轮、多长输入、什么模型）。
    混在一起写的结果是"想单独用判因（比如只想知道该不该清上下文）时，
    被迫伪造一堆症状"。分开后两件事都能单独调用、单独测试。
    """

    def __init__(self, monitor=None, session=None, cfg=None):
        self.monitor = monitor
        self.session = session if isinstance(session, dict) else {}
        self.cfg = cfg if isinstance(cfg, dict) else {}
        # 阈值（可被 cfg 覆盖）：轮数、输入长度、集中度
        self.turns_heavy = int(self.cfg.get("turns_heavy", 40))
        self.input_chars_heavy = int(self.cfg.get("input_chars_heavy", 4000))
        self.concentrate = float(self.cfg.get("concentrate", 0.5))

    # ---------- 工具 ----------
    def _level_of(self, code):
        """某症状的默认严重度：优先问监测层的登记表（唯一真相），拿不到用兜底表。"""
        try:
            table = getattr(self.monitor, "SYMPTOMS", None) if self.monitor is not None else None
            if not table:
                from . import monitor as _m
                table = _m.SYMPTOMS
            row = table.get(code)
            if row:
                return str(row[2])
        except Exception:      # noqa: silent-ok — 拿不到登记表就用兜底表，绝不抛
            pass
        return _FALLBACK_LEVEL.get(code, "light")

    def _cn(self, code):
        try:
            from . import monitor as _m
            row = _m.SYMPTOMS.get(code)
            if row:
                return str(row[1])
        except Exception:      # noqa: silent-ok — 同上
            pass
        return _FALLBACK_CN.get(code, code)

    def _monitor_streak(self, code):
        """从挂上来的监测器取连续轮数（诊断层可以直接拿监测器，省去手工拼 session）。"""
        try:
            if self.monitor is not None:
                return int(self.monitor.streak(code))
        except Exception:      # noqa: silent-ok — 取不到就退回别的来源
            pass
        return 0

    def _streaks(self, codes, symptoms, session):
        """算出每个症状的"连续轮数"（三个来源，取最大，缺了绝不抛）。

        三个来源为什么都要：
          ① 症状自带的 evidence["streak"]（监测层刚盖的，最准）；
          ② session["streak"]（调用方自己数的，离线回放/其它宿主用）；
          ③ session["history"]（**本轮之前**的轮次序列，末轮往回数连续几轮有它）。
        history 的约定必须写清楚：**不含本轮**；本轮含该症状就 +1。
        去掉"取最大"而只认一个来源：从病历回放历史时永远判不出"持续"，
        于是所有离线诊断都是 LIGHT —— 学习层就学不到任何东西。
        """
        out = {}
        hist = session.get("history") if isinstance(session, dict) else None
        s_streak = session.get("streak") if isinstance(session, dict) else None
        for code in codes:
            v = _streak_in(symptoms, code)
            if isinstance(s_streak, dict):
                try:
                    v = max(v, int(s_streak.get(code) or 0))
                except Exception:      # noqa: silent-ok — 值写坏了忽略这一路
                    pass
            if isinstance(hist, (list, tuple)) and hist:
                run = 0
                for round_codes in reversed(hist):
                    got = self._round_has(round_codes, code)
                    if got is None:        # 认不出的轮次格式：停止回溯，不猜
                        break
                    if not got:
                        break
                    run += 1
                v = max(v, run + 1)        # 本轮也算一轮
            out[code] = max(1, int(v))
        return out

    @staticmethod
    def _round_has(round_codes, code):
        """某一轮里有没有这个症状；格式认不出来返回 None（让调用方停止回溯）。"""
        try:
            if isinstance(round_codes, str):
                return round_codes == code
            if isinstance(round_codes, dict):
                inner = round_codes.get("codes", round_codes.get("symptoms", round_codes.get("signs")))
                if inner is None:
                    return None
                return HealthDiagnose._round_has(inner, code)
            if isinstance(round_codes, (list, tuple, set)):
                for x in round_codes:
                    if isinstance(x, (dict,)) and (x.get("code") or "") == code:
                        return True
                    if isinstance(x, str) and x == code:
                        return True
                return False
        except Exception:      # noqa: silent-ok — 认不出来就当未知
            return None
        return None

    # ---------- 判级 ----------
    def diagnose(self, symptoms, session=None):
        """给出一份完整诊断。**永不抛异常**，最差也会返回 LIGHT/model。"""
        s = session if isinstance(session, dict) else (self.session if isinstance(self.session, dict) else {})
        try:
            codes = _codes_of(symptoms)
        except Exception:      # noqa: silent-ok — 连症状都读不出来时按"没病"处理
            codes = []
        try:
            streaks = self._streaks(codes, symptoms, s)
            severity = self._grade(codes, streaks, s)
            cause = self.classify_cause(symptoms, s)
            reason = self._reason(severity, cause, codes, streaks, s)
            advice = self._advice(severity, cause)
        except Exception as e:      # noqa: silent-ok — 诊断层自己出问题时退回"最保守的判断"
            return {"severity": "LIGHT", "cause": "model", "codes": codes,
                    "reason": "诊断层内部异常（%r），按最保守处理：不干预，只记病历。" % (e,),
                    "advice": "继续回答；这条异常已记进病历，下次体检会带上。",
                    "streak": {}, "ok": False}
        return {"severity": severity, "cause": cause, "codes": codes,
                "reason": reason, "advice": advice, "streak": streaks,
                "level": LEVEL_NUM.get(severity, 1), "ok": True, "ts": time.time()}

    def _grade(self, codes, streaks, session):
        """四级判定（顺序即优先级：先看会不会立刻烂掉，再看持不持续，最后看数量）。"""
        code_set = set(codes)
        res = [c for c in codes if c in RESOURCE_CODES]
        # ① 急：安全类症状 / 乱码·拒绝连续 ≥3 / 无法恢复的组合
        if code_set & set(SAFETY_CODES):
            return "EMERGENCY"
        for c in ("garbled", "refusal"):
            if c in code_set and streaks.get(c, 1) >= 3:
                return "EMERGENCY"
        for a, b in FATAL_PAIRS:
            if a in code_set and b in code_set:
                return "EMERGENCY"
        # ② 重：症状持续（≥3 轮）**且**同时有资源告警 —— 病在持续 + 机器也撑不住
        if res and any(streaks.get(c, 1) >= 3 for c in codes):
            return "HEAVY"
        # ③ 重：heavy 级症状连续 ≥2（一次可以算偶然，连着两次就不是了）
        for c in codes:
            if self._level_of(c) == "heavy" and streaks.get(c, 1) >= 2:
                return "HEAVY"
        # ④ 中：同一症状连续 3 次，或同一轮 ≥3 个症状（多点开花说明整体状态不对）
        if any(streaks.get(c, 1) >= 3 for c in codes):
            return "MEDIUM"
        if len(codes) >= 3:
            return "MEDIUM"
        # ⑤ 其余：单次轻症（**只记病历，不干预**）
        # 注意：单独一次 heavy 级症状（比如一次"拒绝服务"）也落在这里 ——
        # 因为"拒绝"可能是模型对一个请求的合理回应，要看到它**连续**才算病。
        return "LIGHT"

    # ---------- 判因 ----------
    def classify_cause(self, symptoms, session=None):
        """病因：resource / context / logic / model（缺信息时按 model 处理，最保守）。"""
        s = session if isinstance(session, dict) else (self.session if isinstance(self.session, dict) else {})
        try:
            codes = _codes_of(symptoms)
            if not codes:
                return "model"
            # ① 资源：只要沾了显存/内存/超时，病因就先归资源 ——
            #    因为资源不够是**因**，文本上的怪象是果；去治果是白费力气。
            if any(c in RESOURCE_CODES for c in codes):
                return "resource"
            n = float(len(codes))
            ctx_hit = sum(1 for c in codes if c in CONTEXT_CODES) / n
            log_hit = sum(1 for c in codes if c in LOGIC_CODES) / n
            turns = self._num(s.get("turns"), 0)
            chars = self._num(s.get("input_chars"), 0)
            long_ctx = (turns > self.turns_heavy) or (chars > self.input_chars_heavy)
            # ② 上下文：**必须同时**有"上下文确实很长"的证据，否则不应把锅甩给上下文
            #    ——否则每次答非所问都会被判成"清一下上下文就好"，而真相可能是火种不行。
            if long_ctx and ctx_hit >= self.concentrate:
                return "context"
            # ③ 逻辑：症状集中在推理链上
            if log_hit >= self.concentrate:
                return "logic"
            # ④ 其余：复读/乱码/情绪/工具 → 火种本身不稳
            return "model"
        except Exception:      # noqa: silent-ok — 判因失败就按 model（最保守：不动上下文）
            return "model"

    @staticmethod
    def _num(v, default=0):
        try:
            return float(v)
        except Exception:      # noqa: silent-ok — 不是数字就用默认值
            return float(default)

    # ---------- 人话 ----------
    def _reason(self, severity, cause, codes, streaks, session):
        """一句中文原因（要能直接给用户看，也必须说清"凭什么这么判"）。"""
        names = "、".join("%s×%d" % (self._cn(c), streaks.get(c, 1)) for c in codes[:4]) or "无明显症状"
        if cause == "resource":
            core = "载体资源吃紧（%s），模型算不准了" % "、".join(
                self._cn(c) for c in codes if c in RESOURCE_CODES)
        elif cause == "context":
            core = "上下文太长（%d 轮对话 / %d 字输入），模型的注意力被稀释了" % (
                int(self._num(session.get("turns"), 0)), int(self._num(session.get("input_chars"), 0)))
        elif cause == "logic":
            core = "推理链条断了，症状集中在逻辑类"
        else:
            core = "火种（模型）在当前上下文长度下开始不稳定"
        return "本轮判为 %s：%s；依据：%s。" % (severity, core, names)

    def _advice(self, severity, cause):
        """一句中文建议（给用户看，也给治疗层当"该做什么"的粗指针）。"""
        base = {
            "LIGHT": "继续回答即可，这次症状已记进病历；同一症状再出现就要干预。",
            "MEDIUM": "已自动重试并清理本轮上下文；若再次出现，换个更简单的问法会更稳。",
            "HEAVY": "建议切到备用火种并让当前任务暂停，稍后再继续（半自动：等你确认）。",
            "EMERGENCY": "已停止生成并保留现场；请检查显存/内存后重启，再让小火种接手。",
        }.get(severity, "继续观察。")
        extra = {
            "resource": "先腾资源（关掉别的吃显存程序）比反复重试更有效。",
            "context": "清一次当前会话上下文（长期记忆会保留）通常立刻见效。",
            "logic": "把任务拆小、一次只问一件事，比让它一口气想完更稳。",
            "model": "同一个火种反复犯同样的病，说明它不适合这个任务，考虑换火种。",
        }.get(cause, "")
        return (base + extra) if extra else base


def diagnose(symptoms, session=None, monitor=None, **kw):
    """便捷入口：一次性诊断（不带状态）。"""
    return HealthDiagnose(monitor=monitor, cfg=kw or None).diagnose(symptoms, session)


__all__ = ["HealthDiagnose", "diagnose", "SEVERITY", "LEVEL_NUM",
           "RESOURCE_CODES", "LOGIC_CODES", "SAFETY_CODES"]
