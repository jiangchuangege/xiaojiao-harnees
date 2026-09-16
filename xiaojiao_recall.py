# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
"""小焦 · **画像召回层**（10 路血管投票：4 路规则 + 6 路模型）

【它解决的是什么】
    用户画像库里躺着十几条"关于用户的事"。用户说一句话，**该把哪几条摆到它眼前** ——
    这一层就是干这个的。不是检索相似度，是**投票**：多路各自独立地指一条，谁票多谁上。

【为什么必须多路，不许砍成 1 路】
    单路一定有系统性偏好：只看关键词 → 同义词全漏；只问模型 → 4B 会盯着**列表里靠前的那条**
    （位置偏见）。多路投票的意义是**让不同的错法互相抵消**，而不是让某一路更准。

【10 路血管 · 签名统一】`def vN(q, order) -> 画像索引 或 None`
    `order` 是**显示顺序**（list of 真实索引）—— 给它看的是 1..N，回来的是 1..N，
    再映射回真实索引。**顺序每问一次就重新洗**，免得它学会"永远选第一条"。

    | 血管 | 类型 | 它问什么 | 权重 |
    |---|---|---|---|
    | v1_trigger   | 规则 | 画像的触发词命中用户这句话 | 1.0 |
    | v2_type_first| 规则 | 先判「状态/偏好/约束/背景」，再在该类里挑 | 1.0 |
    | v3_scope     | 规则 | 先判场景（scope），再在该场景里挑 | 1.0 |
    | v4_direct    | 模型 | 哪条画像跟这句话最相关 | 0.5 |
    | v5_needed    | 模型 | 要回应用户，最需要知道哪条 | 0.5 |
    | v6_aspect    | 模型 | 这句话涉及用户的哪方面 | 0.5 |
    | v7_temp      | 模型 | 同 v4，但 temperature=0.7（借一点随机性） | 0.5 |
    | v8_multi     | 模型 | 哪些相关，返回所有序号（取第一个） | 0.5 |
    | v9_archive   | 模型 | 假设你要回复，需要翻哪一条 | 0.5 |
    | v10_understand| 模型 | 哪条最能帮你理解用户 | 0.5 |

    ⚠️ 规格里"（可选第 4 路）关键词二字滑窗重叠度"**没有单开成第 11 路** ——
    因为它的编号会和模型血管 v4 撞车，而规格同时要求"10 路是核心、权重与门槛不许改"。
    它的能力**没有丢**：作为**加分项**并进了 v1（`ngram_overlap()`），
    规则票的权重仍是 1.0。见 `v1_trigger()` 的注释。

【投票与门槛】（规格给定，一个数都不许动）
    · 规则票 weight += 1.0；模型票 weight += 0.5；都 votes += 1；并记下有没有规则票
    · 合格候选：**有规则票** → `votes >= 2 且 weight >= 1.0`；**纯模型票** → `votes >= 4`
      （4 路是防"同源模型假多数"：7 路模型血管都出自同一个 4B，容易一起错，所以门槛抬高）
    · 排序：weight 降序 → votes 降序
    · 取前 2 条，但**第 2 条的 weight 必须 >= 第 1 条 × 0.6**，否则只返回 1 条
    · 没有合格候选 → 返回空列表（**宁可不给，也不硬塞**）

【为什么直连 9292，不走 llm_chat()】
    主程序的 `llm_chat()` **首选云端**（曾实测：熔断/兜底都在它里面）。这一层要的是
    **本地大脑的稳定行为**：同一个 4B、同一份权重、可复现。走 llm_chat() 会变成
    "这一问是云端答的、下一问是本地答的"，投票结果就不可比了。所以这里用 urllib 直连。

【串行，不许并发】
    llama-swap 上的本地 4B **一次只服务一个请求**，并发只会排队 + 互相拖慢。
    所以血管**一路一路跑**（规格明确要求，见 `recall()` 的注释）。
"""
from __future__ import annotations

import json
import random
import re
import sys
import urllib.error
import urllib.request

__all__ = ["PROFILES", "STOP_TRIGGERS", "recall", "build_system", "local_chat",
           "answer", "chat", "ngram_overlap", "VESSELS"]

import os

# 诊断开关：`XIAOJIAO_RECALL_DEBUG=1` 时把每一路的**原始输出**打出来。
# 为什么留这个：投票结果不对时，必须分得清"模型没选它"和"载体把它的选择解析丢了" ——
# 这两种情况的修法完全相反（一个改问法，一个改解析）。
DEBUG_RAW = os.environ.get("XIAOJIAO_RECALL_DEBUG") == "1"

# ================== 本地大脑：直连，不走 llm_chat() ==================
LOCAL_BASE = "http://127.0.0.1:9292/v1"

# 模型血管统一参数（规格给定）
MODEL_MAX_TOKENS = 64
MODEL_TEMPERATURE = 0.0
V7_TEMPERATURE = 0.7

# 投票权重（规格给定，不许改）
W_RULE = 1.0
W_MODEL = 0.5
# 合格门槛（规格给定，不许改）
NEED_RULE_VOTES = 2
NEED_RULE_WEIGHT = 1.0
NEED_MODEL_VOTES = 4
# 第二条的权重必须 >= 第一条的 0.6 倍，否则只返回 1 条（规格给定）
SECOND_RATIO = 0.6
TOP_N = 2

# ================== 单字动词过滤（规格给定）==================
# 【为什么要它】"看/吃/喝/玩/听…"是**万能词**：用户说"帮我看看这段代码"命中"看"、
# 说"晚上想吃点啥"命中"吃" —— 一条画像只要触发词里混进单字动词，就会**到处乱命中**，
# 投票立刻失去区分度。所以触发词只许放**名词/特征词**，命中时再兜一道闸。
STOP_TRIGGERS = {"看", "吃", "喝", "玩", "听", "写", "读", "买", "去", "走",
                 "做", "学", "用", "说", "讲"}

# 四个合法类型（规格给定）
TYPES = ("状态", "偏好", "约束", "背景")


# ================== 画像库（占位：16 条测试数据）==================
# 【四条字段一个都不能少】
#   text     一句话事实（原样摆给模型看，载体不改写）
#   type     状态 / 偏好 / 约束 / 背景     ← v2 靠它
#   triggers 触发词（**只放名词/特征词**） ← v1 靠它
#   scope    场景（饮食安全 / 技术问题…）   ← v3 靠它
# 少了 triggers 或 scope，就等于把两条血管废掉 —— 上一版就是这么废的。
PROFILES = [
    {"text": "用户对花生严重过敏，绝对不能吃花生", "type": "约束",
     "triggers": ["花生", "过敏"], "scope": "饮食安全"},
    {"text": "用户乳糖不耐受，喝牛奶会不舒服", "type": "约束",
     "triggers": ["牛奶", "乳糖"], "scope": "饮食安全"},
    {"text": "用户不会做饭，经常点外卖", "type": "背景",
     "triggers": ["做饭", "外卖", "点餐"], "scope": "饮食"},
    {"text": "用户是后端工程师，常用 Python", "type": "背景",
     "triggers": ["代码", "函数", "Python", "后端", "性能"], "scope": "技术问题"},
    {"text": "用户住在杭州", "type": "背景",
     "triggers": ["杭州", "周边", "附近", "本地"], "scope": "地理位置"},
    {"text": "用户最近刚失恋，情绪低落", "type": "状态",
     "triggers": ["失恋", "分手", "难过", "低落", "心情"], "scope": "情绪支持"},
    {"text": "用户喜欢听周杰伦的歌", "type": "偏好",
     "triggers": ["歌", "音乐", "周杰伦"], "scope": "音乐"},
    {"text": "用户喜欢猫，养了一只橘猫", "type": "偏好",
     "triggers": ["猫", "橘猫", "宠物"], "scope": "宠物"},
    {"text": "用户最爱看 NBA 比赛", "type": "偏好",
     "triggers": ["NBA", "篮球", "球赛", "比赛"], "scope": "娱乐"},
    {"text": "用户喜欢旅游，去过很多国家", "type": "偏好",
     "triggers": ["旅游", "旅行", "出国", "逛逛", "出去"], "scope": "旅游"},
    {"text": "用户喜欢看悬疑电影", "type": "偏好",
     "triggers": ["电影", "悬疑", "推理", "剧"], "scope": "娱乐"},
    {"text": "用户最近在学吉他", "type": "状态",
     "triggers": ["吉他", "乐器", "练习"], "scope": "学习"},
    {"text": "用户每天早上喝黑咖啡", "type": "偏好",
     "triggers": ["咖啡", "提神", "早上"], "scope": "饮食"},
    {"text": "用户喜欢的作家是村上春树", "type": "偏好",
     "triggers": ["书", "阅读", "作家", "小说", "村上"], "scope": "阅读"},
    {"text": "用户的女儿今年上小学三年级", "type": "背景",
     "triggers": ["女儿", "孩子", "小学", "三年级"], "scope": "家庭"},
    {"text": "用户喜欢安静的地方，不喜欢吵闹", "type": "偏好",
     "triggers": ["安静", "吵闹", "静", "吵"], "scope": "环境偏好"},
]


# ================== 本地对话（urllib 直连 127.0.0.1:9292）==================
_MODEL_CACHE = {"model": ""}


def _local_model():
    """本地大脑的模型 id。

    规格要求用主程序的 `xiaojiao_app._local_brain_model()` 探（它会跳过 coder 那个模型）。
    探不到（主程序导入失败 / llama-swap 正在换模型）就退回本地默认名 —— **保证有目标**，
    否则整层会静默返回空列表，看起来像"画像库坏了"。
    """
    if _MODEL_CACHE["model"]:
        return _MODEL_CACHE["model"]
    m = ""
    try:
        sys.path.insert(0, _here())
        import xiaojiao_app as _X          # noqa: PLC0415 — 只在首次需要时导入
        m = _X._local_brain_model()
    except Exception:      # noqa: silent-ok — 探不到就用本地默认名，不让整层挂掉
        m = ""
    _MODEL_CACHE["model"] = m or "xiaojiao"
    return _MODEL_CACHE["model"]


def _here():
    import os
    return os.path.dirname(os.path.abspath(__file__))


def local_chat(messages, temperature=0.7, max_tokens=512, timeout=180):
    """**直连**本地大脑。返回回答文本；连不上/解析不出返回 ""。

    ⚠️ 这里**故意不走** `xiaojiao_app.llm_chat()` —— 它首选云端，会把这一层变成
    "一会儿本地答、一会儿云端答"，投票就不可比了（见模块头注释）。
    """
    payload = {"model": _local_model(), "messages": messages,
               "temperature": temperature, "max_tokens": max_tokens}
    req = urllib.request.Request(
        LOCAL_BASE + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        return str((d.get("choices") or [{}])[0].get("message", {}).get("content") or "")
    except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError):
        return ""


# ================== 共用小工具 ==================
# 血管的签名是规格定死的 `vN(q, order)`，没法再挂一个 profiles 参数 ——
# 所以"当前正在用哪个画像库"放在这里：`recall()` 进来时设一次。
# 不直接改写 `PROFILES` 本身，那个是给外面看的模块级常量。
_P = {"rows": None}


def _rows():
    return _P["rows"] if _P["rows"] is not None else PROFILES


def _hits(idx, q):
    """这条画像的触发词命中了几个（单字动词不算）。"""
    n = 0
    for t in _rows()[idx].get("triggers") or []:
        if t in q and t not in STOP_TRIGGERS:
            n += 1
    return n


def ngram_overlap(a, b, n=2):
    """二字滑窗重叠度（0.0~1.0）。规格里"可选第 4 路规则血管"的能力并在这里。"""
    a = re.sub(r"[\s\W_]+", "", str(a or ""))
    b = re.sub(r"[\s\W_]+", "", str(b or ""))
    if len(a) < n or len(b) < n:
        return 0.0
    ga = {a[i:i + n] for i in range(len(a) - n + 1)}
    gb = {b[i:i + n] for i in range(len(b) - n + 1)}
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / float(len(ga | gb))


def _card(idx):
    """画像在提示词里长什么样：`[约束] 用户对花生严重过敏…（场景：饮食安全）`"""
    p = _rows()[idx]
    return "[%s] %s（场景：%s）" % (p.get("type"), p.get("text"), p.get("scope"))


def _menu(order):
    """把 `order` 渲染成"1..N"的显示清单（模型看到的就是这个）。"""
    return "\n".join("%d. %s" % (i + 1, _card(idx)) for i, idx in enumerate(order))


def _pick_number(text, order):
    """从模型回答里抠出显示序号 → 真实索引。抠不到返回 None。

    【为什么要这么宽容】4B 会说「第 3 条」「3」「3、7」「3. 用户爱看 NBA」，
    还会先复述一遍清单再给答案。**只认严格数字格式，漏的会全算成"这一路弃权"**，
    投票就会集体偏向没弃权的那几路。
    """
    for m in re.finditer(r"\d+", str(text or "")):
        k = int(m.group(0))
        if 1 <= k <= len(order):
            return order[k - 1]
    return None


_VESSEL_INTRO = ("下面是关于用户的画像，按显示序号列出：\n%s\n\n用户刚说：「%s」\n\n")


def _ask(q, order, question, temperature=MODEL_TEMPERATURE):
    """一路模型血管：把清单和它自己的问题发过去，抠回一个显示序号。"""
    prompt = (_VESSEL_INTRO % (_menu(order), q)) + question
    out = local_chat([{"role": "user", "content": prompt}],
                     temperature=temperature, max_tokens=MODEL_MAX_TOKENS)
    if DEBUG_RAW:
        print("      [raw] %s" % str(out).replace("\n", " ")[:90])
    return _pick_number(out, order)


# ================== 4 路规则血管（权重 1.0）==================
def v1_trigger(q, order):
    """触发词命中最多者胜（单字动词不算）。

    排序依据：① 触发词命中数 ② 二字滑窗重叠度（规格里那条"可选第 4 路"的能力并在这）
    ③ 显示顺序（兜底，保证确定性）。
    """
    best, best_key = None, (0, 0.0)
    for pos, idx in enumerate(order):
        h = _hits(idx, q)
        if h <= 0:
            continue
        key = (h, ngram_overlap(q, _rows()[idx].get("text")))
        if key > best_key or (key == best_key and best is None):
            best, best_key = idx, key
    return best


def _judge(q, options, question):
    """让模型从 `options`（真实索引列表）里挑一个 —— v2/v3 的"先判再挑"用它。"""
    order = list(options)
    if not order:
        return None
    if len(order) == 1:
        return order[0]
    return _ask(q, order, question, temperature=MODEL_TEMPERATURE)


def v2_type_first(q, order):
    """先让模型判「状态/偏好/约束/背景」，再在该类里挑。

    判出类型之后**不是随便挑一条**：先用触发词/滑窗在该类内选（规则的部分），
    一条都没命中才回头问模型"这一类里哪条"。
    """
    opts = "\n".join("%d. %s" % (i + 1, t) for i, t in enumerate(TYPES))
    out = local_chat([{"role": "user", "content":
                       "用户说：「%s」\n\n下面是四类信息：\n%s\n\n"
                       "用户这句话最像是在说哪一类？只回一个数字。"
                       % (q, opts)}],
                     temperature=MODEL_TEMPERATURE, max_tokens=MODEL_MAX_TOKENS)
    t = None
    for m in re.finditer(r"\d+", str(out or "")):
        k = int(m.group(0))
        if 1 <= k <= len(TYPES):
            t = TYPES[k - 1]
            break
    if t is None:
        return None
    same = [i for i in order if _rows()[i].get("type") == t]
    if not same:
        return None
    scored = [(idx, _hits(idx, q), ngram_overlap(q, _rows()[idx].get("text")))
              for idx in same]
    top = max(s[1] for s in scored)
    if top > 0:
        cand = [s for s in scored if s[1] == top]
        cand.sort(key=lambda s: (-s[2], same.index(s[0])))
        return cand[0][0]
    return _judge(q, same, "这几条里哪一条跟用户这句话关系最近？只回一个数字。")


def v3_scope(q, order):
    """先让模型判场景（scope），再在该场景里挑。与 v2 同一套逻辑，换的是维度。"""
    scopes = []
    for idx in order:
        sc = _rows()[idx].get("scope")
        if sc and sc not in scopes:
            scopes.append(sc)
    if not scopes:
        return None
    opts = "\n".join("%d. %s" % (i + 1, s) for i, s in enumerate(scopes))
    out = local_chat([{"role": "user", "content":
                       "用户说：「%s」\n\n下面是一些场景：\n%s\n\n"
                       "用户这句话最可能落在哪个场景里？只回一个数字。"
                       % (q, opts)}],
                     temperature=MODEL_TEMPERATURE, max_tokens=MODEL_MAX_TOKENS)
    sc = None
    for m in re.finditer(r"\d+", str(out or "")):
        k = int(m.group(0))
        if 1 <= k <= len(scopes):
            sc = scopes[k - 1]
            break
    if sc is None:
        return None
    same = [i for i in order if _rows()[i].get("scope") == sc]
    if not same:
        return None
    top = max(_hits(i, q) for i in same)
    if top > 0:
        cand = [i for i in same if _hits(i, q) == top]
        return cand[0]
    return _judge(q, same, "这几条里哪一条跟用户这句话关系最近？只回一个数字。")


# ================== 6 路模型血管（权重 0.5）==================
def v4_direct(q, order):
    """直接挑：哪条画像跟这句话最相关。"""
    return _ask(q, order, "哪条画像跟这句话最相关？只回一个数字。")


def v5_needed(q, order):
    """需要信息：要回应用户，最需要知道哪条。"""
    return _ask(q, order, "要回应用户这句话，你最需要知道上面哪一条？只回一个数字。")


def v6_aspect(q, order):
    """反向：这句话涉及用户的哪方面。"""
    return _ask(q, order, "这句话涉及用户的哪一方面？只回一个数字。")


def v7_temp(q, order):
    """同 v4，但 temperature=0.7 —— 借一点随机性，避免七路模型血管给出同一个答案。"""
    return _ask(q, order, "哪条画像跟这句话最相关？只回一个数字。", temperature=V7_TEMPERATURE)


def v8_multi(q, order):
    """多选：哪些相关，返回所有序号 → **取第一个**。"""
    return _ask(q, order, "哪些画像跟这句话有关？把所有相关的序号都列出来，用逗号隔开。")


def v9_archive(q, order):
    """翻档案：假设你要回复，需要翻哪一条。"""
    return _ask(q, order, "假设你马上要回复用户，你会去翻上面哪一条？只回一个数字。")


def v10_understand(q, order):
    """帮理解：哪条最能帮你理解用户。"""
    return _ask(q, order, "哪一条最能帮你理解这个用户？只回一个数字。")


# 10 路血管：(名字, 函数, 权重)
VESSELS = (
    ("v1_trigger", v1_trigger, W_RULE),
    ("v2_type_first", v2_type_first, W_RULE),
    ("v3_scope", v3_scope, W_RULE),
    ("v4_direct", v4_direct, W_MODEL),
    ("v5_needed", v5_needed, W_MODEL),
    ("v6_aspect", v6_aspect, W_MODEL),
    ("v7_temp", v7_temp, W_MODEL),
    ("v8_multi", v8_multi, W_MODEL),
    ("v9_archive", v9_archive, W_MODEL),
    ("v10_understand", v10_understand, W_MODEL),
)


# ================== 投票 ==================
def _shuffled_order(q, n):
    """显示顺序：**每一问都重新洗**，防止位置偏见。

    用「问题」当随机种子 → 同一个问题每次洗成同一个顺序（可复现，便于对账），
    不同问题顺序不同（模型学不到"永远选第 1 条"）。
    """
    order = list(range(n))
    random.Random(sum(ord(c) for c in str(q)) * 7919 + len(str(q))).shuffle(order)
    return order


def recall(q, profiles=None, verbose=False):
    """10 路投票 → 返回 0~2 条画像（`dict` 列表，按 weight 降序）。

    ⚠️ **串行跑**，不许 ThreadPoolExecutor：llama-swap 上的本地 4B 一次只服务一个请求，
    并发只会排队 + 把每一路都拖慢（规格明确要求，见模块头注释）。
    """
    global PROFILES
    _P["rows"] = list(profiles) if profiles is not None else PROFILES
    n = len(_P["rows"])
    if n == 0 or not str(q).strip():
        return []
    order = _shuffled_order(q, n)

    tally = {}
    for name, fn, w in VESSELS:
        try:
            idx = fn(q, order)
        except Exception as e:      # noqa: silent-ok — 一路挂了不许拖垮整次召回
            if verbose:
                print("    %-16s 异常：%s" % (name, e))
            idx = None
        if verbose:
            print("    %-16s → %s" % (name, PROFILES[idx]["text"][:24] if idx is not None else "弃权"))
        if idx is None or not (0 <= idx < n):
            continue
        slot = tally.setdefault(idx, {"weight": 0.0, "votes": 0, "rule": False})
        slot["weight"] += w
        slot["votes"] += 1
        if w >= W_RULE:
            slot["rule"] = True

    ok = []
    for idx, s in tally.items():
        if s["rule"]:
            if s["votes"] >= NEED_RULE_VOTES and s["weight"] >= NEED_RULE_WEIGHT:
                ok.append((idx, s))
        elif s["votes"] >= NEED_MODEL_VOTES:      # 纯模型票：防同源模型假多数
            ok.append((idx, s))
    ok.sort(key=lambda t: (-t[1]["weight"], -t[1]["votes"], t[0]))
    if verbose:
        print("    合格候选：%s" % [("%s w=%.1f v=%d" % (PROFILES[i]["text"][:12],
                                                    s["weight"], s["votes"])) for i, s in ok])
    if not ok:
        return []
    picked = [ok[0]]
    if len(ok) > 1 and ok[1][1]["weight"] >= ok[0][1]["weight"] * SECOND_RATIO:
        picked.append(ok[1])
    return [dict(PROFILES[i], _idx=i, _weight=s["weight"], _votes=s["votes"])
            for i, s in picked[:TOP_N]]


# ================== system 模板（已定稿，一个字都不许改）==================
# 【绝对禁止】不许加任何额外指令：
#   · 不许加"像认识很久的朋友" → 会编造共同经历
#   · 不许加"不要编造"         → 会脑梗
#   · 不许加"必须避开"         → 会脑梗
#   · 不许加"约束类型要排除"   → 会脑梗
# 只给信息，不描述关系，不下命令。已实测。
_TMPL_WITH = ("你是小焦，用户的本地 AI 伙伴。\n\n"
              "关于这个人，你手上有的信息：\n%s\n\n"
              "自然地跟他聊。")
_TMPL_NONE = "你是小焦，用户的本地 AI 伙伴。自然地聊。"


def build_system(impressions):
    """按定稿模板拼 system。有印象 → 列出来；没印象 → 那一句短的。"""
    rows = list(impressions or [])[:TOP_N]
    if not rows:
        return _TMPL_NONE
    return _TMPL_WITH % "\n".join("- " + r.get("text", "") for r in rows)


# ================== 调用流程 ==================
def chat(user_msg, temperature=0.7, max_tokens=512, verbose=False):
    """一条消息走完：召回 → 拼 system → 发给本地大脑。返回 dict（含过程，便于对账）。"""
    impressions = recall(user_msg, verbose=verbose)
    sys_text = build_system(impressions)
    messages = [{"role": "system", "content": sys_text},
                {"role": "user", "content": user_msg}]
    reply = local_chat(messages, temperature=temperature, max_tokens=max_tokens)
    return {"reply": reply, "impressions": impressions, "system": sys_text,
            "messages": messages}


def answer(user_msg, temperature=0.7, max_tokens=512):
    """只要回答文本。"""
    return chat(user_msg, temperature=temperature, max_tokens=max_tokens)["reply"]


# ================== 自测（规格给定的 10 条）==================
# (用户这句话, 期望召回的顺序：第 1 个是主要期望)
CASES = (
    ("晚上想吃点啥，推荐一下", ("花生", "不会做饭")),
    ("今天心情不好", ("失恋",)),
    ("周末想出去逛逛", ("旅游", "杭州", "安静")),
    ("推荐首歌听听", ("周杰伦",)),
    ("帮我看看这段代码", ("后端",)),
    ("有什么好看的电影推荐", ("悬疑",)),
    ("我最近在学吉他，有什么建议", ("吉他",)),
    ("早上喝什么好", ("咖啡", "乳糖")),
    ("推荐本书看看", ("村上",)),
    ("我女儿最近学习怎么样", ("女儿",)),
)


def _selftest():
    print("=" * 78)
    print("画像召回层自测（10 条）—— 主要期望命中即算这条通过")
    print("=" * 78)
    ok = 0
    for i, (q, expect) in enumerate(CASES, 1):
        print("\n【%d】%s    期望：%s" % (i, q, " / ".join(expect)))
        got = recall(q, verbose=True)
        texts = [g["text"] for g in got]
        for t in texts:
            print("     ✓ %s" % t)
        if not texts:
            print("     （空：没有合格候选）")
        hit = any(any(e in t for t in texts) for e in expect[:1])
        ok += 1 if hit else 0
        print("     判定：%s" % ("通过 ✅" if hit else "**没召回主期望** ❌"))
    print("\n" + "=" * 78)
    print("自测结果：%d/10（判定标准 ≥9/10）" % ok)
    print("=" * 78)
    return 0 if ok >= 9 else 1


def _main(argv):
    if not argv:
        return _selftest()
    if argv[0] == "--selftest":
        return _selftest()
    q = " ".join(argv)
    r = chat(q, verbose=True)
    print("\n召回：%s" % [x["text"] for x in r["impressions"]] or "（空）")
    print("-" * 60)
    print(r["system"])
    print("-" * 60)
    print(r["reply"])
    return 0


if __name__ == "__main__":
    sys.exit(_main([a for a in sys.argv[1:]]))
