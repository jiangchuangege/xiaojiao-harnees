# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是“模型平等”和“变形金刚”的工程基础。
# -*- coding: utf-8 -*-
"""小焦 · 世界层（world layer）

互联网不是小焦的**工具箱**，是它生活的**世界**。这个子包放的就是"在世界里活着"需要的两样东西：

  perception.py  **感知**：一直在看（snapshot / diff / watch），不是用户问了才看；
                 抓一页 → 存快照（logs/world/snapshots.jsonl）→ 跟上次比（changes.jsonl）→
                 能提炼"今天互联网在讨论什么"（hot_topics）和"世界通不通"（availability）。
  model.py       **世界模型**：脑子里的地图（logs/world/model.json）——
                 这个站是干嘛的（type）、可不可信（trust）、多久刷新一次（refresh）、看过几次（hits）。
                 **重构后它还记"小焦自己的判断"**（judged_type/judged_trust/quality/
                 user_relevance/confidence/evidence）、话题表（topics）与用户画像（user_profile）。

  judge.py       **判断器**：给站点下判断（类型/质量/可信度/刷新/相关度），
                 规则先行、模型补充；**每条判断都带可读依据**（用户能追问"凭什么"）。
  explorer.py    **自主探索器**：不等人指令。五步闭环
                 推理（什么值得看）→ RAG（自己去搜）→ 匹对（跟画像/记忆对）→
                 校验（多源交叉+时间检验+可信度）→ 吸收（进记忆 + 更新地图）。
                 带节律（空闲才开啃 / 每小时自检 / 每天 3 点全面探索）与预算（daily_budget）。
  verifier.py    **校验器**：定期回看"上次判断准不准"，准的增强置信度、不准的修正、
                 久不访问的降权（`decay_unused`）—— 没有它，第一个判断就永久生效。
  quarantine.py  **隔离区**：可疑内容**原文留底**（绝不删），3/7/30 天复审，放行仍交给用户。
  firewall.py    **信息污染防火墙**：啃互联网必带的免疫系统 ——
                 10 类污染 / 5 道闸门（来源可信度→内容特征→交叉验证→注入检测→与用户匹对）、
                 消毒（污染片段摘进隔离区、干净部分才吸收）、免疫记忆（黑名单 + 内容指纹 + 降权）、
                 冲突处理（**用户的话 > 互联网信息**）。

两者都**不依赖任何具体模型，也不依赖 Flask**：抓取器（fetcher）与模型都是注入点，
所以后台观察进程、脚本、自测都能直接用，不必等整个 app 起来。

身体边界（属于这一层的原则，不是实现细节）：
  能碰公开页面/公开 API；不能碰需登录、付费、版权保护的；发布与花钱要用户确认；
  **红线是不能删任何文件** —— 世界感知只追加、只备份（坏文件另存 `.bad`），不删除。
  本层自己只做超时与异常兜底 + 只认 http/https，更细的 SSRF/robots 判定由上层负责。

用法：
    from core.world import WorldModel, WorldPerception
    wm = WorldModel()                       # logs/world/model.json
    wp = WorldPerception(model=wm)          # 默认 fetcher：app 的 get → requests 兜底
    wp.observe(["https://example.com"])     # 现在看一遍
    wm.due()                                # 谁到期了（持续观察的驱动）

    from core.world import WorldExplorer, PollutionFirewall, WorldVerifier
    fw = PollutionFirewall(model=wm)        # 免疫系统
    ex = WorldExplorer(model=wm, firewall=fw)   # 自己啃互联网
    ex.start()                              # 后台 daemon：空闲就开啃
"""
from .model import (
    MODEL_PATH,
    TYPE_REFRESH,
    TYPE_TRUST,
    WORLD_DIR,
    WorldModel,
    domain_of_url,
    format_interval,
    parse_interval,
)
from .perception import WorldPerception, default_fetch, parse_tool_result

# 重构后新增的三件套 + 免疫系统。**用 try 包住**：
# 这几个模块各自会惰性去拿 app/记忆库，任何一处初始化不了都不该让
# `from core.world import WorldModel` 这种最基础的用法一起失败（分层降级）。
try:
    from .judge import Judgment, SiteJudge
except Exception:               # noqa: BLE001 — 判断器缺席时世界层其余部分照常可用
    Judgment = SiteJudge = None  # type: ignore
try:
    from .explorer import WorldExplorer, get_explorer, maybe_start, stop_all, touch
except Exception:               # noqa: BLE001
    WorldExplorer = get_explorer = maybe_start = stop_all = touch = None  # type: ignore
try:
    from .verifier import WorldVerifier, get_verifier, review
except Exception:               # noqa: BLE001
    WorldVerifier = get_verifier = review = None  # type: ignore
try:
    from .firewall import PollutionFirewall, ScreenResult, check_conflict
except Exception:               # noqa: BLE001
    PollutionFirewall = ScreenResult = check_conflict = None  # type: ignore
try:
    from .quarantine import Quarantine
except Exception:               # noqa: BLE001
    Quarantine = None  # type: ignore

__all__ = [
    "WorldModel", "WorldPerception",
    "WORLD_DIR", "MODEL_PATH", "TYPE_TRUST", "TYPE_REFRESH",
    "domain_of_url", "parse_interval", "format_interval",
    "default_fetch", "parse_tool_result",
    "SiteJudge", "Judgment", "WorldExplorer", "WorldVerifier", "PollutionFirewall",
    "ScreenResult", "Quarantine", "check_conflict",
    "get_explorer", "get_verifier", "maybe_start", "stop_all", "touch", "review",
]
