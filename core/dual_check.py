# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 双模型交叉审校（2026-10-17）

【为什么需要它】单模型最危险的地方是**它自己不知道自己在编**。
项目里原有的"元认知自评"是**同一个模型给自己打分** —— 实测它的自评和实际质量经常对不上
（自评 B，输出的却是编造的细节）。自己审自己，等于没审。

所以这里做的是**换一个模型来审**：
  · 出答的模型（比如 4B）写答案；
  · 审校的模型（**另一个**，优先选跟出答不同的模型）只看"问题 + 答案"，
    回答三选一：一致 / 不一致 / 无法判断，并给一句理由；
  · 判"不一致"→ 在答案前面标注（**不改正文**），把判断权交回用户。

【什么时候才审】审校要花一次模型调用，不能每句都审。只在"高风险"时审：
  ① 答案里有 ≥2 处可核查的断言（数字/日期/链接/路径）——`core/answer_gate` 已经挑好了；
  ② 或者问题本身涉及钱/医疗/法律/时间承诺这些"错了要出事"的领域。
  其余情况不审，省时间。

【判据的边界，写在前面】
  两个模型一致，**不等于**内容就对（可能一起错，尤其同一个基座的不同量化）。
  所以本模块的输出永远叫"另一模型也这么说"，不叫"已核实"。
  ——措辞上不能越界，这是本项目的规矩。

【失败即跳过】审校超时/连不上/返回看不懂 → 一律当作"无法判断"，绝不让它拖慢或拖垮回答。
"""
import json
import logging
import os
import re
import time

import requests

LOG = logging.getLogger(__name__)

# 高风险领域词（错了代价大的）
_RISKY = ("多少钱", "价格", "费用", "报税", "税", "利率", "汇率", "投资", "股票", "基金",
          "药", "剂量", "吃什么药", "病历", "症状", "诊断", "手术",
          "法律", "合同", "起诉", "律师", "条款", "违法", "判几年",
          "几点", "截止", "deadline", "什么时候开始", "什么时候结束", "有效期")

_PROMPT = (
    "你是审校员。下面是一个 AI 对用户问题的回答。请只做一件事：\n"
    "判断回答里有没有**看起来具体、但无法从问题本身推出的编造细节**"
    "（例如凭空给出的比分、日期、场馆、人名、链接、数字）。\n"
    "第一行只回三个词之一：一致 / 不一致 / 无法判断\n"
    "第二行用一句话说明理由（不超过 30 字）。\n\n"
    "【用户问题】%s\n\n【回答】%s\n"
)


def _base_url():
    try:
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "xiaojiao_control.json")
        c = json.load(open(p, encoding="utf-8"))
        b = str(((c.get("brain") or {}).get("api") or {}).get("base_url") or "").rstrip("/")
        if b:
            return b if b.endswith("/v1") else b + "/v1"
    except Exception as e:      # noqa: silent-ok — 读不到配置就用默认端口
        LOG.debug("双模型审校：读配置失败（用默认）：%s", e)
    return "http://127.0.0.1:9292/v1"


def _enabled():
    """开关：`routing.dual_check`（默认开）。关掉就完全不审，省一次模型调用。"""
    try:
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "xiaojiao_control.json")
        c = json.load(open(p, encoding="utf-8"))
        v = (c.get("routing") or {}).get("dual_check")
        return True if v is None else bool(v)
    except Exception:      # noqa: silent-ok
        return True


def is_risky(question, answer, gate_result=None):
    """这一轮值得花一次模型调用去审吗？返回 (bool, 理由)。

    【为什么门槛要抬到 3 处断言】第一版是 2 处，实测**天气答案**（气温 + 湿度 = 2 处）
    就触发了审校，每条多花 20~30 秒（评测里"太慢 >30s"就是这么来的）。
    审校的价值只在"细节多到人一眼看不出来"的时候，2 处不够。
    """
    q = str(question or "")
    a = str(answer or "")
    if len(a.strip()) < 12:                 # 太短的废话不审
        return False, "回答太短"
    n_claims = int((gate_result or {}).get("claims") or 0)
    if n_claims >= 3:
        return True, "答案里有 %d 处可核查的断言" % n_claims
    hit = [w for w in _RISKY if w in q]
    if hit:
        return True, "问题涉及高风险领域（%s）" % hit[0]
    return False, "普通回答，不审（省一次模型调用）"


def _available_models():
    try:
        r = requests.get(_base_url() + "/models", timeout=5)
        if r.status_code == 200:
            return [str((m or {}).get("id") or "") for m in (r.json().get("data") or [])]
    except Exception:      # noqa: silent-ok
        pass
    return []


def _pick_reviewer(answer_model=""):
    """挑审校模型：**优先挑跟出答不同的**，都不同就用池子里第一个。"""
    ids = _available_models()
    if not ids:
        return ""
    others = [m for m in ids if m and m != answer_model]
    return (others or ids)[0]


def review(question, answer, answer_model="", timeout=12):
    """审一遍。返回 dict：{"verdict": same/diff/unknown, "why": …, "model": …, "sec": …}

    任何失败都返回 unknown（不抛异常、不阻塞）。
    """
    if not _enabled():
        return {"verdict": "unknown", "why": "审校开关关着", "model": "", "sec": 0.0}
    model = _pick_reviewer(answer_model)
    if not model:
        return {"verdict": "unknown", "why": "拿不到模型列表", "model": "", "sec": 0.0}
    t0 = time.time()
    try:
        r = requests.post(_base_url() + "/chat/completions", json={
            "model": model,
            "messages": [{"role": "user", "content": _PROMPT % (str(question)[:800],
                                                                str(answer)[:2500])}],
            "max_tokens": 90, "temperature": 0.0,
        }, timeout=timeout)
        dt = time.time() - t0
        if r.status_code != 200:
            return {"verdict": "unknown", "why": "HTTP %s" % r.status_code, "model": model, "sec": dt}
        txt = ((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        low = txt.strip()
        if "不一致" in low[:20]:
            v = "diff"
        elif "一致" in low[:20]:
            v = "same"
        else:
            v = "unknown"
        why = re.sub(r"\s+", " ", low).strip()[:60]
        LOG.info("双模型审校：%s → %s ｜ %s（%.1fs）", model, v, why[:40], dt)
        return {"verdict": v, "why": why, "model": model, "sec": dt}
    except Exception as e:      # noqa: silent-ok — 审校失败绝不影响回答
        return {"verdict": "unknown", "why": "%s: %s" % (type(e).__name__, str(e)[:60]),
                "model": model, "sec": time.time() - t0}


def annotate(answer, res):
    """把审校结果折成一句标注（正文不动）。一致 → 不加任何东西（别自我加戏）。"""
    v = (res or {}).get("verdict")
    if v == "diff":
        return ("⚠️ **另一个模型审这一条时认为有不一致**（%s）。"
                "下面照原样给你，请重点核实它指出的地方。\n\n" % (res.get("why") or "没说理由")
                + str(answer or ""))
    return answer
