# -*- coding: utf-8 -*-
"""小焦 · 闭环流量表（给「兴趣积累闭环」装一个流水表）

【为什么要有这个】
    「闭环 · 兴趣积累与精准回答」那条链（载体给事实 → 模型判断要不要记 → 载体写画像 →
    下次作为事实注入）**机制是通的，但会不会空转，以前没有任何地方看得见**。
    2026-09-17 实测就是这么发现的：翻一整天的日志才数出来 —— 判断 88 次里「不记」65 次、
    「要记」8 次全是同一句（还是测试流量），68 次注入**从头到尾都是同样 3 条**。
    环在转，里面没有东西流动，而且**它不会报错**。

【这个模块只做一件事】把闭环的三个数按天记下来，并在每一轮顺带报一句：
    · 判了要记几条 / 不记几条（第三步）
    · 注入了几轮 / 几条 / **不同几条**（第四步）
    · 画像库当天新增几条（真正落库的）
    「不同几条」是关键：它一直是 3，就说明**没有新信息进来**（空转）。

【纪律】
    · 只追加写盘（`logs/psyche/profile_loop.jsonl`），不改任何别的库；
    · **绝不抛异常**：任何一步出错都吞掉并返回空串 —— 流量表坏掉不该让对话坏掉；
    · 只记**判断结果与短文本**，不记整轮对话（要查原文去 chat_history）。

运行：
    python core/profile_loop_meter.py                # 看今天 + 最近 7 天的表
    python core/profile_loop_meter.py --backfill     # 从 logs/xiaojiao.log 回填今天已有的事件（幂等）
    python core/profile_loop_meter.py --selftest     # 离线自测（写临时文件，不动真库）
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time

__all__ = ["note_judge", "note_inject", "summary", "summary_line", "backfill_from_log", "path"]

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 把仓库根放进 sys.path：这个模块会以 `core.profile_loop_meter`（应用里）和
# `python core/profile_loop_meter.py`（命令行）两种方式进来，后者的 sys.path[0] 是 core/，
# 那时 `from core import user_profile` 会 ImportError —— 实测踩到过：表里「画像库新增」
# 一直显示"读不到"，而真相只是路径没设。**两种入口都必须能读库**，所以这里补一次。
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_DIR = os.path.join(_ROOT, "logs", "psyche")
_PATH = os.path.join(_DIR, "profile_loop.jsonl")
_LOG = os.path.join(_ROOT, "logs", "xiaojiao.log")
_LOCK = threading.RLock()
_LAST_LINE_AT = [0.0]          # 上一句汇总日志的时间（节流用；用 list 是为了不改全局声明）
_GAP_S = 60.0                  # 至少隔 60 秒才再报一句，免得日志被刷


def path():
    return _PATH


def _today(ts=None):
    return time.strftime("%Y-%m-%d", time.localtime(ts if ts else time.time()))


def _append(ev):
    """只追加写盘。任何异常都不许冒出去。"""
    try:
        with _LOCK:
            os.makedirs(_DIR, exist_ok=True)
            with open(_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    except Exception:      # noqa: silent-ok — 流量表坏掉不能让对话坏掉
        pass


def note_judge(remember, text="", why="", src="live"):
    """第三步（模型判断要不要记）记一笔。返回该不该报汇总（给调用方决定要不要打日志）。"""
    try:
        _append({"t": time.time(), "d": _today(), "k": "judge",
                 "yes": bool(remember), "text": str(text or "")[:60],
                 "why": str(why or "")[:60], "src": src})
    except Exception:      # noqa: silent-ok
        pass
    return summary_line()


def note_inject(n, texts=None, src="live"):
    """第四步（注入 system 几条）记一笔。`n=0` 也要记 —— 空注入同样是事实。"""
    try:
        _append({"t": time.time(), "d": _today(), "k": "inject", "n": int(n or 0),
                 "texts": [str(t or "")[:60] for t in (texts or [])][:8], "src": src})
    except Exception:      # noqa: silent-ok
        pass
    return summary_line()


def _rows(day=None):
    day = day or _today()
    out = []
    try:
        if not os.path.exists(_PATH):
            return out
        with open(_PATH, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:      # noqa: silent-ok — 坏行跳过
                    continue
                if r.get("d") == day and r.get("k") in ("judge", "inject"):
                    out.append(r)
    except Exception:      # noqa: silent-ok
        pass
    return out


def _new_records_today(day=None):
    """画像库当天真正新增几条（排除迁移进来的与测试流量）。"""
    day = day or _today()
    try:
        from core import user_profile as up
        n = 0
        for r in up.all_records():
            src = str(r.get("source") or "")
            if "迁移" in src or src == "测试":
                continue
            if _today(float(r.get("ts") or 0)) == day:
                n += 1
        return n
    except Exception:      # noqa: silent-ok
        return -1                  # -1 = 读不到（如实标，不假装是 0）


def summary(day=None):
    """当天的闭环三个数。返回 dict（字段名见下）。"""
    day = day or _today()
    rows = _rows(day)
    yes = sum(1 for r in rows if r.get("k") == "judge" and r.get("yes"))
    no = sum(1 for r in rows if r.get("k") == "judge" and not r.get("yes"))
    inj = [r for r in rows if r.get("k") == "inject"]
    items = sum(int(r.get("n") or 0) for r in inj)
    texts = set()
    for r in inj:
        for t in (r.get("texts") or []):
            if t:
                texts.add(t)
    yes_texts = {str(r.get("text") or "") for r in rows
                 if r.get("k") == "judge" and r.get("yes") and r.get("text")}
    return {"day": day, "judge_yes": yes, "judge_no": no, "judge_total": yes + no,
            "inject_turns": len(inj), "inject_items": items,
            "inject_distinct": len(texts), "judge_yes_distinct": len(yes_texts),
            "new_records": _new_records_today(day)}


def summary_line(force=False, day=None):
    """一句话汇总（空转时带出来）。调用方打了它才有日志 —— 本模块自己不打日志。"""
    try:
        now = time.time()
        if not force and now - _LAST_LINE_AT[0] < _GAP_S:
            return ""
        _LAST_LINE_AT[0] = now
        s = summary(day)
        tail = ""
        # 空转的三个特征，直接写在日志里 —— 不用等人去翻
        if s["judge_total"] >= 10 and s["judge_yes"] == 0:
            tail += "｜⚠️ 今天还没有一条「要记」：环在空转"
        if s["judge_yes"] >= 5 and s["judge_yes_distinct"] <= 1:
            # ⚠️ 这条是 2026-09-17 实测**补出来的**：那天判断 73 次、「要记」8 条，
            #    看着不像空转 —— 但 8 条**全是同一句**（测试流量反复喂「我 25 岁」）。
            #    只看"要记=0"会漏掉这种"账面上有、实际没有新东西"的空转。
            tail += "｜⚠️ 「要记」的全是同一条（%d 种）：没有新的可积累信息" % s["judge_yes_distinct"]
        if s["inject_turns"] >= 10 and s["inject_distinct"] <= 3:
            tail += "｜⚠️ 注入一直是那 %d 种：没有新信息进来" % s["inject_distinct"]
        return ("闭环流量·%s：判了 %d（要记 %d / 不记 %d）｜注入 %d 轮 / %d 条 / 不同 %d 种"
                "｜画像库新增 %s 条%s"
                % (s["day"], s["judge_total"], s["judge_yes"], s["judge_no"],
                   s["inject_turns"], s["inject_items"], s["inject_distinct"],
                   ("读不到" if s["new_records"] < 0 else s["new_records"]), tail))
    except Exception:      # noqa: silent-ok — 报不出来就不报，绝不抛
        return ""


# ---------------------------------------------------------------- 从历史日志回填
def backfill_from_log(day=None, log_path=None):
    """把 `logs/xiaojiao.log` 里**已经发生**的闭环事件补进流量表（幂等：同一天只补一次）。

    为什么要有：流量表是今天才装的，装之前的账（比如 09-17 那 88 次判断 / 68 次注入）
    已经在 app 日志里了。回填进来的事件标 `src=回填自日志`，**和实时事件分得开**。
    """
    day = day or _today()
    log_path = log_path or _LOG
    if not os.path.exists(log_path):
        return {"ok": False, "why": "日志不存在", "judged": 0, "injected": 0}
    with _LOCK:
        if any(r.get("k") == "backfill_done" and r.get("d") == day for r in _all_rows_raw()):
            return {"ok": True, "why": "今天已经回填过（幂等）", "judged": 0, "injected": 0}
    judged = injected = 0
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except Exception as e:      # noqa: silent-ok
        return {"ok": False, "why": "读日志失败：%s" % e, "judged": 0, "injected": 0}
    for line in lines:
        # 只认这一天的行：日志前缀形如 [2026-09-17 23:16:36]
        if not line.startswith("[%s" % day):
            continue
        try:
            if "用户画像：" in line and "它自己判断不记" in line:
                _append({"t": _ts_of(line), "d": day, "k": "judge", "yes": False,
                         "text": "", "why": _cut(line, "原因："), "src": "回填自日志"})
                judged += 1
            elif "用户画像：" in line and "它自己判断要记" in line:
                _append({"t": _ts_of(line), "d": day, "k": "judge", "yes": True,
                         "text": _cut(line, "content="), "why": "", "src": "回填自日志"})
                judged += 1
            elif "画像召回：合并" in line and "已注入 system" in line:
                n = _n_after(line, "去重后 ")
                # ⚠️ 这一行里**只有一个** `｜`（在「已注入 system」后面），第一版写成
                #    `count("｜") >= 2` 才取，于是正文永远解析成空 —— 「注入不同几种」
                #    被算成 0。而那个数字正是看空转的关键。自测当场抓到，已改成"取第一个 ｜ 之后"。
                body = line.split("｜", 1)[1] if "｜" in line else ""
                _append({"t": _ts_of(line), "d": day, "k": "inject", "n": n,
                         "texts": [x.strip() for x in body.split("／") if x.strip()],
                         "src": "回填自日志"})
                injected += 1
            elif "画像召回：空" in line:
                _append({"t": _ts_of(line), "d": day, "k": "inject", "n": 0, "texts": [],
                         "src": "回填自日志"})
                injected += 1
        except Exception:      # noqa: silent-ok — 单行解析失败就跳过
            continue
    _append({"t": time.time(), "d": day, "k": "backfill_done", "judged": judged,
             "injected": injected})
    return {"ok": True, "why": "", "judged": judged, "injected": injected}


def _all_rows_raw():
    out = []
    try:
        with open(_PATH, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:      # noqa: silent-ok
                    continue
    except Exception:      # noqa: silent-ok
        pass
    return out


def _ts_of(line):
    """从 `[2026-09-17 23:16:36]` 里取时间戳（取不到就用现在）。"""
    try:
        return time.mktime(time.strptime(line[1:20], "%Y-%m-%d %H:%M:%S"))
    except Exception:      # noqa: silent-ok
        return time.time()


def _cut(line, key):
    try:
        if key not in line:
            return ""
        s = line.split(key, 1)[1]
        for stop in ("｜", "）", "\n"):
            s = s.split(stop)[0]
        return s.strip().strip("'\"")[:60]
    except Exception:      # noqa: silent-ok
        return ""


def _n_after(line, key):
    try:
        s = line.split(key, 1)[1]
        n = ""
        for ch in s:
            if ch.isdigit():
                n += ch
            else:
                break
        return int(n or 0)
    except Exception:      # noqa: silent-ok
        return 0


# ---------------------------------------------------------------- 入口
def _print_table(days=7):
    print("=" * 74)
    print("闭环流量表（载体给事实 → 模型判断要不要记 → 载体写画像 → 下次注入）")
    print("=" * 74)
    print("  %-12s %-14s %-22s %-16s %s" % ("日期", "判断(要记/不记)", "注入(轮/条/不同)",
                                            "画像库新增", "备注"))
    today = time.time()
    for i in range(days):
        d = _today(today - i * 86400)
        s = summary(d)
        if s["judge_total"] == 0 and s["inject_turns"] == 0 and s["new_records"] <= 0:
            if i > 0:
                continue
        note = ""
        if s["judge_total"] >= 10 and s["judge_yes"] == 0:
            note += "环在空转 "
        if s["judge_yes"] >= 5 and s["judge_yes_distinct"] <= 1:
            note += "要记的全同一条 "
        if s["inject_turns"] >= 10 and s["inject_distinct"] <= 3:
            note += "注入无新内容"
        print("  %-12s %-14s %-22s %-16s %s"
              % (d, "%d / %d" % (s["judge_yes"], s["judge_no"]),
                 "%d / %d / %d" % (s["inject_turns"], s["inject_items"], s["inject_distinct"]),
                 ("读不到" if s["new_records"] < 0 else s["new_records"]), note))
    print("=" * 74)
    print("  怎么看：**「不同」一直是 3 这种小数字 = 没有新信息进来**；")
    print("           **判断行 10 次以上而「要记」是 0 = 环在空转**。")
    print("=" * 74)


def _selftest():
    """离线自测：写临时文件，**不动真库**。返回 0 = 全过。

    ⚠️ 断言一律按**增量**算（先记下 before，再比 after）——
       第一版写成绝对值，前面几步的账把后面的期望弄错了，自测当场抓到。
    """
    import tempfile
    global _PATH, _LOG
    real, real_log = _PATH, _LOG
    _PATH = os.path.join(tempfile.gettempdir(), "_plm_selftest.jsonl")
    _LOG = os.path.join(tempfile.gettempdir(), "_plm_selftest.log")
    if os.path.exists(_PATH):
        os.remove(_PATH)
    ok = []
    DAY = "2000-01-01"          # 回填用一个人造日期，免得和"今天"的账混在一起
    _LAST_LINE_AT[0] = 0
    try:
        # ① 记一笔判断（不记）→ 汇总里 judge_no +1
        s1 = note_judge(False, why="模型说不记")
        d = summary()
        ok.append(("不记能记上账", d["judge_no"] == 1 and d["judge_yes"] == 0, d))
        ok.append(("汇总行长得对", s1.startswith("闭环流量·") and "不记 1" in s1, s1))
        # ② 节流：紧接着再记一笔，**不该**再报一句话
        s2 = note_judge(True, text="用户关注 NBA")
        ok.append(("60 秒内不重复刷日志", s2 == "", repr(s2)))
        # ③ 注入记账 + 「不同几条」
        note_inject(3, ["A", "B", "C"])
        note_inject(3, ["A", "B", "C"])
        d2 = summary()
        ok.append(("注入两轮共 6 条", d2["inject_turns"] == 2 and d2["inject_items"] == 6, d2))
        ok.append(("不同几条 = 3（不是 6）", d2["inject_distinct"] == 3, d2["inject_distinct"]))
        ok.append(("要记 / 不记分得开", d2["judge_yes"] == 1 and d2["judge_no"] == 1, d2))
        # ④ 注入一直是那 3 种 → 汇总行必须点出来（这一条是真的空转特征）
        for _ in range(9):
            note_inject(3, ["A", "B", "C"])
        _LAST_LINE_AT[0] = 0
        s4 = summary_line(force=True)
        ok.append(("注入没有新内容会被点出来", "没有新信息进来" in s4, s4))
        # ⑤ 空转告警：拿**人造的那一天**做（10 次判断、0 次要记）—— 真日志格式
        with open(_LOG, "w", encoding="utf-8") as f:
            for i in range(10):
                f.write("[%s 10:00:%02d] INFO xiaojiao.xiaojiao_app: 用户画像：**它自己判断不记**"
                        "（原因：模型说不记）｜原始输出 ''\n" % (DAY, i))
        rb = backfill_from_log(day=DAY)
        ok.append(("回填：10 次判断", rb["ok"] and rb["judged"] == 10, rb))
        sb = summary_line(force=True, day=DAY)
        ok.append(("空转能被一句话看出来", "环在空转" in sb, sb))
        # ⑤之二 「要记」全是同一条 —— 这条判据是 2026-09-17 实测补的（账面上有、实际没有新东西）
        with open(_LOG, "w", encoding="utf-8") as f:
            for i in range(5):
                f.write("[2000-01-05 10:00:%02d] INFO xiaojiao: 用户画像：**它自己判断要记**"
                        " → 已写入｜kind=事实｜content=用户 25 岁｜why=基本事实\n" % i)
        backfill_from_log(day="2000-01-05")
        s5 = summary_line(force=True, day="2000-01-05")
        ok.append(("「要记」全是同一条会被点出来", "全是一条" in s5 or "同一条" in s5, s5))
        ok.append(("那一天的要记条数与种数对得上",
                   summary("2000-01-05")["judge_yes"] == 5
                   and summary("2000-01-05")["judge_yes_distinct"] == 1, summary("2000-01-05")))
        # ⑥ 回填的另外两种行：要记 / 注入（按增量算）
        before = summary(DAY)
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write("[%s 10:01:00] INFO xiaojiao.xiaojiao_app: 用户画像：**它自己判断要记**"
                    " → 已写入｜kind=兴趣｜content=用户关注 NBA｜why=主动问了湖人\n" % DAY)
            f.write("[%s 10:01:01] INFO xiaojiao.xiaojiao_app: 画像召回：合并 1+5 → 去重后 3 条"
                    " → 已注入 system｜甲 ／ 乙 ／ 丙\n" % DAY)
            f.write("[%s 10:01:02] INFO xiaojiao.xiaojiao_app: 画像召回：空（血管 0 条 + 画像系统 5 条，"
                    "去重后 0 条）\n" % DAY)
        # 回填是幂等的，所以换个日子名再补一次（同一天只补一次是**故意**的）
        r2 = backfill_from_log(day=DAY)
        ok.append(("回填幂等：同一天不重复补", r2["why"] == "今天已经回填过（幂等）", r2))
        rb2 = backfill_from_log(day="2000-01-02")   # 这份日志里没有 01-02 的行 → 补 0 笔
        ok.append(("没有该日期的行时补 0 笔", rb2["ok"] and rb2["judged"] == 0
                   and rb2["injected"] == 0, rb2))
        # 换一天真正补一次，验证三种行的解析
        with open(_LOG, "w", encoding="utf-8") as f:
            f.write("[2000-01-03 10:00:00] INFO xiaojiao: 用户画像：**它自己判断要记**"
                    " → 已写入｜kind=兴趣｜content=用户关注 NBA｜why=主动问了湖人\n")
            f.write("[2000-01-03 10:00:01] INFO xiaojiao: 画像召回：合并 1+5 → 去重后 3 条"
                    " → 已注入 system｜甲 ／ 乙 ／ 丙\n")
            f.write("[2000-01-03 10:00:02] INFO xiaojiao: 画像召回：空（血管 0 条 + 画像系统 5 条，"
                    "去重后 0 条）\n")
        r3 = backfill_from_log(day="2000-01-03")
        d3 = summary("2000-01-03")
        ok.append(("回填：要记 1 笔 / 注入 2 轮 / 不同 3 种",
                   r3["judged"] == 1 and r3["injected"] == 2 and d3["judge_yes"] == 1
                   and d3["inject_turns"] == 2 and d3["inject_distinct"] == 3, (r3, d3)))
        ok.append(("回填的正文解析对了（不是空串）",
                   "用户关注 NBA" in json.dumps(_rows("2000-01-03"), ensure_ascii=False),
                   _rows("2000-01-03")[:1]))
        ok.append(("前一天的账没被后来的回填改掉", summary(DAY)["judge_total"] == before["judge_total"],
                   summary(DAY)["judge_total"]))
        # ⑦ 坏行不许把整份表带崩
        with open(_PATH, "a", encoding="utf-8") as f:
            f.write("{这不是 json\n\n")
        ok.append(("坏行跳过、不崩", summary()["judge_total"] >= 2, summary()["judge_total"]))
        # ⑧ 画像库读不到两种情形分得开：
        #    a) 库文件不存在 → 0（如实：没有新增），**不抛**
        from core import user_profile as _up
        _real = (_up._PATH, _up._DIR)
        _up._PATH = os.path.join(tempfile.gettempdir(), "_plm_nope", "x.jsonl")
        _up._DIR = os.path.dirname(_up._PATH)
        got_missing = summary()["new_records"]
        ok.append(("库文件不存在 → 0（不是 -1、也不抛）", got_missing == 0, got_missing))
        #    b) 库**读的时候抛异常** → -1（如实标"读不到"），不许当成 0
        #       （第一版想用 `sys.modules[...] = None` 让 import 失败，实测**不管用**：
        #        `from core import user_profile` 走了父包上的属性，拿回的还是真模块 → 得到 0。
        #        改成把 `all_records` 换成会抛的函数，真正打到那个 except 分支。）
        _real_fn = _up.all_records
        _up.all_records = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            got_broken = summary()["new_records"]
        finally:
            _up.all_records = _real_fn
            _up._PATH, _up._DIR = _real
        ok.append(("库读取抛异常 → -1（如实标「读不到」）", got_broken == -1, got_broken))
        # ⑨ 今天真的库能读到（不是永远 -1）
        ok.append(("现在读真库不报「读不到」", summary()["new_records"] >= 0, summary()["new_records"]))
        # ⑩ **写不进去的时候，一句话都不许抛**（它是仪表，坏掉不能让对话坏掉）
        #    造法：把落盘路径指到"父目录是一个文件"的地方 → makedirs 必然失败。
        _save_path = _PATH
        _PATH = os.path.join(_LOG, "不可能", "x.jsonl")     # _LOG 是个文件，不是目录
        _raised = ""
        try:
            l1 = note_judge(False, why="写不进去")
            l2 = note_inject(3, ["a", "b", "c"])
            s = summary()
        except Exception as e:      # 真抛了就证明这一条没做到
            _raised = repr(e)
            l1 = l2 = ""
            s = {}
        finally:
            _PATH = _save_path
        ok.append(("落盘失败时不抛异常", _raised == "", _raised))
        ok.append(("落盘失败时该返回的都返回（空串/零账）",
                   l1 == "" and l2 == "" and s.get("judge_total") == 0 and s.get("inject_items") == 0,
                   (l1, l2, s)))
        # ⑪ 恢复落盘之后还能继续记（不是"坏一次就永久哑了"）
        note_judge(True, text="恢复之后")
        ok.append(("恢复后可继续记账",
                   summary()["judge_yes"] >= 1 and summary()["judge_total"] >= 1, summary()))
    finally:
        try:
            if os.path.exists(_PATH):
                os.remove(_PATH)
            if os.path.exists(_LOG):
                os.remove(_LOG)
        except Exception:      # noqa: silent-ok
            pass
        _PATH, _LOG = real, real_log
    bad = [n for n, c, _ in ok if not c]
    for n, c, info in ok:
        print("  %s %s%s" % ("✅" if c else "❌", n, ("  ← " + str(info)[:130]) if not c else ""))
    print("-" * 74)
    print("闭环流量表自测：通过 %d / 共 %d" % (len(ok) - len(bad), len(ok)))
    return 1 if bad else 0


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    if "--backfill" in sys.argv:
        r = backfill_from_log()
        print("回填：%s（判断 %d 笔 / 注入 %d 笔）" % (r["why"] or "完成", r["judged"], r["injected"]))
    _print_table()
