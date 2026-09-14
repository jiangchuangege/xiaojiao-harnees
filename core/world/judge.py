# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
# -*- coding: utf-8 -*-
"""小焦 · 世界层 · 判断器（site judge：这页值不值得信、值不值得记）

【它解决什么问题】
  探索器会一口气捞回几十条候选（标题+网址+摘要）。它必须**在看之前**就能丢掉大部分：
  广告页、关键词堆砌的 SEO 页、二手转载、跟用户毫无关系的页。
  如果每条都先抓回来再判断，那就是"对全世界挨个敲门" —— 慢、费流量，还很打扰别人。

【口径：规则先行、模型补充（这是本模块唯一重要的设计决定）】
  · 类型 / 可信度 / 刷新周期 → 一律走 `WorldModel` 那三张**可解释的表**
    （wiki/repo/api/docs=0.8、tech_news=0.7、forum/social=0.5、shop=0.4）。
    为什么不让模型打分：让模型给一个站打 0.83，换个模型分数就变了 —— 那不是"世界"，是"模型的印象"。
    用户看到 0.7 能追问"为什么"，看到 0.83 只能干瞪眼。
  · 质量（原创/转载/广告/垃圾）与相关度 → 也先用**规则特征**：
    推广用语、关键词堆砌比、正文/链接比、标题党标点、"转载请注明"标记、与画像关键词的重合度。
    这些特征每一条都能翻译成一句人话（写进 evidence），出错时用户能直接反驳。
  · 只有**规则做不了的那一小块**（"这页到底是原创还是洗稿"）才问模型，
    而且必须 **JSON 输出 + 解析失败就回落规则**。
    为什么宁可回落：模型的乱答（前言后语、截断、幻觉出的字段）绝不能改写可信度 ——
    那等于让火种的抖动污染载体的判断。回落之后结论仍然是"规则口径"，用户仍然看得懂。

【为什么 evidence 至少两条】
  evidence 是这个模块的**产品**，不是调试信息：面板上"小焦为什么觉得这个站不可信"就靠它。
  一条证据等于没有解释（"因为看着像广告"）。所以类型一条、质量一条、相关度一条，永远都在。

落盘：本模块**自己不写任何文件**（判断是纯函数式的一次调用）；
结论交给 `WorldModel.remember_judgment` 落进 `logs/world/model.json`，过程留在探索器的吸收日志里。
"""
import json
import logging
import os
import re
from collections import Counter
from dataclasses import dataclass, field

try:                                    # 包内 import（正常路径）
    from .model import (TYPE_REFRESH, TYPE_TRUST, WORLD_DIR, domain_of_url,
                        format_interval, infer_type_rules)
except ImportError:                     # 直接 `python core/world/judge.py` 时没有包上下文
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from model import (TYPE_REFRESH, TYPE_TRUST, WORLD_DIR, domain_of_url,   # noqa: F401
                       format_interval, infer_type_rules)

logger = logging.getLogger(__name__)

# ===== 推广用语表：命中就是"这页在卖东西" =====
# 为什么必须是**具体词**而不是"广告"两个字：真实广告页几乎不写"广告"，
# 它写的是"点击购买""限时优惠""加微信"。用泛词的结果是一条都命中不了。
_AD_WORDS = ("点击购买", "立即抢购", "限时优惠", "限时特价", "优惠券", "领券", "加微信", "扫码",
             "下单「, 」包邮「, 」全网最低「, 」清仓「, 」仅需「, 」特价「, 」秒杀「, 」库存告急「, 」客服咨询",
             "买一送一「, 」到手价「, 」促销「, 」旗舰店「, 」立即购买「, 」buy now「, 」limited offer",
             "coupon", "discount", "shop now", "add to cart")

# ===== 转载标记：命中说明这是**二手**叙述（不是假的，但要降权）=====
# 为什么降权而不丢弃：转载经常是用户唯一能看到的版本（原文在付费墙里）。
# 降 10% + 标注来源，比直接丢掉更诚实。
_REPOST_WORDS = ("转载请注明", "转载自", "本文转自", "转自：", "来源：", "来源:", "原文链接",
                 "原文出处", "via ", "image via", "repost", "本文摘自")

# ===== 标题党标点/词：不改质量，只压置信度（它是"不严谨"的信号，不是"错"）=====
_CLICKBAIT = ("震惊", "竟然", "必看", "不看后悔", "揭秘", "真相", "惊天", "速看", "删前速看",
              "太可怕", "绝对", "史上最")

# 中文功能词：抽词时过滤掉，否则相关度会被「我们/可以/这个」刷满。
_STOP = {
    "我们「, 」你们「, 」他们「, 」什么「, 」这个「, 」那个「, 」这些「, 」那些「, 」一个「, 」没有「, 」就是",
    "因为「, 」所以「, 」但是「, 」如果「, 」已经「, 」以及「, 」对于「, 」关于「, 」进行「, 」使用「, 」通过",
    "表示「, 」目前「, 」今日「, 」最新「, 」最近「, 」首页「, 」登录「, 」注册「, 」更多「, 」详情「, 」相关",
    "推荐「, 」广告「, 」网站「, 」页面「, 」内容「, 」查看「, 」了解「, 」点击「, 」可以「, 」还是「, 」这样",
    "那样「, 」时候「, 」问题「, 」方式「, 」为了「, 」而且「, 」或者「, 」并且「, 」然后「, 」另外「, 」因此",
    "以下「, 」以上「, 」全部「, 」所有「, 」一些「, 」很多「, 」非常「, 」可能「, 」应该「, 」需要「, 」提供",
    "支持「, 」欢迎「, 」分享「, 」评论「, 」阅读「, 」全文「, 」链接「, 」转载「, 」版权「, 」声明",
}
_STOP_EN = {"the", "and", "for", "with", "this", "that", "you", "are", "was", "not", "from",
            "have「, 」has「, 」but「, 」http「, 」https「, 」www「, 」com「, 」html「, 」body「, 」title",
            "div", "span", "class", "href", "src", "nbsp", "amp", "get", "all", "new"}

_TAG_RE = re.compile(r"<[^>]{0,600}>")
_SCRIPT_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
_EN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#.\-]{1,}")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_MD_TITLE_RE = re.compile(r"^\s{0,3}#{1,3}\s+(.+?)\s*$", re.M)
_JSON_OBJ_RE = re.compile(r"\{.*\}", re.S)
_FENCE_RE = re.compile(r"^\s*```[a-zA-Z]*\s*|\s*```\s*$")


def _clamp(x, lo=0.0, hi=1.0, default=0.5):
    """把数值夹到 [lo,hi]；坏值（None/"abc"/NaN）退回 default，绝不抛错。

    为什么要单独写一个而不是复用 model 里的：那个是私有的（`_clamp01`），
    跨模块 import 私有名会把"内部实现"变成"公共契约" —— 将来它一改就炸两个模块。
    """
    try:
        v = float(x)
    except Exception:
        return float(default)
    if v != v:                      # NaN 参与的比较全 False → 会污染排序/平均
        return float(default)
    return max(float(lo), min(float(hi), v))


def _plain(text):
    """HTML → 可分析的纯文本：先去掉 script/style 整段，再剥标签。

    为什么必须先去 script/style：广告页和 SEO 页的内联脚本里塞满了关键词，
    只剥标签的话这些词会全留下来，把"堆砌比"和"广告词计数"直接刷爆（判谁都是广告）。
    去掉这一步：判断器的两个核心特征全部失真。
    """
    t = str(text or "")
    if not t:
        return ""
    t = _SCRIPT_RE.sub(" ", t)
    t = _TAG_RE.sub(" ", t)
    t = t.replace("&nbsp;", " ").replace("&amp;", "&").replace("&quot;", '"')
    return re.sub(r"[ \t\u3000]+", " ", t).strip()


def _title_of(raw, plain):
    "「」抠标题：原始 HTML 的 <title> 优先，其次 Markdown 一级标题。抠不到返回 「」。「」"
    t = str(raw or "")
    m = _TITLE_RE.search(t)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()[:200]
    m = _MD_TITLE_RE.search(t)
    if m:
        return m.group(1).strip()[:200]
    return ""


def _count_words(text, words):
    "「」统计一组词在正文里的**总出现次数**（不分大小写）。空文本返回 0。「」"
    low = str(text or "").lower()
    if not low:
        return 0
    return sum(low.count(str(w).lower()) for w in words)


def _stuffing_ratio(text):
    """关键词堆砌的量化口径：最高频**中文 2-gram** 占全部 2-gram 的比例。

    为什么用 2-gram 占比而不是"某词出现次数"：
      · 只看次数，长页面随便重复几次就误判；
      · 只看占比，短页面又会剧烈抖动。
    占比配合"正文 ≥200 字"的门槛，就是"整页翻来覆去只有那么两三个词"的可靠刻画。
    为什么是 2-gram：不需要分词器（多一个依赖就多一份维护），而堆砌页的特征恰恰是
    "同一对字反复出现"（量子计算量子计算量子计算… 的 2-gram 全部集中在那两组）。
    返回 (最高频词组, 占比)；样本太小（组数<20）时返回 ("", 0.0) —— 样本不足不下结论。
    """
    runs = _CJK_RE.findall(str(text or ""))
    grams = Counter()
    total = 0
    for r in runs:
        for i in range(len(r) - 1):
            grams[r[i:i + 2]] += 1
            total += 1
    if total < 20 or not grams:
        return "", 0.0
    w, c = grams.most_common(1)[0]
    return w, c / float(total)


def _terms(text, max_n=4):
    """从一段文本里抽"候选词"（中文 2~4-gram + 英文词），过滤功能词。

    为什么要抽 n-gram 而不是等一个分词器：见 `_stuffing_ratio` 的说明 ——
    这一层的目标是"这页在讲什么"，不是词法分析。代价是会有跨词边界的假词，
    所以相关度用的是**画像关键词是否出现**（子串匹配），而不是拿抽出来的词去比。
    """
    out = []
    for run in _CJK_RE.findall(str(text or "")):
        n = len(run)
        for size in range(2, min(max_n, n) + 1):
            for i in range(n - size + 1):
                g = run[i:i + size]
                if g in _STOP:
                    continue
                out.append(g)
    for w in _EN_RE.findall(str(text or "")):
        if len(w) < 2 or w.lower() in _STOP_EN:
            continue
        out.append(w)
    return out


def _profile_keywords(profile):
    """从各种形状的画像里抽出"关键词列表"。

    为什么容忍这么多形状（dict / list / str / None）：画像的写入方不止一个
    （面板、对话里刮到的偏好、探索器自己总结的兴趣），谁都不想被一个格式卡住。
    取值的口径：dict 取所有**值**（字符串或字符串列表）；字符串按标点/空白切。
    去重但保留先后顺序：顺序是给人看的（面板上"最关心什么"排前面）。
    """
    kws = []
    if profile is None:
        return kws
    if isinstance(profile, dict):
        vals = []
        for k, v in profile.items():
            if isinstance(v, (list, tuple, set)):
                vals.extend([str(x) for x in v])
            elif isinstance(v, str):
                vals.append(v)
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                continue            # 数字字段（阈值之类）不是关键词
            _ = k
    elif isinstance(profile, (list, tuple, set)):
        vals = [str(x) for x in profile]
    elif isinstance(profile, str):
        vals = re.split(r"[,，、;；\s/|]+", profile)
    else:
        vals = []
    for v in vals:
        s = str(v or "").strip()
        if not s or len(s) > 40:
            continue
        if s not in kws:
            kws.append(s)
    return kws[:40]


def _parse_quality_json(raw):
    """解析模型回的那一小段 JSON。**任何不合规都返回 None**（调用方回落规则）。

    为什么要专门写一个解析器、而不是 `json.loads(raw)`：
      · 模型极爱把 JSON 包在 ```json 代码块里，或者前后加一句"好的，结果如下："；
      · 字段名/取值也会飘（"quality": "广告" 而不是 "ad"）。
    这里先把代码块和解释剥掉，取出第一个 `{...}`，再校验**取值必须在允许集合里**。
    为什么不"尽量猜"模型的意思：猜错一次就是一次错误的降权，用户还看不到原因。
    宁可退回规则 —— 规则至少是可解释的。
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    s = _FENCE_RE.sub("", s).strip()
    m = _JSON_OBJ_RE.search(s)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    q = str(obj.get("quality") or "").strip().lower()
    alias = {"原创": "original", "转载": "repost", "洗稿": "repost", "广告": "ad",
             "垃圾": "spam", "推广": "ad", "copy": "repost", "unknown": "unknown"}
    q = alias.get(q, q)
    if q not in SiteJudge.QUALITIES:
        return None
    return {"quality": q,
            "confidence": _clamp(obj.get("confidence"), 0.05, 0.95, 0.6),
            "reason": str(obj.get("reason") or "").strip()[:200]}


@dataclass
class Judgment:
    """一次判断的结论（**可解释**是它的核心字段之一）。

    字段口径：
      domain          归一后的域名（判断"哪个站"，不是"哪个 URL"）
      judged_type     判断出的类型（沿用世界模型那三张表的口径：tech_news/forum/…）
      judged_trust    判断出的可信度（类型表基准 × 质量折扣）
      judged_refresh  这个站该多久看一次（人可读 "1h"/"6h"/"7d"，沿用模型口径）
      quality         original/repost/ad/spam/unknown —— **规则或模型给的质量结论**
      user_relevance  0~1：跟用户画像/当前主题的相关度
      confidence      0~1：这条判断本身有多可信（不是站点可信度，别混）
      evidence        至少 2 条中文依据（给人看的，也是出错时唯一能追责的东西）
      by              "model" / "rules" —— 谁下的结论（模型只可能改 quality/confidence）
    """
    domain: str = ""
    judged_type: str = "unknown"
    judged_trust: float = 0.5
    judged_refresh: str = ""
    quality: str = "unknown"
    user_relevance: float = 0.0
    confidence: float = 0.0
    evidence: list = field(default_factory=list)
    by: str = "rules"

    def as_dict(self):
        "「」转成可落盘的 dict（世界模型的 `remember_judgment` 只认字段名，不看类型）。「」"
        return {"domain": self.domain, "judged_type": self.judged_type,
                "judged_trust": float(self.judged_trust),
                "judged_refresh": self.judged_refresh, "quality": self.quality,
                "user_relevance": float(self.user_relevance),
                "confidence": float(self.confidence),
                "evidence": [str(x) for x in (self.evidence or [])], "by": self.by}

    def explain(self):
        "「」一句话人话（日志/面板/自测失败信息都用它，省得每处各拼一遍）。「」"
        return "%s：类型=%s，可信度=%.2f，质量=%s，相关度=%.2f，置信度=%.2f（%s）" % (
            self.domain or "(无域名)", self.judged_type, self.judged_trust,
            self.quality, self.user_relevance, self.confidence, self.by)


class SiteJudge:
    """判断一个站/一页：什么类型、多可信、多久看一次、质量如何、跟用户有没有关系。

    `llm(prompt) -> str` 可注入（默认惰性用 app 的 `llm_chat`，拿不到就纯规则）。
    为什么要可注入：判断器必须在**没有 app 的环境**里也能跑（自测、后台进程、脚本），
    而且"模型平等"意味着这里不该写死任何一个模型的名字。
    """

    QUALITIES = ("original", "repost", "ad", "spam", "unknown")
    MIN_LLM_CHARS = 300          # 正文短于这个就不值得问模型（问也是瞎猜，还费一次推理）
    AD_HITS_TO_CALL_AD = 2       # 两处推广用语才算广告（一处可能是正常文章里的"购买"）
    STUFFING_RATIO = 0.30        # 单个 2-gram 占比超过 30% 判堆砌（正常页面通常 <15%）

    def __init__(self, llm=None, user_profile=None, model=None, allow_llm=True):
        """`llm` 不给就惰性找 app；`user_profile` 是兜底画像（judge(profile=…) 优先）。

        `model` 可选：给一个 WorldModel 就用它的话题表/画像补充相关度判断，
        但**不用它做类型/可信度**（那是规则表的事，两者绝不互换）。
        `allow_llm=False` 用于"纯规则模式"（自测、省额度的部署）。
        """
        self.llm = llm
        self.user_profile = user_profile if user_profile is not None else {}
        self.model = model
        self.allow_llm = bool(allow_llm)
        self.last_error = ""        # 最近一次模型/判断的失败原因（面板可读，绝不抛给调用方）

    # ---- 门面 ----
    def judge(self, url, content="", title="", topic="", profile=None):
        """判断一个页面，返回 `Judgment`。**任何异常都被兜成"unknown + 人话证据"**。

        为什么最外层也要兜：这个方法跑在后台探索线程里，输入是**互联网上的脏数据**
        （编码乱的 HTML、几 MB 的正文、缺字段的搜索结果）。一次未捕获的异常
        会让整轮探索白跑，而"少判一页"几乎没有任何代价。所以宁可兜底。
        """
        u = str(url or "")
        try:
            return self._judge(u, content, title, topic, profile)
        except Exception as e:      # noqa: silent-ok — 判断失败只能是 unknown，不能拖垮探索
            self.last_error = "judge 异常：%s" % str(e)[:150]
            logger.debug("SiteJudge.judge 异常：%s", e)
            return Judgment(domain=domain_of_url(u), judged_type="unknown",
                            judged_trust=float(TYPE_TRUST.get("unknown", 0.5)),
                            judged_refresh=format_interval(TYPE_REFRESH.get("unknown", 21600)) or "6h",
                            quality="unknown", user_relevance=0.0, confidence=0.05,
                            evidence=["判断过程出错（%s）→ 按最保守口径处理" % str(e)[:80],
                                      "规则表兜底：unknown 站可信度 %.2f、刷新 %s，宁可少信不可错信"
                                      % (float(TYPE_TRUST.get("unknown", 0.5)),
                                         format_interval(TYPE_REFRESH.get("unknown", 21600)) or "6h")],
                            by="rules")

    def judge_batch(self, items):
        """批量判断。`items` 支持 dict / (url,content,title[,topic]) / 字符串 URL。

        为什么宽容输入形状：候选来自多个搜索/抓取实现（app.web_search 是三元组，
        插件可能回 dict）。在多态输入上多写十行，比让每个调用点各写一遍适配便宜。
        **返回条数与输入条数一一对应**（坏条目返回保底 Judgment 而不是被跳过）：
        调用方按位置对应结果，少一条就会整体错位 —— 那种 bug 极难查。
        """
        out = []
        for it in (items or []):
            try:
                if isinstance(it, dict):
                    out.append(self.judge(it.get("url") or it.get("link") or "",
                                          it.get("content") or it.get("snippet") or it.get("text") or "",
                                          it.get("title") or "",
                                          it.get("topic") or "", it.get("profile")))
                elif isinstance(it, (list, tuple)):
                    parts = list(it)[:4] + ["", "", "", ""]
                    out.append(self.judge(parts[0], parts[1], parts[2], parts[3]))
                else:
                    out.append(self.judge(str(it or "")))
            except Exception as e:      # noqa: silent-ok — 一条坏输入不能少一条结果
                out.append(self.judge(""))
                out[-1].evidence.append("条目无法识别（%s）→ 保底 unknown 占位，保证结果与输入等长"
                                        % str(e)[:60])
        return out

    # ---- 内部：主流程 ----
    def _judge(self, url, content, title, topic, profile):
        raw = str(content or "")
        text = _plain(raw)
        head = str(title or "").strip() or _title_of(raw, text)
        dom = domain_of_url(url) or ""

        # ① 类型/可信度/刷新：**只走规则表**（可解释、可复现、换模型不变）
        jtype = infer_type_rules(url, content=raw, title=head)
        base_trust = float(TYPE_TRUST.get(jtype, TYPE_TRUST.get("unknown", 0.5)))
        refresh = format_interval(TYPE_REFRESH.get(jtype, TYPE_REFRESH.get("unknown", 21600))) or "6h"
        ev = [("域名 %s 命中类型关键词表 → %s（基准可信度 %.2f）" % (dom, jtype, base_trust))
              if jtype != "unknown" else
              ("域名 %s 在类型表里认不出来 → unknown（基准可信度 %.2f，不猜；正文/标题里有文档特征时才兜底）"
               % (dom or "(无)", base_trust))]

        # ② 质量：规则特征（广告词 / 转载标记 / 堆砌比 / 链接密度）
        quality, q_ev, clickbait = self._rule_quality(url, raw, text, head)
        ev.extend(q_ev)

        # ③ 相关度：跟画像 + 当前主题的关键词重合度
        keys = self._keywords(topic, profile, head, text)
        rel, rel_ev = self._relevance(head, text, keys)
        ev.append(rel_ev)

        # ④ 质量 → 可信度折扣（这一步必须写进 evidence：用户看到 0.25 要能知道为什么）
        trust = _clamp(base_trust, 0.0, 1.0, 0.5)
        factor = {"ad": 0.5, "spam": 0.4, "repost": 0.9, "original": 1.0, "unknown": 1.0}[quality]
        trust = round(_clamp(trust * factor, 0.0, 1.0, 0.5), 3)
        ev.append("质量=%s → 可信度 %.2f×%.1f=%.2f（%s）" % (
            quality, base_trust, factor, trust,
            {"ad": "广告页不能当权威", "spam": "堆砌页基本没有信息量", "repost": "二手转述，降一点",
             "original": "未见折扣特征，不打折", "unknown": "证据不足，按类型表原值"}[quality]))

        conf = self._confidence(jtype, text, quality, clickbait)
        by = "rules"

        # ⑤ 模型只做规则做不了的那一小块：原创 or 洗稿
        if self._should_ask_llm(text, quality):
            got = self._ask_model(url, head, text)
            if got:
                quality = got["quality"]
                conf = _clamp(max(conf, got["confidence"]), 0.05, 0.95, 0.5)
                by = "model"
                # 模型改了质量 → **可信度必须跟着重算**，否则会出现"质量=广告但可信度没打折"
                factor = {"ad": 0.5, "spam": 0.4, "repost": 0.9,
                          "original": 1.0, "unknown": 1.0}[quality]
                trust = round(_clamp(base_trust * factor, 0.0, 1.0, 0.5), 3)
                ev.append("模型复核：%s（置信 %.2f）—— %s；可信度随之重算为 %.2f"
                          % (quality, got["confidence"], got["reason"] or "未给理由", trust))
            else:
                ev.append("模型没有给出可解析的 JSON（%s）→ **回落规则**，结论不变（判断不因模型乱答而漂移）"
                          % (self.last_error or "空回复"))

        return Judgment(domain=dom, judged_type=jtype, judged_trust=trust,
                        judged_refresh=refresh, quality=quality, user_relevance=rel,
                        confidence=conf, evidence=ev[:12], by=by)

    # ---- 规则特征 ----
    def _rule_quality(self, url, raw, text, head):
        """规则判质量。返回 `(quality, [证据…], 标题党计数)`。

        判定顺序就是优先级，写在这里免得后来人以为是随手排的：
          ① 正文太短 → unknown（**不下结论**比下错结论好：短页可能是登录墙/重定向壳）
          ② 广告词命中 → ad（先于堆砌：广告页的推广语天然重复，先判堆砌会把广告叫成垃圾）
          ③ 关键词堆砌 → spam
          ④ 转载标记 → repost
          ⑤ 长且干净 → original
        为什么 ①②不能颠倒：一块"点击购买 点击购买 点击购买"的页面按堆砌判会变成 spam，
        但用户真正需要知道的是"这是广告"，两者处置不同（广告是降权+标注，垃圾是丢弃）。
        """
        L = len(text)
        ad_hits = _count_words(text, _AD_WORDS)
        repost_hits = _count_words(text, _REPOST_WORDS)
        link_n = str(raw or "").lower().count("http://") + str(raw or "").lower().count("https://")
        clickbait = sum(1 for w in _CLICKBAIT if w in text) + \
            (2 if head.count("！") + head.count("!") + head.count("？") + head.count("?") >= 2 else 0)
        ev = []
        if not text and not head:
            return "unknown", ["正文与标题都是空的（可能是登录墙/重定向壳）→ quality=unknown，不下结论"], clickbait
        if L < 80:
            return "unknown", ["正文只有 %d 字，看不出是原创还是转载 → quality=unknown（证据不足宁可不定）"
                               % L], clickbait
        if ad_hits >= self.AD_HITS_TO_CALL_AD or (ad_hits >= 1 and L < 600):
            ev.append("正文含 %d 处推广用语（点击购买/限时优惠/加微信…）→ 疑似广告" % ad_hits)
            return "ad", ev, clickbait
        gram, ratio = _stuffing_ratio(text)
        if gram and ratio >= self.STUFFING_RATIO:
            ev.append("最高频词「%s」占全部双字组的 %.0f%%（>%.0f%%）→ 关键词堆砌（SEO/机器生成页）"
                      % (gram, ratio * 100, self.STUFFING_RATIO * 100))
            return "spam", ev, clickbait
        if repost_hits:
            ev.append("正文出现 %d 处转载标记（转载请注明/本文转自/来源：）→ 二手转述，降权但仍可参考"
                      % repost_hits)
            return "repost", ev, clickbait
        if link_n >= 12 and link_n * 20 > L:
            ev.append("正文 %d 字里塞了 %d 条外链（链接/正文比异常）→ 疑似导流页，按垃圾处理" % (L, link_n))
            return "spam", ev, clickbait
        return "original", ["正文 %d 字，未见推广用语/转载标记/堆砌特征，外链 %d 条 → 判为原创"
                            % (L, link_n)], clickbait

    def _keywords(self, topic, profile, head, text):
        "「」相关度比对的**关键词集合**：主题词 + 画像词 + （有 WorldModel 时）它记的话题。「」"
        keys = []
        t = str(topic or "").strip()
        if t:
            keys.append(t)
            for w in re.split(r"[,，、;；\s/|]+", t):
                if len(w) >= 2 and w not in keys:
                    keys.append(w)
        prof = profile if profile is not None else self.user_profile
        for k in _profile_keywords(prof):
            if k not in keys:
                keys.append(k)
        if self.model is not None:
            try:
                for rec in self.model.topics(top=10):
                    n = str(rec.get("name") or "")
                    if n and n not in keys:
                        keys.append(n)
            except Exception as e:      # noqa: silent-ok — 话题表读不到只是少一路参考
                logger.debug("读话题表失败（相关度只用主题+画像）：%s", e)
        _ = head, text
        return keys[:40]

    def _relevance(self, head, text, keys):
        """相关度 0~1：标题命中权重 ×2、正文命中 ×1，再按关键词总数归一。

        为什么标题权重更高：标题是这页**自己声明的主题**，正文里顺嘴提一句不算相关。
        为什么没有关键词时给 0.5（中性）而不是 0：
          0 会被"相关度低于阈值就丢弃"的规则理解成"确定无关"，把候选全丢光；
          0.5 表示"我没法判断"，让匹对那一步自己决定（通常还有主题本身的命中）。
        """
        if not keys:
            return 0.5, "没有主题词也没有画像词可比 → 相关度取中性 0.50（不做无根据的打压）"
        head_l, text_l = str(head or "").lower(), str(text or "").lower()
        hit_head, hit_body = [], []
        for k in keys:
            kl = str(k).lower()
            if not kl:
                continue
            if kl in head_l:
                hit_head.append(k)
            elif kl in text_l:
                hit_body.append(k)
        w = 2.0 * len(hit_head) + 1.0 * len(hit_body)
        rel = _clamp(w / (2.0 * len(keys)), 0.0, 1.0, 0.0)
        shown = (hit_head + hit_body)[:3]
        return round(rel, 3), "关键词命中 %d/%d（标题 %d 个%s）→ 相关度 %.2f" % (
            len(hit_head) + len(hit_body), len(keys), len(hit_head),
            ("：" + "、".join(shown)) if shown else "，正文里一个都没提", rel)

    def _confidence(self, jtype, text, quality, clickbait):
        """判断本身的可信度（**不是站点可信度**，两回事，别混）。

        口径：类型认出来了 +0.15；正文够长 +0.1；质量有结论 +0.1；标题党 -0.05；
        只剩标题（没正文）-0.15。这样"只凭域名判断"大约 0.5~0.65，"有正文且规则干净"能到 0.85+。
        """
        c = 0.5
        if jtype != "unknown":
            c += 0.15
        if len(text) >= 200:
            c += 0.1
        if quality != "unknown":
            c += 0.1
        if clickbait >= 2:
            c -= 0.05
        if not text:
            c -= 0.15
        return round(_clamp(c, 0.05, 0.95, 0.5), 3)

    # ---- 模型（只做规则做不了的那一小块）----
    def _ask_llm(self):
        """拿到 llm 可调用对象：显式注入优先，否则惰性找 app 的 `llm_chat`。

        惰性手法与载体层其它模块一致（`sys.modules.get("xiaojiao_app")`）：
        判断器要能**独立 import**、独立运行 —— 拿不到 app 就用纯规则，绝不抛错。
        """
        if self.llm is not None:
            return self.llm
        if not self.allow_llm:
            return None
        try:
            import sys
            app = sys.modules.get("xiaojiao_app")
            if app is None:
                return None
            fn = getattr(app, "llm_chat", None)
            return fn if callable(fn) else None
        except Exception:      # noqa: silent-ok — 拿不到 app 是合法情形（离线/后台进程）
            return None

    def _should_ask_llm(self, text, quality):
        """值不值得问模型：只用**规则确实分不清**的那一小块。

        条件：允许用模型 + 正文够长（≥300 字）+ 规则结论是 original/unknown。
        why：
          · 规则已经判成 ad/spam 的页面不需要模型复核（再问一遍只是多一次推理，结论不会变好）；
          · 太短的正文模型也只能瞎猜；
          · 剩下"长且干净"的页面里，恰好藏着规则最不擅长的东西 —— **洗稿**
            （把别人的文章改几个词，转载标记全删掉）。这一小块交给模型才有价值。
        去掉这个门槛会怎样：每一条候选都要过一次推理 —— 探索 50 个站就是 50 次模型调用，
        在 4B 本地模型上等于把机器占满，而这正是"绝不超载"要防的事。
        """
        if not self.allow_llm or len(text) < self.MIN_LLM_CHARS:
            return False
        if quality not in ("original", "unknown"):
            return False
        return self._ask_llm() is not None

    def _ask_model(self, url, head, text):
        "「」问模型一个问题，只要一段 JSON。**失败/乱答一律返回 None**（调用方回落规则）。「」"
        fn = self._ask_llm()
        if fn is None:
            return None
        prompt = (
            "你是网页质量审核员。只回一个 JSON，不要任何解释、不要代码块。\n"
            "判断下面这页属于哪一类：\n"
            '  original=自己采写, repost=转载/洗稿, ad=广告, spam=垃圾/机器生成, unknown=看不出\n'
            '输出格式：{"quality":"original","confidence":0.7,"reason":"一句话理由"}\n'
            "标题：%s\n网址：%s\n正文（截断）：\n%s"
            % (str(head or "")[:200], str(url or "")[:200], str(text or "")[:1200]))
        self.last_error = ""
        raw = None
        try:
            raw = fn(prompt)
        except TypeError:
            # 有些实现只认 messages 列表（app.llm_chat 就是这种）。这里多试一次，
            # 但**只试一次**：注入点形状不一，猜太多次会掩盖真正的错误。
            try:
                raw = fn([{"role": "user", "content": prompt}])
            except Exception as e:
                self.last_error = str(e)[:150]
                return None
        except Exception as e:      # noqa: silent-ok — 模型/网络故障是常态，回落规则即可
            self.last_error = str(e)[:150]
            logger.debug("判断器问模型失败（回落规则）：%s", e)
            return None
        got = _parse_quality_json(raw)
        if got is None:
            self.last_error = "模型输出无法解析为合规 JSON"
        return got

    def __repr__(self):
        return "<SiteJudge by=%s llm=%s>" % (
            "rules+model「 if self._ask_llm() is not None else 」rules",
            "injected" if self.llm is not None else "lazy")
