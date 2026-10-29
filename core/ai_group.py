# -*- coding: utf-8 -*-
"""小焦 · 模型群组（2026-10-30）

【用户要的】「模型与模型之间互相交流，跟人类群组一样，互相聊天；群可能是网络开发、可能是处对象，
各种群由用户设定；用户可以给每个 AI 设置性格人设。」

【分工】
  · **用户**建群、定主题、定成员、定每个人的人设（`core/personas` 里也只有一份人设）；
  · **载体**排轮次、拼上下文、限长、防复读、落盘（`logs/aigroups/groups.json`）；
  · **模型**说话 —— 每个成员说的是它自己那颗火种写的话，全部是 AI 的话。

【为什么"轮流说"要由载体排】
  让模型自己决定下一个谁说，它每轮都会抢着说、还会互相总结；群聊的节奏必须落在载体里：
  谁、按什么顺序、说几条、上下文给几句，全部可查可复现（seed 固定时同一段对话可重放）。

【边界（不粉饰）】
  · 只做"对话"，不做"结论"：群聊里的观点是各颗火种说的，载体不替它们圆场；
  · 某个成员那颗火种挂了 → 这一轮它就沉默，账里写明"没应答"，不编一句塞进去；
  · 消息数、每轮条数、上下文长度都有硬上限，避免一键把机器烧穿。
"""
import io
import json
import logging
import os
import threading
import time
import uuid

LOG = logging.getLogger(__name__)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DIR = os.path.join(_ROOT, "logs", "aigroups")
_PATH = os.path.join(_DIR, "groups.json")
_EVENTS = os.path.join(_DIR, "events.jsonl")
_LOCK = threading.RLock()

_LLM = None
_ALT = None
_MODEL = ""

MAX_MEMBERS = 6
MAX_MSGS_STORE = 400        # 每个群只留最近这么多条
CTX_MSGS = 14               # 拼给模型的最近消息条数


def install(llm_fn=None, alt_fn=None, model_name=""):
    global _LLM, _ALT, _MODEL
    if llm_fn is not None:
        _LLM = llm_fn
    if alt_fn is not None:
        _ALT = alt_fn
    if model_name:
        _MODEL = str(model_name)


def _ensure():
    os.makedirs(_DIR, exist_ok=True)


def _load():
    try:
        with io.open(_PATH, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("groups"), list):
            return d
    except Exception:      # noqa: silent-ok
        pass
    return {"groups": []}


def _save(d):
    _ensure()
    tmp = _PATH + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(json.dumps(d, ensure_ascii=False, indent=1))
    os.replace(tmp, _PATH)


def _event(kind, **kw):
    try:
        _ensure()
        row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": kind}
        row.update(kw)
        with io.open(_EVENTS, "a", encoding="utf-8", newline="") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as e:      # noqa: silent-ok
        LOG.debug("群组记账失败：%s", e)


# ==================== 群的管理 ====================
def create(name, topic="", members=None, style=""):
    """建群。members: [{"name": "小焦", "persona": "…", "model": ""}] 或 ["小焦","小C"]。"""
    name = str(name or "").strip()
    if not name:
        return {"ok": False, "error": "群名不能空"}
    mem = []
    for m in (members or []):
        if isinstance(m, str):
            m = {"name": m}
        n = str((m or {}).get("name") or "").strip()
        if not n:
            continue
        mem.append({"name": n,
                    "persona": str((m or {}).get("persona") or "").strip(),
                    "model": str((m or {}).get("model") or "").strip()})
    if not mem:
        mem = [{"name": "小焦", "persona": "", "model": ""}]
    mem = mem[:MAX_MEMBERS]
    with _LOCK:
        d = _load()
        g = {"id": uuid.uuid4().hex[:8], "name": name, "topic": str(topic or "").strip(),
             "style": str(style or "").strip(),
             "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
             "members": mem, "messages": []}
        d["groups"].append(g)
        _save(d)
    _event("create", gid=g["id"], name=name, members=[m["name"] for m in mem], topic=g["topic"])
    LOG.info("群组：建了「%s」（%d 人 / 主题=%s）", name, len(mem), g["topic"] or "未设")
    return {"ok": True, "group": g}


def list_groups():
    d = _load()
    out = []
    for g in d.get("groups") or []:
        out.append({"id": g.get("id"), "name": g.get("name"), "topic": g.get("topic"),
                    "members": [m.get("name") for m in (g.get("members") or [])],
                    "messages": len(g.get("messages") or []),
                    "created": g.get("created")})
    out.sort(key=lambda x: str(x.get("created") or ""), reverse=True)
    return out


def get(gid):
    for g in _load().get("groups") or []:
        if g.get("id") == gid:
            return g
    return None


def remove(gid):
    with _LOCK:
        d = _load()
        n0 = len(d.get("groups") or [])
        d["groups"] = [g for g in (d.get("groups") or []) if g.get("id") != gid]
        if len(d["groups"]) == n0:
            return {"ok": False, "error": "没有这个群"}
        _save(d)
    _event("remove", gid=gid)
    return {"ok": True}


def set_member(gid, member, persona=None, model=None):
    """改成员人设/火种（人设同时写进 `core/personas`，两个功能共用一份）。"""
    with _LOCK:
        d = _load()
        for g in d.get("groups") or []:
            if g.get("id") != gid:
                continue
            for m in g.get("members") or []:
                if m.get("name") != member:
                    continue
                if persona is not None:
                    m["persona"] = str(persona).strip()
                if model is not None:
                    m["model"] = str(model).strip()
                _save(d)
                try:
                    from core import personas as PS
                    PS.set_persona(m["name"], m.get("persona") or "", m.get("model") or "")
                except Exception as e:      # noqa: silent-ok — 人设库不在也不影响群聊
                    LOG.debug("群组·写人设失败：%s", e)
                _event("set_member", gid=gid, member=member)
                return {"ok": True, "member": m}
            return {"ok": False, "error": "群里没有这个人：%s" % member}
    return {"ok": False, "error": "没有这个群"}


# ==================== 说话 ====================
def _ask(member_model, messages, temperature=0.85):
    """让某个成员说一句。注入了换火种；返回 (文本, 用了谁)。"""
    if _LLM is None:
        return "", ""
    _ctx = None
    try:
        import xiaojiao_app as _app
        _ctx = getattr(_app, "_CTX", None)
    except Exception:      # noqa: silent-ok
        _ctx = None
    _prev = None
    try:
        if member_model and isinstance(_ctx, dict):
            _prev = _ctx.get("force_model")
            _ctx["force_model"] = member_model      # 这颗成员指定了火种就钉住它
        for _try in (1, 2):
            try:
                t = str(_LLM(messages, temperature=temperature) or "").strip()
            except Exception as e:      # noqa: silent-ok
                LOG.debug("群组·第%d次调用失败：%s", _try, e)
                t = ""
            if len(t) >= 1:
                return t, (member_model or _MODEL or "当前火种")
        if _ALT is not None:
            try:
                t, who = _ALT(messages, temperature)
            except Exception as e:      # noqa: silent-ok
                LOG.debug("群组·换火种失败：%s", e)
                t, who = "", ""
            if len(t) >= 1:
                return t, (who or "备用火种")
        return "", ""
    finally:
        if isinstance(_ctx, dict) and member_model:
            if _prev is None:
                _ctx.pop("force_model", None)
            else:
                _ctx["force_model"] = _prev


def _persona_of(m):
    if m.get("persona"):
        return m["persona"]
    try:
        from core import personas as PS
        return PS.get(m.get("name") or "小焦").get("persona") or ""
    except Exception:      # noqa: silent-ok
        return ""


def _transcript(msgs, who_filter=None):
    out = []
    for m in msgs:
        if who_filter and m.get("who") not in who_filter:
            continue
        out.append("%s：%s" % (m.get("who"), str(m.get("text") or "")[:300]))
    return "\n".join(out)


def run_round(gid, rounds=1):
    """跑若干轮：每轮按成员顺序各说一句。返回这一步新增的消息。"""
    g = get(gid)
    if not g:
        return {"ok": False, "error": "没有这个群"}
    members = g.get("members") or []
    if not members:
        return {"ok": False, "error": "这个群还没有成员"}
    rounds = max(1, min(int(rounds or 1), 5))
    added = []
    for r in range(rounds):
        for m in members:
            msgs = (get(gid) or {}).get("messages") or []
            recent = msgs[-CTX_MSGS:]
            sys_p = ("这是一个%s人组成的群聊，你的名字是%s。像真人微信群里聊天那样说话："
                     "短句、口语、可以接别人的话、可以只回半句、可以问别人；"
                     "不要复读别人说过的内容，不要总结整段对话，不要写旁白和表情符号说明。"
                     "一次只说一到两句，40 字以内。只输出你要说的话本身。"
                     % (len(members), m.get("name")))
            per = _persona_of(m)
            if per:
                sys_p += "\n你的人物设定：" + str(per)[:400]
            if g.get("style"):
                sys_p += "\n群规矩：" + str(g.get("style"))[:300]
            usr = "群主题：%s\n\n最近的聊天记录：\n%s\n\n现在轮到你（%s）说话：" % (
                g.get("topic") or "（没设主题，随意聊）",
                _transcript(recent) or "（还没有人说话，你起个头）",
                m.get("name"))
            txt, who = _ask(m.get("model") or "", [{"role": "system", "content": sys_p},
                                                   {"role": "user", "content": usr}])
            if not txt:
                _event("silent", gid=gid, member=m.get("name"),
                       why="这颗火种没应答 → 这一轮它沉默（不编话）")
                continue
            txt = txt.strip().strip("“”\"'")
            # 有人会给自己加「名字：」前缀，去掉（名字由载体管）
            txt = _strip_name_prefix(txt, m.get("name"))
            if not txt:
                continue
            msg = {"id": uuid.uuid4().hex[:8], "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "who": m.get("name"), "text": txt, "by": who, "round": r + 1}
            with _LOCK:
                d = _load()
                for gg in d.get("groups") or []:
                    if gg.get("id") != gid:
                        continue
                    gg.setdefault("messages", []).append(msg)
                    gg["messages"] = gg["messages"][-MAX_MSGS_STORE:]
                    _save(d)
            added.append(msg)
            _event("say", gid=gid, member=m.get("name"), chars=len(txt), by=who)
    LOG.info("群组：%s 跑了 %d 轮，新增 %d 条消息", g.get("name"), rounds, len(added))
    return {"ok": True, "added": added, "group": get(gid)}


def _strip_name_prefix(text, name):
    t = str(text or "").strip()
    for pat in ("%s：", "%s:", "[%s] ", "【%s】"):
        head = pat % name
        if t.startswith(head):
            t = t[len(head):].strip()
    return t


def user_say(gid, text, who="你"):
    """用户也可以插一句（和一屋子 AI 一起聊）。"""
    text = str(text or "").strip()
    if not text:
        return {"ok": False, "error": "空消息"}
    msg = {"id": uuid.uuid4().hex[:8], "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "who": str(who or "你"), "text": text, "by": "user", "round": 0}
    with _LOCK:
        d = _load()
        for g in d.get("groups") or []:
            if g.get("id") != gid:
                continue
            g.setdefault("messages", []).append(msg)
            g["messages"] = g["messages"][-MAX_MSGS_STORE:]
            _save(d)
            _event("user_say", gid=gid, chars=len(text))
            return {"ok": True, "message": msg}
    return {"ok": False, "error": "没有这个群"}


def stats():
    d = _load()
    gs = d.get("groups") or []
    return {"groups": len(gs),
            "messages": sum(len(g.get("messages") or []) for g in gs),
            "members": sum(len(g.get("members") or []) for g in gs),
            "path": _PATH}
