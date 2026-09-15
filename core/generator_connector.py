# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 通用连接器（生成类功能的统一入口）

【这段为什么这么设计】
    小焦有五个"能出东西"的能力：视频、播客、音乐、博客、代码。
    它们各自有模块、各自的参数、各自的产物格式。用户**不应该**先学会"该点哪个界面" ——
    用户只说"我想做个视频"，剩下的事由载体自己走完：

        识别意图 → 自己问参数 → 调模块的提示词优化 → 内化映射 → 调生成 → 等产物 → 交回用户

    用户全程只跟小焦说话，**不需要点任何 UI 模块**。各模块的界面是给用户手动用的备选，
    不是必需路径。

【最关键的一条红线：五类绝不串】
    "做个视频"绝不能走到音乐模块去。这不是"体验不好"，而是**产物形态完全不同**：
    用户等了三分钟拿到一段音频，这比直接失败还糟 —— 他连"为什么不对"都不知道。
    所以：
      · 命中**一个**类别 → 就走那个，绝不"参考"别的类别；
      · 命中**多个**类别 → **反问**"你是想做 X 还是 Y"，让用户定，载体不猜；
      · 一个都没命中 → 退回通用对话（不硬套某个生成器）。

【内化的是"提示词映射"，不是产物】
    用户说"一只猫在沙滩上散步" → 模块把它精炼成一段专业提示词。
    下次同类输入可以直接复用这条映射，**省掉一次精炼调用**。
    但**绝不内化生成的视频/音频本身** —— 那是产物、体积大、而且每次生成都不一样，
    存下来既没用也污染记忆。

【配置原则：不复杂，用户自己可加】
    `xiaojiao_control.json` 里一段 `generators` 就够了：类别 → 关键词表。
    加的类别如果协议一致（关键词 + 一个工具名），不用改代码。
"""
import json
import os
import re
import threading
import time

__all__ = ["KINDS", "load_config", "detect", "route", "ask_params", "plan",
           "remember_mapping", "recall_mapping", "stats", "config_path"]

KINDS = ("video", "podcast", "music", "blog", "code")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOCK = threading.Lock()

# 默认关键词表。用户在 `xiaojiao_control.json` 里写了 `generators` 就以用户那份为准
# （**整体替换**而不是合并：合并会让人删不掉一个词，改起来很别扭）。
DEFAULT_KEYWORDS = {
    "video": ["视频", "短片", "动画", "影片", "生成个视频", "做个视频", "video", "嘴巴动"],
    "podcast": ["播客", "音频节目", "电台", "podcast", "做一期节目"],
    "music": ["音乐", "bgm", "曲子", "配乐", "来段歌", "music", "背景音乐"],
    "blog": ["博客", "文章", "长文", "写一篇", "公众号", "blog"],
    "code": ["代码", "函数", "脚本", "写个程序", "实现一个", "写段代码", "code"],
}

# 类别 → 该类别要调的**生成工具名**。这是"绝不串"最后一道保险：
# 执行时按这张表取工具，取不到就如实说"这个能力当前不可用"，**不会退而求其次去调别的类别**。
KIND_TOOL = {
    "video": "generate_video",
    "podcast": "",          # 播客走服务路由（/api/podcast），没有工具名
    "music": "generate_music",
    "blog": "",             # 博客/长文走 continuation（输出无限）
    "code": "",             # 代码走代码治病链
}

# 参数问法：识别出类别后由载体自己问用户要参数，不用 UI、不用表单
PARAM_ASK = {
    "video": "你想做什么视频？说说画面内容就行（比如「一只猫在沙滩上散步」）。",
    "podcast": "想做一期什么主题的播客？给我一个题目或几句话。",
    "music": "想要什么风格的音乐？可以说风格、情绪、场景，也可以指定时长（默认 5 秒）。",
    "blog": "想写什么主题的文章？给我题目或要点，我来扩写成文。",
    "code": "想让我写什么代码？说清楚要做什么、输入输出是什么。",
}


def config_path():
    """控制文件路径（与主程序同源：仓库根下的 `xiaojiao_control.json`）。"""
    return os.path.join(_ROOT, "xiaojiao_control.json")


def load_config(path=None):
    """读 `generators` 配置。读不到/格式不对就用内置默认表，**不报错**。

    返回 `{"keywords": {类别: [词...]}, "source": "配置"/"默认"}`。
    """
    p = path or config_path()
    kw = {k: list(v) for k, v in DEFAULT_KEYWORDS.items()}
    src = "默认"
    try:
        if os.path.exists(p):
            with open(p, encoding="utf-8", errors="replace") as f:
                cfg = json.load(f) or {}
            g = cfg.get("generators")
            if isinstance(g, dict) and g:
                # 【两条过滤，都是实测踩出来的】
                #   ① `_` 开头的键是**注释**（JSON 没有注释语法，这是社区通行做法）：
                #      不过滤的话 `_说明` 会被当成一个类别，用户说"做个视频配点音乐"时
                #      反问会变成"你是想做_说明，还是视频，还是音乐？"。
                #   ② **值必须是列表**：配置里写了一个字符串时，`for w in "abc"` 会逐**字符**遍历
                #      —— 实测 `_说明` 的 95 个字变成了 95 个"关键词"。
                clean = {}
                for k, v in g.items():
                    if str(k).startswith("_") or not isinstance(v, list):
                        continue
                    clean[str(k)] = [str(w) for w in v if str(w).strip()]
                if clean:
                    kw = clean
                    src = "配置"
    except Exception:      # noqa: silent-ok — 配置坏了就用默认表，绝不能因为读配置失败就不工作
        pass
    return {"keywords": kw, "source": src}


def detect(text, keywords=None):
    """这句命中了**哪几类**生成功能。返回类别列表（可能为空、可能多个）。

    **返回列表而不是单个类别**是有意的：命中多个时必须由用户来定，
    载体不能自己挑一个 —— 那正是"串"的来源。
    """
    t = str(text or "").lower().strip()
    if not t:
        return []
    kw = keywords if keywords is not None else load_config()["keywords"]
    hits = []
    for kind, words in kw.items():
        for w in (words or []):
            w = str(w).lower().strip()
            if w and w in t:
                hits.append(kind)
                break
    # 保持稳定顺序（配置顺序），便于复现与测试
    return [k for k in kw.keys() if k in hits]


def route(text, keywords=None):
    """把一句话路由到**一个**类别。返回：

        {"kind": 类别或 "", "ambiguous": [...], "ask": 反问话术, "why": 理由}

    · 命中一个 → kind 有值，可以直接往下走；
    · 命中多个 → kind 为空、ambiguous 列出候选、ask 是对用户的问句；
    · 一个都没命中 → kind 为空、ambiguous 为空（**通用对话**，不硬套生成器）。

    `why` 是要写进日志给人看的，所以如实说明是"命中了一个"还是"命中多个要用户定"。
    """
    hits = detect(text, keywords=keywords)
    if not hits:
        return {"kind": "", "ambiguous": [], "ask": "",
                "why": "五个类别一个都没命中 → 按通用对话处理（不硬套生成器）"}
    if len(hits) == 1:
        return {"kind": hits[0], "ambiguous": [], "ask": "",
                "why": "命中一个类别：%s" % hits[0]}
    names = {"video": "视频", "podcast": "播客", "music": "音乐", "blog": "文章", "code": "代码"}
    cn = [names.get(h, h) for h in hits]
    ask = "你是想做%s？" % "，还是".join(cn)
    return {"kind": "", "ambiguous": hits, "ask": ask,
            "why": "同时命中 %s —— 五类绝不串，由用户指定，载体不猜" % "、".join(cn)}


def ask_params(kind):
    """识别出类别后要问用户的参数。返回一句问话（未知类别返回空串）。"""
    return PARAM_ASK.get(str(kind or ""), "")


def plan(kind, user_input, keywords=None):
    """给出这一类别的**完整执行计划**（不执行，只描述每一步）。

    【为什么要有个"计划"这一步】用户规格要的是"小焦自己走完整条链路"。
    把链路显式列出来，一是日志里能看到它到底走到哪一步、卡在哪，
    二是自测可以断言"这条路**没有**顺手去调别的类别的工具"——那道红线才可验证。
    """
    k = str(kind or "")
    tool = KIND_TOOL.get(k, "")
    steps = [
        {"n": 1, "do": "识别意图", "detail": "命中类别 %s" % k},
        {"n": 2, "do": "问参数", "detail": ask_params(k) or "（该类别无需额外参数）"},
        {"n": 3, "do": "调模块接口做提示词优化", "detail": "复用该模块**自己的**精炼接口，不另造一套"},
        {"n": 4, "do": "内化映射", "detail": "把「用户原始输入 → 优化后提示词」写进精神记忆库的 method.jsonl"},
        {"n": 5, "do": "调生成接口", "detail": ("工具 `%s`" % tool) if tool else "该类别走自己的服务链（无工具名）"},
        {"n": 6, "do": "等生成", "detail": "阻塞等产物；期间不切到别的类别"},
        {"n": 7, "do": "交回用户", "detail": "把产物链接/文本直接给用户；用户全程不需要点任何 UI"},
    ]
    return {"kind": k, "tool": tool, "steps": steps,
            "input": str(user_input or "")[:200]}


def remember_mapping(kind, original, refined, source="连接器自动内化"):
    """内化"用户原始输入 → 优化后提示词"的映射。

    **内化的是提示词映射，不是生成的产物本身**（见模块头说明）。
    走 `core.spirit_memory.remember()`，所以同样受它的护栏约束：
    超长 / 问答对结构 / 带 answer 字段一律拒收 —— 提示词映射天然是短句，不会被误伤。

    落点是 `logs/spirit_memory/method.jsonl`。
    """
    o = str(original or "").strip()
    r = str(refined or "").strip()
    if not o or not r or o == r:
        # 没优化（模块直接用了原词）就不记：记了等于凭空多一条"映射到自己"的噪音
        return {"ok": False, "action": "skipped", "why": "没有实际优化（原文与优化后相同）"}
    try:
        from core import spirit_memory as SM
        text = "做%s时，把「%s」精炼为「%s」" % (
            {"video": "视频", "podcast": "播客", "music": "音乐", "blog": "文章", "code": "代码"}.get(
                str(kind), str(kind)),
            o[:60], r[:120])
        return SM.remember("method", text, tags=["生成器", str(kind)], source=source)
    except Exception as e:      # noqa: silent-ok — 内化失败只影响"下次省一次调用"
        return {"ok": False, "action": "error", "why": "%s: %s" % (type(e).__name__, e)}


def recall_mapping(kind, user_input, min_sim=0.6):
    """找一条以前内化过的提示词映射（命中就不用再精炼一次）。

    返回 `{"text": 提示词, "sim": 相似度}` 或 None。
    阈值沿用精神记忆库的 0.6：低于它不算同一件事，免得把别的题材的提示词套过来。
    """
    try:
        from core import spirit_memory as SM
        hits = SM.recall(str(user_input or ""), k=3, kind="method", min_sim=min_sim)
    except Exception:      # noqa: silent-ok — 取不到就照常走精炼
        return None
    for h in hits or []:
        if str(kind) in (h.get("tags") or []):
            return {"text": h.get("text") or "", "sim": h.get("sim")}
    return None


def stats():
    """连接器自检信息：用了几类、关键词来自配置还是默认、每类多少个词。"""
    cfg = load_config()
    kw = cfg["keywords"]
    return {"source": cfg["source"], "kinds": sorted(kw.keys()),
            "counts": {k: len(v) for k, v in kw.items()},
            "tools": dict(KIND_TOOL), "path": config_path()}
