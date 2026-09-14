# -*- coding: utf-8 -*-
"""Bug 6 复验：画完自动打开 HTML（真跑，不模拟）。

运行：python tools/test_bug6_open_html.py
上一轮已修 `_open_delivered_html()`，本轮按用户要求复验 4/4：
  ① 带空格的路径能抠出来并触发打开；
  ② 文件不存在时不崩、给出可手动打开的路径；
  ③ 结果里没有路径时安静返回空串（不弹、不报）；
  ④ 打开动作在**后台 daemon 线程**里做（不拖住对话返回）。
"""
import os
import re
import sys
import tempfile
import threading
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import xiaojiao_app as X  # noqa: E402

PASS, FAIL = [], []


def ck(group, name, cond, info=""):
    (PASS if cond else FAIL).append("%s/%s" % (group, name))
    print("  %s [%s] %s%s" % ("✅" if cond else "❌", group, name,
                              ("  ← " + str(info)) if info else ""))


def main():
    print("=" * 62)
    print("  Bug 6 复验：画完自动打开 HTML")
    print("=" * 62)

    opened = []
    # 拦掉真的启动浏览器：把 os.startfile 换成一个记录器（其余逻辑全走真的）
    real_startfile = getattr(os, "startfile", None)
    _has = hasattr(os, "startfile")
    if _has:
        os.startfile = lambda p: opened.append(p)

    try:
        # ---- ① 带空格的路径 ----
        print("\n[①] 带空格的路径能抠出并触发打开")
        d = tempfile.mkdtemp(prefix="xj open html ")          # 目录名里带空格
        fp = os.path.join(d, "架构图 demo.html")
        with open(fp, "w", encoding="utf-8") as f:
            f.write("<html><body>图</body></html>")
        res = "已交付：\n%s\n（大小 632KB）" % fp
        note = X._open_delivered_html(res)
        time.sleep(0.4)                                        # 后台线程要时间
        ck("①", "识别到带空格的完整路径", fp in note, note[:60])
        ck("①", "真的触发了打开", opened == [fp], opened)
        ck("①", "提示里给了可手动打开的路径", "已自动打开" in note and fp in note)

        # ---- ② 文件不存在 ----
        print("\n[②] 文件不存在时不崩，给出可手动打开的路径")
        opened.clear()
        ghost = os.path.join(d, "不存在的 图.html")
        note2 = X._open_delivered_html("交付到：%s" % ghost)
        time.sleep(0.3)
        ck("②", "没有抛异常（拿到的是字符串）", isinstance(note2, str))
        ck("②", "没有触发打开", opened == [], opened)
        ck("②", "如实告诉用户没找到文件、可手动打开", "没找到" in note2 and ghost in note2, note2[:70])

        # ---- ③ 结果里没有路径 ----
        print("\n[③] 结果里没有路径 → 安静返回空串")
        ck("③", "无路径时返回空串", X._open_delivered_html("本次没有交付任何文件") == "",
           repr(X._open_delivered_html("本次没有交付任何文件")))
        ck("③", "空输入也不崩", X._open_delivered_html("") == "" and X._open_delivered_html(None) == "")

        # ---- ④ 后台非阻塞 ----
        print("\n[④] 打开动作在后台，不拖住返回")
        opened.clear()
        done = {}

        def slow_open(p):
            time.sleep(1.5)
            opened.append(p)
            done["ok"] = True
        os.startfile = slow_open
        fp2 = os.path.join(d, "慢打开.html")
        with open(fp2, "w", encoding="utf-8") as f:
            f.write("<html></html>")
        t0 = time.time()
        X._open_delivered_html("交付：%s" % fp2)
        el = time.time() - t0
        ck("④", "调用立刻返回（<0.3s，没有被 1.5s 的打开动作阻塞）", el < 0.3, "%.3fs" % el)
        ck("④", "打开动作确实在别的线程里跑", any(t.name != "MainThread" for t in threading.enumerate()),
           [t.name for t in threading.enumerate()][:6])
        ck("④", "后台线程是 daemon（进程退出不会被它拖住）",
           all(t.daemon for t in threading.enumerate() if t.name != "MainThread"))
        time.sleep(1.8)
        ck("④", "1.8s 后打开动作确实完成了", opened == [fp2], opened)
    finally:
        if real_startfile is not None:
            os.startfile = real_startfile

    print("\n" + "=" * 62)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % ", ".join(FAIL)) if FAIL else ""))
    print("=" * 62)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
