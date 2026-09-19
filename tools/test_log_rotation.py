# -*- coding: utf-8 -*-
"""日志轮转自测（离线）：**别的进程占着日志文件时，轮转失败不许炸**。

【为什么必须钉】2026-09-19 实测：用户第二次 `python start_xiaojiao.py` 时，控制台连刷
  `--- Logging error ---` + `PermissionError: [WinError 32] 另一个程序正在使用此文件`，
  指向 `os.rename('logs/xiaojiao.log' → '.1')` —— 原因是**已经有一个小焦在跑**
  （Windows 不允许重命名被别的进程占用的文件），而 `logging` 默认的 `doRollover()`
  不处理这个异常 → **每写一条日志就抛一次**，堆栈糊在用户脸上、看起来像"启动报错"。

这里钉三件事：
  ① 文件没被占用时：**照常轮转**（`.1` 出现、新文件重新开始）；
  ② 文件被占用时：**不抛异常、不丢日志**（继续往原文件追加，并且只提示一次"轮转跳过"）；
  ③ ③ 之后还能继续正常写（**流被关掉过一次，必须自己重开** —— 否则就从"吵"变成"丢"）。

跑法：python tools/test_log_rotation.py（全用临时目录，**不碰真的 logs/xiaojiao.log**）
"""
import io
import logging
import os
import shutil
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from xiaojiao_log import _SafeRotatingFileHandler  # noqa: E402

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)[:150]) if info else ""))


def main():
    tmp = tempfile.mkdtemp(prefix="xj_logrot_")
    path = os.path.join(tmp, "xiaojiao.log")
    h = _SafeRotatingFileHandler(path, maxBytes=200, backupCount=2, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(message)s"))
    log = logging.getLogger("xjlogrot")
    log.setLevel(logging.INFO)
    log.propagate = False
    log.addHandler(h)
    try:
        print("一、没被占用时：照常轮转")
        for i in range(12):
            log.info("普通一行 %d（够长够长够长够长够长）", i)
        h.flush()
        ck("轮转出了一个 .1 备份", os.path.exists(path + ".1"),
           os.listdir(tmp))
        ck("轮转不算「跳过」", int(getattr(h, "_rotate_skipped", 0)) == 0,
           getattr(h, "_rotate_skipped", 0))

        print("\n二、别的进程占着这个文件时：不抛异常、日志继续写")
        io.open(path, "a", encoding="utf-8").close()
        holder = io.open(path, "a", encoding="utf-8")     # ← 模拟"另一个进程开着它"
        before = os.path.getsize(path)
        h._rotate_skipped = 0
        threw = ""
        try:
            for i in range(20):
                log.info("轮转被占时的一行 %d（够长够长够长够长够长够长）", i)
            h.flush()
        except Exception as e:      # noqa: silent-ok — 真抛出来了就是失败
            threw = repr(e)
        ck("**没有抛异常**（默认实现会抛 PermissionError 糊用户一脸）", not threw, threw)
        ck("记下了「这轮跳过了」", int(getattr(h, "_rotate_skipped", 0)) >= 1,
           getattr(h, "_rotate_skipped", 0))
        ck("**失败后退避**：不是每写一行就重试一次（20 行只试了 %d 次）"
           % int(getattr(h, "_rotate_skipped", 0)),
           1 <= int(getattr(h, "_rotate_skipped", 0)) <= 10, getattr(h, "_rotate_skipped", 0))
        after = os.path.getsize(path)
        ck("**日志一条没丢**（文件还在长）", after > before, "%d → %d" % (before, after))
        tail = io.open(path, encoding="utf-8", errors="replace").read()[-300:]
        ck("最后那几条真的写进去了", "轮转被占时的一行" in tail, tail[-60:])

        print("\n三、占用解除后：又能正常轮转（流没被永久弄坏）")
        holder.close()
        size_before = os.path.getsize(path)
        h._rotate_skipped = 0
        for i in range(12):
            log.info("解除占用后的一行 %d（够长够长够长够长够长够长）", i)
        h.flush()
        ck("又能轮转了（不再记「跳过」）", int(getattr(h, "_rotate_skipped", 0)) == 0,
           getattr(h, "_rotate_skipped", 0))
        ck("文件重新小了下来", os.path.getsize(path) < size_before,
           "%d → %d" % (size_before, os.path.getsize(path)))
    finally:
        try:
            log.removeHandler(h)
            h.close()
        except Exception:      # noqa: silent-ok
            pass
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 62)
    print("日志轮转自测：通过 %d / 共 %d%s"
          % (len(PASS), len(PASS) + len(FAIL), ("　失败：" + str(FAIL)) if FAIL else ""))
    print("=" * 62)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
