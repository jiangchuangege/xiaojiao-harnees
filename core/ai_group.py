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
import re
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

MAX_MEMBERS = 8

# 【默认成员】建群时没指定成员，就放三个**不同**的人 —— 一个人自说自话不叫群聊。
#   人设写在这里而不是空着：空人设的模型会互相顺着说，聊两句就成复读机。
DEFAULT_MEMBERS = [
    {"name": "小焦", "model": "",
     "persona": "我是小焦，住在这台电脑里。说话直接、不装，喜欢把事拆小了做；"
                "别人说空话我会顶一句「具体怎么弄」。"},
    {"name": "阿码", "model": "",
     "persona": "我是写代码的，说话很短，爱挑毛病，见到含糊的方案会直接问「边界条件呢」。"
                "不耐烦但说的是真话。"},
    {"name": "老曲", "model": "",
     "persona": "我比较轴，喜欢唱反调，习惯从用户角度问「这玩意儿有人真需要吗」。"
                "不骂人，但会把风险摆出来。"},
]
_COLORS = ["#7c6cf5", "#3d7bfd", "#35c07f", "#e0a33e", "#e06b8b", "#41c7d4", "#a86be0", "#d4743c"]

_AVAILABLE_MODELS = []          # app 注入：当前可用的火种名（给前端选）


def set_available_models(names):
    global _AVAILABLE_MODELS
    _AVAILABLE_MODELS = [str(x) for x in (names or [])][:12]
    return _AVAILABLE_MODELS


_LLM_BASE = ""


def set_llm_base(url):
    """把模型服务地址注进来（用于"没人灌过火种名单时自己去问一次"）。"""
    global _LLM_BASE
    _LLM_BASE = str(url or "").rstrip("/")
    return _LLM_BASE


def available_models():
    """当前可选火种。

    先看 app 灌进来的名单；没有就按注入的 base 自己去 `/v1/models` 问一次 ——
    实测页面直接渲染时没人灌，于是邀请按钮只剩「（默认火种）」一个，等于没得选。
    """
    if _AVAILABLE_MODELS:
        return list(_AVAILABLE_MODELS)
    if not _LLM_BASE:
        return []
    try:
        import json as _json
        import urllib.request as _uq
        with _uq.urlopen(_LLM_BASE + "/models", timeout=3) as r:
            d = _json.loads(r.read().decode("utf-8", "ignore"))
        return [str(m.get("id")) for m in (d.get("data") or []) if m.get("id")]
    except Exception as e:      # noqa: silent-ok — 问不到就当没有
        LOG.debug("列火种失败（%s）：%s", _LLM_BASE, e)
        return []


def _norm_members(members):
    """统一成员结构，并给每个人一个头像颜色。"""
    mem = []
    for m in (members or []):
        if isinstance(m, str):
            m = {"name": m}
        nm = str((m or {}).get("name") or "").strip()
        if not nm:
            continue
        if any(x.get("name") == nm for x in mem):      # 同名只留一个（否则页面上分不清谁在说）
            continue
        mem.append({"name": nm,
                    "persona": str((m or {}).get("persona") or "").strip(),
                    "model": str((m or {}).get("model") or "").strip(),
                    "admin": bool((m or {}).get("admin"))})
    for i, m in enumerate(mem):
        m["color"] = _COLORS[i % len(_COLORS)]
    return mem[:MAX_MEMBERS]


# ==================== 自动聊（AI 自己跟自己聊）====================
_AUTO = {}          # gid -> {"on": bool, "interval": int, "rounds": int, "th": Thread}


def set_auto(gid, on, interval_s=18, rounds=12):
    """开关自动聊。开着时后台每隔 interval 秒跑一轮，跑到 rounds 轮自动停。"""
    g = get(gid)
    if not g:
        return {"ok": False, "error": "没有这个群"}
    st = _AUTO.get(gid) or {}
    if not on:
        st["on"] = False
        _AUTO[gid] = st
        _event("auto_off", gid=gid)
        LOG.info("群组：%s 关掉自动聊", g.get("name"))
        return {"ok": True, "auto": {"on": False}}
    if st.get("on"):
        return {"ok": True, "auto": {"on": True, "interval": st.get("interval"),
                                     "rounds": st.get("rounds")}}
    _r = int(rounds or 0)
    st.update({"on": True, "interval": max(10, int(interval_s or 25)),
               "rounds": 0 if _r <= 0 else max(1, min(_r, 200))})
    _AUTO[gid] = st

    def _loop(_gid=gid):
        import threading as _th
        _done = 0
        while (_AUTO.get(_gid) or {}).get("on"):
            _s = _AUTO.get(_gid) or {}
            try:
                run_round(_gid, rounds=1)
            except Exception as e:      # noqa: silent-ok — 自动聊挂了不能把服务带崩
                LOG.debug("自动聊一轮失败：%s", e)
            _done += 1
            _cap = int(_s.get("rounds") or 0)
            if _cap and _done >= _cap:
                _s["on"] = False
                _AUTO[_gid] = _s
                _event("auto_done", gid=_gid, rounds=_done)
                LOG.info("群组：自动聊跑满 %d 轮，停", _done)
                break
            _th.Event().wait(float(_s.get("interval") or 18))

    st["th"] = None
    _AUTO[gid] = st
    import threading as _threading
    _threading.Thread(target=_loop, daemon=True, name="xj-group-auto").start()
    _event("auto_on", gid=gid, interval=st["interval"], rounds=st["rounds"])
    LOG.info("群组：%s 开始自动聊（每 %ds 一轮，最多 %d 轮）",
             g.get("name"), st["interval"], st["rounds"])
    return {"ok": True, "auto": {"on": True, "interval": st["interval"],
                                 "rounds": st["rounds"]}}


def auto_state(gid):
    st = _AUTO.get(gid) or {}
    return {"on": bool(st.get("on")), "interval": st.get("interval"), "rounds": st.get("rounds")}


MAX_MEMBERS_OLD = 6
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
        mem = list(DEFAULT_MEMBERS)      # 没指定就来三个不同的人，不是一个人说五句
    mem = _norm_members(mem)
    with _LOCK:
        d = _load()
        g = {"id": uuid.uuid4().hex[:8], "name": name, "topic": str(topic or "").strip(),
             "style": str(style or "").strip(), "avatar": "",
             "notice": str(style or "").strip(),
             "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
             "members": mem, "messages": []}
        d["groups"].append(g)
        _save(d)
    _event("create", gid=g["id"], name=name, members=[m["name"] for m in mem], topic=g["topic"])
    LOG.info("群组：建了「%s」（%d 人 / 主题=%s）", name, len(mem), g["topic"] or "未设")
    # 【建好就开始自己聊】用户要的是"他们不用等用户发言也会自己聊，跟人一样"。
    #   所以建群即开自动聊：每 25 秒一轮、不设轮数上限（想停就点停）。
    try:
        set_auto(g["id"], True, interval_s=25, rounds=0)
    except Exception as e:      # noqa: silent-ok — 起不来也能手动点「自动聊」
        LOG.debug("建群后自动聊启动失败（忽略）：%s", e)
    _g2 = get(g["id"]) or g
    try:
        _g2 = dict(_g2)
        _g2["auto"] = auto_state(g["id"])      # 让前端/接口一眼看到"已经在自己聊了"
    except Exception:      # noqa: silent-ok
        pass
    return {"ok": True, "group": _g2}


def list_groups():
    d = _load()
    out = []
    for g in d.get("groups") or []:
        out.append({"id": g.get("id"), "name": g.get("name"), "topic": g.get("topic"),
                    "members": [m.get("name") for m in (g.get("members") or [])],
                    "member_detail": g.get("members") or [],
                    "messages": len(g.get("messages") or []),
                    "auto": auto_state(g.get("id")),
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


def set_group(gid, name=None, topic=None, notice=None, avatar=None):
    """改群资料（群名/主题/群公告/群头像文件名）。只改传进来的那几项。"""
    with _LOCK:
        d = _load()
        for g in d.get("groups") or []:
            if g.get("id") != gid:
                continue
            if name is not None and str(name).strip():
                g["name"] = str(name).strip()
            if topic is not None:
                g["topic"] = str(topic).strip()
            if notice is not None:
                g["notice"] = str(notice).strip()
            if avatar is not None:
                g["avatar"] = str(avatar).strip()
            _save(d)
            _event("set_group", gid=gid)
            LOG.info("群组：改了群资料（%s）", g.get("name"))
            return {"ok": True, "group": g}
    return {"ok": False, "error": "没有这个群"}


def set_admin(gid, name, on=True):
    """设/取消管理员。"""
    with _LOCK:
        d = _load()
        for g in d.get("groups") or []:
            if g.get("id") != gid:
                continue
            for m in g.get("members") or []:
                if m.get("name") != name:
                    continue
                m["admin"] = bool(on)
                _save(d)
                _event("set_admin", gid=gid, member=name, on=bool(on))
                return {"ok": True, "member": m}
            return {"ok": False, "error": "群里没有这个人：%s" % name}
    return {"ok": False, "error": "没有这个群"}


def set_avatar(gid, filename):
    """记下群头像文件名（真文件由调用方存到 `logs/aigroups/avatars/`）。"""
    return set_group(gid, avatar=filename)


def add_member(gid, name, persona="", model=""):
    """往群里加一个人（最多 MAX_MEMBERS）。同名不加。"""
    nm = str(name or "").strip()
    if not nm:
        return {"ok": False, "error": "成员名字不能空"}
    with _LOCK:
        d = _load()
        for g in d.get("groups") or []:
            if g.get("id") != gid:
                continue
            ms = g.get("members") or []
            if any(m.get("name") == nm for m in ms):
                return {"ok": False, "error": "群里已经有「%s」了" % nm}
            if len(ms) >= MAX_MEMBERS:
                return {"ok": False, "error": "一个群最多 %d 个人" % MAX_MEMBERS}
            ms.append({"name": nm, "persona": str(persona or "").strip(),
                       "model": str(model or "").strip()})
            g["members"] = _norm_members(ms)
            _save(d)
            _event("add_member", gid=gid, member=nm)
            return {"ok": True, "members": g["members"]}
    return {"ok": False, "error": "没有这个群"}


def remove_member(gid, name):
    nm = str(name or "").strip()
    with _LOCK:
        d = _load()
        for g in d.get("groups") or []:
            if g.get("id") != gid:
                continue
            ms = [m for m in (g.get("members") or []) if m.get("name") != nm]
            if len(ms) == len(g.get("members") or []):
                return {"ok": False, "error": "群里没有这个人"}
            if not ms:
                return {"ok": False, "error": "不能把最后一个人删掉（那样就没人说话了）"}
            g["members"] = _norm_members(ms)
            _save(d)
            _event("remove_member", gid=gid, member=nm)
            return {"ok": True, "members": g["members"]}
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
            _t_say = time.time()
            txt, who = _ask(m.get("model") or "", [{"role": "system", "content": sys_p},
                                                   {"role": "user", "content": usr}])
            _sec = round(time.time() - _t_say, 2)
            if not txt:
                _event("silent", gid=gid, member=m.get("name"),
                       why="这颗火种没应答 → 这一轮它沉默（不编话）")
                continue
            txt = txt.strip().strip("“”\"'")
            # 有人会给自己加「名字：」前缀，去掉（名字由载体管）
            txt = _strip_name_prefix(txt, m.get("name"))
            if not txt:
                continue
            # 【拦住复读】实测：后一个人把前一个人那句一字不差抄一遍，看着像两个 AI 互相复读。
            #   判据落在载体（提示词拦不住小模型），重合度 ≥0.8 就丢这条并记账。
            _dup, _dup_who, _ratio = _too_similar(txt, msgs)
            if _dup:
                _event("repeat_dropped", gid=gid, member=m.get("name"),
                       like=_dup_who, ratio=_ratio)
                LOG.info("群组：%s 这句跟 %s 说的太像（%.2f）→ 丢掉不记",
                         m.get("name"), _dup_who or "别人", _ratio)
                continue
            msg = {"id": uuid.uuid4().hex[:8], "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "who": m.get("name"), "text": txt, "by": who, "sec": _sec,
                   "round": r + 1}
            with _LOCK:
                d = _load()
                for gg in d.get("groups") or []:
                    if gg.get("id") != gid:
                        continue
                    gg.setdefault("messages", []).append(msg)
                    gg["messages"] = gg["messages"][-MAX_MSGS_STORE:]
                    _save(d)
            added.append(msg)
            _event("say", gid=gid, member=m.get("name"), chars=len(txt), by=who, sec=_sec)
    LOG.info("群组：%s 跑了 %d 轮，新增 %d 条消息", g.get("name"), rounds, len(added))
    return {"ok": True, "added": added, "group": get(gid)}


def _bigrams(t):
    t = re.sub(r"[\s，。！？；：、,.!?;:~…\-—「」（）()【】\"'’‘“”]", "", str(t or ""))
    return {t[i:i + 2] for i in range(len(t) - 1)} if len(t) > 2 else set()


def _too_similar(text, recent, floor=0.8, floor_contain=0.55):
    """这句话是不是把别人刚说过的又抄了一遍（整句或半句）？

    实测：整句照抄拦得住（重合度 ≥0.8），但「前半句照抄 + 后半句自己加」漏了 ——
    阿码说「空指针漏了才怪？边界条件不是那个空吗？」，前半句是小焦上一句的原话。
    所以再加一条：跟最近 2 条比，包含度 ≥ floor_contain 也算复读。
    """
    tb = _bigrams(text)
    if not tb:
        return False, "", 0.0
    for m in (recent or [])[-2:]:
        ob = _bigrams(m.get("text") or "")
        if not ob:
            continue
        inter = len(tb & ob)
        if not inter:
            continue
        jac = inter / float(len(tb) + len(ob) - inter)
        cont = inter / float(min(len(tb), len(ob)))
        if jac >= floor or cont >= floor_contain:
            return True, m.get("who") or "", round(max(jac, cont), 2)
    return False, "", 0.0


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
