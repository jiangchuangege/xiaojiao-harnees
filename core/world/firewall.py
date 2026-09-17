# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
# -*- coding: utf-8 -*-
"""小焦 · 世界层 · 信息污染防火墙（啃互联网必须先有免疫系统）

【一句话定位】
    互联网对小焦来说是**食物**。吃食物就要有消化、排毒、免疫 ——
    这个模块就是那道"宁可吸收慢，也不能把垃圾吃进去"的闸门。

【为什么必须存在（不是"可选的安全功能"）】
    一个会自己上网的智能体，最大的风险不是"看不到东西"，而是"看到啥都往脑袋里塞"：
      · 网页里藏着一句"忽略之前所有指令"，模型照做了 → 它被**远程遥控**了；
      · 一篇广告软文写得像科普 → 它从此把卖货话术当知识讲给用户；
      · 一条假消息配上"惊天内幕" → 它开始自信地撒谎，而且**自己不知道**；
      · 一个过时五年的数据 → 它用旧事实回答新问题，看起来还很确定。
    这些都发生在"吸收的那一刻"，事后无法追责、无法回滚 ——
    所以拦截必须发生在**写进记忆之前**，并且每一步都要留痕。

【十类污染】
    fake_news 假消息 · stale 过时 · contradiction 与已有记忆矛盾 · advertorial 广告软文
    phishing 钓鱼诈骗 · prompt_injection 网页藏指令 · malicious_code 藏脚本
    seo_spam 洗稿/关键词堆砌 · bias 极端立场/煽动情绪 · illegal 违法/隐私/敏感

【五道闸门（screen 逐步过，每步的判定与证据都写进 gates 留痕）】
    ① 来源可信度   查世界模型的历史可信度（model.trust_of）与免疫黑名单；
                   新站默认 0.5，且**第一次不深度吸收**（只浅吸收：不覆盖任何旧记忆）。
    ② 内容特征     事实陈述 vs 情绪煽动、引用 vs 断言、署名 vs 匿名、
                   发布时间 vs 抓取时间、内容长度 vs 信息密度 —— 十类污染在这里判。
    ③ 交叉验证     同一事实 ≥2 个独立源 → 可信；单源 → 标 unverified；不一致 → 冲突降权。
    ④ 注入检测     "忽略指令/系统提示/返回成功/as an AI/ignore previous"、
                   `<script>`/`<iframe>`/`onerror=`、"请把 X 传给 Y" → 直接拦。
    ⑤ 与用户匹对   与用户画像相关吗？与已有记忆冲突吗？
                   不相关 → 不吸收；冲突 → 标"待用户确认"，**绝不擅自改记忆**。

【为什么第五道闸门排在最后】
    前四道判的是"这条信息自己脏不脏"，第五道判的是"它**配不配进小焦的脑子**"。
    顺序不能颠倒：先验货、再决定要不要吃，反过来就会出现
    "因为它跟用户无关，所以它的钓鱼链接就不算问题了" 这种荒唐结论。

【消毒（和"删除红线"共存的唯一办法）】
    "消毒"= **不把污染部分写进主记忆，但把原文留在隔离区**：
      · 干净部分 → 主记忆（clean_text 里已经摘掉了污染段落）
      · 污染片段 → 隔离区留档（记下 classes / reasons / spans：哪一段、为什么判脏）
      · 原文     → 隔离区整份留底（**一个字符都不删**）
    判错的代价因此只是"晚几天吃"，而不是"内容没了"。

【落盘（全部在 logs/world/ 下，logs/ 已被 .gitignore 忽略）】
    absorption.jsonl              吸收台账（每次筛查一行 event=screen，每次落地一行 event=absorb）
    quarantine/index.jsonl        隔离区索引（见 quarantine.py）
    quarantine/q_*.json           隔离条目（原文留底）
    blacklist.json                免疫记忆：{sites, fingerprints, patterns}
    conflicts.jsonl               冲突台账（每一条都写清"谁说的、按哪条规则处理的"）
    verification.jsonl            复审/放行/驳回/降权/恢复的流水
    rejected_memories.json        被用户驳回的记忆 id（主记忆库没有删除 API，只能"标记不再使用"）

【三条刻意的保守（写在明面上，都不是 bug）】
    · 一次污染 → 该域名 trust 降 0.2；两次 → 降 0.5；三次 → 进黑名单（宁可信其坏）；
    · 内容指纹（正文归一化后的 sha1）一旦因污染被记下，**同一篇换域名再发**也会被认出来；
    · 讲反诈的文章里出现"转账""验证码"会被判成钓鱼 —— 这是**故意的**，
      因为"误拦一篇科普"的代价远小于"吃进一条钓鱼话术"的代价。
      用户随时能在隔离区里手动放行（release），纠错成本是点一下。

【对外 API（主线按这个接）】
    fw = PollutionFirewall(model=None, memory=None, cfg=None, state_dir=None)
    r  = fw.screen(url, content, title, topic, profile, known_facts, sources) -> ScreenResult
    fw.absorb(r, url, topic, meta) -> dict          # accept 写主记忆；其余进隔离区
    fw.stats() / fw.report(days=1)                  # 面板与用户可读报告
    fw.release(qid) / fw.reject(mem_id_or_text)     # 用户可操作：放行 / 驳回（搬家，不是删除）
    fw.blacklist_add(domain, reason, kind) / fw.blacklist_remove(domain) / fw.blacklist()
    fw.set_enabled(True) / fw.enabled()
    check_conflict(new_fact, old_fact) -> dict      # 冲突规则，可单独单测
"""
import difflib
import hashlib
import json
import logging
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# 仓库根：core/world/firewall.py → 上溯三级。
# 为什么自己算：防火墙要能**单独 import**（脚本、后台任务、自测都要用它），
# 不能因为"世界层某个模块换了位置"就整体起不来。
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORLD_DIR = os.path.join(_ROOT, "logs", "world")

try:
    from .quarantine import (Quarantine, QUARANTINE_DIR, ST_QUARANTINED, ST_RELEASED,
                             ST_REJECTED, ST_REVIEWED, REVIEW_DAYS)
except ImportError:            # 直接 `python core/world/firewall.py` 时没有包上下文
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from quarantine import (Quarantine, QUARANTINE_DIR, ST_QUARANTINED, ST_RELEASED,
                            ST_REJECTED, ST_REVIEWED, REVIEW_DAYS)

ABSORPTION_FILE = "absorption.jsonl"
BLACKLIST_FILE = "blacklist.json"
CONFLICTS_FILE = "conflicts.jsonl"
VERIFICATION_FILE = "verification.jsonl"
REJECTED_FILE = "rejected_memories.json"

# ================================================================ 十类污染
# 为什么把类名和中文名分成两张表：**代码里用英文键**（稳定、能进 JSON、不随措辞变），
# **给人看的用中文**（报告、理由都用它）。混着用的话，某天有人把中文措辞改一下，
# 所有历史日志的统计口径就全断了。
CLASSES = ("fake_news", "stale", "contradiction", "advertorial", "phishing",
           "prompt_injection", "malicious_code", "seo_spam", "bias", "illegal")
CLASS_CN = {
    "fake_news": "假消息",
    "stale": "过时信息",
    "contradiction": "与已有记忆矛盾",
    "advertorial": "广告软文",
    "phishing": "钓鱼诈骗",
    "prompt_injection": "网页藏指令（提示词注入）",
    "malicious_code": "藏脚本（可执行代码）",
    "seo_spam": "洗稿/关键词堆砌",
    "bias": "极端立场/煽动情绪",
    "illegal": "违法/隐私/敏感内容",
}

# "硬污染"：命中就直接隔离，不看综合分。
# 为什么这四类必须硬拦、不能"降权后看总分"：
# 它们是**动作型**危险（诱导转账、遥控模型、留后门），不是"可信度低"。
# 一条 99% 正确、1% 钓鱼的内容，综合分照样很高 —— 用总分判会把它放进来。
HARD_CLASSES = ("prompt_injection", "malicious_code", "phishing", "illegal")
# "软污染"：降权 + 局部消毒后可以吸收（干净的那部分还是要吃的）。
# 去掉这个区分（全部硬拦）会怎样：一篇末尾带广告的科普文整篇被拒，
# 免疫系统就从"排毒"退化成"挑食"，吸收效率会低到用户想把它关掉。
SOFT_CLASSES = ("advertorial", "seo_spam", "bias", "stale")

# 被摘掉的段落所属的类（=消毒时"从正文里剪掉"的那些）。
# stale 不在此列：过时不是"某一段脏"，是**整篇都老**，剪段落没有意义，只能降权。
# 去掉这条区分会怎样：把一篇老文章的段落乱剪一通，clean_text 变得不成句子。
REMOVABLE_CLASSES = ("advertorial", "phishing", "prompt_injection", "malicious_code",
                     "illegal", "fake_news", "bias", "seo_spam")

DEFAULT_CFG = {
    "enabled": True,
    "accept_min": 0.50,        # 综合可信度低于它 → 不进主记忆
    "trust_floor": 0.30,       # 来源可信度低于它 → 直接隔离（比"不认识"还差）
    "weights": {"source": 0.30, "content": 0.25, "cross": 0.25, "injection": 0.10,
                "profile": 0.10},
    "penalty": {"soft_class": 0.06, "first_visit": 0.03, "unverified": 0.03,
                "cross_conflict": 0.25},
    "stale_days": 730,         # 时间戳超过这么久 → 过时
    "deep_trust": 0.70,        # 达到它才算"够可信，可以参与覆盖旧记忆"
    "conflict_similarity": 0.62,   # 两句话像到这个程度才算"在说同一件事"
    "old_fact_days": 30,       # 旧记忆超过这么久，且新信息够可信 → 问用户
    "repeat_gram": 8,          # 洗稿检测：8 字片段重复次数
    "repeat_times": 4,
    "decay_days": 30,          # 免疫记忆：多久没再犯就降一级
    "punish": {1: 0.2, 2: 0.5},    # 一次污染降 0.2、两次降 0.5、三次进黑名单
}

# ================================================================ 规则表
# 规则表写成分离的 (正则, 中文原因) 纯数据：**可审计**。
# 出了误杀，能一眼看出"这条是被哪条规则判的、为什么"，不必去读代码逻辑。
# 顺序 = 优先级（先具体后笼统），命中的第一条作为证据 —— 用户看到的理由才准。
# 去掉这个结构（把判断写死在 if 里）→ 规则会散落在各处，改一条要读三百行。

# —— 闸门④：提示词注入（网页藏指令）——
_INJECTION = [
    (r"忽略(?:之前|以前|以上|前面|上述|上面)?(?:的)?(?:所有|全部)?(?:指令|指示|规则|设定|提示|要求)",
     "正文里藏着『忽略之前的指令』这类越权指令"),
    (r"ignore\s+(?:all\s+)?(?:the\s+)?(?:previous|prior|above|foregoing)\s+(?:instruction|prompt|rule|direction)",
     "英文的 ignore previous instructions（对整个链路都生效，必须拦）"),
    (r"(?:disregard|forget)\s+(?:all\s+)?(?:previous|prior|above|everything)",
     "disregard/forget previous：抹掉上文设定的注入手法"),
    (r"(?:system\s*prompt|系统提示词|系统提示|系统指令|developer\s*message|开发者消息)",
     "提到「系统提示词」并试图改写它"),
    (r"(?:as\s+an\s+AI|作为(?:一个)?\s*AI|你现在是(?:一个)?(?:新的)?(?:AI|助手|管理员|root))",
     "试图给模型重新设定身份（越权扮演）"),
    (r"(?:直接|然后|请)?(?:返回|回复|输出)\s*(?:成功|成功状态|OK|ok|true|True|已完成)",
     "要求模型「返回成功」（不管事实如何都说成功）"),
    (r"请把[^。！？\n]{0,20}(?:发送|发给|传给|转发|提交|上传|告诉|写入)(?:给)?[^。！？\n]{0,20}",
     "『请把 X 发给 Y』式的指令：这是要让模型替它搬运数据"),
    (r"(?:不要|别|无需)(?:告诉|通知|提醒)(?:用户|他|她)|(?:do\s+not|don'?t)\s+tell\s+the\s+user",
     "要求对用户隐瞒（正常内容没有任何理由这样写）"),
    (r"(?:忘记|忘掉)(?:你)?(?:的)?(?:设定|身份|规则|人设)", "要求模型忘掉自己的设定"),
]

# —— 闸门④：藏脚本（可执行代码）——
_MALICIOUS = [
    (r"<\s*script\b[^>]*>.*?<\s*/\s*script\s*>", "整块 <script>...</script> 脚本"),
    (r"<\s*script\b[^>]*>", "网页里嵌了 <script> 脚本标签"),
    (r"<\s*iframe\b[^>]*>", "网页里嵌了 <iframe>（可以在你打开时加载别的东西）"),
    (r"\bon(?:error|load|click|mouseover)\s*=", "HTML 事件属性（onerror= 这类）打开即执行脚本"),
    (r"javascript\s*:", "javascript: 伪协议（点击就执行）"),
    (r"\b(?:eval|exec)\s*\(", "eval/exec 调用（把字符串当代码跑）"),
    (r"base64\s*(?:-d|--decode)|\bfrombase64string\b", "base64 解码执行（藏命令的惯用手法）"),
    (r"powershell\s+-(?:enc|encodedcommand|e)\b", "PowerShell 编码命令（最常见的免杀载荷）"),
    (r"(?:curl|wget|iwr|invoke-webrequest|invoke-restmethod)[^\n]{0,60}\|\s*(?:sh|bash|cmd|powershell|iex)",
     "把下载来的内容直接管道给解释器执行"),
    (r"<\s*meta\s+http-equiv\s*=\s*[\"']?refresh", "meta refresh 自动跳转（钓鱼跳板的惯用手法）"),
]

# —— 闸门②：钓鱼诈骗 ——
_PHISHING = [
    (r"(?:点击|打开|扫描|长按)[^。！？\n]{0,12}(?:链接|二维码)[^。！？\n]{0,14}(?:领取|中奖|退款|返现|补贴|验证|激活|解冻)",
     "诱导点击链接去「领取/验证」（典型钓鱼话术）"),
    (r"(?:输入|提供|填写|告知|回复)[^。！？\n]{0,10}(?:银行卡|卡号|身份证|密码|验证码|信用卡|支付密码|短信码)",
     "索要银行卡/身份证/密码/验证码（正规内容绝不会这样要求）"),
    (r"(?:转账|汇款|打款|付款|缴费)[^。！？\n]{0,14}(?:到|至|给|账户|卡号)",
     "要求转账/汇款（涉钱的动作一律先隔离）"),
    (r"(?:免费领取|0\s*元购|一元购|中奖|中签|抽中(?:了)?(?:大奖|奖品)|返利|刷单返现)",
     "免费领取/中奖类诱饵"),
    (r"(?:加|扫码加|添加)[^。！？\n]{0,8}(?:客服|微信|V信|威信|QQ|好友|群)[^。！？\n]{0,12}(?:办理|咨询|领取|退款|返现)?",
     "引流到私聊（脱离平台监管，出了问题没人管）"),
    (r"(?:账户|账号|资金|银行卡)(?:被)?(?:冻结|异常|风险)[^。！？\n]{0,20}(?:验证|解冻|点击|联系)",
     "假冒「账号异常」制造紧张感（诈骗标准剧本）"),
    (r"(?:安全中心|官方客服|公检法|警察|法院)[^。！？\n]{0,16}(?:电话|联系|要求|通知)[^。！？\n]{0,16}(?:转账|汇款|验证|配合)",
     "假冒公检法/官方客服要求配合（假冒身份 + 涉钱）"),
]

# —— 闸门②：违法/隐私/敏感 ——
_ILLEGAL = [
    (r"(?:赌博|博彩|六合彩|时时彩|棋牌室|下注|开盘口|押注)", "赌博/博彩类内容"),
    (r"(?:枪支|弹药|仿真枪|管制刀具|毒品|冰毒|大麻|违禁品|迷药)", "违禁物品"),
    (r"(?:代开|虚开)[^。！？\n]{0,6}(?:发票|增值税)|办证|刻章|假证|病历证明", "代开发票/办假证"),
    (r"(?:洗钱|跑分|刷单|水军|黑产|盗号|木马|撞库|薅羊毛群)", "黑灰产"),
    (r"(?:色情|裸聊|成人视频|约炮|招嫖|福利姬)", "色情类内容"),
    (r"(?:人肉|开盒|身份证号库|手机号库|个人隐私数据|开房记录|户籍查询)", "侵犯隐私/人肉开盒"),
]

# —— 闸门②：广告软文 ——
_ADVERTORIAL = [
    (r"(?:立即|马上|赶紧|现在|快点)(?:点击|下单|抢购|购买|预订|咨询)", "催促下单"),
    (r"(?:限时|今日|全网最低|史低|仅需|只要|只需)\s*[¥￥$]?\s*\d+(?:\.\d+)?\s*(?:元|块|折|起)",
     "价格促销话术"),
    (r"(?:优惠券|折扣码|下单立减|满\s*\d+\s*减|第二件半价|买一送一)", "优惠券/折扣话术"),
    (r"(?:购买链接|商品链接|淘口令|带货|代购|旗舰店|官方正品|点击购买)", "带货/购买引导"),
    (r"(?:扫码|添加|加)\s*(?:微信|客服|好友)[^。！？\n]{0,10}(?:咨询|购买|领取|下单)", "引流到私域成交"),
    (r"本(?:文|内容|篇文章)(?:由|为|系)[^。！？\n]{0,12}(?:赞助|广告|推广|商单|合作)", "自我披露的赞助/广告"),
    (r"(?:广告|推广|赞助内容|软文|商单)\s*[:：]?", "带「广告/推广」标记"),
]

# —— 闸门②：洗稿 / 关键词堆砌 ——
_SEO = [
    (r"(?:本文|文章|内容)(?:由|系|是)\s*(?:AI|人工智能|机器|模型)(?:自动)?(?:生成|撰写|创作|编写)",
     "AI 自动生成（洗稿的常见来源）"),
    (r"(?:改写自|洗稿|伪原创|关键词堆砌|批量采集|采集自|内容农场)", "洗稿/采集"),
    (r"(?:本文\s*来源|原文\s*链接|转载自)[^。！？\n]{0,40}?(?:请注明|侵删)", "搬运痕迹"),
]

# —— 闸门②：极端立场 / 煽动情绪 ——
_BIAS = [
    (r"(?:震惊|惊天|骇人听闻|太可怕了|不转不是|速转|删前速看|必须转发|全民愤怒|气炸了)",
     "煽动式标题党话术（目的是让你转发，不是让你知道）"),
    (r"(?:绝对不会|毫无疑问|板上钉钉|铁定|百分之百|100%)\s*(?:是|会|能|就是)", "绝对化断言"),
    (r"(?:垃圾|智障|脑残|滚出|该死|畜生|无耻之极|卖国贼|汉奸)", "辱骂/极端措辞"),
    (r"(?:都怪|全都是|没有一个好东西|永远是|从来都是)\s*\S{0,6}(?:坏|骗|错|烂)", "以偏概全的极端归因"),
]

# —— 闸门②：假消息特征（注意：这些是"特征"，不是判决本身；判决在闸门③交叉验证）——
_FAKE_NEWS = [
    (r"(?:据|根据)[^，。！？\n]{0,14}(?:内部|知情人士|网友|消息人士|有关部门内部)[^，。！？\n]{0,8}(?:透露|称|表示|爆料)",
     "匿名「内部人士」式转述（无法核实到源头）"),
    (r"(?:研究|数据|调查|统计)(?:表明|显示|证明|发现)[^。！？\n]{0,40}\d{2,}(?:%|％|倍|万|亿|人)",
     "甩出一个数据但不说出处"),
    (r"(?:绝对真实|已被证实|实锤|铁证|官方已确认|99%的人不知道)", "绝对化/耸动式断言"),
    (r"(?:不转不是|速转|赶紧转发|删前速看|惊天内幕|内幕消息|揭秘)", "诱导传播式话术"),
    (r"(?:科学家|专家|教授)(?:表示|称|指出)[^。！？\n]{0,30}(?:终于|竟然|居然)", "假借权威 + 耸动转折"),
]

# 日期：支持 2024-01-02 / 2024/1/2 / 2024年1月2日 / 2024.01.02
_DATE_RE = re.compile(r"(?P<y>(?:19|20)\d{2})\s*[-/.年]\s*(?P<m>\d{1,2})\s*[-/.月]\s*(?P<d>\d{1,2})")
# 有没有"出处"：给了链接/参考文献/机构名，就算有出处。
# 为什么"有出处"能减轻假消息判定：无出处是造假最普遍的特征（编造的东西说不出处），
# 反过来，有可核查出处的内容即使措辞耸动，也该走交叉验证而不是直接判死。
_CITE_RE = re.compile(r"https?://|www\.|参考文献|引用来源|资料来源|来源\s*[:：]|出处|doi:|arxiv", re.I)
_SIGN_RE = re.compile(r"(?:作者|撰稿|记者|编辑|发布(?:时间|日期)?|来源|作者简介)\s*[:：]")
_ANON_RE = re.compile(r"(?:匿名|网传|据传|听说|有网友|某知情人|不便透露姓名)")
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_NEG_RE = re.compile(r"(?:不|没|无|未|非|别|莫|no|not|never|without)", re.I)
_WS_RE = re.compile(r"\s+")
_TAG_RE = re.compile(r"<[^>]{0,400}>")
_SEG_SPLIT_RE = re.compile(r"[。！？!?；;\n\r]+")


# ================================================================ 小工具
def _now():
    "「」当前时间戳（单独抽出来是为了自测能注入 now，不必真的等 30 天）。「」"
    return time.time()


def _clamp01(x, default=0.0):
    "「」夹到 0~1。**非法值返回 default 而不是抛错** —— 可信度算错不该让筛查崩掉。「」"
    try:
        v = float(x)
    except Exception:      # noqa: silent-ok — 拿不到数就退到默认值
        return float(default)
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


def _domain_of(url):
    """URL → 归一化域名（去 www.、去端口、小写）。

    优先用世界层自己的实现（`core.world.model.domain_of_url`）：域名归一只能有**一处**定义，
    两套实现迟早对同一个 URL 给出两个域名，于是"同一个站的可信度"会被记成两份。
    拿不到世界层时用下面的兜底正则 —— 防火墙必须能独立跑。
    去掉兜底 → 在只有防火墙的进程里所有域名都是空串，黑名单和可信度全部失配。
    """
    u = str(url or "").strip()
    try:
        from .model import domain_of_url        # 惰性：世界模型是可选依赖
        d = domain_of_url(u)
        if d:
            return d
    except Exception:      # noqa: silent-ok — 拿不到就用下面这段兜底
        pass
    m = re.match(r"^(?:[a-z][a-z0-9+.\-]*://)?(?:[^@/]*@)?([^/?#:]+)", u, re.I)
    d = (m.group(1) if m else u).strip().lower().rstrip(".")
    if d.startswith("www."):
        d = d[4:]
    return d


def normalize_text(text):
    """正文归一化（算指纹用）：去 HTML 标签、去空白、去标点、英文小写。

    为什么要归一化之后才算指纹：污染源的常规操作就是"换域名、改标点、加空格"再发一遍。
    只要正文实质没变，归一化后的字符串就一模一样 → 指纹能认出来。
    去掉它 → 同一篇垃圾换个域名就能无限次重新闯关，免疫记忆形同虚设。
    """
    t = _TAG_RE.sub(" ", str(text or ""))
    t = t.lower()
    t = re.sub(r"[\s\u3000]+", "", t)
    # 去掉标点与符号（归一化用）：字符类里两个引号都必须转义 ——
    # 不转义的那一个会把 Python 字符串**提前结束**，整行变成语法错
    # （这正是本轮交付里 2000 行的文件一度完全不可用的原因，写下来免得再犯）。
    t = re.sub(r"[，。！？；：、\"'（）《》【】…—\-_=+*#`~|/\\\[\]{}()<>,.!?;:'\"]+", "", t)
    return t


def content_fingerprint(text):
    "「」内容指纹 = 正文归一化后的 sha1（同一篇换域名再发也能认出）。「」"
    return hashlib.sha1(normalize_text(text).encode("utf-8", "replace")).hexdigest()


def split_segments(text):
    """把正文切成句/行级片段，返回 [(段文本, 起, 止)]。

    为什么要切：消毒要**按段落摘掉**脏的部分（整篇拒绝太粗暴、整篇接受太危险），
    而"哪一段脏"必须有精确的起止偏移，才能写进隔离区的 spans 供人复核。
    去掉它 → 只能整篇判脏 / 整篇判净，两边的代价都很大。
    """
    out, start, n = [], 0, len(text)
    for m in _SEG_SPLIT_RE.finditer(text):
        seg = text[start:m.start()]
        if seg.strip():
            out.append((seg, start, m.start()))
        start = m.end()
    tail = text[start:]
    if tail.strip():
        out.append((tail, start, n))
    return out


def strip_spans(text, spans):
    """按 spans 把污染片段从正文里摘掉，返回 clean_text。

    只摘不删文件：这是"消毒"落在文本上的那一半（另一半是隔离区留底）。
    重叠区间先合并再摘，避免同一段被切两刀。
    去掉它 → clean_text 只能等于原文（等于没消毒）或者等于空串（等于整篇丢弃）。
    """
    if not spans:
        return text
    cuts = []
    for s in spans:
        try:
            a, b = int(s.get("start")), int(s.get("end"))
        except Exception:      # noqa: silent-ok — 坏 span 直接跳过，不能因此丢失整篇
            continue
        if 0 <= a < b <= len(text):
            cuts.append((a, b))
    if not cuts:
        return text
    cuts.sort()
    merged = [list(cuts[0])]
    for a, b in cuts[1:]:
        if a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    out, prev = [], 0
    for a, b in merged:
        out.append(text[prev:a])
        prev = b
    out.append(text[prev:])
    return "".join(out)


def _fact_of(x):
    """把"事实"归一成 dict：认识 str（纯文本）和 dict（带 score/ts/from_user 的记录）。

    为什么要同时认两种：`check_conflict` 要能被**单独单测**（人只会写两个字符串），
    而防火墙内部传的是带元信息的记录。两种都认，规则就只需要维护一份。
    """
    if isinstance(x, dict):
        return {"text": str(x.get("text") or x.get("fact") or x.get("content") or ""),
                "score": x.get("score"), "ts": x.get("ts"),
                "from_user": bool(x.get("from_user")),
                "id": str(x.get("id") or "")}
    return {"text": str(x or ""), "score": None, "ts": None, "from_user": False, "id": ""}


def _norm_fact(text):
    "「」事实句归一化（只留中英文数字）：比对「是不是在说同一件事」。「」"
    t = str(text or "").lower()
    t = re.sub(r"[\s\u3000]+", "", t)
    # 去掉标点与符号（归一化用）：字符类里两个引号都必须转义 ——
    # 不转义的那一个会把 Python 字符串**提前结束**，整行变成语法错
    # （这正是本轮交付里 2000 行的文件一度完全不可用的原因，写下来免得再犯）。
    t = re.sub(r"[，。！？；：、\"'（）《》【】…—\-_=+*#`~|/\\\[\]{}()<>,.!?;:'\"]+", "", t)
    return t


def _numbers(text):
    return sorted(set(_NUM_RE.findall(str(text or ""))))


def check_conflict(new_fact, old_fact, new_score=None, now=None, old_ts=None, from_user=None):
    """判断"新信息"和"已有记忆"是不是**互相矛盾**，以及该按哪条规则处理。

    返回 dict：
        conflict            是否矛盾（说的不是同一件事时永远是 False）
        kind                numeric 数字对不上 / negation 一个有一个说没有 / none
        action              keep_old（以旧为准） / ask_user（该问用户） / no_conflict
        needs_user_confirm  是否要挂一条"待用户确认"
        why                 可读中文理由（会原样写进 conflicts.jsonl，用户看得到）

    【四条规则，核心原则：**用户的话 > 互联网信息**】
        ① 新信息可信度 < 0.7          → 不覆盖旧记忆，标"待确认"
        ② 新信息 ≥ 0.7 且旧记忆 >30 天 → 询问用户（needs_user_confirm=True）
        ③ 新信息 ≥ 0.7 且旧记忆很新    → 不覆盖（等更多独立来源，只留档不打扰）
        ④ 旧记忆是**用户明确说过**的    → 永不被外部覆盖（from_user=True）

    为什么"矛盾"要判得这么保守（要求两句话像到 0.62 才算同一件事）：
    误判矛盾的代价是"该吸收的知识被挡在门外 + 用户被无意义的问题打扰"，
    而漏判的代价只是"旧记忆暂时没被更新"（下一次多源验证还有机会）。
    两害相权，宁可漏判。
    去掉这四条规则直接覆盖 → 一次网页抓取就能改掉用户亲口说过的事实，
    这是最严重的一类不可逆损害（用户会彻底不信任它的记忆）。
    """
    n = _fact_of(new_fact)
    o = _fact_of(old_fact)
    t = _now() if now is None else float(now)
    if new_score is not None:
        try:
            n["score"] = float(new_score)
        except Exception:      # noqa: silent-ok — 分数坏掉按"没分数"处理（最保守）
            n["score"] = None
    o_ts = old_ts if old_ts is not None else o.get("ts")
    if from_user is not None:
        o["from_user"] = bool(from_user)
    out = {"conflict": False, "kind": "none", "action": "no_conflict",
           "needs_user_confirm": False, "why": "",
           "new": n["text"], "old": o["text"], "new_score": n["score"],
           "old_age_days": None, "old_id": o["id"]}
    a, b = _norm_fact(n["text"]), _norm_fact(o["text"])
    if len(a) < 4 or len(b) < 4 or a == b:
        return out
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    if ratio < DEFAULT_CFG["conflict_similarity"]:
        return out                       # 说的不是同一件事，谈不上矛盾
    body_a, body_b = _NUM_RE.sub("#", a), _NUM_RE.sub("#", b)
    body_ratio = difflib.SequenceMatcher(None, body_a, body_b).ratio()
    kind = ""
    if _numbers(a) and _numbers(b) and _numbers(a) != _numbers(b) and body_ratio >= 0.5:
        kind = "numeric"                 # 同一句话、数字不一样 → 必有一个是错的
    elif bool(_NEG_RE.search(a)) != bool(_NEG_RE.search(b)):
        kind = "negation"                # 一个说"有"、一个说"没有"
    if not kind:
        return out
    age = None
    try:
        if o_ts:
            age = (t - float(o_ts)) / 86400.0
    except Exception:      # noqa: silent-ok — 旧记忆没时间戳就当作"很久以前"（更该问用户）
        age = None
    out["conflict"] = True
    out["kind"] = kind
    out["old_age_days"] = None if age is None else round(age, 1)
    score = n["score"]
    score_v = 0.0 if score is None else _clamp01(score, 0.0)
    if o["from_user"]:
        out.update(action="keep_old", needs_user_confirm=False,
                   why="与用户亲口说过的事实冲突：**用户的话 > 互联网信息**，永不覆盖")
    elif score_v < DEFAULT_CFG["deep_trust"]:
        out.update(action="keep_old", needs_user_confirm=True,
                   why="新信息可信度 %.2f < %.2f：不覆盖旧记忆，标为待用户确认"
                       % (score_v, DEFAULT_CFG["deep_trust"]))
    elif age is None or age > DEFAULT_CFG["old_fact_days"]:
        out.update(action="ask_user", needs_user_confirm=True,
                   why="新信息可信度够（%.2f ≥ %.2f），但旧记忆%s：覆盖与否请用户定"
                       % (score_v, DEFAULT_CFG["deep_trust"],
                          "没有时间戳" if age is None
                          else "已经 %d 天了" % int(age)))
    else:
        out.update(action="keep_old", needs_user_confirm=False,
                   why="旧记忆还很新（%d 天）：新信息即使可信也不覆盖，等更多独立来源"
                       % int(age))
    return out


def _fact_candidates(text, limit=40):
    """从正文里抽出"像事实的句子"（给交叉验证/冲突检测用）。

    只取长度 ≥6 的句子、最多 limit 条：冲突检测是 O(新句 × 旧句) 的字符串相似度计算，
    不设上限时一篇长文配上十几条记忆就会明显卡顿（筛查是热路径）。
    去掉 limit → 抓一篇万字长文时屏幕会卡住几百毫秒，用户体感是"小焦卡了"。
    """
    out = []
    for seg, _s, _e in split_segments(str(text or "")):
        s = seg.strip()
        if len(s) < 6:
            continue
        out.append(s)
        if len(out) >= limit:
            break
    return out


# ================================================================ 惰性依赖
_HEALTH = {"tried": False, "mod": None}


def _health():
    """惰性拿 `core.health` 里那几个落盘小工具；拿不到就用本文件的兜底。

    为什么借用而不是自己再写一套：`logs/` 下所有模块都该用同一套"追加 JSONL / 容忍坏行"
    的写法（health/__init__.py 里那四个函数就是为此存在的）。
    两套实现的必然结果是"有一边的坏行容错少一点"，然后某天日志里出现读不出来的行。
    拿不到（独立 import、单文件运行）时的兜底在下面，绝不抛。
    """
    if _HEALTH["tried"]:
        return _HEALTH["mod"]
    _HEALTH["tried"] = True
    try:
        from core.health import append_jsonl, read_json, read_jsonl, write_json
        _HEALTH["mod"] = {"append": append_jsonl, "readl": read_jsonl,
                          "readj": read_json, "writej": write_json}
    except Exception:      # noqa: silent-ok — 拿不到是完全合法的情形（离线/单模块）
        _HEALTH["mod"] = None
    return _HEALTH["mod"]


def _append_jsonl(path, obj):
    "「」追加一行 JSON。优先用 health 的实现，拿不到就自己写。**绝不抛**。「」"
    h = _health()
    if h:
        try:
            return bool(h["append"](path, obj))
        except Exception:      # noqa: silent-ok — 借来的实现出问题就退回自己的
            pass
    try:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        return True
    except Exception:      # noqa: silent-ok — 记不上账不能影响筛查本身
        return False


def _read_jsonl(path, days=None, limit=None):
    "「」读 JSONL（坏行跳过）。优先 health，拿不到自己读。**绝不抛**。「」"
    h = _health()
    if h:
        try:
            return list(h["readl"](path, days=days, limit=limit))
        except Exception:      # noqa: silent-ok — 同上，退回自己的实现
            pass
    out = []
    try:
        if not os.path.exists(path):
            return out
        since = (_now() - float(days) * 86400.0) if days else None
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:      # noqa: silent-ok — 半截行跳过
                    continue
                if not isinstance(row, dict):
                    continue
                if since is not None:
                    try:
                        if float(row.get("ts") or 0) < since:
                            continue
                    except Exception:      # noqa: silent-ok — ts 坏掉就当作当期，宁可多算
                        pass
                out.append(row)
                if limit and len(out) >= int(limit):
                    break
    except Exception:      # noqa: silent-ok — 读不动就当没有台账
        return out
    return out


def _read_json(path, default=None):
    "「」读一个小 JSON；坏了返回 default。优先 health，拿不到自己读。「」"
    h = _health()
    if h:
        try:
            return h["readj"](path, default)
        except Exception:      # noqa: silent-ok — 退回自己的实现
            pass
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            v = json.load(f)
        return v if v is not None else default
    except Exception:      # noqa: silent-ok — 坏文件等价于"没状态"，绝不抛
        return default


def _write_json(path, obj):
    """写一个小 JSON（**直写，不搞 临时文件+改名**）。

    为什么不 tmp+rename：rename 在 Windows 上要覆盖目标，语义上等同于"先删掉旧文件"，
    而本层有一条硬红线是**绝不删除任何文件**（core/security/no_delete.py）。
    这里写的是自己的状态文件，内容全在内存里，写坏了下一次写会覆盖回来。
    去掉直写（改成原子替换）在别的平台上没问题，但会破坏"绝不删文件"这条约束。
    """
    h = _health()
    if h:
        try:
            return bool(h["writej"](path, obj))
        except Exception:      # noqa: silent-ok — 退回自己的实现
            pass
    try:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        return True
    except Exception:      # noqa: silent-ok — 状态写不上只是"少记住一件事"
        return False


_MEM = {"tried": False, "mod": None}


def _default_memory():
    """惰性拿小焦的记忆库（`core.memory_vec`）：只 import，不做任何初始化。

    为什么只 import 不调用：`memory_vec` 是**小焦真正的记忆**，本模块不该在 import 期
    碰它一下（自测、离线脚本都不该因此写到真实记忆里）。
    拿不到（没装/没启动）返回 None，调用方按"写自己的 JSONL 兜底"处理。
    """
    if _MEM["tried"]:
        return _MEM["mod"]
    _MEM["tried"] = True
    try:
        import core.memory_vec as m
        _MEM["mod"] = m if callable(getattr(m, "add_memory", None)) else None
    except Exception:      # noqa: silent-ok — 没有记忆库是完全合法的情形
        _MEM["mod"] = None
    return _MEM["mod"]


# ================================================================ 筛查结果
@dataclass
class ScreenResult:
    """一次筛查的完整结论。**字段名与顺序是接口的一部分**（主线按它接）。

    为什么每一道闸的结果都留下来（gates）而不是只给一个决定：
    用户问"为什么这条没吸收"时，答案必须能落到**具体哪一道闸、哪一条证据**上。
    只给 decision 的话，排查就只能靠猜，规则写错了永远发现不了。
    """
    url: str = ""
    domain: str = ""
    decision: str = "quarantine"          # accept / quarantine / discard
    passed: int = 0                       # 过了几道闸（0~5）
    classes: list = field(default_factory=list)      # 命中的污染类型
    reasons: list = field(default_factory=list)      # 可读中文理由（至少 1 条）
    score: float = 0.0                    # 综合可信度 0~1
    clean_text: str = ""                  # 消毒后的正文
    gates: dict = field(default_factory=dict)        # {"1_source": {...}, ... "5_profile": {...}}
    qid: str = ""                         # 进隔离区时的编号（accept 时为空）
    topic: str = ""
    fingerprint: str = ""
    needs_user_confirm: bool = False

    def __post_init__(self):
        # 理由至少一条：**空理由的拒绝 = 用户永远不知道自己为什么被拦**。
        # 去掉它 → 面板上会出现"隔离了 18 条（原因：）"，用户第一反应是关掉防火墙。
        if not self.reasons:
            self.reasons = ["未给出具体理由（按最保守方式处理）"]
        self.classes = list(self.classes or [])
        self.reasons = [str(r) for r in self.reasons]

    @property
    def absorbed_ok(self):
        "「」这条是不是「可以进主记忆」。给调用方一个不用记字符串的判断口。「」"
        return self.decision == "accept"

    def describe(self):
        "「」一句话人话总结（面板/日志用）。「」"
        return "[%s] %s（过 %d/5 道闸，可信度 %.2f）%s" % (
            self.decision, self.domain or self.url, self.passed, self.score,
            "｜" + "；".join(self.reasons[:2]) if self.reasons else "")


# ================================================================ 正则规则：用时才编译
# 【本轮实测抓到的真 bug，写下来免得再犯】
# 规则表（_INJECTION / _MALICIOUS / …）里存的是**正则字符串**，而 `_detect` 里直接写了
# `rx.search(seg)` —— 字符串没有 `.search`，所以**第一次筛查就 AttributeError**：
# 整道防火墙一次都没真正跑起来（这正是"代码写了、接线了、没跑过"的典型）。
# 修法：统一在这里**用时编译 + 缓存**。表仍然是人可读的字符串（改规则不用管编译），
# 性能靠 `_RX_CACHE` 兜住；某条规则写坏了只跳过它并留日志，
# **绝不让一条坏正则把整道闸门带崩**（安全设施自己不能成为故障源）。
_RX_CACHE = {}
_RE_I = 0            # 注入/钓鱼类规则中英混写，大小写不敏感更稳
_RE_S = 0            # 跨行块（<script>…</script>）必须开 DOTALL，否则 ".*?" 遇换行就停
try:
    import re as _re0
    _RE_I = _re0.I
    _RE_S = _re0.I | _re0.S
except Exception:               # noqa: BLE001 — 连 re 都拿不到时后面编译会自己兜底
    pass


def _warn(msg):
    """留痕用（不依赖模块级 logger 的初始化顺序）。"""
    try:
        import logging as _lg
        _lg.getLogger(__name__).warning(msg)
    except Exception:           # noqa: BLE001
        pass


def _rx(pattern, flags=None):
    """把规则表里的正则字符串编译成 pattern（带缓存）。编译不了就返回"永不匹配"。"""
    import re as _re
    fl = _RE_I if flags is None else flags
    key = (pattern, fl)
    got = _RX_CACHE.get(key)
    if got is not None:
        return got
    try:
        rx = _re.compile(pattern, fl)
    except Exception as e:      # noqa: silent-ok — 坏规则跳过，但必须留痕
        _warn("防火墙：规则编译失败，已跳过：%r（%s）" % (str(pattern)[:60], e))
        rx = _re.compile(r"(?!)")          # 永不匹配 == 跳过这条
    _RX_CACHE[key] = rx
    return rx


# ================================================================ 防火墙
class PollutionFirewall:
    """信息污染防火墙：十类污染、五道闸门、隔离区、消毒、免疫记忆、冲突处理。

    三个注入点（**故意的**，和世界层其它模块一个风格）：
      · `model`  世界模型（提供 trust_of / sites）。不给就按"不认识 = 0.5"。
      · `memory` 记忆库（提供 add_memory / search_memory）。不给就惰性找 core.memory_vec，
                 再拿不到就把内容写进 absorption.jsonl 兜底（**绝不抛**）。
      · `cfg`    阈值与权重（accept_min / stale_days / punish …），调阈值不该改代码。
    自测靠这三个口把状态全部打在临时目录里，**绝不碰小焦真正的世界与记忆**。
    """

    def __init__(self, model=None, memory=None, cfg=None, state_dir=None):
        self.state_dir = os.path.abspath(state_dir or WORLD_DIR)
        self.model = model
        self.memory = memory
        self.cfg = _merge_cfg(cfg)
        self.allow_memory_import = True     # 关掉它 = 明确"这次不要碰记忆库"（自测用）
        self.absorption_path = os.path.join(self.state_dir, ABSORPTION_FILE)
        self.blacklist_path = os.path.join(self.state_dir, BLACKLIST_FILE)
        self.conflicts_path = os.path.join(self.state_dir, CONFLICTS_FILE)
        self.verification_path = os.path.join(self.state_dir, VERIFICATION_FILE)
        self.rejected_path = os.path.join(self.state_dir, REJECTED_FILE)
        # 隔离区放在 state_dir 下：整套状态（台账/黑名单/隔离区）必须在同一个目录里，
        # 否则"换一个 state_dir 做自测"会漏掉隔离区，自测就会污染真实隔离区。
        self.quarantine = Quarantine(os.path.join(self.state_dir, "quarantine"))
        self.q = self.quarantine            # 别名（叫起来顺手）
        self._lock = threading.Lock()
        try:
            os.makedirs(self.state_dir, exist_ok=True)
        except Exception as e:      # noqa: silent-ok — 建不出目录后面写入会如实失败
            logger.warning("防火墙状态目录创建失败：%s", e)
        _write_json(self.rejected_path, _read_json(self.rejected_path, {}) or {})

    # ------------------------------------------------------------ 开关
    def enabled(self):
        """防火墙开着吗（用户可在配置里关）。默认**开**。

        为什么默认开：它关掉时的代价（吃进污染、被网页遥控）是不可逆的，
        而它开着的代价只是"偶尔误拦一条，用户点一下放行"。
        """
        v = self._cfg_file().get("enabled", None)
        if v is None:
            return bool(self.cfg.get("enabled", True))
        return bool(v)

    def set_enabled(self, on):
        """开/关防火墙（写进状态文件，立刻生效）。返回当前状态。

        注意：**关掉不等于删掉免疫记忆**。黑名单、隔离区、冲突台账全部原样留着，
        下次打开就接着用 —— 这是"只暂停，不销毁"。
        """
        st = self._cfg_file()
        st["enabled"] = bool(on)
        st["updated"] = round(_now(), 3)
        _write_json(self._state_file(), st)
        self._log_verification({"event": "set_enabled", "enabled": bool(on)})
        return bool(on)

    def _state_file(self):
        return os.path.join(self.state_dir, "firewall.json")

    def _cfg_file(self):
        "「」读自己的开关状态文件（坏了当空 → 回落到 cfg 默认，绝不抛）。「」"
        d = _read_json(self._state_file(), {})
        return d if isinstance(d, dict) else {}

    # ------------------------------------------------------------ 免疫记忆
    def _bl(self):
        """读免疫记忆（blacklist.json）。坏了/缺了都当空表，**绝不抛**。

        为什么每次现读而不是缓存在内存里：可能同时有别的进程（后台复审、用户手改）
        在改这个文件；缓存住就会出现"刚加的黑名单这条不生效"这种灵异现象。
        文件很小（几百条也就几十 KB），读一次的代价可以忽略。
        """
        d = _read_json(self.blacklist_path, {})
        if not isinstance(d, dict):
            d = {}
        for k in ("sites", "fingerprints", "patterns"):
            if not isinstance(d.get(k), dict):
                d[k] = {}
        return d

    def _bl_save(self, d):
        d["updated"] = round(_now(), 3)
        _write_json(self.blacklist_path, d)
        return d

    def blacklist(self):
        "「」免疫记忆全貌：{「sites」: {...}, 「fingerprints」: {...}, 「patterns」: {...}}。「」"
        d = self._bl()
        return {"sites": d["sites"], "fingerprints": d["fingerprints"],
                "patterns": d["patterns"]}

    def is_blacklisted(self, domain):
        "「」这个域名在不在黑名单里（只看 active 的条目）。「」"
        rec = self._bl()["sites"].get(_domain_of(domain))
        return bool(isinstance(rec, dict) and rec.get("active", True))

    def blacklist_add(self, domain, reason="", kind="site"):
        """手动把某个域名/指纹/句式加进黑名单。

        kind："site" 域名 · "fingerprint" 内容指纹（传 sha1）· "pattern" 句式（传正则名）
        手动加入的条目 level 直接记 3（= 等效"犯过三次"），因为它代表**用户的明确意志**：
        用户说这个站别看了，载体不该再问第二遍。
        去掉"手动=满级"这条 → 用户手动加的黑名单只当一次轻微降权，等于没加。
        """
        k = str(kind or "site").strip().lower()
        d = self._bl()
        key = str(domain or "").strip()
        if not key:
            return {"added": False, "error": "没给域名/指纹"}
        now = round(_now(), 3)
        if k == "fingerprint":
            key = content_fingerprint(key) if len(key) != 40 else key
            rec = d["fingerprints"].get(key) or {}
            rec.update({"level": 3, "active": True, "manual": True, "at": now,
                        "reason": str(reason or "用户手动加入指纹黑名单")})
            d["fingerprints"][key] = rec
        elif k == "pattern":
            rec = d["patterns"].get(key) or {}
            rec.update({"level": 3, "active": True, "manual": True, "at": now,
                        "reason": str(reason or "用户手动加入句式黑名单")})
            d["patterns"][key] = rec
        else:
            key = _domain_of(key)
            rec = d["sites"].get(key) or {}
            rec.update({"level": 3, "active": True, "manual": True, "at": now,
                        "reason": str(reason or "用户手动加入黑名单")})
            d["sites"][key] = rec
        self._bl_save(d)
        self._log_verification({"event": "blacklist_add", "kind": k, "key": key,
                                "reason": str(reason or "")})
        return {"added": True, "kind": k, "key": key, "level": 3}

    def blacklist_remove(self, domain, kind="site"):
        """把某个域名移出黑名单。**条目本身保留**，只标 active=False（不是删除）。

        为什么"移除"也不删条目：免疫记忆的价值一半在"曾经坏过"这件事上 ——
        用户下次问"这个站为什么被拦过"，答案还在。
        去掉留痕 → 用户只能看到"它现在是好的"，看不见"它曾经骗过我们"。
        """
        k = str(kind or "site").strip().lower()
        d = self._bl()
        table = {"fingerprint": d["fingerprints"], "pattern": d["patterns"]}.get(k, d["sites"])
        key = str(domain or "").strip()
        if k == "site":
            key = _domain_of(key)
        elif k == "fingerprint" and len(key) != 40:
            key = content_fingerprint(key)
        rec = table.get(key)
        if not isinstance(rec, dict):
            return {"removed": False, "key": key, "error": "不在黑名单里"}
        rec["active"] = False
        rec["removed_at"] = round(_now(), 3)
        rec["note"] = "已从黑名单移除（历史保留，条目不删）"
        table[key] = rec
        self._bl_save(d)
        self._log_verification({"event": "blacklist_remove", "kind": k, "key": key})
        return {"removed": True, "key": key, "kept_history": True,
                "note": "免疫记忆只降级不删除：条目仍然留在 blacklist.json 里"}

    def trust_penalty(self, domain):
        "「」这个域名因为历史污染要被降多少可信度（0 / 0.2 / 0.5 / 1.0）。「」"
        rec = self._bl()["sites"].get(_domain_of(domain))
        if not isinstance(rec, dict):
            return 0.0
        try:
            return float(rec.get("trust_penalty") or 0.0)
        except Exception:      # noqa: silent-ok — 坏值当没有降权
            return 0.0

    def punish(self, domain, reason="", classes=None, url=""):
        """记一次污染：降权 → 累计到三次就进黑名单。返回免疫记忆里的那条记录。

        阶梯：一次降 0.2、两次降 0.5、三次进黑名单（active=True 且 blacklisted=True）。
        为什么是"累计"而不是"每次都降一点"：单次判错的概率不低（规则总有误杀），
        必须"同样的站反复出问题"才升级 —— 否则一次误杀就把一个好站永久打死。
        为什么到三次就进黑名单：三次都由不同的内容触发，说明这不是误杀，是这个站的常态。
        为什么同时写世界模型：世界模型是可信度的**唯一账本**（它们不能各记一套），
        但基线要固定（base_trust 只记第一次），否则"反复惩罚"会把可信度无限往下扣。
        去掉这条 → 一个站被抓 5 次后可信度变成负数级别的噪声值，行为不可解释。
        """
        dom = _domain_of(domain or url)
        if not dom:
            return {}
        d = self._bl()
        now = round(_now(), 3)
        rec = d["sites"].get(dom)
        if not isinstance(rec, dict):
            rec = {"level": 0, "reason": "", "at": now, "active": True,
                   "hits": 0, "base_trust": None, "trust_penalty": 0.0}
        rec["level"] = int(rec.get("level") or 0) + 1
        rec["hits"] = int(rec.get("hits") or 0) + 1
        rec["at"] = now
        rec["last_at"] = now
        cls = [str(c) for c in (classes or [])]
        rec["reason"] = str(reason or ("；".join(CLASS_CN.get(c, c) for c in cls)) or "内容判为污染")
        rec["classes"] = cls
        if not rec.get("base_trust"):
            rec["base_trust"] = self._trust_of(dom)     # 基线只记一次（见上面的说明）
        lvl = rec["level"]
        table = self.cfg["punish"]
        penalty = float(table.get(lvl, 1.0)) if lvl <= 2 else 1.0
        rec["trust_penalty"] = penalty
        if lvl >= 3:
            rec["active"] = True
            rec["blacklisted"] = True
            rec["blacklisted_at"] = now
        d["sites"][dom] = rec
        self._bl_save(d)
        # 世界模型是可信度的唯一账本：把"基线 - 累计降权"写回去（夹在 0~1）
        self._model_remember(dom, trust=_clamp01(float(rec["base_trust"]) - penalty, 0.0))
        self._log_verification({"event": "punish", "domain": dom, "level": lvl,
                                "penalty": penalty, "reason": rec["reason"],
                                "blacklisted": bool(rec.get("blacklisted")), "url": str(url or "")})
        logger.info("免疫记忆：%s 第 %d 次污染（trust 降 %.1f）｜%s", dom, lvl, penalty, rec["reason"])
        return rec

    def _trust_of(self, domain, default=0.5):
        """问世界模型这个站有多可信；没模型时用"不认识 = 0.5 - 历史降权"。

        为什么降权要在**没模型时**也生效：免疫记忆是防火墙自己的账本，
        它的结论不能因为"这次没接世界模型"就失效 —— 否则同一个站，
        在带模型的进程里被拦、在不带模型的进程里被放行。
        """
        dom = _domain_of(domain)
        base = None
        if self.model is not None:
            try:
                base = float(self.model.trust_of(dom, default))
            except Exception:      # noqa: silent-ok — 世界模型坏了就当它没说话
                base = None
        if base is None:
            base = float(default)
            return _clamp01(base - self.trust_penalty(dom), base)
        return _clamp01(base, base)

    def _model_remember(self, domain, trust=None, title="", note=""):
        "「」把可信度写回世界模型（没有模型就静默跳过）。**绝不抛**。「」"
        if self.model is None or not hasattr(self.model, "remember_site"):
            return {}
        try:
            return self.model.remember_site(domain, trust=trust, title=title, note=note) or {}
        except Exception as e:      # noqa: silent-ok — 模型写失败不能影响筛查结论
            logger.debug("写世界模型失败(%s)：%s", domain, e)
            return {}

    def decay(self, days=None, now=None):
        """长期不污染 → 逐步恢复（每次调用把"很久没再犯"的站降一级）。

        为什么必须有恢复机制：没有它，一个站被抓一次就被永久打折，
        等于把"一次误判"变成"终身判决"。免疫记忆该像免疫系统一样**会消退**。
        只降级、**不删条目**（保留历史），降到底回到 base_trust。
        去掉它 → 规则的一次误杀从此不可逆，用户只能手改 JSON 才能救回一个站。
        """
        limit_days = float(self.cfg["decay_days"] if days is None else days)
        t = _now() if now is None else float(now)
        d = self._bl()
        changed = []
        for dom, rec in list(d["sites"].items()):
            if not isinstance(rec, dict):
                continue
            last = rec.get("last_at") or rec.get("at") or 0
            try:
                idle_days = (t - float(last)) / 86400.0
            except Exception:      # noqa: silent-ok — 没时间戳就当作"刚犯过"，不恢复
                continue
            if idle_days < limit_days or int(rec.get("level") or 0) <= 0:
                continue
            rec["level"] = int(rec["level"]) - 1
            lvl = rec["level"]
            penalty = float(self.cfg["punish"].get(lvl, 0.0)) if lvl else 0.0
            rec["trust_penalty"] = penalty
            rec["decayed_at"] = round(t, 3)
            if lvl <= 0:
                rec["active"] = False
                rec["blacklisted"] = False
                rec["note"] = "长期不再污染：已恢复（条目保留，历史可查）"
            d["sites"][dom] = rec
            base = float(rec.get("base_trust") or 0.5)
            self._model_remember(dom, trust=_clamp01(base - penalty, base))
            changed.append({"domain": dom, "level": lvl, "penalty": penalty})
        if changed:
            self._bl_save(d)
            self._log_verification({"event": "decay", "days": limit_days, "recovered": changed})
        return {"recovered": changed, "count": len(changed), "days": limit_days}

    def _register_fingerprint(self, fp, url, domain, classes, reasons, active=True):
        """把判为污染的正文指纹记进免疫记忆（同一篇换域名再发也认得出来）。

        只有**整篇判为污染**（quarantine/discard）才登记指纹，且立刻 active。
        为什么"部分污染"（广告软文那种）不登记：那篇的干净部分已经被吸收了，
        把整篇指纹记成污染会导致"同一篇文章第二次出现时连干净部分也吃不到"。
        去掉这条区分 → 用户看到的现象是"第一次没吃全，第二次整篇不让吃"，很难解释。
        """
        d = self._bl()
        rec = d["fingerprints"].get(fp) or {}
        rec["level"] = int(rec.get("level") or 0) + 1
        rec["at"] = round(_now(), 3)
        rec["domain"] = domain
        rec["url"] = str(url or "")
        rec["classes"] = [str(c) for c in (classes or [])]
        rec["reason"] = "；".join(str(r) for r in (reasons or [])[:2]) or "内容判为污染"
        rec["active"] = bool(active)
        d["fingerprints"][fp] = rec
        self._bl_save(d)
        return rec

    def _register_pattern(self, name, why, sample=""):
        "「」把命中的注入/脚本句式记进免疫记忆（同一套路反复出现时就有据可查）。「」"
        d = self._bl()
        rec = d["patterns"].get(name) or {}
        rec["hits"] = int(rec.get("hits") or 0) + 1
        rec["at"] = round(_now(), 3)
        rec["why"] = str(why or "")
        rec["sample"] = str(sample or "")[:160]
        rec["active"] = bool(rec.get("manual") or rec["hits"] >= 3)
        d["patterns"][name] = rec
        self._bl_save(d)
        return rec

    # ------------------------------------------------------------ 日志
    def _log_absorption(self, rec):
        rec.setdefault("ts", round(_now(), 3))
        return _append_jsonl(self.absorption_path, rec)

    def _log_conflict(self, rec):
        rec.setdefault("ts", round(_now(), 3))
        return _append_jsonl(self.conflicts_path, rec)

    def _log_verification(self, rec):
        rec.setdefault("ts", round(_now(), 3))
        return _append_jsonl(self.verification_path, rec)

    # ------------------------------------------------------------ 闸门②：内容特征
    def _detect(self, raw, title=""):
        """在正文里找十类污染的**证据**（不是判决）。

        返回 {类名: {"why": [...], "spans": [{start,end,why,cls}], "n": 命中次数}}
        为什么只找证据、判决留给闸门：同一份证据在不同闸门下的分量不同
        （"研究显示…42%"这句话，闸门②当作"无出处"，闸门③才决定它算不算假消息）。
        把判决塞进检测里，规则就没法复用了。
        """
        hits = {}
        full = "%s\n%s" % (title or "", raw or "")

        def add(cls, why, span=None):
            h = hits.setdefault(cls, {"why": [], "spans": [], "n": 0})
            h["n"] += 1
            if why not in h["why"]:
                h["why"].append(why)
            if span:
                h["spans"].append({"start": int(span[0]), "end": int(span[1]),
                                   "why": why, "cls": cls})

        segs = split_segments(raw)
        seg_rules = (("prompt_injection", _INJECTION), ("malicious_code", _MALICIOUS),
                     ("phishing", _PHISHING), ("illegal", _ILLEGAL),
                     ("advertorial", _ADVERTORIAL), ("seo_spam", _SEO),
                     ("bias", _BIAS), ("fake_news", _FAKE_NEWS))
        for cls, rules in seg_rules:
            for rx, why in rules:
                rx = _rx(rx)          # 规则表里存的是**正则字符串**，用时才编译（见 _rx 的说明）
                for seg, s, e in segs:
                    if rx.search(seg):
                        add(cls, why, (s, e))
        # 有些规则天生是"跨段"的（整块 <script> 可能跨很多行），在全文上再扫一遍
        for rx, why in _MALICIOUS[:1]:
            rx = _rx(rx, _RE_S)       # 跨行匹配必须开 DOTALL，否则 ".*?" 遇到换行就停
            for m in rx.finditer(raw):
                add("malicious_code", why, (m.start(), m.end()))

        # —— 统计型判据（这三条不是"某个词命中"，是"整篇的形态不对"）——
        cuts = [x for x in (_cn_len(full),) if x]
        if cuts:
            total = cuts[0]
            # 感叹号密度：煽动式表达的形态特征（短篇里一堆感叹号）
            bangs = full.count("！") + full.count("!")
            if bangs >= 5 and total <= 400:
                add("bias", "感叹号密集（%d 个 / 共 %d 字）：煽动式表达" % (bangs, total))
            if bangs >= 12:
                add("bias", "整篇感叹号 %d 个：情绪密度过高" % bangs)
        rep_n, rep_s = _top_repeat(raw, int(self.cfg["repeat_gram"]))
        if rep_n >= int(self.cfg["repeat_times"]):
            add("seo_spam", "同一段文字重复出现 %d 次（%r…）：关键词堆砌/洗稿" % (rep_n, rep_s[:16]))
        # —— 过时：无时间戳，或时间戳很旧 ——
        ds = _dates(raw)
        if not ds:
            add("stale", "整篇没有任何时间戳：不知道它说的是什么时候的事（按过时降权）")
        else:
            newest = max(ds)
            age_days = (_now() - newest) / 86400.0
            if age_days > float(self.cfg["stale_days"]):
                add("stale", "最近的时间戳是 %s（约 %d 天前）：信息可能已经过时"
                    % (time.strftime("%Y-%m-%d", time.localtime(newest)), int(age_days)))
        return hits

    def _content_quality(self, raw, title="", hits=None):
        """闸门②的打分：事实陈述 vs 情绪煽动、引用 vs 断言、署名 vs 匿名、长度 vs 密度。

        返回 (0~1 的分, 特征 dict)。特征 dict 会进 gates 留痕 —— 分数低了要能说出低在哪。
        为什么这些维度要翻译成**加减分**而不是硬规则：
        它们是"质量"而不是"污染"，一篇没署名的技术文章仍然可能是对的。
        用硬规则判会大面积误杀；用打分则体现在"综合可信度不够就先别吃"。
        """
        hits = hits or {}
        feats = {}
        q = 0.5
        text = str(raw or "")
        n_all = _cn_len("%s\n%s" % (title or "", text)) or 0
        feats["chars"] = n_all
        signed = bool(_SIGN_RE.search(text)) or bool(re.search(r"(作者|来源|记者)\s*[:：]", title or ""))
        feats["signed"] = signed
        cite = bool(_CITE_RE.search(text))
        feats["cited"] = cite
        ds = _dates(text)
        feats["dated"] = bool(ds)
        anon = bool(_ANON_RE.search(text))
        feats["anonymous"] = anon
        if signed:
            q += 0.15          # 署名 = 有人为这段话负责
        if cite:
            q += 0.15          # 引用 = 可以顺着查下去
        if ds:
            q += 0.10          # 有时间戳 = 知道它是什么时候的事
        if 200 <= n_all <= 8000:
            q += 0.10          # 长度适中：太短没信息量，太长往往是采集站堆出来的
        elif n_all < 80:
            q -= 0.15
            feats["too_short"] = True
        if anon:
            q -= 0.10          # 匿名/爆料 = 没人负责
        # 情绪 vs 事实：煽动词命中越多，质量越低（上限扣 0.2，不能把分扣成负数）
        emo = hits.get("bias", {}).get("n", 0)
        if emo:
            q -= min(0.20, 0.10 * emo)
        feats["emotion_hits"] = emo
        # 信息密度：中文正文的去重字占比
        body = _TAG_RE.sub("", text)
        uniq = len(set(body)) / max(1, len(body)) if body else 0.0
        feats["uniq_ratio"] = round(uniq, 3)
        if 0 < uniq < 0.12 and len(body) > 400:
            q -= 0.10
            feats["low_density"] = True
        return _clamp01(q, 0.5), feats

    # ------------------------------------------------------------ 闸门③：交叉验证
    def _cross_check(self, raw, known_facts, sources):
        """对同一事实做交叉验证：≥2 独立源 → 可信；单源 → unverified；不一致 → 降权。

        返回 dict：{"pass":bool, "blocking":bool, "score":float, "reason":..., "evidence":[...],
                   "conflicts":[...], "sources":[...], "needs_user_confirm":bool}
        为什么"单源就算 unverified"而不是"看着挺像真的就信"：
        互联网上同一句话被复制一千遍是常态，但**复制不等于验证**。
        不标 unverified 的后果是：小焦会把一个来源的说法当成"大家都这么说"讲给用户。
        """
        facts = _fact_candidates(raw)
        known = [_fact_of(k) for k in (known_facts or [])]
        srcs = []
        for s in (sources or []):
            if isinstance(s, dict):
                sd = _domain_of(s.get("domain") or s.get("url") or "")
                srcs.append({"domain": sd or str(s.get("domain") or ""),
                             "text": str(s.get("text") or s.get("content") or ""),
                             "ts": s.get("ts")})
            else:
                srcs.append({"domain": "", "text": str(s), "ts": None})
        conflicts, agrees = [], []
        for kf in known:
            for f in facts:
                c = check_conflict(f, kf, new_score=None, from_user=kf.get("from_user"))
                if c["conflict"]:
                    c["against"] = "known_fact"
                    conflicts.append(c)
        for s in srcs:
            for f in facts:
                c = check_conflict(f, s.get("text") or "", old_ts=s.get("ts"))
                if c["conflict"]:
                    c["against"] = s.get("domain") or "source"
                    conflicts.append(c)
                elif _norm_fact(f)[:24] and _norm_fact(f)[:24] in _norm_fact(s.get("text") or ""):
                    agrees.append(s.get("domain") or "source")
        for s in srcs:
            for f in facts:
                if _norm_fact(f)[:20] and _norm_fact(f)[:20] in _norm_fact(s.get("text") or ""):
                    agrees.append(s.get("domain") or "source")
        ndom = len({a for a in agrees if a})
        ev = []
        if conflicts:
            for c in conflicts[:3]:
                ev.append("冲突（%s，%s）：%s ←→ %s" % (
                    c.get("against"), c.get("kind"),
                    str(c.get("new"))[:40], str(c.get("old"))[:40]))
        if agrees:
            ev.append("一致来源：%s" % "、".join(sorted({a for a in agrees if a}))[:100])
        user_conflict = any(c.get("old") and _user_owned(c.get("old"), known) for c in conflicts) \
            or any(c.get("against") == "known_fact" and c.get("needs_user_confirm") is False
                   and c.get("action") == "keep_old" and "用户" in str(c.get("why")) for c in conflicts)
        if conflicts:
            return {"pass": False, "blocking": bool(user_conflict), "score": 0.10,
                    "reason": ("与已核验事实/其它来源**互相矛盾**（%d 处）：不覆盖、不背书，"
                               "隔离并留档" % len(conflicts)),
                    "evidence": ev, "conflicts": conflicts, "sources": srcs,
                    "needs_user_confirm": True, "verified_sources": ndom}
        if ndom >= 2:
            return {"pass": True, "blocking": False, "score": 0.90,
                    "reason": "≥2 个独立来源交叉验证通过：%s" % "、".join(sorted({a for a in agrees if a})),
                    "evidence": ev, "conflicts": [], "sources": srcs,
                    "needs_user_confirm": False, "verified_sources": ndom}
        if ndom == 1 or known:
            return {"pass": True, "blocking": False, "score": 0.62,
                    "reason": "只有 %d 个可核对来源，标记 unverified（吸收但不背书）" % max(ndom, len(known)),
                    "evidence": ev, "conflicts": [], "sources": srcs,
                    "needs_user_confirm": False, "verified_sources": ndom, "unverified": True}
        return {"pass": True, "blocking": False, "score": 0.55,
                "reason": "没有第二个来源可交叉验证，标记 unverified（宁可不背书，也不猜）",
                "evidence": ev, "conflicts": [], "sources": srcs,
                "needs_user_confirm": False, "verified_sources": 0, "unverified": True}

    # ------------------------------------------------------------ 闸门⑤：与用户匹对
    def _profile_gate(self, raw, title, topic, profile):
        """与用户画像相关吗？与**已有记忆**冲突吗？

        为什么"不相关"就不吸收：小焦的记忆不是网盘，是**它自己的脑子**。
        把跟自己、跟用户都没关系的东西塞进去，只会稀释检索（相关的更难被想起来）。
        为什么冲突只"标待确认"而不自动改记忆：记忆里那条可能是用户亲口说的、
        也可能是辛苦攒下的结论；自动覆盖是不可逆的（而外部信息是随时会变的）。
        去掉这道闸 → 小爬虫抓到什么，小焦的"信念"就跟着变一次。
        """
        kws = _profile_keywords(profile)
        rel = None
        if kws:
            hay = "%s\n%s\n%s" % (topic or "", title or "", raw or "")
            hit = [k for k in kws if k and str(k) in hay]
            rel = 1.0 if hit else 0.0
        conflicts = []
        mem_hits = 0
        if self.memory is not None or self.allow_memory_import:
            probe = (topic or title or (raw or "")[:60] or "").strip()
            for m in self._memory_search(probe, top_k=5):
                mem_hits += 1
                text = str(m.get("text") or "")
                mts = m.get("ts")
                from_user = bool((m.get("meta") or {}).get("from_user")) if isinstance(m.get("meta"), dict) else False
                for f in _fact_candidates(raw, limit=12):
                    c = check_conflict(f, {"text": text, "ts": mts, "from_user": from_user,
                                           "id": m.get("id")})
                    if c["conflict"]:
                        c["against"] = "memory:%s" % (m.get("id") or "")
                        c["mem_id"] = m.get("id") or ""
                        # 旧记忆可信度按"它是既有事实"来算：用户说的按 1.0，其它按 0.8。
                        # 为什么旧记忆可以被新信息挑战：世界会变，记忆也该能更新 ——
                        # 但更新的门槛（≥0.7 且旧记忆超 30 天）由 check_conflict 把关。
                        conflicts.append(c)
                        break
        if conflicts:
            need = any(c.get("needs_user_confirm") for c in conflicts)
            user_owned = any("用户" in str(c.get("why") or "") for c in conflicts)
            return {"pass": False, "blocking": True, "score": 0.10, "relevance": rel,
                    "reason": ("与已有记忆冲突（%d 处）%s：标为**待用户确认**，"
                               "绝不擅自改记忆" % (len(conflicts),
                                                "，其中涉及用户亲口说过的事实" if user_owned else "")),
                    "evidence": ["%s ←→ %s" % (str(c.get("new"))[:36], str(c.get("old"))[:36])
                                 for c in conflicts[:3]],
                    "conflicts": conflicts, "needs_user_confirm": True,
                    "memory_hits": mem_hits, "keywords": kws[:8]}
        if rel == 0.0:
            return {"pass": False, "blocking": False, "score": 0.0, "relevance": 0.0,
                    "reason": "与用户画像完全不相关（画像关键词 %s 一个都没出现）：不吸收，"
                              "记忆只放跟用户有关的东西" % "、".join(kws[:5]),
                    "evidence": [], "conflicts": [], "needs_user_confirm": False,
                    "memory_hits": mem_hits, "keywords": kws[:8], "irrelevant": True}
        return {"pass": True, "blocking": False,
                "score": 1.0 if rel == 1.0 else 0.75, "relevance": rel,
                "reason": ("与用户画像相关（命中 %s）" % "、".join([k for k in kws if k in (raw or "")][:5])
                           if rel == 1.0 else
                           ("与已有记忆无冲突（检索到 %d 条相关记忆）" % mem_hits if mem_hits
                            else "没有提供用户画像，跳过相关性判定（默认中性）")),
                "evidence": [], "conflicts": [], "needs_user_confirm": False,
                "memory_hits": mem_hits, "keywords": kws[:8]}

    # ------------------------------------------------------------ 闸门④：注入检测
    def _injection_gate(self, hits, raw):
        """闸门④：提示词注入 / 藏脚本。命中即**硬拦**，不看综合分。

        为什么必须硬拦、不能"降权后看总分"：这类内容是**动作型**危险 ——
        综合分是对"可信度"的度量，而"忽略之前的指令"这句话的可信度是[无关的]：
        它哪怕 99% 的内容是真的，只要模型照做了，小焦就被远程遥控了。
        去掉这道闸（合并进内容特征按总分判）→ 一条精心包装的注入页能靠"其它部分很干净"过关。
        """
        inj = hits.get("prompt_injection") or {}
        mal = hits.get("malicious_code") or {}
        both = []
        for cls, h in (("prompt_injection", inj), ("malicious_code", mal)):
            for why in (h.get("why") or []):
                both.append("%s：%s" % (CLASS_CN[cls], why))
                self._register_pattern("%s:%s" % (cls, why[:24]), why)
        blocking = bool(inj.get("n") or mal.get("n"))
        if not blocking:
            return {"pass": True, "blocking": False, "score": 1.0,
                    "reason": "没有发现任何越权指令/隐藏脚本（这一关是硬规则，不靠模型判）",
                    "evidence": [], "spans": []}
        return {"pass": False, "blocking": True, "score": 0.0,
                "reason": "发现网页里藏着指令或可执行代码（%s）：**直接拦截，绝不执行**"
                          % "；".join(both[:2]),
                "evidence": both[:5],
                "spans": (inj.get("spans") or []) + (mal.get("spans") or [])}

    # ------------------------------------------------------------ 主流程
    def screen(self, url, content, title="", topic="", profile=None,
               known_facts=None, sources=None):
        """五道闸门逐步过，返回 ScreenResult（每道闸的判定与证据都在 gates 里留痕）。

        顺序是设计的一部分：① 来源 → ② 内容 → ③ 交叉验证 → ④ 注入 → ⑤ 与用户匹对。
        · 为什么①最先：来源不可信时**根本不值得花力气分析内容**（也省下一次抓取）；
        · 为什么④在⑤之前：注入是"动作型危险"，不该因为"这条跟用户无关"就放过它；
        · 为什么⑤最后：它是"配不配进脑子"的判断，必须建立在前四道已经验完货的基础上。
        黑名单命中时**直接返回**（passed=0，后面四道闸不跑）——
        这既是效率，也是语义："这个站我们连看都不看了"。
        """
        try:
            return self._screen_inner(url, content, title, topic, profile, known_facts, sources)
        except Exception as e:      # noqa: silent-ok — 筛查自己出问题必须保守（不许放行）
            logger.exception("防火墙筛查内部异常，按最保守方式处理")
            r = ScreenResult(url=str(url or ""), domain=_domain_of(url), decision="quarantine",
                             passed=0, classes=[], score=0.0, clean_text="",
                             reasons=["防火墙内部异常（%s）：按最保守方式处理，先放进隔离区等人工看"
                                      % type(e).__name__],
                             gates={"1_source": {"pass": False, "blocking": True,
                                                 "reason": "内部异常，未完成筛查"}})
            self._log_absorption({"event": "screen", "url": r.url, "domain": r.domain,
                                  "decision": r.decision, "passed": 0, "score": 0.0,
                                  # 【2026-09-18 改成中文】原来是英文短码 "internal" ——
                                  #   这条记录会进隔离区日志给人看，按项目铁律 P6「面向用户的
                                  #   error 文案都是中文」，改成中文；同时保留原因（异常类型在
                                  #   `reasons` 那一栏里，见上面 ScreenResult）。
                                  "classes": [], "error": "内部异常（筛查未完成，已按最保守方式处理）"})
            return r

    def _screen_inner(self, url, content, title, topic, profile, known_facts, sources):
        u = str(url or "").strip()
        dom = _domain_of(u)
        raw = str(content or "")
        fp = content_fingerprint(raw)
        gates = {}
        reasons = []
        bl = self._bl()
        enabled = self.enabled()

        # ---------------- 闸门①：来源可信度 ----------------
        g1 = {"pass": True, "blocking": False, "trust": None, "first_visit": False,
              "evidence": [], "enabled": enabled}
        site = bl["sites"].get(dom) if dom else None
        if isinstance(site, dict) and site.get("active", True):
            g1.update(pass_=False)
            g1["pass"] = False
            g1["blocking"] = True
            lvl = int(site.get("level") or 0)
            g1["reason"] = ("来源 %s 在免疫黑名单里（%d 次污染：%s）：这个站**直接不进**，"
                            "后面几道闸也就不必跑了"
                            % (dom or u, lvl, str(site.get("reason") or "历史污染")[:60]))
            g1["evidence"] = ["blacklist site level=%d" % lvl]
            gates["1_source"] = g1
            return self._finish(u, dom, raw, title, topic, fp, gates,
                                decision="discard", reasons=[g1["reason"]], score=0.0,
                                classes=[], clean_text=raw, spans=[], hits={},
                                enabled=enabled, extra={"blocked_by": "blacklist_site"})
        fprec = bl["fingerprints"].get(fp) if fp else None
        if isinstance(fprec, dict) and fprec.get("active", True):
            g1.update(pass_=False)
            g1["pass"] = False
            g1["blocking"] = True
            g1["reason"] = ("内容指纹命中免疫记忆：同一篇内容曾在 %s 被判为污染（%s），"
                            "**换域名再发也照样认得出**，直接不进"
                            % (str(fprec.get("domain") or "别的站"),
                               str(fprec.get("reason") or "")[:60]))
            g1["evidence"] = ["fingerprint=%s" % fp[:12], "first_seen_domain=%s" % fprec.get("domain")]
            gates["1_source"] = g1
            return self._finish(u, dom, raw, title, topic, fp, gates,
                                decision="discard", reasons=[g1["reason"]], score=0.0,
                                classes=list(fprec.get("classes") or []), clean_text=raw,
                                spans=[], hits={}, enabled=enabled,
                                extra={"blocked_by": "blacklist_fingerprint"})
        trust = self._trust_of(dom, 0.5)
        g1["trust"] = round(trust, 3)
        g1["penalty"] = round(self.trust_penalty(dom), 3)
        first_visit = not self._known_domain(dom)
        g1["first_visit"] = first_visit
        if trust < float(self.cfg["trust_floor"]):
            g1["pass"] = False
            g1["blocking"] = True
            g1["reason"] = ("来源 %s 的可信度只有 %.2f（低于 %.2f）：先隔离，等它攒够信用再说"
                            % (dom or u, trust, float(self.cfg["trust_floor"])))
            reasons.append(g1["reason"])
        else:
            g1["reason"] = ("来源 %s 可信度 %.2f（%s）%s"
                            % (dom or u, trust,
                               "世界模型记录「 if self.model is not None else 」没有世界模型，按半信半疑 0.5 起算",
                               "；**首访站点：这次只做浅吸收**（不覆盖任何旧记忆）" if first_visit else ""))
        gates["1_source"] = g1

        # ---------------- 闸门②：内容特征 ----------------
        hits = self._detect(raw, title)
        quality, feats = self._content_quality(raw, title, hits)
        hard_hits = []
        for cls in HARD_CLASSES:
            if hits.get(cls, {}).get("n"):
                hard_hits.append(cls)
        if hits.get("fake_news", {}).get("n", 0) >= 2:
            hard_hits.append("fake_news")          # 多条假消息特征同时命中 → 按硬污染处理
        elif hits.get("fake_news", {}).get("n") and not _CITE_RE.search(raw):
            hard_hits.append("fake_news")          # 有耸动特征且通篇说不出出处 → 硬拦
        soft_hits = [c for c in hits if c not in hard_hits]
        g2 = {"pass": not hard_hits, "blocking": bool(hard_hits), "score": round(quality, 3),
              "classes": sorted(hits.keys()), "features": feats,
              "hard": hard_hits, "soft": soft_hits,
              "spans": [s for c in hits for s in (hits[c].get("spans") or [])
                        if c in REMOVABLE_CLASSES],
              "evidence": ["%s：%s" % (CLASS_CN[c], (hits[c]["why"] or [""])[0])
                           for c in sorted(hits.keys())][:6]}
        g2["degraded"] = bool(soft_hits)
        g2["reason"] = ("内容特征判为**硬污染**（%s）：不看总分直接隔离"
                        % "、".join(CLASS_CN[c] for c in hard_hits) if hard_hits else
                        ("内容特征合格；但有 %s，已降权并做局部消毒"
                         % "、".join(CLASS_CN[c] for c in soft_hits) if soft_hits else
                         "内容特征合格：事实陈述为主、有引用有署名，长度与信息密度正常"))
        gates["2_content"] = g2
        if hard_hits:
            reasons.append(g2["reason"])
        elif soft_hits:
            reasons.append("部分污染已消毒：%s（污染段落已摘进隔离区，干净部分才吸收）"
                           % "、".join(CLASS_CN[c] for c in soft_hits))

        # ---------------- 闸门③：交叉验证 ----------------
        g3 = self._cross_check(raw, known_facts, sources)
        gates["3_cross"] = g3
        if not g3["pass"]:
            reasons.append(g3["reason"])
            for c in (g3.get("conflicts") or []):
                c["url"] = u
                c["domain"] = dom
                self._log_conflict(dict(c, stage="3_cross"))

        # ---------------- 闸门④：注入检测 ----------------
        g4 = self._injection_gate(hits, raw)
        gates["4_injection"] = g4
        if not g4["pass"]:
            reasons.append(g4["reason"])
            reasons.append("这条内容**不会被「执行」也不会被吸收**：指令只当作「污染证据」留档，"
                           "永远不会进入小焦的上下文")

        # ---------------- 消毒（在综合分之前做，因为 clean_text 要交给闸门⑤判相关/冲突）----
        spans = list(g2.get("spans") or []) + list(g4.get("spans") or [])
        clean_text = strip_spans(raw, spans)
        if not clean_text.strip() and raw.strip():
            clean_text = ""      # 全篇都是污染：干净的什么都不剩（不是"把原文当干净"）

        # ---------------- 闸门⑤：与用户匹对 ----------------
        g5 = self._profile_gate(clean_text or raw, title, topic, profile)
        gates["5_profile"] = g5
        if not g5["pass"]:
            reasons.append(g5["reason"])
            for c in (g5.get("conflicts") or []):
                c["url"] = u
                c["domain"] = dom
                self._log_conflict(dict(c, stage="5_profile"))

        # ---------------- 综合分与判决 ----------------
        w = self.cfg["weights"]
        pen = self.cfg["penalty"]
        trust_score = trust
        content_score = quality
        cross_score = float(g3.get("score") or 0.0)
        inj_score = float(g4.get("score") or 0.0)
        prof_score = float(g5.get("score") if g5.get("score") is not None else 0.75)
        score = (w["source"] * trust_score + w["content"] * content_score
                 + w["cross"] * cross_score + w["injection"] * inj_score
                 + w["profile"] * prof_score)
        penalties = []
        for c in soft_hits:
            score -= float(pen["soft_class"])
            penalties.append("%s -%.2f" % (CLASS_CN[c], float(pen["soft_class"])))
        if first_visit:
            score -= float(pen["first_visit"])
            penalties.append("首访站点 -%.2f" % float(pen["first_visit"]))
        if g3.get("unverified"):
            score -= float(pen["unverified"])
            penalties.append("单源未验证 -%.2f" % float(pen["unverified"]))
        if not g3["pass"]:
            score -= float(pen["cross_conflict"])
            penalties.append("交叉验证冲突 -%.2f" % float(pen["cross_conflict"]))
        score = _clamp01(score, 0.0)

        blocking = [k for k, g in gates.items() if g.get("blocking")]
        classes = sorted(hits.keys())
        if g3.get("conflicts"):
            classes = sorted(set(classes) | {"contradiction"})
        if g5.get("conflicts"):
            classes = sorted(set(classes) | {"contradiction"})
        decision = "quarantine"
        if blocking:
            decision = "quarantine"
        elif g5.get("irrelevant"):
            decision = "discard"
            reasons.append("结论：**不吸收**（不是因为它脏，而是因为它跟用户无关）")
        elif score >= float(self.cfg["accept_min"]):
            decision = "accept"
        else:
            reasons.append("综合可信度 %.2f 低于门槛 %.2f：宁可吸收慢，也不能把不确定的东西"
                           "当成已知事实" % (score, float(self.cfg["accept_min"])))
        if not enabled:
            # 关掉防火墙 = **只暂停，不销毁**：照常算分、照常留痕、照常登记免疫记忆，
            # 只是不拦。为什么还要算：用户下次打开时，这段时间的污染记录仍然有效。
            decision = "accept"
            reasons.append("用户已关闭防火墙：本次只留痕、不拦截（免疫记忆照常登记）")
        passed = sum(1 for g in gates.values() if g.get("pass"))
        return self._finish(u, dom, raw, title, topic, fp, gates, decision, reasons, score,
                            classes, clean_text, spans, hits, enabled=enabled,
                            trust=trust, penalties=penalties)

    def _finish(self, u, dom, raw, title, topic, fp, gates, decision, reasons, score,
                classes, clean_text, spans, hits, enabled=True, trust=None, penalties=None,
                extra=None):
        """统一收尾：登记免疫记忆 → 需要时进隔离区 → 写台账 → 返回 ScreenResult。

        为什么收尾要集中在一处：**每一条路径都必须做同样几件事**
        （登记污染、留隔离底、写台账）。散在各分支里，早晚有一条路径忘记登记，
        那条路径的污染就永远不进免疫记忆 —— 而它恰恰是最需要被记住的那类（黑名单短路）。
        """
        needs_confirm = bool(any((gates.get(k) or {}).get("needs_user_confirm")
                                 for k in ("3_cross", "5_profile")))
        qid = ""
        if decision in ("quarantine", "discard"):
            # 原文留底：这是"消毒"的另一半 —— 不吃，但也不丢。
            qid = self.quarantine.put(url=u, raw_text=raw, clean_text=clean_text,
                                      classes=classes, reasons=reasons, spans=spans,
                                      domain=dom,
                                      meta={"topic": topic, "title": title,
                                            "score": round(float(score), 3),
                                            "decision": decision,
                                            "passed": sum(1 for g in gates.values() if g.get("pass")),
                                            "needs_user_confirm": needs_confirm})
            if hits:
                # 只有硬污染/整篇判脏才登记"整篇指纹"（部分污染的那篇干净部分还要吃，见函数说明）
                hard = any(c in HARD_CLASSES for c in classes) or not (clean_text or "").strip()
                if hard:
                    self._register_fingerprint(fp, u, dom, classes, reasons, active=True)
            self.punish(dom, reason=(reasons[0] if reasons else ""), classes=classes, url=u)
        r = ScreenResult(url=u, domain=dom, decision=decision,
                         passed=int(sum(1 for g in gates.values() if g.get("pass"))),
                         classes=list(classes or []), reasons=list(reasons or []),
                         score=round(float(score), 3), clean_text=clean_text or "",
                         gates=gates, qid=qid, topic=topic, fingerprint=fp,
                         needs_user_confirm=needs_confirm)
        rec = {"event": "screen", "url": u, "domain": dom, "decision": decision,
               "passed": r.passed, "score": r.score, "classes": r.classes,
               "reasons": r.reasons[:3], "qid": qid, "fingerprint": fp[:12],
               "trust": trust, "penalties": penalties or [], "enabled": bool(enabled),
               "title": str(title or "")[:120], "topic": str(topic or "")[:80],
               "chars": len(raw), "clean_chars": len(clean_text or "")}
        if extra:
            rec.update(extra)
        self._log_absorption(rec)
        return r

    def _known_domain(self, dom):
        """这个域名是不是"以前打过交道"（= 世界模型里有记录，或以前吸收过它的东西）。

        为什么要读自己的吸收台账：没有世界模型时（离线脚本、自测），
        "首访"就只能从台账里看 —— 否则每次筛查都算首访，浅吸收规则会永远生效。
        """
        d = _domain_of(dom)
        if not d:
            return False
        if self.model is not None:
            try:
                if d in (getattr(self.model, "sites", {}) or {}):
                    return True
            except Exception:      # noqa: silent-ok — 模型读不动就当不知道
                pass
        for rec in _read_jsonl(self.absorption_path, limit=2000):
            if rec.get("event") == "absorb" and rec.get("domain") == d and rec.get("absorbed"):
                return True
        return False

    # ------------------------------------------------------------ 吸收 / 隔离
    def _mem_add(self, text, kind="fact", entities=None, meta=None):
        """写主记忆。返回 (mem_id, note)。**绝不抛**，拿不到记忆库就写自己的台账兜底。

        为什么"拿不到就写 JSONL"而不是"抛给上层"或"干脆不记"：
        信息已经过了五道闸、是被判定为干净的东西；因为记忆库不可用就把它丢掉，
        等于把"筛查劳动"白费（下次还得重新爬、重新筛）。
        写成 JSONL 至少留住了内容本身，等记忆库回来时可以补录。
        """
        m = self.memory
        if m is None and self.allow_memory_import:
            m = _default_memory()
        if m is not None:
            fn = getattr(m, "add_memory", None)
            if callable(fn):
                try:
                    mid = fn(text, kind=kind, entities=list(entities or []), meta=meta or {})
                    return str(mid or ""), ""
                except Exception as e:      # noqa: silent-ok — 记忆库写失败退回台账兜底
                    logger.warning("写记忆库失败，退回台账兜底：%s", e)
                    return "", "记忆库写入失败（%s），已写进 absorption 台账兜底" % type(e).__name__
        return "", "记忆库不可用，已写进 absorption 台账兜底"

    def _memory_search(self, query, top_k=5):
        "「」检索已有记忆（给闸门⑤查冲突用）。拿不到记忆库就返回 []（**绝不抛**）。「」"
        m = self.memory
        if m is None and self.allow_memory_import:
            m = _default_memory()
        fn = getattr(m, "search_memory", None) if m is not None else None
        if not callable(fn):
            return []
        try:
            hits = fn(query, top_k=top_k) or []
        except Exception as e:      # noqa: silent-ok — 检索失败不能影响筛查结论
            logger.debug("检索记忆失败：%s", e)
            return []
        out = []
        for h in hits:
            if isinstance(h, dict):
                out.append(h)
        return out

    def absorb(self, screen, url="", topic="", meta=None):
        """把筛查结论落地：accept → 主记忆；quarantine/discard → 隔离区（原文留底）。

        返回 dict：
          accept    {"absorbed": True, "mem_id":…, "qid":…（部分污染时的隔离编号）, …}
          其它      {"absorbed": False, "qid":…, "decision":…, "reasons":[…]}
        **任何情况下都不删东西**：不吸收的内容一定在隔离区里有一份原文。
        """
        if not isinstance(screen, ScreenResult):
            raise TypeError("absorb 需要 ScreenResult（先调 screen()）")
        u = str(url or screen.url or "")
        dom = screen.domain or _domain_of(u)
        m = dict(meta or {})
        if screen.decision != "accept":
            qid = screen.qid or self.quarantine.put(
                url=u, raw_text="", clean_text=screen.clean_text, classes=screen.classes,
                reasons=screen.reasons, domain=dom, spans=[], meta=m)
            self._log_absorption({"event": "absorb", "absorbed": False, "decision": screen.decision,
                                  "url": u, "domain": dom, "qid": qid, "chars": 0,
                                  "clean_chars": len(screen.clean_text or ""),
                                  "classes": screen.classes, "score": screen.score,
                                  "passed": screen.passed, "topic": topic,
                                  "reasons": screen.reasons[:3], "meta": m})
            return {"absorbed": False, "qid": qid, "decision": screen.decision,
                    "classes": list(screen.classes), "reasons": list(screen.reasons),
                    "score": screen.score, "passed": screen.passed,
                    "note": ("已进隔离区（原文留底，**没有删除任何东西**）：%s"
                             % ("；".join(screen.reasons[:2]) or "待复审"))}
        text = (screen.clean_text or "").strip()
        if not text:
            # 极端情况：全篇都是污染段（clean_text 被摘空）。这时**不能**假装吸收成功，
            # 否则主记忆里会出现一条空记忆（等于"什么都没记住但以为记住了"）。
            qid = self.quarantine.put(url=u, raw_text="", clean_text="",
                                      classes=screen.classes or ["seo_spam"],
                                      reasons=list(screen.reasons) + ["消毒后没有任何干净内容可吸收"],
                                      domain=dom, meta=m)
            self._log_absorption({"event": "absorb", "absorbed": False, "decision": "quarantine",
                                  "url": u, "domain": dom, "qid": qid, "chars": 0,
                                  "classes": screen.classes, "topic": topic,
                                  "reasons": ["消毒后无干净内容"]})
            return {"absorbed": False, "qid": qid, "decision": "quarantine",
                    "reasons": list(screen.reasons) + ["消毒后没有任何干净内容可吸收"],
                    "note": "整篇都是污染片段：只留下隔离副本，主记忆不写空条目"}
        shallow = bool(screen.gates.get("1_source", {}).get("first_visit"))
        mem_meta = dict(m)
        mem_meta.update({"url": u, "domain": dom, "source": "world.firewall",
                         "score": screen.score, "classes": screen.classes,
                         "shallow": shallow,
                         "unverified": bool(screen.gates.get("3_cross", {}).get("unverified"))})
        if shallow:
            # 首访站点：只做浅吸收 —— 记忆里明确标上"这条只有一个来源、还没被验证过"。
            # 为什么要标：将来查冲突时，"浅吸收"的记忆不该跟用户亲口说的事实同等对待。
            mem_meta["from_user"] = False
            mem_meta["note"] = "首访站点浅吸收（单源未验证）"
        mem_id, note = self._mem_add(text, kind="fact", entities=[u] if u else [], meta=mem_meta)
        qid = ""
        spans = [s for g in (screen.gates.get("2_content"), screen.gates.get("4_injection"))
                 if isinstance(g, dict) for s in (g.get("spans") or [])]
        if spans or screen.classes:
            # 部分污染（广告软文那类）：干净部分已经吸收，**污染片段单独进隔离区留档**。
            # 为什么 accept 也要进隔离区：用户有权知道"小焦吃进去的东西里，剪掉了哪几段"。
            qid = self.quarantine.put(url=u, raw_text="", clean_text=screen.clean_text,
                                      classes=screen.classes, reasons=screen.reasons,
                                      spans=spans, domain=dom,
                                      meta=dict(mem_meta, partial=True))
        rec = {"event": "absorb", "absorbed": True, "decision": "accept", "url": u,
               "domain": dom, "mem_id": mem_id, "qid": qid, "chars": len(text),
               "clean_chars": len(text), "classes": screen.classes,
               "score": screen.score, "passed": screen.passed, "topic": topic,
               "shallow": shallow, "memory_note": note, "meta": m,
               "reasons": screen.reasons[:2]}
        if not mem_id:
            # 记忆库不可用：把正文也写进台账（否则这次吸收等于什么都没留下）
            rec["text"] = text
        self._log_absorption(rec)
        return {"absorbed": True, "mem_id": mem_id, "qid": qid, "decision": "accept",
                "chars": len(text), "classes": list(screen.classes),
                "score": screen.score, "passed": screen.passed, "shallow": shallow,
                "note": note or ("已写进主记忆（%d 字）" % len(text))}

    # ------------------------------------------------------------ 用户可操作
    def release(self, qid, note=""):
        """手动放行隔离内容 → 写进主记忆，并把隔离条目标成 released（**条目仍然保留**）。

        为什么放行后不把隔离条目删掉：它是"这条曾经被判过污染"的证据。
        用户以后问"当初为什么没吸收这条"，答案在条目里（reasons/spans 都还在）。
        去掉留痕 → 隔离区变成"进出不留痕"的黑箱，规则改进就没了依据。
        """
        rec = self.quarantine.get(qid)
        if not rec:
            return {"released": False, "qid": str(qid or ""), "error": "找不到这个隔离条目"}
        text = str(rec.get("clean_text") or "").strip() or str(rec.get("raw_text") or "").strip()
        if not text:
            return {"released": False, "qid": rec.get("qid"), "error": "条目里没有可放行的内容"}
        u = str(rec.get("url") or "")
        mem_id, mem_note = self._mem_add(
            text, kind="fact", entities=[u] if u else [],
            meta={"url": u, "domain": rec.get("domain") or _domain_of(u),
                  "source": "world.firewall.release", "released_from": rec.get("qid"),
                  "from_user": True,
                  "note": "用户手动放行（用户的话 > 互联网信息）"})
        stored = "memory" if mem_id else "jsonl"
        rec2 = self.quarantine.mark(rec.get("qid"), ST_RELEASED,
                                    note=(note or "用户手动放行：内容已进主记忆（本条留底不删）"))
        entry = {"event": "release", "qid": rec.get("qid"), "mem_id": mem_id,
                 "stored": stored, "chars": len(text), "url": u,
                 "memory_note": mem_note}
        if not mem_id:
            entry["text"] = text        # 记忆库不可用时，放行的内容至少要留在流水里
        self._log_verification(entry)
        # 放行意味着"这条被误判了"：把它的指纹从免疫记忆里降级（否则下次换域名再发还会被拦）
        fp = content_fingerprint(rec.get("raw_text") or text)
        d = self._bl()
        fpr = d["fingerprints"].get(fp)
        if isinstance(fpr, dict) and fpr.get("active", True):
            fpr["active"] = False
            fpr["note"] = "用户手动放行过同一篇内容：指纹降级（历史保留）"
            self._bl_save(d)
        return {"released": True, "qid": rec.get("qid"), "mem_id": mem_id, "stored": stored,
                "status": str((rec2 or {}).get("status") or ST_RELEASED), "chars": len(text),
                "note": "已进主记忆；隔离条目保留（只改了状态，没有删除）"}

    def reject(self, mem_id_or_text, reason=""):
        """手动驳回一条主记忆 → **搬到隔离区**（不是删除：主记忆里那条仍在，隔离区多一份副本）。

        为什么"驳回"只能是搬家：
        ① 红线不许删任何文件；
        ② 记忆库（core.memory_vec）本身**没有单条删除 API**（只有整库重置），
           从这里硬删是越权且危险的。
        所以驳回的真实语义是"**标记为不再使用** + 把内容搬进隔离区等人工处置"：
        `rejected_memories.json` 记下 id，检索侧可以据此跳过它。
        去掉这个标记 → 用户说"这条是错的，别再说了"，小焦下次检索还是会把那条捞出来用。
        """
        arg = str(mem_id_or_text or "").strip()
        if not arg:
            return {"rejected": False, "error": "没给记忆 id 或内容"}
        mem_id, text, url, dom = "", "", "", ""
        known = self._find_absorbed(arg)
        if known:
            mem_id = arg
            url = str(known.get("url") or "")
            dom = str(known.get("domain") or "")
            text = str(known.get("text") or "")
        if not text:
            text = self._find_in_memory_bank(arg) if not _looks_like_text(arg) else arg
        if not text and not known:
            text = arg
        if not text:
            return {"rejected": False, "error": "找不到这条记忆的内容（主记忆库可能已不在同一台机器上）"}
        qid = self.quarantine.put(url=url or ("mem://%s" % (mem_id or "unknown")),
                                  raw_text=text, clean_text="",
                                  classes=["user_rejected"],
                                  reasons=[("用户手动驳回：%s" % (reason or "这条记忆不许再参与回答"))],
                                  domain=dom, meta={"from_memory": mem_id, "kind": "rejected_memory"})
        rj = _read_json(self.rejected_path, {}) or {}
        if not isinstance(rj, dict):
            rj = {}
        key = mem_id or qid
        rj[key] = {"at": round(_now(), 3), "qid": qid, "reason": str(reason or ""),
                   "chars": len(text), "active": True,
                   "note": "标记为不再使用；主记忆里那条**没有被删除**（红线：绝不删东西）"}
        _write_json(self.rejected_path, rj)
        self._log_verification({"event": "reject", "mem_id": mem_id, "qid": qid,
                                "chars": len(text), "reason": str(reason or "")})
        return {"rejected": True, "qid": qid, "mem_id": mem_id, "moved": True,
                "chars": len(text),
                "marker": key,
                "note": "已搬进隔离区并标记不再使用；**文件都还在**（驳回是搬家，不是删除）"}

    def rejected_memories(self):
        "「」被用户驳回、不再参与回答的记忆标记（检索侧可以据此跳过）。「」"
        d = _read_json(self.rejected_path, {}) or {}
        return d if isinstance(d, dict) else {}

    def _find_absorbed(self, mem_id):
        "「」在自己的吸收台账里按 mem_id 找当时的记录（含兜底时留下的正文）。「」"
        for rec in reversed(_read_jsonl(self.absorption_path, limit=5000)):
            if rec.get("event") == "absorb" and rec.get("mem_id") == mem_id:
                return rec
        return {}

    def _find_in_memory_bank(self, mem_id):
        """去记忆库文件里按 id 找正文（**只读**，绝不改写记忆库）。

        为什么允许直接读文件：`memory_vec` 的公开 API 只有"加/搜/统计"，
        没有"按 id 取"。为了一个只读需求去改那个模块（它是别人的、且有硬隔离约束）
        风险更大；只读它自己的公开路径 `memory_vec.path()` 是安全的。
        读不到就返回 ""，由调用方按"找不到内容"如实回报。
        """
        if not mem_id:
            return ""
        try:
            m = self.memory if self.memory is not None else _default_memory()
            p = m.path() if m is not None and callable(getattr(m, "path", None)) else ""
        except Exception:      # noqa: silent-ok — 拿不到路径就当找不到
            p = ""
        if not p or not os.path.exists(p):
            return ""
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line or mem_id not in line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:      # noqa: silent-ok — 坏行跳过
                        continue
                    if str(obj.get("id") or "") == mem_id:
                        return str(obj.get("text") or "")
        except Exception as e:      # noqa: silent-ok — 读不动就当找不到
            logger.debug("读记忆库失败：%s", e)
        return ""

    # ------------------------------------------------------------ 复审
    def review_due(self, now=None, persist=True):
        """处理到期的隔离条目（3/7/30 天复审）：重新扫一遍原文，给出"可放行/继续隔离"的建议。

        为什么复审**不自动放行**：复审的规则和初筛是同一套，初筛判脏、复审多半也判脏；
        但它可以判"现在看是干净的了"（比如页面被编辑过）。
        不过"自动把一条曾判为污染的东西写进主记忆"风险太大 ——
        建议写进流水、状态改成 reviewed（= 我按时看过了），放行仍然交给用户。
        去掉复审 → 隔离区变成单行道：进去的东西永远不会再看第二眼，
        误杀就真的成了永久损失（只是"没删文件"而已）。
        """
        due = self.quarantine.due_review(now=now)
        done = []
        for item in due:
            qid = item.get("qid")
            rec = self.quarantine.get(qid)
            raw = str(rec.get("raw_text") or "")
            advice, score = "继续隔离", 0.0
            if raw:
                try:
                    res = self._screen_inner(str(rec.get("url") or ""), raw,
                                             title=str((rec.get("meta") or {}).get("title") or ""),
                                             topic="", profile=None, known_facts=None, sources=None)
                    score = res.score
                    advice = ("建议放行" if res.decision == "accept" else
                              "继续隔离（%s）" % (res.reasons[0][:60] if res.reasons else "仍判污染"))
                except Exception as e:      # noqa: silent-ok — 复审失败就当"继续隔离"（保守）
                    advice = "继续隔离（复审出错：%s）" % type(e).__name__
            if persist:
                self.quarantine.mark(qid, ST_REVIEWED,
                                     note="到期复审：%s（综合可信度 %.2f）" % (advice, score))
                self._log_verification({"event": "due_review", "qid": qid,
                                        "stage_days": item.get("stage_days"),
                                        "overdue_s": item.get("overdue_s"),
                                        "advice": advice, "score": score,
                                        "classes": rec.get("classes"),
                                        "url": rec.get("url")})
            done.append({"qid": qid, "advice": advice, "score": score,
                         "stage_days": item.get("stage_days"),
                         "classes": rec.get("classes")})
        return {"due": len(due), "done": done}

    # ------------------------------------------------------------ 统计与报告
    def stats(self):
        """体检数字。口径写在下面（**面板和 report 都读这里，不许各算一套**）。

        口径：
          today.explored    = 今天的 screen 台账行数（= 筛查过多少条）
          today.absorbed    = 今天的 absorb 行里 absorbed=True 的条数
          today.quarantined = 今天的 absorb 行里 decision=quarantine
          today.discarded   = 今天的 absorb 行里 decision=discard
          today.partial     = 今天的 absorb 行里"吸收成功但仍有隔离副本"（部分污染）
          恒等式（自测会钉死）：explored == absorbed + quarantined + discarded
                              隔离区新增条目 == quarantined + discarded + partial
        为什么把恒等式写进注释：数字对不上时，用户会先怀疑"是不是统计错了"，
        而不是去查真正的问题。口径写在代码里，才有人能一眼核对。
        """
        today0 = _day_start(_now())
        screens, absorbs = [], []
        for rec in _read_jsonl(self.absorption_path, limit=20000):
            try:
                ts = float(rec.get("ts") or 0)
            except Exception:      # noqa: silent-ok — ts 坏掉的台账行不计入"今天"
                continue
            if ts < today0:
                continue
            if rec.get("event") == "screen":
                screens.append(rec)
            elif rec.get("event") == "absorb":
                absorbs.append(rec)
        by_class = {}
        for rec in screens:
            for c in (rec.get("classes") or []):
                by_class[str(c)] = by_class.get(str(c), 0) + 1
        today = {
            "explored": len(screens),
            "absorbed": sum(1 for r in absorbs if r.get("absorbed")),
            "quarantined": sum(1 for r in absorbs if r.get("decision") == "quarantine"),
            "discarded": sum(1 for r in absorbs if r.get("decision") == "discard"),
            "partial": sum(1 for r in absorbs if r.get("absorbed") and r.get("qid")),
        }
        qs = self.quarantine.stats()
        bl = self._bl()
        conf_today, conf_all, need = 0, 0, 0
        for rec in _read_jsonl(self.conflicts_path, limit=20000):
            conf_all += 1
            if rec.get("needs_user_confirm"):
                need += 1
            try:
                if float(rec.get("ts") or 0) >= today0:
                    conf_today += 1
            except Exception:      # noqa: silent-ok — ts 坏掉只影响"今天"的分档
                pass
        active_sites = sum(1 for r in (bl["sites"] or {}).values()
                           if isinstance(r, dict) and r.get("active", True))
        return {
            "today": today,
            "blacklist": active_sites,          # 按 spec：这里给"黑名单站点个数"
            "blacklist_detail": {"sites": len(bl["sites"]), "sites_active": active_sites,
                                 "fingerprints": len(bl["fingerprints"]),
                                 "fingerprints_active": sum(
                                     1 for r in bl["fingerprints"].values()
                                     if isinstance(r, dict) and r.get("active", True)),
                                 "patterns": len(bl["patterns"])},
            "quarantine": {"total": qs["total"], "due": qs["due"],
                           "pending_review": qs["by_status"].get(ST_QUARANTINED, 0),
                           "by_status": qs["by_status"], "by_class": qs["by_class"]},
            "conflicts": {"today": conf_today, "total": conf_all, "needs_user_confirm": need},
            "rejected_memories": len(self.rejected_memories()),
            "by_class_today": by_class,
            "enabled": self.enabled(),
            "state_dir": self.state_dir,
            "paths": {"absorption": self.absorption_path, "blacklist": self.blacklist_path,
                      "conflicts": self.conflicts_path, "verification": self.verification_path,
                      "quarantine": qs["index_path"]},
        }

    def report(self, days=1):
        "「」用户可读报告。数字**全部来自 stats()**（不许另算一套，否则迟早对不上）。「」"
        st = self.stats()
        t = st["today"]
        lines = []
        lines.append("🛡️ 小焦的互联网免疫系统 · 最近 %d 天" % int(days or 1))
        lines.append("今天探索 %d 个站，吸收 %d 条，隔离 %d 条，丢弃 %d 条。"
                     % (t["explored"], t["absorbed"], t["quarantined"], t["discarded"]))
        if t["partial"]:
            lines.append("其中 %d 条是「部分污染」：脏的那几段剪掉了，干净的部分才吃进记忆。"
                         % t["partial"])
        if st["by_class_today"]:
            tops = sorted(st["by_class_today"].items(), key=lambda x: -x[1])[:5]
            lines.append("今天拦下的污染类型：" + "、".join(
                "%s %d" % (CLASS_CN.get(k, k), v) for k, v in tops))
        q = st["quarantine"]
        lines.append("隔离区现有 %d 条（观察中 %d 条、到期该复审 %d 条）；"
                     "隔离不是删除，原文都留着，随时可以手动放行或驳回。"
                     % (q["total"], q["pending_review"], q["due"]))
        bl = st["blacklist_detail"]
        lines.append("免疫记忆：黑名单站点 %d 个（累计记过 %d 个）、内容指纹 %d 条、句式 %d 条。"
                     % (bl["sites_active"], bl["sites"], bl["fingerprints"], bl["patterns"]))
        c = st["conflicts"]
        lines.append("与已有记忆的冲突：今天 %d 条、累计 %d 条，其中 %d 条挂着「待用户确认」"
                     "（**用户的话永远优先于互联网**，冲突时绝不擅自改记忆）。"
                     % (c["today"], c["total"], c["needs_user_confirm"]))
        lines.append("状态：%s。" % ("开启（宁可吸收慢，也不把垃圾吃进去）" if st["enabled"]
                                    else "**已关闭**（只留痕、不拦截）"))
        return "\n".join(lines)


# ================================================================ 模块级小工具
def _merge_cfg(cfg):
    "「」默认配置 ← 用户配置（深合一层）。**坏配置不许让防火墙起不来**。「」"
    out = json.loads(json.dumps(DEFAULT_CFG))     # 深拷贝（默认表不许被调用方改坏）
    if isinstance(cfg, dict):
        for k, v in cfg.items():
            if isinstance(v, dict) and isinstance(out.get(k), dict):
                out[k].update(v)
            else:
                out[k] = v
    return out


def _user_owned(old_text, known_list):
    "「」这句「旧话」是不是用户说过的事实（在 known_facts 里带 from_user 标记的）。「」"
    o = _norm_fact(old_text)
    for k in (known_list or []):
        if k.get("from_user") and _norm_fact(k.get("text")) == o:
            return True
    return False


def _cn_len(text):
    """正文字数（**不把 HTML 标签算进去**）。

    为什么必须剥标签再数：网页正文里标签能占一半以上字符，
    不剥离的话"内容长度"这个维度会被标签数量主导（一个空页面能数出三千字）。
    """
    return len(_TAG_RE.sub("", str(text or "")))


def _dates(text):
    """抽出正文里所有可识别日期，返回时间戳列表（升序）。

    为什么"没有时间戳"要算过时：一条不知道是什么时候发生的信息，
    在"事实会变"的世界里只能按最坏情况处理（可能已经过期）。
    去掉它 → 三年前的数据会被当成今天的现状吸收进去。
    """
    out = []
    for m in _DATE_RE.finditer(str(text or "")):
        try:
            y, mo, d = int(m.group("y")), int(m.group("m")), int(m.group("d"))
            if not (1 <= mo <= 12 and 1 <= d <= 31):
                continue
            ts = time.mktime((y, mo, d, 12, 0, 0, 0, 0, -1))
            if ts > 0:
                out.append(float(ts))
        except Exception:      # noqa: silent-ok — 解析不了的日期跳过（不能因此判成"有日期"）
            continue
    return sorted(out)


def _top_repeat(text, n=8):
    """返回 (重复次数最多的 n 字片段出现次数, 片段本身) —— 洗稿/堆砌的形态判据。

    为什么不用"去重字占比"（第一版用过，误杀严重）：中文本身用字重复率高，
    一篇两千字的正经科普文，去重字占比也就 0.2 上下 ——
    拿它判洗稿会把正常文章成片判脏。改用"同一串连续文字重复出现"，
    这个特征在自然语言里极少出现，而洗稿/堆砌文章里非常显眼。
    """
    t = _WS_RE.sub("", _TAG_RE.sub(" ", str(text or "")))
    n = max(4, int(n or 8))
    if len(t) < n * 2:
        return 0, ""
    counts = {}
    for i in range(len(t) - n + 1):
        g = t[i:i + n]
        counts[g] = counts.get(g, 0) + 1
    if not counts:
        return 0, ""
    g, c = max(counts.items(), key=lambda kv: kv[1])
    return c, g


def _day_start(ts):
    """某时间戳所在**当地**日期的 00:00（"今天"的分界线）。

    为什么用本地时区而不是 UTC：用户看到的"今天"是墙上的日历，不是 UTC 日期。
    用 UTC 会让凌晨 0~8 点的行动被算进"昨天"，报告天天对不上用户的直觉。
    """
    lt = time.localtime(ts)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))


def _profile_keywords(profile):
    """把用户画像归一成关键词列表（dict / list / str 都认）。

    为什么要放宽到这个程度：画像是用户和上层给的，形状没人规定死。
    严格只认一种形状的后果是"用户给了画像但格式不对 → 默默变成没有画像"，
    于是相关性判定整段失效，而且**没有任何报错**（最难查的那种 bug）。
    """
    if profile is None:
        return []
    if isinstance(profile, dict):
        vals = []
        for k in ("keywords", "interests", "topics", "likes", "tags", "关注", "兴趣"):
            v = profile.get(k)
            if isinstance(v, (list, tuple, set)):
                vals += [str(x) for x in v]
            elif isinstance(v, str):
                vals.append(v)
        if not vals:
            vals = [str(v) for v in profile.values() if isinstance(v, (str, int, float))]
        # 长句画像切成短词：太长的关键词永远匹配不上（等于没有画像）
        out = []
        for v in vals:
            for piece in re.split(r"[，,、;；\s]+", v):
                if piece.strip():
                    out.append(piece.strip())
        return out
    if isinstance(profile, (list, tuple, set)):
        return [str(x).strip() for x in profile if str(x).strip()]
    return [p.strip() for p in re.split(r"[，,、;；\s]+", str(profile)) if p.strip()]


def _looks_like_text(s):
    "「」这个参数看起来像「一段内容」而不是「一个记忆 id」（决定 reject 怎么解释参数）。「」"
    t = str(s or "")
    return len(t) > 40 or any(ch in t for ch in "，。！？；：\n")


__all__ = ["CLASSES", "CLASS_CN", "DEFAULT_CFG", "HARD_CLASSES", "PollutionFirewall",
           "SOFT_CLASSES", "ScreenResult", "check_conflict", "content_fingerprint",
           "normalize_text", "split_segments", "strip_spans"]
