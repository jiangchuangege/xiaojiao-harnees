# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 技能库（2026-10-27）

【它是什么】一次**成功的多步任务**（用了两个以上工具、且有结果）会被固化成一条「技能」：
    问题 → 工具序列（名称 + 关键参数）→ 结果要点 → 耗时
  下次遇到同类问题时，载体可以**直接照这条序列去调工具**，不必让模型重新试错。

【和"记忆"有什么区别（这张表决定它该不该单独存在）】
    · `core/memory_vec.py`：记**用户与它说过什么**，按语义相似检索，用来"懂你"；
    · `core/experience.py`：记**做事会在哪栽**，按 kind+关键词检索，用来"别再犯"；
    · 本模块：记**做成了的事是怎么做的**，按问题相似度检索，用来"直接照着做"。
  三者检索口径不同、用途不同，混在一起只会互相污染。

【为什么"复用工具序列"是真提升】
  实测过的痛点都在"选工具 + 拼参数"这一步：问天气时它去搜网页、爬书时它去截图、
  写代码时它挑了答错的那个模型。这些错误**每次都要重新犯**。
  把"上次怎么做的"变成可检索的序列，等于把它自己踩出来的正确路径存下来 ——
  这是"越用越快"的物理来源，不是玄学。

【判据（宁可少记，也不记脏）】
  · 只记**至少 2 个工具**的任务（单工具叫"调一下"，不值得叫技能）；
  · 只记**没有失败痕迹**的（参数里有 error / 返回含 Traceback 都不记）；
  · 同一问题**只留最近一条**（问题归一化后作键），避免同一件事堆成几十条；
  · 落盘 append-only，读时去重 —— 和本项目其它记录一样，坏了只坏一条。
"""
import io
import json
import logging
import os
import re
import time

LOG = logging.getLogger(__name__)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PATH = os.path.join(_ROOT, "logs", "skills.jsonl")
_MAX_LINES = 2000

# 这些工具名出现在序列里 → 说明这一轮其实是"失败/兜底"路径，不固化
_BAD_MARKS = ("error", "traceback", "失败", "不可用", "没有装载", "未知工具")

# 外壳工具：它们只表示"把活交出去了"，本身不是做法，不能当技能序列存
_WRAPPER_TOOLS = ("task_start",)


def _ensure():
    d = os.path.dirname(_PATH)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)


def _norm_q(s):
    """问题归一化：去掉空白与标点，用于"同一件事"的判定键。"""
    t = re.sub(r"[\s，。！？；：、,.!?;:\"'（）()【】\[\]]", "", str(s or "")).lower()
    return t[:80]


def _rotate():
    try:
        if not os.path.isfile(_PATH):
            return
        with io.open(_PATH, encoding="utf-8") as f:
            n = sum(1 for _ in f)
        if n <= _MAX_LINES:
            return
        bak = _PATH + ".%d" % int(time.time())
        os.rename(_PATH, bak)
        LOG.info("技能库滚动：%d 行 → 备份 %s", n, os.path.basename(bak))
    except Exception as e:      # noqa: silent-ok — 滚动失败不影响记录
        LOG.debug("技能库滚动失败（忽略）：%s", e)


def _tool_steps(tool_trace):
    """从 tool_trace 里抽出「工具序列」：名称 + 关键参数（去掉大字段）。"""
    steps = []
    for t in (tool_trace or []):
        t = t or {}
        name = str(t.get("tool") or "").strip()
        if not name:
            continue
        res = str(t.get("result") or "")
        if any(mk in res.lower() for mk in _BAD_MARKS):
            return [], "有工具返回失败痕迹（%s）" % name
        args = t.get("args") or {}
        keep = {}
        for k, v in (list(args.items()) if isinstance(args, dict) else []):
            sv = str(v)
            if len(sv) <= 60:                       # 长参数（整页正文之类）不入库
                keep[str(k)] = sv
        steps.append({"tool": name, "args": keep})
    return steps, ""


def remember_task(question, tool_trace, answer="", seconds=0.0):
    """一次任务成功后调用。返回 (是否记下, 说明)。

    调用点在载体出口（`agent_run` 末尾）：工具 ≥2 且没有失败痕迹才记。
    """
    try:
        steps, why = _tool_steps(tool_trace)
        if not steps:
            return False, why or "没有工具调用，不算技能"
        if len(steps) < 2:
            return False, "只用了 1 个工具（%s），不值得固化成技能" % steps[0]["tool"]
        # 【2026-10-28 加】`task_start` 是**外壳**，不是做法。
        #   实测：live 上同一个目标存了两条技能 —— 一条是任务自己固化的真实序列
        #   （get → write_file），另一条是出口处把 `task_start` 当步骤存进去的
        #   （序列 = [task_start]，照它做只会再开一个任务）。外壳不入库。
        if any(s["tool"] in _WRAPPER_TOOLS for s in steps):
            return False, "这一轮只是把活交给了任务（%s），真实步骤由任务自己固化" % (
                ", ".join(sorted({s["tool"] for s in steps if s["tool"] in _WRAPPER_TOOLS})))
        q = str(question or "").strip()
        if not q:
            return False, "没有原话，存了也没法按问题召回"
        _ensure()
        _rotate()
        key = _norm_q(q)
        row = {"key": key, "question": q[:160],
               "steps": steps[:12], "n_steps": len(steps),
               "answer_head": str(answer or "")[:160],
               "sec": round(float(seconds or 0), 1),
               "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        with io.open(_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        LOG.info("技能库：固化一条技能（%d 步：%s）｜%s", len(steps),
                 " → ".join(s["tool"] for s in steps[:4]), q[:30])
        return True, "已固化（%d 步）" % len(steps)
    except Exception as e:      # noqa: silent-ok — 记技能失败不许影响回答
        LOG.debug("技能库：固化失败（忽略）：%s", e)
        return False, "固化出错：%s" % type(e).__name__


def load(limit=600):
    out = []
    try:
        if not os.path.isfile(_PATH):
            return out
        for ln in io.open(_PATH, encoding="utf-8").read().split("\n"):
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except Exception:      # noqa: silent-ok — 坏一行跳过
                continue
    except Exception as e:      # noqa: silent-ok
        LOG.debug("技能库：读取失败（忽略）：%s", e)
    return out[-limit:]


def _tokens(s):
    t = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", str(s or ""))
    return set(t[i:i + 2] for i in range(len(t) - 1))


def recall(question, min_score=0.5):
    """按问题相似度召回一条技能。返回技能 dict 或 None。

    判据：2 字词覆盖率 ≥ min_score（默认 0.5），且取**最近**的一条。
    宁可召不回，也不拿错的技能去套 —— 套错的代价比重新试错大得多。
    """
    try:
        want = _tokens(question)
        if not want:
            return None
        best, best_score = None, 0.0
        for row in reversed(load()):
            ot = _tokens(row.get("question"))
            if not ot:
                continue
            score = len(want & ot) / float(len(want))
            if score >= min_score and score > best_score:
                best, best_score = row, score
        if best:
            best = dict(best)
            best["score"] = round(best_score, 2)
        return best
    except Exception as e:      # noqa: silent-ok — 召不回就当没有
        LOG.debug("技能库：召回失败（忽略）：%s", e)
        return None


def list_skills(limit=10):
    """最近的技能（去重：同一问题只留最近一条）。"""
    seen, out = set(), []
    for row in reversed(load()):
        k = row.get("key") or ""
        if k in seen:
            continue
        seen.add(k)
        out.append(row)
        if len(out) >= limit:
            break
    return out


def stats():
    rows = load(limit=5000)
    seen = {r.get("key") for r in rows}
    by_tool = {}
    for r in rows:
        for s in (r.get("steps") or []):
            by_tool[s.get("tool")] = by_tool.get(s.get("tool"), 0) + 1
    top = sorted(by_tool.items(), key=lambda x: -x[1])[:8]
    return {"total": len(rows), "unique_questions": len(seen),
            "avg_steps": round(sum(int(r.get("n_steps") or 0) for r in rows) / len(rows), 1)
            if rows else 0,
            "top_tools": top, "path": _PATH}


def plan_for(question):
    """给载体用：这条问题有没有现成的工具序列？返回中文说明（没学到就空串）。"""
    s = recall(question)
    if not s:
        return ""
    seq = " → ".join(x.get("tool") or "?" for x in (s.get("steps") or []))
    return ("（技能库召回：上次同类问题用了这条序列「%s」，%d 步，%.1f 秒。可以直接照它做。）"
            % (seq, int(s.get("n_steps") or 0), float(s.get("sec") or 0)))
