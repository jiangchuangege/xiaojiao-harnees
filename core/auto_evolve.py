# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 无人值守的自我改进（2026-10-27）

【它补的是最后一公里】上一轮已经有了：尺子（评测 + 体检）、诊断（self_evolve）、
手（plugin_forge）、记忆（experience）。但**都得有人去按**。本模块让它自己按：

    空闲/定时 → 读诊断 → 挑一项 → 白名单内自动做 → 记录 → 冷却 → 同一项 24 小时内不重试

【三条硬规矩（不给自己开后门）】
  ① **只有一类能自动动手**：「缺能力」走 `plugin_forge`（它自己带静态检查 + 子进程沙箱）；
     判据类、答案类、性能类**一律只出一张改进卡**（写到 logs/auto_evolve/cards/），不动源码。
     理由很实在：自动改 `xiaojiao_app.py` / `core/*` 属于高风险动作，这个模块不该有这个权限。
  ② **同一项不反复试**：记 history，同一 (kind, target) 24 小时内只试一次；
     否则它会在同一个坑上每 6 小时撞一次，日志被刷满、还以为是"在努力"。
  ③ **不空转**：诊断没红点就立刻返回；每天最多行动 N 次（默认 3），可配置关闭。

【怎么开】控制文件 `xiaojiao_control.json` 里：
    "auto_evolve": {"on": true, "interval_h": 6, "per_day": 3}
  默认 **on=true / 6 小时 / 每天 3 次**；关掉就是 `"on": false`。
"""
import io
import json
import logging
import os
import re
import time

LOG = logging.getLogger(__name__)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_HIST = os.path.join(_ROOT, "logs", "auto_evolve", "history.jsonl")
_CARDS = os.path.join(_ROOT, "logs", "auto_evolve", "cards")
_ONCE_HOURS = 24.0

_STATE = {"started": False, "last_tick": 0.0, "thread": None}


def _cfg():
    """读配置（读不到就用默认：开、6 小时、每天 3 次）。"""
    d = {"on": True, "interval_h": 6, "per_day": 3}
    try:
        p = os.path.join(_ROOT, "xiaojiao_control.json")
        c = json.load(open(p, encoding="utf-8"))
        a = c.get("auto_evolve") or {}
        if "on" in a:
            d["on"] = bool(a["on"])
        if a.get("interval_h"):
            d["interval_h"] = max(0.2, float(a["interval_h"]))
        if a.get("per_day"):
            d["per_day"] = max(0, int(a["per_day"]))
    except Exception as e:      # noqa: silent-ok — 读不到就用默认
        LOG.debug("自我改进：读配置失败（用默认）：%s", e)
    return d


def _ensure():
    for p in (os.path.dirname(_HIST), _CARDS):
        if p and not os.path.isdir(p):
            os.makedirs(p, exist_ok=True)


def history(limit=200):
    out = []
    try:
        if not os.path.isfile(_HIST):
            return out
        for ln in io.open(_HIST, encoding="utf-8").read().split("\n"):
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except Exception:      # noqa: silent-ok — 坏一行跳过
                continue
    except Exception:      # noqa: silent-ok
        pass
    return out[-limit:]


def _record(kind, target, action, ok, why, card=""):
    try:
        _ensure()
        with io.open(_HIST, "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                "kind": kind, "target": target, "action": action,
                                "ok": bool(ok), "why": str(why or "")[:300],
                                "card": card}, ensure_ascii=False) + "\n")
    except Exception as e:      # noqa: silent-ok
        LOG.debug("自我改进：记历史失败（忽略）：%s", e)


def _recently_tried(kind, target, hours=_ONCE_HOURS):
    """这一项最近试过吗？（同一项 24 小时内不重试）"""
    now = time.time()
    for row in reversed(history(400)):
        if row.get("kind") != kind or row.get("target") != target:
            continue
        try:
            t = time.mktime(time.strptime(str(row.get("at")), "%Y-%m-%dT%H:%M:%S"))
        except Exception:      # noqa: silent-ok
            continue
        if (now - t) <= hours * 3600:
            return True
    return False


def _today_count():
    today = time.strftime("%Y-%m-%d")
    return sum(1 for r in history(400) if str(r.get("at", "")).startswith(today))


def pick(limit=20):
    """从诊断里挑一项该做的（跳过 24 小时内试过的）。返回 dict 或 None。"""
    try:
        from core import self_evolve as SE
        items = SE.diagnose(limit=limit)
    except Exception as e:      # noqa: silent-ok — 诊断不可用就什么都不做
        LOG.warning("自我改进：拿不到诊断（%s），本轮跳过", type(e).__name__)
        return None
    # 可自动的排前面（缺能力），其余按诊断给的优先级
    items = sorted(items, key=lambda x: (0 if x.get("auto") else 1, x.get("pri", 9)))
    for it in items:
        if _recently_tried(it.get("kind"), it.get("target")):
            continue
        return it
    return None


def _write_card(item, why=""):
    """非白名单项：只写一张改进卡（不动源码）。返回卡片路径。"""
    try:
        _ensure()
        ts = time.strftime("%Y%m%d_%H%M%S")
        safe = "".join(ch for ch in str(item.get("target") or "x") if ch.isalnum() or ch in "_-")[:40]
        path = os.path.join(_CARDS, "%s_%s.md" % (ts, safe or "item"))
        lines = ["# 改进卡：%s" % item.get("kind_name", item.get("kind")),
                 "",
                 "- 目标：`%s`" % item.get("target"),
                 "- 证据：%s" % item.get("evidence"),
                 "- 动作：%s" % item.get("action"),
                 "- 生成时间：%s" % time.strftime("%Y-%m-%d %H:%M:%S"),
                 "",
                 "> 这张卡由 `core/auto_evolve.py` 自动写出。它**只诊断、不改源码**：",
                 "> 改 `core/` 或主程序属于高风险动作，必须人看。",
                 ""]
        if why:
            lines.insert(4, "- 备注：%s" % why)
        io.open(path, "w", encoding="utf-8").write("\n".join(lines))
        return path
    except Exception as e:      # noqa: silent-ok
        LOG.debug("自我改进：写改进卡失败（忽略）：%s", e)
        return ""


def _extract_need(evidence):
    """从诊断证据里提取"可以被 forge 执行的需求"。取不准就返回空串（宁可不动手）。

    证据通常长这样：「最近 5 条失败：语法错误：第 107 行 '(' was never closed」——
    后半段是**故障描述**，不是需求，直接拿去当 need 只会生成垃圾。
    所以：优先取「需求：…」「need：…」这种显式标注；没有就取引号里的短句；
    再没有就返回空 —— 自动动手这条路，宁可不做，也不拿脏输入开工。
    """
    s = str(evidence or "").strip()
    if not s:
        return ""
    for pat in (r"需求[：:]\s*([^\n｜]{4,120})", r"need[：:]\s*([^\n｜]{4,120})",
                r"「([^」]{4,120})」"):
        m = re.search(pat, s)
        if m:
            return m.group(1).strip()
    return ""


def act(item, dry_run=False):
    """执行一项诊断。返回 dict：{ok, action, why, card}。

    只有 item["auto"] 为真（缺能力）才真的动手 —— 走 forge（自带两道闸）。
    """
    if not item:
        return {"ok": False, "action": "none", "why": "没有要做的项", "card": ""}
    kind, target = item.get("kind"), str(item.get("target") or "")

    if item.get("auto"):
        # 【需求文本必须取准，取不准就干脆别动手】实测踩到：evidence 形如
        #   「最近 5 条失败：语法错误…」，我用一串 replace 去"清洗"，
        #   结果拿到了一个 `x` → forge 拿 `x` 当需求，模型胡乱写了一份垃圾插件，
        #   沙箱只校验"不抛异常、返回字符串"，于是它居然过了关、落了地。
        #   现在：只认证据里"像需求"的片段；取不到就**不动手**，写张卡说明原因。
        #   注意这一步要放在 dry_run 之前 —— 否则自测里"取不准就不动手"这条测不出来。
        need = _extract_need(item.get("evidence"))
        if len(need) < 6:
            if dry_run:
                return {"ok": False, "action": "skip",
                        "why": "证据里提取不出可用的需求（%r），本次不动手" % need, "card": ""}
            card = _write_card(item, why="证据里提取不出可执行的需求（%r），本次不动手" % need)
            return {"ok": False, "action": "skip",
                    "why": "证据里提取不出可用的需求，没动手（不拿垃圾需求去生成）", "card": card}
        if dry_run:
            return {"ok": True, "action": "forge(dry-run)",
                    "why": "缺能力类：本可以走 forge（need=%s）" % need[:24], "card": ""}
        try:
            from core import plugin_forge as PF
            r = PF.forge(need)
            ok = bool(r.get("ok"))
            why = str(r.get("why") or "")[:200]
            LOG.info("自我改进：走 forge（need=%r）→ ok=%s stage=%s", need[:30], ok, r.get("stage"))
            return {"ok": ok, "action": "forge", "why": why, "card": "",
                    "stage": r.get("stage"), "module": r.get("module")}
        except Exception as e:      # noqa: silent-ok — 自动动手失败要如实记，不许吞
            return {"ok": False, "action": "forge", "why": "%s: %s" % (type(e).__name__, str(e)[:120]),
                    "card": ""}

    # 其它类型：只出卡
    card = "" if dry_run else _write_card(item)
    return {"ok": True, "action": "card", "why": "非白名单项：只写改进卡，不动源码",
            "card": card}


def tick(dry_run=False, force=False):
    """跑一次自我改进。返回 dict（做了什么 / 为什么没做）。

    `force=True`：忽略间隔与每日上限（自测/手动触发用）。
    """
    cfg = _cfg()
    if not cfg["on"] and not force:
        return {"did": False, "why": "配置里关掉了（auto_evolve.on=false）"}
    now = time.time()
    if not force and (now - float(_STATE.get("last_tick") or 0)) < cfg["interval_h"] * 3600:
        left = cfg["interval_h"] * 3600 - (now - float(_STATE.get("last_tick") or 0))
        return {"did": False, "why": "还没到间隔（还剩 %.1f 小时）" % (left / 3600.0)}
    if not force and _today_count() >= cfg["per_day"]:
        return {"did": False, "why": "今天已经做过 %d 次（上限 %d）" % (_today_count(), cfg["per_day"])}
    _STATE["last_tick"] = now

    item = pick()
    if not item:
        return {"did": False, "why": "诊断没有可做的项（或都已试过）"}
    res = act(item, dry_run=dry_run)
    if not dry_run:
        _record(item.get("kind"), str(item.get("target")), res.get("action"),
                res.get("ok"), res.get("why"), res.get("card"))
    return {"did": True, "item": item, "result": res}


def _loop():
    """后台循环：每 5 分钟看一次该不该做（间隔/日限额由 tick 自己判）。"""
    while True:
        try:
            r = tick()
            if r.get("did"):
                LOG.info("自我改进：%s", json.dumps(
                    {"item": (r.get("item") or {}).get("target"),
                     "result": (r.get("result") or {}).get("action")}, ensure_ascii=False))
        except Exception as e:      # noqa: silent-ok — 循环绝不能死
            LOG.warning("自我改进循环异常（忽略并继续）：%s: %s", type(e).__name__, e)
        time.sleep(300)


def start_in_background():
    """载体启动时调用一次：起一个 daemon 线程（重复调用是幂等的）。"""
    try:
        if _STATE.get("started"):
            return False
        cfg = _cfg()
        if not cfg["on"]:
            LOG.info("自我改进：配置关着，不起后台线程")
            return False
        import threading
        t = threading.Thread(target=_loop, name="xj-auto-evolve", daemon=True)
        t.start()
        _STATE.update({"started": True, "thread": t})
        LOG.info("自我改进：已起后台线程（每 %.0f 小时最多动 %d 次；只做缺能力，其余只出卡）",
                 cfg["interval_h"], cfg["per_day"])
        return True
    except Exception as e:      # noqa: silent-ok — 起不来就算了，不许影响启动
        LOG.warning("自我改进：后台线程起不来：%s", e)
        return False


def status():
    """给界面/自检看：开关、间隔、今日次数、最近几条。"""
    cfg = _cfg()
    h = history(20)
    return {"on": cfg["on"], "interval_h": cfg["interval_h"], "per_day": cfg["per_day"],
            "today": _today_count(), "started": bool(_STATE.get("started")),
            "recent": h[-5:], "cards_dir": _CARDS}
