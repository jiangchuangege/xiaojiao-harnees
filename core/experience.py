# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 经验库（2026-10-27）

【它是什么】小焦自己踩过的坑，**落盘**，下次生成/诊断前先查一遍。

  一条经验长这样：
    {"kind": "forge_fail", "need": "把中文数字转成阿拉伯数字",
     "stage": "static", "why": "语法错误：第 107 行 '(' was never closed",
     "lesson": "生成时 max_tokens 不够会被截断，先让它写短一点",
     "at": "2026-10-27T17:33:00", "ok": false}

  两类来源：
    · `forge_*`：能力自增长的成与败（生成→检查→沙箱哪一关断了、为什么）；
    · `evolve_*`：诊断结论（评测/体检的红点，以及后来靠什么修好的）。

【为什么要单独一个库，而不是塞进对话记忆】
  对话记忆（`core/memory_vec.py`）记的是"用户与它说了什么"，检索按语义相似；
  经验库记的是"做这类事会在哪里栽"，检索按 **kind + 关键词**，要的是**精确命中同一类问题**。
  两者混在一起，生成插件时会检索回一堆闲聊，等于没有。

【为什么必须落盘】进程重启就忘 = 永远在学习的第一天。这个项目吃过这个亏
  （`plugins/rea.py` 的启动器验证、天气的多城市记忆，都是"这轮修好、下轮重犯"）。

【只加不改】经验库是 append-only 的 JSONL：追加成本极低、坏了也只坏一条。
  读的时候按需去重（同一 kind + 同一 why 只取最近一条），不做原地修改。
"""
import io
import json
import logging
import os
import re
import time

LOG = logging.getLogger(__name__)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PATH = os.path.join(_ROOT, "logs", "experience.jsonl")
_MAX_LINES = 4000          # 超过就滚动（保留最近的；不删用户数据：滚动到 experience.1.jsonl）


def _ensure():
    d = os.path.dirname(_PATH)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)


def _rotate_if_needed():
    """太长就滚动：当前文件改名成 .1，新的从头写。**不删**（本项目只加不删）。"""
    try:
        if not os.path.isfile(_PATH):
            return
        with io.open(_PATH, encoding="utf-8") as f:
            n = sum(1 for _ in f)
        if n <= _MAX_LINES:
            return
        bak = _PATH + ".1"
        if os.path.isfile(bak):
            bak = _PATH + ".%d" % int(time.time())
        os.rename(_PATH, bak)
        LOG.info("经验库滚动：%d 行 → 备份为 %s", n, os.path.basename(bak))
    except Exception as e:      # noqa: silent-ok — 滚动失败不该影响记录
        LOG.debug("经验库滚动失败（忽略）：%s", e)


def record(kind, ok, why="", need="", stage="", lesson="", extra=None):
    """记一条经验。任何异常都不许抛（记录失败不影响主流程）。"""
    try:
        _ensure()
        _rotate_if_needed()
        row = {"kind": str(kind or "misc")[:40], "ok": bool(ok),
               "why": str(why or "")[:400], "need": str(need or "")[:200],
               "stage": str(stage or "")[:40], "lesson": str(lesson or "")[:400],
               "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        if extra:
            try:
                row["extra"] = {str(k): str(v)[:200] for k, v in dict(extra).items()}
            except Exception:      # noqa: silent-ok
                pass
        with io.open(_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return True
    except Exception as e:      # noqa: silent-ok
        LOG.debug("记经验失败（忽略）：%s", e)
        return False


def load(limit=800):
    """读经验（最近的 limit 条，时间正序）。"""
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
        LOG.debug("读经验失败（忽略）：%s", e)
    return out[-limit:]


def lessons(kind=None, keyword="", limit=3):
    """取"同类失败"的教训，供生成/诊断时注入提示词。

    `keyword`：用需求里的词去匹配，拿"做过类似需求时踩过的坑"。
    去重口径：同一 (why) 只留最近一条 —— 同一个坑反复记，注入时只会重复。
    """
    kws = [w for w in re.findall(r"[\u4e00-\u9fff]{2,6}|[A-Za-z]{3,}", str(keyword or ""))][:6]
    seen, out = set(), []
    for row in reversed(load()):
        if kind and row.get("kind") != kind:
            continue
        if row.get("ok"):
            continue                            # 只看失败教训
        why = str(row.get("why") or "")
        if not why:
            continue
        if kws and not any(w in (str(row.get("need") or "") + why) for w in kws):
            continue
        key = (row.get("kind"), why[:60])
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
        if len(out) >= limit:
            break
    return out


def stats():
    """给界面/自检看：记了多少、成功率多少。"""
    rows = load(limit=10000)
    total = len(rows)
    ok = sum(1 for r in rows if r.get("ok"))
    by_kind = {}
    for r in rows:
        k = str(r.get("kind") or "misc")
        d = by_kind.setdefault(k, {"n": 0, "ok": 0})
        d["n"] += 1
        d["ok"] += 1 if r.get("ok") else 0
    return {"total": total, "ok": ok,
            "rate": round(100.0 * ok / total, 1) if total else None,
            "by_kind": by_kind, "path": _PATH}


def suggest_lesson(stage, why):
    """把一次失败翻译成一句可复用的教训（失败样本的价值全在这句上）。"""
    s, w = str(stage or ""), str(why or "")
    if s == "generate":
        return "生成阶段就断了：先确认大脑服务在跑（端口 9292），再让它把代码写短（≤60 行）"
    if s == "static":
        if "语法错误" in w and "never closed" in w:
            return "输出被截断：让它写更短、并明确要求『只输出完整代码』"
        if "语法错误" in w:
            return "语法不过：把错误行原文回喂模型让它只改那一处（自修一轮）"
        if "import" in w:
            return "用了非白名单库：提示词里把允许的 import 清单再列一遍"
        if "get_plugin" in w or "get_tool_descriptions" in w:
            return "契约没写全：给它看一个真实插件的最小骨架，比口头描述有效"
        if "中文" in w:
            return "没有中文说明：要求 description 必须中文且含「什么时候用」"
        return "静态检查没过：把检查口径逐条写进提示词"
    if s == "sandbox":
        if "什么时候用" in w:
            return "说明缺「什么时候用」：载体可自动补齐，但要在提示词里先要求"
        if "抛异常" in w:
            return "execute 抛异常：要求用 try/except 兜住并返回中文原因"
        if "工具名" in w:
            return "工具名必须是英文（中文名调不准）"
        return "沙箱没过：拿空参数调用也要返回字符串"
    if s == "write":
        return "落地失败：检查 plugins/ 是否可写"
    return ""


def remember_forge(need, result):
    """能力自增长一次结果的记账（成功也记，用来算成功率）。"""
    ok = bool((result or {}).get("ok"))
    stage = str((result or {}).get("stage") or "")
    why = str((result or {}).get("why") or "")
    lesson = "" if ok else suggest_lesson(stage, why)
    return record("forge_" + ("ok" if ok else "fail"), ok, why=why, need=need,
                  stage=stage, lesson=lesson,
                  extra={"tools": ",".join((result or {}).get("tools") or []),
                         "attempts": (result or {}).get("attempts"),
                         "fixed": (result or {}).get("fixed")})
