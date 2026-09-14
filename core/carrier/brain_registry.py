# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 火种登记处（BrainRegistry）

用户看到的是「小焦」，不是「某个模型」。模型（大脑 / 小脑）是**零件 / 火种**：
LLaMA、Agnes、任何 OpenAI 兼容端点，都只是插进同一个插座的一颗火种。
小焦（载体）= 整个变形金刚系统：记忆、插件工具、世界（控制文件）、会话都在载体里，不归火种管。

**换火种不换小焦**：
  · 记忆 → xiaojiao_memory.txt / 向量库
  · 工具 → plugins/ 目录（CapabilityRegistry）
  · 世界 → xiaojiao_control.json
  · 会话 → xiaojiao_sessions.json
所以 `switch()` **只挪一个"当前火种"指针**，上面四样一个都不碰 —— 这是热插拔，不重启、不丢状态。
为什么必须这样：如果切换顺手"重置一下状态"，用户换一次模型就丢一次记忆，
那这个系统就变成"换模型 = 换小焦"，与设计意图正好相反。

① 这一层为什么存在：
   以前"用哪个模型"散落在控制文件 brain.api、环境变量、models 列表、启动脚本里，
   换一颗火种要手改文件 + 重启 + 重新记配置，而且**没有"它挂了怎么办"**。
   集中成登记处之后，"有哪些火种 / 现在烧哪颗 / 挂没挂 / 谁来顶"变成可查询的数据。
② 去掉它会怎样：
   换模型退回"手改配置 + 重启"；一颗火种 401 了系统就哑掉，没有"下一颗顶上"。

两条铁律（写死在代码里，不靠使用者自觉）：
  1) **默认不写盘**：persist 默认是内存 no-op —— 登记处绝不悄悄改用户的 xiaojiao_control.json。
  2) **绝不抛**：探测 / 应用 / 写日志全部兜住异常。火种探测失败是常态（服务没起、端口被占、
     Key 过期），一次失败不能把调用方（对话主循环）带走。
"""
from __future__ import annotations

import importlib
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# 仓库根 = core/carrier/brain_registry.py 往上三层。**用 __file__ 推算，不写死盘符**：
# 换机器 / 换盘符路径依然对（硬编码绝对路径是静态审计会报的坏味道）。
ROOT = Path(__file__).resolve().parents[2]
CONTROL_FILE = ROOT / "xiaojiao_control.json"
CARRIER_DIR = ROOT / "logs" / "carrier"          # 载体数据一律落这里（logs/ 已被 .gitignore 忽略）
SWITCH_LOG = CARRIER_DIR / "brain_switch.jsonl"  # 换火种历史：{ts, from, to, reason, ok}
APPLY_LOG = CARRIER_DIR / "brain_apply.jsonl"    # 把火种写进 app 全局变量的记录
CONFIG_LOG = CARRIER_DIR / "brain_config.jsonl"  # 配置读坏了（跳过的那一条）的记录

PROBE_TIMEOUT = 3       # 单颗火种探测超时（秒）。3 秒够一次本地 /models 往返，再长就拖住界面
DEFAULT_PRIORITY = 100  # 数字越小越优先；备胎就按它排序

_LOCAL_HINTS = ("127.0.0.1", "localhost", "0.0.0.0", "::1", "host.docker.internal",
                "10.", "192.168.", "172.16.", "172.17.", "172.18.", "172.19.")


def _now() -> str:
    """统一时间戳格式（本地时区，人能直接读的那种）。"""
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _append_jsonl(path: Path, rec: dict) -> bool:
    """往载体日志追加一行 JSON。

    **为什么外面再包一层 try**：写日志失败（盘满、权限、被杀软锁住）只是少一条记录，
    绝不能让"切换火种"这件事因此失败 —— 日志是给人事后看的，不是主流程的依赖。
    去掉这层保护：日志目录一旦不可写，整个切换链路就跟着崩，用户面前直接报错。
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return True
    except Exception as e:      # noqa: silent-ok — 日志写不进去不能中断切换/注册
        logger.debug("载体日志写入失败 %s：%s", path, e)
        return False


def _as_bool(v, default=True) -> bool:
    """把配置里的开关读成 bool。

    **为什么要这一步**：控制文件是手写的，用户会写 "local": "false" / "True" / 0 / ""，
    直接 bool("false") == True 会把"关掉的火种"当成开着的 —— 那就切到一颗用户明明停用的火种上。
    """
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on", "y", "是", "开")
    return default


def _as_int(v, default=0) -> int:
    """把配置里的数字读成 int（读不出来就用默认值，绝不抛）。"""
    try:
        return int(v)
    except Exception:      # noqa: silent-ok — 配置里写了个"三万"之类，用默认值比崩掉强
        return default


def _http_get_json(url: str, key: str = "", timeout: int = PROBE_TIMEOUT):
    """GET 一个 JSON，返回 (ok, status, data, error)。**任何失败都变成返回值，绝不抛**。

    为什么不用 app 里的 `_llm_post`：那个是"发对话请求"，而探测只是想知道"这个端点在不在、
    有哪些模型"，用最轻的 GET /models 就行 —— 探测不该消耗对方的生成额度 / 触发限流。
    也没有新增依赖：优先用已装好的 requests，没有就退回标准库 urllib，功能一样。
    """
    headers = {"Accept": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key      # 云端多数网关不带这个头会回 401
    try:
        import requests
    except Exception:      # noqa: silent-ok — 极简环境没有 requests，走下面的 urllib 分支
        requests = None

    if requests is not None:
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            status = r.status_code
            data = None
            try:
                data = r.json()
            except Exception:      # noqa: silent-ok — 非 JSON 的返回（网关 HTML 报错页）也要能探测出结论
                data = None
            if status != 200:
                return False, status, None, "HTTP %s" % status
            if data is None:
                return False, status, None, "返回的不是 JSON"
            return True, status, data, ""
        except Exception as e:      # noqa: silent-ok — 连不上/超时都要变成 ok=False，而不是抛出
            return False, None, None, "%s: %s" % (type(e).__name__, e)

    try:
        import urllib.request
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            raw = resp.read().decode("utf-8", "replace")
            data = json.loads(raw or "{}")
            if status != 200:
                return False, status, None, "HTTP %s" % status
            return True, status, data, ""
    except Exception as e:      # noqa: silent-ok — 同上：探测失败是结论，不是异常
        return False, None, None, "%s: %s" % (type(e).__name__, e)


def _extract_models(data) -> list:
    """从 /models 的返回里抽出模型名。

    兼容三种真实形状：{"data":[{"id":..}]}（OpenAI 标准）、{"models":[{"name":..}]}
    （llama.cpp / Ollama 风格）、["m1","m2"]（裸列表）。
    为什么要兼容：不同火种的"自我介绍"格式不一样，载体得听懂所有口音，否则"探测"永远是失败的。
    """
    items = []
    if isinstance(data, dict):
        for k in ("data", "models", "result"):
            if isinstance(data.get(k), list):
                items = data[k]
                break
    elif isinstance(data, list):
        items = data
    out = []
    for it in items:
        if isinstance(it, str) and it.strip():
            out.append(it.strip())
        elif isinstance(it, dict):
            for k in ("id", "name", "model"):
                if isinstance(it.get(k), str) and it[k].strip():
                    out.append(it[k].strip())
                    break
    return out


class Brain:
    """一颗**火种**的纯数据描述（不含任何行为副作用）。

    ① 为什么是纯数据：火种会被序列化进 snapshot / 日志 / 配置，一旦它自己持有连接、
       线程或状态，序列化和替换就会变得危险；纯数据让"换火种"退化成"换一个字典"。
    ② 去掉会怎样：每个调用点各自记 url/model/key，谁也不知道"当前这颗"长什么样，
       更没法比较、排序、兜底。
    """

    def __init__(self, name: str, base_url: str = "", model: str = "", api_key: str = "",
                 kind: str = "local", priority: int = DEFAULT_PRIORITY, enabled: bool = True,
                 ctx: int = 0, note: str = "", health: dict | None = None):
        self.name = str(name or "").strip()
        self.base_url = str(base_url or "").strip()
        self.model = str(model or "").strip()
        self.api_key = str(api_key or "").strip()
        self.kind = "local" if str(kind or "local").strip().lower() in ("local", "本地") else "cloud"
        self.priority = _as_int(priority, DEFAULT_PRIORITY)
        self.enabled = _as_bool(enabled, True)
        self.ctx = _as_int(ctx, 0)          # 上下文窗口（token）；0 = 不知道，交给上层判断
        self.note = str(note or "")
        self.health = health if isinstance(health, dict) else None

    # ---- 便捷别名：配置里 url/model/key/local 是常见写法，读的时候两种都能用 ----
    @property
    def url(self) -> str:
        return self.base_url

    @property
    def local(self) -> bool:
        return self.kind == "local"

    def health_ok(self) -> bool:
        """这颗火种现在能不能用。**没探测过 = 能用**。

        为什么不把"没探测过"当不健康：刚配置好的火种还没探过，若因此被排除，
        "自动兜底"会找不到备胎 —— 宁可让它被试一次（试错成本只是一次 HTTP）。
        """
        if not self.enabled:
            return False
        if isinstance(self.health, dict) and self.health.get("ok") is False:
            return False
        return True

    def models_url(self) -> str:
        """探测用的地址：把 base_url 归一到 {base}/models（用户直接填了 /chat/completions 也认）。"""
        base = self.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            base = base[: -len("/chat/completions")]
        return base + "/models"

    def to_target(self) -> dict:
        """转成 `xiaojiao_app._llm_targets()` 那种形状：{url, model, key, local}。

        字段名**照抄** app 的既有约定（`_llm_post` 只认 url / key），这样登记处的新火种
        不用改 app 一行代码就能被调用 —— "接入任何模型，系统不变"就落在这个函数上。
        """
        base = self.base_url.rstrip("/")
        if not base:
            url = ""
        elif base.endswith("/chat/completions"):
            url = base
        else:
            url = base + "/chat/completions"
        return {"url": url, "model": self.model or self.name, "key": self.api_key,
                "local": self.kind == "local"}

    def probe(self, timeout: int = PROBE_TIMEOUT) -> dict:
        """真发一次 HTTP GET {base}/models，返回 {ok,status,models,error,elapsed_ms}。

        为什么必须"真探"而不是相信配置：配置写的是"我以为它在哪"，探测才知道"它到底活没活"
        （服务没起 / 端口被别的东西占了 / Key 过期，都不是配置能表达的）。
        结果顺手记进 self.health —— health_check / fallback / snapshot 直接复用，不必再探一次。
        """
        t0 = time.time()
        ok, status, data, err = _http_get_json(self.models_url(), self.api_key, timeout)
        models = _extract_models(data) if ok else []
        res = {"ok": bool(ok), "status": status, "models": models,
               "error": "" if ok else (err or "探测失败"),
               "elapsed_ms": int((time.time() - t0) * 1000)}
        self.health = dict(res)
        return res

    def to_dict(self, mask_key: bool = True) -> dict:
        """给 snapshot / 日志用的字典。**默认把 Key 掩掉**：
        载体日志可能被用户贴给别人看，Key 不能跟着流出去（只报"设没设"，不报内容）。"""
        d = {"name": self.name, "base_url": self.base_url, "model": self.model,
             "kind": self.kind, "priority": self.priority, "enabled": self.enabled,
             "ctx": self.ctx, "note": self.note, "health": self.health}
        d["api_key"] = ("已设置" if self.api_key else "") if mask_key else self.api_key
        return d

    @classmethod
    def from_config(cls, name: str, cfg: dict) -> "Brain":
        """从配置片段建一颗火种；**字段名兼容两套写法**。

        为什么兼容：老配置写 `url`/`key`/`local`，新文档写 `base_url`/`api_key`/`kind`。
        只认一种就会把用户"明明配好了"的火种读成空的（表现为"切过去就 401"）。
        """
        e = cfg if isinstance(cfg, dict) else {}
        base_url = e.get("base_url") or e.get("url") or ""
        api_key = e.get("api_key") or e.get("key") or ""
        if e.get("kind"):
            kind = e["kind"]
        elif e.get("local") is not None:
            kind = "local" if _as_bool(e.get("local"), True) else "cloud"
        else:
            # 没有任何线索 → 按地址猜（本机/内网 = local）。猜错也只是显示，不影响调用。
            kind = "local" if any(h in str(base_url) for h in _LOCAL_HINTS) else "cloud"
        return cls(name=name, base_url=base_url, model=e.get("model") or "",
                   api_key=api_key, kind=kind,
                   priority=e.get("priority", DEFAULT_PRIORITY),
                   enabled=e.get("enabled", True), ctx=e.get("ctx", 0),
                   note=e.get("note", ""),
                   health=e.get("health") if isinstance(e.get("health"), dict) else None)


class BrainRegistry:
    """火种登记处：登记 / 切换 / 兜底 / 体检 / 应用到 app。线程安全（一把 RLock 足够）。"""

    def __init__(self, config=None, persist=None):
        """config：{"brains":[...], "active_brain":"name"}；不传就**惰性**读 xiaojiao_control.json。
        persist：回调 persist(name)，把"当前火种"写回配置。**默认是内存 no-op**（关键！）。

        ① 为什么 persist 默认不写盘：自测、脚本、多实例都会 new 一个登记处；
           如果默认就写 xiaojiao_control.json，跑一次测试就把用户的真实配置改了 —— 这是事故。
           想持久化的人**显式**传一个回调，权责清楚。
        ② 为什么 config 要"惰性"读：导入 core.carrier 时不该产生任何磁盘读取 / 副作用，
           否则"某个模块 import 了一下"就能让启动变慢或读到半截文件。
        """
        self._lock = threading.RLock()
        self._brains: dict[str, Brain] = {}      # 保持插入顺序（list_brains 会再按优先级排）
        self._active = ""
        self._config = config
        self._source = "未加载"
        self._loaded = False
        self._persist_is_default = not callable(persist)
        self._persist_pending = ""
        self._persist = persist if callable(persist) else self._noop_persist

    # ------------------------------------------------------------------ 持久化
    def _noop_persist(self, name: str) -> bool:
        """默认持久化 = **只记在内存里**，一个字节都不写盘。

        为什么要留这个方法而不是 None：切换流程可以无条件调用 self._persist(name)，
        调用点不必到处判断"是不是默认"，代码少一个分支就少一个漏判（漏判的后果就是
        某条路径真的去写了用户的配置）。
        """
        self._persist_pending = name
        logger.debug("persist 为默认 no-op：当前火种 %s 只记在内存，未写盘", name)
        return False

    # ------------------------------------------------------------------ 配置加载
    def _read_control(self) -> dict | None:
        """读 xiaojiao_control.json。读不到 / 读坏了都返回 None（= 空登记处），并记日志。"""
        try:
            with open(CONTROL_FILE, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            logger.info("没有 %s：火种登记处先空着（app 自己的单火种配置照常工作）", CONTROL_FILE.name)
            return None
        except Exception as e:      # noqa: silent-ok — 配置坏掉时"没有火种"比"启动崩溃"好
            self._log_config_error("控制文件读不出来，按空登记处处理", str(e))
            return None

    def _log_config_error(self, msg: str, raw="") -> None:
        """配置读坏时记一条**文件日志**（不只 logger）。

        为什么落文件：控制文件是用户手改的，出错时用户看不到进程日志，但会翻 logs/。
        记录里带上原文片段，用户一眼就知道是哪一行写错了。
        """
        logger.warning("火种配置：%s（已跳过）", msg)
        _append_jsonl(CONFIG_LOG, {"ts": _now(), "error": msg,
                                   "raw": str(raw)[:400], "source": self._source})

    def _compat_brains(self, cfg: dict) -> dict:
        """兼容老配置形状：没有 `brains` 就从 `models`（列表）/ `brain.api` 里凑出火种。

        为什么值得兼容：现网控制文件里写的是 `models`（还有 brain.api），
        如果只认 `brains`，用户升级后登记处是空的，"换火种"这个功能看起来就是坏的。
        凑出来的名字取自各条的 name 字段 —— 名字是用户的称呼，不能替它编。
        """
        out: dict[str, dict] = {}
        models = cfg.get("models")
        if isinstance(models, list):
            for m in models:
                if isinstance(m, dict) and str(m.get("name") or "").strip():
                    out[str(m["name"]).strip()] = m
        api = (cfg.get("brain") or {}).get("api") if isinstance(cfg.get("brain"), dict) else None
        if isinstance(api, dict) and api.get("base_url") and "默认大脑" not in out:
            out["默认大脑"] = dict(api)
        return out

    def _load_config(self, cfg) -> None:
        """把配置灌进登记处。**坏一条跳一条，绝不整体失败**。

        为什么这么宽：火种配置是用户手写的，一个人多打一个逗号不该让整个"换火种"功能消失；
        能读的火种照常登记，读不了的记进 logs/carrier/brain_config.jsonl 让用户去修。
        """
        if cfg is None:
            return
        if not isinstance(cfg, dict):
            self._log_config_error("配置根不是对象（dict）", cfg)
            return
        raw = cfg.get("brains")
        if raw is not None and not isinstance(raw, (list, dict)):
            self._log_config_error("brains 的形状不对（要 list 或 dict）", raw)
            raw = None
        if raw is None:
            raw = self._compat_brains(cfg)
            if raw:
                logger.info("配置里没有 brains，已按老写法 models/brain.api 兜出 %d 颗火种", len(raw))
        entries = []
        if isinstance(raw, dict):
            for k, v in raw.items():
                entries.append((str(k), v))
        elif isinstance(raw, list):
            for v in raw:
                if not isinstance(v, dict):
                    self._log_config_error("brains 列表里有一条不是对象，已跳过", v)
                    continue
                entries.append((str(v.get("name") or "").strip(), v))
        for name, val in entries:
            if not name:
                self._log_config_error("火种缺 name，已跳过（名字是它的唯一身份，不能猜）", val)
                continue
            if name in self._brains:
                self._log_config_error("火种重名 %s，已跳过后一条" % name, val)
                continue
            self._brains[name] = Brain.from_config(name, val)
        act = cfg.get("active_brain") or cfg.get("active") or ""
        act = str(act).strip()
        if act and act in self._brains:
            self._active = act
        elif act:
            self._log_config_error("active_brain=%s 不在火种表里，先不指定当前火种" % act, act)

    def _ensure_loaded(self) -> None:
        """惰性加载：第一次真正要用的时候才读配置（一次，之后走内存）。"""
        with self._lock:
            if self._loaded:
                return
            self._loaded = True
            cfg = self._config
            if cfg is None:
                self._source = str(CONTROL_FILE)
                cfg = self._read_control()
            else:
                self._source = "构造参数 config"
            self._load_config(cfg)

    # ------------------------------------------------------------------ 基本操作
    def register(self, name, config) -> bool:
        """登记一颗火种。**重名返回 False（不覆盖）**。

        为什么不覆盖：同名覆盖等于"悄悄换掉了用户当前正在用的火种" ——
        用户以为改的是新火种，结果当前会话的中枢被换了。要改就先 unregister，意图明确。
        第一个注册的火种自动成为当前火种（否则登记完还得再切一次，纯多余的步骤）。
        """
        with self._lock:
            self._ensure_loaded()
            nm = str(name or "").strip()
            if not nm:
                return False
            if nm in self._brains:
                return False
            self._brains[nm] = config if isinstance(config, Brain) else Brain.from_config(nm, config)
            if not self._active:
                self._active = nm
            return True

    def unregister(self, name) -> bool:
        """注销一颗火种。**不自动改选当前火种**（悄悄换掉用户的选择是更坏的"贴心"）。"""
        with self._lock:
            self._ensure_loaded()
            nm = str(name or "").strip()
            if nm not in self._brains:
                return False
            del self._brains[nm]
            if self._active == nm:
                self._active = ""
            return True

    def get(self, name) -> "Brain | None":
        with self._lock:
            self._ensure_loaded()
            return self._brains.get(str(name or "").strip())

    def names(self) -> list:
        with self._lock:
            self._ensure_loaded()
            return sorted(self._brains.keys())

    def list_brains(self) -> list:
        """按 (优先级, 名字) 排序返回（稳定顺序 → 每次看到的清单顺序一致，方便对比）。"""
        with self._lock:
            self._ensure_loaded()
            bs = sorted(self._brains.values(), key=lambda b: (b.priority, b.name))
            return [b.to_dict() for b in bs]

    def current(self) -> "Brain | None":
        with self._lock:
            self._ensure_loaded()
            return self._brains.get(self._active)

    # ------------------------------------------------------------------ 切换（核心）
    def switch(self, name) -> bool:
        """热插拔：只把"当前火种"指针挪到 name 上。**载体状态一个都不碰**。

        为什么敢这么"轻"：记忆 / 工具 / 世界 / 会话都挂在载体自己身上（文件与目录），
        火种只是一次 HTTP 请求的目的地。所以切换 = 改一个字符串 + 记一条日志，
        **不需要重新加载模型、不需要重建记忆、不需要重启进程**。
        app 那边之所以立刻生效，是因为 `_llm_targets()` 每次请求都**现读** LLM_BASE/LLM_MODEL。
        """
        return self._set_active(name, reason="manual")

    def _set_active(self, name, reason: str = "") -> bool:
        """切换的唯一实现（switch / auto_fallback 共用），保证"日志只有一条、语义只有一种"。"""
        with self._lock:
            self._ensure_loaded()
            nm = str(name or "").strip()
            b = self._brains.get(nm)
            old = self._active
            if b is None:
                _append_jsonl(SWITCH_LOG, {"ts": _now(), "from": old, "to": nm,
                                           "reason": "火种不存在", "ok": False})
                logger.warning("切换失败：没有名为 %s 的火种", nm)
                return False
            if not b.enabled:
                _append_jsonl(SWITCH_LOG, {"ts": _now(), "from": old, "to": nm,
                                           "reason": "火种已被停用", "ok": False})
                logger.warning("切换失败：火种 %s 处于停用状态", nm)
                return False
            self._active = nm                 # ← 全部副作用就这一行
        # 出锁后再写盘 / 记日志：persist 是**外部回调**，握着锁调它有死锁风险
        self._persist(nm)
        _append_jsonl(SWITCH_LOG, {"ts": _now(), "from": old, "to": nm, "reason": reason, "ok": True})
        logger.info("当前火种：%s → %s（%s）", old or "无", nm, reason)
        return True

    # ------------------------------------------------------------------ 兜底
    def fallback(self, exclude=None) -> "Brain | None":
        """当前火种出问题时，按 priority 选下一颗可用的（不切换，只挑选）。

        选择规则：enabled 且不健康标记为 False 且不在 exclude 里，按 (优先级, 名字) 取第一颗。
        ① 为什么把 exclude 默认设为"当前火种"：兜底的意义就是**换一颗**；
           不排除当前那颗，一旦它 priority 最小就会原地打转（切了等于没切）。
        ② 为什么排序而不是"第一个 found"：dict 顺序是配置书写顺序，
           而"哪颗更该顶上"是用户用 priority 表达的意图，必须尊重。
        """
        with self._lock:
            self._ensure_loaded()
            if exclude is None:
                ex = {self._active} if self._active else set()
            elif isinstance(exclude, str):
                ex = {exclude}
            else:
                ex = {str(x) for x in exclude}
            cands = [b for b in self._brains.values() if b.health_ok() and b.name not in ex]
            if not cands:
                return None
            cands.sort(key=lambda b: (b.priority, b.name))
            return cands[0]

    def auto_fallback(self, reason: str = "") -> "Brain | None":
        """fallback + switch + 记日志（一次调用完成"救场"）。返回顶上来的那颗火种（没有就 None）。

        为什么要有它：云端 401 / 限流 / 超时是**常态**，靠人去发现"它挂了"再手切不现实。
        自动兜底让"一颗火种坏了"退化成"这一条消息慢一点"，用户甚至注意不到。
        """
        cur = self.current()
        nxt = self.fallback(exclude=cur.name if cur else None)
        if nxt is None:
            _append_jsonl(SWITCH_LOG, {"ts": _now(), "from": cur.name if cur else "", "to": "",
                                       "reason": reason or "auto_fallback（无可用备胎）", "ok": False})
            logger.warning("当前火种不可用，但没有备胎可顶（火种数=%d）", len(self.names()))
            return None
        ok = self._set_active(nxt.name, reason=reason or "auto_fallback")
        return nxt if ok else None

    # ------------------------------------------------------------------ 健康
    def mark_unhealthy(self, name, reason: str = "") -> bool:
        """手工/程序化地标记一颗火种不健康（如刚吃了一个 401）。

        为什么不是"探测到才标记"：真实故障常常发生在**请求途中**（401/超时），
        那时我们已经有结论了，不该再花 3 秒去 GET /models 验证一遍才知道要兜底。
        """
        with self._lock:
            self._ensure_loaded()
            b = self._brains.get(str(name or "").strip())
            if b is None:
                return False
            b.health = {"ok": False, "status": None, "models": [], "elapsed_ms": 0,
                        "error": reason or "标记为不健康", "ts": _now()}
            return True

    def mark_healthy(self, name) -> bool:
        """把一颗火种标回健康（修好了 Key / 服务起来了）。不清健康记录，只翻 ok。"""
        with self._lock:
            self._ensure_loaded()
            b = self._brains.get(str(name or "").strip())
            if b is None:
                return False
            old = b.health if isinstance(b.health, dict) else {}
            b.health = {"ok": True, "status": old.get("status"), "models": old.get("models") or [],
                        "elapsed_ms": old.get("elapsed_ms", 0), "error": "", "ts": _now()}
            return True

    def health_check(self, all: bool = False, timeout: int = PROBE_TIMEOUT) -> dict:
        """逐个 probe，返回 {name: {ok,status,models,error,elapsed_ms}}。

        all=False（默认）只探当前火种 —— 界面上的"体检"按钮不该因为配了 20 颗火种就卡 60 秒。
        timeout 可传得很小（例如 1 秒）给"启动时快速巡一遍"用。
        """
        with self._lock:
            self._ensure_loaded()
            cur = self.current()
            targets = list(self._brains.values()) if all else ([cur] if cur else [])
        out = {}
        for b in targets:
            try:
                out[b.name] = b.probe(timeout=timeout)
            except Exception as e:      # noqa: silent-ok — probe 自身已兜异常，这里再保一层：体检绝不能抛
                out[b.name] = {"ok": False, "status": None, "models": [],
                               "error": "%s: %s" % (type(e).__name__, e), "elapsed_ms": 0}
        return out

    # ------------------------------------------------------------------ 应用到 app
    def apply_to_app(self, brain=None) -> bool:
        """把火种写进 `xiaojiao_app` 的全局变量（LLM_BASE / LLM_MODEL / LLM_KEY）。

        变量名**是读源码确认过的**（xiaojiao_app.py 里 `LLM_BASE`/`LLM_MODEL`/`LLM_KEY`），
        不是猜的：猜错就会把参数写到一个不存在的名字上，app 照样用旧火种，用户以为切换成功了。
        成功返回 True；app 不在 / 变量名对不上 → 记日志并返回 **False**，**绝不抛**。
        ① 为什么要"写进 app"而不另起一套调用栈：app 的 `_llm_post` 带着重试、熔断、超时降级，
           复用它 = 新火种自动获得全部可靠性，不用重写一遍（重写必然漏掉某些坑）。
        ② 为什么是改全局变量而不是"重启"：`_llm_targets()` 每次请求现读这三个名字，
           改完**下一条消息就生效** —— 这就是"热插拔、不重启"的落点。
        """
        b = brain if isinstance(brain, Brain) else self.current()
        if b is None:
            _append_jsonl(APPLY_LOG, {"ts": _now(), "brain": "", "ok": False,
                                      "error": "没有可用的火种"})
            logger.warning("apply_to_app：登记处里没有当前火种")
            return False
        tgt = b.to_target()
        base = tgt["url"][: -len("/chat/completions")] if tgt["url"].endswith("/chat/completions") \
            else b.base_url
        try:
            app = sys.modules.get("xiaojiao_app") or importlib.import_module("xiaojiao_app")
        except Exception as e:      # noqa: silent-ok — app 不在（独立脚本/别的进程）也要能返回 False
            _append_jsonl(APPLY_LOG, {"ts": _now(), "brain": b.name, "ok": False,
                                      "error": "import xiaojiao_app 失败：%s" % e})
            logger.warning("apply_to_app：xiaojiao_app 不可用（%s），本次不改任何东西", e)
            return False
        names = ("LLM_BASE", "LLM_MODEL", "LLM_KEY")
        if not any(hasattr(app, n) for n in names):
            _append_jsonl(APPLY_LOG, {"ts": _now(), "brain": b.name, "ok": False,
                                      "error": "app 里找不到 LLM_BASE/LLM_MODEL/LLM_KEY"})
            logger.warning("apply_to_app：变量名对不上，app 可能已改版，本次不改任何东西")
            return False
        try:
            if hasattr(app, "LLM_BASE"):
                app.LLM_BASE = base
            if hasattr(app, "LLM_MODEL"):
                app.LLM_MODEL = tgt["model"]
            if hasattr(app, "LLM_KEY"):
                app.LLM_KEY = b.api_key
        except Exception as e:      # noqa: silent-ok — 写全局失败只影响"生效"，返回 False 由调用方决定
            _append_jsonl(APPLY_LOG, {"ts": _now(), "brain": b.name, "ok": False, "error": str(e)})
            logger.warning("apply_to_app：写入失败 %s", e)
            return False
        _append_jsonl(APPLY_LOG, {"ts": _now(), "brain": b.name, "ok": True, "base_url": base,
                                  "model": tgt["model"], "local": tgt["local"],
                                  "key": "已设置" if b.api_key else ""})
        logger.info("火种已应用：%s → %s（model=%s）", b.name, base, tgt["model"])
        return True

    # ------------------------------------------------------------------ 快照
    def snapshot(self) -> dict:
        """当前状态一览（给界面 / 日志 / 自测看）。**不含明文 Key**。"""
        with self._lock:
            self._ensure_loaded()
            cur = self._brains.get(self._active)
            return {"ts": _now(), "active": self._active,
                    "active_ready": bool(cur and cur.health_ok()),
                    "count": len(self._brains), "brains": self.list_brains(),
                    "persist": "noop(内存，不写盘)" if self._persist_is_default else "callback",
                    "persist_pending": self._persist_pending,
                    "source": self._source, "switch_log": str(SWITCH_LOG)}
