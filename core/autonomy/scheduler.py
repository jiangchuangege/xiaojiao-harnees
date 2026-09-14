# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 自主调度器（自主 1：不等你开口也在做事）

它解决什么问题
--------------
用户说「每天早上八点给我总结一下科技新闻」→ 小焦得**每天八点都会想起来**这件事。
用户说「帮我盯着」→ 得**一直盯**，不是盯一次。
所以载体需要一根**自己的时间轴**：把"什么时候该做什么"从对话里搬出来，
放进一个跟"这一次提问"完全无关的后台循环里。

去掉它会怎样：小焦退回"被动问答机" —— 所有定时、盯梢、到点汇报，
都只能靠用户自己记着。载体就少了一个器官，也就谈不上"活着"。

三种触发方式（互相独立，一条任务只用一种）
------------------------------------------
  cron      5 段式 `分 时 日 月 周`，支持 `*` `*/n` `a-b` `a,b,c`
  interval  `interval_s` 秒一次
  idle      **空闲** `idle_s` 秒后触发 —— 需要外部定期调 `touch()` 上报"有人在用"
            （这就是"我没说话的时候你在干嘛"的入口：用户一直在聊，就不打扰；
              用户停下来了，它才去做自己的事。）

三条铁律（后台绝不能拖垮主对话）
--------------------------------
  ① daemon 线程：主进程退出即结束，不挂住 Flask；
  ② 每一步 try/except 吞异常并落日志：调度器崩了只是"不做事"，绝不带崩对话；
  ③ 任务超时不等待、失败不重试到死：一次失败就等下一个周期。

为什么任务在**独立 worker 线程**里跑，而不是直接在调度循环里跑
--------------------------------------------------------------
直接在循环里跑，一个卡住的网络请求（哪怕只是 30 秒）会把**所有**任务一起卡住 ——
cron 会漂、interval 会堆积、idle 会误判。所以每次触发都开一个短命 daemon worker，
调度循环只管"到点没到点"，永远不被业务代码堵住。
`_running` 标记防止同一个任务被并发重入（上一轮还没跑完，这一轮不该再开一个）。
"""
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta

from . import _append_jsonl, _app_module, _cfg, _log, _state_dir

# cron 五个字段的取值范围（分 时 日 月 周）
_FIELD_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
_MAX_INTERVAL_S = 30 * 86400.0     # 单条任务的周期上限（30 天）—— 防手滑写成一年的秒数
_MIN_INTERVAL_S = 1.0              # 周期下限 1 秒 —— 防手滑写成 0 把 CPU 跑满
_POLL_S = 0.1                      # 调度循环的轮询粒度（0.1s：2 秒周期的任务不会被漏掉也不会忙等）
_TASK_TIMEOUT_S = 300.0            # 单次任务最长执行时间（超了只记日志，不阻塞调度循环）
_SEARCH_DAYS = 1500                # cron 往后找的最大天数（要盖住 2 月 29 日这类 4 年才轮到的组合）


# ============================== cron 解析（纯函数，可单测） ==============================
def parse_field(field, lo, hi):
    """解析 cron 的**一个**字段 → set[int]。格式不认识就抛 ValueError（调用方决定跳过还是报错）。

    支持：`*` / `*/n` / `a-b` / `a-b/n` / `a/n` / `a` / `a,b,c`（上面这些的逗号组合）。
    为什么是"抛 ValueError"而不是"猜一个默认值"：cron 写错了，用户的本意我们猜不到
    （`0 8 * * *` 少了日字段变成 4 段，是每天 8 点还是每月 8 号 0 点？）。
    猜错的结果是**在小焦在错误的时间打扰用户** —— 不如明确拒绝并记一条日志，
    让用户看到"这条任务被跳过了"，而不是"小焦半夜乱发消息"。
    """
    out = set()
    for part in str(field or "").split(","):
        part = part.strip()
        if not part:
            raise ValueError("字段里有空的项")
        step = 1
        if "/" in part:
            part, _, s = part.partition("/")
            if not s.strip().isdigit() or int(s) <= 0:
                raise ValueError("步长非法：%r" % s)
            step = int(s)
            part = part.strip() or "*"
        if part == "*":
            a, b = lo, hi
        elif "-" in part.lstrip("-"):
            a_s, _, b_s = part.partition("-")
            if not a_s.strip().isdigit() or not b_s.strip().isdigit():
                raise ValueError("区间非法：%r" % part)
            a, b = int(a_s), int(b_s)
        else:
            if not part.isdigit():
                raise ValueError("取值非法：%r" % part)
            a = b = int(part)
        if a > b:
            raise ValueError("区间反了：%r" % part)
        if a < lo or b > hi:
            raise ValueError("超出范围 [%d,%d]：%r" % (lo, hi, part))
        out.update(range(a, b + 1, step))
    # 周字段：cron 里 0 和 7 都是周日，统一成 0，否则 `* * * * 7` 会匹配不上任何一天
    if (lo, hi) == (0, 7) and 7 in out:
        out.discard(7)
        out.add(0)
    if not out:
        raise ValueError("字段解析后为空")
    return out


def parse_cron(expr):
    """5 段式 cron 表达式 → (分, 时, 日, 月, 周) 五个 set。格式不对抛 ValueError。"""
    fields = str(expr or "").split()
    if len(fields) != 5:
        raise ValueError("cron 必须是 5 段（分 时 日 月 周），收到 %d 段：%r" % (len(fields), expr))
    return tuple(parse_field(f, lo, hi) for f, (lo, hi) in zip(fields, _FIELD_RANGES))


def _day_matches(sets, d):
    """某一天是否命中「日 月 周」（Vixie cron 的 OR 规则）。

    为什么日/周同时被限定时用 **OR**：这是 POSIX cron 的传统语义 ——
    `0 0 1 * 1` 的意思是"每月 1 号**或**每周一"，不是"既是 1 号又是周一"
    （后者几乎永不发生，等于任务失效）。去掉 OR 就会让这种写法静默失灵。
    """
    minutes, hours, dom, mon, dow = sets
    if (d.month not in mon):
        return False
    dom_restricted = dom != set(range(1, 32))
    dow_restricted = dow != set(range(0, 7))
    cron_dow = (d.weekday() + 1) % 7          # Python 周一=0 → cron 周日=0
    hit_dom = d.day in dom
    hit_dow = cron_dow in dow
    if dom_restricted and dow_restricted:
        return hit_dom or hit_dow
    if dom_restricted:
        return hit_dom
    if dow_restricted:
        return hit_dow
    return True


def next_run_from_sets(sets, after):
    """纯函数：`after`（时间戳）之后**第一次**命中 cron 的时间戳；找不到返回 0.0。

    为什么按"天"跳而不是逐分钟扫：逐分钟扫最坏要扫一年（52 万次），
    而按天跳只扫 1500 次、每天内部只在"命中的小时集合 × 分钟集合"里找第一个 ——
    快了三个数量级，而且**结果完全一样**（都是"第一个命中的整分钟"）。
    秒一律归零：cron 的粒度是分钟，`after=12:34:56` 的下一次必然 ≥ 12:35:00。
    """
    minutes, hours, _dom, _mon, _dow = sets
    minutes = sorted(minutes)
    hours = sorted(hours)
    dt = datetime.fromtimestamp(after).replace(second=0, microsecond=0) + timedelta(minutes=1)
    day = dt.date()
    for _ in range(_SEARCH_DAYS):
        if _day_matches(sets, day):
            for h in hours:
                for m in minutes:
                    cand = datetime(day.year, day.month, day.day, h, m)
                    if cand >= dt:
                        return cand.timestamp()
        day += timedelta(days=1)
    return 0.0


# ============================== 默认 runner / notify ==============================
def _default_runner(task):
    """默认的任务执行方式：**惰性**借用 `xiaojiao_app.agent_run` 跑这条 prompt。

    为什么不在这里自己拼一套模型调用：小焦的完整问答链路（记忆检索 → 联网 → 大脑 →
    记忆回写）全在 `agent_run` 里，后台任务理应走**同一条**路 —— 否则后台学到的、
    后台引用的东西跟对话里不是一回事，两边记忆会分裂。
    拿不到 app 就返回空串（如实记一条空结果），**绝不抛**：调度器不因为"宿主不在"而崩。
    """
    prompt = str(task.get("prompt") or task.get("task") or "").strip()
    if not prompt:
        return ""
    app = _app_module()
    if app is None or not hasattr(app, "agent_run"):
        return ""
    try:
        return app.agent_run(prompt, lean=True) or ""
    except TypeError:
        # 兼容旧签名（没有 lean 参数）—— 后台任务不该因为宿主版本差异就跑不起来
        try:
            return app.agent_run(prompt) or ""
        except Exception:      # noqa: silent-ok — 由 _run_task 统一记失败
            return ""


def _webhook_url(kind, cfg=None):
    """从配置里取 webhook 地址（`autonomy.webhooks.feishu` / `.dingtalk`）。取不到返回 ""。"""
    try:
        hooks = (_cfg() if cfg is None else cfg).get("autonomy", {}).get("webhooks") or {}
        if not isinstance(hooks, dict):
            return ""
        return str(hooks.get(kind) or "").strip()
    except Exception:      # noqa: silent-ok — 配置结构乱七八糟时按"没配"处理
        return ""


def _post_webhook(kind, url, title, text):
    """发一条群机器人消息。返回 (是否成功, 说明)；**任何失败都只是失败，不抛**。

    为什么超时只给 8 秒：后台通知是"锦上添花"，卡住一次会拖住整个任务 worker。
    宁可这条通知丢了（日志里有记录），也不能让后台线程悬在网络 IO 上。
    """
    body = (text or "")[:3000]
    if kind == "feishu":
        payload = {"msg_type": "text", "content": {"text": "%s\n%s" % (title, body)}}
    else:
        payload = {"msgtype": "text", "text": {"content": "%s\n%s" % (title, body)}}
    try:
        import requests
    except Exception:
        return False, "没有 requests 库"
    try:
        r = requests.post(url, json=payload, timeout=8)
        return (200 <= int(r.status_code) < 300), "HTTP %s" % r.status_code
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, str(e)[:120])


def _default_notify(task, text, state_dir=None, cfg=None):
    """默认通知：写 `logs/autonomy/notifications.jsonl`（网页端读它显示）。

    `notify` 字段取值：
      ui        写通知文件（默认，一定有地方能看到）
      feishu    飞书机器人（配了 webhook 才发）
      dingtalk  钉钉机器人（配了 webhook 才发）
    没配 webhook 时**降级成 ui 并如实记 note** —— 用户配错了会看到"降级"说明，
    而不是"我明明配了飞书怎么什么都没收到"。这条"如实"比"静默成功"重要得多。
    """
    st = _state_dir(state_dir)
    kind = str(task.get("notify") or "ui").strip().lower()
    note = ""
    if kind in ("feishu", "dingtalk"):
        url = _webhook_url(kind, cfg)
        if not url:
            note = "%s 未配置 webhook（autonomy.webhooks.%s），已降级为 ui" % (kind, kind)
            kind = "ui"
        else:
            ok, why = _post_webhook(kind, url, "小焦 · %s" % (task.get("id") or "任务"), text)
            if not ok:
                note = "%s 推送失败（%s），已降级为 ui" % (kind, why)
                kind = "ui"
    if kind == "ui":
        _append_jsonl(os.path.join(st, "notifications.jsonl"), {
            "ts": time.time(), "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "id": task.get("id") or "", "kind": "ui", "note": note,
            "title": (task.get("prompt") or task.get("id") or "")[:60],
            "chars": len(text or ""), "text": (text or "")[:2000],
        })
    return kind


# ============================== 调度器 ==============================
class AutonomyScheduler:
    """后台时间轴：登记任务 → 到点执行 → 记结果 → 通知。

    生命周期：`add()` 登记（不启动任何线程）→ `start()` 起 daemon 循环 → `stop()` 优雅退出。
    `tick()` 是**可注入假时钟**的单步推进，自测里用它把"等一小时"压缩成"传一个 now"。
    """

    def __init__(self, runner=None, notify=None, state_dir=None):
        self.runner = runner                 # runner(task) -> str
        self.notify = notify                 # notify(task, text)
        self.state_dir = _state_dir(state_dir)
        self._tasks = {}                     # id -> 任务记录（含运行时字段）
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = None
        self._last_touch = None              # 最近一次"用户有交互"的时间戳（idle 任务用）
        self._cfg_cache = None

    # ---------------------------------------------------------- 登记 / 移除
    def add(self, task):
        """校验并登记一条任务。返回 True/False（False 一律伴随一条日志，便于排查"为什么没生效"）。

        为什么校验这么严：任务定义来自用户手写的 JSON。一条 cron 写错如果不拦，
        要么静默永不触发（用户以为设好了），要么疯狂触发（写成 `* * * * *` 之类）。
        在**入口处**拒绝并记日志，是唯一能让用户自己看懂问题的位置。
        """
        rec, why = self._validate(task)
        if rec is None:
            _log("调度器：跳过非法任务（%s）：%s" % (why, json.dumps(task, ensure_ascii=False)[:200]),
                 os.path.join(self.state_dir, "autonomy.log"))
            return False
        with self._lock:
            if rec["id"] in self._tasks:
                _log("调度器：任务 id 重复，已忽略：%s" % rec["id"],
                     os.path.join(self.state_dir, "autonomy.log"))
                return False
            self._tasks[rec["id"]] = rec
        self._schedule_next(rec, time.time())
        self._wake.set()
        return True

    def _validate(self, task):
        """校验一条任务定义 → (规范化记录, 失败原因)。**不改动调用方传进来的 dict**。"""
        if not isinstance(task, dict):
            return None, "任务不是对象"
        tid = str(task.get("id") or "").strip()
        if not tid:
            return None, "缺少 id"
        if tid in ("", "None"):
            return None, "id 非法"
        rec = dict(task)
        rec["id"] = tid
        rec.setdefault("enabled", True)
        rec["runs"] = 0
        rec["last_run"] = None
        rec["last_result"] = ""
        rec["_running"] = False
        rec["_next"] = None
        rec["_last_idle_anchor"] = None
        rec["trigger"] = ""
        # 触发器优先级：cron > interval_s > idle_s（一条任务只用一种，避免语义打架）
        cron = str(task.get("cron") or "").strip()
        if cron:
            try:
                rec["_cron_sets"] = parse_cron(cron)
            except ValueError as e:
                return None, "cron 非法（%s）：%r" % (e, cron)
            rec["trigger"] = "cron"
            return rec, ""
        for key, trig in (("interval_s", "interval"), ("idle_s", "idle")):
            if task.get(key) is None:
                continue
            try:
                v = float(task[key])
            except (TypeError, ValueError):
                return None, "%s 不是数字：%r" % (key, task[key])
            if v < _MIN_INTERVAL_S:
                return None, "%s 太小（< %ss）" % (key, _MIN_INTERVAL_S)
            if v > _MAX_INTERVAL_S:
                return None, "%s 太大（> %ss）" % (key, _MAX_INTERVAL_S)
            rec[key] = v
            rec["trigger"] = trig
            return rec, ""
        return None, "没有触发器（需要 cron / interval_s / idle_s 之一）"

    def remove(self, tid):
        """移除任务。返回是否真的移除了（不存在返回 False，不抛）。"""
        with self._lock:
            return self._tasks.pop(str(tid), None) is not None

    def get(self, tid):
        """取一条任务记录（不存在返回 None）。"""
        with self._lock:
            return self._tasks.get(str(tid))

    # ---------------------------------------------------------- 时间轴
    def next_run_after(self, task, after):
        """cron 的下一次触发时间戳（**纯函数**，自测用假时钟断言到秒）。

        接受任务 dict 或 cron 字符串。表达式非法时返回 0.0（= 不知道下次什么时候），
        而不是抛异常 —— 这个方法会被 `_schedule_next` 在后台线程里调用，抛出去就是崩线程。
        """
        expr = task.get("cron") if isinstance(task, dict) else task
        if isinstance(task, dict) and task.get("_cron_sets"):
            return next_run_from_sets(task["_cron_sets"], after)
        try:
            return next_run_from_sets(parse_cron(expr), after)
        except ValueError:
            return 0.0

    def _schedule_next(self, rec, now):
        """算出这条任务的下一次触发时刻（写进 rec["_next"]）。

        idle 任务的 `_next` 留 None：它的触发条件不是"到点"而是"**用户安静够久了**"，
        这个信息只有 `touch()` 知道，所以交给 `_due()` 当场判断。
        """
        trig = rec.get("trigger")
        if trig == "cron":
            rec["_next"] = self.next_run_after(rec, now) or None
        elif trig == "interval":
            rec["_next"] = now + float(rec.get("interval_s") or 60)
        else:
            rec["_next"] = None

    def touch(self):
        """上报"用户有交互"（网页端每来一条消息调一次）。

        这就是 idle 任务的"有人在用"信号：用户一直在聊 → idle 任务一直不打扰；
        用户停下来了 → 过 idle_s 秒它才去做自己的事。
        去掉它会怎样：idle 任务永远不知道自己该不该出现 —— 要么永不触发，
        要么在用户正打字的时候插进来（比不做还烦人）。
        """
        self._last_touch = time.time()
        self._wake.set()

    def _due(self, rec, now):
        """这条任务此刻该不该触发？返回 (是否触发, 触发原因)。"""
        if not rec.get("enabled", True) or rec.get("_running"):
            return False, ""
        trig = rec.get("trigger")
        if trig == "idle":
            if self._last_touch is None:
                return False, ""                        # 从没上报过"有人在用" → 不擅自开工
            if now - self._last_touch < float(rec.get("idle_s") or 0):
                return False, ""                        # 用户还在用 → 不打扰
            if rec.get("_last_idle_anchor") == self._last_touch:
                return False, ""                        # 这一轮空闲已经做过一次了，等下次交互
            return True, "idle"
        nxt = rec.get("_next")
        if nxt is None:
            return False, ""
        if now >= float(nxt):
            return True, trig
        return False, ""

    def tick(self, now=None):
        """单步推进：把所有到点的任务发出去。**可注入 now**（自测用假时钟）。

        返回本次触发的 [(任务记录, 触发原因)]，方便自测断言。
        注意这里**不等任务跑完**：发出去就返回，调度循环立刻能继续判断下一个任务。
        """
        now = time.time() if now is None else float(now)
        fired = []
        with self._lock:
            for rec in list(self._tasks.values()):
                ok, why = self._due(rec, now)
                if not ok:
                    continue
                rec["_running"] = True
                self._schedule_next(rec, now)
                if why == "idle":
                    rec["_last_idle_anchor"] = self._last_touch
                fired.append((rec, why))
        for rec, why in fired:
            t = threading.Thread(target=self._run_task, args=(rec, why),
                                 name="autonomy-task-%s" % rec.get("id"), daemon=True)
            t.start()
        return fired

    # ---------------------------------------------------------- 执行
    def _run_task(self, rec, trigger):
        """执行一条任务：调 runner → 记 tasks.jsonl → 通知 → 更新计数。

        **无论成败都必须走完整个收尾**（记数、清 _running）—— 否则一条失败的任务会
        永远卡在 `_running=True`，从此再也不会被触发（"一次失败就永久停摆"，
        这正是最该避免的后台故障模式）。
        """
        t0 = time.time()
        ok, err, text = False, "", ""
        try:
            runner = self.runner or _default_runner
            text = runner(rec) or ""
            text = str(text)
            ok = True
        except Exception as e:
            err = "%s: %s" % (type(e).__name__, str(e)[:200])
            _log("调度器：任务 %s 执行失败：%s" % (rec.get("id"), err),
                 os.path.join(self.state_dir, "autonomy.log"))
        elapsed = round(time.time() - t0, 3)
        with self._lock:
            rec["runs"] = int(rec.get("runs") or 0) + 1
            rec["last_run"] = t0
            rec["last_result"] = (text if ok else "错误：%s" % err)[:200]
            rec["_running"] = False
        # 结果如实落盘（**成功也记**）：tasks.jsonl 是"它到底有没有在做事"的唯一凭据，
        # 只记失败的话，用户没法分辨"跑过了但没结果"和"根本没跑"。
        _append_jsonl(os.path.join(self.state_dir, "tasks.jsonl"), {
            "ts": t0, "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t0)),
            "id": rec.get("id"), "trigger": trigger, "ok": ok,
            "chars": len(text), "elapsed_s": elapsed, "error": err,
            "result_head": text[:200],
        })
        # 通知只在**有内容**时发：空的成功（比如"本次没搜到新东西"）不该打扰用户。
        # 失败不通知（只在日志里），否则断网一晚上会攒出上百条"任务失败"的噪音。
        if ok and text.strip():
            try:
                if self.notify:
                    self.notify(rec, text)
                else:
                    _default_notify(rec, text, self.state_dir, self._cfg_cache)
            except Exception as e:      # noqa: silent-ok — 通知失败不能反过来把任务标成失败
                _log("调度器：任务 %s 通知失败：%s" % (rec.get("id"), e),
                     os.path.join(self.state_dir, "autonomy.log"))
        if elapsed > _TASK_TIMEOUT_S:
            _log("调度器：任务 %s 耗时 %.1fs 超过 %.0fs（后台任务不该这么慢，检查 prompt）"
                 % (rec.get("id"), elapsed, _TASK_TIMEOUT_S),
                 os.path.join(self.state_dir, "autonomy.log"))
        return text

    def run_now(self, tid):
        """手动触发一次（自测/用户在界面上点"立刻跑一次"）。同步执行，返回结果文本。"""
        rec = self.get(tid)
        if rec is None:
            return ""
        with self._lock:
            rec["_running"] = True
        self._schedule_next(rec, time.time())
        return self._run_task(rec, "manual")

    # ---------------------------------------------------------- 查询
    def list_tasks(self):
        """列出任务（带 next_run / last_run / runs / last_result），给界面和自测看。"""
        with self._lock:
            out = []
            for rec in self._tasks.values():
                out.append({
                    "id": rec.get("id"), "trigger": rec.get("trigger"),
                    "cron": rec.get("cron") or "", "interval_s": rec.get("interval_s"),
                    "idle_s": rec.get("idle_s"), "enabled": bool(rec.get("enabled", True)),
                    "notify": rec.get("notify") or "ui",
                    "prompt": (rec.get("prompt") or "")[:120],
                    "next_run": rec.get("_next"), "last_run": rec.get("last_run"),
                    "runs": int(rec.get("runs") or 0), "last_result": rec.get("last_result") or "",
                    "running": bool(rec.get("_running")),
                })
        out.sort(key=lambda x: x["id"])
        return out

    # ---------------------------------------------------------- 生命周期
    def start(self):
        """起后台线程。已经在跑就返回 False（**幂等**：重复 start 不会起第二条线程）。

        为什么必须幂等：网页端可能被刷新多次、或者 app 里两处都调了 start。
        起两条线程的后果是每条任务被触发两次 —— 用户会收到两份重复通知。
        """
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._stop.clear()
            self._wake.clear()
            self._thread = threading.Thread(target=self._loop, name="autonomy-scheduler", daemon=True)
            self._thread.start()
            return True

    def _loop(self):
        """调度主循环：每 `_POLL_S` 秒 tick 一次。整个循环体**全包在 try 里**。

        为什么全包：这是后台线程的最外层。任何一次没预料到的异常（配置被改坏、
        runner 抛了奇怪的东西）如果逃出去，线程就死了 —— 而且**没有任何人会发现**，
        因为没人在等它的结果。用户只会觉得"小焦怎么不理我了"。
        包起来 + 继续循环，最多是"这一步没做成"。
        """
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as e:      # noqa: silent-ok — 单步失败不能让调度线程死掉
                _log("调度器：tick 异常（已忽略继续跑）：%s" % e,
                     os.path.join(self.state_dir, "autonomy.log"))
            self._wake.wait(_POLL_S)
            self._wake.clear()

    def stop(self, timeout=3):
        """优雅停止：置停止事件 + join(timeout)。返回线程是否真的退出了。

        为什么要 timeout：stop 一般在主线程里被调用（网页端退出、Ctrl+C）。
        如果某个任务正卡在网络请求上，无限等下去就是"关不掉的程序"。
        daemon 线程 + 有界等待 = 主线程最多被拖 `timeout` 秒，之后照样退出。
        去掉 timeout 会怎样：用户点"退出"，程序卡在那里不动 —— 最糟的收尾体验。
        """
        self._stop.set()
        self._wake.set()
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout)
        alive = bool(t is not None and t.is_alive())
        if not alive:
            self._thread = None
        return not alive

    def is_running(self):
        """后台线程是否还活着（自测断言"stop 之后线程真的退出了"）。"""
        t = self._thread
        return bool(t is not None and t.is_alive())

    # ---------------------------------------------------------- 配置装载
    def load_from_config(self, cfg=None):
        """从操控文件读 `autonomy.tasks` 并登记。返回成功登记条数。

        **坏了一条只跳过那一条**，其余照常登记：用户手写 10 条任务，
        第 7 条 cron 打错了一个字符 —— 因为这一条把另外 9 条也废掉，是最没道理的失败方式。
        跳过时写日志（哪一条、为什么），用户看一眼就知道改哪儿。
        """
        cfg = _cfg() if cfg is None else cfg
        self._cfg_cache = cfg
        auto = (cfg or {}).get("autonomy") if isinstance(cfg, dict) else None
        auto = auto if isinstance(auto, dict) else {}
        tasks = auto.get("tasks")
        if tasks is None:
            tasks = []
        if not isinstance(tasks, list):
            # 典型手滑：`"tasks": "0 8 * * *"` 或者整个对象忘了包一层数组
            _log("调度器：autonomy.tasks 不是数组（%s），已全部忽略"
                 % type(tasks).__name__, os.path.join(self.state_dir, "autonomy.log"))
            return 0
        ok_n = 0
        for task in tasks:
            if self.add(task):
                ok_n += 1
        return ok_n

    def maybe_start(self, cfg=None, start_if_enabled=True):
        """按配置决定要不要自动开跑（`autonomy.enabled` 默认 False）。

        为什么要这一步而不是"import 就开跑"：后台会自己联网、自己调模型。
        用户没点头就在后台烧额度，是小焦最不该犯的错。先装载任务，再看开关 ——
        这样即使用户没开自动，界面上也能看到"配了哪些任务、下次什么时候跑"。
        """
        cfg = _cfg() if cfg is None else cfg
        n = self.load_from_config(cfg)
        if start_if_enabled and bool((cfg or {}).get("autonomy", {}).get("enabled")):
            return {"loaded": n, "started": self.start()}
        return {"loaded": n, "started": False}


# 模块级便捷入口：宿主（xiaojiao_app）可以直接 `_sched = get_scheduler()` 复用同一个实例，
# 避免"两处各建一个调度器"导致任务被执行两遍。
_SINGLETON = {"lock": threading.Lock(), "obj": None}


def get_scheduler(runner=None, notify=None, state_dir=None):
    """拿进程内唯一的调度器（带锁，多线程同时调也只建一个）。"""
    with _SINGLETON["lock"]:
        if _SINGLETON["obj"] is None:
            _SINGLETON["obj"] = AutonomyScheduler(runner=runner, notify=notify, state_dir=state_dir)
        return _SINGLETON["obj"]


# 正则只用来给"cron 长什么样"做一个粗筛提示（真正的校验在 parse_cron）。
_CRON_SHAPE = re.compile(r"^\s*\S+\s+\S+\s+\S+\s+\S+\s+\S+\s*$")


def looks_like_cron(expr):
    """粗判一个字符串像不像 5 段 cron（给界面做输入提示用，不承担校验职责）。"""
    return bool(_CRON_SHAPE.match(str(expr or "")))
