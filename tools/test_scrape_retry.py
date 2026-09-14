# -*- coding: utf-8 -*-
"""问题 4 回归测试：『忽略 robots 抓一次』必须真的去抓。

运行：python tools/test_scrape_retry.py

用户实测：
  ① "抓 http://www.baidu.com的uuid" → 正确被 robots 拦下（这条没错）
  ② 按提示说"忽略 robots 抓一次" → **无工具轨迹**，直接返回编造的 JSON + 一张
     跟 baidu 毫无关系的 NVD CVE 表格
  ③ 用户看不出来那是编的

本测试证明三件事：
  A. 那句话现在会被识别成"重试 + 授权"，并且**真的调了 get**（带 ignore_robots）；
  B. 网址来自**载体记住的上一次失败**，不是模型编的（一个字符都不差）；
  C. 抓回来的东西必须带目标特征，否则如实标注"可能幻觉"，绝不假装抓到了。
"""
import json
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import xiaojiao_app as X  # noqa: E402

PASS, FAIL = [], []
URL = "http://www.baidu.com/s?wd=uuid"
ROBOTS_ERR = ("robots.txt 明确禁止抓取 www.baidu.com 的这个地址 —— 若你确认有权抓取，"
              "可在 xiaojiao_control.json 的 scrapling 段设 allow_robots_skip=true，"
              "或直接说「忽略 robots 抓一次」")


def ck(group, name, cond, info=""):
    (PASS if cond else FAIL).append("%s/%s" % (group, name))
    print("  %s [%s] %s%s" % ("✅" if cond else "❌", group, name,
                              ("  ← " + str(info)) if info else ""))


class Spy:
    """记录**真实调用**：数的是"工具到底有没有被调、参数是什么"。"""

    def __init__(self, ret):
        self.calls = []
        self.ret = ret

    def __enter__(self):
        self._orig = X._run_tool_impl
        outer = self

        def spy(name, args, force=False):
            outer.calls.append((name, dict(args or {})))
            if name in ("get", "fetch", "stealthy_fetch", "make_request"):
                r = outer.ret
                return r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)
            return outer._orig(name, args, force=force)
        X._run_tool_impl = spy
        return self

    def __exit__(self, *a):
        X._run_tool_impl = self._orig
        return False


def _reset():
    X._LAST_SCRAPE.update({"url": "", "error": "", "at": 0.0, "tool": "", "robots": False})
    X._round_begin()


def main():
    print("=" * 66)
    print("  问题 4 回归：忽略 robots 抓一次 → 必须真去抓")
    print("=" * 66)

    # ===== A 上一次被 robots 拦下 → 载体记住了 =====
    print("\n[A] 第一次抓取被 robots 拦下 → 载体记住网址与原因")
    _reset()
    with Spy({"status": 0, "url": URL, "content": "", "error": ROBOTS_ERR}) as s:
        ans1, tr1 = X._scrape_direct("抓一下 %s" % URL, [])
    ck("A", "第一次确实调了工具", any(c[0] == "get" for c in s.calls), [c[0] for c in s.calls])
    ck("A", "结果如实说抓取失败", "抓取失败" in (ans1 or ""), (ans1 or "")[:50])
    ck("A", "载体记住了这个网址", X._LAST_SCRAPE.get("url") == URL, X._LAST_SCRAPE.get("url"))
    ck("A", "并认出这是 robots 拦截", X._LAST_SCRAPE.get("robots") is True)
    ck("A", "轨迹里有记录（不是空轨迹）", bool(tr1), [t.get("tool") for t in tr1])

    # ===== B "忽略 robots 抓一次" → 强制重抓 =====
    print("\n[B] 『忽略 robots 抓一次』→ 识别为重试+授权，强制调 get")
    intent = X._scrape_retry_intent("忽略 robots 抓一次")
    ck("B", "识别出重试意图", intent is not None, intent)
    ck("B", "用的是**载体记住的**那个网址（不是模型编的）",
       intent and intent[1].get("url") == URL, intent[1].get("url") if intent else None)
    ck("B", "带上了 ignore_robots=true", bool(intent and intent[1].get("ignore_robots")), intent)
    for phrase in ("跳过 robots", "无视 robots", "我确认有权抓取", "再抓一次", "重试一下"):
        ck("B", "识别『%s』" % phrase, X._scrape_retry_intent(phrase) is not None)
    ck("B", "跟抓取无关的话不会被误判", X._scrape_retry_intent("今天天气不错") is None)
    ck("B", "没有失败记忆时不硬猜网址",
       (X._LAST_SCRAPE.update({"url": "", "at": 0.0}),
        X._scrape_retry_intent("忽略 robots 抓一次"))[1] is None)

    # ===== C 端到端：agent_run 里真的走了这条路（模型前面的直通）=====
    print("\n[C] 端到端 · agent_run 里这句话必须真调工具、不许交给模型编")
    _reset()
    _orig = X._LAST_SCRAPE.copy()
    X._LAST_SCRAPE.update({"url": URL, "error": ROBOTS_ERR, "at": time.time(),
                          "tool": "get", "robots": True})
    page = ("<html><head><title>UUID 查询 - 百度 www.baidu.com</title></head><body>"
            "这里是 www.baidu.com 的一个 uuid 生成与查询的页面，可以生成 v4 uuid。</body></html>")
    with Spy({"status": 200, "url": URL, "content": page, "error": ""}) as s:
        X._round_begin()
        ans, online, info, need, tr = X.agent_run("忽略 robots 抓一次")
    ck("C", "真的调了 get（不是交给模型）", any(c[0] == "get" for c in s.calls),
       [c[0] for c in s.calls])
    got = [c for c in s.calls if c[0] == "get"]
    ck("C", "调用参数里带 ignore_robots=true", bool(got and got[0][1].get("ignore_robots")),
       got[0][1] if got else None)
    ck("C", "抓的是**上一次那个网址**", bool(got and got[0][1].get("url") == URL),
       got[0][1].get("url") if got else None)
    ck("C", "**工具轨迹不为空**（用户能看到真调过工具）", bool(tr), [t.get("tool") for t in tr])
    ck("C", "回答里是抓回来的真内容", "uuid" in (ans or "").lower(), (ans or "")[:60].replace("\n", " "))
    ck("C", "抓成之后记忆被清掉（不会一直重抓）", not X._LAST_SCRAPE.get("url"),
       X._LAST_SCRAPE.get("url"))

    # ===== D 结果校验：抓到的东西必须带目标特征 =====
    print("\n[D] 结果校验 · 抓回来的必须像目标本身，否则标『可能幻觉』")
    _reset()
    # 返回一个跟目标毫无关系的页面（模拟风控页/缓存错页）
    with Spy({"status": 200, "url": URL, "content": "<html><body>Access Denied 403</body></html>",
              "error": ""}):
        X._round_begin()
        ans2, tr2 = X._scrape_direct("抓一下 %s" % URL, [])
    ck("D", "内容跟目标对不上时如实标注",
       ("可能幻觉" in (ans2 or "")) or ("⚠️" in (ans2 or "")), (ans2 or "")[:70].replace("\n", " "))
    ck("D", "轨迹里也留了 suspect 标记",
       any(t.get("suspect") for t in (tr2 or [])), [t.get("suspect") for t in (tr2 or [])])
    # 正常页面不该被标注
    _reset()
    with Spy({"status": 200, "url": URL,
              "content": "<html><head><title>UUID 查询 - 百度</title></head>"
                         "<body>百度 uuid 查询页 www.baidu.com</body></html>", "error": ""}):
        X._round_begin()
        ans3, tr3 = X._scrape_direct("抓一下 %s" % URL, [])
    ck("D", "正常页面不被误标", "可能幻觉" not in (ans3 or ""), (ans3 or "")[:60].replace("\n", " "))

    print("\n" + "=" * 66)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % ", ".join(FAIL)) if FAIL else ""))
    print("=" * 66)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
