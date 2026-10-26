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
            args[k] = {"selector": "h1", "pattern": "def ", "expression": "1+1",
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
    try:
        for t in tools:
            fn = t.get("function") or {}
            name = str(fn.get("name") or "")
            if not name or (only and name not in only):
                continue
            src = "插件" if app._TOOL2PLUGIN.get(name) else "内置"
            args, need = _safe_args(fn, tmp)
            # ① 有副作用 → 不真调
            if _is_side_effect(name):
                miss = [k for k in need if k not in args]
                rows.append({"name": name, "src": src, "verdict": "未实测",
                             "note": "有副作用，不真跑（参数就绪：%s）"
                                     % ("齐" if not miss else "缺 " + ",".join(miss))})
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
                    v, note = "需条件", "慢：%.0fs（可能在做重活，超 %.0fs 记这里）" % (sec, a.timeout)
            except Exception as e:
                v, note = "fail", "抛异常：%s: %s" % (type(e).__name__, str(e)[:60])
            rows.append({"name": name, "src": src, "verdict": v, "note": note})
            time.sleep(0.15)               # 别把自己机器打满
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    order = {"ok": 0, "broken": 1, "fail": 2, "需条件": 3, "未实测": 4, "跳过": 5}
    rows.sort(key=lambda r: (order.get(r["verdict"], 9), r["name"]))
    print("\n  %-30s %-5s %-8s %s" % ("工具", "来源", "结论", "说明"))
    print("  " + "-" * 98)
    for r in rows:
        print("  %-30s %-5s %-8s %s" % (r["name"][:30], r["src"], r["verdict"], r["note"][:60]))

    cnt = {}
    for r in rows:
        cnt[r["verdict"]] = cnt.get(r["verdict"], 0) + 1
    print("\n" + "=" * 104)
    print("  合计 %d 个 ｜ 可用 %d ｜ 坏了 %d ｜ 报错 %d ｜ 需条件 %d ｜ 未实测 %d ｜ 跳过 %d"
          % (len(rows), cnt.get("ok", 0), cnt.get("broken", 0), cnt.get("fail", 0),
             cnt.get("需条件", 0), cnt.get("未实测", 0), cnt.get("跳过", 0)))
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
                 "**合计 %d ｜ 可用 %d ｜ 坏了 %d ｜ 报错 %d ｜ 需条件 %d ｜ 未实测 %d ｜ 跳过 %d**"
                 % (len(rows), cnt.get("ok", 0), cnt.get("broken", 0), cnt.get("fail", 0),
                    cnt.get("需条件", 0), cnt.get("未实测", 0), cnt.get("跳过", 0)), "",
                 "| 工具 | 来源 | 结论 | 说明 |", "| --- | --- | --- | --- |"]
        for r in rows:
            lines.append("| `%s` | %s | %s | %s |" % (r["name"], r["src"], r["verdict"],
                                                     r["note"].replace("|", "/")[:80]))
        io.open(path, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
        print("  已写：%s" % path)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
