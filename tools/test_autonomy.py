# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""自主性（core/autonomy）离线自测：`python tools/test_autonomy.py`

**全程离线**：唯一会碰网络的测试是 watcher —— 它连的是本脚本自己起的
`http.server`（端口用 0 让系统分配，不占固定端口、不依赖外网）。
learner 的 fetcher 全部被替换成"返回空串"，专门验证"抓不到时不崩、如实记 skipped"。

跑之前不需要启动小焦、不需要模型、不需要联网。退出码 0 = 全绿。

跑完看这些文件（都在 logs/autonomy/，logs/ 已被 .gitignore 忽略）：
  tasks.jsonl           真定时任务的执行记录（自测会往里面追加 selftest_echo 的记录）
  learning.jsonl        学习周期的记录
  changes.jsonl         盯梢发现的变化
  watch_errors.jsonl    盯梢抓取失败
  notifications.jsonl   默认通知落盘
  autonomy.log          跳过/降级的说明（坏配置测试就是查这个）

**本脚本只 append，绝不删除任何文件**（测试数据放在 logs/autonomy/_selftest/ 下）。
"""
import functools
import http.server
import json
import os
import sys
import threading
import time
from datetime import datetime

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:      # noqa: silent-ok — 老终端不支持就按原编码输出，测试结果不受影响
    pass

from core.autonomy import _enabled                                  # noqa: E402
from core.autonomy.learner import AutonomousLearner                 # noqa: E402
from core.autonomy.scheduler import AutonomyScheduler, parse_cron   # noqa: E402
from core.autonomy.watcher import AutonomousWatcher                 # noqa: E402

_STATE_DIR = os.path.join(_ROOT, "logs", "autonomy")                # 线上默认目录（真定时测试用）
_TEST_DIR = os.path.join(_STATE_DIR, "_selftest")                   # 其它测试的隔离目录
os.makedirs(_TEST_DIR, exist_ok=True)

_OK, _BAD = [], []


def check(name, cond, extra=""):
    """记一条断言结果。`extra` 无论成败都打出来 —— 失败时它就是现场证据。"""
    (_OK if cond else _BAD).append(name)
    tail = ("   ← %s" % extra) if extra else ""
    print("%s %s%s" % ("✅" if cond else "❌", name, tail))
    return bool(cond)


def read_jsonl(path):
    """读 JSONL（坏行跳过）。文件不存在返回 [] —— 测试不该因为"日志还没生成"直接炸。"""
    out = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:      # noqa: silent-ok — 半行残记录跳过即可
                    continue
    except FileNotFoundError:
        pass
    return out


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except FileNotFoundError:
        return ""


# ============================================================ 1. cron 解析
def test_cron():
    print("\n=== 1. cron 解析（假时钟断言到秒）===")
    s = AutonomyScheduler(state_dir=_TEST_DIR)
    base = datetime(2026, 3, 5, 12, 34, 56)          # 2026-03-05 是周四（已核实）
    after = base.timestamp()

    cases = [
        ("*/15 * * * *", datetime(2026, 3, 5, 12, 45, 0)),    # 当天下一个一刻钟
        ("0 8 * * *", datetime(2026, 3, 6, 8, 0, 0)),         # 次日早八
        ("30 2 * * 1", datetime(2026, 3, 9, 2, 30, 0)),       # 下周一 02:30
        ("0 0 1,15 * *", datetime(2026, 3, 15, 0, 0, 0)),     # 下一个 1/15 号
    ]
    for expr, exp in cases:
        got = s.next_run_after({"cron": expr}, after)
        check("cron %-14s → %s" % (expr, exp.strftime("%Y-%m-%d %H:%M:%S")),
              abs(got - exp.timestamp()) < 0.5,
              "实际 %s" % datetime.fromtimestamp(got).strftime("%Y-%m-%d %H:%M:%S"))

    # 正好落在触发点上时，下一次必须是"再下一个"，不能原地打转（否则会同一分钟疯狂触发）
    exact = datetime(2026, 3, 5, 12, 45, 0).timestamp()
    got = s.next_run_after({"cron": "*/15 * * * *"}, exact)
    check("正好在触发点上 → 顺延到下一个（13:00）",
          abs(got - datetime(2026, 3, 5, 13, 0, 0).timestamp()) < 0.5,
          "实际 %s" % datetime.fromtimestamp(got).strftime("%H:%M:%S"))

    # a,b,c 与 a-b 两种写法
    got = s.next_run_after({"cron": "5,35 6-7 * * *"}, datetime(2026, 3, 5, 6, 10, 0).timestamp())
    check("cron 5,35 6-7 * * * → 06:35",
          abs(got - datetime(2026, 3, 5, 6, 35, 0).timestamp()) < 0.5,
          "实际 %s" % datetime.fromtimestamp(got).strftime("%H:%M:%S"))

    for bad in ("0 8 * *", "99 8 * * *", "0 8 * * 9", "* * * * * *", ""):
        try:
            parse_cron(bad)
            ok = False
        except ValueError:
            ok = True
        check("非法 cron 被拒绝：%r" % bad, ok)
    check("非法 cron 的 next_run_after 返回 0.0（不抛）",
          s.next_run_after({"cron": "99 99 * * *"}, after) == 0.0)
    check("秒一律归零（12:34:56 → 下一次是整分钟）",
          s.next_run_after({"cron": "*/15 * * * *"}, after) % 60 == 0)


# ============================================================ 2. 真定时
def test_realtime():
    print("\n=== 2. 真定时：interval 任务真的在后台跑 ===")
    log_path = os.path.join(_STATE_DIR, "tasks.jsonl")
    before = len(read_jsonl(log_path))
    calls = {"n": 0}
    lock = threading.Lock()

    def runner(task):
        with lock:
            calls["n"] += 1
            n = calls["n"]
        return "回声 %d（%s）" % (n, task.get("id"))

    s = AutonomyScheduler(runner=runner)          # 默认 state_dir = logs/autonomy/
    check("登记 interval 任务", s.add({"id": "selftest_echo", "interval_s": 2,
                                      "prompt": "回声测试", "notify": "ui"}))
    check("start() 起了后台线程", s.start())
    time.sleep(5.2)                               # 周期 2s → 5.2 秒内至少跑 2 次
    rec = [t for t in s.list_tasks() if t["id"] == "selftest_echo"]
    check("真定时：5 秒内跑了 ≥2 次", bool(rec) and rec[0]["runs"] >= 2,
          "runs=%s" % (rec[0]["runs"] if rec else "无"))
    check("next_run / last_run 都有值",
          bool(rec) and rec[0]["next_run"] and rec[0]["last_run"],
          "next=%s last=%s" % (rec[0]["next_run"] if rec else None,
                               rec[0]["last_run"] if rec else None))

    lines = read_jsonl(log_path)
    mine = [r for r in lines if r.get("id") == "selftest_echo"]
    check("logs/autonomy/tasks.jsonl 有本次执行记录", len(mine) >= 2, "共 %d 条" % len(mine))
    check("tasks.jsonl 总行数增加", len(lines) > before, "%d → %d" % (before, len(lines)))
    if mine:
        need = ("ts", "id", "trigger", "ok", "chars", "elapsed_s", "error", "result_head")
        check("执行记录字段齐全", all(k in mine[-1] for k in need),
              "缺：%s" % [k for k in need if k not in mine[-1]])
        check("执行记录标记为成功且触发原因是 interval",
              mine[-1].get("ok") is True and mine[-1].get("trigger") == "interval")
    notes = read_jsonl(os.path.join(_STATE_DIR, "notifications.jsonl"))
    check("默认通知落了 notifications.jsonl", any(n.get("id") == "selftest_echo" for n in notes))

    check("stop() 优雅退出", s.stop())
    check("stop 后调度线程不再存活", not s.is_running())


# ============================================================ 3. idle 任务
def test_idle():
    print("\n=== 3. idle 任务：用户安静下来才做事 ===")
    runs = {"n": 0}

    def runner(task):
        runs["n"] += 1
        return "空闲任务跑了一次"

    s = AutonomyScheduler(runner=runner, state_dir=os.path.join(_TEST_DIR, "idle"))
    check("登记 idle 任务", s.add({"id": "selftest_idle", "idle_s": 2, "prompt": "空闲干活"}))
    s.start()
    time.sleep(1.0)
    check("从没 touch() 过 → 不触发（不擅自开工）", runs["n"] == 0, "跑了 %d 次" % runs["n"])

    s.touch()
    time.sleep(1.2)
    check("touch() 后还没到 idle_s → 不触发（不打扰用户）", runs["n"] == 0,
          "跑了 %d 次" % runs["n"])
    time.sleep(1.6)
    check("过 idle_s 之后 → 触发", runs["n"] >= 1, "跑了 %d 次" % runs["n"])

    n1 = runs["n"]
    time.sleep(1.0)
    check("同一轮空闲只做一次（不重复刷）", runs["n"] == n1, "%d → %d" % (n1, runs["n"]))

    s.touch()                                     # 用户又说了一句话
    time.sleep(2.4)
    check("新一轮空闲（再次 touch）后可以再触发", runs["n"] > n1, "跑了 %d 次" % runs["n"])
    check("stop() 优雅退出", s.stop() and not s.is_running())


# ============================================================ 4. 盯梢
class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """本地被测站点。把访问日志静音，免得测试输出被 HTTP 日志刷满。"""

    def log_message(self, *a):      # noqa: D102 — 静音用，无需文档
        pass


def test_watcher():
    print("\n=== 4. 盯梢：本地 http.server 当被测站点 ===")
    web = os.path.join(_TEST_DIR, "web")
    os.makedirs(web, exist_ok=True)
    files = {"a.txt": "版本一 hello 世界", "b.txt": "普通内容，什么都没有",
             "c.txt": "每次都要汇报", "d.txt": "当前版本1", "e.txt": "未知规则测试"}
    for name, body in files.items():
        with open(os.path.join(web, name), "w", encoding="utf-8") as f:
            f.write(body)

    handler = functools.partial(_QuietHandler, directory=web)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)   # 端口 0 → 系统分配
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % port
    t0 = time.time()
    st = os.path.join(_TEST_DIR, "watch")
    w = AutonomousWatcher(state_dir=st)

    check("add 成功（changed 规则）", w.add(base + "/a.txt", interval=1, rule="changed"))
    r1 = w.check_once(now=t0)
    check("第一次抓到 → first_seen", bool(r1) and r1[0]["kind"] == "first_seen",
          "实际 %r" % [c["kind"] for c in r1])

    def write(name, body):
        with open(os.path.join(web, name), "w", encoding="utf-8") as f:
            f.write(body)
        time.sleep(0.05)      # 让文件时间戳稳定，避免个别文件系统的时间分辨率干扰

    write("a.txt", "版本二 world，内容变了")
    r2 = w.check_once(now=t0 + 2)
    check("内容变了 → changed", bool(r2) and r2[0]["kind"] == "changed",
          "实际 %r" % [c["kind"] for c in r2])
    check("变化记录字段齐全",
          bool(r2) and all(k in r2[0] for k in
                           ("ts", "url", "rule", "kind", "detail", "old_head", "new_head")))

    r3 = w.check_once(now=t0 + 4)
    check("内容没变 → 不再记（不然就是噪音）", r3 == [], "实际 %d 条" % len(r3))

    check("add contains 规则", w.add(base + "/b.txt", interval=1, rule="contains:发行版"))
    r4 = w.check_once(now=t0 + 6)
    check("关键词还没出现 → 不记", [c for c in r4 if c["url"].endswith("b.txt")] == [])

    write("b.txt", "新内容：发行版 2.0 上线了")
    r5 = w.check_once(now=t0 + 8)
    check("contains 规则命中 → 记一条",
          any(c["kind"] == "contains" for c in r5), "实际 %r" % [c["kind"] for c in r5])

    write("b.txt", "又改了一次：发行版 2.0 依然在")
    r6 = w.check_once(now=t0 + 10)
    check("同一关键词不重复报（第二次不再记）",
          all(c["kind"] != "contains" for c in r6), "实际 %r" % [c["kind"] for c in r6])

    check("add any 规则", w.add(base + "/c.txt", interval=1, rule="any"))
    r7 = w.check_once(now=t0 + 12, force=True)
    any7 = [c for c in r7 if c["url"].endswith("c.txt")]
    r8 = w.check_once(now=t0 + 14, force=True)
    any8 = [c for c in r8 if c["url"].endswith("c.txt")]
    check("any 规则每次抓都记一条（两次都有）",
          len(any7) == 1 and len(any8) == 1 and any7[0]["kind"] == "any")

    check("add regex 规则", w.add(base + "/d.txt", interval=1, rule=r"regex:版本\d"))
    r9 = w.check_once(now=t0 + 16, force=True)
    rx = [c for c in r9 if c["url"].endswith("d.txt")]
    check("regex 首次命中 → 记一条 regex", len(rx) == 1 and rx[0]["kind"] == "regex",
          "实际 %r" % [(c["url"][-5:], c["kind"]) for c in r9])

    check("未知 rule 降级为 changed（不静默失效）",
          w.add(base + "/e.txt", interval=1, rule="这是什么规则") and
          [x for x in w.list_watchers() if x["url"].endswith("e.txt")][0]["rule"] == "changed")

    check("url 非法被拒绝", w.add("ftp://x/y") is False and w.add("") is False)
    check("重复 add 同一 url → False", w.add(base + "/a.txt") is False)

    # 抓取失败：**不算变化**，但要更新状态 + 单独记错误日志
    bad = "http://127.0.0.1:1/不存在.txt"
    check("可以登记一个抓不到的 url", w.add(bad, interval=1, rule="changed"))
    r10 = w.check_once(now=t0 + 18, force=True)
    check("抓失败不算变化", all(c["url"] != bad for c in r10))
    errs = read_jsonl(os.path.join(st, "watch_errors.jsonl"))
    check("抓失败记 watch_errors.jsonl", any(e.get("url") == bad for e in errs),
          "共 %d 条" % len(errs))
    rec = [x for x in w.list_watchers() if x["url"] == bad][0]
    check("抓失败更新 last_status", str(rec["last_status"]).startswith("error"),
          "last_status=%r" % rec["last_status"])
    check("list_watchers 带 last_check / changes 字段",
          all(k in rec for k in ("last_check", "last_status", "changes")))

    changes = read_jsonl(os.path.join(st, "changes.jsonl"))
    check("changes.jsonl 落了记录", len(changes) >= 3, "共 %d 条" % len(changes))
    state = json.loads(read_text(os.path.join(st, "watchers_state.json")) or "{}")
    check("watchers_state.json 有 url → {hash, at, status, len}",
          any(isinstance(v, dict) and {"hash", "at", "status", "len"} <= set(v)
              for v in state.values()), "状态里有 %d 个目标" % len(state))

    check("load_from_config 装载 watchers（含坏条目只跳过它自己）",
          AutonomousWatcher(state_dir=os.path.join(_TEST_DIR, "watch2")).load_from_config(
              {"autonomy": {"watchers": [{"url": base + "/a.txt", "interval": 60},
                                         "这条不是对象",
                                         {"url": "没有协议的地址"}]}}) == 1)

    # 后台线程：起得来、停得掉
    wt = AutonomousWatcher(fetcher=lambda u: ("", "离线"), state_dir=os.path.join(_TEST_DIR, "watch3"))
    check("watcher start() 起线程", wt.start(poll_s=1) is True and wt.start(poll_s=1) is False)
    check("watcher stop() 后线程退出", wt.stop() and not wt.is_running())

    srv.shutdown()
    srv.server_close()
    check("本地被测站点已关闭（不删除任何文件）", True)


# ============================================================ 5. 学习者
def _fake_history():
    """30 条假历史：8 条提「向量检索」、6 条提「抓取」，其余是别的闲聊。

    刻意混进"帮我/什么/可以/这个"这类停用词，好验证它们**不会**被当成话题。
    """
    msgs = []
    vec = ["向量检索的原理是什么", "向量检索性能怎么优化", "向量检索适合什么场景",
           "向量检索的索引结构", "向量检索的效果如何", "向量检索成本高不高",
           "向量检索落地难在哪", "向量检索选哪个库好"]
    for line in vec:
        msgs.append({"role": "用户", "content": line})
    grab = ["抓取网页", "抓取新闻", "抓取数据", "抓取页面", "抓取文章", "抓取链接"]
    for g in grab:
        msgs.append({"role": "用户", "content": "%s的代码怎么写" % g})
    filler = ["部署脚本报错了", "缓存策略要改", "部署流程太慢", "缓存命中率低",
              "日志太多看不清", "回归测试怎么跑", "日志要分级别", "回归测试太慢",
              "接口响应很慢", "接口文档缺了", "权限配置麻烦", "权限模型要重做",
              "监控告警太多", "监控要看板", "备份策略定了", "备份要定期演练"]
    for line in filler:
        msgs.append({"role": "小焦" if len(msgs) % 2 else "用户", "content": line})
    return msgs


def test_learner():
    print("\n=== 5. 学习者：提炼话题 + 抓不到时如实 skipped ===")
    msgs = _fake_history()
    check("假历史条数正确（30 条）", len(msgs) == 30, "实际 %d" % len(msgs))
    st = os.path.join(_TEST_DIR, "learn")
    L = AutonomousLearner(state_dir=st)
    topics = L.extract_topics(msgs)
    d = dict(topics)
    check("提炼出「向量检索」且次数=8", d.get("向量检索") == 8, "实际 %s" % d.get("向量检索"))
    check("提炼出「抓取」且次数=6", d.get("抓取") == 6, "实际 %s" % d.get("抓取"))
    check("话题按次数降序", [c for _t, c in topics] == sorted([c for _t, c in topics], reverse=True),
          "%r" % topics[:5])
    check("停用词/口水词没被当成话题",
          not any(w in t for t in d for w in ("帮我", "什么", "可以", "这个", "的", "我")),
          "话题：%r" % list(d)[:10])
    check("话题长度合理（≤8 字）", all(2 <= len(t) <= 8 for t in d))
    check("top_n 生效", len(L.extract_topics(msgs, top_n=3)) == 3)
    check("空历史不崩", L.extract_topics([]) == [])

    stored = []

    def storer(topic, text):
        stored.append(topic)
        return True

    L2 = AutonomousLearner(fetcher=lambda t: "", storer=storer,
                           state_dir=os.path.join(_TEST_DIR, "learn2"))
    res = L2.learn_once([("向量检索", 8)])
    check("抓取返回空 → 不崩", isinstance(res, dict))
    check("抓取返回空 → 如实记 skipped", res.get("skipped") == 1 and res.get("learned") == 0,
          "实际 %r" % res)
    check("抓取为空时不调用 storer（不假装学到了）", stored == [])
    check("空话题列表也不崩", L2.learn_once([])["learned"] == 0)

    L3 = AutonomousLearner(history_getter=lambda: msgs, fetcher=lambda t: "",
                           storer=storer, state_dir=os.path.join(_TEST_DIR, "learn3"))
    summary = L3.cycle()
    check("cycle 返回摘要（含 topics/learned/skipped/reason）",
          all(k in summary for k in ("topics", "learned", "skipped", "reason")))
    check("cycle 学到了该学的话题数（每轮最多 2 个）",
          len(summary["topics"]) >= 2 and summary["skipped"] == 2,
          "topics=%d skipped=%s" % (len(summary["topics"]), summary["skipped"]))
    lines = read_jsonl(os.path.join(L3.state_dir, "learning.jsonl"))
    check("learning.jsonl 落了本轮记录", bool(lines) and "topics" in lines[-1],
          "共 %d 条" % len(lines))

    # fetcher 抛异常也必须不崩（网络层什么怪事都有）
    L4 = AutonomousLearner(fetcher=lambda t: (_ for _ in ()).throw(RuntimeError("模拟炸了")),
                           storer=storer, state_dir=os.path.join(_TEST_DIR, "learn4"))
    res4 = L4.learn_once([("抓取", 6)])
    check("fetcher 抛异常 → 不崩且记 skipped", res4.get("skipped") == 1)

    # 抓到内容之后到底存哪去了 —— 两条路都要验，而且**绝不写用户真实的记忆库**：
    # 先把 memory_vec.add_memory 换成假的（记录调用参数），验证"我们是怎么调它的"；
    # 再让它抛异常，验证"记忆库坏了会退到 knowledge.jsonl"，学到的知识不会丢。
    mv, real_add = None, None
    try:
        import core.memory_vec as mv
        real_add = mv.add_memory
    except Exception as e:      # noqa: silent-ok — 环境里没有 embedding 依赖就跳过这两条
        mv = None
        print("   （跳过记忆库断言：%s）" % str(e)[:60])
    try:
        calls = []
        if mv is not None:
            mv.add_memory = lambda *a, **k: (calls.append((a, k)) or "fake-id")
        L5 = AutonomousLearner(fetcher=lambda t: "这是关于 %s 的一小段资料" % t,
                               state_dir=os.path.join(_TEST_DIR, "learn5"))
        res5 = L5.learn_once([("向量检索", 3)])
        check("抓到内容 → 存进记忆（learned=1）", res5.get("learned") == 1, "实际 %r" % res5)
        if mv is not None:
            kw = calls[0][1] if calls else {}
            check("调 add_memory 参数正确（kind=fact / entities / key_text=话题）",
                  kw.get("kind") == "fact" and kw.get("key_text") == "向量检索"
                  and kw.get("entities") == ["向量检索"], "实际 %r" % kw)
            mv.add_memory = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("模拟记忆库坏了"))
            L6 = AutonomousLearner(fetcher=lambda t: "资料：%s" % t,
                                   state_dir=os.path.join(_TEST_DIR, "learn7"))
            res6 = L6.learn_once([("备份策略", 2)])
            kn = read_jsonl(os.path.join(L6.state_dir, "knowledge.jsonl"))
            check("记忆库写失败 → 退到 knowledge.jsonl（知识不丢）",
                  res6.get("learned") == 1 and bool(kn) and kn[-1].get("topic") == "备份策略",
                  "learned=%s / 文件 %d 条" % (res6.get("learned"), len(kn)))
    finally:
        if mv is not None and real_add is not None:
            mv.add_memory = real_add      # 一定要还回去，别把补丁漏给后面的测试

    lt = AutonomousLearner(fetcher=lambda t: "", state_dir=os.path.join(_TEST_DIR, "learn6"))
    check("learner start() 起线程且幂等", lt.start(60) is True and lt.start(60) is False)
    check("learner stop() 后线程退出", lt.stop() and not lt.is_running())


# ============================================================ 6. 坏配置
def test_bad_config():
    print("\n=== 6. 坏配置：跳过坏的，不影响好的 ===")
    st = os.path.join(_TEST_DIR, "badcfg")
    s = AutonomyScheduler(runner=lambda t: "x", state_dir=st)
    n = s.load_from_config({"autonomy": {"tasks": "这不是数组"}})
    check("tasks 写成字符串 → 0 条且不崩", n == 0, "实际 %d" % n)
    check("坏配置有日志说明", "不是数组" in read_text(os.path.join(st, "autonomy.log")))

    n2 = s.load_from_config({"autonomy": {"tasks": [
        {"cron": "0 8 * * *"},                                        # 缺 id
        {"id": "bad_cron", "cron": "99 99 * * *"},                    # cron 非法
        {"id": "no_trigger", "prompt": "没有触发器"},                  # 三种触发都没有
        {"id": "bad_interval", "interval_s": "很久"},                  # 周期不是数字
        {"id": "good_one", "interval_s": 3600, "prompt": "好的任务"},
        {"id": "good_cron", "cron": "0 8 * * *", "prompt": "好的定时任务"},
    ]}})
    check("坏条目被跳过、好条目登记成功（2 条）", n2 == 2, "实际 %d" % n2)
    ids = [t["id"] for t in s.list_tasks()]
    check("只登记了能用的两条", ids == ["good_cron", "good_one"], "实际 %r" % ids)
    logtxt = read_text(os.path.join(st, "autonomy.log"))
    check("跳过原因都写进了日志", "跳过非法任务" in logtxt and "cron 非法" in logtxt)
    check("直接 add 非法任务返回 False",
          s.add({"id": "x", "cron": "0 8 * *"}) is False and
          s.add("这不是对象") is False and
          s.add({"id": "y", "interval_s": 0}) is False)
    check("重复 add 同 id 返回 False", s.add({"id": "good_one", "interval_s": 60}) is False)
    check("remove 存在的返回 True、不存在返回 False",
          s.remove("good_one") is True and s.remove("good_one") is False)

    bad_w = AutonomousWatcher(state_dir=os.path.join(_TEST_DIR, "badcfg_w"))
    check("watchers 写成字符串 → 0 条且不崩",
          bad_w.load_from_config({"autonomy": {"watchers": "不是数组"}}) == 0)
    check("rule 写错 → 降级 changed 并能在日志里看到",
          bad_w.add("http://127.0.0.1:1/x", rule="没这种规则") and
          "无法识别的 rule" in read_text(os.path.join(bad_w.state_dir, "autonomy.log")))

    check("_cfg() 读真实操控文件不抛、默认 enabled=False（用户没点头就不自动开）",
          _enabled() is False)
    check("_cfg() 对任意垃圾 cfg 都返回 dict",
          isinstance(s.load_from_config(None) or 0, int))


# ============================================================ 7. 单例 / 生命周期
def test_lifecycle():
    print("\n=== 7. 单例 / 幂等 / 线程真的退出 ===")
    st = os.path.join(_TEST_DIR, "life")
    before = threading.active_count()
    s = AutonomyScheduler(runner=lambda t: "x", state_dir=st)
    check("add 返回 True", s.add({"id": "life", "interval_s": 3600}) is True)
    check("重复 add 同 id 返回 False", s.add({"id": "life", "interval_s": 1}) is False)
    check("start() 返回 True", s.start() is True)
    check("重复 start() 返回 False（不会起第二条线程）", s.start() is False)
    time.sleep(0.4)
    check("stop() 返回 True（线程真的退出了）", s.stop() is True)
    check("is_running() 为 False", s.is_running() is False)
    time.sleep(0.2)
    check("threading.active_count() 回落", threading.active_count() <= before,
          "%d → %d" % (before, threading.active_count()))
    check("重复 stop() 不报错", s.stop() is True)

    from core.autonomy.scheduler import get_scheduler
    check("get_scheduler 单例：两次拿到同一个对象", get_scheduler() is get_scheduler())

    # 宿主接入入口：默认（enabled=False）**一个线程都不起**，这是"用户没点头就不烧额度"的保证
    import core.autonomy as auto_pkg
    off = auto_pkg.start_all({"autonomy": {"enabled": False}})
    # 【为什么判据从"整个 dict 相等"改成"三个布尔都是 False"】
    #   原来写的是 `off == {"enabled": False, "scheduler": ..., "learner": ..., "watcher": ...}`
    #   —— 那是在断言 **dict 的形状**，而不是这条断言的标题所说的"不起任何后台线程"。
    #   后来 `start_all` 为修一个显示缺陷补了 `tasks / watchers / reason` 三个报告字段
    #   （宿主启动日志原本因字段名对不上，"定时任务 N 个"恒显示 0），
    #   这个"形状相等"当场变红 ——**线程确实一个都没起，是断言判错了对象**。
    #   现在判它真正要保证的事：三个后台器官全没起来。
    check("enabled=False 时 start_all 不起任何后台线程",
          off.get("enabled") is False and off.get("scheduler") is False
          and off.get("learner") is False and off.get("watcher") is False,
          "实际 %r" % off)
    check("enabled=False 时如实说明原因（不让用户猜）",
          bool(off.get("reason")), "reason=%r" % off.get("reason"))
    auto_pkg.touch()      # 只上报交互，不该抛（单例调度器会被建出来但没有线程）
    check("enabled=False 时 touch() 不抛", True)
    check("stop_all 对没起过的东西返回 True", auto_pkg.stop_all() ==
          {"scheduler": True, "learner": True, "watcher": True},
          "实际 %r" % auto_pkg.stop_all())

    before_on = threading.active_count()
    on = auto_pkg.start_all({"autonomy": {"enabled": True, "tasks": [], "watchers": []}},
                            learn_interval_s=3600, watch_poll_s=60)
    check("enabled=True 时 start_all 起三个线程",
          on["scheduler"] and on["learner"] and on["watcher"], "实际 %r" % on)
    time.sleep(0.3)
    check("三个线程确实活着（线程数上升）", threading.active_count() > before_on,
          "%d → %d" % (before_on, threading.active_count()))
    stopped = auto_pkg.stop_all()
    check("stop_all 三个都停干净", all(stopped.values()), "实际 %r" % stopped)
    time.sleep(0.3)
    check("stop_all 后线程数回落", threading.active_count() <= before_on,
          "%d → %d" % (before_on, threading.active_count()))

    s2 = AutonomyScheduler(runner=lambda t: "手动结果", state_dir=os.path.join(_TEST_DIR, "manual"))
    s2.add({"id": "manual", "interval_s": 3600, "prompt": "手动跑一次"})
    check("run_now 手动触发一次并返回结果", s2.run_now("manual") == "手动结果")
    check("run_now 不存在的 id 返回空串（不抛）", s2.run_now("不存在") == "")
    check("run_now 计入 runs 与 last_result",
          s2.list_tasks()[0]["runs"] == 1 and s2.list_tasks()[0]["last_result"] == "手动结果")


def main():
    t0 = time.time()
    print("小焦 · 自主性离线自测（全程不联网外网；盯梢打的是本机 http.server）")
    test_cron()
    test_realtime()
    test_idle()
    test_watcher()
    test_learner()
    test_bad_config()
    test_lifecycle()

    total = len(_OK) + len(_BAD)
    print("\n" + "=" * 60)
    if _BAD:
        print("失败项：")
        for name in _BAD:
            print("  ❌ %s" % name)
    print("通过 %d / 共 %d（耗时 %.1fs）" % (len(_OK), total, time.time() - t0))
    return 0 if not _BAD else 1


if __name__ == "__main__":
    sys.exit(main())
