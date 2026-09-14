# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 自主观察者（自主 1：一直盯着，不是盯一次）

它解决什么问题
--------------
用户说「帮我盯着这个页面，一有新版就告诉我」—— 关键在于"**一直盯**"。
一次性抓取谁都会（那是工具），难的是"记住上一次看到的是什么、下一次比对出差异、
然后主动开口"。这三件事都是载体的活，跟用哪个模型一点关系都没有。

去掉它会怎样：小焦只能"抓一次给你看"。用户得自己每天来问一遍 —— 那就还是工具，不是存在。

四种变化判定（rule）
--------------------
  changed              内容哈希变了 → 记一条（默认；第一次看到记 first_seen）
  any                  每次抓到都算一条（用户就是要"每次都汇报"）
  contains:关键词       新出现了这个词 → 记一条（词消失后重置，下次再出现还能报）
  regex:正则            正则从不匹配变成匹配 → 记一条
不认识（写错的）rule → **按 changed 处理并记 warning**：用户写错一个规则，
不该导致"这个盯梢彻底不工作而且没有任何提示"。宁可行为保守（changed）也不要静默失效。

两条必须守住的诚实
------------------
  ① **抓失败不算变化**。把"网络不通"记成"页面变了"，是后台功能最恶劣的谎 ——
     用户会立刻去检查一个根本没变的页面，然后不再信任任何通知。
     失败只更新 last_status，并往 `watch_errors.jsonl` 记一条。
  ② 每次抓取的结果都要更新状态（哪怕没变化）：`watchers_state.json` 里的
     `at/status/len` 是用户判断"它到底还在不在盯"的唯一凭据。
"""
import hashlib
import json
import os
import re
import threading
import time

from . import _append_jsonl, _app_module, _cfg, _log, _resp_text, _state_dir

_FETCH_TIMEOUT = 8                  # **必须带超时**：盯梢线程绝不能悬在网络 IO 上
_MIN_INTERVAL = 1.0                 # 最小间隔 1 秒（自测要能飞快地跑好几轮）
_HEAD = 160                         # 变化记录里留的"内容开头"长度（给人看"变了哪儿"的线索）
_RULES = ("changed", "any")


def content_hash(text):
    """内容指纹（sha1 十六进制）。用哈希而不是原文比对：状态文件要保持很小。"""
    h = hashlib.sha1()
    h.update((text or "").encode("utf-8", "replace"))
    return h.hexdigest()


def _normalize(text):
    """归一化：把连续空白压成一个空格再去哈希。

    为什么必须归一：很多站点每次请求都会在时间戳/随机 token/空白排版上抖一下。
    不归一的话，`changed` 规则会**每次都报"变了"**，用户一天收到一百条"页面变了" ——
    比不盯还糟。压掉空白是对"内容真的变了"最保守、最不容易误报的一步。
    去掉它会怎样：上面那条噪音地狱。
    """
    return re.sub(r"\s+", " ", text or "").strip()


def _default_fetcher(url):
    """默认抓取：优先借宿主**只读**的抓取函数，其次 requests（8 秒超时），最后 urllib。

    为什么不走宿主的工具层（`xiaojiao_app._run_tool_impl("fetch_url", ...)`）—— 两条硬理由：
      ① 它只返回前 2500 字（给模型看够用），而盯梢**靠全文哈希判变化**：
         页面在第 3000 字之后变了，我们会**看不见**（用户明确要求"盯着"的地方恰好没盯到）；
      ② 它会动全局状态（PENDING / 往界面推"待确认"提示）—— 后台线程去触发界面对话框
         是绝对不能接受的（用户会莫名其妙看到一个确认框）。
    所以这里只探"纯函数式"的抓取接口，抓不到就自己 requests 拿**完整正文**。
    任何一层失败都返回 ("", 原因) —— **绝不抛**，由调用方记成"抓取失败"。
    """
    url = str(url or "").strip()
    if not url:
        return "", "空 url"
    app = _app_module()
    if app is not None:
        for name in ("web_fetch", "tool_web_fetch", "fetch_url"):
            fn = getattr(app, name, None)
            if callable(fn):
                try:
                    r = fn(url)
                    text = r if isinstance(r, str) else str(r or "")
                    if text.strip():
                        return text, ""
                except Exception:      # noqa: silent-ok — 宿主抓取失败就往下走自己的实现
                    break
    err = ""
    try:
        import requests
        r = requests.get(url, timeout=_FETCH_TIMEOUT,
                         headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        if int(getattr(r, "status_code", 0)) != 200:
            return "", "HTTP %s" % getattr(r, "status_code", "?")
        # **必须走 _resp_text，不能用 r.text**：服务端没写 charset 时（本地 http.server、
        # 不少中文站都是这样）requests 会按 ISO-8859-1 解码，中文全变乱码 ——
        # 结果是 `contains:中文关键词` 永不命中。详见 __init__._resp_text 的注释。
        return _resp_text(r), ""
    except Exception as e:
        err = "%s: %s" % (type(e).__name__, str(e)[:120])
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
            raw = resp.read()
        try:
            return raw.decode("utf-8"), ""
        except UnicodeDecodeError:
            # 中文老站常见 GBK/GB18030；换一种编码再试，最后才替换式兜底（绝不抛）
            return raw.decode("gb18030", "replace"), ""
    except Exception as e:
        return "", "%s（requests 也失败：%s）" % ("%s: %s" % (type(e).__name__, str(e)[:80]), err)


def _default_notify(rec, change, state_dir=None):
    """默认通知：写 `logs/autonomy/notifications.jsonl`（跟调度器共用一份，网页端读它）。

    单开一个文件的话，网页端要读两处才能把"小焦主动说的话"凑齐 —— 用户会以为漏了消息。
    共用一份、用 kind 区分来源，是"通知"这个概念该有的样子。
    """
    st = _state_dir(state_dir)
    _append_jsonl(os.path.join(st, "notifications.jsonl"), {
        "ts": time.time(), "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "id": "watch:%s" % (rec.get("url") or ""), "kind": "ui", "note": rec.get("note") or "",
        "title": "盯梢有变化：%s" % (rec.get("url") or ""),
        "chars": len(change.get("detail") or ""),
        "text": "%s\n规则：%s\n变化：%s\n原来：%s\n现在：%s"
                % (rec.get("url") or "", change.get("rule"),
                   change.get("detail"), change.get("old_head"), change.get("new_head")),
    })


class AutonomousWatcher:
    """盯梢管理器：登记 URL → 到期就抓 → 判定变化 → 记录 + 通知。"""

    def __init__(self, fetcher=None, notify=None, state_dir=None):
        self.fetcher = fetcher                        # (url) -> str 或 (str, err)
        self.notify = notify                          # (rec, change) -> None
        self.state_dir = _state_dir(state_dir)
        self._items = {}                              # url -> 盯梢记录
        self._lock = threading.RLock()
        self._state_path = os.path.join(self.state_dir, "watchers_state.json")
        self._state = self._load_state()              # url -> {hash, at, status, len, marks}
        self._stop = threading.Event()
        self._thread = None

    # ---------------------------------------------------------- 状态读写
    def _load_state(self):
        """读上次看到的指纹。文件坏了就当**空状态**（= 下一次抓取记 first_seen）。

        为什么坏了不抛：状态文件是"优化"，不是"真相"。丢了它的代价是"多报一次 first_seen"，
        而抛异常的代价是整个盯梢功能起不来。两者轻重一目了然。
        """
        try:
            with open(self._state_path, "r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:      # noqa: silent-ok — 没有/坏了的状态文件等价于"第一次运行"
            return {}

    def _save_state(self):
        """原子落盘：先写 .tmp 再 os.replace。**绝不删除任何文件**。

        为什么用 replace 而不是直接覆盖：写到一半被 kill 会留下半截 JSON，
        下次启动就"状态全丢"。os.replace 是原子的 —— 要么旧的、要么新的，没有中间态。
        （注意：这里不需要"删除旧文件"，replace 本身就是覆盖语义。）
        """
        try:
            os.makedirs(self.state_dir, exist_ok=True)
            tmp = self._state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._state, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self._state_path)
        except Exception as e:      # noqa: silent-ok — 存不下状态也只是下次多报一次 first_seen
            _log("观察者：状态落盘失败：%s" % e, os.path.join(self.state_dir, "autonomy.log"))

    # ---------------------------------------------------------- 登记 / 移除
    def add(self, url, interval=3600, rule="changed", note=""):
        """登记一个盯梢目标。返回 True/False（False 一定有日志说明原因）。"""
        url = str(url or "").strip()
        if not url.startswith(("http://", "https://")):
            _log("观察者：url 非法（必须以 http:// 或 https:// 开头）：%r" % url,
                 os.path.join(self.state_dir, "autonomy.log"))
            return False
        try:
            interval = float(interval)
        except (TypeError, ValueError):
            interval = 3600.0
        if interval < _MIN_INTERVAL:
            interval = _MIN_INTERVAL
        rule = self._check_rule(rule)
        with self._lock:
            if url in self._items:
                _log("观察者：%s 已在盯梢列表中，忽略重复登记" % url,
                     os.path.join(self.state_dir, "autonomy.log"))
                return False
            self._items[url] = {"url": url, "interval": interval, "rule": rule,
                                "note": str(note or ""), "last_check": 0.0,
                                "last_status": "", "changes": 0}
        return True

    def _check_rule(self, rule):
        """校验 rule；不认识就降级成 changed **并记 warning**（不许静默失效）。"""
        r = str(rule or "changed").strip()
        if not r:
            return "changed"
        low = r.lower()
        if low in _RULES:
            return low
        if low.startswith("contains:") and len(r) > len("contains:"):
            return r
        if low.startswith("regex:"):
            try:
                re.compile(r.split(":", 1)[1])
                return r
            except re.error as e:
                _log("观察者：regex 规则编译失败（%s），已按 changed 处理：%r" % (e, r),
                     os.path.join(self.state_dir, "autonomy.log"))
                return "changed"
        _log("观察者：无法识别的 rule（%r），已按 changed 处理" % r,
             os.path.join(self.state_dir, "autonomy.log"))
        return "changed"

    def remove(self, url):
        """移除一个盯梢目标（同时清掉它的状态，免得下次加回来误报"变了"）。"""
        with self._lock:
            ok = self._items.pop(str(url), None) is not None
            if ok:
                self._state.pop(str(url), None)
                self._save_state()
            return ok

    def list_watchers(self):
        """列出盯梢目标（带 last_check / last_status / changes）。"""
        with self._lock:
            out = []
            for rec in self._items.values():
                st = self._state.get(rec["url"]) or {}
                out.append({
                    "url": rec["url"], "interval": rec["interval"], "rule": rec["rule"],
                    "note": rec["note"], "last_check": rec.get("last_check") or 0.0,
                    "last_status": rec.get("last_status") or "",
                    "changes": int(rec.get("changes") or 0),
                    "state_at": st.get("at"), "state_len": st.get("len"),
                })
        out.sort(key=lambda x: x["url"])
        return out

    # ---------------------------------------------------------- 抓取 + 判定
    def _fetch(self, url):
        """调用 fetcher，统一成 (text, err)。支持 fetcher 返回 str 或 (str, err)。"""
        fn = self.fetcher or _default_fetcher
        try:
            r = fn(url)
        except Exception as e:      # noqa: silent-ok — fetcher 抛异常等价于"这次抓失败"
            return "", "%s: %s" % (type(e).__name__, str(e)[:120])
        if isinstance(r, tuple):
            text = r[0] if r else ""
            err = (r[1] if len(r) > 1 else "") or ""
            return str(text or ""), str(err)
        return str(r or ""), ""

    def _judge(self, rule, st, new_hash, text):
        """判定这次抓取算不算"变化" → (kind, detail)；不算就返回 ("", "")。

        contains/regex 用 `marks` 记"这个条件已经报过了吗"：
        报过就不再重复报（否则"页面上有这个关键词"会**每次抓都报一条**，用户被淹没）；
        条件消失时把标记清掉 —— 这样它下次再出现还能报（"又上架了"是用户真正关心的）。
        为什么不是"拿旧正文比对新正文"：那要把整页正文留在状态文件里（几十个 URL 就是几十 MB）。
        用一个标记位表达同样的语义，状态文件永远只有几百字节。
        """
        low = rule.lower()
        if low == "any":
            return "any", "按要求：每次抓取都记一条"
        if low.startswith("contains:"):
            word = rule.split(":", 1)[1].strip()
            key = "contains:" + word
            marks = st.setdefault("marks", {})
            if word and word in text:
                if not marks.get(key):
                    marks[key] = True
                    return "contains", "新出现关键词：%s" % word
                return "", ""
            marks[key] = False          # 关键词消失了 → 允许下次再报
            return "", ""
        if low.startswith("regex:"):
            pat = rule.split(":", 1)[1]
            key = "regex:" + pat
            marks = st.setdefault("marks", {})
            try:
                m = re.search(pat, text)
            except re.error:      # noqa: silent-ok — 规则坏了就当"没命中"，绝不让盯梢线程崩
                return "", ""
            if m:
                if not marks.get(key):
                    marks[key] = True
                    return "regex", "首次命中：%s" % m.group(0)[:80]
                return "", ""
            marks[key] = False
            return "", ""
        # 默认 changed
        old = st.get("hash")
        if not old:
            return "first_seen", "第一次看到这个页面，先记下当前内容"
        if old != new_hash:
            return "changed", "内容有变化（%s → %s）" % (str(old)[:8], str(new_hash)[:8])
        return "", ""

    def check_once(self, now=None, force=False):
        """把所有**到期**的盯梢跑一遍，返回本次的变化列表。

        `now` 可注入（自测用假时钟把"等一小时"压成"传一个数"）；
        `force=True` 忽略间隔，立刻全抓一遍（界面上"现在就检查"按钮用）。
        抓失败的 URL **不进变化列表**，只更新 last_status + 记 watch_errors.jsonl。
        """
        now = time.time() if now is None else float(now)
        changes = []
        with self._lock:
            items = list(self._items.values())
        for rec in items:
            url = rec["url"]
            with self._lock:
                st = self._state.setdefault(url, {})
            last = float(st.get("at") or 0)
            if not force and (now - last) < float(rec["interval"]):
                continue
            text, err = self._fetch(url)
            if err or not text:
                # 抓失败：**不算变化**，但要如实更新状态并单独记错误日志。
                # 用户看到 last_status=error 就知道"是没抓到"，而不是"页面没变"。
                with self._lock:
                    st.update({"at": now, "status": "error:%s" % (err or "空内容")[:120],
                               "last_error": err or "空内容"})
                    rec["last_check"] = now
                    rec["last_status"] = "error"
                _append_jsonl(os.path.join(self.state_dir, "watch_errors.jsonl"), {
                    "ts": now, "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
                    "url": url, "error": (err or "空内容")[:200],
                })
                continue
            body = _normalize(text)
            new_hash = content_hash(body)
            with self._lock:
                # 注意：_judge 必须在 st.update() **之前**调用 —— 它要读的是"上一次的哈希"。
                old_head = st.get("head") or ""
                kind, detail = self._judge(rec["rule"], st, new_hash, body)
                st.update({"hash": new_hash, "at": now, "status": "ok", "len": len(body),
                           "head": body[:_HEAD]})
                rec["last_check"] = now
                rec["last_status"] = "ok"
                if kind:
                    rec["changes"] = int(rec.get("changes") or 0) + 1
            if not kind:
                continue
            change = {"ts": now, "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
                      "url": url, "rule": rec["rule"], "kind": kind, "detail": detail,
                      "old_head": (old_head or "")[:_HEAD], "new_head": body[:_HEAD]}
            changes.append(change)
            _append_jsonl(os.path.join(self.state_dir, "changes.jsonl"), change)
            try:
                if self.notify:
                    self.notify(rec, change)
                else:
                    _default_notify(rec, change, self.state_dir)
            except Exception as e:      # noqa: silent-ok — 通知失败不能影响盯梢本身
                _log("观察者：通知失败（%s）：%s" % (url, e),
                     os.path.join(self.state_dir, "autonomy.log"))
        with self._lock:
            self._save_state()
        return changes

    # ---------------------------------------------------------- 生命周期
    def start(self, poll_s=60):
        """起后台盯梢线程（daemon）。已在跑返回 False（幂等：两条线程会抓两遍）。"""
        try:
            poll_s = max(1.0, float(poll_s))
        except (TypeError, ValueError):
            poll_s = 60.0
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, args=(poll_s,),
                                            name="autonomy-watcher", daemon=True)
            self._thread.start()
            return True

    def _loop(self, poll_s):
        """盯梢循环：每 `poll_s` 秒问一次"有谁到期了"。

        为什么是"问到期"而不是"每个 URL 一条定时器"：URL 数量是用户写配置时定的，
        可能 1 个也可能 50 个。统一一个循环判断"谁到期了"，比 50 条线程好管得多
        （线程数不随用户配置增长 —— 这是"载体要稳"的基本要求）。
        """
        while not self._stop.is_set():
            try:
                self.check_once()
            except Exception as e:      # noqa: silent-ok — 单轮失败不能让盯梢线程死掉
                _log("观察者：检查异常（已忽略继续跑）：%s" % e,
                     os.path.join(self.state_dir, "autonomy.log"))
            self._stop.wait(poll_s)

    def stop(self, timeout=3):
        """优雅停止（有界等待）。返回线程是否真的退出了。"""
        self._stop.set()
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout)
        alive = bool(t is not None and t.is_alive())
        if not alive:
            self._thread = None
        return not alive

    def is_running(self):
        """后台线程是否还活着。"""
        t = self._thread
        return bool(t is not None and t.is_alive())

    # ---------------------------------------------------------- 配置装载
    def load_from_config(self, cfg=None):
        """从 `autonomy.watchers` 装载：`[{url, interval, rule}]`。返回成功登记条数。

        坏了一条只跳过那一条 —— 用户手写 10 个盯梢目标，第 3 个 URL 少打了个 h，
        没道理让另外 9 个一起不工作。
        """
        cfg = _cfg() if cfg is None else cfg
        auto = (cfg or {}).get("autonomy") if isinstance(cfg, dict) else None
        auto = auto if isinstance(auto, dict) else {}
        items = auto.get("watchers")
        if items is None:
            items = []
        if not isinstance(items, list):
            _log("观察者：autonomy.watchers 不是数组（%s），已全部忽略" % type(items).__name__,
                 os.path.join(self.state_dir, "autonomy.log"))
            return 0
        ok_n = 0
        for it in items:
            if not isinstance(it, dict):
                _log("观察者：跳过非对象条目：%r" % (it,),
                     os.path.join(self.state_dir, "autonomy.log"))
                continue
            if self.add(it.get("url"), it.get("interval", 3600),
                        it.get("rule", "changed"), it.get("note", "")):
                ok_n += 1
        return ok_n
