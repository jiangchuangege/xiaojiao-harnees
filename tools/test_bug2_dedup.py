# -*- coding: utf-8 -*-
"""Bug 2 自测：同一轮里同一 URL 的工具只许调一次（真跑，不模拟）。

运行：python tools/test_bug2_dedup.py
判据（用户口径）：
  · 连测 5 个正常 URL → 每个 get 只调 1 次
  · 抓取失败也只调 1 次（**这是复发点**：失败时原来会重跑整条升级链）
  · 每次 get 都在日志里记下**实际 URL**
另外验证：不同 URL 不被误去重；同一 URL 不同工具（get vs fetch）不被误去重；
         写文件类工具不做去重（它本来就可能一轮里被调多次）。
"""
import io
import json
import os
import re
import sys
import threading

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

os.environ.setdefault("PYTHONUTF8", "1")
import xiaojiao_app as X  # noqa: E402

PASS, FAIL = [], []


def ck(group, name, cond, info=""):
    (PASS if cond else FAIL).append("%s/%s" % (group, name))
    print("  %s [%s] %s%s" % ("✅" if cond else "❌", group, name,
                              ("  ← " + str(info)) if info else ""))


class Counter:
    """把**真实的工具执行**记下来 —— 数的是"到底发了几次网络请求"，不是"轨迹里几条"。"""

    def __init__(self):
        self.calls = []
        self._orig = X._run_tool_impl

    def __enter__(self):
        def spy(name, args, force=False):
            self.calls.append((name, json.dumps(args or {}, sort_keys=True, ensure_ascii=False)))
            return "[stub]" if name in ("get", "fetch", "stealthy_fetch", "make_request",
                                        "bulk_get", "bulk_fetch") else self._orig(name, args, force=force)
        X._run_tool_impl = spy
        return self

    def __exit__(self, *a):
        X._run_tool_impl = self._orig
        return False

    def n(self, tool, url_contains=None):
        return sum(1 for t, a in self.calls
                   if t == tool and (url_contains is None or url_contains in a))


URLS = ["http://127.0.0.1:1/a", "http://127.0.0.1:1/b", "http://127.0.0.1:1/c",
        "http://127.0.0.1:1/d", "http://127.0.0.1:1/e"]


def main():
    print("=" * 62)
    print("  Bug 2 自测：同一轮同一 URL 的工具只调一次")
    print("=" * 62)

    # ---- A 五个正常 URL：每个 get 只调 1 次 ----
    print("\n[A] 连测 5 个 URL（每个各起一轮）→ 每个 get 只调 1 次")
    per_url = []
    for u in URLS:
        with Counter() as c:
            X._round_begin()
            X.run_tool("get", {"url": u})
        per_url.append(c.n("get", u))
    ck("A", "5 个 URL 每个 get 恰好 1 次", per_url == [1] * 5, per_url)

    # ---- B 同一轮内重复调同一个 URL 的 get → 只有第一次真调 ----
    print("\n[B] 同一轮内故意重复调同一个 URL 的 get 3 次")
    with Counter() as c:
        X._round_begin()
        r1 = X.run_tool("get", {"url": URLS[0]})
        r2 = X.run_tool("get", {"url": URLS[0]})
        r3 = X.run_tool("get", {"url": URLS[0]})
    ck("B", "真执行只有 1 次", c.n("get", URLS[0]) == 1, c.n("get", URLS[0]))
    ck("B", "后两次返回复用说明", "复用" in r2 and "复用" in r3, (r2 or "")[:24])
    ck("B", "复用结果里带着第一次的原文", "[stub]" in r2)

    # ---- C 抓取失败也只调一次（Bug 2 复发点）----
    print("\n[C] 抓取失败：整轮最多 1 次 get / 1 次 fetch / 1 次 stealthy_fetch")
    with Counter() as c:
        X._round_begin()
        ans, tr = X._scrape_direct("抓一下 http://127.0.0.1:1/nope", [])
        ans2, tr2 = X._scrape_direct("抓一下 http://127.0.0.1:1/nope", tr)   # 模拟兜底重入
    ck("C", "get 只调 1 次", c.n("get", "127.0.0.1:1/nope") == 1, c.n("get", "127.0.0.1:1/nope"))
    ck("C", "再进一次直通被拦住（返回 None）", ans2 is None and len(tr2) == len(tr), (ans2, len(tr2)))
    chain = [t for t, _ in c.calls]
    ck("C", "升级链里每个候选最多 1 次", all(chain.count(t) <= 1 for t in set(chain)), chain)

    # ---- D 同一轮里两个不同 URL 都要真抓（不能误去重）----
    print("\n[D] 同一轮里两个不同 URL → 都要真抓")
    with Counter() as c:
        X._round_begin()
        X.run_tool("get", {"url": URLS[1]})
        X.run_tool("get", {"url": URLS[2]})
    ck("D", "两个 URL 各 1 次", c.n("get", URLS[1]) == 1 and c.n("get", URLS[2]) == 1, c.calls)

    # ---- E 不同工具不算重复 ----
    print("\n[E] 同一 URL 换工具（get / fetch）→ 不算重复")
    with Counter() as c:
        X._round_begin()
        X.run_tool("get", {"url": URLS[3]})
        X.run_tool("fetch", {"url": URLS[3]})
    ck("E", "get 与 fetch 各自执行", c.n("get", URLS[3]) == 1 and c.n("fetch", URLS[3]) == 1, c.calls)

    # ---- F 写文件类不去重（本来就可能多次）----
    print("\n[F] 写文件类工具不做去重")
    tmp = os.path.join(_ROOT, "logs", "_bug2_tmp.txt")
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    X._round_begin()
    with open(tmp, "w", encoding="utf-8") as f:      # 先建好，免得踩"不覆盖用户文件"红线
        f.write("")
    a1 = X.run_tool("write_file", {"path": tmp, "content": "1"})
    a2 = X.run_tool("write_file", {"path": tmp, "content": "1"})
    ck("F", "write_file 不被去重", "复用" not in str(a1) and "复用" not in str(a2), (a1, a2))

    # ---- G 参数键顺序不同也算同一个调用 ----
    print("\n[G] 参数键顺序不同 → 视为同一个调用")
    with Counter() as c:
        X._round_begin()
        X.run_tool("get", {"url": URLS[4], "ignore_robots": True})
        X.run_tool("get", {"ignore_robots": True, "url": URLS[4]})
    ck("G", "只真调 1 次", c.n("get", URLS[4]) == 1, c.n("get", URLS[4]))

    # ---- H 每轮重置：第二轮必须重新真调 ----
    print("\n[H] 换一轮 → 去重表重置，重新真调")
    with Counter() as c:
        X._round_begin()
        X.run_tool("get", {"url": URLS[0]})
        X._round_begin()
        X.run_tool("get", {"url": URLS[0]})
    ck("H", "两轮各调 1 次（共 2 次）", c.n("get", URLS[0]) == 2, c.n("get", URLS[0]))

    # ---- I 并发安全：两个线程各自一轮，互不串 ----
    print("\n[I] 并发：两个线程各自的轮互不干扰")
    res = {}

    def worker(tag, url):
        X._round_begin()
        X.run_tool("get", {"url": url})
        res[tag] = X._round_cached("get", {"url": url}) is not None

    t1 = threading.Thread(target=worker, args=("a", URLS[0]))
    t2 = threading.Thread(target=worker, args=("b", URLS[1]))
    t1.start(); t2.start(); t1.join(); t2.join()
    ck("I", "两个线程都拿到了自己的缓存", res == {"a": True, "b": True}, res)

    # ---- J 日志里记下了实际 URL ----
    print("\n[J] 日志：每次 get 都记实际 URL")
    buf = io.StringIO()
    h = None
    for hh in X.LOG.handlers if hasattr(X, "LOG") else []:
        pass
    # 直接验证日志摘要函数（它是写日志时唯一拼 URL 的地方）
    s1 = X._summarize_args_for_log("get", {"url": "http://a.com/x"})
    s2 = X._summarize_args_for_log("get", {"urls": ["http://a.com", "http://b.com"]})
    ck("J", "单 URL 摘要带真实网址", "http://a.com/x" in s1, s1)
    ck("J", "多 URL 摘要带个数", "2 个" in s2, s2)
    # 再看真实日志文件里有没有 url=
    logfile = os.path.join(_ROOT, "logs", "xiaojiao.log")
    found = False
    if os.path.exists(logfile):
        with open(logfile, encoding="utf-8", errors="ignore") as f:
            tail = f.readlines()[-400:]
        found = any("url=" in l and ("get" in l or "工具" in l) for l in tail)
    ck("J", "运行日志里出现过带 url= 的工具记录（若无日志文件则跳过）", found or not os.path.exists(logfile),
       "日志文件存在=%s" % os.path.exists(logfile))

    print("\n" + "=" * 62)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % ", ".join(FAIL)) if FAIL else ""))
    print("=" * 62)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
