# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 记忆保养（让"降级 / 压缩 / 巩固"这三件后台活真的跑起来）

【为什么需要这个文件 —— 一段如实的历史】
    `core/memory_deep.py` 里那三个机制（`degrade` / `compress` / `consolidate`）
    加上喂给巩固用的 `note_usage()`，写完之后**只有自测脚本在调**；
    `docs/modules/03-memory-depth.md` 的 7.1 那张表自己就写着「设计，未落地」。
    后果不是报错，而是**整套机制静默不生效**：
      · 清晰度永远停在"高清"（时间降级从没跑过）；
      · 半年前的事不会被压成印象（库只会越长越大、检索越来越吵）；
      · `consolidate()` 的输入 `note_usage()` 一个调用方都没有 —— 就算跑了，
        引用数永远是 0，等于把"重要的事锁住"这条规则空转。
    这个模块把这条链补上：**谁记账、什么时候保养、跑完留下什么证据**。

【只加不删，四条硬规矩】
    ① **只写不读**：保养只改记忆行自己的元数据（clarity / locked / refs / compressed_to），
       **不参与回答**、不改检索排序、不改任何注入文本 —— 所以它可以放心跑在后台；
    ② **一步一记**：降级/压缩/巩固各自 try/except，一个炸了另外两个照跑，
       报告里如实写哪一步失败（不是"整体成功"）；
    ③ **跑完留证据**：每轮报告追加到 `logs/memory_upkeep.jsonl`（真实数字），
       外加一行 INFO 日志 —— "接上了没在跑"是这套机制最容易犯的错，所以必须看得见；
    ④ **节流**：`note_usage` 一次要重写整个记忆文件，所以按"每 N 秒最多记一次"限流，
       并且**同一批 id 一次写完**（原来逐个调用 = 逐个全文件重写，5 条命中就是 5 次）。

【诚实的边界】
    · 它**不判断"这条记忆对不对"**，只按时间与引用次数做保养；
    · 它**不救已经写坏的库**（脏数据得靠写入侧过滤，见 `core/mem_filter.py`）；
    · 它跑不跑得起来要能在日志里看到 —— 看不到就等于没接。
"""
import json
import os
import threading
import time

from . import memory_deep as MD

_LOGS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
_REPORT = os.path.join(_LOGS_DIR, "memory_upkeep.jsonl")

INTERVAL_DEFAULT = 1800.0        # 默认每 30 分钟保养一次
BOOT_DELAY_DEFAULT = 180.0       # 启动后先等 3 分钟：别和启动/预热抢 IO
NOTE_MIN_INTERVAL = 120.0        # 同一进程里，引用记账最多这么频繁一次
_NOTE_MAX_IDS = 8                # 一次最多记 8 条（够用就行，多了也只是写更多行）

_lock = threading.Lock()
_state = {
    "thread": None, "stop": None, "interval": INTERVAL_DEFAULT,
    "runs": 0, "last": None, "last_at": 0.0, "last_error": "",
    "note_at": 0.0, "noted_rows": 0, "note_runs": 0,
}


def _log(msg, *args):
    try:
        import logging
        logging.getLogger("xiaojiao.memory_upkeep").info(msg, *args)
    except Exception:      # noqa: silent-ok — 日志打不出来不影响保养本身
        pass


def _append_report(rec):
    try:
        os.makedirs(_LOGS_DIR, exist_ok=True)
        with open(_REPORT, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:      # noqa: silent-ok — 报告写不进去也要让保养继续
        _log("保养报告写盘失败（忽略）：%s", e)


# ------------------------------------------------------------------ ① 引用记账
def note_usages(ids, force=False, now=None):
    """记"这些记忆这一轮被检索到了"（供 `consolidate()` 决定该不该锁成高清）。

    为什么要节流 + 批量：
      · `note_usage()` 每调一次就**整库重写一遍**（读全表 → 改一行 → 原子替换 → 重建索引）；
      · 一轮对话命中 5 条，逐个调用就是 5 次全库重写 —— 那是拿磁盘换一个计数器。
    所以这里：同一批 id 一次写完；并且**每 `NOTE_MIN_INTERVAL` 秒最多记一次**
    （引用计数是"够不够 3 次"这种量级的判断，不缺这几分钟的精度）。
    返回真实写进去的条数（0 表示被节流或没有可用 id）。
    """
    try:
        now = time.time() if now is None else float(now)
        want = [str(x) for x in (ids or []) if x]
        if not want:
            return 0
        if not force and (now - float(_state["note_at"] or 0)) < NOTE_MIN_INTERVAL:
            return 0
        want = want[:_NOTE_MAX_IDS]
        got = MD.note_usages(want, now=now)
        _state["note_at"] = now
        _state["noted_rows"] = int(_state["noted_rows"]) + int(got or 0)
        _state["note_runs"] = int(_state["note_runs"]) + 1
        if got:
            _log("记忆引用记账：命中 %d 条 → 记上 %d 条（供巩固判断「重要」）", len(want), got)
        return int(got or 0)
    except Exception as e:      # noqa: silent-ok — 记账失败绝不能影响这一轮对话
        _log("记忆引用记账失败（忽略）：%s", e)
        return 0


def note_usages_async(ids):
    """记账丢后台线程（**不在对话链路上做文件 IO**）。同一时刻只允许一个在跑。"""
    def _run():
        if not _lock.acquire(blocking=False):
            return
        try:
            note_usages(ids)
        finally:
            _lock.release()
    try:
        threading.Thread(target=_run, name="xj-memory-note", daemon=True).start()
    except Exception as e:      # noqa: silent-ok
        _log("记账线程起不来（忽略）：%s", e)


# ------------------------------------------------------------------ ② 保养一轮
def maintain(now=None, apply=True):
    """跑一轮保养：**巩固 → 降级 → 压缩**（顺序固定，理由见下）。

    为什么是这个顺序（**2026-10-16 写"接入前后对比"时改正过一次**）：

      · **先巩固**：把"被引用够多"的条目锁成 `locked`。锁上之后，
        `_clarity_of_row()` 会直接返回它自己的档位（不再随时间降），
        而 `compress()` 的条件里写着 `not locked` —— 于是**重要的事既不会被降级、也不会被压缩**。
        这正是这两个机制文档里承诺的「被引用多的记忆锁定为高清（重要的事不该随时间变模糊）」。
      · **再降级**：按时间把**没锁**的那些往下调。
      · **最后压缩**：把 180 天以上、**没锁**的压成印象。

    ⚠️ 原来的顺序是"降级 → 压缩 → 巩固"，**那是错的**：同一轮里，
    一条 200 天、被引用过 5 次的重要条目会**先被压缩成印象**，
    之后才轮到巩固给它上锁 —— 锁上也没用了，细节已经被压掉。
    是写"接入前后对比"时看见"重要条目变成了印象"才发现的，已改正；
    `tools/test_memory_upkeep.py` 里专门钉了"重要且久远的那条必须活着且没被压"。

    每一步**独立成败**：某一步炸了就如实记进 `errors`，其余照跑。
    返回报告 dict（全是真的数字，没有就写 0）。
    """
    t0 = time.time()
    now = time.time() if now is None else float(now)
    rep = {"ts": now, "at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
           "apply": bool(apply), "degrade": None, "compress": None, "consolidate": None,
           "errors": [], "ms": 0}
    if not apply:
        # 推演模式：只算不写（自测与"想先看看会发生什么"时用）
        for name, fn in (("consolidate", lambda: {"count": 0, "locked": [],
                                                  "note": "推演不锁（锁定会写盘）"}),
                         ("degrade", lambda: MD.degrade(now=now, apply=False)),
                         ("compress", lambda: MD.compress(now=now, rows=MD._all_rows()))):
            try:
                rep[name] = fn()
            except Exception as e:
                rep["errors"].append("%s: %s" % (name, e))
        rep["ms"] = int((time.time() - t0) * 1000)
        return rep
    try:
        rep["consolidate"] = MD.consolidate(now=now)
    except Exception as e:
        rep["errors"].append("consolidate: %s" % e)
    try:
        rep["degrade"] = MD.degrade(now=now)
    except Exception as e:
        rep["errors"].append("degrade: %s" % e)
    try:
        rep["compress"] = MD.compress(now=now)
    except Exception as e:
        rep["errors"].append("compress: %s" % e)
    rep["ms"] = int((time.time() - t0) * 1000)
    rep["scanned"] = (rep["degrade"] or {}).get("scanned", 0)
    rep["degraded"] = len((rep["degrade"] or {}).get("changed") or [])
    rep["compressed"] = (rep["compress"] or {}).get("compressed", 0)
    rep["locked"] = (rep["consolidate"] or {}).get("count", 0)
    return rep


def _summarize(rep):
    return ("记忆保养：扫 %s 条 ｜ 降级 %s ｜ 压缩 %s ｜ 锁定 %s ｜ %sms%s"
            % (rep.get("scanned"), rep.get("degraded"), rep.get("compressed"),
               rep.get("locked"), rep.get("ms"),
               ("" if not rep.get("errors") else " ｜ ⚠️ 失败：" + "；".join(rep["errors"]))))


def run_once(apply=True, now=None):
    """保养一轮 + 落报告 + 打日志（后台循环与手动触发都走这里）。"""
    rep = maintain(now=now, apply=apply)
    with _lock:
        _state["runs"] = int(_state["runs"]) + 1
        _state["last"] = rep
        _state["last_at"] = time.time()
        _state["last_error"] = "；".join(rep.get("errors") or [])
    _append_report(rep)
    _log("%s", _summarize(rep))
    if rep.get("errors"):
        _log("记忆保养有步骤失败（其余步骤照常跑完）：%s", "；".join(rep["errors"]))
    return rep


# ------------------------------------------------------------------ ③ 后台循环
def _loop(interval, delay):
    stop = _state["stop"]
    if delay > 0 and stop.wait(delay):
        return
    while not stop.is_set():
        try:
            run_once(apply=True)
        except Exception as e:      # noqa: silent-ok — 一轮炸了不能把循环带走
            with _lock:
                _state["last_error"] = "循环异常: %s" % e
            _log("记忆保养循环异常（继续下一轮）：%s", e)
        if stop.wait(interval):
            break


def start(interval_s=None, delay_s=None):
    """起后台保养线程（**幂等**：已经在跑就直接返回当前状态，不会起第二条）。"""
    with _lock:
        th = _state["thread"]
        if th is not None and th.is_alive():
            return {"started": False, "why": "已经在跑", "interval": _state["interval"]}
        interval = float(interval_s if interval_s is not None else INTERVAL_DEFAULT)
        delay = float(delay_s if delay_s is not None else BOOT_DELAY_DEFAULT)
        # 参数兜底：间隔太短会把磁盘打满（整库重写），这里给一条下限
        interval = max(60.0, interval)
        _state["interval"] = interval
        _state["stop"] = threading.Event()
        _state["thread"] = threading.Thread(
            target=_loop, args=(interval, max(0.0, delay)),
            name="xj-memory-upkeep", daemon=True)
        _state["thread"].start()
    _log("记忆保养已启动：每 %.0f 分钟一轮，启动后先等 %.0f 秒", interval / 60.0, delay)
    return {"started": True, "interval": interval, "delay": delay}


def stop(timeout=5.0):
    """停掉后台保养线程（幂等）。"""
    with _lock:
        th, ev = _state["thread"], _state["stop"]
        _state["thread"] = None
    if ev is not None:
        ev.set()
    if th is not None and th.is_alive():
        th.join(timeout=timeout)
    return {"stopped": True}


def status():
    """给界面/自检看的真实状态（没跑过就如实说没跑过，不编）。"""
    with _lock:
        th = _state["thread"]
        last = _state["last"]
        return {
            "running": bool(th is not None and th.is_alive()),
            "interval_s": _state["interval"],
            "runs": int(_state["runs"]),
            "last_at": float(_state["last_at"] or 0),
            "last_age_s": (time.time() - float(_state["last_at"])) if _state["last_at"] else None,
            "last": last,
            "last_error": _state["last_error"],
            "note_runs": int(_state["note_runs"]),
            "noted_rows": int(_state["noted_rows"]),
            "report_path": _REPORT,
            "report_exists": os.path.exists(_REPORT),
        }


def config(cap):
    """从控制文件的 capabilities 里读保养开关（缺省：开、30 分钟一轮）。"""
    cap = cap or {}
    return {"on": bool(cap.get("memory_upkeep", True)),
            "interval_s": float(cap.get("memory_upkeep_interval_s", INTERVAL_DEFAULT) or INTERVAL_DEFAULT)}
