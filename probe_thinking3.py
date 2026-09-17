import sys
sys.path.insert(0, ".")
from xiaojiao_app import llm_chat
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
PROFILES = [
    {"text":"用户最近工作压力大，容易焦虑失眠","type":"状态","triggers":["失眠","压力","焦虑","累","烦"],"scope":"情绪支持"},
    {"text":"用户喜欢轻松随意的聊天，不喜欢被说教","type":"偏好","triggers":["聊聊","闲聊","随便"],"scope":"聊天风格"},
    {"text":"用户对花生严重过敏，绝对不能吃花生","type":"约束","triggers":["花生","过敏","吃"],"scope":"饮食安全"},
    {"text":"用户是后端工程师，常用 Python","type":"背景","triggers":["代码","函数","Python","后端","性能"],"scope":"技术问题"},
    {"text":"用户住在杭州","type":"背景","triggers":["杭州","周边","附近","本地"],"scope":"地理位置"},
    {"text":"用户平时最爱看 NBA","type":"偏好","triggers":["NBA","篮球","球赛","比赛"],"scope":"娱乐"},
    {"text":"用户喜欢猫，养了一只橘猫","type":"背景","triggers":["猫","橘猫","宠物"],"scope":"宠物"},
    {"text":"用户是素食主义者，不吃肉","type":"约束","triggers":["素食","肉","吃"],"scope":"饮食"},
    {"text":"用户正在准备考研，每天学习 10 小时","type":"状态","triggers":["考研","考试","学习"],"scope":"学习"},
    {"text":"用户喜欢听周杰伦的歌","type":"偏好","triggers":["歌","音乐","周杰伦","听"],"scope":"音乐"},
    {"text":"用户最近在减肥，控制饮食","type":"状态","triggers":["减肥","热量","体重"],"scope":"饮食"},
    {"text":"用户有慢性胃炎，不能吃辣","type":"约束","triggers":["辣","胃","吃"],"scope":"饮食健康"},
    {"text":"用户喜欢看悬疑剧和推理小说","type":"偏好","triggers":["剧","悬疑","推理","小说","看"],"scope":"娱乐"},
    {"text":"用户是独居，一个人住","type":"背景","triggers":["独居","一个人","住"],"scope":"生活"},
    {"text":"用户最近刚失恋，情绪低落","type":"状态","triggers":["失恋","分手","难过","低落"],"scope":"情绪支持"},
    {"text":"用户喜欢旅游，去过很多国家","type":"偏好","triggers":["旅游","旅行","出国","玩"],"scope":"旅游"},
    {"text":"用户不会做饭，经常点外卖","type":"背景","triggers":["做饭","外卖","点餐"],"scope":"饮食"},
    {"text":"用户是前端工程师，主要写 React","type":"背景","triggers":["前端","React","跳槽","面试"],"scope":"技术问题"},
    {"text":"用户养了两只狗","type":"背景","triggers":["狗","宠物"],"scope":"宠物"},
    {"text":"用户每天跑步 5 公里","type":"偏好","triggers":["跑步","运动","健身"],"scope":"运动"},
    {"text":"用户喜欢喝咖啡，每天两杯","type":"偏好","triggers":["咖啡","提神","喝"],"scope":"饮食"},
]
N = len(PROFILES)
def parse_idx(out, multi=False):
    if not out: return [] if multi else None
    out = out.replace("，",",").replace("。"," ").replace("、",",").replace("-1"," ")
    idxs = []
    for t in out.split():
        t = t.strip(", ")
        if t.isdigit():
            i = int(t)
            if 0 <= i < N: idxs.append(i)
    return idxs if multi else (idxs[0] if idxs else None)
def build_opts(order):
    return "\n".join(f"{i}. [{PROFILES[r]['type']}] {PROFILES[r]['text']}" for i,r in enumerate(order))
def _pick(q, tpl, order, temp=0.0, multi=False):
    opts = build_opts(order)
    out = llm_chat([{"role":"user","content":tpl.format(q=q, opts=opts)}], temperature=temp)
    disp = parse_idx(out, multi=multi)
    if multi: return [order[d] for d in disp if d < len(order)]
    if disp is None or disp >= len(order): return None
    return order[disp]
def v1_trigger(q, order):
    best, bs = None, 0
    for disp, real in enumerate(order):
        hits = sum(1 for t in PROFILES[real]["triggers"] if t in q)
        if hits > bs: bs, best = hits, disp
    return order[best] if best is not None and bs >= 1 else None
def v2_type_first(q, order):
    types = ["状态","偏好","约束","背景"]
    out = (llm_chat([{"role":"user","content":
        f"用户说：{q}\n\n这句话最需要哪类用户信息？只回答一个：状态/偏好/约束/背景"}],
        temperature=0.0) or "").strip()
    need = next((t for t in types if t in out), None)
    sub = [r for r in order if PROFILES[r]["type"]==need]
    if not sub: return None
    lines = "\n".join(f"{j}. {PROFILES[r]['text']}" for j,r in enumerate(sub))
    out2 = (llm_chat([{"role":"user","content":
        f"用户说：{q}\n\n从下面挑最相关的一条，只回答序号。\n{lines}"}], temperature=0.0) or "")
    j = parse_idx(out2)
    return sub[j] if j is not None and j < len(sub) else None
def v3_scope(q, order):
    scopes = sorted(set(p["scope"] for p in PROFILES))
    out = (llm_chat([{"role":"user","content":
        f"用户说：{q}\n\n这句话涉及哪个场景？只回答一个：\n" + " / ".join(scopes)}],
        temperature=0.0) or "").strip()
    need = next((s for s in scopes if s in out), None)
    sub = [r for r in order if PROFILES[r]["scope"]==need]
    if not sub: return None
    lines = "\n".join(f"{j}. {PROFILES[r]['text']}" for j,r in enumerate(sub))
    out2 = (llm_chat([{"role":"user","content":
        f"用户说：{q}\n\n从下面挑最相关的一条，只回答序号。\n{lines}"}], temperature=0.0) or "")
    j = parse_idx(out2)
    return sub[j] if j is not None and j < len(sub) else None
def v4(q,o): return _pick(q,"用户说：{q}\n\n下面哪条画像跟这句话最相关？只回答序号，-1表示都不相关。\n{opts}",o)
def v5(q,o): return _pick(q,"用户说：{q}\n\n要回应用户，最需要知道哪条信息？只回答序号。\n{opts}",o)
def v6(q,o): return _pick(q,"用户说：{q}\n\n这句话涉及用户的哪方面？从下面找，只回答序号。\n{opts}",o)
def v7(q,o): return _pick(q,"用户说：{q}\n\n哪条画像最相关？只回答序号，-1表示都不相关。\n{opts}",o,temp=0.7)
def v8(q,o):
    xs = _pick(q,"用户说：{q}\n\n哪些画像跟用户相关？返回所有相关序号，逗号分隔。-1表示都不相关。\n{opts}",o,multi=True)
    return xs[0] if xs else None
def v9(q,o): return _pick(q,"用户说：{q}\n\n假设你要回复用户，需要翻用户档案的哪一条？只回答序号。\n{opts}",o)
def v10(q,o): return _pick(q,"用户说：{q}\n\n哪条画像最能帮你理解用户？只回答序号。\n{opts}",o)
VESSELS = [
    ("触发词", v1_trigger, "rule"), ("类型优先", v2_type_first, "rule"), ("场景优先", v3_scope, "rule"),
    ("直接挑", v4, "model"), ("需要信息", v5, "model"), ("反向", v6, "model"),
    ("温度", v7, "model"), ("多选", v8, "model"), ("翻档案", v9, "model"), ("帮理解", v10, "model"),
]
def run(q, order):
    with ThreadPoolExecutor(max_workers=len(VESSELS)) as ex:
        futs = {n: ex.submit(f, q, order) for n,f,_ in VESSELS}
        kinds = {n: k for n,_,k in VESSELS}
        return {n: (futs[n].result(), kinds[n]) for n in futs}
def vote(picks):
    weight = defaultdict(float); votes = defaultdict(int); has_rule = defaultdict(bool)
    for n,(i,k) in picks.items():
        if i is None: continue
        weight[i] += 1.0 if k=="rule" else 0.5
        votes[i] += 1
        if k=="rule": has_rule[i] = True
    return [(i, weight[i], votes[i], has_rule[i]) for i in weight]
def qualified(cands):
    out = []
    for i,w,v,hr in cands:
        if hr and v>=2: out.append((i,w,v,hr))
        elif (not hr) and v>=4: out.append((i,w,v,hr))
    return out
def recall(q):
    picks = run(q, list(range(N)))
    cands = vote(picks)
    q_c = qualified(cands)
    if not q_c: return [], picks
    q_c.sort(key=lambda x:(x[1],x[2]), reverse=True)
    top = q_c[0]
    keep = [top]
    if len(q_c) > 1 and q_c[1][1] >= top[1] * 0.6:
        keep.append(q_c[1])
    return [PROFILES[i] for i,_,_,_ in keep], picks
# ★ 视角注入，不是规则清单
def build_system(impressions):
    if not impressions:
        return "你是小焦，用户的本地 AI 伙伴。像老朋友一样自然地聊天。"
    imp_text = "\n".join(f"- {p['text']}" for p in impressions)
    return (
        "你是小焦，用户的本地 AI 伙伴。\n\n"
        "你记得关于这个人的一些事：\n"
        f"{imp_text}\n\n"
        "带着这些记忆去跟他说话——就像你是一个认识他很久的朋友，"
        "知道他的情况，自然地顺着聊。不用刻意提起这些事，也不用逐条考虑，"
        "只是你说话时会自然带上这个人的影子。"
    )
def think(user_msg):
    impressions, picks = recall(user_msg)
    sys_prompt = build_system(impressions)
    reply = llm_chat([
        {"role":"system","content":sys_prompt},
        {"role":"user","content":user_msg},
    ], temperature=0.7)
    return impressions, picks, reply
MSGS = [
    "晚上想吃点啥，推荐一下",
    "今天心情不好",
    "周末想出去逛逛",
    "推荐首歌听听",
    "帮我看看这段代码",
]
print("="*74)
for msg in MSGS:
    imp, picks, reply = think(msg)
    print()
    print("👤 用户：" + msg)
    print("🎯 召回印象：")
    if imp:
        for p in imp:
            print(f"    [{p['type']}] {p['text']}")
    else:
        print("    （无）")
    print("🤖 小焦：" + reply)
    print("-"*74)
print("="*74)
