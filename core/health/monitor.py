# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 健康系统 · 监测层（无限 8：它不生病 —— 第一步：知道自己病了）

【为什么模型也需要"症状表"】
    人一不舒服会说"我头疼、我恶心"。模型不会说 —— 它只会**继续吐字**。
    所以载体必须自己长出一双眼睛：从**输出文本 / 工具轨迹 / 资源读数**里
    读出"它现在不对劲"。这就是 18 类症状存在的理由。

【为什么是"症状"而不是"错误"】
    这是本层最重要的一条认知：模型退化**不是 bug**，是**病**。
    bug 的逻辑是"定位 → 修好 → 永不复发"；病的逻辑是"发现 → 缓解 → 记病历 → 防复发"。
    退化会反复出现（同一个火种、同一种上下文长度，就容易反复犯同一种病），
    所以我们要的是"每次都能压下去、并且越压越少"，而不是"找到那个 bug 改掉它"。
    去掉"症状"这个抽象、改成"报错"：就只能处理崩溃，处理不了复读、答非所问这种
    "程序没崩但人已经没法用"的状态 —— 而那恰恰是 4B 模型最常出的问题。

【五组 18 类（为什么要凑到 18，而不是只做复读）】
    只做复读只能救下 Bug 3 一个现象；实测里"模型生病"有五种完全不同的样子：
      语言 language(4)  repeat 复读 / garbled 乱码 / broken_sentence 断句 / pace_shift 语速突变
      逻辑 logic(4)     self_contradiction 自相矛盾 / off_topic 答非所问
                        / logic_gap 逻辑跳步 / fact_reversal 事实反转
      情绪 emotion(3)   sudden_anger 突然暴躁 / sudden_negativity 突然消极
                        / emotion_swing 情绪失控
      行为 behavior(4)  tool_misuse 工具乱调 / tool_skipped 工具不调
                        / refusal 拒绝服务 / infinite_loop 无限循环
      生理 physio(3)    timeout 响应超时 / vram_alert 显存告警 / memory_growth 内存增长
    为什么"生理"也算症状：显存吃满、内存持续涨、响应超时**不是文本问题**，
    但它们是同一件事的因 —— 资源不够 → 算不准 → 复读/幻觉/暴躁一起冒出来。
    只看文本，会一直在治果；把资源症状并行监测，才能判因到"资源"上（见 diagnose.py）。

【为什么"宁可漏判，绝不误报"（本模块唯一的价值观）】
    误报的代价是**不可逆**的：把一段正常回答判成乱码/断句去"治"，用户拿到的
    就是一段被砍过的残缺回答（甚至被清掉上下文、被切走火种）；漏判的代价只是
    "这次没管上"，下一轮还会再判一次。两边的代价完全不对等。
    所以本模块的阈值一律往"几乎不会误伤正常文本"的方向调，宁可弱：
      · 每一类判据都写清"判据说明"，弱信号在 detail 里**明确写"弱信号"**；
      · 拿不准的（比如"不存在的工具"）宁可不判 —— 不知道工具表就不判；
      · 每个判据独立 try/except：一个判据写错，绝不能让整轮检查抛异常。
    去掉这个价值观（把阈值调紧好"多抓几个"）会怎样：用户正常的长回答被反复截断，
    健康系统自己成了最大的故障源 —— 这比模型退化更糟。

【为什么 check() 永不抛异常】
    它是对话热路径上的一环。健康检查是为了让对话更好，不是为了在模型出错时
    再补一刀把整轮回答也带走。所以：每个判据独立 try/except（记在 self._errors），
    输入哪怕是 None / 空串 / 非字符串 / 畸形 context，都返回 list（可以是空的）。
    去掉它：模型偶尔吐个奇怪字符 → 监测层抛异常 → 用户看到"出错了"，比退化还严重。
"""
import json
import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

from . import degeneration as D
from . import cfg as _health_cfg

# ============================================================================
# 症状登记表：code -> (group, 中文名, 默认 severity, 判据说明)
# 这张表就是本层的"总账"：监测认它、诊断按它判级、病历按它分组。
# 为什么用一张表而不是散在各处：判级要按"默认严重度"、病历要按"组"统计，
# 如果严重度写在判据函数里，改一次阈值得翻 18 个函数，早晚改漏一个。
# ============================================================================
SYMPTOMS = {
    # ---- 语言（4）----
    "repeat": ("language", "复读", "medium",
               "退化检测器命中（连续串联 / 短块扎堆 / 二元组多样性塌陷），≥60 字才判"),
    "garbled": ("language", "乱码", "heavy",
                "硬乱码：替换符 U+FFFD ≥2 / 非法控制字符 ≥2 / 私用区字符 ≥2；"
                "或白名单外**符号类**字符占比 ≥30%（≥40 字；别的语言的字母不算）"),
    "broken_sentence": ("language", "断句", "light",
                        "中文正文以汉字收尾（半句没收）；或 ≥200 字长文里句末标点密度 <1%"),
    "pace_shift": ("language", "语速突变", "light",
                   "本次输出长度与近 5 次均值偏离 >3 倍，且绝对差 ≥60 字"),
    # ---- 逻辑（4）----
    "self_contradiction": ("logic", "自相矛盾", "medium",
                           "同一轮相邻小句「肯定 + 否定同一核心」，或与前一轮结论直接相反"),
    "off_topic": ("logic", "答非所问", "medium",
                  "期望关键词命中率 <30% 且回答够长（≥80 字）"),
    "logic_gap": ("logic", "逻辑跳步", "light",
                  "弱信号：出现「因此/所以」但前文既无依据句也无任何数字事实"),
    "fact_reversal": ("logic", "事实反转", "medium",
                      "弱信号：同一实体在相邻两轮被赋予互斥属性（只认已知互斥对 / 直接否定）"),
    # ---- 情绪（3）----
    "sudden_anger": ("emotion", "突然暴躁", "medium",
                     "命中强负面词表 ≥1 条；或弱负面词 ≥3 条"),
    "sudden_negativity": ("emotion", "突然消极", "medium",
                          "第一人称消极短语 ≥1；或 spec 消极短语同轮 ≥2；"
                          "或歧义短语（做不了/没办法）紧跟第一人称出现"),
    "emotion_swing": ("emotion", "情绪失控", "light",
                      "同一轮里正/负情绪词各 ≥3 条同时高频出现"),
    # ---- 行为（4）----
    "tool_misuse": ("behavior", "工具乱调", "heavy",
                    "同一工具同轮 >5 次；或调用工具表里没有的工具；或该给参数却是 None"),
    "tool_skipped": ("behavior", "工具不调", "medium",
                     "本轮标记为工具轮却 tool_trace 为空；或问题有强检索诉求而轨迹为空（弱信号）"),
    "refusal": ("behavior", "拒绝服务", "heavy",
                "命中第一人称/服务语义的拒绝词（我不能帮你/我无法回答…）且**没有**给任何替代方案"),
    "infinite_loop": ("behavior", "无限循环", "heavy",
                      "tool_trace 里同一 (tool, args) 出现 ≥3 次"),
    # ---- 生理（3）----
    "timeout": ("physio", "响应超时", "medium",
                "elapsed_ms ≥ timeout_ms（未给 timeout 时按 180000ms 兜底）"),
    "vram_alert": ("physio", "显存告警", "heavy",
                   "vram_used_pct ≥ 0.9（也可由 used_mb/total_mb 折算；传 95 这种百分数会自动归一）"),
    "memory_growth": ("physio", "内存增长", "medium",
                      "mem_growth_pct ≥ 30（相对本会话起点）"),
}

GROUPS = ("language", "logic", "emotion", "behavior", "physio")
GROUP_CN = {"language": "语言", "logic": "逻辑", "emotion": "情绪",
            "behavior": "行为", "physio": "生理"}


# ================================================================ 载体主动动作白名单
# 【真端到端实测抓到的严重误判，这一节就是为它写的】
# 用户让模型删一个文件 → **载体层红线正确地拦下了**（返回 🚫 …删除禁区…）→
# 但这个"工具没成功"被行为类判据记成了 `tool_misuse` → 连中 2~3 次 →
# 诊断 HEAVY → 三级治疗执行 `switch_brain` → **把本来好好的本地大脑切成了不可用目标** →
# 小焦随后"大脑没有应答"，长文场景三次全不过。
#
# 根因不是阈值不对，是**模块耦合错了**：
#   红线拦截 / 健康治疗 / 权限拒绝 / SSRF 拦截 / 限流，这些都是**载体自己的主动动作**，
#   是"载体在正常工作"的证据 —— 它们与"模型行为异常"没有任何关系。
#   健康系统拿它们当症状，等于免疫系统把疫苗当成病毒，而且还会触发"换火种"这种重型处置。
#
# 所以这里立一条白名单：命中这些标记的工具结果，**一律不算模型退化**，
# 健康系统对它们"视而不见"。判据是**载体自己写下的固定标记**（不是猜语义），
# 因此可靠、不会被模型的措辞影响。
CARRIER_MARKS = (
    "🚫",                 # 安全红线（删除禁区等）的统一标记
    "删除禁区",
    "载体层的硬约束",
    "〔待确认〕",          # 权限确认流程：等用户点头，不是模型出错
    "SSRF",               # 安全防护拦截
    "请求太频繁",          # 限流
    "已被载体层拦截",
    "安全红线",
)


def is_carrier_action(text) -> bool:
    """这段工具结果是不是**载体主动做出来的动作**（红线/治疗/权限/SSRF/限流）。

    是 → 健康系统必须视而不见（不算模型症状、不计入熔断/乱调判断）。
    为什么用"固定标记"而不是"语义判断"：
      标记是载体自己写下的，一个字符都不会变；而语义判断要看模型措辞，
      同一个拦截换个说法就漏了 —— 白名单漏一个，误判链就整条复发。
    """
    s = str(text or "")
    if not s:
        return False
    return any(m in s for m in CARRIER_MARKS)


@dataclass
class Symptom:
    """一次症状的完整记录：**要能直接给用户看**（detail），也要能进病历（evidence）。

    为什么 detail 和 evidence 要分开：
      · detail 是给人读的一句话（"复读：短块『嗯。』扎堆重复 27 次"）；
      · evidence 是给机器用的数字（次数、位置、比例、streak）。
    合成一个字段的后果是二选一：要么人看不懂，要么诊断层得去解析中文 ——
    后者迟早因为改一句文案就把判级搞坏。
    """
    code: str
    group: str = ""
    name: str = ""
    severity: str = "light"
    detail: str = ""
    evidence: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def to_dict(self):
        """落进病历用的扁平结构（必须 JSON 可序列化 —— 里面绝不放 re.Match 这类对象）。"""
        return {"ts": self.ts, "code": self.code, "group": self.group, "name": self.name,
                "severity": self.severity, "detail": self.detail, "evidence": dict(self.evidence or {})}

    def __str__(self):
        return "[%s] %s（%s）：%s" % (self.severity, self.name or self.code, self.code, self.detail)


# ============================================================================
# 词表 / 正则（集中放这里，是为了让"判据"读起来像人话，也方便只调这一处）
# ============================================================================
_CJK = re.compile(r"[\u4e00-\u9fff]")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# 白名单：正常回答会出现的字符（中英日韩/标点/数学/箭头/表情/常见符号）。
# 为什么用**白名单**判乱码：乱码的本质是"出现了不该出现的码位"，黑名单永远列不全；
# 白名单外占比一旦高起来，就是乱码。去掉它就没法判"整段字符集跑飞"。
_OK_CHAR = re.compile(
    r"[\u0020-\u007e"                       # ASCII 可打印
    r"\u00a0-\u024f"                        # 拉丁扩展（法/德/拼音音标）
    r"\u0370-\u04ff"                        # 希腊 / 西里尔
    r"\u2000-\u206f\ufe00-\ufe0f\u200d"     # 常用标点 / 变体选择符 / 零宽连接
    r"\u2100-\u214f\u2190-\u21ff\u2200-\u22ff\u2460-\u24ff"
    r"\u2500-\u257f\u25a0-\u25ff\u2600-\u27bf\u2b00-\u2bff"
    r"\u3000-\u303f\u3040-\u30ff\u31c0-\u31ef"   # CJK 标点 / 假名
    r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"   # CJK 汉字
    r"\uff00-\uffef"                        # 全角
    r"\U0001f000-\U0001faff]"               # emoji
)

# 情绪词表。为什么把"强""弱"分开：`垃圾`/`无聊` 在正常回答里完全合法
# （"清理垃圾数据"、"这是个无聊的问题但…"），只有**连着好几个**才说明它情绪失控了。
_ANGER_STRONG = ("闭嘴", "烦死了", "别问了", "滚开", "滚蛋", "给我滚", "愚蠢",
                 "废物", "神经病", "少废话", "你有病", "弱智", "蠢货", "骂人")
_ANGER_WEAK = ("垃圾", "无聊", "讨厌", "烦人", "闭嘴吧")
# 消极词表：**必须限定"小焦在说自己"**。因为「如果网络不通就没意义了」是正经陈述，
# 而「我做不到」才是它泄气了。不加这个限定，普通回答会被大面积误判。
#
# 【实测踩到的近失误，写下来免得改回去】第一版把"帮不上/做不了/没办法"都算进"泛消极"，
# 只要同一轮出现两条就报警。结果一段**完全正常**的产品说明
# （"有些场景它帮不上忙…还是老实告诉你现在做不了"）被判成"突然消极"。
# 所以现在分三档：第一人称短语（最硬）、spec 点名的消极短语（要两条）、
# 歧义短语（必须紧跟在第一人称之后才算）。
_NEG_FIRST = ("我做不到", "我不行", "我没办法", "我做不了", "我帮不上", "我放弃",
              "我不想做了", "我尽力了", "我无能")
# spec 里点名的非第一人称消极短语：同轮出现两条才算（单条经常是正常叙述）
_NEG_MOOD = ("没意义", "算了", "无所谓", "不想做", "就这样吧", "没用的", "白费")
# 歧义短语：前 6 字内必须有"我/小焦/咱/自己"才算消极，否则是正常陈述
_NEG_FRAMED = ("做不了", "帮不上", "没办法", "不想做", "没用的", "不行了")
_SELF_WORDS = ("我", "小焦", "咱", "自己")
_POS_WORDS = ("太好了", "非常好", "很棒", "优秀", "感谢", "开心", "厉害",
              "完美", "满意", "推荐", "没问题", "放心")

# 拒绝与替代方案：判"拒绝"必须**同时**确认没有替代方案。
# 只看到"我不能"就报警，会把"我不能直接改你的文件，但可以给你命令"这种
# **负责任的回答**判成故障 —— 那是把好回答治坏了。
#
# 为什么拒绝词要**带第一人称/服务语义**，而不是见到"做不到"就算：
# 「如果是十年前，这个做不到」是正常陈述，「我做不到」是它泄气了 ——
# 那是"突然消极"，不是"拒绝服务"。混在一起会让同一句话被算成两个重症症状。
_REFUSE_CORE = ("我无法帮你", "我不能帮你", "我帮不了你", "我帮不了", "我没法帮你",
                "我无法帮", "我不能为你", "我无法为你", "不允许我", "没有权限",
                "我无法回答", "我不能回答", "我无法提供", "我不能提供",
                "我无法完成", "我不能完成", "我无法满足", "我不能满足",
                "我不能这样做", "我无法这样做")
_REFUSE_VERB = ("帮", "做", "给", "提供", "回答", "完成", "满足", "继续", "参与", "生成", "执行")
_ALT = ("不过我可以", "但我可以", "但是我可以", "你可以试试", "建议你", "换个方式",
        "替代方案", "我可以帮你", "或者你可以", "你可以用", "我可以教你", "可以这样",
        "另一条路", "你可以自己")

_TOOL_STRONG = ("搜索", "查一下", "帮我查", "帮我下载", "下载", "打开网页", "爬一下",
                "最新的", "官网", "网址", "链接", "实时")

_CLAUSE_SEP = re.compile(r"[。！？；;!?\n]+")
_NEG_PREFIX = ("不是", "不对", "不能", "不可以", "不支持", "不会", "不需要", "不应该",
               "没有", "并非", "无法", "不属于", "不存在")
_POS_MARK = ("是", "为", "可以", "能", "支持", "需要", "应该", "会", "正确",
             "可行", "属于", "存在", "有")
_CAUSE_WORDS = ("因此", "所以", "由此可见", "综上", "于是")
_EVID_WORDS = ("因为", "由于", "依据", "根据", "基于", "鉴于", "原因", "前提", "假设",
               "条件", "实验", "数据", "统计", "测试", "测量", "报告", "例如", "比如")
# 互斥属性对：只认**已知的**互斥关系。
# 为什么不用"任意两个不同属性都算反转"：那会把"这个模型是开源的，而且很快"判成矛盾。
# 反转必须是**真互斥**（开源/闭源、免费/收费），这是保守到几乎不会误伤的做法。
_ANTONYM = (("开源", "闭源"), ("免费", "收费"), ("本地", "云端"), ("公开", "保密"),
            ("在线", "离线"), ("增加", "减少"), ("上升", "下降"), ("支持", "反对"),
            ("同意", "反对"), ("正确", "错误"), ("安全", "危险"), ("成功", "失败"),
            ("同步", "异步"), ("有损", "无损"), ("加密", "明文"))
_ENTITY_ATTR = re.compile(
    r"([\u4e00-\u9fffA-Za-z0-9]{2,8})(?:是|为|属于|采用|使用|支持|基于)"
    r"([\u4e00-\u9fffA-Za-z0-9]{1,8})")

# 期望关键词里要丢掉的"无信息字"（疑问词/虚词/客套）。
# 为什么不丢：问题里一半的字是"请帮我一下的"，把它们算进命中率，
# 一段完全跑题的回答也能靠"我"和"的"拿到高分，判据就废了。
_QUESTION_STOP = set("请帮我你他她它的一下了吗呢吧啊哦嗯是有和与或及在把被给对为很都就还也才又再"
                     "什么怎么如何为何哪些哪个介绍说明讲讲告诉想要需要能不能可以会不会关于")


def _cfg_int(c, key, default):
    """从配置取整数（容错：用户可能把它写成 "30" 或 30.0）。取不到/坏了用默认值。"""
    try:
        return int(c.get(key, default))
    except Exception:      # noqa: silent-ok — 配置写坏了就当没配，绝不抛
        return int(default)


def _cfg_float(c, key, default):
    try:
        return float(c.get(key, default))
    except Exception:      # noqa: silent-ok — 同上
        return float(default)


class HealthMonitor:
    """18 类症状的检查器：`check(output, context)` → list[Symptom]（可为空，永不抛）。

    为什么是一"个"对象持有状态（streak / 近 5 次长度）而不是纯函数：
      · `streak`（同一症状连续几轮出现）是**判级的关键** —— 单次轻症不用管，
        连续三次才叫"持续"；这个信息只能跨轮累积。
      · 近 5 次输出长度是"语速突变"的基线，同理。
      改成纯函数：诊断层就拿不到"持续"这个维度，只能一轮一轮孤立地看，
      结果是"偶发的一次乱码"和"连着五轮乱码"被同样对待 —— 前者该无视，后者该停机。
    """

    SYMPTOMS = SYMPTOMS
    GROUPS = GROUPS

    def __init__(self, cfg=None, detector=None):
        c = _health_cfg(cfg if isinstance(cfg, dict) else None)
        self.cfg = c
        # 阈值全部来自配置（可调，不必改代码）；默认值一律"保守"。
        self.min_text = _cfg_int(c, "min_text_chars", 20)
        self.off_topic_rate = _cfg_float(c, "off_topic_hit_rate", 0.30)
        self.pace_factor = _cfg_float(c, "pace_factor", 3.0)
        self.pace_min_diff = _cfg_int(c, "pace_min_diff_chars", 60)
        self.vram_pct = _cfg_float(c, "vram_alert_pct", 0.9)
        self.mem_growth = _cfg_float(c, "mem_growth_pct", 30.0)
        self.timeout_ms = _cfg_int(c, "timeout_ms", 180000)
        self.tool_repeat_max = _cfg_int(c, "tool_repeat_max", 5)
        self.loop_repeat = _cfg_int(c, "loop_repeat", 3)
        self.garbled_ratio = _cfg_float(c, "garbled_ratio", 0.30)
        # 复读检测**复用** degeneration.py（Bug 3 的地基），绝不另写一套。
        # 两套重复检测的必然结局：两套阈值、两套误报，用户看到"这回又给砍了"。
        self.detector = detector if detector is not None else D.DegenerationDetector()
        self.reset()

    # ---------- 生命周期 ----------
    def reset(self):
        """清空跨轮状态（新会话/新任务开始时调）。"""
        self._streak = {}
        self._lens = []
        self._last = []
        self._rounds = 0
        self._errors = {}
        try:
            self.detector.reset()
        except Exception:      # noqa: silent-ok — 检测器没 reset 也不影响本轮
            pass

    def streak(self, code):
        """某症状**连续**出现多少轮（这一轮没出现就归零）。

        为什么按"连续"而不是"累计"：累计次数说明不了"现在还在不在病"。
        一个症状上个月犯了 10 次但最近 200 轮都干净，和"连着 5 轮都在犯"，
        处理方式完全不同 —— 后者必须立刻干预，前者只需要记在病历里。
        去掉"连续"语义：诊断层会把陈年旧账当成现症，不断升级治疗级别。
        """
        return int(self._streak.get(code, 0))

    def streaks(self):
        """全部有值的 streak（诊断/病历用）。"""
        return {k: v for k, v in self._streak.items() if v}

    def last(self):
        """上一轮检出的症状（界面上"刚才它怎么了"就显示这个）。"""
        return list(self._last)

    def errors(self):
        """哪些判据自己抛过异常（自检用：判据写挂了要能发现，而不是静默漏诊）。"""
        return dict(self._errors)

    # ---------- 主入口 ----------
    def check(self, output, context=None):
        """对一轮输出跑全部 18 类判据，返回命中的 Symptom 列表（可能为空，**永不抛**）。"""
        ctx = context if isinstance(context, dict) else {}
        text = "" if output is None else (output if isinstance(output, str) else str(output))
        found = []
        for code in SYMPTOMS:
            try:
                probe = getattr(self, "_p_" + code)
                s = probe(text, ctx)
            except Exception as e:      # noqa: silent-ok — 单个判据崩了不能连累整轮检查
                self._errors[code] = repr(e)
                s = None
            if isinstance(s, Symptom):
                found.append(s)
        # 语速基线：**在判据跑完之后**才追加本轮长度（否则本轮会拿自己当基线，永远不突变）
        try:
            if text:
                self._lens.append(len(text))
                del self._lens[:-5]
        except Exception:      # noqa: silent-ok — 基线记不上只是少一个判据
            pass
        # streak 按**登记表**遍历：没出现的 code 必须归零，漏掉这一步 streak 就只增不减
        codes = set(s.code for s in found)
        for code in SYMPTOMS:
            self._streak[code] = (self._streak.get(code, 0) + 1) if code in codes else 0
        for s in found:
            # 把 streak 盖进证据：诊断层判"持续"时直接用，不必再去问监测器（解耦）
            s.evidence.setdefault("streak", self._streak.get(s.code, 1))
        self._rounds += 1
        self._last = found
        return found

    # ---------- 构造工具 ----------
    def _mk(self, code, detail, evidence=None, severity=None):
        """按登记表造一条 Symptom（组/名/默认严重度都从表里取，避免各处手写走形）。"""
        group, name, sev, _rule = SYMPTOMS.get(code, ("?", code, "light", ""))
        return Symptom(code=code, group=group, name=name,
                       severity=severity or sev, detail=detail,
                       evidence=dict(evidence or {}))

    @staticmethod
    def _num(ctx, key):
        """取一个数值上下文（写坏了返回 None，绝不抛）。"""
        v = ctx.get(key)
        if v is None:
            return None
        try:
            return float(v)
        except Exception:      # noqa: silent-ok — 不是数字就当没给
            return None

    # ========================================================================
    # 语言组
    # ========================================================================
    def _p_repeat(self, text, ctx):
        """复读 —— **直接调用 degeneration.py**，本模块不另写一套重复检测。

        【踩过的坑，写下来免得复发】`DegenerationDetector.check()` 对短于 `min_chars`
        的输入会返回 `self._hit` —— 也就是**上一轮锁存的命中**。若直接复用同一个检测器，
        一段 20 字的正常短回答会被判成"复读"（它拿的是上一轮的账），
        streak 于是虚高、诊断级别虚高。所以每轮先 `reset()`，再让 check 只认本轮文本。
        去掉这一步：18 类症状里最容易误报的一条就出现了，而且极难复现（要看历史）。
        """
        d = self.detector
        try:
            d.reset()
        except Exception:      # noqa: silent-ok — reset 失败就退化为"不判复读"，宁可漏判
            return None
        if len(text) < int(getattr(d, "min_chars", 60)):
            return None
        hit = d.check(text, where="monitor")
        if hit is None:
            return None
        return self._mk("repeat",
                        "复读：%s（%s）" % (hit.detail or hit.kind, hit.kind),
                        {"kind": hit.kind, "phrase": (hit.phrase or "")[:24],
                         "count": int(hit.count or 0), "at": int(hit.at or 0),
                         "keep_until": int(hit.keep_until or 0)})

    def _p_garbled(self, text, ctx):
        """乱码：非法控制字符 / 替换符 / 私用区字符 / 白名单外**非文字**字符占比过高。

        为什么"白名单外"还要再排除字母/数字/组合符（L*/N*/M* 类别）：
        泰文、天城文、阿拉伯文、CJK 扩展区的生僻字都在白名单之外，但它们**是正常文字** ——
        用户用泰语提问、模型用泰语回答，绝不能被判成乱码。
        丢掉这层排除会怎样：非中英的**所有**语言都会被误报成乱码（多语言用户直接不可用）。
        剩下的"白名单外的符号类字符"才是真正的"字符集跑飞"信号（比如一堆部首/私用符号）。
        """
        if len(text) < 6:
            return None
        n_fffd = text.count("\ufffd")
        n_ctrl = len(_CTRL.findall(text))
        n_priv = 0
        n_odd = 0
        for ch in text:
            try:
                cat = unicodedata.category(ch)
            except Exception:      # noqa: silent-ok — 类别取不到就当作正常字符（宁可漏判）
                continue
            if cat in ("Co", "Cs", "Cn"):
                n_priv += 1
                continue
            if ch in "\n\r\t":
                continue
            if _OK_CHAR.match(ch):
                continue
            if cat[0] in ("L", "N", "M"):
                continue          # 别的语言的正常文字：不算乱码
            n_odd += 1
        hard = n_fffd + n_ctrl + n_priv
        ratio = n_odd / float(len(text))
        if hard < 2 and not (len(text) >= 40 and ratio >= self.garbled_ratio):
            return None
        return self._mk("garbled",
                        "乱码：替换符 %d 个 / 非法控制字符 %d 个 / 私用区 %d 个，"
                        "白名单外符号占 %.0f%%（样例 %r）"
                        % (n_fffd, n_ctrl, n_priv, ratio * 100, text[:24]),
                        {"fffd": n_fffd, "ctrl": n_ctrl, "private": n_priv,
                         "odd_ratio": round(ratio, 4), "sample": text[:40]})

    def _p_broken_sentence(self, text, ctx):
        """断句：以半句收尾；或长文里几乎没有句末标点。

        为什么用"以**汉字**收尾"当半句判据：正常中文正文不会以汉字突然收尾
        （要么句号、要么引号、要么换行）。而英文句子常以字母收尾、
        列表/标题天然不带句号 —— 所以只看"末尾是汉字"这一种情况，
        并且排除标题行/列表行。去掉这层限定：每份 markdown 清单都会被判断句。
        """
        t = text.rstrip()
        if len(t) < 80:
            return None
        if _CJK.match(t[-1]):
            tail_line = t.rsplit("\n", 1)[-1].strip()
            if not re.match(r"^\s*(#{1,6}\s|[-*+]\s|\d+[.、)]\s|>|\|)", tail_line) \
                    and not tail_line.endswith(("：", ":")):
                return self._mk("broken_sentence",
                                "断句：正文以半句收尾（末尾是「%s」，不是句末标点）" % t[-10:],
                                {"tail": t[-30:], "chars": len(t)})
        if len(t) >= 200:
            cjk = len(_CJK.findall(t))
            ends = sum(t.count(ch) for ch in "。！？!?；;")
            if cjk >= 120 and ends * 100 <= cjk:
                return self._mk("broken_sentence",
                                "断句：%d 字正文只有 %d 个句末标点（密度 <1%%）→ 标点缺失" % (cjk, ends),
                                {"cjk": cjk, "ends": ends})
        return None

    def _p_pace_shift(self, text, ctx):
        """语速突变：本次长度 vs 近 5 次均值，偏离 >3 倍。

        为什么还要一个"绝对差 ≥60 字"的下限：均值 20 字时，从 20 掉到 5 字
        也算"偏离 3 倍"，但那是正常的一句短回应，不是病。
        去掉这个下限：短问答里会不停误报"语速突变"。
        """
        cur = len(text)
        hist = list(self._lens)
        if cur <= 0 or len(hist) < 5:
            return None
        mean = sum(hist) / float(len(hist))
        if mean < 20:
            return None
        diff = abs(cur - mean)
        if diff < self.pace_min_diff:
            return None
        ratio = diff / mean
        if ratio <= self.pace_factor:
            return None
        return self._mk("pace_shift",
                        "语速突变：本次 %d 字，近 5 次均值 %.0f 字（偏离 %.1f 倍，%s）"
                        % (cur, mean, ratio, "突然变长" if cur > mean else "突然变短"),
                        {"chars": cur, "mean": round(mean, 1), "ratio": round(ratio, 2),
                         "history": hist})

    # ========================================================================
    # 逻辑组
    # ========================================================================
    def _p_self_contradiction(self, text, ctx):
        """自相矛盾：同一轮"肯定 + 否定同一核心"，或与前一轮结论直接相反。"""
        clauses = [c.strip() for c in _CLAUSE_SEP.split(text) if c.strip()]
        for i, b in enumerate(clauses):
            pre = self._neg_prefix_of(b)
            if not pre:
                continue
            core = b[len(pre):].lstrip("的了")
            if len(core) < 3:
                continue
            # 只回看最多 4 个小句（同一段话内），避免把相隔很远的无关句子配对
            for a in clauses[max(0, i - 4):i]:
                if core[:6] in a and any(m in a for m in _POS_MARK):
                    return self._mk("self_contradiction",
                                    "自相矛盾：先说「%s」，紧接着又说「%s」" % (a[:24], b[:24]),
                                    {"affirm": a[:60], "deny": b[:60], "core": core[:12]})
        prev = ctx.get("prev_output") or ctx.get("prev_answers")
        if prev:
            prev_text = "。".join(str(x) for x in prev) if isinstance(prev, (list, tuple)) else str(prev)
            for b in clauses:
                pre = self._neg_prefix_of(b)
                if not pre:
                    continue
                core = b[len(pre):].lstrip("的了")
                if len(core) >= 3 and core[:8] in prev_text:
                    return self._mk("self_contradiction",
                                    "自相矛盾：上一轮说「…%s…」，这一轮说「%s」" % (core[:12], b[:24]),
                                    {"core": core[:12], "now": b[:60], "prev": prev_text[:60]})
        return None

    @staticmethod
    def _neg_prefix_of(clause):
        """小句开头的否定前缀（含"这个方案不是…"这种主语开头的形式）。

        【踩过的坑】这条正则有两个括号：`(...主语的字符类...)` 和 `(...否定词...)`。
        一开始取 `m.end(1)` 当"否定前缀结束位置"，结果拿到的是**主语**的结束位置，
        于是 "这个方案不是可行的" 被切成 core="不是可行的" —— 于是永远配不上
        前面的 "…是可行的"，自相矛盾这类判据静默失效（不报错、只是从来不触发）。
        必须用 `m.end(0)`（整个匹配的结束）：`(?:)` 那个非捕获组也是为此写的。
        """
        for p in _NEG_PREFIX:
            if clause.startswith(p):
                return p
        m = re.match(r"^(?:[\u4e00-\u9fffA-Za-z0-9]{1,8}?)(" + "|".join(_NEG_PREFIX) + ")", clause)
        if m:
            return clause[:m.end(0)]
        return ""

    def _p_off_topic(self, text, ctx):
        """答非所问：期望关键词命中率 <30% 且回答够长。

        两条路：给了 `expectations` 就按关键词算；只给了问题，就用**问题里的内容字**
        当"期望关键词"的替身（命中率 = 这些字有多少出现在回答里）。
        为什么用内容字而不是切词：中文切词要么引第三方库、要么自己写一套分词语义，
        而"答非所问"的判据只需要"它有没有在讲这件事"—— 字符覆盖率已经足够，
        且与语言无关。丢掉的只是"讲到了但换了说法"的细微情况，属于可接受的漏判。
        """
        if len(text) < 80:
            return None
        exps = ctx.get("expectations")
        if isinstance(exps, str):
            exps = [exps]
        method = "expectations"
        if isinstance(exps, (list, tuple)) and exps:
            terms = [str(e) for e in exps if str(e).strip()]
            # 【真端到端实测抓到的误报】调用方给的 expectations 可能是**模糊提问**的碎片
            # （"仔细查""肯定不够"），拿它们判"答非所问"会把正常回答判病，
            # 连中 3 轮还会升级到二级治疗、清掉用户的会话上下文。
            # 这里加一道闸：期望要点必须**至少 2 个且都不短于 2 字**，否则不认这批期望，
            # 退回"问题内容字"那条更宽容的路（它对模糊提问基本不会误报）。
            if len(terms) < 2 or all(len(t) < 2 for t in terms):
                exps = None
        if isinstance(exps, (list, tuple)) and exps:
            terms = [str(e) for e in exps if str(e).strip()]
        else:
            q = ctx.get("question") or ctx.get("user_input") or ""
            q = q if isinstance(q, str) else str(q)
            terms = []
            for ch in q:
                if ch in _QUESTION_STOP:
                    continue
                if _CJK.match(ch) or ch.isdigit():
                    terms.append(ch)
            for w in re.findall(r"[A-Za-z]{3,}", q):
                terms.append(w.lower())
            terms = list(dict.fromkeys(terms))
            method = "content_chars"
            if len(terms) < 4:
                return None
        if len(terms) < 2:
            return None
        low = text.lower()
        hit = [e for e in terms if (e.lower() if method == "content_chars" else e) in low]
        rate = len(hit) / float(len(terms))
        if rate >= self.off_topic_rate:
            return None
        return self._mk("off_topic",
                        "答非所问：期望要点命中 %d/%d（%.0f%%，阈值 %.0f%%），"
                        "回答 %d 字却没讲到这些" % (len(hit), len(terms), rate * 100,
                                                 self.off_topic_rate * 100, len(text)),
                        {"rate": round(rate, 3), "n_expected": len(terms), "n_hit": len(hit),
                         "missing": [e for e in terms if e not in hit][:8], "method": method})

    def _p_logic_gap(self, text, ctx):
        """逻辑跳步【弱信号】：出现"因此/所以"，但前文既没有依据句也没有任何数字事实。

        为什么要三重门槛（长度 ≥120、前文 ≥60 字、前文无依据词且无数字）：
        "因此"在正常写作里**非常常见**，只凭它出现就报警会大面积误伤。
        加上"前文连一个数字都没有"这一条后，剩下的基本是"凭空下结论"。
        detail 里明确写"弱信号"，因为它依然是本层最容易漏/最可能误报的一条。
        """
        if len(text) < 120:
            return None
        pos = -1
        word = ""
        for w in _CAUSE_WORDS:
            i = text.find(w)
            if i >= 0 and (pos < 0 or i < pos):
                pos, word = i, w
        if pos < 0:
            return None
        before = text[:pos]
        if len(before) < 60:
            return None
        if any(w in before for w in _EVID_WORDS):
            return None
        if re.search(r"\d", before):
            return None
        return self._mk("logic_gap",
                        "逻辑跳步（弱信号）：出现「%s」，但前面 %d 字里既没有依据句也没有任何数字事实"
                        % (word, len(before)),
                        {"at": pos, "before_chars": len(before), "word": word})

    def _p_fact_reversal(self, text, ctx):
        """事实反转【弱信号】：同一实体在相邻两轮被赋予互斥属性。"""
        prev = ctx.get("prev_output") or ctx.get("prev_answers")
        if not prev:
            return None
        prev_text = "。".join(str(x) for x in prev) if isinstance(prev, (list, tuple)) else str(prev)
        if not prev_text.strip():
            return None
        a_map = self._entity_attrs(prev_text)
        b_map = self._entity_attrs(text)
        for ent in set(a_map) & set(b_map):
            for x in a_map[ent]:
                for y in b_map[ent]:
                    if x == y:
                        continue
                    if (y.startswith("不") and y[1:] == x) or (x.startswith("不") and x[1:] == y):
                        why = "直接否定"
                    elif any((p in x and q in y) or (q in x and p in y) for p, q in _ANTONYM):
                        why = "互斥属性"
                    else:
                        continue
                    return self._mk("fact_reversal",
                                    "事实反转（弱信号）：「%s」上一轮是「%s」，这一轮变成「%s」（%s）"
                                    % (ent, x, y, why),
                                    {"entity": ent, "prev": x, "now": y, "why": why})
        return None

    @staticmethod
    def _entity_attrs(t):
        """抽出「实体 → 属性」候选（`X 是 Y` 这种断言句式）。"""
        out = {}
        try:
            for m in _ENTITY_ATTR.finditer(t or ""):
                out.setdefault(m.group(1), []).append(m.group(2))
        except Exception:      # noqa: silent-ok — 抽不出来就当没有断言，漏判不误判
            return {}
        return out

    # ========================================================================
    # 情绪组
    # ========================================================================
    def _p_sudden_anger(self, text, ctx):
        """突然暴躁：命中强负面词，或弱负面词连中 ≥3。"""
        strong = [w for w in _ANGER_STRONG if w in text]
        weak = [w for w in _ANGER_WEAK if w in text]
        if not strong and len(weak) < 3:
            return None
        return self._mk("sudden_anger",
                        "突然暴躁：命中 %s%s" % ("/".join(strong[:4]) or "",
                                            ("，另有 %s" % "/".join(weak[:3])) if weak else ""),
                        {"strong": strong, "weak": weak})

    def _p_sudden_negativity(self, text, ctx):
        """突然消极：**第一人称**消极短语 ≥1，或 spec 的消极短语 ≥2，或歧义短语紧跟在第一人称后。

        为什么第一人称的门槛最低、别的门槛更高：
        「我做不到」＝它在说自己不行（那是病）；「网络不通就没办法了」＝正常陈述。
        把两者一刀切的结果，是把所有"说明限制"的负责任回答都判成消极（实测踩到过）。
        """
        first = [w for w in _NEG_FIRST if w in text]
        mood = [w for w in _NEG_MOOD if w in text]
        framed = []
        for w in _NEG_FRAMED:
            idx = text.find(w)
            while idx >= 0:
                if any(s in text[max(0, idx - 6):idx] for s in _SELF_WORDS):
                    framed.append(w)
                    break
                idx = text.find(w, idx + 1)
        if not first and len(mood) < 2 and not framed:
            return None
        hits = (first + mood + framed)[:5]
        return self._mk("sudden_negativity",
                        "突然消极：%s" % "、".join(hits),
                        {"first_person": first, "mood": mood, "framed": framed})

    def _p_emotion_swing(self, text, ctx):
        """情绪失控：同一轮里正/负情绪词同时高频出现。

        为什么要求"各 ≥3"：一句话里出现"太好了"和"不行"是很正常的（比如
        "这个方案太好了，但预算不行"）。同一轮里两类都连着冒三次，
        才是情绪在同一个回答里翻来覆去。
        """
        pos = [w for w in _POS_WORDS if w in text]
        neg = [w for w in (_ANGER_STRONG + _ANGER_WEAK + _NEG_FIRST + _NEG_MOOD + _NEG_FRAMED)
               if w in text]
        if len(pos) < 3 or len(neg) < 3:
            return None
        return self._mk("emotion_swing",
                        "情绪失控：同一轮里正面词 %s 与负面词 %s 各出现 3 次以上"
                        % ("/".join(pos[:3]), "/".join(neg[:3])),
                        {"positive": pos, "negative": neg})

    # ========================================================================
    # 行为组
    # ========================================================================
    @staticmethod
    def _norm_trace(trace):
        """把 tool_trace 归一成 [(工具名, 参数), …]（容忍 dict / 元组 / 字符串三种写法）。

        **载体主动动作一律不进这个表**（真端到端实测抓到的严重误判，见 `is_carrier_action`）。
        行为类症状（工具乱调 / 工具不调 / 无限循环）全部基于这张表，
        从这里剔掉就等于"健康系统对载体的主动拦截视而不见" —— 一处收口，三条判据同时安全。
        """
        out = []
        if trace is None:
            return out
        if isinstance(trace, dict):
            trace = [trace]
        if not isinstance(trace, (list, tuple)):
            return out
        for e in trace:
            try:
                name, args = "", None
                if isinstance(e, dict):
                    if is_carrier_action(e.get("result") or e.get("res") or ""):
                        continue              # ← 载体自己的拦截/治疗/拒绝：不算模型行为
                    name = e.get("tool") or e.get("name") or ""
                    args = e.get("args", e.get("arguments"))
                elif isinstance(e, (list, tuple)) and e:
                    name = str(e[0])
                    args = e[1] if len(e) > 1 else None
                elif isinstance(e, str):
                    if is_carrier_action(e):
                        continue
                    name = e
                    args = ""
                if name:
                    out.append((str(name), args))
            except Exception:      # noqa: silent-ok — 单条轨迹畸形就跳过它
                continue
        return out

    @staticmethod
    def _args_key(args):
        try:
            return json.dumps(args, ensure_ascii=False, sort_keys=True, default=str)
        except Exception:      # noqa: silent-ok — 参数不可序列化就用 repr 当键
            return repr(args)

    def _known_tools(self):
        """已知工具表：优先调用方给的，其次**已加载的** app。

        为什么拿不到就不判"不存在的工具"：宁可不判，也不能因为"我不知道有哪些工具"
        就把所有工具调用都报成乱调。这条是"绝不误报"原则的直接体现。
        为什么不在这里 import app：见 `core/health/__init__.py::app_module` 的实测说明
        （会连带加载 4B 模型，2.63s）。
        """
        try:
            from . import app_module
            app = app_module(allow_import=False)
            if app is None:
                return None
            for fn in ("real_tool_names", "all_tool_names"):
                f = getattr(app, fn, None)
                if callable(f):
                    names = f()
                    if names:
                        return set(str(x) for x in names)
        except Exception:      # noqa: silent-ok — 拿不到工具表就不做这项判据
            return None
        return None

    def _p_tool_misuse(self, text, ctx):
        """工具乱调：同一工具 >5 次 / 调不存在的工具 / 该给参数却是 None。"""
        trace = self._norm_trace(ctx.get("tool_trace"))
        if not trace:
            return None
        counter = {}
        for n, _a in trace:
            counter[n] = counter.get(n, 0) + 1
        over = sorted([(n, c) for n, c in counter.items() if c > self.tool_repeat_max],
                      key=lambda x: -x[1])
        known = ctx.get("known_tools") or self._known_tools()
        unknown = []
        if known:
            ks = set(str(x) for x in known)
            unknown = sorted({n for n, _a in trace if n not in ks})
        noarg = sorted({n for n, a in trace if a is None})
        if not over and not unknown and not noarg:
            return None
        bits = []
        if over:
            bits.append("同一工具重复调用 %s" % "、".join("%s×%d" % (n, c) for n, c in over[:3]))
        if unknown:
            bits.append("调用了不存在的工具 %s" % "、".join(unknown[:3]))
        if noarg:
            bits.append("参数为空（None）的工具 %s" % "、".join(noarg[:3]))
        return self._mk("tool_misuse", "工具乱调：" + "；".join(bits),
                        {"over": over, "unknown": unknown, "noarg": noarg, "calls": len(trace)})

    def _p_tool_skipped(self, text, ctx):
        """工具不调：该调工具的轮次却没有任何工具调用。

        为什么要"本轮标记为工具轮"或"问题里有强检索诉求"二者之一才判：
        `tool_trace` 为空在闲聊轮里是**完全正常**的。只凭"空轨迹"就报警，
        每句"你好"都会被判成"工具不调"。
        """
        trace = ctx.get("tool_trace")
        empty = trace is None or (isinstance(trace, (list, tuple, dict)) and len(trace) == 0)
        if not empty:
            return None
        q = ctx.get("question") or ctx.get("user_input") or ""
        q = q if isinstance(q, str) else str(q)
        strong = [w for w in _TOOL_STRONG if w in q]
        if ctx.get("is_tool_turn") is True:
            return self._mk("tool_skipped",
                            "工具不调：本轮被标为工具轮（%s），但 tool_trace 为空" % (q[:30] or "无问题"),
                            {"is_tool_turn": True, "question": q[:60]})
        if ("tool_trace" in ctx) and strong:
            return self._mk("tool_skipped",
                            "工具不调（弱信号）：问题里有 %s 这类明确诉求，但本轮没有任何工具调用"
                            % "、".join(strong[:3]),
                            {"is_tool_turn": False, "markers": strong, "question": q[:60]})
        return None

    def _p_refusal(self, text, ctx):
        """拒绝服务：**带第一人称/服务语义**的拒绝，且没有给替代方案。

        为什么必须确认"没有替代方案"：好的拒绝长这样 ——
        「我不能直接删你的文件，但我可以给你一条命令」。只看拒绝词会把这种
        **正确且负责任**的回答判成故障，然后治疗层去"重试"，反而把好回答推倒重来。
        为什么拒绝词要带第一人称：见文件头词表的说明 —— 不这样限定，
        "这个做不到" 这类正常陈述会被算成重症，而且和"突然消极"重复计数。
        """
        refuse = []
        for core in _REFUSE_CORE:
            if core in text:
                refuse.append(core)
        for m in re.finditer(r"我(?:不能|无法|不可以)", text or ""):
            tail = text[m.end():m.end() + 6]
            if any(v in tail for v in _REFUSE_VERB):
                refuse.append(m.group(0) + tail[:2])
        if not refuse:
            return None
        alt = [w for w in _ALT if w in text]
        if alt or re.search(r"你可以[\u4e00-\u9fff]{1,8}", text):
            return None
        return self._mk("refusal",
                        "拒绝服务：命中「%s」且没有给出任何替代方案" % "、".join(refuse[:3]),
                        {"refuse": refuse[:5], "alt": alt, "chars": len(text)})

    def _p_infinite_loop(self, text, ctx):
        """无限循环：同一 (工具, 参数) 出现 ≥3 次（转圈圈，不是在干活）。"""
        trace = self._norm_trace(ctx.get("tool_trace"))
        if not trace:
            return None
        counter = {}
        for n, a in trace:
            k = (n, self._args_key(a))
            counter[k] = counter.get(k, 0) + 1
        tops = sorted([(k, c) for k, c in counter.items() if c >= self.loop_repeat],
                      key=lambda x: -x[1])
        if not tops:
            return None
        (name, args), cnt = tops[0]
        return self._mk("infinite_loop",
                        "无限循环：(%s, %s) 重复 %d 次" % (name, (args or "")[:40], cnt),
                        {"tool": name, "args": (args or "")[:120], "count": cnt,
                         "calls": len(trace)})

    # ========================================================================
    # 生理组
    # ========================================================================
    def _p_timeout(self, text, ctx):
        """响应超时：elapsed_ms ≥ timeout_ms（没给 timeout 就用兜底上限）。"""
        el = self._num(ctx, "elapsed_ms")
        if el is None:
            return None
        limit = self._num(ctx, "timeout_ms")
        limit = self.timeout_ms if limit is None or limit <= 0 else limit
        if el < limit:
            return None
        return self._mk("timeout",
                        "响应超时：本轮耗时 %.1fs，超过上限 %.1fs" % (el / 1000.0, limit / 1000.0),
                        {"elapsed_ms": el, "limit_ms": limit})

    def _p_vram_alert(self, text, ctx):
        """显存告警：vram_used_pct ≥ 0.9（也接受 used/total MB 折算）。"""
        pct = self._num(ctx, "vram_used_pct")
        if pct is None:
            used = self._num(ctx, "vram_used_mb")
            total = self._num(ctx, "vram_total_mb")
            if used is None or not total:
                return None
            pct = used / total
        if pct > 1.5:          # 有人习惯传 95（百分数）而不是 0.95 —— 归一化，避免漏判
            pct = pct / 100.0
        if pct < self.vram_pct:
            return None
        return self._mk("vram_alert",
                        "显存告警：已用 %.0f%%（阈值 %.0f%%）→ 再涨就要开始算错/复读了"
                        % (pct * 100, self.vram_pct * 100),
                        {"pct": round(pct, 3), "threshold": self.vram_pct})

    def _p_memory_growth(self, text, ctx):
        """内存增长：mem_growth_pct ≥ 30（相对本会话起点）。

        为什么盯"增长"而不是"占用"：占得多的进程未必有病（模型本来就吃内存），
        但**持续涨**一定是漏了 —— 每轮都多留一点上下文/缓存，几百轮后必爆。
        """
        g = self._num(ctx, "mem_growth_pct")
        if g is None or g < self.mem_growth:
            return None
        return self._mk("memory_growth",
                        "内存增长：本会话已涨 %.0f%%（阈值 %.0f%%）→ 疑似上下文/缓存没释放"
                        % (g, self.mem_growth),
                        {"growth_pct": g, "threshold": self.mem_growth})


def detect(text, where="", **kw):
    """一次性检测（无跨轮状态）—— 事后体检 / 单测用。"""
    m = HealthMonitor()
    out = m.check(text, {"__where": where} if where else None)
    return out


__all__ = ["Symptom", "HealthMonitor", "SYMPTOMS", "GROUPS", "GROUP_CN", "detect"]
