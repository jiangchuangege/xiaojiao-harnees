# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 切换手段链（元认知 2：没把握时**换手段**，不是认输）

【这段为什么这么设计 —— 这是"元认知"最容易做歪的地方】
    自评判出 C（没把握）之后，最容易写出来的出口是"对不起，我不知道"。
    那是**把模型的短板直接翻译成用户看到的失败**：用户问一句，得到的是一句道歉，
    问题还在原地。载体的价值恰恰在于"模型不行的时候，还有别的办法"：
        换个工具试 → 换个检索策略试 → 换个表达方式试 → 反过来问一遍看是否自相矛盾。
    只有**全都试过**之后，才允许如实说"这几条路我都走了，还是没拿到" ——
    那时候的"不知道"是**调查报告**，不是认输。

【为什么顺序是这样（不是随便排的）】
    1. 换工具      —— 最可能直接拿到外部事实，代价是调一次工具；
    2. 换检索策略  —— 本地没给到就换联网，已联网就换检索词（最便宜的一手）；
    3. 换表达方式  —— 前两手都没料时，让模型"只说确定的部分"，把答案收紧；
    4. 反转问法    —— 最后一道自检：换个方向问一次，两次矛盾就说明确实不确定。
    代价从小到大、把握从高到低，所以**逐级**试，任一级拿到可用结果就停。

【为什么"判有没有变好"必须由载体做，而不是问模型"你这次答好了吗"】
    模型的自我评价和它的答案一样是概率输出 —— 问它"这次好点没"，它会说好。
    所以这里用**可数的事实**当判据（见 `judge`）：具体信息（数字/日期/专名/链接）更多、
    认输措辞更少、与素材重合更多，才算变好。数得出来的才算，数不出来的不算。

【去掉会怎样】
    C 档沦为一句道歉；用户看到的仍然是"问啥啥不知道"，只是多了一层礼貌。
"""
import hashlib
import re
import time

__all__ = ["MEANS", "plan", "next_step", "judge", "surrender", "reverse_question",
           "run_chain", "steps_text"]

# 手段清单：key 是给调用方派活用的，name/how 是给人看的话术（日志、复盘、文档）
MEANS = (
    {"key": "tool", "name": "换工具",
     "how": "换一个工具再试：载体挑出与这个问题最相关的已注册工具，真的调一次，把结果当素材"},
    {"key": "recall", "name": "换检索策略",
     "how": "换检索策略再试：本地记忆没给到就换联网；已经联网了就换检索词重查一遍"},
    {"key": "rephrase", "name": "换表达方式",
     "how": "换表达方式再试：让大脑只讲它有把握的部分，换个组织方式、不要客套"},
    {"key": "invert", "name": "反转问法",
     "how": "反转问法再试：问一个方向相反的问题，看两次答案是否互相矛盾"},
)
_KEYS = tuple(m["key"] for m in MEANS)
_BY_KEY = {m["key"]: m for m in MEANS}

# 认输/道歉措辞：这些词出现在答案里本身不是错（该说就得说），
# 但它们**不能是这一轮的终点** —— C 档必须先走完手段链（见模块文档）。
_SURRENDER = ("对不起", "抱歉", "很遗憾", "我无法回答", "我无法提供", "我不能回答",
              "我不知道", "我不清楚", "我没办法", "我帮不了", "无法回答这个问题",
              "没有相关信息", "我也不确定", "无法确定")

_NUM = re.compile(r"\d")
_DATE = re.compile(r"\d{4}\s*[-/年]\s*\d{1,2}|\d{1,2}\s*月\s*\d{1,2}\s*日|\d{1,2}:\d{2}")
_URL = re.compile(r"https?://")
# "专名"的粗判据：连续 2~8 个汉字且**不是**常见虚词开头 —— 只用来看"哪次说得更具体"
_PROPERISH = re.compile(r"[\u4e00-\u9fff]{2,8}")
_VAGUE = ("可能", "也许", "大概", "应该", "一般来说", "通常", "众所周知", "总之",
          "简单来说", "在我看来")


def plan(question="", used=(), tried=(), limit=None):
    """还没试过的手段（按代价从小到大）。`used`=这一轮流程已经用掉的，`tried`=试过没成的。"""
    skip = set(str(x) for x in list(used or ()) + list(tried or ()))
    out = [dict(m, why=_why_for(m["key"], question)) for m in MEANS if m["key"] not in skip]
    return out[:int(limit)] if limit else out


def next_step(question="", used=(), tried=()):
    """下一手该试什么；全试过返回 None（**这时候才允许认输**）。"""
    p = plan(question, used=used, tried=tried, limit=1)
    return p[0] if p else None


def _why_for(key, question):
    q = str(question or "")[:24]
    return {
        "tool": "「%s」这类问题常常要靠外部事实，先看有没有能直接查的工具" % q,
        "recall": "本地记忆与联网都可能漏，换一种检索策略再捞一次",
        "rephrase": "前面两手都没给到料 → 让大脑把范围收窄到它有把握的部分",
        "invert": "最后一道自检：反过来问一次，两次互相矛盾就说明确实不确定",
    }.get(key, "")


def surrender(text):
    """这段文本是不是"认输/道歉"型的兜底话（要靠它挡住"一句抱歉交差"）。"""
    t = str(text or "").strip()
    if not t:
        return True
    return any(w in t for w in _SURRENDER)


def _facts(text):
    """可数的"具体程度"：数字 / 日期 / 链接 / 实体词 / 长度。**只用数得出来的东西判**。"""
    t = str(text or "")
    words = _PROPERISH.findall(t)
    vague = sum(t.count(w) for w in _VAGUE)
    return {
        "len": len(t),
        "num": len(_NUM.findall(t)),
        "date": len(_DATE.findall(t)),
        "url": len(_URL.findall(t)),
        "words": len(set(words)),
        "vague": vague,
    }


def judge(old, new, material=""):
    """载体判据：**新答案是不是比旧答案更值得给用户**。返回 `{"better", "why"}`。

    判据全部可核对（不用问模型"你好点没"）：
      ① 空的/纯认输的 → 一定不算变好；
      ② 与素材（检索原文/工具结果）重合的字更多 → 更有依据；
      ③ 具体信息（数字/日期/链接/实体词）更多 → 更实；
      ④ 含糊措辞（可能/大概/一般来说）更多 → 更虚。
    ①②③④ 依次比。全平就判"没变好" —— 平局时**不动**（换一手没改善就不该换）。
    """
    o, n = str(old or ""), str(new or "")
    if not n.strip():
        return {"better": False, "why": "新答案是空的"}
    if surrender(n) and not surrender(o):
        return {"better": False, "why": "新答案退化成认输/道歉，比原来更差"}
    m = str(material or "")
    if m.strip():
        # 素材重合度：用素材里的汉字 2-gram 在新答案里的命中数（可数、可比）
        grams = set()
        mm = re.sub(r"\s+", "", m)
        for i in range(len(mm) - 1):
            if "\u4e00" <= mm[i] <= "\u9fff":
                grams.add(mm[i:i + 2])
        if grams:
            ho = sum(1 for g in grams if g in o)
            hn = sum(1 for g in grams if g in n)
            if hn > ho:
                return {"better": True, "why": "与检索到的素材重合更多（%d > %d）" % (hn, ho)}
            if hn < ho:
                return {"better": False, "why": "与素材重合反而变少（%d < %d）" % (hn, ho)}
    fo, fn = _facts(o), _facts(n)
    so = fo["num"] + fo["date"] * 2 + fo["url"] * 2 + fo["words"] * 0.1
    sn = fn["num"] + fn["date"] * 2 + fn["url"] * 2 + fn["words"] * 0.1
    if sn > so:
        return {"better": True, "why": "新答案更具体（具体度 %.1f > %.1f）" % (sn, so)}
    if sn < so:
        return {"better": False, "why": "新答案更笼统（具体度 %.1f < %.1f）" % (sn, so)}
    if fn["vague"] < fo["vague"]:
        return {"better": True, "why": "含糊措辞变少（%d → %d）" % (fo["vague"], fn["vague"])}
    return {"better": False, "why": "没看出来更好（平局不换）"}


def reverse_question(question):
    """把问题**反过来**问一遍（载体规则，不花模型算力）。

    为什么最后才用它：反转问法拿到的不是答案，而是"两次是否自相矛盾"这个信号 ——
    它是**校验**，不是出路。所以要放在"换工具/换检索/换表达"都没成之后。
    """
    q = str(question or "").strip()
    if not q:
        return ""
    m = re.match(r"^为什么(.+)$", q)
    if m:
        return "如果不成立（也就是%s**不**发生），会是什么样？" % m.group(1)[:60]
    if re.search(r"(是不是|吗|对不对|有没有)\s*[？?]?$", q):
        return "%s（反过来：如果答案是否定的，会是什么情况？）" % q
    return "换个相反的角度看：%s —— 反面/对立面的情形是什么样的？" % q[:80]


def steps_text(steps):
    """把走过的手段链整理成一句人话（日志与"如实交代"都用它）。"""
    if not steps:
        return ""
    return "；".join("%s：%s" % (s.get("name") or s.get("key"),
                                 "拿到料" if s.get("ok") else (s.get("note") or "没拿到"))
                     for s in steps)


def run_chain(question, executors, used=(), tried=(), max_steps=2, material="",
              old_answer="", on_step=None, remember_fn=None):
    """**逐级**试切换手段，任一手变好就停。

    `executors`：`{手段key: callable(step) -> {"ok": bool, "note": str, "answer": str,
    "material": str}}`。**只有调用方知道怎么真的调工具/检索/模型**，所以手段由调用方注入；
    这个函数只负责"按什么顺序试、试到什么时候停、怎么判好坏、怎么记下来"。

    返回 `{"answer", "steps", "tried", "improved", "stopped_why"}`：
      · `answer`    最终该给用户的答案（没有任何一手变好时是 `old_answer` 原样）
      · `steps`     每一手的真实记录（自测取证用，不许事后编）
      · `improved`  是否真的被某一手改善了（False 时调用方**必须如实说**试过哪些手段）
    """
    tried = [str(x) for x in (tried or [])]
    steps = []
    cur = str(old_answer or "")
    cur_material = str(material or "")
    improved = False
    stopped = "没有下一手了"
    budget = max(0, int(max_steps))
    if budget <= 0:
        return {"answer": cur, "steps": steps, "tried": tried, "improved": False,
                "stopped_why": "本轮不切换（额度为 0）"}
    while budget > 0:
        step = next_step(question, used=used, tried=tried)
        if step is None:
            stopped = "四种手段都试过了，仍然没拿到"
            break
        tried.append(step["key"])
        budget -= 1
        fn = (executors or {}).get(step["key"])
        rec = {"key": step["key"], "name": step["name"], "ok": False, "note": "",
               "ms": 0.0, "better": False, "why": ""}
        t0 = time.time()
        if not callable(fn):
            rec["note"] = "这条路当前不可用（没有可执行的手段）"
        else:
            try:
                out = fn(step) or {}
            except Exception as e:      # noqa: silent-ok — 一手失败就换下一手，绝不中断整轮回答
                out = {"ok": False, "note": "这一手抛异常：%s" % type(e).__name__}
            rec["ok"] = bool(out.get("ok"))
            rec["note"] = str(out.get("note") or "")[:120]
            new = str(out.get("answer") or "")
            new_material = str(out.get("material") or "")
            if rec["ok"] and new.strip():
                v = judge(cur, new, material=new_material or cur_material)
                rec["better"], rec["why"] = bool(v["better"]), v["why"]
                if v["better"]:
                    cur, improved = new, True
                    if new_material:
                        cur_material = new_material
        rec["ms"] = round((time.time() - t0) * 1000.0, 1)
        steps.append(rec)
        if on_step:
            try:
                on_step(rec)
            except Exception:      # noqa: silent-ok — 回调只是取证的锦上添花
                pass
        if improved:
            stopped = "第 %d 手（%s）拿到了更好的结果" % (len(steps), rec["name"])
            break
    # 方法经验进精神记忆库：**记的是"这类问题换这一手有没有用"**，不是答案原文
    if remember_fn is not None and steps:
        try:
            for s in steps:
                remember_fn(s, question)
        except Exception:      # noqa: silent-ok — 记不上不影响这一轮的答案
            pass
    return {"answer": cur, "steps": steps, "tried": tried, "improved": improved,
            "stopped_why": stopped}


def method_memory_text(step, question=""):
    """把一次手段尝试提炼成一句"方法"（进精神记忆库的**方法**库，不是答案库）。"""
    key = step.get("key") or "?"
    name = _BY_KEY.get(key, {}).get("name") or key
    q = str(question or "").strip()[:40]
    if step.get("ok"):
        return "遇到「%s」这类问题时，「%s」有效（%s）" % (q, name, (step.get("why") or "")[:40])
    return "遇到「%s」这类问题时，「%s」没拿到东西（%s）" % (q, name, (step.get("note") or "")[:40])


def mem_id(step, question=""):
    """方法经验的稳定 id（同一手段+同类问题不重复占位）。"""
    return hashlib.md5(("%s|%s" % (step.get("key"), str(question)[:40])).encode("utf-8")).hexdigest()[:12]
