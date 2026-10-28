# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 自我改进的量化闸门（2026-10-28）

【它解决什么：把「进化」从叙事变成一次可复现的实验】
  现在会很常见地看到一种说法：「我们的 AI 会自我进化」。
  但追下去往往是三种东西之一：
    ① 改了一版提示词，觉得更好，就发版了（**没有对照**）；
    ② 收集用户反馈，下次改（**没有单一变量**）；
    ③ 换个更大的模型，说能力提升了（**不是它自己改的**）。
  这三种都无法回答一个问题：**这次改动，到底让哪一项指标变好了、哪一项变差了？**

  载体这边可以做一件更硬的事，因为旋钮全在我们手里：
     候选改动 → 声明式地只动**一个旋钮** → 同一套判据跑两遍（配对比较）
              → 有退步就回滚，一个指标都不许被悄悄弄坏
              → 决策与数字全部落盘，日后可复查

【硬规矩（这些不是风格问题，是安全线）】
  1. **只能动白名单旋钮**：旋钮在 `KNOBS` 里显式登记（模块 + 变量名 + 取值范围）。
     不许执行任意代码、不许改文件、不许注入新逻辑 —— 自我改进的权限必须小到"只能调参"。
  2. **必须配对测量**：同一个基准、同一批用例，改动前后各跑一遍，逐条比。
     只报总分不算 —— 总分涨了但某几条塌了，那叫"借新债还旧债"。
  3. **有退步就不落地**：任何一条从"过"变"不过"，直接拒绝，不进仓库状态。
     （可以放宽成"允许零退步 + 总分不降"这种更严的口径，但不许反过来。）
  4. **落地的改动必须能回滚**：决策记录里带完整 revert 信息，`rollback()` 一键复原。
  5. **量不出来就说量不出来**：基准跑不起来（缺依赖/缺网络）→ 结论是 `unknown`，
     不落地，也不假装"验证通过"。

【和另外两件的关系】
  · `core/self_evolve.py`：**诊断**（哪儿弱）；
  · `core/plugin_forge.py`：**补能力**（缺工具就写工具）；
  · 本模块：**调旋钮**（已有能力怎么配得更准），三者都过"测量"这一关才算数。

落盘：
    logs/evolve/decisions.jsonl     每次决策一行（候选、前后分数、逐条差异、结论）
    logs/evolve/applied.json        当前已落地的旋钮值（重启后由 `restore_applied()` 复原）
"""
import importlib
import io
import json
import logging
import os
import time
import uuid

LOG = logging.getLogger(__name__)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DIR = os.path.join(_ROOT, "logs", "evolve")
_DECISIONS = os.path.join(_DIR, "decisions.jsonl")
_APPLIED = os.path.join(_DIR, "applied.json")

# ============================== 白名单旋钮 ==============================
# 每个旋钮：模块、变量名、允许的取值集合、人话说明。
# 【为什么用白名单而不是"随便给个函数"】能执行任意东西的"自我改进"等于给自己 root：
#   一旦模型把某个改动包装成"这会让它更强"，我们就没法审。旋钮制下，
#   候选改动只能是"把这个已知参数从 A 调到 B"，影响面有限、可回滚、可解释。
KNOBS = {
    "gate_note_min": {
        "module": "core.answer_gate", "attr": "NOTE_MIN_STRONG",
        "allowed": [2, 3, 4, 5],
        "desc": "几处以上「找不到依据」才强标注（越小越爱提醒，越大越安静）",
    },
    "display_body_max": {
        "module": "xiaojiao_app", "attr": "DISPLAY_BODY_DEFAULT",
        "allowed": [800, 1200, 1500, 2000, 3000],
        "desc": "聊天里默认给用户看多少字正文（抓取/清单类回答的截断长度）",
    },
    "router_sticky_s": {
        "module": "core.model_router", "attr": "_STICKY_S",
        "allowed": [30.0, 60.0, 120.0],
        "desc": "同一档模型的粘性时间（秒）：太短会来回切模型，太长会跟不上难度",
    },
}


def _ensure():
    if not os.path.isdir(_DIR):
        os.makedirs(_DIR, exist_ok=True)


def _mod(name):
    """按名字取模块（取不到就抛 —— 旋钮不存在时宁可报错，也不静默跳过）。"""
    return importlib.import_module(name)


def knob_read(knob):
    spec = KNOBS.get(knob)
    if not spec:
        raise KeyError("没有这个旋钮：%s" % knob)
    return getattr(_mod(spec["module"]), spec["attr"])


def knob_write(knob, value):
    """把旋钮写进模块（这是唯一会改变运行行为的动作，只有 commit/rollback 调它）。"""
    spec = KNOBS[knob]
    setattr(_mod(spec["module"]), spec["attr"], value)


# ============================== 基准：同一套判据跑两遍 ==============================
def _bench_carrier():
    """载体微基准：**对旋钮敏感**的那几项（不调模型、毫秒级）。

    为什么要单独一组：`tools/eval_xiaojiao.py` 的离线层覆盖的是"意图识别/隔离/契约"，
    那批用例对"标注阈值""展示长度"这些旋钮**不敏感** —— 拿它去量，永远是 0 差异，
    于是每个候选都"不退步"，闸门形同虚设。所以这里补一组直接钉住旋钮行为的用例。
    """
    out = {}
    # ① 标注阈值：造不同条数的「查不到依据」，钉住**项目既定原则**
    #    原则（写在 `core/answer_gate.py` 的注释里，不是这里临时编的）：
    #      P1 一点材料都没有 → 必须标注；
    #      P2 有材料且全部有据 → 一个字都不许标注；
    #      P3 属于「用户会拿去用」的类型（比分/日期/网址/路径）哪怕 1 处 → 要提示；
    #      P4 「每句都弹警告会被当噪声」→ 2 处**普通数值**不该强标注。
    #    这四条一起，才让「阈值」这个旋钮有了**可判对错**的口径：
    #    把阈值改成 2 → P4 被破坏 → 闸门会把它判成退步并拒绝。
    try:
        from core import answer_gate as AG
        ans = "比赛 3:1 结束，日期 2026-07-20，文件在 G:\\dzs\\a.md。"
        r = AG.audit(ans, evidence="（本轮没有任何材料）", question="随便问问")
        out["gate_no_material_note"] = 1 if r.get("note") else 0            # P1
        r2 = AG.audit(ans, evidence="比赛 3:1 结束，日期 2026-07-20，文件在 G:\\dzs\\a.md。",
                      question="随便问问")
        out["gate_with_material_silent"] = 1 if not r2.get("note") else 0    # P2
        r3 = AG.audit("终场是 2:1。", evidence="参考资料：今天天气不错。", question="谁赢了")
        out["gate_strong_single_note"] = 1 if r3.get("note") else 0         # P3
        r4 = AG.audit("那边有 12 人和 30 条船。", evidence="参考资料：海边风景很好。", question="那边有什么")
        out["gate_two_plain_silent"] = 1 if not r4.get("note") else 0        # P4
        # P5：具体数量（7 个链接 / 3 位作者）必须算可核查断言 —— 用户会拿这个数做决定
        _c = AG.extract_claims("这页有 7 个链接，3 位作者。")
        out["gate_count_is_claim"] = 1 if len(_c) >= 2 else 0
    except Exception as e:      # noqa: silent-ok — 基准跑不起来就是"量不出来"
        LOG.debug("基准①跑不了：%s", e)
        for k in ("gate_no_material_note", "gate_with_material_silent",
                  "gate_strong_single_note", "gate_two_plain_silent", "gate_count_is_claim"):
            out[k] = -1
    # ② 展示长度：长正文截断后不超过旋钮值，且要有"后略"提示
    try:
        app = _mod("xiaojiao_app")
        body = "# 标题\n" + ("这是一段很长的正文内容，用来占位。" * 400)
        shown = app._display_body(body)
        lim = int(knob_read("display_body_max"))
        out["display_within_limit"] = 1 if len(shown) <= lim + 40 else 0
        out["display_has_more_hint"] = 1 if (len(body) <= lim or "后略" in shown) else 0
        out["display_keeps_body"] = 1 if "很长的正文内容" in shown else 0
    except Exception as e:      # noqa: silent-ok
        LOG.debug("基准②跑不了：%s", e)
        out["display_within_limit"] = -1
        out["display_has_more_hint"] = -1
        out["display_keeps_body"] = -1
    # ③ 路由粘性：短时间内同一档不该反复换模型
    try:
        from core import model_router as MR
        MR.reset() if hasattr(MR, "reset") else None
        m1, _t, _w = MR.route("帮我写一个 Python 快速排序函数", "chat")
        m2, _t, _w = MR.route("帮我写一个 Python 冒泡排序函数", "chat")
        out["router_no_flip"] = 1 if (m1 == m2) else 0
        out["router_picks_something"] = 1 if bool(m1) else 0
    except Exception as e:      # noqa: silent-ok
        LOG.debug("基准③跑不了：%s", e)
        out["router_no_flip"] = -1
        out["router_picks_something"] = -1
    return out


def _bench_offline_eval():
    """项目自己的离线评测层（确定性、不调模型）。跑不起来就返回空 dict。"""
    out = {}
    try:
        import importlib.util
        path = os.path.join(_ROOT, "tools", "eval_xiaojiao.py")
        spec = importlib.util.spec_from_file_location("_eval_xiaojiao_for_gate", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)          # noqa: S301 — 这是本仓库自己的评测脚本
        app = mod._app()
        for name, fn in getattr(mod, "OFFLINE", []):
            try:
                ok = bool(getattr(mod, fn)(app))
            except Exception:      # noqa: silent-ok — 单条用例异常计 0 分
                ok = False
            out["eval_" + str(name)] = 1 if ok else 0
    except Exception as e:      # noqa: silent-ok — 评测脚本跑不起来就只用量载基
        LOG.debug("离线评测层跑不起来（只用载体微基准）：%s", e)
    return out


def bench(suite="all"):
    """跑一套判据，返回 {用例名: 1/0/-1}。`suite` 可指定 carrier / eval / all。"""
    res = {}
    if suite in ("all", "carrier"):
        res.update(_bench_carrier())
    if suite in ("all", "eval"):
        res.update(_bench_offline_eval())
    return res


def _score(res):
    """把逐条结果压成一个可比较的数：通过 / 有效条数（-1 的"量不出来"不计入分母）。"""
    vals = [v for v in res.values() if v in (0, 1)]
    if not vals:
        return 0.0, 0
    return round(sum(vals) / float(len(vals)), 4), len(vals)


# ============================== 候选与决策 ==============================
def propose(name, knob, new_value, why="", suite="all"):
    """提一个候选：只动**一个**旋钮。返回候选 dict（不落地，先量）。

    合法性在这些地方挡住：旋钮必须在白名单、取值必须在允许集合、
    并且给出当前值 —— 候选里必须写明"从多少改到多少"，不许含糊。
    """
    name = str(name or "").strip() or "未命名改动"
    spec = KNOBS.get(str(knob or ""))
    if not spec:
        return {"ok": False, "why": "没有这个旋钮（只能是：%s）" % "、".join(sorted(KNOBS))}
    allowed = spec.get("allowed") or []
    if allowed and new_value not in allowed:
        return {"ok": False, "why": "取值 %r 不在允许范围内 %s" % (new_value, allowed)}
    try:
        old = knob_read(knob)
    except Exception as e:      # noqa: silent-ok — 读不到当前值就没法配对比较
        return {"ok": False, "why": "读不到旋钮当前值：%s" % e}
    if old == new_value:
        return {"ok": False, "why": "新值和当前值一样（%r），没有必要改" % (old,)}
    return {"ok": True, "id": time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6],
            "name": name, "knob": knob, "old": old, "new": new_value,
            "why": str(why or "")[:200], "suite": suite,
            "desc": spec.get("desc") or "",
            "at": time.strftime("%Y-%m-%dT%H:%M:%S")}


def measure(cand, base=None):
    """配对测量：同一套判据，改前 / 改后各跑一遍，逐条比。

    `base` 可以传入已跑好的基线（省一半时间）；不传就现跑。
    返回 {"before","after","delta","regressions","improvements","n","unknown"}。
    """
    if not cand or not cand.get("ok", True) or not cand.get("knob"):
        return {"ok": False, "why": "候选不合法"}
    suite = cand.get("suite") or "all"
    knob = cand["knob"]
    old, new = cand["old"], cand["new"]
    try:
        if base is None:
            knob_write(knob, old)
            base = bench(suite)
        knob_write(knob, new)
        after = bench(suite)
    finally:
        # 无论测量成功与否，旋钮都要回到原值 —— 测量不许留下副作用
        try:
            knob_write(knob, old)
        except Exception as e:      # noqa: silent-ok
            LOG.warning("旋钮复原失败（%s=%r）：%s", knob, old, e)
    before = dict(base or {})
    # 【必须配对】**只在两边都有的用例上比**：调用方传进来的基线可能是更窄的套件
    #   （比如只跑了载体微基准），而这次跑的是全套 —— 拿 7 条的分母去比 30 条的分母，
    #   算出来的"提升"是分母变化，不是改动带来的（实测踩过：分母一换，凭空 +0.11）。
    keys = sorted(set(before) & set(after))
    only_before = sorted(set(before) - set(after))
    only_after = sorted(set(after) - set(before))
    regressions, improvements, unknown = [], [], []
    for k in keys:
        b, a = before.get(k, -1), after.get(k, -1)
        if b == -1 or a == -1:
            unknown.append(k)
        elif a < b:
            regressions.append({"case": k, "before": b, "after": a})
        elif a > b:
            improvements.append({"case": k, "before": b, "after": a})
    sb, nb = _score({k: before[k] for k in keys})
    sa, na = _score({k: after[k] for k in keys})
    return {"ok": True, "before": sb, "after": sa, "delta": round(sa - sb, 4),
            "n": min(nb, na) if (nb and na) else max(nb, na),
            "paired_cases": len(keys),
            "unpaired": (only_before + only_after)[:8],
            "regressions": regressions, "improvements": improvements,
            "unknown": unknown}


def decide(cand, meas, allow_tie=False):
    """按硬规矩给结论：**有退步就不落地**。

    返回 {"accept": bool, "why": str, "verdict": improved|tie|worse|unknown}
    """
    if not meas or not meas.get("ok"):
        return {"accept": False, "verdict": "unknown",
                "why": "量不出来（%s）" % (meas or {}).get("why", "基准没跑成")}
    d = float(meas.get("delta") or 0.0)
    reg = meas.get("regressions") or []
    unk = meas.get("unknown") or []
    if not meas.get("n"):
        return {"accept": False, "verdict": "unknown", "why": "基准一条用例都没跑成，不敢下结论"}
    if reg:
        return {"accept": False, "verdict": "worse",
                "why": "有 %d 条退步（%s），按规矩不落地" % (
                    len(reg), "、".join(x["case"] for x in reg[:3]))}
    if d > 0:
        return {"accept": True, "verdict": "improved",
                "why": "总分 %+.4f 且零退步" % d}
    if d == 0 and allow_tie:
        return {"accept": True, "verdict": "tie",
                "why": "总分持平、零退步，按 allow_tie 接受（用于压成本/降噪）"}
    if unk:
        return {"accept": False, "verdict": "unknown",
                "why": "总分无提升，且有 %d 条量不出来（%s）" % (len(unk), "、".join(unk[:3]))}
    return {"accept": False, "verdict": "tie", "why": "总分持平、没有收益，不值得改"}


def _load_applied():
    try:
        with io.open(_APPLIED, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:      # noqa: silent-ok — 没有落地记录就是空
        return {}


def _save_applied(d):
    _ensure()
    tmp = _APPLIED + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(json.dumps(d, ensure_ascii=False, indent=1))
    os.replace(tmp, _APPLIED)


def _log_decision(row):
    _ensure()
    try:
        with io.open(_DECISIONS, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as e:      # noqa: silent-ok — 记录写不下也不影响结论
        LOG.debug("闸门决策写入失败（忽略）：%s", e)


def commit(cand, meas, dec):
    """落地一个通过的候选：写旋钮 + 记决策 + 记进 applied.json（带 revert 信息）。"""
    if not dec.get("accept"):
        return {"ok": False, "why": "决策是「不落地」：%s" % dec.get("why")}
    knob, new, old = cand["knob"], cand["new"], cand["old"]
    try:
        knob_write(knob, new)
    except Exception as e:      # noqa: silent-ok — 写不进去就如实失败
        return {"ok": False, "why": "写旋钮失败：%s" % e}
    ap = _load_applied()
    ap[knob] = {"value": new, "from": old, "name": cand.get("name"),
                "cand": cand.get("id"), "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    try:
        _save_applied(ap)
    except Exception as e:      # noqa: silent-ok
        LOG.debug("applied.json 写入失败（忽略）：%s", e)
    row = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "cand": cand.get("id"),
           "name": cand.get("name"), "knob": knob, "old": old, "new": new,
           "why": cand.get("why"), "before": meas.get("before"), "after": meas.get("after"),
           "delta": meas.get("delta"), "regressions": meas.get("regressions"),
           "improvements": meas.get("improvements"), "verdict": dec.get("verdict"),
           "decision": "accept", "note": dec.get("why")}
    _log_decision(row)
    LOG.info("自我改进：落地 %s（%s: %r → %r，总分 %s → %s）",
             cand.get("name"), knob, old, new, meas.get("before"), meas.get("after"))
    # 经验库里也留一条（下次遇到同类改动可以参考"以前这样调过、量出来是这样"）
    try:
        from core import experience as EXP
        EXP.record("gate_evolve", True, need=str(cand.get("name"))[:100],
                   stage="evolve", lesson="%s %r→%r，总分 %+.4f，零退步" % (
                       knob, old, new, float(meas.get("delta") or 0)))
    except Exception as e:      # noqa: silent-ok
        LOG.debug("经验记录失败（忽略）：%s", e)
    return {"ok": True, "knob": knob, "value": new}


def reject(cand, meas, dec):
    """明确记一条"提过但没落地"（这一步是反粉饰的关键：不许只记成功的）。"""
    row = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "cand": cand.get("id"),
           "name": cand.get("name"), "knob": cand.get("knob"),
           "old": cand.get("old"), "new": cand.get("new"), "why": cand.get("why"),
           "before": (meas or {}).get("before"), "after": (meas or {}).get("after"),
           "delta": (meas or {}).get("delta"),
           "regressions": (meas or {}).get("regressions"),
           "verdict": dec.get("verdict"), "decision": "reject", "note": dec.get("why")}
    _log_decision(row)
    try:
        from core import experience as EXP
        EXP.record("gate_evolve", False, why=str(dec.get("why"))[:160],
                   need=str(cand.get("name"))[:100], stage="evolve",
                   lesson="这次改动过不了闸门：%s" % dec.get("why"))
    except Exception as e:      # noqa: silent-ok
        LOG.debug("经验记录失败（忽略）：%s", e)
    return {"ok": True, "decision": "reject"}


def attempt(name, knob, new_value, why="", suite="all", allow_tie=False, base=None):
    """一步到位：提 → 量 → 判 → 落地/拒绝。返回 (结果 dict, 是否落地)。

    这是给 `core/auto_evolve.py` 和插件用的主入口：**没有"直接改"这条路**，
    任何改动都得走完这四步。
    """
    cand = propose(name, knob, new_value, why, suite)
    if not cand.get("ok"):
        return ({"ok": False, "why": cand.get("why")}, False)
    meas = measure(cand, base=base)
    dec = decide(cand, meas, allow_tie=allow_tie)
    if dec.get("accept"):
        r = commit(cand, meas, dec)
        r["measure"] = meas
        r["decision"] = dec
        return (r, bool(r.get("ok")))
    r = reject(cand, meas, dec)
    r["measure"] = meas
    r["decision"] = dec
    return (r, False)


# ============================== 回滚 / 复原 / 历史 ==============================
def rollback(knob):
    """把一个已落地的旋钮退回它落地前的值（决策记录里带着当时的 old）。"""
    ap = _load_applied()
    rec = ap.get(str(knob))
    if not rec:
        return {"ok": False, "why": "这个旋钮没有落地记录，没什么可回滚的"}
    try:
        knob_write(knob, rec.get("from"))
    except Exception as e:      # noqa: silent-ok
        return {"ok": False, "why": "回滚失败：%s" % e}
    row = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "knob": knob,
           "decision": "rollback", "old": rec.get("value"), "new": rec.get("from"),
           "note": "手动回滚"}
    _log_decision(row)
    ap.pop(knob, None)
    try:
        _save_applied(ap)
    except Exception as e:      # noqa: silent-ok
        LOG.debug("applied.json 写入失败（忽略）：%s", e)
    LOG.info("自我改进：回滚 %s → %r", knob, rec.get("from"))
    return {"ok": True, "knob": knob, "value": rec.get("from")}


def restore_applied():
    """进程启动时调用：把已落地的旋钮值重新写回模块（否则重启就悄悄退回了旧值）。"""
    ap = _load_applied()
    done = []
    for knob, rec in (ap or {}).items():
        if knob not in KNOBS:
            continue
        try:
            knob_write(knob, rec.get("value"))
            done.append(knob)
        except Exception as e:      # noqa: silent-ok — 单个旋钮写不回不影响别的
            LOG.debug("复原旋钮 %s 失败：%s", knob, e)
    if done:
        LOG.info("自我改进：已复原 %d 个落地旋钮（%s）", len(done), "、".join(done))
    return done


def history(limit=40):
    """最近的决策（含被拒绝的 —— 只记成功的那种历史没法复盘）。"""
    rows = []
    try:
        if os.path.isfile(_DECISIONS):
            for ln in io.open(_DECISIONS, encoding="utf-8").read().split("\n"):
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    rows.append(json.loads(ln))
                except Exception:      # noqa: silent-ok — 坏一行跳过
                    continue
    except Exception as e:      # noqa: silent-ok
        LOG.debug("闸门历史读取失败（忽略）：%s", e)
    return rows[-int(limit):]


def stats():
    rows = history(limit=1000)
    acc = [r for r in rows if r.get("decision") == "accept"]
    rej = [r for r in rows if r.get("decision") == "reject"]
    rb = [r for r in rows if r.get("decision") == "rollback"]
    gains = [float(r.get("delta") or 0) for r in acc]
    return {"decisions": len(rows), "accepted": len(acc), "rejected": len(rej),
            "rolled_back": len(rb),
            "avg_gain": round(sum(gains) / len(gains), 4) if gains else 0.0,
            "knobs": sorted(KNOBS), "applied": _load_applied(), "dir": _DIR}


def report_md(limit=20):
    """给人看的闸门报告（数字全部来自 decisions.jsonl，没有手写）。"""
    st = stats()
    rows = history(limit)
    lines = ["# 自我改进闸门（`core/gate_evolve.py` 实算）", "",
             "> 数字由 `python tools/evolve_gate.py --save` 生成，不是手写的。", "",
             "## 总览", "",
             "- 决策：**%d** 次 ｜ 落地 **%d** ｜ 拒绝 **%d** ｜ 回滚 **%d**" % (
                 st["decisions"], st["accepted"], st["rejected"], st["rolled_back"]),
             "- 落地改动的平均增益：**%+.4f**（按通过率算）" % st["avg_gain"],
             "- 可调旋钮：%s" % "、".join("`%s`" % k for k in st["knobs"]),
             "- 当前已落地：%s" % (
                 "、".join("`%s`=%r" % (k, v.get("value")) for k, v in (st["applied"] or {}).items())
                 or "（无）"),
             "", "## 最近 %d 次决策" % len(rows), "",
             "| 时间 | 改动 | 旋钮 | 改前→改后 | 分数 前→后 | 结论 | 说明 |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in reversed(rows):
        lines.append("| %s | %s | `%s` | %r → %r | %s → %s | %s | %s |" % (
            str(r.get("at") or "")[5:16], str(r.get("name") or "")[:24],
            r.get("knob"), r.get("old"), r.get("new"),
            r.get("before"), r.get("after"),
            {"accept": "落地", "reject": "拒绝", "rollback": "回滚"}.get(
                r.get("decision"), r.get("decision")),
            str(r.get("note") or "")[:60]))
    if not rows:
        lines.append("| — | （还没有决策记录） |  |  |  |  |  |")
    return "\n".join(lines)
