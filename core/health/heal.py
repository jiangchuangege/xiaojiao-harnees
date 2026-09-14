# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 健康系统 · 治疗层（无限 8：它不生病 —— 第三步：治，而且分级治）

【为什么治疗必须分四级，而不是"出问题就重试"】
    因为**干预的代价不同**，而代价必须匹配病情：
      一级（轻）截断/规整/重做一次   代价：几乎为零，用户察觉不到 → 自动做
      二级（中）清上下文 + 重置模型状态 + 简化问题重问
                                    代价：这轮的上下文没了（长期记忆还在）→ 自动做 + 告诉用户
      三级（重）切备用火种 + 回滚会话 + 暂停任务
                                    代价：**用户可能正在等一个答案**，切走火种等于换了个"人"
                                    → 只切一次、不自动重试，并出报告等用户确认
      四级（急）停机 + 保留现场 + 强通知
                                    代价：服务停了 → 立即执行，不商量（继续生成只会更糟）
    所以分级不是"礼貌"，是**代价-收益的工程判断**。
    去掉分级、全部自动治疗会怎样：一次偶发乱码就把用户的上下文清空、火种切走 ——
    用户会觉得"这软件自己乱动我的东西"，比模型退化更不可接受。

【为什么每一级都必须是**真实动作**，不能只返回一句话】
    返回"已治疗"却什么都没做，是这一层最危险的失败模式：诊断/病历会记下
    "治疗成功"，于是病历开始骗人 —— 后续所有"哪种治法管用"的统计全成了噪声，
    而用户那边问题照旧。所以每一级都落到一个**可验证的副作用**上：
    文本真的变短了、会话真的被清了、请求真的写下来了、快照文件真的存在。
    拿不到能力时（比如没有 app、没有快照），宁可如实返回 ok=False，
    也绝不假装成功 —— 这就"绝不撒谎"的具体含义。

【为什么用**回调注入**（hooks）而不是直接 import app】
    这一层要调的全是"app 才有的能力"：重试要调模型、清上下文要动会话文件、
    切火种要改配置。直接 import 的后果有两个：
      ① 健康系统就和 Flask 应用焊死，单独跑自测/嵌到别的宿主就 import 失败；
      ② 单测没法验"到底调没调那个动作"。
    改成 hooks 注入后：生产由 app 注入真实实现，自测注入"记账用的假函数"，
    两条路都是同一份治疗逻辑。缺哪个 hook 就用本文件的安全默认实现，**绝不抛错**。

【为什么会有"隔离机制"】
    有的会话会**反复**退化（比如用户一直在问超出这个火种能力的问题）。
    对这种会话继续一级一级地治，等于每轮都在烧算力重试。
    隔离（≥3 次中/重症）后只做简单任务（`simplify()` 把问题压短），
    是"承认这个会话该降级跑"，而不是放弃它 —— 用户还能用，只是不再硬碰硬。
"""
import inspect
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from . import degeneration as D
from . import cfg as _health_cfg
from . import append_jsonl, app_module, health_dir, log_line, read_json, write_json
from .diagnose import LEVEL_NUM, SEVERITY, HealthDiagnose
from .records import HealthRecords

_ISO_PATH = os.path.join(health_dir(), "isolated.json")
_STATE_PATH = os.path.join(health_dir(), "preventive_state.json")
_PAUSE_PATH = os.path.join(health_dir(), "paused.json")
_SHUTDOWN_PATH = os.path.join(health_dir(), "shutdown_request.json")
_SWITCH_PATH = os.path.join(health_dir(), "switch_request.json")
_NOTIFY_PATH = os.path.join(health_dir(), "notify.jsonl")

# 二级"降级问法"要摘掉的修饰语：它们不承载信息，只让问题变长。
# 为什么值得专门做这件事：小模型在长问题上的退化率明显更高，
# 而用户的提问里有一半字数都是"能不能帮我尽量详细地…"这种客套。
_DECOR = ("请帮我", "帮我", "麻烦你", "麻烦", "能不能", "可以不可以", "可不可以", "能否",
          "请你", "请", "我想要", "我想", "我要", "我希望", "我希望你", "尽量", "尽可能",
          "务必", "一定要", "详细地", "详细", "认真地", "仔细地", "仔细", "好好地",
          "非常", "特别", "十分", "稍微", "一点", "一下", "好吗", "行吗", "谢谢", "多谢")
_MAX_QUESTION = 24     # 简化后的问法上限（只留"要什么"，不留"怎么要"）


def _clip(v, n=200):
    """把任意值压成短字符串（进 detail 的东西必须能落盘、能日志）。"""
    try:
        s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)
    except Exception:      # noqa: silent-ok — 序列化不了就用 repr
        s = repr(v)
    s = s.replace("\n", " ")
    return s if len(s) <= n else s[:n] + "…"


def _call_ok(v):
    """把 hook 的返回值折成"成功/失败"：字符串看非空，其它看布尔。"""
    if isinstance(v, str):
        return bool(v.strip())
    return bool(v)


@dataclass
class HealResult:
    """一次治疗的结果。

    output 的语义要分清（这是调用方最容易搞错的地方）：
      · 一级：output 是**修好的回答**（截断后的正文），可以直接给用户看；
      · 二级：output 是"重置+降级重问"之后的新回答（没有就退回原文）；
      · 三级/四级：output 为空串 —— 这两种情况下**不该继续作答**，
        要展示的是 note（给用户的报告），而不是一段勉强生成的文字。
        为什么留空而不是硬塞一段：硬塞 = 让已经不稳的模型继续说，正是我们要阻止的事。
    """
    level: int = 0
    action: str = ""
    ok: bool = False
    output: str = ""
    note: str = ""
    detail: dict = field(default_factory=dict)
    elapsed_ms: int = 0

    def to_dict(self):
        return {"level": self.level, "action": self.action, "ok": self.ok,
                "output": self.output, "note": self.note,
                "detail": self.detail, "elapsed_ms": self.elapsed_ms}


class HealthHealer:
    """四级治疗 + 预防层 + 会话隔离。

    `hooks` 全部可选，缺哪个用安全默认：
        retry(question, system, why) -> str        换角度重来一次
        reset_context(session) -> bool             清空当前会话上下文（长期记忆保留）
        reload_kv(session) -> bool                 重置模型状态（清 KV cache / 重新预热）
        switch_brain(reason) -> bool               切备用火种
        rollback(session) -> bool                  回滚到上一个稳定状态
        pause_task(reason) -> bool                 暂停任务并标记"待恢复"
        shutdown(reason) -> bool                   立即停止服务
        snapshot(reason) -> str                    保留现场，返回快照路径
        notify(level, text) -> None                强通知（界面 + 日志）
        organize(session) -> bool                  空闲时后台整理（记忆/索引）
    """

    def __init__(self, hooks=None, diagnose=None, records=None, monitor=None, cfg=None):
        self.hooks = dict(hooks or {}) if isinstance(hooks, dict) else {}
        self.diag = diagnose if diagnose is not None else HealthDiagnose(monitor=monitor)
        self.monitor = monitor
        self.records = records if records is not None else HealthRecords()
        c = _health_cfg(cfg if isinstance(cfg, dict) else None)
        self.cfg = c
        self.auto_heal = bool(c.get("auto_heal", True))
        self.preventive_on = bool(c.get("preventive", True))
        self.isolate_after = int(c.get("isolate_after", 3) or 3)
        self.turns_reset = int(c.get("turns_reset", 50) or 50)
        self.idle_organize_s = int(c.get("idle_organize_s", 1800) or 1800)
        self.probe_resources = bool(c.get("probe_resources", True))
        # 落盘路径**可被配置覆盖**：自测要往临时目录写（否则会污染用户真实病历/
        # 隔离表/"今天已自检"标记，跑一次自测就把用户今晚的凌晨自检吃掉了）。
        # 去掉这个开关：健康系统的自测没法脱离生产数据，跑自测 = 改用户状态。
        self.iso_path = c.get("iso_path") or _ISO_PATH
        self.state_path = c.get("state_path") or _STATE_PATH
        self.pause_path = c.get("pause_path") or _PAUSE_PATH
        self.shutdown_path = c.get("shutdown_path") or _SHUTDOWN_PATH
        self.switch_path = c.get("switch_path") or _SWITCH_PATH
        self.notify_path = c.get("notify_path") or _NOTIFY_PATH
        self.snapshot_dir = c.get("snapshot_dir") or health_dir()
        self._last_self_check = None

    # ==================================================================
    # hook 调用（唯一入口，所有调用都被记账且绝不抛）
    # ==================================================================
    def _adapt(self, fn, args):
        """按 hook 的形参个数裁剪实参。

        为什么要做这件事：hooks 是**别人注入的**，有人写 `def retry(q)`，
        有人写 `def retry(q, system, why)`。直接按最长签名调用，前者会 TypeError，
        而 TypeError 会被 `_hook` 吞掉 → 表现成"重试永远失败"，还查不出原因。
        去掉它：注入方少写一个参数，功能静默失效。
        """
        try:
            sig = inspect.signature(fn)
            params = list(sig.parameters.values())
            if any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params):
                return list(args)
            n = len([p for p in params if p.kind in (inspect.Parameter.POSITIONAL_ONLY,
                                                     inspect.Parameter.POSITIONAL_OR_KEYWORD)])
            return list(args[:n])
        except Exception:      # noqa: silent-ok — 签名读不出来就按原样调用
            return list(args)

    def _hook(self, name, detail, *args):
        """调一个 hook：优先注入的实现，其次内置默认。返回 (ok, value)，**永不抛**。"""
        fn = self.hooks.get(name)
        src = "injected" if callable(fn) else "default"
        if not callable(fn):
            fn = self._defaults().get(name)
        rec = {"name": name, "src": src, "ok": False, "ms": 0, "result": ""}
        t0 = time.time()
        try:
            if not callable(fn):
                rec["result"] = "无此 hook，也没有默认实现（跳过）"
                return False, None
            v = fn(*self._adapt(fn, args))
            rec["ok"] = _call_ok(v)
            if isinstance(v, str) and name == "retry":
                rec["result"] = "重试返回 %d 字" % len(v)
                return rec["ok"], v
            rec["result"] = _clip(v, 160)
            return rec["ok"], v
        except Exception as e:      # noqa: silent-ok — 治疗动作失败绝不能把对话带崩
            rec["ok"] = False
            rec["error"] = repr(e)
            rec["result"] = "hook 抛异常：%s" % _clip(e, 120)
            return False, None
        finally:
            rec["ms"] = int((time.time() - t0) * 1000)
            detail.setdefault("hooks", []).append(rec)

    # ==================================================================
    # 主入口
    # ==================================================================
    def heal(self, severity, session=None, symptoms=None, output="", question=""):
        """按严重度分级治疗。**永不抛异常**，最差返回 level=0 的"没治"。"""
        t0 = time.time()
        s = session if isinstance(session, dict) else {}
        text = output if isinstance(output, str) else ("" if output is None else str(output))
        q = question if isinstance(question, str) else ("" if question is None else str(question))
        detail = {"severity": severity, "session": _clip(s.get("sid") or s.get("session") or "", 40)}
        lvl = self._level_of(severity)
        if lvl <= 0:
            return HealResult(level=0, action="none", ok=False, output=text, note="",
                              detail={"error": "无法识别的严重度：%r" % (severity,)},
                              elapsed_ms=int((time.time() - t0) * 1000))
        if lvl <= 2 and not self.auto_heal:
            return HealResult(level=0, action="disabled", ok=False, output=text, note="",
                              detail={"why": "配置 auto_heal=False，一/二级自动治疗被关掉"},
                              elapsed_ms=int((time.time() - t0) * 1000))
        try:
            if lvl == 1:
                res = self._heal_1(s, symptoms, text, q, detail)
            elif lvl == 2:
                res = self._heal_2(s, symptoms, text, q, detail)
            elif lvl == 3:
                res = self._heal_3(s, symptoms, text, q, detail)
            else:
                res = self._heal_4(s, symptoms, text, q, detail)
        except Exception as e:      # noqa: silent-ok — 任何治疗内部的意外都不能把对话带崩
            res = HealResult(level=lvl, action="error", ok=False, output=text, note="",
                             detail={"error": repr(e)})
        res.detail.setdefault("severity", severity)
        res.elapsed_ms = int((time.time() - t0) * 1000)
        # 治疗结果必须进病历（学习层就靠这个回答"哪种治法管用"）
        try:
            # 症状为空时用 "unspecified" 占位，**不要拿严重度当症状**：
            # 那会把 by_symptom 统计污染成 {"LIGHT": 3, "MEDIUM": 2}，
            # 于是"最高频症状"变成了严重度，预防建议会开始胡说。
            codes = self._codes(symptoms) or ["unspecified"]
            ctx = {"turns": s.get("turns"), "model": s.get("model"), "sid": s.get("sid"),
                   "question": q, "output": text, "level": res.level, "cause": res.detail.get("cause"),
                   "streak": s.get("streak") if isinstance(s.get("streak"), dict) else None}
            res.detail["record"] = self.records.log(
                codes, self._severity_name(severity), res.action, res, ctx)
        except Exception as e:      # noqa: silent-ok — 记不上病历也不能让治疗失败
            res.detail["record_error"] = repr(e)
        # 反复退化的会话 → 自动隔离（只做简单任务）
        try:
            sid = s.get("sid") or s.get("session")
            if sid and res.level in (2, 3):
                res.detail["isolated"] = self.note_relapse(str(sid), self._severity_name(severity),
                                                          res.detail.get("cause", ""))
        except Exception as e:      # noqa: silent-ok — 隔离是优化，不能让它影响治疗
            res.detail["isolate_error"] = repr(e)
        return res

    @staticmethod
    def _level_of(severity):
        """严重度 → 1/2/3/4（接受 "LIGHT"/"light"/1/"1" 各种写法）。"""
        try:
            if isinstance(severity, (int, float)):
                n = int(severity)
                return n if 0 <= n <= 4 else 0
            s = str(severity or "").strip().upper()
            if s.isdigit():
                return int(s)
            return LEVEL_NUM.get(s, 0)
        except Exception:      # noqa: silent-ok — 认不出来就当作"不治"
            return 0

    @staticmethod
    def _severity_name(severity):
        try:
            if isinstance(severity, (int, float)):
                n = int(severity)
                return SEVERITY[n - 1] if 1 <= n <= 4 else "LIGHT"
            s = str(severity or "").strip().upper()
            return s if s in SEVERITY else "LIGHT"
        except Exception:      # noqa: silent-ok — 兜底 LIGHT（最保守）
            return "LIGHT"

    @staticmethod
    def _codes(symptoms):
        """症状 → list[str]（容错：Symptom / dict / str / None 都吃）。"""
        out = []
        items = symptoms if isinstance(symptoms, (list, tuple, set)) else ([symptoms] if symptoms else [])
        for s in items:
            try:
                c = s if isinstance(s, str) else (
                    (s.get("code") or s.get("symptom")) if isinstance(s, dict) else getattr(s, "code", ""))
            except Exception:      # noqa: silent-ok — 读不出来就跳过
                c = ""
            c = str(c or "").strip()
            if c and c not in out:
                out.append(c)
        return out

    def _diagnose(self, symptoms, session):
        """要一句"原因/建议"（三级报告要用）。出任何问题都退回通用文案。"""
        try:
            d = self.diag.diagnose(symptoms, session)
            if isinstance(d, dict) and d.get("reason"):
                return d
        except Exception:      # noqa: silent-ok — 诊断不可用也要能出报告
            pass
        return {"severity": "LIGHT", "cause": "model",
                "reason": "载体监测到本轮输出明显异常，但诊断层没给出细节。",
                "advice": "建议换个更简单的问法，或稍后再试。", "codes": self._codes(symptoms)}

    # ==================================================================
    # 一级：自动、用户无感
    # ==================================================================
    def _heal_1(self, session, symptoms, text, question, detail):
        """① 复读截断 ② 乱码/断句规整 ③ 校验不过 → 重做一次（**最多一次**）。

        为什么重试硬限一次：如果"重试"本身也会退化，重试就会变成新的退化源
        （每次重试都退化 → 再重试 → 死循环烧算力）。一次不行就升级到二级，
        由"清上下文"来打断这个循环，而不是原地再来一遍。
        """
        codes = set(self._codes(symptoms))
        out = text
        cut = 0
        actions = []
        # ① 复读截断（无论有没有 repeat 症状都跑一遍检测：调用方可能没走监测层就直接治）
        try:
            t2, hit, n = D.truncate_repeat(out)
            if hit is not None and n > 0:
                out, cut = t2, n
                actions.append("truncate_repeat")
                detail["repeat"] = {"kind": hit.kind, "phrase": _clip(hit.phrase, 24),
                                    "count": hit.count, "cut_chars": n}
        except Exception as e:      # noqa: silent-ok — 截断失败就保持原文（宁可留着也不能丢内容）
            detail["truncate_error"] = repr(e)
        # ② 乱码/断句 → 先规整（去非法字符 + 回退到完整句）
        if codes & {"garbled", "broken_sentence"} or self._has_ctrl(out):
            t3, n2 = self._tidy(out)
            if n2 > 0 or t3 != out:
                detail["tidy"] = {"cut_chars": n2, "had_ctrl": self._has_ctrl(text)}
                actions.append("tidy_text")
                out, cut = t3, cut + n2
        # ③ 校验：还不过就换角度重做一次
        good, why = self._validate(out, codes)
        detail["validate"] = {"ok": good, "why": why}
        if not good and question:
            ok, new = self._hook("retry", detail, question, "", why)
            if ok and isinstance(new, str) and new.strip():
                out2, _hit2, n3 = D.truncate_repeat(new)
                t4, n4 = D.repair_tail(out2)
                out = t4 or new
                cut += n3 + n4
                actions.append("retry_once")
                good, why = self._validate(out, codes)
                detail["validate"] = {"ok": good, "why": why, "after": "retry"}
        detail["cut_chars"] = cut
        return HealResult(level=1, action="+" .join(actions) or "none", ok=bool(out.strip()),
                          output=out,
                          # 一级必须让用户**看不出来**治过：note 为空串（界面上什么都不显示）
                          note="", detail=detail)

    @staticmethod
    def _has_ctrl(text):
        """有没有非法控制字符 / 替换符（乱码的硬指标）。"""
        try:
            return bool(re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufffd]", text or ""))
        except Exception:      # noqa: silent-ok — 正则失败就当没有，不影响主流程
            return False

    def _tidy(self, text):
        """规整文本：去非法控制字符/替换符 → 回退到最后一个完整句。返回 (新文本, 砍掉字数)。"""
        t = text or ""
        try:
            t2 = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", t).replace("\ufffd", "")
        except Exception:      # noqa: silent-ok — 清理失败就用原文，至少不丢内容
            t2 = t
        t3, n = D.repair_tail(t2)
        return t3, max(0, len(t) - len(t3))

    def _validate(self, text, codes=None):
        """治完之后再验一遍：还病着吗？返回 (是否通过, 为什么)。"""
        try:
            if not (text or "").strip():
                return False, "输出为空"
            if self._has_ctrl(text):
                return False, "仍含非法控制字符/替换符"
            hit = D.detect(text, where="heal_validate")
            if hit is not None:
                return False, "仍检测到复读（%s）" % hit.kind
            return True, ""
        except Exception as e:      # noqa: silent-ok — 验不了就当通过（不能因校验器故障去重试）
            return True, "校验器异常：%r" % (e,)

    # ==================================================================
    # 二级：自动 + 界面提示
    # ==================================================================
    def _heal_2(self, session, symptoms, text, question, detail):
        """清当前会话上下文（**长期记忆保留**）+ 重置模型状态 + 降级（简化问题）重试一次。

        【本轮实测抓到的真 bug —— 二级治疗会把病态回答原样还给用户】
        用户实测：回答里整张表格被"预算"刷满几十行，健康系统明明报出了 `repeat` 症状，
        用户却还是看到了那一屏垃圾。根因就在这里：
          判到 MEDIUM 时（一轮里 ≥3 个症状就会到 MEDIUM）走的是这条路径 ——
          它整段都在忙"清上下文 + 重试"，`out` 一直等于**原文**；
          一旦重试没拿到新内容（模型离线 / 重试也退化 / retry hook 返回空），
          就把那份病态回答**原封不动**返回了。
        这等于"诊断出来了、药也开了、但病人吃的是原来那碗坏饭"。
        修法：不管重试成不成功，**先给原文做一遍退化解毒**（截断 + 回退完整句）——
        拿到新内容用新内容，拿不到就用"治过的原文"，绝不把没治过的原文交出去。
        """
        actions = []
        ok_any = False
        ok, _ = self._hook("reset_context", detail, session)
        actions.append("reset_context" if ok else "reset_context(fail)")
        ok_any = ok_any or ok
        ok2, _ = self._hook("reload_kv", detail, session)
        actions.append("reload_kv" if ok2 else "reload_kv(fail)")
        ok_any = ok_any or ok2
        # ① 先给原文解毒：无论后面重试成不成，这一步都保证"交出去的不会是刷屏原文"
        out = text
        try:
            t0, hit0, n0 = D.truncate_repeat(out)
            if hit0 is not None and n0 > 0:
                out = t0
                actions.append("truncate_repeat")
                detail["repeat_pre"] = {"kind": hit0.kind, "phrase": _clip(hit0.phrase, 24),
                                        "count": hit0.count, "cut_chars": n0}
                ok_any = True
            t0b, n0b = self._tidy(out)
            if n0b > 0 or t0b != out:
                out, _ = t0b, None
                detail["tidy_pre"] = {"cut_chars": n0b}
        except Exception as e:      # noqa: silent-ok — 解毒失败就保持原文，后面还有校验兜着
            detail["truncate_pre_error"] = repr(e)
        qu = self.simplify(question) if question else ""
        if qu:
            # 简化后的问法必须记进 detail：这是"降级策略"的**证据**，
            # 事后复盘"为什么这轮答得不一样"就靠它。
            detail["degraded_question"] = qu
            ok3, new = self._hook("retry", detail, qu, "", "二级治疗：上下文已清、问题已简化后重做")
            actions.append("retry_degraded" if ok3 else "retry_degraded(fail)")
            ok_any = ok_any or ok3
            if ok3 and isinstance(new, str) and new.strip():
                # ② 重试拿到的内容**同样要过一遍解毒**（重试也可能又退化 —— 那正是"二级"要拦的）
                out2, _h, _n = D.truncate_repeat(new)
                out2, _n2 = D.repair_tail(out2)
                if out2.strip():
                    out = out2
                    actions.append("use_retry")
        # ③ 最后的证据留痕：治完之后还有没有复读？有就如实记下来（不许假装治好了）
        try:
            still = D.detect(out, where="heal2_after")
            detail["still_degenerate"] = (still.kind if still else "")
        except Exception as e:      # noqa: silent-ok — 复查失败不影响返回
            detail["still_error"] = repr(e)
        return HealResult(level=2, action="+".join(actions) or "none", ok=bool(ok_any),
                          output=out,
                          note="刚才的回答质量不佳，我已重新组织",
                          detail=detail)

    # ==================================================================
    # 三级：半自动（切一次、不自动重试、出报告）
    # ==================================================================
    def _heal_3(self, session, symptoms, text, question, detail):
        """切备用火种 + 回滚会话 + 暂停任务；同时必须产出给用户看的报告。

        为什么先 `snapshot`：回滚需要"上一个稳定状态"，而没有快照就**没法回滚**。
        先留现场，再切火种 —— 顺序反了的话，切完火种现场就没了（模型状态变了）。
        为什么"只切一次、不自动重试"：换火种相当于换了个"人"接着答，
        到底要不要继续、要不要重问，是**用户**该决定的事（半自动的含义就在这）。
        """
        d = self._diagnose(symptoms, session)
        detail["cause"] = d.get("cause")
        reason, advice = d.get("reason") or "", d.get("advice") or ""
        report = "小焦现在状态不太好，需要休息一下。原因：%s。建议：%s。" % (reason, advice)
        detail["report"] = report
        actions = []
        ok_snap, path = self._hook("snapshot", detail, reason)
        actions.append("snapshot" if ok_snap else "snapshot(fail)")
        ok1, _ = self._hook("switch_brain", detail, reason)
        actions.append("switch_brain" if ok1 else "switch_brain(fail)")
        ok2, _ = self._hook("rollback", detail, session)
        actions.append("rollback" if ok2 else "rollback(fail)")
        ok3, _ = self._hook("pause_task", detail, reason)
        actions.append("pause_task" if ok3 else "pause_task(fail)")
        try:
            self._hook("notify", detail, 3, report)
        except Exception:      # noqa: silent-ok — 通知失败不影响已经做过的治疗动作
            pass
        return HealResult(level=3, action="+".join(actions), ok=bool(ok1 or ok2 or ok3),
                          output="", note=report, detail=detail)

    # ==================================================================
    # 四级：全自动 + 强通知（停机、保现场、不重试、不继续生成）
    # ==================================================================
    def _heal_4(self, session, symptoms, text, question, detail):
        """停机 + 保留现场 + 双通道通知。**不重试、不继续生成。**

        为什么四级要"立刻停"而不是"先试试重试"：进入四级的判据本身就是
        "乱码/拒绝连着三轮"或"显存告警+超时同时出现" —— 前者说明这个火种
        在这个上下文里已经彻底不可用，后者说明机器都扛不住了。
        这两种情况下再生成一次，只会多产生一段垃圾（四级还可能把显存耗干拖垮整机）。
        """
        d = self._diagnose(symptoms, session)
        detail["cause"] = d.get("cause")
        reason, advice = d.get("reason") or "", d.get("advice") or ""
        report = ("小焦现在状态不太好，必须马上停下来休息。原因：%s。建议：%s。"
                  % (reason, advice))
        detail["report"] = report
        ok_snap, path = self._hook("snapshot", detail, reason)
        ok_down, _ = self._hook("shutdown", detail, reason)
        notified, _ = self._hook("notify", detail, 4, report + "（已停止服务，现场已保留）")
        if isinstance(path, str) and path:
            detail["snapshot_path"] = path
        note = report + ("（现场已保留：%s）" % path if isinstance(path, str) and path else "")
        return HealResult(level=4, action="snapshot+shutdown+notify", ok=bool(ok_down or ok_snap),
                          output="", note=note, detail=detail)

    # ==================================================================
    # 预防层
    # ==================================================================
    def preventive(self, session=None):
        """预防：不等出事。①连续 ≥50 轮清上下文 ②空闲 ≥30 分钟整理 ③凌晨自检一次。

        为什么要"防"：一级一级治是**救火**；救火再多也不如不烧起来。
        这三条对应三种最常见的起火原因：
          ① 对话轮数太多 → 注意力稀释 → 答非所问（**信号最明确、收益最大**）；
          ② 长时间空闲 → 该趁没人用的时候整理记忆，别在用户等着的时候整理；
          ③ 每天凌晨做一次全面自检 → 把"偶发"变成"有据可查"（病历+趋势）。
        去掉预防层：健康系统永远是"事后补救"，用户体感就是"偶尔抽风"。

        返回一份可读报告 dict（做了哪些动作、为什么、结果如何）。
        """
        s = session if isinstance(session, dict) else {}
        now = s.get("now")
        try:
            now = float(now) if now is not None else time.time()
        except Exception:      # noqa: silent-ok — now 写坏了就用当前时间
            now = time.time()
        out = {"ts": now, "actions": [], "notes": [], "ok": True}
        if not self.preventive_on:
            out["ok"] = False
            out["notes"].append("预防层在配置里被关掉了（health.preventive=False）")
            return out
        detail = {}
        # ① 轮数
        try:
            turns = int(s.get("turns") or 0)
        except Exception:      # noqa: silent-ok — turns 不是数字就当 0
            turns = 0
        if turns >= self.turns_reset:
            ok, _ = self._hook("reset_context", detail, s)
            out["actions"].append({"name": "reset_context", "ok": ok, "why": "turns>=%d" % self.turns_reset})
            out["notes"].append("已经聊了 %d 轮（阈值 %d 轮）：清一次当前上下文，长期记忆保留。"
                                % (turns, self.turns_reset))
        # ② 空闲整理
        idle = s.get("idle_s")
        if idle is None and s.get("last_active_ts") is not None:
            try:
                idle = now - float(s.get("last_active_ts"))
            except Exception:      # noqa: silent-ok — 时间戳坏掉就当没空闲
                idle = None
        try:
            idle = float(idle) if idle is not None else None
        except Exception:      # noqa: silent-ok — 同上
            idle = None
        if idle is not None and idle >= self.idle_organize_s:
            ok, _ = self._hook("organize", detail, s)
            out["actions"].append({"name": "organize", "ok": ok, "why": "idle>=%ds" % self.idle_organize_s})
            out["notes"].append("空闲了 %.0f 分钟（阈值 %.0f 分钟）：趁没人用，后台整理一次记忆。"
                                % (idle / 60.0, self.idle_organize_s / 60.0))
        # ③ 凌晨自检（每天只做一次）
        try:
            hour = s.get("hour")
            hour = int(hour) if hour is not None else time.localtime(now).tm_hour
        except Exception:      # noqa: silent-ok — 时间读不出来就不自检（宁可少做）
            hour = 12
        lo, hi = self.cfg.get("self_check_hour", (0, 5))
        try:
            lo, hi = int(lo), int(hi)
        except Exception:      # noqa: silent-ok — 配置写坏了就用默认时段
            lo, hi = 0, 5
        today = time.strftime("%Y-%m-%d", time.localtime(now))
        done = self._state().get("last_self_check")
        if lo <= hour < hi and done != today:
            rep = self._run_self_check(today)
            out["actions"].append({"name": "self_check", "ok": bool(rep.get("ok")), "why": "凌晨自检"})
            out["notes"].append("凌晨自检完成：%s" % (rep.get("summary") or "（无摘要）"))
            out["self_check"] = rep
        out["ok"] = all(a.get("ok") for a in out["actions"]) if out["actions"] else True
        if not out["actions"]:
            out["notes"].append("预防层检查过：轮数 %d（< %d）、空闲 %s、当前 %d 点 —— 暂不需要动作。"
                                % (turns, self.turns_reset,
                                   ("%.0f 分钟" % (idle / 60.0)) if idle is not None else "未知", hour))
        return out

    # ---------- 全面自检 ----------
    def resources(self):
        """本机资源读数（显存/内存）。**只读，不做任何变更**；拿不到就返回空 dict。

        为什么用 nvidia-smi 而不是引第三方库：不用新依赖，且失败可控（超时 3 秒）。
        为什么探不到也要正常返回：这个函数会出现在自检报告里，
        探不到只是"这项没数据"，绝不能让体检本身失败。
        """
        out = {}
        if not self.probe_resources:
            out["skipped"] = True
            return out
        try:
            import psutil
            vm = psutil.virtual_memory()
            out["mem_used_pct"] = round(float(vm.percent), 1)
            out["mem_total_mb"] = int(vm.total / 1048576)
        except Exception as e:      # noqa: silent-ok — 没有 psutil / 取不到内存就跳过
            out["mem_error"] = _clip(e, 120)
        try:
            import shutil as _sh
            import subprocess
            exe = _sh.which("nvidia-smi")
            if exe:
                r = subprocess.run([exe, "--query-gpu=memory.used,memory.total",
                                    "--format=csv,noheader,nounits"],
                                   capture_output=True, text=True, timeout=3)
                line = (r.stdout or "").strip().splitlines()
                if line:
                    used, total = [x.strip() for x in line[0].split(",")[:2]]
                    out["vram_used_mb"] = int(float(used))
                    out["vram_total_mb"] = int(float(total))
                    if out["vram_total_mb"]:
                        out["vram_used_pct"] = round(out["vram_used_mb"] / float(out["vram_total_mb"]), 3)
            else:
                out["vram"] = "无 nvidia-smi"
        except Exception as e:      # noqa: silent-ok — 显卡查询失败（超时/被沙箱拦）只跳过
            out["vram_error"] = _clip(e, 120)
        return out

    def self_check(self):
        """全面自检：退化流水 + 病历分析 + 资源检查 → 一份中文报告 dict。"""
        today = time.strftime("%Y-%m-%d")
        return self._run_self_check(today)

    def _run_self_check(self, today):
        rep = {"ts": time.time(), "iso_time": time.strftime("%Y-%m-%d %H:%M:%S"),
               "ok": True, "degeneration": {}, "records": {}, "resources": {}, "notes": []}
        try:
            rep["degeneration"] = D.summary(days=7)
        except Exception as e:      # noqa: silent-ok — 退化流水读不到只是少一块
            rep["degeneration"] = {"error": repr(e)}
        try:
            rep["records"] = self.records.analyze(days=7)
        except Exception as e:      # noqa: silent-ok — 病历分析失败也只是少一块
            rep["records"] = {"error": repr(e)}
        try:
            rep["resources"] = self.resources()
        except Exception as e:      # noqa: silent-ok — 资源探测失败同上
            rep["resources"] = {"error": repr(e)}
        try:
            n_deg = int((rep["degeneration"] or {}).get("total") or 0)
            n_sym = int((rep["records"] or {}).get("total") or 0)
            rate = float((rep["records"] or {}).get("heal_rate") or 0)
            res = rep["resources"] or {}
            bits = ["最近 7 天退化命中 %d 次、病历 %d 条、治疗成功率 %.0f%%" % (n_deg, n_sym, rate * 100)]
            if "vram_used_pct" in res:
                bits.append("显存已用 %.0f%%" % (float(res["vram_used_pct"]) * 100))
            if "mem_used_pct" in res:
                bits.append("内存已用 %.0f%%" % float(res["mem_used_pct"]))
            rep["notes"] = bits
            rep["summary"] = "；".join(bits)
            if "vram_used_pct" in res and float(res["vram_used_pct"]) >= 0.9:
                rep["notes"].append("显存已过 90%：这是退化的高发条件，建议降低上下文或换更小的火种。")
            if n_deg >= 10:
                rep["notes"].append("7 天退化 %d 次（≥10 次说明这个火种在当前上下文长度下不稳）。" % n_deg)
            rep["ok"] = True
        except Exception as e:      # noqa: silent-ok — 摘要拼不出来也不影响报告主体
            rep["summary"] = "自检完成（摘要生成异常：%r）" % (e,)
        try:
            st = self._state()
            st["last_self_check"] = today
            st["last_self_check_ts"] = time.time()
            write_json(self.state_path, st)
            self._last_self_check = today
        except Exception:      # noqa: silent-ok — 状态写不上只会导致"下次多做一次自检"
            pass
        return rep

    def _state(self):
        """读预防层的状态文件（"今天自检过没有"）。

        **实例方法**而不是 staticmethod：路径要落在实例上（可被配置覆盖到临时目录），
        写成类级方法就没法覆盖 —— 自测跑一次就会把用户"今天已自检"的标记写掉。
        """
        v = read_json(self.state_path, {})
        return v if isinstance(v, dict) else {}

    # ==================================================================
    # 隔离机制
    # ==================================================================
    def _iso(self):
        """读隔离表（每次都从盘上读：多个会话可能来自不同进程，缓存会读旧）。"""
        v = read_json(self.iso_path, {})
        return v if isinstance(v, dict) else {}

    def isolate(self, sid, reason=""):
        """标记某会话为隔离状态（隔离中只做简单任务）。返回当前记录 dict。"""
        sid = str(sid or "")
        if not sid:
            return {}
        try:
            st = self._iso()
            rec = st.get(sid) if isinstance(st.get(sid), dict) else {}
            rec = {"reason": _clip(reason, 200), "ts": time.time(),
                   "iso_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "count": int(rec.get("count") or 0)}
            st[sid] = rec
            write_json(self.iso_path, st)
            log_line("heal", "隔离会话 %s：%s" % (sid, _clip(reason, 120)))
            return rec
        except Exception as e:      # noqa: silent-ok — 隔离写不上只是少一层保护
            return {"error": repr(e)}

    def is_isolated(self, sid):
        """这个会话是否处于隔离中。"""
        try:
            return str(sid or "") in self._iso()
        except Exception:      # noqa: silent-ok — 读不出来就当作没隔离（不阻断用户）
            return False

    def release(self, sid):
        """解除隔离（用户改了问法/换了任务之后）。"""
        sid = str(sid or "")
        try:
            st = self._iso()
            if sid in st:
                st.pop(sid, None)
                write_json(self.iso_path, st)
                return True
        except Exception:      # noqa: silent-ok — 解不开也只是保持隔离，不影响对话
            return False
        return False

    def note_relapse(self, sid, severity, cause=""):
        """记一次"这个会话又退化了"；到阈值就自动隔离。

        为什么按**会话**统计而不是全局：退化常常是"这个任务/这个问法"引起的。
        全局统计会被别的会话冲淡，永远到不了阈值；按会话才能精准地
        "对这一个会话降级"，而不是对所有用户降级。

        【踩过的坑】第一版只在"会话已经在隔离表里"时才把计数写回盘上，
        于是新会话的计数永远是 0：第 1 次 → cnt=1，因为 sid 不在表里 → 直接 return False，
        计数根本没落盘 → 第 2 次又从 1 开始 → **永远到不了阈值，自动隔离形同虚设**。
        现在无论隔离与否都先把计数写下来，再判断要不要隔离。
        """
        sid = str(sid or "")
        if not sid:
            return False
        try:
            if str(severity).upper() not in ("MEDIUM", "HEAVY"):
                return self.is_isolated(sid)
            st = self._iso()
            rec = st.get(sid) if isinstance(st.get(sid), dict) else {}
            cnt = int(rec.get("count") or 0) + 1
            # 先落盘计数（isolate() 会读回这条记录并保留 count），再决定隔离
            st[sid] = {"reason": rec.get("reason") or "", "ts": rec.get("ts") or time.time(),
                       "count": cnt}
            write_json(self.iso_path, st)
            if cnt >= self.isolate_after:
                self.isolate(sid, "反复退化 %d 次（阈值 %d，最近一次 %s/%s）"
                             % (cnt, self.isolate_after, severity, cause or "未判因"))
                return True
            return False
        except Exception:      # noqa: silent-ok — 统计失败不影响本次治疗
            return False

    def simplify(self, question, limit=_MAX_QUESTION):
        """把问题简化成"最小可用问法"（隔离中/二级降级都用它）。

        为什么只做"去修饰 + 截短"而不做"改写"：改写要再调一次模型，
        而调模型正是当前不可靠的那个环节 —— 越不可靠越不能依赖它。
        纯文本的简化虽然没有改写聪明，但它**永远能成功、永远不花算力**。
        """
        q = question if isinstance(question, str) else ("" if question is None else str(question))
        orig = q
        try:
            q = re.sub(r"[（(][^）)]{0,30}[）)]", "", q)      # 去掉括号补充说明
            for w in _DECOR:
                q = q.replace(w, "")
            q = re.sub(r"\s+", " ", q).strip(" \t，,。.；;：:、！!？?　")
            if len(q) > limit:
                cut = -1
                for i in range(limit, max(4, limit // 2), -1):     # 尽量切在标点处
                    if q[i - 1] in "，,。.；;：:、！!？? ":
                        cut = i
                        break
                q = q[:cut] if cut > 0 else q[:limit]
                q = q.strip(" \t，,。.；;：:、！!？?　")
            if len(q) >= len(orig) and len(orig) > limit:          # 兜底：必须真的更短
                q = orig[:limit].strip()
        except Exception:      # noqa: silent-ok — 简化失败就原样返回（绝不抛）
            return orig
        return q or orig[:limit]

    # ==================================================================
    # 默认实现（**真实动作**，不是占位）
    # ==================================================================
    def _defaults(self):
        return {"retry": self._d_retry, "reset_context": self._d_reset_context,
                "reload_kv": self._d_reload_kv, "switch_brain": self._d_switch_brain,
                "rollback": self._d_rollback, "pause_task": self._d_pause_task,
                "shutdown": self._d_shutdown, "snapshot": self._d_snapshot,
                "notify": self._d_notify, "organize": self._d_organize}

    def _d_retry(self, question, system="", why=""):
        """默认重试：只有在 app **已经活着**（已在 sys.modules）时才调它重来一次。

        为什么不在这里 import app：见 `core/health/__init__.py::app_module` ——
        实测会连带加载 4B 模型与一堆服务（2.63s + 一屏启动日志），
        而重试只是"锦上添花"的动作，绝不值得卡住用户 2.6 秒。
        """
        app = app_module(allow_import=False)
        if app is None:
            return ""
        for name in ("agent_run",):
            fn = getattr(app, name, None)
            if not callable(fn):
                continue
            try:
                return fn(question, lean=True) or ""
            except TypeError:
                try:
                    return fn(question) or ""
                except Exception:      # noqa: silent-ok — 重试失败就交给上层升级治疗
                    return ""
            except Exception:      # noqa: silent-ok — 同上
                return ""
        return ""

    def _d_reset_context(self, session=None):
        """默认清上下文：把**当前会话的消息**清空，长期记忆（记忆库/向量库）完全不动。

        为什么只清 messages、不动别的字段：会话里还有标题、id、创建时间等，
        清掉它们等于"删了用户的会话"；我们要的是"这一轮不再背着旧上下文"，
        不是"把会话毁了"。长期记忆更是绝对不能清 —— 那是无限 1 的立身之本。
        """
        app = app_module(allow_import=False)
        if app is None:
            return False
        try:
            sid = (session or {}).get("sid") or (session or {}).get("session")
            d = app._sessions() if hasattr(app, "_sessions") else None
            if not isinstance(d, dict) or "sessions" not in d:
                return False
            s = None
            if sid:
                s = next((x for x in d.get("sessions", []) if str(x.get("id")) == str(sid)), None)
            if s is None:
                cur = d.get("current")
                s = next((x for x in d.get("sessions", []) if str(x.get("id")) == str(cur)), None)
            if s is None:
                return False
            had = len(s.get("messages") or [])
            s["messages"] = []
            s["context_reset_at"] = time.time()
            s["context_reset_note"] = "健康系统二级治疗：清空当前上下文（长期记忆保留）"
            if hasattr(app, "_save_sessions"):
                app._save_sessions(d)
            log_line("heal", "已清空会话 %s 的 %d 条上下文" % (s.get("id"), had))
            return True
        except Exception as e:      # noqa: silent-ok — 清不动就如实返回失败，绝不假装成功
            log_line("heal", "清上下文失败：%r" % (e,))
            return False

    def _d_reload_kv(self, session=None):
        """默认重置模型状态：只有 app 暴露了对应能力才做。

        为什么默认失败而不是"假装成功"：KV cache 是**推理服务**的状态，
        载体层没法隔空重置它。假装成功会让病历记下"重置过了"，
        而下一次退化时诊断会以为是别的原因 —— 比不做更坏。
        """
        app = app_module(allow_import=False)
        if app is None:
            return False
        for name in ("reload_kv", "reset_kv", "warmup_model", "unload_model"):
            fn = getattr(app, name, None)
            if callable(fn):
                try:
                    return bool(fn())
                except Exception:      # noqa: silent-ok — 试下一个能力名
                    continue
        return False

    def _d_switch_brain(self, reason=""):
        """默认切火种：**登记切换请求**（不擅自改用户的模型配置）。

        为什么不直接改 xiaojiao_control.json：那是用户的"生存配置" ——
        改错一个字段，小焦下次就起不来（比如把 engine 切成 api 但没有 key）。
        载体层在这里只做一件事：把"该切到哪个火种、为什么"写成请求文件，
        由活着的 app / 下次启动 / 界面确认来执行。这是**真实动作**（有落盘、有可核对的候选），
        只是把"改配置"这个不可逆的动作留给能校验它的人。
        没有备用火种时如实返回 False（不然等于骗诊断层"已经换人了"）。
        """
        try:
            from . import CONTROL_FILE
            cfg = read_json(CONTROL_FILE, {}) or {}
            models = cfg.get("models") if isinstance(cfg, dict) else None
            names = [str(m.get("name")) for m in models if isinstance(m, dict) and m.get("name")] \
                if isinstance(models, list) else []
            cur = str(cfg.get("model_name") or "")
            nxt = next((n for n in names if n != cur), "")
            if not nxt:
                return False
            req = {"ts": time.time(), "iso_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "reason": _clip(reason, 300), "from": cur, "want": nxt, "candidates": names,
                   "note": "健康系统三级治疗请求：切到这个火种（由 app/下次启动执行，载体不擅自改配置）"}
            ok = write_json(self.switch_path, req)
            log_line("heal", "登记火种切换请求：%s → %s（%s）" % (cur, nxt, _clip(reason, 80)))
            return bool(ok)
        except Exception as e:      # noqa: silent-ok — 登记不上就如实失败
            log_line("heal", "登记火种切换请求失败：%r" % (e,))
            return False

    def _d_rollback(self, session=None):
        """默认回滚：没有"上一个稳定状态"就**不假装回滚**。

        为什么默认失败：回滚的前提是有一份快照。没有快照却返回 True，
        用户会以为会话回到了干净状态，实际没有 —— 后面所有的判断都建立在假前提上。
        三级治疗会**先 snapshot 再 rollback**，所以第一次常常是"留了现场但没得回滚"，
        第二次（同一个会话再犯）就真有东西可回滚了。这个语义要写在注释里，
        不然下一个人会以为这是 bug。
        """
        app = app_module(allow_import=False)
        if app is not None:
            for name in ("rollback_session", "restore_snapshot"):
                fn = getattr(app, name, None)
                if callable(fn):
                    try:
                        return bool(fn(session))
                    except Exception:      # noqa: silent-ok — 试下一个能力名
                        continue
        return False

    def _d_pause_task(self, reason=""):
        """默认暂停任务：写"待恢复"标记（真实落盘），让用户下次回来能接着做。"""
        try:
            rec = read_json(self.pause_path, {}) or {}
            if not isinstance(rec, dict):
                rec = {}
            rec.update({"paused": True, "ts": time.time(),
                        "iso_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "reason": _clip(reason, 300), "resume_hint": "状态好了就从这里接着做"})
            ok = write_json(self.pause_path, rec)
            log_line("heal", "暂停任务：%s" % _clip(reason, 120))
            return bool(ok)
        except Exception as e:      # noqa: silent-ok — 标记写不上就如实失败
            log_line("heal", "暂停标记写入失败：%r" % (e,))
            return False

    def _d_shutdown(self, reason=""):
        """默认停机：**登记停机请求**，不真的 os._exit。

        为什么载体层不自己退出：`os._exit` 会立刻丢掉用户正在说的话、
        未落盘的会话和正在跑的工具调用 —— 那是"杀了小焦"，不是"让小焦休息"。
        正确做法是把"必须停机"写成事实（请求文件 + 通知 + 日志），
        由宿主/看门狗/界面执行优雅停机。这一层负责**判断和留证据**，不负责扣扳机。
        """
        try:
            rec = {"ts": time.time(), "iso_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "reason": _clip(reason, 500), "requested": True,
                   "note": "健康系统四级治疗：请求立即停机（由宿主/界面执行优雅停机）"}
            ok = write_json(self.shutdown_path, rec)
            append_jsonl(self.notify_path, {"ts": rec["ts"], "level": 4, "text": "请求停机：%s" % rec["reason"]})
            log_line("heal", "四级治疗请求停机：%s" % _clip(reason, 200))
            return bool(ok)
        except Exception as e:      # noqa: silent-ok — 请求写不上就如实失败
            log_line("heal", "停机请求写入失败：%r" % (e,))
            return False

    def _d_snapshot(self, reason=""):
        """默认保留现场：把资源读数 + 退化流水 + 病历摘要 + 隔离状态写成一个快照文件。

        为什么必须落盘而不是只打日志：日志会被刷掉、会被轮转，
        而"它犯病那一刻现场是什么样"是事后唯一能复盘的东西（也是回滚的前提）。
        返回快照路径，让上层能把它显示给用户（用户知道"东西没丢"）。
        """
        try:
            ts = time.time()
            path = os.path.join(self.snapshot_dir, "snapshot_%s.json" % time.strftime("%Y%m%d_%H%M%S", time.localtime(ts)))
            snap = {"ts": ts, "iso_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)),
                    "reason": _clip(reason, 500), "pid": os.getpid(),
                    "resources": {}, "degeneration": {}, "records": {}, "isolated": {}}
            try:
                snap["resources"] = self.resources()
            except Exception:      # noqa: silent-ok — 快照里少一块也比没有快照好
                pass
            try:
                snap["degeneration"] = D.summary(days=1)
            except Exception:      # noqa: silent-ok — 同上
                pass
            try:
                snap["records"] = self.records.analyze(days=1)
            except Exception:      # noqa: silent-ok — 同上
                pass
            try:
                snap["isolated"] = self._iso()
            except Exception:      # noqa: silent-ok — 同上
                pass
            ok = write_json(path, snap)
            log_line("heal", "保留现场 → %s（%s）" % (path, _clip(reason, 120)))
            return path if ok else ""
        except Exception as e:      # noqa: silent-ok — 快照失败不能影响停机/治疗
            log_line("heal", "快照失败：%r" % (e,))
            return ""

    def _d_notify(self, level=1, text=""):
        """默认强通知：落 `notify.jsonl` + 日志，并尽量走 app 的界面通道。

        为什么通知要"双通道"（界面 + 日志）：界面可能正卡着/用户不在，
        日志可能没人看。两条都发，才能保证"这件事一定留下了痕迹"。
        """
        ok = False
        try:
            ok = append_jsonl(self.notify_path, {"ts": time.time(), "level": int(level or 1),
                                            "text": _clip(text, 800),
                                            "iso_time": time.strftime("%Y-%m-%d %H:%M:%S")})
            log_line("heal", "通知(level=%s)：%s" % (level, _clip(text, 300)))
        except Exception:      # noqa: silent-ok — 落盘失败也要继续尝试界面通道
            pass
        app = app_module(allow_import=False)
        if app is not None:
            for name in ("notify", "push_note", "toast"):
                fn = getattr(app, name, None)
                if callable(fn):
                    try:
                        fn(int(level or 1), text)
                        ok = True
                        break
                    except Exception:      # noqa: silent-ok — 界面通道失败就只算落盘那条
                        continue
        return bool(ok)

    def _d_organize(self, session=None):
        """默认后台整理：没接 app 时**什么都不做**（no-op，而不是假装做了）。

        为什么明确返回 False：整理记忆/重建索引是 app 的活。这里返回 True
        会让预防层的报告显示"已整理"，而实际上什么都没发生 —— 报告就不再可信了。
        """
        app = app_module(allow_import=False)
        if app is None:
            return False
        for name in ("organize_memory", "memory_organize", "reindex_memory"):
            fn = getattr(app, name, None)
            if callable(fn):
                try:
                    return bool(fn())
                except Exception:      # noqa: silent-ok — 试下一个能力名
                    continue
        return False


def heal(severity, session=None, symptoms=None, output="", question="", hooks=None, **kw):
    """便捷入口：一次性治疗（不需要自己 new 对象时用）。"""
    return HealthHealer(hooks=hooks, **kw).heal(severity, session=session, symptoms=symptoms,
                                               output=output, question=question)


__all__ = ["HealthHealer", "HealResult", "heal", "_ISO_PATH", "_STATE_PATH"]
