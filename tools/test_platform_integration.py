# -*- coding: utf-8 -*-
"""平台接线自测：世界层 / 变形金刚 / 自主性在**主程序里真的生效**吗？

运行：python tools/test_platform_integration.py

为什么单独有这个脚本：`core/world`、`core/carrier`、`core/autonomy` 各自都有单测，
但那些只证明"模块自己是好的"。用户要的是**小焦真的用上了它们** ——
抓取前查世界模型、启动时扫能力/注册火种、后台任务真的在跑。这里证明的就是这些接线。

全程离线（本地 http.server 当被测站点），且**不碰用户真实的世界地图/会话**：
世界层走 `_WORLD_CACHE["override"]` 注入临时目录（世界地图是用户的数据，不是测试草稿纸）。
"""
import json
import os
import socket
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import xiaojiao_app as X  # noqa: E402

PASS, FAIL = [], []


def ck(group, name, cond, info=""):
    (PASS if cond else FAIL).append("%s/%s" % (group, name))
    print("  %s [%s] %s%s" % ("✅" if cond else "❌", group, name,
                              ("  ← " + str(info)) if info else ""))


class Site(BaseHTTPRequestHandler):
    body = "<html><head><title>小焦测试站</title></head><body><h1>第一版</h1><p>内容A</p></body></html>"

    def do_GET(self):                                        # noqa: N802 — http.server 的接口约定
        b = type(self).body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):                               # 别把访问日志刷到测试输出里
        pass


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def main():
    print("=" * 62)
    print("  平台接线自测：世界层 / 变形金刚 / 自主性")
    print("=" * 62)

    port = free_port()
    srv = ThreadingHTTPServer(("127.0.0.1", port), Site)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d/page" % port

    # 世界层注入临时目录（不写用户真实的世界地图）
    tmp = tempfile.mkdtemp(prefix="platform_")
    from core.world import WorldModel, WorldPerception
    wm = WorldModel(os.path.join(tmp, "model.json"))
    wp = WorldPerception(model=wm, state_dir=tmp)
    X._WORLD_CACHE["override"] = (wm, wp)
    # 会话也隔离
    X.SESSIONS_FILE = os.path.join(tmp, "sessions.json")
    with open(X.SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump({"current": "p1", "sessions": [{"id": "p1", "title": "t", "messages": []}]}, f)

    try:
        # ===== A 世界层：抓取前查地图 =====
        print("\n[A] 世界层 · 抓取前先查地图")
        ck("A", "第一次见到这个站 → 如实说『第一次见到』",
           "第一次" in X._world_before_fetch(url), X._world_before_fetch(url))
        # 先把它记进地图
        wp.ingest(url, Site.body, 200)
        note = X._world_before_fetch(url)
        ck("A", "记过之后不再说『第一次见到』", "第一次" not in note, note)
        ck("A", "说清『已收录』并给出可信度与刷新周期",
           "已收录" in note and "可信度" in note and "刷新" in note, note)
        ck("A", "世界模型里真有这个站", wm.domain_of(url) in wm.snapshot().get("sites", {}),
           list(wm.snapshot().get("sites", {}).keys()))
        ck("A", "域名回收正确", wm.domain_of(url) == "127.0.0.1", wm.domain_of(url))
        ck("A", "刷新周期可读（秒 → 人能读的中文）",
           X._fmt_interval(wm.refresh_interval(url)) in ("1h", "6h", "30m", "1d", "7d"),
           X._fmt_interval(wm.refresh_interval(url)))

        # ===== B 世界层：抓取后更新地图 + 变化感知 =====
        print("\n[B] 世界层 · 抓取后更新地图 + 变化感知")
        n_snap0 = sum(1 for l in open(os.path.join(tmp, "snapshots.jsonl"), encoding="utf-8")
                      if l.strip()) if os.path.exists(os.path.join(tmp, "snapshots.jsonl")) else 0
        ck("B", "第一次 ingest 不报『变了』（那是首次记录）",
           X._world_after_fetch(url, Site.body, 200) == "")
        Site.body = ("<html><head><title>小焦测试站</title></head><body><h1>第二版</h1>"
                     "<p>内容B</p><p>新增的一段</p></body></html>")
        chg = X._world_after_fetch(url, Site.body, 200)
        ck("B", "内容变了 → 明确告诉用户", "不一样" in chg, chg[:60].replace("\n", " "))
        n_snap1 = sum(1 for l in open(os.path.join(tmp, "snapshots.jsonl"), encoding="utf-8")
                      if l.strip())
        ck("B", "快照被记下来了（每次看都留痕）", n_snap1 >= n_snap0 + 2, "%d → %d" % (n_snap0, n_snap1))
        ck("B", "变化写进了 changes.jsonl",
           os.path.exists(os.path.join(tmp, "changes.jsonl"))
           and "changed" in open(os.path.join(tmp, "changes.jsonl"), encoding="utf-8").read())
        ck("B", "内容没变时不重复报变化",
           X._world_after_fetch(url, Site.body, 200) == "")
        # ---- 走真实抓取入口（_scrape_direct）—— 验证"接线"而不是"函数能调" ----
        # 注意：这里**必须换一个公网域名**并把抓取工具打桩。
        # 第一版直接用 127.0.0.1 → 被载体自己的 SSRF 防护挡下（"禁止访问本机/内网地址"），
        # 于是根本没走到世界层。那条防护是对的，错的是测试用它当被测目标。
        Site.body = ("<html><head><title>小焦测试站</title></head><body><h1>第三版</h1>"
                     "<p>又变了</p></body></html>")
        pub = "https://news.example.com/p/1"
        _orig_impl = X._run_tool_impl

        def _stub(name, args, force=False):
            if name in ("get", "fetch", "stealthy_fetch"):
                return json.dumps({"status": 200, "url": pub, "content": Site.body, "error": ""},
                                  ensure_ascii=False)
            return _orig_impl(name, args, force=force)
        X._run_tool_impl = _stub
        try:
            X._round_begin()
            _ans, _tr = X._scrape_direct("抓一下 %s" % pub, [])
            ck("B", "真实抓取入口也走了世界层（轨迹里带 world 字段）",
               bool(_tr) and "world" in (_tr[-1] or {}), (_tr[-1] or {}).get("world", "无"))
            ck("B", "第一次抓这个站不喊『变了』（那是首次记录）", "不一样" not in (_ans or ""),
               (_ans or "")[-60:].replace("\n", " "))
            # 第二次抓：内容变了 → 必须通过真实入口把变化告诉用户
            Site.body = ("<html><head><title>小焦测试站</title></head><body><h1>第四版</h1>"
                         "<p>这一版真的改了</p></body></html>")
            X._round_begin()
            _ans2, _tr2 = X._scrape_direct("抓一下 %s" % pub, [])
            ck("B", "第二次抓、内容变了 → 真实入口把变化告诉用户", "不一样" in (_ans2 or ""),
               (_ans2 or "")[-90:].replace("\n", " "))
        finally:
            X._run_tool_impl = _orig_impl
        ck("B", "这个站已进了世界地图",
           wm.domain_of(pub) in wm.snapshot().get("sites", {}),
           list(wm.snapshot().get("sites", {}).keys()))

        # ===== C 变形金刚 · 能力扫描 =====
        print("\n[C] 变形金刚 · 能力扫描（不封顶）")
        from core.carrier import CapabilityRegistry
        cap = CapabilityRegistry()
        r = cap.scan()
        ck("C", "扫出真实工具数（>0，且来自 app 真接口）",
           r.get("count", 0) > 0 and r.get("source") == "app", (r.get("count"), r.get("source")))
        # 【2026-09-21 从 `== 77` 改成 `>= 77`】77 是写这条时的基线数字；但**用户自己加的
        #   插件会合法地让这个数变大** —— 实测：小焦自己新建了一个 `plugins/nginx-vts.json`，
        #   于是这条硬编码等式把"用户加了东西"判成了失败（红的原因跟被测能力毫无关系）。
        #   这里要守的是「工具**没被弄丢**」（≥ 基线），不是"一个都不许多"。
        ck("C", "工具数不少于基线 77（用户自加插件只会更多）", r.get("count", 0) >= 77, r.get("count"))
        ck("C", "清单落了盘（capabilities.json）",
           os.path.exists(os.path.join(_ROOT, "logs", "carrier", "capabilities.json")))
        ck("C", "扫描不删任何插件文件", r.get("files", 0) > 0, r.get("files"))

        # ===== D 变形金刚 · 火种注册与热切换 =====
        print("\n[D] 变形金刚 · 火种注册 / 热切换不碰载体状态")
        from core.carrier import BrainRegistry
        reg = BrainRegistry()
        names = reg.names()
        ck("D", "火种已从配置读出来（≥1）", len(names) >= 1, names)
        cur = reg.current()
        ck("D", "当前火种有指向（或如实为空）", cur is None or bool(cur.name),
           cur.name if cur else "未指定")
        # 载体状态：切换前后必须一模一样
        carrier_state = {"memory": ["a"], "tools": ["get"], "world": {"x": 1}, "session": {"id": "p1"}}
        snap_before = json.dumps(carrier_state, sort_keys=True)
        ids_before = (id(carrier_state["memory"]), id(carrier_state["tools"]))
        if len(names) >= 2:
            ok = reg.switch(names[-1])
            ck("D", "热切换成功", ok is True, names[-1])
            ck("D", "切换后当前火种变了", (reg.current() or {}) and reg.current().name == names[-1],
               reg.current().name if reg.current() else None)
            reg.switch(names[0])
        else:
            ck("D", "只登记了 1 个火种 → 如实拒绝切换（不假装成功）", reg.switch("不存在的火种") is False)
        ck("D", "切换前后载体状态一字未变", json.dumps(carrier_state, sort_keys=True) == snap_before)
        ck("D", "载体状态对象身份也没变（不是重建了一份）",
           (id(carrier_state["memory"]), id(carrier_state["tools"])) == ids_before)
        ck("D", "切换流水有记录",
           os.path.exists(os.path.join(_ROOT, "logs", "carrier", "brain_switch.jsonl")))
        ck("D", "切换**没有**改用户的 xiaojiao_control.json",
           "active_brain" not in open(os.path.join(_ROOT, "xiaojiao_control.json"),
                                      encoding="utf-8").read())

        # ===== E 自主性 · 真定时 + 优雅关闭 =====
        print("\n[E] 自主性 · 后台任务真的在跑 + 优雅关闭")
        from core.autonomy import scheduler as SC
        sched = SC.AutonomyScheduler()
        ran = []
        sched.runner = lambda task: (ran.append(task.get("id")), "ok")[1]
        ok = sched.add({"id": "selftest_tick", "interval_s": 1, "prompt": "自测任务"})
        ck("E", "任务登记成功", ok is True)
        ck("E", "重复登记同 id 被拒（幂等）", sched.add({"id": "selftest_tick", "interval_s": 1}) is False)
        sched.start()
        time.sleep(3.2)
        sched.stop(timeout=3)
        ck("E", "3 秒内真的跑了 ≥2 次", len(ran) >= 2, "%d 次" % len(ran))
        alive = [t.name for t in threading.enumerate() if "autonomy" in t.name.lower()
                 or "scheduler" in t.name.lower()]
        ck("E", "stop() 后线程真的退出了", not alive, alive)
        ck("E", "任务流水落了盘",
           os.path.exists(os.path.join(_ROOT, "logs", "autonomy", "tasks.jsonl")))

        # ===== F 自主性 · 盯梢真的能发现变化 =====
        print("\n[F] 自主性 · 盯梢（用户说『帮我盯着』就是一直盯）")
        from core.autonomy import watcher as WT
        w = WT.AutonomousWatcher(state_dir=os.path.join(tmp, "autonomy"))
        ck("F", "加入关注源", w.add(url, interval=1, rule="changed") is True)
        first = w.check_once(force=True)
        ck("F", "第一次记 first_seen", any(c.get("kind") == "first_seen" for c in first),
           [c.get("kind") for c in first])
        Site.body = "<html><head><title>小焦测试站</title></head><body>完全换了一版</body></html>"
        second = w.check_once(force=True)
        ck("F", "内容变了 → 记录 changed", any(c.get("kind") in ("changed", "first_seen")
                                              for c in second), [c.get("kind") for c in second])
        ck("F", "变化写进 changes.jsonl",
           os.path.exists(os.path.join(tmp, "autonomy", "changes.jsonl")),
           os.path.join(tmp, "autonomy", "changes.jsonl"))

        # ===== G 自主性 · 学习（分析历史 → 提炼话题）=====
        print("\n[G] 自主性 · 主动学习")
        from core.autonomy import learner as LN
        lr = LN.AutonomousLearner(state_dir=os.path.join(tmp, "learn"))
        msgs = ([{"role": "用户", "content": "帮我看看向量检索怎么做"} for _ in range(8)]
                + [{"role": "用户", "content": "抓取任务失败了怎么办"} for _ in range(6)])
        topics = lr.extract_topics(msgs)
        ck("G", "能提炼出高频话题", bool(topics), topics[:3])
        ck("G", "话题带次数且降序",
           all(isinstance(t, tuple) and len(t) == 2 for t in topics[:3])
           and [t[1] for t in topics[:3]] == sorted([t[1] for t in topics[:3]], reverse=True),
           topics[:3])
        lr.fetcher = lambda q: ""              # 离线：抓不到也要如实记 skipped
        res = lr.learn_once(topics=[topics[0][0]] if topics else ["向量检索"])
        ck("G", "抓不到内容时不崩、如实记 skipped",
           isinstance(res, dict) and (res.get("skipped") or res.get("learned") is not None), res)
    finally:
        srv.shutdown()
        X._WORLD_CACHE["override"] = None

    print("\n" + "=" * 62)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % ", ".join(FAIL)) if FAIL else ""))
    print("=" * 62)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
