# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 通用工具与专用工具的隔离（2026-10-17）

【要解决的问题】**同一轮里把通用的和专用的工具一起发给模型，它就爱挑通用的那个。**
实测：问「帮我查下济南现在的天气」，`get_weather`（专用，直接给气温风力）和 `web_search`
（通用，给一堆网页片段）同时装载 → 4B 两次都选了 `web_search`。
而有些场景选通用不是"风格差"，是**答不对**：问「我的公网 IP」，走 `web_search` 只会搜到
"怎么看自己的 IP"这类网页，永远拿不到本机真实 IP（走 `net_ip` 直接给 111.17.158.64 ｜ 山东济南）。

【怎么隔离】
  ① 每个专用工具登记一组**触发词**（见 `SPECIALIZED`）；一句话命中哪个专用工具，
     这一轮就**只装那些专用工具**，不装通用兜底（`web_search` / `get` / `fetch` / `run_command`…）；
  ② 一个专用工具都没命中 → 照旧（该装什么装什么，通用工具本来就是这类问题的正解；
     比如"查新闻"用 `web_search` 是对的，它是新闻这件事的**专用**工具）；
  ③ 专用工具**报错/超时**了 → 下一轮把那句问题的通用兜底也装上（`fallback_for()`），
     不允许"因为隔离，工具坏了就彻底没法干活"。

【边界】**这不是"删工具"**：99 个工具一个没少，`rea_call`/点名调用/完整目录仍在 system 里。
隔离只决定"这一轮桌面摆哪几个"，不决定"它能不能用"。
"""
import re

# 专用工具 → 触发词（中文口语并上英文缩写；命中即视为"这件事有专用工具"）
SPECIALIZED = [
    ("get_weather", ("天气", "气温", "下雨", "温度", "几度", "weather")),
    ("net_ip", ("公网ip", "公网 ip", "我的ip", "我的 ip", "归属地", "isp", "运营商")),
    ("get_ip", ("公网ip", "公网 ip", "我的ip", "我的 ip")),
    ("collect_vulnerabilities", ("漏洞", "cve", "高危")),
    ("download", ("下载", "存到本地", "保存到本地")),
    ("screenshot", ("截图", "截屏", "截个图", "截一张", "截一下")),
    ("read_memory", ("你记得", "还记得", "记忆里", "记不记得", "之前跟你说", "我跟你说过")),
    ("archify_deliver", ("画一张", "画个图", "架构图", "流程图", "时序图")),
    ("rea_do", ("逆向", "反编译", "脱壳", "二进制分析")),
]

# 通用兜底：没有专用工具命中时才该出场的那几个（它们能顶很多类事，但每件事都不够准）
GENERIC = ("web_search", "get", "fetch", "bulk_get", "bulk_fetch", "make_request",
           "stealthy_fetch", "run_command")


def _norm(s):
    return re.sub(r"\s+", "", str(s or "").lower())


def specialized_for(text, available=None):
    """这句话命中了哪些专用工具（按命中词数降序）。`available` 给了就只返回真实存在的。"""
    t = _norm(text)
    if not t:
        return []
    hits = []
    for name, keys in SPECIALIZED:
        n = sum(1 for k in keys if _norm(k) and _norm(k) in t)
        if n:
            hits.append((n, name))
    hits.sort(key=lambda x: (-x[0], x[1]))
    out = [n for _, n in hits]
    if available is not None:
        out = [n for n in out if n in available]
    return out


def fallback_for(text, available=None):
    """这句话的通用兜底该给哪几个（专用工具失败时用）。返回空表 = 本来就用不上兜底。"""
    gen = list(GENERIC)
    if available is not None:
        gen = [n for n in gen if n in available]
    return gen


def isolate(text, planned, available=None):
    """把"这一轮想装的工具"和"这句话命中专用工具"合起来算，返回 (最终要装的, 说明)。

    `planned`：原本要装的（意图表给的）。
    规则：
      · 命中专用 → 只留**专用 + 计划里非通用的那几个**（脚本类、文件类该留还是留）；
      · 没命中专用 → 原样返回（通用工具在那些问题上本来就是正解）。
    """
    planned = list(planned or [])
    special = specialized_for(text, available)
    if not special:
        return planned, "没有专用工具命中 → 按原计划装载"
    generic = set(GENERIC)
    keep = []
    for n in planned:
        if n in special:
            keep.append(n)
        elif n in generic:
            continue                      # 逐出通用的竞争者
        else:
            keep.append(n)
    for n in special:                     # 专用工具即便不在原计划里也补上
        if n not in keep:
            keep.append(n)
    dropped = [n for n in planned if n in generic and n not in special]
    if available is not None:             # 只留真实存在的（别把不存在的名字塞进工具表）
        keep = [n for n in keep if n in available]
    return keep, ("命中专用工具 %s → 本轮不装载通用兜底 %s"
                  % ("、".join(special), "、".join(dropped) or "（无）"))
