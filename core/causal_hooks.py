# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
# core/causal_hooks.py —— 关键动作前后问一句「因果记忆」（2026-10-15）
#
# 【为什么要有这一层】上一版把 causal-memory 接进来了，但它记的是「决策 → 结果」——
#   **不埋点就是空库**。靠人工想起来去记，等于白装。所以这里在三类最有价值的动作上自动埋点：
#     ① 改配置（写/改配置文件）      ② 删改文件（写文件、含删除/覆盖/移动的命令）
#     ③ 动显存资源（切换大脑、卸载/加载模型）
#
# 【三条硬规矩】都和这个项目的既有口径一致：
#   1. **只标注、不裁决**：预警只是把「以前这么干出过事」摆到模型面前，**不拦任何动作**
#      （拦不拦是删除红线/渠道隔离那几条闸的事，这里不越权）；
#   2. **绝不挡路**：动作**之前**那句查询最多等 2 秒（等不到就不说），
#      动作**之后**的记录丢到后台线程 —— 用户这一轮不该为"记一笔账"多等一毫秒；
#   3. **宁可不说，不许吓唬人**：只有对面明确给出 WARNING / DANGER 才提示；
#      空结果、UNKNOWN、超时一律静默（查不到 ≠ 安全，但也不该编一句警告出来）。
#
# 【为什么能拿到插件】小焦加载插件时用的模块名就是文件名（`plugins/causal_memory.py` →
#   `sys.modules["causal_memory"]`），模块里那个 `_INSTANCE` 就是常驻客户端。
#   插件没加载 / 二进制没配 / 用户把它关了 → 这一层整体安静地什么都不做。
import re
import sys
import threading
import time

LOG_PREFIX = "【因果记忆】"

# ---- 分类规则（只认这三类，别的动作一律不埋）----
_CONFIG_PATH_RE = re.compile(
    r"(xiaojiao_control\.json|llama-swap\.ya?ml|\.ya?ml$|\.env($|\.)|\.ini$|\.conf$|"
    r"config\.json$|settings\.json$|presets?[/\\].*\.json$|\.toml$)", re.I)
_WRITE_TOOLS = ("write_file", "edit_file", "append_file", "save_to")
_DESTRUCTIVE_RE = re.compile(
    r"(remove-item|\brm\b|\bdel\b|erase\b|move-item|\bmv\b|\brd\b|rmdir|"
    r"set-content|out-file|>\s*\S|truncate|format\b)", re.I)
_READONLY_TOOLS = ("read_file", "list_files", "search_files", "grep_files", "check_env",
                   "web_search", "fetch_url", "capture_screen", "screen_text", "ask_user")

# ---- 节流：同一个动作 10 分钟内只记一次；每小时最多 30 条（免得把库刷成噪声）----
_DEFAULTS = {"min_interval_s": 600.0, "max_per_hour": 30}
_seen = {}                 # 动作指纹 -> 上次记录时间
_hour = []                 # 最近一小时内记录的时间戳
_lock = threading.Lock()


def _cfg():
    """读 causal_memory 那一块配置（缺省全按默认值）。"""
    try:
        import json
        import os
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        d = json.load(open(os.path.join(root, "xiaojiao_control.json"), encoding="utf-8"))
        c = d.get("causal_memory") or {}
        return c if isinstance(c, dict) else {}
    except Exception:      # noqa: silent-ok — 读不到就全用默认
        return {}


def enabled():
    """这一层开不开。默认开；`"auto": false` 关掉；`"auto_kinds"` 可只留其中几类。"""
    c = _cfg()
    if c.get("auto") is False:
        return False
    kinds = c.get("auto_kinds")
    if isinstance(kinds, list) and kinds:
        globals()["_KINDS"] = tuple(str(k) for k in kinds)
    return True


def _kinds():
    c = _cfg()
    k = c.get("auto_kinds")
    if isinstance(k, list) and k:
        return tuple(str(x) for x in k)
    return ("config", "file", "vram")


def _plugin():
    """拿到因果记忆插件的实例（没加载就 None）。"""
    try:
        m = sys.modules.get("causal_memory")
        inst = getattr(m, "_INSTANCE", None) if m is not None else None
        if inst is None:
            return None
        return inst if getattr(inst, "available", False) else None
    except Exception:      # noqa: silent-ok — 拿不到就当没这层
        return None


def _short(s, n=120):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[:n] + "…"


# ---------------- 分类 ----------------
def classify(tool_name, args):
    """判断这次调用属不属于三类要埋点的动作。返回 None 或 {"kind","action"}。

    只认三类，别的一律返回 None —— 埋点要少而准，宁缺毋滥。
    """
    name = str(tool_name or "")
    args = args or {}
    kinds = _kinds()
    if name in _READONLY_TOOLS:
        return None
    if name in _WRITE_TOOLS:
        path = str(args.get("path") or args.get("file") or args.get("filename") or "")
        if not path:
            return None
        kind = "config" if _CONFIG_PATH_RE.search(path) else "file"
        if kind not in kinds:
            return None
        verb = "改配置" if kind == "config" else "写文件"
        return {"kind": kind, "action": "%s：%s" % (verb, _short(path, 100))}
    if name == "run_command":
        cmd = str(args.get("command") or "")
        if not cmd.strip():
            return None
        # ⚠️ 先判"碰没碰配置文件"，再判"是不是删除/覆盖类"：
        #    一条 `Set-Content xiaojiao_control.json` 两条都符合，而**改配置是更该记的那类**
        #    （历史教训基本都出在配置上），所以配置优先。第一版顺序反了，自测当场抓住。
        if _CONFIG_PATH_RE.search(cmd):
            if "config" not in kinds:
                return None
            return {"kind": "config", "action": "用命令改配置：%s" % _short(cmd, 100)}
        if _DESTRUCTIVE_RE.search(cmd):
            if "file" not in kinds:
                return None
            return {"kind": "file", "action": "执行含删除/覆盖/移动的命令：%s" % _short(cmd, 100)}
        return None
    return None


# ---------------- 动作之前：问一句（最多等 2 秒）----------------
def before(tool_name, args, wait_s=2.0):
    """要动手了，先问一句「以前这么干出过事吗」。

    返回要**附在工具结果后面**的一段文字（空串 = 没什么可说的）。
    只有对面明确说 WARNING / DANGER 才提示；UNKNOWN/空/超时一律安静 —— 不吓唬人。
    """
    try:
        if not enabled() or _plugin() is None:
            return ""
        c = classify(tool_name, args)
        if not c:
            return ""
        box = {}

        def _q():
            try:
                p = _plugin()
                if p is None:
                    return
                box["text"] = p.execute("causal_warn", {"action": c["action"]}) or ""
            except Exception as e:      # noqa: silent-ok — 查询失败就当没有
                box["err"] = str(e)[:120]

        t = threading.Thread(target=_q, daemon=True)
        t.start()
        t.join(wait_s)              # 最多等 2 秒：等不到就走，绝不拖慢动作
        txt = box.get("text") or ""
        if not txt:
            return ""
        up = txt.upper()
        if ("WARNING" in up) or ("DANGER" in up):
            return ("\n\n%s 动手前提醒（来自因果记忆，不是我自己的判断）：\n%s"
                    % (LOG_PREFIX, txt.strip()[:600]))
        # 【2026-10-15 实测补的一档：有记录、但引擎没给档位】
        #   真机上直接 `record_decision` 写进去的边，引擎的极性判定目前给的是 other/mixed，
        #   于是 intervention_query 回的是 UNKNOWN —— 也就是说"高危预警"这一档现在基本不会亮。
        #   全咽下去的话这个功能今天就是隐形的；但也不能把 UNKNOWN 说成危险（吓唬人）。
        #   所以折中成一句**如实标注的参考**：有相关记录就摆出来，并明说引擎没给档位。
        #   想安静点就把 auto_show_related 设成 false。
        if not bool(_cfg().get("auto_show_related", True)):
            return ""
        if ("CHAIN" in up) or ("FOUND " in up):
            first = ""
            for ln in txt.splitlines():
                s = ln.strip()
                if s and ("hop" in s or "→" in s or "→(" in s):
                    first = s
                    break
            return ("\n\n%s 有相关历史记录（引擎未给安全档位，仅供参考、不是结论）：%s%s"
                    % (LOG_PREFIX, _short(first or txt, 160), ""))
        return ""
    except Exception as e:      # noqa: silent-ok — 这一层永远不许影响工具本身
        try:
            import logging
            logging.getLogger(__name__).debug("因果记忆预警失败（忽略）：%s", e)
        except Exception:
            pass
        return ""


# ---------------- 动作之后：记一笔（后台线程，不挡路）----------------
def _rate_ok(key):
    now = time.time()
    c = _cfg()
    gap = float(c.get("auto_min_interval_s") or _DEFAULTS["min_interval_s"])
    cap = int(c.get("auto_max_per_hour") or _DEFAULTS["max_per_hour"])
    with _lock:
        last = _seen.get(key)
        if last and (now - last) < gap:
            return False
        while _hour and (now - _hour[0]) > 3600:
            _hour.pop(0)
        if len(_hour) >= cap:
            return False
        _seen[key] = now
        _hour.append(now)
        return True


def after(tool_name, args, result, ok=True):
    """动作做完了，把「决策 → 结果」记进因果记忆（后台，不挡路）。

    `result` 是工具返回的原文（会被截短）；`ok=False` 表示这次动作失败了。
    """
    try:
        if not enabled() or _plugin() is None:
            return
        c = classify(tool_name, args)
        if not c:
            return
        outcome = "%s%s" % ("失败：" if not ok else "", _short(result, 160) or "（没有输出）")
        key = (c["kind"], c["action"], "fail" if not ok else "ok")
        if not _rate_ok(key):
            return

        def _rec():
            try:
                p = _plugin()
                if p is None:
                    return
                p.execute("causal_record", {"decision": c["action"], "outcome": outcome,
                                            "relation": "caused",
                                            "context": "小焦自动埋点（%s 类动作）" % c["kind"]})
            except Exception as e:      # noqa: silent-ok — 记账失败只写日志
                try:
                    import logging
                    logging.getLogger(__name__).debug("因果记忆记账失败（忽略）：%s", e)
                except Exception:
                    pass

        threading.Thread(target=_rec, daemon=True).start()
    except Exception as e:      # noqa: silent-ok
        try:
            import logging
            logging.getLogger(__name__).debug("因果记忆埋点失败（忽略）：%s", e)
        except Exception:
            pass


# ---------------- 显存那一类：大脑切换 ----------------
def note_vram(target, info):
    """大脑切换（卸载/加载模型）之后记一笔。`info` 是 brain_manager.switch_to 的返回值。

    显存这一类的动作不由模型发起（是载体自己切的），所以不走 run_tool 那条路，
    在这里单独埋：**换模型 + 成功与否**，正好是"抢显存"这类事故的因果原料。
    """
    try:
        if not enabled() or "vram" not in _kinds() or _plugin() is None:
            return
        info = info if isinstance(info, dict) else {}
        ok = bool(info.get("ok", True))
        frm = info.get("from") or []
        decision = "把大脑切到「%s」（期间卸载/温存了 %s）" % (str(target), "、".join(map(str, frm)) or "无")
        outcome = ("切换成功：" if ok else "切换失败：") + _short(str(info), 160)
        key = ("vram", decision, "ok" if ok else "fail")
        if not _rate_ok(key):
            return

        def _rec():
            try:
                p = _plugin()
                if p is not None:
                    p.execute("causal_record", {"decision": decision, "outcome": outcome,
                                                "relation": "caused",
                                                "context": "显存资源切换（自动埋点）"})
            except Exception as e:      # noqa: silent-ok
                try:
                    import logging
                    logging.getLogger(__name__).debug("因果记忆显存埋点失败（忽略）：%s", e)
                except Exception:
                    pass

        threading.Thread(target=_rec, daemon=True).start()
    except Exception:      # noqa: silent-ok — 绝不因为记账影响切换本身
        pass


def stats():
    """给自测/诊断看：这一层现在什么状态。"""
    p = _plugin()
    return {"enabled": enabled(), "kinds": list(_kinds()), "plugin": bool(p),
            "seen": len(_seen), "last_hour": len(_hour)}
