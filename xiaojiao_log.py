# -*- coding: utf-8 -*-
"""小焦 · 统一日志

用法：
    from xiaojiao_log import get_logger
    log = get_logger(__name__)

设计要点：
  · **库/插件代码只写日志，不 print**；交互式脚本（安装向导、启动横幅）仍可用 print 输出给用户看
  · 日志文件统一放 logs/（已被 .gitignore 忽略），按大小轮转，避免涨到 GB
  · 关键：**写日志前一律脱敏**（API Key / Token / Cookie / 裸凭据），防止密钥进日志
  · 环境变量 XIAOJIAO_LOG_LEVEL 可调级别（默认 INFO；调试用 DEBUG）
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import re
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
_LOG_DIR = os.path.join(_ROOT, "logs")
_configured = False

# 与 plugins/scrapling_bridge.py 的脱敏规则保持一致（裸凭据 + 键值对）
_SECRET_PATTERNS = [
    re.compile(r"(?i)(authorization\s*[:=]\s*)(\S+)"),
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)(\S+)"),
    re.compile(r"(?i)(token\s*[:=]\s*)(\S+)"),
    re.compile(r"(?i)(cookie\s*[:=]\s*)(\S+)"),
    re.compile(r"(?i)(bearer\s+)(\S+)"),
    re.compile(r"(?i)(password\s*[:=]\s*)(\S+)"),
    re.compile(r"(sk-[A-Za-z0-9_\-]{12,})"),
    re.compile(r"(gh[pousr]_[A-Za-z0-9]{16,})"),
    re.compile(r"(AKIA[0-9A-Z]{12,})"),
    re.compile(r"(xox[baprs]-[A-Za-z0-9\-]{10,})"),
    re.compile(r"(eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{6,})"),
]


def scrub(text) -> str:
    """日志脱敏：抹掉密钥/令牌/Cookie（键值对保留键名，裸凭据整串打码）。"""
    s = str(text)
    for pat in _SECRET_PATTERNS:
        try:
            s = pat.sub(lambda m: m.group(1) + "***", s) if pat.groups >= 2 else pat.sub("***", s)
        except Exception:  # noqa: silent-ok — 脱敏正则本身出错时保持原文，绝不能因日志而中断业务
            continue
    return s


class _ScrubFilter(logging.Filter):
    """写盘/输出前统一脱敏，任何地方漏打码都不会泄露。

    真实缺陷复盘：这里原来是 `record.args = tuple(scrub(a) for a in record.args)`，
    等于把**每个参数都转成字符串**——于是所有用 %d / %.0f 写日志的地方在 emit 时抛
    `TypeError: %d format: a real number is required, not str`，日志直接变成
    "--- Logging error ---" 堆栈（熔断告警就是这么被打掉的）。
    现在改为：先把消息**渲染成最终文本**再脱敏，并清空 args —— 既不破坏格式，
    也保证"渲染前脱敏"的初衷（脱敏的是最终要写出去的那串字）。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if record.args:
                record.msg = scrub(record.getMessage())
                record.args = ()
            else:
                record.msg = scrub(record.msg)
        except Exception:  # noqa: silent-ok — 日志过滤器必须永不抛错，否则会吃掉业务日志
            pass
        return True


class _SafeRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """Windows 上**别的进程正占着日志文件**时，轮转失败不许炸（实测就炸过）。

    【实测现场（2026-09-19）】`python start_xiaojiao.py` 一启动，控制台连刷三段
    `--- Logging error ---` + `PermissionError: [WinError 32] 另一个程序正在使用此文件`，
    指向 `os.rename('logs/xiaojiao.log' → 'logs/xiaojiao.log.1')`。
    原因不是配置错，而是**已经有一个小焦在跑**（也可能是个编辑器 / `tail -f` 开着那文件）——
    Windows 不允许重命名**被别的进程占用**的文件。而 `logging` 默认的 `doRollover()`
    不处理这个异常 → **每写一条日志就抛一次**、堆栈直接糊在用户脸上，
    看起来像"启动报错"，其实业务一点没受影响。

    【改法】**把轮转做成可失败的**：失败就**不轮转、继续往原文件追加** ——
    一条日志都不丢，只是这一轮不叫"轮转"（文件涨到那个进程退出后自然会轮）。
    并且 `rotate` 抛异常时流已经被关掉了，**必须自己把流重新打开**，否则后面每条日志
    都会变成 "I/O operation on closed file"（那就从"吵"变成"丢"了）。
    """

    def shouldRollover(self, record):      # noqa: D102
        # 【失败后退避】被占着的时候，`shouldRollover` 会**每写一行都返回 True** →
        #   每行都去敲一次重命名（还要抛一次异常）。所以失败之后记一个"涨到多少再试"，
        #   没涨到就先老实追加 —— 日志一条不丢，代价也不再是"每行一次系统调用"。
        nxt = int(getattr(self, "_retry_after_bytes", 0) or 0)
        if nxt:
            try:
                if os.path.getsize(self.baseFilename) < nxt:
                    return False
            except OSError:      # noqa: silent-ok — 量不出来就按标准逻辑走
                pass
            self._retry_after_bytes = 0
        return logging.handlers.RotatingFileHandler.shouldRollover(self, record)

    def doRollover(self):      # noqa: D102 — 覆盖标准库实现，语义见类注释
        try:
            return logging.handlers.RotatingFileHandler.doRollover(self)
        except OSError as e:
            self._rotate_skipped = int(getattr(self, "_rotate_skipped", 0)) + 1
            try:
                self._retry_after_bytes = os.path.getsize(self.baseFilename) + int(self.maxBytes)
            except OSError:      # noqa: silent-ok
                self._retry_after_bytes = 0
            try:
                if self.stream is None and not self.delay:
                    self.stream = self._open()        # ← 关键：不重开就等于把日志丢了
            except Exception:      # noqa: silent-ok — 都打不开了也不许再抛
                pass
            if self._rotate_skipped == 1:             # 只说一次，别每条日志来一遍
                try:
                    sys.stderr.write(
                        "[xiaojiao_log] 日志轮转跳过（%s）。常见原因：**已经有一个小焦在跑**，"
                        "或这个日志文件正被别的程序打开 —— 日志会继续写进同一个文件"
                        "（涨到 %s 字节再试一次），业务不受影响；想轮转先关掉那个进程。\n"
                        % (type(e).__name__, self._retry_after_bytes))
                except Exception:      # noqa: silent-ok
                    pass
            return None


def setup(level: str = "") -> None:
    """初始化根日志（幂等）：控制台 + logs/xiaojiao.log（5MB × 3 轮转）。"""
    global _configured
    if _configured:
        return
    _configured = True
    lvl = (level or os.environ.get("XIAOJIAO_LOG_LEVEL") or "INFO").upper()
    root = logging.getLogger("xiaojiao")
    root.setLevel(getattr(logging, lvl, logging.INFO))
    root.propagate = False
    fmt = logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    flt = _ScrubFilter()

    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        fh = _SafeRotatingFileHandler(
            os.path.join(_LOG_DIR, "xiaojiao.log"), maxBytes=5 * 1024 * 1024,
            backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        fh.addFilter(flt)
        root.addHandler(fh)
    except OSError:  # noqa: silent-ok — 日志目录不可写时不影响主流程
        pass

    if os.environ.get("XIAOJIAO_LOG_CONSOLE", "1") == "1":
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        sh.addFilter(flt)
        root.addHandler(sh)


def get_logger(name: str = "xiaojiao") -> logging.Logger:
    """取一个已配置好的 logger（首次调用自动初始化）。"""
    setup()
    if name in ("__main__", ""):
        name = "xiaojiao"
    elif not name.startswith("xiaojiao."):
        if name.startswith("xiaojiao"):
            # **真实缺陷**：主程序模块名是 `xiaojiao_app`，它以 "xiaojiao" 开头却**不在
            # `xiaojiao` 这个 logger 的层级里**，于是它的记录全落到真·root logger，
            # 只被 logging.lastResort 打到控制台（INFO 静默丢弃、文件里一条都没有）。
            # 结果：小焦自己的日志（含"大脑调用失败"这种关键告警）从来没进 logs/xiaojiao.log。
            name = "xiaojiao." + name
        else:
            name = "xiaojiao." + name.split(".")[-1]
    return logging.getLogger(name)
