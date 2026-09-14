# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 能力登记处（CapabilityRegistry）

**能力不封顶**：现在的 77 个工具不是上限。用户往 `plugins/` 里丢一个 `.py` / `.json` / `.md`，
工具数就变；载体**不需要为了新工具改一行代码**。这个登记处就是"载体自己知道自己会什么"的那一环。

它回答三个问题（每次都现算，不缓存成真理）：
  1) 我现在有哪些工具？（`scan` / `available`）
  2) 跟上次比，多了什么 / 少了什么？（`added` / `removed` / `diff`）
  3) 用户刚丢进来的那个文件，算不算数？（`register`）

① 为什么必须"每次现扫"：
   能力是**外部事实**（取决于 plugins/ 目录里有什么），不是内存里的常量。
   启动时扫一次就再也不看，用户丢进新插件后必须重启才生效 —— 那就不是"不封顶"了。
② 去掉它会怎样：
   "我会什么"变成散落在 app 里的隐式知识；用户丢插件没生效、插件被停用没人知道、
   插件扫出几个工具说不清，也就谈不上"载体不为新工具改代码"。

三条自我约束（写死在代码里）：
  · **绝不删除任何文件**：`reload` 只报告增删，报告里那句"少了 xxx"是给用户看的提示，
    载体不去动用户的文件（要停用就自己改名 / 移进 plugins/_disabled/）。
  · **app 接口优先，目录扫描兜底**：app 在就用真接口（load_plugins + _build_tools + all_tool_names），
    app 不在（独立脚本、别的进程）就自己扫目录 —— 但目录扫描是**粗粒度估算**，只保证"大致不丢"。
  · **目录不存在也要能跑**：返回 count=0，绝不抛（空目录是合法状态，不是错误）。
"""
from __future__ import annotations

import hashlib
import importlib
import json
import logging
import os
import re
import sys
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]         # 仓库根：core/carrier/capability.py 往上三层
DEFAULT_PLUGINS_DIR = ROOT / "plugins"
STATE_DIR = ROOT / "logs" / "carrier"              # 载体数据落盘目录（logs/ 已被 .gitignore 忽略）
MANIFEST_FILE = STATE_DIR / "capabilities.json"

# 插件文件后缀：.py（Python 工具）/ .json（清单或 API 插件）/ .md（技能文档）/
# .js·.mjs（Node 插件，仓库里 plugin_runner.js 是运行器本身，不算插件）
PLUGIN_SUFFIXES = (".py", ".json", ".md", ".js", ".mjs")
_RUNNER_FILES = {"plugin_runner.js"}

# 跳过的目录名。`_disabled` 是**停用目录**（停用的插件放这里，用户一看就懂），
# 其余 `_xxx` / `.xxx` 沿用同一约定：下划线/点开头 = "不是给载体用的"。
_SKIP_DIRS = {"__pycache__", "_disabled", "node_modules", ".git"}

# 目录扫描用的正则（app 不可用时的兜底）。
# 为什么用正则而不是 exec 插件：兜底场景下插件依赖可能不全，import 一个插件就炸一次；
# 正则只读文本，永远不会因为插件自己坏掉而扫不动（代价是"可能多认几个名字"）。
_CODE_PATTERNS = (
    re.compile(r'["\']name["\']\s*:\s*["\']([A-Za-z_][A-Za-z0-9_.\-]{0,63})["\']'),
    re.compile(r'\bdef\s+tool_([A-Za-z_][A-Za-z0-9_]{0,63})\s*\('),
    re.compile(r'\b(?:register|register_tool|add_tool)\s*\(\s*["\']([A-Za-z_][A-Za-z0-9_.\-]{0,63})["\']'),
)
_TOOLS_LIST_RE = re.compile(r"\bTOOLS\s*=\s*\[(.*?)\]", re.S)
_QUOTED_RE = re.compile(r'["\']([A-Za-z_][A-Za-z0-9_.\-]{0,63})["\']')

# app 的 `load_plugins()` 用的是**相对 CWD** 的 "plugins" 路径：
# 小焦若不是从仓库根启动的，直接调它会扫空一大半工具。所以调 app 接口时临时切一下 CWD，
# 用同一把锁保护（多线程同时切目录会互相踩），调完立刻切回来 —— 不改用户进程长期的工作目录。
_APP_LOCK = threading.RLock()


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _names_from_code(text: str) -> set:
    """从 .py/.js 源码里"粗抽"工具名。抽多几个没关系（宁多勿少），抽不到才有问题。"""
    out = set()
    for pat in _CODE_PATTERNS:
        for m in pat.finditer(text):
            out.add(m.group(1))
    for block in _TOOLS_LIST_RE.findall(text):
        for m in _QUOTED_RE.finditer(block):
            out.add(m.group(1))
    return out


def _names_from_manifest(text: str) -> set:
    """从 .json 清单里抽工具名。

    有 `tools` 数组就以它为准（那才是工具清单）；没有才退而用清单自身的 `name`。
    ① 为什么优先 tools：`name` 是"这个插件包叫什么"，不等于它提供的工具名，
       直接当工具名会把 1 个包听成 2 个工具（一个包名 + 一个真工具名）。
    ② 读不出来（JSON 坏了）就返回空集：坏清单只是"这个文件不贡献工具"，
       不该让整次扫描失败。
    """
    try:
        data = json.loads(text)
    except Exception:      # noqa: silent-ok — 坏 JSON 只是这个文件不算数，不该拖垮整次扫描
        return set()
    out = set()
    if not isinstance(data, dict):
        return out
    ts = data.get("tools")
    if isinstance(ts, list) and ts:
        for it in ts:
            if isinstance(it, str) and it.strip():
                out.add(it.strip())
            elif isinstance(it, dict) and isinstance(it.get("name"), str) and it["name"].strip():
                out.add(it["name"].strip())
        return out
    nm = data.get("name")
    if isinstance(nm, str) and nm.strip():
        out.add(nm.strip())
    return out


class CapabilityRegistry:
    """能力登记处。默认盯 `<repo>/plugins`，落盘到 `logs/carrier/`。"""

    def __init__(self, plugins_dir=None, state_dir=None):
        """① 两个目录都可注入：自测要一个**临时插件目录**，不能拿用户真 plugins/ 做实验；
        ② 目录不存在也照常构造（`scan` 会返回 count=0）—— "还没有插件"是合法状态。"""
        self.plugins_dir = Path(plugins_dir).resolve() if plugins_dir else DEFAULT_PLUGINS_DIR
        self.state_dir = Path(state_dir).resolve() if state_dir else STATE_DIR
        self._lock = threading.RLock()
        self._last: dict | None = None            # 上次 scan 的完整结果 = diff 的基线
        self._last_diff = {"added": [], "removed": []}
        self._app_fp: str | None = None           # 上次调 app 接口时的目录指纹
        self._app_names: list | None = None       # 目录没变就直接复用，不重复 exec 插件
        self._watch_stop: threading.Event | None = None
        self._watch_thread: threading.Thread | None = None

    # ------------------------------------------------------------------ 内部工具
    def _is_default_dir(self) -> bool:
        """是不是在盯"真的 plugins/"。app 接口只反映它自己的 plugins/，别的目录问它没意义。"""
        return os.path.normcase(str(self.plugins_dir)) == os.path.normcase(str(DEFAULT_PLUGINS_DIR))

    def _walk_files(self) -> dict:
        """列出插件目录里算数的文件：{相对路径: {suffix, mtime, size, fp}}。

        `fp`（指纹）用 mtime_ns + size：比"只比 mtime"稳（同一秒内改两次也能看出来），
        比"读全文算哈希"便宜（用户可能丢进来 150KB 的插件，watch 每 30 秒算一次哈希太浪费）。
        """
        out: dict[str, dict] = {}
        if not self.plugins_dir.is_dir():
            return out
        for dirpath, dirnames, filenames in os.walk(self.plugins_dir):
            # 就地裁剪 dirnames：跳过的目录**连进都不进**（_disabled 里可能有几百个文件）
            dirnames[:] = [d for d in dirnames
                           if d not in _SKIP_DIRS and not d.startswith("_") and not d.startswith(".")]
            for fn in filenames:
                if fn.startswith("__") or fn in _RUNNER_FILES:
                    continue
                suf = os.path.splitext(fn)[1].lower()
                if suf not in PLUGIN_SUFFIXES:
                    continue
                p = Path(dirpath) / fn
                try:
                    st = p.stat()
                except OSError:      # noqa: silent-ok — 扫描途中有文件被删/锁住，跳过它继续扫
                    continue
                rel = str(p.relative_to(self.plugins_dir))
                out[rel] = {"suffix": suf, "mtime": round(st.st_mtime, 3), "size": st.st_size,
                            "fp": "%d:%d" % (st.st_mtime_ns, st.st_size)}
        return out

    def _fingerprint(self, files: dict | None = None) -> str:
        """整个插件目录的指纹（watch 靠它判断"用户丢东西进来了没"）。"""
        files = self._walk_files() if files is None else files
        blob = "|".join("%s=%s" % (k, v["fp"]) for k, v in sorted(files.items()))
        return hashlib.sha1(blob.encode("utf-8", "replace")).hexdigest()

    def _read_text(self, p: Path) -> str:
        """读插件源码文本（编码坏了也不抛：errors=replace，扫目录不该被一个坏字节卡死）。"""
        try:
            return p.read_text(encoding="utf-8", errors="replace")
        except OSError:      # noqa: silent-ok — 读不了就当这个文件没内容，继续扫别的
            return ""

    def _dir_scan(self, files: dict) -> tuple:
        """自己扫目录（app 不可用时的兜底）。返回 (工具名列表, 技能文档数)。"""
        tools, skills = set(), 0
        for rel, info in files.items():
            if info["suffix"] == ".md":
                skills += 1      # .md 是技能/知识文档：只计数，它不提供"可调用的工具"
                continue
            text = self._read_text(self.plugins_dir / rel)
            if not text:
                continue
            if info["suffix"] == ".json":
                tools |= _names_from_manifest(text)
            else:
                tools |= _names_from_code(text)
        return sorted(tools), skills

    def _app_tools(self, fp: str) -> list:
        """优先走 app 的真接口拿工具表（那是**权威**清单：内置 + 插件，且执行路由也是它）。

        目录没变就直接复用上次结果：`load_plugins()` 会重新 exec 每个插件（scrapling_bridge
        有 15 万字符），每 30 秒 watch 一次都重 exec 一遍是纯浪费，还可能重复触发插件的初始化副作用。
        """
        if self._app_names is not None and self._app_fp == fp:
            return list(self._app_names)
        try:
            # 已在 sys.modules 里就直接用（在 app 进程内调用时不会重复 import 一遍）
            app = sys.modules.get("xiaojiao_app") or importlib.import_module("xiaojiao_app")
        except Exception as e:      # noqa: silent-ok — app 不在是很正常的情形，退回目录扫描即可
            logger.info("app 接口不可用（%s），本次退回目录扫描", e)
            return []
        names: list = []
        with _APP_LOCK:
            cwd, changed = os.getcwd(), False
            try:
                if os.path.normcase(os.path.abspath(cwd)) != os.path.normcase(str(ROOT)):
                    os.chdir(str(ROOT))
                    changed = True
                # `load_plugins()` 会把 .md 技能**追加**进 app.PLUGIN_SKILLS（列表只增不减）：
                # 记下长度、调完裁回去 —— 否则每扫一次能力，人设里就多一份重复的技能文本。
                skills_len = len(getattr(app, "PLUGIN_SKILLS", []) or [])
                try:
                    if hasattr(app, "load_plugins"):
                        app.load_plugins()
                except Exception as e:      # noqa: silent-ok — 某个插件自己炸了，不影响清点其它插件
                    logger.warning("load_plugins() 抛错（%s），继续用现有注册表清点", e)
                sl = getattr(app, "PLUGIN_SKILLS", None)
                if isinstance(sl, list) and len(sl) > skills_len:
                    del sl[skills_len:]
                if hasattr(app, "all_tool_names"):
                    names = [n for n in (app.all_tool_names() or []) if n]
                if not names and hasattr(app, "_build_tools"):
                    names = [((t or {}).get("function") or {}).get("name")
                             for t in (app._build_tools() or [])]
                names = [n for n in names if n]
            except Exception as e:      # noqa: silent-ok — 调 app 接口出任何意外都退回目录扫描
                logger.warning("读 app 工具表失败（%s），退回目录扫描", e)
                names = []
            finally:
                if changed:
                    try:
                        os.chdir(cwd)
                    except Exception as e:      # noqa: silent-ok — 切不回原目录也不能让扫描抛出去
                        logger.warning("恢复工作目录失败（%s）：%s", cwd, e)
        if names:
            self._app_names, self._app_fp = list(names), fp
        return names

    # ------------------------------------------------------------------ 对外接口
    def scan(self, use_app: bool = True) -> dict:
        """清点能力。启动时 / 用户丢新插件 / 手动触发时都调它。

        返回 {"tools":[...],"count":n,"added":[...],"removed":[...],"files":n,"source":"app"/"dir",
             "elapsed_ms":x, ...}
        ① 首次扫描 added 为空（只建立基线）：否则"新增"会把全部工具都报一遍，
           用户根本看不出**这次**新丢进来的是哪一个。
        ② source 必须报出来：app 接口（权威）与目录扫描（粗估）的可信度不同，
           报告里混在一起，用户排查"为什么工具数不对"时会走错方向。
        """
        t0 = time.time()
        with self._lock:
            files = self._walk_files()
            fp = self._fingerprint(files)
            tools, skills, source = [], 0, "dir"
            if use_app and self._is_default_dir():
                names = self._app_tools(fp)
                if names:
                    tools, source = sorted(set(names)), "app"
            if source != "app":
                tools, skills = self._dir_scan(files)
            prev = self._last
            added = sorted(set(tools) - set(prev["tools"])) if prev else []
            removed = sorted(set(prev["tools"]) - set(tools)) if prev else []
            result = {"tools": tools, "count": len(tools), "added": added, "removed": removed,
                      "files": len(files), "skills": skills, "source": source,
                      "plugins_dir": str(self.plugins_dir), "ts": _now(),
                      "elapsed_ms": int((time.time() - t0) * 1000)}
            self._last = result
            self._last_diff = {"added": added, "removed": removed}
            if added or removed:
                logger.info("能力变化：+%d / -%d（共 %d 个工具，%d 个插件文件）",
                            len(added), len(removed), len(tools), len(files))
            return dict(result)

    def available(self) -> list:
        """当前可用工具名（排序）。还没扫过就先扫一次 —— 调用方不必记得"要先 scan"。"""
        with self._lock:
            if self._last is None:
                self.scan()
            return sorted(self._last["tools"])

    def register(self, path) -> dict:
        """登记一个**刚丢进来**的插件文件，返回 {ok, path, type, tools, count} 或 {ok:False, error}。

        为什么只"读"不"搬"：用户可能把文件丢在别处（下载目录、桌面），
        载体替他移动/复制文件是**破坏性**的（可能覆盖同名文件、可能他只想先试试）。
        所以只接受已经在 plugins/ 里的文件，别处的一律返回 ok=False 并说清原因。
        """
        with self._lock:
            if self.plugins_dir.is_dir() and not Path(path).is_absolute():
                cand = [Path(path), self.plugins_dir / path]
            else:
                cand = [Path(path)]
            target = next((p for p in cand if p.exists()), None)
            if target is None:
                return {"ok": False, "error": "文件不存在：%s" % path}
            if not target.is_file():
                return {"ok": False, "error": "不是文件（是目录？）：%s" % target}
            suf = target.suffix.lower()
            if suf not in PLUGIN_SUFFIXES:
                return {"ok": False, "error": "不支持的类型 %s（只认 %s）"
                                             % (suf or "无后缀", "/".join(PLUGIN_SUFFIXES))}
            try:
                rel = target.resolve().relative_to(self.plugins_dir)
            except Exception:      # noqa: silent-ok — 不在插件目录内 → 走下面的明确报错分支
                return {"ok": False, "error": "文件不在插件目录 %s 内；请先放进该目录"
                                              "（载体不替用户搬动文件）" % self.plugins_dir}
            if suf == ".md":
                return {"ok": True, "path": str(target), "type": "skill", "tools": [],
                        "count": self._last["count"] if self._last else 0,
                        "note": ".md 是技能文档，只计入文件数，不提供可调用工具"}
            text = self._read_text(target)
            names = _names_from_manifest(text) if suf == ".json" else _names_from_code(text)
            names = sorted(names)
            info = {"suffix": suf, "mtime": round(target.stat().st_mtime, 3),
                    "size": target.stat().st_size}
            if self._last is not None:
                merged = sorted(set(self._last["tools"]) | set(names))
                self._last = dict(self._last, tools=merged, count=len(merged))
            logger.info("登记插件 %s：type=%s，工具 %d 个 %s", rel, suf.lstrip("."), len(names), names)
            return {"ok": True, "path": str(target), "rel": str(rel), "type": suf.lstrip("."),
                    "tools": names, "count": self._last["count"] if self._last else len(names),
                    "info": info}

    def reload(self) -> dict:
        """重扫 + 与上次比对。**只报告增删，绝不删除任何文件。**

        与 scan 的差别只是"语义"：scan 是"看看现在有什么"，reload 是"我刚改了插件，看看变了啥"。
        `removed` 里的名字是**提示**（"这个工具不见了，你去看看是不是文件改名/停用了"），
        载体不会顺着这个提示去动用户的文件。
        """
        res = self.scan()
        res["reloaded"] = True
        res["note"] = "只报告增删；载体绝不删除/移动用户的插件文件"
        return res

    def watch(self, on_change=None, interval_s: int = 30) -> None:
        """后台看守插件目录（daemon 线程）：mtime+size 指纹一变，就重扫并回调 on_change(scan结果)。

        为什么需要它：用户丢插件是**运行中**发生的动作，没人会为此重启小焦。
        为什么是轮询而不是看门狗事件：跨平台可靠（Windows 上 inotify 那套不可用），
        30 秒一次 stat 的代价可以忽略，而"丢了插件半分钟内自动生效"体验已经足够。
        """
        with self._lock:
            if self._watch_thread is not None and self._watch_thread.is_alive():
                logger.info("能力看守线程已在运行，不重复启动")
                return
            stop = threading.Event()
            self._watch_stop = stop
            interval = max(1.0, float(interval_s or 30))

        def _loop():
            last_fp = self._fingerprint()
            while not stop.wait(interval):
                try:
                    fp = self._fingerprint()
                    if fp == last_fp:
                        continue
                    last_fp = fp
                    res = self.scan()
                    if on_change is not None:
                        try:
                            on_change(res)
                        except Exception as e:      # noqa: silent-ok — 用户回调炸了不能把看守线程带走
                            logger.warning("能力变化回调抛错：%s", e)
                except Exception as e:      # noqa: silent-ok — 轮询这一次失败，下一轮继续，看守不能停
                    logger.warning("能力看守轮询失败：%s", e)

        th = threading.Thread(target=_loop, name="carrier-capability-watch", daemon=True)
        with self._lock:
            self._watch_thread = th
        th.start()
        logger.info("开始看守插件目录 %s（每 %.0f 秒一次）", self.plugins_dir, interval)

    def stop_watch(self) -> None:
        """停掉看守线程。**在回调里调它也安全**（不会自己 join 自己 → 死锁）。"""
        with self._lock:
            stop, th = self._watch_stop, self._watch_thread
        if stop is not None:
            stop.set()
        if th is not None and th.is_alive() and th is not threading.current_thread():
            th.join(timeout=2)
        with self._lock:
            self._watch_thread = None

    def manifest(self) -> dict:
        """把当前能力清单落盘到 `logs/carrier/capabilities.json`：{ts,count,tools,files:{name:mtime}}。

        为什么要落盘：能力清单是**跨会话的事实**（"昨天有几个工具"），
        只在内存里的话，重启一次就没法回答"怎么少了两个工具"这类问题。
        app 的 history / 记忆都在文件里，能力清单一视同仁。
        """
        res = self.scan()
        files = {rel: info["mtime"] for rel, info in self._walk_files().items()}
        rec = {"ts": res["ts"], "count": res["count"], "tools": res["tools"], "files": files,
               "source": res["source"], "skills": res["skills"],
               "plugins_dir": res["plugins_dir"]}
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            with open(self.state_dir / MANIFEST_FILE.name, "w", encoding="utf-8") as f:
                json.dump(rec, f, ensure_ascii=False, indent=2)
        except Exception as e:      # noqa: silent-ok — 写不了清单只影响"留档"，能力本身照样可用
            logger.warning("能力清单写盘失败：%s", e)
            rec["write_error"] = str(e)
        return rec

    def diff(self) -> dict:
        """最近一次比对的新增 / 消失（报告用）。还没扫过就先扫一次。"""
        with self._lock:
            if self._last is None:
                self.scan()
            d = dict(self._last_diff)
            d["added_count"] = len(d["added"])
            d["removed_count"] = len(d["removed"])
            d["count"] = self._last["count"] if self._last else 0
            d["ts"] = _now()
            return d
