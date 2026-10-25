# plugins/rea.py —— 把 REA（Reverse Engineer Anything）接进小焦（2026-10-17）
#
# 【它是什么】REA 是一个逆向工程工具集（npm 包 rea-agents，MIT 在它自己的仓库里），
#   跑起来就是一个 MCP stdio server，**229 个工具**：PE / ELF / Mach-O / .NET / APK / IPA /
#   JS / WASM 的静态检查、反编译、xref、字符串搜索、证据导出，还有 frida 动态注入、GDB、
#   模型文件（GGUF / safetensors）检查等。官方说明：从终端或 agent 里逆向任何东西。
#
# 【为什么只包三个工具，而不是把 229 个都挂上去】
#   小焦的大脑是本机 4B 小模型，工具表按意图装载。229 个名字塞进去的后果是可预料的：
#   它会在工具海里乱试、选错工具，甚至选一个参数根本对不上的。
#   所以这里只暴露三个**粗粒度**入口：
#     · rea_status  —— 服务活着没、版本、有多少工具（出问题先看这个）
#     · rea_tools   —— 用关键词搜它有哪些工具（把 229 个变成一个可检索的目录）
#     · rea_call    —— 调指定的那个工具，参数用 JSON 传
#   需要新能力时不加工具名，先 rea_tools 搜、再 rea_call 调 —— 这与小焦"按意图装载"的思路一致。
#
# 【怎么配】控制文件 xiaojiao_control.json 里加一块（或走环境变量 REA_CMD / REA_CWD）：
#   "rea": {
#       "on": true,
#       "cmd": ["C:\\Windows\\System32\\cmd.exe", "/c", "node",
#               "C:\\xiaojiao\\rea-mcp\\node_modules\\rea-agents\\scripts\\rea.mjs", "mcp"],
#       "cwd": "C:\\xiaojiao\\rea-mcp",
#       "timeout_s": 120,          # 单次工具调用的等待上限（反编译这类会慢）
#       "max_chars": 4000          # 返回给模型的文本上限（超了截断并说明）
#   }
#   启动器不存在时：**三个工具一个都不注册**（不糊一个假工具给模型），只在日志里说明。
#
# 【铁的三条】
#   ① 一律返回中文说明，绝不抛异常（小焦那层 run_plugin 会把异常吞成空串，用户什么都看不到）；
#   ② 结果是空的就如实说"没有结果"，不编内容；
#   ③ 明文风险由 REA 自己担：它做什么我们就返回什么，小焦这里不替它解释成"已核验"。
import atexit
import json
import logging
import os
import threading

LOG = logging.getLogger(__name__)

DEFAULT_HOST = r"C:\xiaojiao\rea-mcp"
_ENV_CMD = "REA_CMD"
_ENV_CWD = "REA_CWD"

# 三个粗粒度入口（名字短、说明里写清"什么时候用它"，4B 才好选）
_TOOLS = [
    {"name": "rea_status",
     "description": "REA 逆向引擎：查它在不在线、版本、可用工具数（不启动任何程序）",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "rea_tools",
     "description": "REA 逆向引擎：搜它能做哪些分析（pe、apk、反编译、frida、gguf 等）",
     "parameters": {"type": "object",
                    "properties": {"keyword": {"type": "string", "description": "关键词，空则列前 30 个"},
                                   "limit": {"type": "integer", "description": "最多返回几条，默认 20"}},
                    "required": []}},
    {"name": "rea_call",
     "description": "REA 逆向引擎：按工具名精确调用（tool+args）。不确定用哪个就先用 rea_do",
     "parameters": {"type": "object",
                    "properties": {"tool": {"type": "string", "description": "REA 工具名，如 open_binary"},
                                   "args": {"type": "object", "description": "该工具的参数，JSON 对象；没有就传 {}"}},
                    "required": ["tool"]}},
    # ---- 意图入口：4B 只要说"想干什么"，选工具和拼参数由载体来做（见 _route / _fill_args）----
    {"name": "rea_do",
     "description": "REA 逆向：用一句话说想干什么（如 反编译 main、看哈希、列出字符串），载体自己选工具并调",
     "parameters": {"type": "object",
                    "properties": {"intent": {"type": "string", "description": "要干什么，中文即可"},
                                   "target": {"type": "string", "description": "目标文件路径，可省（上次打开过的会沿用）"},
                                   "focus": {"type": "string", "description": "函数名/地址/要搜的词，可省"}},
                    "required": ["intent"]}},
    {"name": "rea_help",
     "description": "REA 逆向：查某个工具要哪些参数（不知道 rea_do 选对了没、或要精确调时用）",
     "parameters": {"type": "object",
                    "properties": {"tool": {"type": "string", "description": "工具名，如 open_binary"}},
                    "required": ["tool"]}},
]

# REA 的报错是结构化 JSON，直接丢给 4B 模型等于没给。这里把最常见的几类翻成人话 + 下一步该干什么。
_ERR_HINTS = {
    "provider_unavailable": "分析引擎没装或不可用（REA 的深层分析要 Ghidra / Hopper 这类外部引擎）。"
                            "目标文件先用 open_binary 打开是能用的，识别格式、哈希、架构都不需要引擎",
    "invalid_input": "参数和它声明的 schema 对不上 —— 先 rea_tools 搜这个工具，看必填参数叫什么",
    "invalid_request": "参数和它声明的 schema 对不上 —— 先 rea_tools 搜这个工具，看必填参数叫什么",
    "not_found": "它没找到你指的目标（路径写错，或还没用 open_binary 打开过）",
    "unsupported": "这个文件类型它不认，换一个工具或者先 open_binary 看格式",
    "timeout": "它自己超时了 —— 目标太大，或者换更具体的工具（比如先 overview 再按需取细节）",
    "permission": "权限不够（读不到那个文件，或者要提权）",
}

_client = {"obj": None, "tools": None, "err": "", "at": 0.0}
_lock = threading.Lock()


def _load_cfg():
    """读配置：控制文件 > 环境变量 > 默认值。永远返回 dict，不抛。"""
    cfg = {}
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        p = os.path.join(root, "xiaojiao_control.json")
        if os.path.exists(p):
            d = json.load(open(p, encoding="utf-8"))
            c = d.get("rea")
            if isinstance(c, dict):
                cfg.update(c)
    except Exception as e:      # noqa: silent-ok — 读不到就当没配
        LOG.debug("读 rea 配置失败（忽略）：%s", e)
    if os.environ.get(_ENV_CMD):
        try:
            cfg["cmd"] = json.loads(os.environ[_ENV_CMD])
        except Exception:      # noqa: silent-ok — 不是 JSON 就按空格切
            cfg["cmd"] = os.environ[_ENV_CMD].split()
    if os.environ.get(_ENV_CWD):
        cfg["cwd"] = os.environ[_ENV_CWD]
    host = os.path.normpath(str(cfg.get("cwd") or DEFAULT_HOST))
    cfg["cwd"] = host
    if not cfg.get("cmd"):
        entry = os.path.join(host, "node_modules", "rea-agents", "scripts", "rea.mjs")
        # 直接起 node，不套 cmd.exe（实测：套一层会让 node 变成孤儿进程、占着管道不放手，
        # 调用方以为没结束就干等 —— 见 core/mcp_stdio.py 的 stop() 说明）
        cfg["cmd"] = ["node", entry, "mcp"]
    cfg.setdefault("on", True)
    cfg.setdefault("timeout_s", 120)
    cfg.setdefault("max_chars", 4000)
    try:
        cfg["timeout_s"] = max(10, int(cfg.get("timeout_s") or 120))
        cfg["max_chars"] = max(400, int(cfg.get("max_chars") or 4000))
    except Exception:      # noqa: silent-ok — 配错了就用默认
        cfg["timeout_s"], cfg["max_chars"] = 120, 4000
    return cfg


def _launcher_ok(cfg):
    """启动器在不在（只查文件，不起进程 —— 插件加载时不许拖慢启动）。

    判据逐条看命令行里的每个参数：
      · 带路径分隔符、或后缀是 .mjs/.js/.cjs/.py 的，按**文件**检查，缺了就拦；
      · 只有 .exe 名字（如 cmd.exe）的，按 PATH 查；
      · 其余裸名字（如 node、python）放行 —— 真缺了也会在 start() 里报中文错。
    【为什么不能只查第一个像路径的】踩过：命令行是 [python.exe, 不存在的脚本.py] 时，
    第一个参数本身存在（python.exe），于是校验通过、注册了工具，真调用才发现脚本没了。
    """
    cmd = cfg.get("cmd") or []
    if not cmd:
        return False, "没有配置启动命令"
    import re as _re
    import shutil
    for part in cmd:
        s = str(part)
        # 开关（-c / /c 这种）不是路径：踩过 —— cmd.exe 的 /c 带斜杠，被当成文件路径，
        # 于是"启动器不存在"、工具一个都不注册，真机上整条接线静默失效。
        if not s or _re.match(r"^[-/][A-Za-z]{1,4}$", s):
            continue
        low = s.lower()
        is_script = low.endswith((".mjs", ".js", ".cjs", ".py"))
        has_sep = ("\\" in s) or ("/" in s)
        if is_script or has_sep:
            if not os.path.exists(s):
                return False, "启动器不存在：%s" % s
        elif low.endswith(".exe"):
            if not shutil.which(s):
                return False, "启动器不在 PATH 上：%s" % s
    return True, ""


def _client_obj(cfg=None):
    """拿（必要时起）MCP 客户端。返回 (client, err)。"""
    cfg = cfg or _load_cfg()
    with _lock:
        cur = _client["obj"]
        if cur is not None and cur.alive():
            return cur, ""
        try:
            from core.mcp_stdio import McpStdio
        except Exception as e:
            return None, "core/mcp_stdio.py 没加载上：%s" % e
        c = McpStdio(cmd=cfg["cmd"], cwd=cfg["cwd"], tag="rea",
                     init_timeout=max(60, cfg["timeout_s"]), log=LOG)
        _client["obj"] = c
        _client["tools"] = None
        _client["err"] = ""
    return c, ""


def _tool_list(cfg=None):
    """列 REA 的工具（缓存；服务重启后自动重取）。返回 (list, err)。"""
    cfg = cfg or _load_cfg()
    c, err = _client_obj(cfg)
    if err:
        return None, err
    if _client["tools"] is not None:
        return _client["tools"], ""
    tools, err = c.tools(timeout=max(30, cfg["timeout_s"]))
    if err:
        _client["err"] = err
        return None, "列工具失败：%s" % err
    _client["tools"] = tools or []
    LOG.info("REA 已连上：%s 个工具", len(_client["tools"]))
    return _client["tools"], ""


def _clip(text, n):
    t = str(text or "").strip()
    if len(t) <= n:
        return t
    return t[:n] + "\n……（超出 %d 字，已截断；原文共 %d 字）" % (n, len(t))


def _friendly_error(raw):
    """REA 的报错是 {"error":{"code":...,"message":...,"remediation":{...}}} —— 翻成人话。

    为什么必须做这一层：4B 小模型看到嵌套 JSON 只会复述或者干脆忽略；
    而这类报错恰恰是最需要"下一步该干什么"的时候（比如缺引擎、参数不对）。
    翻不出来就原样返回（截断），绝不假装成功。
    """
    s = str(raw or "").strip()
    if not s.startswith("{"):
        return s
    try:
        d = json.loads(s)
    except Exception:      # noqa: silent-ok — 不是 JSON 就原样给
        return s
    err = (d or {}).get("error") or {}
    if not isinstance(err, dict) or not err:
        return s
    code = str(err.get("code") or "").strip()
    msg = str(err.get("message") or "").strip()
    hint = _ERR_HINTS.get(code, "")
    rem = ((err.get("remediation") or {}).get("action")
           or (err.get("remediation") or {}).get("hint") or "")
    parts = ["REA 报错%s：%s" % (("（%s）" % code) if code else "", msg or "没有说明")]
    if hint:
        parts.append("怎么办：%s" % hint)
    if rem and rem != msg:
        parts.append("它自己给的建议：%s" % str(rem)[:160])
    return "\n".join(parts)


def _do_status(cfg):
    c, err = _client_obj(cfg)
    if err:
        return "REA 起不来：%s" % err
    if not c.alive():
        if not c.start():
            return "REA 起不来：%s" % (c.last_error or "未知原因")
    info = getattr(c, "server_info", {}) or {}
    tools, terr = _tool_list(cfg)
    if terr:
        return "REA 连上了但列不了工具：%s" % terr
    return ("REA 在线：%s v%s ｜ 可用工具 %d 个 ｜ 工作目录 %s ｜ 单次最多等 %d 秒\n"
            "用法：先 rea_call 调 open_binary（参数 path）打开目标，再调别的分析工具；"
            "不知道用哪个就 rea_tools 搜。\n"
            "注意：识别格式、哈希、架构不需要额外引擎，但反编译这类深层分析要本机装"
            "Ghidra 或 Hopper，没装会报 provider_unavailable。"
            % (info.get("name", "rea"), info.get("version", "?"), len(tools or []),
               cfg["cwd"], cfg["timeout_s"]))


def _do_tools(cfg, params):
    tools, err = _tool_list(cfg)
    if err:
        return "REA 工具列表取不到：%s" % err
    kw = str((params or {}).get("keyword") or "").strip().lower()
    try:
        limit = int((params or {}).get("limit") or 20)
    except Exception:      # noqa: silent-ok
        limit = 20
    limit = max(1, min(60, limit))
    rows = tools or []
    if kw:
        rows = [t for t in rows
                if kw in str(t.get("name") or "").lower()
                or kw in str(t.get("description") or "").lower()]
    if not rows:
        return ("REA 里没有匹配「%s」的工具（它一共有 %d 个）。换个词试试，"
                "比如 pe、apk、decompile、strings、frida、gguf。" % (kw, len(tools or []))) if kw \
            else "REA 没有工具（按说不会，先 rea_status 看看）"
    head = ("REA 工具（共 %d 个%s）前 %d 个 —— 调法：rea_call，tool 填名字，args 传 JSON\n"
            % (len(tools or []), ("，匹配「%s」的" % kw) if kw else "", min(limit, len(rows))))
    out = []
    for t in rows[:limit]:
        desc = str(t.get("description") or "").replace("\n", " ")
        req = ((t.get("inputSchema") or {}).get("required") or [])
        reqs = (" ｜ 必填：" + "、".join(str(x) for x in req[:5])) if req else ""
        out.append("· %s —— %s%s" % (t.get("name"), desc[:80], reqs))
    return head + "\n".join(out)


def _do_call(cfg, params):
    name = str((params or {}).get("tool") or "").strip()
    if not name:
        return "要调哪个工具？用 rea_tools 先搜一个名字，再放进 tool 里。"
    args = (params or {}).get("args")
    if args is None:
        args = {}
    if isinstance(args, str):
        try:
            args = json.loads(args) if args.strip() else {}
        except Exception as e:
            return "args 不是合法 JSON：%s（要么传对象，要么传能解析的 JSON 字符串）" % str(e)[:80]
    if not isinstance(args, dict):
        return "args 必须是 JSON 对象（键值对），收到的是 %s" % type(args).__name__
    c, err = _client_obj(cfg)
    if err:
        return "REA 起不来：%s" % err
    text, err = c.call_tool(name, args, timeout=cfg["timeout_s"])
    if err:
        # 工具名写错时把候选列出来 —— 比只回一句"失败"有用
        if "unknown" in err.lower() or "not found" in err.lower():
            tools, _ = _tool_list(cfg)
            near = [t.get("name") for t in (tools or []) if name.lower()[:4] in str(t.get("name") or "").lower()]
            return ("REA 里没有叫「%s」的工具。相近的有：%s\n（用 rea_tools 搜完整清单）"
                    % (name, "、".join(near[:8]) or "没有相近的"))
        return "REA 调用「%s」失败：%s" % (name, err)
    if not text:
        return "REA 调「%s」成功，但没有返回任何内容（这多半说明参数不全，先 rea_tools 看它要什么）" % name
    return _clip(_friendly_error(text), cfg["max_chars"])


# ---------------------------------------------------------------- 载体替模型选工具
# 【为什么要有这一层】REA 有 229 个工具。4B 小模型看 229 个英文工具名，只会做两件事：
#   挑一个名字里有它认识的词的，或者干脆不调。所以**选工具和拼参数这两件事由载体做**，
#   模型只负责说"我想干什么"（中文一句话）。这正是这个项目的核心取舍：
#   能力放载体里，模型只做它擅长的那一小步。
# 【它不是"缩减能力"】三个入口（rea_do / rea_call / rea_help）覆盖全部 229 个工具：
#   rea_do 用意图路由，rea_call 用工具名直调，rea_help 看参数 —— 一个都没被藏起来。
_SESSION = {"opened": "", "at": 0.0}      # 上一次 open_binary 打开的目标（REA 那边是会话级的）
_INDEX = {"key": None, "docs": None}


def _tokens(s):
    """把工具名/说明切成小写词元（同时认 snake_case 与 camelCase）。"""
    import re as _re
    t = str(s or "")
    t = _re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", t)
    return set(x for x in _re.split(r"[^A-Za-z0-9_]+", t.lower()) if x)


def _intent_words():
    try:
        from plugins.rea_tools_zh import INTENT_WORDS, EXT_HINTS, EXT_FAMILY, FAMILY_WORDS
        return INTENT_WORDS, EXT_HINTS, EXT_FAMILY, FAMILY_WORDS
    except Exception:
        try:
            import importlib.util as _iu
            p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rea_tools_zh.py")
            spec = _iu.spec_from_file_location("_xj_rea_words", p)
            m = _iu.module_from_spec(spec)
            spec.loader.exec_module(m)
            return (m.INTENT_WORDS, m.EXT_HINTS,
                    getattr(m, "EXT_FAMILY", {}), getattr(m, "FAMILY_WORDS", {}))
        except Exception as e:      # noqa: silent-ok — 词表缺失就退化成纯英文匹配
            LOG.debug("REA 中文词表加载失败（退化）：%s", e)
            return {}, {}, {}, {}


def _build_index(tools):
    """给检索用的轻量索引：每个工具的词元集合 + 参数名集合。"""
    key = (len(tools), str(tools[0].get("name") if tools else ""))
    if _INDEX["docs"] is not None and _INDEX["key"] == key:
        return _INDEX["docs"]
    docs = []
    for t in tools or []:
        sch = t.get("inputSchema") or {}
        props = list((sch.get("properties") or {}).keys())
        docs.append({
            "name": str(t.get("name") or ""),
            "desc": str(t.get("description") or ""),
            "props": props,
            "required": list(sch.get("required") or []),
            "ntok": _tokens(t.get("name")),
            "dtok": _tokens(t.get("description")),
            "ptok": set(p.lower() for p in props),
        })
    _INDEX["key"], _INDEX["docs"] = key, docs
    return docs


def _route(intent, tools, target="", focus=""):
    """把一个中文/英文意图路由到具体工具。返回 (候选列表, 说明)。

    打分（确定性，不调模型）：
      · 意图里出现**工具名本身**（或它的词元）→ 最高分；
      · 意图里的中文词命中词表 → 词表给的英文线索词出现在工具名里（+6）或说明里（+2）；
      · 目标扩展名命中的平台线索（apk/ipa/js…）再加一点，避免"看个 apk"却选了 PE 的工具；
      · 需要参数而我们凑不齐的工具**降权**（能直接跑起来的优先）。
    """
    words, ext_hints, ext_family, family_words = _intent_words()
    docs = _build_index(tools)
    it = str(intent or "").strip()
    low = it.lower()
    itok = _tokens(it)
    # 中文意图 → 英文线索词
    cues = []
    for zh, ens in (words or {}).items():
        if zh and zh in it:
            cues.extend([str(x).lower() for x in ens])
    cues = list(dict.fromkeys(cues))
    # 目标扩展名 → 平台线索 + 家族
    ext_cues = []
    tl = str(target or "").lower()
    my_family = ""
    for ext, ens in (ext_hints or {}).items():
        if tl.endswith(ext):
            ext_cues.extend([str(x).lower() for x in ens])
    for ext, fam in (ext_family or {}).items():
        if tl.endswith(ext):
            my_family = fam
            break

    def _family_penalty(name_low):
        """家族对不上就扣分（.exe 的活不该派给 apk 工具）；**中立工具不奖不罚**。

        【为什么单写成一个"先判自家、再判别家"的函数】第一版是把两件事写在同一个循环里，
        结果 `continue` 把"自家加分"那一段整个跳过了 —— 于是 pe 的工具永远拿不到家族加分，
        给 .exe 找签名被派到了 `inspect_apk_signature`。这种"奖励分支永远执行不到"的错
        不会报错，只会让路由慢慢变差，只能靠枚举用例才看得出来。
        """
        if not my_family or not family_words:
            return 0.0
        mine = family_words.get(my_family) or ()
        if any(k in name_low for k in mine):
            return 4.0
        for fam, kws in family_words.items():
            if fam == my_family:
                continue
            if any(k in name_low for k in kws):
                return -7.0
        return 0.0

    scored = []
    for d in docs:
        s = 0.0
        name_low = d["name"].lower()
        if low and (low == name_low or low.replace(" ", "_") == name_low):
            s += 40
        if itok & d["ntok"]:
            s += 12 * len(itok & d["ntok"])
        for c in cues:
            if c == name_low:
                s += 14            # 意图里点到工具本名：几乎肯定就是它
            elif c in name_low:
                s += 9
            elif c in d["name"].replace("_", " ").lower() or c in d["ntok"]:
                s += 5
            if c and c in d["desc"].lower():
                s += 2
        for c in ext_cues:
            if c in name_low or c in d["ntok"]:
                s += 3
        s += _family_penalty(name_low)
        if focus:
            # 有 focus 时优先"吃 symbol/address/pattern 这类参数"的工具
            if d["ptok"] & {"symbol", "name", "address", "pattern", "procedure", "query"}:
                s += 4
        # 参数凑得齐的加分（载体知道手里有什么）
        if d["required"]:
            have = set()
            if target:
                have |= {"path", "file", "target", "artifact"}
            if focus:
                have |= {"symbol", "name", "address", "pattern", "procedure", "query"}
            missing = [r for r in d["required"] if str(r).lower() not in have]
            if missing:
                s -= 3 * len(missing)
        if name_low.startswith("inspect_") or name_low.startswith("open_"):
            s += 1.5            # 同分时优先"先看清楚"这类动作，比直接深挖安全
        if s > 0:
            scored.append((s, d))
    scored.sort(key=lambda x: (-x[0], len(x[1]["name"])))
    return [d for _, d in scored[:5]], scored[0][0] if scored else 0.0


def _fill_args(doc, target="", focus="", extra=None):
    """载体替模型拼参数：能填的填上，填不了的**列出来问**（绝不瞎编）。"""
    args = dict(extra or {})
    have_target = bool(target) or (bool(_SESSION["opened"]) and not target)
    if target and any(p.lower() in ("path", "file", "target", "artifact") for p in doc["props"]):
        for p in doc["props"]:
            if p.lower() in ("path", "file", "target", "artifact"):
                args.setdefault(p, target)
    if focus:
        for p in doc["props"]:
            if p.lower() in ("symbol", "name", "address", "pattern", "procedure", "query"):
                args.setdefault(p, focus)
    missing = []
    for r in doc["required"]:
        if str(r).lower() in [k.lower() for k in args]:
            continue
        if str(r).lower() in ("path", "file", "target", "artifact") and have_target:
            # REA 里"已经打开过目标"时，path 可以不给
            continue
        missing.append(str(r))
    return args, missing


def _needs_target(doc):
    low = " ".join(doc["props"]).lower() + " " + doc["name"].lower()
    return any(k in low for k in ("path", "file", "target", "artifact")) or \
        doc["name"].startswith(("binary_overview", "inspect_artifact", "list_", "search_",
                                "procedure", "read_", "xrefs", "trace_", "get_"))


def _do_help(cfg, params):
    name = str((params or {}).get("tool") or "").strip()
    tools, err = _tool_list(cfg)
    if err:
        return "REA 工具列表取不到：%s" % err
    if not name:
        return "要查哪个工具？先用 rea_tools 搜一个名字。"
    t = next((x for x in (tools or []) if str(x.get("name")) == name), None)
    if t is None:
        return "REA 里没有叫「%s」的工具。用 rea_tools 搜一下。" % name
    sch = t.get("inputSchema") or {}
    props = sch.get("properties") or {}
    req = list(sch.get("required") or [])
    lines = ["%s —— %s" % (name, str(t.get("description") or "")[:300])]
    if req:
        lines.append("必填：%s" % "、".join(req))
    else:
        lines.append("必填：无（不传参数也能调）")
    if props:
        lines.append("可用参数：")
        for p, spec in list(props.items())[:14]:
            d = str((spec or {}).get("description") or "").replace("\n", " ")[:70]
            ty = str((spec or {}).get("type") or "")
            lines.append("  · %s（%s）%s" % (p, ty or "?", ("：" + d) if d else ""))
    lines.append("调法：rea_call，tool=%s，args 传上面的参数；或直接 rea_do 说你想干什么。" % name)
    return "\n".join(lines)


def _do_intent(cfg, params):
    """意图式入口：说人话 → 载体选工具 → 载体拼参数 → 调 → 报错翻人话。"""
    params = params or {}
    intent = str(params.get("intent") or "").strip()
    target = str(params.get("target") or "").strip().strip('"')
    focus = str(params.get("focus") or "").strip()
    if not intent:
        return "想干什么？比如「反编译 main」「看这个文件的哈希」「列出字符串」。"
    tools, err = _tool_list(cfg)
    if err:
        return "REA 工具列表取不到：%s" % err
    cands, top = _route(intent, tools, target=target, focus=focus)
    if not cands or top < 2:
        return ("没找到合适的 REA 工具来干「%s」。可以 rea_tools 用关键词搜一下"
                "（如 pe、apk、decompile、strings、frida、gguf），再 rea_call 精确调。"
                % intent[:40])
    doc = cands[0]
    # 需要目标但我们手上没有 → 问清楚（比瞎跑一个工具强）
    if _needs_target(doc) and not target and not _SESSION["opened"]:
        return ("这个动作需要一个目标文件（%s）。把文件路径给我，我再跑。\n"
                "可选工具：%s" % (doc["name"], "、".join(d["name"] for d in cands[:3])))
    args, missing = _fill_args(doc, target=target, focus=focus)
    if missing:
        return ("要调 %s，但还缺参数：%s。补充一下（或用 rea_help 看它要什么）。\n"
                "（这句话是载体替你判断的：工具已经选好了，只差参数）"
                % (doc["name"], "、".join(missing)))
    # ---- 执行：目标还没打开就先 open_binary（REA 的多数分析工具都作用于"已打开的目标"）----
    steps = []
    real_target = target or _SESSION["opened"]
    if real_target and not target and _needs_target(doc):
        for p in doc["props"]:
            if p.lower() in ("path", "file", "target", "artifact"):
                args.setdefault(p, real_target)
    if real_target and (_needs_target(doc) or doc["name"] == "open_binary"):
        opened = str(_SESSION["opened"] or "")
        if os.path.normcase(opened) != os.path.normcase(real_target) and doc["name"] != "open_binary":
            o_text, o_err = _call_tool_safe(cfg, "open_binary", {"path": real_target})
            if o_err:
                return "打开目标失败（%s）：%s" % (doc["name"], o_err)
            if o_text and '"error"' in o_text[:40]:
                return "打开目标失败：%s" % _friendly_error(o_text)[:300]
            _SESSION["opened"], _SESSION["at"] = real_target, time.time()
            steps.append("open_binary(%s)" % os.path.basename(real_target))
    text, err2 = _call_tool_safe(cfg, doc["name"], args)
    steps.append("%s(%s)" % (doc["name"], json.dumps(args, ensure_ascii=False)[:120]))
    if err2:
        # 一次自动纠正：报"没打开/找不到"时，自动 open_binary 再重试一次
        low = err2.lower()
        if real_target and any(k in low for k in ("not found", "no document", "open", "provider")):
            o_text, o_err = _call_tool_safe(cfg, "open_binary", {"path": real_target})
            if not o_err:
                _SESSION["opened"] = real_target
                steps.append("open_binary(重试)")
                text, err2 = _call_tool_safe(cfg, doc["name"], args)
        if err2:
            return "按「%s」选的工具是 %s，但调用失败：%s\n（试过：%s）" % (
                intent[:24], doc["name"], err2, "；".join(steps))
    head = "按「%s」→ %s（载体替你选的工具）\n试过：%s\n" % (
        intent[:24], doc["name"], "；".join(steps))
    if not text:
        return head + "调用成功但没返回内容（多半参数不全，rea_help %s 看它要什么）" % doc["name"]
    other = [d["name"] for d in cands[1:4]]
    tail = ("\n（备选工具：%s —— 结果不对就换它们，或 rea_call 精确调）" % "、".join(other)) if other else ""
    return head + _clip(_friendly_error(text), cfg["max_chars"]) + tail


def _call_tool_safe(cfg, name, args, timeout=None):
    """调一个工具，返回 (text, err)。错误统一走中文说明。"""
    c, err = _client_obj(cfg)
    if err:
        return "", "REA 起不来：%s" % err
    text, err = c.call_tool(name, args or {}, timeout=int(timeout or cfg["timeout_s"]))
    if err:
        return "", err
    return text or "", ""


class ReaPlugin:
    """插件契约：get_tool_descriptions() 声明工具，execute() 执行。

    五个入口覆盖全部 229 个工具（**没有缩减任何能力**）：
      · rea_do    —— 说人话，载体替它选工具、拼参数（4B 主要用这个）
      · rea_call  —— 知道工具名时精确调用（可调 229 个里的任何一个）
      · rea_help  —— 看某个工具要哪些参数
      · rea_tools —— 按关键词搜工具目录
      · rea_status—— 服务活没活、多少个工具
    """

    def get_tool_descriptions(self):
        cfg = _load_cfg()
        if not cfg.get("on", True):
            LOG.info("REA 插件：配置里关掉了（rea.on=false），一个工具都不注册")
            return []
        ok, why = _launcher_ok(cfg)
        if not ok:
            LOG.info("REA 插件：%s —— 一个工具都不注册（不糊假工具给模型）", why)
            return []
        return list(_TOOLS)

    def execute(self, tool_name, params):
        params = params or {}
        try:
            cfg = _load_cfg()
            if tool_name == "rea_status":
                return _do_status(cfg)
            if tool_name == "rea_tools":
                return _do_tools(cfg, params)
            if tool_name == "rea_call":
                return _do_call(cfg, params)
            if tool_name == "rea_do":
                return _do_intent(cfg, params)
            if tool_name == "rea_help":
                return _do_help(cfg, params)
            return ("未知工具：%s（REA 有 rea_status、rea_tools、rea_call、rea_do、rea_help）"
                    % tool_name)
        except Exception as e:      # noqa: silent-ok — 插件内部异常必须转成中文说明
            LOG.warning("REA 插件内部异常（已转成说明）：%s: %s", type(e).__name__, e)
            return "REA 插件内部出错了（%s: %s）。先用 rea_status 看服务活着没；" \
                   "如果是启动阶段的问题，检查配置里的 rea.cmd 和 rea.cwd。" \
                   % (type(e).__name__, str(e)[:100])


_PLUGIN = ReaPlugin()


def get_plugin():
    return _PLUGIN


@atexit.register
def _bye():
    try:
        c = _client.get("obj")
        if c is not None:
            c.stop()
    except Exception:      # noqa: silent-ok — 退出阶段不折腾
        pass
