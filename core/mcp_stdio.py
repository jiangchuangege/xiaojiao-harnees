# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · MCP stdio 客户端（起进程 → initialize → tools/list / tools/call）

【这个文件是什么】一个极简的 MCP（Model Context Protocol）stdio 客户端：按行发 JSON-RPC，
把对面那个进程暴露的工具当成本地函数调。小焦用它接外部工具服务（REA、causal-memory 这类）。

【为什么不引官方 mcp 库】这个项目的规矩是"外部依赖越少越好"：
需要的只有「起进程、握手、列工具、调工具」这四件事，六十行能说清、坏了能自己修；
拉一个库进来，出问题时反而只能等上游。

【和 `plugins/causal_memory.py` 里那个 `_McpStdio` 的关系（如实说）】
    那份是同思路的实现，但它的工作目录**写死成 cmd[0] 所在目录**，超时也不可变 ——
    接 REA 时需要"中立工作目录 + 更长的冷启动超时"，所以这里抽出一个参数化版本。
    **暂时两份并存**：causal-memory 那套已在跑、有 25 项自测钉着，这轮不去动它
    （动它就要连带重跑那套自测，属于另一件事）。等哪天真要改它，直接切到这里即可。

【边界】
    * 只支持 stdio 传输（HTTP 传输的 MCP 服务用别的方式接）；
    * 工具调用的结果只取 `content[].text`（小焦只要文本给模型看）；
    * 一切失败都返回中文说明，**不抛异常** —— 上层 `run_plugin` 会把异常吞成空串，
      那样用户什么都看不到，所以错误必须自己说出来。
"""
import json
import logging
import os
import queue
import subprocess
import threading
import time

LOG = logging.getLogger(__name__)


class McpStdio:
    """一个 MCP stdio 客户端。`cmd` 是启动命令，`cwd` 是它的工作目录（可为 None）。"""

    def __init__(self, cmd, cwd=None, env_extra=None, tag="mcp", init_timeout=30, log=None):
        self.cmd = [str(x) for x in (cmd or [])]
        self.cwd = cwd or None
        self.tag = tag or "mcp"
        self.init_timeout = float(init_timeout)
        self.log = log or LOG
        self.env = dict(os.environ)
        self.env.setdefault("PYTHONUTF8", "1")
        if env_extra:
            self.env.update({k: str(v) for k, v in env_extra.items() if v is not None})
        self.proc = None
        # 【必须是可重入锁】`call()` 会先拿锁、再 `start()`，而 `start()` 里的 initialize
        #   又要 `call()` —— 用普通 Lock 就是**自己锁死自己**（实测卡住、连日志都没有）。
        #   RLock 让同一条线程能再次进入，这个坑就没了。
        self._lock = threading.RLock()
        self._next_id = 0
        self._pending = {}
        self._threads = []
        self.last_error = ""

    # ---------------------------------------------------------------- 进程
    def start(self):
        if self.proc and self.proc.poll() is None:
            return True
        if self.proc is not None:          # 之前挂过：清掉再起
            self.stop()
        if not self.cmd:
            self.last_error = "没有配置启动命令"
            return False
        try:
            self.proc = subprocess.Popen(
                self.cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                bufsize=1, env=self.env, cwd=self.cwd,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception as e:
            self.last_error = "起不来（%s: %s）" % (type(e).__name__, str(e)[:150])
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
            self.log.debug("[%s] 读 stdout 结束：%s", self.tag, e)

    def _read_stderr(self):
        try:
            for line in self.proc.stderr:
                s = (line or "").strip()
                if s:
                    self.log.debug("[%s] %s", self.tag, s[:200])
        except Exception:      # noqa: silent-ok
            pass

    def _send(self, obj):
        self.proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    # ---------------------------------------------------------------- RPC
    def call(self, method, params=None, timeout=60):
        """发一个 JSON-RPC 请求并等响应。返回 (result, error_str)。"""
        with self._lock:
            if not self.start():
                return None, self.last_error or "MCP 服务没起来"
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
                return None, "等超时（%d 秒没回）" % int(timeout)
            finally:
                self._pending.pop(mid, None)
        if msg.get("error"):
            err = msg["error"]
            return None, str((err or {}).get("message") or err)[:300]
        return msg.get("result") or {}, ""

    def _initialize(self):
        res, err = self.call("initialize",
                             {"protocolVersion": "2024-11-05", "capabilities": {},
                              "clientInfo": {"name": "xiaojiao", "version": "1.0"}},
                             timeout=self.init_timeout)
        if err:
            self.last_error = "握手失败：%s" % err
            return False
        self.server_info = (res or {}).get("serverInfo") or {}
        try:
            self._send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        except Exception as e:      # noqa: silent-ok — 这个通知发不出去也能用
            self.log.debug("[%s] 发 initialized 通知失败（忽略）：%s", self.tag, e)
        return True

    # ---------------------------------------------------------------- 工具
    def tools(self, timeout=30):
        res, err = self.call("tools/list", {}, timeout)
        if err:
            return None, err
        return (res or {}).get("tools") or [], ""

    def call_tool(self, name, args, timeout=120):
        """调一个工具。返回 (文本, 错误串)。服务端自己报错（isError）也当文本返回。"""
        res, err = self.call("tools/call", {"name": name, "arguments": args or {}}, timeout)
        if err:
            return "", err
        parts = []
        for c in (res or {}).get("content") or []:
            if isinstance(c, dict) and c.get("type") == "text":
                parts.append(str(c.get("text") or ""))
        text = "\n".join(parts).strip()
        if (res or {}).get("isError") and not text:
            text = "服务端报错（没有给说明）"
        return text, ""

    # ---------------------------------------------------------------- 收尾
    def stop(self):
        """停掉子进程。**Windows 上要杀进程树** —— 只 terminate 父进程会留下孤儿。

        【为什么这条必须写】实测踩到过：命令行是 `cmd.exe /c node rea.mjs mcp` 时，
        terminate 只杀掉 cmd.exe，node 还活着并**继续占着 stdout 管道**，
        于是调用方（以及命令行工具）以为进程还没结束，一直等下去 ——
        表现就是"调用卡住十分钟"，而日志里一个字都没有。
        """
        pid = None
        try:
            if self.proc and self.proc.poll() is None:
                pid = self.proc.pid
        except Exception:      # noqa: silent-ok
            pid = None
        if pid:
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                               capture_output=True, timeout=15,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except Exception:      # noqa: silent-ok — taskkill 不在就退回 terminate
                pass
        try:
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except Exception:      # noqa: silent-ok — 不体面就强杀
                    self.proc.kill()
        except Exception:      # noqa: silent-ok
            pass
        finally:
            self.proc = None

    def alive(self):
        return bool(self.proc and self.proc.poll() is None)
