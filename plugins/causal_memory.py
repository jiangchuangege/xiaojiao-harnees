# plugins/causal_memory.py —— 把 causal-memory 的**因果教训层**接进小焦（2026-10-15）
#
# 【为什么接它，而不是重做一遍】
#   小焦自己已经有：事实/画像记忆（memory_vec）、经验记录（self_learn 的 414 条"工具成败/反思"）、
#   来源分层、写入侧去重、隔离区、时间衰减、精排。这些**不动**。
#   缺的是 causal-memory 独有的那几样：**类型化的因果边（caused/enabled/prevented）、
#   动手前的抑制侧预警、反事实对比、多跳故障溯源、预测账本**。所以这里只接缺的那部分。
#
# 【它是什么】Rust 写的单二进制（Apache-2.0），跑起来就是一个 MCP stdio server，17 个工具。
#   本机用的预编译包：https://github.com/JingxuanC/causal-memory/releases（windows-x86_64）
#
# 【怎么配】控制文件 xiaojiao_control.json 里加一块（或走环境变量）：
#   "causal_memory": {
#       "exe": "C:/xiaojiao/causal-memory/causal-memory.exe",
#       "db":  "C:/xiaojiao/causal-memory/xiaojiao.db",
#       "task_tag": "小焦运维",
#       "cmd": ["python", "tools/fake.py"]      # 仅自测用：给了 cmd 就不看 exe
#   }
#   环境变量兜底：CAUSAL_MEMORY_EXE / CAUSAL_MEMORY_DB / CAUSAL_MEMORY_TASK_TAG
#   找不到二进制时：**这个插件的工具一个都不注册**（不糊一个假工具给模型），只在日志里说明。
#
# 【铁的边界】causal-memory 只当"教训查询/登记"用，**不接管小焦的记忆**（避免两套库互相打架）；
#   所有调用失败一律返回中文说明，绝不抛异常（小焦那层的 run_plugin 会把异常吞成空串，
#   真出问题用户什么都看不到，所以这里必须自己说清楚）。
import atexit
import json
import logging
import os
import queue
import subprocess
import threading
import time

LOG = logging.getLogger(__name__)

DEFAULT_EXE = r"C:\xiaojiao\causal-memory\causal-memory.exe"
_ENV_EXE = "CAUSAL_MEMORY_EXE"
_ENV_DB = "CAUSAL_MEMORY_DB"
_ENV_TAG = "CAUSAL_MEMORY_TASK_TAG"

# 七种边里最常用的几个（服务端 relation 是普通字符串，写错会被它自己拒绝）
RELATIONS = ("caused", "enabled", "prevented", "co_occurrence")


def _load_cfg():
    """读配置：控制文件 > 环境变量 > 默认值。永远返回一个 dict，不抛。"""
    cfg = {}
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        p = os.path.join(root, "xiaojiao_control.json")
        if os.path.exists(p):
            d = json.load(open(p, encoding="utf-8"))
            c = d.get("causal_memory")
            if isinstance(c, dict):
                cfg.update(c)
    except Exception as e:      # noqa: silent-ok — 读不到就当没配
        LOG.debug("读 causal_memory 配置失败（忽略）：%s", e)
    if os.environ.get(_ENV_EXE):
        cfg["exe"] = os.environ[_ENV_EXE]
    if os.environ.get(_ENV_DB):
        cfg["db"] = os.environ[_ENV_DB]
    if os.environ.get(_ENV_TAG):
        cfg["task_tag"] = os.environ[_ENV_TAG]
    cfg.setdefault("exe", DEFAULT_EXE)
    cfg.setdefault("task_tag", "小焦运维")
    cfg["exe"] = os.path.normpath(str(cfg.get("exe") or ""))
    if cfg.get("db"):
        cfg["db"] = os.path.normpath(str(cfg["db"]))
    return cfg


class _McpStdio:
    """一个极简的 MCP stdio 客户端（JSON-RPC 按行）。

    【为什么不用 mcp 那个官方库】小焦的 scrapling 桥接里已经有一套（stdio/json-rpc），
    但那边是给 scrapling 专用的（配置、工具白名单、参数换算全绑死了）。这里只要
    「起进程 → initialize → tools/call」这点东西，自己写 60 行比拉一个依赖干净，
    而且**坏了自己能修**（这个项目的规矩：外部依赖越少越好）。
    """

    def __init__(self, cmd, env_extra=None, log=LOG):
        self.cmd = list(cmd)
        self.env = dict(os.environ)
        self.env.setdefault("PYTHONUTF8", "1")
        if env_extra:
            self.env.update({k: str(v) for k, v in env_extra.items() if v})
        self.log = log
        self.proc = None
        self._lock = threading.Lock()
        self._next_id = 0
        self._pending = {}
        self._threads = []
        self.last_error = ""

    # ---------- 起进程 ----------
    def start(self):
        if self.proc and self.proc.poll() is None:
            return True
        if self.proc is not None:            # 之前挂过：清掉再起
            self.stop()
        try:
            self.proc = subprocess.Popen(
                self.cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8",
                errors="replace", bufsize=1, env=self.env,
                cwd=os.path.dirname(self.cmd[0]) or None)
        except Exception as e:
            self.last_error = "起不来（%s: %s）" % (type(e).__name__, str(e)[:120])
            self.proc = None
            return False
        for fn in (self._read_stdout, self._read_stderr):
            t = threading.Thread(target=fn, daemon=True)
            t.start()
            self._threads.append(t)
        if not self._initialize():
            self.stop()
            return False
        return True

    def _read_stdout(self):
        try:
            for line in self.proc.stdout:
                line = (line or "").strip()
                if not line or not line.startswith("{"):
                    continue
                try:
                    msg = json.loads(line)
                except Exception:      # noqa: silent-ok — 不是 JSON 就跳过
                    continue
                mid = msg.get("id")
                if mid is None:        # 服务端通知/日志，不是响应
                    continue
                q = self._pending.get(mid)
                if q is not None:
                    q.put(msg)
        except Exception as e:      # noqa: silent-ok — 管道关了就是进程没了
            self.log.debug("读 stdout 结束：%s", e)

    def _read_stderr(self):
        try:
            for line in self.proc.stderr:
                s = (line or "").strip()
                if s:
                    self.log.debug("[causal-memory] %s", s[:200])
        except Exception:      # noqa: silent-ok
            pass

    def _send(self, obj):
        self.proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    def _call(self, method, params=None, timeout=30):
        """发一个 JSON-RPC 请求并等响应。返回 (result, error_str)。"""
        with self._lock:
            if not self.start():
                return None, self.last_error or "没起来"
            self._next_id += 1
            mid = self._next_id
            q = queue.Queue()
            self._pending[mid] = q
            try:
                self._send({"jsonrpc": "2.0", "id": mid, "method": method,
                            "params": params or {}})
            except Exception as e:
                self._pending.pop(mid, None)
                return None, "写请求失败（%s）" % str(e)[:80]
            try:
                msg = q.get(timeout=timeout)
            except queue.Empty:
                self._pending.pop(mid, None)
                return None, "等超时（%d 秒没回）" % timeout
            finally:
                self._pending.pop(mid, None)
        if msg.get("error"):
            return None, str(msg["error"].get("message") or msg["error"])[:200]
        return msg.get("result") or {}, ""

    def _initialize(self):
        res, err = self._call("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                             "clientInfo": {"name": "xiaojiao", "version": "1.0"}}, 20)
        if err:
            self.last_error = "握手失败：%s" % err
            return False
        try:
            self._send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        except Exception as e:      # noqa: silent-ok — 这个通知发不出去也能用
            self.log.debug("发 initialized 通知失败（忽略）：%s", e)
        return True

    def tools(self, timeout=20):
        res, err = self._call("tools/list", {}, timeout)
        if err:
            return None, err
        return (res or {}).get("tools") or [], ""

    def call_tool(self, name, args, timeout=60):
        """调一个工具，返回 (文本, 错误串)。服务端自己报错（isError）也当文本返回。"""
        res, err = self._call("tools/call", {"name": name, "arguments": args or {}}, timeout)
        if err:
            return "", err
        parts = []
        for c in (res or {}).get("content") or []:
            if isinstance(c, dict) and c.get("type") == "text":
                parts.append(str(c.get("text") or ""))
        text = "\n".join(parts).strip()
        if (res or {}).get("isError") and not text:
            text = "服务端报错（没有说明）"
        return text, ""

    def stop(self):
        try:
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except Exception:      # noqa: silent-ok — 不退就强杀
                    self.proc.kill()
        except Exception as e:      # noqa: silent-ok — 关不掉也不许抛
            self.log.debug("停 causal-memory 失败（忽略）：%s", e)
        self.proc = None


class CausalMemoryPlugin:
    """小焦插件：只接小焦**没有的**因果教训能力。"""

    def __init__(self):
        self.cfg = _load_cfg()
        self._client = None
        self._lock = threading.Lock()
        self._disabled_reason = ""
        self._task_tag = str(self.cfg.get("task_tag") or "小焦运维")[:40]

    # ---------- 可用性 ----------
    def _cmd(self):
        """要跑的命令（自测可以给 cmd，正式用 exe）。"""
        cmd = self.cfg.get("cmd")
        if isinstance(cmd, (list, tuple)) and cmd:
            return [str(x) for x in cmd]
        exe = str(self.cfg.get("exe") or "")
        return [exe] if exe else []

    def _missing(self):
        cmd = self._cmd()
        if not cmd:
            return "没配 causal-memory 可执行文件（控制文件 causal_memory.exe 或环境变量 %s）" % _ENV_EXE
        if len(cmd) == 1 and not os.path.exists(cmd[0]):
            return ("找不到 causal-memory：%s —— 去 github.com/JingxuanC/causal-memory 的 Releases "
                    "下载 windows-x86_64 包解压，再把路径填进控制文件 causal_memory.exe" % cmd[0])
        return ""

    @property
    def available(self):
        return not self._missing()

    def _get(self):
        """拿到（必要时起）那个常驻 MCP 进程。返回 (client, err)。"""
        miss = self._missing()
        if miss:
            return None, miss
        with self._lock:
            if self._client is None:
                env_extra = {}
                if self.cfg.get("db"):
                    env_extra["CAUSAL_MEMORY_DB"] = self.cfg["db"]
                self._client = _McpStdio(self._cmd(), env_extra=env_extra)
            if self._client.proc is None or self._client.proc.poll() is not None:
                if not self._client.start():
                    return None, self._client.last_error or "起不来"
            return self._client, ""

    def _call(self, tool, args, timeout=60):
        cli, err = self._get()
        if err:
            return None, err
        text, err = cli.call_tool(tool, args, timeout=timeout)
        if err:                      # 可能是进程死了：重启再试一次
            with self._lock:
                if self._client is not None:
                    self._client.stop()
            cli, err2 = self._get()
            if err2:
                return None, err2
            text, err = cli.call_tool(tool, args, timeout=timeout)
            if err:
                return None, err
        return text, ""

    # ---------- 给模型看的工具清单 ----------
    def get_tool_descriptions(self):
        """没装/没配就返回空 —— 宁可不出现，也不给模型一个用不了的工具。"""
        if not self.available:
            LOG.info("因果记忆层未启用：%s", self._missing())
            return []
        tag = self._task_tag
        return [
            {"name": "causal_warn",
             "description": "动手前预警（因果记忆·抑制侧）：告诉我这个动作以前造成过什么后果，"
                            "尤其是**以前这么做出过事**。什么时候用：要执行有副作用的操作前"
                            "（改配置、删/覆盖文件、重启服务、装东西、动显卡/显存）。"
                            "输入 action（你打算做的动作，一句话）；输出 安全/警告/危险 + 因果链。",
             "parameters": {"action": "你打算执行的动作，一句话（例：跑视频任务时把聊天模型装回显存）",
                            "task_tag": "可选，领域标签（默认 %s）" % tag}},
            {"name": "causal_search",
             "description": "查以前的教训（因果记忆）：过去同类事情上，什么做法导致了什么结果。"
                            "什么时候用：遇到**非平凡的决策**之前（排障、换方案、改架构），"
                            "先看看以前踩过什么坑。输入 query；输出若干条「决策 →(关系)→ 结果」。",
             "parameters": {"query": "要查的事情，用自然语言（例：显存不够怎么腾）",
                            "task_tag": "可选，领域标签（默认 %s）" % tag,
                            "limit": "可选，返回几条，默认 5"}},
            {"name": "causal_record",
             "description": "记一条「决策 → 结果」到因果记忆。什么时候用：**做完一件事、拿到结果之后**"
                            "（尤其是踩坑、返工、意外成功）。relation 只能是 %s 之一。" % "/".join(RELATIONS),
             "parameters": {"decision": "当时的决策/做法，一句话",
                            "outcome": "实际结果（尽量带数字，例：显存 5.9G→0.9G，视频跑通）",
                            "relation": "关系类型：%s" % "/".join(RELATIONS),
                            "task_tag": "可选，领域标签（默认 %s）" % tag,
                            "context": "可选，当时的处境/约束（有它才能和别的决策比出差别）"}},
            {"name": "causal_trace",
             "description": "故障多跳溯源（因果记忆）：从一个坏结果往回追，找出一条因果链"
                            "（例：服务崩 ← OOM ← 缓存没设 TTL ← Redis 没配过期）。"
                            "什么时候用：单看一个原因解释不了故障时。输入坏结果描述。",
             "parameters": {"outcome_description": "坏结果的描述（例：视频生成 30 分钟超时）",
                            "max_depth": "可选，最多追几跳，默认 3"}},
            {"name": "causal_counterfactual",
             "description": "反事实对比（因果记忆）：两个候选方案，各自过去的结果分布是什么。"
                            "什么时候用：在两个方案之间拿不定主意时。",
             "parameters": {"decision": "方案 A（一句话）", "alternative": "方案 B（一句话）",
                            "task_tag": "可选，领域标签（默认 %s）" % tag}},
            {"name": "causal_report",
             "description": "因果记忆的预测账本：以前那些判断押对了多少（总览/按领域）+ 还没结算的。"
                            "什么时候用：想知道这套经验到底准不准的时候。",
             "parameters": {}},
        ]

    # ---------- 执行 ----------
    def execute(self, tool_name, params):
        params = params or {}
        if tool_name not in ("causal_warn", "causal_search", "causal_record",
                             "causal_trace", "causal_counterfactual", "causal_report"):
            return None
        tag = str(params.get("task_tag") or self._task_tag)[:40]
        try:
            if tool_name == "causal_warn":
                action = str(params.get("action") or "").strip()
                if not action:
                    return "因果记忆：没给 action（要说清你打算做什么）"
                text, err = self._call("intervention_query",
                                       {"action": action, "task_tag": tag, "limit": 5, "max_depth": 3}, 60)
                return self._wrap("动手前预警", text, err)
            if tool_name == "causal_search":
                args = {"task_tag": tag, "limit": int(params.get("limit") or 5), "query": str(params.get("query") or "")}
                text, err = self._call("search_causal", args, 60)
                return self._wrap("过往教训", text, err)
            if tool_name == "causal_record":
                decision = str(params.get("decision") or "").strip()
                outcome = str(params.get("outcome") or "").strip()
                relation = str(params.get("relation") or "caused").strip().lower()
                if relation not in RELATIONS:
                    relation = "caused"
                if not (decision and outcome):
                    return "因果记忆：decision 和 outcome 都得给（一句话各一句）"
                args = {"decision": decision, "outcome": outcome, "relation": relation, "task_tag": tag}
                if params.get("context"):
                    args["context"] = str(params["context"])[:400]
                text, err = self._call("record_decision", args, 60)
                return self._wrap("已记入因果记忆", text, err)
            if tool_name == "causal_trace":
                desc = str(params.get("outcome_description") or "").strip()
                if not desc:
                    return "因果记忆：没给 outcome_description（要说清那个坏结果）"
                text, err = self._call("trace_cause_chain",
                                       {"outcome_description": desc,
                                        "max_depth": int(params.get("max_depth") or 3)}, 60)
                return self._wrap("故障溯源", text, err)
            if tool_name == "causal_counterfactual":
                a = str(params.get("decision") or "").strip()
                b = str(params.get("alternative") or "").strip()
                if not (a and b):
                    return "因果记忆：decision 和 alternative 都要给（两个方案各一句）"
                text, err = self._call("counterfactual_query",
                                       {"decision": a, "alternative": b, "task_tag": tag}, 60)
                return self._wrap("方案对比", text, err)
            if tool_name == "causal_report":
                text, err = self._call("prediction_report", {}, 60)
                return self._wrap("预测账本", text, err)
        except Exception as e:      # noqa: silent-ok — 插件这层绝不许把异常抛给小焦
            LOG.warning("因果记忆插件出错（%s）：%s", tool_name, e)
            return "因果记忆调用出错（%s: %s）—— 这一条不影响本轮其它工具" % (type(e).__name__, str(e)[:120])
        return None

    def _wrap(self, title, text, err):
        """统一包装：**如实说清是谁给的**（这些结论来自 causal-memory，不是小焦自己想出来的）。"""
        if err:
            return "因果记忆（%s）没查成：%s" % (title, err)
        if not text:
            return "因果记忆（%s）：没有相关记录（这条是空的，不代表安全）" % title
        return "【因果记忆·%s】%s" % (title, text)


# 进程常驻：进程退出时收掉子进程（否则会留下孤儿 causal-memory.exe）
_INSTANCE = None
try:
    _INSTANCE = CausalMemoryPlugin()
    atexit.register(lambda: (_INSTANCE._client and _INSTANCE._client.stop()))
except Exception as _e:      # noqa: silent-ok — 插件构建失败不许拖垮主程序
    LOG.warning("因果记忆插件初始化失败（不影响其它功能）：%s", _e)
