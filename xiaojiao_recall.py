# -*- coding: utf-8 -*-
"""小焦 · 画像召回层（血管那条）——**只负责"召回补位"，一个字都不写盘**。

【分工（用户 2026-09-17 定的）】
  · **画像系统 `core/user_profile` = 唯一写入口**：负责"记什么"（落 logs/psyche/user_profile.jsonl）
  · **本模块 = 只召回**：10 路血管投票挑出该摆到它眼前的几条，命中的把 hit_count 记在 user_profile 上

原来本模块自己维护一份 `xiaojiao_profiles.json`（写入链 + 独立库），跟 user_profile 是两份数据，
早晚打架 —— 那一套（save_profiles / append_profile / is_duplicate / generate_profile /
remember_from_message / 本地 hit）已经**整段删掉**，`load_profiles()` 改成从 user_profile 读。
**10 路血管的逻辑一个字没改**，只改了数据来源和写入责任。
"""
import os, json, time, urllib.request

try:      # 与仓库其他模块同样的取日志方式（独立运行时退化为标准 logging）
    from xiaojiao_log import get_logger
    LOG = get_logger(__name__)
except Exception:      # noqa: silent-ok — 没有日志模块也得能跑
    import logging
    LOG = logging.getLogger(__name__)

STOP_TRIGGERS = {"看","吃","喝","玩","听","写","读","买","去","走","做","学","用","说","讲"}
_model, _base = None, None
def _local_target():
    global _model, _base
    if _model and _base: return _base, _model
    _model, _base = "xiaojiao", "http://127.0.0.1:9292/v1"
    try:
        from xiaojiao_app import _local_brain_model, _LOCAL_PROBE
        m = _local_brain_model()
        if m: _model = m
        b = _LOCAL_PROBE.get("base")
        if b: _base = b
    except Exception:
        pass
    return _base, _model
def local_chat(messages, temperature=0.0, max_tokens=64, timeout=300):
    base, model = _local_target()
    url = base.rstrip("/") + "/chat/completions"
    payload = {"model": model, "messages": messages,
               "temperature": float(temperature), "max_tokens": max_tokens}
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode("utf-8"))
    return d["choices"][0]["message"]["content"].strip()
def load_profiles():
    """画像来源**只有一个**：`core.user_profile`（logs/psyche/user_profile.jsonl）。

    【为什么不再读 xiaojiao_profiles.json】原来血管这条链自己维护一份独立的画像库，
    于是同一件事会存在两份数据（user_profile.jsonl 与 xiaojiao_profiles.json），
    早晚会打架（用户报的问题）。现在分工是死的：
      · **画像系统（core.user_profile）= 唯一写入口**，负责"记什么"
      · **血管（本模块）= 只负责召回补位**，一个字都不写盘
    这里只把 user_profile 的记录**映射**成血管内部用的格式。

    ⚠️ user_profile 的记录里**没有 triggers / scope** 两个字段（它们是血管这条链原来的字段），
    所以映射时给 scope 兜底成 kind（否则 v3 场景优先那一路会因为拿不到 scope 整路弃权）、
    triggers 缺省空表（等价于"这一路没命中"，不会误召）。**血管那 10 路的逻辑一个字没改。**
    """
    try:
        from core import user_profile as up
        out = []
        for r in up.all_records():
            if not isinstance(r, dict):
                continue
            out.append({
                "text": str(r.get("content") or ""),
                "type": str(r.get("kind") or ""),
                "id": str(r.get("id") or ""),
                "triggers": [t for t in (r.get("triggers") or []) if t],
                "scope": str(r.get("scope") or r.get("kind") or ""),
                "_raw": r,
            })
        return out
    except Exception as e:      # noqa: silent-ok — 画像库读不到就当空库，不能让对话挂掉
        LOG.debug("读 user_profile 失败（忽略）：%s", e)
        return []


# 【撤掉了模块级写锁 _WRITE_LOCK】：它只服务于 save_profiles/append_profile 那套写盘，
# 而那套（连同 generate_profile / remember_from_message）已经整段删除 ——
# 本模块现在**只读不改**，没有需要上锁的写入。（历史：这个锁的定义曾经被编辑弄丢，
# 导致写入链一跑就 NameError 而调用方把异常吞了，表现是"永远记不住新东西"。写入职责
# 交给 core.user_profile 之后，这类问题不会再出现在这条链上。）


def _parse_idx(out, n, multi=False):
    if not out: return [] if multi else None
    out = out.replace("，",",").replace("。"," ").replace("、",",").replace("-1"," ")
    idxs = []
    for t in out.split():
        t = t.strip(", ")
        if t.isdigit():
            i = int(t)
            if 0 <= i < n: idxs.append(i)
    return idxs if multi else (idxs[0] if idxs else None)
def _build_opts(order, profiles):
    return "\n".join(f"{i}. [{profiles[r]['type']}] {profiles[r]['text']}" for i,r in enumerate(order))
def _pick(q, tpl, order, profiles, temp=0.0, multi=False):
    n = len(profiles)
    opts = _build_opts(order, profiles)
    out = local_chat([{"role":"user","content":tpl.format(q=q, opts=opts)}], temperature=temp, max_tokens=64)
    disp = _parse_idx(out, n, multi=multi)
    if multi: return [order[d] for d in disp if d < len(order)]
    if disp is None or disp >= len(order): return None
    return order[disp]
def _v1_trigger(q, order, profiles):
    best, bs = None, 0
    for disp, real in enumerate(order):
        hits = sum(1 for t in profiles[real]["triggers"] if t in q and t not in STOP_TRIGGERS)
        if hits > bs: bs, best = hits, disp
    return order[best] if best is not None and bs >= 1 else None
def _v2_type_first(q, order, profiles):
    types = ["状态","偏好","约束","背景"]
    out = local_chat([{"role":"user","content":
        f"用户说：{q}\n\n这句话最需要哪类用户信息？只回答一个：状态/偏好/约束/背景"}], max_tokens=16)
    need = next((t for t in types if t in out), None)
    sub = [r for r in order if profiles[r]["type"]==need]
    if not sub: return None
    lines = "\n".join(f"{j}. {profiles[r]['text']}" for j,r in enumerate(sub))
    out2 = local_chat([{"role":"user","content":
        f"用户说：{q}\n\n从下面挑最相关的一条，只回答序号。\n{lines}"}], max_tokens=16)
    j = _parse_idx(out2, len(sub))
    return sub[j] if j is not None and j < len(sub) else None
def _v3_scope(q, order, profiles):
    scopes = sorted(set(p["scope"] for p in profiles))
    out = local_chat([{"role":"user","content":
        f"用户说：{q}\n\n这句话涉及哪个场景？只回答一个：\n" + " / ".join(scopes)}], max_tokens=16)
    need = next((s for s in scopes if s in out), None)
    sub = [r for r in order if profiles[r]["scope"]==need]
    if not sub: return None
    lines = "\n".join(f"{j}. {profiles[r]['text']}" for j,r in enumerate(sub))
    out2 = local_chat([{"role":"user","content":
        f"用户说：{q}\n\n从下面挑最相关的一条，只回答序号。\n{lines}"}], max_tokens=16)
    j = _parse_idx(out2, len(sub))
    return sub[j] if j is not None and j < len(sub) else None
def _v4(q,o,p): return _pick(q,"用户说：{q}\n\n下面哪条画像跟这句话最相关？只回答序号，-1表示都不相关。\n{opts}",o,p)
def _v5(q,o,p): return _pick(q,"用户说：{q}\n\n要回应用户，最需要知道哪条信息？只回答序号。\n{opts}",o,p)
def _v6(q,o,p): return _pick(q,"用户说：{q}\n\n这句话涉及用户的哪方面？从下面找，只回答序号。\n{opts}",o,p)
def _v7(q,o,p): return _pick(q,"用户说：{q}\n\n哪条画像最相关？只回答序号，-1表示都不相关。\n{opts}",o,p,temp=0.7)
def _v8(q,o,p):
    xs = _pick(q,"用户说：{q}\n\n哪些画像跟用户相关？返回所有相关序号，逗号分隔。-1表示都不相关。\n{opts}",o,p,multi=True)
    return xs[0] if xs else None
def _v9(q,o,p): return _pick(q,"用户说：{q}\n\n假设你要回复用户，需要翻用户档案的哪一条？只回答序号。\n{opts}",o,p)
def _v10(q,o,p): return _pick(q,"用户说：{q}\n\n哪条画像最能帮你理解用户？只回答序号。\n{opts}",o,p)
VESSELS = [
    ("触发词", _v1_trigger, "rule"), ("类型优先", _v2_type_first, "rule"), ("场景优先", _v3_scope, "rule"),
    ("直接挑", _v4, "model"), ("需要信息", _v5, "model"), ("反向", _v6, "model"),
    ("温度", _v7, "model"), ("多选", _v8, "model"), ("翻档案", _v9, "model"), ("帮理解", _v10, "model"),
]
def _run_vessels(q, profiles):
    order = list(range(len(profiles)))
    out = {}
    for n,f,k in VESSELS:
        try: out[n] = (f(q, order, profiles), k)
        except Exception: out[n] = (None, k)
    return out
def _vote(picks):
    from collections import defaultdict
    weight = defaultdict(float); votes = defaultdict(int); has_rule = defaultdict(bool)
    for n,(i,k) in picks.items():
        if i is None: continue
        weight[i] += 1.0 if k=="rule" else 0.5
        votes[i] += 1
        if k=="rule": has_rule[i] = True
    return [(i, weight[i], votes[i], has_rule[i]) for i in weight]
def _qualified(cands):
    out = []
    for i,w,v,hr in cands:
        if hr and v>=2: out.append((i,w,v,hr))
        elif (not hr) and v>=4: out.append((i,w,v,hr))
    return out
def recall(user_msg, profiles=None, topn=2):
    """10 路血管投票（**逻辑未改**），只是画像来源可以外面传进来。"""
    profiles = load_profiles() if profiles is None else profiles
    n = len(profiles)
    if n == 0: return []
    idx = _v1_trigger(user_msg, list(range(n)), profiles)
    if idx is not None:
        return [profiles[idx]]
    picks = _run_vessels(user_msg, profiles)
    cands = _vote(picks)
    q_c = _qualified(cands)
    if not q_c: return []
    q_c.sort(key=lambda x:(x[1],x[2]), reverse=True)
    top = q_c[0]; keep = [top]
    if len(q_c) > 1 and q_c[1][1] >= top[1] * 0.6:
        keep.append(q_c[1])
    return [profiles[i] for i,_,_,_ in keep[:topn]]
def build_system(impressions):
    if not impressions:
        return "你是小焦，用户的本地 AI 伙伴。自然地聊。"
    lines = "\n".join("- " + p["text"] for p in impressions)
    return ("你是小焦，用户的本地 AI 伙伴。\n\n"
            "关于这个人，你手上有的信息：\n" + lines + "\n\n"
            "自然地跟他聊。")
def recall_with_hit(user_msg):
    """血管召回（**只召回、不写盘**）：命中就把 `hit_count` 记在 user_profile 上。

    ⚠️ 这里 +1 的是 **`hit_count`（被召回几次）**，**不动 `said_count`（用户说过几次）** ——
       两个计数 2026-09-17 拆开了（见 `core/user_profile.py` 头部）。"被召回"不是"用户说过"。

    返回的是 `user_profile` 的**原始记录**
    （dict：id/ts/kind/content/why/evidence/source/said_count/hit_count），
    上层直接拿去合并、注入 —— 不再经手第二份画像库。
    """
    from core import user_profile as up
    try:
        records = up.all_records()
    except Exception as e:      # noqa: silent-ok — 画像库读不到就返回空，绝不让对话挂掉
        LOG.debug("读 user_profile 失败（忽略）：%s", e)
        return []
    profs = [{
        "text": str(r.get("content") or ""),
        "type": str(r.get("kind") or ""),
        "id": str(r.get("id") or ""),
        "triggers": [t for t in (r.get("triggers") or []) if t],
        "scope": str(r.get("scope") or r.get("kind") or ""),
        "_raw": r,
    } for r in records if isinstance(r, dict)]
    hits = recall(user_msg, profs)
    for h in hits:
        try:
            # 记账走 user_profile 的 hit()（id 不存在时它自己静默返回，不崩）
            up.hit((h.get("_raw") or {}).get("id"))
        except Exception as e:      # noqa: silent-ok — 记不上账也不该影响召回结果
            LOG.debug("hit 记账失败（忽略）：%s", e)
    return [h["_raw"] for h in hits]


if __name__ == "__main__":
    print("画像库：core.user_profile（logs/psyche/user_profile.jsonl）")
    ps = load_profiles()
    print("现有画像：%d 条" % len(ps))
    for q in ["今天心情不好", "推荐首歌听听", "晚上想吃点啥"]:
        imps = recall(q)
        print("  %s  →  %s" % (q, [p["text"][:16] for p in imps]))
