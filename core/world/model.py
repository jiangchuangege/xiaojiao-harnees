# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是“模型平等”和“变形金刚”的工程基础。
# -*- coding: utf-8 -*-
"""小焦 · 世界层 · 世界模型（互联网不是工具箱，是它的世界）

为什么要有"世界模型"（而不是每次上网都从零开始）：
  小焦看一个站，看完就该**记住**这个站是干嘛的、可不可信、多久会变一次、看过几次。
  这些不属于"模型的知识" —— 那是火种的东西，换个模型就断片了；
  它们属于**载体的记忆**，所以落盘在 `logs/world/model.json`，和 `core/memory_vec` 一样是外部存储。
  去掉它：小焦每次刷新都像第一次见到那个站，可信度和刷新周期全靠模型即兴发挥，换个模型
  整个世界就"失忆"了 —— "模型平等"也就不成立了。

结构（主线会读它，字段名不能改）：
  sites     域名 → {type, trust, refresh, first_seen, last_seen, hits, title, note}
  relations [{from, to, kind}]     站点/主题之间的关系（"36kr.com → tech"）
  updated   最后写入时间戳

为什么可信度是**表**、而不是让模型打分：
  让模型给一个站打 0.83 分，换个模型分数就变了 —— 那就不是"世界"，是"模型的印象"。
  表是**可解释、可复现、可审计**的：wiki/repo/api/docs=0.8、tech_news=0.7、
  forum/social=0.5、shop=0.4。用户看到 0.4 就知道"这是商城，别当权威"。
  去掉表：可信度会变成随机数，用户没法质疑一个数字，也就没法纠错。

两处默认口径（写清楚免得后来人以为是 bug）：
  · `trust_of` / `type_of`：**完全不认识**的站 → 返回调用方给的 default（出厂 0.5 / "unknown"）。
    不认识就是半信半疑，这是最诚实的表述。
  · `refresh_interval`：不认识的站按类型表走（unknown=6h），只有"连类型都算不出来"才落到 default。
    为什么这里要**更长**而不是更短：不认识的站抓得越勤越像攻击、也越容易打扰别人；
    6 小时是"持续观察"能接受的代价。它恰好等于表里的 unknown 项，所以不是两套标准。
"""
import copy
import json
import logging
import math
import os
import re
import threading
import time
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

# 仓库根 = 本文件的上三级（core/world/model.py → core/world → core → 根）
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORLD_DIR = os.path.join(_ROOT, "logs", "world")
MODEL_PATH = os.path.join(WORLD_DIR, "model.json")

# ===== 判断器要落盘的 8 个字段（**新增**，与原有的 type/trust/refresh 并存）=====
# 为什么并存而不是覆盖：原有三个字段是"世界模型的总账"（类型表推出来的、可解释、可审计），
# 判断器的结论是"这一页在这一刻长什么样"（带质量、相关度、置信度和证据）。
# 两者口径不同、生命周期也不同（总账长期稳定、单页结论会被下一次判断刷新）。
# 合并成一组的后果：一次广告页判断就会把整个站的可信度永久改掉，用户再也没法追问"凭什么"。
JUDGED_KEYS = ("judged_type", "judged_trust", "judged_refresh", "quality",
               "user_relevance", "confidence", "evidence", "by")

# ===== 除 sites/relations/updated 之外的**新增顶层段**：段名 → 合法类型 =====
# 为什么要有这张表并在 reload 里带回来：读盘时只挑 sites/relations，
# 会把用户攒下的话题表（topics）和画像（user_profile）在每次启动时**悄悄清掉** ——
# 那等于丢数据，而丢数据比崩溃更糟（用户根本不知道丢了）。
# 旧代码只读 sites/relations，多带两个段对它们毫无影响，所以这是纯增量。
_EXTRA_SEGMENTS = {"topics": dict, "user_profile": dict}

# ===== 站点类型 → 默认可信度（可解释的表，不是模型打分）=====
TYPE_TRUST = {
    "wiki": 0.8,        # 百科：多人复核，但可能过时
    "repo": 0.8,        # 代码仓库：一手事实
    "api": 0.8,         # 厂商官方 API/文档：一手事实
    "docs": 0.8,        # 文档站：一手事实
    "tech_news": 0.7,   # 科技媒体：快，但会有二手转述
    "forum": 0.5,       # 论坛：有真知也有噪音
    "social": 0.5,      # 社交：观点多、事实少
    "shop": 0.4,        # 商城：文案是卖货的
    "unknown": 0.5,     # 不认识：半信半疑
}

# ===== 站点类型 → 默认刷新周期（秒）=====
# 语义上这是"这个站多久可能变一次"，决定"持续观察"的节奏。
TYPE_REFRESH = {
    "social": 30 * 60,          # 30m：社交分钟级就翻篇
    "tech_news": 60 * 60,       # 1h：新闻一小时够勤了
    "unknown": 6 * 60 * 60,     # 6h：不认识的站别频繁打扰
    "forum": 6 * 60 * 60,       # 6h：论坛话题半天一变
    "repo": 24 * 60 * 60,       # 1d：仓库/文档一天一遍足够
    "docs": 24 * 60 * 60,
    "shop": 24 * 60 * 60,       # 1d：价格一天看一次
    "api": 24 * 60 * 60,
    "wiki": 7 * 24 * 60 * 60,   # 7d：百科很少动
}

# ===== 域名关键词表（**规则可解释**：命中哪个词就归哪类，不猜）=====
# 顺序 = 优先级（先匹配到的赢），所以：
#   · forum 里放 "news.ycombinator"（多段关键词）→ 它必须赢过 tech_news 里的 "news"；
#   · api 里的**具体厂商**放在 docs 前面 → "api.openai.com" 该算 api，而不是被 "api" 泛词归成 docs；
#   · repo 放在 docs/api 之前 → "api.github.com" 该算 repo（它本质是 GitHub）；
#   · tech_news 放最后 → "news" 这个词太泛，让具体的先说话。
DOMAIN_RULES = (
    ("forum", ("zhihu", "v2ex", "reddit", "news.ycombinator", "douban", "tieba", "discourse")),
    ("social", ("weibo", "twitter", "x.com", "facebook", "instagram", "tiktok", "mastodon")),
    ("repo", ("github", "gitlab", "pypi", "npm", "gitee", "crates.io", "huggingface")),
    ("api", ("openai", "anthropic", "cloudflare", "googleapis", "azure", "aws.amazon")),
    ("docs", ("docs", "developer", "api")),          # spec：docs/developer/api → docs
    ("wiki", ("wiki", "baike")),
    # shop 里补上 "shop/mall/store" 这类**通用词**：spec 只列了 taobao/jd/amazon，
    # 但真实世界里 shop.example.com 这种域名一眼就是商城，认成 unknown 会白丢一条可信度信息。
    # 代价：shopify.com 这类"卖商城系统的站"也会被归进 shop（0.4）—— 偏保守，可以接受。
    ("shop", ("taobao", "jd", "amazon", "tmall", "pinduoduo", "etsy", "shop", "mall", "store")),
    ("tech_news", ("news", "36kr", "hackernews", "techcrunch", "theverge", "ithome", "sspai")),
)

# ===== 正文/标题特征（域名认不出来时的兜底）=====
# 为什么需要兜底：新站、小站、IDN 域名都不在关键词表里，光靠域名只能判 unknown。
# 标题是站方自己写的"我是谁"，比域名可信；去掉它，一半的真实站点都会掉进 unknown。
_TITLE_RULES = (
    ("repo", ("源码", "仓库", "开源项目", "repository", "source code")),
    ("docs", ("文档", "手册", "指南", "教程", "documentation", "api reference", "developer")),
    ("forum", ("论坛", "社区", "讨论区", "问答", "帖子", "bbs")),
    ("wiki", ("百科", "维基", "wiki")),
    ("shop", ("商城", "购物", "旗舰店", "加入购物车", "价格", "购买")),
    ("social", ("微博", "推文", "朋友圈", "tweet")),
    ("tech_news", ("新闻", "快讯", "日报", "晚报", "资讯", "头条", "breaking")),
)

# 正文里的"文档味"用词。密度判定要**同时**看绝对条数与占比：
# 只看条数，长页面随便提两句 "API" 就被误判；只看占比，短页面又会抖动。
_DOC_WORDS = ("documentation", "documented", "api reference", "开发者文档", "接口文档")
_API_MARKS = ("api/", "/api", "api.")

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_MD_TITLE_RE = re.compile(r"^\s{0,3}#{1,3}\s+(.+?)\s*$", re.M)
_INTERVAL_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhd]|sec|secs|min|mins|hour|hours|day|days|秒|分|小时|天)?\s*$", re.I)
_INTERVAL_UNIT = {"s": 1, "sec": 1, "secs": 1, "秒": 1,
                  "m": 60, "min": 60, "mins": 60, "分": 60,
                  "h": 3600, "hour": 3600, "hours": 3600, "小时": 3600,
                  "d": 86400, "day": 86400, "days": 86400, "天": 86400}


# ------------------------------------------------------------------ 小工具
def parse_interval(text, default=0):
    """把 "1h" / "30m" / "2d" / "3600s" / 600 / "1.5h" 解析成秒。

    为什么要一个解析器：世界模型是**人可读的文件**（refresh: "1h" 一眼就懂），
    但调度要的是秒。把"可读"和"可算"分开，用户就能直接改文件调观察节奏。
    解析不了返回 default（调用方自己决定兜底），绝不抛错 —— 一个字段写错不该让整个调度挂掉。
    """
    if text is None:
        return default
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return int(text) if float(text) > 0 else default
    m = _INTERVAL_RE.match(str(text))
    if not m:
        return default
    try:
        num = float(m.group(1))
    except Exception:
        return default
    unit = (m.group(2) or "s").lower()
    sec = num * _INTERVAL_UNIT.get(unit, 1)
    return int(sec) if sec > 0 else default


def format_interval(seconds):
    "「」秒 → 人可读的 「1h」/「30m」/「1d」（写回模型文件用，方便用户直接改）。「」"
    try:
        sec = int(seconds)
    except Exception:
        return ""
    if sec <= 0:
        return ""
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if sec % size == 0:
            return "%d%s" % (sec // size, unit)
    return "%ds" % sec


def _clamp01(x, default=0.5):
    """可信度一律夹到 [0,1]；坏值（None/"abc"/NaN）退回默认值，不抛错。

    为什么用 math.isnan 而不是 `v != v`：那个写法虽然对，但读代码的人第一眼会以为
    是打错了（自检工具也会把它报成"拿自己跟自己比"）。一个会被误读的技巧不值得省一次 import。
    """
    try:
        v = float(x)
    except Exception:
        return float(default)
    if math.isnan(v):              # NaN 会污染排序和平均（NaN 参与的比较全是 False）
        return float(default)
    return max(0.0, min(1.0, v))


def _domain_hit(dom, key):
    """域名是否命中某个关键词（**按标签匹配**，不做无脑子串）。

    为什么不能 `key in dom`：短词会疯狂误伤 —— "jd" 会命中 "jdownloader.com"，
    "x.com" 会命中 "v2ex.com"（子串！）。所以：
      · 带点的关键词（x.com / news.ycombinator / crates.io）只认"整域相等或整段后缀/前缀"；
      · 不带点的按 DNS 标签比：标签等于关键词（jd.com 的 jd），
        或者标签以关键词开头且关键词 ≥3 字符（npmjs.com 的 npm、wikipedia.org 的 wiki）。
    去掉这层约束：分类会变成一堆莫名其妙的结果，而且没法解释给用户听。
    """
    dom = (dom or "").lower().strip(".")
    key = (key or "").lower()
    if not dom or not key:
        return False
    if "." in key:
        return dom == key or dom.endswith("." + key) or dom.startswith(key + ".")
    for label in dom.split("."):
        if label == key:
            return True
        if len(key) >= 3 and len(label) > len(key) and label.startswith(key):
            return True
    return False


def _text_title(text):
    "「」从 HTML / Markdown 里抠标题（HTML 优先，其次一级标题）。抠不到返回 「」。「」"
    t = str(text or "")
    m = _TITLE_RE.search(t)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()[:200]
    m = _MD_TITLE_RE.search(t)
    return (m.group(1).strip()[:200] if m else "")


def domain_of_url(url):
    """取主机名：去 www. / 去端口 / 小写；**非法输入返回 ""**（模块级函数）。

    为什么要有模块级版本：`WorldModel.domain_of` 是给人用的门面，
    但有些地方（关系图节点归一、类型推断）只需要"把 URL 拆成域名"这一件事 ——
    那里**不应该**为了一个纯字符串运算去构造一个 WorldModel（那会顺带读一次磁盘，
    在后台线程里还可能和写盘抢文件）。宁可多一层转发，也不要一个会读盘的"纯函数"。
    """
    s = str(url or "").strip()
    if not s:
        return ""
    host = ""
    try:
        if "://" in s:
            host = urlsplit(s).hostname or ""       # hostname 自带小写、去端口、去 user:pass
        else:
            s2 = s.split("/")[0].split("?")[0].split("#")[0]
            if "@" in s2:
                s2 = s2.rsplit("@", 1)[1]
            if s2.startswith("["):                  # IPv6 字面量
                host = s2.split("]")[0].lstrip("[")
            else:
                host = s2.split(":")[0]
    except Exception:      # noqa: silent-ok — 畸形 URL（坏端口等）当非法，返回 "" 由调用方兜底
        return ""
    host = (host or "").strip().strip(".").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host or any(c in host for c in " \t\r\n/\\?#"):
        return ""
    # "hello"/"某个词" 不是域名（没有点）。但 IPv6 字面量（::1）和 localhost 是合法主机，放行。
    if "." not in host and ":" not in host and host != "localhost":
        return ""
    if not re.match(r"^[a-z0-9._\-\[\]:]+$", host):
        return ""
    return host


def _node_of(name):
    "「」关系图里的节点名：是域名/URL 就归一，否则当普通主题词（小写、空格换下划线）。「」"
    s = str(name or "").strip()
    if not s:
        return ""
    d = domain_of_url(s)
    if d:
        return d
    return re.sub(r"\s+", "_", s.lower())


# ------------------------------------------------------------------ 世界模型
class WorldModel:
    """脑子里的地图：这个站是干嘛的、可不可信、多久刷新一次、看过几次。

    线程安全口径：**内存里的 dict 不做细粒度加锁**（读多写少、单个写操作是原子的），
    但 `save()` 用一把锁 + 原子替换（写临时文件再 os.replace）——
    因为"持续观察"跑在后台线程里，和主线程同时写同一个 model.json，
    不加锁会写出半截 JSON，下次启动就是"世界损坏"。
    """

    def __init__(self, path=None):
        self.path = path or MODEL_PATH
        self._lock = threading.RLock()
        self.data = {"sites": {}, "relations": [], "updated": 0.0}
        self.bad_path = ""          # 上次读到的坏文件被备份到哪了（自愈证据，自检/面板可读）
        self.reload()

    # ---- 便捷视图（永远保证这两个键存在，调用方不必 setdefault）----
    @property
    def sites(self):
        return self.data.setdefault("sites", {})

    @property
    def relations(self):
        return self.data.setdefault("relations", [])

    # ---- 读盘 / 写盘 ----
    def reload(self):
        """从磁盘读回世界模型；**文件损坏时当空模型**，并把坏文件另存为 `.bad`。

        为什么必须自愈而不是抛错：世界模型的写入方是后台"持续观察"线程，
        断电/强杀时留下半截 JSON 完全可能。如果这时直接抛错，
        整个感知层就起不来 —— 而"互联网是它的世界"这件事不该因为一个坏文件停摆。
        为什么还要备份 `.bad`：别把用户的旧数据悄悄抹掉，留一份原文（连坏数据一起），
        用户/开发者才有机会看清"当时到底写坏了什么"。
        """
        raw = ""
        try:
            if not os.path.exists(self.path):
                with self._lock:
                    self.data = {"sites": {}, "relations": [], "updated": 0.0}
                return self
            with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                raw = f.read()
            obj = json.loads(raw) if raw.strip() else {}
            if not isinstance(obj, dict):
                raise ValueError("顶层不是 JSON 对象")
            data = {"sites": {}, "relations": [], "updated": 0.0}
            sites = obj.get("sites") or {}
            if isinstance(sites, dict):
                for dom, rec in sites.items():
                    if isinstance(rec, dict):
                        data["sites"][str(dom)] = copy.deepcopy(rec)
            rels = obj.get("relations") or []
            if isinstance(rels, list):
                data["relations"] = [copy.deepcopy(r) for r in rels if isinstance(r, dict)]
            try:
                data["updated"] = float(obj.get("updated") or 0.0)
            except Exception:
                data["updated"] = 0.0
            # 新增顶层段原样带回（类型不对就当没有；旧代码不认它们，也不会被它们影响）
            for extra, kind in _EXTRA_SEGMENTS.items():
                v = obj.get(extra)
                if isinstance(v, kind):
                    data[extra] = copy.deepcopy(v)
            with self._lock:
                self.data = data
            return self
        except Exception as e:
            logger.warning("世界模型损坏，按空模型继续（原文已另存 .bad）：%s", e)
            self._backup_bad(raw)
            with self._lock:
                self.data = {"sites": {}, "relations": [], "updated": 0.0}
            self.save()             # 立刻写回一个干净的空模型，下次启动就正常了
            return self

    def _backup_bad(self, raw):
        "「」把坏文件另存为 `<path>.bad`（已存在就 .bad.1/.bad.2…，**绝不删任何文件**）。「」"
        target = self.path + ".bad"
        n = 0
        while os.path.exists(target) and n < 1000:
            n += 1
            target = "%s.bad.%d" % (self.path, n)
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.path)) or ".", exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                f.write(raw if raw is not None else "")
            self.bad_path = target
        except Exception as e:      # noqa: silent-ok — 备份失败也要让程序继续（空模型已经够用了）
            logger.debug("备份坏模型失败：%s", e)
            self.bad_path = ""
        return self.bad_path

    def save(self):
        """原子写盘：先写 `.tmp` 再 `os.replace`。

        为什么不能直接 open(path,"w")：写到一半被强杀，磁盘上就是半截 JSON，
        下次启动要自愈一次（见 reload）。原子替换让"文件永远是完整的"，
        后台线程和主线程同时写也不会互相撕。写失败只记日志并返回 False，绝不抛错。
        """
        with self._lock:
            self.data["updated"] = time.time()
            try:
                d = os.path.dirname(os.path.abspath(self.path)) or "."
                os.makedirs(d, exist_ok=True)
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, ensure_ascii=False, indent=1)
                os.replace(tmp, self.path)
                return self.path
            except Exception as e:      # noqa: silent-ok — 存不下就下次再存，不能因此中断感知
                logger.warning("世界模型存盘失败：%s", e)
                return False

    # ---- 域名归一 ----
    def domain_of(self, url):
        """取主机名：去 www. / 去端口 / 小写；**非法输入返回 ""**（薄门面，实现在 domain_of_url）。

        为什么要归一：同一台机器有无数种写法（http://WWW.Example.COM:8080/a?b=1、example.com、
        https://example.com/x），世界模型必须把它们认成**同一个站**，
        否则 hits 分散、可信度各说各话。去掉它：观察次数永远统计不准。
        """
        return domain_of_url(url)

    def _key(self, url_or_domain):
        "「」统一入口：URL 或域名 → sites 的键（归一后的域名）。「」"
        return domain_of_url(url_or_domain)

    @staticmethod
    def _node(name):
        "「」关系图里的节点名（薄门面，实现在 _node_of）。「」"
        return _node_of(name)

    # ---- 站点记忆 ----
    def remember_site(self, url_or_domain, type="", trust=None, refresh="", title="", note=""):
        """记住/更新一个站（返回落盘的那条记录）。

        合并规则：**不拿空值盖掉已有的非空值**。
        为什么：`remember_site(u)` 往往只带着一个标题就被调用（快照时顺手记一笔），
        如果它把上次好不容易推断出的 type/trust 覆盖成空，世界模型就会一直"失忆"。
        返回记录（而不是 True/False），调用方可以立刻读 hits/trust 做决策。
        """
        dom = self._key(url_or_domain)
        if not dom:
            logger.debug("remember_site 收到非法站点：%r", url_or_domain)
            return {}
        now = time.time()
        with self._lock:
            rec = self.sites.get(dom)
            if not isinstance(rec, dict):
                rec = {}
            first = rec.get("first_seen") or now
            new_type = str(type or "").strip() or str(rec.get("type") or "").strip() \
                or self.infer_type(url_or_domain, title=title)
            if trust is None:
                new_trust = _clamp01(rec.get("trust"), TYPE_TRUST.get(new_type, 0.5))
            else:
                new_trust = _clamp01(trust, TYPE_TRUST.get(new_type, 0.5))
            new_refresh = str(refresh or "").strip() or str(rec.get("refresh") or "").strip() \
                or format_interval(TYPE_REFRESH.get(new_type, 0)) or ""
            rec.update({
                "type": new_type,
                "trust": round(float(new_trust), 3),
                "refresh": new_refresh,
                "first_seen": float(first),
                "last_seen": float(rec.get("last_seen") or now),
                "hits": int(rec.get("hits") or 0),
                "title": str(title or "").strip() or str(rec.get("title") or ""),
                "note": str(note or "").strip() or str(rec.get("note") or ""),
            })
            self.sites[dom] = rec
        self.save()
        return copy.deepcopy(rec)

    def mark_seen(self, url_or_domain, status=None, chars=None):
        """标记"刚看过一次"：last_seen=now、hits+1。抓取**失败也要记**。

        为什么失败也记：不记的话，一个坏站会在每轮观察里被无限重试
        （看起来就是"逮着一个死站猛砸"）。记下来，周期（refresh_interval）自然会退避它。

        注意：status/chars **不写进 sites 记录**（世界模型的字段是固定的 9 个，
        状态/正文量属于"快照"信息，存在 snapshots.jsonl 里）——
        这里把它们随返回值交回调用方，模型文件保持干净、不膨胀。
        """
        dom = self._key(url_or_domain)
        if not dom:
            return {}
        now = time.time()
        with self._lock:
            rec = self.sites.get(dom)
            if not isinstance(rec, dict):
                rec = {"type": "unknown", "trust": TYPE_TRUST["unknown"], "refresh": "",
                       "first_seen": now, "last_seen": now, "hits": 0, "title": "", "note": ""}
            rec["last_seen"] = now
            rec["hits"] = int(rec.get("hits") or 0) + 1
            self.sites[dom] = rec
        self.save()
        return {"domain": dom, "hits": int(rec["hits"]), "last_seen": rec["last_seen"],
                "status": status, "chars": chars}

    def trust_of(self, url_or_domain, default=0.5):
        "「」这个站可信度多少（0~1）。记录里的显式值优先，否则按类型表，不认识给 default。「」"
        dom = self._key(url_or_domain)
        rec = self.sites.get(dom) if dom else None
        if isinstance(rec, dict) and rec.get("trust") is not None:
            return _clamp01(rec.get("trust"), float(default))
        t = (rec or {}).get("type") if isinstance(rec, dict) else ""
        t = str(t or "").strip() or self.infer_type(url_or_domain)
        if t and t != "unknown" and t in TYPE_TRUST:
            return float(TYPE_TRUST[t])
        return _clamp01(default, 0.5)

    def refresh_interval(self, url_or_domain, default=3600):
        """这个站多久该看一次（秒）：记录里的 refresh 优先，其次类型表，最后 default。

        `"1h"/"30m"/"2d"/"3600s"` 都由 parse_interval 解析。
        """
        dom = self._key(url_or_domain)
        rec = self.sites.get(dom) if dom else None
        if isinstance(rec, dict):
            sec = parse_interval(rec.get("refresh"), 0)
            if sec > 0:
                return int(sec)
        t = (rec or {}).get("type") if isinstance(rec, dict) else ""
        t = str(t or "").strip() or self.infer_type(url_or_domain)
        sec = TYPE_REFRESH.get(t or "unknown")
        if sec:
            return int(sec)
        try:
            return int(default)
        except Exception:
            return 3600

    def type_of(self, url_or_domain, default="unknown"):
        "「」这个站属于哪一类。记录优先 → 域名规则 → 标题/正文 → 还不认识就给 default。「」"
        dom = self._key(url_or_domain)
        rec = self.sites.get(dom) if dom else None
        if isinstance(rec, dict) and str(rec.get("type") or "").strip():
            return str(rec["type"]).strip()
        t = self.infer_type(url_or_domain)
        return default if t == "unknown" else t

    def due(self, now=None, default_interval=3600):
        """**到期该刷新的域名**（"持续观察"的驱动）—— 最久没看的排前面。

        为什么需要它：观察不能"用户问才看"（那就退回工具箱了），也不能无脑轮询
        （那是 DDoS）。到期表就是这两者之间那条线：每个站按自己的节奏刷新。
        去掉它：要么不动，要么把整个互联网当成一个节奏看 —— 两种都不对。
        """
        now = time.time() if now is None else float(now)
        out = []
        with self._lock:
            items = list(self.sites.items())
        for dom, rec in items:
            if not isinstance(rec, dict):
                continue
            sec = parse_interval(rec.get("refresh"), 0) \
                or TYPE_REFRESH.get(str(rec.get("type") or "unknown")) or int(default_interval)
            last = rec.get("last_seen") or rec.get("first_seen") or 0
            try:
                last = float(last)
            except Exception:
                last = 0.0
            if now - last >= sec:
                out.append((last, dom))
        out.sort()                       # 最久没看的排最前（观察顺序才合理）
        return [d for _t, d in out]

    def should_refresh(self, url_or_domain, last_check=None, now=None):
        """这一个站现在该不该抓？`last_check` 不给就查世界模型里的 last_seen。

        从没看过 → True（第一次必须看）。
        `last_check` 参数的意义：感知层知道"上一次**成功**抓取"的真实时间
        （快照日志里的 ts），比模型里的 last_seen 更准（last_seen 失败也更新）。
        """
        now = time.time() if now is None else float(now)
        dom = self._key(url_or_domain)
        if last_check is None:
            rec = self.sites.get(dom) if dom else None
            last_check = (rec or {}).get("last_seen") if isinstance(rec, dict) else None
        try:
            last = float(last_check) if last_check else 0.0
        except Exception:
            last = 0.0
        if last <= 0:
            return True
        return (now - last) >= self.refresh_interval(url_or_domain)

    def add_relation(self, a, b, kind="related"):
        """加一条关系（from a → to b）。已存在返回 False。

        为什么关系要单独存：站点分类只是一维标签，而世界是有结构的
        （"36kr.com 属于 tech 话题"、"a 站转载 b 站"）。有结构才能推理，
        比如汇聚同一话题的多个来源做交叉验证。去掉它：世界模型退化成一张"域名→分数"的清单。
        自反关系（a→a）直接拒绝：它没有任何信息量，只会污染图。
        """
        na, nb = self._node(a), self._node(b)
        if not na or not nb or na == nb:
            return False
        kind = str(kind or "related").strip() or "related"
        with self._lock:
            for r in self.relations:
                if r.get("from") == na and r.get("to") == nb and r.get("kind") == kind:
                    return False
            self.relations.append({"from": na, "to": nb, "kind": kind})
        self.save()
        return True

    def relations_of(self, node, kind=None):
        "「」这个节点（域名或主题词）的关系，双向都算。「」"
        n = self._node(node)
        if not n:
            return []
        with self._lock:
            out = [copy.deepcopy(r) for r in self.relations
                   if (r.get("from") == n or r.get("to") == n)
                   and (kind is None or r.get("kind") == kind)]
        return out

    def snapshot(self):
        "「」当前世界的**只读快照**（深拷贝）—— 给面板/自检看，改它不会动到真身。「」"
        with self._lock:
            return copy.deepcopy(self.data)

    def stats(self):
        "「」一眼看清世界有多大：站点数、关系数、按类型分布、平均可信度。「」"
        with self._lock:
            sites = list(self.sites.values())
            rels = len(self.relations)
        by_type = {}
        trusts = []
        for rec in sites:
            if not isinstance(rec, dict):
                continue
            t = str(rec.get("type") or "unknown")
            by_type[t] = by_type.get(t, 0) + 1
            try:
                trusts.append(float(rec.get("trust")))
            except Exception:
                pass
        avg = round(sum(trusts) / len(trusts), 3) if trusts else 0.0
        return {"sites": len(sites), "relations": rels, "by_type": by_type, "avg_trust": avg}

    # ---- 类型推断（规则可解释）----
    def infer_type(self, url, content="", title=""):
        """判断一个站/页面是什么类型：**域名关键词 → 正文特征 → unknown**。

        为什么坚持规则可解释（而不是丢给模型分类）：分类结果直接决定"可信度多少、
        多久刷新一次"，用户必须能追问"为什么给我 0.4"。
        规则能回答："因为域名里有 jd，是商城。" 模型打分回答不了。
        去掉正文兜底：新站/小站全掉进 unknown，观察节奏和可信度都会退化成出厂值。
        """
        try:
            dom = self.domain_of(url)
            raw = str(url or "").strip().lower()
            probe = dom or raw
            for t, keys in DOMAIN_RULES:
                for k in keys:
                    if _domain_hit(probe, k):
                        return t
            # 域名认不出来 → 看站方自己写的标题（比域名诚实）
            head = str(title or "").strip() or _text_title(content)
            if head:
                low = head.lower()
                for t, words in _TITLE_RULES:
                    for w in words:
                        if w in low:
                            return t
            # 再看正文密度（文档站最明显的特征就是满页 documentation / api 路径）
            hint = self._content_hint(content)
            if hint:
                return hint
        except Exception as e:      # noqa: silent-ok — 推断失败只能是 unknown，绝不能因此中断抓取
            logger.debug("infer_type 异常（当 unknown）：%s", e)
        return "unknown"

    @staticmethod
    def _content_hint(content):
        "「」正文特征 → 类型（目前只判文档站）。「」"
        low = str(content or "").lower()
        n = len(low)
        if n < 120:
            return ""
        doc = sum(low.count(w) for w in _DOC_WORDS)
        api = sum(low.count(w) for w in _API_MARKS)
        if doc >= 2 and doc / n >= 0.0005:
            return "docs"
        if api >= 3 and api / n >= 0.001:
            return "docs"           # spec：api → docs
        return ""

    # ---- 人看的 ----
    def describe(self, url_or_domain):
        "「」一句话说清「我怎么看这个站」（给模型/用户看的可解释摘要）。「」"
        dom = self._key(url_or_domain) or str(url_or_domain or "")
        rec = self.sites.get(dom) or {}
        return "%s：类型=%s，可信度=%.2f，刷新=%s，看过 %d 次" % (
            dom or "(非法站点)", rec.get("type") or "unknown", self.trust_of(url_or_domain),
            rec.get("refresh") or format_interval(self.refresh_interval(url_or_domain)),
            int(rec.get("hits") or 0))

    # ================= 以下为**纯增量**：判断器结论 / 话题表 / 画像 / 降权 =================
    # 这一节只**新增**方法和**新增**字段，既不改上面任何方法的签名，也不改它们的行为：
    # 旧代码继续按 sites/relations 读（`remember_site` / `trust_of` / `due`… 一字未动），
    # 新增的东西全部落在**新的字段**和**新的顶层段**上，两边互不覆盖。

    @staticmethod
    def _judgment_fields(judgment):
        """把判断结果（dataclass / dict / 任意带属性的对象）归一成要落盘的 8 个字段。

        为什么要有归一这一步：判断器返回的是 `Judgment` 数据类，但世界模型不该 import 判断器
        （那会让"记忆"依赖"判断"，将来换个判断器就得改记忆层）。所以这里只认**字段名**，
        不看类型；坏值一律夹到合法区间，绝不抛错。
        去掉它：每个调用点都得自己翻译一遍，早晚出现"某处落了 confidence 但忘了 evidence"。
        """
        if judgment is None:
            return {}
        out = {}
        for k in JUDGED_KEYS:
            if isinstance(judgment, dict):
                v = judgment.get(k)
            else:
                v = getattr(judgment, k, None)
            if v is None:
                continue
            if k in ("judged_trust", "user_relevance", "confidence"):
                out[k] = round(_clamp01(v, 0.0), 3)
            elif k == "evidence":
                if isinstance(v, str):
                    v = [v] if v.strip() else []
                if isinstance(v, (list, tuple)):
                    out[k] = [str(x)[:300] for x in v if str(x).strip()][:12]
                continue
            else:
                out[k] = str(v).strip()
        return out

    def remember_judgment(self, url_or_domain, judgment):
        """把判断器对某个站的结论写进条目（**新增字段**，`type/trust/refresh` 一字不动）。

        为什么必须并存：`type/trust/refresh` 是"世界模型的总账"（类型表推出来的、可解释、长期稳定），
        `judged_*` 是"判断器这一次看下来的结论"（带质量、相关度、置信度、证据、判定人）。
        用户追问"你为什么说这个站不可信"时，两个口径都要在：总账回答类型，判断回答这一页。
        自反地覆盖总账的后果：一次广告页判断就把整站永久降权，而下次看到正常页又升回去 ——
        数字来回跳，用户看到的不是"世界"，是"噪音"。
        `last_judged` 单独记时间（不看传入值）：它是"这条结论多新"的唯一凭据，verifier 回看要用。
        站点不存在时先补一条最小条目（经 remember_site），否则"判断"会落在一个没有骨架的记录上。
        """
        dom = self._key(url_or_domain)
        if not dom:
            logger.debug("remember_judgment 收到非法站点：%r", url_or_domain)
            return {}
        fields = self._judgment_fields(judgment)
        if not fields:
            return {}
        self.remember_site(url_or_domain)      # 保证条目存在（已存在时它会保留原有字段）
        now = time.time()
        with self._lock:
            rec = self.sites.get(dom)
            if not isinstance(rec, dict):
                rec = {}
            rec.update(fields)
            rec["last_judged"] = now
            self.sites[dom] = rec
        self.save()
        return copy.deepcopy(rec)

    def judgment_of(self, url_or_domain):
        """读回判断器的结论（含 `domain` 与 `last_judged`）；没有判断过就返回 `{}`。

        为什么返回空 dict 而不是默认值：**"没判断过"和"判断成 unknown"是两件不同的事**。
        给默认值(0.5/unknown)会让调用方以为"判过了、结论是不可信"，
        于是永远不去判第一次。空 dict 逼调用方显式处理"还没判过"。
        """
        dom = self._key(url_or_domain)
        rec = self.sites.get(dom) if dom else None
        if not isinstance(rec, dict):
            return {}
        out = {"domain": dom}
        for k in JUDGED_KEYS:
            if k in rec:
                out[k] = copy.deepcopy(rec[k])
        if "last_judged" in rec:
            out["last_judged"] = rec["last_judged"]
        return out if len(out) > 1 else {}

    # ---- 话题表（新增顶层段 topics）----
    def remember_topic(self, name, weight=1.0, source=""):
        """记住一个"值得持续看"的话题。返回落盘的那条记录（非法名字返回 `{}`）。

        `weight` 的口径是 **max 而不是累加**：累加会让"某一轮恰好重复提到"把话题顶到榜首，
        而 max 表达的是"这个话题最高被看重到什么程度"，反复看到只增加 hits（出现次数），
        两者分开记，排序才有意义（weight 是重要性，hits 是热度）。
        去掉 source：将来没法回答"这个话题是谁带进来的"（对话历史 / 搜索引擎 / 某个站）。
        """
        n = str(name or "").strip()
        if not n:
            return {}
        try:
            w = float(weight)
        except Exception:
            w = 1.0
        if math.isnan(w):          # NaN 参与排序全是 False → 话题会随机漂移，宁可退回默认
            w = 1.0
        w = max(0.0, min(100.0, w))
        now = time.time()
        src = str(source or "").strip()
        with self._lock:
            table = self.data.setdefault("topics", {})
            if not isinstance(table, dict):
                table = {}
                self.data["topics"] = table
            rec = table.get(n)
            if not isinstance(rec, dict):
                rec = {"weight": w, "source": src, "hits": 0,
                       "first_seen": now, "last_seen": now}
            try:
                old_w = float(rec.get("weight") or 0.0)
            except Exception:
                old_w = 0.0
            rec["weight"] = max(old_w, w)
            rec["hits"] = int(rec.get("hits") or 0) + 1
            rec["last_seen"] = now
            rec["first_seen"] = float(rec.get("first_seen") or now)
            rec["source"] = src or str(rec.get("source") or "")
            table[n] = rec
        self.save()
        return copy.deepcopy(rec)

    def topics(self, top=10):
        """按重要性排的话题表：`[{"name","weight","source","hits","first_seen","last_seen"}]`。

        排序口径写死：weight 降序 → hits 降序 → 名字升序（最后一项是为了让输出**可复现**：
        同分话题在不同进程里顺序一致，自测和面板才不会"每次跑都不一样"）。
        `top<=0` 表示"全都要"。读不到就返回 []，绝不抛错。
        """
        with self._lock:
            table = self.data.get("topics")
            if not isinstance(table, dict):
                return []
            items = [(str(k), dict(v)) for k, v in table.items() if isinstance(v, dict)]
        out = [{"name": n,
                "weight": round(float(r.get("weight") or 0.0), 3),
                "source": str(r.get("source") or ""),
                "hits": int(r.get("hits") or 0),
                "first_seen": float(r.get("first_seen") or 0.0),
                "last_seen": float(r.get("last_seen") or 0.0)}
               for n, r in items]
        out.sort(key=lambda d: (-d["weight"], -d["hits"], d["name"]))
        try:
            t = int(top)
        except Exception:
            t = 10
        return out if t <= 0 else out[:t]

    # ---- 用户画像（新增顶层段 user_profile）----
    def set_user_profile(self, profile):
        """合并写入用户画像（dict）。非 dict 一律忽略并返回当前画像，绝不抛错。

        为什么是**合并**而不是整体替换：画像会有多个写入方（对话里刮到的偏好、面板上的设置、
        探索器自己总结的兴趣）。整体替换的结果是"后写的那个把别人的都盖掉了"。
        为什么只认 dict：画像必须能被逐字段解释（关键词、兴趣、语言偏好…），
        塞一个字符串进去只会变成"谁也读不懂的一个大字段"。
        """
        if not isinstance(profile, dict):
            return self.user_profile()
        with self._lock:
            cur = self.data.get("user_profile")
            if not isinstance(cur, dict):
                cur = {}
            for k, v in profile.items():
                key = str(k or "").strip()
                if not key:
                    continue
                cur[key] = copy.deepcopy(v)
            self.data["user_profile"] = cur
        self.save()
        return self.user_profile()

    def user_profile(self):
        "「」读回画像（深拷贝，改它不会动到真身）；没有就返回 `{}`。「」"
        with self._lock:
            cur = self.data.get("user_profile")
            return copy.deepcopy(cur) if isinstance(cur, dict) else {}

    # ---- 降权（长时间不看的站，慢慢变得不可信）----
    def decay_unused(self, days=30, floor=0.1, now=None, factor=0.9):
        """很久没访问过的站**降权**（`trust` 与 `judged_trust` 同时乘 factor）。返回受影响条数。

        为什么"久不看"要降权：可信度不是"一次判定终身有效"。一个站半年没人看、内容全变了，
        还挂着当初的 0.8，那是**记忆在说谎**。慢慢衰减 = 让世界模型自己变诚实，
        也把"重新看一眼"的优先级交还给 due()/plan()。
        为什么 `trust` 和 `judged_trust` 都降：它们是同一个概念的两个口径
        （总账口径 / 单次判断口径），只降一个会出现"总账说 0.8、判断说 0.1"的自相矛盾。
        为什么有 `floor` 兜底：衰减到 0 等于把站点永久拉黑，而"很久没看"并不是罪证 ——
        0.1 表示"基本不信，但还留着一条记录等它自己回来"。
        为什么 `factor` 可注入：自测要能一次看到"降到底"的效果，而不是跑 40 轮。
        `days<=0` 表示"所有站都算久没看"（用于人工触发一次全量衰减）。
        """
        now = time.time() if now is None else float(now)
        try:
            d = float(days)
        except Exception:
            d = 30.0
        cutoff = now - max(0.0, d) * 86400.0
        try:
            fl = _clamp01(floor, 0.1)
        except Exception:
            fl = 0.1
        try:
            fac = float(factor)
        except Exception:
            fac = 0.9
        if math.isnan(fac):
            fac = 0.9
        fac = max(0.0, min(1.0, fac))
        n = 0
        with self._lock:
            for dom, rec in list(self.sites.items()):
                if not isinstance(rec, dict):
                    continue
                last = rec.get("last_seen") or rec.get("first_seen") or 0
                try:
                    last = float(last)
                except Exception:
                    last = 0.0
                if last <= 0 or last > cutoff:
                    continue          # 时间未知（读不出）就不动它：宁可少降，不可瞎降
                changed = False
                for key in ("trust", "judged_trust"):
                    if rec.get(key) is None:
                        continue
                    cur_ = _clamp01(rec.get(key), fl)
                    new_ = max(fl, cur_ * fac)
                    if new_ < cur_:
                        rec[key] = round(new_, 3)
                        changed = True
                if changed:
                    rec["decayed_at"] = now
                    n += 1
        if n:
            self.save()
        return n

    def __len__(self):
        return len(self.sites)

    def __repr__(self):
        return "<WorldModel %d sites / %d relations @ %s>" % (
            len(self.sites), len(self.relations), self.path)


# ================= 纯规则推断的**无盘**入口（judge.py 用；纯增量） =================
class _RuleShell:
    """只带"规则方法"的壳：让 `WorldModel.infer_type` 在**不读任何文件**的前提下可用。

    为什么需要它：判断器（core/world/judge.py）要对每个候选页做规则分类，
    而 `WorldModel(path)` 的构造会读一次 model.json —— 在后台探索线程里，
    那次读还可能和写盘抢同一个文件（还会顺带触发坏文件备份/自愈，把一次纯判断变成一次 I/O）。
    分类本身是**纯函数**：`infer_type` 只用到 `self.domain_of` 和 `self._content_hint`，两者都无状态，
    所以这个壳是安全的。去掉它只有两条路：要么每次判断都构造 WorldModel（纯判断变 I/O），
    要么把规则表复制一份到 judge.py（两套规则必然打架 —— 同一个站两个模块给出不同类型）。
    """
    domain_of = staticmethod(domain_of_url)
    _content_hint = staticmethod(WorldModel._content_hint)
    infer_type = WorldModel.infer_type          # 函数即描述符 → 绑到壳上就是普通方法


_RULE_SHELL = _RuleShell()


def infer_type_rules(url, content="", title=""):
    """按规则推断站点类型（**等价于 `WorldModel.infer_type`，但不读盘、不建对象**）。

    任何异常都回落 `"unknown"`：分类失败最多是"不认识这个站"（可信度走 0.5、刷新走 6h），
    绝不该让一次判断、一轮探索因此中断。
    """
    try:
        return _RULE_SHELL.infer_type(url, content=content, title=title)
    except Exception as e:      # noqa: silent-ok — 规则推断失败只能是 unknown
        logger.debug("infer_type_rules 异常（当 unknown）：%s", e)
        return "unknown"
