# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 难度路由（2026-10-17）

【为什么要它】本项目一直是"所有请求都打同一个模型"。但实测（llama-swap 上四个模型，
同一台机器、同一句话）说明**这不是最优**，而且"换更大的模型"根本不等于"更强"：

    | 模型 | 闲聊 | 小数比较（3.11 vs 3.9） | 写快排 |
    | --- | --- | --- | --- |
    | xiaojiao（4B，默认） | 1.2s | 0.7s **答对** | 2.7s |
    | qwopus3.5-4b-coder | 10.9s | 0.6s 答对 | **1.8s** |
    | coder | 28.4s | 1.0s **答错** | 4.9s |
    | deepseek-v4 | 53.6s | 29.6s 答对 | 2.5s |

    看清楚两件事：
      ① **"大模型"在简单题上更贵、还可能更错**（coder 把 3.11 和 3.9 比反了）；
      ② llama-swap 切模型要**重新加载**，冷启动 20~50 秒 —— 所以"每句话都智能挑模型"
         会把时间全花在换模型上。

【于是本模块的立场】
  · 默认就用最快的那个（`xiaojiao`），不折腾；
  · 只在**明确能占到大便宜**的时候换档：写代码 → coder 档（实测快 0.9s）、
    重推理/长文 → strong 档（只在"值得等 30 秒"的题上）；
  · **粘性**：同一个档 120 秒内不换模型，避免来回切导致的反复冷启动；
  · 目标模型不在 `/v1/models` 里 → 立刻退回 fast，绝不把请求发进 404；
  · 每次决策都记一句日志（哪个档、为什么、用了哪个模型），可复盘、可评测。

【边界】本模块**只决定"用哪个模型"**，不改工具、不改提示词、不改记忆。
""" 
import json
import logging
import os
import re
import time

import requests

LOG = logging.getLogger(__name__)

# 档位 → 候选模型（按优先级；第一个存在的就用）。名字与本机 llama-swap 的 id 对齐。
# 【每档只放**真正属于这一档**的模型】第一版把 fast 的 xiaojiao 也塞进 code 档的备选里，
# 结果"要 code 档但只有 xiaojiao"时返回的 tier 还是 code（标注与事实不符）。
# 跨档兜底交给 route() 里"该档全无 → 退 fast"那一步，语义才干净。
TIERS = {
    "fast": ("xiaojiao", "qwopus3.5-4b-coder-mtp-q5_k_m.gguf", "coder", "deepseek-v4"),
    "code": ("qwopus3.5-4b-coder-mtp-q5_k_m.gguf", "coder"),
    "strong": ("deepseek-v4", "coder"),
}

# 判据词表（字面判据，不靠模型自觉；用户实测过"换个说法就失效"的痛，所以宁可宽一点）
_CODE_HINTS = ("写代码", "写个函数", "写一个函数", "实现一个", "实现个", "帮我写", "改代码", "重构",
               "报错", "traceback", "异常", "正则", "sql", "python", "javascript", "typescript",
               "java ", "c++", "golang", "rust", "bash", "脚本", "函数", "接口", "单元测试",
               "排序", "算法", "bug", "调试", "debug", "编译", "依赖", "dockerfile", "git ")
_STRONG_HINTS = ("推理", "证明", "为什么", "分析一下", "对比", "权衡", "方案", "设计一个",
                 "架构", "规划", "评估", "推算", "多步", "分步骤", "详细说明", "深入",
                 "论文", "推导", "复杂", "取舍", "风险", "利弊")
_HEAVY_LEN = 120          # 超过这么多字，默认当"重活"

STATE = {"tier": "fast", "model": "", "at": 0.0, "switches": []}
_STICKY_S = 120.0         # 同一档的粘性时间：这段时间内不再换模型
# 【换档冷却】第一版粘性只对"同档"生效 → 一句闲聊就把 code 档切回 fast，下一句代码又切回去，
# 每切一次 llama-swap 就要重新加载模型（实测冷启动 20~50 秒），越"智能"越慢。
# 所以换档本身也要有冷却：距上次换档不到 _SWITCH_S 秒，**不论目标档是什么都沿用当前模型**。
_SWITCH_S = 60.0
# 【切换预算】评测当场抓到的代价：连续跑 14 条不同任务 → 档位反复切换 →
# 4B 被反复卸载重载，问天气从 8.8 秒变成 99 秒。所以再加一道硬预算：
# **_BUDGET_WINDOW 秒内最多切 _BUDGET_MAX 次**，超了就老实待在当前档。
_BUDGET_WINDOW = 180.0
_BUDGET_MAX = 2
_MODELS_CACHE = {"ids": set(), "at": 0.0}
_MODELS_TTL = 60.0


def _base_url():
    """llama-swap / 大脑服务的根地址（从控制文件里读，读不到就用默认端口）。"""
    try:
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "xiaojiao_control.json")
        c = json.load(open(p, encoding="utf-8"))
        api = (c.get("brain") or {}).get("api") or {}
        b = str(api.get("base_url") or "").rstrip("/")
        if b:
            return b[:-3] if b.endswith("/v1") else b
    except Exception as e:      # noqa: silent-ok — 读不到配置就用默认
        LOG.debug("难度路由：读配置失败（用默认 9292）：%s", e)
    return "http://127.0.0.1:9292"


def available_models(force=False):
    """这台机器上真正可用的模型 id 集合（带 60 秒缓存；拿不到就返回空集）。"""
    now = time.time()
    if not force and _MODELS_CACHE["ids"] and (now - _MODELS_CACHE["at"]) <= _MODELS_TTL:
        return _MODELS_CACHE["ids"]
    try:
        r = requests.get(_base_url() + "/v1/models", timeout=5)
        if r.status_code == 200:
            ids = {str((m or {}).get("id") or "") for m in (r.json().get("data") or [])}
            _MODELS_CACHE.update({"ids": ids, "at": now})
            return ids
    except Exception as e:      # noqa: silent-ok — 探不到就按"未知"处理（后面会退回 fast）
        LOG.info("难度路由：拿不到模型列表（%s）→ 本轮不换档", type(e).__name__)
    return set()


def pick_tier(text, intent=""):
    """这一句该走哪个档？返回 (tier, 理由)。

    判据是**字面 + 长度**，不是问模型自己 —— 因为这一步要在"调用模型之前"完成，
    而且换档决策必须稳定可复现（评测要能钉住它）。
    """
    t = str(text or "")
    low = t.lower()
    n = len(t)
    if any(k in low for k in _CODE_HINTS):
        return "code", "命中代码词"
    if any(k in low for k in _STRONG_HINTS) and n >= 20:
        return "strong", "命中重推理词且题目够长"
    if n >= _HEAVY_LEN:
        return "strong", "题目很长（%d 字）" % n
    if str(intent or "") in ("code", "diagram"):
        return "code", "意图=%s" % intent
    return "fast", "普通问题"


def route(text, intent="", now=None):
    """给这一句挑模型。返回 (model_id 或 "", tier, 理由)。

    换档规则（宁可少换，不能乱换）：
      ① 目标档和当前档不同 **且** 距上次换档已超过粘性时间 → 才换；
      ② 目标档的首选模型不在可用列表里 → 退到该档的备选 → 再退 fast；
      ③ 一个可用模型都没探到（服务没起/列表拿不到）→ 返回空，调用方按原样走。
    """
    now = time.time() if now is None else now
    tier, why = pick_tier(text, intent)

    ids = available_models()
    if not ids:
        return "", tier, "%s（但没探到可用模型列表，不换档）" % why

    # 粘性 / 换档冷却：
    #   · **升档**（fast→code/strong）**立即生效** —— 活儿变重了，值得付一次加载代价；
    #     第一版把升档也压住了，实测表现是"第一次写代码也不切模型"，等于永远让 4B 干重活。
    #   · **降档**（strong/code→fast）要等冷却 —— 降回去不急，别来回切导致反复冷启动。
    #   · 同档 → 无条件沿用。
    _cur_model = str(STATE.get("model") or "")
    _cur_tier = str(STATE.get("tier") or "")
    _since = now - float(STATE.get("at") or 0)
    if _cur_model:
        _w = {"fast": 0, "code": 1, "strong": 2}
        _upgrade = _w.get(tier, 0) > _w.get(_cur_tier, 0)
        if _cur_tier == tier:
            return _cur_model, _cur_tier, "%s（粘性沿用）" % why
        if _upgrade:
            pass                      # 升档放行，往下走正常选模型
        elif _since <= _SWITCH_S:
            return _cur_model, _cur_tier, ("%s（降档冷却中 %.0fs/%.0fs，先沿用 %s 档）"
                                           % (why, _since, _SWITCH_S, _cur_tier))

    model = ""
    for cand in TIERS.get(tier, ()):
        if cand in ids:
            model = cand
            break
    if not model:                       # 该档一个都没有 → 退 fast
        for cand in TIERS["fast"]:
            if cand in ids:
                model = cand
                break
        if model:
            why += "（%s 档的模型都不在，退回 fast）" % tier
            tier = "fast"
    if not model:
        return "", tier, "%s（没有可用模型）" % why
    # 切换预算：窗口内切太多次就老实待着（每次切换 = 一次模型重载）
    try:
        _sw = [t for t in (STATE.get("switches") or []) if (now - float(t)) <= _BUDGET_WINDOW]
        STATE["switches"] = _sw
        if _cur_model and len(_sw) >= _BUDGET_MAX:
            return _cur_model, _cur_tier, ("%s（%d 秒内已切 %d 次，先不切，避免反复重载）"
                                          % (why, int(_BUDGET_WINDOW), len(_sw)))
        _sw.append(now)
    except Exception:      # noqa: silent-ok — 记不了预算就不限制
        pass
    STATE.update({"tier": tier, "model": model, "at": now})
    return model, tier, why


def current():
    """给界面/自检看：现在用的是哪档、哪模型、多久前定的。"""
    return {"tier": STATE.get("tier"), "model": STATE.get("model"),
            "age_s": round(time.time() - float(STATE.get("at") or 0), 1) if STATE.get("at") else None,
            "available": sorted(available_models())}
