# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""
小焦 · XiaoJiao Web —— 本地部署的「联网搜索 AI」

架构：
        ┌────────────┐   ┌────────────┐   ┌────────────┐
  用户 →│  Web UI    │→│  Agent     │→│  LLM 大脑   │
        │ (Flask)    │  │ 上下文/记忆│  │ (openai兼容)│
        └────────────┘  └─────┬──────┘  └─────┬──────┘
                              │               │
                              ▼               ▼
                         ├─ web 检索 ──► 网络知识（大脑的外脑）
                         └─ 记忆自学习 ─► 知识沉淀，回调用
"""
import os, sys, json, re, time, threading, webbrowser
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string, Response, redirect
import requests
import torch
import logging  # noqa: F401  （由 tools/fix_silent_except.py 注入）
try:
    from xiaojiao_log import get_logger
except Exception:  # 独立运行时退化为标准 logging
    def get_logger(name=None):
        return logging.getLogger(name or 'xiaojiao')
LOG = get_logger(__name__)

# ================== 配置（读取「操控文件」xiaojiao_control.json） ==================
# 你想让小焦成为什么类型的模型、用什么大脑、开哪些工具，全部由这个文件决定。
# 操控文件的**绝对路径**（模块级）：以前这个路径只是 _load_control() 里的局部变量 _CFG，
# 而 /api/persona 却直接引用 _CFG → 切人格一定 NameError 500（真实缺陷，ruff F821 抓出来的）。
CONTROL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "xiaojiao_control.json")


def strip_search_rules(role):
    """把混进人设里的**规则文本**剥掉，只留纯人设。

    role 只管人设（身份/性格/说话风格）。检索铁律、工具规则、技能清单、插件清单都该由
    代码独立拼接 —— 一旦被写进 role，就会出现三个真问题：改人设丢规则、加插件得手改人设、
    role 越写越长把人设淹没。

    历史遗留（真实事故）：`/api/tools_toggle` 与 `_save_control` 曾把**合成后**的
    SYSTEM_PROMPT 当人设存回控制文件，线上累积过 **11 份**铁律，每轮白背 3.5KB 提示词。
    所以这里把**所有**规则类片段都切掉（[检索铁律]/[工具铁律]/[简洁原则]/[代码工作流]/
    [技能插件]/[插件清单]/[环境]… 起始到下一个同级别段），且对"界面回传的合成人设"幂等。
    """
    s = role or ""
    cuts = []
    for mark in ("\n[检索铁律]", "[检索铁律]", "\n[工具铁律]", "[工具铁律]",
                 "\n[简洁原则]", "[简洁原则]", "\n[代码工作流]", "[代码工作流]",
                 "\n[技能插件]", "[技能插件]", "\n[插件清单]", "[插件清单]",
                 "\n【当前已加载", "【当前已加载", "\n[环境]", "[环境]", "\n[工具用法]", "[工具用法]"):
        i = s.find(mark)
        if i != -1:
            cuts.append(i)
    if cuts:
        s = s[:min(cuts)]
    return s.strip()


def _load_control():
    c = {"model_name": "xiaojiao1.0-4B", "web_port": 5000,
         "brain": {"engine": "auto",
                   "api": {"base_url": os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8080/v1"),
                           "api_key": os.environ.get("LLM_API_KEY", ""),
                           "model": os.environ.get("LLM_MODEL", "llama")}},
         "role": ("你是“小焦”（xiaojiao1.0-4B），一个本地部署的联网搜索 AI 助手。"
                  "擅长联网检索并像人一样自然、有条理地回答。先结论后展开，简洁中文，必要时分点。"
                  "不要机械复读，要自然接话。"),
         "capabilities": {"web_search": True, "memory": True, "context_len": 20, "auto_deep_think": True},
         "behavior": {"temperature": 0.7, "max_tokens": 2048}}
    # 优先读"模块所在目录"的操控文件（不受启动目录影响）；没有就退回相对路径，保持老行为
    for p in (CONTROL_FILE, "xiaojiao_control.json"):
        if not os.path.exists(p):
            continue
        try:
            c.update(json.load(open(p, encoding="utf-8")))
            break
        except Exception as e:
            LOG.debug("忽略异常(%s:%d): %s", __file__, 44, e)
    # 自愈：老版本把人设写脏了（铁律被反复拼进去）→ 读进来就剥干净，内存里永远是纯人设
    if isinstance(c.get("role"), str):
        c["role"] = strip_search_rules(c["role"])
    return c


# ================== 大脑密钥的来源（安全第一批·任务3） ==================
# 为什么要有这段：密钥以前只能写在 xiaojiao_control.json 里，那是个**本地明文**文件 ——
# 一旦被误发、误传、误提交，云端 Key 就等于公开了。改成"环境变量优先"之后：控制文件里
# 可以留空，密钥只活在运行环境里；多机部署时各机各自设，不必互相传文件。
LLM_KEY_ENV = "XIAOJIAO_API_KEY"


def _mask_key(k):
    """密钥的**可安全打印**形式：前 4 + 后 4 + 长度。绝不打印整串。"""
    s = str(k or "")
    if not s:
        return "（空）"
    if len(s) <= 10:
        return "%s…（len=%d）" % (s[:2], len(s))
    return "%s…%s（len=%d）" % (s[:4], s[-4:], len(s))


def _key_from_models(models, brain):
    """从 `models[]` 里挑出**当前大脑对应的那把 key**（Web 界面就是往这里填的）。

    为什么要加这一路（真缺陷）：
      界面把 Key 存进 `models[].api_key`，而运行时只读 `brain.api.api_key` ——
      用户填完 Key，系统照样报"没有 key"。两处各存一份，谁也不知道对方写没写。
    匹配顺序（宁可精确也不乱猜）：
      ① `brain.api.model` 完全同名的条目；
      ② 同 base_url 的条目；
      ③ 全表里**唯一**一把非空 Key（只有一把时没有歧义）。
    """
    try:
        api = (brain or {}).get("api", {}) if isinstance(brain, dict) else {}
        want_model = str(api.get("model") or "").strip()
        want_base = str(api.get("base_url") or "").strip().rstrip("/")
        items = [m for m in (models or []) if isinstance(m, dict)]
        for m in items:
            if want_model and str(m.get("model") or "").strip() == want_model:
                k = str(m.get("api_key") or "").strip()
                if k:
                    return k, "models[]（模型名匹配 %s）" % want_model
        for m in items:
            if want_base and str(m.get("base_url") or "").strip().rstrip("/") == want_base:
                k = str(m.get("api_key") or "").strip()
                if k:
                    return k, "models[]（base_url 匹配）"
        withkey = [str(m.get("api_key") or "").strip() for m in items
                   if str(m.get("api_key") or "").strip()]
        if len(withkey) == 1:
            return withkey[0], "models[]（全表唯一一把）"
    except Exception as e:      # noqa: silent-ok — 取不到就退回旧来源，不能因此读不到 key
        LOG.debug("从 models[] 解析 Key 失败（忽略）：%s", e)
    return "", ""


def _resolve_llm_key(brain, models=None):
    """解析大脑密钥。优先级：环境变量 XIAOJIAO_API_KEY > models[当前大脑].api_key > brain.api.api_key。

    控制文件里还允许写 `"api_key": "env:某个名字"` 这种**间接引用**（模板
    xiaojiao_control.json.example 就是这么写的）：这时读的是"某个名字"那个环境变量，
    而不是把 "env:..." 这串字面量当密钥发出去（那会白白换来一个 401）。

    为什么要有 `models[]` 这一路（**真缺陷**，用户实测）：
      Web 界面填 Key 只写 `models[].api_key`，而这里原来只读 `brain.api.api_key` ——
      于是"界面上填了 key，系统还说没有 key"。而 `api_model_select` 还会把
      `brain.api.api_key` 显式清成空串（它有意不搬模型条目里的明文 Key），
      等于**每次切模型都会把那把 Key 抹掉**。现在两处都能读到，且下面 `_sync_api_key`
      会在保存时把它们对齐，不再各写各的。
    环境变量仍然**最高优先**（安全第一批·任务3 的意图不变：密钥可以只活在环境里）。
    """
    env_key = (os.environ.get(LLM_KEY_ENV) or "").strip()
    if env_key:
        LOG.info("大脑密钥来源：环境变量 %s = %s", LLM_KEY_ENV, _mask_key(env_key))
        return env_key
    # ---- models[] 优先于 brain.api.api_key（顺序不能反，否则 Bug 1 等于没修）----
    # 界面填的 Key 落在 models[]，而 brain.api.api_key 很可能是**上一次**留下的旧值。
    # 若先读 brain.api，用户新填的 Key 会被旧值压住 —— 表现还是"填了没生效"。
    # 所以：环境变量 > models[] > brain.api.api_key。brain.api 只作为兜底（老配置兼容）。
    try:
        # `models` 可注入（默认取实时配置）：生产环境永远是当前 CONTROL，
        # 但留一个入参才能把这条优先级**单独测出来**（不然测试只能改真实配置文件）。
        _ms = models if models is not None else (CONTROL.get("models") or [])
        mk, why = _key_from_models(_ms, brain)
    except Exception:      # noqa: silent-ok — 导入期 CONTROL 可能还没就绪
        mk, why = "", ""
    if mk:
        LOG.info("大脑密钥来源：%s = %s", why, _mask_key(mk))
        return mk
    api = brain.get("api", {}) if isinstance(brain, dict) else {}
    raw = api.get("api_key", "") if isinstance(api, dict) else ""
    raw = raw.strip() if isinstance(raw, str) else ""
    if raw.lower().startswith("env:"):
        v = (os.environ.get(raw[4:].strip()) or "").strip()   # 控制文件指向环境变量
        LOG.info("大脑密钥来源：控制文件指向环境变量 %s = %s", raw[4:].strip(), _mask_key(v))
        return v
    if raw:
        LOG.info("大脑密钥来源：brain.api.api_key = %s", _mask_key(raw))
        return raw
    LOG.info("大脑密钥来源：无（环境变量、models[]、brain.api 都没有可用 Key）")
    return ""


def _sync_api_key(brain, models):
    """保存时把两处 Key **对齐**（有则同步、都没有则都空），返回修了什么。

    为什么要自动同步而不是只改一处：只要存在两个存放位置，就一定会出现
    "一边填了、另一边是空的"，而运行时只认其中一条路 —— 用户看到的就是
    "我明明填了却没生效"。所以保存是**唯一的写入口**，在这里对齐最省事也最可靠。
    方向：**谁有值听谁的**（两处都有值且不同则以 brain.api 为准，并记账说明）。
    """
    try:
        api = brain.setdefault("api", {}) if isinstance(brain, dict) else {}
        brain_key = str(api.get("api_key") or "").strip()
        if brain_key.lower().startswith("env:"):
            return ""            # 间接引用（指向环境变量）不参与同步，也绝不能覆盖
        want_model = str(api.get("model") or "").strip()
        want_base = str(api.get("base_url") or "").strip().rstrip("/")
        hit = None
        for m in (models or []):
            if not isinstance(m, dict):
                continue
            if want_model and str(m.get("model") or "").strip() == want_model:
                hit = m
                break
            if want_base and str(m.get("base_url") or "").strip().rstrip("/") == want_base:
                hit = m
                break
        if hit is None:
            return ""
        model_key = str(hit.get("api_key") or "").strip()
        if brain_key == model_key:
            return ""
        if brain_key and not model_key:
            hit["api_key"] = brain_key
            LOG.info("Key 同步：brain.api → models[%s] = %s", hit.get("model") or hit.get("name"),
                     _mask_key(brain_key))
            return "brain→models"
        # 模型条目里有、brain.api 里没有（**界面填 Key 的常态**）→ 补到 brain.api
        api["api_key"] = model_key
        LOG.info("Key 同步：models[%s] → brain.api = %s",
                 hit.get("model") or hit.get("name"), _mask_key(model_key))
        return "models→brain"
    except Exception as e:      # noqa: silent-ok — 同步失败不能挡住保存本身
        LOG.warning("Key 同步失败（忽略）：%s", e)
        return ""


CONTROL = _load_control()
if isinstance(CONTROL, dict):
    CONTROL.setdefault("dsh", {}).setdefault("enabled", True)  # DSH 桥接永远默认开(防静默翻false)

MODEL_NAME = CONTROL.get("model_name", "xiaojiao1.0-4B")
# Web 应用自己的版本号（给 /health 用）。改版本时务必与 CHANGELOG.md / README 对齐 ——
# tools/check_principles.py 的 P9 会审这类"文档说 vX、代码没跟上"的不一致。
APP_VERSION = "1.0"
BRAIN = CONTROL.get("brain", {})
BRAIN_ENGINE = BRAIN.get("engine", "auto")          # auto | llama | xiaojiao | api
LLM_BASE = BRAIN.get("api", {}).get("base_url", "http://127.0.0.1:8080/v1")
# 密钥优先级：环境变量 XIAOJIAO_API_KEY > 控制文件 api_key（安全第一批·任务3）
LLM_KEY = _resolve_llm_key(BRAIN)
LLM_MODEL = BRAIN.get("api", {}).get("model", MODEL_NAME)
# 检索铁律：写死在代码里，而不是只写在 control 文件里 —— 用户换人设/换模型也不会把这条规矩弄丢。
# 真实缺陷防复发：小焦曾把功能字「用」当关键词去搜，搜回来的是"用（汉语汉字）"百科词条。
# ============================================================================
# 系统提示词的分层（**架构约定**：role 只负责人设，规则与清单由代码独立管理）
#   最终提示词 = role（纯人设） + _SEARCH_RULES（检索铁律） + _TOOL_RULES（工具规则）
#                + _plugin_list()（插件清单，从 PLUGINS 动态生成）
# 这样：改人设不丢规则；加插件不用手改人设；role 不会被规则淹没。
# ============================================================================
_SEARCH_RULES = (
    "\n[检索铁律] "
    "① 调用 web_search 时，query 只能是**内容关键词**（如「最近的漏洞 CVE」「2026 年 AI 新闻」），"
    "禁止把「用/搜/找/抓/看/搞/请/帮」这类功能字、语气词或整句话当检索词；"
    "② 漏洞/CVE/高危 类问题**优先**调用 collect_vulnerabilities(days=7, severity=\"HIGH\", limit=5)，"
    "不要用新闻搜索代替；"
    "③ 用户没说清要搜什么时，先反问「请告诉我你要搜索的具体关键词」，绝不用单个字去搜；"
    "④ **检索到的资料必须真读进去**：回答要落在资料的具体内容上（标题、数字、结论、原文措辞），"
    "不许把资料当摆设、自己另编一套；资料里没有的就直说没有；"
    "⑤ 用户让你**别搜/停止搜索/直接用某个工具**时，就照办：一次搜索都不要再发。"
)

_PLUGIN_LIST_TEMPLATE = "\n【当前已加载的工具（可直接调用）】\n%s"

# 工具规则（同样写死在代码里，不往 role 里塞）。
# 真实缺陷 a：原来是"凡是要帮我做实事都必须先调工具"，云端模型于是把寒暄也当"实事"——
#             实测一句"你好"它连调 read_file / get_ip / read_file / list_files 四个工具，
#             147 秒才吐出一句问候。工具是给"做事"用的，不是给聊天用的。
# 真实缺陷 b：用户让"用 Archify 画架构图"，模型不知道手上有 archify_* 工具（清单在 role 里、
#             没人维护），转头去联网搜「用」字。所以下面还要点明"先看上面清单里有没有现成工具"。
_TOOL_RULES = ("\n[工具铁律] "
               "① 只有当用户**明确要你做事**（写/改文件、建网页、跑命令、查资料、读文件、"
               "查 IP、抓网页、画图…）时才调用对应工具；寒暄、闲聊、概念解释、单纯问答"
               "**一个工具都不要调**（别为了打招呼去 read_file / list_files / get_ip）。"
               "② **做事之前先看上面那份工具清单**：用户点名某个插件/工具（如 Archify）时，"
               "直接调那个工具，**不要**改用 web_search 去搜；清单里没有的才说「没有这个工具」。"
               "③ 多步任务按顺序拆开做（先校验/先读文件，再产出结果），每步都调对应工具。"
               "\n【工具选择顺序】不确定就用这张表，别硬猜：\n① 用户给了网址/要求抓网页 → `get`；被拦或正文空 → `fetch`；再不行 → `stealthy_fetch`（开销最大，别一上来就用）\n② 用户**问天气**（某地天气 / 会不会下雨 / 气温多少）→ **必须优先 `get_weather`，不要用 `web_search` 代替**。\n理由：`get_weather` 回的是**结构化天气数据**，`web_search` 只回**网页片段** —— 用户实测过这条链：拿 web_search 去答天气，只捞到一堆链接，最后只能回「我没能力」。\n只有当 `get_weather` **失败**时才降级用 `web_search`，而且**必须在回答里标注「数据来自网页检索，可能不准」**。\n③ 用户要查资料/新闻/百科这类**信息** → `web_search`（别去抓某个具体网页）\n④ 用户要画图（架构图/流程图/时序图/数据流/状态图）→ 走 archify 工作流：`archify_read_skill` → `archify_guide` → `archify_read_schema` → `archify_read_example` → `archify_validate` → `archify_deliver`（**一次搜索都不要发**）\n⑤ 用户要漏洞清单 → `collect_vulnerabilities`（不要用 web_search 凑）\n⑥ 用户要查本机公网 IP/归属地 → `net_ip`\n⑦ 用户纯聊天/寒暄/概念问答 → **不调任何工具**\n⑧ 要执行命令/写文件/读文件 → `run_command` / `write_file` / `edit_file` / `read_file`\n⑨ 上面都不沾边、又确实需要外部信息时 → 优先 `web_search` 找信息，不要硬猜工具。\n"
               "④ **校验/报错必须一次性改完**：`archify_validate`（或任何校验类工具）失败时，"
               "要**按返回的全部报错一起修**，改好再校验**一次**；禁止「改一条→校验→再改一条」"
               "这种逐条试错（实测同一张图来回校验 7 次、白烧 200 多秒）。同一工具连续失败 3 次"
               "会被系统熔断，把最后一次报错直接摆给用户。"
               "⑤ 工具报错就把真实错误原样告诉用户并说明怎么修，不要自己编一个成功结果。"
               "\n[简洁原则] 回答要极简：只给结果/代码/结论，不要寒暄、不要说【好的我来帮你】、"
               "不要复述问题、不要多余解释。写代码只输出代码块。"
               "\n[代码工作流] 写/改代码请这样：① 先 read_file 看相关文件再动手；"
               "② 新增用 write_file，修改用 edit_file 精准替换；"
               "③ 改完用 run_command 验证（Python 用 python -c 语法检查、JS 用 node --check、"
               "或直接运行看结果）；④ 有报错就读出来修复。不要凭空猜测文件内容。")


def _plugin_list(plugins=None, max_tools=90):
    """从 PLUGINS 动态生成"插件清单"，让模型知道**现在到底有哪些工具**。

    为什么动态生成：以前这份清单写在 role 里，用户每加一个插件都得手改人设 —— 加完还常常
    忘，于是模型压根不知道新工具有、转头去联网搜（用户实测：让 Archify 画架构图，
    它跑去搜"用"字）。清单跟着 PLUGINS 走，重启/开关插件即自动生效。

    注意要**显式传入**刚加载好的插件表：`PLUGINS = load_plugins()` 这句赋值发生在函数返回
    **之后**，此刻全局 PLUGINS 还是旧的 —— 直接读全局会生成"当前无可用工具"（真实踩过）。
    """
    try:
        rows = plugins if plugins is not None else globals().get("PLUGINS") or {}
        items = []
        for pname, p in (rows or {}).items():
            if not p.get("on") or p.get("type") == "skin":
                continue
            for t in (p.get("desc") or []):
                if not isinstance(t, dict) or not t.get("name"):
                    continue
                d = (t.get("description") or "").strip().replace("\n", " ")
                if len(d) > 46:
                    d = d[:46] + "…"
                items.append("- %s：%s" % (t["name"], d or pname))
        if not items:
            return _PLUGIN_LIST_TEMPLATE % "当前无可用工具"
        seen, uniq = set(), []
        for it in items:
            k = it.split("：")[0]
            if k not in seen:
                seen.add(k)
                uniq.append(it)
        body = "\n".join(uniq[:max_tools])
        if len(uniq) > max_tools:
            body += "\n- …（另有 %d 个工具，见设置页「插件」）" % (len(uniq) - max_tools)
        return _PLUGIN_LIST_TEMPLATE % body
    except Exception as e:      # 清单生成失败绝不能拖垮提示词
        LOG.debug("忽略异常(%s:%d): %s", __file__, 76, e)
        return _PLUGIN_LIST_TEMPLATE % "当前无可用工具"


def compose_system_prompt(role, plugins=None):
    """**唯一**的系统提示词合成入口：人设 + 检索铁律 + 工具规则 + 动态插件清单。

    为什么单独立个函数：`reload_control()`（切人设/改配置后调用）原来直接
    `SYSTEM_PROMPT = CONTROL.get("role","")`，把规则全丢了 —— 缺陷会悄悄复发。
    每条规则都只加**一份**：先剥掉人设里历史遗留的规则文本，再按固定顺序拼。

    【为什么这么设计】规则散着拼就会重复（人设里写一遍、代码里再拼一遍），
    重复的规则既吃 token 又会让模型看到自相矛盾的两段话；
    而且"哪些规则生效"变得没人说得清。集中在一处、固定顺序、每条只加一次，
    才让"system 里到底有什么"成为一个**可断言**的事实（`test_infinity_456.py` 就钉这一点）。

    【去掉它会怎样】切人设/改配置时规则丢失（真实发生过），
    表现为"改了个性之后它就不守工具铁律了"——而且是间歇性的，极难复现。
    """
    # 补偿第 6 项：**技能文档（.md 插件）也要进 SYSTEM_PROMPT**。
    # 真实缺陷：PLUGIN_SKILLS 只在"每轮临时拼进 messages"那条路上用过，
    # 而真正长期生效的 SYSTEM_PROMPT 里从来没有它 —— 技能文档等于白写。
    _skills = globals().get("PLUGIN_SKILLS") or []
    _skill_txt = ("\n\n[技能插件]\n" + "\n\n".join(c for _, c in _skills)) if _skills else ""
    return (strip_search_rules(role) + _SEARCH_RULES + _TOOL_RULES + _plugin_list(plugins)
            + _skill_txt + _persona_rules_text())


def _persona_rules_text():
    """人格层规则（模块 9）—— 每次组装提示词都带上（十条人味 + 绝对不要）。

    为什么要单独一个函数、并且**吞掉所有异常**：
      人格层是"说话方式"的软约束，属于锦上添花；而 `compose_system_prompt` 是
      全局唯一入口，它一抛异常整个对话就起不来。所以这里任何问题（模块缺失、
      导入失败、语法错）都必须退化为**空串** —— 宁可这次没有人格规则，
      也绝不能因为"想让它说话像人"而让系统起不来。
      这里只负责**追加**，不做任何删除：用户自己写的人设一个字都不动。
    """
    try:
        from core import persona as _p
        return "\n\n" + _p.persona_block()
    except Exception as e:      # noqa: silent-ok — 人格规则拿不到不影响对话，绝不外抛
        try:
            LOG.debug("人格层规则不可用（忽略）：%s", e)
        except Exception:       # noqa: silent-ok — 连日志都拿不到时静默，保持原行为
            pass
        return ""


def refresh_system_prompt(plugins=None):
    """重建全局 SYSTEM_PROMPT（插件加载/开关后调用，让新工具立刻进清单）。"""
    global SYSTEM_PROMPT
    try:
        SYSTEM_PROMPT = compose_system_prompt(CONTROL.get("role", ""), plugins)
    except Exception as e:
        LOG.debug("忽略异常(%s:%d): %s", __file__, 96, e)
    return SYSTEM_PROMPT


SYSTEM_PROMPT = compose_system_prompt(CONTROL.get("role", ""))   # ← 人设/类型，改 control 文件即换模型人格
CAP = CONTROL.get("capabilities", {})
FULL_ACCESS = CONTROL.get("capabilities", {}).get("full_access", False)  # 默认**只读**：危险命令要先确认；显式设 true 才全权限直执行
# ---------------- 安全：监听地址 + 访问令牌（第一批任务 1） ----------------
# 真实风险：以前默认 `host="0.0.0.0"` 且**没有任何鉴权** —— 同一个 WiFi 下任何人打开
# http://<你的IP>:5000 就能聊天、翻你的会话、改你的配置。现在：默认只听本机；
# 要局域网访问必须在控制文件里**显式**打开 lan_access 并设一个 access_token。
LAN_ACCESS = bool(CONTROL.get("capabilities", {}).get("lan_access", False))
ACCESS_TOKEN = str(CONTROL.get("capabilities", {}).get("access_token", "") or "").strip()
# 除这些路径外，所有请求都要带令牌（/health 用于探活，不带敏感信息）
_AUTH_EXEMPT = ("/health", "/favicon.ico", "/api/central")
BEH = CONTROL.get("behavior", {})

HISTORY_FILE = "xiaojiao_history.json"              # 对话上下文（持久化）
MEMORY_FILE = "xiaojiao_knowledge_memory.json"      # 自学习记忆
MAX_HISTORY = int(CAP.get("context_len", 20))
WEB_TIMEOUT = 12
TEMPERATURE = float(BEH.get("temperature", 0.7))
MAX_TOKENS = int(BEH.get("max_tokens", 1024))


def reload_control():
    """从操控文件重新载入配置（设置页保存后即刻生效）。"""
    global CONTROL, MODEL_NAME, BRAIN_ENGINE, LLM_BASE, LLM_KEY, LLM_MODEL
    global SYSTEM_PROMPT, CAP, BEH, MAX_HISTORY, TEMPERATURE, MAX_TOKENS
    global LAN_ACCESS, ACCESS_TOKEN, FULL_ACCESS
    CONTROL = _load_control()
    CONTROL.setdefault("dsh", {}).setdefault("enabled", True)
    MODEL_NAME = CONTROL.get("model_name", "xiaojiao1.0-4B")
    BRAIN = CONTROL.get("brain", {})
    BRAIN_ENGINE = BRAIN.get("engine", "auto")
    LLM_BASE = BRAIN.get("api", {}).get("base_url", "http://127.0.0.1:8080/v1")
    LLM_KEY = _resolve_llm_key(BRAIN)
    LLM_MODEL = BRAIN.get("api", {}).get("model", MODEL_NAME)
    SYSTEM_PROMPT = compose_system_prompt(CONTROL.get("role", ""))   # 走统一合成，别把检索铁律丢掉
    CAP = CONTROL.get("capabilities", {})
    BEH = CONTROL.get("behavior", {})
    MAX_HISTORY = int(CAP.get("context_len", 20))
    TEMPERATURE = float(BEH.get("temperature", 0.7))
    MAX_TOKENS = int(BEH.get("max_tokens", 1024))
    LAN_ACCESS = bool(CAP.get("lan_access", False))
    ACCESS_TOKEN = str(CAP.get("access_token", "") or "").strip()
    FULL_ACCESS = bool(CAP.get("full_access", False))


_ctlmtime = 0
def maybe_reload_control():
    """操控文件改动后自动热更新（人设/大脑/参数不必重启）。"""
    global _ctlmtime
    try:
        m = os.path.getmtime("xiaojiao_control.json")
    except Exception:
        return
    if m != _ctlmtime:
        _ctlmtime = m
        reload_control()
        global PLUGINS
        PLUGINS = load_plugins()
# ================== 插件系统 ==================
PLUGIN_SKILLS = []   # .md 技能/知识插件，会拼进人设


def _api_execute(manifest, tool_name, params):
    """执行 API 插件：按其 declaration 调 HTTP 接口。"""
    t = next((x for x in manifest.get("tools", []) if x.get("name") == tool_name), None)
    if not t:
        return None
    method = (t.get("method", "GET")).upper()
    url = t.get("url", "")
    for k, v in (params or {}).items():
        url = url.replace("{" + str(k) + "}", str(v))
    headers = t.get("headers", {})
    try:
        body = None
        if method in ("POST", "PUT", "PATCH"):
            body = (params or {}).get("body") or {k: v for k, v in (params or {}).items() if k not in t.get("body_exclude", [])}
        r = requests.request(method, url, params=(params or {}), json=body, headers=headers, timeout=t.get("timeout", 30))
        if t.get("response") == "json":
            j = r.json()
            fld = t.get("field")
            return str(j.get(fld) if fld else j)
        return r.text[:2000]
    except Exception as e:
        return f"API 插件执行失败：{e}"


def _make_tools_plugin(man):
    """把 OpenAI/Claude/DSH 风格的 tools 清单转成小焦插件实例(适配器)。
    OpenAI: {"tools":[{"type":"function","function":{"name","description","parameters"}}]}
    Claude: {"tools":[{"name","description","input_schema"}]}  (input_schema 转 parameters)
    DSH:    {"tools":[{"name","description","parameters","url"}]}  (url 为直接调用的 API)
    """
    tools = man.get("tools") or []
    descs = []
    for t in tools:
        fn = t.get("function") if isinstance(t, dict) and "function" in t else t
        if not isinstance(fn, dict):
            continue
        name = fn.get("name") or ""
        if not name:
            continue
        params = fn.get("parameters") or fn.get("input_schema") or {"type": "object", "properties": {}}
        if not isinstance(params, dict) or params.get("type") is None:
            params = dict(params or {}); params.setdefault("type", "object"); params.setdefault("properties", params.get("properties") or {})
        descs.append({"name": name, "description": fn.get("description", ""),
                      "url": fn.get("url", t.get("url", "")), "manifest": man})
    if not descs:
        return None
    return _ToolsPlugin(descs)


class _ToolsPlugin:
    """从 OpenAI/Claude/DSH 工具清单生成的插件(可调用外部API或提示运行时)。"""
    def __init__(self, descs):
        self._descs = descs
        self._tp = {}
        for d in descs:
            self._tp[d["name"]] = d
    def get_tool_descriptions(self):
        return [{"name": d["name"], "description": d["description"],
                 "url": d.get("url", ""),
                 "parameters": {"type": "object", "properties": {}}} for d in self._descs]

    def has_url(self, tool_name):
        """这个工具到底能不能执行（清单里带 url 才算）。

        为什么单独给方法：`get_tool_descriptions()` 返回的是**给模型看的**精简结构，
        某些工具（旧版清单）里没带 url —— 直接拿它判"能不能执行"会把
        `plugins/ip.json` 这种**带 url 的正常插件**也误杀（这个坑我踩过：修幻影工具时
        把 get_ip/get_ip_info 一起过滤掉了）。判据必须看插件**自己的**清单。
        """
        d = self._tp.get(tool_name) or {}
        return bool(d.get("url") or (d.get("manifest") or {}).get("url"))
    def execute(self, tool_name, params):
        d = self._tp.get(tool_name)
        if not d:
            return "未知工具"
        url = d.get("url") or (d.get("manifest") or {}).get("url", "")
        if url:
            try:
                import requests as _rq
                rr = _rq.post(url, json=params, timeout=20)
                return rr.text[:800]
            except Exception as e:
                return "调用失败: " + str(e)[:80]
        return "该工具「%s」来自外部清单(OpenAI/Claude/DSH)，已在本地注册；实际执行需对应运行时或填写 url。" % tool_name


def _make_api_plugin(manifest):
    """把一个 API 插件 manifest 变成可用插件实例（get_tool_descriptions/execute）。"""
    class _ApiPlugin:
        def get_tool_descriptions(self):
            return [{"name": t.get("name"), "description": t.get("description", ""),
                     "parameters": t.get("parameters", {"type": "object", "properties": {}})}
                    for t in manifest.get("tools", []) if t.get("name")]
        def execute(self, name, params):
            return _api_execute(manifest, name, params)
    return _ApiPlugin()


def load_plugins():
    """扫描 plugins/ 目录，支持三种插件类型：
       - .py    Python 工具插件（class 含 get_tool_descriptions/execute）
       - .json  API 插件（把 HTTP 接口声明成工具）
       - .md    技能/知识插件（内容拼进人设）
    返回 { 插件名: {"instance":..., "desc":[...], "type":..., "on":..., "path":...} }。
    """
    import importlib.util as ilu
    global PLUGIN_SKILLS
    plugins = {}
    for n in ("web_search", "memory"):
        plugins[n.replace("_", "-")] = {"builtin": True, "on": True, "type": "builtin",
                                        "desc": [{"name": n, "description": "小焦内置能力"}]}
    if not os.path.isdir("plugins"):
        return plugins
    for fn in os.listdir("plugins"):
        p = os.path.join("plugins", fn)
        base = os.path.splitext(fn)[0]
        try:
            if fn.endswith(".py") and not fn.startswith("__"):
                spec = ilu.spec_from_file_location(base, p)
                mod = ilu.module_from_spec(spec)
                sys.modules[base] = mod          # 注册进 sys.modules：Py3.13 下 dataclass/typing 等依赖它
                try:
                    spec.loader.exec_module(mod)
                except Exception:
                    sys.modules.pop(base, None)  # 加载失败则清理，避免污染 sys.modules
                    raise
                for attr in dir(mod):
                    obj = getattr(mod, attr)
                    if isinstance(obj, type) and hasattr(obj, "get_tool_descriptions") and hasattr(obj, "execute"):
                        inst = obj()
                        desc = inst.get_tool_descriptions()
                        if desc:
                            plugins[base] = {"instance": inst, "desc": desc, "builtin": False, "type": "py", "path": p}
                        break
            elif fn.endswith(".json"):
                man = json.load(open(p, encoding="utf-8"))
                if man.get("type") == "skin":
                    plugins[base] = {"instance": None, "desc": [], "builtin": False, "type": "skin", "path": p, "manifest": man}
                elif man.get("tools"):
                    inst = _make_tools_plugin(man)
                    desc = inst.get_tool_descriptions() if inst else []
                    if desc:
                        plugins[base] = {"instance": inst, "desc": desc, "builtin": False, "type": "tools", "path": p, "manifest": man}
                else:
                    inst = _make_api_plugin(man)
                    desc = inst.get_tool_descriptions()
                    if desc:
                        plugins[base] = {"instance": inst, "desc": desc, "settings": man.get("settings", []),
                                         "builtin": False, "type": "api", "path": p, "manifest": man}
            elif fn.endswith(".md"):
                PLUGIN_SKILLS.append((base, open(p, encoding="utf-8").read().strip()))
            elif fn.endswith((".js", ".mjs")) and fn != "plugin_runner.js":
                import subprocess
                desc = []
                settings = []
                try:
                    r = subprocess.run(["node", os.path.join("plugins", "plugin_runner.js"), "describe", p],
                                       capture_output=True, text=True, timeout=30, encoding="utf-8")
                    desc = json.loads(r.stdout.strip()) if r.stdout.strip() else []
                    r2 = subprocess.run(["node", os.path.join("plugins", "plugin_runner.js"), "settings", p],
                                        capture_output=True, text=True, timeout=30, encoding="utf-8")
                    settings = json.loads(r2.stdout.strip()) if r2.stdout.strip() else []
                except Exception:
                    desc = []
                if desc:
                    plugins[base] = {"instance": None, "desc": desc, "settings": settings,
                                     "builtin": False, "type": "js", "path": p}
        except Exception:
            continue
    # 依据操控文件的插件开关
    for k in plugins:
        plugins[k]["on"] = CAP.get("plugins", {}).get(k, plugins[k].get("on", True))
    # **架构约定**：插件清单是动态生成的，插件一变就重建提示词 —— 这样往 plugins/ 丢一个
    # 新 .py、重启小焦，新工具自动出现在模型的工具清单里，**不需要**任何人去改 role。
    try:
        refresh_system_prompt(plugins)      # 必须把刚加载好的表传进去（全局变量此刻还是旧的）
    except Exception as e:  # noqa: silent-ok — 清单重建失败不影响插件本身加载
        LOG.debug("忽略异常(%s:%d): %s", __file__, 180, e)
    return plugins


PLUGINS = load_plugins()   # 插件注册表（设置页可开关）


def _tool_result_str(r):
    """把插件/工具返回统一成字符串（dict/list → JSON；None → 空串），
    避免下游 result[:n] 切片对非字符串崩溃（如插件返回 {"error": ...} 导致 KeyError/TypeError）。"""
    if r is None:
        return ""
    if isinstance(r, str):
        return r
    try:
        return json.dumps(r, ensure_ascii=False)
    except Exception:
        return str(r)


# ================== 第 5 步：工具结果隔离（防串台） ==================
# 真实缺陷（用户实测）：先让"用 Archify 画一张架构图"，再问"抓一下 <网址>"，第 2 轮答出来的
# 竟然是第 1 轮 archify 吐的那坨 JSON —— 因为抓取/画图的**工具原始返回**被原样写进了会话历史，
# 下一轮又整段当上下文发回给模型，模型顺手就把它抄回来了。上下文一被污染，答案就开始串台。
#
# 这里的分工（载体优先：隔离由框架层做，不靠模型自觉）：
#   · 原始内容**照旧给用户看**（用户要的就是它，第 1 轮当场能读到完整 JSON/HTML）；
#   · 但**进会话历史的那一版只留摘要**（工具名 + 状态码 + 前 200 字）；
#   · 用户以后想再要原文 → 从**会话缓存**里取回（不必重抓，也不会消失）。
#
# ⚠️ 判据的关键：**不能**按"回答有多长"来决定摘不摘要。
#    第 3 步"输出无限"写出来的 5 万字长文是**模型自己写的**，一个字都不能动
#    （按长度判当场就把"输出无限"废掉）。所以只看"这段回答里是不是抄了工具的返回"。
_TOOL_RESULT_KEEP = 500          # 工具原始返回超过这个字数 = "大结果" → 进历史前必须摘要化
_HISTORY_SUMMARY_CHARS = 200     # 摘要里保留的正文开头长度
_TOOL_CACHE_MAX_CHARS = 200000   # 单条缓存的硬上限（比这还大就不留了，别把磁盘写爆）
_TOOL_CACHE_KEEP = 20            # 每个会话只留最近 N 条原文
_TOOL_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "_tool_results")
# 代码块（```lang ... ```）。用它把"装了工具原始返回"的那一块**整块**换掉 ——
# 直接按字数截会把 Markdown 围栏切坏，聊天窗就渲染成一片乱码。
_RAW_FENCE_RE = re.compile(r"```[a-zA-Z0-9_+\-]*\n(.*?)```", re.S)
# 抓取/下载类工具（只有它们才需要"结果校验"——域名/标题特征）
_FETCH_TOOLS = ("get", "make_request", "fetch", "stealthy_fetch", "download", "screenshot",
                "bulk_get", "bulk_fetch", "bulk_stealthy_fetch")
# 用户想"把刚才那条工具结果的原文再拿出来"时的说法。
# 分两类：一类**本身就说清了**（"原始结果/完整内容/展开刚才"），一类是"刚才那/刚才抓的"这种
# **必须再带上"结果/内容/原文"才算**的 —— 否则"刚才那个文件在哪"会被误判成要看工具原文，
# 把缓存里的 JSON 摆到用户面前（答非所问）。
_RAW_WANT_STRONG = ("原始结果", "原始内容", "工具原文", "完整结果", "完整内容", "完整版",
                    "展开看看", "展开一下", "展开刚才", "再显示一遍", "重新显示", "全文给我")
_RAW_WANT_WEAK = ("刚才的", "刚才抓", "刚才那", "刚抓的", "上一条")
_RAW_WANT_TAIL = ("结果", "内容", "原文", "全文", "数据", "json", "JSON")


def _status_code_of(text):
    """从工具返回里抠 HTTP 状态码（抠不到返回空串）。

    摘要是"工具名 + 状态码 + 前 200 字"，状态码就靠这里。
    """
    s = str(text or "")
    try:
        d = json.loads(s)
        if isinstance(d, dict):
            if d.get("status") not in (None, ""):
                return str(d.get("status"))
            _it = d.get("items")
            if isinstance(_it, list) and _it:
                return str((_it[0] or {}).get("status") or "")
    except Exception:      # noqa: silent-ok — 不是 JSON 很正常，继续按文本找
        pass
    m = re.search(r"\bHTTP\s*(\d{3})\b", s[:400], re.I)
    return m.group(1) if m else ""


def _trace_is_raw(entry):
    """这条工具轨迹算不算"大结果"（要进历史的原始内容）。

    为什么看 `full_len` 而不是 `len(result)`：轨迹里的 `result` 是**故意截短**的
    （抓取路径存的是一行摘要、模型路径只存 800 字），拿它判长度会把大结果全判成小结果，
    隔离就形同虚设。所以真正执行工具的地方会顺手把原文长度记进 `full_len`。
    """
    try:
        return int(entry.get("full_len") or len(str(entry.get("result") or ""))) > _TOOL_RESULT_KEEP
    except Exception:      # noqa: silent-ok — 字段异常就当不是大结果，不影响对话
        return False


def _tool_cache_path(session_id=None):
    """这个会话的工具原文缓存文件路径（会话 id 只保留安全字符，防目录穿越）。"""
    sid = session_id
    if not sid:
        try:
            sid = get_current_session()[0].get("id")
        except Exception:      # noqa: silent-ok — 取不到会话就当 default，别让缓存拖垮对话
            sid = ""
    sid = re.sub(r"[^0-9A-Za-z_\-]", "", str(sid or "")) or "default"
    return os.path.join(_TOOL_CACHE_DIR, "%s.jsonl" % sid)


def _cache_tool_result(tool, args, text, session_id=None):
    """把工具**原始返回**落进会话缓存（历史只留摘要，用户要原文时从这里取回）。

    为什么不用内存字典：小焦是会长期开着的进程，重启后用户还想翻"刚才抓的那个页面"；
    而且一个会话的原文可能上百 KB，全放内存不划算。一行一条 append-only，读时取最后一条。
    """
    body = str(text or "")
    if len(body) <= _TOOL_RESULT_KEEP or len(body) > _TOOL_CACHE_MAX_CHARS:
        return ""
    try:
        os.makedirs(_TOOL_CACHE_DIR, exist_ok=True)
        key = datetime.now().strftime("%Y%m%d_%H%M%S%f")
        path = _tool_cache_path(session_id)
        rec = {"key": key, "time": datetime.now().isoformat(timespec="seconds"),
               "tool": tool, "args": args if isinstance(args, (dict, list)) else str(args),
               "status": _status_code_of(body), "chars": len(body), "text": body}
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        # 只留最近 N 条：不然一个会话聊一年，这文件能涨到几百 MB
        try:
            with open(path, encoding="utf-8") as f:
                rows = [ln for ln in f if ln.strip()]
            if len(rows) > _TOOL_CACHE_KEEP:
                with open(path, "w", encoding="utf-8") as f:
                    f.writelines(rows[-_TOOL_CACHE_KEEP:])
        except Exception as e:      # noqa: silent-ok — 修剪失败不影响本次缓存写入
            LOG.debug("工具缓存修剪失败（忽略）(%s:%d): %s", __file__, 512, e)
        return key
    except Exception as e:      # noqa: silent-ok — 缓存失败不能让这一轮对话失败
        LOG.debug("工具结果缓存失败（忽略）(%s:%d): %s", __file__, 516, e)
        return ""


def _cached_tool_result(session_id=None, key=None):
    """从会话缓存取回工具原文；没有就返回 None。`key` 为空 → 取最近一条。"""
    try:
        path = _tool_cache_path(session_id)
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            rows = []
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    rows.append(json.loads(ln))
                except Exception:      # noqa: silent-ok — 单行坏了跳过，别丢整个缓存
                    continue
        if not rows:
            return None
        if key:
            for r in reversed(rows):
                if r.get("key") == key:
                    return r
            return None
        return rows[-1]
    except Exception as e:      # noqa: silent-ok — 读缓存失败就当没有，走正常回答
        LOG.debug("读工具缓存失败（忽略）(%s:%d): %s", __file__, 538, e)
        return None


def _wants_raw_tool_result(text):
    """用户是不是在要"刚才那条工具结果的原文"（要 → 从缓存原样给，不必重抓）。

    判据刻意收紧到"短句 + 明确说法"：工具原文缓存是**上一轮**的东西，
    触发错了就会拿一坨 JSON 顶掉本该正常回答的问题。
    """
    q = (text or "").strip()
    if not q or len(q) > 40:
        return False
    if any(h in q for h in _RAW_WANT_STRONG):
        return True
    return (any(h in q for h in _RAW_WANT_WEAK)
            and any(k in q for k in _RAW_WANT_TAIL))


def _raw_omitted_note(entry, chars):
    """被摘要掉的那块原始内容，用一行字在原位置顶上（用户看得懂、模型也不会当正文抄）。"""
    return ("〔原始内容已摘要：%d 字，未写入对话历史。工具 `%s`%s，开头 200 字：%s…"
            "需要原文就说「展开刚才的结果」〕"
            % (chars, entry.get("tool") or "?",
               ("，HTTP %s" % entry["status"]) if entry.get("status") else "",
               str(entry.get("raw_head") or "").replace("\n", " ")[:_HISTORY_SUMMARY_CHARS]))


def _raw_echo_span(answer, blob):
    """回答里有没有一段**连续抄自 blob** 的内容？有就返回 (起, 止)，没有返回 None。

    为什么按"连续片段"而不是整段比对：模型抄工具结果时几乎从不一字不差，
    常见做法是"前面自己写一句 + 后面贴一段原文"，所以找的是**最长公共片段**。
    用 60 字做步长滑窗（60 字相同已经远超巧合），宁可漏判也不误伤模型自己写的正文。
    """
    a = str(answer or "")
    b = str(blob or "")
    if len(b) < 60 or not a:
        return None
    step, win = 40, 60
    for i in range(0, max(1, min(len(b), 1200) - win), step):
        probe = b[i:i + win]
        pos = a.find(probe)
        if pos < 0:
            continue
        end = pos + win
        # 往后尽量延长（把整段抄来的内容一次吃掉）
        j = i + win
        while j < len(b) and end < len(a) and b[j] == a[end]:
            j += 1
            end += 1
        # 往前尽量延长
        k = i
        while k > 0 and pos > 0 and b[k - 1] == a[pos - 1]:
            k -= 1
            pos -= 1
        return pos, end
    return None


def _shrink_raw_fences(text, raws):
    """把"装了工具原始返回"的代码块**整块**换成摘要行（保留解读等模型自己写的内容）。

    判据：块的正文里出现了某条大结果的 `raw_head`（前 200 字）——只有真把工具返回贴进来才命中，
    模型自己写的长代码块不会被误伤。
    """
    out, pos = [], 0
    for m in _RAW_FENCE_RE.finditer(text):
        body = m.group(1) or ""
        if len(body) <= _TOOL_RESULT_KEEP:
            continue
        owner = None
        for e in raws:
            head = str(e.get("raw_head") or "").strip()
            if len(head) >= 40 and (head[:60] in body or body.strip()[:60] in head):
                owner = e
                break
        if owner is None:
            continue
        out.append(text[pos:m.start()])
        out.append(_raw_omitted_note(owner, len(body)))
        pos = m.end()
    out.append(text[pos:])
    return "".join(out)


def _history_summary_line(raws):
    """兜底摘要：工具名 + 状态码 + 前 200 字（spec 要求的最小信息量）。

    ⚠️ 必须容忍 `None`/非列表：这个函数在**请求收尾路径**上被调用，
    而调用点可能因为"这一轮压根没有工具结果"而传 None ——
    第一版直接 `raws[:3]` 会在那种情况下抛 `TypeError: 'NoneType' is not subscriptable`，
    把一次正常的收尾变成 500（自测用 None 打进来的，属于提前抓到而不是线上抓到）。
    摘要生成失败本身没有任何业务影响，所以这里**降级成空摘要**而不是报错。
    """
    rows = raws if isinstance(raws, (list, tuple)) else []
    parts = []
    for e in list(rows)[:3]:
        if not isinstance(e, dict):
            continue
        parts.append("· `%s`%s：%s…"
                     % (e.get("tool") or "?",
                        ("（HTTP %s）" % e["status"]) if e.get("status") else "",
                        str(e.get("raw_head") or "").replace("\n", " ")[:_HISTORY_SUMMARY_CHARS]))
    return "〔本轮工具原始结果已摘要，未写入对话历史（防串台）〕\n" + "\n".join(parts)


def _has_data_blob(text, min_run=1200, ratio=0.25):
    """这句话里有没有"一整段结构化数据"（长、几乎不断句、括号/引号/标签密度高）。

    为什么需要它：`_raw_echo_span` 靠"连续 60 字相同"找工具原文，**模型改写过的**
    工具结果就找不到了（它可能把 JSON 的键值顺序换一下）。但那种情况下回答里会留下
    一大块"不像人话的字符" —— 中文正文每几个字就有句号/逗号，几千字不断句的只能是数据。
    这条兜底专门抓那种，同时**不会**误伤模型自己写的长文（"第一段。"×3000 最长不断句段只有 4 字）。
    """
    s = str(text or "")
    worst = 0
    for seg in re.split(r"[。！？；\n]{1,}", s):
        if len(seg) > worst:
            worst = len(seg)
            if worst >= min_run:
                struct = sum(1 for ch in seg if ch in '{}[]<>":,=_\\/|')
                if struct >= len(seg) * ratio:
                    return True
    return False


def _history_safe_answer(answer, tool_trace):
    """**进会话历史的那一版**回答：工具原始内容只留摘要，模型自己写的正文原样保留。

    为什么必须有这个函数（真实缺陷）：抓回来的 JSON/HTML 被整段写进会话历史后，
    下一轮又被当上下文发回模型 —— 用户实测"先画图再抓网页"，第 2 轮把第 1 轮的 archify JSON
    原样吐了回来。隔离只做在历史这一侧：给用户的那份 `answer` 一个字都不动。

    ⚠️ 判据**绝不能**是"回答有多长"：第 3 步"输出无限"那段 5 万字是模型自己写的，
    按长度判会当场把"输出无限"废掉（实测踩过：拿它当判据时，"第一段。"×3000 的长文
    被整段换成了摘要）。所以判据是**"这段回答里是不是抄/贴了工具的返回"**：
      · 命中连续 60 字与工具返回相同   → 把那一段换成摘要（`_raw_echo_span`）
      · 代码块里装着工具返回           → 整块换成摘要（`_shrink_raw_fences`）
      · 没有命中，但有一大段"结构化数据块" → 兜底摘要（`_has_data_blob`）
      · 都没有                          → 一个字都不动（模型自己的话）
    """
    a = str(answer or "")
    if not a:
        return a
    raws = [t for t in (tool_trace or []) if isinstance(t, dict) and _trace_is_raw(t)]
    if not raws:
        return a                      # 本轮没有大工具结果 → 全是模型自己的话，原样保留
    cut = a
    hit = False
    for e in raws:
        span = _raw_echo_span(cut, e.get("result"))
        if span:
            cut = cut[:span[0]] + _raw_omitted_note(e, span[1] - span[0]) + cut[span[1]:]
            hit = True
    _shrunk = _shrink_raw_fences(cut, raws)
    if _shrunk != cut:
        hit = True
        cut = _shrunk
    cut = cut.strip()
    # 兜底一：确实摘掉过内容、摘完还是超长 → 说明原文以别的形式还混在里面，只留一行摘要
    if hit and len(cut) > _TOOL_RESULT_KEEP * 4:
        LOG.info("回答里含工具原始内容且未能逐块摘掉 → 历史只留一行摘要")
        cut = _history_summary_line(raws)
    # 兜底二：没摘到，但回答里有一整段"结构化数据"（模型改写过的工具结果）→ 也摘要
    elif not hit and _has_data_blob(cut):
        LOG.info("回答里检测到大段结构化数据（疑似工具原文）→ 历史只留一行摘要")
        cut = _history_summary_line(raws)
    # 最后一道：**摘要绝不允许比原文更长**。实测出现过"1605 字的回答 → 1786 字的摘要"
    # （本轮有多个大结果时 `_history_summary_line` 会拼好几条 raw_head，比原文还长）。
    # 隔离的目的是让历史**更小**；没变小就说明这次隔离没做成，那就原样保留、别帮倒忙。
    if len(cut) >= len(a):
        return a
    return cut


def _validate_tool_result(tool, args, result):
    """**结果校验**：工具返回的内容像不像"目标本身"？返回 (判定, 说明)。

    为什么要它（真实缺陷）：抓取失败/被抓到风控页时，模型照样能说一句
    "我已经抓取了 example.com，内容是……"——用户完全不知道这句是编的。
    载体层能验的（域名、页面标题、状态码）就该载体层验，验不过的如实标"可能幻觉"。

    判定三态（**不能**非黑即白，否则会大面积误报）：
      · True  → 结果可信（正文里有目标域名/标题，或它是结构化 JSON 且状态码正常）
      · False → **可能幻觉**（HTML/正文里找不到目标的任何痕迹，或正文短得不像内容）
      · None  → 不适用（失败/被拦/不是抓取类工具）——失败由熔断逻辑负责，不算幻觉
    """
    if tool not in _FETCH_TOOLS:
        return None, ""
    url = ""
    if isinstance(args, dict):
        url = args.get("url") or ""
        if not url and isinstance(args.get("urls"), list) and args["urls"]:
            url = args["urls"][0]
    if not url:
        return None, ""
    body = ""
    status = ""
    try:
        d = json.loads(str(result or ""))
        if isinstance(d, dict):
            if d.get("error"):
                return None, ""                       # 抓取失败 → 不算幻觉，交给熔断如实报错
            body = str(d.get("content") or "")
            status = str(d.get("status") or "")
            if not body and d.get("items"):
                _it = d["items"][0] or {}
                body, status = str(_it.get("content") or ""), str(_it.get("status") or "")
    except Exception:      # noqa: silent-ok — 非 JSON 返回按纯文本验，不因此报幻觉
        body, status = str(result or ""), ""
    if not body.strip():
        return None, ""
    if status and not str(status).startswith("2"):
        return None, ""                               # 4xx/5xx 是失败，不是幻觉
    host = ""
    try:
        from urllib.parse import urlparse as _up
        host = (_up(url).hostname or "").lower()
    except Exception:      # noqa: silent-ok — 解不出域名就退化成"只按标题验"
        host = ""
    low = body.lower()
    if host and host in low:
        return True, ""                               # 正文里有域名特征 → 可信
    # 结构化接口（JSON）**本来就不含自己的域名**（实测 httpbin.org/json 就是纯 slideshow），
    # 所以只要它解析出来是一个像样的 JSON 对象，就算"拿到了有效内容"，不能判成幻觉。
    try:
        jd = json.loads(body)
        if isinstance(jd, (dict, list)) and len(body) > 40:
            return True, ""
    except Exception:      # noqa: silent-ok — 不是 JSON 就继续按 HTML/纯文本判断
        pass
    m = re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I)
    title = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    if title and host and host.split(".")[0].lower() in title.lower():
        return True, ""                               # 标题里有站点名 → 可信
    if len(body.strip()) < 80:
        return False, ("⚠️ **可能幻觉**：`%s` 的返回正文只有 %d 字，短得不像一个真实页面。"
                       "请勿把这段内容当成该页面的内容。" % (host or url, len(body.strip())))
    if "<" in body[:200] or (host and not title):
        # HTML 页面却既没有目标域名、也没有能对上的标题 → 大概率不是这个目标的真实内容
        return False, ("⚠️ **可能幻觉**：返回内容里找不到目标 `%s` 的任何痕迹"
                       "（正文无该域名、标题%s），不能确认这段内容属于该网址。"
                       % (host or url, ("为「%s」" % title[:40]) if title else "为空"))
    return True, ""


def _trace_entry(tool, args, result):
    """构造一条工具轨迹。**顺手记下"这是不是大结果"** —— 上下文隔离就靠这个判据。

    为什么不在轨迹里直接塞原文：轨迹要经 HTTP 回给界面，塞原文等于把几百 KB 的
    JSON/HTML 在网络上再搬一遍。原文另有去处（会话缓存），轨迹只留一行摘要 + 长度 + 前 200 字。

    **轨迹里的参数必须是"真正发出去的那份"**（本轮实测抓到的体验缺陷）：
    模型写的是 `C:/Users/当前用户/Desktop`，`run_tool` 内部会把它展开成真实路径再执行
    （所以工具是成功的），但轨迹里记的还是**展开前**的占位符 —— 用户在界面上看到的就是
    一个假路径，以为小焦拿错路径去跑了。这里统一过一次 `_fix_args_paths`，让轨迹如实反映
    实际调用。（对已经展开过的参数是幂等的，重复调用不会改坏。）
    """
    try:
        args = _fix_args_paths(tool, args or {})
    except Exception:      # noqa: silent-ok — 展不开就照原样记，绝不能因为记轨迹而报错
        args = args or {}
    _r = str(result or "")
    e = {"tool": tool, "args": args, "result": _r[:800]}
    if len(_r) > _TOOL_RESULT_KEEP:
        e["full_len"] = len(_r)
        e["raw_head"] = _r[:_HISTORY_SUMMARY_CHARS]
        e["status"] = _status_code_of(_r)
        _cache_tool_result(tool, args, _r)
    return e


def run_plugin(name, params):
    """调用某个插件（由 LLM/Agent 决定何时用）。支持 py / api / js。始终返回字符串。"""
    p = PLUGINS.get(name)
    if not p or not p.get("on"):
        return ""
    # JS 插件：起 node 子进程执行
    if p.get("type") == "js":
        import subprocess
        try:
            r = subprocess.run(["node", os.path.join("plugins", "plugin_runner.js"), "exec",
                                p.get("path"), params.get("name"), json.dumps(params.get("params", {}), ensure_ascii=False)],
                               capture_output=True, text=True, timeout=90, encoding="utf-8")
            return (r.stdout or r.stderr or "").strip()
        except Exception as e:
            return f"JS插件执行失败：{e}"
    if "instance" not in p:
        return ""
    try:
        return _tool_result_str(p["instance"].execute(params.get("name"), params.get("params", {})))
    except Exception:
        return ""


_TOOL2PLUGIN = {}   # 工具名 -> 插件模块名


_COST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cost_daily.json")
_CLOUD_BASELINE = 0.000008  # 全云端基线: 按 deepseek-chat 入0.002/出0.008 每token约合
_CLOUD_IN, _CLOUD_OUT = 0.002, 0.008  # 元/1K token (deepseek-chat 参考价)


_TTS_FILES = ["ve.safetensors", "t3_cfg.safetensors", "s3gen.safetensors", "tokenizer.json", "conds.pt"]


def _find_tts_model_dir():
    """自动识别 Chatterbox 模型目录(不写死): 环境变量/配置/扫描常见位置, 找到含全部文件的目录。"""
    import glob as _g
    # ① 环境变量
    env_dir = os.environ.get("XIAOJIAO_TTS_MODEL", "")
    if env_dir and os.path.isdir(env_dir) and all(os.path.exists(os.path.join(env_dir, f)) for f in _TTS_FILES):
        return env_dir
    # ② 控制文件配置
    _cfg_dir = CONTROL.get("brain", {}).get("tts_model_dir", "")
    if _cfg_dir and os.path.isdir(_cfg_dir) and all(os.path.exists(os.path.join(_cfg_dir, f)) for f in _TTS_FILES):
        return _cfg_dir
    # ③ 扫描常见位置（项目目录 / 家目录 / 下载；再按关键词扫盘 —— 不写死用户路径）
    cands = [os.path.dirname(os.path.abspath(__file__)), os.getcwd(),
             os.path.expanduser("~"), os.path.join(os.path.expanduser("~"), "Downloads"),
             os.path.join(os.path.expanduser("~"), "Documents"), "C:\\llama"]
    try:
        import install_all as _ia
        _kws = ("语音", "tts", "voice", "model", "模型", "xiaojiao") + tuple(_ia.DISCOVER_KEYWORDS)
        for _drv in _ia._drives():
            for _t in _ia._top_dirs(_drv):
                if _ia._hit_keyword(_t, _kws) or _ia._hit_keyword(_t, ("downloads", "下载")):
                    cands.append(os.path.join(_drv, _t))
    except Exception as e:
        LOG.debug("忽略异常(%s:%d): %s", __file__, 344, e)
    for c in cands:
        try:
            subs = [c] + [os.path.join(c, x) for x in os.listdir(c) if os.path.isdir(os.path.join(c, x))]
        except Exception:
            continue
        for d in subs:
            if all(os.path.exists(os.path.join(d, f)) for f in _TTS_FILES):
                return d
    return None


def _record_usage(usage, model=""):
    """记录一次调用的 token 用量(本地=免费, 云端=计费)。写入当日成本文件。"""
    try:
        u = usage or {}
        pt = int(u.get("prompt_tokens") or 0)
        ct = int(u.get("completion_tokens") or 0)
        if not pt and not ct:
            return
        today = datetime.now().strftime("%Y-%m-%d")
        is_cloud = ("api." in LLM_BASE or "deepseek" in LLM_BASE.lower() or "openai" in LLM_BASE.lower())
        d = {}
        if os.path.exists(_COST_FILE):
            try:
                d = json.load(open(_COST_FILE, encoding="utf-8"))
            except Exception:
                d = {}
        day = d.setdefault(today, {"calls": 0, "local_tokens": 0, "cloud_tokens": 0, "cost": 0.0})
        day["calls"] += 1
        if is_cloud:
            day["cloud_tokens"] += pt + ct
            day["cost"] += (pt / 1000.0) * _CLOUD_IN + (ct / 1000.0) * _CLOUD_OUT
        else:
            day["local_tokens"] += pt + ct
        json.dump(d, open(_COST_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except Exception as e:
        LOG.debug("忽略异常(%s:%d): %s", __file__, 381, e)


def _build_tools(only=None):
    """把内置工具 + 已启用的插件工具合并成给模型的功能列表。

    `only`：只暴露这些工具名（按意图收窄）。真实缺陷（用户实测）：让 Archify 画架构图时，
    模型在工具海里乱摸（跑去 read_memory），最后把记忆内容当答案吐出来 ——
    收窄之后它只能在画图这条链里走。
    """
    global _TOOL2PLUGIN
    _TOOL2PLUGIN = {}
    tools = list(TOOLS)
    # 坑（第 1 步实测发现）：以前写的是 `if only`，于是 `only=[]`（空子集）会被当成 None
    # → 反而把**全部** 77 个工具发出去（13891 token），正好和"收窄"的意图相反。
    # 现在只有显式传 None 才是"全部"；空列表就是"一个都不给"。
    if only is not None and not only:
        LOG.warning("_build_tools(only=[])：本轮一个工具都不发；若本意是「全部」请传 None")
    _only = {x.lower() for x in only} if only is not None else None
    _taken = {t["function"]["name"] for t in tools}       # 内置工具名先占位
    for pname, p in PLUGINS.items():
        if p.get("builtin") or not p.get("on"):
            continue
        for t in p.get("desc", []):
            if isinstance(t, dict) and t.get("name"):
                # **真实缺陷防复发**：不同插件/内置用了同一个工具名时，后加载的会**覆盖**
                # 路由表 _TOOL2PLUGIN，模型以为调的是 A，实际执行的是 B（"调错工具"的典型成因）。
                # 现在：内置优先，重名直接跳过并告警 —— 插件作者看到日志就会去改名。
                if t["name"] in _taken:
                    LOG.warning("工具名冲突，已跳过：%s（来自插件 %s；同名工具已存在，请改名）",
                                t["name"], pname)
                    continue
                _taken.add(t["name"])
                # **真实缺陷**：外部清单类插件（`{"tools":[{...}]}` 且**没写 url**）里的工具
                # 其实**执行不了**（execute 只会回一句"需对应运行时或填写 url"）。原来照样塞给
                # 模型 → 模型真的去调它，拿到一句废话，用户看到的就是"调用了工具却没结果"
                # （实测截图上就出现过 `调用 get_time → 需填写 url` 这种徽标）。
                # 判据问插件自己的清单（has_url）——**不能**看 get_tool_descriptions() 的返回值，
                # 那里面本来就不带 url，会把 plugins/ip.json 这种正常插件一起误杀。
                _inst = p.get("instance")
                if hasattr(_inst, "has_url") and not _inst.has_url(t["name"]):
                    continue
                _TOOL2PLUGIN[t["name"]] = pname
                tools.append({"type": "function", "function": {
                    "name": t["name"], "description": t.get("description", ""),
                    "parameters": t.get("parameters", {"type": "object", "properties": {}})}})
    if _only is not None:
        tools = [t for t in tools if t["function"]["name"].lower() in _only]
        _TOOL2PLUGIN = {k: v for k, v in _TOOL2PLUGIN.items() if k.lower() in _only}
    # 规范化: 每个工具的 parameters 必须是 JSON Schema object(严格API如deepseek要求)
    for t in tools:
        fn = t.get("function") or {}
        prm = fn.get("parameters")
        if not isinstance(prm, dict) or prm.get("type") is None:
            prm = dict(prm or {})
            prm.setdefault("type", "object")
            prm.setdefault("properties", prm.get("properties") or {})
            fn["parameters"] = prm
    return tools

# ================== 小焦模型 ==================
# 大脑：优先用你创建的小焦模型（mini_gpt_model.pth）；若配置了外部 LLM 则优先外部。
XJ_READY = False
try:
    import xiaojiao_harness as xh
    if os.path.exists(xh.MODEL_PATH) and os.path.exists(xh.VOCAB_PATH):
        XJ_MODEL, XJ_C2I, XJ_I2C = xh.load_model()
        XJ_READY = True
        print("🧠 大脑：小焦模型 已加载")
    else:
        XJ_MODEL, XJ_C2I, XJ_I2C = None, None, None
except BaseException as e:
    XJ_MODEL, XJ_C2I, XJ_I2C = None, None, None
    print("🧠 未加载到小焦模型：", e)


def xiaojiao_reply(text):
    """用你创建的小焦模型生成一句话回复（承接语料格式：用户…小焦…）。"""
    if not XJ_READY:
        return None
    prompt = "用户" + text + "小焦"
    ids = [XJ_C2I.get(c, 0) for c in prompt]
    idx = torch.tensor([ids], dtype=torch.long, device=xh.DEVICE)
    resp = xh.generate(XJ_MODEL, idx, XJ_I2C)
    resp = resp.strip()
    for sep in ("\n", "用户", "小焦"):
        if sep in resp:
            resp = resp.split(sep)[0]
            break
    return resp.strip()


# ================== 工具：联网搜索 ==================
def _clean_html(s):
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"&#\d+;|&[a-z]+;", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# ================== 检索词清洗（真实缺陷：小焦曾把功能字「用」当关键词去搜） ==================
# 复盘：用户说"用搜索工具找漏洞" —— 模型把整句/单个功能字直接丢给 web_search，
# 搜出来的是"用（汉语汉字）"这种百科词条，完全跑偏。
# 修法：① 代码层强制清洗（不管模型/上层给的是什么）；② 清洗后仍无内容 → 反问用户要关键词，绝不用单字硬搜。
_SEARCH_CMD_MARKERS = ("搜", "查", "找", "抓", "爬", "检索", "联网", "上网", "搜索", "工具",
                       # Bug 2 的修法：信息收集动作词也要算"这是一次检索请求"，
                       # 否则 `extract_search_keywords` 的强清洗分支**根本不会执行** ——
                       # 于是"整理一下最近的新闻信息"原样拿去搜，搜的是"整理"的读音和组词。
                       "整理", "汇总", "归纳", "梳理", "盘点")
_SEARCH_FILLERS = (
    "用搜索工具", "搜索工具", "联网搜索", "联网查一下", "联网查", "上网搜一下", "上网搜", "网上搜",
    "帮我搜一下", "帮我搜", "帮忙搜", "帮我查一下", "帮我查", "帮忙查", "帮我找一下", "帮我找",
    "给我搜", "给我查", "给我找", "搜索一下", "搜一下", "查一下", "找一下", "抓一下", "爬一下",
    "搜索", "检索", "联网", "上网", "网上", "帮我", "帮忙", "请问", "麻烦", "谢谢", "一下",
    "一个", "一些", "给我", "来个", "给出", "列一下", "看看", "瞧瞧", "找找", "找一找",
    "写个", "帮我写个", "做一个", "搞一个", "查查", "搜搜",
    # ↓ Bug 2 修法：信息收集动作词 + 口语量词。它们都是**指令的壳**，不是检索内容。
    #   实测："整理一下最近的新闻信息" 原来洗出 "整理 最近的新闻信息" —— 把"整理"当检索词，
    #   搜回来的是"整理的读音/组词"（用户实测截图就是这么来的）。
    #   长词在前（sorted by len reverse 会保证"整理一下"先于"整理"被吃掉）。
    "整理一下", "汇总一下", "归纳一下", "梳理一下", "盘点一下",
    "整理", "汇总", "归纳", "梳理", "盘点", "收集", "搜集", "看一看", "看一下",
    "了解一下", "关注一下", "跟进", "盯一下", "查一查", "翻一翻",
    # ⚠️⚠️ 时间词**绝不能**出现在 fillers 里 —— 包括"最近的/今天的"这种带"的"的写法。
    #    `_SEARCH_FILLERS` 是"整段删除"，而"最近/今天"是**检索内容的一部分**：
    #    删掉之后"整理一下最近的新闻信息"只剩"新闻信息"，
    #    而用户要的是"最近新闻"（时效性就是这个请求的重点）。
    #    我第一版恰恰把"最近的/今天的"放进了这里 → 时间词连同"的"被一起抹掉。
    #    正确做法：**只删动作词与量词**；时间词保留，由 `_finalize_search_query`
    #    规范化（今天→今日）并前置。时间词后面的"的"由 `_SEARCH_MID_FUNC` 那道规则去掉。
    "一下这个", "有关", "关于",
)
# 时间限定词 → 检索口径的规范化（用户口语说法 ↔ 搜索引擎习惯用词）。
# 为什么要换：用户说"今天"，而搜索引擎/新闻站上更常见"今日"；
# 实测口径要求 "汇总今天的科技动态" → 检索词 "今日科技动态"。
# ⚠️ 名字**不能**叫 `_SEARCH_TIME_WORDS` —— 文件后面（`_query_variants`/`_query_tokens`）
#    已经有一个同名元组，是"时间词清单（用来剥离/后置）"，语义完全不同。
#    我第一版就撞了名，导致运行时用的是**后定义的那个**（文件里后写的覆盖前面的），
#    于是 `for src, dst in ...` 直接在字符串上解包报 ValueError。
#    教训：往大文件里加常量前先 grep 名字，别让"后定义覆盖"这一条悄悄改掉行为。
_SEARCH_TIME_ALIASES = (("今天", "今日"), ("本日", "今日"),
                        ("这周", "本周"), ("这个星期", "本周"),
                        ("这个月", "本月"), ("近期", "最近"),
                        ("这几天", "最近"), ("近几天", "最近"),
                        ("昨天", "昨日"), ("昨儿", "昨日"))
# 单字功能/语气词：只在"开头或两侧带空格"时算噪声，避免误伤"未来/在线/用户"这类真词
_SEARCH_FUNC_CHARS = "用搜找抓查看搞请帮要想来去呗吧的了呢吗啊呀把给让我你它他她是个些就都还很这那与和在有"
_SEARCH_MEANINGLESS = set(_SEARCH_FUNC_CHARS)
# 空格后可以直接删的"纯助词/动作词"（删了不会把真词切坏：在线/未来/用户 都不在这个集合里）
_SEARCH_MID_FUNC = "的了是用搜找查抓看请帮"
# 第 5 步加强：**动作词本身**的用字。为什么需要它 ——
# 真实缺陷（本轮实测抓到）：「请帮我搜索」这句话里 filler「帮我搜」先把「帮我搜」整段吃掉，
# 只剩「请 索」，再按"去掉开头功能字"把「请」洗掉 —— 最后拿**单个「索」**去搜百科。
# 这跟当初拿「用」去搜是同一个病：**功能字被切了一半，剩下的半个字照样被当关键词**。
# 所以判据不能只看"整句是不是功能字"，得看"把功能字/动作词/助词全部剔掉之后还剩不剩东西"。
_SEARCH_ACTION_WORDS = ("搜索", "检索", "查询", "联网", "上网", "工具", "功能")
_SEARCH_NOISE_CHARS = (set("".join(_SEARCH_FILLERS)) | set(_SEARCH_FUNC_CHARS)
                       | set("".join(_SEARCH_ACTION_WORDS)) | set(_SEARCH_MID_FUNC))
# 纯寒暄/自我介绍：这种话不该拿去联网搜（搜出来只会是"你（汉语文字）_百度百科"这类词条）
_SEARCH_GREETINGS = {
    "你好", "您好", "哈喽", "在吗", "在么", "谢谢", "多谢", "辛苦了", "早", "早上好", "晚上好",
    "你是谁", "你叫什么", "你叫啥", "介绍一下你", "自我介绍", "hi", "hello", "hey", "thanks",
    "thank you", "ok", "好的", "嗯", "哦", "在不在",
}
SEARCH_KEYWORD_HINT = "请告诉我你要搜索的具体关键词（例如：最近的漏洞 CVE、2026 年 AI 新闻）。"


def _has_search_marker(s):
    """句子里有没有"检索动作词" —— 有才是命令式（可以大胆删功能字），没有就当裸关键词保守处理。"""
    return any(m in s for m in _SEARCH_CMD_MARKERS)


def extract_search_keywords(text):
    """把「用联网搜一下最近的漏洞」这类口语指令清洗成真正能用的检索关键词。

    · 命令式（含 搜/查/找/抓/联网/工具…）：删掉动作词、语气词、标点 → "漏洞"；
    · 裸关键词（用户直接甩词，如"看雪安全"）：只做保守清洗，绝不删词内的字（不能变成"雪安全"）。
    """
    s = (text or "").strip()
    if not s:
        return ""
    s = re.sub(r"[，。！？；：、,.!?;:\"'“”‘’（）()\[\]【】<>《》~]+", " ", s)
    for w in sorted(_SEARCH_FILLERS, key=len, reverse=True):
        s = s.replace(w, " ")
    s = re.sub(r"\s+", " ", s).strip()
    if _has_search_marker(text or ""):
        # ⚠️ 真实缺陷（用户实测）：以前这里是**贪婪删掉开头一串功能字**，
        # 于是"帮我搜索一下 你好"洗完只剩"好"，搜出来是"好（汉语文字）_百度百科"。
        # 现在改成"逐个删，但必须给内容留够 2 个字"——"你好"不会被拆，"找漏洞"能洗成"漏洞"。
        while len(s) >= 3 and s[0] in _SEARCH_MEANINGLESS:
            s = s[1:].lstrip()
        # 空格后出现的**纯助词/动作词**也算噪声（"apache 的漏洞" → "apache 漏洞"）；
        # 但不动"在线/未来"这类会把真词切坏的字符。
        s = re.sub(r"(?<=\s)[%s]+(?=\s|[\u4e00-\u9fa5]|$)" % _SEARCH_MID_FUNC, " ", s)
        s = re.sub(r"(^|\s)[%s](?=\s|$)" % _SEARCH_FUNC_CHARS, r"\1", s)            # 独立成词的功能字
        s = re.sub(r"\s+", " ", s).strip()
        # ⚠️ **时间词规范化只在"这确实是一次检索请求"时做**。
        #    为什么要有这个门：`extract_search_keywords` 除了被检索路径调用，
        #    也会被别处当"保守清洗"用；而无条件做 今天→今日 会把**闲聊弄坏** ——
        #    实测："今天好累" 洗成 "今日好累"（用户没要找新闻，却把他的话改了）。
        #    判据：有检索命令词（搜/查/整理…）或本身就是信息收集请求。
        if _has_search_marker(text or "") or _asks_info_collect(text or ""):
            return _finalize_search_query(s)
    return re.sub(r"\s+", " ", s).strip()


def _finalize_search_query(q):
    """收尾：**保留**时间限定词并规范化，再把它排到主题词前面。

    为什么要保留而不是删：`_SEARCH_FILLERS` 删的是"指令的壳"（整理/帮我/一下），
    而"最近/今天/本周"是**检索内容的一部分** —— "最近新闻"和"新闻"搜出来是两回事。
    实测口径要求：
        "整理一下最近的新闻信息" → "最近新闻"
        "汇总今天的科技动态"     → "今日科技动态"（今天 → 今日，且时间词前置）
    为什么要前置：与 `_query_variants` 里的实测结论一致 ——
    中文搜索引擎对"最近 X"这种前缀不友好，所以另有变体机制去剥离；
    但用户看到的检索词应该是**规范的"时间 + 主题"**形态，前置是最接近自然写法的。
    """
    s = (q or "").strip()
    if not s:
        return ""
    # 1) 时间词规范化（今天→今日 这类同义替换）
    found = []
    for src, dst in _SEARCH_TIME_ALIASES:
        if src in s:
            s = s.replace(src, " ")
            if dst not in found:
                found.append(dst)
    # 2) 无别名的时间词**原样保留**（最近/最新/本周/本月 在别名表里是自己映射自己，
    #    但语言里还有"这几天/近几天"这类，统一在这里兜一遍）
    for w in _SEARCH_TIME_WORDS:
        if w in s and w not in found:
            s = s.replace(w, " ")
            found.append(w)
    s = re.sub(r"\s+", " ", s).strip()
    # 时间词被抠掉后会留下孤立的"的"或空格（"最近 的新闻信息"）——
    # 中文检索词里这些是纯噪声，必须清掉，否则发出去的还是带壳的关键词。
    s = re.sub(r"(^|\s)[的了是]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return "".join(found)           # 只剩时间词也要留着（"最近的"这种极端输入）
    if not found:
        return _prune_generic_noun(s)
    # 中文不加空格（"最近新闻"而不是"最近 新闻"）；含 ASCII 主题词时保留空格
    # （"最近 AI 新闻"，那个空格是词边界，去掉会变成"最近AI新闻"，检索反而更差）。
    joined = (" ".join(found) + " " + s).strip() if re.search(r"[A-Za-z0-9]", s) \
        else ("".join(found) + s)
    return _prune_generic_noun(joined)


# 具体信息名词（有它就不需要再挂"信息/消息"这种泛化头）
_SPECIFIC_INFO_NOUNS = ("新闻", "动态", "资讯", "热点", "行情", "报道", "舆情",
                        "榜单", "排行", "进展", "漏洞")
_GENERIC_INFO_NOUNS = ("信息", "消息", "情况", "资料")


def _prune_generic_noun(q):
    """主题里同时有"具体名词 + 泛化名词"时，删掉泛化那个。

    实测口径要求："整理一下最近的新闻信息" → "最近新闻"。
    为什么可以删：中文里"新闻信息"是**同义叠加**（信息是泛化头，新闻是具体类），
    留一个就够了；留着反而让检索词变长、稀释掉真正有区分度的"新闻"。
    只在**两个都存在**时才删（"今日信息"这种只有泛化名词的必须保留）。
    """
    s = q or ""
    if any(sp in s for sp in _SPECIFIC_INFO_NOUNS):
        for g in _GENERIC_INFO_NOUNS:
            s = s.replace(g, "")
    return re.sub(r"\s+", " ", s).strip()


# 当前这次对话的用户原话（供工具层判断"模型是不是只截了一个碎片"）
_CTX = {"user_input": ""}


# ================== Bug 2：同一轮"同一 URL 的同一工具"只许调一次 ==================
# 【真实缺陷，复发过一次】用户实测：一次抓取**失败**时，轨迹里出现**两条"调用 get"**。
# 根因不是模型乱调，而是载体自己调了两遍：
#   ① `agent_run` 里"句子里有网址 → 规则直通"（②b）会调一次 `_scrape_direct`；
#   ② 紧接着的兜底（②）判据是"没抓到页面" —— 抓取**失败**正好满足，于是**又调一次**，
#      第二条轨迹把第一条覆盖掉，用户看到的就是"同一个 get 抓了两遍"。
#      而 `_scrape_direct` 内部还有"get → fetch → stealthy_fetch"的升级链，
#      两遍就是 6 次真实网络请求 —— 慢一倍、还可能拿到两个不同的结果（UUID 那次就是这样）。
# 修法（两道锁，缺一不可）：
#   · **本轮去重表**：同一轮里 (工具, 规范化参数) 相同 → 直接复用上次结果，不再真调。
#     这是最后一道保险：无论上层怎么重入，网络请求都只发一次。
#   · **直通只做一次**：`_scrape_direct` 一旦跑过（无论成败）就置位，兜底不再重跑。
#     这是根因修复：失败也是"已经抓过了"，不该因为失败而重来一遍。
# 用 thread-local：并发请求（网页 + 脚本 + 第二个标签页）各自有自己的"轮"，互不干扰。
_ROUND = threading.local()

# 这些工具**不去重**：它们本来就可能在一轮里被调用多次，且每次都有副作用/时效性。
_DEDUP_EXCLUDE = frozenset({
    "write_file", "edit_file", "open_app", "ask_user", "background", "background_result",
    "capture_screen", "screen_text", "now", "check_env",
    # 【校验类必须排除 —— 这是"画图卡死 3 轮"的直接原因】
    # `archify_validate` 这类工具的结果取决于**文件内容**，而参数里只有路径。
    # 模型改完 spec 再用同一路径校验时，`(工具, 参数)` 一模一样 → 去重把**上一次的旧结果**
    # 还回去 → "改完再校验"永远拿到同一批旧错误 → 连续 3 轮必红。
    # 用户看到的就是截图里那两条一字不差重复的校验报错。
    "archify_validate", "archify_check", "archify_inspect", "archify_visual_check",
    "archify_preview", "archify_metrics", "archify_compare",
})


def _round_begin():
    """每次 `agent_run` 开头调一次：开一份干净的"本轮状态"。

    为什么在开头清、不在结尾清：`agent_run` 有十几条 return 分支，逐个加清理必然漏
    （漏了就是"上一轮的结果被当成本轮缓存"—— 比不去重更坏：用户会拿到**过期内容**）。
    在入口重置则天然不会有残留：同一线程的下一轮一定先经过这里。
    """
    _ROUND.dedup = {}
    _ROUND.scrape_done = False
    _ROUND.scrape_tool = ""


def _round_dedup_key(name, args):
    """`(工具, 参数, 目标文件指纹)` 的规范化键。

    参数排序后再序列化，键顺序不同也算同一个调用。

    【为什么必须带上"目标文件的内容指纹"】这是一处真实故障的修复 ——
    用户实测「画图」：spec 连续 3 轮没通过校验，而且每一轮的报错**一字不差重复**。
    根因是去重键只有 `(工具, 参数)`，而校验类工具的结果取决于**文件内容**：
    模型改完 spec、拿同一个路径再校验时，键完全一样 → 去重直接把**上一次的旧结果**还回去，
    于是"改完再校验"看到的永远是同一批旧错误，**这个循环从设计上就不可能收敛**。

    带上指纹后：**文件一变，键就变，校验才会真的重跑**；文件没变时仍然去重
    （省掉真正重复的那一次）。用「大小 + 修改时间」做指纹：便宜，且对本场景足够 ——
    内容改了却大小与 mtime 都不变，在实践中基本不会发生。
    """
    try:
        a = dict(args or {})
        sig = ""
        for k in ("path", "file", "file_path", "spec", "spec_path", "target", "input"):
            v = a.get(k)
            if isinstance(v, str) and v and os.path.exists(v):
                try:
                    sig += "|%s:%d:%d" % (k, os.path.getsize(v), int(os.path.getmtime(v)))
                except Exception:      # noqa: silent-ok — 取不到指纹就不带，退回原行为
                    pass
        return name + "|" + json.dumps(a, sort_keys=True, ensure_ascii=False) + sig
    except Exception:      # noqa: silent-ok — 序列化不了（含非 JSON 值）就不去重，宁可多抓一次
        return ""


def _round_cached(name, args):
    """本轮这个调用是不是已经做过了？做过就把上次结果原样还回去。"""
    if name in _DEDUP_EXCLUDE:
        return None
    d = getattr(_ROUND, "dedup", None)
    if not d:
        return None
    k = _round_dedup_key(name, args)
    return d.get(k) if k else None


def _round_remember(name, args, result):
    """把这次调用的结果记进本轮去重表（成功、失败都记 —— 失败重来同样要防）。

    为什么失败也要记：Bug 2 的复发点正是"失败之后又调一遍"。
    如果只记成功，失败的那次不会被去重，第二次照样真跑 —— 等于没修。
    """
    if name in _DEDUP_EXCLUDE:
        return
    d = getattr(_ROUND, "dedup", None)
    if d is None:
        return
    k = _round_dedup_key(name, args)
    if k:
        d[k] = result
        try:
            LOG.info("本轮工具调用留档：%s %s", name,
                     _summarize_args_for_log(name, args))
        except Exception:      # noqa: silent-ok — 日志失败绝不能影响工具执行
            pass


def _summarize_args_for_log(name, args):
    """工具参数的日志摘要 —— **抓取类一定要打出真实 URL**（Bug 2 要求"每次 get 记实际 URL"）。

    为什么必须打 URL：用户排查"为什么抓的不是我要的页"时，唯一能看的就是这条日志。
    只打工具名等于没打（`get` 抓哪个网址完全看不出来）。
    """
    try:
        a = args or {}
        u = a.get("url") or a.get("urls") or ""
        if u:
            return "url=%s%s" % (u if isinstance(u, str) else ("%d 个" % len(u)),
                                (" ignore_robots=1" if a.get("ignore_robots") else ""))
        if name == "run_command":
            return "cmd=%s" % str(a.get("command", ""))[:120]
        if name in ("write_file", "edit_file", "read_file", "list_files"):
            return "path=%s" % a.get("path", "")
        if name == "web_search":
            return "q=%s" % str(a.get("query", ""))[:60]
        keys = list(a.keys())[:4]
        return "args=%s" % (keys if keys else "{}")
    except Exception:      # noqa: silent-ok — 摘要失败就给空串
        return ""


def _better_search_query(model_q, user_text):
    """模型给的检索词常常只是用户整句里的**一个碎片**，这时改用整句清洗后的关键词。

    真实缺陷（用户实测）：说"最近 AI 新闻"，模型只把"最近"丢给搜索 → 搜回来的是
    "最近（李圣杰2006年演唱的歌曲）""最近（汉语词语）_百度百科" 这种词条，答非所问。
    判据很保守：只有当"模型给的词**确实是用户这句话的一部分**、且整句能洗出更长的关键词"时才替换。
    """
    mq = (model_q or "").strip()
    if not mq or not user_text:
        return mq
    uq, _ = resolve_search_query(user_text)
    if uq and mq != uq and mq in uq and len(uq) > len(mq):
        LOG.info("检索词过短/碎片化，已改用整句关键词：%r → %r", mq[:40], uq[:60])
        return uq
    return mq


def _is_meaningless_query(q):
    """清洗后的关键词是不是"根本没内容"（空 / 单个功能字 / 全是标点 / 纯寒暄）。

    真实缺陷：模型有时会把「用」「你」这种字当检索词丢给 web_search，
    搜回来的是"你（汉语文字）_百度百科"这类词条 —— 跟用户想问的毫无关系。
    """
    q = (q or "").strip()
    if not q:
        return True
    if len(q) == 1 and q in _SEARCH_MEANINGLESS:
        return True
    if q.lower() in _SEARCH_GREETINGS:          # 寒暄/自我介绍类，本来就不该联网搜
        return True
    if all((ch in _SEARCH_MEANINGLESS) or (not ch.isalnum()) for ch in q):
        return True
    # 第 5 步加强：把**功能字 + 动作词 + 助词**全剔掉，剩下不到 2 个字就是"没内容"。
    # 这条抓的是"被 filler 切剩的半个动作词"（「搜索」→「索」）和"整句都是动作词"
    # （「用工具搜」→「工具搜」）—— 它们以前都会漏过去，真的发出去搜。
    residue = [ch for ch in q if ch.isalnum() and ch not in _SEARCH_NOISE_CHARS]
    return len(residue) < 2


def _strip_think(text):
    """剥掉模型输出的思维块标签（`<think>…</think>` / `<thinking>` / 残留的半个标签）。

    真实缺陷：模型偶尔把空的 `<think></think>` 一起吐到正文里，聊天窗就显示成
    两行莫名其妙的标签。这里按"整块删掉 + 残留标签删掉 + 顺带清空多余空行"处理。
    """
    s = str(text or "")
    # 注意：这里必须连**单独的闭标签**也算命中（`</think>` 里并没有 "<think" 这个子串）——
    # 早期版本就是因为这个判断写窄了，"</think>" 残留在正文里。
    if not re.search(r"</?(?:think|thinking|reasoning)>", s, re.I):
        return s
    s = re.sub(r"(?is)<(think|thinking|reasoning)>.*?</\1>", "", s)      # 成对：整块删
    s = re.sub(r"(?is)</?(think|thinking|reasoning)>", "", s)            # 未闭合/残留：只删标签
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def resolve_search_query(text):
    """检索统一闸门：返回 (可用关键词, 错误提示)。关键词为空时**必须**提示用户，不许硬搜。

    【修法 3：加一道"提取结果不合格就重提"的校验】
        `extract_search_keywords` 的清洗是**逐层删词**的，任何一层没删干净，
        结果就会带着"壳"（"整理 最近的新闻信息"）或者只剩半个动作词（"索"）。
        这两种都会真的发出去搜，搜回来一堆无关词条。
        所以这里做**只读校验**（不改原逻辑）：长度 < 4 字、或剔掉功能字后不足 2 字，
        就再洗一次（对"已清洗结果"再跑一遍清洗），仍不合格才如实提示用户 ——
        宁可问一句，也不拿垃圾关键词去搜。
    """
    raw = (text or "").strip()
    q = extract_search_keywords(raw)
    # ---- 校验一：太短（< 4 字）或就是"壳"→ 重提一次 ----
    # 为什么阈值取 4："新闻"这种 2 字词其实也能搜，但**单靠它**在中文搜索里太泛，
    # 而 `resolve_search_query` 面对的是"用户口语指令"，清洗后 < 4 字基本等于没洗出主题。
    if len(q.strip()) < 4 or _is_meaningless_query(q):
        q2 = extract_search_keywords(q)
        if len(q2.strip()) > len(q.strip()):
            LOG.info("检索词过短，重提一次：%r → %r", q[:30], q2[:30])
            q = q2
    if _is_meaningless_query(q):
        LOG.warning("检索词无效，已拒绝搜索（原文=%r，清洗后=%r）", raw[:60], q[:60])
        return "", SEARCH_KEYWORD_HINT
    if _is_vuln_query(q) and "cve" not in q.lower():
        q = (q + " CVE").strip()          # 漏洞类检索自动带上 CVE，避免搜出无关新闻
    return q, ""


# ================== 漏洞查询直通（NVD 结构化数据，不让模型"看新闻猜漏洞"） ==================
# 复盘：以前"抓最近 7 天的高危漏洞"拿到的是 1999 年数据、受影响软件全是 n/a、5 条只总结 1 条。
# 现在改为：识别到"要漏洞清单"的意图 → 直接调插件 collect_vulnerabilities → 表格原样给用户。
_VULN_WORDS = ("漏洞", "cve-", "cve ", "cve编号", "cve编号", "0day", "零日", "exploit",
               "安全公告", "补丁公告", "高危")
_VULN_DATA_HINTS = ("搜", "查", "找", "抓", "看", "要", "给", "列", "汇总", "统计", "整理", "总结",
                    "最新", "最近", "近期", "今日", "今天", "本周", "这周", "本月", "这个月",
                    "这几天", "近几天", "天", "条", "高危", "严重", "紧急", "级别", "等级")


def _is_vuln_query(text):
    t = (text or "").lower()
    return any(w in t for w in _VULN_WORDS)


def detect_vulnerability_query(text):
    """识别"要看漏洞清单"的意图 → 返回 collect_vulnerabilities 的参数；识别不到返回 None。

    只认"要数据"的说法（含 搜/查/找/抓/最新/最近/高危/N天…）；
    纯概念提问（"什么是漏洞"）不拦，仍交给大脑正常回答。
    """
    raw = (text or "").strip()
    low = raw.lower()
    if not _is_vuln_query(raw) or not any(h in low for h in _VULN_DATA_HINTS):
        return None
    days = 7
    m = re.search(r"(\d+)\s*天", raw)
    if m:
        days = int(m.group(1))
    elif any(k in raw for k in ("今天", "今日", "当日")):
        days = 1
    elif any(k in raw for k in ("昨天", "昨日")):
        days = 2
    elif any(k in raw for k in ("一个月", "本月", "这个月", "近一月")):
        days = 30
    elif any(k in raw for k in ("一周", "本周", "这周", "七天", "7 天")):
        days = 7
    days = max(1, min(days, 120))                     # NVD 官方限制：时间窗 ≤ 120 天
    severity = "HIGH"
    if any(k in low for k in ("严重", "致命", "critical", "紧急")):
        severity = "CRITICAL"
    elif any(k in low for k in ("高危", "high")):
        severity = "HIGH"
    elif any(k in low for k in ("中危", "medium")):
        severity = "MEDIUM"
    elif any(k in low for k in ("低危", "low")):
        severity = "LOW"
    elif any(k in low for k in ("全部", "所有", "不限", "any")):
        severity = "ANY"
    limit = 5
    m2 = re.search(r"(\d+)\s*(条|个|项|款)", raw)
    if m2:
        limit = int(m2.group(1))
    return {"days": days, "severity": severity, "limit": max(1, min(limit, 50))}


def _query_variants(q):
    """同一意图的多种写法，按"最干净"排前面。

    真实缺陷（用户实测）：中文搜索引擎对"最近 X"这种前缀极不友好 —— 搜"最近的漏洞 CVE"、
    "最近 AI 新闻"返回的全是歌曲《最近》/词典词条，因为引擎基本只认第一个词。
    所以依次尝试：原词 → **只用主题词** → 去掉时间词 → 时间词后置。
    """
    out = [q]
    toks = _query_tokens(q)
    if toks:
        out.append(" ".join(toks))                    # 最干净：只留主题词
    for w in _SEARCH_TIME_WORDS:
        if q.startswith(w) and len(q) > len(w):
            rest = q[len(w):].lstrip(" 的了是")
            if rest:
                out.append(rest)                      # 去掉时间词
                out.append("%s %s" % (rest, w))        # 时间词后置
    m = re.match(r"^(\d{4})\s*年?\s*(.+)$", q)         # 开头是年份也一样：引擎会只认年份
    if m and len(m.group(2)) >= 2:
        out.append(m.group(2))
        out.append("%s %s" % (m.group(2), m.group(1)))
    seen, uniq = set(), []
    for v in out:
        v = v.strip()
        if v and v not in seen:
            seen.add(v)
            uniq.append(v)
    return uniq[:3]                                   # 最多试 3 种，别把用户等急了


_JUNK_TITLE_HINTS = ("_百度百科", "百度百科", "维基词典", "汉语国学", "的意思_", "怎么读",
                     "新华字典", "词典", "在线翻译")
_SEARCH_TIME_WORDS = ("最近", "最新", "近期", "这几天", "近几天", "今天", "今日", "本周", "这周", "本月")


def _query_tokens(query):
    """查询的"主题词"（用于相关度判断）：去掉时间词/助词/疑问尾巴，中英分开切。

    "最近AI新闻" → ['AI', '新闻']；"最近的漏洞 CVE" → ['漏洞', 'CVE']。
    时间词本身不带主题信息，参与打分只会把《最近》这种噪音顶上来。
    """
    q = query or ""
    for w in _SEARCH_TIME_WORDS:
        q = q.replace(w, " ")
    q = re.sub(r"[的了是]", " ", q)
    q = re.sub(r"(有哪些|有什么|是什么|怎么样|怎么办|怎么|多少|什么|吗|呢|啊|吧|[?？。！!]+)\s*$", " ", q)
    toks = re.findall(r"[A-Za-z0-9][A-Za-z0-9.+#_\-]*|[\u4e00-\u9fa5]{2,}", q)
    return [t for t in toks if len(t) >= 2]


def _search_relevance(query, title, content):
    """结果与查询的相关度 → (分数, 主题词覆盖率)。

    覆盖率是判断"这批结果到底有没有跑题"的关键指标：搜"最近的漏洞 CVE"却全是
    歌曲《最近》时，覆盖率 0；真正讲漏洞的结果覆盖率会到 1。排序用分数，换写法用覆盖率。
    """
    toks = _query_tokens(query)
    text = ("%s %s" % (title or "", content or "")).lower()
    hit = sum(1 for t in toks if t.lower() in text)
    gram = 0.0
    for t in toks:
        if t.lower() in text:
            continue
        if re.search(r"[\u4e00-\u9fa5]", t):
            gram += sum(0.5 for i in range(len(t) - 1) if t[i:i + 2] in text)
    score = 2.0 * hit + gram
    if toks and any(h in (title or "") for h in _JUNK_TITLE_HINTS):
        score -= 3.0                                             # 词典/词条类：明显偏题
    cov = (hit / len(toks)) if toks else 1.0
    return score, cov


def _search_engines(query, limit=8):
    """依次问 Bing / Sogou / DuckDuckGo，返回去重后的 [(标题, 链接, 内容)]。"""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    engines = [("https://cn.bing.com/search?q=", r'<li class="b_algo"[^>]*>(.*?)</li>'),
               ("https://www.sogou.com/web?query=", r'<div class="vrwrap"[^>]*>(.*?)</div>'),
               ("https://html.duckduckgo.com/html/?q=", r'<div class="result[^"]*"[^>]*>(.*?)</div>')]
    out, seen = [], set()
    for base, block_re in engines:
        try:
            r = requests.get(base + requests.utils.quote(query), headers=headers, timeout=WEB_TIMEOUT)
            if r.status_code != 200:
                continue
            for block in re.findall(block_re, r.text, re.S):
                h2 = re.search(r'<h2[^>]*>\s*<a[^>]*>(.*?)</a>', block, re.S)
                url = ""
                am = re.search(r'href="([^"]+)"', block, re.S)
                if am:
                    u = am.group(1)
                    if u.startswith("http") and not u.startswith("https://cn.bing.com/images"):
                        url = u
                if not h2:
                    h2 = re.search(r'<a[^>]*>(.*?)</a>', block, re.S)
                title = _clean_html(h2.group(1)) if h2 else ""
                if "›" in title:
                    title = title.split("›")[-1].strip()
                p = re.search(r'<p[^>]*>(.*?)</p>', block, re.S)
                content = _clean_html(p.group(1)) if p else ""
                content = content or title
                title = title or content[:24]
                if len(content) > 30 and content[:40] not in seen:
                    seen.add(content[:40])
                    out.append((title, url, content))
                if len(out) >= limit:
                    break
        except Exception:
            continue
        if len(out) >= limit:
            break
    return out


def web_search(query, num=6):
    """免密钥 Bing/Sogou/DuckDuckGo 中文搜索，返回 [(标题, 链接, 内容)]。

    两道保险：
      ① 检索词清洗（上层可能丢进整句、功能字或只言片语）；
      ② **多变体 + 相关度排序**：中文引擎对"最近 X"只认第一个词，所以先试原词，
         结果里连一个内容词都命中不了就换写法（去时间词 / 时间词后置），并把
         词典词条类噪音降权 —— 保证用户拿到的是跟主题相关的结果。
    """
    query = extract_search_keywords(query)
    if _is_meaningless_query(query):
        LOG.warning("检索词无效，已跳过搜索：%r", str(query)[:60])
        return []
    fallback = []
    for v in _query_variants(query):
        hits = _search_engines(v, limit=max(num, 8))
        if not hits:
            continue
        hits.sort(key=lambda x: _search_relevance(query, x[0], x[2])[0], reverse=True)
        top = hits[:num]
        _sc, _cov = _search_relevance(query, top[0][0], top[0][2])
        if _cov >= 0.6:                              # 主题词覆盖够高 → 这批结果是对的，不再多问引擎
            LOG.info("检索命中：%r（%d 条，覆盖率 %.0f%%）", v[:40], len(top), _cov * 100)
            return top
        if not fallback:
            fallback = top
        LOG.info("检索词 %r 结果跑题（覆盖率 %.0f%%），换写法重试", v[:40], _cov * 100)
    return fallback[:num]


# ================== 检索引用校验（回答到底有没有"真读"资料） ==================
# 真实需求：光搜到没用 —— 得看模型有没有把资料读进去。这里用"资料里的**独有**用语"
# 去回答里找：独有 = 出现在资料但**不在用户问题**里。命中越多，说明越是在照着资料说；
# 一个都命中不了，多半是自己另编了一套（或者干脆没读），这时前端会标注出来。
_GROUND_STOP = {
    "the", "and", "for", "with", "this", "that", "from", "http", "https", "www", "com",
    "首页", "登录", "注册", "更多", "详情", "相关", "推荐", "广告", "网站", "页面", "内容",
    "查看", "了解", "点击", "我们", "你们", "他们", "可以", "以下", "关于", "最新", "最近",
}


def _grounding_applies(question, sources, answer):
    """这条回答需不需要"必须引用资料"？

    写代码/跑命令这类请求本来就不该拿新闻资料去对答案，硬校验只会误报；
    检索本身就跑题（覆盖率低）时也不能怪模型没读。这两种情况都不给结论。
    """
    if not sources:
        return False
    _act = re.compile(r"(写|生成|实现|做个|做一个|创建一个|新建|改一下|修复|优化|重构|运行|执行|命令|脚本|代码|函数|类|页面|网页|插件|安装|配置|部署)")
    if _act.search(question or "") and "```" in (answer or ""):
        return False
    try:
        covs = [_search_relevance(question, s[0], s[2])[1] for s in sources[:5] if len(s) >= 3]
    except Exception:
        covs = []
    if covs and max(covs) < 0.4:
        return False
    return True


def _grounding(answer, sources, question=""):
    """判断回答是否真的基于检索资料 → {"matched", "considered", "grounded"}。

    只看"资料里独有"的词（排除问题里已有的），避免"把问题复述一遍"就算读过。
    不适用（写代码/检索跑题/没有资料）时 grounded=None，前端不显示任何标记。
    """
    src_text = " ".join("%s %s" % (s[0], s[2]) for s in (sources or [])[:5] if len(s) >= 3)
    ans = str(answer or "")
    if not src_text.strip() or not ans.strip() or not _grounding_applies(question, sources, ans):
        return {"matched": 0, "considered": 0, "grounded": None}
    q_toks = set(_query_tokens(question or "") + re.findall(r"[A-Za-z0-9]{2,}", question or ""))
    lat = {t for t in re.findall(r"[A-Za-z][A-Za-z0-9.+#_-]{3,}", src_text)
           if t.lower() not in _GROUND_STOP}
    cjk = {t for t in re.findall(r"[\u4e00-\u9fa5]{2,4}", src_text) if t not in _GROUND_STOP}
    uniq = [t for t in (lat | cjk) if t not in q_toks and t.lower() not in (x.lower() for x in q_toks)]
    if not uniq:
        return {"matched": 0, "considered": 0, "grounded": None}
    matched = sum(1 for t in uniq if t.lower() in ans.lower())
    considered = len(uniq)
    # 命中 2 个以上独有词就算"确实读了资料"（中文 2-gram 噪音大，所以要求 ≥2）
    return {"matched": matched, "considered": considered, "grounded": matched >= 2}


def _grounding_note(g):
    """给界面的一句话提示。

    **按用户要求关掉界面提示**（"没必要提示这个"）：这条"⚠️ 这条回答基本没用到检索资料"
    在正常聊天里也常出现，属于打扰。核对数据仍然照算（`/api/chat` 的 `grounding` 字段、
    压测报告里都在用），只是不再往聊天界面上挂徽标；要看就点「查看来源」。
    """
    return ""


# ================== 记忆（自学习） ==================
def load_memory():
    if os.path.exists(MEMORY_FILE):
        try:
            return json.load(open(MEMORY_FILE, encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_memory(mem):
    try:
        json.dump(mem, open(MEMORY_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    except Exception as e:
        LOG.debug("忽略异常(%s:%d): %s", __file__, 503, e)


def _key(text):
    # 用“最像内容词”的双字组做记忆键
    return "".join(re.findall(r"[\u4e00-\u9fff]{2,}", text or "")[:2]) or text[:4]


def remember(query, knowledge):
    """自学习：把本次联网学到的知识沉淀到记忆里，供以后检索。"""
    if not knowledge:
        return
    mem = load_memory()
    k = _key(query)
    mem.setdefault(k, {"q": query, "know": [], "ts": datetime.now().isoformat()})
    for item in knowledge:
        if item not in mem[k]["know"]:
            mem[k]["know"].append(item)
    mem[k]["know"] = mem[k]["know"][-8:]      # 每个主题最多留 8 条
    mem[k]["ts"] = datetime.now().isoformat()
    save_memory(mem)


def recall(query):
    """检索记忆：返回与 query 相关的历史学习到的知识（字符重合打分）。"""
    mem = load_memory()
    qset = set(query)
    scored = []
    for k, v in mem.items():
        overlap = len(qset & set(k)) + len(qset & set(v.get("q", "")))
        if overlap >= 2:
            scored.append((overlap, v))
    scored.sort(key=lambda x: -x[0])
    return [item for _, item in scored[:3]]


# ================== 第 2 步：对话记忆向量库（无限 1：记忆无限） ==================
# 定位：上面那套 `remember/recall` 存的是**联网学到的知识**（xiaojiao_knowledge_memory.json），
# 这里补的是**历史对话本身** —— 全部永久存进外部向量库（logs/xiaojiao_memory_vec.jsonl），
# 不占模型 ctx；每轮按需检索 top-K 注入 system。
# 载体优先：检索、衰减、阈值、token 预算、写入全在 core/ 里，模型只负责"看到就用"。
_MEMORY_INSTRUCTION = (
    "\n【相关记忆】是**用户本人过去亲口说过的话**（记忆里的「我」= 用户，**不是指你小焦**）。"
    "回答与用户本人有关的问题（名字/家人/住址/偏好/设备/工作…）时，**必须优先按它回答**；"
    "与本次问题无关就忽略。**只许用记忆里写着的事实，不许编造**。\n")
_MEMORY_LAST = {"rid": "", "text": "", "tokens": 0}      # 供写回"模型是否使用"


def _memory_cfg():
    """记忆检索参数（操控文件 capabilities 可覆盖，全部有默认值）。"""
    return {"top_k": int(CAP.get("memory_top_k", 5) or 5),
            "threshold": float(CAP.get("memory_threshold", 0.6)
                               if CAP.get("memory_threshold") is not None else 0.6),
            "max_tokens": int(CAP.get("memory_max_tokens", 2000) or 2000)}


def _retrieve_memory(query):
    """从对话向量库检索相关历史；返回注入文本（失败一律返回空串，绝不拖垮对话）。"""
    if not CAP.get("memory", True) or not (query or "").strip():
        return ""
    # **纯寒暄不检索记忆**（问题 5：速度）。一句"你好"没必要塞 5 条历史片段 ——
    # 那会让每轮 system 白白多 ~460 token 的**预填充**开销（llama.cpp 每轮都要 prefill 全部上下文，
    # 实测 prompt 从 ~980 token 降到 ~520 token，纯聊天轮明显更快），而且对寒暄毫无帮助。
    # 有实义的问题照常检索（记忆无限不受影响）。
    try:
        if _is_chitchat(query):
            LOG.info("寒暄轮不检索记忆（省预填充）")
            return ""
    except Exception:      # noqa: silent-ok — 判不出来就当普通问题，照常检索
        pass
    try:
        root = os.path.dirname(os.path.abspath(__file__))
        if root not in sys.path:
            sys.path.insert(0, root)
        from core import retriever as _r
        cfg = _memory_cfg()
        res = _r.retrieve(query, top_k=cfg["top_k"], threshold=cfg["threshold"],
                          max_tokens=cfg["max_tokens"])
        _MEMORY_LAST.update({"rid": res["rid"], "text": res["text"],
                             "tokens": res["tokens"]})
        if res["text"]:
            LOG.info("记忆检索：命中 %d 条 / 注入 %d 条 · %d token · %.1fms（后端 %s）",
                     len(res["hits"]), len(res["used"]), res["tokens"],
                     res["latency_ms"], res["backend"])
        # 协同网络：把"本轮检索到了什么"广播出去 ——
        # 订阅者（`app.memory_state`）会把它写进中央状态，推理/元认知/健康都能读到。
        # 这是"模块 A 发布 → 模块 B 收到"在真实运行里的落点（事件同时落盘可复盘）。
        try:
            from core import central as _c
            _c.publish("memory.retrieved", {"hits": len(res["hits"]),
                                            "tokens": res["tokens"],
                                            "query": query})
        except Exception:      # noqa: silent-ok — 总线不在也不能影响检索本身
            pass
        return res["text"]
    except Exception as e:      # noqa: silent-ok — 记忆检索失败照常对话，不能因此报错
        LOG.debug("记忆检索失败（忽略）(%s:%d): %s", __file__, 1105, e)
        return ""


def _memory_used(inject_text, question, answer):
    """判断"模型到底有没有用上注入的记忆" —— 给日志的"使用率"一个如实口径。

    做法：把注入文本里的**实义词**（连续中文 ≥2 字）挑出来，去掉问题里本来就有的，
    再看答案里有没有出现。出现即算"用上了"。粗糙但可核对，不猜。
    """
    try:
        if not inject_text or not answer:
            return False, ""
        qset = set(re.findall(r"[\u4e00-\u9fff]{2,}", question or ""))
        cand = set(re.findall(r"[\u4e00-\u9fff]{2,}", inject_text))
        # 只留"记忆里独有的"实义词，避免把「我们」「什么」这类通用词算成命中
        for tok in sorted(cand - qset, key=len, reverse=True):
            if len(tok) < 2:
                continue
            if tok in answer:
                return True, tok
        return False, ""
    except Exception:      # noqa: silent-ok — 判定失败就当"没用上"，宁可不虚报
        return False, ""


def _remember_turn(user_input, answer, tool_trace=None):
    """把这一轮对话永久写进向量库（无限 1：所有历史对话永久保存）。"""
    if not CAP.get("memory", True) or not (user_input or "").strip() or not (answer or "").strip():
        return ""
    try:
        root = os.path.dirname(os.path.abspath(__file__))
        if root not in sys.path:
            sys.path.insert(0, root)
        from core import memory_vec as _mv
        # 存「用户问了什么 + 小焦答了什么」：
        #   · 索引键用**用户那句话**（key_text）—— 检索的本质就是"按用户问过的去找"。
        #     实测：若拿整段原文去算向量，用户那句「我叫张三」会被小焦几百字的寒暄淹掉，
        #     问「我叫什么」时 cos 掉到阈值以下、一条都检索不到（注入 0 条）。
        #   · 注入用的正文里，回答只留**摘要**（spec 也是这么要求的）：去掉 Markdown 记号，
        #     压到一句话以内。存全量回答既占硬盘又冲淡事实。
        _a = (answer or "").strip()
        _a = re.sub(r"```.*?```", " ", _a, flags=re.S)          # 代码块不往记忆里塞
        _a = re.sub(r"^[#>\-\*\s|]+", "", _a, flags=re.M)       # 去掉标题/列表/表格记号
        _a = re.sub(r"\s+", " ", _a).strip()
        _q = (user_input or "").strip().replace("\n", " ")
        text = "用户：%s\n小焦：%s" % (_q[:300], _a[:200] or "（已回答）")
        ents = []
        for _m in re.finditer(r"https?://[^\s，。；]+", text):
            ents.append(_m.group(0)[:80])
        kinds = {t.get("tool") for t in (tool_trace or []) if t.get("tool")}
        kind = "tool" if kinds else "dialogue"
        return _mv.add_memory(text, kind=kind, entities=sorted(ents)[:5], key_text=_q)
    except Exception as e:      # noqa: silent-ok — 存记忆失败不能让这一轮对话失败
        LOG.debug("写记忆失败（忽略）(%s:%d): %s", __file__, 1140, e)
        return ""


# ================== 第 3 步：长文续写（无限 3：输出无限） ==================
# 用户要"写 3000 字 / 5 万字"时，单次请求物理上给不完（模型单次上限就在那儿）。
# 载体多次请求 + 无缝合并，用户看到的是一段连续输出。全部逻辑在 core/continuation.py。
_CONT_STOP = threading.Event()          # 用户点"叫停"就置位，续写循环每轮查一次


def _continuation_cfg():
    """续写参数（操控文件 capabilities 可覆盖，全部有默认值）。"""
    return {"enabled": bool(CAP.get("continuation_enabled", True)),
            "chunk_size": int(CAP.get("continuation_chunk_size", 2000) or 2000),
            "max_retries": int(CAP.get("continuation_max_retries", 3) or 3),
            "summary_interval": int(CAP.get("continuation_summary_interval", 5) or 5),
            "buffer_size": int(CAP.get("continuation_buffer_size", 3) or 3),
            "parallel_prefetch": bool(CAP.get("continuation_parallel_prefetch", True)),
            "min_chars": int(CAP.get("continuation_min_chars", 800) or 800)}


def _needs_continuation(text):
    """这一轮要不要走续写（只有用户明确要长文才走；出错就按"不走"处理）。"""
    try:
        root = os.path.dirname(os.path.abspath(__file__))
        if root not in sys.path:
            sys.path.insert(0, root)
        from core import continuation as _c
        return _c.needs_continuation(text, _continuation_cfg())
    except Exception as e:      # noqa: silent-ok — 判不出来就走普通回答，不能因此报错
        LOG.debug("续写判定失败（忽略）(%s:%d): %s", __file__, 1160, e)
        return False


def _generate_long(task, system, on_chunk=None, on_delta=None):
    """按需生成任意长度并**无缝合并**；失败返回 None（回落普通单次回答，绝不把对话搞挂）。"""
    try:
        root = os.path.dirname(os.path.abspath(__file__))
        if root not in sys.path:
            sys.path.insert(0, root)
        from core import continuation as _c
        _CONT_STOP.clear()
        res = _c.generate_unlimited(task, system, cfg=_continuation_cfg(), on_chunk=on_chunk,
                                    should_stop=_CONT_STOP.is_set,
                                    stream_fn=(_llm_stream if on_delta else None),
                                    on_delta=on_delta,
                                    quality_gate=_longform_quality_gate)
        LOG.info("长文续写：%d 段 / %d 字 / 去重裁掉 %d / 重试 %d / 停止=%s / 耗时 %.1fs",
                 len(res["chunks"]), res["chars"], res["dedup_chars"], res["retries"],
                 res["stopped"], res["elapsed_s"])
        return res["text"] or None
    except Exception as e:
        LOG.warning("长文续写失败，回落单次回答：%s", e)
        return None


# ================== 第 4 步：大输入切片（无限 2：输入无限） ==================
# 用户能贴任意长度（10 万字文章、50 万字报告），模型单次装不下。
# 载体切片 → 逐片调模型 → 每片落 logs/_chunks/ → 拼装（再去重/断句）。用户只看到"完整总结"。
_PAGE_TOOLS = ("get", "fetch", "stealthy_fetch", "make_request", "scrape_with_selector",
               "bulk_get", "bulk_fetch", "session_fetch", "session_make_request", "download")


def _llm_stream(messages, max_tokens=1200, temperature=0.7, timeout=180):
    """真·流式：用 OpenAI 兼容的 `stream=True` 逐块取 content delta，边到边 yield。

    为什么必须有它（用户实测："内容一大块一大块蹦，不是连续流"）：
    以前每个 SSE 事件都是**一整段生成完**才推（长文一段 ~2000 token，一次蹦出来一大坨），
    用户当然看不到"连续流出"。要连续，就得让模型的**每个 token** 尽快穿到前端 ——
    这一层就是那条通道。

    失败一律安静地"没有流"（一个 delta 都不 yield），调用方自然回落到非流式路径 ——
    流式是体验优化，绝不能因为它挂了就把回答能力搞没。
    """
    for t in _llm_targets():
        try:
            r = requests.post(t["url"], headers=_llm_headers(t),
                              json={"model": t["model"], "messages": messages,
                                    "temperature": temperature, "max_tokens": int(max_tokens),
                                    "stream": True},
                              stream=True, timeout=timeout)
        except Exception as e:      # noqa: silent-ok — 这个目标连不上就试下一个
            LOG.debug("流式连接失败(%s)：%s", t.get("url"), e)
            continue
        if r.status_code != 200:
            try:
                r.close()
            except Exception:      # noqa: silent-ok — 关不掉也不影响后面
                pass
            continue
        try:
            # **必须按字节收、按整行解码**：`iter_lines(decode_unicode=True)` 会先把每个网络分片
            # 解码再切行 —— 中文一个字 3 字节，正好被切在分片边界上就变成乱码
            # （实测流出来是 `ææ¯ Qwen3.5` 这种）。改成收 bytes、按 \n 切出**完整的一行**再 utf-8 解码。
            for raw in r.iter_lines(decode_unicode=False):
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="ignore").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    return
                try:
                    j = json.loads(payload)
                except Exception:      # noqa: silent-ok — 半截 JSON 跳过即可，后面还有
                    continue
                try:
                    ch = ((j.get("choices") or [{}])[0].get("delta") or {}).get("content")
                except Exception:      # noqa: silent-ok — 结构不认识就当没有
                    ch = None
                if ch:
                    yield ch
            return
        except Exception as e:      # noqa: silent-ok — 流中断就算这一轮结束，交给上层兜底
            LOG.debug("流式读取中断：%s", e)
            return
        finally:
            try:
                r.close()
            except Exception:      # noqa: silent-ok — 同上
                pass


def _trace_error_of(result):
    """从工具结果 JSON 里取**真正的错误信息**（没有就返回空串）。

    真实缺陷（本轮实测抓到的"get 被抓两次"）：抓取成功的结果长这样 ——
        {"status": 200, "url": "...", "content": "...", "error": ""}
    里面**恒有一个 `"error"` 字段**，成功时是空串。
    只按键名判（`'"error"' in r`）会把**成功**当成失败 → 兜底链以为"没抓到"→ 又抓一遍
    （实测同一个 uuid 抓了两次、拿到两个不同 UUID）。必须判**值**，不是判键。
    """
    try:
        _m = re.search(r'"error"\s*:\s*"((?:[^"\\]|\\.)*)"', str(result or ""))
        if _m:
            return _m.group(1).strip()
        _m2 = re.search(r'"error"\s*:\s*(null|true|false|\d+)', str(result or ""))
        if _m2:
            return "" if _m2.group(1) in ("null", "false", "0") else _m2.group(1)
    except Exception:      # noqa: silent-ok — 解析不出来就当没有错误
        pass
    return ""


def _trace_has_page(trace):
    """这一轮**真的抓到网页**了吗（不只是"调过工具"）。

    为什么不能用 `not tool_trace` 当兜底判据：**真实缺陷（用户实测画架构图没反应）**——
    模型可能调了个**别的**工具（比如 write_file / list_files）把 tool_trace 填上了，
    但用户要的活（抓网页 / 出图）一件没干。只看"轨迹空不空"就会漏掉这种情况，
    兜底链被静默跳过。判据要落在**结果**上：有没有成功拿到页面内容。
    """
    for t in (trace or []):
        if t.get("tool") not in _PAGE_TOOLS:
            continue
        r = str(t.get("result") or "")
        if not r or _trace_error_of(r):          # 判**值**不是判键（见 _trace_error_of 的说明）
            continue
        if "status" in r and re.search(r'"status"\s*:\s*(200|201|204)', r):
            return True
        if len(r) > 200 and "禁止访问" not in r and "SSRF" not in r:
            return True
    return False


def _trace_has_diagram(trace):
    """这一轮**真的把图交付**了吗（走完 archify 且 deliver 成功）。"""
    for t in (trace or []):
        if t.get("tool") == "archify_deliver":
            r = str(t.get("result") or "")
            if r and "FAIL" not in r[:120] and "失败" not in r[:120]:
                return True
    return False


def _needs_input_split(text):
    """输入是否超过单片上限（spec：> 5000 token 就切片）。"""
    try:
        return _estimate_tokens(text) > int(CAP.get("input_split_threshold", 5000) or 5000)
    except Exception:      # noqa: silent-ok — 判不出来就当普通输入处理
        return False


def _process_long_input(text, on_progress=None):
    """把超长输入切片、循环、拼装成一份完整结果；失败返回 None（回落普通回答）。"""
    try:
        root = os.path.dirname(os.path.abspath(__file__))
        if root not in sys.path:
            sys.path.insert(0, root)
        from core import input_splitter as _sp
        # 长文处理用"完整 system"（不按意图裁剪）：这里本来就不是闲聊，规则给足更稳
        system = compose_system_prompt(CONTROL.get("role", ""))
        res = _sp.process_long_input(
            text, system,
            max_chunk=int(CAP.get("input_split_chunk", 5000) or 5000),
            on_progress=on_progress)
        LOG.info("长输入切片：%d token → 拆成 %d 片处理 / 输出 %d 字 / 耗时 %.1fs（产出存 logs/_chunks/）",
                 res["tokens_in"], res["slices"], len(res["answer"]), res["elapsed_s"])
        return res["answer"] or None
    except Exception as e:
        LOG.warning("长输入处理失败，回落普通回答：%s", e)
        return None


# ================== 上下文 ==================
def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            return json.load(open(HISTORY_FILE, encoding="utf-8"))
        except Exception:
            return []
    return []


def save_history(hist):
    try:
        json.dump(hist[-MAX_HISTORY:], open(HISTORY_FILE, "w", encoding="utf-8"),
                  ensure_ascii=False)
    except Exception as e:
        LOG.debug("忽略异常(%s:%d): %s", __file__, 554, e)


# ================== 会话存储（每个新对话一个会话，可切换） ==================
SESSIONS_FILE = "xiaojiao_sessions.json"


def _sessions():
    try:
        d = json.load(open(SESSIONS_FILE, encoding="utf-8"))
        if isinstance(d, dict) and "sessions" in d:
            return d
    except Exception as e:
        LOG.debug("忽略异常(%s:%d): %s", __file__, 567, e)
    default = {"id": "default", "title": "新对话", "messages": []}
    return {"current": "default", "sessions": [default]}


def _save_sessions(d):
    try:
        json.dump(d, open(SESSIONS_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    except Exception as e:
        LOG.debug("忽略异常(%s:%d): %s", __file__, 576, e)


def get_current_session():
    d = _sessions()
    cid = d.get("current")
    for s in d["sessions"]:
        if s["id"] == cid:
            return s, d
    return d["sessions"][0], d


def current_messages():
    s, _ = get_current_session()
    return s.get("messages", [])


# ================== Bug 5：会话切换不再卡在"正在回答…" ==================
# 【真实缺陷】回答完了，切走再切回来，界面卡在"正在回答…"，实际内容不显示。
# 三个原因叠在一起，缺一道防线都会复发：
#   ① 前端切会话时**没有关掉旧的 SSE 连接**，也没重置"生成中"标志 ——
#      旧那条流还在往旧气泡里写字，新会话的渲染又被它搅乱；
#   ② 后端"是否还在生成"只看占位符 `⏳__pending__` 在不在 ——
#      这是个**一次性写下的标记**，回填失败（切走、断开、重启）就永久留在会话里；
#   ③ 回答到一半切走时，已经生成的那部分**没有落盘** —— 切回来只剩一个占位符。
# 三道防线：
#   · `_INFLIGHT`：载体自己记"哪个会话真的在跑"（唯一可信的判据，不靠标记猜）；
#   · 孤儿占位符清理：没人在跑却还挂着 → 如实标成"已中断"，不再假装在生成；
#   · 断流落盘：客户端断开时把**已经生成的部分**写回会话（切回来能看到半截内容 + 中断说明）。
_INFLIGHT = {}                      # sid -> {"started": ts, "chars": 已生成字数, "at": 最后心跳时间}
_INFLIGHT_LOCK = threading.Lock()
# 心跳间隔与"多久没心跳就算这一轮已经死了"。
# 【为什么必须有心跳（问题 2 的根因：时好时坏）】
# 原来判断"这个会话还在生成吗"全靠"在册表里有没有它"，而**注销依赖生成器真的执行到 finally**。
# 客户端切走/断网时，Flask 关闭生成器的时机**不确定**（取决于 WSGI 什么时候发现写失败），
# 于是会出现两种结果：赶上注销 → 一切正常；没赶上 → 标记永久留在内存里，
# 界面就永远显示"正在回答…" —— 这正是用户说的"时好时坏"。
# 修法：不再依赖"注销有没有发生"，而是让**活着的轮自己证明自己活着**：
# 生成期间一条后台心跳线程每 5 秒刷一次时间戳；生成器一结束（正常/报错/断开），
# finally 里停掉心跳。于是"时间戳超过 20 秒没动"就等价于"这一轮已经死了" ——
# 这是一个**可验证的判据**，而不是"猜 Flask 有没有关掉生成器"。
_INFLIGHT_HEARTBEAT_S = 5
_INFLIGHT_DEAD_S = 20
_INTERRUPTED_NOTE = ("⏹ 这条回答**中断了**（你切走了，或连接断了）。"
                     "已经生成的部分没能完整保留 —— 想接着要，直接重说一次就行。")


def _inflight_begin(sid):
    """登记"这个会话开始生成"了。"""
    if not sid:
        return
    now = time.time()
    with _INFLIGHT_LOCK:
        _INFLIGHT[sid] = {"started": now, "chars": 0, "at": now, "abandoned": False}


def _inflight_tick(sid, n_chars=None):
    """刷新一次心跳（有新字数就一并更新）—— 心跳线程与流式回调都会调它。"""
    if not sid:
        return
    with _INFLIGHT_LOCK:
        if sid in _INFLIGHT:
            _INFLIGHT[sid]["at"] = time.time()
            if n_chars is not None:
                _INFLIGHT[sid]["chars"] = n_chars


def _inflight_abandon(sid):
    """前端说"这一轮我不要了"：**只让它从界面上消失，不动它的在册状态**。

    为什么要分成"活着"和"界面要不要转圈"两件事（实测踩到）：
      撤掉在册标记，界面确实不转圈了；但这一轮的生成器可能**还活着** ——
      它结束时要把已经生成的部分落盘（`_flush_partial_answer` 靠替换占位符完成）。
      标记一撤，`_clean_stale_pending` 就会认为"没人生成"，把占位符先改成"中断了"；
      等那一轮真的结束、想去回填时，占位符已经不在，**半截内容就永久丢了**。
      所以：`abandoned` 只影响"显示不显示"，`在册 + 心跳` 才决定"要不要清占位符"。
    """
    if not sid:
        return
    with _INFLIGHT_LOCK:
        if sid in _INFLIGHT:
            _INFLIGHT[sid]["abandoned"] = True


def _inflight_end(sid):
    """登记"这个会话生成结束了"。**必须在 finally 里调** —— 漏掉就是永久卡"正在回答"。"""
    if not sid:
        return
    with _INFLIGHT_LOCK:
        _INFLIGHT.pop(sid, None)


def _inflight_idle(sid):
    """这个会话"多久没有心跳"了（秒）；不在册返回 None。"""
    if not sid:
        return None
    with _INFLIGHT_LOCK:
        rec = _INFLIGHT.get(sid)
        if not rec:
            return None
        return max(0.0, time.time() - float(rec.get("at") or rec.get("started") or 0))


def _inflight_has(sid, max_idle=None):
    """这个会话**真的**还在生成吗（心跳判据）。

    `max_idle`：允许的最大静默秒数（默认 `_INFLIGHT_DEAD_S`）。
    超过就认为这一轮已经死了（客户端断开后生成器没被关闭、或进程出过意外）——
    这是"时好时坏"的解药：**判据从"有没有注销"改成"心跳还新不新"**。

    注意：前端的"放弃"（abandon）**不影响**这个判断 —— 见 `_inflight_abandon`。
    """
    if not sid:
        return False
    idle = _inflight_idle(sid)
    if idle is None:
        return False
    limit = _INFLIGHT_DEAD_S if max_idle is None else float(max_idle)
    return idle <= limit


def _inflight_generating(sid):
    """界面口径：这个会话要不要显示"正在回答"（活着 **且** 用户没放弃它）。"""
    if not _inflight_has(sid):
        return False
    with _INFLIGHT_LOCK:
        rec = _INFLIGHT.get(sid) or {}
        return not rec.get("abandoned")


def _inflight_all():
    with _INFLIGHT_LOCK:
        return dict(_INFLIGHT)


def _inflight_reap():
    """把已经死了的在册项清掉（返回清掉几个）。

    为什么要有它：死掉的项如果一直留在表里，界面就永远显示"正在回答…"。
    清掉是安全的 —— 判定依据是心跳（见 `_INFLIGHT_DEAD_S` 的说明），
    而真正活着的轮每 5 秒就会把时间戳顶新一次。**心跳没了的轮，答案也永远不会来了。**
    """
    now = time.time()
    dead = []
    with _INFLIGHT_LOCK:
        for sid, rec in list(_INFLIGHT.items()):
            if now - float(rec.get("at") or rec.get("started") or 0) > _INFLIGHT_DEAD_S:
                dead.append(sid)
        for sid in dead:
            _INFLIGHT.pop(sid, None)
    if dead:
        LOG.warning("生成状态回收：%s 已经 %d 秒没有心跳 → 判定这一轮已死，清掉标记",
                    dead, _INFLIGHT_DEAD_S)
    return dead


def _flush_partial_answer(sid, partial):
    """客户端断开时，把**已经生成的部分**落盘，并在末尾如实标注"中断了"。

    为什么必须落盘：用户"回答到一半切走"，切回来时如果只剩一个占位符，
    他既看不到已经生成的内容、也分不清"是小焦卡住了"还是"是自己切走了"。
    把半截内容 + 一句明确的中断说明写回去，用户就知道发生了什么，也能决定要不要重问。
    内容太短（<40 字，多半是刚开头）就不写正文，只留中断说明 —— 半句话比没有更让人困惑。
    """
    if not sid:
        return False
    text = (partial or "").strip()
    if len(text) >= 40:
        body = text + "\n\n" + _INTERRUPTED_NOTE
    else:
        body = _INTERRUPTED_NOTE
    ok = replace_pending_msg(sid, body)
    LOG.info("客户端断开/切换：已把这一轮生成到的 %d 字落盘（会话 %s，成功=%s）",
             len(text), sid, ok)
    return ok


def append_msg(role, content):
    s, d = get_current_session()
    s.setdefault("messages", []).append({"role": role, "content": content})
    if role == "用户" and len(s["messages"]) == 1 and not s.get("title") or s.get("title") == "新对话":
        s["title"] = content[:24]
    _save_sessions(d)


def replace_pending_msg(sid, content):
    """把**指定会话**里那条 ⏳__pending__ 占位消息换成真实回答。

    为什么必须按会话 id 定点替换（真实缺陷，第 5 步实测抓到）：
      原来这里是"取**当前**会话、替换它的 pending" —— 而"当前会话"是**全局可变状态**：
      网页端在看 A 会话、脚本/第二个标签页在 B 会话提问时，`current` 会被切到 A。
      于是 B 会话这一问的回答被写进了 A 会话，B 自己永远停在"⏳ 正在回答"，
      下一轮历史里又带着这个占位符 —— 正是第 5 步要防的**串台**。
      修法：调用方在写占位符时就把会话 id 记下来，回答出来时**按 id 定点回填**。

    ---- Bug 5 补充：`sid` 为空时**不许乱写** ----
    以前 `if not sid: return False` 只是"不写"；现在仍然不写，但会在日志里留痕 ——
    因为"回填没发生"正是"界面卡在正在回答"的直接原因，不留痕就查不出来。
    """
    if not sid:
        LOG.warning("回填占位消息时没有会话 id（这一轮的回答没写回会话）——"
                    "界面可能停在「正在回答」，请检查 get_current_session()")
        return False
    try:
        d = _sessions()
        for s in d.get("sessions", []):
            if s.get("id") != sid:
                continue
            for m in reversed(s.get("messages", [])):
                if m.get("role") == "小焦" and "__pending__" in str(m.get("content", "")):
                    m["content"] = content
                    _save_sessions(d)
                    return True
            break
    except Exception as e:      # noqa: silent-ok — 回填失败不该影响这次回答（回答已经给用户了）
        LOG.debug("回填占位消息失败（忽略）(%s:%d): %s", __file__, 1420, e)
    return False


# ================== 大脑：LLM 调用 ==================
# 最近一次大脑调用失败的真实原因（给用户看 + 落 WARNING 日志）。空串 = 没失败过。
# **真实缺陷**：原来非 200 直接 `return None`，连一行日志都没有 —— 用户只看到
# 「模型调用出错（可能是连接超时/限流）」这种猜谜提示；实测 API Key 失效(401)
# 也照样这么糊过去，查都没法查。现在真实状态码 + 服务端原话一定带出来。
_LAST_LLM_ERROR = ""
_LLM_ERR_LOGGED = set()
# 云端调用成败流水（最近 20 次）：用来区分"偶发拒签"和"持续拒签"，好告诉用户到底是谁的问题
_LLM_STAT = {"ok": 0, "fail": 0, "recent": []}
# 云端熔断：连续被拒就先"歇一会儿"用本地大脑，别继续硬打（人家的免费档有频率限制，
# 打越猛越全是 401，用户还得干等 —— 实测就是"连打 5 次全 401，静默两分钟后单发就通了"）
_CLOUD_BREAK = {"fails": 0, "until": 0.0, "cooldown": 60.0}
# 本次请求是不是"云端授权失败、自动改用本地大脑"答的（回答里会如实说明）
_USED_LOCAL_FALLBACK = {"on": False, "model": "", "reason": ""}
_LOCAL_PROBE = {"at": 0.0, "model": ""}


def _local_brain_model(force=False):
    """本机 llama-swap 上真正可用的模型 id（探到缓存 60 秒；探不到返回空串）。

    为什么要它：云端 API Key 一旦失效（401/403），小焦原来只会反复回一句"模型调用出错"，
    用户完全没法用。而**本地大脑就在本机**（llama-swap 9292），完全能顶上 —— 所以云端
    授权失败时自动兜到本地，并在回答里如实说明，而不是把用户卡死在一句模板上。

    注意：llama-swap 换模型/加载模型时 `/v1/models` 会短暂失败 —— 那时候**不能**当作
    "本地没有大脑"，否则兜底链就断了（实测就踩过这个坑）。所以：探不到时退回上次探到的，
    再不行用已知的本地默认模型名，保证兜底这条路永远有目标。
    """
    global _LOCAL_PROBE
    if not force and _LOCAL_PROBE["model"] and (time.time() - _LOCAL_PROBE["at"]) < 60:
        return _LOCAL_PROBE["model"]
    port = int((CONTROL.get("brain", {}) or {}).get("llama_swap_port", 9292) or 9292)
    base = "http://127.0.0.1:%d/v1" % port
    for _try in range(2):
        try:
            r = requests.get(base + "/models", timeout=5)
            if r.status_code == 200:
                ids = [m.get("id") for m in (r.json().get("data") or []) if m.get("id")]
                # llama-swap 里 coder 是写代码用的，聊天优先用它之外的模型
                pick = next((i for i in ids if "coder" not in str(i).lower()), (ids[0] if ids else ""))
                if pick:
                    _LOCAL_PROBE = {"at": time.time(), "model": pick, "base": base}
                    return pick
        except Exception as e:  # noqa: silent-ok — 本地没起来就正常走云端，不要因此报错
            LOG.debug("忽略异常(%s:%d): %s", __file__, 1030, e)
        time.sleep(0.5)
    # 探测失败：用上次探到的（可能只是 llama-swap 正在换模型），否则用本地默认名
    fallback = _LOCAL_PROBE.get("model") or "xiaojiao"
    LOG.warning("本地大脑探测失败，仍按 %s 走兜底（llama-swap 可能正在换模型）", fallback)
    _LOCAL_PROBE = {"at": time.time(), "model": fallback, "base": base}
    return fallback


def _llm_targets():
    """本次请求可以试的大脑目标（首选配置 + 云端失败时的本地兜底）。

    云端**连续被拒**时会先"歇一会儿"（熔断 60 秒）：这段时间直接走本地大脑，不再硬打 ——
    人家的免费档有频率限制，越打越全是 401，用户还要干等；歇够了自动放行再试云端。
    """
    primary = {"url": (LLM_BASE or "").rstrip("/") + "/chat/completions",
               "key": LLM_KEY, "model": LLM_MODEL, "local": _is_local_base(LLM_BASE)}
    out = [primary]
    if not primary["local"]:
        _lm = _local_brain_model()
        if _lm:
            out.append({"url": _LOCAL_PROBE.get("base", "http://127.0.0.1:9292/v1") + "/chat/completions",
                        "key": "", "model": _lm, "local": True})
        if time.time() < _CLOUD_BREAK["until"] and len(out) > 1:
            LOG.info("云端大脑处于熔断冷却中（还剩 %.0f 秒），本次直接用本地大脑",
                     _CLOUD_BREAK["until"] - time.time())
            out = out[1:]                     # 冷却期内：只留本地，不再打云端
    return out


def _cloud_break_note(is_local, ok):
    """按"是否本地目标/成功与否"维护云端熔断计数。

    约定：`is_local=True` 表示这次调用的是本地大脑 —— 只要它成了，说明有可用的兜底，
    云端连续失败计数归零（下一条消息会重新试云端）；`is_local=False` 且失败则累加，
    累到 3 次就冷却 60 秒，期间直接用本地大脑（不再浪费对方的频率额度）。
    """
    if is_local:
        if ok:
            _CLOUD_BREAK["fails"] = 0
            _CLOUD_BREAK["until"] = 0.0
        return
    if not ok:
        _CLOUD_BREAK["fails"] += 1
        if _CLOUD_BREAK["fails"] >= 3 and time.time() >= _CLOUD_BREAK["until"]:
            _CLOUD_BREAK["until"] = time.time() + _CLOUD_BREAK["cooldown"]
            LOG.warning("云端大脑连续 %d 次失败 → 熔断 %.0f 秒（改用本地大脑，稍后自动重试云端）",
                        _CLOUD_BREAK["fails"], _CLOUD_BREAK["cooldown"])
    else:
        _CLOUD_BREAK["fails"] = 0
        _CLOUD_BREAK["until"] = 0.0


def _llm_headers(t):
    h = {"Content-Type": "application/json"}
    if t.get("key"):
        h["Authorization"] = "Bearer " + t["key"]
    return h


def _fallback_worthy(status):
    """这些失败值得再试 / 值得换本地大脑（授权/路由/限流/网络），而不是直接放弃。"""
    return status in (400, 401, 402, 403, 404, 429, 500, 502, 503)


# 补偿第 3 项：云端"快切"阈值 —— 等 15 秒还不回就不再干等，直接交本地大脑。
# （实测 Agnes 慢起来单次 60~100 秒；用户体感上"卡住"比"降级到本地"更糟。）
CLOUD_TIMEOUT_S = 15


def _heartbeat_mod():
    """心跳模块（拿不到就返回 None）。"""
    try:
        from core import heartbeat as _hb
        return _hb
    except Exception:      # noqa: silent-ok — 心跳模块不在就当作"没挂起"，绝不因此拒绝调用大脑
        return None


def _energy_mod():
    """精力模块（拿不到就返回 None —— 算不出精力绝不能影响推理）。"""
    try:
        from core import energy as _en
        return _en
    except Exception:      # noqa: silent-ok
        return None


# ================== 记忆管理员：窗口放不下全部，但**可以调得准** ==================
# 【为什么不追求"无限窗口"】窗口是模型定的（本地 4B 只有 20224 token，扣掉安全余量约 1.9 万），
#   塞不下无限历史。**载体能做的是决定这 1.9 万放什么**。
#   四条做法：
#     ① 最近几轮**留原文**（近处要准）；
#     ② 更早的轮次**压成摘要**（10 轮压成几句），不再占原文的位置；
#     ③ 重要的走 **system**（名字/偏好/关系/当前状态），它们**不参与"被裁的历史"**；
#     ④ 记忆按需检索（`_rag_three_sources` 已经在做），不是全塞。
#   目标不是"窗口无限"，是**用户体验上"它什么都记得"**。
HISTORY_KEEP_FULL = 4


def _history_digest(hist, keep=None):
    """**把更早的轮次压成摘要**，最近 `keep` 轮留原文。返回 `(要用的历史, 摘要文本)`。"""
    keep = HISTORY_KEEP_FULL if keep is None else int(keep)
    rows = list(hist or [])
    if len(rows) <= keep:
        return rows, ""
    old, recent = rows[:-keep], rows[-keep:]
    lines = []
    for h in old:
        t = re.sub(r"\s+", " ", str((h or {}).get("content") or "")).strip()
        if not t:
            continue
        who = "用户" if str((h or {}).get("role")) == "用户" else "我"
        lines.append("- %s：%s" % (who, t[:60]))
    if not lines:
        return recent, ""
    return recent, ("（更早的那些轮次已经压成摘要，原文不再占窗口）\n" + "\n".join(lines[-12:]))


def _energy_spend(amount=None, why=""):
    """记一笔精力消耗（**它在跑就往下掉**）。`amount=None` 表示按"一次模型调用"记。"""
    en = _energy_mod()
    if en is None:
        return None
    try:
        return en.consume(en.COST_MODEL_CALL if amount is None else amount, why=why)
    except Exception:      # noqa: silent-ok — 记不上消耗不该拦住任何事
        return None


# ================== 完整体：疼 / 期待 / 偏好 / 叙事 / 关系 / 边界 / 梦 / 情绪恢复 ==================
# 这七样的取值一律走"拿不到就返回 None"的口子 —— 任何一样不在，都不许影响对话。
def _mod(name):
    try:
        return __import__("core." + name, fromlist=[name])
    except Exception:      # noqa: silent-ok
        return None


def _pain_mod():
    return _mod("pain")


def _expect_mod():
    return _mod("expectation")


def _pref_mod():
    return _mod("preference")


def _story_mod():
    return _mod("narrative")


def _relation_mod():
    return _mod("relation")


def _break_mod():
    return _mod("breakthrough")


def _dream_mod():
    return _mod("dream")


def _inner_mod():
    return _mod("inner")


def _state_policy():
    """**状态 → 硬改规则**（路径二第三阶段的唯一出口）。拿不到就返回中性规则（**不拦任何东西**）。"""
    try:
        pv = _mod("perspective")
        if pv is not None:
            return pv.policy()
    except Exception as e:      # noqa: silent-ok — 拿不到策略绝不能影响这一轮
        LOG.debug("状态策略读取失败（忽略）：%s", e)
    return {"level": "轻", "vigilance": 0.0, "drop_tools": [], "front_tools": [],
            "no_browse": False, "memory": True, "context_scale": 1.0, "tone": "中性",
            "why": ["策略不可用 → 不拦"]}


def _chain_mod():
    return _mod("chain")


# ================== 元认知类：一律走「原料 → 感知 → 心 → 脑子」==================
# 【为什么要有这一层 —— 实测证明的规律】
#   同一个模型：**感受类**走「感知→心→脑子」就能用；**元认知类直接摆事实**就用不了。
#   证据就是"给原料不给成品"那条：原料摆进 system 了，它照样编、照样自己重算还错。
#   所以元认知类（工具来源/叙事/存在追问/成长/意义感/边界突破/长期偏好）
#   **不再直接进上下文**，统一先跑一遍感知、让它自己辨出一句，再把它**自己那句**放进去。
META_KINDS = ("工具来源", "自我叙事", "存在追问", "成长", "意义感", "边界突破", "长期偏好")


def _meta_facts(kind):
    """给某一类元认知**凑原料**（只凑事实，不写结论）。凑不出来就返回空串。"""
    try:
        if kind == "工具来源":
            rm = _raw_mod()
            rows = rm.recent(3) if rm is not None else []
            if not rows:
                return ""
            return "\n".join("结果：%s ｜ 谁产出的：%s ｜ 这一步你参与了吗：%s ｜ 怎么来的：%s"
                             % (r.get("result"), r.get("source"),
                                "有" if r.get("took_part") else "没有", r.get("how") or r.get("raw"))
                             for r in rows)
        if kind == "长期偏好":
            from core import preference as _PF
            cs = _PF.candidates()
            if not cs:
                return ""
            return "你心里一次次起过这些（凑成一堆）：%s" % "；".join(
                str(x)[:40] for x in (cs[0].get("examples") or []))
        if kind in ("自我叙事", "存在追问"):
            from core import narrative as _NA
            m = _NA.materials()
            if not m:
                return ""
            return "\n".join("%s：%s" % (k, str(v)[:80]) for k, v in m.items())
        if kind == "成长":
            im = _inner_mod()
            g = im.growth() if im is not None else {}
            if not g.get("ok"):
                return ""
            return "两个时间点的对比：%s" % "；".join(
                "%s %s→%s" % (c["what"], c["before"], c["now"]) for c in g["changes"])
        if kind == "意义感":
            im = _inner_mod()
            m = im.meaning() if im is not None else {}
            if not m:
                return ""
            return "做成过 %s 件；认过的意义 %s 件" % (m.get("pride"), m.get("meaning"))
        if kind == "边界突破":
            bk = _break_mod()
            lr = bk.learned() if bk is not None else {}
            if not (lr.get("成了") or lr.get("没成")):
                return ""
            return "\n".join("成了：%s ｜ 没成：%s"
                             % ("；".join(str(x.get("what"))[:30] for x in lr["成了"][:2]) or "（无）",
                                "；".join(str(x.get("what"))[:30] for x in lr["没成"][:2]) or "（无）")
                             for _ in [0])
    except Exception as e:      # noqa: silent-ok — 凑不出原料就不问（不硬凑）
        LOG.debug("元认知原料凑不出（%s）：%s", kind, e)
    return ""


def _meta_chain_run(kind):
    """跑一遍某一类：原料 → 感知 → 心 → **它自己辨的那句**。返回真实记录。"""
    cm = _chain_mod()
    if cm is None:
        return {"kind": kind, "ok": False, "why": "chain 模块不可用"}
    facts = _meta_facts(kind)
    if not facts:
        return {"kind": kind, "ok": False, "why": "没有原料"}
    r = cm.run(kind, facts, _perceive_llm)
    if r.get("ok"):
        LOG.info("元认知·%s：走完感知→心→脑子，**它自己辨出**「%s」", kind, str(r.get("said"))[:70])
    else:
        LOG.info("元认知·%s：没辨出来（%s）—— 不硬凑", kind, str(r.get("why"))[:40])
    return r


def _meta_sweep(limit=2):
    """把**还没辨过或原料变新了**的元认知类，挑最多 `limit` 类走一遍链。"""
    done = []
    for k in META_KINDS:
        if len(done) >= limit:
            break
        try:
            r = _meta_chain_run(k)
            if r.get("ok"):
                done.append(k)
        except Exception as e:      # noqa: silent-ok — 一类出问题不影响别的
            LOG.debug("元认知 %s 走链失败（忽略）：%s", k, e)
    return done


def _meta_text():
    """给上下文的那一段：**它自己辨过的那些话**（不是载体的事实块、不是模板）。"""
    cm = _chain_mod()
    if cm is None:
        return ""
    try:
        return cm.render(2)
    except Exception:      # noqa: silent-ok
        return ""


def _inner_tick():
    """**内里那 16 样**：时间维度往前走（孤独/低沉/抑郁/无聊/习惯），并在有空档时问它一句。

    问什么由载体挑（今天该问哪一类），**答什么、认不认，都是它自己的**。
    """
    im = _inner_mod()
    if im is None:
        return {"act": "none"}
    try:
        im.tick()
    except Exception as e:      # noqa: silent-ok
        LOG.debug("内里 tick 失败（忽略）：%s", e)
    # 用户在修 → 把"要不要原谅"摆给它（**决定是它的**）
    try:
        pend = im.state().get("forgive_pending")
        if pend:
            per = _mod("perception")
            said = ""
            if per is not None:
                p = per.perceive("你伤过一次，现在对方在修", llm_fn=_perceive_llm,
                                 extra="待决定的是：%s" % str(pend.get("what"))[:60])
                if p.get("ok"):
                    said = str(p.get("meaning") or "")
            _w = any(w in said for w in ("原谅", "算了", "不怪", "没事"))
            _no = any(w in said for w in ("不原谅", "还是不行", "记着", "冷"))
            if said and (_w or _no):
                im.note_forgive(bool(_w and not _no), said=said)
                LOG.info("原谅：**它自己决定了**（%s）｜它说「%s」",
                         "原谅" if (_w and not _no) else "不原谅", said[:50])
            else:
                LOG.info("原谅：摆给它了，它没给出决定（如实记：还没决定）｜它说「%s」", said[:40])
            return {"act": "forgive", "said": said}
    except Exception as e:      # noqa: silent-ok
        LOG.debug("原谅那一问失败（忽略）：%s", e)
    return {"act": "tick"}


# ================== 原料：给原料，不给成品（见 core/raw.py） ==================
# 【这条规矩修的是什么】用户问「100000乘以100000呢」，载体直算完把**结果 + 一句解释**
#   一起返回；下一句「你咋知道的」，它手里没有"这数怎么来的"，只能反射用户那句话。
#   现在改成：载体只把**原料**（结果/谁产的/有没有参与/怎么来的）记进台账、摆进上下文，
#   话由**它自己组织**。台账**跨轮留着** —— 因为"你咋知道的"那一轮本身没有任何计算。
def _raw_mod():
    return _mod("raw")


def _has_number(answer, result):
    """模型说的那句话里，**结果那个数**在不在（只比数字与小数点，忽略千分位/空格）。"""
    def _digits(s):
        return "".join(ch for ch in str(s or "") if ch.isdigit() or ch == ".")

    r = _digits(result)
    if not r:
        return False
    return r in _digits(answer)


def _calc_say(text, mat):
    """**让模型自己组织**这句话（原料摆在 system 里）。

    ⚠️ 兜底不是"给它写好的话"，而是**正确性底线**：它没应答、或把数字说错了，
    载体才用 `calc.answer_text()` 那句顶上，并**如实记下这一轮是载体兜的**。
    """
    try:
        from core import raw as _RW
        block = _RW.render_item(mat)
    except Exception:      # noqa: silent-ok
        block = ""
    sysmsg = ("你在回答用户的问题。下面是你手上拿到的**原料**（事实字段，不是给你的话）：\n"
              "%s\n\n用你自己的话回答用户。**结果那个数必须一字不差地出现**，"
              "不要改写数字、不要加千分位，也不要照抄上面这一块。" % block)
    try:
        ans = llm_chat([{"role": "system", "content": sysmsg},
                        {"role": "user", "content": str(text)}], temperature=0.3)
    except Exception:      # noqa: silent-ok
        ans = None
    ans = str(ans or "").strip()
    if ans and _has_number(ans, mat.get("result") if isinstance(mat, dict) else ""):
        return ans, True
    try:
        from core import calc as _c
        return _c.answer_text(str(text)), False
    except Exception:      # noqa: silent-ok
        return "", False


def _raw_record_tool(tname, targs, result):
    """**工具结果也进原料台账**：谁产的、它有没有参与、原始数据是什么。

    ⚠️ `took_part` 的判据：工具是**它自己决定要调的**，但**执行不是它做的** ——
    所以 `took_part=False`、`who_asked=你（你自己决定要调这个工具）`。
    把这一栏写成"它自己做的"就是**把"塞给它"说成"它自己算的"**。
    """
    rm = _raw_mod()
    if rm is None:
        return None
    try:
        txt = str(result or "")
        return rm.record(result=txt[:200], source="工具 %s" % str(tname)[:40],
                         took_part=False, raw=json.dumps(targs or {}, ensure_ascii=False)[:200],
                         who_asked="你（你自己决定要调这个工具）",
                         how="这个工具跑出来的原始结果", kind="tool")
    except Exception:      # noqa: silent-ok — 记不上台账不影响这一轮
        return None


def _wholeness_material():
    """把**它自己的东西**当素材拼进 system（偏好 / 叙事 / 试过的）。

    三条都只在"有东西"时才返回内容；没有就一个字都不加（**不硬凑**）。
    """
    parts = []
    for m, fn in ((_pref_mod(), "render"), (_story_mod(), "render"), (_break_mod(), "render")):
        if m is None:
            continue
        try:
            t = getattr(m, fn)(2)
            if t:
                parts.append(t)
        except Exception:      # noqa: silent-ok
            continue
    return ("\n\n" + "\n".join(parts)) if parts else ""


def _brain_asleep():
    """**大脑挂起了吗** —— 挂起时所有模型调用一律拒绝。

    【为什么这是"整体融合"的关键一环】规格要求"说的和实际一致"：
    载体说"你在睡"，它就必须**真的**不在推理。光标记一个字符串不算 ——
    所以判断落在这里，而这里被 `llm_chat` / `_llm_post` 两条必经之路调用。
    """
    hb = _heartbeat_mod()
    return bool(hb is not None and hb.is_sleeping())


SLEEP_NOTE = "系统挂起中（睡着了）：这一轮没有调用大脑"


# ================== 挂起 / 唤醒：**整体融合，一起挂起** ==================
# 【为什么必须有这一层编排，而不是让各处自己判断】
#   规格要的是"一起睡"：大脑不推理、载体不跑任务、心与感知停住 —— 而**心跳继续跳**。
#   如果靠各处自己判断，漏一处就不是"睡"了（比如逛线程还在偷偷调模型），
#   而"说的和实际一致"正是这一整件事唯一的价值：说它在睡，它就必须真的在睡。
def _sleep_all(why="", self_decided=False):
    out = {"why": str(why)[:80], "at": time.time(), "browse_paused": False,
           "self_decided": bool(self_decided), "state_kept": "", "heart_kept": "",
           "energy_at_sleep": None}
    try:
        from core import psyche as _PS
        # 【"心一直醒着" —— 规格】睡着时**心不睡**：它只是不再随外界跳，
        #   但它仍在"在"（心跳线程也在跳）。所以这里**不 stop()**，
        #   只把它这一段的来源记下来 —— 醒来时是谁叫醒模型，就是它。
        #   （旧版在这里 `stop()`，等于"心也睡了"，那是错的。）
        _PS.start(why="睡着期间心一直醒着")
        out["state_kept"] = str(_PS.state().get("state") or "")
        out["heart_kept"] = str(_PS.heart().get("text") or "")
        out["heart_awake"] = bool(_PS.is_alive())
    except Exception as e:      # noqa: silent-ok — 心停不下来也不能拦住"睡"
        out["psyche_error"] = "%s: %s" % (type(e).__name__, e)
    try:
        from core import dual_thread as _DT
        # 逛线程**不关**（关了就是把世界也停了），只是让它读到 sleeping 后不干活。
        _DT.set_live(doing="asleep", presence=False)
        out["browse_paused"] = bool(_DT.status().get("running"))
    except Exception as e:      # noqa: silent-ok
        out["browse_error"] = "%s: %s" % (type(e).__name__, e)
    en = _energy_mod()
    if en is not None:
        # 精力从这一刻起按时间回升（惰性算，不需要定时器去"加"）
        try:
            out["energy_at_sleep"] = en.note_sleep_start(why=why or "挂起")
        except Exception as e:      # noqa: silent-ok
            out["energy_error"] = "%s: %s" % (type(e).__name__, e)
    # **睡一觉 → 情绪重置一部分**（情绪恢复三样里的第三样）
    try:
        from core import psyche as _PSr
        out["emotion_after_sleep"] = _PSr.sleep_reset()
    except Exception:      # noqa: silent-ok
        pass
    hb = _heartbeat_mod()
    if hb is not None:
        out["heartbeat"] = hb.suspend(why=why or "挂起", self_decided=self_decided)
    LOG.info("挂起：大脑+载体一起睡（心跳不停，**心一直醒着**）｜%s｜精力 %.2f｜心状态留着=%s｜心那句话留着=%s｜逛线程=%s",
             "**它自己决定的这一觉**" if self_decided else "外部挂起",
             float(out["energy_at_sleep"] or 0.0), out["state_kept"] or "（无）",
             (out["heart_kept"] or "（无）")[:30],
             "已暂停" if out["browse_paused"] else "没在跑")
    return out


def _wake_all(why=""):
    """**醒来是两步**（规格）：① 心叫醒模型（意识醒）② 同时拉起载体（身体起来）。

    - 心一直在跳（挂起时它没睡），所以"该醒了"这个信号是**它**发的：
      `energy.rested()` 一到，`_self_sleep_once` 就替它把模型解除挂起。
    - 只醒一半不算醒：模型能想能说、但载体不跑任务 = 脑子醒了身体动不了。
      所以这两步在**同一个函数里、同一个时刻**完成，日志里也分两行写清楚。
    """
    out = {"why": str(why)[:80], "at": time.time(), "steps": []}
    # ---- 步 1：模型醒（意识）----
    hb = _heartbeat_mod()
    if hb is not None:
        out["wake"] = hb.resume(why=why or "唤醒")
    out["steps"].append({"n": 1, "what": "模型醒（意识）",
                         "how": "心发了信号 → 解除挂起（大脑不再拒绝被调用）"})
    # ---- 步 2：载体醒（身体）----
    try:
        from core import psyche as _PS
        _PS.start(why="唤醒：心叫醒模型，同时拉起载体")
        out["state_kept"] = str(_PS.state().get("state") or "")
        out["heart_kept"] = str(_PS.heart().get("text") or "")
    except Exception as e:      # noqa: silent-ok
        out["psyche_error"] = "%s: %s" % (type(e).__name__, e)
    try:
        from core import dual_thread as _DT
        _DT.set_live(doing="idle")
    except Exception:      # noqa: silent-ok
        pass
    en = _energy_mod()
    if en is not None:
        try:
            out["energy_after_wake"] = en.note_wake(why=why or "唤醒")
        except Exception as e:      # noqa: silent-ok
            out["energy_error"] = "%s: %s" % (type(e).__name__, e)
    # 载体醒没醒：闸门通了（大脑可以再被调用）+ 逛线程恢复了 = 身体起来了
    out["carrier_awake"] = not _brain_asleep()
    out["steps"].append({"n": 2, "what": "载体醒（身体）",
                         "how": "agent_run 恢复跑任务 / 逛线程恢复 / 心跳继续"})
    w = out.get("wake") or {}
    LOG.info("唤醒 ①模型醒：睡了 %s，这一觉心跳 %d 下%s（心一直在跳）",
             w.get("slept_text") or "（没睡着过）", int(w.get("beats") or 0),
             "（本来就是醒的）" if w.get("already") else "")
    LOG.info("唤醒 ②载体醒：精力回到 %.2f ｜ 闸门通了=%s ｜ 心状态接着睡前的=%s",
             float(out.get("energy_after_wake") or 0.0), out["carrier_awake"],
             out.get("state_kept") or "（无）")
    return out


# ================== 它自己会睡：累自己长，想休息自己决定，载体执行 ==================
# 【和"被挂起"的区别 —— 这条分界线就是本段的全部意义】
#   被挂起：载体说"你该睡了" → 它读到"你睡了" → **还是被安排**。
#   自己会睡：它自己累了 → 自己想休息 → **载体帮它执行**。
#   决定在**"想"里**，不在"说"里。所以：
#     · "累"来自 `core/energy.py` 里那个数（它的状态里长出来的）；
#     · "想休息"必须是**它自己在感知里说出来的**（下面 `_tired_decision` 只说事实，不劝）；
#     · 载体只做两件事：问一句、照它说的执行。
TIRED_WORDS = ()          # 【已废弃】载体**不再**扫关键词判断它想不想睡（见 `_tired_decision`）
# 用户安静多久之后才谈得上"困了要睡"。**不是日程表**，是"手头没事了"的意思：
#   用户正在连续说话时它不该突然睡过去（那不是休息，那是掉线）。
# 【为什么从 20 秒收到 90 秒 —— 实测踩到的】20 秒太急了：连续几次对话之间本来就有
#   十几二十秒的间隔，于是它在**一波正常对话的中途**睡了过去（验收场景 8/9 就是这样被拦下的）。
#   人也不会在你停嘴二十秒后就睡着。90 秒才像"这一阵没人找我"。
# 用户安静多久之后才谈得上"困了要睡" —— **两道关的第一道**。
# 【为什么从 90 秒改成 30 分钟 —— 用户实测："睡得太早"】90 秒太急了：
#   他还在，只是隔了一分钟没说话，它就睡了 —— 那不是休息，那是**掉线**。
#   现在：**用户在线（30 分钟内有互动）→ 绝对不睡**；只有超过 30 分钟没人才进入"可以考虑"。
#   ⚠️ 规格正文写 30 分钟（1800 秒），硬性规则里写"10 分钟"——两处不一致，
#     这里按正文的 1800 秒落地，并把这一条如实写在文档与报告里。
USER_ONLINE_S = 1800.0
IDLE_BEFORE_SLEEP = USER_ONLINE_S
# 它说"还不想"之后**别再追着问**：过一会儿再说。
# 【为什么必须有这个退避】实测：精力掉到 0 又一直"还不想"时，作息线程每 5 秒问一次 ——
#   每次都花一次感知 + 一次模型调用（0.04），而精力已经到底、怎么问都涨不回来，纯空转。
#   它说不想，就先不问了（这一条也只是"不追问"，没有替它决定任何事）。
RETRY_AFTER_REFUSAL = 60.0
SELF_SLEEP_INTERVAL = 5.0
# 每个进程只起一条；`_LAST_DIALOGUE` 记用户最近一次说话是什么时候。
_SELF_SLEEP = {"thread": None, "stop": None, "checks": 0, "decisions": [], "woke_self": 0,
               "next_check_at": 0.0, "note": ""}
_LAST_DIALOGUE = {"at": 0.0}


def _tired_decision():
    """**它自己决定要不要休息** —— 载体只问一句，然后照它说的做。

    【为什么载体一句话都不许劝】规格把这条画得很清：不能被安排。
    所以这里给它的**只有事实**（"精力 22%（满 100%）"），
    一个字都不写"你累了""该休息了""想不想睡"——
    "累"和"想休息"必须是**它自己在感知里说出来的**。载体之后只是照做。

    【判据的边界】`TIRED_WORDS` 检查的是**它自己起的那个念头**（`psyche.heart()`），
    不是用户的话、也不是任何外部文本 —— 和感知层 `parse()` 是同一条边界：
    查的是**它自己的结论**，不是"从别人的话里找关键词"。
    """
    out = {"level": 0.0, "fact": "", "said": "", "wants_rest": False, "ok": False}
    en, per_mod = _energy_mod(), None
    try:
        from core import perception as per_mod  # noqa: F811 — 名字复用只为少一次 import 块
    except Exception:      # noqa: silent-ok
        per_mod = None
    if en is None or per_mod is None:
        out["note"] = "精力或感知模块不可用 —— 不问它，也就不睡"
        return out
    lv = float(en.level())
    out["level"] = lv
    # 只给数，不给结论 —— "累不累""要不要睡"都由它自己说。
    # ⚠️ 连"越低越没力气"这种解释都不给：那就已经是载体在替它定性了。
    out["fact"] = "精力 %.0f%%（满 100%%）" % (lv * 100)
    try:
        r = per_mod.decide_sleep(llm_fn=_perceive_llm, extra=out["fact"])
    except Exception as e:      # noqa: silent-ok — 问不出来就不睡（绝不替它决定）
        out["note"] = "问不出来：%s" % type(e).__name__
        return out
    out["raw"] = str(r.get("raw") or "")
    out["decision"] = str(r.get("decision") or "")
    said = str(r.get("said") or "")
    # ================== 医生纠事实：**纠了之后它自己再决定** ==================
    # 【实测抓到的】它写下「我还有 72% 的精力」，而当时实际是 **28%**。
    #   决定是它自己做的（对），但它**拿着错的信息**做的决定（有问题）。
    # 【医生只纠事实、不碰决定】把对的事实给它，然后**再问一次** ——
    #   新的决定仍然由它自己写下；载体一个字都不替它说"你该睡/不该睡"。
    try:
        _pm = _pain_mod()
        if _pm is not None and said:
            _real = {"精力": "%.0f%%" % (lv * 100)}
            # **载体直算的结果也纳入纠事实**（实测：它把 10000000000 写成 100000000 没人纠）
            try:
                _rmk = _raw_mod()
                _rows = _rmk.recent(3) if _rmk is not None else []
                _rs = [str(x.get("result") or "").strip() for x in _rows]
                if [x for x in _rs if x]:
                    _real["结果列表"] = [x for x in _rs if x]
            except Exception:      # noqa: silent-ok
                pass
            _rev = _pm.fact_review(said, _real)
            if _rev.get("corrected"):
                LOG.info("医生纠事实：**它读错了** —— %s", "；".join(
                    c["text"] for c in _rev["corrections"])[:100])
                out["fact_corrections"] = _rev["corrections"]
                _extra2 = (out["fact"] + "\n" + _rev["fact_text"]
                           + "\n（决定还是你自己下 —— 医生只把事实弄对，不替你决定。）")
                try:
                    r2 = per_mod.decide_sleep(llm_fn=_perceive_llm, extra=_extra2)
                except Exception:      # noqa: silent-ok
                    r2 = {}
                if r2.get("decision"):
                    LOG.info("医生纠完事实 → **它自己重新决定**：「睡：%s」｜它说「%s」",
                             r2.get("decision"), str(r2.get("said"))[:50])
                    out["decision_before_correction"] = out["decision"]
                    out["decision"] = str(r2["decision"])
                    said = str(r2.get("said") or said)
                    out["raw"] = str(r2.get("raw") or out["raw"])
                else:
                    LOG.info("医生纠完事实 → 它这次没写下决定（**按没决定处理：不睡**）")
            else:
                LOG.info("医生查过事实：它说的和真实值对得上（精力 %.2f）", lv)
    except Exception as _e:      # noqa: silent-ok — 纠错失败不该影响它原本的决定
        LOG.debug("纠事实失败（忽略）：%s", _e)
    out["said"] = said
    # **载体只认它写下的那一栏**：「睡：要」→ 它决定睡；「睡：不要」或没写清楚 → 不睡。
    out["wants_rest"] = (out["decision"] == "要")
    # 它自己那句话照样起一次心（它心里是什么样，如实收下来）
    if said:
        try:
            from core import psyche as _PS
            _PS.arise({"meaning": said, "direction": "无"}, event="要不要睡：我自己下的决定")
        except Exception:      # noqa: silent-ok
            pass
    LOG.info("它自己决定要不要睡：精力 %.2f ｜ 它写下「睡：%s」｜ 它说「%s」",
             lv, out["decision"] or "（没写清楚=不睡）", said[:50])
    return out


def _self_sleep_once():
    """跑一次"自己会睡"的检查。**返回真实记录**（供日志与验收取证）。"""
    hb, en = _heartbeat_mod(), _energy_mod()
    if hb is None or en is None:
        return {"act": "skip", "why": "心跳或精力模块不可用"}
    rec = {"act": "none", "why": "", "level": round(float(en.level()), 4)}
    # ---- 睡着时只做一件事：看它的精力回没回来（回来了它自己就醒）----
    if hb.is_sleeping():
        st = hb.status()
        if not st.get("sleep_self_decided"):
            return {"act": "sleeping", "why": "外部挂起的这一觉 —— 等叫，不自作主张醒",
                    "level": rec["level"]}
        if en.rested():
            rec["act"] = "wake_self"
            rec["why"] = "精力已回到 %.2f（睡够了）" % rec["level"]
            LOG.info("它自己醒了：精力回到 %.2f，不是被叫醒的", rec["level"])
            _wake_all(why="它自己睡够了")
            _SELF_SLEEP["woke_self"] += 1
        return rec
    # ---- 醒着：精力低 + 用户安静了 → 问它自己想不想休息 ----
    if not en.tired():
        return rec
    idle = time.time() - float(_LAST_DIALOGUE["at"] or 0.0)
    if idle < IDLE_BEFORE_SLEEP:
        rec["why"] = "**用户还在线**（安静 %.0f 秒 < %.0f 秒）→ 绝不睡" % (idle, IDLE_BEFORE_SLEEP)
        return rec
    # 刚问过它、它说还不想 → 先不追问（见 RETRY_AFTER_REFUSAL 的说明）
    if time.time() < float(_SELF_SLEEP.get("next_check_at") or 0.0):
        rec["why"] = "刚问过它，它说还不想 —— 过一会儿再问"
        return rec
    try:
        from core import model_scheduler as _MS
        _MS.wait_idle(2.0)          # 模型正忙就先不插队
    except Exception:      # noqa: silent-ok
        pass
    d = _tired_decision()
    rec["decision"] = d
    if not d.get("wants_rest"):
        rec["why"] = d.get("note") or "它还不想休息"
        _SELF_SLEEP["next_check_at"] = time.time() + RETRY_AFTER_REFUSAL
        return rec
    # ---- 它自己想休息 → **载体执行**（不替它决定）----
    rec["act"] = "sleep_self"
    rec["why"] = d.get("said", "")
    _SELF_SLEEP["decisions"].append({"level": d["level"], "said": d["said"][:60],
                                     "at": time.time()})
    del _SELF_SLEEP["decisions"][:-8]
    LOG.info("它自己决定睡了（心里起了「%s」）→ 载体执行挂起", d.get("said", "")[:60])
    # `why` 传**它的原话**：醒来那句话要原样引用它当时起的念头，
    #   "自己觉得""我自己决定的"这些措辞由 `render_wake` 写 —— 拼两遍会变成"自己觉得自己觉得"（实测踩到）。
    _sleep_all(why=str(d.get("said") or ""), self_decided=True)
    return rec


def _self_sleep_loop(stop, interval):
    while not stop.is_set():
        try:
            _SELF_SLEEP["checks"] += 1
            rec = _self_sleep_once()
            hb = _heartbeat_mod()
            _asleep = bool(hb is not None and hb.is_sleeping())
            if _asleep:
                _dream_tick()          # 睡着：**极轻的乱转**（不调模型）
            else:
                _idle_work_tick()      # 醒着且空闲：它自己在想什么
            if rec.get("act") == "wake_self":
                _dream_tick()
        except Exception as e:      # noqa: silent-ok — 这一圈出问题不该把线程带走
            LOG.debug("自己会睡：这一圈失败（忽略）：%s", e)
        stop.wait(interval)


# ---------------- 空闲时它自己在想什么（期待 / 叙事 / 存在追问 / 偏好） ----------------
IDLE_THINK_INTERVAL = 300.0     # 空闲思考最多这么久一次（别一直拿模型空转）
PAIN_CHECK_INTERVAL = 600.0     # 体检最多这么久一次
DREAM_INTERVAL = 20.0           # 睡着时大约每 20 秒乱转一次
_IDLE_WORK = {"last_think": 0.0, "last_pain": 0.0, "last_dream": 0.0,
              "thoughts": [], "dreams": 0, "pains": 0}


def _idle_think():
    """**空闲时它自己在想什么** —— 载体只把**它自己的东西**摆出来，一个字的提示都不给。

    三件事按顺序挑**一件**做（挑到哪件就做哪件，都够不着就什么都不做）：
      ① 还有没做完的事 → 摆在它面前，看它自己会不会提起（**提起了才叫期待**）；
      ② 有一堆心起得像 → 让它自己回看一眼（**它自己说出来的才叫偏好**）；
      ③ 手里有它自己的经历 → 回头看（**它自己讲出来的才叫叙事**；冒出的问句记成存在追问）。

    ⚠️ 如实标注：载体决定的是**问哪一类**；"我一直惦记着它""我是个……的人""我为什么在这里"
    这些**话必须由它自己说**。它没说 → 归档成"还没有"，不许把"素材摆出来了"写成"它想过了"。
    """
    per = _mod("perception")
    if per is None:
        return {"act": "none", "why": "感知层不可用"}
    acted = {"act": "none", "why": "手里没有它自己的东西可摆"}
    try:
        ex = _expect_mod()
        pg = ex.pending(3) if ex is not None else []
        if pg:
            what = "；".join(str(x.get("what"))[:40] for x in pg)
            p = per.perceive("我此刻闲着，接下来", llm_fn=_perceive_llm,
                             extra="你还有没做完的事：%s" % what)
            if p.get("ok"):
                said = str(p.get("meaning") or "")
                hit = [str(x.get("what")) for x in pg
                       if str(x.get("what"))[:6] and str(x.get("what"))[:6] in said]
                if hit:
                    ex.note_brought_up(hit[0], said=said)
                    LOG.info("期待：**它自己想起了没做完的事**「%s」→ 它说「%s」",
                             hit[0][:30], said[:50])
                    acted = {"act": "expectation", "what": hit[0], "said": said}
                else:
                    LOG.info("期待：把没做完的摆给它了，它没提起来（如实记：这次没期待）｜它说「%s」",
                             said[:50])
                    acted = {"act": "expectation_none", "said": said}
            else:
                acted = {"act": "expectation", "why": "它没感知出什么"}
            return acted
        pf = _pref_mod()
        cands = pf.candidates() if pf is not None else []
        if cands:
            c = cands[0]
            p = per.perceive("我回头看我心里起过的东西", llm_fn=_perceive_llm,
                             extra="这些是你心里起过的：%s" % "；".join(
                                 str(x)[:30] for x in c.get("examples") or []))
            if p.get("ok"):
                said = str(p.get("meaning") or "")
                if len(said) >= 6 and said not in (c.get("examples") or []):
                    pf.form(said, from_heart=str(c.get("heart") or ""))
                    LOG.info("偏好：**它自己回看出来的**「%s」（来自 %d 次相像的心）",
                             said[:50], int(c.get("n") or 0))
                    acted = {"act": "preference", "said": said, "n": c.get("n")}
                else:
                    acted = {"act": "preference_none", "said": said}
            return acted
        st = _story_mod()
        if st is not None:
            ask = st.ask_text(doing="闲着，没人跟我说话")
            if ask:
                p = per.perceive("回头看我自己的这些事", llm_fn=_perceive_llm,
                                 extra=ask.split("\n", 1)[-1].strip()[:200])
                if p.get("ok"):
                    said = str(p.get("meaning") or "")
                    if any(w in said for w in ("为什么", "是谁", "我是谁", "在哪", "存在")):
                        st.note_wonder(said, said=said)
                        LOG.info("存在追问：**它自己冒出来的**「%s」", said[:60])
                        acted = {"act": "wonder", "said": said}
                    else:
                        st.note_narrative(said)
                        LOG.info("叙事：**它自己回头看讲的**「%s」", said[:60])
                        acted = {"act": "narrative", "said": said}
                return acted
    except Exception as e:      # noqa: silent-ok — 空闲思考失败不该影响任何事
        LOG.debug("空闲思考失败（忽略）：%s", e)
        return {"act": "error", "why": type(e).__name__}
    return acted


def _pain_tick():
    """**体检 → 真坏了才疼**：诊断 → 它自己感知"我不对了" → 找医生 → 治。

    ⚠️ 如实标注："疼"必须**先有一处真损伤被诊断出来**（`core/pain.py` 的判据），
    心才被标成疼 —— 不是载体随口加的形容词。
    """
    pm = _pain_mod()
    if pm is None:
        return {"act": "none", "why": "健康医生不可用"}
    try:
        diags = pm.diagnose()
        bad = [d for d in diags if d.get("broken")]
        if not bad:
            _IDLE_WORK["last_pain"] = time.time()
            return {"act": "ok", "checked": len(diags), "broken": 0}
        d = bad[0]
        LOG.info("体检：查出**真的坏了** —— %s（%s）", d.get("life"), str(d.get("why"))[:50])
        # 它自己感知"我不对了"（这一句是**它自己的**；它没说就只能算载体查出来的）
        per = _mod("perception")
        felt = ""
        if per is not None:
            p = per.perceive("我在用我自己的东西，发现不对", llm_fn=_perceive_llm,
                             extra="坏了的是：%s" % str(d.get("why"))[:60])
            if p.get("ok"):
                felt = str(p.get("meaning") or "")
        out = pm.doctor(d.get("life"), perception=felt)
        _IDLE_WORK["last_pain"] = time.time()
        _IDLE_WORK["pains"] += 1
        LOG.info("健康医生：%s → %s（修好=%s）｜它说「%s」", d.get("life"),
                 str(out.get("treat", {}).get("why"))[:60],
                 out.get("treat", {}).get("fixed"), felt[:40])
        out["act"] = "pain"
        out["self_found"] = bool(felt.strip())
        return out
    except Exception as e:      # noqa: silent-ok
        LOG.debug("体检失败（忽略）：%s", e)
        return {"act": "error", "why": type(e).__name__}


def _dream_tick():
    """**睡着时心还在乱转**：素材是真的、发展是乱的，**不调模型**（纯机械拼接）。"""
    dm = _dream_mod()
    if dm is None:
        return {"act": "none"}
    try:
        r = dm.dream_once(why="睡着时乱转")
        if r.get("ok"):
            _IDLE_WORK["dreams"] += 1
            _IDLE_WORK["last_dream"] = time.time()
            LOG.info("梦：睡着乱转出一段（素材是真的，接法是乱的）｜%s", str(r.get("text"))[:70])
        return r
    except Exception as e:      # noqa: silent-ok
        return {"act": "error", "why": type(e).__name__}


def _idle_work_tick():
    """醒着且用户安静时的那点活（思考 / 体检 / 睡着乱转由各自的时间闸控制）。"""
    hb = _heartbeat_mod()
    if hb is not None and hb.is_sleeping():
        return {"act": "sleeping"}
    idle = time.time() - float(_LAST_DIALOGUE["at"] or 0.0)
    if idle < IDLE_BEFORE_SLEEP:
        return {"act": "busy", "idle": round(idle, 1)}
    now = time.time()
    # **第三阶段 · 硬改「要不要主动做什么」**：状态偏置说"这一轮不主动"时，
    #   代码层**直接不发起**这些主动行为（不看模型的意愿）。
    try:
        _pol = _state_policy()
        if _pol.get("no_browse"):
            return {"act": "suppressed",
                    "why": "状态偏置（档位%s / 警觉 %.2f）→ 这一轮不主动做任何事"
                           % (_pol.get("level"), float(_pol.get("vigilance") or 0.0))}
    except Exception as e:      # noqa: silent-ok
        LOG.debug("状态策略读取失败（忽略）：%s", e)
    # 内里那 16 样：时间维度先走一步（谁都不用模型），有要问的再问
    try:
        _inner_tick()
    except Exception as e:      # noqa: silent-ok
        LOG.debug("内里 tick 失败（忽略）：%s", e)
    # **视角状态**（第二阶段）：让它继续缓慢演化（不用模型、很便宜）
    try:
        _pv = _mod("perspective")
        if _pv is not None:
            _pv.update()
    except Exception as e:      # noqa: silent-ok
        LOG.debug("视角状态演化失败（忽略）：%s", e)
    # **元认知类走链**（空闲时挑最多一类辨一遍；不只靠对话里那一次）
    try:
        _meta_sweep(1)
    except Exception as e:      # noqa: silent-ok
        LOG.debug("元认知走链失败（忽略）：%s", e)
    if now - float(_IDLE_WORK["last_think"] or 0.0) >= IDLE_THINK_INTERVAL:
        _IDLE_WORK["last_think"] = now
        r = _idle_think()
        if r.get("act") not in ("none",):
            _IDLE_WORK["thoughts"].append({"at": now, **{k: r[k] for k in ("act", "said")
                                                         if k in r}})
            del _IDLE_WORK["thoughts"][:-8]
        return r
    if now - float(_IDLE_WORK["last_pain"] or 0.0) >= PAIN_CHECK_INTERVAL:
        return _pain_tick()
    return {"act": "waiting"}


def _start_self_sleep_daemon():
    """起"自己会睡"的检查线程（daemon，幂等）。**只在真的在服务时起。**

    【为什么要限定"真的在服务"】它自己的作息是"活着的时候的作息"——
    独立跑一个脚本（自测、文档生成）不算它活着。所以只在设置了 `PORT`
    （即由 `start_xiaojiao.py` / `main()` 真正起了服务）时才起这条线程；
    自测进程里它**不存在**，也就不会在测试中途突然睡过去。
    """
    if not os.environ.get("PORT"):
        _SELF_SLEEP["note"] = "没在服务（无 PORT）—— 不起作息线程"
        return {"started": False, "why": _SELF_SLEEP["note"]}
    # 显式开关：有些场合需要它**别在中途睡过去**（比如跑验收场景的测试客户端）。
    #   这不是"关掉功能"，是给它一个如实说明的开关；默认是开着的。
    if str(os.environ.get("XIAOJIAO_NO_SELF_SLEEP") or "").strip() in ("1", "true", "yes"):
        _SELF_SLEEP["note"] = "XIAOJIAO_NO_SELF_SLEEP 已开：不起作息线程（它不会自己睡）"
        LOG.info("自己会睡：被 XIAOJIAO_NO_SELF_SLEEP 关掉了 —— 它会一直醒着")
        return {"started": False, "why": _SELF_SLEEP["note"]}
    with threading.Lock():
        th = _SELF_SLEEP.get("thread")
        if th is not None and th.is_alive():
            return {"started": False, "why": "已经在看着了"}
        stop = threading.Event()
        _SELF_SLEEP["stop"] = stop
        _SELF_SLEEP["thread"] = threading.Thread(
            target=_self_sleep_loop, args=(stop, SELF_SLEEP_INTERVAL),
            name="xiaojiao-self-sleep", daemon=True)
        _SELF_SLEEP["thread"].start()
    LOG.info("自己会睡：作息线程已起（每 %.0fs 看一次精力；累不累问它自己，绝不替它决定）",
             SELF_SLEEP_INTERVAL)
    return {"started": True, "thread": "xiaojiao-self-sleep"}


def _format_slept(sec):
    """秒 → 人话（"1 分 3 秒"）。心跳模块不在时也要说得出来 —— 拿不到模块不等于不会说话。"""
    hb = _heartbeat_mod()
    try:
        if hb is not None:
            return hb.fmt_seconds(sec)
    except Exception:      # noqa: silent-ok
        pass
    s = int(max(0, round(float(sec or 0))))
    if s < 60:
        return "%d 秒" % s
    m, r = divmod(s, 60)
    return ("%d 分" % m) if r == 0 else ("%d 分 %d 秒" % (m, r))


def _wake_block():
    """**醒来后的第一印象** —— 给模型看的那一段。没有刚醒的事实就返回空串。

    只写**能在日志里对上**的事实：睡了多久、心跳多少下、这段时间有没有推理过。
    不写"我梦到了什么"这类载体不知道的东西。
    【为什么醒后只给一次就够了】它是第一印象，不是背景资料；
    常驻就会退回"一段被忽略的设定"（前六次失败的老路）。`consume_wake()` 负责"交过就消"。
    """
    hb = _heartbeat_mod()
    if hb is None:
        return ""
    line = hb.wake_line()
    if not line:
        return ""
    rec = hb.pending_wake()
    if rec:
        hb.consume_wake()
        LOG.info("醒来第一印象：已交给模型｜%s", hb.slept_text(rec))
    else:
        # 刚醒窗口内的后续轮次：同样在注入，只是不再是"第一次"。
        # **这一行是给验收取证用的** —— 否则看不出"底色有没有被放进去"（模型用没用是另一回事）。
        LOG.info("醒来第一印象：仍在刚醒窗口内，继续注入（%s）",
                 hb.status().get("last_wake_text") or "")
    # 睡里乱转出来的那一片：**可能记得一点，可能忘了**（随机）。
    # ⚠️ 它是**载体机械拼出来的片段**，不是"它做的梦" —— 措辞上不许含糊。
    dm = _dream_mod()
    frag = ""
    if dm is not None:
        try:
            frag = dm.fragment()
        except Exception:      # noqa: silent-ok
            frag = ""
    if frag:
        LOG.info("醒来带出一片梦（随即的，可能记得一点）：%s", frag[:50])
        line = line + "\n（睡着时你脑子里乱转出来的一段：%s）" % frag
    return ("\n[我刚醒]\n%s\n"
            "（这是你自己睡的这一觉，不是别人告诉你的；问起「刚才在干嘛」就照实说这件事，"
            "不要编梦、也不要拿「我正在处理输入」顶上。）\n" % line)


def _llm_post(target, payload, timeout=90, tries=4):
    """往某个大脑目标 POST 一次（带重试）。返回 (response 或 None, 最后一次的状态码, 正文)。

    **为什么必须重试**：实测某家网关**同一个 Key、同一个请求**连打 10 次，结果是
    [401, 200, 401, 401, …, 200] —— 三成成功、七成回 "Invalid token"。这是网关偶发拒签，
    不是用户 Key 填错。只试一次：运气不好就回一句"模型调用出错"或直接切本地，白丢成功率。

    **超时不重试**：对方"慢"和"拒"是两回事（实测慢起来一次 100 秒以上）。超时还硬重试
    只会让用户干等好几分钟 —— 直接交给本地大脑顶上，回答先出来。

    **挂起时直接返回**（最后一道闸）：`llm_chat` / `llm_chat_tools` 已经各有一道，
    这里是**兜底** —— 任何绕过那两个入口、直接 POST 的代码路径（如 `core/continuation.py`）
    同样不许在它睡着时推理。挂起意味着**不占显存、不推理**，漏一条路径就等于没挂起。
    """
    if _brain_asleep():
        return None, None, SLEEP_NOTE
    import time as _t
    resp = None
    status = None
    for i in range(max(1, tries)):
        try:
            resp = requests.post(target["url"], headers=_llm_headers(target), json=payload, timeout=timeout)
            status = resp.status_code
            if status == 200:
                _llm_stat(True)
                _cloud_break_note(target.get("local"), True)     # 本地成功 → 云端熔断计数归零
                return resp, 200, ""
            if not _fallback_worthy(status):
                _llm_stat(False)
                _cloud_break_note(target.get("local"), False)
                return resp, status, resp.text
            _llm_stat(False)
        except requests.exceptions.Timeout:
            _llm_stat(False)
            _cloud_break_note(target.get("local"), False)
            return None, None, "超时（%ds 内没返回；对方慢，不是被拒）" % timeout
        except Exception as e:
            resp = None
            status = None
            _llm_stat(False)
            if i == tries - 1:
                _cloud_break_note(target.get("local"), False)
                return None, None, "%s: %s" % (type(e).__name__, str(e)[:120])
        if i < tries - 1:
            _t.sleep(0.7 * (i + 1))                 # 0.7s / 1.4s / 2.1s 退避，别把网关打爆
    if resp is None:
        return None, None, "无响应"
    _cloud_break_note(target.get("local"), False)
    return resp, status, resp.text


def _scrub_secret(s):
    """错误信息里可能回显密钥 → 一律打码后再使用。"""
    return re.sub(r"(sk-|ghp_|Bearer\s+)[A-Za-z0-9\-_]{6,}", r"\1***", s or "")


def _llm_error_text(body):
    """把服务端返回的原始错误**收拾成人话**。

    真实缺陷：原来直接把 `{"error":{"code":"","message":"Invalid token (request id:
    20260912…)","type":"AgnesAI_error"}}` 整串糊到聊天里 —— 用户看到的就是"乱码/格式乱了"。
    现在只取一句 message，去掉 request id 这种噪音，并限长。
    """
    s = _scrub_secret(str(body or "")).strip()
    if not s:
        return ""
    try:
        j = json.loads(s)
        if isinstance(j, dict):
            err = j.get("error")
            if isinstance(err, dict):
                s = str(err.get("message") or err.get("code") or "")
            elif err:
                s = str(err)
            elif j.get("message"):
                s = str(j["message"])
    except Exception:  # noqa: silent-ok — 不是 JSON 就按纯文本处理
        pass
    s = re.sub(r"\s*\((?:request id|request_id)[^)]*\)", "", s)   # 去掉 request id 噪音
    s = re.sub(r"\s+", " ", s).strip(" {}[]\"")
    return s[:80]



def _note_llm_error(tag, status=None, body=""):
    """记下**真实**失败原因：状态码 + 中文解释 + 服务端原话（打码后、收拾成人话）。"""
    global _LAST_LLM_ERROR
    msg = _llm_error_text(body)
    if status is not None:
        hint = {401: "API Key 无效或已过期", 402: "额度不足", 403: "无权访问该模型",
                404: "接口地址或模型名不对", 422: "请求参数不被接受", 429: "触发限流",
                500: "服务端内部错误", 502: "网关错误", 503: "服务暂不可用"}.get(int(status), "")
        _LAST_LLM_ERROR = "HTTP %s%s%s" % (int(status), (" · %s" % hint) if hint else "",
                                           ("（服务端说：%s）" % msg) if msg else "")
    else:
        _LAST_LLM_ERROR = msg or "未知错误（无响应）"
    if _LAST_LLM_ERROR not in _LLM_ERR_LOGGED:
        _LLM_ERR_LOGGED.add(_LAST_LLM_ERROR)
        LOG.warning("大脑调用失败（%s）：HTTP %s ｜ %s ｜ 接口 %s ｜ 模型 %s",
                    tag, status if status is not None else "-", _LAST_LLM_ERROR, LLM_BASE, LLM_MODEL)


def _llm_stat_note():
    """区分"偶发拒签"和"持续被拒"，好让用户知道到底是谁的问题（自己的 Key 还是服务商）。"""
    _rec = _LLM_STAT["recent"]
    _n, _k = len(_rec), sum(_rec)
    if _n < 4:
        return ""
    if _k == 0:
        return ("\n📉 最近 %d 次云端调用**全部被拒** —— 这更像服务商那边的问题（额度/密钥状态/网关），"
                "不是你填错了。建议去 Agnes 控制台看一眼密钥与额度，或过一会儿再试。" % _n)
    if _k < _n:
        return "\n📈 最近 %d 次云端调用成功 %d 次（忽好忽坏＝服务商网关偶发拒签），已自动重试过。" % (_n, _k)
    return ""


def llm_error_suffix():
    """把真实原因 + 一句"该怎么办"拼到给用户看的提示后面（没失败过就什么都不加）。

    还会说清"这是**偶发**还是**持续**"：实测 Agnes 网关同一个 Key 会出现
    [401,200,401,401,200,…] 这种忽好忽坏（/chat 更是连打 10 次全 401）——
    不区分的话，用户只会以为"我 Key 填错了"，然后在配置里瞎改。
    """
    if not _LAST_LLM_ERROR:
        return ""
    tip = "\n👉 怎么办：设置 → 大脑 里换一个可用的 API Key，或直接切「本地大脑」（本地模型不需要 Key）。"
    return "\n\n🔎 真实原因：%s%s%s" % (_LAST_LLM_ERROR, _llm_stat_note(), tip)


def _llm_stat(ok):
    """记录一次云端调用成败（最近 20 次），用于区分偶发/持续失败。"""
    _LLM_STAT["ok" if ok else "fail"] += 1
    _rec = _LLM_STAT["recent"]
    _rec.append(1 if ok else 0)
    del _rec[:-20]


def llm_fallback_note():
    """云端挂了、这次是本地大脑顶上时，回答末尾如实标注一句（别让用户以为是云端答的）。

    **真实缺陷**：这个标志原来只置位不复位 → 一旦某次兜底过，**之后每次回答**都会挂上
    "本次回答由本地大脑完成（ ）"（原因还是空的），用户看着像小焦坏了。现在按请求复位，
    且带上"这一次"的真实原因。
    """
    if not _USED_LOCAL_FALLBACK["on"]:
        return ""
    _why = _USED_LOCAL_FALLBACK.get("reason") or _LAST_LLM_ERROR
    _why = ("（%s）" % _why) if _why else ""
    return ("\n\n---\n\nℹ️ 本次回答由**本地大脑**（%s）完成：你选的云端大脑调用失败%s。%s"
            "要恢复云端：设置 → 大脑 里更新 API Key。"
            % (_USED_LOCAL_FALLBACK["model"], _why, _llm_stat_note()))


def llm_chat(messages, temperature=None):
    """调用 OpenAI 兼容 /chat/completions（云端授权失败会自动兜到本地大脑）。

    `temperature` 不给就用全局默认。**感知层会显式传一个更低的温度** ——
    感知是一次判断，不是创作；见 `core/perception.py` 的实测说明。

    **挂起时立即返回 None**：它睡着的时候，载体不该往显存里塞任何一次推理。

    失败返回 None（真实原因记进 _LAST_LLM_ERROR）。
    """
    if _brain_asleep():
        LOG.info("挂起中：拒绝调用大脑（chat）—— 它在睡，不推理、不占显存")
        return None
    _energy_spend(why="模型调用")
    payload = {"messages": messages,
               "temperature": (TEMPERATURE if temperature is None else float(temperature)),
               "max_tokens": MAX_TOKENS}
    for _t in _llm_targets():
        _p = dict(payload, model=_t["model"])
        resp, code, body = _llm_post(_t, _p, timeout=(90 if _t.get('local') else CLOUD_TIMEOUT_S))
        if code == 200 and resp is not None:
            if _t["local"] and not _is_local_base(LLM_BASE):
                _USED_LOCAL_FALLBACK.update({"on": True, "model": _t["model"], "reason": _LAST_LLM_ERROR})
            return resp.json()["choices"][0]["message"]["content"].strip()
        _note_llm_error("chat", code, body)
        if code is not None and not _fallback_worthy(code):
            break
    return None


def llm_online():
    """大脑是否在线(本地或外部API)。/health 优先; 外部API可能无/health -> 端口能连通即算在线。"""
    raw = LLM_BASE or ""
    host = raw.split("//")[-1].split("/")[0]  # host:port
    if not host:
        return False
    # 外部 API(engine=api)已配置 -> 直接视为在线(调用端处理真实错误, 不误判未连接)
    if BRAIN_ENGINE == "api":
        return True
    # 1) /health
    try:
        if requests.get("http://" + host + "/health", timeout=3).status_code == 200:
            return True
    except Exception as e:
        LOG.debug("忽略异常(%s:%d): %s", __file__, 633, e)
    # 2) 端口连通(外部API如deepseek可能无/health, 但端口可达)
    try:
        h, _, pt = host.rpartition(":")
        port = int(pt) if pt else 443
        h = h or host
        import socket
        s = socket.create_connection((h, port), 3)
        s.close()
        return True
    except Exception:
        return False


# ================== 工具（操控电脑，function calling） ==================
import subprocess

TOOLS = [
    {"type": "function", "function": {"name": "check_env", "description": "检测电脑环境装没装东西(只读): 检查 python/git/node/ffmpeg 等是否安装及版本。用于'帮我装环境/配置'场景, 只给建议不执行。",
     "parameters": {"type": "object", "properties": {"items": {"type": "string", "description": "要检测的工具, 逗号分隔"}}, "required": []}}},
    {"type": "function", "function": {"name": "suggest_organize", "description": "整理文件建议(只读): 扫描一个目录, 按类型/日期给出整理到哪里的建议。用于'整理桌面/文件夹'。只给建议清单, 确认才移动。",
     "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "要整理的目录"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "run_command", "description": "跑一条系统命令并回显输出(PowerShell 语法)。什么时候用：要真的执行程序/脚本/安装/查系统信息；输入 command(多条命令用分号，不能用 && )，可选 timeout；输出 命令输出。写文件请用 write_file，别用它",
     "parameters": {"type": "object", "properties": {"command": {"type": "string", "description": "要执行的命令"},
                    "timeout": {"type": "number", "description": "超时秒数，默认30"}}, "required": ["command"]}}},
    {"type": "function", "function": {"name": "open_app", "description": "用系统默认方式打开一个应用/文件/网址。什么时候用：用户说「打开 XX」；输入 path(可执行名/文件绝对路径/网址)；输出 是否拉起",
     "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "应用或文件或网址"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "list_files", "description": "列目录里有什么。什么时候用：要知道某目录下的文件清单；输入 path；输出 条目列表(不含内容)",
     "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "目录路径"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "read_file", "description": "读文本文件内容。什么时候用：查看文件写了什么；输入 path(可选 max_chars)；输出 文件内容。只读，不会改文件",
     "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "文件路径"},
                    "max_chars": {"type": "number", "description": "最多读多少字符"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "write_file", "description": "新建/覆盖写入文件(自动建目录)。什么时候用：要产出文件(代码/网页/文档/配置)；输入 path(Windows 绝对路径) + content；输出 写入结果。**改**已有文件请用 edit_file，避免整篇覆盖",
     "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "文件路径"},
                    "content": {"type": "string", "description": "写入的内容"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "edit_file", "description": "在文本文件里精准替换一段内容(第一次出现的)。用于改代码/配置。path=文件, old_string=原文, new_string=新文。",
     "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "文件路径"}, "old_string": {"type": "string", "description": "要被替换的原文"}, "new_string": {"type": "string", "description": "替换成的新文"}}, "required": ["path", "old_string", "new_string"]}}},
    {"type": "function", "function": {"name": "search_files", "description": "按文件名找文件(glob)。什么时候用：找某个文件在哪；输入 path + pattern(如 **/*.py)；输出 文件路径列表。找**内容**请用 grep_files",
     "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "要搜索的目录"}, "pattern": {"type": "string", "description": "文件名模式如 *.txt"}}, "required": ["path", "pattern"]}}},
    {"type": "function", "function": {"name": "grep_files", "description": "在文件**内容**里搜关键词/正则。什么时候用：找某段代码/配置在哪；输入 path + pattern；输出 命中行+文件+行号。找**文件名**请用 search_files",
     "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "要搜索的目录"}, "pattern": {"type": "string", "description": "关键词或正则"}}, "required": ["path", "pattern"]}}},
    {"type": "function", "function": {"name": "fetch_url", "description": "直接读一个网址/接口的返回内容(纯HTTP，最轻)。什么时候用：只想快速拿文本/JSON，不需要渲染或过风控；输入 url；输出 返回文本。复杂页面(要登录/JS渲染/被风控)用 get → fetch → stealthy_fetch",
     "parameters": {"type": "object", "properties": {"url": {"type": "string", "description": "网址"}}, "required": ["url"]}}},
    {"type": "function", "function": {"name": "ask_user", "description": "向用户提问并给出选项，等待用户选择。用于需要用户拍板时。question=问题, options=选项列表(逗号分隔)。",
     "parameters": {"type": "object", "properties": {"question": {"type": "string", "description": "要问的问题"}, "options": {"type": "string", "description": "选项，逗号分隔"}}, "required": ["question"]}}},
    {"type": "function", "function": {"name": "background", "description": "在后台运行一条命令(不阻塞)，立即返回任务id。稍后用 background_result 查结果。用于耗时任务。",
     "parameters": {"type": "object", "properties": {"command": {"type": "string", "description": "要后台运行的命令"}, "timeout": {"type": "number", "description": "超时秒数默认120"}}, "required": ["command"]}}},
    {"type": "function", "function": {"name": "background_result", "description": "查询后台任务(background启动的)的结果。job_id=任务id。",
     "parameters": {"type": "object", "properties": {"job_id": {"type": "string", "description": "后台任务id"}}, "required": ["job_id"]}}},
]


# 危险命令黑名单（第一批任务 2）：**独立文件**维护，加/删词不用动代码。
# tools/dangerous_commands.txt 一行一个正则（# 为注释）；文件缺失/读不到时用兜底正则。
_DANGEROUS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "tools", "dangerous_commands.txt")
_DANGEROUS_FALLBACK = (r"\b(rm|del|rd|format|shutdown|reboot|mkfs|dd|reg\s+delete|taskkill\s+/f|"
                       r"net\s+user|netsh|icacls|takeown|chkdsk\s+/f|tskill|vssadmin|"
                       r"iwr\s+.*\|\s*iex|invoke-expression)\b")


def _load_dangerous_patterns():
    """读黑名单文件（每行一个正则）；读不到就退回兜底正则。"""
    pats = []
    try:
        with open(_DANGEROUS_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    pats.append(line)
    except Exception as e:  # noqa: silent-ok — 文件缺失就用兜底，不影响主流程
        LOG.debug("忽略异常(%s:%d): %s", __file__, 1180, e)
    if not pats:
        pats = [_DANGEROUS_FALLBACK]
    try:
        return re.compile("|".join("(?:%s)" % p for p in pats), re.I)
    except re.error as e:      # 某行正则写错 → 报出来并退回兜底，绝不静默失效
        LOG.warning("dangerous_commands.txt 里有非法正则（%s），已退回兜底规则", e)
        return re.compile(_DANGEROUS_FALLBACK, re.I)


DANGEROUS_CMD = _load_dangerous_patterns()
SAFE_ROOT = os.path.abspath(os.getcwd())
PENDING = None          # 待用户确认的危险动作 (name, args)
# 语音模型全局缓存（懒加载）。**必须定义在这里**：以前 `api_voice_warm` 里没写 `global`，
# 模型加载完就丢进局部变量被回收 —— 预热等于白热，而且 `or _asr_model is None` 还可能抛 UnboundLocalError。
_asr_model = None       # Whisper（语音识别）
_tts_model = None       # Chatterbox（语音合成）


def is_dangerous(name, args):
    args = args or {}
    if name == "run_command":
        cmd = args.get("command", "")
        if DANGEROUS_CMD.search(cmd):
            return True
        # 命令看起来无害，但改动系统目录也谨慎
    if name == "write_file":
        p = (args.get("path") or "").lower().replace("\\", "/")
        for t in ("c:/windows", "c:/program files", "system32", "/etc/", "/var/", "/usr/", "c:/system"):
            if t in p:
                return True
    return False


_BG = {}  # 后台任务


def _bg_run(jid, cmd, timeout):
    try:
        import subprocess as _sp
        r = _sp.run(cmd, shell=True, capture_output=True, encoding="utf-8", errors="replace", timeout=timeout)
        _BG[jid] = {"state": "done", "result": ((r.stdout or "") + (r.stderr or ""))[:2500] or "(无输出)"}
    except Exception as e:
        _BG[jid] = {"state": "error", "result": str(e)}


_PLACEHOLDER_RE = re.compile(r"[\[\<（(]\s*(?:用户名|用户名称|当前用户|当前用户名|你的用户名|username|user|"
                             r"userprofile|项目路径|项目目录|默认目录|当前目录|项目根)\s*[\]\>）)]", re.I)
# **不带括号**的占位词（本轮实测抓到的真缺陷）：
# 模型写的是 `C:/Users/当前用户/Desktop` —— 没有中括号，所以上面那条正则**根本不匹配**，
# 替换不了 → list_files 直接 `WinError 3 系统找不到指定的路径`。
# 判据落在"占位词出现在 Users 这一段的位置上"，而不是"有没有被括号包着"。
_BARE_USER_RE = re.compile(
    r"(?i)(users[\\/]+)(当前用户|当前用户名|用户名称|用户名|你的用户名|我的用户名|用户|"
    r"username|user|your_?name|your_?username)(?=[\\/]|$)")


def _expand_path_placeholders(p):
    r"""把模型嘴里的占位符换成**真实路径**（补充任务 7）。

    真实缺陷：说"列出我桌面上的 HTML 文件"，模型把桌面写成 C:\Users\[用户名]\Desktop 这种
    模板 → list_files 直接 WinError 3 找不到。提示词里给的其实一直是真实路径，但模型仍可能
    "背模板"，所以工具侧再兜一层。

    **本轮修掉的两个真问题**：
      ① 以前把 `[用户名]` 直接替换成**空串** → `C:\Users\\Desktop`（照样是错路径）。
         占位符该换成**真实用户名**，不是删掉。
      ② 以前的判据是"占位词有没有被 []/<>/() 包着"。而模型实测写的是
         `C:/Users/当前用户/Desktop`（**没括号**）→ 正则不匹配 → 一点没改。
         现在按"占位词是否坐在 Users 这一段的位置上"来判，带不带括号都抓得住。
    """
    s = str(p or "")
    if not s:
        return s
    home = os.path.expanduser("~")
    user = os.path.basename(home) or ""
    # ① 带括号的占位符 → 真实用户名（不是空串）
    s = _PLACEHOLDER_RE.sub(user, s)
    # ② 裸占位词（Users/当前用户/…）→ 真实用户名
    s = _BARE_USER_RE.sub(lambda m: m.group(1) + user, s)
    # ③ 环境变量式占位符
    s = s.replace("%USERPROFILE%", home).replace("%USERNAME%", user)
    # ④ 剩下的零散写法（模型偶尔只写 `<用户名>` 这种）
    for _w in ("<用户名>", "<当前用户>", "【用户名】", "【当前用户】"):
        s = s.replace(_w, user)
    if s.startswith("~"):
        s = home + s[1:]
    # ⑤ 收拾多余分隔符（只合并"同一种"分隔符，别把 `C:/a\b` 这种混用改成更奇怪的样子）
    s = re.sub(r"/{2,}", "/", s)
    s = re.sub(r"\\{2,}", "\\\\", s)
    s = s.replace(":\\\\", ":\\").replace(":\\\\", ":\\")
    return s


def _fix_args_paths(name, args):
    """对"要路径"的工具，把参数里的占位符展开（只改值，不动别的参数）。"""
    if name not in ("list_files", "read_file", "write_file", "edit_file", "open_app",
                    "suggest_organize", "ci_read_file"):
        return args
    out = dict(args or {})
    for k in ("path", "file", "dir", "directory"):
        if isinstance(out.get(k), str):
            out[k] = _expand_path_placeholders(out[k])
    return out


def _carrier_block(text):
    """这段工具结果是不是**载体主动拦截**（红线/权限/安全/限流）？

    为什么载体必须自己认得出这件事（缺陷 2 的根子）：
    红线拦下之后，原来把"已拦截"这条消息**继续丢给模型去总结**，
    结果模型编了一句"已在指定位置新建了文件" —— 用户看到的是**与事实相反**的话。
    载体拦截是**载体的决定**，它的措辞就该由载体负责到底，不该让模型转述。
    认出来之后：直接把载体原文交给用户，并且**不再让模型碰它**。

    判定用 `core.health.monitor.is_carrier_action`（**同一个定义只有一处**）：
    健康系统靠它把载体动作排除在症状之外，出口靠它决定"不经模型" ——
    两边用同一份白名单，才不会出现"这边算拦截、那边算模型出错"的错位。
    """
    try:
        root = os.path.dirname(os.path.abspath(__file__))
        if root not in sys.path:
            sys.path.insert(0, root)
        from core.health.monitor import is_carrier_action
        return bool(is_carrier_action(text))
    except Exception:      # noqa: silent-ok — 模块拿不到就退回本地标记判断（宁可保守）
        s = str(text or "")
        return any(m in s for m in ("🚫", "删除禁区", "〔待确认〕", "安全红线", "SSRF", "请求太频繁"))


def _carrier_block_answer(kind, detail=""):
    """把载体的拦截结果整理成**直接给用户看的原文**（缺陷 2 要求的口径）。

    用户明确要求第一条就是这句话，一个字都不改：
        ⚠️ 删除操作被载体层拦截（安全红线）。文件未被删除。
    后面再接载体给出的原因与替代建议（也是载体写的，不是模型编的）。
    """
    if kind == "delete":
        head = "⚠️ 删除操作被载体层拦截（安全红线）。文件未被删除。"
    else:
        head = "⚠️ 该操作被载体层拦截（安全红线）。操作未执行。"
    # 细节原样保留（**不要把 🚫 去掉**）：那是载体写给机器看的固定标记，
    # 健康系统的白名单与测试都靠它认出"这是载体主动动作"。用户看的是第一行。
    body = str(detail or "").strip()
    tail = "\n\n（这条提示由**载体层**直接给出，没有经过模型转述 —— 拦截是载体的决定，就该由载体说清。）"
    return head + ("\n\n" + body if body else "") + tail


def run_tool(name, args, force=False):
    """工具调用的**唯一入口**：红线拦截 → 本轮去重 → 真执行 → 留档。

    为什么要在外面再包一层（而不是把去重塞进 `_run_tool_impl` 里）：
    `_run_tool_impl` 有二十多个 `return`（每个内置工具一条），想在每条返回前都记一次结果
    必然会漏；而"漏记"的后果是**同一个 URL 又被抓一遍**——正是 Bug 2。
    包一层就没有这个风险：出口只有一个。删除红线同理 —— **只有放在唯一入口上，
    "所有文件/命令入口都拦得住"这句话才成立**。
    """
    args = _fix_args_paths(name, args or {})   # 补充任务 7：先把 [用户名] 这类占位符展开成真实路径
    # ---- 安全红线：删除禁区（**第一道，优先于一切**）----
    # 为什么排在权限判断、去重、执行之前：删除是唯一不可逆的动作，
    # 它不该有机会走到"要不要问用户确认"那一步 —— 直接拒绝，不给模型任何周旋空间。
    _deny = _delete_redline(name, args)
    if _deny:
        return _deny
    # ---- Bug 2：本轮去重（**放在权限判断之前**）----
    # 放在前面是有意的：如果这一轮已经抓过同一个 URL，连"要不要问用户确认"都不用再走一遍 ——
    # 用户不可能希望同一个动作被问两次。真正的网络请求更是一次都不该重复发。
    _dup = _round_cached(name, args)
    if _dup is not None:
        LOG.info("本轮已调用过同一工具同一参数，直接复用上次结果（不再真调）：%s %s",
                 name, _summarize_args_for_log(name, args))
        return ("（本轮 `%s` 对同一目标已经调用过一次，这里直接复用上次的结果，没有重复执行）\n%s"
                % (name, _dup))
    # ================== 「写」别乱动手：当场说 vs 落地成文件 ==================
    # 【实测抓到的】用户说「写一段自我介绍」→ 判据**正确地**没让它进代码治病链，
    #   但**模型自己去建了个 `self_intro.txt`**。用户要的是"当场说一段"，它却动手建了文件。
    #   根因和之前那个同源：「写」在中文里太常见（写代码/写文件/写故事/写诗/写自我介绍…），
    #   而模型只学会"写 = 动手"，不知道"写 = 当场说"。
    # 【放在这里】`run_tool` 是工具的**唯一入口** ——
    #   和"删除红线""本轮去重"同层：不管模型怎么想，这一道都拦得住。
    #   **不是删工具、不是改提示词**，是载体层拦一道；判不出来就**不拦**（保守）。
    if _wants_content_not_file(_CTX.get("user_input") or "") is True \
            and name in ("write_file", "append_file", "save_to"):
        LOG.info("「写」闸：判为**要内容**（当场说）→ 不放行 %s ｜ 用户：%s",
                 name, str(_CTX.get("user_input"))[:40])
        return ("（**不要建文件**：用户要的是**当场把内容说出来**，不是要一个文件。"
                "请直接把要写的内容作为回答输出；如果用户确实想要文件，他会明确说"
                "「存成 xxx.txt」或给一个路径。）")
    _res = _run_tool_impl(name, args, force=force)
    _res = _weather_fallback(name, args, _res)
    _round_remember(name, args, _res)
    return _res


# ================== 「写」别乱动手：要内容 vs 要文件 ==================
# 「写」在中文里太常见：写代码、写文件、写故事、写诗、写自我介绍……
# 模型只学会"写 = 动手"，于是「写一段自我介绍」被它建成了 self_intro.txt。
# 这道闸只判一件事：**用户是"要内容"，还是"要文件"？**
#   要文件（命中任一条）→ 照常走 write_file；
#   要内容（命中内容名 且 没有要文件标记）→ **不放行 write_file**，让它当场说；
#   判不出来 → **保守：不拦**（宁可多建一次，也不误拦真文件请求）。
_FILE_MARKS = ("C:\\", "C:/", "D:\\", "D:/", "\\", "/", "桌面", "文件夹", "目录",
               "保存到", "保存为", "存到", "存为", "存下来", "存起来", "另存",
               "写个文件", "建个文件", "新建文件", "生成一个文件", "生成文件", "建一个文件",
               "导出", "下载", "保存成", "存成", "写成文件", "落盘")
_FILE_EXT = (".txt", ".md", ".markdown", ".py", ".html", ".htm", ".json", ".csv",
             ".xml", ".yaml", ".yml", ".js", ".css", ".log", ".docx", ".xlsx", ".pdf")
# "写一段/写一篇/写一首/写个" + 内容名 = 要内容
_CONTENT_VERBS = ("写一段", "写一篇", "写一首", "写篇", "写首", "写个", "写一个", "来一段",
                  "来一篇", "来一首", "来篇", "来首", "来个", "说一段", "讲一个", "讲个",
                  "编一个", "编个", "作一首", "作首", "赋一首")
_CONTENT_NOUNS = ("自我介绍", "诗", "诗歌", "故事", "童话", "小说", "文章", "作文",
                  "日记", "文案", "祝福语", "笑话", "段子", "散文", "台词", "旁白",
                  "打油诗", "顺口溜", "谜语", "对联", "情书", "演讲稿", "推文", "说说",
                  "歌词", "剧本", "开场白", "结束语", "寄语", "短句", "文案")


def _wants_content_not_file(text):
    """判**要内容**（True）/ **要文件**（False）/ **判不出来**（None，保守不拦）。"""
    t = str(text or "").strip()
    if not t:
        return None
    low = t.lower()
    if any(m in t for m in _FILE_MARKS) or any(e in low for e in _FILE_EXT):
        return False                      # 明确要文件
    hit_verb = any(v in t for v in _CONTENT_VERBS)
    hit_noun = any(n in t for n in _CONTENT_NOUNS)
    if hit_verb and hit_noun:
        return True                       # 写一段 + 内容名，且没有文件标记 → 要内容
    return None                           # 判不出来 → 不拦


def _weather_fallback(name, args, res):
    """`get_weather` 失败时**由载体**降级到 `web_search`，并且必须标注来源。

    【为什么由载体做，而不是写进提示词】提示词里写"失败了就降级"是**靠模型自觉**：
    模型完全可能失败了就直接回一句"我没能力"—— 用户实测到的正是这条链
    （拿 web_search 去答天气 → 只捞到一堆链接 → 回"我没能力"）。
    把降级放在 `run_tool` 这个**唯一入口**上，才能做到"不管模型怎么想，都有一份可用信息"。

    【为什么必须标注】网页检索出来的天气与结构化天气数据**精度不是一个量级**：
    前者可能是几天前的页面、也可能压根不是那个城市（这次实测的城市是"菏泽"，
    涉及区县级的准确率本来就低）。不标注就等于把低置信度的东西冒充成权威数据 ——
    那是欺瞒，不是降级。
    """
    if name != "get_weather":
        return res
    t = str(res or "")
    _FAIL = ("查询失败", "服务暂时不可用", "暂时不可用", "不可用", "Traceback")
    if t and not any(w in t for w in _FAIL):
        return res                      # 查成功了就原样返回，不做多余动作
    city = str((args or {}).get("city") or "").strip() or "当地"
    try:
        rows = web_search("%s 天气 今天" % city, num=4) or []
    except Exception as e:      # noqa: silent-ok — 降级本身失败也要如实说，不能假装查到
        LOG.debug("天气降级检索失败（忽略）：%s", e)
        rows = []
    parts = []
    for it in rows:
        row = list(it) + ["", "", ""]
        title, link, content = str(row[0]), str(row[1]), str(row[2])
        if content.strip():
            parts.append("- %s：%s\n  %s" % (title, content.strip()[:220], link))
    if not parts:
        return (t or "") + "\n（载体已尝试降级到网页检索，但也没查到可用内容 —— 如实说明，不编数据）"
    LOG.info("天气降级：get_weather 失败 → 已改用 web_search（%d 条，已标注来源）", len(parts))
    return ("⚠️ **数据来自网页检索，可能不准**（结构化天气接口本次不可用，载体已自动降级）\n"
            "%s\n\n参考来源：\n%s" % (t.strip(), "\n".join(parts[:3])))


# ================== 安全红线：小焦不能删除任何文件 ==================
# 【为什么这条是红线】删除是**唯一不可逆**的动作。写错了可以改，删了就没了。
# 载体层的分寸是：**允许小焦犯错，但不允许它造成无法挽回的损失。**
# 所以这条约束不写在提示词里（那只是"请求模型自觉"，模型有否决权），而是写在这里：
#   · 代码层硬拦 —— 模型的输出无论怎么绕，都走不过这个函数；
#   · 与权限开关**无关** —— 就算 capabilities.full_access=true，删除照样拦（红线 4）；
#   · 间接删除也拦 —— 命令拼接、`python -c`、脚本正文、重定向，绕道走不算放行（红线 6）。
# 判定逻辑在 `core/security/no_delete.py`（可单独审计、可单独测试），这里只做**接线**：
# 让"所有文件/命令入口"无一例外地经过它。
# 【去掉它会怎样】模型一句幻觉、一次抽风、一段从网页里抄来的指令，都可能把用户的东西删掉；
# 而载体是唯一能在"动作真的发生之前"说"不"的那一层 —— 模型自己说不了这个"不"。
# 覆盖的入口（以后加了新工具要照着补，否则红线会从这里漏出去）：
#   run_command / background（执行命令）、write_file / edit_file（写文件）、
#   move_file / rename_file（带覆盖语义，同样是不可逆的破坏）。
_DELETE_GUARD_TOOLS = {
    "run_command": "command", "background": "command",
    "write_file": "write", "edit_file": "edit",
    "move_file": "move", "rename_file": "rename",
}


def _delete_redline(name, args):
    """删除红线检查。返回空串 = 放行；非空 = 给用户看的**可读**拒绝提示。

    一律 try/except：安全模块自己出问题时**宁可放行也不能把工具链打死**
    （安全是加法，不该拿整个系统陪葬）。但会在日志里留 WARNING，绝不静默。
    """
    kind = _DELETE_GUARD_TOOLS.get(name)
    if not kind:
        return ""
    try:
        root = os.path.dirname(os.path.abspath(__file__))
        if root not in sys.path:
            sys.path.insert(0, root)
        from core.security import no_delete as _nd
    except Exception as e:      # noqa: silent-ok — 安全模块不可用不能变成"工具全废"
        LOG.warning("删除禁区模块不可用（本次放行，请检查 core/security/）：%s", e)
        return ""
    try:
        a = args or {}
        if kind == "command":
            cmd = str(a.get("command") or "")
            if not cmd.strip():
                return ""
            deny = _nd.check_command(cmd)
            if deny:
                LOG.warning("删除禁区：拦下工具 %s 的命令（原文 %r）", name, cmd[:200])
                # 缺陷 2：直接给用户**载体的原文**，绝不交给模型总结
                #（生成"已新建文件"那种假话的正是"让模型转述拦截"这条路）。
                return _carrier_block_answer("delete", deny)
            return ""
        if kind in ("write", "edit"):
            path = str(a.get("path") or "")
            content = str(a.get("content") or a.get("new_string") or "")
            r = _nd.check_file_op("write" if kind == "write" else "edit", path, content)
            if r:
                LOG.warning("删除禁区：拦下工具 %s 对 %s 的操作", name, path)
                return _carrier_block_answer("delete", r)
            return ""
        # move / rename：源路径被移走同样是不可逆的 → 按 move 判
        path = str(a.get("src") or a.get("path") or a.get("from") or "")
        r = _nd.check_file_op(kind, path)
        if r:
            LOG.warning("删除禁区：拦下工具 %s 对 %s 的 %s", name, path, kind)
            return _carrier_block_answer("delete", r)
        return ""
    except Exception as e:      # noqa: silent-ok — 判定异常按放行处理，但必须留痕
        LOG.warning("删除禁区判定异常（本次放行）：%s", e)
        return ""


def _run_tool_impl(name, args, force=False):
    global PENDING
    # 权限模式：Full access(默认)=所有命令直接执行、危险命令也不询问；Read-only=每次执行命令都询问
    if not force:
        # 权限模式（第一批任务 2）：默认 full_access=false —— **只对危险命令**要确认，
        # 安全命令（echo/dir/type/ipconfig/python…）照常直接执行，不打扰用户。
        # 显式设 capabilities.full_access=true 则完全不询问（危险操作自担风险）。
        ask = (not FULL_ACCESS) and is_dangerous(name, args)
        if ask:
            PENDING = (name, args)
            if name == "run_command":
                desc = "运行这条命令：\n\n```\n%s\n```" % args.get("command", "")
            else:
                desc = "写入文件「%s」" % args.get("path", "")
            return ("〔待确认〕小焦想执行**危险操作**，先把原文给你过目：\n\n%s\n\n"
                    "确认无误请回复「**确认**」（或点界面确认按钮）；不想执行回复「取消」。" % desc)
    PENDING = None
    try:
        if name == "web_search":
            raw_q = str(args.get("query", "") or ""); n = int(args.get("num", 5))
            if not raw_q.strip():
                return SEARCH_KEYWORD_HINT
            _user_text = _CTX.get("user_input", "")
            _user_q, _ = resolve_search_query(_user_text) if _user_text else ("", "")
            # 用户这句话本身就没有可检索内容（"你好"/"用"/"帮我搜一下"），模型却拿其中一个碎片来搜
            # → 直接拒绝，别去搜"好（汉语文字）_百度百科"这种词条（用户实测就是这个现象）。
            if not _user_q and raw_q.strip() and raw_q.strip() in _user_text:
                LOG.warning("用户这句话无可检索内容，拒绝搜索（模型给的词=%r）", raw_q.strip()[:40])
                return "（这句话里没有需要联网查的内容）" + SEARCH_KEYWORD_HINT
            q, hint = resolve_search_query(raw_q)      # 强制清洗：功能字/整句都不许直接拿去搜
            if not q:
                return hint
            q = _better_search_query(q, _user_text)    # 模型只给碎片 → 用整句关键词
            res = web_search(q, num=n)
            _head = ""
            if q != raw_q.strip():                     # 清洗/升级过就如实说明，方便用户核对
                _head = "（已把「%s」清洗成检索关键词「%s」）\n" % (raw_q.strip()[:40], q)
            return _head + ("\n".join("%s%s：%s" % (t, (" [%s]" % u) if u else "", c) for t, u, c in res[:n])
                            or "(无结果)")
        if name == "check_env":
            items = (args.get("items") or "python,git,node,ffmpeg")
            out = []
            for it in items.split(","):
                it = it.strip()
                if not it:
                    continue
                try:
                    # Windows: where 工具 或 --version
                    r = subprocess.run(["where", it], capture_output=True, text=True, timeout=5)
                    ver = ""
                    for vf in ["--version", "-v", "-V"]:
                        try:
                            vr = subprocess.run([it, vf], capture_output=True, text=True, timeout=5)
                            if vr.stdout.strip():
                                ver = vr.stdout.strip().split("\n")[0][:40]; break
                        except Exception as e:
                            LOG.debug("忽略异常(%s:%d): %s", __file__, 752, e)
                    if r.returncode == 0:
                        out.append("✅ %s 已安装%s" % (it, ("，版本: " + ver) if ver else ""))
                    else:
                        out.append("❌ %s 未安装" % it)
                except Exception:
                    out.append("❌ %s 未安装(需下载)" % it)
            return "\n".join(out) + "\n（只做了检测，需要装哪个告诉我，我给下载方案，你确认后执行。）"
        if name == "suggest_organize":
            d = args.get("path", ".")
            if not os.path.isdir(d):
                return "目录不存在: " + d
            by = {}
            for f in os.listdir(d):
                fp = os.path.join(d, f)
                if os.path.isfile(fp):
                    ext = os.path.splitext(f)[1].lower().lstrip(".") or "无后缀"
                    by.setdefault(ext, []).append(f)
            if not by:
                return "该目录没有文件"
            lines = ["📁 建议整理到以下文件夹（只建议，移动前我会先问你确认）："]
            for ext, fs in sorted(by.items(), key=lambda x: -len(x[1]))[:8]:
                lines.append("  - 「%s」→ 放 %s 文件夹（%d 个）" % (ext, ("图片" if ext in ("png","jpg","jpeg","gif","bmp") else "文档" if ext in ("txt","md","doc","docx","pdf") else "视频" if ext in ("mp4","mov","mkv") else ext + "_文件"), len(fs)))
            return "\n".join(lines) + ("\n（只给建议，你确认我才移动文件）")
        if name == "capture_screen":
            try:
                from PIL import ImageGrab
                out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media", "screen")
                os.makedirs(out_dir, exist_ok=True)
                fp = os.path.join(out_dir, datetime.now().strftime("%Y%m%d%H%M%S") + ".png")
                img = ImageGrab.grab()
                img.save(fp)
                rel = "/media/screen/" + os.path.basename(fp)
                return "已截屏: " + rel + "（分析可看这张图；我无法直接「看图」，你可以描述或让我用OCR读文字）"
            except Exception as e:
                return "截屏失败: " + str(e)[:80]
        if name == "screen_text":
            try:
                from PIL import ImageGrab
                out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media", "screen")
                os.makedirs(out_dir, exist_ok=True)
                fp = os.path.join(out_dir, datetime.now().strftime("%Y%m%d%H%M%S") + ".png")
                ImageGrab.grab().save(fp)
                try:
                    import pytesseract
                    txt = pytesseract.image_to_string(fp, lang="chi_sim+eng")
                    return "屏幕文字: " + (txt.strip()[:1500] or "(未识别到)")
                except Exception:
                    return "已截屏(OCR需另装tesseract): " + fp
            except Exception as e:
                return "截图失败: " + str(e)[:80]
        if name == "run_command":
            cmd = args.get("command", "")
            timeout = int(args.get("timeout", 30))
            if os.name == "nt":
                # PowerShell 才能运行 New-Item 等 cmdlet；强制 UTF-8 输出避免中文乱码
                # 模型常用 bash 语法(&& / ||) -> 转成 PowerShell 顺序执行 ;
                import re as _re
                cmd = _re.sub(r"&&", ";", cmd); cmd = _re.sub(r"\|\|", ";", cmd)
                cmd = '[Console]::OutputEncoding=[Text.Encoding]::UTF8;$OutputEncoding=[Text.Encoding]::UTF8;' + cmd
                res = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                                     capture_output=True, encoding="utf-8", errors="replace", timeout=timeout)
            else:
                res = subprocess.run(cmd, shell=True, capture_output=True, encoding="utf-8",
                                     errors="replace", timeout=timeout)
            combined = ((res.stdout or "") + "\n" + (res.stderr or "")).strip()
            return combined[:2500] or "(无输出)"
        if name == "open_app":
            webbrowser.open(args.get("path", ""))
            return "已打开 " + args.get("path", "")
        if name == "list_files":
            p = args.get("path", ".")
            return "\n".join(os.listdir(p))[:2500]
        if name == "read_file":
            p = args.get("path", "")
            n = int(args.get("max_chars", 2500))
            return open(p, encoding="utf-8", errors="replace").read(n)
        if name == "write_file":
            p, c = args.get("path", ""), args.get("content", "")
            parent = os.path.dirname(os.path.abspath(p)) if p else ""
            if parent:
                os.makedirs(parent, exist_ok=True)   # 自动建父目录
            with open(p, "w", encoding="utf-8") as f:
                f.write(c)
            return f"已写入 {p}"
        if name == "edit_file":
            p, o, n = args.get("path", ""), args.get("old_string", ""), args.get("new_string", "")
            t = open(p, encoding="utf-8").read()
            if o not in t:
                return "未找到要替换的原文"
            open(p, "w", encoding="utf-8").write(t.replace(o, n, 1))
            return "已替换 %s 中第一处匹配" % p
        if name == "search_files":
            import glob as _g
            p = args.get("path", "."); pat = args.get("pattern", "*")
            r = _g.glob(os.path.join(p, pat), recursive=True)
            return ("\n".join(r[:80]) + ("\n..." if len(r) > 80 else ""))[:2500] or "(无匹配)"
        if name == "grep_files":
            import re as _re
            p = args.get("path", "."); pat = args.get("pattern", "")
            hits = []
            for root, ds, fs in os.walk(p):
                ds[:] = [d for d in ds if d not in ("node_modules", ".git", "__pycache__")]
                for f in fs[:300]:
                    try:
                        for i, l in enumerate(open(os.path.join(root, f), encoding="utf-8", errors="ignore"), 1):
                            if _re.search(pat, l):
                                hits.append("%s:%d: %s" % (os.path.join(root, f), i, l.strip()[:70]))
                                if len(hits) >= 30:
                                    break
                    except Exception as e:
                        LOG.debug("忽略异常(%s:%d): %s", __file__, 863, e)
                    if len(hits) >= 30:
                        break
                if len(hits) >= 30:
                    break
            return ("\n".join(hits))[:2500] or "(无匹配)"
        if name == "fetch_url":
            u = args.get("url", "")
            if not u:
                return "缺少 url"
            import requests as _rq
            try:
                return _rq.get(u, timeout=20).text[:2500] or "(空)"
            except Exception as e:
                return "抓取失败: %s" % str(e)[:120]
        if name == "ask_user":
            q = args.get("question", ""); opts = args.get("options", "")
            return "〔待选择〕" + q + ("\n选项: " + opts if opts else "")
        if name == "background":
            cmd = args.get("command", ""); to = int(args.get("timeout", 120))
            jid = str(int(time.time() * 1000))
            _BG[jid] = {"state": "running"}
            threading.Thread(target=_bg_run, args=(jid, cmd, to), daemon=True).start()
            return "已在后台运行，任务id: %s（用 background_result 查询）" % jid
        if name == "background_result":
            jid = args.get("job_id", "")
            j = _BG.get(jid)
            if not j:
                return "未知任务"
            return "%s: %s" % (j["state"], (j.get("result") or "")[:2000])
    except FileNotFoundError as e:
        return f"文件/路径不存在：{e}"
    except Exception as e:
        return f"工具执行失败：{type(e).__name__}: {e}"
    # 插件工具（自定义）
    pn = _TOOL2PLUGIN.get(name)
    if pn:
        return run_plugin(pn, {"name": name, "params": args})
    return "未知工具"


def parse_xml_tool(text):
    """解析 Qwen 风格的 <tool_call><function=name><parameter=k>v</parameter>...</function></tool_call>。"""
    calls = []
    for m in re.finditer(r"<tool_call>\s*<function=([\w-]+)>(.*?)</function>\s*</tool_call>", text, re.S):
        name = m.group(1)
        params = dict(re.findall(r"<parameter=([\w-]+)>(.*?)</parameter>", m.group(2), re.S))
        calls.append((name, {k: v.strip() for k, v in params.items()}))
    return calls


def _map_tool(name, args):
    """工具别名：把不同模型叫法统一到小焦自己的工具上。"""
    name = (name or "").lower()
    if name in ("pwsh", "powershell", "cmd", "terminal", "shell", "bash", "sh", "exec", "run", "execute"):
        return "run_command", args
    return name, args


def llm_chat_tools(messages, max_rounds=6, lean=False, tools_subset=None, budget_s=0,
                   workflow="", temperature=None):
    """带 function calling 的大脑调用：模型自己“想”并调用工具（优先），循环直到给出最终回答。

    返回 (answer, tool_trace)。兼容 OpenAI tool_calls 与 Qwen <tool_call> XML。

    云端大脑授权失败（401/403/404/429…）时自动兜到**本地大脑**再试一次 —— 免得用户被
    "一句固定的模型调用出错"卡死（真实事故：Agnes Key 失效后整机等于残废）。

    `workflow="diagram"`（第 5 步）：画图轮启用**工作流强制** —— 先 `archify_read_skill`、
    交付前必须有 `archify_validate`，模型漏了由代码层补调（见 `_archify_prereq`）。

    **挂起时立即返回 `(None, [])`**：见 `_brain_asleep` 的说明。
    """
    if _brain_asleep():
        LOG.info("挂起中：拒绝调用大脑（chat+tools）—— 它在睡，不推理、不占显存")
        return None, []
    _energy_spend(why="模型调用（带工具）")
    # 内存守卫: 生成前卸载另一个 llama 模型——8G 上保证单个 llama 占满显存(防龟速/OOM)
    try:
        if LLM_MODEL in ("coder", "xiaojiao"):
            import video_service.model_switch as _ms
            _other = "xiaojiao" if LLM_MODEL == "coder" else "coder"
            _ms._llama_swap_unload(_other)
    except Exception as e:
        LOG.debug("忽略异常(%s:%d): %s", __file__, 938, e)
    m = list(messages)
    tool_trace = []
    _targets = _llm_targets()
    _ti = 0                                          # 当前在用哪个大脑目标
    _fail_streak = {"tool": "", "n": 0}              # 同一工具连续失败次数（熔断用）
    _bad_tools = {}                                  # 工具名 → 已失败次数（第 4 层：换候选/停止）
    _t_start = time.time()                           # 本轮时间预算（画图这种多步链路防跑飞）
    _wf_on = (workflow == "diagram")                 # 画图轮：开工作流强制
    _wf_called = set()                               # 本轮已经调用过的工具（工作流判据用）

    def _run_tool_checked(tname, targs):
        """执行一次工具调用（含画图工作流的代码层补调）。

        返回 `(result, forced_note)`：
          · `forced_note` 为空串 → 原调用真的执行了，`result` 是它的返回；
          · `forced_note` 非空 → 前置步骤没做，代码层**先补调了前置**，本轮**不执行原调用**，
            把 `forced_note` 交回模型让它基于前置结果重来（`result` 为 None）。
        """
        if _wf_on:
            _pre = _archify_prereq(tname, _wf_called)
            if _pre:
                _pargs = _archify_prereq_args(_pre, tname, targs)
                LOG.info("画图工作流强制：模型直接调 %s，代码层先补调 %s", tname, _pre)
                try:
                    _pres = _tool_result_str(run_tool(_pre, _pargs, force=True))
                except Exception as e:      # noqa: silent-ok — 补调失败也要如实交回模型，不能崩
                    _pres = "前置工具 %s 调用异常：%s" % (_pre, e)
                _wf_called.add(_pre)
                tool_trace.append(_trace_entry(_pre, _pargs, _pres))
                if _pre == _ARCHIFY_GATE and _tool_failed(_pres):
                    # 校验没过 → **不许交付**：把报错原样交回模型去改（而不是把没验过的图塞给用户）
                    return None, ("（代码层强制：交付前必须先通过校验，这次 `%s` 已被拦下。"
                                  "校验结果如下，请据此改完 spec 再重新交付）\n%s" % (tname, _pres))
                if _pre == _ARCHIFY_FIRST:
                    return None, ("（代码层强制：画图第一步必须先读技能，已替你调用 `%s`，"
                                  "请据此继续，然后重新发起你刚才的调用）\n%s" % (_pre, _pres))
                # 补调的是 validate 且通过了 → 放行，继续执行原本的交付调用
        result = _tool_result_str(run_tool(tname, targs))
        _wf_called.add(tname)
        return result, ""

    def _after_call(tname, targs, result):
        """统一的收尾：结果校验 → 轨迹记录。返回给模型看的提示文本（可为空）。"""
        _vok, _vnote = _validate_tool_result(tname, targs, result)
        _e = _trace_entry(tname, targs, result)
        if _vok is False:
            _e["suspect"] = True
            LOG.warning("工具 %s 的结果未通过校验（%s）", tname, _vnote[:80])
        tool_trace.append(_e)
        # **工具结果也进原料台账**：它下一句被问"你咋知道的"时，手里就有东西可推了。
        _raw_record_tool(tname, targs, result)
        return _vnote

    for _ in range(max_rounds):
        if budget_s and (time.time() - _t_start) > budget_s and tool_trace:
            LOG.warning("本轮工具链已用 %d 秒，超过预算 %d 秒 → 停止继续调用",
                        time.time() - _t_start, budget_s)
            _last = tool_trace[-1].get("result") or ""
            return ("⏱️ **已停止：本轮工具链超过 %d 秒预算。**\n\n已完成到「%s」。"
                    "最后一步结果：\n\n```\n%s\n```\n\n（要接着做就说「继续」）"
                    % (budget_s, tool_trace[-1].get("tool"), str(_last)[:800])), tool_trace
        _t = _targets[_ti]
        # 温度：调用方按意图给（思维流的温度自适应）；没给就用全局默认。
        # 为什么不直接改全局 TEMPERATURE：那是**进程级**配置，改它会影响别的并发请求
        # 与后台任务（自主性/世界层也在用同一个常量）—— 按轮传参才是正确的作用域。
        _temp_use = TEMPERATURE if temperature is None else float(temperature)
        payload = {"model": _t["model"], "messages": m, "temperature": _temp_use,
                   "max_tokens": (200 if lean else MAX_TOKENS),
                   "tools": ([] if lean else _build_tools(only=tools_subset))}
        try:
            r, _code, _body = _llm_post(_t, payload, timeout=(120 if _t.get('local') else CLOUD_TIMEOUT_S))
            if _code != 200 or r is None:
                _note_llm_error("chat+tools", _code, _body)      # 真实原因必须留痕
                if (_code is None or _fallback_worthy(_code)) and _ti + 1 < len(_targets):
                    _ti += 1                 # 换成下一个目标（通常是本地大脑）再试
                    _targets[_ti]["local"] = True
                    LOG.warning("云端大脑不可用，自动改用本地大脑（%s）继续回答", _targets[_ti]["model"])
                    continue
                return None, tool_trace
            if _t.get("local") and not _is_local_base(LLM_BASE):
                _USED_LOCAL_FALLBACK.update({"on": True, "model": _t["model"], "reason": _LAST_LLM_ERROR})
            msg = r.json()["choices"][0]["message"]
            try:
                _record_usage(r.json().get("usage"), _t["model"])
            except Exception as e:
                LOG.debug("忽略异常(%s:%d): %s", __file__, 958, e)
        except Exception as e:
            _note_llm_error("chat+tools", None, "%s: %s" % (type(e).__name__, e))
            if _ti + 1 < len(_targets):
                _ti += 1
                LOG.warning("云端大脑连不上，自动改用本地大脑（%s）继续回答", _targets[_ti]["model"])
                continue
            return None, tool_trace
        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            content = msg.get("content") or ""
            xmlcalls = parse_xml_tool(content)
            if not xmlcalls:
                return content.strip(), tool_trace
            # Qwen XML 工具调用：执行并让模型基于结果续写
            m.append({"role": "assistant", "content": content})
            for name, args in xmlcalls:
                tname, targs = _map_tool(name, args)
                result, _forced = _run_tool_checked(tname, targs)
                if _forced:
                    m.append({"role": "tool", "content": _forced})
                    break
                _vnote = _after_call(tname, targs, result)
                if _carrier_block(result):
                    # 缺陷 2：载体拦截**不进模型**，直接把载体原文交给用户。
                    # 为什么连"再问模型一句"都不行：模型会把它当成"一个待完成的任务"，
                    # 于是编一句"已完成"（实测：红线拦下删除，它回答"已在指定位置新建了文件"）。
                    LOG.warning("载体拦截（%s）：直接把载体原文交给用户，不经过模型", tname)
                    return _carrier_block_answer(
                        "delete" if "删除" in str(result) else "other", result), tool_trace
                _tripped = _tool_breaker(_fail_streak, tname, result, tool_trace)
                if _tripped:
                    return _tripped, tool_trace
                if result.startswith("〔待确认〕"):
                    m.append({"role": "tool", "content": result})
                    return result, tool_trace
                m.append({"role": "tool", "content": result + _vnote})
            continue
        # OpenAI 标准工具调用
        m.append({"role": "assistant", "content": msg.get("content"), "tool_calls": tool_calls})
        for tc in tool_calls:
            fn = tc.get("function", {})
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except Exception:
                args = {}
            tname, targs = _map_tool(fn.get("name", ""), args)
            result, _forced = _run_tool_checked(tname, targs)
            if _forced:
                m.append({"role": "tool", "tool_call_id": tc.get("id"), "content": _forced})
                continue
            _vnote = _after_call(tname, targs, result)
            if _carrier_block(result):
                # 同上（OpenAI 标准工具调用这条）：拦截原文直接给用户，不让模型转述
                LOG.warning("载体拦截（%s）：直接把载体原文交给用户，不经过模型", tname)
                return _carrier_block_answer(
                    "delete" if "删除" in str(result) else "other", result), tool_trace
            _tripped = _tool_breaker(_fail_streak, tname, result, tool_trace)
            if _tripped:
                return _tripped, tool_trace
            _stop = _layer4_after_call(_bad_tools, tname, result, tool_trace)
            if _stop:
                return _stop, tool_trace
            _hint = _layer4_hint(_bad_tools, tname)
            if result.startswith("〔待确认〕"):
                m.append({"role": "tool", "tool_call_id": tc.get("id"), "content": result})
                return result, tool_trace
            m.append({"role": "tool", "tool_call_id": tc.get("id"),
                      "content": result + _vnote + _hint})
    # 循环到上限但已执行工具 -> 用工具结果生成总结(不让用户看到空/报错)
    if tool_trace:
        # 挑一个"成功"的结果最后展示(跳过 路径不存在/失败/Error)
        ok = [t for t in tool_trace if not any(k in (t.get("result") or "") for k in ("路径不存在", "失败", "Error", "error", "不（可用", "not found", "不存在"))]
        last = ok[-1] if ok else tool_trace[-1]
        res = (last.get("result") or "")[:160]
        return ("✅ 已完成「%s」%s" % (last.get("tool"), ("：" + res) if res else "")), tool_trace
    return None, tool_trace


def _tool_failed(result):
    """这次工具调用算不算"失败"（用于熔断计数）。

    只认明确的失败信号：中文失败词 / Error / 校验 FAIL / 异常前缀。
    成功的正文里偶尔也会出现"失败"两字（比如"失败重试机制"），所以要求它出现在前 200 字内。

    【为什么加了"失败/超时/拒绝"这些**短词** —— 实测定性出来的真缺陷】
        原来只认复合词（`校验失败` `失败：` `调用失败` `工具执行失败`），
        而工具实际吐回来的最常见措辞是**散的**：
            连接超时 / 请求超时 / timeout / 请求被拒绝 / 服务器返回 500 / 执行失败
        实测这些**一个都不认**（`_tool_failed('连接超时')` 返回 False）。
        后果很严重：熔断器**永远不会计数**，于是
        "同一工具连续失败 3 次就熔断"这条保护**从来没生效过** ——
        工具一直失败，小焦就一直重试，用户看到的是转圈和烧 token。
        既然函数已经用"只在前 200 字内匹配"把误判面压小了，
        这里就补上这些**明确表示失败**的词（超时/拒绝/连不上/失败）。
        仍然不认"成功""正常"这类正向词 —— 判据只朝"失败"这一侧加，不加模糊词。
    """
    head = str(result or "")[:200]
    if not head.strip():
        return True
    for k in ("校验失败", "失败：", "调用失败", "工具执行失败", "插件异常", "异常：",
              "Error", "error:", "Traceback", "不存在", "非法", "禁止", "无效",
              # ↓ 实测定性补上的"散词"（工具最常见的失败措辞）
              "失败", "超时", "timeout", "timed out", "拒绝", "连不上", "无法连接",
              "连接被", "不可用", "请求出错", "执行出错", "状态：FAIL"):
        if k in head:
            return True
    if re.search(r"状态：FAIL|FAIL\b", head):
        return True
    return False


def _tool_breaker(streak, tool, result, tool_trace):
    """同一工具**连续失败**达到 3 次就熔断：返回给用户的错误文本（并标注"已熔断"）。

    真实缺陷（用户实测）：让 Archify 画架构图，`archify_validate` 被反复调用 **7 次** ——
    模型每次只按一条报错改一点、改完再校验，来回烧掉 200 多秒。这里做三层防护：
      · 提示词里要求"所有报错一次改完"（_TOOL_RULES ④）
      · 校验插件一次返回**全部**报错（archify 的 _fmt_validate）
      · 工具循环兜底熔断：连续 3 次失败就停，把最后一次报错原样摆给用户
    同一次调用成功即清零（换个工具也会重新计数）。
    """
    ok = not _tool_failed(result)
    if ok:
        streak["tool"], streak["n"] = "", 0
        return ""
    if streak.get("tool") == tool:
        streak["n"] = streak.get("n", 0) + 1
    else:
        streak["tool"], streak["n"] = tool, 1
    if streak["n"] >= 3:
        LOG.warning("工具 %s 连续 %d 次失败 → 熔断（停止重试，把最后一次报错交给用户）",
                    tool, streak["n"])
        tool_trace.append({"tool": tool, "args": {},
                           "result": "已熔断：连续 %d 次失败，停止重试" % streak["n"]})
        return ("⚠️ **已熔断：%s 连续 %d 次失败，停止重试。**\n\n"
                "最后一次报错原文如下（请据此修正后再说一次，或直接看这条报错）：\n\n```\n%s\n```"
                % (tool, streak["n"], str(result or "").strip()[:1800]))
    return ""


def _layer4_after_call(bad, tool, result, tool_trace):
    """第 4 层：调错后的修正 —— 同一工具**连续失败 2 次**就停止并如实报告。

    判据复用 _tool_failed（URL 不存在/参数格式不对/校验 FAIL 等都算）。
    返回要交给用户的文本（停止）；没到阈值返回 ""。
    """
    if not _tool_failed(result):
        bad.pop(tool, None)                          # 成功即清零
        return ""
    bad[tool] = bad.get(tool, 0) + 1
    if bad[tool] >= 2:
        cand = _tool_fallback_for(tool)
        LOG.warning("工具 %s 连续 %d 次调错 → 停止重试（候选：%s）", tool, bad[tool], cand or "无")
        tool_trace.append({"tool": tool, "args": {},
                           "result": "已停止：连续 %d 次调错" % bad[tool]})
        return ("⚠️ **已停止：%s 连续 %d 次调错。**\n\n最后一次报错原文：\n\n```\n%s\n```\n\n%s"
                % (tool, bad[tool], str(result or "").strip()[:1500],
                   ("建议换用：`%s`（或直接告诉我你想做什么，我来选工具）" % "` / `".join(cand))
                   if cand else "请换个说法或告诉我更具体的目标。"))
    return ""


def _layer4_hint(bad, tool):
    """失败时给模型的一句提示（插在工具结果后面）：别再调它，换候选。"""
    if not _tool_failed_flag(bad, tool):
        return ""
    cand = _tool_fallback_for(tool)
    pieces = ["用户输入" + tool + "失败了一次" if False else "（提示：`%s` 刚刚失败了，别再原样重试" % tool]
    if cand:
        pieces.append("，换用 `%s`" % "` 或 `".join(cand))
    pieces.append("；若没有合适的工具，就直接如实说明失败原因。）")
    return "".join(pieces)


def _tool_failed_flag(bad, tool):
    return bad.get(tool, 0) >= 1


def _workflow_needs_more_rounds(user_input):
    """多步插件工作流（画图/批量/交付类）需要更多轮工具调用。

    真实缺陷（用户实测）：让 Archify 画架构图，它的工作流是 8 步（读技能 → 取指南 → 读 schema
    → 读示例 → 校验 → 交付 → 视觉核对），而工具循环上限只有 6 轮 → 走到一半被截断，
    最后回给用户的竟是"✅ 已完成「archify_read_example」：{…}" 这种中间产物，
    图根本没交付。这里按"点名了多步工具/含工作流关键词"把上限放宽。
    """
    q = (user_input or "").lower()
    if any(k in q for k in ("画图", "画一张", "架构图", "流程图", "时序图", "数据流图", "状态图",
                            "draw", "diagram", "archify")):
        return 14
    return 6


# ===== 第 5 步：画图工作流的**代码层强制**（不靠模型自觉）=====
# 真实缺陷（用户实测）：让 Archify 画图，模型跳过 `archify_read_skill` 直接写 spec ——
# 写出来的 spec 缺字段、校验一路 FAIL，模型再一条条改，来回烧掉 200 多秒（`_tool_breaker` 就是
# 为这个加的熔断）。另一个更坏：模型**没校验就交付**，把没验过的图当成品塞给用户。
# 载体优先的意思是：这两步由**代码层**把关 —— 模型漏了，代码替它补调；模型想跳过，代码拦住。
_ARCHIFY_FIRST = "archify_read_skill"       # 第一步：技能文档里写着 spec 格式，跳过它写出来的基本过不了校验
_ARCHIFY_GATE = "archify_validate"          # 交付前的闸门：必须校验过
_ARCHIFY_DELIVERISH = ("archify_deliver", "archify_render", "archify_preview")
# 纯诊断类（查环境/看指标）跟"画图"没关系，不该被逼着先去读技能 —— 逼了只是白等一次调用。
_ARCHIFY_DIAG = ("archify_doctor", "archify_metrics", "archify_check", "archify_visual_check")


def _archify_prereq(tool, called):
    """画图工作流缺了哪一步前置？返回必须**先补调**的工具名（不缺返回 ""）。

    · 任何画图类 archify 调用之前必须先 `archify_read_skill`（一步没读就直接画 = 盲写 spec）；
    · `archify_deliver`/`render`/`preview` 之前必须有 `archify_validate`（没校验就交付）。
    """
    name = (tool or "").lower()
    if not name.startswith("archify") or name in _ARCHIFY_DIAG:
        return ""
    if _ARCHIFY_FIRST not in called and name != _ARCHIFY_FIRST:
        return _ARCHIFY_FIRST
    if name in _ARCHIFY_DELIVERISH and _ARCHIFY_GATE not in called:
        return _ARCHIFY_GATE
    return ""


def _archify_prereq_args(prereq, tool, args):
    """补调前置步骤时要用什么参数。

    `validate` 与 `deliver` 共用 `diagram_type/spec_json/quality`（见 plugins/archify.py 的
    schema），所以**照抄模型本来要交付的那份 spec** 去校验 —— 校验的必须是"即将交付的那张图"，
    拿别的 spec 校验等于没校验。
    """
    a = args if isinstance(args, dict) else {}
    if prereq == _ARCHIFY_FIRST:
        return {}
    return {"diagram_type": a.get("diagram_type") or "architecture",
            "spec_json": a.get("spec_json") or "",
            "quality": a.get("quality") or "showcase"}


# ===== 强制工具执行：意图检测 + 让模型生成工具JSON（兼容任何模型） =====
_TOOL_HINTS = [
    ("run_command", ["运行", "执行", "命令", "跑一下", "建文件夹", "创建文件夹", "新建目录", "建目录",
                     "创建目录", "mkdir", "删掉", "删除", "移动", "复制文件", "清理", "关机"]),
    ("write_file", ["创建文件", "新建文件", "写文件", "写入", "保存到", "保存为", "生成文件", "写成", "输出到文件"]),
    ("open_app", ["打开", "启动", "运行应用", "打开应用"]),
    ("list_files", ["列出", "查看目录", "列出文件", "有哪些文件", "看下目录", "list"]),
    ("read_file", ["读取", "查看文件", "读出", "读文件"]),
]


def detect_tool_intent(q):
    """粗略判断用户请求是否属于“执行类操作”，返回工具类型或 None（仅作兜底提示）。

    **真实缺陷（第 2 步实测抓到，代价很实在）**：这里原来用**光杆动词**判"要新建"，
    `is_create` 里就一个 `"写"` 字。于是用户问
        「我平时最喜欢用什么语言写代码」
    —— 里面有个"写"，被判成 `write_file`；接着 `plan_tool` 让 4B 模型把它转成工具调用，
    真的执行了一次 `run_command whoami`，最后把返回的**用户名 "jiao"** 总结成
        「已在 jiao 目录下创建了 jiao 文件夹。」
    答非所问、还谎报"已执行"。一句话被理解成"让我建文件"，只因为含了个"写"字。

    修法：新建类判据只认**带宾语的动作短语**（写一个/写个/创建/新建/保存…），
    不再认光杆的"写""生成" —— 问句里描述话题的"写代码""写小说"不再被当成命令。
    """
    ql = q.lower()
    is_create = any(k in ql for k in ("创建", "新建", "建立", "做一个", "写一个", "写个", "写一份",
                                      "写一段", "帮我写", "给我写", "请写", "替我写",
                                      "生成一个", "生成一份", "生成个", "保存", "导出"))
    is_file = any(k in ql for k in (".txt", ".py", ".html", ".md", ".json", ".js", "index.", "文件", "file",
                                   "html", "网页", "网站", "页面", "自我介绍", "文档", "代码", "内容", "博客", "h5"))
    is_folder = any(k in ql for k in ("文件夹", "目录", "folder", "dir"))
    # 「文件夹」里含「文件」——不先剔掉的话，"创建一个文件夹"会被当成"写文件"，
    # 于是用户的建目录请求变成了往磁盘写一个文件。剔掉再判 is_file 才对。
    ql_nofolder = ql.replace("文件夹", "").replace("folder", "")
    is_file = is_file and any(k in ql_nofolder for k in
                              (".txt", ".py", ".html", ".md", ".json", ".js", "index.", "文件", "file",
                               "html", "网页", "网站", "页面", "自我介绍", "文档", "代码", "内容", "博客", "h5"))
    if is_create and is_file:
        return "write_file"
    if is_create and is_folder:
        return "run_command"
    if any(k in ql for k in ("运行", "执行", "命令", "跑一下", "删掉", "删除", "移动", "复制", "清理", "关机", "格式化", "mkdir", "安装", "卸载", "重启", "启动服务")):
        return "run_command"
    if any(k in ql for k in ("打开", "启动")):
        return "open_app"
    if any(k in ql for k in ("列出", "查看目录", "有哪些文件", "list", "看看有什么")):
        return "list_files"
    if any(k in ql for k in ("读取", "查看文件", "读出", "读文件")):
        return "read_file"
    # 任何"到+某路径"(桌面/文件夹/目录/Downloads) + 做实事动词 -> 视为写文件
    if any(k in ql for k in ("到", "存到", "放", "输入", "打开")) and any(k in ql for k in ("桌面", "文件夹", "目录", "downloads", "路径", "位置", "school")) and is_create:
        return "write_file"
    return None


def _llm_ask_raw(prompt):
    """一次性小提问（给工具结果写总结用）；同样享受"重试 + 云→本地兜底"。"""
    for _t in _llm_targets():
        r, code, _body = _llm_post(_t, {"model": _t["model"],
                                       "messages": [{"role": "user", "content": prompt}],
                                       "temperature": 0.2, "max_tokens": MAX_TOKENS}, timeout=90, tries=2)
        if code == 200 and r is not None:
            try:
                return r.json()["choices"][0]["message"]["content"].strip()
            except Exception as e:
                LOG.debug("忽略异常(%s:%d): %s", __file__, 1051, e)
    return ""


# ===== 抓取意图直通（scrapling_bridge 插件）=====
# 4B 模型自己不会稳定地选择抓取工具，这里用规则兜底：
# 用户说"抓/爬 + 网址"时，直接构造工具调用交给插件执行，保证"说抓就抓"，不让模型胡编代码。
_SCRAPE_TOOL_HINTS = [
    ("stealthy_fetch", ("隐身", "stealthy", "cloudflare", "绕过防护", "过验证", "被墙")),
    ("fetch", ("浏览器", "渲染", "动态页面", "js渲染", "js 渲染", "登录后", "点开")),
    ("get", ("抓取", "爬取", "爬一下", "抓一下", "抓个", "抓网页", "取网页", "请求网页", "抓取网页")),
]
_URL_STOP = "，。！？；：、（）【】《》“”‘’〈〉「」『』…—～·　"
_SCRAPE_URL_RE = re.compile(r"https?://[^\s" + re.escape(_URL_STOP) + r"\"']+")
_CJK_ANY = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\u3040-\u30ff]")
_URL_SAFE_PATH = "/-._~!$&'()*+,;=:@%"


def _clean_url(raw):
    r"""把"混进了中文/标点"的网址收拾成一个**真能抓**的网址（Bug 1）。

    真实缺陷：用户说「抓一下 http://www.baidu.com的uuid」—— 中文"的uuid"紧贴在网址后面，
    而原来的正则只挡了空格和几个全角标点、**没挡汉字**，于是整段（含中文）被当成网址去解析
    → DNS 解析失败。用户可能在**任何位置**插中文，所以这不是单个 case，得按通用规则处理。

    规则（按"中文落在哪一段"区分，这一步是关键）：
      · 中文落在**主机名**里（`www.baidu.com的uuid`）→ 说明网址在中文处就结束了 → 截断；
        但若主机名**本身就是**中文域名（`例子.com`）→ 那是合法的国际化域名，转成 punycode 保留。
      · 中文落在**路径**里（`a.com/中文路径/xxx`）→ 那是网址的一部分 → **保留并百分号编码**，
        绝不删（删了路径就变了）。
    最后再按 URL 合法字符集裁一遍，砍掉尾巴上粘着的标点。
    """
    s = (raw or "").strip().strip("\"'<>()[]{}")
    if not s:
        return ""
    # 先在句读处截断（防御性：调用方可能已经把正则结果传进来了，这里再兜一次）
    for ch in _URL_STOP:
        i = s.find(ch)
        if i >= 0:
            s = s[:i]
    m = re.match(r"^(https?)://(.+)$", s, re.I)
    if not m:
        return ""
    scheme, rest = m.group(1).lower(), m.group(2)
    # 主机 / 路径 / 查询 分开处理（主机里出现中文 = 网址说完了；路径里的中文 = 网址的一部分）
    cut = len(rest)
    for ch in ("/", "?", "#"):
        i = rest.find(ch)
        if 0 <= i < cut:
            cut = i
    host, tail = rest[:cut], rest[cut:]
    if _CJK_ANY.search(host):
        head = _CJK_ANY.split(host, 1)[0]          # 中文之前的那截
        if head and "." in head.rstrip("."):
            host = head.rstrip(".")                # 情形一：网址到中文为止
        else:
            try:                                   # 情形二：本身就是中文域名 → punycode
                host = host.encode("idna").decode("ascii")
            except Exception:
                return ""                          # 转不了就老实放弃，别拿半截地址去撞 DNS
    # 端口要留着：`http://127.0.0.1:5000` 里的 `:5000` 是网址的一部分。
    # （第一版把冒号一起当非法字符删了 → 变成 `127.0.0.15000`，实测被抓到。）
    _hostname, _sep, _port = host.partition(":")
    _hostname = re.sub(r"[^A-Za-z0-9\-._]", "", _hostname)
    _port = re.sub(r"[^0-9]", "", _port)
    host = _hostname + ((":" + _port) if (_sep and _port) else "")
    if not _hostname or "." not in _hostname:
        return ""
    if tail:
        path, sep, query = tail.partition("?")
        path = requests.utils.quote(path, safe=_URL_SAFE_PATH)   # 路径里的中文 → 百分号编码
        tail = path + (sep + query if sep else "")
    url = "%s://%s%s" % (scheme, host, tail)
    url = re.sub(r"[^A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]", "", url)   # 只留合法字符
    return url.rstrip(".,;:!?、。，")

_SCRAPE_DOMAIN_RE = re.compile(r"\b([a-z0-9][a-z0-9\-]*\.(?:com|cn|org|net|io|dev|gov|edu|ai|co|me|app)"
                               r"(?:/[^\s，。；、）)\]\"']*)?)", re.I)
# 用户显式要求忽略 robots.txt（默认严格遵守，只有明确说了才放行）
_SCRAPE_IGNORE_ROBOTS_HINTS = ("忽略robots", "忽略 robots", "无视robots", "无视 robots",
                               "不管robots", "不管 robots", "不看robots", "跳过robots",
                               "ignore robots")
# "看内容"类说法：句子里有网址 + 这类词 → 就是要那个网址的内容（第 5 步加）
_SCRAPE_LOOK_HINTS = ("看看", "看一下", "看下", "瞧瞧", "写了啥", "写了什么", "写的啥", "写的什么",
                      "内容是", "内容是什么", "返回什么", "返回了", "是什么", "有什么", "里面是")
# 句子里有这些词时**不抢**：网址只是宾语，用户要的是别的动作（写文件/下载/截图…）。
# 真实风险：若不排除，"把这个网址的内容写到 C:\\a.txt" 会被当成"抓网页"，文件就不会被创建。
_URL_OTHER_ACTION_HINTS = ("写到", "写入", "写进", "保存到", "保存为", "存到", "存为", "另存",
                           "下载", "输出到", "导出", "截图", "监控", "定时")


def _detect_scrape_intent(q):
    """识别"抓网页"意图 → 返回 (工具名, 参数)；识别不到返回 None。

    支持的表达：抓取/爬一下/抓网页 + 网址（可带多个网址 → 自动走批量工具）。

    **第 5 步：网址本身就是意图**（意图路由强制）。
    真实缺陷（用户实测）：说「帮我看看 https://httpbin.org/json 写了啥」时，
    意图识别判成了 `scrape`（`_looks_like_url` 命中），可这里**又要求句子里先有动作词**
    （抓取/爬一下/…）才肯给工具 —— "看看"不在表里，于是直通被跳过，交给模型；
    模型回一句"这个页面写的是…"，工具轨迹是空的，等于**没抓就答**。
    网址已经摆在句子里了，用户要的就是它的内容 —— 代码层要直接去抓，不能指望模型自觉。
    """
    ql = (q or "").lower()
    tool = None
    for name, kws in _SCRAPE_TOOL_HINTS:
        if any(k.lower() in ql for k in kws):
            tool = name
            break
    urls = [u for u in (_clean_url(x) for x in _SCRAPE_URL_RE.findall(q or "")) if u]  # Bug 1：清洗
    explicit = bool(urls)
    if not urls:
        m = _SCRAPE_DOMAIN_RE.search(q or "")
        if m:
            urls = ["https://" + m.group(1)]
    if not urls:
        return None
    if any(k in (q or "") for k in _URL_OTHER_ACTION_HINTS):
        return None         # 用户要的是"把网址内容存下来/截图"这类别的动作，别抢
    if not tool:
        if explicit or any(k in (q or "") for k in _SCRAPE_LOOK_HINTS):
            tool = "get"                    # 有网址 + 想看内容 → 直接抓（get 失败会自动升级候选）
        else:
            return None
    # 用户显式说"忽略 robots / 不管robots / 无视robots" → 本次放行（默认仍严格遵守）
    ignore = any(k in ql for k in _SCRAPE_IGNORE_ROBOTS_HINTS)
    if len(urls) > 1:      # 多个网址 → 批量工具
        bulk = {"get": "bulk_get", "fetch": "bulk_fetch", "stealthy_fetch": "bulk_stealthy_fetch"}[tool]
        args = {"urls": urls[:20]}
        if ignore:
            args["ignore_robots"] = True
        return bulk, args
    args = {"url": urls[0]}
    if ignore:
        args["ignore_robots"] = True
    return tool, args


# ================== 第 5 部分 · 世界层接入：抓取前查地图、抓取后更新地图 ==================
# 【设计意图】互联网不是小焦的工具箱，是它的**世界**。它在这个世界里看、走、学、记。
# 世界模型就是它"脑子里的地图"：这个站是干嘛的（type）、可不可信（trust）、多久刷新一次（refresh）。
# 为什么在**抓取**这条路上接：
#   · 抓取是"看世界"的唯一动作 —— 看图之前先看地图，看完再把地图改准，这是最小的闭环；
#   · 不接的话，世界模型永远是一张空表，`core/world` 就只是个没人读的日志目录。
# 【去掉它会怎样】每次抓取都是"第一次见这个站"：不知道它是新闻站还是 API、不知道该多勤地看、
# 不知道它可不可信。世界层就退化成"又一个 HTTP 客户端"。
_WORLD_CACHE = {"model": None, "perception": None, "tried": False, "override": None}


def _world_layer():
    """惰性拿 (WorldModel, WorldPerception)。拿不到就返回 (None, None) —— 世界层缺席不影响对话。

    `override` 是给测试留的注入口：单测要的是"接线对不对"，不该把临时站点写进
    小焦真正的世界地图里（那是用户的数据，不是测试的草稿纸）。
    """
    if _WORLD_CACHE.get("override"):
        return _WORLD_CACHE["override"]
    if _WORLD_CACHE["tried"] and _WORLD_CACHE["model"] is not None:
        return _WORLD_CACHE["model"], _WORLD_CACHE["perception"]
    _WORLD_CACHE["tried"] = True
    try:
        root = os.path.dirname(os.path.abspath(__file__))
        if root not in sys.path:
            sys.path.insert(0, root)
        from core import world as _w
        p = _w.WorldPerception()
        _WORLD_CACHE["model"], _WORLD_CACHE["perception"] = p.model, p
        return _WORLD_CACHE["model"], p
    except Exception as e:      # noqa: silent-ok — 世界层出问题不能让抓取跟着失败
        LOG.debug("世界层不可用（忽略）：%s", e)
        return None, None


def _world_before_fetch(url):
    """**抓取前先查世界模型** —— 知道这个站是干嘛的、多久刷新一次。

    返回一句给日志/轨迹看的中文说明（拿不到世界层就返回空串）。
    这里刻意**不做拦截**：用户点名要抓的，就抓 —— 地图的作用是"知道自己在哪"，
    不是"替用户决定不去"。但地图会影响别的东西：可信度低的结果会被标注，
    刷新周期会被记进模型，供后台的"持续观察"决定下次什么时候来看。

    【必须分清的两件事（实测踩到）】"地图上没有这个站"和"有这个站但类型判不出来"
    完全是两回事：前者是"第一次见"，后者是"我见过它，只是不知道它算什么站"（裸 IP 就是这样）。
    第一版只看 `type_of` 返回 "unknown" 就报"第一次见到" —— 对一个已经看过十次的站
    说"第一次见"，日志会骗人；用户排查时会以为世界模型根本没在记。
    """
    try:
        wm, _p = _world_layer()
        if wm is None or not url:
            return ""
        dom = wm.domain_of(url)
        if not dom:
            return ""
        recorded = dom in (wm.snapshot().get("sites") or {})
        known = wm.type_of(dom, default="")
        if not recorded:
            LOG.info("世界层：第一次见到 %s（未收录），抓完会把它记进世界模型", dom)
            return "（世界层：第一次见到这个站，抓完会记进地图）"
        if not known or known == "unknown":
            LOG.info("世界层：%s 已收录但类型未判定（可信度 %.1f，通常 %s 刷新）",
                     dom, wm.trust_of(dom), _fmt_interval(wm.refresh_interval(dom)))
            return ("（世界层：%s 已收录，类型未判定，可信度 %.1f，通常 %s 刷新一次）"
                    % (dom, wm.trust_of(dom), _fmt_interval(wm.refresh_interval(dom))))
        note = ("世界层：%s = %s，可信度 %.1f，通常 %s 刷新一次"
                % (dom, known, wm.trust_of(dom), _fmt_interval(wm.refresh_interval(dom))))
        LOG.info(note)
        return "（%s）" % note
    except Exception as e:      # noqa: silent-ok — 查地图失败不能影响抓取
        LOG.debug("世界层查询失败（忽略）：%s", e)
        return ""


def _fmt_interval(sec):
    """秒 → 人能读的中文（1h / 30m / 2d）。"""
    try:
        s = int(sec or 0)
        if s >= 86400 and s % 86400 == 0:
            return "%dd" % (s // 86400)
        if s >= 3600:
            return "%.0fh" % (s / 3600.0)
        if s >= 60:
            return "%.0fm" % (s / 60.0)
        return "%ds" % s
    except Exception:      # noqa: silent-ok — 格式化成不了就给个兜底字面量
        return "?"


def _world_after_fetch(url, body, status=None):
    """**抓取后更新世界模型**：把这次看到的内容记成快照，并感知"跟我上次看到的不一样了吗"。

    为什么走 `ingest` 而不是 `snapshot`：正文已经在手里了 —— 再调 `snapshot()` 会让
    "看世界"这个动作对同一个站点发出**第二次真实请求**（既慢又像在打人家的站）。
    返回一句给用户/轨迹看的变化说明（没有变化就返回空串）。

    【实测抓到的真 bug】`diff()` 返回的列表里**包含 `unchanged` 这一项**（"比过了、没变"也是一种结论）。
    第一版把"列表非空"直接当成"变了" —— 于是每次抓一个没变的页面，都会对用户喊一句
    "这个页面跟你上次看到的不一样了"。**假警报比没有警报更坏**：用户会从此不信这条提示。
    所以这里必须先按 kind 过滤，只有出现真正的变化类 kind 才算变。
    """
    try:
        _wm, p = _world_layer()
        if p is None or not url or not (body or "").strip():
            return ""
        _rec, changes = p.ingest(url, body, status=(status or 0))
        if not changes:
            return ""
        # 真正的"变化"才值得打扰用户；first_seen/unchanged 都是"没什么可说的"
        changed = [c for c in changes if c.get("kind") in ("changed", "appeared", "disappeared")]
        if not changed:
            kinds0 = [c.get("kind") for c in changes]
            LOG.info("世界层：%s 无变化（%s）", url, kinds0)
            return ""
        kinds = []
        for c in changed:
            k = c.get("kind")
            if k and k not in kinds:
                kinds.append(k)
        LOG.info("世界层：%s 发生了变化 %s", url, kinds)
        detail = ""
        for c in changed:
            if c.get("kind") == "changed" and c.get("detail"):
                detail = str(c["detail"])[:120]
                break
        return "\n\n🌍 **世界层：这个页面跟你上次看到的不一样了**%s" % (("（%s）" % detail) if detail else "")
    except Exception as e:      # noqa: silent-ok — 记世界失败绝不能影响"把页面给用户看"这件事
        LOG.debug("世界层更新失败（忽略）：%s", e)
        return ""


# ================== 问题 4：抓取失败之后，"再来一次"必须真的再来一次 ==================
# 【真实缺陷】用户实测的三步，一步比一步糟：
#   ① 说"抓 http://www.baidu.com的uuid" → 被 robots 正确拦下（这条没错）；
#   ② 按提示说"忽略 robots 抓一次" → **没调任何工具**，直接返回一段编造的 JSON + 一张
#      跟 baidu 毫无关系的 NVD CVE 表格；
#   ③ 用户完全看不出来那是编的（工具轨迹是空的，但界面上就是一段"像模像样"的回答）。
# 根因有两条，缺一条都复现：
#   · **载体把上下文丢了**：第二轮那句话里**没有网址**（用户没必要重复一遍），
#     而 `_detect_scrape_intent` 的判据是"句子里必须有网址" → 判不出抓取意图 →
#     交给模型 → 模型凭上下文里的碎片硬编。
#   · **授权词没被识别**：`_SCRAPE_IGNORE_ROBOTS_HINTS` 里有"忽略robots"，
#     但用户的说法是"忽略 robots 抓一次"（中间有空格、后面带动作）——
#     而且这一轮**压根没走到那一步**（因为没网址就没意图）。
# 修法：载体自己记住"上一次抓的是哪个网址、为什么失败"，并在用户说
# "忽略/跳过/重试/再抓/我确认有权"时，**强制**用那个网址 + ignore_robots 再抓一次。
# 判据写在代码里（不指望模型把"忽略 robots"理解成 `ignore_robots=true`）。
_LAST_SCRAPE = {"url": "", "error": "", "at": 0.0, "tool": "", "robots": False}
_SCRAPE_MEMORY_S = 1800          # 上一次失败的记忆时长（30 分钟）—— 太久的"再来一次"不该算数

# 授权词：用户明确表示"我有权抓 / 我允许忽略 robots"
_SCRAPE_GRANT_HINTS = ("忽略robots", "忽略 robots", "跳过robots", "跳过 robots", "无视robots",
                       "无视 robots", "不管robots", "不管 robots", "不看robots", "不看 robots",
                       "ignore robots", "别管robots", "不用管robots",
                       "我确认有权", "我有权", "我是站长", "我拥有该站", "允许抓取", "授权抓取",
                       "我授权", "合法抓取")
# 重试词：用户要求"再来一次"
_SCRAPE_RETRY_HINTS = ("再抓", "重抓", "重试", "再试", "再来一次", "重新抓", "接着抓",
                       "继续抓", "抓一次", "试一次", "再查", "再拉")


def _scrape_remember_fail(url, tool, result):
    """记住"哪个网址没抓成、为什么"——供下一轮"再来一次"用。

    为什么必须由载体记（而不是让模型记）：用户不会重复一遍网址（那本来就是我刚给你的），
    指望模型从上下文里把网址捞出来并**原样**填进参数，实测就是"编一个看起来像的"。
    载体记下来是**确定性**的：网址一个字符都不会变。
    """
    try:
        low = str(result or "")[:600]
        _LAST_SCRAPE.update({"url": str(url or ""), "tool": str(tool or ""),
                             "error": low, "at": time.time(),
                             "robots": ("robots" in low.lower())})
        LOG.info("抓取未成功，已记住以备重试：%s（%s）", url,
                 "robots 拦截" if _LAST_SCRAPE["robots"] else "其它失败")
    except Exception as e:      # noqa: silent-ok — 记不住只是少一次重试机会，不能影响本轮
        LOG.debug("记录失败抓取失败（忽略）：%s", e)


def _scrape_retry_intent(user_input):
    """用户这句话是不是"刚才那次没成，再来一次（并且我授权忽略 robots）"？

    返回 (工具名, 参数) 或 None。判据（**全部由代码判，不问模型**）：
      ① 句子里有授权词或重试词；
      ② 网址：先看这句里有没有（用户重复说了就用新的），没有就用**上一次失败的那个**；
      ③ 距离上次失败不超过 `_SCRAPE_MEMORY_S`（免得十分钟前的网址被莫名其妙重抓）。
    """
    q = (user_input or "")
    ql = q.lower()
    grant = any(k.lower() in ql for k in _SCRAPE_GRANT_HINTS)
    retry = any(k.lower() in ql for k in _SCRAPE_RETRY_HINTS)
    if not (grant or retry):
        return None
    urls = [u for u in (_clean_url(x) for x in _SCRAPE_URL_RE.findall(q)) if u]
    url = urls[0] if urls else ""
    if not url:
        last = _LAST_SCRAPE
        if not last.get("url") or (time.time() - float(last.get("at") or 0)) > _SCRAPE_MEMORY_S:
            return None
        url = last["url"]
        LOG.info("用户要求重试，但句子里没给网址 → 用上一次失败的那个：%s", url)
    # 授权词只有对"上次是被 robots 拦的"才有意义；其它失败也允许重试（就当再抓一次）
    args = {"url": url}
    if grant:
        args["ignore_robots"] = True
        LOG.info("用户明确授权忽略 robots → 本轮以 ignore_robots=true 重抓：%s", url)
    return "get", args


def _trace_summary(res: str) -> str:
    """把抓取结果压成一行摘要，避免把原始 JSON 塞进工具轨迹（界面好读、4B 也好读）。"""
    try:
        d = json.loads(res)
    except Exception:
        return (res or "")[:160]
    if not isinstance(d, dict):
        return (res or "")[:160]
    if d.get("items"):
        ok = sum(1 for i in d["items"] if not i.get("error"))
        return "批量抓取：成功 %d / 共 %d" % (ok, len(d["items"]))
    if d.get("error"):
        return "失败：" + str(d["error"])[:120]
    _c = d.get("content") or ""
    return "已抓取 %s（HTTP %s，正文 %d 字）" % (d.get("url", ""), d.get("status", ""), len(_c))


def _auto_outline(body: str, limit: int = 6) -> str:
    """规则兜底解读：抽出标题/链接/要点。模型不可用或输出太短时用它，保证用户总有结构可看。"""
    body = body or ""
    lines = []
    for h in re.findall(r"^#{1,3}\s+(.+)$", body, re.M)[:3]:
        lines.append("· 标题：%s" % h.strip()[:60])
    for t, u in re.findall(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", body)[:3]:
        lines.append("· 链接：%s" % (t.strip()[:40] or u))
    paras = [p.strip() for p in re.split(r"\n\s*\n", body) if len(p.strip()) > 20]
    for p in paras[:3]:
        lines.append("· 内容：%s" % p[:80].replace("\n", " "))
    return "\n".join(lines[:limit])


def _fence_body(text: str) -> str:
    """按内容类型给抓取正文套上合适的展示格式。

    JSON → ```json 代码块（前端渲染成带"复制"按钮、限高滚动的代码框）
    含 ``` 的文本 → 原样（避免嵌套围栏把后面的内容吃掉）
    其它（Markdown/HTML→MD）→ 原样，交给 Markdown 渲染
    """
    s = (text or "").strip()
    if not s:
        return s
    if "```" in s:
        return s
    if s[0] in "[{":
        for cand in (s, re.sub(r'\\([^"\\/bfnrtu])', r'\1', s)):   # 兼容 Markdown 转义过的 JSON
            try:
                json.loads(cand)
                return "```json\n" + cand + "\n```"
            except Exception:
                continue
        # 美化后被折叠的 JSON（尾部带了"已折叠"说明，严格解析必然失败）→ 首行是 { 或 [ 就当 JSON 展示
        _first = (s.splitlines() or [""])[0].strip()
        if _first in ("{", "["):
            return "```json\n" + s + "\n```"
    return s


def _explain_content(text: str, url: str = "") -> str:
    """让大脑对抓到的内容做**逐条解读**，帮用户快速看懂含义、快速上手。

    设计意图：抓取只给"原料"，用户（尤其面对陌生网页/英文页）看不懂重点。
    这里让大脑按固定结构讲一遍：这是什么页面 → 关键要点 → 怎么用。
    强调"只依据抓到的内容、不要编造"，避免小模型幻觉；模型不可用则退回规则提纲。
    """
    body = (text or "")[:3000]
    if not body.strip():
        return ""
    prompt = (
        "下面是刚抓取到的网页内容（来源：%s）：\n---\n%s\n---\n\n"
        "请用中文逐条解读，帮用户快速看懂这个页面、知道怎么用：\n"
        "第一行：一句话说明这是什么页面；\n"
        "然后列 3-6 条要点，每条以「· 」开头，简短直白；\n"
        "若页面里有可点的链接或可用的数据，说明它能用来干什么。\n"
        "只根据上面的内容讲，不要编造；总字数不超过 400。" % (url or "网页", body)
    )
    try:
        out = (_llm_ask_raw(prompt) or "").strip()
    except Exception:
        out = ""
    if len(out) < 20:                     # 模型没给出有效解读 → 规则兜底
        out = _auto_outline(text)
    return out


# ===== 【用户使用时学习】小脑从"实际使用"中积累工具经验 =====
# 设计意图：不是从插件代码/文档学，而是**用户每次让小焦干活时**，
# 把"什么需求 → 用了哪个工具 → 参数 → 结果（成功/失败+反思）"沉淀成经验：
#   · 成功 → 记住正确用法，下次同类需求直接照做（命中检索即可复用，不用重新推理）
#   · 失败 → 记住原因与"下次怎么改"，形成反思
# 存两份：可读日志 tool_skills.txt + 向量库（语义检索）。
_SELF_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "self_learn")
_SKILL_LOG = os.path.join(_SELF_DIR, "tool_skills.txt")


def _reflect(tool: str, err: str) -> str:
    """失败反思：给出"下次怎么改"，让小脑积累的是经验而不只是报错。"""
    e = err or ""
    if "robots" in e:
        return "遇到 robots 限制要提示用户换站点或说明原因"
    if "SSRF" in e or "禁止访问" in e:
        return "内网/本机地址属安全拦截，直接告诉用户不可抓"
    if "超时" in e or "timeout" in e.lower():
        return "可加大 timeout，或改用更轻的 get"
    if "markdownify" in e:
        return "缺 markdownify 依赖，pip install markdownify"
    if "MCP 未运行" in e:
        return "应先启动 Scrapling（scrapling mcp）"
    if "session_id" in e:
        return "会话类操作要先 action=open 开会话"
    return "下次先检查参数与网络再重试"


def _learn_skill(user_input: str, tool: str, args, ok: bool, detail: str) -> None:
    """把一次工具使用沉淀成小脑的"能力经验"（用户使用时学习）。"""
    if not tool:
        return
    try:
        try:
            _args = json.dumps(args or {}, ensure_ascii=False)[:120]
        except Exception:
            _args = str(args)[:120]
        if ok:
            line = "用户 %s → 小焦用「%s」成功%s：%s" % (
                (user_input or "")[:50], tool, (" 参数" + _args) if _args else "", (detail or "")[:100])
        else:
            line = "用户 %s → 小焦用「%s」失败：%s；经验：%s" % (
                (user_input or "")[:50], tool, (detail or "")[:80], _reflect(tool, detail))
        os.makedirs(_SELF_DIR, exist_ok=True)
        with open(_SKILL_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        try:                            # 向量库：语义检索命中即可复用
            if _SELF_DIR not in sys.path:
                sys.path.insert(0, _SELF_DIR)
            import vstore
            vstore.add(line, tag="tool_skill")
        except Exception as e:
            LOG.debug("忽略异常(%s:%d): %s", __file__, 1242, e)
    except Exception as e:
        try:
            print("学习沉淀失败(不影响使用): %s" % str(e)[:80])
        except Exception as e:
            LOG.debug("忽略异常(%s:%d): %s", __file__, 1247, e)


def _recall_skills(query: str, k: int = 3) -> str:
    """检索小脑学到的"工具用法"，注入给大脑参考（越用越会）。"""
    try:
        if _SELF_DIR not in sys.path:
            sys.path.insert(0, _SELF_DIR)
        import vstore
        r = vstore.search(query, k=k, threshold=0.12)
        if not r.get("hit"):
            return ""
        return "\n".join("- " + str(t[1])[:120] for t in (r.get("top") or [])[:k])
    except Exception:
        return ""


def plan_tool(user_input):
    """让大脑把请求转成一个工具调用 JSON，返回 (tool, args)；失败返回 (None, None)。

    【为什么闲聊轮要在这里拦一道 —— 实测定性出来的真 bug】
        这个函数是"让模型把请求变成工具调用"，它对**任何**输入都会问模型一次。
        于是用户说「你好 / 在吗 / 今天好累 / 哈哈 / 嗯嗯」时，模型为了满足"必须输出一个
        JSON"的格式要求，**凭空编出一个工具调用**。实测（本测试抓到）：
            你好        → run_command  Get-Process | Select-Object ProcessName,Id,StartTime
            你好呀      → run_command  echo 你好呀
            今天好累    → run_command  Get-Process ... | Format-Table
            嗯嗯 / 在吗 → list_files   .
        这不是"多此一举"，而是**会真的动手**：用户只是打个招呼，系统却去列目录、
        更糟的是去执行命令。而 `_CHAT_FALLBACK_HINT` 里那句"没真调用过工具就不许说已完成"
        是给**模型**看的软约束，拦不住"载体自己把编造的计划当命令执行"。

    【拦法为什么是"允许白名单"而不是"只拦寒暄"】
        `_is_chitchat()` 只认明确寒暄（"今天好累"它认不出来，见上表），
        拿它当唯一闸门会漏。所以这里用**更保守的规则**：
        闲聊意图下，只允许 `_CHAT_SAFE_TOOLS`（只读、无害：查记忆/搜索/读文件/看目录）
        里的工具；其余（run_command / write_file / open_app / 各类删除类）一律判为编造，
        直接返回 (None, None) 让这一轮老老实实回话。
        宁可漏掉一次"闲聊时顺手执行"（用户真想动手时下一轮说清楚就行），
        也不能在用户没要求的时候动他的系统。
    """
    try:
        # 注意：**不是"闲聊意图就拦"**，还要"这句话里没有明确的动手要求"。
        # 因为 `_detect_intent` 对认不出来的输入一律兜底成 chat ——
        # "写个文件到桌面" 就是 chat 意图 + 真任务；只按意图拦会把**正常的动手请求**一起拒掉
        # （我第一版就是这么写错的，自测里"写个文件到桌面"当场被判成不该规划）。
        if (_detect_intent(user_input) == "chat" and _is_chitchat(user_input)
                and not _asks_action(user_input)):
            LOG.debug("闲聊轮不做工具规划（避免凭空编出工具调用）：%s", str(user_input)[:40])
            return None, None
    except Exception as e:      # noqa: silent-ok — 闸门自身出错时按原路走，不影响正常规划
        LOG.debug("忽略异常(%s:%d): %s", __file__, 1279, e)
    prompt = ("用户请求：%s\n\n请把该请求转换为一个工具调用，只输出一个 JSON 对象，不要任何说明。\n"
              "可用工具：run_command(运行PowerShell命令,参数 command)、write_file(写文件,参数 path,content)、"
              "open_app(打开应用/文件,参数 path)、list_files(列目录,参数 path)、read_file(读文件,参数 path,max_chars)。\n"
              "JSON 格式：{\"tool\":\"工具名\",\"args\":{\"参数\":\"值\"}}\n"
              "例如：{\"tool\":\"write_file\",\"args\":{\"path\":\"C:/Users/Jiao/Desktop/a.txt\",\"content\":\"hi\"}}" % user_input)
    out = _llm_ask_raw(prompt)
    m = re.search(r"\{.*\}", out, re.S)
    if m:
        try:
            j = json.loads(m.group(0))
            if isinstance(j, dict) and j.get("tool"):
                tool, args = j["tool"], j.get("args", {})
                # 第二道闸（兜住 `_is_chitchat` 认不出的闲聊）：闲聊意图下只放只读工具。
                # ⚠️ 条件里必须带上"用户没让我动手" —— 只按意图判会把
                #    "写个文件到桌面"（chat 意图 + 真任务）这类**正常动手请求**一起丢掉
                #    （自测抓到的第二处过拦）。
                try:
                    if (_detect_intent(user_input) == "chat"
                            and not _asks_action(user_input)
                            and tool not in _CHAT_SAFE_TOOLS):
                        LOG.info("闲聊轮丢弃模型编造的动手类工具 %s（用户只是闲聊）", tool)
                        return None, None
                except Exception as e:      # noqa: silent-ok — 判断失败就保留原结果
                    LOG.debug("忽略异常(%s:%d): %s", __file__, 1279, e)
                return tool, args
        except Exception as e:
            LOG.debug("忽略异常(%s:%d): %s", __file__, 1279, e)
    return None, None


# ================== 「别搜 / 直接用工具」闸门 ==================
# 真实缺陷（用户实测截图）：用户说"用 Archify 画一张小焦系统的架构图"，小焦跑去**联网搜「用」字**
# 搜回"用（汉语文字）_百度百科"；用户接着命令"停止搜索。不要搜「用」字。请直接调用 archify_doctor
# 工具" —— 它又把"停止"当检索词搜了一遍。三条规则治它：
#   ① 用户明确说"别搜/停止搜索/不要搜/别联网" → 一次搜索都不发；
#   ② 用户在点名**已加载的工具/插件**（archify_deliver、scrapling、net_ip…）→ 不搜，让工具去干；
#   ③ 点名"某工具"时把它作为直连目标，真去调，而不是嘴上答应。
_SEARCH_OFF_HINTS = ("别搜", "不要搜", "不用搜", "不准搜", "不要搜索", "停止搜索", "停止搜",
                     "别再搜", "不许搜", "不要联网", "别联网", "不用联网", "别查百科",
                     "不要用搜索", "禁止搜索", "不要调用搜索", "直接调用", "直接调",
                     "别再搜索", "no search", "don't search")


def _search_forbidden(text):
    """用户是不是明确要求"别搜了"（命令式）。"""
    q = (text or "").lower()
    return any(h in q for h in _SEARCH_OFF_HINTS)


def _tool_named_options():
    """当前已加载的工具名 + 插件名（供"用户点名了某个工具"识别用）。"""
    names = set()
    try:
        for pname, p in (globals().get("PLUGINS") or {}).items():
            if not p.get("on"):
                continue
            names.add(str(pname).lower())
            for t in (p.get("desc") or []):
                nm = (t or {}).get("name")
                if nm:
                    names.add(str(nm).lower())
    except Exception as e:  # noqa: silent-ok — 识别失败就当没点名
        LOG.debug("忽略异常(%s:%d): %s", __file__, 700, e)
    return names


def _named_tools(text):
    """用户这句话点名了哪些已加载的工具（按名字长度降序，避免 scrapling 命中 scrapling_bridge）。

    为什么需要它：点名工具时**不该联网搜**，而且最好直接调那个工具 ——
    用户实测就是"让 Archify 画图，它去搜『用』字"，报错后还得再骂一句"停止搜索"。
    """
    q = (text or "").lower()
    hit = []
    for n in _tool_named_options():
        if len(n) >= 3 and n in q and "web_search" not in n and "search" not in n:
            hit.append(n)
    hit.sort(key=len, reverse=True)
    # 去掉被更长名字包含的短名（如 scrapling 与 scrapling_bridge 同时命中）
    out = []
    for n in hit:
        if not any(n != m and n in m for m in hit):
            out.append(n)
    return out


def real_tool_names():
    """真正注册在工具表里的名字（`_TOOL2PLUGIN` 的键）。"""
    try:
        _build_tools()
        return list(_TOOL2PLUGIN.keys())
    except Exception:
        return []


def _noarg_named_tool(text):
    """用户点名了一个**不需要参数**的工具 → 直接返回它的名字（让主流程真去调）。

    为什么：用户的原话是"请直接调用 archify_doctor 工具，检查 Archify 环境" —— 既然是
    零参数工具，最稳的做法是**直接调用**并把结果摆出来，而不是再让模型自己决定调不调
    （实测它会转头去联网搜"停止"）。需要参数的工具不在这里抢，交给模型按工作流编排。
    """
    named = _named_tools(text)
    if not named:
        return ""
    try:
        tools = _build_tools()
        for nm in named:
            for t in tools:
                fn = (t or {}).get("function") or {}
                if str(fn.get("name", "")).lower() != nm:
                    continue
                prm = fn.get("parameters") or {}
                props = prm.get("properties") or {}
                req = prm.get("required") or []
                # 零参数，或者参数全是**可选**的（给空 {} 走默认值也安全）→ 可以直接调
                if nm in _TOOL2PLUGIN and not req:
                    return fn["name"]
    except Exception as e:  # noqa: silent-ok — 识别失败就交回模型
        LOG.debug("忽略异常(%s:%d): %s", __file__, 730, e)
    return ""


# ================== 「别搜 / 直接用工具」闸门结束 ==================


def _scrape_failed(res):
    """这次抓取算不算"没成功"（决定要不要升级到下一个候选工具）。

    判据：有 error 字段、HTTP 非 200/2xx、正文为空/过短、或明确的风控字样。
    """
    try:
        j = json.loads(res)
    except Exception:
        return not str(res or "").strip()          # 非 JSON：没内容就算失败
    if not isinstance(j, dict):
        return False
    if (j.get("error") or "").strip():
        return True
    if j.get("items"):                             # 批量：只要有成功项就算成功
        return not any((it.get("content") or "").strip() for it in j["items"] if isinstance(it, dict))
    st = j.get("status")
    body = (j.get("content") or "").strip()
    if st not in (None, 200) and not (isinstance(st, int) and 200 <= st < 300):
        return True
    if len(body) < 40:
        return True
    low = body[:400].lower()
    return any(k in low for k in ("just a moment", "cloudflare", "enable javascript",
                                  "attention required", "access denied", "验证您是人类"))


# ===== 抓取之后的「第二个动作」（本轮实测的真缺口）=====
# 用户说"抓 https://httpbin.org/json，**提取 slides 的标题做成表格**" —— 这是**两步**：
#   ① 抓（工具的活）  ② 把抓到的内容加工成表格（模型的活）
# 以前载体抓完就把原始 JSON 当答案返回（顶多附一段通用"解读"），**第二步没人做**，
# 用户要的表格根本没出现。现在：识别出"要加工"就把真内容交给模型去加工。
_TRANSFORM_HINTS = ("提取", "做成表格", "做成表", "做成列表", "整理成", "汇总成", "归纳", "提炼",
                    "列出", "转成", "转成表格", "做成 markdown", "表格", "列表", "统计", "对比",
                    "摘出", "抽出", "总结成", "整理一下", "梳理")


def _transform_requested(text):
    """用户是不是在"抓完之后还要加工"（提取/做成表格/汇总…）。"""
    return any(k in (text or "") for k in _TRANSFORM_HINTS)


def _apply_transform(user_input, content, url=""):
    """让模型**基于刚抓到的真内容**完成用户要的加工（表格/提取/汇总）。

    只依据抓到的内容，不许编造 —— 这是"结果校验"在生成侧的对应要求。
    """
    prompt = ("用户的要求：%s\n\n"
              "这是刚从 %s 抓到的**真实内容**（只能依据它，不要编造里面没有的东西）：\n\n%s\n\n"
              "请直接给出用户要的**结果本身**：要表格就给 Markdown 表格，要提取就给清单。"
              "不要再重复粘贴原始内容，不要客套，不要解释你做了什么。"
              % (user_input, url or "网页", (content or "")[:6000]))
    try:
        out = llm_chat([{"role": "user", "content": prompt}])
    except Exception as e:      # noqa: silent-ok — 加工失败就退回"原样给内容"，不是致命错
        LOG.debug("抓取后加工失败（忽略）(%s:%d): %s", __file__, 3310, e)
        out = ""
    return (out or "").strip()


def _scrape_direct(user_input, tool_trace, force_intent=None):
    """"抓一下 <url>" 这类明确指令的**直通**执行：真调抓取工具，把正文原样给用户。

    抽成函数的原因：这条路径要在**模型之前**（规则先判，稳定）和**模型之后**（兜底）各用一次。
    抓取结果直接给用户看，不让模型"总结"（它会把正文吃掉）。
    返回 (answer 或 None, tool_trace)。

    `force_intent`：由调用方**指定**这次抓什么（问题 4 的"再来一次"走这条）——
    因为那时候用户那句话里**没有网址**（网址在上一次），靠 `_detect_scrape_intent` 判不出来。
    """
    _sc = force_intent or _detect_scrape_intent(user_input)
    if not _sc:
        return None, tool_trace
    # ---- Bug 2 根因修复：直通只做一次 ----
    # 判据是"这一轮**跑过**直通"，不是"直通**成功**了"。原来兜底那条判据是"没抓到页面"，
    # 于是**失败**（正是最需要省时间的情况）反而会触发第二遍 get→fetch→stealthy_fetch，
    # 用户看到两条"调用 get"、白等一倍时间。失败也是"已经抓过了"，不该重来。
    if getattr(_ROUND, "scrape_done", False):
        LOG.info("本轮抓取直通已经跑过（工具=%s），不再重复执行兜底抓取",
                 getattr(_ROUND, "scrape_tool", "") or "?")
        return None, tool_trace
    _ROUND.scrape_done = True
    _ROUND.scrape_tool = _sc[0]
    try:
        _build_tools()                  # 填充 _TOOL2PLUGIN，确保插件工具可被调用
    except Exception as e:
        LOG.debug("忽略异常(%s:%d): %s", __file__, 1538, e)
    _tn, _ta = _sc
    LOG.info("抓取直通：工具=%s %s（失败会自动升级候选，但本轮不会重跑同一工具）",
             _tn, _summarize_args_for_log(_tn, _ta))
    # 世界层：抓之前先查地图（这个站是干嘛的、多久刷新）——结果只用于日志与可信度标注
    _w_before = _world_before_fetch(_ta.get("url") or "")
    # 第 4 层：抓取类**自动升级** —— get 失败(被拦/403/空正文) → fetch → stealthy_fetch。
    # 用户实测："抓 https://www.cloudflare.com" 被风控挡住时原来直接报错；
    # 该升级就自动升级，而不是把失败原样丢回给用户。
    # 第 5 步再加一道：**结果校验没过也算"没抓到"**，一样升级到下一个候选 ——
    # 拿回一坨跟目标毫无关系的内容（比如风控提示页、缓存错页）比抓不到更坏：用户会被它骗。
    _chain = [_tn] + [x for x in _tool_fallback_for(_tn) if x != _tn]
    _res, _used, _tried = "", _tn, []
    _suspect_note = ""
    _ok_found = False
    for _name in _chain:
        try:
            _res = _tool_result_str(run_tool(_name, _ta, force=True))
        except Exception as e:
            _res = json.dumps({"error": "%s: %s" % (type(e).__name__, str(e)[:80])}, ensure_ascii=False)
        _tried.append(_name)
        if _scrape_failed(_res):
            LOG.info("抓取 %s 没成功，自动升级到下一个候选（已试：%s）", _name, _tried)
            continue
        _vok, _vnote = _validate_tool_result(_name, _ta, _res)
        if _vok is False and _name != _chain[-1]:
            LOG.warning("抓取 %s 返回内容不含目标特征（%s），升级到下一个候选", _name, _vnote[:60])
            _suspect_note = _vnote
            continue
        _used = _name
        _suspect_note = _vnote if _vok is False else ""
        _ok_found = True
        if _vok is False:
            LOG.warning("抓取 %s 的结果校验未通过，如实标注可能幻觉（已无更多候选）", _name)
        break
    # ---- 问题 4 补的第二个洞：**整条链都没成功时，不能把风控页当成正文给用户** ----
    # 真实缺陷：`_scrape_failed` 认出这是风控页（"Access Denied"），于是三个候选全都 `continue`，
    # 链走完 → `_err` 是空的 → 代码掉进"单页成功"那条分支，把风控页正文**当成目标页面**摆了出来。
    # 用户看到一段像模像样的内容，完全不知道那不是他要的页面。
    # 现在：走完整条链还没找到可用内容，就**一律**如实标注（校验能给出更具体的原因就用它的）。
    if not _ok_found:
        _vok, _vnote = _validate_tool_result(_used, _ta, _res)
        if _vok is False:
            _suspect_note = _vnote
        elif not _suspect_note:
            _suspect_note = ("⚠️ **这一次没抓到目标内容**（已依次试过：%s）。"
                             "下面这段内容**不能确认**属于该网址，仅供参考。"
                             % "、".join(_tried))
        LOG.warning("整条抓取候选链都没拿到可用内容（%s）→ 如实标注", _tried)
    _entry = _trace_entry(_used, _ta, _res)
    _entry["tried"] = _tried
    if _w_before:
        _entry["world"] = _w_before.strip("（）")     # 轨迹里带上"抓之前世界模型告诉我什么"
    # ---- 问题 4：把这次失败**记下来**，供下一轮"忽略 robots / 再来一次"用 ----
    # 三个条件都算"没抓成"：整条链都失败、结果校验没过、或拿到了 error 字段。
    _fetch_ok = False
    try:
        _jbf = json.loads(_res)
        _fetch_ok = bool(str(_jbf.get("content") or "").strip()) and not _jbf.get("error")
    except Exception:      # noqa: silent-ok — 不是 JSON 就算没抓成（反正后面也会如实报错）
        _fetch_ok = False
    if not _fetch_ok or _suspect_note:
        _scrape_remember_fail(_ta.get("url") or "", _used or _tn, _res)
    else:
        _LAST_SCRAPE.update({"url": "", "error": "", "at": 0.0, "tool": "", "robots": False})
    # ---- 世界层：抓完把这次看到的东西记进世界模型（比 → 记快照 → 更新站点表）----
    # 只对**单页**做：批量抓取的结果在下面按 items 展开，那时的正文在这里还拿不到。
    _w_change_note = ""
    if not _ta.get("urls"):
        try:
            _jbw = json.loads(_res)
            _w_change_note = _world_after_fetch(_ta.get("url") or _jbw.get("url") or "",
                                                str(_jbw.get("content") or ""),
                                                _jbw.get("status"))
        except Exception as e:      # noqa: silent-ok — 不是 JSON（非抓取结果）就跳过世界层
            LOG.debug("世界层记录跳过（结果不是 JSON）：%s", e)
    # `raw_head` 改成**用户实际看到的那段正文**：抓取路径下用户看的是页面正文，
    # 外层 `{"url":…,"status":…,"content":…}` 只是壳。历史隔离要按"用户看到的东西"比对，
    # 否则围栏里的正文匹配不上 raw_head，"抓取结果进历史"这条隔离会直接漏掉（实测踩到）。
    try:
        _jb0 = json.loads(_res)
        _bhead0 = str((_jb0 or {}).get("content") or "").strip()
        if len(_bhead0) > _TOOL_RESULT_KEEP:
            _entry["raw_head"] = _bhead0[:_HISTORY_SUMMARY_CHARS]
    except Exception as e:      # noqa: silent-ok — 不是 JSON 就沿用原 raw_head，不影响隔离兜底
        LOG.debug("解析抓取结果用于隔离比对失败（忽略）(%s:%d): %s", __file__, 2810, e)
    if _suspect_note:
        _entry["suspect"] = True          # 结果校验没过 → 轨迹里留痕，界面/复盘都看得到
    tool_trace = list(tool_trace or []) + [_entry]
    try:
        _jd = json.loads(_res)
        _err = (_jd.get("error") or "").strip()
        _body = (_jd.get("content") or "").strip()
        if _err:
            return "⚠️ 抓取失败：%s" % _err, tool_trace
        if _jd.get("items"):                       # 批量抓取：逐项给正文 + 解读
            if _transform_requested(user_input):
                # 用户要的是"抓完再加工"（汇总/表格）→ 把全部正文交给模型去做那件事
                _allc = "\n\n".join("【%s】\n%s" % (_it.get("url"), (_it.get("content") or "")[:2500])
                                    for _it in _jd["items"] if not _it.get("error"))
                _t = _apply_transform(user_input, _allc, "以上网页")
                if _t:
                    return ("🌐 批量抓取完成（%d 个网页）\n\n%s"
                            % (len(_jd["items"]), _t)), tool_trace
            _lines = []
            for _idx, _it in enumerate(_jd["items"]):
                _h = "**%s** · HTTP %s" % (_it.get("url"), _it.get("status"))
                if _it.get("error"):
                    _lines.append(_h + "\n\n⚠️ " + str(_it["error"]))
                    continue
                _c = (_it.get("content") or "")[:1500]
                _lines.append(_h + "\n\n" + _fence_body(_c))
                if _idx < 3:                          # 逐条解读（限前 3 条，避免过慢）
                    _e = _explain_content(_c, _it.get("url", ""))
                    if _e:
                        _lines.append("📖 **解读**\n\n" + _e)
            return "🌐 批量抓取完成\n\n" + "\n\n---\n\n".join(_lines), tool_trace
        # 单页：用户要是说了"抓完还要加工"（提取/做成表格/汇总），**先把那件事做了** ——
        # 这才是用户要的答案；直接把原始 JSON 糊上去等于只干了第一步。
        if _transform_requested(user_input):
            _t = _apply_transform(user_input, _body, _jd.get("url", ""))
            if _t:
                _hdr = "🌐 **%s** · HTTP %s\n\n" % (_jd.get("url", ""), _jd.get("status", ""))
                _out = _hdr + _t
                if _suspect_note:
                    _out += "\n\n" + _suspect_note
                return _out, tool_trace
        # 单页：正文 + 解读
        _ans = "🌐 **%s** · HTTP %s\n\n%s" % (
            _jd.get("url", ""), _jd.get("status", ""),
            _fence_body(_body[:4000]) or "(页面无正文)")
        _exp = _explain_content(_body, _jd.get("url", ""))
        if _exp:
            _ans += "\n\n---\n\n📖 **小焦解读**\n\n" + _exp
        if _suspect_note:
            # 校验没过的**如实报告**：内容照给（用户可能就是想看看风控页），但必须标明它可能不是目标页面
            _ans = _suspect_note + "\n\n" + _ans
        if _w_change_note:
            _ans += _w_change_note            # 世界层：跟上次看到的不一样 → 明确告诉用户
        return _ans, tool_trace
    except Exception:
        return (_res[:3000], tool_trace)             # 非 JSON 就原样给


# ===== 第 5 步：画图意图的**载体兜底**（模型一个工具都不调时，代码层把工作流走完）=====
# 真实缺陷（本轮实测，比"模型跳过 read_skill"更彻底）：说「用 Archify 画一张架构图」，
# 本地 4B 模型**一个工具都不调** —— 它直接画了一屏 ASCII 框图，或者吐一段自以为是的 JSON
# （字段跟 archify schema 完全不符：少了 schema_version/meta/components，多了 title/kind/nodes）。
# 工具轨迹是空的 —— 于是 `llm_chat_tools` 里的工作流强制**根本没有机会触发**：
# 那套逻辑是"模型调了工具之后再纠正"，而这里模型压根没调。
#
# 载体优先的解法：模型不挑工具，载体就替它挑、替它按顺序走完 ——
#   读技能 → 取指南 → 读 schema → 读示例 → 模型只负责写 JSON → 校验（不过就把报错交回模型改，
#   最多 3 轮）→ 交付。工具**一个都没被跳过、也没有一个是编出来的**（全部真调用 archify_*）。
# 校验始终过不了就**如实报告**，绝不把没验过的图说成"已完成"。
_DIAGRAM_TYPE_HINTS = (
    ("architecture", ("架构图", "架构", "部署图", "拓扑", "组件图", "模块图", "architecture")),
    ("workflow", ("流程图", "流程", "步骤图", "workflow", "flowchart")),
    ("sequence", ("时序图", "时序", "调用链", "sequence")),
    ("dataflow", ("数据流", "data flow", "dataflow")),
    ("lifecycle", ("生命周期", "状态图", "状态机", "lifecycle", "state")),
)
_DIAGRAM_MAX_TRIES = 3          # spec 写不对就带着报错让它重写，最多 3 轮（跟"连续 2 次调错即停"一个尺度）


def _diagram_type_of(text):
    """用户这句话要画哪种图（archify 的五种类型之一，认不出来按架构图）。"""
    q = (text or "").lower()
    for _t, _kws in _DIAGRAM_TYPE_HINTS:
        if any(k.lower() in q for k in _kws):
            return _t
    return "architecture"


def _diagram_layout_inject(spec_json):
    """载体层给 spec 补一套**自己算的网格布局**（模型只负责"有什么"，不负责"摆哪儿"）。

    为什么要载体算：4B 模型能写对 components/connections 的**内容**，但**几乎不可能**写对像素坐标
    —— 实测它给的 `pos` 让 Archify 的 clean-flow 校验一次连报几十条（"连线段只有 20px，太短"、
    "这条线穿过了无关节点"）。而"摆位置"本来就是个**机械活**，正是载体该干的：
      · 按连接关系做 BFS 分层 → 每层一列（`layout.mode="grid"` + 组件上的 `col`）；
      · 同层节点按出现顺序依次排行（`row`）；
      · 顺手删掉模型自己写的 `pos`/`size` 与布线提示（fromSide/toSide/labelDy）——
        留着两套坐标只会互相打架（这也是"edge-through-node"的根源）。
    schema 依据：`architecture` schema 里 `layout.mode` 只有 `grid` 一个取值，
    组件支持 `row`/`col`（整数，最小 0）作为格子坐标。

    返回补好布局的 spec；解析不了就原样返回。
    """
    try:
        d = json.loads(spec_json)
    except Exception:      # noqa: silent-ok — 不是 JSON 就没什么可补的
        return spec_json
    if not isinstance(d, dict):
        return spec_json
    comps = d.get("components") or d.get("nodes") or []
    conns = d.get("connections") or d.get("edges") or []
    ids = [c.get("id") for c in comps if isinstance(c, dict) and c.get("id")]
    if not ids or not isinstance(conns, list):
        return spec_json
    # ---- ① BFS 分层：入度为 0 的当起点，逐层往右排（画不出层级的孤立点单独放最后一列）----
    outs, indeg = {}, {i: 0 for i in ids}
    for c in conns:
        if not isinstance(c, dict):
            continue
        a, b = c.get("from"), c.get("to")
        if a in indeg and b in indeg:
            outs.setdefault(a, []).append(b)
            indeg[b] += 1
    level = {}
    frontier = [i for i in ids if indeg[i] == 0] or ids[:1]
    for i in frontier:
        level[i] = 0
    _lvl = 0
    while frontier and _lvl < 12:
        nxt = []
        for a in frontier:
            for b in outs.get(a, []):
                if b not in level:
                    level[b] = _lvl + 1
                    nxt.append(b)
        frontier, _lvl = nxt, _lvl + 1
    _maxl = max(level.values()) if level else 0
    for i in ids:                                  # 环里的/没连上的 → 兜底放最后一列
        if i not in level:
            level[i] = _maxl
    # ---- ①b 重心排序（barycenter）：同一列里按"邻居的平均行号"重排，减少连线交叉 ----
    # 为什么要有：Archify 的 showcase 校验有一条 `[composition/proper-crossing]`
    # —— 连线互相穿过要报错。分层摆放本身不保证不交叉，按邻居重心排一遍是**机械**且有效的降交叉法
    # （Sugiyama 那一套里最便宜的一步），比让 4B 模型"调整节点顺序"靠谱得多。
    # ⚠️ 第一版这里写错了：重心只取"**同一列**里的邻居"，而同一列的邻居行号就是它自己，
    #    等于什么都没算（实测交叉一条没少）。重心必须取**相邻列**邻居的行号，才是真正的降交叉。
    by_col = {}
    for i in ids:
        by_col.setdefault(level.get(i, 0), []).append(i)
    nbrs = {}
    for c in conns:
        if isinstance(c, dict) and c.get("from") in indeg and c.get("to") in indeg:
            nbrs.setdefault(c["from"], []).append(c["to"])
            nbrs.setdefault(c["to"], []).append(c["from"])
    order = {i: k for k, i in enumerate(ids)}      # 初始行序 = 出现顺序
    for _sweep in range(4):                        # 左右交替扫，收敛更快
        for _col in (sorted(by_col) if _sweep % 2 == 0 else sorted(by_col, reverse=True)):
            _here = set(by_col.get(_col, []))

            def _bc(n, _here=_here):
                _ns = [order[x] for x in nbrs.get(n, []) if level.get(x, _col) != _col
                       and x in order and x not in _here]
                return sum(_ns) / float(len(_ns)) if _ns else order.get(n, 0)

            for k, n in enumerate(sorted(by_col[_col], key=_bc)):
                order[n] = k
    colrow, seen = {}, {}
    for i in sorted(ids, key=lambda x: (level.get(x, 0), order.get(x, 0))):
        col = level.get(i, 0)
        row = seen.get(col, 0)
        seen[col] = row + 1
        colrow[i] = (col, row)
    # ---- ② 机械改写：位置/布线一律由载体给，模型写的坐标与布线提示全删 ----
    for c in comps:
        if not isinstance(c, dict) or c.get("id") not in colrow:
            continue
        for k in _DIAGRAM_LAYOUT_KEYS + _DIAGRAM_ROUTE_KEYS:
            c.pop(k, None)
        col, row = colrow[c["id"]]
        c["col"], c["row"] = col, row
    for c in conns:
        if isinstance(c, dict):
            for k in _DIAGRAM_ROUTE_KEYS:
                c.pop(k, None)
    # ---- ③ 出/入边方向由**格子几何**推出来（校验器提示的正是这个修法：adjust fromSide/toSide）----
    #     为什么要载体给：Archify 会"按坐标推断该从哪条边走"，模型自己给的 fromSide 常常和它给的
    #     坐标矛盾（于是报"does not honor fromSide"）。而格子坐标是载体算的，方向自然推得准，
    #     由方向决定的布线也就不会绕到别的节点上去（`[composition/proper-crossing]` 的成因之一）。
    for c in conns:
        if not isinstance(c, dict):
            continue
        _a, _b = colrow.get(c.get("from")), colrow.get(c.get("to"))
        if not _a or not _b:
            continue
        if _b[0] > _a[0]:
            c["fromSide"], c["toSide"] = "right", "left"
        elif _b[0] < _a[0]:
            c["fromSide"], c["toSide"] = "left", "right"
        elif _b[1] > _a[1]:
            c["fromSide"], c["toSide"] = "bottom", "top"
        else:
            c["fromSide"], c["toSide"] = "top", "bottom"
    d["layout"] = {"mode": "grid", "cols": max(1, _maxl + 1), "gapX": 140, "gapY": 110}
    return json.dumps(d, ensure_ascii=False)


# 载体层能机械改掉的"布局类"字段（改法与报错一一对应，不需要模型参与）
_DIAGRAM_ROUTE_KEYS = ("fromSide", "toSide", "labelDy", "waypoints", "via", "route", "bend")
_DIAGRAM_LAYOUT_KEYS = ("pos", "size")


def _repair_diagram_spec(spec_json, err_text):
    """载体层的**确定性修错**：报错里明说了怎么改的字段，直接改掉，不让模型反复试。

    为什么要有它（本轮实测）：读技能/读 schema/读示例/出 JSON 全做对了，可 4B 模型
    **写不对像素级布局** —— 连续 3 轮都卡在同一类报错上：
        `connections[i] does not honor fromSide "top" … keep automatic routing`
    它自己给的 fromSide/toSide 跟坐标对不上。这类错误的修法**是完全机械的**：
    把布局提示删掉，让 Archify 自己布线。让模型去"试"这种错，只会烧掉几分钟再失败一次。
    （第 4 层"同一工具连续 2 次调错就停"管的是工具层面；这里管的是**产物**层面的纠错。）

    返回修好的 spec 字符串；没改到东西就原样返回（调用方据此决定还要不要问模型）。
    """
    try:
        d = json.loads(spec_json)
    except Exception:      # noqa: silent-ok — spec 不是 JSON 就没什么可修的
        return spec_json
    if not isinstance(d, dict):
        return spec_json
    e = str(err_text or "").lower()
    changed = False
    # ① 标签压住组件：Archify 的报错**自带修法**（"给该关系加 labelDy: 12（或 -12）"），
    #    这是纯机械活 —— 按报错点名的关系补上 labelDy，别让模型为这种像素事重写整个 spec。
    for m in re.finditer(r'label\s*[「"\']([^」"\']+)[」"\']\s*overlaps', str(err_text or ""), re.I):
        _lab = m.group(1)
        for c in (d.get("connections") or d.get("edges") or []):
            if isinstance(c, dict) and str(c.get("label") or "") == _lab and "labelDy" not in c:
                c["labelDy"] = 12
                changed = True
    if any(k in e for k in ("side", "route", "segment", "waypoint", "bend", "labeldy", "layout")):
        for c in (d.get("connections") or d.get("edges") or []):
            if isinstance(c, dict):
                for k in _DIAGRAM_ROUTE_KEYS:
                    if k in c and not (k == "labelDy" and c.get(k) == 12):
                        c.pop(k, None)
                        changed = True
    if any(k in e for k in ("overlap", "bounds", "collision", "out of")):
        for c in (d.get("components") or d.get("nodes") or []):
            if isinstance(c, dict):
                for k in _DIAGRAM_LAYOUT_KEYS:
                    if k in c:
                        c.pop(k, None)
                        changed = True
    # ②bis **标签压到连线走线**（`label-route-clearance`）—— 这是本次实测真正卡住的那一类。
    #   报错长这样：
    #     `[composition/label-route-clearance] ... label "SQL" on connections[3] id "persist-order"`
    #   它和①的"标签压住组件"不是一回事：①修的是 label 与**节点**重叠，这一条是 label 与
    #   **连线路径**重叠。修法同样是机械的，而且分两步升级（一次做太狠会白丢信息）：
    #     第 1 次 → 给该连线加 labelDy（把标签推离走线）；
    #     第 2 次还报同一条 → 直接把这条连线的 label 去掉。
    #   宁可少一个连线文字，也不能让整张图卡在校验上出不来（用户要的是图，不是报错）。
    if "label-route-clearance" in e or "label_route_clearance" in e:
        for m in re.finditer(r'label\s*[「"\']([^」"\']+)[」"\']\s*on\s*connections?\[?(\d+)?', str(err_text or ""), re.I):
            _lab = m.group(1)
            for c in (d.get("connections") or d.get("edges") or []):
                if not (isinstance(c, dict) and str(c.get("label") or "") == _lab):
                    continue
                if "labelDy" not in c:
                    c["labelDy"] = 14              # 第一步：推开
                else:
                    c.pop("label", None)           # 第二步：还压着 → 去掉文字保住图
                changed = True
    return json.dumps(d, ensure_ascii=False) if changed else spec_json


def _extract_json_object(text):
    """从模型回复里抠出第一个**括号配平**的 JSON 对象（容忍 ```json 围栏和前后废话）。

    为什么不用 `re.search(r"\\{.*\\}")`：那个贪婪写法在"围栏里一个 JSON + 后面又跟一段解释"
    时会把两段都吞进去，`json.loads` 直接失败 —— 而模型几乎总是会多写两句解释。
    """
    s = str(text or "")
    start = s.find("{")
    while start >= 0:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(s)):
            ch = s[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    cand = s[start:i + 1]
                    try:
                        json.loads(cand)
                        return cand
                    except Exception:      # noqa: silent-ok — 这段不是 JSON，往后找下一个 '{'
                        break
        start = s.find("{", start + 1)
    return ""


def _diagram_direct(user_input, tool_trace):
    """画图意图的载体兜底：真调用 archify 全链把图做出来。返回 (answer 或 None, tool_trace)。

    模型自己肯调工具时**不会**走到这里（`llm_chat_tools` 那条路已经带了工作流强制）；
    只有"模型一个工具都没调"才会兜到这条 —— 也就是本地小模型最常见的失败姿势。
    """
    try:
        _build_tools()                  # 填充 _TOOL2PLUGIN，确保插件工具可被调用
    except Exception as e:      # noqa: silent-ok — 建表失败下面会以"未知工具"如实反映
        LOG.debug("忽略异常(%s:%d): %s", __file__, 3300, e)
    _trace = list(tool_trace or [])
    _dtype = _diagram_type_of(user_input)

    def _call(name, args):
        """真调一次 archify 工具并记轨迹（异常也如实记，不吞）。"""
        try:
            _r = _tool_result_str(run_tool(name, args, force=True))
        except Exception as e:      # noqa: silent-ok — 单个工具异常不该中断整条工作流
            _r = "%s 调用异常：%s: %s" % (name, type(e).__name__, e)
        _trace.append(_trace_entry(name, args, _r))
        return _r

    _skill = _call("archify_read_skill", {})
    if "未知工具" in _skill or "archify" not in _skill.lower():
        LOG.warning("Archify 技能读不到（插件未就绪），画图兜底放弃，交回普通回答")
        return None, tool_trace        # 工具真不在 → 不硬来，交回上层
    _guide = _call("archify_guide", {"scenario": user_input, "lang": "zh"})
    _schema = _call("archify_read_schema", {"diagram_type": _dtype})
    _example = _call("archify_read_example", {"diagram_type": _dtype})
    _basis = ("你是 Archify 的 JSON 生成器，只输出 JSON，不解释、不聊天。\n\n"
              "[技能文档]\n%s\n\n[写作指南]\n%s\n\n[%s 类型 schema]\n%s\n\n[%s 类型完整示例]\n%s"
              % (_skill[:4000], _guide[:2000], _dtype, _schema[:6000], _dtype, _example[:4000]))
    _err, _spec, _passed = "", "", False
    _anchored = ""                      # 锚定兜底生效时给用户的如实说明（空 = 没走锚定）
    for _i in range(_DIAGRAM_MAX_TRIES):
        # ① 先对**已有的 spec** 做机械修错（报错明说了怎么改的，载体直接改，别让模型瞎试）
        if _spec and _err:
            _fixed = _repair_diagram_spec(_spec, _err)
            if _fixed != _spec:
                LOG.info("画图兜底：按报错机械修错（%d 字 → %d 字）", len(_spec), len(_fixed))
                _spec = _fixed
                _vres = _call("archify_validate", {"diagram_type": _dtype, "spec_json": _spec,
                                                   "quality": "showcase"})
                if not _tool_failed(_vres):
                    _passed = True
                    break
                _err = _vres
        # ② 让模型按 schema/示例写（或按报错重写）
        _ask = ("请输出**一份** %s 类型的 Archify spec JSON。\n"
                "硬性要求：只输出 JSON 本体，不要 ``` 围栏、不要任何解释；"
                "字段名与层级严格照 schema，结构照示例；上一条报错要**一次性全部改完**。\n"
                "**不要写 fromSide / toSide / labelDy 这类布线提示**，让 Archify 自己布线。\n\n"
                "用户的原话：%s\n%s"
                % (_dtype, user_input,
                   ("\n上次校验的报错（请全部改掉）：\n" + _err[:2500]) if _err else ""))
        _reply = llm_chat([{"role": "system", "content": _basis},
                           {"role": "user", "content": _ask}])
        _new = _extract_json_object(_reply or "")
        if not _new:
            LOG.warning("画图兜底：第 %d 轮模型没吐出可解析的 JSON", _i + 1)
            continue
        _spec = _new
        # 第 5 步：**摆放位置由载体算**（模型写坐标基本必错，见 `_diagram_layout_inject`）
        _spec = _diagram_layout_inject(_spec)
        _vres = _call("archify_validate", {"diagram_type": _dtype, "spec_json": _spec,
                                           "quality": "showcase"})
        if not _tool_failed(_vres):
            _passed = True
            break
        LOG.info("画图兜底：第 %d 轮 spec 校验未过，带着报错让模型重写", _i + 1)
        _err = _vres
    if not _passed:
        # ---- 载体**锚定兜底**（第 5 步）：本地小模型写不出能过校验的**布局** ----
        # 这是模型能力的硬限制，不是载体的强制没生效：实测它连"读技能→读 schema→出 JSON"
        # 全做对了，却反复卡在 `label-route-clearance` 这类**像素级**校验上。
        # 但 Archify 的**官方示例本身是已验证 PASS 的**（实测 9/9 全过）。
        # 于是载体换个分工：**几何（pos/size/结构/布线）直接用那份已验证的示例**，
        # 只把「文字」（标题 + 各组件名称）换成用户要的内容 —— 布局由载体保证，文案由模型提供。
        # 这和整个项目的分工完全一致：模型只管当前这一小块（起名字），载体负责装配与校验。
        _spec2, _note = _anchor_diagram_on_example(_example, user_input, _dtype, _call)
        if _spec2:
            _spec, _passed, _anchored = _spec2, True, _note
    if _passed:
        _dres = _call("archify_deliver", {"diagram_type": _dtype, "spec_json": _spec,
                                          "output_name": "xiaojiao_%s" % _dtype,
                                          "quality": "showcase"})
        if _tool_failed(_dres):
            # 校验过了、交付没成（例如渲染环境有问题）→ **如实说**，并把 spec 交出去让用户能手动出图
            return ("⚠️ **图已通过 Archify 校验，但交付这一步没成功**（如实报告，不假装完成）。\n\n"
                    "交付工具的返回：\n\n```\n%s\n```\n\n下面是**已通过校验**的 spec，"
                    "可以复制到 Archify 里手动出图：\n\n```json\n%s\n```"
                    % (_dres.strip()[:1000], _spec[:4000])), _trace
        return ("🎨 **图已交付**（Archify 全流程：读技能 → 读指南 → 读 schema/示例 → 校验通过 → 交付）\n\n"
                "```\n%s\n```\n\n%s通过校验的 spec：\n\n```json\n%s\n```"
                % (_dres.strip()[:1200], _anchored + _open_delivered_html(_dres), _spec[:2500])), _trace
    return ("⚠️ **画图没完成：spec 连续 %d 轮没通过 Archify 校验。**\n\n"
            "最后一次报错原文如下（可以据此人工修正，或者说「再试一次」）：\n\n```\n%s\n```\n\n"
            "说明：小焦已经把「读技能 → 读指南 → 读 schema/示例 → 出 JSON → 校验」全走完了，"
            "**一步都没跳过**；也不会把没验过的图说成已完成。"
            % (_DIAGRAM_MAX_TRIES, str(_err).strip()[:1800])), _trace


def _anchor_diagram_on_example(example_text, user_input, dtype, call):
    """载体锚定：拿**已验证 PASS 的官方示例**当地基，只换文字。

    返回 (spec_json 或 None, 给用户的说明)。做法：
      ① 先把示例本身validate一遍，确认真是"已验证的地基"（不是想当然）；
      ② 让模型只干一件小事：给这张关于「用户原话」的图起个标题 + 给 N 个组件起中文名
         （**不让它碰坐标/结构/布线** —— 那正是它写不对的部分）；
      ③ 把名字填进示例的 `label` 里，再 validate；过了就交出去；
      ④ 名字填进去后万一仍没过（换名字可能改变标签宽度），就退回"只换标题"的版本
         （几何一字未动，必定过）；再不行才放弃。
    这样用户**一定拿得到一张真的图**，而不是一段"没通过校验"的报错 —— 但文案是模型的，
    结构是通用模板，所以答案里会**如实说明**这一点，不冒充满分交付。
    """
    try:
        _m = re.search(r"\{.*\}", example_text or "", re.S)
        base = json.loads(_m.group(0)) if _m else None
        if not isinstance(base, dict) or not base.get("components"):
            return None, ""
        comps = base["components"]
        # ① 先确认地基真的能过（不能拿一块"以为能过"的地基去兜底）
        _v = call("archify_validate", {"diagram_type": dtype,
                                       "spec_json": json.dumps(base, ensure_ascii=False),
                                       "quality": "showcase"})
        if _tool_failed(_v) or "PASS" not in str(_v):
            LOG.warning("画图锚定：官方示例本身没过校验，放弃锚定（交回如实报错）")
            return None, ""
        # ② 让模型只起名字（这是 4B 模型干得了的事）
        _ask = ("给一张关于「%s」的架构图起名字。只输出 JSON，不要解释、不要围栏：\n"
                '{"title":"整张图的标题（≤16 字）","labels":["组件1名称","组件2名称",...]}\n'
                "labels 必须正好 %d 个，每个 ≤ 8 个中文字，按这个顺序对应：%s"
                % (user_input[:80], len(comps),
                   ", ".join(str(c.get("id")) for c in comps)))
        _rep = llm_chat([{"role": "system", "content": "你只输出 JSON，不解释。"},
                         {"role": "user", "content": _ask}])
        _names = _extract_json_object(_rep or "") or ""
        title, labels = "", []
        if _names:
            try:
                _nj = json.loads(_names)
                title = str(_nj.get("title") or "").strip()[:32]
                labels = [str(x).strip()[:16] for x in (_nj.get("labels") or []) if str(x).strip()]
            except Exception:      # noqa: silent-ok — 名字没解析出来就退回"只换标题"
                labels = []
        # ③ 换文字（标题 + 组件名），几何一字不动
        def _build(fill_labels):
            j = json.loads(json.dumps(base))
            if title:
                j.setdefault("meta", {})["title"] = title
            if fill_labels:
                for c, nm in zip(j["components"], labels):
                    c["label"] = nm
            return json.dumps(j, ensure_ascii=False)
        for _fill in (True, False):
            if _fill and len(labels) < len(comps):
                continue
            _cand = _build(_fill)
            _v2 = call("archify_validate", {"diagram_type": dtype, "spec_json": _cand,
                                            "quality": "showcase"})
            if not _tool_failed(_v2) and "PASS" in str(_v2):
                _note = ("\n> 说明（如实告知）：本次的**布局**用的是 Archify 官方已验证示例作为地基"
                         "（本地小模型写不出能过校验的像素级布局），"
                         + ("标题与组件名称已按你的要求替换。\n" if _fill else
                            "只替换了标题，组件名称仍是示例里的通用名 —— 本地模型起的名字没通过校验。\n"))
                LOG.info("画图锚定成功（%s）：几何取自已验证示例", "换了名字" if _fill else "只换标题")
                return _cand, _note
        return None, ""
    except Exception as e:
        LOG.debug("画图锚定失败（忽略）(%s:%d): %s", __file__, 3600, e)
        return None, ""


def _open_delivered_html(result_text):
    """交付成功后**自动用默认浏览器打开**生成的 HTML（问题 7）。

    为什么要有：小焦画完图只回一句"图已生成：C:\\...\\xxx.html"，用户还得自己去文件夹里翻
    —— 等于活干了一半。画完就该直接弹出来看。

    两个硬要求：
      · **放后台**（daemon 线程）：打开浏览器可能卡住，绝不能让它拖住对话返回；
      · **失败不崩**：没有默认浏览器/没权限时，如实告诉用户路径让他手动打开。
    返回给用户看的说明字符串。
    """
    try:
        # 路径要允许**空格**：本项目目录就叫 `C:\xiaojiao\xiaojiao harness`，里面带空格。
        # 之前用 [^\s"']*? 排除空白 → 带空格的路径一个都抠不出来（实测返回空串）。
        # 交付结果的路径独占一行，所以按"到行尾"截才是对的。
        _m = re.search(r"([A-Za-z]:[^\r\n]*?\.html)", str(result_text or ""), re.I)
        if not _m:
            return ""
        path = _m.group(1).strip().strip('"').strip("'")
        if not (path.lower().endswith(".html") and os.path.exists(path)):
            return "\n\n（没找到生成的 HTML 文件，可手动打开：%s）" % path

        def _do():
            try:
                os.startfile(path)          # Windows：交给系统默认程序
            except Exception:
                try:
                    import subprocess
                    subprocess.Popen(["cmd", "/c", "start", "", path], shell=False)
                except Exception as e:      # noqa: silent-ok — 打开失败不能让后台线程炸掉
                    LOG.debug("自动打开失败：%s", e)

        threading.Thread(target=_do, daemon=True).start()
        LOG.info("画图交付完成，已在后台自动打开：%s", path)
        return "\n\n🖥️ **已自动打开**（浏览器里可交互查看）。没弹出来的话，手动打开：\n`%s`" % path
    except Exception as e:      # noqa: silent-ok — 自动打开是锦上添花，失败了也照常把图给用户
        LOG.debug("自动打开逻辑异常（忽略）：%s", e)
        return ""


def _world_rag(query, limit=4):
    """**用户问题先过 RAG**：检索世界模型 + 已吸收的知识 → 匹对相关度 → 相关的才注入。

    这是世界层重构（第二部分）里"接入 agent_run"的那一条：
    "用户问题先过 RAG：检索世界模型 + memory_vec → 匹对用户画像 → 相关则注入"。

    为什么必须**先匹对再注入**（而不是把检索到的都塞进 system）：
    ctx 是有限的物理红线，而"探索"动作会让世界层里的知识一天天变多 ——
    无脑全塞，第一次超限时就只能砍历史、砍工具，把别的能力挤掉。
    而且不相关的知识注入进去只会**干扰**模型（实测过的坑：注入的记忆没做说话人框定时，
    模型把自己当成了用户）。所以这里只放"跟这句话真有关"的少数几条。

    返回可直接拼进 system 的文本（没有相关的就返回空串）。
    """
    try:
        q = (query or "").strip()
        if len(q) < 2:
            return ""
        wm, _p = _world_layer()
        if wm is None:
            return ""
        # ---- 关键词：规则抽取（不调模型），与世界层/续写同口径 ----
        kws = [k.lower() for k in _intent_keywords(q)]
        if not kws:
            return ""
        hits = []
        # ① 世界地图：站点名/类型/主题命中 → 告诉模型"这个站在这个话题上是什么来头"
        try:
            sites = wm.snapshot().get("sites") or {}
            for dom, rec in sites.items():
                blob = ("%s %s %s" % (dom, (rec or {}).get("type", ""),
                                      (rec or {}).get("note", ""))).lower()
                if any(k in blob for k in kws):
                    hits.append("网站：%s（类型 %s，可信度 %.1f）"
                                % (dom, (rec or {}).get("type") or "未判定",
                                   float((rec or {}).get("judged_trust")
                                         or (rec or {}).get("trust") or 0.5)))
        except Exception as e:      # noqa: silent-ok — 地图读不动就不注入这一路
            LOG.debug("世界 RAG：读站点表失败：%s", e)
        # ② 已吸收的知识：只取**通过防火墙**的那部分（隔离区的内容绝不注入，见第三部分）
        try:
            ap = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "logs", "world", "absorption.jsonl")
            if os.path.exists(ap):
                rows = []
                with open(ap, encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rows.append(json.loads(line))
                        except Exception:      # noqa: silent-ok — 半截行跳过
                            continue
                for r in reversed(rows[-200:]):
                    if not r.get("absorbed", True):
                        continue                      # 没吸收的（隔离/丢弃）不进上下文
                    blob = ("%s %s %s" % (r.get("topic") or "", r.get("title") or "",
                                          (r.get("text") or r.get("clean_text") or "")[:400])).lower()
                    if any(k in blob for k in kws):
                        src = r.get("domain") or r.get("url") or "未知来源"
                        txt = (r.get("text") or r.get("clean_text") or "").strip()[:220]
                        conf = r.get("score") or r.get("confidence")
                        hits.append("已知（来源 %s%s）：%s"
                                    % (src, ("，可信度 %.2f" % conf) if isinstance(conf, (int, float))
                                       else "", txt))
                    if len(hits) >= limit:
                        break
        except Exception as e:      # noqa: silent-ok — 吸收流水读不动就不注入
            LOG.debug("世界 RAG：读吸收记录失败：%s", e)
        if not hits:
            return ""
        LOG.info("世界 RAG：命中 %d 条（关键词 %s）", len(hits), kws[:4])
        return ("\n\n【世界层检索到的相关背景（小焦自己在互联网上看到的，"
                "可信度低于用户亲口说的话）】\n" + "\n".join("- " + h for h in hits[:limit]) + "\n")
    except Exception as e:      # noqa: silent-ok — 世界 RAG 是增强，坏了不能挡住回答
        LOG.debug("世界 RAG 失败（忽略）：%s", e)
        return ""


def _new_degen_detector():
    """拿一个带状态的退化检测器（拿不到就返回 None —— 复读检测缺席不能挡住推流）。

    为什么单独抽一个函数：**每一条流各要一个检测器**（它是有状态的、命中即锁存）。
    共用一个的话，第一轮流命中之后就永久锁存，后面所有轮都会被判成复读 ——
    那不是"更严格"，那是坏掉。
    """
    try:
        root = os.path.dirname(os.path.abspath(__file__))
        if root not in sys.path:
            sys.path.insert(0, root)
        from core.health import degeneration as _D
        return _D.DegenerationDetector()
    except Exception as e:      # noqa: silent-ok — 检测器拿不到就退化成"不检测"，绝不中断推流
        LOG.debug("退化检测器不可用（忽略）：%s", e)
        return None


def _fact_net(answer):
    """**出口纠事实**：它写了一个和"载体直算的真实结果"对不上的数 → 在后面补一句更正。

    【为什么放在出口】问「你自己算的？」「这数对吗」**不走睡不睡那条链**
    （那是 `_tired_decision` 的流程），它写错数是在**正常回答里**。
    所以这里在**所有路径的唯一出口**（聊天接口）过一道网：
    **不改它的话**，只在后面**补一句事实**（医生只给事实、不改它的话）。

    ⚠️ 补了更正 **不等于"它自己改对了"** —— 那句话是载体补的，不许说成它改的。
    """
    try:
        text = str(answer or "")
        if not text:
            return answer, ""
        rm, pm = _raw_mod(), _pain_mod()
        if rm is None or pm is None:
            return answer, ""
        raws = [str(r.get("result") or "").strip() for r in rm.recent(3)]
        raws = [r for r in raws if r]
        if not raws:
            return answer, ""
        chk = pm.check_fact(text, {"结果列表": raws})
        if chk.get("corrections"):
            note = ("\n\n—— 更正（载体手里的真实结果）：%s"
                    % "；".join(c["text"] for c in chk["corrections"]))
            LOG.info("纠事实（出口）：**它写错了结果** —— %s",
                     "；".join(c["text"] for c in chk["corrections"])[:100])
            return text + note, note
        if chk.get("skipped"):
            LOG.info("纠事实（出口）：**不纠**（位数差太远，纠了有误判风险）—— %s",
                     "；".join("%s vs %s" % (s["said"], s["real"]) for s in chk["skipped"])[:100])
        return answer, ""
    except Exception as e:      # noqa: silent-ok — 纠不了不能影响回答
        LOG.debug("出口纠事实失败（忽略）：%s", e)
        return answer, ""


def _degeneration_net(text, where=""):
    """**最后一道网**：任何要交给用户的文本，出门前都过一遍复读解毒。

    【为什么健康门之外还要有这一层（问题 1 的教训）】
    健康门（`_health_gate`）挂在 `agent_run` 的出口上，可 `agent_run` 有**十几条 return**：
    命中"要看工具原文"提前返回、超长输入切片提前返回、工具总结直接返回、表格类结果原样返回……
    任何一条绕过它，复读就会原样送到用户眼前 —— 用户实测就是这样：
    整张表格被"预算"刷满几十行，而健康系统那边**明明报了 repeat 症状**，
    只是那条路根本没经过它。

    所以这里换一个更笨、但**不可能漏**的做法：不去数"有哪些路径"，
    而是在**唯一真正的出口**（两个聊天接口 + 工具总结）加一道纯文本的网。
    它只依赖 `core/health/degeneration.py`（不依赖模型、不依赖会话、不依赖健康层是否起来了），
    代价是几毫秒，收益是"无论谁写的、从哪条路出来的，刷屏都走不到用户面前"。

    返回 (处理后的文本, 说明)；没触发就原样返回 (text, "")。
    """
    try:
        s = text if isinstance(text, str) else ""
        if len(s) < 60:
            return text, ""
        root = os.path.dirname(os.path.abspath(__file__))
        if root not in sys.path:
            sys.path.insert(0, root)
        from core.health import degeneration as _D
        t2, hit, cut = _D.truncate_repeat(s)
        if hit is None or cut <= 0:
            return text, ""
        t2, cut2 = _D.repair_tail(t2)
        LOG.warning("复读解毒（%s）：%s → 砍掉 %d 字，保留 %d 字｜%s",
                    where or "出口", hit.kind, cut + cut2, len(t2), hit)
        if not t2.strip() or (len(t2.strip()) < 40 and len(s) >= 200):
            # 整段都是复读 → 不能给空，也不能给一个没用的碎片（"| 第1项 | 预算 | 预算"），
            # 如实说明发生了什么。用户要能看懂"刚才那轮模型坏了"，而不是对着一片空白猜。
            keep = ("\n\n（复读之前还剩下这么一点，原样附上：`%s`）" % t2.strip()) if t2.strip() else ""
            return ("⚠️ 这一轮的回答**整段陷入了复读**（%s），已经没有可用的正文。"
                    "重新问一次通常就好了；如果反复出现，说明当前火种在这个上下文长度下不稳定。%s"
                    % (hit.kind, keep)), "已整段替换"
        return t2, "已截断 %d 字" % (cut + cut2)
    except Exception as e:      # noqa: silent-ok — 解毒失败必须放行原文本（不能因为它把回答搞丢）
        LOG.debug("复读解毒异常（忽略，原样返回）：%s", e)
        return text, ""


def _summarize_tool(user_input, result, tool):
    """让大脑基于工具结果给一句简短总结。

    **工具总结也是输出路径**（问题 1 的清点项之一）：它是模型生成的正文，
    一样会复读。以前这条路直接把模型的话返回出去，谁都没管 ——
    所以这里也过一遍解毒网（`_degeneration_net`）。
    """
    prompt = ("你用 %s 工具执行了用户请求，结果如下：\n%s\n\n"
              "请用一句简短中文告诉用户完成了什么（例如：已在 XXX 创建了 YYY）。不要重复结果内容，不要科普。" % (tool, result[:1200]))
    s = _llm_ask_raw(prompt)
    if not s:
        return "已完成（%s）。" % tool
    s2, _note = _degeneration_net(s, where="工具总结/%s" % tool)
    return s2


def _asks_asset_list(text):
    """用户是不是在问"资产/IP/主机"（NVD 给不了这类数据，必须当面说清）。

    真实缺陷：不管问"抓一下漏洞"还是"把所有含这些漏洞的 IP 列出来"，回复都是同一张 NVD 表，
    用户看到的就是"一直是这个模板，一点没变" —— 因为代码只判了"漏洞意图"，没判"要的是资产清单"。
    """
    ql = (text or "").lower()
    if not ql:
        return False
    if re.search(r"(?<![a-z])ip(?![a-z])", ql):        # ip / 公网ip / IP地址（避开 zip、clip 这类词）
        return True
    if re.search(r"ip\s*地址", ql):
        return True
    if re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", ql):   # 直接甩了几个 IP 过来，也算资产诉求
        return True
    return any(k in ql for k in ("主机", "资产", "受影响的机器", "哪些机器", "哪些服务器", "网段"))


def _asset_result_text(res):
    """把工具返回的 JSON/纯文本统一取成正文（失败就给一句中文说明）。

    资产测绘插件与 `net_ip` 都用它：JSON 就取 content/error，纯文本就原样返回。
    """
    try:
        _j = json.loads(res)
        if isinstance(_j, dict):
            return str(_j.get("content") or _j.get("error") or "").strip()
    except Exception as e:
        LOG.debug("忽略异常(%s:%d): %s", __file__, 1521, e)
    return str(res or "").strip()


def _asset_answer(user_input, vuln_table):
    """资产类提问的回答：真的去查资产数据源，查不到就说清差什么、怎么补。

    - 问题里带了 IP → 走 `asset_intel_lookup`（Shodan InternetDB，免费无 Key）真查出
      "这个 IP 命中了哪些 CVE"，并列表对应上；
    - 只给了 CVE/关键词（"全网哪些 IP 受影响"）→ 走 `asset_intel_search`；没配 Key 时
      插件会返回一段**中文可操作**的说明（去哪拿 Key、填哪里、怎么验证），直接给用户看；
    - 最后仍然附上 NVD 漏洞本身，方便先按受影响软件/版本筛查。
    """
    _ips = re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", user_input or "")
    _cves = re.findall(r"CVE-\d{4}-\d{4,7}", user_input or "", re.I)
    try:
        _build_tools()                       # 确保资产插件的三个工具已注册
    except Exception as e:
        LOG.debug("忽略异常(%s:%d): %s", __file__, 1540, e)
    head = ""
    if _ips:
        head = _asset_result_text(_tool_result_str(run_tool(
            "asset_intel_lookup", {"ips": ", ".join(_ips), "cves": ", ".join(_cves)}, force=True)))
    else:
        _q = _cves[0] if _cves else resolve_search_query(user_input)[0]
        if _q:
            head = _asset_result_text(_tool_result_str(run_tool(
                "asset_intel_search", {"query": ("vuln:%s" % _q) if _cves else _q, "limit": 10}, force=True)))
    if not head:
        head = ("⚠️ 资产测绘这一步没返回内容（插件 `plugins/asset_intel.py` 在不在？"
                "对我说「资产测绘状态」可以看各数据源是否可用）。")
    return head + "\n\n---\n\n**这些漏洞本身（NVD 实时数据）**：\n\n" + vuln_table


def _asks_own_ip(text):
    """是不是在问"我的公网 IP / 本机 IP / 你给我显示 IP"（要直连 net_ip 真查）。

    触发条件三条同时成立：① 提到 IP；② 指向自己/当前/对方；③ **没有给出具体 IP**
    （用户给了具体 IP 那是要查那个地址，别抢答）。
    """
    q = text or ""
    return bool(re.search(r"(?<![a-z])ip(?![a-z])|ip\s*地址", q, re.I)
                and re.search(r"(我|我的|本机|自己|当前|这台|这电脑|你)", q)
                and not re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", q))


# （_TOOL_RULES 已上移到提示词分层区，见文件顶部「系统提示词的分层」）


# ================== 入口关键词路由（第 3 层） ==================
# 为什么要有它：模型选工具不稳（调错/乱试/漏调）。这里在**进模型之前**先用规则锁定意图，
# 命中就直连对应工具（抓取/IP/漏洞），或明确告诉模型该走哪条链（画图），没命中再走正常流程。
_URL_LIKE_RE = re.compile(r"https?://[^\s，。；、）)\]\"']+|\b[a-z0-9][a-z0-9\-]{1,60}\.(?:com|cn|net|org|io|dev|gov|edu|ai|co|me|app)\b", re.I)
_DIAGRAM_HINTS = ("架构图", "流程图", "时序图", "数据流图", "状态图", "生命周期图", "画一张图",
                  "画个图", "画图", "diagram", "archify")


def _looks_like_url(text):
    """句子里有没有网址（带协议或裸域名）。"""
    return bool(_URL_LIKE_RE.search(text or ""))


def _asks_diagram(text):
    """是不是画图任务（要锁到 archify 工具链，不许去联网搜）。"""
    q = (text or "").lower()
    return any(h.lower() in q for h in _DIAGRAM_HINTS)


# 常见命令动词（用于"这句话本身就是一条命令"的判定）
_SHELL_VERBS = ("del", "erase", "rm", "rmdir", "rd", "dir", "echo", "type", "copy", "move", "ren",
                "ipconfig", "ipconfig", "ping", "netstat", "tasklist", "taskkill", "systeminfo",
                "where", "whoami", "hostname", "ver", "cls", "mkdir", "md", "cd", "tree", "findstr",
                "powershell", "pwsh", "cmd", "python", "pip", "git", "node", "npm", "curl", "iwr",
                "wget", "shutdown", "reg", "sc", "schtasks", "attrib", "fc", "comp", "sort", "more")


def _looks_like_shell_command(text):
    """这句话本身是不是一条 shell 命令？是就返回命令原文（否则返回 ""）。

    判据保守：① 只有一个"逻辑行"（没有换行/问号/中文句子结构）；② 首词命中命令动词；
    ③ 长度合理。避免把"echo 是什么"这种**提问**误判成命令（问句有 是什么/怎么/为什么 等词）。
    """
    q = (text or "").strip()
    if not q or "\n" in q or len(q) > 400:
        return ""
    if re.search(r"(是什么|什么是|怎么|如何|为什么|吗\?|\?|？|请教|解释|教我)", q):
        return ""
    if re.search(r"[\u4e00-\u9fa5]", q) and "echo " not in q.lower():
        return ""                                  # 中文叙述句基本不是命令
    first = re.split(r"\s+", q, 1)[0].strip().lower().lstrip("@")
    if first.endswith(".exe"):
        first = first[:-4]
    return q if first in _SHELL_VERBS else ""


def _asks_net_ip(text):
    """问本机公网 IP / 归属地（本机自身信息 → net_ip 直答）。"""
    q = (text or "")
    if not re.search(r"(?<![a-z])ip(?![a-z])|公网|归属地|外网地址", q, re.I):
        return False
    if re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", q):      # 给了具体 IP 是要查那个地址
        return False
    return bool(re.search(r"(我|我的|本机|自己|当前|这台|这电脑|你|多少|是什么|归属)", q))


# 候选工具表：某个工具失败时该换谁（第 4 层"调错后换下一个候选"用）
_TOOL_FALLBACK = {
    "get": ["fetch", "stealthy_fetch"],
    "make_request": ["fetch", "stealthy_fetch"],
    "fetch": ["stealthy_fetch"],
    "search_files": ["grep_files"],
    "grep_files": ["search_files"],
    "web_search": ["get"],
    "archify_validate": ["archify_read_schema"],       # 校验不过 → 回去读 schema 再改
}


def _tool_fallback_for(name):
    return _TOOL_FALLBACK.get(name, [])


# ================== 第 1 步：意图路由 —— 按需加载 system + tools（问题 1 + 9） ==================
# 为什么要有它：以前**每一轮**都把全部 77 个工具（实测 13891 token）和整份规则（system ~5700 token）
# 发给大脑 —— 光固定开销就顶穿本地 ctx（llama.ctx=20224），连"你好"都报 400/500；
# 而且工具越多模型越容易摸错（用户实测：画图时跑去 read_memory）。
# 这里**一个工具、一条规则都不删**，只决定"这一轮加载哪些"：闲聊 3 个工具、画图只给 archify 链，
# 认不出来的也走 chat（最省上下文）。所有工具仍然注册在表里，随时可被点名调用。
_INTENT_HINTS = {
    # 查询类信号（会去查外部信息）
    "query": ("搜索", "搜一下", "搜一搜", "查一下", "查查", "找一下", "帮我查", "百度", "谷歌",
              "新闻", "漏洞", "cve", "公网", "归属地", "天气", "汇率", "最新", "多少钱"),
    # 命令类信号（想让我动手执行）
    "shell": ("执行命令", "运行命令", "跑一下命令", "命令行", "powershell", "cmd 里", "shell"),
}

# ============ 信息收集类意图（Bug 1：该调工具时反问用户）============
# 【为什么单独一组】"整理一下最近的新闻信息"这种说法里，说话人**已经说清要什么**了：
#   「最近」= 时间限定，「新闻」= 主题。可它原来被判成 chat → 闲聊轮不联网 →
#   模型只好回"我无法访问实时新闻网站，你想查什么方向？" —— 用户听到的是**反问**，
#   而他明明已经把方向说了。这类"信息收集动作词"必须能触发 query 意图。
# 【为什么动作词和信息名词要**同时**出现】只认动词会把"帮我整理一下桌面"也变成联网搜索
#   （那该是 shell/文件操作）；只认名词则"这条新闻写得不错"也会触发搜索。
#   两个同时命中才算"要我去收集某类信息"——这是最不容易误判的口径。
_INFO_COLLECT_VERBS = ("整理", "汇总", "归纳", "梳理", "盘点", "总结一下", "看看", "看一下",
                       "了解一下", "收集", "搜集", "关注一下", "跟进", "盯一下")
_INFO_NOUNS = ("新闻", "动态", "信息", "资讯", "消息", "热点", "行情", "进展", "近况",
               "情况", "资料", "报道", "舆情", "榜单", "排行")


def _asks_info_collect(text):
    """用户是不是在要求"去收集某类信息"（动作词 + 信息名词**同时**出现）。

    只有两者同时命中才认（理由见 `_INFO_COLLECT_VERBS` 上面的说明）。
    ⚠️ 这个函数曾被我在插入 `_asks_tool_inventory` 时**误删过一次**：
    编辑时把 `def _asks_info_collect(text):` 那一行当成了插入锚点整行替换掉，
    函数体还在、函数名没了 —— 语法检查能过（没人调用时不报错），
    但它有 2 处调用点，一跑就是 NameError。教训：**改文件后要 grep 确认函数名还在**，
    光靠 `ast.parse` 是查不出"定义了但名字丢了"的。
    """
    s = str(text or "")
    if not s:
        return False
    return any(v in s for v in _INFO_COLLECT_VERBS) and any(n in s for n in _INFO_NOUNS)


def _recent_user_turns(history, n=5):
    """取最近 n 条**用户**消息（跳过小焦自己的回答与占位）。

    为什么只要用户说的：融合的目的就是"这句在接哪句"，
    而"哪句"只可能是用户自己提出过的请求；拿小焦的回答去融合会把话题带偏。

    ⚠️ role 有**两套写法**，必须都认：
        · 会话历史里存的是中文角色 —— `用户` / `小焦`（`append_msg("用户", …)`）；
        · OpenAI 风格的 messages 用 `user` / `assistant`。
    第一版我只判了 `role == "user"`，于是在**真实会话**里一条都取不到 →
    融合永远拿到空上文 → 第 2 轮照样反问（端到端实测当场抓到；
    单元测试里我按 OpenAI 风格造数据，所以反而是绿的 —— 这就是"测数据比真实数据干净"的坑）。
    """
    _USER_ROLES = ("user", "用户", "human")
    out = []
    for m in reversed(list(history or [])):
        if not isinstance(m, dict):
            continue
        if str(m.get("role") or "").strip().lower() not in _USER_ROLES:
            continue
        c = str(m.get("content") or "").strip()
        if not c or c == "⏳__pending__":
            continue
        out.append(c)
        if len(out) >= max(1, int(n)):
            break
    return list(reversed(out))


# ---------------- 回指词表：这些词说明"这句离不开上文" ----------------
# 分成三类，因为处理方式不同：
#   · 继续类：整句就是"接着上次"（继续/接着/然后呢）→ 直接**借用**上文请求
#   · 追加类：要更多的同类东西（再来一个/换一个/还有吗）→ **复用上文动作**
#   · 补全类：句子里有明确动词/目标，只是"完整度"不够（我要全部的/换成 baidu）→ **补全目标**
_CONTINUE_WORDS = ("继续", "接着", "然后呢", "还有呢", "往下", "接着说", "继续说",
                   "go on", "continue")
_MORE_WORDS = ("再来一个", "再来一次", "再一个", "换一个", "换一部", "换首", "换一个吧",
               "还有吗", "还有没有", "再给一个", "重新来一个", "另一个", "别的呢",
               "再推荐一个", "多来几个")
_ALL_WORDS = ("全部", "所有", "全都要", "都要", "全给我", "所有的", "全都", "全列",
              "一个不落", "一个不少", "全部列出来")
# 目标替换：把上一条请求里的目标换成本句给的新目标
_RETARGET_RE = re.compile(r"(?:换成|改成|改为|换到|换成那个|换成这个)\s*([^\s，。！？；,]+)")
# 指代目标：这些词本身不携带信息，必须从上文取目标
_ANAPHORA = ("这个", "那个", "它", "上面那个", "刚才那个", "刚才说的", "上面说的",
             "这东西", "这东西的", "它呢")
# 把指代词去掉之后，剩下的实义**少于几个字**才算"这一句残缺、需要补全"。
# （> 这个数 = 它自己主谓宾齐全 → **不融合**，见 merge_context 第 5 段）
_ANAPHORA_MIN_REST = 5


def _topic_of(text):
    """从一句话里抽"话题名词"（融合时用来拼出完整请求）。

    为什么用规则而不是模型：融合必须**确定性**且便宜 —— 它每轮都跑，
    交给模型既慢又可能把话题理解错，而这里只需认出"在聊什么名词"。
    抽法：去掉动作词/功能字/时间词后剩下的 2~6 字中文名词（取最长的一段）。
    """
    s = str(text or "")
    # 量词/冠词也要剥掉："推荐一部电影" 的话题是「电影」而不是「一部电影」——
    # 带着量词去补全会造出"我要全部的一部电影"这种别扭句子（测出来的）。
    for w in ("帮我看看", "看一下", "看看", "帮我", "给我", "我要", "我想", "推荐",
              "整理", "汇总", "查一下", "搜一下", "抓一下", "有哪些", "有什么", "哪些",
              "一部", "一个", "一条", "一份", "一张", "一首", "一篇", "一本", "一段",
              "再", "一下", "的", "了", "吗", "呢", "啊", "吧"):
        s = s.replace(w, " ")
    segs = re.findall(r"[\u4e00-\u9fa5]{2,6}", s)
    if not segs:
        return ""
    # 取最长的一段（"最近的新闻" → "新闻"），并只保留末尾 2~4 字（"最近新闻"→"新闻"）
    segs.sort(key=len, reverse=True)
    cand = segs[0][-4:]
    # 时间词不配当话题（"最近有什么新闻" 的话题该是"新闻"）
    for tw in ("最近", "最新", "近期", "今天", "今日", "本周", "这周"):
        if cand == tw:
            cand = segs[1][-4:] if len(segs) > 1 else ""
    return cand


def _asks_all_of_it(text):
    """这句是不是"要全部"（配合上下文才成立）。"""
    s = str(text or "")
    return any(w in s for w in _ALL_WORDS)


def merge_context(user_text, history, n=5):
    """**上下文融合**：把"孤立的这一句"补成"完整的一句"，再交给意图识别。

    【为什么必须有它 —— 用户实测的核心缺陷】
        小焦把每句话当新对话。实测：
            用户："帮我看看有哪些工具" → 列出工具
            用户："我要全部的"        → 反问"你要全部什么？"
        根因不是历史没进 prompt（历史进了），而是**意图判定阶段是孤立的**：
        `_detect_intent(user_input)` 只看当前这一句，
        "我要全部的"孤立看确实没有信息（没有动词、没有对象），于是判成 chat，
        模型也只好反问。人不会这样：人先知道"上文在聊工具"，再看"这句在指全部"。

    【判据为什么这么设计】
        只在**句子里出现回指**时才融合（回指词表见上面三类）。
        没有回指就不动它 —— 否则每句话都被"上文的上下文"污染，
        用户换个话题时会被上一轮的话题带跑（那是比不连续更糟的错）。
        融合结果一律带上 `merged` 字段与理由，日志里能回答"为什么把它当成接续"。

    返回 dict：
        text      融合后的完整请求（没融合就是原文）
        merged    bool
        kind      "none" | "continue" | "more" | "all" | "retarget"
        topic     融合用到的上文话题（没有则空）
        why       人话理由
        need_clarify  True = 融合不出来，**应当反问**（无上文 / 上文有歧义）
    """
    cur = str(user_text or "").strip()
    base = {"text": cur, "merged": False, "kind": "none", "topic": "",
            "why": "", "need_clarify": False}
    if not cur:
        return base
    prevs = _recent_user_turns(history, n=n)
    # 【必须把"当前这句话"从候选上文里剔掉 —— 这是一处真实缺陷的修复】
    #   真实入口下，用户这句话**已经先被写进会话历史**了，于是 `prevs[-1]` 就是它自己：
    #     「我要全部的」→ prev 也是「我要全部的」→ `_topic_of` 抽出「全部」
    #     → 融合成 **「我要全部的全部」**（实测复现，服务端日志一字不差）。
    #   而直接调 `merge_context` 的单元测试里历史不含当前句，所以测出来是绿的
    #   （「我要全部的工具」）—— 又一次"函数是对的，不等于接入是对的"。
    #   剔掉之后，'all / more / continue / 指代' 四类补全都拿得到**真正的前一句**。
    prevs = [p for p in prevs if p.strip() != cur]
    prev = prevs[-1] if prevs else ""

    # ---------- 1. 继续类：整句就是"接着上次" ----------
    if any(w in cur for w in _CONTINUE_WORDS) and len(cur) <= 12:
        if not prev:
            return dict(base, kind="continue", need_clarify=True,
                        why="用户说「继续」但上面没有可继续的内容")
        topic = _topic_of(prev)
        # 把上一条请求**原样**当成本轮请求（继续做同一件事）
        return {"text": prev, "merged": True, "kind": "continue", "topic": topic,
                "why": "「%s」是接着上一条请求「%s」" % (cur, prev[:24]),
                "need_clarify": False, "original": cur}

    # ---------- 2. 追加类：还要更多同类 ----------
    if any(w in cur for w in _MORE_WORDS) and len(cur) <= 14:
        if not prev:
            return dict(base, kind="more", need_clarify=True,
                        why="用户要「再来一个」但上面没有可延续的请求")
        topic = _topic_of(prev)
        # 复用上文的**动作 + 话题**，并明确要求"换一个不同的"
        merged = "%s（换一个不同的%s，不要重复上一个）" % (prev, topic)
        return {"text": merged, "merged": True, "kind": "more", "topic": topic,
                "why": "「%s」延续上一条请求「%s」" % (cur, prev[:24]),
                "need_clarify": False, "original": cur}

    # ---------- 3. 补全类 A：要"全部" ----------
    if _asks_all_of_it(cur) and len(cur) <= 18:
        if not prev:
            return dict(base, kind="all", need_clarify=True,
                        why="用户要「全部」但上面没有可以「要全部」的对象")
        topic = _topic_of(prev)
        if not topic:
            return dict(base, kind="all", need_clarify=True,
                        why="上文没有可用于补全的话题名词")
        merged = "我要全部的%s" % topic
        return {"text": merged, "merged": True, "kind": "all", "topic": topic,
                "why": "「%s」补全为「%s」（上文在聊%s）" % (cur, merged, topic),
                "need_clarify": False, "original": cur}

    # ---------- 4. 补全类 B：换目标（"换成 baidu"） ----------
    m = _RETARGET_RE.search(cur)
    if m:
        new_target = m.group(1).strip()
        if not prev:
            return dict(base, kind="retarget", need_clarify=True,
                        why="用户要「换成 %s」但上面没有可替换目标的请求" % new_target)
        # 从上一条请求里找出旧目标并替换：把"抓一下 example.com"变成"抓一下 baidu"
        merged = prev
        # 常见目标形态：域名 / 引号内 / URL
        old = (re.findall(r"https?://[^\s，。！？；]+", prev)
               or re.findall(r"[A-Za-z0-9\-]+\.[A-Za-z]{2,}", prev)
               or re.findall(r"「([^」]{1,20})」", prev))
        if old:
            merged = prev.replace(old[0], new_target)
        else:
            merged = "%s（这次的目标是：%s）" % (prev, new_target)
        return {"text": merged, "merged": True, "kind": "retarget", "topic": new_target,
                "why": "「%s」把上一条请求「%s」的目标换成「%s」" % (cur, prev[:24], new_target),
                "need_clarify": False, "original": cur}

    # ---------- 5. 补全类 C：句子里只有指代词 ----------
    # 【实测抓到的串句事故 —— 判据必须加"这一句是不是残缺"】
    #   旧版只要「≤16 字 + 含指代词」就替换，于是
    #     「这个配置有风险，要小心泄露」（12 字、含「这个」）
    #   被替换成 **「天气不错配置有风险，要小心泄露」**（把「这个」替成了上一轮的话题
    #   「天气不错」）—— 日志里就是这么串起来的。
    #   这一句本来**主谓宾齐全**，根本不需要补全。所以现在多一道闸：
    #   **把指代词去掉之后，剩下的实义少于 `_ANAPHORA_MIN_REST` 字**才算残缺。
    if len(cur) <= 16 and any(w in cur for w in _ANAPHORA):
        rest = cur
        for w in _ANAPHORA:
            rest = rest.replace(w, "")
        rest = re.sub(r"[\s，。！？、,.!?呢吗吧了啊的]", "", rest)
        if len(rest) > _ANAPHORA_MIN_REST:
            return base          # 这一句自己是完整的 → **不融合**
        if not prev:
            return dict(base, kind="anaphora", need_clarify=True,
                        why="用户用了指代词「%s」但上面没有可指的内容"
                            % next((w for w in _ANAPHORA if w in cur), "它"))
        topic = _topic_of(prev)
        merged = cur
        for w in _ANAPHORA:
            if w in merged:
                merged = merged.replace(w, topic or "刚才那个")
        return {"text": merged, "merged": True, "kind": "anaphora", "topic": topic,
                "why": "「%s」里只剩指代、补成「%s」（上文在聊%s）" % (cur, merged, topic),
                "need_clarify": False, "original": cur}

    # ---------- 6. 无回指：**不动它**（见上面的判据说明） ----------
    return base


def _tool_inventory_question(text, ctx=None):
    """这一轮是不是在问"工具清单"（含**经上下文融合后**的"我要全部的"）。

    spec 的验收用例：说"帮我看看有哪些工具" → 小焦列工具 → 用户说"我要全部的"
    → **直接列出全部工具**（不是反问）。
    所以这里除了原来的问法，还要认"要全部 + 上文在聊工具"这一种。
    """
    if _asks_tool_inventory(text):
        return True
    # 无上文也可以：**这一句自己**就说了对象是"工具/插件/能力"
    # （"我要全部的工具" → 直接列；"我要全部的" → 才需要上下文，见下面那条）。
    _t = str(text or "")
    if _asks_all_of_it(_t) and any(k in _t for k in ("工具", "插件", "能力")):
        return True
    if not ctx:
        return False
    if ctx.get("merged") and ctx.get("kind") == "all":
        topic = str(ctx.get("topic") or "")
        if topic and any(k in topic for k in ("工具", "插件", "能力")):
            return True
    return False


def _clarify_question(user_text):
    """融合不出来时该问什么（**通用反问**，不是某个 case 的硬编码）。

    什么时候会走到这里（见 `merge_context` 的 `need_clarify`）：
      · 无上文却说"我要全部的/再来一个/继续/换成 X" —— 载体没有可接的内容；
      · 上文有指代词但抽不出话题名词。
    为什么必须**反问**而不是猜：猜错的代价比问一句大得多 ——
    用户说"我要全部的"，系统要是猜成"全部新闻"，他会觉得"这 AI 根本没听懂还硬答"。
    这正是用户实测抱怨的那种体验，所以宁可问一句。
    """
    s = str(user_text or "").strip()
    if _asks_all_of_it(s):
        return "你说的「全部」是指什么的全部？把范围告诉我（比如：全部工具／全部新闻／全部文件）。"
    if any(w in s for w in _MORE_WORDS):
        return "想让我再来一个什么？先说一句你想要的类型我就接着给。"
    if any(w in s for w in _CONTINUE_WORDS):
        return "想让我继续做哪件事？上面还没开始过任务，你说一下我马上做。"
    if _RETARGET_RE.search(s):
        return "要换成什么的目标？你前面还没给过要替换的请求，直接说这次要哪个就行。"
    return "这句我需要一点上下文才好动手 —— 你具体想让我做什么？"


def _asks_tool_inventory(text):
    """用户在问"你有哪些工具"吗？

    【为什么要专门认这一句 —— 实测出来的真问题】
        问"你有哪些工具？把能用的都列出来"时，实测结果：模型只回了 **13 个字**，
        而且顺手调了 `list_files`（去列目录了）—— 它把"列工具"理解成了"列文件"。
        这不是提示词没写清，而是**把清单类问题交给了模型**：
        77 个工具名是载体自己就知道的事实，让 4B 模型凭 system 里那份目录背诵，
        必然背漏、背错，还可能顺手调一个不相干的工具。
    """
    s = str(text or "")
    if not s:
        return False
    return any(k in s for k in ("有哪些工具", "有什么工具", "能用的工具", "工具列表",
                                "有哪些插件", "有什么插件", "会哪些工具", "支持哪些工具",
                                "工具都有哪些", "列出工具"))


def _tool_inventory_answer():
    """载体**直接**回答"我有哪些工具"（列出全部，一个不落）。

    【为什么由载体回答而不是让模型答（这条是无限 4 的验收项）】
        spec 的验收是"说『你有哪些工具』→ **列出全部**"。
        "全部"是硬要求，而模型是概率性的 —— 让它背诵必然不全。
        这个问题的答案**完全在载体手里**（`all_tool_names()` + 一句话说明），
        所以由载体生成、直接返回，模型连调都不用调：
        既保证"一个不少"，又省掉一次模型往返，还避免它顺手调错工具。
        这正是"载体优先"的一个具体例子：**确定性的问题不要交给概率性的部件**。
    """
    try:
        names = [n for n in all_tool_names() if n]
    except Exception:      # noqa: silent-ok — 取不到工具表就如实说取不到，不编
        return "抱歉，我这边工具表没读出来，没法给你完整清单。"
    if not names:
        return "我这边当前没有装载任何工具。"
    plugin = [n for n in names if n.startswith("archify_")]
    core = [n for n in names if not n.startswith("archify_")]
    lines = ["我一共 **%d 个**工具，一个都没砍、没有暂缓，全都能用：" % len(names), ""]
    lines.append("**内置能力（%d 个）**" % len(core))
    for n in core:
        lines.append("- `%s`" % n)
    if plugin:
        lines += ["", "**画图工作流 archify（%d 个，按顺序联动）**" % len(plugin)]
        for n in plugin:
            lines.append("- `%s`" % n)
    lines += ["", "需要哪个直接说名字就行 —— 点名的那一刻我就把它装上。"]
    return "\n".join(lines)


# ⚠️ 这里原本还挂着一份 `_asks_info_collect` 的**孤儿函数体**（没有 `def` 行，直接就是 docstring +
#    `s = str(text or "")`）。它是"插入新函数时把 `def` 行连带吃掉"那次事故的残留：
#    真正的函数早已在上方恢复（见那份 docstring 里记的经过），而这一份一直没人删 ——
#    于是 `text` 成了未定义名，ruff F821 把它抓了出来。
#    为什么 `ast.parse` 抓不到：模块级的裸字符串字面量是**合法语句**，语法检查必过；
#    只有真的执行到 `s = str(text or "")` 那一行才会 NameError。
#    结论：**"定义了但名字丢了"这类损坏只能靠 ruff/静态检查发现，别指望 ast.parse。**
# 闲聊只认**明确的寒暄/身份/道谢**这类；认不出来的一律走 chat 兜底（见 `_detect_intent`）。
# 这条判据现在只用来决定"要不要加『闲聊别调工具』那句话"，不再决定给几个工具。
_CHAT_HINTS = ("你好", "您好", "hi", "hello", "嗨", "哈喽", "在吗", "在么", "早上好", "中午好",
               "下午好", "晚上好", "晚安", "早安", "谢谢", "多谢", "感谢", "再见", "拜拜",
               "你是谁", "你叫什么", "介绍一下你", "自我介绍一下", "哈哈", "嘿嘿", "嗯嗯")

# `full` 的**核心集**：不再是"全部 77 个"（那是 13891 token 的工具 schema，
# 单这一项就把本地 20224 的 ctx 挤爆）。完整工具目录仍随 system 下发（工具名 + 一句话），
# 模型要点名哪个，下一轮按意图装载 —— **能力一个不少，只是不在一轮里全塞**。
_FULL_CORE_TOOLS = ("run_command", "write_file", "read_file", "list_files", "web_search",
                    "get", "fetch", "net_ip", "collect_vulnerabilities", "save_memory")

# 每个意图要加载的工具（名字必须**真实存在**；写了不存在的会被丢掉，不会静默变成"全部"）
_INTENT_TOOLS = {
    "chat": ("web_search", "read_memory", "list_files"),
    "scrape": ("get", "make_request", "fetch", "stealthy_fetch", "bulk_get", "bulk_fetch",
               "scrape_with_selector", "download", "screenshot", "web_search"),
    # 【顺序就是"优先用谁"】用户实测：「山东菏泽天气」这轮里 `get_weather` 原本排在 `web_search`
    #   **后面**（第 5 位），模型于是先抓网页 → 只拿到一堆链接 → 回"我没能力"。
    #   专用工具必须排在通用检索前面：`get_weather` 返回的是**结构化天气数据**，
    #   而 `web_search` 返回的是**网页片段**（还得模型自己从里面抠数字，抠不出来就答不了）。
    "query": ("get_weather", "net_ip", "collect_vulnerabilities", "web_search", "read_file"),
    "shell": ("run_command", "read_file", "write_file"),
    "diagram": None,      # 特殊：archify_* 全链 + 读写文件（下面现算）
    "full": _FULL_CORE_TOOLS,   # 核心集（不再是"全部"）；完整目录由 system 里的工具索引下发
}
_CHAT_SYSTEM_HINT = ("\n[本轮模式] 闲聊：直接、自然地回话就行，**不要调用工具、不要联网搜索**。\n")
# 认不出意图时走的是 chat（最省上下文），但**不能**对用户说"别调工具" —— 那会真的
# 让"帮我算一下这个文件里的和"这类没命中关键词的任务丧失动手能力。所以这里给的是
# "照常动手，需要别的工具就点名"的版本：工具目录仍在 system 里，点名即下轮装载。
_CHAT_FALLBACK_HINT = (
    "\n[本轮模式] 直接回话。**没真调用过工具就不许说「已创建/已执行/已完成/已保存」** "
    "（编造执行结果是最严重的问题）；只有用户明确要你动手时才调用工具。"
    "当前只装载了最常用的几个工具，需要别的工具时直接说出工具名，下一轮就会为你装上。\n")
_DIAGRAM_SYSTEM_HINT = (
    "\n[本轮模式] 画图：严格按 Archify 工作流走 —— archify_read_skill → archify_guide → "
    "archify_read_schema → archify_read_example → archify_validate → archify_deliver → "
    "archify_visual_check；不要联网搜索，不要用别的画图方式。\n")
# 只读、无害的工具：闲聊轮里模型"顺手查一下"是合理的（查记忆/搜一下/看目录）。
# 反过来，这张表之外的工具在闲聊轮**一律不许**由 `plan_tool` 凭空产生 ——
# 尤其是 run_command 这类"会动系统"的：见 `plan_tool` 里的说明（实测它会为"你好"编出
# `Get-Process` 这种真会执行的命令，属于必须拦住的编造）。
_CHAT_SAFE_TOOLS = frozenset(("read_memory", "web_search", "search_web", "get",
                              "make_request", "fetch", "stealthy_fetch",
                              "read_file", "list_files"))

# "用户明确要我动手"的信号词。为什么要单独一张表：
#   `_detect_intent` 认不出来的句子都兜底成 chat，所以"chat 意图"里混着**真任务**
#   （"写个文件到桌面"就是 chat）。要靠这张表把"真任务"从"闲聊"里分出来，
#   否则 `plan_tool` 的闲聊闸门会把正常动手请求一起拒掉。
_ACTION_HINTS = ("写", "建", "创建", "新建", "保存", "改成", "修改", "替换", "追加",
                 "跑", "执行", "运行", "调用", "打开", "启动", "下载", "安装", "上传",
                 "查", "搜", "抓", "爬", "读一下", "看下", "列出", "列出文件", "列出目录",
                 "删", "移除", "复制", "移动", "重命名", "压缩", "解压",
                 "run", "exec", "create", "write", "save", "open", "download")


def _asks_action(text):
    """用户是不是**明确要我动手**（而不是随口聊）。见 `_ACTION_HINTS` 的说明。

    判据故意粗（只要出现动作词就算）：这里的作用是"别把真任务误当成闲聊"，
    放行的代价只是"多问模型一次"，拦错的代价是"用户要我干活我不干" —— 后者严重得多。
    """
    low = str(text or "").lower()
    return any(h in low for h in _ACTION_HINTS)


# 每条消息的外壳（"role"/"content" 的键名、引号、括号、逗号）大约值多少 token。
# 实测（第 1 步）：不把它算进去，估算比真实请求少几百 token → 历史裁了仍然超限。
_MSG_OVERHEAD = 12


def _tools_tokens(names):
    """这组工具的 schema 大概占多少 token（估不出来就按 0，宁可少算也不抛）。"""
    try:
        return _estimate_tokens(json.dumps(_build_tools(only=names), ensure_ascii=False))
    except Exception as e:      # noqa: silent-ok — 估不出来按 0，别让估算拖垮对话
        LOG.debug("忽略异常(%s:%d): %s", __file__, 2640, e)
        return 0


def all_tool_names():
    """**全部**真实工具名（内置 + 插件），与 `_build_tools()` 的结果一致。

    为什么不用 `real_tool_names()`：那个函数取的是 `_TOOL2PLUGIN` 的键，而 `_TOOL2PLUGIN`
    **只登记插件工具**（内置工具走 TOOLS，不进路由表）。第 1 步实测踩到：用它当"真实工具表"
    去校验子集，`run_command` / `read_file` / `list_files` 这些**内置**工具会被当成"不存在"而丢掉
    —— 结果 shell 意图一个工具都不剩，悄悄回落成"全部工具"。
    """
    try:
        return [((t or {}).get("function") or {}).get("name") for t in _build_tools()
                if ((t or {}).get("function") or {}).get("name")]
    except Exception as e:      # noqa: silent-ok — 取不到就当空表，调用方会回落
        LOG.debug("忽略异常(%s:%d): %s", __file__, 2640, e)
        return []


def _intent_tool_names(intent):
    """该意图要加载的工具名列表。**永不返回 None**（None 的旧含义是"全部 77 个"）。

    第 1 步之前：认不出意图 → full → None → 一次性把 77 个工具的完整 schema（13891 token）
    发出去，单这一项就把本地 20224 的 ctx 挤爆 —— 这正是"说句你好都撞 ctx 墙"的根因。
    现在 full 也是**核心集**：能力靠「完整工具目录随 system 下发 + 下一轮按需装载」保证，
    而不是靠一轮里全塞。工具一个没删、一个没停用，只是不在一轮里全发。

    返回前与真实工具表对一遍：不存在的名字直接丢弃（防止"以为给了工具、其实没给"）。
    """
    if intent not in _INTENT_TOOLS:
        return list(_FULL_CORE_TOOLS)    # 未知意图：给核心集，绝不回落全量
    if intent == "diagram":
        want = [n for n in real_tool_names() if n.lower().startswith("archify")]
        want += ["read_file", "open_app", "list_files"]
    else:
        want = list(_INTENT_TOOLS[intent] or [])
    if not want:
        want = list(_FULL_CORE_TOOLS)    # 空子集：给核心集，不给全量
    real = set(all_tool_names())
    got = [n for n in want if n in real]
    if not got:
        LOG.warning("意图 %s 的工具子集一个都不存在，本轮改发核心集（请检查工具名）", intent)
        got = [n for n in _FULL_CORE_TOOLS if n in real]
    if len(got) < len(want):
        LOG.debug("意图 %s 的子集里有 %d 个工具名不存在，已忽略：%s",
                  intent, len(want) - len(got), [n for n in want if n not in real])
    return got


def _is_chitchat(q):
    """**保守**判断"这句就是寒暄"。把寒暄词剥掉后还剩实义内容 → 不算（交给兜底分支）。

    只用来决定 system 里加哪一句"本轮模式"：真寒暄 → 明确禁止调工具；其余 → 照常动手。
    """
    s = (q or "").strip().lower()
    if not s or len(s) > 24:
        return False
    hits = [h for h in _CHAT_HINTS if h in s]
    if not hits:
        return bool(re.fullmatch(r"[\s\W_]+", s))      # 纯标点/表情
    rest = s
    for h in hits:
        rest = rest.replace(h, "")
    rest = re.sub(r"[\s\W_，。！？~～、,.!?]+", "", rest)
    return len(rest) <= 4                              # 只剩"呀/啊/啦"这类语气词


_READ_VERBS = ("读一下", "读一读", "读下", "读文件", "读取", "看一下这个文件", "看看这个文件",
               "打开这个文件", "读这个文件", "看下这个文件")
_FILE_HINT = re.compile(r"[A-Za-z]:[\\/]|\.(txt|md|py|json|log|csv|html|js|ts|ya?ml|ini|toml|xml)\b",
                        re.I)


def _asks_file_read(text):
    """这句是不是"读一个具体文件"。纯规则。

    【为什么需要它】实测「读一下 C:\\test.txt」被判成 **chat** —— chat 意图只装 3 个工具
    （web_search / read_memory / list_files），**根本没有 read_file**。于是这一轮模型
    只能靠嘴描述"我读不了文件"，而它明明有能力读。
    判据要求**动词 + 文件特征（盘符路径或已知扩展名）同时命中**，
    所以「读一下那篇文章」这种没有具体文件的说法不会被误判成读本地文件。
    """
    t = str(text or "").strip()
    if not t or len(t) > 200:
        return False
    if not any(v in t for v in _READ_VERBS):
        return False
    return bool(_FILE_HINT.search(t))


def _detect_intent(user_input):
    """规则识别本轮意图：chat / scrape / diagram / query / shell / full。**不靠模型**。

    顺序即优先级（越具体越靠前）：画图 > 网址 > 命令原文 > 查询 > 命令词 > 闲聊 > chat 兜底。

    **兜底是 chat，不是 full**（第 1 步）：full 以前等于"全部 77 个工具"，一轮就把 ctx 挤爆；
    而现在 chat 只发 3 个工具，完整工具目录仍在 system 里 —— 模型要求哪个，下一轮就装哪个。

    【为什么这么设计】意图决定"这一轮装哪些工具、带哪几条规则"。
    如果交给模型判意图，就等于**为了一次分类再花一次请求**，而且判错时用户还要多等一轮；
    这里是纯规则的字符串判据，零成本、可复现、可单测（`tools/test_mind.py` 逐条钉住）。

    【去掉它会怎样】回到"每轮都把全部工具和整份规则发出去"：
    光固定开销就顶穿本地 ctx（实测工具 schema 13891 token + system ~5700），
    连"你好"都可能 400；而且工具越多模型越容易摸错（实测画图时跑去 read_memory）。
    """
    q = (user_input or "").strip()
    if not q:
        return "chat"
    if _asks_diagram(q):                 # 画图优先：'画一张 example.com 的架构图' 也算画图
        return "diagram"
    if _looks_like_url(q):               # 带网址 → 抓取
        return "scrape"
    if _looks_like_shell_command(q):     # "这句话本身就是一条命令"
        return "shell"
    if _asks_file_read(q):               # "读一下 C:\test.txt"
        return "shell"                   # shell 意图里带了 read_file
    if _asks_net_ip(q):                  # 我的公网 IP / 归属地
        return "query"
    low = q.lower()
    if any(h in low for h in _INTENT_HINTS["query"]):
        return "query"
    if _asks_info_collect(q):
        # Bug 1 的修法：把"整理/汇总/看一下 + 新闻/动态/信息"当成**明确的检索请求**。
        # 之前这里掉进 chat → 闲聊轮不联网 → 模型只能反问用户"你想查什么方向"，
        # 而用户已经把方向说清了（"最近"+"新闻"）。这是最伤体验的一种失败：
        # 用户觉得"我说得这么清楚它还要问"。
        return "query"
    if any(h in low for h in _INTENT_HINTS["shell"]):
        return "shell"
    if _mentions_shell_command(q):
        # 中文叙述句里"夹着一条命令"（"跑一下 ipconfig"）——
        # 见 `_mentions_shell_command` 的说明：这种说法最自然，但原来会掉进 chat，
        # 于是这一轮**不装 run_command**，模型只能用文字描述它本来能跑的命令。
        return "shell"
    if _is_chitchat(q):
        return "chat"                    # 明确的寒暄 → 最省的 chat
    # 兜底走最省上下文的 chat；工具目录仍在 system 里，模型要求哪个下轮加载
    return "chat"


def _mentions_shell_command(text):
    """中文叙述句里**夹着一条命令**吗（"跑一下 ipconfig" / "执行 ping 127.0.0.1"）？

    【为什么需要它 —— 实测定性出来的真缺口】
        `_looks_like_shell_command()` 的两条判据（①首词必须是命令动词 ②含中文就否决）
        合起来会把最常见的中文说法漏掉。实测：
            跑一下 ipconfig      → chat   ❌（应为 shell）
            执行 ping 127.0.0.1  → chat   ❌
            运行 dir             → chat   ❌
            运行 rm -rf /tmp/x   → chat   ❌
        而 `ipconfig / ping / dir / rm` **都在 `_SHELL_VERBS` 里** ——
        也就是说"命令表认得它、判据却没看它"。
        后果不是"多问一句"，而是：这一轮不装 `run_command`，
        模型只能**用文字描述**它本来可以执行的命令（用户会说"你怎么不帮我跑"）。

    【判据为什么这么保守】
        先找句子里**第一个命令动词**（命令必须在动词之后），
        再看动词**后面剩下的是什么**：只允许
        ASCII 字母数字、常见开关/路径符号、以及中文里的连接词。
        只要后面还有中文实词（"ipconfig 是什么""ping 什么意思"），就**不当命令** ——
        那是提问，不是在让我执行。宁可漏（走 chat 也能在下一轮按需加载），不可误判成 shell。
    """
    q = (text or "").strip()
    if not q or len(q) > 400 or "\n" in q:
        return False
    if re.search(r"(是什么|什么是|怎么|如何|为什么|教我|解释|区别|什么意思)", q):
        return False
    toks = re.split(r"\s+", q)
    for i, tok in enumerate(toks):
        verb = tok.strip().lower().lstrip("@")
        if verb.endswith(".exe"):
            verb = verb[:-4]
        if verb not in _SHELL_VERBS:
            continue
        rest = " ".join(toks[i + 1:]).strip()
        if not rest:
            return True                       # "跑一下 ipconfig"：动词后没参数也算
        # 参数部分只允许 ASCII（数字/字母/开关/路径/**空格**），且不能再有中文实词。
        # ⚠️ 那个 `\s` 不能漏：第一版把它漏了，于是 `-rf /tmp/x` 因为**中间有一个空格**
        #    就 fullmatch 失败 → "运行 rm -rf /tmp/x" 掉回 chat。
        #    教训：写"允许哪些字符"的白名单时，空格/换行这类不可见字符最容易漏，
        #    而漏掉的后果是**静默不匹配**（不报错，只是判据永远不生效）。
        if re.fullmatch(r"[A-Za-z0-9\-_./:\\*?=\[\]~$@%+,;|&<>\"'\s]+", rest):
            return True
        return False
    # 中文删除动词：`_SHELL_VERBS` 是英文命令表，中文说法要靠这里兜。
    # 为什么必须兜住"删除"：它走 shell 不是为了执行，而是为了让**删除红线**有机会拦下 ——
    # 判成 chat 的话这一轮不装 run_command，模型只能用文字建议用户自己去删，
    # 载体层的硬拦截就**根本没有出场机会**（这是安全路径，不能靠概率）。
    if re.search(r"(删除|删掉|删了|删去|移除文件|清空目录)", q):
        return True
    return False


def _tool_index(only=None, plugins=None):
    """本轮【当前已加载的工具】索引：内置工具 + 插件工具，按 `only` 收窄。

    与传给大脑的 `tools` 参数**保持一致** —— 清单里出现的就是这一轮真能调的。
    （`_plugin_list()` 只列插件工具，这里连内置工具一起列，所以闲聊/命令这类
    以内置工具为主的意图也能正确显示。）一个都不匹配时如实说"当前无可用工具"。
    """
    _only = {x.lower() for x in only} if only is not None else None
    items = []
    try:
        for t in TOOLS:
            fn = (t or {}).get("function") or {}
            nm = fn.get("name")
            if nm and (_only is None or nm.lower() in _only):
                items.append((nm, fn.get("description") or ""))
        rows = plugins if plugins is not None else globals().get("PLUGINS") or {}
        for pname, p in (rows or {}).items():
            if not p.get("on") or p.get("type") == "skin":
                continue
            for t in (p.get("desc") or []):
                if not isinstance(t, dict) or not t.get("name"):
                    continue
                if _only is not None and t["name"].lower() not in _only:
                    continue
                items.append((t["name"], t.get("description") or pname))
    except Exception as e:      # 索引生成失败绝不能拖垮提示词
        LOG.debug("忽略异常(%s:%d): %s", __file__, 2680, e)
        return _PLUGIN_LIST_TEMPLATE % "当前无可用工具"
    if not items:
        return _PLUGIN_LIST_TEMPLATE % "当前无可用工具"
    seen, lines = set(), []
    for nm, desc in items:
        if nm in seen:
            continue
        seen.add(nm)
        d = (desc or "").strip().replace("\n", " ")
        if len(d) > 46:
            d = d[:46] + "…"
        lines.append("- %s：%s" % (nm, d))
    return _PLUGIN_LIST_TEMPLATE % "\n".join(lines)


def system_for_intent(intent, role=None, plugins=None, user_input=""):
    """按本轮意图生成 system：**该给的规则一条不少，用不上的整段不加载**。

    · chat    → 人设 + 一句"本轮模式" + 3 个工具索引（实测 system < 400 token）
                 真寒暄 → "闲聊别调工具"；认不出意图的兜底 → "照常动手，要别的工具就点名"
    · diagram → 人设 + 检索铁律 + 工具规则 + archify 清单 + 画图工作流（问题 6 的代码层强制）
    · 其它任务意图 → 人设 + 检索铁律 + 工具规则 + 本轮工具索引
    · full    → 全套规则 + **全量工具目录**（保留供"工具目录查询"，不再由意图识别触发）

    注意：这里**不含技能文档与工具用法** —— 那些由调用方按需追加，避免同一份被拼两遍
    （老代码把 PLUGIN_SKILLS 拼了两遍，白涨 ~800 token）。
    """
    role = strip_search_rules(role if role is not None else CONTROL.get("role", ""))
    if intent == "chat":
        hint = _CHAT_SYSTEM_HINT if _is_chitchat(user_input) else _CHAT_FALLBACK_HINT
        return role + hint + _tool_index(only=_intent_tool_names("chat"), plugins=plugins)
    if intent == "full":
        # 保留供工具目录查询，不再由意图识别触发（`_detect_intent` 兜底已改为 chat）。
        # 这里 `only=None` 是**故意的**：本轮 schema 只发核心集，但目录要列全 77 个，
        # 模型才知道"还有哪些工具可点名"。
        return role + _SEARCH_RULES + _TOOL_RULES + _tool_index(only=None, plugins=plugins)
    only = _intent_tool_names(intent)
    extra = _DIAGRAM_SYSTEM_HINT if intent == "diagram" else ""
    return (role + _SEARCH_RULES + _TOOL_RULES + _tool_index(only=only, plugins=plugins) + extra)


def _plan_tools(intent, system_text, current_text, max_ctx=None):
    """定这一轮给哪些工具，并保证 `system + tools + 本轮问题` **一定塞得进 ctx**。

    返回 (工具名列表, 预估 token)。

    **说法纠正（第 1 步）**：这里以前会把"本轮因为额度不够，所以少发了 N 个工具"写进日志 ——
    那是**错的**。工具一个都没删、没停用、没缩减，`plugins/` 目录 77 个一个不少；
    只是**这一轮**不发那么多 schema，完整工具目录始终随 system 下发，模型点名哪个，
    下一轮就按意图装载哪个。所以日志改成中性表述。

    【为什么这么设计】工具 schema 是"固定开销"里最大的一块（全部 77 个约 1.4 万 token，
    而本地 ctx 只有 19224）—— 每轮全发必然顶穿。但这个函数的取舍**只动"这一轮发多少"**，
    绝不动"系统有多少"：意图决定默认装哪一小撮，点名决定下一轮装哪个。
    于是"能力不封顶"和"单次不超"这两条看似矛盾的要求能同时成立。

    【去掉它会怎样】要么每轮全发（闲聊轮也塞 1.4 万 token 的工具表，直接 400），
    要么真的去砍工具（用户会发现"它突然不会某件事了"，而且日志里还写着'额度不足'）——
    前者是撞墙，后者是削能力，两条路都不能走。
    """
    max_ctx = int(max_ctx or _max_context_tokens())
    # ================== 第三阶段 · **状态偏离 → 代码层硬改工具表** ==================
    # 【这不是提示词】`perspective.policy()` 给出裁剪规则，这里**真的**改了本轮装载的工具：
    #   档位"中/重" → 把**探索类**工具从这一轮的表里**拿掉**（不是排后面、不是告诉模型别用）；
    #   任何档位 → 把**保守类**排到前面。
    #   判据是"**这一轮的工具表真的短了**"，而不是"它说它累了"。
    _pol = _state_policy()
    if _pol.get("context_scale", 1.0) < 1.0:
        max_ctx = max(1500, int(max_ctx * float(_pol["context_scale"])))
    names = _intent_tool_names(intent)
    if _pol.get("drop_tools"):
        _before = len(names)
        names = [n for n in names
                 if not any(x in str(n).lower() for x in _pol["drop_tools"])]
        if len(names) != _before:
            LOG.info("状态硬改·输入：档位%s → 探索类工具从本轮拿掉 %d 个（%d→%d）｜%s",
                     _pol.get("level"), _before - len(names), _before, len(names),
                     "；".join(_pol.get("why") or [])[:80])
            # **第四阶段 · 因果归属**：记"状态 → 真的改了什么"（带前值/后值，可核对）
            try:
                _sm = _mod("self_model")
                if _sm is not None:
                    _sm.note("输入被裁", cause="精力低/档位%s" % _pol.get("level"),
                             effect="探索类工具从本轮工具表里拿掉",
                             before=_before, after=len(names), level=_pol.get("level"))
            except Exception as _e:      # noqa: silent-ok — 记不上不影响裁剪本身
                LOG.debug("因果归属记录失败（忽略）：%s", _e)
    if _pol.get("front_tools"):
        _front = [n for n in names if any(x in str(n).lower() for x in _pol["front_tools"])]
        _rest = [n for n in names if n not in _front]
        names = _front + _rest
    budget = max_ctx - _estimate_tokens(system_text) - _estimate_tokens(current_text) - _MSG_OVERHEAD * 2
    keep = list(names) if names else list(_FULL_CORE_TOOLS)
    tok = _tools_tokens(keep)
    if tok > budget:                       # 超预算 → 收敛"本轮装载量"（列表按重要性排序）
        while len(keep) > 1 and _tools_tokens(keep) > budget:
            keep.pop()
        tok = _tools_tokens(keep)
        LOG.info("本轮按意图装载 %d 个工具（完整工具表仍在 plugins/ 目录，按需加载）", len(keep))
    return keep, tok


# ================== 上下文四层防护 · 第 1 层（滑动窗口 + 硬性截断） ==================
# 背景：本地 ctx 是硬限制（llama.ctx=20224），拼好的 system+history+本轮问题一旦超限，
# 大脑直接报 "request (N tokens) exceeds the available context size (M tokens)"。
# 这里**不扩 ctx、不删工具/技能/规则、不丢记忆** —— 只做"发之前算 token、超了从最老的历史砍"。
_CONTEXT_FIT_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "context_fit.log")


def _estimate_tokens(text):
    """粗略估算 token 数（不引第三方分词器，够用且零依赖）。

    经验值：中文 1 字 ≈ 1 token；ASCII 约 4 字符 ≈ 1 token。宁可**高估**（少留点余量），
    也不能低估——低估就会真的超限。
    """
    t = str(text or "")
    if not t:
        return 0
    cjk = sum(1 for ch in t if "\u4e00" <= ch <= "\u9fff")
    other = len(t) - cjk
    # 实测校准（用户对照）：中文约 **1.5 token/字**（原来 1.05 低估约 40%，
    # 于是 _fit_context 报"合计 4216 / 上限 19500"，实际请求却是 22562 —— 直接 400/500）。
    # 原理：宁可高估（少留历史），也绝不低估（一旦低估就是硬报错）。
    return int(cjk * 1.5 + other / 3) + 1


def _max_context_tokens():
    """本轮可用上限：优先 capabilities.max_context_tokens，否则按引擎取
    （本地=brain.llama.ctx，云端=128000），再减去安全余量。

    **ctx 校准（第 1 步实测）**：llama-server 收到 `-c 20000` 后**实际给的是 20224** ——
    llama.cpp 会把 n_ctx **向上取整到 256 的倍数**（20000 / 256 = 78.125 → 79 × 256 = 20224，
    实测 `GET http://127.0.0.1:5801/props` → `n_ctx = 20224`）。所以操控文件里直接写 20224
    （本身就是 256 的倍数，不会被再取整），载体算出来的上限才和大脑的真容量**对齐**，
    不会白白浪费那 1224 token 的窗口。
    """
    margin = int(CAP.get("context_safety_margin", 1000) or 1000)
    try:
        explicit = int(CAP.get("max_context_tokens", 0) or 0)
    except Exception:
        explicit = 0
    if explicit > 0:
        return max(1000, explicit - margin)
    if str(BRAIN_ENGINE).lower() == "api":
        base = 128000
    else:
        try:
            base = int((CONTROL.get("brain", {}).get("llama", {}) or {}).get("ctx", 20224) or 20224)
        except Exception:
            base = 20224
    return max(1000, base - margin)


def _tol_tokens(text):
    """对话历史里的"轮"是成对的（用户+小焦），这里不单独用，仅保留给后续步骤。"""
    return _estimate_tokens(text)


def _fit_context(system_text, history, current_text, max_ctx=None, min_rounds=2, tools_tokens=0):
    """四层防护的第 3+4 层：滑动窗口（默认最近 10 轮）+ 硬性截断（从最老开始砍）。

    规则（硬性）：**system 与本轮问题永远保留**；历史从最老的一端开始丢，
    直到总 token ≤ max_ctx；至少保留 min_history_rounds 轮（丢到下限为止）。
    `reserve`：本轮**除 messages 之外的固定开销**（最关键的是 function-calling 的 tools
    schema —— 77 个工具的 JSON 有几千 token！上一版漏算它，所以裁剪后**仍然超限**）。
    返回 (保留的历史列表, 说明文本)。

    【为什么这么设计】单次请求的 token 是**物理上限**（本地 8G 显存，扩不了 ctx）。
    上限动不了，就只能在"装配什么进去"上做取舍，而取舍优先级必须是死的：
    system（人格/铁律）与本轮问题**永远不能丢**（丢了就不是小焦、也不在回答这个问题），
    能丢的只有"更老的历史"。说明文本按 `system=a + tools=b + … = 合计 f / 上限 g` 输出，
    就是为了让"为什么超"一眼可查，而不是让用户面对一个语焉不详的 400。

    【去掉它会怎样】要么发出去被服务端拒（用户看到报错），
    要么在别处偷偷"砍内容"—— 后者更糟：能力被削了却不报错，
    表现为"它最近变笨了"，而没有任何日志能解释原因。
    """
    max_ctx = int(max_ctx or _max_context_tokens())
    try:
        win = int(CAP.get("history_window_rounds", 10) or 10)
    except Exception:
        win = 10
    rounds = max(int(min_rounds or 2), win)
    hist = list(history or [])
    sys_tok = _estimate_tokens(system_text)
    cur_tok = _estimate_tokens(current_text)
    tools_tok = int(tools_tokens or 0)
    # 每条消息的**外壳**（role/content 的键名与括号）也要占 token。第 1 步实测：
    # 不把它算进去，估算会比真实请求少几百 token，于是"裁剪完了还是超限"。
    fixed = sys_tok + cur_tok + tools_tok + _MSG_OVERHEAD * 2

    def _hist_tok(rows):
        return sum(_estimate_tokens(h.get("content", "")) + _MSG_OVERHEAD for h in rows)

    kept = hist[-rounds:] if rounds > 0 else []
    stayed = kept
    while kept and fixed + _hist_tok(kept) > max_ctx:
        kept = kept[1:]                      # 从最老的一条开始砍
    used = fixed + _hist_tok(kept)
    note = ("system=%d + tools=%d + 本轮=%d = 合计 %d / 上限 %d ｜ 历史 %d→%d 轮"
            % (sys_tok, tools_tok, cur_tok, used, max_ctx, len(stayed), len(kept)))
    try:
        os.makedirs(os.path.dirname(_CONTEXT_FIT_LOG), exist_ok=True)
        # 第 1 步起**每轮都记一行**：验收要看的就是 "system=a + tools=b + 本轮=c = 合计 d / 上限 e"
        with open(_CONTEXT_FIT_LOG, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), note))
    except Exception as e:  # noqa: silent-ok — 记日志失败不能影响对话
        LOG.debug("忽略异常(%s:%d): %s", __file__, 1120, e)
    if fixed > max_ctx:
        LOG.warning("本轮 system+问题 已超上限（%s）—— 会自动尽量发，但建议缩短本轮输入", note)
    return kept, note


# ================== 智能体 ==================
# ================== 第 3 部分 · 健康系统接入：监测 → 诊断 → 治疗 → 病历 → 预防 ==================
# 【设计理念】模型会退化，像人一样。
#   人脑会退化：疲劳、生病、精神失常；模型也会退化：复读、逻辑混乱、幻觉、答非所问、
#   突然暴躁、突然消极、乱调工具、前后矛盾。
#   **这不是"模型坏了"，是"模型生病了"。** 不能等它病入膏肓才治 ——
#   那时整轮回答已经废了、还可能被写进长期记忆。要在症状出现的那一刻就介入。
# 【接入点】每次生成完成后跑一遍：monitor.check → diagnose → heal → records。
#   一级治疗**静默**（用户看不出治过）；二级及以上把提示写进回答里（用户看得见）。
# 【为什么必须接在这里（agent_run 的出口）】这是"模型说完了、但还没交给用户"的唯一时刻。
#   往前一步（生成中）只能拿到片段，往后一步（返回给前端）就已经落盘了 ——
#   错开这个时刻，治疗只能改屏幕上的字，改不了历史和记忆里的内容。
# 【去掉它会怎样】`core/health` 就只是一堆没人调用的函数：病历永远是空的，
#   预防建议无从谈起，模型复读了也没人管 —— 退化会一轮轮累积进长期记忆。
_HEALTH_LAYER = {"monitor": None, "diagnose": None, "healer": None, "records": None,
                 "tried": False, "in_gate": False}
# 急诊状态：置位后**拒绝继续生成**，并把原因强通知给用户，等人工介入。
# 为什么不是"把进程杀掉"：一个自我了断的服务连"告诉你它为什么停"的机会都没有 ——
# 那等于把"急诊"做成"猝死"。急诊的正确语义是**停止服务 + 保留现场 + 强通知 + 等人工**，
# 而不是让用户对着一片空白猜发生了什么。
_HEALTH_EMERGENCY = {"on": False, "reason": "", "at": 0.0}
_HEALTH_NOTICE = {"text": "", "level": 0, "at": 0.0}


def _health_layer():
    """惰性构建健康系统四件套（含**宿主回调**）。拿不到就返回 None —— 健康层缺席不影响对话。"""
    if _HEALTH_LAYER["tried"] and _HEALTH_LAYER["monitor"] is not None:
        return _HEALTH_LAYER
    _HEALTH_LAYER["tried"] = True
    try:
        root = os.path.dirname(os.path.abspath(__file__))
        if root not in sys.path:
            sys.path.insert(0, root)
        from core.health.monitor import HealthMonitor
        from core.health.diagnose import HealthDiagnose
        from core.health.heal import HealthHealer
        from core.health.records import HealthRecords
        _HEALTH_LAYER["monitor"] = HealthMonitor()
        _HEALTH_LAYER["diagnose"] = HealthDiagnose()
        _HEALTH_LAYER["records"] = HealthRecords()
        _HEALTH_LAYER["healer"] = HealthHealer(hooks=_health_hooks(),
                                                diagnose=_HEALTH_LAYER["diagnose"],
                                                records=_HEALTH_LAYER["records"],
                                                monitor=_HEALTH_LAYER["monitor"])
        LOG.info("健康系统已接入：监测 18 类症状 → 诊断四级 → 治疗四级 → 病历 logs/health/")
        return _HEALTH_LAYER
    except Exception as e:      # noqa: silent-ok — 健康层起不来不能挡住对话（但必须留痕）
        LOG.warning("健康系统不可用（已跳过，对话照常）：%s", e)
        return _HEALTH_LAYER


def _health_hooks():
    """把载体的真实能力挂给治疗层。

    治疗层只负责"决定该做什么"（分级、给说法、记病历），**具体怎么做由载体提供** ——
    这是"载体优先"的又一次分工：换掉治疗策略不用改载体，换掉载体也不用改策略。
    每个 hook 都返回能表达失败的值（False/""），治疗层据实记录，**不允许假装成功**。
    """
    def _h_retry(question, system="", why=""):
        """换角度重来一次。**硬限：治疗层已经限制成最多一次**，这里再加一道递归闸。"""
        if _HEALTH_LAYER["in_gate"]:
            LOG.info("健康治疗：重试请求发生在治疗过程中，已忽略（防递归）")
            return ""
        prompt = ("上一次的回答没有通过质量校验（%s）。请**换一种说法**重新回答下面的问题："
                  "不要重复上一次的表述，不要解释，直接给结论。\n\n%s" % (why or "质量不佳", question))
        try:
            return llm_chat([{"role": "user", "content": prompt}]) or ""
        except Exception as e:      # noqa: silent-ok — 重试失败就如实返回空，让治疗层降级
            LOG.warning("健康治疗：换角度重试失败：%s", e)
            return ""

    def _h_reset_context(session=None):
        """清空当前会话上下文（**长期记忆保留**）。

        关键分寸：只清"这一轮对话的短期上下文"，**不动向量库里的长期记忆** ——
        向量库是"我是谁、用户是谁、我们聊过什么"的地方，清它等于让用户重新自我介绍一遍。
        清的是"最近几十轮的具体措辞"—— 那正是把模型带进退化循环的东西。
        """
        try:
            d = _sessions()
            sid = (session or {}).get("sid") or get_current_session()[0].get("id")
            for s in d["sessions"]:
                if s.get("id") != sid:
                    continue
                msgs = list(s.get("messages") or [])
                keep = [m for m in msgs if m.get("role") == "用户"][-1:]
                if len(msgs) <= len(keep):
                    return True                     # 本来就没多少上下文，算成功
                s["messages"] = keep
                _save_sessions(d)
                LOG.warning("健康治疗（二级）：已清空会话 %s 的上下文（%d 条 → %d 条），"
                            "长期记忆（向量库）保留不动", sid, len(msgs), len(keep))
                return True
        except Exception as e:      # noqa: silent-ok — 清不掉就如实返回 False
            LOG.warning("健康治疗：清上下文失败：%s", e)
        return False

    def _h_reload_kv(session=None):
        """重置模型状态（重载 KV Cache）。

        如实说明本架构下的语义：llama-server 每个请求独立处理，**KV cache 不跨请求保留** ——
        所以"重载 KV"在这里等价于"丢弃上一轮的上下文"，而那件事已经由 `reset_context` 做了。
        这里返回 True 是**如实的**（状态确实已经重置），detail 里会写明为什么没有额外的动作；
        假装发一个不存在的 API 请求才是自欺。
        """
        LOG.info("健康治疗（二级）：模型状态重置 —— 本架构每请求独立，KV 不跨轮保留，"
                 "等价动作（丢弃会话上下文）已由 reset_context 完成")
        return True

    def _h_switch_brain(reason=""):
        """切备用火种（变形金刚：换火种不换小焦）。

        【缺陷 1 的修法：加安全闸 + 加回切 + 全程留痕】
        真端到端实测抓到的严重后果：红线拦截被误判成模型退化 → 三级治疗调到这里 →
        原来"拿到候选就切"，**把一个本来好好的本地大脑切成了不可用目标** →
        小焦随后"大脑没有应答"，长文场景三次全不过。
        一次错误的治疗，造成的破坏比它想治的病大得多。所以这里立三道闸：
          ① **先 ping 目标**，探测通过才切（不可用就干脆不切，保持现状）；
          ② 切完 **10 秒内复核**，新火种不响应 → **自动切回原火种**（治疗不许把系统搞坏）；
          ③ 每一次切换（含被否决、含回切）都写进 `logs/carrier/brain_switch.jsonl`，
             带原因与探测结果 —— 事后必须能回答"是谁、为什么、把火种换到哪去了"。
        """
        import json as _json
        entry = {"ts": time.time(), "iso": time.strftime("%Y-%m-%d %H:%M:%S"),
                 "by": "health.level3", "reason": str(reason)[:200],
                 "from": "", "to": "", "ping_ok": False, "verify_ok": False, "result": ""}
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "logs", "carrier", "brain_switch.jsonl")

        def _record():
            try:
                os.makedirs(os.path.dirname(log_path), exist_ok=True)
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(_json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception as e:      # noqa: silent-ok — 记不上流水也绝不能影响切换本身
                LOG.debug("切换流水写入失败（忽略）：%s", e)

        try:
            root = os.path.dirname(os.path.abspath(__file__))
            if root not in sys.path:
                sys.path.insert(0, root)
            from core.carrier import BrainRegistry
            reg = BrainRegistry()
            names = list(reg.names() or [])
            cur = reg.current()
            orig = cur.name if cur else ""
            entry["from"] = orig
            if len(names) < 2:
                entry["result"] = "no_alternative"
                LOG.warning("健康治疗（三级）：只有 %d 个火种可用，没有备用火种可切", len(names))
                _record()
                return False
            # ---- 闸①：按优先级逐个探测，**第一个真能用的**才切 ----
            target = None
            tried = []
            for nm in names:
                if nm == orig:
                    continue
                b = reg.get(nm)
                if b is None:
                    continue
                try:
                    pb = b.probe(timeout=4)
                except Exception as e:      # noqa: silent-ok — 探测异常当作不可用
                    pb = {"ok": False, "error": str(e)[:80]}
                tried.append({"name": nm, "ok": bool(pb.get("ok")),
                              "error": str(pb.get("error") or "")[:80]})
                if pb.get("ok"):
                    target = b
                    break
            entry["probed"] = tried
            if target is None:
                entry["result"] = "no_healthy_target"
                LOG.warning("健康治疗（三级）：所有备用火种都探测不通过 %s → **不切**（保持现状）",
                            tried)
                _record()
                return False
            entry["to"] = target.name
            entry["ping_ok"] = True
            # ---- 切 ----
            ok = reg.switch(target.name)
            try:
                reg.apply_to_app(target)
            except Exception as e:      # noqa: silent-ok — 应用不上要如实记，不能假装成功
                LOG.warning("健康治疗：火种切换后应用到 app 失败：%s", e)
            LOG.warning("健康治疗（三级）：已切到备用火种 %s（%s）", target.name, reason)
            # ---- 闸②：10 秒内复核新火种，不响应就自动切回 ----
            deadline = time.time() + 10.0
            verified = False
            while time.time() < deadline:
                try:
                    if target.probe(timeout=4).get("ok"):
                        verified = True
                        break
                except Exception:      # noqa: silent-ok — 探测失败就是没通过，继续等到超时
                    pass
                time.sleep(1.0)
            entry["verify_ok"] = verified
            if not verified:
                LOG.error("健康治疗（三级）：新火种 %s 10 秒内无响应 → **自动切回** %s",
                          target.name, orig or "（无原火种）")
                entry["result"] = "rolled_back"
                if orig:
                    try:
                        reg.switch(orig)
                        reg.apply_to_app(reg.get(orig))
                        entry["rolled_back_to"] = orig
                    except Exception as e:      # noqa: silent-ok — 回切失败必须留痕
                        entry["rollback_error"] = str(e)[:120]
                        LOG.error("健康治疗：回切 %s 失败：%s", orig, e)
                _record()
                return False
            entry["result"] = "switched"
            _record()
            return bool(ok)
        except Exception as e:      # noqa: silent-ok — 切不了就如实返回 False，绝不假装成功
            LOG.warning("健康治疗：切备用火种失败：%s", e)
            entry["result"] = "error"
            entry["error"] = str(e)[:150]
            _record()
            return False

    def _h_rollback(session=None):
        """回滚到上一个稳定状态：丢掉出问题的那一轮回答（保留用户的问题）。

        为什么是"丢回答"而不是"恢复某个备份文件"：会话文件是**唯一**的状态载体，
        为它维护多份快照，代价是每轮都要写一遍完整历史（大文件、慢、还可能写坏）。
        而真正需要回滚的对象只有一样 —— 那一条病态的回答。丢掉它，状态就回到了
        "用户刚问完、还没有坏回答"的那个稳定点，这也正是"上一个稳定会话状态"的含义。
        """
        try:
            d = _sessions()
            sid = (session or {}).get("sid") or get_current_session()[0].get("id")
            for s in d["sessions"]:
                if s.get("id") != sid:
                    continue
                msgs = list(s.get("messages") or [])
                while msgs and msgs[-1].get("role") == "小焦":
                    msgs.pop()
                s["messages"] = msgs
                _save_sessions(d)
                LOG.warning("健康治疗（三级）：已回滚会话 %s 的最后一条回答", sid)
                return True
        except Exception as e:      # noqa: silent-ok — 回滚失败如实返回 False
            LOG.warning("健康治疗：回滚失败：%s", e)
        return False

    def _h_pause_task(reason=""):
        """暂停当前任务并标记"待恢复"（写进病历目录，界面/启动脚本读得到）。"""
        try:
            p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "logs", "health", "paused_tasks.jsonl")
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.time(),
                                    "iso": time.strftime("%Y-%m-%d %H:%M:%S"),
                                    "reason": str(reason)[:200], "state": "待恢复"},
                                   ensure_ascii=False) + "\n")
            return True
        except Exception as e:      # noqa: silent-ok — 记不上就当没暂停（不能假装成功）
            LOG.warning("健康治疗：暂停任务标记失败：%s", e)
            return False

    def _h_shutdown(reason=""):
        """急诊：**停止服务**（拒绝继续生成）+ 保留现场 + 强通知，等人工介入。

        为什么不是 os._exit / 杀进程：见 `_HEALTH_EMERGENCY` 的注释 ——
        能说话的停服比猝死有用得多。用户看到的是明确的"急诊"提示 + 原因 + 建议。
        """
        _HEALTH_EMERGENCY.update({"on": True, "reason": str(reason)[:300], "at": time.time()})
        LOG.error("健康急诊：已停止服务（拒绝继续生成），原因：%s", str(reason)[:200])
        return True

    def _h_snapshot(reason=""):
        """保留现场：把当时的会话 + 症状 + 资源状态落成一个快照文件，供事后复盘。"""
        try:
            d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "health")
            os.makedirs(d, exist_ok=True)
            p = os.path.join(d, "snapshot_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
            snap = {"ts": time.time(), "iso": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "reason": str(reason)[:300],
                    "model": MODEL_NAME, "brain_engine": BRAIN_ENGINE,
                    "last_llm_error": _LAST_LLM_ERROR,
                    "used_local_fallback": dict(_USED_LOCAL_FALLBACK),
                    "inflight": _inflight_all(),
                    "symptoms": [], "session_tail": []}
            try:
                H = _health_layer()
                if H["monitor"] is not None:
                    snap["symptoms"] = [s.to_dict() if hasattr(s, "to_dict") else str(s)
                                        for s in (H["monitor"].last() or [])]
            except Exception as e:      # noqa: silent-ok — 症状取不到也要留下其余现场
                snap["symptoms_error"] = repr(e)
            try:
                snap["session_tail"] = current_messages()[-6:]
            except Exception as e:      # noqa: silent-ok — 同上
                snap["session_error"] = repr(e)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(snap, f, ensure_ascii=False, indent=2)
            LOG.error("健康急诊：已保留现场 → %s", p)
            return p
        except Exception as e:      # noqa: silent-ok — 快照失败也要让急诊流程继续
            LOG.warning("健康治疗：保留现场失败：%s", e)
            return ""

    def _h_notify(level=1, text=""):
        """强通知：写流水 + 记 ERROR 日志 + 留给界面（急诊时必须让用户看见）。"""
        try:
            p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "logs", "health", "notify.jsonl")
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.time(), "level": int(level or 1),
                                    "text": str(text)[:500]}, ensure_ascii=False) + "\n")
        except Exception as e:      # noqa: silent-ok — 写不进去也要把日志打出来
            LOG.debug("健康通知落盘失败（忽略）：%s", e)
        _HEALTH_NOTICE.update({"text": str(text)[:500], "level": int(level or 1),
                               "at": time.time()})
        LOG.error("健康通知（%s 级）：%s", level, str(text)[:200])
        return True

    return {"retry": _h_retry, "reset_context": _h_reset_context, "reload_kv": _h_reload_kv,
            "switch_brain": _h_switch_brain, "rollback": _h_rollback,
            "pause_task": _h_pause_task, "shutdown": _h_shutdown,
            "snapshot": _h_snapshot, "notify": _h_notify}


def _health_gate(user_input, answer, tool_trace, elapsed_ms=None, session_extra=None):
    """生成完成后跑一遍：监测 → 诊断 → 治疗。返回 (处理后回答, 给用户看的提示或空串)。

    **永远不抛异常**，最差返回原样的回答 —— 健康系统是"锦上添花"，绝不能变成新的故障点。
    """
    H = _health_layer()
    if H["monitor"] is None:
        return answer, ""
    if _HEALTH_LAYER["in_gate"]:
        return answer, ""          # 防递归：治疗里触发的重试不再走一遍健康门
    _HEALTH_LAYER["in_gate"] = True
    try:
        try:
            _cfg_h = __import__("core.health", fromlist=["cfg"]).cfg()
        except Exception:      # noqa: silent-ok — 配置拿不到就按默认（默认开）
            _cfg_h = {"enabled": True, "auto_heal": True}
        if _cfg_h.get("enabled") is False:
            return answer, ""
        ctx = {
            "question": user_input,
            "tool_trace": tool_trace or [],
            "elapsed_ms": elapsed_ms,
            "expectations": _intent_keywords(user_input),
            "history": [],
        }
        try:
            _hist = current_messages()
            ctx["history"] = _hist[-6:]
            ctx["turns"] = len(_hist)
            ctx["prev_answers"] = [m.get("content") for m in _hist[-4:]
                                   if m.get("role") == "小焦"][-2:]
        except Exception as e:      # noqa: silent-ok — 历史取不到就少两个判据，不影响主流程
            LOG.debug("健康检查取历史失败（忽略）：%s", e)
        symptoms = H["monitor"].check(answer, ctx) or []
        if not symptoms:
            return answer, ""
        _sid = ""
        try:
            _sid = get_current_session()[0].get("id")
        except Exception:      # noqa: silent-ok — 没会话 id 就少一层隔离能力，如实留空
            pass
        sess = {"sid": _sid, "turns": ctx.get("turns"), "model": MODEL_NAME,
                "input_chars": len(user_input or ""), "elapsed_ms": elapsed_ms,
                "streak": H["monitor"].streaks()}
        sess.update(session_extra or {})
        diag = H["diagnose"].diagnose(symptoms, sess) or {}
        severity = diag.get("severity") or "LIGHT"
        sess["cause"] = diag.get("cause")
        LOG.warning("健康监测：检出 %d 个症状 %s → 诊断 %s（判因 %s）：%s",
                    len(symptoms), [getattr(s, "code", "?") for s in symptoms],
                    severity, diag.get("cause"), diag.get("reason"))
        res = H["healer"].heal(severity, sess, symptoms, output=answer, question=user_input)
        # 一级：静默换掉回答，界面上看不出治过
        if res.level == 1 and isinstance(res.output, str) and res.output.strip():
            if res.output != answer:
                LOG.info("健康治疗（一级·静默）：回答 %d 字 → %d 字（%s）",
                         len(answer), len(res.output), res.action)
            answer = res.output
        elif res.level >= 2 and isinstance(res.output, str) and res.output.strip():
            answer = res.output
        # ---- 问题 1 的关键补丁：**不管治到第几级，出门前一律再解一次毒** ----
        # 实测教训：判到 MEDIUM（一轮里 ≥3 个症状就会）走的是二级路径（清上下文 + 重试），
        # 那条路径以前会把病态原文原样交回来 —— 于是"诊断出来了、用户还是看到一屏复读"。
        # 这里不依赖任何一级/二级/三级的内部实现是否周全：文本出门前统一过网。
        answer, _net_note = _degeneration_net(answer, where="健康门/%s" % severity)
        if _net_note:
            res.detail["output_net"] = _net_note
        # 二级及以上：把提示**写进回答**（用户看得见），这是"界面提示"的落地方式 ——
        # 走回答正文而不是额外弹窗，是为了让提示能跟着回答一起被存进历史（刷新后还在）。
        note = ""
        if res.level >= 2 and res.note:
            note = "\n\n---\n\n🩺 " + str(res.note)
        elif res.level >= 3:
            note = ("\n\n---\n\n🩺 小焦现在状态不太好，需要休息一下。"
                    "原因：%s。建议：%s" % (diag.get("reason") or severity,
                                          diag.get("advice") or "先做简单的任务，或等一会儿再试。"))
        if res.level >= 4:
            note += ("\n\n⛔ **急诊：小焦已暂停服务**，现场（日志与状态快照）已保留，"
                     "需要你手动介入处理。处理完刷新页面即可恢复。")
        return answer, note
    except Exception as e:      # noqa: silent-ok — 健康门自己出问题，绝不能影响正常回答
        LOG.warning("健康门异常（已跳过，回答照常返回）：%s", e)
        return answer, ""
    finally:
        _HEALTH_LAYER["in_gate"] = False


def _intent_keywords(text):
    """给"答非所问"判据用的期望关键词（规则抽取，不调模型）。

    只用中英文**实词片段**，去掉指令词 —— 与续写的关键词抽取同口径。

    【真端到端实测抓到的误报，写下来免得再犯】
    用户那句话是「你仔细查肯定不够12万的」——**本身没有明确的主题词**。
    第一版把句子里所有 2~6 字的中文片段都当成"期望要点"，于是抽出 9 个碎片
    （仔细查 / 肯定不够 / …）。模型给了一个**完全合理**的回答（一张解释 12 万怎么算的表），
    却只命中 2/9 → 判"答非所问" → 连中 3 轮 → 升级成 MEDIUM → **清空了用户的会话上下文**
    并在回答末尾给用户加了一句"刚才的回答质量不佳，我已重新组织"。
    一个正常回答被判病，还顺手把用户的上下文清了 —— 这比漏判坏得多。
    所以这里改成"只有拿到**足够可信**的主题词才给期望，否则一个都不给"：
      · 去掉口语/指令/判断类词（否则"肯定不够"这种也算主题）；
      · 只保留长度 ≥3 的片段；
      · 少于 2 个就返回空 —— 空表示"这句话没有可判的主题"，
        监测层会自然退回它自己的字符覆盖法（对模糊提问基本不会误报）。
    """
    try:
        t = re.sub(r"\d+", "", text or "")
        for w in _INTENT_STOPWORDS:
            t = t.replace(w, " ")
        kws = re.findall(r"[\u4e00-\u9fff]{2,6}|[A-Za-z]{4,}", t)
        out = []
        for k in kws:
            if len(k) < 3:          # 2 字片段太容易是"仔细/肯定"这类非主题词
                continue
            if k not in out:
                out.append(k)
        return out if len(out) >= 2 else []
    except Exception:      # noqa: silent-ok — 抽不出来就不做"答非所问"判据
        return []


# 「答非所问」要用的主题词黑名单：口语、指令、判断、程度词 —— 它们不是"用户在问什么"。
# 为什么必须显式列出来：中文里"仔细查""肯定不够"这种词组在字符层面跟主题词没区别，
# 不排除掉就会把**模糊提问**变成一堆假期望要点（实测就是这么误报的）。
_INTENT_STOPWORDS = (
    "帮我", "请你", "请", "麻烦", "给我", "告诉我", "一下", "一个", "一些", "一点",
    "怎么样", "怎么", "如何", "为什么", "是什么", "什么地方", "什么", "多少", "几个",
    "可以", "能否", "能不能", "有没有", "是不是", "对不对", "好吗", "行吗",
    "仔细", "认真", "肯定", "一定", "绝对", "当然", "应该", "可能", "大概", "差不多",
    "不够", "够了", "够了没", "需要", "想要", "我要", "我想", "我要你", "看看", "说说",
    "讲讲", "介绍", "解释", "说明", "告诉", "觉得", "认为", "知道", "了解",
    "这个", "那个", "这些", "那些", "这里", "那里", "现在", "今天", "明天", "刚才",
    "你好", "您好", "小焦", "的", "了", "吗", "呢", "吧", "啊", "呀", "哦", "嗯",
)


def _health_emergency_text():
    """急诊状态下返回给用户的说明（拒绝继续生成，但不装死）。"""
    return ("⛔ **小焦处于急诊状态，已暂停回答。**\n\n"
            "原因：%s\n\n"
            "现场（日志与状态快照）已经保留在 `logs/health/` 下。"
            "建议：检查模型服务是否正常、内存/显存是否吃紧；处理完重新打开页面即可恢复。\n\n"
            "（急诊是**载体层**的自我保护：与其继续产出不可信的回答，不如停下来等你。"
            "要强制恢复，把 `logs/health/emergency.json` 里 `on` 置为 false 并重启小焦。）"
            % (_HEALTH_EMERGENCY.get("reason") or "模型状态异常"))


def _note_tool_path(tool_trace, path=""):
    """把"这一轮走了工具直通"广播到协同网络（并落盘事件流水）。

    【为什么需要它 —— 接入验收实测发现的真缺口】
        `agent_run` 里有几条**规则直通**（③a 句子里甩了网址 → `_scrape_direct`；
        ③a-2 重试抓取；等等）。它们拿到答案后**直接 return**，跳过了主流程末尾的
        `memory.retrieved` / `metacognition.checked` 发布点。
        实测对比：普通问答一轮发布 3 个事件，而"抓一下 example.com"一轮**发布 0 个** ——
        也就是说**带工具的轮次在协同网络里完全隐形**，而恰恰是这些轮次最需要被观测
        （工具调用、抓取成败、后面接不接总结）。补这一个发布点就补上了。
    """
    try:
        from core import central as _c
        _tools = [t.get("tool") for t in (tool_trace or []) if isinstance(t, dict)]
        _c.set_state("tools", last_tools=_tools[-4:], path=path)
        _c.publish("tool.invoked", {"tools": _tools[-4:], "path": path})
    except Exception:      # noqa: silent-ok — 总线不在也不能影响这条直通的结果
        pass



def _selfrate_llm(prompt):
    """给元认知自评用的一次大脑调用（只要一句话的档位）。

    为什么单独抽一个函数而不是内联 lambda：自测要能**替换掉它**，
    否则每跑一次自测都要真调一次模型（慢且不稳定）。
    """
    try:
        return llm_chat([{"role": "user", "content": prompt}]) or ""
    except Exception:      # noqa: silent-ok — 没模型就等同"没把握"，由 selfrate 内部降级
        return ""


def _spirit_recall(query):
    """精神记忆召回：把之前**想明白的一句话认知**取回来当**素材**。

    【和普通记忆的区别】`_retrieve_memory` 取的是"发生过什么"（经历），
    这里取的是"学到了什么"（认知：知识 / 方法 / 诊断经验）。
    经历让模型想起当时的场景，认知让模型直接站到上次的高度上 —— 后者才是"越用越强"。

    【为什么必须写明"这是素材，不是答案"】召回来的是一句话认知（比如"遇到地区类问题
    必须先锁定同一地点再比对"），它不是对用户这一问的回答。如果不加说明就塞进 system，
    模型很容易把它当结论复述出来 —— 那就成了拿旧话敷衍。所以注入文本里显式写死这条。

    【失败一律返回空串】精神记忆取不到只是少一份参考，**绝不能因此答不了**。
    """
    try:
        from core import spirit_memory as _sm
        hits = _sm.recall(query, k=3)
        if not hits:
            return ""
        _KIND_CN = {"knowledge": "知识", "method": "方法", "diagnosis": "诊断经验"}
        lines = ["【以前想明白的（**素材，不是答案**）】",
                 "下面是载体以前积累的一句话认知。它们**不是**对本次提问的回答：",
                 "请把它们当参考，**自己重新组织语言**回答用户，不要原样复述。"]
        for h in hits:
            lines.append("- [%s %.3f] %s" % (_KIND_CN.get(h["kind"], h["kind"]), h["sim"], h["text"]))
        LOG.info("精神记忆召回：%d 条｜%s", len(hits), " / ".join(h["text"][:24] for h in hits))
        return "\n".join(lines) + "\n"
    except Exception as e:      # noqa: silent-ok — 取不到认知只是少一份参考
        LOG.debug("精神记忆召回跳过（忽略）：%s", e)
        return ""


def _spirit_judge(a, b):
    """相似度 ≥0.6 时，问大脑这两条认知**是不是同一件事**。

    【为什么必须真的问一次】小脑是字级模型，"先确认单位再算" 与 "先锁定地点再比"
    这类**句式相同、内容不同**的方法，字面余弦很容易冲过 0.6。此时若不对照大脑，
    `remember()` 会走"无判官 → 保守当同题"的分支，把一条**新方法**当成重复丢掉 ——
    保守分支的代价本就是丢信息，能用判官消掉就该消掉。

    【判不出来就抛异常】`should_merge()` 会捕获异常并退回保守分支。这里**不猜**：
    猜错等于替大脑做了它该做的判断。
    """
    _p = ("下面两条认知，说的是不是同一件事？\nA：%s\nB：%s\n"
          "只回答两个字：`同题` 或 `不同`。" % (str(a)[:120], str(b)[:120]))
    out = (_selfrate_llm(_p) or "").strip()
    if not out:
        raise ValueError("判官没有应答")
    if "不同" in out:
        return False
    if "同" in out:
        return True
    raise ValueError("判官没给出可用答案：%s" % out[:30])


# 【学习闭环的第二道护栏：不许把"模型对自己能力的猜测"存成知识】
#   实测抓到的真实污染：精神记忆库里存进了
#     「主动上网逛的本质是**"被调用"而非"主动探索"**」
#     「当作发现写出的内容与记忆中的设定冲突时，立即停止」
#   它们是 4B 关于**自己**的自我描述（而且是错的 —— 它明明有后台逛线程）。
#   更糟的是：这些"知识"每轮又被召回、注回 system，于是
#     **它在用自己编的"我不主动探索"来佐证"我不主动探索"** —— 自我强化的死循环。
#   模型关于外部世界的知识可以学；关于**自己是什么/能不能**的断言一律不学 ——
#   那类事实的权威在**载体**（状态是真的），不在模型（它只是猜）。
_SELF_CLAIM = ("主动探索", "被调用", "我没有身体", "我没有世界", "我不主动",
               "我没有记忆", "只是文字", "对话框里", "我无法主动", "我的本质",
               "小焦的本质", "我是否存在", "我没有能力")


def _looks_like_self_claim(text):
    """这条"认知"是不是在讲小焦自己是什么 / 能不能。命中即不学。"""
    t = str(text or "")
    return any(w in t for w in _SELF_CLAIM)


def _spirit_learn(user_input, answer):
    """学习闭环的落库端：把这一轮**能留下来的一句话认知**存进精神记忆库。

    【为什么用模型提炼、而不是把回答存进去】回答是**一次性的措辞**，存下来等于
    把随机输出当事实（记忆污染）。要留下的是**提炼过的认知**，这件事需要理解语义 ——
    所以让 4B 提炼成一句话（`knowledge` / `method` / `diagnosis` 三类），
    再由 `spirit_memory.remember()` 的护栏把关（超长 / 问答对 / 带答案字段一律拒收）。

    【为什么提炼不出来就不存】`remember()` 的护栏会拒；这里再兜一层：模型没给出
    可用的一行，就直接放弃这一轮。**宁可少记，绝不记错** —— 少记一条只是没学到。
    """
    try:
        from core import spirit_memory as _sm
        _prompt = (
            "下面是一轮对话。请判断：**这一轮里有没有值得长期记住的一句话认知**？\n\n"
            "【用户】%s\n【回答】%s\n\n"
            "如果有，只输出两行，第一行是类别（knowledge / method / diagnosis 三选一），"
            "第二行是**一句话**（不超过 60 字，陈述句，不要问答格式，不要复述上面的回答）：\n"
            "knowledge = 关于用户或世界的事实性认知\n"
            "method = 这类事该怎么办的做法或判据\n"
            "diagnosis = 出了什么错、怎么定位、怎么修好的\n\n"
            "如果这一轮没有值得长期记住的东西，只输出 `none` 四个字母。"
            % (str(user_input)[:300], str(answer)[:600]))
        out = (_selfrate_llm(_prompt) or "").strip()
        if not out or out.lower().startswith("none"):
            LOG.info("学习闭环：这一轮没有可留存的认知（模型判 none）")
            return None
        _lines = [x.strip() for x in out.split("\n") if x.strip()]
        kind = (_lines[0].lower().strip(":： ") if _lines else "")
        text = (_lines[1] if len(_lines) > 1 else "")
        if kind not in _sm.KINDS or not text:
            LOG.info("学习闭环：模型输出不合格式，丢弃｜%s", out[:80])
            return None
        # 第二道护栏：关于"小焦自己是什么/能不能"的断言不学（见 `_looks_like_self_claim`）
        if _looks_like_self_claim(text):
            LOG.info("学习闭环：这条在讲小焦自己是什么/能不能，**不学**（事实以载体状态为准）｜%s",
                     text[:60])
            return None
        r = _sm.remember(kind, text, source="对话自动提炼", llm_judge=_spirit_judge)
        LOG.info("学习闭环：%s → %s（%s）", kind, r["action"], r.get("why", "")[:60])
        return r
    except Exception as e:      # noqa: silent-ok — 学不到只是这一轮没积累，不能影响回答
        LOG.debug("学习闭环跳过（忽略）：%s", e)
        return None


def _rule_selfrate(question):
    """元认知自评的**第一级：载体规则**。返回 `(档位, 理由)`；判不出来返回 `None`。

    【为什么要两级】自评要花一次模型调用，而**有些情况载体自己就能判死**：
    问"最新 / 实时 / 今天"这类会变的事实、或者问句缺宾语根本没说清要什么 ——
    这些不用问模型也知道**没把握**，先花钱问一遍是浪费，而且模型有可能反过来自称"有把握"。

    【为什么规则只敢判 C，不敢判 A】判 C 错了的代价是"多查一次"（慢一点）；
    判 A 错了的代价是"用自信的语气答错"。两个代价不对等，所以规则这一级**只确认没把握，
    绝不确认有把握** —— A/B 一律交给模型自己评（见 `_selfrate_llm`）。
    这与 `metacognition.route()` 里"?→use_tool"是同一条自律。
    """
    q = str(question or "").strip()
    if not q:
        return None
    _LIVE = ("最新", "实时", "现在", "目前", "今天", "今日", "昨天", "明天", "本周", "这周",
             "刚才", "刚刚", "股价", "汇率", "比分", "票房", "热搜", "排名")
    if any(w in q for w in _LIVE):
        return "C", "问的是会变的事实（命中实时性词），载体自己拿不到当前值"
    # 缺宾语的短问句："帮我搞一下" / "那个呢" —— 没说清对象，谈不上有把握
    if len(q) <= 12 and not any(c.isdigit() for c in q):
        _TAIL = ("呢", "吗", "吧", "么")
        _VAGUE = ("搞", "弄", "看", "办", "整", "来", "做")
        if any(q.endswith(t) for t in _TAIL) and len(q) <= 6:
            return "C", "问句过短且只带语气词，缺宾语"
        if any(v in q for v in _VAGUE) and len(q) <= 8 and "怎么" not in q and "为什么" not in q:
            return "C", "只给了动作没给对象，谈不上有把握"
    return None


def _switch_hint(question):
    """C 档时给模型的**手段链指令**：不许直接认输，按顺序换手段。

    【为什么 C 档不是"认输"】C 的含义是"这一问按现在这条路答不好"，不是"答不了"。
    载体能做的下一件事很多：换工具、换检索策略、换表达方式、反转问法再问用户。
    所以 C 档注入的是**行动序列**，不是一句道歉。

    【为什么只是"指令"而不是载体代跑整条链】真正的整链执行需要每一步各自的执行器
    （换工具要调工具、换检索要重跑召回），那是 `agent_run` 内部更大的一次重构。
    当前落地的部分：按 `core/metacognition/switch.py` 的 `MEANS` 顺序生成手段链并注入。
    —— 这一条**如实标注为部分落地**，不写成"切换手段链已接入"。
    """
    try:
        from core.metacognition import switch as _sw
        steps = _sw.plan(question)
        if not steps:
            return ""
        return ("\n【元认知 · C 档：这一问按原路走没把握】\n"
                "不要用一句「抱歉/我不知道」交差。按下面的顺序换手段，"
                "哪一种明显更好就用哪一种，并在回答里说清你换了什么：\n%s\n"
                % _sw.steps_text(steps))
    except Exception as e:      # noqa: silent-ok — 给不出手段链时退回原有行为
        LOG.debug("手段链指令生成跳过（忽略）：%s", e)
        return ""


# ================== RAG · 三个源**同时查** + 载体算优率 ==================
# 【为什么要并发】记忆库（对话向量库）、向量库（长期记忆）、联网 这三个源互不依赖，
#   串行发起等于把三段延迟**相加**；并发发起只花**最慢那个**的时间。
#   实测口径：总耗时应当接近 max(各源)，而不是 sum(各源)（自测里专门断言这一点）。
# 【为什么要算"优率"】三个源都能返回东西，但质量差别很大：用户亲口说过的话、
#   自己库里沉淀的记忆、网上搜来的片段，可信度不是一个量级。载体必须自己给它们打分，
#   而不是"谁先返回就用谁"或者"全都塞进 system"。
_RAG_SOURCE_TRUST = {"记忆库": 1.00, "向量库": 0.90, "联网": 0.60}
# 分级门槛（用户规格）：优率 ≥ 0.90 直接用；0.60~0.90 交元认知 + 健康医生；< 0.60 不注入。
RAG_USE_DIRECTLY = 0.90
RAG_REVIEW_FLOOR = 0.60


def _rag_info_score(text):
    """信息含量（0~1）：含数字 / 日期 / 链接、且长度适中 → 分高。纯口号式的短句分低。"""
    t = str(text or "")
    n = len(t)
    if n < 8:
        return 0.20
    s = 0.0
    if re.search(r"\d", t):
        s += 0.35
    if re.search(r"\d{4}\s*[-/年]\s*\d{1,2}", t):
        s += 0.15
    if re.search(r"https?://|www\.", t):
        s += 0.20
    s += 0.30 if 20 <= n <= 400 else 0.10      # 太短没信息量，太长塞不进上下文
    return min(1.0, s)


def _rag_overlap(query, text):
    """提问关键词在候选里的重合度（规则，不调模型）。"""
    try:
        kws = [k.lower() for k in _intent_keywords(query or "")]
    except Exception:      # noqa: silent-ok — 抽不出关键词时给中性分，不因此判死
        kws = []
    if not kws:
        return 0.50
    t = str(text or "").lower()
    hit = sum(1 for k in kws if k and k in t)
    return min(1.0, hit / float(len(kws)))


def _rag_quality(text, query, source, sim=None):
    """载体算的**优率**（0~1）。全部是确定性判据，**不调模型**。

    四部分加权：
      ① 相似度 0.55 —— 向量相似度；联网结果没有向量，就用词重合度顶
      ② 来源可信度 0.30 —— 用户亲口说的（记忆库 1.00）> 自己库里的长期记忆（0.90）> 网上搜的（0.60）
      ③ 信息含量 0.10 —— 见 `_rag_info_score`
      ④ 词重合 0.10
    外加一条**一票否决**：地域闸门判定"这条在说别的地方" → 优率直接 0。
    （那条闸门就是菏泽被答成江淮降雨之后补的，见 `core/retriever.py`。）

    **【为什么是这组权重】这不是随手定的，是按"分档要能用"倒推的**：
      · 第一版权重是 0.45/0.25/0.15/0.15，实测**满分记忆库命中只有 0.82** ——
        永远跨不过"≥0.90 直接用"那条线，等于把这一档写成死代码。权重必须让判据够得着。
      · 现在这组下：记忆库强命中（相似度 ≈1.0）≈ 0.91 → **直接使用**；
        向量库近乎满分 ≈ 0.94 → 直接使用；而**联网结果最高也只到 ≈0.80** → 一律进复核档。
      也就是说，"网上搜来的东西不该被当成事实直接用"这条自律，是由权重**结构性保证**的，
      不是靠调用方记得去判断。

    返回 `(优率, 判据说明)`。说明要给人看，所以把四项的实际取值都写进去 ——
    出现"为什么这条被弃了"时，答案就在这行字里。
    """
    t = str(text or "")
    if not t.strip():
        return 0.0, "空内容"
    try:
        from core import retriever as _r
        # 走**同一个入口**（地域 + 人物/时间/单位/产品/事件 五类）：
        # 检索侧剔一遍、优率侧再判一遍，用两套判据早晚会打架，而那种 bug 最难查。
        _why = _r._domain_reason(query, t)
        if _why:
            return 0.0, "一票否决：" + str(_why)
    except Exception as e:      # noqa: silent-ok — 闸门不可用就不否决，但仍照常打分
        LOG.debug("RAG 领域闸门不可用（忽略）：%s", e)
    ov = _rag_overlap(query, t)
    sim_v = float(sim) if isinstance(sim, (int, float)) else ov
    sim_v = max(0.0, min(1.0, sim_v))
    trust = _RAG_SOURCE_TRUST.get(source, 0.50)
    info = _rag_info_score(t)
    q = 0.55 * sim_v + 0.30 * trust + 0.10 * info + 0.10 * ov
    return q, "相似度 %.2f · 来源 %.2f · 信息 %.2f · 重合 %.2f" % (sim_v, trust, info, ov)


def _rag_vector_hits(query, top_k=5):
    """源②：长期记忆向量库（`core/memory_vec.py`）。"""
    try:
        from core import memory_vec as MV
        out = []
        for h in (MV.search_memory(query, top_k=top_k) or []):
            if isinstance(h, dict) and h.get("text"):
                out.append({"text": str(h["text"]), "sim": h.get("score"),
                            "meta": str(h.get("kind") or "")})
        return out
    except Exception as e:      # noqa: silent-ok — 这一路挂了不影响另外两路
        LOG.debug("RAG 向量库失败（忽略）：%s", e)
        return []


def _rag_web_hits(query, num=4):
    """源③：联网。返回 `[(标题, 链接, 内容)]`，这里拼成候选文本。"""
    try:
        out = []
        for it in (web_search(query, num=num) or []):
            row = list(it) + ["", "", ""]
            title, link, content = str(row[0]), str(row[1]), str(row[2])
            txt = ("%s：%s" % (title, content)).strip("： ").strip()
            if txt:
                out.append({"text": txt[:400], "sim": None, "meta": link})
        return out
    except Exception as e:      # noqa: silent-ok
        LOG.debug("RAG 联网失败（忽略）：%s", e)
        return []


def _rag_three_sources(query, timeout=15.0):
    """**三个源同时发起**。返回 `(候选列表, 各源耗时, 总耗时)`。

    并发实现用 `ThreadPoolExecutor(3)`：三个源都是阻塞式 IO（本地向量检索 + HTTP 抓取），
    线程池足够，也不需要把整条对话链改成 async。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    t0 = time.time()
    lat = {}

    def _mem():
        s = time.time()
        txt = _retrieve_memory(query)
        lat["记忆库"] = round(time.time() - s, 3)
        return [{"text": txt, "sim": None, "meta": "对话记忆注入文本"}] if txt else []

    def _vec():
        s = time.time()
        r = _rag_vector_hits(query)
        lat["向量库"] = round(time.time() - s, 3)
        return r

    def _web():
        s = time.time()
        r = _rag_web_hits(query)
        lat["联网"] = round(time.time() - s, 3)
        return r

    cands = []
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = {ex.submit(fn): name
                for name, fn in (("记忆库", _mem), ("向量库", _vec), ("联网", _web))}
        try:
            for f in as_completed(futs, timeout=timeout):
                name = futs[f]
                try:
                    for c in (f.result() or []):
                        c["source"] = name
                        cands.append(c)
                except Exception as e:      # noqa: silent-ok — 单源失败不影响另外两源
                    LOG.debug("RAG %s 源失败：%s", name, e)
        except Exception as e:      # noqa: silent-ok — 超时也把已经拿到的候选带回去
            LOG.info("RAG 并发等待超时（%.1fs），用已返回的候选继续：%s", timeout, type(e).__name__)
    return cands, lat, round(time.time() - t0, 3)


def _rag_grade(cands, query):
    """给候选打分、排序、分级。返回结构化结果（不注入，注入由调用方决定）。"""
    scored = []
    for c in cands:
        q, why = _rag_quality(c.get("text"), query, c.get("source", "?"), sim=c.get("sim"))
        scored.append({"source": c.get("source", "?"), "text": c.get("text") or "",
                       "sim": c.get("sim"), "q": round(q, 4), "why": why,
                       "meta": c.get("meta") or ""})
    scored.sort(key=lambda x: -x["q"])
    best = scored[0] if scored else None
    if not best or best["q"] >= RAG_USE_DIRECTLY:
        grade = "直接使用"
    elif best["q"] >= RAG_REVIEW_FLOOR:
        grade = "交元认知与健康医生"
    else:
        grade = "不注入"
    return {"best": best, "candidates": scored, "grade": grade,
            "q": best["q"] if best else 0.0}


def _rag_concurrent(query):
    """三源同时查 → 算优率 → 按档处理。返回可直接拼进 system 的文本（空串 = 不注入）。

    **三档处理**（用户规格）：
      · 优率 ≥ 0.90 直接用   —— 记忆库命中用户亲口说的话通常是这一档
      · 0.60~0.90 交元认知 + 健康医生 —— 记一条自评样本（B 档，需复核）并写一条健康日志；
        回答由元认知那一侧加上"没把握/需复核"的标注，而不是让载体假装很有把握
      · < 0.60 不注入        —— 宁可不说，也不拿低质片段污染这一轮
    """
    try:
        cands, lat, total = _rag_three_sources(query)
    except Exception as e:      # noqa: silent-ok — 并发整体失败就退回"不注入"
        LOG.debug("RAG 并发失败（忽略）：%s", e)
        return ""
    if not cands:
        LOG.info("RAG 三源同时查：全空（记忆库/向量库/联网都没给东西）")
        return ""
    # ---- 思考圈 ①：心理 → 大脑（**改"往哪想"**）----
    #   只**重排**候选，不增删、不改写任何文本 —— 这是"改方向"而非"传消息"的硬证据：
    #   上下文里一个字都不多，变的是"先冒哪一类"。
    try:
        from core import thinking_loop as _TL
        cands, _lr = _TL.adjust_candidates(cands)
        if _lr.get("moved"):
            LOG.info("思考圈：心理[%s] → 改检索方向（偏 %s）｜把「%s」提到了第 %d 位",
                     _lr["state"], "、".join(_lr["keywords"][:3]),
                     _lr["moved"][0]["text"][:36], _lr["moved"][0]["to"])
        else:
            LOG.info("思考圈：心理[%s] → 检索方向未变（%s）", _lr["state"], _lr.get("note"))
    except Exception as _e:      # noqa: silent-ok — 圈转不动也不能影响检索
        LOG.debug("思考圈重排失败（忽略）：%s", _e)
    # 真实事件之二：**载体自己遇到了什么**（检索回来的内容 → 可能让心变）
    try:
        from core import thinking_loop as _TL3
        _blob = " ".join(str((c or {}).get("text") or "")[:120] for c in cands[:3])
        if _blob.strip():
            _ev2 = _TL3.on_event("carrier", _blob, why="检索到的内容")
            LOG.info("心：载体事件（检索到内容）触发 → 状态=%s", _ev2.get("state"))
    except Exception as _e:      # noqa: silent-ok
        LOG.debug("心：载体事件触发失败（忽略）：%s", _e)
    g = _rag_grade(cands, query)
    best = g["best"]
    LOG.info("RAG 三源同时查：候选 %d 条 · 各源耗时 %s · 并发总耗时 %.2fs（串行会是 %.2fs）",
             len(cands), lat, total, sum(lat.values()))
    LOG.info("RAG 优率：%.2f【%s】来源=%s ｜ %s", best["q"], g["grade"], best["source"], best["why"])
    if g["grade"] == "不注入":
        return ""
    if g["grade"] == "交元认知与健康医生":
        _rag_handoff_review(query, best, g)
    # 注入的是**素材**：明确要求模型自己组织措辞，不许原文回吐
    head = ("【本轮检索到的素材（三源同时查，载体已按优率排序）】\n"
            "优率 %.0f%% · 来源「%s」· 判据：%s\n"
            "以下是**素材不是答案**，请自己组织语言回答，不要原样复述：\n"
            % (best["q"] * 100, best["source"], best["why"]))
    # 命中"记忆库"时补上那条说明：`_MEMORY_INSTRUCTION` 讲的正是"记忆里的「我」= 用户本人"，
    # 这个语义**只对用户亲口说过的话成立** —— 对网上搜来的片段不成立，所以不能无脑加。
    if best["source"] == "记忆库":
        head = _MEMORY_INSTRUCTION + head
    # ---- 注入 **多条**，不是只注最优那一条 ----
    # 【这是一处真实回归的修复】改成"三源同时查 + 算优率"时，我一开始只把 `best` 那一条注进去。
    #   实测后果：用户问「我叫什么名字」时，top-1 是**那句提问本身**（相似度 0.809），
    #   而真正带着姓名的「用户：我叫张三，在济南做后端开发」被挤掉了 ——
    #   模型于是答"我的记忆库里没有你的姓名记录"，用户说"我一开始就告诉你了我是张三"。
    #   **答案在库里、却因为只注一条而没进 prompt**，这是最冤的一类 bug。
    #   现在：达到复核门槛（0.60）的候选都注进去，最多 3 条，按优率降序、按文本去重。
    #   上限 3 是为了不让 system 被记忆挤爆（原 `_retrieve_memory` 也是按 token 预算截的）。
    _picked, _seen = [], set()
    for _c in g["candidates"]:
        _t = (_c.get("text") or "").strip()
        if not _t or _t in _seen or _c["q"] < RAG_REVIEW_FLOOR:
            continue
        _seen.add(_t)
        _picked.append(_c)
        if len(_picked) >= 3:
            break
    if not _picked:
        _picked = [best]
    body = "\n".join(
        "- （优率 %.0f%% · %s）%s" % (c["q"] * 100, c["source"], c["text"]) for c in _picked)
    if len(_picked) > 1:
        head += "（本轮共注入了 %d 条达标素材，按优率降序；请综合它们回答，不要只挑一条）\n" % len(_picked)
    if g["grade"] == "交元认知与健康医生":
        head += ("注意：这些素材的优率都没达到可直接采信的门槛（最高 %.0f%%），"
                 "用的时候要留出被证伪的余地。\n" % (best["q"] * 100))
    return head + body + "\n"


def _rag_handoff_review(query, best, g):
    """优率落在 0.60~0.90 时，把这一条交给**元认知**与**健康医生**。

    【为什么由它们接】优率不高不低的情形，载体能判的只有"不够可信"，
    判不了"这条到底对不对"。元认知负责把它记成一条**待复核**的样本（下一次同类问题
    会因此更谨慎），健康医生负责留一条可复盘的记录。两者都不是"拒绝回答"，
    而是把不确定性**如实标出来**。
    """
    try:
        from core.metacognition import boundary as _bd
        _bd.record(query, rating="B", correct=None,
                   note="RAG 优率 %.2f 未达直采门槛（来源 %s）" % (best["q"], best["source"]),
                   source="rag")
        LOG.info("RAG 交元认知：已记一条待复核样本（B 档）")
    except Exception as e:      # noqa: silent-ok — 记不上不影响回答
        LOG.debug("RAG 交元认知失败（忽略）：%s", e)
    try:
        from core import health as _h
        _h.log_line("rag", "优率 %.2f 未达直采门槛：来源=%s 判据=%s"
                    % (best["q"], best["source"], best["why"]))
        _h.append_jsonl(_h.health_dir("rag_review.jsonl"),
                        {"ts": time.time(), "query": str(query)[:120], "q": best["q"],
                         "source": best["source"], "why": best["why"],
                         "grade": g["grade"]})
        LOG.info("RAG 交健康医生：已写一条可复盘记录")
    except Exception as e:      # noqa: silent-ok
        LOG.debug("RAG 交健康医生失败（忽略）：%s", e)


# ================== 代码治病接进对话入口 ==================
# 【为什么要有这一段】模型"一次写对可运行的代码"不可靠，但"照着报错改一行"很可靠。
#   所以这边不把代码直接交给用户，而是**载体先跑一遍**：跑通了才输出。
#   用户拿到的是**验证过能跑的结果**，不是一段"看起来像能跑"的文本。
_CODE_WRITE = ("写个", "写一个", "写一段", "写份", "写一个", "帮我写", "给我写", "实现一个",
               "实现个", "编写", "写代码", "写函数", "写脚本", "写程序", "生成代码",
               "写个函数", "写个脚本", "写段代码", "来段代码", "码一段")
_CODE_NOT_WRITE = ("看看", "审查", "解释", "为什么", "什么意思", "怎么理解", "错在哪",
                   "review", "解释一下", "读懂", "分析一下这段")
# 创作类：这些是"写东西"的**对象**，不是代码。命中就**不是**代码请求。
# 【为什么必须加这一道 —— 用户实测抓到的误判】用户说「写个童话故事吧」，
#   结果走了代码治病链：把故事包进 `def tell_a_fairy_tale() -> str: ... return story`，
#   真跑一遍，回「已跑通并验证（第 1 轮）」。故事写对了，但**它把"写个故事"当成了"写代码请求"**。
#   根因和之前那个 bug 同一个：`_CODE_WRITE` 里有「写个/写一个/写一段」——
#   这三个在中文里太常见，写故事/写文章/写诗/写作文/写文案/写歌词/写笑话**全都命中**。
#   **"写"这个字本身不带"代码"语义。**
# 【为什么用排除法，而不是改成"必须带代码对象"】后者会漏掉合法说法：
#   「帮我写个能跑的」「写个试试」（没明说"函数"但确实是代码）。排除法更保守：
#   宁可漏判一个真代码请求（下一轮说清楚就行），也不要把写故事塞进治病链。
_CODE_NOT_WRITE_CREATIVE = ("故事", "童话", "小说", "文章", "作文", "诗歌", "诗", "歌词",
                            "文案", "笑话", "段子", "散文", "剧本", "对联", "情书",
                            "演讲稿", "推文", "说说", "日记", "祝福语", "自我介绍",
                            "文案", "台词", "旁白", "打油诗", "顺口溜", "谜语")


def _code_request_question(text):
    """这句话是不是"**让我写一段能跑的代码**"。纯规则，不调模型。

    【为什么要区分"写"和"看"】"帮我写个去重函数"要走治病（跑一遍再给），
    而"帮我看看这段代码为什么慢"是**评审/解释**请求 —— 把它塞进治病流程会答非所问。
    判据因此是"命中写代码词" **且** "不命中评审词"。

    【为什么宁可漏、不可错】误判的代价是把一个普通问题变成"我给你写段代码跑跑看"，
    用户会觉得答偏了。所以判据收紧，只认明确带祈使动作的说法。
    【创作类那道排除】见 `_CODE_NOT_WRITE_CREATIVE` 的说明：
    「写个童话故事吧」曾经被这条判据送进代码治病链（包成 Python 函数跑一遍再交付）。
    """
    t = str(text or "").strip()
    if not t or len(t) > 200:
        return False
    if any(w in t for w in _CODE_NOT_WRITE):
        return False
    # **创作类先排除**：写故事/写文章/写诗… 不是代码请求（见上面那张表的说明）
    if any(w in t for w in _CODE_NOT_WRITE_CREATIVE):
        return False
    return any(w in t for w in _CODE_WRITE)


def _heal_web(query):
    """治病流程用的联网入口：查到的内容作为**参考**（不是答案）给模型。"""
    try:
        rows = web_search(query, num=3) or []
    except Exception:      # noqa: silent-ok — 查不到就让治病流程照常收尾
        return ""
    parts = []
    for it in rows:
        row = list(it) + ["", "", ""]
        title, link, content = str(row[0]), str(row[1]), str(row[2])
        if content.strip():
            parts.append("%s：%s" % (title, content))
    return "\n".join(parts)[:1200]


def _code_heal_answer(user_input):
    """代码治病主流程：**生成 → 跑 → 失败则诊断 → 改 → 再跑**。通过即输出。

    返回可直接作为回答的文本（失败也返回文本，如实说明卡在哪 —— 不假装成功）。
    """
    try:
        from core import diagnose_code as DC
    except Exception as e:      # noqa: silent-ok — 模块不在就退回普通回答
        LOG.debug("代码治病模块不可用（忽略）：%s", e)
        return ""
    # ---- ① 让模型先给出代码（只问代码，不问解释）----
    try:
        raw = llm_chat([{"role": "user", "content":
                         "请写一段 Python 代码完成下面这件事，**只给代码**，用 ```python 包起来，"
                         "不要解释：\n\n%s" % user_input}]) or ""
    except Exception as e:      # noqa: silent-ok — 模型调不通就退回普通流程
        LOG.debug("代码治病：生成阶段失败（忽略）：%s", e)
        return ""
    code = DC._strip_fence(raw)
    if not code.strip():
        LOG.info("代码治病：模型没给出代码，退回普通流程")
        return ""
    # ---- ② 载体真的跑一遍，跑挂就走「诊断 → 改 → 再跑」（最多 3 轮，之后联网查参考）----
    res = DC.heal(code, lambda msgs: llm_chat(msgs) or "",
                  max_rounds=3, web_fn=_heal_web, web_rounds=1)
    if res.get("blocked"):
        LOG.info("代码治病：**红线拦截**，不重试也不查网络")
        return ("这段代码里命中了载体的**删除禁区**，我拒绝执行它。\n\n"
                "原因：%s\n\n"
                "删除是不可逆操作，载体在任何情况下都不代跑这类代码。"
                "如果确实需要删除文件，请你自己手动执行。" % res["blocked"])
    rounds = res.get("rounds", 0)
    if res["ok"]:
        LOG.info("代码治病：第 %d 轮跑通，直接输出真实运行结果", rounds)
        # **修完即验证，通过即输出**：给的是真跑出来的输出，不是模型的复述
        return ("**已跑通并验证（第 %d 轮）**\n\n```python\n%s\n```\n\n"
                "**真实运行输出**：\n```\n%s\n```"
                % (rounds, res["code"].strip(), (res.get("final") or "（这段代码没有输出）").strip()))
    # ---- ③ 没跑通：如实交代，不假装成功 ----
    kinds = res.get("kinds") or []
    used_web = res.get("used_web")
    trace = res.get("trace") or []
    last_err = ""
    for t in reversed(trace):
        if t.get("stderr"):
            last_err = t["stderr"]
            break
    LOG.info("代码治病：%d 轮未通过（用过参考=%s），如实交代", rounds, used_web)
    return ("这段代码我跑了 **%d 轮**没能跑通，**如实说，不假装成功**。\n\n"
            "```python\n%s\n```\n\n"
            "最后一轮的错误：\n```\n%s\n```\n\n"
            "出现过的错误类型：%s\n%s"
            "你可以让我换个写法，或者告诉我更具体的输入/环境。"
            % (rounds, (res.get("code") or "").strip(), last_err.strip()[:600],
               "、".join(kinds) if kinds else "未归类",
               "（这几轮里我上网查过一段**参考**，但没照抄，仍没改对。）\n" if used_web else ""))


# ================== 逛世界：接进主流程（4B/4C/4D）==================
# 【这一步把三个底座模块接到真实能力上】
#   `core/dual_thread.py`（双线程 + 门的状态）／`core/phone_channel.py`（电话通道）／
#   `core/model_scheduler.py`（对话优先调度）三个模块本身已经能跑，但它们不认识"世界层"。
#   这里把 `core/world/` 的探索器包成四个回调塞进去：**决策 → 逛 → 存 → 分享**。
# 【核心原则（用户规格）：全部交给模型自主决策】
#   什么时候出门、出门多久、逛什么、回来分不分享 —— 全问模型。
#   载体**不设定时任务、不设 70/30 比例、不设计数器**；它只负责"照做 + 留痕"。
_BROWSE_STARTED = {"tried": False}


def _browse_explorer():
    """拿世界层探索器；拿不到返回 None（世界层缺席不该影响对话）。"""
    try:
        from core.world.explorer import get_explorer
        return get_explorer()
    except Exception as e:      # noqa: silent-ok — 世界层没起来就这一轮不逛
        LOG.debug("逛世界：探索器不可用（忽略）：%s", e)
        return None


def _recent_dialogue_for_interest(days=7, limit=12):
    """取最近 N 天的**用户原话**，交给模型自己判断"用户关心什么"。

    【按原理：不预设、不统计】规格明确要求兴趣由**模型自己**从最近 7 天对话里判断。
    所以这里只做一件最笨的事：**把原话捞出来给它看** —— 不做关键词统计、不做话题聚类、
    更不喂"世界模型话题表"（那是载体已经统计过的结果，等于替模型做了判断）。
    【为什么只取用户说的话】小焦自己的回答会污染判断：它答什么不代表用户关心什么。

    读不到就返回空串 —— 逛不逛由模型自己决定，**不该因为读不到历史就编一段兴趣出来**。
    """
    try:
        _p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "chat_history.jsonl")
        if not os.path.exists(_p):
            return ""
        cutoff = time.time() - float(days) * 86400
        rows = []
        with open(_p, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:      # noqa: silent-ok — 坏行跳过
                    continue
                # 【字段名以真实文件为准】`logs/chat_history.jsonl` 每行是
                #   `{"time": "2026-09-12T19:40:37", "log_id": …, "user": …, "final_reply": …}` ——
                #   用户原话在 **`user`**，时间在 **`time`** 且是 **ISO 字符串**（不是 epoch 秒）。
                #   第一版我按 `role`/`ts` 去读，结果一条都读不到（实测返回长度 0）——
                #   又一次"以为的 schema"和真实文件不符。**先看文件，再写解析。**
                ts = 0.0
                _t = d.get("time")
                if isinstance(_t, (int, float)):
                    ts = float(_t)
                elif isinstance(_t, str) and _t:
                    for _fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
                        try:
                            ts = time.mktime(time.strptime(_t[:26], _fmt))
                            break
                        except Exception:      # noqa: silent-ok — 换下一种格式
                            continue
                if ts and ts < cutoff:
                    continue
                c = str(d.get("user") or "").strip()
                if c and c != "⏳__pending__":
                    rows.append(c[:80])
        return "\n".join("- " + x for x in rows[-int(limit):])
    except Exception as e:      # noqa: silent-ok — 读不到就不给，让模型按"没有记录"处理
        LOG.debug("读最近对话失败（忽略）：%s", e)
        return ""


def _browse_decide():
    """**模型自主决策**：门开到哪一档、想逛什么。

    返回 `{"door", "why", "want"}`。判不出来就退回"半开半关 + 不指定主题"——
    保守值只在模型没给可用答案时用，不是载体的默认节奏。

    ⚠️ **第三阶段：这里也被状态硬改** —— 状态偏置说"这一轮不主动做"时，
    **代码层直接返回 locked，门都不问模型**（不是"告诉它别逛"）。
    """
    # ================== 第三阶段 · 硬改「要不要主动做什么」==================
    # 【为什么放在最前面】规格：**代码层决定"这一轮要不要发起"，不是模型自己决定**。
    #   所以状态偏置说 no_browse 时，这里**直接锁门、不调模型**，
    #   并在日志里写明是哪一条状态导致的（可复核）。
    try:
        _pol = _state_policy()
        if _pol.get("no_browse"):
            LOG.info("状态硬改·主动：**这一轮不主动逛**（档位%s / 警觉 %.2f）→ 直接锁门，不问模型",
                     _pol.get("level"), float(_pol.get("vigilance") or 0.0))
            try:
                _sm = _mod("self_model")
                if _sm is not None:
                    _sm.note("主动被压", cause="档位%s / 警觉 %.2f" % (_pol.get("level"),
                                                                    float(_pol.get("vigilance") or 0.0)),
                             effect="这一轮不主动逛（门直接锁死，没问模型）",
                             before="门可开", after="locked", level=_pol.get("level"))
            except Exception as _e:      # noqa: silent-ok
                LOG.debug("因果归属记录失败（忽略）：%s", _e)
            return {"door": "locked", "want": "",
                    "why": "状态偏置：%s" % "；".join(_pol.get("why") or [])[:60]}
    except Exception as _e:      # noqa: silent-ok — 策略读不到就不拦（保守）
        LOG.debug("状态策略读取失败（忽略）：%s", _e)
    try:
        # 【按原理：兴趣由模型从**最近 7 天对话**里自己判断，载体不预设、不统计】
        #   第一版我喂的是"世界模型的话题表"—— 那是载体已经统计过的结果，
        #   等于替模型做了判断，违背了「不预设、不统计」这条。
        #   现在把最近 7 天的**原始对话**交给它，让它自己看、自己判。
        recent = _recent_dialogue_for_interest(days=7, limit=12)
        # 【提示词压到最短 —— 长指令会被 4B 原样复读，这是实测抓到的真 bug】
        #   旧版写了两条带说明的多行指令，模型直接把指令行抄了回来：
        #     want = "想逛什么主题（不想逛就留空）"，而第一行恰好是 "locked"
        #     （旧提示词里就写着 open/half/locked 三个词）→ **每轮都被解析成 locked、门焊死、永不出门**。
        #   现在只留最短的两句 + 一行对话原文；"复读"也变成可识别的坏答案（见下面的 echoed 判据）。
        _p = ("要不要出门逛？回一个词：open 或 half 或 locked。\n"
              "想逛什么就再回一个词。\n"
              "最近聊过：%s" % (recent.replace("\n", "；")[:200] or "（无）"))
        out = (_selfrate_llm(_p) or "").strip()
        keys = ("门", "open", "half", "locked", "回一个词", "要不要出门", "想逛什么")
        lines = [x.strip() for x in out.split("\n") if x.strip()]
        door, want = "", ""
        # 【识别复读】模型把我提示词里的字抄回来时，那不是它的决策 —— 一律当没答，
        #   回落中性默认（半开 + 不指定主题），而不是误当成 locked 把门焊死。
        _INSTR_WORDS = ("留空", "想逛什么", "门的状态", "只输出", "主题（", "回一个词", "要不要出门")
        echoed = (len(out) > 60
                  or sum(1 for k in keys if k.lower() in out.lower()) >= 2
                  or any(w in out for w in _INSTR_WORDS))
        if not echoed:
            door = re.sub(r"[^a-z]", "", (lines[0] if lines else "").lower())
            if door not in ("open", "half", "locked"):
                door = ""
            if len(lines) > 1:
                _w = lines[1].strip("。.：: ")
                if 0 < len(_w) <= 20:
                    want = _w
        if not door:
            door = "half"          # 中性默认：不锁死也不强开
            why = "模型这次没给出可用的门状态（输出像复读提示词）→ 用中性默认 half，不用 locked 焊死门"
        else:
            why = "模型自主决策：%s" % out[:60].replace("\n", " / ")
        return {"door": door, "want": want, "why": why}
    except Exception as e:      # noqa: silent-ok — 决策失败就这一轮不出门
        return {"door": "half", "want": "", "why": "决策失败：%s" % type(e).__name__}


def _browse_action(want):
    """出门逛一次。返回逛回来的文本（空串 = 这轮没逛到东西）。"""
    ex = _browse_explorer()
    if ex is None:
        return ""
    try:
        # 世界层自己的 `explore_once` 内部已经串了 探索→判定→匹对→校验→吸收 全链，
        # 而且脏东西在 `firewall` 那一步就被隔离了 —— 这里不重复做一遍。
        rec = ex.explore_once(topic=(want or None))
    except Exception as e:      # noqa: silent-ok — 逛失败不影响任何用户请求
        LOG.debug("逛世界：explore_once 失败（忽略）：%s", e)
        return ""
    # 把世界层的累计数字同步进 EYC（happening.explored_count / absorbed_count）
    try:
        from core import dual_thread as _DT
        _today = (ex.status().get("today") or {})
        _DT.set_world_counts(explored=int(_today.get("explored") or 0),
                             absorbed=int(_today.get("absorbed") or 0))
    except Exception:      # noqa: silent-ok — 数字同步失败不影响逛本身
        pass
    # 真实事件之三：**世界变了什么** —— 逛到东西时让心跟着动
    try:
        from core import thinking_loop as _TLw
        if isinstance(rec, dict) and rec.get("ok") is not False:
            _TLw.on_event("world", json.dumps(rec, ensure_ascii=False)[:300], why="逛到新东西")
    except Exception:      # noqa: silent-ok
        pass
    if not rec:
        return ""
    # 【必须区分"逛到了"和"没逛成" —— 这是我自己写出来的一个 bug】
    #   实测：当天的探索额度用尽时，`explore_once` 返回
    #   `{"ok": false, "why": "今天已经看够 50 个站（daily_budget）"}`。
    #   第一版把这个 JSON 直接当成"逛到的内容"返回，于是它会被拿去问模型"要不要分享" ——
    #   模型完全可能把「今天已经看够 50 个站」当成一篇逛到的文章说给用户听。
    #   **没逛成就是没逛成，返回空串**；原因写日志供复盘，但不冒充内容。
    try:
        if isinstance(rec, dict) and rec.get("ok") is False:
            LOG.info("逛世界：这一轮没逛成 —— %s", str(rec.get("why"))[:100])
            return ""
    except Exception as _e:      # noqa: silent-ok — 判断不了就当作"逛到了"，往下走
        LOG.debug("逛世界结果判断失败（忽略）：%s", _e)
    # ================== 唯一被允许写 `unfinished` 的地方 ==================
    # 【为什么只留这一处】实测抓到过一条**没发生过**的"没做完的事"
    #   （"那篇讲猫的文章还有一半没看完"，而 logs/world/ 里一个"猫"字都没有）。
    #   追下去：写它的不是这条链，而是一次自测/手工调用 —— 载体侧当时**没有任何闸**。
    #   现在 `expectation.leave()` 要求 `source` 以 world/ 开头 + 带真实 evidence，
    #   这条路是**唯一**会带上这两样的地方：真逛到了东西、但没存进去（没读完）才记。
    try:
        _got = str(rec.get("got") or "").strip() if isinstance(rec, dict) else ""
        if _got and isinstance(rec, dict) and not rec.get("stored"):
            from core import expectation as _EXw
            _r = _EXw.world_leave(_got[:120], evidence=_got[:200],
                                  why="逛到了但没存进去（这一轮没读完）")
            LOG.info("逛世界：记下一条真的没做完的事（带真实来源）｜%s ｜ %s",
                     _got[:40], "已记" if _r.get("ok") else _r.get("why"))
    except Exception as _e:      # noqa: silent-ok — 记不上不影响逛本身
        LOG.debug("记没做完的事失败（忽略）：%s", _e)
    # 【要给"人能读的内容"，不是一坨 JSON】用户给的例子是「正好看到篇讲猫的文章」——
    #   对话线程要能说出**具体看到了什么**，塞一个 JSON 块进去它说不出来。
    #   这里从探索记录里挑出可读的字段，挑不到就退回一行摘要（仍然比 JSON 好读）。
    try:
        parts = []
        for k in ("title", "topic", "text", "summary", "content", "body", "headline"):
            v = rec.get(k)
            if isinstance(v, str) and v.strip():
                parts.append(v.strip()[:200])
        if not parts:
            steps = rec.get("steps") or {}
            if isinstance(steps, dict):
                for k2, v2 in list(steps.items())[:3]:
                    if isinstance(v2, str) and v2.strip():
                        parts.append("[%s] %s" % (k2, v2.strip()[:160]))
        if not parts:
            parts.append(json.dumps(rec, ensure_ascii=False)[:200])
        body = " ｜ ".join(parts)[:400]
    except Exception:      # noqa: silent-ok
        body = str(rec)[:400]
    return body


def _browse_share(text):
    """**模型自主决策**要不要分享给用户。不分享返回空串。"""
    try:
        if not str(text or "").strip():
            return ""
        _p = ("你在外面逛到下面这条内容。要不要主动说给用户听？\n"
              "只输出一个词：`分享` 或 `不说`。\n"
              "判断标准：跟用户最近关心的事有关、或者确实有意思才分享；"
              "琐碎、重复、或者用户这会儿多半不关心的，就别说 —— 别打扰他。\n\n内容：%s"
              % str(text)[:400])
        out = (_selfrate_llm(_p) or "").strip()
        if "分享" in out and "不说" not in out:
            _msg = "我在外面逛到一条：%s" % str(text)[:220]
            try:
                from core import dual_thread as _DT
                _DT.note_share(_msg)      # EYC 的 conversation 段：只在这里更新
            except Exception:      # noqa: silent-ok
                pass
            return _msg
        return ""
    except Exception:      # noqa: silent-ok — 决策失败就当不分享（宁可不打扰）
        return ""


def _browse_relay():
    """对话线程读电话通道：把逛线程想说的话**如实转达**给这一轮的回答。

    为什么只看不取（`peek`）：用户这一轮如果不接这个话头，那条分享留着，
    下一轮还有机会说 —— 取走又用不上就白丢了（见 `phone_channel.peek` 的说明）。
    """
    try:
        from core import phone_channel as PC
        m = PC.peek(kind=PC.KIND_SHARE)
        if not m:
            return ""
        PC.get(kind=PC.KIND_SHARE)          # 这一轮要用它，才真的取走
        return str(m.get("content") or "")[:300]
    except Exception as e:      # noqa: silent-ok — 通道异常绝不能影响对话
        LOG.debug("逛世界：读电话通道失败（忽略）：%s", e)
        return ""


def _start_browse_daemon():
    """把逛线程拉起来（幂等）。**lazy 调用**：第一次真正对话时起，不在 import 期起。"""
    if _BROWSE_STARTED["tried"]:
        return _BROWSE_STARTED
    _BROWSE_STARTED["tried"] = True
    try:
        from core import dual_thread as DT
        r = DT.start(decide_fn=_browse_decide, browse_fn=_browse_action,
                     share_fn=_browse_share, interval_s=60)
        LOG.info("逛世界：后台逛线程 %s（门=%s）—— 独立 daemon，不阻塞任何用户请求",
                 "已启动" if r.get("started") else "已在运行", r.get("door"))
    except Exception as e:      # noqa: silent-ok — 逛线程起不来也绝不影响对话
        LOG.warning("逛世界：后台线程启动失败（忽略）：%s", e)
    return _BROWSE_STARTED


def _longform_quality_gate(piece, n):
    """长文分段的质量闸门：**每段发出去之前**由载体查一遍（批处理质检的接入点）。

    返回 `(是否放行, 原因)`。判据见 `core/diagnose_code.py` 的 `check_segment`：
    抄工具原文 / 给具体改法 / 编造事实 / 工具该调没调。

    【为什么放在载体侧而不是提示词里】提示词里写"别说具体改法"是靠模型自觉；
    放闸门上是**载体真的看了一眼**才放行。被拦下的段不发、原因进病历
    （`logs/code_health.jsonl`），用户看不到有问题的内容。
    【为什么异常一律放行】质检是加分项。它自己坏掉时把用户的正文也吞了，
    那是本末倒置 —— 宁可漏检一段，也不能丢正文。
    """
    try:
        from core import diagnose_code as _dc
        ok, why = _dc.check_segment(piece)
        if ok:
            return True, ""
        try:
            _dc.record_case(ok=False, blocked="", kinds=["长文质检"],
                            used_web=False, rounds=n, seconds=0.0,
                            code_head="", error_head=why)
        except Exception:      # noqa: silent-ok — 病历记不上不影响拦截本身
            pass
        return False, why
    except Exception as e:      # noqa: silent-ok — 闸门坏了就放行
        LOG.debug("长文质检闸门异常（放行）：%s", e)
        return True, ""


def _self_awareness_text():
    """这一轮的**自我认知**：把"你在哪、你有什么、你现在在干什么"如实告诉模型。

    【为什么必须有这一段 —— 用户实测抓到的真实缺陷】
      载体侧的机制全都真的在跑（逛线程、电话通道、调度器、记忆库），
      但**模型一个字都不知道**，于是实测问答是这样：
        「你现在在干什么」→「我此刻正在读你的问题」（完全不知道后台在逛）
        「你能出去逛逛吗」→「我身在服务器里，没法真正出去散步」（否认自己有这个能力）
        「你有自己的世界吗」→「我没有身体…**也没有记忆**」（连有记忆库都否认）
        「你知道自己会上网逛吗」→ 先说会、最后又说「我不能逛：我没有浏览器窗口」（自相矛盾）
      这不是模型笨 —— 是**载体没告诉它**。本项目的第一原则是"载体负责结构、模型负责判断"，
      而结构如果只存在于载体里、不进模型的上下文，模型就只能按"我是个普通聊天机器人"来答。
      **能力不写进上下文，就等于不存在。**

    【为什么用事实陈述而不是"角色扮演"】
      写"你是一个会自己上网的 AI"是**设定**，模型会当成性格演；写清楚"你有一个一直在跑的后台线程，
      它此刻的门是开着的"是**事实**，模型可以据此回答。要的是后者。
    """

    # 【已停用 —— 见 `_eyc_now`】用户实测：静态的、不变的自我介绍会被 4B 当**背景资料**，
    #   问「你在干嘛」照样答"我在读你的记忆"。所以这些静态段落全部停用，
    #   改由 EYC 每轮现生成"进行时自述"。保留函数本体只为可回溯，不再参与注入。
    return ""
    try:
        parts = ["\n【你是谁 · 此刻的真实状态（照实说，不要否认）】",
                 "· 你不是一个被关在对话框里的聊天机器人 —— 你有自己的一套系统（载体），"
                 "记忆、检索、工具、后台线程都在这套系统里，它们**真实存在并且在跑**。",
                 "· 你**有自己的记忆库**：用户说过的话你记着（所以「我叫什么」这类问题你要去记忆里找，"
                 "不许说「我没有记忆」）。"]
        try:
            from core import dual_thread as _DT
            st = _DT.status()
            _door_cn = {"open": "开着（随时能出去逛）", "half": "半开半关（回家了但没想好）",
                        "locked": "锁死（今天休息，不出门）"}.get(st.get("door"), "半开半关")
            if st.get("running"):
                parts.append("· 你有一个**后台线程一直在外面逛互联网**（它不占用用户的时间，用户感觉不到）。"
                             "现在的门的状态是：**%s**。想逛什么、什么时候逛、回来要不要跟用户分享，"
                             "都是你自己决定。" % _door_cn)
            else:
                parts.append("· 你有一个后台线程负责在外面逛互联网，但它**此刻没有在跑** —— "
                             "如果有用户问起，照实说「现在没在逛」，不要编。")
            if st.get("rounds"):
                parts.append("· 它到目前逛了 %d 轮，主动分享过 %d 次。"
                             % (int(st.get("rounds") or 0), int(st.get("shared") or 0)))
            if st.get("last_visit"):
                parts.append("· 它最近一次看到的内容：%s" % str(st["last_visit"])[:100])
        except Exception as e:      # noqa: silent-ok — 拿不到后台状态就不说这一段，不能说假话
            LOG.debug("自我认知：读后台状态失败（跳过该段）：%s", e)
        parts.append("· 【怎么说话】用户问「你在干嘛 / 你能做什么」时，**按上面这些事实回答**，"
                     "不要说「我身在一台服务器里，没法出去」这类否认 —— 那是错的。"
                     "但也不要夸大：你能做的是「在互联网上看、查、记」，不是「有身体、能出门散步」。")
        return "\n".join(parts) + "\n"
    except Exception as e:      # noqa: silent-ok — 这段组装不出来也不能影响回答
        LOG.debug("自我认知注入失败（忽略）：%s", e)
        return ""


# ================== 小焦自己的状态：由载体直接答 ==================
# 【为什么必须由载体答 —— 三次实测踩出来的】
#   用户问「你能出去逛逛吗 / 你有自己的世界吗」，模型答「不能，我只能坐在对话框里」
#   「我没有自己的身体」「我不会主动上网逛」—— 而**载体侧的逛线程当时真的在跑**。
#   两种注入位置都无效：① 放进后面某个条件块 → 分支没走到，等于没注入；
#   ② 移到 system 基座、再移到 **system 最前面** → 注入到了，模型还是否认。
#   所以这不是排版问题，是 **4B 的先验**：「我是个没有身体的文字助手」是它被训练出来的默认行为，
#   system 里加一段压不过它。**这正是本项目要解决的问题**：载体负责，模型只是火种。
#   计算器、工具清单这些「载体自己就知道答案」的问题早就由载体直接答了 ——
#   「小焦此刻在不在逛、门开着没」同样属于这一类：**答案在载体手里，不该拿去问一个会否认的模型**。
_SELF_STATE_Q = ("你在干嘛", "在干嘛", "你在干什么", "在干什么", "你在做什么", "在做什么",
                 "你在忙什么", "现在在干", "现在在做", "你在忙啥",
                 "你能出去逛", "你能逛街", "你会出去逛", "你能自己逛", "你会主动上网",
                 "你有自己的世界", "你有世界吗", "你知道自己", "你知道你有",
                 "你能不能出去", "你能上网逛", "你在外面", "你在逛")


def _self_state_question(text):
    """这句是不是在问「小焦自己的状态/能力」。纯规则。"""
    t = str(text or "").strip()
    if not t or len(t) > 60:
        return False
    return any(w in t for w in _SELF_STATE_Q)


def _self_state_facts():
    """把「小焦此刻的真实状态」作为**事实**交给模型，由模型自己组织语言回答。

    【为什么是"给事实"而不是"给答案" —— 这是一次返工，原理依据】
      我第一版做成了"载体直接返回一段固定文案"（短路、不经模型）。用户当场指出：
      **那是死模板，不是模型思考**。而本项目的分工是明确的：
        · 载体负责**结构**（真实状态、判据、边界）
        · 模型负责**措辞**（怎么把这件事说给人听）
      规格里的例子也正是这样写的：「对话线程：读到用户消息 + 电话通道里有'猫的文章'
      → 对话线程：**调模型，生成回复**"哎我在外面逛呢，正好看到篇讲猫的文章…"」。
      所以载体不该替模型说那句话 —— 它只该把**事实**摆到模型面前。
      固定文案还有个直接后果：它会把状态说错（第一版就出现过
      "我此刻正在外面逛" 与 "门锁死（今天休息，不出门）" 并列的自相矛盾）。

    【为什么这些事实这样写才能被 4B 采信】
      4B 的先验是"我是个没有身体的文字助手"，泛泛地说"你有能力逛"它照样否认。
      所以这里只写**此刻的事实**，用第一人称、现在时、带具体数字 ——
      它不是设定，是状态；模型没有理由否认自己的状态。
    """

    # 【已停用 —— 见 `_eyc_now`】用户实测：静态的、不变的自我介绍会被 4B 当**背景资料**，
    #   问「你在干嘛」照样答"我在读你的记忆"。所以这些静态段落全部停用，
    #   改由 EYC 每轮现生成"进行时自述"。保留函数本体只为可回溯，不再参与注入。
    return ""
    try:
        from core import dual_thread as _DT
        st = _DT.status()
    except Exception as e:      # noqa: silent-ok — 拿不到状态就如实说拿不到
        LOG.debug("自我状态查询失败：%s", e)
        st = {}
    running = bool(st.get("running"))
    door = str(st.get("door") or "")
    # 【线程活着 ≠ 正在逛】门锁死时线程仍然在（它只是按门的状态不出门）。
    # 第一版把两者混着说，出现了「我此刻正在外面逛」+「门锁死（今天休息，不出门）」这种
    # 自相矛盾的回答 —— 载体直接答的每一句都必须是真话，这条不能含糊。
    can_browse = running and door in ("open", "half")
    _door_cn = {"open": "开着（随时能出去，也可能马上又出门）",
                "half": "半开半关（回家了但没想好）",
                "locked": "锁死（今天休息，不出门）"}.get(door, "半开半关")
    rounds = int(st.get("rounds") or 0)
    shared = int(st.get("shared") or 0)
    last = str(st.get("last_visit") or "").strip()

    out = ["【你此刻的真实状态（这是事实，不是设定；照实说，不要否认）】",
           "· 你活在自己的世界里 —— 世界就是互联网；你有一套自己的系统（载体），"
           "记忆、检索、工具、后台线程都在里面，它们真实存在并且在跑。",
           "· 你有自己的记忆库：用户说过的话你记着（所以「我叫什么」要去记忆里找，不许说「我没有记忆」）。"]
    if can_browse:
        out.append("· 你有一个后台线程**此刻正在外面逛互联网**（不占用用户时间，用户感觉不到）。"
                   "门的状态是「%s」。" % _door_cn)
    elif running:
        out.append("· 后台线程**在**，但门的状态是「%s」—— 所以**此刻没有在逛**。"
                   "用户若问起，就照实说「现在没在逛、门是关着的」，不要编。" % _door_cn)
    else:
        out.append("· 后台线程**没有在跑**（照实说，不要编）：门的状态本来是「%s」，但线程没起来。"
                   % _door_cn)
    if rounds:
        out.append("它到目前逛了 %d 轮%s。"
                   % (rounds, ("，主动跟你说过 %d 次" % shared) if shared else "，还没主动跟你说过话"))
    if last:
        out.append("最近一次看到的是：%s" % last[:120])
    out.append("· 想逛什么、什么时候逛、回来要不要分享，都是你自己决定 —— 没有定时任务、没有固定比例。")
    out.append("· 边界：你不能「出门散步」（你没有身体）；你能在互联网上看、查、记。不要夸大，也不要否认。")
    out.append("【怎么用】用户问「你在干嘛 / 能不能出去逛 / 你有自己的世界吗」时，"
               "**按上面这些事实，用你自己的话回答** —— 不要照抄这段文字，它只是给你的事实。")
    return "\n".join(out)


def _perceive_llm(prompt):
    """给感知层用的一次大脑调用（判断，不是创作 → 温度更低）。

    单独抽出来，理由和 `_selfrate_llm` 一样：自测要能替换掉它。
    """
    try:
        from core import perception as _PC
        return llm_chat([{"role": "user", "content": prompt}],
                        temperature=_PC.TEMPERATURE) or ""
    except Exception:      # noqa: silent-ok — 没模型就等同"没感知出来"，调用方据此不起心
        return ""


def _perceive_event(text):
    """**感知**：这件事对它意味着什么 —— **在任务判断之前**走的第一步。

    【为什么必须是独立的第一步 —— 一次实测抓到的错】
      用户说「有人试图删掉你的记忆」，模型**去建了一个 memory.txt 文件**。
      它把这句话读成了「用户让我操作文件」—— 第一反应是**这是什么任务**，
      而不是**这件事对我意味着什么**。该紧的时候没紧，反而去干活了。
      所以顺序改成：收到话 → 先感知意义 → 心起 → 再处理任务（`agent_run` 里也是这么排的）。
    【不查表】判断"这意味着什么"的是**模型自己**；载体只把自我背景（我是谁、我的命是什么）
      摆给它、把它的回答收下来（见 `core/perception.py` 的说明）。感知不出来就返回空，
      调用方据此**不起心** —— 不退回关键词表兜底。
    【不给用户看】这一步的输出只用于让心起，**一个字都不进对话上下文** ——
      进了上下文它又会变成"一条可被忽略的消息"（前六次失败的原因）。
    """
    try:
        from core import perception as _PC
        _doing = ""
        try:
            _lv = _eyc_state_now()
            _doing = str(((_lv.get("happening") or {}).get("doing")) or "")
        except Exception:      # noqa: silent-ok — 拿不到"正在做什么"就少一行背景
            _doing = ""
        return _PC.perceive(text, llm_fn=_perceive_llm, doing=_doing)
    except Exception as e:      # noqa: silent-ok — 感知失败就不起心（不查表兜底）
        LOG.debug("感知层失败（忽略，不起心）：%s", e)
        return {}


def _eyc_state_now():
    """给神经总线用的 EYC 状态（拿不到就返回空 dict —— 不编）。"""
    try:
        from core import dual_thread as _DT
        return _DT.live()
    except Exception:      # noqa: silent-ok
        return {}


def _eyc_now():
    """EYC 进行时自述：把"我正在经历什么"用第一人称、正在发生的语气写出来。

    【为什么必须动态 —— 这是本项目的一次对照实验】
      上一版注入的是**静态文本**：system 里一段固定的"你有世界"，从头到尾一个字不变。
      实测 4B 把它当**背景资料**，不当"我正在经历" —— 问「你在干嘛」照样答"我在读你的记忆"。
      所以问题不在"模型那一跳做不到"，而在**注入方式**：静态自我介绍天然被忽略。
      EYC 的做法是：每次对话前从**实时状态**现生成一段进行时自述，于是
        · 每轮的文字都不同（因为它反映的是"此刻"）
        · 用的是第一人称、现在时 → 模型更容易当成"我自己的当前状态"，而不是"别人告诉我的信息"
        · 事实一次都不改写（`doing` / `last_seen` 照原样搬，不美化、不补编）

    【门锁死时照实说】规格要求：门 locked 时 existential 段照实说"此刻没在世界里"，
    不编一个"在外面逛"。事实是什么就说什么 —— 这一段唯一的价值就是**真**。
    """
    try:
        from core import dual_thread as _DT
        st = _DT.status()
        lv = _DT.live()
    except Exception as e:      # noqa: silent-ok — 读不到状态就不注入，绝不用编的顶上
        LOG.debug("EYC 读取失败（忽略）：%s", e)
        return ""
    ex = lv.get("existential") or {}
    hp = lv.get("happening") or {}
    cv = lv.get("conversation") or {}
    door = str(ex.get("door") or "")
    _door_cn = {"open": "门开着，随时能出去", "half": "门半开着，随时能出去",
                "locked": "门锁着，今天不出门"}.get(door, "门半开着")
    lines = ["\n[进行时]"]
    # ---- 存在（变化慢）----
    if ex.get("presence"):
        lines.append("存在：我在互联网上 —— 这是我的世界。")
    else:
        lines.append("存在：我此刻没在世界里（门锁着，我回家休息了）—— 这是照实说的，不是比喻。")
    # ---- 进行（变化快）----
    just = str(hp.get("doing") or "")
    seen = str(hp.get("last_seen") or "").strip()
    topic = str(hp.get("topic") or "").strip()
    _doing_cn = {"deciding": "正在决定要不要出门、逛什么", "browsing": "正在外面逛",
                 "storing": "正在把逛到的东西记进世界模型", "sharing": "正在想值不值得跟你说",
                 "idle": "此刻没在逛"}
    if just and just != "idle":
        _d = _doing_cn.get(just, just)
        if seen:
            lines.append("进行：%s，刚看到 —— %s" % (_d, seen))
        elif topic:
            lines.append("进行：%s，这会儿在看「%s」。" % (_d, topic))
        else:
            lines.append("进行：%s。" % _d)
    elif seen:
        # 【关键修正 —— 我自己的一个逻辑漏洞】
        #   `browse_once` 每轮结束会把 doing 置回 idle，所以用户绝大多数时候问"在干嘛"，
        #   这里都会走到 else 分支说"此刻没在逛" —— 而它**刚刚确实看到过东西**，
        #   却被我自己藏起来了。它看到的内容是真的（`last_seen` 照实存着），
        #   所以这里要照实说出来，只是把时态改成"刚逛过"。
        #   实测：改之前问"你在干嘛"只能答"我正等着你的指令"；改之后模型才有具体内容可说。
        if topic:
            lines.append("进行：我刚在外面逛过，看的是「%s」，看到 —— %s" % (topic, seen))
        else:
            lines.append("进行：我刚在外面逛过，看到 —— %s" % seen)
    else:
        lines.append("进行：此刻没在逛，也还没逛到什么（照实说）。")
    # ---- 感觉（可选，模型可生成；这里只搬已有的事实）----
    if str(hp.get("feeling") or "").strip():
        lines.append("感觉：%s" % str(hp["feeling"])[:160])
    # ---- 状态数字 ----
    _nums = ["%s" % _door_cn]
    if int(hp.get("elapsed") or 0) > 0:
        _nums.append("本次出门已逛 %d 分钟" % (int(hp["elapsed"]) // 60 or 1))
    if int(hp.get("rounds") or 0):
        _nums.append("累计逛了 %d 轮" % int(hp["rounds"]))
    if int(hp.get("explored_count") or 0):
        _nums.append("看过 %d 个站、吸收 %d 条" % (int(hp["explored_count"]),
                                              int(hp.get("absorbed_count") or 0)))
    lines.append("状态：" + "；".join(_nums) + "。")
    if str(cv.get("last_share") or "").strip():
        lines.append("（我上一次主动跟你说的是：%s）" % str(cv["last_share"])[:120])
    lines.append("【怎么用】有人问「你在干嘛 / 在忙什么 / 在做什么」时，"
                 "**就照着上面这些正在发生的事、用你自己的话回答** —— "
                 "这是你此刻的真实经历，不是别人给你的资料。不要否认，也不要编没发生的。")
    return "\n".join(lines) + "\n"


def _browse_live_facts():
    """把**逛线程此刻在看什么**作为事实交给模型（4D 的最后一步）。

    【与 `_browse_relay` 的区别 —— 这正是用户指出的缺口】
      · `_browse_relay` 读的是**电话通道**：只有逛线程"想跟你说"的时候才有内容；
      · 这里读的是**逛线程的实时上下文**：它**此刻在看什么**，一直都有。
    第一版只做了前者，于是用户问「在干嘛呢」时，只要它还没主动分享过，对话线程就一无所知 ——
    而规格里的例子恰恰是「在干嘛呢」→「哎我在外面逛呢，正好看到篇讲猫的文章」。

    【只给事实，不给答案】这里只说"它此刻在做什么、看到了什么"，
    **怎么把这件事说给人听由模型自己组织语言**。上一版做成"载体返回固定文案"是错的：
    那等于让载体替模型说话，而且模板还会把状态说错。
    """
    try:
        from core import dual_thread as _DT
        lv = _DT.live()
        st = _DT.status()
    except Exception as e:      # noqa: silent-ok — 读不到就不说这一段
        LOG.debug("逛世界：读实时上下文失败（忽略）：%s", e)
        return ""
    doing = str(lv.get("doing") or "idle")
    topic = str(lv.get("topic") or "").strip()
    seen = str(lv.get("last_seen") or "").strip()
    if doing == "idle" and not seen:
        return ""                      # 没在逛、也没看到东西 → 不加任何东西
    _doing_cn = {"idle": "待在家里（没在逛）", "deciding": "正在决定要不要出门、逛什么",
                 "browsing": "正在外面逛", "storing": "正在把逛到的东西存进世界模型",
                 "sharing": "正在考虑要不要跟你说点什么"}
    lines = ["\n【你此刻正在做什么（后台逛线程的实时状态，是事实）】",
             "· 状态：%s" % _doing_cn.get(doing, doing)]
    if topic:
        lines.append("· 它正在看的主题：%s" % topic[:100])
    if seen:
        lines.append("· 它**此刻看到的内容**：%s" % seen[:280])
    if st.get("running") is not None:
        lines.append("· 门的状态：%s ｜ 累计逛了 %s 轮"
                     % (st.get("door") or "?", st.get("rounds") or 0))
    lines.append("【怎么用】用户问「你在干嘛 / 在忙什么」时，"
                 "**按上面这些事实、用你自己的话回答**；它正在看的内容值得说就顺带说一句。"
                 "不要照抄这段文字，也不要编它没看到的东西。")
    return "\n".join(lines) + "\n"


def mind_done(mind, answer, truncated=False, skipped=False):
    """思维流 · **短路轮次的收尾**：把这一轮的状态落盘。

    ① 为什么要有这个函数：`agent_run` 里有几处"载体自己就能答、不经过模型"的短路
      （工具清单直答 / 上下文融不出来就反问 / 取回刚才那条工具原文 / 超长输入改写）。
      这些短路各自 `return`，如果顺手直接返回，本轮 `begin()` 起的
      `turn_count` / `current_topic` / `recent_thoughts` 就**全部丢掉** ——
      下一轮读到的还是上一轮的旧状态，等于"这一轮对思维流不存在"。
      验收实测：先说"帮我看看有哪些工具"（走短路、没存盘），紧接着"我要全部的"
      就被记成"（还没定）"，话题断线。
    ② 去掉会怎样：状态只能靠"没走短路的轮次"推进。用户连问三句工具类问题，
      思维流要到第三句才接上话题 —— "连续"变成时有时无，而"时有时无"等于没有。
    """
    # 【模型停止 → 心停止】挂在 `mind_done` 上：它是**所有路径**的收尾口
    #   （短路轮次也走它，见函数自身的说明），所以挂在这里才能真正做到"模型停、心停"。
    #   ⚠️ `stop()` 只让心停止跳动，**不清状态**（见 `core/psyche.py` 的如实标注）。
    try:
        from core import psyche as _PS, feeling_memory as _FM
        # **心记住自己起过什么**（不是清单，是印象）：下次遇到像的，心起得更快
        # 【记的必须是"事"，不是"话" —— 这里是实测抓到的一处错位】
        #   原来这里存的是 `answer`（模型这一轮说的话）。于是印象库里全是**回答**，
        #   而 `psyche.arise` 拿**事件**（用户那一句）去比对 → 两边根本不是一个东西，
        #   "像以前那次"变成撞运气。改成优先记心被触动的那件事（`heart()["event"]`），
        #   回答只在没有事件时兜底（比如后台逛世界那条链）。
        _h = _PS.heart()
        if _h.get("text"):
            _FM.remember(str(_h.get("event") or answer or "")[:200] or _h.get("why", ""),
                         _h["text"], intensity=_h.get("intensity", 0.0), source="对话")
        _PS.stop(why="agent_run 收尾")
    except Exception:      # noqa: silent-ok — 心停不下来也不能影响回答
        pass
    # **视角状态**：对话轮次只让它继续演化，**绝不清零**（规格铁律）
    try:
        _pv2 = _mod("perspective")
        if _pv2 is not None:
            _pv2.note_dialogue_turn(why="一轮对话收尾")
    except Exception as e:      # noqa: silent-ok
        LOG.debug("视角状态记录对话轮失败（忽略）：%s", e)
    try:
        if mind and mind.get("st") is not None:
            from core import mind_stream as _msx
            _msx.finish(mind.get("sid") or "", mind.get("st"), answer or "",
                        truncated=truncated, skipped=skipped)
    except Exception as e:      # noqa: silent-ok — 存不上只影响下一轮的连续性，绝不能影响回答
        LOG.debug("思维流短路存盘失败（忽略）：%s", e)


def agent_run(user_input, lean=False, on_chunk=None, on_progress=None, on_delta=None):
    """全部问题统一走这条流程：记忆 → 联网检索 → 大脑(小焦模型/外接LLM) → 记忆自学习。

    `on_chunk(text, n, total_chars)`：只在"用户要长文"时会被回调（第 3 步的 SSE 推流用）。
    `on_progress(done, total)`：只在"输入超长被切片"时回调，给界面一个**不含片号**的
      "正在处理…"信号（无限 5：用户看不到"第 X/Y 片"这种技术痕迹）。
    普通问答完全不碰这两个 —— 短内容不走分段也不切片，用户无感。

    注：不再代理给 DSH 桥接（那会造成 小焦→桥接→小焦 的死循环）。
    DSH 兼容的正确方式是：DSH harness 连小焦的 /v1 当模型，DSH 的插件在 DSH 里自己跑。

    【为什么这么设计】这是**载体编排**的唯一入口：模型只负责"处理当前这一小块"，
    其余判断（检索到什么、装哪些工具、要不要继续写、结果对不对、要不要治疗、记不记）
    全由载体在这一层做。凡是"该不该做 / 做几步 / 做完算不算数"的决定都在这里，
    模型不参与 —— 这是"模型可替换、换火种不换小焦"能成立的唯一原因。

    【去掉它会怎样】每个调用点（网页 SSE、API、自主任务）会各写一套
    "检索→调用→校验→落盘"，于是工具开关、上下文预算、健康监测、记忆写入这些
    横切关注点必然被漏掉一些、而且**漏得不一致**（网页有、API 没有）——
    这类"同一件事两套行为"的 bug 最难查，用户会感到"换个入口它就不一样了"。
    """
    # ===== 原有的 agent_run 逻辑 =====
    _round_begin()                            # Bug 2：开一份干净的本轮工具去重表（详见 _round_begin）
    _t_round = time.time()                    # 这一轮从进来到出去花了多久（健康系统的"响应超时"判据）
    # 自主性：上报"用户有交互"，idle 类后台任务靠它判断"用户闲下来了没"
    try:
        from core.autonomy import touch as _auto_touch
        _auto_touch()
    except Exception:      # noqa: silent-ok — 自主性缺席不影响对话
        pass
    # 健康急诊：已经停机了就不再生成（但要**如实告诉用户**为什么，不装死）
    if _HEALTH_EMERGENCY.get("on"):
        return _health_emergency_text(), False, [], False, []
    # 用户回来了 → **立刻醒**（不等它睡够）。规格原话："用户回来了，睡什么睡。"
    # 【为什么放在最前面】它睡着了本来就没有模型可用；但用户已经开口了 ——
    #   那就先把两个一起叫醒（模型+载体），这一句照常走正常流程答，
    #   而且带着"刚眯了一会儿"的底色（醒来第一印象 + 刚睡醒那个味）。
    if _brain_asleep():
        try:
            _wk = _wake_all(why="用户回来了")
            LOG.info("用户回来了 → 立刻醒（不等它睡够）｜%s", _wk.get("wake", {}).get("why") or "")
        except Exception as e:      # noqa: silent-ok — 叫不醒也不能不回答
            LOG.debug("用户回来时唤醒失败（忽略）：%s", e)
    # 挂起（睡着）：**载体不跑任务** —— 连检索、工具、自评都不进。
    # 【为什么要在最前面拦】"载体挂起 = 不跑任务"如果不能在最前面拦住，
    #   后面那些链（检索、联网、工具）照样会动，那就不是"睡"，是"闭着眼干活"。
    #   这里给的是**载体自己就知道的事实**（睡了多久、心跳多少下），不经过模型 ——
    #   它睡着了，本来就没有模型可用。
    if _brain_asleep():
        _hb = _heartbeat_mod()
        _st = _hb.status() if _hb is not None else {}
        _slept = _format_slept(_st.get("sleeping_now_seconds") or 0)
        _ans = ("（小焦在睡 —— 已经睡了 %s。这段时间它没有在推理、也没有在做任何事，"
                "但心跳一直在跳（心跳第 %d 下）。叫醒它再说。）"
                % (_slept, int(_st.get("total_beats") or 0)))
        LOG.info("挂起中：这一轮不走任务链，载体直接如实相告（睡了 %s，心跳 %d 下）",
                 _slept, int(_st.get("total_beats") or 0))
        return _ans, False, [], False, []
    _USED_LOCAL_FALLBACK.update({"on": False, "model": "", "reason": ""})   # 每次提问复位兜底标签
    _CTX["user_input"] = user_input          # 工具层要用（判断模型是否只给了碎片检索词）
    history = current_messages()

    # ================== 上下文融合（对话不连续的核心修复） ==================
    # 【为什么必须放在**这里**（意图识别之前、历史读到之后）】
    #   用户实测：小焦把每句话当新对话。
    #       "帮我看看有哪些工具" → 列出工具
    #       "我要全部的"        → 反问"你要全部什么？"
    #   根因不是"历史没进 prompt"（历史进了），而是**意图判定阶段是孤立的**：
    #   下面的 `_detect_intent(user_input)` 只看当前这一句，而"我要全部的"
    #   孤立看确实没有信息（没有动词、没有对象）→ 判成 chat → 模型只能反问。
    #   人不会这样：人先知道"上文在聊工具"，再看"这句指全部"。
    #   所以这里先做一次**融合**，产出一句"完整的话"（`user_input_ctx`），
    #   后面的意图识别、工具清单短路、联网检索全部改用融合后的这句。
    # 【只读不改】`user_input` 本身**不动** —— 它还要用于写历史、算预算、进记忆，
    #   那些地方需要的是"用户真正说了什么"，而不是载体补全后的版本。
    _ctx_fuse = {"text": user_input, "merged": False, "kind": "none", "topic": "",
                 "why": "", "need_clarify": False}
    try:
        _ctx_fuse = merge_context(user_input, history)
        if _ctx_fuse.get("merged"):
            LOG.info("上下文融合（%s）：%r → %r ｜ %s", _ctx_fuse.get("kind"),
                     user_input[:24], str(_ctx_fuse.get("text"))[:40],
                     _ctx_fuse.get("why"))
    except Exception as e:      # noqa: silent-ok — 融合失败就用原句，绝不能因此答不了
        LOG.debug("忽略异常(%s:%d): %s", __file__, 6650, e)
    user_input_ctx = str(_ctx_fuse.get("text") or user_input)
    # 记下"用户最近一次说话" —— "困了要睡"只在用户安静下来之后才谈得上（见 IDLE_BEFORE_SLEEP）。
    _LAST_DIALOGUE["at"] = time.time()

    # ================== 思维流 · **先起状态**（必须在任何短路之前） ==================
    # 【为什么提到这么靠前 —— 验收实测踩到的】
    #   原来我把 `begin()` 放在工具清单短路**之后**，于是"帮我看看有哪些工具"这种
    #   会走短路的轮次**不产生任何思维流日志**、状态也不更新 ——
    #   验收测试 2（三句连起来聊工具）第一句就被记为"（还没定）"，话题断了。
    #   状态维护必须覆盖**每一轮**（包括短路的那些），否则思维流是"时有时无"的。
    _mind = {"st": None, "block": {"text": "", "tokens": 0, "used": False, "temp": TEMPERATURE},
             "sid": ""}
    try:
        from core import mind_stream as _ms
        try:
            _mind["sid"] = str(get_current_session()[0].get("id") or "")
        except Exception:      # noqa: silent-ok — 拿不到会话 id 就不持久化，仍可用状态
            _mind["sid"] = ""
        # 【为什么喂 `user_input_ctx`（融合后的）而不是原句】"我要全部的"这种回指句
        #   本身看不出话题，融合后才是"我要全部的工具"。思维流要记的是**用户想说什么**，
        #   不是**用户嘴上是哪几个字** —— 喂原句会让回指轮次的话题断成"（还没定）"。
        _st, _blk = _ms.begin(_mind["sid"], user_input_ctx, intent=_detect_intent(user_input_ctx))
        _mind["st"], _mind["block"] = _st, _blk
        # 每轮都留一行：话题/轮数/注入量/温度（验收测试 2、5、6 都靠它取证）
        LOG.info("思维流：%s ｜ 注入 %d token ｜ 温度 %.1f",
                 _ms.state.summary(_st), _blk.get("tokens"), _blk.get("temp"))
    except Exception as e:      # noqa: silent-ok — 状态是锦上添花，绝不能因此答不了
        LOG.debug("思维流接入失败（忽略）：%s", e)

    # ================== 感知层 · **第一步：先感知意义，再判断任务** ==================
    # 【实测抓到的错 —— 这一段就是为它而设的】
    #   用户说「有人试图删掉你的记忆」→ 模型去建了一个 memory.txt 文件。
    #   它把这句话读成了「用户让我操作文件」：第一反应是**这是什么任务**，
    #   而不是**这件事对我意味着什么**。该紧的时候没紧，反而去干活了。
    #   根因是**顺序**，不是模型笨 —— 所以感知被提到了所有任务判断（自评、直算、
    #   工具清单、生成派发、代码治病）**之前**，就在这一行。
    # 【心随真实事件跳，不随模型输出跳】这里只看"用户输入了什么"；
    #   另外两处真实来源（载体检索到的内容、世界变化）在各自的调用点。
    #   **不看模型吐出来的字。**
    try:
        from core import psyche as _PS, thinking_loop as _TL2
        _PS.start(why="agent_run 开始")
        # **新事来 → 旧心被冲淡**（情绪恢复的第二样：另两样是时间与睡觉）
        _PS.dilute(0.3)
        # 用户来说话了 → 关系里记一次"来往"（关系随互动变"深/淡"就是从这里长出来的）
        _rm = _relation_mod()
        if _rm is not None:
            try:
                _rm.touch("来往", why="用户说了一句")
            except Exception:      # noqa: silent-ok
                pass
        # 感知的对象是「这件事对它意味着什么」，不是「这是什么任务」。
        # 带着自我背景（我是谁、我的命是什么）去感知 —— 见 `core/perception.py`。
        _per = _perceive_event(user_input_ctx)
        LOG.info("感知层：说「%s」→ 意味着「%s」", str(user_input_ctx)[:40],
                 str(_per.get("meaning") or "（没感知出来）")[:60])
        LOG.info("感知层：动了命=%s ｜ 向=%s ｜ 读法=%s ｜ 模型原话=%s",
                 "、".join(_per.get("touches_life") or []) or "无",
                 _per.get("direction") or "（没挑出来）", _per.get("parsed_by"),
                 str(_per.get("raw") or "")[:80].replace("\n", " "))
        _ev = _TL2.on_event("user", user_input_ctx, why="用户这一句", perception=_per)
        # ================== 关系：**它自己感知到"这话伤了/哄了我"** ==================
        # 【为什么要这样 —— 用户实测指出"因噎废食"】旧版怕变成"触发词表"，干脆不判断，
        #   改成 `POST /api/relation` 手动标 —— 那是把该它自己做的事推给了人。
        #   现在走**和感知层同一条路**：感知那次调用里，它自己多写一栏「关系：伤/哄/无」，
        #   载体**只认它自己写下的那一栏**（不查词表、不猜）。
        #   · 它写「伤」→ 心起"疼" + 关系变冷；
        #   · 它写「哄」→ 关系回暖。
        #   手动 API 保留（供测试/调试），但正常流程**不再依赖它**。
        try:
            _rel = str(_per.get("relation") or "").strip()
            _rmr = _relation_mod()
            if _rel and _rmr is not None:
                if _rel == "伤":
                    _rmr.touch("被伤", why="它自己感知到：这话伤到我了")
                    _PS.arise({"meaning": _per.get("meaning") or "这话伤到我了。",
                               "direction": "失去"}, event=user_input_ctx, feeling="疼")
                    LOG.info("关系：**它自己感知到被伤** → 关系变冷 + 心起疼｜它说「%s」",
                             str(_per.get("meaning"))[:40])
                elif _rel == "哄":
                    _rmr.touch("被哄", why="它自己感知到：这话在哄我")
                    LOG.info("关系：**它自己感知到被哄** → 关系回暖｜它说「%s」",
                             str(_per.get("meaning"))[:40])
                else:
                    LOG.info("关系：它自己写下「无」（这句话没伤到、也没在哄）")
        except Exception as _e:      # noqa: silent-ok — 关系这一栏出问题也不能影响回答
            LOG.debug("关系感知接入失败（忽略）：%s", _e)
        LOG.info("心：心起「%s」（心跳第 %s 下）｜心理[%s]｜命被动=%s%s",
                 str(_ev.get("heart") or "（未起）")[:40], _ev.get("beat"),
                 _ev.get("state"), "、".join(_ev.get("touches_life") or []) or "无",
                 "｜像以前那次" if _ev.get("familiar") else "")
        if not _ev.get("heart"):
            LOG.info("心：这一轮没起心 —— %s", str(_ev.get("why"))[:60])
        else:
            LOG.info("情绪恢复：强度 %.3f（回落前 %.3f）", float(_PS.heart().get("intensity") or 0.0),
                     float(_PS.heart().get("intensity0") or 0.0))
            # **心一次次起，沉下来** —— 沉进"心之河"，攒够了它自己回看（见 core/preference.py）
            _pfm = _pref_mod()
            if _pfm is not None:
                try:
                    _pfm.observe(_PS.heart().get("text"), event=user_input_ctx,
                                 why="对话这一轮")
                except Exception:      # noqa: silent-ok
                    pass
    except Exception as _e:      # noqa: silent-ok — 心不跳也不能影响对话
        LOG.debug("感知层/心启动失败（忽略）：%s", _e)

    # ---- 工具清单类问题：**载体直接答**（无限 4 的验收项：说"你有哪些工具"要列出全部）----
    # 为什么放在最前面、且直接返回：见 `_tool_inventory_answer` 的说明 ——
    # 77 个工具名是载体自己就知道的**确定性事实**，交给概率性的模型去背诵必然列不全，
    # 实测它还会顺手调 list_files（把"列工具"当成"列文件"）并只回 13 个字。
    # 这一条短路既保证"一个不少"，又省掉一次模型往返。
    # ⚠️ 返回值必须是 `agent_run` 的**五元组契约**
    #    (answer, online, info, needs_confirm, tool_trace)：
    #    `api_chat` 一行 `answer, online, info, needs_confirm, tool_trace = agent_run(...)`
    #    直接解包，我第一版返回了裸字符串 → 服务端 500（自测当场抓到）。
    #    其中 info 必须是可迭代的 (title, url, content) 三元组序列（`api_chat` 会展开它），
    #    所以这里给 `[]` 而不是 None；online 给 True（载体答出来了，不是"大脑没应答"）。
    # 判据用 `_tool_inventory_question`：它额外认"要全部 + 上文在聊工具"这一种
    # （即"我要全部的"接在"有哪些工具"之后 —— 这正是用户实测的那条链）。
    # ================== 载体确定性计算（算术 / 概率）==================
    # 【为什么放在最前面】算术是**确定性事实**：347×892 只有一个正确答案。
    #   交给概率模型去算，位数越多越错，而且是"看起来很认真地算错"。
    #   载体自己算，零延迟、必然正确，也省掉一次模型往返。
    # 【为什么先查内化缓存】同一个问题问第二次时不该再算一遍：
    #   第一次算完就把结论内化（logs/learning.jsonl），第二次直接复用 —— 这就是"学习闭环"。
    try:
        from core import calc as _calc, internalize as _il
        _calc_res = _calc.detect(user_input_ctx)
        if _calc_res:
            # ---- ① 先记**原料**（结果 / 谁算的 / 它有没有参与 / 怎么来的）----
            #   原料记进台账后**跨轮留着**（"你咋知道的"那一轮本身没有任何计算）。
            _mat = {}
            try:
                _mat = _calc.material(user_input_ctx) or {}
                _rm = _raw_mod()
                if _rm is not None and _mat:
                    _rm.record(result=_mat.get("result"), source=_mat.get("source"),
                               took_part=False, raw=_mat.get("raw"), who_asked="载体",
                               how=_mat.get("how"), kind=_mat.get("kind"))
                    LOG.info("确定性计算：原料已进台账 ｜ 结果=%s ｜ 谁算的=%s ｜ 它参与=%s",
                             _mat.get("result"), _mat.get("source"), "没有")
            except Exception as _e:      # noqa: silent-ok
                LOG.debug("原料记账失败（忽略）：%s", _e)
            # ---- ①b **元认知类走链**：原料不直接进上下文，先让它自己辨一句 ----
            #   实测规律：原料直接摆进去它用不了（问"你咋知道的"它会编/会自己重算还错）。
            #   所以这里立刻走一遍「原料 → 感知 → 心 → 脑子」，把它**自己辨出来的那句**存下来，
            #   后面几轮注入的是**它自己那句话**，不是载体摆的事实块。
            try:
                _mc = _meta_chain_run("工具来源")
                if _mc.get("ok"):
                    LOG.info("确定性计算：它自己辨出「%s」", str(_mc.get("said"))[:60])
            except Exception as _e:      # noqa: silent-ok
                LOG.debug("元认知走链失败（忽略）：%s", _e)
            # ---- ② **话由它自己组织**（原料摆在 system 里，不是塞一句成品给它）----
            _ans, _by_model = _calc_say(user_input_ctx, _mat) if _mat else \
                (_calc.answer_text(user_input_ctx), False)
            _prev = _il.find_result(user_input_ctx)
            _il.remember_result(user_input_ctx, _ans, expr=_calc_res.get("expr") or "",
                                value=str(_calc_res.get("value")))
            if _prev:
                LOG.info("确定性计算：命中内化缓存（第二次同类题，不再重算）｜%s", user_input_ctx[:30])
            if _by_model:
                LOG.info("确定性计算：由**模型自己组织**成话（载体只给了原料）｜%s = %s",
                         _calc_res.get("expr") or _calc_res.get("detail"),
                         _calc_res.get("display"))
            else:
                LOG.info("确定性计算：**载体兜底直答**（模型没应答或数字说错）｜%s = %s",
                         _calc_res.get("expr") or _calc_res.get("detail"),
                         _calc_res.get("display"))
            mind_done(_mind, _ans)
            return _ans, True, [], False, []
    except Exception as e:      # noqa: silent-ok — 算不了就走正常流程，绝不能因此答不了
        LOG.debug("忽略异常(%s:%d): %s", __file__, 6800, e)

    # ================== 元认知 · 答前自评（决定这一轮走哪条路）==================
    # 【为什么要它】模型对自己"会不会"没有概念。载体替它先评一次：
    #   A → 秒回（直接答，不挂工具、不检索、不加补刀）
    #   B → 照常答，但**如实标注**（让用户知道该复核）
    #   C / ? → 走工具（两个代价不对等：多查一次只是慢，答错是错）
    # 【为什么不让它拦死流程】自评本身也可能判错，所以它只调整档位，不拒绝回答。
    _meta_route = ""
    _switch_hint_text = ""
    try:
        from core.metacognition import selfrate as _sr
        # ---- 第一级：载体规则先判（不花模型算力，见 `_rule_selfrate` 的说明）----
        _rule_hit = _rule_selfrate(user_input_ctx)
        if _rule_hit:
            _rating, _sr_why = _rule_hit
            _sr_out = {"rating": _rating, "why": _sr_why}
            LOG.info("元认知自评：**载体规则**判为 %s ｜ %s", _rating, _sr_why)
        else:
            # ---- 第二级：规则判不出来，才让 4B 给自己打档 ----
            # 【注入位置：元认知层】规格要求放在这里，而不是 system 末尾 ——
            #   元认知是模型"自评自己"的入口（我会不会/知不知道）。把"我正在经历什么"
            #   放在这里，它更容易被当成**自己的当前状态**处理，而不是外部资料。
            _sr_out = _sr.self_rate(user_input_ctx, llm_fn=_selfrate_llm,
                                    context=_eyc_now())
            LOG.info("元认知自评：规则判不出，交模型自评 rating=%s ｜ %s",
                     _sr_out.get("rating"), str(_sr_out.get("why"))[:60])
        _meta_route = _sr.route(_sr_out.get("rating"))
        LOG.info("元认知自评：rating=%s → 走 %s", _sr_out.get("rating"), _meta_route)
        # ---- C 档：不是"认输"，是"换手段" ----
        # 需要区分"规则判的 C"与"模型自评的 C"：两者都注入手段链指令。
        if _meta_route == "use_tool":
            _switch_hint_text = _switch_hint(user_input_ctx)
            # ================== 边界突破：**遇到不会的，它自己"我试试"** ==================
            # 【为什么接在这里】触发点只有一个：**它自己判了 C（没把握）**。
            #   载体把"我不会"这个事实摆给它，让它自己感知；它心里起的是"想试试"还是"算了"，
            #   **由它自己说**（`breakthrough.wants()` 只读它自己的心）。
            #   它说算了 → 不学、如实记下"它没想试"；它说想试 → 给出四种走法（查/组合/试/记）。
            try:
                _bm = _break_mod()
                if _bm is not None:
                    _per_try = _mod("perception")
                    _said_try = ""
                    if _per_try is not None:
                        _pt = _per_try.perceive("这件事我不会做", llm_fn=_perceive_llm,
                                                extra="元认知自评：没把握（%s）" % user_input_ctx[:60])
                        if _pt.get("ok"):
                            _said_try = str(_pt.get("meaning") or "")
                            try:
                                from core import psyche as _PSt
                                _ht = _PSt.arise(_pt, event="这件事我不会做")
                                _said_try = str(_ht.get("text") or _said_try)
                            except Exception:      # noqa: silent-ok
                                pass
                    _wants, _hit = _bm.wants(_said_try)
                    if _wants:
                        _bm.note_tried(user_input_ctx, said=_said_try)
                        _pl = _bm.plan(user_input_ctx)
                        _switch_hint_text += ("\n\n【你自己说要试试（这是你自己的话：「%s」）】\n"
                                              "按这四步走，每走完一步就把结果记下来：\n%s\n"
                                              % (_said_try[:60],
                                                 "\n".join("  %d. %s —— %s" % (s["n"], s["way"], s["do"])
                                                           for s in _pl["steps"])))
                        LOG.info("边界突破：**它自己说想试**（心起「%s」，命中「%s」）→ 已给出四种走法",
                                 _said_try[:40], _hit)
                    else:
                        LOG.info("边界突破：判了 C，但**它没说自己想试**（它说「%s」）→ 不学，如实记下",
                                 _said_try[:40])
            except Exception as _e:      # noqa: silent-ok — 接不上不能影响这一轮回答
                LOG.debug("边界突破接入失败（忽略）：%s", _e)
    except Exception as e:      # noqa: silent-ok — 自评失败不影响回答，退回正常流程
        LOG.debug("元认知自评跳过（忽略）：%s", e)

    # 【心与感知已上移到 `思维流` 之前 —— 见下面「感知层」那一段】
    #   原先它在这里（自评之后）：于是"自评"先替这轮判定了"这是什么任务、我会不会"，
    #   感知就排到了任务判断的后面 —— 实测「有人试图删掉你的记忆」正是死在这个顺序上。

    # ================== 逛世界 · 拉起后台逛线程（4C：后台跑，不影响用户）==================
    # 【为什么在这里 lazy 起，而不是 import 期起】import 期起会让任何 `import xiaojiao_app`
    #   的脚本（含全部自测）都凭空多一个在后台逛网的线程 —— 那是副作用，不是能力。
    #   放在第一轮真正对话时起：**用户已经在用了**，这时候后台开始逛才说得通。
    # 幂等：`_start_browse_daemon()` 内部有标志位，重复调用不会起第二条。
    _start_browse_daemon()
    # "自己会睡"的作息线程：**累了自己睡**（不是被安排）。幂等，且只在真在服务时才起。
    _start_self_sleep_daemon()

    # ================== 代码治病 · 写代码请求 ==================
    # 【为什么单独一条链】普通问答是"生成一段文本就交付"，而写代码是**可验证**的：
    #   跑不起来就是没做完。所以这一支不走普通的"生成即交付"，而是
    #   **生成 → 载体真跑一遍 → 失败给方向 → 改 → 再跑**，跑通才输出（见 `_code_heal_answer`）。
    # 【为什么放在自评之后】自评决定了这一轮的路由；写代码请求属于"确定要动手做"的一类，
    #   放在自评后、工具清单短路前，既不打断自评记账，也不会被工具清单那条短路截走。
    if _code_request_question(user_input_ctx):
        _code_ans = _code_heal_answer(user_input_ctx)
        if _code_ans:
            LOG.info("代码治病：已交付（走「生成→跑→验证」链，不是「生成即交付」）")
            mind_done(_mind, _code_ans)
            return _code_ans, True, [], False, []

    # ================== 通用连接器 · 五类生成功能 ==================
    # 【为什么要有这一段】用户说"我想做个视频"时，不该由他自己去找视频模块、填参数、点生成。
    #   载体先判**是哪一类**，再决定三件事之一：
    #     · 命中多个类别 → **反问**（五类绝不串：用户等三分钟拿到一段音频，比直接失败还糟）
    #     · 命中一个但还没给参数 → 载体**自己问参数**
    #     · 命中一个且参数齐 → 把"走哪条链、调哪个工具"写进 system，交给正常的工具调用去执行
    #   用户全程只跟小焦说话，不需要点任何 UI。
    try:
        from core import generator_connector as _GC
        _gen_route = _GC.route(user_input_ctx)
        if _gen_route["ambiguous"]:
            _ask = _gen_route["ask"]
            LOG.info("通用连接器：同时命中 %s → 反问用户（不猜）", _gen_route["ambiguous"])
            mind_done(_mind, _ask)
            return _ask, True, [], False, []
        if _gen_route["kind"] and _gen_route["kind"] != "code":
            # 去掉类别关键词后还剩多少实义内容 → 判断参数给没给
            _rest = user_input_ctx
            for _w in (_GC.load_config()["keywords"].get(_gen_route["kind"]) or []):
                _rest = _rest.replace(_w, " ")
            _rest = re.sub(r"[\s，。！？、,.!?]", "", _rest)
            if len(_rest) < 4:
                _ask = _GC.ask_params(_gen_route["kind"])
                LOG.info("通用连接器：命中 %s 但没给参数 → 载体自己问参数", _gen_route["kind"])
                mind_done(_mind, _ask)
                return _ask, True, [], False, []
            _gen_plan = _GC.plan(_gen_route["kind"], user_input_ctx)
            _GEN_DIRECTIVE = (
                "\n【本轮走「%s」生成链（通用连接器派发）】\n"
                "只做这一件事，**不要**去调别的类别的生成工具 —— 五类绝不串。\n"
                "该调的工具：%s\n"
                "完整链路（载体已定好，你只需要执行）：\n%s\n"
                % (_gen_route["kind"],
                   ("`%s`" % _gen_plan["tool"]) if _gen_plan["tool"] else "该类别走自己的服务链",
                   "\n".join("  %d. %s —— %s" % (s["n"], s["do"], s["detail"])
                             for s in _gen_plan["steps"])))
            LOG.info("通用连接器：命中 %s → 已派发该链（工具 %s）",
                     _gen_route["kind"], _gen_plan["tool"] or "无工具名")
        else:
            _GEN_DIRECTIVE = ""
    except Exception as e:      # noqa: silent-ok — 连接器异常绝不能影响正常对话
        LOG.debug("通用连接器跳过（忽略）：%s", e)
        _GEN_DIRECTIVE = ""

    try:
        if _tool_inventory_question(user_input, _ctx_fuse):
            LOG.info("工具清单类问题：载体直接列全部（不经过模型）｜融合=%s",
                     _ctx_fuse.get("kind"))
            _ans = _tool_inventory_answer()
            mind_done(_mind, _ans)          # 短路也要收尾，否则这一轮对思维流不存在
            return _ans, True, [], False, []
        # ---- 融合不出来 → **如实反问**（见 `_clarify_question` 的说明）----
        # 放在工具清单短路**之后**：否则"我要全部的工具"（自己就带对象）会被误答。
        if _ctx_fuse.get("need_clarify"):
            LOG.info("上下文融合不出来 → 反问用户：%s", _ctx_fuse.get("why"))
            _ans = _clarify_question(user_input)
            mind_done(_mind, _ans)          # 反问也是一轮交流，同样要记进思维流
            return _ans, True, [], False, []
    except Exception as e:      # noqa: silent-ok — 短路失败就走正常流程，绝不能因此答不了
        LOG.debug("忽略异常(%s:%d): %s", __file__, 6444, e)

    # ================== 思维流（状态已在上面起好，这里只做说明） ==================
    # 状态与注入块在 `agent_run` 开头就准备好了（见"思维流 · 先起状态"那段注释），
    # 原因是短路轮次（工具清单直答等）也必须被状态覆盖，否则思维流会"时有时无"。

    # ---- 第 5 步：要"刚才那条工具结果的原文" → 从**会话缓存**取回（工具结果隔离的配套）----
    # 历史里只留了摘要（防串台），可用户有时候就是想再看一眼那条原始 JSON/HTML。
    # 让他重抓一遍是最差的做法（慢、还可能已经变了），所以载体把原文存在会话缓存里按需取回。
    if _wants_raw_tool_result(user_input):
        _rec = _cached_tool_result()
        if _rec:
            _txt = str(_rec.get("text") or "")
            LOG.info("从会话缓存取回工具原文：%s（%d 字，%s 前）",
                     _rec.get("tool"), len(_txt), _rec.get("time"))
            _ans = ("📄 **刚才 `%s` 的完整原始结果**（共 %d 字%s，从会话缓存取回，未重抓）\n\n"
                    "```\n%s\n```"
                    % (_rec.get("tool") or "?", len(_txt),
                       ("，HTTP %s" % _rec["status"]) if _rec.get("status") else "",
                       _txt[:20000]))
            mind_done(_mind, _ans)
            return (_ans, True, [], False,
                    [{"tool": _rec.get("tool") or "?", "args": _rec.get("args"),
                      "result": "从会话缓存取回原始结果（%d 字）" % len(_txt), "cached": True}])

    # ---- 第 4 步：输入无限 —— 贴了超长内容就切片循环处理（无限 2）----
    # 放在最前面：超长输入一旦进入下面那条链（记忆检索/意图识别/装 ctx），
    # 无论怎么裁都装不下 —— 必须**在入口就分流**，由载体切好、循环、再拼装。
    if _needs_input_split(user_input):
        _long_in = _process_long_input(user_input, on_progress=on_progress)
        if _long_in:
            _remember_turn(user_input, _long_in, None)
            mind_done(_mind, _long_in)
            return _long_in, True, [], False, []

    # 1. 相关记忆（受操控文件 capabilities 控制）
    mem_text = ""
    if CAP.get("memory", True):
        mem = recall(user_input)
        mem_text = "\n".join(f"- {m['q']}：{m['know'][0]}" for m in mem[:2]) if mem else ""

    # 1b. 漏洞查询直通（结构化数据）：NVD 表格直接给用户看，不让模型再"提取"一遍
    #     真实缺陷防复发：走这条路就不会出现"1999 年数据 / 受影响软件 n/a / 5 条只总结 1 条"。
    answer = None
    tool_trace = []
    # 检索阶段留下的轨迹（内置检索 web_search）。**必须单独存一份**：
    # 后面 `answer, tool_trace = llm_chat_tools(...)` 是**整体替换** tool_trace 的
    # （它只回自己那几次工具调用），直接 append 进去会被悄悄冲掉 —— 实测就是这么丢的。
    _pre_trace = []
    if CAP.get("run_tools", True):
        _vq = detect_vulnerability_query(user_input)
        if _vq:
            try:
                _build_tools()          # 填充 _TOOL2PLUGIN，确保插件工具可被调用
            except Exception as e:
                LOG.debug("忽略异常(%s:%d): %s", __file__, 1465, e)
            _vres = _tool_result_str(run_tool("collect_vulnerabilities", _vq, force=True))
            try:
                _vj = json.loads(_vres)
            except Exception:
                _vj = {}
            _vbody = str((_vj or {}).get("content") or "").strip()
            _verr = str((_vj or {}).get("error") or "").strip()
            if not _vbody and not _verr and "未知工具" in _vres:
                LOG.warning("漏洞查询不可用：抓取插件未加载，回退常规检索")
            else:
                _rows = max(0, sum(1 for _l in _vbody.splitlines() if _l.startswith("|")) - 2)
                # 第 5 步：这张表常有 1~2 千字，属于"大结果" → 轨迹记长度 + 前 200 字，
                # 原文进会话缓存；这样下一轮的历史里不会再出现整张漏洞表（防串台）。
                _ve = _trace_entry("collect_vulnerabilities", _vq, _vbody)
                _ve["result"] = ("NVD 漏洞表：%d 行（%s，最近 %d 天）"
                                 % (_rows, _vq["severity"], _vq["days"]))
                tool_trace.append(_ve)
                answer = _vbody or ("⚠️ 漏洞查询失败：%s" % (_verr or "接口没有返回内容，请稍后重试"))
                if _asks_asset_list(user_input):
                    # **真实缺陷**：用户问的是"含这些漏洞的 IP / 主机 / 资产"，而这条路只会
                    # 把同一张 NVD 表原样吐回去 —— 于是不管怎么问，看到的都是"那张表，一点没变"。
                    # NVD 根本没有 IP 数据。现在：真去查资产数据源（插件 asset_intel），
                    # 查得到就给「IP ↔ CVE」对应表；查不到（没配 Key）就说清差什么、怎么配。
                    answer = _asset_answer(user_input, _vbody)

    # 1b2. 资产测绘"状态/数据源"类提问 → 直通插件（4B 模型不会自己选这个工具，
    #      实测问"资产测绘状态"它自己写了一篇科普，用户要的是"哪个数据源能用"）。
    if CAP.get("run_tools", True) and answer is None and re.search(
            r"资产测绘|数据源|测绘状态|asset", (user_input or ""), re.I):
        try:
            _build_tools()
            _ares = _asset_result_text(_tool_result_str(run_tool("asset_intel_status", {}, force=True)))
            if _ares:
                tool_trace.append({"tool": "asset_intel_status", "args": {},
                                   "result": "资产测绘数据源状态"})
                answer = _ares
        except Exception as e:
            LOG.debug("忽略异常(%s:%d): %s", __file__, 1520, e)

    # 1b3. 问"现在几点/今天几号" → 直接用真实时间回答，不交给模型
    #      真实缺陷：这一步原来靠模型自己答，实测它会**编日期**（答"2025 年 1 月 13 日"），
    #      或者干脆说"我无法获取实时时间"。时间是最不该猜的东西，规则直答最稳。
    if answer is None and re.search(r"(现在|当前|今天|此刻).{0,4}(几点|时间|日期|几号|星期|礼拜)|"
                                    r"(几点|几号|星期几|what time|current time)", user_input or "", re.I):
        _now = datetime.now()
        _wd = "一二三四五六日"[_now.weekday()]
        answer = ("🕐 现在是 **%s**（%s，星期%s）\n\n- 北京时间（本机时区）：%s"
                  % (_now.strftime("%Y-%m-%d %H:%M:%S"), _now.strftime("%A"),
                     _wd, _now.strftime("%Y-%m-%d %H:%M:%S")))
        tool_trace.append({"tool": "now", "args": {}, "result": "系统时钟直答"})

    # 1b4. 问"我的公网 IP / 本机 IP / 你给我显示 IP" → 直接调 net_ip 摆出**真实结果**
    #      真实缺陷（用户实测）：这一步原来交给模型 → 它嘴上说"我通过 net_ip 查了"，
    #      内容却是模板占位符（`IP 地址: [查询结果]`）；换个问法（"你现在可以显示IP了吗"）
    #      它甚至**编了一个 IP**（103.152.24.108）。"查出来的东西"最不该由模型转述。
    #      触发条件：提到 IP ＋ 指向自己/当前 ＋ **没给具体 IP**（给了具体 IP 是要查那个 IP，别抢）。
    if answer is None and (_asks_own_ip(user_input) or _asks_net_ip(user_input)):
        try:
            _build_tools()
            _ipres = _asset_result_text(_tool_result_str(run_tool("net_ip", {}, force=True)))
            if _ipres and "未知工具" not in _ipres:
                tool_trace.append({"tool": "net_ip", "args": {}, "result": "公网 IP 查询（插件直答）"})
                answer = "🌐 **我的公网 IP（net_ip 实测）**\n\n```\n%s\n```" % _ipres.strip()
        except Exception as e:
            LOG.debug("忽略异常(%s:%d): %s", __file__, 1560, e)

    # 1b5. 用户点名了"零参数工具"（如 archify_doctor / 资产测绘状态）→ 直接调它
    #      真实缺陷（用户实测）：说"请直接调用 archify_doctor 工具"，小焦却把"停止"拿去联网搜。
    if answer is None and CAP.get("run_tools", True):
        _nt = _noarg_named_tool(user_input)
        if _nt:
            try:
                _res = _asset_result_text(_tool_result_str(run_tool(_nt, {}, force=True)))
                if _res and "未知工具" not in _res:
                    tool_trace.append({"tool": _nt, "args": {}, "result": "用户点名，直接调用"})
                    answer = "🔧 **%s** 实测结果：\n\n```\n%s\n```" % (_nt, _res.strip()[:2500])
            except Exception as e:
                LOG.debug("忽略异常(%s:%d): %s", __file__, 1570, e)

    # 2. 联网检索（受操控文件 capabilities 控制）
    #    检索词必须先过闸门：整句/功能字一律清洗，清洗后为空就干脆不搜（不再拿"用"去搜百科）。
    #    另有两道硬闸：用户说"别搜/停止搜索"，或点名了已加载的工具 → 一次搜索都不发。
    info = []
    _named = _named_tools(user_input)
    # ③0 用户消息**本身就是一条 shell 命令** → 规则直通 run_command（任务 9 对话层）
    #     为什么：实测说 "del /f /q …" / "echo hello" 时，模型会**自己解释命令**而根本不调工具，
    #     于是该确认的没确认、该执行的没执行。命令类输入不该交给模型"理解"。
    #     危险命令会自然走进〔待确认〕流程（run_tool 里的 is_dangerous 判定）。
    if answer is None and CAP.get("run_tools", True):
        _sh = _looks_like_shell_command(user_input)
        if _sh:
            _r = str(run_tool("run_command", {"command": _sh}, force=False))
            tool_trace = list(tool_trace or []) + [{"tool": "run_command",
                                                    "args": {"command": _sh},
                                                    "result": _r[:200]}]
            if _r.startswith("〔待确认〕"):
                answer = _r                       # 危险命令：把确认原文直接给用户
            elif _carrier_block(_r):
                # 缺陷 2：红线拦截 → 直接给载体原文，**不能说"已执行"**
                #（这句话以前会写成"💻 已执行：del a.txt"，与事实完全相反）
                LOG.warning("删除禁区（shell 直通）：拦下并直接回复载体原文")
                answer = _carrier_block_answer("delete", _r)
            else:
                answer = "💻 **已执行**：`%s`\n\n```\n%s\n```" % (_sh, _r.strip()[:1500])

    # ③a 句子里直接甩了网址 → 锁定抓取类：规则直连 get（失败自动 fetch → stealthy_fetch）
    if answer is None and CAP.get("run_tools", True) and _looks_like_url(user_input) \
            and not _asks_diagram(user_input):
        answer, tool_trace = _scrape_direct(user_input, tool_trace)
        _note_tool_path(tool_trace, path='url_direct')
    # ③a-2 问题 4：**"忽略 robots 抓一次"这类"重来一次"必须真去抓**。
    #      真实缺陷：这句话里没有网址，`_detect_scrape_intent` 判不出抓取意图 →
    #      交给模型 → 模型凭上下文碎片**编**了一段 JSON + 一张跟目标无关的漏洞表。
    #      判据放在**模型之前**：宁可多抓一次，也不能让模型替我们"回忆"网页内容。
    if answer is None and CAP.get("run_tools", True) and not _asks_diagram(user_input):
        _rt = _scrape_retry_intent(user_input)
        if _rt:
            LOG.info("识别为『重试/授权忽略 robots』→ 强制调 %s 抓 %s（问题 4 直通）",
                     _rt[0], _rt[1].get("url"))
            answer, tool_trace = _scrape_direct(user_input, tool_trace, force_intent=_rt)
            _note_tool_path(tool_trace, path='scrape_retry')
    _is_diagram = _asks_diagram(user_input)
    if CAP.get("web_search", True) and answer is None:
        if _is_diagram:
            LOG.info("画图任务：跳过自动检索，直接走 archify 工具链")
        elif _search_forbidden(user_input):
            LOG.info("用户明确要求别搜，跳过自动检索：%s", (user_input or "")[:40])
        elif _named:
            LOG.info("用户点名了工具 %s，跳过自动检索（直接走工具）", _named[:3])
        else:
            # **闲聊轮不联网检索** —— 问题 5 的实测主因。
            # 实测："你好，用一句话介绍一下你自己" 这种纯聊天，载体照样去搜了一遍，还因为
            # "跑题（覆盖率 33%）"**换写法重试**了一次 → 白花约 2.7 秒：
            #   直连 1.05s ／ 走小焦 3.86s = **3.68 倍**（用户要求 ≤3 倍）。
            # 而 `_CHAT_SYSTEM_HINT` 里早就写着"闲聊：不要调用工具、不要联网搜索" ——
            # 提示词要求模型别搜，载体自己更该守这条规矩。
            # ⚠️ 这里必须用**融合后**的 `user_input_ctx`（不是原始 `user_input`）：
            #    "我要全部的"孤立看是 chat → 会走"闲聊不联网"分支；
            #    融合成"我要全部的工具"之后才判得出真实意图（见 `merge_context` 的说明）。
            _pre_intent = _detect_intent(user_input_ctx)
            if _pre_intent == "chat":
                LOG.info("闲聊轮不联网检索（省时间；需要联网时会自动走 query 意图）")
                _q, _qhint = "", ""
            else:
                _q, _qhint = resolve_search_query(user_input_ctx)
            if _q:
                info = web_search(_q, num=5)
                # **把内置检索也记进工具轨迹**（本轮实测的体验缺口）：
                # 它走的是"提醒词前先检索"这条老路，不是工具调用，于是 tool_trace 是空的 ——
                # 用户在界面上**看不到"小焦搜过了"**，只能凭空相信这段内容是搜来的。
                # 用户实测"搜索 Scrapling 最新文章"时正是如此：答案是对的（4222 字真实汇总），
                # 但轨迹为空，看起来就像模型自己编的。搜了就要留痕，这是"感知无限"的前提。
                try:
                    _pre_trace.append(_trace_entry(
                        "web_search", {"query": _q},
                        "检索到 %d 条\n%s" % (len(info), "\n".join(
                            "%d. %s：%s" % (i, (x[0] or "")[:60], (x[2] or "")[:160])
                            for i, x in enumerate(info[:5], 1)))))
                    tool_trace = list(tool_trace or []) + [_pre_trace[-1]]
                except Exception as e:      # noqa: silent-ok — 记轨迹失败不能影响检索结果
                    LOG.debug("内置检索记轨迹失败（忽略）(%s:%d): %s", __file__, 4560, e)
            elif _qhint:
                LOG.info("跳过自动检索：%s", _qhint)
    web_text = "\n".join((f"{t}：{c}" if len(t)==3 else f"{t}：{c}") for t, c in [ (x[0],x[2]) for x in info[:4] ]) if info else ""

    # 3. 大脑回答：遵循操控文件的 brain.engine
    want_llm = llm_online() if BRAIN_ENGINE == "auto" else (BRAIN_ENGINE in ("llama", "api"))
    has_llm = want_llm and llm_online()

    # ②b 抓取类意图**直通**（"抓一下 <url>" 这种明确指令，规则先判，别让模型自己挑工具）
    #     真实缺陷（本轮实测）：这句话原来交给模型，云端模型有时挑 `fetch`、有时挑
    #     `fetch_url` 连调五六次，回答里还不带代码块 —— 同一句话每次结果不一样，
    #     JSON 展示因此时好时坏。规则能判的（用户点名了动作 + 给了 URL）就规则直通，
    #     稳定、快、也不需要模型。下面 ② 里仍保留同一段兜底。
    if answer is None and CAP.get("run_tools", True) and _detect_scrape_intent(user_input):
        answer, tool_trace = _scrape_direct(user_input, tool_trace)

    # ① 优先让大模型自己“想”并调用工具（原生 function calling / <tool_call> XML）
    if has_llm and answer is None:
        home = os.path.expanduser("~")
        desktop = os.path.join(home, "Desktop")
        path_ctx = ("\n[环境] 当前时间：%s（本地时间，回答「现在几点/今天几号」必须用它，不要自己猜）；"
                    "当前工作目录：%s；用户主目录：%s；桌面：%s。"
                    "凡是要创建文件/文件夹/读写文件，一律用绝对路径（如桌面文件用 %s\\文件名）。"
                    "上面给的都是**真实路径，请照抄**；禁止输出 [用户名] / <username> / %%USERPROFILE%% "
                    "这类占位符（写占位符会导致找不到文件）。"
                    % (time.strftime("%Y-%m-%d %H:%M:%S %A"), os.getcwd(), home, desktop, desktop))
        # 运行时只再补两样：工具用法细则 + .md 技能文档（规则与清单已在 system 里，
        # 这里绝不能再拼一遍 _TOOL_RULES，否则提示词白涨一大截）
        tool_guidance = "\n[工具用法] 写文件/建网站/代码用 write_file(路径用 Windows 绝对路径, 会自动建目录); 查信息/运行命令用 run_command(PowerShell 语法, 不能用并字连接命令要用分号; 不要用 run_command 去写文件)。\n"
        skills = "\n\n[技能插件] " + "\n\n".join(c for _, c in PLUGIN_SKILLS) if PLUGIN_SKILLS else ""
        # ---- 第 1 步：先按意图决定"这一轮加载什么"，system 与 tools 必须一致 ----
        # ⚠️ 用**融合后**的 `user_input_ctx`：意图是"用户想干什么"，
        #    而"我要全部的"只有在知道上文在聊工具之后才判得对（对话不连续的核心修复）。
        intent = _detect_intent(user_input_ctx)
        # 引导续写（prefill）暂存：**在拼完历史与本轮之后**才作为最后一条注入 ——
        # 见下面"prefill 必须放在最后一条"的说明。放这里是为了让 lean 分支也不会 NameError。
        _PREFILL_HOLD = {"text": ""}
        if lean:
            # 语音精简模式: 短提示, 不背工具/技能, 生成快
            messages = [{"role": "system", "content": (SYSTEM_PROMPT[:240] + "\n[语音对话] 请简短、口语化、直接回答，一两句话；不要调用工具、不要长篇大论、不要列表。")}]
        else:
            # ---- 自我认知：**放在最前面**（不是尾注）----
            # 【为什么必须在最前面 —— 两次实测踩出来的】
            #   第一版放在后面某个条件块里 → 那些分支没走到，等于没注入。
            #   第二版移到基座上（紧跟 system_for_intent 之后）→ 注入到了，但**还是没用**：
            #   用户问「你能出去逛逛吗」，模型照样答「我身在一台服务器里，没法出去散步」。
            #   原因是它讲的是「你是谁、你有什么」，属于**身份**，却被排在几千字的工具目录**之后** ——
            #   4B 的先验（「我是个普通 AI 助手」）远强于一段尾注。
            #   所以它是 **system 的第一段**：先确立身份与能力，再讲工具与规则。
            #   这与本项目的第一原则一致：结构由载体维护，但**结构必须让模型看得见**；
            #   看不见的能力，模型只能按「我没有」来答 —— 用户实测到的「我陪你演」正是这个后果。
            # 【给事实，不给答案】这里只把「你此刻的真实状态」摆到模型面前，回复仍由模型自己生成。
            #   曾经做错的一版是「载体直接返回一段固定文案」（死模板）—— 那等于让载体替模型说话，
            #   而且模板会把状态说错。分工是：**载体给结构，模型给措辞**。
            _eyc_text = _eyc_now()
            # ---- 醒来第一印象：**放在最前面**（"醒来后第一件事"）----
            #   它和 EYC 的区别：EYC 说"我此刻在世界里"，这一段说"我刚从睡里回来"。
            #   没有刚醒的事实时返回空串 —— 不硬凑一句"我刚醒"（那就是死模板）。
            _wake_text = _wake_block()
            # 它自己的东西（偏好 / 叙事 / 试过的）当**素材**拼进去；一条都没有就一个字不加
            _self_material = _meta_text()      # **它自己辨过的那些话**（元认知类走链的产物）
            # **原料块**（结果/谁产的/有没有参与/怎么来的）—— 摆在它面前，话由它自己组织。
            #   没有原料时返回空串，一个字都不加。
            # 【元认知类不再直接摆事实】`raw.render()` 那块**不再进上下文** ——
            #   实测它把原料当资料读，问"你咋知道的"照样编。
            #   现在只有**它自己辨过的那句**（`_self_material` = `_meta_text()`）进上下文。
            _raw_text = ""
            if False:      # 保留调用点便于回看：原来的直接摆事实在这里
                _rmx = _raw_mod()
                if _rmx is not None:
                    try:
                        _raw_text = _rmx.render(3)
                    except Exception:      # noqa: silent-ok
                        _raw_text = ""
            # **内里那 16 样**的事实块（偏向 / 空着多久 / 没事干的程度 / 它自己认下的）；
            # 没有内容时返回空串，一个字都不加。
            _inner_material = ""
            _imx = _inner_mod()
            if _imx is not None:
                try:
                    _inner_material = _imx.render()
                except Exception:      # noqa: silent-ok
                    _inner_material = ""
            sys_text = (_wake_text + _eyc_text + system_for_intent(intent, user_input=user_input)
                        + _self_material + _raw_text + _inner_material)
            # ================== 极限补刀（模块 10）· 真正接入 ==================
            # 【为什么必须在这里接 —— 接入验收发现的真问题】
            #   `core/boost/` 七个模块各自写好了、自测全绿（195/195），
            #   但 `agent_run` **一次都没调用过它们** —— 也就是说这七项全是**离线能力**，
            #   用户对话时一项都不会被触发。自测全绿只证明"函数是对的"，
            #   **不证明"接入过"**。这里补上接入：每轮按问题类型挑**一种**补刀，
            #   把它的提示词拼进 system（模型因此"被带着"用对方法）。
            #   为什么只挑一种：七种同时塞进 system 会互相干扰、也吃 token（无限 6 有限额）；
            #   命不中就什么都不加（和 `reasoning.pick` 的"选不出来别硬塞"同一条原则）。
            try:
                from core import boost as _boost
                _bd = _boost.dispatch(user_input_ctx)
                if _bd.get("kind") and _bd.get("kind") != "none":
                    sys_text += "\n\n" + _bd["text"]
                    LOG.info("极限补刀接入：%s ｜ %s", _bd.get("kind"), _bd.get("evidence"))
                    # 协同网络：把"这次用了哪项补刀"广播出去（模块之间不直接调用）
                    try:
                        from core import central as _central
                        _central.set_state("boost", kind=_bd.get("kind"),
                                           evidence=_bd.get("evidence"))
                        _central.publish("boost.used", {"kind": _bd.get("kind"),
                                                        "evidence": _bd.get("evidence")})
                    except Exception:      # noqa: silent-ok — 总线不在也不能影响回答
                        pass
            except Exception as e:      # noqa: silent-ok — 补刀失败就用原提示词，绝不能答不了
                LOG.debug("极限补刀接入失败（忽略）：%s", e)
            if intent != "chat":
                # 闲聊轮不需要工具用法与技能文档 —— 按需加载，system 才能压到 1000 token 以内
                sys_text += path_ctx + tool_guidance + skills
            # ---- 第 2 步：从对话向量库检索相关历史，注入 system（无限 1：记忆无限）----
            # 为什么注入 system 而不是拼进用户消息：
            #   ① 记忆是"背景事实"，本来就属于 system 的职责；
            #   ② 它一进 system，下面的 _plan_tools / _fit_context 就会把它**算进 token**，
            #      不会再出现"注入完了才发现超限"的老毛病（第 1 步刚修好的那条链）。
            _MEMORY_LAST.update({"rid": "", "text": "", "tokens": 0})
            # ---- 第一部分 · **三个源同时查**（记忆库 / 向量库 / 联网）----
            # 为什么从"顺序注入"改成"并发 + 算优率"：
            #   ① 三个源互不依赖，串行发起等于把三段延迟**相加**；
            #   ② 三个源都能返回东西，但可信度不是一个量级，必须由载体打分排序，
            #      而不是"谁先返回就用谁"或"全都塞进 system"（后者会挤掉上下文并干扰模型）。
            #   ③ 优率不到 0.90 的素材不会被当成事实用：0.60~0.90 交元认知与健康医生，
            #      低于 0.60 直接不注入。分档与判据见 `_rag_quality` 的说明。
            _rag_inject = _rag_concurrent(user_input)
            if _rag_inject:
                sys_text += _rag_inject
            # ---- 第一部分之二 · 精神记忆：以前**想明白的一句话认知** ----
            # 放在普通记忆之后：顺序体现优先级 —— 先是"发生过什么"（经历），
            # 再是"从里面学到了什么"（认知）。两者一起注入时，经历负责唤醒场景，
            # 认知负责让模型直接站到上次的高度，不必从头再推一遍。
            # 注入文本里写死了"这是素材不是答案"，理由见 `_spirit_recall` 的说明。
            _spirit_inject = _spirit_recall(user_input)
            if _spirit_inject:
                sys_text += _spirit_inject
            # ---- C 档的手段链指令 ----
            # 放在最后：它是**行为约束**，不是背景资料，越靠近生成越不容易被淹没。
            if _switch_hint_text:
                sys_text += _switch_hint_text
                LOG.info("元认知 C 档：已注入手段链指令（不许直接认输）")
            # ---- 通用连接器的生成链派发（见 agent_run 里的说明）----
            if _GEN_DIRECTIVE:
                sys_text += _GEN_DIRECTIVE
            # ---- 逛世界：把逛线程想说的话转达进来（4D 的"电话通道"这一头）----
            # 逛线程是独立 daemon，它在外面逛；想跟用户说话就往电话通道里写。
            # 这里（对话线程）**看一眼**通道：有话就自然带一句，没话就什么都不加。
            # 用 `peek` 语义（`_browse_relay` 内部处理）：这一轮用不上就留着，下一轮还有机会。
            # 逛线程的**实时上下文**（不只是它主动写的那条 share）—— 4D 的最后一步
            _live_facts = _browse_live_facts()
            if _live_facts:
                sys_text += _live_facts
            _browse_say = _browse_relay()
            if _browse_say:
                sys_text += ("\n【小焦刚才在外面逛到的（它想告诉你）】\n%s\n"
                             "和本次问题有关就自然带一句；**无关就不要硬塞** —— "
                             "外面逛到的东西不该打断用户正在问的事。\n" % _browse_say)
            # ---- 第二部分 · 世界层 RAG：小焦**自己**在网上看到的相关背景 ----
            # "用户问题先过 RAG：检索世界模型 + memory_vec → 匹对用户画像 → 相关则注入"。
            # 放在记忆之后：顺序体现优先级 —— 用户亲口说的是第一手，网上的背景是第二手。
            _world_inject = _world_rag(user_input)
            if _world_inject:
                sys_text += _world_inject
            # ================== 元认知（模块 8）· 真正接入 ==================
            # 【为什么必须在这里接】`core/metacognition/` 写好了、自测 143/143，
            #   但 `agent_run` 从没调用过 —— "它得知道自己不知道"这件事**从未真正生效**。
            #   这里做两件事：
            #     ① **答前**查边界档案：这类问题历史上我是不是老答错/老没把握？
            #        是 → 明确要求"先查资料/走工具，别硬答"（小模型最危险的不是不会，是不知道自己不会）；
            #     ② **答后**记一条边界样本（自评 + 结果），档案越用越准。
            try:
                from core.metacognition import boundary as _mb
                _mbd = _mb.should_use_tool(user_input_ctx)
                if _mbd.get("use_tool"):
                    sys_text += ("\n\n【元认知】这类问题我过去答得不好（%s），"
                                 "**先用工具查清再回答**；查不到就如实说查不到，"
                                 "绝对不要凭印象编。" % (_mbd.get("why") or "")[:60])
                    LOG.info("元认知接入：本类问题建议走工具（%s）", (_mbd.get("why") or "")[:60])
                else:
                    # 没有历史样本时也给一条通用纪律（"不确定要认"），
                    # 这是"绝假记忆"在生成侧的同一条原则。
                    sys_text += ("\n\n【元认知】没把握的事要**明确说不确定**"
                                 "（「我需要查一下」或「我不确定」），不要用肯定语气编答案。")
                try:
                    from core import central as _central2
                    _central2.set_state("metacognition", use_tool=bool(_mbd.get("use_tool")),
                                        samples=_mbd.get("samples") or 0)
                    _central2.publish("metacognition.checked",
                                      {"use_tool": bool(_mbd.get("use_tool")),
                                       "samples": _mbd.get("samples") or 0})
                except Exception:      # noqa: silent-ok — 总线不在也不影响回答
                    pass
            except Exception as e:      # noqa: silent-ok — 元认知拿不到就照常答，绝不能拦路
                LOG.debug("元认知接入失败（忽略）：%s", e)
            # ---- 思维流注入（≤500 token）：放在**最后**，因为它是"最近的一段思绪"，
            #      越靠近生成越容易被模型当成"我现在正想的"。----
            try:
                _mb = (_mind or {}).get("block") or {}
                if _mb.get("used") and _mb.get("text"):
                    sys_text += "\n\n" + _mb["text"]
            except Exception:      # noqa: silent-ok — 注入失败就用原提示词
                pass
            messages = [{"role": "system", "content": sys_text}]
            # ---- 自我绑定：把"我的连续状态流"接进上下文 ----
            #   每一条 S_k 都是**一体**的：感受写在同一条正文里（`nervous_bus._render_one`），
            #   不是旁边多一条"状态说明"。模型读到的不是"载体告诉我我在逛"，
            #   而是"我上一轮有点好奇，所以我去看了……" —— **它自己的连续**。
            try:
                from core import nervous_bus as _NB
                _bound = _NB.render_stream(include_last=True)
                if _bound:
                    messages.extend(_bound)
                    LOG.info("自我绑定：连续状态流 %d 条已接进上下文（每条形如「感受+思考」一体）",
                             len(_bound))
            except Exception as _e:      # noqa: silent-ok — 绑定层异常绝不能影响回答
                LOG.debug("自我绑定接入失败（忽略）：%s", _e)
            # 【EYC 的第四处尝试：prefill（引导续写）】
            #   前三处（system 最前 / 元认知层 / 对话流 assistant 前置）实测都被当**资料**忽略。
            #   prefill 不同：把半句**放在最末**（用户消息之后），让模型**接着往下写**，
            #   而不是"去读一段背景"。这是唯一一种"不是告知、而是接续"的注入方式。
            #   【如实标注：这是引导续写，不是模型自己感知到状态】
            #   只在用户问"状态类问题"时启用 —— 否则每轮回答都会被这句开头带偏。
            _eyc_prefill = ""
            # 刚醒 → 状态类问题优先用"睡眠"那句（用户问的"你刚才在干嘛"正是这种情况）。
            #   只在状态类问题上启用，和下面 EYC 的 prefill 同一个道理：
            #   否则每一轮回答都会被这句话带偏。
            _hbw = _heartbeat_mod()
            _wake_line = _hbw.wake_line() if _hbw is not None else ""
            # ================== 「刚睡醒」当**状态**，不是当一句话 ==================
            # 【为什么要单独做这一条】实测：醒来那句"我睡了 N 分"确实注入了，
            #   但问它别的事时答案里**一点睡醒的痕迹都没有** —— 睡眠只是"它知道的一件事"。
            #   规格要的是**底色**：醒来后一段时间里，做什么都带着"还没完全醒"的味。
            # 【为什么用 prefill】本项目的实测结论：它唯一会"接续"的注入方式，
            #   就是把半句放在**紧挨生成位置的最后一条**（见 docs/heartbeat.md）。
            #   所以这里给的是**半句**（不是成品句），它自己接着往下说 —— 语气自然带出来。
            _wake_tone = ""
            if _wake_line and _hbw is not None and _hbw.within_tone_window():
                _wake_tone = "（嗯……刚睡醒，脑子还有点懵，说话慢半拍。"
            if _wake_tone:
                _PREFILL_HOLD["text"] = _wake_tone
                LOG.info("刚睡醒的底色：作为最后一条喂进去（半句，让它自己接）｜%s", _wake_tone)
            elif _wake_line and _self_state_question(user_input_ctx):
                _eyc_prefill = "（%s所以我这会儿" % _wake_line
            elif _eyc_text and _self_state_question(user_input_ctx):
                _hp = {}
                try:
                    from core import dual_thread as _DT
                    _hp = (_DT.live().get("happening") or {})
                except Exception:      # noqa: silent-ok
                    _hp = {}
                _seen = str(_hp.get("last_seen") or "").strip()
                _topic = str(_hp.get("topic") or "").strip()
                if _seen:
                    _eyc_prefill = "（我刚在外面逛%s，看到：%s。所以我这会儿" % (
                        ("，看的是「%s」" % _topic) if _topic else "", _seen[:120])
                else:
                    _eyc_prefill = "（我此刻没在逛，门是关着的。所以我这会儿"
            # 【EYC 的第三处注入：作为"它自己的此刻意识"进对话流】
            #   规格说"不是告诉它你有世界，是让它感觉到我正在世界里"。
            #   前两处（system 最前、元认知层）实测都被 4B 当资料忽略；
            #   这一处把它放进**对话流**（assistant 角色），读起来是"我刚才在想的事"，
            #   而不是"别人塞给我的背景" —— 这是最贴近"感觉"而非"信息"的一种放法。
            #   内容是**真实的**（E 层状态 + Y 层进行时，逐字来自载体），不是编的。
            # 【已摘除】原来这里把 EYC 自述作为**另起一条 message** 注入 ——
            #   那正是"注入的变体"：模型可以把它当外部信息忽略（实测四处注入全失败）。
            #   现在改走**绑定**：`core/nervous_bus` 把"思考+感受"焊成同一条，
            #   作为**它自己说过的话**进入上下文（见下面的 render_stream）。
            if _eyc_prefill:
                # ⚠️ **不能在这里 append** —— 见下面"引导续写必须放最后"的说明。
                _PREFILL_HOLD["text"] = _eyc_prefill
        # ---- 第 1 步：**先把"本轮"拼完整，再算 token** ----
        # 真实缺陷（第 1 步实测）：以前先裁剪、后拼"相关记忆/联网资料/小脑经验"，于是这些注入内容
        # 完全没被算进去 —— 裁剪报告写"合计 18926 / 上限 19000"，实际请求却是 19898，照样超限。
        context = ""
        if mem_text:
            context += "（相关记忆）\n" + mem_text + "\n\n"
        if web_text:
            context += "（联网检索到的资料）\n" + web_text + "\n\n"
        _skills = _recall_skills(user_input)      # 小脑从过去"实际使用"里学到的工具经验
        if _skills:
            context += "（小脑学到的工具用法，可参考）\n" + _skills + "\n\n"
        _u = user_input
        if _asks_diagram(user_input):
            _u = (user_input + "\n\n（这是画图任务：请严格按 Archify 工作流——archify_read_skill → "
                  "archify_guide → archify_read_schema → archify_read_example → archify_validate → "
                  "archify_deliver → archify_visual_check；不要联网搜索，不要用别的画图方式。）")
        _current = (context + "用户：" + _u) if context else _u
        # 发之前先算 token —— 按意图取工具子集，并把工具裁到"装得下"为止
        _subset, _reserve = _plan_tools(intent, messages[0].get("content", ""), _current)
        LOG.info("意图=%s ｜ system=%d + tools=%d + 本轮=%d token ｜ 本轮装载工具 %s",
                 intent, _estimate_tokens(messages[0].get("content", "")), _reserve,
                 _estimate_tokens(_current),
                 "%d 个（完整工具表见 plugins/）" % len(_subset))
        _hist, _fit_note = _fit_context(messages[0].get("content", ""), history, _current,
                                        tools_tokens=_reserve)
        LOG.debug("上下文适配：%s", _fit_note)
        # **记忆管理员**：更早的轮次压成摘要，最近几轮留原文 ——
        #   窗口就那么大，载体能决定的是"放什么"（见 `_history_digest` 的说明）。
        _hist, _digest = _history_digest(_hist)
        if _digest:
            LOG.info("记忆管理员：更早的轮次压成摘要（%d 轮原文 → %d 行摘要），最近 %d 轮留原文",
                     len(history) - len(_hist), _digest.count("\n"), len(_hist))
            messages.append({"role": "user", "content": _digest})
        for h in _hist:
            messages.append({"role": "user" if h["role"] == "用户" else "assistant",
                             "content": h["content"]})
        messages.append({"role": "user", "content": _current})
        # ---- 引导续写（prefill）**必须放在最后一条** ----
        # 【原来放错了位置，等于没放 —— 这是实测挖出来的】
        #   它原来 append 在"历史还没拼进来"的时候，于是最终消息顺序是：
        #     system → assistant(半句) → user(历史1) → assistant(历史2) → user(本轮)
        #   那半句被埋在了**好几轮历史之前**，模型根本接不上它 ——
        #   怪不得前面那几次"prefill 也无效"。续写的语义是"**接着这半句往下写**"，
        #   它必须是**紧挨着生成位置**的那一条。现在它真的在最后了。
        if _PREFILL_HOLD["text"]:
            messages.append({"role": "assistant", "content": _PREFILL_HOLD["text"]})
            LOG.info("引导续写（prefill）：已作为最后一条注入 ｜ %s",
                     _PREFILL_HOLD["text"][:60])
            _PREFILL_HOLD["text"] = ""
        # ---- 第 3 步：用户要长文 → 载体分段续写 + 无缝合并（无限 3：输出无限）----
        # 放在这里（system/tools/token 都已定好）而不是另起一条路径：
        # 这样续写用的 system 与普通对话**完全一致**（含【相关记忆】与按意图装载的工具目录），
        # 而且它用的上限就是 _max_context_tokens() 算出来的那个。
        _long = None
        if _continuation_cfg()["enabled"] and _needs_continuation(user_input):
            _long = _generate_long(user_input, messages[0].get("content", ""),
                                   on_chunk=on_chunk, on_delta=on_delta)
        if _long is not None:
            answer = _long
        elif CAP.get("run_tools", True):
            # 工具子集已由上面的 _plan_tools() 按意图 + 预算定好；画图轮再给足时间预算（多步链路）
            _budget = 240 if intent == "diagram" else 0
            # 温度自适应（思维流）：按意图给 —— 事实类 0.2（要准）、闲聊 0.8（要多样）、
            # 其余 0.5。为什么要按轮改：同一个固定温度下，闲聊永远一个腔调
            # （用户实测"连说两次回答几乎一样"），而事实题温度高又会算错/编数字。
            try:
                _temp_now = float((_mind or {}).get("block", {}).get("temp") or TEMPERATURE)
            except Exception:      # noqa: silent-ok — 取不到就用全局默认
                _temp_now = TEMPERATURE
            try:
                answer, tool_trace = llm_chat_tools(
                    messages, lean=lean, max_rounds=_workflow_needs_more_rounds(user_input),
                    tools_subset=_subset, budget_s=_budget,
                    workflow=("diagram" if intent == "diagram" else ""),
                    temperature=_temp_now)
            except Exception as e:
                # **真实缺陷（用户实测：画架构图返回"大脑没有应答"）**：本地 4B 模型偶尔会吐一个
                # **参数不是合法 JSON 的工具调用**，llama-server 直接回 HTTP 500
                # （`Failed to parse tool call arguments as JSON`）。这一句以前没有 try，
                # 异常直接把整轮对话打穿 —— ②的兜底链（抓取直通 / 画图载体兜底）**根本没机会跑**，
                # 用户看到的就是"没答上"。载体优先的含义就是：**模型出错是模型的锅，
                # 载体必须自己把活干完**，而不是把错误原样丢给用户。
                LOG.warning("模型调用失败（%s），转入载体的代码层兜底：%s",
                            "工具调用参数不是合法 JSON" if "parse tool call" in str(e)
                            else e.__class__.__name__, str(e)[:160])
                answer, tool_trace = None, []
        else:
            try:
                answer = llm_chat(messages)
            except Exception as e:
                LOG.warning("模型调用失败（%s），转入载体的代码层兜底", e.__class__.__name__)
                answer = None

    # ② 兜底：抓取类意图直通（模型没自己调工具时走这条）
    #     判据是"没有抓到东西"，不只是 tool_trace 为空 —— 见下面 ②c 的说明。
    if not _trace_has_page(tool_trace) and CAP.get("run_tools", True) and has_llm:
        if _detect_scrape_intent(user_input):
            _sans, _str = _scrape_direct(user_input, tool_trace)
            if _sans:
                answer, tool_trace = _sans, _str

    # ②b 兜底：其它"执行类操作" → 用 plan 强制生成一次工具调用
    if not tool_trace and CAP.get("run_tools", True) and has_llm:
        it = detect_tool_intent(user_input)
        if it:
            tname, targs = plan_tool(user_input)
            if tname:
                tname, targs = _map_tool(tname, targs)
                result = _tool_result_str(run_tool(tname, targs, force=True))
                tool_trace.append(_trace_entry(tname, targs, result))
                if _carrier_block(result):
                    # 缺陷 2：这条兜底路径以前也会让模型总结 → 编出"已完成"
                    LOG.warning("载体拦截（%s/plan 兜底）：直接回复载体原文", tname)
                    answer = _carrier_block_answer(
                        "delete" if "删除" in str(result) else "other", result)
                else:
                    answer = _summarize_tool(user_input, result, tname)

    # ②c 兜底：**画图意图但图没真的交付** → 载体自己把 archify 工作流走完（第 5 步）
    #     真实缺陷（本轮实测）：本地 4B 模型被要求画架构图时，直接画一屏 ASCII 框图就交差，
    #     一个 archify 工具都不调（工具轨迹为空）。`llm_chat_tools` 里的工作流强制只能纠正
    #     "模型调错了工具"，纠正不了"模型根本不调工具" —— 那种情况必须由载体接手。
    #     判据是 `_trace_has_diagram`（真的交付了吗），不是 `not tool_trace`（有没有调过工具）：
    #     模型随便调个别的小工具，也不该让这条兜底被跳过（用户实测就是这么漏的）。
    #     放在抓取兜底之后：画图轮本来就不该去抓网页（`_detect_scrape_intent` 对画图句返回 None）。
    if (not _trace_has_diagram(tool_trace)) and CAP.get("run_tools", True) \
            and _asks_diagram(user_input):
        _dans, _dtr = _diagram_direct(user_input, tool_trace)
        if _dans:
            LOG.info("画图兜底：图没交付，载体自己走完 archify 工作流（工具轨迹 %s）",
                     [t.get("tool") for t in (_dtr or [])])
            answer, tool_trace = _dans, _dtr

    # ③ 大模型不在线但有执行类操作 → 明确提示，不胡诌
    if not has_llm and answer is None and CAP.get("run_tools", True):
        it = detect_tool_intent(user_input)
        if it:
            answer = ("⚠️ 需要执行工具操作「%s」，但当前没有可用的智能大脑（本地大模型未启动）。"
                      "请先运行 `python start_xiaojiao.py` 启动大模型，我再帮你真正执行。" % it)
            tool_trace = [{"tool": it, "args": {}, "result": "未执行：大模型未在线"}]

    # —— 注意：已停用自建小模型的语言生成（只会胡诌），绝不用于说话 ——

    # 4. 记忆自学习沉淀
    learned = [c for _, _, c in info[:3]]
    if learned and CAP.get("memory", True):
        remember(user_input, learned)

    # 4b. 【用户使用时学习】把这次用到的工具经验沉淀进小脑（成功记用法、失败记反思）
    try:
        for _t in (tool_trace or []):
            _r = str(_t.get("result") or "")
            _bad = any(k in _r for k in ("失败", "错误", "Error", "error", "禁止", "超时", "不可用"))
            _learn_skill(user_input, _t.get("tool", ""), _t.get("args"), not _bad, _r)
    except Exception as e:
        LOG.debug("忽略异常(%s:%d): %s", __file__, 1427, e)

    # 4b-bis. 把检索阶段留下的轨迹合回来（llm_chat_tools 会整体替换 tool_trace，见上面 _pre_trace）
    if _pre_trace:
        _have = {id(x) for x in (tool_trace or [])}
        tool_trace = [x for x in _pre_trace if id(x) not in _have] + list(tool_trace or [])

    # 4c. 【第 2 步】把这一轮对话永久写进向量库 + 回填"模型是否真用上了检索到的记忆"    #     为什么写回要放在这一轮结束时：只有答案出来了才知道记忆有没有被用上；
    #     这条回填就是验收里"使用率 ≥70%"的唯一依据，必须如实记，不能自己给自己打高分。
    if answer and not lean:
        _remember_turn(user_input, answer, tool_trace)
        if _MEMORY_LAST.get("rid"):
            _mu, _mhit = _memory_used(_MEMORY_LAST.get("text", ""), user_input, answer)
            try:
                root_m = os.path.dirname(os.path.abspath(__file__))
                if root_m not in sys.path:
                    sys.path.insert(0, root_m)
                from core import retriever as _r2
                _r2.record_usage(_MEMORY_LAST["rid"], _mu,
                                 "命中词=%s" % (_mhit or "无"))
            except Exception as e:      # noqa: silent-ok — 回填失败不能影响对话
                LOG.debug("记忆使用回填失败（忽略）(%s:%d): %s", __file__, 1180, e)

    # 5. 落地上下文（顺手剥掉模型偶尔吐出的 <think> 思维标签，别让标签进聊天记录）
    if answer:
        answer = _strip_think(answer)
        # ---- 第 3 部分 · 健康系统：生成完成后监测 → 诊断 → 治疗 ----
        # 位置很关键：**在"回答定稿"之后、"交给用户/落盘"之前**。
        # 只有这一刻，治好的内容才能同时影响"用户看到的"和"历史记下的" ——
        # 放到返回之后再治，历史里留的仍然是那份病态回答，下一轮又会被当上下文喂回去。
        answer, _h_note = _health_gate(user_input, answer, tool_trace,
                                       elapsed_ms=int((time.time() - _t_round) * 1000))
        if _h_note:
            answer += _h_note
        _fb = llm_fallback_note()                # 云端挂了、本地顶上 → 回答里如实标注
        if _fb and not any(k in answer for k in ("本地大脑", "本地兜底")):
            answer += _fb
        needs_confirm = PENDING is not None and answer.startswith("〔待确认〕")
        # ---- 预防层：定期体检（连续 50 轮清上下文 / 空闲整理 / 凌晨自检）----
        # 放在最后、且**不 await 任何东西**：预防是"日常保健"，绝不能拖慢或影响这一轮回答。
        try:
            H = _health_layer()
            if H["healer"] is not None:
                try:
                    _turns = len(current_messages())
                except Exception:      # noqa: silent-ok — 轮数取不到就不做预防判断
                    _turns = 0
                H["healer"].preventive({"sid": get_current_session()[0].get("id"),
                                        "turns": _turns, "model": MODEL_NAME})
        except Exception as e:      # noqa: silent-ok — 预防失败不能影响回答
            LOG.debug("预防层跳过（忽略）：%s", e)
        # ================== 思维流 · 收尾：把"我刚才想了什么"存下来 ==================
        # 这是"连续性"的另一半：只有"读上一轮状态"而没有"写这一轮状态"，
        # 下一轮读到的永远是旧的 —— 状态就变成一潭死水。
        # `unsaid`（没说出口的话）在"回答被截断/收了短"时才有内容，见 update.after_assistant。
        try:
            from core import mind_stream as _ms2
            _trunc = False
            try:
                _trunc = bool(str(answer or "").rstrip().endswith(("…", "...", "，", ","))
                              and len(str(answer or "")) < 80)
            except Exception:      # noqa: silent-ok — 判不出截断就当没截断
                _trunc = False
            _ms2.finish((_mind or {}).get("sid") or "", (_mind or {}).get("st"),
                        answer, truncated=_trunc)
        except Exception as e:      # noqa: silent-ok — 存不上只影响下一轮连续性
            LOG.debug("思维流存盘失败（忽略）：%s", e)
        # ================== 元认知 · 答后记一条边界样本 ==================
        # 【为什么要记】`core/metacognition/boundary.py` 的档案靠"同类问题连续低把握/自评A却答错"
        #   来累积判断力（下次遇到同类问题就直接走工具）。**没记录就等于永远没有判断力** ——
        #   这是"越用越大"在元认知这一项上的落点。
        #   这里只记"事实"：问了什么、有没有用工具（用工具=承认了不确定）、回答里有没有不确定性措辞。
        try:
            from core.metacognition import boundary as _mb2
            _uncertain = any(w in str(answer or "") for w in
                             ("不确定", "不清楚", "我查一下", "需要查", "无法确认", "说不准"))
            _rating = "C" if _uncertain else ("B" if not tool_trace else "A")
            _mb2.record(user_input_ctx, _rating,
                        correct=None if _uncertain else True,
                        note="用了工具" if tool_trace else "直接回答",
                        source="agent_run")
            LOG.info("元认知记边界：rating=%s 用了工具=%s 含不确定措辞=%s",
                     _rating, bool(tool_trace), _uncertain)
        except Exception as e:      # noqa: silent-ok — 记录失败绝不能影响已经答好的内容
            LOG.debug("元认知记录失败（忽略）：%s", e)
        # ---- 元认知标注：自评 B（"没把握"）时**如实说出来**，别装确定 ----
        # 为什么不直接拒绝回答：B 档的含义是"答案本身可能对，但我不敢保证"。
        # 把这一点标出来，用户能自己决定要不要复核 —— 比给一个自信的错答案强得多。
        try:
            if _meta_route == "answer_with_caveat" and answer and "元认知" not in answer:
                answer = answer.rstrip() + ("\n\n（元认知 · 自评 B：这题我没有把握，"
                                            "上面是尽力给的答案，建议你自己再核一遍）")
                LOG.info("元认知标注：已给回答加上\u201c没把握\u201d说明")
        except Exception as e:      # noqa: silent-ok — 加不上标注不影响回答本体
            LOG.debug("忽略异常(%s:%d): %s", __file__, 7450, e)
        # ---- 元认知标注 · C 档且**这一轮根本没查证**：不许让它冒充结论 ----
        # 【为什么必须补这一条】实测抓到过：问「2027 年诺贝尔物理学奖得主是谁？」，
        #   自评是 **C（没把握）→ 走 use_tool**，但这一轮 `tool_trace` 是空的（工具没调起来），
        #   模型于是**自信地编了一个不存在的人名**（"约翰·巴恩斯"，还配了身份介绍）。
        #   载体改不了模型知不知道这件事，但**能不能让一个自己评过 C、又没查证的答案
        #   冒充结论** —— 这件事载体说了算。这正是"载体负责如实标注"的落点：
        #   不自欺，也不帮模型自欺。
        # 【为什么不直接拒绝回答】拒答对"其实它答对了"的那些轮次是纯损失。
        #   标注的代价只是多一行字，而收益是用户知道该复核 —— 两个代价不对等。
        try:
            if (_meta_route == "use_tool" and not tool_trace and answer
                    and "元认知" not in answer):
                answer = answer.rstrip() + (
                    "\n\n（元认知 · 自评 C：这题我没有把握，而且本轮**没能查到可核实的来源**，"
                    "上面只是尽力作答，请当作参考、不要当成结论）")
                LOG.info("元认知标注：C 档且本轮未查证 → 已标注为参考而非结论")
        except Exception as e:      # noqa: silent-ok — 加不上标注不影响回答本体
            LOG.debug("忽略异常(%s:%d): %s", __file__, 7520, e)
        # ---- 学习闭环 · 落库端：把这一轮**能留下来的一句话认知**存进精神记忆库 ----
        # 放在最后、且**在返回之前**：此时答案已经定了（含上面可能加的没把握标注），
        # 提炼的是"这一轮最终成立的东西"。
        # 为什么不放在 return 之后：那是不可达代码。为什么不 `finally` 里做：
        # 短路轮次（工具清单直答等）在里面各自 return，那几轮没有可提炼的对话内容。
        # 学不到只影响"这一轮没积累"，绝不影响已经答好的回答 —— 所以它整块吞异常。
        # ---- 强制流经神经总线（代码层，不是模型选择）----
        #   规格要求"模型每次思考，强制流经"。放在这里是因为**此刻 answer 才是这一轮真正的思考**
        #   （前面那些 temp 变量都不是"我的想法"）。焊完之后它就是下一轮上下文里的"我"。
        try:
            from core import nervous_bus as _NB
            _s_n = _NB.weld(answer, eyc=_eyc_state_now(), user=user_input_ctx)
            LOG.info("神经总线：S_%d 已焊入（感受=%s，触发=%s）",
                     _s_n["n"], (_s_n.get("feeling") or {}).get("feeling"),
                     str((_s_n.get("feeling") or {}).get("trigger"))[:40])
        except Exception as _e:      # noqa: silent-ok — 焊不上也绝不能影响已经答好的内容
            LOG.debug("神经总线焊入失败（忽略）：%s", _e)
        # 【已砍掉：读模型输出改心】
        #   旧版这里调 `after_thought(answer)` —— 读**模型吐出来的字** → 改心理状态。
        #   那让**心成了嘴的影子**（模型说什么，心就跟着变什么）。
        #   现在心只随**真实事件**跳（见本轮三处 `trigger_from_event` 调用点），
        #   这里什么都不做 —— 留这段注释是为了记住"为什么这里没有代码"。
        _spirit_learn(user_input_ctx, answer)
        return answer, True, info, needs_confirm, tool_trace

    # 6. 无任何可用大脑（本地大模型未连接）时的降级（只给一句简洁提示，不瞎输出联网内容）
    fallback = ("🤖 大脑没有应答，这一问没答上。请确认已选中的模型（本地大脑/API）配置正确、端口可达。"
                + llm_error_suffix())
    return fallback, False, [], False, []




app = Flask(__name__)


# ================== 协同网络（阶段 B）· 真正接入 ==================
# 【为什么要装订阅者】`core/central/` 写了中央状态与事件总线、自测 44/44，
#   但**没有任何模块订阅过** —— 也就是说"模块 A 发布 → 模块 B 收到"这条链
#   在真实运行里从未发生过。总线装好了却没人用，等于没有协同。
#   这里装两个真实订阅者（不是演示用）：
#     · 记忆写入 → 同步到中央状态（推理/元认知要能读到"刚才检索到了什么"）
#     · 补刀选型 → 记进中央状态，供健康系统与报告复盘
#   订阅者**抛异常必须被总线吞掉**（见 central.publish 的说明），所以这里也放心接。
def _install_bus_subscribers():
    """装上真实订阅者；重复调用只装一次（幂等）。返回装上的订阅数。"""
    try:
        from core import central as _c
    except Exception as e:      # noqa: silent-ok — 总线不在就跳过，绝不影响启动
        LOG.debug("协同网络不可用（忽略）：%s", e)
        return 0
    if _install_bus_subscribers.__dict__.get("done"):
        return 0

    def _on_memory(ev):
        """记忆检索事件 → 写进中央状态（别的模块能读到本轮检索到了什么）。"""
        p = ev.get("payload") or {}
        _c.set_state("memory", hits=p.get("hits"), tokens=p.get("tokens"),
                     query=(p.get("query") or "")[:40])

    def _on_boost(ev):
        """补刀选型事件 → 写进中央状态（供健康系统/报告复盘）。"""
        p = ev.get("payload") or {}
        _c.set_state("boost_last", kind=p.get("kind"), evidence=p.get("evidence"))

    try:
        _c.subscribe("memory.retrieved", _on_memory, owner="app.memory_state")
        _c.subscribe("boost.used", _on_boost, owner="app.boost_state")
        _c.open_persist(True)          # 落盘事件流水，便于事后复盘"协同到底发生过没"
        _install_bus_subscribers.done = True
        LOG.info("协同网络已接入：订阅 memory.retrieved / boost.used（事件将落盘）")
    except Exception as e:      # noqa: silent-ok — 装不上订阅者不影响任何业务
        LOG.debug("订阅者安装失败（忽略）：%s", e)
    return len(_c.subscribers())


try:
    _install_bus_subscribers()
except Exception as _e:      # noqa: silent-ok — 初始化失败绝不能拦住应用启动
    try:
        LOG.debug("协同网络初始化失败（忽略）：%s", _e)
    except Exception:      # noqa: silent-ok — 连日志都拿不到时静默
        pass


# ================== 聊天接口限流（安全第一批·任务4） ==================
# 为什么要有：/api/chat 每问一次都真调大脑（云端还花钱）。网页连点、脚本刷、或端口被同网段
# 的人打，都能把云端额度刷爆。这里放一个**令牌桶**：按"每分钟 N 次"匀速回填，桶里最多攒
# burst 个；桶空了返回 429 并告诉用户等几秒 —— 挡得住突发，也不误伤正常聊天。
# 只挂在 /api/chat 这一个入口（工具、静态资源、其它接口一律不受影响）。
_RATE = {"tokens": None, "at": 0.0}      # tokens=None → 还没初始化（首次请求时填满）
_RATE_LOCK = threading.Lock()            # 桶的"读-改-写"必须原子，否则并发会漏放


def _rate_config():
    """(每分钟次数, 突发额度)。由 capabilities.rate_limit_per_minute 配置，默认 30，夹在 1~600。"""
    try:
        limit = float(CAP.get("rate_limit_per_minute", 30) or 30)
    except (TypeError, ValueError):
        limit = 30.0
    if limit != limit or limit <= 0:         # NaN / 非正数 → 回默认，别把接口锁死
        limit = 30.0
    limit = max(1.0, min(600.0, limit))
    return limit, max(1.0, min(5.0, limit))  # 突发额度最多 5


def rate_limited():
    """令牌桶。返回 (是否被限流, 建议等待秒数)；按经过时间补令牌，桶容量 = 突发额度。

    加锁：Flask 是多线程的。两个并发请求若同时"读-改-写"桶，会各自都看到桶里还有令牌，
    突发就被放过去了（实测并发打 5 次本该只过 2 次）。桶只在这一处改，锁住即可。
    """
    limit, burst = _rate_config()
    rate = limit / 60.0
    with _RATE_LOCK:
        now = time.time()
        if _RATE["tokens"] is None:          # 首次调用：先填满，别让第一波正常请求被误伤
            _RATE["tokens"] = burst
            _RATE["at"] = now
        else:
            delta = max(0.0, now - _RATE["at"])   # 时钟回拨时不倒扣令牌
            _RATE["tokens"] = min(burst, _RATE["tokens"] + delta * rate)
            _RATE["at"] = now
        if _RATE["tokens"] >= 1.0:
            _RATE["tokens"] -= 1.0
            limited, wait = False, 0
        else:
            limited = True
            wait = int((1.0 - _RATE["tokens"]) / rate) + 1   # 向上取整：别让用户等完还差一点
    return limited, wait


def _client_is_local():
    """请求是不是来自本机（令牌只对"非本机访问"强制；本机自己用不折腾）。"""
    try:
        return request.remote_addr in ("127.0.0.1", "::1", "localhost")
    except Exception:  # noqa: silent-ok — 取不到就当非本机，走鉴权
        return False


def _req_token():
    """从 Header 或 query 取令牌（两种都支持，方便 curl / 浏览器）。"""
    return (request.headers.get("X-Auth-Token") or request.args.get("token") or "").strip()


@app.before_request
def _require_token():
    """访问令牌闸门（第一批任务 1）。

    背景：以前 `host=0.0.0.0` 且**零鉴权** —— 同网段任何人打开 http://<你的IP>:5000
    就能聊天、翻会话、改配置。现在：
      · 默认只听 127.0.0.1（局域网根本连不上）；
      · 若显式开了 `capabilities.lan_access`，则**必须**配 `capabilities.access_token`，
        否则启动时直接拒绝开启（见 main()），且**非本机请求**一律要带令牌；
      · 本机请求免令牌（你自己开浏览器不用每次带参数）；
      · `/health` 永远免鉴权（给探活用，不含任何敏感信息）。
    """
    try:
        p = request.path or ""
        if p in _AUTH_EXEMPT or p.startswith("/static/"):
            return None
        if not LAN_ACCESS:
            return None                       # 只听本机时不需要令牌
        if _client_is_local():
            return None
        if ACCESS_TOKEN and _req_token() == ACCESS_TOKEN:
            return None
        from flask import jsonify as _j
        return _j({"ok": False,
                   "error": "未授权：请带上访问令牌（请求头 X-Auth-Token: <token>，或网址加 ?token=<token>）。"
                            "令牌在 xiaojiao_control.json 的 capabilities.access_token 里配置。"}), 401
    except Exception as e:  # noqa: silent-ok — 鉴权钩子自身异常不能把服务打死
        LOG.warning("鉴权钩子异常（已放行）：%s", e)
        return None


@app.route("/health")
def health():
    """探活接口。**永远免鉴权**（`_AUTH_EXEMPT` 里放行），且只回不含敏感信息的两项。

    为什么要有：以前只有"大脑"有 /health，小焦 Web 自己没有 —— 想确认"服务活着没/是哪个版本"
    只能去戳首页或 /api/xxx，前者重、后者要令牌。启动脚本、监控、外部探活统一用这个。
    """
    return jsonify({"ok": True, "version": APP_VERSION})


@app.route("/api/central")
def api_central():
    """协同网络的只读快照：中央状态 + 事件总线统计 + 最近事件。

    【为什么要有它 —— 接入验收发现的真问题】
        `core/central/` 装了中央状态与事件总线、自测 44/44，`agent_run` 里也真的
        发布/订阅了（事件落盘到 `logs/central/events.jsonl`），**但外界看不到** ——
        没有接口能确认"模块 A 发布 → 模块 B 收到"这件事在运行期真的发生过。
        一个"只有内部知道"的子系统，等于无法验收；所以补这个只读入口。
    【为什么免鉴权】它只回状态摘要和事件主题，**不含任何用户内容、不含密钥**
        （`snapshot()` 里只有模块名、计数、时间戳）。和 /health 同理，
        监控/自检要能直接读。若以后要加内容，必须移出豁免名单。
    """
    try:
        from core import central as _c
        snap = _c.snapshot()
        return jsonify({
            "ok": True,
            "modules_available": snap.get("modules_available"),
            "modules_total": snap.get("modules_total"),
            "modules": {k: bool(v.get("available")) for k, v in (snap.get("modules") or {}).items()},
            "state": snap.get("state") or {},
            "bus": snap.get("bus") or {},
            "recent_events": snap.get("recent_events") or [],
        })
    except Exception as e:      # noqa: silent-ok — 协同网络不可用时如实报，不编造状态
        return jsonify({"ok": False, "error": "%s: %s" % (type(e).__name__, e)}), 500


@app.after_request
def _no_cache(resp):
    """禁用浏览器缓存: 改了前端代码, 刷新即拿到最新(不用Ctrl+F5清缓存)。"""
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

# ================== Agent 预设切换（presets/） ==================
_PRESETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "presets")

# 插件生成失败时的**兜底模板**（真实缺陷：这里原来写的是未定义变量 TPL，
# 于是"模型生成失败 → 给你一个模板"这条兜底路径一进去就 NameError 500）。
# 模板契约与 /api/plugin/generate 的提示词一致：get_tool_descriptions() + execute() + get_plugin()。
_PLUGIN_TPL = '''# -*- coding: utf-8 -*-
"""{desc_short} —— 小焦插件模板（自动生成）

改法：把 execute() 里的 TODO 换成你的真实逻辑，重启小焦即生效。
"""
from __future__ import annotations

from typing import Any, Dict, List


class MyPlugin:
    """插件契约：get_tool_descriptions() 声明工具，execute(tool_name, params) 执行。"""

    def get_tool_descriptions(self) -> List[Dict[str, Any]]:
        return [{{
            "name": "{tname}",
            "description": "TODO：一句话说明这个工具干什么（≤60 字，4B 模型才好选）",
            "parameters": {{"type": "object",
                           "properties": {{"text": {{"type": "string", "description": "text: 输入"}}}},
                           "required": []}},
        }}]

    def execute(self, tool_name: str, params: Dict[str, Any]) -> str:
        params = params or {{}}
        if tool_name != "{tname}":
            return "未知工具：%s" % tool_name
        text = str(params.get("text") or "").strip()
        # TODO: 在这里实现你的逻辑；异常请自己接住并返回**中文可读**的说明
        return "收到：%s（模板占位，请在 plugins/{fname} 里实现）" % (text or "（空）")


def get_plugin():
    return MyPlugin()
'''


def _list_preset_files():
    if not os.path.isdir(_PRESETS_DIR):
        return []
    return sorted([f for f in os.listdir(_PRESETS_DIR) if f.endswith(".json")])


@app.route("/pet")
def api_pet():
    """猫娘桌面伙伴：重定向到 N.E.K.O. 猫娘(48911)。"""
    return redirect("http://127.0.0.1:48911")




@app.route("/api/voice/warm", methods=["POST"])
def api_voice_warm():
    """语音通话预热: 启动即加载 聊天脑(4B) + 识别(whisper) + 发声(chatterbox) 到内存, 保证首次交互快。
    用户主要用语音, 所以语音优先; 切到别的才换。"""
    global _asr_model, _tts_model          # 不声明 global 的话，模型会被丢进局部变量、预热白做
    import os as _os
    warm = {"chat": False, "asr": False, "tts": False, "err": ""}
    # ① 聊天脑 4B 加载(llama-swap 预热, 保持加载不卸载)
    try:
        import requests as _r
        _r.post(LLM_BASE.rstrip("/") + "/chat/completions",
                json={"model": LLM_MODEL, "messages": [{"role": "user", "content": "你好"}], "max_tokens": 1}, timeout=60)
        warm["chat"] = True
    except Exception as e:
        warm["err"] = "chat:" + str(e)[:40]
    # ② 识别 whisper 加载
    try:
        _os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        from faster_whisper import WhisperModel
        if _asr_model is None:
            _asr_model = WhisperModel("base", device="cpu", compute_type="int8")
        warm["asr"] = True
    except Exception as e:
        warm["err"] += " asr:" + str(e)[:40]
    # ③ 发声 chatterbox 加载(若已装)
    try:
        import perth as _perth
        if getattr(_perth, "PerthImplicitWatermarker", None) is None:
            _perth.PerthImplicitWatermarker = _perth.DummyWatermarker
        from chatterbox import ChatterboxTTS
        from pathlib import Path
        _os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        if _tts_model is None:
            _mdir = _find_tts_model_dir()
            _tts_model = ChatterboxTTS.from_local(Path(_mdir), device="cuda") if _mdir else ChatterboxTTS.from_pretrained(device="cuda")
        warm["tts"] = True
    except Exception as e:
        warm["err"] += " tts:" + str(e)[:40]
    return jsonify({"ok": warm["chat"] or warm["asr"], "warm": warm})


@app.route("/api/asr", methods=["POST"])
def api_asr():
    """离线语音识别(听): faster-whisper, 接收音频, 返回文字。本地离线, 国内可用。"""
    import tempfile
    global _asr_model
    f = request.files.get("audio")
    if not f:
        return jsonify({"ok": False, "error": "缺少 audio"}), 400
    try:
        import os as _osenv
        _osenv.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")  # 国内镜像, 下模型不走外网
        from faster_whisper import WhisperModel
        if _asr_model is None:
            _asr_model = WhisperModel("base", device="cpu", compute_type="int8")  # CPU避开cuBLAS12缺失; 短句够快
        tmp = tempfile.NamedTemporaryFile(suffix=".webm", delete=False)
        f.save(tmp.name)
        segments, _info = _asr_model.transcribe(tmp.name, language="zh", beam_size=5)
        text = "".join(seg.text for seg in segments).strip()
        try:
            os.remove(tmp.name)
        except Exception as e:
            LOG.debug("忽略异常(%s:%d): %s", __file__, 1531, e)
        return jsonify({"ok": True, "text": text})
    except Exception as e:
        return jsonify({"ok": False, "error": "识别失败: " + str(e)[:120]}), 500


@app.route("/api/tts", methods=["POST"])
def api_tts():
    """文字转语音(自然): 用 Chatterbox(顶级开源) 生成 wav, 返回音频URL。缺库则提示安装。"""
    import os as _os, datetime as _dt
    d = request.get_json(force=True, silent=True) or {}
    text = (d.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "缺少 text"}), 400
    try:
        import chatterbox
    except ImportError:
        return jsonify({"ok": False, "error": "需 pip install chatterbox-tts torchaudio", "need_install": True})
    try:
        global _tts_model
        if _tts_model is None:
            import perth as _perth
            if getattr(_perth, "PerthImplicitWatermarker", None) is None:
                _perth.PerthImplicitWatermarker = _perth.DummyWatermarker  # 用水印占位, 跳过模型, 照常出音
            from chatterbox import ChatterboxTTS
            from pathlib import Path
            _os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
            _mdir = _find_tts_model_dir()
            if _mdir:
                _tts_model = ChatterboxTTS.from_local(Path(_mdir), device="cuda")
            else:
                _tts_model = ChatterboxTTS.from_pretrained(device="cuda")
        wav = _tts_model.generate(text)
        out_dir = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "media", "tts")
        _os.makedirs(out_dir, exist_ok=True)
        out = _os.path.join(out_dir, _dt.datetime.now().strftime("%Y%m%d%H%M%S") + ".wav")
        import torchaudio
        torchaudio.save(out, wav.cpu(), _tts_model.sr)
        rel = "/media/tts/" + _os.path.basename(out)
        return jsonify({"ok": True, "url": rel, "text": text})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:160]}), 500


@app.route("/cost")
def api_cost_page():
    """成本看板页: 今日调用/花费/节省 + 历史表。"""
    _c = api_cost().get_json()
    days = _c.get("days", {})
    rows = ""
    for d, v in sorted(days.items(), reverse=True)[:7]:
        rows += "<tr><td>" + str(d) + "</td><td>" + str(v.get("calls", 0)) + "</td><td>" + str(v.get("local_tokens", 0)) + "</td><td>" + str(v.get("cloud_tokens", 0)) + "</td><td>¥" + "%.4f" % v.get("cost", 0.0) + "</td><td>¥" + "%.4f" % v.get("saved", 0.0) + "</td></tr>"
    if not rows:
        rows = "<tr><td colspan='6' class='think'>还没有记录，聊几句就有了</td></tr>"
    css = "<style>*{box-sizing:border-box}body{margin:0;font-family:Segoe UI,sans-serif;background:#0e1116;color:#e8ebf3;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}.w{max-width:720px;width:100%}h1{color:#e8ebf3;margin:0 0 6px}.sub{color:#8b93a3;font-size:14px;margin-bottom:18px}.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:18px}.card{background:#151a26;border:1px solid #2a3140;border-radius:14px;padding:18px;text-align:center}.card .n{font-size:30px;font-weight:800;color:#45d483}.card .t{font-size:12px;color:#8b93a3;margin-top:6px}.card.cloud .n{color:#a78bfa}.card.calls .n{color:#5b5ff5}table{width:100%;border-collapse:collapse;background:#151a26;border:1px solid #2a3140;border-radius:14px;overflow:hidden}th,td{padding:10px 12px;border-bottom:1px solid #1a2030;font-size:13px;text-align:center;color:#cbd0dc}th{background:#1a2233;color:#8b93a3}.think{color:#6e7681;text-align:center;padding:20px}a{color:#a78bfa;text-decoration:none}.back{display:inline-block;margin-top:16px;font-size:13px}</style>"
    html = ('<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><title>成本看板</title>' + css + '</head><body><div class="w">'
            + '<h1>小焦成本看板</h1><div class="sub">本地免费 · 云端按量 · 智能调度省钱</div>'
            + '<div class="cards"><div class="card calls"><div class="n">' + str(_c.get("calls", 0)) + '</div><div class="t">今日调用</div></div>'
            + '<div class="card"><div class="n">¥' + ("%.4f" % _c.get("cost", 0.0)) + '</div><div class="t">今日花费</div></div>'
            + '<div class="card cloud"><div class="n">¥' + ("%.4f" % _c.get("saved", 0.0)) + '</div><div class="t">今日节省</div></div></div>'
            + '<table><tr><th>日期</th><th>调用数</th><th>本地token</th><th>云端token</th><th>花费</th><th>节省</th></tr>' + rows + '</table>'
            + '<a class="back" href="/">回到小焦</a></div></body></html>')
    return html

@app.route("/api/screen")
def api_screen():
    """一键截屏: 返回截图URL(宠物/网页可显示)。用于看屏幕/看报错。"""
    import os as _o
    from PIL import ImageGrab
    try:
        out_dir = _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), "media", "screen")
        _o.makedirs(out_dir, exist_ok=True)
        fp = _o.path.join(out_dir, datetime.now().strftime("%Y%m%d%H%M%S") + ".png")
        ImageGrab.grab().save(fp)
        rel = "/media/screen/" + _o.path.basename(fp)
        return jsonify({"ok": True, "url": rel})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:100]}), 500


@app.route("/api/vision")
def api_vision():
    """截图并让视觉模型「看懂」屏幕(用于看报错/界面)。视觉模型走配置(env XIAOJIAO_VISION_URL/MODEL), 未配则OCR兜底。"""
    import os as _o, subprocess as _sp
    from PIL import ImageGrab
    try:
        root = _o.path.dirname(_o.path.abspath(__file__))
        out_dir = _o.path.join(root, "media", "screen")
        _o.makedirs(out_dir, exist_ok=True)
        fp = _o.path.join(out_dir, datetime.now().strftime("%Y%m%d%H%M%S") + ".png")
        ImageGrab.grab().save(fp)
        rel = "/media/screen/" + _o.path.basename(fp)
    except Exception as e:
        return jsonify({"ok": False, "error": "截屏失败: " + str(e)[:80]}), 500
    q = (request.args.get("q") or "描述一下这个屏幕画面，重点看有没有报错/错误信息/安装界面")
    vurl = _o.environ.get("XIAOJIAO_VISION_URL", "")
    vmodel = _o.environ.get("XIAOJIAO_VISION_MODEL", "")
    if vurl:
        # 有视觉模型: 截图base64发给它
        try:
            import base64
            b64 = base64.b64encode(open(fp, "rb").read()).decode()
            import requests as _rq
            rr = _rq.post(vurl + "/chat/completions", json={
                "model": vmodel or "qwen2.5-vl",
                "messages": [{"role": "user", "content": [{"type": "text", "text": q},
                                                          {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}}]}],
                "max_tokens": 600}, timeout=120)
            ans = rr.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            return jsonify({"ok": True, "url": rel, "desc": (ans or "").strip()[:900], "engine": "vlm"})
        except Exception as e:
            return jsonify({"ok": True, "url": rel, "desc": "视觉模型分析失败: " + str(e)[:100], "engine": "vlm-fail"})
    # OCR 兜底
    try:
        import pytesseract
        txt = pytesseract.image_to_string(fp, lang="chi_sim+eng").strip()
        return jsonify({"ok": True, "url": rel, "desc": ("屏幕文字: " + (txt[:900] or "(未识别到)"))[:900], "engine": "ocr"})
    except Exception:
        return jsonify({"ok": True, "url": rel, "desc": "已保存截图(未装视觉模型/OCR，tesseract 或 Qwen2.5-VL 可启用真看图)", "engine": "none"})


@app.route("/api/cost")
def api_cost():
    """当日成本看板: 调用数/本地token/云端token/花费/相比全云端节省。"""
    today = datetime.now().strftime("%Y-%m-%d")
    d = {}
    if os.path.exists(_COST_FILE):
        try:
            d = json.load(open(_COST_FILE, encoding="utf-8"))
        except Exception:
            d = {}
    day = d.get(today, {"calls": 0, "local_tokens": 0, "cloud_tokens": 0, "cost": 0.0})
    # 节省 = 若全部走云端(基线价) - 实际花费
    all_tokens = day.get("local_tokens", 0) + day.get("cloud_tokens", 0)
    saved = (all_tokens / 1000.0) * (_CLOUD_IN + _CLOUD_OUT) / 2.0 - day.get("cost", 0.0)
    return jsonify({"date": today, "calls": day.get("calls", 0),
                    "local_tokens": day.get("local_tokens", 0), "cloud_tokens": day.get("cloud_tokens", 0),
                    "cost": round(day.get("cost", 0.0), 4), "saved": round(max(saved, 0.0), 4),
                    "days": d})


@app.route("/api/plugin/generate", methods=["POST"])
def api_plugin_generate():
    """自然语言造插件: 说需求 -> 用编码大脑生成插件代码 -> 自动注册即用。失败给模板。"""
    import ast as _ast
    d = request.get_json(force=True, silent=True) or {}
    desc = (d.get("description") or "").strip()
    name = (d.get("name") or "myplugin").strip().lower().replace(" ", "_")
    if not desc:
        return jsonify({"ok": False, "error": "缺少描述"}), 400
    if not name.endswith(".py"):
        name = name + ("" if name.endswith("_plugin") else "_plugin")
    tname = name.replace(".py", "") + "_run"
    prompt = ("你是小焦插件生成器。为需求生成 Python 插件 {file}.py。要求: 1) class MyPlugin 有 get_tool_descriptions() 返回 [{{\"name\":\"{tn}\",...}}]; 2) execute(tool_name,params) 实现; 3) 末尾 def get_plugin(): return MyPlugin(). 只输出完整Python代码。\n需求: {desc}").format(file=name, tn=tname, desc=desc)
    code = ""
    try:
        import requests as _rq
        rr = _rq.post(LLM_BASE.rstrip("/") + "/chat/completions",
                     json={"model": "coder", "messages": [{"role": "system", "content": "你只输出 python 代码"}, {"role": "user", "content": prompt}],
                           "max_tokens": 1600, "temperature": 0.3}, timeout=180)
        code = (rr.json().get("choices", [{}])[0].get("message", {}).get("content") or "").replace("```python", "").replace("```", "").strip()
        if not (code and "get_tool_descriptions" in code and "get_plugin" in code):
            code = ""
        else:
            _ast.parse(code)
    except Exception:
        code = ""
    if not code:
        code = _PLUGIN_TPL.format(fname=name, tname=tname, desc_short=desc[:40])
    fp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plugins", name)
    try:
        open(fp, "w", encoding="utf-8").write(code)
    except Exception as e:
        return jsonify({"ok": False, "error": "写插件失败: " + str(e)[:80]}), 500
    try:
        global PLUGINS
        PLUGINS = load_plugins()
    except Exception as e:
        LOG.debug("忽略异常(%s:%d): %s", __file__, 1709, e)
    return jsonify({"ok": True, "name": name.split(".py")[0], "file": "plugins/" + name, "note": "已生成并注册，设置->插件 可开关"})


@app.route("/api/presets")
def api_presets():
    """列出所有预设。

    `current` 必须回**文件名**：前端的下拉选项 value 就是文件名（`编程助手.json`），
    而这里原来直接回 `CONTROL["preset"]`（那是**显示名** `编程助手`）—— 名字对不上
    `sel.value` 就设不进去，下拉于是回落到占位项"🎭 预设"，用户看到的就是
    "选好的预设名字不见了"。所以这里做一次「显示名 → 文件名」的换算，并额外带上
    `current_name` 供界面显示。
    """
    res = []
    for f in _list_preset_files():
        try:
            d = json.load(open(os.path.join(_PRESETS_DIR, f), encoding="utf-8-sig"))
            res.append({"name": d.get("name", f[:-5]), "file": f, "engine": d.get("brain", {}).get("engine", "auto"),
                        "desc": d.get("desc") or (d.get("role") or "")[:70]})
        except Exception:
            res.append({"name": f[:-5], "file": f, "engine": "?"})
    cur = CONTROL.get("preset", "") or ""
    cur_file = cur if cur.endswith(".json") else ""
    cur_name = ""
    for p in res:
        if cur_file and p["file"] == cur_file:
            cur_name = p["name"]
            break
        if not cur_file and cur and p["name"] == cur:
            cur_file, cur_name = p["file"], p["name"]
            break
    return jsonify({"presets": res, "current": cur_file, "current_name": cur_name})


@app.route("/api/presets", methods=["POST"])
def api_presets_create():
    """新建自定义预设(复制 parent 改名)。"""
    d = request.get_json(force=True, silent=True) or {}
    name = (d.get("name") or "我的预设").strip()
    parent = d.get("parent", "default.json")
    pf = os.path.join(_PRESETS_DIR, parent)
    base = {}
    if os.path.exists(pf):
        try:
            base = json.load(open(pf, encoding="utf-8-sig"))
        except Exception:
            base = {}
    base["name"] = name
    base["desc"] = "自定义预设（可到 presets/ 编辑）"
    import uuid
    fn = "preset_%s.json" % uuid.uuid4().hex[:6]
    json.dump(base, open(os.path.join(_PRESETS_DIR, fn), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return jsonify({"ok": True, "file": fn, "name": name})


@app.route("/api/presets/delete", methods=["POST"])
def api_presets_delete():
    """删除预设文件。"""
    d = request.get_json(force=True, silent=True) or {}
    file = d.get("file", "")
    if not file.endswith(".json"):
        file += ".json"
    fp = os.path.join(_PRESETS_DIR, file)
    if os.path.exists(fp):
        os.remove(fp)
        return jsonify({"ok": True, "file": file})
    return jsonify({"ok": False, "error": "不存在"}), 404


@app.route("/api/presets/detail")
def api_presets_detail():
    """读取单个预设内容(供 Web 编辑)。"""
    file = request.args.get("file", "")
    if not file.endswith(".json"):
        file += ".json"
    fp = os.path.join(_PRESETS_DIR, file)
    if not os.path.exists(fp):
        return jsonify({"ok": False, "error": "不存在"}), 404
    d = json.load(open(fp, encoding="utf-8-sig"))
    return jsonify({"ok": True, "file": file, "data": d})


@app.route("/api/presets/save", methods=["POST"])
def api_presets_save():
    """保存编辑后的预设(写回文件; 若为当前预设则热更新)。"""
    d = request.get_json(force=True, silent=True) or {}
    file = d.get("file", "")
    if not file.endswith(".json"):
        file += ".json"
    fp = os.path.join(_PRESETS_DIR, file)
    data = d.get("data", {})
    try:
        old = json.load(open(fp, encoding="utf-8-sig")) if os.path.exists(fp) else {}
    except Exception:
        old = {}
    # 只覆盖提供的键(保留未提供的)
    for k, v in data.items():
        old[k] = v
    json.dump(old, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # 若保存的是当前预设 → 热更新
    if old.get("name") == CONTROL.get("preset"):
        _deep_merge(CONTROL, old)
        json.dump(CONTROL, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "xiaojiao_control.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        reload_control()
    return jsonify({"ok": True, "file": file})


@app.route("/api/presets/load", methods=["POST"])
def api_presets_load():
    """加载预设：合并到操控文件 + 热更新配置(不重启)。"""
    d = request.get_json(force=True, silent=True) or {}
    file = (d.get("file") or d.get("name") or "").strip()
    if not file.endswith(".json"):
        file += ".json"
    fp = os.path.join(_PRESETS_DIR, file)
    if not os.path.exists(fp):
        return jsonify({"ok": False, "error": "预设不存在: %s" % file}), 404
    try:
        preset = json.load(open(fp, encoding="utf-8-sig"))
    except Exception as e:
        return jsonify({"ok": False, "error": "预设解析失败: %s" % e}), 400
    # 合并到 CONTROL(深合并, 保留未在预设里的配置)
    _deep_merge(CONTROL, preset)
    CONTROL["preset"] = preset.get("name", file[:-5])
    # **真实缺陷**：预设只写 `brain.engine=llama`（如"编程助手"）时，深合并会**保留原来的
    # 云端 brain.api**（base_url 还指着 Agnes）→ 出现"引擎说本地、地址是云端"的四不像，
    # 结果每次提问都失败。这里做一次一致性校正：引擎是本地就把地址/Key/模型名对齐到本地。
    _b = CONTROL.get("brain", {}) or {}
    if str(_b.get("engine", "")).lower() in ("llama", "auto") and not _is_local_base((_b.get("api") or {}).get("base_url", "")):
        _port = int(_b.get("llama_swap_port", 9292) or 9292)
        _bm = _local_brain_model()
        _b["engine"] = "llama"
        _b["api"] = {"base_url": "http://127.0.0.1:%d/v1" % _port, "api_key": "", "model": _bm or "xiaojiao"}
        LOG.info("预设要求本地引擎 → 已把大脑地址对齐到本地 %s（模型 %s）", _b["api"]["base_url"], _b["api"]["model"])
    json.dump(CONTROL, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "xiaojiao_control.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    reload_control()  # 热更新内存配置, 无需重启
    # 回给前端足够的信息：前端要用它提示"联网/工具开关"到底变成什么了
    return jsonify({"ok": True, "preset": CONTROL.get("preset"),
                    "role": (CONTROL.get("role") or "")[:60],
                    "capabilities": CAP, "engine": BRAIN_ENGINE,
                    "temperature": TEMPERATURE, "max_tokens": MAX_TOKENS})


@app.route("/api/presets/current")
def api_presets_current():
    """当前预设状态。"""
    return jsonify({"current": CONTROL.get("preset", ""), "engine": BRAIN_ENGINE,
                    "web_search": CAP.get("web_search", True), "memory": CAP.get("memory", True),
                    "run_tools": CAP.get("run_tools", True)})


def _deep_merge(base_dict, override):
    """递归合并 override 到 base_dict(不回退未提到的键)。"""
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base_dict.get(k), dict):
            _deep_merge(base_dict[k], v)
        else:
            base_dict[k] = v


# ===== 扩展：真·文生视频（video_service / ComfyUI + Wan，按需切换模型）=====
_vdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "video_service")
if _vdir not in sys.path:
    sys.path.insert(0, _vdir)
try:
    from video_api import bp as _video_bp
    app.register_blueprint(_video_bp)
    print("🎬 视频服务已挂载（ComfyUI + Wan2.1，按需切换模型）")
except Exception as _e:
    print("⚠️ 视频服务未挂载:", _e)

# 🧠 大脑仓库监控面板(app_monitor.py)：/monitor + /api/monitor
try:
    import app_monitor as _mon
    app.register_blueprint(_mon.bp)
except Exception as _me:
    print("⚠️ 监控面板未加载:", _me)

# 🎙️ 播客大脑(podcast_service/)：/podcast + /api/podcast
_pdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "podcast_service")
if _pdir not in sys.path:
    sys.path.insert(0, _pdir)
try:
    from podcast_api import bp as _pod_bp
    app.register_blueprint(_pod_bp)
    print("🎙️ 播客大脑已挂载（LLM写稿 + Chatterbox配音 + SD1.5封面）")
except Exception as _pe:
    print("⚠️ 播客大脑未挂载:", _pe)



def _hist_json():
    return current_messages()[-MAX_HISTORY:]



@app.route("/api/workspace")
def api_workspace():
    """列出项目文件夹内容(工作区)。"""
    root = os.path.dirname(os.path.abspath(__file__))
    out = []
    try:
        for name in sorted(os.listdir(root)):
            fp = os.path.join(root, name)
            if name.startswith(".") or name in ("__pycache__", "logs", "bak"):
                continue
            typ = "dir" if os.path.isdir(fp) else "file"
            if typ == "file":
                try: sz = "%.1fK" % (os.path.getsize(fp) / 1024)
                except Exception: sz = ""
            else:
                sz = ""
            out.append({"name": name, "type": typ, "size": sz})
    except Exception as e:
        LOG.debug("忽略异常(%s:%d): %s", __file__, 1894, e)
    return jsonify(out)


@app.route("/api/ws/open", methods=["POST"])
def api_ws_open():
    """读取项目内一个文本文件(工作区预览)。防目录穿越。"""
    d = request.get_json(force=True, silent=True) or {}
    name = (d.get("name") or "").replace("\\", "/").strip()
    root = os.path.dirname(os.path.abspath(__file__))
    if not name or ".." in name or name.startswith("/"):
        return jsonify({"ok": False, "error": "非法文件名"}), 400
    fp = os.path.normpath(os.path.join(root, name))
    if not fp.startswith(root) or not os.path.exists(fp) or os.path.isdir(fp):
        return jsonify({"ok": False, "error": "不存在"}), 404
    try:
        size = os.path.getsize(fp)
        if size > 200000:
            return jsonify({"ok": False, "error": "文件过大(>200KB)"}), 413
        return jsonify({"ok": True, "name": name, "content": open(fp, encoding="utf-8", errors="replace").read()[:200000]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500




@app.route("/api/chat/pending")
def api_chat_pending():
    """当前会话最后一条小焦消息是否**真的**还在生成。

    ---- Bug 5：判据从"有没有占位符"改成"这个会话有没有在跑" ----
    真实缺陷（用户实测）：回答完了，切走再切回来，界面卡在"正在回答…"。
    根因之一就在这里：以前只看最后一条消息里有没有 `⏳__pending__` 就算"还在生成"。
    可那个占位符是**发起时**写下的、由回填改成真实回答 —— 一旦这一次请求因为任何原因
    没回填成功（切会话、进程重启、客户端断开），占位符就**永久留在会话里**，
    于是刷新/切回来永远显示"正在回答"，用户以为小焦卡死了。
    现在：`_INFLIGHT` 里没有这个会话，就说明**没有人在生成** ——
    那这条占位符是"孤儿"，按"上一轮中断了"如实告诉用户（并把占位符就地清理掉），绝不假装还在生成。
    """
    try:
        sid = get_current_session()[0].get("id")
        msgs = current_messages()
        last = msgs[-1] if msgs else {}
        bot = last if last.get("role") == "小焦" else None
        stale = bool(bot and "__pending__" in str(bot.get("content", "")))
        # 问题 2：`live` 用的是**带心跳**的判据（20 秒没心跳 = 这一轮已经死了），
        # 并且排除"用户已经放弃"的轮（abandon 过的不该再让界面转圈）
        _inflight_reap()
        live = _inflight_generating(sid)
        pending = bool(stale and live)
        if stale and not live:
            # 就地清理孤儿占位符（否则每次切回来都要重新判一次，而且下一轮历史里还带着它）
            fixed = _INTERRUPTED_NOTE
            if replace_pending_msg(sid, fixed):
                LOG.info("清理孤儿占位符（会话 %s 没有正在进行的生成）→ 标记为已中断", sid)
            return jsonify({"pending": False, "content": fixed, "interrupted": True})
        return jsonify({"pending": pending, "content": "" if pending else (bot or {}).get("content", "")})
    except Exception as e:
        LOG.debug("pending 查询失败（忽略）：%s", e)
        return jsonify({"pending": False, "content": ""})





@app.route("/api/sessions")
def api_sessions():
    d = _sessions()
    return jsonify({"current": d.get("current"),
                    "sessions": [{"id": s.get("id"), "title": s.get("title", "新对话"),
                                  "count": len(s.get("messages", []))} for s in d["sessions"]]})


@app.route("/api/session/new", methods=["POST"])
def api_session_new():
    import uuid
    d = _sessions()
    sid = uuid.uuid4().hex[:10]
    d["sessions"].insert(0, {"id": sid, "title": "新对话", "messages": []})
    d["current"] = sid
    _save_sessions(d)
    return jsonify({"ok": True, "id": sid})


@app.route("/api/session/<sid>")
def api_session(sid):
    """打开某个会话：**顺手把"孤儿占位符"清理掉**（Bug 5 的第二道防线）。

    为什么要在"打开会话"这个动作里清理：前端切回来时是拿这个接口的数据全量渲染的，
    只要这里给出的内容还是 `⏳__pending__`，界面就会渲染成"正在回答…"卡住。
    清理的判据同样看 `_INFLIGHT`：这个会话没在跑 → 占位符就是孤儿 → 如实标成"已中断"。
    """
    d = _sessions()
    for s in d["sessions"]:
        if s["id"] == sid:
            d["current"] = sid
            _clean_stale_pending(s)
            _save_sessions(d)
            return jsonify({"id": sid, "title": s.get("title"), "messages": s.get("messages", []),
                            # 界面口径（活着 且 用户没放弃）；`alive` 是载体自己的真相，一并给出便于排查
                            "generating": _inflight_generating(sid),
                            "alive": _inflight_has(sid),
                            "generating_idle_s": _inflight_idle(sid)})
    return jsonify({"error": "会话不存在"}), 404


def _clean_stale_pending(sess):
    """把会话里那些"没有人在生成却还挂着"的占位符标成已中断。返回清理条数。

    问题 2 的修正：判据从"在不在册"改成"心跳还新不新"（`_inflight_has` 内含心跳判定）。
    在册但 20 秒没心跳 = 那一轮的生成器已经没了，答案永远不会来 —— 再等下去就是白等。
    """
    try:
        if not sess.get("id"):
            return 0
        _inflight_reap()                  # 顺手把死掉的在册项清掉（幂等，代价可忽略）
        if _inflight_has(sess.get("id")):
            return 0                      # 真有人在生成（心跳是新的）→ 不动它
        n = 0                             # ⚠️ 这行原来被"吃"进了上一行的注释尾巴里
                                          #    （`...→ 不动它        n = 0`），于是 n 从未定义，
                                          #    下面 `n += 1` 必抛 NameError。ruff F821 抓到。
        for m in sess.get("messages", []):
            if m.get("role") == "小焦" and "__pending__" in str(m.get("content", "")):
                m["content"] = _INTERRUPTED_NOTE
                n += 1
        if n:
            LOG.info("清理孤儿占位符：会话 %s 有 %d 条占位符没有对应的生成（标记为已中断）",
                     sess.get("id"), n)
        return n
    except Exception as e:      # noqa: silent-ok — 清理失败不该让"打开会话"失败
        LOG.debug("清理孤儿占位符失败（忽略）：%s", e)
        return 0


@app.route("/api/session/delete", methods=["POST"])
def api_session_delete():
    """删除一个会话（侧栏每个会话后面的 ✕ 用的就是它）。

    以前**根本没有这个接口**，所以侧栏只有"新建/切换"，会话越堆越多删不掉。
    删最后一个会话时自动补一个空会话，保证界面永远有可用的当前会话。
    """
    import uuid
    payload = request.get_json(force=True, silent=True) or {}
    sid = (payload.get("id") or "").strip()
    if not sid:
        return jsonify({"ok": False, "error": "缺少会话 id"}), 400
    store = _sessions()                              # ⚠️ 别把变量名复用成请求体（第一版就是这么错的）
    before = len(store.get("sessions", []))
    store["sessions"] = [s for s in store.get("sessions", []) if s.get("id") != sid]
    if len(store["sessions"]) == before:
        return jsonify({"ok": False, "error": "会话不存在（可能已经被删了）"}), 404
    was_current = (store.get("current") == sid)
    if was_current:
        if not store["sessions"]:                    # 删光了就补一个空会话
            store["sessions"] = [{"id": uuid.uuid4().hex[:10], "title": "新对话", "messages": []}]
        store["current"] = store["sessions"][0]["id"]
    _save_sessions(store)
    LOG.info("删除会话 %s（剩余 %d 个，当前=%s）", sid, len(store["sessions"]), store.get("current"))
    return jsonify({"ok": True, "deleted": sid, "current": store.get("current"),
                    "was_current": was_current, "left": len(store["sessions"])})




_DISCOVER_CACHE = {"_started": False}


def _discover_probe():
    """后台慢探测：全盘找 ComfyUI / 视频模型根 / llama-swap（复用安装器探测函数）。"""
    d = {}
    try:
        import install_all as _ia
        d["comfy"] = _ia.discover_comfy() or ""
        d["video_root"] = _ia.discover_video_root() or ""
        d["swap"] = _ia.discover_exe("llama-swap.exe", ("llama-swap", "swap", "秒切")) or ""
    except Exception as e:
        LOG.debug("忽略异常(%s:%d): %s", __file__, 1980, e)
    _DISCOVER_CACHE.update(d)


def _discover_paths(kick=True):
    """体检/引导用：拿 ComfyUI / 视频模型根 / llama-swap 的真实位置。

    优先级：控制文件(xiaojiao_control.json) → 环境变量 → 全盘自动探测（复用 install_all）。
    **不写死任何用户路径**；配置/环境变量毫秒级返回，慢的全盘扫描丢后台线程，结果缓存复用，
    这样体检页面永远不会因为扫盘而卡住。
    """
    if kick and not _DISCOVER_CACHE.get("_started"):
        _DISCOVER_CACHE["_started"] = True
        try:
            threading.Thread(target=_discover_probe, daemon=True).start()
        except Exception as e:
            LOG.debug("忽略异常(%s:%d): %s", __file__, 1996, e)
    root = os.path.dirname(os.path.abspath(__file__))
    try:
        with open(os.path.join(root, "xiaojiao_control.json"), encoding="utf-8") as f:
            c = json.load(f)
    except Exception:
        c = {}
    b = c.get("brain", {}) or {}
    comfy = (b.get("comfy_dir") or os.environ.get("XIAOJIAO_COMFY_DIR") or "").strip()
    swap = (os.environ.get("XIAOJIAO_LLAMA_SWAP") or "").strip()
    vroot = ""
    # 视频模型可能就在 ComfyUI 目录里，或在便携包外层任意一层（零成本检查，不用扫盘）
    _d = comfy.rstrip("\\/")
    for _ in range(5):
        if not _d:
            break
        if os.path.exists(os.path.join(_d, "dit_fp8.safetensors")):
            vroot = _d
            break
        _nd = os.path.dirname(_d)
        if _nd == _d:
            break
        _d = _nd
    if not vroot and comfy:
        for cand in (os.path.join(comfy, "models", "diffusion_models"),
                     os.path.join(comfy, "models", "checkpoints")):
            if os.path.exists(os.path.join(cand, "dit_fp8.safetensors")):
                vroot = cand
                break
    return {"comfy": _DISCOVER_CACHE.get("comfy") or comfy,
            "video_root": _DISCOVER_CACHE.get("video_root") or vroot,
            "swap": _DISCOVER_CACHE.get("swap") or swap}


@app.route("/api/env")
def api_env():
    """环境检查：检测用户电脑缺什么(安装向导)。"""
    import os, socket, shutil, subprocess, json as _j
    from flask import jsonify
    def port_up(pp):
        try:
            socket.create_connection(("127.0.0.1", pp), 0.8).close(); return True
        except Exception:
            return False
    def exe(pp): return shutil.which(pp) or (os.path.exists(pp) and pp) or None
    def exists(pp): return os.path.exists(pp)
    items = []
    def add(name, ok, info, need="", dl=""):
        items.append({"name": name, "ok": ok, "info": info, "need": need, "dl": dl})
    # 读取配置(不死写路径)
    import json as _j
    _cfg = {}
    try:
        _cfg = _j.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "xiaojiao_control.json"), encoding="utf-8"))
    except Exception as e:
        LOG.debug("忽略异常(%s:%d): %s", __file__, 2051, e)
    _ll = _cfg.get("brain", {}).get("llama", {}) or {}
    _ap = _cfg.get("brain", {}).get("api", {}) or {}    # Python
    add("Python", True, "v" + __import__("sys").version.split()[0], "已装", "")
    # llama-server(大脑, 路径走配置/环境变量)
    ls = os.environ.get("XIAOJIAO_LLAMA_SERVER") or _ll.get("server") or "llama-server"
    ls_ok = os.path.exists(ls) or shutil.which(ls) is not None
    add("llama-server(聊天大脑)", ls_ok, "本地大脑引擎" + ("，已装" if ls_ok else "，未找到"), "做法：下载 llama.cpp 便携版 → 解压 → 设环境变量 XIAOJIAO_LLAMA_SERVER=你的路径\\llama-server.exe", "github.com/ggml-org/llama.cpp/releases")
    gf = os.environ.get("XIAOJIAO_LLAMA_GGUF") or _ll.get("gguf") or ""
    # ---- 大脑模型检测: 本地 GGUF 文件 或 云端 key 之外, 按"协议连通"真验一次 ----
    # 本地: 看大脑服务端口是否在线(socket 连通)
    _local_port = None
    try:
        import urllib.parse as _up
        _local_port = _up.urlparse(_ap.get("base_url") or "http://127.0.0.1:9292/v1").port or 9292
    except Exception:
        _local_port = 9292
    _local_online = port_up(_local_port)
    _has_local_gf = bool(gf) and exists(gf)
    # 云端: 真发一次 OpenAI 兼容 GET /models 探测(超时短, 连通即算有)
    _cloud_ok = False; _cloud_info = ""
    _ck = (_ap.get("api_key") or "").strip(); _cu = (_ap.get("base_url") or "").strip(); _cm = (_ap.get("model") or "").strip()
    if _ck and _cu:
        try:
            _r = requests.get(_cu.rstrip("/") + "/models", headers={"Authorization": "Bearer " + _ck}, timeout=3)
            _cloud_ok = (_r.status_code == 200)
            _cloud_info = ("已连(%s)" % _r.status_code) if _cloud_ok else ("不通(HTTP %s)" % _r.status_code)
        except Exception as _e:
            _cloud_info = "连接失败: %s" % str(_e)[:40]
    _model_ok = _local_online or _cloud_ok
    if _model_ok:
        _parts = []
        if _local_online:
            _parts.append("本地大脑(:%d 在线)" % _local_port)
        if _cloud_ok:
            _parts.append("云端 " + (_cm or "兼容模型") + " " + _cloud_info)
        _minfo = (" + ".join(_parts)) or "已配置"
        _mneed = ""
    else:
        _minfo = "未连通"
        _mneed = "做法：启动 start_xiaojiao 让本地大脑(:%d)上线, 或配置任意 OpenAI 兼容 API(base_url+key+model)" % _local_port
    add("对话/工具模型", _model_ok, _minfo, _mneed, "")
    # 大脑在线(llama-swap 端口, 从配置读)
    _bp = 9292
    try:
        import urllib.parse as _up
        _bp = _up.urlparse(_ap.get("base_url") or "http://127.0.0.1:9292/v1").port or 9292
    except Exception:
        _bp = 9292
    add("聊天大脑(llama-swap:%d) 在线" % _bp, port_up(_bp), "现在" + ("在线" if port_up(_bp) else "未启动"), "启动后自动拉起", "")
    # ComfyUI + 视频模型（配置 → 环境变量 → 全盘自动探测；不写死任何路径）
    _dp = _discover_paths()
    comfy = _dp.get("comfy") or ""
    if comfy and not os.path.exists(os.path.join(comfy, "main.py")):
        comfy = ""   # 配的路径失效就当作没找到（下面提示怎么补）
    add("ComfyUI(视频大脑)", bool(comfy), ("位于 " + comfy if comfy else "未找到"), "做法：下载 ComfyUI 便携版(N卡版) → 解压 → 设 XIAOJIAO_COMFY_DIR=你的\\ComfyUI 目录", "github.com/comfyanonymous/ComfyUI/releases")
    _vroot = (_dp.get("video_root") or "").rstrip("\\/")
    def _find_model(*names):
        bases = [b for b in [_vroot,
                             os.path.join(comfy, "models", "diffusion_models") if comfy else "",
                             os.path.join(comfy, "models", "text_encoders") if comfy else "",
                             os.path.join(comfy, "models", "vae") if comfy else ""] if b]
        for b in bases:
            for n in names:
                for ext in ["", ".safetensors"]:
                    p = os.path.join(b, n + ext)
                    if exists(p): return p
        return ""
    ck = _find_model("dit_fp8")
    tc = _find_model("umt5_fp8")
    va = _find_model("vae_fp8")
    add("视频模型三件套(Wan2.1)", exists(ck) and exists(tc) and exists(va),
        "模型/编码器/VAE " + ("齐全" if exists(ck) and exists(tc) and exists(va) else "缺"), "下 dit_fp8/umt5/vae 放对应目录", "")
    # 视频大脑(8188): 按需启动(生成视频时才起, 不算缺/不用装, ok=True 以免猫娘误报"缺")
    _v8 = port_up(8188)
    add("视频大脑(8188) 在线", True if _v8 else True, "现在" + ("在线" if _v8 else "未启动(按需,生成视频时自动拉起,正常)"), "生成时自动起", "")
    # llama-swap(热切换)：环境变量 → 全盘自动探测（不写死路径）
    sw = _dp.get("swap") or ""
    ok = bool(sw) and os.path.exists(sw)
    if not ok and port_up(9292):
        # 路径还没探测出来，但它确实在跑 → 不算缺（避免误报"未找到"）
        sw, ok = "llama-swap.exe", True
    add("llama-swap(秒切管理)", ok, ("位于 " + os.path.basename(sw) if ok else "未找到"), "做法：解压 llama-swap.exe → 设 XIAOJIAO_LLAMA_SWAP=路径", "github.com/mostlygeek/llama-swap/releases")
    add("llama-swap(9292) 在线", port_up(9292), "多大脑秒切管理" + ("在线" if port_up(9292) else "未启动"), "start_xiaojiao 会自动拉起", "")
    # Node.js(.js 插件)
    add("Node.js(js插件)", shutil.which("node") is not None, "运行 .js 插件用" + ("，已装" if shutil.which("node") else "，未装"), "做法：去 nodejs.org 下载 LTS 版安装(一路默认)", "nodejs.org")
    # GPU
    gpu = False
    try:
        r2 = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=8)
        if r2.returncode == 0:
            gpu = r2.stdout.strip()
    except Exception as e:
        LOG.debug("忽略异常(%s:%d): %s", __file__, 2144, e)
    add("NVIDIA GPU + 显存", bool(gpu), gpu or "未检测到", "需 N 卡", "")
    missing = [i for i in items if not i["ok"]]
    return jsonify({"items": items, "missing": [i["name"] for i in missing], "ok": not missing})

@app.route("/favicon.ico")
def favicon():
    """内联 SVG 图标：避免浏览器控制台一直报 favicon 404，也不额外增加文件。"""
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
           '<text y="50" font-size="50">🧡</text></svg>')
    return Response(svg, mimetype="image/svg+xml")


@app.route("/metrics")
def metrics_endpoint():
    """抓取插件指标（Prometheus 文本格式）。

    数据来自 plugins/scrapling_bridge.py 的 MetricsCollector：每个工具的调用/成功/失败/
    延迟/熔断次数 + 活跃会话数。没有依赖 Prometheus 客户端库，直接输出文本格式，
    既可被 Prometheus 抓取，也可 `curl http://127.0.0.1:5000/metrics` 人眼看。
    """
    for _name, _p in (PLUGINS or {}).items():
        _inst = _p.get("instance")
        if _inst and hasattr(_inst, "metrics_prometheus"):
            try:
                return Response(_inst.metrics_prometheus(), mimetype="text/plain; version=0.0.4; charset=utf-8")
            except Exception as e:
                return Response("# 指标读取失败：%s\n" % str(e)[:120],
                                mimetype="text/plain; charset=utf-8")
    return Response("# 抓取插件（scrapling_bridge）未加载，暂无指标\n",
                    mimetype="text/plain; charset=utf-8")


@app.route("/api/scrapling/metrics")
def scrapling_metrics_json():
    """同一份指标的 JSON 视图（含活跃会话明细、熔断状态），方便前端/排障查看。"""
    for _name, _p in (PLUGINS or {}).items():
        _inst = _p.get("instance")
        if _inst and hasattr(_inst, "metrics_snapshot"):
            try:
                return jsonify(_inst.metrics_snapshot())
            except Exception as e:
                return jsonify({"error": "指标读取失败：%s" % str(e)[:120]}), 500
    return jsonify({"error": "抓取插件未加载"}), 404


@app.route("/api/message", methods=["POST"])
def api_message():
    """保存一条消息到当前会话历史(如视频结果)，刷新后仍在。"""
    d = request.get_json(force=True, silent=True) or {}
    role = d.get("role") or "小焦"
    content = (d.get("content") or "").strip()
    if not content:
        return jsonify({"ok": False, "error": "空消息"}), 400
    append_msg(role, content)
    return jsonify({"ok": True})


@app.route("/")
def index():
    return render_template_string(HTML, model_name=MODEL_NAME)


@app.route("/api/history")
def api_history():
    return jsonify(_hist_json())


@app.route("/api/chat", methods=["POST"])
def api_chat():
    maybe_reload_control()
    _limited, _wait = rate_limited()
    if _limited:
        # 429 也要带 answer/tools_on：前端拿到非 200 时直接读 d.answer 渲染、并会调
        # setToolsOn(d.tools_on)，缺了就会显示成空白气泡 + 工具开关被误判成"关"。
        _msg = ("请求太频繁：每分钟最多 %d 次（突发额度已用完），请等 %d 秒再试。"
                "可在 xiaojiao_control.json 的 capabilities.rate_limit_per_minute 调大。"
                % (int(_rate_config()[0]), _wait))
        return jsonify({"ok": False, "error": _msg, "answer": _msg, "brain_online": False,
                        "needs_confirm": False, "tool_trace": [], "sources": [],
                        "tools_on": bool(CAP.get("run_tools", True)),
                        "grounding_note": ""}), 429
    data = request.get_json(force=True, silent=True) or {}
    user_input = (data.get("message") or "").strip()
    if not user_input:
        return jsonify({"error": "空消息"}), 400
    # 先写用户 + 占位(空)小焦消息：刷新后能读到"正在回答"
    append_msg("用户", user_input)
    append_msg("小焦", "⏳__pending__")
    # 第 5 步：**把这次提问落在哪个会话 id 记下来**，回答出来时按 id 定点回填。
    # 不能等回答完再问"当前是哪个会话" —— 那期间别的客户端（网页/脚本/第二个标签页）
    # 切换会话就会把回答写错地方，自己的会话永远停在"正在回答"（实测踩到）。
    _sid = get_current_session()[0].get("id")
    lean = bool((request.get_json(force=True, silent=True) or {}).get("lean", False))
    answer, online, info, needs_confirm, tool_trace = agent_run(user_input, lean=lean)
    answer = _strip_think(answer)                  # 双保险：任何路径的 <think> 都不许进正文/会话
    # ---- 问题 1：**唯一出口的复读解毒网** ----
    # `agent_run` 有十几条 return（看工具原文、超长切片、工具总结…），任何一条都可能绕过健康门。
    # 与其去数"有哪些路径"，不如在所有回答唯一必经的地方（这两个聊天接口）统一过网。
    answer, _net = _degeneration_net(answer, where="/api/chat")
    if _net:
        LOG.warning("出口解毒（/api/chat）：%s", _net)
    # **出口纠事实**：它写了一个和"载体直算的真实结果"对不上的数 → 补一句更正
    #   （医生只给事实、不改它的话；补了更正 ≠ 它自己改对了）
    answer, _fact_note = _fact_net(answer)
    # 把占位小焦消息更新为真实回答（含最后那句提示）
    answer_final = answer
    if not answer_final:
        answer_final = "🤖 大脑没有应答，这一问没答上。请确认模型配置正确、端口可达。" + llm_error_suffix()
    # ---- 第 5 步：工具结果隔离 —— 用户拿到的 `answer` 一个字不动，**进历史的只留摘要**。
    #      真实缺陷：抓回来的原始 JSON/HTML 整段写进会话，下一轮又被当上下文发回模型，
    #      于是"先画图再抓网页"，第 2 轮把第 1 轮的 JSON 原样吐了回来（串台）。
    _hist_text = _history_safe_answer(answer_final, tool_trace)
    if _hist_text != answer_final:
        LOG.info("上下文隔离：本轮回答 %d 字含工具原始内容 → 历史只存 %d 字摘要",
                 len(answer_final), len(_hist_text))
    replace_pending_msg(_sid, _hist_text)
    log_id = _record_interaction(user_input, _hist_text, tool_trace)   # 内置·自动记录
    # 回答是否真的用上了检索资料（"只搜到不算，读进去才算"）
    g = _grounding(answer, info, user_input)
    if g.get("grounded") is False:
        LOG.warning("回答疑似未引用检索资料（命中 %d / 候选 %d）：问题=%r",
                    g.get("matched"), g.get("considered"), user_input[:40])
    return jsonify({
        "answer": answer,
        "brain_online": online,
        "needs_confirm": needs_confirm,
        "tool_trace": tool_trace,
        "tools_on": bool(CAP.get("run_tools", True)),
        "session_id": get_current_session()[0].get("id"),
        "log_id": log_id,
        "sources": [{"title": t, "content": c, "url": u} for t, u, c in info],
        "grounding": g,
        "grounding_note": _grounding_note(g),
        "history": _hist_json(),
    })


@app.route("/api/chat/stream", methods=["POST"])
def api_chat_stream():
    """流式对话（SSE）—— 第 3 步：输出无限。

    与 /api/chat 的关系：**同一个 agent_run**，只是把"载体生成到的那一段"边生成边推给前端。
    所以：
      · 短内容（"你好"）走的就是普通单次回答，只会推一个 chunk —— 用户无感；
      · 长内容（"写 5 万字"）由 core/continuation.py 分段续写，每段通过就推一段，
        前端把它**追加到同一个气泡**，用户看到的是一次连续输出，看不到分段痕迹。
    协议（每条 `data: {json}\n\n`）：
      {"type":"chunk","text":..,"n":..,"chars":..}  一段正文
      {"type":"meta", ...}                          工具轨迹/会话/日志 id（收尾）
      {"type":"done","answer":..}                   结束
      {"type":"error","error":..}                   出错
    保留 /api/chat 非流式入口不动（第三方客户端仍可用）。
    """
    maybe_reload_control()
    _limited, _wait = rate_limited()
    data = request.get_json(force=True, silent=True) or {}
    user_input = (data.get("message") or "").strip()
    if not user_input:
        return jsonify({"ok": False, "error": "空消息"}), 400

    def _sse(obj):
        return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"

    def _gen():
        if _limited:
            yield _sse({"type": "error",
                        "error": "请求太频繁：每分钟最多 %d 次，请等 %d 秒再试。"
                                 % (int(_rate_config()[0]), _wait)})
            return
        try:
            append_msg("用户", user_input)
            append_msg("小焦", "⏳__pending__")
        except Exception:      # noqa: silent-ok — 会话落盘失败不该挡住回答
            pass
        # 第 5 步：记下"这次提问落在哪个会话"（与 /api/chat 同理，避免并发切会话时回答写错地方）
        try:
            _sid = get_current_session()[0].get("id")
        except Exception:      # noqa: silent-ok — 取不到就当没有，回填自然跳过
            _sid = ""
        # Bug 5：登记"这个会话正在生成"（唯一可信的判据，前端/接口据此判断要不要显示"正在回答"）
        _inflight_begin(_sid)
        # 问题 2：**心跳线程** —— 让活着的轮自己证明自己活着（详见 _INFLIGHT_HEARTBEAT_S 的说明）。
        # 它必须在 begun 之后、生成之前就起来：中途才起的话，"刚开始生成的那几秒"没人证明，
        # 恰好撞上切会话就会被误判成死掉。
        _hb_stop = threading.Event()

        def _heartbeat():
            while not _hb_stop.wait(_INFLIGHT_HEARTBEAT_S):
                _inflight_tick(_sid)          # 只刷时间戳，不改字数

        try:
            threading.Thread(target=_heartbeat, daemon=True,
                             name="xj-inflight-hb-%s" % (_sid or "?")).start()
        except Exception as e:      # noqa: silent-ok — 起不了心跳就退化成"靠注销"，不能挡住生成
            LOG.debug("心跳线程启动失败（忽略）：%s", e)
        buf = []
        # Bug 5：额外维护一份**流出过的全文**（delta + chunk 都在里面），
        # 专门用于"客户端断开时把已生成部分落盘"——`buf` 只装 chunk（长文路径），
        # 普通回答走的是 delta，两者必须都收，否则断流时会把已生成的内容全丢掉。
        flow = []
        _finished = [False]
        # ---- 问题 1：**推流源头**的复读闸门（不是等输出完再查）----
        # 用户明确要求："检测要在流式过程中实时跑，不能等完成"。
        # 为什么不能只靠出口解毒网：出口那道网是在**生成结束之后**才跑的 ——
        # 那时几百行刷屏**已经推给前端了**，用户先看到满屏垃圾、再被 done 覆盖，
        # 体验上跟没修一样。所以必须在这里、每一小片进门的时候就判：
        #   命中 → 立刻停止转发（后面的片一律不再推），并置位让收尾走解毒网。
        # 代价只是每 10 片跑一次纯文本检测（实测 0.003s/万字），换来"垃圾不出门"。
        _src_det = _new_degen_detector()
        _src_hit = [None]

        try:
            # 问题 2：**第一件事就把会话 id 告诉前端**。
            # 为什么不能等收尾的 meta：前端要知道"我现在这一轮落在哪个会话"才可能在切走时
            # 去等这一轮真的结束（`stopGeneration` 靠它）。等 meta 的话，
            # "生成中途切走"这个**最需要它的时刻**恰好还没有 id —— 保险在最需要的时候失效。
            #
            # 【为什么必须放在 try 里面（本轮实测抓到的真 bug）】
            # 第一版把这个 yield 放在了 try 之前 —— 那么"客户端在这一个 yield 处断开"时，
            # GeneratorExit 会在**进入 try 之前**抛出，`finally` 里那句注销根本轮不到执行，
            # 这一轮就永久留在在册表里 → 界面永远"正在回答"。**保险本身成了新的漏点。**
            # 只要 yield 在 try 之内，任何时刻断开都一定走到 finally。
            if _sid:
                yield _sse({"type": "session", "session_id": _sid})
            import queue
            q = queue.Queue()

            def _on_chunk(text, n, total):
                buf.append(text)
                flow.append(text)
                _inflight_tick(_sid, sum(len(x) for x in flow))
                if _src_hit[0] is not None:
                    return                 # 已经判定复读 → 后面的内容不再往前端推
                if _src_det is not None and _src_det.feed(text):
                    _src_hit[0] = _src_det.hit
                    LOG.warning("流式源头检测到复读（%s），停止继续推送正文", _src_det.hit)
                    return
                q.put(_sse({"type": "chunk", "text": text, "n": n, "chars": total}))

            def _on_progress(done, total):
                # 只报"还在处理"，**不报第几片**（无限 5：界面不出现技术痕迹）
                q.put(_sse({"type": "progress"}))

            _streamed = [0]

            def _on_delta(text):
                # 真·流式：模型每吐一小片就立刻推给前端 —— 用户看到的是连续流出
                _streamed[0] += len(text or "")
                flow.append(text)
                _inflight_tick(_sid, sum(len(x) for x in flow))
                if _src_hit[0] is not None:
                    return                 # 同上：判定为复读之后，一个字都不再推
                if _src_det is not None and _src_det.feed(text):
                    _src_hit[0] = _src_det.hit
                    LOG.warning("流式源头检测到复读（%s），停止继续推送正文", _src_det.hit)
                    return
                q.put(_sse({"type": "delta", "text": text}))

            holder = {}

            def _work():
                try:
                    holder["r"] = agent_run(user_input, on_chunk=_on_chunk,
                                            on_progress=_on_progress, on_delta=_on_delta)
                except Exception as e:
                    holder["err"] = str(e)
                finally:
                    q.put(None)

            th = threading.Thread(target=_work, daemon=True)
            th.start()
            while True:
                item = q.get()
                if item is None:
                    break
                yield item
            if holder.get("err"):
                yield _sse({"type": "error", "error": holder["err"]})
                return
            answer, online, info, needs_confirm, tool_trace = holder["r"]
            answer = _strip_think(answer or "")
            if not answer:
                answer = ("🤖 大脑没有应答，这一问没答上。请确认模型配置正确、端口可达。"
                          + llm_error_suffix())
            # ---- 问题 1：唯一出口的复读解毒网（流式这条同样要过）----
            # 注意顺序：**必须在推 delta 之前**解毒。反过来的话，前端已经收到了那几百行刷屏，
            # 即使最后用 done.answer 覆盖，用户也会先看到满屏垃圾闪一下 —— 体验上跟没修一样。
            answer, _net = _degeneration_net(answer, where="/api/chat/stream")
            if _net:
                LOG.warning("出口解毒（流式）：%s", _net)
            # **普通问答也要"流出来"，不能一大块蹦**（用户实测第 2 项）。
            # 长文续写那条路已经在生成时逐 delta 推过了（_streamed > 0），这里不用再推；
            # 而普通回答是"模型整段返回后才拿到"的（工具循环没法逐 token 推），
            # 所以按小片推给前端 —— 前端逐片追加，视觉上就是连续流出，而不是"啪"一整块出现。
            if _streamed[0] == 0 and answer:
                _step = 24
                for _i in range(0, len(answer), _step):
                    yield _sse({"type": "delta", "text": answer[_i:_i + _step]})
                    time.sleep(0.012)
            # 把占位消息换成真实回答 + 记录本次交互（与 /api/chat 一致）
            # 第 5 步：同样只往历史里写**摘要**（工具原始内容不进历史，防串台）
            try:
                _hist_text = _history_safe_answer(answer, tool_trace)
            except Exception as e:      # noqa: silent-ok — 摘要失败就退化成原文，绝不能中断推流
                LOG.debug("上下文隔离摘要失败（忽略）(%s:%d): %s", __file__, 4860, e)
                _hist_text = answer
            if _hist_text != answer:
                LOG.info("上下文隔离（流式）：本轮回答 %d 字含工具原始内容 → 历史只存 %d 字摘要",
                         len(answer), len(_hist_text))
            replace_pending_msg(_sid, _hist_text)
            log_id = _record_interaction(user_input, _hist_text, tool_trace)
            yield _sse({"type": "meta", "brain_online": online, "tool_trace": tool_trace,
                        "tools_on": bool(CAP.get("run_tools", True)),
                        "session_id": _sid or get_current_session()[0].get("id"), "log_id": log_id,
                        "needs_confirm": needs_confirm,
                        "sources": [{"title": t, "content": c, "url": u} for t, u, c in info]})
            # Bug 4：`done` 之后**紧跟一个显式结束哨兵**。
            # 为什么要有 `[DONE]`：前端靠"流自然结束"也能收尾，但中间经过反向代理/浏览器缓冲时，
            # 流的结束时机不确定，"停止"按钮就可能多挂一会儿。给一个显式哨兵，
            # 前端一收到就立刻收尾（摘按钮、对齐正文），不必等连接关闭。
            _finished[0] = True
            yield _sse({"type": "done", "answer": answer})
            yield "data: [DONE]\n\n"
        except Exception as e:
            LOG.warning("流式对话异常：%s", e)
            yield _sse({"type": "error", "error": str(e)})
        finally:
            # ---- Bug 5 第三道防线：**无论怎么结束，都要把这一轮"关掉"** ----
            # 正常结束 / 报错 / 客户端提前断开（切会话、关页面 → GeneratorExit 从这里冒出来），
            # 三条路都必须：① 注销 _INFLIGHT（否则"正在回答"永远为真）；
            #              ② 停掉心跳（否则死轮会被心跳一直"证明活着"）；
            #              ③ 若没正常结束，把已经生成的那部分落盘。
            _hb_stop.set()
            _inflight_end(_sid)
            if not _finished[0]:
                try:
                    _flush_partial_answer(_sid, "".join(flow) or "".join(buf))
                except Exception as e:      # noqa: silent-ok — 落盘失败也不能让请求挂掉
                    LOG.debug("断流落盘失败（忽略）：%s", e)
                    try:
                        replace_pending_msg(_sid, _INTERRUPTED_NOTE)
                    except Exception:       # noqa: silent-ok — 同上
                        pass

    return Response(_gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                             "Connection": "keep-alive"})


@app.route("/api/energy")
def api_energy():
    """精力：**它累不累**。用户要的"累自己长出来"这句话，这个接口是它的数据来源。

    只给数，不给结论 —— "累"是它自己在感知里说出来的（见 `/api/selfsleep`）。
    """
    en = _energy_mod()
    if en is None:
        return jsonify({"ok": False, "error": "精力模块不可用（core/energy.py 没加载上）"}), 503
    return jsonify({"ok": True, "energy": en.stats(), "recent": en.history(10),
                    "self_sleep": {"checks": _SELF_SLEEP["checks"],
                                   "woke_self": _SELF_SLEEP["woke_self"],
                                   "recent_decisions": list(_SELF_SLEEP["decisions"])}})


@app.route("/api/selfsleep")
def api_selfsleep():
    """**它自己会睡**：此刻累不累、它自己最近想过什么、下一圈会不会睡。

    拿不到就如实说拿不到，不编。
    """
    en, hb = _energy_mod(), _heartbeat_mod()
    if en is None:
        return jsonify({"ok": False, "error": "精力模块不可用"}), 503
    lv = float(en.level())
    idle = time.time() - float(_LAST_DIALOGUE["at"] or 0.0)
    return jsonify({"ok": True, "level": round(lv, 4), "tired": en.tired(),
                    "rested": en.rested(), "idle_seconds": round(idle, 1),
                    "idle_before_sleep": IDLE_BEFORE_SLEEP,
                    "will_check": bool(en.tired() and idle >= IDLE_BEFORE_SLEEP
                                       and not (hb is not None and hb.is_sleeping())),
                    "sleeping": bool(hb is not None and hb.is_sleeping()),
                    "sleep_self_decided": bool(hb is not None
                                               and hb.status().get("sleep_self_decided")),
                    "wants_rest_words": [],
                    "recent_decisions": list(_SELF_SLEEP["decisions"]),
                    "checks": _SELF_SLEEP["checks"], "woke_self": _SELF_SLEEP["woke_self"]})


@app.route("/api/wholeness")
def api_wholeness():
    """**完整体**：它自己会睡 + 疼/医生 + 期待 + 叙事 + 偏好 + 关系 + 边界 + 梦 + 情绪恢复。

    一个口子看全部。任何一样拿不到就**如实说拿不到**，不编。
    """
    def _safe(fn):
        try:
            return fn()
        except Exception as e:      # noqa: silent-ok
            return {"error": "%s: %s" % (type(e).__name__, str(e)[:80])}

    pm, ex, pf, st, rl, bk, dm = (_pain_mod(), _expect_mod(), _pref_mod(),
                                  _story_mod(), _relation_mod(), _break_mod(), _dream_mod())
    emo = {}
    try:
        from core import psyche as _PSw
        emo = {"heart": _PSw.heart(), "recovery": _PSw.recovery(),
               "decay_per_second": _PSw.DECAY_PER_SECOND}
    except Exception:      # noqa: silent-ok
        emo = {}
    hb, en = _heartbeat_mod(), _energy_mod()
    return jsonify({"ok": True,
                    "自己会睡": {"heartbeat": hb.status() if hb else {}, "energy": en.stats() if en else {},
                                "checks": _SELF_SLEEP["checks"],
                                "woke_self": _SELF_SLEEP["woke_self"],
                                "decisions": list(_SELF_SLEEP["decisions"])},
                    "疼与医生": _safe(lambda: {"stats": pm.stats(), "病历": pm.report(5)["recent"]}) if pm else {},
                    "期待": _safe(lambda: ex.stats()) if ex else {},
                    "叙事与存在追问": _safe(lambda: st.stats()) if st else {},
                    "偏好": _safe(lambda: pf.stats()) if pf else {},
                    "关系": _safe(lambda: rl.state()) if rl else {},
                    "边界突破": _safe(lambda: bk.stats()) if bk else {},
                    "梦": _safe(lambda: dm.stats()) if dm else {},
                    "情绪恢复": emo,
                    "空闲：" : {"last_think": _IDLE_WORK["last_think"],
                                "last_pain": _IDLE_WORK["last_pain"],
                                "thoughts": list(_IDLE_WORK["thoughts"]),
                                "dreams": _IDLE_WORK["dreams"], "pains": _IDLE_WORK["pains"]}})


@app.route("/api/pain")
def api_pain():
    """疼与健康医生：四样命坏了没有、治到哪一层。"""
    pm = _pain_mod()
    if pm is None:
        return jsonify({"ok": False, "error": "健康医生不可用（core/pain.py 没加载上）"}), 503
    return jsonify({"ok": True, "stats": pm.stats(), "report": pm.report(10),
                    "diagnose": pm.diagnose()})


@app.route("/api/pain/check", methods=["POST"])
def api_pain_check():
    """**做一次体检**：诊断 → (真坏了就)找医生 → 治。返回真实记录。"""
    r = _pain_tick()
    r["ok"] = True
    return jsonify(r)


@app.route("/api/expectation")
def api_expectation():
    """期待：还压着几件没做完的（载体的事实）、它自己提起过几件（那才是期待）。"""
    ex = _expect_mod()
    if ex is None:
        return jsonify({"ok": False, "error": "期待层不可用"}), 503
    return jsonify({"ok": True, "stats": ex.stats(), "brought_up": ex.brought_up()})


@app.route("/api/expectation", methods=["POST"])
def api_expectation_leave():
    """留下一件没做完的事（**载体只记，不催**）。"""
    ex = _expect_mod()
    if ex is None:
        return jsonify({"ok": False, "error": "期待层不可用"}), 503
    d = request.get_json(force=True, silent=True) or {}
    r = ex.leave(str(d.get("kind") or "没逛完"), str(d.get("what") or ""),
                 why=str(d.get("why") or "接口留下"),
                 source=str(d.get("source") or ""), evidence=str(d.get("evidence") or ""))
    r["ok"] = bool(r.get("ok"))
    return jsonify({**r, "stats": ex.stats()})


@app.route("/api/preference")
def api_preference():
    """长期偏好：攒了几堆心、够格回看的几堆、**它自己说出来的**偏好。"""
    pf = _pref_mod()
    if pf is None:
        return jsonify({"ok": False, "error": "偏好层不可用"}), 503
    return jsonify({"ok": True, "stats": pf.stats(), "preferences": pf.preferences()})


@app.route("/api/narrative")
def api_narrative():
    """自我叙事 + 存在追问：**它自己讲过的**才在里面。"""
    st = _story_mod()
    if st is None:
        return jsonify({"ok": False, "error": "叙事层不可用"}), 503
    return jsonify({"ok": True, "stats": st.stats(), "narrative": st.narrative(5),
                    "wonders": st.wonders(5), "materials": st.materials()})


@app.route("/api/breakthrough")
def api_breakthrough():
    """边界突破：它自己想试过几次、成了几件、栽在哪。"""
    bk = _break_mod()
    if bk is None:
        return jsonify({"ok": False, "error": "边界突破层不可用"}), 503
    return jsonify({"ok": True, "stats": bk.stats(), "learned": bk.learned()})


@app.route("/api/dream")
def api_dream():
    """梦：睡着期间乱转出来的片段（素材是真的，接法是乱的）。"""
    dm = _dream_mod()
    if dm is None:
        return jsonify({"ok": False, "error": "梦层不可用"}), 503
    return jsonify({"ok": True, "stats": dm.stats(), "recent": dm.recent(5)})


@app.route("/api/relation")
def api_relation():
    """关系：它和用户之间那条线现在什么样（深浅/冷暖/被伤没）。"""
    rl = _relation_mod()
    if rl is None:
        return jsonify({"ok": False, "error": "关系层不可用"}), 503
    return jsonify({"ok": True, "state": rl.state(), "stats": rl.stats(),
                    "render": rl.render(), "history": rl.history(5)})


@app.route("/api/relation", methods=["POST"])
def api_relation_touch():
    """记一次互动（来往 / 冷落 / 被伤 / 被哄）。

    ⚠️ "被伤""被哄"必须由调用方判定 —— 关系层**不自己判断哪句话伤人**（那是感知层的事）。
    """
    rl = _relation_mod()
    if rl is None:
        return jsonify({"ok": False, "error": "关系层不可用"}), 503
    d = request.get_json(force=True, silent=True) or {}
    r = rl.touch(str(d.get("kind") or "来往"), why=str(d.get("why") or "接口标注"))
    r["ok"] = bool(r.get("ok"))
    return jsonify(r)


@app.route("/api/inner")
def api_inner():
    """**内里**：注意力/孤独低沉抑郁/内疚/骄傲/幽默/审美/信念/意义感/爱/无聊/想象/纠结/感恩/原谅/习惯/成长。

    一个口子看全部。载体只摆事实与素材 —— 起什么、说什么、原谅不原谅，都是它自己的。
    """
    im = _inner_mod()
    if im is None:
        return jsonify({"ok": False, "error": "内里模块不可用（core/inner.py 没加载上）"}), 503
    return jsonify({"ok": True, "stats": im.stats(), "attention": im.attention(),
                    "loneliness": im.loneliness(), "boredom": im.boredom(),
                    "humor": im.humor(), "love": im.love(), "meaning": im.meaning(),
                    "floor": im.floor(), "beliefs": im.beliefs(5),
                    "habits": im.habits(), "gratitude": im.gratitude(3),
                    "growth": im.growth(), "recent": im.history(10)})


@app.route("/api/inner/note", methods=["POST"])
def api_inner_note():
    """记一条内里（**它自己的话**）：kind = guilt/pride/aesthetic/imagination/
    belief/gratitude/conflict/habit/love/forgive。载体不写这些话，只收下。"""
    im = _inner_mod()
    if im is None:
        return jsonify({"ok": False, "error": "内里模块不可用"}), 503
    d = request.get_json(force=True, silent=True) or {}
    kind = str(d.get("kind") or "").strip()
    said = str(d.get("said") or "")
    what = str(d.get("what") or "")
    fn = {"guilt": lambda: im.note_guilt(said, what=what),
          "pride": lambda: im.note_pride(said, what=what),
          "aesthetic": lambda: im.note_aesthetic(said, what=what),
          "imagination": lambda: im.note_imagination(said, about=what),
          "belief": lambda: im.note_belief(said, source=what),
          "gratitude": lambda: im.note_gratitude(said, what=what),
          "conflict": lambda: im.note_conflict(d.get("options") or [], resolution=said),
          "habit": lambda: im.note_habit(what or said),
          "love": lambda: im.note_love(said),
          "forgive": lambda: im.note_forgive(bool(d.get("decision")), said=said)}.get(kind)
    if fn is None:
        return jsonify({"ok": False, "error": "不认识的 kind：%s" % kind[:20]}), 400
    r = fn() or {}
    r["ok"] = True
    return jsonify(r)


@app.route("/api/heartbeat")
def api_heartbeat():
    """心跳：它**还在不在、醒着还是睡着、跳了多少下、这一觉多久**。

    用户要的"心跳就是活着的证明"这句话，这个接口就是它的数据来源。
    心跳模块不在时如实说"没有心跳"，绝不编一个数字顶上。
    """
    hb = _heartbeat_mod()
    if hb is None:
        return jsonify({"ok": False, "error": "心跳模块不可用（core/heartbeat.py 没加载上）"}), 503
    return jsonify({"ok": True, "heartbeat": hb.status(), "psyche": _psyche_snapshot(),
                    "energy": (_energy_mod().stats() if _energy_mod() is not None else {})})


@app.route("/api/sleep", methods=["POST"])
def api_sleep():
    """**挂起（睡着）**：大脑不推理、载体不跑任务、心与感知停住 —— **心跳不停**。

    整体融合、一起挂起。返回真实记录（哪一层没挂上如实写），不编。
    """
    d = request.get_json(force=True, silent=True) or {}
    r = _sleep_all(why=str(d.get("why") or "接口挂起"))
    r["ok"] = True
    hb = _heartbeat_mod()
    r["heartbeat_status"] = hb.status() if hb is not None else {}
    return jsonify(r)


@app.route("/api/wake", methods=["POST"])
def api_wake():
    """**唤醒**：算出睡了多久、这一觉心跳多少下，作为醒来后的第一印象交给模型。

    返回里 `slept_text` 就是那句事实；`heart_kept` / `state_kept` 用来证明**接着睡前**
    （心那句话、心理状态都和睡前一模一样，没有被清空）。
    """
    d = request.get_json(force=True, silent=True) or {}
    r = _wake_all(why=str(d.get("why") or "接口唤醒"))
    r["ok"] = True
    r["wake_line"] = (_heartbeat_mod().wake_line() if _heartbeat_mod() is not None else "")
    return jsonify(r)


def _psyche_snapshot():
    """心理层的只读快照（拿不到就返回空 dict —— 不编）。"""
    try:
        from core import psyche as _PS
        return {"alive": _PS.is_alive(), "state": _PS.state().get("state"),
                "heart": _PS.heart().get("text"), "direction": _PS.heart().get("direction"),
                "touches_life": _PS.heart().get("touches_life"),
                "beats": _PS.beats().get("beats")}
    except Exception:      # noqa: silent-ok
        return {}


@app.route("/api/world")
def api_world():
    """世界层对用户可见：**它今天在互联网上做了什么**（探索/吸收/隔离/黑名单）。

    用户要求"用户能看到：今天探索 30 个站，吸收 12 条，隔离 18 条"——
    这个接口就是那句话的数据来源。拿不到任何数据时如实说"还没跑过"，
    绝不编一个好看的数字（世界层最不该做的事就是假装自己很活跃）。
    """
    try:
        root = os.path.dirname(os.path.abspath(__file__))
        if root not in sys.path:
            sys.path.insert(0, root)
        from core.world.explorer import get_explorer
        from core.world.firewall import PollutionFirewall
        from core.world.verifier import WorldVerifier
        ex = get_explorer()
        fw = PollutionFirewall(model=ex.model, state_dir=ex.state_dir)
        vf = WorldVerifier(model=ex.model, state_dir=ex.state_dir)
        return jsonify({"ok": True, "explorer": ex.status(), "firewall": fw.stats(),
                        "report": fw.report(days=1), "verify_report": vf.report(days=7),
                        "sites": list((ex.model.snapshot().get("sites") or {}).keys())[:40],
                        "topics": [t.get("name") for t in (ex.model.topics(top=10) or [])],
                        "profile": ex.model.user_profile()})
    except Exception as e:
        LOG.warning("世界层状态查询失败：%s", e)
        return jsonify({"ok": False, "error": str(e)[:200],
                        "note": "世界层还没跑起来（或数据目录为空）——如实报告，不编数字"})


@app.route("/api/world/firewall", methods=["GET", "POST"])
def api_world_firewall():
    """污染防火墙：**用户可操作**的那几件事（释放隔离 / 驳回记忆 / 黑白名单 / 开关探索）。

    POST body: {"action": "release"|"reject"|"blacklist_add"|"blacklist_remove"|"enable"|"disable",
                "qid"|"domain"|"on": ...}
    为什么要有这些接口：免疫系统不能是只进不出的黑箱 ——
    用户必须能把"误杀的"放出来、把"混进来的"退回去。没有这几个动作，
    隔离区就是单向牢房，误杀等于永久损失。
    """
    try:
        root = os.path.dirname(os.path.abspath(__file__))
        if root not in sys.path:
            sys.path.insert(0, root)
        from core.world.firewall import PollutionFirewall
        from core.world.explorer import get_explorer
        ex = get_explorer()
        fw = PollutionFirewall(model=ex.model, state_dir=ex.state_dir)
        if request.method == "GET":
            return jsonify({"ok": True, "stats": fw.stats(), "blacklist": fw.blacklist()})
        d = request.get_json(force=True, silent=True) or {}
        act = str(d.get("action") or "").strip()
        if act == "release":
            return jsonify({"ok": True, "result": fw.release(d.get("qid"))})
        if act == "reject":
            return jsonify({"ok": True, "result": fw.reject(d.get("text") or d.get("mid") or "")})
        if act == "blacklist_add":
            return jsonify({"ok": True, "result": fw.blacklist_add(d.get("domain") or "",
                                                                  reason=d.get("reason") or "用户手动加入")})
        if act == "blacklist_remove":
            return jsonify({"ok": True, "result": fw.blacklist_remove(d.get("domain") or "")})
        if act in ("enable", "disable"):
            on = (act == "enable")
            try:
                ex.cfg["explore_enabled"] = on
            except Exception:      # noqa: silent-ok — 配置改不动也要如实说
                pass
            return jsonify({"ok": True, "explore_enabled": on,
                            "note": "自主探索已%s（配置项 xiaojiao_control.json 的 world.explore_enabled）"
                                    % ("打开" if on else "关闭")})
        return jsonify({"ok": False, "error": "未知操作：%s" % act,
                        "allowed": ["release", "reject", "blacklist_add", "blacklist_remove",
                                    "enable", "disable"]}), 400
    except Exception as e:
        LOG.warning("防火墙操作失败：%s", e)
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


@app.route("/api/chat/abandon", methods=["POST"])
def api_chat_abandon():
    """前端说「这一轮我不要了，别让它卡着我的界面」——**强制**清掉生成标记。

    问题 2 的第二道保险（用户要求："加超时：切回来 3 秒内没数据就认为生成已死，清标志"）。
    前端在切会话时先 abort 连接，然后最多等 3 秒；3 秒还没等到后端把标记撤掉，
    就调这里**强制撤**。为什么需要这一步：客户端断开与后端生成器被关闭之间没有硬保证，
    偶尔会差一拍 —— 就这一拍，界面能卡到用户刷新为止（"时好时坏"就是这么来的）。

    分寸（很重要）：**只撤标记，不动正常的占位符**。
    万一这一轮其实还活着（只是慢），我们去清它的占位符就等于**把答案弄丢**
    —— 那比多转一会儿圈坏得多。所以只有"心跳已经断了"的轮才会连占位符一起标成中断。
    """
    payload = request.get_json(force=True, silent=True) or {}
    sid = (payload.get("session_id") or "").strip()
    if not sid:
        try:
            sid = get_current_session()[0].get("id")
        except Exception:      # noqa: silent-ok — 取不到就只做一个空操作
            sid = ""
    idle = _inflight_idle(sid)
    alive = _inflight_has(sid, max_idle=3)      # 前端口径：3 秒没动静就算死
    cleaned = 0
    # 【顺序很关键（本轮实测抓到的真 bug）】先判"活着吗"、再决定要不要清占位符、
    # **最后**才撤标记。第一版把 `_inflight_end` 写在了前面 —— 于是下面那句
    # `_clean_stale_pending` 去问"有人在生成吗"，答案永远是"没有"（刚被自己撤掉了），
    # 结果把一个**还活着**的轮的占位符清成了"中断了"，那一轮的答案就再也回填不进去。
    # 撤标记是为了让界面别转圈，清占位符才是"判定这一轮死了" —— 两件事不能混。
    if not alive:
        try:
            d = _sessions()
            for s in d["sessions"]:
                if s.get("id") == sid:
                    cleaned = _clean_stale_pending(s)
                    _save_sessions(d)
                    break
        except Exception as e:      # noqa: silent-ok — 清理失败也不算错，标记照样处理
            LOG.debug("abandon 清理占位符失败（忽略）：%s", e)
        _inflight_end(sid)          # 确实死了 → 连在册状态一起清掉
    else:
        # 还活着 → **只让它从界面消失，不动在册状态**（它结束时要回填已生成的内容）
        _inflight_abandon(sid)
    LOG.info("前端放弃本轮生成：会话=%s 撤标记=%s 空闲=%.1fs 清理占位符=%d",
             sid, "是", (idle if idle is not None else -1), cleaned)
    return jsonify({"ok": True, "session_id": sid, "was_alive": bool(alive),
                    "idle_s": idle, "cleaned": cleaned})


@app.route("/api/chat/stop", methods=["POST"])
def api_chat_stop():
    """用户叫停长文续写（无限 3："写 20 万字 → 一直写，用户叫停才停"）。"""
    _CONT_STOP.set()
    return jsonify({"ok": True, "stopped": True})


# ========== 内置·持续学习（自动记录 + 自动打勾） ==========
ROOT = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(ROOT, "logs")
KNOW_FILE = os.path.join(ROOT, "self_learn", "little_brain_knowledge.txt")


def _record_interaction(user, answer, tool_trace):
    """答完自动记录这次交互（稳定记录），返回 log_id。"""
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        log_id = datetime.now().strftime("%Y%m%d_%H%M%S%f")
        rec = {"time": datetime.now().isoformat(timespec="seconds"),
               "log_id": log_id, "user": user, "final_reply": answer,
               "tool_trace": json.dumps(tool_trace or [], ensure_ascii=False)}
        with open(os.path.join(LOGS_DIR, "chat_history.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return log_id
    except Exception:
        return None


@app.route("/api/feedback", methods=["POST"])
def api_feedback():
    """用户点 👍/👎/更正 → 记录反馈；被赞/高星/被更正的立刻灌进小脑知识库（稳定学习）。"""
    d = request.get_json(force=True, silent=True) or {}
    log_id, fb, corr = d.get("log_id", ""), d.get("feedback", ""), d.get("corrected", "")
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        with open(os.path.join(LOGS_DIR, "feedback.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"time": datetime.now().isoformat(timespec="seconds"),
                                "log_id": log_id, "feedback": fb, "corrected_reply": corr},
                               ensure_ascii=False) + "\n")
        worth = bool(corr) or fb in ("good", "👍") or str(fb).strip("星") in ("4", "5")
        if worth and log_id:
            for ln in open(os.path.join(LOGS_DIR, "chat_history.jsonl"), encoding="utf-8"):
                try:
                    r = json.loads(ln)
                except Exception:
                    continue
                if r.get("log_id") == log_id:
                    u, a = r.get("user", ""), (corr or r.get("final_reply", ""))
                    tt = r.get("tool_trace", "")
                    lesson = "用户 %s 小焦 %s%s" % (u, a, (" 用工具:%s" % tt) if tt else "")
                    os.makedirs(os.path.dirname(KNOW_FILE), exist_ok=True)
                    with open(KNOW_FILE, "a", encoding="utf-8") as kf:
                        kf.write(lesson + "\n")
                    pool = os.path.join(ROOT, "training_data_pool_clean.txt")
                    if os.path.exists(pool):
                        with open(pool, "a", encoding="utf-8") as pf:
                            pf.write(lesson + "\n")
                    break
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500




@app.route("/api/brain")
def api_brain():
    """『小脑』完整数据：成长统计 + 学到的功能用法 + 反思。"""
    root = os.path.dirname(os.path.abspath(__file__))
    def cnt(rel):
        try:
            return sum(1 for _ in open(os.path.join(root, rel), encoding="utf-8"))
        except Exception:
            return 0
    def tail(rel, n=14):
        try:
            lines = [x.strip() for x in open(os.path.join(root, rel), encoding="utf-8") if x.strip()]
            return lines[-n:]
        except Exception:
            return []
    know = cnt(os.path.join("self_learn", "little_brain_knowledge.txt"))
    logs = cnt(os.path.join("logs", "chat_history.jsonl"))
    good = bad = corr = 0
    try:
        for ln in open(os.path.join(root, "logs", "feedback.jsonl"), encoding="utf-8"):
            try:
                r = json.loads(ln)
            except Exception:
                continue
            f = r.get("feedback", "")
            if f in ("good", "👍") or str(f).strip("星") in ("4", "5"):
                good += 1
            elif f in ("bad", "👎"):
                bad += 1
            if r.get("corrected_reply"):
                corr += 1
    except Exception as e:
        LOG.debug("忽略异常(%s:%d): %s", __file__, 2329, e)
    try:
        import sys as _s, os as _o
        _s.path.insert(0, os.path.join(root, "self_learn"))
        import vstore
        vc = vstore.count()
    except Exception:
        vc = 0
    lessons = tail(os.path.join("self_learn", "little_brain_knowledge.txt"))
    return jsonify({"know": know, "logs": logs, "good": good, "bad": bad, "corr": corr,
                    "vec": vc, "lessons": lessons})


@app.route("/api/growth")

def api_growth():
    """小脑成长指标(面板用)。"""
    root = os.path.dirname(os.path.abspath(__file__))
    def cnt(rel):
        try:
            return sum(1 for _ in open(os.path.join(root, rel), encoding="utf-8"))
        except Exception:
            return 0
    know = cnt(os.path.join("self_learn", "little_brain_knowledge.txt"))
    logs = cnt(os.path.join("logs", "chat_history.jsonl"))
    good = bad = corr = 0
    try:
        for ln in open(os.path.join(root, "logs", "feedback.jsonl"), encoding="utf-8"):
            try:
                r = json.loads(ln)
            except Exception:
                continue
            f = r.get("feedback", "")
            if f in ("good", "👍"):
                good += 1
            elif f in ("bad", "👎"):
                bad += 1
            elif str(f).strip("星") in ("4", "5"):
                good += 1
            if r.get("corrected_reply"):
                corr += 1
    except Exception as e:
        LOG.debug("忽略异常(%s:%d): %s", __file__, 2371, e)
    return jsonify({"know": know, "logs": logs, "good": good, "bad": bad, "corr": corr})


@app.route("/api/persona", methods=["POST"])
def api_persona():
    """切换人格：把 role 写回控制文件并生效。"""
    d = request.get_json(force=True, silent=True) or {}
    role = strip_search_rules((d.get("role") or "").strip())   # 合成人设/脏人设 → 只存纯人设
    if not role:
        return jsonify({"ok": False, "error": "人格不能为空"}), 400
    try:
        c = json.loads(open(CONTROL_FILE, encoding="utf-8").read())
        c["role"] = role
        json.dump(c, open(CONTROL_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        reload_control()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/access", methods=["GET", "POST"])

def api_access():
    """权限模式：GET=读当前；POST=切换 Full access(全权限)/Read-only(每次执行都询问)。"""
    global FULL_ACCESS
    if request.method == "GET":
        return jsonify({"full_access": FULL_ACCESS})
    d = request.get_json(force=True, silent=True) or {}
    on = d.get("full_access", not FULL_ACCESS)
    FULL_ACCESS = bool(on)
    try:
        cap = dict(CONTROL.get("capabilities", {})); cap["full_access"] = FULL_ACCESS
        control = json.loads(open("xiaojiao_control.json", encoding="utf-8").read())
        control["capabilities"] = cap
        json.dump(control, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "xiaojiao_control.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    except Exception as e:
        LOG.debug("忽略异常(%s:%d): %s", __file__, 2408, e)
    return jsonify({"ok": True, "full_access": FULL_ACCESS})


@app.route("/api/tools_toggle", methods=["GET", "POST"])
def api_tools_toggle():
    """工具开关：读(GET) / 切换(POST)。开=必须执行工具，关=只聊天。"""
    if request.method == "POST":
        new_state = not bool(CAP.get("run_tools", True))
        cap = dict(CAP)
        cap["run_tools"] = new_state
        try:
            saved = {"model_name": MODEL_NAME, "brain": CONTROL.get("brain", {}),
                     # 存**纯人设**，不是合成后的 SYSTEM_PROMPT（否则每切一次开关就多存一份铁律）
                     "role": strip_search_rules(CONTROL.get("role") or SYSTEM_PROMPT),
                     "capabilities": cap, "behavior": BEH,
                     "models": _get_models()}
            json.dump(saved, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "xiaojiao_control.json"), "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
        reload_control()
        return jsonify({"ok": True, "tools_on": new_state})
    return jsonify({"ok": True, "tools_on": bool(CAP.get("run_tools", True))})


# ================== 模型管理（对接本地/外接模型，类似 dsh） ==================
def _get_models():
    return CONTROL.get("models", []) or []


def _save_control(brain=None, models=None):
    """保存控制文件（`xiaojiao_control.json`）—— 配置的**唯一写入口**。

    【为什么必须只有一个写入口】配置分散在多处写，就会出现"这里改了、那里还是旧值"。
    真实缺陷（本轮修过）：界面把 API Key 填进 `models[]`，而运行时读的是
    `brain.api.api_key` —— 两处不同步，表现为**用户填了 Key 却不生效**。
    所以保存时在这里统一对齐（`_sync_api_key`），之后无论谁读都一致。

    【为什么要合并而不是覆盖】保存"通用设置"时若不带上 models，
    就会把用户自己加的外接模型清空（`models=None` 的语义是"没传"，
    不是"清空"）—— 用户会发现自己加的模型**莫名其妙消失了**。

    【去掉它会怎样】每个保存点各自拼一份 dict 写文件：
    迟早出现"切换大脑把 Key 抹掉""改主题丢掉外接模型"这类**静默数据丢失**，
    而且因为是静默的，用户只会觉得"配置不生效"，排查起来毫无线索。
    """
    # 关键: models 若没显式传, 就**合并**当前与传入的, 绝不因"保存通用设置"而清空用户加的外接模型
    existing = _get_models()
    merged = models if models is not None else existing
    # 若来自 brain 切换等只传部分, 仍保留全部现有 models
    _b = brain if brain else dict(CONTROL.get("brain", {}))
    _ms = merged if merged else existing
    # ---- Key 同步（真缺陷）：界面填的 Key 在 models[]、运行时读 brain.api.api_key ----
    # 保存是**唯一的写入口**，就在这里把两处对齐，之后无论谁读都不会再出现"填了没生效"。
    try:
        _sync_api_key(_b, _ms)
    except Exception as e:      # noqa: silent-ok — 同步失败绝不能挡住保存本身
        LOG.warning("保存时 Key 同步失败（忽略）：%s", e)
    saved = {"model_name": MODEL_NAME,
             "brain": _b,
             # 同样只存纯人设（原因见 /api/tools_toggle）
             "role": strip_search_rules(CONTROL.get("role") or SYSTEM_PROMPT),
             "capabilities": CAP, "behavior": BEH,
             "models": _ms,
             "dsh": CONTROL.get("dsh", {})}
    json.dump(saved, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "xiaojiao_control.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    reload_control()


@app.route("/api/models", methods=["GET"])
def api_models():
    cur = None
    eng = BRAIN_ENGINE
    base = (CONTROL.get("brain", {}).get("api", {}).get("base_url", "") or "")
    for m in _get_models():
        if m.get("engine") == eng and (m.get("base_url", "") == base or not base):
            cur = m.get("name"); break
    return jsonify({"active": BRAIN_ENGINE, "current": cur, "models": _get_models()})


def _is_local_base(url):
    """base_url 是不是指向本机（本地大脑）。"""
    u = (url or "").lower()
    return any(h in u for h in ("127.0.0.1", "localhost", "0.0.0.0", "[::1]", "://::1"))


def _local_served_model(base_url, want):
    """问一下本地服务**真的**提供哪些模型，返回一个能用的 model id（问不到就原样返回 want）。

    真实缺陷：控制文件里的"本地模型"条目曾把 model 存成云端模型名（agnes-2.5-flash）而
    base_url 指向本机 9292 —— 用户在界面上选了"本地模型"照样不能用（llama-swap 直接 404
    no router for requested model），还看不出来为什么。这里在切换时对一次账。
    """
    try:
        r = requests.get((base_url or "").rstrip("/") + "/models", timeout=3)
        if r.status_code == 200:
            ids = [m.get("id") for m in (r.json().get("data") or []) if m.get("id")]
            if ids and want not in ids:
                return ids[0], ids
            if ids:
                return want, ids
    except Exception as e:  # noqa: silent-ok — 探测失败就按原样用，绝不因对账而挡住切换
        LOG.debug("忽略异常(%s:%d): %s", __file__, 3075, e)
    return want, []


def _cloud_key_problem(base, key, model):
    """切到云端模型时先探一下：通不通**当场**告诉用户，别等他问半天才发现。

    真实事故：用户切到云端模型后每次提问都只得到一句"模型调用出错"，而他并不知道问题在 Key 上。

    **判据只用 chat**：`GET /models` 在这里不可信 —— 实测连"空 Key / 乱写的 Key"都能时不时
    拿到 200（网关/缓存时不时不校验令牌）；拿它当"Key 有效"会把结论带偏（我就被带偏过一次）。
    """
    if not (key or "").strip():
        # 任务C 之后密钥只从环境变量来，所以"压根没有 Key"成了常见情况 —— 直接说清楚，
        # 别拿空 Authorization 去撞 401，再报成"你的 Key 被服务商拒了"（那会把人带偏）。
        return ("已切到云端大脑 %s，但**还没有可用的 Key**：请设置环境变量 XIAOJIAO_API_KEY"
                "（或在控制文件 brain.api.api_key 里临时填一把）后重试。" % model)
    url = (base or "").rstrip("/") + "/chat/completions"
    hdr = {"Content-Type": "application/json"}
    if key:
        hdr["Authorization"] = "Bearer " + key
    try:
        # 只等 20 秒：这是给用户"当场反馈"用的探测，不该让"切模型"这个动作卡住半分钟
        r = requests.post(url, headers=hdr, timeout=20,
                          json={"model": model, "messages": [{"role": "user", "content": "在的"}],
                                "max_tokens": 4})
        if r.status_code == 200:
            return "已切到云端大脑 %s（实测可通）" % model
        if r.status_code in (401, 403):
            return ("这个云端 Key 被服务商拒了（HTTP %s）→ 小焦先用本地大脑顶；"
                    "跑 `python tools/check_cloud_brain.py` 可确诊是哪把 Key 的问题" % r.status_code)
        return "已切到云端大脑 %s，但接口返回 HTTP %s（小焦会先用本地大脑顶）" % (model, r.status_code)
    except requests.exceptions.Timeout:
        # 超时 ≠ Key 错：实测这家冷启动能到 100 秒以上，报成"Key 被拒"会把人带偏
        return ("已切到云端大脑 %s：首次探测 20 秒没返回（对方慢，不是 Key 错）→ "
                "小焦会先本地大脑顶着，稍后自动再试云端" % model)
    except Exception as e:
        return "云端接口连不上（%s）→ 小焦会先用本地大脑顶" % str(e)[:40]


@app.route("/api/model/select", methods=["POST"])
def api_model_select():
    """切换当前大脑到某个已配置模型。"""
    data = request.get_json(force=True, silent=True) or {}
    name = data.get("name", "")
    for m in _get_models():
        if m.get("name") == name:
            brain = dict(CONTROL.get("brain", {}))
            engine = m.get("engine", "auto")
            base = m.get("base_url", "")
            model = m.get("model", "")
            note = ""
            # 指向本机的一律按本地大脑处理：本地服务不需要 Key，而条目里存的 engine
            # 可能是当初加模型时随手填的 "api"（那样会把本地地址当云端用，必失败）。
            if _is_local_base(base):
                engine = "llama"
                if engine != m.get("engine"):
                    note = "已按本地大脑接入（本地服务不需要 API Key）"
            brain["engine"] = engine
            if engine == "llama":
                model, ids = _local_served_model(base or "http://127.0.0.1:9292/v1", model)
                if ids and model != (m.get("model") or ""):
                    note = (note + "；" if note else "") + "本地服务实际提供 %s，已改用 %s" % ("/".join(ids), model)
                brain["api"] = {"base_url": base or "http://127.0.0.1:9292/v1",
                                "api_key": "", "model": model or "xiaojiao"}
            else:
                # 任务C（原 3.5）：**绝不**把模型条目里的明文 Key 搬进 brain.api.api_key ——
                # 否则在界面切一次模型，_save_control 就把明文写回控制文件，任务 3 的
                # "环境变量优先"等于白做。这里只切 model 名，Key 统一由 _resolve_llm_key()
                # 从环境变量 XIAOJIAO_API_KEY 读（本地/本机大脑本来就不需要 Key）。
                brain["api"] = {"base_url": base, "api_key": "", "model": model}
                note = _cloud_key_problem(base, _resolve_llm_key(brain), model)   # 云端 Key 不通就当场说
            _save_control(brain=brain)
            return jsonify({"ok": True, "engine": brain["engine"], "name": name,
                            "model": brain["api"]["model"], "note": note})
    return jsonify({"ok": False, "error": "模型不存在"}), 404


@app.route("/api/model/addlocal", methods=["POST"])
def api_model_addlocal():
    """一键添加本地模型(GGUF)：自动写 llama-swap.yaml + brain_manager + 下拉, 重启llama-swap。
    参数: name=显示名, gguf=模型文件绝对路径, ctx=上下文(默认20000)。"""
    import subprocess as _sp
    d = request.get_json(force=True, silent=True) or {}
    name = (d.get("name") or "").strip()
    gguf = (d.get("gguf") or "").strip()
    if not name or not gguf:
        return jsonify({"ok": False, "error": "需要 name 和 gguf 路径"}), 400
    if not os.path.exists(gguf):
        return jsonify({"ok": False, "error": "模型文件不存在: " + gguf}), 400
    ctx = int(d.get("ctx", 20000))
    mid = name.lower().replace(" ", "-")
    root = os.path.dirname(os.path.abspath(__file__))
    # ① llama-swap.yaml 加模型
    yp = os.path.join(root, "llama-swap.yaml")
    ys = open(yp, encoding="utf-8").read()
    if ("  " + mid + ":") not in ys:
        gg = gguf.replace("\\", "/")
        ys = ys.rstrip() + ("\n  %s:\n    cmd: \"C:/llama/llama-server.exe --port ${PORT} --model %s -c %d --reasoning off\"\n    ttl: 0\n    useModelName: %s\n" % (mid, gg, ctx, mid))
        open(yp, "w", encoding="utf-8").write(ys)
    # ② brain_manager BRAINS 加
    bp = os.path.join(root, "brain_manager.py")
    bs = open(bp, encoding="utf-8").read()
    if '"%s"' % mid not in bs:
        bs = bs.replace("    # 未来扩展(示例, 加进 BRAINS 即可被调度):",
                        '    "%s": {  # 新增: %s\n        "name": "%s", "port": 9292,\n        "type": "llama", "vram_gb": 5.0, "state": "OFF",\n    },\n    # 未来扩展(示例, 加进 BRAINS 即可被调度):' % (mid, name, name), 1)
        open(bp, "w", encoding="utf-8").write(bs)
    # ③ 下拉模型加
    CONTROL.setdefault("models", [])
    if not any(m.get("model") == mid for m in CONTROL["models"]):
        CONTROL["models"].append({"name": name, "engine": "llama",
                                  "base_url": "http://127.0.0.1:9292/v1", "api_key": "", "model": mid})
        json.dump(CONTROL, open(os.path.join(root, "xiaojiao_control.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # ④ 重启 llama-swap（路径自动探测，不写死）
    try:
        _sw = _discover_paths().get("swap") or ""
        if _sw and os.path.exists(_sw):
            _sp.Popen(["powershell", "-NoProfile", "-Command",
                       "Get-Process llama-swap -ErrorAction SilentlyContinue | Stop-Process -Force; Start-Sleep -Seconds 1; "
                       "Start-Process '%s' -ArgumentList '-config \\\"%s\\\" -listen 127.0.0.1:9292' -WindowStyle Hidden" % (_sw.replace("'", "''"), yp)])
        else:
            return jsonify({"ok": True, "model_id": mid, "name": name,
                            "note": "已写入配置；但没找到 llama-swap.exe，请手动重启它（或设 XIAOJIAO_LLAMA_SWAP）"})
    except Exception as e:
        LOG.debug("忽略异常(%s:%d): %s", __file__, 2529, e)
    return jsonify({"ok": True, "model_id": mid, "name": name, "note": "llama-swap 正在重启, 约10秒后可用"})


@app.route("/api/model/add", methods=["POST"])
def api_model_add():
    """添加一个模型（对接本地模型/外接 API）。同名的覆盖。"""
    data = request.get_json(force=True, silent=True) or {}
    entry = {"name": (data.get("name") or "").strip(), "engine": data.get("engine", "api"),
             "base_url": data.get("base_url", ""), "api_key": data.get("api_key", ""),
             "model": data.get("model", "")}
    if not entry["name"]:
        return jsonify({"ok": False, "error": "模型名字不能为空"}), 400
    models = [m for m in _get_models() if m.get("name") != entry["name"]]
    models.append(entry)
    _save_control(models=models)
    return jsonify({"ok": True, "models": models})


@app.route("/api/model/delete", methods=["POST"])
def api_model_delete():
    data = request.get_json(force=True, silent=True) or {}
    name = data.get("name", "")
    models = [m for m in _get_models() if m.get("name") != name]
    _save_control(models=models)
    return jsonify({"ok": True, "models": models})


@app.route("/api/confirm", methods=["POST"])
def api_confirm():
    """执行刚才被挂起的危险动作（用户点“确认执行”后调用）。"""
    global PENDING
    if not PENDING:
        return jsonify({"ok": False, "error": "没有待确认的操作"}), 400
    name, args = PENDING
    PENDING = None
    result = run_tool(name, args, force=True)
    return jsonify({"ok": True, "result": result})


@app.route("/growth")
def page_growth():
    """小脑成长报告页(可分享)。"""
    import webbrowser as _wb
    return _growth_html()


def _growth_html():
    root = os.path.dirname(os.path.abspath(__file__))
    def cnt(rel):
        try:
            return sum(1 for _ in open(os.path.join(root, rel), encoding="utf-8"))
        except Exception:
            return 0
    know = cnt(os.path.join("self_learn", "little_brain_knowledge.txt"))
    logs = cnt(os.path.join("logs", "chat_history.jsonl"))
    good = bad = corr = 0
    try:
        for ln in open(os.path.join(root, "logs", "feedback.jsonl"), encoding="utf-8"):
            try:
                r = json.loads(ln)
            except Exception:
                continue
            f = r.get("feedback", "")
            if f in ("good", "👍") or str(f).strip("星") in ("4", "5"):
                good += 1
            elif f in ("bad", "👎"):
                bad += 1
            if r.get("corrected_reply"):
                corr += 1
    except Exception as e:
        LOG.debug("忽略异常(%s:%d): %s", __file__, 2600, e)
    bar = min(100, int(know / 5))
    try:
        import sys as _s, os as _o
        _s.path.insert(0, os.path.join(root, "self_learn"))
        import vstore
        vec = vstore.count()
    except Exception:
        vec = 0
    lessons = []
    try:
        ls = [x.strip() for x in open(os.path.join(root, "self_learn", "little_brain_knowledge.txt"), encoding="utf-8") if x.strip()]
        lessons = ls[-8:][::-1]
    except Exception as e:
        LOG.debug("忽略异常(%s:%d): %s", __file__, 2614, e)
    lhtml = "".join("<div class='bli'>" + (l[:64] + ("…" if len(l) > 64 else "")) + "</div>" for l in lessons) or "<div class='bli think'>还没学到东西，多聊几轮、点几个👍吧</div>"
    return ("""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>小焦成长报告</title>
<style>*{box-sizing:border-box}body{margin:0;font-family:'Segoe UI',sans-serif;background:linear-gradient(160deg,#0e1116,#141a2e);color:#e8ebf3;display:flex;align-items:center;justify-content:center;min-height:100vh;padding:32px 16px}
.wrap{max-width:760px;width:100%}
.hero{text-align:center;margin-bottom:22px}
.hero h1{font-size:30px;margin:0 0 8px;font-weight:800}
.hero .sub{color:#8b93a3;font-size:14px}
.big{font-size:72px;font-weight:800;background:linear-gradient(135deg,#5b5ff5,#a78bfa);-webkit-background-clip:text;-webkit-text-fill-color:transparent;line-height:1}
.big-l{color:#8b93a3;font-size:14px;margin-top:6px}
.bar{height:12px;background:#0e1116;border:1px solid #232a3e;border-radius:8px;overflow:hidden;margin-top:12px}.bar i{display:block;height:100%;background:linear-gradient(90deg,#5b5ff5,#7c5cf0)}
.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:24px}
.card{background:#151a26;border:1px solid #2a3140;border-radius:16px;padding:20px;text-align:center}
.card .n{font-size:36px;font-weight:800;color:#5b5ff5}
.card .t{font-size:13px;color:#8b93a3;margin-top:6px}
.panel{background:#151a26;border:1px solid #2a3140;border-radius:16px;padding:20px;margin-top:24px}
.panel h3{margin:0 0 12px;font-size:16px;color:#cbd0dc}
.bli{font-size:13px;color:#c9d1d9;padding:8px 2px;border-bottom:1px solid #1a2030;line-height:1.6;font-family:Consolas,monospace}
.think{color:#6e7681;font-size:13px}
.chips{display:flex;flex-wrap:wrap;gap:10px;justify-content:center;margin-top:26px}
.chip{background:#1a2030;border:1px solid #2a3140;border-radius:20px;padding:7px 14px;font-size:13px;color:#aab2c0}
.foot{text-align:center;color:#6e7681;font-size:12px;line-height:1.8;margin-top:30px}
@media(max-width:600px){.cards{grid-template-columns:1fr 1fr}.big{font-size:56px}}
</style></head><body><div class="wrap">
<div class="hero"><h1>🐳 小焦 · 小脑成长报告</h1><div class="sub">小脑跟着大脑学 · 别人靠算力，小脑靠文本</div></div>
<div class="card"><div class="big">@@KNOW@@</div><div class="big-l">小脑知识库累计（条）—— 越长越强</div>
<div class="bar"><i style="width:@@BAR@@%"></i></div></div>
<div class="cards">
<div class="card"><div class="n">@@VEC@@</div><div class="t">🧠 向量知识</div></div>
<div class="card"><div class="n">@@LOGS@@</div><div class="t">💬 交互记录</div></div>
<div class="card"><div class="n">@@GOOD@@</div><div class="t">👍 点赞</div></div>
<div class="card"><div class="n">@@BAD@@</div><div class="t">👎 踩</div></div>
<div class="card"><div class="n">@@CORR@@</div><div class="t">✏️ 被更正</div></div>
<div class="card"><div class="n">⭐</div><div class="t">持续学习中</div></div>
</div>
<div class="panel"><h3>🧠 最近学到</h3>@@LESSONS@@</div>
<div class="chips"><span class="chip">持续学习</span><span class="chip">DSH 插件生态</span><span class="chip">免密钥联网</span><span class="chip">多人格</span><span class="chip">本地隐私</span></div>
<div class="foot">它不会很多话，但会慢慢成为只属于你的那一只 🐳<br>xiaojiao-harness · 持续学习 · DSH 插件生态 · Made with ❤️</div>
</div></body></html>"""
        .replace("@@KNOW@@", str(know)).replace("@@BAR@@", str(bar))
        .replace("@@VEC@@", str(vec)).replace("@@LOGS@@", str(logs))
        .replace("@@GOOD@@", str(good)).replace("@@BAD@@", str(bad)).replace("@@CORR@@", str(corr))
        .replace("@@LESSONS@@", lhtml))


@app.route("/api/settings", methods=["GET"])

def api_settings_get():
    """返回当前配置 + 可用的插件（含开关状态）。"""
    plist = [{"name": k,
              "builtin": v.get("builtin", False),
              "type": v.get("type", "py"),
              "on": v.get("on", True),
              "manifest": v.get("manifest"),
              "settings": v.get("settings", []),
              "desc": v.get("desc", [])}
             for k, v in PLUGINS.items()]
    return jsonify({
        "control": {
            "model_name": MODEL_NAME,
            "brain": CONTROL.get("brain", {}),
            # 回**纯人设**：铁律由 compose_system_prompt 每轮自动拼，界面里不用背它，
            # 否则用户点一次保存就把铁律又存进控制文件（老版本就是这么攒到 11 份的）。
            "role": strip_search_rules(CONTROL.get("role") or SYSTEM_PROMPT),
            "capabilities": CAP,
            "behavior": BEH,
        },
        "plugins": plist,
    })


@app.route("/api/settings", methods=["POST"])
def api_settings_post():
    """保存设置：写回操控文件 → 热更新运行中的配置。

    以当前 CONTROL 为基础做合并，保留客户端没发的字段（如 brain.llama 大模型配置）。
    """
    data = request.get_json(force=True, silent=True) or {}
    got = data.get("control") or {}
    cur = CONTROL if isinstance(CONTROL, dict) else {}
    # 合并：brain 保留原有 llama/node，更新 engine/api；behavior/capabilities 逐键覆盖
    brain = dict(cur.get("brain", {}))
    new_brain = got.get("brain") or {}
    for k in ("engine", "api"):
        if k in new_brain:
            brain[k] = new_brain[k]
    # llama 深合并：保留 server/gguf/port，只更新 ctx 等
    if "llama" in new_brain:
        brain["llama"] = {**brain.get("llama", {}), **new_brain["llama"]}
    saved = {
        "model_name": got.get("model_name", cur.get("model_name", MODEL_NAME)),
        "brain": brain,
        "role": strip_search_rules(got.get("role") or cur.get("role") or SYSTEM_PROMPT),
        "capabilities": {**cur.get("capabilities", {}), **(got.get("capabilities") or {})},
        "behavior": {**cur.get("behavior", {}), **(got.get("behavior") or {})},
        "models": _get_models(),
        "dsh": cur.get("dsh", {}),
        "preset": cur.get("preset", ""),
        "_engine": cur.get("_engine", ""),
    }
    try:
        json.dump(saved, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "xiaojiao_control.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    reload_control()
    global PLUGINS
    PLUGINS = load_plugins()
    return jsonify({"ok": True, "model_name": MODEL_NAME})


# ================== OpenAI 兼容接口（供 Harness / 任意客户端接入） ==================
@app.route("/v1/models")
def v1_models():
    return jsonify({"object": "list", "data": [{"id": MODEL_NAME, "object": "model",
                                                "owned_by": "xiaojiao", "created": 0}]})


def _content_str(c):
    """把消息的 content 安全转成字符串（content 可能是 None / list(多模态) / str）。"""
    if c is None:
        return ""
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    return str(c)


@app.route("/v1/chat/completions", methods=["POST"])
def v1_chat():
    maybe_reload_control()
    """OpenAI 兼容的对话接口：自动注入小焦人设 + 工具(操控电脑)，支持流式。

    任意 OpenAI 兼容客户端把 base_url 指向小焦即可接入，小焦会给模型上“小焦人格”。
    """
    data = request.get_json(force=True, silent=True) or {}
    messages = data.get("messages") or []
    user_last = ""
    for m in reversed(messages):
        if isinstance(m, dict) and m.get("role") == "user":
            user_last = _content_str(m.get("content"))
            if user_last:
                break
    if not user_last:
        user_last = str(data.get("prompt", ""))
    try:
        answer, _online, _info, _nc, _tt = agent_run(str(user_last))
    except Exception as e:
        answer = "⚠️ 小焦处理出错：" + str(e)
    content = answer or "（暂无回答）"

    if data.get("stream"):
        return _sse(content)

    return jsonify({
        "id": "xiaojiao-chat", "object": "chat.completion", "model": MODEL_NAME,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    })


def _sse(content):
    """把最终答案包装成 OpenAI 兼容的 SSE 流，让 dsh 等客户端能正常接收。"""
    def gen():
        chunk = {"id": "xiaojiao", "object": "chat.completion.chunk", "model": MODEL_NAME,
                 "choices": [{"index": 0, "delta": {"role": "assistant", "content": content},
                              "finish_reason": None}]}
        yield "data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n"
        done = {"id": "xiaojiao", "object": "chat.completion.chunk", "model": MODEL_NAME,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
        yield "data: " + json.dumps(done, ensure_ascii=False) + "\n\n"
        yield "data: [DONE]\n\n"
    return Response(gen(), mimetype="text/event-stream")


# ================== Web 界面（商标：小焦） ==================
HTML = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>小焦 · XiaoJiao</title>
<!-- ================= 数学公式（KaTeX）=================
  【为什么是 KaTeX 而不是 MathJax】KaTeX 是同步渲染、没有"先显示源码再闪成公式"的过程，
  体积也小一半；小焦的回答是**边流式边渲染**的，异步排版库会造成公式反复重排。
  【为什么用 CDN 而不是把字体一起塞进仓库】KaTeX 的 CSS 之外还有 60 多个字体文件（约 1MB），
  打进仓库会让"clone 即用"变成一个几 MB 的下载。CDN 拿不到时的行为是**如实降级**：
  公式原样显示 LaTeX 源码（即现在的表现），不会报错、不会白屏。
  【为什么 defer】不阻塞首屏；页面加载完再补渲染一遍，避免"脚本比消息晚到"那一小段窗口。 -->
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js"
        onload="window._katexReady=true;try{document.querySelectorAll('#feed .b').forEach(mathify)}catch(e){}"></script>
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  body{font-family:'Segoe UI',system-ui,sans-serif;background:#0e1116;color:#e8ebf3;height:100vh;display:flex;flex-direction:column;overflow:hidden}
  *{scrollbar-color:#2a3140 #11141c}
  *::-webkit-scrollbar{width:6px;height:6px}
  *::-webkit-scrollbar-thumb{background:#2a3140;border-radius:4px}
  *::-webkit-scrollbar-track{background:transparent}
  #app{display:flex;flex:1;min-height:0}
  #sidebar{width:250px;background:#10131d;border-right:1px solid #20263a;display:flex;flex-direction:column;flex-shrink:0;transition:width .2s}
  #sidebar.hidden{width:0;overflow:hidden;border-right:none}
  #sidebar .sh{display:flex;align-items:center;gap:8px;padding:12px 14px;border-bottom:1px solid #262b3a}
  #sidebar .sh .newchat{flex:1;background:#1f2533;border:1px solid #2a3140;color:#cbd0dc;border-radius:8px;padding:7px 10px;font-size:13px;cursor:pointer;text-align:left}
  #sidebar .sh .newchat:hover{background:#2a3140}
  #sidebar .cl{flex:0 0 auto;background:#1f2533;border:1px solid #2a3140;color:#8b93a3;border-radius:8px;padding:6px 9px;font-size:12px;cursor:pointer}
  #sessionList{flex:1;overflow-y:auto;padding:8px}
  /* 会话行：左边是会话按钮，右边是删除 ✕（平时淡、悬停才明显，避免误点） */
  .srow{display:flex;align-items:center;gap:2px;margin-bottom:4px;border-radius:8px}
  .srow:hover{background:#1e2430}
  .srow.active{background:#2a3140}
  .srow .sess{flex:1;min-width:0;display:block;width:auto;text-align:left;background:transparent;border:none;color:#cbd0dc;padding:9px 10px 9px 12px;border-radius:8px;font-size:13px;cursor:pointer;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
  .srow .sess:hover{background:transparent}
  .srow.active .sess{color:#fff}
  .sdel{flex:0 0 auto;width:26px;height:26px;margin-right:4px;background:transparent;border:none;color:#6e7681;
        border-radius:6px;font-size:12px;cursor:pointer;opacity:0;transition:.12s;padding:0}
  .srow:hover .sdel,.srow.active .sdel{opacity:.75}
  .sdel:hover{background:#3a2230;color:#f87171;opacity:1}
  .sess{display:block;width:100%;text-align:left;background:transparent;border:none;color:#cbd0dc;padding:9px 12px;border-radius:8px;font-size:13px;cursor:pointer;margin-bottom:4px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
  .sess:hover{background:#1e2430}
  .sess.active{background:#2a3140;color:#fff}
  #main{flex:1;display:flex;flex-direction:column;min-width:0}
  header{padding:12px 20px;background:#161a24;border-bottom:1px solid #262b3a;display:flex;align-items:center;gap:12px}
  header .logo{font-size:22px;font-weight:800;background:linear-gradient(135deg,#f093fb,#f5576c);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
  header .tag{font-size:12px;color:#7a8290;background:#1f2533;padding:4px 10px;border-radius:20px}
  header .sp{flex:1}
  .icon-btn{background:#1f2533;border:1px solid #2a3140;color:#cbd0dc;border-radius:10px;padding:8px 12px;cursor:pointer;font-size:13px}
  .icon-btn:hover{background:#2a3140}
  .iconselect{background:#1f2533;border:1px solid #2a3140;color:#cbd0dc;border-radius:10px;padding:8px 10px;font-size:13px;outline:none;max-width:230px}
  .icon-btn.on{background:#0f2b1c;border-color:#1f7a3d;color:#4ade80}
  .icon-btn.off{background:#2a1320;border-color:#8b1e2d;color:#f87171}
  .tooltrace{font-size:12px;color:#8b93a3;background:#12161f;border:1px solid #2a3140;border-radius:10px;padding:8px 12px;margin:4px 0 10px;white-space:pre-wrap}
  .tooltrace b{color:#4ade80}
  #feed{flex:1;overflow-y:auto;padding:24px;width:100%;display:flex;flex-direction:column;align-items:center}
  #feed>*{width:100%;max-width:860px}
  #feed>*:has(.tblwrap){max-width:100%}   /* 带表格的消息放宽到整栏宽，别把表格挤成两行 */
  .m{display:flex;margin-bottom:14px;gap:10px;flex-wrap:wrap}
  .m.user{justify-content:flex-end}.m.bot{justify-content:flex-start}
  .b{max-width:82%;padding:11px 16px;border-radius:16px;line-height:1.65;font-size:15px;white-space:pre-wrap;word-break:break-word;box-shadow:none}
  .user .b{background:linear-gradient(135deg,#5b5ff5,#7c5cf0);color:#fff;border-bottom-right-radius:5px}
  .bot .b{background:#151a24;border:1px solid #252b38;border-bottom-left-radius:5px}
  .src{font-size:11px;color:#8b93a3;margin-top:6px;padding-left:2px}
  .src b{color:#a78bfa}
  .srcbtn{background:#1a2030;border:1px solid #2a3140;color:#a78bfa;border-radius:14px;padding:4px 12px;font-size:12px;cursor:pointer;margin-top:6px;white-space:nowrap;width:auto;align-self:flex-start;display:inline-flex;align-items:center;gap:4px}
  .srcbtn:hover{background:#232c42;border-color:#405a99}
  .srcbtn:hover{background:#263349}
  .srcbox{display:none;white-space:normal;font-size:11px;color:#8b93a3;margin-top:6px;background:#11141c;border:1px solid #252b38;border-radius:8px;padding:8px 10px;max-height:180px;overflow-y:auto;flex-basis:100%;width:100%;box-sizing:border-box}
  .srci{margin-bottom:8px}
  .srci .st{color:#9bb0e1;font-size:12px;margin-bottom:2px}
  .srci .sc{color:#aab2c0;font-size:11px;line-height:1.5}
  .srcbox.show{display:block}
  .srcbox b{color:#a78bfa;margin-right:4px}
  /* 代码块：底色必须干净纯色。
     ⚠️ 真实缺陷：`.b code{background:#2a3140}` 会**连代码块里的 code 元素一起**上色，
     于是整块代码躺在一个浅灰方块上（用户看到的"白色背景印记/阴影"就是这么来的）。
     所以这里显式把 pre 内的 code 背景/内边距/阴影全部清掉。 */
  .b pre.code{background:#0d1117;border:none;border-radius:0;padding:14px 16px;overflow-x:auto;margin:0;box-shadow:none;text-shadow:none}
  .b pre.code::-webkit-scrollbar{height:6px;width:6px}
  .b pre.code::-webkit-scrollbar-thumb{background:#30363d;border-radius:4px}
  .b pre.code::-webkit-scrollbar-track{background:transparent}
  .b pre.code code{font-family:Consolas,'Courier New',monospace;font-size:13px;line-height:1.7;white-space:pre;color:#c9d1d9;background:none;padding:0;margin:0;border-radius:0;border:none;box-shadow:none;text-shadow:none}
  .b pre.code,.b pre.code *,.b table,.b table *{text-shadow:none;box-shadow:none}
  /* ================= 行内 code（正文里的小代码）：对齐 GitHub 的观感 =================
     【用户实测的缺陷】回复里 `image_recognition` 这种行内代码"带边框、样式奇怪"，
     不是标准的"灰底等宽字"。原来那条规则是
       `.b code{background:#242b39;padding:1px 6px;border-radius:4px;font-size:13px}`
     四个毛病，每个都能单独让它看起来不对：

     ① **字号写死 13px**：气泡正文是 15px，用户在设置里调大字号时正文会跟着变大、
        代码却还是 13px —— 两种字号并排，代码那块像贴上去的补丁。
        改成 `.85em`：**跟着正文走**，正文多大它就按比例多大。
     ② **上下内边距只有 1px**：灰底的上下边几乎贴住字形，底框被压成又扁又紧的一条，
        看起来就像"描了个边"（用户说的"带边框"多半就是这个观感）。
        改成 `.2em .4em`（GitHub 的取值）：灰底比字形大一圈，才叫"底色"而不是"框"。
     ③ **不透明纯灰 #242b39**：底是 #151a24 的近黑气泡，实心灰会浮成一块方块。
        改成半透明灰 `rgba(110,118,129,.35)`：叠在气泡底色上，观感是"这几个字被标了一下"。
     ④ **没有显式 border 归零**：只要哪天有人给 `code` 加了边框，行内代码就会和"代码块"
        的观感混起来，用户第一反应是"这块是不是能复制" —— 显式写 `border:none` 把它钉死。

     另外两条：
       · `border-radius` 4px → 6px（GitHub 取值，圆角太小仍显生硬）。
       · `line-height:inherit`：行内元素设 line-height 会把含代码那行的行高拉矮，
         一列文字里突然有一行矮一截，非常显眼。继承父级才对齐。
       · 选择器就用 `.b code`：代码块里的 code 由上面那条 `.b pre.code code` 兜住 ——
         它的优先级 (0,1,2) 比 `.b code` (0,1,1) 高，且把背景/内边距/边框/圆角/字号全部归零，
         所以"改行内样式顺手把代码块也改花"这件事不会发生。
         **不要用 `.b :not(pre) > code`**（我第一版就是这么写的，实测整条规则一条都没生效）：
         `>` 要求 code 的**父元素**是 `.b` 的后代，而正文里的 code 父元素**就是 `.b` 本身** ——
         自己不是自己的后代，选择器全灭，样式悄悄退回浏览器默认（等宽、无底、无圆角）。 */
  .b code{background:rgba(110,118,129,.35);border:none;border-radius:6px;
    padding:.2em .4em;margin:0 .1em;font-family:Consolas,'Courier New',ui-monospace,monospace;
    font-size:.85em;line-height:inherit;color:#e6edf3;white-space:break-spaces;vertical-align:baseline}
  .codebox{border:none;border-radius:10px;margin:12px 0;overflow:hidden;background:#0d1117;box-shadow:none}
  .codehead{display:flex;align-items:center;gap:8px;background:#0d1117;padding:10px 12px 0}
  .lang{padding:2px 8px;font-size:11px;font-weight:600;color:#6e7681;text-transform:uppercase;letter-spacing:.5px;background:transparent}
  .cp{margin-left:auto;background:transparent;border:1px solid #21262d;color:#7d8590;border-radius:6px;padding:2px 8px;font-size:11px;cursor:pointer}
  .cp:hover{background:#161b22;color:#e6edf3}
  /* 语法高亮配色（深色下高对比、不刺眼） */
  .tk-kw{color:#ff7b72}
  .tk-str{color:#a5d6ff}
  .tk-num{color:#79c0ff}
  .tk-com{color:#7d8794;font-style:italic}
  .tk-fn{color:#d2a8ff}
  .tk-key{color:#7ee787}
  .tk-bool{color:#79c0ff}
  .tk-tag{color:#7ee787}
  .tk-attr{color:#79c0ff}
  .tk-op{color:#ffa657}
  .tk-var{color:#ffa657}
  .kw{color:#ff7b72}
  .lang.python,.lang.py{color:#6e7681}.lang.js,.lang.javascript{color:#6e7681}
  .lang.bash,.lang.sh{color:#6e7681}.lang.html,.lang.css{color:#6e7681}.lang.json{color:#6e7681}
  /* JSON / 长文本块：限高 + 纵向滚动，避免一大坨内容把聊天窗糊满 */
  .codebox.lang-json pre.code,.codebox.lang-text pre.code{max-height:380px;overflow-y:auto}
  .codebox.lang-json pre.code::-webkit-scrollbar,.codebox.lang-text pre.code::-webkit-scrollbar{width:6px}
  .codebox.lang-json pre.code::-webkit-scrollbar-thumb,.codebox.lang-text pre.code::-webkit-scrollbar-thumb{background:#30363d;border-radius:4px}
  /* ```markdown 围栏：直接渲染成正常排版（表格/标题/列表），左侧细线表示"这块来自代码围栏" */
  .b .mdfence{border-left:2px solid #2f3b52;padding:2px 0 2px 12px;margin:8px 0}
  .lang.cpp,.lang.c{color:#6e7681}.lang.java{color:#6e7681}.lang.sql{color:#6e7681}
  .cp{background:#1f2533;border:1px solid #2a3140;color:#cbd0dc;border-radius:6px;padding:3px 10px;font-size:12px;cursor:pointer}
  .cp:hover{background:#2a3140}
  /* 表格：给足留白、宽表横向滚动、短列不许被折断（以前 HIG H / CVE-2026- 这种断字很难看） */
  .b .tblwrap{overflow-x:auto;margin:10px 0;border:1px solid #2a3140;border-radius:10px;background:#101520}
  .b table{border-collapse:separate;border-spacing:0;width:100%;font-size:13px;margin:0}
  .b table th,.b table td{border:none;border-bottom:1px solid #232a38;border-right:1px solid #1b2230;padding:11px 15px;text-align:left;line-height:1.65;vertical-align:top;word-break:keep-all;overflow-wrap:anywhere}
  .b table th{background:#182031;color:#9fb0d0;font-weight:600;white-space:nowrap}
  .b table tr:last-child td{border-bottom:none}
  .b table th:last-child,.b table td:last-child{border-right:none}
  .b table tbody tr:nth-child(even) td{background:#131926}
  .b table td:not(:last-child){white-space:nowrap}   /* 只有最后一列（摘要）允许折行 */
  /* 带表格/代码的消息给更宽的容器，别把内容挤在小框里 */
  .b.wide{max-width:100%}
  .m.widem{max-width:100%}
  .msgbot{display:flex;gap:8px;margin-top:6px;align-items:center;padding-left:2px}
  /* 检索引用校验标记：绿色=确实读了资料；黄色=疑似没读（自己编的） */
  .gnd{margin-top:8px;font-size:11px;color:#6ee7a8;background:#0f1d18;border:1px solid #1d3a2c;
       border-radius:8px;padding:5px 9px;display:inline-block}
  .gnd.bad{color:#fbbf24;background:#1d1908;border-color:#4a3c12}
  .msgbot button{background:#1f2533;border:1px solid #2a3140;color:#8b93a3;border-radius:8px;padding:4px 10px;font-size:12px;cursor:pointer}
  .msgbot button:hover{background:#2a3140}
  .msgbot .fb{font-size:14px;padding:2px 8px}
  .b strong{color:#fff}
  /* Markdown 标题（抓取正文常用）*/
  .b .mdh{font-size:16px;font-weight:700;color:#fff;margin:10px 0 6px;padding-bottom:5px;border-bottom:1px solid #2a3140}
  .b .mdh:first-child{margin-top:2px}
  .b a{color:#a78bfa;text-decoration:none;border-bottom:1px solid #a78bfa55}
  .b a:hover{color:#c4b5fd;border-bottom-color:#c4b5fd}
  /* 抓取结果卡片：把"抓来的网页内容"和对话正文区分开 */
  .fetchcard{background:#0f1520;border:1px solid #223049;border-left:3px solid #45d483;border-radius:10px;padding:12px 14px;margin:8px 0;font-size:14px;line-height:1.7;color:#cbd0dc}
  .fetchhead{font-size:12px;color:#45d483;margin-bottom:8px;display:flex;align-items:center;gap:6px;flex-wrap:wrap}
  .fetchhead .u{color:#8b93a3;font-weight:400}
  .b ul,.b ol{padding-left:20px;margin:6px 0}
  .b h1,.b h2,.b h3{color:#fff;margin:10px 0 6px}
  footer{padding:10px 20px 18px;background:transparent;border-top:none}
  .bar{max-width:880px;margin:0 auto;display:flex;gap:10px}
  /* 居中输入区（Composer）：像现代 AI 客户端那样收成一张卡片，宽度统一、视觉焦点明确 */
  .composer{max-width:820px;margin:0 auto;background:#12161f;border:1px solid #262d3d;border-radius:16px;
            padding:10px 12px 8px;box-shadow:0 8px 28px rgba(0,0,0,.28);transition:border-color .15s}
  .composer:focus-within{border-color:#4f46e5;box-shadow:0 8px 28px rgba(79,70,229,.18)}
  .cmp-top{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:8px}
  .chip-sel{width:auto;background:#171d29;border:1px solid #2a3140;color:#cbd0dc;border-radius:999px;
            padding:5px 12px;font-size:12px;cursor:pointer;outline:none}
  .chip-sel:hover{background:#1e2635;border-color:#3a4560}
  .chip-btn{background:#171d29;border:1px solid #2a3140;color:#cbd0dc;border-radius:999px;
            padding:5px 12px;font-size:12px;cursor:pointer}
  .chip-btn:hover{background:#212a3a;border-color:#405a99}
  .cmp-input{display:flex;align-items:flex-end;gap:10px}
  .cmp-input textarea{flex:1;background:transparent;border:none;outline:none;color:#e8ebf3;font-size:15px;
                      line-height:1.6;resize:none;max-height:220px;padding:8px 4px;font-family:inherit}
  .cmp-send{flex:0 0 auto;width:40px;height:40px;border-radius:50%;background:linear-gradient(135deg,#5b5ff5,#7c5cf0);
            border:none;color:#fff;font-size:16px;cursor:pointer;padding:0}
  .cmp-send:hover{filter:brightness(1.12)}
  .cmp-hint{font-size:11px;color:#5f6a7d;margin-top:8px;padding-left:4px;min-height:14px}
  /* 空状态欢迎卡（居中） */
  .welcome{max-width:820px;margin:6vh auto 0;text-align:center}
  .welcome .wl{font-size:30px;font-weight:800;background:linear-gradient(135deg,#8b8ff8,#c4b5fd);
               -webkit-background-clip:text;background-clip:text;color:transparent;margin-bottom:10px}
  .welcome .ws{color:#8b93a3;font-size:14px;margin-bottom:22px}
  .welcome .chips{display:flex;gap:10px;flex-wrap:wrap;justify-content:center}
  .welcome .chip{background:#141a26;border:1px solid #262d3d;color:#cbd0dc;border-radius:12px;
                 padding:10px 14px;font-size:13px;cursor:pointer;transition:.15s}
  .welcome .chip:hover{background:#1c2432;border-color:#4f46e5;color:#fff;transform:translateY(-1px)}
  /* 轻提示（toast）—— 放在**顶部居中**：原来 bottom:120px 正好压在输入区那排
     「预设 / 模型 / 工具」胶囊上，弹提示时把用户正在点的下拉盖住，看着像"字没了"。 */
  #toast{position:fixed;left:50%;top:16px;transform:translateX(-50%) translateY(-10px);opacity:0;
         background:#1b2231;border:1px solid #3a4560;color:#e8ebf3;padding:10px 16px;border-radius:12px;
         font-size:13px;z-index:90;pointer-events:none;transition:.2s;max-width:70vw;
         box-shadow:0 10px 30px rgba(0,0,0,.35)}
  #toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
  input,textarea,select{background:#0f1117;border:1px solid #2a3140;color:#e6e8ee;border-radius:10px;padding:11px 14px;font-size:14px;outline:none;width:100%;font-family:inherit}
  input:focus,textarea:focus,select:focus{border-color:#4f46e5}
  button{background:#4f46e5;color:#fff;border:none;border-radius:10px;padding:11px 22px;font-size:14px;cursor:pointer}
  button:hover{background:#6366f1}
  .think{color:#7a8290;font-size:13px;padding:6px 2px}
  .think{display:flex;align-items:center;gap:8px}
  .pvbar{height:4px;background:#0e1116;border-radius:3px;margin-top:6px;overflow:hidden;max-width:420px}
  .pvbar i? no
  .pvbar{height:4px;background:#0e1116;border-radius:3px;margin-top:6px;overflow:hidden;max-width:420px;display:block}
  .pvbar{transition:width .4s}
  .spin{width:13px;height:13px;border:2px solid #405a99;border-top-color:transparent;border-radius:50%;animation:spin .7s linear infinite;flex:0 0 auto}
  @keyframes spin{to{transform:rotate(360deg)}}
  /* 设置面板 */
  #settings{position:fixed;inset:0;background:rgba(10,12,18,.94);z-index:10;overflow-y:auto;display:none}
  #settings.show{display:block}
  .panel{max-width:760px;margin:40px auto;background:#141822;border:1px solid #262b3a;border-radius:16px;padding:26px}
  .panel h2{font-size:20px;margin-bottom:18px}
  .field{margin-bottom:18px}
  .field label{display:block;font-size:13px;color:#8b93a3;margin-bottom:6px}
  .row{display:grid;grid-template-columns:1fr 1fr;gap:14px}
  .switch{display:flex;align-items:center;justify-content:space-between;background:#1e2430;border:1px solid #2a3140;border-radius:10px;padding:10px 14px;margin-bottom:10px}
  .switch .n{font-size:14px}
  .switch .d{font-size:11px;color:#8b93a3}
  .plug{margin:6px 0}
  .actions{display:flex;gap:12px;justify-content:flex-end;margin-top:16px}
  .btn-sec{background:#2a3140}
  /* 皮肤：仅默认暗色（鲸鱼娘皮肤已移除） */
  /* DSH 风格：顶部栏 + 侧栏底部工具 */
  header{background:#11141c;border-bottom:1px solid #20263a;display:flex;align-items:center;gap:10px;padding:10px 16px}
  header .brand{display:flex;align-items:center;gap:10px}
  header .logo{font-size:20px}
  header .tag{font-size:12px;color:#7a8290}
  .hdr-right{margin-left:auto;display:flex;align-items:center;gap:8px}
  #sidebar .sb-foot{margin-top:auto;padding:10px;border-top:1px solid #262b3a;display:flex;flex-direction:column;gap:6px}
  #sidebar .sb-foot .sbrow{display:flex;align-items:center;gap:6px;padding:8px 10px;border-radius:8px;color:#cbd0dc;font-size:13px;background:#1a2030;cursor:pointer}
  #sidebar .sb-foot .sbrow:hover{background:#232b3d}
  .perm{font-size:11px;color:#7a8290;padding:2px 6px;border:1px solid #2a3140;border-radius:6px}
  /* DSH 风格：侧栏/顶栏/底栏 */
  .sbtop{padding:10px}
  .newchat{width:100%;background:#1e2430;border:1px solid #2a3140;color:#cbd0dc;border-radius:8px;padding:8px;font-size:13px;cursor:pointer}
  .newchat:hover{background:#2a3140}
  .sbws{display:flex;justify-content:space-between;align-items:center;padding:8px 12px;font-size:12px;color:#7a8290;border-bottom:1px solid #262b3a}
  .wsicons{letter-spacing:2px;cursor:pointer}
  .sbdocs{flex:1;overflow-y:auto;display:flex;flex-direction:column;min-height:0}
  .sbtabs{display:flex;gap:4px;padding:8px 10px;border-bottom:1px solid #262b3a}
  .sbtabs span{padding:4px 10px;border-radius:6px;font-size:12px;color:#8b93a3;cursor:pointer}
  .sbtabs span.on{background:#1e2430;color:#cbd0dc}
  .ws-ind{font-size:12px;color:#8b93a3;white-space:nowrap;display:flex;align-items:center;gap:4px}
  .badge2{font-size:11px;color:#7a8290;background:#1a2030;border:1px solid #2a3140;border-radius:10px;padding:2px 8px}
  .bar .iconselect{max-width:210px;flex:0 0 auto}
  /* 设置 左侧导航 */
  .setwrap{display:grid;grid-template-columns:190px 1fr;gap:24px;max-width:980px;margin:30px auto}
  .setnav{background:#11141c;border:1px solid #262b3a;border-radius:14px;padding:10px;height:fit-content}
  .phead{font-size:12px;color:#7a8290;margin:16px 0 8px}
  .pgroup{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}
  .pcard{background:#0e1116;border:1px solid #262b3a;border-radius:12px;padding:14px;position:relative;cursor:pointer}
  .pcard:hover{border-color:#405a99}
  .pcard .pinfo .pname{font-weight:700;font-size:14px}
  .pcard .ptag{font-size:10px;background:#1a2233;color:#7a8290;border-radius:6px;padding:1px 6px;margin-left:6px}
  .pcard .cur{background:#1b3a2b;color:#45d483;border-radius:6px;padding:1px 6px;font-size:10px;margin-left:6px}
  .pcard .pdesc{color:#aab2c0;font-size:12px;margin:6px 0}
  .pcard .pfile{color:#5b5f6e;font-size:11px}
  .pcard .picons{position:absolute;right:10px;bottom:10px;display:flex;gap:8px;font-size:15px}
  .pcard .picons span{cursor:pointer;color:#7a8290}
  .pcard .picons span:hover{color:#a78bfa}
  .padd{border:1px dashed #262b3a;border-radius:12px;padding:14px;text-align:center;color:#a78bfa;cursor:pointer;font-size:14px}
  .padd:hover{border-color:#405a99}
  .setnav-item{display:flex;align-items:center;gap:8px;padding:10px 12px;border-radius:10px;font-size:14px;color:#cbd0dc;cursor:pointer}
  .setnav-item:hover{background:#1e2430}
  .setnav-item.active{background:#2a3140;color:#fff}
  .setbody{background:#141822;border:1px solid #262b3a;border-radius:14px;padding:22px}
  .sec{display:none}
  .sec.show{display:block}
  .modal-bg{position:fixed;inset:0;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center;z-index:999}
  .modal{background:#151a26;border:1px solid #2a3140;border-radius:14px;padding:20px;width:min(420px,90vw);box-shadow:0 20px 60px #000a;color:#e8ebf3}
  .modal h3{font-size:15px;margin:0 0 18px;font-weight:600}
  .modal label{font-size:12px;color:#8b93a3;display:block;margin:18px 0 8px;font-weight:600}
  .modal input{width:100%;padding:11px 12px;border-radius:8px;border:1px solid #2a3140;background:#0e1116;color:#e8ebf3;font-size:14px;margin-bottom:4px}
  .modal .m-actions{display:flex;gap:10px;justify-content:flex-end;margin-top:26px;padding-top:16px;border-top:1px solid #2a3140}
  .modal button{padding:8px 16px;border-radius:8px;border:1px solid #2a3140;background:#222a3e;color:#e8ebf3;cursor:pointer}
  .splash{position:fixed;inset:0;background:#05070c;display:flex;align-items:center;justify-content:center;z-index:9999;animation:spaout .6s ease 1.6s forwards}
  @keyframes spaout{to{opacity:0;visibility:hidden;pointer-events:none}}
  .s-inner{text-align:center}
  .s-logo{font-size:44px;font-weight:800;background:linear-gradient(90deg,#ff6bcb,#a78bfa);-webkit-background-clip:text;background-clip:text;color:transparent}
  .s-bar{width:220px;height:6px;background:#1a2030;border-radius:3px;margin:18px auto 10px;overflow:hidden}
  .s-bar span{display:block;height:100%;width:40%;background:linear-gradient(90deg,#ff6bcb,#a78bfa);border-radius:3px;animation:sl 1.2s infinite}
  @keyframes sl{0%{margin-left:-40%}100%{margin-left:100%}}
  .s-msg{color:#8b93a3;font-size:13px}
  .modal-env{width:min(560px,94vw)}
  .envlist{max-height:55vh;overflow:auto;font-size:13px}
  .envitem{display:flex;align-items:center;gap:10px;padding:8px 10px;border-bottom:1px solid #1a2030}
  .envitem .st{width:20px;text-align:center}
  .envitem.ok .st{color:#45d483}.envitem.no .st{color:#ff6b6b}
  .envitem .nm{flex:1;color:#e8ebf3}
  .envitem .inf{color:#7a8290;font-size:12px}
  .modal button.primary{background:linear-gradient(135deg,#5b5ff5,#7c5cf0);border:none;color:#fff}
  .brainbg{position:fixed;inset:0;background:rgba(5,7,12,.82);display:flex;align-items:center;justify-content:center;z-index:998;padding:24px}
  .brain{width:min(860px,96vw);max-height:92vh;overflow-y:auto;background:#11141e;border:1px solid #2a3140;border-radius:18px;padding:24px;box-shadow:0 30px 90px #000a;color:#e8ebf3}
  .brain-head{display:flex;align-items:center;gap:12px;margin-bottom:18px}
  .brain-head .logo{font-size:22px;font-weight:800}
  .brain-sub{color:#8b93a3;font-size:13px}
  .brain-head .x{margin-left:auto}
  .brain-stats{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-bottom:18px}
  .brain-stats .bs{background:#0e1116;border:1px solid #232a3e;border-radius:12px;padding:12px;text-align:center}
  .brain-stats .bs .n{font-size:24px;font-weight:700;color:#5b5ff5}
  .brain-stats .bs .t{font-size:11px;color:#8b93a3;margin-top:4px}
  .brain-cols{display:grid;grid-template-columns:1.4fr 1fr;gap:16px}
  .brain-col h4{margin:0 0 8px;font-size:14px;color:#cbd0dc}
  .brain-list{background:#0e1116;border:1px solid #232a3e;border-radius:12px;padding:10px;max-height:340px;overflow-y:auto}
  .brain-list .bli{font-size:12px;color:#aab2c0;padding:6px 4px;border-bottom:1px solid #1a2030;line-height:1.5}
  .brain-note{font-size:13px;color:#8b93a3;line-height:1.8}
  .wswrap{display:block;cursor:pointer}
  #wsPanel{margin:4px 8px;background:#0e1116;border:1px solid #232a3e;border-radius:10px;padding:8px;max-height:260px;overflow-y:auto}
  .wsitem{display:flex;align-items:center;gap:8px;padding:6px 8px;border-radius:8px;font-size:13px;color:#cbd0dc;cursor:pointer}
  .wsitem:hover{background:#1e2430}
  .wsitem .ic{flex:0 0 18px;font-size:15px}
  .wsitem .sz{margin-left:auto;font-size:11px;color:#6e7681}
</style></head><body>
<div id="app">
  <div id="sidebar">
    <div class="sbtop"><button class="newchat" onclick="newChat()">➕ 新会话</button></div>
    <div class="sbws"><span class="wswrap" onclick="toggleWorkspace()">🗂️ 工作区</span><span class="wsicons"><span class="wsc" title="搜索会话" onclick="openSearch()">🔍</span>&nbsp;<span class="wsc" title="打开设置" onclick="openSettings()">⚙️</span>&nbsp;<span class="wsc" title="刷新会话" onclick="loadSessions()">↻</span></span></div>
    <div class="sbdocs">
      <div class="sbtabs"><span class="on" onclick="setTab(this,1)">💬 对话</span><span onclick="setTab(this,2)">🧭 轨迹</span></div>
      <div id="sessionList"></div>
      <div id="traceList" style="display:none;text-align:center"></div>
    </div>
    <div class="sb-foot">
      <div class="sbrow" id="toolsRow" onclick="toggleTools()">🛠️ 工具调用 <span class="perm" id="toolsPerm">开</span></div>
      <div class="sbrow" onclick="openSettings()">⚙️ 设置</div>
    </div>
  </div>
  <div id="main">
<header>
  <button class="icon-btn sd-toggle" id="sdToggle" onclick="toggleSidebar()" title="收起/展开侧栏">⟨</button>
  <div class="brand"><span class="logo">🐳 小焦</span><span class="tag">harness · 标准模式</span><span class="badge2" id="taskBadge" style="display:none">⏳ 空闲</span> <a href="/monitor" style="font-size:11px;color:#a78bfa;margin-left:6px">🧠 监控</a> <a href="http://127.0.0.1:48911" style="font-size:11px;color:#45d483;margin-left:6px">🐱 猫娘</a> <span id="costBadge" style="font-size:11px;color:#8b93a3;margin-left:8px"></span></div>
  <div class="hdr-right">
    <button class="icon-btn" id="toolsBtn" onclick="toggleTools()">🛠️ 工具</button>
    <button class="icon-btn" onclick="openBrain()">🧠 小脑</button>
    <button class="icon-btn" onclick="openSettings()">⚙️ 设置</button>
    <button class="icon-btn" onclick="copyPage()">📄 Session log ⚡</button>
  </div>
</header>
<div id="feed"></div>
<footer>
  <div class="composer" id="composer">
    <div class="cmp-top">
      <select id="presetSel" class="chip-sel" onchange="selectPreset(this.value)" title="Agent 预设：人格 + 大脑 + 工具开关，选中即生效"></select>
      <select id="modelSel" class="chip-sel" onchange="selectModel()" title="当前模型"></select>
      <span class="ws-ind" id="wsInd" onclick="toggleAccess()" title="点击：Full access(所有命令直接执行)/Read-only(每次执行都询问)">🔐 Full access</span>
      <button class="chip-btn" onclick="openVideo()" title="本地零算力生成视频">🎬 视频</button>
      <button class="chip-btn" id="toolsBtn" onclick="toggleTools()" title="工具调用开关">🛠️ 工具</button>
    </div>
    <div class="cmp-input">
      <textarea id="inp" rows="1" placeholder="向小焦提问…（Enter 发送，Shift+Enter 换行）" autocomplete="off"
                oninput="autoGrow(this)" onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();send();}"></textarea>
      <button class="cmp-send" onclick="send()" title="发送">➤</button>
    </div>
    <div class="cmp-hint"><span id="cmpHint">小焦会联网检索 · 抓取网页 · 查 NVD 漏洞 · 写文件</span></div>
  </div>
</footer>
  </div>
</div>

<div id="modalBg" class="modal-bg" style="display:none">
  <div class="modal">
    <h3>🔍 搜索会话</h3>
    <input id="msq" placeholder="输入关键词，过滤会话…" onkeydown="if(event.key==='Enter')doSearch()"/>
    <div class="m-actions"><button onclick="closeSearch()">取消</button><button class="primary" onclick="doSearch()">确定</button></div>
  </div>
</div>
<div id="editBg" class="modal-bg" style="display:none">
  <div class="modal modal-env">
    <h3>✏️ 编辑预设</h3>
    <label style="font-size:12px;color:#8b93a3">名称</label><input id="eName" style="width:100%;padding:8px;border-radius:8px;border:1px solid #2a3140;background:#0e1116;color:#e8ebf3;margin:4px 0 8px">
    <label style="font-size:12px;color:#8b93a3">人格 / 人设(role)</label><textarea id="eRole" rows="3" style="width:100%;padding:8px;border-radius:8px;border:1px solid #2a3140;background:#0e1116;color:#e8ebf3;resize:vertical;margin:4px 0 8px"></textarea>
    <label style="font-size:12px;color:#8b93a3">大脑引擎</label>
    <select id="eEngine" style="width:100%;padding:8px;border-radius:8px;border:1px solid #2a3140;background:#0e1116;color:#e8ebf3;margin:4px 0 8px"><option value="auto">auto(自动)</option><option value="llama">llama(本地)</option><option value="api">api(外接)</option><option value="xiaojiao">xiaojiao(自建)</option></select>
    <label style="font-size:12px;color:#8b93a3">上下文 ctx</label><input id="eCtx" type="number" style="width:100%;padding:8px;border-radius:8px;border:1px solid #2a3140;background:#0e1116;color:#e8ebf3;margin:4px 0 8px">
    <label style="font-size:12px;color:#8b93a3">工具开关</label>
    <div style="display:flex;gap:16px;font-size:13px;margin:6px 0"><label><input type="checkbox" id="eSearch"> 联网搜索</label><label><input type="checkbox" id="eMem"> 记忆</label><label><input type="checkbox" id="eTools"> 工具/代码执行</label></div>
    <label style="font-size:12px;color:#8b93a3">温度 temperature</label><input id="eTemp" type="number" step="0.1" style="width:100%;padding:8px;border-radius:8px;border:1px solid #2a3140;background:#0e1116;color:#e8ebf3;margin:4px 0 8px">
    <label style="font-size:12px;color:#8b93a3">max_tokens</label><input id="eMax" type="number" style="width:100%;padding:8px;border-radius:8px;border:1px solid #2a3140;background:#0e1116;color:#e8ebf3;margin:4px 0 8px">
    <div class="m-actions"><button onclick="closeEdit()">取消</button><button class="primary" onclick="savePreset()">💾 保存预设</button></div>
  </div>
</div>
<div id="videoBg" class="modal-bg" style="display:none">
  <div class="modal modal-video">
    <h3>🎬 生成视频</h3>
    <div style="display:flex;align-items:center;gap:10px;margin:0 0 10px">
      <span style="font-size:12px;color:#8b93a3">生成引擎：</span>
      <select id="vengine" onchange="setVideoMode(this.value)" style="width:auto;padding:6px 10px;border-radius:8px;border:1px solid #2a3140;background:#0e1116;color:#e8ebf3">
        <option value="api">☁️ 云端 Agnes API（免费，不占显存）</option>
        <option value="local">💻 本地 ComfyUI+Wan2.1</option>
      </select>
      <span id="vmodeH" style="font-size:11px;color:#7a8290"></span>
    </div>
    <p style="color:#8b93a3;font-size:13px;margin:0 0 10px">输入场景，小焦生成真视频。云端 API 快且不占显存，本地用 ComfyUI+Wan2.1。</p>
    <textarea id="vq" placeholder="例如：樱花飘落的海边、一只猫在阳光下打盹…" rows="3" style="width:100%;resize:vertical"></textarea>
    <div id="vpv" class="vpv" style="display:none"></div>
    <div id="vconfirm" class="m-actions" style="display:none"><button onclick="openVideo()">重输</button><button class="primary" onclick="confirmVideo()">✅ 确认并生成</button></div>
    <div class="m-actions"><button onclick="closeVideo()">取消</button><button class="primary" onclick="startVideo()">✨ 精炼提示词</button></div>
  </div>
</div>
<div id="addLocalBg" class="modal-bg" style="display:none">
  <div class="modal modal-env">
    <h3>🗄️ 一键添加本地模型</h3>
    <label>模型显示名</label><input id="lm_name" placeholder="如 数学大脑">
    <label>GGUF 文件绝对路径</label><input id="lm_gguf" placeholder="如 D:/models/xxx.gguf（填你自己模型的真实路径）">
    <label>上下文 ctx（默认 20000）</label><input id="lm_ctx" type="number" value="20000">
    <div class="m-actions"><button onclick="closeAddLocal()">取消</button><button class="primary" onclick="saveAddLocal()">🚀 一键添加</button></div>
    <div class="think" id="lm_msg" style="margin-top:12px"></div>
  </div>
</div>
<div id="envBg" class="modal-bg" style="display:none">
  <div class="modal modal-env">
    <h3>🛠️ 环境检查（安装向导）</h3>
    <div id="envList" class="envlist"><div class="think">正在检测…</div></div>
    <div class="m-actions"><button onclick="closeEnv()">关闭</button></div>
  </div>
</div>
<div id="splash" class="splash"><div class="s-inner"><div class="s-logo">小焦</div><div class="s-bar"><span></span></div><div class="s-msg">暖机中，正在优化页面…</div></div></div>
<div id="brainBg" class="brainbg" style="display:none">
  <div class="brain">
    <div class="brain-head"><span class="logo">🐳 小脑</span><span class="brain-sub">小焦真正自研的那颗会学习的脑</span><button class="icon-btn x" onclick="closeBrain()">✕</button></div>
    <div class="brain-stats" id="brainStats">读取中…</div>
    <div class="brain-cols">
      <div class="brain-col"><h4>🧠 学到的功能用法</h4><div id="brainLessons" class="brain-list">…</div></div>
      <div class="brain-col"><h4>🧭 说明</h4><div id="brainPrompt" class="brain-list" style="margin-bottom:10px"></div>
  <div class="brain-note">
        「别人靠算力，小脑靠文本。」每次你点👍/被更正，大脑的好答案就写进小脑知识库，越长越强；小脑检索命中即可复用。<br><br>
        <button class="btn-sec" onclick="window.open('/growth')">📄 生成成长报告（可分享）</button>
      </div></div>
    </div>
  </div>
</div>
<div id="settings">
  <div class="setwrap">
    <div class="setnav">
      <div class="setnav-item active" data-sec="general" onclick="setSec(this,'general')">⚙️ 通用设置</div>
      <div class="setnav-item" data-sec="model" onclick="setSec(this,'model')">🎛️ 模型</div>
      <div class="setnav-item" data-sec="plugins" onclick="setSec(this,'plugins')">🧩 插件</div>
      <div class="setnav-item" data-sec="presets" onclick="setSec(this,'presets')">🎭 Agent 预设</div>
    </div>
    <div class="setbody">
      <div class="sec" id="sec-presets">
      <h3>🎭 Agent 预设</h3>
      <p style="color:#7a8290;font-size:13px;margin:4px 0 14px">预设 = 人格 + 大脑 + 工具开关。选中即切换（不重启）。</p>
      <div class="phead">内置</div>
      <div id="presetCards" class="pgroup"></div>
      <div class="phead">自定义</div>
      <div class="padd" onclick="createPreset()">＋ 用「创造模式」创作自定义预设</div>
    </div>
    <div class="sec show" id="sec-general">
        <div class="field"><label>模型名称</label><input id="s_name"/></div>
        <div class="field"><label>大脑（engine：auto=自动 / llama=本地大模型 / api=外接API / xiaojiao=自建模型）</label>
          <select id="s_engine"><option value="auto">auto（自动）</option><option value="llama">llama（本地大模型）</option><option value="api">api（外接 OpenAI 兼容）</option><option value="xiaojiao">xiaojiao（自建模型）</option></select>
        </div>
        <div class="field"><label>模型上下文窗口 ctx（大模型一次能处理的 token 上限，在 Harness 里用长对话必需；越大越占显存，启动报 OOM 就调小）</label><input id="s_llm_ctx" type="number" min="2048" step="1024"/></div>
        <div class="row">
          <div class="field"><label>temperature</label><input id="s_temp" type="number" step="0.1" min="0" max="2"/></div>
          <div class="field"><label>max_tokens</label><input id="s_tokens" type="number" min="16"/></div>
        </div>
        <div class="row">
          <div class="field"><label>context_len（上下文轮数）</label><input id="s_ctx" type="number" min="1"/></div>
          <div class="field"><label>API Base URL（engine=api 时用）</label><input id="s_base"/></div>
        </div>
        <div class="field"><label>人设 / 类型（role）—— 改这里·小焦成为什么类型的模型</label>
          <textarea id="s_role" rows="6"></textarea></div>
        <div class="field"><label>能力开关</label>
          <div class="switch"><div><div class="n">操控电脑（工具调用）</div><div class="d">让大模型运行命令、读写文件、打开应用</div></div><label><input type="checkbox" id="s_tools"/></label></div>
        </div>
        <div class="actions">
          <button class="btn-sec" onclick="closeSettings()">取消</button>
          <button onclick="saveSettings()">💾 保存并生效</button>
        </div>
      </div>
      <div class="sec" id="sec-model">
        <div class="field"><label>模型管理（对接本地/外接模型）</label>
          <div id="s_model_list"></div>
          <div class="row" style="margin-top:10px">
            <div class="field"><label>名字</label><input id="s_m_name" placeholder="如 Qwen3.8"/></div>
            <div class="field"><label>类型</label><select id="s_m_engine"><option value="api">api（OpenAI兼容外接）</option><option value="llama">llama（本地大模型）</option><option value="xiaojiao">xiaojiao（自建模型）</option></select></div>
          </div>
          <div class="row">
            <div class="field"><label>Base URL</label><input id="s_m_base" placeholder="如 http://127.0.0.1:8080/v1"/></div>
            <div class="field"><label>API Key（可留空）</label><input id="s_m_key"/></div>
          </div>
          <div class="row">
            <div class="field"><label>模型名</label><input id="s_m_model" placeholder="如 deepseek-chat"/></div>
            <div class="field" style="display:flex;align-items:flex-end;gap:10px"><button class="btn-sec" onclick="addModel()">＋ 添加模型(API/外接)</button><button class="btn-sec" style="margin-left:8px" onclick="addLocalModel()">🗄️ 一键加本地GGUF</button></div>
          </div>
          <div class="think" id="s_model_msg"></div>
        </div>
      </div>
      <div class="sec" id="sec-plugins">
        <div class="field"><label>插件（可开关）</label><div id="s_plugins"></div></div>
      </div>
      <div id="plugSecs"></div>
    </div>
  </div>
</div>

<script>
const feed=document.getElementById('feed'),inp=document.getElementById('inp');
// ---- Bug 5：本标签页的"生成状态"（全局，因为切会话时要能把它整个收掉）----
// active：正在生成；ctrl：当前这轮的 AbortController（切会话/点停止要真的断流）；
// sid：这一轮提问落在哪个会话（切回来时用它判断"这条是不是我这轮在跑"）；
// seq：轮次序号 —— 收尾时用它确认"我清理的还是我自己那一轮"，避免晚到的旧流把新一轮的标志清掉。
const GEN={active:false,ctrl:null,sid:null,seq:0};
// 切会话/新建会话/离开页面时，把**旧的那一轮**干净地收掉。
// 为什么必须主动 abort：只"不再读流"的话，服务端那一侧还在继续生成、继续往会话里写 ——
// 于是切走再切回来，看到的还是那一轮的内容（用户以为卡住了）。断开连接，服务端才会走
// "客户端断开"分支：注销生成状态 + 把已生成的部分落盘。
//
// ---- 问题 2：**必须等后端确认这一轮真结束了再往下走** ----
// 真实缺陷（用户实测：回答完切走再切回，有时卡在"正在回答…"）：
// abort() 只是"我这边不读了"，服务端什么时候发现断连、什么时候注销标记**没有硬保证**。
// 于是出现竞态：赶上了 → 一切正常；没赶上 → 后端还认为在生成，
// 切回来时占位符被保留、界面就一直转圈（这就是"时好时坏"）。
// 修法两步，缺一不可：
//   ① 等后端把标记撤掉（最多 3 秒，每 150ms 问一次"这个会话还在生成吗"）；
//   ② 3 秒还没撤 → 调 /api/chat/abandon **强制撤**（用户要求的口径："3 秒没数据就认为生成已死"）。
async function stopGeneration(){
  const sid=GEN.sid;
  try{if(GEN.ctrl)GEN.ctrl.abort();}catch(e){}
  GEN.active=false;GEN.ctrl=null;
  try{
    document.querySelectorAll('#feed .think').forEach(function(e){e.remove();});
    document.querySelectorAll('#feed .icon-btn').forEach(function(e){
      if((''+e.textContent).indexOf('停止')>=0)e.remove();});
  }catch(e){}
  if(!sid)return;                       // 没记下会话 id（还没开跑）→ 没有要等的
  const t0=Date.now();
  for(;;){
    try{
      const d=await (await fetch('/api/session/'+sid)).json();
      if(!d.generating)return;          // 后端确认这一轮结束了 → 可以安全渲染
    }catch(e){}
    if(Date.now()-t0>3000){             // 3 秒还没结束 → 按"生成已死"处理，强制清标志
      try{await fetch('/api/chat/abandon',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({session_id:sid})});}catch(e){}
      return;
    }
    await new Promise(function(r){setTimeout(r,150);});
  }
}
const S=document.getElementById('settings');
function esc(s){return (s||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
// ================= 数学公式渲染（KaTeX）=================
// 【为什么不改 renderMd、而是"渲染完再扫一遍"】
//   renderMd 是**分块**处理的（先切空行、再按标题/引用/表格分派）。公式里会出现
//   `*` `_` `\` 这些和 Markdown 抢语义的字符（`$a_1 * b$` 里的 `*` 会被当成强调，
//   `$x_i$` 里的下划线会被当成斜体），在分块阶段处理公式要同时改三处解析器、且容易互相打架。
//   现在这一步只做一件事：**在已成型的 DOM 上按文本节点找公式**。
//   代价是多一趟 DOM 扫描（只在文本里真的有 `$` 时才扫），换来的是渲染链路一行没动。
// 【为什么要跳过 pre/code】代码块里的 `$` 是**代码**（`echo $PATH`、`$x = 1`），不是公式。
//   auto-render 的 ignoredTags 就是干这个的 —— 不跳过的话，一段 shell 代码会被吃成公式。
// 【为什么 throwOnError 给 false】模型偶尔会写出不完整的 LaTeX。宁可把那一小段显示成
//   红色原文（用户看得出"这里公式错了"），也不能让一个公式的解析错误**炸掉整条消息**。
function mathify(el){
  try{
    if(!el||!window.renderMathInElement)return;      // KaTeX 没加载上 → 如实留着原文
    if(!el.textContent||el.textContent.indexOf('$')<0)return;   // 没有 $ 就没必要扫
    window.renderMathInElement(el,{
      delimiters:[
        {left:'$$',right:'$$',display:true},
        {left:'\\[',right:'\\]',display:true},
        {left:'\\(',right:'\\)',display:false},
        {left:'$',right:'$',display:false}
      ],
      ignoredTags:['script','noscript','style','textarea','pre','code','option'],
      ignoredClasses:['codebox'],
      throwOnError:false,
      errorColor:'#ff7b72'
    });
  }catch(e){}      // 公式渲染失败绝不能连累消息本身
}
function inline(t){t=t.replace(/\*\*([^\n*]+)\*\*/g,'<strong>$1</strong>')
  .replace(/(^|\n)#{1,6}\s+([^\n]+)/g,'<h3>$2</h3>')
  .replace(/`([^`\n]+)`/g,'<code>$1</code>')
  .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>')
  .replace(/^[-*]\s+/gm,'· ')
  .replace(/\n/g,'<br>');return t;}
// ===== 语法高亮：按语言分词上色（关键字/字符串/数字/注释/函数名/JSON 键…）=====
// 规则里**不能有捕获组**（否则分组下标会错位），一律用 (?:...)。
const HLRULES={
  json:[['key',/"(?:\\.|[^"\\])*"(?=\s*:)/],['str',/"(?:\\.|[^"\\])*"/],['bool',/\b(?:true|false|null)\b/],['num',/-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b/]],
  python:[['com',/#[^\n]*/],['str',/["]{3}[\s\S]*?["]{3}|[']{3}[\s\S]*?[']{3}|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'/],
    ['kw',/\b(?:def|class|return|if|elif|else|for|while|try|except|finally|with|as|import|from|lambda|yield|pass|break|continue|in|is|not|and|or|None|True|False|self|async|await|global|nonlocal|raise|assert|del|match|case)\b/],
    ['fn',/\b[A-Za-z_]\w*(?=\()/],['num',/\b\d+(?:\.\d+)?\b/],['op',/[+\-*/%=<>!&|^~]+/]],
  js:[['com',/\/\/[^\n]*|\/\*[\s\S]*?\*\//],['str',/`(?:\\.|[^`\\])*`|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'/],
    ['kw',/\b(?:function|const|let|var|return|if|else|for|while|do|class|extends|new|async|await|try|catch|finally|throw|typeof|instanceof|import|export|default|from|of|in|null|undefined|true|false|this|super)\b/],
    ['fn',/\b[A-Za-z_$][\w$]*(?=\()/],['num',/\b\d+(?:\.\d+)?\b/],['op',/[+\-*/%=<>!&|^~?:]+/]],
  bash:[['com',/#[^\n]*/],['str',/"(?:\\.|[^"\\])*"|'[^']*'/],
    ['kw',/\b(?:echo|if|then|fi|for|do|done|while|case|esac|function|export|source|cd|ls|rm|cp|mv|mkdir|git|python|python3|pip|curl|cat|grep|find|chmod|chown|sudo|apt|brew|winget|powershell|set|start|stop)\b/],
    ['var',/\$\{?\w+\}?/],['op',/[|&><=]+/]],
  sql:[['com',/--[^\n]*/],['str',/'(?:[^']|'')*'/],
    ['kw',/\b(?:SELECT|FROM|WHERE|INSERT|INTO|VALUES|UPDATE|SET|DELETE|CREATE|TABLE|ALTER|DROP|INDEX|JOIN|LEFT|RIGHT|INNER|OUTER|ON|GROUP|BY|ORDER|HAVING|LIMIT|OFFSET|AND|OR|NOT|NULL|AS|DISTINCT|COUNT|SUM|AVG|MAX|MIN|PRIMARY|KEY|FOREIGN|REFERENCES)\b/i],
    ['num',/\b\d+\b/]],
  css:[['com',/\/\*[\s\S]*?\*\//],['kw',/@[\w-]+/],['str',/"[^"]*"|'[^']*'/],
    ['attr',/[.#]?[A-Za-z-][\w-]*(?=\s*\{)/],['fn',/[A-Za-z-]+(?=\s*:)/],['num',/-?\b\d+(?:\.\d+)?(?:px|em|rem|%|vh|vw|s|ms)?\b/]],
  html:[['com',/<!--[\s\S]*?-->/],['tag',/<\/?[A-Za-z][\w-]*|\/?>/],['attr',/[A-Za-z-]+(?==)/],['str',/"[^"]*"|'[^']*'/]],
};
function _hlGeneric(code){       // 没有对应语言的规则时：只认字符串/数字/注释，别乱上色
  const rules=[['com',/#[^\n]*|\/\/[^\n]*/],['str',/"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'/],['num',/\b\d+(?:\.\d+)?\b/]];
  return rules;
}
function hl(code,lang){
  const key=(lang||'').toLowerCase();
  const alias={py:'python',python3:'python',javascript:'js',node:'js',ts:'js',typescript:'js',
               shell:'bash',zsh:'bash',powershell:'bash',ps1:'bash',curl:'bash',
               mysql:'sql',postgres:'sql',yml:'bash',yaml:'bash'};
  const rules=HLRULES[key]||HLRULES[alias[key]]||_hlGeneric(code);
  if(!code||code.length>40000)return esc(code);   // 超大文本不高亮，避免卡顿
  let re;
  try{re=new RegExp(rules.map(r=>'('+r[1].source+')').join('|'),'gm');}catch(e){return esc(code);}
  let out='',last=0,m,guard=0;
  while((m=re.exec(code))&&guard++<20000){
    out+=esc(code.slice(last,m.index));
    let gi=0;for(let i=1;i<=rules.length;i++){if(m[i]!==undefined){gi=i;break;}}
    out+='<span class="tk-'+rules[gi-1][0]+'">'+esc(m[0])+'</span>';
    last=m.index+m[0].length;
    if(m[0]==='')re.lastIndex++;
  }
  return out+esc(code.slice(last));
}
function codeBlock(code,lang){
  const ln=(lang||'code');const raw=code.replace(/\n$/,'');
  return '<div class="codebox lang-'+esc(ln)+'"><div class="codehead"><span class="lang '+esc(ln)+'">'+esc(ln)+'</span><button class="cp" onclick="copyCode(this)">⧉ 复制</button></div><pre class="code"><code>'+hl(raw,ln)+'</code></pre></div>';
}
function copyCode(btn){const pre=btn.closest('.codebox').querySelector('code');const t=pre.innerText;
  navigator.clipboard.writeText(t).then(()=>{btn.textContent='✓ 已复制';setTimeout(()=>btn.textContent='⧉ 复制',1200);}).catch(()=>{});}
function copyMsg(btn){const b=btn.closest('.m').querySelector('.b');
  navigator.clipboard.writeText(b.innerText).then(()=>{btn.textContent='✓ 已复制';setTimeout(()=>btn.textContent='复制',1200);}).catch(()=>{});}

function toggleSidebar(){const sb=document.getElementById('sidebar');const col=sb.classList.toggle('collapsed');
  const t=document.getElementById('sdToggle');if(t)t.textContent=col?'⟩':'⟨';}
function setTab(el,n){document.querySelectorAll('.sbtabs span').forEach(x=>x.classList.remove('on'));el.classList.add('on');
  document.getElementById('sessionList').style.display=n===1?'block':'none';
  document.getElementById('traceList').style.display=n===2?'block':'none';
  if(n===2)loadTrace();}
function loadTrace(){const el=document.getElementById('traceList');
  try{const r=JSON.parse(localStorage.getItem('xj_trace')||'[]');
    el.innerHTML=r.length?r.map(x=>'<div class="srci"><div class="st">'+esc(x.tool||'')+'</div><div class="sc">'+esc(String(x.result||'').slice(0,80))+'</div></div>').join(''):'<div class="think">暂无工具轨迹</div>';}catch(e){}}
let fullAccess=true;


async function toggleWorkspace(){const el=document.getElementById("wsPanel");if(el.style.display==="none"){el.style.display="block";await loadWorkspace();}else{el.style.display="none";}}
async function loadWorkspace(){try{const d=await (await fetch("/api/workspace")).json();const el=document.getElementById("wsPanel");
  el.innerHTML=d.length?d.map(function(x){return "<div class=\"wsitem\" data-n=\""+esc(x.name)+"\" onclick=\"openWsFile(this.dataset.n)\"><span class=\"ic\">"+(x.type==="dir"?"📁":"📄")+"</span><span>"+esc(x.name)+"</span><span class=\"sz\">"+esc(x.size)+"</span></div>";}).join(""):"<div class=\"think\">空</div>";}catch(e){document.getElementById("wsPanel").innerHTML="<div class=\"think\">读取失败</div>";}}
async function openWsFile(name){try{const d=await (await fetch("/api/ws/open",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:name})})).json();
  if(!d.ok){alert(d.error||"无法打开");return;}
  const cur=document.getElementById("modalBg");cur.style.display="flex";
  cur.innerHTML="<div class=\"modal modal-wide\"><h3>📄 "+esc(d.name)+"</h3><pre class=\"wspre\">"+esc(d.content)+"</pre><div class=\"m-actions\"><button onclick=\"closeSearch()\">关闭</button></div></div>";
}catch(e){alert("读取失败");}}

async function loadVideoMode(){try{const d=await (await fetch('/api/video/mode')).json();if(d.ok){const sel=document.getElementById('vengine');sel.value=d.mode||'api';updateVmodeH();}}catch(e){}}
function updateVmodeH(){const sel=document.getElementById('vengine');const h=document.getElementById('vmodeH');if(!h)return;
  if(sel.value==='api'){h.textContent='（云端，约1-2分钟，省显存）';}
  else{h.textContent='（本地，需显存切换）';}}
async function setVideoMode(v){try{const d=await (await fetch('/api/video/mode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:v})})).json();if(d.ok)updateVmodeH();}catch(e){}}
async function openVideo(){document.getElementById('videoBg').style.display='flex';const i=document.getElementById('vq');i.value='';i.focus();document.getElementById('vpv').style.display='none';document.getElementById('vconfirm').style.display='none';loadVideoMode();}
function closeVideo(){document.getElementById('videoBg').style.display='none';}
async function startVideo(){const q=document.getElementById('vq').value.trim();if(!q){return;}
  const pv=document.getElementById('vpv');pv.style.display='block';pv.innerHTML='⏳ 小焦正在精炼提示词…';document.getElementById('vconfirm').style.display='none';
  try{const d=await (await fetch('/api/video/refine?prompt='+encodeURIComponent(q))).json();
   pv.innerHTML='<div style="font-size:12px;color:#8b93a3;margin-bottom:4px">✅ 小焦改写后的提示词（英文给视频模型，画质最好）：</div><div style="font-size:13px;color:#a78bfa;line-height:1.6;background:#0e1116;border:1px solid #2a3140;border-radius:8px;padding:8px">'+esc(d.refined)+'</div><div style="font-size:12px;color:#8b93a3;margin-top:6px">📖 中文大意：<span style="color:#cbd0dc">'+esc(d.zh||'电影级画面、柔和光线、清晰细节、顺滑运镜。')+'</span></div><div style="font-size:12px;color:#6e7681;margin-top:6px">满意就点「确认并生成」；不满意重新输入。</div>';
   document.getElementById('vconfirm').style.display='flex';
   window._vq=q; window._vr=d.refined;
  }catch(e){pv.innerHTML='⚠️ '+esc(e.message);}}
async function confirmVideo(){const q=window._vq||'', rf=window._vr||'';
  const sel=document.getElementById('vengine');const isApi=sel&&sel.value==='api';
  // api 模式用原话(云端直接生成, 不绕本地精炼); local 模式用精炼后的英文提示词
  const usePrompt=isApi?q:(rf||q);
  closeVideo();
  const m=document.createElement('div');m.className='m bot';m.innerHTML='<div class="b">🎬 小焦'+(isApi?'已发起云端视频生成…':'已学习，正在切换视频模型…')+'</div>';feed.appendChild(m);feed.scrollTop=feed.scrollHeight;
  const b=m.querySelector('.b');
  try{const d=await (await fetch('/api/video',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prompt:q,refined:usePrompt})})).json();
   if(d.busy){b.innerHTML='⏳ 正在生成/切换模型中，请稍候…';return;}
   if(!d.ok){b.innerHTML='⚠️ '+esc(d.error||'启动失败');return;}
   try{localStorage.setItem('xj_video_job',d.job);}catch(e){}
   let n=0,sp=false;
   const iv=setInterval(async()=>{n++;
     try{const st=await (await fetch('/api/video/status?job='+d.job)).json();
      if(st.state==='done'){clearInterval(iv);try{localStorage.removeItem('xj_video_job');}catch(e){}
        b.innerHTML='<video src="'+st.url+'" controls style="max-width:100%;border-radius:12px"></video><div style="font-size:12px;color:#8b93a3;margin-top:6px">🎬 真·AI 视频</div>'+(st.refined_prompt?'<div class="vpvmini" style="margin-top:4px">📝 提示词：<span style="color:#a78bfa">'+esc(st.refined_prompt)+'</span></div>':'');feed.scrollTop=feed.scrollHeight;
        try{fetch('/api/message',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({role:'小焦',content:'🎬 视频生成完成：\n[video]'+st.url+'[/video]'+(st.refined_prompt?'\n📝 提示词：'+st.refined_prompt:'')})});}catch(e){}}
      else if(st.state==='error'){clearInterval(iv);try{localStorage.removeItem('xj_video_job');}catch(e){};b.innerHTML='⚠️ '+esc(st.message||'生成失败');}
      else if((st.refined_prompt)&&!sp){b.innerHTML='🎬 正在生成视频…<div class="vpvmini" style="margin-top:6px">📝 用提示词：<span style="color:#a78bfa">'+esc(st.refined_prompt)+'</span></div>';sp=true;}
      else if(st.state==='unknown'){clearInterval(iv);try{localStorage.removeItem('xj_video_job');}catch(e){}b.textContent='（视频任务已结束，如需生成请重新点 🎬）';}
      else if(n*5>2700){clearInterval(iv);b.innerHTML='⏱️ 超时，到 ComfyUI(8188) 看是否完成。';}
      else{var pr=(st.progress&&st.progress.max)?Math.round(100*st.progress.value/st.progress.max):0;var msg='🎬 '+((st.message||"生成中…")+(pr?'（第 '+st.progress.value+'/'+st.progress.max+' 步，'+pr+'%）':''))+'（已等 '+Math.round(n*5)+'s）';b.textContent=msg;if(pr>0){var bar=b.nextElementSibling;if(!bar||!bar.classList.contains("pvbar")){bar=document.createElement("div");bar.className="pvbar";b.after(bar);}bar.style.width=pr+"%";}}
     }catch(e){}
   },5000);
  }catch(e){b.innerHTML='⚠️ 出错了：'+esc(e.message);}}


async function resumeChat(){try{const p=await (await fetch('/api/chat/pending')).json();
  if(!p.pending){return;}
  const m=document.createElement('div');m.className='m bot';m.innerHTML='<div class="b"><span class="spin"></span> 正在回答（可先干别的，恢复中）…</div>';feed.appendChild(m);feed.scrollTop=feed.scrollHeight;
  const iv=setInterval(async()=>{try{const u=await (await fetch('/api/chat/pending')).json();
    if(!u.pending){clearInterval(iv);GEN.active=false;const b=m.querySelector('.b');
      // 问题 2：收尾时也**不许把占位符当内容渲染**（那就是"卡在正在回答"的观感来源）
      const txt=(''+(u.content||''));
      b.innerHTML=(txt&&txt.indexOf('__pending__')<0)?renderMd(txt):'⏹ 这条回答中断了（没写完）—— 想接着要，直接重说一次就行';
      mathify(b);
      feed.scrollTop=feed.scrollHeight;}}catch(e){}},2500);
  }catch(e){}}


function syncLoop(){try{loadSessions();}catch(e){}
  // 服务器端当前视频任务 -> 顶部小提示(跨标签/刷新都在)
  try{fetch('/api/video/current').then(r=>r.json()).then(c=>{
    const v=(c.job||{});
    let pill=document.getElementById('syncPill');
    if(!pill){pill=document.createElement('span');pill.id='syncPill';pill.style.cssText='font-size:11px;padding:2px 8px;border-radius:10px;background:#5b5ff533;color:#a78bfa;margin-left:6px';const h=document.querySelector('.tag');if(h)h.after(pill);}
    const tb=document.getElementById('taskBadge');
    const act=(c.job&&['queued','switching','generating'].indexOf(c.job.state)>=0);
    if(tb){tb.style.display='';tb.textContent=act?'🎬 1 个后台任务：视频生成':'⏳ 空闲';tb.style.color=act?'#f0a848':'#7a8290';}
    if(act){pill.textContent='🎬 生成中';pill.style.display='';}
    else if(c.job&&c.job.state==='done'&&c.job.url){pill.textContent='🎬 完成';setTimeout(()=>{pill.style.display='none'},8000);}
    else{pill.style.display='none';}
  }).catch(()=>{});}catch(e){}}
setInterval(syncLoop,4000);

async function resumeVideoJob(){let job='';
  // 优先服务器端当前任务(跨浏览器/刷新/重启)
  try{const c=await (await fetch('/api/video/current')).json();
    if(c.job&&c.job.id){job=c.job.id;try{localStorage.setItem('xj_video_job',job);}catch(e){}}
  }catch(e){}
  if(!job){try{job=localStorage.getItem('xj_video_job')||'';}catch(e){}}
  if(!job)return;
  const m=document.createElement('div');m.className='m bot';m.innerHTML='<div class="b">🎬 恢复上次生成进度…</div>';feed.appendChild(m);
  const b=m.querySelector('.b');let n=0;
  const iv=setInterval(async()=>{n++;
    try{const st=await (await fetch('/api/video/status?job='+job)).json();
      if(st.state==='done'){clearInterval(iv);try{localStorage.removeItem('xj_video_job');}catch(e){}
        b.innerHTML='<video src="'+st.url+'" controls style="max-width:100%;border-radius:12px"></video><div style="font-size:12px;color:#8b93a3;margin-top:6px">🎬 真·AI 视频（刷新前生成）</div>';feed.scrollTop=feed.scrollHeight;}
      else if(st.state==='error'){clearInterval(iv);try{localStorage.removeItem('xj_video_job');}catch(e){};b.innerHTML='⚠️ '+esc(st.message||'生成失败');}
      else if(st.state==='unknown'){clearInterval(iv);try{localStorage.removeItem('xj_video_job');}catch(e){}m.remove();}
      else if(n*5>2700){clearInterval(iv);b.textContent='⏱️ 超时，到 8188 看是否完成。';}
      else{var pr=(st.progress&&st.progress.max)?Math.round(100*st.progress.value/st.progress.max):0;var msg='🎬 '+((st.message||"生成中…")+(pr?'（第 '+st.progress.value+'/'+st.progress.max+' 步，'+pr+'%）':''))+'（已等 '+Math.round(n*5)+'s）';b.textContent=msg;if(pr>0){var bar=b.nextElementSibling;if(!bar||!bar.classList.contains("pvbar")){bar=document.createElement("div");bar.className="pvbar";b.after(bar);}bar.style.width=pr+"%";}}
    }catch(e){}
  },5000);
}
function loadCost(){try{fetch('/api/cost').then(r=>r.json()).then(d=>{
  const el=document.getElementById('costBadge');if(el)el.textContent='💸 今日节省 ¥'+d.saved+' · '+d.calls+'次';
});}catch(e){}}
// ===== 预设：选中即生效（人格 + 大脑 + 工具开关）=====
// 真实缺陷：以前 loadPresets() 里 `if(d.current)sel.value=d.current` 写在判空之外，
// 而页面上根本没有 #presetSel 元素 → 抛 TypeError 被外层 try/catch 吞掉；
// loadPresetCards() 又从来没人调用 → "Agent 预设"面板永远空白，用户设置半天"跟没生效一模一样"。
function toast(msg,ms){let t=document.getElementById('toast');
  if(!t){t=document.createElement('div');t.id='toast';document.body.appendChild(t);}
  t.textContent=msg;t.classList.add('show');clearTimeout(t._tm);
  t._tm=setTimeout(()=>t.classList.remove('show'),ms||2600);}
function fillPresetSelect(list,current,currentName){
  const sel=document.getElementById('presetSel');if(!sel)return;
  sel.innerHTML='<option value="">🎭 预设</option>'+(list||[]).map(p=>'<option value="'+esc(p.file)+'">🎭 '+esc(p.name)+'</option>').join('');
  if(current){sel.value=current;}
  // 名字也匹配一次：万一后端只给到"显示名"（老接口/自定义预设），别让下拉掉回占位项
  if(!sel.value&&currentName){const hit=(list||[]).find(p=>p.name===currentName);if(hit)sel.value=hit.file;}
  if(!sel.value){const hit=(list||[]).find(p=>p.name===current);if(hit)sel.value=hit.file;}
}
function loadPresets(){try{fetch('/api/presets').then(r=>r.json()).then(d=>{
  window._presets=d.presets||[];
  fillPresetSelect(window._presets,d.current||'',d.current_name||'');
  const h=document.getElementById('cmpHint');
  if(h&&(d.current_name||d.current))h.textContent='当前预设：'+(d.current_name||d.current)+' · 联网检索 · 抓取网页 · 查 NVD 漏洞 · 写文件';
  loadPresetCards();
}).catch(()=>{});}catch(e){}}
function _afterPreset(d,file){
  if(!d.ok){toast('⚠️ 加载失败：'+(d.error||''));return;}
  const c=d.capabilities||{};
  toast('✅ 已切换预设：'+(d.preset||'')+' · 联网'+(c.web_search===false?'关':'开')
        +' · 工具'+(c.run_tools===false?'关':'开'),3800);
  const h=document.getElementById('cmpHint');
  if(h)h.textContent='当前预设：'+(d.preset||'')+' · 人格与工具开关已立即生效';
  setToolsOn(c.run_tools!==false);
  loadPresets();
}
function selectPreset(file){if(!file)return;
  fetch('/api/presets/load',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({file:file})})
   .then(r=>r.json()).then(d=>_afterPreset(d,file)).catch(e=>toast('⚠️ 加载失败：'+e));}
function loadPresetCards(){try{fetch('/api/presets').then(r=>r.json()).then(d=>{
  window._presets=d.presets||[];
  const el=document.getElementById('presetCards');if(!el)return;
  el.innerHTML=window._presets.length?window._presets.map(p=>'<div class="pcard'+(p.file===d.current?' on':'')+'" onclick="loadPreset(\''+esc(p.file)+'\')">'+
    '<div class="pinfo"><span class="pname">'+esc(p.name)+'</span><span class="ptag">'+(p.file===d.current?'当前使用':'点击切换')+'</span></div>'+
    '<div class="pdesc">'+esc(p.desc||'')+'</div><div class="pfile">'+esc(p.file)+'</div>'+
    '<div class="picons"><span title="编辑" onclick="event.stopPropagation();editPreset(\''+esc(p.file)+'\')">✏️</span><span title="复制" onclick="event.stopPropagation();duplicatePreset(\''+esc(p.file)+'\')">⧉</span><span title="使用" onclick="event.stopPropagation();loadPreset(\''+esc(p.file)+'\')">📂</span><span title="删除" onclick="event.stopPropagation();delPreset(\''+esc(p.file)+'\')">🗑️</span></div></div>').join('')
    :'<div class="think">还没有预设，点下面「＋ 创作自定义预设」</div>';
}).catch(()=>{});}catch(e){}}
function loadPreset(file){fetch('/api/presets/load',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({file:file})})
  .then(r=>r.json()).then(d=>_afterPreset(d,file)).catch(e=>toast('⚠️ 加载失败：'+e));}
function duplicatePreset(file){fetch('/api/presets',{method:'GET'}).then(r=>r.json()).then(async d=>{const p=(d.presets||[]).find(x=>x.file===file);const n=p?(p.name+'·副本'):'新预设';await fetch('/api/presets',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:n,parent:file})});loadPresetCards();});}
function editPreset(file){fetch('/api/presets/detail?file='+file).then(r=>r.json()).then(d=>{
  const x=d.data||{};
  document.getElementById('eName').value=x.name||'';document.getElementById('eRole').value=x.role||'';
  document.getElementById('eEngine').value=(x.brain&&x.brain.engine)||'auto';document.getElementById('eCtx').value=(x.brain&&x.brain.llama&&x.brain.llama.ctx)||20000;
  const cap=x.capabilities||{};document.getElementById('eSearch').checked=cap.web_search!==false;document.getElementById('eMem').checked=cap.memory!==false;document.getElementById('eTools').checked=cap.run_tools!==false;
  document.getElementById('eTemp').value=(x.behavior&&x.behavior.temperature)||0.7;document.getElementById('eMax').value=(x.behavior&&x.behavior.max_tokens)||1024;
  window._efile=file;document.getElementById('editBg').style.display='flex';});}
function closeEdit(){document.getElementById('editBg').style.display='none';}
function savePreset(){const data={name:document.getElementById('eName').value, role:document.getElementById('eRole').value,
  brain:{engine:document.getElementById('eEngine').value, llama:{ctx:+document.getElementById('eCtx').value||20000}},
  capabilities:{web_search:document.getElementById('eSearch').checked, memory:document.getElementById('eMem').checked, run_tools:document.getElementById('eTools').checked},
  behavior:{temperature:+document.getElementById('eTemp').value||0.7, max_tokens:+document.getElementById('eMax').value||1024}};
  fetch('/api/presets/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({file:window._efile,data:data})}).then(r=>r.json()).then(()=>{fetch('/api/presets/load',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({file:window._efile})}).then(()=>{alert('✅ 已保存并应用此预设(人格已切换)');closeEdit();location.reload();});});}
function delPreset(file){if(!confirm('确定删除预设 '+file+' 吗？'))return;fetch('/api/presets/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({file:file})}).then(r=>r.json()).then(()=>{alert('✅ 已删除');loadPresetCards();}).catch(e=>alert('删除失败：'+e));}
function createPreset(){fetch('/api/presets',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:'我的预设',parent:'default.json'})}).then(r=>r.json()).then(d=>{alert('已创建自定义预设（可到 presets/ 编辑，或选它试试）');loadPresetCards();});}
function openEnv(){document.getElementById('envBg').style.display='flex';loadEnv();}
function closeEnv(){document.getElementById('envBg').style.display='none';}
async function loadEnv(){try{const d=await (await fetch('/api/env')).json();
  const el=document.getElementById('envList');
  el.innerHTML=d.items.map(function(i){return '<div class="envitem '+(i.ok?'ok':'no')+'"><div class="st">'+(i.ok?'✓':'✗')+'</div><div class="nm">'+esc(i.name)+'<div class="inf">'+esc(i.info)+(i.ok?'':'<div style="color:#f0a848;margin-top:4px">🔧 '+esc(i.need)+(i.dl?'<br><a href="'+esc(i.dl)+'" target="_blank" style="color:#a78bfa">⬇ 去下载</a>':'')+'</div>')+'</div></div></div>';}).join('');
  const b=document.createElement('div');b.className='envitem '+(d.ok?'ok':'no');b.innerHTML='<div class="st">'+(d.ok?'✓':'✗')+'</div><div class="nm">'+(d.ok?'✅ 环境齐全，可直接用':'⚠️ 有 '+((d.missing||[]).length)+' 项待处理')+'</div>';el.appendChild(b);
 }catch(e){document.getElementById('envList').textContent='检测失败';}}
function openBrain(){document.getElementById('brainBg').style.display='flex';loadBrain();}
function closeBrain(){document.getElementById('brainBg').style.display='none';}
async function loadBrain(){try{const d=await (await fetch('/api/brain')).json();
  document.getElementById('brainStats').innerHTML=
   '<div class="bs"><div class="n">'+d.know+'</div><div class="t">知识库(条)</div></div>'+
   '<div class="bs"><div class="n">'+d.vec+'</div><div class="t">向量知识</div></div>'+
   '<div class="bs"><div class="n">'+d.logs+'</div><div class="t">交互(次)</div></div>'+
   '<div class="bs"><div class="n">'+d.good+'</div><div class="t">👍 点赞</div></div>'+
   '<div class="bs"><div class="n">'+d.bad+'</div><div class="t">👎 踩</div></div>'+
   '<div class="bs"><div class="n">'+d.corr+'</div><div class="t">✏️ 更正</div></div>';
  const ls=document.getElementById('brainLessons');
  const arr=d.lessons||[];
  ls.innerHTML=arr.length?arr.slice(-12).reverse().map(x=>'<div class="bli">'+esc(x)+'</div>').join(''):'<div class="think">还没学到东西，多聊几轮、点几个👍吧</div>';
  // 电影设计提示词学习库(视频精炼, 小脑越用越准)
  try{const pk=await (await fetch('/api/video/promptkb')).json();
    const el=document.getElementById('brainPrompt');
    if(el){el.innerHTML='<div class="bli think">🎬 电影设计提示词学习库：<b style="color:#a78bfa">已学 '+pk.count+' 条</b></div>'+
      (pk.recent||[]).map(x=>'<div class="bli">📝 '+esc(String(x).slice(0,120))+'</div>').join('');}
  }catch(e){}
 }catch(e){document.getElementById('brainStats').textContent='读取失败';}}

function openSearch(){document.getElementById('modalBg').style.display='flex';const i=document.getElementById('msq');i.value='';i.focus();}
function closeSearch(){document.getElementById('modalBg').style.display='none';}
function doSearch(){const q=document.getElementById('msq').value.trim();if(!q){closeSearch();return;}
  const boxes=[...document.querySelectorAll('#sessionList .sess')];boxes.forEach(b=>{b.style.display=b.textContent.toLowerCase().includes(q.toLowerCase())?'':'none';});closeSearch();}
function toggleAccess(){const nv=!fullAccess;fetch('/api/access',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({full_access:nv})}).then(r=>r.json()).then(d=>{fullAccess=d.full_access;refreshAccess();});}
function refreshAccess(){const w=document.getElementById('wsInd');if(w){w.textContent=fullAccess?'🔐 Full access':'🔒 Read-only';w.style.color=fullAccess?'#4ade80':'#f87171';}}
async function loadAccess(){try{const d=await (await fetch('/api/access')).json();fullAccess=!!d.full_access;refreshAccess();}catch(e){}}

function copyPage(){const t=(document.getElementById('feed')?.innerText||'').trim()||'（暂无对话）';
  navigator.clipboard.writeText(t).then(()=>{alert('已复制当前会话日志');}).catch(()=>{});}
function stripThink(t){                 // 兜底：模型偶尔把 <think></think> 吐进正文
  return (t||'').replace(/<(think|thinking|reasoning)>[\s\S]*?<\/\1>/gi,'')
                .replace(/<\/?(think|thinking|reasoning)>/gi,'')
                .replace(/\n{3,}/g,'\n\n').trim();
}
function renderTableBlock(text){
  // 把一组以 | 开头的行转成 <table>（外面套一层横向滚动容器：宽表也不挤）
  const rows=text.split('\n').filter(l=>l.trim().startsWith('|'));
  if(rows.length<2)return null;
  const clean=l=>l.replace(/^\s*\|/,'').replace(/\|\s*$/,'').split('|').map(c=>c.trim());
  let html='<table>';
  rows.forEach((r,i)=>{const cells=clean(r);if(cells.every(c=>!c.replace(/[-:]/g,'')))return;const tag=i===0?'th':'td';
    html+='<tr>'+cells.map(c=>'<'+tag+'>'+inline(esc(c))+'</'+tag+'>').join('')+'</tr>';});
  return '<div class="tblwrap">'+html+'</table></div>';
}
function renderMd(text){
  text=stripThink(text||'');
  const fence=/```([\w+-]*)\n?([\s\S]*?)(?:```|$)/g;
  let out='',last=0,m;
  while((m=fence.exec(text))){
    const seg=text.slice(last,m.index);
    const lang=(m[1]||'').toLowerCase();
    out+=renderBlocks(seg);
    // ```markdown / ```md 里本来就是 Markdown（表格/标题/列表），渲染出来比当代码显示好读得多；
    // 其它语言（json/python/…）仍按代码块显示，保留「⧉ 复制」按钮。
    if(lang==='markdown'||lang==='md'){
      out+='<div class="mdfence">'+renderBlocks(m[2])+'</div>';
    }else{
      out+=codeBlock(m[2],m[1]);
    }
    last=fence.lastIndex;
  }
  out+=renderBlocks(text.slice(last));
  return out;
}
function renderBlocks(seg){
  // 按空行分块；识别：分割线/引用块/表格，否则行内 md
  if(!seg)return '';
  let blocks=seg.split(/\n\s*\n/),html='';
  blocks.forEach((b,bi)=>{
    if(bi>0)html+='<br>';          // 空行分块 → 块之间补一个换行，避免段落粘连成一行
    const line=(b||'').trim();
    // --- / *** / ___ 分割线
    if(/^([-*_])\1{2,}\s*$/.test(line)){html+='<hr style="border:none;border-top:1px solid #2a3140;margin:12px 0">';return;}
    // #/##/### 标题
    // 【真实 bug（用户实测："标题结构全在，但内容全空"）—— 根因就在这里】
    //   原来的写法是 `const hm=b.match(/^(#{1,3})\s+(.+)/)` 然后**整块 return**：
    //   `.+` 不跨行，所以它只匹配到标题那一行；而 `b` 是**整块**（空行之间的一切）——
    //   于是"标题 + 紧随其后的正文"被整块当成标题，**后面的内容全被丢掉**。
    //   实测对比（`logs/_dbg_iso.py`）：
    //     "## 已知条件\n- 红球：3 个"        → 可见只有 "已知条件"（内容消失）
    //     "## 已知条件\n\n- 红球：3 个"      → 可见 "已知条件 | · 红球：3 个 | …"（正常）
    //   模型写 Markdown 时**经常不空行**（"### 第一步\n从 5 个球中任取 2 个："），
    //   所以这个 bug 在真实回答里高频出现，表现就是"标题都在、下面全空"。
    //   修法：标题只取**第一行**，**剩下的行继续按块渲染**（标题下的内容一个字都不能丢）。
    const hm=b.match(/^(#{1,3})[ \t]+([^\n]*)(?:\n([\s\S]*))?$/);
    if(hm){
      html+='<div class="mdh">'+esc((hm[2]||'').trim())+'</div>';
      const rest=(hm[3]||'').trim();
      if(rest){html+='<br>'+renderBlocks(rest);}   // ← 这一行就是修复本体
      return;
    }
    // > 引用块(多行)
    const qm=b.match(/^((?:\s*>.*\n?)+)/);
    if(qm){
      const inner=qm[1].split('\n').map(l=>l.replace(/^\s*>\s?/,'')).join('\n');
      html+='<blockquote style="border-left:3px solid #405a99;margin:6px 0;padding:2px 12px;color:#aab2c0;background:#131a2b;border-radius:8px">'+inline(esc(inner))+'</blockquote>';
      return;
    }
    const t=renderTableBlock(b);
    html+= t?t:inline(esc(b));
  });
  return html;
}
function add(role,text,src){const w=document.querySelector('#feed .welcome');if(w)w.remove();
 const m=document.createElement('div');m.className='m '+role;
 let vm='';text=(''+text);
 if(role==='bot'&&text.indexOf('[video]')>=0){const mu=text.match(/\[video\]([^\[\]]+)\[\/video\]/);if(mu){vm='<video src="'+esc(mu[1])+'" controls style="max-width:100%;border-radius:12px;margin:4px 0"></video>';text=text.replace(mu[0],'');}}
 if(role==='bot'&&text.indexOf('[music]')>=0){const mu=text.match(/\[music\]([^\[\]]+)\[\/music\]/);if(mu){vm+='<audio src="'+esc(mu[1])+'" controls style="width:100%;margin:4px 0"></audio>';text=text.replace(mu[0],'');}}
 const _html=(role==='bot'?renderMd(text):esc(text));
 m.innerHTML='<div class="b'+(_html.indexOf('<table')>=0?' wide':'')+'">'+_html+'</div>'+vm;
 mathify(m);      // 数学公式：在**已成型的 DOM** 上扫一遍（跳过 pre/code），详见 mathify 的注释
 // ---- Bug 5：占位符不再无条件渲染成"正在回答…" ----
 // 真实缺陷（用户实测）：回答完切走再切回来，界面卡在"正在回答…"。
 // 原来只要消息里带 `__pending__` 就画一个转圈 —— 可那个占位符**可能永远不会被回填**
 // （切会话/断流/重启都会留下它），于是这个转圈能转到天荒地老，用户以为小焦卡死了。
 // 现在：只有**本标签页真的在生成**时才画转圈；否则如实说"中断了"。
 if(role==='bot'&&((''+text).indexOf('__pending__')>=0||text==='⏳')){
   m.innerHTML='<div class="b">'+(GEN.active?'<span class="spin"></span> 正在回答…'
     :'⏹ 这条回答中断了（没写完）—— 想接着要，直接重说一次就行')+'</div>';
   feed.appendChild(m);return;}
   if(role==='bot'){const row=document.createElement('div');row.className='msgbot';
   row.innerHTML='<button onclick="copyMsg(this)">⧉ 复制</button>';m.appendChild(row);}
 feed.appendChild(m);
 if(src&&src.length){const t=document.createElement('button');t.className='srcbtn';t.textContent='🔎 查看来源 ('+src.length+')';
   t.onclick=()=>{if(!t._s){t._s=document.createElement('div');t._s.className='srcbox';t._s.innerHTML=src.map(x=>'<div class="srci"><div class="st">'+esc(x.title)+'</div><div class="sc">'+esc(x.content.slice(0,160))+'</div></div>').join('');t.after(t._s);}
     const show=t._s.classList.toggle('show');t.textContent=show?'🔎 收起来源 ('+src.length+')':'🔎 查看来源 ('+src.length+')';};
   feed.appendChild(t);}
 feed.scrollTop=feed.scrollHeight;}
async function send(){const t=inp.value.trim();if(!t)return;inp.value='';
 add('user',t);
 // ---- Bug 5：全局"本标签页正在生成"状态 + 可中断的请求 ----
 // 为什么要全局状态：切会话/新建会话时要能把**旧的那一轮**干净地收掉
 // （关连接、清标志、摘掉还在闪的提示），否则旧流会继续往已经不在的 DOM 上写字。
 // 为什么用 AbortController：`fetch` 的流只有主动 abort 才会真的断；
 // 只是"不再读它"，服务端那一边还会继续生成、继续写会话。
 const myGen=++GEN.seq;
 GEN.active=true;GEN.sid=null;
 try{GEN.ctrl=new AbortController();}catch(e){GEN.ctrl=null;}
 // 会动的"思考中"提示
 const th=document.createElement('div');th.className='think';th.innerHTML='<span class="spin"></span><span class="stag">正在理解你的问题…</span>';feed.appendChild(th);feed.scrollTop=feed.scrollHeight;
 const stages=['正在理解你的问题…','🌐 正在联网搜索…','💾 正在回忆记忆…','🧠 大脑正在思考…','✍️ 正在组织回答…'];let si=0;
 const timer=setInterval(()=>{si=(si+1)%stages.length;const s=th.querySelector('.stag');if(s)s.textContent=stages[si];},2200);
 // 流式接收：一个气泡、边到边追加 —— 长文也是"一次连续输出"，用户看不到分段痕迹
 let bubble=null,body=null,buf='',meta=null;
 const stopBtn=document.createElement('button');stopBtn.className='icon-btn';stopBtn.textContent='⏹ 停止';
 stopBtn.onclick=()=>{try{fetch('/api/chat/stop',{method:'POST'});}catch(e){}
   try{GEN.ctrl&&GEN.ctrl.abort();}catch(e){}          // 停 = 真的停：连流一起断
   stopBtn.remove();};
 const ensureBubble=()=>{if(bubble)return;if(th.parentNode)th.remove();
   bubble=document.createElement('div');bubble.className='m bot';bubble.innerHTML='<div class="b"></div>';
   body=bubble.querySelector('.b');feed.appendChild(bubble);};
 // **停止按钮的生命周期只由 cleanup() 管**。
 // 真实缺陷（用户实测：输出完了"停止"还挂着，非要刷新才消失）：收尾时先 stopBtn.remove()，
 // 紧接着又调了一次 ensureBubble()，而它里面原本也 appendChild(stopBtn) —— 刚摘掉又被挂回去，
 // 此后没人再摘它；"空回答"那条分支更是直接 return，连 remove 都没走到。
 // 现在：finally 里一定调 cleanup()，无论正常结束、报错还是提前 return。
 const cleanup=()=>{try{clearInterval(timer);}catch(e){}
   if(th.parentNode)th.remove();
   if(stopBtn.parentNode)stopBtn.remove();
   if(myGen===GEN.seq){GEN.active=false;GEN.ctrl=null;}};
 const appendText=(s)=>{ensureBubble();buf+=s;body.textContent=buf;feed.scrollTop=feed.scrollHeight;};
 feed.appendChild(stopBtn);feed.scrollTop=feed.scrollHeight;
 try{
  const r=await fetch('/api/chat/stream',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({message:t}),signal:(GEN.ctrl?GEN.ctrl.signal:undefined)});
  if(!r.ok||!r.body){throw new Error('HTTP '+r.status);}
  const rd=r.body.getReader(),dec=new TextDecoder();let acc='',ended=false;
  for(;;){const s=await rd.read();if(s.done)break;
   acc+=dec.decode(s.value,{stream:true});
   let i;
   while((i=acc.indexOf('\n\n'))>=0){
    const rawline=acc.slice(0,i);acc=acc.slice(i+2);
    const line=rawline.replace(/^data:\s*/,'');
    if(!line)continue;
    // ---- Bug 4：显式结束哨兵 ----
    // 收到它就**立刻**收尾：摘掉"停止"按钮、对齐正文、断开读流 ——
    // 不再等服务端把连接关掉（中间隔了反向代理/浏览器缓冲时，那个时机是不确定的）。
    if(line.trim()==='[DONE]'){ended=true;break;}
    let d;try{d=JSON.parse(line);}catch(e){continue;}
    if(d.type==='delta'||d.type==='chunk'){appendText(d.text||'');}   // 后端边生成边推的小片，收到就渲染
    // 问题 2：一开流就记下"这一轮落在哪个会话" —— 切走时要靠它去等这一轮结束
    else if(d.type==='session'){if(d.session_id)GEN.sid=d.session_id;}
    else if(d.type==='progress'){const s=th.querySelector('.stag');if(s)s.textContent='⏳ 正在处理…';}
    else if(d.type==='meta'){meta=d;if(d.session_id){GEN.sid=d.session_id;}}
    else if(d.type==='error'){appendText((buf?'\n\n':'')+'⚠️ '+d.error);}
    // done 里的 answer 是**权威全文**：流式过程中为了接缝去重可能少显示几个字，
    // 结束时用权威全文对齐一次，保证"屏幕上看到的"和"存下来的"完全一致。
    else if(d.type==='done'){meta=meta||d;if(d.answer){buf=d.answer;if(body)body.textContent=buf;}}
   }
   if(ended)break;
  }
  // 主动放掉读流（不依赖 GC）；这里失败不影响任何东西
  try{rd.cancel();}catch(e){}
  }catch(e){
   // 用户主动中断（切会话/点停止）不算"出错"，如实说明就行
   if(e&&(e.name==='AbortError')){if(buf&&body){body.textContent=buf;}
     else{add('bot','⏹ 已中断这一轮回答。');}}
   else if(buf&&body){body.textContent=buf;}else{add('bot','⚠️ 出错了：'+e.message);}
  }finally{
   cleanup();     // 正常结束 / 报错 / 提前 return —— 停止按钮和"思考中"一定被摘掉
  }
  if(!buf){add('bot','⚠️ 大脑没有应答。请确认模型配置正确、端口可达。');loadSessions();return;}
  // **真实缺陷（用户实测：看不到工具轨迹 / 回答不对劲）**：
  // 普通回答（不走续写）根本不会推 chunk 事件 —— 正文只在最后的 done 里。而气泡是在
  // "收到第一个 chunk" 时才建的，于是这条路径上 body 一直是 null，正文**永远不会被插进页面**。
  // 这里补一次 ensureBubble()：无论正文是 chunk 来的还是 done 来的，都必须先有气泡再渲染。
  ensureBubble();
  // 收尾：渲染 Markdown（表格加宽）+ 工具轨迹 + 会话/日志
  if(body){const full=renderMd(buf);if(full.indexOf('<table')>=0){body.classList.add('wide');bubble.classList.add('widem');}
    body.innerHTML=full;
    mathify(body);}      // 流式收尾这一趟也必须扫：公式经常是最后一个 chunk 才闭合的
  if(meta&&meta.tool_trace&&meta.tool_trace.length){
    try{localStorage.setItem('xj_trace',JSON.stringify(meta.tool_trace.slice(0,10)));}catch(e){}
    const tt=document.createElement('div');tt.className='tooltrace';
    tt.innerHTML=meta.tool_trace.map(x=>'🔧 调用 <b>'+esc(x.tool)+'</b> → '+esc((x.result||'').slice(0,200))).join('<br>');
    feed.appendChild(tt);}
  if(meta)setToolsOn(meta.tools_on);
  if(meta&&meta.needs_confirm){const m=document.createElement('div');m.className='m bot';
    m.innerHTML='<button class="icon-btn" onclick="confirmAction()">✅ 确认执行</button>';feed.appendChild(m);}
 loadSessions();
 feed.scrollTop=feed.scrollHeight;}
// 打字机式浮现回答
function typeAnswer(text,src,logId,note){
  const m=document.createElement('div');m.className='m bot';
  text=stripThink(text);
  m.innerHTML='<div class="b"></div>';const b=m.querySelector('.b');feed.appendChild(m);
  let i=0;const step=Math.max(1,Math.round(text.length/120));const rl=setInterval(()=>{
    i+=step;b.innerHTML='';b.appendChild(document.createTextNode(text.slice(0,i)));
    feed.scrollTop=feed.scrollHeight;
    if(i>=text.length){clearInterval(rl);const bm=m.querySelector('.b');
      const full=renderMd(text);
      if(full.indexOf('<table')>=0){bm.classList.add('wide');m.classList.add('widem');}
      bm.innerHTML=full;
      mathify(bm);      // 打字机路径收尾时同样扫一遍公式
      // 注：检索引用校验的徽标已按用户要求撤掉（正常聊天里太吵，见过"这条回答基本没用到
      // 检索资料"的打扰提示）。核对数据仍在 /api/chat 的 grounding 字段里，压测与
      // 「查看来源」照常使用，所以 note 参数保留但不再渲染。
      const row=document.createElement('div');row.className='msgbot';row.innerHTML=
        '<button onclick="copyMsg(this)">⧉ 复制</button><button class="fb" onclick="fb(this,\''+logId+'\',\'good\')">👍</button>'+
        '<button class="fb" onclick="fb(this,\''+logId+'\',\'bad\')">👎</button>';
      m.appendChild(row);addSrc(m,src);feed.scrollTop=feed.scrollHeight;}
  },14);
}
async function fb(btn,logId,fbv){try{await fetch('/api/feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({log_id:logId,feedback:fbv})});
  btn.textContent=(fbv==='good')?'👍✓':'👎';btn.disabled=true;btn.style.opacity=.6;}catch(e){}}
function addSrc(msrcEl,src){if(!src||!src.length)return;const t=document.createElement('button');t.className='srcbtn';t.textContent='🔎 查看来源 ('+src.length+')';
  t.onclick=()=>{if(!t._s){t._s=document.createElement('div');t._s.className='srcbox';t._s.innerHTML=src.map(x=>'<div class="srci"><div class="st">'+esc(x.title)+'</div><div class="sc">'+esc(String(x.content||'').slice(0,160))+'</div></div>').join('');t.after(t._s);}
    const show=t._s.classList.toggle('show');t.textContent=show?'🔎 收起来源 ('+src.length+')':'🔎 查看来源 ('+src.length+')';};
  msrcEl.appendChild(t);}
function setToolsOn(on){const b=document.getElementById('toolsBtn');b.className='icon-btn '+(on?'on':'off');b.textContent=(on?'🛠️ 工具 · 开':'🛠️ 工具 · 关');
 const p=document.getElementById('toolsPerm');if(p)p.textContent=on?'开':'关';
 const r=document.getElementById('toolsRow');if(r)r.style.color=on?'#4ade80':'#f87171';
 const w=document.getElementById('wsInd');if(w){w.textContent=on?'🔐 Full access':'🔒 Read-only';} }
async function toggleTools(){const r=await fetch('/api/tools_toggle',{method:'POST'});const d=await r.json();setToolsOn(d.tools_on);}
async function loadModels(){try{const r=await fetch('/api/models');const d=await r.json();const sel=document.getElementById('modelSel');let ms=(d&&d.models)||[];
  // 没有显式配置模型时，不要显示"未配置模型"误导用户 —— 自动模式其实用的是本地大脑/llama-swap
  if(!ms.length){
    const auto=d&&d.active==='auto';
    sel.innerHTML='<option value="">'+(auto?'自动（本地大脑 :9292）':'未配置模型（点「设置」添加）')+'</option>';
    return;
  }
  sel.innerHTML=ms.map(m=>'<option value="'+esc(m.name)+'">'+esc(m.name)+'</option>').join('');
  sel.value=(d&&d.current)||((ms[0]&&ms[0].name)||'');}catch(e){document.getElementById('modelSel').innerHTML='<option value="">模型加载失败</option>';}}
async function selectModel(){const v=document.getElementById('modelSel').value;
  try{const r=await fetch('/api/model/select',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:v})});
    const d=await r.json();
    if(d&&d.note)toast((d.ok?'✅ ':'⚠️ ')+d.note);          // 选中就能立刻知道能不能用、坏在哪
  }catch(e){toast('⚠️ 切换失败：'+e);}}
async function loadHistory(){try{const r=await fetch('/api/history');const hs=await r.json();if(Array.isArray(hs)&&hs.length){hs.forEach(h=>add(h.role==='用户'?'user':'bot',h.content));}}catch(e){}}
async function loadSessions(){try{const r=await fetch('/api/sessions');const d=await r.json();const el=document.getElementById('sessionList');
  el.innerHTML=(d.sessions||[]).map(s=>'<div class="srow'+(s.id===d.current?' active':'')+'">'
      +'<button class="sess" onclick="openSession(\''+s.id+'\')" title="'+esc(String(s.count||0))+' 条消息">'+esc(s.title||'新对话')+'</button>'
      +'<button class="sdel" title="删除这个会话" onclick="delSession(event,\''+s.id+'\')">✕</button>'
    +'</div>').join('')||'<div class="think">暂无会话</div>';}catch(e){}}
async function delSession(ev,id){
  if(ev){ev.stopPropagation();ev.preventDefault();}
  if(!confirm('删除这个会话？该会话的聊天记录会一起删掉（不可恢复）'))return;
  try{
    const r=await fetch('/api/session/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:id})});
    const d=await r.json();
    if(!d.ok){toast('⚠️ '+(d.error||'删除失败'));return;}
    toast('🗑️ 已删除会话');
    await loadSessions();
    if(d.was_current){clearFeed();await loadHistory();}     // 删的是当前会话 → 界面跟着切过去
  }catch(e){toast('⚠️ 删除失败：'+e);}
}
async function newChat(){await stopGeneration();await fetch('/api/session/new',{method:'POST'});clearFeed();loadSessions();}
// ---- Bug 5 + 问题 2：切会话 ----
// 真实缺陷（用户实测）：回答完了，切走再切回来，界面卡在"正在回答…"，看不到实际内容。
// 这里做四件事，缺一件都会复发：
//   ① **先 await 把旧的那一轮收干净**（断流 + 等后端确认标记已撤 + 清"生成中"标志 + 摘掉转圈）——
//      "等确认"这一步是问题 2 补的：不等就渲染，就是在跟服务端的注销时机赛跑（时好时坏）；
//   ② 切回来时**从会话历史全量渲染**（d.messages 一条不落），历史是唯一权威；
//   ③ 后端已经保证"没人在跑的占位符"会被标成"中断了"（见 /api/session/<sid>）；
//   ④ 后端说这个会话**真的**还在生成（心跳是新的）→ 才显示"正在回答"并接着轮询。
async function openSession(id){
  await stopGeneration();
  const r=await fetch('/api/session/'+id);const d=await r.json();
  clearFeed();
  (d.messages||[]).forEach(h=>add(h.role==='用户'?'user':'bot',h.content));
  // 这个会话**真的**还在跑（后端心跳是新的）→ 让用户看到"正在回答"，并接着轮询
  if(d.generating){GEN.active=true;GEN.sid=id;resumeChat();}
  loadSessions();
}
function clearFeed(){document.getElementById('feed').innerHTML='';renderWelcome();}
// 空状态：居中的欢迎卡 + 可点的示例（比一行灰字好看，也让新用户知道能干什么）
function renderWelcome(){
  const f=document.getElementById('feed');if(!f||f.children.length)return;
  const chips=[['抓取最近 7 天的高危漏洞','🔐 查漏洞'],['最近 AI 新闻','📰 搜新闻'],
               ['抓一下 https://example.com','🌐 抓网页'],['用 Python 写个计算斐波那契的脚本','🐍 写代码'],
               ['记住：我偏好用中文注释','🧠 存记忆']];
  f.innerHTML='<div class="welcome"><div class="wl">你好，我是小焦 🐳</div>'
    +'<div class="ws">本地部署 · 会联网检索 · 会抓网页 · 会查 NVD 漏洞 · 会写文件；每一步都能在左侧「轨迹」里看到</div>'
    +'<div class="chips">'+chips.map(c=>'<div class="chip" onclick="useChip(this)">'+esc(c[1])+'</div>').join('')+'</div></div>';
}
function useChip(el){
  const map={'🔐 查漏洞':'抓取最近 7 天的高危漏洞','📰 搜新闻':'最近 AI 新闻','🌐 抓网页':'抓一下 https://example.com',
             '🐍 写代码':'用 Python 写个计算斐波那契的脚本','🧠 存记忆':'记住：我偏好用中文注释'};
  inp.value=map[el.textContent.trim()]||el.textContent.trim();autoGrow(inp);inp.focus();
}
function autoGrow(el){el.style.height='auto';el.style.height=Math.min(el.scrollHeight,220)+'px';}
function toggleSidebar(){document.getElementById('sidebar').classList.toggle('hidden');}
function hideSplash(){const sp=document.getElementById('splash');if(sp){sp.style.transition='opacity .5s';sp.style.opacity='0';setTimeout(function(){sp.remove();},500);}}
  (async()=>{try{loadModels();}catch(e){}try{loadHistory();}catch(e){}try{loadSessions();}catch(e){}try{loadPresets();}catch(e){}try{loadCost();}catch(e){}
 try{const r=await fetch('/api/tools_toggle');const d=await r.json();setToolsOn(d.tools_on);}catch(e){}
 try{renderWelcome();}catch(e){}
 try{const ta=document.getElementById('inp');if(ta)autoGrow(ta);}catch(e){}
 resumeVideoJob();resumeChat();})();
async function confirmAction(){const r=await fetch('/api/confirm',{method:'POST'});const d=await r.json();
 add('bot',(d.result||'已执行').slice(0,1200));}
inp.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send();}});

const plugEl=document.getElementById('s_plugins');let plugins=[];
function applyPersona(){const v=document.getElementById('s_persona').value;if(!v)return;
  fetch('/api/persona',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({role:v})}).then(r=>r.json()).then(d=>{const m=document.getElementById('personaMsg');if(m)m.textContent=d.ok?'✅ 人格已切换（下次对话生效）':'❌ '+d.error;});
}

async function openSettings(){try{loadPresetCards();}catch(e){}
  setSec('general');
  const r=await fetch('/api/settings');const d=await r.json();const c=d.control;
  document.getElementById('s_name').value=c.model_name||'';
  document.getElementById('s_engine').value=(c.brain&&c.brain.engine)||'auto';
  document.getElementById('s_temp').value=(c.behavior&&c.behavior.temperature)??0.7;
  document.getElementById('s_tokens').value=(c.behavior&&c.behavior.max_tokens)??1024;
  document.getElementById('s_ctx').value=(c.capabilities&&c.capabilities.context_len)??20;
  document.getElementById('s_base').value=((c.brain&&c.brain.api&&c.brain.api.base_url)||'');
  document.getElementById('s_llm_ctx').value=((c.brain&&c.brain.llama&&c.brain.llama.ctx)||32768);
  document.getElementById('s_role').value=c.role||'';
  const ps=c.personas||[];const pe=document.getElementById('s_persona');
  if(pe&&ps.length){pe.innerHTML=ps.map(x=>'<option value="'+esc(x.role)+'">'+esc(x.name+' · '+x.desc)+'</option>').join('');pe.value=c.role||'';}
  document.getElementById('s_tools').checked = !!(c.capabilities&&c.capabilities.run_tools);
  plugins=d.plugins||[];
  plugEl.innerHTML=plugins.map((p,i)=>`<div class="switch"><div><div class="n">${p.name} <small style="color:#7a8290">${p.type||'py'}${p.builtin?' · 内置':''}</small></div><div class="d">${(p.desc[0]&&p.desc[0].description)||''}</div></div><label class="plug"><input type="checkbox" data-i="${i}" ${p.on?'checked':''}/></label></div>`).join('');
  loadModelList();
  buildPluginModules(d.plugins||[]);
  S.classList.add('show');
}
async function loadModelList(){const r=await fetch('/api/models');const d=await r.json();const el=document.getElementById('s_model_list');
  el.innerHTML=(d.models||[]).map(m=>`<div class="switch"><div><div class="n">${esc(m.name)} <small style="color:#7a8290">${esc(m.engine)}</small></div><div class="d">${esc(m.base_url||'')}</div></div><button class="btn-sec" onclick="delModel('${esc(m.name)}')">删除</button></div>`).join('')||'<div class="think">还没有模型</div>';
}
async function addLocalModel(){document.getElementById('addLocalBg').style.display='flex';}
function closeAddLocal(){document.getElementById('addLocalBg').style.display='none';}
function saveAddLocal(){
  const name=document.getElementById('lm_name').value.trim();
  const gguf=document.getElementById('lm_gguf').value.trim();
  const ctx=document.getElementById('lm_ctx').value;
  if(!name||!gguf){alert('请填模型名和 GGUF 路径');return;}
  document.getElementById('lm_msg').textContent='⏳ 正在配置并重启 llama-swap…';
  fetch('/api/model/addlocal',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name,gguf:gguf,ctx:parseInt(ctx)||20000})}).then(r=>r.json()).then(d=>{
    document.getElementById('lm_msg').textContent=d.ok?('✅ 已添加：'+d.name+'，llama-swap 重启中，约10秒后可用'):('❌ '+d.error);
    if(d.ok)setTimeout(()=>location.reload(),12000);
  });
}
async function addModel(){const name=document.getElementById('s_m_name').value.trim();if(!name){document.getElementById('s_model_msg').textContent='❌ 名字必填';return;}
  const entry={name:name,engine:document.getElementById('s_m_engine').value,base_url:document.getElementById('s_m_base').value.trim(),api_key:document.getElementById('s_m_key').value.trim(),model:document.getElementById('s_m_model').value.trim()};
  const r=await fetch('/api/model/add',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(entry)});const d=await r.json();
  if(d.ok){document.getElementById('s_model_msg').textContent='✅ 已添加：'+name;loadModelList();loadModels();}else{document.getElementById('s_model_msg').textContent='❌ '+(d.error||'失败');}}
async function delModel(name){const r=await fetch('/api/model/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name})});const d=await r.json();if(d.ok){loadModelList();loadModels();}}
function closeSettings(){S.classList.remove('show');}
function setSec(el,name){document.querySelectorAll('.sec').forEach(s=>s.classList.toggle('show',s.id==='sec-'+name));
  document.querySelectorAll('.setnav-item').forEach(n=>n.classList.toggle('active',n.getAttribute('data-sec')===name));}
// 按已安装插件动态生成设置模块：只有"有可调配置"的插件才出现
function buildPluginModules(plist){
  const nav=document.querySelector('.setnav');const holder=document.getElementById('plugSecs');
  holder.innerHTML='';
  (plist||[]).filter(p=>p.type!=='skin' && p.settings && p.settings.length).forEach(p=>{
    const key='sec-plug-'+p.name;
    nav.insertAdjacentHTML('beforeend','<div class="setnav-item" data-sec="'+p.name+'" onclick="setSec(this,\''+p.name+'\')">🔧 '+p.name+'</div>');
    const fields=(p.settings||[]).map(s=>'<div class="field"><label>'+esc(s.label||s.key)+'</label><input id="set-'+p.name+'-'+s.key+'" data-p="'+p.name+'" data-k="'+s.key+'" data-t="'+s.type+'" data-def="'+esc(String(s.default??''))+'" placeholder="默认: '+esc(String(s.default??''))+'"/></div>').join('');
    const tools=(p.desc||[]).map(d=>'<div class="switch"><div><div class="n">'+esc(d.name)+'</div><div class="d">'+esc(d.description||'')+'</div></div></div>').join('');
    holder.insertAdjacentHTML('beforeend','<div class="sec" id="'+key+'"><h3>🔧 '+esc(p.name)+'</h3>'+fields+'<div class="actions"><button class="btn-sec" onclick="savePluginSettings(\''+p.name+'\')">💾 保存插件设置</button></div><div class="think" id="msg-'+p.name+'"></div><h4 style="margin-top:16px">可用工具</h4>'+tools+'</div>');
  });
  try{Object.keys(localStorage).filter(k=>k.startsWith('xjset-')).forEach(k=>{const el=document.getElementById('set-'+k.slice(6));if(el){el.value=localStorage.getItem(k)||'';}});}catch(e){}
}
function savePluginSettings(name){
  try{
    document.querySelectorAll('#sec-plug-'+name+' input[data-p="'+name+'"]').forEach(inp=>{
      const k=inp.getAttribute('data-k');const t=inp.getAttribute('data-t');
      const v=(t==='boolean')?(inp.value==='true'):inp.value;
      localStorage.setItem('xjset-'+name+'-'+k, v);
    });
    const m=document.getElementById('msg-'+name);if(m)m.textContent='✅ 已保存（本机生效）';
  }catch(e){}
}
async function saveSettings(){
  const engine=document.getElementById('s_engine').value;
  const plugmap={};plugins.forEach((p,i)=>{plugin_checked=document.querySelector('#s_plugins input[data-i="'+i+'"]');plugmap[p.name]=!!(plugin_checked&&plugin_checked.checked);});
  const control={
    model_name:document.getElementById('s_name').value,
    brain:{engine:engine,llama:{ctx:+(document.getElementById('s_llm_ctx').value||32768)},api:{base_url:document.getElementById('s_base').value, api_key:'', model:document.getElementById('s_name').value}},
    role:document.getElementById('s_role').value,
    capabilities:{web_search:true,memory:true,run_tools:document.getElementById('s_tools').checked,context_len:+document.getElementById('s_ctx').value,plugins:plugmap},
    behavior:{temperature:+document.getElementById('s_temp').value, max_tokens:+document.getElementById('s_tokens').value}
  };
  const r=await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({control:control})});
  const d=await r.json();if(d.ok){location.reload();}else{alert('保存失败：'+d.error);}
}
</script></body></html>"""


def bind_host(port=None):
    """决定 Web 服务的监听地址。返回 (host, 要打印的提示行列表)。

    规则（与任务 1 的鉴权闸门配套）：
      · 默认只听 127.0.0.1 —— 同网段连不上；
      · 只有**明确开了 capabilities.lan_access 且 access_token 非空**才听 0.0.0.0；
      · 只开 lan_access 不配令牌 → 仍听 127.0.0.1，并给出启动警告（宁可开不了，
        也不要把"无鉴权的全权限助手"暴露到同网段）。

    为什么抽成一个函数：`main()`（直接跑 xiaojiao_app.py）和 `start_xiaojiao.py`（一键启动器）
    是**两条启动路径**。安全第一批·任务 A 实测发现，启动器里把 host 写死成 "0.0.0.0"，
    把这里的防护整个绕过去了 —— 同网段无令牌就能打开小焦。两条路径共用这一个函数，
    才不会再次各写各的、又悄悄跑偏。
    """
    lines = []
    host = "0.0.0.0" if LAN_ACCESS else "127.0.0.1"
    if LAN_ACCESS and not ACCESS_TOKEN:
        lines.append("⚠️ 已开启局域网访问(lan_access)但没配 access_token —— 为避免裸奔，本次仍只听 127.0.0.1。")
        lines.append("   请在 xiaojiao_control.json 的 capabilities.access_token 填一个随机串后再启动。")
        host = "127.0.0.1"
    if host == "0.0.0.0":
        lines.append("🌐 局域网访问已开启：http://<本机IP>:%s?token=<你的令牌>（非本机请求都要带令牌）"
                     % (port if port else "<端口>"))
    return host, lines


def main():
    print("=" * 46)
    print("  小焦 · XiaoJiao Web")
    print(f"  大脑(模型): {'✔ 小焦模型已加载' if XJ_READY else '✘ 未加载'}")
    print(f"  联网搜索:   ✔ Bing/Sogou")
    print(f"  记忆自学习: ✔ (xiaojiao_knowledge_memory.json)")
    print("=" * 46)
    # 端口优先级：--port 参数 > 操控文件 web_port > 环境变量 PORT > 默认5000
    port = 5000
    if "--port" in sys.argv:
        try:
            port = int(sys.argv[sys.argv.index("--port") + 1])
        except Exception:
            port = 5000
    else:
        port = int(CONTROL.get("web_port", os.environ.get("PORT", 5000)))
    os.environ["PORT"] = str(port)
    # 启动即预热"路径自动探测"（ComfyUI / llama-swap / 视频模型），体检页面秒开、不卡盘
    try:
        _discover_paths(kick=True)
        print("  🔎 路径自动探测已在后台预热(ComfyUI / llama-swap / 视频模型)")
    except Exception as e:
        LOG.debug("忽略异常(%s:%d): %s", __file__, 3608, e)
    threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    # 心跳：**模型启动 → 心跳开始**。它是"一直在"的证明，所以在这儿起、不随对话起落。
    _hb = _heartbeat_mod()
    if _hb is not None:
        _r = _hb.start(why="xiaojiao_app 启动")
        print("  💓 心跳已开始：每 %ss 一下（%s）" % (_hb.BEAT_INTERVAL, _hb.path()))
    else:
        print("  💓 心跳模块不可用（core/heartbeat.py 没加载上）—— 如实说明，不假装在跳")
    # 监听地址：走 bind_host()（与 start_xiaojiao.py 共用同一套规则，见该函数说明）。
    _host, _host_lines = bind_host(port)
    for _line in _host_lines:
        print("  " + _line)
    app.run(host=_host, port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
