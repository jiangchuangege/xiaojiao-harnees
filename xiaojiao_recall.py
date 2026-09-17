import hashlib
# -*- coding: utf-8 -*-
"""小焦 · 画像召回层（独立模块，不 import xiaojiao_app 的循环）"""
import os, json, time, hashlib, urllib.request
PROFILES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "xiaojiao_profiles.json")
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
def _gen_id(text):
    """按内容生成稳定 id。同一条内容永远同一个 id（天然去重）。"""
    h = hashlib.md5(str(text or "").encode("utf-8")).hexdigest()[:12]
    return "p_" + h
def load_profiles():
    """读画像库。发现没 id 的画像自动补 id 并写回。"""
    if not os.path.exists(PROFILES_PATH):
        return []
    try:
        with open(PROFILES_PATH, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except Exception:
        return []
    profiles = doc.get("profiles", [])
    if not isinstance(profiles, list):
        return []
    # 惰性补 id
    changed = False
    _now = time.time()
    for p in profiles:
        if not p.get("id"):
            p["id"] = _gen_id(p.get("text") or p.get("content") or "")
            changed = True
        if not p.get("ts"):
            p["ts"] = _now
            changed = True
    if changed:
        doc["profiles"] = profiles
        doc["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        tmp = PROFILES_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        os.replace(tmp, PROFILES_PATH)
    return profiles


# ⚠️ 这一行是**补回来的**：`save_profiles()` / `append_profile()` 都在用 `_WRITE_LOCK`，
# 但 13:24 那次编辑把这个定义弄丢了 —— 结果"血管"的写入链一跑就 `NameError`，
# 每次它判定"要记"都在这里崩掉（实测 `remember_from_message('我对芒果过敏')` → NameError），
# 而调用方把异常吞了，表现是"永远记不住新东西、日志上还看不出来"。
# 语义与原来完全一致（模块级一把可重入锁）。
_WRITE_LOCK = __import__("threading").Lock()


def save_profiles(profiles):
    """原子写：先写临时文件，再 rename，防止并发撕文件。"""
    doc = {"version": 1, "source": "auto",
           "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
           "profiles": profiles}
    with _WRITE_LOCK:
        tmp = PROFILES_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        os.replace(tmp, PROFILES_PATH)


def append_profile(new_p):
    with _WRITE_LOCK:
        ps = load_profiles()
        ps.append(new_p)
        doc = {"version": 1, "source": "auto",
               "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
               "profiles": ps}
        tmp = PROFILES_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        os.replace(tmp, PROFILES_PATH)


def is_duplicate(new_p, profiles):
    nt = new_p["text"].strip()
    for old in profiles:
        ot = old["text"].strip()
        if nt == ot: return True
        if len(nt) > 6 and (nt in ot or ot in nt): return True
    return False
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
def recall(user_msg, topn=2):
    profiles = load_profiles()
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
def should_remember(user_msg):
    prompt = (f"用户说：{user_msg}\n\n"
        "这句话里有没有关于用户本人的、值得长期记住的信息？\n"
        "值得记的：身份、职业、居住地、喜好、忌讳、健康、家人、长期状态。\n"
        "不值得记的：临时情绪、一次性提问、天气、闲聊、问句。\n"
        "只回答两个字：要记 或 不记。")
    out = local_chat([{"role":"user","content":prompt}], temperature=0.0, max_tokens=8)
    return "要记" in out
def generate_profile(user_msg):
    prompt = (f"用户说：{user_msg}\n\n"
        "从这句话提取一条用户画像，输出 JSON，只输出 JSON，不要解释：\n"
        '{"text": "一条简短的画像描述", "type": "状态/偏好/约束/背景", '
        '"triggers": ["名词或特征词"], "scope": "一句话场景"}\n\n'
        "要求：\n- text 用第三人称，一句话，不超过 30 字\n"
        "- type 从 状态/偏好/约束/背景 里选一个\n"
        "- triggers 放名词或特征词，不要放单字动词\n"
        "- scope 是一句话，说明这条画像用在什么场景")
    out = local_chat([{"role":"user","content":prompt}], temperature=0.0, max_tokens=256)
    s = out.find("{"); e = out.rfind("}")
    if s == -1 or e == -1: return None
    try: p = json.loads(out[s:e+1])
    except Exception: return None
    if not all(k in p for k in ("text","type","triggers","scope")): return None
    if p["type"] not in ("状态","偏好","约束","背景"): return None
    if not isinstance(p["triggers"], list): return None
    p["triggers"] = [t for t in p["triggers"] if t not in STOP_TRIGGERS]
    if not p["triggers"]: return None
    return p
def remember_from_message(user_msg):
    if not should_remember(user_msg): return None
    p = generate_profile(user_msg)
    if p is None: return None
    profiles = load_profiles()
    if is_duplicate(p, profiles): return None
    append_profile(p)
    return p

# ========== hit 回写 ==========
def hit(ids):
    """把命中的画像 hit_count +1。跟 user_profile.hit 一样的语义。
    存回 xiaojiao_profiles.json。
    """
    if not ids:
        return 0
    ids = set(ids)
    try:
        with open(PROFILES_PATH, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except Exception:
        return 0
    profiles = doc.get("profiles", [])
    n = 0
    for p in profiles:
        if p.get("id") in ids:
            p["hit_count"] = int(p.get("hit_count") or 0) + 1
            n += 1
    if n:
        doc["profiles"] = profiles
        doc["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        tmp = PROFILES_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        os.replace(tmp, PROFILES_PATH)
    return n
def recall_with_hit(user_msg, topn=2):
    """跟 recall 一样，但会自动把命中的画像 hit_count+1。
    上层直接调这个就行。
    """
    imps = recall(user_msg, topn=topn)
    ids = [p.get("id") for p in imps if p.get("id")]
    if ids:
        hit(ids)
    return imps


if __name__ == "__main__":
    print(f"画像库：{PROFILES_PATH}")
    ps = load_profiles()
    print(f"现有画像：{len(ps)} 条")
    for q in ["今天心情不好", "推荐首歌听听", "晚上想吃点啥"]:
        imps = recall(q)
        print(f"  {q}  →  {[p['text'][:16] for p in imps]}")
