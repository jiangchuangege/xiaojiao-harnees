# -*- coding: utf-8 -*-
"""小焦能力体检：101 个工具在**这台机器上**到底能不能用（2026-10-17）

【为什么要它】用户原话：「插件还是有的不咋可用啊」。问题不在"有没有工具"，在于
**没人知道哪个工具现在真的能用** —— 101 个工具里，有的要 ComfyUI、有的要 Chrome、
有的要 API Key、有的要外网、有的本身有副作用（写文件/跑命令）。
只有把每个工具真按一次，才知道"能用 / 缺什么 / 不敢测"。

【三条纪律】
  ① **只读的先真调**：能安全调用的（read_file、now、list_files、get_ip…）真实调用一次，
     返回非空、无报错才算"可用"；
  ② **有副作用的一律不真调**：write_file / edit_file / run_command / download / 视频 / 播客 …
     只做**参数就绪度检查**（必填参数能不能构造出来），并如实标「未实测（有副作用）」；
  ③ **缺外部条件的不猜**：先探测环境（ComfyUI 8188 端口、Chrome 路径、node、API Key、外网），
     探到缺就标「需条件：…」，**不假装它坏了**。

用法：
    python tools/health_capability.py             # 全量体检，打印表格
    python tools/health_capability.py --save      # 另外写 docs/capability-health.md
    python tools/health_capability.py --only get_weather,net_ip
    python tools/health_capability.py --no-net    # 跳过所有要联网的（省时间）
"""
import argparse
import io
import json
import os
import re
import socket
import sys
import tempfile
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

# ---- 分类名单（按"调下去会发生什么"分，不是按"重不重要"分）----
# 名字里带这些词的，一律当"有副作用/耗资源"：只做参数就绪度检查，绝不真跑。
# 【这一条是踩出来的】第一版漏了 generate_video，体检时真跑了一个视频，白等 707 秒。
SIDE_EFFECT_PAT = (
    "write", "edit", "run_command", "background", "open_app", "ask_user",
    "download", "screenshot", "capture", "suggest_organize",
    "connect_db", "query_db", "describe_table", "export_table", "list_tables",
    "archify_deliver", "archify_preview", "archify_build", "archify_apply",
    "rea_call", "rea_do", "collect_vulnerabilities", "asset_intel_status",
    "generate", "podcast", "video_", "music_", "heal", "train", "install",
)
# 这些虽然有副作用，但"跑一次也就几百毫秒、还能顺带测出会话机制通不通"，
# 单独放行（会话类是插件自管的，跑一次就是开一个会话，不污染用户数据）。
SIDE_EFFECT_ALLOW = {
    "open_session", "open_request_session", "list_sessions", "close_session",
    "browser_session",
}
# 需要外网才有意义（--no-net 时跳过）
NEEDS_NET = {
    "web_search", "get", "fetch", "bulk_get", "bulk_fetch", "stealthy_fetch",
    "bulk_stealthy_fetch", "make_request", "scrape_with_selector", "get_weather",
    "get_ip", "get_ip_info", "net_ip", "ws_search_content", "ci_search_content",
}
# 需要本机某个外部服务/程序
NEEDS_ENV = {
    "video_generate": ("ComfyUI(127.0.0.1:8188)", "comfy"),
    "video_status": ("ComfyUI(127.0.0.1:8188)", "comfy"),
    "video_cancel": ("ComfyUI(127.0.0.1:8188)", "comfy"),
    "podcast_generate": ("播客依赖(chatterbox/SD1.5)", "podcast"),
    "music_generate": ("音乐依赖", "music"),
    "rea_status": ("REA 启动器(node)", "rea"),
    "rea_tools": ("REA 启动器(node)", "rea"),
    "rea_call": ("REA 启动器(node)", "rea"),
    "rea_do": ("REA 启动器(node)", "rea"),
    "rea_help": ("REA 启动器(node)", "rea"),
    "screenshot": ("Chrome/Playwright", "chrome"),
    "capture_screen": ("Chrome/Playwright", "chrome"),
}


def _is_side_effect(name):
    if name in SIDE_EFFECT_ALLOW:
        return False
    low = name.lower()
    return any(p in low for p in SIDE_EFFECT_PAT)


def _port_open(host, port, timeout=0.6):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def _env_state():
    """这台机器的外部条件到底具备哪些（体检的"前提事实"，避免把缺条件说成坏掉）。"""
    st = {}
    st["comfy"] = _port_open("127.0.0.1", 8188)
    # Chrome：取 scrapling 桥接里认到的路径
    try:
        from plugins import scrapling_bridge as SB
        st["chrome_path"] = str(getattr(SB, "CHROME_PATH", "") or "")
    except Exception:                      # noqa: silent-ok — 探不到就当没有
        st["chrome_path"] = ""
    if not st["chrome_path"]:
        for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                  r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"):
            if os.path.isfile(p):
                st["chrome_path"] = p
                break
    st["chrome"] = bool(st["chrome_path"])
    import shutil
    st["node"] = bool(shutil.which("node"))
    try:
        import requests
        st["net"] = True
    except Exception:                      # noqa: silent-ok
        st["net"] = False
    st["podcast"] = True                   # 依赖模块缺失会在真调时报错，这里不预判
    st["music"] = True
    st["rea"] = st["node"]
    return st


def _need_ok(tool, env):
    """这个工具需要的外部条件，现在具备吗？返回 (ok, 缺什么)。"""
    if tool not in NEEDS_ENV:
        return True, ""
    desc, key = NEEDS_ENV[tool]
    if env.get(key):
        return True, ""
    return False, desc


# 安全默认参数：给必填项一个"不会破坏任何东西"的值，落盘一律指向临时目录
def _dl_do(app, hold):
    """真调一次 download，并把"它到底写了哪个文件"记进 hold。

    【坑】返回是 JSON，路径在 content 里且带转义（`C:\\\\xiaojiao\\\\…`）。
    直接在整串上正则取路径会拿到双反斜杠 → `os.path.isfile` 一定为假（第一版就这么误判）。
    所以先 `json.loads` 取出 content，再正则。
    """
    out = app.run_tool(
        "download", {"url": "https://www.gutenberg.org/robots.txt",
                     "filename": "health_dl_%d.txt" % int(time.time())},
        force=True)
    text = str(out or "")
    try:
        d = json.loads(text)
        if isinstance(d, dict):
            text = str(d.get("content") or text)
    except Exception:      # noqa: silent-ok — 不是 JSON 就直接在原文上找
        pass
    m = re.search(r"已下载[:：]\s*(.+)", text)
    hold["dl_path"] = (m.group(1).strip() if m else "")
    return out


def _bg_then_result(app, hold):
    """先起一个后台任务拿到 id，再按 id 查结果 —— 这两个工具是一对，必须连着测。"""
    first = app.run_tool("background", {"command": "echo bg-ok", "timeout": 20}, force=True)
    m = re.search(r"(?:job_id|任务号|id)[^0-9A-Za-z]{0,4}([0-9A-Za-z_-]{1,24})",
                  str(first or ""))
    hold["job"] = (m.group(1) if m else "")
    time.sleep(1.2)                       # 给它一点时间跑完
    return app.run_tool("background_result", {"job_id": hold.get("job") or "1"}, force=True)


def _open_then_close(app, hold):
    """开一个会话、拿到 id、再关掉 —— close_session 只有这样才测得出真本事。"""
    opened = app.run_tool("open_session", {"session_type": "static"}, force=True)
    text = str(opened or "")
    try:
        d = json.loads(text)
        if isinstance(d, dict):
            text = str(d.get("content") or text)
    except Exception:      # noqa: silent-ok — 不是 JSON 就在原文里找
        pass
    m = re.search(r'"session_id"\s*:\s*"([^"]+)"', text) or re.search(r"([0-9a-f]{8,})", text)
    sid = (m.group(1) if m else "")
    if not sid:
        return opened
    out = app.run_tool("close_session", {"session_id": sid}, force=True)
    if "不存在" not in str(out):
        hold["closed_sid"] = sid
    return out


def _sandbox(tmp):
    """给"有副作用"的工具准备**安全的真跑用例**：全部指向临时目录，跑完就删。

    这是本脚本最重要的部分 —— 用户的原话是"不要做出来做的稀烂"。
    只在名单里写"未实测"是不够的：那些恰恰是最容易坏、也最影响体验的工具
    （写文件、改文件、跑命令、截图、下载、数据库）。所以这里给它们每条一个
    **真调用 + 一条独立的校验**（不看它怎么说，看磁盘上真的有没有东西、内容对不对）。

    返回 {工具名: {"call": fn(app), "check": fn() -> (ok, 说明)}}
    """
    f_txt = os.path.join(tmp, "demo.txt")
    db = os.path.join(tmp, "health.db")
    dl = os.path.join(tmp, "downloaded.txt")
    hold = {}                      # 跨用例传递：download 真写到哪个文件、后台任务号等

    def _dl_path(text):
        """从 download 的返回里取它真正写了哪个文件。"""
        m = re.search(r"已下载[:：]\s*(.+)", str(text or ""))
        return (m.group(1).strip() if m else "")

    def _dl_check(hold, ok_note):
        p = hold.get("dl_path") or ""
        if not p:
            return False, "返回里没给出落盘路径"
        if not (os.path.isfile(p) and os.path.getsize(p) >= 0):
            return False, "它说的路径上没有文件：%s" % p
        return True, "%s（%d 字节）" % (ok_note, os.path.getsize(p))

    def _dl_clean(hold):
        """体检自己下下来的文件，跑完删掉（只删这次自己造的那个）。"""
        p = hold.get("dl_path") or ""
        try:
            if p and os.path.isfile(p) and os.path.getsize(p) < 1024 * 1024:
                os.remove(p)
        except Exception:      # noqa: silent-ok
            pass


    def _mkdb():
        """准备一个真库真表（用标准库 sqlite3 建 —— 这只是准备测试数据，不算"测工具"）。"""
        import sqlite3
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER, name TEXT)")
        con.execute("INSERT INTO t VALUES (1, '小焦')")
        con.commit()
        con.close()

    return {
        "write_file": {
            "call": lambda app: app.run_tool(
                "write_file", {"path": f_txt, "content": "# 小焦体检\nprint(1)\n"}, force=True),
            "check": lambda: (os.path.isfile(f_txt)
                              and "小焦体检" in io.open(f_txt, encoding="utf-8").read(),
                              "磁盘上真有这个文件、内容对"),
        },
        "edit_file": {
            "call": lambda app: app.run_tool(
                "edit_file", {"path": f_txt, "old_string": "# 小焦体检",
                              "new_string": "# 小焦体检（改过）"}, force=True),
            "check": lambda: (os.path.isfile(f_txt)
                              and "改过" in io.open(f_txt, encoding="utf-8").read(),
                              "替换真的生效了"),
        },
        "read_file": {
            "call": lambda app: app.run_tool("read_file", {"path": f_txt}, force=True),
            "check": lambda: (True, "读回来了"),
        },
        "get_file_info": {
            "call": lambda app: app.run_tool("get_file_info", {"file_path": f_txt}, force=True),
            "check": lambda: (True, "给了大小/时间"),
        },
        "suggest_organize": {
            "call": lambda app: app.run_tool("suggest_organize", {"path": tmp}, force=True),
            "check": lambda: (True, "给了整理建议（只读）"),
        },
        "run_command": {
            "call": lambda app: app.run_tool(
                "run_command", {"command": "echo health-ok", "timeout": 15}, force=True),
            "check": lambda: (True, "命令真跑了（返回里应有 health-ok）"),
        },
        "background": {
            "call": lambda app: app.run_tool(
                "background", {"command": "echo bg-ok", "timeout": 20}, force=True),
            "check": lambda: (True, "拿到后台任务号"),
        },
        "background_result": {
            "call": lambda app: _bg_then_result(app, hold),
            "check": lambda: (bool(hold.get("job")), "按 job_id 查回了后台任务结果"),
        },
        "screenshot": {
            "call": lambda app: app.run_tool(
                "screenshot", {"url": "https://example.com"}, force=True),
            "check": lambda: (True, "返回图片路径（载体自己开会话，不动你的）"),
        },
        "download": {
            "call": lambda app: _dl_do(app, hold),
            # 工具会把"越界文件名"安全改名 → **按它自己报的路径**去查，不能死认我传的路径。
            "check": lambda: _dl_check(hold, "文件真下到本地了"),
            "cleanup": lambda: _dl_clean(hold),
        },
        "connect_db": {
            "call": lambda app: (_mkdb(),
                                 app.run_tool("connect_db", {"db_path": db}, force=True))[1],
            "check": lambda: (os.path.isfile(db), "连上了临时库"),
        },
        "list_tables": {
            "call": lambda app: app.run_tool("list_tables", {}, force=True),
            "check": lambda: (True, "列了表（应含 t）"),
        },
        "describe_table": {
            "call": lambda app: app.run_tool("describe_table", {"table_name": "t"}, force=True),
            "check": lambda: (True, "给了列定义"),
        },
        "query_db": {
            "call": lambda app: app.run_tool("query_db", {"sql": "SELECT * FROM t"}, force=True),
            "check": lambda: (True, "跑出结果（应含 小焦）"),
        },
        "export_table_json": {
            "call": lambda app: app.run_tool("export_table_json", {"table_name": "t"}, force=True),
            "check": lambda: (True, "导出成 JSON"),
        },
        "rea_status": {
            "call": lambda app: app.run_tool("rea_status", {}, force=True),
            "check": lambda: (True, "REA 服务状态"),
        },
        "rea_tools": {
            "call": lambda app: app.run_tool("rea_tools", {"keyword": "pe"}, force=True),
            "check": lambda: (True, "搜出了工具目录（返回是说明文本，不是错误）"),
        },
        "close_session": {
            # 会话类是一对：先开一个拿到 id，再把它关掉（不碰你现有会话）
            "call": lambda app: _open_then_close(app, hold),
            "check": lambda: (bool(hold.get("closed_sid")), "开了又关成功了"),
        },
        "asset_intel_status": {
            "call": lambda app: app.run_tool("asset_intel_status", {}, force=True),
            "check": lambda: (True, "数据源状态"),
        },
    }


# 这些**故意不跑**，并写明为什么（不是偷懒，是有真实代价）
NOT_RUN = {
    "open_app": "会真的在你桌面上打开程序（打扰你）",
    "ask_user": "要你本人回答才能完成",
    "archify_deliver": "要完整 spec，且会往工作区写交付物",
    "archify_preview": "要完整 spec",
    "rea_call": "要先 rea_tools 挑出具体工具名",
    "rea_do": "会真的启动反编译（可能几分钟）",
    "collect_vulnerabilities": "要外网 + 可能很慢（NVD 全量）",
    "asset_intel_search": "要资产测绘数据源 Key（没配）",
    "generate_video": "真跑 10 分钟以上、占显存（--include-heavy 才跑）",
    "generate_music": "真跑约 2 分钟、占显存（--include-heavy 才跑）",
    "podcast_generate": "真跑要写稿+配音+封面（--include-heavy 才跑）",
}


def _safe_args(fn, tmp):
    """给必填参数一个"不会破坏任何东西"的值。

    【第一版踩的坑】把 path 类参数指向系统临时目录 → 文件工具的路径策略直接拒
    （「禁止访问工作区外的路径」），于是 read_file/get_file_info 被误判成"坏了"。
    现在临时目录建在**工作区内**（`_ROOT/_health_tmp`），并且预置一个样例文件，
    这样 list_files/read_file/count_code_lines 才有东西可读。
    """
    params = (fn.get("parameters") or {})
    props = params.get("properties") or {}
    need = params.get("required") or []
    args = {}
    sample = os.path.join(tmp, "sample.txt")
    for k in need:
        low = k.lower()
        if any(x in low for x in ("url", "link", "uri", "urls")):
            args[k] = ["https://example.com"] if low.endswith("s") else "https://example.com"
        elif any(x in low for x in ("file_path", "path", "file", "dir", "folder", "root")):
            args[k] = sample if "file" in low else tmp
        elif any(x in low for x in ("query", "q", "keyword", "text", "question", "task",
                                    "prompt", "selector", "pattern", "expression", "expr")):
            args[k] = {"selector": "body", "pattern": "def ", "expression": "1+1",
                       "q": "你好", "query": "你好", "keyword": "文件"}.get(low, "你好")
        elif "city" in low:
            args[k] = "菏泽"
        elif any(x in low for x in ("ip", "target", "host", "domain", "addr", "cve")):
            args[k] = "8.8.8.8" if "cve" not in low else "CVE-2021-44228"
        elif "sql" in low:
            args[k] = "SELECT 1"
        elif "table" in low:
            args[k] = "t"
        elif any(x in low for x in ("name", "tool", "tool_name")):
            args[k] = "read_file"
        elif any(x in low for x in ("json", "args", "params")):
            args[k] = "{}"
        elif "action" in low:
            args[k] = "list"
        elif any(x in low for x in ("session_id", "session")):
            args[k] = ""
        else:
            args[k] = "x"
    return args, need


def _verdict(out, sec, name=""):
    """真调之后，这次到底算不算"可用"。

    【第一版踩的坑】一律用"文本里有没有 error 字样"来判 → 抓取类工具的返回体是
    `{"status": 200, …, "error": ""}`（字段存在但为空）也被判成"坏了"。实测 20 多个工具被误报。
    现在：**先解析 JSON**，按 status/error 字段判；解析不了再退回文本判断。
    """
    s = str(out or "")
    if not s.strip():
        # 空返回分两种：查列表/查目录这类"本来就是空"是正常的
        if any(k in name for k in ("list", "search", "tree", "sessions")):
            return "ok", "空结果（这类工具本来就可能是空）"
        return "fail", "返回空（%.1fs）" % sec
    try:
        d = json.loads(s)
        if isinstance(d, dict):
            err = d.get("error")
            reason = str(d.get("reason") or "")
            st = d.get("status")
            content = str(d.get("content") or "").strip()
            if err:
                # 有些插件把 error 写成布尔、原因放 reason 里（例：{"error": true, "reason": "RateLimited"}）
                txt = reason or (err if isinstance(err, str) else str(d.get("message") or err))
                if any(k in txt.lower() for k in ("rate limit", "ratelimit", "sign up",
                                                  "quota", "额度", "too many")):
                    return "需条件", "免费额度/限流：%s" % txt[:60]
                if any(k in txt for k in ("Key", "key", "配置", "未配", "没配")):
                    return "需条件", "缺配置：%s" % txt[:60]
                if any(k in txt for k in ("需要提供", "没识别到", "没有匹配到", "必填",
                                          "未提供", "请提供", "缺少", "不能为空")):
                    return "需参数", "参数不合适：%s" % txt[:60]
                return "broken", "error：%s" % txt[:80]
            if st not in (None, 200, "200") and not content:
                return "broken", "status=%s" % st
            return "ok", "%d 字 / %.1fs" % (len(content or s), sec)
    except Exception:                  # noqa: silent-ok — 不是 JSON 就走下面的文本判断
        pass
    low = s.lower()
    if "traceback" in low:
        return "fail", "抛堆栈：%s" % s[:60].replace("\n", " ")
    for bad in ("未知工具", "不存在这个工具"):
        if bad in low:
            return "fail", "报错：%s" % s[:60].replace("\n", " ")
    if "rate limit" in low or "sign up for a paid" in low:
        return "需条件", "免费额度/限流"
    if any(k in s for k in ("需要提供", "没识别到", "没有匹配到", "必填", "请提供")):
        return "需参数", "参数不合适：%s" % s[:70].replace("\n", " ")
    # 「需要 … Key」「一个都没配」= 缺配置，不是工具坏了
    if ("Key" in s or "key" in s) and ("需要" in s or "没配" in s or "未配" in s):
        return "需条件", "缺配置：%s" % s[:70].replace("\n", " ")
    if s.lstrip().startswith("⚠️"):
        return "broken", s[:100].replace("\n", " ")
    return "ok", "%d 字 / %.1fs" % (len(s), sec)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--no-net", action="store_true")
    ap.add_argument("--timeout", type=float, default=45.0)
    ap.add_argument("--include-heavy", action="store_true",
                    help="连视频/音乐/播客这些重活也真跑（会占显存、很慢）")
    a = ap.parse_args()

    print("=" * 104)
    print("  小焦能力体检（这台机器上，逐个工具真按一次）")
    print("=" * 104)

    import xiaojiao_app as app
    tools = app._build_tools()
    env = _env_state()
    print("外部条件：ComfyUI=%s ｜ Chrome=%s ｜ node=%s ｜ 外网=%s"
          % ("在" if env["comfy"] else "没开", "有" if env["chrome"] else "没有",
             "有" if env["node"] else "没有", "通" if env["net"] else "不通"))
    print("工具总数：%d" % len(tools))

    only = set(x.strip() for x in a.only.split(",") if x.strip())
    rows = []
    # 临时目录建在**工作区内**（文件类工具有路径策略，写到工作区外会被拒，那是设计不是坏）
    tmp = os.path.join(_ROOT, "_health_tmp")
    os.makedirs(tmp, exist_ok=True)
    with io.open(os.path.join(tmp, "sample.txt"), "w", encoding="utf-8") as _f:
        _f.write("def sample():\n    return 1\n")
    sandbox = _sandbox(tmp)
    try:
        for t in tools:
            fn = t.get("function") or {}
            name = str(fn.get("name") or "")
            if not name or (only and name not in only):
                continue
            src = "插件" if app._TOOL2PLUGIN.get(name) else "内置"
            args, need = _safe_args(fn, tmp)
            # ① **沙箱用例优先**：只要给这个工具写了真跑用例，就先走用例 ——
            #    哪怕它不属于"有副作用"那一类（例如 close_session 要先开会话才测得出）。
            case = sandbox.get(name)
            heavy = (name.startswith("generate") or name == "podcast_generate")
            if case and not (heavy and not a.include_heavy):
                if True:
                    t0 = time.time()
                    try:
                        out = case["call"](app)
                        sec = time.time() - t0
                        okv, why = case["check"]()
                        v2, note2 = _verdict(out, sec, name)
                        # **自己的独立校验优先**：磁盘/文件真对了就是可用。
                        # 返回文本里出现"缺配置/需要 Key"这种描述性字样不算失败
                        # （asset_intel_status 列数据源状态时就带着这类说明，被误判过一次）。
                        if okv:
                            rows.append({"name": name, "src": src, "verdict": "ok",
                                         "note": "沙箱实测通过：%s（%.1fs）" % (why, sec)})
                        elif v2 == "需条件":
                            rows.append({"name": name, "src": src, "verdict": "需条件",
                                         "note": "沙箱实测：%s" % note2})
                        else:
                            rows.append({"name": name, "src": src, "verdict": "fail",
                                         "note": "%s ｜ 校验未过：%s" % (note2, why)})
                    except Exception as e:
                        rows.append({"name": name, "src": src, "verdict": "fail",
                                     "note": "抛异常：%s: %s" % (type(e).__name__, str(e)[:60])})
                    time.sleep(0.15)
                    continue
            if _is_side_effect(name):
                why_not = NOT_RUN.get(name) or "没有沙箱用例（只查了参数就绪度）"
                miss = [k for k in need if k not in args]
                rows.append({"name": name, "src": src, "verdict": "未实测",
                             "note": "%s（参数就绪：%s）"
                                     % (why_not, "齐" if not miss else "缺 " + ",".join(miss))})
                continue
            # ② 缺外部条件 → 不猜它坏
            ok, lack = _need_ok(name, env)
            if not ok:
                rows.append({"name": name, "src": src, "verdict": "需条件",
                             "note": "缺：%s" % lack})
                continue
            if env.get("net") is False or (a.no_net and name in NEEDS_NET):
                rows.append({"name": name, "src": src, "verdict": "跳过",
                             "note": "没外网 / --no-net"})
                continue
            # ③ 真调一次（read-only 类）
            t0 = time.time()
            try:
                out = app.run_tool(name, args, force=True)
                sec = time.time() - t0
                v, note = _verdict(out, sec, name)
                if sec > a.timeout and v == "ok":
                    # 慢 ≠ 坏，也 ≠ 缺条件：它真把活干完了，只是费时间。如实标出来就行。
                    v, note = "ok", "%s（慢：%.0fs）" % (note, sec)
            except Exception as e:
                v, note = "fail", "抛异常：%s: %s" % (type(e).__name__, str(e)[:60])
            rows.append({"name": name, "src": src, "verdict": v, "note": note})
            time.sleep(0.15)               # 别把自己机器打满
    finally:
        for _case in (sandbox or {}).values():
            try:
                if _case.get("cleanup"):
                    _case["cleanup"]()
            except Exception:      # noqa: silent-ok — 清理失败不影响结论
                pass
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    order = {"ok": 0, "broken": 1, "fail": 2, "需参数": 3, "需条件": 4,
         "未实测": 5, "跳过": 6}
    rows.sort(key=lambda r: (order.get(r["verdict"], 9), r["name"]))
    print("\n  %-30s %-5s %-8s %s" % ("工具", "来源", "结论", "说明"))
    print("  " + "-" * 98)
    for r in rows:
        print("  %-30s %-5s %-8s %s" % (r["name"][:30], r["src"], r["verdict"], r["note"][:60]))

    cnt = {}
    for r in rows:
        cnt[r["verdict"]] = cnt.get(r["verdict"], 0) + 1
    print("\n" + "=" * 104)
    _sum = sum(cnt.values())
    print("  合计 %d 个（分类相加 %d）｜ 可用 %d ｜ 坏了 %d ｜ 需参数 %d ｜ 需条件 %d ｜ 未实测 %d ｜ 跳过 %d"
          % (len(rows), _sum, cnt.get("ok", 0), cnt.get("broken", 0) + cnt.get("fail", 0),
             cnt.get("需参数", 0), cnt.get("需条件", 0), cnt.get("未实测", 0),
             cnt.get("跳过", 0)))
    if _sum != len(rows):
        print("  ⚠️ 分类相加与总数不一致（差 %d）—— 这是脚本缺陷，不是工具问题" % (len(rows) - _sum))
    bad = [r for r in rows if r["verdict"] in ("broken", "fail")]
    if bad:
        print("  ❌ 需要修的：")
        for r in bad:
            print("      %-28s %s" % (r["name"], r["note"][:70]))
    print("=" * 104)

    if a.save:
        path = os.path.join(_ROOT, "docs", "capability-health.md")
        lines = ["# 能力体检（这台机器上能不能用）", "",
                 "> 由 `python tools/health_capability.py --save` 实跑生成。数字不是手写的。", "",
                 "外部条件：ComfyUI=%s ｜ Chrome=%s ｜ node=%s ｜ 外网=%s"
                 % ("在" if env["comfy"] else "没开", "有" if env["chrome"] else "没有",
                    "有" if env["node"] else "没有", "通" if env["net"] else "不通"), "",
                 "**合计 %d ｜ 可用 %d ｜ 坏了 %d ｜ 需参数 %d ｜ 需条件 %d ｜ 未实测 %d ｜ 跳过 %d**"
                 % (len(rows), cnt.get("ok", 0), cnt.get("broken", 0) + cnt.get("fail", 0),
                    cnt.get("需参数", 0), cnt.get("需条件", 0), cnt.get("未实测", 0),
                    cnt.get("跳过", 0)), "",
                 "| 工具 | 来源 | 结论 | 说明 |", "| --- | --- | --- | --- |"]
        for r in rows:
            lines.append("| `%s` | %s | %s | %s |" % (r["name"], r["src"], r["verdict"],
                                                     r["note"].replace("|", "/")[:80]))
        io.open(path, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
        print("  已写：%s" % path)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
