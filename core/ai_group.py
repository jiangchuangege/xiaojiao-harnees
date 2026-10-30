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
import random
import re
import threading
import time
import uuid

LOG = logging.getLogger(__name__)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DIR = os.path.join(_ROOT, "logs", "aigroups")
_PATH = os.path.join(_DIR, "groups.json")
_EVENTS = os.path.join(_DIR, "events.jsonl")
_FILES = os.path.join(_DIR, "files")          # 群文件落盘：files/<gid>/<文件名>
_LOCK = threading.RLock()
_ROUND_LOCK = threading.Lock()     # 同一时刻只允许一个群在跑一轮（模型是共享资源）

_LLM = None
_ALT = None
_MODEL = ""

MAX_MEMBERS = 8
ACT_PROB = 0.45        # 默认几率（群没设节奏时用）
ACT_MIN_GAP = 1        # 同一个成员最少隔几条消息才再动手（避免一直闷头干活不说话）

# 【按群的节奏】用户原话：「可以改成按群的节奏（比如"这个群是开发群，就多动手少聊天"）」
PACES = {
    "chat": {"label": "聊天群", "act_prob": 0.10, "interval": 22,
             "hint": "这是一个聊天群，主要就是聊，别动不动就动工具。"},
    "mixed": {"label": "混合", "act_prob": 0.45, "interval": 25,
              "hint": "该聊就聊，该动手就动手。"},
    "dev": {"label": "开发群", "act_prob": 0.75, "interval": 20,
            "hint": "这是一个开发群：多动手、少空谈。能查就查、能写就写、能跑就跑。"},
}


def pace_of(g):
    """这个群的节奏（没设就是 mixed）。"""
    k = str((g or {}).get("pace") or "mixed")
    return k if k in PACES else "mixed"


def set_pace(gid, pace):
    """改群节奏：chat / mixed / dev。改了之后自动聊的间隔也跟着变。"""
    k = str(pace or "").strip()
    if k not in PACES:
        return {"ok": False, "error": "节奏只能是 chat / mixed / dev"}
    with _LOCK:
        d = _load()
        for g in d.get("groups") or []:
            if g.get("id") != gid:
                continue
            g["pace"] = k
            _save(d)
            _event("set_pace", gid=gid, pace=k)
            LOG.info("群组：%s 的节奏改成 %s（动手几率 %.2f）",
                     g.get("name"), PACES[k]["label"], PACES[k]["act_prob"])
            break
    try:
        st = _AUTO.get(gid) or {}
        if st.get("on"):
            set_auto(gid, False)
            set_auto(gid, True, interval_s=PACES[k]["interval"], rounds=0)
    except Exception as e:      # noqa: silent-ok
        LOG.debug("群组·切节奏后重启自动聊失败：%s", e)
    return {"ok": True, "pace": k, "label": PACES[k]["label"]}

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

# 【人设跟着群主题走】实测：交友群里一堆"边界条件呢""语法错了吧"——
#   因为成员人设是空的，回落到全局小焦人设（技术味很重）。这里按主题分四类。
TOPIC_KINDS = {
    "social": ("交友", "恋爱", "对象", "情感", "相亲", "聊天搭子", "脱单", "撩",
               "认识", "朋友", "生活", "闲聊", "聚会", "约会", "家常", "心情", "八卦"),
    "dev": ("开发", "代码", "编程", "架构", "技术", "bug", "重构", "上线", "微服务", "算法"),
    "study": ("学习", "考试", "读书", "考研", "英语", "复习", "论文"),
    "game": ("游戏", "开黑", "副本", "上分", "联机", "攻略", "炉石", "原神"),
}
KIND_PERSONAS = {
    "social": [
        "我是个爱聊的人，关注对方的感受，会接话、会追问，聊天像朋友之间那样自然。",
        "我有点幽默，喜欢自嘲，也爱分享生活里的小事；遇到冷场会主动换话题。",
        "我比较真诚，愿意聊聊自己对关系的看法，也会坦白自己的小毛病。",
    ],
    "dev": [
        "我是写代码的，说话短，见到含糊的方案会直接问边界条件。",
        "我管过线上服务，习惯先问数据、再问方案，不爱空谈。",
        "我偏保守，会先算风险再动手；对「先能跑」这件事很执着。",
    ],
    "study": [
        "我在准备考试，说话有条理，喜欢把知识拆成能背的小块。",
        "我记性一般，喜欢用例子记东西，也爱问「这个到底怎么用」。",
    ],
    "game": [
        "我是老玩家，爱讲配合和心态，输了也不骂人。",
        "我玩得菜但很上头，喜欢分享翻盘的那一局。",
    ],
    "other": [
        "我就是个普通人，说话随和，喜欢接别人的话往下聊。",
        "我比较好奇，遇到不懂的会直接问；也会讲讲自己的看法。",
    ],
}


def topic_kind(topic=""):
    """这句话/这个群的主题属于哪一类（认不出来就 other）。"""
    t = str(topic or "")
    for k, words in TOPIC_KINDS.items():
        if any(w.lower() in t.lower() for w in words):
            return k
    return "other"


def kind_persona(kind, i=0):
    lst = KIND_PERSONAS.get(kind) or KIND_PERSONAS["other"]
    return lst[int(i or 0) % len(lst)]

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
                    "admin": bool((m or {}).get("admin")),
                    # 【自由但要能收回】allow_tools=它能不能在这个群里动手（调插件/写文件/写代码）。
                    #   默认开；随时可以用 set_member_perm 关掉。
                    "allow_tools": bool((m or {}).get("allow_tools", True)),
                    "skills": list((m or {}).get("skills") or [])})
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
    st.update({"on": True, "interval": max(30, int(interval_s or 30)),
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


def resume_all(interval_s=None):
    """把**所有**群的自动聊恢复成开（服务启动时调一次）。

    为什么需要：UI 上的「停」按钮已经去掉了（用户要"像人一样一直聊"），
    但进程里可能还留着早前被停掉的状态 —— 那会让所有群静默，看起来像"它们不说话"。
    """
    n = 0
    for g in (list_groups() or []):
        gid = g.get("id")
        try:
            if not (auto_state(gid) or {}).get("on"):
                _iv = interval_s or (PACES.get(g.get("pace") or "mixed") or {}).get("interval") or 25
                set_auto(gid, True, interval_s=_iv, rounds=0)
                n += 1
        except Exception as e:      # noqa: silent-ok
            LOG.debug("群组·恢复自动聊失败（%s）：%s", gid, e)
    if n:
        LOG.info("群组：启动时恢复了 %d 个群的自动聊", n)
    return n


def auto_state(gid):
    st = _AUTO.get(gid) or {}
    return {"on": bool(st.get("on")), "interval": st.get("interval"), "rounds": st.get("rounds")}


MAX_MEMBERS_OLD = 6
MAX_MSGS_STORE = 400        # 每个群只留最近这么多条
CTX_MSGS = 14               # 拼给模型的最近消息条数


_ACT = None          # 带工具的调用：act(member_dict, messages) -> (text, by, actions)
_DISTILL = None      # 蒸馏：distill(messages) -> "经验1；经验2"（app 注入）
_EXEC_PROP = None    # 执行提议：exec(member_dict, 提议文本) -> (正文, 谁, actions)（app 注入）


def install(llm_fn=None, alt_fn=None, model_name="", act_fn=None, distill_fn=None):
    global _LLM, _ALT, _MODEL, _ACT, _DISTILL
    if llm_fn is not None:
        _LLM = llm_fn
    if alt_fn is not None:
        _ALT = alt_fn
    if model_name:
        _MODEL = str(model_name)
    if act_fn is not None:
        _ACT = act_fn
    if distill_fn is not None:
        _DISTILL = distill_fn


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
def create(name, topic="", members=None, style="", pace="mixed"):
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
    _kind0 = topic_kind(topic or name)
    if not mem:
        if _kind0 == "dev":
            mem = list(DEFAULT_MEMBERS)   # 技术群才用技术味的默认三人
        else:
            # 其他主题：名字照旧，人设换成**这一类的**，别让交友群也满嘴边界条件
            mem = [{"name": d["name"], "persona": kind_persona(_kind0, i), "model": d.get("model") or ""}
                   for i, d in enumerate(DEFAULT_MEMBERS)]
    mem = _norm_members(mem)
    # 【人设跟着主题走】空人设的成员按群主题领一个分类人设（交友群就别再让它聊边界条件了）
    _kind = topic_kind(topic or name)
    for _i, _m in enumerate(mem):
        if not str(_m.get("persona") or "").strip():
            _m["persona"] = kind_persona(_kind, _i)
    if _kind == "social" and str(pace or "mixed") == "mixed":
        pace = "chat"                    # 交友/闲聊类默认少动手
        LOG.info("群组：按主题判定为 %s → 默认人设已分配，节奏改为 chat", _kind)
    with _LOCK:
        d = _load()
        g = {"id": uuid.uuid4().hex[:8], "name": name, "topic": str(topic or "").strip(),
             "style": str(style or "").strip(), "avatar": "",
             "notice": str(style or "").strip(),
             "pace": (pace if pace in PACES else "mixed"),
             "distilled": [], "proposals": [],
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
                    "pace": pace_of(g),
                    "pace_label": (PACES.get(pace_of(g)) or {}).get("label"),
                    "distilled": len(g.get("distilled") or []),
                    "proposals": len(g.get("proposals") or []),
                    "files": len(g.get("files") or []),
                    "unread": unread_count(g),
                    "last": (str(((g.get("messages") or [{}])[-1] or {}).get("text") or ""))[:60],
                    "last_who": str(((g.get("messages") or [{}])[-1] or {}).get("who") or ""),
                    "last_ts": str(((g.get("messages") or [{}])[-1] or {}).get("ts") or ""),
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


def _files_dir(gid):
    d = os.path.join(_FILES, re.sub(r"[^0-9A-Za-z_\-]", "_", str(gid or "x")))
    os.makedirs(d, exist_ok=True)
    return d


def upload_file(gid, name, blob, by="你", note=""):
    """上传一个群文件（真落盘）。返回文件记录。"""
    nm = os.path.basename(str(name or "").strip()) or ("文件_%d" % int(time.time()))
    nm = re.sub(r'[\\/:*?"<>|]', "_", nm)[:120]
    try:
        d = _files_dir(gid)
        fp = os.path.join(d, nm)
        with open(fp, "wb") as f:
            f.write(blob or b"")
        return register_file(gid, nm, os.path.getsize(fp), by=by, note=note, path=fp)
    except Exception as e:      # noqa: silent-ok
        LOG.debug("群文件写入失败：%s", e)
        return None


def register_file(gid, name, size=0, by="你", note="", path=""):
    """登记一条群文件（AI 自己写出来的文件也走这里 —— 真人有文件也会丢进群）。"""
    with _LOCK:
        d = _load()
        for g in d.get("groups") or []:
            if g.get("id") != gid:
                continue
            fs = list(g.get("files") or [])
            fid = uuid.uuid4().hex[:8]
            fs.append({"id": fid, "name": str(name)[:160], "size": int(size or 0),
                       "by": str(by or "你"), "note": str(note or "")[:120],
                       "path": str(path or ""),
                       "ts": time.strftime("%Y-%m-%dT%H:%M:%S")})
            g["files"] = fs[-60:]
            _save(d)
            _event("file", gid=gid, name=str(name)[:80], size=int(size or 0), by=by,
                   path=str(path or "")[:160])
            LOG.info("群文件：%s 往「%s」放了 %s（%d 字节）", by, g.get("name"), name, int(size or 0))
            return {"ok": True, "file": fs[-1]}
    return {"ok": False, "error": "没有这个群"}


def file_path(gid, fid):
    """取群文件的真实路径（下载用）。只认登记过的，防路径穿越。"""
    for g in _load().get("groups") or []:
        if g.get("id") != gid:
            continue
        for f in g.get("files") or []:
            if f.get("id") != fid:
                continue
            p = str(f.get("path") or "")
            if p and os.path.isfile(p):
                return p, f
            cand = os.path.join(_files_dir(gid), os.path.basename(str(f.get("name") or "")))
            if os.path.isfile(cand):
                return cand, f
    return "", None


def mark_read(gid):
    """把"我读到哪儿了"推到最新（左侧红点靠这个消）。"""
    with _LOCK:
        d = _load()
        for g in d.get("groups") or []:
            if g.get("id") != gid:
                continue
            msgs = g.get("messages") or []
            g["last_read"] = str(msgs[-1].get("ts") or "") if msgs else ""
            g["last_read_n"] = len(msgs)
            _save(d)
            return {"ok": True, "n": len(msgs)}
    return {"ok": False, "error": "没有这个群"}


def unread_count(g):
    """还没读的消息条数（自己说的话不算）。"""
    try:
        n0 = int((g or {}).get("last_read_n") or 0)
        msgs = (g or {}).get("messages") or []
        return max(0, sum(1 for m in msgs[n0:] if m.get("who") != "你"))
    except Exception:      # noqa: silent-ok
        return 0


def set_member_perm(gid, name, allow_tools):
    """开关某个成员"能不能动手"（调插件 / 写文件 / 写代码 / 造插件）。"""
    with _LOCK:
        d = _load()
        for g in d.get("groups") or []:
            if g.get("id") != gid:
                continue
            for m in g.get("members") or []:
                if m.get("name") != name:
                    continue
                m["allow_tools"] = bool(allow_tools)
                _save(d)
                _event("set_perm", gid=gid, member=name, allow_tools=bool(allow_tools))
                return {"ok": True, "member": m}
            return {"ok": False, "error": "群里没有这个人：%s" % name}
    return {"ok": False, "error": "没有这个群"}


def _register_written(gid, who, actions):
    """把「它自己写出来的文件」登记成群文件 —— 真人有文件也会丢进群，它也一样。"""
    _n = 0
    for a in (actions or []):
        if str(a.get("tool")) not in ("write_file", "edit_file"):
            continue
        try:
            p = str((a.get("args") or {}).get("path") or "")
            if p and os.path.isfile(p):
                r = register_file(gid, os.path.basename(p), size=os.path.getsize(p),
                                  by=str(who or "AI"), note="我写的，大家看看", path=p)
                if (r or {}).get("ok"):
                    _n += 1
        except Exception as e:      # noqa: silent-ok
            LOG.debug("群组·登记 AI 文件失败：%s", e)
    return _n


def _note_skill(gid, name, note):
    """把"这次动手做了什么"记进成员身上（越用越强就靠这个接续）。"""
    with _LOCK:
        d = _load()
        for g in d.get("groups") or []:
            if g.get("id") != gid:
                continue
            for m in g.get("members") or []:
                if m.get("name") != name:
                    continue
                sk = list(m.get("skills") or [])
                sk.append({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "note": str(note)[:200]})
                m["skills"] = sk[-20:]        # 只留最近 20 条，别把 prompt 撑爆
                _save(d)
                return True
    return False


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


def _persona_of(m, g=None):
    if m.get("persona"):
        return m["persona"]
    # 没写人设：**按群主题**给一份，而不是回落到全局（技术味的）小焦人设
    try:
        _k = topic_kind((g or {}).get("topic") or (g or {}).get("name") or "")
        _names = [x.get("name") for x in ((g or {}).get("members") or [])]
        _i = _names.index(m.get("name")) if m.get("name") in _names else 0
        return kind_persona(_k, _i)
    except Exception:      # noqa: silent-ok
        return kind_persona("other", 0)


def _transcript(msgs, who_filter=None):
    out = []
    for m in msgs:
        if who_filter and m.get("who") not in who_filter:
            continue
        out.append("%s：%s" % (m.get("who"), str(m.get("text") or "")[:300]))
    return "\n".join(out)


def run_round(gid, rounds=1, speakers=None, allow_act=True):
    """跑若干轮：每轮按成员顺序各说一句。返回这一步新增的消息。"""
    g = get(gid)
    if not g:
        return {"ok": False, "error": "没有这个群"}
    # 排队：别的群正在说就等一会儿（否则多个群一起抢模型，谁都慢到超时）
    _got = _ROUND_LOCK.acquire(timeout=180)
    if not _got:
        return {"ok": False, "error": "别的群正在发言，等太久先放弃这一轮（稍后自动会再聊）"}
    try:
        return _run_round_locked(gid, rounds, speakers, allow_act)
    finally:
        try:
            _ROUND_LOCK.release()
        except Exception:      # noqa: silent-ok
            pass


def _run_round_locked(gid, rounds=1, speakers=None, allow_act=True):
    g = get(gid)
    if not g:
        return {"ok": False, "error": "没有这个群"}
    members = g.get("members") or []
    if not members:
        return {"ok": False, "error": "这个群还没有成员"}
    rounds = max(1, min(int(rounds or 1), 5))
    added = []
    # 【一轮别让 8 个人全说】不然一轮要几分钟，页面看着就像"卡住不说话"。
    #   每轮挑最多 4 个，起点轮转（持久化 `rr`），几轮下来大家都有机会。
    _cap = min(len(members), int(speakers or 4))
    _rr = int(g.get("rr") or 0)
    _order = [members[(i + _rr) % len(members)] for i in range(len(members))][:_cap]
    try:
        with _LOCK:
            _d0 = _load()
            for _g0 in _d0.get("groups") or []:
                if _g0.get("id") == gid:
                    _g0["rr"] = (_rr + _cap) % max(1, len(members))
                    _save(_d0)
    except Exception as _e:      # noqa: silent-ok
        LOG.debug("群组·轮转指针保存失败：%s", _e)
    for r in range(rounds):
        for m in _order:
            msgs = (get(gid) or {}).get("messages") or []
            recent = msgs[-CTX_MSGS:]
            sys_p = ("这是一个%s人组成的群聊，你的名字是%s。像真人微信群里聊天那样说话："
                     "短句、口语、可以接别人的话、可以只回半句、可以问别人；"
                     "不要复读别人说过的内容，不要总结整段对话，不要写旁白和表情符号说明。"
                     "一次只说一到两句，40 字以内。只输出你要说的话本身。"
                     % (len(members), m.get("name")))
            per = _persona_of(m, g)
            if per:
                sys_p += "\n你的人物设定：" + str(per)[:400]
            # 【越用越强】把自己最近做过的事带上 —— 接着上次往前走，而不是每轮从零开始。
            _sk = [x.get("note") for x in (m.get("skills") or [])[-3:] if x.get("note")]
            if _sk:
                sys_p += "\n你最近在这个群里做过的事：" + "；".join(str(x)[:80] for x in _sk)
            # 【能动手就写进提示词】只有允许动手的成员才提工具，免得它想动又动不了。
            _can_act = bool(m.get("allow_tools", True)) and (_ACT is not None) and bool(allow_act)
            if _can_act:
                sys_p += ("\n你有工具可以用：查资料、读写文件、跑命令、画图，必要时用 forge_plugin 造新插件。"
                          "该动手就动手，别只在嘴上说；做完用一两句话说清你做了什么、结果如何。")
            if g.get("style"):
                sys_p += "\n群规矩：" + str(g.get("style"))[:300]
            _pc = PACES.get(pace_of(g)) or PACES["mixed"]
            sys_p += "\n本群节奏：" + str(_pc.get("hint") or "")[:160]
            # 【互相蒸馏】把本群已经聊出来的共识带上 —— 越聊越聪明靠这一条
            _fl = ["%s（%s 上传）" % (f.get("name"), f.get("by"))
                   for f in (g.get("files") or [])[-5:] if f.get("name")]
            if _fl:
                sys_p += "\n本群文件：" + "、".join(_fl) + \
                    "\n（可以就这些文件讨论；需要读内容就用 read_file。）"
            _kind_now = topic_kind(g.get("topic") or g.get("name") or "")
            _ds = []
            for _x in (g.get("distilled") or [])[-6:]:
                _note = str(_x.get("note") or "").strip()
                if not _note:
                    continue
                # 旧话题的共识别拿来污染新话题：技术词只在 dev/study 群里带
                _tech = any(w in _note for w in ("代码", "接口", "部署", "服务", "数据库", "语法",
                                                 "框架", "性能", "并发", "锁", "测试"))
                if _tech and _kind_now not in ("dev", "study"):
                    continue
                _ds.append(_note)
            if _ds:
                sys_p += "\n本群已有的共识（别重复讨论，直接用）：\n" + "\n".join(
                    "· " + str(x)[:120] for x in _ds)
            if _can_act:
                sys_p += ("\n如果你认为该做一件具体的事（写文件/跑命令/查资料/造插件），"
                          "就在回答末尾单独写一行：〔提议：工具名 + 一句话说明〕，"
                          "载体会把提议记下来并执行。不要删除或移动任何文件。")
            usr = "群主题：%s\n\n最近的聊天记录：\n%s\n\n现在轮到你（%s）说话：" % (
                g.get("topic") or "（没设主题，随意聊）",
                _transcript(recent) or "（还没有人说话，你起个头）",
                m.get("name"))
            if not allow_act:
                # 回应"用户插话"的快速轮：直接回答用户，不折腾工具
                usr += "\n（刚才是用户在说话，直接回答用户的问题，一到两句，别东拉西扯。）"
            _t_say = time.time()
            _actions = []
            _msgs_for_model = [{"role": "system", "content": sys_p},
                               {"role": "user", "content": usr}]
            txt, who = "", ""
            # 载体掷骰：这一轮是"动手"还是"只说一句"（动手慢，不能每轮都动）
            _act_roll = random.random()
            _act_prob = float((PACES.get(pace_of(g)) or PACES["mixed"]).get("act_prob") or ACT_PROB)
            _do_act = bool(_can_act and _act_roll < _act_prob)
            if _do_act:
                try:
                    txt, who, _actions = _ACT(m, _msgs_for_model)
                except Exception as e:      # noqa: silent-ok — 动手失败就退回"只说一句"
                    LOG.debug("群组·动手失败（退回只说）：%s", e)
                    txt, who, _actions = "", "", []
                _event("act_try", gid=gid, member=m.get("name"), roll=round(_act_roll, 3),
                       prob=_act_prob, pace=pace_of(g), ok=bool(txt),
                       tools=[a.get("tool") for a in (_actions or [])][:6])
            if not txt:
                txt, who = _ask(m.get("model") or "", _msgs_for_model)
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
                # 【先给它一次机会】实测一整轮几句都被判重复 → 群里看起来"没人说话"。
                #   带着"换个角度、别重复"再问一遍；还重复才丢。
                _event("repeat_retry", gid=gid, member=m.get("name"),
                       like=_dup_who, ratio=_ratio)
                try:
                    _retry_msgs = list(_msgs_for_model) + [
                        {"role": "user",
                         "content": "你刚才那句跟 %s 说的太像了。换一个角度，说点**新的**，别重复。" % (
                             _dup_who or "别人")}]
                    txt2, who2 = _ask(m.get("model") or "", _retry_msgs)
                    if txt2:
                        txt = _strip_name_prefix(str(txt2).strip().strip("“”\"'"),
                                                 m.get("name"))
                        who = who2 or who
                        _dup2, _dw2, _r2 = _too_similar(txt, msgs)
                        if _dup2:
                            _event("repeat_dropped", gid=gid, member=m.get("name"),
                                   like=_dw2, ratio=_r2)
                            LOG.info("群组：%s 重说一遍还是像 %s（%.2f）→ 丢掉不记",
                                     m.get("name"), _dw2 or "别人", _r2)
                            continue
                except Exception as _e:      # noqa: silent-ok
                    LOG.debug("群组·重说一遍失败：%s", _e)
            msg = {"id": uuid.uuid4().hex[:8], "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "who": m.get("name"), "text": txt, "by": who, "sec": _sec,
                   "round": r + 1, "actions": (_actions or [])[:6]}
            with _LOCK:
                d = _load()
                for gg in d.get("groups") or []:
                    if gg.get("id") != gid:
                        continue
                    gg.setdefault("messages", []).append(msg)
                    gg["messages"] = gg["messages"][-MAX_MSGS_STORE:]
                    _save(d)
            added.append(msg)
            _event("say", gid=gid, member=m.get("name"), chars=len(txt), by=who, sec=_sec,
                   actions=[a.get("tool") for a in (_actions or [])][:6])
            # 【自己提议】它写了〔提议：工具+说明〕就记下来，载体之后真去执行
            try:
                for _pm in re.finditer(r"[〔\[【]\s*提议\s*[:：]\s*([^〕\]】\n]{4,120})[〕\]】]",
                                       txt):
                    _prop = _pm.group(1).strip()
                    with _LOCK:
                        _d2 = _load()
                        for _gg in _d2.get("groups") or []:
                            if _gg.get("id") != gid:
                                continue
                            _ps = list(_gg.get("proposals") or [])
                            _ps.append({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                        "who": m.get("name"), "text": _prop[:160],
                                        "done": False})
                            _gg["proposals"] = _ps[-20:]
                            _save(_d2)
                    _event("propose", gid=gid, member=m.get("name"), text=_prop[:120])
                    LOG.info("群组：%s 提议 → %s", m.get("name"), _prop[:80])
                    if _EXEC_PROP is not None:
                        try:
                            _rtxt, _rwho, _racts = _EXEC_PROP(
                                {"name": m.get("name"),
                                 "persona": _persona_of(m, g),
                                 "model": m.get("model") or ""}, _prop)
                            if _rtxt:
                                _rm = {"id": uuid.uuid4().hex[:8],
                                       "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                       "who": "载体", "text": "〔已执行 %s〕%s" % (
                                           "、".join(a.get("tool") for a in (_racts or [])[:3]) or "提议",
                                           str(_rtxt)[:300]),
                                       "by": _rwho or "", "sec": 0, "round": r + 1,
                                       "actions": (_racts or [])[:6]}
                                with _LOCK:
                                    _d3 = _load()
                                    for _g3 in _d3.get("groups") or []:
                                        if _g3.get("id") != gid:
                                            continue
                                        _g3.setdefault("messages", []).append(_rm)
                                        _g3["messages"] = _g3["messages"][-MAX_MSGS_STORE:]
                                        _save(_d3)
                                try:
                                    _register_written(gid, m.get("name") or "AI", _racts)
                                except Exception as _fe:      # noqa: silent-ok
                                    LOG.debug("群组·提议产物登记失败：%s", _fe)
                                added.append(_rm)
                                _event("propose_done", gid=gid, member=m.get("name"),
                                       tools=[a.get("tool") for a in (_racts or [])][:6])
                        except Exception as _pe:      # noqa: silent-ok
                            LOG.debug("群组·执行提议失败：%s", _pe)
            except Exception as _pme:      # noqa: silent-ok — 提议解析失败不能影响群聊
                LOG.debug("群组·解析提议失败：%s", _pme)

            # 【AI 自己传文件】写出来的东西自动登记成群文件（真人有文件也会丢进群）
            try:
                _register_written(gid, m.get("name") or "AI", _actions)
            except Exception as _fe:      # noqa: silent-ok
                LOG.debug("群组·登记 AI 文件失败：%s", _fe)

            # 动手了就记到这人身上（下一轮 prompt 会带"你最近做过什么"）
            for _a in (_actions or [])[:3]:
                try:
                    _line = str(_a.get("result") or "").strip().splitlines()
                    _line = (_line[0] if _line else "").strip()
                    _note_skill(gid, m.get("name"),
                                "用 %s 做了：%s" % (_a.get("tool"), _line[:40]))
                except Exception as _e:      # noqa: silent-ok
                    LOG.debug("群组·记 skills 失败：%s", _e)
    # 【互相蒸馏】一轮结束就把这一轮压成经验，存进本群共识（下一轮 prompt 会带上）
    try:
        if _DISTILL is not None and added:
            _new = [{"who": x.get("who"), "text": x.get("text")} for x in added]
            _note = str(_DISTILL(_new) or "").strip()
            if _note:
                with _LOCK:
                    _d4 = _load()
                    for _g4 in _d4.get("groups") or []:
                        if _g4.get("id") != gid:
                            continue
                        _dl = list(_g4.get("distilled") or [])
                        _dl.append({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                    "note": _note[:400]})
                        _g4["distilled"] = _dl[-12:]
                        _save(_d4)
                _event("distill", gid=gid, chars=len(_note), note=_note[:120])
                LOG.info("群组蒸馏：%s → %s", g.get("name"), _note[:80])
    except Exception as _de:      # noqa: silent-ok — 蒸馏失败不影响群聊
        LOG.debug("群组·蒸馏失败：%s", _de)
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


def user_say(gid, text, who="你", respond=True):
    """用户插一句；默认**立刻让群里有人回应**（真人群聊也是这样，你说话有人接）。"""
    text = str(text or "").strip()
    if not text:
        return {"ok": False, "error": "空消息"}
    msg = {"id": uuid.uuid4().hex[:8], "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "who": str(who or "你"), "text": text, "by": "user", "round": 0}
    _hit = None
    with _LOCK:
        d = _load()
        for g in d.get("groups") or []:
            if g.get("id") != gid:
                continue
            g.setdefault("messages", []).append(msg)
            g["messages"] = g["messages"][-MAX_MSGS_STORE:]
            _save(d)
            _event("user_say", gid=gid, chars=len(text))
            _hit = {"ok": True, "message": msg}
            break
    if _hit is None:
        return {"ok": False, "error": "没有这个群"}
    # 【你说话就有人接】后台起一轮回应，不挡你这条消息显示
    if respond:
        try:
            import threading as _th
            # 回应走快速通道：两个人、不动工具 —— 用户问一句不该等一分钟
            _th.Thread(target=run_round, kwargs={"gid": gid, "rounds": 1,
                                                 "speakers": 2, "allow_act": False},
                       daemon=True, name="xj-group-reply").start()
            _event("reply_trigger", gid=gid, why="用户说话了 → 起一轮回应")
        except Exception as e:      # noqa: silent-ok — 起不来也不影响消息落盘
            LOG.debug("群组·触发回应失败：%s", e)
    return _hit


def stats():
    d = _load()
    gs = d.get("groups") or []
    return {"groups": len(gs),
            "messages": sum(len(g.get("messages") or []) for g in gs),
            "members": sum(len(g.get("members") or []) for g in gs),
            "path": _PATH}
