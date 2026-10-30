# -*- coding: utf-8 -*-
"""小焦 · 好友（2026-10-30）

【用户要的东西，原话】
  「不是这样，是聊天单独的聊天好友，聊天好友页面，用户定义角色，然后定义后他就是一个好友，
   这个好友跟活着一样有他自己的朋友圈等等，也可以和用户聊天培养感情，不要只等用户去发给他信息，
   他有事情也会主动找用户，去定义每个人而不是朋友圈，还有这个朋友圈是他自己发不是我们点击才发，
   把这个点击才发的模块去掉」

所以这个模块的模型是：**每个 AI 是一个好友**。
  · 用户先定义这个好友（名字 / 性格 / 关系 / 头像 / 火种）——定义一次，他就是一个"人"；
  · 每个好友有**自己的**：一对一聊天记录、朋友圈（他自己的动态）；
  · 他会**主动**找用户说话（`proactive_tick` 由载体判断该不该说，模型负责说什么），
    不需要用户先开口；每次主动都记账（为什么发、多久没聊、说没说得成）；
  · 聊天记录、未读数、最近一次互动都落盘 `logs/friends/<名字>.json`。

【边界】
  · 主动说话是**载体掷骰 + 冷却 + 每日上限**共同决定，不是"每轮必发"，也不会刷屏；
  · 模型没应答就不发（不编一句"在吗"糊弄），事件账里写明；
  · 好友 ≠ 模型：好友是"人设"，火种是"脑子"，同一个好友可以换火种，记忆与关系不变。
"""
import io
import json
import logging
import os
import random
import re
import threading
import time

LOG = logging.getLogger(__name__)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DIR = os.path.join(_ROOT, "logs", "friends")
_LOCK = threading.RLock()

_LLM = None
_ALT = None
_MODEL = ""

DEFAULTS = {
    "enabled": True,
    "check_interval_s": 180,     # 多久看一次"有没有话想说"
    "min_gap_min": 45,           # 同一个好友两条主动消息至少隔多久
    "prob": 0.35,                # 每次检查有多少几率想说话
    "max_per_day": 6,            # 每个好友每天最多主动几条
    "max_msgs": 300,             # 每个好友保留多少条聊天
}
_CFG = dict(DEFAULTS)


def _cfg_num(k, d):
    v = _CFG.get(k)
    if v is None or v == "":
        return float(d)
    try:
        return float(v)
    except Exception:      # noqa: silent-ok
        return float(d)


def install(llm_fn=None, alt_fn=None, model_name=""):
    global _LLM, _ALT, _MODEL
    if llm_fn is not None:
        _LLM = llm_fn
    if alt_fn is not None:
        _ALT = alt_fn
    if model_name:
        _MODEL = str(model_name)


def configure(**kw):
    for k, v in (kw or {}).items():
        if k in _CFG and v is not None:
            _CFG[k] = v
    return dict(_CFG)


def _ensure():
    os.makedirs(_DIR, exist_ok=True)


def _safe(name):
    return re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fa5]", "_", str(name or "好友"))[:40] or "friend"


def _path(name):
    return os.path.join(_DIR, _safe(name) + ".json")


def _load(name):
    try:
        with io.open(_path(name), encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            d.setdefault("messages", [])
            return d
    except Exception:      # noqa: silent-ok — 没有就是新的
        pass
    return {"name": str(name), "messages": [], "last_read_n": 0,
            "last_proactive_ts": "", "created": time.strftime("%Y-%m-%dT%H:%M:%S")}


def _save(name, d):
    _ensure()
    with _LOCK:
        tmp = _path(name) + ".tmp"
        with io.open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(json.dumps(d, ensure_ascii=False, indent=1))
        os.replace(tmp, _path(name))


def _event(kind, **kw):
    try:
        _ensure()
        row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": kind}
        row.update(kw)
        with io.open(os.path.join(_DIR, "events.jsonl"), "a", encoding="utf-8", newline="") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as e:      # noqa: silent-ok
        LOG.debug("好友记账失败：%s", e)


def _persona(name):
    try:
        from core import personas as PS
        p = PS.get(name)
        if (not p.get("persona")) and (not p.get("relation")):
            return None
        return p
    except Exception:      # noqa: silent-ok
        return None


def _personas_all():
    try:
        from core import personas as PS
        return [x for x in (PS.list_all() or []) if x.get("name")]
    except Exception:      # noqa: silent-ok
        return []


def _ask(messages, temperature=0.9):
    if _LLM is None:
        return "", ""
    for _t in (1, 2):
        try:
            txt = str(_LLM(messages, temperature=temperature) or "").strip()
        except Exception as e:      # noqa: silent-ok
            LOG.debug("好友·第%d次调用失败：%s", _t, e)
            txt = ""
        if len(txt) >= 2:
            return txt, (_MODEL or "当前火种")
    if _ALT is not None:
        try:
            txt, who = _ALT(messages, temperature)
            if len(str(txt or "")) >= 2:
                return txt, (who or "备用火种")
        except Exception as e:      # noqa: silent-ok
            LOG.debug("好友·换火种失败：%s", e)
    return "", ""


# ==================== 好友列表 / 一对一聊天 ====================
def list_friends():
    """所有人设都是"好友"；带上未读数、最近一条、朋友圈条数。"""
    out = []
    for p in _personas_all():
        nm = p.get("name")
        d = _load(nm)
        msgs = d.get("messages") or []
        last = msgs[-1] if msgs else {}
        n0 = int(d.get("last_read_n") or 0)
        unread = sum(1 for m in msgs[n0:] if m.get("from") == "friend")
        try:
            from core import moments as MO
            n_moments = len(MO.list_posts(limit=200, author=nm) or [])
        except Exception:      # noqa: silent-ok
            n_moments = 0
        out.append({"name": nm, "relation": p.get("relation") or "",
                    "persona": (p.get("persona") or "")[:80], "avatar": p.get("avatar") or "",
                    "model": p.get("model") or "", "unread": unread,
                    "moments": n_moments, "messages": len(msgs),
                    "last": str(last.get("text") or "")[:60],
                    "last_from": last.get("from") or "",
                    "last_ts": last.get("ts") or ""})
    out.sort(key=lambda x: str(x.get("last_ts") or ""), reverse=True)
    return out


def history(name, limit=100):
    d = _load(name)
    return (d.get("messages") or [])[-int(limit or 100):]


def mark_read(name):
    d = _load(name)
    d["last_read_n"] = len(d.get("messages") or [])
    _save(name, d)
    return {"ok": True, "n": d["last_read_n"]}


def _append(name, from_, text, by="", why=""):
    d = _load(name)
    msg = {"id": "%d%03d" % (int(time.time() * 1000), random.randint(0, 999)),
           "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "from": from_,
           "text": str(text or "")[:1500], "by": by, "why": why}
    d.setdefault("messages", []).append(msg)
    d["messages"] = d["messages"][-int(_cfg_num("max_msgs", 300)):]
    if from_ == "friend":
        d["last_proactive_ts"] = msg["ts"]
    _save(name, d)
    return msg


def _ctx_msgs(name, limit=10):
    """把最近几句拼成模型能看懂的上下文。"""
    who = _persona(name) or {"name": name}
    me = who.get("name") or name
    rel = who.get("relation") or ""
    lines = []
    for m in history(name, limit):
        lines.append("%s：%s" % ("你" if m.get("from") == "friend" else "他", m.get("text")))
    head = "你是%s" % me
    if rel:
        head += "（他给你的关系/身份：%s）" % rel
    head += "。"
    if who.get("persona"):
        head += "你的人物设定：" + str(who.get("persona"))[:400]
    return head, "\n".join(lines)


def say(name, text):
    """用户对某个好友说一句 → 他回（走快速一对一，不折腾工具）。"""
    text = str(text or "").strip()
    if not text:
        return {"ok": False, "error": "空消息"}
    if _persona(name) is None:
        return {"ok": False, "error": "没有这个好友（先在好友页定义角色）"}
    _append(name, "user", text)
    _event("user_say", friend=name, chars=len(text))
    head, ctx = _ctx_msgs(name)
    sys_p = (head + " 你们在微信一样的一对一聊天。像真人那样回他：短、口语、有情绪，"
             "可以反问一句。不要复述他说的话，不要客套。只输出你要说的话，40 字以内。")
    txt, by = _ask([{"role": "system", "content": sys_p},
                    {"role": "user", "content": "最近的对话：\n%s\n\n他刚说：%s" % (
                        ctx[-600:], text)}])
    if not txt:
        _event("reply_skip", friend=name, why="模型没应答（不编一句假的）")
        return {"ok": True, "reply": None, "why": "模型这次没应答"}
    msg = _append(name, "friend", txt, by=by, why="回你")
    _event("reply", friend=name, chars=len(txt), by=by)
    return {"ok": True, "reply": msg}


def proactive(name, force=False):
    """这个好友**自己**想起一件事，主动找你（不需要你先说话）。"""
    if _persona(name) is None:
        return None, "不是好友（先定义角色）"
    if not _CFG.get("enabled", True) and not force:
        return None, "好友主动说话开关是关的"
    d = _load(name)
    msgs = d.get("messages") or []
    today = time.strftime("%Y-%m-%d")
    n_today = sum(1 for m in msgs
                  if m.get("from") == "friend" and str(m.get("ts") or "").startswith(today)
                  and (m.get("why") or "") != "回你")
    if not force and n_today >= int(_cfg_num("max_per_day", 6)):
        return None, "今天他已经主动找过你 %d 次了" % n_today
    if not force and msgs:
        try:
            last = time.mktime(time.strptime(str(msgs[-1]["ts"]), "%Y-%m-%dT%H:%M:%S"))
            gap = (time.time() - last) / 60.0
            need = _cfg_num("min_gap_min", 45)
            if gap < need:
                return None, "才 %.0f 分钟没说话（至少 %d 分钟）" % (gap, need)
        except Exception:      # noqa: silent-ok
            pass
    roll = random.random()
    prob = _cfg_num("prob", 0.35)
    if not force and roll > prob:
        _event("skip", friend=name, why="掷骰没中", roll=round(roll, 3), prob=prob)
        return None, "掷骰 %.2f > %.2f，这次不想说" % (roll, prob)
    head, ctx = _ctx_msgs(name)
    # 他最近发的朋友圈也能当话题
    own_moments = ""
    try:
        from core import moments as MO
        ps = MO.list_posts(limit=3, author=name) or []
        if ps:
            own_moments = "；".join(str(p.get("text"))[:60] for p in ps)
    except Exception:      # noqa: silent-ok
        own_moments = ""
    sys_p = (head + " 现在没人跟你说话。你自己忽然想起一件事（或想问他一句），"
             "**主动**给他发条消息：一两句，像真人随手发的那种，不要客套开场，"
             "不要说「在吗」这种废话。只输出这条消息。")
    usr = "你们最近的对话：\n%s" % (ctx[-500:] or "（还没聊过）")
    if own_moments:
        usr += "\n你最近发过的动态：%s" % own_moments
    txt, by = _ask([{"role": "system", "content": sys_p},
                    {"role": "user", "content": usr}], temperature=0.95)
    if not txt:
        _event("skip", friend=name, why="模型没应答（宁可不发也不编）")
        return None, "模型这次没应答"
    why = "自己想起来找你说" if msgs else "第一次主动打招呼"
    msg = _append(name, "friend", txt, by=by, why=why)
    _event("proactive", friend=name, chars=len(txt), by=by, why=why)
    LOG.info("好友主动：%s → %s", name, str(txt)[:60])
    # 【他有自己的生活】顺手发一条自己的朋友圈（35% 几率），内容也是他自己写的
    try:
        if random.random() < 0.35:
            from core import moments as _MO
            _mtxt, _mby, _ = _MO.compose(
                context="我最近在想：%s\n我刚跟朋友说：%s" % (ctx[-200:] or "（没什么）", txt),
                author=name)
            if _mtxt:
                _MO.publish(_mtxt, author=name, by=_mby, source="self",
                            why="自己想起来发的")
                _event("moment", friend=name, chars=len(_mtxt))
                LOG.info("好友动态：%s 自己发了一条（%d 字）", name, len(_mtxt))
    except Exception as _e:      # noqa: silent-ok — 发动态失败不影响这次主动说话
        LOG.debug("好友发动态失败（忽略）：%s", _e)
    return msg, why


def proactive_tick():
    """载体循环调它：轮着看每个好友"想不想说话"。"""
    if not _CFG.get("enabled", True):
        return []
    out = []
    names = [f["name"] for f in list_friends()]
    random.shuffle(names)
    for nm in names:
        try:
            msg, why = proactive(nm)
        except Exception as e:      # noqa: silent-ok — 一个人挂了不影响别人
            LOG.debug("好友主动失败（%s）：%s", nm, e)
            msg, why = None, str(e)[:60]
        if msg:
            out.append({"friend": nm, "text": msg.get("text"), "why": why})
    return out


def stats():
    fs = list_friends()
    return {"friends": len(fs), "unread": sum(f["unread"] for f in fs),
            "messages": sum(f["messages"] for f in fs),
            "moments": sum(f["moments"] for f in fs), "cfg": dict(_CFG), "path": _DIR}
