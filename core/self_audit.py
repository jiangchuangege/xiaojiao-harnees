# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 自审循环（2026-10-28）

【一句话】把"账本 → 审计 → 改进闸门"接成一个**自己会转的环**，而不是等人来查。

【为什么这一步才是闭环的关键】
  前面三件各自都成立：
    · `core/evidence_ledger.py` 记下每句话的依据（可复算）；
    · `core/gate_evolve.py` 让改动**先量后落地**（有退步就拒）；
    · `core/self_evolve.py` 能说出"哪儿弱"。
  但它们之间原来**没有人接线**：账本里"有据率掉到 40%"这个事实，没有任何机制去动手。
  于是"可核查"只是好看，"自我改进"只是能手动跑。这一层就是把它们连起来：

      定时（默认每 6 小时）→ 审最近的账本
        ├ 有据率低于阈值 → 提一个**旋钮候选**（标注阈值那档），交给闸门配对测量
        │                    → 过了才落地；过不了就记一条"试过、量出来没收益"
        ├ 复算不一致 / 缺快照 → 这是账本自身的问题，**不许自己修自己**，
        │                    只写改进卡 + 记经验，等人看
        └ 产物失效（当时有据、现在失效）→ 记经验，并写卡说明"哪份材料过期了"

【三条自律（写死在代码里，不是写在注释里）】
  1. **不许改判据**：这一层只能"提候选"，落不落地由 `gate_evolve` 的配对测量决定；
  2. **账本自己的毛病只报不改**：`recheck_bad` / `missing_blobs` 一律只出卡 ——
     让它自己修自己的证据，等于让被告当法官；
  3. **同一项 24 小时内不重试**：和 `auto_evolve` 一个口径，避免"每天提同一个被拒的改动"
     刷屏，也避免把预算烧在同一个点上。

落盘：
    logs/self_audit/history.jsonl    每次自审一行（数字 + 动作 + 结论）
    logs/self_audit/cards/*.md       给人看的改进卡
"""
import io
import json
import logging
import os
import threading
import time

LOG = logging.getLogger(__name__)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DIR = os.path.join(_ROOT, "logs", "self_audit")
_CARDS = os.path.join(_DIR, "cards")
_HIST = os.path.join(_DIR, "history.jsonl")
_LOCK = threading.Lock()
_STATE = {"thread": None, "stop": False, "last": 0.0, "rounds": 0}


def _ensure():
    for d in (_DIR, _CARDS):
        if not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)


def _cfg():
    """配置（控制文件里 `self_audit` 段，缺省值就是这里写的）。"""
    try:
        import xiaojiao_app as _A
        c = (_A.CONTROL or {}).get("self_audit") or {}
    except Exception:      # noqa: silent-ok — 拿不到配置就用默认
        c = {}
    return {"enabled": bool(c.get("enabled", True)),
            "interval_h": float(c.get("interval_h", 6) or 6),
            "window": int(c.get("window", 30) or 30),
            "min_support_ratio": float(c.get("min_support_ratio", 0.6) or 0.6),
            "max_actions_per_run": int(c.get("max_actions_per_run", 1) or 1),
            "skip_hours": float(c.get("skip_hours", 24) or 24)}


# ============================== 账本 → 一次体检 ==============================
def inspect(window=30):
    """审一遍最近的账本，返回一份**纯事实**的体检结果（不含任何建议）。"""
    from core import evidence_ledger as EL
    ag = EL.audit_recent(limit=int(window))
    st = EL.stats()
    ch = EL.verify_chain()
    rows = ag.get("details") or []
    bad_rounds = [r for r in rows if (r.get("recheck_bad") or r.get("missing_blobs"))]
    stale_rounds = [r for r in rows if r.get("stale_files")]
    no_support = [r for r in rows if (r.get("claims") or 0) > 0
                  and (r.get("supported") or 0) == 0]
    return {"at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "rounds": ag.get("rounds") or 0,
            "claims": ag.get("claims") or 0,
            "supported": ag.get("supported") or 0,
            "ratio": float(ag.get("ratio") or 0.0),
            "ledger_total": st.get("rounds") or 0,
            "chain_ok": bool(ch.get("ok")),
            "chain_broken": ch.get("broken") or [],
            "recheck_failed": len(bad_rounds),
            "stale_rounds": len(stale_rounds),
            "all_unsupported_rounds": len(no_support),
            "worst": [{"id": r.get("id"), "question": (r.get("question") or "")[:40],
                       "claims": r.get("claims"), "supported": r.get("supported"),
                       "verdict": r.get("verdict")} for r in (bad_rounds + no_support)[:5]]}


# ============================== 体检 → 动作（只提候选，不自己改） ==============================
def _tried_recently(key, hours=24.0):
    """同一项最近试过吗（避免每天重提同一个被拒的改动）。"""
    try:
        from core import gate_evolve as GE
        for row in GE.history(limit=200):
            if str(row.get("name") or "") != key:
                continue
            try:
                t = time.mktime(time.strptime(str(row.get("at")), "%Y-%m-%dT%H:%M:%S"))
            except Exception:      # noqa: silent-ok
                continue
            if (time.time() - t) < float(hours) * 3600:
                return True
    except Exception as e:      # noqa: silent-ok — 查不到历史就当没试过
        LOG.debug("自审：查闸门历史失败（%s）", e)
    return False


def _write_card(title, body):
    _ensure()
    path = os.path.join(_CARDS, time.strftime("%Y%m%d_%H%M%S") + "_" + str(title)[:20]
                        .replace(" ", "").replace("/", "_") + ".md")
    try:
        with io.open(path, "w", encoding="utf-8", newline="") as f:
            f.write("# %s\n\n- 生成时间：%s\n\n%s\n"
                    % (title, time.strftime("%Y-%m-%d %H:%M:%S"), body))
        LOG.info("自审：已写改进卡 %s", os.path.basename(path))
        return path
    except Exception as e:      # noqa: silent-ok
        LOG.debug("自审：改进卡写入失败（%s）", e)
        return ""


def act(fit, cfg=None):
    """按体检结果做**动作**。返回动作列表（每条都写清做了什么、结果）。

    三条分支：
      · 有据率低于阈值 → 提候选（走闸门），过闸才落地；
      · 账本自身有问题 → **只出卡**（不许自己修自己的证据）；
      · 产物失效 → 记经验 + 出卡（告诉人哪份材料过期了）。
    """
    cfg = cfg or _cfg()
    acts = []
    max_act = int(cfg.get("max_actions_per_run") or 1)
    ratio = float(fit.get("ratio") or 0.0)
    claims = int(fit.get("claims") or 0)

    # ① 有据率低：提候选（只提一个，且 24 小时内不重提）
    if claims >= 5 and ratio < float(cfg.get("min_support_ratio") or 0.6) and len(acts) < max_act:
        key = "按自审调标注阈值"
        if _tried_recently(key, cfg.get("skip_hours") or 24):
            acts.append({"action": "skip", "why": "24 小时内试过同一个候选，不重提", "key": key})
        else:
            try:
                from core import gate_evolve as GE
                cur = int(GE.knob_read("gate_note_min"))
                # 有据率低 → 说明"该标注的没标注"更危险 → 往更严（数字更小）调一档
                cand_v = max([v for v in GE.KNOBS["gate_note_min"]["allowed"] if v < cur]
                             or [cur])
                if cand_v == cur:
                    acts.append({"action": "skip", "why": "标注阈值已经是最严档"})
                else:
                    base = GE.bench("carrier")
                    res, ok = GE.attempt(key, "gate_note_min", cand_v,
                                         why="自审：最近有据率 %.0f%% < %.0f%%（%d 条断言）"
                                             % (ratio * 100,
                                                float(cfg.get("min_support_ratio") or 0.6) * 100,
                                                claims),
                                         suite="carrier", base=base)
                    acts.append({"action": "gate", "key": key, "knob": "gate_note_min",
                                 "from": cur, "to": cand_v, "accepted": bool(ok),
                                 "why": (res.get("decision") or {}).get("why", "")})
            except Exception as e:      # noqa: silent-ok — 闸门跑挂不影响记录
                acts.append({"action": "error", "key": key, "why": "%s: %s" % (type(e).__name__, e)})

    # ② 账本自身有问题：只出卡（不许自己修自己的证据）
    if fit.get("recheck_failed") or not fit.get("chain_ok"):
        body = ("## 事实\n\n"
                "- 复算不一致的轮次：%d\n- 哈希链：%s\n\n## 最差的几轮\n\n%s\n\n"
                "## 为什么只出卡、不自动改\n\n"
                "证据账本一旦能「自己修自己」，它就不再是证据了 —— 让被告当法官。\n"
                "这一项必须人来看：是账本被改过，还是快照丢了。\n"
                % (fit.get("recheck_failed") or 0,
                   "完整" if fit.get("chain_ok") else "断了：%s" % (fit.get("chain_broken") or [])[:2],
                   "\n".join("- `%s` %s ｜ %s" % (w.get("id"), w.get("question"), w.get("verdict"))
                             for w in (fit.get("worst") or [])) or "（无明细）"))
        p = _write_card("账本自身有不一致", body)
        acts.append({"action": "card", "key": "账本自身有不一致", "path": p})

    # ③ 产物失效：记经验 + 出卡
    if fit.get("stale_rounds"):
        body = ("## 事实\n\n最近 %d 轮里有 **%d 轮**的产物/材料已经变了（当时有据、现在失效）。\n\n"
                "## 这意味着\n\n那些轮次的结论**当时是对的，现在不能直接引用** —— "
                "用户可能已经拿它去做事了，值得提醒一句。\n"
                % (fit.get("rounds") or 0, fit.get("stale_rounds") or 0))
        p = _write_card("有产物已经失效", body)
        acts.append({"action": "card", "key": "有产物已经失效", "path": p})
        try:
            from core import experience as EXP
            EXP.record("self_audit", False, why="%d 轮产物失效" % fit["stale_rounds"],
                       need="账本产物保鲜", stage="audit",
                       lesson="材料/产物会变：结论要带时间戳，重用前必须复核")
        except Exception as e:      # noqa: silent-ok
            LOG.debug("自审：记经验失败（%s）", e)
    return acts


def run_once(window=None, verbose=False):
    """跑一次自审：体检 → 动作 → 落盘。返回一条完整记录。"""
    cfg = _cfg()
    fit = inspect(int(window or cfg.get("window") or 30))
    acts = act(fit, cfg)
    rec = {"at": fit["at"], "fit": fit, "acts": acts,
           "verdict": ("有据率 %.0f%%，复算不一致 %d 轮，失效 %d 轮"
                       % (fit["ratio"] * 100, fit["recheck_failed"], fit["stale_rounds"]))}
    _ensure()
    try:
        with io.open(_HIST, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:      # noqa: silent-ok
        LOG.debug("自审历史写入失败（%s）", e)
    with _LOCK:
        _STATE["last"] = time.time()
        _STATE["rounds"] = int(_STATE["rounds"]) + 1
    LOG.info("自审完成：%s ｜ 动作 %d 个", rec["verdict"], len(acts))
    if verbose:
        print("自审：%s" % rec["verdict"])
        for a in acts:
            print("  - %s %s" % (a.get("action"), a.get("why") or a.get("key") or ""))
    return rec


# ============================== 后台循环 ==============================
def start_in_background():
    """起一个 daemon 线程，定时自审。已经在跑就返回 False（不重复起）。"""
    cfg = _cfg()
    if not cfg["enabled"]:
        LOG.info("自审：配置里关掉了（self_audit.enabled=false），不起")
        return False
    with _LOCK:
        if _STATE["thread"] is not None and _STATE["thread"].is_alive():
            return False
        _STATE["stop"] = False

    def _loop():
        # 起的时候先等一会儿：别和启动那阵的保养/世界层抢
        _wait = 120.0
        while not _STATE["stop"]:
            time.sleep(5.0)
            _wait -= 5.0
            if _wait > 0:
                continue
            try:
                run_once()
            except Exception as e:      # noqa: silent-ok — 循环里的异常绝不许把线程打死
                LOG.warning("自审这一轮失败（继续下一轮）：%s: %s", type(e).__name__, e)
            _interval = float(_cfg()["interval_h"]) * 3600.0
            slept = 0.0
            while slept < _interval and not _STATE["stop"]:
                time.sleep(5.0)
                slept += 5.0

    t = threading.Thread(target=_loop, name="xj-self-audit", daemon=True)
    with _LOCK:
        _STATE["thread"] = t
    t.start()
    LOG.info("自审：已起（每 %s 小时一次，窗口 %s 轮）", cfg["interval_h"], cfg["window"])
    return True


def stop():
    with _LOCK:
        _STATE["stop"] = True


def stats():
    rows = []
    try:
        if os.path.isfile(_HIST):
            for ln in io.open(_HIST, encoding="utf-8").read().split("\n"):
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    rows.append(json.loads(ln))
                except Exception:      # noqa: silent-ok — 坏一行跳过
                    continue
    except Exception as e:      # noqa: silent-ok
        LOG.debug("自审统计读取失败（%s）", e)
    acts = [a for r in rows for a in (r.get("acts") or [])]
    return {"runs": len(rows), "last": rows[-1]["at"] if rows else "",
            "gated": len([a for a in acts if a.get("action") == "gate"]),
            "accepted": len([a for a in acts if a.get("action") == "gate" and a.get("accepted")]),
            "cards": len([a for a in acts if a.get("action") == "card"]),
            "live": bool(_STATE["thread"] is not None and _STATE["thread"].is_alive()),
            "current": (rows[-1].get("verdict") if rows else ""), "dir": _DIR}


def report_text(limit=5):
    """给插件/命令行看的一段话。"""
    st = stats()
    if not st["runs"]:
        return ("还没跑过自审。说「自审一下」我就跑一次；后台默认每 6 小时自己跑（可在 "
                "xiaojiao_control.json 的 self_audit 段改）。")
    lines = ["🧾 **自审**（后台%s，已跑 %d 次）" % ("在跑" if st["live"] else "没在跑", st["runs"]),
             "", "- 最近一次：%s ｜ %s" % (st["last"][5:16], st["current"]),
             "- 提过候选 %d 次，其中落地 %d 次（其余被闸门按「有退步就不落地」拒了）"
             % (st["gated"], st["accepted"]),
             "- 出过的改进卡：%d 张（`logs/self_audit/cards/`）" % st["cards"]]
    rows = []
    try:
        if os.path.isfile(_HIST):
            rows = [json.loads(x) for x in io.open(_HIST, encoding="utf-8").read().split("\n")
                    if x.strip()][-limit:]
    except Exception:      # noqa: silent-ok
        rows = []
    if rows:
        lines += ["", "最近几次："]
        for r in reversed(rows):
            lines.append("- %s ｜ %s" % (str(r.get("at"))[5:16],
                                         (r.get("verdict") or "")[:60]))
    lines += ["", "—— 规矩：这一层只**提候选**，落不落地由 `core/gate_evolve.py` 的配对测量决定；"
              "账本自己的毛病只出卡不改（不许让被告当法官）。"]
    return "\n".join(lines)
