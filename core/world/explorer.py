# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 世界层 · 自主探索器（autonomous explorer）

【一句话定位】互联网不是小焦的工具箱，是它的**世界**。它不该"用户问了才看"，
而是**一直在啃互联网** —— 即使没人问，它也在看、在学、在记、在想、在长。

【为什么必须有这一层（而不是只有 perception）】
`perception.py` 解决的是"怎么看清一页"（抓→存→比）；它**不会自己决定看什么**。
没有探索器，世界层就只是一个"用户点一下才动一下"的抓取器 ——
用户要的"活着"就无从谈起（他说得很清楚：**用户不说 → 也在做事，这是它活着的证据**）。

【五步闭环（对应"推理 → RAG → 匹对 → 吸收 → 存脑"）】
  ① **推理** `infer_topics()`   ：判断"什么值得看"（从对话历史 + 世界模型 + 变化记录推）
  ② **RAG**  `_rag()`          ：自己去检索（不等用户问）
  ③ **匹对** `_match()`        ：跟用户画像/已有记忆对 —— 相关留、不相关丢、冲突标记
  ④ **校验** `_verify()`       ：多源交叉 + 时间检验 + 可信度评分
  ⑤ **吸收** `_absorb()`       ：过污染防火墙 → 写 memory_vec + 更新世界地图
每一步都会把**证据**写进返回值和 `logs/world/exploration.jsonl`，
这样"它到底探过什么、为什么吸收/丢弃"随时可复盘 —— 而不是只能看到一个总数。

【节律（它自己的作息）】
  · 空闲（用户 5 分钟没说话）才开始啃 —— **不跟用户抢资源、不打扰**
  · 白天探索 + 记录；夜里整理（压缩/去重/建索引，**只写不删**）
  · 每小时自检一次；每天 3 点做一轮全面探索
  · 速度可配（slow/normal/fast），默认 **slow**：抓取之间有硬间隔，
    **宁可慢，也不能把别人的站当靶子打**（这是身体边界的一部分）。

【去掉它会怎样】世界层退化成"被动抓取器"，`world/model.json` 永远只有用户手动抓过的那几个站，
`absorption.jsonl` 永远是空的 —— "自主性"这个词在这套系统里就没有落点。
"""
import json
import os
import random
import re
import sys
import threading
import time

try:
    from .model import WorldModel, parse_interval
    from .perception import WorldPerception
except Exception:                       # noqa: BLE001 — 允许作为脚本直接跑
    from model import WorldModel, parse_interval          # type: ignore
    from perception import WorldPerception                # type: ignore

logger = None
try:
    import logging
    logger = logging.getLogger(__name__)
except Exception:                       # noqa: BLE001
    pass


def _log(msg, *a):
    if logger is not None:
        try:
            logger.info(msg, *a)
            return
        except Exception:               # noqa: BLE001
            pass


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORLD_DIR = os.path.join(_REPO_ROOT, "logs", "world")
CONTROL_FILE = os.path.join(_REPO_ROOT, "xiaojiao_control.json")

# 探索速度 → (两次抓取之间的最小间隔秒数, 单轮最多看几个站)
# 为什么默认 slow：探索是**无人监督的自动抓取**，抓得太勤等于对别人的服务器做压力测试。
# 世界层要长期跑下去（它是"一直活着"的那部分），所以体面比速度重要。
SPEEDS = {"slow": (10.0, 3), "normal": (3.0, 6), "fast": (0.5, 12)}

DEFAULT_CFG = {
    "explore_enabled": True,
    "daily_budget": 50,             # 每天最多看多少个站（硬上限，防跑飞）
    "topic_interests": [],          # 用户关心的方向（给推理层当先验）
    "forbidden_sites": [],          # 身体边界：这些域一律不看
    "min_trust_to_remember": 0.5,   # 低于这个可信度的站：只记录，不写主记忆
    "explore_speed": "slow",
    "idle_seconds": 300,            # 用户 5 分钟没说话才开啃
    "daily_full_explore_hour": 3,
}

# 停用词：从话题里滤掉没有信息量的高频虚词（与世界层/续写同一套口径思路）
_STOP = set("的 了 是 在 和 与 也 都 就 而 被 把 对 从 到 着 过 呢 吗 吧 啊 呀 哦 嗯 我 你 他 她 它 们 这 那 什么 怎么 因为 所以 但是 而且 如果 帮我 请你 一下 怎么 如何 是什么 有没有 可以 能否 介绍 说说 讲讲".split())


def _cfg(override=None):
    """配置：默认值 ← xiaojiao_control.json 的 world 段 ← 显式 override。**绝不抛**。"""
    merged = dict(DEFAULT_CFG)
    try:
        if os.path.exists(CONTROL_FILE):
            with open(CONTROL_FILE, "r", encoding="utf-8", errors="replace") as f:
                raw = json.load(f) or {}
            if isinstance(raw, dict) and isinstance(raw.get("world"), dict):
                merged.update(raw["world"])
    except Exception:                   # noqa: BLE001 — 配置坏了用默认值，不能让探索起不来
        pass
    if isinstance(override, dict):
        merged.update(override)
    return merged


def _app():
    """惰性拿宿主模块（不主动 import：那会把整个应用连带模型一起初始化）。"""
    m = sys.modules.get("xiaojiao_app")
    if m is None:
        m = sys.modules.get("__main__")
        if m is not None and not hasattr(m, "agent_run"):
            m = None
    return m


def _append(path, obj):
    """追加一行 JSON（append-only，**从不删改**）。"""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        return True
    except Exception:                   # noqa: BLE001 — 记不上日志不能中断探索
        return False


def default_topics():
    """没有历史可依据时的兜底话题（保证"没人问也在做事"有一条起跑线）。"""
    return ["人工智能", "开源项目", "科技新闻"]


class WorldExplorer:
    """自己决定探索什么、自己去搜、自己判断、自己吸收。"""

    def __init__(self, model=None, perception=None, judge=None, firewall=None,
                 history_getter=None, searcher=None, storer=None, state_dir=None,
                 cfg=None):
        self.cfg = _cfg(cfg)
        self.state_dir = state_dir or WORLD_DIR
        try:
            os.makedirs(self.state_dir, exist_ok=True)
        except Exception:               # noqa: BLE001 — 建不了目录后面写入点还会兜
            pass
        self.model = model if model is not None else WorldModel(os.path.join(self.state_dir, "model.json"))
        self.perception = perception if perception is not None else WorldPerception(model=self.model)
        self._judge = judge
        self._firewall = firewall
        self._history_getter = history_getter
        self._searcher = searcher
        self._storer = storer
        self.log_path = os.path.join(self.state_dir, "exploration.jsonl")
        self.absorb_path = os.path.join(self.state_dir, "absorption.jsonl")
        self.conflict_path = os.path.join(self.state_dir, "conflicts.jsonl")
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._last_touch = time.time()
        self._last_fetch = 0.0
        self._today = {"date": time.strftime("%Y-%m-%d"), "explored": 0, "absorbed": 0,
                       "quarantined": 0, "discarded": 0, "conflicts": 0}
        self._load_state()

    # ---------------- 状态 ----------------
    def _state_path(self):
        return os.path.join(self.state_dir, "explorer_state.json")

    def _load_state(self):
        try:
            with open(self._state_path(), "r", encoding="utf-8") as f:
                d = json.load(f) or {}
            if d.get("date") == time.strftime("%Y-%m-%d"):
                self._today.update(d)
        except Exception:               # noqa: BLE001 — 状态坏了就当今天还没探
            pass

    def _save_state(self):
        try:
            with open(self._state_path(), "w", encoding="utf-8") as f:
                json.dump(self._today, f, ensure_ascii=False, indent=2)
        except Exception:               # noqa: BLE001 — 存不上只是重启后预算重置，不致命
            pass

    def _roll_day(self):
        today = time.strftime("%Y-%m-%d")
        if self._today.get("date") != today:
            self._today = {"date": today, "explored": 0, "absorbed": 0, "quarantined": 0,
                           "discarded": 0, "conflicts": 0}
            self._save_state()

    def touch(self):
        """用户有交互 → 重置空闲计时（空闲任务靠它判断"用户闲下来了没"）。"""
        self._last_touch = time.time()

    def idle_seconds(self):
        return max(0.0, time.time() - self._last_touch)

    def status(self):
        self._roll_day()
        budget = int(self.cfg.get("daily_budget") or 50)
        return {"enabled": bool(self.cfg.get("explore_enabled")),
                "idle_seconds": round(self.idle_seconds(), 1),
                "today": dict(self._today),
                "budget": budget,
                "budget_left": max(0, budget - int(self._today.get("explored") or 0)),
                "speed": self.cfg.get("explore_speed"),
                "model_sites": len(self.model.snapshot().get("sites") or {}),
                # topics() 返回的是 [{name, weight, ...}]；这里只取名字。
                # 兼容处理是**故意的**：世界模型以后若改成 [(name, w)] 这种形状，
                # 探索器的状态面板不该因此直接 KeyError（那是"看板把主流程带崩"）
                "topics": [self._topic_name(t) for t in (self.model.topics(top=5) or [])]}

    @staticmethod
    def _topic_name(t):
        """从 topics() 的一项里取名字（dict / tuple / str 都吃）。"""
        if isinstance(t, dict):
            return str(t.get("name") or "")
        if isinstance(t, (list, tuple)) and t:
            return str(t[0])
        return str(t or "")

    @staticmethod
    def _topic_weight(t):
        """从 topics() 的一项里取权重（取不到按 1 算）。"""
        try:
            if isinstance(t, dict):
                return int(t.get("weight") or t.get("hits") or 1)
            if isinstance(t, (list, tuple)) and len(t) > 1:
                return int(t[1] or 1)
        except Exception:               # noqa: BLE001 — 权重坏掉按 1 算，不影响话题本身
            pass
        return 1

    # ---------------- 依赖（惰性、缺了就降级） ----------------
    def _history(self):
        if callable(self._history_getter):
            try:
                return self._history_getter() or []
            except Exception:           # noqa: BLE001 — 取不到历史就不推话题
                return []
        app = _app()
        if app is None:
            return []
        try:
            return app.current_messages() or []
        except Exception:               # noqa: BLE001
            return []

    def _search(self, q, n=5):
        if callable(self._searcher):
            try:
                return self._searcher(q, n) or []
            except Exception:           # noqa: BLE001 — 搜不到就当这一轮没结果
                return []
        app = _app()
        if app is None:
            return []
        try:
            res = app.web_search(q, num=n) or []
            return [(t, u, c) for (t, u, c) in res][:n]
        except Exception:               # noqa: BLE001
            return []

    def _store(self, text, meta=None):
        if callable(self._storer):
            try:
                return bool(self._storer(text, meta or {}))
            except Exception:           # noqa: BLE001
                return False
        try:
            from .. import memory_vec as _mv
            _mv.add_memory(text, kind="fact", key_text=(meta or {}).get("key_text") or text[:60],
                           entities=(meta or {}).get("entities") or [])
            return True
        except Exception:               # noqa: BLE001 — 记忆库不可用就退回本层 JSONL
            return _append(os.path.join(self.state_dir, "knowledge.jsonl"),
                           {"ts": time.time(), "text": text[:500], "meta": meta or {}})

    def _judge_mod(self):
        if self._judge is not None:
            return self._judge
        try:
            from .judge import SiteJudge
            self._judge = SiteJudge(model=self.model)
        except Exception:               # noqa: BLE001 — 判断器不可用就用世界模型自带规则
            self._judge = None
        return self._judge

    def _fw(self):
        if self._firewall is not None:
            return self._firewall
        try:
            from .firewall import PollutionFirewall
            self._firewall = PollutionFirewall(model=self.model)
        except Exception:               # noqa: BLE001 — 防火墙不可用 = 只剩世界模型的可信度闸
            self._firewall = None
        return self._firewall

    # ---------------- ① 推理：什么值得看 ----------------
    def infer_topics(self, limit=8):
        """从对话历史 + 世界模型主题 + 用户关注方向，推出"值得看的几件事"。

        为什么先看对话历史：用户真正关心什么，**他自己说的话最准**（这是全系统的第一原则：
        用户的话 > 互联网信息）。世界模型里的主题只作为"我最近在看的"补充。
        """
        counts = {}
        for m in (self._history() or [])[-80:]:
            try:
                txt = str((m or {}).get("content") or "")
            except Exception:           # noqa: BLE001
                continue
            for w in re.findall(r"[\u4e00-\u9fff]{2,6}|[A-Za-z]{3,}", txt):
                if w in _STOP or len(w) < 2:
                    continue
                counts[w] = counts.get(w, 0) + 1
        # 注意这里必须用 `_topic_name(t)` 而不是 `t`：topics() 的一项是个 dict，
        # 直接拿来当字典的键会 `TypeError: unhashable type: 'dict'`（实测踩到）。
        for name, w in ((self._topic_name(t), self._topic_weight(t))
                        for t in (self.model.topics(top=10) or [])):
            if not name:
                continue
            counts[name] = counts.get(name, 0) + int(w or 1)
        for name in (self.cfg.get("topic_interests") or []):
            counts[str(name)] = counts.get(str(name), 0) + 3
        out = [k for k, _ in sorted(counts.items(), key=lambda x: -x[1])[:limit]]
        return out or default_topics()

    def plan(self, limit=5):
        """今天打算探什么：话题 → 查询词。**可预测**（单测据此断言）。"""
        limit = max(1, min(int(limit or 5), 20))
        topics = self.infer_topics(limit=limit)
        seen = {s for s in (self.model.snapshot().get("sites") or {})}
        plans = []
        for t in topics:
            plans.append({"topic": t, "query": "%s 最新" % t, "why": "对话里出现过 / 你在关注",
                          "known_sites": len(seen)})
            if len(plans) >= limit:
                break
        return plans

    # ---------------- 五步闭环 ----------------
    def _forbidden(self, url):
        """这个地址能不能碰：用户配的禁区名单 + **真正进了黑名单**的站。

        【分寸（本轮实测踩到）】防火墙对"一次污染"只是**降权**（level 1），
        用户的口径写得很清楚：一次降权 / 两次降更多 / **三次才进黑名单**。
        第一版这里只要 `is_blacklisted()` 为真就不碰 —— 于是一个页面**没有发布时间戳**
        （soft 类 `stale`，绝大多数页面都没有）就把它整站拉黑，
        世界层从此再也吸收不到这个站的任何东西。**免疫系统不能变成"看谁都不干净"。**
        所以这里要求 level ≥ 3（真正拉黑）才算禁区；1~2 级只降权、照样能看。
        """
        dom = self.model.domain_of(url) or ""
        for bad in (self.cfg.get("forbidden_sites") or []):
            b = str(bad).strip().lower().lstrip(".")
            if b and (dom == b or dom.endswith("." + b)):
                return True
        fw = self._fw()
        try:
            if fw is None:
                return False
            bl = fw.blacklist() or {}
            rec = ((bl.get("sites") or {}).get(dom) or {})
            if int(rec.get("level") or 0) >= 3 and rec.get("active", True):
                return True
        except Exception:               # noqa: BLE001 — 黑名单查不动就当没命中
            pass
        return False

    def _rag(self, plan, n=5):
        """② RAG：自己去检索（不等用户问）。返回候选 [{title,url,snippet}]。"""
        q = plan.get("query") or plan.get("topic") or ""
        raw = self._search(q, n)
        out = []
        for item in raw or []:
            try:
                t, u, c = (list(item) + ["", "", ""])[:3]
            except Exception:           # noqa: BLE001
                continue
            u = str(u or "").strip()
            if not u.startswith(("http://", "https://")):
                continue
            if self._forbidden(u):
                out.append({"title": str(t), "url": u, "snippet": str(c), "skipped": "在禁区名单里"})
                continue
            out.append({"title": str(t), "url": u, "snippet": str(c), "skipped": ""})
        return out

    def _match(self, cand, plan, profile=None):
        """③ 匹对：跟用户画像/已有记忆对 —— 相关留、不相关丢、冲突标记。"""
        keys = self._profile_keys(profile)
        text = ("%s %s %s" % (cand.get("title"), cand.get("snippet"), plan.get("topic"))).lower()
        hit = sum(1 for k in keys if k and k.lower() in text)
        rel = min(1.0, 0.35 + 0.22 * hit) if keys else 0.5
        if not keys:
            return {"action": "keep", "relevance": rel, "why": "还没有画像，先按默认相关度保留"}
        if rel < 0.4:
            return {"action": "drop", "relevance": rel, "why": "与你的关注点重合度太低（%.2f）" % rel}
        # 冲突检查：跟已吸收的知识直接矛盾 → 标记，**不擅自改记忆**（用户的话 > 互联网）
        conflict = self._conflict_of(cand)
        if conflict:
            return {"action": "conflict", "relevance": rel, "conflict": conflict,
                    "why": "与已有记忆冲突，标为待确认"}
        return {"action": "keep", "relevance": rel, "why": "与你的关注点相关（%.2f）" % rel}

    def _profile_keys(self, profile=None):
        p = profile if isinstance(profile, dict) else (self.model.user_profile() or {})
        keys = []
        for v in (p or {}).values():
            if isinstance(v, str):
                keys.append(v)
            elif isinstance(v, (list, tuple)):
                keys.extend([str(x) for x in v if isinstance(x, str)])
        keys.extend(str(x) for x in (self.cfg.get("topic_interests") or []))
        return [k for k in keys if k][:30]

    def _conflict_of(self, cand):
        """跟已吸收的条目做一次朴素矛盾检查（有否定词差异就算冲突）。"""
        try:
            p = self.absorb_path
            if not os.path.exists(p):
                return ""
            text = ("%s %s" % (cand.get("title"), cand.get("snippet"))).lower()
            neg_new = any(w in text for w in ("不是", "并非", "否认", "辟谣", "假的", "not ", "no "))
            with open(p, encoding="utf-8", errors="ignore") as f:
                for line in list(f)[-60:]:
                    try:
                        r = json.loads(line)
                    except Exception:   # noqa: BLE001 — 半截行跳过
                        continue
                    old = str(r.get("text") or "")[:200].lower()
                    if not old:
                        continue
                    neg_old = any(w in old for w in ("不是", "并非", "否认", "辟谣", "假的"))
                    if neg_new != neg_old and len(set(old[:40]) & set(text[:40])) >= 12:
                        return "已有记忆：%s" % old[:60]
        except Exception:               # noqa: BLE001 — 查不了冲突就不标
            pass
        return ""

    def _verify(self, cand, sources=None):
        """④ 校验：多源交叉 + 时间检验 + 可信度评分。"""
        srcs = sources or []
        same = 0
        dom = self.model.domain_of(cand.get("url") or "")
        for s in srcs:
            try:
                if self.model.domain_of(s.get("url") or "") != dom:
                    same += 1
            except Exception:           # noqa: BLE001
                continue
        score = 0.45
        if same >= 2:
            score += 0.25
            verdict = "多源一致（%d 个独立来源）" % same
        elif same == 1:
            score += 0.1
            verdict = "单源（未验证）"
        else:
            verdict = "只有这一个来源（未验证）"
        j = self._judge_mod()
        if j is not None:
            try:
                jd = j.judge(cand.get("url") or "", content=cand.get("snippet") or "",
                             title=cand.get("title") or "")
                score = max(0.0, min(1.0, (score + float(getattr(jd, "judged_trust", 0.5))) / 2.0))
                verdict += "；站点判断：%s/%s" % (getattr(jd, "judged_type", "?"),
                                                getattr(jd, "quality", "?"))
            except Exception:           # noqa: BLE001 — 判断器出错就用规则分
                pass
        return {"score": round(score, 3), "verified": same >= 2, "verdict": verdict,
                "independent_sources": same}

    def _absorb(self, cand, plan, match, verify):
        """⑤ 吸收：过污染防火墙 → 写记忆 + 更新世界地图。返回可复盘的吸收记录。"""
        url = cand.get("url") or ""
        dom = self.model.domain_of(url)
        body = cand.get("snippet") or cand.get("title") or ""
        min_trust = float(self.cfg.get("min_trust_to_remember") or 0.5)
        fw = self._fw()
        screen = None
        if fw is not None:
            try:
                screen = fw.screen(url, body, title=cand.get("title") or "",
                                   topic=plan.get("topic") or "",
                                   profile=self.model.user_profile() or {})
            except Exception as e:      # noqa: BLE001 — 防火墙出错 → 按最保守处理（不吸收）
                screen = None
                _log("世界探索：防火墙筛查失败，本轮按不吸收处理：%s", e)
        decision = getattr(screen, "decision", "") if screen is not None else ""
        score = getattr(screen, "score", verify.get("score")) if screen is not None else verify.get("score")
        clean = getattr(screen, "clean_text", body) if screen is not None else body
        classes = list(getattr(screen, "classes", []) or []) if screen is not None else []

        rec = {"ts": time.time(), "iso": time.strftime("%Y-%m-%d %H:%M:%S"),
               "url": url, "domain": dom, "topic": plan.get("topic"),
               "title": cand.get("title"), "text": (clean or "")[:400],
               "score": score, "matched": match, "verify": verify,
               "classes": classes, "firewall": decision or "skipped",
               "absorbed": False, "why": ""}
        # 身体边界 + 可信度闸：可信度不够的站**不写主记忆**（只在地图里留个记录）
        if not dom:
            rec["why"] = "域名解不出来"
        elif self._forbidden(url):
            rec["why"] = "在禁区名单里"
        elif decision in ("quarantine", "discard"):
            rec["why"] = "污染防火墙拦下（%s）" % ("、".join(classes) or decision)
        elif float(score or 0) < min_trust:
            rec["why"] = "可信度 %.2f 低于门槛 %.2f，只记录不吸收" % (float(score or 0), min_trust)
        elif match.get("action") == "conflict":
            rec["why"] = "与已有记忆冲突，标为待确认（用户的话 > 互联网）"
            _append(self.conflict_path, {"ts": time.time(), "url": url, "topic": plan.get("topic"),
                                         "why": match.get("conflict"), "kept_old": True})
            self._today["conflicts"] = int(self._today.get("conflicts") or 0) + 1
        else:
            ok = self._store("【%s】%s" % (plan.get("topic") or "世界", rec["text"]),
                             {"key_text": "%s %s" % (plan.get("topic"), cand.get("title")),
                              "entities": [dom], "source": url, "score": score})
            rec["absorbed"] = bool(ok)
            rec["why"] = "已吸收进长期记忆" if ok else "写记忆失败（已留档）"
        # 无论吸不吸收，世界地图都要更新 —— "我看过这个站"本身就是事实
        try:
            self.model.remember_site(url, title=cand.get("title") or "")
            self.model.mark_seen(url)
            j = self._judge_mod()
            if j is not None:
                try:
                    jd = j.judge(url, content=body, title=cand.get("title") or "")
                    self.model.remember_judgment(url, jd)
                except Exception:       # noqa: BLE001 — 判断失败不影响"记下我见过它"
                    pass
            if plan.get("topic"):
                self.model.remember_topic(plan["topic"], 1, source="explore")
        except Exception as e:          # noqa: BLE001 — 地图写失败不能把整轮探索带崩
            _log("世界探索：更新世界模型失败：%s", e)
        _append(self.absorb_path, rec)
        self._today["absorbed" if rec["absorbed"] else
                   ("quarantined" if decision == "quarantine" else "discarded")] = \
            int(self._today.get("absorbed" if rec["absorbed"] else
                                ("quarantined" if decision == "quarantine" else "discarded")) or 0) + 1
        return rec

    def explore_once(self, topic=None):
        """走完五步，返回**每一步的证据**（可复盘：它凭什么吸收/丢弃了这一条）。"""
        self._roll_day()
        budget = int(self.cfg.get("daily_budget") or 50)
        if int(self._today.get("explored") or 0) >= budget:
            return {"ok": False, "why": "今天已经看够 %d 个站（daily_budget）" % budget,
                    "steps": {}}
        plans = self.plan(limit=3)
        plan = None
        if topic:
            plan = {"topic": topic, "query": "%s 最新" % topic, "why": "手动指定"}
        elif plans:
            plan = random.choice(plans)
        if not plan:
            return {"ok": False, "why": "推不出值得看的话题", "steps": {}}

        steps = {"infer": {"topic": plan.get("topic"), "why": plan.get("why"),
                           "candidates": [p.get("topic") for p in plans]}}
        cands = self._rag(plan)
        steps["rag"] = {"query": plan.get("query"), "found": len(cands),
                        "urls": [c.get("url") for c in cands[:5]]}
        usable = [c for c in cands if not c.get("skipped")]
        if not usable:
            steps["match"] = {"action": "drop", "why": "没搜到可用候选（或全在禁区里）"}
            _append(self.log_path, {"ts": time.time(), "topic": plan.get("topic"), "steps": steps,
                                    "ok": False})
            return {"ok": False, "why": "没搜到可用候选", "plan": plan, "steps": steps}
        cand = usable[0]
        profile = self.model.user_profile() or {}
        match = self._match(cand, plan, profile)
        steps["match"] = match
        if match.get("action") == "drop":
            self._today["discarded"] = int(self._today.get("discarded") or 0) + 1
            _append(self.log_path, {"ts": time.time(), "topic": plan.get("topic"), "steps": steps,
                                    "ok": False})
            return {"ok": False, "why": match.get("why"), "plan": plan, "candidate": cand,
                    "steps": steps}
        verify = self._verify(cand, sources=usable)
        steps["verify"] = verify
        rec = self._absorb(cand, plan, match, verify)
        steps["absorb"] = {"absorbed": rec["absorbed"], "why": rec["why"],
                           "firewall": rec["firewall"], "classes": rec["classes"]}
        self._today["explored"] = int(self._today.get("explored") or 0) + 1
        self._save_state()
        _append(self.log_path, {"ts": time.time(), "topic": plan.get("topic"), "steps": steps,
                                "ok": True})
        return {"ok": True, "plan": plan, "candidate": cand, "steps": steps, "record": rec}

    def cycle(self, budget=None):
        """一轮探索：按 speed 决定看几个站，**每次抓取之间有硬间隔**（不打扰站点）。"""
        self._roll_day()
        speed = str(self.cfg.get("explore_speed") or "slow").lower()
        gap, per_round = SPEEDS.get(speed, SPEEDS["slow"])
        left = int(self.cfg.get("daily_budget") or 50) - int(self._today.get("explored") or 0)
        n = max(0, min(int(budget or per_round), left))
        out = []
        for _ in range(n):
            if self._stop.is_set():
                break
            wait = gap - (time.time() - self._last_fetch)
            if wait > 0:
                self._stop.wait(min(wait, gap))     # 可被 stop 打断的等待
            self._last_fetch = time.time()
            try:
                out.append(self.explore_once())
            except Exception as e:      # noqa: BLE001 — 一轮失败不能把整个循环带崩
                out.append({"ok": False, "why": "探索出错：%s" % str(e)[:120], "steps": {}})
        ok = sum(1 for r in out if r.get("ok"))
        return {"round": len(out), "ok": ok, "results": out, "status": self.status()}

    # ---------------- 节律 ----------------
    def organize(self):
        """夜里的整理：压缩 + 去重 + 建索引。**只写不删**（红线）。

        为什么不能删：吸收流水是"我为什么信这条"的唯一证据，删了就再也解释不清。
        所以整理只做两件事：把重复的**标出来**（不改原文），再写一份索引供快速检索。
        """
        try:
            rows = []
            with open(self.absorb_path, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except Exception:   # noqa: BLE001 — 半截行跳过
                        continue
            seen, dup = {}, 0
            for r in rows:
                k = (r.get("domain") or "") + "|" + (r.get("title") or "")[:40]
                if k in seen:
                    dup += 1
                seen[k] = seen.get(k, 0) + 1
            idx = {"ts": time.time(), "total": len(rows), "unique": len(seen), "dups": dup,
                   "by_domain": {}}
            for r in rows:
                d = r.get("domain") or "?"
                idx["by_domain"][d] = idx["by_domain"].get(d, 0) + 1
            _append(os.path.join(self.state_dir, "index.jsonl"), idx)
            return idx
        except Exception as e:          # noqa: BLE001 — 整理失败不影响探索
            return {"error": str(e)[:120]}

    def self_check(self):
        """每小时自检：世界层还活着吗？预算/线程/落盘正常吗？"""
        st = self.status()
        rep = {"ts": time.time(), "status": st,
               "writable": _append(os.path.join(self.state_dir, "heartbeat.jsonl"),
                                   {"ts": time.time()})}
        _append(os.path.join(self.state_dir, "selfcheck.jsonl"), rep)
        return rep

    def full_explore(self):
        """每天 3 点：一轮全面探索 + 更新世界模型。"""
        st = self.status()
        res = self.cycle(budget=SPEEDS.get(str(self.cfg.get("explore_speed")), SPEEDS["slow"])[1])
        try:
            dec = self.model.decay_unused()
        except Exception:               # noqa: BLE001 — 降权失败不影响探索结果
            dec = 0
        rep = {"ts": time.time(), "kind": "full_explore", "explored": res.get("ok"),
               "decayed": dec, "status": st}
        _append(os.path.join(self.state_dir, "full_explore.jsonl"), rep)
        return rep

    def should_explore_now(self):
        """现在该不该开啃：开关开着 + 用户空闲够久 + 今天还有预算。"""
        self._roll_day()
        if not self.cfg.get("explore_enabled"):
            return False, "explore_enabled=false"
        if self.idle_seconds() < float(self.cfg.get("idle_seconds") or 300):
            return False, "用户还在用（空闲 %.0fs < %.0fs）" % (
                self.idle_seconds(), float(self.cfg.get("idle_seconds") or 300))
        if int(self._today.get("explored") or 0) >= int(self.cfg.get("daily_budget") or 50):
            return False, "今天预算已用完"
        return True, "空闲且还有预算"

    def _loop(self, poll_s=60):
        last_hour = last_full = ""
        while not self._stop.wait(poll_s):
            try:
                self.touch() if False else None
                now = time.localtime()
                hour_key = time.strftime("%Y-%m-%d %H")
                if hour_key != last_hour:          # 每小时自检一次
                    last_hour = hour_key
                    self.self_check()
                day_key = time.strftime("%Y-%m-%d")
                if now.tm_hour == int(self.cfg.get("daily_full_explore_hour") or 3) and day_key != last_full:
                    last_full = day_key
                    self.full_explore()
                elif now.tm_hour in (1, 2, 4):     # 夜里做整理
                    self.organize()
                ok, _why = self.should_explore_now()
                if ok:
                    self.cycle()
            except Exception as e:      # noqa: BLE001 — 后台线程绝不能因为一次异常就死掉
                _log("世界探索后台循环出错（继续跑）：%s", e)

    def start(self, poll_s=60):
        if self._thread and self._thread.is_alive():
            return False
        self._stop.clear()
        # 不主动抢跑：起线程时把"用户刚交互过"当作起点（免得一启动就开啃）
        self._last_touch = time.time()
        self._thread = threading.Thread(target=self._loop, args=(poll_s,),
                                        name="xj-world-explorer", daemon=True)
        self._thread.start()
        _log("世界探索器已启动（speed=%s, idle=%ss, budget=%s/天）",
             self.cfg.get("explore_speed"), self.cfg.get("idle_seconds"),
             self.cfg.get("daily_budget"))
        return True

    def stop(self, timeout=3):
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=timeout)
        self._thread = None
        return True


# ---------------- 单例（进程内只跑一个探索器） ----------------
_SINGLETON = {"obj": None}
_SINGLETON_LOCK = threading.Lock()


def get_explorer(**kw):
    with _SINGLETON_LOCK:
        if _SINGLETON["obj"] is None:
            _SINGLETON["obj"] = WorldExplorer(**kw)
        return _SINGLETON["obj"]


def maybe_start(cfg=None, poll_s=60):
    """宿主启动时调：按配置决定要不要真的起来（默认**开**，因为这是"活着"的证据）。"""
    c = _cfg(cfg)
    if not c.get("explore_enabled"):
        return {"enabled": False, "reason": "explore_enabled=false"}
    ex = get_explorer(cfg=c)
    ex.start(poll_s=poll_s)
    return {"enabled": True, "status": ex.status()}


def stop_all(timeout=3):
    with _SINGLETON_LOCK:
        ex = _SINGLETON["obj"]
    if ex is not None:
        return ex.stop(timeout=timeout)
    return True


def touch():
    with _SINGLETON_LOCK:
        ex = _SINGLETON["obj"]
    if ex is not None:
        ex.touch()
