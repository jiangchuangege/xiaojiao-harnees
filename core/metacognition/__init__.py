# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 元认知（自评 / 交叉检查 / 能力边界档案）

【这一层解决什么问题】
    别的层解决的是"怎么答得又多又好"，这一层解决的是"它到底知不知道自己几斤几两"。
    模型有一个天生的毛病：**它对任何问题都用同一个自信的语气回答**。
    "北京是中国的首都"和"你昨天说过的那个车牌号"在它嘴里听起来一样确定 ——
    而后者它其实是在编。载体层唯一能拦住这件事的办法，就是**让它在开口前先自评**，
    在开口后**再换个角度问自己一遍**，并把结果**攒成一本账**。

【三个器官（每个器官缺了都会漏掉一类事故）】
    selfrate.py   答前自评：让模型给自己的把握打 A/B/C 三档 → 载体据此决定直接答 / 带标注答 / 去走工具。
                  没有它 → 模型对"它根本不知道的事"也用同样的语气编，载体手里没有任何依据可以拦。
    crosscheck.py 答后交叉检查：同一个问题从 2~3 个角度各答一遍，载体比对答案的一致性。
                  没有它 → 前后自相矛盾的两个答案原样交给用户。这是最伤信任的失败，
                  比"我不知道"严重得多（"不知道"只是能力问题，"自相矛盾"让人怀疑整个系统）。
    boundary.py   边界档案：把"哪类问题它老没把握、哪类问题它自评有把握却答错"落盘成可查的账。
                  没有它 → 同一个坑一遍遍踩：上个月在这类问题上答错过，这个月还是同一个姿势答错，
                  而且因为没人记账，谁都不知道它错过。

【三条贯穿全层的取向（三个模块都按这个来，谁都不许破例）】
    ① **宁严不宽**：拿不准一律倒向更稳的那条路 —— 解析不出档位按 "?" 处理（走工具），
       一致性落在 0.3~0.6 的中间地带按"矛盾"处理（重答并标注），而不是按"大概没事"处理。
       为什么：把"不确定"说成"确定"的代价是**编造**（用户拿去用了）；
       把"确定"说成"不确定"的代价只是**多确认一次**。两个代价不对等，所以一律倒向后者。
    ② **绝不猜**：解析不到就如实返回 "?"，只有一个样本就说 unknown。
       绝不允许"因为没有反例所以算一致"这种自欺 —— 那等于把闸门关上了还宣称门是好的。
    ③ **不认模型**：`llm_fn` 一律由调用方注入，传 None 就如实返回"没有可用的模型"，**绝不抛错**。
       去掉这条：离线自测跑不起来（要真拉一个 4B 模型才能在 CI 里验），
       而换火种时这一层就会跟着火种一起改 —— 那就不是载体了。

【为什么 __init__ 里放这几个小工具（而不是三个模块各写一份）】
    三个模块都要做同样几件事：拿落盘目录、追加一行 JSONL、读回来、惰性拿 app、记一行日志。
    各写一份的结果是"三份略有差异的实现"，早晚出现"自评认 logs/metacognition、
    档案写进 logs/health"这种灵异现象（记录看着存在，只是存在别的地方）。
    放这里统一；去掉它就等于把目录语义撕成三份。

【数据落盘一律在 logs/metacognition/ 下】（logs/ 已被 .gitignore 忽略，不脏仓库）
    boundary.jsonl   能力边界档案（一条自评样本一行，append-only）

【为什么这里**不**在文件顶部 import 三个子模块】
    三个子模块都要 `from . import ...` 拿本文件里的工具（目录、append_jsonl），
    本文件若在 import 期反过来把它们拉进来就成了循环 import：
    单独 `import core.metacognition.selfrate` 会直接 ImportError。
    所以改用 PEP 562 的模块级 `__getattr__`：**用到才 import**。
    去掉它：`import core.metacognition as MC; MC.self_rate(...)` 这种顺手写法报 AttributeError，
    而 `from core.metacognition.selfrate import self_rate` 仍然正常。
"""
import json
import os
import re
import sys
import time

# 仓库根：core/metacognition/__init__.py → 上溯三级。
# 为什么要自己算一次而不是 import 主程序的常量：这一层必须能在**主程序没起来**时独立跑
# （离线自测就是这样），所以路径只能自己推。上溯级数一旦写错，档案就落到仓库外面去了。
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_CONTROL_FILE = os.path.join(_REPO_ROOT, "xiaojiao_control.json")
_META_DIR = os.path.join(_REPO_ROOT, "logs", "metacognition")

# 复用健康系统的 JSONL 读写（**不重复造一份**）：
# 为什么必须复用：读 JSONL 那些容错（半截行跳过、days 过滤、ts 坏掉时的取舍）
# 是踩过坑才写成那样的；这里再抄一份的结果是"两份容错略有差异"，
# 于是会出现"档案里明明有这条、分析时却看不见"。去掉复用就等于制造这个差异。
from ..health import append_jsonl, read_jsonl, read_json, write_json      # noqa: F401,E402

# metacognition 段的默认值。为什么默认全是"开"：
# 这一层做的全是**本地判断**（打分、算 2-gram、查自己写的小档案），
# 不联网、不额外调模型（自评那一次调用是调用方本来就有的那一轮），代价可以忽略；
# 关掉它省不下什么，却会让模型对"它不知道的事"继续用确定的语气编。
_DEFAULT_METACOGNITION = {
    "enabled": True,
    "self_rate": True,        # 答前自评
    "cross_check": True,      # 答后交叉检查
    "cross_check_n": 3,       # 交叉检查用几个角度（≥2 才有意义）
    "min_samples": 3,         # 判"这类问题我老不行"的最少历史样本数
    "days": 30,               # 档案默认回看窗口（天）
}


def meta_dir(sub=None):
    """元认知数据目录（默认 `logs/metacognition/`）；建不出来也不抛。

    为什么集中在这里算路径：三个模块各用 `os.path.dirname(__file__)` 拼一次的话，
    早晚有人拼错一级，档案就散到仓库别处去了 —— 排查时你以为"没记录"，
    其实记录在另一个目录里。去掉它就会这样（`core/health` 的目录函数同款理由）。
    """
    d = _META_DIR if not sub else os.path.join(_META_DIR, sub)
    try:
        os.makedirs(os.path.dirname(d) if os.path.splitext(d)[1] else d, exist_ok=True)
    except Exception:      # noqa: silent-ok — 目录建不出来时各写入点自己还会再兜一层
        pass
    return d


def cfg(override=None):
    """元认知配置：代码默认值 ← `xiaojiao_control.json` 的 `metacognition` 段 ← 显式 override。

    为什么读操控文件而不是写死：判"这类问题我老不行"要看几条样本、交叉检查用几个角度，
    这些是要按机器和模型调的；调阈值不该改代码。
    为什么**绝不抛错**：用户手改 JSON 少个逗号，不能让整个元认知层（乃至对话）起不来。
    去掉容错会怎样：一次手抖 → `import core.metacognition` 失败 → 小焦起不来。
    """
    merged = dict(_DEFAULT_METACOGNITION)
    try:
        with open(_CONTROL_FILE, "r", encoding="utf-8", errors="replace") as f:
            raw = json.load(f) or {}
        if isinstance(raw, dict) and isinstance(raw.get("metacognition"), dict):
            merged.update(raw["metacognition"])
    except Exception:      # noqa: silent-ok — 读不到/写坏了就用默认值
        pass
    if isinstance(override, dict):
        merged.update(override)
    return merged


def log_line(name, msg):
    """往 `logs/metacognition/<name>.log` 追加一行（人肉排查"它到底判了什么"）。

    为什么单独留一个人读的日志（而不是只看 JSONL）：档案里存的是**结论**，
    而排查问题时最想知道的是"当时为什么这么判"（哪个角度没答上来、一致性是多少）。
    结论可以重算，过程重算不了。去掉它：出事时只能看到一行行结论，看不见原因。
    """
    p = os.path.join(_META_DIR, "%s.log" % name)
    try:
        os.makedirs(_META_DIR, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:      # noqa: silent-ok — 写不上日志不影响功能
        pass


# ------------------------------------------------------------------ 共享的中文 2-gram 特征
# 中文虚词单字：**只有当一个 2-gram 的两个字都是虚词时才丢掉它**。
# 为什么必须滤：不滤的话"我的""是不""这个"这类片段会让任何两段中文都"看着像"，
# 一致性比对的分母被灌水，真假答案的相似度全被抬到 0.6 以上（闸门直接失效）。
# 为什么只丢"两字全虚"的：只要有一个实义字就有信息量（"记忆""怎么"要分开看），
# 一律按单字滤会把实词也削掉（"的记"这种跨词片段反而有用）。
_STOP_CHARS = set("的了是我你他她它们在有和与也就都还不没很呢吧啊呀哦这那什么怎么请"
                  "问一下帮我个说记之前跟曾经经过于把被给对于从到会要能可能很想第")

# 为什么这两个特征函数放在 __init__ 而不是各模块一份（**这是有实际教训的形状**）：
# 一致性比对（crosscheck）和话题粗聚（boundary）都要算同一套 2-gram 特征。
# 各写一份的必然结果是两边清洗规则慢慢漂移（一边剔了标点、一边忘了剔），
# 于是"同一个问题"在一边算同类、在另一边算不同类 —— 这种不一致**不会报错**，
# 只会让"该走工具"的判断悄悄变成"直接硬答"。所以统一放这里。


def clean_text(text):
    """清洗：剔掉标点、空白、下划线，只留中英文与数字。

    为什么必须先清洗再切 2-gram：不清洗就会切出"好。今"这种**跨标点**的假片段，
    而两段话的标点习惯不一样时（一段用"，"、一段用"、"），假片段的比例也跟着变，
    相似度就随标点习惯漂移，而不是随内容漂移。去掉它：一致性比对变成"标点比对"。
    """
    s = "" if text is None else str(text)
    return re.sub(r"[^\w]|_", "", s, flags=re.UNICODE)


def bigrams(text):
    """按出现顺序返回清洗后的 2-gram 列表（**含重复**，已滤掉纯虚词片段）。

    为什么保留顺序和重复：话题粗聚要的是"这段话里第一个有实义的双字词"
    （中文问题的话题词通常在句首），这是**位置信息**，用集合存下来就没了。
    """
    t = clean_text(text)
    out = []
    for i in range(len(t) - 1):
        bg = t[i:i + 2]
        if bg[0] in _STOP_CHARS and bg[1] in _STOP_CHARS:
            continue
        out.append(bg)
    if not out and len(t) == 1 and t not in _STOP_CHARS:
        out.append(t)          # 单字（"谁"）：留着，否则短问题会被当成"没有任何实义内容"
    return out


def features(text):
    """2-gram 特征**集合**（给一致性比对用；这里顺序没有意义、重复也没有意义）。"""
    return set(bigrams(text))


def app_module():
    """惰性拿 `xiaojiao_app` 模块；拿不到返回 None（**绝不抛错、也绝不主动 import**）。

    这是整个载体层"能独立跑"的关键手法（`core/health`、`core/autonomy` 同款）：
    正常起法就是 `import xiaojiao_app`，所以"应用在跑"等价于"它在 sys.modules 里"。

    【为什么不直接复用 core/health.app_module（它已经写好了）】
    health 那一份带一个"允许主动 import"的开关（环境变量 XIAOJIAO_HEALTH_IMPORT_APP=1）,
    而 `import xiaojiao_app` 会连带加载小脑模型、视频/播客服务，本机实测 2.63s。
    元认知在**对话热路径**上被调用（每轮都要自评一次），一旦有人设了那个环境变量，
    每轮对话都会把整个应用再初始化一遍 —— 这里只认已经在内存里的那份，不给这个口子。
    去掉这个独立实现：一个为健康系统准备的环境变量会拖慢元认知的每一次调用。
    """
    try:
        m = sys.modules.get("xiaojiao_app")
        if m is not None:
            return m
        # 以 `python xiaojiao_app.py` 方式跑时应用叫 __main__，且必须确认它真是应用本体
        # （__main__ 也可能是任意一个脚本，比如自测脚本 —— 不能认错人）。
        m = sys.modules.get("__main__")
        if m is not None and hasattr(m, "agent_run"):
            return m
    except Exception:      # noqa: silent-ok — 拿不到 app 是合法情形（离线自测就是这样）
        return None
    return None


# 顶层名字 → (子模块名, 属性名)。为什么列这张表而不是只放子模块：
# 宿主接线的写法是 `from core.metacognition import self_rate`（跟 core.health 一个风格），
# 少写一段 `from ...selfrate import`；表里没列的名字一律 AttributeError（不许瞎猜一个出来）。
_LAZY = {
    "self_rate": ("selfrate", "self_rate"),
    "rate_prompt": ("selfrate", "rate_prompt"),
    "parse_rating": ("selfrate", "parse_rating"),
    "route": ("selfrate", "route"),
    "cross_check": ("crosscheck", "cross_check"),
    "angles": ("crosscheck", "angles"),
    "similarity": ("crosscheck", "similarity"),
    "prefer": ("crosscheck", "prefer"),
    "record": ("boundary", "record"),
    "stats": ("boundary", "stats"),
    "should_use_tool": ("boundary", "should_use_tool"),
    "summary": ("boundary", "summary"),
}

__all__ = ["selfrate", "crosscheck", "boundary",
           "meta_dir", "cfg", "log_line", "app_module",
           "clean_text", "bigrams", "features",
           "append_jsonl", "read_jsonl", "read_json", "write_json",
           "self_rate", "rate_prompt", "parse_rating", "route",
           "cross_check", "angles", "similarity", "prefer",
           "record", "stats", "should_use_tool", "summary"]


def __getattr__(name):
    """按需 import 子模块 / 取子模块里的函数（PEP 562），**不引入 import 环**。

    只有被真正取用时才 import；`__all__` 里的名字全部覆盖。
    去掉它：`MC.self_rate(...)` 报 AttributeError（得写全 `core.metacognition.selfrate.self_rate`）。
    """
    if name in ("selfrate", "crosscheck", "boundary"):
        import importlib
        return importlib.import_module("." + name, __name__)
    hit = _LAZY.get(name)
    if hit is not None:
        import importlib
        mod = importlib.import_module("." + hit[0], __name__)
        return getattr(mod, hit[1])
    raise AttributeError("module %r has no attribute %r" % (__name__, name))
