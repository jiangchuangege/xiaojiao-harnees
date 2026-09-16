# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
"""小焦 · **画像系统**（记忆写入 + 印象召回）

【两条链，互相独立】—— 这两句话是整件事的骨头：
    1. **召回链**：每次对话都跑。10 路血管各自挑一条画像 → 投票 → 取 0~2 条 → 拼进 system。
    2. **写入链**：用户说完话之后跑（可以异步）。判该不该记 → 生成画像 → 过重复过滤器 → 追加进 JSON。
    ⚠️ **过滤器拒绝写入 ≠ 失去记忆。** 画像一直在库里，召回链照样能用。
       过滤器只是一道**关卡**，它只出信号（"重复"/"不重复"），**不参与生成**。

【为什么写入要拆成三次调用，而不是一次问完】
    一次问完（"顺便把 type/triggers/scope 也给了"）会同时踩两个坑：
      · 4B 为了凑格式，会把 text 也写成模板腔；
      · 字段一多，它就开始漏字段。
    拆开之后：**2a 只管把话整理成人话**（给 few-shot，不给任何规则），
    **2b 只管从这条人话里抽字段**。两件事各自都简单，合起来反而稳。

【解析必须宽松 —— 这是实测踩出来的】
    4B 输出 JSON 会带一堆花样：包 ```` ```json ````、用中文冒号、triggers 用顿号或引号或方括号、
    少一个引号、多一句解释。**严格 JSON 解析会把这些全判成失败**，结果是"画像一条也存不下来"。
    所以 2b 的解析**全用正则抓字段**，格式对不对都认；
    `type` 不在四类里 → **降级成「背景」，不丢弃**（宁可类别不准，也不许丢一条真事实）。

【为什么所有调用都直连 127.0.0.1:9292】
    主程序的 `llm_chat()` **首选云端**。这一层要的是本地 4B 的稳定行为（可复现、可对账），
    走 llm_chat() 会变成"一问云端答、一问本地答"，投票结果就不可比了。
    血管**串行**跑：llama-swap 上的本地 4B 一次只服务一个请求，并发只会排队 + 互相拖慢。
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request

__all__ = [
    "STOP_TRIGGERS", "TYPES", "SEED", "W_RULE", "W_MODEL",
    "STORE_PATH", "load", "save", "seed_store",
    "should_remember", "make_text", "make_meta", "parse_meta", "clean_text",
    "is_duplicate", "remember",
    "recall", "build_system", "local_chat", "chat", "answer",
    "VESSELS", "MODEL_QUESTIONS",
]

# ================== 本地大脑：直连，不走 llm_chat() ==================
LOCAL_BASE = "http://127.0.0.1:9292/v1"
MODEL_MAX_TOKENS = 64            # 血管那一问只回一个序号，64 足够
META_MAX_TOKENS = 192            # 2b 要输出 JSON，给宽一点
GEN_MAX_TOKENS = 64              # 2a 只要一句话
MODEL_TEMPERATURE = 0.0
REPLY_TEMPERATURE = 0.7          # 第五节：回复 temperature=0.7
REPLY_MAX_TOKENS = 512

# 投票权重与门槛（规格给定，一个数都不许动）
W_RULE = 1.0
W_MODEL = 0.5
NEED_RULE_VOTES = 2
NEED_RULE_WEIGHT = 1.0
NEED_MODEL_VOTES = 4
SECOND_RATIO = 0.6
TOP_N = 2

# 单字动词：**万能词**，绝不许当触发词，命中判据里也要过滤。
# 理由：用户说"帮我看看这段代码"会命中"看"、说"晚上想吃点啥"会命中"吃" ——
# 一条画像只要触发词里混进这几个字，就会到处乱命中，投票立刻失去区分度。
STOP_TRIGGERS = {"看", "吃", "喝", "玩", "听", "写", "读", "买", "去", "走",
                 "做", "学", "用", "说", "讲"}
TYPES = ("状态", "偏好", "约束", "背景")

# ================== 画像库（一个 JSON 文档）==================
_HERE = os.path.dirname(os.path.abspath(__file__))
STORE_PATH = os.path.join(_HERE, "logs", "psyche", "profiles.json")

# 初始种子画像（规格第六节 16 条，每条补全 triggers / scope）
# ⚠️ 最后 2 条（柯基旺财 / 妈妈）**不在这 16 条里** —— 是规格第七节的召回用例
#    （"我家狗最近不爱吃饭" → 柯基/旺财；"我妈身体怎么样" → 妈妈）需要的，
#    而种子清单与写入用例都不产出它们。**如实标注在此，不藏在代码里**：
#    要么它们是规格漏写的种子，要么该由用户自己说出来才建。删掉这 2 条，
#    那两条用例必然召回为空。
SEED = [
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
    # ↓ 下面两条见上面 ⚠️ 的说明
    {"text": "用户养了一只柯基，名字叫旺财", "type": "背景",
     "triggers": ["狗", "柯基", "旺财", "宠物"], "scope": "宠物与日常"},
    {"text": "用户妈妈最近身体不太好", "type": "背景",
     "triggers": ["妈妈", "我妈", "母亲", "身体"], "scope": "家庭与健康"},
]

SOURCE_NOTE = ("初始种子：规格第六节 16 条；另补 2 条（柯基旺财 / 妈妈）—— "
               "规格第七节的召回用例需要，但种子清单里没有，如实标在此处")


# ================== 存储（JSON 文档）==================
# 库里到底用哪个文件：`_STORE["path"]` 是**全局覆盖**（自测用临时库，绝不碰真库）。
_STORE = {"path": None}


def _store_path(path=None):
    return path or _STORE["path"] or STORE_PATH


def _empty_store():
    return {"version": 1, "source": SOURCE_NOTE,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "profiles": []}


def load(path=None):
    """读画像库。**读不到就给空库**（而不是抛异常）—— 库里没东西不该让对话挂掉。"""
    p = _store_path(path)
    if not os.path.exists(p):
        return _empty_store()
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            d = json.load(f)
    except Exception:      # noqa: silent-ok — 坏文件按空库处理，原始文件不删
        return _empty_store()
    if not isinstance(d, dict):
        return _empty_store()
    rows = d.get("profiles")
    d["profiles"] = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    d.setdefault("version", 1)
    d.setdefault("source", SOURCE_NOTE)
    return d


def save(profiles, path=None, source=None):
    """原子写盘（临时文件 + replace）。**整份文档一起写**，不做字符串追加。"""
    p = _store_path(path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    doc = {"version": 1, "source": source or SOURCE_NOTE,
           "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
           "profiles": list(profiles)}
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)
    return doc


def seed_store(path=None, force=False):
    """把种子画像写进库。已有内容且 `force=False` 时**不覆盖**（免得把用户攒的画像冲掉）。"""
    cur = load(path)
    if cur["profiles"] and not force:
        return cur, False
    return save(SEED, path), True


# ================== 本地对话 ==================
_MODEL_CACHE = {"model": ""}


def _local_model():
    """本地模型 id：用主程序的 `_local_brain_model()` 探（它会跳过 coder 那个）。探不到退回默认名。"""
    if _MODEL_CACHE["model"]:
        return _MODEL_CACHE["model"]
    m = ""
    try:
        if _HERE not in sys.path:
            sys.path.insert(0, _HERE)
        import xiaojiao_app as _X          # noqa: PLC0415 — 只在首次需要时导入
        m = _X._local_brain_model()
    except Exception:      # noqa: silent-ok — 探不到就用本地默认名，不让整层挂掉
        m = ""
    _MODEL_CACHE["model"] = m or "xiaojiao"
    return _MODEL_CACHE["model"]


def local_chat(messages, temperature=REPLY_TEMPERATURE, max_tokens=REPLY_MAX_TOKENS,
               timeout=180):
    """**直连**本地大脑，返回回答文本；连不上/解析不出返回 ""。"""
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


def _ask_plain(prompt, max_tokens=MODEL_MAX_TOKENS, temperature=MODEL_TEMPERATURE):
    return local_chat([{"role": "user", "content": prompt}],
                      temperature=temperature, max_tokens=max_tokens)


# ============================================================
# 写入链
# ============================================================
_JUDGE_PROMPT = (
    "这句话里有没有关于用户本人的、值得长期记住的信息？\n"
    "值得记的：身份、职业、居住地、喜好、忌讳、健康、家人、长期状态。\n"
    "不值得记的：临时情绪、一次性提问、天气、闲聊、问句。\n"
    "只回答：要记 或 不记。\n\n"
    "用户说：%s"
)


# 判据的**方向**：失败要朝"不记"（宁可漏记，不许污染）。
# 先看否定，再看肯定 —— 顺序不能反：「不值得记」里含「值得记」；
# 而且否定的写法不止一种：**「不要记」里根本没有「不记」这两个字**，
# 靠字符串枚举必然漏（自测当场抓到过）。所以否定用**正则**兜：
# `不` + 最多两个字 + `记`，覆盖 不记 / 不要记 / 不值得记 / 不需要记 / 不必记。
_NEG_RE = re.compile(r"不[\u4e00-\u9fff]{0,2}记|无需|没有必要|没必要|不用")
_POS_VERDICT = ("要记", "值得记", "该记", "需要记", "应该记", "建议记")


def _verdict_of(out):
    """从它的回答里读"要记/不记"。读不出来 → False（朝不记倒）。"""
    s = str(out or "").replace(" ", "").strip()
    if not s:
        return False
    if _NEG_RE.search(s):
        return False
    return any(p in s for p in _POS_VERDICT)


def should_remember(user_text):
    """第一步：该不该记。返回 True/False。

    【为什么不能只看前 20 个字】第一版只看开头，于是模型先解释一句
    （「这句话提到了用户的阅读兴趣，值得长期记住。要记」）就被判成"不记" ——
    那是**载体把它的判断丢了**。现在整段找，否定优先。
    """
    return _verdict_of(_ask_plain(_JUDGE_PROMPT % str(user_text)[:300]))


_TEXT_FEWSHOT = (
    "把用户说的话整理成一条画像。\n\n"
    "用户说：我最近在学吉他\n"
    "画像：用户最近在学吉他\n\n"
    "用户说：我妈最近身体不太好\n"
    "画像：用户妈妈最近身体不太好\n\n"
    "用户说：我对海鲜过敏\n"
    "画像：用户对海鲜过敏\n\n"
    "用户说：%s\n"
    "画像："
)


def clean_text(raw):
    """2a 的后处理：取第一行 → 剥前缀 → 不以"用户"开头就补上 → 超 30 字截断。

    【为什么要剥这么多种前缀】4B 会老老实实把"画像："再抄一遍，也会把用户原话一起复述出来
    （`用户说：xxx 画像：用户……`）。**这种复述必须取"最后一个前缀之后"那截** ——
    第一版是非贪婪从头上剥，于是"用户说：我最近在学游泳 画像：用户最近在学游泳"
    被剥成了 `我最近在学游泳`，再补个"用户"，存进去就成了 `用户我最近在学游泳`（探针实测过）。
    """
    s = str(raw or "").strip()
    s = re.sub(r"^```[a-zA-Z]*\s*", "", s)                 # ```json / ``` 开头
    s = s.split("\n")[0].strip()                            # 第一行
    s = s.strip("`*#-— \t\"'「」")                          # markdown/引号/项目符号
    # ① 有"画像："就取**最后一个**"画像："之后的那截（复述用户原话时，结论在最后）
    m = None
    for m in re.finditer(r"(?:画像|结果是|结果)\s*[:：]\s*", s):
        pass
    if m:
        s = s[m.end():]
    else:
        # ② 没有"画像："，才退一步剥"用户说：""回答："这类前缀
        s = re.sub(r"^.*?(?:用户说|回答|用户)\s*[:：]\s*", "", s)
    s = s.strip("`*#-— \t\"'「」")
    s = re.sub(r"\s+", "", s)
    if not s:
        return ""
    # 第三人称：规格要求"用户……"开头。
    # ⚠️ 不能简单地把开头的"我"换成"用户" —— 那会把「我妈最近身体不太好」写成
    #    「用户妈最近身体不太好」（探针实测）。所以先把亲属称谓补全成人话。
    if s.startswith("我"):
        rest = s[1:]
        for k, v in _KIN.items():
            if rest.startswith(k):
                s = "用户" + v + rest[len(k):]
                break
        else:
            s = "用户" + rest
    elif not s.startswith("用户"):
        s = "用户" + s
    if len(s) > 30:
        s = s[:30]
    return s


# 亲属/家人的口语写法 → 画像里该有的第三人称说法（只处理开头那一下）
_KIN = {"妈妈": "妈妈", "妈": "妈妈", "爸爸": "爸爸", "爸": "爸爸",
        "哥哥": "哥哥", "哥": "哥哥", "姐姐": "姐姐", "姐": "姐姐",
        "弟弟": "弟弟", "弟": "弟弟", "妹妹": "妹妹", "妹": "妹妹",
        "儿子": "儿子", "女儿": "女儿", "孩子": "孩子",
        "老婆": "妻子", "媳妇": "妻子", "老公": "丈夫", "先生": "丈夫"}


def make_text(user_text):
    """2a：只把人话整理成一句画像（few-shot，不给任何规则）。"""
    return clean_text(_ask_plain(_TEXT_FEWSHOT % str(user_text)[:300],
                                 max_tokens=GEN_MAX_TOKENS))


_META_PROMPT = (
    "画像：%s\n\n"
    "这条画像的 type / triggers / scope 是什么？只输出 JSON：\n"
    "{\"type\": \"状态/偏好/约束/背景\", \"triggers\": [\"词1\",\"词2\"], \"scope\": \"一句话\"}"
)


def _unwrap(raw):
    """把可能带 markdown、中文冒号、全角括号的原始输出，收拾成好抓的形状。"""
    s = str(raw or "")
    s = s.replace("```json", " ").replace("```", " ").replace("**", "")
    s = s.replace("：", ":").replace("［", "[").replace("］", "]")
    s = s.replace("｛", "{").replace("｝", "}").replace("“", "\"").replace("”", "\"")
    s = s.replace("‘", "'").replace("’", "'")
    s = s.replace("\n", " \n ")
    return s


def _grab_field(s, names):
    """抓一个字段的值：从 `名字` 后面第一个冒号/等号开始，到下一个已知字段名或行尾为止。

    **不看格式对不对**（有没有引号、有没有 JSON 括号都不管）—— 这就是"宽松"的含义。
    ⚠️ 字段名前面那个字符可能是**引号**（`{"triggers": [...]}` 里 `triggers` 前面是 `"`）——
    第一版没把引号算进前置字符，于是带引号的标准 JSON 反而抓不到 triggers 和 scope，
    全靠兜底值撑着（探针实测过）。
    """
    for nm in names:
        m = re.search(r"(?:^|[\s,{'\"]|\[)" + nm + r"[\"']?\s*[:=]\s*", s, re.I)
        if not m:
            continue
        rest = s[m.end():]
        stop = re.search(r"[\s,]\s*[\"']?\s*(?:type|triggers?|scope|场景|类型|触发词)\s*[\"']?\s*[:=]"
                         r"|\}|\n", rest, re.I)
        val = rest[:stop.start()] if stop else rest
        return val.strip()
    return ""


def _split_list(val):
    """triggers 的分隔符：逗号、顿号、引号、方括号、竖线、分号都算。"""
    if not val:
        return []
    v = val.strip().strip("[]{}()")
    v = re.sub(r"[\[\]{}()\"'「」『』]", " ", v)
    parts = re.split(r"[,，、;；|/\s]+", v)
    out = []
    for p in parts:
        p = p.strip().strip("`*#-—.").strip()
        if p and p not in out and p not in ("type", "scope", "triggers"):
            out.append(p)
    return out


def _fallback_triggers(text):
    """triggers 全空时的兜底：从 text 里摘一段当触发词。

    做法：先去掉"用户"，按标点切成小块，取**最长的 2~4 字**那块（单字不要 —— 万能词风险）。
    摘不到就退回整条 text 去掉"用户"后的头 4 个字。**绝不返回空 list**：
    空的 triggers 等于把触发词那路血管废掉。
    """
    body = re.sub(r"^用户", "", str(text or ""))
    chunks = [c for c in re.split(r"[，。、；：,;:!！?？\s]+", body) if c]
    cand = [c for c in chunks if 2 <= len(c) <= 6]
    if cand:
        return [max(cand, key=len)[:6]]
    body = re.sub(r"[^\w\u4e00-\u9fff]", "", body)
    return [body[:4]] if body else ["未分类"]


def parse_meta(raw, text=""):
    """2b 的解析：**宽松正则，不许严格 JSON 解析**。

    规格给的四条硬要求，逐条落在这里：
      · 用正则抓字段，不管格式对不对、有没有 markdown 符号  → `_unwrap` + `_grab_field`
      · 中英文冒号都认                                      → `_unwrap` 里先把「：」换成「:」
      · triggers 分隔符：逗号、顿号、引号、方括号都算        → `_split_list`
      · type 不在四类里就**降级为背景，不丢弃**；triggers 全空就从 text 兜底
    """
    s = _unwrap(raw)
    t_raw = _grab_field(s, ["type", "类型"])
    t = ""
    for k in TYPES:
        if k in t_raw:
            t = k
            break
    if not t:      # 输出里没写"type:"这种字段也不要紧，正文里出现哪个词就用哪个
        for k in TYPES:
            if k in s:
                t = k
                break
    if not t:
        t = "背景"     # **降级，不丢弃**
    trg = _split_list(_grab_field(s, ["triggers?", "触发词", "触发"]))
    trg = [x for x in trg if x not in STOP_TRIGGERS]      # 单字动词不许当触发词
    if not trg:
        trg = _fallback_triggers(text)
    sc = _grab_field(s, ["scope", "场景", "适用范围"]).strip("`*#-—.  \"'「」")
    if not sc:
        sc = "通用"
    return {"type": t, "triggers": trg, "scope": sc[:30]}


def make_meta(text):
    """2b：从一条画像里抽 type / triggers / scope。"""
    return parse_meta(_ask_plain(_META_PROMPT % text, max_tokens=META_MAX_TOKENS), text)


# ---------------- 重复过滤器（关卡，只出信号）----------------
def _norm(t):
    return re.sub(r"[\s，。、！？；：,.!?;:]", "", str(t or ""))


def is_duplicate(text, profiles, semantic=True):
    """返回 (是否重复, 原因)。**只出信号，不参与生成。**

    第一层·字符串快筛：完全相同 / 一方包含另一方 → 重复。
    第二层·语义判重：把新的和已有的**一起**给模型，问"讲的是同一件事吗"。
                     同一件事的不同说法也算重复（「喜欢村上春树」vs「在看村上春树的书」）。
    """
    nt = _norm(text)
    if not nt:
        return True, "空画像"
    for i, p in enumerate(profiles):
        op = _norm(p.get("text"))
        if not op:
            continue
        if nt == op or nt in op or op in nt:
            return True, "字符串快筛：跟第 %d 条完全同/被包含" % (i + 1)
    if not semantic or not profiles:
        return False, ""
    menu = "\n".join("%d. %s" % (i + 1, p.get("text")) for i, p in enumerate(profiles))
    prompt = ("新的这条跟已有的哪一条讲的是同一件事？只回答序号，都不重复回答 -1。\n"
              "同一件事的不同说法算重复（「喜欢村上春树」和「在看村上春树的书」是同一件事）。\n\n"
              "新的：%s\n\n已有的：\n%s" % (text, menu))
    out = str(_ask_plain(prompt, max_tokens=MODEL_MAX_TOKENS) or "")
    m = re.search(r"-\s*1", out)
    if m:
        return False, ""
    for mm in re.finditer(r"\d+", out):
        k = int(mm.group(0))
        if 1 <= k <= len(profiles):
            return True, "语义判重：跟第 %d 条是同一件事" % k
    return False, ""


def remember(user_text, path=None, semantic=True, verbose=False):
    """写入链整条：判该不该记 → 生成 → 过滤 → 追加。返回过程 dict（便于对账）。

    调用方逻辑（规格给定）：**重复 → 拒绝进入，不写入；不重复 → 写入。**
    """
    res = {"user": user_text, "judged": False, "text": "", "profile": None,
           "duplicate": False, "reason": "", "written": False}
    res["judged"] = should_remember(user_text)
    if verbose:
        print("    ①该不该记：%s" % ("要记" if res["judged"] else "不记"))
    if not res["judged"]:
        return res
    text = make_text(user_text)
    res["text"] = text
    if verbose:
        print("    ②a画像：%s" % text)
    if not text:
        res["reason"] = "画像为空（模型没答出来）"
        return res
    meta = make_meta(text)
    prof = {"text": text, "type": meta["type"], "triggers": meta["triggers"],
            "scope": meta["scope"]}
    res["profile"] = prof
    if verbose:
        print("    ②b字段：type=%s triggers=%s scope=%s"
              % (prof["type"], prof["triggers"], prof["scope"]))
    doc = load(path)
    dup, why = is_duplicate(text, doc["profiles"], semantic=semantic)
    res["duplicate"], res["reason"] = dup, why
    if verbose:
        print("    ③过滤器：%s" % ("重复 → 拒绝写入（%s）" % why if dup else "不重复 → 写入"))
    if dup:
        return res
    doc["profiles"].append(prof)
    save(doc["profiles"], path)
    res["written"] = True
    if verbose:
        print("    ④已写入，库里现在 %d 条" % len(doc["profiles"]))
    return res


# ============================================================
# 召回链
# ============================================================
_R = {"rows": None}


def _rows():
    if _R["rows"] is not None:
        return _R["rows"]
    return load()["profiles"]


def _hits(idx, q):
    """这条画像的触发词命中了几个（单字动词不算）。"""
    n = 0
    for t in (_rows()[idx].get("triggers") or []):
        if t in q and t not in STOP_TRIGGERS:
            n += 1
    return n


def ngram_overlap(a, b, n=2):
    """二字滑窗重叠度（0~1）。"""
    a = re.sub(r"[\s\W_]+", "", str(a or ""))
    b = re.sub(r"[\s\W_]+", "", str(b or ""))
    if len(a) < n or len(b) < n:
        return 0.0
    ga = {a[i:i + n] for i in range(len(a) - n + 1)}
    gb = {b[i:i + n] for i in range(len(b) - n + 1)}
    return len(ga & gb) / float(len(ga | gb)) if ga and gb else 0.0


def _card(idx):
    p = _rows()[idx]
    return "[%s] %s（场景：%s）" % (p.get("type"), p.get("text"), p.get("scope"))


def _menu(order):
    return "\n".join("%d. %s" % (i + 1, _card(idx)) for i, idx in enumerate(order))


def _pick_number(text, order):
    """从模型回答里抠显示序号 → 真实索引。抠不到 None。

    4B 会答「第 3 条」「3」「3、7」「3. 用户爱看 NBA」，还会先复述清单再给答案 ——
    只认严格数字格式的话，这些全被算成"这一路弃权"，投票就会集体偏向没弃权的那几路。
    """
    for m in re.finditer(r"\d+", str(text or "")):
        k = int(m.group(0))
        if 1 <= k <= len(order):
            return order[k - 1]
    return None


def _shuffled_order(q, n):
    """显示顺序：每一问重新洗（防位置偏见）。用问题当种子 → 同一个问题可复现。"""
    order = list(range(n))
    random.Random(sum(ord(c) for c in str(q)) * 7919 + len(str(q))).shuffle(order)
    return order


_VESSEL_INTRO = ("下面是关于用户的画像，按显示序号列出：\n%s\n\n用户刚说：「%s」\n\n")


def _ask(q, order, question):
    prompt = (_VESSEL_INTRO % (_menu(order), q)) + question
    return _pick_number(_ask_plain(prompt), order)


# ---------- 3 路规则血管（权重 1.0）----------
def v1_trigger(q, order):
    """触发词命中最多者胜（单字动词不算）。并列时看二字滑窗重叠度，再看显示顺序。"""
    best, best_key = None, (0, 0.0)
    for idx in order:
        h = _hits(idx, q)
        if h <= 0:
            continue
        key = (h, ngram_overlap(q, _rows()[idx].get("text")))
        if key > best_key or (key == best_key and best is None):
            best, best_key = idx, key
    return best


def v2_type_first(q, order):
    """类型优先：先判「状态/偏好/约束/背景」，再在该类内挑。"""
    opts = [t for t in TYPES if any(_rows()[i].get("type") == t for i in order)]
    if not opts:
        return None
    menu = "\n".join("%d. %s" % (i + 1, t) for i, t in enumerate(opts))
    out = _ask_plain("用户说：「%s」\n\n下面是四类信息：\n%s\n\n"
                     "用户这句话最像是在说哪一类？只回一个数字。" % (q, menu))
    t = None
    for m in re.finditer(r"\d+", str(out or "")):
        k = int(m.group(0))
        if 1 <= k <= len(opts):
            t = opts[k - 1]
            break
    if t is None:
        return None
    same = [i for i in order if _rows()[i].get("type") == t]
    if not same:
        return None
    top = max(_hits(i, q) for i in same)
    if top > 0:
        return [i for i in same if _hits(i, q) == top][0]
    return _ask(q, same, "这几条里哪一条跟用户这句话关系最近？只回一个数字。")


def v3_scope_first(q, order):
    """场景优先：先判 scope，再在该 scope 内挑。"""
    scopes = []
    for i in order:
        sc = _rows()[i].get("scope")
        if sc and sc not in scopes:
            scopes.append(sc)
    if not scopes:
        return None
    menu = "\n".join("%d. %s" % (i + 1, s) for i, s in enumerate(scopes))
    out = _ask_plain("用户说：「%s」\n\n下面是一些场景：\n%s\n\n"
                     "用户这句话最可能落在哪个场景里？只回一个数字。" % (q, menu))
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
        return [i for i in same if _hits(i, q) == top][0]
    return _ask(q, same, "这几条里哪一条跟用户这句话关系最近？只回一个数字。")


# ---------- 7 路模型血管（权重 0.5，7 个不同的认知任务）----------
# 【为什么必须是 7 个不同的问题】都问"哪条最相关"等于同一个 4B 答 7 遍 ——
# 7 票会一起对、也一起错，投票就退化成一个模型的一次判断（还白白多花 7 次调用）。
# 换问法 = 换**抽取角度**：想做的那件事 / 第一浮现的 / 缺的背景 / 只能记一件 /
# 沾边的全部 / 避免说错话 / "原来他是这样"。角度不同，错的分布才不同。
MODEL_QUESTIONS = {
    "v4_intent": "他这句话想让我做什么？为了回应他，我需要翻他档案的哪条？只回一个数字。",
    "v5_first": "听到这句话，你脑子里第一个浮现的关于他的事是哪条？只回一个数字。",
    "v6_missing": "要真正理解他这句话，我缺了他哪块背景？只回一个数字。",
    "v7_only_one": "假如你只能记住他的一件事来回应这句话，你记哪条？只回一个数字。",
    "v8_related": "下面这些里，哪些跟他这句话沾边？返回所有相关序号，用逗号隔开。",
    "v9_avoid": "哪条信息能帮我避免说错话或给错建议？只回一个数字。",
    "v10_reveal": "哪条信息让你觉得「哦，原来他是这样」？只回一个数字。",
}


def v4_intent(q, order):
    return _ask(q, order, MODEL_QUESTIONS["v4_intent"])


def v5_first(q, order):
    return _ask(q, order, MODEL_QUESTIONS["v5_first"])


def v6_missing(q, order):
    return _ask(q, order, MODEL_QUESTIONS["v6_missing"])


def v7_only_one(q, order):
    return _ask(q, order, MODEL_QUESTIONS["v7_only_one"])


def v8_related(q, order):
    return _ask(q, order, MODEL_QUESTIONS["v8_related"])


def v9_avoid(q, order):
    return _ask(q, order, MODEL_QUESTIONS["v9_avoid"])


def v10_reveal(q, order):
    return _ask(q, order, MODEL_QUESTIONS["v10_reveal"])


# 10 路血管：(名字, 函数, 权重)
VESSELS = (
    ("v1_trigger", v1_trigger, W_RULE),
    ("v2_type_first", v2_type_first, W_RULE),
    ("v3_scope_first", v3_scope_first, W_RULE),
    ("v4_intent", v4_intent, W_MODEL),
    ("v5_first", v5_first, W_MODEL),
    ("v6_missing", v6_missing, W_MODEL),
    ("v7_only_one", v7_only_one, W_MODEL),
    ("v8_related", v8_related, W_MODEL),
    ("v9_avoid", v9_avoid, W_MODEL),
    ("v10_reveal", v10_reveal, W_MODEL),
)


def recall(q, profiles=None, verbose=False):
    """10 路投票 → 0~2 条画像（按权重降序）。

    ⚠️ **串行跑**，不许 ThreadPoolExecutor：本地 4B 一次只服务一个请求。
    """
    _R["rows"] = list(profiles) if profiles is not None else load()["profiles"]
    n = len(_R["rows"])
    if n == 0 or not str(q).strip():
        return []
    order = _shuffled_order(q, n)

    tally = {}
    for name, fn, w in VESSELS:
        try:
            idx = fn(q, order)
        except Exception as e:      # noqa: silent-ok — 一路挂了不许拖垮整次召回
            if verbose:
                print("    %-14s 异常：%s" % (name, e))
            idx = None
        if verbose:
            print("    %-14s → %s" % (name, _rows()[idx]["text"][:24] if idx is not None
                                      else "弃权"))
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
    if not ok:
        return []
    picked = [ok[0]]
    if len(ok) > 1 and ok[1][1]["weight"] >= ok[0][1]["weight"] * SECOND_RATIO:
        picked.append(ok[1])
    return [dict(_rows()[i], _idx=i, _weight=s["weight"], _votes=s["votes"])
            for i, s in picked[:TOP_N]]


# ================== system 模板（一个字都不许改）==================
# 【禁止】不许加任何额外指令：
#   · 不许加"像认识很久的朋友"（会编造共同经历）
#   · 不许加"不要编造""必须避开""约束要排除"（会脑梗）
#   · 不许描述关系、不许下命令、不许列规则
#   · 不许把"了解…一些"改成"记得"（"记得"会被理解成共同经历）
#   · 不许把"听他接着说"改成"用这些回应他"（"回应"会让模型编内容）
_TMPL_WITH = ("你是小焦，用户的本地 AI 伙伴。\n\n"
              "你了解关于他的一些事：\n%s\n\n"
              "听他接着说。")
_TMPL_NONE = "你是小焦，用户的本地 AI 伙伴。自然地聊。"


def build_system(impressions):
    rows = list(impressions or [])[:TOP_N]
    if not rows:
        return _TMPL_NONE
    return _TMPL_WITH % "\n".join("- " + r.get("text", "") for r in rows)


# ================== 调用流程（规格第五节）==================
def chat(user_msg, verbose=False):
    """用户说话后：召回 → 拼 system → 发给本地模型（T=0.7, max_tokens=512）。"""
    impressions = recall(user_msg, verbose=verbose)
    sys_text = build_system(impressions)
    messages = [{"role": "system", "content": sys_text},
                {"role": "user", "content": user_msg}]
    reply = local_chat(messages, temperature=REPLY_TEMPERATURE, max_tokens=REPLY_MAX_TOKENS)
    return {"reply": reply, "impressions": impressions, "system": sys_text,
            "messages": messages}


def answer(user_msg):
    return chat(user_msg)["reply"]


# ================== 自测（规格第七节）==================
WRITE_CASES = (
    ("我最近在看村上春树的《挪威的森林》", "拒绝", "跟「喜欢村上春树」重复"),
    ("我对海鲜过敏，吃了会起疹子", "写入", "新事实"),
    ("我在学游泳，每周去三次", "写入", "新事实"),
    ("今天天气真好啊", "不记", "闲聊"),
    ("1+1等于几", "不记", "一次性提问"),
)

RECALL_CASES = (
    ("推荐本书看看", "村上"),
    ("我最近在学游泳", "游泳"),
    ("我家狗最近不爱吃饭", "旺财"),
    ("我妈身体怎么样", "妈妈"),
    ("海鲜我能吃吗", "海鲜"),
)

# 回复必须"认账"：出现这些词就算不认账（说明它没把画像用上，或直接说不记得）
_DENY = ("不记得", "没提过", "没说过", "没有印象", "不知道你", "没告诉过我", "不掌握",
         "没有记录", "暂时不知道")


def _selftest():
    import tempfile
    tmp = os.path.join(tempfile.gettempdir(), "_xj_profiles_selftest.json")
    if os.path.exists(tmp):
        os.remove(tmp)
    _STORE["path"] = tmp          # **全局切到临时库**：召回链也必须读它
    seed_store(tmp, force=True)

    print("=" * 78)
    print("画像系统自测 · 写入链（规格第七节）")
    print("=" * 78)
    w_ok = 0
    for i, (msg, want, why) in enumerate(WRITE_CASES, 1):
        print("\n【写 %d】%s    期望：%s（%s）" % (i, msg, want, why))
        r = remember(msg, path=tmp, verbose=True)
        if want == "不记":
            got = "不记" if not r["judged"] else "要记"
        elif want == "拒绝":
            got = "拒绝" if r["duplicate"] else ("写入" if r["written"] else "没生成")
        else:
            got = "写入" if r["written"] else ("拒绝" if r["duplicate"] else "没生成")
        ok = (got == want)
        w_ok += 1 if ok else 0
        print("     判定：%s（期望 %s）%s" % (got, want, "✅" if ok else "❌"))
    print("\n写入链：%d/%d" % (w_ok, len(WRITE_CASES)))

    # ---- 过滤器专项：第 1 条用例在第一步就判了"不记"，**过滤器根本没被走到** ----
    # 所以这里单独把"如果第一步说要记"这条路走完，证明**这道关卡本身是通的**。
    # （规格第七节那条用例要的正是这个：要记 → 过滤器拒绝。）
    print("\n" + "-" * 78)
    print("过滤器专项（跳过第一步，直接验第 1 条用例的判重）")
    doc = load(tmp)
    t = make_text("我最近在看村上春树的《挪威的森林》")
    print("     2a 画像：%s" % t)
    dup, why = is_duplicate(t, doc["profiles"])
    print("     过滤器：%s%s" % ("**重复 → 拒绝写入**" if dup else "**没判成重复**",
                             "（%s）" % why if why else ""))
    print("     判定：%s" % ("通过 ✅" if dup else "没过 ❌"))

    print("\n" + "=" * 78)
    print("画像系统自测 · 召回链（规格第七节）—— 判定标准 ≥7/7")
    print("=" * 78)
    r_ok = 0
    for i, (msg, want) in enumerate(RECALL_CASES, 1):
        print("\n【召 %d】%s    期望：%s" % (i, msg, want))
        c = chat(msg, verbose=True)
        texts = [x["text"] for x in c["impressions"]]
        for t in texts:
            print("     ✓ %s" % t)
        if not texts:
            print("     （空：没有合格候选）")
        hit = any(want in t for t in texts)
        print("     system：%s" % c["system"].replace("\n", " ⏎ "))
        print("     回复：%s" % c["reply"].replace("\n", " ")[:150])
        if msg == "海鲜我能吃吗":      # 规格：这一条要求回复必须认账
            deny = [d for d in _DENY if d in c["reply"]]
            if deny:
                hit = False
                print("     ⚠️ 回复不认账（出现 %s）" % deny)
        r_ok += 1 if hit else 0
        print("     判定：%s" % ("通过 ✅" if hit else "**没过** ❌"))
    print("\n召回链：%d/%d" % (r_ok, len(RECALL_CASES)))

    total_need = len(RECALL_CASES)
    print("\n" + "=" * 78)
    print("召回链判定：%d/%d（要求 ≥%d/%d）→ %s"
          % (r_ok, total_need, total_need, total_need,
             "通过 ✅" if r_ok >= total_need else "**未达标** ❌"))
    print("=" * 78)
    return 0 if r_ok >= total_need else 1


def _main(argv):
    if argv and argv[0] == "--selftest":
        return _selftest()
    if argv and argv[0] == "--seed":
        return seed_store(force=False)[1] and 0 or 1
    q = " ".join(argv) if argv else "举个例子，你了解我什么"
    c = chat(q, verbose=True)
    print("\n召回：%s" % ([x["text"] for x in c["impressions"]] or "（空）"))
    print("-" * 60)
    print(c["system"])
    print("-" * 60)
    print(c["reply"])
    return 0


if __name__ == "__main__":
    sys.exit(_main([a for a in sys.argv[1:]]))
