# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 自主学习者（自主 1：它会自己找东西学）

它解决什么问题
--------------
用户反复聊到"向量检索"，说明这是他关心的事。一个"活着"的存在不会等用户开口说
"你去学学向量检索" —— 它会自己注意到"我们最近老提这个"，然后自己去把它搞懂、记下来。
这就是本模块的循环：**读历史 → 提炼高频话题 → 主动抓资料 → 存进长期记忆**。

去掉它会怎样：小焦永远只知道"用户明确教过它的东西"。对话里反复出现的关切
不会被它自己转化成知识，它就一直停在"你问我答"的水平上。

三个可替换的接缝（都是惰性的，宿主不在也能跑）
----------------------------------------------
  history_getter()           读对话历史 → [{"role":"用户"/"小焦","content":...}]
  fetcher(topic) -> str      去外面找这个题目的资料
  storer(topic, text) -> bool 把学到的存进长期记忆
默认实现分别是：借 `xiaojiao_app.current_messages` / 借 `xiaojiao_app.web_search`（拿不到就
用 requests 抓必应，8 秒超时）/ 借 `core.memory_vec.add_memory`（拿不到就落 JSONL）。
**每一个接缝都允许"拿不到"**，这时退化成离线模式：如实记 skipped，不崩、不假装学到了。

为什么中文分词是"字符 2~4-gram + 停用词过滤"
--------------------------------------------
要求是"不许引入新依赖"，而中文没有空格，正则切不出词。可选做法里：
  · 按标点整句当话题 → 太粗，"向量检索和抓取数据"会变成一整个"话题"，学不到点子上；
  · 上 jieba → 新依赖，且装不上就整个功能废掉；
  · **字符 n-gram**：`向量检索` 会自然产出 `向量检索`(4-gram) / `向量检`(3) / `向量`(2)…
    高频的子串自己会浮上来，再用"长词优先 + 互斥抑制"把 `向量检索` 挑出来、把
    `量检索` 这种错位碎片压下去。
去掉 n-gram 改用整句：话题会退化成"用户说过的一整句话"，抓资料时等于拿整句去搜，
召回质量崩塌（这也是 xiaojiao_app 里"检索词清洗"存在的原因）。
"""
import os
import re
import threading
import time

from . import _append_jsonl, _app_module, _log, _resp_text, _state_dir

# ============================== 停用词 / 噪声 ==============================
# 三类要剥掉的东西：① 助词代词（的/了/我/你）② 指令措辞（帮我/请问/写一个）
# ③ 口水词（那个/什么/可以）。它们频次最高，不剥掉的话"高频话题"永远是"帮我"。
#
# 为什么分成两张表（这里踩过一次，记录一下）：
#   一开始把所有停用字都当**子串**过滤，结果「向量检索」被判定成噪声 ——
#   因为里面有「向」。同理「上下文」里的「下」、「数据库/地址」里的「地」也会中招。
#   单字停用字的杀伤面太大：它几乎必然出现在**正常词汇内部**。
#   所以改成两张表：
#     _STOP_SUB   多字停用词 + 几个"绝不会出现在正常词内部"的语气助词 → 按子串判；
#     _STOP_CHARS 其余单字虚词 → 只有**整个候选全是这些字**时才判噪声（"我看"/"看看"被挡掉，
#                 "向量"/"上下文"活下来）。
#   去掉这个区分会怎样：专业技术话题被自己的字面误杀，学到的全是"帮我""这个"这类口水。
_STOP_SUB = (
    # 多字：代词 / 指示词
    "我们", "你们", "他们", "自己", "这个", "那个", "这些", "那些", "什么", "怎么",
    "怎样", "如何", "为什么", "哪些", "哪个", "多少", "时候", "现在", "已经",
    # 多字：指令 / 客套
    "帮我", "帮忙", "请问", "麻烦", "谢谢", "你好", "您好", "小焦", "给我", "替我",
    "可以", "需要", "应该", "可能", "一个", "一下", "一些", "一点", "生成", "告诉我",
    "问一下", "有没有", "是不是", "对不对", "我要", "我想",
    # 多字：连接词 / 口水
    "如果", "因为", "所以", "然后", "但是", "而且", "并且", "还是", "就是", "真的",
    "东西", "事情", "问题", "情况", "方面", "地方", "今天", "明天", "昨天", "最近",
    "目前", "一直", "感觉", "觉得",
    # 单字里的"高信号噪声"：这几个几乎不会出现在正常词汇内部，可以放心按子串判
    "的", "了", "着", "吗", "呢", "吧", "啊", "呀", "哦", "嗯", "嘛", "之", "其",
)
# 低信号单字虚词：只有"整段全是这类字"才算噪声（不然会误杀正常词，见上面的说明）
_STOP_CHARS = set(
    "我你他她它是在和与或及把被让给对从到为就都也还很太更最又而但却则此该各每些"
    "个只件条种次点间来去看说想要能会做写帮请向上下里外前后左右内过地得哈哪"
)

# 英文停用词（代码/技术对话里 the/and/for 这类会冒出来，跟中文停用词同理）
_EN_STOP = {
    "the", "and", "for", "with", "that", "this", "from", "you", "are", "was", "were",
    "have", "has", "had", "not", "but", "can", "will", "would", "should", "could",
    "http", "https", "www", "com", "org", "net", "html", "php", "asp", "index",
    "print", "true", "false", "none", "null", "var", "let", "const", "def", "self",
}

_N_GRAMS = (2, 3, 4)                    # 候选话题的字符长度区间
_MIN_COUNT = 2                          # 至少出现过 2 条消息才算"高频"（只出现一次的是噪声）
_MAX_TOPIC_LEN = 8                      # 话题长度上限（防止把半句话当话题）
_FETCH_LIMIT = 4000                     # 抓回来的资料最多留多少字（记忆库不是垃圾场）
_BING_TIMEOUT = 8                       # **必须带超时**：后台线程绝不能悬在网络 IO 上

# 中文连续段 / 英文词（英文要求 ≥3 字母：单字母和双字母基本是变量名或噪声）
_RUN = re.compile(r"[\u4e00-\u9fff]+|[A-Za-z][A-Za-z0-9_+#.\-]{2,}")
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _is_noisy(gram):
    """这段字是不是噪声（含停用词 / 全是虚词 / 全数字 / 太短）？是就丢掉。

    两段判据对应上面两张停用词表 —— 多字按子串判，单字只在"整段全是虚词"时判。
    """
    if not gram or len(gram) < 2:
        return True
    if any(w in gram for w in _STOP_SUB):
        return True
    if gram.isdigit():
        return True
    if all(ch in _STOP_CHARS for ch in gram):
        return True
    return False


def _bigrams(s):
    """字符串的字符 2-gram 集合（判两个候选话题"是不是同一件事"用的指纹）。"""
    return set(s[i:i + 2] for i in range(max(0, len(s) - 1)))


def _related(a, b):
    """a 与 b 是不是"同一个话题的不同长度写法"（用于互斥抑制）。

    判据一：一个是另一个的子串（`检索` ⊂ `向量检索`）；
    判据二：2-gram 重合度 > 0.5（`量检索` 与 `向量检索` 重合 {量检,检索}/{向量,量检,检索}=1.0）。
    为什么取 **> 0.5 而不是 ≥ 0.5**：`记忆检索` 与 `向量检索` 的重合度正好是 0.5
    （只共享"检索"），它们是**两个不同话题**，不能互相吃掉。用 ≥ 会把"记忆检索"误杀。
    """
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    ga, gb = _bigrams(a), _bigrams(b)
    if not ga or not gb:
        return False
    inter = len(ga & gb) / float(min(len(ga), len(gb)))
    return inter > 0.5


class AutonomousLearner:
    """后台自主学习者：`cycle()` 一次完整周期，`start(interval_s)` 让它定期自己跑。"""

    def __init__(self, history_getter=None, fetcher=None, storer=None, state_dir=None):
        self.history_getter = history_getter        # () -> list[dict]
        self.fetcher = fetcher                      # (topic) -> str
        self.storer = storer                        # (topic, text) -> bool
        self.state_dir = _state_dir(state_dir)
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self.rounds = 0
        self.learned_total = 0

    # ---------------------------------------------------------- ① 提炼话题
    def extract_topics(self, messages, top_n=8):
        """从对话历史里提炼高频话题 → [(话题, 次数)] 降序。

        `messages = [{"role": "用户"/"小焦", "content": "..."}]`。

        **次数 = 文档频率**：这个字串出现在**多少条**消息里（同一条消息里出现 5 次只算 1）。
        为什么这样数：话题热度看的是"我们多少轮在聊它"，而不是"某一条里它被复读了几遍"。
        用原始词频的话，小焦某次又长又水的回答（同一句话抄三遍）会把一个偶然词顶成
        头号话题 —— 那就学歪了。
        """
        counts = {}
        for text in self._texts(messages):
            seen = set()
            for run in _RUN.findall(text):
                if run[0].isascii():
                    w = run.lower()
                    if len(w) >= 3 and w not in _EN_STOP:
                        seen.add(w)
                    continue
                for n in _N_GRAMS:
                    for i in range(len(run) - n + 1):
                        g = run[i:i + n]
                        if _is_noisy(g):
                            continue
                        seen.add(g)
            for g in seen:
                counts[g] = counts.get(g, 0) + 1

        # 排序：先按热度，热度相同让**长的**排前面（"向量检索"优先于"向量"）——
        # 这样互斥抑制时，被保留的一定是信息量更大的那个写法。
        items = [(g, c) for g, c in counts.items() if c >= _MIN_COUNT and len(g) <= _MAX_TOPIC_LEN]
        items.sort(key=lambda z: (-z[1], -len(z[0]), z[0]))
        kept = []
        for g, c in items:
            # 互斥抑制：跟已选话题"是同一个东西"就丢掉（`向量`/`量检索` 都被 `向量检索` 代表）。
            # 不做这一步的话，前 8 名会全是同一个词的各种切法（向量检索/向量/量检/检索…），
            # 等于只提炼出一个话题 —— 学出来的东西高度重复，白花抓取额度。
            if any(_related(g, k) for k, _kc in kept):
                continue
            kept.append((g, c))
            if len(kept) >= max(1, int(top_n)):
                break
        return kept

    @staticmethod
    def _texts(messages):
        """把 messages 拉平成一串文本（容忍 dict / str / None 混着来）。"""
        out = []
        for m in messages or []:
            if isinstance(m, dict):
                out.append(str(m.get("content") or m.get("text") or ""))
            elif m is not None:
                out.append(str(m))
        return out

    # ---------------------------------------------------------- ② 学一轮
    def learn_once(self, topics=None):
        """抓 1~2 个话题 → 存进记忆。返回 {learned, skipped, items, reason}。

        为什么一轮只学 1~2 个：这是**后台**行为，会真的联网和调模型。
        每个周期抓 8 个话题 = 用户没开口就被花掉 8 次额度。少抓、常抓，
        既是省钱，也是"像人一样慢慢学"而不是"一次性刷完"。

        离线 / 抓不到时的行为：**如实记 skipped 并给出原因**，绝不假装学过。
        为什么必须如实：`learning.jsonl` 是"它到底学了什么"的唯一凭据。
        把失败写成成功，用户会以为小焦知道某件事，实际上是空的 —— 这比不知道更坏。
        """
        picked = list(topics or [])[:2]
        learned, skipped, items = 0, 0, []
        if not picked:
            return {"learned": 0, "skipped": 0, "items": [], "reason": "没有可用话题"}

        fetch = self.fetcher or self._default_fetcher
        store = self.storer or self._default_storer
        for item in picked:
            topic = item[0] if isinstance(item, (tuple, list)) and item else str(item)
            topic = str(topic or "").strip()
            if not topic:
                continue
            try:
                text = fetch(topic) or ""
            except Exception as e:      # noqa: silent-ok — 一次抓取失败只是"这轮没学到"
                text, _err = "", "%s: %s" % (type(e).__name__, str(e)[:120])
                _log("学习者：抓取 %r 失败：%s" % (topic, _err),
                     os.path.join(self.state_dir, "autonomy.log"))
            text = (text or "").strip()[:_FETCH_LIMIT]
            if not text:
                # 离线 / 没有结果 / 抓取超时 —— 都走这里，如实记 skipped
                skipped += 1
                items.append({"topic": topic, "ok": False, "reason": "抓取为空或无网络"})
                continue
            try:
                ok = bool(store(topic, text))
            except Exception as e:      # noqa: silent-ok — 存不进去也只是这轮没学到
                ok = False
                items.append({"topic": topic, "ok": False, "reason": "存储失败：%s" % str(e)[:100]})
                _log("学习者：存储 %r 失败：%s" % (topic, e),
                     os.path.join(self.state_dir, "autonomy.log"))
                skipped += 1
                continue
            if ok:
                learned += 1
                items.append({"topic": topic, "ok": True, "chars": len(text)})
            else:
                skipped += 1
                items.append({"topic": topic, "ok": False, "reason": "storer 返回 False"})
        return {"learned": learned, "skipped": skipped, "items": items, "reason": ""}

    # ---------------------------------------------------------- ③ 一个完整周期
    def cycle(self):
        """一次完整周期：读历史 → 提炼话题 → 学 → 落盘。返回摘要 dict。

        为什么整段包 try：这是后台线程的执行体。用户的历史文件可能正被另一个进程写、
        可能格式变了 —— 任何一种意外都不能让学习线程死掉（死了就再也不会学了，
        而且没人会发现）。异常在这里被转成一条 learning.jsonl 的 reason。
        """
        t0 = time.time()
        reason = ""
        topics = []
        res = {"learned": 0, "skipped": 0, "items": []}
        try:
            getter = self.history_getter or self._default_history
            messages = getter() or []
            topics = self.extract_topics(messages)
            res = self.learn_once(topics)
            reason = res.get("reason") or ""
        except Exception as e:
            reason = "周期异常：%s: %s" % (type(e).__name__, str(e)[:200])
            _log("学习者：周期异常：%s" % reason, os.path.join(self.state_dir, "autonomy.log"))
        with self._lock:
            self.rounds += 1
            self.learned_total += int(res.get("learned") or 0)
        summary = {
            "ts": t0, "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t0)),
            "topics": [[t, c] for t, c in topics],
            "learned": int(res.get("learned") or 0),
            "skipped": int(res.get("skipped") or 0),
            "reason": reason,
            "elapsed_s": round(time.time() - t0, 3),
            "items": res.get("items") or [],
        }
        _append_jsonl(os.path.join(self.state_dir, "learning.jsonl"), summary)
        return summary

    # ---------------------------------------------------------- 默认实现（全部惰性）
    def _default_history(self):
        """默认历史来源：借宿主的 `current_messages()`；拿不到就退回读会话 JSON 文件。

        为什么不直接读文件：宿主的会话是**内存里维护 + 定期落盘**的，直接读文件可能读到
        上一轮的状态（少几条）。借宿主的接口拿到的才是"现在正在聊的这些"。
        拿不到宿主时退回文件，是为了"单独跑这个模块"也能工作（自测就是这么跑的）。
        """
        app = _app_module()
        if app is not None and hasattr(app, "current_messages"):
            try:
                return app.current_messages() or []
            except Exception:      # noqa: silent-ok — 宿主接口挂了就退回文件
                pass
        return self._history_from_file()

    def _history_from_file(self):
        """从 `logs/../../../xiaojiao_sessions.json`（或 history.json）里捞历史消息。"""
        import json
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        for name in ("xiaojiao_sessions.json", "xiaojiao_history.json"):
            p = os.path.join(root, name)
            try:
                if not os.path.exists(p):
                    continue
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    data = json.load(f)
            except Exception:      # noqa: silent-ok — 文件坏了就当没有历史
                continue
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                if isinstance(data.get("messages"), list):
                    return data["messages"]
                out = []
                for s in data.get("sessions") or []:
                    if isinstance(s, dict) and isinstance(s.get("messages"), list):
                        out.extend(s["messages"])
                    if len(out) > 500:
                        break
                if out:
                    return out
        return []

    def _default_fetcher(self, topic):
        """默认抓取：优先借宿主的 `web_search`（它自带中文检索词清洗 + 相关度排序）；
        拿不到就自己抓必应 HTML 提纯。**任何失败都返回空串**（交给 learn_once 记 skipped）。

        为什么优先借宿主：宿主那套搜索做过"检索词清洗 + 多变体 + 相关度排序"。
        自己再写一遍必然更差（那些坑是实测踩出来的），所以能借就借。
        """
        topic = str(topic or "").strip()
        if not topic:
            return ""
        app = _app_module()
        if app is not None and hasattr(app, "web_search"):
            try:
                hits = app.web_search(topic, 5) or []
            except Exception as e:      # noqa: silent-ok — 宿主搜索挂了就走自己抓
                hits, _e = [], e
            lines = []
            for h in hits[:5]:
                try:
                    title, url, content = h[0], h[1], h[2]
                except Exception:      # noqa: silent-ok — 结果结构不认识就整条转字符串
                    title, url, content = str(h), "", ""
                lines.append("- %s（%s）：%s" % (title or "", url or "",
                                                _WS.sub(" ", str(content or ""))[:400]))
            if lines:
                return "话题：%s\n%s" % (topic, "\n".join(lines))
        return self._bing_fetch(topic)

    def _bing_fetch(self, topic):
        """自己抓必应搜索结果页并提纯成文本。**8 秒超时，失败返回空串**。

        为什么留着这条兜底：宿主不在（单独跑模块、被别的东西 import）时，
        自主学习者不该直接瘫掉。抓不到就是抓不到 —— 返回空串，让调用方如实记 skipped。
        去掉超时会怎样：必应偶尔会吊住连接，后台线程从此悬在那里不返回 ——
        学习线程再也不会跑第二轮，而且**没有任何报错**。
        """
        try:
            import requests
        except Exception:      # noqa: silent-ok — 没有 requests 就是"离线"，返回空串
            return ""
        try:
            r = requests.get("https://www.bing.com/search",
                             params={"q": topic}, timeout=_BING_TIMEOUT,
                             headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            if int(getattr(r, "status_code", 0)) != 200:
                return ""
            html = _resp_text(r)      # 不能用 r.text：没写 charset 时中文会变乱码
        except Exception:      # noqa: silent-ok — 断网/超时/被墙都是正常情况（离线自测就是）
            return ""
        text = _WS.sub(" ", _TAG.sub(" ", html)).strip()
        return text[:2000]

    def _default_storer(self, topic, text):
        """默认存储：**惰性** import `core.memory_vec.add_memory`（先读它的真实签名再用）。

        签名（已核对）：`add_memory(text, kind="dialogue", entities=None, ts=None,
        meta=None, key_text=None)`。
        这里传 `kind="fact"`（学来的知识，不是对话轮次）、`entities=[topic]`（便于按实体筛）、
        `key_text=topic`（**向量按话题算**：资料原文又长又杂，按原文算向量会把话题信号稀释掉，
        检索时就找不到它了 —— 这个坑 memory_vec 的注释里有实测记录）。
        拿不到 memory_vec 就写 `logs/autonomy/knowledge.jsonl`：功能降级但**不丢知识**。
        """
        body = ("话题：%s\n%s" % (topic, text)).strip()
        try:
            from core import memory_vec      # noqa: WPS433 — 惰性 import：拿不到就走文件兜底
        except Exception:
            memory_vec = None
        if memory_vec is not None and hasattr(memory_vec, "add_memory"):
            try:
                mid = memory_vec.add_memory(body, kind="fact", entities=[topic], key_text=topic)
                if mid:
                    return True
            except Exception as e:      # noqa: silent-ok — 记忆库写失败就退回文件，知识不能丢
                _log("学习者：写记忆库失败（改落文件）：%s" % e,
                     os.path.join(self.state_dir, "autonomy.log"))
        return _append_jsonl(os.path.join(self.state_dir, "knowledge.jsonl"), {
            "ts": time.time(), "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "topic": topic, "chars": len(body), "text": body[:4000],
        })

    # ---------------------------------------------------------- 生命周期
    def start(self, interval_s=1800):
        """起后台学习线程（daemon）。已在跑返回 False（幂等）。

        **第一轮等一个周期再跑**，不是立刻跑：启动瞬间往往是用户刚打开小焦、
        正要提问的时候 —— 这时候去联网学习，会跟用户的第一条消息抢带宽和模型额度。
        等一个周期（默认半小时）再动，用户完全没有感知。
        """
        try:
            interval_s = max(60.0, float(interval_s))
        except (TypeError, ValueError):
            interval_s = 1800.0
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, args=(interval_s,),
                                            name="autonomy-learner", daemon=True)
            self._thread.start()
            return True

    def _loop(self, interval_s):
        """学习循环。整个循环体包 try —— 后台线程死了没人会发现，绝不能让它死。"""
        while not self._stop.is_set():
            if self._stop.wait(interval_s):
                break
            try:
                self.cycle()
            except Exception as e:      # noqa: silent-ok — cycle 内部已经兜了一层，这里是双保险
                _log("学习者：循环异常（已忽略继续跑）：%s" % e,
                     os.path.join(self.state_dir, "autonomy.log"))

    def stop(self, timeout=3):
        """优雅停止（有界等待，绝不把主线程挂住）。返回线程是否真的退出了。"""
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

    @property
    def stats(self):
        """累计统计（给界面/自检看）：跑了多少轮、一共学进去多少条。"""
        return {"rounds": self.rounds, "learned_total": self.learned_total,
                "state_dir": self.state_dir}
